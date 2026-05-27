'use client'

import clsx from 'clsx'
import { useEffect, useState, useCallback, useRef } from 'react'
import {
  createChart,
  ColorType,
  CrosshairMode,
  type IChartApi,
  type ISeriesApi,
} from 'lightweight-charts'
import { getStockDetail, getStockOHLCV, getDataIntraday, getDataOHLCV, getDataLiveQuote } from '@/lib/api'
import { useTheme } from '@/context/ThemeContext'
import { useLiveQuotes } from '@/context/AppContext'

interface StockDetailModalProps {
  ticker: string | null
  onClose: () => void
}

type PeriodDays = 'intraday' | 5 | 30 | 90 | 252 | 756 | 1260
type ChartType = 'line' | 'candle'

const PERIODS: { label: string; days: PeriodDays }[] = [
  { label: '⚡ Today', days: 'intraday' },
  { label: '5D',  days: 5 },
  { label: '1M',  days: 30 },
  { label: '3M',  days: 90 },
  { label: '1Y',  days: 252 },
  { label: '3Y',  days: 756 },
  { label: '5Y',  days: 1260 },
]

// ── Lightweight-charts stock chart ────────────────────────────────────────────

interface LWStockChartProps {
  ohlcv: Array<{ date: string; open: number; high: number; low: number; close: number; volume: number }>
  chartType: ChartType
  isDark: boolean
}

function LWStockChart({ ohlcv, chartType, isDark }: LWStockChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef     = useRef<IChartApi | null>(null)
  const priceRef     = useRef<ISeriesApi<any> | null>(null)
  const volumeRef    = useRef<ISeriesApi<'Histogram'> | null>(null)

  const bg          = isDark ? '#0f172a' : '#ffffff'
  const textColor   = isDark ? '#94a3b8' : '#6b7280'
  const gridColor   = isDark ? '#1e293b' : '#f3f4f6'
  const borderColor = isDark ? '#334155' : '#e5e7eb'

  // Recreate chart whenever theme or chart type changes
  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      layout: { background: { type: ColorType.Solid, color: bg }, textColor },
      grid:   { vertLines: { color: gridColor }, horzLines: { color: gridColor } },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor },
      timeScale: { borderColor, timeVisible: false, secondsVisible: false },
      width:  containerRef.current.clientWidth,
      height: 300,
    })

    const priceSeries: ISeriesApi<any> = chartType === 'candle'
      ? chart.addCandlestickSeries({
          upColor: '#10b981', downColor: '#f43f5e',
          borderUpColor: '#10b981', borderDownColor: '#f43f5e',
          wickUpColor:   '#10b981', wickDownColor:   '#f43f5e',
        })
      : chart.addLineSeries({ color: '#4f46e5', lineWidth: 2 })

    const volumeSeries = chart.addHistogramSeries({
      color: '#c7d2fe',
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    })
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })

    priceRef.current  = priceSeries
    volumeRef.current = volumeSeries
    chartRef.current  = chart

    const ro = new ResizeObserver(entries => {
      if (entries[0] && chartRef.current) {
        chartRef.current.applyOptions({ width: entries[0].contentRect.width })
      }
    })
    ro.observe(containerRef.current)

    return () => {
      ro.disconnect()
      chart.remove()
      chartRef.current  = null
      priceRef.current  = null
      volumeRef.current = null
    }
  }, [isDark, chartType]) // eslint-disable-line react-hooks/exhaustive-deps

  // Load data into series whenever ohlcv or chartType changes
  useEffect(() => {
    if (!priceRef.current || !volumeRef.current || !ohlcv.length) return

    if (chartType === 'candle') {
      priceRef.current.setData(
        ohlcv.map(r => ({ time: r.date as any, open: r.open, high: r.high, low: r.low, close: r.close }))
      )
    } else {
      priceRef.current.setData(
        ohlcv.map(r => ({ time: r.date as any, value: r.close }))
      )
    }

    volumeRef.current.setData(
      ohlcv.map(r => ({
        time:  r.date as any,
        value: r.volume,
        color: r.close >= r.open ? '#10b98155' : '#f43f5e55',
      }))
    )

    chartRef.current?.timeScale().fitContent()
  }, [ohlcv, chartType])

  return (
    <div className={clsx('rounded-xl overflow-hidden border', isDark ? 'border-slate-700' : 'border-gray-200')}>
      <div ref={containerRef} className="w-full" />
    </div>
  )
}

