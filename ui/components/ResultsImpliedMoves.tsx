'use client'

/**
 * Options into results (Bloomberg-style implied earnings move): for F&O stocks reporting in the next ten days, the
 * move their options price by the first expiry after the results, the part of it attributable to the results day,
 * and the stock's usual results-day move. Names are judged against this week's median ratio (about 1.0 on corrected
 * release times): well above it = options price an unusually big reaction.
 */
import { useEffect, useState } from 'react'
import { getResultsImpliedMoves, type ImpliedMoveRow } from '@/lib/api'
import { DataTable, Panel, T, TickerLink, type Column, fmtDay } from '@/components/terminal'

const pm = (v: number | null | undefined, d = 1) => (v == null ? '—' : `±${v.toFixed(d)}%`)

export function ResultsImpliedMoves() {
  const [d, setD] = useState<Awaited<ReturnType<typeof getResultsImpliedMoves>>['data'] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { getResultsImpliedMoves(10).then(r => setD(r.data)).catch(e => setErr(e?.message || 'unavailable')) }, [])
  if (err || !d || !d.rows.length) return null
  const ratios = d.rows.map(r => r.ratio).filter((x): x is number => x != null).sort((a, b) => a - b)
  const med = ratios.length ? ratios[Math.floor(ratios.length / 2)] : 1
  const cols: Column<ImpliedMoveRow>[] = [
    { key: 'sym', label: 'Stock', sort: r => r.symbol, render: r => <TickerLink symbol={r.symbol} /> },
    { key: 'date', label: 'Results', sort: r => r.results_date, render: r => <span style={{ color: T.text, whiteSpace: 'nowrap' }}>{fmtDay(r.results_date)}</span> },
    { key: 'exp', label: 'Options to', render: r => <span style={{ color: T.dim, whiteSpace: 'nowrap' }}>{r.expiry ? fmtDay(r.expiry) : '—'} · {r.trading_days}d</span> },
    { key: 'iv', label: 'ATM IV', align: 'right', sort: r => r.atm_iv ?? 0, render: r => <span style={{ color: T.violet }}>{r.atm_iv != null ? `${r.atm_iv}%` : '—'}</span> },
    { key: 'em', label: 'Priced to expiry', align: 'right', sort: r => r.expected_move_pct ?? 0, title: '±1 standard deviation by the expiry, from at-the-money implied volatility',
      render: r => <span style={{ color: T.muted }}>{pm(r.expected_move_pct)}</span> },
    { key: 'ev', label: 'Results-day move priced', align: 'right', sort: r => r.event_abs_move_pct ?? 0,
      title: "the part of the priced move left after normal days (60-session realised volatility), as an expected absolute move",
      render: r => <span style={{ color: T.amber, fontWeight: 600 }}>{pm(r.event_abs_move_pct)}</span> },
    { key: 'typ', label: 'Usual reaction', align: 'right', sort: r => r.typical_move_pct ?? 0, title: 'average absolute results-day move, last 8 quarters',
      render: r => <span>{pm(r.typical_move_pct)}{r.quarters ? <span style={{ color: T.dim, fontSize: 10 }}> ({r.quarters}q)</span> : null}</span> },
    { key: 'ratio', label: 'Priced ÷ usual', align: 'right', sort: r => r.ratio ?? 0,
      render: r => r.ratio == null ? <span style={{ color: T.dim }}>—</span>
        : <span style={{ color: r.ratio >= 1.5 * med ? T.amber : r.ratio <= med / 1.5 ? T.cyan : T.text, fontWeight: r.ratio >= 1.5 * med || r.ratio <= med / 1.5 ? 700 : 400 }}>{r.ratio.toFixed(2)}×</span> },
    { key: 'm', label: 'Normal days from', render: r => <span style={{ color: T.dim, fontSize: 10 }} title={r.method === 'term' ? "the gap between the first two expiries' implied volatility" : 'recent realised volatility (only one expiry usable): overstates the results-day part'}>
        {r.method === 'term' ? 'options' : r.method === 'realised' ? 'realised vol' : '—'}</span> },
  ]
  return (
    <Panel title={`Options into results · ${d.rows.length} F&O names`} accent={T.violet} pad={0} style={{ marginBottom: 12 }}
      subtitle={`next ${d.days} days · NSE F&O bhavcopy ${d.fo_date ?? ''} · this week's median priced ÷ usual ${med.toFixed(2)}× · amber = ≥ 1.5× that median (an unusually big reaction priced), cyan = ≤ ⅔ of it`}>
      <DataTable columns={cols} rows={d.rows} rowKey={r => `${r.symbol}-${r.results_date}`} dense initialSort={{ key: 'ratio', dir: 'desc' }} exportName="results_implied_moves" />
      <div style={{ fontSize: 10, color: T.dim, padding: '6px 10px', lineHeight: 1.5 }}>
        Results-day move priced = √(priced variance to expiry − normal days × recent daily variance) × 0.8 (σ → average absolute move).
        An approximation from end-of-day option prices: it describes what the options charge, not which way the stock moves.
      </div>
    </Panel>
  )
}
