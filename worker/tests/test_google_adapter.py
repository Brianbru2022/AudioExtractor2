import json
import tempfile
import unittest
from pathlib import Path

from app.services.transcription.google_adapter import GoogleSpeechV2Adapter, _parse_batch_recognize_response
from app.services.transcription.models import TranscriptionSettings


class GoogleSpeechV2AdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = GoogleSpeechV2Adapter()

    def test_validate_runtime_reports_installed_packages(self) -> None:
        settings = self._settings(auth_mode="application_default_credentials", credentials_path="")
        versions = self.adapter.validate_runtime(settings)
        self.assertIn("google-cloud-speech", versions)
        self.assertIn("google-cloud-storage", versions)
        self.assertIn("protobuf", versions)
        self.assertIn("google-auth", versions)

    def test_validate_runtime_rejects_invalid_credentials_file(self) -> None:
        credentials_path = self._write_credentials_stub('{"type":"service_account","project_id":"test-project","private_key":"INVALID"}')
        settings = self._settings(credentials_path=credentials_path)
        with self.assertRaisesRegex(RuntimeError, "invalid or unreadable"):
            self.adapter.validate_runtime(settings)

    def test_parse_batch_response_handles_inline_result_shape(self) -> None:
        raw_response = {
            "results": {
                "gs://bucket/chunk_000.flac": {
                    "inline_result": {
                        "transcript": {
                            "results": [
                                {
                                    "alternatives": [
                                        {
                                            "transcript": "Hello team",
                                            "confidence": 0.91,
                                            "words": [
                                                {
                                                    "word": "Hello",
                                                    "start_offset": "0.000s",
                                                    "end_offset": "0.420s",
                                                    "speaker_label": "speaker_1",
                                                    "confidence": 0.95,
                                                },
                                                {
                                                    "word": "team",
                                                    "start_offset": "0.500s",
                                                    "end_offset": "0.920s",
                                                    "speaker_label": "speaker_1",
                                                    "confidence": 0.94,
                                                },
                                            ],
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                }
            }
        }

        transcript_text, average_confidence, segments = _parse_batch_recognize_response(raw_response)
        self.assertEqual(transcript_text, "Hello team")
        self.assertEqual(average_confidence, 0.91)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].speaker_label, "speaker_1")
        self.assertEqual(segments[0].text, "Hello team")

    def test_parse_batch_response_handles_inline_result_camel_case_shape(self) -> None:
        raw_response = {
            "results": [
                {
                    "inlineResult": {
                        "results": [
                            {
                                "alternatives": [
                                    {
                                        "transcript": "Status update",
                                        "confidence": 0.8,
                                    }
                                ],
                                "resultEndOffset": "2.000s",
                            }
                        ]
                    }
                }
            ]
        }
        transcript_text, average_confidence, segments = _parse_batch_recognize_response(raw_response)
        self.assertEqual(transcript_text, "Status update")
        self.assertEqual(average_confidence, 0.8)
        self.assertEqual(len(segments), 1)
        self.assertEqual(segments[0].start_ms_in_chunk, 0)
        self.assertEqual(segments[0].end_ms_in_chunk, 2000)

    def test_parse_batch_response_normalizes_out_of_range_word_offsets(self) -> None:
        raw_response = {
            "results": {
                "gs://bucket/chunk_000.flac": {
                    "inline_result": {
                        "transcript": {
                            "results": [
                                {
                                    "alternatives": [
                                        {
                                            "transcript": "Hello. Good morning. How are you?",
                                            "words": [
                                                {"word": "Hello.", "start_offset": "9s", "end_offset": "9.120s", "speaker_label": "1"},
                                                {"word": "Good", "start_offset": "9.240s", "end_offset": "9.360s", "speaker_label": "2"},
                                                {"word": "morning.", "start_offset": "9.360s", "end_offset": "9.560s", "speaker_label": "2"},
                                                {"word": "How", "start_offset": "10.280s", "end_offset": "10.360s", "speaker_label": "1"},
                                                {"word": "are", "start_offset": "10.360s", "end_offset": "10.440s", "speaker_label": "1"},
                                                {"word": "you?", "start_offset": "10.440s", "end_offset": "10.520s", "speaker_label": "1"},
                                            ],
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                }
            }
        }

        transcript_text, average_confidence, segments = _parse_batch_recognize_response(
            raw_response,
            chunk_duration_ms=7000,
        )
        self.assertEqual(transcript_text, "Hello. Good morning. How are you?")
        self.assertIsNone(average_confidence)
        self.assertEqual(len(segments), 3)
        self.assertEqual(segments[0].start_ms_in_chunk, 0)
        self.assertEqual(segments[0].end_ms_in_chunk, 120)
        self.assertEqual(segments[1].start_ms_in_chunk, 240)
        self.assertEqual(segments[2].start_ms_in_chunk, 1280)

    def test_parse_batch_response_drops_malformed_and_punctuation_only_words(self) -> None:
        raw_response = {
            "results": {
                "gs://bucket/chunk_000.flac": {
                    "inline_result": {
                        "transcript": {
                            "results": [
                                {
                                    "alternatives": [
                                        {
                                            "transcript": "[ Good morning. Respond in English.",
                                            "words": [
                                                {"word": "[", "end_offset": "1.560s", "speaker_label": "0"},
                                                {"word": "Good", "start_offset": "1.600s", "end_offset": "1.720s", "speaker_label": "0"},
                                                {"word": "morning.", "start_offset": "1.720s", "end_offset": "1.880s", "speaker_label": "0"},
                                                {"word": "Respond", "start_offset": "22.720s", "end_offset": "9.240s", "speaker_label": "2"},
                                                {"word": "in", "start_offset": "9.240s", "end_offset": "9.320s", "speaker_label": "2"},
                                                {"word": "English.", "start_offset": "10.520s", "end_offset": "10.840s", "speaker_label": "2"},
                                            ],
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                }
            }
        }

        transcript_text, average_confidence, segments = _parse_batch_recognize_response(
            raw_response,
            chunk_duration_ms=720_000,
        )
        self.assertEqual(transcript_text, "[ Good morning. Respond in English.")
        self.assertIsNone(average_confidence)
        self.assertEqual(len(segments), 2)
        self.assertEqual(segments[0].text, "Good morning.")
        self.assertEqual(segments[1].text, "in English.")
        self.assertEqual(segments[0].start_ms_in_chunk, 1600)
        self.assertEqual(segments[0].end_ms_in_chunk, 1880)
        self.assertEqual(segments[1].start_ms_in_chunk, 9240)
        self.assertEqual(segments[1].end_ms_in_chunk, 10840)

    def _settings(self, *, auth_mode: str = "credentials_file", credentials_path: str) -> TranscriptionSettings:
        return TranscriptionSettings(
            project_id="test-project",
            auth_mode=auth_mode,
            credentials_path=credentials_path,
            recognizer_location="global",
            recognizer_id="_",
            staging_bucket="test-audio-extractor-bucket",
            staging_prefix="audio-extractor-2",
            model="chirp_3",
            language_code="en-US",
            alternative_language_codes=[],
            diarization_enabled=True,
            min_speaker_count=2,
            max_speaker_count=4,
            automatic_punctuation_enabled=True,
            profanity_filter_enabled=False,
            enable_word_time_offsets=True,
            enable_word_confidence=True,
            max_parallel_chunks=1,
            phrase_hints_placeholder=[],
            low_confidence_threshold=0.7,
        )

    def _write_credentials_stub(self, content: str) -> str:
        path = Path(tempfile.gettempdir()) / "audio-extractor-google-adapter-test.json"
        path.write_text(content, encoding="utf-8")
        return str(path)


if __name__ == "__main__":
    unittest.main()
