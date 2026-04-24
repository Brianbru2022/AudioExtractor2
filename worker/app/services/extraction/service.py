from __future__ import annotations

import json
import threading
from collections import defaultdict
from typing import Any

from app.core.config import config
from app.repositories.extraction import (
    ExtractionEntityRepository,
    ExtractionEvidenceRepository,
    ExtractionRunRepository,
    ExtractionSummaryRepository,
)
from app.repositories.meetings import ArtifactRepository, MeetingRepository
from app.repositories.transcription import JobRunRepository, TranscriptSegmentRepository, TranscriptionRunRepository
from app.services.artifacts.service import ArtifactService
from app.services.extraction.context_selection import ExtractionContextSelector
from app.services.extraction.postprocess import assess_review, dedupe_validated_entities, normalize_due_date, normalize_owner
from app.services.gemini.service import GeminiApiService
from app.utils.files import ensure_directory, write_json

PASS1_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "decisions": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "text": {"type": "STRING"},
            "confidence": {"type": "NUMBER"},
            "explicit_or_inferred": {"type": "STRING", "enum": ["explicit", "inferred"]},
            "evidence": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
                "transcript_segment_id": {"type": "INTEGER"},
                "start_ms": {"type": "INTEGER"},
                "end_ms": {"type": "INTEGER"},
                "speaker_label": {"type": "STRING"},
                "quote_snippet": {"type": "STRING"},
                "confidence": {"type": "NUMBER"},
            }, "required": ["transcript_segment_id", "start_ms", "end_ms"]}},
        }, "required": ["text", "confidence", "explicit_or_inferred", "evidence"]}},
        "action_items": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "text": {"type": "STRING"},
            "owner": {"type": "STRING", "nullable": True},
            "due_date": {"type": "STRING", "nullable": True},
            "priority": {"type": "STRING", "nullable": True},
            "confidence": {"type": "NUMBER"},
            "explicit_or_inferred": {"type": "STRING", "enum": ["explicit", "inferred"]},
            "evidence": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
                "transcript_segment_id": {"type": "INTEGER"},
                "start_ms": {"type": "INTEGER"},
                "end_ms": {"type": "INTEGER"},
                "speaker_label": {"type": "STRING"},
                "quote_snippet": {"type": "STRING"},
                "confidence": {"type": "NUMBER"},
            }, "required": ["transcript_segment_id", "start_ms", "end_ms"]}},
        }, "required": ["text", "confidence", "explicit_or_inferred", "evidence"]}},
        "risks_issues": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "text": {"type": "STRING"},
            "confidence": {"type": "NUMBER"},
            "explicit_or_inferred": {"type": "STRING", "enum": ["explicit", "inferred"]},
            "evidence": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
                "transcript_segment_id": {"type": "INTEGER"},
                "start_ms": {"type": "INTEGER"},
                "end_ms": {"type": "INTEGER"},
                "speaker_label": {"type": "STRING"},
                "quote_snippet": {"type": "STRING"},
                "confidence": {"type": "NUMBER"},
            }, "required": ["transcript_segment_id", "start_ms", "end_ms"]}},
        }, "required": ["text", "confidence", "explicit_or_inferred", "evidence"]}},
        "open_questions": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "text": {"type": "STRING"},
            "confidence": {"type": "NUMBER"},
            "explicit_or_inferred": {"type": "STRING", "enum": ["explicit", "inferred"]},
            "evidence": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
                "transcript_segment_id": {"type": "INTEGER"},
                "start_ms": {"type": "INTEGER"},
                "end_ms": {"type": "INTEGER"},
                "speaker_label": {"type": "STRING"},
                "quote_snippet": {"type": "STRING"},
                "confidence": {"type": "NUMBER"},
            }, "required": ["transcript_segment_id", "start_ms", "end_ms"]}},
        }, "required": ["text", "confidence", "explicit_or_inferred", "evidence"]}},
        "key_discussion_topics": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
            "text": {"type": "STRING"},
            "confidence": {"type": "NUMBER"},
            "explicit_or_inferred": {"type": "STRING", "enum": ["explicit", "inferred"]},
            "evidence": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
                "transcript_segment_id": {"type": "INTEGER"},
                "start_ms": {"type": "INTEGER"},
                "end_ms": {"type": "INTEGER"},
                "speaker_label": {"type": "STRING"},
                "quote_snippet": {"type": "STRING"},
                "confidence": {"type": "NUMBER"},
            }, "required": ["transcript_segment_id", "start_ms", "end_ms"]}},
        }, "required": ["text", "confidence", "explicit_or_inferred", "evidence"]}},
    },
    "required": ["decisions", "action_items", "risks_issues", "open_questions", "key_discussion_topics"],
}

