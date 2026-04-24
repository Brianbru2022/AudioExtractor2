import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Sparkles } from 'lucide-react'
import { api } from '@/lib/api'
import { Panel } from '@/components/Panel'
import { InsightsTab } from '@/features/meetings/InsightsTab'
import { FactGrid, StageActionButton, StageEmptyState, TechnicalSummary, WorkflowStageLayout, WorkflowWarning, isTranscriptReadyStatus, useWorkflowMeetings } from './shared'

const minutesFilter = (meeting: { status: string }) => ['transcribed', 'extracting'].includes(meeting.status)

export function MinutesTasksPage() {
  const queryClient = useQueryClient()
  const { filteredMeetings, selectedMeeting, selectedMeetingId, selectMeeting } = useWorkflowMeetings(minutesFilter)

  const insightsQuery = useQuery({
    queryKey: ['insights', selectedMeetingId],
    queryFn: () => api.getInsights(selectedMeetingId as number),
    enabled: !!selectedMeetingId && selectedMeeting?.latest_extraction_run?.status === 'completed',
  })

  const extractionMutation = useMutation({
    mutationFn: (meetingId: number) => api.startExtraction(meetingId),
    onSuccess: async (_data, meetingId) => {
      await queryClient.invalidateQueries({ queryKey: ['meeting', meetingId] })
      await queryClient.invalidateQueries({ queryKey: ['meetings'] })
      await queryClient.invalidateQueries({ queryKey: ['jobs'] })
      await queryClient.invalidateQueries({ queryKey: ['insights', meetingId] })
    },
  })

  const updateActionMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Record<string, unknown> }) => api.updateAction(id, payload),
    onSuccess: async () => selectedMeetingId && queryClient.invalidateQueries({ queryKey: ['insights', selectedMeetingId] }),
  })
  const updateDecisionMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Record<string, unknown> }) => api.updateDecision(id, payload),
    onSuccess: async () => selectedMeetingId && queryClient.invalidateQueries({ queryKey: ['insights', selectedMeetingId] }),
  })
  const updateRiskMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Record<string, unknown> }) => api.updateRisk(id, payload),
    onSuccess: async () => selectedMeetingId && queryClient.invalidateQueries({ queryKey: ['insights', selectedMeetingId] }),
  })
  const updateQuestionMutation = useMutation({
    mutationFn: ({ id, payload }: { id: number; payload: Record<string, unknown> }) => api.updateQuestion(id, payload),
    onSuccess: async () => selectedMeetingId && queryClient.invalidateQueries({ queryKey: ['insights', selectedMeetingId] }),
  })

  const canExtract =
    !!selectedMeeting?.latest_transcription_run &&
    isTranscriptReadyStatus(selectedMeeting.latest_transcription_run.status) &&
    selectedMeeting.latest_extraction_run?.status !== 'running'

  return (
    <WorkflowStageLayout
      title="Minutes & Tasks"
      description="Generate and review evidence-backed minutes, actions, decisions, risks, and open questions from the persisted transcript."
      sidebarTitle="Ready for review"
      emptyTitle="No meetings are ready for minutes and task review"
      emptyBody="Complete transcription first, then meetings will appear here for evidence-backed extraction."
      meetings={filteredMeetings}
      selectedMeetingId={selectedMeetingId}
      onSelectMeeting={selectMeeting}
      selectedMeeting={selectedMeeting}
    >
      {selectedMeeting ? (
        <div className="space-y-6">
          <WorkflowWarning meeting={selectedMeeting} />

          <Panel eyebrow="Review" title="Minutes and tasks">
            <div className="space-y-5">
              <FactGrid
                items={[
                  { label: 'Transcript', value: selectedMeeting.latest_transcription_run?.status || 'Not ready' },
                  { label: 'Extraction', value: selectedMeeting.latest_extraction_run?.status || 'Not started' },
                  { label: 'Model', value: selectedMeeting.latest_extraction_run?.model || 'Gemini default' },
                  { label: 'Meeting', value: selectedMeeting.title },
                ]}
              />
              {canExtract && !insightsQuery.data ? (
                <StageActionButton
                  disabled={extractionMutation.isPending}
                  onClick={() => extractionMutation.mutate(selectedMeeting.id)}
                >
                  <Sparkles className="h-4 w-4" />
                  {extractionMutation.isPending ? 'Starting extraction' : 'Generate minutes and tasks'}
                </StageActionButton>
              ) : null}
            </div>
          </Panel>

          {insightsQuery.data ? (
            <InsightsTab
              insights={insightsQuery.data}
              latestRun={selectedMeeting.latest_extraction_run}
              onJumpToEvidence={() => undefined}
              onUpdateAction={(id, payload) => updateActionMutation.mutate({ id, payload })}
              onUpdateDecision={(id, payload) => updateDecisionMutation.mutate({ id, payload })}
              onUpdateRisk={(id, payload) => updateRiskMutation.mutate({ id, payload })}
              onUpdateQuestion={(id, payload) => updateQuestionMutation.mutate({ id, payload })}
              onBulkAcceptActions={(ids) => {
                void Promise.all(ids.map((id) => api.updateAction(id, { review_status: 'accepted' }))).then(async () => {
                  if (selectedMeetingId) {
                    await queryClient.invalidateQueries({ queryKey: ['insights', selectedMeetingId] })
                  }
                })
              }}
            />
          ) : (
            <StageEmptyState
              title={selectedMeeting.latest_extraction_run?.status === 'running' ? 'Extraction in progress' : 'Minutes and tasks not generated yet'}
              body={
                selectedMeeting.latest_extraction_run?.status === 'running'
                  ? 'Evidence-backed extraction is running in the background.'
                  : 'Run extraction to create structured minutes, action items, decisions, risks, and questions.'
              }
            />
          )}

          <TechnicalSummary meeting={selectedMeeting} />
        </div>
      ) : null}
    </WorkflowStageLayout>
  )
}
