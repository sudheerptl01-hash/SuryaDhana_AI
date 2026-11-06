/**
 * OSTR v2 + the paper F&O book (Terminal v2 PLAN 2.2, review M39 / M40 / m059–m063, W2-BOOK) — the pure part.
 *
 * No React, no '@/' imports: checked under plain node by ./__tests__/fobook.check.ts.
 *
 *  - template seeding by DELTA (review m060): strikes are picked where the Black-76 delta on each strike's own IV is
 *    closest to the target (spreads ATM / 25Δ, strangle 25Δ, condor shorts 16Δ ≈ 1σ, wings 5Δ), so a BANKNIFTY monthly
 *    condor is seeded around its expected range instead of ±2 / ±4 strikes;
 *  - net delta in lots and ₹ per 1 % move (m062); the gamma P&L of a 1 % move;
 *  - the margin block's rule (m059): the heuristic line is printed ONLY when the heuristic answered;
 *  - the heat-map colour scale (P&L is arithmetic: green / red by sign, the neutral token at zero);
 *  - the leg → book / margin / save bodies (PAPER: no order method exists anywhere in this module).
 */

export type Side = 'buy' | 'sell'
export type Kind = 'CE' | 'PE' | 'FUT' | 'EQ'

export interface ChainLike {
  symbol: string; date: string; expiry: string; expiries: string[]; days_to_expiry: number
  spot: number | null; future: number | null; forward: number | null; atm: number; lot: number | null; atm_iv: number | null
  rows: { strike: number; ce: { price: number | null; iv: number | null }; pe: { price: number | null; iv: number | null } }[]
  live?: boolean; as_of?: string | null
  /** the chain's own T in days (fo_iv.black76 'cal365-1530'): whole days at end of day, fractional in session */
  t_days?: number | null
}

/**
 * The OSTR time convention = the app's one (review M04, fo_iv.black76.TIME_CONVENTION 'cal365-1530', settled 6 Nov): the
 * chain's `t_days` — calendar days to 15:30 IST on expiry, whole at end of day, fractional in session — else its whole
 * `days_to_expiry`; never a half-day. The paper book (routers/fo_book.py t_days) and OMON use the same T, so a contract's
 * IV, Θ and ν read the same on every page.
 */
export const legDays = (chain: Pick<ChainLike, 'days_to_expiry'> & { t_days?: number | null }) =>
  Math.max(0, chain.t_days ?? chain.days_to_expiry)

// ── futures legs: one seeding rule, the same one the paper book marks with (routers/fo_book.py mark_from_chain) ──────
/** NSE's monthly contracts (the futures' expiries): the last listed expiry of each calendar month, oldest first */
export function monthlyExpiries(expiries: readonly string[]): string[] {
  const byMonth = new Map<string, string>()
  for (const e of [...expiries].sort()) byMonth.set(e.slice(0, 7), e)
  return [...byMonth.values()].sort()
}

export type FutBasis = 'future' | 'parity-forward'
/**
 * A FUT leg's price on expiry `c.expiry` (c = that expiry's chain): the traded near-month future when `c` is the near
 * monthly (the chain's `future` is NSE's nearest future), else that expiry's put-call-parity forward, labelled — the
 * book marks the same way, so a FUT leg never shows a basis P&L the moment it is booked.
 */
export function futSeed(c: Pick<ChainLike, 'expiry' | 'expiries' | 'future' | 'forward'>): { price: number | null; basis: FutBasis } {
  const near = monthlyExpiries(c.expiries)[0] ?? null
  if (c.expiry === near && c.future != null) return { price: c.future, basis: 'future' }
  if (c.forward != null) return { price: c.forward, basis: 'parity-forward' }
  return { price: c.future, basis: 'future' }
}

/** a GO hand-off's template name (`NIFTY OSTR IC` → 'Iron condor'), validated against this page's templates */
export function pickTemplate(name: string | null | undefined): Template | null {
  return (TEMPLATES as readonly string[]).includes(String(name ?? '')) ? name as Template : null
}

// ── normal CDF (erf, Abramowitz–Stegun 7.1.26) and the Black-76 delta ──────────────────────────────────────────────
export function normCdf(x: number): number {
  const t = 1 / (1 + 0.3275911 * Math.abs(x) / Math.SQRT2)
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-(x * x) / 2)
  return x >= 0 ? (1 + y) / 2 : (1 - y) / 2
}

