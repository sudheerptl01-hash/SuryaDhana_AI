'use client'

/**
 * GlassBoxStudio — Pillar-2 multi-dimensional "glass-box" charting environments.
 *
 *   ROTATION         Relative Rotation Graph (RS-Ratio × RS-Momentum quadrants)
 *   CORRELATION      Rolling 30d Nifty correlation + Squeeze/VIPT alert dots
 *   VOLUME PROFILE   Horizontal volume-by-price (HVN/LVN/POC) + anchored VWAP
 *
 * All series are computed server-side off the same trailing, look-ahead-free
 * engine that drives the Backtest Lab. MODE = PAPER.
 */
import { useCallback, useMemo, useRef, useState } from 'react'
import { T } from '@/components/terminal'   // T.muted for axis text (RUP-06: one muted grey)
import clsx from 'clsx'
import { ChartActions } from './terminal/ChartActions'
import {
  ComposedChart, ScatterChart, Scatter, BarChart, Bar, Line, XAxis, YAxis, ZAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, ReferenceLine, ReferenceArea, Cell,
} from 'recharts'
import {
  fetchFactorSeries, fetchRRG, fetchVolumeProfile,
  type FactorSeriesResult, type RRGResult, type VolumeProfileResult,
} from '@/lib/glassbox'
import { trailingRange } from '@/lib/format'

type Mode = 'rotation' | 'correlation' | 'volume'
interface Props { isDark?: boolean }

const PALETTE = ['#38bdf8', '#34d399', '#ffb000', '#f472b6', '#a78bfa', '#fb7185', '#22d3ee', '#facc15', '#4ade80', '#c084fc']
const QUAD = {
  Leading:   { fill: '#10b981', label: 'LEADING' },
  Weakening: { fill: '#ffb000', label: 'WEAKENING' },
  Lagging:   { fill: '#ef4444', label: 'LAGGING' },
  Improving: { fill: '#3b82f6', label: 'IMPROVING' },
}

