'use client'

/**
 * Market valuation from NSE itself: P/E, P/B and dividend yield of the main and sector indices, with 1M / 1Y moves,
 * where today's P/E sits in its own history, and a weekly history chart of the selected index (P/E · P/B · yield).
 */
import { useEffect, useState } from 'react'
import { fmtSigned, unicodeMinus } from '@/lib/format'   // signed numbers with U+2212 (C1-trader-ux-18)
import { getIndexValuation, getIndexValuationHistory, getYieldGap, type IndexValuationHistory, type IndexValuationRow, type YieldGap } from '@/lib/api'
import { Chip, DataTable, Panel, T, fmtPct, type Column, ordinal, undatedSource } from '@/components/terminal'
import { nseDelayedSource } from '@/components/liveModel'
import { nseSession } from '@/components/desktop/session'
import { useMarketOpen } from '@/components/shell/useFeed'

type Row = IndexValuationRow & { name: string }

const fmtMonth = (d: string) => new Date(`${d}T00:00:00`).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })

export function IndexValuation() {
  const [rows, setRows] = useState<Row[] | null>(null)
  const [days, setDays] = useState(0)
  const [hist, setHist] = useState<Record<string, { pctl: number; median: number; p25: number; p75: number; low: number; high: number; p05: number; p95: number; since: string; days: number }>>({})
  const [pick, setPick] = useState('NIFTY 50')
  const [rel, setRel] = useState<Record<string, { ratio: number; pctl: number; median: number; p25: number; p75: number }>>({})
  const [stamp, setStamp] = useState<string | null>(null)
  // live program (reports/live_nse): today's P/E, P/B, yield and move come from NSE allIndices (15 s server cache), so the
  // panel re-reads them every 60 s in session (it used to load once) and its chip carries NSE's own stamp and age
  const marketOpen = useMarketOpen()
  useEffect(() => {
    let alive = true
    const get = (first: boolean) => getIndexValuation().then(r => {
      if (!alive) return
      setRows(Object.entries(r.data.indices).map(([name, v]) => ({ name, ...v }))); setDays(r.data.history_days)
      setHist(r.data.vs_history ?? {}); setRel(r.data.rel_history ?? {}); setStamp(r.data.timestamp ?? null)
    }).catch(() => { if (alive && first) setRows([]) })
    get(true)
    const iv = setInterval(() => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
      if (nseSession(Date.now()).state === 'CLOSED') return
      void get(false)
    }, 60_000)
    return () => { alive = false; clearInterval(iv) }
  }, [])
  if (!rows || rows.length === 0) return null
  const n50 = rows.find(r => r.name === 'NIFTY 50')
  const cols: Column<Row>[] = [
    { key: 'name', label: 'Index', render: r => <span style={{ color: r.name === 'NIFTY 50' ? T.amber : T.text }}>{r.name.replace('NIFTY ', '')}</span> },
    { key: 'pe', label: 'P/E', align: 'right', sort: r => r.pe ?? 1e9, render: r => r.pe == null ? '—' :
        <span style={{ color: n50?.pe && r.pe > n50.pe * 1.25 ? T.red : n50?.pe && r.pe < n50.pe * 0.8 ? T.green : T.text }}>{r.pe.toFixed(1)}×</span> },
    { key: 'hist', label: 'P/E vs history', align: 'right', sort: r => hist[r.name]?.pctl ?? 1e9,
      title: "percentile of today's P/E among every trading day on the same earnings basis (consolidated, since 31 Mar 2021; NSE daily index files), and the median",
      render: r => { const h = hist[r.name]; if (!h) return <span style={{ color: T.dim }}>—</span>
        return <span title={`since ${h.since} · middle half ${h.p25}–${h.p75}× · 90% of days ${h.p05}–${h.p95}×`}>
          <span style={{ color: h.pctl <= 20 ? T.green : h.pctl >= 80 ? T.red : T.muted }}>{ordinal(h.pctl)}</span>
          <span style={{ color: T.dim, fontSize: 10 }}> · med {h.median.toFixed(1)}×</span></span> } },
    { key: 'rel', label: 'vs NIFTY P/E', align: 'right', sort: r => rel[r.name]?.pctl ?? -1,
      title: "P/E ÷ NIFTY 50's P/E, and that ratio's percentile since Mar 2021 (the mid / small-cap premium, or a sector's discount)",
      render: r => { const v = rel[r.name]; if (!v) return <span style={{ color: T.dim }}>—</span>
        return <span title={`median ${v.median}× · middle half ${v.p25}–${v.p75}×`}>{v.ratio.toFixed(2)}×
          <span style={{ color: v.pctl >= 80 ? T.red : v.pctl <= 20 ? T.green : T.dim, fontSize: 10 }}> {ordinal(v.pctl)}</span></span> } },
    { key: 'pb', label: 'P/B', align: 'right', sort: r => r.pb ?? 1e9, render: r => r.pb == null ? '—' : `${r.pb.toFixed(2)}×` },
    { key: 'dy', label: 'Div yield', align: 'right', sort: r => r.dy ?? -1, render: r => r.dy == null ? '—' : <span style={{ color: T.muted }}>{r.dy.toFixed(2)}%</span> },
    { key: 'ey', label: 'Earnings yield', align: 'right', sort: r => (r.pe ? 100 / r.pe : -1), render: r => r.pe ? <span style={{ color: T.muted }}>{(100 / r.pe).toFixed(1)}%</span> : '—' },
    { key: 'd', label: 'Today', align: 'right', sort: r => r.change_pct ?? -999, render: r => <span style={{ color: (r.change_pct ?? 0) >= 0 ? T.green : T.red }}>{fmtPct(r.change_pct, 2)}</span> },
    { key: 'm', label: '1M', align: 'right', sort: r => r.chg_30d ?? -999, render: r => <span style={{ color: (r.chg_30d ?? 0) >= 0 ? T.green : T.red }}>{fmtPct(r.chg_30d, 1)}</span> },
    { key: 'y', label: '1Y', align: 'right', sort: r => r.chg_365d ?? -999, render: r => <span style={{ color: (r.chg_365d ?? 0) >= 0 ? T.green : T.red }}>{fmtPct(r.chg_365d, 1)}</span> },
  ]
  return (
    <Panel source={stamp ? nseDelayedSource(stamp, { marketOpen, now: Date.now(), hint: "today's P/E, P/B, yield and move from NSE allIndices (stamped to the minute, 1–3 min behind); history from NSE's daily index files" })
        : undatedSource('NSE index file', 'P/E, P/B, dividend yield as NSE publishes them each evening')} badge="context" title="Valuation · NSE" accent={T.amber} pad={0} style={{ marginBottom: 12 }}
      subtitle={`P/E, P/B and dividend yield as NSE publishes them for each index · P/E colour: well below / above NIFTY 50's · click an index to chart its history (NSE daily index files${days ? `, + ${days} live day${days === 1 ? '' : 's'}` : ''})`}>
      <ValuationHistoryChart index={pick} todayPe={rows.find(r => r.name === pick)?.pe ?? null} />
      <DataTable columns={cols} rows={rows} rowKey={r => r.name} dense onRowClick={r => setPick(r.name)}
        rowStyle={r => (r.name === pick ? { background: 'rgba(245,158,11,0.07)' } : undefined)} />
    </Panel>
  )
}

