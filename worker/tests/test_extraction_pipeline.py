import shutil
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
import os

from app.utils.files import sha256_for_file
from tests._support import IsolatedWorkerApp


class ScriptedGeminiExtractionService:
    def __init__(self, segment_ids: list[int], pass1_payloads: list[dict], pass2_payload: dict | None = None) -> None:
        self.calls = 0
        self.segment_ids = segment_ids
        self.pass1_payloads = list(pass1_payloads)
        self.pass2_payload = pass2_payload or {
            "executive_summary": "The meeting aligned on a phased rollout and highlighted the need for an updated timeline.",
            "formal_minutes": "Decision: proceed with the phased rollout.\nAction: draft the revised implementation timeline.",
        }

    def get_settings(self):
        return SimpleNamespace(
            model="gemini-3.1-pro-preview",
            extraction_model="gemini-3.1-pro-preview",
            minutes_model="gemini-3.1-pro-preview",
            thinking_level="medium",
            max_segments_per_batch=4,
            max_evidence_items_per_entity=5,
            low_confidence_threshold=0.7,
        )

    def validate_runtime(self):
        return self.get_settings()

    def generate_content(self, **kwargs):
        self.calls += 1
        prompt = str(kwargs.get("prompt") or "")
        if "validated_extraction" in prompt:
            return {"json": self.pass2_payload, "raw_response": {"pass": 2, "call": self.calls}}
        index = min(self.calls - 1, len(self.pass1_payloads) - 1)
        return {"json": self.pass1_payloads[index], "raw_response": {"pass": 1, "call": self.calls}}


class ExtractionPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.worker = IsolatedWorkerApp(prefix="audio-extractor-phase3-").start()
        self.client = self.worker.client
        self.services = self.worker.services
        self.temp_dir = Path(tempfile.mkdtemp(prefix="audio-extractor-phase3-"))
        self.original_gemini = self.services["extraction_service"].gemini_service
        current = next((row for row in self.services["settings_repository"].list() if row["key"] == "gemini_defaults"), None)
        self.original_settings = current["value_json"] if current else None

    def tearDown(self) -> None:
        self.services["extraction_service"].gemini_service = self.original_gemini
        if self.original_settings is not None:
            self.services["settings_repository"].upsert("gemini_defaults", self.original_settings)
        self.worker.stop()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_extraction_persists_evidence_backed_outputs(self) -> None:
        meeting_id, segment_ids = self._create_transcribed_meeting(
            [
                "Let's proceed with the phased rollout.",
                "We still need a revised implementation timeline.",
                "Can we still hit the beta date without more staffing?",
            ]
        )
        self.services["extraction_service"].gemini_service = ScriptedGeminiExtractionService(
            segment_ids,
            pass1_payloads=[
                {
                    "decisions": [
                        {
                            "text": "Proceed with the phased rollout.",
                            "confidence": 0.93,
                            "explicit_or_inferred": "explicit",
                            "evidence": [
                                {
                                    "transcript_segment_id": segment_ids[0],
                                    "start_ms": 0,
                                    "end_ms": 14000,
                                    "speaker_label": "speaker_1",
                                    "quote_snippet": "Let's proceed with the phased rollout.",
                                    "confidence": 0.9,
                                }
                            ],
                        }
                    ],
                    "action_items": [
                        {
                            "text": "Draft the revised implementation timeline.",
                            "owner": None,
                            "due_date": None,
                            "priority": "high",
                            "confidence": 0.84,
                            "explicit_or_inferred": "inferred",
                            "evidence": [
                                {
                                    "transcript_segment_id": segment_ids[1],
                                    "start_ms": 15000,
                                    "end_ms": 29000,
                                    "speaker_label": "speaker_2",
                                    "quote_snippet": "We still need a revised implementation timeline.",
                                    "confidence": 0.82,
                                }
                            ],
                        }
                    ],
                    "risks_issues": [],
                    "open_questions": [
                        {
                            "text": "Can we hit the current beta date without more staffing?",
                            "confidence": 0.8,
                            "explicit_or_inferred": "explicit",
                            "evidence": [
                                {
                                    "transcript_segment_id": segment_ids[2],
                                    "start_ms": 30000,
                                    "end_ms": 43000,
                                    "speaker_label": "speaker_1",
                                    "quote_snippet": "Can we still hit the beta date without more staffing?",
                                    "confidence": 0.78,
                                }
                            ],
                        }
                    ],
                    "key_discussion_topics": [
                        {
                            "text": "Phased rollout planning",
                            "confidence": 0.88,
                            "explicit_or_inferred": "explicit",
                            "evidence": [
                                {
                                    "transcript_segment_id": segment_ids[0],
                                    "start_ms": 0,
                                    "end_ms": 14000,
                                    "speaker_label": "speaker_1",
                                    "quote_snippet": "Let's proceed with the phased rollout.",
                                    "confidence": 0.88,
                                }
                            ],
                        }
                    ],
                }
            ],
        )

        response = self.client.post(f"/api/v1/meetings/{meeting_id}/extract")
        self.assertEqual(response.status_code, 200)

        insights = self._wait_for_insights(meeting_id)
        self.assertEqual(insights["run"]["status"], "completed")
        self.assertEqual(len(insights["actions"]), 1)
        self.assertEqual(len(insights["decisions"]), 1)
        self.assertEqual(len(insights["questions"]), 1)
        self.assertEqual(len(insights["topics"]), 1)
        self.assertEqual(insights["actions"][0]["owner"], None)
        self.assertEqual(insights["actions"][0]["due_date"], None)
        self.assertIsInstance(insights["actions"][0]["evidence"][0]["transcript_segment_id"], int)
        self.assertIn("phased rollout", insights["summary"]["summary_text"].lower())

    def test_duplicate_actions_are_collapsed_and_unsupported_owner_due_date_are_cleared(self) -> None:
        meeting_id, segment_ids = self._create_transcribed_meeting(
            [
                "We need the revised launch plan before the board review.",
                "The revised launch plan still needs to be drafted before the board review.",
                "Let's proceed with the phased rollout.",
            ]
        )
        self.services["extraction_service"].gemini_service = ScriptedGeminiExtractionService(
            segment_ids,
            pass1_payloads=[
                {
                    "decisions": [
                        {
                            "text": "Proceed with the phased rollout.",
                            "confidence": 0.91,
                            "explicit_or_inferred": "explicit",
                            "evidence": [
                                {
                                    "transcript_segment_id": segment_ids[2],
                                    "start_ms": 30000,
                                    "end_ms": 43000,
                                    "speaker_label": "speaker_1",
                                    "quote_snippet": "Let's proceed with the phased rollout.",
                                    "confidence": 0.91,
                                }
                            ],
                        }
                    ],
                    "action_items": [
                        {
                            "text": "Draft the revised launch plan before the board review.",
                            "owner": "Alex",
                            "due_date": "Friday",
                            "priority": "high",
                            "confidence": 0.62,
                            "explicit_or_inferred": "inferred",
                            "evidence": [
                                {
                                    "transcript_segment_id": segment_ids[0],
                                    "start_ms": 0,
                                    "end_ms": 14000,
                                    "speaker_label": "speaker_1",
                                    "quote_snippet": "We need the revised launch plan before the board review.",
                                    "confidence": 0.62,
                                }
                            ],
                        },
                        {
                            "text": "Draft the revised launch plan before the board review",
                            "owner": "Alex",
                            "due_date": "Friday",
                            "priority": "high",
                            "confidence": 0.78,
                            "explicit_or_inferred": "inferred",
                            "evidence": [
                                {
                                    "transcript_segment_id": segment_ids[1],
                                    "start_ms": 15000,
                                    "end_ms": 29000,
                                    "speaker_label": "speaker_2",
                                    "quote_snippet": "The revised launch plan still needs to be drafted before the board review.",
                                    "confidence": 0.78,
                                }
                            ],
                        },
                    ],
                    "risks_issues": [],
                    "open_questions": [],
                    "key_discussion_topics": [],
                }
            ],
        )

        response = self.client.post(f"/api/v1/meetings/{meeting_id}/extract")
        self.assertEqual(response.status_code, 200)
        insights = self._wait_for_insights(meeting_id)

        self.assertEqual(len(insights["actions"]), 1)
        action = insights["actions"][0]
        self.assertEqual(action["owner"], None)
        self.assertEqual(action["due_date"], None)
        self.assertTrue(action["needs_review"])
        self.assertGreaterEqual(len(action["evidence"]), 2)
        self.assertEqual(sorted({item["transcript_segment_id"] for item in action["evidence"]}), sorted(segment_ids[:2]))

    def test_patch_action_updates_review_status_and_text(self) -> None:
        meeting_id, segment_ids = self._create_transcribed_meeting(
            [
                "Please update the revised implementation timeline.",
                "We should proceed with the phased rollout.",
            ]
        )
        self.services["extraction_service"].gemini_service = ScriptedGeminiExtractionService(
            segment_ids,
            pass1_payloads=[
                {
                    "decisions": [],
                    "action_items": [
                        {
                            "text": "Update the revised implementation timeline.",
                            "owner": None,
                            "due_date": None,
                            "priority": None,
                            "confidence": 0.85,
                            "explicit_or_inferred": "explicit",
                            "evidence": [
                                {
                                    "transcript_segment_id": segment_ids[0],
                                    "start_ms": 0,
                                    "end_ms": 14000,
                                    "quote_snippet": "Please update the revised implementation timeline.",
                                    "confidence": 0.85,
                                }
                            ],
                        }
                    ],
                    "risks_issues": [],
                    "open_questions": [],
                    "key_discussion_topics": [],
                }
            ],
        )

        self.client.post(f"/api/v1/meetings/{meeting_id}/extract")
        insights = self._wait_for_insights(meeting_id)
        action_id = insights["actions"][0]["id"]
        patch_response = self.client.patch(
            f"/api/v1/insights/actions/{action_id}",
            json={"review_status": "accepted", "owner": "PM", "text": "Update the launch timeline."},
        )
        self.assertEqual(patch_response.status_code, 200)
        self.assertEqual(patch_response.json()["review_status"], "accepted")
        self.assertEqual(patch_response.json()["owner"], "PM")
        self.assertEqual(patch_response.json()["text"], "Update the launch timeline.")

    def test_missing_gemini_key_blocks_extraction_before_enqueue(self) -> None:
        previous_key = os.environ.pop("GEMINI_API_KEY", None)
        try:
            self.services["settings_repository"].upsert(
                "gemini_defaults",
                {
                    "auth_mode": "api_key_env",
                    "api_key_env_var": "GEMINI_API_KEY",
                    "api_base_url": "https://generativelanguage.googleapis.com/v1beta",
                    "model": "gemini-3.1-pro-preview",
                    "thinking_level": "medium",
                    "temperature": 1.0,
                    "response_mime_type": "application/json",
                },
            )
            meeting_id, _ = self._create_transcribed_meeting(
                ["We agreed to proceed with the phased rollout."]
            )
            response = self.client.post(f"/api/v1/meetings/{meeting_id}/extract")
            self.assertEqual(response.status_code, 400)
            self.assertIn("Gemini API key not found", response.json()["detail"])
        finally:
            if previous_key is not None:
                os.environ["GEMINI_API_KEY"] = previous_key

    def _create_transcribed_meeting(self, segment_texts: list[str]) -> tuple[int, list[int]]:
        meeting_id = self.services["meeting_repository"].create(
            "Extraction Seed",
            "2026-04-10",
            "Phase 3",
            "Seeded extraction meeting",
        )
        source_path = self.temp_dir / f"meeting_{meeting_id}.wav"
        source_path.write_bytes(b"seed-source")
        normalized_path = self.temp_dir / f"meeting_{meeting_id}.flac"
        normalized_path.write_bytes(b"normalized-source")
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
                "duration_ms": 60_000,
                "sample_rate": 16000,
                "channels": 1,
            }
        )
        self.services["meeting_repository"].update_status(meeting_id, "transcribed")

        preprocess_job_id = self.services["job_run_repository"].create(meeting_id, "preprocess", "seeded preprocessing")
        preprocessing_run_id = self.services["run_repository"].create(
            meeting_id,
            preprocess_job_id,
            "0.3.0",
            {"target_ms": 600000},
        )
        self.services["run_repository"].finalize_success(
            preprocessing_run_id,
            normalized_format="flac",
            normalized_sample_rate=16000,
            normalized_channels=1,
            silence_map={"candidate_count": 0},
            chunk_strategy={"coverage_validation": {"covers_full_duration": True}},
            waveform_summary={"buckets": [0.1]},
        )
        self.services["job_run_repository"].finalize(
            preprocess_job_id,
            status="completed",
            stage="completed",
            current_message="done",
            error_message=None,
        )

        transcribe_job_id = self.services["job_run_repository"].create(meeting_id, "transcribe", "seeded transcription")
        transcription_run_id = self.services["transcription_run_repository"].create(
            meeting_id=meeting_id,
            preprocessing_run_id=preprocessing_run_id,
            job_run_id=transcribe_job_id,
            engine="fake",
            engine_model="fake",
            language_code="en-US",
            diarization_enabled=True,
            automatic_punctuation_enabled=True,
            chunk_count=1,
            config_json={"low_confidence_threshold": 0.7},
        )
        self.services["transcription_run_repository"].mark_running(transcription_run_id)
        self.services["transcription_run_repository"].finalize_success(transcription_run_id, average_confidence=0.91)
        self.services["job_run_repository"].finalize(
            transcribe_job_id,
            status="completed",
            stage="completed",
            current_message="done",
            error_message=None,
        )

        merged_segments = []
        for index, text in enumerate(segment_texts):
            start_ms = index * 15_000
            end_ms = start_ms + 14_000
            merged_segments.append(
                {
                    "meeting_id": meeting_id,
                    "chunk_id": None,
                    "segment_index": index,
                    "speaker_label": f"speaker_{(index % 2) + 1}",
                    "speaker_name": None,
                    "text": text,
                    "start_ms_in_meeting": start_ms,
                    "end_ms_in_meeting": end_ms,
                    "start_ms_in_chunk": None,
                    "end_ms_in_chunk": None,
                    "confidence": 0.82 + (index * 0.02),
                }
            )
        self.services["transcript_segment_repository"].replace_for_run(
            transcription_run_id,
            "merged",
            merged_segments,
        )
        segment_rows = self.services["transcript_segment_repository"].list_for_run(transcription_run_id, "merged")
        return meeting_id, [segment["id"] for segment in segment_rows]

    def _wait_for_insights(self, meeting_id: int) -> dict:
        for _ in range(80):
            response = self.client.get(f"/api/v1/meetings/{meeting_id}/insights")
            if response.status_code == 200:
                payload = response.json()
                if payload["run"]["status"] == "completed":
                    return payload
            time.sleep(0.1)
        self.fail("Timed out waiting for extraction insights")


if __name__ == "__main__":
    unittest.main()
