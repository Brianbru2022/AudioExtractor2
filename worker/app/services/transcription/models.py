from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class TranscriptionSettings:
    project_id: str
    auth_mode: str
    credentials_path: str | None
    recognizer_location: str
    recognizer_id: str
    staging_bucket: str
    staging_prefix: str
    model: str
    language_code: str
    alternative_language_codes: list[str]
    diarization_enabled: bool
    min_speaker_count: int
    max_speaker_count: int
    automatic_punctuation_enabled: bool
    profanity_filter_enabled: bool
    enable_word_time_offsets: bool
    enable_word_confidence: bool
    max_parallel_chunks: int
    phrase_hints_placeholder: list[str]
    low_confidence_threshold: float

    @property
    def recognizer_path(self) -> str:
        recognizer_id = self.recognizer_id or "_"
        return f"projects/{self.project_id}/locations/{self.recognizer_location}/recognizers/{recognizer_id}"


@dataclass(frozen=True)
class TranscriptWord:
    word_text: str
    start_ms_in_chunk: int | None
    end_ms_in_chunk: int | None
    speaker_label: str | None
    confidence: float | None


@dataclass(frozen=True)
class TranscriptSegment:
    text: str
    start_ms_in_chunk: int | None
    end_ms_in_chunk: int | None
    speaker_label: str | None
    confidence: float | None
    words: list[TranscriptWord]


@dataclass(frozen=True)
class ChunkTranscriptionResult:
    transcript_text: str
    raw_response: dict[str, object]
    average_confidence: float | None
    segments: list[TranscriptSegment]
    request_config: dict[str, object]
    response_metadata: dict[str, object]


@dataclass(frozen=True)
class ChunkTranscriptionRequest:
    chunk_id: int
    chunk_path: Path
    chunk_index: int
    start_ms: int
    end_ms: int
    overlap_before_ms: int
    overlap_after_ms: int
