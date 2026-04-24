from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ImportMeetingRequest(BaseModel):
    source_path: str
    import_mode: Literal["reference", "managed_copy"]
    title: str | None = None
    meeting_date: str | None = None
    project: str | None = None
    notes: str | None = None
    attendees: list[str] = Field(default_factory=list)
    circulation: list[str] = Field(default_factory=list)


class UpdateSettingRequest(BaseModel):
    value_json: dict[str, Any] = Field(default_factory=dict)


class GeminiGenerateRequest(BaseModel):
    prompt: str
    system_instruction: str | None = None
    model: str | None = None
    response_mime_type: str | None = None
    thinking_level: Literal["minimal", "low", "medium", "high"] | None = None
    temperature: float | None = None


class UpdateInsightRequest(BaseModel):
    text: str | None = None
    owner: str | None = None
    due_date: str | None = None
    priority: str | None = None
    review_status: Literal["pending", "accepted", "rejected"] | None = None


class RetryTranscriptionRequest(BaseModel):
    chunk_ids: list[int] | None = None


class UpdateSpeakerRequest(BaseModel):
    speaker_name: str | None = None


class UpdateTranscriptSegmentsRequest(BaseModel):
    segment_ids: list[int] = Field(default_factory=list)
    excluded_from_review: bool
    exclusion_reason: str | None = None


class CreateExportRequest(BaseModel):
    export_profile: Literal["formal_minutes_pack", "action_register", "full_archive", "transcript_export"]
    format: Literal["docx", "pdf", "csv", "xlsx", "json", "txt"]
    reviewed_only: bool = True
    include_evidence_appendix: bool = True
    include_transcript_appendix: bool = False
    include_confidence_flags: bool = False
    output_directory: str | None = None


class InspectImportSourceRequest(BaseModel):
    source_path: str