export function GlassBoxStudio({ isDark = true }: Props) {
  const [mode, setMode] = useState<Mode>('rotation')
  const [tickers, setTickers] = useState('RELIANCE TCS INFY HDFCBANK ICICIBANK SBIN ITC LT')
  // default: the last 9 months up to today (IST); it used to be a fixed 2025-09-01 → 2026-05-31 (C1-18)
  const [fromDate, setFromDate] = useState(() => trailingRange(9).from)
  const [toDate, setToDate] = useState(() => trailingRange(9).to)

  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [rrg, setRrg] = useState<RRGResult | null>(null)
  const [series, setSeries] = useState<FactorSeriesResult | null>(null)
  const [vp, setVp] = useState<VolumeProfileResult | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const tickerList = useMemo(
    () => tickers.split(/[,\s]+/).map(t => t.trim().toUpperCase()).filter(Boolean),
    [tickers])

  const run = useCallback(async () => {
    abortRef.current?.abort()
    const ac = new AbortController(); abortRef.current = ac
    setLoading(true); setErr(null)
    try {
      if (mode === 'rotation') {
        setRrg(await fetchRRG({ tickers: tickerList, from_date: fromDate, to_date: toDate, tail: 10 }, ac.signal))
      } else if (mode === 'correlation') {
        setSeries(await fetchFactorSeries({ ticker: tickerList[0] || 'RELIANCE', from_date: fromDate, to_date: toDate }, ac.signal))
      } else {
        setVp(await fetchVolumeProfile({ ticker: tickerList[0] || 'RELIANCE', from_date: fromDate, to_date: toDate, bins: 24 }, ac.signal))
      }
    } catch (e: any) {
      if (!ac.signal.aborted) setErr(e?.message || 'Request failed')
    } finally {
      if (!ac.signal.aborted) setLoading(false)
    }
  }, [mode, tickerList, fromDate, toDate])

  const card = 'rounded-lg border border-slate-700/60 bg-slate-900/40'

  return (
    <div className="font-mono text-slate-200 space-y-4">
      {/* control bar */}
      <div className={clsx(card, 'p-4')}>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[10px] font-bold tracking-[0.18em] text-slate-400">STUDIO CONTROLS</span>
          <span className="px-1.5 py-0.5 text-[9px] font-bold tracking-wider border" style={{ color: '#39c6ff', borderColor: '#39c6ff55', background: '#39c6ff12' }}>PAPER</span>
          <div className="ml-auto flex gap-1">
            {(['rotation', 'correlation', 'volume'] as Mode[]).map(m => (
              <button key={m} onClick={() => setMode(m)}
                className={clsx('px-2.5 py-1 rounded text-[10px] font-bold uppercase tracking-wide',
                  mode === m ? 'bg-sky-500/20 text-sky-200 border border-sky-500/50' : 'bg-slate-800 text-slate-400 border border-slate-700')}>
                {m === 'rotation' ? 'Rotation (RRG)' : m === 'correlation' ? 'Corr & Squeeze' : 'Volume Profile'}
              </button>
            ))}
          </div>
        </div>
        <div className="mt-3 grid grid-cols-1 sm:grid-cols-4 gap-2">
          <label className="sm:col-span-2 flex flex-col gap-1">
            <span className="text-[9px] uppercase tracking-wider text-slate-500">
              {mode === 'rotation' ? 'Basket (RRG plots all)' : 'Ticker (uses first)'}
            </span>
            <input value={tickers} onChange={e => setTickers(e.target.value)}
              className="px-2 py-1 rounded bg-slate-800 border border-slate-700 text-[11px] focus:border-sky-500 outline-none" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[9px] uppercase tracking-wider text-slate-500">From</span>
            <input type="date" value={fromDate} onChange={e => setFromDate(e.target.value)}
              className="px-2 py-1 rounded bg-slate-800 border border-slate-700 text-[11px] focus:border-sky-500 outline-none" />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[9px] uppercase tracking-wider text-slate-500">To</span>
            <input type="date" value={toDate} onChange={e => setToDate(e.target.value)}
              className="px-2 py-1 rounded bg-slate-800 border border-slate-700 text-[11px] focus:border-sky-500 outline-none" />
          </label>
        </div>
        <div className="mt-3">
          <button onClick={run} disabled={loading}
            className="px-3 py-1.5 rounded text-[11px] font-bold bg-emerald-600/20 border border-emerald-500/50 text-emerald-200 hover:bg-emerald-600/30 disabled:opacity-40">
            {loading ? 'Rendering…' : '▶ Render'}
          </button>
        </div>
      </div>

      {err && <div className="rounded-lg border border-rose-600/50 bg-rose-950/30 px-4 py-2 text-[11px] text-rose-300">⚠ {err}</div>}

      {mode === 'rotation' && <RRGPanel data={rrg} loading={loading} />}
      {mode === 'correlation' && <CorrPanel data={series} loading={loading} />}
      {mode === 'volume' && <VolumePanel data={vp} loading={loading} />}
    </div>
  )
}

// Share volume in the Indian compact style used across the terminal (K / L / cr).
const fmtVolume = (v: number) =>
  v >= 1e7 ? `${+(v / 1e7).toFixed(1)}cr` : v >= 1e5 ? `${+(v / 1e5).toFixed(1)}L` : v >= 1e3 ? `${+(v / 1e3).toFixed(0)}K` : `${v}`

