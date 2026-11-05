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
import { CHART_BOX, Chip, DataTable, ErrorBox, Loading, PageHeader, Panel, Stat, T, TickerLink, fmtPct, type Column, useChartSize } from '@/components/terminal'

const cr = (v: number | null | undefined) => (v == null ? '—' : v >= 1000 ? `₹${(v / 1000).toFixed(2)}k cr` : `₹${v.toFixed(v >= 100 ? 0 : 1)} cr`)
const lakhCr = (lakh: number | null | undefined) => (lakh == null ? '—' : `₹${(lakh / 100).toLocaleString('en-IN', { maximumFractionDigits: 0 })} cr`)

export function MarginMonitor() {
  const [lookback, setLookback] = useState(20)
  const [data, setData] = useState<Awaited<ReturnType<typeof getMtfMonitor>>['data'] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const { ref: chartRef, w: W, h: H } = useChartSize(1000, 150, { maxRatio: 1.2 })   // CSS px (C1-17)
  useEffect(() => {
    setData(null)
    getMtfMonitor(lookback, 1).then(r => setData(r.data)).catch(e => setError(apiError(e, 'unavailable')))
  }, [lookback])

  const m = data?.market ?? []
  const last = m[m.length - 1], prior = m[Math.max(0, m.length - 1 - lookback)]
  const bookChg = last?.end_lakh && prior?.end_lakh ? (last.end_lakh / prior.end_lakh - 1) * 100 : null
  const lists = useMemo(() => {
    const st = (data?.stocks ?? []).filter(s => (s.amount_cr ?? 0) >= 5)
    return {
      largest: [...st].sort((a, b) => (b.amount_cr ?? 0) - (a.amount_cr ?? 0)).slice(0, 25),
      building: [...st].filter(s => s.qty_chg_pct != null).sort((a, b) => b.qty_chg_pct! - a.qty_chg_pct!).slice(0, 25),
      crowded: [...st].filter(s => s.days_to_unwind != null).sort((a, b) => b.days_to_unwind! - a.days_to_unwind!).slice(0, 25),
    }
  }, [data])

  const cols: Column<MtfStock>[] = [
    { key: 's', label: 'Stock', sort: r => r.symbol, render: r => <span title={r.name ?? ''}><TickerLink symbol={r.symbol} /></span> },
    { key: 'a', label: 'Funded', align: 'right', sort: r => r.amount_cr ?? 0, render: r => <span style={{ color: T.text }}>{cr(r.amount_cr)}</span> },
    { key: 'c', label: `${lookback}-session chg`, align: 'right', sort: r => r.qty_chg_pct ?? -999,
      render: r => <span style={{ color: (r.qty_chg_pct ?? 0) > 25 ? T.amber : (r.qty_chg_pct ?? 0) < 0 ? T.green : T.text }}>{fmtPct(r.qty_chg_pct, 0)}</span> },
    { key: 'd', label: 'Days to unwind', align: 'right', sort: r => r.days_to_unwind ?? -1,
      render: r => <span style={{ color: (r.days_to_unwind ?? 0) >= 10 ? T.red : (r.days_to_unwind ?? 0) >= 3 ? T.amber : T.muted }}>{r.days_to_unwind == null ? '—' : r.days_to_unwind.toFixed(1)}</span> },
  ]

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
          <Panel title="Market MTF book · 1 year" accent={T.violet} pad={8} style={{ marginBottom: 12 }}
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
            <Panel title="Fastest leveraged build-up" accent={T.amber} pad={0} subtitle={`funded quantity growth over ${lookback} sessions · ≥ ₹5 cr funded`}>
              <DataTable columns={cols} rows={lists.building} rowKey={r => r.symbol} dense initialSort={{ key: 'c', dir: 'desc' }} />
            </Panel>
            <Panel title="Most crowded" accent={T.red} pad={0} subtitle="days of normal turnover a forced sale would take · ≥ ₹5 cr funded">
              <DataTable columns={cols} rows={lists.crowded} rowKey={r => r.symbol} dense initialSort={{ key: 'd', dir: 'desc' }} />
            </Panel>
            <Panel title="Largest funded positions" accent={T.cyan} pad={0} subtitle="₹ crore held on margin">
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
