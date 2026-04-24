import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { AudioLines, ClipboardList, FileDown, FileOutput, History, Mic2, Settings2, Tags, Waves } from 'lucide-react'
import { useMemo } from 'react'
import { useUiStore } from '@/store/ui-store'

const navItems = [
  { to: '/import', label: 'Import', icon: FileDown, key: 'import' as const },
  { to: '/preparation', label: 'Preparation', icon: Waves, key: 'preparation' as const },
  { to: '/transcription', label: 'Transcription', icon: Mic2, key: 'transcription' as const },
  { to: '/speaker-tagging', label: 'Speaker Tagging', icon: Tags, key: 'speaker_tagging' as const },
  { to: '/minutes-tasks', label: 'Minutes & Tasks', icon: ClipboardList, key: 'minutes_tasks' as const },
  { to: '/export', label: 'Export', icon: FileOutput, key: 'export' as const },
  { to: '/history', label: 'History', icon: History, key: 'history' as const },
  { to: '/settings', label: 'Settings', icon: Settings2, key: 'settings' as const },
]

export function AppShell() {
  const location = useLocation()
  const setActiveNav = useUiStore((state) => state.setActiveNav)

  const pageTitle = useMemo(() => {
    if (location.pathname.startsWith('/meetings/')) {
      return 'Advanced Meeting View'
    }

    const currentItem = navItems.find((item) => location.pathname.startsWith(item.to))
    return currentItem?.label ?? 'Workspace'
  }, [location.pathname])

  return (
    <div className="flex min-h-screen bg-transparent text-slate-100">
      <aside className="flex w-[232px] shrink-0 flex-col border-r border-[color:var(--color-border)] bg-[color:var(--color-panel-strong)] px-4 py-5">
        <div className="flex items-center gap-3 border-b border-[color:var(--color-border)] px-2 pb-5">
          <div className="flex h-10 w-10 items-center justify-center rounded-2xl border border-cyan-400/20 bg-cyan-400/10 text-cyan-200">
            <AudioLines className="h-5 w-5" />
          </div>
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-cyan-200/80">Audio Extractor 2</p>
            <p className="text-sm font-semibold text-slate-100">Meeting Intelligence Prep</p>
          </div>
        </div>

        <nav className="mt-5 space-y-1.5">
          {navItems.map((item) => {
            const Icon = item.icon
            return (
              <NavLink
                key={item.to}
                to={item.to}
                onClick={() => setActiveNav(item.key)}
                className={({ isActive }) =>
                  [
                    'flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition',
                    isActive
                      ? 'border border-cyan-400/20 bg-cyan-400/12 text-cyan-100'
                      : 'border border-transparent text-slate-300 hover:border-slate-700 hover:bg-slate-900/70 hover:text-white',
                  ].join(' ')
                }
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </NavLink>
            )
          })}
        </nav>

        <div className="mt-auto rounded-2xl border border-[color:var(--color-border)] bg-slate-950/50 p-4">
          <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-[color:var(--color-muted)]">Workspace</p>
          <p className="mt-2 text-sm font-semibold text-slate-100">Workflow-First Navigation</p>
          <p className="mt-1 text-xs leading-5 text-[color:var(--color-muted)]">
            Move left to right through import, preparation, transcription, speaker tagging, minutes/tasks, and export. Technical diagnostics stay secondary.
          </p>
          <NavLink
            to="/jobs"
            className="mt-4 inline-flex rounded-lg border border-[color:var(--color-border)] px-3 py-2 text-xs font-semibold text-[color:var(--color-muted-strong)] hover:text-slate-100"
          >
            Open diagnostics
          </NavLink>
        </div>
      </aside>

      <main className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-10 border-b border-[color:var(--color-border)] bg-[rgba(5,10,17,0.92)] backdrop-blur-xl">
          <div className="flex items-center justify-between px-8 py-4">
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-[0.28em] text-[color:var(--color-muted)]">Current Workspace</p>
              <h1 className="mt-1 text-xl font-semibold tracking-tight text-slate-50">{pageTitle}</h1>
            </div>
            <div className="rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1.5 text-xs font-medium text-cyan-100">
              Windows Local Pipeline
            </div>
          </div>
        </header>

        <div className="flex-1 px-8 py-6">
          <Outlet />
        </div>
      </main>
    </div>
  )
}
