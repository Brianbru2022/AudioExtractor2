import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { HardDriveDownload, Languages, Plus, Settings2, Trash2 } from 'lucide-react'
import { api } from '@/lib/api'
import { Panel } from '@/components/Panel'

export function SettingsPage() {
  const queryClient = useQueryClient()
  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: api.getSettings,
  })

  const [newProject, setNewProject] = useState('')

  const settings = settingsQuery.data ?? []
  const chunkDefaults = settings.find((setting) => setting.key === 'chunk_defaults')
  const transcriptionDefaults = settings.find((setting) => setting.key === 'transcription_defaults')
  const geminiDefaults = settings.find((setting) => setting.key === 'gemini_defaults')
  const projectCategorySetting = settings.find((setting) => setting.key === 'project_categories')
  const projects = useMemo(() => {
    const raw = projectCategorySetting?.value_json?.projects
    return Array.isArray(raw) ? raw.filter((value): value is string => typeof value === 'string' && value.trim().length > 0) : []
  }, [projectCategorySetting])

  const saveProjectsMutation = useMutation({
    mutationFn: (nextProjects: string[]) => api.updateSetting('project_categories', { projects: nextProjects }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['settings'] })
    },
  })

  const addProject = () => {
    const candidate = newProject.trim()
    if (!candidate) {
      return
    }
    const nextProjects = Array.from(new Set([...projects, candidate])).sort((a, b) => a.localeCompare(b))
    saveProjectsMutation.mutate(nextProjects)
    setNewProject('')
  }

  const removeProject = (project: string) => {
    saveProjectsMutation.mutate(projects.filter((entry) => entry !== project))
  }

  return (
    <div className="grid grid-cols-[0.9fr_1.1fr] gap-6">
      <div className="space-y-6">
        <Panel eyebrow="Workflow Settings" title="Project Categories">
          <div className="space-y-4">
            <p className="text-sm leading-6 text-[color:var(--color-muted-strong)]">
              Manage the project/category list used by the Import workflow. Imports now use this as a dropdown instead of free text.
            </p>

            <div className="flex gap-3">
              <input
                value={newProject}
                onChange={(event) => setNewProject(event.target.value)}
                placeholder="Add a project"
                className="min-w-0 flex-1 rounded-xl border border-[color:var(--color-border)] bg-slate-950/60 px-4 py-3 text-sm text-slate-100 outline-none"
              />
              <button
                onClick={addProject}
                disabled={saveProjectsMutation.isPending || newProject.trim().length === 0}
                className="inline-flex items-center gap-2 rounded-xl bg-cyan-400 px-4 py-3 text-sm font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <Plus className="h-4 w-4" />
                Add
              </button>
            </div>

            {projects.length === 0 ? (
              <div className="rounded-2xl border border-dashed border-[color:var(--color-border-strong)] bg-slate-950/25 px-5 py-8 text-center">
                <p className="text-sm font-semibold text-slate-100">No projects yet</p>
                <p className="mt-3 text-sm leading-6 text-[color:var(--color-muted)]">Add one or more projects here and they will appear in the Import dropdown.</p>
              </div>
            ) : (
              <div className="space-y-3">
                {projects.map((project) => (
                  <div key={project} className="flex items-center justify-between gap-3 rounded-xl border border-[color:var(--color-border)] bg-slate-950/35 px-4 py-3">
                    <span className="text-sm font-medium text-slate-100">{project}</span>
                    <button
                      onClick={() => removeProject(project)}
                      disabled={saveProjectsMutation.isPending}
                      className="inline-flex items-center gap-2 rounded-lg border border-red-500/25 bg-red-500/10 px-3 py-2 text-xs font-semibold text-red-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </Panel>

        <Panel eyebrow="Pipeline Defaults" title="Chunking Strategy">
          <SettingCard title="chunk_defaults" value={chunkDefaults?.value_json ?? {}} />
        </Panel>

        <Panel eyebrow="Storage" title="Runtime Layout">
          <div className="space-y-4 text-sm leading-6 text-[color:var(--color-muted-strong)]">
            <div className="flex items-start gap-3 rounded-xl border border-[color:var(--color-border)] bg-slate-950/40 p-4">
              <HardDriveDownload className="mt-0.5 h-4 w-4 text-cyan-200" />
              <div>
                <p className="font-semibold text-slate-100">Local storage folders</p>
                <p>`storage/db`, `storage/managed`, `storage/normalized`, `storage/chunks`, `storage/artifacts`, and `storage/logs` remain the local runtime roots for preprocessing and transcript artifacts.</p>
              </div>
            </div>
          </div>
        </Panel>
      </div>

      <div className="space-y-6">
        <Panel eyebrow="Google Cloud STT" title="Transcription Defaults">
          <div className="space-y-4">
            <SettingCard title="transcription_defaults" value={transcriptionDefaults?.value_json ?? {}} />
            <div className="rounded-xl border border-[color:var(--color-border)] bg-slate-950/40 p-4 text-sm text-[color:var(--color-muted-strong)]">
              <div className="flex items-center gap-2 text-slate-100">
                <Languages className="h-4 w-4 text-cyan-200" />
                <span className="font-semibold">Credential model</span>
              </div>
              <p className="mt-3">The worker expects Google Application Default Credentials by default, or a credentials file path reference. Raw credential JSON is not stored in SQLite.</p>
              <p className="mt-2">Speech-to-Text V2 chunk transcription uses a staging bucket for batch requests, while all transcript artifacts and stitched outputs remain tracked locally.</p>
            </div>
          </div>
        </Panel>

        <Panel eyebrow="Gemini API" title="Gemini Defaults">
          <div className="space-y-4">
            <SettingCard title="gemini_defaults" value={geminiDefaults?.value_json ?? {}} />
            <div className="rounded-xl border border-[color:var(--color-border)] bg-slate-950/40 p-4 text-sm text-[color:var(--color-muted-strong)]">
              <div className="flex items-center gap-2 text-slate-100">
                <Languages className="h-4 w-4 text-cyan-200" />
                <span className="font-semibold">Model naming</span>
              </div>
              <p className="mt-3">The current Gemini 3 text model names are preview IDs like `gemini-3-flash-preview` and `gemini-3.1-pro-preview`. There is not a literal `gemini-3.0` model id to send in the API request.</p>
              <p className="mt-2">This app keeps Gemini auth env-based or file-based. Raw API keys are not stored in SQLite.</p>
            </div>
          </div>
        </Panel>
      </div>
    </div>
  )
}

function SettingCard({ title, value }: { title: string; value: Record<string, unknown> }) {
  return (
    <div className="rounded-xl border border-[color:var(--color-border)] bg-slate-950/40 p-4">
      <div className="flex items-center gap-2 text-slate-100">
        <Settings2 className="h-4 w-4 text-cyan-200" />
        <span className="font-semibold">{title}</span>
      </div>
      <pre className="mt-3 overflow-auto rounded-xl bg-slate-950 px-3 py-3 text-xs text-cyan-100">
        {JSON.stringify(value, null, 2)}
      </pre>
    </div>
  )
}
