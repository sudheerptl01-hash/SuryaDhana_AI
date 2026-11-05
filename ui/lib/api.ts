import axios, { type AxiosResponse } from 'axios'
import { createSharedCache } from './sharedFetch'

// Use relative paths so Next.js rewrites proxy /api/* to the backend.
// Works both in Docker (ui-api:8000 internal) and local dev (localhost:8010).
const client = axios.create({
  baseURL: '',
  timeout: 10000,
})

// Dashboard
export const getDashboardSummary  = () => client.get('/api/dashboard/summary')
export const getEnrichmentStatus  = () => client.get('/api/dashboard/enrichment-status')
export const getUniverseStatus    = () => client.get('/api/dashboard/universe-status')
export const bootstrapUniverse    = () => client.post('/api/dashboard/bootstrap-universe', {}, { timeout: 60000 })
export const triggerRefresh = (payload = { universe: 'nse_1500', years: 5 }) =>
  client.post('/api/dashboard/refresh', payload, { timeout: 30000 })
export const getRefreshStatus = () => client.get('/api/dashboard/refresh-status')
export const getStaleness = () => client.get('/api/dashboard/staleness')
export const triggerEnrich = () => client.post('/api/dashboard/enrich', {}, { timeout: 30000 })
export const getEnrichProgress = () => client.get('/api/dashboard/enrich-progress')

// Stocks
export const listStocks = (skip = 0, limit = 50, search = '') =>
  client.get('/api/stocks/list', { params: { skip, limit, search } })
export const getStockDetail = (ticker: string) =>
  client.get(`/api/stocks/${ticker}/detail`)
export const getStockOHLCV = (ticker: string, days = 90) =>
  client.get(`/api/stocks/${ticker}/ohlcv`, { params: { days } })
export const screenStocks = (filters: Record<string, boolean>, skip = 0, limit = 100) =>
  client.get('/api/stocks/screener', { params: { ...filters, skip, limit } })

// Analytics - Backtesting & Signals
export const getFilterCatalog = () => client.get('/api/analytics/filters')
export const runBacktest = (payload: {
  from_date: string
  to_date: string
  forward_days: number
  win_threshold: number
  filters: Array<{ field: string; op: string; value: number }>
}) => client.post('/api/analytics/backtest', payload)
export const runWFOBacktest = (payload: {
  from_date: string
  to_date: string
  in_sample_days: number
  out_sample_days: number
  forward_days: number
  win_threshold: number
  filters: Array<{ field: string; op: string; value: number }>
  monte_carlo_runs: number
}) => client.post('/api/analytics/wfo-backtest', payload)
export const getSignalCoverage = () => client.get('/api/analytics/signal-coverage')
export const getFeatureQuality = () => client.get('/api/analytics/feature-quality')
export const getLabelDistribution = () => client.get('/api/analytics/label-distribution')

// Pipeline - Feature generation, model training, RL
export const getPipelineServiceHealth = () => client.get('/api/pipeline/service-health')
export const triggerFeatureGeneration = () => client.post('/api/pipeline/generate-features')
export const triggerModelTraining = (payload?: any) => client.post('/api/pipeline/train-model', payload)
export const getPipelineJobStatus = (jobId: string) => client.get(`/api/pipeline/status/${jobId}`)
export const getFeatureImportance = () => client.get('/api/pipeline/feature-importance')
export const getModelMetrics = () => client.get('/api/pipeline/model-metrics')
export const getShapValues = (ticker: string, features: Record<string, number>) =>
  client.post(`/api/pipeline/shap/${ticker}`, features)
export const getRLStatus = () => client.get('/api/pipeline/rl-status')
export const triggerRLTraining = (payload: any) => client.post('/api/pipeline/rl-train', payload)
export const getRLTrainingMetrics = () => client.get('/api/pipeline/rl-training-metrics')
export const getDataQuality = () => client.get('/api/pipeline/data-quality')

// Model Investigation Suite
export const getConfusionMatrix     = () => client.get('/api/pipeline/confusion-matrix')
export const getRocCurve            = () => client.get('/api/pipeline/roc-curve')
export const getScoreDistribution   = () => client.get('/api/pipeline/score-distribution')
export const getCalibration         = () => client.get('/api/pipeline/calibration')
export const getModelParams         = () => client.get('/api/pipeline/model-params')
export const getShapGlobal          = () => client.post('/api/pipeline/shap-global', {}, { timeout: 120000 })
export const getPDP                 = (feature: string) =>
  client.post('/api/pipeline/pdp', null, { params: { feature }, timeout: 60000 })
export const getFeatureStats        = () => client.get('/api/pipeline/feature-stats', { timeout: 30000 })
export const getFeatureCorrelations = () => client.get('/api/pipeline/feature-correlations', { timeout: 30000 })
export const getFeatureDistribution = (feature: string) =>
  client.get('/api/pipeline/feature-distribution', { params: { feature } })
export const triggerTrainingConfig  = (config: Record<string, any>) =>
  client.post('/api/pipeline/train-config', config)
export const getFeatureExplorer     = (params: {
  page?: number; page_size?: number; ticker?: string; sort_by?: string; sort_dir?: string
}) => client.get('/api/pipeline/features-explorer', { params })

// SSE stream base URLs — append job_id to connect
export const ML_TRAIN_STREAM_URL  = '/api/pipeline/ml-stream/'
export const RL_TRAIN_STREAM_URL  = '/api/pipeline/rl-stream/'

// Model Catalog & Registry
export const getModelCatalog        = () => client.get('/api/pipeline/model-catalog')
export const getModelRegistry       = () => client.get('/api/pipeline/model-registry')
export const activateModel          = (modelId: string) =>
  client.post(`/api/pipeline/model-registry/${modelId}/activate`)
export const deleteModel            = (modelId: string) =>
  client.delete(`/api/pipeline/model-registry/${modelId}`)

// SHAP Beeswarm & Waterfall
export const getShapBeeswarm        = (nSamples = 200, nFeatures = 15) =>
  client.post('/api/pipeline/shap-beeswarm', {}, { params: { n_samples: nSamples, n_features: nFeatures }, timeout: 120000 })
export const getShapWaterfall       = (sampleIdx = 0) =>
  client.post('/api/pipeline/shap-waterfall', {}, { params: { sample_idx: sampleIdx }, timeout: 60000 })

// Performance (future)
export const getBacktestSummary = () => client.get('/api/performance/backtest-summary')
export const getModelComparison = () => client.get('/api/performance/model-comparison')
export const getStrategyPerformance = () => client.get('/api/performance/strategy-performance')

// Positions
// Broker calls may log in to Breeze first (~11 s, up to the 30 s proxy limit): allow 30 s, not the default 10.
const BROKER = { timeout: 30000 }
export const getPositionSummary = () => client.get('/api/positions/summary', BROKER)
export const getOpenPositions = () => client.get('/api/positions/open-positions', BROKER)
export const getTradeHistory = (limit = 50) =>
  client.get('/api/positions/trade-history', { params: { limit }, ...BROKER })
export const getSectorExposure = () => client.get('/api/positions/sector-exposure', BROKER)
export const getICICIConnectionStatus = () => client.get('/api/positions/connection-status', BROKER)
export const saveICICICredentials = (payload: {
  api_key: string
  api_secret: string
  client_id?: string
  password?: string
}) => client.post('/api/positions/credentials', payload, BROKER)
export const updateSessionToken = (token: string) =>
  client.post('/api/positions/session-token', { token }, BROKER)

// Config (reads from backend .env — never hardcoded in UI)
export const getTradingConfig = () => client.get('/api/config/trading')

