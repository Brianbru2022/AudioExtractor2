import { useState } from 'react'
import { Check, CircleAlert, Clock3, FileSearch2, ShieldCheck, X } from 'lucide-react'
import { formatDateTime, formatDuration } from '@/lib/format'
import { Panel } from '@/components/Panel'
import { StatusBadge } from '@/components/StatusBadge'
import type {
  ExtractedActionRecord,
  ExtractedDecisionRecord,
  ExtractedQuestionRecord,
  ExtractedRiskRecord,
  ExtractedTopicRecord,
  ExtractionRunDetail,
  InsightsPayload,
} from '@shared/contracts/api'

const insightTabs = ['Summary', 'Minutes', 'Actions', 'Decisions', 'Risks', 'Questions'] as const
type InsightTabKey = (typeof insightTabs)[number]
type InsightItem = ExtractedActionRecord | ExtractedDecisionRecord | ExtractedRiskRecord | ExtractedQuestionRecord
const actionPriorityOptions = [
  { value: '', label: 'No priority' },
  { value: 'low', label: 'Low' },
  { value: 'medium', label: 'Medium' },
  { value: 'high', label: 'High' },
  { value: 'critical', label: 'Critical' },
] as const

export function InsightsTab({
  insights,
  latestRun,
  onJumpToEvidence,
  onUpdateAction,
  onUpdateDecision,
  onUpdateRisk,
  onUpdateQuestion,
  onBulkAcceptActions,
}: {
  insights: InsightsPayload | undefined
  latestRun: ExtractionRunDetail | null | undefined
  onJumpToEvidence: (segmentId: number) => void
  onUpdateAction: (id: number, payload: Record<string, unknown>) => void
  onUpdateDecision: (id: number, payload: Record<string, unknown>) => void
  onUpdateRisk: (id: number, payload: Record<string, unknown>) => void
  onUpdateQuestion: (id: number, payload: Record<string, unknown>) => void
  onBulkAcceptActions: (ids: number[]) => void
}) {
  const [activeTab, setActiveTab] = useState<InsightTabKey>('Summary')
  const [searchText, setSearchText] = useState('')
  const [ownerFilter, setOwnerFilter] = useState('all')
  const [reviewFilter, setReviewFilter] = useState('all')
  const [inferenceFilter, setInferenceFilter] = useState('all')
  const [dueDateFilter, setDueDateFilter] = useState('all')

  if (!insights) {
    return (
      <Panel eyebrow="Insights" title="Evidence-Backed Insights">
        <EmptyState
          title={latestRun?.status === 'running' ? 'Extraction in progress' : 'Extraction has not been run yet'}
          message={
            latestRun?.status === 'running'
              ? `The latest extraction run is in progress with model ${latestRun.model}. Refresh continues automatically while the run completes.`
              : 'Run extraction after transcription to produce reviewable actions, decisions, risks, and questions with transcript evidence.'
          }
          meta={latestRun ? `Status ${latestRun.status} • Started ${formatDateTime(latestRun.started_at)}` : undefined}
        />
      </Panel>
    )
  }

  const owners = Array.from(new Set(insights.actions.map((action) => action.owner).filter(Boolean))) as string[]
  const filteredActions = insights.actions.filter((action) => {
    const ownerMatch = ownerFilter === 'all' ? true : action.owner === ownerFilter
    const reviewMatch = reviewFilter === 'all' ? true : action.review_status === reviewFilter
    const inferenceMatch = inferenceFilter === 'all' ? true : action.explicit_or_inferred === inferenceFilter
    const dueDateMatch =
      dueDateFilter === 'all'
        ? true
        : dueDateFilter === 'with_due_date'
          ? Boolean(action.due_date)
          : !action.due_date
    const searchMatch = searchText.trim()
      ? [action.text, action.owner || '', action.due_date || ''].join(' ').toLowerCase().includes(searchText.trim().toLowerCase())
      : true
    return ownerMatch && reviewMatch && inferenceMatch && dueDateMatch && searchMatch
  })
  const actionReviewSummary = summarizeReview(insights.actions)

  return (
    <div className="space-y-5">
      <Panel eyebrow="Insights" title="Structured Extraction Review">
        <div className="grid grid-cols-[1.3fr_0.7fr] gap-4">
          <div className="grid grid-cols-6 gap-3">
            <Meta label="Status" value={insights.run.status} />
            <Meta label="Model" value={insights.run.model} />
            <Meta label="Pending Review" value={`${countNeedsReview(insights)}`} tone="warn" />
            <Meta label="Accepted" value={`${countAccepted(insights)}`} tone="good" />
            <Meta label="Evidence Links" value={`${countEvidence(insights)}`} />
            <Meta label="Artifacts" value={`${insights.run.artifacts.length}`} />
          </div>
          <div className="rounded-xl border border-[color:var(--color-border)] bg-slate-950/40 px-4 py-3">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[color:var(--color-muted)]">Run Metadata</p>
            <div className="mt-3 space-y-2 text-sm text-[color:var(--color-muted-strong)]">
              <Row label="Started" value={formatDateTime(insights.run.started_at)} compact />
              <Row label="Completed" value={formatDateTime(insights.run.completed_at)} compact />
              <Row label="Transcription run" value={`${insights.run.transcription_run_id}`} compact />
              <Row label="Artifacts" value={insights.run.artifacts.map((artifact) => artifact.role).join(', ') || '-'} compact />
            </div>
          </div>
        </div>
      </Panel>

      <div className="flex flex-wrap gap-2">
        {insightTabs.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className={[
              'rounded-xl px-4 py-2.5 text-sm font-semibold transition',
              activeTab === tab
                ? 'bg-emerald-400 text-slate-950'
                : 'border border-[color:var(--color-border)] bg-slate-950/40 text-slate-300',
            ].join(' ')}
          >
            {tab}
          </button>
        ))}
      </div>

      {activeTab === 'Summary' ? (
        <div className="grid grid-cols-[1.12fr_0.88fr] gap-5">
          <Panel eyebrow="Executive Summary" title="Evidence-Backed Summary">
            <p className="whitespace-pre-wrap text-sm leading-7 text-slate-100">
              {insights.summary?.summary_text || 'No summary has been generated yet.'}
            </p>
          </Panel>
          <Panel eyebrow="Review Health" title="Reviewer Attention">
            <div className="grid grid-cols-2 gap-3">
              <Meta label="Pending actions" value={`${actionReviewSummary.pending}`} tone="warn" />
              <Meta label="Accepted actions" value={`${actionReviewSummary.accepted}`} tone="good" />
              <Meta label="Rejected items" value={`${countRejected(insights)}`} tone="danger" />
              <Meta label="Inferred items" value={`${countInferred(insights)}`} />
            </div>
            <div className="mt-4 space-y-3">
              {insights.topics.length === 0 ? (
                <EmptyState title="No topics extracted" message="No evidence-backed discussion topics were extracted from the merged transcript." />
              ) : (
                insights.topics.map((topic) => <ReadonlyInsightCard key={topic.id} item={topic} onJumpToEvidence={onJumpToEvidence} />)
              )}
            </div>
          </Panel>
        </div>
      ) : null}

      {activeTab === 'Minutes' ? (
        <Panel eyebrow="Formal Minutes" title="Review Minutes">
          <p className="whitespace-pre-wrap text-sm leading-7 text-slate-100">
            {insights.summary?.minutes_text || 'No minutes have been generated yet.'}
          </p>
        </Panel>
      ) : null}

      {activeTab === 'Actions' ? (
        <div className="space-y-4">
          <Panel eyebrow="Actions" title="Action Review Controls">
            <div className="grid grid-cols-[1fr_200px_200px_180px_180px_auto] gap-3">
              <input
                value={searchText}
                onChange={(event) => setSearchText(event.target.value)}
                placeholder="Search actions, owner, or due date"
                className="rounded-xl border border-[color:var(--color-border)] bg-slate-950/50 px-4 py-3 text-sm text-slate-100 outline-none placeholder:text-slate-500"
              />
              <select
                value={ownerFilter}
                onChange={(event) => setOwnerFilter(event.target.value)}
                className="rounded-xl border border-[color:var(--color-border)] bg-slate-950/50 px-4 py-3 text-sm text-slate-100 outline-none"
              >
                <option value="all">All owners</option>
                {owners.map((owner) => (
                  <option key={owner} value={owner}>
                    {owner}
                  </option>
                ))}
              </select>
              <select
                value={reviewFilter}
                onChange={(event) => setReviewFilter(event.target.value)}
                className="rounded-xl border border-[color:var(--color-border)] bg-slate-950/50 px-4 py-3 text-sm text-slate-100 outline-none"
              >
                <option value="all">All review states</option>
                <option value="pending">Needs review</option>
                <option value="accepted">Accepted</option>
                <option value="rejected">Rejected</option>
              </select>
              <select
                value={inferenceFilter}
                onChange={(event) => setInferenceFilter(event.target.value)}
                className="rounded-xl border border-[color:var(--color-border)] bg-slate-950/50 px-4 py-3 text-sm text-slate-100 outline-none"
              >
                <option value="all">Explicit + inferred</option>
                <option value="explicit">Explicit only</option>
                <option value="inferred">Inferred only</option>
              </select>
              <select
                value={dueDateFilter}
                onChange={(event) => setDueDateFilter(event.target.value)}
                className="rounded-xl border border-[color:var(--color-border)] bg-slate-950/50 px-4 py-3 text-sm text-slate-100 outline-none"
              >
                <option value="all">All due dates</option>
                <option value="with_due_date">With due date</option>
                <option value="without_due_date">Without due date</option>
              </select>
              <button
                disabled={filteredActions.length === 0}
                onClick={() => onBulkAcceptActions(filteredActions.map((action) => action.id))}
                className="inline-flex items-center justify-center gap-2 rounded-xl bg-emerald-400 px-4 py-3 text-sm font-semibold text-slate-950 disabled:cursor-not-allowed disabled:opacity-50"
              >
                <ShieldCheck className="h-4 w-4" />
                Accept Filtered
              </button>
            </div>
          </Panel>
          <InsightList items={filteredActions} onJumpToEvidence={onJumpToEvidence} onUpdate={onUpdateAction} showActionFields />
        </div>
      ) : null}

      {activeTab === 'Decisions' ? (
        <InsightList items={insights.decisions} onJumpToEvidence={onJumpToEvidence} onUpdate={onUpdateDecision} />
      ) : null}
      {activeTab === 'Risks' ? (
        <InsightList items={insights.risks} onJumpToEvidence={onJumpToEvidence} onUpdate={onUpdateRisk} />
      ) : null}
      {activeTab === 'Questions' ? (
        <InsightList items={insights.questions} onJumpToEvidence={onJumpToEvidence} onUpdate={onUpdateQuestion} />
      ) : null}
    </div>
  )
}