// ── Main modal ────────────────────────────────────────────────────────────────

export function StockDetailModal({ ticker, onClose }: StockDetailModalProps) {
  const { isDark }      = useTheme()
  const { liveQuotes }  = useLiveQuotes()
  const liveQ           = ticker ? liveQuotes[ticker.toUpperCase()] : null

  const [detail, setDetail]             = useState<any>(null)
  const [loading, setLoading]           = useState(false)
  const [error, setError]               = useState<string | null>(null)
  const [activeTab, setActiveTab]       = useState<'details' | 'chart'>('details')
  const [ohlcv, setOhlcv]               = useState<any[]>([])
  const [chartLoading, setChartLoading] = useState(false)
  const [chartError, setChartError]     = useState<string | null>(null)
  const [period, setPeriod]             = useState<PeriodDays>(90)
  const [chartType, setChartType]       = useState<ChartType>('candle')
  const [isIntraday, setIsIntraday]     = useState(false)
  const [livePrice, setLivePrice]       = useState<number | null>(null)

  useEffect(() => {
    if (!ticker) return
    setLoading(true)
    setError(null)
    setDetail(null)
    setActiveTab('details')
    setLivePrice(null)
    // Fetch detail + live price in parallel
    Promise.all([
      getStockDetail(ticker),
      getDataLiveQuote(ticker).catch(() => null),
    ])
      .then(([detailRes, quoteRes]) => {
        setDetail(detailRes.data)
        const q = quoteRes?.data?.quote
        if (q) {
          const p = q.ltp ?? q.last_price ?? q.lastPrice ?? q.price
          if (p) setLivePrice(Number(p))
        }
      })
      .catch(err => setError(err.response?.data?.detail || 'Failed to load stock detail'))
      .finally(() => setLoading(false))
  }, [ticker])

  // Merge WS live price into livePrice state
  useEffect(() => {
    if (liveQ?.ltp !== undefined) setLivePrice(liveQ.ltp)
  }, [liveQ?.ltp])

  const fetchOHLCV = useCallback(async (p: PeriodDays) => {
    if (!ticker) return
    setChartLoading(true)
    setChartError(null)
    const intraday = p === 'intraday'
    setIsIntraday(intraday)
    try {
      if (intraday) {
        // Use data-service proxy for intraday bars
        const res = await getDataIntraday(ticker, '5minute')
        const rows = (res.data?.data || []).map((r: any) => ({
          date:   r.date || r.datetime || r.timestamp,
          open:   r.open,  high:   r.high,
          low:    r.low,   close:  r.close,
          volume: r.volume ?? 0,
        })).filter((r: any) => r.date && r.close)
        if (rows.length === 0) {
          // Fallback: get last 5 days from data proxy ohlcv
          const fb = await getDataOHLCV(ticker)
          const d = (fb.data?.data || []).slice(-10).map((r: any) => ({
            date: r.date, open: r.open, high: r.high,
            low: r.low, close: r.close, volume: r.volume ?? 0,
          }))
          setOhlcv(d)
        } else {
          setOhlcv(rows)
        }
      } else {
        // Try data-service proxy first (richer data), fall back to ui-api stock endpoint
        try {
          const res = await getDataOHLCV(ticker)
          const all: any[] = res.data?.data || []
          // Slice to requested days from the end
          const sliced = all.slice(-Number(p)).map((r: any) => ({
            date: r.date, open: r.open, high: r.high,
            low: r.low, close: r.close, volume: r.volume ?? 0,
          }))
          setOhlcv(sliced.length ? sliced : [])
        } catch {
          // Fallback to existing ui-api stock OHLCV endpoint
          const res = await getStockOHLCV(ticker, p as number)
          setOhlcv(res.data?.rows || [])
        }
      }
    } catch (err: any) {
      setChartError(err.response?.data?.detail || 'Failed to load chart data')
    } finally {
      setChartLoading(false)
    }
  }, [ticker])

  useEffect(() => {
    if (activeTab === 'chart') fetchOHLCV(period)
  }, [activeTab, period, fetchOHLCV])

  if (!ticker) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4"
      onClick={e => e.target === e.currentTarget && onClose()}
    >
      <div className={clsx(
        'w-full max-w-4xl max-h-[92vh] overflow-y-auto rounded-2xl border shadow-2xl',
        isDark ? 'bg-slate-900 border-slate-700' : 'bg-white border-gray-200',
      )}>
        {/* Header */}
        <div className={clsx(
          'sticky top-0 border-b px-6 py-4 flex justify-between items-center z-10',
          isDark ? 'bg-slate-900 border-slate-700' : 'bg-white border-gray-200',
        )}>
          <div className="flex items-center gap-3">
            <div className={clsx('w-9 h-9 rounded-xl border flex items-center justify-center',
              isDark ? 'bg-indigo-900/40 border-indigo-700' : 'bg-indigo-100 border-indigo-200',
            )}>
              <span className="text-sm font-black text-indigo-500">{ticker.charAt(0)}</span>
            </div>
            <div>
              <div className="flex items-center gap-3">
                <h2 className={clsx('text-xl font-black', isDark ? 'text-slate-100' : 'text-gray-900')}>{ticker}</h2>
                {livePrice !== null && (
                  <span className={clsx(
                    'flex items-center gap-1 text-sm font-bold font-mono px-2 py-0.5 rounded-lg border',
                    isDark ? 'bg-emerald-900/30 border-emerald-700/40 text-emerald-300' : 'bg-emerald-50 border-emerald-200 text-emerald-700',
                  )}>
                    <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                    ₹{livePrice.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
                  </span>
                )}
              </div>
              {detail?.fundamentals?.sector && (
                <p className={clsx('text-xs', isDark ? 'text-slate-400' : 'text-gray-400')}>{detail.fundamentals.sector}</p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className={clsx('flex items-center gap-1 rounded-lg p-1', isDark ? 'bg-slate-800' : 'bg-gray-100')}>
              <button
                onClick={() => setActiveTab('details')}
                className={clsx(
                  'px-3 py-1.5 rounded-md text-xs font-semibold transition-all',
                  activeTab === 'details'
                    ? (isDark ? 'bg-slate-700 shadow text-amber-400' : 'bg-white shadow text-indigo-600')
                    : (isDark ? 'text-slate-400 hover:text-slate-200' : 'text-gray-500 hover:text-gray-700'),
                )}
              >
                Details
              </button>
              <button
                onClick={() => setActiveTab('chart')}
                className={clsx(
                  'px-3 py-1.5 rounded-md text-xs font-semibold transition-all',
                  activeTab === 'chart'
                    ? (isDark ? 'bg-slate-700 shadow text-amber-400' : 'bg-white shadow text-indigo-600')
                    : (isDark ? 'text-slate-400 hover:text-slate-200' : 'text-gray-500 hover:text-gray-700'),
                )}
              >
                📈 Chart
              </button>
            </div>
            <button
              onClick={onClose}
              className={clsx(
                'text-xl leading-none w-7 h-7 flex items-center justify-center rounded-lg transition-colors',
                isDark ? 'text-slate-400 hover:text-slate-200 hover:bg-slate-700' : 'text-gray-400 hover:text-gray-700 hover:bg-gray-100',
              )}
            >
              ✕
            </button>
          </div>
        </div>

        <div className="p-6">
          {loading && (
            <div className="space-y-3">
              {Array(4).fill(0).map((_, i) => (
                <div key={i} className={clsx('h-14 animate-pulse rounded-xl', isDark ? 'bg-slate-800' : 'bg-gray-100')} />
              ))}
            </div>
          )}

          {error && (
            <div className="rounded-xl bg-rose-50 border border-rose-200 p-4 text-rose-600 text-sm">{error}</div>
          )}

          {/* ── Details Tab ─────────────────────────────────────────────── */}
          {!loading && !error && detail && activeTab === 'details' && (
            <div className="space-y-6">
              <Section title="OHLCV Data" isDark={isDark}>
                <div className="grid grid-cols-2 gap-3">
                  <Stat label="Total Rows" value={detail.ohlcv.total_rows.toLocaleString()} isDark={isDark} />
                  <Stat label="Data Density" value={`${detail.ohlcv.data_density_pct.toFixed(1)}%`} isDark={isDark} />
                  <div className="col-span-2">
                    <Stat label="Date Range" value={`${detail.ohlcv.first_date} → ${detail.ohlcv.latest_date}`} mono isDark={isDark} />
                  </div>
                  <Stat label="Missing Days" value={detail.ohlcv.missing_rows} isDark={isDark}
                    color={detail.ohlcv.missing_rows > 20 ? 'rose' : 'emerald'} />
                  <Stat label="Last Updated" value={`${detail.data_quality.days_since_update} day(s) ago`} isDark={isDark}
                    color={detail.data_quality.days_since_update <= 1 ? 'emerald' : 'amber'} />
                </div>
              </Section>

              {(detail.index_name || detail.nifty_bucket || detail.midcap_bucket) && (
                <Section title="Index Membership" isDark={isDark}>
                  <div className="grid grid-cols-2 gap-3">
                    <Stat label="Index" value={detail.index_name ?? '—'} isDark={isDark} />
                    <Stat label="Nifty Bucket" value={detail.nifty_bucket ? `Nifty ${detail.nifty_bucket}` : '—'} isDark={isDark} />
                    <div className="col-span-2">
                      <Stat label="Midcap Bucket" value={detail.midcap_bucket ? `Midcap ${detail.midcap_bucket}` : '—'} isDark={isDark} />
                    </div>
                  </div>
                </Section>
              )}

              {detail.fundamentals?.available && (
                <Section title="Fundamentals" isDark={isDark}>
                  <div className="grid grid-cols-2 gap-3">
                    <Stat label="P/E Ratio" value={fmt(detail.fundamentals.trailing_pe, '.2f')} isDark={isDark} />
                    <Stat label="P/B Ratio" value={fmt(detail.fundamentals.price_to_book, '.2f')} isDark={isDark} />
                    <Stat label="ROE" value={fmt(detail.fundamentals.roe, '%')} isDark={isDark} />
                    <Stat label="D/E Ratio" value={fmt(detail.fundamentals.debt_to_equity, '.2f')} isDark={isDark} />
                    <Stat label="Dividend Yield" value={fmt(detail.fundamentals.dividend_yield, '%')} isDark={isDark} />
                    <Stat label="Sector" value={detail.fundamentals.sector ?? '—'} isDark={isDark} />
                  </div>
                </Section>
              )}

              {detail.upcoming_events?.length > 0 && (
                <Section title="Upcoming Events" isDark={isDark}>
                  <div className="space-y-2">
                    {detail.upcoming_events.map((ev: any, i: number) => (
                      <div key={i} className={clsx(
                        'flex justify-between items-center rounded-lg border px-4 py-2.5',
                        isDark ? 'bg-slate-800 border-slate-700' : 'bg-gray-50 border-gray-200',
                      )}>
                        <span className={clsx('text-sm font-medium', isDark ? 'text-slate-200' : 'text-gray-700')}>{ev.type}</span>
                        <span className="text-xs font-mono text-indigo-500">{ev.date}</span>
                      </div>
                    ))}
                  </div>
                </Section>
              )}

              <Section title="Corporate History" isDark={isDark}>
                <div className="grid grid-cols-2 gap-3">
                  <Stat label="Dividends" value={detail.dividends.count} isDark={isDark} />
                  <Stat label="Stock Splits" value={detail.splits.count} isDark={isDark} />
                </div>
              </Section>

              <div className={clsx(
                'rounded-xl border p-4',
                detail.data_quality.overall === 'excellent' ? 'border-emerald-700 bg-emerald-900/20' :
                detail.data_quality.overall === 'good'      ? 'border-teal-700 bg-teal-900/20' :
                detail.data_quality.overall === 'fair'      ? 'border-amber-700 bg-amber-900/20' :
                                                              (isDark ? 'border-slate-700 bg-slate-800/30' : 'border-gray-200 bg-gray-50'),
              )}>
                <p className={clsx('text-xs font-medium mb-2', isDark ? 'text-slate-400' : 'text-gray-500')}>Data Health</p>
                <div className="flex items-center gap-4">
                  <div>
                    <p className={clsx('text-xs', isDark ? 'text-slate-400' : 'text-gray-400')}>Density</p>
                    <p className={clsx('text-lg font-black mt-0.5', isDark ? 'text-slate-100' : 'text-gray-900')}>
                      {detail.ohlcv.data_density_pct.toFixed(1)}%
                    </p>
                  </div>
                  <div className={clsx('w-px h-10', isDark ? 'bg-slate-700' : 'bg-gray-200')} />
                  <div>
                    <p className={clsx('text-xs', isDark ? 'text-slate-400' : 'text-gray-400')}>Last updated</p>
                    <p className={clsx('text-lg font-black mt-0.5',
                      detail.data_quality.days_since_update <= 1 ? 'text-emerald-500' :
                      detail.data_quality.days_since_update <= 3 ? 'text-amber-500' :
                      (isDark ? 'text-slate-300' : 'text-gray-600'),
                    )}>
                      {detail.data_quality.days_since_update}d ago
                    </p>
                  </div>
                  <div className={clsx('w-px h-10', isDark ? 'bg-slate-700' : 'bg-gray-200')} />
                  <div>
                    <p className={clsx('text-xs', isDark ? 'text-slate-400' : 'text-gray-400')}>Total rows</p>
                    <p className={clsx('text-lg font-black mt-0.5', isDark ? 'text-slate-100' : 'text-gray-900')}>
                      {detail.ohlcv.total_rows.toLocaleString()}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ── Chart Tab ─────────────────────────────────────────────── */}
          {activeTab === 'chart' && (
            <div className="space-y-4">
              {/* Controls */}
              <div className="flex items-center justify-between flex-wrap gap-2">
                <div className="flex items-center gap-2">
                  <p className={clsx('text-sm font-semibold', isDark ? 'text-slate-200' : 'text-gray-700')}>
                    {ticker} · {
                      period === 'intraday' ? 'Today (Intraday)' :
                      period <= 30  ? `${period}D` :
                      period === 90 ? '3M' :
                      period === 252 ? '1Y' :
                      period === 756 ? '3Y' : '5Y'
                    }
                  </p>
                  {isIntraday && (
                    <span className={clsx(
                      'flex items-center gap-1 text-[10px] font-bold px-2 py-0.5 rounded-full border',
                      isDark ? 'bg-emerald-900/30 border-emerald-700/40 text-emerald-400' : 'bg-emerald-50 border-emerald-300 text-emerald-700',
                    )}>
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
                      ICICI LIVE
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2">
                  {/* Chart type toggle */}
                  <div className={clsx('flex items-center gap-1 rounded-lg p-1', isDark ? 'bg-slate-800' : 'bg-gray-100')}>
                    {(['line', 'candle'] as ChartType[]).map(ct => (
                      <button
                        key={ct}
                        onClick={() => setChartType(ct)}
                        className={clsx(
                          'px-2.5 py-1 rounded-md text-xs font-bold transition-all capitalize',
                          chartType === ct
                            ? (isDark ? 'bg-slate-700 shadow text-amber-400' : 'bg-white shadow text-indigo-600')
                            : (isDark ? 'text-slate-400 hover:text-slate-200' : 'text-gray-500 hover:text-gray-700'),
                        )}
                      >
                        {ct === 'line' ? 'Line' : 'Candle'}
                      </button>
                    ))}
                  </div>
                  {/* Period selector */}
                  <div className={clsx('flex items-center gap-1 rounded-lg p-1', isDark ? 'bg-slate-800' : 'bg-gray-100')}>
                    {PERIODS.map(({ label, days }) => (
                      <button
                        key={days}
                        onClick={() => setPeriod(days)}
                        className={clsx(
                          'px-2.5 py-1 rounded-md text-xs font-bold transition-all',
                          period === days
                            ? (isDark ? 'bg-slate-700 shadow text-amber-400' : 'bg-white shadow text-indigo-600')
                            : (isDark ? 'text-slate-400 hover:text-slate-200' : 'text-gray-500 hover:text-gray-700'),
                        )}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {chartLoading && (
                <div className={clsx('h-72 animate-pulse rounded-xl flex items-center justify-center',
                  isDark ? 'bg-slate-800' : 'bg-gray-100',
                )}>
                  <span className={clsx('text-sm', isDark ? 'text-slate-400 animate-pulse' : 'text-gray-400')}>
                    Loading chart…
                  </span>
                </div>
              )}

              {chartError && (
                <div className="rounded-xl bg-amber-50 border border-amber-200 p-4 text-amber-700 text-sm">
                  {chartError}
                </div>
              )}

              {!chartLoading && !chartError && ohlcv.length > 0 && (
                <LWStockChart ohlcv={ohlcv} chartType={chartType} isDark={isDark} />
              )}

              {!chartLoading && !chartError && ohlcv.length === 0 && (
                <div className={clsx(
                  'rounded-xl border p-12 text-center',
                  isDark ? 'border-slate-700 bg-slate-800/30' : 'border-gray-200 bg-gray-50',
                )}>
                  <p className={clsx('text-sm', isDark ? 'text-slate-400' : 'text-gray-400')}>
                    No price history available for {ticker}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Sub-components ────────────────────────────────────────────────────────────

function Section({ title, children, isDark }: { title: string; children: React.ReactNode; isDark: boolean }) {
  return (
    <div>
      <h3 className={clsx('text-xs font-bold uppercase tracking-wider mb-3', isDark ? 'text-slate-400' : 'text-gray-400')}>
        {title}
      </h3>
      {children}
    </div>
  )
}

function Stat({ label, value, color = 'slate', mono = false, isDark }: {
  label: string; value: any; color?: 'slate' | 'emerald' | 'rose' | 'amber'; mono?: boolean; isDark: boolean
}) {
  const valueColors = {
    slate:   isDark ? 'text-slate-100' : 'text-gray-900',
    emerald: 'text-emerald-500',
    rose:    'text-rose-500',
    amber:   'text-amber-500',
  }
  return (
    <div className={clsx('rounded-xl border px-4 py-3', isDark ? 'bg-slate-800/50 border-slate-700' : 'bg-gray-50 border-gray-200')}>
      <p className={clsx('text-xs', isDark ? 'text-slate-400' : 'text-gray-400')}>{label}</p>
      <p className={clsx('text-base font-bold mt-0.5', mono ? 'font-mono text-sm' : '', valueColors[color])}>
        {value ?? '—'}
      </p>
    </div>
  )
}

function fmt(val: number | null | undefined, format: string): string {
  if (val === null || val === undefined) return '—'
  if (format === '%') return `${(val * 100).toFixed(2)}%`
  if (format === '.2f') return val.toFixed(2)
  return String(val)
}