// Execution Engine — Phase 6 Live / Paper Trading
export const getExecutionStatus  = () => client.get('/api/execution/status')
export const getLivePositions    = () => client.get('/api/execution/positions')
export const getExecutionOrders  = (limit = 50) => client.get('/api/execution/orders', { params: { limit } })
export const setExecutionMode    = (mode: 'PAPER' | 'LIVE', confirm_live = false) =>
  client.post('/api/execution/mode', { mode, confirm_live })
export const setActiveModel      = (model: string) =>
  client.post('/api/execution/model', { model })
export const executeLiquidate    = (reason = 'Manual LIQUIDATE & HALT') =>
  client.post('/api/execution/liquidate', { reason, confirm: true })
export const rebalancePortfolio  = (
  target_weights: Record<string, number>,
  prices: Record<string, number>,
  signal_sources: Record<string, string> = {},
  dry_run = true,
) => client.post('/api/execution/rebalance', { target_weights, prices, signal_sources, dry_run })
export const placeManualOrder    = (payload: {
  symbol: string; side: 'BUY' | 'SELL'; quantity: number;
  price: number; signal_source?: string; stop_loss_price?: number;
}) => client.post('/api/execution/order', payload)
export const reconcilePositions  = (broker_positions: Record<string, any>[]) =>
  client.post('/api/execution/reconcile', { broker_positions })
export const resetEngine         = (new_equity?: number) =>
  client.post('/api/execution/reset', { new_equity, confirm: true })

// Telemetry — master controller status, logs, autopilot
export const getTelemetryStatus  = () => client.get('/api/telemetry/status')
export const getTelemetryLogs    = (limit = 100) => client.get('/api/telemetry/logs', { params: { limit } })
export const getTelemetryMetrics = () => client.get('/api/telemetry/metrics')
export const getAutopilot        = () => client.get('/api/telemetry/autopilot')
export const setAutopilot        = (enabled: boolean) =>
  client.post('/api/telemetry/autopilot', { enabled })

// Larry Williams Scanner & Screener
export const getLWScreener      = (days = 500) => client.get('/api/lw/screener', { params: { days }, timeout: 60000 })
export const getLWScanResults   = (topN = 50)  => client.get('/api/lw/scan-results', { params: { top_n: topN } })
export const triggerLWScan      = (nStocks = 200) => client.post('/api/lw/run-cycle-scan', null, { params: { n_stocks: nStocks } })
export const getLWScanJob       = (jobId: string)  => client.get(`/api/lw/job/${jobId}`)
export const getLWOHLCV         = (ticker: string, days = 120) => client.get(`/api/lw/ohlcv/${ticker}`, { params: { days } })

// ── Data-Service Proxy (all via /api/data/* → ui-api → data-service:8001) ─────

// Health & provider
export const getDataServiceHealth    = () => client.get('/api/data/health', { timeout: 8000 })
export const getDataServiceReady     = () => client.get('/api/data/ready',  { timeout: 8000 })
export const getDataProviderStatus   = () => client.get('/api/data/provider/status', { timeout: 8000 })
export const configureDataProvider   = (payload: {
  api_key?: string; api_secret?: string; session_token?: string
}) => client.post('/api/data/provider/configure', payload, { timeout: 30000 })

// Historical / batch fetch
export const fetchHistorical = (payload: { tickers: string[]; years?: number }) =>
  client.post('/api/data/fetch/historical', payload, { timeout: 300000 })

export const fetchRefreshSingle = (payload: { ticker: string; start_date?: string }) =>
  client.post('/api/data/fetch/refresh', payload, { timeout: 60000 })

export const fetchRefreshBatch = (payload: { tickers: string[]; years?: number }) =>
  client.post('/api/data/fetch/refresh-batch', payload, { timeout: 300000 })

// fetchICICIDaily removed: daily history is Yahoo-only (data-service returns 410 Gone).

export const fetchFundamentals = (payload: { tickers: string[] }) =>
  client.post('/api/data/fetch/fundamentals', payload, { timeout: 300000 })

// OHLCV & live quotes
export const getDataOHLCV = (ticker: string, start?: string, end?: string) =>
  client.get(`/api/data/ohlcv/${ticker}`, { params: { start, end }, timeout: 30000 })

export const getDataLiveQuote     = (ticker: string) =>
  client.get(`/api/data/live/quote/${ticker}`, { timeout: 8000 })

export const getDataLiveNifty     = () =>
  client.get('/api/data/live/index/nifty', { timeout: 8000 })

export const getDataIntraday = (ticker: string, interval = '5minute', day?: string) =>
  client.get(`/api/data/live/intraday/${ticker}`, { params: { interval, ...(day ? { day } : {}) }, timeout: 30000 })

// Refresh only the selected/watchlist tickers (scoped — skips the full universe)
export const refreshWatchlist = (tickers: string[], years = 5) =>
  client.post('/api/dashboard/refresh', { tickers, years }, { timeout: 30000 })

// ── Data Warehouse introspection (DuckDB stats via data-service) ─────────────────

export const getWarehouseStats     = () =>
  client.get('/api/data/db/stats', { timeout: 30000 })

export const getWarehouseOhlcvMeta = () =>
  client.get('/api/data/db/ohlcv-meta', { timeout: 90000 })

export const getWarehouseMlStats   = () =>
  client.get('/api/data/db/ml-stats', { timeout: 30000 })

// ── Monitor REST endpoints ─────────────────────────────────────────────────────

export const monitorSubscribe   = (symbol: string) =>
  client.post('/api/monitor/subscribe',   { symbol }, { timeout: 5000 })

export const monitorUnsubscribe = (symbol: string) =>
  client.post('/api/monitor/unsubscribe', { symbol }, { timeout: 5000 })

export const monitorList        = () =>
  client.get('/api/monitor/list', { timeout: 5000 })

export const monitorLiveNifty   = () =>
  client.get('/api/monitor/live/nifty', { timeout: 8000 })

// WebSocket URL constant (resolved at runtime in components/hooks)
export const MONITOR_WS_PATH = '/api/monitor/ws/monitor'

// ── Alpha Discovery Desk (novel_alpha_engine via /api/alpha/*) ───────────────────

export interface AlphaParamSpec {
  default: number | boolean
  min: number | null
  max: number | null
  step: number | null
  type: 'float' | 'int' | 'bool' | string
  label: string
}

export interface AlphaStrategyMeta {
  name: string
  params: Record<string, AlphaParamSpec>
  knobs: Record<string, AlphaParamSpec>
  flags: Record<string, AlphaParamSpec>
}

export interface AlphaStrategiesResponse {
  mode: string
  default: string | null
  strategies: Record<string, AlphaStrategyMeta>
}

export interface AlphaScanResult {
  ticker: string
  date: string
  last_close: number | null
  entry_adj?: number | null
  exit_adj?: number | null
  fwd5?: number | null
  net5?: number | null
}

export interface AlphaScanResponse {
  mode: string
  strategy_id: string
  strategy_name: string
  params: Record<string, number | boolean>
  universe: { total: number; eligible: number; rows_scanned: number }
  as_of: string
  n_signals_total: number
  n_signals_window: number
  tickers: string[]
  results: AlphaScanResult[]
  edge: {
    n_with_forward: number
    mean_net5_bps: number
    median_net5_bps: number
    win_rate: number
  } | null
  latency: { sql_s: number; signal_s: number; total_s: number }
}

export const getAlphaMode        = () => client.get('/api/alpha/mode', { timeout: 8000 })
export const getAlphaStrategies  = () =>
  client.get<AlphaStrategiesResponse>('/api/alpha/strategies', { timeout: 30000 })
