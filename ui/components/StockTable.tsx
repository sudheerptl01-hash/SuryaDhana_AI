'use client'

import clsx from 'clsx'
import { useState, useMemo } from 'react'

interface Stock {
  ticker: string
  company_name?: string | null
  sector_name?: string | null
  index_name?: string
  nifty_bucket?: string | null
  midcap_bucket?: string | null
  cap_category?: string | null
  has_ohlcv?: boolean
  latest_price?: number | null
  price_date?: string | null
  total_rows?: number
  first_date?: string | null
  latest_date?: string | null
  years_of_data?: number
  data_density_pct?: number
  days_since_update?: number | null
  data_quality?: string
  ma50?: number
  ma150?: number
  ma200?: number
  rs_rating?: number
  sepa_stage?: string
  filters?: Record<string, boolean>
  // Financial metrics from stock_metrics table
  cmp?: number | null
  pe_ratio?: number | null
  mktcap_cr?: number | null
  div_yld_pct?: number | null
  np_qtr_cr?: number | null
  qtr_pft_var?: number | null
  sales_qtr_cr?: number | null
  qtr_sal_var?: number | null
  roce_pct?: number | null
}

interface StockTableProps {
  stocks: Stock[]
  onRowClick: (ticker: string) => void
  loading?: boolean
  isDark?: boolean
  watchlist?: string[]
  onWatchToggle?: (ticker: string) => void
}

type SortColumn =
  | 'ticker' | 'price' | 'ma50' | 'rs_rating' | 'density'
  | 'cmp' | 'pe_ratio' | 'mktcap_cr' | 'div_yld_pct'
  | 'np_qtr_cr' | 'sales_qtr_cr' | 'roce_pct'

type SortDir = 'asc' | 'desc'

interface ColFilters {
  ticker: string
  nifty: string
  midcap: string
  capCategory: string
  sector: string
  priceMin: string
  priceMax: string
  quality: string
}

const EMPTY_FILTERS: ColFilters = {
  ticker: '', nifty: '', midcap: '', capCategory: '', sector: '',
  priceMin: '', priceMax: '', quality: '',
}

const CAP_BADGE_COLORS: Record<string, string> = {
  'Large Cap': 'bg-blue-100 text-blue-700',
  'Mid Cap':   'bg-yellow-100 text-yellow-700',
  'Small Cap': 'bg-green-100 text-green-700',
  'Micro Cap': 'bg-gray-100 text-gray-500',
}

const SEPA_COLORS: Record<string, string> = {
  'Stage 3': 'bg-emerald-100 text-emerald-700 border-emerald-200',
  'Stage 2': 'bg-indigo-100 text-indigo-700 border-indigo-200',
  'Stage 4': 'bg-rose-100 text-rose-700 border-rose-200',
  'Stage 1': 'bg-gray-100 text-gray-600 border-gray-200',
}

const QUALITY_DOTS: Record<string, string> = {
  excellent: 'bg-emerald-500',
  good: 'bg-teal-500',
  fair: 'bg-amber-400',
  poor: 'bg-rose-400',
}

function fmt(n: number | null | undefined, decimals = 0): string {
  if (n == null) return '—'
  return n.toLocaleString('en-IN', { maximumFractionDigits: decimals })
}

function TrendArrow({ pct }: { pct?: number | null }) {
  if (pct == null) return null
  const up = pct >= 0
  return (
    <span className={clsx('ml-1 text-xs font-bold', up ? 'text-emerald-600' : 'text-rose-500')}>
      {up ? '▲' : '▼'}{Math.abs(pct).toFixed(1)}%
    </span>
  )
}

