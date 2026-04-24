import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { AlertTriangle, Play, RefreshCcw, Trash2 } from 'lucide-react'
import { api } from '@/lib/api'
import { formatDate, formatDateTime, formatDuration, formatPercent } from '@/lib/format'
import { Panel } from '@/components/Panel'
import { StatusBadge } from '@/components/StatusBadge'

export function MeetingsPage() {
  const queryClient = useQueryClient()
  const meetingsQuery = useQuery({
    queryKey: ['meetings'],
    queryFn: api.listMeetings,
    refetchInterval: 5_000,
  })

  const preprocessMutation = useMutation({
    mutationFn: (meetingId: number) => api.startPreprocess(meetingId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['meetings'] })
      await queryClient.invalidateQueries({ queryKey: ['jobs'] })
    },
  })

  const deleteMeetingMutation = useMutation({
    mutationFn: (meetingId: number) => api.deleteMeeting(meetingId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['meetings'] })
      await queryClient.invalidateQueries({ queryKey: ['jobs'] })
    },
  })

  const meetings = meetingsQuery.data ?? []

  return (
    <div className="space-y-6">
      <Panel
        eyebrow="Meetings"
        title="Review queue"
        actions={
          <button
            className="inline-flex items-center gap-2 rounded-xl border border-[color:var(--color-border)] bg-slate-950/60 px-3 py-2 text-xs font-semibold text-slate-200"
            onClick={() => meetingsQuery.refetch()}
          >
            <RefreshCcw className="h-3.5 w-3.5" />
            Refresh
          </button>
        }
      >
        <div className="grid gap-4 md:grid-cols-3">
          <Metric label="Meetings" value={`${meetings.length}`} />
          <Metric label="Ready for transcript" value={`${meetings.filter((item) => item.status === 'prepared').length}`} />
          <Metric
            label="Needs attention"
            value={`${meetings.filter((item) => (item.integrity_issues ?? []).length > 0 || item.status === 'failed').length}`}
          />
        </div>
      </Panel>

      <Panel eyebrow="Workflow" title="Active meetings">
        {meetings.length === 0 ? (
          <EmptyState
            title="No meetings imported yet"
            body="Import a meeting file to start the workflow. Once a source is in place, preparation, transcription, review, and export all continue from the Meetings workspace."
          />
        ) : (
          <div className="space-y-3">
            {meetings.map((meeting) => {
              const integrityIssues = meeting.integrity_issues ?? []
              const blockingIssue = integrityIssues[0] ?? null
              const sourceBlockingIssue =
                integrityIssues.find(
                  (issue) =>
                    issue.startsWith('Missing source record') ||
                    issue.startsWith('Reference source file missing') ||
                    issue.startsWith('Managed source file missing'),
                ) ?? null
              const canPrepare =
                !!meeting.source_file &&
                !sourceBlockingIssue &&
                meeting.status !== 'preprocessing' &&
                meeting.latest_run?.status !== 'running' &&
                !preprocessMutation.isPending

              return (
                <div key={meeting.id} className="rounded-2xl border border-[color:var(--color-border)] bg-slate-950/25 p-4">
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <Link to={`/meetings/${meeting.id}`} className="text-base font-semibold text-slate-100 hover:text-cyan-200">
                          {meeting.title}
                        </Link>
                        <StatusBadge status={meeting.status} />
                      </div>
                      <p className="mt-1 text-sm text-[color:var(--color-muted-strong)]">
                        {(meeting.project || 'General') + (meeting.meeting_date ? ` · ${formatDate(meeting.meeting_date)}` : '')}
                      </p>
                      <p className="mt-2 text-sm text-[color:var(--color-muted)]">
                        {meeting.source_file
                          ? `${meeting.source_file.file_name} · ${formatDuration(meeting.source_file.duration_ms)}`
                          : 'Source metadata incomplete'}
                      </p>
                    </div>

                    <div className="flex shrink-0 items-center gap-2">
                      <Link
                        to={`/meetings/${meeting.id}`}
                        className="rounded-xl border border-[color:var(--color-border)] px-3 py-2 text-xs font-semibold text-slate-200"
                      >
                        Open
                      </Link>
                      <button
                        className="inline-flex items-center gap-2 rounded-xl bg-cyan-400 px-3 py-2 text-xs font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-50"
                        disabled={!canPrepare}
                        onClick={() => preprocessMutation.mutate(meeting.id)}
                      >
                        <Play className="h-3.5 w-3.5" />
                        Prepare
                      </button>
                      <button
                        className="inline-flex items-center gap-2 rounded-xl border border-red-500/25 bg-red-500/10 px-3 py-2 text-xs font-semibold text-red-100 disabled:cursor-not-allowed disabled:opacity-50"
                        disabled={deleteMeetingMutation.isPending || meeting.latest_run?.status === 'running'}
                        onClick={() => {
                          const message = [
                            `Delete "${meeting.title}"?`,
                            '',
                            'This removes the meeting record and all app-managed local artifacts, runs, logs, chunks, and exports for it.',
                            meeting.source_file?.import_mode === 'reference'
                              ? 'The original reference-mode source file on disk will be preserved.'
                              : 'Managed-copy source files stored by the app will also be removed.',
                          ].join('\n')
                          if (window.confirm(message)) {
                            deleteMeetingMutation.mutate(meeting.id)
                          }
                        }}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        Delete
                      </button>
                    </div>
                  </div>

                  <div className="mt-4 grid gap-3 md:grid-cols-[1.1fr_0.9fr_160px]">
                    <div className="rounded-xl border border-[color:var(--color-border)] bg-slate-950/35 px-4 py-3">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[color:var(--color-muted)]">Workflow</p>
                      <p className="mt-2 text-sm font-semibold text-slate-100">
                        {blockingIssue
                          ? 'Resolve warning'
                          : meeting.status === 'imported' || meeting.status === 'draft'
                            ? 'Prepare audio'
                            : meeting.status === 'prepared'
                              ? 'Start transcription'
                              : meeting.status === 'transcribed'
                                ? 'Review transcript'
                                : meeting.status === 'failed'
                                  ? 'Inspect failure'
                                  : 'Continue review'}
                      </p>
                      {meeting.latest_run ? (
                        <p className="mt-1 text-xs text-[color:var(--color-muted)]">
                          {meeting.latest_run.stage} · {formatPercent(meeting.latest_run.progress_percent)}
                        </p>
                      ) : null}
                    </div>

                    <div className="rounded-xl border border-[color:var(--color-border)] bg-slate-950/35 px-4 py-3">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[color:var(--color-muted)]">Latest note</p>
                      {blockingIssue ? (
                        <div className="mt-2 flex items-start gap-2 text-sm text-amber-200">
                          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                          <span>{blockingIssue}</span>
                        </div>
                      ) : (
                        <p className="mt-2 text-sm text-[color:var(--color-muted-strong)]">
                          {meeting.latest_run?.current_message || 'Meeting is ready for the next workflow step.'}
                        </p>
                      )}
                    </div>

                    <div className="rounded-xl border border-[color:var(--color-border)] bg-slate-950/35 px-4 py-3">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[color:var(--color-muted)]">Imported</p>
                      <p className="mt-2 text-sm font-semibold text-slate-100">{formatDateTime(meeting.created_at)}</p>
                      <p className="mt-1 text-xs text-[color:var(--color-muted)]">{meeting.chunk_count} chunks</p>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </Panel>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-[color:var(--color-border)] bg-slate-950/40 px-4 py-4">
      <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-[color:var(--color-muted)]">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-slate-50">{value}</p>
    </div>
  )
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-[color:var(--color-border-strong)] bg-slate-950/30 px-8 py-16 text-center">
      <h3 className="text-lg font-semibold text-slate-100">{title}</h3>
      <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-[color:var(--color-muted)]">{body}</p>
    </div>
  )
}