export const getAlphaUniverse    = (days = 400) =>
  client.get('/api/alpha/universe', { params: { days }, timeout: 120000 })
export const getAlphaValidated   = () => client.get('/api/alpha/validated', { timeout: 15000 })
export const runAlphaScan = (payload: {
  strategy_id: string
  params: Record<string, number | boolean>
  days?: number
  mode?: 'latest' | 'recent' | 'all'
  recent_days?: number
  max_results?: number
  include_diagnostics?: boolean
}) => client.post<AlphaScanResponse>('/api/alpha/scan', payload, { timeout: 180000 })

// ── Commodity Desk (global futures + EIA/FRED fundamentals via /api/commodity/*) ──

export interface CommodityQuote {
  symbol: string
  label: string
  category: string
  unit: string
  currency: string
  price: number | null
  prev_close: number | null
  change: number | null
  change_pct: number | null
  spark: number[]
  as_of: number | null
  stale: boolean
}

export interface CommodityFundamentalPoint { date: string; value: number }

export interface CommodityFundamentalSeries {
  id: string
  label: string
  unit: string
  latest?: CommodityFundamentalPoint | null
  points: CommodityFundamentalPoint[]
  error?: string
}

export interface CommodityFundamentalsLeg {
  available: boolean
  reason?: string
  series: CommodityFundamentalSeries[]
}

export interface CommodityOverview {
  as_of: number
  futures: CommodityQuote[]
  fundamentals: { fred: CommodityFundamentalsLeg; eia: CommodityFundamentalsLeg }
  sources: { price: string; eia: boolean; fred: boolean }
  note: string
}

export interface CommodityCandle { t: number; o: number | null; h: number | null; l: number | null; c: number | null }

export interface CommodityHistory {
  symbol: string
  label: string
  unit: string
  currency: string
  range: string
  interval: string
  candles: CommodityCandle[]
}

export const getCommodityOverview = () =>
  client.get<CommodityOverview>('/api/commodity/overview', { timeout: 20000 })
export const getCommodityHistory = (symbol: string, range = '6mo', interval = '1d') =>
  client.get<CommodityHistory>(`/api/commodity/price/${symbol}`, { params: { range, interval }, timeout: 20000 })
export const getCommodityHealth = () =>
  client.get('/api/commodity/health', { timeout: 8000 })

// ── Gold Pre-Open desk (/api/commodity/gold-preopen) ──
export interface GoldLeg { symbol: string; now: number; ref: number | null; ref_how: string; as_of: string | null }
export interface GoldContextRow {
  key: string; label: string; symbol: string; unit?: string; value: number | null; at_close?: number | null
  change?: number | null; signal?: 'supportive' | 'headwind' | null; trigger?: number; trigger_state?: 'above' | 'below'
  note?: string
}
export interface GoldHeadline { topic: string; title: string; publisher: string; link: string; published_at: string }
export interface GoldVerdict {
  state: 'OK' | 'WAIT' | 'AWAITING_OPEN' | 'NEED_PRICE' | 'NO_MODEL'; title: string; detail: string; diff?: number
}
export interface GoldPreOpen {
  as_of: string
  contract: { name: string; expiry: string; comex: string; band_low: number | null; band_high: number | null
              band_pct: number | null; open_interest_lots: number | null }
  baseline: { value: number | null; source: string | null; session: string; close_time: string; settlement_from_band: number | null }
  mcx_price: { value: number | null; source: string | null; broker: Record<string, unknown> | null }
  model: {
    comex?: GoldLeg; inr?: GoldLeg; fair_open?: number; gap?: number; gap_pct?: number; comex_part?: number
    inr_part?: number; rs_per_comex_dollar?: number; rs_per_inr_rupee?: number; implied_premium_pct?: number
    lot_pnl_per_rupee?: number; threshold_in_comex_dollars?: number
  }
  threshold: number
  verdict: GoldVerdict
  event_risk: { flagged_headlines: number; advice: string | null }
  context: GoldContextRow[]
  headlines: GoldHeadline[]
  manual_checks: { name: string; what: string; url: string }[]
  notes: string[]
}
export const getGoldPreOpen = (params: { baseline?: number; mcx_price?: number; threshold?: number; eurusd_trigger?: number }) =>
  client.get<GoldPreOpen>('/api/commodity/gold-preopen', { params, timeout: 30000 })

// ── News Catalyst Terminal (/api/news-scanner → new_scnner/YYYYMMDD.json + Yahoo) ──
export const getNewsScans     = () => client.get('/api/news-scanner/scans', { timeout: 15000 })
export const getNewsScan      = (date = 'latest') => client.get('/api/news-scanner/scan', { params: { date }, timeout: 15000 })
export const getNewsQuotes    = (symbols: string[]) =>
  client.get('/api/news-scanner/quotes', { params: { symbols: symbols.join(',') }, timeout: 30000 })
export const getNewsChart     = (symbol: string, range = '1y') =>
  client.get(`/api/news-scanner/chart/${encodeURIComponent(symbol)}`, { params: { range }, timeout: 30000 })
export const getNewsHeadlines = (symbol: string, name?: string, region = 'US', count = 15) =>
  client.get(`/api/news-scanner/headlines/${encodeURIComponent(symbol)}`, { params: { count, name, region }, timeout: 30000 })

export default client

// Decision Desk (paper trading of the approved monthly momentum strategy)
export const getDeskStatus  = () => client.get('/api/desk/status', { timeout: 30000 })
export const getDeskPreview = () => client.get('/api/desk/preview', { timeout: 300000 })
export const reenableDesk   = () => client.post('/api/desk/reenable', {}, { timeout: 30000 })

// ── Market Monitor (/api/market/monitor ← data-service /db/market-monitor) ──
export interface MarketMover {
  symbol: string; industry: string; close: number | null; chg_pct: number | null; turnover_cr: number | null
  vol_x: number | null; from_52w_high_pct: number | null
}
export interface MarketSector {
  industry: string; stocks: number; ret_1d_pct: number | null; ret_5d_pct: number | null
  ret_21d_pct: number | null; ret_63d_pct: number | null; pct_above50: number | null
}
export interface MarketMonitor {
  as_of: string
  index_name: string
  regime: { score: number; exposure: string; setups: string; changed_from: number; days_at_score: number
            components: { key: string; label: string; ok: boolean; detail: string }[] }
  breadth: Record<string, number | null>
  history: { date: string; score: number; pct_above50: number | null; pct_above200: number | null; ad_line: number
             nh_nl: number; index: number | null; mm_ratio10: number | null }[]
  sectors: MarketSector[]
  movers: Record<'gainers' | 'losers' | 'most_active' | 'volume_shockers' | 'new_highs' | 'new_lows', MarketMover[]>
  map?: { symbol: string; industry: string; size: number | null; r1: number | null; r5: number | null; r21: number | null }[]
  rotation?: { industry: string; stocks: number; quadrant: string; tail: { date: string; x: number | null; y: number | null }[] }[]
}
export const getMarketMonitor = () => client.get<MarketMonitor>('/api/market/monitor', { timeout: 30000 })

// Command bar symbol directory (local universe CSV, no DB hit)
export interface SymbolEntry { t: string; n: string; s: string | null; c: string | null }
export const getSymbols = () => client.get<{ data: SymbolEntry[] }>('/api/stocks/symbols')

