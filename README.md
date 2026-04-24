# Audio Extractor 2

[![Windows Desktop Build](https://github.com/Brianbru2022/AudioExtractor2/actions/workflows/windows-release.yml/badge.svg)](https://github.com/Brianbru2022/AudioExtractor2/actions/workflows/windows-release.yml)

Audio Extractor 2 is a Windows-first desktop application for long-form meeting ingestion, chunk-aware transcription prep, Google Cloud Speech-to-Text transcription, evidence-backed Gemini extraction, human review, and business-ready export.

![Audio Extractor 2 overview](app/src/assets/hero.png)

## What it does

- Imports local meeting audio and video files
- Preserves the original file while creating normalized working audio
- Plans long-form chunks using silence-aware boundaries and overlap
- Transcribes prepared chunks with Google Cloud Speech-to-Text V2
- Stitches chunk transcripts into a merged, reviewable meeting transcript
- Extracts evidence-backed minutes, decisions, risks, questions, and actions with Gemini
- Supports reviewer approval and export to DOCX, PDF, CSV, XLSX, JSON, and TXT

## Architecture

| Area | Stack | Purpose |
| --- | --- | --- |
| Desktop app | Tauri + React + TypeScript + Vite + Tailwind | Windows shell and review UI |
| Local worker | FastAPI + Python 3 | Ingest, preprocessing, chunking, transcription, extraction, export |
| Storage | SQLite + local filesystem | Persistent metadata, runs, artifacts, transcripts, exports |
| Media tooling | FFmpeg + FFprobe | Probe, normalize, silence analysis, chunk writing |
| STT | Google Cloud Speech-to-Text V2 | Chunk transcription |
| Extraction | Gemini structured outputs | Evidence-backed downstream meeting extraction |

## Current workflow

The UI is organized around a business workflow rather than pipeline internals:

1. Import
2. Preparation
3. Transcription
4. Speaker Tagging
5. Minutes & Tasks
6. Export
7. History
8. Settings

## Repository layout

- `app/` - Tauri desktop shell and React frontend
- `worker/` - FastAPI worker, repositories, services, and tests
- `shared/` - shared TypeScript API contracts
- `docs/` - architecture notes and validation reports
- `storage/` - local runtime data only, intentionally gitignored

## Local development

### Prerequisites

- Windows 10 or 11
- Node.js 20+
- Python 3.11+
- Rust stable toolchain
- FFmpeg and FFprobe on `PATH`
- Tauri Windows prerequisites, including WebView2

### Run the worker

```powershell
cd worker
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765 --reload
```

### Run the desktop app

```powershell
cd app
npm install
npm run tauri:dev
```

The worker listens on `http://127.0.0.1:8765`.

## Cloud configuration

### Google Cloud Speech-to-Text

Configure the worker with:

- `project_id`
- `auth_mode`
- `credentials_path` when using file-based credentials
- `recognizer_location`
- `recognizer_id`
- `staging_bucket`
- `staging_prefix`
- `model`
- `language_code`

Recommended defaults:

- model: `chirp_3`
- language: `en-US`
- recognizer location: region aligned with your bucket and recognizer setup

### Gemini extraction

Gemini is used only for downstream structured extraction, not transcription.

- preferred auth: environment variable `GEMINI_API_KEY`
- supported auth modes: environment-based or file-based
- default extraction model: `gemini-3.1-pro-preview`
- faster fallback: `gemini-3-flash-preview`

Do not commit credential files, API keys, or local settings JSON.

## GitHub Actions packaging

This repository includes a Windows GitHub Actions workflow in [`.github/workflows/windows-release.yml`](.github/workflows/windows-release.yml).

What it does:

- builds the Tauri desktop shell on `windows-latest`
- uploads workflow artifacts on manual runs
- creates a GitHub release with Windows bundles when you push a tag like `v0.1.0`

Important:

- the workflow packages the desktop app shell
- the FastAPI worker is still operated separately in the current architecture
- if you later want a single-click shipped installer with the worker bundled, that should be handled as a packaging phase rather than by committing runtime data

## Validation

Frontend:

```powershell
cd app
npm run build
```

Worker:

```powershell
cd worker
python -m unittest discover -s tests
python -m compileall app
```

## Documentation

- [Architecture](docs/architecture.md)
- [Transcription Phase](docs/transcription-phase.md)
- [Extraction Phase](docs/extraction-phase.md)
- [Export Phase](docs/export-phase.md)
- [Phase 1 Validation](docs/phase1-validation.md)
- [Phase 3 Validation](docs/phase3-validation.md)
- [Phase 3 Live Validation](docs/phase3-live-validation.md)
- [Phase 3 STT Live Validation](docs/phase3-stt-live-validation.md)

## Known limitations

- Worker and desktop shell are still deployed as separate processes
- Speaker identity is preserved per transcript evidence but not fully reconciled across chunks
- Live recording, cloud sync, multi-user support, and generic assistant behavior are intentionally out of scope

## License

This repository is currently licensed under the MIT License. See [LICENSE](LICENSE).