export function StockTable({ stocks, onRowClick, loading, isDark = true, watchlist = [], onWatchToggle }: StockTableProps) {
  const [hovered, setHovered] = useState<string | null>(null)
  const [sortCol, setSortCol] = useState<SortColumn>('ticker')
  const [sortDir, setSortDir] = useState<SortDir>('asc')
  const [showFilters, setShowFilters] = useState(false)
  const [filters, setFilters] = useState<ColFilters>(EMPTY_FILTERS)

  const toggleSort = (col: SortColumn) => {
    if (sortCol === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortCol(col); setSortDir('asc') }
  }

  const SortIcon = ({ col }: { col: SortColumn }) =>
    <span className={clsx('ml-1', sortCol === col ? 'text-indigo-600' : 'text-gray-300')}>
      {sortCol === col ? (sortDir === 'asc' ? '↑' : '↓') : '↕'}
    </span>

  const displayed = useMemo(() => {
    let r = [...stocks]

    // Apply column filters
    if (filters.ticker) r = r.filter(s => s.ticker.toLowerCase().includes(filters.ticker.toLowerCase()))
    if (filters.nifty)  r = r.filter(s => s.nifty_bucket === filters.nifty)
    if (filters.midcap) r = r.filter(s => s.midcap_bucket === filters.midcap)
    if (filters.capCategory) r = r.filter(s => s.cap_category === filters.capCategory)
    if (filters.sector) r = r.filter(s => (s.sector_name || '').toLowerCase().includes(filters.sector.toLowerCase()))
    if (filters.priceMin) r = r.filter(s => (s.cmp ?? s.latest_price ?? 0) >= parseFloat(filters.priceMin))
    if (filters.priceMax) r = r.filter(s => (s.cmp ?? s.latest_price ?? 0) <= parseFloat(filters.priceMax))
    if (filters.quality) r = r.filter(s => s.data_quality === filters.quality)

    // Sort
    r.sort((a, b) => {
      let av: number | string = 0, bv: number | string = 0
      switch (sortCol) {
        case 'ticker':     av = a.ticker;                  bv = b.ticker; break
        case 'price':      av = a.cmp ?? a.latest_price ?? 0; bv = b.cmp ?? b.latest_price ?? 0; break
        case 'ma50':       av = a.ma50 ?? 0;               bv = b.ma50 ?? 0; break
        case 'rs_rating':  av = a.rs_rating ?? 0;          bv = b.rs_rating ?? 0; break
        case 'density':    av = a.data_density_pct ?? 0;   bv = b.data_density_pct ?? 0; break
        case 'cmp':        av = a.cmp ?? 0;                bv = b.cmp ?? 0; break
        case 'pe_ratio':   av = a.pe_ratio ?? 0;           bv = b.pe_ratio ?? 0; break
        case 'mktcap_cr':  av = a.mktcap_cr ?? 0;          bv = b.mktcap_cr ?? 0; break
        case 'div_yld_pct':av = a.div_yld_pct ?? 0;       bv = b.div_yld_pct ?? 0; break
        case 'np_qtr_cr':  av = a.np_qtr_cr ?? 0;         bv = b.np_qtr_cr ?? 0; break
        case 'sales_qtr_cr':av = a.sales_qtr_cr ?? 0;     bv = b.sales_qtr_cr ?? 0; break
        case 'roce_pct':   av = a.roce_pct ?? 0;           bv = b.roce_pct ?? 0; break
      }
      if (typeof av === 'string') return sortDir === 'asc' ? av.localeCompare(bv as string) : (bv as string).localeCompare(av)
      return sortDir === 'asc' ? ((av as number) - (bv as number)) : ((bv as number) - (av as number))
    })

    return r
  }, [stocks, sortCol, sortDir, filters])

  if (loading) {
    return (
      <div className="space-y-2 p-4">
        {Array(10).fill(0).map((_, i) => (
          <div key={i} className={clsx('h-11 animate-pulse rounded-lg', isDark ? 'bg-slate-700' : 'bg-gray-100')} />
        ))}
      </div>
    )
  }

  const activeCount = Object.values(filters).filter(Boolean).length

  return (
    <div className="space-y-3">
      {/* Filter toggle */}
      <div className="flex items-center gap-3 px-4">
        <button
          onClick={() => setShowFilters(v => !v)}
          className={clsx(
            'flex items-center gap-2 text-xs font-semibold px-3 py-1.5 rounded-lg border transition-colors',
            activeCount > 0
              ? isDark ? 'bg-amber-950/40 border-amber-700/50 text-amber-300' : 'bg-indigo-50 border-indigo-200 text-indigo-700'
              : isDark ? 'bg-slate-800/50 border-slate-700/50 text-slate-400 hover:border-slate-600' : 'bg-gray-50 border-gray-200 text-gray-600 hover:border-gray-300'
          )}
        >
          🔍 Column Filters
          {activeCount > 0 && (
            <span className={clsx('px-1.5 rounded-full text-white text-xs font-bold', isDark ? 'bg-amber-600/80' : 'bg-indigo-600')}>{activeCount}</span>
          )}
        </button>
        {activeCount > 0 && (
          <button onClick={() => setFilters(EMPTY_FILTERS)} className={clsx('text-xs font-medium', isDark ? 'text-slate-400 hover:text-rose-400' : 'text-gray-400 hover:text-rose-500')}>
            Clear all
          </button>
        )}
        <span className={clsx('ml-auto text-xs', isDark ? 'text-slate-400' : 'text-gray-400')}>
          {displayed.length} of {stocks.length} stocks
        </span>
      </div>

      {/* Filter panel */}
      {showFilters && (
        <div className={clsx('mx-4 p-4 rounded-xl border', isDark ? 'bg-slate-800/50 border-slate-700/50' : 'bg-gray-50 border-gray-200')}>
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2">
            <input
              type="text" placeholder="Ticker search"
              value={filters.ticker}
              onChange={e => setFilters(f => ({ ...f, ticker: e.target.value }))}
              className={clsx('px-2 py-1.5 text-xs rounded focus:ring-1 focus:border-transparent', isDark ? 'border border-slate-600 bg-slate-700 text-slate-200 focus:ring-amber-500' : 'border border-gray-300 bg-white focus:ring-indigo-400')}
            />
            <select
              value={filters.nifty}
              onChange={e => setFilters(f => ({ ...f, nifty: e.target.value }))}
              className={clsx('px-2 py-1.5 text-xs rounded focus:ring-1', isDark ? 'border border-slate-600 bg-slate-700 text-slate-200 focus:ring-amber-500' : 'border border-gray-300 bg-white focus:ring-indigo-400')}
            >
              <option value="">All Nifty</option>
              <option value="1000">Nifty 1000</option>
              <option value="500">Nifty 500</option>
              <option value="200">Nifty 200</option>
              <option value="100">Nifty 100</option>
              <option value="50">Nifty 50</option>
            </select>
            <select
              value={filters.midcap}
              onChange={e => setFilters(f => ({ ...f, midcap: e.target.value }))}
              className={clsx('px-2 py-1.5 text-xs rounded focus:ring-1', isDark ? 'border border-slate-600 bg-slate-700 text-slate-200 focus:ring-amber-500' : 'border border-gray-300 bg-white focus:ring-indigo-400')}
            >
              <option value="">All Midcap</option>
              <option value="300">Midcap 300</option>
              <option value="150">Midcap 150</option>
              <option value="50">Midcap 50</option>
            </select>
            <select
              value={filters.capCategory}
              onChange={e => setFilters(f => ({ ...f, capCategory: e.target.value }))}
              className={clsx('px-2 py-1.5 text-xs rounded focus:ring-1', isDark ? 'border border-slate-600 bg-slate-700 text-slate-200 focus:ring-amber-500' : 'border border-gray-300 bg-white focus:ring-indigo-400')}
            >
              <option value="">All Cap Types</option>
              <option value="Large Cap">Large Cap ≥₹20K Cr</option>
              <option value="Mid Cap">Mid Cap ≥₹5K Cr</option>
              <option value="Small Cap">Small Cap ≥₹500 Cr</option>
              <option value="Micro Cap">Micro Cap ≥₹100 Cr</option>
            </select>
            <input
              type="text" placeholder="Sector"
              value={filters.sector}
              onChange={e => setFilters(f => ({ ...f, sector: e.target.value }))}
              className={clsx('px-2 py-1.5 text-xs rounded focus:ring-1', isDark ? 'border border-slate-600 bg-slate-700 text-slate-200 focus:ring-amber-500' : 'border border-gray-300 bg-white focus:ring-indigo-400')}
            />
            <input
              type="number" placeholder="Price min ₹"
              value={filters.priceMin}
              onChange={e => setFilters(f => ({ ...f, priceMin: e.target.value }))}
              className={clsx('px-2 py-1.5 text-xs rounded focus:ring-1', isDark ? 'border border-slate-600 bg-slate-700 text-slate-200 focus:ring-amber-500' : 'border border-gray-300 bg-white focus:ring-indigo-400')}
            />
            <input
              type="number" placeholder="Price max ₹"
              value={filters.priceMax}
              onChange={e => setFilters(f => ({ ...f, priceMax: e.target.value }))}
              className={clsx('px-2 py-1.5 text-xs rounded focus:ring-1', isDark ? 'border border-slate-600 bg-slate-700 text-slate-200 focus:ring-amber-500' : 'border border-gray-300 bg-white focus:ring-indigo-400')}
            />
            <select
              value={filters.quality}
              onChange={e => setFilters(f => ({ ...f, quality: e.target.value }))}
              className={clsx('px-2 py-1.5 text-xs rounded focus:ring-1', isDark ? 'border border-slate-600 bg-slate-700 text-slate-200 focus:ring-amber-500' : 'border border-gray-300 bg-white focus:ring-indigo-400')}
            >
              <option value="">All Quality</option>
              <option value="excellent">Excellent</option>
              <option value="good">Good</option>
              <option value="fair">Fair</option>
              <option value="poor">Poor</option>
            </select>
          </div>
        </div>
      )}

      {/* Table */}
      {displayed.length === 0 ? (
        <div className="py-16 text-center">
          <div className="text-4xl mb-3 opacity-30">📭</div>
          <p className={clsx('font-medium', isDark ? 'text-slate-400' : 'text-gray-500')}>No stocks match the selected filters</p>
          <p className={clsx('text-sm mt-1', isDark ? 'text-slate-500' : 'text-gray-400')}>Try adjusting your search criteria</p>
        </div>
      ) : (
        <div className="overflow-x-auto overflow-y-auto max-h-[calc(100vh-320px)] px-4">
          <table className="w-full text-sm min-w-[1400px]">
            <thead className="sticky top-0 z-10">
              <tr className={clsx('border-b', isDark ? 'border-slate-700/50 bg-slate-800/50' : 'border-gray-200 bg-gray-50')}>
                {/* Static columns */}
                <th onClick={() => toggleSort('ticker')}
                  className={clsx('px-3 py-3 text-left text-xs font-bold uppercase tracking-wider cursor-pointer whitespace-nowrap', isDark ? 'text-slate-400 hover:bg-slate-700/30' : 'text-gray-500 hover:bg-gray-100')}>
                  Ticker <SortIcon col="ticker" />
                </th>
                <th className={clsx('px-3 py-3 text-left text-xs font-bold uppercase tracking-wider whitespace-nowrap', isDark ? 'text-slate-400' : 'text-gray-500')}>Company</th>
                <th className={clsx('px-3 py-3 text-center text-xs font-bold uppercase tracking-wider whitespace-nowrap', isDark ? 'text-slate-400' : 'text-gray-500')}>Nifty</th>
                <th className={clsx('px-3 py-3 text-center text-xs font-bold uppercase tracking-wider whitespace-nowrap', isDark ? 'text-slate-400' : 'text-gray-500')}>Midcap</th>
                <th className={clsx('px-3 py-3 text-center text-xs font-bold uppercase tracking-wider whitespace-nowrap', isDark ? 'text-slate-400' : 'text-gray-500')}>Cap Type</th>

                {/* Financial columns — sortable */}
                <th onClick={() => toggleSort('cmp')}
                  className={clsx('px-3 py-3 text-right text-xs font-bold uppercase tracking-wider cursor-pointer whitespace-nowrap', isDark ? 'text-slate-400 hover:bg-slate-700/30' : 'text-gray-500 hover:bg-gray-100')}>
                  CMP ₹ <SortIcon col="cmp" />
                </th>
                <th onClick={() => toggleSort('pe_ratio')}
                  className={clsx('px-3 py-3 text-right text-xs font-bold uppercase tracking-wider cursor-pointer whitespace-nowrap', isDark ? 'text-slate-400 hover:bg-slate-700/30' : 'text-gray-500 hover:bg-gray-100')}>
                  P/E <SortIcon col="pe_ratio" />
                </th>
                <th onClick={() => toggleSort('mktcap_cr')}
                  className={clsx('px-3 py-3 text-right text-xs font-bold uppercase tracking-wider cursor-pointer whitespace-nowrap', isDark ? 'text-slate-400 hover:bg-slate-700/30' : 'text-gray-500 hover:bg-gray-100')}>
                  Mkt Cap Cr <SortIcon col="mktcap_cr" />
                </th>
                <th onClick={() => toggleSort('div_yld_pct')}
                  className={clsx('px-3 py-3 text-center text-xs font-bold uppercase tracking-wider cursor-pointer whitespace-nowrap', isDark ? 'text-slate-400 hover:bg-slate-700/30' : 'text-gray-500 hover:bg-gray-100')}>
                  Div Yld% <SortIcon col="div_yld_pct" />
                </th>
                <th onClick={() => toggleSort('np_qtr_cr')}
                  className={clsx('px-3 py-3 text-right text-xs font-bold uppercase tracking-wider cursor-pointer whitespace-nowrap', isDark ? 'text-slate-400 hover:bg-slate-700/30' : 'text-gray-500 hover:bg-gray-100')}>
                  NP Qtr Cr <SortIcon col="np_qtr_cr" />
                </th>
                <th onClick={() => toggleSort('sales_qtr_cr')}
                  className={clsx('px-3 py-3 text-right text-xs font-bold uppercase tracking-wider cursor-pointer whitespace-nowrap', isDark ? 'text-slate-400 hover:bg-slate-700/30' : 'text-gray-500 hover:bg-gray-100')}>
                  Sales Qtr Cr <SortIcon col="sales_qtr_cr" />
                </th>
                <th onClick={() => toggleSort('roce_pct')}
                  className={clsx('px-3 py-3 text-right text-xs font-bold uppercase tracking-wider cursor-pointer whitespace-nowrap', isDark ? 'text-slate-400 hover:bg-slate-700/30' : 'text-gray-500 hover:bg-gray-100')}>
                  ROCE% <SortIcon col="roce_pct" />
                </th>

                {/* Data quality columns */}
                <th onClick={() => toggleSort('density')}
                  className={clsx('px-3 py-3 text-left text-xs font-bold uppercase tracking-wider cursor-pointer whitespace-nowrap', isDark ? 'text-slate-400 hover:bg-slate-700/30' : 'text-gray-500 hover:bg-gray-100')}>
                  Data% <SortIcon col="density" />
                </th>
                <th className={clsx('px-3 py-3 text-center text-xs font-bold uppercase tracking-wider whitespace-nowrap', isDark ? 'text-slate-400' : 'text-gray-500')}>Health</th>
                {onWatchToggle && (
                  <th className={clsx('px-3 py-3 text-center text-xs font-bold uppercase tracking-wider whitespace-nowrap', isDark ? 'text-slate-400' : 'text-gray-500')}>Watch</th>
                )}
              </tr>
            </thead>
            <tbody className={clsx('divide-y', isDark ? 'divide-slate-700/50' : 'divide-gray-200')}>
              {displayed.map((stock, idx) => {
                const sepaKey   = stock.sepa_stage?.split(':')[0]?.trim() ?? ''
                const sepaColor = SEPA_COLORS[sepaKey] ?? 'bg-gray-100 text-gray-500 border-gray-200'
                const qualityDot = stock.has_ohlcv === false ? 'bg-gray-200' : (QUALITY_DOTS[stock.data_quality ?? ''] ?? 'bg-gray-300')
                const displayPrice = stock.cmp ?? stock.latest_price
                const isEvenRow = idx % 2 === 0

                return (
                  <tr
                    key={stock.ticker}
                    onClick={() => onRowClick(stock.ticker)}
                    onMouseEnter={() => setHovered(stock.ticker)}
                    onMouseLeave={() => setHovered(null)}
                    className={clsx(
                      'cursor-pointer transition-colors',
                      isDark && (
                        hovered === stock.ticker
                          ? 'bg-amber-500/20 shadow-md shadow-amber-500/10'
                          : isEvenRow ? 'bg-slate-800/20' : 'bg-slate-900/10'
                      ),
                      !isDark && (
                        hovered === stock.ticker
                          ? 'bg-indigo-50'
                          : isEvenRow ? 'bg-gray-50' : 'bg-white'
                      )
                    )}
                  >
                    {/* Ticker */}
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <div className={clsx('w-2 h-2 rounded-full flex-shrink-0', qualityDot)} />
                        <span className={clsx('font-black', isDark ? 'text-slate-100' : 'text-gray-900')}>{stock.ticker}</span>
                      </div>
                    </td>

                    {/* Company name */}
                    <td className="px-3 py-2.5 max-w-[180px]">
                      <span className={clsx('text-xs truncate block', isDark ? 'text-slate-300' : 'text-gray-600')} title={stock.company_name ?? ''}>
                        {stock.company_name ?? <span className={isDark ? 'text-slate-500' : 'text-gray-300'}>—</span>}
                      </span>
                      {stock.sector_name && (
                        <span className={clsx('text-[10px]', isDark ? 'text-slate-400' : 'text-gray-400')}>{stock.sector_name}</span>
                      )}
                    </td>

                    {/* Nifty bucket */}
                    <td className="px-3 py-2.5 text-center">
                      <span className={clsx(
                        'inline-block min-w-[36px] rounded-lg px-2 py-0.5 text-xs font-bold',
                        stock.nifty_bucket ? 'bg-indigo-100 text-indigo-700' : 'bg-gray-100 text-gray-400'
                      )}>
                        {stock.nifty_bucket ?? '—'}
                      </span>
                    </td>

                    {/* Midcap bucket */}
                    <td className="px-3 py-2.5 text-center">
                      <span className={clsx(
                        'inline-block min-w-[36px] rounded-lg px-2 py-0.5 text-xs font-bold',
                        stock.midcap_bucket ? 'bg-amber-100 text-amber-700' : 'bg-gray-100 text-gray-400'
                      )}>
                        {stock.midcap_bucket ?? '—'}
                      </span>
                    </td>

                    {/* Cap Category */}
                    <td className="px-3 py-2.5 text-center">
                      {stock.cap_category ? (
                        <span className={clsx(
                          'inline-block rounded-lg px-2 py-0.5 text-xs font-semibold whitespace-nowrap',
                          CAP_BADGE_COLORS[stock.cap_category] ?? 'bg-gray-100 text-gray-500'
                        )}>
                          {stock.cap_category}
                        </span>
                      ) : <span className="text-gray-300 text-xs">—</span>}
                    </td>

                    {/* CMP ₹ */}
                    <td className="px-3 py-2.5 text-right">
                      <span className={clsx('font-semibold', isDark ? 'text-slate-200' : 'text-gray-800')}>
                        {displayPrice != null ? `₹${fmt(displayPrice, 2)}` : '—'}
                      </span>
                    </td>

                    {/* P/E */}
                    <td className="px-3 py-2.5 text-right">
                      {stock.pe_ratio != null ? (
                        <span className={clsx('font-semibold', stock.pe_ratio < 20 ? 'text-emerald-600' : stock.pe_ratio > 50 ? 'text-rose-500' : isDark ? 'text-slate-300' : 'text-gray-700')}>
                          {fmt(stock.pe_ratio, 1)}
                        </span>
                      ) : <span className={isDark ? 'text-slate-500' : 'text-gray-300'}>—</span>}
                    </td>

                    {/* Market Cap */}
                    <td className={clsx('px-3 py-2.5 text-right text-xs', isDark ? 'text-slate-300' : 'text-gray-700')}>
                      {stock.mktcap_cr != null ? fmt(Math.round(stock.mktcap_cr)) : <span className={isDark ? 'text-slate-500' : 'text-gray-300'}>—</span>}
                    </td>

                    {/* Div Yield */}
                    <td className="px-3 py-2.5 text-center">
                      {stock.div_yld_pct != null && stock.div_yld_pct > 0 ? (
                        <span className="text-xs font-semibold text-teal-600">{fmt(stock.div_yld_pct, 2)}%</span>
                      ) : <span className={clsx('text-xs', isDark ? 'text-slate-500' : 'text-gray-300')}>—</span>}
                    </td>

                    {/* NP Quarter Cr */}
                    <td className="px-3 py-2.5 text-right">
                      {stock.np_qtr_cr != null ? (
                        <span className={clsx('text-xs', stock.np_qtr_cr >= 0 ? (isDark ? 'text-slate-300' : 'text-gray-700') : 'text-rose-500')}>
                          {fmt(stock.np_qtr_cr, 0)}
                          <TrendArrow pct={stock.qtr_pft_var} />
                        </span>
                      ) : <span className={clsx('text-xs', isDark ? 'text-slate-500' : 'text-gray-300')}>—</span>}
                    </td>

                    {/* Sales Quarter Cr */}
                    <td className="px-3 py-2.5 text-right">
                      {stock.sales_qtr_cr != null ? (
                        <span className={clsx('text-xs', isDark ? 'text-slate-300' : 'text-gray-700')}>
                          {fmt(stock.sales_qtr_cr, 0)}
                          <TrendArrow pct={stock.qtr_sal_var} />
                        </span>
                      ) : <span className={clsx('text-xs', isDark ? 'text-slate-500' : 'text-gray-300')}>—</span>}
                    </td>

                    {/* ROCE % */}
                    <td className="px-3 py-2.5 text-right">
                      {stock.roce_pct != null ? (
                        <span className={clsx('text-xs font-semibold', stock.roce_pct >= 15 ? 'text-emerald-600' : stock.roce_pct < 5 ? 'text-rose-500' : isDark ? 'text-slate-300' : 'text-gray-600')}>
                          {fmt(stock.roce_pct, 1)}%
                        </span>
                      ) : <span className={clsx('text-xs', isDark ? 'text-slate-500' : 'text-gray-300')}>—</span>}
                    </td>

                    {/* Data density bar */}
                    <td className="px-3 py-2.5">
                      {stock.has_ohlcv === false ? (
                        <span className={clsx('text-[10px] font-medium', isDark ? 'text-slate-500' : 'text-gray-300')}>No data</span>
                      ) : (
                        <div className="flex items-center gap-1.5 min-w-[70px]">
                          <div className={clsx('h-1.5 w-14 rounded-full overflow-hidden', isDark ? 'bg-slate-700/50' : 'bg-gray-200')}>
                            <div
                              className={clsx('h-full rounded-full',
                                (stock.data_density_pct ?? 0) >= 95 ? 'bg-emerald-500' :
                                (stock.data_density_pct ?? 0) >= 85 ? 'bg-teal-500' :
                                (stock.data_density_pct ?? 0) >= 70 ? 'bg-amber-400' : 'bg-rose-400'
                              )}
                              style={{ width: `${Math.min(100, stock.data_density_pct ?? 0)}%` }}
                            />
                          </div>
                          <span className={clsx('text-xs tabular-nums', isDark ? 'text-slate-400' : 'text-gray-400')}>{(stock.data_density_pct ?? 0).toFixed(0)}%</span>
                        </div>
                      )}
                    </td>

                    {/* Health dot */}
                    <td className="px-3 py-2.5 text-center">
                      <div
                        className={clsx('w-3 h-3 rounded-full mx-auto', qualityDot)}
                        title={stock.has_ohlcv === false ? 'No price data' : (stock.data_quality ?? '')}
                      />
                    </td>

                    {/* Watchlist toggle */}
                    {onWatchToggle && (
                      <td className="px-3 py-2.5 text-center" onClick={e => e.stopPropagation()}>
                        <button
                          onClick={() => onWatchToggle(stock.ticker)}
                          title={watchlist.includes(stock.ticker) ? 'Remove from watchlist' : 'Add to watchlist'}
                          className={clsx(
                            'text-base transition-transform hover:scale-125',
                            watchlist.includes(stock.ticker) ? 'text-amber-400' : isDark ? 'text-slate-600 hover:text-amber-500' : 'text-gray-300 hover:text-amber-500'
                          )}
                        >
                          {watchlist.includes(stock.ticker) ? '★' : '☆'}
                        </button>
                      </td>
                    )}
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
