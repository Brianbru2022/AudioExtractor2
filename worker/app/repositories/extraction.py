from __future__ import annotations

import json
from typing import Any

from app.db.database import Database
from app.utils.files import utc_now_iso


class ExtractionRunRepository:
    def __init__(self, database: Database):
        self.database = database

    def create(
        self,
        *,
        meeting_id: int,
        transcription_run_id: int,
        job_run_id: int,
        model: str,
        model_version: str,
        config_json: dict[str, Any],
    ) -> int:
        return self.database.execute(
            """
            INSERT INTO extraction_runs (
              meeting_id, transcription_run_id, job_run_id, model, model_version, status,
              started_at, completed_at, config_json, error_message, created_at
            ) VALUES (?, ?, ?, ?, ?, 'pending', NULL, NULL, ?, NULL, ?)
            """,
            (
                meeting_id,
                transcription_run_id,
                job_run_id,
                model,
                model_version,
                json.dumps(config_json),
                utc_now_iso(),
            ),
        )

    def get(self, run_id: int) -> dict[str, Any] | None:
        row = self.database.fetch_one("SELECT * FROM extraction_runs WHERE id = ?", (run_id,))
        return _deserialize_run(row)

    def get_latest_for_meeting(self, meeting_id: int) -> dict[str, Any] | None:
        row = self.database.fetch_one(
            "SELECT * FROM extraction_runs WHERE meeting_id = ? ORDER BY id DESC LIMIT 1",
            (meeting_id,),
        )
        return _deserialize_run(row)

    def list_all(self) -> list[dict[str, Any]]:
        rows = self.database.fetch_all(
            """
            SELECT e.*, m.title AS meeting_title
            FROM extraction_runs e
            JOIN meetings m ON m.id = e.meeting_id
            ORDER BY e.created_at DESC
            """
        )
        return [_deserialize_run(row) for row in rows]

    def list_for_meeting(self, meeting_id: int) -> list[dict[str, Any]]:
        rows = self.database.fetch_all(
            "SELECT * FROM extraction_runs WHERE meeting_id = ? ORDER BY id ASC",
            (meeting_id,),
        )
        return [_deserialize_run(row) for row in rows]

    def mark_running(self, run_id: int) -> None:
        self.database.execute(
            "UPDATE extraction_runs SET status = 'running', started_at = COALESCE(started_at, ?) WHERE id = ?",
            (utc_now_iso(), run_id),
        )

    def finalize_success(self, run_id: int) -> None:
        self.database.execute(
            "UPDATE extraction_runs SET status = 'completed', completed_at = ? WHERE id = ?",
            (utc_now_iso(), run_id),
        )

    def finalize_failure(self, run_id: int, error_message: str) -> None:
        self.database.execute(
            "UPDATE extraction_runs SET status = 'failed', completed_at = ?, error_message = ? WHERE id = ?",
            (utc_now_iso(), error_message, run_id),
        )

    def delete_for_meeting(self, meeting_id: int, connection=None) -> None:
        executor = connection.execute if connection else self.database.execute
        executor("DELETE FROM extraction_runs WHERE meeting_id = ?", (meeting_id,))


