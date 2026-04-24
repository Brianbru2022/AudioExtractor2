# Phase 3.2 Live Validation Report

## Scope

This pass focused on live-path validation and targeted hardening for the existing pipeline:

- import
- preprocess
- chunking
- Google STT preflight and failure handling
- Gemini extraction runtime validation
- transcript and insight review persistence

No export work was added.

## Validation Plan

The validation plan for this pass was:

1. Run real local ingest and preprocessing on production-like media already present in the workspace.
2. Exercise the cloud stages with real runtime conditions where credentials existed, and otherwise validate failure behavior with real adapters instead of only stubs.
3. Inspect persisted artifacts, run state transitions, and evidence traceability after each stage.
4. Tighten any runtime issues found in the live path, then add regression coverage.

## Live Test Scenarios

### Scenario A: short real-file ingest and preprocessing

- Source: `storage/imports/validation/formats/sample.wav`
- Import mode: `reference`
- Title: `Live Validation Short`

Observed result:

- import completed successfully
- preprocessing completed successfully
- normalized FLAC written
- 1 prepared chunk written
- expected artifacts persisted:
  - normalized audio
  - silence map
  - chunk manifest
  - waveform summary
  - preprocessing log

### Scenario B: long-form real-file ingest and preprocessing

- Source: `storage/imports/validation/long_form/long_form_2h.mp3`
- Import mode: `managed_copy`
- Title: `Live Validation Long`

Observed result:

- import completed successfully
- managed copy written into local storage
- preprocessing completed successfully
- normalized FLAC written
- 10 chunks generated across the 2-hour fixture
- first chunk boundary reason: `hard_max_fallback`
- final chunk boundary reason: `min_length_adjustment`
- expected artifacts persisted:
  - managed copy
  - normalized audio
  - silence map
  - chunk manifest
  - waveform summary
  - preprocessing log

This confirms the local ingest, normalization, and long-form chunking path is working on real files, not just seeded tests.

### Scenario C: transcription preflight without valid live Google setup

Validated against prepared meetings:

- `POST /meetings/{id}/transcribe` now fails immediately when transcription settings still contain placeholder values
- the error is explicit:
  - `Google Cloud project_id is still set to a placeholder value`

This is an improvement over letting invalid runtime settings reach the background job.

### Scenario D: transcription background failure with intentionally invalid live config

Used:

- non-placeholder project id
- non-placeholder bucket name
- invalid credentials file

Observed result:

- transcription job enqueued
- run failed cleanly in the background
- chunk transcript rows were persisted with failure state
- run-level error now includes the underlying chunk error summary instead of only `All chunk transcription requests failed`

Observed runtime blocker:

- the environment is missing the Google Speech dependency path needed by the live adapter:
  - `Google Cloud Speech dependencies are missing. Install google-cloud-speech and protobuf.`

This is now surfaced clearly at the run level.

### Scenario E: live Gemini extraction with missing key

Observed result:

- extraction enqueue fails early with:
  - `Gemini API key not found in environment variable GEMINI_API_KEY`

This is the intended hardened behavior.

### Scenario F: live Gemini extraction with real Gemini responses

Used:

- transient environment variable only
- no key stored in SQLite or repo
- model baseline restored to `gemini-3.1-pro-preview`

Validated on persisted transcripts from existing completed meetings:

- meeting `43`: short transcript with limited insight content
- meeting `40`: transcript containing a rollout decision and timeline action

Observed result on meeting `43`:

- extraction completed successfully
- summary stayed conservative
- no actions or decisions were invented
- only discussion topics were returned

Observed result on meeting `40`:

- extraction completed successfully
- 1 action returned
- 1 decision returned
- action owner remained `null`
- action due date remained `null`
- evidence links pointed to valid stored transcript segment ids
- evidence jump targets were confirmed against the transcript payload
- accept/edit persistence worked through the existing insight PATCH route

Artifacts written for live extraction runs included:

- context selection report
- raw Gemini evidence response
- validated extraction JSON
- extraction validation report
- raw Gemini minutes response
- insights snapshot

## What Was Adjusted

### 1. Stronger transcription preflight validation

`TranscriptionSettingsService.validate()` now rejects:

- placeholder project ids
- placeholder bucket names
- missing credentials file paths
- missing credentials files
- missing Application Default Credentials when ADC mode is selected
- invalid speaker-count ranges

### 2. Stronger Gemini runtime validation

`GeminiApiService` now exposes `validate_runtime()` and checks:

- model presence
- API key availability
- non-empty key file contents

`ExtractionService.enqueue()` now uses that preflight path.

### 3. Fixed live Gemini runtime bug

Live validation exposed a real runtime defect:

- `GeminiSettings` did not include extraction-specific fields already expected by `ExtractionService`

This was fixed by adding:

- `extraction_model`
- `minutes_model`
- `fallback_model`
- `max_segments_per_batch`
- `max_evidence_items_per_entity`
- `low_confidence_threshold`

The extraction service now uses extraction/minutes model fields explicitly.

### 4. Better all-chunks-failed transcription errors

If every chunk fails, the run-level transcription error now includes the first chunk failure details so the reviewer sees the actionable cause immediately.

### 5. Test isolation hardening

Tests were mutating the live SQLite settings rows. The test suite now restores settings after execution so the local runtime configuration does not drift after test runs.

## Deterministic Regression Coverage Added Or Updated

Validated with:

```bash
cd worker
python -m unittest discover -s tests
python -m compileall app
```

Current worker test count:

- `24` tests passing

New or updated coverage includes:

- placeholder transcription settings rejection
- all-chunks-failed error propagation
- Gemini runtime validation coverage
- settings restoration in tests

## What Worked Well

- real local ingest and preprocessing path is stable on both short and long-form files
- artifact persistence remains consistent and queryable
- long-form chunking continues to behave sensibly on the 2-hour fixture
- live Gemini extraction is grounded and conservative on sparse transcripts
- evidence references remain traceable into transcript segment ids
- reviewer acceptance persistence works on extracted items

## Remaining Limitations

- a full live Google STT V2 run was not completed in this environment because real Google Cloud prerequisites are still missing
- the current machine is missing the `google-cloud-speech` dependency path required by the adapter
- no valid Speech-to-Text credentials or staging bucket were available for a real cloud transcription job
- the live Gemini validation was run against persisted transcripts already in SQLite, not against transcripts produced by a live STT job in this environment
- the Insights UI was validated through payload behavior and persistence, not through a recorded desktop UI session in this report

## Readiness Assessment Before Export

Current assessment:

- local ingest/preprocess/chunking: ready
- Gemini extraction runtime path: substantially validated
- reviewer persistence path: validated
- full live STT-to-stitch-to-extract chain: not yet fully validated on real Google STT in this environment

Conclusion:

The app is **not yet ready for export implementation** if export is expected to depend on production confidence in the full cloud transcription path.

Before export should start, complete one more live validation pass with:

- installed Google STT Python dependencies
- valid Google Cloud credentials
- valid staging bucket
- at least one real end-to-end STT V2 run from prepared chunks through merged transcript and extraction
