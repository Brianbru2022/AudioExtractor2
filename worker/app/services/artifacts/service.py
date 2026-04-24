from __future__ import annotations

from pathlib import Path

from app.models.domain import ArtifactDescriptor
from app.repositories.meetings import ArtifactRepository
from app.utils.files import mime_type_for_path, sha256_for_file


class ArtifactService:
    def __init__(self, artifact_repository: ArtifactRepository) -> None:
        self.artifact_repository = artifact_repository

    def record_file_artifact(
        self,
        *,
        meeting_id: int,
        preprocessing_run_id: int | None,
        transcription_run_id: int | None = None,
        extraction_run_id: int | None = None,
        artifact_type: str,
        role: str,
        path: Path,
        metadata: dict[str, object],
    ) -> None:
        descriptor = ArtifactDescriptor(
            artifact_type=artifact_type,
            role=role,
            path=path,
            mime_type=mime_type_for_path(path),
            sha256=sha256_for_file(path),
            size_bytes=path.stat().st_size,
            metadata=metadata,
        )
        self._persist_descriptor(meeting_id, preprocessing_run_id, transcription_run_id, extraction_run_id, descriptor)

    def record_json_artifact(
        self,
        *,
        meeting_id: int,
        preprocessing_run_id: int | None,
        transcription_run_id: int | None = None,
        extraction_run_id: int | None = None,
        artifact_type: str,
        role: str,
        path: Path,
        metadata: dict[str, object],
    ) -> None:
        descriptor = ArtifactDescriptor(
            artifact_type=artifact_type,
            role=role,
            path=path,
            mime_type="application/json",
            sha256=sha256_for_file(path),
            size_bytes=path.stat().st_size,
            metadata=metadata,
        )
        self._persist_descriptor(meeting_id, preprocessing_run_id, transcription_run_id, extraction_run_id, descriptor)

    def _persist_descriptor(
        self,
        meeting_id: int,
        preprocessing_run_id: int | None,
        transcription_run_id: int | None,
        extraction_run_id: int | None,
        descriptor: ArtifactDescriptor,
    ) -> None:
        self.artifact_repository.upsert(
            {
                "meeting_id": meeting_id,
                "preprocessing_run_id": preprocessing_run_id,
                "transcription_run_id": transcription_run_id,
                "extraction_run_id": extraction_run_id,
                "artifact_type": descriptor.artifact_type,
                "role": descriptor.role,
                "path": str(descriptor.path),
                "mime_type": descriptor.mime_type,
                "sha256": descriptor.sha256,
                "size_bytes": descriptor.size_bytes,
                "metadata_json": descriptor.metadata,
            }
        )
