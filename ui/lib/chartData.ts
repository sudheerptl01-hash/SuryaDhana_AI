/**
 * chartData.ts — CHRT chart studio data layer (worldclass W1).
 *
 * Typed fetchers for /api/charts/* plus the indicator math, kept as small pure
 * functions over plain arrays so each one is unit-testable and auditable:
 *   - ema():       seeded with the SMA of the first `period` values, k = 2/(period+1)
 *   - bollinger(): SMA(period) ± mult·σ with POPULATION σ (ddof 0 — the charting
 *                  convention, TradingView-compatible), not sample σ
 *   - rsi():       Wilder's RSI — first average is the simple mean of the first
 *                  `period` changes, then Wilder smoothing (n−1)/n
 * Every series is index-aligned with its input bars; warm-up slots are null.
 */

// ── types (mirror services/ui-api/routers/charts.py) ──────────────────────────

export type Timeframe = 'D' | 'W' | 'M'
export type IntradayInterval = '1m' | '5m' | '15m'
export type ChartTf = Timeframe | IntradayInterval

/** One bar: t is 'YYYY-MM-DD' (EOD) or 'HH:MM' IST (intraday, W6 tick-store contract). */
export interface ChartBar { t: string; o: number; h: number; l: number; c: number; v: number }

export interface OhlcvResponse {
  symbol: string
  tf: Timeframe
  days: number
  bars: ChartBar[]
  rows: number
  as_of: string | null
  source: string
}

export interface IntradayResponse {
  symbol: string
  date: string
  interval: IntradayInterval
  bars: ChartBar[]
  vwap: number | null
  source: string | null
  note?: string
  ok?: boolean
  error_info?: { code: string; message: string; hint?: string }
}

// ── fetchers (relative /api paths: Next rewrites proxy to ui-api) ─────────────

const qs = (o: Record<string, string | number | undefined>): string =>
  Object.entries(o)
    .filter(([, v]) => v !== undefined && v !== '')
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`)
    .join('&')

async function getJson<T>(url: string): Promise<T> {
  const r = await fetch(url)
  let body: unknown = null
  try { body = await r.json() } catch { /* non-JSON body → status-based error below */ }
  if (!r.ok) {
    const b = body as { error?: { message?: string }; detail?: unknown } | null
    const msg = b?.error?.message ?? (typeof b?.detail === 'string' ? b.detail : `HTTP ${r.status}`)
    throw new Error(msg)
  }
  return body as T
}

export const fetchDailyBars = (symbol: string, tf: Timeframe, days: number): Promise<OhlcvResponse> =>
  getJson<OhlcvResponse>(`/api/charts/ohlcv?${qs({ symbol, tf, days })}`)

export const fetchIntradayBars = (symbol: string, interval: IntradayInterval, date?: string): Promise<IntradayResponse> =>
  getJson<IntradayResponse>(`/api/charts/intraday?${qs({ symbol, interval, date })}`)

// ── time helpers ───────────────────────────────────────────────────────────────

/** 'YYYY-MM-DD' + 'HH:MM' IST → epoch seconds of that wall-clock time AS IF UTC.
 *  lightweight-charts renders timestamps on a UTC axis, so pre-shifting makes the
 *  axis and crosshair read IST directly (the terminal's convention — IndexIntraday
 *  does the same). Never use these values as real Unix timestamps. */
export function istChartTime(date: string, hhmm: string): number {
  const [y, m, d] = date.split('-').map(Number)
  const [hh, mm] = hhmm.split(':').map(Number)
  return Date.UTC(y, (m || 1) - 1, d || 1, hh || 0, mm || 0) / 1000
}

// ── indicator math (pure, index-aligned, null during warm-up) ─────────────────

export function sma(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null)
  if (period <= 0 || values.length < period) return out
  let sum = 0
  for (let i = 0; i < values.length; i++) {
    sum += values[i]
    if (i >= period) sum -= values[i - period]
    if (i >= period - 1) out[i] = sum / period
  }
  return out
}

export function ema(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null)
  if (period <= 0 || values.length < period) return out
  const k = 2 / (period + 1)
  let seed = 0
  for (let i = 0; i < period; i++) seed += values[i]
  let prev = seed / period
  out[period - 1] = prev
  for (let i = period; i < values.length; i++) {
    prev = values[i] * k + prev * (1 - k)
    out[i] = prev
  }
  return out
}

export interface BollingerBands { mid: (number | null)[]; upper: (number | null)[]; lower: (number | null)[] }

export function bollinger(values: number[], period = 20, mult = 2): BollingerBands {
  const mid = sma(values, period)
  const upper: (number | null)[] = new Array(values.length).fill(null)
  const lower: (number | null)[] = new Array(values.length).fill(null)
  for (let i = period - 1; i < values.length; i++) {
    const m = mid[i]
    if (m == null) continue
    let s2 = 0
    for (let j = i - period + 1; j <= i; j++) s2 += (values[j] - m) * (values[j] - m)
    const sd = Math.sqrt(s2 / period) // population σ (ddof 0)
    upper[i] = m + mult * sd
    lower[i] = m - mult * sd
  }
  return { mid, upper, lower }
}

/** Wilder's RSI. All-gain window → 100, all-loss → 0, perfectly flat → 50. */
export function rsi(values: number[], period = 14): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null)
  if (period <= 0 || values.length <= period) return out
  let gain = 0
  let loss = 0
  for (let i = 1; i <= period; i++) {
    const d = values[i] - values[i - 1]
    if (d >= 0) gain += d
    else loss -= d
  }
  let avgG = gain / period
  let avgL = loss / period
  const toRsi = (g: number, l: number): number =>
    l === 0 ? (g === 0 ? 50 : 100) : 100 - 100 / (1 + g / l)
  out[period] = toRsi(avgG, avgL)
  for (let i = period + 1; i < values.length; i++) {
    const d = values[i] - values[i - 1]
    avgG = (avgG * (period - 1) + Math.max(d, 0)) / period
    avgL = (avgL * (period - 1) + Math.max(-d, 0)) / period
    out[i] = toRsi(avgG, avgL)
  }
  return out
}

// ── presentation defaults ─────────────────────────────────────────────────────

/** EOD lookback window (calendar days) that suits each resample: enough bars to
 *  fill the pane and warm up EMA200 without hauling the whole panel over. */
export const DEFAULT_DAYS: Record<Timeframe, number> = { D: 540, W: 2200, M: 7320 }

export const RANGE_OPTIONS: { value: string; label: string }[] = [
  { value: '180', label: '6M' },
  { value: '365', label: '1Y' },
  { value: '1095', label: '3Y' },
  { value: '1825', label: '5Y' },
  { value: '3650', label: '10Y' },
  { value: '7320', label: 'MAX' },
]
