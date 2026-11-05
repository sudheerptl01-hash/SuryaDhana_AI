'use client'

/**
 * COMP — compare stocks: performance rebased to 100 against NIFTY 50, with return, volatility, max drawdown,
 * beta / correlation to NIFTY and a correlation matrix. Daily closes from Yahoo (split-adjusted) via
 * /api/news-scanner/chart. Open from the command bar: `COMP TCS INFY HCLTECH`.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getNewsChart, getStockActions } from '@/lib/api'
import { useFinancialsLatest } from '@/lib/useFinancials'
import { useExternalPrefChange } from '@/lib/prefs/useExternalChange'
import { CHART_BOX, Chip, DataTable, Input, PageHeader, Panel, T, TickerLink, type Column, fmtFixed, fmtPct, ordinal, useChartSize } from '@/components/terminal'
import { compareAdd, compareBase, compareRemove, sameList } from '@/components/compareSet'
import { useRequestSeq } from '@/components/useRequestSeq'

export { COMP_KEY } from '@/lib/pageKeys'
import { COMP_KEY } from '@/lib/pageKeys'
const BENCH = '^NSEI'
const COLORS = [T.amber, T.cyan, T.violet, T.green, '#ff8a3d', '#ff5fa2', '#9be15d', '#5fd3ff']
const PERIODS: [string, string][] = [['1mo', '1M'], ['3mo', '3M'], ['6mo', '6M'], ['1y', '1Y'], ['2y', '2Y']]

type Series = { sym: string; dates: string[]; close: number[] }

function readRaw(): string | null {
  try { return localStorage.getItem(COMP_KEY) } catch { return null }
}

function load(): { syms: string[]; period: string } {
  try {
    const s = JSON.parse(localStorage.getItem(COMP_KEY) || '{}')
    if (Array.isArray(s.syms) && s.syms.length) return { syms: s.syms.slice(0, 8), period: s.period || '1y' }
  } catch { /* defaults */ }
  return { syms: ['TCS', 'INFY', 'HCLTECH'], period: '1y' }
}

const yahoo = (s: string) => (s.startsWith('^') || s.includes('.') ? s : `${s}.NS`)
const day = (t: number) => new Date(t * 1000).toISOString().slice(0, 10)

function stats(c: number[], bench?: number[]) {
  const r = c.slice(1).map((v, i) => v / c[i] - 1)
  const mean = r.reduce((a, b) => a + b, 0) / (r.length || 1)
  const sd = Math.sqrt(r.reduce((a, b) => a + (b - mean) ** 2, 0) / Math.max(r.length - 1, 1))
  let peak = c[0], dd = 0
  for (const v of c) { peak = Math.max(peak, v); dd = Math.min(dd, v / peak - 1) }
  let beta = null as number | null, corr = null as number | null
  if (bench && bench.length === c.length) {
    const b = bench.slice(1).map((v, i) => v / bench[i] - 1)
    const mb = b.reduce((a, x) => a + x, 0) / b.length
    const cov = r.reduce((a, x, i) => a + (x - mean) * (b[i] - mb), 0) / Math.max(r.length - 1, 1)
    const vb = b.reduce((a, x) => a + (x - mb) ** 2, 0) / Math.max(b.length - 1, 1)
    const sdb = Math.sqrt(vb)
    beta = vb ? cov / vb : null
    corr = sd && sdb ? cov / (sd * sdb) : null
  }
  return { ret: (c[c.length - 1] / c[0] - 1) * 100, vol: sd * Math.sqrt(252) * 100, dd: dd * 100, beta, corr,
           best: Math.max(...r) * 100, worst: Math.min(...r) * 100 }
}

function corrOf(a: number[], b: number[]): number {
  const ra = a.slice(1).map((v, i) => v / a[i] - 1), rb = b.slice(1).map((v, i) => v / b[i] - 1)
  const ma = ra.reduce((x, y) => x + y, 0) / ra.length, mb = rb.reduce((x, y) => x + y, 0) / rb.length
  let cov = 0, va = 0, vb = 0
  ra.forEach((x, i) => { cov += (x - ma) * (rb[i] - mb); va += (x - ma) ** 2; vb += (rb[i] - mb) ** 2 })
  return va && vb ? cov / Math.sqrt(va * vb) : NaN
}

