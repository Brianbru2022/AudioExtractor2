from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
VALIDATION_ROOT = WORKSPACE_ROOT / "storage" / "imports" / "validation"
LONG_FORM_ROOT = VALIDATION_ROOT / "long_form"
FORMAT_ROOT = VALIDATION_ROOT / "formats"


def run_command(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed: {' '.join(command)}\n{completed.stderr}")


def sha256_for_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_media_matrix() -> dict[str, Path]:
    if VALIDATION_ROOT.exists():
        shutil.rmtree(VALIDATION_ROOT)
    FORMAT_ROOT.mkdir(parents=True, exist_ok=True)
    LONG_FORM_ROOT.mkdir(parents=True, exist_ok=True)

    audio_base = FORMAT_ROOT / "meeting_base.wav"
    run_command(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono:d=1",
            "-f",
            "lavfi",
            "-i",
            "anoisesrc=color=pink:amplitude=0.01:duration=2",
            "-filter_complex",
            "[0:a][1:a][2:a]concat=n=3:v=0:a=1[out]",
            "-map",
            "[out]",
            str(audio_base),
        ]
    )

    outputs = {
        "wav": FORMAT_ROOT / "sample.wav",
        "mp3": FORMAT_ROOT / "sample.mp3",
        "m4a": FORMAT_ROOT / "sample.m4a",
        "flac": FORMAT_ROOT / "sample.flac",
    }
    run_command(["ffmpeg", "-y", "-i", str(audio_base), str(outputs["wav"])])
    run_command(["ffmpeg", "-y", "-i", str(audio_base), "-c:a", "libmp3lame", str(outputs["mp3"])])
    run_command(["ffmpeg", "-y", "-i", str(audio_base), "-c:a", "aac", str(outputs["m4a"])])
    run_command(["ffmpeg", "-y", "-i", str(audio_base), "-c:a", "flac", str(outputs["flac"])])

    color_input = "color=c=0x0f172a:s=640x360:d=5"
    outputs["mp4"] = FORMAT_ROOT / "sample.mp4"
    outputs["mov"] = FORMAT_ROOT / "sample.mov"
    outputs["mkv"] = FORMAT_ROOT / "sample.mkv"
    for extension, output in [("mp4", outputs["mp4"]), ("mov", outputs["mov"]), ("mkv", outputs["mkv"])]:
        run_command(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                color_input,
                "-i",
                str(audio_base),
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(output),
            ]
        )

    long_mp3 = LONG_FORM_ROOT / "long_form_2h.mp3"
    run_command(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anoisesrc=color=pink:amplitude=0.008:duration=7200",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=16000:cl=mono:d=7200",
            "-filter_complex",
            "[0:a]volume=0.4[a0];[1:a]volume=0.02[a1];[a0][a1]amix=inputs=2:weights=1 1[out]",
            "-map",
            "[out]",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "24k",
            str(long_mp3),
        ]
    )
    outputs["long_2h_mp3"] = long_mp3

    return outputs


def wait_for_run_completion(client: TestClient, meeting_id: int) -> dict:
    for _ in range(180):
        detail = client.get(f"/api/v1/meetings/{meeting_id}").json()
        run = detail.get("latest_run_detail")
        if run and run.get("status") in {"completed", "failed"}:
            return detail
        time.sleep(1)
    raise TimeoutError(f"Timed out waiting for meeting {meeting_id} preprocessing")


def validate_chunk_coverage(chunks: list[dict], duration_ms: int, intended_overlap_ms: int) -> dict[str, int | bool]:
    total_gap_ms = 0
    duplicate_beyond_overlap_ms = 0

    for index, chunk in enumerate(chunks):
        if index == 0:
            if chunk["base_start_ms"] != 0:
                total_gap_ms += chunk["base_start_ms"]
            continue

        previous = chunks[index - 1]
        total_gap_ms += max(0, chunk["base_start_ms"] - previous["base_end_ms"])
        duplicate_beyond_overlap_ms += max(0, previous["base_end_ms"] - chunk["base_start_ms"])
        actual_overlap_ms = previous["end_ms"] - chunk["start_ms"]
        duplicate_beyond_overlap_ms += max(0, actual_overlap_ms - intended_overlap_ms)

    covers_full_duration = bool(chunks) and chunks[-1]["base_end_ms"] == duration_ms
    return {
        "covers_full_duration": covers_full_duration,
        "gaps_ms": total_gap_ms,
        "duplicate_beyond_overlap_ms": duplicate_beyond_overlap_ms,
        "chunk_count": len(chunks),
    }


