import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Mic2 } from 'lucide-react'
import { api } from '@/lib/api'
import { Panel } from '@/components/Panel'
import { FactGrid, StageActionButton, StageEmptyState, TechnicalSummary, TranscriptReviewPane, WorkflowStageLayout, WorkflowWarning, useWorkflowMeetings } from './shared'

const transcriptionFilter = (meeting: { status: string; chunk_count: number }) =>
  meeting.chunk_count > 0 || ['prepared', 'transcribing', 'transcribed', 'extracting', 'failed'].includes(meeting.status)

export function TranscriptionPage() {
  const queryClient = useQueryClient()
  const { filteredMeetings, selectedMeeting, selectedMeetingId, selectMeeting } = useWorkflowMeetings(transcriptionFilter)

  const transcriptQuery = useQuery({
    queryKey: ['transcript', selectedMeetingId],
    queryFn: () => api.getTranscript(selectedMeetingId as number),
    enabled: !!selectedMeetingId && !!selectedMeeting?.latest_transcription_run && ['completed', 'completed_with_failures', 'recovered'].includes(selectedMeeting.latest_transcription_run.status),
  })

  const transcriptionMutation = useMutation({
    mutationFn: (meetingId: number) => api.startTranscription(meetingId),
    onSuccess: async (_data, meetingId) => {
      await queryClient.invalidateQueries({ queryKey: ['meeting', meetingId] })
      await queryClient.invalidateQueries({ queryKey: ['meetings'] })
      await queryClient.invalidateQueries({ queryKey: ['jobs'] })
      await queryClient.invalidateQueries({ queryKey: ['transcript', meetingId] })
    },
  })

  const retryChunksMutation = useMutation({
    mutationFn: (runId: number) => api.retryFailedTranscriptionChunks(runId),
    onSuccess: async () => {
      if (selectedMeetingId) {
        await queryClient.invalidateQueries({ queryKey: ['meeting', selectedMeetingId] })
        await queryClient.invalidateQueries({ queryKey: ['transcript', selectedMeetingId] })
      }
      await queryClient.invalidateQueries({ queryKey: ['meetings'] })
      await queryClient.invalidateQueries({ queryKey: ['jobs'] })
    },
  })

  const canTranscribe =
    selectedMeeting?.status === 'prepared' &&
    selectedMeeting.chunk_count > 0 &&
    selectedMeeting.latest_transcription_run?.status !== 'running'
  const transcriptionQueuedOrRunning =
    transcriptionMutation.isSuccess ||
    selectedMeeting?.latest_transcription_run?.status === 'pending' ||
    selectedMeeting?.latest_transcription_run?.status === 'running' ||
    selectedMeeting?.status === 'transcribing'

  return (
    <WorkflowStageLayout
      title="Transcription"
      description="Run chunk-based cloud transcription, preserve raw chunk responses, and review the merged transcript before speaker cleanup."
      sidebarTitle="Transcription queue"
      emptyTitle="No meetings are ready for transcription"
      emptyBody="Preparation needs to complete before a meeting appears here."
      meetings={filteredMeetings}
      selectedMeetingId={selectedMeetingId}
      onSelectMeeting={selectMeeting}
      selectedMeeting={selectedMeeting}
    >
      {selectedMeeting ? (
        <div className="space-y-6">
          <WorkflowWarning meeting={selectedMeeting} />

          <Panel eyebrow="Transcription" title="First-pass transcript">
            <div className="space-y-5">
              <FactGrid
                items={[
                  { label: 'Status', value: selectedMeeting.latest_transcription_run?.status || 'Not started' },
                  { label: 'Chunks', value: `${selectedMeeting.chunk_count}` },
                  {
                    label: 'Chunk results',
                    value: selectedMeeting.latest_transcription_run
                      ? `${selectedMeeting.latest_transcription_run.completed_chunk_count}/${selectedMeeting.latest_transcription_run.chunk_count}`
                      : '0/0',
                  },
                  { label: 'Model', value: selectedMeeting.latest_transcription_run?.engine_model || 'chirp_3 default' },
                ]}
              />

              <p className="text-sm leading-6 text-[color:var(--color-muted-strong)]">
                {selectedMeeting.latest_transcription_run?.status === 'running'
                  ? 'Transcription is currently running in the background and merged transcript review will unlock once the run completes.'
                  : selectedMeeting.latest_transcription_run?.status === 'pending'
                    ? 'Transcription has been queued and will begin as soon as the local worker picks it up.'
                  : transcriptQuery.data
                    ? 'The merged transcript is ready. Continue into Speaker Tagging to clean up speaker names.'
                    : 'Transcription sends prepared chunks to Google Speech-to-Text and stores the raw chunk responses locally for later stitching and traceability.'}
              </p>

              {transcriptionQueuedOrRunning ? (
                <div className="rounded-xl border border-cyan-400/25 bg-cyan-400/8 px-4 py-3 text-sm text-cyan-100">
                  {selectedMeeting.latest_transcription_run?.status === 'running'
                    ? 'Transcription is running now. Progress updates will appear on this page automatically.'
                    : 'Transcription has been queued. If progress does not appear within a few seconds, check Settings for cloud configuration or open Diagnostics from the sidebar.'}
                </div>
              ) : null}

              {transcriptionMutation.error ? (
                <div className="rounded-xl border border-red-500/25 bg-red-500/10 px-4 py-3 text-sm text-red-100">
                  <p className="font-semibold">Unable to queue transcription</p>
                  <p className="mt-1 leading-6">
                    {transcriptionMutation.error instanceof Error
                      ? transcriptionMutation.error.message
                      : 'The transcription request failed.'}
                  </p>
                </div>
              ) : null}

              {canTranscribe ? (
                <StageActionButton
                  disabled={transcriptionMutation.isPending}
                  onClick={() => transcriptionMutation.mutate(selectedMeeting.id)}
                >
                  <Mic2 className="h-4 w-4" />
                  {transcriptionMutation.isPending ? 'Queueing transcription' : 'Queue transcription'}
                </StageActionButton>
              ) : null}

              {selectedMeeting.latest_transcription_run && selectedMeeting.latest_transcription_run.failed_chunk_count > 0 ? (
                <StageActionButton
                  disabled={retryChunksMutation.isPending}
                  onClick={() => retryChunksMutation.mutate(selectedMeeting.latest_transcription_run!.id)}
                >
                  <Mic2 className="h-4 w-4" />
                  {retryChunksMutation.isPending ? 'Retrying failed chunks' : 'Retry failed chunks'}
                </StageActionButton>
              ) : null}
            </div>
          </Panel>

          {transcriptQuery.data ? (
            <Panel eyebrow="Transcript" title="Merged transcript review">
              <TranscriptReviewPane transcriptPayload={transcriptQuery.data} />
            </Panel>
          ) : (
            <StageEmptyState
              title={selectedMeeting.latest_transcription_run?.status === 'running' ? 'Transcription in progress' : 'Transcript not ready yet'}
              body="The transcript becomes readable here once the background transcription run completes."
            />
          )}

          <TechnicalSummary meeting={selectedMeeting} />
        </div>
      ) : null}
    </WorkflowStageLayout>
  )
}
