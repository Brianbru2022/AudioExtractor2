import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { AlertTriangle } from 'lucide-react'
import { api } from '@/lib/api'
import { useUiStore } from '@/store/ui-store'
import { formatBytes, formatDate, formatDateTime, formatDuration, formatPercent } from '@/lib/format'
import { Panel } from '@/components/Panel'
import { StatusBadge } from '@/components/StatusBadge'
import type { ArtifactRecord, MeetingDetail, MeetingSummary, TranscriptPayload, TranscriptSegmentRecord } from '@shared/contracts/api'

export const transcriptReadyStatuses = ['completed', 'completed_with_failures', 'recovered'] as const

export function isTranscriptReadyStatus(status: string | null | undefined) {
  return !!status && (transcriptReadyStatuses as readonly string[]).includes(status)
}

export function useWorkflowMeetings(filter: (meeting: MeetingSummary) => boolean) {
  const [searchParams, setSearchParams] = useSearchParams()
  const lastWorkflowMeetingId = useUiStore((state) => state.lastWorkflowMeetingId)
  const setLastWorkflowMeetingId = useUiStore((state) => state.setLastWorkflowMeetingId)
  const meetingsQuery = useQuery({
    queryKey: ['meetings'],
    queryFn: api.listMeetings,
    refetchInterval: 5_000,
  })

  const meetings = meetingsQuery.data ?? []
  const filteredMeetings = useMemo(() => meetings.filter(filter), [meetings, filter])
  const requestedMeetingId = Number(searchParams.get('meeting'))

  const selectedMeetingId = useMemo(() => {
    if (Number.isFinite(requestedMeetingId)) {
      const requested = filteredMeetings.find((meeting) => meeting.id === requestedMeetingId)
      if (requested) {
        return requested.id
      }
    }
    if (typeof lastWorkflowMeetingId === 'number') {
      const remembered = filteredMeetings.find((meeting) => meeting.id === lastWorkflowMeetingId)
      if (remembered) {
        return remembered.id
      }
    }
    return filteredMeetings[0]?.id ?? null
  }, [filteredMeetings, lastWorkflowMeetingId, requestedMeetingId])

  useEffect(() => {
    if (!selectedMeetingId) {
      return
    }
    setLastWorkflowMeetingId(selectedMeetingId)
  }, [selectedMeetingId, setLastWorkflowMeetingId])

  useEffect(() => {
    if (!selectedMeetingId) {
      return
    }
    if (requestedMeetingId === selectedMeetingId) {
      return
    }
    const next = new URLSearchParams(searchParams)
    next.set('meeting', `${selectedMeetingId}`)
    setSearchParams(next, { replace: true })
  }, [requestedMeetingId, searchParams, selectedMeetingId, setSearchParams])

  const meetingDetailQuery = useQuery({
    queryKey: ['meeting', selectedMeetingId],
    queryFn: () => api.getMeeting(selectedMeetingId as number),
    enabled: typeof selectedMeetingId === 'number',
    refetchInterval: 4_000,
  })

  return {
    meetingsQuery,
    meetings,
    filteredMeetings,
    selectedMeetingId,
    selectedMeeting: meetingDetailQuery.data ?? null,
    meetingDetailQuery,
    selectMeeting: (meetingId: number) => {
      setLastWorkflowMeetingId(meetingId)
      const next = new URLSearchParams(searchParams)
      next.set('meeting', `${meetingId}`)
      setSearchParams(next)
    },
  }
}

