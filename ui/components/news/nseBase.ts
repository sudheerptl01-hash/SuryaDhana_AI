/**
 * The NSE base layer of WTCH and the news dock (live program round 2, reports/live_nse, builder L2-UI). Pure, no DOM,
 * no React of its own, relative imports only (unit-tested under plain node by ui/components/__tests__/live.check.ts,
 * section L22). Used by WatchMonitor.tsx and news/NewsTerminal.tsx only.
 *
 * An NSE row is built from two NSE sources and nothing else:
 *  - the stored half — company name, the one-month sparkline (the last 22 daily closes) and the 52-week range — from
 *    NSE's own stored closes: `GET /api/market/closes?symbols=…&days=366` (L2-API: nse_bhavcopy EQ/BE, split- and
 *    bonus-adjusted, only sessions already stored; `meta.high/low` = the adjusted 52-week high / low, `meta.name` =
 *    NSE's EQUITY_L company name). One request for the whole list, end of day, refreshed every 10 min;
 *  - the live half — price, day move, day range, volume — from the live quote hook (lib/liveQuotes: Breeze websocket →
 *    NSE's website → the last close), overlaid with the hook's own rule (an in-session EOD row never paints yesterday's
 *    move as today's).
 * No Yahoo request is made for an NSE row (the 60 s news-scanner quotes call carries only non-NSE symbols: US names,
 * commodities, FX). The one exception is the pre-live world: while /api/live/quotes answers 404 (the live service is
 * not deployed on this ui-api) the panes keep the pre-live quotes route for NSE rows and label it with its own source.
 */
import { isStaleEod, overlayQuote, type LiveQuote } from '../../lib/liveQuotes'

/** Calendar days of stored closes the base asks for (52 weeks). */
export const BASE_DAYS = 366
/** Sessions in the one-month sparkline. */
export const SPARK_N = 22
/** The stored half changes once a day (bhavcopy ~18:30): re-read every 10 min (the route's own SWR window). */
export const BASE_REFRESH_MS = 10 * 60_000
/** The closes route's cap per request (and 300 × 366 days stays under its symbol-day budget). */
export const BASE_CHUNK = 300
/** Below this many stored sessions a closing range is not a 52-week range. */
export const MIN_SESSIONS_52W = 200

export interface NseBase {
  symbol: string
  /** NSE's company name (EQUITY_L) when the route carries it */
  name: string | null
  /** the last SPARK_N adjusted closes, oldest first */
  spark: number[]
  high_52w: number | null
  low_52w: number | null
  /** 'high_low': the adjusted daily high / low (route meta); 'closes': the closing range (meta absent) */
  range_basis: 'high_low' | 'closes' | null
  /** the last stored session ('YYYY-MM-DD') */
  last_date: string | null
}

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/
const fin = (v: unknown): number | null => {
  const n = typeof v === 'number' ? v : typeof v === 'string' && v.trim() !== '' ? Number(v) : NaN
  return Number.isFinite(n) ? n : null
}

/** 'TCS.NS' / 'tcs' → 'TCS'; null for anything that is not an NSE stock code. */
export function nseCode(sym: string | null | undefined): string | null {
  const s = String(sym ?? '').trim().toUpperCase().replace(/\.NS$/, '')
  return /^[A-Z0-9&-]{1,20}$/.test(s) ? s : null
}

/** A Yahoo-form symbol of an NSE stock ('TCS.NS'). */
export function isNseYahoo(y: string): boolean {
  return /\.NS$/i.test(y) && nseCode(y) != null
}

/**
 * The closes route's body → the stored half per asked NSE symbol (null: the route has no closes for it — the row then
 * shows no spark / 52-week range, never another source's).
 */
export function nseBaseFromCloses(body: unknown, symbols: readonly string[]): Record<string, NseBase | null> {
  const b = body && typeof body === 'object' && !Array.isArray(body) ? (body as Record<string, unknown>) : {}
  const series = b.series && typeof b.series === 'object' && !Array.isArray(b.series) ? (b.series as Record<string, unknown>) : {}
  const meta = b.meta && typeof b.meta === 'object' && !Array.isArray(b.meta) ? (b.meta as Record<string, unknown>) : {}
  const keyed = (o: Record<string, unknown>) => new Map(Object.entries(o).map(([k, v]) => [nseCode(k) ?? k, v]))
  const S = keyed(series), M = keyed(meta)
  const out: Record<string, NseBase | null> = {}
  for (const raw of symbols) {
    const sym = nseCode(raw)
    if (!sym) continue
    const pts = Array.isArray(S.get(sym)) ? (S.get(sym) as unknown[]) : []
    const byDate = new Map<string, number>()
    for (const p of pts) {
      if (!p || typeof p !== 'object') continue
      const d = (p as { date?: unknown }).date, c = fin((p as { close?: unknown }).close)
      if (typeof d === 'string' && DATE_RE.test(d) && c != null && c > 0) byDate.set(d, c)
    }
    const dates = [...byDate.keys()].sort()
    const m = (M.get(sym) && typeof M.get(sym) === 'object' ? M.get(sym) : {}) as Record<string, unknown>
    if (!dates.length) { out[sym] = null; continue }
    const closes = dates.map(d => byDate.get(d) as number)
    const mh = fin(m.high), ml = fin(m.low)
    let high: number | null = null, low: number | null = null, basis: NseBase['range_basis'] = null
    if (mh != null && ml != null && mh > 0 && ml > 0 && mh >= ml) { high = mh; low = ml; basis = 'high_low' }
    else if (closes.length >= MIN_SESSIONS_52W) { high = Math.max(...closes); low = Math.min(...closes); basis = 'closes' }
    out[sym] = {
      symbol: sym,
      name: typeof m.name === 'string' && m.name.trim() ? m.name.trim() : null,
      spark: closes.slice(-SPARK_N),
      high_52w: high, low_52w: low, range_basis: basis,
      last_date: typeof m.last_date === 'string' && DATE_RE.test(m.last_date) ? m.last_date : dates[dates.length - 1],
    }
  }
  return out
}

