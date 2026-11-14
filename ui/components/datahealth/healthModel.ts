/**
 * Pure helpers of SYS › DATA (reports/terminal_v2/PLAN.md 1.4): the row types of GET /api/data/health and the
 * wording / ordering rules — counts, never a composite score. No imports: unit-tested under plain node by
 * ui/components/vol/__tests__/terminal_v2.check.ts; components/datahealth/api.ts re-exports it.
 */

export type HealthState = 'live' | 'fresh' | 'amber' | 'red' | 'gap'

export interface HealthRow {
  id: string; label: string; pages: string[]; publisher: string; published_ist: string | null; expected_by: string | null
  as_of: string | null; lag_sessions: number | null; state: HealthState | string; unrecoverable: boolean; job_id: string | null
  // last_run: a catalogued job that never ran comes back with all three fields null (SYS › DATA crashed on it, 5 Nov)
  last_run: { ts: string | null; status: string | null; ms: number | null } | null; next_run: string | null; catchup_at: string | null
  note: string; dictionary_anchor: string | null; badge?: string; max_age_sessions?: number | null
}
export interface DataHealth {
  as_of: string; rows: HealthRow[]; summary: { green: number; amber: number; red: number; gaps: number; rows?: number }
  last_session: string | null; catalog_source: string; inputs_unavailable: Record<string, string>; controller_online: boolean
  status?: string; service?: string; data_service?: { reachable: boolean }; note: string; badge?: string; ok?: boolean
}

const ORDER: Record<string, number> = { gap: 0, red: 1, amber: 2, live: 3, fresh: 4 }

/** Rows that are not fresh: amber + red + gap (the header chip's n). */
export function staleCount(h: Pick<DataHealth, 'summary' | 'rows'> | null | undefined): number {
  if (!h) return 0
  if (h.summary) return (h.summary.amber ?? 0) + (h.summary.red ?? 0) + (h.summary.gaps ?? 0)
  return (h.rows ?? []).filter(r => r.state === 'amber' || r.state === 'red' || r.state === 'gap').length
}

/** Worst first (gap → red → amber → live → fresh), then the most sessions behind, then the label. */
export function sortRows(rows: readonly HealthRow[]): HealthRow[] {
  return [...rows].sort((a, b) => (ORDER[a.state] ?? 9) - (ORDER[b.state] ?? 9)
    || (b.lag_sessions ?? -1) - (a.lag_sessions ?? -1) || a.label.localeCompare(b.label))
}

/** Rows a page reads (`pages[]` holds page codes: DERV, OMON, …); every row when `page` is empty. */
export function filterByPage(rows: readonly HealthRow[], page: string | null | undefined): HealthRow[] {
  if (!page) return [...rows]
  const p = page.toUpperCase()
  return rows.filter(r => (r.pages ?? []).some(x => String(x).toUpperCase() === p))
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const dm = (iso: string | null | undefined): string => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '')
  return m && +m[2] >= 1 && +m[2] <= 12 ? `${+m[3]} ${MONTHS[+m[2] - 1]}` : ''
}
const hm = (iso: string | null | undefined): string => {
  const m = /T(\d{2}):(\d{2})/.exec(iso ?? '')
  return m ? `${m[1]}:${m[2]}` : ''
}

/**
 * The honest sentence for a row when the server sent none: "stored 30 Oct · expected by 21:00 · 3 sessions behind ·
 * catch-up 19:30 tomorrow". No adjective, no score.
 */
/** The clause that says a gap is gone for good — appended to whatever the row says, never instead of it. */
function unrecoverableClause(r: HealthRow): string {
  return r.unrecoverable && (r.state === 'gap' || r.state === 'red')
    ? 'cannot be recovered later (session-bound capture)' : ''
}

export function rowSentence(r: HealthRow): string {
  // F6 (14 Nov 2026): this used to `return r.note` outright, and EVERY row carries a server note — so the
  // unrecoverable clause below was a dead branch. That is the sentence that tells a reader a red row is gone
  // for good rather than broken, and its absence had three successive review rounds recommending a "fix" for
  // gold_preopen_log, whose two missed 08:45 captures were unrecoverable by design. Append, never replace.
  if (r.note) {
    const clause = unrecoverableClause(r)
    return clause && !r.note.includes('recovered') ? `${r.note} · ${clause}` : r.note
  }
  const bits: string[] = []
  bits.push(r.as_of ? `stored ${dm(r.as_of) || r.as_of}` : 'nothing stored')
  if (r.expected_by) bits.push(`expected by ${r.expected_by}`)
  if (r.lag_sessions != null && r.lag_sessions > 0) bits.push(`${r.lag_sessions} session${r.lag_sessions === 1 ? '' : 's'} behind`)
  if (r.catchup_at) bits.push(`catch-up ${hm(r.catchup_at) || r.catchup_at}${dm(r.catchup_at) ? ` ${dm(r.catchup_at)}` : ''}`)
  { const clause = unrecoverableClause(r); if (clause) bits.push(clause) }
  return bits.join(' · ')
}
