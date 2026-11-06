'use client'

import { apiError } from '@/lib/errors'
import { fmtSigned } from '@/lib/format'   // signed numbers with U+2212 (C1-trader-ux-18)
/**
 * MEMB · "Index members & drivers" (Bloomberg MEMB / IMAP) for NIFTY 50 / NEXT 50 / BANK / IT: every member's rebuilt
 * free-float weight, today's move, returns over 1M / 3M / YTD / 1Y, distance from its 52-week high, and P/E and
 * last-quarter growth from its NSE results filing. On top: breadth, concentration and the weight-implied P/E.
 *
 * Terminal v2 (reports/terminal_v2/PLAN.md 1.2; GO aliases DRVR / IMAP / CONTRIB): a horizon selector (1D / 5D / 1M /
 * 3M / YTD / since the last driver change) drives the PTS column from the nightly point-in-time contribution table
 * (additive points, so a horizon is a sum; the old "YTD pts" column — today's weights × YTD returns — is gone); the
 * DRIVER REGIME strip (neutral, "describes, does not predict"); the fit chip on the table header; sector contribution,
 * the monthly leaderboard and the concentration & breadth chart below. Today's live "who moved the index" stays on MOV.
 *
 * Review M46 / m027 / m029 (D-DATA, 6 Nov): the route's `tab` state greys the horizon points, sectors, concentration
 * and monthly board when the fit is degraded or the history insufficient (one note above the table, a caption on each
 * greyed panel); members' `flags` mark distorted filing figures (⚑, heuristic badge, the route's rule); the subtitle
 * names where today's explained points come from (`explained_source`: the live rebuild in the session, the stored
 * attribution after the close).
 */
import { useEffect, useMemo, useState } from 'react'
import { getIndexMemb, type IndexMemb, type IndexMembRow } from '@/lib/api'
import { BadgeChip, Chip, DataTable, ErrorBox, Loading, PageHeader, Panel, SourceChip, Stat, T, TickerLink, fmtIdx, fmtPct, fmtPx, nseStampIso, ordinal, sourceOf, type Column } from '@/components/terminal'
import type { Badge } from '@/components/terminal/source'
import { useLiveQuotes } from '@/lib/liveQuotes'
import { liveLevel } from '@/components/liveModel'
import { ConcentrationChart, DriverRegimeStrip, DriversEmpty, DriversTabNotice, FitChip, HorizonPicker, MonthlyLeaderboard, SectorContribution, TabGrey, isDriverIndex, useDrivers, useTimelines } from '@/components/drivers/DriversView'
import { HORIZON_LABEL, fmtPts, fmtShare, type Horizon } from '@/components/drivers/api'
import { flagCell, flagWords, tabView } from '@/components/drivers/driversModel'

/** The route's additive fields (D-DATA, 6 Nov) on top of lib/api's IndexMemb: per-member heuristic flags, their badge
 *  and rule, and where today's explained points come from. Optional: an older ui-api sends none of them. */
type MembRow = IndexMembRow & { flags?: string[] }
type MembExtra = { flag_badge?: Badge; flag_rule?: string; explained_source?: string }
const flagged = (r: MembRow, cell: 'pe' | 'pat' | 'rev', rule: string | undefined, body: React.ReactNode) =>
  !flagCell(r.flags, cell) ? body
    : <span data-memb-flag={cell} title={`heuristic flag: ${flagWords(r.flags).join(' · ')}${rule ? ` — ${rule}` : ''}`}
        style={{ borderBottom: `1px dotted ${T.amber}` }}>{body}<span style={{ color: T.amber, marginLeft: 3 }}>⚑</span></span>

const INDICES = ['NIFTY 50', 'NIFTY NEXT 50', 'NIFTY BANK', 'NIFTY IT'] as const
const tone = (v: number | null | undefined) => (v == null ? T.dim : v > 0 ? T.green : v < 0 ? T.red : T.muted)
const pct = (v: number | null | undefined, d = 1) => <span style={{ color: tone(v) }}>{fmtPct(v, d)}</span>

