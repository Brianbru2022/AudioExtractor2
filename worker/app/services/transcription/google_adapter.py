from __future__ import annotations

import importlib.metadata
import os
import time
from typing import Any
from uuid import uuid4

from app.services.transcription.models import (
    ChunkTranscriptionRequest,
    ChunkTranscriptionResult,
    TranscriptSegment,
    TranscriptWord,
    TranscriptionSettings,
)


class GoogleSpeechV2Adapter:
    engine_name = "google_speech_to_text_v2"
    _upload_timeout_seconds = 900
    _delete_timeout_seconds = 120
    _max_attempts = 3

    def __init__(self) -> None:
        self._speech_client = None
        self._storage_client = None
        self._speech_client_key: tuple[str, str | None, str] | None = None
        self._storage_client_key: tuple[str, str | None, str] | None = None

    def transcribe_chunk(
        self,
        *,
        chunk: ChunkTranscriptionRequest,
        settings: TranscriptionSettings,
        meeting_id: int,
        run_id: int,
    ) -> ChunkTranscriptionResult:
        self.validate_runtime(settings)
        speech_v2, cloud_speech, json_format = self._speech_modules()
        storage = self._storage_module()
        credentials = self._load_credentials(settings)
        speech_client = self._get_speech_client(speech_v2, settings, credentials)
        storage_client = self._get_storage_client(storage, settings, credentials)

        object_name = f"{settings.staging_prefix}/meeting_{meeting_id}/transcription_{run_id}/chunk_{chunk.chunk_index:03d}.flac"
        bucket = storage_client.bucket(settings.staging_bucket)
        blob = bucket.blob(object_name)
        blob.upload_from_filename(str(chunk.chunk_path), timeout=self._upload_timeout_seconds)
        gcs_uri = f"gs://{settings.staging_bucket}/{object_name}"

        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                effective_word_confidence = settings.enable_word_confidence and settings.model != "chirp_3"
                recognition_config = cloud_speech.RecognitionConfig(
                    auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
                    language_codes=[settings.language_code, *settings.alternative_language_codes],
                    model=settings.model,
                    features=cloud_speech.RecognitionFeatures(
                        enable_automatic_punctuation=settings.automatic_punctuation_enabled,
                        profanity_filter=settings.profanity_filter_enabled,
                        enable_word_time_offsets=settings.enable_word_time_offsets,
                        enable_word_confidence=effective_word_confidence,
                        diarization_config=cloud_speech.SpeakerDiarizationConfig(
                            min_speaker_count=settings.min_speaker_count,
                            max_speaker_count=settings.max_speaker_count,
                        )
                        if settings.diarization_enabled
                        else None,
                    ),
                )
                request = cloud_speech.BatchRecognizeRequest(
                    recognizer=settings.recognizer_path,
                    config=recognition_config,
                    files=[cloud_speech.BatchRecognizeFileMetadata(uri=gcs_uri)],
                    recognition_output_config=cloud_speech.RecognitionOutputConfig(
                        inline_response_config=cloud_speech.InlineOutputConfig(),
                    ),
                )
                response = speech_client.batch_recognize(request=request).result(timeout=1800)
                raw_response = json_format.MessageToDict(response._pb, preserving_proto_field_name=True)
                transcript_text, average_confidence, segments = _parse_batch_recognize_response(
                    raw_response,
                    chunk_duration_ms=max(0, chunk.end_ms - chunk.start_ms),
                )
                return ChunkTranscriptionResult(
                    transcript_text=transcript_text,
                    raw_response=raw_response,
                    average_confidence=average_confidence,
                    segments=segments,
                    request_config={
                        "recognizer": settings.recognizer_path,
                        "model": settings.model,
                        "language_codes": [settings.language_code, *settings.alternative_language_codes],
                        "diarization_enabled": settings.diarization_enabled,
                        "automatic_punctuation_enabled": settings.automatic_punctuation_enabled,
                        "enable_word_time_offsets": settings.enable_word_time_offsets,
                        "enable_word_confidence": effective_word_confidence,
                        "gcs_uri": gcs_uri,
                        "attempt": attempt,
                    },
                    response_metadata={"gcs_uri": gcs_uri},
                )
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= self._max_attempts or not _is_retryable_transcription_error(exc):
                    raise
                time.sleep(2 * attempt)
            finally:
                try:
                    blob.delete(timeout=self._delete_timeout_seconds)
                except Exception:
                    pass

        if last_error is not None:
            raise last_error
        raise RuntimeError("Unexpected Google STT retry loop exit")

    def validate_runtime(self, settings: TranscriptionSettings) -> dict[str, str]:
        speech_v2, _, _ = self._speech_modules()
        self._storage_module()

        if settings.auth_mode == "credentials_file" and settings.credentials_path:
            try:
                from google.oauth2 import service_account

                service_account.Credentials.from_service_account_file(settings.credentials_path)
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(
                    f"Google credentials file is invalid or unreadable: {settings.credentials_path}"
                ) from exc

        try:
            from google.auth.credentials import AnonymousCredentials

            client_options = (
                {"api_endpoint": f"{settings.recognizer_location}-speech.googleapis.com"}
                if settings.recognizer_location != "global"
                else None
            )
            speech_v2.SpeechClient(credentials=AnonymousCredentials(), client_options=client_options)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Unable to construct Google Speech V2 client for location {settings.recognizer_location}"
            ) from exc

        return {
            "google-cloud-speech": importlib.metadata.version("google-cloud-speech"),
            "google-cloud-storage": importlib.metadata.version("google-cloud-storage"),
            "protobuf": importlib.metadata.version("protobuf"),
            "google-auth": importlib.metadata.version("google-auth"),
        }

    def validate_preflight(
        self,
        settings: TranscriptionSettings,
        *,
        validate_bucket_write: bool,
    ) -> dict[str, Any]:
        runtime_versions = self.validate_runtime(settings)
        speech_v2, _, _ = self._speech_modules()
        storage = self._storage_module()
        credentials = self._load_credentials(settings)
        self._get_speech_client(speech_v2, settings, credentials)
        storage_client = self._get_storage_client(storage, settings, credentials)

        bucket = storage_client.bucket(settings.staging_bucket)
        try:
            bucket_exists = bucket.exists()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"Unable to access Google Cloud Storage bucket {settings.staging_bucket}. "
                "Check credentials, project_id, bucket name, and IAM permissions."
            ) from exc
        if not bucket_exists:
            raise RuntimeError(
                f"Google Cloud Storage staging bucket is not accessible or does not exist: {settings.staging_bucket}"
            )

        write_checked = False
        if validate_bucket_write:
            preflight_object = (
                f"{settings.staging_prefix}/_preflight/"
                f"{settings.recognizer_location}_{uuid4().hex}.txt"
            )
            blob = bucket.blob(preflight_object)
            try:
                blob.upload_from_string(
                    b"audio-extractor-2 stt preflight",
                    content_type="text/plain",
                    timeout=self._upload_timeout_seconds,
                )
                write_checked = True
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(
                    f"Google Cloud Storage staging bucket is reachable but not writable: {settings.staging_bucket}"
                ) from exc
            finally:
                try:
                    blob.delete(timeout=self._delete_timeout_seconds)
                except Exception:
                    pass

        return {
            "packages": runtime_versions,
            "auth_mode": settings.auth_mode,
            "project_id": settings.project_id,
            "recognizer_location": settings.recognizer_location,
            "staging_bucket": settings.staging_bucket,
            "bucket_accessible": True,
            "bucket_write_checked": write_checked,
        }

    def _get_speech_client(self, speech_v2, settings: TranscriptionSettings, credentials):
        client_key = (settings.auth_mode, settings.credentials_path, settings.recognizer_location)
        if self._speech_client is None or self._speech_client_key != client_key:
            client_options = {"api_endpoint": f"{settings.recognizer_location}-speech.googleapis.com"} if settings.recognizer_location != "global" else None
            self._speech_client = speech_v2.SpeechClient(credentials=credentials, client_options=client_options)
            self._speech_client_key = client_key
        return self._speech_client

    def _get_storage_client(self, storage, settings: TranscriptionSettings, credentials):
        client_key = (settings.auth_mode, settings.credentials_path, settings.project_id)
        if self._storage_client is None or self._storage_client_key != client_key:
            self._storage_client = storage.Client(project=settings.project_id or None, credentials=credentials)
            self._storage_client_key = client_key
        return self._storage_client

    def _load_credentials(self, settings: TranscriptionSettings):
        if settings.auth_mode == "credentials_file" and settings.credentials_path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = settings.credentials_path
            try:
                from google.oauth2 import service_account

                return service_account.Credentials.from_service_account_file(settings.credentials_path)
            except Exception as exc:  # noqa: BLE001
                raise RuntimeError(
                    f"Failed to load Google service-account credentials from {settings.credentials_path}"
                ) from exc

        try:
            import google.auth

            credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            return credentials
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "Application Default Credentials are not available. Set GOOGLE_APPLICATION_CREDENTIALS or use credentials_file mode."
            ) from exc

    @staticmethod
    def _speech_modules():
        try:
            from google.cloud import speech_v2
            from google.cloud.speech_v2.types import cloud_speech
            from google.protobuf import json_format
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Google Cloud Speech dependencies are missing. Install google-cloud-speech and protobuf."
            ) from exc
        return speech_v2, cloud_speech, json_format

    @staticmethod
    def _storage_module():
        try:
            from google.cloud import storage
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Google Cloud Storage dependencies are missing. Install google-cloud-storage."
            ) from exc
        return storage