function InsightList({
  items,
  onJumpToEvidence,
  onUpdate,
  showActionFields = false,
}: {
  items: Array<ExtractedActionRecord | ExtractedDecisionRecord | ExtractedRiskRecord | ExtractedQuestionRecord>
  onJumpToEvidence: (segmentId: number) => void
  onUpdate: (id: number, payload: Record<string, unknown>) => void
  showActionFields?: boolean
}) {
  if (items.length === 0) {
    return (
      <EmptyState
        title="No evidence-backed items"
        message="The current filters returned no review items. Adjust the filters or rerun extraction after transcript review changes."
      />
    )
  }

  return (
    <div className="space-y-4">
      {items.map((item) => (
        <EditableInsightCard
          key={item.id}
          item={item}
          onJumpToEvidence={onJumpToEvidence}
          onUpdate={onUpdate}
          showActionFields={showActionFields}
        />
      ))}
    </div>
  )
}

function EditableInsightCard({
  item,
  onJumpToEvidence,
  onUpdate,
  showActionFields,
}: {
  item: InsightItem
  onJumpToEvidence: (segmentId: number) => void
  onUpdate: (id: number, payload: Record<string, unknown>) => void
  showActionFields: boolean
}) {
  const [draftText, setDraftText] = useState(item.text)
  const [draftOwner, setDraftOwner] = useState('owner' in item ? item.owner || '' : '')
  const [draftDueDate, setDraftDueDate] = useState('due_date' in item ? item.due_date || '' : '')
  const [draftPriority, setDraftPriority] = useState('priority' in item ? item.priority || '' : '')

  const reviewVariant = item.review_status === 'accepted' ? 'good' : item.review_status === 'rejected' ? 'danger' : 'warn'
  const showNeedsReview = item.review_status === 'pending'

  return (
    <div
      className={[
        'rounded-2xl border p-4',
        reviewVariant === 'good'
          ? 'border-emerald-500/30 bg-emerald-500/5'
          : reviewVariant === 'danger'
            ? 'border-red-500/30 bg-red-500/5'
            : 'border-amber-500/30 bg-amber-500/5',
      ].join(' ')}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1 space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={item.review_status} />
            <span className="rounded-full border border-[color:var(--color-border)] px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-cyan-100">
              {item.explicit_or_inferred}
            </span>
            <span className="text-xs text-[color:var(--color-muted)]">{Math.round(item.confidence * 100)}% confidence</span>
            <span className="text-xs text-[color:var(--color-muted)]">{item.evidence_count ?? item.evidence.length} evidence links</span>
            {showNeedsReview ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-amber-500/12 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-amber-100">
                <CircleAlert className="h-3.5 w-3.5" />
                Needs review
              </span>
            ) : null}
          </div>

          {item.review_hints && item.review_hints.length > 0 ? (
            <div className="flex flex-wrap gap-2">
              {item.review_hints.map((hint) => (
                <span
                  key={`${item.id}-${hint}`}
                  className="rounded-full border border-amber-500/20 bg-amber-500/8 px-2.5 py-1 text-[11px] font-medium text-amber-100"
                >
                  {hint}
                </span>
              ))}
            </div>
          ) : null}

          <textarea
            value={draftText}
            onChange={(event) => setDraftText(event.target.value)}
            className="min-h-[88px] w-full rounded-xl border border-[color:var(--color-border)] bg-slate-950/70 px-3 py-3 text-sm text-slate-100 outline-none"
          />

          {showActionFields ? (
            <div className="grid grid-cols-3 gap-3">
              <input
                value={draftOwner}
                onChange={(event) => setDraftOwner(event.target.value)}
                placeholder="Owner"
                className="rounded-xl border border-[color:var(--color-border)] bg-slate-950/70 px-3 py-3 text-sm text-slate-100 outline-none"
              />
              <input
                type="date"
                value={draftDueDate}
                onChange={(event) => setDraftDueDate(event.target.value)}
                className="rounded-xl border border-[color:var(--color-border)] bg-slate-950/70 px-3 py-3 text-sm text-slate-100 outline-none"
              />
              <select
                value={draftPriority}
                onChange={(event) => setDraftPriority(event.target.value)}
                className="rounded-xl border border-[color:var(--color-border)] bg-slate-950/70 px-3 py-3 text-sm text-slate-100 outline-none"
              >
                {actionPriorityOptions.map((option) => (
                  <option key={option.value || 'none'} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          ) : null}

          <EvidenceList evidence={item.evidence} onJumpToEvidence={onJumpToEvidence} />
        </div>

        <div className="flex shrink-0 flex-col gap-2">
          <button
            onClick={() => onUpdate(item.id, buildUpdatePayload(draftText, draftOwner, draftDueDate, draftPriority, 'accepted', showActionFields))}
            className="inline-flex items-center gap-2 rounded-xl bg-emerald-400 px-3 py-2 text-sm font-semibold text-slate-950"
          >
            <Check className="h-4 w-4" />
            Accept
          </button>
          <button
            onClick={() => onUpdate(item.id, buildUpdatePayload(draftText, draftOwner, draftDueDate, draftPriority, 'pending', showActionFields))}
            className="inline-flex items-center gap-2 rounded-xl border border-[color:var(--color-border)] bg-slate-950/60 px-3 py-2 text-sm font-semibold text-slate-100"
          >
            <Clock3 className="h-4 w-4" />
            Pending
          </button>
          <button
            onClick={() => onUpdate(item.id, buildUpdatePayload(draftText, draftOwner, draftDueDate, draftPriority, 'rejected', showActionFields))}
            className="inline-flex items-center gap-2 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm font-semibold text-red-100"
          >
            <X className="h-4 w-4" />
            Reject
          </button>
        </div>
      </div>
    </div>
  )
}

function ReadonlyInsightCard({
  item,
  onJumpToEvidence,
}: {
  item: ExtractedTopicRecord
  onJumpToEvidence: (segmentId: number) => void
}) {
  return (
    <div className="rounded-2xl border border-[color:var(--color-border)] bg-slate-950/40 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-[color:var(--color-border)] px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-cyan-100">
          {item.explicit_or_inferred}
        </span>
        <span className="text-xs text-[color:var(--color-muted)]">{Math.round(item.confidence * 100)}% confidence</span>
        {item.review_status === 'pending' ? (
          <span className="rounded-full bg-amber-500/12 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-amber-100">
            Needs review
          </span>
        ) : null}
      </div>
      <p className="mt-3 text-sm leading-6 text-slate-100">{item.text}</p>
      <EvidenceList evidence={item.evidence} onJumpToEvidence={onJumpToEvidence} />
    </div>
  )
}

function EvidenceList({
  evidence,
  onJumpToEvidence,
}: {
  evidence: InsightsPayload['actions'][number]['evidence']
  onJumpToEvidence: (segmentId: number) => void
}) {
  return (
    <div className="space-y-2">
      {evidence.map((entry) => (
        <button
          key={entry.id}
          onClick={() => entry.transcript_segment_id && onJumpToEvidence(entry.transcript_segment_id)}
          className="flex w-full items-start justify-between gap-4 rounded-xl border border-cyan-500/20 bg-cyan-500/6 px-3 py-3 text-left transition hover:border-cyan-400/40 hover:bg-cyan-500/10"
        >
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2 text-xs text-cyan-100">
              <span>
                {formatDuration(entry.start_ms)} to {formatDuration(entry.end_ms)}
              </span>
              {entry.speaker_label ? <span>{entry.speaker_label}</span> : null}
              {entry.confidence !== null ? <span>{Math.round(entry.confidence * 100)}% evidence confidence</span> : null}
            </div>
            {entry.quote_snippet ? (
              <p className="mt-2 line-clamp-3 text-sm leading-6 text-slate-100">{entry.quote_snippet}</p>
            ) : null}
          </div>
          <div className="inline-flex items-center gap-1 rounded-full border border-cyan-500/30 px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-100">
            <FileSearch2 className="h-3.5 w-3.5" />
            Jump
          </div>
        </button>
      ))}
    </div>
  )
}

function buildUpdatePayload(
  draftText: string,
  draftOwner: string,
  draftDueDate: string,
  draftPriority: string,
  reviewStatus: 'accepted' | 'pending' | 'rejected',
  showActionFields: boolean,
) {
  return {
    text: draftText,
    ...(showActionFields
      ? {
          owner: draftOwner || null,
          due_date: draftDueDate || null,
          priority: draftPriority || null,
        }
      : {}),
    review_status: reviewStatus,
  }
}

function summarizeReview(items: ExtractedActionRecord[]) {
  return items.reduce(
    (summary, item) => {
      summary[item.review_status] += 1
      return summary
    },
    { pending: 0, accepted: 0, rejected: 0 } as Record<'pending' | 'accepted' | 'rejected', number>,
  )
}

function countNeedsReview(insights: InsightsPayload) {
  return [...insights.actions, ...insights.decisions, ...insights.risks, ...insights.questions, ...insights.topics].filter(
    (item) => item.review_status === 'pending',
  ).length
}

function countAccepted(insights: InsightsPayload) {
  return [...insights.actions, ...insights.decisions, ...insights.risks, ...insights.questions].filter(
    (item) => item.review_status === 'accepted',
  ).length
}

function countRejected(insights: InsightsPayload) {
  return [...insights.actions, ...insights.decisions, ...insights.risks, ...insights.questions].filter(
    (item) => item.review_status === 'rejected',
  ).length
}

function countInferred(insights: InsightsPayload) {
  return [...insights.actions, ...insights.decisions, ...insights.risks, ...insights.questions, ...insights.topics].filter(
    (item) => item.explicit_or_inferred === 'inferred',
  ).length
}

function countEvidence(insights: InsightsPayload) {
  return [...insights.actions, ...insights.decisions, ...insights.risks, ...insights.questions, ...insights.topics].reduce(
    (count, item) => count + item.evidence.length,
    0,
  )
}

function EmptyState({
  title,
  message,
  meta,
}: {
  title: string
  message: string
  meta?: string
}) {
  return (
    <div className="rounded-2xl border border-dashed border-[color:var(--color-border-strong)] bg-slate-950/30 px-8 py-14 text-center">
      <p className="text-sm font-semibold text-slate-100">{title}</p>
      <p className="mt-3 text-sm leading-6 text-[color:var(--color-muted)]">{message}</p>
      {meta ? <p className="mt-3 text-xs uppercase tracking-[0.16em] text-[color:var(--color-muted)]">{meta}</p> : null}
    </div>
  )
}

function Meta({
  label,
  value,
  tone = 'default',
}: {
  label: string
  value: string
  tone?: 'default' | 'warn' | 'good' | 'danger'
}) {
  const toneClass =
    tone === 'warn'
      ? 'text-amber-100'
      : tone === 'good'
        ? 'text-emerald-100'
        : tone === 'danger'
          ? 'text-red-100'
          : 'text-slate-100'

  return (
    <div className="rounded-xl border border-[color:var(--color-border)] bg-slate-950/40 px-4 py-3">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[color:var(--color-muted)]">{label}</p>
      <p className={`mt-2 text-sm font-semibold ${toneClass}`}>{value}</p>
    </div>
  )
}

function Row({
  label,
  value,
  compact = false,
}: {
  label: string
  value: string
  compact?: boolean
}) {
  return (
    <div className={`flex items-center justify-between gap-4 ${compact ? 'text-xs' : 'text-sm'}`}>
      <span className="text-[color:var(--color-muted)]">{label}</span>
      <span className="text-right font-medium text-slate-100">{value}</span>
    </div>
  )
}
