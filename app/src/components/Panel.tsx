import type { PropsWithChildren, ReactNode } from 'react'
import clsx from 'clsx'

interface PanelProps extends PropsWithChildren {
  title?: string
  eyebrow?: string
  actions?: ReactNode
  className?: string
}

export function Panel({ title, eyebrow, actions, className, children }: PanelProps) {
  return (
    <section
      className={clsx(
        'rounded-2xl border border-[color:var(--color-border)] bg-[color:var(--color-panel)] shadow-[0_16px_60px_rgba(2,6,23,0.38)]',
        className,
      )}
    >
      {(title || eyebrow || actions) && (
        <header className="flex items-start justify-between gap-4 border-b border-[color:var(--color-border)] px-5 py-4">
          <div className="space-y-1">
            {eyebrow ? (
              <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-[color:var(--color-muted)]">
                {eyebrow}
              </p>
            ) : null}
            {title ? <h2 className="text-sm font-semibold text-slate-100">{title}</h2> : null}
          </div>
          {actions}
        </header>
      )}
      <div className="px-5 py-4">{children}</div>
    </section>
  )
}
