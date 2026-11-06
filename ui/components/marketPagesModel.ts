/**
 * Presentation rules for the market pages (page review 5 Nov 2026, D-UI): EQS, BRF, HDS, MRGN, MOV, ECO, EVTS, DEAL,
 * INSD, CF, WRAP, MKT, WEI, PRE, SEAG, IPO, COMP. Each rule answers one review item (IDs in the comments: M = major,
 * m = minor, synth/05_issues.md).
 *
 * Pure module (no React, no imports): unit-tested by ui/components/__tests__/market_pages.check.ts under plain node.
 */

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const MINUS = '−'

/** "+2.23" / "−0.41" with U+2212, `d` decimals. */
export function signed(v: number, d = 1): string {
  const x = Math.abs(v) < 0.5 * 10 ** -d ? 0 : v
  return `${x > 0 ? '+' : x < 0 ? MINUS : ''}${Math.abs(x).toFixed(d)}`
}

/** Indian grouping with two decimals (24,536.60). */
export function idx2(v: number): string {
  return v.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

/** '2026-11-30' → '30 Nov' (and the weekday when asked). */
export function dayMonth(iso: string | null | undefined, weekday = false): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '')
  if (!m) return '—'
  const s = `${+m[3]} ${MONTHS[+m[2] - 1]}`
  if (!weekday) return s
  const wd = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).getUTCDay()]
  return `${wd} ${s}`
}

// ── EQS (M07, m076–m079) ───────────────────────────────────────────────────────────────────────────────────────

export type ValuationBasis = 'filings' | 'snapshot_rebased' | 'withheld' | 'etf' | 'none'
export interface EqsRowLike {
  latest_price?: number | null; cmp?: number | null; cmp_basis?: string; valuation_basis?: ValuationBasis
  pe_ratio?: number | null; mktcap_cr?: number | null; div_yld_pct?: number | null; div_basis?: string
  quarter_basis?: string; instrument?: string; snapshot_cmp?: number | null; qtr_period?: string | null
}

/**
 * M07: the CMP column is the stored NSE close (`latest_price`, dated `price_date`), never the enrichment snapshot's
 * price. An older ui-api sent the snapshot as `cmp` (TCS ₹2,350 vs the ₹2,495.70 close): it is never displayed.
 */
export function eqsPrice(s: EqsRowLike): number | null {
  return s.latest_price ?? null
}

/**
 * P/E, market cap and dividend yield as the grid shows them: only a dated, comparable value. 'filings' (NSE results
 * filings at the close, FUND / COMP's source) and 'snapshot_rebased' (the snapshot scaled to the close when its price
 * is within 0.5–2× of it) show; 'withheld' (a split, bonus or stale snapshot), 'etf' and an older server's undated
 * snapshot numbers show "—".
 */
export function shownValuation(s: EqsRowLike, key: 'pe_ratio' | 'mktcap_cr' | 'div_yld_pct'): number | null {
  if (key === 'div_yld_pct') return s.div_basis === 'snapshot_rebased' ? (s.div_yld_pct ?? null) : null
  return s.valuation_basis === 'filings' || s.valuation_basis === 'snapshot_rebased' ? (s[key] ?? null) : null
}

/** The hover text that says where a valuation cell came from. */
export function valuationNote(s: EqsRowLike): string {
  switch (s.valuation_basis) {
    case 'filings': return 'P/E (trailing profit) and market cap at the stored NSE close, from the latest NSE results filing (FUND / COMP use the same)'
    case 'snapshot_rebased': return 'no NSE results filing read yet: the enrichment snapshot’s P/E and market cap rebased to the stored close (marked ˢ)'
    case 'withheld': return `the enrichment snapshot’s price (₹${s.snapshot_cmp ?? '—'}) is too far from the close to rebase (a split, a bonus or a stale snapshot): withheld`
    case 'etf': return 'an ETF: a fund, no company earnings or market cap'
    case 'none': return 'no valuation stored for this company'
    default: return 'this server sent no dated valuation (ui-api not yet restarted): hidden rather than shown stale'
  }
}

/** m079: the grid's provenance counts for the legend under the table. */
export function eqsLegend(rows: readonly EqsRowLike[]): { filings: number; rebased: number; withheld: number; etf: number; legacy: number } {
  const c = { filings: 0, rebased: 0, withheld: 0, etf: 0, legacy: 0 }
  for (const r of rows) {
    if (r.instrument === 'ETF' || r.valuation_basis === 'etf') c.etf++
    else if (r.valuation_basis === 'filings') c.filings++
    else if (r.valuation_basis === 'snapshot_rebased') c.rebased++
    else if (r.valuation_basis === 'withheld') c.withheld++
    else if (r.valuation_basis == null) c.legacy++
  }
  return c
}

// ── BRF: the crash filter's two lines (M08) ────────────────────────────────────────────────────────────────────

