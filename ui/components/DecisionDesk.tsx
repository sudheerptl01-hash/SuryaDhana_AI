'use client'

import { apiError } from '@/lib/errors'
/**
 * DecisionDesk: the monthly "what do I do" screen for the approved momentum strategy.
 *
 * Backend: GET /api/desk/status, GET /api/desk/preview, POST /api/desk/reenable
 * (services/ui-api/routers/desk.py → shared/decision_desk.py). PAPER mode: fills are
 * simulated at NSE's official opening price; nothing is sent to the broker.
 */
import { RiskChips } from '@/components/RiskChips'
import { useSurveillance } from '@/lib/useSurveillance'
import { useCallback, useEffect, useLayoutEffect, useMemo, useState } from 'react'
import { INDUSTRY_MAX_W, deskGridColumns, deskWatchLayout, hiddenColumnsCue, hiddenHeaders } from '@/components/deskLayout'
import { getDeskStatus, getDeskPreview, reenableDesk, getCrashFilter, type CrashFilter } from '@/lib/api'
import { DeskAttribution } from '@/components/drivers/DeskAttribution'
import { openTicker } from '@/lib/openTicker'
import { BasketRisk } from '@/components/BasketRisk'
import { useFinancialsLatest } from '@/lib/useFinancials'
import { daysUntil, useCorpEvents, useResultsAvoid } from '@/lib/useCorpEvents'
import {
  Btn, CHART_BOX, Chip, DataTable, Empty, EventBadge, ErrorBox, Grid, KV, Label, Loading, Notice, PageHeader, Panel, SourceChip, Stat, T,
  fmtFixed, fmtIdx, fmtInr, fmtInrPx, fmtSignedPct, sourceOf, tone, useChartSize, type Column, AvoidFlag, referenceSource } from '@/components/terminal'
import { useLiveQuotes } from '@/lib/liveQuotes'

interface Order {
  symbol: string; side: 'BUY' | 'SELL'; est_qty: number; est_price: number | null; est_value: number
  est_cost: number; reason: string; rank: number | null; sector: string; status?: string
  fill_qty?: number | null; fill_price?: number | null; fill_date?: string | null
}
interface WatchItem { symbol: string; rank: number | null; sector: string; ret6: number; ret12: number; close: number }
interface Summary {
  signal_date: string; kind: string; risk_on: boolean; nifty: number; nifty_200dma: number; exposure: number
  equity_share: number; nav_estimate: number; per_name_target: number; trades: number; est_costs: number
  rules: string; watchlist?: WatchItem[]
}
interface Plan { plan_id: string; cycle: string; kind: string; status: string; executed_date: string | null; summary: Summary; orders: Order[] }
interface NavRow { date: string; nav: number; cash: number; holdings: number; positions: number; nifty: number; peak: number; drawdown: number }
interface Position { symbol: string; qty: number; avg_cost: number; last: number | null; value: number | null; pnl_pct: number | null; since: string; sector: string }
interface Status {
  meta: { cash: number; start_capital: number; peak: number; stopped: number; last_mark: string | null; cost_profile: string; config: Record<string, any> }
  latest: NavRow | null; positions: Position[]; plans: Plan[]; nav: NavRow[]
  events: { ts: string; kind: string; message: string }[]
}