// Research library (RSCH): study reports with curated verdicts
export interface ResearchEntry {
  id: string; title: string; area: string; verdict: string; takeaway: string; updated: string; lines: number
  data_files: { name: string; kb: number }[]
}
export const listResearch = () => client.get<{ data: ResearchEntry[] }>('/api/research')
export const getResearchDoc = (id: string) =>
  client.get<ResearchEntry & { markdown: string }>('/api/research/doc', { params: { id } })
export const researchFileUrl = (id: string, name: string) =>
  `/api/research/file?id=${encodeURIComponent(id)}&name=${encodeURIComponent(name)}`

// W7 S6: columnar core payloads ({columns, data}) → row objects, so components keep their shapes
export function fromColumnar<T>(columns: string[], data: unknown[][]): T[] {
  return data.map(row => {
    const o: Record<string, unknown> = {}
    columns.forEach((c, i) => { o[c] = row[i] })
    return o as T
  })
}

// Corporate calendar (EVTS): NSE event calendar + board meetings + corporate actions
export interface CorpEvent {
  symbol: string; event_date: string; kind: string; source: string; sources?: string[]; tags: string | null
  company: string | null; purpose: string | null; detail: string | null; record_date: string | null
  announced_at?: string | null; url: string | null; first_seen?: string | null
  turnover_cr: number | null; close: number | null
  typical_move_pct?: number; typical_quarters?: number   // RESULTS only: average |move| on recent results
}
export const getMarketEvents = (start?: string, end?: string) =>
  client.get<{ start: string; end: string; columns: string[]; data: unknown[][]; count: number; refreshing: boolean }>(
    '/api/market/events', { params: { start, end, fields: 'core' }, timeout: 30000 })
    .then(r => ({
      ...r,
      data: {
        start: r.data.start, end: r.data.end, count: r.data.count, refreshing: r.data.refreshing,
        // the core wire nulls `purpose` where it duplicated `detail` — restore it exactly
        rows: fromColumnar<CorpEvent>(r.data.columns, r.data.data).map(e => ({ ...e, purpose: e.purpose ?? e.detail ?? null })),
      },
    }))
export const getNewsTrackRecord = () => client.get('/api/news-scanner/track-record', { timeout: 15000 })

// Gold desk accuracy log (fair open at 08:45 vs actual MCX open)
export interface GoldLogRow {
  date: string; snapshot_at?: string; contract?: string; baseline?: number; baseline_source?: string; fair_open?: number
  actual_open?: number; actual_source?: string; error?: number; naive_error?: number; event_risk?: number
}
export interface GoldLogStats {
  days: number; mean_abs_error?: number; median_abs_error?: number; bias?: number; within_threshold_pct?: number
  naive_mean_abs_error?: number | null; p90_abs_error?: number; threshold?: number
}
export const getGoldLog = (threshold = 300) =>
  client.get<{ rows: GoldLogRow[]; stats: GoldLogStats }>('/api/commodity/gold-preopen/log', { params: { threshold } })
export const setGoldActual = (date: string, open: number) =>
  client.post<GoldLogRow>('/api/commodity/gold-preopen/actual', { date, open })

// Stock profile (DES): /api/stocks/{ticker}/profile ← data-service /db/security/{symbol}
export interface OwnershipQuarter {
  period_end: string; promoter_pct: number | null; fpi_pct: number | null; mf_pct: number | null
  retail_pct: number | null; total_holders: number | null; retail_holders: number | null
}
export interface StockProfile {
  symbol: string; found: boolean; industry: string | null
  price: {
    date: string; close: number | null; series: string | null; chg_pct: number | null
    returns: Record<'1W' | '1M' | '3M' | '6M' | '1Y', number | null>
    high_52w: number | null; low_52w: number | null; from_high_pct: number | null; from_low_pct: number | null
    atr_pct: number | null; above: Record<string, boolean | null>; sma: Record<string, number | null>
    turnover_cr: number | null; turnover_cr_20d: number | null; volume_x50: number | null
    deliv_pct: number | null; deliv_pct_20d: number | null; sessions: number
  } | null
  corporate_actions: { date: string; k: number; source: string }[]
  ownership: {
    quarters: OwnershipQuarter[]; window: string; holders_change_pct: number | null
    change_over_window: Record<'promoter_pct' | 'fpi_pct' | 'mf_pct' | 'retail_pct', number | null>
  } | null
  insiders: { rows: { intimation_date: string; person: string | null; category: string | null; txn_type: string | null
                      mode: string | null; qty: number | null; value: number | null }[]
              net_market_buy_cr: number | null; buyers: number; sellers: number }
  deals: { rows: { date: string; kind: string; client_name: string | null; side: string | null; qty: number | null
                   price: number | null; value_cr: number | null }[]; net_value_cr: number | null
           short: { days: number; qty: number } }
  derivatives: { date: string; near_expiry: string | null; fut_close: number | null; basis_pct: number | null
                 fut_oi: number | null; fut_oi_chg_20d_pct: number | null; pcr_oi: number | null } | null
  margin_funding: { date: string; amount_cr: number | null; qty: number | null; qty_chg_20d_pct: number | null } | null
  events: { event_date: string; kind: string; tags: string | null; purpose: string | null; detail: string | null
            source: string; url: string | null }[]
}
export const getStockProfile = (ticker: string) =>
  client.get<StockProfile>(`/api/stocks/${encodeURIComponent(ticker)}/profile`, { timeout: 30000 })
export interface ResultReaction {
  period_end: string; released_at: string; timing: 'pre-open' | 'market hours' | 'after close'; reaction_date: string
  move_pct: number; gap_pct: number; vs_nifty_pct: number | null
}
export interface ResultsSummary {
  quarters: number; avg_abs_move_pct?: number; median_abs_move_pct?: number; up_pct?: number
  biggest_up_pct?: number; biggest_down_pct?: number; avg_abs_vs_nifty_pct?: number | null
}
export const getStockResults = (ticker: string) =>
  client.get<{ symbol: string; reactions: ResultReaction[]; summary: ResultsSummary }>(
    `/api/stocks/${encodeURIComponent(ticker)}/results`, { timeout: 45000 })

export interface CorpAction { ex_date: string; kind: 'dividend' | 'bonus' | 'split' | 'buyback' | 'rights' | 'other'; subject: string; rs_per_share: number | null; special: boolean }
export interface StockActions { symbol: string; years: number; items: CorpAction[]; ttm_dividend: number | null; ttm_reshaped: boolean
  by_fy: Record<string, number>; price: number | null; ttm_yield_pct: number | null }
// HP: daily price history as traded, with delivery % (NSE bhavcopy)
export interface HistoryRow { date: string; open: number | null; high: number | null; low: number | null; close: number | null; vwap: number | null
  change_pct: number | null; volume: number; value_cr: number | null; trades: number | null; deliv_pct: number | null; series: string | null; action_k: number | null }
export interface StockHistory { symbol: string; found: boolean; rows: HistoryRow[]; actions: { date: string; k: number }[]
  summary: { from: string; to: string; sessions: number; return_pct: number | null; high: number | null; low: number | null
    avg_value_cr: number | null; avg_deliv_pct: number | null; up_days: number; down_days: number
    max_dd_pct: number | null; dd_peak: string | null; dd_trough: string | null; dd_now_pct: number | null } | null }
export const getStockHistory = (ticker: string, days = 90) =>
  client.get<StockHistory>(`/api/stocks/${encodeURIComponent(ticker)}/history`, { params: { days } })

export const getStockActions = (ticker: string, years = 5) =>
  client.get<StockActions>(`/api/stocks/${encodeURIComponent(ticker)}/actions`, { params: { years }, timeout: 30000 })
export interface PeHistory { symbol: string; points: { date: string; pe: number }[]; now?: number; median?: number; p25?: number; p75?: number
  low?: number; high?: number; percentile?: number; since?: string }
