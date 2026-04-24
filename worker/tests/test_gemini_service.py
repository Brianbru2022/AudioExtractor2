import io
import json
import os
import unittest

from app.services.gemini.service import GeminiApiService
from tests._support import IsolatedWorkerApp


class _FakeResponse:
    def __init__(self, payload: dict):
        self._buffer = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def read(self) -> bytes:
        return self._buffer.read()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class GeminiApiServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.worker = IsolatedWorkerApp(prefix="audio-extractor-gemini-tests-").start()
        self.settings_repository = self.worker.services["settings_repository"]
        current = next((row for row in self.settings_repository.list() if row["key"] == "gemini_defaults"), None)
        self.original_settings = current["value_json"] if current else None
        self.settings_repository.upsert(
            "gemini_defaults",
            {
                "auth_mode": "api_key_env",
                "api_key_env_var": "GEMINI_API_KEY",
                "api_base_url": "https://generativelanguage.googleapis.com/v1beta",
                "model": "gemini-3-flash-preview",
                "thinking_level": "medium",
                "temperature": 1.0,
                "response_mime_type": "application/json",
            },
        )
        self.previous_key = os.environ.get("GEMINI_API_KEY")
        os.environ["GEMINI_API_KEY"] = "test-key"

    def tearDown(self) -> None:
        if self.original_settings is not None:
            self.settings_repository.upsert("gemini_defaults", self.original_settings)
        if self.previous_key is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = self.previous_key
        self.worker.stop()

    def test_generate_content_extracts_text_and_json(self) -> None:
        observed = {}

        def fake_request(request, timeout=120):
            observed["url"] = request.full_url
            observed["headers"] = dict(request.headers)
            observed["body"] = json.loads(request.data.decode("utf-8"))
            return _FakeResponse(
                {
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "text": '{"ok": true, "message": "hello"}',
                                    }
                                ]
                            }
                        }
                    ]
                }
            )

        service = GeminiApiService(self.settings_repository, request_callable=fake_request)
        result = service.generate_content(
            prompt="Say hello",
            system_instruction="Return JSON",
        )

        self.assertEqual(observed["url"], "https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent")
        self.assertEqual(observed["headers"]["X-goog-api-key"], "test-key")
        self.assertEqual(observed["body"]["contents"][0]["parts"][0]["text"], "Say hello")
        self.assertEqual(result["json"], {"ok": True, "message": "hello"})
        self.assertEqual(result["model"], "gemini-3-flash-preview")

    def test_missing_env_key_fails_clearly(self) -> None:
        os.environ.pop("GEMINI_API_KEY", None)
        service = GeminiApiService(self.settings_repository, request_callable=lambda request, timeout=120: _FakeResponse({}))
        with self.assertRaisesRegex(RuntimeError, "Gemini API key not found"):
            service.generate_content(prompt="Hello")

    def test_validate_runtime_fails_clearly_when_key_missing(self) -> None:
        os.environ.pop("GEMINI_API_KEY", None)
        service = GeminiApiService(self.settings_repository, request_callable=lambda request, timeout=120: _FakeResponse({}))
        with self.assertRaisesRegex(RuntimeError, "Gemini API key not found"):
            service.validate_runtime()


if __name__ == "__main__":
    unittest.main()
