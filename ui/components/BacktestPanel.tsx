'use client'

import { useState, useCallback, useEffect, useRef } from 'react'
import {
  ComposedChart, Line, Bar, CartesianGrid, XAxis, YAxis, Tooltip, ResponsiveContainer, Brush, ReferenceLine, Legend, BarChart, Cell,
} from 'recharts'
import {
  createChart,
  ColorType,
  CrosshairMode,
  type IChartApi,
} from 'lightweight-charts'
import clsx from 'clsx'
import { TradeExplorer } from './TradeExplorer'
import { runWFOBacktest } from '@/lib/api'

// ── LW Equity Curve ─────────────────────────────────────────────────────────

interface EquityPoint { date: string; cumulative_return: number }

function LWEquityCurve({ data }: { data: EquityPoint[] }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef     = useRef<IChartApi | null>(null)

  useEffect(() => {
    if (!containerRef.current || !data.length) return

    const finalReturn = data[data.length - 1]?.cumulative_return ?? 0
    const isPositive  = finalReturn >= 0
    const lineColor   = isPositive ? '#f59e0b' : '#ef4444'
    const topFill     = isPositive ? '#f59e0b33' : '#ef444433'

    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: '#1e293b' }, textColor: '#94a3b8' },
      grid:   { vertLines: { color: '#334155' }, horzLines: { color: '#334155' } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#475569' },
      timeScale: { borderColor: '#475569', timeVisible: false },
      width:  containerRef.current.clientWidth,
      height: 220,
    })

    const series = chart.addAreaSeries({
      lineColor,
      topColor:    topFill,
      bottomColor: 'transparent',
      lineWidth:   2,
    })

    series.setData(data.map(d => ({ time: d.date as any, value: d.cumulative_return })))
    chart.timeScale().fitContent()
    chartRef.current = chart

    const ro = new ResizeObserver(entries => {
      if (entries[0] && chartRef.current) {
        chartRef.current.applyOptions({ width: entries[0].contentRect.width })
      }
    })
    ro.observe(containerRef.current)

    return () => { ro.disconnect(); chart.remove(); chartRef.current = null }
  }, [data])

  return <div ref={containerRef} className="w-full rounded-xl overflow-hidden" />
}

interface FilterCondition {
  id: string
  field: string
  op: 'lt' | 'gt' | 'lte' | 'gte'
  value: number
}

interface Trade {
  date: string
  ticker: string
  entry_price: number
  exit_price: number
  return_pct: number
  is_win: boolean
}

interface BacktestResult {
  total_trades: number
  wins: number
  losses: number
  win_rate: number
  avg_return: number
  avg_win_return: number
  avg_loss_return: number
  max_drawdown: number
  sharpe_ratio: number
  sortino_ratio?: number
  calmar_ratio?: number
  profit_factor?: number
  monte_carlo?: {
    p5: number
    p25: number
    p50: number
    p75: number
    p95: number
    histogram: number[]
  }
  wfo_windows?: Array<{ start: string; end: string; trades: number; return_pct: number }>
  equity_curve: Array<{ date: string; cumulative_return: number; stocks_entered?: number }>
  trades: Trade[]
}