export interface CrashLike { nifty: number; sma200: number; risk_on: boolean; gap_pct: number; move_needed_pct: number; next_signal_date: string; date?: string }
export interface DeskNavRow { date: string; holdings?: number | null; positions?: number | null; nav?: number | null }
export interface DeskLike { positions?: unknown[] | null; latest?: DeskNavRow | null; nav?: DeskNavRow[] | null
  plans?: { signal_date?: string | null; summary?: { signal_date?: string | null; risk_on?: boolean | number | null } | null }[] | null }

/** Where the Desk's money is today: invested or in the liquid fund, and since when (from the NAV ledger). */
export function bookState(desk: DeskLike | null | undefined): { invested: boolean; positions: number; since: string | null; equityPct: number | null; lastSignal: string | null; lastSignalRiskOn: boolean | null } {
  const positions = desk?.positions?.length ?? desk?.latest?.positions ?? 0
  const latest = desk?.latest
  const invested = positions > 0 || (latest?.holdings ?? 0) > 0
  const nav = desk?.nav ?? []
  let since: string | null = null
  for (let i = nav.length - 1; i >= 0; i--) {
    const r = nav[i]
    const rowInvested = (r.positions ?? 0) > 0 || (r.holdings ?? 0) > 0
    if (rowInvested !== invested) break
    since = r.date
  }
  const plan = desk?.plans?.[0]
  const riskOn = plan?.summary?.risk_on
  return {
    invested, positions, since,
    equityPct: latest?.nav ? ((latest.holdings ?? 0) / latest.nav) * 100 : null,
    lastSignal: plan?.summary?.signal_date ?? plan?.signal_date ?? null,
    lastSignalRiskOn: riskOn == null ? null : !!riskOn,
  }
}

/**
 * M08: two labelled lines, never "INVESTED" for an all-cash book. `reading` = today's crash-filter reading (what the
 * next monthly signal would do on it); `book` = where the money is and since when. Both are context.
 */
export function crashLines(crash: CrashLike, desk: DeskLike | null | undefined): { reading: string; book: string } {
  const side = crash.risk_on ? 'above' : 'below'
  const nextDay = dayMonth(crash.next_signal_date, true)
  const reading = `Today's reading: NIFTY ${idx2(crash.nifty)} ${side} its 200-DMA ${idx2(crash.sma200)} (${signed(crash.gap_pct, 1)}%)`
    + (crash.risk_on ? ` · on this reading the ${nextDay} signal would invest` : ` · the ${nextDay} signal stays in the liquid fund unless NIFTY gains +${crash.move_needed_pct.toFixed(1)}%`)
  const b = bookState(desk)
  const since = b.since ? ` since ${dayMonth(b.since)}` : ''
  const why = b.lastSignal ? ` (the ${dayMonth(b.lastSignal)} signal${b.lastSignalRiskOn === false ? ': crash filter on' : b.lastSignalRiskOn ? ': invest' : ''})` : ''
  const book = b.invested
    ? `The book: invested${since}, ${b.positions} position${b.positions === 1 ? '' : 's'}${b.equityPct != null ? ` (${b.equityPct.toFixed(0)}% of NAV in equities)` : ''}${why} · the next signal is ${nextDay}`
    : `The book: in the liquid fund${since}${why} · the next signal is ${nextDay}`
  return { reading, book }
}

// ── MKT / BRF: FII–DII coverage (M09) ─────────────────────────────────────────────────────────────────────────

export interface CashSummaryLike { sessions_5d?: number; sessions_mtd?: number; sessions?: number
  expected_5d?: number; expected_mtd?: number; missing_5d?: string[]; missing_mtd?: string[]; label_5d?: string | null; label_mtd?: string | null }

/**
 * M09: "n of m sessions" for the 5-session and month-to-date sums (data-service fii_dii.summarize: the NSE session
 * calendar from the bhavcopy). A window with a missing session is labelled and listed, never summed silently. An
 * older server without the calendar fields says how many were collected, never that the window is complete.
 */
export function cashCoverage(s: CashSummaryLike, which: '5d' | 'mtd'): { text: string; gap: boolean; missing: string[] } {
  const n = (which === '5d' ? s.sessions_5d : s.sessions_mtd) ?? 0
  const m = which === '5d' ? s.expected_5d : s.expected_mtd
  const missing = (which === '5d' ? s.missing_5d : s.missing_mtd) ?? []
  if (m == null || m === 0) return { text: `${n} collected · session calendar unknown`, gap: true, missing }
  const miss = missing.length ? ` · missing ${missing.map(d => dayMonth(d)).join(', ')}` : ''
  return { text: `${n} of ${m} sessions${miss}`, gap: n < m, missing }
}

// ── HDS: quarter-on-quarter only (M25, m037, m038) ─────────────────────────────────────────────────────────────

const QEND = /-(03-31|06-30|09-30|12-31)$/
export const isQuarterEnd = (iso: string | null | undefined): boolean => !!iso && QEND.test(iso)

