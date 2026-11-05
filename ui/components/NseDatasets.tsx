'use client'

import { apiError } from '@/lib/errors'
/** NSE research datasets: rows and date range of every NSE table SuryaDhana keeps (Warehouse tab). */
import { useEffect, useState } from 'react'
import { getArchiveMeta, getNseDatasetsMeta } from '@/lib/api'
import { DataTable, Panel, T, type Column } from '@/components/terminal'

// newest row should be no older than this many days (weekends + publication lag); older = the feed may have broken
const MAX_AGE_DAYS: Record<string, number> = {
  nse_bhavcopy: 5, nse_fo_daily: 5, nse_participant_oi: 5, nse_deals: 5, nse_mtf: 6,
  nse_insider_trades: 14, nse_shareholding: 120, nse_results: 21, nse_fii_dii_cash: 5,
  'archive:preopen': 5, 'archive:internals': 5, 'archive:financials': 8,
}
const ageDays = (iso: string | null) => (iso ? Math.floor((Date.now() - new Date(`${iso.slice(0, 10)}T00:00:00`).getTime()) / 86_400_000) : null)

const ABOUT: Record<string, [string, string]> = {
  nse_bhavcopy: ['Bhavcopy (all securities, delivery %)', 'EOD pipeline, daily'],
  nse_fo_daily: ['F&O futures and options OI', 'EOD pipeline + 20:30 catch-up'],
  nse_participant_oi: ['Participant-wise OI (FII / DII / Pro / Client)', 'EOD pipeline'],
  nse_deals: ['Bulk, block and short deals', 'EOD pipeline'],
  nse_mtf: ['Margin trading (MTF) positions', 'EOD pipeline (T+1)'],
  nse_insider_trades: ['Insider trades (PIT)', 'Saturday 09:00'],
  nse_shareholding: ['Shareholding pattern (XBRL)', 'Saturday 09:00'],
  nse_events: ['Corporate calendar (results, ex-dates)', 'EOD pipeline + 12 h self-refresh'],
  nse_results: ['Quarterly results release times', 'on demand / weekly per stock'],
  nse_fii_dii_cash: ['FII / DII cash-market flows (latest day only: collected from 12 Oct 2026)', '20:30 catch-up + page self-refresh'],
  'archive:preopen': ['Pre-open auction books (files; rows = files)', '09:09:30 capture, weekdays'],
  'archive:internals': ['Market internals through the day (files = sessions)', 'every 2 min in session'],
  'archive:financials': ['Quarterly financials from results XBRL (files = companies; dates = last read)', 'results filings + Saturday sweep'],
  'archive:ipo': ['IPO bid books (files = issues)', 'on demand (IPO page)'],
  'archive:derived': ['Derived history (option IV / PCR)', 'OMON, incremental'],
}

interface Row { table: string; first: string | null; last: string | null; rows: number }

export function NseDatasets() {
  const [rows, setRows] = useState<Row[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    Promise.all([getNseDatasetsMeta(), getArchiveMeta().catch(() => ({ data: {} }))])
      .then(([db, files]) => setRows([...Object.entries(db.data), ...Object.entries(files.data)].map(([table, v]) => ({ table, ...v }))))
      .catch(e => setErr(apiError(e, 'unavailable')))
  }, [])
  const cols: Column<Row>[] = [
    { key: 'table', label: 'Dataset', render: r => <span><span style={{ color: T.text }}>{ABOUT[r.table]?.[0] ?? r.table}</span> <span style={{ color: T.dim, fontSize: 10 }}>{r.table}</span></span> },
    { key: 'rows', label: 'Rows', align: 'right', sort: r => r.rows, render: r => r.rows.toLocaleString('en-IN') },
    { key: 'first', label: 'From', align: 'right', render: r => <span style={{ color: T.muted }}>{r.first?.slice(0, 10) ?? '—'}</span> },
    { key: 'last', label: 'To', align: 'right', render: r => <span style={{ color: T.text }}>{r.last?.slice(0, 10) ?? '—'}</span> },
    { key: 'health', label: 'Freshness', render: r => {
      const age = ageDays(r.last), max = MAX_AGE_DAYS[r.table]
      if (age == null || max == null) return <span style={{ color: T.dim }}>—</span>
      const stale = age > max
      return <span title={stale ? `Newest row is ${age} days old (expected ≤ ${max}): the source may have changed or the job is failing` : ''}
                   style={{ color: stale ? T.red : T.green, fontWeight: stale ? 700 : 400 }}>{stale ? `⚠ STALE ${age}d` : `OK · ${Math.max(age, 0)}d`}</span>
    } },
    { key: 'when', label: 'Refreshed', render: r => <span style={{ color: T.dim }}>{ABOUT[r.table]?.[1] ?? ''}</span> },
  ]
  return (
    <Panel title="NSE research datasets" subtitle="free official NSE data: DuckDB tables, then file archives (data/nse_archive) · see docs/NSE_DATA_DICTIONARY.md" pad={0} accent={T.cyan}>
      {err ? <div style={{ padding: 12, fontSize: 11, color: T.red }}>{err}</div>
        : <DataTable columns={cols} rows={rows ?? []} rowKey={r => r.table} dense empty={rows ? 'No datasets' : 'Loading…'} />}
    </Panel>
  )
}