/** undiscounted Black-76 delta (futures-equivalent N(d1)); `ivPct` in percent, `days` calendar days */
export function b76Delta(kind: 'CE' | 'PE', F: number, K: number, days: number, ivPct: number): number {
  const T = Math.max(days, 1e-6) / 365, s = Math.max(ivPct, 0.1) / 100
  const d1 = (Math.log(F / K) + s * s * T / 2) / (s * Math.sqrt(T))
  return kind === 'CE' ? normCdf(d1) : normCdf(d1) - 1
}

/** the strike whose |delta| (on that strike's IV, else the other side's, else ATM) is closest to `target` (0–1) */
export function strikeByDelta(chain: ChainLike, kind: 'CE' | 'PE', target: number): number | null {
  const F = chain.forward ?? chain.future ?? chain.spot
  if (!F || !chain.rows.length) return null
  const days = legDays(chain)
  let best: number | null = null, gap = Infinity
  for (const r of chain.rows) {
    const leg = kind === 'CE' ? r.ce : r.pe, other = kind === 'CE' ? r.pe : r.ce
    const iv = leg.iv ?? other.iv ?? chain.atm_iv
    if (!iv || leg.price == null) continue
    const d = Math.abs(b76Delta(kind, F, r.strike, days, iv))
    // OTM side only (a 25Δ call is above the forward, a 25Δ put below): never pick the ITM mirror
    if ((kind === 'CE' && r.strike < F && target < 0.5) || (kind === 'PE' && r.strike > F && target < 0.5)) continue
    if (Math.abs(d - target) < gap) { gap = Math.abs(d - target); best = r.strike }
  }
  return best
}

export const atmStrike = (chain: ChainLike) =>
  chain.rows.reduce((b, r) => Math.abs(r.strike - chain.atm) < Math.abs(b - chain.atm) ? r.strike : b, chain.rows[0]?.strike ?? chain.atm)

export const TEMPLATES = [
  'Long call', 'Long put', 'Bull call spread', 'Bear put spread',
  'Straddle', 'Strangle', 'Iron condor', 'Covered call (fut+CE)', 'Covered call (shares+CE)',
] as const
export type Template = typeof TEMPLATES[number]

export const DELTA_RULE = 'seeded by delta (Black-76 on each strike\'s IV): spreads ATM / 25Δ, strangle 25Δ, condor shorts 16Δ (≈ 1σ) and wings 5Δ — starting points, not recommendations'

export interface SeedSpec { side: Side; kind: Kind; strike: number | null }

/** the legs of a template as (side, kind, strike) picked by delta from the chain */
export function templateSpecs(t: Template, chain: ChainLike): SeedSpec[] {
  const atm = atmStrike(chain)
  const c = (d: number) => strikeByDelta(chain, 'CE', d) ?? atm, p = (d: number) => strikeByDelta(chain, 'PE', d) ?? atm
  switch (t) {
    case 'Long call': return [{ side: 'buy', kind: 'CE', strike: atm }]
    case 'Long put': return [{ side: 'buy', kind: 'PE', strike: atm }]
    case 'Bull call spread': return [{ side: 'buy', kind: 'CE', strike: atm }, { side: 'sell', kind: 'CE', strike: c(0.25) }]
    case 'Bear put spread': return [{ side: 'buy', kind: 'PE', strike: atm }, { side: 'sell', kind: 'PE', strike: p(0.25) }]
    case 'Straddle': return [{ side: 'buy', kind: 'CE', strike: atm }, { side: 'buy', kind: 'PE', strike: atm }]
    case 'Strangle': return [{ side: 'buy', kind: 'CE', strike: c(0.25) }, { side: 'buy', kind: 'PE', strike: p(0.25) }]
    case 'Iron condor': return [{ side: 'sell', kind: 'PE', strike: p(0.16) }, { side: 'buy', kind: 'PE', strike: p(0.05) },
                                { side: 'sell', kind: 'CE', strike: c(0.16) }, { side: 'buy', kind: 'CE', strike: c(0.05) }]
    case 'Covered call (fut+CE)': return [{ side: 'buy', kind: 'FUT', strike: null }, { side: 'sell', kind: 'CE', strike: c(0.25) }]
    case 'Covered call (shares+CE)': return [{ side: 'buy', kind: 'EQ', strike: null }, { side: 'sell', kind: 'CE', strike: c(0.25) }]
  }
}

