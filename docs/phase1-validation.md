# Phase 1 Validation

## What was tested

### Long-form chunking

- End-to-end preprocessing run against a generated 2-hour MP3 meeting file
- Planner-level 3-hour coverage test with repeated silence candidates
- Coverage validation checked:
  - chunk count
  - full-duration coverage
  - gap detection
  - duplicate coverage beyond intended overlap

### Silence-analysis and planning edge cases

- Many silence candidates near target boundaries
- No silence candidates at all
- Long silent stretches where the target falls inside a silence window
- Low-level background noise in generated validation media

### Audio format robustness

End-to-end import + preprocess validation for:

- WAV
- MP3
- M4A
- FLAC
- MP4
- MOV
- MKV

### Artifact and data integrity

- Normalized audio checksum verification from artifact record to file on disk
- Chunk-manifest coverage validation
- Reference mode validation
- Managed-copy mode validation
- Missing or moved source file failure behavior at preprocess start

### UI review pass

- Meeting detail view density and status clarity
- Job progress visibility
- Artifact display clarity
- Error visibility in the meeting detail view

## What passed

- The 2-hour end-to-end preprocessing run completed successfully with `prepared` meeting status and `completed` run status.
- The long-form validation produced 10 chunks with:
  - `covers_full_duration: true`
  - `gaps_ms: 0`
  - `duplicate_beyond_overlap_ms: 0`
- All tested formats imported, probed, normalized, and prepared successfully.
- Video containers were correctly identified as `media_type: video`.
- Normalized-audio checksums matched the artifact records for every tested format.
- Managed-copy mode stored stable paths under `storage/managed`.
- Reference mode preserved the original path without copying.
- Missing/moved reference sources now fail clearly before the background job is queued.
- Planner-level coverage tests for sparse, dense, and long-silence candidate sets passed.

## Edge cases fixed during hardening

- Fixed overlap math in chunk generation.
  The original implementation doubled effective overlap across boundaries. The chunk planner now splits overlap across adjacent chunks so duplicate coverage does not exceed the intended overlap budget.

- Added chunk coverage validation metadata.
  The chunking strategy now records whether the chunk graph covers the full duration, whether any gaps exist, and whether there is duplicate coverage beyond the configured overlap.

- Improved long-silence boundary selection.
  When the target boundary falls inside a long silence window, the planner now prefers the target point instead of blindly using the silence midpoint.

- Hardened missing-source handling.
  Preprocess requests now fail immediately with a clear `400` response if the reference or managed-copy source path no longer exists.

- Improved silence summary output.
  Silence analysis now records total silence and longest silence, which helps review and later UI/debugging.

- Tightened review UI clarity.
  The Jobs page now shows visible progress bars and failure emphasis, and the Meeting Detail page surfaces progress, errors, artifact checksums, and logs more clearly in a denser layout.

## Limitations that remain

- The long-form end-to-end validation was run against a generated 2-hour file, not a full 3-hour real meeting recording.
- The 3-hour scenario is currently validated at planner level rather than by running the full FFmpeg pipeline on a 3-hour corpus.
- Format validation used synthetic but realistic-enough generated media, not a large external corpus with unusual codecs or damaged files.
- Silence behavior is still based on a single default threshold and duration setting; very difficult real-world recordings may still benefit from configurable thresholds or adaptive analysis in a later phase.
- Retry and cancel are still designed for but not implemented yet.
