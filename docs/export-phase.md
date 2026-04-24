# Phase 4 Export Architecture

## Scope

This phase adds reviewed-output export only.

Included:

- DOCX formal minutes export
- PDF formal minutes export
- CSV action register export
- XLSX action register export
- JSON full archive export
- TXT merged transcript export
- persisted export history
- Meeting Detail export UI

Not included:

- new AI features
- export to cloud destinations
- multi-user delivery workflows
- live capture

## Source Of Truth

Exports are generated from persisted worker data only.

The export service reads:

- `meetings`
- `source_files`
- `preprocessing_runs`
- `transcription_runs`
- `transcript_segments` with `source_type = merged`
- `extraction_runs`
- `extracted_actions`
- `extracted_decisions`
- `extracted_risks`
- `extracted_questions`
- `extracted_topics`
- `extracted_evidence_links`
- `extracted_summaries`

The React UI only submits export requests and displays export history. It does not assemble export content.

## Export Profiles

### Formal Minutes Pack

Supported formats:

- `docx`
- `pdf`

Content:

- meeting metadata
- executive summary
- formal minutes
- decisions
- risks/issues
- open questions
- action items
- optional evidence appendix
- optional transcript appendix

### Action Register

Supported formats:

- `csv`
- `xlsx`

Content:

- one row per action
- action text
- owner
- due date
- review status
- explicit vs inferred
- evidence timestamps
- optional confidence

### Full Archive

Supported formats:

- `json`

Content:

- meeting metadata
- source file summary
- preprocessing and transcription metadata
- merged transcript
- extracted outputs
- evidence mappings
- artifact list
- export options used

### Transcript Export

Supported formats:

- `txt`

Content:

- merged transcript only
- meeting-relative timestamps
- speaker labels when available
- persisted segment ordering

## Reviewed-Only Behavior

When `reviewed_only = true`:

- exported actions, decisions, risks, questions, and topics are filtered to `review_status = accepted`

Summary and formal minutes are still exported from persisted `extracted_summaries`, because they are stored as the canonical reviewed summary text for the meeting.

When `reviewed_only = false`:

- all persisted extracted items are included regardless of review status

## File Output Location

Exports are written under:

- [storage/exports](/D:/new-apps/WORK/2026/Audio%20Extractor%202/storage/exports)

Per-meeting layout:

- `storage/exports/meeting_{id}/`

Example file naming:

- `20260410T201500Z_weekly_operating_review_formal_minutes_pack.docx`

## Worker Architecture

Main components:

- [exports.py](/D:/new-apps/WORK/2026/Audio%20Extractor%202/worker/app/repositories/exports.py)
  Export history persistence
- [service.py](/D:/new-apps/WORK/2026/Audio%20Extractor%202/worker/app/services/exports/service.py)
  Export source assembly and file generation
- [routes.py](/D:/new-apps/WORK/2026/Audio%20Extractor%202/worker/app/api/routes.py)
  Thin export routes

Formats used:

- `python-docx` for DOCX
- `reportlab` for PDF
- `openpyxl` for XLSX
- Python standard library for CSV, JSON, and TXT

## API Routes

- `POST /api/v1/meetings/{meeting_id}/exports`
- `GET /api/v1/meetings/{meeting_id}/exports`
- `GET /api/v1/export-runs/{export_run_id}`
- `POST /api/v1/export-runs/{export_run_id}/open-folder`

## Export History

`export_runs` stores:

- export profile
- format
- options used
- output path
- status
- started/completed timestamps
- failure message when applicable

This allows the UI to show:

- latest export state
- last export time
- open-folder action
- export failures

## Current Limitations

- DOCX/PDF styling is intentionally compact and professional, but not yet template-branded
- PDF and DOCX are generated from the same persisted content, not from a shared rich layout template
- summary/minutes do not currently have an explicit review-status workflow separate from item-level review
- export runs are synchronous worker operations rather than queued background jobs

## Recommended Next Phase

Before adding cloud sync or collaboration, the strongest next step would be:

1. add summary/minutes explicit review and approval state
2. add speaker rename/reconciliation to improve transcript-facing exports
3. add export bundles or zip packaging if operational delivery requires one-click packs
