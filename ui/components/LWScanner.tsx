'use client'

import { apiError } from '@/lib/errors'
import { fmtSigned } from '@/lib/format'   // signed numbers with U+2212 (C1-trader-ux-18)
import { useCallback, useEffect, useState } from 'react'
import { BadgeChip, PageHeader, ResearchNote, SourceChip, sourceOf } from '@/components/terminal'
import clsx from 'clsx'
import { getLWScreener, getLWScanResults, triggerLWScan, getLWScanJob, getLWOHLCV } from '@/lib/api'
import { useTheme } from '@/context/ThemeContext'
import { IndicatorPriceChart } from './IndicatorPriceChart'
import { ChartActions } from './terminal/ChartActions'
import { IndicatorMenu } from './IndicatorMenu'
import { defaultIndicators, type Bar, type IndicatorConfig } from '@/lib/indicators'

// ── Types ─────────────────────────────────────────────────────────────────────

interface CycleResult {
  ticker: string
  composite_score: number
  cycle_edge: number
  cycle_pvalue: number
  divergence_count: number
  divergence_intensity: number
  recent_divergence: boolean
  failed_breakouts: number
  failure_rate: number
  blast_off_signals: number
  momentum_strength: number
  is_active_momentum: boolean
  momentum_direction: number
  // 5 Nov 2026 review (M24 / m088): flags withheld past their horizon, FDR-adjusted calendar p-values
  active_at_scan?: boolean
  cycle_qvalue?: number | null
  cycle_significant_fdr?: boolean
}

interface ScreenerResult {
  ticker: string
  close: number
  atr_14: number
  williams_r: number
  adv_20_cr: number
  pass_squeeze: boolean
  pass_oops: boolean
  pass_oversold_uptrend: boolean
  pass_liquidity: boolean
}

interface ScreenerData {
  scan_date: string
  universe_size: number
  filter_counts: Record<string, number>
  combined_pass: number
  results: ScreenerResult[]
}

interface ScanData {
  status: string
  results: CycleResult[]
  last_run: string | null
  total: number
  as_of?: string
  as_of_source?: string
  last_close?: string
  sessions_behind?: number
  stale?: boolean
  active_flags_expired?: boolean
  active_horizon_sessions?: number
  universe?: string
  n_stocks?: number
  multiple_testing?: { method: string; q: number; n_tests: number; expected_false_positives_at_p05: number; raw_p_below_05: number; significant_after_fdr: number }
}

interface JobStatus {
  job_id: string
  status: string
  progress: number
  total: number
  elapsed_secs: number
  error: string | null
}

// ── Score bar ─────────────────────────────────────────────────────────────────

function ScoreBar({ value, max = 1 }: { value: number; max?: number }) {
  const pct = Math.min(100, Math.round((value / max) * 100))
  const color = pct >= 70 ? 'bg-amber-400' : pct >= 40 ? 'bg-amber-600' : 'bg-slate-600'
  return (
    <div className="flex items-center gap-2">
      <div className="w-20 h-1.5 rounded-full bg-slate-700 overflow-hidden">
        <div className={clsx('h-full rounded-full', color)} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs font-mono text-slate-300">{value.toFixed(3)}</span>
    </div>
  )
}

function FilterBadge({ label, count, total }: { label: string; count: number; total: number }) {
  const { isDark } = useTheme()
  const pct = total > 0 ? Math.round((count / total) * 100) : 0
  return (
    <div className={clsx('flex flex-col gap-1 px-4 py-3 rounded-xl border', isDark ? 'bg-slate-800/50 border-slate-700/40' : 'bg-white border-gray-200')}>
      <span className={clsx('text-xs font-semibold', isDark ? 'text-slate-400' : 'text-gray-500')}>{label}</span>
      <span className={clsx('text-2xl font-black font-mono', isDark ? 'text-amber-300' : 'text-indigo-700')}>{count}</span>
      <span className={clsx('text-xs', isDark ? 'text-slate-500' : 'text-gray-400')}>{pct}% of universe</span>
    </div>
  )
}

