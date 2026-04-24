import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Panel } from '@/components/Panel'
import { SpeakerAssignmentPanel, StageEmptyState, TechnicalSummary, TranscriptReviewPane, WorkflowStageLayout, WorkflowWarning, isTranscriptReadyStatus, useWorkflowMeetings } from './shared'
import { api } from '@/lib/api'

const speakerFilter = (meeting: { status: string }) => ['transcribed', 'extracting'].includes(meeting.status)

export function SpeakerTaggingPage() {
  const queryClient = useQueryClient()
  const { filteredMeetings, selectedMeeting, selectedMeetingId, selectMeeting } = useWorkflowMeetings(speakerFilter)
  const [selectedSegmentIds, setSelectedSegmentIds] = useState<number[]>([])
  const [bulkReason, setBulkReason] = useState('Off-topic or unrelated transcript content')
  const [selectedSpeakerValue, setSelectedSpeakerValue] = useState('all')

  const transcriptQuery = useQuery({
    queryKey: ['transcript', selectedMeetingId],
    queryFn: () => api.getTranscript(selectedMeetingId as number),
    enabled: !!selectedMeetingId && !!selectedMeeting?.latest_transcription_run && isTranscriptReadyStatus(selectedMeeting.latest_transcription_run.status),
  })

  const assignSpeakerMutation = useMutation({
    mutationFn: ({ speakerLabel, speakerName }: { speakerLabel: string; speakerName: string | null }) =>
      api.assignSpeakerName(selectedMeetingId as number, speakerLabel, speakerName),
    onSuccess: async () => {
      if (selectedMeetingId) {
        await queryClient.invalidateQueries({ queryKey: ['meeting', selectedMeetingId] })
        await queryClient.invalidateQueries({ queryKey: ['transcript', selectedMeetingId] })
      }
    },
  })

  const updateSegmentsMutation = useMutation({
    mutationFn: (payload: { segment_ids: number[]; excluded_from_review: boolean; exclusion_reason?: string | null }) =>
      api.updateTranscriptSegments(selectedMeetingId as number, payload),
    onSuccess: async () => {
      setSelectedSegmentIds([])
      if (selectedMeetingId) {
        await queryClient.invalidateQueries({ queryKey: ['meeting', selectedMeetingId] })
        await queryClient.invalidateQueries({ queryKey: ['transcript', selectedMeetingId] })
      }
    },
  })

  const selectedSegments = useMemo(() => {
    const segmentMap = new Map((transcriptQuery.data?.segments ?? []).map((segment) => [segment.id, segment]))
    return selectedSegmentIds.map((id) => segmentMap.get(id)).filter(Boolean)
  }, [selectedSegmentIds, transcriptQuery.data?.segments])
  const hasSelectedIncluded = selectedSegments.some((segment) => segment && !segment.excluded_from_review)
  const hasSelectedExcluded = selectedSegments.some((segment) => segment?.excluded_from_review)
  const speakerOptions = useMemo(() => {
    const grouped = new Map<string, { value: string; label: string; includedIds: number[]; excludedIds: number[] }>()
    for (const segment of transcriptQuery.data?.segments ?? []) {
      const value = segment.speaker_name || segment.speaker_label || 'Unlabeled speaker'
      const label = segment.speaker_name ? `${segment.speaker_name} (${segment.speaker_label || 'speaker'})` : value
      const entry = grouped.get(value) ?? { value, label, includedIds: [], excludedIds: [] }
      if (segment.excluded_from_review) {
        entry.excludedIds.push(segment.id)
      } else {
        entry.includedIds.push(segment.id)
      }
      grouped.set(value, entry)
    }
    return Array.from(grouped.values()).sort((left, right) => left.label.localeCompare(right.label))
  }, [transcriptQuery.data?.segments])
  const selectedSpeakerOption = speakerOptions.find((speaker) => speaker.value === selectedSpeakerValue) ?? null

  useEffect(() => {
    setSelectedSegmentIds([])
  }, [selectedMeetingId])

  useEffect(() => {
    setSelectedSpeakerValue('all')
  }, [selectedMeetingId])

  return (
    <WorkflowStageLayout
      title="Speaker Tagging"
      description="Tidy up speaker labels after first-pass transcription so the final transcript and reviewed outputs are easier to read."
      sidebarTitle="Ready for speaker cleanup"
      emptyTitle="No transcripts are ready for speaker tagging"
      emptyBody="Run transcription first and completed meetings will appear here."
      meetings={filteredMeetings}
      selectedMeetingId={selectedMeetingId}
      onSelectMeeting={selectMeeting}
      selectedMeeting={selectedMeeting}
    >
      {selectedMeeting ? (
        <div className="space-y-6">
          <WorkflowWarning meeting={selectedMeeting} />

          {!transcriptQuery.data ? (
            <StageEmptyState title="Transcript not available" body="A merged transcript is required before speaker names can be assigned." />
          ) : (
            <>
              <Panel eyebrow="Transcript cleanup" title="Remove unrelated lines before speaker tagging">
                <div className="space-y-5">
                  <p className="text-sm leading-6 text-[color:var(--color-muted-strong)]">
                    Use this step to exclude transcript lines that are clearly unrelated to the meeting, such as pre-roll chatter, accidental capture, or post-meeting noise.
                    Excluded lines stay preserved in the raw record and can be restored later.
                  </p>

                  <div className="flex flex-wrap items-end gap-3">
                    <label className="min-w-[280px] flex-1">
                      <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.16em] text-[color:var(--color-muted)]">
                        Exclusion reason
                      </span>
                      <input
                        value={bulkReason}
                        onChange={(event) => setBulkReason(event.target.value)}
                        placeholder="Why these lines are being removed from review"
                        className="w-full rounded-xl border border-[color:var(--color-border)] bg-slate-950/60 px-4 py-3 text-sm text-slate-100 outline-none"
                      />
                    </label>
                    <label className="min-w-[280px] flex-1">
                      <span className="mb-2 block text-xs font-semibold uppercase tracking-[0.16em] text-[color:var(--color-muted)]">
                        Speaker shortcut
                      </span>
                      <select
                        value={selectedSpeakerValue}
                        onChange={(event) => setSelectedSpeakerValue(event.target.value)}
                        className="w-full rounded-xl border border-[color:var(--color-border)] bg-slate-950/60 px-4 py-3 text-sm text-slate-100 outline-none"
                      >
                        <option value="all">Choose a speaker</option>
                        {speakerOptions.map((speaker) => (
                          <option key={speaker.value} value={speaker.value}>
                            {speaker.label} · {speaker.includedIds.length + speaker.excludedIds.length} lines
                          </option>
                        ))}
                      </select>
                    </label>
                    <button
                      type="button"
                      disabled={!hasSelectedIncluded || updateSegmentsMutation.isPending}
                      onClick={() =>
                        updateSegmentsMutation.mutate({
                          segment_ids: selectedSegmentIds,
                          excluded_from_review: true,
                          exclusion_reason: bulkReason,
                        })
                      }
                      className="rounded-xl border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-sm font-semibold text-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {updateSegmentsMutation.isPending ? 'Updating lines' : 'Exclude selected lines'}
                    </button>
                    <button
                      type="button"
                      disabled={!selectedSpeakerOption || selectedSpeakerOption.includedIds.length === 0 || updateSegmentsMutation.isPending}
                      onClick={() =>
                        updateSegmentsMutation.mutate({
                          segment_ids: selectedSpeakerOption?.includedIds ?? [],
                          excluded_from_review: true,
                          exclusion_reason: bulkReason,
                        })
                      }
                      className="rounded-xl border border-amber-500/25 bg-amber-500/10 px-4 py-3 text-sm font-semibold text-amber-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {updateSegmentsMutation.isPending ? 'Updating lines' : 'Exclude whole speaker'}
                    </button>
                    <button
                      type="button"
                      disabled={!hasSelectedExcluded || updateSegmentsMutation.isPending}
                      onClick={() =>
                        updateSegmentsMutation.mutate({
                          segment_ids: selectedSegmentIds,
                          excluded_from_review: false,
                          exclusion_reason: null,
                        })
                      }
                      className="rounded-xl border border-[color:var(--color-border)] px-4 py-3 text-sm font-semibold text-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {updateSegmentsMutation.isPending ? 'Updating lines' : 'Restore selected lines'}
                    </button>
                    <button
                      type="button"
                      disabled={!selectedSpeakerOption || selectedSpeakerOption.excludedIds.length === 0 || updateSegmentsMutation.isPending}
                      onClick={() =>
                        updateSegmentsMutation.mutate({
                          segment_ids: selectedSpeakerOption?.excludedIds ?? [],
                          excluded_from_review: false,
                          exclusion_reason: null,
                        })
                      }
                      className="rounded-xl border border-[color:var(--color-border)] px-4 py-3 text-sm font-semibold text-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {updateSegmentsMutation.isPending ? 'Updating lines' : 'Restore whole speaker'}
                    </button>
                  </div>

                  <TranscriptReviewPane
                    transcriptPayload={transcriptQuery.data}
                    selectable
                    selectedSegmentIds={selectedSegmentIds}
                    onToggleSegment={(segmentId, checked) =>
                      setSelectedSegmentIds((current) =>
                        checked ? Array.from(new Set([...current, segmentId])) : current.filter((value) => value !== segmentId),
                      )
                    }
                    onToggleSelectAll={(segmentIds, checked) =>
                      setSelectedSegmentIds((current) => {
                        if (checked) {
                          return Array.from(new Set([...current, ...segmentIds]))
                        }
                        const visible = new Set(segmentIds)
                        return current.filter((value) => !visible.has(value))
                      })
                    }
                    showExcludedToggle
                  />
                </div>
              </Panel>

              <Panel eyebrow="Speaker tagging" title="Assign readable speaker names">
                <SpeakerAssignmentPanel
                  transcriptPayload={transcriptQuery.data}
                  disabled={assignSpeakerMutation.isPending}
                  onSave={(speakerLabel, speakerName) => assignSpeakerMutation.mutate({ speakerLabel, speakerName })}
                />
              </Panel>

              <Panel eyebrow="Transcript" title="Transcript with speaker labels">
                <TranscriptReviewPane transcriptPayload={transcriptQuery.data} />
              </Panel>
            </>
          )}

          <TechnicalSummary meeting={selectedMeeting} />
        </div>
      ) : null}
    </WorkflowStageLayout>
  )
}
