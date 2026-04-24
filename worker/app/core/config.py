from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class ChunkDefaults:
    target_ms: int = 600_000
    hard_max_ms: int = 720_000
    min_chunk_ms: int = 180_000
    overlap_ms: int = 1_500
    min_silence_ms: int = 700
    silence_threshold_db: int = -35


@dataclass(frozen=True)
class TranscriptionDefaults:
    model: str = "chirp_3"
    language_code: str = "en-US"
    diarization_enabled: bool = True
    min_speaker_count: int = 2
    max_speaker_count: int = 8
    automatic_punctuation_enabled: bool = True
    profanity_filter_enabled: bool = False
    enable_word_time_offsets: bool = True
    enable_word_confidence: bool = True
    max_parallel_chunks: int = 2
    low_confidence_threshold: float = 0.7


@dataclass(frozen=True)
class AppConfig:
    workspace_root: Path
    storage_root: Path
    db_path: Path
    settings_backup_path: Path
    artifacts_root: Path
    normalized_root: Path
    chunks_root: Path
    managed_root: Path
    logs_root: Path
    exports_root: Path
    worker_version: str
    host: str
    port: int
    chunk_defaults: ChunkDefaults
    transcription_defaults: TranscriptionDefaults


def load_config() -> AppConfig:
    default_workspace_root = Path(__file__).resolve().parents[3]
    workspace_root = Path(os.getenv("AUDIO_EXTRACTOR_WORKSPACE_ROOT", str(default_workspace_root)))
    storage_root = Path(os.getenv("AUDIO_EXTRACTOR_STORAGE_ROOT", str(workspace_root / "storage")))
    settings_backup_path = Path(
        os.getenv("AUDIO_EXTRACTOR_SETTINGS_BACKUP_PATH", str(workspace_root / ".audio_extractor_2_cloud_settings.json"))
    )

    return AppConfig(
        workspace_root=workspace_root,
        storage_root=storage_root,
        db_path=storage_root / "db" / "audio_extractor_2.sqlite3",
        settings_backup_path=settings_backup_path,
        artifacts_root=storage_root / "artifacts",
        normalized_root=storage_root / "normalized",
        chunks_root=storage_root / "chunks",
        managed_root=storage_root / "managed",
        logs_root=storage_root / "logs",
        exports_root=storage_root / "exports",
        worker_version="0.2.0",
        host="127.0.0.1",
        port=8765,
        chunk_defaults=ChunkDefaults(),
        transcription_defaults=TranscriptionDefaults(),
    )


config = load_config()
