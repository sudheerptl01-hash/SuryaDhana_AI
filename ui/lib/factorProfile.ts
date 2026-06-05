/**
 * factorProfile.ts — typed client for the Factor Decile Profiler.
 *
 * POST /api/analytics/factor-profile returns the decile/base-rate diagnostic for a
 * single numeric factor over the current Backtest Lab window + scope. Pure JSON
 * (not streamed) — the heavy lift runs server-side in a worker thread.
 */

export interface FactorDecile {
  decile: number
  lo: number          // lower quantile edge of the bucket
  hi: number          // upper quantile edge of the bucket
  obs_lo: number      // realised min of the factor inside the bucket
  obs_hi: number      // realised max of the factor inside the bucket
  samples: number
  positives: number
  event_rate: number  // % of bucket that were forward wins
  lift: number        // event_rate - global_base_rate (percentage points)
}

export interface FactorProfileResult {
  mode: string
  factor: string
  factor_label: string
  unit: string
  category: string
  lookahead_bias_present: boolean
  forward_days: number
  win_threshold: number
  friction_bps: number
  config: { scope: string; n_tickers: number; from_date: string; to_date: string }
  deciles: FactorDecile[]
  global_base_rate: number
  total_samples: number
  total_positives: number
  n_deciles_requested: number
  n_deciles_effective: number
  monotonicity_spearman: number
  best_decile: number | null
  worst_decile: number | null
  degenerate: boolean
  note?: string
}

export interface FactorProfileParams {
  factor: string
  from_date: string
  to_date: string
  forward_days: number
  win_threshold: number
  friction_bps: number
  scope: 'universe' | 'watchlist'
  tickers?: string[]
  n_deciles?: number
}

export async function fetchFactorProfile(
  params: FactorProfileParams,
  signal?: AbortSignal,
): Promise<FactorProfileResult> {
  const res = await fetch('/api/analytics/factor-profile', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ n_deciles: 10, ...params }),
    signal,
  })
  if (!res.ok) {
    let detail = `Factor profile request failed (${res.status})`
    try { detail = (await res.json())?.detail || detail } catch { /* non-JSON */ }
    throw new Error(detail)
  }
  return (await res.json()) as FactorProfileResult
}
