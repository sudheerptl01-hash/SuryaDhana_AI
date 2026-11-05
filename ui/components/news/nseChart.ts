/**
 * The news dock's TERMINAL chart for an NSE pick (live program round 2, reports/live_nse, builder L2-UI): NSE's own
 * daily bars instead of Yahoo's. Pure, no DOM, no React, relative imports only (unit-tested under plain node by
 * ui/components/__tests__/live.check.ts, section L23). Used by news/NewsTerminal.tsx only.
 *
 *  - Daily ranges (1M … 2Y; 5Y as weekly bars labelled with each week's last trading day) from the stored NSE bhavcopy
 *    (`GET /api/stocks/{sym}/history`: bars as traded, newest first, `action_k` on split / bonus ex-dates), adjusted here
 *    the way the hover card and data-service do it (prices before an ex-date × its k, volume ÷ k), so a bonus is not
 *    drawn as a crash. End of day: the chip says EOD · <last session>.
 *  - 1D: 5-minute bars of the session from the tick store (`/api/charts/intraday`, built from Breeze ticks), when it
 *    holds any; an empty store says so — never a Yahoo bar. (5D is not offered for NSE picks: no stored source.)
 *  - The SMA 20 / 50 / 200 and RSI 14 overlays and the key stats (returns, RSI, ATR %, trend, volume ratio, distance to
 *    the 52-week high / low) are the Yahoo route's formulas (news_scanner.py _sma / _rsi / _atr_pct / _daily_stats) on
 *    these bars: the stats always from DAILY bars, whatever range is drawn.
 */
import type { Candle, ChartData, ChartStats, Point } from './types'

export interface HistRowLike {
  date: string; open: number | null; high: number | null; low: number | null; close: number | null
  volume: number | null; action_k?: number | null
}
export interface IntradayBarLike { t: string; o: number; h: number; l: number; c: number; v: number }

/** Calendar days of bhavcopy history read once per symbol per day (5 years of weekly bars + the SMA 200 warm-up). */
export const NSE_HISTORY_DAYS = 1900
/** Ranges the dock offers for an NSE pick (no 5D: there is no stored 15-minute history). */
export const NSE_RANGES = ['1d', '1mo', '3mo', '6mo', '1y', '2y', '5y'] as const
const KEEP_DAILY: Readonly<Record<string, number>> = { '1mo': 22, '3mo': 64, '6mo': 127, '1y': 253, '2y': 10_000 }
const FIVE_YEARS_DAYS = 1830

const fin = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
const dayTime = (d: string): number => {
  const [y, m, dd] = d.split('-').map(Number)
  return Date.UTC(y, (m || 1) - 1, dd || 1) / 1000
}

/** Bhavcopy rows (newest first) → adjusted daily candles, oldest first; time = the session's UTC midnight (epoch s). */
export function adjustedDailyCandles(rows: readonly HistRowLike[] | null | undefined): Candle[] {
  const out: Candle[] = []
  let k = 1
  const seen = new Set<string>()
  for (const r of rows ?? []) {
    if (!r || typeof r.date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(r.date) || seen.has(r.date)) continue
    const c = fin(r.close)
    if (c != null && c > 0) {
      seen.add(r.date)
      const o = fin(r.open) ?? c, h = fin(r.high) ?? Math.max(o, c), l = fin(r.low) ?? Math.min(o, c)
      const v = fin(r.volume) ?? 0
      const rd = (x: number) => Math.round(x * k * 100) / 100
      out.push({ time: dayTime(r.date), open: rd(o), high: rd(Math.max(h, o, c)), low: rd(Math.min(l, o, c)), close: rd(c), volume: Math.round(v / k) })
    }
    const ak = fin(r.action_k)
    if (ak != null && ak > 0) k *= ak                     // every OLDER row is scaled by this ex-date's factor
  }
  return out.reverse()
}

