# Transcription Phase Notes

## Scope completed in this phase

- Google Cloud Speech-to-Text V2 chunk transcription
- raw per-chunk transcript persistence
- merged transcript stitching with overlap-aware deduplication
- transcript artifacts and confidence summary tracking
- transcript review UI and combined jobs UI

## Worker architecture

Main transcription components:

- `TranscriptionSettingsService`
- `GoogleSpeechV2Adapter`
- `TranscriptionJobService`
- `TranscriptStitcher`

The adapter is intentionally isolated so the Google API surface can change without route or UI churn.

## Google credential setup

Preferred path:

- use Application Default Credentials

Alternative path:

- set `auth_mode` to `credentials_file`
- point `credentials_path` to a local service-account JSON file

Required settings:

- `project_id`
- `recognizer_location`
- `recognizer_id` or `_`
- `staging_bucket`
- `staging_prefix`
- `model`
- `language_code`

## Why a staging bucket exists

The app remains local-first for storage and review, but modern long-form Google STT V2 chunk transcription is implemented through a batch flow, so chunk files are staged to Cloud Storage for the request and the resulting artifacts are still persisted locally.

## Data model additions

- `job_runs`
- `transcription_runs`
- `chunk_transcripts`
- `transcript_segments`
- `transcript_words`

The existing `artifacts` table is reused with `transcription_run_id` so transcript outputs stay traceable beside preprocessing artifacts.

## Current limitations

- speaker labels are preserved, but cross-chunk speaker identity continuity is not reconciled yet
- the default implementation expects Google Cloud Storage staging for live V2 batch runs
- retry/cancel is not exposed in the UI yet
- transcript pagination is not implemented because the desktop MVP is optimized for practical meeting-sized review sessions

## Phase 3 follow-up

1. Speaker rename and reconciliation tools
2. Timeline navigation tied to chunk boundaries and waveform data
3. Retry and cancel controls for transcription runs
4. Gemini-based structured minutes, decisions, and actions downstream of the merged transcript
