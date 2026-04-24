from __future__ import annotations

from pathlib import Path

from app.models.domain import MediaProbe
from app.utils.subprocesses import require_binary, run_command


class NormalizationService:
    def __init__(self) -> None:
        self.ffmpeg = require_binary("ffmpeg")

    def normalize_to_flac(self, source_path: Path, output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        run_command(
            [
                self.ffmpeg,
                "-y",
                "-i",
                str(source_path),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "flac",
                str(output_path),
            ]
        )

    @staticmethod
    def normalized_metadata(probe: MediaProbe) -> dict[str, int | str | None]:
        return {
            "normalized_format": "flac",
            "normalized_sample_rate": probe.sample_rate,
            "normalized_channels": probe.channels,
        }