/** Daily candles → weekly (Mon–Sun buckets), each labelled with its last trading day. */
export function weeklyCandles(daily: readonly Candle[]): Candle[] {
  const out: Candle[] = []
  let key = -1
  for (const c of daily) {
    const dow = new Date(c.time * 1000).getUTCDay()                 // 0 = Sunday
    const monday = c.time - ((dow + 6) % 7) * 86_400
    if (monday !== key) { out.push({ ...c }); key = monday; continue }
    const w = out[out.length - 1]
    w.time = c.time; w.high = Math.max(w.high, c.high); w.low = Math.min(w.low, c.low); w.close = c.close; w.volume += c.volume
  }
  return out
}

export function smaSeries(vals: readonly number[], n: number): (number | null)[] {
  const out: (number | null)[] = new Array(vals.length).fill(null)
  let s = 0
  vals.forEach((v, i) => {
    s += v
    if (i >= n) s -= vals[i - n]
    if (i >= n - 1) out[i] = s / n
  })
  return out
}

/** Wilder's RSI, as news_scanner.py _rsi. */
export function rsiSeries(closes: readonly number[], n = 14): (number | null)[] {
  const out: (number | null)[] = new Array(closes.length).fill(null)
  if (closes.length <= n) return out
  let gains = 0, losses = 0
  for (let i = 1; i <= n; i++) { const d = closes[i] - closes[i - 1]; gains += Math.max(d, 0); losses += Math.max(-d, 0) }
  let ag = gains / n, al = losses / n
  out[n] = al ? 100 - 100 / (1 + ag / al) : 100
  for (let i = n + 1; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1]
    ag = (ag * (n - 1) + Math.max(d, 0)) / n
    al = (al * (n - 1) + Math.max(-d, 0)) / n
    out[i] = al ? 100 - 100 / (1 + ag / al) : 100
  }
  return out
}

const ret = (closes: readonly number[], bars: number): number | null =>
  closes.length <= bars || !closes[closes.length - bars - 1] ? null : (closes[closes.length - 1] / closes[closes.length - bars - 1] - 1) * 100

function atrPct(c: readonly Candle[], n = 14): number | null {
  if (c.length <= n) return null
  const trs: number[] = []
  for (let i = 1; i < c.length; i++) trs.push(Math.max(c[i].high - c[i].low, Math.abs(c[i].high - c[i - 1].close), Math.abs(c[i].low - c[i - 1].close)))
  const atr = trs.slice(-n).reduce((a, x) => a + x, 0) / n
  const last = c[c.length - 1].close
  return last ? (atr / last) * 100 : null
}

/** The key stats from DAILY adjusted candles (news_scanner.py _daily_stats); 52-week = the last 252 sessions' high / low. */
export function dailyStats(c: readonly Candle[]): ChartStats {
  const closes = c.map(x => x.close)
  const last = closes.length - 1
  const s20 = smaSeries(closes, 20), s50 = smaSeries(closes, 50), s200 = smaSeries(closes, 200), r = rsiSeries(closes)
  const tail20 = c.slice(-20)
  const vol20 = tail20.length ? tail20.reduce((a, x) => a + x.volume, 0) / Math.min(20, c.length) : 0
  const yr = c.slice(-252)
  const hi = yr.length ? Math.max(...yr.map(x => x.high)) : null, lo = yr.length ? Math.min(...yr.map(x => x.low)) : null
  const lastC = last >= 0 ? closes[last] : null
  return {
    ret_1d: ret(closes, 1), ret_5d: ret(closes, 5), ret_1m: ret(closes, 21), ret_3m: ret(closes, 63), ret_6m: ret(closes, 126), ret_1y: ret(closes, 252),
    rsi_14: last >= 0 ? r[last] : null, atr_pct: atrPct(c),
    sma20: last >= 0 ? s20[last] : null, sma50: last >= 0 ? s50[last] : null, sma200: last >= 0 ? s200[last] : null,
    above_sma50: last >= 0 && s50[last] != null ? closes[last] > (s50[last] as number) : null,
    above_sma200: last >= 0 && s200[last] != null ? closes[last] > (s200[last] as number) : null,
    avg_volume_20d: vol20 || null, volume_ratio: vol20 && c.length ? c[c.length - 1].volume / vol20 : null,
    pct_from_52w_high: hi && lastC != null ? (lastC / hi - 1) * 100 : null,
    pct_from_52w_low: lo && lastC != null ? (lastC / lo - 1) * 100 : null,
    history_days: c.length,
  }
}

