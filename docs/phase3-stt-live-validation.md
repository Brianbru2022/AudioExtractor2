# Phase 3.3-3.5 STT Live Validation

## Scope

This pass was limited to real Speech-to-Text V2 activation, live validation, and chunk-level recovery hardening:

- validate the real worker runtime and dependency path
- validate credentials loading in the worker runtime
- validate staging-bucket reachability and write access before queueing transcription
- run one true live Google STT V2 transcription end to end
- validate multi-chunk transcription and stitching on a real long-form meeting
- add chunk-level retry and recovery so one failed chunk does not force a full rerun
- inspect persisted raw responses, merged transcript artifacts, timestamps, and status transitions
- tighten failure messaging only where the live run exposed real defects

No export work was added. No Gemini work was changed. A minimal schema change was added for chunk transcript attempt history.

## Exact Environment Used

Worker interpreter:

- `C:\Users\birob\AppData\Local\Programs\Python\Python313\python.exe`

Installed package versions in the real worker runtime:

- `google-cloud-speech==2.33.0`
- `google-cloud-storage==3.4.1`
- `protobuf==6.33.0`
- `google-auth==2.49.2`

Credential mode used for the successful live run:

- `credentials_file`

Actual credentials file used:

- `C:\Users\birob\Downloads\Audio Extractor Codex Handoff 2026-03-20\stt-transcription-app-4c55c135d34e.json`

Note:

- the user-provided path `C:\Users\Brian\keys\stt-service-account.json` did not exist in this environment
- the existing handoff JSON above was used instead

Validated service-account metadata:

- project id: `stt-transcription-app`
- client email: `stt-backend@stt-transcription-app.iam.gserviceaccount.com`

## Exact STT Settings Used

Final working configuration:

- `project_id`: `stt-transcription-app`
- `auth_mode`: `credentials_file`
- `credentials_path`: `C:\Users\birob\Downloads\Audio Extractor Codex Handoff 2026-03-20\stt-transcription-app-4c55c135d34e.json`
- `recognizer_location`: `us`
- `recognizer_id`: `_`
- `staging_bucket`: `stt-transcription-app-audio-extractor-birob-01`
- `staging_prefix`: `audio-extractor-2`
- `model`: `chirp_3`
- `language_code`: `en-US`
- `diarization_enabled`: `true`
- `automatic_punctuation_enabled`: `true`
- `enable_word_time_offsets`: `true`
- `enable_word_confidence`: configured `true`, but automatically disabled at request time for `chirp_3`

Bucket metadata observed during validation:

- bucket: `stt-transcription-app-audio-extractor-birob-01`
- location: `US-CENTRAL1`
- storage class: `STANDARD`

## Environment Activation Results

### Runtime and credential discovery

Confirmed:

- Google STT dependencies import correctly in the real worker runtime
- the Speech V2 client constructs successfully
- the credentials file is readable and valid
- the worker health route now reports both dependency status and STT preflight status

### Bucket validation

Confirmed:

- the configured bucket is reachable from the active credentials
- transcription enqueue now validates bucket write access before it creates a background job

## Live Run Summary

### Final successful meeting

Meeting used for the final successful run:

- meeting id: `103`
- title: `Live STT Smoke Test`
- source file: `D:\new-apps\WORK\2026\Audio Extractor 2\storage\imports\smoke_test.wav`
- source duration: `7000 ms`
- preprocessing run id: `89`
- transcription job id: `167`
- transcription run id: `62`

### Successful live run outcome

Result:

- live Google STT V2 transcription completed successfully end to end

Observed state transitions:

- meeting status: `prepared` -> `transcribing` -> `transcribed`
- job status/stage: `running/transcribing_chunks` -> `completed/completed`
- transcription run status: `pending` -> `running` -> `completed`

Chunk outcome:

- chunk count: `1`
- completed chunk transcripts: `1`
- failed chunk transcripts: `0`

Persisted transcript text:

- `Hello. Good morning. How are you?`

Persisted merged segments:

1. `0-120 ms` speaker `1` -> `Hello.`
2. `240-560 ms` speaker `2` -> `Good morning.`
3. `1280-1520 ms` speaker `1` -> `How are you?`

Transcript summary:

- merged segment count: `3`
- word count: `6`
- speaker labels: `1`, `2`
- average confidence: `null`

Average confidence remained `null` because the real `chirp_3` response used in this run did not include confidence scores.

### Multi-chunk validation meeting

Meeting used for multi-chunk validation:

- meeting id: `11`
- title: `Validation Long Form 2H`
- source file: `D:\new-apps\WORK\2026\Audio Extractor 2\storage\imports\validation\long_form\long_form_2h.mp3`
- source duration: `7,200,000 ms`
- preprocessing run id: `10`
- chunk count: `10`

Final multi-chunk transcription run:

- job run id: `191`
- transcription run id: `73`

Initial observed outcome:

- transcription run status: `completed`
- completed chunk count: `9`
- failed chunk count: `1`
- merged segment count: `23`
- merged word count: `55`
- merged transcript artifact payload size: about `68.5 KB`

