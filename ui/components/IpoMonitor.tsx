'use client'

import { apiError } from '@/lib/errors'
/**
 * IPO — open and forthcoming issues (NSE) with live category-wise subscription, and a scorecard of recent listings:
 * listing-day open vs the issue price, the day-1 close, +20 / +60 sessions from the day-1 close, and today vs the
 * issue price (NSE bhavcopy). The QIB-bucket table is descriptive and in-sample: context, not a trading rule.
 */
import { useEffect, useMemo, useState } from 'react'
import { getIpo, type IpoBids, type IpoBucket, type IpoIssue, type IpoListing } from '@/lib/api'
import { Chip, DataTable, ErrorBox, Loading, PageHeader, Panel, Stat, T, TickerLink, fmtPct, type Column, median, sourceOf } from '@/components/terminal'
import { ipoRows, isEntitlementSymbol } from '@/components/marketPagesModel'

const tone = (v: number | null | undefined) => (v == null || Math.abs(v) < 0.05 ? T.muted : v > 0 ? T.green : T.red)
const times = (v: number | null | undefined) => (v == null ? '—' : v >= 100 ? `${v.toFixed(0)}×` : `${v.toFixed(1)}×`)
const day = (iso: string | null) => (iso ? new Date(`${iso}T00:00:00`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }) : '—')
const Pct = ({ v, bold }: { v: number | null | undefined; bold?: boolean }) => <span style={{ color: tone(v), fontWeight: bold ? 600 : 400 }}>{fmtPct(v, 1)}</span>
const Sub = ({ v, strong = 50 }: { v: number | null | undefined; strong?: number }) =>
  <span style={{ color: v == null ? T.dim : v >= strong ? T.green : v >= 1 ? T.text : T.red }}>{times(v)}</span>

function BidsLine({ b }: { b: IpoBids }) {
  return (
    <span style={{ display: 'inline-flex', gap: 10, fontSize: 11 }}>
      <span><span style={{ color: T.dim }}>QIB</span> <Sub v={b.qib} /></span>
      <span><span style={{ color: T.dim }}>NII</span> <Sub v={b.nii} /></span>
      <span><span style={{ color: T.dim }}>Retail</span> <Sub v={b.retail} strong={10} /></span>
      <span><span style={{ color: T.dim }}>Total</span> <b><Sub v={b.total} /></b></span>
    </span>
  )
}

