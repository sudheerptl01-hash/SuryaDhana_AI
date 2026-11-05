'use client'

import { apiError } from '@/lib/errors'
import { fmtSigned } from '@/lib/format'   // signed numbers with U+2212 (C1-trader-ux-18)
/**
 * MEMB · index members (Bloomberg MEMB) for NIFTY 50 / NEXT 50 / BANK / IT: every member's rebuilt free-float weight,
 * today's move and index points, returns over 1M / 3M / YTD / 1Y, distance from its 52-week high, and P/E and
 * last-quarter growth from its NSE results filing. On top: breadth, concentration and the weight-implied P/E.
 */
import { useEffect, useState } from 'react'
import { getIndexMemb, type IndexMemb, type IndexMembRow } from '@/lib/api'
import { Chip, DataTable, ErrorBox, Loading, PageHeader, Panel, Stat, T, TickerLink, fmtIdx, fmtPct, fmtPx, ordinal, type Column } from '@/components/terminal'

const INDICES = ['NIFTY 50', 'NIFTY NEXT 50', 'NIFTY BANK', 'NIFTY IT'] as const
const tone = (v: number | null | undefined) => (v == null ? T.dim : v > 0 ? T.green : v < 0 ? T.red : T.muted)
const pct = (v: number | null | undefined, d = 1) => <span style={{ color: tone(v) }}>{fmtPct(v, d)}</span>