function BookChart({ nav }: { nav: NavRow[] }) {
  // drawn in CSS px (C1-17): axis text stays 9–10.5 px at any panel width
  const { ref, w, h } = useChartSize(640, 160)
  if (nav.length < 2) return <Empty title="NAV history starts with the first marked session" hint="One point per trading day after the 19:30 IST cycle." icon="◌" />
  const L = 40, R = 92, TOP = 8, B = 20
  const a = nav.map(r => r.nav / nav[0].nav), b = nav.map(r => r.nifty / nav[0].nifty)
  const lo = Math.min(...a, ...b), hi = Math.max(...a, ...b), span = hi - lo || 1
  const x = (i: number) => L + (i / (a.length - 1)) * (w - L - R)
  const y = (v: number) => TOP + (1 - (v - lo) / span) * (h - TOP - B)
  const path = (s: number[]) => s.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(' ')
  const pctOf = (v: number) => `${v >= 1 ? '+' : '−'}${Math.abs((v - 1) * 100).toFixed(1)}%`
  const ea = a[a.length - 1], eb = b[b.length - 1]
  const day = (d: string) => new Date(`${d.slice(0, 10)}T00:00:00`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })
  return (
    <div ref={ref} style={CHART_BOX}>
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ display: 'block' }} role="img" aria-label="Book vs NIFTY">
      {[lo, 1, hi].filter(v => v === 1 || Math.abs(y(v) - y(1)) > 14).map(v => (
        <g key={v}>
          <line x1={L} x2={w - R} y1={y(v)} y2={y(v)} stroke={v === 1 ? T.borderHi : T.border} strokeDasharray="4 4" />
          <text x={L - 5} y={y(v) + 3} textAnchor="end" fontSize={9} fill={T.dim} fontFamily={T.mono}>{pctOf(v)}</text>
        </g>
      ))}
      <path d={path(b)} fill="none" stroke={T.muted} strokeWidth={1.2} strokeDasharray="5 4" />
      <path d={path(a)} fill="none" stroke={T.green} strokeWidth={1.8} />
      <text x={w - R + 6} y={y(ea) + 3} fontSize={11} fill={T.green} fontFamily={T.mono}>BOOK {pctOf(ea)}</text>
      <text x={w - R + 6} y={y(eb) + (Math.abs(y(eb) - y(ea)) < 12 ? 14 : 3)} fontSize={11} fill={T.muted} fontFamily={T.mono}>NIFTY {pctOf(eb)}</text>
      <text x={L} y={h - 5} fontSize={9} fill={T.dim} fontFamily={T.mono}>{day(nav[0].date)}</text>
      <text x={w - R} y={h - 5} textAnchor="end" fontSize={9} fill={T.dim} fontFamily={T.mono}>{day(nav[nav.length - 1].date)}</text>
    </svg>
    </div>
  )
}

/** Measured width of an element (0 until the first layout pass), kept current by a ResizeObserver. */
function useWidth() {
  const [el, setEl] = useState<HTMLElement | null>(null)
  const [w, setW] = useState(0)
  useLayoutEffect(() => {
    if (!el) return
    const read = () => { const cw = Math.floor(el.getBoundingClientRect().width); setW(prev => (prev === cw ? prev : cw)) }
    read()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(read)
    ro.observe(el)
    return () => ro.disconnect()
  }, [el])
  return { ref: setEl, w }
}

/**
 * CT-03: names the watchlist columns that are out of view inside the table's own scroll box ('⇢ scroll for
 * NEXT EVENT, P/E'), so a narrow window never hides a column without saying so. Re-measured on scroll and resize.
 */
function useHiddenColumnsCue(rowsKey: string) {
  const [el, setEl] = useState<HTMLElement | null>(null)
  const [cue, setCue] = useState('')
  useEffect(() => {
    const box = el?.querySelector<HTMLElement>('.t-table > div')
    if (!box) { setCue(''); return }
    const read = () => {
      const b = box.getBoundingClientRect()
      const heads = Array.from(box.querySelectorAll<HTMLElement>('thead th')).map(th => {
        const r = th.getBoundingClientRect()
        return { label: (th.textContent ?? '').replace(/[↕▲▼]/g, '').trim().toUpperCase(), left: r.left, right: r.right }
      })
      const next = hiddenColumnsCue(hiddenHeaders(b.left, b.right, heads))
      setCue(prev => (prev === next ? prev : next))
    }
    read()
    box.addEventListener('scroll', read, { passive: true })
    const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(read)
    ro?.observe(box)
    const table = box.querySelector('table')
    if (table) ro?.observe(table)
    return () => { box.removeEventListener('scroll', read); ro?.disconnect() }
  }, [el, rowsKey])
  return { ref: setEl, cue }
}

const RULES: [string, string][] = [
  ['Rebalance', 'Monthly · signal at last close · execute at next open'],
  ['Signal', 'NSE momentum (6m & 12m return ÷ 1-yr vol)'],
  ['Universe', '300 most liquid EQ stocks · ≥ ₹20 · no ETFs'],
  ['Positions', 'Up to 20 · equal weight · keep while rank ≤ 30'],
  ['Caps', '15% per stock · 40% per NSE industry'],
  ['Crash filter', 'NIFTY < 200-DMA → liquid fund · 15% vol target'],
  ['Emergency', '−20% from peak → sell all at next open'],
]

