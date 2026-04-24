import type {
  ArtifactRecord,
  ChunkRecord,
  CreateExportRequest,
  DeleteMeetingResponse,
  ExportRunRecord,
  HealthResponse,
  ImportMeetingRequest,
  ImportMeetingResponse,
  ImportSourceInspection,
  InsightsPayload,
  JobSummary,
  MeetingDetail,
  MeetingSummary,
  PreprocessingRunDetail,
  SettingsRecord,
  StartExtractionResponse,
  StartPreprocessResponse,
  StartTranscriptionResponse,
  TranscriptPayload,
  TranscriptionRunDetail,
  UpdateSpeakerResponse,
  UpdateTranscriptSegmentsRequest,
  UpdateTranscriptSegmentsResponse,
} from '@shared/contracts/api'

const API_BASE = 'http://127.0.0.1:8765/api/v1'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  })

  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || `Request failed: ${response.status}`)
  }

  return response.json() as Promise<T>
}

export const api = {
  health: () => request<HealthResponse>('/health'),
  listMeetings: () => request<MeetingSummary[]>('/meetings'),
  getMeeting: (meetingId: number) => request<MeetingDetail>(`/meetings/${meetingId}`),
  deleteMeeting: (meetingId: number) =>
    request<DeleteMeetingResponse>(`/meetings/${meetingId}`, {
      method: 'DELETE',
    }),
  importMeeting: (payload: ImportMeetingRequest) =>
    request<ImportMeetingResponse>('/meetings/import', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  inspectImportSource: (source_path: string) =>
    request<ImportSourceInspection>('/imports/inspect', {
      method: 'POST',
      body: JSON.stringify({ source_path }),
    }),
  startPreprocess: (meetingId: number) =>
    request<StartPreprocessResponse>(`/meetings/${meetingId}/preprocess`, {
      method: 'POST',
    }),
  getLatestRun: (meetingId: number) =>
    request<PreprocessingRunDetail | null>(`/meetings/${meetingId}/preprocessing`),
  getLatestTranscriptionRun: (meetingId: number) =>
    request<TranscriptionRunDetail | null>(`/meetings/${meetingId}/transcription`),
  getTranscript: (meetingId: number) => request<TranscriptPayload>(`/meetings/${meetingId}/transcript`),
  assignSpeakerName: (meetingId: number, speakerLabel: string, speaker_name: string | null) =>
    request<UpdateSpeakerResponse>(`/meetings/${meetingId}/speakers/${encodeURIComponent(speakerLabel)}`, {
      method: 'PATCH',
      body: JSON.stringify({ speaker_name }),
    }),
  updateTranscriptSegments: (meetingId: number, payload: UpdateTranscriptSegmentsRequest) =>
    request<UpdateTranscriptSegmentsResponse>(`/meetings/${meetingId}/transcript-segments`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    }),
  getChunks: (meetingId: number) => request<ChunkRecord[]>(`/meetings/${meetingId}/chunks`),
  getArtifacts: (meetingId: number) =>
    request<ArtifactRecord[]>(`/meetings/${meetingId}/artifacts`),
  startTranscription: (meetingId: number) =>
    request<StartTranscriptionResponse>(`/meetings/${meetingId}/transcribe`, {
      method: 'POST',
    }),
  retryFailedTranscriptionChunks: (runId: number, chunk_ids?: number[]) =>
    request<StartTranscriptionResponse>(`/transcription-runs/${runId}/retry-failed`, {
      method: 'POST',
      body: JSON.stringify({ chunk_ids }),
    }),
  startExtraction: (meetingId: number) =>
    request<StartExtractionResponse>(`/meetings/${meetingId}/extract`, {
      method: 'POST',
    }),
  listJobs: () => request<JobSummary[]>('/jobs'),
  deleteJob: (runId: number) =>
    request<{ status: string; run_id: number }>(`/jobs/${runId}`, {
      method: 'DELETE',
    }),
  listTranscriptionRuns: () => request<TranscriptionRunDetail[]>('/transcription-runs'),
  getTranscriptionRun: (runId: number) => request<TranscriptionRunDetail>(`/transcription-runs/${runId}`),
  getExtraction: (meetingId: number) => request<{ run: unknown; insights: InsightsPayload } | null>(`/meetings/${meetingId}/extraction`),
  getInsights: (meetingId: number) => request<InsightsPayload>(`/meetings/${meetingId}/insights`),
  updateAction: (id: number, payload: Record<string, unknown>) =>
    request(`/insights/actions/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  updateDecision: (id: number, payload: Record<string, unknown>) =>
    request(`/insights/decisions/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  updateRisk: (id: number, payload: Record<string, unknown>) =>
    request(`/insights/risks/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  updateQuestion: (id: number, payload: Record<string, unknown>) =>
    request(`/insights/questions/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  createExport: (meetingId: number, payload: CreateExportRequest) =>
    request<ExportRunRecord>(`/meetings/${meetingId}/exports`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  listExports: (meetingId: number) => request<ExportRunRecord[]>(`/meetings/${meetingId}/exports`),
  getExportRun: (exportRunId: number) => request<ExportRunRecord>(`/export-runs/${exportRunId}`),
  openExportFolder: (exportRunId: number) =>
    request<{ status: string; folder_path: string }>(`/export-runs/${exportRunId}/open-folder`, {
      method: 'POST',
    }),
  getSettings: () => request<SettingsRecord[]>('/settings'),
  updateSetting: (key: string, value_json: Record<string, unknown>) =>
    request<SettingsRecord>(`/settings/${key}`, {
      method: 'PUT',
      body: JSON.stringify({ value_json }),
    }),
}
