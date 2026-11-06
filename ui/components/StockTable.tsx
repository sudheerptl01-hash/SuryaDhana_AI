'use client'

/**
 * EQS stock table (up to the whole 1,500-stock universe).
 *
 * Rendering cost (C2-performance-01): every row is a memoized <StockRow> that receives only its own values
 * (its live LTP, flash state, watched flag, next event, avoid flag) and stable callbacks, so a NIFTY tick, the
 * 30 s data-service status poll, a watchlist toggle or a parent re-render re-renders only the rows whose own
 * values changed. Row hover is pure CSS (it used to be React state on the whole table, re-rendering all
 * 1,500 rows for every row the mouse crossed). Flashes are tracked only for tickers in this table, so index
 * ticks (NIFTY) no longer re-render it. Sorting, filtering, clicks and the watch toggle are unchanged.
 *
 * Incremental mount: the first FIRST_ROWS rows render with the page (a screenful and more), the rest are
 * appended in CHUNK-row transitions right after, so the table shows at once instead of after one 1,500-row
 * render + table layout (≈1.1 s in WebKit). Within about a second every row is in the DOM, exactly as before.
 */
import clsx from 'clsx'
import { memo, startTransition, useCallback, useState, useMemo, useEffect, useRef } from 'react'
import { useLiveQuotes as useMonitorQuotes } from '@/context/AppContext'
import { useLiveQuotes } from '@/lib/liveQuotes'
import { daysUntil, useCorpEvents, useResultsAvoid } from '@/lib/useCorpEvents'
import type { CorpEvent, RecentResult } from '@/lib/api'
import { AvoidFlag, BadgeChip, EventBadge, SourceChip, T, fmtFixed } from '@/components/terminal'
import { eqsLegend, eqsPrice, shownValuation, valuationNote, type ValuationBasis } from '@/components/marketPagesModel'
import { istDateISO } from '@/lib/format'
import { createFlashClock } from '@/components/flashClock'
import { hiddenColumnsCue, hiddenHeaders } from '@/components/deskLayout'

/** live program: how many of the first rows (current sort / filter) carry a live NSE price */
const LIVE_ROWS = 60
/** incremental mount: rows rendered with the page, then rows appended per transition (see the header) */
const FIRST_ROWS = 60
const CHUNK = 240

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
  // M07 / m076–m078 (ui-api routers/stocks.py eqs_valuation): where each number came from
  cmp_basis?: 'nse_close' | 'none'
  cmp_date?: string | null
  snapshot_cmp?: number | null
  valuation_basis?: ValuationBasis
  quarter_basis?: 'filings' | 'snapshot' | 'etf' | 'none'
  div_basis?: 'snapshot_rebased' | 'withheld' | 'etf' | 'none'
  qtr_period?: string | null
  qtr_turn?: string | null
  instrument?: 'EQ' | 'ETF'
  etf_underlying?: string | null
  cap_rank?: number | null
  cap_sebi?: 'Large' | 'Mid' | 'Small' | null
  metrics_as_of?: string | null
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
  capCategory: string
  sector: string
  priceMin: string
  priceMax: string
  quality: string
}

const EMPTY_FILTERS: ColFilters = {
  ticker: '', nifty: '', capCategory: '', sector: '',
  priceMin: '', priceMax: '', quality: '',
}

