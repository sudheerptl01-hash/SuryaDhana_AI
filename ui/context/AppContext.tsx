'use client'

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useEffect,
  useRef,
  ReactNode,
} from 'react'
import { monitorWS, buildWsUrl, type LiveQuote } from '@/lib/wsManager'
import { monitorSubscribe, monitorUnsubscribe, MONITOR_WS_PATH } from '@/lib/api'

// ── ML Config ─────────────────────────────────────────────────────────────────
export interface MLConfig {
  model_type:    string
  n_estimators:  number
  max_depth:     number
  learning_rate: number
  subsample:     number
  train_start:   string
  train_end:     string
}

// ── RL Config ─────────────────────────────────────────────────────────────────
export interface RLConfig {
  total_timesteps: number
  learning_rate:   number
  n_steps:         number
  batch_size:      number
  n_epochs:        number
  n_candidates:    number
  max_positions:   number
  train_start:     string
  train_end:       string
}

// ── Pipeline state ────────────────────────────────────────────────────────────
export interface PipelineState {
  featuresReady:    boolean
  featureInspected: boolean
  modelTrained:     boolean
  rlTrained:        boolean
}

// ── Data-service status (live health checks) ──────────────────────────────────
export interface DataServiceStatus {
  health:   'ok' | 'error' | 'unknown'
  ready:    boolean
  provider: string | null       // e.g. "ICICIBreezeProvider"
  connected: boolean            // ICICI connected?
  lastChecked: number | null    // epoch ms
}

// ── Context shape ─────────────────────────────────────────────────────────────
interface AppContextType {
  // Watchlist
  watchlist:           string[]
  addToWatchlist:      (ticker: string) => void
  removeFromWatchlist: (ticker: string) => void
  clearWatchlist:      () => void
  isWatched:           (ticker: string) => boolean

  // ML / RL config
  mlConfig:    MLConfig
  setMLConfig: (cfg: Partial<MLConfig>) => void

  rlConfig:    RLConfig
  setRLConfig: (cfg: Partial<RLConfig>) => void

  // Pipeline state
  pipeline:    PipelineState
  setPipeline: (s: Partial<PipelineState>) => void

  // Live quotes (keyed by symbol)
  liveQuotes:      Record<string, LiveQuote>
  setLiveQuote:    (symbol: string, quote: LiveQuote) => void

  // WebSocket connection state
  wsConnected:     boolean

  // Data-service health
  dataServiceStatus:    DataServiceStatus
  refreshDataStatus:    () => void
}

// ── Defaults ──────────────────────────────────────────────────────────────────
const today = new Date()
const fiveYearsAgo = new Date(today)
fiveYearsAgo.setFullYear(today.getFullYear() - 5)
const fmt = (d: Date) => d.toISOString().slice(0, 10)

const DEFAULT_ML: MLConfig = {
  model_type:    'xgboost',
  n_estimators:  300,
  max_depth:     5,
  learning_rate: 0.05,
  subsample:     0.8,
  train_start:   fmt(fiveYearsAgo),
  train_end:     fmt(today),
}

const DEFAULT_RL: RLConfig = {
  total_timesteps: 100000,
  learning_rate:   0.0003,
  n_steps:         2048,
  batch_size:      64,
  n_epochs:        10,
  n_candidates:    15,
  max_positions:   5,
  train_start:     fmt(fiveYearsAgo),
  train_end:       fmt(today),
}

const DEFAULT_PIPELINE: PipelineState = {
  featuresReady:    false,
  featureInspected: false,
  modelTrained:     false,
  rlTrained:        false,
}

const DEFAULT_DATA_STATUS: DataServiceStatus = {
  health:      'unknown',
  ready:       false,
  provider:    null,
  connected:   false,
  lastChecked: null,
}

// ── Context ───────────────────────────────────────────────────────────────────
const AppContext = createContext<AppContextType | undefined>(undefined)

