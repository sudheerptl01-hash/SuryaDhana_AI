'use client'

import { useEffect, useState, useCallback } from 'react'
import clsx from 'clsx'
import { ThemeProvider, useTheme } from '@/context/ThemeContext'
import { AppProvider, useWatchlist } from '@/context/AppContext'
import {
  getDashboardSummary,
  getEnrichmentStatus,
  listStocks,
  screenStocks,
  triggerRefresh,
  getRefreshStatus,
  bootstrapUniverse,
  triggerEnrich,
  getEnrichProgress,
} from '@/lib/api'
import { KPICard } from '@/components/KPICard'
import { StockTable } from '@/components/StockTable'
import { StockDetailModal } from '@/components/StockDetailModal'
import { PipelineStudio } from '@/components/PipelineStudio'
import { LivePortfolio } from '@/components/LivePortfolio'
import { BacktestPanel } from '@/components/BacktestPanel'
import { SystemTelemetry } from '@/components/SystemTelemetry'
import { LWScanner } from '@/components/LWScanner'
import { DataExplorerTab } from '@/components/DataExplorerTab'
import { LiveMonitorBar } from '@/components/LiveMonitorBar'
import { SystemStatusWidget } from '@/components/SystemStatusWidget'
import { ToastProvider } from '@/context/ToastContext'

type Tab = 'overview' | 'stocks' | 'backtest' | 'positions' | 'pipeline' | 'scanner' | 'explorer' | 'system'

const FILTERS_INIT = { t1: false, t2: false, t3: false, t4: false, t5: false, t6: false, t7: false, t8: false }