export const getStockPeHistory = (ticker: string) =>
  client.get<PeHistory>(`/api/stocks/${encodeURIComponent(ticker)}/pe-history`, { timeout: 30000 })
export const getStockFilings = (ticker: string, days = 30) =>
  client.get<{ symbol: string; days: number; items: Filing[] }>(`/api/stocks/${encodeURIComponent(ticker)}/filings`, { params: { days }, timeout: 30000 })

// Quarterly financials (FA) from NSE results XBRL
export interface FinQuarter {
  period_end: string; period_start: string; consolidated: boolean; bank: boolean; filed_at: string; xbrl: string
  revenue: number | null; other_income: number | null; total_income: number | null; expenses: number | null
  pbt: number | null; pat: number | null; eps: number | null; nii?: number | null
  revenue_yoy: number | null; revenue_qoq: number | null; pat_yoy: number | null; pat_qoq: number | null; pat_margin: number | null
  pat_yoy_turn?: string | null; pat_qoq_turn?: string | null
  scale_fixed?: number        // the filer reported this quarter 100× too small (+100) or too large (−100); corrected
}
export interface Valuation {
  price?: number; shares?: number | null; mcap?: number | null; ttm_profit?: number | null; pe?: number | null
  book_equity?: number | null; book_as_of?: string | null; pb?: number | null
}
export const getStockFinancials = (ticker: string) =>
  client.get<{ symbol: string; quarters: FinQuarter[]; fetched_at: string | null; basis: string; valuation?: Valuation }>(
    `/api/stocks/${encodeURIComponent(ticker)}/financials`, { timeout: 60000 })

export interface FinLatest {
  period_end: string; filed_at: string; revenue: number | null; pat: number | null; revenue_yoy: number | null; pat_yoy: number | null
  pat_yoy_turn?: string | null; pat_margin: number | null; bank: boolean; consolidated: boolean; mcap: number | null; pe: number | null; pb: number | null
  pe_pctl?: number | null; pe_median_hist?: number | null
}
export const getFinancialsLatest = (symbols: string[]) =>
  client.get<{ latest: Record<string, FinLatest> }>('/api/market/financials-latest', { params: { symbols: symbols.join(',') } })
export const prefetchFinancials = (symbols: string[]) =>
  client.post<{ queued: number }>('/api/market/financials/prefetch', null, { params: { symbols: symbols.join(',') } })

export interface ScreenRow extends FinLatest { symbol: string; industry: string | null }
export const getFundamentalsScreen = () =>
  client.get<{ columns: string[]; data: unknown[][]; count: number }>(
    '/api/market/fundamentals-screen', { params: { fields: 'core' }, timeout: 30000 })
    .then(r => ({ ...r, data: { rows: fromColumnar<ScreenRow>(r.data.columns, r.data.data), count: r.data.count } }))

// Trade ticket: shared/trading_costs.py via /api/costs/ticket
export interface CostLegs { trade_value: number; brokerage: number; stt: number; stamp: number; exchange: number; sebi: number; ipft: number; dp: number; gst: number; total: number }
export interface TradeTicket {
  profile: string; price: number; shares: number; notional: number; round_trip: CostLegs; round_trip_pct: number | null
  breakeven_move_pct: number | null; intraday_round_trip: CostLegs; min_position_for_1pct: number | null
  stop?: { atr_multiple: number; price: number; distance_pct: number; loss_if_hit: number; loss_pct_of_capital: number | null }
  tax_on_10pct_gain: { gain: number; short_term: number; long_term_with_exemption: number; rules: string }
}
export const getTradeTicket = (p: { value: number; price: number; atr_pct?: number | null; stop_atr?: number; capital?: number }) =>
  client.get<TradeTicket>('/api/costs/ticket', { params: { ...p, atr_pct: p.atr_pct ?? undefined } })

export interface CrashFilter {
  date: string; nifty: number; sma200: number; risk_on: boolean; gap_pct: number; move_needed_pct: number
  sessions_below: number; next_signal_date: string
}
export const getCrashFilter = () => client.get<CrashFilter>('/api/market/crash-filter')
export const getArchiveMeta = () =>
  client.get<Record<string, { first: string | null; last: string | null; rows: number }>>('/api/data/db/archive-meta', { timeout: 30000 })
export const getNseDatasetsMeta = () =>
  client.get<Record<string, { first: string | null; last: string | null; rows: number }>>('/api/data/db/nse-positions-meta', { timeout: 30000 })

export interface RecentResult {
  symbol: string; period_end: string; released_at: string; timing: string; turnover_cr: number
  reaction_date: string | null; move_pct: number | null; vs_nifty_pct: number | null; typical_move_pct: number | null
  sessions_since?: number | null; avoid?: boolean     // ≤ −5% vs NIFTY within 60 sessions (reports/results_drift H2)
}
export const getRecentResults = (days = 10) =>
  client.get<{ days: number; rows: RecentResult[]; count: number }>('/api/market/results-recent', { params: { days } })

export const getIndicesLive = (names = ['NIFTY 50', 'NIFTY BANK', 'INDIA VIX']) =>
  client.get<{ indices: Record<string, { last: number | null; change?: number | null; change_pct: number | null; previous_close?: number | null; time?: string }>; timestamp?: string }>(
    '/api/market/indices-live', { params: { names: names.join(',') } })

export interface IndexContribution {
  index: string; last: number | null; change: number | null; change_pct: number | null; explained_points: number; time?: string
  members: { symbol: string; change_pct: number; weight_pct: number | null; points: number | null; promoter_pct: number | null }[]; missing: string[]
}
export const getIndexContribution = (index = 'NIFTY 50') =>
  client.get<IndexContribution>('/api/market/index-contribution', { params: { index } })

export interface IndexValuationRow { last: number | null; change_pct: number | null; pe: number | null; pb: number | null; dy: number | null; chg_30d: number | null; chg_365d: number | null }
export const getIndexValuation = () =>
  client.get<{ timestamp: string; indices: Record<string, IndexValuationRow>; history_days: number
    vs_history?: Record<string, { pctl: number; median: number; p25: number; p75: number; low: number; high: number; p05: number; p95: number; since: string; days: number }>; pe_basis_from?: string
    rel_history?: Record<string, { ratio: number; pctl: number; median: number; p25: number; p75: number }> }>('/api/market/index-valuation')

export interface IndexValuationHistory {
  index: string; metric: 'pe' | 'pb' | 'dy' | 'rel'; points: { date: string; v: number }[]; basis_from: string | null
  stats: { now: number; pctl: number; median: number; p25: number; p75: number; low: number; high: number; p05: number; p95: number; since: string; asof: string; days: number } | null
}
export const getIndexValuationHistory = (index = 'NIFTY 50', metric: 'pe' | 'pb' | 'dy' | 'rel' = 'pe') =>
  client.get<IndexValuationHistory>('/api/market/index-valuation-history', { params: { index, metric } })

// Institutional short selling (NSE daily disclosure) per stock over a window
export interface ShortRow { symbol: string; short_qty: number; days: number; last: string; window_volume: number | null; short_pct_of_volume: number | null; move_pct: number | null }
export const getShortSelling = (days = 20) =>
  client.get<{ days: number; from: string; rows: ShortRow[]; count: number; data_through: string | null }>('/api/market/short-selling', { params: { days }, timeout: 60000 })

// Daily index closes (relative-strength charts)
export const getIndexDaily = (symbol = 'NIFTY50', days = 1500) =>
  client.get<{ symbol: string; rows: { date: string; close: number }[] }>('/api/market/index-daily', { params: { symbol, days } })

