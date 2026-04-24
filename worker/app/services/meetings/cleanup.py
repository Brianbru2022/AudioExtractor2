from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from app.core.config import load_config
from app.db.database import Database
from app.repositories.extraction import (
    ExtractionEntityRepository,
    ExtractionEvidenceRepository,
    ExtractionRunRepository,
    ExtractionSummaryRepository,
)
from app.repositories.exports import ExportRunRepository
from app.repositories.meetings import ArtifactRepository, ChunkRepository, MeetingRepository, RunRepository, SourceFileRepository
from app.repositories.transcription import (
    ChunkTranscriptAttemptRepository,
    ChunkTranscriptRepository,
    JobRunRepository,
    TranscriptSegmentRepository,
    TranscriptWordRepository,
    TranscriptionRunRepository,
)


class MeetingCleanupService:
    def __init__(
        self,
        *,
        database: Database,
        meeting_repository: MeetingRepository,
        source_file_repository: SourceFileRepository,
        run_repository: RunRepository,
        chunk_repository: ChunkRepository,
        artifact_repository: ArtifactRepository,
        job_run_repository: JobRunRepository,
        transcription_run_repository: TranscriptionRunRepository,
        chunk_transcript_repository: ChunkTranscriptRepository,
        chunk_transcript_attempt_repository: ChunkTranscriptAttemptRepository,
        transcript_segment_repository: TranscriptSegmentRepository,
        transcript_word_repository: TranscriptWordRepository,
        extraction_run_repository: ExtractionRunRepository,
        extracted_action_repository: ExtractionEntityRepository,
        extracted_decision_repository: ExtractionEntityRepository,
        extracted_risk_repository: ExtractionEntityRepository,
        extracted_question_repository: ExtractionEntityRepository,
        extracted_topic_repository: ExtractionEntityRepository,
        extraction_evidence_repository: ExtractionEvidenceRepository,
        extraction_summary_repository: ExtractionSummaryRepository,
        export_run_repository: ExportRunRepository,
    ) -> None:
        self.database = database
        self.meeting_repository = meeting_repository
        self.source_file_repository = source_file_repository
        self.run_repository = run_repository
        self.chunk_repository = chunk_repository
        self.artifact_repository = artifact_repository
        self.job_run_repository = job_run_repository
        self.transcription_run_repository = transcription_run_repository
        self.chunk_transcript_repository = chunk_transcript_repository
        self.chunk_transcript_attempt_repository = chunk_transcript_attempt_repository
        self.transcript_segment_repository = transcript_segment_repository
        self.transcript_word_repository = transcript_word_repository
        self.extraction_run_repository = extraction_run_repository
        self.extracted_action_repository = extracted_action_repository
        self.extracted_decision_repository = extracted_decision_repository
        self.extracted_risk_repository = extracted_risk_repository
        self.extracted_question_repository = extracted_question_repository
        self.extracted_topic_repository = extracted_topic_repository
        self.extraction_evidence_repository = extraction_evidence_repository
        self.extraction_summary_repository = extraction_summary_repository
        self.export_run_repository = export_run_repository

    def delete_meeting(self, meeting_id: int) -> dict[str, Any]:
        meeting = self.meeting_repository.get(meeting_id)
        if not meeting:
            raise ValueError("Meeting not found")
        if self.job_run_repository.has_running_for_meeting(meeting_id):
            raise ValueError("Cannot delete a meeting while a job is still running for it")

        source_files = self.source_file_repository.list_for_meeting(meeting_id)
        chunks = self.chunk_repository.list_for_meeting(meeting_id)
        artifacts = self.artifact_repository.list_for_meeting(meeting_id)
        export_runs = self.export_run_repository.list_for_meeting(meeting_id)
        extraction_runs = self.extraction_run_repository.list_for_meeting(meeting_id)
        paths_to_remove, directories_to_remove, preserved_reference_original = self._collect_paths(
            meeting_id=meeting_id,
            source_files=source_files,
            chunks=chunks,
            artifacts=artifacts,
            export_runs=export_runs,
        )

        extraction_run_ids = [int(run["id"]) for run in extraction_runs]
        with self.database.transaction() as connection:
            self.extraction_evidence_repository.delete_for_run_ids(extraction_run_ids, connection=connection)
            self.extraction_summary_repository.delete_for_meeting(meeting_id, connection=connection)
            self.extracted_action_repository.delete_for_meeting(meeting_id, connection=connection)
            self.extracted_decision_repository.delete_for_meeting(meeting_id, connection=connection)
            self.extracted_risk_repository.delete_for_meeting(meeting_id, connection=connection)
            self.extracted_question_repository.delete_for_meeting(meeting_id, connection=connection)
            self.extracted_topic_repository.delete_for_meeting(meeting_id, connection=connection)
            self.export_run_repository.delete_for_meeting(meeting_id, connection=connection)
            self.chunk_transcript_attempt_repository.delete_for_meeting(meeting_id, connection=connection)
            self.transcript_word_repository.delete_for_meeting(meeting_id, connection=connection)
            self.transcript_segment_repository.delete_for_meeting(meeting_id, connection=connection)
            self.chunk_transcript_repository.delete_for_meeting(meeting_id, connection=connection)
            self.artifact_repository.delete_for_meeting(meeting_id, connection=connection)
            self.extraction_run_repository.delete_for_meeting(meeting_id, connection=connection)
            self.transcription_run_repository.delete_for_meeting(meeting_id, connection=connection)
            self.chunk_repository.delete_for_meeting(meeting_id, connection=connection)
            self.run_repository.delete_for_meeting(meeting_id, connection=connection)
            self.source_file_repository.delete_for_meeting(meeting_id, connection=connection)
            self.job_run_repository.delete_for_meeting(meeting_id, connection=connection)
            self.meeting_repository.delete(meeting_id, connection=connection)

        deleted_local_files = self._remove_paths(paths_to_remove, directories_to_remove)
        return {
            "status": "deleted",
            "meeting_id": meeting_id,
            "deleted_local_files": deleted_local_files,
            "preserved_reference_original": preserved_reference_original,
        }

    def _collect_paths(
        self,
        *,
        meeting_id: int,
        source_files: list[dict[str, Any]],
        chunks: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        export_runs: list[dict[str, Any]],
    ) -> tuple[set[Path], set[Path], bool]:
        current_config = load_config()
        paths_to_remove: set[Path] = set()
        directories_to_remove: set[Path] = set()
        preserved_reference_original = False

        for source_file in source_files:
            if source_file.get("import_mode") == "reference":
                preserved_reference_original = True
            managed_copy_path = source_file.get("managed_copy_path")
            normalized_audio_path = source_file.get("normalized_audio_path")
            if managed_copy_path:
                self._add_storage_path(paths_to_remove, managed_copy_path, storage_root=current_config.storage_root)
            if normalized_audio_path:
                self._add_storage_path(paths_to_remove, normalized_audio_path, storage_root=current_config.storage_root)

        for chunk in chunks:
            self._add_storage_path(paths_to_remove, chunk.get("file_path"), storage_root=current_config.storage_root)

        for artifact in artifacts:
            self._add_storage_path(paths_to_remove, artifact.get("path"), storage_root=current_config.storage_root)

        for export_run in export_runs:
            self._add_storage_path(paths_to_remove, export_run.get("file_path"), storage_root=current_config.storage_root)

        for root in [
            current_config.normalized_root / f"meeting_{meeting_id}",
            current_config.chunks_root / f"meeting_{meeting_id}",
            current_config.artifacts_root / f"meeting_{meeting_id}",
            current_config.managed_root / f"meeting_{meeting_id}",
            current_config.logs_root / f"meeting_{meeting_id}",
            current_config.exports_root / f"meeting_{meeting_id}",
        ]:
            directories_to_remove.add(root)

        return paths_to_remove, directories_to_remove, preserved_reference_original

    def _remove_paths(self, paths_to_remove: set[Path], directories_to_remove: set[Path]) -> int:
        deleted_count = 0
        for path in sorted(paths_to_remove, key=lambda item: len(str(item)), reverse=True):
            try:
                if path.exists() and path.is_file():
                    path.unlink()
                    deleted_count += 1
            except FileNotFoundError:
                continue

        for directory in sorted(directories_to_remove, key=lambda item: len(str(item)), reverse=True):
            if directory.exists():
                shutil.rmtree(directory, ignore_errors=True)
                deleted_count += 1
        return deleted_count

    @staticmethod
    def _add_storage_path(paths_to_remove: set[Path], raw_path: str | None, *, storage_root: Path) -> None:
        if not raw_path:
            return
        path = Path(raw_path)
        try:
            path.relative_to(storage_root)
        except ValueError:
            return
        paths_to_remove.add(path)
