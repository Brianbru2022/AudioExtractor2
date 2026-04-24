# Phase 3.1 Validation Report

## Scope

This pass hardened the evidence-backed extraction and review workflow without expanding into export, live capture, or generic assistant behavior.

The main focus areas were:

- retrieval-style transcript context selection for larger meetings
- duplicate collapse and extraction post-processing
- stronger evidence persistence and reviewer traceability
- denser, more controllable Insights review UI
- deterministic test coverage for large-transcript behavior

## What Was Tested

### Worker tests

Ran:

```bash
cd worker
python -m unittest discover -s tests
python -m compileall app
```

Validated:

- retrieval/context selection preserves transcript segment ids for selected windows
- small transcripts still use a simple single-window path
- duplicate action extraction collapses into one review item when intent overlaps
- owner and due date remain `null` unless explicitly supported by transcript evidence
- extraction pipeline persists evidence-backed outputs and summary/minutes
- accept/edit/reject persistence still works through the existing PATCH workflow

### Frontend build

Ran:

```bash
cd app
npm run build
```

Validated:

- the denser Insights review UI compiles cleanly
- new filters and bulk accept controls do not break the meeting detail workspace
- evidence jump wiring still targets transcript segment ids

## Improvements Made

### 1. Retrieval-style context selection

Fixed-window extraction batching was replaced with a deterministic context selection layer.

The new flow:

- groups merged transcript segments into topic-aware transcript blocks
- scores blocks for action, decision, risk, question, and topic relevance
- pulls neighboring context around selected blocks
- adds coverage blocks when retrieval would otherwise miss too much of the transcript
- falls back to simple windowing only when needed

Traceability is preserved because every selected context window still contains exact stored transcript segment ids and original meeting-relative timestamps.

Artifacts now include:

- `context_selection_report.json`
- `validated_extraction.json`
- `validation_report.json`

### 2. Better extraction quality control

Post-processing now:

- deduplicates semantically overlapping entities
- merges evidence links from duplicate candidates
- normalizes trivial wording variants
- keeps owner and due date `null` unless evidence actually supports them
- surfaces weak-support cases through `needs_review` and reviewer hints

### 3. Stronger evidence handling

Evidence links now:

- remain multi-link per extracted item
- are deduplicated by segment/timestamp span
- preserve stronger quote snippets
- stay sorted and stable for UI rendering

This makes transcript provenance clearer and keeps evidence jumps deterministic.

### 4. Reviewer workflow hardening

The Insights tab was tightened into a denser review tool:

- clearer run metadata and review-state summary
- stronger pending-review highlighting
- review hints for low confidence, inferred content, missing owner/due date, and thin evidence
- action filters for owner, due-date presence, review status, and explicit vs inferred
- bulk accept for filtered actions
- richer evidence cards with quote snippets and jump actions

## What Passed

- worker unit and integration-style extraction tests passed
- Python compilation passed
- frontend production build passed
- existing extraction persistence behavior remained intact
- evidence-backed review actions remained patchable after the hardening changes

## Edge Cases Fixed

- large transcripts no longer rely purely on fixed transcript windows for extraction context
- duplicate actions with the same intent are collapsed into one review item
- unsupported owners and due dates are cleared instead of silently persisting weak guesses
- evidence links are more stable and reviewer-visible
- low-support extracted items are easier to identify before acceptance

## Remaining Limitations

- retrieval is still heuristic and lexical, not embedding-based semantic search
- diarization continuity across chunk boundaries is still only as strong as the transcription phase
- bulk review is currently focused on action acceptance, not all entity types
- reviewer edits still patch individual entities directly rather than via a richer audit trail
- minutes generation still depends on the validated extraction object quality; it is safer now, but not yet human-equivalent for every dense multi-topic meeting

## What Should Come Next Before Export

- add optional semantic retrieval or reranking for very large transcripts
- add reviewer-side merge/split controls for extracted entities
- add explicit audit history for reviewer edits and bulk actions
- improve topic clustering for long meetings with repeated themes
- add transcript-to-insight side-by-side review affordances before export is introduced