// ── units (m062) ─────────────────────────────────────────────────────────────────────────────────────────────────
export function deltaUnits(delta: number, lot: number, forward: number): { lots: number; inrPer1pct: number } {
  return { lots: lot > 0 ? delta / lot : NaN, inrPer1pct: delta * forward * 0.01 }
}

// ── margin block rule (m059): one source, never the heuristic beside a real answer ───────────────────────────────
export type MarginView = 'real' | 'heuristic' | 'asking'
export function marginView(sourceChip: string | null | undefined, err: string | null | undefined): MarginView {
  const chip = String(sourceChip ?? '').toUpperCase()
  if (chip === 'BREEZE' || chip === 'NSE SPAN FILE') return 'real'
  if (chip === 'HEURISTIC' || err) return 'heuristic'
  return 'asking'
}

// ── P&L heat map colours (arithmetic: green / red by sign, intensity by |P&L| / max) ────────────────────────────
export function heatColor(v: number, maxAbs: number, pos = '#22c55e', neg = '#ef4444', zero = '#1b2230'): string {
  if (!Number.isFinite(v) || maxAbs <= 0 || Math.abs(v) < maxAbs * 0.01) return zero
  const a = Math.min(1, Math.abs(v) / maxAbs)
  const alpha = Math.round((0.18 + 0.72 * a) * 255).toString(16).padStart(2, '0')
  return `${v > 0 ? pos : neg}${alpha}`
}

export function gridMaxAbs(pnl: number[][]): number {
  let m = 0
  for (const row of pnl) for (const v of row) if (Number.isFinite(v)) m = Math.max(m, Math.abs(v))
  return m
}

// ── request bodies ───────────────────────────────────────────────────────────────────────────────────────────────
export interface LegLike {
  side: Side; kind: Kind; strike: number | null; expiry: string; premium: string; iv: string; lots: string
}
const lotsOf = (l: LegLike) => Math.max(1, Math.round(Number(l.lots) || 1))

/** the PAPER book's body: F&O legs only (shares stay in the cash book), each with its expiry, fill and its source */
export function bookLegs<L extends LegLike>(legs: L[], lotOf: (l: L) => number, forwardOf: (l: L) => number | null,
                                            sourceOf: (l: L) => string) {
  return legs.filter(l => l.kind !== 'EQ').map(l => ({
    side: l.side, kind: l.kind, strike: l.kind === 'FUT' ? null : l.strike, expiry: l.expiry,
    premium: Number(l.premium) || 0, iv: Number(l.iv) > 0 ? Number(l.iv) : null, lots: lotsOf(l), lot_size: lotOf(l),
    forward: forwardOf(l), price_source: sourceOf(l),
  }))
}

/** the margin route's legs: NFO only (shares are not margined here), each on ITS expiry (calendars margined per leg) */
export function marginLegs<L extends LegLike>(legs: L[], lotOf: (l: L) => number) {
  return legs.filter(l => l.kind !== 'EQ').map(l => ({
    side: l.side, kind: l.kind as 'CE' | 'PE' | 'FUT', strike: l.kind === 'FUT' ? null : l.strike, expiry: l.expiry,
    premium: Number(l.premium) || 0, lots: lotsOf(l), lot_size: lotOf(l),
  }))
}

/** a default structure name: "NIFTY 2-leg 09-Nov" / "NIFTY calendar 09-Nov/17-Nov" */
export function defaultName(symbol: string, legs: LegLike[], template: string | null): string {
  const exps = [...new Set(legs.filter(l => l.kind !== 'EQ').map(l => l.expiry))].sort()
  const short = (e: string) => { const d = new Date(`${e}T00:00:00Z`); return Number.isNaN(d.getTime()) ? e : `${String(d.getUTCDate()).padStart(2, '0')}-${d.toLocaleString('en-GB', { month: 'short', timeZone: 'UTC' })}` }
  const what = template ?? (exps.length > 1 ? 'calendar' : `${legs.length}-leg`)
  return `${symbol} ${what} ${exps.map(short).join('/')}`.trim()
}

/** the days to the nearest option expiry of a book (the T+n slider's range) */
export function nearestDays(legs: { kind: Kind; days: number }[]): number {
  const ds = legs.filter(l => l.kind === 'CE' || l.kind === 'PE').map(l => l.days)
  return ds.length ? Math.min(...ds) : 0
}
