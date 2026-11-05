'use client'

import { apiError } from '@/lib/errors'
import { fmtSigned } from '@/lib/format'   // signed numbers with U+2212 (C1-trader-ux-18)
/**
 * HDS — ownership shifts: for each stock with shareholding filings (the ~320 most liquid names), the latest quarter vs
 * the one before. Change in promoter, foreign-investor (FPI), mutual-fund and retail share in percentage points, and
 * the change in the number of shareholders. Quick views: where mutual funds and FPIs bought or sold the most, and
 * where shareholder counts jumped (a retail rush). Companies file within 21 days of the quarter end.
 */
import { useEffect, useMemo, useState } from 'react'
import { getHoldingChanges, type HoldingChange } from '@/lib/api'
import { Chip, DataTable, ErrorBox, Loading, PageHeader, Panel, T, TickerLink, type Column, sourceOf } from '@/components/terminal'

type View = 'mf_buy' | 'mf_sell' | 'fpi_buy' | 'fpi_sell' | 'promoter' | 'holders'
const VIEWS: [View, string, (r: HoldingChange) => number | null, 'asc' | 'desc'][] = [
  ['mf_buy', 'MF BUYING', r => r.d_mf, 'desc'], ['mf_sell', 'MF SELLING', r => r.d_mf, 'asc'],
  ['fpi_buy', 'FPI BUYING', r => r.d_fpi, 'desc'], ['fpi_sell', 'FPI SELLING', r => r.d_fpi, 'asc'],
  ['promoter', 'PROMOTER CHANGES', r => (r.d_promoter == null ? null : Math.abs(r.d_promoter)), 'desc'],
  ['holders', 'SHAREHOLDER SURGE', r => r.d_holders_pct, 'desc'],
]
const pp = (v: number | null) => (v == null ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(2)} pp`)
const tone = (v: number | null) => (v == null || Math.abs(v) < 0.005 ? T.muted : v > 0 ? T.green : T.red)
const qtr = (iso: string | null) => (iso ? new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { month: 'short', year: '2-digit' }) : '—')

export function OwnershipShifts() {
  const [data, setData] = useState<Awaited<ReturnType<typeof getHoldingChanges>>['data'] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<View>('mf_buy')
  const [period, setPeriod] = useState<string | null>(null)
  useEffect(() => { getHoldingChanges().then(r => setData(r.data)).catch(e => setError(apiError(e, 'unavailable'))) }, [])

  // quarters with enough filings to compare (month ends only: ignore odd interim dates)
  const periods = useMemo(() => {
    const c = new Map<string, number>()
    for (const r of data?.rows ?? []) if (r.prev_period && /-(03-31|06-30|09-30|12-31)$/.test(r.period_end)) c.set(r.period_end, (c.get(r.period_end) ?? 0) + 1)
    return [...c.entries()].sort((a, b) => b[0].localeCompare(a[0]))
  }, [data])
  const active = period ?? periods[0]?.[0] ?? null
  const [, , key, dir] = VIEWS.find(v => v[0] === view)!
  const rows = useMemo(() => (data?.rows ?? [])
    .filter(r => r.period_end === active && key(r) != null)
    .sort((a, b) => (dir === 'desc' ? key(b)! - key(a)! : key(a)! - key(b)!)).slice(0, 60), [data, active, key, dir])

  const cols: Column<HoldingChange>[] = [
    { key: 's', label: 'Stock', sort: r => r.symbol, render: r => <TickerLink symbol={r.symbol} /> },
    { key: 'mf', label: 'Mutual funds', align: 'right', sort: r => r.d_mf ?? -99, render: r => <span><span style={{ color: tone(r.d_mf), fontWeight: 600 }}>{pp(r.d_mf)}</span> <span style={{ color: T.dim, fontSize: 10 }}>→ {r.mf_pct?.toFixed(1) ?? '—'}%</span></span> },
    { key: 'fpi', label: 'Foreign investors', align: 'right', sort: r => r.d_fpi ?? -99, render: r => <span><span style={{ color: tone(r.d_fpi), fontWeight: 600 }}>{pp(r.d_fpi)}</span> <span style={{ color: T.dim, fontSize: 10 }}>→ {r.fpi_pct?.toFixed(1) ?? '—'}%</span></span> },
    { key: 'pr', label: 'Promoters', align: 'right', sort: r => r.d_promoter ?? -99, render: r => <span><span style={{ color: tone(r.d_promoter) }}>{pp(r.d_promoter)}</span> <span style={{ color: T.dim, fontSize: 10 }}>→ {r.promoter_pct?.toFixed(1) ?? '—'}%</span></span> },
    { key: 'rt', label: 'Retail', align: 'right', sort: r => r.d_retail ?? -99, render: r => <span><span style={{ color: tone(r.d_retail) }}>{pp(r.d_retail)}</span> <span style={{ color: T.dim, fontSize: 10 }}>→ {r.retail_pct?.toFixed(1) ?? '—'}%</span></span> },
    { key: 'h', label: 'Shareholders', align: 'right', sort: r => r.d_holders_pct ?? -99,
      render: r => <span><span style={{ color: (r.d_holders_pct ?? 0) > 20 ? T.amber : T.muted }}>{r.d_holders_pct == null ? '—' : `${fmtSigned(r.d_holders_pct, 0)}%`}</span>
        <span style={{ color: T.dim, fontSize: 10 }}> {r.total_holders != null ? `→ ${(r.total_holders / 1e5).toFixed(1)} L` : ''}</span></span> },
    { key: 'q', label: 'Quarter', render: r => <span style={{ color: T.dim, fontSize: 10.5 }}>{qtr(r.prev_period)} → {qtr(r.period_end)}</span> },
  ]

  return (
    <div>
      <PageHeader code="HDS" title="Ownership Shifts"
        subtitle={`quarterly shareholding filings (NSE XBRL) · latest vs previous quarter · ${data ? `${data.count} stocks covered (the most liquid names)` : 'loading'}`}
        right={<div style={{ display: 'flex', gap: 4 }}>{periods.slice(0, 3).map(([p, n]) => (
          <Chip key={p} color={T.cyan} active={active === p} onClick={() => setPeriod(p)}>Q-END {qtr(p).toUpperCase()} · {n}</Chip>))}</div>} />
      {error && <ErrorBox error={error} />}
      {!data && !error && <Loading label="Reading shareholding filings" />}
      {data && (
        <Panel source={sourceOf(data?.data_through ?? null, { source: 'NSE shareholding filings', maxAgeDays: 120 })} badge="context" title={`${VIEWS.find(v => v[0] === view)![1]} · quarter ended ${qtr(active)}`} accent={T.violet} pad={0}
          subtitle="pp = percentage points of the company's shares · the shareholder count includes every demat holder · companies file within 21 days of the quarter end"
          right={<div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>{VIEWS.map(([k, l]) => <Chip key={k} color={T.violet} active={view === k} onClick={() => setView(k)}>{l}</Chip>)}</div>}>
          <DataTable columns={cols} rows={rows} rowKey={r => r.symbol} dense maxHeight={720} empty="No filings for this quarter yet" />
        </Panel>
      )}
      <div style={{ fontSize: 10, color: T.dim, marginTop: 8 }}>
        Context, not a signal: ownership changes were part of the held-overnight research (RSCH). A stock's full ownership history is on its Profile.
      </div>
    </div>
  )
}
