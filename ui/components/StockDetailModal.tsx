'use client'

import clsx from 'clsx'
import { useEffect, useState, useCallback } from 'react'
import {
  ComposedChart,
  Line,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from 'recharts'
import { getStockDetail, getStockOHLCV } from '@/lib/api'

interface StockDetailModalProps {
  ticker: string | null
  onClose: () => void
}

type PeriodDays = 5 | 30 | 90 | 252 | 756 | 1260
type ChartType = 'line' | 'candle'

const PERIODS: { label: string; days: PeriodDays }[] = [
  { label: '5D', days: 5 },
  { label: '1M', days: 30 },
  { label: '3M', days: 90 },
  { label: '1Y', days: 252 },
  { label: '3Y', days: 756 },
  { label: '5Y', days: 1260 },
]

// Custom candlestick bar shape for recharts
const CandlestickShape = (props: any) => {
  const { x, width, low, high, openClose } = props
  if (!openClose || openClose.length < 2) return null
  const [open, close] = openClose
  if (open == null || close == null || low == null || high == null) return null

  const isGreen = close >= open
  const color = isGreen ? '#10b981' : '#ef4444'
  const bodyTop = Math.min(open, close)
  const bodyH = Math.max(Math.abs(open - close), 1)
  const cx = x + width / 2

  return (
    <g>
      {/* High-Low wick */}
      <line x1={cx} y1={high} x2={cx} y2={bodyTop} stroke={color} strokeWidth={1.5} />
      <line x1={cx} y1={bodyTop + bodyH} x2={cx} y2={low} stroke={color} strokeWidth={1.5} />
      {/* Body */}
      <rect x={x + 1} y={bodyTop} width={Math.max(width - 2, 2)} height={bodyH} fill={color} rx={1} />
    </g>
  )
}

// Custom tooltip for candlestick
const CandleTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null
  const d = payload[0]?.payload
  if (!d) return null
  const isGreen = d.close >= d.open
  return (
    <div className="bg-white border border-gray-200 rounded-lg shadow-lg p-3 text-xs">
      <p className="font-bold text-gray-700 mb-1">{d.date}</p>
      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5">
        <span className="text-gray-400">Open</span>  <span className="font-semibold text-gray-800">₹{d.open?.toFixed(2)}</span>
        <span className="text-gray-400">High</span>  <span className="font-semibold text-emerald-600">₹{d.high?.toFixed(2)}</span>
        <span className="text-gray-400">Low</span>   <span className="font-semibold text-rose-500">₹{d.low?.toFixed(2)}</span>
        <span className="text-gray-400">Close</span> <span className={clsx('font-bold', isGreen ? 'text-emerald-600' : 'text-rose-500')}>₹{d.close?.toFixed(2)}</span>
      </div>
      <p className="text-gray-400 mt-1">Vol: {d.volume >= 1_000_000 ? `${(d.volume/1_000_000).toFixed(2)}M` : `${(d.volume/1000).toFixed(0)}K`}</p>
    </div>
  )
}

