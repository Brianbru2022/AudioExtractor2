from __future__ import annotations

import json
import shutil
import struct
import subprocess
import threading
from pathlib import Path
from typing import Any

from app.core.config import config
from app.repositories.meetings import (
    ArtifactRepository,
    ChunkRepository,
    MeetingRepository,
    RunRepository,
    SourceFileRepository,
)
from app.repositories.transcription import JobRunRepository
from app.services.artifacts.service import ArtifactService
from app.services.chunk_planning.service import ChunkPlanningService
from app.services.chunk_writing.service import ChunkWriterService
from app.services.normalization.service import NormalizationService
from app.services.probing.service import ProbeService
from app.services.silence_analysis.service import SilenceAnalysisService
from app.utils.files import ensure_directory, sha256_for_file, utc_now_iso, write_json
from app.utils.subprocesses import require_binary


class JobService:
    def __init__(
        self,
        *,
        meeting_repository: MeetingRepository,
        source_file_repository: SourceFileRepository,
        run_repository: RunRepository,
        job_run_repository: JobRunRepository,
        chunk_repository: ChunkRepository,
        artifact_repository: ArtifactRepository,
        probe_service: ProbeService,
        normalization_service: NormalizationService,
        silence_analysis_service: SilenceAnalysisService,
        chunk_planning_service: ChunkPlanningService,
        chunk_writer_service: ChunkWriterService,
    ) -> None:
        self.meeting_repository = meeting_repository
        self.source_file_repository = source_file_repository
        self.run_repository = run_repository
        self.job_run_repository = job_run_repository
        self.chunk_repository = chunk_repository
        self.artifact_service = ArtifactService(artifact_repository)
        self.probe_service = probe_service
        self.normalization_service = normalization_service
        self.silence_analysis_service = silence_analysis_service
        self.chunk_planning_service = chunk_planning_service
        self.chunk_writer_service = chunk_writer_service
        self._tasks: dict[int, threading.Thread] = {}
        self.ffmpeg = require_binary("ffmpeg")

    def enqueue(self, meeting_id: int) -> int:
        job_run_id = self.job_run_repository.create(meeting_id, "preprocess", "Queued for preprocessing")
        run_id = self.run_repository.create(
            meeting_id,
            job_run_id,
            config.worker_version,
            {
                "target_ms": config.chunk_defaults.target_ms,
                "hard_max_ms": config.chunk_defaults.hard_max_ms,
                "min_chunk_ms": config.chunk_defaults.min_chunk_ms,
                "overlap_ms": config.chunk_defaults.overlap_ms,
                "min_silence_ms": config.chunk_defaults.min_silence_ms,
                "silence_threshold_db": config.chunk_defaults.silence_threshold_db,
            },
        )
        self.meeting_repository.update_status(meeting_id, "preprocessing")
        task = threading.Thread(target=self._run_pipeline, args=(run_id,), daemon=True)
        self._tasks[run_id] = task
        task.start()
        return run_id

    def _run_pipeline(self, run_id: int) -> None:
        run = self.run_repository.get(run_id)
        if not run:
            return

        meeting_id = int(run["meeting_id"])
        job_run_id = run.get("job_run_id")
        source_file = self.source_file_repository.get_for_meeting(meeting_id)
        if not source_file:
            return

        try:
            self._set_stage(run_id, "running", "probing", 10, "Refreshing source probe")
            source_path = self._resolve_source_path(source_file)
            source_probe = self.probe_service.probe(source_path)
            self._log(run_id, "probe", {"source": str(source_path), "duration_ms": source_probe.duration_ms})

            self._set_stage(run_id, "running", "normalizing", 28, "Normalizing audio to FLAC")
            run_root = ensure_directory(config.normalized_root / f"meeting_{meeting_id}" / f"run_{run_id}")
            normalized_path = run_root / "normalized.flac"
            self.normalization_service.normalize_to_flac(source_path, normalized_path)
            normalized_probe = self.probe_service.probe(normalized_path)
            normalized_sha = sha256_for_file(normalized_path)
            self.source_file_repository.update_normalized_path(
                meeting_id,
                str(normalized_path),
                normalized_probe.sample_rate,
                normalized_probe.channels,
            )
            self.artifact_service.record_file_artifact(
                meeting_id=meeting_id,
                preprocessing_run_id=run_id,
                artifact_type="audio",
                role="normalized audio",
                path=normalized_path,
                metadata={
                    "duration_ms": normalized_probe.duration_ms,
                    "sample_rate": normalized_probe.sample_rate,
                    "channels": normalized_probe.channels,
                    "sha256": normalized_sha,
                },
            )

            self._set_stage(run_id, "running", "analyzing_silence", 48, "Finding silence candidates")
            silence_map = self.silence_analysis_service.analyze(
                normalized_path,
                config.chunk_defaults.silence_threshold_db,
                config.chunk_defaults.min_silence_ms,
            )
            artifacts_root = ensure_directory(config.artifacts_root / f"meeting_{meeting_id}" / f"run_{run_id}")
            silence_map_path = artifacts_root / "silence_map.json"
            write_json(silence_map_path, silence_map)
            self.artifact_service.record_json_artifact(
                meeting_id=meeting_id,
                preprocessing_run_id=run_id,
                artifact_type="analysis",
                role="silence map",
                path=silence_map_path,
                metadata={"candidate_count": silence_map["candidate_count"]},
            )

            self._set_stage(run_id, "running", "planning_chunks", 64, "Planning chunk boundaries")
            chunk_plan = self.chunk_planning_service.plan(
                duration_ms=normalized_probe.duration_ms,
                silence_candidates=silence_map["candidates"],
                target_ms=config.chunk_defaults.target_ms,
                hard_max_ms=config.chunk_defaults.hard_max_ms,
                min_chunk_ms=config.chunk_defaults.min_chunk_ms,
                overlap_ms=config.chunk_defaults.overlap_ms,
            )

            self._set_stage(run_id, "running", "writing_chunks", 78, "Writing chunk audio files")
            chunk_root = ensure_directory(config.chunks_root / f"meeting_{meeting_id}" / f"run_{run_id}")
            chunk_records: list[dict[str, Any]] = []
            manifest_chunks: list[dict[str, Any]] = []
            for planned_chunk in chunk_plan["chunks"]:
                chunk_path = chunk_root / f"chunk_{planned_chunk['chunk_index']:03d}.flac"
                chunk_sha = self.chunk_writer_service.write_chunk(
                    normalized_path,
                    chunk_path,
                    start_ms=int(planned_chunk["start_ms"]),
                    end_ms=int(planned_chunk["end_ms"]),
                )
                record = {
                    "meeting_id": meeting_id,
                    "chunk_index": int(planned_chunk["chunk_index"]),
                    "file_path": str(chunk_path),
                    "sha256": chunk_sha,
                    "start_ms": int(planned_chunk["start_ms"]),
                    "end_ms": int(planned_chunk["end_ms"]),
                    "overlap_before_ms": int(planned_chunk["overlap_before_ms"]),
                    "overlap_after_ms": int(planned_chunk["overlap_after_ms"]),
                    "duration_ms": int(planned_chunk["duration_ms"]),
                    "boundary_reason": str(planned_chunk["boundary_reason"]),
                    "status": "prepared",
                }
                manifest_payload = {
                    **record,
                    "base_start_ms": int(planned_chunk["base_start_ms"]),
                    "base_end_ms": int(planned_chunk["base_end_ms"]),
                }
                manifest_chunks.append(manifest_payload)
                chunk_records.append(record)
            self.chunk_repository.replace_for_run(run_id, chunk_records)

            manifest_path = artifacts_root / "chunk_manifest.json"
            write_json(
                manifest_path,
                {
                    "meeting_id": meeting_id,
                    "run_id": run_id,
                    "generated_at": utc_now_iso(),
                    "strategy": chunk_plan["strategy"],
                    "chunks": manifest_chunks,
                },
            )
            self.artifact_service.record_json_artifact(
                meeting_id=meeting_id,
                preprocessing_run_id=run_id,
                artifact_type="chunking",
                role="chunk manifest",
                path=manifest_path,
                metadata={
                    "chunk_count": len(manifest_chunks),
                    "coverage_validation": chunk_plan["strategy"]["coverage_validation"],
                },
            )

            waveform_summary = self._generate_waveform_summary(normalized_path)
            waveform_path = artifacts_root / "waveform_summary.json"
            write_json(waveform_path, waveform_summary)
            self.artifact_service.record_json_artifact(
                meeting_id=meeting_id,
                preprocessing_run_id=run_id,
                artifact_type="analysis",
                role="waveform summary",
                path=waveform_path,
                metadata={"bucket_count": len(waveform_summary["buckets"])},
            )

            self._set_stage(run_id, "running", "finalizing", 95, "Finalizing artifacts and status")
            self._log(run_id, "complete", {"chunks": len(chunk_records)})
            self.run_repository.finalize_success(
                run_id,
                normalized_format="flac",
                normalized_sample_rate=normalized_probe.sample_rate or 16000,
                normalized_channels=normalized_probe.channels or 1,
                silence_map=silence_map,
                chunk_strategy=chunk_plan["strategy"],
                waveform_summary=waveform_summary,
            )
            if job_run_id:
                self.job_run_repository.finalize(
                    int(job_run_id),
                    status="completed",
                    stage="completed",
                    current_message="Preprocessing complete",
                    error_message=None,
                )
            self.meeting_repository.update_status(meeting_id, "prepared")

            logs_path = config.logs_root / f"meeting_{meeting_id}" / f"run_{run_id}.json"
            ensure_directory(logs_path.parent)
            logs = self.run_repository.get(run_id)["log_json"]
            logs_path.write_text(logs, encoding="utf-8")
            self.artifact_service.record_json_artifact(
                meeting_id=meeting_id,
                preprocessing_run_id=run_id,
                artifact_type="logs",
                role="preprocessing log",
                path=logs_path,
                metadata={"entries": len(json.loads(logs))},
            )
        except Exception as exc:  # noqa: BLE001
            self._log(run_id, "error", {"message": str(exc)})
            self.run_repository.finalize_failure(run_id, str(exc))
            if job_run_id:
                self.job_run_repository.finalize(
                    int(job_run_id),
                    status="failed",
                    stage="failed",
                    current_message=str(exc),
                    error_message=str(exc),
                )
            self.meeting_repository.update_status(meeting_id, "failed")

    @staticmethod
    def _resolve_source_path(source_file: dict[str, Any]) -> Path:
        managed_copy_path = source_file.get("managed_copy_path")
        original_path = source_file.get("original_path")
        import_mode = source_file.get("import_mode")

        if managed_copy_path:
            candidate = Path(managed_copy_path)
            if candidate.exists():
                return candidate
            raise FileNotFoundError(f"Managed copy is missing: {candidate}")

        candidate = Path(original_path)
        if candidate.exists():
            return candidate

        raise FileNotFoundError(
            f"Source file is missing for {import_mode} import mode: {candidate}"
        )

    def _set_stage(self, run_id: int, status: str, stage: str, progress: float, message: str) -> None:
        run = self.run_repository.get(run_id)
        self.run_repository.update_state(
            run_id,
            status=status,
            stage=stage,
            progress_percent=progress,
            current_message=message,
        )
        if run and run.get("job_run_id"):
            self.job_run_repository.update_state(
                int(run["job_run_id"]),
                status=status,
                stage=stage,
                progress_percent=progress,
                current_message=message,
            )

    def _log(self, run_id: int, event: str, metadata: dict[str, Any]) -> None:
        self.run_repository.append_log(
            run_id,
            {
                "timestamp": utc_now_iso(),
                "event": event,
                "metadata": metadata,
            },
        )

    def _generate_waveform_summary(self, normalized_path: Path) -> dict[str, Any]:
        command = [
            self.ffmpeg,
            "-hide_banner",
            "-i",
            str(normalized_path),
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ac",
            "1",
            "-ar",
            "8000",
            "-",
        ]
        completed = subprocess.run(command, capture_output=True, check=False)
        raw = completed.stdout
        if not raw:
            return {"sample_rate": 8000, "bucket_duration_ms": 250, "buckets": []}

        samples = struct.iter_unpack("<h", raw)
        values = [abs(sample[0]) / 32768 for sample in samples]
        if not values:
            return {"sample_rate": 8000, "bucket_duration_ms": 250, "buckets": []}

        bucket_size = 2000
        buckets = []
        for index in range(0, len(values), bucket_size):
            slice_values = values[index : index + bucket_size]
            buckets.append(round(sum(slice_values) / len(slice_values), 4))

        return {"sample_rate": 8000, "bucket_duration_ms": 250, "buckets": buckets}


def import_source_into_mode(source_path: Path, meeting_id: int, import_mode: str) -> Path | None:
    if import_mode != "managed_copy":
        return None

    target_dir = ensure_directory(config.managed_root / f"meeting_{meeting_id}")
    target_path = target_dir / source_path.name
    shutil.copy2(source_path, target_path)
    return target_path
