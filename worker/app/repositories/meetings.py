from __future__ import annotations

import json
from typing import Any

from app.db.database import Database
from app.utils.files import utc_now_iso


class MeetingRepository:
    def __init__(self, database: Database):
        self.database = database

    def create(
        self,
        title: str,
        meeting_date: str | None,
        project: str | None,
        notes: str | None,
        attendees: list[str] | None = None,
        circulation: list[str] | None = None,
    ) -> int:
        now = utc_now_iso()
        return self.database.execute(
            """
            INSERT INTO meetings (title, meeting_date, project, notes, attendees_json, circulation_json, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'draft', ?, ?)
            """,
            (
                title,
                meeting_date,
                project,
                notes,
                json.dumps(_normalize_people_list(attendees)),
                json.dumps(_normalize_people_list(circulation)),
                now,
                now,
            ),
        )

    def update_status(self, meeting_id: int, status: str) -> None:
        self.database.execute(
            "UPDATE meetings SET status = ?, updated_at = ? WHERE id = ?",
            (status, utc_now_iso(), meeting_id),
        )

    def get(self, meeting_id: int) -> dict[str, Any] | None:
        return _deserialize_meeting_row(self.database.fetch_one("SELECT * FROM meetings WHERE id = ?", (meeting_id,)))

    def list(self) -> list[dict[str, Any]]:
        meetings = [_deserialize_meeting_row(row) for row in self.database.fetch_all("SELECT * FROM meetings ORDER BY created_at DESC")]
        for meeting in meetings:
            meeting["source_file"] = self.database.fetch_one(
                "SELECT * FROM source_files WHERE meeting_id = ? ORDER BY id DESC LIMIT 1",
                (meeting["id"],),
            )
            meeting["chunk_count"] = self.database.fetch_one(
                "SELECT COUNT(*) AS count FROM chunks WHERE meeting_id = ?",
                (meeting["id"],),
            )["count"]
            latest_run = self.database.fetch_one(
                "SELECT * FROM preprocessing_runs WHERE meeting_id = ? ORDER BY id DESC LIMIT 1",
                (meeting["id"],),
            )
            meeting["latest_run"] = latest_run
        return meetings

    def delete(self, meeting_id: int, connection=None) -> None:
        executor = connection.execute if connection else self.database.execute
        executor("DELETE FROM meetings WHERE id = ?", (meeting_id,))


def _deserialize_meeting_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    row["attendees"] = _deserialize_people_list(row.get("attendees_json"))
    row["circulation"] = _deserialize_people_list(row.get("circulation_json"))
    return row


def _deserialize_people_list(value: Any) -> list[str]:
    try:
        raw = json.loads(value) if value else []
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(raw, list):
        return []
    return [item.strip() for item in raw if isinstance(item, str) and item.strip()]


def _normalize_people_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    return [value.strip() for value in values if isinstance(value, str) and value.strip()]


