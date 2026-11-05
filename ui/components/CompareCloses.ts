/**
 * COMP's price history (live program round 2, reports/live_nse, builder L2-UI): where each compared series comes from
 * and what its chip says. Pure, no DOM, no React, relative imports only (unit-tested under plain node by
 * ui/components/__tests__/live.check.ts, section L20).
 *
 *  - An NSE stock (a plain code: 'TCS', 'M&M', 'BAJAJ-AUTO') reads NSE's own stored closes — `GET /api/market/closes`
 *    (ui-api, SWR 10 min) ← data-service `/db/closes` ← the `nse_bhavcopy` EQ/BE series, split/bonus-adjusted, only
 *    sessions already stored. It was Yahoo's chart history under a chip that said "NSE closes" (L-INVENTORY D11).
 *    A stock the closes route does not know shows "no NSE closes": it is never filled from Yahoo.
 *  - The NIFTY 50 benchmark is an NSE index: it reads NSE's own daily index file through the same closes route
 *    ('NIFTY 50' → index_ohlc_daily, Terminal v2) when that covers the period; until it does (the table is new), the
 *    app's stored daily index closes (`GET /api/market/index-daily?symbol=NIFTY50`, market_index_daily, which can hold
 *    Yahoo-ingested rows — the chip says so). Never a Yahoo request from this page for it.
 *  - Only a symbol that is not an NSE code ('^GSPC', 'AAPL.US', a '.BO' code: a '^' or a '.' in it, the page's existing
 *    rule) still reads Yahoo's daily closes through the app's one Yahoo fetcher (/api/news-scanner/chart).
 *
 * Everything here is daily data: the chip is EOD · <last date> (STALE past 4 days) and the header line reads
 * 'NSE closes · <last date>'. Nothing on COMP is a live price.
 */
import { sourceOf, type SourceInfo } from './terminal/source'

export type ComparePeriod = '1mo' | '3mo' | '6mo' | '1y' | '2y'

/** Calendar days each period looks back (the closes route's `days`; series are trimmed to the same start date). */
export const PERIOD_DAYS: Readonly<Record<ComparePeriod, number>> = Object.freeze({ '1mo': 31, '3mo': 92, '6mo': 183, '1y': 366, '2y': 731 })

/** The benchmark's key in the compare set (kept from the Yahoo era: stored keys and colours depend on it). */
export const BENCH = '^NSEI'
/** market_index_daily's symbol for the NIFTY 50 (the /api/market/index-daily default). */
export const BENCH_STORE_SYMBOL = 'NIFTY50'
/** The closes route's name for the NIFTY 50 (NSE's daily index file, index_ohlc_daily). */
export const BENCH_CLOSES_SYMBOL = 'NIFTY 50'
/** A benchmark series counts as covering the period when it starts within this many calendar days of the start. */
export const BENCH_SLACK_DAYS = 10

export type BenchSource = 'nse_index_file' | 'index_store'

export interface Series { sym: string; dates: string[]; close: number[] }

/** An NSE stock code as COMP holds it (no '^', no '.', the page's existing rule for "send to Yahoo"). */
export function isNseCode(sym: string): boolean {
  const s = sym.trim().toUpperCase()
  return s !== BENCH && /^[A-Z0-9&-]{1,20}$/.test(s)
}

/**
 * Which source a compared symbol reads: the NSE closes route, the stored index closes (benchmark), Yahoo (only a
 * '^' index or a dotted non-NSE code, the page's existing rule) or nothing (not a valid code: never sent anywhere, so
 * one bad entry cannot fail the whole closes batch).
 */
export function seriesSource(sym: string): 'nse_closes' | 'index_store' | 'yahoo' | 'invalid' {
  if (sym === BENCH) return 'index_store'
  if (isNseCode(sym)) return 'nse_closes'
  return /^\^|\./.test(sym) ? 'yahoo' : 'invalid'
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/

/** 'YYYY-MM-DD' `days` calendar days before `today` (UTC calendar arithmetic on the IST date string). */
export function periodStart(today: string, period: ComparePeriod): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(today)
  if (!m) return '0000-00-00'
  const t = Date.UTC(+m[1], +m[2] - 1, +m[3]) - PERIOD_DAYS[period] * 86_400_000
  return new Date(t).toISOString().slice(0, 10)
}

/** Today's date in IST ('YYYY-MM-DD'). */
export function istToday(now: number): string {
  return new Date(now + 330 * 60_000).toISOString().slice(0, 10)
}

/**
 * Raw [{date, close}] points → a validated series, oldest first, one point per date (the last one wins), only finite
 * positive closes on 'YYYY-MM-DD' dates, trimmed to `start` and later. Null when nothing usable is left.
 */
export function cleanSeries(sym: string, points: unknown, start: string): Series | null {
  if (!Array.isArray(points)) return null
  const byDate = new Map<string, number>()
  for (const p of points) {
    if (!p || typeof p !== 'object') continue
    const d = (p as { date?: unknown }).date, c = (p as { close?: unknown }).close
    const close = typeof c === 'number' ? c : typeof c === 'string' && c.trim() !== '' ? Number(c) : NaN
    if (typeof d !== 'string' || !DATE_RE.test(d.slice(0, 10)) || !Number.isFinite(close) || close <= 0) continue
    const day = d.slice(0, 10)
    if (day >= start) byDate.set(day, close)
  }
  if (!byDate.size) return null
  const dates = [...byDate.keys()].sort()
  return { sym, dates, close: dates.map(d => byDate.get(d) as number) }
}

export interface ClosesBody { as_of?: unknown; source?: unknown; series?: unknown }

