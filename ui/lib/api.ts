import axios from 'axios'

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
export const getPositionSummary = () => client.get('/api/positions/summary')
export const getOpenPositions = () => client.get('/api/positions/open-positions')
export const getTradeHistory = (limit = 50) =>
  client.get('/api/positions/trade-history', { params: { limit } })
export const getSectorExposure = () => client.get('/api/positions/sector-exposure')
export const getICICIConnectionStatus = () => client.get('/api/positions/connection-status')
export const saveICICICredentials = (payload: {
  api_key: string
  api_secret: string
  client_id?: string
  password?: string
}) => client.post('/api/positions/credentials', payload)
export const updateSessionToken = (token: string) =>
  client.post('/api/positions/session-token', { token })

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

export const fetchICICIDaily = (payload: {
  tickers: string[]
  start_date: string
  end_date?: string
  exchange_code?: string
}) => client.post('/api/data/fetch/icici/daily', payload, { timeout: 300000 })

export const fetchFundamentals = (payload: { tickers: string[] }) =>
  client.post('/api/data/fetch/fundamentals', payload, { timeout: 300000 })

// OHLCV & live quotes
export const getDataOHLCV = (ticker: string, start?: string, end?: string) =>
  client.get(`/api/data/ohlcv/${ticker}`, { params: { start, end }, timeout: 30000 })

export const getDataLiveQuote     = (ticker: string) =>
  client.get(`/api/data/live/quote/${ticker}`, { timeout: 8000 })

export const getDataLiveNifty     = () =>
  client.get('/api/data/live/index/nifty', { timeout: 8000 })

export const getDataIntraday = (ticker: string, interval = '5minute') =>
  client.get(`/api/data/live/intraday/${ticker}`, { params: { interval }, timeout: 30000 })

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

export default client