class SourceFileRepository:
    def __init__(self, database: Database):
        self.database = database

    def create(self, payload: dict[str, Any]) -> int:
        return self.database.execute(
            """
            INSERT INTO source_files (
              meeting_id, import_mode, original_path, managed_copy_path, normalized_audio_path,
              file_name, extension, mime_type, media_type, size_bytes, sha256, duration_ms,
              sample_rate, channels, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["meeting_id"],
                payload["import_mode"],
                payload["original_path"],
                payload["managed_copy_path"],
                payload["normalized_audio_path"],
                payload["file_name"],
                payload["extension"],
                payload["mime_type"],
                payload["media_type"],
                payload["size_bytes"],
                payload["sha256"],
                payload["duration_ms"],
                payload["sample_rate"],
                payload["channels"],
                utc_now_iso(),
            ),
        )

    def update_normalized_path(
        self,
        meeting_id: int,
        normalized_audio_path: str,
        sample_rate: int | None,
        channels: int | None,
    ) -> None:
        self.database.execute(
            """
            UPDATE source_files
            SET normalized_audio_path = ?, sample_rate = ?, channels = ?
            WHERE meeting_id = ?
            """,
            (normalized_audio_path, sample_rate, channels, meeting_id),
        )

    def get_for_meeting(self, meeting_id: int) -> dict[str, Any] | None:
        return self.database.fetch_one(
            "SELECT * FROM source_files WHERE meeting_id = ? ORDER BY id DESC LIMIT 1",
            (meeting_id,),
        )

    def list_for_meeting(self, meeting_id: int) -> list[dict[str, Any]]:
        return self.database.fetch_all(
            "SELECT * FROM source_files WHERE meeting_id = ? ORDER BY id ASC",
            (meeting_id,),
        )

    def list_all(self) -> list[dict[str, Any]]:
        return self.database.fetch_all("SELECT * FROM source_files ORDER BY id ASC")

    def delete_for_meeting(self, meeting_id: int, connection=None) -> None:
        executor = connection.execute if connection else self.database.execute
        executor("DELETE FROM source_files WHERE meeting_id = ?", (meeting_id,))


class RunRepository:
    def __init__(self, database: Database):
        self.database = database

    def create(self, meeting_id: int, job_run_id: int | None, worker_version: str, chunk_strategy: dict[str, Any]) -> int:
        return self.database.execute(
            """
            INSERT INTO preprocessing_runs (
              meeting_id, job_run_id, started_at, completed_at, status, stage, progress_percent,
              current_message, worker_version, normalized_format, normalized_sample_rate,
              normalized_channels, log_json, silence_map_json, chunking_strategy_json,
              waveform_summary_json, error_message, retry_of_run_id, cancel_requested_at, created_at
            ) VALUES (?, ?, NULL, NULL, 'queued', 'queued', 0, ?, ?, NULL, NULL, NULL, ?, NULL, ?, NULL, NULL, NULL, NULL, ?)
            """,
            (
                meeting_id,
                job_run_id,
                "Queued for preprocessing",
                worker_version,
                json.dumps([]),
                json.dumps(chunk_strategy),
                utc_now_iso(),
            ),
        )

    def get(self, run_id: int) -> dict[str, Any] | None:
        return self.database.fetch_one("SELECT * FROM preprocessing_runs WHERE id = ?", (run_id,))

    def get_latest_for_meeting(self, meeting_id: int) -> dict[str, Any] | None:
        return self.database.fetch_one(
            "SELECT * FROM preprocessing_runs WHERE meeting_id = ? ORDER BY id DESC LIMIT 1",
            (meeting_id,),
        )

    def list_for_meeting(self, meeting_id: int) -> list[dict[str, Any]]:
        return self.database.fetch_all(
            "SELECT * FROM preprocessing_runs WHERE meeting_id = ? ORDER BY id ASC",
            (meeting_id,),
        )

    def update_state(
        self,
        run_id: int,
        *,
        status: str,
        stage: str,
        progress_percent: float,
        current_message: str,
    ) -> None:
        self.database.execute(
            """
            UPDATE preprocessing_runs
            SET status = ?, stage = ?, progress_percent = ?, current_message = ?,
                started_at = COALESCE(started_at, ?)
            WHERE id = ?
            """,
            (status, stage, progress_percent, current_message, utc_now_iso(), run_id),
        )

    def append_log(self, run_id: int, entry: dict[str, Any]) -> None:
        run = self.get(run_id)
        logs = json.loads(run["log_json"]) if run and run["log_json"] else []
        logs.append(entry)
        self.database.execute(
            "UPDATE preprocessing_runs SET log_json = ? WHERE id = ?",
            (json.dumps(logs), run_id),
        )

    def finalize_success(
        self,
        run_id: int,
        *,
        normalized_format: str,
        normalized_sample_rate: int,
        normalized_channels: int,
        silence_map: dict[str, Any],
        chunk_strategy: dict[str, Any],
        waveform_summary: dict[str, Any] | None,
    ) -> None:
        self.database.execute(
            """
            UPDATE preprocessing_runs
            SET completed_at = ?, status = 'completed', stage = 'completed',
                progress_percent = 100, current_message = 'Preprocessing complete',
                normalized_format = ?, normalized_sample_rate = ?, normalized_channels = ?,
                silence_map_json = ?, chunking_strategy_json = ?, waveform_summary_json = ?
            WHERE id = ?
            """,
            (
                utc_now_iso(),
                normalized_format,
                normalized_sample_rate,
                normalized_channels,
                json.dumps(silence_map),
                json.dumps(chunk_strategy),
                json.dumps(waveform_summary) if waveform_summary else None,
                run_id,
            ),
        )

    def finalize_failure(self, run_id: int, error_message: str) -> None:
        self.database.execute(
            """
            UPDATE preprocessing_runs
            SET completed_at = ?, status = 'failed', stage = 'failed', error_message = ?, current_message = ?
            WHERE id = ?
            """,
            (utc_now_iso(), error_message, error_message, run_id),
        )

    def delete_for_meeting(self, meeting_id: int, connection=None) -> None:
        executor = connection.execute if connection else self.database.execute
        executor("DELETE FROM preprocessing_runs WHERE meeting_id = ?", (meeting_id,))


class ChunkRepository:
    def __init__(self, database: Database):
        self.database = database

    def replace_for_run(self, run_id: int, chunks: list[dict[str, Any]]) -> None:
        self.database.execute("DELETE FROM chunks WHERE preprocessing_run_id = ?", (run_id,))
        for chunk in chunks:
            self.database.execute(
                """
                INSERT INTO chunks (
                  meeting_id, preprocessing_run_id, chunk_index, file_path, sha256,
                  start_ms, end_ms, overlap_before_ms, overlap_after_ms, duration_ms,
                  boundary_reason, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk["meeting_id"],
                    run_id,
                    chunk["chunk_index"],
                    chunk["file_path"],
                    chunk["sha256"],
                    chunk["start_ms"],
                    chunk["end_ms"],
                    chunk["overlap_before_ms"],
                    chunk["overlap_after_ms"],
                    chunk["duration_ms"],
                    chunk["boundary_reason"],
                    chunk["status"],
                    utc_now_iso(),
                ),
            )

    def list_for_meeting(self, meeting_id: int) -> list[dict[str, Any]]:
        return self.database.fetch_all(
            "SELECT * FROM chunks WHERE meeting_id = ? ORDER BY chunk_index ASC",
            (meeting_id,),
        )

    def list_all(self) -> list[dict[str, Any]]:
        return self.database.fetch_all("SELECT * FROM chunks ORDER BY id ASC")

    def list_for_run(self, preprocessing_run_id: int) -> list[dict[str, Any]]:
        return self.database.fetch_all(
            "SELECT * FROM chunks WHERE preprocessing_run_id = ? ORDER BY chunk_index ASC",
            (preprocessing_run_id,),
        )

    def delete_for_meeting(self, meeting_id: int, connection=None) -> None:
        executor = connection.execute if connection else self.database.execute
        executor("DELETE FROM chunks WHERE meeting_id = ?", (meeting_id,))


