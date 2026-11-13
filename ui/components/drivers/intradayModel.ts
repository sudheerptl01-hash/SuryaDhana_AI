/**
 * Pure model for the MEMB within-day contribution timeline (FINAL round R2-DRIV; RATING R9-I3): no DOM, no React,
 * unit-tested under plain node by ui/components/drivers/__tests__/intraday.check.ts.
 *
 * The route (`/api/market/index-drivers/intraday`) sends per-minute member points (prev index close × weight ×
 * intraday return from the live tick store's minute closes; 2-min tape fallback; honest gaps as nulls — never
 * interpolated), the index's own move, the explained sum and the residual. This module turns that into stackable
 * segments and honest wording. Badges: timeline `context`, members/fit `arithmetic`; every verdict line ends
 * "describes, does not predict". No direction words; nothing here feeds a desk, an alert or a ticket.
 */

export interface IntradayMember {
  symbol: string; industry: string | null; weight_pct: number | null
  points: number | null; ret_pct: number | null; source: string
  series: (number | null)[] | null
}
export interface IntradayGap { symbol: string; weight_pct: number | null; reason: string }
export interface IntradayDriversPayload {
  ok?: boolean; store_errors?: Record<string, string>
  index: string; date: string | null; interval: string; live?: boolean
  minutes: string[]
  prev_index_level: number | null
  actual_pts: (number | null)[]; explained_pts: (number | null)[]; residual_pts: (number | null)[]
  priced: number[]; others_pts: (number | null)[]
  residual_now: number | null; index_source: string | null
  members: { add: IntradayMember[]; drag: IntradayMember[]; rest?: IntradayMember[] }
  coverage: { members_total: number; members_priced: number; gaps: IntradayGap[] }
  weight_method: string | null; weights_as_of: string | null
  first_minute: string | null; last_minute: string | null
  as_of?: string | null; badges?: Record<string, string>; note?: string
}

/** Categorical hues for member segments (identification only — never a bullish/bearish meaning; drags are simply
 *  stacked below zero). 14 slots: top-7 adds then top-7 drags, cycled if ever longer. */
export const PALETTE = ['#56b4e9', '#e6a640', '#7bc8a4', '#b89ae0', '#e88a8a', '#6fd3d3', '#d3b36f',
                       '#8fa8e0', '#c99ac2', '#9fcf6f', '#e0a88f', '#79b8d6', '#cbb3e6', '#a8c4a0'] as const

export interface ShownSeries { symbol: string; color: string; series: (number | null)[] }

/** The series the chart stacks: top adds, top drags, then OTHERS (explained − shown; grey by convention). */
export function shownSeries(p: IntradayDriversPayload, othersColor = '#5a5f6a'): ShownSeries[] {
  const named: ShownSeries[] = [...(p.members?.add ?? []), ...(p.members?.drag ?? [])]
    .filter(m => Array.isArray(m.series))
    .map((m, i) => ({ symbol: m.symbol, color: PALETTE[i % PALETTE.length], series: m.series as (number | null)[] }))
  if ((p.others_pts ?? []).some(v => v != null && v !== 0)) named.push({ symbol: 'OTHERS', color: othersColor, series: p.others_pts })
  return named
}

export interface StackSegment { symbol: string; color: string; y0: number; y1: number }

/** One minute's stack: positives up from 0 in list order, negatives down — a null contributes nothing (the gap stays
 *  a gap). `y0`/`y1` are points (y1 farther from zero). */
export function stackAt(shown: ShownSeries[], i: number): StackSegment[] {
  let up = 0
  let down = 0
  const out: StackSegment[] = []
  for (const s of shown) {
    const v = s.series[i]
    if (v == null || v === 0 || !Number.isFinite(v)) continue
    if (v > 0) { out.push({ symbol: s.symbol, color: s.color, y0: up, y1: up + v }); up += v }
    else { out.push({ symbol: s.symbol, color: s.color, y0: down, y1: down + v }); down += v }
  }
  return out
}

/** Chart extent over the stack totals and both lines, zero always included; [0, 0] when nothing is priced. */
export function extentOf(p: IntradayDriversPayload, shown: ShownSeries[]): [number, number] {
  let lo = 0
  let hi = 0
  const n = p.minutes?.length ?? 0
  for (let i = 0; i < n; i++) {
    let up = 0
    let down = 0
    for (const s of shown) {
      const v = s.series[i]
      if (v == null || !Number.isFinite(v)) continue
      if (v > 0) up += v
      else down += v
    }
    for (const v of [up, down, p.actual_pts?.[i], p.explained_pts?.[i]]) {
      if (v == null || !Number.isFinite(v)) continue
      if (v < lo) lo = v
      if (v > hi) hi = v
    }
  }
  return [lo, hi]
}

/** Hour labels on the minute axis: the indices of the grid slots at :00 plus the first and last slot. */
export function axisTicks(minutes: string[]): number[] {
  const cand: number[] = []
  minutes.forEach((m, i) => { if (m.endsWith(':00') || i === 0 || i === minutes.length - 1) cand.push(i) })
  const out: number[] = []
  for (const i of cand) if (!out.length || i - out[out.length - 1] > 4) out.push(i)
  return out
}

/** Honest one-line coverage: priced of total, gaps with their weights, the index series' source. */
export function coverageLine(p: IntradayDriversPayload): string {
  const c = p.coverage ?? { members_total: 0, members_priced: 0, gaps: [] }
  const bits = [`${c.members_priced} of ${c.members_total} members priced`]
  if (c.gaps.length) {
    const named = c.gaps.slice(0, 4).map(g => `${g.symbol}${g.weight_pct != null ? ` ${g.weight_pct.toFixed(1)}%w` : ''}`)
    bits.push(`gaps (never filled): ${named.join(', ')}${c.gaps.length > 4 ? ` +${c.gaps.length - 4} more` : ''}`)
  }
  if (p.index_source) bits.push(`index series from ${p.index_source}`)
  if (p.first_minute && p.first_minute > '09:15') bits.push(`first print ${p.first_minute} — no data before it`)
  return bits.join(' · ')
}

/** The residual line, printed once on the panel (one number once per page). */
export function residualLine(p: IntradayDriversPayload): string | null {
  if (p.residual_now == null || !Number.isFinite(p.residual_now)) return null
  const at = p.last_minute ?? ''
  return `residual ${fmtPts2(p.residual_now)} pts at ${at}: the part of the index move the stored weights do not explain`
}

/** Signed, 1 dp, U+2212 (matches drivers/api.ts fmtPts conventions without importing React-adjacent code). */
export function fmtPts2(v: number | null | undefined, d = 1): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const r = Number(v.toFixed(d)) || 0
  return `${r > 0 ? '+' : r < 0 ? '−' : ''}${Math.abs(r).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d })}`
}

/** Nearest grid index for a mouse x in [0, 1] across n slots. */
export function nearestIdx(fx: number, n: number): number {
  if (n <= 0) return 0
  return Math.max(0, Math.min(n - 1, Math.round(fx * (n - 1))))
}

export interface HoverRow { symbol: string; points: number; color: string }

/** The hover card's member rows at minute i: the shown series, |points| descending, top `k`. */
export function hoverRows(shown: ShownSeries[], i: number, k = 4): HoverRow[] {
  return shown
    .map(s => ({ symbol: s.symbol, points: s.series[i], color: s.color }))
    .filter((r): r is HoverRow => r.points != null && Number.isFinite(r.points) && r.points !== 0)
    .sort((a, b) => Math.abs(b.points) - Math.abs(a.points))
    .slice(0, k)
}