export function Compare() {
  const [syms, setSyms] = useState<string[]>([])
  const [period, setPeriod] = useState('1y')
  const [data, setData] = useState<Record<string, Series | 'error'>>({})
  const [add, setAdd] = useState('')
  const [hover, setHover] = useState<number | null>(null)

  // Multi-window (C3-02): the compare set is a synced key edited step by step (add / ✕), so a second window must
  // never write its stale copy over another window's edit. `stored` is the string this window last read or wrote;
  // an equal state is never written again (no echo over a newer write from another window).
  const stored = useRef<string | null>(null)
  useEffect(() => {
    // mount and same-window hand-off (GO bar `COMP …`, FUND, WTCH write the key and fire 'suryadhana:comp')
    const read = () => { const s = load(); stored.current = readRaw(); setSyms(s.syms); setPeriod(s.period) }
    read()
    window.addEventListener('suryadhana:comp', read)
    return () => window.removeEventListener('suryadhana:comp', read)
  }, [])
  // another window of this origin, or the prefs sync applying a newer server value, changed the set: adopt it
  useExternalPrefChange(COMP_KEY, () => {
    const s = load()
    stored.current = readRaw() ?? JSON.stringify({ syms: s.syms, period: s.period })
    setSyms(prev => (sameList(prev, s.syms) ? prev : s.syms))
    setPeriod(s.period)
  })
  useEffect(() => {
    if (!syms.length) return
    const v = JSON.stringify({ syms, period })
    if (v === stored.current) return          // already stored (read or adopted): never echo it back
    try { localStorage.setItem(COMP_KEY, v); stored.current = v } catch { /* private window */ }
  }, [syms, period])
  // merge on write: an edit applies to the latest saved set when ANOTHER window changed it a moment ago (the stored
  // string is not the one this window last read or wrote); otherwise to what this window shows. RUP-03: an emptied
  // set is never written, so storage still holds the removed last symbol: it must not come back on the next add.
  const latestSyms = () => compareBase(syms, readRaw(), stored.current)
  const editSyms = (next: string[]) => setSyms(prev => (sameList(prev, next) ? prev : next))

  // CT-01: latest request wins. A slower answer for the previous set or period never replaces the newer one
  const seq = useRequestSeq()                         // in a ref, never useMemo (P1); cancelled on unmount
  const fetchAll = useCallback(async () => {
    const mine = seq.begin()
    const want = [BENCH, ...syms]
    const got = await Promise.all(want.map(async s => {
      try {
        const r = (await getNewsChart(yahoo(s), period)).data
        const candles = (r.candles ?? []) as { time: number; close: number }[]
        return [s, { sym: s, dates: candles.map(c => day(c.time)), close: candles.map(c => c.close) }] as const
      } catch { return [s, 'error' as const] as const }
    }))
    if (seq.isCurrent(mine)) setData(Object.fromEntries(got))
  }, [syms, period, seq])
  useEffect(() => { if (syms.length) fetchAll() }, [fetchAll, syms.length])

  // align on dates every series has
  const aligned = useMemo(() => {
    const ok = [BENCH, ...syms].filter(s => data[s] && data[s] !== 'error') as string[]
    if (!ok.length) return null
    const common = (data[ok[0]] as Series).dates.filter(d => ok.every(s => (data[s] as Series).dates.includes(d)))
    const byDate = (s: string) => { const x = data[s] as Series; const m = new Map(x.dates.map((d, i) => [d, x.close[i]])); return common.map(d => m.get(d)!) }
    return { dates: common, series: Object.fromEntries(ok.map(s => [s, byDate(s)])) as Record<string, number[]> }
  }, [data, syms])

  const submit = () => {
    const s = add.trim().toUpperCase().replace(/\.NS$/, '')
    if (s) editSyms(compareAdd(latestSyms(), s))
    setAdd('')
  }

  // drawn in CSS px (C1-17): axis and end labels stay 10–10.5 px at any window width
  const { ref: chartRef, w: W, h: H } = useChartSize(1200, 380, { minRatio: 0.75, maxRatio: 1.1 })
  const PAD_L = 48, PAD_R = 118, PAD_T = 14, PAD_B = 26
  const chart = useMemo(() => {
    if (!aligned || aligned.dates.length < 2) return null
    const norm = Object.fromEntries(Object.entries(aligned.series).map(([s, c]) => [s, c.map(v => (v / c[0]) * 100)]))
    const all = Object.values(norm).flat()
    const lo = Math.min(...all), hi = Math.max(...all)
    const n = aligned.dates.length
    const x = (i: number) => PAD_L + (i / (n - 1)) * (W - PAD_L - PAD_R)
    const y = (v: number) => PAD_T + (1 - (v - lo) / (hi - lo || 1)) * (H - PAD_T - PAD_B)
    return { norm, lo, hi, n, x, y }
  }, [aligned, W, H])

  const order = [BENCH, ...syms]
  const color = (s: string) => (s === BENCH ? T.muted : COLORS[syms.indexOf(s) % COLORS.length])
  const rows = aligned ? order.filter(s => aligned.series[s]).map(s => ({ sym: s, ...stats(aligned.series[s], s === BENCH ? undefined : aligned.series[BENCH]) })) : []
  const cols: Column<(typeof rows)[number]>[] = [
    { key: 'sym', label: 'Stock', render: r => <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
      <span style={{ width: 10, height: 3, background: color(r.sym) }} />
      {r.sym === BENCH ? <span style={{ color: T.muted }}>NIFTY 50</span> : <TickerLink symbol={r.sym} />}
    </span> },
    { key: 'ret', label: 'Return', align: 'right', sort: r => r.ret, render: r => <span style={{ color: r.ret >= 0 ? T.green : T.red, fontWeight: 600 }}>{fmtPct(r.ret, 1)}</span> },
    { key: 'vol', label: 'Volatility (yr)', align: 'right', sort: r => r.vol, render: r => `${r.vol.toFixed(1)}%` },
    { key: 'dd', label: 'Max drawdown', align: 'right', sort: r => r.dd, render: r => <span style={{ color: T.red }}>{fmtPct(r.dd, 1, false)}</span> },
    { key: 'beta', label: 'Beta', align: 'right', sort: r => r.beta ?? 0, render: r => r.beta == null ? '—' : fmtFixed(r.beta, 2) },
    { key: 'corr', label: 'Corr. NIFTY', align: 'right', render: r => r.corr == null ? '—' : fmtFixed(r.corr, 2) },
    { key: 'best', label: 'Best / worst day', align: 'right', render: r => <span><span style={{ color: T.green }}>{fmtPct(r.best, 1)}</span> / <span style={{ color: T.red }}>{fmtPct(r.worst, 1)}</span></span> },
  ]

  const { fin, pending } = useFinancialsLatest(syms)
  // trailing-12-month dividend yield per compared stock (NSE corporate actions, at most 8 calls)
  const [divy, setDivy] = useState<Record<string, number | null>>({})
  useEffect(() => {
    let live = true
    Promise.all(syms.map(sym => getStockActions(sym, 2).then(r => [sym, r.data.ttm_yield_pct] as const).catch(() => [sym, null] as const)))
      .then(pairs => { if (live) setDivy(Object.fromEntries(pairs)) })
    return () => { live = false }
  }, [syms.join(',')])   // eslint-disable-line react-hooks/exhaustive-deps
  const crs = (v: number | null | undefined) => v == null ? '—' : Math.round(v / 1e7).toLocaleString('en-IN')
  const gr = (v: number | null | undefined, turn?: string | null) => turn ? <span style={{ color: turn === 'to profit' ? T.green : T.red }}>{turn}</span>
    : v == null ? <span style={{ color: T.dim }}>—</span> : <span style={{ color: v >= 0 ? T.green : T.red }}>{fmtPct(v, 1)}</span>
  const fcols: Column<{ sym: string }>[] = [
    { key: 'sym', label: 'Stock', render: r => <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}><span style={{ width: 10, height: 3, background: color(r.sym) }} /><TickerLink symbol={r.sym} /></span> },
    { key: 'mcap', label: 'Mcap ₹ cr', align: 'right', sort: r => fin[r.sym]?.mcap ?? -1, render: r => fin[r.sym] ? crs(fin[r.sym].mcap) : <span style={{ color: T.dim }}>…</span> },
    { key: 'pe', label: 'P/E (TTM)', align: 'right', sort: r => fin[r.sym]?.pe ?? 1e9, render: r => fin[r.sym]?.pe != null ? `${fin[r.sym].pe!.toFixed(1)}×` : <span style={{ color: T.dim }}>—</span> },
    { key: 'pctl', label: 'P/E vs own past', align: 'right', sort: r => fin[r.sym]?.pe_pctl ?? 1e9, title: "percentile of today's P/E within the stock's own point-in-time P/E history",
      render: r => fin[r.sym]?.pe_pctl == null ? <span style={{ color: T.dim }}>—</span>
        : <span style={{ color: fin[r.sym].pe_pctl! <= 20 ? T.green : fin[r.sym].pe_pctl! >= 80 ? T.red : T.muted }}>{ordinal(fin[r.sym].pe_pctl)} pct</span> },
    { key: 'pb', label: 'P/B', align: 'right', sort: r => fin[r.sym]?.pb ?? 1e9, render: r => fin[r.sym]?.pb != null ? `${fin[r.sym].pb!.toFixed(1)}×` : <span style={{ color: T.dim }}>—</span> },
    { key: 'rev', label: 'Revenue YoY', align: 'right', sort: r => fin[r.sym]?.revenue_yoy ?? -999, render: r => gr(fin[r.sym]?.revenue_yoy) },
    { key: 'pat', label: 'Profit YoY', align: 'right', sort: r => fin[r.sym]?.pat_yoy ?? -999, render: r => gr(fin[r.sym]?.pat_yoy, fin[r.sym]?.pat_yoy_turn) },
    { key: 'mg', label: 'Net margin', align: 'right', sort: r => fin[r.sym]?.pat_margin ?? -999, render: r => fin[r.sym]?.pat_margin != null ? `${fin[r.sym].pat_margin!.toFixed(1)}%` : '—' },
    { key: 'dy', label: 'Div yield', align: 'right', sort: r => divy[r.sym] ?? -1, title: 'dividends of the last 12 months ÷ last close (NSE corporate actions)',
      render: r => divy[r.sym] == null ? <span style={{ color: T.dim }}>—</span> : <span style={{ color: T.muted }}>{divy[r.sym]!.toFixed(2)}%</span> },
    { key: 'q', label: 'Latest quarter', align: 'right', render: r => <span style={{ color: T.muted }}>{fin[r.sym]?.period_end ?? '—'}</span> },
  ]

  return (
    <div>
      <PageHeader code="COMP" title="Compare"
        subtitle={aligned ? `${aligned.dates.length} sessions · ${aligned.dates[0]} → ${aligned.dates[aligned.dates.length - 1]} · rebased to 100 · vs NIFTY 50` : 'performance rebased to 100'}
        right={<div style={{ display: 'flex', gap: 4 }}>{PERIODS.map(([k, l]) => <Chip key={k} color={T.amber} active={period === k} onClick={() => setPeriod(k)}>{l}</Chip>)}</div>} />
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center', marginBottom: 10 }}>
        {syms.map(s => (
          <span key={s} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, border: `1px solid ${color(s)}66`, padding: '3px 8px', fontFamily: T.mono, fontSize: 11.5 }}>
            <span style={{ width: 10, height: 3, background: color(s) }} />
            <span style={{ color: data[s] === 'error' ? T.red : T.text }}>{s}{data[s] === 'error' ? ' (no data)' : ''}</span>
            <span role="button" onClick={() => editSyms(compareRemove(latestSyms(), s))} style={{ color: T.dim, cursor: 'pointer' }}>✕</span>
          </span>
        ))}
        <form onSubmit={e => { e.preventDefault(); submit() }} style={{ display: 'flex', gap: 6 }}>
          <Input value={add} onChange={setAdd} placeholder={syms.length >= 8 ? 'max 8' : 'Add ticker + Enter'} width={160} />
        </form>
      </div>
      <Panel title="Performance" accent={T.amber} pad={0}
        subtitle={hover != null && aligned && chart ? `${aligned.dates[hover]} · ` + order.filter(s => chart.norm[s]).map(s => `${s === BENCH ? 'NIFTY' : s} ${fmtPct(chart.norm[s][hover] - 100, 1)}`).join(' · ') : 'hover the chart for values'}>
        <div ref={chartRef} style={CHART_BOX}>
        {!chart ? <div style={{ padding: 30, fontSize: 12, color: T.muted }}>Loading prices…</div> : (
          <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }}
               onMouseMove={e => { const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect(); const fx = ((e.clientX - r.left) / r.width) * W
                 const i = Math.round(((fx - PAD_L) / (W - PAD_L - PAD_R)) * (chart.n - 1)); setHover(Math.max(0, Math.min(chart.n - 1, i))) }}
               onMouseLeave={() => setHover(null)}>
            {[chart.lo, 100, chart.hi].map(v => (
              <g key={v}>
                <line x1={PAD_L} x2={W - PAD_R} y1={chart.y(v)} y2={chart.y(v)} stroke={v === 100 ? T.borderHi : T.border} strokeDasharray={v === 100 ? '4 4' : '2 5'} />
                <text x={PAD_L - 6} y={chart.y(v) + 3} textAnchor="end" fontSize={10} fill={T.dim} fontFamily={T.mono}>{v.toFixed(0)}</text>
              </g>
            ))}
            {order.filter(s => chart.norm[s]).map(s => {
              const v = chart.norm[s]
              return (
                <g key={s}>
                  <path d={v.map((p, i) => `${i ? 'L' : 'M'}${chart.x(i).toFixed(1)},${chart.y(p).toFixed(1)}`).join('')} fill="none"
                        stroke={color(s)} strokeWidth={s === BENCH ? 1.4 : 2} strokeDasharray={s === BENCH ? '5 4' : undefined} />
                  <text x={W - PAD_R + 6} y={chart.y(v[v.length - 1]) + 3} fontSize={10.5} fill={color(s)} fontFamily={T.mono}>
                    {s === BENCH ? 'NIFTY' : s} {fmtPct(v[v.length - 1] - 100, 0)}
                  </text>
                </g>
              )
            })}
            {hover != null && <line x1={chart.x(hover)} x2={chart.x(hover)} y1={PAD_T} y2={H - PAD_B} stroke={T.borderHi} />}
            {aligned && [0, Math.floor(chart.n / 2), chart.n - 1].map(i => (
              <text key={i} x={chart.x(i)} y={H - 8} textAnchor={i === 0 ? 'start' : i === chart.n - 1 ? 'end' : 'middle'} fontSize={10} fill={T.dim} fontFamily={T.mono}>{aligned.dates[i]}</text>
            ))}
          </svg>
        )}
        </div>
      </Panel>
      <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'minmax(0, 2fr) minmax(0, 1fr)', marginTop: 12, alignItems: 'start' }}>
        <Panel title="Risk and return" pad={0} accent={T.cyan}>
          <DataTable columns={cols} rows={rows} rowKey={r => r.sym} dense />
        </Panel>
        <Panel title="Correlation of daily returns" pad={10} accent={T.violet}>
          {aligned && syms.filter(s => aligned.series[s]).length > 1 ? (
            <table style={{ borderCollapse: 'collapse', fontFamily: T.mono, fontSize: 11 }}>
              <thead><tr><th />{syms.filter(s => aligned.series[s]).map(s => <th key={s} style={{ padding: '3px 6px', color: color(s), fontWeight: 600 }}>{s.slice(0, 8)}</th>)}</tr></thead>
              <tbody>{syms.filter(s => aligned.series[s]).map(a => (
                <tr key={a}><td style={{ padding: '3px 6px', color: color(a) }}>{a.slice(0, 8)}</td>
                  {syms.filter(s => aligned.series[s]).map(b => {
                    const c = a === b ? 1 : corrOf(aligned.series[a], aligned.series[b])
                    return <td key={b} style={{ padding: '4px 6px', textAlign: 'center', color: T.bright,
                                                background: `rgba(181,139,255,${Math.max(0, c) * 0.55})` }}>{fmtFixed(c, 2)}</td>
                  })}
                </tr>
              ))}</tbody>
            </table>
          ) : <div style={{ fontSize: 11, color: T.dim }}>Add two or more stocks.</div>}
          <div style={{ fontSize: 10, color: T.dim, marginTop: 8 }}>High correlation = the names move together: holding them adds little diversification.</div>
        </Panel>
      </div>
      {syms.length > 0 && (
        <Panel title="Fundamentals" accent={T.green} pad={0} style={{ marginTop: 12 }}
          subtitle={`latest quarter vs a year ago · valuation at the last NSE close · from NSE results filings${pending ? ` · reading ${pending} more…` : ''}`}>
          <DataTable columns={fcols} rows={syms.map(sym => ({ sym }))} rowKey={r => r.sym} dense />
        </Panel>
      )}
    </div>
  )
}
