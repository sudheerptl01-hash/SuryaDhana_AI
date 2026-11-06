/**
 * Pure wording for the "Index members & drivers" panels (reports/terminal_v2/PLAN.md 1.2): no DOM, no React,
 * unit-tested under plain node by ui/components/vol/__tests__/terminal_v2.check.ts.
 *
 *  - `regimeLine`: the DRIVER REGIME strip — the 20-session leader and its tenure / share (the route's sentence), the
 *    60-session leader and since when, the top-5 share of the move and EW − CW breadth — always ending
 *    "describes, does not predict". A leader is a name, never a colour or a direction word.
 *  - `fitChip`: "explains −2,132 of −2,169 YTD points · MAE 9 pts/day · weights rebuilt, calibrated to NSE's top-10 on 04 Nov".
 */
/** The sentence every verdict ends with (PLAN §0.1); equal to terminal/source.ts DESCRIBES (checked by the node check). */
export const DESCRIBES = 'describes, does not predict'

/** `s` with the mandatory ending (idempotent); the same rule as terminal/source.ts `describes`. */
export function describes(s: string): string {
  const t = s.trim().replace(/[.\s]+$/, '')
  return t.toLowerCase().endsWith(DESCRIBES) ? t : `${t} — ${DESCRIBES}`
}

export interface StateLike {
  leader?: string | null; tenure?: number | null; leader_share?: number | null; change_date?: string | null; changed_from?: string | null
  sentence?: string | null
}
export interface TimelineLike { points: { date: string; leader: string | null; changed: boolean }[]; changes?: { date: string; to: string | null }[] }

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
/** '2026-09-11' → '11 Sep' ('' when unparsable). */
export function dayMon(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '')
  return m && +m[2] >= 1 && +m[2] <= 12 ? `${m[3]} ${MONTHS[+m[2] - 1]}` : ''
}