const METRICS = { pe: { label: 'P/E', unit: '×' }, pb: { label: 'P/B', unit: '×' }, dy: { label: 'Div yield', unit: '%' }, rel: { label: 'P/E vs NIFTY', unit: '×' } } as const
type Metric = keyof typeof METRICS

/** Weekly history of one index's valuation since NSE's files start; median and middle half drawn for the same-basis
 *  period only (NSE moved to consolidated earnings in Apr 2021; earlier readings run higher and are not compared). */
function ValuationHistoryChart({ index, todayPe }: { index: string; todayPe: number | null }) {
  const [metric, setMetric] = useState<Metric>('pe')
  useEffect(() => { if (index === 'NIFTY 50' && metric === 'rel') setMetric('pe') }, [index, metric])   // NIFTY vs itself = 1
  const [d, setD] = useState<IndexValuationHistory | null>(null)
  const [hover, setHover] = useState<number | null>(null)
  useEffect(() => {
    let live = true
    getIndexValuationHistory(index, metric).then(r => { if (live) setD(r.data) }).catch(() => { if (live) setD(null) })
    return () => { live = false }
  }, [index, metric])
  const pts = d?.points ?? []
  if (pts.length < 50) return null
  const s = d!.stats, u = METRICS[metric].unit, W = 1200, H = 120, pad = 4
  const vals = pts.map(p => p.v)
  // loss years send P/E to the thousands (NIFTY REALTY hit 23,308×): scale the axis to the 2nd–98th percentile
  const sorted = [...vals].sort((a, b) => a - b), q = (f: number) => sorted[Math.min(sorted.length - 1, Math.floor(f * sorted.length))]
  const wild = sorted[sorted.length - 1] > 2 * q(0.98) || sorted[0] < q(0.02) / 2       // only clip real blow-ups
  const lo = wild ? Math.min(q(0.02), s?.p05 ?? Infinity) : sorted[0]
  const hi = wild ? Math.max(q(0.98), s?.p95 ?? -Infinity, metric === 'pe' && todayPe ? todayPe : -Infinity) : sorted[sorted.length - 1]
  const clipped = vals.some(v => v > hi || v < lo)
  const x = (i: number) => pad + (i / (vals.length - 1)) * (W - 2 * pad)
  const y = (v: number) => H - pad - ((Math.min(hi, Math.max(lo, v)) - lo) / (hi - lo || 1)) * (H - 2 * pad)
  const breakAt = d!.basis_from ? pts.findIndex(p => p.date >= d!.basis_from!) : -1
  const x0 = breakAt > 0 ? x(breakAt) : 0
  const now = metric === 'pe' && todayPe ? todayPe : s?.now ?? vals[vals.length - 1]
  // for yield, high = cheap; for P/E and P/B, low = cheap
  const tone = (p: number) => ((metric === 'dy' ? 100 - p : p) <= 20 ? T.green : (metric === 'dy' ? 100 - p : p) >= 80 ? T.red : T.text)
  const hv = hover != null ? pts[hover] : null
  return <div style={{ padding: '8px 10px', borderBottom: `1px solid ${T.border}` }}>
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 4 }}>
      <span style={{ fontSize: 11, fontFamily: T.mono, color: T.muted }}>
        <span style={{ color: T.amber }}>{index}</span> {METRICS[metric].label} since {pts[0].date.slice(0, 4)} · now{' '}
        <span style={{ color: T.amber }}>{now.toFixed(metric === 'pe' ? 1 : 2)}{u}</span>
        {s && <>, <span style={{ color: tone(s.pctl) }}>{ordinal(s.pctl)} percentile</span>
          <span style={{ color: T.dim }}> of days since {fmtMonth(s.since)} · median {s.median}{u} · middle half {s.p25}–{s.p75}{u} (shaded) · 90% of days {s.p05}–{s.p95}{u}</span></>}
      </span>
      <span style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
        {(Object.keys(METRICS) as Metric[]).filter(m => m !== 'rel' || index !== 'NIFTY 50').map(m =>
          <Chip key={m} color={T.amber} active={metric === m} onClick={() => setMetric(m)}>{METRICS[m].label}</Chip>)}
      </span>
    </div>
    <div style={{ position: 'relative' }}>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: H, display: 'block' }}
        onMouseLeave={() => setHover(null)}
        onMouseMove={e => { const r = e.currentTarget.getBoundingClientRect()
          setHover(Math.max(0, Math.min(pts.length - 1, Math.round(((e.clientX - r.left) / r.width * W - pad) / (W - 2 * pad) * (pts.length - 1))))) }}>
        {s && <>
          <rect x={x0} width={W - x0} y={y(s.p75)} height={Math.max(1, y(s.p25) - y(s.p75))} fill="rgba(56,189,248,0.08)" />
          <line x1={x0} x2={W} y1={y(s.median)} y2={y(s.median)} stroke={T.dim} strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />
        </>}
        {breakAt > 0 && <line x1={x0} x2={x0} y1={0} y2={H} stroke={T.muted} strokeDasharray="2 3" vectorEffect="non-scaling-stroke" />}
        <path d={vals.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join('')} fill="none" stroke={T.amber} strokeWidth={1.4} vectorEffect="non-scaling-stroke" />
        {hover != null && <line x1={x(hover)} x2={x(hover)} y1={0} y2={H} stroke={T.muted} vectorEffect="non-scaling-stroke" />}
      </svg>
      {hv && <div style={{ position: 'absolute', top: 2, left: `${Math.min(85, (hover! / (pts.length - 1)) * 100)}%`, fontSize: 10.5, fontFamily: T.mono,
        background: T.panel, border: `1px solid ${T.border}`, padding: '2px 6px', pointerEvents: 'none', whiteSpace: 'nowrap' }}>
        {hv.date} · <span style={{ color: T.amber }}>{hv.v.toFixed(2)}{u}</span></div>}
    </div>
    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 9.5, color: T.dim }}><span>{pts[0].date.slice(0, 7)}</span>
      <span style={{ textAlign: 'center' }}>weekly · as NSE publishes it{breakAt > 0 ? ` · dotted line: NSE moved P/E and yield to consolidated figures (${fmtMonth(pts[breakAt].date)}); earlier readings are on a different basis and not compared` : ''} · {clipped ? 'axis clipped at the 2nd–98th percentile (loss years) · ' : ''}describes the past, not a forecast</span>
      <span>{pts[pts.length - 1].date.slice(0, 7)}</span></div>
  </div>
}