def main() -> None:
    outputs = build_media_matrix()
    client = TestClient(app)
    results: dict[str, object] = {"formats": {}, "long_form": {}, "edge_cases": {}}

    for extension in ["wav", "mp3", "m4a", "flac", "mp4", "mov", "mkv"]:
        import_mode = "managed_copy" if extension in {"mp3", "mov"} else "reference"
        response = client.post(
            "/api/v1/meetings/import",
            json={
                "source_path": str(outputs[extension]),
                "import_mode": import_mode,
                "title": f"Validation {extension.upper()}",
            },
        )
        response.raise_for_status()
        meeting = response.json()["meeting"]
        preprocess = client.post(f"/api/v1/meetings/{meeting['id']}/preprocess")
        preprocess.raise_for_status()
        detail = wait_for_run_completion(client, meeting["id"])
        source_file = detail["source_file"]
        run = detail["latest_run_detail"]
        chunk_validation = run["chunking_strategy_json"]["coverage_validation"]
        normalized_artifact = next(artifact for artifact in detail["artifacts"] if artifact["role"] == "normalized audio")
        checksum_matches = sha256_for_file(Path(normalized_artifact["path"])) == normalized_artifact["sha256"]
        results["formats"][extension] = {
            "meeting_status": detail["status"],
            "run_status": run["status"],
            "media_type": source_file["media_type"],
            "duration_ms": source_file["duration_ms"],
            "managed_copy_path": source_file["managed_copy_path"],
            "normalized_checksum_ok": checksum_matches,
            "coverage_validation": chunk_validation,
        }

    long_response = client.post(
        "/api/v1/meetings/import",
        json={
            "source_path": str(outputs["long_2h_mp3"]),
            "import_mode": "managed_copy",
            "title": "Validation Long Form 2H",
        },
    )
    long_response.raise_for_status()
    long_meeting = long_response.json()["meeting"]
    client.post(f"/api/v1/meetings/{long_meeting['id']}/preprocess").raise_for_status()
    long_detail = wait_for_run_completion(client, long_meeting["id"])
    long_run = long_detail["latest_run_detail"]
    long_manifest = next(artifact for artifact in long_detail["artifacts"] if artifact["role"] == "chunk manifest")
    manifest_payload = json.loads(Path(long_manifest["path"]).read_text(encoding="utf-8"))
    results["long_form"] = {
        "meeting_status": long_detail["status"],
        "run_status": long_run["status"],
        "duration_ms": long_detail["source_file"]["duration_ms"],
        "chunk_count": len(long_detail["chunks"]),
        "coverage_validation": validate_chunk_coverage(
            manifest_payload["chunks"],
            long_detail["source_file"]["duration_ms"],
            long_run["chunking_strategy_json"]["overlap_ms"],
        ),
    }

    missing_response = client.post(
        "/api/v1/meetings/import",
        json={
            "source_path": str(outputs["wav"]),
            "import_mode": "reference",
            "title": "Validation Missing Source",
        },
    )
    missing_response.raise_for_status()
    missing_meeting = missing_response.json()["meeting"]
    moved_path = outputs["wav"].with_name("sample-moved.wav")
    outputs["wav"].rename(moved_path)
    missing_preprocess = client.post(f"/api/v1/meetings/{missing_meeting['id']}/preprocess")
    results["edge_cases"]["missing_reference_source"] = {
        "status_code": missing_preprocess.status_code,
        "detail": missing_preprocess.json()["detail"],
    }
    moved_path.rename(outputs["wav"])

    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
