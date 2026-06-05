/**
 * glassbox.ts — typed clients for the Pillar-2 "glass-box" charting endpoints.
 *
 *  • factor-series  → rolling correlation + squeeze/VIPT flags for one asset
 *  • rrg            → Relative Rotation Graph trajectories for a basket
 *  • volume-profile → horizontal volume-by-price (HVN/LVN/POC) + anchored VWAP
 */

export interface FactorSeriesPoint {
  date: string
  open: number | null; high: number | null; low: number | null; close: number | null
  volume: number | null
  corr30: number | null
  squeeze_on: boolean
  squeeze_ratio: number | null
  vmi_ratio: number | null
  vol_zscore_20: number | null
  vipt_breakout: boolean
}
export interface FactorSeriesResult {
  mode: string; ticker: string; benchmark: string; corr_window: number; n: number
  points: FactorSeriesPoint[]
}

export interface RRGPoint { date: string; rs_ratio: number | null; rs_mom: number | null; quadrant: string }
export interface RRGResult {
  mode: string; benchmark: string; window: number; momentum: number
  tickers: Record<string, RRGPoint[]>
}

export interface VolumeBin {
  price_lo: number; price_hi: number; price_mid: number
  volume: number; pct: number; node: 'HVN' | 'LVN'; poc: boolean
}
export interface VPOhlc { date: string; open: number | null; high: number | null; low: number | null; close: number | null; avwap: number | null }
export interface VolumeProfileResult {
  mode: string; ticker: string; n_bars: number
  price_lo: number; price_hi: number; poc_price: number
  bins: VolumeBin[]; ohlc: VPOhlc[]
}

async function post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  const res = await fetch(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body), signal,
  })
  if (!res.ok) {
    let detail = `${path} failed (${res.status})`
    try { detail = (await res.json()).detail || detail } catch { /* keep */ }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

export const fetchFactorSeries = (p: { ticker: string; from_date: string; to_date: string; corr_window?: number }, signal?: AbortSignal) =>
  post<FactorSeriesResult>('/api/analytics/factor-series', p, signal)

export const fetchRRG = (p: { tickers: string[]; from_date: string; to_date: string; window?: number; momentum?: number; tail?: number }, signal?: AbortSignal) =>
  post<RRGResult>('/api/analytics/rrg', p, signal)

export const fetchVolumeProfile = (p: { ticker: string; from_date: string; to_date: string; bins?: number }, signal?: AbortSignal) =>
  post<VolumeProfileResult>('/api/analytics/volume-profile', p, signal)
