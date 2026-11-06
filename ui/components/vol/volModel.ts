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

/** The 252-session window behind every "percentile of the past year" label (the IV history fetch is ≈ 3 years). */
export const ONE_YEAR_SESSIONS = 252
export function lastYear<T>(rows: readonly T[]): T[] { return rows.slice(-ONE_YEAR_SESSIONS) }

/**
 * "IV paid vs vol delivered" (M02, review 5 Nov 2026): the rows come from the server (`/iv/{symbol}/paid-delivered`: NSE
 * monthly expiries, the ATM IV at ≈ 30 DTE, the close-to-close zero-mean vol over the option's own life). The old client
 * ledger here took the first expiry 20–60 days out (a weekly), the trailing RV20 ≈ 20 sessions BEFORE expiry, and
 * close-to-close under a Yang-Zhang header; it is gone. (The review's −1.76 was its own re-computation over that ledger's
 * weekly rows, not the own-life result: over NSE's 11 closed monthlies to 27 Oct 2026 the server ledger gives NIFTY +0.63 pts,
 * 6 of 11 paid above, with the re-dated March 2026 monthly at −14.90 — +2.35 before round 2 put March back.) This summary only counts what the server delivered: closed months, their mean, how many paid above.
 */
export interface PaidRowLike { expiry: string; open?: boolean; paid_minus_delivered: number | null }
export interface PaidSummary { closed: number; open: number; mean: number | null; paid_above: number }
export function paidSummary(rows: readonly PaidRowLike[]): PaidSummary {
  const closed = rows.filter(r => !r.open && fin(r.paid_minus_delivered))
  const mean = closed.length ? closed.reduce((s, r) => s + (r.paid_minus_delivered as number), 0) / closed.length : null
  return { closed: closed.length, open: rows.filter(r => r.open).length, mean, paid_above: closed.filter(r => (r.paid_minus_delivered as number) > 0).length }
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

/**
 * The three realised-vol estimators + FOVOLT beside IV30 on the last row, in vol points (M01, review 5 Nov 2026): the spread
 * of record is against CLOSE-TO-CLOSE (the stored `iv_minus_rv20`, the catalog's IV30_CM − RV20_CC) — the tile used to say
 * "(YZ)" and, without a stored spread, silently fell back to Yang-Zhang. The Parkinson and Yang-Zhang spreads are computed
 * here and always named. FOVOLT is NSE's √365 number; `fovolt252` is it on the √252 basis of the three RVs (m054).
 */
export interface IvVsRv {
  date: string; iv30: number | null; cc: number | null; parkinson: number | null; yz: number | null; fovolt: number | null; fovolt252: number | null
  spread: number | null; spreadParkinson: number | null; spreadYz: number | null
}
export const FOVOLT_TO_252 = Math.sqrt(252 / 365)
export function ivVsRv(rows: readonly SummaryLike[]): IvVsRv | null {
  const r = lastWith(rows, 'iv30_cm')
  if (!r) return null
  const iv = r.iv30_cm ?? null
  const minus = (a: number | null, b: number | null | undefined) => (fin(a) && fin(b) ? +(a - b).toFixed(2) : null)
  return { date: r.date, iv30: iv, cc: r.rv20_cc ?? null, parkinson: r.rv20_parkinson ?? null, yz: r.rv20_yz ?? null,
           fovolt: r.fovolt_ann ?? null, fovolt252: fin(r.fovolt_ann) ? r.fovolt_ann * FOVOLT_TO_252 : null,
           spread: fin(r.iv_minus_rv20) ? r.iv_minus_rv20 : minus(iv, r.rv20_cc), spreadParkinson: minus(iv, r.rv20_parkinson), spreadYz: minus(iv, r.rv20_yz) }
}

/**
 * m053: the straddle against what the index actually did. "0.80× the priced move" was the √(2/π) identity (it printed 0.80
 * on every underlying). Instead: the straddle's breakeven (call + put ÷ forward) against the stored spot history — the share
 * of past windows of the SAME length (sessions to expiry) whose |move| went beyond it. Arithmetic on stored rows; a
 * description of the past, never a forecast.
 */
export interface StraddleHit { windows: number; beyond: number; share: number | null; sessions: number }
export function straddleHitRate(rows: readonly SummaryLike[], breakevenPct: number | null | undefined, sessions: number | null | undefined, lookback = 250): StraddleHit {
  const h = fin(sessions) && sessions > 0 ? Math.max(1, Math.round(sessions)) : 0
  const spots = rows.map(r => r.spot).filter(fin)
  if (!fin(breakevenPct) || breakevenPct <= 0 || !h || spots.length <= h) return { windows: 0, beyond: 0, share: null, sessions: h }
  let windows = 0, beyond = 0
  for (let i = Math.max(0, spots.length - h - lookback); i + h < spots.length; i++) {
    const move = Math.abs(spots[i + h] / spots[i] - 1) * 100
    windows++
    if (move > breakevenPct) beyond++
  }
  return { windows, beyond, share: windows ? (beyond / windows) * 100 : null, sessions: h }
}

/** Weekdays strictly after `from` up to and including `to` (ISO dates): sessions to expiry, NSE holidays not removed. */
export function weekdaysBetween(from: string, to: string): number {
  const a = new Date(`${from}T00:00:00Z`), b = new Date(`${to}T00:00:00Z`)
  if (!(a < b)) return 0
  let n = 0
  for (let d = new Date(a.getTime() + 86_400_000); d <= b; d = new Date(d.getTime() + 86_400_000)) { const w = d.getUTCDay(); if (w !== 0 && w !== 6) n++ }
  return n
}

/**
 * m047: one IV per strike for the Greeks, from the OUT-OF-THE-MONEY side (puts below the forward, calls at / above it) —
 * the chain took the in-the-money call's IV first (`ce.iv ?? pe.iv`), so Θ / Γ jumped where the ITM call and the OTM put
 * disagreed (23,850: 15.0 % vs 17.4 %).
 */
export function otmIv(strike: number, forward: number | null | undefined, ceIv: number | null | undefined, peIv: number | null | undefined): number | null {
  const put = fin(peIv) ? peIv : null, call = fin(ceIv) ? ceIv : null
  if (!fin(forward)) return call ?? put
  return strike < forward ? (put ?? call) : (call ?? put)
}

/** m071: the expiry nearest a target tenor (calendar days) among those carrying a smile — today's and the ghost's alike. */
export function nearestTenor<E extends { dte: number | null | undefined; smile?: readonly unknown[] }>(expiries: readonly E[], targetDte = 30): E | null {
  const ok = expiries.filter(e => fin(e.dte) && (e.dte as number) > 2 && (e.smile?.length ?? 0) >= 3)
  if (!ok.length) return null
  return ok.reduce((b, e) => (Math.abs((e.dte as number) - targetDte) < Math.abs((b.dte as number) - targetDte) ? e : b))
}

/** m067: annualised basis only from DTE ≥ `minDte` (expiry-week annualisation divides by ~1 day and sets the axis). */
export function basisForChart<R extends { dte: number; basis_ann_pct: number | null }>(rows: readonly R[], minDte = 3): (number | null)[] {
  return rows.map(r => (r.dte >= minDte && fin(r.basis_ann_pct) ? r.basis_ann_pct : null))
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
  // 3 strikes → iron fly: long wings at the outer strikes, short straddle at the middle one
  if (ks.length === 3) return [{ side: 'buy', kind: 'PE', strike: ks[0] }, { side: 'sell', kind: 'PE', strike: ks[1] }, { side: 'sell', kind: 'CE', strike: ks[1] }, { side: 'buy', kind: 'CE', strike: ks[2] }]
  if (ks.length >= 4) return [{ side: 'buy', kind: 'PE', strike: ks[0] }, { side: 'sell', kind: 'PE', strike: ks[1] }, { side: 'sell', kind: 'CE', strike: ks[2] }, { side: 'buy', kind: 'CE', strike: ks[3] }]
  return []
}

// ── the shared active-symbol convention on F&O pages (V-VOL fix wave 2, round 2) ──────────────────────────────────

/** NSE's index underlyings with options: always F&O, so a page adopts them before its stock list has loaded. */
export const FNO_INDEX_UNDERLYINGS: readonly string[] = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50']

/**
 * May a page that shows only F&O underlyings (DERV, OMON) adopt `candidate` from the active-symbol store? Another page
 * (DEAL, a stock window) writes any cash symbol there, and DERV used to open on it and show an error instead of NIFTY.
 *  - 'adopt'  an index underlying, or a name on the F&O list; also when the list is unavailable (`fno` null): no guard is
 *             better than a page that never follows;
 *  - 'reject' the list is known and the name is not on it (keep the current underlying);
 *  - 'wait'   a stock while the list is still loading (`fno` undefined): decide when it arrives.
 */
export type FnoVerdict = 'adopt' | 'reject' | 'wait'
export function fnoVerdict(candidate: string | null | undefined, fno: readonly string[] | null | undefined): FnoVerdict {
  const s = typeof candidate === 'string' ? candidate.trim().toUpperCase() : ''
  if (!s) return 'reject'
  if (FNO_INDEX_UNDERLYINGS.includes(s)) return 'adopt'
  if (fno === undefined) return 'wait'
  if (fno === null || fno.length === 0) return 'adopt'
  return fno.includes(s) ? 'adopt' : 'reject'
}

/**
 * The expiry GO hands to OMON: `TCS OMON 27NOV` writes {symbol: TCS, expiry: 2026-11-27} to the active-symbol store and
 * TCS to OMON's hand-off key. OMON opens on that expiry when the store's symbol is the one it opens on and the expiry has
 * not passed (IST calendar day); otherwise null, the nearest series. Whether the exchange lists it is the chain's answer
 * (`expiries`); see `expiryNote`.
 */
export function handoffExpiry(active: { symbol: string; expiry: string | null } | null | undefined, symbol: string, todayIso: string): string | null {
  if (!active || !active.expiry || active.symbol !== symbol.trim().toUpperCase()) return null
  if (!/^\d{4}-\d{2}-\d{2}$/.test(active.expiry)) return null
  return active.expiry >= todayIso ? active.expiry : null
}

/** A sentence when the expiry asked for is not a listed one (the chain then answers with its nearest series), else null. */
export function expiryNote(asked: string | null | undefined, chain: { symbol: string; expiry: string; expiries: readonly string[] } | null | undefined): string | null {
  if (!asked || !chain || chain.expiries.includes(asked)) return null
  const later = chain.expiries.find(e => e >= asked) ?? null
  return `${asked} is not a listed ${chain.symbol} expiry: showing ${chain.expiry}${later && later !== chain.expiry ? `; the next listed after it is ${later}` : ''}.`
}

/** IST calendar day (YYYY-MM-DD) for `now`. */
export function istDay(now: Date = new Date()): string {
  return new Date(now.getTime() + 330 * 60_000).toISOString().slice(0, 10)
}

/** M02 round 2: the ledger's skipped months, consecutive months with one reason and no expiry folded into a run
 *  ("2025-11 → 2026-10: no contract of the month in the store …"), the rest one by one, in month order. */
export interface SkippedMonth { month: string; expiry: string | null; reason: string }
export function skippedRuns(skipped: readonly SkippedMonth[]): string[] {
  const next = (m: string) => { const [y, mo] = m.split('-').map(Number); return mo === 12 ? `${y + 1}-01` : `${y}-${String(mo + 1).padStart(2, '0')}` }
  const out: string[] = []
  const xs = [...skipped].sort((a, b) => a.month.localeCompare(b.month))
  for (let i = 0; i < xs.length; i++) {
    const x = xs[i]
    if (x.expiry) { out.push(`${x.month} (${x.expiry}): ${x.reason}`); continue }
    let j = i
    while (j + 1 < xs.length && !xs[j + 1].expiry && xs[j + 1].reason === x.reason && xs[j + 1].month === next(xs[j].month)) j++
    out.push(`${j > i ? `${x.month} → ${xs[j].month}` : x.month}: ${x.reason}`)
    i = j
  }
  return out
}