// ── Candlestick Chart (lightweight-charts) ────────────────────────────────────

interface CandleChartProps {
  ticker: string
  days: number
  isDark: boolean
  indicators: IndicatorConfig[]
}

function CandleChart({ ticker, days, isDark, indicators }: CandleChartProps) {
  const [bars, setBars]       = useState<Bar[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState<string | null>(null)

  // Fetch OHLCV whenever ticker or window changes; rendering is delegated to the
  // shared IndicatorPriceChart (overlays + oscillators + legend).
  useEffect(() => {
    let alive = true
    setLoading(true)
    setError(null)
    getLWOHLCV(ticker, days)
      .then(res => {
        if (!alive) return
        const rows: Bar[] = (res.data.candles ?? []).map((c: any) => ({
          time: c.time, open: c.open, high: c.high, low: c.low, close: c.close, volume: c.volume ?? 0,
        }))
        setBars(rows)
        setLoading(false)
      })
      .catch(e => {
        if (!alive) return
        setError(apiError(e, 'Failed to load OHLCV'))
        setLoading(false)
      })
    return () => { alive = false }
  }, [ticker, days])

  return (
    <div className="relative w-full">
      {loading && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-slate-900/60 rounded-xl">
          <span className="text-xs text-amber-400 animate-pulse font-mono">Loading {ticker}…</span>
        </div>
      )}
      {error && (
        <div className="absolute inset-0 z-20 flex items-center justify-center bg-slate-900/60 rounded-xl">
          <span className="text-xs text-rose-400 font-mono">{error}</span>
        </div>
      )}
      <IndicatorPriceChart bars={bars} chartType="candle" isDark={isDark} indicators={indicators} height={340} />
    </div>
  )
}

// ── Chart Panel ───────────────────────────────────────────────────────────────

interface ChartPanelProps {
  ticker: string
  isDark: boolean
  onClose: () => void
}

