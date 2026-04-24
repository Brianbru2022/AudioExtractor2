# Audio Extractor 2

Windows desktop meeting-ingest and transcript-review app built with Tauri, React, FastAPI, SQLite, FFmpeg, and Google Cloud Speech-to-Text.

## What is complete in the current phase

- Tauri + React desktop shell with dense dark review UI
- FastAPI local worker with background preprocessing and transcription jobs
- SQLite persistence with migration bootstrap
- Import flow with `reference` and `managed_copy` modes
- FFmpeg-based normalization to mono 16 kHz FLAC
- Silence-aware chunk planning and real chunk file generation with checksums
- Google Cloud Speech-to-Text V2 chunk transcription pipeline
- Raw per-chunk transcript persistence plus merged transcript stitching
- Transcript review UI with speaker labels, timestamps, confidence flags, artifacts, and job tracking
- Gemini-backed evidence extraction from persisted merged transcripts
- Reviewable insights UI for summaries, minutes, actions, decisions, risks, and questions
- Export pipeline for DOCX, PDF, CSV, XLSX, JSON, and TXT delivery outputs

## What is not included yet

- Live recording or microphone streaming
- Speaker reconciliation across chunks
- Cloud sync
- Multi-user auth

## Folder layout

- [app](/D:/new-apps/WORK/2026/Audio%20Extractor%202/app): Tauri desktop shell, React UI, TypeScript frontend
- [worker](/D:/new-apps/WORK/2026/Audio%20Extractor%202/worker): FastAPI worker, SQLite access, preprocessing and transcription services
- [shared](/D:/new-apps/WORK/2026/Audio%20Extractor%202/shared): shared TypeScript API contracts
- [storage](/D:/new-apps/WORK/2026/Audio%20Extractor%202/storage): runtime database, artifacts, normalized audio, chunks, logs
- [docs](/D:/new-apps/WORK/2026/Audio%20Extractor%202/docs): architecture notes and validation docs

## How to run the worker

1. Install Python dependencies:

```powershell
cd "D:\new-apps\WORK\2026\Audio Extractor 2\worker"
python -m pip install -r requirements.txt
```

2. Start the worker:

```powershell
cd "D:\new-apps\WORK\2026\Audio Extractor 2\worker"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload
```

The worker listens on `http://127.0.0.1:8765`.

## How to run the desktop app

1. Install frontend dependencies:

```powershell
cd "D:\new-apps\WORK\2026\Audio Extractor 2\app"
npm install
```

2. Run the web UI during development:

```powershell
cd "D:\new-apps\WORK\2026\Audio Extractor 2\app"
npm run dev
```

3. Run the desktop shell with Tauri:

```powershell
cd "D:\new-apps\WORK\2026\Audio Extractor 2\app"
npm run tauri:dev
```

## FFmpeg expectations

- `ffmpeg` must be available on `PATH`
- `ffprobe` must be available on `PATH`
- The worker uses FFmpeg for probe refresh, normalization, silence analysis, waveform summary generation, and chunk writing

## Gemini API foundation

The worker includes a dedicated Gemini REST client used internally for structured extraction work.

- Settings key: `gemini_defaults`
- Auth modes:
  - `api_key_env`
  - `api_key_file`

Important:

- Do not hardcode Gemini API keys in the repo or SQLite
- Prefer `GEMINI_API_KEY` in the environment
- The current Gemini 3 text model names are preview ids such as `gemini-3-flash-preview` and `gemini-3.1-pro-preview`
- The default extraction model is `gemini-3.1-pro-preview`
- There is not a literal `gemini-3.0` API model id

## Google Cloud setup

The transcription worker is local-first, but Google Speech-to-Text V2 chunk transcription needs Google credentials and a staging bucket.

Configure these in `app_settings.transcription_defaults` through the worker settings API or directly in the DB:

- `project_id`
- `auth_mode`
- `credentials_path` if you are not using Application Default Credentials
- `recognizer_location`
- `recognizer_id` or `_`
- `staging_bucket`
- `staging_prefix`
- `model`
- `language_code`
- diarization, punctuation, confidence, and parallelism defaults

Credential handling rules:

- Prefer Application Default Credentials
- Or set `auth_mode` to `credentials_file` and point `credentials_path` at a local service-account file
- Do not store raw credential JSON in SQLite

## Where files are stored

- Database: [storage/db](/D:/new-apps/WORK/2026/Audio%20Extractor%202/storage/db)
- Managed copies: [storage/managed](/D:/new-apps/WORK/2026/Audio%20Extractor%202/storage/managed)
- Normalized audio: [storage/normalized](/D:/new-apps/WORK/2026/Audio%20Extractor%202/storage/normalized)
- Chunk files: [storage/chunks](/D:/new-apps/WORK/2026/Audio%20Extractor%202/storage/chunks)
- JSON and transcript artifacts: [storage/artifacts](/D:/new-apps/WORK/2026/Audio%20Extractor%202/storage/artifacts)
- Export outputs: [storage/exports](/D:/new-apps/WORK/2026/Audio%20Extractor%202/storage/exports)
- Logs: [storage/logs](/D:/new-apps/WORK/2026/Audio%20Extractor%202/storage/logs)

Original media is never modified. In `reference` mode the worker reads the original file in place. In `managed_copy` mode it duplicates the original into local storage before preprocessing.

## Validation

- `npm run build`
- `python -m unittest discover -s tests`
- `python -m compileall worker/app`

## Export formats

Meeting Detail now supports these exports from persisted reviewed data:

- Formal Minutes Pack
  - `DOCX`
  - `PDF`
- Action Register
  - `CSV`
  - `XLSX`
- Full Archive
  - `JSON`
- Merged Transcript
  - `TXT`

Export options include:

- reviewed only vs all extracted items
- evidence appendix on/off
- transcript appendix on/off
- confidence flags on/off

## What should come next

1. Add speaker rename and cross-chunk speaker reconciliation.
2. Add transcript navigation tied to waveform and chunk boundaries.
3. Add explicit review/approval state for summary and minutes.
4. Add retry and cancel controls for more background job types where useful.
5. Add packaging and delivery workflows on top of the export layer.
