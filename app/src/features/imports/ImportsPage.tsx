import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderOpen, Upload } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { api } from '@/lib/api'
import { selectSourceFile, subscribeToFileDrops } from '@/lib/tauri'
import { Panel } from '@/components/Panel'
import { useUiStore } from '@/store/ui-store'

function parsePersonList(value: string) {
  return value
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean)
}

export function ImportsPage() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const importDraft = useUiStore((state) => state.importDraft)
  const updateImportDraft = useUiStore((state) => state.updateImportDraft)
  const resetImportDraft = useUiStore((state) => state.resetImportDraft)
  const [browseError, setBrowseError] = useState<string | null>(null)
  const [inspectionError, setInspectionError] = useState<string | null>(null)
  const lastInspectedPath = useRef<string>('')

  const settingsQuery = useQuery({
    queryKey: ['settings'],
    queryFn: api.getSettings,
  })

  const projectOptions = useMemo(() => {
    const record = settingsQuery.data?.find((setting) => setting.key === 'project_categories')
    const rawProjects = Array.isArray(record?.value_json?.projects) ? (record?.value_json?.projects as unknown[]) : []
    return rawProjects.filter((value): value is string => typeof value === 'string' && value.trim().length > 0)
  }, [settingsQuery.data])

  const importMutation = useMutation({
    mutationFn: api.importMeeting,
    onSuccess: async (response) => {
      resetImportDraft()
      await queryClient.invalidateQueries({ queryKey: ['meetings'] })
      navigate(`/preparation?meeting=${response.meeting.id}`)
    },
  })

  useEffect(() => {
    let unlisten: { (): void } | undefined
    void subscribeToFileDrops((paths) => {
      const path = paths.find(Boolean)
      if (path) {
        updateImportDraft({ sourcePath: path })
      }
    }).then((cleanup) => {
      unlisten = cleanup
    })

    return () => {
      unlisten?.()
    }
  }, [updateImportDraft])

  useEffect(() => {
    const path = importDraft.sourcePath.trim()
    const hasLikelyExtension = /\.(wav|mp3|m4a|flac|mp4|mov|mkv)$/i.test(path)
    if (!path || !hasLikelyExtension || path === lastInspectedPath.current) {
      return
    }

    const timer = window.setTimeout(async () => {
      try {
        const inspection = await api.inspectImportSource(path)
        lastInspectedPath.current = path
        setInspectionError(null)
        updateImportDraft({
          meetingDate: inspection.meeting_date,
          title: importDraft.title.trim().length > 0 ? importDraft.title : inspection.meeting_title,
        })
      } catch (error) {
        setInspectionError(error instanceof Error ? error.message : String(error))
      }
    }, 300)

    return () => window.clearTimeout(timer)
  }, [importDraft.sourcePath, importDraft.title, updateImportDraft])

  const canSubmit = useMemo(() => importDraft.sourcePath.trim().length > 0, [importDraft.sourcePath])

  return (
    <div className="space-y-6">
      <Panel eyebrow="Import" title="Bring in a meeting source">
        <div className="grid gap-6 xl:grid-cols-[1.05fr_0.95fr]">
          <div className="space-y-5">
            <div className="rounded-2xl border border-dashed border-cyan-400/30 bg-cyan-400/6 px-6 py-10">
              <p className="text-base font-semibold text-slate-100">Drop a meeting file here or browse from disk</p>
              <p className="mt-2 max-w-2xl text-sm leading-6 text-[color:var(--color-muted)]">
                Supported types: WAV, MP3, M4A, FLAC, MP4, MOV, MKV. The source stays untouched. Preparation later creates the normalized working audio and chunk artifacts locally.
              </p>
              <div className="mt-5 flex gap-3">
                <button
                  className="inline-flex items-center gap-2 rounded-xl bg-cyan-400 px-4 py-2.5 text-sm font-semibold text-slate-950"
                  onClick={async () => {
                    setBrowseError(null)
                    try {
                      const selected = await selectSourceFile()
                      if (selected) {
                        updateImportDraft({ sourcePath: selected })
                      }
                    } catch (error) {
                      const message = error instanceof Error ? error.message : 'Unable to open the file picker.'
                      setBrowseError(`Browse failed: ${message}`)
                    }
                  }}
                >
                  <FolderOpen className="h-4 w-4" />
                  Browse files
                </button>
              </div>
              {browseError ? <p className="mt-3 text-sm text-red-300">{browseError}</p> : null}
              {inspectionError ? <p className="mt-2 text-sm text-amber-200">{inspectionError}</p> : null}
            </div>

            <label className="block space-y-2">
              <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[color:var(--color-muted)]">Source path</span>
              <input
                value={importDraft.sourcePath}
                onChange={(event) => updateImportDraft({ sourcePath: event.target.value })}
                className="w-full rounded-xl border border-[color:var(--color-border)] bg-slate-950/60 px-4 py-3 text-sm text-slate-100 outline-none"
                placeholder="D:\\Meetings\\team-sync.mp4"
              />
            </label>

            <div className="grid gap-4 md:grid-cols-2">
              <SelectField
                label="Import mode"
                value={importDraft.importMode}
                onChange={(value) => updateImportDraft({ importMode: value as 'reference' | 'managed_copy' })}
                options={[
                  { value: 'reference', label: 'Reference original file' },
                  { value: 'managed_copy', label: 'Managed local copy' },
                ]}
              />
              <InputField
                label="Meeting date"
                type="date"
                value={importDraft.meetingDate}
                onChange={(value) => updateImportDraft({ meetingDate: value })}
              />
            </div>

            <div className="grid gap-4 md:grid-cols-2">
              <InputField label="Meeting title" value={importDraft.title} onChange={(value) => updateImportDraft({ title: value })} />
              <SelectField
                label="Project / category"
                value={importDraft.project}
                onChange={(value) => updateImportDraft({ project: value })}
                options={[
                  { value: '', label: projectOptions.length > 0 ? 'No project selected' : 'Add projects in Settings first' },
                  ...projectOptions.map((project) => ({ value: project, label: project })),
                ]}
              />
            </div>

            <label className="block space-y-2">
              <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[color:var(--color-muted)]">Notes</span>
              <textarea
                value={importDraft.notes}
                onChange={(event) => updateImportDraft({ notes: event.target.value })}
                rows={5}
                className="w-full rounded-xl border border-[color:var(--color-border)] bg-slate-950/60 px-4 py-3 text-sm text-slate-100 outline-none"
                placeholder="Optional context for later review."
              />
            </label>

            <div className="grid gap-4 md:grid-cols-2">
              <label className="block space-y-2">
                <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[color:var(--color-muted)]">Attendees</span>
                <textarea
                  value={importDraft.attendees}
                  onChange={(event) => updateImportDraft({ attendees: event.target.value })}
                  rows={5}
                  className="w-full rounded-xl border border-[color:var(--color-border)] bg-slate-950/60 px-4 py-3 text-sm text-slate-100 outline-none"
                  placeholder="One per line or comma separated"
                />
              </label>

              <label className="block space-y-2">
                <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[color:var(--color-muted)]">Circulation</span>
                <textarea
                  value={importDraft.circulation}
                  onChange={(event) => updateImportDraft({ circulation: event.target.value })}
                  rows={5}
                  className="w-full rounded-xl border border-[color:var(--color-border)] bg-slate-950/60 px-4 py-3 text-sm text-slate-100 outline-none"
                  placeholder="People who should receive the final minutes"
                />
              </label>
            </div>
          </div>

          <div className="space-y-4">
            <div className="rounded-2xl border border-[color:var(--color-border)] bg-slate-950/35 p-5">
              <p className="text-sm font-semibold text-slate-100">What happens next</p>
              <div className="mt-4 space-y-3 text-sm leading-6 text-[color:var(--color-muted-strong)]">
                <p>1. Import stores the meeting metadata and source-file record.</p>
                <p>2. Preparation runs separately as a background job when you choose it.</p>
                <p>3. The prepared meeting then moves into transcription, review, insights, and export.</p>
              </div>
              <p className="mt-4 text-xs text-[color:var(--color-muted)]">
                Meeting date defaults to the source file creation date and can still be adjusted before import. Attendees and circulation feed directly into the formal export pack.
              </p>
            </div>

            <div className="rounded-2xl border border-[color:var(--color-border)] bg-slate-950/35 p-5">
              <p className="text-sm font-semibold text-slate-100">Import modes</p>
              <div className="mt-4 space-y-3 text-sm leading-6 text-[color:var(--color-muted-strong)]">
                <p><span className="font-semibold text-slate-100">Reference</span> keeps the original file in place.</p>
                <p><span className="font-semibold text-slate-100">Managed copy</span> duplicates the source into app storage for safer long-term processing.</p>
              </div>
            </div>

            <div className="rounded-2xl border border-[color:var(--color-border)] bg-slate-950/40 p-5">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-sm font-semibold text-slate-100">Create meeting record</p>
                  <p className="mt-1 text-sm text-[color:var(--color-muted-strong)]">
                    Import now, then start preparation separately from the Meetings page.
                  </p>
                </div>
                <button
                  disabled={!canSubmit || importMutation.isPending}
                  onClick={() =>
                    importMutation.mutate({
                      source_path: importDraft.sourcePath,
                      import_mode: importDraft.importMode,
                      title: importDraft.title || undefined,
                      meeting_date: importDraft.meetingDate || null,
                      project: importDraft.project || null,
                      notes: importDraft.notes || null,
                      attendees: parsePersonList(importDraft.attendees),
                      circulation: parsePersonList(importDraft.circulation),
                    })
                  }
                  className="inline-flex items-center gap-2 rounded-xl bg-cyan-400 px-4 py-2.5 text-sm font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Upload className="h-4 w-4" />
                  {importMutation.isPending ? 'Importing' : 'Import meeting'}
                </button>
              </div>
              {importMutation.error ? <p className="mt-3 text-sm text-red-300">{(importMutation.error as Error).message}</p> : null}
            </div>
          </div>
        </div>
      </Panel>
    </div>
  )
}

function InputField({
  label,
  value,
  onChange,
  type = 'text',
}: {
  label: string
  value: string
  onChange: (value: string) => void
  type?: string
}) {
  return (
    <label className="block space-y-2">
      <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[color:var(--color-muted)]">{label}</span>
      <input
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-xl border border-[color:var(--color-border)] bg-slate-950/60 px-4 py-3 text-sm text-slate-100 outline-none"
      />
    </label>
  )
}

function SelectField({
  label,
  value,
  onChange,
  options,
}: {
  label: string
  value: string
  onChange: (value: string) => void
  options: Array<{ value: string; label: string }>
}) {
  return (
    <label className="block space-y-2">
      <span className="text-xs font-semibold uppercase tracking-[0.18em] text-[color:var(--color-muted)]">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-xl border border-[color:var(--color-border)] bg-slate-950/60 px-4 py-3 text-sm text-slate-100 outline-none"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  )
}
