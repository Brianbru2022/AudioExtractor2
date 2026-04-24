from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

ExportProfile = Literal["formal_minutes_pack", "action_register", "full_archive", "transcript_export"]
ExportFormat = Literal["docx", "pdf", "csv", "xlsx", "json", "txt"]


@dataclass(frozen=True)
class ExportOptions:
    reviewed_only: bool = True
    include_evidence_appendix: bool = True
    include_transcript_appendix: bool = False
    include_confidence_flags: bool = False

    def to_json(self) -> dict[str, Any]:
        return {
            "reviewed_only": self.reviewed_only,
            "include_evidence_appendix": self.include_evidence_appendix,
            "include_transcript_appendix": self.include_transcript_appendix,
            "include_confidence_flags": self.include_confidence_flags,
        }


@dataclass(frozen=True)
class ExportDescriptor:
    export_profile: ExportProfile
    format: ExportFormat
    file_path: Path
    display_name: str