export function AppProvider({ children }: { children: ReactNode }) {
  const [watchlist, setWatchlist]         = useState<string[]>([])
  const [mlConfig,  setMLConfigState]     = useState<MLConfig>(DEFAULT_ML)
  const [rlConfig,  setRLConfigState]     = useState<RLConfig>(DEFAULT_RL)
  const [pipeline,  setPipelineState]     = useState<PipelineState>(DEFAULT_PIPELINE)
  const [liveQuotes, setLiveQuotes]       = useState<Record<string, LiveQuote>>({})
  const [wsConnected, setWsConnected]     = useState(false)
  const [dataServiceStatus, setDSStatus]  = useState<DataServiceStatus>(DEFAULT_DATA_STATUS)

  // Track previous watchlist for diff-based subscribe/unsubscribe
  const prevWatchlistRef = useRef<string[]>([])
  // Guards the persist effect until the watchlist has hydrated from localStorage,
  // so the empty initial state never clobbers a stored list on first render.
  const watchlistHydratedRef = useRef(false)

  // ── Live quote updater ──────────────────────────────────────────────────────
  const setLiveQuote = useCallback((symbol: string, quote: LiveQuote) => {
    setLiveQuotes(prev => ({ ...prev, [symbol.toUpperCase()]: quote }))
  }, [])

  // ── Data-service health poll ────────────────────────────────────────────────
  const refreshDataStatus = useCallback(async () => {
    try {
      const { getDataServiceHealth, getDataServiceReady, getDataProviderStatus } =
        await import('@/lib/api')

      const [h, r, p] = await Promise.allSettled([
        getDataServiceHealth(),
        getDataServiceReady(),
        getDataProviderStatus(),
      ])

      const health    = h.status === 'fulfilled' ? 'ok'  : 'error'
      const ready     = r.status === 'fulfilled' ? true  : false
      const provider  = p.status === 'fulfilled' ? (p.value.data?.provider ?? null)  : null
      const connected = p.status === 'fulfilled' ? (p.value.data?.connected ?? false) : false

      setDSStatus({ health, ready, provider, connected, lastChecked: Date.now() })
    } catch {
      setDSStatus(prev => ({ ...prev, health: 'error', lastChecked: Date.now() }))
    }
  }, [])

  // ── WebSocket setup ─────────────────────────────────────────────────────────
  useEffect(() => {
    if (typeof window === 'undefined') return

    const wsUrl = buildWsUrl(MONITOR_WS_PATH)

    // Register a global callback that routes all quotes into liveQuotes state
    const unsub = monitorWS.subscribeAll((data: any) => {
      // The WS server publishes: { symbol, ts, payload: { ltp, ... } }
      const sym = data?.symbol || data?.payload?.symbol
      if (!sym) return

      // Normalise ICICI Breeze field names → canonical LiveQuote fields
      // ICICI: ltp_percent_change (vs generic: change_pct)
      // ICICI: previous_close     (vs generic: prev_close)
      const p = data?.payload ?? {}
      const ltp = p?.ltp ?? p?.last_price ?? data?.ltp
      const prevClose = p?.previous_close ?? p?.prev_close
      const changePct = p?.change_pct ?? p?.ltp_percent_change ?? p?.changepct
      const change    = p?.change ?? (
        ltp != null && prevClose != null ? ltp - prevClose : undefined
      )

      setLiveQuote(sym, {
        symbol:     sym,
        ltp,
        change,
        change_pct: changePct,
        volume:     p?.volume ?? p?.total_quantity_traded,
        ts:         data?.ts,
        raw:        p,
      })
    })

    monitorWS.connect(wsUrl, setWsConnected)

    // Always subscribe to NIFTY
    monitorWS.addSymbols(['NIFTY', 'NSEI'])

    return () => {
      unsub()
      monitorWS.disconnect()
    }
  }, [setLiveQuote]) // eslint-disable-line react-hooks/exhaustive-deps

  // ── Sync watchlist changes → WS subscription + Redis set ───────────────────
  useEffect(() => {
    const prev = prevWatchlistRef.current
    const added   = watchlist.filter(t => !prev.includes(t))
    const removed = prev.filter(t => !watchlist.includes(t))

    if (added.length)   monitorWS.addSymbols(added)
    if (removed.length) monitorWS.removeSymbols(removed)

    // Fire-and-forget REST calls to maintain the Redis monitored set
    added.forEach(t   => monitorSubscribe(t).catch(() => { /* best-effort */ }))
    removed.forEach(t => monitorUnsubscribe(t).catch(() => { /* best-effort */ }))

    prevWatchlistRef.current = watchlist
  }, [watchlist])

  // ── Poll data-service status every 30s ─────────────────────────────────────
  useEffect(() => {
    refreshDataStatus()
    const id = setInterval(refreshDataStatus, 30_000)
    return () => clearInterval(id)
  }, [refreshDataStatus])

  // ── Watchlist helpers ───────────────────────────────────────────────────────
  const addToWatchlist = useCallback((ticker: string) => {
    setWatchlist(prev => prev.includes(ticker) ? prev : [...prev, ticker])
  }, [])

  const removeFromWatchlist = useCallback((ticker: string) => {
    setWatchlist(prev => prev.filter(t => t !== ticker))
  }, [])

  const clearWatchlist = useCallback(() => setWatchlist([]), [])
  const isWatched      = useCallback((ticker: string) => watchlist.includes(ticker), [watchlist])

  // ── Persist watchlist across reloads / restarts (localStorage) ──────────────
  const WATCHLIST_KEY = 'suryadhana.watchlist'

  useEffect(() => {
    // Hydrate once on mount (client-only; localStorage is undefined during SSR).
    try {
      const raw = typeof window !== 'undefined' ? window.localStorage.getItem(WATCHLIST_KEY) : null
      if (raw) {
        const parsed = JSON.parse(raw)
        if (Array.isArray(parsed)) {
          setWatchlist(parsed.filter((t): t is string => typeof t === 'string'))
        }
      }
    } catch { /* ignore corrupt/blocked storage */ }
    watchlistHydratedRef.current = true
  }, [])

  useEffect(() => {
    if (!watchlistHydratedRef.current) return  // don't overwrite store before hydration
    try { window.localStorage.setItem(WATCHLIST_KEY, JSON.stringify(watchlist)) } catch { /* quota/SSR */ }
  }, [watchlist])

  // ── Config setters ──────────────────────────────────────────────────────────
  const setMLConfig = useCallback((cfg: Partial<MLConfig>) => {
    setMLConfigState(prev => ({ ...prev, ...cfg }))
  }, [])

  const setRLConfig = useCallback((cfg: Partial<RLConfig>) => {
    setRLConfigState(prev => ({ ...prev, ...cfg }))
  }, [])

  const setPipeline = useCallback((s: Partial<PipelineState>) => {
    setPipelineState(prev => ({ ...prev, ...s }))
  }, [])

  return (
    <AppContext.Provider value={{
      watchlist, addToWatchlist, removeFromWatchlist, clearWatchlist, isWatched,
      mlConfig, setMLConfig,
      rlConfig, setRLConfig,
      pipeline, setPipeline,
      liveQuotes, setLiveQuote,
      wsConnected,
      dataServiceStatus, refreshDataStatus,
    }}>
      {children}
    </AppContext.Provider>
  )
}

// ── Hooks ─────────────────────────────────────────────────────────────────────

export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used within AppProvider')
  return ctx
}

export function useWatchlist() {
  const { watchlist, addToWatchlist, removeFromWatchlist, clearWatchlist, isWatched } = useApp()
  return { watchlist, addToWatchlist, removeFromWatchlist, clearWatchlist, isWatched }
}

export function useMLConfig() {
  const { mlConfig, setMLConfig } = useApp()
  return { mlConfig, setMLConfig }
}

export function useRLConfig() {
  const { rlConfig, setRLConfig } = useApp()
  return { rlConfig, setRLConfig }
}

export function usePipeline() {
  const { pipeline, setPipeline } = useApp()
  return { pipeline, setPipeline }
}

export function useLiveQuotes() {
  const { liveQuotes, wsConnected } = useApp()
  return { liveQuotes, wsConnected }
}

export function useDataServiceStatus() {
  const { dataServiceStatus, refreshDataStatus } = useApp()
  return { dataServiceStatus, refreshDataStatus }
}

export type { LiveQuote }
