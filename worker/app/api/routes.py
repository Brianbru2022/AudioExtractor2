from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from app.core.config import config
from app.schemas.api import (
    CreateExportRequest,
    ImportMeetingRequest,
    InspectImportSourceRequest,
    RetryTranscriptionRequest,
    UpdateTranscriptSegmentsRequest,
    UpdateInsightRequest,
    UpdateSettingRequest,
    UpdateSpeakerRequest,
)
from app.services.exports.models import ExportOptions
from app.services.jobs.service import import_source_into_mode
from app.utils.files import sha256_for_file


SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".flac", ".mp4", ".mov", ".mkv"}

router = APIRouter()


def _serialize_run(services, run: dict | None) -> dict | None:
    if not run:
        return None
    run["log_json"] = json.loads(run["log_json"]) if run.get("log_json") else []
    run["silence_map_json"] = json.loads(run["silence_map_json"]) if run.get("silence_map_json") else None
    run["chunking_strategy_json"] = json.loads(run["chunking_strategy_json"]) if run.get("chunking_strategy_json") else {}
    run["waveform_summary_json"] = json.loads(run["waveform_summary_json"]) if run.get("waveform_summary_json") else None
    run["artifacts"] = services["artifact_repository"].list_for_run(run["id"])
    return run


def _serialize_transcription_run(services, run: dict | None) -> dict | None:
    if not run:
        return None
    run["artifacts"] = services["artifact_repository"].list_for_transcription_run(run["id"])
    run["chunk_transcripts"] = services["chunk_transcript_repository"].list_for_run(run["id"])
    attempts = services["chunk_transcript_attempt_repository"].list_for_run(run["id"])
    attempts_by_chunk: dict[int, list[dict]] = {}
    for attempt in attempts:
        attempts_by_chunk.setdefault(int(attempt["chunk_id"]), []).append(attempt)
    failed_chunk_ids: list[int] = []
    for chunk_transcript in run["chunk_transcripts"]:
        chunk_attempts = attempts_by_chunk.get(int(chunk_transcript["chunk_id"]), [])
        chunk_transcript["attempts"] = chunk_attempts
        chunk_transcript["attempt_count"] = len(chunk_attempts)
        chunk_transcript["retryable"] = chunk_transcript["status"] == "failed"
        if chunk_transcript["status"] == "failed":
            failed_chunk_ids.append(int(chunk_transcript["chunk_id"]))
    run["merged_segments"] = services["transcript_segment_repository"].list_for_run(run["id"], "merged")
    run["retryable_chunk_ids"] = failed_chunk_ids
    run["has_partial_transcript"] = bool(run["failed_chunk_count"])
    run["transcript_completeness"] = "partial" if run["failed_chunk_count"] else "complete"
    return run


def _serialize_extraction_run(services, run: dict | None) -> dict | None:
    if not run:
        return None
    run["artifacts"] = services["artifact_repository"].list_for_extraction_run(run["id"])
    run["summary"] = services["extraction_summary_repository"].get_for_run(run["id"])
    run["actions"] = services["extraction_service"].build_insights_payload(run["meeting_id"])["actions"] if run else []
    return run


def _serialize_meeting_summary(services, meeting: dict) -> dict:
    summary = dict(meeting)
    summary["source_file"] = summary.get("source_file") or services["source_file_repository"].get_for_meeting(summary["id"])
    summary["chunk_count"] = summary.get("chunk_count")
    if summary["chunk_count"] is None:
        summary["chunk_count"] = len(services["chunk_repository"].list_for_meeting(summary["id"]))
    summary["latest_run"] = summary.get("latest_run")
    if summary["latest_run"] is None:
        summary["latest_run"] = services["run_repository"].get_latest_for_meeting(summary["id"])
    summary["integrity_issues"] = services["meeting_integrity_service"].list_issues_for_meeting(
        summary["id"],
        meeting=summary,
    )
    return summary


