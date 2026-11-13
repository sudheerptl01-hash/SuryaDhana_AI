'use client'

import { apiError } from '@/lib/errors'
/**
 * MRGN — margin trading (MTF) crowding: how much stock retail traders hold on broker-funded margin. The market MTF
 * book over a year; per stock the funded amount, how fast it grew over the last N sessions, and days-to-unwind
 * (funded amount ÷ 20-day average traded value: how many sessions of normal volume a forced sell-off would need).
 * Fast leveraged build-ups unwind hard in sell-offs. NSE publishes the MTF report for day T on T+1.
 */
import { useEffect, useMemo, useState } from 'react'
import { getMtfMonitor, type MtfStock } from '@/lib/api'
import { CHART_BOX, Chip, DataTable, ErrorBox, Loading, PageHeader, Panel, Stat, T, TickerLink, fmtPct, type Column, useChartSize, sourceOf } from '@/components/terminal'
import { MTF_MIN_SESSIONS, mtfBuilding, mtfEligible, mtfRupeeChange, type MtfLike } from '@/components/marketPagesModel'

const cr = (v: number | null | undefined) => (v == null ? '—' : v >= 1000 ? `₹${(v / 1000).toFixed(2)}k cr` : `₹${v.toFixed(v >= 100 ? 0 : 1)} cr`)
const lakhCr = (lakh: number | null | undefined) => (lakh == null ? '—' : `₹${(lakh / 100).toLocaleString('en-IN', { maximumFractionDigits: 0 })} cr`)