export function WorkflowStageLayout({
  title,
  description,
  sidebarTitle,
  emptyTitle,
  emptyBody,
  meetings,
  selectedMeetingId,
  onSelectMeeting,
  selectedMeeting,
  children,
}: {
  title: string
  description: string
  sidebarTitle: string
  emptyTitle: string
  emptyBody: string
  meetings: MeetingSummary[]
  selectedMeetingId: number | null
  onSelectMeeting: (meetingId: number) => void
  selectedMeeting: MeetingDetail | null
  children: ReactNode
}) {
  return (
    <div className="grid gap-6 xl:grid-cols-[330px_minmax(0,1fr)]">
      <div className="space-y-6">
        <Panel eyebrow="Workflow" title={title}>
          <p className="text-sm leading-6 text-[color:var(--color-muted-strong)]">{description}</p>
        </Panel>

        <Panel eyebrow="Queue" title={sidebarTitle}>
          {meetings.length === 0 ? (
            <StageEmptyState title={emptyTitle} body={emptyBody} compact />
          ) : (
            <div className="space-y-3">
              {meetings.map((meeting) => {
                const active = meeting.id === selectedMeetingId
                const issue = meeting.integrity_issues?.[0]
                return (
                  <button
                    key={meeting.id}
                    type="button"
                    onClick={() => onSelectMeeting(meeting.id)}
                    className={[
                      'w-full rounded-2xl border p-4 text-left transition',
                      active
                        ? 'border-cyan-400/35 bg-cyan-400/8'
                        : 'border-[color:var(--color-border)] bg-slate-950/25 hover:bg-slate-950/45',
                    ].join(' ')}
                  >
                    <div className="flex items-center justify-between gap-3">
                      <p className="truncate text-sm font-semibold text-slate-100">{meeting.title}</p>
                      <StatusBadge status={meeting.status} />
                    </div>
                    <p className="mt-1 text-xs text-[color:var(--color-muted)]">
                      {(meeting.project || 'General') + (meeting.meeting_date ? ` · ${formatDate(meeting.meeting_date)}` : '')}
                    </p>
                    <p className="mt-2 text-xs text-[color:var(--color-muted-strong)]">
                      {meeting.source_file
                        ? `${meeting.source_file.file_name} · ${formatDuration(meeting.source_file.duration_ms)}`
                        : 'Source metadata incomplete'}
                    </p>
                    <p className="mt-2 text-xs text-[color:var(--color-muted)]">
                      {meeting.latest_run
                        ? `${meeting.latest_run.stage} · ${formatPercent(meeting.latest_run.progress_percent)}`
                        : `${meeting.chunk_count} chunks`}
                    </p>
                    {issue ? (
                      <div className="mt-2 flex items-start gap-2 text-xs text-amber-200">
                        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                        <span>{issue}</span>
                      </div>
                    ) : null}
                  </button>
                )
              })}
            </div>
          )}
        </Panel>
      </div>

      <div className="min-w-0 space-y-6">
        {!selectedMeeting ? (
          <Panel title="Select a meeting">
            <p className="text-sm leading-6 text-[color:var(--color-muted-strong)]">
              Choose a meeting from the queue to continue with this workflow step.
            </p>
          </Panel>
        ) : (
          <>
            <Panel eyebrow="Selected Meeting" title={selectedMeeting.title}>
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <p className="text-sm text-[color:var(--color-muted-strong)]">
                    {(selectedMeeting.project || 'General') +
                      (selectedMeeting.meeting_date ? ` · ${formatDate(selectedMeeting.meeting_date)}` : '')}
                  </p>
                  <p className="mt-2 text-sm text-[color:var(--color-muted)]">
                    {selectedMeeting.source_file
                      ? `${selectedMeeting.source_file.file_name} · ${formatDuration(selectedMeeting.source_file.duration_ms)}`
                      : 'Source metadata incomplete'}
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <StatusBadge status={selectedMeeting.status} />
                  <Link
                    to={`/meetings/${selectedMeeting.id}`}
                    className="rounded-xl border border-[color:var(--color-border)] px-3 py-2 text-xs font-semibold text-slate-200"
                  >
                    Advanced view
                  </Link>
                </div>
              </div>
            </Panel>
            {children}
          </>
        )}
      </div>
    </div>
  )
}

export function WorkflowWarning({ meeting }: { meeting: MeetingDetail }) {
  const issue = meeting.integrity_issues?.[0]
  if (!issue) {
    return null
  }

  return (
    <div className="rounded-2xl border border-amber-500/25 bg-amber-500/8 px-5 py-4">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-200" />
        <div>
          <p className="text-sm font-semibold text-amber-100">Blocking warning</p>
          <p className="mt-1 text-sm leading-6 text-amber-50/90">{issue}</p>
        </div>
      </div>
    </div>
  )
}

export function StageActionButton({
  children,
  onClick,
  disabled,
}: {
  children: ReactNode
  onClick: () => void
  disabled?: boolean
}) {
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

export function StageEmptyState({
  title,
  body,
  compact = false,
}: {
  title: string
  body: string
  compact?: boolean
}) {
  return (
    <div
      className={`rounded-2xl border border-dashed border-[color:var(--color-border-strong)] bg-slate-950/25 text-center ${
        compact ? 'px-5 py-8' : 'px-8 py-14'
      }`}
    >
      <p className="text-sm font-semibold text-slate-100">{title}</p>
      <p className="mx-auto mt-3 max-w-3xl text-sm leading-6 text-[color:var(--color-muted)]">{body}</p>
    </div>
  )
}

export function FactGrid({ items }: { items: Array<{ label: string; value: string }> }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => (
        <div key={item.label} className="rounded-2xl border border-[color:var(--color-border)] bg-slate-950/35 px-4 py-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[color:var(--color-muted)]">{item.label}</p>
          <p className="mt-2 text-sm font-semibold text-slate-100">{item.value}</p>
        </div>
      ))}
    </div>
  )
}

