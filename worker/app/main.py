from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import config
from app.db.database import Database
from app.db.migrations import bootstrap_database
from app.repositories.meetings import (
    ArtifactRepository,
    ChunkRepository,
    MeetingRepository,
    RunRepository,
    SettingsRepository,
    SourceFileRepository,
)
from app.repositories.extraction import (
    ExtractionEntityRepository,
    ExtractionEvidenceRepository,
    ExtractionRunRepository,
    ExtractionSummaryRepository,
)
from app.repositories.exports import ExportRunRepository
from app.repositories.transcription import (
    ChunkTranscriptAttemptRepository,
    ChunkTranscriptRepository,
    JobRunRepository,
    TranscriptSegmentRepository,
    TranscriptWordRepository,
    TranscriptionRunRepository,
)
from app.services.artifacts.service import ArtifactService
from app.services.chunk_planning.service import ChunkPlanningService
from app.services.chunk_writing.service import ChunkWriterService
from app.services.gemini.service import GeminiApiService
from app.services.jobs.service import JobService
from app.services.meetings.cleanup import MeetingCleanupService
from app.services.meetings.integrity import MeetingIntegrityService
from app.services.normalization.service import NormalizationService
from app.services.probing.service import ProbeService
from app.services.settings_backup import SettingsBackupService
from app.services.silence_analysis.service import SilenceAnalysisService
from app.services.transcription.google_adapter import GoogleSpeechV2Adapter
from app.services.transcription.job_service import TranscriptionJobService
from app.services.transcription.settings import TranscriptionSettingsService
from app.services.transcription.stitcher import TranscriptStitcher
from app.services.extraction.service import ExtractionService
from app.services.exports.service import ExportService
from app.utils.files import ensure_directory

ensure_directory(config.db_path.parent)
if config.settings_backup_path.parent != config.workspace_root:
    ensure_directory(config.settings_backup_path.parent)

database = Database(config.db_path)
bootstrap_database(database)

for path in [
    config.storage_root,
    config.artifacts_root,
    config.normalized_root,
    config.chunks_root,
    config.managed_root,
    config.logs_root,
    config.exports_root,
]:
    ensure_directory(path)

meeting_repository = MeetingRepository(database)
source_file_repository = SourceFileRepository(database)
run_repository = RunRepository(database)
chunk_repository = ChunkRepository(database)
artifact_repository = ArtifactRepository(database)
settings_repository = SettingsRepository(database)
settings_backup_service = SettingsBackupService(
    settings_repository=settings_repository,
    backup_path=config.settings_backup_path,
)
settings_backup_service.restore_cloud_settings_if_missing()
job_run_repository = JobRunRepository(database)
transcription_run_repository = TranscriptionRunRepository(database)
chunk_transcript_repository = ChunkTranscriptRepository(database)
chunk_transcript_attempt_repository = ChunkTranscriptAttemptRepository(database)
transcript_segment_repository = TranscriptSegmentRepository(database)
transcript_word_repository = TranscriptWordRepository(database)
extraction_run_repository = ExtractionRunRepository(database)
extracted_action_repository = ExtractionEntityRepository(database, "extracted_actions")
extracted_decision_repository = ExtractionEntityRepository(database, "extracted_decisions")
extracted_risk_repository = ExtractionEntityRepository(database, "extracted_risks")
extracted_question_repository = ExtractionEntityRepository(database, "extracted_questions")
extracted_topic_repository = ExtractionEntityRepository(database, "extracted_topics")
extraction_evidence_repository = ExtractionEvidenceRepository(database)
extraction_summary_repository = ExtractionSummaryRepository(database)
export_run_repository = ExportRunRepository(database)