def _serialize_meeting_detail(services, meeting_id: int, meeting: dict) -> dict:
    detail = _serialize_meeting_summary(services, meeting)
    detail["integrity_issues"] = services["meeting_integrity_service"].detail_issues_for_meeting(
        meeting_id,
        meeting=detail,
    )
    latest_run = services["run_repository"].get_latest_for_meeting(meeting_id)
    detail["latest_run"] = latest_run
    detail["latest_run_detail"] = _serialize_run(services, latest_run)
    detail["chunks"] = services["chunk_repository"].list_for_meeting(meeting_id)
    detail["artifacts"] = services["artifact_repository"].list_for_meeting(meeting_id)
    latest_transcription_run = services["transcription_run_repository"].get_latest_for_meeting(meeting_id)
    detail["latest_transcription_run"] = _serialize_transcription_run(services, latest_transcription_run)
    latest_extraction_run = services["extraction_run_repository"].get_latest_for_meeting(meeting_id)
    detail["latest_extraction_run"] = _serialize_extraction_run(services, latest_extraction_run)
    return detail


def _services(request: Request):
    return request.app.state.services


@router.get("/health")
def health(request: Request):
    services = _services(request)
    google_runtime: dict[str, object]
    try:
        settings_service = services["transcription_settings_service"]
        settings = settings_service.get()
        adapter = services["transcription_job_service"].adapter
        runtime_packages = adapter.validate_runtime(settings)
        google_runtime = {"speech_dependencies_available": True, "packages": runtime_packages}
        try:
            settings_service.validate(settings)
            preflight = adapter.validate_preflight(settings, validate_bucket_write=False)
            google_runtime.update(
                {
                    "speech_preflight_available": True,
                    "speech_preflight": preflight,
                }
            )
        except Exception as preflight_exc:  # noqa: BLE001
            google_runtime.update(
                {
                    "speech_preflight_available": False,
                    "speech_preflight_error": str(preflight_exc),
                    "speech_preflight_settings": {
                        "auth_mode": settings.auth_mode,
                        "project_id": settings.project_id,
                        "recognizer_location": settings.recognizer_location,
                        "staging_bucket": settings.staging_bucket,
                        "model": settings.model,
                    },
                }
            )
    except Exception as exc:  # noqa: BLE001
        google_runtime = {
            "speech_dependencies_available": False,
            "speech_runtime_error": str(exc),
        }
    return {
        "status": "ok",
        "version": config.worker_version,
        "ffmpeg_available": True,
        "ffprobe_available": True,
        "integrity_summary": services["meeting_integrity_service"].summarize(),
        **google_runtime,
    }


@router.post("/meetings/import")
def import_meeting(payload: ImportMeetingRequest, request: Request):
    services = _services(request)
    source_path = Path(payload.source_path)
    if not source_path.exists() or not source_path.is_file():
        raise HTTPException(status_code=400, detail="Source file does not exist")

    if source_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    probe = services["probe_service"].probe(source_path)
    detected_meeting_date = datetime.fromtimestamp(source_path.stat().st_ctime).date().isoformat()
    title = payload.title or source_path.stem.replace("_", " ").replace("-", " ").strip().title()
    meeting_id = services["meeting_repository"].create(
        title,
        payload.meeting_date or detected_meeting_date,
        payload.project,
        payload.notes,
        payload.attendees,
        payload.circulation,
    )
    managed_copy = import_source_into_mode(source_path, meeting_id, payload.import_mode)

    source_sha = sha256_for_file(source_path)
    services["source_file_repository"].create(
        {
            "meeting_id": meeting_id,
            "import_mode": payload.import_mode,
            "original_path": str(source_path),
            "managed_copy_path": str(managed_copy) if managed_copy else None,
            "normalized_audio_path": None,
            "file_name": source_path.name,
            "extension": source_path.suffix.lower(),
            "mime_type": probe.mime_type,
            "media_type": probe.media_type,
            "size_bytes": probe.size_bytes,
            "sha256": source_sha,
            "duration_ms": probe.duration_ms,
            "sample_rate": probe.sample_rate,
            "channels": probe.channels,
        }
    )

    if managed_copy:
        services["artifact_service"].record_file_artifact(
            meeting_id=meeting_id,
            preprocessing_run_id=None,
            artifact_type="source",
            role="managed copy",
            path=managed_copy,
            metadata={"import_mode": payload.import_mode},
        )

    services["meeting_repository"].update_status(meeting_id, "imported")
    meetings = services["meeting_repository"].list()
    meeting = next((entry for entry in meetings if entry["id"] == meeting_id), None)
    return {"meeting": _serialize_meeting_summary(services, meeting)}


