import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { AlertTriangle, ArrowLeft, ChevronDown, Mic2, Play, Sparkles, Trash2 } from 'lucide-react'
import { api } from '@/lib/api'
import { formatBytes, formatDate, formatDateTime, formatDuration, formatPercent } from '@/lib/format'
import { Panel } from '@/components/Panel'
import { StatusBadge } from '@/components/StatusBadge'
import { ExportTab } from './ExportTab'
import { InsightsTab } from './InsightsTab'
import type { ArtifactRecord, CreateExportRequest, MeetingDetail, TranscriptPayload, TranscriptSegmentRecord } from '@shared/contracts/api'

const transcriptReadyStatuses = ['completed', 'completed_with_failures', 'recovered'] as const

function isTranscriptReadyStatus(status: string | null | undefined) {
  return !!status && (transcriptReadyStatuses as readonly string[]).includes(status)
}

export function MeetingDetailPage() {
  const { meetingId } = useParams()
  const parsedMeetingId = Number(meetingId)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [transcriptSearch, setTranscriptSearch] = useState('')
  const [speakerFilter, setSpeakerFilter] = useState('all')
  const [highlightedSegmentId, setHighlightedSegmentId] = useState<number | null>(null)

  const meetingQuery = useQuery({
    queryKey: ['meeting', parsedMeetingId],
    queryFn: () => api.getMeeting(parsedMeetingId),
    enabled: Number.isFinite(parsedMeetingId),
    refetchInterval: 4_000,
  })

  const meeting = meetingQuery.data

  const transcriptQuery = useQuery({
    queryKey: ['transcript', parsedMeetingId],
    queryFn: () => api.getTranscript(parsedMeetingId),
    enabled:
      Number.isFinite(parsedMeetingId) &&
      !!meeting?.latest_transcription_run &&
      isTranscriptReadyStatus(meeting.latest_transcription_run.status),
  })

  const insightsQuery = useQuery({
    queryKey: ['insights', parsedMeetingId],
    queryFn: () => api.getInsights(parsedMeetingId),
    enabled: Number.isFinite(parsedMeetingId) && meeting?.latest_extraction_run?.status === 'completed',
  })

  const exportsQuery = useQuery({
    queryKey: ['exports', parsedMeetingId],
    queryFn: () => api.listExports(parsedMeetingId),
    enabled: Number.isFinite(parsedMeetingId),
  })

  const preprocessMutation = useMutation({
    mutationFn: () => api.startPreprocess(parsedMeetingId),
    onSuccess: async () => invalidateWorkspace(queryClient, parsedMeetingId),
  })
  const transcriptionMutation = useMutation({
    mutationFn: () => api.startTranscription(parsedMeetingId),
    onSuccess: async () => invalidateWorkspace(queryClient, parsedMeetingId),
  })
  const retryChunksMutation = useMutation({
    mutationFn: (runId: number) => api.retryFailedTranscriptionChunks(runId),
    onSuccess: async () => invalidateWorkspace(queryClient, parsedMeetingId),
  })
  const extractionMutation = useMutation({
    mutationFn: () => api.startExtraction(parsedMeetingId),
    onSuccess: async () => invalidateWorkspace(queryClient, parsedMeetingId),
  })
  const deleteMeetingMutation = useMutation({
    mutationFn: () => api.deleteMeeting(parsedMeetingId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['meetings'] })
      await queryClient.invalidateQueries({ queryKey: ['jobs'] })
      navigate('/meetings')
    },
  })
  const exportMutation = useMutation({
    mutationFn: (payload: CreateExportRequest) => api.createExport(parsedMeetingId, payload),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['exports', parsedMeetingId] }),
  })
  const openExportFolderMutation = useMutation({
    mutationFn: (exportRunId: number) => api.openExportFolder(exportRunId),
  })
  const assignSpeakerMutation = useMutation({
    mutationFn: ({ speakerLabel, speakerName }: { speakerLabel: string; speakerName: string | null }) =>
      api.assignSpeakerName(parsedMeetingId, speakerLabel, speakerName),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['meeting', parsedMeetingId] })
      await queryClient.invalidateQueries({ queryKey: ['transcript', parsedMeetingId] })
    },
  })
  const updateActionMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Record<string, unknown> }) => api.updateAction(id, payload),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['insights', parsedMeetingId] }),
  })
  const updateDecisionMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Record<string, unknown> }) => api.updateDecision(id, payload),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['insights', parsedMeetingId] }),
  })
  const updateRiskMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Record<string, unknown> }) => api.updateRisk(id, payload),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['insights', parsedMeetingId] }),
  })
  const updateQuestionMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Record<string, unknown> }) => api.updateQuestion(id, payload),
    onSuccess: async () => queryClient.invalidateQueries({ queryKey: ['insights', parsedMeetingId] }),
  })

  useEffect(() => {
    if (!highlightedSegmentId) {
      return
    }
    const timer = window.setTimeout(() => {
      document.getElementById(`segment-${highlightedSegmentId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    }, 60)
    return () => window.clearTimeout(timer)
  }, [highlightedSegmentId, transcriptQuery.data])

  if (!Number.isFinite(parsedMeetingId)) {
    return <SimpleState title="Meeting not found" body="The current route does not contain a valid meeting id." />
  }
  if (meetingQuery.isLoading) {
    return <SimpleState title="Loading meeting" body="Refreshing workflow state and review data." />
  }
  if (meetingQuery.isError || !meeting) {
    return (
      <SimpleState
        title="Unable to load meeting"
        body={meetingQuery.error instanceof Error ? meetingQuery.error.message : 'The meeting could not be loaded.'}
      />
    )
  }

  const transcriptPayload = transcriptQuery.data
  const insights = insightsQuery.data
  const exportRuns = exportsQuery.data ?? []
  const integrityIssues = meeting.integrity_issues ?? []
  const sourceBlockingIssue =
    integrityIssues.find(
      (issue) =>
        issue.startsWith('Missing source record') ||
        issue.startsWith('Reference source file missing') ||
        issue.startsWith('Managed source file missing'),
    ) ?? null

  const canPrepare =
    Boolean(meeting.source_file) &&
    !sourceBlockingIssue &&
    meeting.status !== 'preprocessing' &&
    meeting.latest_run?.status !== 'running'
  const canTranscribe =
    meeting.status === 'prepared' &&
    meeting.chunk_count > 0 &&
    meeting.latest_transcription_run?.status !== 'running'
  const canExtract =
    Boolean(meeting.latest_transcription_run) &&
    isTranscriptReadyStatus(meeting.latest_transcription_run?.status) &&
    meeting.latest_extraction_run?.status !== 'running'

  const filteredSegments = useMemo(
    () => filterSegments(transcriptPayload?.segments ?? [], transcriptSearch, speakerFilter),
    [transcriptPayload?.segments, transcriptSearch, speakerFilter],
  )
  const speakers = useMemo(() => buildSpeakers(transcriptPayload), [transcriptPayload])

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <Link to={`/history?meeting=${meeting.id}`} className="inline-flex items-center gap-2 text-sm text-[color:var(--color-muted-strong)] hover:text-slate-100">
            <ArrowLeft className="h-4 w-4" />
            Back to history
          </Link>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight text-slate-50">{meeting.title}</h1>
            <StatusBadge status={meeting.status} />
          </div>
          <p className="mt-2 text-sm text-[color:var(--color-muted-strong)]">
            {meeting.project || 'General'} {meeting.meeting_date ? `· ${formatDate(meeting.meeting_date)}` : ''}
          </p>
        </div>

        <button
          className="inline-flex items-center gap-2 rounded-xl border border-red-500/25 bg-red-500/10 px-3 py-2.5 text-sm font-semibold text-red-100 disabled:cursor-not-allowed disabled:opacity-50"
          disabled={deleteMeetingMutation.isPending || meeting.latest_run?.status === 'running'}
          onClick={() => {
            const message = [
              `Delete "${meeting.title}"?`,
              '',
              'This removes the meeting record and all app-managed local artifacts, runs, logs, chunks, transcript data, insights, and exports.',
              meeting.source_file?.import_mode === 'reference'
                ? 'The original reference-mode source file is preserved.'
                : 'Managed-copy source files stored by the app are also removed.',
            ].join('\n')
            if (window.confirm(message)) {
              deleteMeetingMutation.mutate()
            }
          }}
        >
          <Trash2 className="h-4 w-4" />
          Delete
        </button>
      </div>

      {integrityIssues[0] ? <WarningBanner message={integrityIssues[0]} extra={integrityIssues[1] ? 'More detail is available in Advanced details.' : undefined} /> : null}

      <Panel eyebrow="Workflow" title="Guided Review Path">
        <div className="grid gap-3 md:grid-cols-5">
          <StepCard title="Source imported" status={meeting.source_file ? 'done' : 'blocked'} body={meeting.source_file?.file_name || 'Source metadata missing'} />
          <StepCard
            title="Audio prepared"
            status={meeting.status === 'preprocessing' ? 'active' : meeting.chunk_count > 0 ? 'done' : 'pending'}
            body={meeting.chunk_count > 0 ? `${meeting.chunk_count} chunks ready` : meeting.latest_run?.current_message || 'Waiting to prepare'}
          />
          <StepCard
            title="Transcript ready"
            status={transcriptPayload ? 'done' : meeting.latest_transcription_run?.status === 'running' ? 'active' : 'pending'}
            body={transcriptPayload ? `${transcriptPayload.summary.segment_count} segments` : meeting.latest_transcription_run?.status || 'Waiting'}
          />
          <StepCard
            title="Insights reviewed"
            status={insights ? 'done' : meeting.latest_extraction_run?.status === 'running' ? 'active' : 'pending'}
            body={insights ? `${countPendingReviews(insights)} pending review` : 'Waiting'}
          />
          <StepCard
            title="Export delivered"
            status={exportRuns.some((item) => item.status === 'completed') ? 'done' : 'pending'}
            body={exportRuns[0] ? formatDateTime(exportRuns[0].completed_at || exportRuns[0].created_at) : 'No exports yet'}
          />
        </div>
      </Panel>

      <div className="grid gap-6 xl:grid-cols-[0.95fr_1.05fr]">
        <Panel eyebrow="Overview" title={resolveOverviewTitle(meeting, transcriptPayload, insights)}>
          <div className="space-y-5">
            <p className="text-sm leading-6 text-[color:var(--color-muted-strong)]">
              {resolveOverviewBody(meeting, transcriptPayload, insights, sourceBlockingIssue)}
            </p>
            <div className="flex flex-wrap gap-2">
              {canPrepare ? (
                <ActionButton disabled={preprocessMutation.isPending} onClick={() => preprocessMutation.mutate()}>
                  <Play className="h-4 w-4" />
                  {preprocessMutation.isPending ? 'Starting preparation' : 'Prepare audio'}
                </ActionButton>
              ) : null}
              {canTranscribe ? (
                <ActionButton disabled={transcriptionMutation.isPending} onClick={() => transcriptionMutation.mutate()}>
                  <Mic2 className="h-4 w-4" />
                  {transcriptionMutation.isPending ? 'Queueing transcription' : 'Queue transcription'}
                </ActionButton>
              ) : null}
              {canExtract ? (
                <ActionButton disabled={extractionMutation.isPending} onClick={() => extractionMutation.mutate()}>
                  <Sparkles className="h-4 w-4" />
                  {extractionMutation.isPending ? 'Starting extraction' : 'Run extraction'}
                </ActionButton>
              ) : null}
              {!canPrepare && !canTranscribe && !canExtract ? (
                <MutedBadge>{meeting.latest_run?.current_message || 'Workflow is current'}</MutedBadge>
              ) : null}
            </div>
          </div>
        </Panel>

        <Panel eyebrow="Status" title="Current readiness">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            <MiniStat label="Source" value={meeting.source_file?.file_name ?? 'Unavailable'} />
            <MiniStat label="Duration" value={formatDuration(meeting.source_file?.duration_ms)} />
            <MiniStat label="Chunks" value={`${meeting.chunk_count}`} />
            <MiniStat
              label="Preparation"
              value={
                meeting.latest_run_detail
                  ? `${meeting.latest_run_detail.stage} · ${formatPercent(meeting.latest_run_detail.progress_percent)}`
                  : 'Not started'
              }
            />
            <MiniStat
              label="Transcript"
              value={
                meeting.latest_transcription_run
                  ? `${meeting.latest_transcription_run.completed_chunk_count}/${meeting.latest_transcription_run.chunk_count} chunks`
                  : 'Not started'
              }
            />
            <MiniStat label="Insights" value={meeting.latest_extraction_run?.status || 'Not started'} />
          </div>
        </Panel>
      </div>

      <Panel eyebrow="Transcript Review" title="Readable transcript">
        {!transcriptPayload ? (
          <EmptySection
            title={meeting.latest_transcription_run?.status === 'running' ? 'Transcription in progress' : 'Transcript not ready yet'}
            body={
              meeting.latest_transcription_run?.status === 'running'
                ? 'Chunk transcription is running in the background.'
                : 'The transcript becomes the main review surface once transcription is complete.'
            }
          />
        ) : (
          <div className="space-y-5">
            <div className="grid gap-3 sm:grid-cols-4">
              <MiniStat label="Engine" value={transcriptPayload.transcription_run.engine_model} />
              <MiniStat label="Language" value={transcriptPayload.transcription_run.language_code} />
              <MiniStat label="Segments" value={`${transcriptPayload.summary.segment_count}`} />
              <MiniStat
                label="Average confidence"
                value={
                  transcriptPayload.summary.average_confidence !== null
                    ? `${Math.round(transcriptPayload.summary.average_confidence * 100)}%`
                    : 'N/A'
                }
              />
            </div>

            <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_300px]">
              <div className="space-y-4">
                <div className="flex flex-wrap items-center gap-3">
                  <input
                    value={transcriptSearch}
                    onChange={(event) => setTranscriptSearch(event.target.value)}
                    placeholder="Search transcript"
                    className="min-w-[220px] flex-1 rounded-xl border border-[color:var(--color-border)] bg-slate-950/60 px-4 py-3 text-sm text-slate-100 outline-none placeholder:text-slate-500"
                  />
                  <select
                    value={speakerFilter}
                    onChange={(event) => setSpeakerFilter(event.target.value)}
                    className="rounded-xl border border-[color:var(--color-border)] bg-slate-950/60 px-4 py-3 text-sm text-slate-100 outline-none"
                  >
                    <option value="all">All speakers</option>
                    {speakers.map((speaker) => (
                      <option key={speaker.value} value={speaker.value}>
                        {speaker.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="space-y-3">
                  {filteredSegments.length === 0 ? (
                    <EmptySection title="No transcript segments match the filters" body="Try a broader search or switch the speaker filter back to all speakers." />
                  ) : (
                    filteredSegments.map((segment) => (
                      <TranscriptCard key={segment.id} segment={segment} highlighted={segment.id === highlightedSegmentId} />
                    ))
                  )}
                </div>
              </div>

              <div className="space-y-4">
                <Panel eyebrow="Speakers" title="Assignment">
                  {speakers.length === 0 ? (
                    <EmptySection title="No speaker labels" body="Speaker assignment appears here when diarization labels are available." compact />
                  ) : (
                    <div className="space-y-3">
                      {speakers.map((speaker) => (
                        <SpeakerRow
                          key={speaker.value}
                          speakerLabel={speaker.value}
                          speakerName={speaker.name}
                          disabled={assignSpeakerMutation.isPending}
                          onSave={(nextName) =>
                            assignSpeakerMutation.mutate({ speakerLabel: speaker.value, speakerName: nextName })
                          }
                        />
                      ))}
                    </div>
                  )}
                </Panel>

                {meeting.latest_transcription_run && meeting.latest_transcription_run.failed_chunk_count > 0 ? (
                  <Panel eyebrow="Recovery" title="Retry failed chunks">
                    <p className="text-sm leading-6 text-[color:var(--color-muted-strong)]">
                      Retry only the failed transcription requests without rerunning successful chunks.
                    </p>
                    <button
                      onClick={() => retryChunksMutation.mutate(meeting.latest_transcription_run!.id)}
                      disabled={retryChunksMutation.isPending}
                      className="mt-4 inline-flex items-center gap-2 rounded-xl bg-cyan-400 px-4 py-2.5 text-sm font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <Mic2 className="h-4 w-4" />
                      {retryChunksMutation.isPending ? 'Retrying failed chunks' : 'Retry failed chunks'}
                    </button>
                  </Panel>
                ) : null}
              </div>
            </div>
          </div>
        )}
      </Panel>

      <Panel eyebrow="Insights Review" title="Evidence-backed output">
        {!transcriptPayload ? (
          <EmptySection title="Insights depend on transcription" body="Once transcription is complete, you can run evidence-backed extraction from the stored merged transcript." />
        ) : !insights ? (
          <EmptySection
            title={meeting.latest_extraction_run?.status === 'running' ? 'Extraction in progress' : 'Insights not generated yet'}
            body={
              meeting.latest_extraction_run?.status === 'running'
                ? 'Extraction is currently running in the background.'
                : 'Run extraction to create structured minutes, actions, decisions, risks, and questions with evidence.'
            }
          />
        ) : (
          <InsightsTab
            insights={insights}
            latestRun={meeting.latest_extraction_run}
            onJumpToEvidence={(segmentId) => setHighlightedSegmentId(segmentId)}
            onUpdateAction={(id, payload) => updateActionMutation.mutate({ id, payload })}
            onUpdateDecision={(id, payload) => updateDecisionMutation.mutate({ id, payload })}
            onUpdateRisk={(id, payload) => updateRiskMutation.mutate({ id, payload })}
            onUpdateQuestion={(id, payload) => updateQuestionMutation.mutate({ id, payload })}
            onBulkAcceptActions={(ids) => {
              void Promise.all(ids.map((id) => api.updateAction(id, { review_status: 'accepted' }))).then(async () => {
                await queryClient.invalidateQueries({ queryKey: ['insights', parsedMeetingId] })
              })
            }}
          />
        )}
      </Panel>

      <Panel eyebrow="Export" title="Delivery">
        <ExportTab
          meeting={meeting}
          exports={exportRuns}
          exportPending={exportMutation.isPending}
          onCreateExport={(payload) => exportMutation.mutate(payload)}
          onOpenFolder={(exportRunId) => openExportFolderMutation.mutate(exportRunId)}
        />
      </Panel>

      <AdvancedDetails title="Advanced details">
        <div className="grid gap-6 xl:grid-cols-2">
          <Panel eyebrow="Source" title="Technical source details">
            {meeting.source_file ? (
              <div className="space-y-3 text-sm text-[color:var(--color-muted-strong)]">
                <KeyValue label="Original path" value={meeting.source_file.original_path} breakAll />
                <KeyValue label="Managed copy" value={meeting.source_file.managed_copy_path || '-'} breakAll />
                <KeyValue label="Normalized audio" value={meeting.source_file.normalized_audio_path || '-'} breakAll />
                <KeyValue label="Import mode" value={meeting.source_file.import_mode} />
                <KeyValue label="Size" value={formatBytes(meeting.source_file.size_bytes)} />
                <KeyValue label="Checksum" value={meeting.source_file.sha256} breakAll />
              </div>
            ) : (
              <EmptySection title="Source metadata missing" body="The meeting is still viewable and deletable, but technical source details are incomplete." compact />
            )}
          </Panel>

          <Panel eyebrow="Pipeline" title="Runs and artifacts">
            <div className="space-y-3 text-sm text-[color:var(--color-muted-strong)]">
              <KeyValue label="Latest job" value={meeting.latest_run ? `${meeting.latest_run.job_type} / ${meeting.latest_run.status}` : '-'} />
              <KeyValue
                label="Preparation"
                value={
                  meeting.latest_run_detail
                    ? `${meeting.latest_run_detail.stage} / ${formatPercent(meeting.latest_run_detail.progress_percent)}`
                    : '-'
                }
              />
              <KeyValue
                label="Transcription"
                value={meeting.latest_transcription_run ? `${meeting.latest_transcription_run.status} / ${meeting.latest_transcription_run.engine_model}` : '-'}
              />
              <KeyValue label="Artifacts" value={`${meeting.artifacts.length}`} />
            </div>
          </Panel>
        </div>

        <Panel eyebrow="Artifacts" title="Tracked files" className="mt-6">
          <ArtifactList artifacts={meeting.artifacts} />
        </Panel>
      </AdvancedDetails>
    </div>
  )
}

async function invalidateWorkspace(queryClient: ReturnType<typeof useQueryClient>, meetingId: number) {
  await Promise.all([
    queryClient.invalidateQueries({ queryKey: ['meeting', meetingId] }),
    queryClient.invalidateQueries({ queryKey: ['meetings'] }),
    queryClient.invalidateQueries({ queryKey: ['jobs'] }),
    queryClient.invalidateQueries({ queryKey: ['transcript', meetingId] }),
    queryClient.invalidateQueries({ queryKey: ['insights', meetingId] }),
    queryClient.invalidateQueries({ queryKey: ['exports', meetingId] }),
  ])
}

function resolveOverviewTitle(meeting: MeetingDetail, transcriptPayload: TranscriptPayload | undefined, insights: unknown) {
  if (!meeting.source_file) return 'Repair source metadata before continuing'
  if (meeting.status === 'imported' || meeting.status === 'draft') return 'Prepare audio into chunk-ready working files'
  if (meeting.status === 'preprocessing') return 'Audio preparation is currently running'
  if (!transcriptPayload) return 'Transcribe the prepared chunks into a merged transcript'
  if (!insights) return 'Generate evidence-backed insights from the transcript'
  return 'Review insights and deliver an export'
}

function resolveOverviewBody(
  meeting: MeetingDetail,
  transcriptPayload: TranscriptPayload | undefined,
  insights: unknown,
  sourceBlockingIssue: string | null,
) {
  if (sourceBlockingIssue) return sourceBlockingIssue
  if (!meeting.source_file) return 'The meeting remains accessible, but source records are incomplete and pipeline actions are blocked.'
  if (meeting.status === 'imported' || meeting.status === 'draft') {
    return 'Preparation creates a normalized local working copy, silence analysis, and the chunk plan used for background transcription.'
  }
  if (meeting.status === 'preprocessing') return meeting.latest_run?.current_message || 'The worker is preparing audio and chunk artifacts.'
  if (!transcriptPayload) return 'Preparation is complete. The next meaningful step is transcription and transcript review.'
  if (!insights) return 'The transcript is ready. Run extraction to create reviewable minutes, actions, decisions, risks, and questions.'
  return 'Transcript, insights, and export tooling are all available from this review workspace.'
}

function filterSegments(segments: TranscriptSegmentRecord[], search: string, speakerFilter: string) {
  const query = search.trim().toLowerCase()
  return segments.filter((segment) => {
    const speakerValue = segment.speaker_name || segment.speaker_label || 'Unlabeled speaker'
    const matchesSpeaker = speakerFilter === 'all' ? true : speakerValue === speakerFilter
    const matchesSearch = query
      ? [segment.text, segment.speaker_name || '', segment.speaker_label || ''].join(' ').toLowerCase().includes(query)
      : true
    return matchesSpeaker && matchesSearch
  })
}

function buildSpeakers(transcriptPayload: TranscriptPayload | undefined) {
  if (!transcriptPayload) return []
  const speakers = new Map<string, { value: string; label: string; name: string | null }>()
  for (const segment of transcriptPayload.segments) {
    const key = segment.speaker_name || segment.speaker_label
    if (!key || speakers.has(key)) continue
    speakers.set(key, {
      value: key,
      label: segment.speaker_name ? `${segment.speaker_name} (${segment.speaker_label || 'speaker'})` : key,
      name: segment.speaker_name,
    })
  }
  return Array.from(speakers.values())
}

function countPendingReviews(insights: NonNullable<Awaited<ReturnType<typeof api.getInsights>>>) {
  return [...insights.actions, ...insights.decisions, ...insights.risks, ...insights.questions].filter(
    (item) => item.review_status !== 'accepted',
  ).length
}

function SimpleState({ title, body }: { title: string; body: string }) {
  return (
    <Panel title={title}>
      <p className="text-sm leading-6 text-[color:var(--color-muted-strong)]">{body}</p>
    </Panel>
  )
}

function WarningBanner({ message, extra }: { message: string; extra?: string }) {
  return (
    <div className="rounded-2xl border border-amber-500/25 bg-amber-500/8 px-5 py-4">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-200" />
        <div>
          <p className="text-sm font-semibold text-amber-100">Integrity or runtime warning</p>
          <p className="mt-1 text-sm leading-6 text-amber-50/90">{message}</p>
          {extra ? <p className="mt-2 text-xs uppercase tracking-[0.14em] text-amber-200/80">{extra}</p> : null}
        </div>
      </div>
    </div>
  )
}

function StepCard({ title, status, body }: { title: string; status: 'done' | 'active' | 'pending' | 'blocked'; body: string }) {
  const badgeStatus = status === 'done' ? 'completed' : status === 'active' ? 'running' : status === 'blocked' ? 'failed' : 'pending'
  const surface =
    status === 'done'
      ? 'border-emerald-500/25 bg-emerald-500/8'
      : status === 'active'
        ? 'border-cyan-400/25 bg-cyan-400/8'
        : status === 'blocked'
          ? 'border-red-500/25 bg-red-500/8'
          : 'border-[color:var(--color-border)] bg-slate-950/30'
  return (
    <div className={`rounded-2xl border p-4 ${surface}`}>
      <div className="flex items-center justify-between gap-3">
        <p className="text-sm font-semibold text-slate-100">{title}</p>
        <StatusBadge status={badgeStatus} />
      </div>
      <p className="mt-3 text-sm leading-6 text-[color:var(--color-muted-strong)]">{body}</p>
    </div>
  )
}

function ActionButton({ children, onClick, disabled }: { children: ReactNode; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="inline-flex items-center gap-2 rounded-xl bg-cyan-400 px-4 py-2.5 text-sm font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {children}
    </button>
  )
}

function MutedBadge({ children }: { children: ReactNode }) {
  return <div className="rounded-xl border border-[color:var(--color-border)] bg-slate-950/50 px-4 py-2.5 text-sm text-slate-200">{children}</div>
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-[color:var(--color-border)] bg-slate-950/35 px-4 py-3">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[color:var(--color-muted)]">{label}</p>
      <p className="mt-2 text-sm font-semibold text-slate-100">{value}</p>
    </div>
  )
}

function EmptySection({ title, body, compact = false }: { title: string; body: string; compact?: boolean }) {
  return (
    <div className={`rounded-2xl border border-dashed border-[color:var(--color-border-strong)] bg-slate-950/25 text-center ${compact ? 'px-5 py-8' : 'px-8 py-14'}`}>
      <p className="text-sm font-semibold text-slate-100">{title}</p>
      <p className="mx-auto mt-3 max-w-3xl text-sm leading-6 text-[color:var(--color-muted)]">{body}</p>
    </div>
  )
}

function TranscriptCard({ segment, highlighted }: { segment: TranscriptSegmentRecord; highlighted: boolean }) {
  const speakerName = segment.speaker_name || segment.speaker_label || 'Unlabeled speaker'
  return (
    <article
      id={`segment-${segment.id}`}
      className={[
        'rounded-2xl border px-5 py-4',
        highlighted ? 'border-cyan-300/60 bg-cyan-400/8' : 'border-[color:var(--color-border)] bg-slate-950/35',
      ].join(' ')}
    >
      <div className="flex flex-wrap items-center gap-3">
        <span className="rounded-full border border-[color:var(--color-border)] px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-100">
          {formatDuration(segment.start_ms_in_meeting)} - {formatDuration(segment.end_ms_in_meeting)}
        </span>
        <span className="text-sm font-semibold text-slate-100">{speakerName}</span>
        {segment.confidence !== null && segment.confidence < 0.75 ? (
          <span className="rounded-full bg-amber-500/12 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-amber-100">
            Low confidence
          </span>
        ) : null}
      </div>
      <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-slate-100">{segment.text}</p>
    </article>
  )
}

function SpeakerRow({
  speakerLabel,
  speakerName,
  disabled,
  onSave,
}: {
  speakerLabel: string
  speakerName: string | null
  disabled: boolean
  onSave: (speakerName: string | null) => void
}) {
  const [value, setValue] = useState(speakerName || '')
  useEffect(() => {
    setValue(speakerName || '')
  }, [speakerName])
  return (
    <div className="rounded-2xl border border-[color:var(--color-border)] bg-slate-950/35 p-3">
      <p className="text-sm font-semibold text-slate-100">{speakerLabel}</p>
      <div className="mt-3 flex items-center gap-2">
        <input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Readable speaker name"
          className="min-w-0 flex-1 rounded-xl border border-[color:var(--color-border)] bg-slate-950/60 px-3 py-2.5 text-sm text-slate-100 outline-none"
        />
        <button
          onClick={() => onSave(value.trim() || null)}
          disabled={disabled}
          className="rounded-xl bg-cyan-400 px-3 py-2.5 text-xs font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Save
        </button>
      </div>
    </div>
  )
}

function AdvancedDetails({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="group rounded-2xl border border-[color:var(--color-border)] bg-slate-950/20">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-5 py-4">
        <div>
          <p className="text-sm font-semibold text-slate-100">{title}</p>
          <p className="mt-1 text-sm text-[color:var(--color-muted-strong)]">Logs, paths, artifacts, and pipeline internals stay available here when needed.</p>
        </div>
        <ChevronDown className="h-4 w-4 text-[color:var(--color-muted)] transition group-open:rotate-180" />
      </summary>
      <div className="border-t border-[color:var(--color-border)] px-5 py-5">{children}</div>
    </details>
  )
}

function KeyValue({ label, value, breakAll = false }: { label: string; value: string; breakAll?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-xl border border-[color:var(--color-border)] bg-slate-950/35 px-4 py-3">
      <span className="text-[color:var(--color-muted)]">{label}</span>
      <span className={`text-right font-medium text-slate-100 ${breakAll ? 'break-all' : ''}`}>{value}</span>
    </div>
  )
}

function ArtifactList({ artifacts }: { artifacts: ArtifactRecord[] }) {
  if (artifacts.length === 0) {
    return <EmptySection title="No artifacts yet" body="Tracked files will appear here when pipeline stages generate them." compact />
  }
  return (
    <div className="space-y-3">
      {artifacts.map((artifact) => (
        <div key={artifact.id} className="rounded-2xl border border-[color:var(--color-border)] bg-slate-950/35 p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-slate-100">
                {artifact.role} <span className="text-[color:var(--color-muted)]">· {artifact.artifact_type}</span>
              </p>
              <p className="mt-1 break-all text-xs text-[color:var(--color-muted-strong)]">{artifact.path}</p>
            </div>
            <div className="text-right text-xs text-[color:var(--color-muted)]">
              <p>{artifact.size_bytes ? formatBytes(artifact.size_bytes) : '-'}</p>
              <p>{formatDateTime(artifact.created_at)}</p>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}
