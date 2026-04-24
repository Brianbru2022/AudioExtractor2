from __future__ import annotations

import json
from typing import Any

from app.db.database import Database
from app.utils.files import utc_now_iso


class JobRunRepository:
    def __init__(self, database: Database):
        self.database = database

    def create(self, meeting_id: int, job_type: str, initial_message: str) -> int:
        now = utc_now_iso()
        return self.database.execute(
            """
            INSERT INTO job_runs (
              meeting_id, job_type, status, stage, progress_percent, current_message,
              started_at, completed_at, error_message, created_at
            ) VALUES (?, ?, 'queued', 'queued', 0, ?, NULL, NULL, NULL, ?)
            """,
            (meeting_id, job_type, initial_message, now),
        )

    def update_state(
        self,
        job_run_id: int,
        *,
        status: str,
        stage: str,
        progress_percent: float,
        current_message: str,
    ) -> None:
        self.database.execute(
            """
            UPDATE job_runs
            SET status = ?, stage = ?, progress_percent = ?, current_message = ?,
                started_at = COALESCE(started_at, ?)
            WHERE id = ?
            """,
            (status, stage, progress_percent, current_message, utc_now_iso(), job_run_id),
        )

    def finalize(self, job_run_id: int, *, status: str, stage: str, current_message: str, error_message: str | None) -> None:
        self.database.execute(
            """
            UPDATE job_runs
            SET status = ?, stage = ?, progress_percent = CASE WHEN ? IN ('completed', 'completed_with_failures', 'recovered') THEN 100 ELSE progress_percent END,
                current_message = ?, completed_at = ?, error_message = ?
            WHERE id = ?
            """,
            (status, stage, status, current_message, utc_now_iso(), error_message, job_run_id),
        )

    def get(self, job_run_id: int) -> dict[str, Any] | None:
        return self.database.fetch_one(
            """
            SELECT j.*, m.title AS meeting_title
            FROM job_runs j
            JOIN meetings m ON m.id = j.meeting_id
            WHERE j.id = ?
            """,
            (job_run_id,),
        )

    def list_all(self) -> list[dict[str, Any]]:
        return self.database.fetch_all(
            """
            SELECT j.*, m.title AS meeting_title
            FROM job_runs j
            JOIN meetings m ON m.id = j.meeting_id
            ORDER BY j.created_at DESC
            """
        )

    def delete(self, job_run_id: int) -> None:
        self.database.execute("UPDATE preprocessing_runs SET job_run_id = NULL WHERE job_run_id = ?", (job_run_id,))
        self.database.execute("UPDATE transcription_runs SET job_run_id = NULL WHERE job_run_id = ?", (job_run_id,))
        self.database.execute("UPDATE extraction_runs SET job_run_id = NULL WHERE job_run_id = ?", (job_run_id,))
        self.database.execute("DELETE FROM job_runs WHERE id = ?", (job_run_id,))

    def list_for_meeting(self, meeting_id: int) -> list[dict[str, Any]]:
        return self.database.fetch_all(
            """
            SELECT j.*, m.title AS meeting_title
            FROM job_runs j
            JOIN meetings m ON m.id = j.meeting_id
            WHERE j.meeting_id = ?
            ORDER BY j.created_at DESC
            """,
            (meeting_id,),
        )

    def has_running_for_meeting(self, meeting_id: int) -> bool:
        row = self.database.fetch_one(
            "SELECT COUNT(*) AS count FROM job_runs WHERE meeting_id = ? AND status = 'running'",
            (meeting_id,),
        )
        return bool(row and row["count"])

    def delete_for_meeting(self, meeting_id: int, connection=None) -> None:
        executor = connection.execute if connection else self.database.execute
        executor("UPDATE preprocessing_runs SET job_run_id = NULL WHERE meeting_id = ?", (meeting_id,))
        executor("UPDATE transcription_runs SET job_run_id = NULL WHERE meeting_id = ?", (meeting_id,))
        executor("UPDATE extraction_runs SET job_run_id = NULL WHERE meeting_id = ?", (meeting_id,))
        executor("DELETE FROM job_runs WHERE meeting_id = ?", (meeting_id,))


