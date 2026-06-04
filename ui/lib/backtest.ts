/**
 * backtest.ts — typed contract + NDJSON streaming client for the Backtest Lab.
 *
 * Streams progress from POST /api/analytics/backtest(/wfo-backtest)/stream so the
 * cockpit can render a live progress bar + ETA, then delivers the final result.
 */

export interface BacktestFilter { field: string; op: string; value: number }

export interface BacktestParams {
  from_date: string
  to_date: string
  forward_days: number
  win_threshold: number
  filters: BacktestFilter[]
  max_stocks_per_day?: number
  starting_capital: number
  friction_bps: number
  stop_loss_pct: number | null
  trailing_stop_pct: number | null
  max_positions: number
  scope: 'universe' | 'watchlist'
  tickers?: string[]
  // WFO-only
  in_sample_days?: number
  out_sample_days?: number
  monte_carlo_runs?: number
}

export interface EquityPoint {
  date: string
  nav: number
  cash: number
  positions: number
  benchmark_nav: number
  drawdown_pct: number
}

export interface Trade {
  entry_date: string
  exit_date: string
  ticker: string
  entry_price: number
  exit_price: number
  gross_return_pct: number
  return_pct: number
  holding_days: number
  exit_reason: 'stop_loss' | 'trailing_stop' | 'time_stop'
  capital_allocated: number
  pnl: number
  is_win: boolean
}

export interface WfoWindow {
  start: string; end: string; trades: number
  return_pct: number; total_return_pct: number; win_rate: number
  best: number; worst: number
}

export interface MonteCarlo {
  p5: number; p25: number; p50: number; p75: number; p95: number; histogram: number[]
}

export interface BacktestResult {
  mode: string
  config: {
    from_date?: string; to_date?: string; forward_days?: number; win_threshold?: number
    starting_capital: number; friction_bps?: number
    stop_loss_pct?: number | null; trailing_stop_pct?: number | null
    max_positions?: number; scope: string; n_tickers: number; benchmark_label: string
  }
  fundamental_lookahead_active: boolean
  starting_capital: number
  final_nav: number
  total_return_pct: number
  cagr_pct: number
  benchmark_total_return_pct: number
  total_trades: number
  wins: number
  losses: number
  win_rate: number
  avg_return: number
  avg_win_return: number
  avg_loss_return: number
  win_loss_ratio: number
  expectancy: number
  profit_factor: number
  sharpe_ratio: number
  sortino_ratio: number
  calmar_ratio: number
  max_drawdown: number
  max_drawdown_duration_days: number
  beta: number
  alpha_annual_pct: number
  exit_breakdown: { stop_loss: number; trailing_stop: number; time_stop: number }
  equity_curve: EquityPoint[]
  trades: Trade[]
  wfo_windows?: WfoWindow[]
  monte_carlo?: MonteCarlo
}

export interface ProgressEvent { event: 'progress'; pct: number; label: string; eta_seconds: number | null }

interface StreamOpts {
  wfo?: boolean
  onProgress?: (e: ProgressEvent) => void
  onResult?: (r: BacktestResult) => void
  onError?: (detail: string) => void
  signal?: AbortSignal
}

/** Stream a backtest, parsing NDJSON progress + result events as they arrive. */
export async function streamBacktest(params: BacktestParams, opts: StreamOpts): Promise<void> {
  const url = opts.wfo ? '/api/analytics/wfo-backtest/stream' : '/api/analytics/backtest/stream'
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
    signal: opts.signal,
  })
  if (!res.ok || !res.body) {
    throw new Error(`Backtest request failed (${res.status})`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''

  // eslint-disable-next-line no-constant-condition
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let nl: number
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl).trim()
      buf = buf.slice(nl + 1)
      if (!line) continue
      let evt: any
      try { evt = JSON.parse(line) } catch { continue }
      if (evt.event === 'progress') opts.onProgress?.(evt as ProgressEvent)
      else if (evt.event === 'result') opts.onResult?.(evt.data as BacktestResult)
      else if (evt.event === 'error') opts.onError?.(evt.detail as string)
    }
  }
}