Observed failed chunk:

- chunk index: `6`
- chunk id: `15`
- error:
  - `503 WSAGetOverlappedResult: Connection reset (An existing connection was forcibly closed by the remote host. -- 10054)`

### Chunk-level recovery validation

Recovery pass executed against the same real run:

- original transcription run id: `73`
- recovery job run id: `289`
- retried chunk ids: `15`

Final observed outcome after retry:

- transcription run status: `recovered`
- completed chunk count: `10`
- failed chunk count: `0`
- merged segment count: `26`
- merged word count: `61`

Observed state transitions during recovery:

- run status: `completed_with_failures` -> `running` -> `recovered`
- recovery job status/stage: `queued/queued` -> `running/transcribing_chunks` -> `running/stitching` -> `recovered/completed`

Validation result:

- only the failed chunk was retranscribed
- previously successful chunk results were preserved and not resent
- the merged transcript was regenerated after recovery
- raw response persistence now includes per-attempt files for retried chunks
- the final transcript is complete again without rerunning the whole meeting

## Persisted Artifacts Verified

The successful run persisted all expected transcript artifacts:

- raw chunk response:
  - `storage/artifacts/meeting_103/transcription_62/chunk_000_response.json`
- merged transcript JSON:
  - `storage/artifacts/meeting_103/transcription_62/merged_transcript.json`
- merged transcript text:
  - `storage/artifacts/meeting_103/transcription_62/merged_transcript.txt`
- stitching report:
  - `storage/artifacts/meeting_103/transcription_62/stitching_report.json`
- confidence summary:
  - `storage/artifacts/meeting_103/transcription_62/confidence_summary.json`

Stitching report confirmed:

- `chunk_count = 1`
- `raw_segment_count = 3`
- `merged_segment_count = 3`
- `word_count = 6`
- `dropped_segment_count = 0`
- `dropped_word_count = 0`

For the multi-chunk run (`transcription_run_id = 73`), verified persisted artifacts include:

- raw chunk responses for the successful original chunk requests
- raw per-attempt retry response for recovered chunk `6`:
  - `storage/artifacts/meeting_11/transcription_73/chunk_006_attempt_02_response.json`
- merged transcript JSON
- merged transcript TXT
- stitching report
- confidence summary

Recovered multi-chunk stitching report confirmed:

- `chunk_count = 10`
- `raw_segment_count = 26`
- `merged_segment_count = 26`
- `word_count = 61`
- `dropped_segment_count = 0`
- `dropped_word_count = 0`

## Real Issues Exposed And Fixed

### 1. `chirp_3` with `global` location

Initial live attempt failed with:

- `The model "chirp_3" does not exist in the location named "global".`

Fix made:

- added early validation so `chirp_3` with `recognizer_location=global` fails before queueing a job
- health now surfaces the same preflight error clearly

Final behavior:

- health reports `speech_preflight_available: false`
- enqueue returns HTTP `400` with:
  - `chirp_3 is not available in recognizer_location=global. Use a supported location such as us or eu.`

### 2. Unsupported `enable_word_confidence` for `chirp_3`

After switching to `us`, the next live attempt failed with:

- `Recognizer does not support feature: word_level_confidence`

Fix made:

- request-building now disables `enable_word_confidence` automatically for `chirp_3`
- the stored request config shows the effective value used for the request

This keeps the transcription path working while preserving `average_confidence` and word confidence as nullable fields.

### 3. Real-response offset normalization

The first successful chunk response returned real transcript text, but word offsets came back outside the local 7-second chunk timeline:

- first returned word offset was `9s`
- last returned word offset was `10.520s`

That caused the stitcher to drop all merged segments.

Fix made:

- parse-time normalization now re-bases obviously out-of-range word offsets against the chunk timeline
- a regression test was added for this exact response pattern

Final result:

- merged segments now persist correctly
- meeting-relative timestamps are ordered and usable in the transcript UI

### 4. Multi-chunk timing sanitation

The live multi-chunk run exposed additional timing pathologies from real STT output:

- punctuation-only pseudo-words such as `[` with no usable timing
- single tokens with implausibly long word durations
- malformed word ordering that could distort segment grouping

Fixes made:

- punctuation-only tokens are dropped during word parsing
- words whose `end_offset` is earlier than `start_offset` are dropped
- parsed words are always sorted by effective time before grouping
- implausibly long token windows are clamped to a sane local duration
- missing word start/end values now fall back to bounded token windows

Final result:

- merged transcript segments no longer contain negative durations
- merged transcript segments are ordered monotonically in meeting time
- the earlier stray `[` segment and reversed-time segment corruption no longer appear

### 5. SQLite lock hardening during long-run polling

During aggressive polling against a long transcription run, SQLite raised:

- `database is locked`

Fix made:

- SQLite connections now use a `30s` timeout
- `PRAGMA journal_mode = WAL`
- `PRAGMA busy_timeout = 30000`
- `PRAGMA synchronous = NORMAL`