/* ── Relative Rotation Graph ──────────────────────────────────────────────────── */
function RRGPanel({ data, loading }: { data: RRGResult | null; loading: boolean }) {
  const entries = data ? Object.entries(data.tickers) : []
  // Auto-fit axes around 100 with a symmetric margin, rounded to 0.5 so ticks land on
  // readable values (100 ± m, ± m/2) instead of recharts' raw float divisions.
  const all = entries.flatMap(([, pts]) => pts)
  const ext = (key: 'rs_ratio' | 'rs_mom') => {
    const v = all.map(p => p[key]).filter((x): x is number => x != null)
    const m = Math.ceil(Math.max(2, ...v.map(x => Math.abs(x - 100))) * 1.1 * 2) / 2
    return [100 - m, 100 + m] as [number, number]
  }
  const xd = all.length ? ext('rs_ratio') : [96, 104]
  const yd = all.length ? ext('rs_mom') : [96, 104]
  const ticks = ([lo, hi]: number[]) => [lo, (lo + 100) / 2, 100, (hi + 100) / 2, hi]
  const fmtAxis = (v: number) => v.toFixed(1)

  return (
    <div className="rounded-lg border border-slate-700/60 bg-slate-900/40 p-3">
      <PanelHead title="RELATIVE ROTATION GRAPH" sub={data ? `vs ${data.benchmark}` : 'RS-Ratio × RS-Momentum'} />
      <div className="h-[440px]">
        {!data || !entries.length ? (
          <Empty loading={loading} hint="Render a basket to map sector/stock rotation." />
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={{ top: 10, right: 20, bottom: 16, left: 0 }}>
              {/* quadrant backgrounds */}
              <ReferenceArea x1={100} x2={xd[1]} y1={100} y2={yd[1]} fill={QUAD.Leading.fill} fillOpacity={0.06} />
              <ReferenceArea x1={100} x2={xd[1]} y1={yd[0]} y2={100} fill={QUAD.Weakening.fill} fillOpacity={0.06} />
              <ReferenceArea x1={xd[0]} x2={100} y1={yd[0]} y2={100} fill={QUAD.Lagging.fill} fillOpacity={0.06} />
              <ReferenceArea x1={xd[0]} x2={100} y1={100} y2={yd[1]} fill={QUAD.Improving.fill} fillOpacity={0.06} />
              <CartesianGrid strokeDasharray="2 4" stroke="#1a2130" />
              <ReferenceLine x={100} stroke="#475569" />
              <ReferenceLine y={100} stroke="#475569" />
              <XAxis type="number" dataKey="rs_ratio" domain={xd} ticks={ticks(xd)} tickFormatter={fmtAxis} name="RS-Ratio" tick={{ fontSize: 9, fill: T.muted }} stroke="#2a3448"
                label={{ value: 'JdK RS-Ratio →', position: 'insideBottom', dy: 12, fontSize: 9, fill: '#475569' }} />
              <YAxis type="number" dataKey="rs_mom" domain={yd} ticks={ticks(yd)} tickFormatter={fmtAxis} width={52} name="RS-Momentum" tick={{ fontSize: 9, fill: T.muted }} stroke="#2a3448"
                label={{ value: 'RS-Momentum ↑', angle: -90, position: 'insideLeft', fontSize: 9, fill: '#475569' }} />
              <ZAxis range={[20, 20]} />
              <Tooltip cursor={{ strokeDasharray: '3 3' }}
                contentStyle={{ background: '#0a0e17', border: '1px solid #1a2130', fontSize: 11, fontFamily: 'monospace' }}
                formatter={(v: any, n: any) => [typeof v === 'number' ? v.toFixed(2) : v, n]} />
              {entries.map(([tkr, pts], i) => {
                const color = PALETTE[i % PALETTE.length]
                const head = pts[pts.length - 1]
                return (
                  <Scatter key={tkr} name={tkr} data={pts} line={{ stroke: color, strokeWidth: 1.4 }}
                    lineType="joint" fill={color} fillOpacity={0.55}
                    shape={(props: any) => {
                      const isHead = props.payload?.date === head?.date
                      return (
                        <g>
                          <circle cx={props.cx} cy={props.cy} r={isHead ? 5 : 2.5}
                            fill={color} stroke={isHead ? '#0a0e17' : 'none'} strokeWidth={isHead ? 1.5 : 0} />
                          {isHead && <text x={props.cx + 7} y={props.cy + 3} fontSize={9} fill={color}>{tkr}</text>}
                        </g>
                      )
                    }} />
                )
              })}
            </ScatterChart>
          </ResponsiveContainer>
        )}
      </div>
      <QuadLegend />
    </div>
  )
}