class TranscriptionRunRepository:
    def __init__(self, database: Database):
        self.database = database

    def create(
        self,
        *,
        meeting_id: int,
        preprocessing_run_id: int,
        job_run_id: int,
        engine: str,
        engine_model: str,
        language_code: str,
        diarization_enabled: bool,
        automatic_punctuation_enabled: bool,
        chunk_count: int,
        config_json: dict[str, Any],
    ) -> int:
        return self.database.execute(
            """
            INSERT INTO transcription_runs (
              meeting_id, preprocessing_run_id, job_run_id, engine, engine_model,
              language_code, diarization_enabled, automatic_punctuation_enabled, status,
              started_at, completed_at, chunk_count, completed_chunk_count, failed_chunk_count,
              average_confidence, error_message, config_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, NULL, ?, 0, 0, NULL, NULL, ?, ?)
            """,
            (
                meeting_id,
                preprocessing_run_id,
                job_run_id,
                engine,
                engine_model,
                language_code,
                1 if diarization_enabled else 0,
                1 if automatic_punctuation_enabled else 0,
                chunk_count,
                json.dumps(config_json),
                utc_now_iso(),
            ),
        )

    def get(self, run_id: int) -> dict[str, Any] | None:
        row = self.database.fetch_one("SELECT * FROM transcription_runs WHERE id = ?", (run_id,))
        return _deserialize_transcription_run(row)

    def get_latest_for_meeting(self, meeting_id: int) -> dict[str, Any] | None:
        row = self.database.fetch_one(
            "SELECT * FROM transcription_runs WHERE meeting_id = ? ORDER BY id DESC LIMIT 1",
            (meeting_id,),
        )
        return _deserialize_transcription_run(row)

    def list_all(self) -> list[dict[str, Any]]:
        rows = self.database.fetch_all(
            """
            SELECT t.*, m.title AS meeting_title
            FROM transcription_runs t
            JOIN meetings m ON m.id = t.meeting_id
            ORDER BY t.created_at DESC
            """
        )
        return [_deserialize_transcription_run(row) for row in rows]

    def list_for_meeting(self, meeting_id: int) -> list[dict[str, Any]]:
        rows = self.database.fetch_all(
            "SELECT * FROM transcription_runs WHERE meeting_id = ? ORDER BY id ASC",
            (meeting_id,),
        )
        return [_deserialize_transcription_run(row) for row in rows]

    def mark_running(self, run_id: int) -> None:
        self.database.execute(
            """
            UPDATE transcription_runs
            SET status = 'running', started_at = COALESCE(started_at, ?), completed_at = NULL, error_message = NULL
            WHERE id = ?
            """,
            (utc_now_iso(), run_id),
        )

    def attach_job_run(self, run_id: int, job_run_id: int) -> None:
        self.database.execute(
            "UPDATE transcription_runs SET job_run_id = ? WHERE id = ?",
            (job_run_id, run_id),
        )

    def update_progress(self, run_id: int, *, completed_chunk_count: int, failed_chunk_count: int) -> None:
        self.database.execute(
            """
            UPDATE transcription_runs
            SET completed_chunk_count = ?, failed_chunk_count = ?
            WHERE id = ?
            """,
            (completed_chunk_count, failed_chunk_count, run_id),
        )

    def finalize_success(
        self,
        run_id: int,
        *,
        status: str = "completed",
        average_confidence: float | None,
        error_message: str | None = None,
    ) -> None:
        self.database.execute(
            """
            UPDATE transcription_runs
            SET status = ?, completed_at = ?, average_confidence = ?, error_message = ?
            WHERE id = ?
            """,
            (status, utc_now_iso(), average_confidence, error_message, run_id),
        )

    def finalize_failure(self, run_id: int, *, error_message: str) -> None:
        self.database.execute(
            """
            UPDATE transcription_runs
            SET status = 'failed', completed_at = ?, error_message = ?
            WHERE id = ?
            """,
            (utc_now_iso(), error_message, run_id),
        )

    def delete_for_meeting(self, meeting_id: int, connection=None) -> None:
        executor = connection.execute if connection else self.database.execute
        executor("DELETE FROM transcription_runs WHERE meeting_id = ?", (meeting_id,))


