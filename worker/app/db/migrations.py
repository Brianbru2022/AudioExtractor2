from __future__ import annotations

import json

from app.core.config import config
from app.db.database import Database
from app.utils.files import ensure_directory, utc_now_iso

SCHEMA_VERSION = 7

DEFAULT_SETTINGS = {
    "chunk_defaults": {
        "target_ms": config.chunk_defaults.target_ms,
        "hard_max_ms": config.chunk_defaults.hard_max_ms,
        "min_chunk_ms": config.chunk_defaults.min_chunk_ms,
        "overlap_ms": config.chunk_defaults.overlap_ms,
        "min_silence_ms": config.chunk_defaults.min_silence_ms,
        "silence_threshold_db": config.chunk_defaults.silence_threshold_db,
    },
    "transcription_defaults": {
        "project_id": "",
        "auth_mode": "application_default_credentials",
        "credentials_path": "",
        "recognizer_location": "global",
        "recognizer_id": "_",
        "staging_bucket": "",
        "staging_prefix": "audio-extractor-2",
        "model": config.transcription_defaults.model,
        "language_code": config.transcription_defaults.language_code,
        "alternative_language_codes": [],
        "diarization_enabled": config.transcription_defaults.diarization_enabled,
        "min_speaker_count": config.transcription_defaults.min_speaker_count,
        "max_speaker_count": config.transcription_defaults.max_speaker_count,
        "automatic_punctuation_enabled": config.transcription_defaults.automatic_punctuation_enabled,
        "profanity_filter_enabled": config.transcription_defaults.profanity_filter_enabled,
        "enable_word_time_offsets": config.transcription_defaults.enable_word_time_offsets,
        "enable_word_confidence": config.transcription_defaults.enable_word_confidence,
        "max_parallel_chunks": config.transcription_defaults.max_parallel_chunks,
        "phrase_hints_placeholder": [],
        "low_confidence_threshold": config.transcription_defaults.low_confidence_threshold,
    },
    "gemini_defaults": {
        "auth_mode": "api_key_env",
        "api_key_env_var": "GEMINI_API_KEY",
        "api_key_file_path": "",
        "api_base_url": "https://generativelanguage.googleapis.com/v1beta",
        "model": "gemini-3.1-pro-preview",
        "extraction_model": "gemini-3.1-pro-preview",
        "minutes_model": "gemini-3.1-pro-preview",
        "fallback_model": "gemini-3-flash-preview",
        "thinking_level": "medium",
        "temperature": 1.0,
        "response_mime_type": "application/json",
        "max_segments_per_batch": 80,
        "max_evidence_items_per_entity": 5,
        "low_confidence_threshold": 0.7,
    },
}

CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version INTEGER PRIMARY KEY,
  applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meetings (
  id INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  meeting_date TEXT NULL,
  project TEXT NULL,
  notes TEXT NULL,
  attendees_json TEXT NOT NULL DEFAULT '[]',
  circulation_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS source_files (
  id INTEGER PRIMARY KEY,
  meeting_id INTEGER NOT NULL,
  import_mode TEXT NOT NULL,
  original_path TEXT NOT NULL,
  managed_copy_path TEXT NULL,
  normalized_audio_path TEXT NULL,
  file_name TEXT NOT NULL,
  extension TEXT NOT NULL,
  mime_type TEXT NOT NULL,
  media_type TEXT NOT NULL,
  size_bytes INTEGER NOT NULL,
  sha256 TEXT NOT NULL,
  duration_ms INTEGER NOT NULL,
  sample_rate INTEGER NULL,
  channels INTEGER NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(meeting_id) REFERENCES meetings(id)
);

CREATE TABLE IF NOT EXISTS preprocessing_runs (
  id INTEGER PRIMARY KEY,
  meeting_id INTEGER NOT NULL,
  job_run_id INTEGER NULL,
  started_at TEXT NULL,
  completed_at TEXT NULL,
  status TEXT NOT NULL,
  stage TEXT NOT NULL,
  progress_percent REAL NOT NULL,
  current_message TEXT NULL,
  worker_version TEXT NOT NULL,
  normalized_format TEXT NULL,
  normalized_sample_rate INTEGER NULL,
  normalized_channels INTEGER NULL,
  log_json TEXT NOT NULL,
  silence_map_json TEXT NULL,
  chunking_strategy_json TEXT NOT NULL,
  waveform_summary_json TEXT NULL,
  error_message TEXT NULL,
  retry_of_run_id INTEGER NULL,
  cancel_requested_at TEXT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(meeting_id) REFERENCES meetings(id),
  FOREIGN KEY(job_run_id) REFERENCES job_runs(id)
);

CREATE TABLE IF NOT EXISTS chunks (
  id INTEGER PRIMARY KEY,
  meeting_id INTEGER NOT NULL,
  preprocessing_run_id INTEGER NOT NULL,
  chunk_index INTEGER NOT NULL,
  file_path TEXT NOT NULL,
  sha256 TEXT NOT NULL,
  start_ms INTEGER NOT NULL,
  end_ms INTEGER NOT NULL,
  overlap_before_ms INTEGER NOT NULL,
  overlap_after_ms INTEGER NOT NULL,
  duration_ms INTEGER NOT NULL,
  boundary_reason TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(meeting_id) REFERENCES meetings(id),
  FOREIGN KEY(preprocessing_run_id) REFERENCES preprocessing_runs(id),
  UNIQUE(preprocessing_run_id, chunk_index)
);

CREATE TABLE IF NOT EXISTS artifacts (
  id INTEGER PRIMARY KEY,
  meeting_id INTEGER NOT NULL,
  preprocessing_run_id INTEGER NULL,
  transcription_run_id INTEGER NULL,
  extraction_run_id INTEGER NULL,
  artifact_type TEXT NOT NULL,
  role TEXT NOT NULL,
  path TEXT NOT NULL,
  mime_type TEXT NULL,
  sha256 TEXT NULL,
  size_bytes INTEGER NULL,
  metadata_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(meeting_id) REFERENCES meetings(id),
  FOREIGN KEY(preprocessing_run_id) REFERENCES preprocessing_runs(id),
  FOREIGN KEY(transcription_run_id) REFERENCES transcription_runs(id),
  FOREIGN KEY(extraction_run_id) REFERENCES extraction_runs(id)
);

CREATE TABLE IF NOT EXISTS job_runs (
  id INTEGER PRIMARY KEY,
  meeting_id INTEGER NOT NULL,
  job_type TEXT NOT NULL,
  status TEXT NOT NULL,
  stage TEXT NOT NULL,
  progress_percent REAL NOT NULL,
  current_message TEXT NULL,
  started_at TEXT NULL,
  completed_at TEXT NULL,
  error_message TEXT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(meeting_id) REFERENCES meetings(id)
);

CREATE TABLE IF NOT EXISTS transcription_runs (
  id INTEGER PRIMARY KEY,
  meeting_id INTEGER NOT NULL,
  preprocessing_run_id INTEGER NULL,
  job_run_id INTEGER NULL,
  engine TEXT NOT NULL,
  engine_model TEXT NOT NULL,
  language_code TEXT NOT NULL,
  diarization_enabled INTEGER NOT NULL,
  automatic_punctuation_enabled INTEGER NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NULL,
  completed_at TEXT NULL,
  chunk_count INTEGER NOT NULL,
  completed_chunk_count INTEGER NOT NULL,
  failed_chunk_count INTEGER NOT NULL,
  average_confidence REAL NULL,
  error_message TEXT NULL,
  config_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(meeting_id) REFERENCES meetings(id),
  FOREIGN KEY(preprocessing_run_id) REFERENCES preprocessing_runs(id),
  FOREIGN KEY(job_run_id) REFERENCES job_runs(id)
);

CREATE TABLE IF NOT EXISTS chunk_transcripts (
  id INTEGER PRIMARY KEY,
  meeting_id INTEGER NOT NULL,
  chunk_id INTEGER NOT NULL,
  transcription_run_id INTEGER NOT NULL,
  engine TEXT NOT NULL,
  engine_model TEXT NOT NULL,
  status TEXT NOT NULL,
  transcript_text TEXT NOT NULL,
  raw_response_json TEXT NOT NULL,
  average_confidence REAL NULL,
  started_at TEXT NULL,
  completed_at TEXT NULL,
  error_message TEXT NULL,
  request_config_json TEXT NOT NULL,
  FOREIGN KEY(meeting_id) REFERENCES meetings(id),
  FOREIGN KEY(chunk_id) REFERENCES chunks(id),
  FOREIGN KEY(transcription_run_id) REFERENCES transcription_runs(id),
  UNIQUE(transcription_run_id, chunk_id)
);

CREATE TABLE IF NOT EXISTS transcript_segments (
  id INTEGER PRIMARY KEY,
  meeting_id INTEGER NOT NULL,
  transcription_run_id INTEGER NOT NULL,
  chunk_id INTEGER NULL,
  segment_index INTEGER NOT NULL,
  speaker_label TEXT NULL,
  speaker_name TEXT NULL,
  text TEXT NOT NULL,
  start_ms_in_meeting INTEGER NOT NULL,
  end_ms_in_meeting INTEGER NOT NULL,
  start_ms_in_chunk INTEGER NULL,
  end_ms_in_chunk INTEGER NULL,
  confidence REAL NULL,
  excluded_from_review INTEGER NOT NULL DEFAULT 0,
  exclusion_reason TEXT NULL,
  source_type TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(meeting_id) REFERENCES meetings(id),
  FOREIGN KEY(transcription_run_id) REFERENCES transcription_runs(id),
  FOREIGN KEY(chunk_id) REFERENCES chunks(id)
);

CREATE TABLE IF NOT EXISTS transcript_words (
  id INTEGER PRIMARY KEY,
  meeting_id INTEGER NOT NULL,
  transcription_run_id INTEGER NOT NULL,
  chunk_id INTEGER NOT NULL,
  segment_id INTEGER NULL,
  word_index INTEGER NOT NULL,
  word_text TEXT NOT NULL,
  start_ms_in_meeting INTEGER NOT NULL,
  end_ms_in_meeting INTEGER NOT NULL,
  start_ms_in_chunk INTEGER NULL,
  end_ms_in_chunk INTEGER NULL,
  speaker_label TEXT NULL,
  confidence REAL NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(meeting_id) REFERENCES meetings(id),
  FOREIGN KEY(transcription_run_id) REFERENCES transcription_runs(id),
  FOREIGN KEY(chunk_id) REFERENCES chunks(id),
  FOREIGN KEY(segment_id) REFERENCES transcript_segments(id)
);

CREATE TABLE IF NOT EXISTS chunk_transcript_attempts (
  id INTEGER PRIMARY KEY,
  meeting_id INTEGER NOT NULL,
  chunk_id INTEGER NOT NULL,
  transcription_run_id INTEGER NOT NULL,
  chunk_transcript_id INTEGER NULL,
  attempt_number INTEGER NOT NULL,
  retried_from_attempt_id INTEGER NULL,
  engine TEXT NOT NULL,
  engine_model TEXT NOT NULL,
  status TEXT NOT NULL,
  transcript_text TEXT NOT NULL,
  raw_response_json TEXT NOT NULL,
  average_confidence REAL NULL,
  started_at TEXT NULL,
  completed_at TEXT NULL,
  error_message TEXT NULL,
  request_config_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(meeting_id) REFERENCES meetings(id),
  FOREIGN KEY(chunk_id) REFERENCES chunks(id),
  FOREIGN KEY(transcription_run_id) REFERENCES transcription_runs(id),
  FOREIGN KEY(chunk_transcript_id) REFERENCES chunk_transcripts(id),
  FOREIGN KEY(retried_from_attempt_id) REFERENCES chunk_transcript_attempts(id),
  UNIQUE(transcription_run_id, chunk_id, attempt_number)
);

CREATE TABLE IF NOT EXISTS extraction_runs (
  id INTEGER PRIMARY KEY,
  meeting_id INTEGER NOT NULL,
  transcription_run_id INTEGER NOT NULL,
  job_run_id INTEGER NOT NULL,
  model TEXT NOT NULL,
  model_version TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NULL,
  completed_at TEXT NULL,
  config_json TEXT NOT NULL,
  error_message TEXT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(meeting_id) REFERENCES meetings(id),
  FOREIGN KEY(transcription_run_id) REFERENCES transcription_runs(id),
  FOREIGN KEY(job_run_id) REFERENCES job_runs(id)
);

CREATE TABLE IF NOT EXISTS extracted_actions (
  id INTEGER PRIMARY KEY,
  extraction_run_id INTEGER NOT NULL,
  meeting_id INTEGER NOT NULL,
  text TEXT NOT NULL,
  owner TEXT NULL,
  due_date TEXT NULL,
  priority TEXT NULL,
  confidence REAL NOT NULL,
  explicit_or_inferred TEXT NOT NULL,
  review_status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(extraction_run_id) REFERENCES extraction_runs(id),
  FOREIGN KEY(meeting_id) REFERENCES meetings(id)
);

CREATE TABLE IF NOT EXISTS extracted_decisions (
  id INTEGER PRIMARY KEY,
  extraction_run_id INTEGER NOT NULL,
  meeting_id INTEGER NOT NULL,
  text TEXT NOT NULL,
  confidence REAL NOT NULL,
  explicit_or_inferred TEXT NOT NULL,
  review_status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(extraction_run_id) REFERENCES extraction_runs(id),
  FOREIGN KEY(meeting_id) REFERENCES meetings(id)
);

CREATE TABLE IF NOT EXISTS extracted_risks (
  id INTEGER PRIMARY KEY,
  extraction_run_id INTEGER NOT NULL,
  meeting_id INTEGER NOT NULL,
  text TEXT NOT NULL,
  confidence REAL NOT NULL,
  explicit_or_inferred TEXT NOT NULL,
  review_status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(extraction_run_id) REFERENCES extraction_runs(id),
  FOREIGN KEY(meeting_id) REFERENCES meetings(id)
);

CREATE TABLE IF NOT EXISTS extracted_questions (
  id INTEGER PRIMARY KEY,
  extraction_run_id INTEGER NOT NULL,
  meeting_id INTEGER NOT NULL,
  text TEXT NOT NULL,
  confidence REAL NOT NULL,
  explicit_or_inferred TEXT NOT NULL,
  review_status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(extraction_run_id) REFERENCES extraction_runs(id),
  FOREIGN KEY(meeting_id) REFERENCES meetings(id)
);

CREATE TABLE IF NOT EXISTS extracted_topics (
  id INTEGER PRIMARY KEY,
  extraction_run_id INTEGER NOT NULL,
  meeting_id INTEGER NOT NULL,
  text TEXT NOT NULL,
  confidence REAL NOT NULL,
  explicit_or_inferred TEXT NOT NULL,
  review_status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  FOREIGN KEY(extraction_run_id) REFERENCES extraction_runs(id),
  FOREIGN KEY(meeting_id) REFERENCES meetings(id)
);

CREATE TABLE IF NOT EXISTS extracted_evidence_links (
  id INTEGER PRIMARY KEY,
  extraction_run_id INTEGER NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id INTEGER NOT NULL,
  transcript_segment_id INTEGER NULL,
  start_ms INTEGER NOT NULL,
  end_ms INTEGER NOT NULL,
  speaker_label TEXT NULL,
  quote_snippet TEXT NULL,
  confidence REAL NULL,
  FOREIGN KEY(extraction_run_id) REFERENCES extraction_runs(id),
  FOREIGN KEY(transcript_segment_id) REFERENCES transcript_segments(id)
);

CREATE TABLE IF NOT EXISTS extracted_summaries (
  id INTEGER PRIMARY KEY,
  extraction_run_id INTEGER NOT NULL,
  meeting_id INTEGER NOT NULL,
  summary_text TEXT NOT NULL,
  minutes_text TEXT NOT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(extraction_run_id) REFERENCES extraction_runs(id),
  FOREIGN KEY(meeting_id) REFERENCES meetings(id)
);

CREATE TABLE IF NOT EXISTS app_settings (
  id INTEGER PRIMARY KEY,
  key TEXT NOT NULL UNIQUE,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS export_runs (
  id INTEGER PRIMARY KEY,
  meeting_id INTEGER NOT NULL,
  export_profile TEXT NOT NULL,
  format TEXT NOT NULL,
  options_json TEXT NOT NULL,
  file_path TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NULL,
  completed_at TEXT NULL,
  error_message TEXT NULL,
  created_at TEXT NOT NULL,
  FOREIGN KEY(meeting_id) REFERENCES meetings(id)
);

CREATE INDEX IF NOT EXISTS idx_meetings_status_date ON meetings(status, meeting_date);
CREATE INDEX IF NOT EXISTS idx_source_files_meeting_id ON source_files(meeting_id);
CREATE INDEX IF NOT EXISTS idx_source_files_sha256 ON source_files(sha256);
CREATE INDEX IF NOT EXISTS idx_preprocessing_runs_meeting_status_stage ON preprocessing_runs(meeting_id, status, stage);
CREATE INDEX IF NOT EXISTS idx_chunks_meeting_run_index ON chunks(meeting_id, preprocessing_run_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_artifacts_lookup ON artifacts(meeting_id, preprocessing_run_id, artifact_type, role);
CREATE INDEX IF NOT EXISTS idx_job_runs_meeting_type_status ON job_runs(meeting_id, job_type, status);
CREATE INDEX IF NOT EXISTS idx_transcription_runs_meeting_status ON transcription_runs(meeting_id, status);
CREATE INDEX IF NOT EXISTS idx_chunk_transcripts_run_chunk ON chunk_transcripts(transcription_run_id, chunk_id);
CREATE INDEX IF NOT EXISTS idx_segments_meeting_run_source_index ON transcript_segments(meeting_id, transcription_run_id, source_type, segment_index);
CREATE INDEX IF NOT EXISTS idx_words_meeting_run_chunk_index ON transcript_words(meeting_id, transcription_run_id, chunk_id, word_index);
CREATE INDEX IF NOT EXISTS idx_chunk_transcript_attempts_run_chunk_attempt ON chunk_transcript_attempts(transcription_run_id, chunk_id, attempt_number);
CREATE INDEX IF NOT EXISTS idx_extraction_runs_meeting_status ON extraction_runs(meeting_id, status);
CREATE INDEX IF NOT EXISTS idx_extracted_actions_run_meeting ON extracted_actions(extraction_run_id, meeting_id, review_status);
CREATE INDEX IF NOT EXISTS idx_extracted_decisions_run_meeting ON extracted_decisions(extraction_run_id, meeting_id, review_status);
CREATE INDEX IF NOT EXISTS idx_extracted_risks_run_meeting ON extracted_risks(extraction_run_id, meeting_id, review_status);
CREATE INDEX IF NOT EXISTS idx_extracted_questions_run_meeting ON extracted_questions(extraction_run_id, meeting_id, review_status);
CREATE INDEX IF NOT EXISTS idx_extracted_topics_run_meeting ON extracted_topics(extraction_run_id, meeting_id, review_status);
CREATE INDEX IF NOT EXISTS idx_extracted_evidence_entity ON extracted_evidence_links(extraction_run_id, entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_extracted_summaries_run_meeting ON extracted_summaries(extraction_run_id, meeting_id);
CREATE INDEX IF NOT EXISTS idx_export_runs_meeting_created ON export_runs(meeting_id, created_at);
"""


def bootstrap_database(database: Database) -> None:
    ensure_directory(config.db_path.parent)
    database.execute_script(CREATE_TABLES_SQL)
    _apply_migrations(database)

    migration = database.fetch_one("SELECT version FROM schema_migrations WHERE version = ?", (SCHEMA_VERSION,))
    if not migration:
        database.execute(
            "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
            (SCHEMA_VERSION, utc_now_iso()),
        )

    for key, payload in DEFAULT_SETTINGS.items():
        existing = database.fetch_one("SELECT id FROM app_settings WHERE key = ?", (key,))
        if not existing:
            database.execute(
                "INSERT INTO app_settings (key, value_json, updated_at) VALUES (?, ?, ?)",
                (key, json.dumps(payload), utc_now_iso()),
            )


def _apply_migrations(database: Database) -> None:
    _add_column_if_missing(database, "preprocessing_runs", "job_run_id", "INTEGER NULL")
    _add_column_if_missing(database, "artifacts", "transcription_run_id", "INTEGER NULL")
    _add_column_if_missing(database, "artifacts", "extraction_run_id", "INTEGER NULL")
    _create_index_if_missing(
        database,
        "idx_artifacts_transcription_lookup",
        "CREATE INDEX idx_artifacts_transcription_lookup ON artifacts(meeting_id, transcription_run_id, artifact_type, role)",
    )
    _create_index_if_missing(
        database,
        "idx_artifacts_extraction_lookup",
        "CREATE INDEX idx_artifacts_extraction_lookup ON artifacts(meeting_id, extraction_run_id, artifact_type, role)",
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS chunk_transcript_attempts (
          id INTEGER PRIMARY KEY,
          meeting_id INTEGER NOT NULL,
          chunk_id INTEGER NOT NULL,
          transcription_run_id INTEGER NOT NULL,
          chunk_transcript_id INTEGER NULL,
          attempt_number INTEGER NOT NULL,
          retried_from_attempt_id INTEGER NULL,
          engine TEXT NOT NULL,
          engine_model TEXT NOT NULL,
          status TEXT NOT NULL,
          transcript_text TEXT NOT NULL,
          raw_response_json TEXT NOT NULL,
          average_confidence REAL NULL,
          started_at TEXT NULL,
          completed_at TEXT NULL,
          error_message TEXT NULL,
          request_config_json TEXT NOT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(meeting_id) REFERENCES meetings(id),
          FOREIGN KEY(chunk_id) REFERENCES chunks(id),
          FOREIGN KEY(transcription_run_id) REFERENCES transcription_runs(id),
          FOREIGN KEY(chunk_transcript_id) REFERENCES chunk_transcripts(id),
          FOREIGN KEY(retried_from_attempt_id) REFERENCES chunk_transcript_attempts(id),
          UNIQUE(transcription_run_id, chunk_id, attempt_number)
        )
        """
    )
    _create_index_if_missing(
        database,
        "idx_chunk_transcript_attempts_run_chunk_attempt",
        "CREATE INDEX idx_chunk_transcript_attempts_run_chunk_attempt ON chunk_transcript_attempts(transcription_run_id, chunk_id, attempt_number)",
    )
    _add_column_if_missing(database, "transcript_segments", "excluded_from_review", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(database, "transcript_segments", "exclusion_reason", "TEXT NULL")
    _add_column_if_missing(database, "meetings", "attendees_json", "TEXT NOT NULL DEFAULT '[]'")
    _add_column_if_missing(database, "meetings", "circulation_json", "TEXT NOT NULL DEFAULT '[]'")
    _create_index_if_missing(
        database,
        "idx_transcript_segments_review_visibility",
        "CREATE INDEX idx_transcript_segments_review_visibility ON transcript_segments(transcription_run_id, source_type, excluded_from_review, segment_index)",
    )
    database.execute(
        """
        INSERT INTO chunk_transcript_attempts (
          meeting_id, chunk_id, transcription_run_id, chunk_transcript_id, attempt_number,
          retried_from_attempt_id, engine, engine_model, status, transcript_text, raw_response_json,
          average_confidence, started_at, completed_at, error_message, request_config_json, created_at
        )
        SELECT
          ct.meeting_id,
          ct.chunk_id,
          ct.transcription_run_id,
          ct.id,
          1,
          NULL,
          ct.engine,
          ct.engine_model,
          ct.status,
          ct.transcript_text,
          ct.raw_response_json,
          ct.average_confidence,
          ct.started_at,
          ct.completed_at,
          ct.error_message,
          ct.request_config_json,
          COALESCE(ct.completed_at, ct.started_at, ?)
        FROM chunk_transcripts ct
        WHERE NOT EXISTS (
          SELECT 1
          FROM chunk_transcript_attempts attempt
          WHERE attempt.transcription_run_id = ct.transcription_run_id
            AND attempt.chunk_id = ct.chunk_id
        )
        """,
        (utc_now_iso(),),
    )
    database.execute(
        """
        DELETE FROM artifacts
        WHERE id NOT IN (
          SELECT MAX(id)
          FROM artifacts
          GROUP BY
            meeting_id,
            COALESCE(preprocessing_run_id, -1),
            COALESCE(transcription_run_id, -1),
            COALESCE(extraction_run_id, -1),
            artifact_type,
            role,
            path
        )
        """
    )
    database.execute(
        """
        CREATE TABLE IF NOT EXISTS export_runs (
          id INTEGER PRIMARY KEY,
          meeting_id INTEGER NOT NULL,
          export_profile TEXT NOT NULL,
          format TEXT NOT NULL,
          options_json TEXT NOT NULL,
          file_path TEXT NOT NULL,
          status TEXT NOT NULL,
          started_at TEXT NULL,
          completed_at TEXT NULL,
          error_message TEXT NULL,
          created_at TEXT NOT NULL,
          FOREIGN KEY(meeting_id) REFERENCES meetings(id)
        )
        """
    )
    _create_index_if_missing(
        database,
        "idx_export_runs_meeting_created",
        "CREATE INDEX idx_export_runs_meeting_created ON export_runs(meeting_id, created_at)",
    )


def _add_column_if_missing(database: Database, table: str, column: str, definition: str) -> None:
    columns = database.fetch_all(f"PRAGMA table_info({table})")
    if any(item["name"] == column for item in columns):
        return
    database.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _create_index_if_missing(database: Database, index_name: str, sql: str) -> None:
    existing = database.fetch_one(
        "SELECT name FROM sqlite_master WHERE type = 'index' AND name = ?",
        (index_name,),
    )
    if not existing:
        database.execute(sql)
