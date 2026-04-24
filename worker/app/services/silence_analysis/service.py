from __future__ import annotations

import re
from pathlib import Path

from app.models.domain import SilenceCandidate
from app.utils.subprocesses import require_binary
import subprocess


SILENCE_START = re.compile(r"silence_start:\s(?P<value>[0-9.]+)")
SILENCE_END = re.compile(r"silence_end:\s(?P<end>[0-9.]+)\s+\|\s+silence_duration:\s(?P<duration>[0-9.]+)")


class SilenceAnalysisService:
    def __init__(self) -> None:
        self.ffmpeg = require_binary("ffmpeg")

    def analyze(self, audio_path: Path, threshold_db: int, min_silence_ms: int) -> dict[str, object]:
        command = [
            self.ffmpeg,
            "-hide_banner",
            "-i",
            str(audio_path),
            "-af",
            f"silencedetect=n={threshold_db}dB:d={min_silence_ms / 1000}",
            "-f",
            "null",
            "NUL",
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        stderr = completed.stderr
        candidates: list[SilenceCandidate] = []
        current_start_ms: int | None = None

        for line in stderr.splitlines():
            start_match = SILENCE_START.search(line)
            if start_match:
                current_start_ms = int(float(start_match.group("value")) * 1000)
                continue

            end_match = SILENCE_END.search(line)
            if end_match and current_start_ms is not None:
                end_ms = int(float(end_match.group("end")) * 1000)
                duration_ms = int(float(end_match.group("duration")) * 1000)
                boundary_ms = current_start_ms + duration_ms // 2
                candidates.append(
                    SilenceCandidate(
                        start_ms=current_start_ms,
                        end_ms=end_ms,
                        duration_ms=duration_ms,
                        boundary_ms=boundary_ms,
                    )
                )
                current_start_ms = None

        return {
            "threshold_db": threshold_db,
            "min_silence_ms": min_silence_ms,
            "candidate_count": len(candidates),
            "total_silence_ms": sum(candidate.duration_ms for candidate in candidates),
            "longest_silence_ms": max((candidate.duration_ms for candidate in candidates), default=0),
            "candidates": [candidate.__dict__ for candidate in candidates],
        }
