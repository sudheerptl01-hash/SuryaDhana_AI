'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import { Chip, PageHeader, T, ResearchNote, fmtNum, fmtSigned } from '@/components/terminal'
import clsx from 'clsx'
import {
  Bar, BarChart, CartesianGrid, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { StockDetailModal } from './StockDetailModal'
import { EquityCockpitChart } from './EquityCockpitChart'
import { BacktestTradeGrid } from './BacktestTradeGrid'
import { FactorDiagnosticStudio } from './FactorDiagnosticStudio'
import { streamBacktest, type BacktestParams, type BacktestResult, type Trade } from '@/lib/backtest'
import { exportBacktestCSV, exportBacktestExcel } from '@/lib/backtestExport'
import { getTradeTicket } from '@/lib/api'
import { DESK_LIKE, LEGACY_DEFAULTS, MIN_FRICTION_BPS, frictionFromRoundTrip, looksLegacy, positionValue, stopPayload, type StopMode } from './btstDefaults'

// ── Filter catalog (fundamental = look-ahead-prone snapshot fields) ──────────────
const FUNDAMENTAL = new Set(['pe_ratio', 'div_yld_pct', 'mktcap_cr', 'roce_pct'])

const FILTER_CATALOG: Record<string, Array<{ id: string; label: string; unit?: string; toggle?: boolean; op: 'lt' | 'gt'; val: number; desc: string }>> = {
  Valuation: [
    { id: 'pe_ratio', label: 'P/E Ratio', unit: 'x', op: 'lt', val: 25, desc: 'Price / earnings' },
    { id: 'div_yld_pct', label: 'Dividend Yield', unit: '%', op: 'gt', val: 1, desc: 'Dividend / price' },
    { id: 'mktcap_cr', label: 'Market Cap', unit: 'Cr', op: 'gt', val: 500, desc: 'Market capitalization' },
  ],
  Quality: [
    { id: 'roce_pct', label: 'ROCE', unit: '%', op: 'gt', val: 15, desc: 'Return on capital' },
  ],
  Trend: [
    { id: 'price_gt_ma50', label: 'Price > 50-MA', toggle: true, op: 'gt', val: 0, desc: 'Above short-term trend' },
    { id: 'price_gt_ma150', label: 'Price > 150-MA', toggle: true, op: 'gt', val: 0, desc: 'Above intermediate trend (Minervini T1 — combine with Price > 200-MA)' },
    { id: 'price_gt_ma200', label: 'Price > 200-MA', toggle: true, op: 'gt', val: 0, desc: 'Above long-term trend' },
    { id: 'ma50_gt_ma200', label: '50-MA > 200-MA', toggle: true, op: 'gt', val: 0, desc: 'Golden cross' },
    { id: 'ma150_gt_ma200', label: '150-MA > 200-MA', toggle: true, op: 'gt', val: 0, desc: 'Stage-2 uptrend (Minervini T2)' },
  ],
  Momentum: [
    { id: 'rsi_14', label: 'RSI (14)', unit: '', op: 'gt', val: 50, desc: 'Oversold <30 / overbought >70' },
    { id: 'atr_14_pct', label: 'ATR %', unit: '%', op: 'lt', val: 5, desc: 'Volatility (% of close)' },
  ],
  Volatility: [
    { id: 'above_52w_low_pct', label: '% above 52w-Low', unit: '%', op: 'gt', val: 30, desc: 'Bounce strength' },
    { id: 'within_52w_high_pct', label: '% within 52w-High', unit: '%', op: 'lt', val: 25, desc: 'Near yearly peak' },
    { id: 'dist_ma200_pct', label: 'Dist 200-MA', unit: '%', op: 'lt', val: 20, desc: 'Over/under-extended' },
    { id: 'squeeze_ratio', label: 'Squeeze Ratio BB/KC', unit: 'x', op: 'lt', val: 1, desc: 'BB width / KC width (<1 ⇒ squeeze)' },
    { id: 'squeeze_on', label: 'Squeeze ON', toggle: true, op: 'gt', val: 0, desc: 'Bollinger inside Keltner' },
  ],
  Volume: [
    { id: 'volume_gt_avg', label: 'Vol > 20d-Avg', toggle: true, op: 'gt', val: 0, desc: 'Accumulation' },
  ],
  Microstructure: [
    { id: 'vmi_ratio', label: 'Volume Market Impact', unit: 'x', op: 'gt', val: 1, desc: 'Outsized $-vol vs 20d, vol-normalized' },
    { id: 'vol_zscore_20', label: 'Volume Thrust z', unit: 'σ', op: 'gt', val: 2, desc: 'Volume vs prior-20d baseline' },
    { id: 'vipt_breakout', label: 'VIPT Breakout', toggle: true, op: 'gt', val: 0, desc: '20d range breakout on >3σ volume' },
    { id: 'intraday_intention', label: 'Intraday Intention', unit: '', op: 'gt', val: 0.7, desc: '3-day close-location value' },
    { id: 'intention_pullback', label: 'Intention on Pullback', toggle: true, op: 'gt', val: 0, desc: 'CLV>0.8 through a 3-day dip' },
  ],
  'Relative Strength': [
    { id: 'sector_rel_mom_14_pct', label: 'Sector-Rel Mom 14d', unit: '%', op: 'gt', val: 0, desc: '14d return vs sector composite' },
    { id: 'sector_positive_regime', label: 'Positive Sector Regime', toggle: true, op: 'gt', val: 0, desc: 'Sector momentum > 0' },
    { id: 'corr_nifty_30', label: 'Market Corr 30d', unit: 'ρ', op: 'lt', val: 0.2, desc: 'Rolling 30d corr to market' },
    { id: 'decoupled_leader', label: 'De-coupled Leader', toggle: true, op: 'gt', val: 0, desc: 'Low corr in a market pullback' },
  ],
  'Structural Alpha': [
    { id: 'beta_resid_5d', label: 'Idiosyncratic 5d', unit: '%', op: 'gt', val: 0, desc: 'Beta-30d-residual 5d return vs Nifty (idiosyncratic momentum)' },
    { id: 'vol_adj_sector_alpha_14', label: 'Vol-Adj Sector Alpha 14d', unit: 'x', op: 'gt', val: 0, desc: '(14d ret − sector 14d) / 14d ATR%' },
  ],
  'ML Signal': [
    { id: 'prob_up', label: 'P(up · 5d)', unit: 'prob', op: 'gt', val: 0.55, desc: 'Leak-safe holdout XGBoost P(up over next 5d); available ~last year only (2025-06 →). RSCH: the 5-day labels behind it FAIL' },
  ],
}

const PRESETS = [
  { label: '6M', days: 180 }, { label: '1Y', days: 365 },
  { label: '2Y', days: 730 }, { label: '3Y', days: 1095 }, { label: '5Y', days: 1825 },
]

interface FilterCond { field: string; op: 'lt' | 'gt' | 'lte' | 'gte'; value: number }

// ── Formatting helpers ──────────────────────────────────────────────────────────
const fNum = (n: number, d = 2) => fmtNum(n ?? 0, d)
const fCr = (n: number) => {
  if (Math.abs(n) >= 1e7) return `₹${(n / 1e7).toFixed(2)} cr`
  if (Math.abs(n) >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`
  return `₹${fNum(n, 0)}`
}
const fPct = (n: number) => `${fmtSigned(n ?? 0, 2)}%`   // U+2212 for losses (C1-18)

// ── KPI cell ──────────────────────────────────────────────────────────────────────
function Kpi({ label, value, tone = 'slate', sub }: { label: string; value: string; tone?: 'amber' | 'emerald' | 'rose' | 'slate' | 'indigo'; sub?: string }) {
  const toneMap = {
    amber: 'text-amber-300', emerald: 'text-emerald-300', rose: 'text-rose-300',
    slate: 'text-slate-100', indigo: 'text-indigo-300',
  }
  return (
    <div className="rounded-lg border border-slate-700/40 bg-slate-800/40 px-3 py-2.5">
      <p className="text-[10px] text-slate-500 uppercase tracking-widest font-semibold truncate">{label}</p>
      <p className={clsx('text-base sm:text-lg font-bold font-mono tabular-nums leading-tight mt-0.5', toneMap[tone])}>{value}</p>
      {sub && <p className="text-[10px] text-slate-500 font-mono mt-0.5 truncate">{sub}</p>}
    </div>
  )
}

interface BacktestPanelProps { isDark?: boolean; watchlist?: string[] }

export function BacktestPanel({ watchlist = [] }: BacktestPanelProps) {
  const today = new Date().toISOString().split('T')[0]
  const ago = (d: number) => new Date(Date.now() - d * 864e5).toISOString().split('T')[0]

  // Window + strategy
  const [fromDate, setFromDate] = useState(ago(365))
  const [toDate, setToDate] = useState(today)
  const [forwardDays, setForwardDays] = useState<number>(DESK_LIKE.holdSessions)
  const [winThreshold, setWinThreshold] = useState(0)
  const [filters, setFilters] = useState<FilterCond[]>([])

  // Risk + capital (Pillar 1)
  const [startingCapital, setStartingCapital] = useState(10_000_000)
  // friction: the real ICICI round trip at this lab's position size (shared/trading_costs.py via /api/costs/ticket),
  // until the user types their own number (M20)
  const [frictionBps, setFrictionBps] = useState<number | null>(null)
  const [frictionAuto, setFrictionAuto] = useState(true)
  const [costNote, setCostNote] = useState<{ pct: number; value: number; profile: string } | 'error' | null>(null)
  const [stopMode, setStopMode] = useState<StopMode>(DESK_LIKE.stopMode)
  const [atrMult, setAtrMult] = useState(2)
  const [stopLossPct, setStopLossPct] = useState(2)
  const [trailEnabled, setTrailEnabled] = useState(false)
  const [trailingPct, setTrailingPct] = useState(5)
  const [maxPositions, setMaxPositions] = useState<number>(DESK_LIKE.maxPositions)
  const [entryTiming, setEntryTiming] = useState<'next_open' | 'close'>('next_open')
  const [ddHaltEnabled, setDdHaltEnabled] = useState(true)
  const [ddHaltPct, setDdHaltPct] = useState<number>(DESK_LIKE.ddHaltPct)
  const [dailyHalt, setDailyHalt] = useState<boolean>(DESK_LIKE.dailyHalt)

  const posValue = positionValue(startingCapital, maxPositions)
  useEffect(() => {
    if (!frictionAuto) return
    let live = true
    const value = Math.round(posValue)
    const t = setTimeout(() => {
      getTradeTicket({ value, price: 1 })
        .then(r => {
          if (!live) return
          const bps = frictionFromRoundTrip(r.data.round_trip_pct)
          if (bps == null) { setCostNote('error'); return }
          setFrictionBps(bps)
          setCostNote({ pct: r.data.round_trip_pct ?? 0, value, profile: r.data.profile })
        })
        .catch(() => { if (live) setCostNote('error') })
    }, 300)
    return () => { live = false; clearTimeout(t) }
  }, [posValue, frictionAuto])

  // Scope (Pillar 2)
  const [propensityMissing, setPropensityMissing] = useState<'keep' | 'exclude' | 'neutral'>('keep')
  const [scope, setScope] = useState<'universe' | 'watchlist'>('universe')

  // WFO
  const [wfoMode, setWfoMode] = useState(false)
  const [outSampleDays, setOutSampleDays] = useState(60)
  const [inSampleDays, setInSampleDays] = useState(180)
  const [monteCarloRuns, setMonteCarloRuns] = useState(1000)

  // Run state
  const [loading, setLoading] = useState(false)
  const [progress, setProgress] = useState<{ pct: number; label: string; eta: number | null }>({ pct: 0, label: '', eta: null })
  const [results, setResults] = useState<BacktestResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const fundamentalActive = filters.some(f => FUNDAMENTAL.has(f.field))
  const propensityActive = filters.some(f => f.field === 'prob_up')
  const watchlistEmpty = scope === 'watchlist' && watchlist.length === 0

  const toggleFilter = (id: string) => {
    const f = filters.find(x => x.field === id)
    if (f) { setFilters(filters.filter(x => x.field !== id)); return }
    for (const group of Object.values(FILTER_CATALOG)) {
      const def = group.find(d => d.id === id)
      if (def) { setFilters([...filters, { field: id, op: def.op, value: def.val }]); break }
    }
  }
  const updateFilter = (id: string, patch: Partial<FilterCond>) =>
    setFilters(filters.map(f => (f.field === id ? { ...f, ...patch } : f)))

  // Factor Diagnostic Studio → upsert a data-derived threshold into Tier-1 filters.
  const applyThreshold = (field: string, op: 'gte' | 'lte', value: number) =>
    setFilters(prev =>
      prev.some(f => f.field === field)
        ? prev.map(f => (f.field === field ? { ...f, op, value } : f))
        : [...prev, { field, op, value }])

  const setPreset = (days: number) => { setFromDate(ago(days)); setToDate(today) }

  const run = async () => {
    if (watchlistEmpty) { setError('Watchlist scope selected but your watchlist is empty. Star stocks in the Stocks tab first.'); return }
    abortRef.current?.abort()
    const ac = new AbortController()
    abortRef.current = ac
    setLoading(true); setError(null); setResults(null); setProgress({ pct: 2, label: 'Starting…', eta: null })

    if (frictionBps == null) { setError('The real round-trip cost is not known yet: wait a moment, or type a friction in bps.'); return }
    const stops = stopPayload(stopMode, atrMult, stopLossPct)
    // the stop and daily-halt fields go out explicitly: the API's own defaults must never switch a stop on silently
    const params: BacktestParams & { atr_stop_mult: number | null; daily_loss_halt_pct: number | null } = {
      from_date: fromDate, to_date: toDate, forward_days: forwardDays, win_threshold: winThreshold,
      filters, starting_capital: startingCapital, friction_bps: frictionBps,
      stop_loss_pct: stops.stop_loss_pct, atr_stop_mult: stops.atr_stop_mult,
      daily_loss_halt_pct: dailyHalt ? 2 : null,
      trailing_stop_pct: trailEnabled ? trailingPct : null,
      max_positions: maxPositions, max_drawdown_halt_pct: ddHaltEnabled ? ddHaltPct : null,
      scope, tickers: scope === 'watchlist' ? watchlist : [], entry_timing: entryTiming,
      propensity_missing: propensityMissing,
      ...(wfoMode ? { in_sample_days: inSampleDays, out_sample_days: outSampleDays, monte_carlo_runs: monteCarloRuns } : {}),
    }

    try {
      await streamBacktest(params, {
        wfo: wfoMode,
        signal: ac.signal,
        onProgress: e => setProgress({ pct: e.pct, label: e.label, eta: e.eta_seconds }),
        onResult: r => setResults(r),
        onError: d => setError(d),
      })
    } catch (e: any) {
      if (e?.name !== 'AbortError') setError(e?.message || 'Backtest failed')
    } finally {
      setLoading(false)
    }
  }

  const activeFilterCount = filters.length

  return (
    <div className="text-slate-100">
      <PageHeader code="BTST" title="Backtest Lab"
        status={<Chip color={T.green} active>PAPER</Chip>}
        subtitle="Capital-managed, friction-aware simulation · signal at close, fill at next open"
        right={results ? (
          <span style={{ fontSize: 11 }}>
            <span style={{ color: results.total_return_pct >= 0 ? T.green : T.red, fontWeight: 700 }}>{fPct(results.total_return_pct)}</span>
            <span style={{ color: T.muted }}> · {results.total_trades} trades · {results.win_rate}% win · DD {results.max_drawdown}%</span>
          </span>
        ) : undefined} />
      <ResearchNote verdict="REFERENCE" report="reports/costs/CAPITAL_VIABILITY.md">
        Costs decide short-hold strategies: a 5-day, 5-name book pays about 48% of capital a year in ICICI charges (108% at
        ₹10,000), monthly momentum about 3–5%. Judge every backtest here after costs, against the Desk.
      </ResearchNote>
      <ResearchNote verdict="FAIL" report="reports/handbook_swing/REPORT.md">
        The old defaults here ({LEGACY_DEFAULTS.maxPositions} names, a {LEGACY_DEFAULTS.stopPct}% stop, a {LEGACY_DEFAULTS.holdSessions}-day
        time-stop, {LEGACY_DEFAULTS.frictionBps} bps) were the legacy 5-day system, which FAILS after costs (−17.8% a year after ICICI
        charges in the rules-only swing backtest). The defaults now follow the Desk: {DESK_LIKE.maxPositions} names, a {DESK_LIKE.holdSessions}-session
        hold, no per-trade stop, the real round trip. The lab has no monthly ranking, so it approximates the Desk, never replicates it.
      </ResearchNote>

      <div className="w-full grid grid-cols-1 lg:grid-cols-4 gap-3">
        {/* ── Control rail ──────────────────────────────────────────────────────── */}
        <div className="lg:col-span-1 space-y-4 lg:max-h-[calc(100vh-130px)] lg:overflow-y-auto pr-1">
          {/* Scope */}
          <div className="rounded-xl border border-slate-700/40 bg-slate-800/30 p-4 space-y-3">
            <h3 className="text-[11px] font-bold text-amber-400 uppercase tracking-widest">Scope</h3>
            <div className="grid grid-cols-2 gap-2">
              {(['universe', 'watchlist'] as const).map(s => (
                <button key={s} onClick={() => setScope(s)}
                  className={clsx('px-2 py-2 rounded-lg text-xs font-semibold border transition-colors',
                    scope === s ? 'bg-amber-500/20 text-amber-300 border-amber-500/40' : 'bg-slate-800/60 text-slate-400 border-slate-700 hover:border-slate-600')}>
                  {s === 'universe' ? 'Full Universe' : `Watchlist (${watchlist.length})`}
                </button>
              ))}
            </div>
            {watchlistEmpty && <p className="text-[11px] text-rose-400">Watchlist empty — star stocks in the Stocks tab.</p>}
          </div>

          {/* Date range */}
          <div className="rounded-xl border border-slate-700/40 bg-slate-800/30 p-4 space-y-3">
            <h3 className="text-[11px] font-bold text-amber-400 uppercase tracking-widest">Window</h3>
            <div className="grid grid-cols-2 gap-2">
              <label className="text-[11px] text-slate-400">From
                <input type="date" value={fromDate} onChange={e => setFromDate(e.target.value)}
                  className="mt-1 w-full px-2 py-1.5 rounded bg-slate-700/50 border border-slate-600 text-slate-100 text-xs font-mono focus:border-amber-500 outline-none" />
              </label>
              <label className="text-[11px] text-slate-400">To
                <input type="date" value={toDate} onChange={e => setToDate(e.target.value)}
                  className="mt-1 w-full px-2 py-1.5 rounded bg-slate-700/50 border border-slate-600 text-slate-100 text-xs font-mono focus:border-amber-500 outline-none" />
              </label>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {PRESETS.map(p => (
                <button key={p.label} onClick={() => setPreset(p.days)}
                  className="px-2 py-1 rounded text-[11px] font-semibold bg-slate-700/40 text-slate-300 hover:bg-slate-600/50">{p.label}</button>
              ))}
            </div>
            <p className="text-[10px] text-slate-500 leading-snug">⤺ A 250-day+ trailing warm-up is loaded <span className="text-slate-400">before</span> your From date, so MA/RSI/ATR/52-week indicators are fully seeded on day one — no cold-start bias.</p>
          </div>

          {/* Capital & risk */}
          <div className="rounded-xl border border-slate-700/40 bg-slate-800/30 p-4 space-y-3">
            <h3 className="text-[11px] font-bold text-amber-400 uppercase tracking-widest">Capital & Risk</h3>
            <label className="block text-[11px] text-slate-400">Starting Capital (₹)
              <input type="number" value={startingCapital} step={100000} min={10000}
                onChange={e => setStartingCapital(Math.max(10000, Number(e.target.value)))}
                className="mt-1 w-full px-2 py-1.5 rounded bg-slate-700/50 border border-slate-600 text-slate-100 text-xs font-mono focus:border-amber-500 outline-none" />
              <span className="text-[10px] text-slate-500">{fCr(startingCapital)}</span>
            </label>
            <div className="grid grid-cols-2 gap-2">
              <label className="block text-[11px] text-slate-400">Friction (bps)
                <input type="number" value={frictionBps ?? ''} step={1} min={MIN_FRICTION_BPS} placeholder="…"
                  onChange={e => { setFrictionAuto(false); setFrictionBps(Math.max(MIN_FRICTION_BPS, Number(e.target.value))) }}
                  className="mt-1 w-full px-2 py-1.5 rounded bg-slate-700/50 border border-slate-600 text-slate-100 text-xs font-mono focus:border-amber-500 outline-none" />
                <span className="text-[10px] text-slate-500">
                  {frictionBps != null ? `${(frictionBps / 100).toFixed(2)}% round trip` : 'reading the cost model…'}
                  {frictionAuto && costNote && costNote !== 'error'
                    ? ` · ${costNote.profile.replace('icici_moneysaver', 'ICICI MoneySaver').replace(/^icici_/, 'ICICI ').replace(/_/g, ' ')} at ₹${costNote.value.toLocaleString('en-IN')} a name (shared/trading_costs.py)`
                    : ''}
                  {costNote === 'error' && frictionAuto ? ' · cost model unavailable: type the friction' : ''}
                  {!frictionAuto && <> · your number · <button type="button" className="underline text-amber-300/80" onClick={() => setFrictionAuto(true)}>use the real cost</button></>}
                </span>
              </label>
              <label className="block text-[11px] text-slate-400">Max Positions
                <input type="number" value={maxPositions} step={1} min={1} max={50}
                  onChange={e => setMaxPositions(Math.min(50, Math.max(1, Number(e.target.value))))}
                  className="mt-1 w-full px-2 py-1.5 rounded bg-slate-700/50 border border-slate-600 text-slate-100 text-xs font-mono focus:border-amber-500 outline-none" />
              </label>
            </div>
            {/* Per-trade stop: OFF by default (the Desk's rules forbid it: it sells winners on normal dips) */}
            <div>
              <label className="block text-[11px] text-slate-400 mb-1">Per-trade stop</label>
              <div className="grid grid-cols-3 gap-1.5">
                {(['none', 'atr', 'fixed'] as const).map(m => (
                  <button key={m} type="button" onClick={() => setStopMode(m)}
                    className={clsx('px-2 py-1.5 rounded-lg text-[11px] font-semibold border transition-colors',
                      stopMode === m ? 'bg-amber-500/20 text-amber-300 border-amber-500/40' : 'bg-slate-800/60 text-slate-400 border-slate-700 hover:border-slate-600')}>
                    {m === 'none' ? 'None (Desk)' : m === 'atr' ? 'k·ATR' : 'Fixed %'}
                  </button>
                ))}
              </div>
              {stopMode !== 'none' && (
                <div className="flex items-center gap-2 mt-1.5">
                  {stopMode === 'atr' && <>
                    <span className="text-[10px] text-slate-500">k</span>
                    <input type="number" value={atrMult} step={0.5} min={0.5} onChange={e => setAtrMult(Number(e.target.value))}
                      className="w-14 px-2 py-1 rounded bg-slate-700/50 border border-slate-600 text-slate-100 text-xs font-mono outline-none" />
                    <span className="text-[10px] text-slate-500">× ATR · else</span>
                  </>}
                  <input type="number" value={stopLossPct} step={0.5} min={0.1} onChange={e => setStopLossPct(Number(e.target.value))}
                    className="w-14 px-2 py-1 rounded bg-slate-700/50 border border-slate-600 text-slate-100 text-xs font-mono outline-none" />
                  <span className="text-[10px] text-slate-500">%</span>
                </div>
              )}
              <p className="text-[10px] text-slate-500 mt-1">{stopMode === 'none' ? 'No per-trade stop: exits come from the hold, as on the Desk' : 'A per-trade stop is the legacy setting the Desk rejected'}</p>
            </div>
            {/* Trailing */}
            <div className="flex items-center gap-2">
              <input type="checkbox" id="tr" checked={trailEnabled} onChange={e => setTrailEnabled(e.target.checked)} className="accent-amber-500" />
              <label htmlFor="tr" className="text-[11px] text-slate-300 flex-1">Trailing Stop</label>
              <input type="number" value={trailingPct} step={0.5} min={0.1} disabled={!trailEnabled}
                onChange={e => setTrailingPct(Number(e.target.value))}
                className="w-16 px-2 py-1 rounded bg-slate-700/50 border border-slate-600 text-slate-100 text-xs font-mono disabled:opacity-40 outline-none" />
              <span className="text-[10px] text-slate-500">%</span>
            </div>
            {/* Max-drawdown circuit breaker */}
            <div className="flex items-center gap-2">
              <input type="checkbox" id="ddh" checked={ddHaltEnabled} onChange={e => setDdHaltEnabled(e.target.checked)} className="accent-amber-500" />
              <label htmlFor="ddh" className="text-[11px] text-slate-300 flex-1" title="Halt new entries once portfolio drawdown breaches this level (the Desk's HARD −20 % rule sells everything instead)">DD Circuit Breaker</label>
              <input type="number" value={ddHaltPct} step={1} min={1} disabled={!ddHaltEnabled}
                onChange={e => setDdHaltPct(Number(e.target.value))}
                className="w-16 px-2 py-1 rounded bg-slate-700/50 border border-slate-600 text-slate-100 text-xs font-mono disabled:opacity-40 outline-none" />
              <span className="text-[10px] text-slate-500">%</span>
            </div>
            {/* Daily-loss halt: a legacy 5-day rule, off on the Desk */}
            <div className="flex items-center gap-2">
              <input type="checkbox" id="dlh" checked={dailyHalt} onChange={e => setDailyHalt(e.target.checked)} className="accent-amber-500" />
              <label htmlFor="dlh" className="text-[11px] text-slate-300 flex-1" title="Halt new entries for the day after a −2 % day (legacy 5-day system rule; the Desk has none)">Daily-loss halt −2% (legacy)</label>
            </div>
            {/* Entry timing — removes same-bar look-ahead */}
            <div>
              <label className="block text-[11px] text-slate-400 mb-1">Entry Timing</label>
              <div className="grid grid-cols-2 gap-2">
                {(['next_open', 'close'] as const).map(et => (
                  <button key={et} onClick={() => setEntryTiming(et)}
                    className={clsx('px-2 py-1.5 rounded-lg text-[11px] font-semibold border transition-colors',
                      entryTiming === et ? 'bg-amber-500/20 text-amber-300 border-amber-500/40' : 'bg-slate-800/60 text-slate-400 border-slate-700 hover:border-slate-600')}>
                    {et === 'next_open' ? 'Next Open' : 'Same Close'}
                  </button>
                ))}
              </div>
              <p className="text-[10px] text-slate-500 mt-1">{entryTiming === 'next_open' ? 'Enters next bar — no same-bar look-ahead' : 'Enters on the signal-bar close'}</p>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <label className="block text-[11px] text-slate-400">Hold (sessions)
                <input type="number" value={forwardDays} step={1} min={1} max={30}
                  onChange={e => setForwardDays(Math.min(30, Math.max(1, Number(e.target.value))))}
                  className="mt-1 w-full px-2 py-1.5 rounded bg-slate-700/50 border border-slate-600 text-slate-100 text-xs font-mono focus:border-amber-500 outline-none" />
              </label>
              <label className="block text-[11px] text-slate-400">Win Threshold %
                <input type="number" value={winThreshold} step={0.5}
                  onChange={e => setWinThreshold(Number(e.target.value))}
                  className="mt-1 w-full px-2 py-1.5 rounded bg-slate-700/50 border border-slate-600 text-slate-100 text-xs font-mono focus:border-amber-500 outline-none" />
              </label>
            </div>
          </div>

          {/* Filters */}
          <div className="rounded-xl border border-slate-700/40 bg-slate-800/30 p-4 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-[11px] font-bold text-amber-400 uppercase tracking-widest">Filters</h3>
              {activeFilterCount > 0 && <button onClick={() => setFilters([])} className="text-[11px] text-slate-400 hover:text-rose-400 underline">clear {activeFilterCount}</button>}
            </div>
            {Object.entries(FILTER_CATALOG).map(([cat, fields]) => (
              <div key={cat} className="space-y-1.5">
                <p className="text-[10px] text-slate-500 uppercase tracking-wider">{cat}</p>
                {fields.map(def => {
                  const active = filters.find(f => f.field === def.id)
                  return (
                    <div key={def.id} className="rounded-lg p-1.5 hover:bg-slate-700/20">
                      <label className="flex items-center gap-2 cursor-pointer">
                        <input type="checkbox" checked={!!active} onChange={() => toggleFilter(def.id)} className="accent-amber-500" />
                        <span className="text-[11px] text-slate-200 flex-1" title={def.desc}>{def.label}{FUNDAMENTAL.has(def.id) && <span className="ml-1 text-amber-500/70" title="Fundamental snapshot (look-ahead-prone)">⚠</span>}
                          {def.id === 'prob_up' && <span className="ml-1.5 px-1 text-[9px] font-mono font-bold border border-rose-500/60 text-rose-300"
                            title="RSCH · ML labels and NSE features: FAIL. The 5-day labels behind this score are flawed and the ML book trails Desk momentum after costs.">RSCH · FAIL</span>}</span>
                      </label>
                      {active && !def.toggle && (
                        <div className="ml-6 mt-1.5 flex gap-1.5 items-center">
                          <select value={active.op} onChange={e => updateFilter(def.id, { op: e.target.value as any })}
                            className="px-1.5 py-1 rounded text-[11px] bg-slate-700/50 border border-slate-600 text-slate-100 font-mono outline-none">
                            <option value="lt">&lt;</option><option value="gt">&gt;</option><option value="lte">≤</option><option value="gte">≥</option>
                          </select>
                          <input type="number" value={active.value} step={0.1} onChange={e => updateFilter(def.id, { value: Number(e.target.value) })}
                            className="w-16 px-1.5 py-1 rounded bg-slate-700/50 border border-slate-600 text-slate-100 font-mono text-[11px] outline-none" />
                          <span className="text-[10px] text-slate-500">{def.unit}</span>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            ))}
          </div>

          {/* WFO */}
          <div className="rounded-xl border border-slate-700/40 bg-slate-800/30 p-4 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-[11px] font-bold text-amber-400 uppercase tracking-widest">Walk-Forward (WFO)</h3>
              <button onClick={() => setWfoMode(v => !v)} className={clsx('relative w-10 h-5 rounded-full transition-colors', wfoMode ? 'bg-amber-500' : 'bg-slate-700')}>
                <div className={clsx('absolute top-0.5 w-4 h-4 rounded-full bg-white transition-transform', wfoMode ? 'right-0.5' : 'left-0.5')} />
              </button>
            </div>
            {wfoMode && (
              <div className="space-y-2">
                <label className="block text-[11px] text-slate-400">Out-of-Sample window (days): <span className="text-amber-300 font-mono">{outSampleDays}</span>
                  <input type="range" min={20} max={180} value={outSampleDays} onChange={e => setOutSampleDays(+e.target.value)} className="w-full accent-amber-500" />
                </label>
                <label className="block text-[11px] text-slate-400">In-Sample context (days): <span className="text-amber-300 font-mono">{inSampleDays}</span>
                  <input type="range" min={30} max={365} value={inSampleDays} onChange={e => setInSampleDays(+e.target.value)} className="w-full accent-amber-500" />
                </label>
                <label className="block text-[11px] text-slate-400">Monte Carlo runs
                  <input type="number" min={100} max={5000} step={100} value={monteCarloRuns} onChange={e => setMonteCarloRuns(+e.target.value)}
                    className="mt-1 w-full px-2 py-1.5 rounded bg-slate-700/50 border border-slate-600 text-amber-300 text-xs font-mono outline-none" />
                </label>
              </div>
            )}
          </div>

          {looksLegacy({ holdSessions: forwardDays, maxPositions, frictionBps: frictionBps ?? MIN_FRICTION_BPS }) && (
            <p className="text-[10.5px] text-rose-300/90 leading-snug">This is a short-hold or floor-cost setup: the configuration the research FAILED after
              costs. Read any result as a cost lesson, not an edge.</p>
          )}
          <button onClick={run} disabled={loading || watchlistEmpty}
            className={clsx('w-full py-3 rounded-xl font-bold uppercase tracking-widest text-sm transition-all',
              loading || watchlistEmpty ? 'bg-slate-700 text-slate-500 cursor-not-allowed' : 'bg-gradient-to-r from-amber-500 to-amber-600 text-slate-950 hover:shadow-lg hover:shadow-amber-500/40')}>
            {loading ? '⟳ Running…' : '▶ Run Backtest'}
          </button>
        </div>

        {/* ── Results ───────────────────────────────────────────────────────────── */}
        <div className="lg:col-span-3 space-y-4">
          {/* Factor Diagnostic Studio — pre-trade threshold discovery (decile IC) */}
          <FactorDiagnosticStudio
            config={{
              fromDate, toDate, forwardDays, winThreshold, frictionBps: frictionBps ?? MIN_FRICTION_BPS,
              scope, watchlist,
            }}
            onApplyThreshold={applyThreshold}
          />

          {/* Bias banner — Pillar 1: fundamental point-in-time alert */}
          {fundamentalActive && (
            <div className="rounded-lg border border-amber-600/50 bg-amber-500/10 px-4 py-2.5 text-[12px] text-amber-200 font-medium">
              [▲ WARNING] Fundamental look-ahead bias active: using current point-in-time snapshot metrics over historical dates.
              <span className="block mt-0.5 text-[11px] text-amber-300/80 font-normal">P/E, ROCE, Mkt-Cap &amp; Div-Yield apply today&apos;s values to past dates. Technical filters (MA/RSI/ATR/52w) are strictly trailing and bias-free.</span>
            </div>
          )}

          {/* ML Signal — leak-safe propensity controls + window notice */}
          {propensityActive && (
            <div className="rounded-lg border border-indigo-600/50 bg-indigo-500/10 px-4 py-2.5 text-[12px] text-indigo-200">
              <div className="flex items-center justify-between gap-3 flex-wrap">
                <span className="font-medium">ƒ ML Signal active — P(up·5d) from a leak-safe holdout model (trained ≤ 2025-05, scored ~last year only). RSCH: its 5-day labels FAIL (reports/ml_labels).</span>
                <label className="flex items-center gap-1.5 text-[11px] font-medium shrink-0">
                  <span className="text-indigo-300/80">Unscored names:</span>
                  <select
                    value={propensityMissing}
                    onChange={e => setPropensityMissing(e.target.value as 'keep' | 'exclude' | 'neutral')}
                    className="rounded bg-slate-800 border border-indigo-600/40 px-1.5 py-0.5 text-indigo-100 text-[11px] focus:outline-none focus:border-indigo-400"
                  >
                    <option value="keep">keep (qualify on other filters)</option>
                    <option value="exclude">exclude (drop)</option>
                    <option value="neutral">neutral (P=0.5)</option>
                  </select>
                </label>
              </div>
              <span className="block mt-0.5 text-[11px] text-indigo-300/70 font-normal">Propensity exists only for 2025-06 → present (the model&apos;s out-of-sample holdout). Outside that window the policy above decides whether a name is kept, dropped, or treated as a coin-flip.</span>
            </div>
          )}

          {error && <div className="rounded-lg border border-rose-600/50 bg-rose-500/10 px-4 py-2.5 text-[12px] text-rose-200">⛔ {error}</div>}

          {/* Progress telemetry */}
          {loading && (
            <div className="rounded-xl border border-slate-700/40 bg-slate-800/30 p-5">
              <div className="flex items-center justify-between text-xs font-mono text-slate-300 mb-2">
                <span>{progress.label || 'Processing…'}</span>
                <span>{progress.pct.toFixed(0)}%{progress.eta != null ? ` · ETA ${progress.eta.toFixed(0)}s` : ''}</span>
              </div>
              <div className="h-2.5 rounded-full bg-slate-700/50 overflow-hidden">
                <div className="h-full bg-gradient-to-r from-amber-500 to-amber-400 transition-all duration-300" style={{ width: `${progress.pct}%` }} />
              </div>
              <p className="mt-2 text-[11px] text-slate-500 font-mono">Simulating finite-capital portfolio across the selected universe…</p>
            </div>
          )}

          {/* Empty state */}
          {!results && !loading && !error && (
            <div className="rounded-xl border border-slate-700/40 bg-gradient-to-br from-slate-800/30 to-slate-900/20 p-16 text-center min-h-[380px] flex flex-col items-center justify-center">
              <div className="text-3xl mb-5 opacity-40 font-mono">◌</div>
              <h2 className="text-lg font-bold text-slate-200 mb-2">Institutional simulation cockpit</h2>
              <p className="text-sm text-slate-400 max-w-md">Start with the Desk-like baseline: {DESK_LIKE.maxPositions} names, a {DESK_LIKE.holdSessions}-session hold,
                no per-trade stop{frictionBps != null ? `, ${(frictionBps / 100).toFixed(2)}% a round trip` : ''}, no filters, last year. Then add one filter
                (for example Price &gt; 200-MA, the evidence-backed veto) and compare the two runs after costs, against the Desk.</p>
              <button onClick={run} disabled={loading || watchlistEmpty || frictionBps == null}
                className="mt-5 px-4 py-2 rounded-lg text-xs font-bold uppercase tracking-widest border border-amber-500/50 text-amber-300 hover:bg-amber-500/10 disabled:opacity-40">
                ▶ Run the Desk-like baseline
              </button>
              <p className="text-[10.5px] text-slate-500 max-w-md mt-3">A backtest describes what a rule did; it predicts nothing until a pre-registered,
                out-of-sample study passes (RSCH).</p>
            </div>
          )}

          {results && !loading && (
            <>
              {/* KPI matrix */}
              <div className="rounded-xl border border-slate-700/40 bg-slate-900/30 p-3 space-y-3">
                <div className="flex items-center justify-between px-1">
                  <p className="text-[10px] text-emerald-400 uppercase tracking-widest font-bold">Returns</p>
                  <p className="text-[10px] text-slate-500 font-mono">
                    {results.config.scope} · {results.config.n_tickers} tickers · {results.config.entry_timing === 'close' ? 'close-entry' : 'next-open'} · vs {results.config.benchmark_label}
                    {results.config.fundamentals_as_of ? ` · fundamentals @ ${results.config.fundamentals_as_of}` : ''}
                    {propensityActive && results.config.propensity_pit
                      ? ` · ML coverage ${(results.config.propensity_coverage_pct ?? 0).toFixed(0)}%${results.config.propensity_coverage_start ? ` from ${results.config.propensity_coverage_start}` : ''} (${results.config.propensity_missing_policy ?? 'keep'})`
                      : ''}
                  </p>
                </div>
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2">
                  <Kpi label="Total Return" value={fPct(results.total_return_pct)} tone={results.total_return_pct >= 0 ? 'emerald' : 'rose'} sub={`bmk ${fPct(results.benchmark_total_return_pct)}`} />
                  <Kpi label="CAGR" value={fPct(results.cagr_pct)} tone={results.cagr_pct >= 0 ? 'emerald' : 'rose'} />
                  <Kpi label="Final NAV" value={fCr(results.final_nav)} tone="amber" sub={`from ${fCr(results.starting_capital)}`} />
                  <Kpi label="Alpha (ann.)" value={fPct(results.alpha_annual_pct)} tone={results.alpha_annual_pct >= 0 ? 'emerald' : 'rose'} />
                  <Kpi label="Beta" value={fNum(results.beta)} tone="indigo" />
                  <Kpi label="Sharpe" value={fNum(results.sharpe_ratio)} tone="slate" />
                </div>
                <p className="text-[10px] text-rose-400 uppercase tracking-widest font-bold px-1 pt-1">Risk</p>
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2">
                  <Kpi label="Sortino" value={fNum(results.sortino_ratio)} />
                  <Kpi label="Calmar" value={fNum(results.calmar_ratio)} />
                  <Kpi label="Max Drawdown" value={`${fNum(results.max_drawdown)}%`} tone="rose" />
                  <Kpi label="DD Duration" value={`${results.max_drawdown_duration_days}d`} tone="rose" sub="peak→recovery" />
                  <Kpi label="Profit Factor" value={fNum(results.profit_factor)} tone={results.profit_factor >= 1 ? 'emerald' : 'rose'} />
                  <Kpi label="Expectancy" value={`${fNum(results.expectancy)}%`} tone={results.expectancy >= 0 ? 'emerald' : 'rose'} sub="net / trade" />
                </div>
                <p className="text-[10px] text-amber-400 uppercase tracking-widest font-bold px-1 pt-1">Trade Quality</p>
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2">
                  <Kpi label="Win Rate" value={`${fNum(results.win_rate, 1)}%`} tone="amber" />
                  <Kpi label="Total Trades" value={results.total_trades.toLocaleString('en-IN')} />
                  <Kpi label="Avg Win" value={fPct(results.avg_win_return)} tone="emerald" />
                  <Kpi label="Avg Loss" value={`${fNum(results.avg_loss_return)}%`} tone="rose" />
                  <Kpi label="Win/Loss" value={fNum(results.win_loss_ratio)} tone={results.win_loss_ratio >= 1 ? 'emerald' : 'rose'} />
                  <Kpi label="Exits SL/TR/TM" value={`${results.exit_breakdown.stop_loss}/${results.exit_breakdown.trailing_stop}/${results.exit_breakdown.time_stop}`} sub="stop/trail/time" />
                </div>
              </div>

              {/* Equity cockpit */}
              {results.equity_curve.length > 0 && (
                <div className="rounded-xl border border-slate-700/40 bg-slate-800/30 p-4">
                  <div className="flex items-center justify-between mb-3">
                    <h3 className="text-xs font-bold text-slate-200 uppercase tracking-wide">Compounded Equity · NAV vs Benchmark · Drawdown</h3>
                    <div className="flex gap-2">
                      <button onClick={() => results && exportBacktestCSV(results)} className="px-2.5 py-1 rounded bg-slate-700/50 text-slate-300 text-[11px] font-semibold hover:bg-slate-700">⬇ CSV</button>
                      <button onClick={() => results && exportBacktestExcel(results)} className="px-2.5 py-1 rounded bg-emerald-600/30 text-emerald-200 text-[11px] font-semibold hover:bg-emerald-600/50 border border-emerald-600/40">⬇ Excel</button>
                    </div>
                  </div>
                  <EquityCockpitChart data={results.equity_curve} />
                </div>
              )}

              {/* WFO comparative grid */}
              {results.wfo_windows && results.wfo_windows.length > 0 && (
                <div className="rounded-xl border border-amber-600/30 bg-slate-800/30 p-4">
                  <h3 className="text-xs font-bold text-amber-300 uppercase tracking-wide mb-3">Walk-Forward — Out-of-Sample Windows</h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-[11px] font-mono">
                      <thead className="text-slate-400 border-b border-slate-700">
                        <tr>
                          {['Window', 'Trades', 'Avg %', 'Total %', 'Win %', 'Best', 'Worst'].map(h => <th key={h} className="px-2 py-1.5 text-right first:text-left uppercase">{h}</th>)}
                        </tr>
                      </thead>
                      <tbody>
                        {results.wfo_windows.map((w, i) => (
                          <tr key={i} className="border-b border-slate-800/60">
                            <td className="px-2 py-1.5 text-slate-300">{w.start} → {w.end}</td>
                            <td className="px-2 py-1.5 text-right text-slate-300">{w.trades}</td>
                            <td className={clsx('px-2 py-1.5 text-right font-bold', w.return_pct >= 0 ? 'text-emerald-400' : 'text-rose-400')}>{fPct(w.return_pct)}</td>
                            <td className={clsx('px-2 py-1.5 text-right', w.total_return_pct >= 0 ? 'text-emerald-400/80' : 'text-rose-400/80')}>{fPct(w.total_return_pct)}</td>
                            <td className="px-2 py-1.5 text-right text-slate-300">{w.win_rate}%</td>
                            <td className="px-2 py-1.5 text-right text-emerald-400/70">+{fNum(w.best)}</td>
                            <td className="px-2 py-1.5 text-right text-rose-400/70">{fNum(w.worst)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* Monte Carlo */}
              {results.monte_carlo && results.monte_carlo.histogram.length > 0 && (
                <div className="rounded-xl border border-slate-700/40 bg-slate-800/30 p-4">
                  <h3 className="text-xs font-bold text-slate-200 uppercase tracking-wide mb-3">Monte Carlo — Max Drawdown Distribution</h3>
                  <ResponsiveContainer width="100%" height={180}>
                    <BarChart data={results.monte_carlo.histogram.map((count, idx) => ({ bucket: idx, count }))}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#1a2130" />
                      <XAxis dataKey="bucket" tick={{ fontSize: 10, fill: T.muted }} />
                      <YAxis tick={{ fontSize: 10, fill: T.muted }} />
                      <Tooltip contentStyle={{ backgroundColor: T.bg, border: '1px solid #2a3448', borderRadius: 8, color: '#f1f5f9', fontSize: 11 }} />
                      <Bar dataKey="count" fill="#ffb000" radius={[3, 3, 0, 0]} />
                      <ReferenceLine x={Math.floor(results.monte_carlo.histogram.length * 0.05)} stroke="#ef4444" strokeDasharray="4 2" label={{ value: `p95 ${results.monte_carlo.p95.toFixed(0)}%`, fill: '#ef4444', fontSize: 10, position: 'top' }} />
                    </BarChart>
                  </ResponsiveContainer>
                  <div className="mt-2 grid grid-cols-5 gap-2 text-center text-[11px] font-mono">
                    {(['p5', 'p25', 'p50', 'p75', 'p95'] as const).map(p => (
                      <div key={p} className={clsx('rounded-lg p-1.5', p === 'p95' ? 'bg-rose-500/15 text-rose-300' : p === 'p50' ? 'bg-amber-500/15 text-amber-300' : 'bg-slate-700/40 text-slate-300')}>
                        <div className="opacity-60">{p}</div><div className="font-bold">{results.monte_carlo![p].toFixed(1)}%</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Trade grid */}
              {results.trades.length > 0 && (
                <div className="rounded-xl border border-slate-700/40 bg-slate-800/30 overflow-hidden">
                  <div className="flex items-center justify-between px-3 py-2 border-b border-slate-700/50">
                    <h3 className="text-xs font-bold text-slate-200 uppercase tracking-wide">Trade Blotter <span className="text-slate-500 font-normal">({results.trades.length})</span></h3>
                  </div>
                  <BacktestTradeGrid trades={results.trades} onTradeClick={setSelectedTrade} />
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {selectedTrade && <StockDetailModal ticker={selectedTrade.ticker} onClose={() => setSelectedTrade(null)} />}
    </div>
  )
}