@router.post("/imports/inspect")
def inspect_import_source(payload: InspectImportSourceRequest, request: Request):
    services = _services(request)
    source_path = Path(payload.source_path)
    if not source_path.exists() or not source_path.is_file():
        raise HTTPException(status_code=400, detail="Source file does not exist")

    if source_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Unsupported file type")

    probe = services["probe_service"].probe(source_path)
    created_at = datetime.fromtimestamp(source_path.stat().st_ctime)
    return {
        "source_path": str(source_path),
        "file_name": source_path.name,
        "meeting_title": source_path.stem.replace("_", " ").replace("-", " ").strip().title(),
        "meeting_date": created_at.date().isoformat(),
        "created_at": created_at.isoformat(),
        "duration_ms": probe.duration_ms,
        "size_bytes": probe.size_bytes,
        "media_type": probe.media_type,
    }


@router.get("/meetings")
def list_meetings(request: Request):
    services = _services(request)
    return [_serialize_meeting_summary(services, meeting) for meeting in services["meeting_repository"].list()]


@router.get("/meetings/{meeting_id}")
def get_meeting(meeting_id: int, request: Request):
    services = _services(request)
    meeting = services["meeting_repository"].get(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return _serialize_meeting_detail(services, meeting_id, meeting)


@router.delete("/meetings/{meeting_id}")
def delete_meeting(meeting_id: int, request: Request):
    services = _services(request)
    try:
        return services["meeting_cleanup_service"].delete_meeting(meeting_id)
    except ValueError as exc:
        if str(exc) == "Meeting not found":
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/meetings/{meeting_id}/preprocess")
def preprocess_meeting(meeting_id: int, request: Request):
    services = _services(request)
    meeting = services["meeting_repository"].get(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")

    source_file = services["source_file_repository"].get_for_meeting(meeting_id)
    if not source_file:
        raise HTTPException(status_code=400, detail="Meeting has no source file record. Delete the orphaned meeting or re-import the source.")

    source_path = Path(source_file["managed_copy_path"] or source_file["original_path"])
    if not source_path.exists():
        mode = source_file["import_mode"]
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start preprocessing because the {mode} source is missing: {source_path}",
        )

    run_id = services["job_service"].enqueue(meeting_id)
    return {"run_id": run_id, "status": "queued", "stage": "queued"}


@router.get("/meetings/{meeting_id}/preprocessing")
def get_latest_preprocessing(meeting_id: int, request: Request):
    services = _services(request)
    run = services["run_repository"].get_latest_for_meeting(meeting_id)
    return _serialize_run(services, run)


@router.get("/meetings/{meeting_id}/chunks")
def list_chunks(meeting_id: int, request: Request):
    services = _services(request)
    latest_run = services["run_repository"].get_latest_for_meeting(meeting_id)
    return services["chunk_repository"].list_for_run(int(latest_run["id"])) if latest_run else []


@router.get("/meetings/{meeting_id}/artifacts")
def list_artifacts(meeting_id: int, request: Request):
    services = _services(request)
    return services["artifact_repository"].list_for_meeting(meeting_id)


@router.get("/jobs")
def list_jobs(request: Request):
    services = _services(request)
    return services["job_run_repository"].list_all()


@router.get("/jobs/{run_id}")
def get_job(run_id: int, request: Request):
    services = _services(request)
    job = services["job_run_repository"].get(run_id)
    if not job:
        raise HTTPException(status_code=404, detail="Run not found")
    if job["job_type"] == "preprocess":
        preprocess = services["run_repository"].get_latest_for_meeting(job["meeting_id"])
        if preprocess and preprocess.get("job_run_id") == run_id:
            job["detail"] = _serialize_run(services, preprocess)
    if job["job_type"] == "transcribe":
        transcription = services["transcription_run_repository"].get_latest_for_meeting(job["meeting_id"])
        if transcription and transcription.get("job_run_id") == run_id:
            job["detail"] = _serialize_transcription_run(services, transcription)
    if job["job_type"] == "extract":
        extraction = services["extraction_run_repository"].get_latest_for_meeting(job["meeting_id"])
        if extraction and extraction.get("job_run_id") == run_id:
            job["detail"] = _serialize_extraction_run(services, extraction)
    return job


@router.delete("/jobs/{run_id}")
def delete_job(run_id: int, request: Request):
    services = _services(request)
    job = services["job_run_repository"].get(run_id)
    if not job:
        raise HTTPException(status_code=404, detail="Run not found")
    if job["status"] == "running":
        raise HTTPException(status_code=400, detail="Running jobs cannot be deleted from the queue")
    services["job_run_repository"].delete(run_id)
    return {"status": "deleted", "run_id": run_id}


@router.post("/meetings/{meeting_id}/transcribe")
def transcribe_meeting(meeting_id: int, request: Request):
    services = _services(request)
    meeting = services["meeting_repository"].get(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    try:
        return services["transcription_job_service"].enqueue(meeting_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/transcription-runs/{run_id}/retry-failed")
def retry_failed_transcription_chunks(run_id: int, payload: RetryTranscriptionRequest, request: Request):
    services = _services(request)
    try:
        return services["transcription_job_service"].retry_failed_chunks(
            run_id,
            chunk_ids=payload.chunk_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/meetings/{meeting_id}/transcription")
def get_latest_transcription(meeting_id: int, request: Request):
    services = _services(request)
    run = services["transcription_run_repository"].get_latest_for_meeting(meeting_id)
    return _serialize_transcription_run(services, run)


@router.get("/meetings/{meeting_id}/transcript")
def get_meeting_transcript(meeting_id: int, request: Request):
    services = _services(request)
    run = services["transcription_run_repository"].get_latest_for_meeting(meeting_id)
    if not run:
        raise HTTPException(status_code=404, detail="Transcript not found")
    merged_segments = services["transcript_segment_repository"].list_for_run(run["id"], "merged", include_excluded=True)
    words = services["transcript_word_repository"].list_for_run(run["id"])
    included_segments = [segment for segment in merged_segments if not segment.get("excluded_from_review")]
    return {
        "meeting_id": meeting_id,
        "transcription_run": _serialize_transcription_run(services, run),
        "segments": merged_segments,
        "words": words,
        "summary": {
            "segment_count": len(merged_segments),
            "included_segment_count": len(included_segments),
            "excluded_segment_count": len(merged_segments) - len(included_segments),
            "word_count": len(words),
            "speaker_labels": sorted({segment["speaker_label"] for segment in included_segments if segment.get("speaker_label")}),
            "average_confidence": run.get("average_confidence"),
        },
    }


@router.patch("/meetings/{meeting_id}/speakers/{speaker_label}")
def assign_transcript_speaker_name(meeting_id: int, speaker_label: str, payload: UpdateSpeakerRequest, request: Request):
    services = _services(request)
    meeting = services["meeting_repository"].get(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    run = services["transcription_run_repository"].get_latest_for_meeting(meeting_id)
    if not run:
        raise HTTPException(status_code=404, detail="Transcription run not found")
    updated_count = services["transcript_segment_repository"].assign_speaker_name(
        int(run["id"]),
        speaker_label,
        payload.speaker_name,
    )
    if updated_count == 0:
        raise HTTPException(status_code=404, detail=f"Speaker label not found: {speaker_label}")
    return {
        "meeting_id": meeting_id,
        "transcription_run_id": int(run["id"]),
        "speaker_label": speaker_label,
        "speaker_name": payload.speaker_name.strip() if isinstance(payload.speaker_name, str) and payload.speaker_name.strip() else None,
        "updated_segments": updated_count,
    }


@router.patch("/meetings/{meeting_id}/transcript-segments")
def update_transcript_segments_review_state(meeting_id: int, payload: UpdateTranscriptSegmentsRequest, request: Request):
    services = _services(request)
    meeting = services["meeting_repository"].get(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    run = services["transcription_run_repository"].get_latest_for_meeting(meeting_id)
    if not run:
        raise HTTPException(status_code=404, detail="Transcription run not found")
    segment_ids = sorted({int(segment_id) for segment_id in payload.segment_ids if int(segment_id) > 0})
    if not segment_ids:
        raise HTTPException(status_code=400, detail="At least one transcript segment id is required")
    updated_count = services["transcript_segment_repository"].update_review_exclusions(
        int(run["id"]),
        segment_ids,
        excluded_from_review=payload.excluded_from_review,
        exclusion_reason=payload.exclusion_reason,
    )
    return {
        "meeting_id": meeting_id,
        "transcription_run_id": int(run["id"]),
        "updated_segments": updated_count,
        "excluded_from_review": payload.excluded_from_review,
        "exclusion_reason": payload.exclusion_reason.strip() if isinstance(payload.exclusion_reason, str) and payload.exclusion_reason.strip() else None,
    }


@router.get("/transcription-runs")
def list_transcription_runs(request: Request):
    services = _services(request)
    runs = services["transcription_run_repository"].list_all()
    return [_serialize_transcription_run(services, run) for run in runs]


@router.get("/transcription-runs/{run_id}")
def get_transcription_run(run_id: int, request: Request):
    services = _services(request)
    run = services["transcription_run_repository"].get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Transcription run not found")
    return _serialize_transcription_run(services, run)


@router.post("/meetings/{meeting_id}/extract")
def extract_meeting(meeting_id: int, request: Request):
    services = _services(request)
    meeting = services["meeting_repository"].get(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    try:
        return services["extraction_service"].enqueue(meeting_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/meetings/{meeting_id}/extraction")
def get_latest_extraction(meeting_id: int, request: Request):
    services = _services(request)
    run = services["extraction_run_repository"].get_latest_for_meeting(meeting_id)
    if not run:
        return None
    payload = services["extraction_service"].build_insights_payload(meeting_id)
    return {"run": _serialize_extraction_run(services, run), "insights": payload}


@router.get("/meetings/{meeting_id}/insights")
def get_meeting_insights(meeting_id: int, request: Request):
    services = _services(request)
    payload = services["extraction_service"].build_insights_payload(meeting_id)
    if not payload:
        raise HTTPException(status_code=404, detail="Insights not found")
    payload["run"] = _serialize_extraction_run(services, payload["run"])
    return payload


@router.post("/meetings/{meeting_id}/exports")
def create_export(meeting_id: int, payload: CreateExportRequest, request: Request):
    services = _services(request)
    meeting = services["meeting_repository"].get(meeting_id)
    if not meeting:
        raise HTTPException(status_code=404, detail="Meeting not found")
    try:
        return services["export_service"].create_export(
            meeting_id=meeting_id,
            export_profile=payload.export_profile,
            format=payload.format,
            options=ExportOptions(
                reviewed_only=payload.reviewed_only,
                include_evidence_appendix=payload.include_evidence_appendix,
                include_transcript_appendix=payload.include_transcript_appendix,
                include_confidence_flags=payload.include_confidence_flags,
            ),
            output_directory=payload.output_directory,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/meetings/{meeting_id}/exports")
def list_exports(meeting_id: int, request: Request):
    services = _services(request)
    return services["export_service"].list_exports(meeting_id)


@router.get("/export-runs/{export_run_id}")
def get_export_run(export_run_id: int, request: Request):
    services = _services(request)
    export_run = services["export_service"].get_export(export_run_id)
    if not export_run:
        raise HTTPException(status_code=404, detail="Export run not found")
    return export_run


@router.post("/export-runs/{export_run_id}/open-folder")
def open_export_folder(export_run_id: int, request: Request):
    services = _services(request)
    try:
        return services["export_service"].open_export_folder(export_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/settings")
def list_settings(request: Request):
    services = _services(request)
    return services["settings_repository"].list()


@router.put("/settings/{key}")
def update_setting(key: str, payload: UpdateSettingRequest, request: Request):
    services = _services(request)
    return services["settings_backup_service"].upsert(key, payload.value_json)


@router.patch("/insights/actions/{item_id}")
def patch_action(item_id: int, payload: UpdateInsightRequest, request: Request):
    return _patch_insight(_services(request)["extracted_action_repository"], item_id, payload)


@router.patch("/insights/decisions/{item_id}")
def patch_decision(item_id: int, payload: UpdateInsightRequest, request: Request):
    return _patch_insight(_services(request)["extracted_decision_repository"], item_id, payload)


@router.patch("/insights/risks/{item_id}")
def patch_risk(item_id: int, payload: UpdateInsightRequest, request: Request):
    return _patch_insight(_services(request)["extracted_risk_repository"], item_id, payload)


@router.patch("/insights/questions/{item_id}")
def patch_question(item_id: int, payload: UpdateInsightRequest, request: Request):
    return _patch_insight(_services(request)["extracted_question_repository"], item_id, payload)


@router.patch("/insights/topics/{item_id}")
def patch_topic(item_id: int, payload: UpdateInsightRequest, request: Request):
    return _patch_insight(_services(request)["extracted_topic_repository"], item_id, payload)


def _patch_insight(repository, item_id: int, payload: UpdateInsightRequest):
    updates = payload.model_dump(exclude_unset=True)
    updated = repository.update(item_id, updates)
    if not updated:
        raise HTTPException(status_code=404, detail="Insight item not found")
    return updated
