import { useMemo } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Trash2 } from 'lucide-react'
import { useWorkflowMeetings } from './shared'
import { Panel } from '@/components/Panel'
import { api } from '@/lib/api'
import { formatDate, formatDateTime, formatDuration } from '@/lib/format'
import { StatusBadge } from '@/components/StatusBadge'

const historyFilter = () => true

export function HistoryPage() {
  const queryClient = useQueryClient()
  const [, setSearchParams] = useSearchParams()
  const { meetings, selectedMeeting, selectedMeetingId, selectMeeting } = useWorkflowMeetings(historyFilter)

  const nextMeetingId = useMemo(
    () => meetings.find((meeting) => meeting.id !== selectedMeetingId)?.id ?? null,
    [meetings, selectedMeetingId],
  )

  const deleteMeetingMutation = useMutation({
    mutationFn: (meetingId: number) => api.deleteMeeting(meetingId),
    onSuccess: async (_response, meetingId) => {
      await queryClient.invalidateQueries({ queryKey: ['meetings'] })
      await queryClient.invalidateQueries({ queryKey: ['jobs'] })
      await queryClient.invalidateQueries({ queryKey: ['meeting', meetingId] })
      await queryClient.invalidateQueries({ queryKey: ['transcript', meetingId] })
      await queryClient.invalidateQueries({ queryKey: ['insights', meetingId] })
      await queryClient.invalidateQueries({ queryKey: ['exports', meetingId] })
      setSearchParams((current) => {
        const next = new URLSearchParams(current)
        if (nextMeetingId) {
          next.set('meeting', `${nextMeetingId}`)
        } else {
          next.delete('meeting')
        }
        return next
      })
    },
  })

  const handleDeleteMeeting = (meetingId: number, meetingTitle: string, importMode: string | null | undefined) => {
    const message = [
      `Permanently delete "${meetingTitle}" from history?`,
      '',
      'This removes the meeting record and all app-managed local artifacts, runs, transcript data, insights, and exports.',
      importMode === 'reference'
        ? 'The original reference-mode source file on disk will be preserved.'
        : 'Any managed-copy source file stored by the app will also be removed.',
    ].join('\n')

    if (window.confirm(message)) {
      deleteMeetingMutation.mutate(meetingId)
    }
  }

  return (
    <div className="grid gap-6 xl:grid-cols-[330px_minmax(0,1fr)]">
      <div className="space-y-6">
        <Panel eyebrow="History" title="Previous meetings">
          <p className="text-sm leading-6 text-[color:var(--color-muted-strong)]">
            Reopen prior transcript work, reviewed minutes and tasks, or exports from the complete meeting history.
          </p>
        </Panel>

        <Panel eyebrow="Archive" title="Meeting history">
          {meetings.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-[color:var(--color-border-strong)] bg-slate-950/25 px-5 py-8 text-center">
              <p className="text-sm font-semibold text-slate-100">No meetings yet</p>
              <p className="mt-3 text-sm leading-6 text-[color:var(--color-muted)]">Imported meetings will accumulate here for later review and reuse.</p>
            </div>
          ) : (
            <div className="space-y-3">
              {meetings.map((meeting) => (
                <div
                  key={meeting.id}
                  className={[
                    'rounded-2xl border p-4 transition',
                    meeting.id === selectedMeetingId
                      ? 'border-cyan-400/35 bg-cyan-400/8'
                      : 'border-[color:var(--color-border)] bg-slate-950/25 hover:bg-slate-950/45',
                  ].join(' ')}
                >
                  <div className="flex items-start gap-3">
                    <button type="button" onClick={() => selectMeeting(meeting.id)} className="min-w-0 flex-1 text-left">
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
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDeleteMeeting(meeting.id, meeting.title, meeting.source_file?.import_mode)}
                      disabled={deleteMeetingMutation.isPending || meeting.latest_run?.status === 'running'}
                      className="inline-flex items-center gap-2 rounded-lg border border-red-500/25 bg-red-500/10 px-3 py-2 text-xs font-semibold text-red-100 disabled:cursor-not-allowed disabled:opacity-50"
                      title="Delete permanently"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      Delete
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      <div className="space-y-6">
        {!selectedMeeting ? (
          <Panel title="Select a meeting">
            <p className="text-sm leading-6 text-[color:var(--color-muted-strong)]">Choose a meeting from the history list to reopen its workflow state.</p>
          </Panel>
        ) : (
          <>
            <Panel eyebrow="Meeting history" title={selectedMeeting.title}>
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                <HistoryFact label="Status" value={selectedMeeting.status} />
                <HistoryFact label="Imported" value={formatDateTime(selectedMeeting.created_at)} />
                <HistoryFact label="Transcript" value={selectedMeeting.latest_transcription_run?.status || 'Not started'} />
                <HistoryFact label="Insights" value={selectedMeeting.latest_extraction_run?.status || 'Not started'} />
              </div>

              <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap gap-2">
                  <Link to={`/preparation?meeting=${selectedMeeting.id}`} className="rounded-xl border border-[color:var(--color-border)] px-3 py-2 text-sm font-semibold text-slate-200">
                    Preparation
                  </Link>
                  <Link to={`/transcription?meeting=${selectedMeeting.id}`} className="rounded-xl border border-[color:var(--color-border)] px-3 py-2 text-sm font-semibold text-slate-200">
                    Transcription
                  </Link>
                  <Link to={`/speaker-tagging?meeting=${selectedMeeting.id}`} className="rounded-xl border border-[color:var(--color-border)] px-3 py-2 text-sm font-semibold text-slate-200">
                    Speaker Tagging
                  </Link>
                  <Link to={`/minutes-tasks?meeting=${selectedMeeting.id}`} className="rounded-xl border border-[color:var(--color-border)] px-3 py-2 text-sm font-semibold text-slate-200">
                    Minutes & Tasks
                  </Link>
                  <Link to={`/export?meeting=${selectedMeeting.id}`} className="rounded-xl border border-[color:var(--color-border)] px-3 py-2 text-sm font-semibold text-slate-200">
                    Export
                  </Link>
                </div>
                <button
                  type="button"
                  onClick={() => handleDeleteMeeting(selectedMeeting.id, selectedMeeting.title, selectedMeeting.source_file?.import_mode)}
                  disabled={deleteMeetingMutation.isPending || selectedMeeting.latest_run?.status === 'running'}
                  className="inline-flex items-center gap-2 rounded-xl border border-red-500/25 bg-red-500/10 px-3 py-2 text-sm font-semibold text-red-100 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Trash2 className="h-4 w-4" />
                  Delete permanently
                </button>
              </div>
            </Panel>

            <Panel eyebrow="Summary" title="Last known workflow state">
              <div className="space-y-3 text-sm text-[color:var(--color-muted-strong)]">
                <p>{selectedMeeting.source_file ? `Source: ${selectedMeeting.source_file.file_name}` : 'Source metadata incomplete.'}</p>
                <p>{selectedMeeting.chunk_count} chunks prepared.</p>
                <p>{selectedMeeting.latest_run?.current_message || 'No background job is currently active.'}</p>
                <p>{selectedMeeting.integrity_issues?.[0] || 'No integrity warnings are currently recorded.'}</p>
              </div>
            </Panel>
          </>
        )}
      </div>
    </div>
  )
}

function HistoryFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-[color:var(--color-border)] bg-slate-950/35 px-4 py-3">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[color:var(--color-muted)]">{label}</p>
      <p className="mt-2 text-sm font-semibold text-slate-100">{value}</p>
    </div>
  )
}