export function IpoMonitor() {
  const [kind, setKind] = useState<'Mainboard' | 'SME'>('Mainboard')
  const [months, setMonths] = useState(24)
  const [data, setData] = useState<Awaited<ReturnType<typeof getIpo>>['data'] | null>(null)
  const [error, setError] = useState<string | null>(null)
  // m041: when NSE's issue list was last read successfully (an empty list and a failed fetch must not look alike)
  const [checkedAt, setCheckedAt] = useState<Date | null>(null)
  useEffect(() => {
    let alive = true
    const load = () => getIpo(months, kind).then(r => { if (alive) { setData(r.data); setError(null); setCheckedAt(new Date()) } })
      .catch(e => alive && setError(apiError(e, 'unavailable')))
    setData(null); load()
    // while past bid books are being fetched in the background, re-read every 20 s; open issues every 2 min
    const iv = setInterval(load, 20_000)
    return () => { alive = false; clearInterval(iv) }
  }, [months, kind])

  // m040: one row per listing; rights entitlements / partly-paid lines (ADANIENPP1 ×3) out; rows NSE has no price
  // for yet are counted under the table instead of listed as all-"—" lines
  const clean = useMemo(() => ipoRows(data?.recent ?? []), [data])
  const rows = clean.rows
  const issues = useMemo(() => (data?.issues ?? []).filter(i => !isEntitlementSymbol(i.symbol)), [data])
  const priced = useMemo(() => rows.filter(r => r.listing_gain_pct != null), [rows])
  const stats = useMemo(() => ({
    medGain: median(priced.map(r => r.listing_gain_pct!)),
    above: priced.length ? (priced.filter(r => r.listing_gain_pct! > 0).length / priced.length) * 100 : null,
    medSince: median(priced.map(r => r.since_issue_pct!).filter(v => v != null)),
    below: priced.filter(r => (r.since_issue_pct ?? 0) < 0).length,
  }), [priced])

  const issueCols: Column<IpoIssue>[] = [
    { key: 'status', label: 'Status', render: r => <span style={{ color: r.status === 'Open' ? T.green : T.amber, fontWeight: 600, fontSize: 11, letterSpacing: 0.5 }}>{(r.status ?? '').toUpperCase()}</span> },
    { key: 'company', label: 'Company', render: r => <span><span style={{ color: T.amber }}>{r.symbol}</span> <span style={{ color: T.muted }}>{r.company}</span></span> },
    { key: 'series', label: 'Board', render: r => <span style={{ color: r.series === 'SME' ? T.violet : T.cyan, fontSize: 11 }}>{r.series === 'SME' ? 'SME' : 'MAIN'}</span> },
    { key: 'dates', label: 'Bidding', render: r => <span style={{ color: T.text }}>{day(r.start)} → {day(r.end)}{r.days_left != null && r.days_left >= 0 && r.status === 'Open' ? <span style={{ color: T.dim }}> · {r.days_left === 0 ? 'closes today' : `${r.days_left}d left`}</span> : null}</span> },
    { key: 'band', label: 'Price band', align: 'right', render: r => <span style={{ color: T.bright }}>{r.price_lo != null ? (r.price_lo === r.price_hi ? `₹${r.price_hi}` : `₹${r.price_lo}–${r.price_hi}`) : '—'}</span> },
    { key: 'size', label: 'Size', align: 'right', sort: r => r.size_cr ?? 0, render: r => <span style={{ color: T.text }}>{r.size_cr != null ? `₹${r.size_cr.toLocaleString('en-IN', { maximumFractionDigits: 0 })} cr` : '—'}</span> },
    { key: 'lot', label: 'Lot', align: 'right', render: r => <span style={{ color: T.muted }}>{r.lot ? `${r.lot.toLocaleString('en-IN')} sh${r.price_hi ? ` · ₹${(r.lot * r.price_hi).toLocaleString('en-IN', { maximumFractionDigits: 0 })}` : ''}` : '—'}</span> },
    { key: 'bids', label: 'Subscription (live)', render: r => r.bids ? <BidsLine b={r.bids} /> : <span style={{ color: T.dim }}>{r.status === 'Open' ? (r.series === 'SME' ? 'n/a on NSE for SME' : '—') : 'opens ' + day(r.start)}</span> },
  ]
  const cols: Column<IpoListing>[] = [
    { key: 'date', label: 'Listed', sort: r => r.listing_date, render: r => <span style={{ color: T.text }}>{day(r.listing_date)} <span style={{ color: T.dim, fontSize: 10 }}>{r.listing_date.slice(2, 4)}</span></span> },
    { key: 'symbol', label: 'Stock', sort: r => r.symbol, render: r => <span title={r.company ?? ''}><TickerLink symbol={r.symbol} /></span> },
    { key: 'issue', label: 'Issue ₹', align: 'right', sort: r => r.issue_price, render: r => <span style={{ color: T.muted }}>{r.issue_price.toLocaleString('en-IN')}</span> },
    ...(kind === 'Mainboard' ? [
      { key: 'qib', label: 'QIB', align: 'right', sort: (r: IpoListing) => r.qib ?? -1, render: (r: IpoListing) => <Sub v={r.qib} /> },
      { key: 'retail', label: 'Retail', align: 'right', sort: (r: IpoListing) => r.retail ?? -1, render: (r: IpoListing) => <Sub v={r.retail} strong={10} /> },
      { key: 'total', label: 'Total', align: 'right', sort: (r: IpoListing) => r.total ?? -1, render: (r: IpoListing) => <Sub v={r.total} /> },
    ] as Column<IpoListing>[] : []),
    { key: 'gain', label: 'Listing open', align: 'right', sort: r => r.listing_gain_pct ?? -999, render: r => <Pct v={r.listing_gain_pct} bold /> },
    { key: 'd1', label: 'Day-1 close', align: 'right', sort: r => r.listing_close_pct ?? -999, render: r => <Pct v={r.listing_close_pct} /> },
    { key: 'r20', label: '+20 sess.', align: 'right', sort: r => r.ret_20d_pct ?? -999, render: r => <Pct v={r.ret_20d_pct} /> },
    { key: 'r60', label: '+60 sess.', align: 'right', sort: r => r.ret_60d_pct ?? -999, render: r => <Pct v={r.ret_60d_pct} /> },
    { key: 'since', label: 'Now vs issue', align: 'right', sort: r => r.since_issue_pct ?? -999, render: r => <Pct v={r.since_issue_pct} bold /> },
  ]
  const bucketCols: Column<IpoBucket>[] = [
    { key: 'b', label: 'QIB subscribed', render: r => <span style={{ color: T.text }}>{r.bucket}</span> },
    { key: 'n', label: 'IPOs', align: 'right', render: r => <span style={{ color: T.muted }}>{r.n}</span> },
    { key: 'mean', label: 'Avg listing gain', align: 'right', render: r => <Pct v={r.mean_listing_gain} bold /> },
    { key: 'med', label: 'Median', align: 'right', render: r => <Pct v={r.median_listing_gain} /> },
    { key: 'above', label: 'Listed above issue', align: 'right', render: r => <span style={{ color: T.text }}>{r.pct_listed_above != null ? `${r.pct_listed_above}%` : '—'}</span> },
    { key: 'r60', label: 'Avg +60 sess. (from day-1 close)', align: 'right', render: r => <span><Pct v={r.mean_ret_60d} /> <span style={{ color: T.dim, fontSize: 10 }}>n={r.n_60d}</span></span> },
  ]

  return (
    <div>
      <PageHeader code="IPO" title="IPO Monitor"
        subtitle={`open & forthcoming issues with live subscription · listing scorecard from NSE bhavcopy${data?.bhavcopy_through ? ` (through ${data.bhavcopy_through})` : ''}`}
        right={<div style={{ display: 'flex', gap: 4 }}>
          {(['Mainboard', 'SME'] as const).map(k => <Chip key={k} color={T.cyan} active={kind === k} onClick={() => setKind(k)}>{k.toUpperCase()}</Chip>)}
          <span style={{ width: 8 }} />
          {[12, 24, 60].map(m => <Chip key={m} color={T.amber} active={months === m} onClick={() => setMonths(m)}>{m}M</Chip>)}
        </div>} />
      {error && <ErrorBox error={error} />}
      {!data && !error && <Loading label="Reading NSE issues" />}
      {data && (
        <>
          <Panel source={sourceOf(checkedAt ? checkedAt.toISOString() : null, { source: 'NSE IPO data', maxAgeDays: 1, hint: 'the issue list, re-read every 20 s while the page is open' })} title="Open & forthcoming" accent={T.green} pad={0} subtitle="NSE public issues · subscription = times the shares offered to each category (QIB = institutions, NII = HNIs)"
            style={{ marginBottom: 12 }}>
            <DataTable columns={issueCols} rows={issues} rowKey={r => r.symbol} dense
              empty={`No open or forthcoming issues on NSE · checked ${checkedAt ? checkedAt.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }) : '—'} IST`} />
          </Panel>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 10, marginBottom: 12 }}>
            <Stat label={`${kind} listings · ${months}M`} value={rows.length} sub={`${priced.length} with prices`} />
            <Stat label="Median listing open" value={fmtPct(stats.medGain, 1)} color={tone(stats.medGain)} sub="opening price vs issue price" />
            <Stat label="Opened above issue" value={stats.above != null ? `${stats.above.toFixed(0)}%` : '—'} />
            <Stat label="Median now vs issue" value={fmtPct(stats.medSince, 1)} color={tone(stats.medSince)} sub={`${stats.below} trade below the issue price`} />
          </div>
          {kind === 'Mainboard' && data.buckets.length > 0 && (
            <Panel source={sourceOf(data?.bhavcopy_through ?? null, { source: 'NSE bhavcopy' })} badge="context" title="Does institutional demand show up in the listing?" accent={T.violet} pad={0} style={{ marginBottom: 12 }}
              subtitle={`by QIB subscription · ${months} months of mainboard IPOs · descriptive and in-sample, small samples: context, not a rule${data.details.running ? ` · fetching bid books ${data.details.done}/${data.details.total}` : ''}`}>
              <DataTable columns={bucketCols} rows={data.buckets} rowKey={r => r.bucket} dense />
            </Panel>
          )}
          <Panel source={sourceOf(data?.bhavcopy_through ?? null, { source: 'NSE bhavcopy' })} title={`Recent listings · ${rows.length}`} accent={T.amber} pad={0}
            subtitle="listing open / day-1 close vs the issue price · +20 / +60 sessions measured from the day-1 close (what a buyer after listing got)">
            <DataTable columns={cols} rows={rows} rowKey={r => r.symbol + r.listing_date} dense maxHeight={720} initialSort={{ key: 'date', dir: 'desc' }} empty="No listings in this window" />
            {(clean.unpriced.length > 0 || clean.entitlements.length > 0) && (
              <div data-ipo-left-out style={{ padding: '6px 10px', fontSize: 11, color: T.dim, borderTop: `1px solid ${T.border}`, lineHeight: 1.5 }}>
                {clean.unpriced.length > 0 && <>No NSE bhavcopy prices yet (left out): {clean.unpriced.join(', ')}. </>}
                {clean.entitlements.length > 0 && <>Rights entitlements / partly-paid lines, not IPOs (left out): {clean.entitlements.join(', ')}.</>}
              </div>)}
          </Panel>
        </>
      )}
    </div>
  )
}
