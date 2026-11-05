'use client'

import { apiError } from '@/lib/errors'
import { fmtSigned } from '@/lib/format'   // signed numbers with U+2212 (C1-trader-ux-18)
/**
 * Corporate calendar (EVTS) — results, dividends, splits, bonuses, rights, buybacks for NSE stocks.
 *   1. Your stocks: events for what you hold (ICICI), what the Desk holds, your watchlist and pins.
 *   2. Five-week calendar: busiest names per day; click a day to filter the list.
 *   3. Event list: filter by kind, liquidity and text; rows open the stock.
 * Data: /api/market/events ← data-service /db/events (nse_events table, refreshed by the EOD pipeline).
 */
import { useFinancialsLatest } from '@/lib/useFinancials'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { getDeskStatus, getMarketEvents, getOpenPositions, getRecentResults, getResultsReacting, type ReactingResult, getFundamentalsScreen, type ScreenRow, type CorpEvent, type RecentResult, getAnnouncementsCore, heldSymbols, getEcoCalendar, type EcoEvent } from '@/lib/api'
import { ECO_KINDS } from '@/components/EconomicCalendar'
import { ResultsImpliedMoves } from '@/components/ResultsImpliedMoves'
import { useWatchlist } from '@/context/AppContext'
import { usePins } from '@/lib/pins'
import { Chip, DataTable, ErrorBox, Input, Loading, PageHeader, Panel, T, TickerLink, type Column, AvoidFlag, fiscalQuarter, fmtPct, median, sourceOf, undatedSource } from '@/components/terminal'
import { CrushLedger } from '@/components/vol/CrushLedger'

const KIND_COLOR: Record<string, string> = {
  RESULTS: T.amber, DIVIDEND: T.green, BONUS: T.cyan, SPLIT: T.cyan, RIGHTS: T.violet, BUYBACK: T.green,
  'FUND RAISE': T.violet, 'M&A': T.red, AGM: T.muted, OTHER: T.dim,
}
const KIND_ORDER = ['RESULTS', 'DIVIDEND', 'BONUS', 'SPLIT', 'BUYBACK', 'RIGHTS', 'FUND RAISE', 'M&A', 'AGM', 'OTHER']
const LIQUID_CR = 5

type Owner = 'HELD' | 'DESK' | 'WATCH' | 'PIN'
const OWNER_COLOR: Record<Owner, string> = { HELD: T.green, DESK: T.amber, WATCH: T.cyan, PIN: T.violet }

const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
const parse = (s: string) => new Date(`${s}T00:00:00`)
const fmtDay = (s: string) => parse(s).toLocaleDateString('en-IN', { weekday: 'short', day: '2-digit', month: 'short' })
function until(s: string): { text: string; color: string } {
  const today = parse(iso(new Date()))
  const d = Math.round((parse(s).getTime() - today.getTime()) / 86_400_000)
  if (d === 0) return { text: 'TODAY', color: T.amber }
  if (d === 1) return { text: 'tomorrow', color: T.amber }
  if (d < 0) return { text: `${-d}d ago`, color: T.dim }
  return { text: `in ${d}d`, color: d <= 7 ? T.text : T.muted }
}

function KindChip({ kind }: { kind: string }) {
  const c = KIND_COLOR[kind] ?? T.muted
  return <span style={{ fontFamily: T.mono, fontSize: 9.5, fontWeight: 700, letterSpacing: .8, color: c,
                        border: `1px solid ${c}55`, padding: '1px 5px', whiteSpace: 'nowrap' }}>{kind}</span>
}