def _parse_batch_recognize_response(
    raw_response: dict[str, Any],
    *,
    chunk_duration_ms: int | None = None,
) -> tuple[str, float | None, list[TranscriptSegment]]:
    results_payload = raw_response.get("results", {})
    file_results = list(results_payload.values()) if isinstance(results_payload, dict) else results_payload if isinstance(results_payload, list) else []

    recognition_results: list[dict[str, Any]] = []
    for file_result in file_results:
        inline_result = file_result.get("inline_result") or file_result.get("inlineResult") or {}
        transcript_container = inline_result.get("transcript") or inline_result
        chunk_results = transcript_container.get("results") or file_result.get("results") or []
        if isinstance(chunk_results, list):
            recognition_results.extend(chunk_results)

    if not recognition_results:
        return "", None, []

    full_text_parts: list[str] = []
    confidences: list[float] = []
    segments: list[TranscriptSegment] = []
    for result in recognition_results:
        alternatives = result.get("alternatives") or []
        if not alternatives:
            continue
        top = alternatives[0]
        text = str(top.get("transcript", "")).strip()
        if text:
            full_text_parts.append(text)
        confidence = _float_or_none(top.get("confidence"))
        if confidence is not None:
            confidences.append(confidence)
        words = [_parse_word(word) for word in top.get("words") or []]
        kept_words = [word for word in words if word is not None]
        kept_words = _normalize_word_offsets(kept_words, chunk_duration_ms=chunk_duration_ms)
        if kept_words:
            segments.extend(_group_words_into_segments(kept_words))
        elif text:
            end_ms = _duration_to_ms(result.get("result_end_offset") or result.get("resultEndOffset"))
            if chunk_duration_ms is not None and end_ms is not None and end_ms > chunk_duration_ms + 500:
                end_ms = min(chunk_duration_ms, max(0, end_ms))
            segments.append(
                TranscriptSegment(
                    text=text,
                    start_ms_in_chunk=0 if end_ms is not None else None,
                    end_ms_in_chunk=end_ms,
                    speaker_label=None,
                    confidence=confidence,
                    words=[],
                )
            )

    average_confidence = round(sum(confidences) / len(confidences), 4) if confidences else None
    return " ".join(part for part in full_text_parts if part), average_confidence, segments


