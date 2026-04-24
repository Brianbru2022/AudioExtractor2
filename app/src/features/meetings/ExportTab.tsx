import { useMemo, useState } from 'react'
import { Download, ExternalLink, FileArchive, FileSpreadsheet, FileText } from 'lucide-react'
import { formatDateTime } from '@/lib/format'
import { Panel } from '@/components/Panel'
import { StatusBadge } from '@/components/StatusBadge'
import { selectDirectory } from '@/lib/tauri'
import type { CreateExportRequest, ExportFormat, ExportProfile, ExportRunRecord, MeetingDetail } from '@shared/contracts/api'

const exportProfiles: Array<{
  export_profile: ExportProfile
  title: string
  description: string
  formats: ExportFormat[]
  icon: typeof FileText
}> = [
  {
    export_profile: 'formal_minutes_pack',
    title: 'Formal Minutes Pack',
    description: 'DOCX or PDF minutes package using persisted summary, minutes, and reviewed insights.',
    formats: ['docx', 'pdf'],
    icon: FileText,
  },
  {
    export_profile: 'action_register',
    title: 'Action Register',
    description: 'Structured action export for operational follow-up in CSV or XLSX.',
    formats: ['csv', 'xlsx'],
    icon: FileSpreadsheet,
  },
  {
    export_profile: 'full_archive',
    title: 'Full Archive',
    description: 'Structured JSON archive containing metadata, transcript, extraction output, and evidence mappings.',
    formats: ['json'],
    icon: FileArchive,
  },
  {
    export_profile: 'transcript_export',
    title: 'Merged Transcript',
    description: 'Readable TXT export of the persisted merged transcript with timestamps and speaker labels.',
    formats: ['txt'],
    icon: FileText,
  },
]