export function DecisionDesk(_: { isDark?: boolean }) {
  const [status, setStatus] = useState<Status | null>(null)
  const [crash, setCrash] = useState<CrashFilter | null>(null)
  useEffect(() => { getCrashFilter().then(r => setCrash(r.data)).catch(() => {}) }, [])
  const [preview, setPreview] = useState<{ summary: Summary; orders: Order[] } | null>(null)
  const [loading, setLoading] = useState(true)
  const [previewing, setPreviewing] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    try { setStatus((await getDeskStatus()).data); setError(null) }
    catch (e: any) { setError(apiError(e)) }
    finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  const runPreview = async () => {
    setPreviewing(true)
    try { setPreview((await getDeskPreview()).data); setError(null) }
    catch (e: any) { setError(apiError(e)) }
    finally { setPreviewing(false) }
  }
  // Two-step, in-page confirmation (never window.confirm: inside SuryaDhana.app the dialog plugin makes it async, a
  // Promise reads as "yes", and the HARD −20% stop would clear without asking — FEATURE_PARITY.md R2).
  const [confirmReenable, setConfirmReenable] = useState(false)
  const reenable = async () => {
    setConfirmReenable(false)
    await reenableDesk(); load()
  }

  // live NSE overlay for the book (reports/live_nse): LAST / Value / P&L from the live quote service (Breeze websocket →
  // NSE ≈ 1 min → the last close; never Yahoo); the desk's own EOD marks (meta.last_mark) remain the base layer and the
  // system of record, labelled MARK EOD <date> beside the live price.
  const liveB = useLiveQuotes((status?.positions ?? []).map(p => p.symbol), { intervalMs: 3_000 })
  const livePx = (sym: string): number | null => { const q = liveB.quotes[sym.toUpperCase()]; return q && q.price != null && q.state !== 'unavailable' ? q.price : null }
  const markDay = status?.meta.last_mark ? status.meta.last_mark.slice(0, 10) : status?.latest?.date ?? null

  const latestPlan = status?.plans?.find(p => p.kind === 'REBALANCE' || p.kind === 'EMERGENCY_EXIT')
  const brief = preview ?? (latestPlan ? { summary: latestPlan.summary, orders: latestPlan.orders } : null)
  const start = status?.meta.start_capital ?? 0
  const nav = status?.latest?.nav ?? start
  const niftyRet = useMemo(() => {
    const n = status?.nav ?? []
    return n.length > 1 ? (n[n.length - 1].nifty / n[0].nifty - 1) * 100 : null
  }, [status])
  const equityShare = Number(status?.meta.config?.equity_share ?? 0.66)

  const orderCols: Column<Order>[] = [
    { key: 'side', label: 'Action', sort: o => o.side, render: o => (
      <span style={{ color: o.side === 'BUY' ? T.green : T.red, fontWeight: 700 }}>
        {o.side}{o.status && o.status !== 'PENDING' ? <span style={{ color: T.muted, fontWeight: 400 }}> · {o.status}</span> : null}
      </span>) },
    { key: 'symbol', label: 'Stock', sort: o => o.symbol, render: o => <span style={{ color: T.amber, fontWeight: 600 }}>{o.symbol}</span> },
    { key: 'rank', label: 'Rank', align: 'right', sort: o => o.rank ?? 999, render: o => o.rank ?? '—' },
    { key: 'sector', label: 'Industry', sort: o => o.sector, render: o => <span style={{ color: T.muted }}>{o.sector}</span> },
    { key: 'qty', label: 'Shares', align: 'right', sort: o => o.fill_qty ?? o.est_qty, render: o => o.fill_qty ?? o.est_qty },
    { key: 'price', label: 'Price', align: 'right', render: o => fmtInrPx(o.fill_price ?? o.est_price) },
    { key: 'value', label: 'Value', align: 'right', sort: o => o.est_value, render: o => fmtInr(o.est_value) },
    { key: 'cost', label: 'Charges', align: 'right', sort: o => o.est_cost, render: o => fmtInr(o.est_cost) },
    { key: 'reason', label: 'Why', render: o => <span style={{ color: T.muted, whiteSpace: 'normal' }}>{o.reason}</span> },
  ]
  const events = useCorpEvents()
  const avoid = useResultsAvoid()
  // context only (the Desk ranks on momentum alone): valuation and latest-quarter growth from NSE filings
  const { fin } = useFinancialsLatest((brief?.summary.watchlist ?? []).map(w => w.symbol))
  const risk = useSurveillance((brief?.summary.watchlist ?? []).map(w => w.symbol))
  // CT-03: priority order (price and the next results date before the context columns), Industry cut with an
  // ellipsis (full name on hover), so the whole table fits the default window; see components/deskLayout.ts
  const watchCols: Column<WatchItem>[] = [
    { key: 'rank', label: '#', align: 'right', width: 36, sort: w => w.rank ?? 999, render: w => <span style={{ color: T.dim }}>{w.rank}</span> },
    { key: 'symbol', label: 'Stock', sort: w => w.symbol, render: w => <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
        <span style={{ color: T.amber, fontWeight: 600 }}>{w.symbol}</span><RiskChips flags={risk[w.symbol]} max={2} /></span> },
    { key: 'sector', label: 'Industry', sort: w => w.sector, render: w => (
        <span title={w.sector} style={{ color: T.muted, display: 'inline-block', maxWidth: INDUSTRY_MAX_W, overflow: 'hidden', textOverflow: 'ellipsis',
                                        verticalAlign: 'bottom' }}>{w.sector}</span>) },
    { key: 'close', label: 'Last', align: 'right', sort: w => w.close, render: w => fmtInrPx(w.close) },
    { key: 'ret6', label: '6M', align: 'right', sort: w => w.ret6, render: w => <span style={{ color: tone(w.ret6) }}>{fmtSignedPct(w.ret6 * 100, 0)}</span> },
    { key: 'ret12', label: '12M', align: 'right', sort: w => w.ret12, render: w => <span style={{ color: tone(w.ret12) }}>{fmtSignedPct(w.ret12 * 100, 0)}</span> },
    { key: 'event', label: 'Next event', render: w => {
      const e = events.get(w.symbol)?.[0], bad = avoid.get(w.symbol)
      return <span style={{ display: 'inline-flex', gap: 4 }}>
        {bad && <AvoidFlag r={bad} />}
        {e ? <EventBadge kind={e.kind} date={e.event_date} days={daysUntil(e.event_date)} typical={e.typical_move_pct} detail={e.detail} /> : !bad && <span style={{ color: T.dim }}>—</span>}
      </span>
    } },
    { key: 'pe', label: 'P/E', align: 'right', sort: w => fin[w.symbol]?.pe ?? 1e9, title: 'context only: the Desk does not use valuation',
      render: w => fin[w.symbol]?.pe != null ? <span style={{ color: T.muted }}>{fmtFixed(fin[w.symbol].pe, 1)}×</span> : <span style={{ color: T.dim }}>{fin[w.symbol] ? '—' : '…'}</span> },
    { key: 'pat', label: 'Profit y/y', align: 'right', sort: w => fin[w.symbol]?.pat_yoy ?? -999, title: 'latest quarter vs a year ago (NSE filing)',
      render: w => { const f = fin[w.symbol]; if (!f) return <span style={{ color: T.dim }}>…</span>
        if (f.pat_yoy_turn) return <span style={{ color: f.pat_yoy_turn === 'to profit' ? T.green : T.red }}>{f.pat_yoy_turn}</span>
        return f.pat_yoy == null ? <span style={{ color: T.dim }}>—</span> : <span style={{ color: tone(f.pat_yoy) }}>{fmtSignedPct(f.pat_yoy, 0)}</span> } },
  ]
  const row = useWidth()
  const layout = deskWatchLayout(row.w)
  const watchCue = useHiddenColumnsCue(`${layout}|${brief?.summary.watchlist?.length ?? 0}`)
  const posCols: Column<Position>[] = [
    { key: 'symbol', label: 'Stock', sort: p => p.symbol, render: p => <span style={{ color: T.amber, fontWeight: 600 }}>{p.symbol}</span> },
    { key: 'qty', label: 'Shares', align: 'right', sort: p => p.qty, render: p => Math.round(p.qty) },
    { key: 'avg', label: 'Avg cost', align: 'right', render: p => fmtInrPx(p.avg_cost) },
    { key: 'last', label: 'Last', align: 'right', width: 96, sort: p => livePx(p.symbol) ?? p.last ?? 0,
      render: p => { const lp = livePx(p.symbol), px = lp ?? p.last
        const info = lp != null ? liveB.sourceFor(p.symbol) : null
        return px != null
          ? <span title={info ? `${liveB.lineFor(p.symbol) ?? ''} · desk mark ${p.last != null ? fmtInrPx(p.last) : '—'} (EOD ${markDay ?? '—'})` : `desk mark at the last close (EOD ${markDay ?? '—'})`}>
              {fmtInrPx(px)}<span data-sd-row-source={info?.state ?? 'mark'} style={{ display: 'inline-block', width: 6, height: 6, marginLeft: 5, borderRadius: 3, verticalAlign: 'middle',
                background: info?.state === 'live' ? T.green : info?.state === 'stale' ? T.amber : T.muted }} /></span>
          : <span style={{ color: T.dim }}>—</span> } },
    { key: 'value', label: 'Value', align: 'right', sort: p => p.value ?? 0,
      render: p => { const lp = livePx(p.symbol); return fmtInr(lp != null ? lp * p.qty : p.value) } },
    { key: 'pnl', label: 'P&L', align: 'right', sort: p => p.pnl_pct ?? 0,
      render: p => { const lp = livePx(p.symbol)
        const v = lp != null && p.avg_cost > 0 ? (lp / p.avg_cost - 1) * 100 : p.pnl_pct
        return <span style={{ color: tone(v) }}>{fmtSignedPct(v, 1)}</span> } },
  ]

  return (
    <div>
      <PageHeader code="DESK" title="Decision Desk"
        status={<>
          <Chip color={T.amber} active>PAPER</Chip>
          {status?.meta.stopped ? <Chip color={T.red} active>EMERGENCY STOP</Chip> : null}
        </>}
        subtitle={<>Monthly momentum · top 20 · crash filter · {Math.round(equityShare * 100)}% equity · costs {status?.meta.cost_profile ?? '—'}</>}
        right={<>
          {status?.meta.stopped
            ? (confirmReenable
                ? <ReenableConfirm onCancel={() => setConfirmReenable(false)} onConfirm={reenable} />
                : <Btn variant="danger" onClick={() => setConfirmReenable(true)}>Re-enable after review</Btn>)
            : null}
          <Btn onClick={load}>{loading ? 'Loading…' : '↻ Refresh'}</Btn>
          <Btn variant="primary" onClick={runPreview} disabled={previewing}>{previewing ? 'Computing…' : '▶ Preview now'}</Btn>
        </>} />
      {error && <div style={{ marginBottom: 10 }}><ErrorBox error={error} onRetry={load} /></div>}
      {loading && !status ? <Loading label="Loading paper book" /> : (
        <div style={{ display: 'grid', gap: 10 }}>
          <Grid cols={6}>
            <Stat label="Book value" value={fmtInr(nav)} sub={`start ${fmtInr(start)}`} accent={T.amber} />
            <Stat label="Return" value={fmtSignedPct(start ? (nav / start - 1) * 100 : null)} color={tone(nav - start)} sub="since the book opened" />
            <Stat label="NIFTY same period" value={fmtSignedPct(niftyRet)} color={tone(niftyRet)} sub="price index" />
            <Stat label="Drawdown" value={fmtSignedPct((status?.latest?.drawdown ?? 0) * 100)} color={(status?.latest?.drawdown ?? 0) < -0.1 ? T.red : T.text} sub="stop at −20%" />
            <Stat label="Liquid fund" value={fmtInr(status?.meta.cash)} sub="earns ~6%/yr (paper)" />
            <Stat label="Positions" value={status?.positions.length ?? 0} sub="max 20" />
          </Grid>

          <Panel source={sourceOf(brief?.summary.signal_date ?? null, { source: 'Desk', maxAgeDays: 35 })} title={preview ? 'Preview · if the month ended today' : 'This month’s brief'}
            subtitle={brief ? `signal ${brief.summary.signal_date} · ${brief.summary.rules}${latestPlan && !preview ? ` · ${latestPlan.status}` : ''}` : undefined}
            right={brief ? <Label>{brief.summary.trades} trades · charges {fmtInr(brief.summary.est_costs)}</Label> : undefined}>
            {!brief ? (
              <Empty title="No brief yet this month"
                hint="The brief is created after the last trading day of the month (19:30 IST) and executes at the next session’s open. Press PREVIEW NOW to see what it would say today." />
            ) : (
              <div style={{ display: 'grid', gap: 10 }}>
                <Notice color={brief.summary.risk_on ? T.green : T.amber}>
                  {brief.summary.risk_on
                    ? <>CRASH FILTER OFF: NIFTY {fmtIdx(brief.summary.nifty)} is above its 200-day average ({fmtIdx(brief.summary.nifty_200dma)}). Invest ~{fmtInr(brief.summary.per_name_target)} per new stock at {Math.round(brief.summary.exposure * 100)}% exposure.</>
                    : <>CRASH FILTER ON: NIFTY {fmtIdx(brief.summary.nifty)} is below its 200-day average ({fmtIdx(brief.summary.nifty_200dma)}). <b style={{ color: T.amber }}>Stay in the liquid fund.</b> The watchlist shows what it will buy once NIFTY recovers.</>}
                  {crash && (
                    <div style={{ marginTop: 4, color: T.muted }}>
                      Today ({crash.date}): NIFTY {fmtIdx(crash.nifty)} vs 200-DMA {fmtIdx(crash.sma200)}
                      {crash.risk_on ? <span style={{ color: T.green }}> · above it now: the next signal ({crash.next_signal_date}) would invest</span>
                                     : <> · needs <b style={{ color: T.amber }}>+{crash.move_needed_pct.toFixed(1)}%</b> by the next signal ({crash.next_signal_date}) to invest</>}
                    </div>
                  )}
                </Notice>
                <DataTable columns={orderCols} rows={brief.orders} rowKey={o => o.side + o.symbol} onRowClick={o => openTicker(o.symbol)}
                  empty={<Empty title="No trades this month" icon="✓" />} />
                <div style={{ fontSize: 10, color: T.muted }}>
                  Executes at the next session’s open · paper fill at NSE’s official opening price · charges: real NSE costs and taxes ({status?.meta.cost_profile ?? 'broker profile'})
                </div>
              </div>
            )}
          </Panel>

          {/* CT-03: side by side only when the whole watchlist fits next to the side panels; otherwise stacked */}
          <div ref={row.ref} data-desk-layout={layout} style={{ display: 'grid', gridTemplateColumns: deskGridColumns(layout), gap: 10 }}>
            <Panel source={sourceOf(brief?.summary.signal_date ?? null, { source: 'Desk', maxAgeDays: 35 })} title="Momentum watchlist" subtitle="top 20 within the 300 most liquid NSE stocks" pad={0}
              right={watchCue.cue ? <span data-testid="watch-hidden-cue" style={{ fontSize: 10, color: T.amber, fontFamily: T.mono }}>{watchCue.cue}</span> : undefined}>
              {brief?.summary.watchlist?.length
                ? <div ref={watchCue.ref}><DataTable columns={watchCols} rows={brief.summary.watchlist} rowKey={w => w.symbol} dense maxHeight={420} onRowClick={w => openTicker(w.symbol)} /></div>
                : <Empty title="Run a preview to rank the universe" hint="PREVIEW NOW computes today’s ranking (~1 min cold, seconds when warm)." />}
            </Panel>
            <div style={{ display: 'grid', gap: 10, alignContent: 'start',
                          gridTemplateColumns: layout === 'stacked' ? 'minmax(0, 1fr) minmax(0, 1fr)' : 'minmax(0, 1fr)' }}>
              {/* the side column is narrow: the legend sits in the body so the header keeps one line with its chip */}
              <Panel title="Book vs NIFTY · NAV" source={sourceOf(status?.latest?.date ?? null, { source: 'paper ledger' })}>
                <div style={{ fontSize: 10, color: T.muted, marginBottom: 4 }}>green = book · dashed = NIFTY · arithmetic</div>
                <BookChart nav={status?.nav ?? []} />
              </Panel>
              <Panel source={referenceSource('owner-approved Desk rules (shared/momentum.py)')} title="Rules" subtitle="owner-approved 2026-09-27">
                <KV items={RULES} />
              </Panel>
            </div>
          </div>
          {brief?.summary.watchlist?.length ? (
            <BasketRisk title="Watchlist risk · what the Desk would hold" symbols={brief.summary.watchlist.map(w => w.symbol)}
              industries={Object.fromEntries(brief.summary.watchlist.map(w => [w.symbol, w.sector]))}
              capPct={Math.round(Number(status?.meta.config?.sector_cap ?? 0.4) * 100)} />
          ) : null}

          {/* terminal v2 PLAN 1.2: real lots × stored closes beside NIFTY's drivers; honest in cash ("liquid fund since …") */}
          <DeskAttribution />

          <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', gap: 10 }}>
            <Panel title="Holdings" pad={0}
              right={status?.positions.length && liveB.available ? <span style={{ fontSize: 10, color: T.dim, fontFamily: T.mono }} title="the Desk's own marks (system of record) are end of day">MARK EOD {markDay ?? '—'}</span> : undefined}
              source={status?.positions.length && liveB.available && liveB.source ? liveB.source
                : { state: 'delayed', source: 'Desk marks', asOf: markDay,
                    hint: `desk marks at last close${markDay ? ` (${markDay})` : ''}${liveB.status === 'missing' ? '; live NSE quote service not deployed' : liveB.status === 'error' ? '; live NSE quote service not answering' : ''}` }}>
              {status?.positions.length
                ? <DataTable columns={posCols} rows={status.positions} rowKey={p => p.symbol} dense onRowClick={p => openTicker(p.symbol)} />
                : <Empty title={`All in the liquid fund (${fmtInr(status?.meta.cash)})`} icon="◇" />}
            </Panel>
            <Panel source={sourceOf(status?.events?.[0]?.ts ?? null, { source: 'Desk ledger', maxAgeDays: null })} title="Activity" pad={0}>
              <div style={{ maxHeight: 260, overflow: 'auto' }}>
                {(status?.events ?? []).map((e, i) => (
                  <div key={i} style={{ display: 'grid', gridTemplateColumns: '120px 90px 1fr', gap: 8, padding: '6px 12px',
                                        borderBottom: `1px solid ${T.border}`, fontSize: 11 }}>
                    <span style={{ color: T.dim }}>{e.ts.slice(0, 16).replace('T', ' ')}</span>
                    <span style={{ color: e.kind === 'EMERGENCY' ? T.red : e.kind === 'FILL' ? T.green : T.cyan }}>{e.kind}</span>
                    <span style={{ color: T.text }}>{e.message}</span>
                  </div>
                ))}
                {!status?.events?.length && <Empty title="No activity yet" />}
              </div>
            </Panel>
          </div>
        </div>
      )}
    </div>
  )
}

