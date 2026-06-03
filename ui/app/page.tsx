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
import { QuantKPICard } from '@/components/QuantKPICard'
import { StockTable } from '@/components/StockTable'
import { StockDetailModal } from '@/components/StockDetailModal'
import { PipelineStudio } from '@/components/PipelineStudio'
import { LivePortfolio } from '@/components/LivePortfolio'
import { BacktestPanel } from '@/components/BacktestPanel'
import { SystemTelemetry } from '@/components/SystemTelemetry'
import { LWScanner } from '@/components/LWScanner'
import { DataExplorerTab } from '@/components/DataExplorerTab'
import { WarehouseHealth } from '@/components/WarehouseHealth'
import { AlphaDiscoveryDesk } from '@/components/AlphaDiscoveryDesk'
import { SystemStatusWidget } from '@/components/SystemStatusWidget'
import { LiveMonitorBar } from '@/components/LiveMonitorBar'
import { MarketCommandHeader } from '@/components/MarketCommandHeader'
import { ToastProvider } from '@/context/ToastContext'
import { ErrorCatcher } from '@/components/ErrorCatcher'

type Tab = 'overview' | 'stocks' | 'backtest' | 'positions' | 'pipeline' | 'scanner' | 'discovery' | 'explorer' | 'warehouse' | 'system'

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

  // Build tab descriptor list for MarketCommandHeader
  const tabList = [
    { id: 'overview',  label: 'Overview' },
    { id: 'stocks',    label: 'Stocks',       badge: activeFilterCount || undefined },
    { id: 'backtest',  label: 'Backtest' },
    { id: 'positions', label: 'Portfolio' },
    { id: 'pipeline',  label: 'Pipeline',     badge: watchlist.length || undefined },
    { id: 'scanner',   label: 'LW Scanner' },
    { id: 'discovery', label: 'Alpha Discovery' },
    { id: 'explorer',  label: 'Data Explorer' },
    { id: 'warehouse', label: 'Warehouse' },
    { id: 'system',    label: 'System' },
  ]

  return (
    <div
      className="min-h-screen font-mono"
      style={{
        background: isDark
          ? 'linear-gradient(160deg, #030810 0%, #050D1A 40%, #040B16 100%)'
          : 'linear-gradient(160deg, #F8FAFC 0%, #F1F5F9 100%)',
        color: isDark ? '#C8DCF0' : '#1E293B',
      }}
    >
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&display=swap');

        * { scrollbar-width: thin; scrollbar-color: #1A2D44 transparent; }
        *::-webkit-scrollbar { width: 5px; height: 5px; }
        *::-webkit-scrollbar-track { background: transparent; }
        *::-webkit-scrollbar-thumb { background: #1A2D44; border-radius: 3px; }
        *::-webkit-scrollbar-thumb:hover { background: #243D58; }

        body { font-family: 'JetBrains Mono', 'Courier New', monospace; }

        @keyframes fadeUp {
          from { opacity: 0; transform: translateY(6px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        main > * { animation: fadeUp 0.5s ease-out both; }
        main > *:nth-child(1) { animation-delay: 0.05s; }
        main > *:nth-child(2) { animation-delay: 0.12s; }
        main > *:nth-child(3) { animation-delay: 0.20s; }
        main > *:nth-child(4) { animation-delay: 0.28s; }
      `}</style>

      {/* ── NSE Operations Center Command Header ───────────────────────── */}
      <MarketCommandHeader
        onRefresh={handleRefresh}
        refreshing={refreshing}
        totalStocks={dashboard?.total_stocks ?? totalStocks}
        latestDate={dashboard?.latest_date}
        activeTab={view}
        tabs={tabList}
        onTabChange={(id) => setView(id as Tab)}
      />

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

      {/* ── Live Monitor Bar ────────────────────────────────────────────── */}
      <LiveMonitorBar isDark={isDark} />

      {/* ── Main Content ────────────────────────────────────────────────── */}
      <main className="w-full px-2 sm:px-4 lg:px-6 py-6">
        {pageLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {Array(8).fill(0).map((_, i) => (
              <div
                key={i}
                className="h-28 animate-pulse rounded-lg"
                style={{ background: 'rgba(7,14,27,0.9)', border: '1px solid rgba(17,30,48,0.9)' }}
              />
            ))}
          </div>
        ) : loadError ? (
          /* ── Backend unreachable ───────────────────────────────────── */
          <div className="flex flex-col items-center justify-center py-32 gap-6">
            <div
              className="w-16 h-16 rounded-full flex items-center justify-center text-3xl"
              style={{ background: 'rgba(255,59,71,0.08)', border: '1px solid rgba(255,59,71,0.2)' }}
            >
              ⚠
            </div>
            <div className="text-center">
              <p
                className="text-lg font-bold mb-2"
                style={{ fontFamily: "'Chakra Petch', sans-serif", color: '#C8DCF0' }}
              >
                BACKEND UNREACHABLE
              </p>
              <p className="text-sm mb-6" style={{ color: '#3D5872' }}>
                {loadError} — ui-api may be starting up
              </p>
              <button
                onClick={() => setRetryCount(c => c + 1)}
                className="px-6 py-2.5 text-sm font-semibold rounded-lg transition-all"
                style={{
                  background: 'rgba(245,166,35,0.1)',
                  border: '1px solid rgba(245,166,35,0.3)',
                  color: '#F5A623',
                  fontFamily: "'Chakra Petch', sans-serif",
                }}
              >
                RETRY CONNECTION
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
            {view === 'discovery' && <AlphaDiscoveryDesk isDark={isDark} />}
            {view === 'explorer' && (
              <div className="rounded-2xl border border-slate-700/50 bg-slate-900/60 p-5 shadow-xl">
                <div className="mb-4 flex items-center gap-3">
                  <span className="font-mono text-xs font-semibold tracking-widest text-amber-400">🔬 DATA EXPLORER</span>
                  <span className="font-mono text-[10px] text-slate-500">Paginated feature grid · sort · filter by ticker · data health stats</span>
                </div>
                <DataExplorerTab />
              </div>
            )}
            {view === 'warehouse' && <WarehouseHealth isDark={isDark} />}
            {view === 'system' && <SystemTelemetry isDark={isDark} />}
            {/* PipelineStudio stays mounted once first visited — preserves training state */}
            <div style={{ display: view === 'pipeline' ? 'block' : 'none' }}>
              <PipelineStudio isDark={isDark} watchlist={watchlist} />
            </div>
          </>
        )}
      </main>

      {/* ── Footer ──────────────────────────────────────────────────────── */}
      <footer
        className="mt-16 py-4"
        style={{ borderTop: '1px solid rgba(17,30,48,0.9)' }}
      >
        <div
          className="w-full px-4 lg:px-6 text-center text-[10px] tracking-widest uppercase"
          style={{ fontFamily: "'Chakra Petch', sans-serif", color: '#3D5872' }}
        >
          SURYADHANA © 2026 · NSE INDIA · DUCKDB + FASTAPI + NEXTJS · XGBOOST + RL
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

      {/* ── Row 1: Universe & OHLCV KPIs ─────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-4 gap-4">
        <QuantKPICard
          label="Universe"
          value={universeSize.toLocaleString()}
          subtext={universeLabel}
          accent="indigo" icon="◈" animate
        />
        <QuantKPICard
          label="In Database"
          value={dbCount.toLocaleString()}
          subtext={`${coveragePct}% coverage`}
          accent="violet" icon="⊞" animate
        />
        <QuantKPICard
          label="Latest Bar"
          value={dashboard?.latest_date ?? '—'}
          subtext={`${stale}d stale`}
          accent={freshnessColor === 'emerald' ? 'jade' : freshnessColor === 'amber' ? 'amber' : 'crimson'}
          icon="▦"
        />
        <QuantKPICard
          label="Data Window"
          value={`${dashboard?.data_range?.from?.slice(0,7) ?? '—'}`}
          subtext={`→ ${dashboard?.data_range?.to ?? '—'}`}
          accent="slate" icon="⬡"
        />
      </div>

      {/* ── Row 2: Freshness breakdown ────────────────────────────────────── */}
      <div className="rounded-lg p-5" style={{ background: '#070E1B', border: '1px solid #111E30' }}>
        {/* Header row */}
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3
              className="text-xs font-semibold tracking-widest uppercase"
              style={{ fontFamily: "'Chakra Petch', sans-serif", color: '#3D5872' }}
            >
              DATA FRESHNESS
            </h3>
            <p
              className="mt-0.5 text-sm font-bold tabular-nums"
              style={{ fontFamily: "'JetBrains Mono', monospace", color: '#C8DCF0' }}
            >
              {dbCount.toLocaleString()} stocks with OHLCV data
            </p>
          </div>
          <span
            className="text-xs font-bold px-2.5 py-1 rounded tabular-nums"
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              background: freshPct >= 95 ? 'rgba(0,200,150,0.10)' : freshPct >= 80 ? 'rgba(245,166,35,0.10)' : 'rgba(255,59,71,0.08)',
              color:      freshPct >= 95 ? '#00C896' : freshPct >= 80 ? '#F5A623' : '#FF3B47',
              border:     `1px solid ${freshPct >= 95 ? 'rgba(0,200,150,0.2)' : freshPct >= 80 ? 'rgba(245,166,35,0.2)' : 'rgba(255,59,71,0.2)'}`,
            }}
          >
            {freshPct}% FRESH
          </span>
        </div>

        {/* Segmented progress bar */}
        <div className="w-full h-2 rounded-sm overflow-hidden flex mb-5" style={{ background: '#0E1828' }}>
          <div className="h-full transition-all duration-700" style={{ width: `${(fresh / Math.max(dbCount, 1)) * 100}%`, background: '#00C896' }} />
          <div className="h-full transition-all duration-700" style={{ width: `${(staleCount / Math.max(dbCount, 1)) * 100}%`, background: '#F5A623' }} />
          <div className="h-full transition-all duration-700" style={{ width: `${(veryStale / Math.max(dbCount, 1)) * 100}%`, background: '#FF3B47' }} />
        </div>

        <div className="grid grid-cols-3 gap-3">
          {[
            { label: 'FRESH', sub: '< 1 day',  value: fresh,      color: '#00C896', bg: 'rgba(0,200,150,0.05)',   border: 'rgba(0,200,150,0.15)' },
            { label: 'STALE', sub: '1–7 days', value: staleCount, color: '#F5A623', bg: 'rgba(245,166,35,0.05)', border: 'rgba(245,166,35,0.15)' },
            { label: 'AGED',  sub: '> 7 days', value: veryStale,  color: '#FF3B47', bg: 'rgba(255,59,71,0.04)',  border: 'rgba(255,59,71,0.12)'  },
          ].map(({ label, sub, value, color, bg, border }) => (
            <div key={label} className="rounded p-3 text-center" style={{ background: bg, border: `1px solid ${border}` }}>
              <p className="text-2xl font-black tabular-nums" style={{ fontFamily: "'JetBrains Mono', monospace", color }}>
                {value.toLocaleString()}
              </p>
              <p className="text-[9px] font-semibold tracking-widest uppercase mt-1" style={{ fontFamily: "'Chakra Petch', sans-serif", color }}>
                {label}
              </p>
              <p className="text-[9px] mt-0.5" style={{ color: '#3D5872' }}>{sub}</p>
            </div>
          ))}
        </div>
      </div>

      {/* ── Row 3 + 4: Enrichment + Mission Roadmap + System Status ──────── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

        {/* Enrichment */}
        <div className="rounded-lg p-5" style={{ background: '#070E1B', border: '1px solid #111E30' }}>
          <div className="flex items-start justify-between mb-4">
            <div>
              <h3
                className="text-xs font-semibold tracking-widest uppercase"
                style={{ fontFamily: "'Chakra Petch', sans-serif", color: '#3D5872' }}
              >
                FUNDAMENTALS ENRICHMENT
              </h3>
              <p className="mt-0.5 text-[10px]" style={{ color: '#3D5872' }}>
                PE · MktCap · NP QTR · Sales QTR · ROCE
              </p>
            </div>
            <button
              onClick={onEnrich}
              disabled={enriching}
              className="text-[10px] font-semibold tracking-wider px-3 py-1.5 rounded transition-all"
              style={{
                fontFamily: "'Chakra Petch', sans-serif",
                background: enriching ? 'rgba(160,96,255,0.05)' : 'rgba(160,96,255,0.10)',
                border: `1px solid ${enriching ? 'rgba(160,96,255,0.15)' : 'rgba(160,96,255,0.30)'}`,
                color: enriching ? '#6A40A0' : '#B87AFF',
                cursor: enriching ? 'not-allowed' : 'pointer',
              }}
            >
              {enriching ? '⏳ ENRICHING…' : enriched === 0 ? '⚡ ENRICH NOW' : '↻ RE-ENRICH'}
            </button>
          </div>

          {/* Progress bar */}
          <div className="w-full h-1.5 rounded-sm overflow-hidden mb-4" style={{ background: '#0E1828' }}>
            <div
              className="h-full transition-all duration-700"
              style={{ width: `${enrichPct}%`, background: '#A060FF' }}
            />
          </div>

          {enriching && enrichProgress && (
            <p className="text-[10px] mb-3 tabular-nums" style={{ color: '#B87AFF', fontFamily: "'JetBrains Mono', monospace" }}>
              {enrichProgress.done?.toLocaleString()} / {enrichProgress.total?.toLocaleString()} · {enrichProgress.pct}%
            </p>
          )}

          <div className="grid grid-cols-3 gap-2">
            {[
              { label: 'ENRICHED', value: enriched,                color: '#B87AFF', bg: 'rgba(160,96,255,0.06)', border: 'rgba(160,96,255,0.14)' },
              { label: 'PENDING',  value: enrichTotal - enriched,  color: '#7DA4BE', bg: 'rgba(61,88,114,0.06)',  border: 'rgba(61,88,114,0.14)'  },
              { label: 'COVERAGE', value: `${enrichPct}%`,         color: '#B87AFF', bg: 'rgba(160,96,255,0.06)', border: 'rgba(160,96,255,0.14)' },
            ].map(({ label, value, color, bg, border }) => (
              <div key={label} className="rounded p-2.5 text-center" style={{ background: bg, border: `1px solid ${border}` }}>
                <p className="text-xl font-black tabular-nums" style={{ fontFamily: "'JetBrains Mono', monospace", color }}>
                  {typeof value === 'number' ? value.toLocaleString() : value}
                </p>
                <p className="text-[9px] font-semibold tracking-widest uppercase mt-1" style={{ fontFamily: "'Chakra Petch', sans-serif", color }}>
                  {label}
                </p>
              </div>
            ))}
          </div>
        </div>

        {/* System status + Roadmap */}
        <div className="rounded-lg p-5" style={{ background: '#070E1B', border: '1px solid #111E30' }}>
          <h3
            className="text-xs font-semibold tracking-widest uppercase mb-4"
            style={{ fontFamily: "'Chakra Petch', sans-serif", color: '#3D5872' }}
          >
            MISSION ROADMAP
          </h3>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            {[
              { phase: 'P1', weeks: 'Wk 1–3',   label: 'NSE 1500 Universe',      status: 'done' },
              { phase: 'P2', weeks: 'Wk 4–6',   label: 'DuckDB + 5yr OHLCV',     status: 'done' },
              { phase: 'P3', weeks: 'Wk 7–9',   label: '40+ Features + Labels',  status: 'active' },
              { phase: 'P4', weeks: 'Wk 10–12', label: 'XGBoost Models 55%+',    status: 'pending' },
              { phase: 'P5', weeks: 'Wk 13–14', label: 'Walk-fwd + RL Agent',    status: 'pending' },
              { phase: 'P6', weeks: 'Wk 15–16', label: 'Paper → Live ₹10K',      status: 'pending' },
            ].map(({ phase, weeks, label, status }) => (
              <div
                key={phase}
                className="flex items-center gap-3 rounded p-2.5"
                style={{
                  background: status === 'done'   ? 'rgba(0,200,150,0.05)'   :
                               status === 'active' ? 'rgba(245,166,35,0.05)' : 'rgba(17,30,48,0.4)',
                  border: `1px solid ${
                    status === 'done'   ? 'rgba(0,200,150,0.15)'   :
                    status === 'active' ? 'rgba(245,166,35,0.15)'  : 'rgba(17,30,48,0.8)'
                  }`,
                }}
              >
                <span
                  className="text-[9px] font-bold w-5 shrink-0"
                  style={{
                    fontFamily: "'Chakra Petch', sans-serif",
                    color: status === 'done' ? '#00C896' : status === 'active' ? '#F5A623' : '#3D5872',
                  }}
                >
                  {status === 'done' ? '✓' : status === 'active' ? '▶' : '○'}
                </span>
                <div className="min-w-0">
                  <p
                    className="text-[9px] font-semibold tracking-wider"
                    style={{
                      fontFamily: "'Chakra Petch', sans-serif",
                      color: status === 'done' ? '#00C896' : status === 'active' ? '#F5A623' : '#3D5872',
                    }}
                  >
                    {phase} · {weeks}
                  </p>
                  <p
                    className="text-[11px] font-semibold truncate"
                    style={{
                      fontFamily: "'JetBrains Mono', monospace",
                      color: status === 'done' ? '#C8DCF0' : status === 'active' ? '#C8DCF0' : '#4A6478',
                    }}
                  >
                    {label}
                  </p>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* System Status */}
        <SystemStatusWidget isDark={isDark} />
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
          <ErrorCatcher />
          <HomeContent />
        </ToastProvider>
      </AppProvider>
    </ThemeProvider>
  )
}

