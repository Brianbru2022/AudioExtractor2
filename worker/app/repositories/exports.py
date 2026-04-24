from __future__ import annotations

import json
from typing import Any

from app.db.database import Database
from app.utils.files import utc_now_iso


class ExportRunRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(
        self,
        *,
        meeting_id: int,
        export_profile: str,
        format: str,
        options_json: dict[str, Any],
        file_path: str,
    ) -> int:
        now = utc_now_iso()
        return self.database.execute(
            """
            INSERT INTO export_runs (
              meeting_id, export_profile, format, options_json, file_path, status,
              started_at, completed_at, error_message, created_at
            ) VALUES (?, ?, ?, ?, ?, 'running', ?, NULL, NULL, ?)
            """,
            (meeting_id, export_profile, format, json.dumps(options_json), file_path, now, now),
        )

    def finalize_success(self, export_run_id: int, *, file_path: str) -> None:
        self.database.execute(
            """
            UPDATE export_runs
            SET status = 'completed', file_path = ?, completed_at = ?, error_message = NULL
            WHERE id = ?
            """,
            (file_path, utc_now_iso(), export_run_id),
        )

    def finalize_failure(self, export_run_id: int, *, error_message: str) -> None:
        self.database.execute(
            """
            UPDATE export_runs
            SET status = 'failed', completed_at = ?, error_message = ?
            WHERE id = ?
            """,
            (utc_now_iso(), error_message, export_run_id),
        )

    def get(self, export_run_id: int) -> dict[str, Any] | None:
        row = self.database.fetch_one("SELECT * FROM export_runs WHERE id = ?", (export_run_id,))
        return _deserialize_export_run(row)

    def list_for_meeting(self, meeting_id: int) -> list[dict[str, Any]]:
        rows = self.database.fetch_all(
            "SELECT * FROM export_runs WHERE meeting_id = ? ORDER BY created_at DESC",
            (meeting_id,),
        )
        return [_deserialize_export_run(row) for row in rows]

    def delete_for_meeting(self, meeting_id: int, connection=None) -> None:
        executor = connection.execute if connection else self.database.execute
        executor("DELETE FROM export_runs WHERE meeting_id = ?", (meeting_id,))


def _deserialize_export_run(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    row["options_json"] = json.loads(row["options_json"])
    return row
