from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.repositories.meetings import SettingsRepository


@dataclass(frozen=True)
class GeminiSettings:
    auth_mode: str
    api_key_env_var: str
    api_key_file_path: str | None
    api_base_url: str
    model: str
    extraction_model: str
    minutes_model: str
    fallback_model: str | None
    thinking_level: str
    temperature: float
    response_mime_type: str
    max_segments_per_batch: int
    max_evidence_items_per_entity: int
    low_confidence_threshold: float


class GeminiApiService:
    def __init__(
        self,
        settings_repository: SettingsRepository,
        request_callable: Callable[..., Any] | None = None,
    ) -> None:
        self.settings_repository = settings_repository
        self.request_callable = request_callable or urlopen

    def get_settings(self) -> GeminiSettings:
        settings_map = {row["key"]: row["value_json"] for row in self.settings_repository.list()}
        payload = settings_map.get("gemini_defaults", {})
        return GeminiSettings(
            auth_mode=str(payload.get("auth_mode", "api_key_env")).strip() or "api_key_env",
            api_key_env_var=str(payload.get("api_key_env_var", "GEMINI_API_KEY")).strip() or "GEMINI_API_KEY",
            api_key_file_path=_string_or_none(payload.get("api_key_file_path")),
            api_base_url=str(payload.get("api_base_url", "https://generativelanguage.googleapis.com/v1beta")).rstrip("/"),
            model=str(payload.get("model", "gemini-3-flash-preview")).strip() or "gemini-3-flash-preview",
            extraction_model=str(payload.get("extraction_model", payload.get("model", "gemini-3.1-pro-preview"))).strip() or "gemini-3.1-pro-preview",
            minutes_model=str(payload.get("minutes_model", payload.get("model", "gemini-3.1-pro-preview"))).strip() or "gemini-3.1-pro-preview",
            fallback_model=_string_or_none(payload.get("fallback_model")),
            thinking_level=str(payload.get("thinking_level", "medium")).strip() or "medium",
            temperature=float(payload.get("temperature", 1.0)),
            response_mime_type=str(payload.get("response_mime_type", "text/plain")).strip() or "text/plain",
            max_segments_per_batch=max(10, int(payload.get("max_segments_per_batch", 80))),
            max_evidence_items_per_entity=max(1, int(payload.get("max_evidence_items_per_entity", 5))),
            low_confidence_threshold=float(payload.get("low_confidence_threshold", 0.7)),
        )

    def validate_runtime(self) -> GeminiSettings:
        settings = self.get_settings()
        if not settings.model:
            raise RuntimeError("Gemini model is not configured")
        self._resolve_api_key(settings)
        return settings

    def generate_content(
        self,
        *,
        prompt: str,
        system_instruction: str | None = None,
        model: str | None = None,
        response_mime_type: str | None = None,
        thinking_level: str | None = None,
        temperature: float | None = None,
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        settings = self.get_settings()
        api_key = self._resolve_api_key(settings)
        selected_model = model or settings.model
        selected_response_mime = response_mime_type or settings.response_mime_type
        selected_thinking_level = thinking_level or settings.thinking_level
        selected_temperature = settings.temperature if temperature is None else temperature

        payload: dict[str, Any] = {
            "contents": [
                {
                    "parts": [
                        {
                            "text": prompt,
                        }
                    ]
                }
            ],
            "generationConfig": {
                "responseMimeType": selected_response_mime,
                "temperature": selected_temperature,
                "thinkingConfig": {
                    "thinkingLevel": selected_thinking_level,
                },
            },
        }
        if response_schema:
            payload["generationConfig"]["responseSchema"] = response_schema
        if system_instruction:
            payload["system_instruction"] = {
                "parts": [
                    {
                        "text": system_instruction,
                    }
                ]
            }

        url = f"{settings.api_base_url}/models/{selected_model}:generateContent"
        request = Request(
            url=url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            method="POST",
        )

        try:
            with self.request_callable(request, timeout=120) as response:
                raw_body = response.read().decode("utf-8")
        except HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace") if hasattr(exc, "read") else str(exc)
            raise RuntimeError(f"Gemini API request failed with HTTP {exc.code}: {error_body}") from exc
        except URLError as exc:
            raise RuntimeError(f"Gemini API request failed: {exc.reason}") from exc

        raw_response = json.loads(raw_body)
        text = _extract_text(raw_response)
        parsed_json: Any | None = None
        if selected_response_mime == "application/json" and text:
            try:
                parsed_json = json.loads(text)
            except json.JSONDecodeError:
                parsed_json = None

        return {
            "model": selected_model,
            "response_mime_type": selected_response_mime,
            "thinking_level": selected_thinking_level,
            "text": text,
            "json": parsed_json,
            "raw_response": raw_response,
            "request_payload": payload,
        }

    def _resolve_api_key(self, settings: GeminiSettings) -> str:
        if settings.auth_mode == "api_key_env":
            api_key = os.environ.get(settings.api_key_env_var, "").strip()
            if not api_key:
                raise RuntimeError(
                    f"Gemini API key not found in environment variable {settings.api_key_env_var}"
                )
            return api_key

        if settings.auth_mode == "api_key_file":
            if not settings.api_key_file_path:
                raise RuntimeError("Gemini api_key_file_path is required when auth_mode is api_key_file")
            api_key_path = Path(settings.api_key_file_path)
            if not api_key_path.exists():
                raise RuntimeError(f"Gemini API key file does not exist: {api_key_path}")
            api_key = api_key_path.read_text(encoding="utf-8").strip()
            if not api_key:
                raise RuntimeError(f"Gemini API key file is empty: {api_key_path}")
            return api_key

        raise RuntimeError(f"Unsupported Gemini auth_mode: {settings.auth_mode}")


def _extract_text(raw_response: dict[str, Any]) -> str:
    candidates = raw_response.get("candidates") or []
    texts: list[str] = []
    for candidate in candidates:
        content = candidate.get("content") or {}
        parts = content.get("parts") or []
        for part in parts:
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                texts.append(text.strip())
    return "\n".join(texts)


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