// NSE surveillance / risk flags (ASM, GSM, ESM, IRP, tight bands, trade-to-trade, F&O ban)
export interface RiskChip { code: string; level: 'high' | 'medium' | 'low'; why: string }
export interface RiskFlags { symbol: string; band: number | null; series: string | null; chips: RiskChip[] }
export const getSurveillance = (symbols: string[], allFlagged = false) =>
  client.get<{ flags: Record<string, RiskFlags>; ban: string[]; dates: Record<string, string | null>; counts: Record<string, number>
    flagged?: Record<string, string[]> }>(
    '/api/market/surveillance', { params: { symbols: symbols.join(','), ...(allFlagged ? { all_flagged: true } : {}) }, timeout: 60000 })

// MEMB: index members with weights, returns, valuation (not getIndexMembers: that is MOV's live drill-down)
export interface IndexMembRow { symbol: string; change_pct: number | null; promoter_pct: number | null; weight_pct: number | null; points: number | null
  ret_1m: number | null; ret_3m: number | null; ret_ytd: number | null; ret_1y: number | null; from_high_pct: number | null; close: number | null
  pe: number | null; mcap: number | null; pat_yoy: number | null; pat_turn: string | null; revenue_yoy: number | null; quarter: string | null
  ytd_contrib_pp: number | null; pe_pctl?: number | null }
export interface IndexMemb extends Omit<IndexContribution, 'members'> { members: IndexMembRow[]
  summary: { members: number; up: number; down: number; top5_weight_pct: number; implied_pe: number | null; pe_coverage_pct: number; near_high: number
    ytd_explained_pct: number; index_ytd_pct: number | null } }
export const getIndexMemb = (index = 'NIFTY 50') => client.get<IndexMemb>('/api/market/index-memb', { params: { index }, timeout: 60000 })

// Options into results: priced results-day move vs the stock's usual reaction (F&O names reporting soon)
export interface ImpliedMoveRow { symbol: string; results_date: string; expiry: string | null; trading_days: number; atm_iv: number | null
  expected_move_pct: number | null; daily_vol_pct: number | null; event_sigma_pct: number | null; event_abs_move_pct: number | null
  typical_move_pct: number | null; quarters: number | null; ratio: number | null; method?: "term" | "realised" | null; normal_daily_pct?: number | null }
export const getResultsImpliedMoves = (days = 10) =>
  client.get<{ rows: ImpliedMoveRow[]; fo_date: string | null; days: number }>('/api/market/results-implied-moves', { params: { days }, timeout: 60000 })

// Equity vs bonds: NIFTY earnings yield − India 10Y (monthly; the bond yield is ~3 months late)
export interface YieldGap { points: { month: string; ey: number; y10: number; gap: number }[]; basis_from: string; bond_through?: string | null
  stats: { month: string; gap: number; pctl: number; median: number; p25: number; p75: number; months: number } | null }
export const getYieldGap = () => client.get<YieldGap>('/api/market/yield-gap', { timeout: 45000 })

// SEAG: seasonality by calendar month
export interface SeasonMonth { month: string; n: number; avg: number | null; median: number | null; pct_up: number | null; best: number | null; worst: number | null }
export interface Seasonality { symbol: string; kind: 'index' | 'stock'; years: number; from: string | null; to: string | null
  grid: { year: number; months: Record<string, number | null>; year_ret: number | null }[]; months: SeasonMonth[]
  current: { month: string; year: number; ret: number; asof: string } | null }
export const getSeasonality = (symbol = 'NIFTY 50') => client.get<Seasonality>('/api/market/seasonality', { params: { symbol } })

// Intraday index path (NSE chart feed, latest session)
export interface IndexBar { ts: number; date: string; open: number; high: number; low: number; close: number }
export interface IndexIntraday { index: string; minutes: number; day: string | null; previous_close: number | null; rows: IndexBar[] }
export const getIndexIntraday = (index = 'NIFTY 50', minutes = 1) =>
  client.get<IndexIntraday>('/api/market/index-intraday', { params: { index, minutes } })

// Market internals through the session (breadth + segment moves, sampled every 2 min)
export interface InternalsSample {
  nse_ts: string; nifty: number | null; n50_pct: number | null; n500_pct: number | null; mid_pct: number | null
  small_pct: number | null; bank_pct: number | null; n500_adv: number | null; n500_dec: number | null; all_adv: number | null; all_dec: number | null
}
export interface MarketInternals {
  day: string; rows: InternalsSample[]
  summary: { samples: number; first?: string; last?: string; n500_adv?: number | null; n500_dec?: number | null; ad_ratio?: number | null
             net_now?: number | null; net_best?: number | null; net_worst?: number | null; divergence?: string | null; small_minus_n50?: number | null }
}
export const getMarketInternals = (day?: string) =>
  client.get<MarketInternals>('/api/market/internals', { params: day ? { day } : {} })

// Results filed since the last close, with today's live move vs the stock's typical results-day move
export interface ReactingResult { symbol: string; filed_at: string; change_pct: number | null; vs_nifty_pct: number | null; typical_move_pct: number | null; vs_typical: number | null
  revenue_yoy?: number | null; pat_yoy?: number | null; pat_turn?: string | null; quarter?: string | null; reacts_next_session?: boolean; numbers?: 'ok' | 'not_on_feed' | 'pending' }
export const getResultsReacting = () =>
  client.get<{ rows: ReactingResult[]; since: string; as_of?: string; nifty_change_pct?: number | null; phase?: 'session' | 'preopen' | 'closed' }>('/api/market/results-reacting', { timeout: 45000 })

// Option monitor (OMON): EOD chain from NSE's F&O bhavcopy
export interface OptionSide { price: number | null; oi: number | null; oi_chg: number | null; volume: number | null; iv: number | null }
export interface OptionChain {
  symbol: string; date: string; expiry: string; expiries: string[]; days_to_expiry: number
  spot: number | null; future: number | null; forward: number | null; forward_source: string
  atm: number; lot: number | null; atm_iv: number | null; expected_move_pct: number | null
  pcr_oi: number | null; max_pain: number | null; call_oi_total: number; put_oi_total: number
  resistance: number[]; support: number[]; rows: { strike: number; ce: OptionSide; pe: OptionSide }[]; underlyings?: string[]
  live?: boolean; as_of?: string | null
}
export const getOptionChain = (symbol: string, expiry?: string) =>
  client.get<OptionChain>(`/api/market/option-chain/${encodeURIComponent(symbol)}`, { params: { expiry }, timeout: 30000 })
export const getOptionChainLive = (symbol: string, expiry?: string) =>
  client.get<OptionChain>(`/api/market/option-chain-live/${encodeURIComponent(symbol)}`, { params: { expiry }, timeout: 40000 })

// Index F&O positioning by participant (FII / DII / Pro / Client)
export interface ParticipantRow {
  client_type: string; fut_long: number; fut_short: number; fut_net: number; fut_long_pct: number
  fut_net_chg_1d: number | null; fut_net_chg_5d: number | null; opt_net_bull: number
}
export const getParticipants = (days = 250) =>
  client.get<{ date: string; snapshot: ParticipantRow[]; fii_history: { date: string; long_pct: number; net: number }[] }>(
    '/api/market/participants', { params: { days } })
export interface OptionHistoryRow { date: string; spot: number | null; atm_iv: number | null; pcr: number | null; max_pain: number | null; expiry: string }
export const getOptionHistory = (symbol: string, days = 260) =>
  client.get<{ symbol: string; rows: OptionHistoryRow[]; updating: boolean }>(`/api/market/option-history/${encodeURIComponent(symbol)}`, { params: { days } })