/** 'YYYY-MM-DD' (IST) of an ISO time; null when unparsable. */
function istDay(iso: string | null | undefined): string | null {
  const t = iso ? Date.parse(iso) : NaN
  return Number.isFinite(t) ? new Date(t + 330 * 60_000).toISOString().slice(0, 10) : null
}

/** The quote-shaped row (the news-scanner `Quote` keys WTCH and the dock render) of one NSE stock. */
export interface NseQuoteRow {
  symbol: string
  available: boolean
  name?: string
  currency: 'INR'
  exchange: 'NSE'
  price?: number
  change?: number
  change_pct?: number
  prev_close?: number
  day_high?: number
  day_low?: number
  volume?: number
  high_52w?: number
  low_52w?: number
  spark?: number[]
  market_time?: number
  stale?: boolean
  /** where the row's parts come from (for titles and the static gate) */
  base_source: 'nse_closes' | null
  range_basis: NseBase['range_basis']
  eod_as_of: string | null
  live_source?: string
  live_state?: string
  [k: string]: unknown
}

/**
 * The displayed NSE row: the stored half from `base`, the live half from `live` (lib/liveQuotes overlayQuote). Today's
 * live point extends the sparkline and the 52-week range when the stored closes end before today's session; an
 * in-session EOD row (the previous close, 'stale') never does, and its change is never shown as today's.
 */
export function nseQuoteRow(sym: string, base: NseBase | null | undefined, live: LiveQuote | null | undefined, fallbackName?: string | null): NseQuoteRow {
  const code = nseCode(sym) ?? sym
  const row: NseQuoteRow = {
    symbol: `${code}.NS`, available: false, currency: 'INR', exchange: 'NSE',
    name: base?.name ?? fallbackName ?? undefined,
    spark: base?.spark?.length ? [...base.spark] : undefined,
    high_52w: base?.high_52w ?? undefined, low_52w: base?.low_52w ?? undefined,
    base_source: base ? 'nse_closes' : null, range_basis: base?.range_basis ?? null, eod_as_of: base?.last_date ?? null,
  }
  const o = overlayQuote(row as unknown as Record<string, unknown>, live) as unknown as NseQuoteRow
  if (!live || o === (row as unknown) || live.price == null) return row
  const out: NseQuoteRow = { ...o }
  const t = live.ltt ? Date.parse(live.ltt) : NaN
  if (Number.isFinite(t)) out.market_time = Math.floor(t / 1000)
  out.stale = live.state === 'stale'
  if (!isStaleEod(live)) {
    const day = istDay(live.ltt)
    const newer = !!day && (!base?.last_date || day > base.last_date)
    if (newer && out.spark?.length) out.spark = [...out.spark, live.price].slice(-SPARK_N)
    if (out.high_52w != null) out.high_52w = Math.max(out.high_52w, live.day_high ?? live.price, live.price)
    if (out.low_52w != null) out.low_52w = Math.min(out.low_52w, live.day_low ?? live.price, live.price)
  }
  return out
}

/** The 1M / 52W column titles: what the numbers are and the stored session they end on. */
export function baseTitles(b: Pick<NseQuoteRow, 'eod_as_of' | 'range_basis' | 'base_source'> | null | undefined): { spark: string; range: string } {
  if (!b || b.base_source !== 'nse_closes') return { spark: 'no stored NSE closes for this name', range: 'no stored NSE 52-week range for this name' }
  const asOf = b.eod_as_of ? ` (stored to ${b.eod_as_of})` : ''
  return {
    spark: `last ${SPARK_N} NSE daily closes, split/bonus-adjusted${asOf}, plus today's live point in session`,
    range: b.range_basis === 'high_low' ? `52-week high / low on adjusted NSE daily bars${asOf}, widened by today's range`
      : b.range_basis === 'closes' ? `52-week CLOSING range from NSE daily closes${asOf} (high / low not in the payload), widened by today's range`
        : 'fewer than 200 stored sessions: no 52-week range',
  }
}

/** Split a Yahoo-form list into NSE codes (base layer + live hook) and everything else (Yahoo, non-NSE only). */
export function splitSymbols(yahooSyms: readonly string[]): { nse: string[]; other: string[] } {
  const nse: string[] = [], other: string[] = []
  for (const y of yahooSyms) {
    const c = isNseYahoo(y) ? nseCode(y) : null
    if (c) nse.push(c); else other.push(y)
  }
  return { nse: [...new Set(nse)].sort(), other: [...new Set(other)].sort() }
}

/** The symbols the 60 s news-scanner quotes call may carry: non-NSE always; NSE '.NS' only while the live route is
 *  not deployed (status 'missing': the pre-live world, labelled by the route's own source). */
export function yahooCallSymbols(yahooSyms: readonly string[], liveStatus: string): string[] {
  const { nse, other } = splitSymbols(yahooSyms)
  return liveStatus === 'missing' ? [...other, ...nse.map(s => `${s}.NS`)] : other
}
