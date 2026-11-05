/**
 * Pure arithmetic behind the IV panels (reports/terminal_v2/PLAN.md 1.1; R-IV §4 math reused): no DOM, no React,
 * unit-tested under plain node by ui/components/vol/__tests__/terminal_v2.check.ts. Every number here is `arithmetic`
 * (an identity on stored rows) or `context` (a description); nothing forecasts, nothing feeds a trade.
 */

export interface SummaryLike {
  date: string; spot?: number | null; iv30_cm?: number | null; monthly_atm_iv?: number | null; monthly_expiry?: string | null
  near_atm_iv?: number | null; near_dte?: number | null; skew_25d_30?: number | null; term_slope_30_90?: number | null
  rv20_cc?: number | null; rv20_parkinson?: number | null; rv20_yz?: number | null; fovolt_ann?: number | null
  iv_minus_rv20?: number | null; expected_move_1d_pct?: number | null
}

const fin = (v: number | null | undefined): v is number => v != null && Number.isFinite(v)

/** The last row with a finite `key`, or null. */
export function lastWith<K extends keyof SummaryLike>(rows: readonly SummaryLike[], key: K): SummaryLike | null {
  for (let i = rows.length - 1; i >= 0; i--) if (fin(rows[i][key] as number | null | undefined)) return rows[i]
  return null
}

/**
 * "IV paid vs vol delivered" over the last `n` monthly expiries: for each monthly expiry in the stored rows, the
 * monthly ATM IV on the FIRST session that expiry was the monthly series (what a seller was paid) against the 20-day
 * realised vol (Yang-Zhang) on the LAST session before it rolled (what the month delivered). `paid_minus_delivered`
 * in vol points; positive = IV ran above the vol that followed. A description of the past (`context`).
 */
export interface PaidRow { expiry: string; from: string; to: string; iv_paid: number; rv_delivered: number | null; paid_minus_delivered: number | null; sessions: number }
export function ivPaidLedger(rows: readonly SummaryLike[], n = 12): PaidRow[] {
  const groups = new Map<string, SummaryLike[]>()
  for (const r of rows) {
    if (!r.monthly_expiry || !fin(r.monthly_atm_iv)) continue
    const g = groups.get(r.monthly_expiry) ?? []
    g.push(r); groups.set(r.monthly_expiry, g)
  }
  const out: PaidRow[] = []
  for (const [expiry, g] of groups) {
    const first = g[0], last = g[g.length - 1]
    const rv = fin(last.rv20_yz) ? last.rv20_yz : fin(last.rv20_cc) ? last.rv20_cc : null
    out.push({ expiry, from: first.date, to: last.date, iv_paid: first.monthly_atm_iv as number, rv_delivered: rv,
               paid_minus_delivered: rv == null ? null : +(first.monthly_atm_iv! - rv).toFixed(2), sessions: g.length })
  }
  out.sort((a, b) => a.expiry.localeCompare(b.expiry))
  // the open month (its expiry after the last stored session) has not delivered yet: keep it last, flagged by rv null
  return out.slice(-n)
}

/**
 * Expected-move hit-rate over the last `window` sessions: the share of sessions whose next-session spot move stayed
 * inside ±expected_move_1d_pct (≈ iv30_cm / √252). A lognormal 1σ band should hold about 68 % of the time; the
 * measured share is printed beside that reference, never judged ("describes, does not predict").
 */
export interface HitRate { sessions: number; inside: number; share: number | null; reference: number }
export function expectedMoveHitRate(rows: readonly SummaryLike[], window = 60): HitRate {
  let sessions = 0, inside = 0
  for (let i = Math.max(1, rows.length - window); i < rows.length; i++) {
    const prev = rows[i - 1], cur = rows[i]
    if (!fin(prev.spot) || !fin(cur.spot) || !fin(prev.expected_move_1d_pct) || prev.spot === 0) continue
    const move = Math.abs(cur.spot / prev.spot - 1) * 100
    sessions++
    if (move <= prev.expected_move_1d_pct) inside++
  }
  return { sessions, inside, share: sessions ? (inside / sessions) * 100 : null, reference: 68.27 }
}