export function TranscriptReviewPane({
  transcriptPayload,
  highlightedSegmentId,
  selectable = false,
  selectedSegmentIds = [],
  onToggleSegment,
  onToggleSelectAll,
  showExcludedToggle = false,
  defaultShowExcluded = false,
}: {
  transcriptPayload: TranscriptPayload
  highlightedSegmentId?: number | null
  selectable?: boolean
  selectedSegmentIds?: number[]
  onToggleSegment?: (segmentId: number, checked: boolean) => void
  onToggleSelectAll?: (segmentIds: number[], checked: boolean) => void
  showExcludedToggle?: boolean
  defaultShowExcluded?: boolean
}) {
  const [search, setSearch] = useState('')
  const [speakerFilter, setSpeakerFilter] = useState('all')
  const [showExcluded, setShowExcluded] = useState(defaultShowExcluded)

  const speakers = useMemo(() => buildSpeakers(transcriptPayload, showExcluded), [transcriptPayload, showExcluded])
  const filteredSegments = useMemo(
    () => filterSegments(transcriptPayload.segments, search, speakerFilter, showExcluded),
    [transcriptPayload.segments, search, speakerFilter, showExcluded],
  )
  const selectedSet = useMemo(() => new Set(selectedSegmentIds), [selectedSegmentIds])
  const selectedVisibleCount = filteredSegments.filter((segment) => selectedSet.has(segment.id)).length

  return (
    <div className="space-y-5">
      <FactGrid
        items={[
          { label: 'Engine', value: transcriptPayload.transcription_run.engine_model },
          { label: 'Language', value: transcriptPayload.transcription_run.language_code },
          { label: 'Included', value: `${transcriptPayload.summary.included_segment_count}` },
          { label: 'Excluded', value: `${transcriptPayload.summary.excluded_segment_count}` },
          {
            label: 'Average confidence',
            value:
              transcriptPayload.summary.average_confidence !== null
                ? `${Math.round(transcriptPayload.summary.average_confidence * 100)}%`
                : 'N/A',
          },
        ]}
      />

      <div className="flex flex-wrap items-center gap-3">
        <input
          value={search}
          onChange={(event) => setSearch(event.target.value)}
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
        {showExcludedToggle ? (
          <label className="inline-flex items-center gap-2 rounded-xl border border-[color:var(--color-border)] bg-slate-950/60 px-3 py-3 text-sm text-slate-200">
            <input
              type="checkbox"
              checked={showExcluded}
              onChange={(event) => setShowExcluded(event.target.checked)}
              className="h-4 w-4 rounded border-[color:var(--color-border)] bg-slate-950/60"
            />
            Show excluded lines
          </label>
        ) : null}
      </div>

      {selectable ? (
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-[color:var(--color-border)] bg-slate-950/25 px-4 py-3">
          <p className="text-sm text-[color:var(--color-muted-strong)]">
            {selectedVisibleCount > 0
              ? `${selectedVisibleCount} selected in the current view`
              : 'Select one or more lines to clean up irrelevant transcript content before speaker tagging.'}
          </p>
          <button
            type="button"
            onClick={() => onToggleSelectAll?.(filteredSegments.map((segment) => segment.id), selectedVisibleCount !== filteredSegments.length)}
            disabled={filteredSegments.length === 0}
            className="rounded-xl border border-[color:var(--color-border)] px-3 py-2 text-xs font-semibold text-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {selectedVisibleCount === filteredSegments.length && filteredSegments.length > 0 ? 'Clear visible selection' : 'Select visible lines'}
          </button>
        </div>
      ) : null}

      {!showExcluded && transcriptPayload.summary.excluded_segment_count > 0 ? (
        <div className="rounded-2xl border border-amber-500/20 bg-amber-500/8 px-4 py-3 text-sm text-amber-50/90">
          {transcriptPayload.summary.excluded_segment_count} line{transcriptPayload.summary.excluded_segment_count === 1 ? '' : 's'} currently excluded from review and hidden from the default transcript view.
        </div>
      ) : null}

      <div className="space-y-3">
        {filteredSegments.length === 0 ? (
          <StageEmptyState title="No transcript segments match the filters" body="Try a broader search or switch the speaker filter back to all speakers." compact />
        ) : (
          filteredSegments.map((segment) => (
            <article
              key={segment.id}
              id={`segment-${segment.id}`}
              className={[
                'rounded-2xl border px-5 py-4',
                segment.excluded_from_review
                  ? 'border-amber-500/25 bg-amber-500/6'
                  : highlightedSegmentId === segment.id
                    ? 'border-cyan-300/60 bg-cyan-400/8'
                    : 'border-[color:var(--color-border)] bg-slate-950/35',
              ].join(' ')}
            >
              <div className="flex flex-wrap items-center gap-3">
                {selectable ? (
                  <input
                    type="checkbox"
                    checked={selectedSet.has(segment.id)}
                    onChange={(event) => onToggleSegment?.(segment.id, event.target.checked)}
                    className="h-4 w-4 rounded border-[color:var(--color-border)] bg-slate-950/60"
                  />
                ) : null}
                <span className="rounded-full border border-[color:var(--color-border)] px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-100">
                  {formatDuration(segment.start_ms_in_meeting)} - {formatDuration(segment.end_ms_in_meeting)}
                </span>
                <span className="text-sm font-semibold text-slate-100">
                  {segment.speaker_name || segment.speaker_label || 'Unlabeled speaker'}
                </span>
                {segment.excluded_from_review ? (
                  <span className="rounded-full bg-amber-500/12 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-amber-100">
                    Excluded from review
                  </span>
                ) : null}
                {segment.confidence !== null && segment.confidence < 0.75 ? (
                  <span className="rounded-full bg-amber-500/12 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-amber-100">
                    Low confidence
                  </span>
                ) : null}
              </div>
              <p className="mt-3 whitespace-pre-wrap text-sm leading-7 text-slate-100">{segment.text}</p>
              {segment.excluded_from_review && segment.exclusion_reason ? (
                <p className="mt-3 text-xs text-amber-100/90">Reason: {segment.exclusion_reason}</p>
              ) : null}
            </article>
          ))
        )}
      </div>
    </div>
  )
}

