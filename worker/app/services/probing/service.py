from __future__ import annotations

from pathlib import Path

from app.models.domain import MediaProbe
from app.utils.files import mime_type_for_path
from app.utils.subprocesses import probe_json, require_binary


class ProbeService:
    def __init__(self) -> None:
        self.ffprobe = require_binary("ffprobe")

    def probe(self, source_path: Path) -> MediaProbe:
        payload = probe_json(
            [
                self.ffprobe,
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(source_path),
            ]
        )
        streams = payload.get("streams", [])
        format_payload = payload.get("format", {})
        audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)
        video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
        media_type = "video" if video_stream else "audio"
        duration = format_payload.get("duration")
        duration_ms = int(float(duration) * 1000) if duration else 0
        sample_rate = int(audio_stream["sample_rate"]) if audio_stream and audio_stream.get("sample_rate") else None
        channels = int(audio_stream["channels"]) if audio_stream and audio_stream.get("channels") else None

        return MediaProbe(
            source_path=source_path,
            media_type=media_type,
            duration_ms=duration_ms,
            sample_rate=sample_rate,
            channels=channels,
            mime_type=mime_type_for_path(source_path),
            size_bytes=source_path.stat().st_size,
        )