class ArtifactRepository:
    def __init__(self, database: Database):
        self.database = database

    def upsert(self, payload: dict[str, Any]) -> int:
        existing = self.database.fetch_one(
            """
            SELECT id
            FROM artifacts
            WHERE meeting_id = ?
              AND COALESCE(preprocessing_run_id, -1) = COALESCE(?, -1)
              AND COALESCE(transcription_run_id, -1) = COALESCE(?, -1)
              AND COALESCE(extraction_run_id, -1) = COALESCE(?, -1)
              AND artifact_type = ?
              AND role = ?
              AND path = ?
            """,
            (
                payload["meeting_id"],
                payload["preprocessing_run_id"],
                payload.get("transcription_run_id"),
                payload.get("extraction_run_id"),
                payload["artifact_type"],
                payload["role"],
                payload["path"],
            ),
        )
        params = (
            payload["meeting_id"],
            payload["preprocessing_run_id"],
            payload.get("transcription_run_id"),
            payload.get("extraction_run_id"),
            payload["artifact_type"],
            payload["role"],
            payload["path"],
            payload["mime_type"],
            payload["sha256"],
            payload["size_bytes"],
            json.dumps(payload["metadata_json"]),
            utc_now_iso(),
        )
        if existing:
            self.database.execute(
                """
                UPDATE artifacts
                SET meeting_id = ?, preprocessing_run_id = ?, transcription_run_id = ?, extraction_run_id = ?,
                    artifact_type = ?, role = ?, path = ?, mime_type = ?, sha256 = ?, size_bytes = ?, metadata_json = ?, created_at = ?
                WHERE id = ?
                """,
                params + (existing["id"],),
            )
            return int(existing["id"])
        return self.database.execute(
            """
            INSERT INTO artifacts (
              meeting_id, preprocessing_run_id, transcription_run_id, extraction_run_id, artifact_type, role, path, mime_type,
              sha256, size_bytes, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            params,
        )

    def list_for_meeting(self, meeting_id: int) -> list[dict[str, Any]]:
        rows = self.database.fetch_all(
            "SELECT * FROM artifacts WHERE meeting_id = ? ORDER BY id ASC",
            (meeting_id,),
        )
        for row in rows:
            row["metadata_json"] = json.loads(row["metadata_json"])
        return rows

    def list_for_run(self, run_id: int) -> list[dict[str, Any]]:
        rows = self.database.fetch_all(
            "SELECT * FROM artifacts WHERE preprocessing_run_id = ? ORDER BY id ASC",
            (run_id,),
        )
        for row in rows:
            row["metadata_json"] = json.loads(row["metadata_json"])
        return rows

    def list_for_transcription_run(self, run_id: int) -> list[dict[str, Any]]:
        rows = self.database.fetch_all(
            "SELECT * FROM artifacts WHERE transcription_run_id = ? ORDER BY id ASC",
            (run_id,),
        )
        for row in rows:
            row["metadata_json"] = json.loads(row["metadata_json"])
        return rows

    def list_for_extraction_run(self, run_id: int) -> list[dict[str, Any]]:
        rows = self.database.fetch_all(
            "SELECT * FROM artifacts WHERE extraction_run_id = ? ORDER BY id ASC",
            (run_id,),
        )
        for row in rows:
            row["metadata_json"] = json.loads(row["metadata_json"])
        return rows

    def delete_for_meeting(self, meeting_id: int, connection=None) -> None:
        executor = connection.execute if connection else self.database.execute
        executor("DELETE FROM artifacts WHERE meeting_id = ?", (meeting_id,))


class SettingsRepository:
    def __init__(self, database: Database):
        self.database = database

    def list(self) -> list[dict[str, Any]]:
        rows = self.database.fetch_all("SELECT key, value_json, updated_at FROM app_settings ORDER BY key ASC")
        for row in rows:
            row["value_json"] = json.loads(row["value_json"])
        return rows

    def upsert(self, key: str, value_json: dict[str, Any]) -> dict[str, Any]:
        now = utc_now_iso()
        existing = self.database.fetch_one("SELECT id FROM app_settings WHERE key = ?", (key,))
        if existing:
            self.database.execute(
                "UPDATE app_settings SET value_json = ?, updated_at = ? WHERE key = ?",
                (json.dumps(value_json), now, key),
            )
        else:
            self.database.execute(
                "INSERT INTO app_settings (key, value_json, updated_at) VALUES (?, ?, ?)",
                (key, json.dumps(value_json), now),
            )
        return {"key": key, "value_json": value_json, "updated_at": now}