export function EventCalendar({ onSelectTicker }: { onSelectTicker: (s: string) => void }) {
  const [rows, setRows] = useState<CorpEvent[] | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [kind, setKind] = useState<string | null>(null)
  const [day, setDay] = useState<string | null>(null)
  const [liquid, setLiquid] = useState(true)
  const [q, setQ] = useState('')
  const [held, setHeld] = useState<string[]>([])
  const [desk, setDesk] = useState<string[]>([])
  const [brokerNote, setBrokerNote] = useState<string | null>(null)
  const [recent, setRecent] = useState<RecentResult[] | null>(null)
  const { watchlist } = useWatchlist()
  const { pins } = usePins()

  const load = useCallback(async () => {
    try {
      const r = (await getMarketEvents()).data
      setRows(r.rows); setRefreshing(r.refreshing); setError(null)
      if (r.refreshing) setTimeout(load, 15_000)           // first pull of the day: pick up the result
    } catch (e: any) { setError(apiError(e, 'Calendar unavailable')) }
  }, [])
  useEffect(() => { load() }, [load])
  useEffect(() => {
    getOpenPositions().then(r => {
      if (r.data?.connected === false) setBrokerNote(r.data?.last_known
        ? `ICICI not connected: using your last known holdings (${String(r.data.last_known.as_of).slice(0, 16).replace('T', ' ')})`
        : 'ICICI not connected: broker holdings not included')
      setHeld(heldSymbols(r.data))
    }).catch(() => setBrokerNote('ICICI unavailable: broker holdings not included'))
    getDeskStatus().then(r => setDesk((r.data?.positions ?? []).map((p: any) => String(p.symbol).toUpperCase()))).catch(() => {})
    getRecentResults(10).then(r => setRecent(r.data.rows)).catch(() => setRecent([]))
  }, [])
  // earnings season so far: every company whose newest-quarter filing has been read (FA cache)
  const [season, setSeason] = useState<ScreenRow[] | null>(null)
  useEffect(() => { getFundamentalsScreen().then(r => setSeason(r.data.rows)).catch(() => setSeason([])) }, [])
  const [eco, setEco] = useState<EcoEvent[]>([])
  useEffect(() => { getEcoCalendar(7, 40).then(r => setEco(r.data.events)).catch(() => setEco([])) }, [])
  const ecoByDay = useMemo(() => {
    const m = new Map<string, EcoEvent[]>()
    for (const e of eco) m.set(e.date, [...(m.get(e.date) ?? []), e])
    return m
  }, [eco])
  // results filed since the last close, priced live (refreshed every 2 min)
  const [reacting, setReacting] = useState<{ rows: ReactingResult[]; since: string; phase?: string } | null>(null)
  useEffect(() => {
    const get = () => getResultsReacting().then(r => setReacting(r.data)).catch(() => {})
    get(); const iv = setInterval(get, 120_000); return () => clearInterval(iv)
  }, [])
  // results filed with NSE today (live announcements): ✓ on today's RESULTS rows before the nightly capture
  const [filedToday, setFiledToday] = useState<Map<string, string>>(new Map())
  useEffect(() => {
    const get = () => getAnnouncementsCore().then(r => {
      const m = new Map<string, string>()
      for (const f of r.data.items) if (f.category === 'results' && !m.has(f.symbol)) m.set(f.symbol, (f.time ?? '').slice(11, 16))
      setFiledToday(m)
    }).catch(() => {})
    get(); const iv = setInterval(get, 120_000); return () => clearInterval(iv)
  }, [])

  const owners = useMemo(() => {
    const m = new Map<string, Owner[]>()
    const add = (s: string, o: Owner) => m.set(s, [...(m.get(s) ?? []).filter(x => x !== o), o])
    held.forEach(s => add(s, 'HELD'))
    desk.forEach(s => add(s, 'DESK'))
    watchlist.forEach(s => add(s.toUpperCase().replace(/\.NS$/, ''), 'WATCH'))
    Object.values(pins).forEach(p => { const sym = p.pick.symbol; if (sym?.region === 'IN') add(sym.base.toUpperCase(), 'PIN') })
    return m
  }, [held, desk, watchlist, pins])

  const today = iso(new Date())
  const mine = useMemo(() => (rows ?? []).filter(r => owners.has(r.symbol) && r.event_date >= today), [rows, owners, today])

  const filtered = useMemo(() => (rows ?? []).filter(r =>
    (!kind || r.kind === kind || (r.tags ?? '').split(',').includes(kind)) &&
    (!day || r.event_date === day) &&
    (!liquid || (r.turnover_cr ?? 0) >= LIQUID_CR || owners.has(r.symbol)) &&
    (!q.trim() || `${r.symbol} ${r.company ?? ''} ${r.detail ?? ''}`.toLowerCase().includes(q.trim().toLowerCase()))
  ), [rows, kind, day, liquid, q, owners])

  // Five weeks of weekdays from this week's Monday
  const weeks = useMemo(() => {
    const now = parse(today)
    const monday = new Date(now); monday.setDate(now.getDate() - ((now.getDay() + 6) % 7))
    return Array.from({ length: 5 }, (_, w) => Array.from({ length: 5 }, (_, d) => {
      const x = new Date(monday); x.setDate(monday.getDate() + w * 7 + d); return iso(x)
    }))
  }, [today])
  const byDay = useMemo(() => {
    const m = new Map<string, CorpEvent[]>()
    for (const r of rows ?? []) {
      if (liquid && (r.turnover_cr ?? 0) < LIQUID_CR && !owners.has(r.symbol)) continue
      if (kind && r.kind !== kind && !(r.tags ?? '').split(',').includes(kind)) continue
      m.set(r.event_date, [...(m.get(r.event_date) ?? []), r])
    }
    return m
  }, [rows, liquid, kind, owners])
  const kindCounts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const r of rows ?? []) if (r.event_date >= today && (!liquid || (r.turnover_cr ?? 0) >= LIQUID_CR)) c[r.kind] = (c[r.kind] ?? 0) + 1
    return c
  }, [rows, liquid, today])

  // last reported quarter for each company in the calendar (cache only: a long calendar must not queue hundreds of reads)
  const { fin: lastQ } = useFinancialsLatest([...new Set([...(rows ?? []).map(r => r.symbol)])], { prefetch: false })
  const cols: Column<CorpEvent>[] = [
    { key: 'event_date', label: 'Date', sort: r => r.event_date, render: r => {
      const u = until(r.event_date)
      return <span style={{ whiteSpace: 'nowrap' }}><span style={{ color: r.event_date < today ? T.dim : T.text }}>{fmtDay(r.event_date)}</span>
        <span style={{ color: u.color, fontSize: 10, marginLeft: 6 }}>{u.text}</span></span>
    } },
    { key: 'symbol', label: 'Stock', sort: r => r.symbol, render: r => (
      <span style={{ display: 'inline-flex', gap: 5, alignItems: 'center' }}>
        <span style={{ color: T.amber, fontWeight: 600 }}>{r.symbol}</span>
        {(owners.get(r.symbol) ?? []).map(o => <span key={o} style={{ fontSize: 9, color: OWNER_COLOR[o], border: `1px solid ${OWNER_COLOR[o]}66`, padding: '0 3px' }}>{o}</span>)}
      </span>) },
    { key: 'company', label: 'Company', render: r => <span style={{ color: T.muted }}>{r.company ?? '—'}</span> },
    { key: 'kind', label: 'Event', sort: r => KIND_ORDER.indexOf(r.kind), render: r => (
      <span style={{ display: 'inline-flex', gap: 4 }}>
        <KindChip kind={r.kind} />
        {(r.tags ?? '').split(',').filter(t => t && t !== r.kind).map(t => <KindChip key={t} kind={t} />)}
        {r.event_date === today && filedToday.has(r.symbol) && (r.kind === 'RESULTS' || (r.tags ?? '').includes('RESULTS')) && (
          <span title="results filed with NSE today (live announcements)" style={{ fontSize: 9.5, color: T.green, border: `1px solid ${T.green}66`, padding: '0 4px' }}>
            ✓ FILED {filedToday.get(r.symbol)}</span>)}
      </span>) },
    { key: 'detail', label: 'Detail', render: r => (
      <span title={r.detail ?? ''} style={{ display: 'inline-block', maxWidth: 420, overflow: 'hidden', textOverflow: 'ellipsis',
                                            whiteSpace: 'nowrap', verticalAlign: 'bottom', color: T.text }}>
        {r.source === 'action' ? `${r.detail ?? ''}${r.record_date ? ` · record ${fmtDay(r.record_date)}` : ''}` : (r.purpose ?? r.detail ?? '—')}
      </span>) },
    { key: 'typical', label: 'Typical move', align: 'right', sort: r => r.typical_move_pct ?? -1,
      render: r => r.typical_move_pct != null
        ? <span title={`Average absolute move on the last ${r.typical_quarters} results`} style={{ color: r.typical_move_pct >= 5 ? T.amber : T.muted }}>±{r.typical_move_pct.toFixed(1)}%</span>
        : <span style={{ color: T.dim }}>—</span> },
    { key: 'lastq', label: 'Last quarter', align: 'right', sort: r => lastQ[r.symbol]?.pat_yoy ?? -999,
      title: "the company's previous results (from its NSE filing): profit vs a year ago · P/E",
      render: r => { const f = lastQ[r.symbol]; if (!f) return <span style={{ color: T.dim }}>—</span>
        return <span style={{ fontSize: 10.5 }}>{f.pat_yoy_turn ? <span style={{ color: f.pat_yoy_turn === 'to profit' ? T.green : T.red }}>{f.pat_yoy_turn}</span>
          : <span style={{ color: f.pat_yoy == null ? T.dim : f.pat_yoy >= 0 ? T.green : T.red }}>{f.pat_yoy == null ? '—' : `${fmtSigned(f.pat_yoy, 0)}%`}</span>}
          {f.pe != null && <span style={{ color: T.dim }}> · {f.pe.toFixed(0)}×</span>}</span> } },
    { key: 'turnover_cr', label: '₹ cr/day', align: 'right', sort: r => r.turnover_cr ?? -1,
      render: r => <span style={{ color: T.muted }}>{r.turnover_cr != null ? r.turnover_cr.toLocaleString('en-IN', { maximumFractionDigits: r.turnover_cr < 10 ? 1 : 0 }) : '—'}</span> },
    { key: 'close', label: 'Close', align: 'right', render: r => r.close != null ? r.close.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—' },
    { key: 'url', label: '', render: r => r.url
      ? <a href={r.url} target="_blank" rel="noreferrer" onClick={e => e.stopPropagation()} style={{ color: T.cyan, fontSize: 10, textDecoration: 'none' }}>FILING ↗</a>
      : null },
  ]

  if (error && !rows) return <div><PageHeader code="EVTS" title="Corporate Calendar" /><ErrorBox error={error} onRetry={load} /></div>
  if (!rows) return <div><PageHeader code="EVTS" title="Corporate Calendar" /><Loading label="Reading NSE calendar" /></div>

  return (
    <div>
      <PageHeader code="EVTS" title="Corporate Calendar"
        subtitle={`NSE event calendar · board meetings · corporate actions · ${rows.filter(r => r.event_date >= today).length} upcoming`}
        status={refreshing ? <Chip color={T.cyan} active>UPDATING FROM NSE…</Chip> : undefined}
        right={<div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <Chip color={T.green} active={liquid} onClick={() => setLiquid(v => !v)} title={`Only stocks trading ≥ ₹${LIQUID_CR} cr a day (your stocks always show)`}>
            {liquid ? '✓ ' : ''}LIQUID ≥ ₹{LIQUID_CR} CR</Chip>
          <Chip color={T.amber} onClick={load}>↻ REFRESH</Chip>
        </div>} />

      <div style={{ display: 'grid', gap: 12 }}>
        <Panel source={undatedSource('NSE calendar', brokerNote)} title="Your stocks" accent={T.green}
          subtitle={`ICICI holdings · Desk · watchlist · pins — ${owners.size} tracked${brokerNote ? ` · ${brokerNote}` : ''}`} pad={mine.length ? 0 : 12}>
          {mine.length
            ? <DataTable columns={cols} rows={mine} rowKey={r => `${r.symbol}-${r.event_date}-${r.kind}`} dense onRowClick={r => onSelectTicker(r.symbol)} />
            : <div style={{ fontSize: 11.5, color: T.muted, lineHeight: 1.6 }}>
                No announced events for your {owners.size} tracked stocks in the next 60 days.
                {owners.size === 0 && ' Pin stocks or add them to the watchlist to track their results and ex-dates here.'}
              </div>}
        </Panel>

        {reacting && reacting.rows.length > 0 && (
          <Panel source={sourceOf(reacting.since ?? null, { source: 'NSE results', hint: reacting.phase === 'session' ? "today's moves from NSE's heatmap (about 1 min behind) and the quotes route for the other filers: not a live feed" : null })} badge="context" title={reacting.phase === 'session' ? 'Reacting today · live' : reacting.phase === 'preopen' ? 'Results · pre-open auction' : 'Results since the last close · react at 09:15'} accent={T.violet} pad={0}
            subtitle={`results filed since ${reacting.since} · what the numbers said (revenue / profit vs a year ago; … = still reading the filing; hover for why a figure is missing) and today's move vs the stock's average results-day move · the scoreboard below fills in tonight`}>
            <DataTable<ReactingResult> dense maxHeight={300} rowKey={r => r.symbol} onRowClick={r => onSelectTicker(r.symbol)}
              initialSort={{ key: 'size', dir: 'desc' }} rows={reacting.rows}
              columns={[
                { key: 'symbol', label: 'Stock', sort: r => r.symbol, render: r => <><TickerLink symbol={r.symbol} />{owners.has(r.symbol) && <span style={{ color: T.green, fontSize: 10 }}> ● yours</span>}</> },
                { key: 'filed', label: 'Filed', sort: r => r.filed_at, render: r => <span style={{ color: T.muted }}>{r.filed_at.slice(5, 16)}</span> },
                { key: 'rev', label: 'Revenue YoY', align: 'right', sort: r => r.revenue_yoy ?? -999, title: 'from the filing (XBRL), same quarter a year earlier',
                  render: r => r.revenue_yoy != null ? <span style={{ color: r.revenue_yoy >= 0 ? T.green : T.red }}>{fmtPct(r.revenue_yoy, 1)}</span>
                    : <span style={{ color: T.dim }} title={r.numbers === 'not_on_feed' ? "NSE's results feed has no XBRL for this filing yet (it often lands hours after the PDF)" : r.numbers === 'ok' ? 'no year-ago quarter to compare' : 'reading the filing'}>
                        {r.numbers === 'not_on_feed' ? 'not on feed yet' : r.numbers === 'ok' ? '—' : '…'}</span> },
                { key: 'pat', label: 'Profit YoY', align: 'right', sort: r => r.pat_yoy ?? -999,
                  render: r => r.pat_turn ? <span style={{ color: r.pat_turn === 'to profit' ? T.green : T.red }}>{r.pat_turn}</span>
                    : r.pat_yoy == null ? <span style={{ color: T.dim }}>{r.numbers === 'pending' ? '…' : '—'}</span> : <span style={{ color: r.pat_yoy >= 0 ? T.green : T.red }}>{fmtPct(r.pat_yoy, 1)}</span> },
                { key: 'chg', label: 'Today', align: 'right', sort: r => r.change_pct ?? -999,
                  render: r => r.change_pct == null ? <span style={{ color: T.dim }}>{r.reacts_next_session ? 'next session' : reacting.phase !== 'session' ? 'at the open' : 'no quote'}</span>
                    : <span style={{ color: r.change_pct >= 0 ? T.green : T.red, fontWeight: 700 }}>{fmtPct(r.change_pct, 1)}</span> },
                { key: 'vsn', label: 'vs NIFTY', align: 'right', sort: r => r.vs_nifty_pct ?? -999,
                  render: r => r.vs_nifty_pct == null ? '—' : <span style={{ color: r.vs_nifty_pct >= 0 ? T.green : T.red }}>{fmtPct(r.vs_nifty_pct, 1)}</span> },
                { key: 'typical', label: 'Typical', align: 'right', render: r => r.typical_move_pct == null ? <span style={{ color: T.dim }}>—</span> : <span style={{ color: T.muted }}>±{r.typical_move_pct.toFixed(1)}%</span> },
                { key: 'size', label: 'Size vs normal', align: 'right', sort: r => r.vs_typical ?? -1,
                  render: r => r.vs_typical == null ? '—' : <span style={{ color: r.vs_typical >= 2 ? T.amber : T.muted, fontWeight: r.vs_typical >= 2 ? 700 : 400 }}>{r.vs_typical.toFixed(1)}×</span> },
              ]} />
          </Panel>
        )}

        {season && season.length > 0 && (() => {
          const latest = season.reduce((m, r) => (r.period_end > m ? r.period_end : m), '')
          const rep = season.filter(r => r.period_end === latest)
          if (rep.length < 3) return null
          const qn = fiscalQuarter(latest)
          const med = median
          const revs = rep.map(r => r.revenue_yoy).filter((v): v is number => v != null)
          const pats = rep.map(r => r.pat_yoy).filter((v): v is number => v != null)
          const grew = rep.filter(r => (r.pat_yoy != null && r.pat_yoy > 0) || r.pat_yoy_turn === 'to profit').length
          const fell = rep.filter(r => (r.pat_yoy != null && r.pat_yoy < 0) || r.pat_yoy_turn === 'to loss').length
          const byInd = new Map<string, ScreenRow[]>()
          for (const r of rep) { const k = r.industry ?? 'Other / unclassified'; byInd.set(k, [...(byInd.get(k) ?? []), r]) }
          const inds = [...byInd.entries()].map(([k, v]) => ({ k, n: v.length,
            rev: med(v.map(r => r.revenue_yoy).filter((x): x is number => x != null)),
            pat: med(v.map(r => r.pat_yoy).filter((x): x is number => x != null)) })).sort((a, b) => b.n - a.n).slice(0, 8)
          const pc = (v: number | null) => <span style={{ color: v == null ? T.dim : v >= 0 ? T.green : T.red }}>{fmtPct(v, 1)}</span>
          return (
            <Panel source={undatedSource('NSE results filings', 'latest quarter per company')} badge="context" title={`${qn} season so far`} accent={T.green}
              subtitle={`${rep.length} companies reported and read · latest quarter vs a year ago · from their NSE results filings (XBRL) · full list: FUND`}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 8, marginBottom: 10 }}>
                {([['Reported', String(rep.length), T.text], ['Median revenue growth', fmtPct(med(revs), 1), (med(revs) ?? 0) >= 0 ? T.green : T.red],
                   ['Median profit growth', fmtPct(med(pats), 1), (med(pats) ?? 0) >= 0 ? T.green : T.red],
                   ['Profit up / down', `${grew} / ${fell}`, grew >= fell ? T.green : T.red]] as const).map(([k, v, c]) => (
                  <div key={k} style={{ border: `1px solid ${T.border}`, padding: '6px 10px' }}>
                    <div style={{ fontSize: 9, color: T.dim, letterSpacing: 1, textTransform: 'uppercase' }}>{k}</div>
                    <div style={{ fontFamily: T.mono, fontSize: 16, color: c }}>{v}</div>
                  </div>))}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(330px, 1fr))', columnGap: 18 }}>
                {inds.map(i => (
                  <div key={i.k} style={{ display: 'grid', gridTemplateColumns: '1fr 34px 80px 80px', gap: 6, padding: '3px 0', borderBottom: `1px solid ${T.border}`, fontSize: 11, fontFamily: T.mono }}>
                    <span style={{ color: T.muted, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{i.k}</span>
                    <span style={{ color: T.dim, textAlign: 'right' }}>{i.n}</span>
                    <span style={{ textAlign: 'right' }}>rev {pc(i.rev)}</span>
                    <span style={{ textAlign: 'right' }}>pft {pc(i.pat)}</span>
                  </div>))}
              </div>
              {(() => {   // the season's extremes by profit growth (turns to loss count as worst)
                const scored = rep.map(r => ({ r, v: r.pat_yoy_turn === 'to loss' ? -1e9 : r.pat_yoy_turn === 'to profit' ? 1e9 : r.pat_yoy }))
                  .filter((x): x is { r: ScreenRow; v: number } => x.v != null)
                if (scored.length < 6) return null
                scored.sort((a, b) => b.v - a.v)
                const line = (x: { r: ScreenRow }) => (
                  <span key={x.r.symbol} style={{ whiteSpace: 'nowrap', marginRight: 12 }}><TickerLink symbol={x.r.symbol} />{' '}
                    <span style={{ color: x.r.pat_yoy_turn ? (x.r.pat_yoy_turn === 'to profit' ? T.green : T.red) : (x.r.pat_yoy ?? 0) >= 0 ? T.green : T.red }}>
                      {x.r.pat_yoy_turn ?? fmtPct(x.r.pat_yoy, 0)}</span></span>)
                return <div style={{ fontSize: 11, marginTop: 8, lineHeight: 1.8 }}>
                  <span style={{ color: T.dim, fontSize: 10, letterSpacing: 1 }}>BEST PROFIT GROWTH </span>{scored.slice(0, 5).map(line)}<br />
                  <span style={{ color: T.dim, fontSize: 10, letterSpacing: 1 }}>WORST </span>{scored.slice(-5).reverse().map(line)}
                </div>
              })()}
              <div style={{ fontSize: 10, color: T.dim, marginTop: 6 }}>Medians by industry (count = companies). Early in a season the sample is small and skewed to whoever reports first (IT, banks).</div>
            </Panel>
          )
        })()}

        {recent && recent.length > 0 && (
          <Panel source={sourceOf(recent.map(r => r.released_at.slice(0, 10)).sort().pop() ?? null, { source: 'NSE results', maxAgeDays: 10 })} badge="context" title="Results scoreboard" accent={T.amber} pad={0}
            subtitle={`reported in the last 10 days · reaction session after each release · size = move ÷ the stock's typical results move`}
            right={(() => {
              const done = recent.filter(r => r.move_pct != null)
              const upN = done.filter(r => (r.vs_nifty_pct ?? 0) > 0).length
              const avg = done.length ? done.reduce((a, r) => a + (r.vs_nifty_pct ?? 0), 0) / done.length : null
              return <span style={{ fontFamily: T.mono, fontSize: 10.5, color: T.muted }}>
                {done.length} reacted · <span style={{ color: T.green }}>{upN} beat NIFTY</span> · <span style={{ color: T.red }}>{done.length - upN} lagged</span>
                {avg != null && <> · avg <span style={{ color: avg >= 0 ? T.green : T.red }}>{fmtSigned(avg, 1)}%</span> vs NIFTY</>}
              </span>
            })()}>
            <DataTable<RecentResult> dense maxHeight={340} rowKey={r => `${r.symbol}-${r.period_end}`} onRowClick={r => onSelectTicker(r.symbol)}
              initialSort={{ key: 'move', dir: 'desc' }}
              rows={recent}
              columns={[
                { key: 'symbol', label: 'Stock', sort: r => r.symbol, render: r => <TickerLink symbol={r.symbol} /> },
                { key: 'released', label: 'Released', sort: r => r.released_at, render: r => <span style={{ color: T.muted }}>{r.released_at.slice(5)} <span style={{ color: T.dim, fontSize: 10 }}>{r.timing}</span></span> },
                { key: 'move', label: 'Reaction', align: 'right', sort: r => r.move_pct ?? -999,
                  render: r => r.move_pct == null ? <span style={{ color: T.dim }}>pending</span>
                    : <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>{r.avoid && <AvoidFlag r={r} />}
                        <span style={{ color: r.move_pct >= 0 ? T.green : T.red, fontWeight: 700 }}>{fmtSigned(r.move_pct, 1)}%</span></span> },
                { key: 'vs', label: 'vs NIFTY', align: 'right', sort: r => r.vs_nifty_pct ?? -999,
                  render: r => r.vs_nifty_pct == null ? '—' : <span style={{ color: r.vs_nifty_pct >= 0 ? T.green : T.red }}>{fmtSigned(r.vs_nifty_pct, 1)}%</span> },
                { key: 'typical', label: 'Typical', align: 'right', render: r => r.typical_move_pct == null ? '—' : <span style={{ color: T.muted }}>±{r.typical_move_pct.toFixed(1)}%</span> },
                { key: 'size', label: 'Size vs normal', align: 'right', sort: r => r.move_pct != null && r.typical_move_pct ? Math.abs(r.move_pct) / r.typical_move_pct : -1,
                  render: r => r.move_pct != null && r.typical_move_pct ? (() => { const x = Math.abs(r.move_pct!) / r.typical_move_pct!
                    return <span style={{ color: x >= 2 ? T.amber : T.muted, fontWeight: x >= 2 ? 700 : 400 }}>{x.toFixed(1)}×</span> })() : '—' },
                { key: 'to', label: '₹ cr/day', align: 'right', sort: r => r.turnover_cr, render: r => <span style={{ color: T.dim }}>{Math.round(r.turnover_cr)}</span> },
              ]} />
          </Panel>
        )}

        <ResultsImpliedMoves />
        {/* terminal v2 PLAN 1.1: the per-stock results IV-crush ledger (last 8 releases), names sorted by next results */}
        <CrushLedger />
        <Panel source={undatedSource('NSE calendar')} title="Next five weeks" accent={T.amber} pad={0}
          subtitle={day ? `showing ${fmtDay(day)} · click again to clear` : 'busiest names per day by turnover · ◆ = economic data / RBI / Fed (ECO) · click a day to filter'}
          right={<div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
            <Chip color={T.muted} active={!kind} onClick={() => setKind(null)}>ALL</Chip>
            {KIND_ORDER.filter(k => kindCounts[k]).map(k => (
              <Chip key={k} color={KIND_COLOR[k]} active={kind === k} onClick={() => setKind(kind === k ? null : k)}>{k} {kindCounts[k]}</Chip>
            ))}
          </div>}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(0, 1fr))' }}>
            {['Mon', 'Tue', 'Wed', 'Thu', 'Fri'].map(d => (
              <div key={d} style={{ padding: '6px 10px', fontSize: 9.5, letterSpacing: 1.4, color: T.dim, borderBottom: `1px solid ${T.border}`,
                                    fontFamily: T.display, textTransform: 'uppercase' }}>{d}</div>
            ))}
            {weeks.flat().map(d => {
              const ev = byDay.get(d) ?? []
              const isToday = d === today, past = d < today, on = d === day
              const mineHere = ev.filter(e => owners.has(e.symbol))
              return (
                <button key={d} onClick={() => setDay(on ? null : d)}
                  style={{ textAlign: 'left', minHeight: 92, padding: '7px 9px', cursor: ev.length ? 'pointer' : 'default',
                           background: on ? T.panel3 : isToday ? '#0f1219' : 'transparent', opacity: past ? 0.45 : 1,
                           border: 'none', borderRight: `1px solid ${T.border}`, borderBottom: `1px solid ${T.border}`,
                           outline: on ? `1px solid ${T.amber}` : 'none', outlineOffset: -1 }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: 6, marginBottom: 5 }}>
                    <span style={{ fontFamily: T.mono, fontSize: 12, fontWeight: 700, color: isToday ? T.amber : T.text }}>{parse(d).getDate()}</span>
                    <span style={{ fontSize: 9, color: T.dim }}>{parse(d).toLocaleDateString('en-IN', { month: 'short' })}</span>
                    <span style={{ flex: 1 }} />
                    {ev.length > 0 && <span style={{ fontFamily: T.mono, fontSize: 10, color: T.muted }}>{ev.length}</span>}
                  </div>
                  {(ecoByDay.get(d) ?? []).map(m => (   // macro releases and policy decisions (ECO)
                    <div key={`${m.kind}-${m.date}`} title={`${m.what} · ${m.time ?? ''} IST`}
                      style={{ fontSize: 9.5, lineHeight: '15px', color: ECO_KINDS[m.kind]?.color ?? T.muted, fontFamily: T.mono, letterSpacing: 0.5,
                               whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                      ◆ {ECO_KINDS[m.kind]?.label ?? m.kind} {m.time}</div>))}
                  {[...mineHere, ...ev.filter(e => !owners.has(e.symbol))].slice(0, 4).map(e => (
                    <div key={`${e.symbol}-${e.kind}`} style={{ display: 'flex', gap: 5, alignItems: 'center', fontSize: 10.5, lineHeight: '16px' }}>
                      <span style={{ width: 5, height: 5, background: KIND_COLOR[e.kind] ?? T.muted, flex: 'none' }} />
                      <span style={{ color: owners.has(e.symbol) ? T.green : T.text, fontFamily: T.mono, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{e.symbol}</span>
                    </div>
                  ))}
                  {ev.length > 4 && <div style={{ fontSize: 9.5, color: T.dim, marginTop: 2 }}>+{ev.length - 4} more</div>}
                </button>
              )
            })}
          </div>
        </Panel>

        <Panel source={undatedSource('NSE calendar')} title="All events" accent={T.cyan} pad={0}
          subtitle={`${filtered.length} shown · last 7 days and next 60 · click a stock for its chart`}
          right={<Input value={q} onChange={setQ} placeholder="Stock, company or text…" width={220} />}>
          <DataTable columns={cols} rows={filtered} rowKey={r => `${r.symbol}-${r.event_date}-${r.kind}`} dense maxHeight={620}
            onRowClick={r => onSelectTicker(r.symbol)} empty="No events match these filters"
            rowStyle={r => (r.event_date < today ? { opacity: 0.5 } : undefined)} />
        </Panel>
        <div style={{ fontSize: 10, color: T.dim, lineHeight: 1.6 }}>
          Source: NSE event calendar, board-meeting intimations and corporate actions (free, official). Board-meeting dates are when
          results are approved; they usually come out that evening. Ex-date is the first day the stock trades without the dividend,
          bonus or split. Pulled daily by the EOD pipeline and kept, so past events build a history for research.
        </div>
      </div>
    </div>
  )
}