/** Equity vs bonds: NIFTY 50 earnings yield minus India's 10-year yield, monthly since 2012 (Fed-model view). */
export function YieldGapPanel() {
  const [d, setD] = useState<YieldGap | null>(null)
  const [hover, setHover] = useState<number | null>(null)
  useEffect(() => { getYieldGap().then(r => setD(r.data)).catch(() => setD(null)) }, [])
  const pts = d?.points ?? []
  if (pts.length < 24) return null
  const s = d!.stats, W = 1200, H = 120, pad = 6
  const vals = pts.flatMap(p => [p.gap]), lo = Math.min(...vals), hi = Math.max(...vals)
  const x = (i: number) => pad + (i / (pts.length - 1)) * (W - 2 * pad)
  const y = (v: number) => H - pad - ((v - lo) / (hi - lo || 1)) * (H - 2 * pad)
  const breakAt = pts.findIndex(p => p.month >= d!.basis_from)
  const last = pts[pts.length - 1], hv = hover != null ? pts[hover] : null
  return (
    <Panel source={undatedSource('NSE + FRED (monthly)', d?.bond_through ? `bond yield through ${d.bond_through}` : null)} badge="context" title="Equity vs bonds · NIFTY earnings yield − India 10-year yield" accent={T.cyan} pad={10} style={{ marginBottom: 12 }}
      subtitle={`monthly since ${pts[0].month} · higher = equities cheaper relative to bonds · bond yield: OECD monthly average via FRED, published with a lag (latest ${d!.bond_through ?? last.month})`}>
      <div style={{ fontSize: 11.5, fontFamily: T.mono, color: T.muted, marginBottom: 4 }}>
        {last.month}: earnings yield <span style={{ color: T.text }}>{last.ey.toFixed(2)}%</span> − 10Y <span style={{ color: T.text }}>{last.y10.toFixed(2)}%</span> ={' '}
        <span style={{ color: T.amber }}>{fmtSigned(last.gap, 2)} pts</span>
        {s && <>, <span style={{ color: s.pctl >= 80 ? T.green : s.pctl <= 20 ? T.red : T.text }}>{ordinal(s.pctl)} percentile</span>
          <span style={{ color: T.dim }}> of months since {fmtMonth(`${d!.basis_from}-01`)} · {unicodeMinus(`median ${s.median} · middle half ${s.p25} to ${s.p75}`)}</span></>}
      </div>
      <div style={{ position: 'relative' }}>
        <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ width: '100%', height: H, display: 'block' }}
          onMouseLeave={() => setHover(null)}
          onMouseMove={e => { const r = e.currentTarget.getBoundingClientRect()
            setHover(Math.max(0, Math.min(pts.length - 1, Math.round(((e.clientX - r.left) / r.width * W - pad) / (W - 2 * pad) * (pts.length - 1))))) }}>
          {s && breakAt > 0 && <>
            <rect x={x(breakAt)} width={W - x(breakAt)} y={y(s.p75)} height={Math.max(1, y(s.p25) - y(s.p75))} fill="rgba(56,189,248,0.08)" />
            <line x1={x(breakAt)} x2={W} y1={y(s.median)} y2={y(s.median)} stroke={T.dim} strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />
            <line x1={x(breakAt)} x2={x(breakAt)} y1={0} y2={H} stroke={T.muted} strokeDasharray="2 3" vectorEffect="non-scaling-stroke" />
          </>}
          <path d={pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(p.gap).toFixed(1)}`).join('')} fill="none" stroke={T.cyan} strokeWidth={1.5} vectorEffect="non-scaling-stroke" />
          {hover != null && <line x1={x(hover)} x2={x(hover)} y1={0} y2={H} stroke={T.muted} vectorEffect="non-scaling-stroke" />}
        </svg>
        {hv && <div style={{ position: 'absolute', top: 2, left: `${Math.min(80, (hover! / (pts.length - 1)) * 100)}%`, fontSize: 10.5, fontFamily: T.mono,
          background: T.panel, border: `1px solid ${T.border}`, padding: '2px 6px', pointerEvents: 'none', whiteSpace: 'nowrap' }}>
          {hv.month} · EY {hv.ey.toFixed(2)}% − 10Y {hv.y10.toFixed(2)}% = <span style={{ color: T.cyan }}>{hv.gap.toFixed(2)}</span></div>}
      </div>
      <div style={{ fontSize: 9.5, color: T.dim, marginTop: 3 }}>
        dotted line: NSE moved index P/E to consolidated earnings (Mar 2021), which raised the earnings yield, so only later months are compared ·
        context, not a timing signal: the gap can stay wide or narrow for years
      </div>
    </Panel>
  )
}