/** '2026-09-30' → the quarter end before it ('2026-06-30'); null for a date that is not a quarter end. */
export function previousQuarterEnd(iso: string): string | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  if (!m || !isQuarterEnd(iso)) return null
  const y = +m[1]
  return { '03': `${y - 1}-12-31`, '06': `${y}-03-31`, '09': `${y}-06-30`, '12': `${y}-09-30` }[m[2]] ?? null
}

/**
 * M25: a row compares two consecutive quarter-end filings. IPO and listing-time filings ("Sept 26 → Sept 26",
 * "Aug 26 → Sept 26": allotment, not buying) are not quarter-on-quarter and leave the leaderboards.
 */
export function isQoq(r: { period_end: string; prev_period: string | null }): boolean {
  return !!r.prev_period && isQuarterEnd(r.period_end) && isQuarterEnd(r.prev_period) && previousQuarterEnd(r.period_end) === r.prev_period
}

/** m037: how a quarter's coverage splits (comparable, listing-time / IPO pairs, no earlier filing). */
export function hdsCoverage(rows: readonly { period_end: string; prev_period: string | null }[], period: string | null): { filings: number; qoq: number; listing: number; first: number } {
  const q = rows.filter(r => r.period_end === period)
  const qoq = q.filter(isQoq).length
  const first = q.filter(r => !r.prev_period).length
  return { filings: q.length, qoq, listing: q.length - qoq - first, first }
}

/** m038: a percentage-point change and its level; nothing when both are missing (no "— → —%"). */
export function ppCell(change: number | null | undefined, level: number | null | undefined): { change: string; level: string } {
  const c = change == null ? '—' : `${change > 0 ? '+' : change < 0 ? MINUS : ''}${Math.abs(change).toFixed(2)} pp`
  const l = level == null ? '' : `→ ${level.toFixed(1)}%`
  return { change: c, level: l }
}

// ── MRGN: base effects out of the % leaderboard (M26) ──────────────────────────────────────────────────────────

export interface MtfLike { symbol: string; amount_cr: number | null; qty_chg_pct: number | null; amount_chg_cr?: number | null; mtf_sessions?: number | null }
export const MTF_MIN_SESSIONS = 60

/**
 * M26: names with at least 60 sessions of MTF history. data-service's `mtf_sessions` when it sends it; otherwise the
 * 60-session read's own evidence: a name that had a funded position 60 sessions ago (`qty_chg_pct` not null at
 * lookback 60). Recent listings (ESDS +19,142 % from a near-zero first day) fail both.
 */
export function mtfEligible(rows: readonly MtfLike[], rows60: readonly MtfLike[] | null): Set<string> | null {
  if (rows.some(r => r.mtf_sessions != null)) return new Set(rows.filter(r => (r.mtf_sessions ?? 0) >= MTF_MIN_SESSIONS).map(r => r.symbol))
  if (!rows60) return null
  return new Set(rows60.filter(r => r.qty_chg_pct != null).map(r => r.symbol))
}

/** The ₹ change in the funded amount: the server's `amount_chg_cr`, else the added quantity at today's funding (≈). */
export function mtfRupeeChange(r: MtfLike): { value: number | null; approx: boolean } {
  if (r.amount_chg_cr != null) return { value: r.amount_chg_cr, approx: false }
  if (r.amount_cr == null || r.qty_chg_pct == null || r.qty_chg_pct <= -100) return { value: null, approx: true }
  return { value: r.amount_cr * (r.qty_chg_pct / (100 + r.qty_chg_pct)), approx: true }
}

export function mtfBuilding(rows: readonly MtfLike[], mode: 'pct' | 'rupees', eligible: Set<string> | null, minCr = 5, n = 25): MtfLike[] {
  const base = rows.filter(r => (r.amount_cr ?? 0) >= minCr)
  if (mode === 'rupees') {
    return base.filter(r => mtfRupeeChange(r).value != null)
      .sort((a, b) => mtfRupeeChange(b).value! - mtfRupeeChange(a).value!).slice(0, n)
  }
  return base.filter(r => r.qty_chg_pct != null && (!eligible || eligible.has(r.symbol)))
    .sort((a, b) => b.qty_chg_pct! - a.qty_chg_pct!).slice(0, n)
}

// ── MOV (M27, m017–m019) ───────────────────────────────────────────────────────────────────────────────────────

/** NSE's '27-Nov-2025' → ISO, or null. */
export function nseDateIso(s: string | null | undefined): string | null {
  const m = /^(\d{1,2})-([A-Za-z]{3})-(\d{4})/.exec(s ?? '')
  if (!m) return null
  const mo = MONTHS.findIndex(x => x.toLowerCase() === m[2].toLowerCase())
  return mo < 0 ? null : `${m[3]}-${String(mo + 1).padStart(2, '0')}-${m[1].padStart(2, '0')}`
}

