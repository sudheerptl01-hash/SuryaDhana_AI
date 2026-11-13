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
import { hdsCoverage, isQoq, isQuarterEnd, ppCell } from '@/components/marketPagesModel'

type View = 'mf_buy' | 'mf_sell' | 'fpi_buy' | 'fpi_sell' | 'promoter' | 'holders'
const VIEWS: [View, string, (r: HoldingChange) => number | null, 'asc' | 'desc'][] = [
  ['mf_buy', 'MF BUYING', r => r.d_mf, 'desc'], ['mf_sell', 'MF SELLING', r => r.d_mf, 'asc'],
  ['fpi_buy', 'FPI BUYING', r => r.d_fpi, 'desc'], ['fpi_sell', 'FPI SELLING', r => r.d_fpi, 'asc'],
  ['promoter', 'PROMOTER CHANGES', r => (r.d_promoter == null ? null : Math.abs(r.d_promoter)), 'desc'],
  ['holders', 'SHAREHOLDER SURGE', r => r.d_holders_pct, 'desc'],
]
const tone = (v: number | null) => (v == null || Math.abs(v) < 0.005 ? T.muted : v > 0 ? T.green : T.red)
const qtr = (iso: string | null) => (iso ? new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { month: 'short', year: '2-digit' }) : '—')

export function OwnershipShifts() {
  const [data, setData] = useState<Awaited<ReturnType<typeof getHoldingChanges>>['data'] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [view, setView] = useState<View>('mf_buy')
  const [period, setPeriod] = useState<string | null>(null)
  useEffect(() => { getHoldingChanges().then(r => setData(r.data)).catch(e => setError(apiError(e, 'unavailable'))) }, [])

  // quarters with filings to compare. M25: a row counts only when BOTH filings are consecutive quarter ends: IPO and
  // listing-time filings ('Sept 26 → Sept 26', 'Aug 26 → Sept 26': allotment, not buying) leave the leaderboards
  const periods = useMemo(() => {
    const c = new Map<string, number>()
    for (const r of data?.rows ?? []) if (isQuarterEnd(r.period_end) && isQoq(r)) c.set(r.period_end, (c.get(r.period_end) ?? 0) + 1)
    return [...c.entries()].sort((a, b) => b[0].localeCompare(a[0]))
  }, [data])
  const active = period ?? periods[0]?.[0] ?? null
  const [, , key, dir] = VIEWS.find(v => v[0] === view)!
  const rows = useMemo(() => (data?.rows ?? [])
    .filter(r => r.period_end === active && isQoq(r) && key(r) != null)
    .sort((a, b) => (dir === 'desc' ? key(b)! - key(a)! : key(a)! - key(b)!)).slice(0, 60), [data, active, key, dir])

  const cov = useMemo(() => hdsCoverage(data?.rows ?? [], active), [data, active])
  // m038: a missing holder group prints "—" once, never "— → —%"
  const cell = (d: number | null, lvl: number | null, strong = false) => {
    const c = ppCell(d, lvl)
    return <span><span style={{ color: tone(d), fontWeight: strong ? 600 : 400 }}>{c.change}</span>{c.level && <span style={{ color: T.dim, fontSize: 10 }}> {c.level}</span>}</span>
  }
  const cols: Column<HoldingChange>[] = [
    { key: 's', label: 'Stock', sort: r => r.symbol, render: r => <TickerLink symbol={r.symbol} /> },
    { key: 'mf', label: 'Mutual funds', align: 'right', sort: r => r.d_mf ?? -99, render: r => cell(r.d_mf, r.mf_pct, true) },
    { key: 'fpi', label: 'Foreign investors', align: 'right', sort: r => r.d_fpi ?? -99, render: r => cell(r.d_fpi, r.fpi_pct, true) },
    { key: 'pr', label: 'Promoters', align: 'right', sort: r => r.d_promoter ?? -99, render: r => cell(r.d_promoter, r.promoter_pct) },
    { key: 'rt', label: 'Retail', align: 'right', sort: r => r.d_retail ?? -99, render: r => cell(r.d_retail, r.retail_pct) },
    { key: 'h', label: 'Shareholders', align: 'right', sort: r => r.d_holders_pct ?? -99,
      render: r => <span><span style={{ color: (r.d_holders_pct ?? 0) > 20 ? T.amber : T.muted }}>{r.d_holders_pct == null ? '—' : `${fmtSigned(r.d_holders_pct, 0)}%`}</span>
        <span style={{ color: T.dim, fontSize: 10 }}> {r.total_holders != null ? `→ ${(r.total_holders / 1e5).toFixed(1)} L` : ''}</span></span> },
    { key: 'q', label: 'Quarter', render: r => <span style={{ color: T.dim, fontSize: 11 }}>{qtr(r.prev_period)} → {qtr(r.period_end)}</span> },
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
          {/* m037: how the header's coverage splits for this quarter */}
          <div data-hds-coverage style={{ padding: '6px 10px', fontSize: 11, color: T.dim, borderTop: `1px solid ${T.border}`, lineHeight: 1.5 }}>
            Quarter ended {qtr(active)}: {cov.filings} filings read · <span style={{ color: T.muted }}>{cov.qoq} compared with the quarter before</span>
            {cov.listing > 0 && <> · {cov.listing} left out: the earlier filing is not the previous quarter end (an IPO or listing-time shareholding: allotment, not buying)</>}
            {cov.first > 0 && <> · {cov.first} with no earlier filing</>}
            {data.count > cov.filings && <> · the header&apos;s {data.count} stocks include names with no filing for this quarter yet</>}
          </div>
        </Panel>
      )}
      <div style={{ fontSize: 10, color: T.dim, marginTop: 8 }}>
        Context, not a signal: ownership changes were part of the held-overnight research (RSCH). A stock's full ownership history is on its Profile.
      </div>
    </div>
  )
}
