# Extraction Phase Notes

## Goal

Produce evidence-backed meeting outputs from the persisted merged transcript:

- executive summary
- formal meeting minutes
- decisions
- action items
- risks and issues
- open questions
- key discussion topics

## Pipeline

Extraction is a two-pass background workflow.

### Pass 1: evidence extraction

Gemini receives transcript segments already stored in SQLite and returns schema-constrained JSON for:

- decisions
- action items
- risks/issues
- open questions
- key discussion topics

Each item must carry transcript evidence references. The worker validates those references against stored transcript segment ids and meeting-relative timestamp bounds before anything is persisted.

### Pass 2: formatted minutes generation

Gemini receives:

- transcript metadata
- the validated pass 1 extraction object

It does not receive the raw transcript alone for the final minutes stage. This keeps the final summary and minutes grounded in the validated extraction output.

## Evidence rules

- no extracted item is persisted without valid transcript evidence
- owner stays `null` unless clearly supported
- due date stays `null` unless clearly supported
- evidence links preserve transcript segment ids, timestamp spans, speaker labels, and quote snippets where available
- raw Gemini responses are preserved as artifacts
- validated structured extraction JSON is preserved as an artifact

## Data model

Primary tables:

- `extraction_runs`
- `extracted_actions`
- `extracted_decisions`
- `extracted_risks`
- `extracted_questions`
- `extracted_topics`
- `extracted_evidence_links`
- `extracted_summaries`

The existing `artifacts` table is reused with `extraction_run_id` for raw responses, validated extraction JSON, and snapshot artifacts.

## UI review workflow

The Meeting Detail page now includes an `Insights` tab with:

- Summary
- Minutes
- Actions
- Decisions
- Risks
- Questions

Reviewers can:

- inspect evidence pills and timestamps
- jump back to transcript segments
- accept, reject, or keep items pending
- edit extracted item text
- edit owner, due date, and priority on actions

## Current limitations

- extraction currently batches transcript segments into simple windows rather than semantic retrieval chunks
- topics are persisted and shown in Summary, but there is not yet a dedicated Topics review tab
- speaker reconciliation still depends on transcription-phase speaker labels