class ChunkTranscriptRepository:
    def __init__(self, database: Database):
        self.database = database

    def upsert(self, payload: dict[str, Any]) -> int:
        existing = self.database.fetch_one(
            "SELECT id FROM chunk_transcripts WHERE transcription_run_id = ? AND chunk_id = ?",
            (payload["transcription_run_id"], payload["chunk_id"]),
        )
        params = (
            payload["meeting_id"],
            payload["chunk_id"],
            payload["transcription_run_id"],
            payload["engine"],
            payload["engine_model"],
            payload["status"],
            payload["transcript_text"],
            json.dumps(payload["raw_response_json"]),
            payload["average_confidence"],
            payload["started_at"],
            payload["completed_at"],
            payload["error_message"],
            json.dumps(payload["request_config_json"]),
        )
        if existing:
            self.database.execute(
                """
                UPDATE chunk_transcripts
                SET meeting_id = ?, chunk_id = ?, transcription_run_id = ?, engine = ?, engine_model = ?,
                    status = ?, transcript_text = ?, raw_response_json = ?, average_confidence = ?,
                    started_at = ?, completed_at = ?, error_message = ?, request_config_json = ?
                WHERE id = ?
                """,
                params + (existing["id"],),
            )
            return int(existing["id"])
        return self.database.execute(
            """
            INSERT INTO chunk_transcripts (
              meeting_id, chunk_id, transcription_run_id, engine, engine_model, status,
              transcript_text, raw_response_json, average_confidence, started_at, completed_at,
              error_message, request_config_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            params,
        )

    def list_for_run(self, transcription_run_id: int) -> list[dict[str, Any]]:
        rows = self.database.fetch_all(
            """
            SELECT ct.*, c.chunk_index, c.start_ms, c.end_ms, c.overlap_before_ms, c.overlap_after_ms
            FROM chunk_transcripts ct
            JOIN chunks c ON c.id = ct.chunk_id
            WHERE ct.transcription_run_id = ?
            ORDER BY c.chunk_index ASC
            """,
            (transcription_run_id,),
        )
        for row in rows:
            row["raw_response_json"] = json.loads(row["raw_response_json"])
            row["request_config_json"] = json.loads(row["request_config_json"])
        return rows

    def get(self, transcription_run_id: int, chunk_id: int) -> dict[str, Any] | None:
        row = self.database.fetch_one(
            """
            SELECT ct.*, c.chunk_index, c.start_ms, c.end_ms, c.overlap_before_ms, c.overlap_after_ms
            FROM chunk_transcripts ct
            JOIN chunks c ON c.id = ct.chunk_id
            WHERE ct.transcription_run_id = ? AND ct.chunk_id = ?
            """,
            (transcription_run_id, chunk_id),
        )
        if not row:
            return None
        row["raw_response_json"] = json.loads(row["raw_response_json"])
        row["request_config_json"] = json.loads(row["request_config_json"])
        return row

    def list_failed_for_run(self, transcription_run_id: int) -> list[dict[str, Any]]:
        rows = self.database.fetch_all(
            """
            SELECT ct.*, c.file_path, c.chunk_index, c.start_ms, c.end_ms, c.overlap_before_ms, c.overlap_after_ms
            FROM chunk_transcripts ct
            JOIN chunks c ON c.id = ct.chunk_id
            WHERE ct.transcription_run_id = ? AND ct.status = 'failed'
            ORDER BY c.chunk_index ASC
            """,
            (transcription_run_id,),
        )
        for row in rows:
            row["raw_response_json"] = json.loads(row["raw_response_json"])
            row["request_config_json"] = json.loads(row["request_config_json"])
        return rows

    def delete_for_meeting(self, meeting_id: int, connection=None) -> None:
        executor = connection.execute if connection else self.database.execute
        executor("DELETE FROM chunk_transcripts WHERE meeting_id = ?", (meeting_id,))


class ChunkTranscriptAttemptRepository:
    def __init__(self, database: Database):
        self.database = database

    def next_attempt_number(self, transcription_run_id: int, chunk_id: int) -> int:
        row = self.database.fetch_one(
            """
            SELECT COALESCE(MAX(attempt_number), 0) AS attempt_number
            FROM chunk_transcript_attempts
            WHERE transcription_run_id = ? AND chunk_id = ?
            """,
            (transcription_run_id, chunk_id),
        )
        return int(row["attempt_number"]) + 1 if row else 1

    def create(self, payload: dict[str, Any]) -> int:
        return self.database.execute(
            """
            INSERT INTO chunk_transcript_attempts (
              meeting_id, chunk_id, transcription_run_id, chunk_transcript_id, attempt_number,
              retried_from_attempt_id, engine, engine_model, status, transcript_text, raw_response_json,
              average_confidence, started_at, completed_at, error_message, request_config_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payload["meeting_id"],
                payload["chunk_id"],
                payload["transcription_run_id"],
                payload.get("chunk_transcript_id"),
                payload["attempt_number"],
                payload.get("retried_from_attempt_id"),
                payload["engine"],
                payload["engine_model"],
                payload["status"],
                payload["transcript_text"],
                json.dumps(payload["raw_response_json"]),
                payload["average_confidence"],
                payload["started_at"],
                payload["completed_at"],
                payload["error_message"],
                json.dumps(payload["request_config_json"]),
                utc_now_iso(),
            ),
        )

    def list_for_run(self, transcription_run_id: int) -> list[dict[str, Any]]:
        rows = self.database.fetch_all(
            """
            SELECT a.*, c.chunk_index
            FROM chunk_transcript_attempts a
            JOIN chunks c ON c.id = a.chunk_id
            WHERE a.transcription_run_id = ?
            ORDER BY c.chunk_index ASC, a.attempt_number ASC
            """,
            (transcription_run_id,),
        )
        for row in rows:
            row["raw_response_json"] = json.loads(row["raw_response_json"])
            row["request_config_json"] = json.loads(row["request_config_json"])
        return rows

    def get_latest_for_chunk(self, transcription_run_id: int, chunk_id: int) -> dict[str, Any] | None:
        row = self.database.fetch_one(
            """
            SELECT *
            FROM chunk_transcript_attempts
            WHERE transcription_run_id = ? AND chunk_id = ?
            ORDER BY attempt_number DESC
            LIMIT 1
            """,
            (transcription_run_id, chunk_id),
        )
        if not row:
            return None
        row["raw_response_json"] = json.loads(row["raw_response_json"])
        row["request_config_json"] = json.loads(row["request_config_json"])
        return row

    def delete_for_meeting(self, meeting_id: int, connection=None) -> None:
        executor = connection.execute if connection else self.database.execute
        executor("DELETE FROM chunk_transcript_attempts WHERE meeting_id = ?", (meeting_id,))