class ExtractionEntityRepository:
    def __init__(self, database: Database, table_name: str) -> None:
        self.database = database
        self.table_name = table_name

    def replace_for_run(self, extraction_run_id: int, meeting_id: int, items: list[dict[str, Any]]) -> list[int]:
        self.database.execute(f"DELETE FROM {self.table_name} WHERE extraction_run_id = ?", (extraction_run_id,))
        ids: list[int] = []
        for item in items:
            ids.append(self._insert(extraction_run_id, meeting_id, item))
        return ids

    def list_for_run(self, extraction_run_id: int) -> list[dict[str, Any]]:
        return self.database.fetch_all(
            f"SELECT * FROM {self.table_name} WHERE extraction_run_id = ? ORDER BY id ASC",
            (extraction_run_id,),
        )

    def update(self, item_id: int, payload: dict[str, Any]) -> dict[str, Any] | None:
        existing = self.database.fetch_one(f"SELECT * FROM {self.table_name} WHERE id = ?", (item_id,))
        if not existing:
            return None
        columns = []
        params: list[Any] = []
        for key, value in payload.items():
            columns.append(f"{key} = ?")
            params.append(value)
        columns.append("updated_at = ?")
        params.append(utc_now_iso())
        params.append(item_id)
        self.database.execute(
            f"UPDATE {self.table_name} SET {', '.join(columns)} WHERE id = ?",
            tuple(params),
        )
        return self.database.fetch_one(f"SELECT * FROM {self.table_name} WHERE id = ?", (item_id,))

    def delete_for_meeting(self, meeting_id: int, connection=None) -> None:
        executor = connection.execute if connection else self.database.execute
        executor(f"DELETE FROM {self.table_name} WHERE meeting_id = ?", (meeting_id,))

    def _insert(self, extraction_run_id: int, meeting_id: int, item: dict[str, Any]) -> int:
        now = utc_now_iso()
        if self.table_name == "extracted_actions":
            return self.database.execute(
                """
                INSERT INTO extracted_actions (
                  extraction_run_id, meeting_id, text, owner, due_date, priority, confidence,
                  explicit_or_inferred, review_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    extraction_run_id,
                    meeting_id,
                    item["text"],
                    item.get("owner"),
                    item.get("due_date"),
                    item.get("priority"),
                    item["confidence"],
                    item["explicit_or_inferred"],
                    item.get("review_status", "pending"),
                    now,
                    now,
                ),
            )
        return self.database.execute(
            f"""
            INSERT INTO {self.table_name} (
              extraction_run_id, meeting_id, text, confidence, explicit_or_inferred,
              review_status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                extraction_run_id,
                meeting_id,
                item["text"],
                item["confidence"],
                item["explicit_or_inferred"],
                item.get("review_status", "pending"),
                now,
                now,
            ),
        )


class ExtractionEvidenceRepository:
    def __init__(self, database: Database):
        self.database = database

    def replace_for_run(self, extraction_run_id: int, links: list[dict[str, Any]]) -> None:
        self.database.execute("DELETE FROM extracted_evidence_links WHERE extraction_run_id = ?", (extraction_run_id,))
        for link in links:
            self.database.execute(
                """
                INSERT INTO extracted_evidence_links (
                  extraction_run_id, entity_type, entity_id, transcript_segment_id, start_ms, end_ms,
                  speaker_label, quote_snippet, confidence
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    extraction_run_id,
                    link["entity_type"],
                    link["entity_id"],
                    link.get("transcript_segment_id"),
                    link["start_ms"],
                    link["end_ms"],
                    link.get("speaker_label"),
                    link.get("quote_snippet"),
                    link.get("confidence"),
                ),
            )

    def list_for_run(self, extraction_run_id: int) -> list[dict[str, Any]]:
        return self.database.fetch_all(
            "SELECT * FROM extracted_evidence_links WHERE extraction_run_id = ? ORDER BY id ASC",
            (extraction_run_id,),
        )

    def delete_for_run_ids(self, extraction_run_ids: list[int], connection=None) -> None:
        if not extraction_run_ids:
            return
        placeholders = ", ".join(["?"] * len(extraction_run_ids))
        executor = connection.execute if connection else self.database.execute
        executor(
            f"DELETE FROM extracted_evidence_links WHERE extraction_run_id IN ({placeholders})",
            tuple(extraction_run_ids),
        )


class ExtractionSummaryRepository:
    def __init__(self, database: Database):
        self.database = database

    def replace_for_run(self, extraction_run_id: int, meeting_id: int, summary_text: str, minutes_text: str) -> None:
        self.database.execute("DELETE FROM extracted_summaries WHERE extraction_run_id = ?", (extraction_run_id,))
        self.database.execute(
            """
            INSERT INTO extracted_summaries (
              extraction_run_id, meeting_id, summary_text, minutes_text, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (extraction_run_id, meeting_id, summary_text, minutes_text, utc_now_iso()),
        )

    def get_for_run(self, extraction_run_id: int) -> dict[str, Any] | None:
        return self.database.fetch_one(
            "SELECT * FROM extracted_summaries WHERE extraction_run_id = ? ORDER BY id DESC LIMIT 1",
            (extraction_run_id,),
        )

    def delete_for_meeting(self, meeting_id: int, connection=None) -> None:
        executor = connection.execute if connection else self.database.execute
        executor("DELETE FROM extracted_summaries WHERE meeting_id = ?", (meeting_id,))


def _deserialize_run(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    row["config_json"] = json.loads(row["config_json"])
    return row