// m077: SEBI-style buckets by market-cap rank (1–100 large, 101–250 mid); neutral tones (context, not a verdict)
const CAP_BADGE_COLORS: Record<string, string> = {
  Large: 'text-[var(--t-text)]',
  Mid:   'text-[var(--t-muted)]',
  Small: 'text-[var(--t-dim)]',
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

type Flash = 'up' | 'down' | null
const NO_FLASH: Record<string, Flash> = {}

/** Today's IST date, re-read every minute: memoized rows re-render their 'in 1d' event badges once a day (RUP-09). */
function useIstDay(): string {
  const [day, setDay] = useState(() => istDateISO())
  useEffect(() => {
    const id = setInterval(() => { const d = istDateISO(); setDay(prev => (prev === d ? prev : d)) }, 60_000)
    return () => clearInterval(id)
  }, [])
  return day
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
  const events = useCorpEvents()
  const avoid = useResultsAvoid()
  const [sortCol, setSortCol]       = useState<SortColumn>('ticker')
  const [sortDir, setSortDir]       = useState<SortDir>('asc')
  const [showFilters, setShowFilters] = useState(false)
  const [filters, setFilters]       = useState<ColFilters>(EMPTY_FILTERS)
  // m078: ETFs are funds, not companies: hidden by default, one click shows them
  const [showEtfs, setShowEtfs]     = useState(false)
  const etfCount = useMemo(() => stocks.filter(s => s.instrument === 'ETF').length, [stocks])
  const legend = useMemo(() => eqsLegend(stocks), [stocks])

  // ── Live quote overlay ──────────────────────────────────────────────────────
  const { liveQuotes } = useMonitorQuotes()
  // Map of ticker → 'up' | 'down' | null for flash animation
  const [flashMap, setFlashMap]     = useState<Record<string, Flash>>(NO_FLASH)
  const prevPrices                  = useRef<Record<string, number>>({})
  // only this table's tickers flash: an index tick (NIFTY) must not re-render 1,500 rows
  const tickers = useMemo(() => new Set(stocks.map(s => s.ticker)), [stocks])

  // RUP-04: one pending clear per symbol (components/flashClock.ts). The old per-batch timer was cancelled by the
  // next tick of ANY symbol (effect cleanup), leaving earlier cells tinted until they ticked again.
  const flashClock = useMemo(() => createFlashClock(sym => setFlashMap(prev => (prev[sym] == null ? prev : { ...prev, [sym]: null }))), [])
  useEffect(() => () => flashClock.dispose(), [flashClock])
  useEffect(() => {
    if (!liveQuotes) return
    const newFlashes: Record<string, 'up' | 'down'> = {}

    Object.entries(liveQuotes).forEach(([sym, q]) => {
      const curr = q?.ltp
      if (curr === undefined) return
      if (!tickers.has(sym)) return
      const prev = prevPrices.current[sym]
      if (prev !== undefined && curr !== prev) {
        newFlashes[sym] = curr > prev ? 'up' : 'down'
      }
      prevPrices.current[sym] = curr
    })

    if (Object.keys(newFlashes).length === 0) return

    setFlashMap(prev => ({ ...prev, ...newFlashes }))
    for (const sym of Object.keys(newFlashes)) flashClock.flashed(sym)
  }, [liveQuotes, tickers, flashClock])
  const today = useIstDay()

  // stable callbacks for the memoized rows (the page passes fresh inline arrows on every render)
  const rowClickRef = useRef(onRowClick)
  const watchToggleRef = useRef(onWatchToggle)
  useEffect(() => { rowClickRef.current = onRowClick; watchToggleRef.current = onWatchToggle })
  const handleRowClick = useCallback((ticker: string) => rowClickRef.current(ticker), [])
  const handleWatchToggle = useCallback((ticker: string) => watchToggleRef.current?.(ticker), [])
  const watched = useMemo(() => new Set(watchlist), [watchlist])
  const showWatch = !!onWatchToggle

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
    if (!showEtfs) r = r.filter(s => s.instrument !== 'ETF')
    if (filters.nifty)  r = r.filter(s => s.nifty_bucket === filters.nifty)
    if (filters.capCategory) r = r.filter(s => s.cap_sebi === filters.capCategory)
    if (filters.sector) r = r.filter(s => (s.sector_name || '').toLowerCase().includes(filters.sector.toLowerCase()))
    if (filters.priceMin) r = r.filter(s => (eqsPrice(s) ?? 0) >= parseFloat(filters.priceMin))
    if (filters.priceMax) r = r.filter(s => (eqsPrice(s) ?? 0) <= parseFloat(filters.priceMax))
    if (filters.quality) r = r.filter(s => s.data_quality === filters.quality)

    // Sort
    r.sort((a, b) => {
      let av: number | string = 0, bv: number | string = 0
      switch (sortCol) {
        case 'ticker':     av = a.ticker;                  bv = b.ticker; break
        case 'price':      av = eqsPrice(a) ?? 0; bv = eqsPrice(b) ?? 0; break
        case 'ma50':       av = a.ma50 ?? 0;               bv = b.ma50 ?? 0; break
        case 'rs_rating':  av = a.rs_rating ?? 0;          bv = b.rs_rating ?? 0; break
        case 'density':    av = a.data_density_pct ?? 0;   bv = b.data_density_pct ?? 0; break
        case 'cmp':        av = eqsPrice(a) ?? 0;          bv = eqsPrice(b) ?? 0; break
        case 'pe_ratio':   av = shownValuation(a, 'pe_ratio') ?? 0;    bv = shownValuation(b, 'pe_ratio') ?? 0; break
        case 'mktcap_cr':  av = shownValuation(a, 'mktcap_cr') ?? 0;   bv = shownValuation(b, 'mktcap_cr') ?? 0; break
        case 'div_yld_pct':av = shownValuation(a, 'div_yld_pct') ?? 0; bv = shownValuation(b, 'div_yld_pct') ?? 0; break
        case 'np_qtr_cr':  av = a.np_qtr_cr ?? 0;         bv = b.np_qtr_cr ?? 0; break
        case 'sales_qtr_cr':av = a.sales_qtr_cr ?? 0;     bv = b.sales_qtr_cr ?? 0; break
        case 'roce_pct':   av = a.roce_pct ?? 0;           bv = b.roce_pct ?? 0; break
      }
      if (typeof av === 'string') return sortDir === 'asc' ? av.localeCompare(bv as string) : (bv as string).localeCompare(av)
      return sortDir === 'asc' ? ((av as number) - (bv as number)) : ((bv as number) - (av as number))
    })

    return r
  }, [stocks, sortCol, sortDir, filters, showEtfs])

  // incremental mount (see the header): grow the rendered row count in transitions until every row is in. RUP-09: a
  // new result set (filter, sort, screener, reload) starts again from a screenful, in the same render, instead of
  // rendering up to 1,500 rows in one synchronous pass
  const [grow, setGrow] = useState<{ of: Stock[]; n: number }>(() => ({ of: displayed, n: FIRST_ROWS }))
  if (grow.of !== displayed) setGrow({ of: displayed, n: FIRST_ROWS })
  const limit = grow.of === displayed ? grow.n : FIRST_ROWS
  useEffect(() => {
    if (limit >= displayed.length) return
    const id = setTimeout(() => startTransition(() => setGrow(g => (g.of === displayed ? { of: g.of, n: g.n + CHUNK } : g))), 16)
    return () => clearTimeout(id)
  }, [limit, displayed])
  const shown = limit >= displayed.length ? displayed : displayed.slice(0, limit)
  // live program (reports/live_nse): the CMP of the first LIVE_ROWS rows in the current sort / filter (a screenful and
  // more) from the live NSE quote service (Breeze websocket → NSE ≈ 1 min → the last close; never Yahoo) every 5 s;
  // the rest keep the stored close (EOD), and the column header's chip says which
  const liveSyms = useMemo(() => shown.slice(0, LIVE_ROWS).map(s => s.ticker), [shown])
  const liveEq = useLiveQuotes(liveSyms, { intervalMs: 5_000 })
  const livePx = (t: string): number | undefined => { const q = liveEq.quotes[t.toUpperCase()]; return q && q.price != null && q.state !== 'unavailable' ? q.price : undefined }

  // CT-08: name the columns that are out of view in the table's scroll box ('⇢ scroll for ROCE%, DATA%'), as DESK
  // does, so a narrow window never hides a column silently. Re-measured on scroll and resize.
  const [scrollBox, setScrollBox] = useState<HTMLDivElement | null>(null)
  const [cue, setCue] = useState('')
  useEffect(() => {
    if (!scrollBox) { setCue(''); return }
    const read = () => {
      const b = scrollBox.getBoundingClientRect()
      const heads = Array.from(scrollBox.querySelectorAll<HTMLElement>('thead th')).map(th => {
        const r = th.getBoundingClientRect()
        return { label: (th.textContent ?? '').replace(/[↕↑↓]/g, '').trim().toUpperCase(), left: r.left, right: r.right }
      })
      const next = hiddenColumnsCue(hiddenHeaders(b.left, b.right, heads))
      setCue(prev => (prev === next ? prev : next))
    }
    read()
    scrollBox.addEventListener('scroll', read, { passive: true })
    const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(read)
    ro?.observe(scrollBox)
    const table = scrollBox.querySelector('table')
    if (table) ro?.observe(table)
    return () => { scrollBox.removeEventListener('scroll', read); ro?.disconnect() }
  }, [scrollBox])

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
          <span aria-hidden style={{ color: T.amber }}>⌕</span> Column Filters
          {activeCount > 0 && (
            <span className={clsx('px-1.5 rounded-full text-white text-xs font-bold', isDark ? 'bg-amber-600/80' : 'bg-indigo-600')}>{activeCount}</span>
          )}
        </button>
        {activeCount > 0 && (
          <button onClick={() => setFilters(EMPTY_FILTERS)} className={clsx('text-xs font-medium', isDark ? 'text-slate-400 hover:text-rose-400' : 'text-gray-400 hover:text-rose-500')}>
            Clear all
          </button>
        )}
        {cue && <span data-eqs-cue className="ml-auto text-[10.5px]" style={{ color: T.amber }} title="Columns outside the visible part of the table">{cue}</span>}
        {etfCount > 0 && (
          <button onClick={() => setShowEtfs(v => !v)} data-eqs-etf-toggle
            title="ETFs are funds, not companies: no earnings, no market cap (m078)"
            className={clsx(cue ? 'ml-3' : 'ml-auto', 'text-[10.5px] px-2 py-0.5 border')}
            style={{ borderColor: T.border, color: showEtfs ? T.amber : T.muted }}>
            {showEtfs ? `✓ ${etfCount} ETFs shown` : `${etfCount} ETFs hidden · show`}
          </button>
        )}
        <span className={clsx(cue || etfCount > 0 ? 'ml-3' : 'ml-auto', 'text-xs', isDark ? 'text-slate-400' : 'text-gray-400')}>
          {displayed.length.toLocaleString('en-IN')} of {stocks.length.toLocaleString('en-IN')} {showEtfs ? 'securities' : 'listings'}
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
              value={filters.capCategory}
              onChange={e => setFilters(f => ({ ...f, capCategory: e.target.value }))}
              className={clsx('px-2 py-1.5 text-xs rounded focus:ring-1', isDark ? 'border border-slate-600 bg-slate-700 text-slate-200 focus:ring-amber-500' : 'border border-gray-300 bg-white focus:ring-indigo-400')}
            >
              <option value="">All sizes</option>
              <option value="Large">Large · market-cap rank 1–100</option>
              <option value="Mid">Mid · rank 101–250</option>
              <option value="Small">Small · rank 251+</option>
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

      {/* m079: what each column is and where it came from (evidence badges; M07 provenance counts) */}
      <div data-eqs-legend className="px-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-[10.5px]" style={{ color: T.dim }}>
        <span><span style={{ color: T.muted }}>CMP</span> the stored NSE close (live NSE quote on the first {LIVE_ROWS} rows when the feed answers)</span>
        <span className="inline-flex items-center gap-1"><BadgeChip badge="arithmetic" /> P/E · Mkt cap · size rank at that close, from the latest NSE results filing ({legend.filings.toLocaleString('en-IN')} rows){legend.rebased ? `; ${legend.rebased} rebased from the enrichment snapshot (ˢ)` : ''}{legend.withheld ? `; ${legend.withheld} withheld (snapshot not comparable)` : ''}</span>
        <span className="inline-flex items-center gap-1"><BadgeChip badge="context" /> NP / Sales Qtr: that filing vs a year earlier · Div Yld, ROCE: the enrichment snapshot{(() => { const d = stocks.reduce<string | null>((m, x) => (x.metrics_as_of && (!m || x.metrics_as_of > m) ? x.metrics_as_of : m), null); return d ? ` of ${d.slice(0, 10)}` : ' (undated)' })()} (COMP and DVD give the trailing-12-month yield)</span>
        <span className="inline-flex items-center gap-1"><BadgeChip badge="heuristic" /> Size: SEBI-style rank by today&apos;s market cap (1–100 large, 101–250 mid), not AMFI&apos;s six-month list</span>
      </div>

      {/* Table */}
      {displayed.length === 0 ? (
        <div className="py-16 text-center">
          <div className="text-4xl mb-3 opacity-30" style={{ color: T.dim }}>◇</div>
          <p className={clsx('font-medium', isDark ? 'text-slate-400' : 'text-gray-500')}>No stocks match the selected filters</p>
          <p className={clsx('text-sm mt-1', isDark ? 'text-slate-500' : 'text-gray-400')}>Try adjusting your search criteria</p>
        </div>
      ) : (
        <div ref={setScrollBox} className="overflow-x-auto overflow-y-auto max-h-[calc(100vh-320px)] px-4">
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10">
              <tr className={clsx('border-b', 'border-[#1a2130] bg-[#080b10]')}>
                {/* CT-08: the watch star leads (it was the last column, the first to be cut off at 1600 px) */}
                {onWatchToggle && (
                  <th className={clsx('px-2 py-2 text-center text-[9.5px] font-medium uppercase tracking-wider whitespace-nowrap', isDark ? 'text-slate-400' : 'text-gray-500')} title="Watchlist">★</th>
                )}
                {/* Static columns */}
                <th onClick={() => toggleSort('ticker')}
                  className={clsx('px-2 py-2 text-left text-[9.5px] font-medium uppercase tracking-wider cursor-pointer whitespace-nowrap', isDark ? 'text-slate-400 hover:bg-slate-700/30' : 'text-gray-500 hover:bg-gray-100')}>
                  Ticker <SortIcon col="ticker" />
                </th>
                <th className={clsx('px-2 py-2 text-left text-[9.5px] font-medium uppercase tracking-wider whitespace-nowrap', isDark ? 'text-slate-400' : 'text-gray-500')}>Company · Sector</th>
                <th className={clsx('px-2 py-2 text-center text-[9.5px] font-medium uppercase tracking-wider whitespace-nowrap', isDark ? 'text-slate-400' : 'text-gray-500')} title="member of the NIFTY 500 index">Nifty</th>
                <th className={clsx('px-2 py-2 text-center text-[9.5px] font-medium uppercase tracking-wider whitespace-nowrap', isDark ? 'text-slate-400' : 'text-gray-500')}
                  title="SEBI-style size by market-cap rank at the latest close: 1–100 large, 101–250 mid, the rest small (heuristic: SEBI ranks the six-month average)">Size</th>
                <th className={clsx('px-2 py-2 text-left text-[9.5px] font-medium uppercase tracking-wider whitespace-nowrap', isDark ? 'text-slate-400' : 'text-gray-500')}>Event</th>

                {/* Financial columns — sortable */}
                <th onClick={() => toggleSort('cmp')}
                  className={clsx('px-2 py-2 text-right text-[9.5px] font-medium uppercase tracking-wider cursor-pointer whitespace-nowrap', isDark ? 'text-slate-400 hover:bg-slate-700/30' : 'text-gray-500 hover:bg-gray-100')}>
                  CMP ₹ <SortIcon col="cmp" />
                  {liveEq.available && liveEq.source && <span title={`first ${LIVE_ROWS} rows in this order: live NSE quotes; the rest: the stored close (EOD)`}>
                    {' '}<SourceChip info={liveEq.source} style={{ fontSize: 8.5, padding: '0 4px' }} /></span>}
                </th>
                <th onClick={() => toggleSort('pe_ratio')}
                  className={clsx('px-2 py-2 text-right text-[9.5px] font-medium uppercase tracking-wider cursor-pointer whitespace-nowrap', isDark ? 'text-slate-400 hover:bg-slate-700/30' : 'text-gray-500 hover:bg-gray-100')}>
                  <span title="trailing P/E at the stored NSE close (latest NSE results filing)">P/E</span> <SortIcon col="pe_ratio" />
                </th>
                <th onClick={() => toggleSort('mktcap_cr')}
                  className={clsx('px-2 py-2 text-right text-[9.5px] font-medium uppercase tracking-wider cursor-pointer whitespace-nowrap', isDark ? 'text-slate-400 hover:bg-slate-700/30' : 'text-gray-500 hover:bg-gray-100')}>
                  Mkt Cap Cr <SortIcon col="mktcap_cr" />
                </th>
                <th onClick={() => toggleSort('div_yld_pct')}
                  className={clsx('px-2 py-2 text-center text-[9.5px] font-medium uppercase tracking-wider cursor-pointer whitespace-nowrap', isDark ? 'text-slate-400 hover:bg-slate-700/30' : 'text-gray-500 hover:bg-gray-100')}>
                  <span title="the enrichment snapshot's dividend yield rebased to the stored close; COMP / DVD give the trailing-12-month yield from NSE corporate actions">Div Yld%ˢ</span> <SortIcon col="div_yld_pct" />
                </th>
                <th onClick={() => toggleSort('np_qtr_cr')}
                  className={clsx('px-2 py-2 text-right text-[9.5px] font-medium uppercase tracking-wider cursor-pointer whitespace-nowrap', isDark ? 'text-slate-400 hover:bg-slate-700/30' : 'text-gray-500 hover:bg-gray-100')}>
                  <span title="net profit of the latest quarter filed with NSE, ₹ cr, vs the same quarter a year earlier">NP Qtr Cr</span> <SortIcon col="np_qtr_cr" />
                </th>
                <th onClick={() => toggleSort('sales_qtr_cr')}
                  className={clsx('px-2 py-2 text-right text-[9.5px] font-medium uppercase tracking-wider cursor-pointer whitespace-nowrap', isDark ? 'text-slate-400 hover:bg-slate-700/30' : 'text-gray-500 hover:bg-gray-100')}>
                  Sales Qtr Cr <SortIcon col="sales_qtr_cr" />
                </th>
                <th onClick={() => toggleSort('roce_pct')}
                  className={clsx('px-2 py-2 text-right text-[9.5px] font-medium uppercase tracking-wider cursor-pointer whitespace-nowrap', isDark ? 'text-slate-400 hover:bg-slate-700/30' : 'text-gray-500 hover:bg-gray-100')}>
                  ROCE% <SortIcon col="roce_pct" />
                </th>

                {/* Data quality columns */}
                <th onClick={() => toggleSort('density')}
                  className={clsx('px-2 py-2 text-left text-[9.5px] font-medium uppercase tracking-wider cursor-pointer whitespace-nowrap', isDark ? 'text-slate-400 hover:bg-slate-700/30' : 'text-gray-500 hover:bg-gray-100')}>
                  Data% <SortIcon col="density" />
                </th>
              </tr>
            </thead>
            <tbody className={clsx('divide-y', 'divide-[#1a2130]')}>
              {shown.map((stock, idx) => (
                <StockRow key={stock.ticker} stock={stock} even={idx % 2 === 0} isDark={isDark}
                  live={livePx(stock.ticker) ?? liveQuotes[stock.ticker]?.ltp} flash={flashMap[stock.ticker] ?? null}
                  watched={watched.has(stock.ticker)} showWatch={showWatch}
                  event={events.get(stock.ticker)?.[0]} avoid={avoid.get(stock.ticker)} today={today}
                  onRowClick={handleRowClick} onWatchToggle={handleWatchToggle} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

interface StockRowProps {
  stock: Stock
  even: boolean
  isDark: boolean
  /** live LTP from the monitor WebSocket (watched stocks only) */
  live: number | undefined
  flash: Flash
  watched: boolean
  showWatch: boolean
  event: CorpEvent | undefined
  avoid: RecentResult | undefined
  /** today's IST date: changes once a day so the event badge's day count re-renders (RUP-09) */
  today: string
  onRowClick: (ticker: string) => void
  onWatchToggle: (ticker: string) => void
}

/** One EQS row. Memoized: it re-renders only when its own props change (C2-performance-01). */
const StockRow = memo(function StockRow({ stock: raw, even, isDark, live, flash, watched, showWatch, event, avoid, today, onRowClick, onWatchToggle }: StockRowProps) {
  // M07: the row renders only dated, comparable valuations (shownValuation: filings at the close, or the snapshot
  // rebased within the band); anything else is null and prints "—"
  const stock: Stock = { ...raw, pe_ratio: shownValuation(raw, 'pe_ratio'), mktcap_cr: shownValuation(raw, 'mktcap_cr'), div_yld_pct: shownValuation(raw, 'div_yld_pct') }
  const sepaKey   = stock.sepa_stage?.split(':')[0]?.trim() ?? ''
  const sepaColor = SEPA_COLORS[sepaKey] ?? 'bg-gray-100 text-gray-500 border-gray-200'
  const qualityDot = stock.has_ohlcv === false ? 'bg-gray-200' : (QUALITY_DOTS[stock.data_quality ?? ''] ?? 'bg-gray-300')
  // M07: the stored NSE close (never the enrichment snapshot's price: an older ui-api sent that as `cmp`)
  const displayPrice = eqsPrice(stock)
  const vNote = valuationNote(stock)
  const snapMark = stock.valuation_basis === 'snapshot_rebased' ? 'ˢ' : ''
  const quarterOk = stock.quarter_basis === 'filings' || stock.quarter_basis === 'snapshot'
  const qTitle = stock.quarter_basis === 'filings' ? `quarter ended ${stock.qtr_period ?? '—'} (NSE results filing) vs a year earlier`
    : stock.quarter_basis === 'snapshot' ? 'the enrichment snapshot (no NSE results filing read yet)' : 'no quarter stored'
  const isEvenRow = even

  return (
    <tr
      key={stock.ticker}
      onClick={() => onRowClick(stock.ticker)}
      className={clsx(
        'cursor-pointer transition-colors duration-200',
        isDark && (isEvenRow ? 'bg-[#0a0d13] hover:bg-[#131926]' : 'bg-[#080a0f] hover:bg-[#131926]'),
        !isDark && (isEvenRow ? 'bg-gray-50 hover:bg-indigo-50' : 'bg-white hover:bg-indigo-50')
      )}
    >
      {/* Watchlist toggle (CT-08: first column) */}
      {showWatch && (
        <td className="px-2 py-1.5 text-center" onClick={e => e.stopPropagation()}>
          <button
            onClick={() => onWatchToggle(stock.ticker)}
            title={watched ? 'Remove from watchlist' : 'Add to watchlist'}
            aria-label={`${watched ? 'Remove' : 'Add'} ${stock.ticker} ${watched ? 'from' : 'to'} the watchlist`}
            className={clsx(
              'text-base leading-none transition-transform hover:scale-125',
              watched ? 'text-amber-400' : isDark ? 'text-slate-600 hover:text-amber-500' : 'text-gray-300 hover:text-amber-500'
            )}
          >
            {watched ? '★' : '☆'}
          </button>
        </td>
      )}

      {/* Ticker; the dot is the data health (CT-08: the separate HEALTH column repeated this same dot) */}
      <td className="px-2 py-1.5">
        <div className="flex items-center gap-2">
          <div className={clsx('w-2 h-2 rounded-full flex-shrink-0', qualityDot)}
               title={`data health: ${stock.has_ohlcv === false ? 'no price data' : (stock.data_quality || 'unknown')}`} />
          <span className="font-semibold" style={{ color: '#ffb000' }}>{stock.ticker}</span>
          {stock.instrument === 'ETF' && <span title={`ETF · ${stock.etf_underlying ?? ''}`} className="text-[9px] px-1 border" style={{ color: T.muted, borderColor: T.border }}>ETF</span>}
        </div>
      </td>

      {/* Company name · sector on ONE line (CT-08: the two-line cell made every row ~50 px; full text on hover) */}
      <td className="px-2 py-1.5 max-w-[220px]">
        <span className={clsx('text-xs truncate block', isDark ? 'text-slate-300' : 'text-gray-600')}
              title={[stock.company_name, stock.sector_name].filter(Boolean).join(' · ')}>
          {stock.company_name ?? <span className={isDark ? 'text-slate-500' : 'text-gray-300'}>—</span>}
          {stock.sector_name && <span className={clsx('text-[10px]', isDark ? 'text-slate-400' : 'text-gray-400')}> · {stock.sector_name}</span>}
        </span>
      </td>

      {/* Nifty bucket */}
      <td className="px-2 py-1.5 text-center">
        <span className={clsx(
          'inline-block min-w-[36px] px-1.5 text-[10px] font-semibold border',
          stock.nifty_bucket ? 'border-[#39c6ff55] text-[#39c6ff]' : 'border-transparent text-[var(--t-dim)]'
        )}>
          {stock.nifty_bucket ?? '—'}
        </span>
      </td>

      {/* m077: size by market-cap rank (the CSV's 'Large Cap' only meant NIFTY 500 membership, shown in the Nifty column) */}
      <td className="px-2 py-1.5 text-center">
        {stock.cap_sebi ? (
          <span className={clsx('inline-block px-1.5 text-[10px] font-medium whitespace-nowrap border border-current uppercase', CAP_BADGE_COLORS[stock.cap_sebi])}
            title={`market-cap rank ${stock.cap_rank} at the latest close (SEBI-style: 1–100 large, 101–250 mid)`}>
            {stock.cap_sebi}
          </span>
        ) : <span className="text-xs" style={{ color: T.dim }} title={stock.instrument === 'ETF' ? 'an ETF' : 'no market cap stored'}>—</span>}
      </td>

      {/* Next corporate event + research flag (bad results reaction within 60 sessions) */}
      <td className="px-2 py-1.5">
        {/* CT-08: a BAD RESULTS flag next to an event badge (6 of 1,500 rows) wraps under it instead of widening the
            whole column by ~80 px and pushing DATA% out of a 1600 px window */}
        <span style={{ display: 'inline-flex', flexWrap: 'wrap', gap: 4, maxWidth: 160 }}>
          {avoid && <AvoidFlag r={avoid} />}
          {event ? <EventBadge key={today} kind={event.kind} date={event.event_date} days={daysUntil(event.event_date)} typical={event.typical_move_pct} detail={event.detail} /> : null}
        </span>
      </td>

      {/* CMP ₹ — overlays live WS price for watched stocks */}
      <td className={clsx(
        'px-2 py-1.5 text-right transition-colors duration-300',
        flash === 'up'   && (isDark ? 'bg-emerald-900/30' : 'bg-emerald-50'),
        flash === 'down' && (isDark ? 'bg-rose-900/20'    : 'bg-rose-50'),
      )}>
        {(() => {
          const price = live ?? displayPrice
          return (
            <div className="flex items-center justify-end gap-1">
              {live !== undefined && (
                <span className={clsx(
                  'w-1 h-1 rounded-full flex-shrink-0',
                  flash === 'up'   ? 'bg-emerald-400' :
                  flash === 'down' ? 'bg-rose-400'    : 'bg-emerald-500 animate-pulse',
                )} />
              )}
              <span className={clsx(
                'font-semibold tabular-nums',
                flash === 'up'   ? 'text-emerald-400' :
                flash === 'down' ? 'text-rose-400'    :
                live !== undefined
                  ? (isDark ? 'text-emerald-300' : 'text-emerald-700')
                  : (isDark ? 'text-slate-200'  : 'text-gray-800'),
              )}>
                {price != null ? `₹${fmtFixed(price, 2)}` : '—'}
              </span>
            </div>
          )
        })()}
      </td>

      {/* P/E (M07: at the stored close; neutral tone: a valuation is context, not a buy / sell colour) */}
      <td className="px-2 py-1.5 text-right" title={vNote}>
        {stock.pe_ratio != null ? (
          <span className={clsx('font-semibold', isDark ? 'text-slate-300' : 'text-gray-700')}>{fmtFixed(stock.pe_ratio, 1)}{snapMark}</span>
        ) : <span className={isDark ? 'text-slate-500' : 'text-gray-300'}>{stock.valuation_basis === 'etf' ? 'ETF' : '—'}</span>}
      </td>

      {/* Market Cap */}
      <td className={clsx('px-2 py-1.5 text-right text-xs', isDark ? 'text-slate-300' : 'text-gray-700')} title={vNote}>
        {stock.mktcap_cr != null ? <>{fmt(Math.round(stock.mktcap_cr))}{snapMark}</> : <span className={isDark ? 'text-slate-500' : 'text-gray-300'}>—</span>}
      </td>

      {/* Div Yield (the snapshot, rebased to the close; withheld when not comparable) */}
      <td className="px-2 py-1.5 text-center" title={stock.div_basis === 'withheld' ? 'withheld: the snapshot is not comparable with the close' : 'the enrichment snapshot rebased to the stored close'}>
        {stock.div_yld_pct != null && stock.div_yld_pct > 0 ? (
          <span className={clsx('text-xs', isDark ? 'text-slate-300' : 'text-gray-700')}>{fmtFixed(stock.div_yld_pct, 2)}%</span>
        ) : <span className={clsx('text-xs', isDark ? 'text-slate-500' : 'text-gray-300')}>—</span>}
      </td>

      {/* NP Quarter Cr */}
      <td className="px-2 py-1.5 text-right" title={qTitle}>
        {quarterOk && stock.np_qtr_cr != null ? (
          <span className={clsx('text-xs', stock.np_qtr_cr >= 0 ? (isDark ? 'text-slate-300' : 'text-gray-700') : 'text-rose-500')}>
            {fmtFixed(stock.np_qtr_cr, 0)}
            <TrendArrow pct={stock.qtr_pft_var} />
          </span>
        ) : <span className={clsx('text-xs', isDark ? 'text-slate-500' : 'text-gray-300')}>—</span>}
      </td>

      {/* Sales Quarter Cr */}
      <td className="px-2 py-1.5 text-right" title={qTitle}>
        {quarterOk && stock.sales_qtr_cr != null ? (
          <span className={clsx('text-xs', isDark ? 'text-slate-300' : 'text-gray-700')}>
            {fmtFixed(stock.sales_qtr_cr, 0)}
            <TrendArrow pct={stock.qtr_sal_var} />
          </span>
        ) : <span className={clsx('text-xs', isDark ? 'text-slate-500' : 'text-gray-300')}>—</span>}
      </td>

      {/* ROCE % */}
      <td className="px-2 py-1.5 text-right">
        {stock.roce_pct != null ? (
          <span className={clsx('text-xs', isDark ? 'text-slate-300' : 'text-gray-600')} title="the enrichment snapshot's ROCE">
            {fmtFixed(stock.roce_pct, 1)}%
          </span>
        ) : <span className={clsx('text-xs', isDark ? 'text-slate-500' : 'text-gray-300')}>—</span>}
      </td>

      {/* Data density bar */}
      <td className="px-2 py-1.5">
        {stock.has_ohlcv === false ? (
          <span className={clsx('text-[10px] font-medium', isDark ? 'text-slate-500' : 'text-gray-300')}>No data</span>
        ) : (
          <div className="flex items-center gap-1.5">
            <div className={clsx('h-1.5 w-12 rounded-full overflow-hidden', isDark ? 'bg-slate-700/50' : 'bg-gray-200')}>
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

    </tr>
  )
})