/** m018: an old-high date with its year ('27 Nov 25'): "27-Nov" alone read like a date to come. */
export function shortDateWithYear(s: string | null | undefined): string {
  const iso = nseDateIso(s)
  if (!iso) return ''
  return `${+iso.slice(8, 10)} ${MONTHS[+iso.slice(5, 7) - 1]} ${iso.slice(2, 4)}`
}

export interface HighLowRow { symbol: string; ltp: number | null; change_pct: number | null; new_level?: number | null; prev_level?: number | null; prev_date?: string | null; value_cr?: number | null }

/**
 * M27: the 52-week list newest first by the date on the row (NSE's prevHLDate), then by the ₹ traded (the day's most
 * important highs, ICICIBANK and KOTAKBANK, lead instead of A–G alphabetically), then by the size of the move.
 * `value` looks up the traded value when the row has none (after the close NSE drops it: MKT's EOD turnover, the
 * live-quotes map).
 */
export function sortHighLow<R extends HighLowRow>(rows: readonly R[], value: (sym: string) => number | null | undefined): R[] {
  const v = (r: R) => r.value_cr ?? value(r.symbol) ?? -1
  return [...rows].sort((a, b) => (nseDateIso(b.prev_date) ?? '').localeCompare(nseDateIso(a.prev_date) ?? '')
    || v(b) - v(a) || Math.abs(b.change_pct ?? 0) - Math.abs(a.change_pct ?? 0))
}

/**
 * m018: a row with no previous 52-week level (a new listing: BCSSL "old high 0.00" in BOTH lists) is not a new high
 * or a new low; it leaves both lists and is named once.
 */
/**
 * NSE's 52-week list can carry a symbol more than once (another series: ALIVUS at +110.24 % beside −1.40 %, FROG ×3).
 * One row per symbol: the one with the smaller move (an equity cannot move past its 20 % band in a session; the other
 * row's reference price is another series').
 */
export function onePerSymbol<R extends HighLowRow>(rows: readonly R[]): R[] {
  const by = new Map<string, R>()
  for (const r of rows) {
    const prev = by.get(r.symbol)
    if (!prev || Math.abs(r.change_pct ?? Infinity) < Math.abs(prev.change_pct ?? Infinity)) by.set(r.symbol, r)
  }
  return rows.filter(r => by.get(r.symbol) === r)
}

export function splitNoHistory<R extends HighLowRow>(highsIn: readonly R[], lowsIn: readonly R[]): { highs: R[]; lows: R[]; noHistory: string[] } {
  const highs = onePerSymbol(highsIn), lows = onePerSymbol(lowsIn)
  const bad = (r: R) => r.prev_level == null || r.prev_level <= 0
  const both = new Set(highs.map(r => r.symbol).filter(s => lows.some(l => l.symbol === s)))
  const out = (rs: readonly R[]) => rs.filter(r => !bad(r) && !both.has(r.symbol))
  const noHistory = [...new Set([...highs, ...lows].filter(r => bad(r) || both.has(r.symbol)).map(r => r.symbol))]
  return { highs: out(highs), lows: out(lows), noHistory }
}

/** m017: fill a missing traded value from EOD lookups (first hit wins); says where it came from. */
export function fillValue<R extends { symbol: string; value_cr?: number | null }>(rows: readonly R[], lookups: readonly ((s: string) => number | null | undefined)[]): (R & { value_from?: 'eod' })[] {
  return rows.map(r => {
    if (r.value_cr != null) return r
    for (const f of lookups) {
      const v = f(r.symbol)
      if (v != null) return { ...r, value_cr: v, value_from: 'eod' as const }
    }
    return r
  })
}

export interface SurgeRow { symbol: string; ltp: number | null; change_pct: number | null; value_cr?: number | null; vs_week?: number | null }
export interface EodMover { symbol: string; close: number | null; chg_pct: number | null; turnover_cr: number | null; vol_x: number | null }

/**
 * M27: the volume-surge panel after the close. NSE's live list loses the traded value after 15:30, and the ≥ ₹1 cr
 * filter then emptied the panel ("—" while MKT listed PIIND 34.6×). After the close it reads MKT's end-of-day
 * volume shockers (volume ÷ the 50-session average, ≥ 3×) when MKT is on the same session; in session it stays NSE's.
 */
export function volumeSurge(live: readonly SurgeRow[], marketOpen: boolean, eod: readonly EodMover[] | null, eodDate: string | null, sessionDate: string | null):
  { rows: SurgeRow[]; basis: 'nse_live' | 'eod' | 'nse_live_no_value'; note: string } {
  const liveRows = live.filter(r => (r.value_cr ?? 0) >= 1).slice(0, 20)
  if (marketOpen || liveRows.length) return { rows: liveRows, basis: 'nse_live', note: "volume ÷ NSE's 1-week average · ≥ ₹1 cr traded" }
  if (eod && eod.length && eodDate && (!sessionDate || eodDate === sessionDate)) {
    return { rows: eod.map(r => ({ symbol: r.symbol, ltp: r.close, change_pct: r.chg_pct, value_cr: r.turnover_cr, vs_week: r.vol_x })), basis: 'eod',
             note: `end of day ${dayMonth(eodDate)} (MKT): volume ÷ the 50-session average, ≥ 3×, liquid names` }
  }
  return { rows: live.slice(0, 20) as SurgeRow[], basis: 'nse_live_no_value', note: "volume ÷ NSE's 1-week average · NSE drops the traded value after the close" }
}