/** The three realised-vol estimators + FOVOLT beside IV30 on the last row, in vol points. */
export interface IvVsRv { date: string; iv30: number | null; cc: number | null; parkinson: number | null; yz: number | null; fovolt: number | null; spread: number | null }
export function ivVsRv(rows: readonly SummaryLike[]): IvVsRv | null {
  const r = lastWith(rows, 'iv30_cm')
  if (!r) return null
  return { date: r.date, iv30: r.iv30_cm ?? null, cc: r.rv20_cc ?? null, parkinson: r.rv20_parkinson ?? null, yz: r.rv20_yz ?? null,
           fovolt: r.fovolt_ann ?? null, spread: fin(r.iv_minus_rv20) ? r.iv_minus_rv20 : (fin(r.iv30_cm) && fin(r.rv20_yz) ? +(r.iv30_cm - r.rv20_yz).toFixed(2) : null) }
}

/** Straddle as a % of the forward, and what a lognormal 1σ to expiry implies: an arithmetic comparison, not a view. */
export interface StraddleView { price: number | null; pct_of_forward: number | null; sigma_to_expiry_pct: number | null; straddle_over_sigma: number | null }
export function straddleView(cePrice: number | null | undefined, pePrice: number | null | undefined, forward: number | null | undefined,
                             atmIvPct: number | null | undefined, dte: number | null | undefined): StraddleView {
  const price = fin(cePrice) && fin(pePrice) ? cePrice + pePrice : null
  const pct = price != null && fin(forward) && forward > 0 ? (price / forward) * 100 : null
  const sigma = fin(atmIvPct) && fin(dte) && dte > 0 ? atmIvPct * Math.sqrt(dte / 365) : null
  return { price, pct_of_forward: pct, sigma_to_expiry_pct: sigma, straddle_over_sigma: pct != null && sigma ? pct / sigma : null }
}

/** Keep a series of (date, value) points for a chart: drops nulls, keeps order. */
export function seriesOf<R extends { date: string }>(rows: readonly R[], pick: (r: R) => number | null | undefined): { date: string; v: number }[] {
  const out: { date: string; v: number }[] = []
  for (const r of rows) { const v = pick(r); if (fin(v)) out.push({ date: r.date, v }) }
  return out
}

/** Term-structure shape words for a slope in vol points (a description; never bullish / bearish). */
export function termWord(slope: number | null | undefined): string {
  if (!fin(slope)) return '—'
  if (slope > 0.5) return 'upward (longer-dated IV higher)'
  if (slope < -0.5) return 'inverted (near IV higher)'
  return 'flat'
}

/** Seed legs for OSTR from the strikes picked on OMON (1 → straddle at the strike; 2 → strangle; 4 → iron condor). */
export type SeedLeg = { side: 'buy' | 'sell'; kind: 'CE' | 'PE'; strike: number }
export function legsFromStrikes(strikes: readonly number[]): SeedLeg[] {
  const ks = [...new Set(strikes.filter(k => Number.isFinite(k) && k > 0))].sort((a, b) => a - b)
  if (ks.length === 1) return [{ side: 'buy', kind: 'CE', strike: ks[0] }, { side: 'buy', kind: 'PE', strike: ks[0] }]
  if (ks.length === 2) return [{ side: 'buy', kind: 'PE', strike: ks[0] }, { side: 'buy', kind: 'CE', strike: ks[1] }]
  if (ks.length === 3) return [{ side: 'buy', kind: 'PE', strike: ks[0] }, { side: 'sell', kind: 'PE', strike: ks[1] }, { side: 'sell', kind: 'CE', strike: ks[1] }].concat([{ side: 'buy', kind: 'CE', strike: ks[2] }])
  if (ks.length >= 4) return [{ side: 'buy', kind: 'PE', strike: ks[0] }, { side: 'sell', kind: 'PE', strike: ks[1] }, { side: 'sell', kind: 'CE', strike: ks[2] }, { side: 'buy', kind: 'CE', strike: ks[3] }]
  return []
}
