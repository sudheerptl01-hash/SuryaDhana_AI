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