export function IndexMembers() {
  const [index, setIndex] = useState<(typeof INDICES)[number]>('NIFTY 50')
  const [d, setD] = useState<IndexMemb | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    setD(null); setErr(null)
    getIndexMemb(index).then(r => { if (live) setD(r.data) }).catch(e => { if (live) setErr(apiError(e, 'members unavailable')) })
    return () => { live = false }
  }, [index])
  const maxW = Math.max(1, ...(d?.members ?? []).map(r => r.weight_pct ?? 0))
  const cols: Column<IndexMembRow>[] = [
    { key: 'sym', label: 'Stock', sort: r => r.symbol, render: r => <TickerLink symbol={r.symbol} /> },
    { key: 'w', label: 'Weight', align: 'right', sort: r => r.weight_pct ?? 0, title: 'rebuilt free-float weight: shares × price × (1 − promoter %)',
      render: r => <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, justifyContent: 'flex-end' }}>
        <span style={{ display: 'inline-block', width: 50, height: 6, background: T.border, position: 'relative' }}>
          <span style={{ position: 'absolute', right: 0, top: 0, bottom: 0, width: `${((r.weight_pct ?? 0) / maxW) * 100}%`, background: T.amber, opacity: 0.8 }} /></span>
        <span style={{ minWidth: 40 }}>{r.weight_pct?.toFixed(2)}%</span></span> },
    { key: 'px', label: 'Close', align: 'right', sort: r => r.close ?? 0, render: r => <span style={{ color: T.bright }}>{fmtPx(r.close)}</span> },
    { key: 'd', label: 'Today', align: 'right', sort: r => r.change_pct ?? -999, render: r => pct(r.change_pct, 2) },
    { key: 'pts', label: 'Pts', align: 'right', sort: r => r.points ?? -999, title: 'index points from this stock today',
      render: r => <span style={{ color: tone(r.points), fontWeight: 600 }}>{r.points == null ? '—' : `${fmtSigned(r.points, 1)}`}</span> },
    { key: '1m', label: '1M', align: 'right', sort: r => r.ret_1m ?? -999, render: r => pct(r.ret_1m) },
    { key: '3m', label: '3M', align: 'right', sort: r => r.ret_3m ?? -999, render: r => pct(r.ret_3m) },
    { key: 'ytd', label: 'YTD', align: 'right', sort: r => r.ret_ytd ?? -999, render: r => pct(r.ret_ytd) },
    { key: 'ytdc', label: 'YTD pts', align: 'right', sort: r => r.ytd_contrib_pp ?? -999, title: "contribution to the index's year-to-date move, in percentage points (weight × YTD return)",
      render: r => <span style={{ color: tone(r.ytd_contrib_pp) }}>{r.ytd_contrib_pp == null ? '—' : `${fmtSigned(r.ytd_contrib_pp, 2)}`}</span> },
    { key: '1y', label: '1Y', align: 'right', sort: r => r.ret_1y ?? -999, render: r => pct(r.ret_1y) },
    { key: 'hi', label: 'vs 52w high', align: 'right', sort: r => r.from_high_pct ?? -999,
      render: r => <span style={{ color: (r.from_high_pct ?? -99) >= -5 ? T.green : (r.from_high_pct ?? 0) <= -25 ? T.red : T.muted }}>{fmtPct(r.from_high_pct, 1)}</span> },
    { key: 'pe', label: 'P/E', align: 'right', sort: r => r.pe ?? 1e9, title: 'price ÷ trailing four quarters of profit (NSE results filings)',
      render: r => r.pe == null ? <span style={{ color: T.dim }}>—</span> : <span>{r.pe.toFixed(1)}×</span> },
    { key: 'pep', label: 'P/E vs own', align: 'right', sort: r => r.pe_pctl ?? 1e9, title: "today's P/E percentile within the company's own point-in-time P/E history (FA → P/E history)",
      render: r => r.pe_pctl == null ? <span style={{ color: T.dim }}>—</span>
        : <span style={{ color: r.pe_pctl <= 20 ? T.green : r.pe_pctl >= 80 ? T.red : T.muted }}>{ordinal(r.pe_pctl)}</span> },
    { key: 'pat', label: 'Profit y/y', align: 'right', sort: r => r.pat_yoy ?? -999, title: 'last reported quarter vs the same quarter a year earlier',
      render: r => r.pat_turn ? <span style={{ color: r.pat_turn === 'to profit' ? T.green : T.red }}>{r.pat_turn}</span> : pct(r.pat_yoy, 0) },
    { key: 'rev', label: 'Revenue y/y', align: 'right', sort: r => r.revenue_yoy ?? -999, render: r => pct(r.revenue_yoy, 0) },
    { key: 'q', label: 'Qtr', align: 'right', render: r => <span style={{ color: T.dim, fontSize: 10 }}>{r.quarter?.slice(0, 7) ?? ''}</span> },
  ]
  const s = d?.summary
  return (
    <div>
      <PageHeader code="MEMB" title="Index members"
        subtitle="weights, who moved the index, returns, distance from highs, P/E and growth: one row per member"
        right={<div style={{ display: 'flex', gap: 4 }}>{INDICES.map(i => <Chip key={i} color={T.amber} active={index === i} onClick={() => setIndex(i)}>{i.replace('NIFTY ', '')}</Chip>)}</div>} />
      {err && <ErrorBox error={err} />}
      {!d && !err && <Loading label="index members" />}
      {d && s && <>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 8, marginBottom: 12 }}>
          <Stat label={index} value={fmtIdx(d.last)} color={tone(d.change_pct)}
            sub={`${fmtPct(d.change_pct, 2)} · ${d.change != null ? `${fmtSigned(d.change, 1)} pts` : ''}`} />
          <Stat label="Breadth today" value={`${s.up} / ${s.down}`} color={s.up >= s.down ? T.green : T.red} sub={`up / down of ${s.members}`} />
          <Stat label="Top 5 weight" value={`${s.top5_weight_pct}%`} color={T.amber} sub="of the index in five stocks" />
          <Stat label="Weight-implied P/E" value={s.implied_pe != null ? `${s.implied_pe}×` : '—'} color={T.text}
            sub={`from members' filings (${s.pe_coverage_pct}% of weight) · NSE publishes its own on MKT`} />
          <Stat label="Year to date" value={s.index_ytd_pct != null ? fmtPct(s.index_ytd_pct, 1) : fmtPct(s.ytd_explained_pct, 1)} color={tone(s.index_ytd_pct ?? s.ytd_explained_pct)}
            sub={`today's members × weights explain ${fmtPct(s.ytd_explained_pct, 1)} (members and weights change during the year) · ${s.near_high} near their 52w high`} />
        </div>
        <Panel title={`${index} · ${d.members.length} members`} accent={T.amber} pad={0}
          subtitle={`weights rebuilt from filings (NSE does not publish live weights): they explain ${fmtSigned(d.explained_points, 1)} of today's ${d.change != null ? `${fmtSigned(d.change, 1)}` : '—'} points · click a column to sort${d.missing.length ? ` · not priced: ${d.missing.join(', ')}` : ''}`}>
          <DataTable columns={cols} rows={d.members} rowKey={r => r.symbol} dense initialSort={{ key: 'w', dir: 'desc' }} exportName={`MEMB_${index.replace(/ /g, '_')}`} />
        </Panel>
        <div style={{ fontSize: 10, color: T.dim, marginTop: 6 }}>
          Returns on split- and bonus-adjusted NSE closes (dividends excluded). P/E and growth from each company's latest
          NSE results filing (consolidated where filed). Today's move is from NSE's live index feed ({d.time ?? 'last update'}).
        </div>
      </>}
    </div>
  )
}