interface OHLCV {
  date: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

// Candlestick rendering function for recharts
const renderCandlesticks = (data: OHLCV[], yScale: any, xScale: any) => {
  if (!data || data.length === 0) return null

  const minPrice = Math.min(...data.map(d => d.low))
  const maxPrice = Math.max(...data.map(d => d.high))
  const range = maxPrice - minPrice || 1

  return (
    <g key="candlesticks">
      {data.map((candle, idx) => {
        const isGain = candle.close >= candle.open
        const color = isGain ? '#10b981' : '#ef4444'

        // Approximate X position based on index
        const xPos = (idx / (data.length - 1 || 1)) * 700 + 30

        // Scale Y positions (inverted: high = top, low = bottom)
        const highY = 10 + (1 - (candle.high - minPrice) / range) * 380
        const lowY = 10 + (1 - (candle.low - minPrice) / range) * 380
        const openY = 10 + (1 - (candle.open - minPrice) / range) * 380
        const closeY = 10 + (1 - (candle.close - minPrice) / range) * 380

        const bodyTop = Math.min(openY, closeY)
        const bodyBottom = Math.max(openY, closeY)
        const bodyHeight = Math.max(bodyBottom - bodyTop, 1)

        return (
          <g key={`candle-${idx}`}>
            {/* Wick (high-low line) */}
            <line
              x1={xPos}
              x2={xPos}
              y1={highY}
              y2={lowY}
              stroke={color}
              strokeWidth={1}
            />
            {/* Body (open-close rectangle) */}
            <rect
              x={xPos - 3}
              y={bodyTop}
              width={6}
              height={bodyHeight || 1}
              fill={color}
              stroke={color}
              strokeWidth={0.5}
            />
          </g>
        )
      })}
    </g>
  )
}

// Tier 1 Indicators (Institutional Grade)
const TIER_1_FILTERS = {
  'Valuation': [
    { id: 'pe_ratio', label: 'P/E Ratio', unit: 'x', defaultOp: 'lt' as const, defaultVal: 25, desc: 'Price-to-earnings ratio' },
    { id: 'div_yld_pct', label: 'Dividend Yield', unit: '%', defaultOp: 'gt' as const, defaultVal: 1, desc: 'Annual dividend / price' },
    { id: 'mktcap_cr', label: 'Market Cap', unit: 'Cr', defaultOp: 'gt' as const, defaultVal: 500, desc: 'Market capitalization' },
  ],
  'Quality': [
    { id: 'roce_pct', label: 'ROCE', unit: '%', defaultOp: 'gt' as const, defaultVal: 15, desc: 'Return on invested capital' },
  ],
  'Technical Trend': [
    { id: 'price_gt_ma50', label: 'Price > 50-day MA', toggle: true, desc: 'Above short-term trend', defaultOp: 'gt' as const, defaultVal: 0 },
    { id: 'price_gt_ma200', label: 'Price > 200-day MA', toggle: true, desc: 'Above long-term trend', defaultOp: 'gt' as const, defaultVal: 0 },
    { id: 'ma50_gt_ma200', label: '50-day MA > 200-day MA', toggle: true, desc: 'Golden cross signal', defaultOp: 'gt' as const, defaultVal: 0 },
  ],
  'Technical Momentum': [
    { id: 'rsi_14', label: 'RSI (14)', unit: '0-100', defaultOp: 'gt' as const, defaultVal: 30, desc: 'Oversold <30, Overbought >70' },
    { id: 'atr_14_pct', label: 'ATR % (14)', unit: '%', defaultOp: 'lt' as const, defaultVal: 5, desc: 'Volatility measure' },
  ],
  'Volatility & Support': [
    { id: 'above_52w_low_pct', label: '% above 52-week Low', unit: '%', defaultOp: 'gt' as const, defaultVal: 30, desc: 'Bounce strength signal' },
    { id: 'within_52w_high_pct', label: '% within 52-week High', unit: '%', defaultOp: 'lt' as const, defaultVal: 25, desc: 'Nearness to yearly peak' },
    { id: 'dist_ma200_pct', label: 'Distance from 200-day MA', unit: '%', defaultOp: 'lt' as const, defaultVal: 20, desc: 'Overbought/oversold (±20%)' },
  ],
  'Volume': [
    { id: 'volume_gt_avg', label: 'Volume > 20-day Avg', toggle: true, desc: 'Accumulation signal', defaultOp: 'gt' as const, defaultVal: 0 },
  ],
}

const PRESET_RANGES = [
  { label: '1M', days: 30 },
  { label: '3M', days: 90 },
  { label: '6M', days: 180 },
  { label: '1Y', days: 365 },
  { label: '2Y', days: 730 },
  { label: '5Y', days: 1825 },
]

interface BacktestPanelProps {
  isDark?: boolean
  watchlist?: string[]
}

export function BacktestPanel({ isDark = true, watchlist = [] }: BacktestPanelProps) {
  const today = new Date().toISOString().split('T')[0]
  const threeMonthsAgo = new Date(Date.now() - 90 * 24 * 60 * 60 * 1000).toISOString().split('T')[0]

  const [fromDate, setFromDate] = useState(threeMonthsAgo)
  const [toDate, setToDate] = useState(today)
  const [forwardDays, setForwardDays] = useState(5)
  const [winThreshold, setWinThreshold] = useState(0)
  const [filters, setFilters] = useState<FilterCondition[]>([])
  const [loading, setLoading] = useState(false)
  const [results, setResults] = useState<BacktestResult | null>(null)
  const [activeSort, setActiveSort] = useState<{ col: string; asc: boolean }>({ col: 'date', asc: false })
  const [tradePageIndex, setTradePageIndex] = useState(0)
  const [showControls, setShowControls] = useState(true)
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null)
  const [chartData, setChartData] = useState<OHLCV[]>([])
  const [chartLoading, setChartLoading] = useState(false)
  const [chartPeriod, setChartPeriod] = useState<'5D' | '1M' | '3M' | '6M' | '1Y' | '2Y'>('1M')
  const [chartType, setChartType] = useState<'line' | 'candle' | 'area'>('line')
  const [wfoMode, setWfoMode] = useState(false)
  const [inSampleDays, setInSampleDays] = useState(180)
  const [outSampleDays, setOutSampleDays] = useState(60)
  const [monteCarloRuns, setMonteCarloRuns] = useState(1000)

  const PERIOD_DAYS = { '5D': 5, '1M': 30, '3M': 90, '6M': 180, '1Y': 365, '2Y': 730 }

  const setPresetRange = (days: number) => {
    const end = new Date()
    const start = new Date(end.getTime() - days * 24 * 60 * 60 * 1000)
    setFromDate(start.toISOString().split('T')[0])
    setToDate(end.toISOString().split('T')[0])
  }

  const fetchChartData = useCallback(async (ticker: string, days: number) => {
    setChartLoading(true)
    try {
      const res = await fetch(`/api/stocks/${ticker}/ohlcv?days=${days}`)
      if (!res.ok) {
        console.error(`Failed to fetch chart data: ${res.status} ${res.statusText}`)
        return
      }
      const data = await res.json()
      if (data.rows && Array.isArray(data.rows)) {
        setChartData(data.rows)
      } else {
        console.warn('No OHLCV data in response:', data)
      }
    } catch (err) {
      console.error('Failed to load chart data:', err)
    } finally {
      setChartLoading(false)
    }
  }, [])

  const openTradeChart = async (trade: Trade) => {
    setSelectedTrade(trade)
    await fetchChartData(trade.ticker, PERIOD_DAYS[chartPeriod])
  }

  // Re-fetch when chart period changes
  useEffect(() => {
    if (!selectedTrade) return
    fetchChartData(selectedTrade.ticker, PERIOD_DAYS[chartPeriod])
  }, [chartPeriod, selectedTrade, fetchChartData])

  const closeTradeChart = () => {
    setSelectedTrade(null)
    setChartData([])
  }

  const toggleFilter = (fieldId: string) => {
    const existing = filters.find(f => f.field === fieldId)
    if (existing) {
      setFilters(filters.filter(f => f.field !== fieldId))
    } else {
      // Find field definition in TIER_1_FILTERS
      let fieldDef: any = null
      for (const category of Object.values(TIER_1_FILTERS)) {
        fieldDef = category.find(f => f.id === fieldId)
        if (fieldDef) break
      }

      if (fieldDef && 'defaultOp' in fieldDef) {
        setFilters([...filters, {
          id: fieldId,
          field: fieldId,
          op: fieldDef.defaultOp,
          value: fieldDef.defaultVal,
        }])
      }
    }
  }

  const updateFilter = (id: string, op?: 'lt' | 'gt' | 'lte' | 'gte', value?: number) => {
    setFilters(filters.map(f =>
      f.id === id ? { ...f, ...(op && { op }), ...(value !== undefined && { value }) } : f
    ))
  }