function HomeContent() {
  const [view, setView] = useState<Tab>('overview')
  const { isDark, toggleTheme } = useTheme()
  const { watchlist, addToWatchlist, removeFromWatchlist, isWatched } = useWatchlist()
  const [dashboard, setDashboard] = useState<any>(null)
  const [enrichment, setEnrichment] = useState<any>(null)

  const [allStocks, setAllStocks] = useState<any[]>([])
  const [displayStocks, setDisplayStocks] = useState<any[]>([])
  const [totalStocks, setTotalStocks] = useState(0)
  const [isFiltered, setIsFiltered] = useState(false)
  const [filteredTotal, setFilteredTotal] = useState(0)

  const [selectedTicker, setSelectedTicker] = useState<string | null>(null)
  const [pageLoading, setPageLoading] = useState(true)
  const [filterLoading, setFilterLoading] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [showRefreshPanel, setShowRefreshPanel] = useState(false)
  const [refreshStatus, setRefreshStatus] = useState<any>(null)
  const [refreshError, setRefreshError] = useState<string | null>(null)
  const [bootstrapping, setBootstrapping] = useState(false)
  const [bootstrapResult, setBootstrapResult] = useState<any>(null)
  const [stocksPage, setStocksPage] = useState(0)
  const [technicalFilters, setTechnicalFilters] = useState(FILTERS_INIT)
  const [enriching, setEnriching] = useState(false)
  const [enrichProgress, setEnrichProgress] = useState<any>(null)

  // ── Initial load (with retry) ─────────────────────────────────────────────
  const [loadError, setLoadError] = useState<string | null>(null)
  const [retryCount, setRetryCount] = useState(0)

  const loadDashboard = useCallback(async () => {
    setPageLoading(true)
    setLoadError(null)
    try {
      const [dash, enrich, stocksRes] = await Promise.all([
        getDashboardSummary(),
        getEnrichmentStatus(),
        listStocks(0, 1500),
      ])
      setDashboard(dash.data)
      setEnrichment(enrich.data)
      const stocks = stocksRes.data?.stocks || []
      const total = stocksRes.data?.total || stocks.length
      setAllStocks(stocks)
      setDisplayStocks(stocks)
      setTotalStocks(total)
    } catch (err: any) {
      const msg = err?.message || 'Backend unreachable'
      setLoadError(msg)
      console.error('Failed to load dashboard:', err)
    } finally {
      setPageLoading(false)
    }
  }, [])

  useEffect(() => { loadDashboard() }, [loadDashboard, retryCount])

  // ── Screener filter ───────────────────────────────────────────────────────
  const applyTechnicalFilters = useCallback(async (filters: typeof FILTERS_INIT) => {
    setTechnicalFilters(filters)
    const anyActive = Object.values(filters).some(Boolean)

    if (!anyActive) {
      setIsFiltered(false)
      setDisplayStocks(allStocks)
      return
    }

    setFilterLoading(true)
    try {
      const byTicker = new Map(allStocks.map((stock) => [stock.ticker, stock]))
      const res = await screenStocks(filters, 0, 200)
      const results = (res.data?.results || []).map((r: any) => ({
        ...(byTicker.get(r.ticker) || {}),
        ticker: r.ticker,
        latest_price: r.latest_price,
        price_date: r.price_date,
        total_rows: 0,
        first_date: '',
        latest_date: r.price_date,
        years_of_data: 0,
        data_density_pct: 95,
        days_since_update: 0,
        data_quality: 'excellent',
        ma50: r.ma50,
        ma150: r.ma150,
        ma200: r.ma200,
        rs_rating: r.rs_rating,
        sepa_stage: r.sepa_stage,
        filters: r.filters,
      }))
      setIsFiltered(true)
      setFilteredTotal(res.data?.total || results.length)
      setDisplayStocks(results)
    } catch (err) {
      console.error('Screener error:', err)
    } finally {
      setFilterLoading(false)
    }
  }, [allStocks])

  // ── Load more ─────────────────────────────────────────────────────────────
  const loadMoreStocks = async () => {
    const nextPage = stocksPage + 1
    setStocksPage(nextPage)
    const res = await listStocks(nextPage * 100, 100)
    const newBatch = res.data?.stocks || []
    const combined = [...allStocks, ...newBatch]
    setAllStocks(combined)
    if (!isFiltered) setDisplayStocks(combined)
  }

  // ── Bootstrap universe (cold-start: fetch Nifty 500 list from NSE) ─────────
  const handleBootstrap = async () => {
    setBootstrapping(true)
    setBootstrapResult(null)
    setRefreshError(null)
    try {
      const res = await bootstrapUniverse()
      setBootstrapResult(res.data)
      // Auto-trigger OHLCV refresh after successful bootstrap
      if (res.data?.status === 'bootstrapped') {
        setTimeout(() => handleRefresh(), 500)
      }
    } catch (err: any) {
      setRefreshError(err?.response?.data?.detail || 'Bootstrap failed. Check your internet connection.')
    } finally {
      setBootstrapping(false)
    }
  }

  // ── Refresh: smart incremental OHLCV download ────────────────────────────
  const handleRefresh = async () => {
    if (refreshing) {
      setShowRefreshPanel(true)
      return
    }
    setRefreshing(true)
    setShowRefreshPanel(true)
    setRefreshStatus(null)
    setRefreshError(null)
    try {
      const triggerRes = await triggerRefresh({ universe: 'nse_1500', years: 5 })
      const data = triggerRes.data

      // Backend signals no universe exists — show setup guidance
      if (data?.status === 'no_universe') {
        setRefreshError(data.message || 'No universe data found. Bootstrap first.')
        setRefreshing(false)
        return
      }

      // Poll progress every 3 seconds until done
      const poll = async () => {
        try {
          const res = await getRefreshStatus()
          setRefreshStatus(res.data)
          if (res.data?.active) {
            setTimeout(poll, 3000)
          } else {
            setRefreshing(false)
            // Re-fetch dashboard after completion
            const [dash, enrich, stocksRes] = await Promise.all([
              getDashboardSummary(),
              getEnrichmentStatus(),
              listStocks(0, 1500),
            ])
            setDashboard(dash.data)
            setEnrichment(enrich.data)
            const stocks = stocksRes.data?.stocks || []
            setAllStocks(stocks)
            setDisplayStocks(stocks)
            setTotalStocks(stocksRes.data?.total || stocks.length)
            setStocksPage(0)
          }
        } catch {
          setRefreshing(false)
        }
      }
      setTimeout(poll, 2000)
    } catch (err) {
      console.error('Refresh error:', err)
      setRefreshing(false)
    }
  }

  // ── Enrich fundamentals (PE, MCap, NP QTR, Sales, ROCE) ─────────────────
  const handleEnrich = async () => {
    if (enriching) return
    setEnriching(true)
    setEnrichProgress(null)
    try {
      await triggerEnrich()
      const poll = async () => {
        try {
          const res = await getEnrichProgress()
          setEnrichProgress(res.data)
          if (res.data?.active) {
            setTimeout(poll, 5000)
          } else {
            setEnriching(false)
            const dash = await getDashboardSummary()
            setDashboard(dash.data)
          }
        } catch { setEnriching(false) }
      }
      setTimeout(poll, 2000)
    } catch { setEnriching(false) }
  }

  const activeFilterCount = Object.values(technicalFilters).filter(Boolean).length
  const displayCount = isFiltered ? filteredTotal : totalStocks

  return (
    <div className={clsx(
      'min-h-screen transition-colors duration-500 font-mono',
      isDark
        ? 'bg-gradient-to-br from-slate-950 via-slate-920 to-slate-950 text-slate-100'
        : 'bg-gradient-to-br from-slate-50 via-white to-slate-50 text-slate-900'
    )}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600;700&display=swap');
        @import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&display=swap');

        * { scrollbar-width: thin; scrollbar-color: rgb(100, 116, 139) transparent; }
        *::-webkit-scrollbar { width: 6px; height: 6px; }
        *::-webkit-scrollbar-track { background: transparent; }
        *::-webkit-scrollbar-thumb { background: rgb(100, 116, 139); border-radius: 3px; }
        *::-webkit-scrollbar-thumb:hover { background: rgb(148, 163, 184); }

        body {
          font-family: 'IBM Plex Mono', 'Courier New', monospace;
          background-attachment: fixed;
        }

        /* Bloomberg terminal aesthetic: subtle grid background */
        @keyframes fadeIn {
          from { opacity: 0; transform: translateY(4px); }
          to { opacity: 1; transform: translateY(0); }
        }

        main > * {
          animation: fadeIn 0.6s ease-out;
        }

        main > *:nth-child(2) { animation-delay: 0.1s; }
        main > *:nth-child(3) { animation-delay: 0.2s; }
        main > *:nth-child(4) { animation-delay: 0.3s; }
      `}</style>
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <header className={clsx(
        'border-b sticky top-0 z-40 shadow-xl transition-all duration-300',
        isDark
          ? 'border-slate-700/30 bg-gradient-to-r from-slate-900/60 via-slate-900/50 to-slate-900/60 backdrop-blur-xl'
          : 'border-gray-200 bg-white/95 backdrop-blur-md'
      )}>
        <div className="w-full px-4 sm:px-6 lg:px-8 py-3 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center text-xl shadow-md">
              ☀️
            </div>
            <div>
              <h1 className={clsx('text-2xl font-black tracking-tight', isDark ? 'text-slate-100' : 'text-gray-900')}>
                SuryaDhana
              </h1>
              <p className={clsx('text-xs mt-0.5', isDark ? 'text-slate-400' : 'text-gray-400')}>NSE Quant System · XGBoost + RL</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className={clsx('flex items-center gap-2 px-3 py-1.5 rounded-lg border', isDark ? 'bg-emerald-950/50 border-emerald-700/50' : 'bg-emerald-50 border-emerald-200')}>
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <span className={clsx('text-xs font-semibold', isDark ? 'text-emerald-300' : 'text-emerald-700')}>LIVE</span>
            </div>
            <div className={clsx('text-xs', isDark ? 'text-slate-400' : 'text-gray-500')}>
              <span className={clsx('font-bold', isDark ? 'text-slate-100' : 'text-gray-900')}>{dashboard?.total_stocks ?? totalStocks}</span> stocks ·{' '}
              <span className={clsx('font-bold', isDark ? 'text-slate-100' : 'text-gray-900')}>{dashboard?.latest_date || '—'}</span>
            </div>
            {/* Theme Toggle Button */}
            <button
              onClick={toggleTheme}
              className={clsx(
                'flex items-center justify-center w-10 h-10 rounded-lg font-semibold transition-all text-sm border',
                isDark
                  ? 'bg-amber-500/10 border-amber-500/30 hover:bg-amber-500/20 hover:border-amber-500/50 text-amber-400 shadow-lg shadow-amber-500/5'
                  : 'bg-indigo-50 border-indigo-200 hover:bg-indigo-100 text-indigo-600 shadow-md'
              )}
              title={isDark ? 'Switch to day view' : 'Switch to night view'}
            >
              {isDark ? '☀️' : '🌙'}
            </button>
            {/* Refresh Button */}
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className={clsx(
                'flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold border transition-all',
                refreshing
                  ? 'bg-indigo-50 border-indigo-200 text-indigo-400 cursor-not-allowed'
                  : 'bg-indigo-600 border-indigo-600 text-white hover:bg-indigo-700 shadow-sm'
              )}
              title="Refresh all stock data from NSE 1500 universe via yfinance"
            >
              <span
                className={clsx(
                  'text-sm',
                  refreshing ? 'inline-block animate-spin' : ''
                )}
              >
                {refreshing ? '↻' : '↻'}
              </span>
              {refreshing ? 'Refreshing…' : 'Refresh Data'}
            </button>
          </div>
        </div>
      </header>

      {/* ── Live Monitor Bar: NIFTY + Watchlist ticks ───────────────────── */}
      <LiveMonitorBar isDark={isDark} />

      {/* ── Refresh / Setup Panel ───────────────────────────────────────── */}
      {showRefreshPanel && (
        <div className={clsx('border-b', isDark ? 'border-indigo-900/50 bg-indigo-950/30' : 'border-indigo-100 bg-indigo-50')}>
          <div className="w-full px-4 sm:px-6 lg:px-8 py-4">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-3">
                {(refreshing || bootstrapping) && (
                  <span className="w-3 h-3 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
                )}
                <span className={clsx(
                  'text-sm font-bold',
                  refreshError ? 'text-amber-700' : isDark ? 'text-indigo-300' : 'text-indigo-800'
                )}>
                  {bootstrapping
                    ? 'Bootstrapping NSE 500 universe from niftyindices.com…'
                    : refreshError
                    ? 'Setup required — no stock data found'
                    : refreshing
                    ? `Downloading 5yr OHLCV from NSE via yfinance…`
                    : refreshStatus?.total > 0
                    ? `Done — ${refreshStatus.done}/${refreshStatus.total} stocks updated`
                    : 'Refresh complete'}
                </span>
                {refreshStatus && !refreshError && (
                  <span className="text-xs text-indigo-600">
                    {refreshStatus.done} done · {refreshStatus.downloading} active · {refreshStatus.pending} pending
                    {refreshStatus.errors > 0 && ` · ${refreshStatus.errors} errors`}
                  </span>
                )}
              </div>
              <button
                onClick={() => { setShowRefreshPanel(false); setRefreshError(null); setBootstrapResult(null) }}
                className={clsx('text-sm font-medium', isDark ? 'text-indigo-400 hover:text-indigo-200' : 'text-indigo-400 hover:text-indigo-700')}
              >
                Close
              </button>
            </div>

            {/* ── No-universe setup guidance ─────────────────────────────── */}
            {refreshError && (
              <div className={clsx('rounded-lg p-4 mb-3 border', isDark ? 'bg-amber-950/40 border-amber-700/50' : 'bg-amber-50 border-amber-200')}>
                <p className={clsx('text-xs mb-3', isDark ? 'text-amber-300' : 'text-amber-800')}>
                  The database is empty and no universe CSV was found. Choose a setup path:
                </p>
                <div className="flex flex-wrap gap-3">
                  {/* Option A: Quick bootstrap from NSE */}
                  <button
                    onClick={handleBootstrap}
                    disabled={bootstrapping}
                    className={clsx(
                      'flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold border transition-all',
                      bootstrapping
                        ? 'bg-emerald-50 border-emerald-200 text-emerald-400 cursor-not-allowed'
                        : 'bg-emerald-600 border-emerald-600 text-white hover:bg-emerald-700 shadow-sm'
                    )}
                  >
                    {bootstrapping ? '↻ Fetching…' : '⚡ Quick Bootstrap (Nifty 500)'}
                  </button>
                  {/* Option B: Manual terminal steps */}
                  <div className={clsx('text-xs rounded-lg px-3 py-2 border font-mono', isDark ? 'bg-slate-900 border-slate-700 text-slate-300' : 'bg-white border-gray-200 text-gray-700')}>
                    <span className="text-gray-400">Or run in terminal:</span>
                    <br />
                    <span className="text-emerald-500">python</span> scripts/nifty500_pipeline.py <span className="text-amber-400">--mode universe1500</span>
                    <br />
                    <span className="text-emerald-500">python</span> scripts/nifty500_pipeline.py <span className="text-amber-400">--mode initial</span>
                  </div>
                </div>
                {bootstrapResult && (
                  <p className={clsx('text-xs mt-2 font-semibold', isDark ? 'text-emerald-400' : 'text-emerald-700')}>
                    ✓ {bootstrapResult.tickers} tickers loaded — downloading OHLCV data now…
                  </p>
                )}
              </div>
            )}

            {/* ── Progress bar ───────────────────────────────────────────── */}
            {refreshStatus?.total > 0 && (
              <div className="w-full h-2 rounded-full bg-indigo-200 overflow-hidden mb-3">
                <div
                  className="h-full bg-indigo-600 rounded-full transition-all duration-500"
                  style={{ width: `${refreshStatus.pct}%` }}
                />
              </div>
            )}

            {/* ── Per-ticker status badges ────────────────────────────────── */}
            {refreshStatus?.tickers && Object.keys(refreshStatus.tickers).length > 0 && (
              <div className="flex flex-wrap gap-1 max-h-28 overflow-y-auto">
                {Object.entries(refreshStatus.tickers as Record<string, string>).map(([t, status]) => (
                  <span
                    key={t}
                    className={clsx(
                      'text-xs px-1.5 py-0.5 rounded font-mono',
                      status === 'done'        ? 'bg-emerald-100 text-emerald-700' :
                      status === 'downloading' ? 'bg-indigo-200 text-indigo-700 animate-pulse' :
                      status === 'error'       ? 'bg-rose-100 text-rose-600' :
                                                 'bg-gray-100 text-gray-400'
                    )}
                  >
                    {t}
                  </span>
                ))}
              </div>
            )}

            {!refreshStatus && refreshing && (
              <p className={clsx('text-xs', isDark ? 'text-indigo-400' : 'text-indigo-500')}>
                Fetching 5yr NSE OHLCV from yfinance (.NS suffix) — incremental, only missing dates downloaded per ticker…
              </p>
            )}
          </div>
        </div>
      )}

      {/* ── Navigation ──────────────────────────────────────────────────── */}
      <nav className={clsx('w-full px-4 sm:px-6 lg:px-8 pt-4 flex gap-2 overflow-x-auto transition-colors duration-300', isDark ? 'bg-gradient-to-r from-slate-900/50 via-slate-900/30 to-transparent' : 'bg-transparent')}>
        {([
          { id: 'overview',  label: 'Overview',     icon: '📊' },
          { id: 'stocks',   label: 'Stocks',        icon: '📈' },
          { id: 'backtest', label: 'Backtest Lab',  icon: '🧪' },
          { id: 'positions', label: 'Portfolio',    icon: '💰' },
          { id: 'pipeline', label: 'Pipeline',      icon: '⚙️' },
          { id: 'scanner',  label: 'LW Scanner',    icon: '📡' },
          { id: 'explorer', label: 'Data Explorer', icon: '🔬' },
          { id: 'system',   label: 'System',        icon: '🖥️' },
        ] as { id: Tab; label: string; icon: string }[]).map(({ id, label, icon }) => (
          <button
            key={id}
            onClick={() => setView(id)}
            className={clsx(
              'flex items-center gap-1.5 px-4 py-2.5 rounded-lg text-sm font-medium transition-all duration-200 whitespace-nowrap border',
              view === id
                ? isDark
                  ? 'bg-gradient-to-br from-amber-500/20 to-amber-500/10 text-amber-300 border-amber-500/40 shadow-lg shadow-amber-500/10'
                  : 'bg-indigo-600 text-white border-indigo-600 shadow-md shadow-indigo-200'
                : isDark
                  ? 'text-slate-400 border-slate-700/30 hover:text-slate-200 hover:bg-slate-700/40 hover:border-slate-600/50'
                  : 'text-gray-500 border-gray-200 hover:text-gray-800 hover:bg-gray-100'
            )}
          >
            <span>{icon}</span>
            {label}
            {id === 'stocks' && activeFilterCount > 0 && (
              <span className={clsx('ml-1 px-1.5 py-0.5 rounded-full text-xs font-bold', isDark ? 'bg-amber-500/40 text-amber-200' : 'bg-white/30 text-white')}>
                {activeFilterCount}
              </span>
            )}
            {(id === 'backtest' || id === 'pipeline') && watchlist.length > 0 && (
              <span className={clsx('ml-1 px-1.5 py-0.5 rounded-full text-xs font-bold', isDark ? 'bg-emerald-500/40 text-emerald-200' : 'bg-emerald-600 text-white')}>
                {watchlist.length}
              </span>
            )}
          </button>
        ))}
      </nav>

      {/* ── Main Content ────────────────────────────────────────────────── */}
      <main className={clsx(
        'w-full px-2 sm:px-4 lg:px-6 py-8 transition-colors duration-500',
        isDark ? 'bg-gradient-to-br from-slate-950 via-slate-920 to-slate-950' : 'bg-gradient-to-br from-slate-50 via-white to-slate-50'
      )}>
        {pageLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {Array(8).fill(0).map((_, i) => (
              <div key={i} className={clsx('h-28 animate-pulse rounded-xl', isDark ? 'bg-slate-700' : 'bg-gray-200')} />
            ))}
          </div>
        ) : loadError ? (
          /* ── Backend unreachable: retry panel ──────────────────────── */
          <div className="flex flex-col items-center justify-center py-32 gap-6">
            <div className="text-5xl">⚠️</div>
            <div className="text-center">
              <p className={clsx('text-lg font-bold mb-2', isDark ? 'text-slate-200' : 'text-gray-800')}>
                Backend Unreachable
              </p>
              <p className={clsx('text-sm mb-4', isDark ? 'text-slate-400' : 'text-gray-500')}>
                {loadError} — ui-api may be starting up
              </p>
              <button
                onClick={() => setRetryCount(c => c + 1)}
                className="px-6 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold rounded-xl transition-all shadow-md"
              >
                Retry Connection
              </button>
            </div>
          </div>
        ) : (
          <>
            {view === 'overview' && (
              <OverviewTab
                dashboard={dashboard}
                enrichment={enrichment}
                totalStocks={totalStocks}
                isDark={isDark}
                enriching={enriching}
                enrichProgress={enrichProgress}
                onEnrich={handleEnrich}
              />
            )}
            {view === 'stocks' && (
              <StocksTab
                displayStocks={displayStocks}
                displayCount={displayCount}
                isFiltered={isFiltered}
                filterLoading={filterLoading}
                technicalFilters={technicalFilters}
                allStocksCount={allStocks.length}
                totalStocks={totalStocks}
                onFilterChange={applyTechnicalFilters}
                onRowClick={setSelectedTicker}
                onLoadMore={loadMoreStocks}
                isDark={isDark}
                watchlist={watchlist}
                onWatchToggle={(ticker: string) => isWatched(ticker) ? removeFromWatchlist(ticker) : addToWatchlist(ticker)}
              />
            )}
            {view === 'backtest' && <BacktestPanel isDark={isDark} watchlist={watchlist} />}
            {view === 'positions' && <LivePortfolio isDark={isDark} />}
            {view === 'scanner' && <LWScanner />}
            {view === 'explorer' && (
              <div className="rounded-2xl border border-slate-700/50 bg-slate-900/60 p-5 shadow-xl">
                <div className="mb-4 flex items-center gap-3">
                  <span className="font-mono text-xs font-semibold tracking-widest text-amber-400">🔬 DATA EXPLORER</span>
                  <span className="font-mono text-[10px] text-slate-500">Paginated feature grid · sort · filter by ticker · data health stats</span>
                </div>
                <DataExplorerTab />
              </div>
            )}
            {view === 'system' && <SystemTelemetry isDark={isDark} />}
            {/* PipelineStudio stays mounted once first visited — preserves training state */}
            <div style={{ display: view === 'pipeline' ? 'block' : 'none' }}>
              <PipelineStudio isDark={isDark} watchlist={watchlist} />
            </div>
          </>
        )}
      </main>

      {/* ── Footer ──────────────────────────────────────────────────────── */}
      <footer className={clsx(
        'mt-16 py-6 transition-colors duration-300',
        isDark
          ? 'border-t border-slate-700/50 bg-slate-900/30'
          : 'border-t border-gray-200 bg-white'
      )}>
        <div className={clsx(
          'w-full px-2 sm:px-4 lg:px-6 text-center text-xs',
          isDark ? 'text-slate-500' : 'text-gray-400'
        )}>
          SuryaDhana © 2026 · Enterprise AI Trading System · NSE India · DuckDB + FastAPI + Next.js
        </div>
      </footer>

      {selectedTicker && (
        <StockDetailModal ticker={selectedTicker} onClose={() => setSelectedTicker(null)} />
      )}
    </div>
  )
}

// ── Overview Tab ──────────────────────────────────────────────────────────────
function OverviewTab({ dashboard, enrichment, totalStocks, isDark = true, enriching, enrichProgress, onEnrich }: any) {
  const stale = dashboard?.days_stale ?? 99
  const freshnessColor = stale <= 1 ? 'emerald' : stale <= 3 ? 'amber' : 'rose'
  const fresh      = dashboard?.freshness?.fresh ?? 0
  const staleCount = dashboard?.freshness?.stale ?? 0
  const veryStale  = dashboard?.freshness?.very_stale ?? 0
  const freshPct   = dashboard?.freshness?.fresh_pct ?? 0
  const enriched   = dashboard?.enrichment?.enriched ?? 0
  const enrichTotal = dashboard?.enrichment?.total ?? totalStocks
  const enrichPct  = dashboard?.enrichment?.enrichment_pct ?? 0
  const universeSize  = dashboard?.universe_size ?? 0
  const coveragePct   = dashboard?.coverage_pct ?? 0
  const universeLabel = (dashboard?.universe_label ?? 'nse_500').replace('nse_', 'NSE ').toUpperCase()
  // dbCount = stocks actually in DuckDB (from dashboard API) — always consistent with freshness numbers
  const dbCount = dashboard?.total_stocks ?? totalStocks

  const card = (isDark: boolean) =>
    isDark ? 'border-slate-700/50 bg-slate-800/40' : 'border-gray-200 bg-white'

  return (
    <div className="space-y-6">

      {/* ── Row 0: Service Status Widget ─────────────────────────────────── */}
      <SystemStatusWidget isDark={isDark} />

      {/* ── Row 1: Universe & OHLCV KPIs ─────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-4 gap-4">
        <KPICard
          label="Universe"
          value={universeSize.toLocaleString()}
          subtext={universeLabel}
          color="indigo" icon="🌐" isDark={isDark}
        />
        <KPICard
          label="In DB"
          value={dbCount.toLocaleString()}
          subtext={`${coveragePct}% of universe`}
          color="violet" icon="📦" isDark={isDark}
        />
        <KPICard
          label="Latest Bar"
          value={dashboard?.latest_date ?? '—'}
          subtext={`${stale}d stale`}
          color={freshnessColor as any} icon="📅" isDark={isDark}
        />
        <KPICard
          label="Data Range"
          value={`${dashboard?.data_range?.from?.slice(0,7) ?? '—'}`}
          subtext={`→ ${dashboard?.data_range?.to ?? '—'}`}
          color="slate" icon="🗓️" isDark={isDark}
        />
      </div>

      {/* ── Row 2: Freshness breakdown ────────────────────────────────────── */}
      <div className={clsx('rounded-2xl border p-5 shadow-sm', card(isDark))}>
        <div className="flex items-center justify-between mb-4">
          <h3 className={clsx('text-sm font-bold', isDark ? 'text-slate-200' : 'text-gray-800')}>
            Data Freshness — {dbCount.toLocaleString()} stocks with OHLCV data
          </h3>
          <span className={clsx('text-xs font-semibold px-2 py-1 rounded-full',
            freshPct >= 95 ? (isDark ? 'bg-emerald-900/50 text-emerald-300' : 'bg-emerald-100 text-emerald-700') :
            freshPct >= 80 ? (isDark ? 'bg-amber-900/50 text-amber-300' : 'bg-amber-100 text-amber-700') :
                             (isDark ? 'bg-rose-900/50 text-rose-300' : 'bg-rose-100 text-rose-700')
          )}>
            {freshPct}% fresh
          </span>
        </div>

        {/* Stacked bar */}
        <div className="w-full h-3 rounded-full overflow-hidden bg-gray-200 dark:bg-slate-700 flex mb-4">
          <div className="h-full bg-emerald-500 transition-all duration-700" style={{ width: `${(fresh / Math.max(dbCount, 1)) * 100}%` }} />
          <div className="h-full bg-amber-400 transition-all duration-700"  style={{ width: `${(staleCount / Math.max(dbCount, 1)) * 100}%` }} />
          <div className="h-full bg-rose-500 transition-all duration-700"   style={{ width: `${(veryStale / Math.max(dbCount, 1)) * 100}%` }} />
        </div>

        <div className="grid grid-cols-3 gap-3">
          <div className={clsx('rounded-xl p-3 border text-center', isDark ? 'bg-emerald-900/20 border-emerald-700/40' : 'bg-emerald-50 border-emerald-200')}>
            <p className={clsx('text-2xl font-black', isDark ? 'text-emerald-300' : 'text-emerald-700')}>{fresh.toLocaleString()}</p>
            <p className={clsx('text-xs font-semibold mt-0.5', isDark ? 'text-emerald-400' : 'text-emerald-600')}>Fresh (&lt;1 day)</p>
          </div>
          <div className={clsx('rounded-xl p-3 border text-center', isDark ? 'bg-amber-900/20 border-amber-700/40' : 'bg-amber-50 border-amber-200')}>
            <p className={clsx('text-2xl font-black', isDark ? 'text-amber-300' : 'text-amber-700')}>{staleCount.toLocaleString()}</p>
            <p className={clsx('text-xs font-semibold mt-0.5', isDark ? 'text-amber-400' : 'text-amber-600')}>Stale (1-7 days)</p>
          </div>
          <div className={clsx('rounded-xl p-3 border text-center', isDark ? 'bg-rose-900/20 border-rose-700/40' : 'bg-rose-50 border-rose-200')}>
            <p className={clsx('text-2xl font-black', isDark ? 'text-rose-300' : 'text-rose-700')}>{veryStale.toLocaleString()}</p>
            <p className={clsx('text-xs font-semibold mt-0.5', isDark ? 'text-rose-400' : 'text-rose-600')}>Very Stale (&gt;7d)</p>
          </div>
        </div>
      </div>

      {/* ── Row 3: Enrichment status ──────────────────────────────────────── */}
      <div className={clsx('rounded-2xl border p-5 shadow-sm', card(isDark))}>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className={clsx('text-sm font-bold', isDark ? 'text-slate-200' : 'text-gray-800')}>
              Fundamentals Enrichment
            </h3>
            <p className={clsx('text-xs mt-0.5', isDark ? 'text-slate-400' : 'text-gray-500')}>
              PE · MktCap · NP QTR · Sales QTR · ROCE — from Yahoo Finance
            </p>
          </div>
          <button
            onClick={onEnrich}
            disabled={enriching}
            className={clsx(
              'px-4 py-2 rounded-lg text-xs font-bold border transition-all',
              enriching
                ? 'bg-violet-50 border-violet-200 text-violet-400 cursor-not-allowed'
                : 'bg-violet-600 border-violet-600 text-white hover:bg-violet-700 shadow-sm'
            )}
          >
            {enriching ? '⏳ Enriching…' : enriched === 0 ? '⚡ Enrich Now' : '↻ Re-enrich'}
          </button>
        </div>

        {/* Progress bar */}
        <div className="w-full h-2.5 rounded-full overflow-hidden bg-gray-200 mb-3">
          <div
            className="h-full bg-violet-500 transition-all duration-700"
            style={{ width: `${enrichPct}%` }}
          />
        </div>

        {enriching && enrichProgress && (
          <p className={clsx('text-xs mb-2', isDark ? 'text-violet-300' : 'text-violet-700')}>
            {enrichProgress.done?.toLocaleString()} / {enrichProgress.total?.toLocaleString()} enriched · {enrichProgress.pct}%
          </p>
        )}

        <div className="grid grid-cols-3 gap-3">
          <div className={clsx('rounded-xl p-3 border text-center', isDark ? 'bg-violet-900/20 border-violet-700/40' : 'bg-violet-50 border-violet-200')}>
            <p className={clsx('text-2xl font-black', isDark ? 'text-violet-300' : 'text-violet-700')}>{enriched.toLocaleString()}</p>
            <p className={clsx('text-xs font-semibold mt-0.5', isDark ? 'text-violet-400' : 'text-violet-600')}>Enriched</p>
          </div>
          <div className={clsx('rounded-xl p-3 border text-center', isDark ? 'bg-slate-800/40 border-slate-700/30' : 'bg-gray-50 border-gray-200')}>
            <p className={clsx('text-2xl font-black', isDark ? 'text-slate-200' : 'text-gray-800')}>{(enrichTotal - enriched).toLocaleString()}</p>
            <p className={clsx('text-xs font-semibold mt-0.5', isDark ? 'text-slate-400' : 'text-gray-500')}>Pending</p>
          </div>
          <div className={clsx('rounded-xl p-3 border text-center', isDark ? 'bg-slate-800/40 border-slate-700/30' : 'bg-gray-50 border-gray-200')}>
            <p className={clsx('text-2xl font-black', isDark ? 'text-violet-300' : 'text-violet-700')}>{enrichPct}%</p>
            <p className={clsx('text-xs font-semibold mt-0.5', isDark ? 'text-slate-400' : 'text-gray-500')}>Coverage</p>
          </div>
        </div>
      </div>

      {/* ── Row 4: System status ──────────────────────────────────────────── */}
      <div className={clsx('rounded-2xl border p-5 shadow-sm', card(isDark))}>
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <span className={clsx('w-3 h-3 rounded-full animate-pulse',
                (dashboard?.health?.status === 'healthy') ? 'bg-emerald-500' : 'bg-amber-500'
              )} />
              <h3 className={clsx('text-sm font-bold', isDark ? 'text-slate-100' : 'text-gray-900')}>
                Status: <span className={clsx(
                  'font-black',
                  dashboard?.health?.status === 'healthy' ? (isDark ? 'text-emerald-400' : 'text-emerald-600') : (isDark ? 'text-amber-400' : 'text-amber-600')
                )}>
                  {(dashboard?.health?.status ?? 'unknown').toUpperCase()}
                </span>
              </h3>
            </div>
            <p className={clsx('text-xs', isDark ? 'text-slate-400' : 'text-gray-500')}>
              {dbCount.toLocaleString()} stocks · {dashboard?.data_range?.from} → {dashboard?.data_range?.to}
              · Source: Yahoo Finance v8 API (.NS)
            </p>
          </div>
          <span className={clsx('px-4 py-2 rounded-lg font-bold text-xs',
            isDark ? 'bg-emerald-900/40 text-emerald-300 border border-emerald-700/50' : 'bg-emerald-100 text-emerald-700 border border-emerald-200'
          )}>
            Phase 1 + 2 Complete ✓
          </span>
        </div>
      </div>

      {/* ── Row 5: Roadmap ────────────────────────────────────────────────── */}
      <div className={clsx('rounded-2xl border p-5 shadow-sm', card(isDark))}>
        <h3 className={clsx('text-sm font-bold mb-4', isDark ? 'text-slate-200' : 'text-gray-800')}>16-Week Roadmap</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {[
            { phase: 'Phase 1', weeks: '1–3', label: 'NSE 1500 Universe', status: 'done' },
            { phase: 'Phase 2', weeks: '4–6', label: 'DuckDB + 5yr OHLCV', status: 'done' },
            { phase: 'Phase 3', weeks: '7–9', label: '40+ Features + Labels', status: 'pending' },
            { phase: 'Phase 4', weeks: '10–12', label: 'XGBoost Models (55%+)', status: 'pending' },
            { phase: 'Phase 5', weeks: '13–14', label: 'Walk-forward + RL Agent', status: 'pending' },
            { phase: 'Phase 6', weeks: '15–16', label: 'Paper → Live ₹10K', status: 'pending' },
          ].map(({ phase, weeks, label, status }) => (
            <div key={phase} className={clsx(
              'rounded-xl p-4 border',
              status === 'done'
                ? (isDark ? 'border-emerald-700/50 bg-emerald-900/20' : 'border-emerald-200 bg-emerald-50')
                : (isDark ? 'border-slate-700/30 bg-slate-800/20' : 'border-gray-200 bg-gray-50')
            )}>
              <div className="flex items-center justify-between mb-1">
                <span className={clsx('text-xs font-bold', isDark ? 'text-slate-400' : 'text-gray-400')}>{phase} · Wk {weeks}</span>
                <span className={clsx('text-xs font-bold',
                  status === 'done' ? (isDark ? 'text-emerald-400' : 'text-emerald-600') : (isDark ? 'text-slate-500' : 'text-gray-400')
                )}>
                  {status === 'done' ? '✓ DONE' : '⏸ PENDING'}
                </span>
              </div>
              <p className={clsx('text-sm font-semibold',
                status === 'done' ? (isDark ? 'text-emerald-300' : 'text-emerald-800') : (isDark ? 'text-slate-300' : 'text-gray-600')
              )}>{label}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Stocks Tab ────────────────────────────────────────────────────────────────
function StocksTab({
  displayStocks, displayCount, isFiltered, filterLoading, technicalFilters,
  allStocksCount, totalStocks, onFilterChange, onRowClick, onLoadMore, isDark = true,
  watchlist = [], onWatchToggle,
}: any) {
  const FILTERS = [
    { key: 't1', label: 'T1', desc: 'Price > 150/200 MA' },
    { key: 't2', label: 'T2', desc: '150 MA > 200 MA' },
    { key: 't3', label: 'T3', desc: '200 MA Uptrend 1M+' },
    { key: 't4', label: 'T4', desc: '50 MA > 150/200 MA' },
    { key: 't5', label: 'T5', desc: 'Price > 50 MA' },
    { key: 't6', label: 'T6', desc: 'Price ≥30% above 52W low' },
    { key: 't7', label: 'T7', desc: 'Price within 25% of 52W high' },
    { key: 't8', label: 'T8', desc: 'RS Rating ≥70' },
  ]

  const toggle = (key: string) => {
    const next = { ...technicalFilters, [key]: !technicalFilters[key] }
    onFilterChange(next)
  }

  const clearAll = () => onFilterChange({ t1: false, t2: false, t3: false, t4: false, t5: false, t6: false, t7: false, t8: false })
  const activeCount = Object.values(technicalFilters).filter(Boolean).length

  return (
    <div className="space-y-6">
      {/* Filters */}
      <div className={clsx('rounded-2xl border p-6 shadow-sm', isDark ? 'border-slate-700/50 bg-slate-800/40' : 'border-gray-200 bg-white')}>
        <div className="flex items-center justify-between mb-4">
          <h3 className={clsx('text-base font-bold', isDark ? 'text-slate-100' : 'text-gray-900')}>
            Minervini Trend Template Filters
            {activeCount > 0 && (
              <span className={clsx('ml-2 px-2 py-0.5 rounded-full text-xs font-bold', isDark ? 'bg-amber-600/80 text-amber-100' : 'bg-indigo-600 text-white')}>
                {activeCount} active
              </span>
            )}
          </h3>
          {activeCount > 0 && (
            <button
              onClick={clearAll}
              className={clsx('text-xs transition-colors font-medium', isDark ? 'text-slate-400 hover:text-rose-400' : 'text-gray-400 hover:text-rose-500')}
            >
              Clear all
            </button>
          )}
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2">
          {FILTERS.map(({ key, label, desc }) => {
            const active = (technicalFilters as any)[key]
            return (
              <button
                key={key}
                onClick={() => toggle(key)}
                className={clsx(
                  'flex flex-col items-center p-4 rounded-lg border-2 transition-all text-center hover:scale-105',
                  active
                    ? isDark
                      ? 'border-amber-500/50 bg-amber-500/15 text-amber-300 shadow-lg shadow-amber-500/10'
                      : 'border-indigo-500 bg-indigo-50 text-indigo-700 shadow-sm'
                    : isDark
                      ? 'border-slate-700/50 bg-slate-700/20 text-slate-400 hover:border-slate-600 hover:text-slate-300'
                      : 'border-gray-200 bg-gray-50 text-gray-500 hover:border-indigo-300 hover:text-indigo-600'
                )}
              >
                <span className={clsx('text-sm font-black', active ? (isDark ? 'text-amber-300' : 'text-indigo-600') : isDark ? 'text-slate-300' : 'text-gray-700')}>{label}</span>
                <span className={clsx('text-xs mt-1 leading-tight font-medium', active ? (isDark ? 'text-amber-200' : 'text-indigo-600') : isDark ? 'text-slate-300' : 'text-gray-600')}>{desc}</span>
              </button>
            )
          })}
        </div>
      </div>

      {/* Watchlist strip */}
      {watchlist.length > 0 && (
        <div className={clsx('rounded-2xl border p-4 shadow-sm', isDark ? 'border-emerald-700/40 bg-emerald-950/30' : 'border-emerald-200 bg-emerald-50')}>
          <div className="flex items-center gap-3 flex-wrap">
            <span className={clsx('text-xs font-bold uppercase tracking-widest', isDark ? 'text-emerald-400' : 'text-emerald-700')}>
              Watchlist ({watchlist.length}) — syncs to Backtest &amp; Pipeline:
            </span>
            {watchlist.map((t: string) => (
              <span key={t} className={clsx('flex items-center gap-1 px-2 py-1 rounded-lg text-xs font-mono font-bold', isDark ? 'bg-emerald-900/60 text-emerald-300 border border-emerald-700/50' : 'bg-emerald-100 text-emerald-800 border border-emerald-300')}>
                {t}
                <button onClick={() => onWatchToggle(t)} className="ml-0.5 text-emerald-500 hover:text-rose-400 transition-colors">✕</button>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Table */}
      <div className={clsx('rounded-2xl border shadow-sm', isDark ? 'border-slate-700/50 bg-slate-800/30' : 'border-gray-200 bg-white')}>
        <div className={clsx('p-5 border-b flex items-center justify-between', isDark ? 'border-slate-700/30' : 'border-gray-100')}>
          <div>
            <h3 className={clsx('text-lg font-bold tracking-tight', isDark ? 'text-slate-50' : 'text-gray-900')}>
              {isFiltered ? 'Screener Results' : 'All Stocks'}
              <span className={clsx('ml-3 font-mono text-sm opacity-75', isDark ? 'text-slate-400' : 'text-gray-500')}>
                ({isFiltered ? `${displayCount} matched` : `${allStocksCount} of ${totalStocks}`})
              </span>
            </h3>
            {isFiltered && (
              <p className={clsx('text-xs mt-0.5', isDark ? 'text-amber-400' : 'text-indigo-500')}>
                Showing stocks matching {activeCount} active filter{activeCount > 1 ? 's' : ''}
              </p>
            )}
          </div>
          {filterLoading && (
            <div className="flex items-center gap-2 text-xs text-indigo-500">
              <span className="w-3 h-3 border-2 border-indigo-400 border-t-transparent rounded-full animate-spin" />
              Filtering…
            </div>
          )}
        </div>
        <StockTable stocks={displayStocks} onRowClick={onRowClick} loading={filterLoading} isDark={isDark} watchlist={watchlist} onWatchToggle={onWatchToggle} />
        {!isFiltered && allStocksCount < totalStocks && (
          <div className="p-5 border-t border-gray-100 text-center">
            <button
              onClick={onLoadMore}
              className="px-5 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold rounded-lg transition-colors shadow-sm"
            >
              Load More ({totalStocks - allStocksCount} remaining)
            </button>
          </div>
        )}
      </div>
    </div>
  )
}

export default function Home() {
  return (
    <ThemeProvider>
      <AppProvider>
        <ToastProvider>
          <HomeContent />
        </ToastProvider>
      </AppProvider>
    </ThemeProvider>
  )
}

