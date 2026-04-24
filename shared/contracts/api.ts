export type MeetingStatus =
  | 'draft'
  | 'imported'
  | 'preprocessing'
  | 'prepared'
  | 'transcribing'
  | 'transcribed'
  | 'extracting'
  | 'failed'

export type RunStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled'
export type TranscriptionRunStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'completed_with_failures'
  | 'recovered'
  | 'failed'
export type ExtractionRunStatus = 'pending' | 'running' | 'completed' | 'failed'
export type JobType = 'preprocess' | 'transcribe' | 'extract'
export type ReviewStatus = 'pending' | 'accepted' | 'rejected'
export type ExportProfile = 'formal_minutes_pack' | 'action_register' | 'full_archive' | 'transcript_export'
export type ExportFormat = 'docx' | 'pdf' | 'csv' | 'xlsx' | 'json' | 'txt'

export type RunStage =
  | 'queued'
  | 'probing'
  | 'normalizing'
  | 'analyzing_silence'
  | 'planning_chunks'
  | 'writing_chunks'
  | 'finalizing'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'transcribing_chunks'
  | 'stitching'
  | 'preparing_context'
  | 'extracting_evidence'
  | 'validating_evidence'
  | 'generating_minutes'

export type ChunkStatus = 'prepared' | 'failed'
export type ImportMode = 'reference' | 'managed_copy'

export interface SourceFileSummary {
  id: number
  meeting_id: number
  import_mode: ImportMode
  original_path: string
  managed_copy_path: string | null
  normalized_audio_path: string | null
  file_name: string
  extension: string
  mime_type: string
  media_type: string
  size_bytes: number
  sha256: string
  duration_ms: number
  sample_rate: number | null
  channels: number | null
  created_at: string
}

export interface JobSummary {
  id: number
  meeting_id: number
  meeting_title: string
  job_type: JobType
  status: string
  stage: string
  progress_percent: number
  current_message: string | null
  started_at: string | null
  completed_at: string | null
  error_message: string | null
  created_at: string
}

export interface IntegritySummary {
  meeting_count: number
  orphan_meeting_count: number
  missing_source_path_count: number
  missing_chunk_file_count: number
  stale_job_link_count: number
}

export interface ArtifactRecord {
  id: number
  meeting_id: number
  preprocessing_run_id: number | null
  transcription_run_id: number | null
  extraction_run_id: number | null
  artifact_type: string
  role: string
  path: string
  mime_type: string | null
  sha256: string | null
  size_bytes: number | null
  metadata_json: Record<string, unknown>
  created_at: string
}

export interface ChunkRecord {
  id: number
  meeting_id: number
  preprocessing_run_id: number
  chunk_index: number
  file_path: string
  sha256: string
  start_ms: number
  end_ms: number
  overlap_before_ms: number
  overlap_after_ms: number
  duration_ms: number
  boundary_reason: string
  status: ChunkStatus
  created_at: string
}

export interface ChunkTranscriptRecord {
  id: number
  meeting_id: number
  chunk_id: number
  transcription_run_id: number
  engine: string
  engine_model: string
  status: string
  transcript_text: string
  raw_response_json: Record<string, unknown>
  average_confidence: number | null
  started_at: string | null
  completed_at: string | null
  error_message: string | null
  request_config_json: Record<string, unknown>
  chunk_index?: number
  start_ms?: number
  end_ms?: number
  overlap_before_ms?: number
  overlap_after_ms?: number
  attempt_count?: number
  retryable?: boolean
  attempts?: ChunkTranscriptAttemptRecord[]
}

export interface ChunkTranscriptAttemptRecord {
  id: number
  meeting_id: number
  chunk_id: number
  transcription_run_id: number
  chunk_transcript_id: number | null
  attempt_number: number
  retried_from_attempt_id: number | null
  engine: string
  engine_model: string
  status: string
  transcript_text: string
  raw_response_json: Record<string, unknown>
  average_confidence: number | null
  started_at: string | null
  completed_at: string | null
  error_message: string | null
  request_config_json: Record<string, unknown>
  created_at: string
  chunk_index?: number
}