probe_service = ProbeService()
normalization_service = NormalizationService()
silence_analysis_service = SilenceAnalysisService()
chunk_planning_service = ChunkPlanningService()
chunk_writer_service = ChunkWriterService()
artifact_service = ArtifactService(artifact_repository)
gemini_api_service = GeminiApiService(settings_repository)
transcription_settings_service = TranscriptionSettingsService(settings_repository)
google_speech_adapter = GoogleSpeechV2Adapter()
transcript_stitcher = TranscriptStitcher()
extraction_service = ExtractionService(
    meeting_repository=meeting_repository,
    transcription_run_repository=transcription_run_repository,
    transcript_segment_repository=transcript_segment_repository,
    job_run_repository=job_run_repository,
    extraction_run_repository=extraction_run_repository,
    action_repository=extracted_action_repository,
    decision_repository=extracted_decision_repository,
    risk_repository=extracted_risk_repository,
    question_repository=extracted_question_repository,
    topic_repository=extracted_topic_repository,
    evidence_repository=extraction_evidence_repository,
    summary_repository=extraction_summary_repository,
    artifact_repository=artifact_repository,
    gemini_service=gemini_api_service,
)
export_service = ExportService(
    meeting_repository=meeting_repository,
    source_file_repository=source_file_repository,
    preprocessing_run_repository=run_repository,
    transcription_run_repository=transcription_run_repository,
    transcript_segment_repository=transcript_segment_repository,
    extraction_run_repository=extraction_run_repository,
    action_repository=extracted_action_repository,
    decision_repository=extracted_decision_repository,
    risk_repository=extracted_risk_repository,
    question_repository=extracted_question_repository,
    topic_repository=extracted_topic_repository,
    evidence_repository=extraction_evidence_repository,
    summary_repository=extraction_summary_repository,
    artifact_repository=artifact_repository,
    export_run_repository=export_run_repository,
)
meeting_integrity_service = MeetingIntegrityService(
    meeting_repository=meeting_repository,
    source_file_repository=source_file_repository,
    run_repository=run_repository,
    chunk_repository=chunk_repository,
    artifact_repository=artifact_repository,
    job_run_repository=job_run_repository,
    transcription_run_repository=transcription_run_repository,
    extraction_run_repository=extraction_run_repository,
)
meeting_cleanup_service = MeetingCleanupService(
    database=database,
    meeting_repository=meeting_repository,
    source_file_repository=source_file_repository,
    run_repository=run_repository,
    chunk_repository=chunk_repository,
    artifact_repository=artifact_repository,
    job_run_repository=job_run_repository,
    transcription_run_repository=transcription_run_repository,
    chunk_transcript_repository=chunk_transcript_repository,
    chunk_transcript_attempt_repository=chunk_transcript_attempt_repository,
    transcript_segment_repository=transcript_segment_repository,
    transcript_word_repository=transcript_word_repository,
    extraction_run_repository=extraction_run_repository,
    extracted_action_repository=extracted_action_repository,
    extracted_decision_repository=extracted_decision_repository,
    extracted_risk_repository=extracted_risk_repository,
    extracted_question_repository=extracted_question_repository,
    extracted_topic_repository=extracted_topic_repository,
    extraction_evidence_repository=extraction_evidence_repository,
    extraction_summary_repository=extraction_summary_repository,
    export_run_repository=export_run_repository,
)
job_service = JobService(
    meeting_repository=meeting_repository,
    source_file_repository=source_file_repository,
    run_repository=run_repository,
    job_run_repository=job_run_repository,
    chunk_repository=chunk_repository,
    artifact_repository=artifact_repository,
    probe_service=probe_service,
    normalization_service=normalization_service,
    silence_analysis_service=silence_analysis_service,
    chunk_planning_service=chunk_planning_service,
    chunk_writer_service=chunk_writer_service,
)
transcription_job_service = TranscriptionJobService(
    meeting_repository=meeting_repository,
    run_repository=run_repository,
    chunk_repository=chunk_repository,
    artifact_repository=artifact_repository,
    job_run_repository=job_run_repository,
    transcription_run_repository=transcription_run_repository,
    chunk_transcript_repository=chunk_transcript_repository,
    chunk_transcript_attempt_repository=chunk_transcript_attempt_repository,
    transcript_segment_repository=transcript_segment_repository,
    transcript_word_repository=transcript_word_repository,
    settings_service=transcription_settings_service,
    adapter=google_speech_adapter,
    stitcher=transcript_stitcher,
)

app = FastAPI(title="Audio Extractor 2 Worker", version=config.worker_version)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.state.services = {
    "meeting_repository": meeting_repository,
    "source_file_repository": source_file_repository,
    "run_repository": run_repository,
    "chunk_repository": chunk_repository,
    "artifact_repository": artifact_repository,
    "settings_repository": settings_repository,
    "job_run_repository": job_run_repository,
    "transcription_run_repository": transcription_run_repository,
    "chunk_transcript_repository": chunk_transcript_repository,
    "chunk_transcript_attempt_repository": chunk_transcript_attempt_repository,
    "transcript_segment_repository": transcript_segment_repository,
    "transcript_word_repository": transcript_word_repository,
    "extraction_run_repository": extraction_run_repository,
    "extracted_action_repository": extracted_action_repository,
    "extracted_decision_repository": extracted_decision_repository,
    "extracted_risk_repository": extracted_risk_repository,
    "extracted_question_repository": extracted_question_repository,
    "extracted_topic_repository": extracted_topic_repository,
    "extraction_evidence_repository": extraction_evidence_repository,
    "extraction_summary_repository": extraction_summary_repository,
    "export_run_repository": export_run_repository,
    "probe_service": probe_service,
    "artifact_service": artifact_service,
    "gemini_api_service": gemini_api_service,
    "job_service": job_service,
    "meeting_cleanup_service": meeting_cleanup_service,
    "meeting_integrity_service": meeting_integrity_service,
    "settings_backup_service": settings_backup_service,
    "transcription_settings_service": transcription_settings_service,
    "transcription_job_service": transcription_job_service,
    "extraction_service": extraction_service,
    "export_service": export_service,
}
app.include_router(router, prefix="/api/v1")