export function MarginMonitor() {
  const [lookback, setLookback] = useState(20)
  const [data, setData] = useState<Awaited<ReturnType<typeof getMtfMonitor>>['data'] | null>(null)
  const [error, setError] = useState<string | null>(null)
  // M26: the % leaderboard needs ≥ 60 sessions of MTF history (the 60-session read shows who had a position then);
  // the ₹ ranking needs none
  const [mode, setMode] = useState<'pct' | 'rupees'>('pct')
  const [rows60, setRows60] = useState<MtfLike[] | null>(null)
  useEffect(() => {
    if (lookback === MTF_MIN_SESSIONS) { setRows60(null); return }
    let live = true
    getMtfMonitor(MTF_MIN_SESSIONS, 1).then(r => { if (live) setRows60(r.data.stocks) }).catch(() => { if (live) setRows60(null) })
    return () => { live = false }
  }, [lookback])
  const { ref: chartRef, w: W, h: H } = useChartSize(1000, 150, { maxRatio: 1.2 })   // CSS px (C1-17)
  useEffect(() => {
    setData(null)
    getMtfMonitor(lookback, 1).then(r => setData(r.data)).catch(e => setError(apiError(e, 'unavailable')))
  }, [lookback])

  const m = data?.market ?? []
  const last = m[m.length - 1], prior = m[Math.max(0, m.length - 1 - lookback)]
  const bookChg = last?.end_lakh && prior?.end_lakh ? (last.end_lakh / prior.end_lakh - 1) * 100 : null
  const eligible = useMemo(() => mtfEligible(data?.stocks ?? [], lookback === MTF_MIN_SESSIONS ? (data?.stocks ?? null) : rows60), [data, rows60, lookback])
  const lists = useMemo(() => {
    const st = (data?.stocks ?? []).filter(s => (s.amount_cr ?? 0) >= 5)
    return {
      largest: [...st].sort((a, b) => (b.amount_cr ?? 0) - (a.amount_cr ?? 0)).slice(0, 25),
      building: mtfBuilding(data?.stocks ?? [], mode, eligible) as MtfStock[],
      crowded: [...st].filter(s => s.days_to_unwind != null).sort((a, b) => b.days_to_unwind! - a.days_to_unwind!).slice(0, 25),
      excluded: mode === 'pct' && eligible ? st.filter(s => s.qty_chg_pct != null && !eligible.has(s.symbol)).length : 0,
    }
  }, [data, mode, eligible])

  const unwindCol: Column<MtfStock> = { key: 'd', label: 'Days to unwind', align: 'right', sort: r => r.days_to_unwind ?? -1,
    render: r => <span style={{ color: (r.days_to_unwind ?? 0) >= 10 ? T.red : (r.days_to_unwind ?? 0) >= 3 ? T.amber : T.muted }}>{r.days_to_unwind == null ? '—' : r.days_to_unwind.toFixed(1)}</span> }
  const base: Column<MtfStock>[] = [
    { key: 's', label: 'Stock', sort: r => r.symbol, render: r => <span title={r.name ?? ''}><TickerLink symbol={r.symbol} /></span> },
    { key: 'a', label: 'Funded', align: 'right', sort: r => r.amount_cr ?? 0, render: r => <span style={{ color: T.text }}>{cr(r.amount_cr)}</span> },
    { key: 'c', label: `${lookback}-session chg`, align: 'right', sort: r => r.qty_chg_pct ?? -999,
      // m039: a name with no funded position `lookback` sessions ago (a new listing) says so instead of "—"
      render: r => r.qty_chg_pct == null ? <span style={{ color: T.dim }} title={`no funded position ${lookback} sessions ago: a new listing or a new MTF name`}>new</span>
        : <span style={{ color: (r.qty_chg_pct ?? 0) > 25 ? T.amber : T.text }}>{fmtPct(r.qty_chg_pct, 0)}</span> },
  ]
  const cols: Column<MtfStock>[] = [...base, unwindCol]
  // the ₹ change column only on the build-up board (three five-column tables overflowed their 420 px panels)
  const buildCols: Column<MtfStock>[] = [...base, { key: 'r', label: '₹ chg', align: 'right', sort: r => mtfRupeeChange(r).value ?? -1e9,
    title: 'change in the funded amount over the window, ₹ crore (≈: the added quantity at today\'s funding)',
    render: r => { const c = mtfRupeeChange(r); return c.value == null ? <span style={{ color: T.dim }}>—</span>
      : <span style={{ color: T.text }}>{c.approx ? '≈' : ''}{c.value >= 0 ? '+' : '−'}{cr(Math.abs(c.value))}</span> } }]

  // market book chart
  const P = 30
  const vals = m.map(r => (r.end_lakh ?? 0) / 100)
  const lo = vals.length ? Math.min(...vals) * 0.98 : 0, hi = vals.length ? Math.max(...vals) * 1.02 : 1
  const x = (i: number) => P + (i / Math.max(vals.length - 1, 1)) * (W - 2 * P)
  const y = (v: number) => 8 + (1 - (v - lo) / (hi - lo || 1)) * (H - 26)

  return (
    <div>
      <PageHeader code="MRGN" title="Margin Monitor"
        subtitle={`NSE margin trading facility (MTF) · broker-funded positions${data?.as_of ? ` · report ${data.as_of} (published T+1) vs ${data.base_date}` : ''}`}
        right={<div style={{ display: 'flex', gap: 4 }}>{[5, 20, 60].map(n => <Chip key={n} color={T.amber} active={lookback === n} onClick={() => setLookback(n)}>{n} SESSIONS</Chip>)}</div>} />
      {error && <ErrorBox error={error} />}
      {!data && !error && <Loading label="Reading NSE MTF reports" />}
      {data && last && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10, marginBottom: 12 }}>
            <Stat label="Market MTF book" value={lakhCr(last.end_lakh)} sub={`as of ${last.date}`} />
            <Stat label={`Change over ${lookback} sessions`} value={fmtPct(bookChg, 1)} color={(bookChg ?? 0) > 0 ? T.amber : T.green} sub="leverage building (amber) or unwinding" />
            <Stat label="Fresh funding · last day" value={lakhCr(last.fresh_lakh)} />
            <Stat label="Liquidated · last day" value={lakhCr(last.liquidated_lakh)} color={T.red} />
          </div>
          <Panel source={sourceOf(data?.as_of ?? null, { source: 'NSE MTF report (T+1)', maxAgeDays: 5 })} badge="context" title="Market MTF book · 1 year" accent={T.violet} pad={8} style={{ marginBottom: 12 }}
            subtitle="total broker-funded positions, ₹ crore · a rising book late in a rally is leverage that has to be sold in a fall">
            <div ref={chartRef} style={CHART_BOX}>
            <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }} role="img" aria-label="MTF book">
              {[lo, (lo + hi) / 2, hi].map(v => (
                <g key={v}><line x1={P} x2={W - P} y1={y(v)} y2={y(v)} stroke={T.border} strokeDasharray="3 4" />
                  <text x={P - 4} y={y(v) + 3} textAnchor="end" fontSize={9} fill={T.dim} fontFamily={T.mono}>{(v / 1000).toFixed(0)}k</text></g>))}
              <path d={vals.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join('')} fill="none" stroke={T.violet} strokeWidth={1.6} />
              <text x={P} y={H - 3} fontSize={9} fill={T.dim} fontFamily={T.mono}>{m[0]?.date}</text>
              <text x={W - P} y={H - 3} textAnchor="end" fontSize={9} fill={T.dim} fontFamily={T.mono}>{last.date}</text>
            </svg>
            </div>
          </Panel>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: 12, alignItems: 'start' }}>
            <Panel source={sourceOf(data?.as_of ?? null, { source: 'NSE MTF report (T+1)', maxAgeDays: 5 })} badge="context" title="Fastest leveraged build-up" accent={T.amber} pad={0}>
              <div style={{ display: 'flex', gap: 4, padding: '6px 10px', borderBottom: `1px solid ${T.border}`, alignItems: 'center' }}>
                <span style={{ fontSize: 10, color: T.dim, marginRight: 4 }}>RANK BY</span>
                <Chip color={T.amber} active={mode === 'pct'} onClick={() => setMode('pct')} title={`quantity growth, names with ≥ ${MTF_MIN_SESSIONS} sessions of MTF history`}>% GROWTH</Chip>
                <Chip color={T.amber} active={mode === 'rupees'} onClick={() => setMode('rupees')} title="the funded amount added, ₹ crore: no base effect">₹ ADDED</Chip>
              </div>
              <DataTable key={mode} columns={buildCols} rows={lists.building} rowKey={r => r.symbol} dense initialSort={{ key: mode === 'pct' ? 'c' : 'r', dir: 'desc' }} />
              {/* m039: the rule lives under the table (the header subtitle wrapped into an eight-line column) */}
              <div data-mrgn-rule style={{ padding: '6px 10px', fontSize: 11, color: T.dim, borderTop: `1px solid ${T.border}`, lineHeight: 1.5 }}>
                {mode === 'pct'
                  ? <>Funded-quantity growth over {lookback} sessions · ≥ ₹5 cr funded · only names with ≥ {MTF_MIN_SESSIONS} sessions of MTF history
                      {eligible ? (lists.excluded ? ` (${lists.excluded} recent listings left out: growth from a near-zero first day is a base effect)` : '') : ' (history check unavailable: recent listings may lead)'}</>
                  : <>Funded amount added over {lookback} sessions, ₹ crore · ≥ ₹5 cr funded · no history rule needed (a ₹ figure has no base effect)</>}
              </div>
            </Panel>
            <Panel source={sourceOf(data?.as_of ?? null, { source: 'NSE MTF report (T+1)', maxAgeDays: 5 })} badge="context" title="Most crowded" accent={T.red} pad={0}>
              <DataTable columns={cols} rows={lists.crowded} rowKey={r => r.symbol} dense initialSort={{ key: 'd', dir: 'desc' }} />
              <div style={{ padding: '6px 10px', fontSize: 11, color: T.dim, borderTop: `1px solid ${T.border}` }}>Days of normal turnover a forced sale would take · ≥ ₹5 cr funded</div>
            </Panel>
            <Panel source={sourceOf(data?.as_of ?? null, { source: 'NSE MTF report (T+1)', maxAgeDays: 5 })} badge="context" title="Largest funded positions" accent={T.cyan} pad={0}>
              <DataTable columns={cols} rows={lists.largest} rowKey={r => r.symbol} dense initialSort={{ key: 'a', dir: 'desc' }} />
            </Panel>
          </div>
          <div style={{ fontSize: 10, color: T.dim, marginTop: 8 }}>
            Context, not a signal: MTF build-ups were part of the held-overnight study (RSCH); a stock's own MTF trend is on its Profile (Positioning).
          </div>
        </>
      )}
    </div>
  )
}