export interface TranscriptSegmentRecord {
  id: number
  meeting_id: number
  transcription_run_id: number
  chunk_id: number | null
  segment_index: number
  speaker_label: string | null
  speaker_name: string | null
  text: string
  start_ms_in_meeting: number
  end_ms_in_meeting: number
  start_ms_in_chunk: number | null
  end_ms_in_chunk: number | null
  confidence: number | null
  excluded_from_review: boolean
  exclusion_reason?: string | null
  source_type: 'chunk_raw' | 'merged'
  created_at: string
}

export interface TranscriptWordRecord {
  id: number
  meeting_id: number
  transcription_run_id: number
  chunk_id: number
  segment_id: number | null
  word_index: number
  word_text: string
  start_ms_in_meeting: number
  end_ms_in_meeting: number
  start_ms_in_chunk: number | null
  end_ms_in_chunk: number | null
  speaker_label: string | null
  confidence: number | null
  created_at: string
}

export interface EvidenceLinkRecord {
  id: number
  extraction_run_id: number
  entity_type: string
  entity_id: number
  transcript_segment_id: number | null
  start_ms: number
  end_ms: number
  speaker_label: string | null
  quote_snippet: string | null
  confidence: number | null
}

export interface ExtractionBaseItem {
  id: number
  extraction_run_id: number
  meeting_id: number
  text: string
  confidence: number
  explicit_or_inferred: 'explicit' | 'inferred'
  review_status: ReviewStatus
  needs_review?: boolean
  review_hints?: string[]
  evidence_count?: number
  created_at: string
  updated_at: string
  evidence: EvidenceLinkRecord[]
}

export interface ExtractedActionRecord extends ExtractionBaseItem {
  owner: string | null
  due_date: string | null
  priority: string | null
}

export type ExtractedDecisionRecord = ExtractionBaseItem
export type ExtractedRiskRecord = ExtractionBaseItem
export type ExtractedQuestionRecord = ExtractionBaseItem
export type ExtractedTopicRecord = ExtractionBaseItem

export interface ExtractedSummaryRecord {
  id: number
  extraction_run_id: number
  meeting_id: number
  summary_text: string
  minutes_text: string
  created_at: string
}

export interface PreprocessingRunDetail {
  id: number
  meeting_id: number
  job_run_id?: number | null
  started_at: string | null
  completed_at: string | null
  status: RunStatus
  stage: RunStage
  progress_percent: number
  current_message: string | null
  worker_version: string
  normalized_format: string | null
  normalized_sample_rate: number | null
  normalized_channels: number | null
  log_json: Array<Record<string, unknown>>
  silence_map_json: Record<string, unknown> | null
  chunking_strategy_json: Record<string, unknown>
  waveform_summary_json: Record<string, unknown> | null
  error_message: string | null
  retry_of_run_id: number | null
  cancel_requested_at: string | null
  created_at: string
  artifacts: ArtifactRecord[]
}

export interface TranscriptionRunDetail {
  id: number
  meeting_id: number
  preprocessing_run_id: number | null
  job_run_id: number | null
  engine: string
  engine_model: string
  language_code: string
  diarization_enabled: boolean
  automatic_punctuation_enabled: boolean
  status: TranscriptionRunStatus
  started_at: string | null
  completed_at: string | null
  chunk_count: number
  completed_chunk_count: number
  failed_chunk_count: number
  average_confidence: number | null
  error_message: string | null
  config_json: Record<string, unknown>
  created_at: string
  artifacts: ArtifactRecord[]
  chunk_transcripts: ChunkTranscriptRecord[]
  merged_segments: TranscriptSegmentRecord[]
  retryable_chunk_ids?: number[]
  has_partial_transcript?: boolean
  transcript_completeness?: 'partial' | 'complete'
  meeting_title?: string
}

export interface ExtractionRunDetail {
  id: number
  meeting_id: number
  transcription_run_id: number
  job_run_id: number
  model: string
  model_version: string
  status: ExtractionRunStatus
  started_at: string | null
  completed_at: string | null
  config_json: Record<string, unknown>
  error_message: string | null
  created_at: string
  artifacts: ArtifactRecord[]
  summary: ExtractedSummaryRecord | null
  actions: ExtractedActionRecord[]
}

