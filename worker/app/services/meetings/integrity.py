from __future__ import annotations

from pathlib import Path
from typing import Any

from app.repositories.extraction import ExtractionRunRepository
from app.repositories.meetings import ArtifactRepository, ChunkRepository, MeetingRepository, RunRepository, SourceFileRepository
from app.repositories.transcription import JobRunRepository, TranscriptionRunRepository


class MeetingIntegrityService:
    def __init__(
        self,
        *,
        meeting_repository: MeetingRepository,
        source_file_repository: SourceFileRepository,
        run_repository: RunRepository,
        chunk_repository: ChunkRepository,
        artifact_repository: ArtifactRepository,
        job_run_repository: JobRunRepository,
        transcription_run_repository: TranscriptionRunRepository,
        extraction_run_repository: ExtractionRunRepository,
    ) -> None:
        self.meeting_repository = meeting_repository
        self.source_file_repository = source_file_repository
        self.run_repository = run_repository
        self.chunk_repository = chunk_repository
        self.artifact_repository = artifact_repository
        self.job_run_repository = job_run_repository
        self.transcription_run_repository = transcription_run_repository
        self.extraction_run_repository = extraction_run_repository

    def summarize(self) -> dict[str, Any]:
        database = self.meeting_repository.database
        orphan_meeting_count = database.fetch_one(
            """
            SELECT COUNT(*) AS count
            FROM meetings m
            LEFT JOIN source_files s ON s.meeting_id = m.id
            WHERE s.id IS NULL
            """
        )["count"]
        source_files = self.source_file_repository.list_all()
        missing_source_path_count = sum(1 for source_file in source_files if self._source_path_issue(source_file))
        missing_chunk_file_count = sum(
            1
            for chunk in self.chunk_repository.list_all()
            if chunk.get("file_path") and not Path(chunk["file_path"]).exists()
        )
        stale_job_link_count = self._count_detached_jobs()
        meeting_count = database.fetch_one("SELECT COUNT(*) AS count FROM meetings")["count"]
        return {
            "meeting_count": meeting_count,
            "orphan_meeting_count": orphan_meeting_count,
            "missing_source_path_count": missing_source_path_count,
            "missing_chunk_file_count": missing_chunk_file_count,
            "stale_job_link_count": stale_job_link_count,
        }

    def list_issues_for_meeting(self, meeting_id: int, *, meeting: dict[str, Any] | None = None) -> list[str]:
        meeting_record = meeting or self.meeting_repository.get(meeting_id)
        if not meeting_record:
            return ["Meeting record is missing."]

        issues: list[str] = []
        source_file = meeting_record.get("source_file") if isinstance(meeting_record.get("source_file"), dict) else self.source_file_repository.get_for_meeting(meeting_id)
        if not source_file:
            issues.append("Missing source record for this meeting.")
        else:
            source_issue = self._source_path_issue(source_file)
            if source_issue:
                issues.append(source_issue)
        issues.extend(self._detached_job_messages(meeting_id))
        return issues

    def detail_issues_for_meeting(self, meeting_id: int, *, meeting: dict[str, Any] | None = None) -> list[str]:
        meeting_record = meeting or self.meeting_repository.get(meeting_id)
        if not meeting_record:
            return ["Meeting record is missing."]

        issues = self.list_issues_for_meeting(meeting_id, meeting=meeting_record)
        source_file = meeting_record.get("source_file") if isinstance(meeting_record.get("source_file"), dict) else self.source_file_repository.get_for_meeting(meeting_id)
        if source_file:
            normalized_audio_path = source_file.get("normalized_audio_path")
            if normalized_audio_path and not Path(normalized_audio_path).exists():
                issues.append(f"Normalized audio artifact missing: {normalized_audio_path}")

        missing_chunk_indices = [
            str(int(chunk["chunk_index"]) + 1)
            for chunk in self.chunk_repository.list_for_meeting(meeting_id)
            if chunk.get("file_path") and not Path(chunk["file_path"]).exists()
        ]
        if missing_chunk_indices:
            preview = ", ".join(missing_chunk_indices[:6])
            if len(missing_chunk_indices) > 6:
                preview = f"{preview}, +{len(missing_chunk_indices) - 6} more"
            issues.append(f"Missing chunk files for chunk(s): {preview}")

        missing_artifact_roles = [
            artifact["role"]
            for artifact in self.artifact_repository.list_for_meeting(meeting_id)
            if artifact.get("path") and not Path(artifact["path"]).exists()
        ]
        if missing_artifact_roles:
            preview = ", ".join(missing_artifact_roles[:4])
            if len(missing_artifact_roles) > 4:
                preview = f"{preview}, +{len(missing_artifact_roles) - 4} more"
            issues.append(f"Missing artifact files: {preview}")
        return issues

    def _source_path_issue(self, source_file: dict[str, Any]) -> str | None:
        managed_copy_path = source_file.get("managed_copy_path")
        original_path = source_file.get("original_path")
        if managed_copy_path and not Path(managed_copy_path).exists():
            return f"Managed source file missing: {managed_copy_path}"
        if original_path and not Path(original_path).exists():
            return f"Reference source file missing: {original_path}"
        return None

    def _count_detached_jobs(self) -> int:
        detached = 0
        for meeting in self.meeting_repository.list():
            detached += len(self._detached_job_messages(meeting["id"]))
        return detached

    def _detached_job_messages(self, meeting_id: int) -> list[str]:
        messages: list[str] = []
        preprocess_job_ids = {
            int(run["job_run_id"])
            for run in self.run_repository.list_for_meeting(meeting_id)
            if run.get("job_run_id") is not None
        }
        transcription_job_ids = {
            int(run["job_run_id"])
            for run in self.transcription_run_repository.list_for_meeting(meeting_id)
            if run.get("job_run_id") is not None
        }
        extraction_job_ids = {
            int(run["job_run_id"])
            for run in self.extraction_run_repository.list_for_meeting(meeting_id)
            if run.get("job_run_id") is not None
        }
        for job in self.job_run_repository.list_for_meeting(meeting_id):
            job_id = int(job["id"])
            if job["job_type"] == "preprocess" and job_id not in preprocess_job_ids:
                messages.append(f"Detached preprocess job history: queue item {job_id} has no linked preprocessing run.")
            if job["job_type"] == "transcribe" and job_id not in transcription_job_ids:
                messages.append(f"Detached transcription job history: queue item {job_id} has no linked transcription run.")
            if job["job_type"] == "extract" and job_id not in extraction_job_ids:
                messages.append(f"Detached extraction job history: queue item {job_id} has no linked extraction run.")
        return messages
