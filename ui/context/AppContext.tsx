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
import { attachMonitorSocket } from '@/lib/monitorLifecycle'
import { monitorList, monitorSubscribe, monitorUnsubscribe, MONITOR_WS_PATH } from '@/lib/api'
import { useExternalPrefChange } from '@/lib/prefs/useExternalChange'
import { noteQuoteMessage } from '@/lib/liveEvidence'
import { missingMonitorSymbols, MONITOR_RESYNC_MS, MONITOR_RESYNC_HIDDEN_MS } from '@/lib/monitorLifecycle'
import { useDocumentHidden, usePolling } from '@/components/shell/usePoll'

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
  // The list the hydrate effect handed to setWatchlist: the persist effect waits until the state IS that list, so
  // the mount render's empty [] is never written over the stored list (other windows would adopt that transient []).
  const watchlistPendingRef = useRef<string[] | null>(null)
  // Multi-window (C3-02): the serialized list this window last read from or wrote to localStorage. A state equal to
  // it is not written again, so a list adopted from another window (or the server) is never echoed back over a
  // newer write.
  const watchlistStoredRef = useRef<string | null>(null)

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
      // the chips' "market is printing" evidence (R-UI-SHELL-03): only a quote with a fresh exchange time that is a new
      // print counts, never a pong / subscription ack / error, nor a previous session's quote on a holiday (round 4b)
      noteQuoteMessage(data)
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

    // ONE socket per window, closed cleanly on unmount and on page hide, reopened when a hidden page comes back
    // from the back-forward cache (lib/monitorLifecycle.ts). The symbol set survives a reconnect (wsManager keeps it).
    const detach = attachMonitorSocket(window, monitorWS, wsUrl, setWsConnected)

    // Always subscribe to NIFTY
    monitorWS.addSymbols(['NIFTY', 'NSEI'])

    return () => {
      unsub()
      detach()
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

  // ── Poll data-service status every 30 s (2 min while the window is hidden; at once when it is shown again) ──
  // (R-UI-SHELL-06 / C-PERF-06: a window hidden to the menu bar no longer polls the chrome at the visible cadence)
  const hidden = useDocumentHidden()
  usePolling(refreshDataStatus, hidden ? 120_000 : 30_000)

  // ── P10: keep the server's monitored set holding this window's watchlist ───────────────────────────────────
  // data-service's watchlist poller quotes the symbols in Redis `monitored.stocks`, which the diff effect above only
  // fills when a symbol is ADDED. A Redis restart (or flush) empties it while the socket stays up, so the watchlist
  // never ticked again. Re-registered on every socket REconnect and every 10 min (30 min while hidden): one GET of
  // the set, then a subscribe only for the symbols missing from it (idempotent SADD; nothing is ever removed here).
  const watchlistRef = useRef(watchlist)
  watchlistRef.current = watchlist
  const resyncMonitor = useCallback(async () => {
    const list = watchlistRef.current
    if (!list.length) return
    let server: unknown
    try { server = (await monitorList()).data?.symbols } catch { return /* Redis or ui-api down: the next resync retries */ }
    for (const t of missingMonitorSymbols(list, server)) monitorSubscribe(t).catch(() => { /* best-effort */ })
  }, [])
  const wsSeenRef = useRef<'never' | 'up' | 'down'>('never')
  useEffect(() => {
    // the first connect is covered by the diff effect (it subscribes the hydrated list); every reconnect resyncs
    if (wsConnected && wsSeenRef.current === 'down') void resyncMonitor()
    if (wsConnected) wsSeenRef.current = 'up'
    else if (wsSeenRef.current === 'up') wsSeenRef.current = 'down'
  }, [wsConnected, resyncMonitor])
  usePolling(resyncMonitor, hidden ? MONITOR_RESYNC_HIDDEN_MS : MONITOR_RESYNC_MS)

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
          const list = parsed.filter((t): t is string => typeof t === 'string')
          watchlistPendingRef.current = list
          watchlistStoredRef.current = JSON.stringify(list)
          setWatchlist(list)
        }
      }
    } catch { /* ignore corrupt/blocked storage */ }
    watchlistHydratedRef.current = true
  }, [])

  // Changed outside this window's state: another window of this origin (⌘N, session restore, a second tab) or
  // lib/prefs/sync.ts applying a newer server value. Adopt it, so this window's next edit starts from it.
  useExternalPrefChange(WATCHLIST_KEY, () => {
    let list: string[]
    try {
      const parsed = JSON.parse(window.localStorage.getItem(WATCHLIST_KEY) || '[]')
      if (!Array.isArray(parsed)) return
      list = parsed.filter((t): t is string => typeof t === 'string')
    } catch { return /* ignore corrupt/blocked storage */ }
    const s = JSON.stringify(list)
    watchlistPendingRef.current = null
    watchlistStoredRef.current = s
    setWatchlist(prev => (JSON.stringify(prev) === s ? prev : list))
  })

  useEffect(() => {
    if (!watchlistHydratedRef.current) return  // don't overwrite store before hydration
    const pending = watchlistPendingRef.current
    if (pending) {
      if (watchlist !== pending) return        // the mount render's [] (hydration's setWatchlist not applied yet)
      watchlistPendingRef.current = null
    }
    const s = JSON.stringify(watchlist)
    if (s === watchlistStoredRef.current) return  // already stored (hydrated or adopted): never echo it back
    try { window.localStorage.setItem(WATCHLIST_KEY, s); watchlistStoredRef.current = s } catch { /* quota/SSR */ }
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
