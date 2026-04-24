from __future__ import annotations

from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
import threading
from typing import Any

from app.core.config import config
from app.repositories.meetings import ArtifactRepository, ChunkRepository, MeetingRepository, RunRepository
from app.repositories.transcription import (
    ChunkTranscriptAttemptRepository,
    ChunkTranscriptRepository,
    JobRunRepository,
    TranscriptSegmentRepository,
    TranscriptWordRepository,
    TranscriptionRunRepository,
)
from app.services.artifacts.service import ArtifactService
from app.services.transcription.google_adapter import GoogleSpeechV2Adapter
from app.services.transcription.models import ChunkTranscriptionRequest, TranscriptSegment, TranscriptWord
from app.services.transcription.settings import TranscriptionSettingsService
from app.services.transcription.stitcher import TranscriptStitcher
from app.utils.files import ensure_directory, utc_now_iso, write_json


class TranscriptionJobService:
    def __init__(
        self,
        *,
        meeting_repository: MeetingRepository,
        run_repository: RunRepository,
        chunk_repository: ChunkRepository,
        artifact_repository: ArtifactRepository,
        job_run_repository: JobRunRepository,
        transcription_run_repository: TranscriptionRunRepository,
        chunk_transcript_repository: ChunkTranscriptRepository,
        chunk_transcript_attempt_repository: ChunkTranscriptAttemptRepository,
        transcript_segment_repository: TranscriptSegmentRepository,
        transcript_word_repository: TranscriptWordRepository,
        settings_service: TranscriptionSettingsService,
        adapter: GoogleSpeechV2Adapter,
        stitcher: TranscriptStitcher,
    ) -> None:
        self.meeting_repository = meeting_repository
        self.run_repository = run_repository
        self.chunk_repository = chunk_repository
        self.artifact_service = ArtifactService(artifact_repository)
        self.job_run_repository = job_run_repository
        self.transcription_run_repository = transcription_run_repository
        self.chunk_transcript_repository = chunk_transcript_repository
        self.chunk_transcript_attempt_repository = chunk_transcript_attempt_repository
        self.transcript_segment_repository = transcript_segment_repository
        self.transcript_word_repository = transcript_word_repository
        self.settings_service = settings_service
        self.adapter = adapter
        self.stitcher = stitcher
        self._tasks: dict[tuple[str, int], threading.Thread] = {}

    def enqueue(self, meeting_id: int) -> dict[str, int | str]:
        settings = self.settings_service.get()
        self.settings_service.validate(settings)
        self.adapter.validate_preflight(settings, validate_bucket_write=True)

        preprocessing_run = self.run_repository.get_latest_for_meeting(meeting_id)
        if not preprocessing_run or preprocessing_run["status"] != "completed":
            raise ValueError("Meeting does not have a completed preprocessing run")

        chunks = self.chunk_repository.list_for_run(int(preprocessing_run["id"]))
        if not chunks:
            raise ValueError("Meeting has no prepared chunks to transcribe")
        self._validate_chunk_files(chunks)

        job_run_id = self.job_run_repository.create(meeting_id, "transcribe", "Queued for transcription")
        transcription_run_id = self.transcription_run_repository.create(
            meeting_id=meeting_id,
            preprocessing_run_id=int(preprocessing_run["id"]),
            job_run_id=job_run_id,
            engine=self.adapter.engine_name,
            engine_model=settings.model,
            language_code=settings.language_code,
            diarization_enabled=settings.diarization_enabled,
            automatic_punctuation_enabled=settings.automatic_punctuation_enabled,
            chunk_count=len(chunks),
            config_json=self._settings_snapshot(settings),
        )
        self.meeting_repository.update_status(meeting_id, "transcribing")

        task = threading.Thread(
            target=self._run_pipeline,
            args=(meeting_id, transcription_run_id, job_run_id, chunks),
            daemon=True,
        )
        self._tasks[("run", transcription_run_id)] = task
        task.start()
        return {
            "job_run_id": job_run_id,
            "transcription_run_id": transcription_run_id,
            "status": "pending",
        }

    def retry_failed_chunks(self, transcription_run_id: int, *, chunk_ids: list[int] | None = None) -> dict[str, int | str | list[int]]:
        run = self.transcription_run_repository.get(transcription_run_id)
        if not run:
            raise ValueError("Transcription run not found")
        if run["status"] == "running":
            if self._has_active_task(transcription_run_id):
                raise ValueError("Transcription run is already active")
            self._recover_orphaned_run(run)
            run = self.transcription_run_repository.get(transcription_run_id)

        failed_rows = self.chunk_transcript_repository.list_failed_for_run(transcription_run_id)
        if chunk_ids:
            requested = {int(chunk_id) for chunk_id in chunk_ids}
            failed_rows = [row for row in failed_rows if int(row["chunk_id"]) in requested]
            invalid = requested.difference({int(row["chunk_id"]) for row in failed_rows})
            if invalid:
                raise ValueError("Retry requests may only target currently failed chunks")
        if not failed_rows:
            raise ValueError("Transcription run has no failed chunks to retry")
        self._validate_chunk_files(failed_rows)

        settings = self.settings_service.get()
        self.settings_service.validate(settings)
        self.adapter.validate_preflight(settings, validate_bucket_write=True)

        job_run_id = self.job_run_repository.create(run["meeting_id"], "transcribe", "Queued failed chunk retry")
        self.transcription_run_repository.attach_job_run(transcription_run_id, job_run_id)
        self.meeting_repository.update_status(run["meeting_id"], "transcribing")

        requests = [
            ChunkTranscriptionRequest(
                chunk_id=int(row["chunk_id"]),
                chunk_path=Path(row["file_path"]),
                chunk_index=int(row["chunk_index"]),
                start_ms=int(row["start_ms"]),
                end_ms=int(row["end_ms"]),
                overlap_before_ms=int(row["overlap_before_ms"]),
                overlap_after_ms=int(row["overlap_after_ms"]),
            )
            for row in failed_rows
        ]
        task = threading.Thread(
            target=self._retry_pipeline,
            args=(run["meeting_id"], transcription_run_id, job_run_id, requests),
            daemon=True,
        )
        self._tasks[("retry", transcription_run_id)] = task
        task.start()
        return {
            "job_run_id": job_run_id,
            "transcription_run_id": transcription_run_id,
            "status": "running",
            "retried_chunk_ids": [request.chunk_id for request in requests],
        }

    def _run_pipeline(
        self,
        meeting_id: int,
        transcription_run_id: int,
        job_run_id: int,
        chunks: list[dict[str, Any]],
    ) -> None:
        settings = self.settings_service.get()
        try:
            prior_status = "pending"
            self.transcription_run_repository.mark_running(transcription_run_id)
            self._set_job_state(job_run_id, "running", "transcribing_chunks", 8, "Transcribing chunks with Google Speech-to-Text")
            requests = [self._request_from_chunk(chunk) for chunk in chunks]
            result = self._transcribe_requests(
                meeting_id=meeting_id,
                transcription_run_id=transcription_run_id,
                job_run_id=job_run_id,
                settings=settings,
                requests=requests,
                progress_offset=10,
                progress_span=65,
                progress_label="Processed {processed} of {total} chunks",
            )
            self._finalize_run(
                meeting_id=meeting_id,
                transcription_run_id=transcription_run_id,
                job_run_id=job_run_id,
                chunk_rows=chunks,
                chunk_segment_map=result["chunk_segment_map"],
                confidence_values=result["confidence_values"],
                prior_status=prior_status,
            )
        except Exception as exc:  # noqa: BLE001
            self._fail_run(meeting_id=meeting_id, transcription_run_id=transcription_run_id, job_run_id=job_run_id, error_message=str(exc))

    def _retry_pipeline(
        self,
        meeting_id: int,
        transcription_run_id: int,
        job_run_id: int,
        requests: list[ChunkTranscriptionRequest],
    ) -> None:
        settings = self.settings_service.get()
        try:
            prior_status = str(self.transcription_run_repository.get(transcription_run_id)["status"])
            self.transcription_run_repository.mark_running(transcription_run_id)
            self._set_job_state(job_run_id, "running", "transcribing_chunks", 12, "Retrying failed chunks with Google Speech-to-Text")

            chunk_rows = self.chunk_repository.list_for_meeting(meeting_id)
            chunk_map = {int(chunk["id"]): chunk for chunk in chunk_rows}
            persisted_map = self._load_persisted_chunk_segment_map(transcription_run_id)
            result = self._transcribe_requests(
                meeting_id=meeting_id,
                transcription_run_id=transcription_run_id,
                job_run_id=job_run_id,
                settings=settings,
                requests=requests,
                progress_offset=18,
                progress_span=42,
                progress_label="Retried {processed} of {total} failed chunks",
            )
            persisted_map.update(result["chunk_segment_map"])

            successful_chunk_rows = [chunk_map[chunk_id] for chunk_id in sorted(persisted_map) if chunk_id in chunk_map]
            self._finalize_run(
                meeting_id=meeting_id,
                transcription_run_id=transcription_run_id,
                job_run_id=job_run_id,
                chunk_rows=successful_chunk_rows,
                chunk_segment_map=persisted_map,
                confidence_values=self._confidence_values_for_run(transcription_run_id),
                prior_status=prior_status,
            )
        except Exception as exc:  # noqa: BLE001
            self._fail_run(meeting_id=meeting_id, transcription_run_id=transcription_run_id, job_run_id=job_run_id, error_message=str(exc))

    def _transcribe_requests(
        self,
        *,
        meeting_id: int,
        transcription_run_id: int,
        job_run_id: int,
        settings,
        requests: list[ChunkTranscriptionRequest],
        progress_offset: float,
        progress_span: float,
        progress_label: str,
    ) -> dict[str, Any]:
        chunk_segment_map: dict[int, list[TranscriptSegment]] = {}
        confidence_values: list[float] = []
        processed_requests = 0
        if not requests:
            return {
                "chunk_segment_map": chunk_segment_map,
                "confidence_values": confidence_values,
            }

        with ThreadPoolExecutor(max_workers=settings.max_parallel_chunks) as executor:
            futures: dict[Future[Any], tuple[ChunkTranscriptionRequest, str]] = {
                executor.submit(
                    self.adapter.transcribe_chunk,
                    chunk=request,
                    settings=settings,
                    meeting_id=meeting_id,
                    run_id=transcription_run_id,
                ): (request, utc_now_iso())
                for request in requests
            }
            for future in as_completed(futures):
                request, started_at = futures[future]
                self._persist_chunk_result(
                    request=request,
                    meeting_id=meeting_id,
                    transcription_run_id=transcription_run_id,
                    settings=settings,
                    future=future,
                    started_at=started_at,
                    chunk_segment_map=chunk_segment_map,
                    confidence_values=confidence_values,
                )
                current_rows = self.chunk_transcript_repository.list_for_run(transcription_run_id)
                completed_count = len([item for item in current_rows if item["status"] == "completed"])
                failed_count = len([item for item in current_rows if item["status"] == "failed"])
                self.transcription_run_repository.update_progress(
                    transcription_run_id,
                    completed_chunk_count=completed_count,
                    failed_chunk_count=failed_count,
                )
                processed_requests += 1
                total = len(requests)
                progress = progress_offset + (processed_requests / max(1, total)) * progress_span
                self._set_job_state(
                    job_run_id,
                    "running",
                    "transcribing_chunks",
                    progress,
                    progress_label.format(processed=processed_requests, total=total),
                )

        return {
            "chunk_segment_map": chunk_segment_map,
            "confidence_values": confidence_values,
        }

    def _finalize_run(
        self,
        *,
        meeting_id: int,
        transcription_run_id: int,
        job_run_id: int,
        chunk_rows: list[dict[str, Any]],
        chunk_segment_map: dict[int, list[TranscriptSegment]],
        confidence_values: list[float],
        prior_status: str,
    ) -> None:
        current_rows = self.chunk_transcript_repository.list_for_run(transcription_run_id)
        completed_count = len([item for item in current_rows if item["status"] == "completed"])
        failed_rows = [item for item in current_rows if item["status"] == "failed"]
        failed_count = len(failed_rows)
        self.transcription_run_repository.update_progress(
            transcription_run_id,
            completed_chunk_count=completed_count,
            failed_chunk_count=failed_count,
        )
        if completed_count == 0:
            chunk_errors = [row["error_message"] for row in failed_rows if row.get("error_message")]
            detail = f": {' | '.join(chunk_errors[:2])}" if chunk_errors else ""
            raise RuntimeError(f"All chunk transcription requests failed{detail}")

        self._set_job_state(job_run_id, "running", "stitching", 84, "Stitching merged transcript")
        stitched = self.stitcher.stitch(
            meeting_id=meeting_id,
            transcription_run_id=transcription_run_id,
            chunk_rows=chunk_rows,
            chunk_segment_map=chunk_segment_map,
        )
        if not stitched["merged_segments"]:
            raise RuntimeError(
                "Transcript stitching completed but produced no merged transcript segments. Check chunk responses, credentials, and recognizer settings."
            )

        self.transcript_segment_repository.replace_for_run(transcription_run_id, "chunk_raw", stitched["raw_segments"])
        self.transcript_segment_repository.replace_for_run(transcription_run_id, "merged", stitched["merged_segments"])
        self.transcript_word_repository.replace_for_run(
            transcription_run_id,
            [{**word, "meeting_id": meeting_id} for word in stitched["raw_words"]],
        )

        average_confidence = round(sum(confidence_values) / len(confidence_values), 4) if confidence_values else None
        self._set_job_state(job_run_id, "running", "finalizing", 93, "Writing transcript artifacts")
        self._write_merged_artifacts(
            meeting_id=meeting_id,
            transcription_run_id=transcription_run_id,
            stitched=stitched,
            average_confidence=average_confidence,
            failed_chunk_count=failed_count,
            completed_chunk_count=completed_count,
        )

        run_status = self._resolve_success_status(previous_status=prior_status, failed_count=failed_count)
        message = self._success_message(run_status, failed_count, completed_count, len(current_rows))
        self.transcription_run_repository.finalize_success(
            transcription_run_id,
            status=run_status,
            average_confidence=average_confidence,
            error_message=(f"{failed_count} chunk(s) remain failed" if failed_count else None),
        )
        self.job_run_repository.finalize(
            job_run_id,
            status=run_status,
            stage="completed",
            current_message=message,
            error_message=None if failed_count == 0 else f"{failed_count} chunk(s) remain failed",
        )
        self.meeting_repository.update_status(meeting_id, "transcribed")

    def _fail_run(self, *, meeting_id: int, transcription_run_id: int, job_run_id: int, error_message: str) -> None:
        self.transcription_run_repository.finalize_failure(transcription_run_id, error_message=error_message)
        self.job_run_repository.finalize(
            job_run_id,
            status="failed",
            stage="failed",
            current_message=error_message,
            error_message=error_message,
        )
        self.meeting_repository.update_status(meeting_id, "failed")

    def _persist_chunk_result(
        self,
        *,
        request: ChunkTranscriptionRequest,
        meeting_id: int,
        transcription_run_id: int,
        settings,
        future: Future[Any],
        started_at: str,
        chunk_segment_map: dict[int, list[TranscriptSegment]],
        confidence_values: list[float],
    ) -> None:
        attempt_number = self.chunk_transcript_attempt_repository.next_attempt_number(transcription_run_id, request.chunk_id)
        previous_attempt = self.chunk_transcript_attempt_repository.get_latest_for_chunk(transcription_run_id, request.chunk_id)
        completed_at = utc_now_iso()
        try:
            result = future.result()
            chunk_transcript_id = self.chunk_transcript_repository.upsert(
                {
                    "meeting_id": meeting_id,
                    "chunk_id": request.chunk_id,
                    "transcription_run_id": transcription_run_id,
                    "engine": self.adapter.engine_name,
                    "engine_model": settings.model,
                    "status": "completed",
                    "transcript_text": result.transcript_text,
                    "raw_response_json": result.raw_response,
                    "average_confidence": result.average_confidence,
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "error_message": None,
                    "request_config_json": result.request_config,
                }
            )
            self.chunk_transcript_attempt_repository.create(
                {
                    "meeting_id": meeting_id,
                    "chunk_id": request.chunk_id,
                    "transcription_run_id": transcription_run_id,
                    "chunk_transcript_id": chunk_transcript_id,
                    "attempt_number": attempt_number,
                    "retried_from_attempt_id": previous_attempt["id"] if previous_attempt else None,
                    "engine": self.adapter.engine_name,
                    "engine_model": settings.model,
                    "status": "completed",
                    "transcript_text": result.transcript_text,
                    "raw_response_json": result.raw_response,
                    "average_confidence": result.average_confidence,
                    "started_at": started_at,
                    "completed_at": completed_at,
                    "error_message": None,
                    "request_config_json": result.request_config,
                }
            )
            chunk_segment_map[request.chunk_id] = result.segments
            if result.average_confidence is not None:
                confidence_values.append(result.average_confidence)
            self._write_raw_response_artifact(
                meeting_id=meeting_id,
                transcription_run_id=transcription_run_id,
                chunk_index=request.chunk_index,
                attempt_number=attempt_number,
                raw_response=result.raw_response,
            )
        except Exception as exc:  # noqa: BLE001
            payload = {
                "meeting_id": meeting_id,
                "chunk_id": request.chunk_id,
                "transcription_run_id": transcription_run_id,
                "engine": self.adapter.engine_name,
                "engine_model": settings.model,
                "status": "failed",
                "transcript_text": "",
                "raw_response_json": {"error": str(exc)},
                "average_confidence": None,
                "started_at": started_at,
                "completed_at": completed_at,
                "error_message": str(exc),
                "request_config_json": {
                    "model": settings.model,
                    "language_code": settings.language_code,
                },
            }
            chunk_transcript_id = self.chunk_transcript_repository.upsert(payload)
            self.chunk_transcript_attempt_repository.create(
                {
                    **payload,
                    "chunk_transcript_id": chunk_transcript_id,
                    "attempt_number": attempt_number,
                    "retried_from_attempt_id": previous_attempt["id"] if previous_attempt else None,
                }
            )

    def _set_job_state(self, job_run_id: int, status: str, stage: str, progress: float, message: str) -> None:
        self.job_run_repository.update_state(
            job_run_id,
            status=status,
            stage=stage,
            progress_percent=progress,
            current_message=message,
        )

    def _write_raw_response_artifact(
        self,
        *,
        meeting_id: int,
        transcription_run_id: int,
        chunk_index: int,
        attempt_number: int,
        raw_response: dict[str, Any],
    ) -> None:
        artifact_root = ensure_directory(config.artifacts_root / f"meeting_{meeting_id}" / f"transcription_{transcription_run_id}")
        raw_path = artifact_root / f"chunk_{chunk_index:03d}_attempt_{attempt_number:02d}_response.json"
        write_json(raw_path, raw_response)
        self.artifact_service.record_json_artifact(
            meeting_id=meeting_id,
            preprocessing_run_id=None,
            transcription_run_id=transcription_run_id,
            artifact_type="transcript",
            role="raw chunk response",
            path=raw_path,
            metadata={"chunk_index": chunk_index, "attempt_number": attempt_number},
        )

    def _write_merged_artifacts(
        self,
        *,
        meeting_id: int,
        transcription_run_id: int,
        stitched: dict[str, Any],
        average_confidence: float | None,
        failed_chunk_count: int,
        completed_chunk_count: int,
    ) -> None:
        artifact_root = ensure_directory(config.artifacts_root / f"meeting_{meeting_id}" / f"transcription_{transcription_run_id}")
        merged_json_path = artifact_root / "merged_transcript.json"
        merged_txt_path = artifact_root / "merged_transcript.txt"
        report_path = artifact_root / "stitching_report.json"
        confidence_path = artifact_root / "confidence_summary.json"

        write_json(
            merged_json_path,
            {
                "segments": stitched["merged_segments"],
                "summary": {
                    **stitched["report"],
                    "failed_chunk_count": failed_chunk_count,
                    "completed_chunk_count": completed_chunk_count,
                    "transcript_completeness": "partial" if failed_chunk_count else "complete",
                },
                "generated_at": utc_now_iso(),
            },
        )
        merged_txt_path.write_text(
            "\n".join(
                f"[{segment['start_ms_in_meeting']} - {segment['end_ms_in_meeting']}] {segment.get('speaker_label') or 'Speaker'}: {segment['text']}"
                for segment in stitched["merged_segments"]
            ),
            encoding="utf-8",
        )
        write_json(
            report_path,
            {
                **stitched["report"],
                "failed_chunk_count": failed_chunk_count,
                "completed_chunk_count": completed_chunk_count,
                "transcript_completeness": "partial" if failed_chunk_count else "complete",
            },
        )
        write_json(
            confidence_path,
            {
                "average_confidence": average_confidence,
                "segment_count": len(stitched["merged_segments"]),
                "failed_chunk_count": failed_chunk_count,
            },
        )

        descriptors = [
            ("merged transcript json", merged_json_path, {"segment_count": len(stitched["merged_segments"]), "failed_chunk_count": failed_chunk_count}),
            ("merged transcript txt", merged_txt_path, {"segment_count": len(stitched["merged_segments"]), "failed_chunk_count": failed_chunk_count}),
            ("stitching report", report_path, {"failed_chunk_count": failed_chunk_count, **stitched["report"]}),
            ("confidence summary", confidence_path, {"average_confidence": average_confidence, "failed_chunk_count": failed_chunk_count}),
        ]
        for role, path, metadata in descriptors:
            self.artifact_service.record_file_artifact(
                meeting_id=meeting_id,
                preprocessing_run_id=None,
                transcription_run_id=transcription_run_id,
                artifact_type="transcript",
                role=role,
                path=path,
                metadata=metadata,
            )

    @staticmethod
    def _settings_snapshot(settings) -> dict[str, Any]:
        return {
            "project_id": settings.project_id,
            "recognizer_location": settings.recognizer_location,
            "recognizer_id": settings.recognizer_id,
            "staging_bucket": settings.staging_bucket,
            "staging_prefix": settings.staging_prefix,
            "model": settings.model,
            "language_code": settings.language_code,
            "alternative_language_codes": settings.alternative_language_codes,
            "diarization_enabled": settings.diarization_enabled,
            "min_speaker_count": settings.min_speaker_count,
            "max_speaker_count": settings.max_speaker_count,
            "automatic_punctuation_enabled": settings.automatic_punctuation_enabled,
            "profanity_filter_enabled": settings.profanity_filter_enabled,
            "enable_word_time_offsets": settings.enable_word_time_offsets,
            "enable_word_confidence": settings.enable_word_confidence,
            "max_parallel_chunks": settings.max_parallel_chunks,
            "phrase_hints_placeholder": settings.phrase_hints_placeholder,
            "low_confidence_threshold": settings.low_confidence_threshold,
        }

    @staticmethod
    def _request_from_chunk(chunk: dict[str, Any]) -> ChunkTranscriptionRequest:
        return ChunkTranscriptionRequest(
            chunk_id=int(chunk["id"]),
            chunk_path=Path(chunk["file_path"]),
            chunk_index=int(chunk["chunk_index"]),
            start_ms=int(chunk["start_ms"]),
            end_ms=int(chunk["end_ms"]),
            overlap_before_ms=int(chunk["overlap_before_ms"]),
            overlap_after_ms=int(chunk["overlap_after_ms"]),
        )

    def _load_persisted_chunk_segment_map(self, transcription_run_id: int) -> dict[int, list[TranscriptSegment]]:
        raw_segments = self.transcript_segment_repository.list_for_run(transcription_run_id, "chunk_raw")
        raw_words = self.transcript_word_repository.list_for_run(transcription_run_id)
        words_by_chunk: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for word in raw_words:
            words_by_chunk[int(word["chunk_id"])].append(word)

        chunk_segment_map: dict[int, list[TranscriptSegment]] = defaultdict(list)
        for segment_row in raw_segments:
            chunk_id = int(segment_row["chunk_id"])
            segment_words = []
            for word_row in words_by_chunk.get(chunk_id, []):
                start_in_chunk = word_row.get("start_ms_in_chunk")
                end_in_chunk = word_row.get("end_ms_in_chunk")
                if start_in_chunk is None and end_in_chunk is None:
                    continue
                if segment_row.get("start_ms_in_chunk") is not None and start_in_chunk is not None and start_in_chunk < segment_row["start_ms_in_chunk"]:
                    continue
                if segment_row.get("end_ms_in_chunk") is not None and end_in_chunk is not None and end_in_chunk > segment_row["end_ms_in_chunk"]:
                    continue
                segment_words.append(
                    TranscriptWord(
                        word_text=word_row["word_text"],
                        start_ms_in_chunk=start_in_chunk,
                        end_ms_in_chunk=end_in_chunk,
                        speaker_label=word_row.get("speaker_label"),
                        confidence=word_row.get("confidence"),
                    )
                )
            chunk_segment_map[chunk_id].append(
                TranscriptSegment(
                    text=segment_row["text"],
                    start_ms_in_chunk=segment_row.get("start_ms_in_chunk"),
                    end_ms_in_chunk=segment_row.get("end_ms_in_chunk"),
                    speaker_label=segment_row.get("speaker_label"),
                    confidence=segment_row.get("confidence"),
                    words=segment_words,
                )
            )
        return dict(chunk_segment_map)

    def _confidence_values_for_run(self, transcription_run_id: int) -> list[float]:
        rows = self.chunk_transcript_repository.list_for_run(transcription_run_id)
        return [float(row["average_confidence"]) for row in rows if row.get("status") == "completed" and row.get("average_confidence") is not None]

    @staticmethod
    def _validate_chunk_files(chunks: list[dict[str, Any]]) -> None:
        missing = []
        for chunk in chunks:
            path = Path(chunk["file_path"])
            if not path.exists():
                missing.append((int(chunk.get("chunk_index", -1)), str(path)))
        if not missing:
            return
        preview = " | ".join(
            f"chunk {index + 1}: {path}" if index >= 0 else path
            for index, path in missing[:3]
        )
        raise ValueError(
            "Prepared chunk files are missing on disk. "
            f"Re-run preprocessing or remove the stale queue item. Missing: {preview}"
        )

    def _has_active_task(self, transcription_run_id: int) -> bool:
        for key in (("run", transcription_run_id), ("retry", transcription_run_id)):
            task = self._tasks.get(key)
            if task and task.is_alive():
                return True
        return False

    def _recover_orphaned_run(self, run: dict[str, Any]) -> None:
        message = "Previous transcription job was interrupted before completion. Retry resumed from persisted chunk results."
        if run.get("job_run_id"):
            self.job_run_repository.finalize(
                int(run["job_run_id"]),
                status="failed",
                stage="failed",
                current_message=message,
                error_message=message,
            )
        fallback_status = "completed_with_failures" if int(run.get("failed_chunk_count") or 0) else "completed"
        self.transcription_run_repository.finalize_success(
            int(run["id"]),
            status=fallback_status,
            average_confidence=run.get("average_confidence"),
            error_message=message if fallback_status == "completed_with_failures" else None,
        )

    @staticmethod
    def _resolve_success_status(*, previous_status: str, failed_count: int) -> str:
        if failed_count > 0:
            return "completed_with_failures"
        return "recovered" if previous_status == "completed_with_failures" else "completed"

    @staticmethod
    def _success_message(run_status: str, failed_count: int, completed_count: int, total_count: int) -> str:
        if run_status == "recovered":
            return f"Recovered transcript to {completed_count}/{total_count} completed chunks"
        if failed_count:
            return f"Transcription completed with {failed_count} failed chunk(s)"
        return "Transcription completed"