export interface Headline { topic: string; title: string; publisher: string; link: string; published_at: string }
export const getMarketHeadlines = () => client.get<{ headlines: Headline[] }>('/api/market/headlines', { timeout: 20000 })

// Insider monitor (INSD): promoter / director / KMP open-market buys
export interface InsiderBuy {
  symbol: string; last_date: string; first_date: string; total_value: number; trades: number; buyers: number
  categories: string | null; top_buyer: string | null; filing_close: number | null; last_close: number | null
  last_px_date: string | null; since_filing_pct: number | null
}
export const getInsiderBuys = (days = 60, min_value = 1e6) =>
  client.get<{ days: number; min_value: number; rows: InsiderBuy[]; count: number; data_through: string | null }>(
    '/api/market/insider-buys', { params: { days, min_value } })

// Deals monitor (DEAL): market-wide bulk / block deals, netted per client per stock per day
export interface Deal {
  date: string; kind: 'bulk' | 'block'; symbol: string; security_name: string | null; client_name: string | null
  direction: 'buy' | 'sell'; institution: boolean; qty: number; avg_price: number; value: number
  pct_of_volume: number | null; deal_close: number | null; last_close: number | null; last_date: string | null; since_pct: number | null
}
export interface DealsSummary { deals: number; buy_value: number; sell_value: number; institution_value: number; top_net: { symbol: string; net_value: number }[] }
export const getDeals = (days = 10, min_value = 1e7, kind: 'all' | 'bulk' | 'block' = 'all') =>
  client.get<{ days: number; min_value: number; kind: string; rows: Deal[]; count: number; summary: DealsSummary; data_through: string | null }>(
    '/api/market/deals', { params: { days, min_value, kind } })

// Pre-open monitor (PRE): NSE call auction 09:00–09:08
export interface PreOpenRow {
  symbol: string; series: string | null; iep: number | null; prev_close: number | null; change: number | null; change_pct: number | null
  final_qty: number | null; value: number | null; buy_qty: number | null; sell_qty: number | null; imbalance: number | null
  ato_buy: number | null; ato_sell: number | null; year_high: number | null; year_low: number | null; vs_year_high_pct: number | null
  market_cap: number | null; purpose: string | null
}
export interface PreOpen {
  key: string; timestamp: string | null; advances: number | null; declines: number | null; unchanged: number | null
  total_value: number | null; rows: PreOpenRow[]; fetched_at: string
}
export const getPreOpen = (key: 'FO' | 'NIFTY' | 'BANKNIFTY' | 'ALL' = 'FO') =>
  client.get<PreOpen>('/api/market/preopen', { params: { key }, timeout: 30000 })

// FII / DII cash-market flows (₹ cr), collected daily from NSE since 12 Oct 2026
export interface FiiDiiCash {
  rows: { date: string; category: 'FII' | 'DII'; buy_cr: number | null; sell_cr: number | null; net_cr: number | null }[]
  summary: { latest_date: string | null; latest: Record<string, number>; sum_5d: Record<string, number>; mtd: Record<string, number>
             sessions: number; sessions_5d?: number; sessions_mtd?: number }
  error: string | null
}
export const getFiiDiiCash = (days = 90) => client.get<FiiDiiCash>('/api/market/fii-dii-cash', { params: { days } })

// IPO monitor (IPO): open / forthcoming issues and the listing scorecard
export interface IpoBids { qib: number | null; nii: number | null; retail: number | null; employee?: number | null; total: number | null }
export interface IpoIssue {
  symbol: string; company: string | null; series: string | null; status: string | null; start: string | null; end: string | null
  price_lo: number | null; price_hi: number | null; shares: number | null; lot: number | null; size_cr: number | null
  days_left: number | null; bids: IpoBids | null
}
export interface IpoListing {
  symbol: string; company: string | null; kind: string; issue_price: number; price_band: string | null; listing_date: string
  list_open: number | null; list_close: number | null; listing_gain_pct: number | null; listing_close_pct: number | null
  ret_20d_pct: number | null; ret_60d_pct: number | null; last_close: number | null; since_issue_pct: number | null; sessions: number
  qib?: number | null; nii?: number | null; retail?: number | null; total?: number | null
}
export interface IpoBucket { bucket: string; n: number; mean_listing_gain: number | null; median_listing_gain: number | null; pct_listed_above: number | null; n_60d: number; mean_ret_60d: number | null }
export const getIpo = (months = 24, kind: 'Mainboard' | 'SME' = 'Mainboard') =>
  client.get<{ issues: IpoIssue[]; recent: IpoListing[]; buckets: IpoBucket[]; kind: string; months: number
               details: { running: boolean; done: number; total: number }; bhavcopy_through: string | null }>('/api/market/ipo', { params: { months, kind }, timeout: 60000 })

// Live movers (MOV): NSE live market analysis during the session
export interface LiveMover { symbol: string; ltp: number | null; change_pct: number | null; value_cr?: number | null; volume?: number | null; company?: string | null
  vs_week?: number | null; new_level?: number | null; prev_level?: number | null; prev_date?: string | null; high?: number | null; low?: number | null }
export interface LiveOiSpurt { symbol: string; oi: number | null; prev_oi: number | null; oi_change: number | null; oi_change_pct: number | null; underlying: number | null }
export interface LiveIndex { group: string; index: string; last: number | null; change_pct: number | null; advances: number | null; declines: number | null
  pct_30d: number | null; pct_365d: number | null; year_high: number | null; year_low: number | null; pe: number | null }
export interface LiveMovers {
  universe: string; timestamp: string | null; market_open: boolean; errors: Record<string, string>
  gainers: LiveMover[]; losers: LiveMover[]; most_active: LiveMover[]; volume_surge: LiveMover[]
  highs: { count: number; rows: LiveMover[] }; lows: { count: number; rows: LiveMover[] }; oi_spurts: LiveOiSpurt[]; indices: LiveIndex[]
}
export const getLiveMovers = (universe = 'FOSec') => client.get<LiveMovers>('/api/market/live-movers', { params: { universe }, timeout: 40000 })

// Daily market wraps (WRAP): reports/daily_wrap/<date>.md, written 21:00 IST
export const getWraps = (limit = 60) => client.get<{ wraps: { date: string; teaser: string }[] }>('/api/market/wraps', { params: { limit } })
export const getWrap = (day: string) => client.get<{ date: string; markdown: string }>(`/api/market/wraps/${day}`)

// Live quotes for ~300 large and mid caps (NSE heatmap lists): the MKT market map's LIVE mode
export const getLiveQuotes = () =>
  client.get<{ quotes: Record<string, { ltp: number | null; change_pct: number | null; value_cr: number | null; time: string | null }>; lists: number; failed: string[]; market_open: boolean }>(
    '/api/market/live-quotes', { timeout: 40000 })

// Basket risk (DESK watchlist, WTCH): vol, beta, drawdown, correlation over the trailing year
export interface BasketStock { symbol: string; obs: number; vol: number | null; beta: number | null; ret: number | null; max_dd: number | null }
export interface BasketRisk {
  stocks: BasketStock[]; window: { start: string | null; end: string | null; days: number }
  basket?: { n: number; weighting?: 'equal' | 'value'; vol: number; avg_stock_vol: number; diversification: number | null; beta: number | null; ret: number; max_dd: number | null
             avg_corr: number | null; most_correlated: { a: string; b: string; corr: number } | null
             var95?: number | null; es95?: number | null; worst_day?: number | null }
  nifty?: { vol: number; ret: number; max_dd: number | null; var95?: number | null; es95?: number | null; worst_day?: number | null }
}
export const getBasketRisk = (symbols: string[], days = 365, weights?: number[]) =>
  client.get<BasketRisk>('/api/market/basket-risk', { params: { symbols: symbols.join(','), days, ...(weights ? { weights: weights.join(',') } : {}) } })