// ── ECO (M28, m012) ────────────────────────────────────────────────────────────────────────────────────────────

export interface EcoLike { date: string; time: string | null; kind: string; what: string; country: string; source?: string | null
  impact?: string | null; forecast?: string | null; previous?: string | null; actual?: string | null }
export type EcoFamily = 'IN_DATA' | 'RBI' | 'US_DATA' | 'FED' | 'EXPIRY' | 'SESSION' | 'HOLIDAY' | 'OTHER'

const IN_KINDS = new Set(['CPI', 'WPI', 'IIP', 'CORE', 'GDP'])
/** The filter family of a calendar row (India data, RBI, US data, Fed, F&O expiries, special sessions, holidays). */
export function ecoFamily(e: EcoLike): EcoFamily {
  const k = e.kind.toUpperCase()
  if (k === 'HOLIDAY') return 'HOLIDAY'
  if (k === 'RBI') return 'RBI'
  if (k === 'FED' || k === 'FOMC' || k.startsWith('FOMC')) return 'FED'
  if (k.includes('EXPIRY')) return 'EXPIRY'
  if (k === 'MUHURAT' || k.includes('SESSION') || k === 'SPECIAL') return 'SESSION'
  if (e.country !== 'IN' || k.startsWith('US')) return 'US_DATA'
  return IN_KINDS.has(k) ? 'IN_DATA' : 'OTHER'
}

/** A unique row key: several US releases share a date and a kind (US_DATA 19:00 ×3 on 6 Nov). */
export const ecoKey = (e: EcoLike): string => `${e.kind}|${e.date}|${e.time ?? ''}|${e.what}`

/** The cards across the top: the next releases that matter (no low-impact Fed speeches, holidays last). */
export function ecoNext(events: readonly EcoLike[], today: string, n = 4): EcoLike[] {
  const lowImpact = (e: EcoLike) => (e.impact ?? '').toLowerCase() === 'low' || /SPEECH|SPEAKS/i.test(`${e.kind} ${e.what}`)
  return events.filter(e => e.date >= today && !lowImpact(e) && ecoFamily(e) !== 'HOLIDAY').slice(0, n)
}

/**
 * The short form BRF's "Data this week" line shows: the period of an India release ("Oct"), the first US release of
 * the day (data-service sends one "US" row per day with its `items`), weekly / monthly for an expiry, the session name.
 */