def _parse_word(payload: dict[str, Any]) -> TranscriptWord | None:
    word_text = str(payload.get("word", "")).strip()
    if not word_text:
        return None
    if not any(character.isalnum() for character in word_text):
        return None
    speaker_label = str(payload.get("speaker_label") or payload.get("speakerLabel") or "").strip() or None
    start_ms = _duration_to_ms(payload.get("start_offset") or payload.get("startOffset"))
    end_ms = _duration_to_ms(payload.get("end_offset") or payload.get("endOffset"))
    if start_ms is not None and end_ms is not None and end_ms < start_ms:
        return None
    return TranscriptWord(
        word_text=word_text,
        start_ms_in_chunk=start_ms,
        end_ms_in_chunk=end_ms,
        speaker_label=speaker_label,
        confidence=_float_or_none(payload.get("confidence")),
    )


def _group_words_into_segments(words: list[TranscriptWord]) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    buffer: list[TranscriptWord] = []
    current_label: str | None = None
    for word in words:
        if not buffer:
            buffer = [word]
            current_label = word.speaker_label
            continue
        previous = buffer[-1]
        gap_ms = None
        if previous.end_ms_in_chunk is not None and word.start_ms_in_chunk is not None:
            gap_ms = word.start_ms_in_chunk - previous.end_ms_in_chunk
        if word.speaker_label != current_label or (gap_ms is not None and gap_ms > 1200):
            segments.append(_segment_from_words(buffer))
            buffer = [word]
            current_label = word.speaker_label
        else:
            buffer.append(word)
    if buffer:
        segments.append(_segment_from_words(buffer))
    return segments


def _segment_from_words(words: list[TranscriptWord]) -> TranscriptSegment:
    confidences = [word.confidence for word in words if word.confidence is not None]
    return TranscriptSegment(
        text=" ".join(word.word_text for word in words),
        start_ms_in_chunk=words[0].start_ms_in_chunk,
        end_ms_in_chunk=words[-1].end_ms_in_chunk,
        speaker_label=words[0].speaker_label,
        confidence=round(sum(confidences) / len(confidences), 4) if confidences else None,
        words=words,
    )