// Server-side price alerts (WTCH): checked every minute in market hours by the scheduler, even with the terminal closed
export interface AlertLevelsSrv { above?: number; below?: number; move?: number; yahoo?: string }
export interface AlertHitSrv { sym: string; side: 'above' | 'below' | 'move'; level: number; price: number; at: string; change_pct?: number }
export const getPriceAlerts = () => client.get<{ alerts: Record<string, AlertLevelsSrv>; history: AlertHitSrv[] }>('/api/alerts')
export const putPriceAlert = (sym: string, body: { above: number | null; below: number | null; move?: number | null; yahoo?: string }) =>
  client.put<{ alerts: Record<string, AlertLevelsSrv>; history: AlertHitSrv[] }>(`/api/alerts/${encodeURIComponent(sym)}`, body)
export const runPriceAlerts = () => client.post<{ hits: AlertHitSrv[]; checked: number }>('/api/alerts/run', {}, { timeout: 60000 })

// Company filings (CF): today's NSE announcements, categorised
export interface Filing { symbol: string; company: string | null; time: string | null; subject: string; text: string; pdf: string | null; category: string; seq: string | null }
export const getAnnouncements = (day?: string) =>
  client.get<{ date: string; items: Filing[]; counts: Record<string, number>; market_open: boolean }>('/api/market/announcements', { params: day ? { day } : {}, timeout: 40000 })

// W7 S6: the 2-min pollers (EVTS/BRIEF) read only these three fields — 224 KB → 37 KB per poll
export interface FilingCore { symbol: string; time: string | null; category: string }
export const getAnnouncementsCore = (day?: string) =>
  client.get<{ date: string; items: FilingCore[]; counts: Record<string, number>; market_open: boolean }>(
    '/api/market/announcements', { params: { ...(day ? { day } : {}), fields: 'core' }, timeout: 40000 })

// MOV sector board drill-down: live members of one NSE index
export const getIndexMembers = (index: string, group: string) =>
  client.get<{ index: string; group: string; capped: boolean; members: { symbol: string; ltp: number | null; change_pct: number | null; vwap: number | null; value_cr: number | null }[] }>(
    '/api/market/index-members', { params: { index, group } })

// Stock news (Profile): Google News, relevance-filtered to the company
export interface StockHeadline { title: string; publisher: string; link: string; published_at: string }
export const getStockNews = (symbol: string, name?: string, days = 7) =>
  client.get<{ symbol: string; headlines: StockHeadline[] }>(`/api/market/stock-news/${encodeURIComponent(symbol)}`, { params: { name, days }, timeout: 20000 })

// Owner setup checklist (BRIEF): booleans and reasons only, never secrets
export interface SetupCheck { key: string; ok: boolean; title: string; detail: string; fix: string }
export const getSetupStatus = () => client.get<{ checks: SetupCheck[] }>('/api/config/setup-status')

// Margin (MRGN): MTF crowding monitor
export interface MtfStock { symbol: string; name: string | null; amount_cr: number | null; qty_chg_pct: number | null; days_to_unwind: number | null; close: number | null }
export interface MtfMarketRow { date: string; begin_lakh: number | null; fresh_lakh: number | null; liquidated_lakh: number | null; end_lakh: number | null }
export const getMtfMonitor = (lookback = 20, min_amount_cr = 0) =>
  client.get<{ as_of: string | null; base_date: string | null; lookback: number; market: MtfMarketRow[]; stocks: { columns: string[]; data: unknown[][] } }>(
    '/api/market/mtf-monitor', { params: { lookback, min_amount_cr, fields: 'core' } })
    .then(r => ({ ...r, data: { ...r.data, stocks: fromColumnar<MtfStock>(r.data.stocks.columns, r.data.stocks.data) } }))

// US FOMC meetings (WEI, BRIEF): federalreserve.gov calendar
export interface FomcMeeting { start: string; end: string; projections: boolean }
export const getFomc = () => client.get<{ next: FomcMeeting | null; upcoming: FomcMeeting[]; source: string }>('/api/market/fomc')
export const getRbiMpc = () =>
  client.get<{ next: { start: string; end: string } | null; upcoming: { start: string; end: string }[]; source: string | null; stale: boolean }>('/api/market/rbi-mpc')

// ECO: economic calendar (India CPI / WPI / IIP / core / GDP from the official release calendars, RBI and Fed decisions)
export interface EcoEvent { date: string; time: string | null; kind: string; what: string; country: 'IN' | 'US'; source: string | null; moved: boolean }
export type EcoCalendarResponse = { today: string; events: EcoEvent[]; sources: Record<string, string>; note: string | null; valid_until: string | null; fed_available: boolean }
/** The query BRIEF and the session clocks share (today … +7 days; NSE holidays are read for today only). */
export const ECO_SHARED_QUERY = { back: 0, ahead: 7 } as const
// BRIEF, the page header and the desktop title strip (NSE holidays, components/desktop/holidays.ts) used to fetch this
// calendar separately on every page load: that one query is now ONE request per IST day (≤ 30 min old) for every
// caller on the page. Other queries (ECO, EVTS) are fetched exactly as before.
const ecoCache = createSharedCache<AxiosResponse<EcoCalendarResponse>>({ ttlMs: 30 * 60_000 })
export const getEcoCalendar = (back = 14, ahead = 60) => {
  const fetchIt = () => client.get<EcoCalendarResponse>('/api/market/eco-calendar', { params: { back, ahead } })
  return back === ECO_SHARED_QUERY.back && ahead === ECO_SHARED_QUERY.ahead ? ecoCache.get(`${back}:${ahead}`, fetchIt) : fetchIt()
}

// GIFT NIFTY (NSE IX, trades 06:30–15:40 and 16:35–02:45 IST): the overnight cue for the NIFTY open
export interface GiftNifty { last: number | null; change: number | null; change_pct: number | null; expiry: string | null; time: string | null
  nifty_last: number | null; nifty_status: string | null; implied_gap_pct: number | null }
export const getGiftNifty = () => client.get<GiftNifty>('/api/market/gift-nifty')

// Notification inbox (header bell): what the scheduler sent (price, move, filing, wrap)
export interface NotificationItem { at: string; kind: string; title: string; body: string }
export const getNotificationFeed = (limit = 30) => client.get<{ items: NotificationItem[] }>('/api/alerts/feed', { params: { limit } })

// Ownership shifts (HDS): latest shareholding filing vs the previous one
export interface HoldingChange { symbol: string; period_end: string; prev_period: string | null; promoter_pct: number | null; d_promoter: number | null
  fpi_pct: number | null; d_fpi: number | null; mf_pct: number | null; d_mf: number | null; retail_pct: number | null; d_retail: number | null
  total_holders: number | null; d_holders_pct: number | null }
export const getHoldingChanges = () => client.get<{ rows: HoldingChange[]; count: number; data_through: string | null }>('/api/market/holding-changes')

/** Holdings symbols from an /open-positions reply, falling back to the last known holdings when ICICI is not connected. */
export function heldSymbols(d: any): string[] {
  const rows = (d?.positions?.length ? d.positions : d?.last_known?.positions) ?? []
  return rows.map((p: any) => String(p.symbol).toUpperCase())
}
