import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { Panel } from '@/components/Panel'
import { ExportTab } from '@/features/meetings/ExportTab'
import { FactGrid, TechnicalSummary, WorkflowStageLayout, WorkflowWarning, useWorkflowMeetings } from './shared'

const exportFilter = (meeting: { status: string }) => ['transcribed', 'extracting'].includes(meeting.status)

export function ExportWorkflowPage() {
  const queryClient = useQueryClient()
  const { filteredMeetings, selectedMeeting, selectedMeetingId, selectMeeting } = useWorkflowMeetings(exportFilter)

  const exportsQuery = useQuery({
    queryKey: ['exports', selectedMeetingId],
    queryFn: () => api.listExports(selectedMeetingId as number),
    enabled: !!selectedMeetingId,
  })

  const exportMutation = useMutation({
    mutationFn: (payload: Parameters<typeof api.createExport>[1]) => api.createExport(selectedMeetingId as number, payload),
    onSuccess: async () => selectedMeetingId && queryClient.invalidateQueries({ queryKey: ['exports', selectedMeetingId] }),
  })

  const openFolderMutation = useMutation({
    mutationFn: (exportRunId: number) => api.openExportFolder(exportRunId),
  })

  return (
    <WorkflowStageLayout
      title="Export"
      description="Create deliverables from the persisted reviewed data, choose the destination folder, and reopen completed exports when needed."
      sidebarTitle="Ready to export"
      emptyTitle="No meetings are ready for export"
      emptyBody="Meetings appear here once transcript review and minutes/task generation have produced something worth delivering."
      meetings={filteredMeetings}
      selectedMeetingId={selectedMeetingId}
      onSelectMeeting={selectMeeting}
      selectedMeeting={selectedMeeting}
    >
      {selectedMeeting ? (
        <div className="space-y-6">
          <WorkflowWarning meeting={selectedMeeting} />

          <Panel eyebrow="Delivery" title="Export workspace">
            <FactGrid
              items={[
                { label: 'Transcript', value: selectedMeeting.latest_transcription_run?.status || 'Not ready' },
                { label: 'Insights', value: selectedMeeting.latest_extraction_run?.status || 'Not started' },
                { label: 'Exports', value: `${exportsQuery.data?.length ?? 0}` },
                { label: 'Meeting', value: selectedMeeting.title },
              ]}
            />
          </Panel>

          <ExportTab
            meeting={selectedMeeting}
            exports={exportsQuery.data ?? []}
            exportPending={exportMutation.isPending}
            onCreateExport={(payload) => exportMutation.mutate(payload)}
            onOpenFolder={(exportRunId) => openFolderMutation.mutate(exportRunId)}
          />

          <TechnicalSummary meeting={selectedMeeting} />
        </div>
      ) : null}
    </WorkflowStageLayout>
  )
}
