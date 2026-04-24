import shutil
import tempfile
import time
import unittest
from pathlib import Path

from app.core.config import load_config
from app.services.transcription.models import ChunkTranscriptionResult, TranscriptSegment, TranscriptWord
from app.utils.files import sha256_for_file
from tests._support import IsolatedWorkerApp


class FakeSpeechAdapter:
    engine_name = "fake_google_speech"

    def __init__(self, fail_chunk_index: int | None = None) -> None:
        self.fail_chunk_index = fail_chunk_index

    def validate_runtime(self, settings) -> dict[str, str]:
        return {"google-cloud-speech": "fake"}

    def validate_preflight(self, settings, *, validate_bucket_write: bool) -> dict[str, object]:
        return {"bucket_accessible": True, "bucket_write_checked": validate_bucket_write}

    def transcribe_chunk(self, *, chunk, settings, meeting_id: int, run_id: int):
        if self.fail_chunk_index is not None and chunk.chunk_index == self.fail_chunk_index:
            raise RuntimeError(f"Forced failure for chunk {chunk.chunk_index}")

        if chunk.chunk_index == 0:
            words = [
                TranscriptWord("Hello", 0, 450, "speaker_1", 0.96),
                TranscriptWord("team", 500, 980, "speaker_1", 0.95),
                TranscriptWord("status", 58_000, 58_400, "speaker_1", 0.92),
                TranscriptWord("update", 58_450, 58_900, "speaker_1", 0.91),
            ]
        else:
            words = [
                TranscriptWord("status", 100, 450, "speaker_2", 0.88),
                TranscriptWord("update", 500, 1_000, "speaker_2", 0.87),
                TranscriptWord("next", 2_100, 2_500, "speaker_2", 0.93),
                TranscriptWord("steps", 2_600, 3_000, "speaker_2", 0.94),
            ]

        segment = TranscriptSegment(
            text=" ".join(word.word_text for word in words),
            start_ms_in_chunk=words[0].start_ms_in_chunk,
            end_ms_in_chunk=words[-1].end_ms_in_chunk,
            speaker_label=words[0].speaker_label,
            confidence=0.92,
            words=words,
        )
        return ChunkTranscriptionResult(
            transcript_text=segment.text,
            raw_response={"chunk_index": chunk.chunk_index, "meeting_id": meeting_id, "run_id": run_id},
            average_confidence=0.92,
            segments=[segment],
            request_config={"model": settings.model, "language_code": settings.language_code},
            response_metadata={},
        )


class AlwaysFailSpeechAdapter:
    engine_name = "fake_google_speech"

    def validate_runtime(self, settings) -> dict[str, str]:
        return {"google-cloud-speech": "fake"}

    def validate_preflight(self, settings, *, validate_bucket_write: bool) -> dict[str, object]:
        return {"bucket_accessible": True, "bucket_write_checked": validate_bucket_write}

    def transcribe_chunk(self, *, chunk, settings, meeting_id: int, run_id: int):
        raise RuntimeError(f"Forced adapter failure for chunk {chunk.chunk_index}")


class TranscriptionPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.worker = IsolatedWorkerApp(prefix="audio-extractor-phase2-").start()
        self.client = self.worker.client
        self.services = self.worker.services
        self.config = load_config()
        self.temp_dir = Path(tempfile.mkdtemp(prefix="audio-extractor-phase2-"))
        self.original_adapter = self.services["transcription_job_service"].adapter
        current = next((row for row in self.services["settings_repository"].list() if row["key"] == "transcription_defaults"), None)
        self.original_settings = current["value_json"] if current else None
        self._seed_transcription_settings()

    def tearDown(self) -> None:
        self.services["transcription_job_service"].adapter = self.original_adapter
        if self.original_settings is not None:
            self.services["settings_repository"].upsert("transcription_defaults", self.original_settings)
        self.worker.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_transcription_run_persists_segments_and_dedupes_overlap(self) -> None:
        self.services["transcription_job_service"].adapter = FakeSpeechAdapter()
        meeting_id = self._create_prepared_meeting()

        response = self.client.post(f"/api/v1/meetings/{meeting_id}/transcribe")
        self.assertEqual(response.status_code, 200)
        run_payload = response.json()
        self.assertEqual(run_payload["status"], "pending")

        transcription = self._wait_for_transcription(meeting_id)
        self.assertEqual(transcription["status"], "completed")
        self.assertEqual(transcription["completed_chunk_count"], 2)
        self.assertEqual(transcription["failed_chunk_count"], 0)
        self.assertGreaterEqual(len(transcription["chunk_transcripts"]), 2)

        transcript_response = self.client.get(f"/api/v1/meetings/{meeting_id}/transcript")
        self.assertEqual(transcript_response.status_code, 200)
        transcript_payload = transcript_response.json()
        self.assertGreaterEqual(transcript_payload["summary"]["segment_count"], 2)
        merged_text = " ".join(segment["text"] for segment in transcript_payload["segments"])
        self.assertIn("Hello team", merged_text)
        self.assertIn("next steps", merged_text)
        self.assertEqual(merged_text.count("status update"), 1)
        self.assertGreaterEqual(transcript_payload["segments"][1]["start_ms_in_meeting"], 60_000)

    def test_partial_chunk_failure_keeps_run_completed_when_transcript_exists(self) -> None:
        self.services["transcription_job_service"].adapter = FakeSpeechAdapter(fail_chunk_index=1)
        meeting_id = self._create_prepared_meeting()

        response = self.client.post(f"/api/v1/meetings/{meeting_id}/transcribe")
        self.assertEqual(response.status_code, 200)

        transcription = self._wait_for_transcription(meeting_id)
        self.assertEqual(transcription["status"], "completed_with_failures")
        self.assertEqual(transcription["completed_chunk_count"], 1)
        self.assertEqual(transcription["failed_chunk_count"], 1)
        self.assertTrue(any(item["status"] == "failed" for item in transcription["chunk_transcripts"]))
        self.assertTrue(transcription["has_partial_transcript"])
        failed_chunk = next(item for item in transcription["chunk_transcripts"] if item["status"] == "failed")
        self.assertEqual(failed_chunk["attempt_count"], 1)
        self.assertEqual(len(failed_chunk["attempts"]), 1)

    def test_retry_failed_chunk_recovers_without_rerunning_successful_chunks(self) -> None:
        self.services["transcription_job_service"].adapter = FakeSpeechAdapter(fail_chunk_index=1)
        meeting_id = self._create_prepared_meeting()

        first_response = self.client.post(f"/api/v1/meetings/{meeting_id}/transcribe")
        self.assertEqual(first_response.status_code, 200)
        initial_run = self._wait_for_transcription(meeting_id)
        self.assertEqual(initial_run["status"], "completed_with_failures")
        self.assertEqual(initial_run["failed_chunk_count"], 1)
        failed_chunk = next(item for item in initial_run["chunk_transcripts"] if item["status"] == "failed")
        completed_chunk = next(item for item in initial_run["chunk_transcripts"] if item["status"] == "completed")

        self.services["transcription_job_service"].adapter = FakeSpeechAdapter()
        retry_response = self.client.post(
            f"/api/v1/transcription-runs/{initial_run['id']}/retry-failed",
            json={"chunk_ids": [failed_chunk["chunk_id"]]},
        )
        self.assertEqual(retry_response.status_code, 200)
        self.assertEqual(retry_response.json()["transcription_run_id"], initial_run["id"])
        self.assertEqual(retry_response.json()["retried_chunk_ids"], [failed_chunk["chunk_id"]])

        recovered = self._wait_for_transcription(meeting_id, terminal_statuses={"recovered", "failed"})
        self.assertEqual(recovered["status"], "recovered")
        self.assertEqual(recovered["completed_chunk_count"], 2)
        self.assertEqual(recovered["failed_chunk_count"], 0)

        recovered_failed_chunk = next(item for item in recovered["chunk_transcripts"] if item["chunk_id"] == failed_chunk["chunk_id"])
        recovered_completed_chunk = next(item for item in recovered["chunk_transcripts"] if item["chunk_id"] == completed_chunk["chunk_id"])
        self.assertEqual(recovered_failed_chunk["status"], "completed")
        self.assertEqual(recovered_failed_chunk["attempt_count"], 2)
        self.assertEqual(recovered_completed_chunk["attempt_count"], 1)

        transcript_response = self.client.get(f"/api/v1/meetings/{meeting_id}/transcript")
        self.assertEqual(transcript_response.status_code, 200)
        transcript_payload = transcript_response.json()
        self.assertEqual(transcript_payload["transcription_run"]["status"], "recovered")
        self.assertEqual(transcript_payload["transcription_run"]["transcript_completeness"], "complete")
        merged_text = " ".join(segment["text"] for segment in transcript_payload["segments"])
        self.assertIn("Hello team", merged_text)
        self.assertIn("next steps", merged_text)

    def test_retry_rejects_non_failed_chunk_requests(self) -> None:
        self.services["transcription_job_service"].adapter = FakeSpeechAdapter(fail_chunk_index=1)
        meeting_id = self._create_prepared_meeting()

        response = self.client.post(f"/api/v1/meetings/{meeting_id}/transcribe")
        self.assertEqual(response.status_code, 200)
        transcription = self._wait_for_transcription(meeting_id)
        completed_chunk = next(item for item in transcription["chunk_transcripts"] if item["status"] == "completed")

        retry_response = self.client.post(
            f"/api/v1/transcription-runs/{transcription['id']}/retry-failed",
            json={"chunk_ids": [completed_chunk["chunk_id"]]},
        )
        self.assertEqual(retry_response.status_code, 400)
        self.assertIn("currently failed chunks", retry_response.json()["detail"])

    def test_missing_transcription_settings_fail_clearly(self) -> None:
        self.services["settings_repository"].upsert(
            "transcription_defaults",
            {
                "project_id": "",
                "staging_bucket": "",
                "model": "chirp_3",
                "language_code": "en-US",
            },
        )
        meeting_id = self._create_prepared_meeting()
        response = self.client.post(f"/api/v1/meetings/{meeting_id}/transcribe")
        self.assertEqual(response.status_code, 400)
        self.assertIn("project_id", response.json()["detail"])

    def test_placeholder_transcription_settings_fail_clearly(self) -> None:
        self.services["settings_repository"].upsert(
            "transcription_defaults",
            {
                "project_id": "demo-project",
                "auth_mode": "application_default_credentials",
                "credentials_path": "",
                "recognizer_location": "global",
                "recognizer_id": "_",
                "staging_bucket": "demo-bucket",
                "staging_prefix": "audio-extractor-2",
                "model": "chirp_3",
                "language_code": "en-US",
                "alternative_language_codes": [],
                "diarization_enabled": True,
                "min_speaker_count": 2,
                "max_speaker_count": 4,
                "automatic_punctuation_enabled": True,
                "profanity_filter_enabled": False,
                "enable_word_time_offsets": True,
                "enable_word_confidence": True,
                "max_parallel_chunks": 2,
                "phrase_hints_placeholder": [],
                "low_confidence_threshold": 0.7,
            },
        )
        meeting_id = self._create_prepared_meeting()
        response = self.client.post(f"/api/v1/meetings/{meeting_id}/transcribe")
        self.assertEqual(response.status_code, 400)
        self.assertIn("placeholder", response.json()["detail"])

    def test_all_chunk_failures_surface_underlying_error(self) -> None:
        self.services["transcription_job_service"].adapter = AlwaysFailSpeechAdapter()
        meeting_id = self._create_prepared_meeting()
        response = self.client.post(f"/api/v1/meetings/{meeting_id}/transcribe")
        self.assertEqual(response.status_code, 200)

        transcription = self._wait_for_transcription(meeting_id)
        self.assertEqual(transcription["status"], "failed")
        self.assertIn("Forced adapter failure", transcription["error_message"])

    def test_missing_chunk_file_fails_before_queueing(self) -> None:
        self.services["transcription_job_service"].adapter = FakeSpeechAdapter()
        meeting_id = self._create_prepared_meeting()
        chunks = self.services["chunk_repository"].list_for_meeting(meeting_id)
        Path(chunks[0]["file_path"]).unlink()

        response = self.client.post(f"/api/v1/meetings/{meeting_id}/transcribe")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Prepared chunk files are missing on disk", response.json()["detail"])

    def test_chirp_3_global_location_fails_before_queueing(self) -> None:
        self.services["settings_repository"].upsert(
            "transcription_defaults",
            {
                "project_id": "test-project",
                "auth_mode": "credentials_file",
                "credentials_path": str(self.temp_dir / "fake-google-creds.json"),
                "recognizer_location": "global",
                "recognizer_id": "_",
                "staging_bucket": "test-audio-extractor-bucket",
                "staging_prefix": "audio-extractor-2",
                "model": "chirp_3",
                "language_code": "en-US",
                "alternative_language_codes": [],
                "diarization_enabled": True,
                "min_speaker_count": 2,
                "max_speaker_count": 4,
                "automatic_punctuation_enabled": True,
                "profanity_filter_enabled": False,
                "enable_word_time_offsets": True,
                "enable_word_confidence": True,
                "max_parallel_chunks": 2,
                "phrase_hints_placeholder": [],
                "low_confidence_threshold": 0.7,
            },
        )
        meeting_id = self._create_prepared_meeting()
        response = self.client.post(f"/api/v1/meetings/{meeting_id}/transcribe")
        self.assertEqual(response.status_code, 400)
        self.assertIn("chirp_3", response.json()["detail"])

    def _seed_transcription_settings(self) -> None:
        credentials_path = self.temp_dir / "fake-google-creds.json"
        credentials_path.write_text('{"type":"service_account","project_id":"test-project"}', encoding="utf-8")
        self.services["settings_repository"].upsert(
            "transcription_defaults",
            {
                "project_id": "test-project",
                "auth_mode": "credentials_file",
                "credentials_path": str(credentials_path),
                "recognizer_location": "us",
                "recognizer_id": "_",
                "staging_bucket": "test-audio-extractor-bucket",
                "staging_prefix": "audio-extractor-2",
                "model": "chirp_3",
                "language_code": "en-US",
                "alternative_language_codes": [],
                "diarization_enabled": True,
                "min_speaker_count": 2,
                "max_speaker_count": 4,
                "automatic_punctuation_enabled": True,
                "profanity_filter_enabled": False,
                "enable_word_time_offsets": True,
                "enable_word_confidence": True,
                "max_parallel_chunks": 2,
                "phrase_hints_placeholder": [],
                "low_confidence_threshold": 0.7,
            },
        )

    def _create_prepared_meeting(self) -> int:
        meeting_id = self.services["meeting_repository"].create(
            "Transcript Seed",
            "2026-04-10",
            "Phase 2",
            "Seeded test meeting",
        )
        source_path = self.temp_dir / f"meeting_{meeting_id}.wav"
        source_path.write_bytes(b"seed-source")
        normalized_path = self.temp_dir / f"meeting_{meeting_id}_normalized.flac"
        normalized_path.write_bytes(b"normalized-seed")

        self.services["source_file_repository"].create(
            {
                "meeting_id": meeting_id,
                "import_mode": "reference",
                "original_path": str(source_path),
                "managed_copy_path": None,
                "normalized_audio_path": str(normalized_path),
                "file_name": source_path.name,
                "extension": ".wav",
                "mime_type": "audio/wav",
                "media_type": "audio",
                "size_bytes": source_path.stat().st_size,
                "sha256": sha256_for_file(source_path),
                "duration_ms": 120_000,
                "sample_rate": 16_000,
                "channels": 1,
            }
        )
        self.services["meeting_repository"].update_status(meeting_id, "prepared")
        job_run_id = self.services["job_run_repository"].create(meeting_id, "preprocess", "seeded preprocessing")
        preprocessing_run_id = self.services["run_repository"].create(
            meeting_id,
            job_run_id,
            self.config.worker_version,
            {
                "target_ms": 600_000,
                "hard_max_ms": 720_000,
                "min_chunk_ms": 180_000,
                "overlap_ms": 1_500,
                "min_silence_ms": 700,
                "silence_threshold_db": -35,
            },
        )
        self.services["run_repository"].finalize_success(
            preprocessing_run_id,
            normalized_format="flac",
            normalized_sample_rate=16_000,
            normalized_channels=1,
            silence_map={"candidate_count": 1, "candidates": []},
            chunk_strategy={"coverage_validation": {"covers_full_duration": True}},
            waveform_summary={"buckets": [0.1, 0.2]},
        )
        self.services["job_run_repository"].finalize(
            job_run_id,
            status="completed",
            stage="completed",
            current_message="seeded preprocessing complete",
            error_message=None,
        )

        chunk_a = self.temp_dir / f"meeting_{meeting_id}_chunk_000.flac"
        chunk_b = self.temp_dir / f"meeting_{meeting_id}_chunk_001.flac"
        chunk_a.write_bytes(b"chunk-a")
        chunk_b.write_bytes(b"chunk-b")
        self.services["chunk_repository"].replace_for_run(
            preprocessing_run_id,
            [
                {
                    "meeting_id": meeting_id,
                    "chunk_index": 0,
                    "file_path": str(chunk_a),
                    "sha256": sha256_for_file(chunk_a),
                    "start_ms": 0,
                    "end_ms": 60_000,
                    "overlap_before_ms": 0,
                    "overlap_after_ms": 1_500,
                    "duration_ms": 60_000,
                    "boundary_reason": "silence_preferred",
                    "status": "prepared",
                },
                {
                    "meeting_id": meeting_id,
                    "chunk_index": 1,
                    "file_path": str(chunk_b),
                    "sha256": sha256_for_file(chunk_b),
                    "start_ms": 58_500,
                    "end_ms": 120_000,
                    "overlap_before_ms": 1_500,
                    "overlap_after_ms": 0,
                    "duration_ms": 61_500,
                    "boundary_reason": "final_tail",
                    "status": "prepared",
                },
            ],
        )
        return meeting_id

    def _wait_for_transcription(self, meeting_id: int, terminal_statuses: set[str] | None = None) -> dict:
        statuses = terminal_statuses or {"completed", "completed_with_failures", "recovered", "failed"}
        for _ in range(60):
            response = self.client.get(f"/api/v1/meetings/{meeting_id}/transcription")
            payload = response.json()
            if payload and payload["status"] in statuses:
                return payload
            time.sleep(0.1)
        self.fail("Timed out waiting for transcription run")


if __name__ == "__main__":
    unittest.main()
