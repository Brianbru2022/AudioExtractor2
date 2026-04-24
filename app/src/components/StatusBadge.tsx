import clsx from 'clsx'

const styles: Record<string, string> = {
  draft: 'border-slate-700/80 bg-slate-900/80 text-slate-300',
  imported: 'border-cyan-500/25 bg-cyan-500/10 text-cyan-200',
  preprocessing: 'border-amber-500/25 bg-amber-500/10 text-amber-200',
  prepared: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200',
  transcribing: 'border-fuchsia-500/25 bg-fuchsia-500/10 text-fuchsia-200',
  transcribed: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-100',
  failed: 'border-red-500/25 bg-red-500/10 text-red-200',
  queued: 'border-slate-700/80 bg-slate-900/80 text-slate-300',
  pending: 'border-slate-700/80 bg-slate-900/80 text-slate-300',
  running: 'border-amber-500/25 bg-amber-500/10 text-amber-200',
  completed: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-200',
  completed_with_failures: 'border-amber-500/25 bg-amber-500/10 text-amber-100',
  recovered: 'border-emerald-500/25 bg-emerald-500/10 text-emerald-100',
  cancelled: 'border-slate-700/80 bg-slate-900/80 text-slate-300',
}

export function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={clsx(
        'inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.16em]',
        styles[status] ?? 'border-slate-700/80 bg-slate-900/80 text-slate-300',
      )}
    >
      {status}
    </span>
  )
}