const pts = (v: number, d = 0) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d })}`

/** The 60-session leader and the date it took over, from the 60-session timeline (latest point; last change). */
export function leader60(tl: TimelineLike | null | undefined): { leader: string; since: string | null } | null {
  const p = tl?.points ?? []
  if (!p.length) return null
  const last = p[p.length - 1]
  if (!last.leader) return null
  let since: string | null = null
  for (let i = p.length - 1; i >= 0; i--) {
    if (p[i].leader !== last.leader) break
    since = p[i].date
    if (p[i].changed) break
  }
  return { leader: last.leader, since }
}

export function regimeLine(d20: StateLike | null | undefined, tl60: TimelineLike | null | undefined,
                           top5Share: number | null | undefined, ewMinusCwPp: number | null | undefined, breadthWord?: string | null): string | null {
  const bits: string[] = []
  if (d20?.leader) {
    const base = (d20.sentence ?? '').trim().replace(/[\s.—-]*describes, does not predict[.\s]*$/i, '').trim()
    bits.push(base || `20-session leader ${d20.leader}${d20.tenure != null ? ` for ${d20.tenure} sessions` : ''}${d20.leader_share != null ? `, ${(d20.leader_share * 100).toFixed(1)} % of member points` : ''}`)
  }
  const l60 = leader60(tl60)
  if (l60) bits.push(`60-session leader ${l60.leader}${l60.since ? ` since ${dayMon(l60.since)}` : ''}`)
  if (top5Share != null && Number.isFinite(top5Share)) bits.push(`top-5 of the move ${(top5Share * 100).toFixed(0)} %`)
  // the route's 20-session sentence may already carry its own EW − CW: never print two breadth numbers in one line
  if (ewMinusCwPp != null && Number.isFinite(ewMinusCwPp) && !bits.some(x => x.includes('EW − CW'))) bits.push(`EW − CW ${pts(ewMinusCwPp, 2)} pp${breadthWord ? `: ${breadthWord}` : ''}`)
  if (!bits.length) return null
  return describes(bits.join('; '))
}

export interface FitLike {
  index_move_pts?: number | null; explained_pts?: number | null; as_of?: string | null
  horizon?: { name?: string | null; sessions?: number | null } | null
  fit?: { mae_60s?: number | null; degraded?: boolean | null } | null
  weight_method?: { label?: string | null } | null
}
const H_WORD: Record<string, string> = { '1d': 'session', '5d': '5-session', '1m': '1-month', '3m': '3-month', ytd: 'YTD', since_change: 'since-change' }

export function fitChip(d: FitLike | null | undefined): string | null {
  if (!d || d.explained_pts == null || d.index_move_pts == null) return null
  const h = H_WORD[d.horizon?.name ?? ''] ?? ''
  const parts = [`explains ${pts(d.explained_pts)} of ${pts(d.index_move_pts)}${h ? ` ${h}` : ''} points`]
  if (d.fit?.mae_60s != null) parts.push(`MAE ${d.fit.mae_60s.toFixed(d.fit.mae_60s < 10 ? 1 : 0)} pts/day`)
  // the label may already name its calibration date ("… top-10 on 2026-11-02"): add the as-of only when it does not
  if (d.weight_method?.label) parts.push(/\d{4}-\d{2}-\d{2}/.test(d.weight_method.label) ? d.weight_method.label : `${d.weight_method.label}${d.as_of ? ` on ${dayMon(d.as_of)}` : ''}`)
  if (d.fit?.degraded) parts.push('FIT DEGRADED (60-session MAE > 25 pts)')
  return parts.join(' · ')
}


// ── review M46 / m025 / m027 / m028 (D-DATA, 6 Nov): how far the drivers tab can be read ───────────────────────────
export type TabState = 'ok' | 'degraded' | 'insufficient'
export interface TabLike { state?: string | null; sessions?: number | null; sentence?: string | null }
export interface TabView { grey: boolean; state: TabState | null; label: string | null; caption: string | null }

const TAB_LABEL: Record<TabState, string> = { ok: 'FIT OK', degraded: 'FIT DEGRADED', insufficient: 'HISTORY INSUFFICIENT' }

/**
 * The route's `tab` → what the page does with it. `ok` (or no tab: an older ui-api) shows everything as before;
 * `degraded` and `insufficient` grey the horizon points, sectors, concentration and the monthly board and caption them.
 * The degraded caption carries no MAE (the fit chip prints it: the same number once per page); the insufficient one is
 * the route's sentence (sessions stored and since when, which nothing else on the page prints).
 */
export function tabView(tab: TabLike | null | undefined): TabView {
  const s = tab?.state
  if (s !== 'degraded' && s !== 'insufficient') return { grey: false, state: s === 'ok' ? 'ok' : null, label: s === 'ok' ? TAB_LABEL.ok : null, caption: null }
  const caption = s === 'degraded'
    ? "the rebuilt weights miss the index by more than the 25-pt bar (error on the fit chip): members' points, sectors and the monthly board are approximate; the residual is shown"
    : (tab?.sentence ?? '').trim().replace(/[.\s]+$/, '') || 'too few sessions of attribution stored: the backfill has not run'
  return { grey: true, state: s, label: TAB_LABEL[s], caption }
}

/** Short per-panel caption on a greyed panel (the full sentence is printed once, above the table). */
export function tabPanelCaption(v: TabView): string | null {
  return v.grey && v.label ? `${v.label} · read with the note above the table` : null
}

export interface ChallengerLike { symbol?: string | null; sessions_leading?: number | null; sessions_needed?: number | null; sentence?: string | null }

/** m028: "X leads the raw points; the label changes after N sessions (k so far)" — always ending the describes clause. */
export function challengerLine(ch: ChallengerLike | null | undefined): string | null {
  if (!ch?.symbol) return null
  const base = (ch.sentence ?? '').trim()
  return describes(base || `${ch.symbol} leads the raw points (${ch.sessions_leading ?? 0} of ${(ch.sessions_leading ?? 0) + (ch.sessions_needed ?? 0)} sessions the label needs)`)
}

const FLAG_LABEL: Record<string, string> = { pat_yoy_outlier: 'profit y/y beyond ±200 %', revenue_yoy_outlier: 'revenue y/y beyond ±200 %', pe_distorted: 'P/E outside 3–150×' }
/** m027: the member's heuristic flags in words (unknown codes pass through), [] when none. */
export function flagWords(flags: readonly string[] | null | undefined): string[] {
  return (flags ?? []).map(f => FLAG_LABEL[f] ?? f.replace(/_/g, ' '))
}
/** Which MEMB cell a flag marks: P/E, profit y/y or revenue y/y. */
export function flagCell(flags: readonly string[] | null | undefined, cell: 'pe' | 'pat' | 'rev'): boolean {
  const code = cell === 'pe' ? 'pe_distorted' : cell === 'pat' ? 'pat_yoy_outlier' : 'revenue_yoy_outlier'
  return (flags ?? []).includes(code)
}

/** m025: the monthly board's data date — the route's `as_of` (the last stored session, '2026-11-05'); an older ui-api
 *  sent the month there ('2026-11'), so fall back to the last month's first day only then. */
export function monthlyAsOf(m: { as_of?: string | null; months?: { month: string }[] } | null | undefined): string | null {
  if (!m) return null
  if (m.as_of && /^\d{4}-\d{2}-\d{2}$/.test(m.as_of)) return m.as_of
  const last = m.months?.length ? m.months[m.months.length - 1].month : null
  return last ? `${last}-01`.slice(0, 10) : null
}