export function StockDetailModal({ ticker, onClose }: StockDetailModalProps) {
  const [detail, setDetail] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [activeTab, setActiveTab] = useState<'details' | 'chart'>('details')
  const [ohlcv, setOhlcv] = useState<any[]>([])
  const [chartLoading, setChartLoading] = useState(false)
  const [chartError, setChartError] = useState<string | null>(null)
  const [period, setPeriod] = useState<PeriodDays>(90)
  const [chartType, setChartType] = useState<ChartType>('line')

  useEffect(() => {
    if (!ticker) return
    setLoading(true)
    setError(null)
    setDetail(null)
    setActiveTab('details')
    getStockDetail(ticker)
      .then((res) => setDetail(res.data))
      .catch((err) => setError(err.response?.data?.detail || 'Failed to load stock detail'))
      .finally(() => setLoading(false))
  }, [ticker])

  const fetchOHLCV = useCallback(async (days: PeriodDays) => {
    if (!ticker) return
    setChartLoading(true)
    setChartError(null)
    try {
      const res = await getStockOHLCV(ticker, days)
      setOhlcv(res.data?.rows || [])
    } catch (err: any) {
      setChartError(err.response?.data?.detail || 'Failed to load chart data')
    } finally {
      setChartLoading(false)
    }
  }, [ticker])

  useEffect(() => {
    if (activeTab === 'chart') {
      fetchOHLCV(period)
    }
  }, [activeTab, period, fetchOHLCV])

  if (!ticker) return null

  // Build chart data with MA overlays
  const chartData = ohlcv.map((row, i) => {
    const slice50 = ohlcv.slice(Math.max(0, i - 49), i + 1)
    const slice200 = ohlcv.slice(Math.max(0, i - 199), i + 1)
    const ma50 = slice50.reduce((s: number, r: any) => s + r.close, 0) / slice50.length
    const ma200 = slice200.reduce((s: number, r: any) => s + r.close, 0) / slice200.length
    return {
      date: row.date,
      open: row.open ? +row.open.toFixed(2) : null,
      high: row.high ? +row.high.toFixed(2) : null,
      low: row.low ? +row.low.toFixed(2) : null,
      close: row.close ? +row.close.toFixed(2) : null,
      openClose: [
        row.open ? +row.open.toFixed(2) : null,
        row.close ? +row.close.toFixed(2) : null,
      ],
      ma50: i >= 49 ? +ma50.toFixed(2) : null,
      ma200: i >= 199 ? +ma200.toFixed(2) : null,
      volume: row.volume,
      // For candlestick Y positioning (passed as number for ComposedChart axis)
      barHigh: row.high ? +row.high.toFixed(2) : null,
      barLow: row.low ? +row.low.toFixed(2) : null,
    }
  })

  // Thin out X-axis labels based on period
  const xTickInterval = period <= 30 ? 4 : period <= 90 ? 14 : period <= 252 ? 30 : period <= 756 ? 90 : 180

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm p-4"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="w-full max-w-4xl max-h-[92vh] overflow-y-auto rounded-2xl bg-white border border-gray-200 shadow-2xl">
        {/* Header */}
        <div className="sticky top-0 bg-white border-b border-gray-200 px-6 py-4 flex justify-between items-center z-10">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-indigo-100 border border-indigo-200 flex items-center justify-center">
              <span className="text-sm font-black text-indigo-600">{ticker.charAt(0)}</span>
            </div>
            <div>
              <h2 className="text-xl font-black text-gray-900">{ticker}</h2>
              {detail?.fundamentals?.sector && (
                <p className="text-xs text-gray-400">{detail.fundamentals.sector}</p>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1">
              <button
                onClick={() => setActiveTab('details')}
                className={clsx(
                  'px-3 py-1.5 rounded-md text-xs font-semibold transition-all',
                  activeTab === 'details' ? 'bg-white shadow text-indigo-600' : 'text-gray-500 hover:text-gray-700'
                )}
              >
                Details
              </button>
              <button
                onClick={() => setActiveTab('chart')}
                className={clsx(
                  'px-3 py-1.5 rounded-md text-xs font-semibold transition-all',
                  activeTab === 'chart' ? 'bg-white shadow text-indigo-600' : 'text-gray-500 hover:text-gray-700'
                )}
              >
                📈 Chart
              </button>
            </div>
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-gray-700 text-xl leading-none w-7 h-7 flex items-center justify-center rounded-lg hover:bg-gray-100"
            >
              ✕
            </button>
          </div>
        </div>

        <div className="p-6">
          {/* Loading */}
          {loading && (
            <div className="space-y-3">
              {Array(4).fill(0).map((_, i) => (
                <div key={i} className="h-14 animate-pulse rounded-xl bg-gray-100" />
              ))}
            </div>
          )}

          {error && (
            <div className="rounded-xl bg-rose-50 border border-rose-200 p-4 text-rose-600 text-sm">
              {error}
            </div>
          )}

          {/* ── Details Tab ──────────────────────────────────────────── */}
          {!loading && !error && detail && activeTab === 'details' && (
            <div className="space-y-6">
              <Section title="OHLCV Data">
                <div className="grid grid-cols-2 gap-3">
                  <Stat label="Total Rows" value={detail.ohlcv.total_rows.toLocaleString()} />
                  <Stat label="Data Density" value={`${detail.ohlcv.data_density_pct.toFixed(1)}%`} />
                  <div className="col-span-2">
                    <Stat label="Date Range" value={`${detail.ohlcv.first_date} → ${detail.ohlcv.latest_date}`} mono />
                  </div>
                  <Stat label="Missing Days" value={detail.ohlcv.missing_rows} color={detail.ohlcv.missing_rows > 20 ? 'rose' : 'emerald'} />
                  <Stat label="Last Updated" value={`${detail.data_quality.days_since_update} day(s) ago`}
                    color={detail.data_quality.days_since_update <= 1 ? 'emerald' : 'amber'} />
                </div>
              </Section>

              {detail.fundamentals?.available && (
                <Section title="Fundamentals">
                  <div className="grid grid-cols-2 gap-3">
                    <Stat label="P/E Ratio" value={fmt(detail.fundamentals.trailing_pe, '.2f')} />
                    <Stat label="P/B Ratio" value={fmt(detail.fundamentals.price_to_book, '.2f')} />
                    <Stat label="ROE" value={fmt(detail.fundamentals.roe, '%')} />
                    <Stat label="D/E Ratio" value={fmt(detail.fundamentals.debt_to_equity, '.2f')} />
                    <Stat label="Dividend Yield" value={fmt(detail.fundamentals.dividend_yield, '%')} />
                    <Stat label="Sector" value={detail.fundamentals.sector ?? '—'} />
                  </div>
                </Section>
              )}

              {detail.upcoming_events?.length > 0 && (
                <Section title="Upcoming Events">
                  <div className="space-y-2">
                    {detail.upcoming_events.map((ev: any, i: number) => (
                      <div key={i} className="flex justify-between items-center rounded-lg bg-gray-50 border border-gray-200 px-4 py-2.5">
                        <span className="text-sm font-medium text-gray-700">{ev.type}</span>
                        <span className="text-xs font-mono text-indigo-500">{ev.date}</span>
                      </div>
                    ))}
                  </div>
                </Section>
              )}

              <Section title="Corporate History">
                <div className="grid grid-cols-2 gap-3">
                  <Stat label="Dividends" value={detail.dividends.count} />
                  <Stat label="Stock Splits" value={detail.splits.count} />
                </div>
              </Section>

              {/* Data Health — no "Poor" label */}
              <div className={clsx(
                'rounded-xl border p-4',
                detail.data_quality.overall === 'excellent' ? 'border-emerald-200 bg-emerald-50' :
                detail.data_quality.overall === 'good' ? 'border-teal-200 bg-teal-50' :
                detail.data_quality.overall === 'fair' ? 'border-amber-200 bg-amber-50' :
                'border-gray-200 bg-gray-50'
              )}>
                <p className="text-xs text-gray-500 font-medium mb-2">Data Health</p>
                <div className="flex items-center gap-4">
                  <div>
                    <p className="text-xs text-gray-400">Density</p>
                    <p className="text-lg font-black text-gray-900 mt-0.5">{detail.ohlcv.data_density_pct.toFixed(1)}%</p>
                  </div>
                  <div className="w-px h-10 bg-gray-200" />
                  <div>
                    <p className="text-xs text-gray-400">Last updated</p>
                    <p className={clsx('text-lg font-black mt-0.5',
                      detail.data_quality.days_since_update <= 1 ? 'text-emerald-600' :
                      detail.data_quality.days_since_update <= 3 ? 'text-amber-600' : 'text-gray-600'
                    )}>
                      {detail.data_quality.days_since_update}d ago
                    </p>
                  </div>
                  <div className="w-px h-10 bg-gray-200" />
                  <div>
                    <p className="text-xs text-gray-400">Total rows</p>
                    <p className="text-lg font-black text-gray-900 mt-0.5">{detail.ohlcv.total_rows.toLocaleString()}</p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* ── Chart Tab ────────────────────────────────────────────── */}
          {activeTab === 'chart' && (
            <div className="space-y-4">
              {/* Controls row */}
              <div className="flex items-center justify-between flex-wrap gap-2">
                <p className="text-sm font-semibold text-gray-700">{ticker} Price Chart</p>
                <div className="flex items-center gap-2">
                  {/* Chart type toggle */}
                  <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1">
                    <button
                      onClick={() => setChartType('line')}
                      className={clsx(
                        'px-2.5 py-1 rounded-md text-xs font-bold transition-all',
                        chartType === 'line' ? 'bg-white shadow text-indigo-600' : 'text-gray-500 hover:text-gray-700'
                      )}
                    >
                      Line
                    </button>
                    <button
                      onClick={() => setChartType('candle')}
                      className={clsx(
                        'px-2.5 py-1 rounded-md text-xs font-bold transition-all',
                        chartType === 'candle' ? 'bg-white shadow text-indigo-600' : 'text-gray-500 hover:text-gray-700'
                      )}
                    >
                      Candle
                    </button>
                  </div>
                  {/* Period selector */}
                  <div className="flex items-center gap-1 bg-gray-100 rounded-lg p-1">
                    {PERIODS.map(({ label, days }) => (
                      <button
                        key={days}
                        onClick={() => setPeriod(days)}
                        className={clsx(
                          'px-2.5 py-1 rounded-md text-xs font-bold transition-all',
                          period === days ? 'bg-white shadow text-indigo-600' : 'text-gray-500 hover:text-gray-700'
                        )}
                      >
                        {label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>

              {chartLoading && (
                <div className="h-72 animate-pulse rounded-xl bg-gray-100 flex items-center justify-center">
                  <span className="text-gray-400 text-sm">Loading chart…</span>
                </div>
              )}

              {chartError && (
                <div className="rounded-xl bg-amber-50 border border-amber-200 p-4 text-amber-700 text-sm">
                  {chartError}
                </div>
              )}

              {!chartLoading && !chartError && chartData.length > 0 && (
                <>
                  {chartType === 'line' ? (
                    <div className="rounded-xl border border-gray-200 bg-white p-4">
                      <ResponsiveContainer width="100%" height={320}>
                        <ComposedChart data={chartData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                          <XAxis
                            dataKey="date"
                            tick={{ fontSize: 10, fill: '#9ca3af' }}
                            tickLine={false}
                            interval={xTickInterval}
                            tickFormatter={(v) => v.slice(5)}
                          />
                          <YAxis
                            orientation="right"
                            tick={{ fontSize: 10, fill: '#9ca3af' }}
                            tickLine={false}
                            axisLine={false}
                            tickFormatter={(v) => `₹${v >= 1000 ? (v/1000).toFixed(1)+'K' : v.toFixed(0)}`}
                            width={70}
                          />
                          <Tooltip
                            contentStyle={{ background: 'white', border: '1px solid #e5e7eb', borderRadius: 8, fontSize: 12 }}
                            labelStyle={{ color: '#374151', fontWeight: 700 }}
                            formatter={(v: any, name: string) => [
                              `₹${Number(v).toFixed(2)}`,
                              name === 'close' ? 'Close' : name === 'ma50' ? 'MA 50' : 'MA 200',
                            ]}
                          />
                          <Legend wrapperStyle={{ fontSize: 11, paddingTop: 8 }}
                            formatter={(v) => v === 'close' ? 'Close' : v === 'ma50' ? 'MA 50' : 'MA 200'} />
                          <Line type="monotone" dataKey="close" stroke="#4f46e5" strokeWidth={2} dot={false} connectNulls />
                          <Line type="monotone" dataKey="ma50" stroke="#f59e0b" strokeWidth={1.5} strokeDasharray="4 2" dot={false} connectNulls />
                          <Line type="monotone" dataKey="ma200" stroke="#10b981" strokeWidth={1.5} strokeDasharray="4 2" dot={false} connectNulls />
                        </ComposedChart>
                      </ResponsiveContainer>
                    </div>
                  ) : (
                    /* Candlestick chart */
                    <div className="rounded-xl border border-gray-200 bg-white p-4">
                      <ResponsiveContainer width="100%" height={320}>
                        <ComposedChart data={chartData} margin={{ top: 5, right: 10, bottom: 5, left: 10 }}>
                          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                          <XAxis
                            dataKey="date"
                            tick={{ fontSize: 10, fill: '#9ca3af' }}
                            tickLine={false}
                            interval={xTickInterval}
                            tickFormatter={(v) => v.slice(5)}
                          />
                          <YAxis
                            orientation="right"
                            tick={{ fontSize: 10, fill: '#9ca3af' }}
                            tickLine={false}
                            axisLine={false}
                            tickFormatter={(v) => `₹${v >= 1000 ? (v/1000).toFixed(1)+'K' : v.toFixed(0)}`}
                            width={70}
                            domain={['auto', 'auto']}
                          />
                          <Tooltip content={<CandleTooltip />} />
                          {/* Render candle wicks using high/low range bars */}
                          <Bar
                            dataKey="close"
                            shape={(props: any) => {
                              const { x, width, y, payload } = props
                              if (!payload) return <g />
                              const { open, close, high, low } = payload

                              // We need pixel coordinates — use the YAxis scale
                              // Since recharts doesn't expose scale directly in shape props,
                              // we approximate using the chart's y domain
                              // This is handled by recharts: y is the pixel y for dataKey value (close)
                              // We need to compute pixel positions for open, high, low
                              // recharts Bar shape receives `y` = pixel top of bar
                              // We'll use a relative approach: y is where `close` sits
                              // The chart height is 320 - margins (5+5+padding) ≈ 290px
                              // We compute scale manually from the data

                              const allPrices = chartData.flatMap(d => [d.high, d.low]).filter(Boolean) as number[]
                              const minP = Math.min(...allPrices)
                              const maxP = Math.max(...allPrices)
                              const chartH = 290
                              const toY = (price: number) => chartH - ((price - minP) / (maxP - minP)) * chartH

                              if (!open || !close || !high || !low) return <g />
                              const isGreen = close >= open
                              const color = isGreen ? '#10b981' : '#ef4444'
                              const cx = x + width / 2
                              const yOpen = toY(open)
                              const yClose = toY(close)
                              const yHigh = toY(high)
                              const yLow = toY(low)
                              const bodyTop = Math.min(yOpen, yClose)
                              const bodyH = Math.max(Math.abs(yOpen - yClose), 1)

                              return (
                                <g>
                                  <line x1={cx} y1={yHigh} x2={cx} y2={bodyTop} stroke={color} strokeWidth={1} />
                                  <line x1={cx} y1={bodyTop + bodyH} x2={cx} y2={yLow} stroke={color} strokeWidth={1} />
                                  <rect x={x + 1} y={bodyTop} width={Math.max(width - 2, 2)} height={bodyH} fill={color} rx={1} />
                                </g>
                              )
                            }}
                            isAnimationActive={false}
                          />
                        </ComposedChart>
                      </ResponsiveContainer>
                    </div>
                  )}

                  {/* Volume chart — same for both modes */}
                  <div className="rounded-xl border border-gray-200 bg-white p-4">
                    <p className="text-xs font-semibold text-gray-400 mb-2 uppercase tracking-wider">Volume</p>
                    <ResponsiveContainer width="100%" height={80}>
                      <ComposedChart data={chartData} margin={{ top: 0, right: 10, bottom: 0, left: 10 }}>
                        <XAxis dataKey="date" hide />
                        <YAxis
                          tick={{ fontSize: 9, fill: '#9ca3af' }}
                          tickLine={false}
                          axisLine={false}
                          tickFormatter={(v) => v >= 1_000_000 ? `${(v/1_000_000).toFixed(0)}M` : `${(v/1000).toFixed(0)}K`}
                          width={45}
                        />
                        <Tooltip
                          contentStyle={{ background: 'white', border: '1px solid #e5e7eb', borderRadius: 8, fontSize: 11 }}
                          formatter={(v: any) => [
                            v >= 1_000_000 ? `${(v/1_000_000).toFixed(2)}M` : `${(v/1000).toFixed(0)}K`,
                            'Volume',
                          ]}
                        />
                        <Bar dataKey="volume" fill="#c7d2fe" radius={[2, 2, 0, 0]} />
                      </ComposedChart>
                    </ResponsiveContainer>
                  </div>
                </>
              )}

              {!chartLoading && !chartError && chartData.length === 0 && (
                <div className="rounded-xl border border-gray-200 bg-gray-50 p-12 text-center">
                  <p className="text-gray-400 text-sm">No price history available for {ticker}</p>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-xs font-bold uppercase tracking-wider text-gray-400 mb-3">{title}</h3>
      {children}
    </div>
  )
}

function Stat({ label, value, color = 'slate', mono = false }: {
  label: string; value: any; color?: 'slate' | 'emerald' | 'rose' | 'amber'; mono?: boolean
}) {
  const valueColors = { slate: 'text-gray-900', emerald: 'text-emerald-600', rose: 'text-rose-600', amber: 'text-amber-600' }
  return (
    <div className="rounded-xl bg-gray-50 border border-gray-200 px-4 py-3">
      <p className="text-xs text-gray-400">{label}</p>
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
