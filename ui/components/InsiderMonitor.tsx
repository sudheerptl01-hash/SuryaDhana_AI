'use client'

import { apiError } from '@/lib/errors'
import { fmtSigned } from '@/lib/format'   // signed numbers with U+2212 (C1-trader-ux-18)
/**
 * INSD — insider monitor: open-market purchases by promoters, directors and key managers (≥ ₹10 lakh by default),
 * per stock, with how the stock moved since the latest filing. The H4 definition from the held-overnight study,
 * where it was the strongest flow candidate (PROMISING, not proven). NSE PIT disclosures, dated by broadcast.
 */
import { useEffect, useState } from 'react'
import { getInsiderBuys, type InsiderBuy } from '@/lib/api'
import { daysUntil, useCorpEvents } from '@/lib/useCorpEvents'
import { orderCategories } from '@/components/pageModels'   // stable 'Who' order (P16)
import { Chip, DataTable, ErrorBox, EventBadge, Loading, PageHeader, Panel, ResearchNote, T, TickerLink, type Column } from '@/components/terminal'

const cr = (v: number | null) => (v == null ? '—' : v >= 1e7 ? `₹${(v / 1e7).toFixed(v >= 1e9 ? 0 : 1)} cr` : `₹${(v / 1e5).toFixed(1)} L`)

export function InsiderMonitor() {
  const [days, setDays] = useState(60)
  const [minValue, setMinValue] = useState(1e6)
  const [data, setData] = useState<Awaited<ReturnType<typeof getInsiderBuys>>['data'] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const events = useCorpEvents()
  useEffect(() => {
    setData(null); setError(null)
    getInsiderBuys(days, minValue).then(r => setData(r.data)).catch(e => setError(apiError(e, 'unavailable')))
  }, [days, minValue])

  const staleDays = data?.data_through ? Math.floor((Date.now() - new Date(`${data.data_through.slice(0, 10)}T00:00:00`).getTime()) / 86_400_000) : null
  const cols: Column<InsiderBuy>[] = [
    { key: 'symbol', label: 'Stock', sort: r => r.symbol, render: r => <TickerLink symbol={r.symbol} /> },
    { key: 'last', label: 'Latest filing', sort: r => r.last_date, render: r => <span style={{ color: T.text }}>{r.last_date}{r.first_date !== r.last_date && <span style={{ color: T.dim, fontSize: 10 }}> (from {r.first_date})</span>}</span> },
    { key: 'value', label: 'Bought', align: 'right', sort: r => r.total_value, render: r => <span style={{ color: T.green, fontWeight: 600 }}>{cr(r.total_value)}</span> },
    { key: 'trades', label: 'Trades', align: 'right', sort: r => r.trades, render: r => <span style={{ color: T.muted }}>{r.trades}</span> },
    { key: 'buyers', label: 'Buyers', align: 'right', sort: r => r.buyers, render: r => <span style={{ color: r.buyers > 1 ? T.amber : T.muted }}>{r.buyers}</span> },
    { key: 'who', label: 'Who', render: r => <span title={r.top_buyer ?? ''} style={{ color: T.muted, maxWidth: 300, display: 'inline-block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', verticalAlign: 'bottom' }}>{orderCategories(r.categories)}{r.top_buyer ? ` · ${r.top_buyer}` : ''}</span> },
    { key: 'since', label: 'Since filing', align: 'right', sort: r => r.since_filing_pct ?? -999,
      render: r => r.since_filing_pct == null ? '—' : <span style={{ color: r.since_filing_pct >= 0 ? T.green : T.red }}>{fmtSigned(r.since_filing_pct, 1)}%</span> },
    { key: 'event', label: 'Next event', render: r => { const e = events.get(r.symbol)?.[0]; return e ? <EventBadge kind={e.kind} date={e.event_date} days={daysUntil(e.event_date)} typical={e.typical_move_pct} detail={e.detail} /> : <span style={{ color: T.dim }}>—</span> } },
  ]
  return (
    <div>
      <PageHeader code="INSD" title="Insider Monitor"
        subtitle={`open-market buys by promoters, directors and key managers · NSE PIT disclosures${data?.data_through ? ` · data through ${data.data_through.slice(0, 10)}` : ''}`}
        right={<div style={{ display: 'flex', gap: 4 }}>
          {[30, 60, 180].map(d => <Chip key={d} color={T.amber} active={days === d} onClick={() => setDays(d)}>{d}D</Chip>)}
          <span style={{ width: 8 }} />
          {[[1e6, '≥ ₹10 L'], [1e7, '≥ ₹1 cr']].map(([v, l]) => <Chip key={l} color={T.green} active={minValue === v} onClick={() => setMinValue(v as number)}>{l}</Chip>)}
        </div>} />
      <ResearchNote verdict="PROMISING" report="reports/held_overnight/FINDINGS.md">
        Held-overnight study, H4: these purchases were followed by +1.0% / +2.6% excess over 20 days (2019–23 / 2024–26) and
        +4.4% / +2.7% over 60 days, but the holdout is not yet significant. Fresh first buys are being tracked forward from Oct 2026.
      </ResearchNote>
      {staleDays != null && staleDays > 14 && (
        <div style={{ fontSize: 11, color: T.red, marginBottom: 10 }}>⚠ The newest insider filing is {staleDays} days old: the NSE feed may have changed (Warehouse → NSE datasets).</div>
      )}
      {error && <ErrorBox error={error} />}
      {!data && !error && <Loading label="Reading insider filings" />}
      {data && (
        <Panel title={`${data.count} stocks with insider buying`} pad={0} accent={T.green}
          subtitle={`last ${days} days · market purchases only (no ESOPs, gifts, pledges or off-market transfers) · click a stock for its profile`}>
          <DataTable columns={cols} rows={data.rows} rowKey={r => r.symbol} dense maxHeight={700} initialSort={{ key: 'last', dir: 'desc' }}
            empty="No qualifying insider purchases in this window" />
        </Panel>
      )}
    </div>
  )
}
