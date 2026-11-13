'use client'

/**
 * WATCH monitor — every stock you care about in one live grid: the watchlist, pins, ICICI holdings and the
 * Desk's positions, with price, day change, a one-month sparkline, where it sits in its day and 52-week range,
 * volume, and the next corporate event. NSE rows' price, day change and day range are LIVE NSE quotes (lib/liveQuotes:
 * the Breeze websocket, else NSE's website ≈ 1 min, else the last close labelled CLOSE), every 3 s, with a per-row
 * source mark. Live program round 2 (L2-UI): their name, one-month spark and 52-week range come from NSE's own stored
 * closes (news/useNseBase → /api/market/closes, one request, every 10 min) — no Yahoo request for an NSE row; the 60 s
 * /api/news-scanner/quotes call carries only the non-NSE pins (US names, commodities), and NSE rows only while the live
 * route is not deployed (404, the pre-live world, labelled). Add a stock by typing its ticker. Click a ticker for its
 * chart and profile.
 */
import { RiskChips } from '@/components/RiskChips'
import { fmtSigned } from '@/lib/format'   // signed numbers with U+2212 (C1-trader-ux-18)
import { useSurveillance } from '@/lib/useSurveillance'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { getDeskStatus, getNewsQuotes, getOpenPositions, getSymbols, type SymbolEntry, heldSymbols } from '@/lib/api'
import type { Quote } from '@/components/news/types'
import { useWatchlist } from '@/context/AppContext'
import { usePins } from '@/lib/pins'
import { daysUntil, useCorpEvents, useResultsAvoid } from '@/lib/useCorpEvents'
import { notifyHits, useAlerts } from '@/lib/alerts'
import { hitText } from '@/lib/alertText'
import { useToast } from '@/context/ToastContext'
import { BasketRisk } from '@/components/BasketRisk'
import { useFinancialsLatest } from '@/lib/useFinancials'
import { COMP_KEY } from '@/components/Compare'
import { goToPage } from '@/lib/navigate'
import { Chip, DataTable, EventBadge, Input, Notice, PageHeader, Panel, Spark, Stat, T, TickerLink, type Column, AvoidFlag, fmtFixed, fmtPct, fmtPx, inputSource, sourceOf, tone, type SourceInfo } from '@/components/terminal'
import { openSettingsImport } from '@/components/shell/SettingsImport'
import { sourceChipText } from '@/components/terminal/source'
import { useMarketOpen } from '@/components/shell/useFeed'
import { BellGlyph } from '@/components/shell/Glyphs'   // monochrome SVG bell, not the colour emoji (CT-14)
import { useLiveQuotes } from '@/lib/liveQuotes'
import { baseTitles, nseQuoteRow, yahooCallSymbols } from '@/components/news/nseBase'
import { useNseBase } from '@/components/news/useNseBase'
import { isDesktop, notificationPermission, requestNotificationPermission, shellMarker } from '@/lib/platform'

type Source = 'HELD' | 'DESK' | 'WATCH' | 'PIN'
const SRC_COLOR: Record<Source, string> = { HELD: T.green, DESK: T.amber, WATCH: T.cyan, PIN: T.violet }
const REFRESH_MS = 60_000

interface Row { sym: string; yahoo: string; name: string; sources: Source[]; q?: Quote & { spark?: number[] } }

const pct = fmtPct

function RangeDot({ lo, hi, v, label }: { lo?: number; hi?: number; v?: number; label: string }) {
  if (lo == null || hi == null || v == null || hi <= lo) return <span style={{ color: T.dim }}>—</span>
  const p = Math.max(0, Math.min(100, ((v - lo) / (hi - lo)) * 100))
  return (
    <span title={`${label}: ${lo.toFixed(2)} – ${hi.toFixed(2)} (${p.toFixed(0)}% of range)`}
      style={{ display: 'inline-block', position: 'relative', width: 70, height: 6, background: T.border, verticalAlign: 'middle' }}>
      <span style={{ position: 'absolute', left: `calc(${p}% - 2px)`, top: -2, width: 4, height: 10,
                     background: p > 80 ? T.green : p < 20 ? T.red : T.amber }} />
    </span>
  )
}

/** A row's live source as a 6 px dot after its price: green = Breeze live, grey = NSE delayed / close, amber = stale; hover for the chip text. */
function RowSource({ info }: { info: SourceInfo | null }) {
  if (!info) return null
  const t = sourceChipText(info)
  const c = info.state === 'live' ? T.green : info.state === 'stale' ? T.amber : info.state === 'offline' ? T.red : T.muted
  return <span title={`${t.label} — ${t.title}`} data-sd-row-source={info.state}
    style={{ display: 'inline-block', width: 6, height: 6, marginLeft: 5, borderRadius: 3, background: c, verticalAlign: 'middle', opacity: info.state === 'live' ? 1 : 0.8 }} />
}