function QuadLegend() {
  return (
    <div className="mt-2 flex flex-wrap gap-3 text-[9px] text-slate-500">
      {Object.entries(QUAD).map(([k, v]) => (
        <span key={k} className="flex items-center gap-1">
          <span className="h-2 w-2 rounded-sm" style={{ background: v.fill, opacity: 0.6 }} />{v.label}
        </span>
      ))}
      <span className="ml-auto text-slate-600">tail = last 10 sessions · head labelled</span>
    </div>
  )
}

/* ── Rolling correlation + squeeze dots ───────────────────────────────────────── */
function CorrPanel({ data, loading }: { data: FactorSeriesResult | null; loading: boolean }) {
  const pts = data?.points ?? []
  const squeezeDays = pts.filter(p => p.squeeze_on).length
  const viptDays = pts.filter(p => p.vipt_breakout).length
  return (
    <div className="rounded-lg border border-slate-700/60 bg-slate-900/40 p-3">
      <PanelHead title={`ROLLING CORRELATION & SQUEEZE — ${data?.ticker ?? ''}`}
        sub={data ? `${data.corr_window}d corr vs ${data.benchmark} · ${squeezeDays} squeeze · ${viptDays} VIPT` : 'price · corr · squeeze dots'} />
      {data?.ticker && <ChartActions ticker={data.ticker} from="Glass-Box" style={{ marginBottom: 8 }} />}
      <div className="h-[300px]">
        {!data || !pts.length ? <Empty loading={loading} hint="Render to plot price, market correlation and squeeze alerts." /> : (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={pts} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="2 4" stroke="#1a2130" />
              <XAxis dataKey="date" tick={{ fontSize: 9, fill: T.muted }} stroke="#2a3448" minTickGap={28} />
              <YAxis yAxisId="px" tick={{ fontSize: 9, fill: T.muted }} stroke="#2a3448" domain={['auto', 'auto']} width={48} />
              <Tooltip contentStyle={{ background: '#0a0e17', border: '1px solid #1a2130', fontSize: 11, fontFamily: 'monospace' }} />
              <Line yAxisId="px" type="monotone" dataKey="close" name="close" stroke="#e2e8f0" dot={false} strokeWidth={1.4} isAnimationActive={false} />
              {/* squeeze alert dots ride the price line as amber markers */}
              <Line yAxisId="px" type="monotone" dataKey="close" name="squeeze" stroke="transparent" isAnimationActive={false} legendType="none"
                dot={(p: any) => p.payload?.squeeze_on
                  ? <circle key={p.key ?? `${p.cx}-${p.cy}`} cx={p.cx} cy={p.cy} r={3} fill="#ffb000" stroke="#0a0e17" strokeWidth={0.5} />
                  : <g key={p.key ?? `${p.cx}-${p.cy}`} />} />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
      {/* linked correlation sub-plot (-1..+1) */}
      <div className="h-[150px] mt-1">
        {data && pts.length > 0 && (
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={pts} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="2 4" stroke="#1a2130" />
              <XAxis dataKey="date" tick={{ fontSize: 9, fill: T.muted }} stroke="#2a3448" minTickGap={28} />
              <YAxis domain={[-1, 1]} ticks={[-1, -0.5, 0, 0.5, 1]} tick={{ fontSize: 9, fill: T.muted }} stroke="#2a3448" width={48} />
              <ReferenceLine y={0.2} stroke="#ef4444" strokeDasharray="4 4"
                label={{ value: 'de-couple <0.2', fontSize: 9, fill: '#ef4444', position: 'insideTopRight' }} />
              <ReferenceLine y={0} stroke="#475569" />
              <Tooltip contentStyle={{ background: '#0a0e17', border: '1px solid #1a2130', fontSize: 11, fontFamily: 'monospace' }} />
              <Line type="monotone" dataKey="corr30" name="corr30" stroke="#22d3ee" dot={false} strokeWidth={1.5} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}

/* ── Volume profile ───────────────────────────────────────────────────────────── */
function VolumePanel({ data, loading }: { data: VolumeProfileResult | null; loading: boolean }) {
  const bins = data?.bins ?? []
  // recharts horizontal bars: category axis = price band, value = volume.
  const rows = useMemo(() => [...bins].sort((a, b) => a.price_mid - b.price_mid)
    .map(b => ({ ...b, band: b.price_mid.toFixed(0) })), [bins])
  return (
    <div className="rounded-lg border border-slate-700/60 bg-slate-900/40 p-3">
      <PanelHead title={`VOLUME PROFILE — ${data?.ticker ?? ''}`}
        sub={data ? `${data.n_bars} bars · POC ₹${data.poc_price} · anchored VWAP ₹${data.ohlc.at(-1)?.avwap?.toFixed(2) ?? '—'}` : 'HVN/LVN · POC · anchored VWAP'} />
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <div className="lg:col-span-1 h-[420px]">
          {!data || !rows.length ? <Empty loading={loading} hint="Volume-by-price." /> : (
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={rows} layout="vertical" margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="2 4" stroke="#1a2130" horizontal={false} />
                <XAxis type="number" tickFormatter={fmtVolume} tick={{ fontSize: 9, fill: T.muted }} stroke="#2a3448" />
                <YAxis type="category" dataKey="band" tick={{ fontSize: 9, fill: T.muted }} stroke="#2a3448" width={42} interval={1} />
                <Tooltip contentStyle={{ background: '#0a0e17', border: '1px solid #1a2130', fontSize: 11, fontFamily: 'monospace' }}
                  formatter={(v: any, _n: any, p: any) => [`${Number(v).toLocaleString('en-IN')} (${p.payload.pct}%)`, p.payload.node + (p.payload.poc ? ' · POC' : '')]} />
                <Bar dataKey="volume" name="volume">
                  {rows.map((r, i) => (
                    <Cell key={i} fill={r.poc ? '#ffb000' : r.node === 'HVN' ? '#38bdf8' : '#2a3448'}
                      fillOpacity={r.poc ? 0.95 : r.node === 'HVN' ? 0.7 : 0.45} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
        {/* price + anchored VWAP context */}
        <div className="lg:col-span-2 h-[420px]">
          {data && data.ohlc.length > 0 && (
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={data.ohlc} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="2 4" stroke="#1a2130" />
                <XAxis dataKey="date" tick={{ fontSize: 9, fill: T.muted }} stroke="#2a3448" minTickGap={30} />
                <YAxis domain={['auto', 'auto']} tick={{ fontSize: 9, fill: T.muted }} stroke="#2a3448" width={48} />
                <Tooltip contentStyle={{ background: '#0a0e17', border: '1px solid #1a2130', fontSize: 11, fontFamily: 'monospace' }} />
                <ReferenceLine y={data.poc_price} stroke="#ffb000" strokeDasharray="4 4"
                  label={{ value: `POC ${data.poc_price}`, fontSize: 9, fill: '#ffb000', position: 'insideTopLeft' }} />
                <Line type="monotone" dataKey="close" name="close" stroke="#e2e8f0" dot={false} strokeWidth={1.3} isAnimationActive={false} />
                <Line type="monotone" dataKey="avwap" name="anchored VWAP" stroke="#a78bfa" dot={false} strokeWidth={1.5} strokeDasharray="4 3" isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>
    </div>
  )
}

/* ── shared bits ──────────────────────────────────────────────────────────────── */
function PanelHead({ title, sub }: { title: string; sub: string }) {
  return (
    <div className="flex items-baseline justify-between mb-2">
      <span className="text-[11px] font-bold tracking-wide text-slate-300">{title}</span>
      <span className="text-[9px] text-slate-600">{sub}</span>
    </div>
  )
}
function Empty({ loading, hint }: { loading: boolean; hint: string }) {
  return <div className="h-full flex items-center justify-center text-[11px] text-slate-600">{loading ? 'Rendering…' : hint}</div>
}