class TranscriptSegmentRepository:
    def __init__(self, database: Database):
        self.database = database

    def replace_for_run(self, transcription_run_id: int, source_type: str, segments: list[dict[str, Any]]) -> list[int]:
        ids: list[int] = []
        with self.database.transaction() as connection:
            connection.execute(
                "DELETE FROM transcript_segments WHERE transcription_run_id = ? AND source_type = ?",
                (transcription_run_id, source_type),
            )
            for segment in segments:
                cursor = connection.execute(
                    """
                    INSERT INTO transcript_segments (
                      meeting_id, transcription_run_id, chunk_id, segment_index, speaker_label, speaker_name,
                      text, start_ms_in_meeting, end_ms_in_meeting, start_ms_in_chunk, end_ms_in_chunk,
                      confidence, excluded_from_review, exclusion_reason, source_type, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        segment["meeting_id"],
                        transcription_run_id,
                        segment.get("chunk_id"),
                        segment["segment_index"],
                        segment.get("speaker_label"),
                        segment.get("speaker_name"),
                        segment["text"],
                        segment["start_ms_in_meeting"],
                        segment["end_ms_in_meeting"],
                        segment.get("start_ms_in_chunk"),
                        segment.get("end_ms_in_chunk"),
                        segment.get("confidence"),
                        1 if segment.get("excluded_from_review") else 0,
                        segment.get("exclusion_reason"),
                        source_type,
                        utc_now_iso(),
                    ),
                )
                ids.append(int(cursor.lastrowid))
        return ids

    def list_for_run(
        self,
        transcription_run_id: int,
        source_type: str,
        *,
        include_excluded: bool = True,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT * FROM transcript_segments
            WHERE transcription_run_id = ? AND source_type = ?
        """
        params: list[Any] = [transcription_run_id, source_type]
        if not include_excluded:
            sql += " AND excluded_from_review = 0"
        sql += " ORDER BY segment_index ASC"
        rows = self.database.fetch_all(sql, tuple(params))
        for row in rows:
            row["excluded_from_review"] = bool(row.get("excluded_from_review"))
        return rows

    def assign_speaker_name(self, transcription_run_id: int, speaker_label: str, speaker_name: str | None) -> int:
        normalized_name = speaker_name.strip() if isinstance(speaker_name, str) else None
        self.database.execute(
            """
            UPDATE transcript_segments
            SET speaker_name = ?
            WHERE transcription_run_id = ? AND speaker_label = ? AND excluded_from_review = 0
            """,
            (normalized_name or None, transcription_run_id, speaker_label),
        )
        row = self.database.fetch_one(
            """
            SELECT COUNT(*) AS count
            FROM transcript_segments
            WHERE transcription_run_id = ? AND speaker_label = ? AND excluded_from_review = 0
            """,
            (transcription_run_id, speaker_label),
        )
        return int(row["count"]) if row else 0

    def update_review_exclusions(
        self,
        transcription_run_id: int,
        segment_ids: list[int],
        *,
        excluded_from_review: bool,
        exclusion_reason: str | None,
    ) -> int:
        if not segment_ids:
            return 0
        placeholders = ", ".join("?" for _ in segment_ids)
        normalized_reason = exclusion_reason.strip() if isinstance(exclusion_reason, str) and exclusion_reason.strip() else None
        params: list[Any] = [
            1 if excluded_from_review else 0,
            normalized_reason if excluded_from_review else None,
            transcription_run_id,
            *segment_ids,
        ]
        self.database.execute(
            f"""
            UPDATE transcript_segments
            SET excluded_from_review = ?, exclusion_reason = ?
            WHERE transcription_run_id = ? AND id IN ({placeholders})
            """,
            tuple(params),
        )
        row = self.database.fetch_one(
            f"""
            SELECT COUNT(*) AS count
            FROM transcript_segments
            WHERE transcription_run_id = ? AND id IN ({placeholders})
            """,
            tuple([transcription_run_id, *segment_ids]),
        )
        return int(row["count"]) if row else 0

    def delete_for_meeting(self, meeting_id: int, connection=None) -> None:
        executor = connection.execute if connection else self.database.execute
        executor("DELETE FROM transcript_segments WHERE meeting_id = ?", (meeting_id,))


class TranscriptWordRepository:
    def __init__(self, database: Database):
        self.database = database

    def replace_for_run(self, transcription_run_id: int, words: list[dict[str, Any]]) -> None:
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM transcript_words WHERE transcription_run_id = ?", (transcription_run_id,))
            connection.executemany(
                """
                INSERT INTO transcript_words (
                  meeting_id, transcription_run_id, chunk_id, segment_id, word_index, word_text,
                  start_ms_in_meeting, end_ms_in_meeting, start_ms_in_chunk, end_ms_in_chunk,
                  speaker_label, confidence, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        word["meeting_id"],
                        transcription_run_id,
                        word["chunk_id"],
                        word.get("segment_id"),
                        word["word_index"],
                        word["word_text"],
                        word["start_ms_in_meeting"],
                        word["end_ms_in_meeting"],
                        word.get("start_ms_in_chunk"),
                        word.get("end_ms_in_chunk"),
                        word.get("speaker_label"),
                        word.get("confidence"),
                        utc_now_iso(),
                    )
                    for word in words
                ],
            )

    def list_for_run(self, transcription_run_id: int) -> list[dict[str, Any]]:
        return self.database.fetch_all(
            """
            SELECT * FROM transcript_words
            WHERE transcription_run_id = ?
            ORDER BY word_index ASC
            """,
            (transcription_run_id,),
        )

    def delete_for_meeting(self, meeting_id: int, connection=None) -> None:
        executor = connection.execute if connection else self.database.execute
        executor("DELETE FROM transcript_words WHERE meeting_id = ?", (meeting_id,))


def _deserialize_transcription_run(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    row["config_json"] = json.loads(row["config_json"])
    row["diarization_enabled"] = bool(row["diarization_enabled"])
    row["automatic_punctuation_enabled"] = bool(row["automatic_punctuation_enabled"])
    return row
