import { create } from 'zustand'

type NavKey =
  | 'import'
  | 'preparation'
  | 'transcription'
  | 'speaker_tagging'
  | 'minutes_tasks'
  | 'export'
  | 'history'
  | 'settings'

interface ImportDraft {
  sourcePath: string
  importMode: 'reference' | 'managed_copy'
  title: string
  meetingDate: string
  project: string
  notes: string
  attendees: string
  circulation: string
}

interface UiState {
  activeNav: NavKey
  importDraft: ImportDraft
  lastWorkflowMeetingId: number | null
  setActiveNav: (nav: NavKey) => void
  updateImportDraft: (patch: Partial<ImportDraft>) => void
  resetImportDraft: () => void
  setLastWorkflowMeetingId: (meetingId: number | null) => void
}

const defaultImportDraft: ImportDraft = {
  sourcePath: '',
  importMode: 'reference',
  title: '',
  meetingDate: '',
  project: '',
  notes: '',
  attendees: '',
  circulation: '',
}

export const useUiStore = create<UiState>((set) => ({
  activeNav: 'import',
  importDraft: defaultImportDraft,
  lastWorkflowMeetingId: null,
  setActiveNav: (activeNav) => set({ activeNav }),
  updateImportDraft: (patch) =>
    set((state) => ({
      importDraft: {
        ...state.importDraft,
        ...patch,
      },
    })),
  resetImportDraft: () => set({ importDraft: defaultImportDraft }),
  setLastWorkflowMeetingId: (lastWorkflowMeetingId) => set({ lastWorkflowMeetingId }),
}))