def _duration_to_ms(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(float(value) * 1000)
    text = str(value).strip()
    if text.endswith("s"):
        return int(round(float(text[:-1]) * 1000))
    return None


def _float_or_none(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _is_retryable_transcription_error(exc: Exception) -> bool:
    message = str(exc).lower()
    retry_markers = (
        "connection reset",
        "timed out",
        "timeout",
        "temporarily unavailable",
        "503",
        "10054",
        "deadline exceeded",
    )
    return any(marker in message for marker in retry_markers)


def _normalize_word_offsets(
    words: list[TranscriptWord],
    *,
    chunk_duration_ms: int | None,
) -> list[TranscriptWord]:
    if not words or chunk_duration_ms is None:
        return _normalize_word_windows(_sort_words(words), chunk_duration_ms=chunk_duration_ms)

    starts = [word.start_ms_in_chunk for word in words if word.start_ms_in_chunk is not None]
    ends = [word.end_ms_in_chunk for word in words if word.end_ms_in_chunk is not None]
    if not starts or not ends:
        return _normalize_word_windows(_sort_words(words), chunk_duration_ms=chunk_duration_ms)

    min_start = min(starts)
    max_end = max(ends)
    if max_end <= chunk_duration_ms + 500 or min_start < 1000:
        return _normalize_word_windows(_sort_words(words), chunk_duration_ms=chunk_duration_ms)

    shift_ms = min_start
    normalized: list[TranscriptWord] = []
    for word in words:
        start_ms = None if word.start_ms_in_chunk is None else max(0, word.start_ms_in_chunk - shift_ms)
        end_ms = None if word.end_ms_in_chunk is None else max(0, word.end_ms_in_chunk - shift_ms)
        normalized.append(
            TranscriptWord(
                word_text=word.word_text,
                start_ms_in_chunk=start_ms,
                end_ms_in_chunk=end_ms,
                speaker_label=word.speaker_label,
                confidence=word.confidence,
            )
        )
    return _normalize_word_windows(_sort_words(normalized), chunk_duration_ms=chunk_duration_ms)


def _sort_words(words: list[TranscriptWord]) -> list[TranscriptWord]:
    return sorted(
        words,
        key=lambda word: (
            word.start_ms_in_chunk if word.start_ms_in_chunk is not None else word.end_ms_in_chunk if word.end_ms_in_chunk is not None else 0,
            word.end_ms_in_chunk if word.end_ms_in_chunk is not None else word.start_ms_in_chunk if word.start_ms_in_chunk is not None else 0,
            word.word_text,
        ),
    )


def _normalize_word_windows(
    words: list[TranscriptWord],
    *,
    chunk_duration_ms: int | None,
) -> list[TranscriptWord]:
    normalized: list[TranscriptWord] = []
    max_word_duration_ms = 1_500
    fallback_word_duration_ms = 800

    for index, word in enumerate(words):
        start_ms = word.start_ms_in_chunk
        end_ms = word.end_ms_in_chunk

        next_start_ms = None
        for next_word in words[index + 1 :]:
            if next_word.start_ms_in_chunk is not None:
                next_start_ms = next_word.start_ms_in_chunk
                break

        if start_ms is None and end_ms is not None:
            start_ms = max(0, end_ms - fallback_word_duration_ms)
        if end_ms is None and start_ms is not None:
            candidate_end_ms = start_ms + fallback_word_duration_ms
            if next_start_ms is not None and next_start_ms > start_ms:
                candidate_end_ms = min(candidate_end_ms, next_start_ms)
            end_ms = candidate_end_ms

        if start_ms is None and end_ms is None:
            continue
        if start_ms is not None and end_ms is not None and end_ms < start_ms:
            continue

        if start_ms is not None and end_ms is not None and end_ms - start_ms > max_word_duration_ms:
            capped_end_ms = start_ms + fallback_word_duration_ms
            if next_start_ms is not None and next_start_ms > start_ms:
                capped_end_ms = min(capped_end_ms, next_start_ms)
            end_ms = capped_end_ms

        if chunk_duration_ms is not None:
            if start_ms is not None:
                start_ms = min(max(0, start_ms), chunk_duration_ms)
            if end_ms is not None:
                end_ms = min(max(0, end_ms), chunk_duration_ms)

        normalized.append(
            TranscriptWord(
                word_text=word.word_text,
                start_ms_in_chunk=start_ms,
                end_ms_in_chunk=end_ms,
                speaker_label=word.speaker_label,
                confidence=word.confidence,
            )
        )

    return normalized