export function WatchMonitor() {
  const { watchlist, addToWatchlist, removeFromWatchlist } = useWatchlist()
  const { pins } = usePins()
  const events = useCorpEvents()
  const avoid = useResultsAvoid()
  const [held, setHeld] = useState<string[]>([])
  // quantity and buy price per held stock (live ICICI book, or the last known one while logged out)
  const [book, setBook] = useState<Record<string, { qty: number; buy: number }>>({})
  // PLAN 1.4: whether the book is ICICI's live one or the last-known file, as a chip (it was only implied in a comment)
  const [bookSrc, setBookSrc] = useState<SourceInfo | null>(null)
  const [desk, setDesk] = useState<string[]>([])
  const [quotes, setQuotes] = useState<Record<string, Quote & { spark?: number[] }>>({})
  const [asOf, setAsOf] = useState<Date | null>(null)
  const [dir, setDir] = useState<Map<string, SymbolEntry>>(new Map())
  const [add, setAdd] = useState('')
  const [addMsg, setAddMsg] = useState<string | null>(null)
  const [filter, setFilter] = useState<Source | null>(null)
  const { alerts, history, setBoth, check } = useAlerts()
  const { addToast } = useToast()
  const [editing, setEditing] = useState<string | null>(null)
  const [alertUp, setAlertUp] = useState('')
  const [alertDown, setAlertDown] = useState('')
  const [perm, setPerm] = useState<string>(() => (typeof Notification !== 'undefined' ? Notification.permission : 'unsupported'))
  useEffect(() => { if (isDesktop()) void notificationPermission().then(setPerm) }, [])   // app: macOS permission via the shell

  useEffect(() => {
    getOpenPositions().then(r => {
      setHeld(heldSymbols(r.data))
      const rows: any[] = r.data?.positions?.length ? r.data.positions : (r.data?.last_known?.positions ?? [])
      setBookSrc(r.data?.positions?.length ? sourceOf(new Date().toISOString(), { live: true, source: 'ICICI' })
        : r.data?.last_known ? sourceOf(String(r.data.last_known.as_of ?? '') || null, { source: 'ICICI last-known book', maxAgeDays: 1, hint: 'ICICI not connected: last known holdings' })
        : null)
      const b: Record<string, { qty: number; buy: number }> = {}
      for (const p of rows) {
        const qty = Number(p.quantity), buy = Number(p.buy_price ?? p.average_price)
        if (p.symbol && qty > 0 && buy > 0) b[String(p.symbol).toUpperCase()] = { qty, buy }
      }
      setBook(b)
    }).catch(() => {})
    getDeskStatus().then(r => setDesk((r.data?.positions ?? []).map((p: any) => String(p.symbol).toUpperCase()))).catch(() => {})
    getSymbols().then(r => setDir(new Map(r.data.data.map(s => [s.t, s])))).catch(() => {})
  }, [])

  const rows = useMemo<Row[]>(() => {
    const m = new Map<string, Row>()
    const put = (sym: string, yahoo: string, name: string | undefined, src: Source) => {
      const r = m.get(yahoo) ?? { sym, yahoo, name: name ?? dir.get(sym)?.n ?? sym, sources: [] }
      if (!r.sources.includes(src)) r.sources.push(src)
      m.set(yahoo, r)
    }
    held.forEach(s => put(s, `${s}.NS`, undefined, 'HELD'))
    desk.forEach(s => put(s, `${s}.NS`, undefined, 'DESK'))
    watchlist.forEach(w => { const s = w.toUpperCase().replace(/\.NS$/, ''); put(s, `${s}.NS`, undefined, 'WATCH') })
    Object.values(pins).forEach(p => { const s = p.pick.symbol; if (s) put(s.base, s.yahoo, p.pick.company_name, 'PIN') })
    return [...m.values()].map(r => ({ ...r, q: quotes[r.yahoo] }))
  }, [held, desk, watchlist, pins, quotes, dir])

  const yahooKey = rows.map(r => r.yahoo).sort().join(',')
  // NSE stocks in the list (pins can be US names or commodities), for the risk panel
  const nseSyms = useMemo(() => [...new Set(rows.filter(r => r.yahoo.endsWith('.NS')).map(r => r.sym))].sort().slice(0, 60), [yahooKey])  // eslint-disable-line react-hooks/exhaustive-deps

  // live NSE overlay (reports/live_nse): every NSE row's price, day change and day range from the live quote service
  // (Breeze websocket → NSE website → last close; never Yahoo); round 2: its name, 1M spark and 52-week range from NSE's
  // stored closes (useNseBase). The 60 s quotes call below carries the non-NSE pins only — and NSE rows only while the
  // live route answers 404 (not deployed: the pre-live route, labelled by its own source).
  const liveSyms = useMemo(() => [...new Set(rows.filter(r => r.yahoo.endsWith('.NS')).map(r => r.sym))].sort(), [yahooKey])  // eslint-disable-line react-hooks/exhaustive-deps
  const liveQ = useLiveQuotes(liveSyms, { intervalMs: 3_000 })
  const nseBase = useNseBase(liveSyms)
  const legacy = liveQ.status === 'missing'
  const callKey = yahooCallSymbols(yahooKey ? yahooKey.split(',') : [], liveQ.status).join(',')
  const refresh = useCallback(async () => {
    const syms = callKey ? callKey.split(',') : []
    if (!syms.length) return
    const out: Record<string, any> = {}
    for (let i = 0; i < syms.length; i += 60) {                 // endpoint caps a call at 60 symbols
      try { Object.assign(out, (await getNewsQuotes(syms.slice(i, i + 60))).data.quotes) } catch { /* keep last */ }
    }
    setQuotes(q => ({ ...q, ...out })); setAsOf(new Date())
  }, [callKey])
  useEffect(() => { refresh(); const iv = setInterval(refresh, REFRESH_MS); return () => clearInterval(iv) }, [refresh])

  const rowsLive = useMemo(() => rows.map(r => {
    if (!r.yahoo.endsWith('.NS') || legacy) return r                       // non-NSE pins: their Yahoo row as is
    const q = nseQuoteRow(r.sym, nseBase.base[r.sym], liveQ.quotes[r.sym], dir.get(r.sym)?.n ?? null) as unknown as Row['q']
    return { ...r, q }
  }), [rows, liveQ.quotes, nseBase.base, legacy, dir])
  const nonNse = rows.filter(r => !r.yahoo.endsWith('.NS')).length
  const nonNseHint = nonNse ? ` · ${nonNse} non-NSE pin${nonNse > 1 ? 's' : ''} on Yahoo (60 s)` : ''
  const baseHint = nseBase.asOf ? ` · names, 1M sparks and 52-week ranges: NSE closes stored to ${nseBase.asOf}${nseBase.status === 'error' ? ` (last read; ${nseBase.error})` : ''}`
    : nseBase.status === 'missing' ? ' · NSE closes route not deployed: no sparks / 52-week ranges'
      : nseBase.status === 'error' ? ` · NSE closes unavailable (${nseBase.error}): no sparks / 52-week ranges` : ''
  // an empty list is the user's (nothing pinned), not a feed that failed: the 5 Nov live audit read OFFLINE · YAHOO here
  const monitorSrc: SourceInfo = rows.length === 0
    ? inputSource('your watch list: nothing pinned yet (NSE pins price live from Breeze / NSE; other pins from Yahoo)')
    : legacy
    ? { state: Object.keys(quotes).length ? 'delayed' : 'offline', source: 'YAHOO', asOf: asOf?.toISOString() ?? null,
        hint: 'live NSE quote service not deployed: the pre-live quotes route on a 60 s refresh' }
    : liveQ.source
      ? { ...liveQ.source, hint: `${liveQ.source.hint ?? ''}${baseHint}${nonNseHint}` }
      : liveSyms.length
        ? { state: 'offline', source: 'LIVE', asOf: null, ageDays: null,
            hint: `${liveQ.status === 'error' ? 'live NSE quote service not answering' : 'waiting for the live NSE quote service'}${baseHint}${nonNseHint}` }
        : { state: Object.keys(quotes).length ? 'delayed' : 'offline', source: 'YAHOO', asOf: asOf?.toISOString() ?? null, hint: 'non-NSE pins: Yahoo quotes on a 60 s refresh' }

  // the alert check runs on its own 60 s tick: NSE rows no longer arrive through the 60 s quotes call (round 2)
  const [checkTick, setCheckTick] = useState(0)
  useEffect(() => { const iv = setInterval(() => setCheckTick(t => t + 1), REFRESH_MS); return () => clearInterval(iv) }, [])
  useEffect(() => {
    // the server prices and fires the levels (also every minute from the scheduler); show what's new here
    check().then(hits => {
      // kit glyphs, no colour emoji (CT-14): the arrow says which way the level was crossed
      // P11: a ±% MOVE hit says "TCS moved −6.1 % (≥ 5 %)" (lib/alertText.ts hitText), never "fell below ₹5"
      hits.forEach(h => addToast(h.side === 'move'
        ? `${(h.change_pct ?? 0) >= 0 ? '▲' : '▼'} ALERT ${hitText(h)}`
        : `${h.side === 'above' ? '▲' : '▼'} ALERT ${h.sym} ${h.side === 'above' ? 'rose above' : 'fell below'} ₹${h.level.toLocaleString('en-IN')} — now ₹${fmtPx(h.price)}`, 'warning', 20000))
      // the app (round 3, K5) posts the scheduler's price alerts natively from its notification feed whatever page is
      // open: a second banner from this page would be a duplicate. An older app without the feature, and the browser,
      // keep the page's own notification.
      if (!shellMarker()?.features?.includes('notification_feed')) notifyHits(hits)   // one per check, with a count (C3-logic-unchanged-07)
    })
  }, [checkTick]) // eslint-disable-line react-hooks/exhaustive-deps

  const openEditor = (sym: string) => {
    setEditing(sym); setAlertUp(alerts[sym]?.above ? String(alerts[sym].above) : ''); setAlertDown(alerts[sym]?.below ? String(alerts[sym].below) : '')
  }
  const saveEditor = () => {
    if (!editing) return
    const n = (v: string) => { const x = Number(v.replace(/[,₹\s]/g, '')); return x > 0 ? x : null }
    const yahoo = rows.find(r => r.sym === editing)?.yahoo
    // one PUT with both sides: two calls would race on the same record
    setBoth(editing, n(alertUp), n(alertDown), yahoo); setEditing(null)
  }

  const submit = () => {
    const s = add.trim().toUpperCase().replace(/\.NS$/, '')
    if (!s) return
    if (dir.size && !dir.has(s)) { setAddMsg(`${s} is not in the 1,500-stock directory; added anyway`) } else setAddMsg(null)
    addToWatchlist(s); setAdd('')
  }

  const marketOpen = useMarketOpen()
  const dayWord = marketOpen ? 'today' : 'last session'
  const shown = rowsLive.filter(r => !filter || r.sources.includes(filter))
  const live = shown.filter(r => r.q?.available && r.q.change_pct != null)
  const up = live.filter(r => (r.q!.change_pct ?? 0) > 0).length
  const avg = live.length ? live.reduce((a, r) => a + (r.q!.change_pct ?? 0), 0) / live.length : null
  const best = [...live].sort((a, b) => (b.q!.change_pct ?? 0) - (a.q!.change_pct ?? 0))[0]
  const worst = [...live].sort((a, b) => (a.q!.change_pct ?? 0) - (b.q!.change_pct ?? 0))[0]
  const counts = (['HELD', 'DESK', 'WATCH', 'PIN'] as Source[]).map(s => [s, rows.filter(r => r.sources.includes(s)).length] as const)

  const { fin } = useFinancialsLatest(rows.map(r => r.sym))
  const risk = useSurveillance(rows.filter(r => r.yahoo.endsWith('.NS')).map(r => r.sym))
  const cols: Column<Row>[] = [
    { key: 'sym', label: 'Stock', sort: r => r.sym, render: r => (
      <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
        {r.yahoo.endsWith('.NS') || r.yahoo.endsWith('.BO') ? <TickerLink symbol={r.sym} noFlag /> : <span style={{ color: T.amber, fontWeight: 600 }}>{r.sym}</span>}
        {r.sources.map(s => <span key={s} style={{ fontSize: 9, color: SRC_COLOR[s], border: `1px solid ${SRC_COLOR[s]}66`, padding: '0 3px' }}>{s}</span>)}
        {avoid.get(r.sym) && <AvoidFlag r={avoid.get(r.sym)!} />}
        <RiskChips flags={risk[r.sym]} max={2} />
      </span>) },
    { key: 'name', label: 'Name', render: r => <span style={{ color: T.muted, maxWidth: 230, display: 'inline-block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', verticalAlign: 'bottom' }}>{r.q?.name ?? r.name}</span> },
    { key: 'price', label: 'Last', align: 'right', sort: r => r.q?.price ?? -1, render: r => r.q?.price != null
      ? <span>{r.q.price.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}<RowSource info={r.yahoo.endsWith('.NS') ? liveQ.sourceFor(r.sym) : null} /></span>
      : <span style={{ color: T.dim }}>{r.q ? 'n/a' : '…'}</span> },
    { key: 'chg', label: 'Day', align: 'right', sort: r => r.q?.change_pct ?? -999, render: r => <span style={{ color: tone(r.q?.change_pct), fontWeight: 600 }}>{pct(r.q?.change_pct)}</span> },
    { key: 'pos', label: 'Position', align: 'right', sort: r => { const b = book[r.sym]; return b && r.q?.price != null ? r.q.price / b.buy - 1 : -999 },
      render: r => { const b = book[r.sym], px = r.q?.price
        if (!b) return <span style={{ color: T.dim }}>—</span>
        if (px == null) return <span style={{ color: T.muted }}>{b.qty} @ {fmtPx(b.buy)}</span>
        const pnl = (px - b.buy) * b.qty, c = r.q?.change_pct, day = c != null ? px * b.qty * (c / 100) / (1 + c / 100) : null
        return <span title={`${b.qty} @ ₹${fmtPx(b.buy)} · value ₹${Math.round(px * b.qty).toLocaleString('en-IN')}${day != null ? ` · ${dayWord} ${day >= 0 ? '+' : '−'}₹${Math.abs(Math.round(day)).toLocaleString('en-IN')}` : ''}`}>
          <span style={{ color: T.dim, fontSize: 10 }}>{b.qty} @ {fmtPx(b.buy)} </span>
          <span style={{ color: tone(pnl), fontWeight: 600 }}>{pnl >= 0 ? '+' : '−'}₹{Math.abs(Math.round(pnl)).toLocaleString('en-IN')} ({pct((px / b.buy - 1) * 100)})</span></span> } },
    { key: 'fa', label: 'P/E · profit y/y', align: 'right', sort: r => fin[r.sym]?.pe ?? 1e9, title: 'valuation and latest quarter from NSE results filings (FA)',
      render: r => { const f = fin[r.sym]; if (!f) return <span style={{ color: T.dim }}>…</span>
        return <span style={{ fontSize: 11 }}><span style={{ color: T.muted }}>{f.pe != null ? `${fmtFixed(f.pe, 1)}×` : '—'}</span>
          <span style={{ color: T.dim }}> · </span>{f.pat_yoy_turn ? <span style={{ color: f.pat_yoy_turn === 'to profit' ? T.green : T.red }}>{f.pat_yoy_turn}</span>
            : <span style={{ color: f.pat_yoy == null ? T.dim : f.pat_yoy >= 0 ? T.green : T.red }}>{fmtPct(f.pat_yoy, 0)}</span>}</span> } },
    { key: 'spark', label: '1M', title: 'NSE rows: the last 22 NSE daily closes (stored, split/bonus-adjusted) plus today\'s live point; non-NSE pins: Yahoo',
      render: r => r.q?.spark && r.q.spark.length > 1
      ? <span title={r.yahoo.endsWith('.NS') && !legacy ? baseTitles(r.q as never).spark : 'Yahoo daily closes (non-NSE pin)'} data-sd-base={r.yahoo.endsWith('.NS') && !legacy ? 'nse_closes' : 'yahoo'}>
          <Spark values={r.q.spark} width={90} height={22} color={r.q.spark[r.q.spark.length - 1] >= r.q.spark[0] ? T.green : T.red} /></span> : null },
    { key: 'day', label: 'Day range', render: r => <RangeDot lo={r.q?.day_low} hi={r.q?.day_high} v={r.q?.price} label="Day range" /> },
    { key: '52w', label: '52W', sort: r => r.q?.price != null && r.q.high_52w ? r.q.price / r.q.high_52w : -1,
      title: 'NSE rows: the 52-week high / low on adjusted NSE daily bars (stored), widened by today\'s range; non-NSE pins: Yahoo',
      render: r => <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }} title={r.yahoo.endsWith('.NS') && !legacy ? baseTitles(r.q as never).range : undefined}>
        <RangeDot lo={r.q?.low_52w} hi={r.q?.high_52w} v={r.q?.price} label="52-week range" />
        <span style={{ fontSize: 10, color: T.muted }}>{r.q?.price != null && r.q.high_52w ? ((r.q.price / r.q.high_52w - 1) * 100 > -0.5 ? <span style={{ color: T.green }}>HIGH</span> : pct((r.q.price / r.q.high_52w - 1) * 100, 0)) : ''}</span>
      </span> },
    { key: 'event', label: 'Next event', render: r => { const e = events.get(r.sym)?.[0]; return e ? <EventBadge kind={e.kind} date={e.event_date} days={daysUntil(e.event_date)} typical={e.typical_move_pct} detail={e.detail} /> : <span style={{ color: T.dim }}>—</span> } },
    { key: 'alert', label: 'Alert', render: r => {
      const a = alerts[r.sym]
      return <span role="button" title="Set price alerts" onClick={e => { e.stopPropagation(); openEditor(r.sym) }}
        style={{ display: 'inline-flex', gap: 5, alignItems: 'center', cursor: 'pointer', fontFamily: T.mono, fontSize: 11 }}>
        <span style={{ color: a ? T.amber : T.dim }}><BellGlyph size={10} /></span>
        {a?.above != null && <span style={{ color: T.green }}>↑{a.above.toLocaleString('en-IN')}</span>}
        {a?.below != null && <span style={{ color: T.red }}>↓{a.below.toLocaleString('en-IN')}</span>}
      </span>
    } },
    { key: 'x', label: '', render: r => r.sources.includes('WATCH')
      ? <span role="button" title="Remove from watchlist" onClick={e => { e.stopPropagation(); removeFromWatchlist(r.sym) }}
          style={{ color: T.dim, cursor: 'pointer', padding: '0 6px' }}>✕</span> : null },
  ]

  return (
    <div>
      <PageHeader code="WTCH" title="Watch Monitor"
        subtitle={`watchlist · pins · ICICI holdings · Desk · ${legacy ? 'quotes every 60 s (live NSE service not deployed)' : 'live NSE quotes every 3 s · NSE closes'}${legacy && asOf ? ` · ${asOf.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' })}` : ''}`}
        right={<form onSubmit={e => { e.preventDefault(); submit() }} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <Input value={add} onChange={setAdd} placeholder="Add ticker + Enter" width={170} />
          <Chip color={T.amber} onClick={submit}>+ ADD</Chip>
          <Chip color={T.cyan} onClick={refresh}>↻</Chip>
          {Object.keys(book).length >= 2 && <Chip color={T.green} title="open your holdings side by side in COMP (performance, risk, fundamentals)"
            onClick={() => { try { localStorage.setItem(COMP_KEY, JSON.stringify({ syms: Object.keys(book).slice(0, 8), period: '1y' })) } catch { /* storage blocked */ }
                             window.dispatchEvent(new Event('suryadhana:comp')); goToPage('compare') }}>COMPARE HELD</Chip>}
        </form>} />
      {addMsg && <div style={{ fontSize: 11, color: T.amber, marginBottom: 8 }}>{addMsg}</div>}
      <div style={{ display: 'grid', gap: 10, gridTemplateColumns: `repeat(${Object.keys(book).length ? 5 : 4}, minmax(0, 1fr))`, marginBottom: 12 }}>
        {Object.keys(book).length > 0 && (() => {   // your holdings: today's ₹ move and total P&L at live prices
          let day = 0, pnl = 0, value = 0, n = 0
          for (const r of rowsLive) {
            const b = book[r.sym], px = r.q?.price, c = r.q?.change_pct
            if (!b || px == null) continue
            n++; value += px * b.qty; pnl += (px - b.buy) * b.qty
            if (c != null) day += px * b.qty * (c / 100) / (1 + c / 100)
          }
          if (!n) return null
          const rs = (v: number) => `${v >= 0 ? '+' : '−'}₹${Math.abs(Math.round(v)).toLocaleString('en-IN')}`
          return <Stat label={marketOpen ? 'Holdings today' : 'Holdings · last session'} value={rs(day)} color={tone(day)}
            sub={`P&L ${rs(pnl)} on ₹${Math.round(value).toLocaleString('en-IN')} · ${n} held`} />
        })()}
        <Stat label="Names" value={shown.length} sub={counts.map(([s, n]) => `${s} ${n}`).join(' · ')} />
        {/* C1-13 / CT-13: 'today' only in session; no green '0 / 0' before any quote has arrived */}
        <Stat label={marketOpen ? 'Up / down today' : 'Up / down · last session'} value={live.length ? `${up} / ${live.length - up}` : '—'}
              color={!live.length ? T.muted : up * 2 >= live.length ? T.green : T.red} />
        <Stat label="Average day move" value={pct(avg)} color={tone(avg)} sub="equal weight" />
        <Stat label="Best / worst" value={best ? `${best.sym} ${pct(best.q?.change_pct, 1)}` : '—'} color={tone(best?.q?.change_pct)}
              sub={worst ? `${worst.sym} ${pct(worst.q?.change_pct, 1)}` : ''} />
      </div>
      {editing && (
        <form onSubmit={e => { e.preventDefault(); saveEditor() }}
          style={{ display: 'flex', gap: 8, alignItems: 'flex-end', padding: '10px 12px', marginBottom: 12, border: `1px solid ${T.amber}66`, background: '#120e04' }}>
          <span style={{ fontFamily: T.display, fontSize: 12, letterSpacing: 1.4, color: T.amber, alignSelf: 'center' }}><BellGlyph size={11} /> {editing}</span>
          <span style={{ fontSize: 11, color: T.muted, alignSelf: 'center' }}>now ₹{rowsLive.find(r => r.sym === editing)?.q?.price?.toLocaleString('en-IN') ?? '—'}</span>
          <Input label="Alert above ₹" value={alertUp} onChange={setAlertUp} width={130} />
          <Input label="Alert below ₹" value={alertDown} onChange={setAlertDown} width={130} />
          <Chip color={T.green} onClick={saveEditor}>SAVE</Chip>
          <Chip color={T.muted} onClick={() => setEditing(null)}>CANCEL</Chip>
          <span style={{ fontSize: 10, color: T.dim, alignSelf: 'center' }}>leave a box empty to clear it · each level fires once</span>
        </form>
      )}
      {(Object.keys(alerts).length > 0 || history.length > 0) && (
        <Panel title="Price alerts" accent={T.amber} pad={10} style={{ marginBottom: 12 }} source={inputSource('your alert levels (server-checked every minute in session)')}
          subtitle="kept on the server · checked every minute 09:15–15:30 (Mac notification, Telegram when set) and on every refresh here · not broker orders"
          right={perm !== 'granted' && perm !== 'unsupported'
            ? <Chip color={T.amber} onClick={() => void requestNotificationPermission().then(setPerm)}>ENABLE DESKTOP NOTIFICATIONS</Chip>
            : <span style={{ fontSize: 10, color: T.dim }}>{perm === 'granted' ? 'desktop notifications on' : ''}</span>}>
          <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontFamily: T.mono, fontSize: 11 }}>
            {Object.entries(alerts).map(([sym, a]) => (
              <span key={sym} style={{ display: 'inline-flex', gap: 6, alignItems: 'center', border: `1px solid ${T.border}`, padding: '3px 8px' }}>
                <span style={{ color: T.amber, cursor: 'pointer' }} onClick={() => openEditor(sym)}>{sym}</span>
                {a.above != null && <span style={{ color: T.green }}>↑ {a.above.toLocaleString('en-IN')}</span>}
                {a.below != null && <span style={{ color: T.red }}>↓ {a.below.toLocaleString('en-IN')}</span>}
                <span role="button" title="Remove" style={{ color: T.dim, cursor: 'pointer' }}
                  onClick={() => { setBoth(sym, null, null) }}>✕</span>
              </span>
            ))}
          </div>
          {history.length > 0 && (
            <div style={{ marginTop: 8, fontSize: 11, color: T.muted }}>
              Fired: {history.slice(0, 6).map(h => `${h.sym} ${h.side === 'above' ? '↑' : '↓'}${h.level.toLocaleString('en-IN')} (${new Date(h.at).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' })})`).join(' · ')}
            </div>
          )}
        </Panel>
      )}
      <Panel title="Monitor" pad={0} accent={T.cyan} source={monitorSrc}
        right={<div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <Chip color={T.muted} active={!filter} onClick={() => setFilter(null)}>ALL</Chip>
          {counts.filter(([, n]) => n).map(([s, n]) => <Chip key={s} color={SRC_COLOR[s]} active={filter === s} onClick={() => setFilter(filter === s ? null : s)}>{s} {n}</Chip>)}
        </div>}>
        <DataTable columns={cols} rows={shown} rowKey={r => r.yahoo} dense initialSort={{ key: 'chg', dir: 'desc' }}
          empty={<div style={{ padding: 20, fontSize: 12, color: T.muted, display: 'grid', gap: 12 }}>
            <div>Nothing to watch yet: add a ticker above, ☆ PIN a stock from any chart, or connect ICICI to see your holdings.</div>
            {/* R3-NITS (F2-TRADER: "GO IMPORT has still never been run — third report in a row"; WTCH NAMES 0 blocks
                key-2, GPLN focus and the watch-tier tape): the empty state offers the one-time settings import. */}
            <Notice>
              Used the old browser terminal before? Its watchlist and pins can be brought over once:{' '}
              <span role="button" tabIndex={0} data-wtch-import onClick={() => openSettingsImport()}
                onKeyDown={e => { if (e.key === 'Enter') openSettingsImport() }}
                style={{ color: T.cyan, cursor: 'pointer', fontFamily: T.mono, fontWeight: 600 }}>GO IMPORT ›</span>
              {' '}(type IMPORT in the GO bar, or click here).{' '}
              <span style={{ color: T.muted }}>RUNBOOK §8 one-liner: open http://localhost:3000 once in the browser you used before — its settings sync to the server store from there.</span>
            </Notice>
          </div>} />
      </Panel>
      <div style={{ fontSize: 10, color: T.dim, marginTop: 8 }}>{liveQ.available
        ? `Prices of NSE stocks: live NSE quotes every 3 s (ICICI Breeze websocket; NSE's website about 1 minute behind when a name is not streaming; the last close, labelled CLOSE, after the session). The dot after each price is its source (hover it). Names, 1M sparks and 52-week ranges of NSE stocks: NSE's stored daily closes${nseBase.asOf ? ` (to ${nseBase.asOf})` : ''}, end of day, plus today's live point. Non-NSE pins are Yahoo, about 1 minute delayed. Range markers: green near the high, red near the low.`
        : legacy
          ? "Prices: the pre-live quotes route (live NSE quote service not deployed on this ui-api), about 1 minute delayed. Range markers: green near the high, red near the low."
          : "Prices of NSE stocks: waiting for the live NSE quote service (no Yahoo price is shown for an NSE stock). Names, 1M sparks and 52-week ranges: NSE's stored daily closes. Range markers: green near the high, red near the low."}</div>
      {(() => {   // book X-ray: your holdings by value at live prices (ICICI book, or the last known one)
        const held = rowsLive.filter(r => book[r.sym] && r.q?.price != null)
          .map(r => ({ sym: r.sym, value: r.q!.price! * book[r.sym].qty, f: fin[r.sym] }))
        const total = held.reduce((a, h) => a + h.value, 0)
        if (held.length < 1 || total <= 0) return null
        held.sort((a, b) => b.value - a.value)
        const w = held.map(h => h.value / total)
        const effective = 1 / w.reduce((a, x) => a + x * x, 0)
        const withPe = held.filter(h => h.f?.pe != null && h.f.pe > 0)
        const covered = withPe.reduce((a, h) => a + h.value, 0)
        const bookPe = covered > 0 ? covered / withPe.reduce((a, h) => a + h.value / h.f!.pe!, 0) : null     // value-weighted (harmonic)
        const growth = held.filter(h => h.f?.pat_yoy != null)
        const gw = growth.reduce((a, h) => a + h.value, 0)
        const bookGrowth = gw > 0 ? growth.reduce((a, h) => a + h.value * h.f!.pat_yoy!, 0) / gw : null
        const colors = [T.amber, T.cyan, T.violet, T.green, '#fb923c', '#f472b6', '#94a3b8']
        return (
          <Panel title="Your book · X-ray" accent={T.amber} style={{ marginTop: 12 }} source={bookSrc ?? monitorSrc} badge="arithmetic"
            subtitle={`${held.length} holdings · ₹${Math.round(total).toLocaleString('en-IN')} at live prices · weights by value`}>
            <div style={{ display: 'flex', height: 14, border: `1px solid ${T.border}`, marginBottom: 8 }}>
              {held.map((h, i) => <div key={h.sym} title={`${h.sym} ${(w[i] * 100).toFixed(1)}%`} style={{ width: `${w[i] * 100}%`, background: colors[i % colors.length] }} />)}
            </div>
            <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontFamily: T.mono, fontSize: 11, marginBottom: 8 }}>
              {held.map((h, i) => <span key={h.sym}><span style={{ color: colors[i % colors.length] }}>■</span> <TickerLink symbol={h.sym} /> {(w[i] * 100).toFixed(1)}%</span>)}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 8 }}>
              {([['Largest holding', `${held[0].sym} ${(w[0] * 100).toFixed(0)}%`, w[0] > 0.4 ? T.red : w[0] > 0.25 ? T.amber : T.text,
                  'Desk rule of thumb: ≤ 15% per stock'],
                 ['Effective holdings', effective.toFixed(1), effective < 3 ? T.amber : T.text, '1 ÷ Σ weight²: how many equal-sized positions the book behaves like'],
                 ['Book P/E', bookPe != null ? `${bookPe.toFixed(0)}×` : '—', T.amber, `value-weighted (harmonic) over ${withPe.length} of ${held.length} holdings with a P/E`],
                 ['Book profit growth', bookGrowth != null ? `${fmtSigned(bookGrowth, 0)}%` : '—', bookGrowth == null ? T.dim : bookGrowth >= 0 ? T.green : T.red,
                  "value-weighted latest-quarter profit vs a year ago (NSE filings)"]] as const).map(([k, v, c, tip]) => (
                <div key={k} title={tip} style={{ border: `1px solid ${T.border}`, padding: '6px 10px' }}>
                  <div style={{ fontSize: 9, color: T.dim, letterSpacing: 1, textTransform: 'uppercase' }}>{k}</div>
                  <div style={{ fontFamily: T.mono, fontSize: 15, color: c }}>{v}</div>
                </div>))}
            </div>
            {held.length >= 2 && <div style={{ marginTop: 10 }}>
              <BasketRisk title="Your book · risk (value-weighted)" symbols={held.map(h => h.sym)} weights={Object.fromEntries(held.map(h => [h.sym, h.value]))} />
            </div>}
          </Panel>
        )
      })()}
      {nseSyms.length >= 2 && !nseSyms.every(x => book[x]) && (      // all-holdings list: the X-ray above already covers it
        <div style={{ marginTop: 12 }}>
          <BasketRisk title="Your list · risk profile" symbols={nseSyms} />
        </div>
      )}
    </div>
  )
}
