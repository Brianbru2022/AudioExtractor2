import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Play } from 'lucide-react'
import { api } from '@/lib/api'
import { formatDuration, formatPercent } from '@/lib/format'
import { Panel } from '@/components/Panel'
import { StageActionButton, StageEmptyState, FactGrid, TechnicalSummary, WorkflowStageLayout, WorkflowWarning, useWorkflowMeetings } from './shared'

const preparationFilter = (meeting: { status: string }) =>
  ['draft', 'imported', 'preprocessing', 'prepared', 'failed'].includes(meeting.status)

export function PreparationPage() {
  const queryClient = useQueryClient()
  const { filteredMeetings, selectedMeeting, selectedMeetingId, selectMeeting } = useWorkflowMeetings(preparationFilter)

  const preprocessMutation = useMutation({
    mutationFn: (meetingId: number) => api.startPreprocess(meetingId),
    onSuccess: async (_data, meetingId) => {
      await queryClient.invalidateQueries({ queryKey: ['meeting', meetingId] })
      await queryClient.invalidateQueries({ queryKey: ['meetings'] })
      await queryClient.invalidateQueries({ queryKey: ['jobs'] })
    },
  })

  const canPrepare =
    !!selectedMeeting?.source_file &&
    !selectedMeeting.integrity_issues?.some(
      (issue) =>
        issue.startsWith('Missing source record') ||
        issue.startsWith('Reference source file missing') ||
        issue.startsWith('Managed source file missing'),
    ) &&
    selectedMeeting.status !== 'preprocessing' &&
    selectedMeeting.latest_run?.status !== 'running'

  return (
    <WorkflowStageLayout
      title="Preparation"
      description="Normalize imported audio, analyze silence, and create the chunk plan that feeds the rest of the workflow."
      sidebarTitle="Needs preparation"
      emptyTitle="Nothing is waiting for preparation"
      emptyBody="Import a new meeting to begin the workflow, or reopen older work from History."
      meetings={filteredMeetings}
      selectedMeetingId={selectedMeetingId}
      onSelectMeeting={selectMeeting}
      selectedMeeting={selectedMeeting}
    >
      {selectedMeeting ? (
        <div className="space-y-6">
          <WorkflowWarning meeting={selectedMeeting} />

          <Panel eyebrow="Preparation" title="Audio routing and chunk readiness">
            <div className="space-y-5">
              <FactGrid
                items={[
                  { label: 'Source', value: selectedMeeting.source_file?.file_name ?? 'Unavailable' },
                  { label: 'Duration', value: formatDuration(selectedMeeting.source_file?.duration_ms) },
                  { label: 'Chunks', value: `${selectedMeeting.chunk_count}` },
                  {
                    label: 'Preparation status',
                    value: selectedMeeting.latest_run_detail
                      ? `${selectedMeeting.latest_run_detail.stage} · ${formatPercent(selectedMeeting.latest_run_detail.progress_percent)}`
                      : selectedMeeting.status,
                  },
                ]}
              />

              <p className="text-sm leading-6 text-[color:var(--color-muted-strong)]">
                {selectedMeeting.status === 'preprocessing'
                  ? selectedMeeting.latest_run?.current_message || 'Preparation is currently running in the background.'
                  : selectedMeeting.chunk_count > 0
                    ? 'Preparation is complete. This meeting is ready to move into transcription.'
                    : 'Preparation creates the normalized working audio, silence-aware chunk plan, and chunk files used for transcription.'}
              </p>

              {canPrepare ? (
                <StageActionButton
                  disabled={preprocessMutation.isPending}
                  onClick={() => preprocessMutation.mutate(selectedMeeting.id)}
                >
                  <Play className="h-4 w-4" />
                  {preprocessMutation.isPending ? 'Starting preparation' : 'Prepare audio'}
                </StageActionButton>
              ) : null}
            </div>
          </Panel>

          {selectedMeeting.chunks.length > 0 ? (
            <Panel eyebrow="Result" title="Chunk coverage">
              <div className="space-y-3">
                {selectedMeeting.chunks.slice(0, 8).map((chunk) => (
                  <div key={chunk.id} className="rounded-xl border border-[color:var(--color-border)] bg-slate-950/35 px-4 py-3">
                    <div className="flex items-center justify-between gap-3">
                      <p className="text-sm font-semibold text-slate-100">Chunk {chunk.chunk_index}</p>
                      <p className="text-xs text-[color:var(--color-muted)]">{chunk.boundary_reason}</p>
                    </div>
                    <p className="mt-1 text-sm text-[color:var(--color-muted-strong)]">
                      {formatDuration(chunk.start_ms)} - {formatDuration(chunk.end_ms)} · {formatDuration(chunk.duration_ms)}
                    </p>
                  </div>
                ))}
              </div>
            </Panel>
          ) : (
            <StageEmptyState title="No chunks yet" body="Chunk details appear here after preparation completes." compact />
          )}

          <TechnicalSummary meeting={selectedMeeting} />
        </div>
      ) : null}
    </WorkflowStageLayout>
  )
}