PASS2_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "executive_summary": {"type": "STRING"},
        "formal_minutes": {"type": "STRING"},
    },
    "required": ["executive_summary", "formal_minutes"],
}


class ExtractionService:
    def __init__(
        self,
        *,
        meeting_repository: MeetingRepository,
        transcription_run_repository: TranscriptionRunRepository,
        transcript_segment_repository: TranscriptSegmentRepository,
        job_run_repository: JobRunRepository,
        extraction_run_repository: ExtractionRunRepository,
        action_repository: ExtractionEntityRepository,
        decision_repository: ExtractionEntityRepository,
        risk_repository: ExtractionEntityRepository,
        question_repository: ExtractionEntityRepository,
        topic_repository: ExtractionEntityRepository,
        evidence_repository: ExtractionEvidenceRepository,
        summary_repository: ExtractionSummaryRepository,
        artifact_repository: ArtifactRepository,
        gemini_service: GeminiApiService,
    ) -> None:
        self.meeting_repository = meeting_repository
        self.transcription_run_repository = transcription_run_repository
        self.transcript_segment_repository = transcript_segment_repository
        self.job_run_repository = job_run_repository
        self.extraction_run_repository = extraction_run_repository
        self.action_repository = action_repository
        self.decision_repository = decision_repository
        self.risk_repository = risk_repository
        self.question_repository = question_repository
        self.topic_repository = topic_repository
        self.evidence_repository = evidence_repository
        self.summary_repository = summary_repository
        self.artifact_service = ArtifactService(artifact_repository)
        self.gemini_service = gemini_service
        self.context_selector = ExtractionContextSelector()
        self._tasks: dict[int, threading.Thread] = {}

    def enqueue(self, meeting_id: int) -> dict[str, int | str]:
        transcript_run = self.transcription_run_repository.get_latest_for_meeting(meeting_id)
        if not transcript_run or transcript_run["status"] != "completed":
            raise ValueError("Meeting does not have a completed transcription run")

        segments = self.transcript_segment_repository.list_for_run(
            int(transcript_run["id"]),
            "merged",
            include_excluded=False,
        )
        if not segments:
            raise ValueError("Meeting does not have a merged transcript to extract from")
        if not any(str(segment.get("text") or "").strip() for segment in segments):
            raise ValueError("Meeting transcript is empty, so extraction cannot run")

        gemini_settings = self.gemini_service.validate_runtime()
        job_run_id = self.job_run_repository.create(meeting_id, "extract", "Queued for extraction")
        extraction_run_id = self.extraction_run_repository.create(
            meeting_id=meeting_id,
            transcription_run_id=int(transcript_run["id"]),
            job_run_id=job_run_id,
            model=gemini_settings.extraction_model,
            model_version=gemini_settings.extraction_model,
            config_json={
                "extraction_model": gemini_settings.extraction_model,
                "minutes_model": gemini_settings.minutes_model,
                "thinking_level": gemini_settings.thinking_level,
                "max_segments_per_batch": gemini_settings.max_segments_per_batch,
                "max_evidence_items_per_entity": gemini_settings.max_evidence_items_per_entity,
                "context_selection_mode": "retrieval_context_selection",
            },
        )
        self.meeting_repository.update_status(meeting_id, "extracting")
        task = threading.Thread(
            target=self._run_pipeline,
            args=(meeting_id, extraction_run_id, job_run_id, transcript_run, segments),
            daemon=True,
        )
        self._tasks[extraction_run_id] = task
        task.start()
        return {"job_run_id": job_run_id, "extraction_run_id": extraction_run_id, "status": "pending"}

    def _run_pipeline(
        self,
        meeting_id: int,
        extraction_run_id: int,
        job_run_id: int,
        transcript_run: dict[str, Any],
        segments: list[dict[str, Any]],
    ) -> None:
        try:
            settings = self.gemini_service.get_settings()
            low_confidence_threshold = float(getattr(settings, "low_confidence_threshold", 0.7))
            self.extraction_run_repository.mark_running(extraction_run_id)

            self._set_job(job_run_id, "running", "preparing_context", 10, "Selecting transcript evidence context")
            context_windows, context_report = self.context_selector.select(
                segments,
                max_segments_per_window=int(settings.max_segments_per_batch),
            )
            self._write_artifact(
                meeting_id,
                extraction_run_id,
                "context_selection_report.json",
                context_report,
                role="context selection report",
            )

            self._set_job(job_run_id, "running", "extracting_evidence", 28, "Running evidence extraction")
            raw_pass1_payloads: list[dict[str, Any]] = []
            for index, window in enumerate(context_windows):
                response = self.gemini_service.generate_content(
                    prompt=self._build_pass1_prompt(window, window_index=index, total_windows=len(context_windows)),
                    system_instruction=self._pass1_system_instruction(),
                    model=settings.extraction_model,
                    response_mime_type="application/json",
                    thinking_level=settings.thinking_level,
                    response_schema=PASS1_SCHEMA,
                )
                raw_pass1_payloads.append(response)
                self._write_artifact(
                    meeting_id,
                    extraction_run_id,
                    f"pass1_window_{index:02d}_raw.json",
                    response["raw_response"],
                    role="gemini evidence raw response",
                )
                self._set_job(
                    job_run_id,
                    "running",
                    "extracting_evidence",
                    28 + ((index + 1) / max(1, len(context_windows))) * 26,
                    f"Evidence extraction context {index + 1} of {len(context_windows)} complete",
                )

            self._set_job(job_run_id, "running", "validating_evidence", 58, "Validating evidence and collapsing duplicates")
            validated = self._validate_pass1_outputs(
                segments,
                raw_pass1_payloads,
                max_evidence_items=int(settings.max_evidence_items_per_entity),
            )
            self._write_artifact(
                meeting_id,
                extraction_run_id,
                "validated_extraction.json",
                validated,
                role="validated extraction json",
            )

            validation_report = self._build_validation_report(validated, low_confidence_threshold=low_confidence_threshold)
            self._write_artifact(
                meeting_id,
                extraction_run_id,
                "validation_report.json",
                validation_report,
                role="extraction validation report",
            )

            self._set_job(job_run_id, "running", "generating_minutes", 78, "Generating summary and formal minutes")
            minutes_response = self.gemini_service.generate_content(
                prompt=self._build_pass2_prompt(transcript_run, validated),
                system_instruction=self._pass2_system_instruction(),
                model=settings.minutes_model,
                response_mime_type="application/json",
                thinking_level=settings.thinking_level,
                response_schema=PASS2_SCHEMA,
            )
            self._write_artifact(
                meeting_id,
                extraction_run_id,
                "pass2_minutes_raw.json",
                minutes_response["raw_response"],
                role="gemini minutes raw response",
            )

            self._persist_validated_outputs(meeting_id, extraction_run_id, validated, minutes_response.get("json") or {})
            self.extraction_run_repository.finalize_success(extraction_run_id)
            self.job_run_repository.finalize(
                job_run_id,
                status="completed",
                stage="completed",
                current_message="Extraction complete",
                error_message=None,
            )
            self.meeting_repository.update_status(meeting_id, "transcribed")
        except Exception as exc:  # noqa: BLE001
            self.extraction_run_repository.finalize_failure(extraction_run_id, str(exc))
            self.job_run_repository.finalize(
                job_run_id,
                status="failed",
                stage="failed",
                current_message=str(exc),
                error_message=str(exc),
            )
            self.meeting_repository.update_status(meeting_id, "failed")

    def _validate_pass1_outputs(
        self,
        segments: list[dict[str, Any]],
        payloads: list[dict[str, Any]],
        *,
        max_evidence_items: int,
    ) -> dict[str, Any]:
        segment_map = {int(segment["id"]): segment for segment in segments}
        combined = {
            "decisions": [],
            "action_items": [],
            "risks_issues": [],
            "open_questions": [],
            "key_discussion_topics": [],
        }
        for payload in payloads:
            data = payload.get("json") or {}
            for key in combined:
                if isinstance(data.get(key), list):
                    combined[key].extend(data[key])

        validated = {key: [] for key in combined}
        for entity_key, items in combined.items():
            for item in items:
                valid_item = self._validate_item(entity_key, item, segment_map)
                if valid_item:
                    validated[entity_key].append(valid_item)

        for entity_key in validated:
            validated[entity_key] = dedupe_validated_entities(
                entity_key,
                validated[entity_key],
                max_evidence_items=max_evidence_items,
            )
        return validated

    def _validate_item(
        self,
        entity_key: str,
        item: dict[str, Any],
        segment_map: dict[int, dict[str, Any]],
    ) -> dict[str, Any] | None:
        text = str(item.get("text", "")).strip()
        if not text:
            return None
        confidence = _clamp_confidence(item.get("confidence"))
        explicit_or_inferred = item.get("explicit_or_inferred")
        if explicit_or_inferred not in {"explicit", "inferred"}:
            explicit_or_inferred = "inferred"

        evidence_items = []
        for evidence in item.get("evidence") or []:
            segment_id = evidence.get("transcript_segment_id")
            if segment_id is None:
                continue
            try:
                segment_id = int(segment_id)
            except (TypeError, ValueError):
                continue
            if segment_id not in segment_map:
                continue
            segment = segment_map[segment_id]
            segment_start = int(segment["start_ms_in_meeting"])
            segment_end = int(segment["end_ms_in_meeting"])
            start_ms = max(segment_start, int(evidence.get("start_ms", segment_start)))
            end_ms = min(segment_end, int(evidence.get("end_ms", segment_end)))
            if end_ms < start_ms:
                continue
            quote_snippet = str(evidence.get("quote_snippet") or "").strip()
            if not quote_snippet:
                quote_snippet = _snippet_from_segment(segment, start_ms=start_ms, end_ms=end_ms)
            evidence_items.append(
                {
                    "transcript_segment_id": segment_id,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "speaker_label": evidence.get("speaker_label") or segment.get("speaker_label"),
                    "quote_snippet": quote_snippet[:280],
                    "confidence": _clamp_confidence(evidence.get("confidence")),
                }
            )
        evidence_items = _dedupe_evidence(evidence_items)
        if not evidence_items:
            return None

        evidence_texts = [
            str(segment_map[evidence["transcript_segment_id"]].get("text") or "")
            for evidence in evidence_items
            if evidence.get("transcript_segment_id") in segment_map
        ]

        validated = {
            "text": text,
            "confidence": confidence,
            "explicit_or_inferred": explicit_or_inferred,
            "review_status": "pending",
            "evidence": evidence_items,
        }
        if entity_key == "action_items":
            validated["owner"] = normalize_owner(item.get("owner"), evidence_texts)
            validated["due_date"] = normalize_due_date(item.get("due_date"), evidence_texts)
            validated["priority"] = _nullable_string(item.get("priority"))
        return validated

    def _persist_validated_outputs(
        self,
        meeting_id: int,
        extraction_run_id: int,
        validated: dict[str, Any],
        summary_payload: dict[str, Any],
    ) -> None:
        action_ids = self.action_repository.replace_for_run(extraction_run_id, meeting_id, validated["action_items"])
        decision_ids = self.decision_repository.replace_for_run(extraction_run_id, meeting_id, validated["decisions"])
        risk_ids = self.risk_repository.replace_for_run(extraction_run_id, meeting_id, validated["risks_issues"])
        question_ids = self.question_repository.replace_for_run(extraction_run_id, meeting_id, validated["open_questions"])
        topic_ids = self.topic_repository.replace_for_run(extraction_run_id, meeting_id, validated["key_discussion_topics"])

        evidence_links = []
        entity_id_map = {
            "action_items": action_ids,
            "decisions": decision_ids,
            "risks_issues": risk_ids,
            "open_questions": question_ids,
            "key_discussion_topics": topic_ids,
        }
        entity_type_map = {
            "action_items": "action",
            "decisions": "decision",
            "risks_issues": "risk",
            "open_questions": "question",
            "key_discussion_topics": "topic",
        }
        for key, ids in entity_id_map.items():
            for idx, entity_id in enumerate(ids):
                for evidence in validated[key][idx]["evidence"]:
                    evidence_links.append(
                        {
                            "entity_type": entity_type_map[key],
                            "entity_id": entity_id,
                            "transcript_segment_id": evidence["transcript_segment_id"],
                            "start_ms": evidence["start_ms"],
                            "end_ms": evidence["end_ms"],
                            "speaker_label": evidence.get("speaker_label"),
                            "quote_snippet": evidence.get("quote_snippet"),
                            "confidence": evidence.get("confidence"),
                        }
                    )
        self.evidence_repository.replace_for_run(extraction_run_id, evidence_links)
        self.summary_repository.replace_for_run(
            extraction_run_id,
            meeting_id,
            str(summary_payload.get("executive_summary", "")).strip(),
            str(summary_payload.get("formal_minutes", "")).strip(),
        )
        self._write_artifact(
            meeting_id,
            extraction_run_id,
            "insights_snapshot.json",
            {
                "validated": validated,
                "summary": summary_payload,
            },
            role="insights snapshot",
        )

    def build_insights_payload(self, meeting_id: int) -> dict[str, Any] | None:
        run = self.extraction_run_repository.get_latest_for_meeting(meeting_id)
        if not run:
            return None
        settings = self.gemini_service.get_settings()
        low_confidence_threshold = float(getattr(settings, "low_confidence_threshold", 0.7))
        actions = self.action_repository.list_for_run(run["id"])
        decisions = self.decision_repository.list_for_run(run["id"])
        risks = self.risk_repository.list_for_run(run["id"])
        questions = self.question_repository.list_for_run(run["id"])
        topics = self.topic_repository.list_for_run(run["id"])
        evidence = self.evidence_repository.list_for_run(run["id"])
        summary = self.summary_repository.get_for_run(run["id"])
        grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
        for item in evidence:
            grouped[(item["entity_type"], item["entity_id"])].append(item)

        payload = {
            "run": run,
            "summary": summary,
            "actions": _attach_evidence(actions, grouped, "action"),
            "decisions": _attach_evidence(decisions, grouped, "decision"),
            "risks": _attach_evidence(risks, grouped, "risk"),
            "questions": _attach_evidence(questions, grouped, "question"),
            "topics": _attach_evidence(topics, grouped, "topic"),
        }
        for key in ("actions", "decisions", "risks", "questions", "topics"):
            for item in payload[key]:
                review = assess_review(item, low_confidence_threshold=low_confidence_threshold)
                item["needs_review"] = review.needs_review
                item["review_hints"] = review.review_hints
                item["evidence_count"] = len(item.get("evidence") or [])
        return payload

    def _build_pass1_prompt(self, segments: list[dict[str, Any]], *, window_index: int, total_windows: int) -> str:
        transcript_lines = []
        for segment in segments:
            transcript_lines.append(
                f"[segment_id={segment['id']}] [start_ms={segment['start_ms_in_meeting']}] [end_ms={segment['end_ms_in_meeting']}] "
                f"[speaker={segment.get('speaker_label') or 'unknown'}] {segment['text']}"
            )
        return "\n".join(
            [
                "Extract only evidence-backed meeting insights from the transcript segments below.",
                "The transcript context was selected by a deterministic retrieval layer. Preserve exact transcript_segment_id references.",
                "Do not invent owners, due dates, attendees, decisions, or deadlines.",
                "Every returned item must include one or more evidence entries linked to transcript_segment_id values from the provided transcript.",
                "If owner or due_date is not explicit in evidence, return null for those fields.",
                f"Context window {window_index + 1} of {total_windows}.",
                "",
                "Transcript segments:",
                *transcript_lines,
            ]
        )

    @staticmethod
    def _pass1_system_instruction() -> str:
        return (
            "You are an evidence-first meeting analysis system. "
            "Extract only items supported by the provided transcript segments. "
            "Return no item unless it has concrete transcript evidence. "
            "Prefer direct quotes for quote_snippet where possible."
        )

    def _build_pass2_prompt(self, transcript_run: dict[str, Any], validated: dict[str, Any]) -> str:
        return json.dumps(
            {
                "instruction": (
                    "Generate a concise executive summary and formal meeting minutes using only the validated extraction object below. "
                    "Do not invent attendees, owners, deadlines, or decisions. "
                    "Do not use information outside this payload."
                ),
                "transcript_metadata": {
                    "language_code": transcript_run.get("language_code"),
                    "chunk_count": transcript_run.get("chunk_count"),
                    "average_confidence": transcript_run.get("average_confidence"),
                },
                "validated_extraction": validated,
            },
            indent=2,
        )

    @staticmethod
    def _pass2_system_instruction() -> str:
        return (
            "You write polished but factual meeting summaries and minutes from validated structured extraction data only. "
            "Never add unsupported statements."
        )

    def _build_validation_report(self, validated: dict[str, Any], *, low_confidence_threshold: float) -> dict[str, Any]:
        report = {"counts": {}, "needs_review": {}}
        mapping = {
            "actions": validated["action_items"],
            "decisions": validated["decisions"],
            "risks": validated["risks_issues"],
            "questions": validated["open_questions"],
            "topics": validated["key_discussion_topics"],
        }
        for key, items in mapping.items():
            report["counts"][key] = len(items)
            report["needs_review"][key] = sum(
                1
                for item in items
                if assess_review(item, low_confidence_threshold=low_confidence_threshold).needs_review
            )
        return report

    def _write_artifact(
        self,
        meeting_id: int,
        extraction_run_id: int,
        file_name: str,
        payload: dict[str, Any],
        *,
        role: str,
    ) -> None:
        artifact_root = ensure_directory(config.artifacts_root / f"meeting_{meeting_id}" / f"extraction_{extraction_run_id}")
        path = artifact_root / file_name
        write_json(path, payload)
        self.artifact_service.record_json_artifact(
            meeting_id=meeting_id,
            preprocessing_run_id=None,
            transcription_run_id=None,
            extraction_run_id=extraction_run_id,
            artifact_type="extraction",
            role=role,
            path=path,
            metadata={"file_name": file_name},
        )

    def _set_job(self, job_run_id: int, status: str, stage: str, progress: float, message: str) -> None:
        self.job_run_repository.update_state(
            job_run_id,
            status=status,
            stage=stage,
            progress_percent=progress,
            current_message=message,
        )


def _attach_evidence(
    items: list[dict[str, Any]],
    grouped: dict[tuple[str, int], list[dict[str, Any]]],
    entity_type: str,
) -> list[dict[str, Any]]:
    enriched = []
    for item in items:
        evidence = sorted(grouped.get((entity_type, item["id"]), []), key=lambda entry: (entry["start_ms"], entry["end_ms"], entry["id"]))
        enriched.append({**item, "evidence": evidence})
    return enriched


def _clamp_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = 0.5
    return max(0.0, min(1.0, round(number, 4)))


def _nullable_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _dedupe_evidence(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[int, int, int]] = set()
    for item in sorted(items, key=lambda evidence: (evidence["start_ms"], evidence["end_ms"], evidence["transcript_segment_id"])):
        key = (item["transcript_segment_id"], item["start_ms"], item["end_ms"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _snippet_from_segment(segment: dict[str, Any], *, start_ms: int, end_ms: int) -> str:
    segment_text = str(segment.get("text") or "").strip()
    if not segment_text:
        return ""
    prefix = f"{_format_ms(start_ms)}-{_format_ms(end_ms)}"
    return f"{prefix} {segment_text[:220]}".strip()


def _format_ms(value: int) -> str:
    total_seconds = max(0, value // 1000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"
