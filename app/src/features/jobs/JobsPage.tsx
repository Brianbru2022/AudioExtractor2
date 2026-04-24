import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, Trash2 } from 'lucide-react'
import { api } from '@/lib/api'
import { formatDateTime, formatPercent } from '@/lib/format'
import { Panel } from '@/components/Panel'
import { StatusBadge } from '@/components/StatusBadge'

function durationLabel(startedAt: string | null, completedAt: string | null) {
  if (!startedAt || !completedAt) {
    return '-'
  }
  const durationMs = new Date(completedAt).getTime() - new Date(startedAt).getTime()
  if (durationMs < 1000) {
    return '<1s'
  }
  const seconds = Math.round(durationMs / 1000)
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  return minutes > 0 ? `${minutes}m ${remainingSeconds}s` : `${remainingSeconds}s`
}

export function JobsPage() {
  const queryClient = useQueryClient()
  const jobsQuery = useQuery({
    queryKey: ['jobs'],
    queryFn: api.listJobs,
    refetchInterval: 3_000,
  })
  const deleteJobMutation = useMutation({
    mutationFn: (runId: number) => api.deleteJob(runId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['jobs'] })
      await queryClient.invalidateQueries({ queryKey: ['meetings'] })
    },
  })

  const jobs = jobsQuery.data ?? []

  return (
    <div className="space-y-6">
      <Panel eyebrow="Jobs" title="Operational queue">
        <div className="grid gap-4 md:grid-cols-3">
          <JobMetric label="Total jobs" value={`${jobs.length}`} />
          <JobMetric label="Running" value={`${jobs.filter((job) => job.status === 'running').length}`} />
          <JobMetric
            label="Needs attention"
            value={`${jobs.filter((job) => job.status === 'failed' || job.status === 'completed_with_failures').length}`}
          />
        </div>
      </Panel>

      <Panel eyebrow="Background Queue" title="Processing and transcription jobs">
        {jobs.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-[color:var(--color-border-strong)] bg-slate-950/30 px-8 py-14 text-center text-sm text-[color:var(--color-muted)]">
            No jobs have been started yet.
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-[color:var(--color-border)]">
            <table className="min-w-full divide-y divide-[color:var(--color-border)] text-sm">
              <thead className="bg-slate-950/60 text-left text-[11px] uppercase tracking-[0.18em] text-[color:var(--color-muted)]">
                <tr>
                  <th className="px-4 py-3">Meeting</th>
                  <th className="px-4 py-3">Job type</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Stage</th>
                  <th className="px-4 py-3">Progress</th>
                  <th className="px-4 py-3">Message</th>
                  <th className="px-4 py-3">Started</th>
                  <th className="px-4 py-3">Completed</th>
                  <th className="px-4 py-3">Duration</th>
                  <th className="px-4 py-3">Queue</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[color:var(--color-border)]">
                {jobs.map((job) => (
                  <tr key={job.id} className="bg-slate-950/20 hover:bg-slate-900/40">
                    <td className="px-4 py-3 font-medium text-slate-100">{job.meeting_title}</td>
                    <td className="px-4 py-3 text-cyan-100">{job.job_type}</td>
                    <td className="px-4 py-3">
                      <StatusBadge status={job.status} />
                    </td>
                    <td className="px-4 py-3">{job.stage}</td>
                    <td className="px-4 py-3">
                      <div className="space-y-2">
                        <div className="h-2 rounded-full bg-slate-800">
                          <div className="h-2 rounded-full bg-cyan-300" style={{ width: `${Math.max(4, job.progress_percent)}%` }} />
                        </div>
                        <div className="text-xs text-[color:var(--color-muted)]">{formatPercent(job.progress_percent)}</div>
                      </div>
                    </td>
                    <td className="px-4 py-3 text-[color:var(--color-muted-strong)]">
                      <div className="flex items-start gap-2">
                        {job.status === 'failed' || job.status === 'completed_with_failures' ? (
                          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 text-red-300" />
                        ) : null}
                        <span>{job.current_message || job.error_message || '-'}</span>
                      </div>
                    </td>
                    <td className="px-4 py-3">{formatDateTime(job.started_at || job.created_at)}</td>
                    <td className="px-4 py-3">{formatDateTime(job.completed_at)}</td>
                    <td className="px-4 py-3">{durationLabel(job.started_at, job.completed_at)}</td>
                    <td className="px-4 py-3">
                      <button
                        disabled={job.status === 'running' || deleteJobMutation.isPending}
                        onClick={() => {
                          if (window.confirm(`Delete queue item ${job.id} for "${job.meeting_title}"?`)) {
                            deleteJobMutation.mutate(job.id)
                          }
                        }}
                        className="inline-flex items-center gap-2 rounded-lg border border-red-500/25 bg-red-500/10 px-3 py-2 text-xs font-semibold uppercase tracking-[0.14em] text-red-100 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                        Delete
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  )
}

function JobMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-[color:var(--color-border)] bg-slate-950/40 px-4 py-4">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[color:var(--color-muted)]">{label}</p>
      <p className="mt-2 text-2xl font-semibold text-slate-50">{value}</p>
    </div>
  )
}
