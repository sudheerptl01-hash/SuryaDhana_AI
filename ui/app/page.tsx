'use client'

import { useEffect, useState, useCallback } from 'react'
import clsx from 'clsx'
import {
  getDashboardSummary,
  getEnrichmentStatus,
  listStocks,
  screenStocks,
  triggerRefresh,
  getRefreshStatus,
} from '@/lib/api'
import { KPICard } from '@/components/KPICard'
import { StockTable } from '@/components/StockTable'
import { StockDetailModal } from '@/components/StockDetailModal'
import { DataPipeline } from '@/components/DataPipeline'
import { PortfolioSummary } from '@/components/PortfolioSummary'

type Tab = 'overview' | 'stocks' | 'analysis' | 'positions' | 'pipeline'

const FILTERS_INIT = { t1: false, t2: false, t3: false, t4: false, t5: false, t6: false, t7: false, t8: false }

export default function Home() {
  const [view, setView] = useState<Tab>('overview')
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
  const [stocksPage, setStocksPage] = useState(0)
  const [technicalFilters, setTechnicalFilters] = useState(FILTERS_INIT)

  // ── Initial load ──────────────────────────────────────────────────────────
  useEffect(() => {
    Promise.all([getDashboardSummary(), getEnrichmentStatus(), listStocks(0, 100)])
      .then(([dash, enrich, stocksRes]) => {
        setDashboard(dash.data)
        setEnrichment(enrich.data)
        const stocks = stocksRes.data?.stocks || []
        const total = stocksRes.data?.total || stocks.length
        setAllStocks(stocks)
        setDisplayStocks(stocks)
        setTotalStocks(total)
      })
      .catch((err) => console.error('Failed to load dashboard:', err))
      .finally(() => setPageLoading(false))
  }, [])

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
      const res = await screenStocks(filters, 0, 200)
      const results = (res.data?.results || []).map((r: any) => ({
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

  // ── Refresh all data with progress polling ────────────────────────────────
  const handleRefresh = async () => {
    if (refreshing) {
      setShowRefreshPanel(true)
      return
    }
    setRefreshing(true)
    setShowRefreshPanel(true)
    setRefreshStatus(null)
    try {
      await triggerRefresh()

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
              listStocks(0, 100),
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

  const activeFilterCount = Object.values(technicalFilters).filter(Boolean).length
  const displayCount = isFiltered ? filteredTotal : totalStocks

  return (
    <div className="min-h-screen bg-gray-50 text-gray-900">
      {/* ── Header ──────────────────────────────────────────────────────── */}
      <header className="border-b border-gray-200 bg-white/95 backdrop-blur-md sticky top-0 z-40 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center text-xl shadow-md">
              ☀️
            </div>
            <div>
              <h1 className="text-2xl font-black tracking-tight text-gray-900">
                SuryaDhana
              </h1>
              <p className="text-xs text-gray-400 mt-0.5">NSE Quant System · XGBoost + RL</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-emerald-50 border border-emerald-200">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <span className="text-xs font-semibold text-emerald-700">LIVE</span>
            </div>
            <div className="text-xs text-gray-500">
              <span className="text-gray-900 font-bold">{totalStocks}</span> stocks ·{' '}
              <span className="text-gray-900 font-bold">{dashboard?.latest_date || '—'}</span>
            </div>
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
              title="Refresh all stock data from NSE 1000 + Midcap 500"
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

      {/* ── Refresh Progress Panel ──────────────────────────────────────── */}
      {showRefreshPanel && (
        <div className="border-b border-indigo-100 bg-indigo-50">
          <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4">
            <div className="flex items-center justify-between mb-3">
              <div className="flex items-center gap-3">
                {refreshing && <span className="w-3 h-3 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />}
                <span className="text-sm font-bold text-indigo-800">
                  {refreshing ? 'Downloading NSE 1000 + Midcap 500 data…' : 'Refresh complete'}
                </span>
                {refreshStatus && (
                  <span className="text-xs text-indigo-600">
                    {refreshStatus.done} done · {refreshStatus.downloading} downloading · {refreshStatus.pending} pending
                    {refreshStatus.errors > 0 && ` · ${refreshStatus.errors} errors`}
                  </span>
                )}
              </div>
              <button
                onClick={() => setShowRefreshPanel(false)}
                className="text-indigo-400 hover:text-indigo-700 text-sm font-medium"
              >
                Close
              </button>
            </div>
            {/* Progress bar */}
            {refreshStatus?.total > 0 && (
              <div className="w-full h-2 rounded-full bg-indigo-200 overflow-hidden mb-3">
                <div
                  className="h-full bg-indigo-600 rounded-full transition-all duration-500"
                  style={{ width: `${refreshStatus.pct}%` }}
                />
              </div>
            )}
            {/* Per-ticker status grid */}
            {refreshStatus?.tickers && (
              <div className="flex flex-wrap gap-1 max-h-24 overflow-y-auto">
                {Object.entries(refreshStatus.tickers as Record<string, string>).map(([t, status]) => (
                  <span
                    key={t}
                    className={clsx(
                      'text-xs px-1.5 py-0.5 rounded font-mono',
                      status === 'done' ? 'bg-emerald-100 text-emerald-700' :
                      status === 'downloading' ? 'bg-indigo-200 text-indigo-700 animate-pulse' :
                      status === 'error' ? 'bg-rose-100 text-rose-600' :
                      'bg-gray-100 text-gray-400'
                    )}
                  >
                    {t}
                  </span>
                ))}
              </div>
            )}
            {!refreshStatus && refreshing && (
              <p className="text-xs text-indigo-500">Starting download engine… this may take 10–30 minutes for all stocks.</p>
            )}
          </div>
        </div>
      )}

      {/* ── Navigation ──────────────────────────────────────────────────── */}
      <nav className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-4 flex gap-1 overflow-x-auto">
        {([
          { id: 'overview', label: 'Overview', icon: '📊' },
          { id: 'stocks', label: 'Stocks', icon: '📈' },
          { id: 'analysis', label: 'Analysis', icon: '🔬' },
          { id: 'positions', label: 'Portfolio', icon: '💰' },
          { id: 'pipeline', label: 'Pipeline', icon: '⚙️' },
        ] as { id: Tab; label: string; icon: string }[]).map(({ id, label, icon }) => (
          <button
            key={id}
            onClick={() => setView(id)}
            className={clsx(
              'flex items-center gap-1.5 px-4 py-2.5 rounded-lg text-sm font-medium transition-all whitespace-nowrap',
              view === id
                ? 'bg-indigo-600 text-white shadow-md shadow-indigo-200'
                : 'text-gray-500 hover:text-gray-800 hover:bg-gray-100'
            )}
          >
            <span>{icon}</span>
            {label}
            {id === 'stocks' && activeFilterCount > 0 && (
              <span className="ml-1 px-1.5 py-0.5 rounded-full bg-white/30 text-white text-xs font-bold">
                {activeFilterCount}
              </span>
            )}
          </button>
        ))}
      </nav>

      {/* ── Main Content ────────────────────────────────────────────────── */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {pageLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {Array(8).fill(0).map((_, i) => (
              <div key={i} className="h-28 animate-pulse rounded-xl bg-gray-200" />
            ))}
          </div>
        ) : view === 'overview' ? (
          <OverviewTab dashboard={dashboard} enrichment={enrichment} totalStocks={totalStocks} />
        ) : view === 'stocks' ? (
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
          />
        ) : view === 'analysis' ? (
          <AnalysisTab />
        ) : view === 'positions' ? (
          <PortfolioSummary />
        ) : (
          <DataPipeline />
        )}
      </main>

      {/* ── Footer ──────────────────────────────────────────────────────── */}
      <footer className="border-t border-gray-200 bg-white mt-16 py-6">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center text-xs text-gray-400">
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
function OverviewTab({ dashboard, enrichment, totalStocks }: any) {
  const freshnessColor = (dashboard?.days_stale ?? 99) <= 1 ? 'emerald' : (dashboard?.days_stale ?? 99) <= 3 ? 'amber' : 'rose'

  return (
    <div className="space-y-8">
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label="Total Stocks" value={totalStocks} subtext="in universe" color="indigo" icon="📊" />
        <KPICard
          label="Data Freshness"
          value={`${dashboard?.health?.freshness_pct ?? 0}%`}
          subtext="data quality score"
          color={freshnessColor as any}
          icon="📅"
        />
        <KPICard
          label="Latest Bar"
          value={dashboard?.latest_date ?? 'N/A'}
          subtext="most recent trading day"
          color="slate"
          icon="📍"
        />
        <KPICard
          label="Days Stale"
          value={dashboard?.days_stale ?? '—'}
          subtext="since last update"
          color={(dashboard?.days_stale ?? 99) <= 1 ? 'emerald' : 'rose'}
          icon={(dashboard?.days_stale ?? 99) <= 1 ? '✅' : '⚠️'}
        />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <KPICard label="Fundamentals" value={`${enrichment?.with_fundamentals ?? 0}`} subtext="stocks enriched" color="violet" icon="💼" />
        <KPICard label="Dividends" value={`${enrichment?.with_dividends ?? 0}`} subtext="stocks with history" color="cyan" icon="💰" />
        <KPICard label="Splits" value={`${enrichment?.with_splits ?? 0}`} subtext="stocks with history" color="slate" icon="✂️" />
        <KPICard
          label="Coverage"
          value={`${enrichment?.enrichment_coverage_pct ?? 0}%`}
          subtext="fundamental coverage"
          color="violet"
          icon="📋"
        />
      </div>

      {/* System Health Card */}
      <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-3 mb-2">
              <span className="w-3 h-3 rounded-full bg-emerald-500 animate-pulse" />
              <h3 className="text-lg font-bold text-gray-900">
                System Status: <span className="text-indigo-600">{(dashboard?.health?.status ?? 'unknown').toUpperCase()}</span>
              </h3>
            </div>
            <p className="text-gray-500 text-sm">
              {dashboard?.stocks_with_today_data ?? 0} stocks have today's data ·
              Data range: <span className="text-gray-800 font-medium">{dashboard?.data_range?.from}</span>
              {' → '}
              <span className="text-gray-800 font-medium">{dashboard?.data_range?.to}</span>
            </p>
          </div>
          <div className="px-5 py-2 rounded-lg bg-indigo-600 text-white font-bold text-sm shadow-md shadow-indigo-200">
            Phase 1 Complete ✓
          </div>
        </div>
      </div>

      {/* Roadmap */}
      <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
        <h3 className="text-lg font-bold text-gray-900 mb-6">16-Week Roadmap</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
          {[
            { phase: 'Phase 1', weeks: '1–3', label: 'Stock Universe', status: 'done' },
            { phase: 'Phase 2', weeks: '4–6', label: 'DuckDB + ICICI + 5yr Data', status: 'done' },
            { phase: 'Phase 3', weeks: '7–9', label: '40+ Features + Labels', status: 'pending' },
            { phase: 'Phase 4', weeks: '10–12', label: 'XGBoost Models (55%+)', status: 'pending' },
            { phase: 'Phase 5', weeks: '13–14', label: 'Walk-forward + RL Agent', status: 'pending' },
            { phase: 'Phase 6', weeks: '15–16', label: 'Paper → Live ₹10K', status: 'pending' },
          ].map(({ phase, weeks, label, status }) => (
            <div
              key={phase}
              className={clsx(
                'rounded-xl p-4 border',
                status === 'done'
                  ? 'border-emerald-200 bg-emerald-50'
                  : 'border-gray-200 bg-gray-50'
              )}
            >
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-bold text-gray-400">{phase} · Wk {weeks}</span>
                <span className={clsx('text-xs font-bold', status === 'done' ? 'text-emerald-600' : 'text-gray-400')}>
                  {status === 'done' ? '✓ DONE' : '⏸ PENDING'}
                </span>
              </div>
              <p className={clsx('text-sm font-semibold', status === 'done' ? 'text-emerald-800' : 'text-gray-600')}>
                {label}
              </p>
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
  allStocksCount, totalStocks, onFilterChange, onRowClick, onLoadMore,
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
      <div className="rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-bold text-gray-900">
            Minervini Trend Template Filters
            {activeCount > 0 && (
              <span className="ml-2 px-2 py-0.5 rounded-full bg-indigo-600 text-xs font-bold text-white">
                {activeCount} active
              </span>
            )}
          </h3>
          {activeCount > 0 && (
            <button
              onClick={clearAll}
              className="text-xs text-gray-400 hover:text-rose-500 transition-colors font-medium"
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
                  'flex flex-col items-center p-3 rounded-xl border-2 transition-all text-center',
                  active
                    ? 'border-indigo-500 bg-indigo-50 text-indigo-700 shadow-sm'
                    : 'border-gray-200 bg-gray-50 text-gray-500 hover:border-indigo-300 hover:text-indigo-600'
                )}
              >
                <span className={clsx('text-sm font-black', active ? 'text-indigo-600' : '')}>{label}</span>
                <span className="text-xs mt-1 leading-tight opacity-70">{desc}</span>
              </button>
            )
          })}
        </div>
      </div>

      {/* Table */}
      <div className="rounded-2xl border border-gray-200 bg-white overflow-hidden shadow-sm">
        <div className="p-5 border-b border-gray-100 flex items-center justify-between">
          <div>
            <h3 className="text-base font-bold text-gray-900">
              {isFiltered ? 'Screener Results' : 'All Stocks'}
              <span className="ml-2 text-gray-400 font-normal text-sm">
                ({isFiltered ? `${displayCount} matched` : `${allStocksCount} loaded of ${totalStocks}`})
              </span>
            </h3>
            {isFiltered && (
              <p className="text-xs text-indigo-500 mt-0.5">
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
        <StockTable stocks={displayStocks} onRowClick={onRowClick} loading={filterLoading} />
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

// ── Analysis Tab ──────────────────────────────────────────────────────────────
function AnalysisTab() {
  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-gray-200 bg-white p-8 text-center shadow-sm">
        <h2 className="text-2xl font-bold text-gray-900 mb-3">Advanced Analytics</h2>
        <p className="text-gray-500 mb-8">Signal coverage, feature quality, and model metrics will appear here after Phase 3–4.</p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[
            { icon: '📈', title: 'Signal Quality', desc: 'XGBoost model accuracy & AUC', color: 'indigo' },
            { icon: '🎯', title: 'Feature Coverage', desc: '40+ technical indicators per stock', color: 'violet' },
            { icon: '📊', title: 'Label Distribution', desc: '5-day return classification stats', color: 'cyan' },
          ].map(({ icon, title, desc }) => (
            <div key={title} className="rounded-xl border border-gray-200 bg-gray-50 p-6">
              <div className="text-4xl mb-3">{icon}</div>
              <h3 className="font-bold text-gray-900 mb-1">{title}</h3>
              <p className="text-sm text-gray-500">{desc}</p>
              <div className="mt-4 text-xs text-gray-400 font-mono">Phase 4 · Pending</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
