'use client'

/**
 * FactorDiagnosticStudio — the "📊 Factor Diagnostic Studio" accordion.
 *
 * Sorts the raw values of any numeric indicator across the historical universe,
 * buckets them into 10 equal-population deciles, and maps each decile against the
 * friction-aware forward win base rate. A dual-axis chart shows Event Rate (bars,
 * left) vs Sample Size (line, right) with the Global Asset Base Rate drawn as a
 * dashed reference, so the user can spot statistically-outperforming deciles that
 * are NOT illiquid low-sample anomalies. Clicking a decile pushes its boundary
 * straight back into the Tier-1 filter inputs.
 *
 * MODE = PAPER — this is pure diagnostics, no orders.
 */

import { useCallback, useEffect, useRef, useState } from 'react'
import clsx from 'clsx'
import {
  Bar, CartesianGrid, Cell, ComposedChart, Line, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { fetchFactorProfile, type FactorProfileResult, type FactorDecile } from '@/lib/factorProfile'

// Numeric factors only — mirrors backtest_engine.FIELD_MAP (boolean toggles excluded).
const FACTORS: Array<{ id: string; label: string; unit: string; fundamental?: boolean }> = [
  { id: 'rsi_14', label: 'RSI (14)', unit: '' },
  { id: 'atr_14_pct', label: 'ATR %', unit: '%' },
  { id: 'dist_ma200_pct', label: 'Distance from 200-MA', unit: '%' },
  { id: 'above_52w_low_pct', label: '% above 52w-Low', unit: '%' },
  { id: 'within_52w_high_pct', label: '% within 52w-High', unit: '%' },
  { id: 'pe_ratio', label: 'P/E Ratio', unit: 'x', fundamental: true },
  { id: 'div_yld_pct', label: 'Dividend Yield', unit: '%', fundamental: true },
  { id: 'mktcap_cr', label: 'Market Cap', unit: 'Cr', fundamental: true },
  { id: 'roce_pct', label: 'ROCE', unit: '%', fundamental: true },
]

export interface FactorStudioConfig {
  fromDate: string
  toDate: string
  forwardDays: number
  winThreshold: number
  frictionBps: number
  scope: 'universe' | 'watchlist'
  watchlist: string[]
}

interface Props {
  config: FactorStudioConfig
  onApplyThreshold: (field: string, op: 'gte' | 'lte', value: number) => void
}

const fNum = (n: number, d = 2) => (n ?? 0).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d })
const fInt = (n: number) => (n ?? 0).toLocaleString('en-IN')

