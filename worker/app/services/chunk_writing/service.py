from __future__ import annotations

from pathlib import Path

from app.utils.files import ensure_directory, sha256_for_file
from app.utils.subprocesses import require_binary, run_command


class ChunkWriterService:
    def __init__(self) -> None:
        self.ffmpeg = require_binary("ffmpeg")

    def write_chunk(self, normalized_audio_path: Path, output_path: Path, *, start_ms: int, end_ms: int) -> str:
        ensure_directory(output_path.parent)
        run_command(
            [
                self.ffmpeg,
                "-y",
                "-ss",
                f"{start_ms / 1000:.3f}",
                "-to",
                f"{end_ms / 1000:.3f}",
                "-i",
                str(normalized_audio_path),
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "flac",
                str(output_path),
            ]
        )
        return sha256_for_file(output_path)