function overlays(bars: readonly Candle[], start: number): Pick<ChartData, 'sma20' | 'sma50' | 'sma200' | 'rsi'> {
  const closes = bars.map(b => b.close)
  const series = (arr: (number | null)[]): Point[] => {
    const pts: Point[] = []
    for (let i = start; i < bars.length; i++) if (arr[i] != null) pts.push({ time: bars[i].time, value: Math.round((arr[i] as number) * 1e4) / 1e4 })
    return pts
  }
  return { sma20: series(smaSeries(closes, 20)), sma50: series(smaSeries(closes, 50)), sma200: series(smaSeries(closes, 200)), rsi: series(rsiSeries(closes)) }
}

export interface NseChart extends ChartData { last_date: string | null; source_kind: 'nse_bhavcopy' | 'tick_store' }

/** The dock's chart payload for a daily range from bhavcopy rows; null when there are fewer than 2 bars. */
export function nseDailyChart(sym: string, rows: readonly HistRowLike[] | null | undefined, range: string): NseChart | null {
  const daily = adjustedDailyCandles(rows)
  if (daily.length < 2) return null
  const lastDate = new Date(daily[daily.length - 1].time * 1000).toISOString().slice(0, 10)
  let bars: Candle[], start: number, interval: string
  if (range === '5y') {
    const from = daily[daily.length - 1].time - FIVE_YEARS_DAYS * 86_400
    bars = weeklyCandles(daily.filter(c => c.time >= from)); start = 0; interval = '1wk'
  } else {
    bars = daily; interval = '1d'
    start = Math.max(0, daily.length - (KEEP_DAILY[range] ?? KEEP_DAILY['1y']))
  }
  return {
    symbol: `${sym}.NS`, range, interval, intraday: false,
    quote: { symbol: `${sym}.NS`, available: false, currency: 'INR', gmtoffset: 0 },
    candles: bars.slice(start), ...overlays(bars, start), stats: dailyStats(daily),
    last_date: lastDate, source_kind: 'nse_bhavcopy',
  }
}

/** IST wall clock of 'YYYY-MM-DD' + 'HH:MM' as epoch seconds AS IF UTC (the chart axis then reads IST). */
function istWall(date: string, hhmm: string): number {
  const [y, m, d] = date.split('-').map(Number)
  const [hh, mm] = hhmm.split(':').map(Number)
  return Date.UTC(y, (m || 1) - 1, d || 1, hh || 0, mm || 0) / 1000
}

/** The 1D chart from the tick store's bars (stats still from daily rows); null when the store holds no bars. */
export function nseIntradayChart(sym: string, date: string, bars: readonly IntradayBarLike[] | null | undefined, dailyRows: readonly HistRowLike[] | null | undefined): NseChart | null {
  const c: Candle[] = (bars ?? []).filter(b => b && /^\d{2}:\d{2}$/.test(b.t) && [b.o, b.h, b.l, b.c].every(x => typeof x === 'number' && Number.isFinite(x) && x > 0))
    .map(b => ({ time: istWall(date, b.t), open: b.o, high: b.h, low: b.l, close: b.c, volume: Number.isFinite(b.v) ? b.v : 0 }))
  if (c.length < 2) return null
  return {
    symbol: `${sym}.NS`, range: '1d', interval: '5m', intraday: true,
    quote: { symbol: `${sym}.NS`, available: false, currency: 'INR', gmtoffset: 0 },
    candles: c, ...overlays(c, 0), stats: dailyStats(adjustedDailyCandles(dailyRows)),
    last_date: date, source_kind: 'tick_store',
  }
}
