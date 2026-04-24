from __future__ import annotations

from pathlib import Path
from typing import Any

from app.repositories.meetings import SettingsRepository
from app.services.transcription.models import TranscriptionSettings


class TranscriptionSettingsService:
    def __init__(self, settings_repository: SettingsRepository) -> None:
        self.settings_repository = settings_repository

    def get(self) -> TranscriptionSettings:
        rows = self.settings_repository.list()
        settings_map = {row["key"]: row["value_json"] for row in rows}
        payload = settings_map.get("transcription_defaults", {})
        return TranscriptionSettings(
            project_id=str(payload.get("project_id", "")).strip(),
            auth_mode=str(payload.get("auth_mode", "application_default_credentials")).strip(),
            credentials_path=_string_or_none(payload.get("credentials_path")),
            recognizer_location=str(payload.get("recognizer_location", "global")).strip() or "global",
            recognizer_id=str(payload.get("recognizer_id", "_")).strip() or "_",
            staging_bucket=str(payload.get("staging_bucket", "")).strip(),
            staging_prefix=str(payload.get("staging_prefix", "audio-extractor-2")).strip() or "audio-extractor-2",
            model=str(payload.get("model", "chirp_3")).strip() or "chirp_3",
            language_code=str(payload.get("language_code", "en-US")).strip() or "en-US",
            alternative_language_codes=_list_of_strings(payload.get("alternative_language_codes")),
            diarization_enabled=bool(payload.get("diarization_enabled", True)),
            min_speaker_count=max(1, int(payload.get("min_speaker_count", 2))),
            max_speaker_count=max(1, int(payload.get("max_speaker_count", 8))),
            automatic_punctuation_enabled=bool(payload.get("automatic_punctuation_enabled", True)),
            profanity_filter_enabled=bool(payload.get("profanity_filter_enabled", False)),
            enable_word_time_offsets=bool(payload.get("enable_word_time_offsets", True)),
            enable_word_confidence=bool(payload.get("enable_word_confidence", True)),
            max_parallel_chunks=max(1, int(payload.get("max_parallel_chunks", 2))),
            phrase_hints_placeholder=_list_of_strings(payload.get("phrase_hints_placeholder")),
            low_confidence_threshold=float(payload.get("low_confidence_threshold", 0.7)),
        )

    def validate(self, settings: TranscriptionSettings) -> None:
        if not settings.project_id:
            raise ValueError("Google Cloud project_id is required in transcription settings")
        if settings.project_id.lower() in {"demo-project", "your-project-id", "project-id"}:
            raise ValueError("Google Cloud project_id is still set to a placeholder value")
        if not settings.staging_bucket:
            raise ValueError("Google Cloud Storage staging_bucket is required for Speech-to-Text V2 batch transcription")
        if settings.staging_bucket.lower() in {"demo-bucket", "your-bucket", "bucket-name"}:
            raise ValueError("Google Cloud Storage staging_bucket is still set to a placeholder value")
        if settings.auth_mode == "credentials_file" and not settings.credentials_path:
            raise ValueError("credentials_path is required when auth_mode is credentials_file")
        if settings.auth_mode == "credentials_file" and settings.credentials_path:
            credentials_path = Path(settings.credentials_path)
            if not credentials_path.exists():
                raise ValueError(f"credentials_path does not exist: {credentials_path}")
        if settings.auth_mode == "application_default_credentials":
            self._validate_application_default_credentials()
        if settings.max_speaker_count < settings.min_speaker_count:
            raise ValueError("max_speaker_count must be greater than or equal to min_speaker_count")
        if settings.model == "chirp_3" and settings.recognizer_location == "global":
            raise ValueError(
                "chirp_3 is not available in recognizer_location=global. Use a supported location such as us or eu."
            )

    @staticmethod
    def _validate_application_default_credentials() -> None:
        try:
            import google.auth
            from google.auth.exceptions import DefaultCredentialsError
        except ImportError:
            return

        try:
            google.auth.default()
        except DefaultCredentialsError as exc:
            raise ValueError(
                "Application Default Credentials are not available. Set GOOGLE_APPLICATION_CREDENTIALS or switch transcription auth_mode to credentials_file."
            ) from exc


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _list_of_strings(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [item.strip() for item in value.split(",") if item.strip()]
    return []