/**
 * The closes route's body → one series per asked NSE symbol (keys matched case-insensitively; '.NS' tolerated).
 * A symbol the route did not return, or returned empty, maps to null ("no NSE closes"), never to another source.
 */
export function seriesFromCloses(body: ClosesBody | null | undefined, symbols: readonly string[], start: string): Record<string, Series | null> {
  const raw = body && typeof body.series === 'object' && body.series && !Array.isArray(body.series) ? (body.series as Record<string, unknown>) : {}
  const byKey = new Map<string, unknown>()
  for (const [k, v] of Object.entries(raw)) byKey.set(k.trim().toUpperCase().replace(/\.NS$/, ''), v)
  const out: Record<string, Series | null> = {}
  for (const s of symbols) out[s] = cleanSeries(s, byKey.get(s.toUpperCase()), start)
  return out
}

/** The stored index closes (/api/market/index-daily: {rows: [{date, close}]} oldest first) → the benchmark series. */
export function benchFromIndexDaily(body: { rows?: unknown } | null | undefined, start: string): Series | null {
  return cleanSeries(BENCH, body?.rows, start)
}

/** True when `s` starts within BENCH_SLACK_DAYS of `start` (a 3-session-old table does not make a 1-year line). */
export function coversPeriod(s: Series | null | undefined, start: string): boolean {
  if (!s || s.dates.length < 2) return false
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(start)
  if (!m) return false
  const lim = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]) + BENCH_SLACK_DAYS * 86_400_000).toISOString().slice(0, 10)
  return s.dates[0] <= lim
}

/**
 * The benchmark line: NSE's daily index file (closes route) when it covers the period, else the stored index closes
 * (market_index_daily), else none. Says which, for the chip.
 */
export function pickBench(fromCloses: Series | null, fromStore: Series | null, start: string): { series: Series | null; source: BenchSource | null } {
  if (coversPeriod(fromCloses, start)) return { series: { ...(fromCloses as Series), sym: BENCH }, source: 'nse_index_file' }
  if (fromStore && fromStore.dates.length >= 2) return { series: { ...fromStore, sym: BENCH }, source: 'index_store' }
  if (fromCloses && fromCloses.dates.length >= 2) return { series: { ...fromCloses, sym: BENCH }, source: 'nse_index_file' }
  return { series: null, source: null }
}

/** Yahoo chart candles ({time: epoch s, close}) → a series (non-NSE symbols only). */
export function seriesFromCandles(sym: string, candles: unknown, start: string): Series | null {
  if (!Array.isArray(candles)) return null
  const pts = candles.map(c => {
    const t = (c as { time?: unknown })?.time
    return { date: typeof t === 'number' && Number.isFinite(t) ? new Date(t * 1000).toISOString().slice(0, 10) : null, close: (c as { close?: unknown })?.close }
  })
  return cleanSeries(sym, pts, start)
}

/** The last stored date over the NSE series (the as-of the chip and the header line print); null when none. */
export function lastNseDate(series: Readonly<Record<string, Series | 'error' | null | undefined>>): string | null {
  let last: string | null = null
  for (const [sym, s] of Object.entries(series)) {
    if (!s || s === 'error' || seriesSource(sym) !== 'nse_closes') continue
    const d = s.dates[s.dates.length - 1]
    if (d && (last == null || d > last)) last = d
  }
  return last
}

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** 'NSE closes · 04 Nov 2026' (the header label the brief asks for); 'NSE closes · none stored' without a date. */
export function closesLabel(last: string | null): string {
  const m = last ? /^(\d{4})-(\d{2})-(\d{2})$/.exec(last) : null
  return m ? `NSE closes · ${m[3]} ${MON[Number(m[2]) - 1]} ${m[1]}` : 'NSE closes · none stored'
}

/**
 * The panels' SourceChip: EOD · <the newest NSE close> (STALE past 4 days; OFFLINE without one), source 'NSE closes',
 * and a hint that names every source on the page: the bhavcopy closes, the stored NIFTY 50 closes, Yahoo for the
 * non-NSE symbols (named), and the route's state when it is not deployed.
 */
export function compareSource(series: Readonly<Record<string, Series | 'error' | null | undefined>>,
  opts: { routeMissing?: boolean; bench?: BenchSource | null; now?: Date } = {}): SourceInfo {
  const last = lastNseDate(series)
  const yahoo = Object.keys(series).filter(s => seriesSource(s) === 'yahoo')
  const parts = ['NSE bhavcopy closes (EQ/BE, split- and bonus-adjusted), end of day: not a live feed',
    opts.bench === 'nse_index_file' ? "NIFTY 50: NSE's daily index file"
      : opts.bench === 'index_store' ? "NIFTY 50: the app's stored index closes (market_index_daily; older rows may be Yahoo-ingested) until NSE's daily index file covers the period"
        : 'NIFTY 50: no stored closes']
  if (yahoo.length) parts.push(`${yahoo.join(', ')}: not NSE codes, Yahoo daily closes`)
  if (opts.routeMissing) parts.push('the NSE closes route (/api/market/closes) is not deployed on this ui-api')
  return sourceOf(last, { source: 'NSE closes', hint: parts.join(' · '), now: opts.now })
}

/** Why a compared symbol has no line (shown beside its tag). */
export function missingReason(sym: string, routeMissing: boolean, closesError?: string | null): string {
  const src = seriesSource(sym)
  if (src === 'nse_closes') return routeMissing ? 'NSE closes route not deployed' : closesError ? `NSE closes unavailable: ${closesError}` : 'no NSE closes stored'
  if (src === 'index_store') return 'no stored NIFTY 50 closes'
  if (src === 'invalid') return 'not an NSE code'
  return 'no Yahoo data'
}
