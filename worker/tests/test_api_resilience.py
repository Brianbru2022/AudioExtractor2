import json
import shutil
import tempfile
import unittest
from pathlib import Path

from app.core.config import load_config
from app.utils.files import ensure_directory, sha256_for_file
from tests._support import IsolatedWorkerApp


class ApiResilienceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.worker = IsolatedWorkerApp(prefix="audio-extractor-phase1-").start()
        self.client = self.worker.client
        self.services = self.worker.services
        self.config = load_config()
        self.temp_dir = Path(tempfile.mkdtemp(prefix="audio-extractor-phase1-"))

    def tearDown(self) -> None:
        self.worker.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_missing_reference_source_fails_clearly(self) -> None:
        missing_path = self.temp_dir / "missing.wav"
        response = self.client.post(
            "/api/v1/meetings/import",
            json={
                "source_path": str(missing_path),
                "import_mode": "reference",
                "title": "Missing Source",
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_moved_reference_source_blocks_preprocess(self) -> None:
        source_path = self.temp_dir / "source.wav"
        source_path.write_bytes(b"not-real-media")

        # Import will fail with non-media content, so this test inserts a meeting through the API path used in validation.
        import_response = self.client.post(
            "/api/v1/meetings/import",
            json={
                "source_path": str(self._create_valid_wav()),
                "import_mode": "reference",
                "title": "Moved Source",
            },
        )
        meeting = import_response.json()["meeting"]
        valid_source = Path(meeting["source_file"]["original_path"])
        moved_path = valid_source.with_name(f"{valid_source.stem}-moved{valid_source.suffix}")
        valid_source.rename(moved_path)

        response = self.client.post(f"/api/v1/meetings/{meeting['id']}/preprocess")
        self.assertEqual(response.status_code, 400)
        self.assertIn("source is missing", response.json()["detail"])

    def test_delete_completed_job_removes_queue_row(self) -> None:
        meeting_id = self.services["meeting_repository"].create("Queue Cleanup", "2026-04-13", "Ops", "job cleanup")
        job_run_id = self.services["job_run_repository"].create(meeting_id, "preprocess", "seed queue item")
        self.services["job_run_repository"].finalize(
            job_run_id,
            status="failed",
            stage="failed",
            current_message="failed for cleanup",
            error_message="failed for cleanup",
        )

        response = self.client.delete(f"/api/v1/jobs/{job_run_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "deleted")
        self.assertIsNone(self.services["job_run_repository"].get(job_run_id))

    def test_delete_managed_copy_meeting_removes_local_files_and_rows(self) -> None:
        meeting_id, managed_copy, normalized_path, chunk_path, export_path = self._create_seeded_meeting(import_mode="managed_copy")

        response = self.client.delete(f"/api/v1/meetings/{meeting_id}")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "deleted")
        self.assertFalse(payload["preserved_reference_original"])
        self.assertIsNone(self.services["meeting_repository"].get(meeting_id))
        self.assertFalse(managed_copy.exists())
        self.assertFalse(normalized_path.exists())
        self.assertFalse(chunk_path.exists())
        self.assertFalse(export_path.exists())

    def test_delete_reference_meeting_preserves_original_source(self) -> None:
        meeting_id, original_path, normalized_path, chunk_path, export_path = self._create_seeded_meeting(import_mode="reference")

        response = self.client.delete(f"/api/v1/meetings/{meeting_id}")
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["preserved_reference_original"])
        self.assertTrue(original_path.exists())
        self.assertFalse(normalized_path.exists())
        self.assertFalse(chunk_path.exists())
        self.assertFalse(export_path.exists())

    def test_delete_orphan_meeting_succeeds(self) -> None:
        meeting_id = self.services["meeting_repository"].create("Orphan Meeting", "2026-04-13", "Ops", "orphan")

        detail_response = self.client.get(f"/api/v1/meetings/{meeting_id}")
        self.assertEqual(detail_response.status_code, 200)
        self.assertIn("Missing source record", detail_response.json()["integrity_issues"][0])

        delete_response = self.client.delete(f"/api/v1/meetings/{meeting_id}")
        self.assertEqual(delete_response.status_code, 200)
        self.assertIsNone(self.services["meeting_repository"].get(meeting_id))

    def test_delete_meeting_with_running_job_is_blocked(self) -> None:
        meeting_id = self.services["meeting_repository"].create("Running Meeting", "2026-04-13", "Ops", "running")
        self._create_source_record(meeting_id, import_mode="reference")
        job_run_id = self.services["job_run_repository"].create(meeting_id, "preprocess", "running")
        self.services["job_run_repository"].update_state(
            job_run_id,
            status="running",
            stage="normalizing",
            progress_percent=42,
            current_message="running",
        )

        response = self.client.delete(f"/api/v1/meetings/{meeting_id}")
        self.assertEqual(response.status_code, 400)
        self.assertIn("running", response.json()["detail"])

    def test_list_meetings_exposes_integrity_issues_for_missing_reference_source(self) -> None:
        meeting_id = self.services["meeting_repository"].create("Missing Ref", "2026-04-13", "Ops", "missing")
        self._create_source_record(meeting_id, import_mode="reference")
        source_file = self.services["source_file_repository"].get_for_meeting(meeting_id)
        Path(source_file["original_path"]).unlink()

        response = self.client.get("/api/v1/meetings")
        self.assertEqual(response.status_code, 200)
        meeting = next(item for item in response.json() if item["id"] == meeting_id)
        self.assertTrue(any("Reference source file missing" in issue for issue in meeting["integrity_issues"]))

    def test_assigning_speaker_name_updates_transcript_segments(self) -> None:
        meeting_id = self.services["meeting_repository"].create("Speaker Review", "2026-04-13", "Ops", "speaker test")
        self._create_source_record(meeting_id, import_mode="reference")
        self.services["meeting_repository"].update_status(meeting_id, "transcribed")
        preprocessing_job_run_id = self.services["job_run_repository"].create(meeting_id, "preprocess", "seed preprocess")
        preprocessing_run_id = self.services["run_repository"].create(
            meeting_id, preprocessing_job_run_id, self.config.worker_version, {"seeded": True}
        )
        transcription_job_run_id = self.services["job_run_repository"].create(meeting_id, "transcribe", "seed transcribe")
        transcription_run_id = self.services["transcription_run_repository"].create(
            meeting_id=meeting_id,
            preprocessing_run_id=preprocessing_run_id,
            job_run_id=transcription_job_run_id,
            engine="google_speech_to_text_v2",
            engine_model="chirp_3",
            language_code="en-US",
            diarization_enabled=True,
            automatic_punctuation_enabled=True,
            chunk_count=1,
            config_json={"seeded": True},
        )
        self.services["transcript_segment_repository"].replace_for_run(
            transcription_run_id,
            "merged",
            [
                {
                    "meeting_id": meeting_id,
                    "chunk_id": None,
                    "segment_index": 0,
                    "speaker_label": "Speaker 1",
                    "speaker_name": None,
                    "text": "Kickoff note",
                    "start_ms_in_meeting": 0,
                    "end_ms_in_meeting": 1000,
                    "start_ms_in_chunk": None,
                    "end_ms_in_chunk": None,
                    "confidence": 0.9,
                    "source_type": "merged",
                },
                {
                    "meeting_id": meeting_id,
                    "chunk_id": None,
                    "segment_index": 1,
                    "speaker_label": "Speaker 1",
                    "speaker_name": None,
                    "text": "Follow-up note",
                    "start_ms_in_meeting": 1000,
                    "end_ms_in_meeting": 2000,
                    "start_ms_in_chunk": None,
                    "end_ms_in_chunk": None,
                    "confidence": 0.9,
                    "source_type": "merged",
                },
            ],
        )

        response = self.client.patch(
            f"/api/v1/meetings/{meeting_id}/speakers/Speaker%201",
            json={"speaker_name": "Alex"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["speaker_name"], "Alex")
        self.assertEqual(response.json()["updated_segments"], 2)

        transcript = self.client.get(f"/api/v1/meetings/{meeting_id}/transcript")
        self.assertEqual(transcript.status_code, 200)
        self.assertTrue(all(segment["speaker_name"] == "Alex" for segment in transcript.json()["segments"]))

    def _create_valid_wav(self) -> Path:
        output_path = self.temp_dir / "tiny.wav"
        command = (
            f'ffmpeg -y -f lavfi -i "sine=frequency=440:duration=1" "{output_path}"'
        )
        import subprocess

        completed = subprocess.run(command, shell=True, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr)
        return output_path

    def _create_source_record(self, meeting_id: int, *, import_mode: str) -> Path:
        original_path = self.temp_dir / f"meeting_{meeting_id}.wav"
        original_path.write_bytes(b"source")
        self.services["source_file_repository"].create(
            {
                "meeting_id": meeting_id,
                "import_mode": import_mode,
                "original_path": str(original_path),
                "managed_copy_path": None,
                "normalized_audio_path": None,
                "file_name": original_path.name,
                "extension": ".wav",
                "mime_type": "audio/wav",
                "media_type": "audio",
                "size_bytes": original_path.stat().st_size,
                "sha256": sha256_for_file(original_path),
                "duration_ms": 1_000,
                "sample_rate": 16_000,
                "channels": 1,
            }
        )
        self.services["meeting_repository"].update_status(meeting_id, "imported")
        return original_path

    def _create_seeded_meeting(self, *, import_mode: str) -> tuple[int, Path, Path, Path, Path]:
        meeting_id = self.services["meeting_repository"].create("Delete Seed", "2026-04-13", "Ops", "delete test")
        original_path = self.temp_dir / f"meeting_{meeting_id}.wav"
        original_path.write_bytes(b"original")

        managed_copy = self.config.managed_root / f"meeting_{meeting_id}" / original_path.name
        normalized_path = self.config.normalized_root / f"meeting_{meeting_id}" / "run_1" / "normalized.flac"
        chunk_path = self.config.chunks_root / f"meeting_{meeting_id}" / "run_1" / "chunk_000.flac"
        export_path = self.config.exports_root / f"meeting_{meeting_id}" / "minutes.docx"
        for path in [managed_copy, normalized_path, chunk_path, export_path]:
            ensure_directory(path.parent)
            path.write_bytes(path.name.encode("utf-8"))

        self.services["source_file_repository"].create(
            {
                "meeting_id": meeting_id,
                "import_mode": import_mode,
                "original_path": str(original_path),
                "managed_copy_path": str(managed_copy) if import_mode == "managed_copy" else None,
                "normalized_audio_path": str(normalized_path),
                "file_name": original_path.name,
                "extension": ".wav",
                "mime_type": "audio/wav",
                "media_type": "audio",
                "size_bytes": original_path.stat().st_size,
                "sha256": sha256_for_file(original_path),
                "duration_ms": 1_000,
                "sample_rate": 16_000,
                "channels": 1,
            }
        )
        self.services["meeting_repository"].update_status(meeting_id, "prepared")
        job_run_id = self.services["job_run_repository"].create(meeting_id, "preprocess", "seeded")
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
            silence_map={"candidate_count": 0, "candidates": []},
            chunk_strategy={"coverage_validation": {"covers_full_duration": True}},
            waveform_summary={"buckets": [0.1]},
        )
        self.services["job_run_repository"].finalize(
            job_run_id,
            status="completed",
            stage="completed",
            current_message="done",
            error_message=None,
        )
        self.services["chunk_repository"].replace_for_run(
            preprocessing_run_id,
            [
                {
                    "meeting_id": meeting_id,
                    "chunk_index": 0,
                    "file_path": str(chunk_path),
                    "sha256": sha256_for_file(chunk_path),
                    "start_ms": 0,
                    "end_ms": 1_000,
                    "overlap_before_ms": 0,
                    "overlap_after_ms": 0,
                    "duration_ms": 1_000,
                    "boundary_reason": "final_tail",
                    "status": "prepared",
                }
            ],
        )
        self.services["artifact_repository"].upsert(
            {
                "meeting_id": meeting_id,
                "preprocessing_run_id": preprocessing_run_id,
                "transcription_run_id": None,
                "extraction_run_id": None,
                "artifact_type": "audio",
                "role": "normalized audio",
                "path": str(normalized_path),
                "mime_type": "audio/flac",
                "sha256": sha256_for_file(normalized_path),
                "size_bytes": normalized_path.stat().st_size,
                "metadata_json": {},
            }
        )
        export_run_id = self.services["export_run_repository"].create(
            meeting_id=meeting_id,
            export_profile="formal_minutes_pack",
            format="docx",
            options_json={"reviewed_only": True},
            file_path=str(export_path),
        )
        self.services["export_run_repository"].finalize_success(export_run_id, file_path=str(export_path))
        return meeting_id, managed_copy if import_mode == "managed_copy" else original_path, normalized_path, chunk_path, export_path


if __name__ == "__main__":
    unittest.main()