/** Inline confirmation for clearing the HARD −20% emergency stop: Cancel has focus, Esc cancels, nothing is sent
 *  until the second, explicit click. Same behaviour in a browser and in the desktop app. */
function ReenableConfirm({ onCancel, onConfirm }: { onCancel: () => void; onConfirm: () => void }) {
  const [el, setEl] = useState<HTMLSpanElement | null>(null)
  // focus Cancel once, when the confirmation opens (not on every DESK re-render: the inline onCancel changes each
  // render and used to pull focus back here, e.g. away from the GO bar, on every status refresh)
  useEffect(() => { el?.querySelector<HTMLButtonElement>('[data-role="cancel-wrap"] button')?.focus() }, [el])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { e.preventDefault(); onCancel() } }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [el, onCancel])
  return (
    <span ref={setEl} role="alertdialog" aria-label="Clear the emergency stop?"
      style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '2px 6px', border: `1px solid ${T.red}`,
               fontFamily: T.mono, fontSize: 10, color: T.bright }}>
      <span>Clear the emergency stop? Only after reviewing why the book fell 20%.</span>
      <span data-role="cancel-wrap" onClickCapture={onCancel}>
        <Btn size="sm" title="Keep the emergency stop (Esc)">Cancel</Btn>
      </span>
      <Btn size="sm" variant="danger" onClick={onConfirm} title="Clears the stop and resets the drawdown peak">Clear emergency stop</Btn>
    </span>
  )
}