export function ExportTab({
  meeting,
  exports,
  exportPending,
  onCreateExport,
  onOpenFolder,
}: {
  meeting: MeetingDetail
  exports: ExportRunRecord[]
  exportPending: boolean
  onCreateExport: (payload: CreateExportRequest) => void
  onOpenFolder: (exportRunId: number) => void
}) {
  const [selectedProfile, setSelectedProfile] = useState<ExportProfile>('formal_minutes_pack')
  const profile = exportProfiles.find((item) => item.export_profile === selectedProfile) ?? exportProfiles[0]
  const [selectedFormat, setSelectedFormat] = useState<ExportFormat>(profile.formats[0])
  const [reviewedOnly, setReviewedOnly] = useState(true)
  const [includeEvidenceAppendix, setIncludeEvidenceAppendix] = useState(true)
  const [includeTranscriptAppendix, setIncludeTranscriptAppendix] = useState(false)
  const [includeConfidenceFlags, setIncludeConfidenceFlags] = useState(false)
  const [outputDirectory, setOutputDirectory] = useState<string | null>(null)
  const [directoryError, setDirectoryError] = useState<string | null>(null)

  const exportSupport = useMemo(() => {
    const hasTranscript = ['completed', 'completed_with_failures', 'recovered'].includes(meeting.latest_transcription_run?.status ?? '')
    const hasExtraction = meeting.latest_extraction_run?.status === 'completed'
    return {
      hasTranscript,
      hasExtraction,
      canFormalMinutes: hasExtraction && Boolean(meeting.latest_extraction_run?.summary),
      canActions: hasExtraction,
      canArchive: hasTranscript,
      canTranscript: hasTranscript,
    }
  }, [meeting])

  const canExport =
    !exportPending &&
    ((selectedProfile === 'formal_minutes_pack' && exportSupport.canFormalMinutes) ||
      (selectedProfile === 'action_register' && exportSupport.canActions) ||
      (selectedProfile === 'full_archive' && exportSupport.canArchive) ||
      (selectedProfile === 'transcript_export' && exportSupport.canTranscript))

  const lastExport = exports[0] ?? null

  const handleProfileChange = (next: ExportProfile) => {
    const nextProfile = exportProfiles.find((item) => item.export_profile === next) ?? exportProfiles[0]
    setSelectedProfile(next)
    setSelectedFormat(nextProfile.formats[0])
  }

  return (
    <div className="grid grid-cols-[1.02fr_0.98fr] gap-6">
      <div className="space-y-6">
        <Panel eyebrow="Export Profiles" title="Operational Delivery">
          <div className="space-y-3">
            {exportProfiles.map((item) => {
              const Icon = item.icon
              const active = item.export_profile === selectedProfile
              return (
                <button
                  key={item.export_profile}
                  onClick={() => handleProfileChange(item.export_profile)}
                  className={[
                    'flex w-full items-start gap-4 rounded-2xl border px-4 py-4 text-left transition',
                    active
                      ? 'border-cyan-400/40 bg-cyan-500/8'
                      : 'border-[color:var(--color-border)] bg-slate-950/30 hover:bg-slate-950/50',
                  ].join(' ')}
                >
                  <div className="rounded-xl bg-slate-950/70 p-3">
                    <Icon className="h-5 w-5 text-cyan-200" />
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-slate-100">{item.title}</p>
                    <p className="mt-1 text-sm leading-6 text-[color:var(--color-muted-strong)]">{item.description}</p>
                    <p className="mt-2 text-[11px] uppercase tracking-[0.16em] text-cyan-200">
                      Formats {item.formats.join(' / ')}
                    </p>
                  </div>
                </button>
              )
            })}
          </div>
        </Panel>

        <Panel eyebrow="History" title="Export History">
          {exports.length === 0 ? (
            <EmptyState message="No exports have been generated for this meeting yet." />
          ) : (
            <div className="space-y-3">
              {exports.map((exportRun) => (
                <div key={exportRun.id} className="rounded-xl border border-[color:var(--color-border)] bg-slate-950/40 px-4 py-3">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-slate-100">
                        {exportRun.export_profile} / {exportRun.format}
                      </p>
                      <p className="mt-1 text-xs text-[color:var(--color-muted)]">{exportRun.file_path}</p>
                    </div>
                    <StatusBadge status={exportRun.status} />
                  </div>
                  <div className="mt-3 flex items-center justify-between gap-4 text-xs text-[color:var(--color-muted-strong)]">
                    <span>Completed {formatDateTime(exportRun.completed_at || exportRun.created_at)}</span>
                    <button
                      disabled={exportRun.status !== 'completed'}
                      onClick={() => onOpenFolder(exportRun.id)}
                      className="inline-flex items-center gap-2 rounded-lg border border-[color:var(--color-border)] bg-slate-950/60 px-3 py-2 font-semibold text-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                      Open folder
                    </button>
                  </div>
                  {exportRun.error_message ? <p className="mt-2 text-xs text-red-300">{exportRun.error_message}</p> : null}
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      <div className="space-y-6">
        <Panel eyebrow="Export Options" title="Create Export">
          <div className="grid grid-cols-2 gap-3">
            <Meta label="Meeting" value={meeting.title} />
            <Meta label="Last export" value={lastExport ? formatDateTime(lastExport.completed_at || lastExport.created_at) : 'Never'} />
            <Meta label="Transcript" value={exportSupport.hasTranscript ? 'Available' : 'Not available'} />
            <Meta label="Insights" value={exportSupport.hasExtraction ? 'Available' : 'Not available'} />
          </div>

          <div className="mt-5 grid grid-cols-2 gap-3">
            <label className="space-y-2">
              <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[color:var(--color-muted)]">Profile</span>
              <select
                value={selectedProfile}
                onChange={(event) => handleProfileChange(event.target.value as ExportProfile)}
                className="w-full rounded-xl border border-[color:var(--color-border)] bg-slate-950/60 px-4 py-3 text-sm text-slate-100 outline-none"
              >
                {exportProfiles.map((item) => (
                  <option key={item.export_profile} value={item.export_profile}>
                    {item.title}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-2">
              <span className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[color:var(--color-muted)]">Format</span>
              <select
                value={selectedFormat}
                onChange={(event) => setSelectedFormat(event.target.value as ExportFormat)}
                className="w-full rounded-xl border border-[color:var(--color-border)] bg-slate-950/60 px-4 py-3 text-sm text-slate-100 outline-none"
              >
                {profile.formats.map((format) => (
                  <option key={format} value={format}>
                    {format.toUpperCase()}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="mt-5 grid grid-cols-2 gap-3">
            <Toggle label="Reviewed only" checked={reviewedOnly} onChange={setReviewedOnly} />
            <Toggle label="Include evidence appendix (quotes and timestamps)" checked={includeEvidenceAppendix} onChange={setIncludeEvidenceAppendix} />
            <Toggle label="Include transcript appendix" checked={includeTranscriptAppendix} onChange={setIncludeTranscriptAppendix} />
            <Toggle label="Include confidence flags" checked={includeConfidenceFlags} onChange={setIncludeConfidenceFlags} />
          </div>

          <div className="mt-5 rounded-xl border border-[color:var(--color-border)] bg-slate-950/40 px-4 py-4 text-sm text-[color:var(--color-muted-strong)]">
            <p className="font-semibold text-slate-100">Selected export</p>
            <p className="mt-2 leading-6">
              {profile.title} in {selectedFormat.toUpperCase()} generated from persisted meeting, transcript, and extraction records.
            </p>
          </div>

          <div className="mt-5 rounded-xl border border-[color:var(--color-border)] bg-slate-950/40 px-4 py-4">
            <div className="flex items-center justify-between gap-4">
              <div>
                <p className="text-sm font-semibold text-slate-100">Export destination</p>
                <p className="mt-1 text-sm text-[color:var(--color-muted-strong)]">
                  {outputDirectory ? outputDirectory : `Default: storage/exports/meeting_${meeting.id}`}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={async () => {
                    try {
                      const selected = await selectDirectory()
                      if (selected) {
                        setOutputDirectory(selected)
                        setDirectoryError(null)
                      }
                    } catch (error) {
                      setDirectoryError(error instanceof Error ? error.message : String(error))
                    }
                  }}
                  className="inline-flex items-center gap-2 rounded-lg border border-[color:var(--color-border)] bg-slate-950/60 px-3 py-2 text-xs font-semibold text-slate-100"
                >
                  Choose folder
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setOutputDirectory(null)
                    setDirectoryError(null)
                  }}
                  className="inline-flex items-center gap-2 rounded-lg border border-[color:var(--color-border)] bg-slate-950/40 px-3 py-2 text-xs font-semibold text-[color:var(--color-muted-strong)]"
                >
                  Use default
                </button>
              </div>
            </div>
            {directoryError ? <p className="mt-3 text-xs text-amber-200">{directoryError}</p> : null}
          </div>

          <div className="mt-5 flex items-center justify-between gap-4">
            <div className="text-sm text-[color:var(--color-muted)]">
              Files are written to <span className="font-semibold text-slate-100">{outputDirectory || `storage/exports/meeting_${meeting.id}`}</span>.
            </div>
            <button
              disabled={!canExport}
              onClick={() =>
                onCreateExport({
                  export_profile: selectedProfile,
                  format: selectedFormat,
                  reviewed_only: reviewedOnly,
                  include_evidence_appendix: includeEvidenceAppendix,
                  include_transcript_appendix: includeTranscriptAppendix,
                  include_confidence_flags: includeConfidenceFlags,
                  output_directory: outputDirectory,
                })
              }
              className="inline-flex items-center gap-2 rounded-xl bg-cyan-400 px-4 py-3 text-sm font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Download className="h-4 w-4" />
              {exportPending ? 'Exporting' : 'Create export'}
            </button>
          </div>

          {!canExport ? (
            <p className="mt-3 text-xs text-amber-200">
              {selectedProfile === 'formal_minutes_pack'
                ? 'Formal minutes export requires a completed extraction run with persisted summary/minutes.'
                : selectedProfile === 'action_register'
                  ? 'Action register export requires persisted extracted actions.'
                  : selectedProfile === 'full_archive'
                    ? 'Full archive export requires a merged transcript.'
                    : 'Transcript export requires a merged transcript.'}
            </p>
          ) : null}
        </Panel>
      </div>
    </div>
  )
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string
  checked: boolean
  onChange: (value: boolean) => void
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className={[
        'flex items-center justify-between rounded-xl border px-4 py-3 text-left text-sm transition',
        checked
          ? 'border-cyan-400/40 bg-cyan-500/10 text-slate-100'
          : 'border-[color:var(--color-border)] bg-slate-950/40 text-[color:var(--color-muted-strong)]',
      ].join(' ')}
    >
      <span>{label}</span>
      <span className="text-xs font-semibold uppercase tracking-[0.16em]">{checked ? 'On' : 'Off'}</span>
    </button>
  )
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-[color:var(--color-border)] bg-slate-950/40 px-4 py-3">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[color:var(--color-muted)]">{label}</p>
      <p className="mt-2 text-sm font-semibold text-slate-100">{value}</p>
    </div>
  )
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-[color:var(--color-border-strong)] bg-slate-950/30 px-8 py-14 text-center text-sm text-[color:var(--color-muted)]">
      {message}
    </div>
  )
}
