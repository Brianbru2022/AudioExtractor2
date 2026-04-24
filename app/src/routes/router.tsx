import { createBrowserRouter, Navigate } from 'react-router-dom'
import { AppShell } from '@/layout/AppShell'
import { ImportsPage } from '@/features/imports/ImportsPage'
import { JobsPage } from '@/features/jobs/JobsPage'
import { MeetingDetailPage } from '@/features/meetings/MeetingDetailPage'
import { SettingsPage } from '@/features/settings/SettingsPage'
import { PreparationPage } from '@/features/workflow/PreparationPage'
import { TranscriptionPage } from '@/features/workflow/TranscriptionPage'
import { SpeakerTaggingPage } from '@/features/workflow/SpeakerTaggingPage'
import { MinutesTasksPage } from '@/features/workflow/MinutesTasksPage'
import { ExportWorkflowPage } from '@/features/workflow/ExportWorkflowPage'
import { HistoryPage } from '@/features/workflow/HistoryPage'

export const router = createBrowserRouter([
  {
    path: '/',
    element: <AppShell />,
    children: [
      { index: true, element: <Navigate to="/import" replace /> },
      { path: '/import', element: <ImportsPage /> },
      { path: '/imports', element: <Navigate to="/import" replace /> },
      { path: '/preparation', element: <PreparationPage /> },
      { path: '/transcription', element: <TranscriptionPage /> },
      { path: '/speaker-tagging', element: <SpeakerTaggingPage /> },
      { path: '/minutes-tasks', element: <MinutesTasksPage /> },
      { path: '/export', element: <ExportWorkflowPage /> },
      { path: '/history', element: <HistoryPage /> },
      { path: '/meetings/:meetingId', element: <MeetingDetailPage /> },
      { path: '/jobs', element: <JobsPage /> },
      { path: '/settings', element: <SettingsPage /> },
    ],
  },
  {
    path: '*',
    element: <Navigate to="/import" replace />,
  },
])