This reduced contention between background job writes and concurrent read polling during long runs.

### 6. Transient network retry for long chunk uploads

The first multi-chunk runs exposed transient Google transport failures such as:

- upload timeout while writing chunk files to GCS
- `503` connection reset during the STT call path

Fix made:

- GCS upload timeout increased substantially for chunk staging
- chunk transcription now retries transient transport failures up to three attempts

This improved the long-form live run from several failed chunks to a single remaining failed chunk.

### 7. Chunk-level retry, recovery, and orphaned-run cleanup

The long-form live validation confirmed the remaining production gap:

- one transient chunk failure should not require retranscribing the full meeting

Fixes made:

- added `chunk_transcript_attempts` persistence to keep attempt-level history
- added per-chunk retry for failed chunks within the existing transcription run
- added recovery-aware run statuses:
  - `completed_with_failures`
  - `recovered`
- added regeneration of merged transcript artifacts after recovered chunks succeed
- changed artifact persistence to upsert by run/role/path so regeneration does not create duplicate review records
- added orphaned-run recovery so a stale `running` transcription can be resumed safely after process interruption

Validated live on run `73`:

- the failed chunk retried successfully without retranscribing the other `9` chunks
- attempt history now shows:
  - attempt `1`: failed
  - attempt `2`: completed
- run `73` now ends in `recovered`
- the final merged transcript and stitching report were regenerated cleanly

## Failure-Path Confirmation

Confirmed during this pass:

### Missing credentials path

- health reports:
  - `Google credentials file is invalid or unreadable: ...`
- enqueue returns HTTP `400` with:
  - `credentials_path does not exist: ...`

### Invalid model/location combination

- health reports:
  - `chirp_3 is not available in recognizer_location=global. Use a supported location such as us or eu.`
- enqueue returns HTTP `400` with the same message

### Package/runtime mismatch

The health route continues to surface missing Google dependencies explicitly if they are absent from the worker runtime.

### Bucket access and bucket write preflight

Transcription enqueue now performs a real bucket-write preflight before creating the job. If the bucket is reachable but not writable, the enqueue path fails early with a bucket-specific error instead of failing later in the background worker.

### Long-run transient transport failures

Confirmed during live multi-chunk validation:

- transient network failures are now captured at the chunk level
- the transcription run can complete with partial chunk failure
- the failed chunk can then be retried in place and recovered without rerunning the full meeting
- failed chunk counts and per-chunk error details remain visible in the run payload

## UI And Reviewer Usability

Validated through the worker payloads backing the desktop UI:

- meeting detail can now show a completed live STT run with persisted artifacts
- transcript payload includes speaker-labeled merged segments
- segment timestamps are meeting-relative and ordered
- raw chunk response and merged transcript artifacts are available for inspection

This pass added only the minimum review-surface needed for reliability:

- Transcript view now shows:
  - partial transcript state
  - failed chunk count
  - retry action for failed chunks
  - attempt history per chunk
- Jobs view now surfaces `completed_with_failures` and `recovered` clearly

For the multi-chunk transcript payload:

- merged segment count remained modest (`23`)
- transcript payload size was about `68.5 KB`
- no negative-duration segments were present
- no overlapping merged segments were present
- boundary-adjacent segments remained queryable and ordered across chunk boundaries

This indicates the Transcript tab payload shape should remain usable for larger stitched transcripts in the current desktop UI.

## Remaining Limitations

- `chirp_3` still did not return confidence values in the validated samples, so confidence remains nullable in the UI and persistence layer
- the long-form validation source is sparse and repetitive, so it validates chunk boundaries and long-run stability well, but it is not a semantically rich meeting for transcript quality review
- one returned phrase remains suspiciously model-generated:
  - `in the original language of the speech, English.`
  This appears to come directly from the STT output rather than the stitcher, so it remains a model/output-quality limitation rather than a merge bug

## Production Readiness Assessment

Current assessment:

- real Google STT V2 activation: working
- credentials-file mode in the real worker runtime: working
- bucket reachability and write preflight: working
- raw response persistence: working
- merged transcript generation: working
- meeting-relative timestamp persistence: working
- early failure messaging for key STT misconfigurations: improved and confirmed
- multi-chunk live transcription: working
- chunk-level retry and recovery: working
- long-run SQLite contention under polling: hardened
- real-word timing corruption from STT output: substantially hardened in parsing and stitching

Conclusion:

The STT layer is now **working and materially closer to production-ready** for real short meetings and for long-form multi-chunk meetings, including targeted recovery from transient chunk failures.

The live long-form validation now completed successfully after targeted chunk recovery, so the primary reliability gap from the earlier pass has been closed.

Before calling the STT layer fully production-ready for broad release, the next recommended work is:

1. run one richer multi-speaker real meeting through the same path
2. confirm transcript review ergonomics on a longer, denser transcript in the desktop UI
3. proceed to export only after reviewing one full realistic meeting end to end in the reviewer workflow