export interface MeetingSummary {
  id: number
  title: string
  meeting_date: string | null
  project: string | null
  notes: string | null
  attendees: string[]
  circulation: string[]
  status: MeetingStatus
  created_at: string
  updated_at: string
  source_file: SourceFileSummary | null
  chunk_count: number
  latest_run: JobSummary | null
  integrity_issues: string[]
}

export interface MeetingDetail extends MeetingSummary {
  latest_run_detail: PreprocessingRunDetail | null
  latest_transcription_run: TranscriptionRunDetail | null
  latest_extraction_run: ExtractionRunDetail | null
  chunks: ChunkRecord[]
  artifacts: ArtifactRecord[]
}

export interface TranscriptPayload {
  meeting_id: number
  transcription_run: TranscriptionRunDetail
  segments: TranscriptSegmentRecord[]
  words: TranscriptWordRecord[]
  summary: {
    segment_count: number
    included_segment_count: number
    excluded_segment_count: number
    word_count: number
    speaker_labels: string[]
    average_confidence: number | null
  }
}

export interface InsightsPayload {
  run: ExtractionRunDetail
  summary: ExtractedSummaryRecord | null
  actions: ExtractedActionRecord[]
  decisions: ExtractedDecisionRecord[]
  risks: ExtractedRiskRecord[]
  questions: ExtractedQuestionRecord[]
  topics: ExtractedTopicRecord[]
}

export interface HealthResponse {
  status: string
  version: string
  ffmpeg_available: boolean
  ffprobe_available: boolean
  integrity_summary?: IntegritySummary
  speech_dependencies_available?: boolean
  speech_preflight_available?: boolean
  packages?: Record<string, string>
  speech_preflight?: Record<string, unknown>
  speech_preflight_error?: string
  speech_runtime_error?: string
}

export interface ImportMeetingRequest {
  source_path: string
  import_mode: ImportMode
  title?: string
  meeting_date?: string | null
  project?: string | null
  notes?: string | null
  attendees?: string[]
  circulation?: string[]
}

export interface ImportMeetingResponse {
  meeting: MeetingSummary
}

export interface ImportSourceInspection {
  source_path: string
  file_name: string
  meeting_title: string
  meeting_date: string
  created_at: string
  duration_ms: number
  size_bytes: number
  media_type: string
}

export interface UpdateTranscriptSegmentsRequest {
  segment_ids: number[]
  excluded_from_review: boolean
  exclusion_reason?: string | null
}

export interface UpdateTranscriptSegmentsResponse {
  meeting_id: number
  transcription_run_id: number
  updated_segments: number
  excluded_from_review: boolean
  exclusion_reason: string | null
}

export interface StartPreprocessResponse {
  run_id: number
  status: RunStatus
  stage: RunStage
}

export interface StartTranscriptionResponse {
  job_run_id: number
  transcription_run_id: number
  status: TranscriptionRunStatus
  retried_chunk_ids?: number[]
}

export interface StartExtractionResponse {
  job_run_id: number
  extraction_run_id: number
  status: ExtractionRunStatus
}

export interface SettingsRecord {
  key: string
  value_json: Record<string, unknown>
  updated_at: string
}

export interface ExportRunRecord {
  id: number
  meeting_id: number
  export_profile: ExportProfile
  format: ExportFormat
  options_json: {
    reviewed_only: boolean
    include_evidence_appendix: boolean
    include_transcript_appendix: boolean
    include_confidence_flags: boolean
  }
  file_path: string
  status: 'running' | 'completed' | 'failed'
  started_at: string | null
  completed_at: string | null
  error_message: string | null
  created_at: string
}

export interface CreateExportRequest {
  export_profile: ExportProfile
  format: ExportFormat
  reviewed_only: boolean
  include_evidence_appendix: boolean
  include_transcript_appendix: boolean
  include_confidence_flags: boolean
  output_directory?: string | null
}

export interface DeleteMeetingResponse {
  status: string
  meeting_id: number
  deleted_local_files: number
  preserved_reference_original: boolean
}

export interface UpdateInsightRequest {
  text?: string
  owner?: string | null
  due_date?: string | null
  priority?: string | null
  review_status?: ReviewStatus
}

export interface UpdateSpeakerRequest {
  speaker_name?: string | null
}

export interface UpdateSpeakerResponse {
  meeting_id: number
  transcription_run_id: number
  speaker_label: string
  speaker_name: string | null
  updated_segments: number
}