export function SpeakerAssignmentPanel({
  transcriptPayload,
  disabled,
  onSave,
}: {
  transcriptPayload: TranscriptPayload
  disabled: boolean
  onSave: (speakerLabel: string, speakerName: string | null) => void
}) {
  const speakers = useMemo(() => buildSpeakers(transcriptPayload, false), [transcriptPayload])

  if (speakers.length === 0) {
    return <StageEmptyState title="No speaker labels" body="Speaker assignment appears here when diarization labels are available." compact />
  }

  return (
    <div className="space-y-3">
      {speakers.map((speaker) => (
        <SpeakerEditor
          key={speaker.value}
          speakerLabel={speaker.value}
          speakerName={speaker.name}
          disabled={disabled}
          onSave={(speakerName) => onSave(speaker.value, speakerName)}
        />
      ))}
    </div>
  )
}

function SpeakerEditor({
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

export function TechnicalSummary({ meeting }: { meeting: MeetingDetail }) {
  return (
    <details className="group rounded-2xl border border-[color:var(--color-border)] bg-slate-950/20">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-4 px-5 py-4">
        <div>
          <p className="text-sm font-semibold text-slate-100">Advanced details</p>
          <p className="mt-1 text-sm text-[color:var(--color-muted-strong)]">Technical source paths, artifacts, and run metadata remain available here when needed.</p>
        </div>
        <span className="text-xs font-semibold uppercase tracking-[0.14em] text-[color:var(--color-muted)]">Show</span>
      </summary>
      <div className="border-t border-[color:var(--color-border)] px-5 py-5">
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
              <StageEmptyState title="Source metadata missing" body="Technical source details are incomplete for this meeting." compact />
            )}
          </Panel>
          <Panel eyebrow="Pipeline" title="Run details">
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
      </div>
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
    return <StageEmptyState title="No artifacts yet" body="Tracked files will appear here when pipeline stages generate them." compact />
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

function filterSegments(segments: TranscriptSegmentRecord[], search: string, speakerFilter: string, showExcluded: boolean) {
  const query = search.trim().toLowerCase()
  return segments.filter((segment) => {
    if (!showExcluded && segment.excluded_from_review) {
      return false
    }
    const speakerValue = segment.speaker_name || segment.speaker_label || 'Unlabeled speaker'
    const matchesSpeaker = speakerFilter === 'all' ? true : speakerValue === speakerFilter
    const matchesSearch = query
      ? [segment.text, segment.speaker_name || '', segment.speaker_label || ''].join(' ').toLowerCase().includes(query)
      : true
    return matchesSpeaker && matchesSearch
  })
}

function buildSpeakers(transcriptPayload: TranscriptPayload, showExcluded: boolean) {
  const speakers = new Map<string, { value: string; label: string; name: string | null }>()
  for (const segment of transcriptPayload.segments) {
    if (!showExcluded && segment.excluded_from_review) {
      continue
    }
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