function ChartPanel({ ticker, isDark, onClose }: ChartPanelProps) {
  const [days, setDays] = useState(90)
  const [indicators, setIndicators] = useState<IndicatorConfig[]>(defaultIndicators)
  const card = clsx('rounded-xl border', isDark ? 'bg-slate-800/60 border-slate-700/40' : 'bg-white border-gray-200')
  const mu   = isDark ? 'text-slate-400' : 'text-gray-500'
  const tx   = isDark ? 'text-slate-100' : 'text-gray-900'

  return (
    <div className={clsx(card, 'p-4 flex flex-col gap-3 h-fit sticky top-4')}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <p className={clsx('text-base font-black font-mono', isDark ? 'text-amber-300' : 'text-indigo-700')}>{ticker}</p>
          <p className={clsx('text-[10px]', mu)}>Interactive candlestick · Pan & zoom enabled</p>
        </div>
        <button onClick={onClose} className={clsx('text-lg leading-none transition-colors', mu, 'hover:text-white')}>✕</button>
      </div>
      <ChartActions ticker={ticker} from="LW Scanner" />

      {/* Period selector */}
      <div className={clsx('flex rounded-lg border overflow-hidden', isDark ? 'border-slate-700' : 'border-gray-200')}>
        {([30, 90, 180, 365] as const).map(d => (
          <button
            key={d}
            onClick={() => setDays(d)}
            className={clsx(
              'flex-1 py-1.5 text-[11px] font-bold transition-all',
              days === d
                ? isDark ? 'bg-amber-500/20 text-amber-300' : 'bg-indigo-600 text-white'
                : isDark ? 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/40' : 'text-gray-600 hover:bg-gray-100'
            )}
          >{d}D</button>
        ))}
      </div>

      {/* Indicator toolbar */}
      <div className={clsx('rounded-lg border px-2 py-1.5', isDark ? 'bg-slate-900/40 border-slate-700' : 'bg-gray-50 border-gray-200')}>
        <IndicatorMenu indicators={indicators} onChange={setIndicators} isDark={isDark} />
      </div>

      {/* Chart */}
      <CandleChart ticker={ticker} days={days} isDark={isDark} indicators={indicators} />

      <p className={clsx('text-[9px] text-center', mu)}>Scroll to zoom · Drag to pan · Crosshair for values</p>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function LWScanner() {
  const { isDark } = useTheme()
  const [subTab, setSubTab] = useState<'cycle' | 'screener'>('cycle')
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null)

  // Cycle scanner state
  const [scanData, setScanData]       = useState<ScanData | null>(null)
  const [scanLoading, setScanLoading] = useState(false)
  const [jobId, setJobId]             = useState<string | null>(null)
  const [jobStatus, setJobStatus]     = useState<JobStatus | null>(null)

  // Screener state
  const [screener, setScreener]               = useState<ScreenerData | null>(null)
  const [screenerLoading, setScreenerLoading] = useState(false)
  const [screenerError, setScreenerError]     = useState<string | null>(null)

  // Load cached cycle results
  useEffect(() => {
    getLWScanResults(50)
      .then(r => setScanData(r.data))
      .catch(() => setScanData({ status: 'no_data', results: [], last_run: null, total: 0 }))
  }, [])

  // Poll job status
  useEffect(() => {
    if (!jobId) return
    const interval = setInterval(async () => {
      try {
        const r = await getLWScanJob(jobId)
        setJobStatus(r.data)
        if (r.data.status === 'done') {
          clearInterval(interval)
          setJobId(null)
          setScanLoading(false)
          const res = await getLWScanResults(50)
          setScanData(res.data)
        } else if (r.data.status === 'error') {
          clearInterval(interval)
          setJobId(null)
          setScanLoading(false)
        }
      } catch {
        clearInterval(interval)
        setScanLoading(false)
      }
    }, 3000)
    return () => clearInterval(interval)
  }, [jobId])

  // Trigger cycle scan. Inside a freeze window the server answers 409: the page asks in place (no browser dialog) and
  // only an explicit "run anyway" sends confirm=true.
  const [freezeAsk, setFreezeAsk] = useState<string | null>(null)
  const handleRunScan = useCallback(async (override = false) => {
    setScanLoading(true)
    setJobStatus(null)
    setFreezeAsk(null)
    try {
      if (override) {
        const res = await fetch('/api/lw/run-cycle-scan?n_stocks=200&confirm=true', { method: 'POST' })
        if (!res.ok) throw new Error((await res.json().catch(() => null))?.detail ?? `HTTP ${res.status}`)
        setJobId((await res.json()).job_id)
      } else {
        const r = await triggerLWScan(200)
        setJobId(r.data.job_id)
      }
    } catch (e: any) {
      setScanLoading(false)
      if (e?.response?.status === 409 && /freeze window/i.test(String(e?.response?.data?.detail ?? ''))) {
        setFreezeAsk(String(e.response.data.detail)); return
      }
      const msg = apiError(e, 'Scan trigger failed')
      setJobStatus({ job_id: '', status: 'error', progress: 0, total: 0, elapsed_secs: 0, error: msg })
    }
  }, [])

  // Load screener
  const loadScreener = useCallback(async () => {
    setScreenerLoading(true)
    setScreenerError(null)
    try {
      const r = await getLWScreener(500)
      setScreener(r.data)
    } catch (e: any) {
      setScreenerError(apiError(e, 'Screener failed'))
    } finally {
      setScreenerLoading(false)
    }
  }, [])

  useEffect(() => {
    if (subTab === 'screener' && !screener && !screenerLoading) {
      loadScreener()
    }
  }, [subTab, screener, screenerLoading, loadScreener])

  // Shared classes
  const card  = clsx('rounded-xl border p-4', isDark ? 'bg-slate-800/40 border-slate-700/40' : 'bg-white border-gray-200')
  const th    = clsx('px-3 py-2 text-left text-xs font-semibold uppercase tracking-wider', isDark ? 'text-slate-400' : 'text-gray-500')
  const td    = clsx('px-3 py-2 text-xs font-mono', isDark ? 'text-slate-300' : 'text-gray-700')
  const trBase = clsx('border-b transition-colors cursor-pointer', isDark ? 'border-slate-700/30 hover:bg-amber-500/8' : 'border-gray-100 hover:bg-indigo-50/60')
  const trSelected = isDark ? 'bg-amber-500/12 border-amber-500/20' : 'bg-indigo-50 border-indigo-200'

  return (
    <div className="space-y-4">
      <PageHeader code="LWSC" title="Larry Williams Scanner"
        subtitle="Macro cycle patterns · volatility breakout screener · NSE universe · click a row for the chart" />
      <ResearchNote verdict="FAIL" report="reports/handbook_swing/REPORT.md">
        Related study: a rules-only swing system (breakouts and pullbacks, 2020 → today) lost 17.8% a year after ICICI costs while
        NIFTY 500 made 12.4%. Most trades were held about 3 sessions, too short to beat a ~1% round trip.
      </ResearchNote>
      {/* Section header */}
      <div className="flex items-center justify-end flex-wrap gap-3">
        <div className={clsx('flex rounded-lg border overflow-hidden', isDark ? 'border-slate-700' : 'border-gray-200')}>
          {(['cycle', 'screener'] as const).map(t => (
            <button
              key={t}
              onClick={() => { setSubTab(t); setSelectedTicker(null) }}
              className={clsx(
                'px-4 py-2 text-xs font-semibold transition-all',
                subTab === t
                  ? isDark ? 'bg-amber-500/20 text-amber-300' : 'bg-indigo-600 text-white'
                  : isDark ? 'text-slate-400 hover:text-slate-200 hover:bg-slate-700/40' : 'text-gray-600 hover:bg-gray-100'
              )}
            >
              {t === 'cycle' ? 'Cycle Scanner' : 'Vol Screener'}
            </button>
          ))}
        </div>
      </div>

      {/* ── CYCLE SCANNER tab ──────────────────────────────────────────── */}
      {subTab === 'cycle' && (
        <div className="space-y-4">
          {/* Controls row */}
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div className={clsx('text-xs flex items-center gap-2 flex-wrap', isDark ? 'text-slate-400' : 'text-gray-500')}>
              {scanData?.last_run
                ? <>
                    <SourceChip info={sourceOf(scanData.as_of ?? null, { source: 'LW cycle scan', maxAgeDays: 2 })} />
                    <span>Scan of the <span className={clsx('font-semibold', isDark ? 'text-slate-200' : 'text-gray-800')}>{scanData.as_of ?? '—'}</span> close
                      (written {scanData.last_run}){scanData.universe ? ` · ${scanData.universe}` : ''}</span>
                    {scanData.stale && (
                      <span data-lw-stale className="px-2 py-0.5 rounded border border-amber-500/50 text-amber-300 font-semibold">
                        STALE · {scanData.sessions_behind} sessions behind the {scanData.last_close} close
                        {scanData.active_flags_expired ? ' · ACTIVE flags withheld (past their 5-session horizon)' : ''}
                      </span>
                    )}
                  </>
                : <span className="italic">No scan results yet — run a scan to populate</span>
              }
            </div>
            <button
              onClick={() => handleRunScan(false)}
              disabled={scanLoading}
              className={clsx(
                'flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold border transition-all',
                scanLoading
                  ? 'bg-slate-700 border-slate-600 text-slate-500 cursor-not-allowed'
                  : isDark
                    ? 'bg-amber-500/15 border-amber-500/40 text-amber-300 hover:bg-amber-500/25'
                    : 'bg-indigo-600 border-indigo-600 text-white hover:bg-indigo-700'
              )}
            >
              {scanLoading
                ? <><span className="animate-spin">↻</span> Scanning…</>
                : <><span>▶</span> Run Cycle Scan (200 most liquid)</>
              }
            </button>
          </div>
          {freezeAsk && (
            <div className={clsx(card, 'py-3 flex items-center gap-3 flex-wrap')}>
              <span className="text-xs text-amber-300">{freezeAsk}</span>
              <button onClick={() => handleRunScan(true)} className="px-3 py-1 rounded border border-amber-500/50 text-amber-300 text-xs font-semibold">Run anyway</button>
              <button onClick={() => setFreezeAsk(null)} className="px-3 py-1 rounded border border-slate-600 text-slate-400 text-xs">Later</button>
            </div>
          )}
          {scanData?.multiple_testing && (
            <div className={clsx('text-[11px] flex items-center gap-2 flex-wrap', isDark ? 'text-slate-400' : 'text-gray-500')}>
              <BadgeChip badge="heuristic" note="Equal-weight pattern scores: a house rule, never fitted or validated. The related swing study FAILS after costs." />
              <span>Calendar-edge p-values: {scanData.multiple_testing.raw_p_below_05} of {scanData.multiple_testing.n_tests} below 0.05, where chance alone
                gives ≈ {scanData.multiple_testing.expected_false_positives_at_p05}; {scanData.multiple_testing.significant_after_fdr} survive the
                {' '}{scanData.multiple_testing.method} correction (* = q &lt; {scanData.multiple_testing.q}). Scores describe past patterns; they do not predict.</span>
            </div>
          )}

          {/* Job progress */}
          {jobStatus && (
            <div className={clsx(card, 'py-3')}>
              {jobStatus.status === 'error'
                ? <p className="text-xs text-rose-400 font-mono">{jobStatus.error}</p>
                : (
                  <div className="flex items-center gap-3">
                    <div className="flex-1 h-2 rounded-full bg-slate-700 overflow-hidden">
                      <div
                        className="h-full rounded-full bg-amber-400 transition-all duration-500"
                        style={{ width: jobStatus.total > 0 ? `${(jobStatus.progress / jobStatus.total) * 100}%` : '0%' }}
                      />
                    </div>
                    <span className={clsx('text-xs font-mono whitespace-nowrap', isDark ? 'text-slate-400' : 'text-gray-500')}>
                      {jobStatus.progress}/{jobStatus.total} · {jobStatus.elapsed_secs}s · {jobStatus.status}
                    </span>
                  </div>
                )
              }
            </div>
          )}

          {/* Pattern legend */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { key: 'cycle',     label: '28-Day Calendar Cycle',      color: 'text-amber-400'   },
              { key: 'divergence',label: 'Volume-Price Divergence',     color: 'text-sky-400'     },
              { key: 'reversal',  label: 'Accum/Dist Failure Reversal', color: 'text-emerald-400' },
              { key: 'momentum',  label: 'Blast-Off Momentum (3-day)',  color: 'text-rose-400'    },
            ].map(({ key, label, color }) => (
              <div key={key} className={clsx('px-3 py-2 rounded-lg border text-xs', isDark ? 'bg-slate-800/40 border-slate-700/30' : 'bg-gray-50 border-gray-200')}>
                <span className={clsx('font-semibold', color)}>●</span>
                <span className={clsx('ml-2', isDark ? 'text-slate-300' : 'text-gray-700')}>{label}</span>
              </div>
            ))}
          </div>

          {/* Results — split layout when ticker selected */}
          {scanData?.results && scanData.results.length > 0 ? (
            <div className={clsx('gap-4', selectedTicker ? 'grid grid-cols-[1fr_400px]' : '')}>
              {/* Table */}
              <div className={clsx(card, 'p-0 overflow-hidden')}>
                <div className="overflow-x-auto">
                  <table className="w-full text-left min-w-[700px]">
                    <thead className={clsx('border-b', isDark ? 'bg-slate-900/50 border-slate-700/40' : 'bg-gray-50 border-gray-200')}>
                      <tr>
                        <th className={th}>#</th>
                        <th className={th}>Ticker</th>
                        <th className={th}>Composite</th>
                        <th className={th}>Calendar Edge</th>
                        <th className={th}>Vol Divergence</th>
                        <th className={th}>Failed BOs</th>
                        <th className={th}>Blast-Off</th>
                        <th className={th}>Active</th>
                      </tr>
                    </thead>
                    <tbody>
                      {scanData.results.map((row, i) => (
                        <tr
                          key={row.ticker}
                          onClick={() => setSelectedTicker(prev => prev === row.ticker ? null : row.ticker)}
                          className={clsx(trBase, selectedTicker === row.ticker && trSelected)}
                        >
                          <td className={clsx(td, 'text-slate-500')}>{i + 1}</td>
                          <td className={clsx(td, 'font-bold', isDark ? 'text-amber-300' : 'text-indigo-700')}>
                            {row.ticker}
                            {selectedTicker === row.ticker && <span className="ml-1 text-[9px] text-amber-400">◀ chart</span>}
                          </td>
                          <td className={td}><ScoreBar value={row.composite_score} /></td>
                          <td className={td}>
                            <span className={clsx('font-mono', row.cycle_edge >= 0 ? 'text-emerald-400' : 'text-rose-400')}>
                              {fmtSigned(row.cycle_edge, 3)}
                            </span>
                            {row.cycle_significant_fdr
                              ? <span className="ml-1 text-amber-400 text-xs" title={`p ${row.cycle_pvalue.toFixed(3)} · q ${row.cycle_qvalue?.toFixed(3)} (Benjamini–Hochberg across the scan)`}>*</span>
                              : row.cycle_pvalue < 0.05 && <span className="ml-1 text-slate-500 text-[10px]" title={`raw p ${row.cycle_pvalue.toFixed(3)}, but q ${row.cycle_qvalue != null ? row.cycle_qvalue.toFixed(3) : '—'} after the multiple-testing correction: what chance gives across ${scanData.multiple_testing?.n_tests ?? 'all'} tests`}>p&lt;.05 · n.s.</span>}
                          </td>
                          <td className={td}>
                            <span className={clsx(row.divergence_count > 0 ? 'text-sky-400' : isDark ? 'text-slate-500' : 'text-gray-400')}>
                              {row.divergence_count}×
                            </span>
                            {row.recent_divergence && <span className="ml-1 text-xs text-sky-300" title="Signal in last 3 days">↑recent</span>}
                          </td>
                          <td className={td}>
                            <span className={row.failed_breakouts > 0 ? 'text-emerald-400' : isDark ? 'text-slate-500' : 'text-gray-400'}>
                              {row.failed_breakouts}
                            </span>
                            <span className={clsx('ml-1 text-xs', isDark ? 'text-slate-500' : 'text-gray-400')}>
                              ({(row.failure_rate * 100).toFixed(1)}%)
                            </span>
                          </td>
                          <td className={td}>
                            <span className={row.blast_off_signals > 0 ? 'text-rose-400' : isDark ? 'text-slate-500' : 'text-gray-400'}>
                              {row.blast_off_signals}
                            </span>
                            <span className={clsx('ml-1 text-xs', isDark ? 'text-slate-500' : 'text-gray-400')}>
                              str:{row.momentum_strength.toFixed(2)}
                            </span>
                          </td>
                          <td className={td}>
                            {row.is_active_momentum ? (
                              <span className="px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 text-xs font-semibold border border-amber-500/30">
                                {row.momentum_direction >= 0 ? '▲ LONG' : '▼ SHORT'}
                              </span>
                            ) : row.active_at_scan ? (
                              <span className={clsx('text-[10px]', isDark ? 'text-slate-500' : 'text-gray-400')}
                                title={`Active at the ${scanData.as_of} scan; older than its ${scanData.active_horizon_sessions ?? 5}-session horizon, so withheld`}>expired</span>
                            ) : (
                              <span className={clsx('text-xs', isDark ? 'text-slate-600' : 'text-gray-400')}>—</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Chart panel — slides in when ticker selected */}
              {selectedTicker && (
                <ChartPanel
                  ticker={selectedTicker}
                  isDark={isDark}
                  onClose={() => setSelectedTicker(null)}
                />
              )}
            </div>
          ) : (
            <div className={clsx(card, 'flex flex-col items-center justify-center py-16 gap-3')}>
              <span className="text-3xl opacity-30 font-mono">◌</span>
              <p className={clsx('text-sm font-medium', isDark ? 'text-slate-400' : 'text-gray-500')}>
                No cycle scan data — click "Run Cycle Scan" to analyse the 200 most liquid NSE stocks
              </p>
            </div>
          )}
        </div>
      )}

      {/* ── VOL SCREENER tab ───────────────────────────────────────────── */}
      {subTab === 'screener' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between flex-wrap gap-3">
            <div className={clsx('text-xs', isDark ? 'text-slate-400' : 'text-gray-500')}>
              {screener
                ? <>Scanned <span className={clsx('font-semibold', isDark ? 'text-slate-200' : 'text-gray-800')}>{screener.universe_size}</span> tickers · {screener.scan_date}</>
                : screenerLoading ? 'Computing indicators…' : 'Click Refresh to run screener'
              }
            </div>
            <button
              onClick={loadScreener}
              disabled={screenerLoading}
              className={clsx(
                'flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold border transition-all',
                screenerLoading
                  ? 'bg-slate-700 border-slate-600 text-slate-500 cursor-not-allowed'
                  : isDark
                    ? 'bg-amber-500/15 border-amber-500/40 text-amber-300 hover:bg-amber-500/25'
                    : 'bg-indigo-600 border-indigo-600 text-white hover:bg-indigo-700'
              )}
            >
              {screenerLoading ? <><span className="animate-spin">↻</span> Running…</> : <><span>↻</span> Refresh Screener</>}
            </button>
          </div>

          {screenerError && (
            <div className="px-4 py-3 rounded-xl border border-rose-500/40 bg-rose-900/20 text-rose-400 text-xs font-mono">
              {screenerError}
            </div>
          )}

          {screener && (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <FilterBadge label="The Squeeze"          count={screener.filter_counts['squeeze'] ?? 0}          total={screener.universe_size} />
                <FilterBadge label="Oops Reversal"        count={screener.filter_counts['oops'] ?? 0}             total={screener.universe_size} />
                <FilterBadge label="Oversold in Uptrend"  count={screener.filter_counts['oversold_uptrend'] ?? 0} total={screener.universe_size} />
                <FilterBadge label="Liquidity (ADV >₹10 cr)" count={screener.filter_counts['liquidity'] ?? 0}     total={screener.universe_size} />
              </div>

              <div className={clsx('flex items-center gap-3 px-4 py-3 rounded-xl border', isDark ? 'bg-amber-500/10 border-amber-500/30' : 'bg-indigo-50 border-indigo-200')}>
                <span className="text-xl font-mono text-amber-400">◎</span>
                <div>
                  <span className={clsx('text-base font-black', isDark ? 'text-amber-300' : 'text-indigo-700')}>{screener.combined_pass} stocks</span>
                  <span className={clsx('text-xs ml-2', isDark ? 'text-slate-400' : 'text-gray-500')}>pass all 4 filters</span>
                </div>
              </div>

              {/* Results — split layout when ticker selected */}
              {screener.results.length > 0 ? (
                <div className={clsx('gap-4', selectedTicker ? 'grid grid-cols-[1fr_400px]' : '')}>
                  <div className={clsx(card, 'p-0 overflow-hidden')}>
                    <div className="overflow-x-auto">
                      <table className="w-full text-left min-w-[700px]">
                        <thead className={clsx('border-b', isDark ? 'bg-slate-900/50 border-slate-700/40' : 'bg-gray-50 border-gray-200')}>
                          <tr>
                            <th className={th}>Ticker</th>
                            <th className={th}>Close ₹</th>
                            <th className={th}>ATR (14)</th>
                            <th className={th}>Williams %R</th>
                            <th className={th}>ADV ₹Cr</th>
                            <th className={th}>Squeeze</th>
                            <th className={th}>Oops</th>
                            <th className={th}>Oversold↑</th>
                            <th className={th}>Liquid</th>
                          </tr>
                        </thead>
                        <tbody>
                          {screener.results.map(row => (
                            <tr
                              key={row.ticker}
                              onClick={() => setSelectedTicker(prev => prev === row.ticker ? null : row.ticker)}
                              className={clsx(trBase, selectedTicker === row.ticker && trSelected)}
                            >
                              <td className={clsx(td, 'font-bold', isDark ? 'text-amber-300' : 'text-indigo-700')}>
                                {row.ticker}
                                {selectedTicker === row.ticker && <span className="ml-1 text-[9px] text-amber-400">◀</span>}
                              </td>
                              <td className={td}>{row.close.toFixed(2)}</td>
                              <td className={td}>{row.atr_14.toFixed(3)}</td>
                              <td className={clsx(td, row.williams_r < -80 ? 'text-emerald-400' : row.williams_r > -20 ? 'text-rose-400' : '')}>
                                {row.williams_r.toFixed(1)}
                              </td>
                              <td className={td}>{row.adv_20_cr.toFixed(1)}</td>
                              {[row.pass_squeeze, row.pass_oops, row.pass_oversold_uptrend, row.pass_liquidity].map((v, i) => (
                                <td key={i} className={td}>
                                  <span className={v ? 'text-emerald-400' : isDark ? 'text-slate-600' : 'text-gray-300'}>{v ? '✓' : '✗'}</span>
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>

                  {selectedTicker && (
                    <ChartPanel ticker={selectedTicker} isDark={isDark} onClose={() => setSelectedTicker(null)} />
                  )}
                </div>
              ) : (
                <div className={clsx(card, 'flex flex-col items-center justify-center py-12 gap-2')}>
                  <span className="text-3xl opacity-30">◇</span>
                  <p className={clsx('text-sm', isDark ? 'text-slate-400' : 'text-gray-500')}>No stocks passing all 4 filters today</p>
                </div>
              )}
            </>
          )}

          <div className={clsx('rounded-xl border p-4 space-y-2', isDark ? 'bg-slate-800/30 border-slate-700/30' : 'bg-gray-50 border-gray-200')}>
            <p className={clsx('text-xs font-semibold uppercase tracking-wider', isDark ? 'text-slate-400' : 'text-gray-500')}>Filter Definitions</p>
            <ul className={clsx('text-xs space-y-1 font-mono', isDark ? 'text-slate-400' : 'text-gray-600')}>
              <li><span className="text-amber-400">Squeeze</span> — Bollinger Bands inside Keltner Channels (volatility compression)</li>
              <li><span className="text-sky-400">Oops Reversal</span> — Open below prior low, closes back above (failed gap-down)</li>
              <li><span className="text-emerald-400">Oversold Uptrend</span> — Williams %R &lt; −80 AND price &gt; 200-day SMA</li>
              <li><span className="text-rose-400">Liquidity</span> — 20-day Average Dollar Volume &gt; ₹10 cr</li>
            </ul>
          </div>
        </div>
      )}
    </div>
  )
}
