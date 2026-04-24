# Architecture Notes

## Desktop shell

The desktop app is a Tauri shell wrapping a React + TypeScript frontend built with Vite and styled with Tailwind CSS.

UI structure:

- left navigation rail
- sticky workspace header
- compact meetings, jobs, and transcript review tables
- dense meeting detail tabs for source, prep, chunks, and transcript review

The frontend uses:

- React Router for workspace routes
- Zustand for local UI state
- TanStack Query for worker-backed reads and mutations

## Worker

The worker is a FastAPI service with thin route handlers. Core logic is pushed into dedicated services:

- `ProbeService`: media inspection via `ffprobe`
- `NormalizationService`: audio extraction/transcoding to mono 16 kHz FLAC
- `SilenceAnalysisService`: silence candidate detection via `ffmpeg silencedetect`
- `ChunkPlanningService`: final boundary selection from silence candidates
- `ChunkWriterService`: real chunk audio file generation and checksum capture
- `ArtifactService`: artifact registration
- `JobService`: preprocessing background execution
- `TranscriptionSettingsService`: resolves Google STT runtime config
- `GoogleSpeechV2Adapter`: isolated Google Cloud Speech-to-Text V2 adapter
- `TranscriptStitcher`: overlap-aware merged transcript builder
- `TranscriptionJobService`: background chunk transcription orchestration
- `GeminiApiService`: isolated Gemini `generateContent` REST client for downstream structured extraction
- `ExtractionService`: evidence-backed two-pass meeting extraction pipeline

## Background jobs

There are now two job types:

- `preprocess`
- `transcribe`

Jobs are tracked in `job_runs`, while stage-specific tables keep their own rich metadata:

- `preprocessing_runs`
- `transcription_runs`

This keeps the Jobs UI generic without flattening the domain model.

## Data model

Primary tables:

- `meetings`
- `source_files`
- `job_runs`
- `preprocessing_runs`
- `chunks`
- `transcription_runs`
- `chunk_transcripts`
- `transcript_segments`
- `transcript_words`
- `artifacts`
- `app_settings`
- `schema_migrations`

Important modeling choices:

- meeting lifecycle uses `draft`, `imported`, `preprocessing`, `prepared`, `transcribing`, `transcribed`, `failed`
- preprocessing and transcription both run as true background jobs
- raw per-chunk transcript responses are preserved
- merged transcript segments are stored separately from chunk-raw segments
- artifacts remain first-class records for preprocessing and transcription outputs
- speaker labels are preserved as returned by STT and are not forced into cross-chunk identity continuity yet

## Processing pipeline

1. Import validates the source file, probes media, stores metadata, and optionally copies the original into managed storage.
2. Preprocess enqueues a background run, writes normalized FLAC, analyzes silence, plans chunks, writes real chunk files, and records artifacts.
3. Transcribe enqueues a separate background run against the latest prepared chunk set.
4. The transcription adapter stages each chunk to Google Cloud Storage, submits a Speech-to-Text V2 batch request, and captures the raw response.
5. Per-chunk responses are normalized into chunk-relative segments and optional words.
6. The stitcher converts those to meeting-relative timings and trims overlap regions to avoid duplicate transcript coverage.
7. The worker persists merged transcript segments, transcript artifacts, and run summaries for UI review.
8. Extraction runs consume the persisted merged transcript, produce evidence-backed structured entities, then generate executive summary and formal minutes from the validated extraction output only.

## Extension points

- speaker rename and reconciliation can layer on top of `speaker_label` plus `speaker_name`
- Gemini extraction should consume the merged transcript, not replace STT
- phrase hints and adaptation config fit into `transcription_runs.config_json`
- retry and cancel can extend `job_runs` and `transcription_runs` without changing the UI contracts