export function IndexMembers() {
  const [index, setIndex] = useState<(typeof INDICES)[number]>('NIFTY 50')
  const [d, setD] = useState<IndexMemb | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [horizon, setHorizon] = useState<Horizon>('1m')
  const drv = useDrivers(index, horizon)
  const { tl20, tl60 } = useTimelines(index)
  const ptsBy = useMemo(() => new Map((drv.data?.members ?? []).map(m => [m.symbol, m])), [drv.data])
  const hasPts = ptsBy.size > 0
  useEffect(() => {
    let live = true
    setD(null); setErr(null)
    getIndexMemb(index).then(r => { if (live) setD(r.data) }).catch(e => { if (live) setErr(apiError(e, 'members unavailable')) })
    return () => { live = false }
  }, [index])
  // live program (D12): today's move per member and the index level from the live NSE quote service (Breeze websocket,
  // the same subscription as MOV) instead of the payload's one read at load; returns / P/E / horizon points stay stored
  const memSyms = useMemo(() => (d ? [index, ...d.members.map(m => m.symbol)] : []), [d, index])
  const liveM = useLiveQuotes(memSyms, { intervalMs: 5_000 })
  const todayOf = (r: IndexMembRow): number | null => liveLevel({ last: r.close, change_pct: r.change_pct }, liveM.quotes[r.symbol]).change_pct
  const lvl = liveLevel(d ? { last: d.last, change_pct: d.change_pct } : null, liveM.quotes[index])
  const lvlRow = liveM.quotes[index]
  const lvlChange = lvl.fromService && lvlRow ? lvlRow.change ?? (lvlRow.price != null && lvlRow.prev_close != null ? lvlRow.price - lvlRow.prev_close : null) : d?.change ?? null
  const breadth = useMemo(() => {
    if (!d || !liveM.available) return null
    let up = 0, down = 0
    for (const r of d.members) { const c = todayOf(r); if (c != null) { if (c > 0) up++; else if (c < 0) down++ } }
    return { up, down }
  }, [d, liveM.available, liveM.quotes])  // eslint-disable-line react-hooks/exhaustive-deps
  const maxW = Math.max(1, ...(d?.members ?? []).map(r => r.weight_pct ?? 0))
  const ext = (d ?? {}) as MembExtra
  const tab = isDriverIndex(index) ? drv.data?.tab ?? null : null
  const tv = tabView(tab)                                      // M46: degraded / insufficient grey the horizon columns
  const greyCell = (body: React.ReactNode) => (tv.grey ? <span style={{ opacity: 0.45 }} title={tv.caption ?? undefined}>{body}</span> : body)
  const nFlagged = (d?.members ?? []).filter(r => ((r as MembRow).flags ?? []).length > 0).length
  const cols: Column<IndexMembRow>[] = [
    { key: 'sym', label: 'Stock', sort: r => r.symbol, render: r => <TickerLink symbol={r.symbol} /> },
    { key: 'w', label: 'Weight', align: 'right', sort: r => r.weight_pct ?? 0, title: 'rebuilt free-float weight: shares × price × (1 − promoter %)',
      render: r => <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, justifyContent: 'flex-end' }}>
        <span style={{ display: 'inline-block', width: 50, height: 6, background: T.border, position: 'relative' }}>
          <span style={{ position: 'absolute', right: 0, top: 0, bottom: 0, width: `${((r.weight_pct ?? 0) / maxW) * 100}%`, background: T.amber, opacity: 0.8 }} /></span>
        <span style={{ minWidth: 40 }}>{r.weight_pct?.toFixed(2)}%</span></span> },
    { key: 'px', label: 'Close', align: 'right', sort: r => r.close ?? 0, render: r => <span style={{ color: T.bright }}>{fmtPx(r.close)}</span> },
    { key: 'd', label: 'Today', align: 'right', sort: r => todayOf(r) ?? -999, render: r => {
        const info = liveM.quotes[r.symbol] ? liveM.sourceFor(r.symbol) : null
        return <span title={info ? liveM.lineFor(r.symbol) ?? undefined : `NSE heatmap at load (${d?.time ?? 'no stamp'})`}>{pct(todayOf(r), 2)}</span> } },
    // PLAN 1.2: the PTS column follows the horizon — Σ stored daily points (L × w × r) over the window, never today's
    // weights × a long return (the old YTD pts column); today's live points are on MOV
    { key: 'pts', label: `Pts · ${HORIZON_LABEL[horizon]}`, align: 'right', sort: r => ptsBy.get(r.symbol)?.points ?? -1e9,
      title: drv.data?.horizon?.from ? `index points from this stock, ${drv.data.horizon.from} → ${drv.data.horizon.to} (${drv.data.horizon.sessions} sessions), summed from the stored daily contribution table` : 'index points over the horizon, from the stored daily contribution table (backfill pending)',
      render: r => { const m = ptsBy.get(r.symbol); return m?.points == null ? <span style={{ color: T.dim }}>—</span>
        : greyCell(<span style={{ color: tv.grey ? T.muted : tone(m.points), fontWeight: 600 }} title={`weight ${m.weight_pct?.toFixed(2) ?? '—'}% (${drv.data?.weight_method?.label ?? 'rebuilt'}) · return ${fmtPct(m.ret_pct, 2)}`}>{fmtPts(m.points, 1)}</span>) } },
    { key: 'share', label: 'Share of move', align: 'right', sort: r => ptsBy.get(r.symbol)?.share_abs ?? -1, title: '|points| ÷ Σ |member points| over the horizon (arithmetic)',
      render: r => greyCell(<span style={{ color: T.muted }}>{fmtShare(ptsBy.get(r.symbol)?.share_abs, 1)}</span>) },
    { key: '1m', label: '1M', align: 'right', sort: r => r.ret_1m ?? -999, render: r => pct(r.ret_1m) },
    { key: '3m', label: '3M', align: 'right', sort: r => r.ret_3m ?? -999, render: r => pct(r.ret_3m) },
    { key: 'ytd', label: 'YTD', align: 'right', sort: r => r.ret_ytd ?? -999, render: r => pct(r.ret_ytd) },
    { key: '1y', label: '1Y', align: 'right', sort: r => r.ret_1y ?? -999, render: r => pct(r.ret_1y) },
    { key: 'hi', label: 'vs 52w high', align: 'right', sort: r => r.from_high_pct ?? -999,
      render: r => <span style={{ color: (r.from_high_pct ?? -99) >= -5 ? T.green : (r.from_high_pct ?? 0) <= -25 ? T.red : T.muted }}>{fmtPct(r.from_high_pct, 1)}</span> },
    { key: 'pe', label: 'P/E', align: 'right', sort: r => r.pe ?? 1e9, title: 'price ÷ trailing four quarters of profit (NSE results filings)',
      render: r => r.pe == null ? <span style={{ color: T.dim }}>—</span> : flagged(r, 'pe', ext.flag_rule, <span>{r.pe.toFixed(1)}×</span>) },
    { key: 'pep', label: 'P/E vs own', align: 'right', sort: r => r.pe_pctl ?? 1e9, title: "today's P/E percentile within the company's own point-in-time P/E history (FA → P/E history)",
      render: r => r.pe_pctl == null ? <span style={{ color: T.dim }}>—</span>
        : <span style={{ color: r.pe_pctl <= 20 ? T.green : r.pe_pctl >= 80 ? T.red : T.muted }}>{ordinal(r.pe_pctl)}</span> },
    { key: 'pat', label: 'Profit y/y', align: 'right', sort: r => r.pat_yoy ?? -999, title: 'last reported quarter vs the same quarter a year earlier',
      render: r => r.pat_turn ? <span style={{ color: r.pat_turn === 'to profit' ? T.green : T.red }}>{r.pat_turn}</span> : flagged(r, 'pat', ext.flag_rule, pct(r.pat_yoy, 0)) },
    { key: 'rev', label: 'Revenue y/y', align: 'right', sort: r => r.revenue_yoy ?? -999, render: r => flagged(r, 'rev', ext.flag_rule, pct(r.revenue_yoy, 0)) },
    { key: 'q', label: 'Qtr', align: 'right', render: r => <span style={{ color: T.dim, fontSize: 10 }}>{r.quarter?.slice(0, 7) ?? ''}</span> },
  ]
  const s = d?.summary
  return (
    <div>
      <PageHeader code="MEMB" title="Index members & drivers"
        subtitle="who drove the index over a horizon, weights, returns, distance from highs, P/E and growth: one row per member"
        right={<div style={{ display: 'flex', gap: 4 }}>{INDICES.map(i => <Chip key={i} color={T.amber} active={index === i} onClick={() => setIndex(i)}>{i.replace('NIFTY ', '')}</Chip>)}</div>} />
      {err && <ErrorBox error={err} />}
      {!d && !err && <Loading label="index members" />}
      {d && s && <>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))', gap: 8, marginBottom: 12 }}>
          <Stat label={index} value={fmtIdx(lvl.last)} color={tone(lvl.change_pct)}
            sub={<span>{fmtPct(lvl.change_pct, 2)} · {lvlChange != null ? `${fmtSigned(lvlChange, 1)} pts` : ''}
              {lvl.fromService && liveM.source ? <> <SourceChip info={liveM.sourceFor(index) ?? liveM.source} style={{ fontSize: 8.5 }} /></> : null}</span>} />
          <Stat label="Breadth today" value={`${breadth?.up ?? s.up} / ${breadth?.down ?? s.down}`} color={(breadth?.up ?? s.up) >= (breadth?.down ?? s.down) ? T.green : T.red} sub={`up / down of ${s.members}`} />
          <Stat label="Top 5 weight" value={`${s.top5_weight_pct}%`} color={T.amber} sub="of the index in five stocks" />
          <Stat label="Weight-implied P/E" value={s.implied_pe != null ? `${s.implied_pe}×` : '—'} color={T.text}
            sub={`from members' filings (${s.pe_coverage_pct}% of weight) · NSE publishes its own on MKT`} />
          <Stat label="Year to date" value={fmtPct(s.index_ytd_pct, 1)} color={tone(s.index_ytd_pct)}
            sub={`${s.near_high} near their 52w high · what drove it: pick YTD below`} />
        </div>
        <DriverRegimeStrip index={index} d={drv.data} tl60={tl60.data} />
        <Panel title={`${index} · ${d.members.length} members`} accent={T.amber} pad={0}
          source={liveM.available && liveM.source ? { ...liveM.source, hint: `Today column: ${liveM.source.hint ?? 'live NSE quotes'}; weights, returns, P/E and horizon points are stored (EOD)` }
            : sourceOf(nseStampIso(d.time) ?? drv.data?.as_of ?? null, { source: 'NSE', live: false, hint: drv.error })} badge={drv.data?.badges?.members ?? 'arithmetic'}
          right={<span style={{ display: 'inline-flex', gap: 8, alignItems: 'center', flexWrap: 'wrap', justifyContent: 'flex-end' }}>
            <HorizonPicker value={horizon} onChange={setHorizon} />
          </span>}
          // m029: the route says where today's explained points come from (live rebuild in the session, the stored attribution after the close)
          subtitle={`${ext.explained_source ?? 'weights rebuilt from filings (NSE does not publish live weights)'}: they explain ${fmtSigned(d.explained_points, 1)} of today's ${d.change != null ? `${fmtSigned(d.change, 1)}` : '—'} points · click a column to sort${d.missing.length ? ` · not priced: ${d.missing.join(', ')}` : ''}`}>
          {/* the fit chip on its own row under the header (in the header it squeezed the subtitle into a narrow column) */}
          {isDriverIndex(index) && <div style={{ padding: '6px 12px', borderBottom: `1px solid ${T.border}` }}><FitChip d={drv.data} /></div>}
          {isDriverIndex(index) && <DriversTabNotice d={drv.data} />}
          {!hasPts && !drv.loading && <div style={{ padding: '8px 12px', borderBottom: `1px solid ${T.border}` }}><DriversEmpty index={index} error={drv.error} payload={drv.data} /></div>}
          <DataTable columns={cols} rows={d.members} rowKey={r => r.symbol} dense initialSort={{ key: 'w', dir: 'desc' }} exportName={`MEMB_${index.replace(/ /g, '_')}_${horizon}`} />
          {nFlagged > 0 && <div data-memb-flags style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '6px 12px', borderTop: `1px solid ${T.border}`, fontSize: 10, color: T.muted }}>
            <BadgeChip badge={ext.flag_badge ?? 'heuristic'} />
            <span><span style={{ color: T.amber }}>⚑</span> {nFlagged} member{nFlagged === 1 ? '' : 's'} flagged: {ext.flag_rule ?? 'a filing figure outside the usual range: read the filing first'}</span>
          </div>}
        </Panel>
        {isDriverIndex(index) && (
          <TabGrey tab={tab}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(440px, 1fr))', gap: 12, marginTop: 12 }}>
              <SectorContribution d={drv.data} error={drv.error} />
              <ConcentrationChart index={index} tl20={tl20} />
            </div>
          </TabGrey>
        )}
        {isDriverIndex(index) && <div style={{ marginTop: 12 }}><TabGrey tab={tab}><MonthlyLeaderboard index={index} /></TabGrey></div>}
        <div style={{ fontSize: 10, color: T.dim, marginTop: 6 }}>
          Returns on split- and bonus-adjusted NSE closes (dividends excluded). P/E and growth from each company's latest
          NSE results filing (consolidated where filed). Today's move is from NSE's live index feed ({d.time ?? 'last update'}).
        </div>
      </>}
    </div>
  )
}