  const runBacktest = async () => {
    setLoading(true)
    try {
      const filterData = filters.map(({ field, op, value }) => ({ field, op, value }))

      if (wfoMode) {
        // Call WFO endpoint
        const payload = {
          from_date: fromDate,
          to_date: toDate,
          in_sample_days: inSampleDays,
          out_sample_days: outSampleDays,
          forward_days: forwardDays,
          win_threshold: winThreshold,
          filters: filterData,
          monte_carlo_runs: monteCarloRuns,
        }
        const res = await runWFOBacktest(payload)
        setResults(res.data)
      } else {
        // Call regular backtest
        const payload = {
          from_date: fromDate,
          to_date: toDate,
          forward_days: forwardDays,
          win_threshold: winThreshold,
          filters: filterData,
        }
        const res = await fetch('/api/analytics/backtest', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        })
        const data = await res.json()
        setResults(data)
      }
      setTradePageIndex(0)
    } catch (err) {
      console.error('Backtest error:', err)
    } finally {
      setLoading(false)
    }
  }

  const sortedTrades = results?.trades
    ? [...results.trades].sort((a, b) => {
        let aVal: any = (a as any)[activeSort.col]
        let bVal: any = (b as any)[activeSort.col]
        if (typeof aVal === 'string') aVal = aVal.toLowerCase()
        if (typeof bVal === 'string') bVal = bVal.toLowerCase()
        const cmp = aVal < bVal ? -1 : aVal > bVal ? 1 : 0
        return activeSort.asc ? cmp : -cmp
      })
    : []

  const tradesPerPage = 20
  const paginatedTrades = sortedTrades.slice(tradePageIndex * tradesPerPage, (tradePageIndex + 1) * tradesPerPage)

  const activeFilterCount = filters.length

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100" style={{ fontFamily: 'IBM Plex Sans, system-ui, sans-serif' }}>
      {/* Header */}
      <div className="border-b border-slate-800 bg-slate-900/50 backdrop-blur-sm sticky top-0 z-30">
        <div className="w-full px-4 sm:px-6 lg:px-8 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3 flex-1 min-w-0">
            <div className="text-2xl sm:text-3xl flex-shrink-0">📊</div>
            <div className="min-w-0">
              <h1 className="text-lg sm:text-xl font-bold text-slate-100 truncate">Backtest Lab</h1>
              <p className="text-xs text-slate-400 mt-0.5 hidden sm:block">Simulate trading filters on historical NSE data</p>
            </div>
          </div>
          <div className="text-xs text-slate-500 ml-2 text-right whitespace-nowrap">
            {results && <span className="hidden sm:inline">{results.total_trades} trades · {results.win_rate.toFixed(1)}% win</span>}
            {results && <span className="sm:hidden">{results.win_rate.toFixed(1)}%</span>}
          </div>
          <button
            onClick={() => setShowControls(!showControls)}
            className="ml-4 px-3 py-2 rounded-lg bg-slate-700/30 text-slate-300 text-sm font-semibold hover:bg-slate-700/50 lg:hidden"
          >
            {showControls ? '✕ Hide' : '⚙ Show'} Filter
          </button>
        </div>
      </div>

      {/* Main Layout: Split Pane */}
      <div className="w-full px-4 sm:px-6 lg:px-8 py-6 sm:py-8 grid grid-cols-1 lg:grid-cols-4 gap-6 sm:gap-8">
        {/* Left: Control Panel */}
        <div className={clsx(
          "lg:col-span-1 space-y-5 lg:max-h-[calc(100vh-200px)] lg:overflow-y-auto",
          !showControls && "hidden lg:block"
        )}>
          {/* Date Range Card */}
          <div className="rounded-xl border border-slate-700/40 bg-slate-800/30 backdrop-blur-sm p-5 space-y-4 transition-all hover:border-slate-600/60 hover:shadow-md hover:shadow-slate-950/50">
            <h3 className="text-xs font-bold text-amber-400 uppercase tracking-widest">Date Range</h3>
            <div className="grid grid-cols-2 gap-2 sm:gap-3">
              <div>
                <label className="block text-xs text-slate-400 mb-1.5">From</label>
                <input
                  type="date"
                  value={fromDate}
                  onChange={e => setFromDate(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-700/50 border border-slate-600 text-slate-100 text-sm font-mono focus:outline-none focus:border-amber-500 focus:ring-1 focus:ring-amber-500/30"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1.5">To</label>
                <input
                  type="date"
                  value={toDate}
                  onChange={e => setToDate(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-700/50 border border-slate-600 text-slate-100 text-sm font-mono focus:outline-none focus:border-amber-500 focus:ring-1 focus:ring-amber-500/30"
                />
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              {PRESET_RANGES.map(({ label, days }) => (
                <button
                  key={label}
                  onClick={() => setPresetRange(days)}
                  className={clsx(
                    'px-2.5 py-1 rounded-md text-xs font-semibold transition-all',
                    fromDate === new Date(Date.now() - days * 24 * 60 * 60 * 1000).toISOString().split('T')[0]
                      ? 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
                      : 'bg-slate-700/30 text-slate-400 hover:bg-slate-600/40'
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>

          {/* Simulation Settings */}
          <div className="rounded-xl border border-slate-700/40 bg-slate-800/30 backdrop-blur-sm p-5 space-y-4 transition-all hover:border-slate-600/60 hover:shadow-md hover:shadow-slate-950/50">
            <h3 className="text-xs font-bold text-amber-400 uppercase tracking-widest">Settings</h3>
            <div>
              <label className="flex items-center justify-between mb-2">
                <span className="text-sm text-slate-400">Forward Period (days)</span>
                <span className="text-lg font-mono font-bold text-amber-400">{forwardDays}</span>
              </label>
              <input
                type="range"
                min="1"
                max="30"
                value={forwardDays}
                onChange={e => setForwardDays(Number(e.target.value))}
                className="w-full h-2 rounded-lg bg-slate-700 accent-amber-500 cursor-pointer"
              />
            </div>
            <div>
              <label className="flex items-center justify-between mb-2">
                <span className="text-sm text-slate-400">Win Threshold (%)</span>
                <span className="text-lg font-mono font-bold text-amber-400">{winThreshold.toFixed(1)}</span>
              </label>
              <input
                type="number"
                value={winThreshold}
                onChange={e => setWinThreshold(Number(e.target.value))}
                className="w-full px-3 py-2 rounded-lg bg-slate-700/50 border border-slate-600 text-slate-100 font-mono text-sm focus:outline-none focus:border-amber-500 focus:ring-1 focus:ring-amber-500/30"
              />
              <p className="text-xs text-slate-500 mt-1">Min return % to count as a win</p>
            </div>
          </div>

          {/* Tier 1 Filters - Organized by Category */}
          <div className="space-y-6">
            {Object.entries(TIER_1_FILTERS).map(([category, fields]) => {
              const sectionHasActiveFilter = fields.some(f => filters.find(x => x.field === f.id))
              return (
              <div key={category} className={clsx(
                "rounded-xl border bg-slate-800/30 backdrop-blur-sm p-5 space-y-4 transition-all duration-150 hover:shadow-md hover:shadow-slate-950/50",
                sectionHasActiveFilter
                  ? "border-l-2 border-l-amber-500 border-slate-700/60 bg-slate-800/40"
                  : "border-slate-700/40 hover:border-slate-600/60"
              )}>
                <div className="flex items-center justify-between">
                  <h3 className="text-xs font-bold text-amber-400 uppercase tracking-widest">{category}</h3>
                  {sectionHasActiveFilter && (
                    <span className="inline-flex items-center justify-center w-5 h-5 rounded-full bg-amber-500/20 text-amber-300 text-[10px] font-bold">
                      {fields.filter(f => filters.find(x => x.field === f.id)).length}
                    </span>
                  )}
                </div>

                {sectionHasActiveFilter && (
                  <div className="h-px bg-gradient-to-r from-amber-500/40 to-transparent" />
                )}

                <div className="space-y-4">
                  {fields.map((field: any) => {
                    const filter = filters.find(f => f.field === field.id)
                    const isToggle = field.toggle === true

                    return (
                      <div key={field.id} className={clsx(
                        "group transition-colors duration-100 rounded-lg p-3",
                        filter ? "bg-slate-700/20" : "hover:bg-slate-700/10"
                      )}>
                        <div className="flex items-start gap-3 mb-1.5">
                          {/* Custom Checkbox */}
                          <label htmlFor={`filter-${field.id}`} className="flex items-start gap-3 flex-1 cursor-pointer">
                            <div className="relative flex-shrink-0 mt-0.5">
                              <input
                                type="checkbox"
                                id={`filter-${field.id}`}
                                checked={!!filter}
                                onChange={() => toggleFilter(field.id)}
                                className="sr-only"
                              />
                              <div className={clsx(
                                "w-4 h-4 rounded-md border-2 transition-all duration-150 flex items-center justify-center",
                                filter
                                  ? "bg-amber-500 border-amber-500 shadow-md shadow-amber-500/20"
                                  : "border-slate-600 bg-slate-700/50 group-hover:border-slate-500 group-hover:bg-slate-600/50"
                              )}>
                                {filter && (
                                  <svg className="w-2.5 h-2.5 text-slate-950" fill="currentColor" viewBox="0 0 20 20">
                                    <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                                  </svg>
                                )}
                              </div>
                            </div>
                            <div className="flex-1 min-w-0">
                              <span className="text-xs font-semibold text-slate-200 block">{field.label}</span>
                              <p className="text-xs text-slate-400 font-medium uppercase tracking-wider mt-0.5">{field.desc}</p>
                            </div>
                          </label>
                        </div>

                        {filter && !isToggle && (
                          <div className="ml-7 flex gap-2 items-center mt-3 pt-3 border-t border-slate-700/30">
                            <select
                              value={filter.op}
                              onChange={e => updateFilter(filter.id, e.target.value as any)}
                              className="px-2 py-1.5 rounded text-xs bg-slate-700/50 border border-slate-600 text-slate-100 font-mono focus:outline-none focus:border-amber-500 focus:ring-1 focus:ring-amber-500/30 transition-colors duration-100"
                            >
                              <option value="lt">&lt;</option>
                              <option value="gt">&gt;</option>
                              <option value="lte">≤</option>
                              <option value="gte">≥</option>
                            </select>
                            <input
                              type="number"
                              value={filter.value}
                              onChange={e => updateFilter(filter.id, undefined, Number(e.target.value))}
                              className="w-20 px-2 py-1.5 rounded bg-slate-700/50 border border-slate-600 text-slate-100 font-mono text-xs focus:outline-none focus:border-amber-500 focus:ring-1 focus:ring-amber-500/30 transition-colors duration-100"
                              step="0.1"
                            />
                            <span className="text-xs font-mono text-slate-400 flex-shrink-0">{field.unit || ''}</span>
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )})}
          </div>

          {/* WFO Mode Toggle */}
          <div className="rounded-lg bg-slate-800/50 border border-slate-700 p-3 flex items-center gap-3">
            <label className="text-xs text-slate-300 font-semibold uppercase tracking-wide">WFO Mode</label>
            <button
              onClick={() => setWfoMode(!wfoMode)}
              className={clsx(
                'relative w-12 h-6 rounded-full transition-colors',
                wfoMode ? 'bg-amber-500' : 'bg-slate-700'
              )}
            >
              <div className={clsx(
                'absolute top-1 w-4 h-4 rounded-full bg-white transition-transform duration-200',
                wfoMode ? 'right-1' : 'left-1'
              )} />
            </button>
            <span className={`text-xs ${wfoMode ? 'text-amber-300' : 'text-slate-400'}`}>
              {wfoMode ? 'ON' : 'OFF'}
            </span>
          </div>

          {/* Run Button */}
          <button
            onClick={runBacktest}
            disabled={loading}
            className={clsx(
              'w-full py-3.5 rounded-xl font-bold uppercase tracking-widest text-sm transition-all duration-200 shadow-lg',
              loading
                ? 'bg-slate-700 text-slate-500 cursor-not-allowed shadow-slate-950/20'
                : 'bg-gradient-to-r from-amber-500 to-amber-600 text-slate-950 hover:shadow-xl hover:shadow-amber-500/50 hover:scale-[1.02] active:scale-95'
            )}
          >
            <span className="flex items-center justify-center gap-2">
              <span className={clsx(
                'inline-block transition-transform duration-300',
                loading && 'animate-spin'
              )}>
                {loading ? '⟳' : '▶'}
              </span>
              {loading ? 'Running Backtest…' : 'Run Backtest'}
            </span>
          </button>

          {/* Filter State Summary */}
          {activeFilterCount > 0 && (
            <div className="rounded-lg bg-amber-500/5 border border-amber-500/20 p-3">
              <p className="text-xs text-amber-300 font-mono">
                {activeFilterCount} filter{activeFilterCount !== 1 ? 's' : ''} active
              </p>
              <button
                onClick={() => setFilters([])}
                className="text-xs text-amber-400 hover:text-amber-300 mt-2 underline"
              >
                Clear all
              </button>
            </div>
          )}
        </div>

        {/* Right: Results Panel */}
        <div className="lg:col-span-3 space-y-5">
          {!results && !loading && (
            <div className="rounded-xl border border-slate-700/40 bg-gradient-to-br from-slate-800/30 to-slate-900/20 backdrop-blur-sm p-12 sm:p-16 text-center min-h-[400px] flex flex-col items-center justify-center transition-all hover:border-slate-600/60 hover:shadow-md hover:shadow-slate-950/50">
              <div className="text-5xl sm:text-6xl mb-6 opacity-60">✨</div>
              <h2 className="text-lg sm:text-xl font-bold text-slate-200 mb-3">Ready to backtest</h2>
              <p className="text-sm text-slate-400 max-w-md mb-8">Configure your filters on the left panel and click <span className="text-amber-400 font-semibold">Run Backtest</span> to analyze NSE stock performance</p>
              <div className="flex gap-4 text-xs text-slate-500">
                <div className="flex items-center gap-1.5">
                  <span className="text-amber-400">●</span> 500+ NSE stocks
                </div>
                <div className="flex items-center gap-1.5">
                  <span className="text-emerald-400">●</span> 5 years data
                </div>
              </div>
            </div>
          )}

          {loading && (
            <div className="rounded-xl border border-slate-700/40 bg-gradient-to-br from-slate-800/30 to-slate-900/20 backdrop-blur-sm p-12 sm:p-16 text-center min-h-[400px] flex flex-col items-center justify-center">
              <div className="relative w-16 h-16 mb-6">
                <div className="absolute inset-0 rounded-full border-2 border-amber-500/20" />
                <div className="absolute inset-0 rounded-full border-2 border-transparent border-t-amber-500 animate-spin" />
                <div className="absolute inset-1 rounded-full border border-slate-700/40" />
              </div>
              <h2 className="text-lg sm:text-xl font-bold text-slate-200 mb-2">Backtesting…</h2>
              <p className="text-sm text-slate-400">Simulating historical trades across your selected filters</p>
            </div>
          )}

          {results && !loading && (
            <>
              {/* WFO Controls */}
              {wfoMode && (
                <div className="rounded-xl border border-amber-600/40 bg-amber-500/8 p-4 space-y-3">
                  <h3 className="text-sm font-bold text-amber-300 uppercase tracking-wide">Walk-Forward Optimization</h3>
                  <div className="grid grid-cols-3 gap-4">
                    <div>
                      <label className="block text-xs text-slate-400 mb-2">In-Sample Days</label>
                      <input
                        type="range"
                        min="30"
                        max="365"
                        value={inSampleDays}
                        onChange={e => setInSampleDays(parseInt(e.target.value))}
                        className="w-full"
                      />
                      <div className="text-xs text-amber-300 font-mono mt-1">{inSampleDays} days</div>
                    </div>
                    <div>
                      <label className="block text-xs text-slate-400 mb-2">Out-of-Sample Days</label>
                      <input
                        type="range"
                        min="20"
                        max="180"
                        value={outSampleDays}
                        onChange={e => setOutSampleDays(parseInt(e.target.value))}
                        className="w-full"
                      />
                      <div className="text-xs text-amber-300 font-mono mt-1">{outSampleDays} days</div>
                    </div>
                    <div>
                      <label className="block text-xs text-slate-400 mb-2">Monte Carlo Runs</label>
                      <input
                        type="number"
                        min="100"
                        max="5000"
                        value={monteCarloRuns}
                        onChange={e => setMonteCarloRuns(parseInt(e.target.value))}
                        className="w-full px-2 py-1 rounded bg-slate-700/50 border border-slate-600 text-amber-300 text-sm font-mono"
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* KPI Cards — 10 Institutional Metrics */}
              <div className="grid grid-cols-2 md:grid-cols-5 lg:grid-cols-5 gap-3 sm:gap-4">
                {[
                  { label: 'Win Rate', value: results.win_rate.toFixed(1) + '%', color: 'amber' },
                  { label: 'Total Trades', value: results.total_trades.toLocaleString(), color: 'slate' },
                  { label: 'Avg Return', value: (results.avg_return > 0 ? '+' : '') + results.avg_return.toFixed(2) + '%', color: results.avg_return > 0 ? 'emerald' : 'rose' },
                  { label: 'Avg Win', value: '+' + results.avg_win_return.toFixed(2) + '%', color: 'emerald' },
                  { label: 'Avg Loss', value: results.avg_loss_return.toFixed(2) + '%', color: 'rose' },
                  { label: 'Sharpe Ratio', value: results.sharpe_ratio.toFixed(2), color: 'slate' },
                  { label: 'Sortino Ratio', value: (results.sortino_ratio || 0).toFixed(2), color: 'slate' },
                  { label: 'Calmar Ratio', value: (results.calmar_ratio || 0).toFixed(2), color: 'slate' },
                  { label: 'Max Drawdown', value: results.max_drawdown.toFixed(2) + '%', color: 'rose' },
                  { label: 'Profit Factor', value: (results.profit_factor || 0).toFixed(2), color: 'emerald' },
                ].map(({ label, value, color }) => (
                  <div
                    key={label}
                    className={clsx(
                      'rounded-xl border p-4 backdrop-blur-sm transition-all duration-200 hover:shadow-md hover:shadow-slate-950/50',
                      color === 'amber' && 'bg-amber-500/8 border-amber-500/30 hover:border-amber-500/50',
                      color === 'emerald' && 'bg-emerald-500/8 border-emerald-500/30 hover:border-emerald-500/50',
                      color === 'rose' && 'bg-rose-500/8 border-rose-500/30 hover:border-rose-500/50',
                      color === 'slate' && 'bg-slate-800/40 border-slate-700/40 hover:border-slate-600/60'
                    )}
                  >
                    <p className="text-xs text-slate-400 uppercase tracking-widest font-semibold mb-2">{label}</p>
                    <p
                      className={clsx(
                        'text-lg sm:text-2xl font-bold font-mono line-clamp-1',
                        color === 'amber' && 'text-amber-300',
                        color === 'emerald' && 'text-emerald-300',
                        color === 'rose' && 'text-rose-300',
                        color === 'slate' && 'text-slate-100'
                      )}
                    >
                      {value}
                    </p>
                  </div>
                ))}
              </div>

              {/* Equity Curve */}
              {results.equity_curve.length > 0 && (
                <div className="rounded-xl border border-slate-800 bg-slate-800/30 backdrop-blur-sm p-4 sm:p-6 overflow-hidden">
                  <h3 className="text-sm font-bold text-slate-200 mb-4 uppercase tracking-wide">Equity Curve</h3>
                  <LWEquityCurve data={results.equity_curve} />
                </div>
              )}

              {/* Monte Carlo Drawdown Distribution */}
              {results.monte_carlo && (
                <div className="rounded-xl border border-slate-800 bg-slate-800/30 backdrop-blur-sm p-4 sm:p-6 overflow-hidden">
                  <h3 className="text-sm font-bold text-slate-200 mb-4 uppercase tracking-wide">Monte Carlo Drawdown Distribution</h3>
                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart
                      data={results.monte_carlo.histogram.map((count, idx) => ({
                        bucket: idx,
                        count,
                      }))}
                    >
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                      <XAxis
                        dataKey="bucket"
                        tick={{ fontSize: 11, fill: '#94a3b8' }}
                        label={{ value: 'Max Drawdown Percentile', position: 'insideBottomRight', offset: -5, fill: '#94a3b8', fontSize: 11 }}
                      />
                      <YAxis tick={{ fontSize: 11, fill: '#94a3b8' }} label={{ value: 'Frequency', angle: -90, position: 'insideLeft', fill: '#94a3b8' }} />
                      <Tooltip
                        contentStyle={{
                          backgroundColor: '#1e293b',
                          border: '1px solid #475569',
                          borderRadius: '8px',
                          color: '#f1f5f9',
                        }}
                        formatter={(v: number) => [v, 'Count']}
                      />
                      <Bar dataKey="count" fill="#f59e0b" radius={[4, 4, 0, 0]} />
                      {/* Reference lines for percentiles */}
                      <ReferenceLine
                        x={Math.floor(results.monte_carlo.histogram.length * 0.5)}
                        stroke="#94a3b8"
                        strokeDasharray="4 2"
                        label={{ value: `p50: ${results.monte_carlo.p50.toFixed(1)}%`, position: 'top', fill: '#94a3b8', fontSize: 10 }}
                      />
                      <ReferenceLine
                        x={Math.floor(results.monte_carlo.histogram.length * 0.95)}
                        stroke="#ef4444"
                        strokeDasharray="4 2"
                        label={{ value: `p95: ${results.monte_carlo.p95.toFixed(1)}%`, position: 'top', fill: '#ef4444', fontSize: 10 }}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                  <div className="mt-4 grid grid-cols-5 gap-2 text-center">
                    <div className="rounded-lg bg-slate-700/40 p-2">
                      <p className="text-xs text-slate-400">p5</p>
                      <p className="text-sm font-bold text-slate-200">{results.monte_carlo.p5.toFixed(1)}%</p>
                    </div>
                    <div className="rounded-lg bg-slate-700/40 p-2">
                      <p className="text-xs text-slate-400">p25</p>
                      <p className="text-sm font-bold text-slate-200">{results.monte_carlo.p25.toFixed(1)}%</p>
                    </div>
                    <div className="rounded-lg bg-amber-500/20 border border-amber-500/40 p-2">
                      <p className="text-xs text-amber-300">p50</p>
                      <p className="text-sm font-bold text-amber-200">{results.monte_carlo.p50.toFixed(1)}%</p>
                    </div>
                    <div className="rounded-lg bg-slate-700/40 p-2">
                      <p className="text-xs text-slate-400">p75</p>
                      <p className="text-sm font-bold text-slate-200">{results.monte_carlo.p75.toFixed(1)}%</p>
                    </div>
                    <div className="rounded-lg bg-rose-500/20 border border-rose-500/40 p-2">
                      <p className="text-xs text-rose-300">p95</p>
                      <p className="text-sm font-bold text-rose-200">{results.monte_carlo.p95.toFixed(1)}%</p>
                    </div>
                  </div>
                </div>
              )}

              {/* Trade Explorer (Unified View) */}
              {results.trades.length > 0 && (
                <>
                  <div className="flex items-center justify-between">
                    <h2 className="text-lg sm:text-xl font-bold text-slate-100 flex items-center gap-2">
                      🎯 Trade Explorer
                      <span className="text-xs bg-amber-500/20 text-amber-300 px-2 py-1 rounded-full">{results.trades.length} trades</span>
                    </h2>
                  </div>
                  <div className="rounded-xl border border-slate-700/40 bg-slate-800/30 backdrop-blur-sm overflow-hidden">
                    <TradeExplorer trades={results.trades} title="Trade Explorer" isDark={isDark} onTradeClick={openTradeChart} showHeader={false} showFooter={false} />
                  </div>
                </>
              )}


              {/* Export / Save for Future */}
              <div className="rounded-lg bg-slate-800/20 border border-slate-700/30 p-3 sm:p-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
                <p className="text-xs text-slate-500">📌 Save backtest results for later comparison</p>
                <button className="px-3 py-1 rounded-lg bg-slate-700/40 text-slate-300 text-xs font-semibold hover:bg-slate-700/60 whitespace-nowrap">
                  Export
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Trade Chart Modal */}
      {selectedTrade && (
        <div className="fixed inset-0 bg-black/70 backdrop-blur-md z-50 flex items-center justify-center p-4 animate-in fade-in duration-300">
          <div className="bg-gradient-to-b from-slate-900 to-slate-950 rounded-xl border border-slate-700/50 w-full max-w-4xl max-h-[90vh] overflow-y-auto shadow-2xl shadow-black/80">
            {/* Modal Header */}
            <div className="sticky top-0 bg-gradient-to-r from-slate-800 to-slate-850 border-b border-slate-700/50 p-4 sm:p-6 flex items-start justify-between backdrop-blur-sm">
              <div>
                <h2 className="text-lg sm:text-xl font-bold text-slate-100">
                  {selectedTrade.ticker}
                </h2>
                <p className="text-sm text-slate-400 mt-1">
                  Entry: {selectedTrade.date} @ ₹{selectedTrade.entry_price.toFixed(0)} →{' '}
                  <span className={selectedTrade.is_win ? 'text-emerald-400' : 'text-rose-400'}>
                    {selectedTrade.is_win ? '✓' : '✗'} {selectedTrade.return_pct > 0 ? '+' : ''}
                    {selectedTrade.return_pct.toFixed(2)}%
                  </span>
                </p>
              </div>
              <button
                onClick={closeTradeChart}
                className="text-slate-400 hover:text-slate-200 text-2xl leading-none"
              >
                ✕
              </button>
            </div>

            {/* Modal Content */}
            <div className="p-4 sm:p-6 space-y-4">
              {/* Period & Chart Type Selector */}
              <div className="flex flex-col sm:flex-row gap-3 sm:gap-4 items-start sm:items-center justify-between border-b border-slate-700 pb-4">
                <div className="flex gap-2 flex-wrap">
                  {(['5D', '1M', '3M', '6M', '1Y', '2Y'] as const).map(period => (
                    <button
                      key={period}
                      onClick={() => setChartPeriod(period)}
                      className={clsx(
                        'px-3 py-1.5 rounded text-xs font-semibold transition-all',
                        chartPeriod === period
                          ? 'bg-amber-500/30 text-amber-300 ring-1 ring-amber-500/50'
                          : 'bg-slate-700/30 text-slate-400 hover:text-slate-300'
                      )}
                    >
                      {period}
                    </button>
                  ))}
                </div>
                <div className="flex gap-2">
                  {(['line', 'candle', 'area'] as const).map(type => (
                    <button
                      key={type}
                      onClick={() => setChartType(type)}
                      className={clsx(
                        'px-3 py-1.5 rounded text-xs font-semibold transition-all',
                        chartType === type
                          ? 'bg-amber-500/30 text-amber-300 ring-1 ring-amber-500/50'
                          : 'bg-slate-700/30 text-slate-400 hover:text-slate-300'
                      )}
                    >
                      {type === 'candle' ? '🕯' : type === 'area' ? '📊' : '📈'} {type}
                    </button>
                  ))}
                </div>
              </div>

              {chartLoading ? (
                <div className="text-center py-12">
                  <div className="inline-block w-8 h-8 border-2 border-amber-500 border-t-transparent rounded-full animate-spin mb-3" />
                  <p className="text-slate-400">Loading {chartPeriod} data...</p>
                </div>
              ) : chartData.length > 0 ? (
                <div className="space-y-4">
                  {chartType === 'candle' ? (
                    // SVG-based candlestick chart
                    <svg width="100%" height="400" viewBox="0 0 800 400" className="border border-slate-700 rounded bg-slate-800/20">
                      {/* Grid */}
                      <g stroke="#334155" strokeWidth={0.5} strokeDasharray="3 3">
                        {Array(5).fill(0).map((_, i) => (
                          <line
                            key={`hline-${i}`}
                            x1="30"
                            x2="770"
                            y1={10 + (i * 95)}
                            y2={10 + (i * 95)}
                          />
                        ))}
                      </g>

                      {/* Y-axis labels */}
                      <g fill="#94a3b8" fontSize="10">
                        {Array(5).fill(0).map((_, i) => {
                          const minPrice = Math.min(...chartData.map((d: any) => d.low))
                          const maxPrice = Math.max(...chartData.map((d: any) => d.high))
                          const range = maxPrice - minPrice || 1
                          const price = maxPrice - (i * range / 4)
                          return (
                            <text key={`ylabel-${i}`} x="25" y={15 + (i * 95)} textAnchor="end">
                              ₹{price.toFixed(0)}
                            </text>
                          )
                        })}
                      </g>

                      {/* Candlesticks */}
                      {renderCandlesticks(chartData, null, null)}

                      {/* Entry line */}
                      <g stroke="#f59e0b" strokeWidth={1} strokeDasharray="5 5">
                        <line
                          x1="30"
                          x2="770"
                          y1={10 + (1 - (selectedTrade.entry_price - Math.min(...chartData.map(d => d.low))) / (Math.max(...chartData.map(d => d.high)) - Math.min(...chartData.map(d => d.low)) || 1)) * 380}
                          y2={10 + (1 - (selectedTrade.entry_price - Math.min(...chartData.map(d => d.low))) / (Math.max(...chartData.map(d => d.high)) - Math.min(...chartData.map(d => d.low)) || 1)) * 380}
                        />
                      </g>

                      {/* Exit line */}
                      <g stroke={selectedTrade.is_win ? '#10b981' : '#ef4444'} strokeWidth={1} strokeDasharray="5 5">
                        <line
                          x1="30"
                          x2="770"
                          y1={10 + (1 - (selectedTrade.exit_price - Math.min(...chartData.map(d => d.low))) / (Math.max(...chartData.map(d => d.high)) - Math.min(...chartData.map(d => d.low)) || 1)) * 380}
                          y2={10 + (1 - (selectedTrade.exit_price - Math.min(...chartData.map(d => d.low))) / (Math.max(...chartData.map(d => d.high)) - Math.min(...chartData.map(d => d.low)) || 1)) * 380}
                        />
                      </g>

                      {/* X-axis */}
                      <line x1="30" x2="770" y1="390" y2="390" stroke="#475569" strokeWidth={1} />

                      {/* Date labels */}
                      <g fill="#94a3b8" fontSize="9" textAnchor="middle">
                        {chartData.length > 0 && [0, Math.floor(chartData.length / 3), Math.floor(2 * chartData.length / 3), chartData.length - 1]
                          .filter(i => i >= 0 && i < chartData.length)
                          .map((i, idx) => {
                            const xPos = 30 + (i / (chartData.length - 1 || 1)) * 740
                            return (
                              <text key={`xlabel-${idx}`} x={xPos} y="405">
                                {chartData[i].date.slice(5)}
                              </text>
                            )
                          })}
                      </g>
                    </svg>
                  ) : (
                    <ResponsiveContainer width="100%" height={400}>
                      <ComposedChart data={chartData} margin={{ top: 10, right: 30, left: 0, bottom: 10 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                        <XAxis
                          dataKey="date"
                          tick={{ fontSize: 11, fill: '#94a3b8' }}
                          tickFormatter={d => d.slice(5)}
                        />
                        <YAxis yAxisId="left" tick={{ fontSize: 11, fill: '#94a3b8' }} />
                        <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 11, fill: '#94a3b8' }} />
                        <Tooltip
                          contentStyle={{
                            backgroundColor: '#1e293b',
                            border: '1px solid #475569',
                            borderRadius: '8px',
                            color: '#f1f5f9',
                          }}
                          formatter={(v: any) => v && Array.isArray(v) ? v : [v?.toFixed?.(0) || v, 'Value']}
                          labelFormatter={(label: string) => `${label}`}
                        />
                        <Legend wrapperStyle={{ fontSize: 12 }} />
                        <Brush dataKey="date" height={20} stroke="#475569" travellerWidth={8} />

                        {/* Volume bars on right axis */}
                        <Bar yAxisId="right" dataKey="volume" fill="#475569" opacity={0.3} />

                        {/* Price lines */}
                        {chartType === 'line' && (
                          <>
                            <Line
                              yAxisId="left"
                              type="monotone"
                              dataKey="close"
                              stroke="#f59e0b"
                              dot={false}
                              strokeWidth={2}
                              name="Close Price"
                            />
                            <Line
                              yAxisId="left"
                              type="monotone"
                              dataKey="open"
                              stroke="#94a3b8"
                              dot={false}
                              strokeWidth={1}
                              strokeDasharray="5 5"
                              name="Open Price"
                            />
                          </>
                        )}

                        {/* Area chart */}
                        {chartType === 'area' && (
                          <Line
                            yAxisId="left"
                            type="monotone"
                            dataKey="close"
                            stroke="#f59e0b"
                            fill="#f59e0b"
                            fillOpacity={0.2}
                            dot={false}
                            strokeWidth={2}
                            name="Close Price"
                          />
                        )}

                        {/* Entry & exit reference lines */}
                        <ReferenceLine
                          yAxisId="left"
                          y={selectedTrade.entry_price}
                          stroke="#f59e0b"
                          strokeDasharray="5 5"
                          label={{ value: `Entry ₹${selectedTrade.entry_price.toFixed(0)}`, position: 'right', fill: '#f59e0b', fontSize: 10 }}
                          name="Entry Price"
                        />
                        <ReferenceLine
                          yAxisId="left"
                          y={selectedTrade.exit_price}
                          stroke={selectedTrade.is_win ? '#10b981' : '#ef4444'}
                          strokeDasharray="5 5"
                          label={{ value: `Exit ₹${selectedTrade.exit_price.toFixed(0)}`, position: 'right', fill: selectedTrade.is_win ? '#10b981' : '#ef4444', fontSize: 10 }}
                          name="Exit Price"
                        />
                      </ComposedChart>
                    </ResponsiveContainer>
                  )}

                  {/* Trade Details */}
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                    <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700">
                      <p className="text-xs text-slate-400 uppercase tracking-wide mb-1">Entry Price</p>
                      <p className="text-lg font-bold text-slate-200 font-mono">₹{selectedTrade.entry_price.toFixed(0)}</p>
                    </div>
                    <div className="bg-slate-800/50 rounded-lg p-3 border border-slate-700">
                      <p className="text-xs text-slate-400 uppercase tracking-wide mb-1">Exit Price</p>
                      <p className="text-lg font-bold text-slate-200 font-mono">₹{selectedTrade.exit_price.toFixed(0)}</p>
                    </div>
                    <div
                      className={clsx(
                        'rounded-lg p-3 border',
                        selectedTrade.is_win
                          ? 'bg-emerald-500/5 border-emerald-500/20'
                          : 'bg-rose-500/5 border-rose-500/20'
                      )}
                    >
                      <p className="text-xs text-slate-400 uppercase tracking-wide mb-1">Return</p>
                      <p
                        className={clsx(
                          'text-lg font-bold font-mono',
                          selectedTrade.is_win ? 'text-emerald-400' : 'text-rose-400'
                        )}
                      >
                        {selectedTrade.return_pct > 0 ? '+' : ''}{selectedTrade.return_pct.toFixed(2)}%
                      </p>
                    </div>
                  </div>
                </div>
              ) : (
                <p className="text-slate-400 text-center py-8">No chart data available for this stock</p>
              )}
            </div>
          </div>
        </div>
      )}

    </div>
  )
}