export function FactorDiagnosticStudio({ config, onApplyThreshold }: Props) {
  const [open, setOpen] = useState(false)
  const [factor, setFactor] = useState('rsi_14')
  const [result, setResult] = useState<FactorProfileResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [applied, setApplied] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const meta = FACTORS.find(f => f.id === factor)!

  const run = useCallback(async () => {
    abortRef.current?.abort()
    const ac = new AbortController()
    abortRef.current = ac
    setLoading(true); setError(null)
    try {
      const r = await fetchFactorProfile({
        factor,
        from_date: config.fromDate,
        to_date: config.toDate,
        forward_days: config.forwardDays,
        win_threshold: config.winThreshold,
        friction_bps: config.frictionBps,
        scope: config.scope,
        tickers: config.scope === 'watchlist' ? config.watchlist : [],
        n_deciles: 10,
      }, ac.signal)
      setResult(r)
    } catch (e: any) {
      if (e?.name !== 'AbortError') setError(e?.message || 'Profiling failed')
    } finally {
      setLoading(false)
    }
  }, [factor, config])

  // Auto-profile when the accordion opens or the factor changes (only while open).
  useEffect(() => {
    if (open) run()
    return () => abortRef.current?.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, factor])

  // Higher-decile-is-better when the event-rate trend rises with the factor.
  // Apply ≥ lower-edge to keep the outperforming tail; otherwise ≤ upper-edge.
  const applyDecile = (d: FactorDecile) => {
    const ascending = (result?.monotonicity_spearman ?? 0) >= 0
    const op: 'gte' | 'lte' = ascending ? 'gte' : 'lte'
    const value = ascending ? d.lo : d.hi
    onApplyThreshold(factor, op, Number(value.toFixed(4)))
    setApplied(`${meta.label} ${op === 'gte' ? '≥' : '≤'} ${fNum(value)} ${meta.unit} → filter applied (D${d.decile})`)
    setTimeout(() => setApplied(null), 4000)
  }

  const chartData = (result?.deciles ?? []).map(d => ({
    name: `D${d.decile}`,
    range: `${fNum(d.lo, d.lo >= 1000 ? 0 : 1)}–${fNum(d.hi, d.hi >= 1000 ? 0 : 1)}`,
    event_rate: d.event_rate,
    samples: d.samples,
    lift: d.lift,
    raw: d,
  }))
  const base = result?.global_base_rate ?? 0

  const CustomTick = (props: any) => {
    const { x, y, payload } = props
    const datum = chartData[payload.index]
    return (
      <g transform={`translate(${x},${y})`}>
        <text x={0} y={0} dy={12} textAnchor="middle" fontSize={11} fontWeight={700} fill="#cbd5e1" fontFamily="monospace">{payload.value}</text>
        <text x={0} y={0} dy={26} textAnchor="middle" fontSize={8.5} fill="#64748b" fontFamily="monospace">[{datum?.range}]</text>
      </g>
    )
  }

  const ChartTooltip = ({ active, payload }: any) => {
    if (!active || !payload?.length) return null
    const d = payload[0]?.payload?.raw as FactorDecile | undefined
    if (!d) return null
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-900/95 px-3 py-2 text-[11px] font-mono shadow-xl">
        <div className="text-amber-300 font-bold mb-1">Decile {d.decile} · {meta.label}</div>
        <div className="text-slate-300">Range: <span className="text-slate-100">{fNum(d.lo)} → {fNum(d.hi)} {meta.unit}</span></div>
        <div className="text-slate-300">Event Rate: <span className={d.lift >= 0 ? 'text-emerald-300' : 'text-rose-300'}>{fNum(d.event_rate)}%</span> <span className="text-slate-500">({d.lift >= 0 ? '+' : ''}{fNum(d.lift)} vs base)</span></div>
        <div className="text-slate-300">Samples: <span className="text-indigo-300">{fInt(d.samples)}</span> · Wins: {fInt(d.positives)}</div>
        <div className="mt-1 text-[10px] text-amber-400/80">click to apply boundary →</div>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-slate-700/40 bg-slate-900/40 overflow-hidden">
      {/* Accordion header */}
      <button onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-3 px-4 py-3 hover:bg-slate-800/40 transition-colors">
        <span className="text-lg">📊</span>
        <div className="text-left min-w-0">
          <h3 className="text-sm font-bold text-slate-100 flex items-center gap-2">
            Factor Diagnostic Studio
            <span className="text-[9px] font-mono px-1.5 py-0.5 rounded bg-indigo-500/15 text-indigo-300 border border-indigo-500/30">DECILE IC</span>
          </h3>
          <p className="text-[11px] text-slate-500 hidden sm:block">Stop guessing thresholds — profile any factor against the forward win base rate</p>
        </div>
        <div className="ml-auto flex items-center gap-3">
          {result && !open && (
            <span className="text-[11px] font-mono text-slate-400 hidden md:block">
              base {fNum(result.global_base_rate)}% · {fInt(result.total_samples)} obs
            </span>
          )}
          <span className={clsx('text-slate-400 transition-transform', open && 'rotate-180')}>▾</span>
        </div>
      </button>

      {open && (
        <div className="border-t border-slate-800 p-4 space-y-3 relative">
          {/* Controls */}
          <div className="flex flex-wrap items-center gap-2">
            <label className="text-[11px] text-slate-400 font-semibold uppercase tracking-wider">Factor</label>
            <select value={factor} onChange={e => setFactor(e.target.value)}
              className="px-2.5 py-1.5 rounded-lg bg-slate-800/70 border border-slate-600 text-slate-100 text-xs font-mono focus:border-amber-500 outline-none">
              {FACTORS.map(f => (
                <option key={f.id} value={f.id}>{f.label}{f.fundamental ? ' ⚠' : ''}</option>
              ))}
            </select>
            <button onClick={run} disabled={loading}
              className={clsx('px-3 py-1.5 rounded-lg text-xs font-bold uppercase tracking-wide transition-colors',
                loading ? 'bg-slate-700 text-slate-500' : 'bg-amber-500/20 text-amber-300 border border-amber-500/40 hover:bg-amber-500/30')}>
              {loading ? '⟳ Analyzing…' : '▶ Re-profile'}
            </button>
            <span className="text-[10px] text-slate-500 font-mono ml-auto hidden lg:block">
              {config.scope} · fwd {config.forwardDays}d · win&gt;{fNum(config.winThreshold)}% · {config.frictionBps}bps
            </span>
          </div>

          {/* Look-ahead structural guard */}
          {result?.lookahead_bias_present && (
            <div className="rounded-lg border border-amber-600/50 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-200">
              ⚠️ LOOK-AHEAD BIAS: <span className="font-semibold">{meta.label}</span> is a current fundamental snapshot applied to historical dates — decile ranks are point-in-time-inaccurate. Treat as indicative only.
            </div>
          )}

          {applied && (
            <div className="rounded-lg border border-emerald-600/50 bg-emerald-500/10 px-3 py-2 text-[11px] text-emerald-200 font-mono">✓ {applied}</div>
          )}
          {error && <div className="rounded-lg border border-rose-600/50 bg-rose-500/10 px-3 py-2 text-[11px] text-rose-200">⛔ {error}</div>}

          {/* Summary chips */}
          {result && !error && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              <Chip label="Global Base Rate" value={`${fNum(result.global_base_rate)}%`} tone="amber" sub="dashed line" />
              <Chip label="Total Observations" value={fInt(result.total_samples)} tone="slate" sub={`${result.config.n_tickers} tickers`} />
              <Chip label="Monotonicity (ρ)" value={fNum(result.monotonicity_spearman)} tone={Math.abs(result.monotonicity_spearman) > 0.5 ? 'emerald' : 'slate'} sub="rank corr" />
              <Chip label="Best / Worst Decile" value={`D${result.best_decile ?? '–'} / D${result.worst_decile ?? '–'}`} tone="indigo" sub={result.degenerate ? 'degenerate' : `${result.n_deciles_effective} buckets`} />
            </div>
          )}

          {/* Dual-axis decile chart */}
          {result && chartData.length > 0 && !error && (
            <div className="rounded-lg border border-slate-700/40 bg-slate-950/50 p-3">
              <div className="flex items-center justify-between mb-1 px-1">
                <span className="text-[10px] text-emerald-400 uppercase tracking-widest font-bold">Event Rate % (bars)</span>
                <span className="text-[10px] text-indigo-400 uppercase tracking-widest font-bold">Sample Size (line)</span>
              </div>
              <ResponsiveContainer width="100%" height={300}>
                <ComposedChart data={chartData} margin={{ top: 12, right: 12, bottom: 18, left: 4 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                  <XAxis dataKey="name" tick={<CustomTick />} height={40} interval={0} stroke="#334155" />
                  <YAxis yAxisId="left" tick={{ fontSize: 10, fill: '#64748b', fontFamily: 'monospace' }}
                    stroke="#334155" label={{ value: 'Event %', angle: -90, position: 'insideLeft', fontSize: 10, fill: '#64748b' }} />
                  <YAxis yAxisId="right" orientation="right" tick={{ fontSize: 10, fill: '#64748b', fontFamily: 'monospace' }}
                    stroke="#334155" />
                  <Tooltip content={<ChartTooltip />} cursor={{ fill: 'rgba(148,163,184,0.08)' }} />
                  <ReferenceLine yAxisId="left" y={base} stroke="#f59e0b" strokeDasharray="6 3" strokeWidth={1.5}
                    label={{ value: `BASE ${fNum(base)}%`, position: 'right', fontSize: 9, fill: '#f59e0b', fontFamily: 'monospace' }} />
                  <Bar yAxisId="left" dataKey="event_rate" radius={[3, 3, 0, 0]} cursor="pointer"
                    onClick={(d: any) => { const raw = d?.raw ?? d?.payload?.raw; if (raw) applyDecile(raw) }}>
                    {chartData.map((d, i) => (
                      <Cell key={i} fill={d.lift >= 0 ? '#10b981' : '#64748b'} fillOpacity={d.lift >= 0 ? 0.9 : 0.55} />
                    ))}
                  </Bar>
                  <Line yAxisId="right" type="monotone" dataKey="samples" stroke="#818cf8" strokeWidth={2}
                    dot={{ r: 3, fill: '#818cf8' }} activeDot={{ r: 5 }} />
                </ComposedChart>
              </ResponsiveContainer>
              <p className="text-[10px] text-slate-500 mt-1 px-1 font-mono">
                Green decile = outperforms base rate · click any bar to push its boundary into Tier-1 filters
                {result.monotonicity_spearman >= 0 ? ' (≥ lower edge)' : ' (≤ upper edge)'}
              </p>
            </div>
          )}

          {result && chartData.length === 0 && !loading && !error && (
            <div className="rounded-lg border border-slate-700/40 bg-slate-800/30 px-4 py-8 text-center text-slate-400 text-sm">
              No candidate instances in this window/scope. {result.note ? `(${result.note})` : 'Widen the date range.'}
            </div>
          )}

          {/* Dark terminal loading overlay */}
          {loading && (
            <div className="absolute inset-0 z-20 flex flex-col items-center justify-center rounded-xl bg-slate-950/85 backdrop-blur-sm">
              <div className="h-7 w-7 rounded-full border-2 border-slate-700 border-t-amber-400 animate-spin" />
              <div className="font-mono text-amber-400 text-sm mt-3 animate-pulse">⟳ DECILE ENGINE</div>
              <div className="font-mono text-[11px] text-slate-400 mt-1">sorting {meta.label} across the universe…</div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Chip({ label, value, tone, sub }: { label: string; value: string; tone: 'amber' | 'emerald' | 'rose' | 'slate' | 'indigo'; sub?: string }) {
  const toneMap = { amber: 'text-amber-300', emerald: 'text-emerald-300', rose: 'text-rose-300', slate: 'text-slate-100', indigo: 'text-indigo-300' }
  return (
    <div className="rounded-lg border border-slate-700/40 bg-slate-800/40 px-3 py-2">
      <p className="text-[9px] text-slate-500 uppercase tracking-widest font-semibold truncate">{label}</p>
      <p className={clsx('text-sm font-bold font-mono tabular-nums leading-tight mt-0.5', toneMap[tone])}>{value}</p>
      {sub && <p className="text-[9px] text-slate-500 font-mono mt-0.5 truncate">{sub}</p>}
    </div>
  )
}