export function ecoShortLabel(e: EcoLike & { items?: { name?: string | null }[] | null; monthly?: boolean | null }): string {
  const f = ecoFamily(e)
  if (f === 'IN_DATA') return (e.what.split(' · ')[1] ?? '').replace(/ 20\d\d$/, '')
  if (f === 'US_DATA') {
    const first = e.items?.[0]?.name ?? e.what.replace(/^US data:\s*/, '').split(/ \(| · /)[0]
    const more = (e.items?.length ?? 0) > 1 ? ` +${e.items!.length - 1}` : ''
    return `${first.length > 26 ? `${first.slice(0, 25)}…` : first}${more}`
  }
  if (f === 'EXPIRY') return e.monthly || /monthly/i.test(e.what) ? 'monthly' : 'weekly'
  if (f === 'SESSION') return e.what.split(' · ')[0]
  return ''
}

/** m012: a past release's print, or what to say when the calendar has none. */
export function ecoPrint(e: EcoLike, today: string): { text: string; known: boolean } {
  if (e.actual != null && e.actual !== '') return { text: e.actual, known: true }
  if (e.date >= today) return { text: e.forecast ? `fcst ${e.forecast}` : '', known: false }
  return { text: ecoFamily(e) === 'IN_DATA' ? 'not stored · see the source' : '', known: false }
}

// ── EVTS (M12, m042–m046) ──────────────────────────────────────────────────────────────────────────────────────

/**
 * m042: the "reacting" panel after the close. The API's phase stays 'session' all evening; the prices are end of day
 * (`source: 'eod'`), so the title says so and the chip is the session's date, not the window's start ('04 NOV').
 */
export function reactingHeading(phase: string | undefined, source: string | undefined, marketClosed: boolean, sessionDate: string, since: string,
                                todayIso: string): { title: string; asOf: string; live: boolean } {
  if (phase === 'preopen') return { title: 'Results · pre-open auction', asOf: sessionDate, live: false }
  if (phase === 'session' && !marketClosed && source !== 'eod') return { title: 'Reacting today · in session', asOf: sessionDate, live: true }
  if (phase === 'session') {
    return { title: `${sessionDate === todayIso ? 'Reacted today' : `Reacted ${dayMonth(sessionDate, true)}`} · end of day`, asOf: sessionDate, live: false }
  }
  return { title: 'Results since the last close · react at 09:15', asOf: since.slice(0, 10), live: false }
}

/** 'YYYY-MM-DD HH:MM…' or ISO → 'HH:MM', else ''. */
export const hhmm = (s: string | null | undefined): string => (/[ T](\d{2}:\d{2})/.exec(s ?? '')?.[1] ?? '')

/**
 * M12 (UI): the scoreboard's release time against the results filing NSE broadcast. When the earliest results filing
 * of that day is earlier than the stored release time (MOTHERSON 14:58:36 filed, scoreboard 20:34 "after close"), the
 * filing's time is shown and the row is marked: the reaction belongs to the filing's session.
 */
export function releaseCheck(releasedAt: string, filedAt: string | null | undefined): { time: string; differs: boolean; intraday: boolean } {
  const rel = hhmm(releasedAt), fil = hhmm(filedAt)
  const sameDay = !!filedAt && filedAt.slice(0, 10) === releasedAt.slice(0, 10)
  const differs = sameDay && !!fil && !!rel && fil < rel
  const t = differs ? fil : rel
  return { time: t, differs, intraday: !!t && t >= '09:15' && t < '15:30' }
}

/**
 * m043: options into results are a priced event only before the release. A name that filed during (or before) the
 * session whose closing chain is shown (`foDate`) is post-event: its "results-day move priced" is not a price of the
 * event.
 */
export function postEvent(resultsDate: string, foDate: string | null, filedAt: string | null | undefined): boolean {
  if (!foDate) return false
  if (resultsDate < foDate) return true
  if (resultsDate > foDate) return false
  const t = hhmm(filedAt)
  return !!t && t < '15:30'
}

/** m046: industry from the screen, else the symbol directory; returns the coverage too. */
export function fillIndustry<R extends { symbol: string; industry: string | null }>(rows: readonly R[], directory: ReadonlyMap<string, string | null>):
  { rows: R[]; known: number; total: number } {
  const out = rows.map(r => (r.industry ? r : { ...r, industry: directory.get(r.symbol) ?? null }))
  return { rows: out, known: out.filter(r => r.industry).length, total: out.length }
}

// ── DEAL / INSD (m031, m033–m036) ──────────────────────────────────────────────────────────────────────────────

/** The index close on or before `day` (ISO) from ascending {date, close} rows. */
export function closeOnOrBefore(series: readonly { date: string; close: number }[], day: string): number | null {
  let out: number | null = null
  for (const p of series) {
    if (p.date.slice(0, 10) <= day) out = p.close
    else break
  }
  return out
}

/**
 * m035 / m036: the move since a filing or a deal in excess of NIFTY over the same dates, ((1 + stock) ÷ (1 + NIFTY) − 1),
 * so a rising market (NIFTY +8 % since 30 Sep) does not read as an insider "hit rate". Null on the deal's own session
 * (no close after it yet: BCSSL showed "0.0 %").
 */
export function excessVsIndex(rawPct: number | null | undefined, start: string, end: string | null | undefined,
                              series: readonly { date: string; close: number }[] | null): number | null {
  if (rawPct == null || !end || end.slice(0, 10) <= start.slice(0, 10) || !series?.length) return null
  const a = closeOnOrBefore(series, start.slice(0, 10)), b = closeOnOrBefore(series, end.slice(0, 10))
  if (a == null || b == null || a <= 0) return null
  return ((1 + rawPct / 100) / (b / a) - 1) * 100
}

/** m031: a deal larger than the day's bhavcopy volume (the block window is not in it): not a share of the day. */
export function volShare(p: number | null | undefined): { text: string; capped: boolean } {
  if (p == null) return { text: '—', capped: false }
  return p > 100 ? { text: '> 100%', capped: true } : { text: `${p.toFixed(1)}%`, capped: false }
}

/** m032 (display only): an insurance BROKER is not an insurer (INTEGRATED INSURANCE BROKING SERVICES). */
export const isBrokerNotInsurer = (name: string | null | undefined): boolean => /INSURANCE\s+BROK/i.test(name ?? '')

export interface DealLike { date: string; symbol: string; client_name: string | null; direction: 'buy' | 'sell'; qty: number; value: number }

const NAME_STOP = new Set(['LIMITED', 'LTD', 'PRIVATE', 'PVT', 'SECURITIES', 'SECURITY', 'CAPITAL', 'FUND', 'FUNDS', 'INDIA', 'SERVICES',
  'TRUST', 'BANK', 'INVESTMENT', 'INVESTMENTS', 'HOLDINGS', 'HOLDING', 'MANAGEMENT', 'FINANCIAL', 'FINANCE', 'MARKETS', 'GLOBAL',
  'ASSET', 'ASSETS', 'ADVISORS', 'PARTNERS', 'COMPANY', 'CORPORATION', 'INTERNATIONAL', 'MAURITIUS', 'SINGAPORE', 'EUROPE', 'MASTER',
  'VENTURES', 'ENTERPRISES', 'INDUSTRIES', 'SHARES', 'STOCK', 'BROKING', 'TRADING', 'COMMODITIES', 'LLP', 'INC', 'PLC'])
/** Distinctive name tokens; the Bank of America family (BofA, Merrill) is one alias. */
function nameTokens(name: string | null | undefined): Set<string> {
  const n = (name ?? '').toUpperCase().replace(/BANK OF AMERICA|MERRILL LYNCH|\bBOFA\b/g, ' BOFAGROUP ').replace(/[^A-Z0-9 ]/g, ' ')
  return new Set(n.split(/\s+/).filter(t => t.length >= 4 && !NAME_STOP.has(t)))
}
/** Two client names that look like one group (a shared distinctive word: BofA Securities Europe ↔ Bank of America N.A.). */
export function sameGroupNames(a: string | null | undefined, b: string | null | undefined): boolean {
  const ta = nameTokens(a)
  for (const t of nameTokens(b)) if (ta.has(t)) return true
  return false
}

/**
 * m033: a buy and a sell of the same stock on the same day for (nearly) the same quantity between two names that look
 * like one group (a shared distinctive word, or the BofA family) is one internal transfer, not two flows. Every block
 * deal has a buyer and a seller of equal size, so equal quantity alone is not enough: an ordinary block (a promoter
 * selling to a fund) stays a flow. Returns the row keys of the matched legs (heuristic: quantities within 1 %).
 */
export function matchedTransfers(rows: readonly DealLike[], tol = 0.01): Set<string> {
  const key = (r: DealLike) => `${r.date}|${r.symbol}|${r.client_name}|${r.direction}`
  const by = new Map<string, DealLike[]>()
  for (const r of rows) { const k = `${r.date}|${r.symbol}`; by.set(k, [...(by.get(k) ?? []), r]) }
  const out = new Set<string>()
  for (const g of by.values()) {
    const buys = g.filter(r => r.direction === 'buy'), sells = g.filter(r => r.direction === 'sell')
    const used = new Set<DealLike>()
    for (const b of buys) {
      const s = sells.find(x => !used.has(x) && x.client_name !== b.client_name && sameGroupNames(x.client_name, b.client_name)
        && Math.abs(x.qty - b.qty) <= tol * Math.max(x.qty, b.qty))
      if (s) { used.add(s); out.add(key(b)); out.add(key(s)) }
    }
  }
  return out
}

// ── CF (M11 UI) ────────────────────────────────────────────────────────────────────────────────────────────────

/**
 * The list against the day's total: a truncated list says so, and a chip's whole-day count is not the list's.
 * `meta` = the route's own `truncated` / `total` / `returned` (ui-api since M11); without them (an older server that
 * cut at 1,000 silently) the whole-day category counts are compared with the list.
 */
export function cfCoverage(items: readonly { time: string | null }[], counts: Readonly<Record<string, number>>,
                           meta?: boolean | { truncated?: boolean; total?: number; returned?: number } | null):
  { shown: number; total: number; truncated: boolean; earliest: string } {
  const m = typeof meta === 'boolean' ? { truncated: meta } : (meta ?? {})
  const countsTotal = Object.values(counts).reduce((a, b) => a + b, 0)
  const times = items.map(i => i.time ?? '').filter(Boolean).sort()
  const total = m.total ?? countsTotal
  const truncated = m.total != null || m.returned != null ? (!!m.truncated || (m.total ?? 0) > (m.returned ?? items.length))
    : (!!m.truncated || countsTotal > items.length)
  return { shown: items.length, total, truncated, earliest: hhmm(times[0]) }
}

// ── WRAP (m022, M10 UI) ────────────────────────────────────────────────────────────────────────────────────────

/** m022: after the close and before tonight's wrap is stored, say when it lands instead of showing yesterday's silently. */
export function wrapPending(todayIso: string, istHHMM: number, latestWrap: string | null, isSessionDay: boolean): string | null {
  if (!isSessionDay || (latestWrap ?? '') >= todayIso || istHHMM < 1530) return null
  return `today's wrap is written after the evening data pass (≈ 21:00–21:30 IST); showing ${latestWrap ? dayMonth(latestWrap, true) : 'the last one'}`
}

/** M10 (UI): dates a wrap's sections carry that are not the wrap's own day ("NSE end of day 2026-10-30" under 04 Nov). */
export function wrapForeignDates(markdown: string, day: string): string[] {
  const found = new Set<string>()
  const re = /(end of day|as of|data for|EOD)\s*\(?(\d{4}-\d{2}-\d{2})/gi
  let m: RegExpExecArray | null
  while ((m = re.exec(markdown))) if (m[2] !== day) found.add(m[2])
  return [...found].sort()
}

// ── PRE (m013, m015) ───────────────────────────────────────────────────────────────────────────────────────────

/** NSE's '06-Nov-2026 09:09:49' → ISO date and HH:MM. */
export function nseStamp(s: string | null | undefined): { day: string | null; time: string } {
  return { day: nseDateIso(s), time: /(\d{2}:\d{2})/.exec(s ?? '')?.[1] ?? '' }
}

/**
 * m013: the auction label by the book's own date. A book from an earlier session is "the last session's auction"; this
 * morning's book after 09:15 is "this morning's auction (book 09:09) · regular session / market closed".
 */
export function preopenLabel(todayIso: string, istHHMM: number, weekday: boolean, bookStamp: string | null | undefined): { live: boolean; label: string; lastSession: boolean } {
  const { day, time } = nseStamp(bookStamp)
  const at = time ? ` (book ${time})` : ''
  if (day && day < todayIso) return { live: false, label: `last session's auction · ${dayMonth(day, true)}${at}`, lastSession: true }
  if (!weekday) return { live: false, label: `market closed today · last session's auction${at}`, lastSession: true }
  if (istHHMM < 900) return { live: false, label: `auction opens 09:00 · showing the last session${at}`, lastSession: true }
  if (istHHMM < 908) return { live: true, label: 'ORDER ENTRY · 09:00–09:08', lastSession: false }
  if (istHHMM < 915) return { live: true, label: 'PRICE DISCOVERY DONE · trading at 09:15', lastSession: false }
  return { live: false, label: `this morning's auction${at} · ${istHHMM < 1530 ? 'regular session now' : 'market closed'}`, lastSession: false }
}

/** m015: NSE's 52-week high is not adjusted for demergers or special dividends; a deep gap is flagged for a check. */
export const suspectYearHigh = (vsHighPct: number | null | undefined): boolean => vsHighPct != null && vsHighPct <= -60

// ── SEAG (m030) ────────────────────────────────────────────────────────────────────────────────────────────────

/** The first and last month that carry a RETURN (the first close only seeds the first return: 2012-02 → Mar 2012). */
export function seagSpan(grid: readonly { year: number; months: Record<string, number | null | undefined> }[], monthNames: readonly string[]): { first: string | null; last: string | null } {
  let first: string | null = null, last: string | null = null
  const rows = [...grid].sort((a, b) => a.year - b.year)
  for (const r of rows) for (const m of monthNames) {
    if (r.months[m] == null) continue
    const k = `${m} ${r.year}`
    if (!first) first = k
    last = k
  }
  return { first, last }
}

// ── IPO (m040) ─────────────────────────────────────────────────────────────────────────────────────────────────

/** A partly-paid or rights-entitlement line (ADANIENPP1), not an IPO. */
export const isEntitlementSymbol = (sym: string): boolean => /(PP|RE)\d+$|-RE$/.test(sym)

/** m040: one row per listing; entitlements out; rows NSE has no price for yet counted, not listed as "—" lines. */
export function ipoRows<R extends { symbol: string; listing_date: string; list_open: number | null; listing_gain_pct: number | null; last_close: number | null }>(rows: readonly R[]):
  { rows: R[]; entitlements: string[]; unpriced: string[] } {
  const seen = new Set<string>()
  const entitlements: string[] = [], unpriced: string[] = [], out: R[] = []
  for (const r of rows) {
    const k = `${r.symbol}|${r.listing_date}`
    if (seen.has(k)) continue
    seen.add(k)
    if (isEntitlementSymbol(r.symbol)) { if (!entitlements.includes(r.symbol)) entitlements.push(r.symbol); continue }
    if (r.list_open == null && r.listing_gain_pct == null && r.last_close == null) { unpriced.push(r.symbol); continue }
    out.push(r)
  }
  return { rows: out, entitlements, unpriced }
}

// ── COMP (m083) ────────────────────────────────────────────────────────────────────────────────────────────────

const INDEX_UNDERLYINGS = new Set(['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50', 'SENSEX', 'BANKEX'])
export const isIndexUnderlying = (s: string): boolean => INDEX_UNDERLYINGS.has(s.toUpperCase())

/**
 * m083: a one-name set opens the correlation panel empty. Suggest the active symbol (when it is a stock and not in the
 * set) and up to `n` same-sector names from the symbol directory, large caps first.
 */
export function compSuggestions(syms: readonly string[], active: string | null, directory: readonly { t: string; s: string | null; c: string | null }[], n = 3): string[] {
  const have = new Set(syms)
  const out: string[] = []
  if (active && !have.has(active) && !isIndexUnderlying(active)) out.push(active)
  const first = syms[0]
  const sector = first ? directory.find(d => d.t === first)?.s : null
  if (sector) {
    const peers = directory.filter(d => d.s === sector && !have.has(d.t) && !out.includes(d.t))
      .sort((a, b) => (a.c === 'Large Cap' ? 0 : 1) - (b.c === 'Large Cap' ? 0 : 1) || a.t.localeCompare(b.t))
    for (const p of peers) { if (out.length >= n + (active ? 1 : 0)) break; out.push(p.t) }
  }
  return out
}
