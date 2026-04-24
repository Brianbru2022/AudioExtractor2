from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MediaProbe:
    source_path: Path
    media_type: str
    duration_ms: int
    sample_rate: int | None
    channels: int | None
    mime_type: str
    size_bytes: int


@dataclass(frozen=True)
class SilenceCandidate:
    start_ms: int
    end_ms: int
    duration_ms: int
    boundary_ms: int


@dataclass(frozen=True)
class PlannedChunk:
    chunk_index: int
    base_start_ms: int
    base_end_ms: int
    start_ms: int
    end_ms: int
    overlap_before_ms: int
    overlap_after_ms: int
    duration_ms: int
    boundary_reason: str


@dataclass(frozen=True)
class ArtifactDescriptor:
    artifact_type: str
    role: str
    path: Path
    mime_type: str | None
    sha256: str | None
    size_bytes: int | None
    metadata: dict[str, Any]
