'use client'

import { apiError } from '@/lib/errors'
import { Z } from '@/lib/z'
/**
 * NewsTerminal — full-screen "Bloomberg-style" catalyst terminal over the daily
 * soft-catalyst scans in new_scnner/YYYYMMDD.json.
 *
 *  ┌ top bar: scan date · counts · refresh · close ───────────────────────────────┐
 *  │ macro tape (scrolling)                                                        │
 *  ├ picks (live quote, spark, conviction) ┬ instrument header + key stats ────────┤
 *  │  pinned (carried across scans)        │ chart: Terminal | TradingView          │
 *  │  filters · search                     │ tabs: catalyst · thesis · headlines ·  │
 *  │  rejected · disclaimer                │       technicals · sources             │
 *  └───────────────────────────────────────┴──────────────────────────────────────┘
 * Keys: ↑/↓ select · / search · Esc close
 *
 * Live program round 2 (reports/live_nse, L2-UI): an NSE pick (IN, '.NS') never reads Yahoo. Its price / move / day
 * range come from the live quote hook, its name / 1M spark / 52-week range from NSE's stored closes (useNseBase), and
 * its TERMINAL chart from NSE's stored daily bars (bhavcopy, adjusted; 1D from the tick store) — ./nseBase.ts and
 * ./nseChart.ts. The Yahoo routes (quotes, chart) carry only the non-NSE picks (US, UK); NSE picks reach the quotes
 * route only while /api/live/quotes answers 404 (the live service not deployed: the pre-live world, labelled).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getNewsChart, getNewsHeadlines, getNewsQuotes, getNewsScan, getNewsScans, getNewsTrackRecord, getStockHistory } from '@/lib/api'
import { fetchIntradayBars } from '@/lib/chartData'
import { useLiveQuotes } from '@/lib/liveQuotes'
import { SourceChip, sourceOf, type SourceInfo } from '@/components/terminal'
import { baseTitles, isNseYahoo, nseCode, nseQuoteRow, yahooCallSymbols } from './nseBase'
import { useNseBase } from './useNseBase'
import { NSE_HISTORY_DAYS, NSE_RANGES, nseDailyChart, nseIntradayChart, type HistRowLike, type NseChart } from './nseChart'
import { PriorPicks, TrackRecordView, trackVerdict, type TrackRecordData, type TrackRow } from './TrackRecord'
import { useWatchlist } from '@/context/AppContext'
import { usePins } from '@/lib/pins'
import { NewsChart, TradingViewEmbed, type Overlays } from './NewsChart'
import type { ChartData, Headline, Pick, Quote, Scan, ScanIndex } from './types'
import {
  T, convictionColor, fmtChange, fmtNum, fmtPct, fmtPrice, fmtVol, REGION_LABEL, signColor, timeAgo, tradingViewUrl,
} from './format'

const RANGES = ['1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y'] as const
const RANGE_LABEL: Record<string, string> = { '1d': '1D', '5d': '5D', '1mo': '1M', '3mo': '3M', '6mo': '6M', '1y': '1Y', '2y': '2Y', '5y': '5Y' }

// NSE picks' stored daily bars, once per symbol per IST day (the bhavcopy changes once a day, ~18:30)
const nseHistCache = new Map<string, { day: string; rows: HistRowLike[] }>()
const istDay = () => new Date(Date.now() + 330 * 60_000).toISOString().slice(0, 10)
async function nseHistory(sym: string): Promise<HistRowLike[]> {
  const hit = nseHistCache.get(sym)
  if (hit && hit.day === istDay()) return hit.rows
  const rows = ((await getStockHistory(sym, NSE_HISTORY_DAYS)).data?.rows ?? []) as HistRowLike[]
  if (nseHistCache.size > 50) nseHistCache.clear()
  nseHistCache.set(sym, { day: istDay(), rows })
  return rows
}
/** An NSE pick's TERMINAL chart: stored bhavcopy bars (daily ranges) or the tick store's 5-minute bars (1D). Never Yahoo. */
async function nseChartFor(sym: string, range: string): Promise<NseChart> {
  const rows = await nseHistory(sym)
  if (range === '1d') {
    const day = istDay()
    const r = await fetchIntradayBars(sym, '5m', day)
    const c = nseIntradayChart(sym, r.date || day, r.bars, rows)
    if (!c) throw new Error(`no intraday bars stored for ${sym} today (${r.note ?? 'the tick store fills while the Breeze feed is armed'}): pick 1M or longer`)
    return c
  }
  const c = nseDailyChart(sym, rows, range)
  if (!c) throw new Error(`${sym} has no stored NSE daily bars`)
  return c
}
type Tab = 'catalyst' | 'thesis' | 'headlines' | 'technicals' | 'sources'
type Region = 'ALL' | 'US' | 'IN' | 'UK' | 'PINNED'

// ── small building blocks ─────────────────────────────────────────────────────

function Sparkline({ values, width = 64, height = 20 }: { values?: number[]; width?: number; height?: number }) {
  if (!values || values.length < 2) return <span style={{ width, display: 'inline-block' }} />
  const lo = Math.min(...values), hi = Math.max(...values), span = hi - lo || 1
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * width},${height - ((v - lo) / span) * height}`).join(' ')
  const up = values[values.length - 1] >= values[0]
  return (
    <svg width={width} height={height} style={{ display: 'block' }}>
      <polyline points={pts} fill="none" stroke={up ? T.green : T.red} strokeWidth={1.2} />
    </svg>
  )
}

function ConvictionBar({ score }: { score: number }) {
  return (
    <div style={{ display: 'flex', gap: 2 }} title={`Conviction ${score}/10`}>
      {Array.from({ length: 10 }, (_, i) => (
        <span key={i} style={{ width: 4, height: 10, borderRadius: 1,
          background: i < score ? convictionColor(score) : T.border }} />
      ))}
    </div>
  )
}

function RangeBar({ label, lo, hi, value, ccy }: { label: string; lo?: number; hi?: number; value?: number; ccy?: string }) {
  const ok = lo != null && hi != null && value != null && hi > lo
  const pct = ok ? Math.min(100, Math.max(0, ((value! - lo!) / (hi! - lo!)) * 100)) : 0
  return (
    <div style={{ minWidth: 170 }}>
      <div style={{ fontSize: 9, color: T.muted, letterSpacing: 1.2, marginBottom: 4 }}>{label}</div>
      <div style={{ position: 'relative', height: 4, background: T.border, borderRadius: 2 }}>
        {ok && <span style={{ position: 'absolute', left: `calc(${pct}% - 4px)`, top: -3, width: 8, height: 10,
                              background: T.amber, borderRadius: 1 }} />}
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: T.text, marginTop: 4 }}>
        <span>{fmtPrice(lo, ccy)}</span><span>{fmtPrice(hi, ccy)}</span>
      </div>
    </div>
  )
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ minWidth: 88 }}>
      <div style={{ fontSize: 9, color: T.muted, letterSpacing: 1.2 }}>{label}</div>
      <div style={{ fontSize: 13, color: color ?? T.text, marginTop: 3, fontWeight: 600 }}>{value}</div>
    </div>
  )
}

function Chip({ children, color = T.muted, active = false, onClick, title }: {
  children: React.ReactNode; color?: string; active?: boolean; onClick?: () => void; title?: string
}) {
  return (
    <button onClick={onClick} title={title}
      style={{ fontFamily: T.mono, fontSize: 10, letterSpacing: 1, padding: '3px 8px', borderRadius: 2,
               border: `1px solid ${active ? color : T.border}`, color: active ? T.bg : color,
               background: active ? color : 'transparent', cursor: onClick ? 'pointer' : 'default' }}>
      {children}
    </button>
  )
}

// ── main component ───────────────────────────────────────────────────────────

export function NewsTerminal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { addToWatchlist, isWatched } = useWatchlist()
  const [index, setIndex] = useState<ScanIndex | null>(null)
  const [date, setDate] = useState('latest')
  const [scan, setScan] = useState<Scan | null>(null)
  const [scanError, setScanError] = useState<string | null>(null)
  const [quotes, setQuotes] = useState<Record<string, Quote>>({})
  const { pins, toggle: togglePinKey } = usePins()      // shared with every chart in the app
  const [selected, setSelected] = useState<string | null>(null)
  const [region, setRegion] = useState<Region>('ALL')
  const [track, setTrack] = useState<TrackRecordData | null>(null)
  const [showTrack, setShowTrack] = useState(false)
  useEffect(() => {
    if (open && !track) getNewsTrackRecord().then(r => setTrack(r.data)).catch(() => { /* no report yet: view hidden */ })
  }, [open, track])
  const trackBySymbol = useMemo(() => {
    const m = new Map<string, TrackRow[]>()
    for (const r of track?.rows ?? []) if (r.yahoo) m.set(r.yahoo, [...(m.get(r.yahoo) ?? []), r])
    return m
  }, [track])
  const [query, setQuery] = useState('')
  const [range, setRange] = useState<string>('1y')
  const [overlays, setOverlays] = useState<Overlays>({ sma20: true, sma50: true, sma200: true, rsi: true })
  const [mode, setMode] = useState<'terminal' | 'tv'>('terminal')
  const [tab, setTab] = useState<Tab>('catalyst')
  const [chart, setChart] = useState<ChartData | null>(null)
  const [chartState, setChartState] = useState<'idle' | 'loading' | 'error'>('idle')
  const [chartError, setChartError] = useState('')
  const [headlines, setHeadlines] = useState<Headline[] | null>(null)
  const [showRejected, setShowRejected] = useState(false)
  const searchRef = useRef<HTMLInputElement>(null)


  // lock the page behind the terminal while it is open
  useEffect(() => {
    if (!open) return
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => { document.body.style.overflow = prev }
  }, [open])

  // ── scan index + selected scan ────────────────────────────────────────────
  const loadScan = useCallback(async () => {
    try {
      const [ix, sc] = await Promise.all([getNewsScans(), getNewsScan(date)])
      setIndex(ix.data); setScan(sc.data); setScanError(null)
    } catch (err: any) {
      setScanError(apiError(err, 'Scan unavailable'))
    }
  }, [date])

  useEffect(() => { if (open) loadScan() }, [open, loadScan])
  // pick up a new/updated scan file while the terminal is open
  useEffect(() => {
    if (!open) return
    const id = setInterval(async () => {
      try {
        const ix = (await getNewsScans()).data as ScanIndex
        if (date === 'latest' && ix.latest_version && ix.latest_version !== scan?.version) loadScan()
        else setIndex(ix)
      } catch { /* transient */ }
    }, 30_000)
    return () => clearInterval(id)
  }, [open, date, scan?.version, loadScan])

  // ── list = current scan picks (+ pinned from older scans) ──────────────────
  const rows: { pick: Pick; pinnedFrom?: string }[] = useMemo(() => {
    const current = (scan?.picks ?? []).filter(p => p.symbol)
    const inScan = new Set(current.map(p => p.symbol!.yahoo))
    const carried = Object.values(pins)
      .filter(pp => pp.pick.symbol && !inScan.has(pp.pick.symbol.yahoo))
      .map(pp => ({ pick: pp.pick, pinnedFrom: pp.scan_date }))
    let all = [...carried, ...current.map(p => ({ pick: p }))]
    if (region === 'PINNED') all = all.filter(r => pins[r.pick.symbol!.yahoo])
    else if (region !== 'ALL') all = all.filter(r => r.pick.symbol!.region === region)
    const q = query.trim().toUpperCase()
    if (q) all = all.filter(r => r.pick.symbol!.base.includes(q) || (r.pick.company_name || '').toUpperCase().includes(q)
                               || (r.pick.catalyst_category || '').toUpperCase().includes(q))
    return all
  }, [scan, pins, region, query])

  // default selection = highest conviction
  useEffect(() => {
    if (!rows.length) return
    if (!selected || !rows.some(r => r.pick.symbol!.yahoo === selected)) setSelected(rows[0].pick.symbol!.yahoo)
  }, [rows, selected])

  const current = rows.find(r => r.pick.symbol!.yahoo === selected)?.pick
    ?? scan?.picks.find(p => p.symbol?.yahoo === selected) ?? null

  // ── quotes for everything listed ────────────────────────────────────────────
  const symbolsKey = useMemo(() => Array.from(new Set([
    ...(scan?.picks ?? []).map(p => p.symbol?.yahoo), ...Object.keys(pins),
  ].filter(Boolean) as string[])).sort().join(','), [scan, pins])

  // live program (reports/live_nse): the NSE picks' price, move and day range from the live NSE quote service (Breeze
  // websocket → NSE ≈ 1 min → the last close; never Yahoo) every 3 s while the dock is open; round 2: their name, 1M
  // spark and 52-week range from NSE's stored closes. The 60 s quotes call carries the non-NSE picks (US, UK) only —
  // NSE picks too only while the live route answers 404 (not deployed: the pre-live route, labelled by its own source)
  const nsePicks = useMemo(() => (symbolsKey ? symbolsKey.split(',').filter(isNseYahoo).map(y => nseCode(y) as string) : []), [symbolsKey])
  const liveNse = useLiveQuotes(nsePicks, { intervalMs: 3_000, enabled: open })
  const nseBase = useNseBase(nsePicks, { enabled: open })
  const legacy = liveNse.status === 'missing'
  const callKey = yahooCallSymbols(symbolsKey ? symbolsKey.split(',') : [], liveNse.status).join(',')

  useEffect(() => {
    if (!open || !callKey) return
    let alive = true
    const pull = async () => {
      try { const r = await getNewsQuotes(callKey.split(',')); if (alive) setQuotes(q => ({ ...q, ...r.data.quotes })) } catch { /* keep last */ }
    }
    pull()
    const id = setInterval(pull, 60_000)
    return () => { alive = false; clearInterval(id) }
  }, [open, callKey])

  const pickName = useMemo(() => {
    const m = new Map<string, string>()
    for (const p of [...(scan?.picks ?? []), ...Object.values(pins).map(pp => pp.pick)]) if (p.symbol && p.company_name) m.set(p.symbol.yahoo, p.company_name)
    return m
  }, [scan, pins])
  const quotesLive = useMemo(() => {
    if (legacy) return quotes
    const out: Record<string, Quote> = { ...quotes }
    for (const b of nsePicks) {
      const k = `${b}.NS`
      out[k] = nseQuoteRow(b, nseBase.base[b], liveNse.quotes[b], pickName.get(k) ?? null) as unknown as Quote
    }
    return out
  }, [quotes, legacy, liveNse.quotes, nseBase.base, nsePicks, pickName])

  // ── chart + headlines for the selection ────────────────────────────────────
  // an NSE pick's TERMINAL chart is NSE's stored daily bars (1D: the tick store); Yahoo's chart only for non-NSE picks
  const selNse = selected && isNseYahoo(selected) ? nseCode(selected) : null
  const effRange = selNse && !(NSE_RANGES as readonly string[]).includes(range) ? '1mo' : range    // 5D (no NSE source) → 1M
  useEffect(() => {
    if (!open || !selected) return
    let alive = true
    setChartState('loading')
    const req: Promise<ChartData> = selNse ? nseChartFor(selNse, effRange) : getNewsChart(selected, effRange).then(r => r.data as ChartData)
    req
      .then(r => { if (alive) { setChart(r); setChartState('idle') } })
      .catch(err => { if (alive) { setChart(null); setChartState('error')
        setChartError(apiError(err, 'Chart unavailable')) } })
    return () => { alive = false }
  }, [open, selected, effRange, selNse])

  useEffect(() => {
    if (!open || !selected) return
    let alive = true
    setHeadlines(null)
    const pick = scan?.picks.find(p => p.symbol?.yahoo === selected) ?? pins[selected]?.pick
    getNewsHeadlines(selected, pick?.company_name, pick?.symbol?.region ?? 'US')
      .then(r => { if (alive) setHeadlines(r.data.items) }).catch(() => { if (alive) setHeadlines([]) })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, selected])

  // ── keyboard ──────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement)?.tagName === 'INPUT'
      if (e.key === 'Escape') { if (typing) (e.target as HTMLElement).blur(); else onClose() }
      else if (e.key === '/' && !typing) { e.preventDefault(); searchRef.current?.focus() }
      else if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && !typing && rows.length) {
        e.preventDefault()
        const i = rows.findIndex(r => r.pick.symbol!.yahoo === selected)
        const next = e.key === 'ArrowDown' ? Math.min(rows.length - 1, i + 1) : Math.max(0, i - 1)
        setSelected(rows[next].pick.symbol!.yahoo)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, rows, selected, onClose])

  const togglePin = (p: Pick) =>
    togglePinKey(p.symbol!.yahoo, () => ({ pick: p, scan_date: scan?.scan_date ?? '', pinned_at: new Date().toISOString() }))

  if (!open) return null
  // Live 60 s quote first so the header always matches the list; chart quote (5 min cache) is the fallback.
  const q = current?.symbol
    ? (quotesLive[current.symbol.yahoo]?.available ? quotesLive[current.symbol.yahoo] : undefined)
      ?? (chart?.symbol === current.symbol.yahoo ? chart.quote : undefined)
    : undefined
  const st = chart?.symbol === current?.symbol?.yahoo ? chart?.stats : undefined
  const curBase = current?.symbol?.yahoo && /\.NS$/i.test(current.symbol.yahoo) ? current.symbol.yahoo.replace(/\.NS$/i, '') : null
  // an NSE pick's chip is its live row's own (LIVE · BREEZE / DELAYED · NSE / CLOSE / OFFLINE with the reason); the
  // pre-live route (live service not deployed) prints its own state below instead
  const curLive = curBase && !legacy ? liveNse.sourceFor(curBase) : null
  // the TERMINAL chart's own chip: NSE bhavcopy EOD · <last session> / the tick store's 5-minute bars / Yahoo (non-NSE)
  const nseChartData = chart && current?.symbol && chart.symbol === current.symbol.yahoo && 'source_kind' in chart ? (chart as NseChart) : null
  const chartSrc: SourceInfo | null = !nseChartData ? null
    : nseChartData.source_kind === 'tick_store'
      ? { state: 'delayed', source: 'TICK STORE', asOf: nseChartData.candles.length ? new Date(nseChartData.candles[nseChartData.candles.length - 1].time * 1000).toISOString().slice(0, 16) + ':00+05:30' : null,
          ageDays: 0, hint: "5-minute bars built from stored Breeze ticks (tick store); re-read when the range is picked again" }
      : sourceOf(nseChartData.last_date, { source: 'NSE bhavcopy', hint: 'NSE daily bars as traded, split/bonus-adjusted; end of day, not a live feed (the price above is the live quote)' })
  const counts = {
    ALL: (scan?.picks ?? []).length, US: 0, IN: 0, UK: 0, PINNED: Object.keys(pins).length,
  } as Record<Region, number>
  ;(scan?.picks ?? []).forEach(p => { if (p.symbol && p.symbol.region in counts) counts[p.symbol.region as Region]++ })

  return (
    <div role="dialog" aria-label="News Catalyst Terminal"
      style={{ position: 'fixed', inset: 0, top: 'var(--shell-top, 0px)', zIndex: Z.overlay, background: T.bg, color: T.text, fontFamily: T.mono,
               display: 'flex', flexDirection: 'column' }}>
      <style>{`
        @keyframes nt-tape { from { transform: translateX(0) } to { transform: translateX(-50%) } }
        .nt-row:hover { background: ${T.panel2} }
        .nt-scroll::-webkit-scrollbar { width: 6px } .nt-scroll::-webkit-scrollbar-thumb { background: ${T.border} }
        .nt-link { color: ${T.cyan}; text-decoration: none } .nt-link:hover { text-decoration: underline }
      `}</style>

      {/* ── top bar ─────────────────────────────────────────────────────── */}
      <div style={{ height: 44, display: 'flex', alignItems: 'center', gap: 16, padding: '0 16px',
                    borderBottom: `1px solid ${T.border}`, background: '#07090d' }}>
        <span style={{ fontFamily: T.display, fontWeight: 700, letterSpacing: 2, color: T.amber, fontSize: 14 }}>
          ◉ SURYADHANA <span style={{ color: T.dim }}>▸</span> NEWS CATALYST TERMINAL
        </span>
        <select value={date} onChange={e => setDate(e.target.value)}
          style={{ background: T.panel, color: T.text, border: `1px solid ${T.border}`, fontFamily: T.mono,
                   fontSize: 11, padding: '4px 6px' }}>
          <option value="latest">LATEST SCAN</option>
          {index?.scans.map(s => <option key={s.date} value={s.date}>{s.date.replace(/(\d{4})(\d{2})(\d{2})/, '$1-$2-$3')} · {s.picks} picks</option>)}
        </select>
        <span style={{ fontSize: 11, color: T.muted }}>
          {scan ? <>SCAN <span style={{ color: T.text }}>{scan.scan_date}</span> · {scan.picks.length} PICKS · {scan.rejected.length} REJECTED · UPDATED {timeAgo(scan.modified_at)}</> : 'LOADING…'}
        </span>
        <span style={{ flex: 1 }} />
        {track && (() => {
          const v = trackVerdict(track)
          return (
            <Chip color={v.color} active={showTrack} onClick={() => setShowTrack(x => !x)}
              title={`${v.text}. Click for the full track record.`}>
              ▦ TRACK RECORD · {track.picks} PICKS
            </Chip>
          )
        })()}
        <span style={{ fontSize: 10, color: T.dim }}>↑↓ SELECT · / SEARCH · ESC CLOSE</span>
        <Chip color={T.cyan} onClick={loadScan} title="Reload scan">⟳ REFRESH</Chip>
        <button onClick={onClose} aria-label="Close terminal"
          style={{ color: T.muted, fontSize: 18, background: 'none', border: 'none', cursor: 'pointer', padding: '0 4px' }}>✕</button>
      </div>

      {/* ── macro tape ──────────────────────────────────────────────────── */}
      {scan?.macro_context && (
        <div style={{ height: 26, overflow: 'hidden', borderBottom: `1px solid ${T.border}`, background: '#080b10',
                      display: 'flex', alignItems: 'center' }}>
          <span style={{ padding: '0 10px', fontSize: 10, color: T.bg, background: T.amber, height: '100%',
                         display: 'flex', alignItems: 'center', fontWeight: 700, letterSpacing: 1, flexShrink: 0 }}>MACRO</span>
          <div style={{ flex: 1, overflow: 'hidden', height: '100%', display: 'flex', alignItems: 'center' }}>
            <div style={{ whiteSpace: 'nowrap', animation: 'nt-tape 70s linear infinite', fontSize: 11, color: T.text, paddingLeft: 12 }}>
              <span style={{ paddingRight: 80 }}>{scan.macro_context}</span>
              <span style={{ paddingRight: 80 }}>{scan.macro_context}</span>
            </div>
          </div>
        </div>
      )}

      {scanError && (
        <div style={{ padding: 24, color: T.red, fontSize: 13 }}>
          ⚠ {scanError}{index?.directory ? <span style={{ color: T.muted }}> — folder: {index.directory}</span> : null}
        </div>
      )}

      {showTrack && track && <TrackRecordView data={track} />}
      <div style={{ flex: 1, display: showTrack && track ? 'none' : 'grid', gridTemplateColumns: '380px 1fr', minHeight: 0 }}>
        {/* ── left: picks ───────────────────────────────────────────────── */}
        <div style={{ borderRight: `1px solid ${T.border}`, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
          <div style={{ padding: 10, borderBottom: `1px solid ${T.border}`, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <input ref={searchRef} value={query} onChange={e => setQuery(e.target.value)}
              placeholder="SEARCH TICKER / COMPANY / CATALYST  ( / )"
              style={{ background: T.panel, border: `1px solid ${T.border}`, color: T.text, fontFamily: T.mono,
                       fontSize: 11, padding: '6px 8px', outline: 'none' }} />
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {(['ALL', 'US', 'IN', 'UK', 'PINNED'] as Region[]).map(r => (
                <Chip key={r} active={region === r} color={r === 'PINNED' ? T.amber : T.cyan} onClick={() => setRegion(r)}>
                  {r === 'PINNED' ? '★ PINNED' : REGION_LABEL[r] ?? r} {counts[r] ?? 0}
                </Chip>
              ))}
            </div>
          </div>

          <div className="nt-scroll" style={{ flex: 1, overflowY: 'auto' }}>
            {rows.map(({ pick, pinnedFrom }) => {
              const s = pick.symbol!, qq = quotesLive[s.yahoo], sel = s.yahoo === selected
              return (
                <div key={s.yahoo} className="nt-row" onClick={() => setSelected(s.yahoo)}
                  style={{ padding: '8px 10px', borderBottom: `1px solid ${T.border}`, cursor: 'pointer',
                           background: sel ? T.panel2 : undefined, borderLeft: `2px solid ${sel ? T.amber : 'transparent'}` }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontWeight: 700, fontSize: 13, color: sel ? T.amber : T.text, minWidth: 92 }}>
                      {pins[s.yahoo] ? '★ ' : ''}{s.base}
                    </span>
                    <span style={{ fontSize: 9, color: T.dim, border: `1px solid ${T.border}`, padding: '0 4px' }}>{s.exchange}</span>
                    <span style={{ flex: 1 }} />
                    <span title={isNseYahoo(s.yahoo) && !legacy ? baseTitles(qq as never).spark : undefined} data-sd-base={isNseYahoo(s.yahoo) && !legacy ? 'nse_closes' : 'quotes_route'}>
                      <Sparkline values={qq?.spark} /></span>
                    <div style={{ textAlign: 'right', minWidth: 78 }}>
                      <div style={{ fontSize: 12 }}>{qq?.available === false ? 'N/A' : fmtPrice(qq?.price, qq?.currency)}</div>
                      <div style={{ fontSize: 10, color: signColor(qq?.change_pct) }}>{fmtPct(qq?.change_pct)}</div>
                    </div>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 5 }}>
                    <ConvictionBar score={pick.conviction_score ?? 0} />
                    <span style={{ fontSize: 10, color: convictionColor(pick.conviction_score ?? 0) }}>{pick.conviction_score}/10</span>
                    <span style={{ fontSize: 10, color: T.muted, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }}>
                      {pinnedFrom ? `PINNED ${pinnedFrom} · ` : ''}{pick.catalyst_category}
                    </span>
                  </div>
                </div>
              )
            })}
            {!!scan?.unresolved_tickers?.length && (
              <div style={{ padding: '8px 10px', fontSize: 10, color: T.amber, borderBottom: `1px solid ${T.border}` }}>
                ⚠ Could not read ticker(s): {scan.unresolved_tickers.join(', ')}
              </div>
            )}
            {!rows.length && scan && (
              <div style={{ padding: 20, fontSize: 11, color: T.muted }}>No picks match this filter.</div>
            )}

            {scan && scan.rejected.length > 0 && (
              <div style={{ padding: 10 }}>
                <button onClick={() => setShowRejected(v => !v)}
                  style={{ fontFamily: T.mono, fontSize: 10, color: T.muted, background: 'none', border: 'none', cursor: 'pointer', letterSpacing: 1 }}>
                  {showRejected ? '▾' : '▸'} REJECTED BY SCANNER ({scan.rejected.length})
                </button>
                {showRejected && scan.rejected.map(r => (
                  <div key={r.raw_ticker} style={{ fontSize: 10, color: T.muted, padding: '6px 0', borderBottom: `1px dashed ${T.border}` }}>
                    <span style={{ color: T.text }}>{r.raw_ticker}</span> · {r.reason}
                  </div>
                ))}
              </div>
            )}
            {scan?.disclaimer && (
              <div style={{ padding: 10, fontSize: 9, color: T.dim, lineHeight: 1.5 }}>
                ⚠ {scan.disclaimer}{scan.run_log?.length ? <><br />{scan.run_log.join(' · ')}</> : null}
              </div>
            )}
          </div>
        </div>

        {/* ── right: instrument ─────────────────────────────────────────── */}
        {current?.symbol ? (
          <div className="nt-scroll" style={{ overflowY: 'auto', minHeight: 0 }}>
            {/* header */}
            <div style={{ padding: '14px 18px', borderBottom: `1px solid ${T.border}`, display: 'flex', gap: 24, alignItems: 'flex-end', flexWrap: 'wrap' }}>
              <div>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
                  <span style={{ fontFamily: T.display, fontSize: 26, fontWeight: 700, color: T.amber, letterSpacing: 1 }}>{current.symbol.base}</span>
                  <span style={{ fontSize: 11, color: T.muted }}>{current.symbol.tv} · {q?.currency ?? ''}</span>
                  {q?.resolved_symbol && q.resolved_symbol !== current.symbol.yahoo && (
                    <span style={{ fontSize: 10, color: T.amber, border: `1px solid ${T.amberDim}`, padding: '0 4px' }}
                      title={`${current.symbol.yahoo} has no Yahoo data; showing ${q.resolved_symbol}`}>
                      DATA VIA {q.resolved_symbol.endsWith('.BO') ? 'BSE' : 'NSE'}
                    </span>
                  )}
                </div>
                <div style={{ fontSize: 12, color: T.text, marginTop: 2 }}>{q?.name || current.company_name}</div>
              </div>
              <div>
                <div style={{ fontSize: 26, fontWeight: 700 }}>{fmtPrice(q?.price, q?.currency)}</div>
                <div style={{ fontSize: 12, color: signColor(q?.change_pct) }}>
                  {q?.change != null ? fmtChange(q.change, q.currency) : ''} {fmtPct(q?.change_pct)}
                  {curLive ? <> <SourceChip info={curLive} style={{ marginLeft: 4 }} /></> : <>
                  {q?.stale ? <span style={{ color: T.amber }}> · STALE</span> : null}
                  {q?.market_time ? <span style={{ color: T.dim }}> · {new Date(q.market_time * 1000).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })}</span> : null}</>}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <ConvictionBar score={current.conviction_score} />
                <span style={{ fontSize: 11, color: convictionColor(current.conviction_score) }}>CONVICTION {current.conviction_score}/10</span>
              </div>
              <span style={{ flex: 1 }} />
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                <Chip color={T.amber} active={!!pins[current.symbol.yahoo]} onClick={() => togglePin(current)}
                  title="Pinned stocks stay in your list across future scans">
                  {pins[current.symbol.yahoo] ? '★ PINNED' : '☆ PIN'}
                </Chip>
                {current.symbol.region === 'IN' && (
                  <Chip color={T.green} active={isWatched(current.symbol.base)}
                    onClick={() => !isWatched(current.symbol!.base) && addToWatchlist(current.symbol!.base)}
                    title="Adds to the SuryaDhana watchlist (Backtest / Pipeline tabs)">
                    {isWatched(current.symbol.base) ? '✓ IN WATCHLIST' : '+ WATCHLIST'}
                  </Chip>
                )}
                <a href={tradingViewUrl(current.symbol.tv)} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
                  <Chip color={T.cyan}>↗ TRADINGVIEW</Chip>
                </a>
                <a href={`https://finance.yahoo.com/quote/${encodeURIComponent(current.symbol.yahoo)}`} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
                  <Chip color={T.violet}>↗ YAHOO</Chip>
                </a>
              </div>
            </div>

            {/* key stats */}
            <div style={{ padding: '10px 18px', borderBottom: `1px solid ${T.border}`, display: 'flex', gap: 22, flexWrap: 'wrap', alignItems: 'flex-end' }}>
              <RangeBar label="DAY RANGE" lo={q?.day_low} hi={q?.day_high} value={q?.price} ccy={q?.currency} />
              <RangeBar label="52-WEEK RANGE" lo={q?.low_52w} hi={q?.high_52w} value={q?.price} ccy={q?.currency} />
              <Stat label="VOLUME" value={fmtVol(q?.volume)} />
              <Stat label="VOL / 20D AVG" value={st?.volume_ratio != null ? `${fmtNum(st.volume_ratio, 2)}×` : '—'}
                    color={st?.volume_ratio != null && st.volume_ratio > 1.5 ? T.amber : undefined} />
              <Stat label="RSI 14" value={fmtNum(st?.rsi_14)} color={st?.rsi_14 != null ? (st.rsi_14 > 70 ? T.red : st.rsi_14 < 30 ? T.green : undefined) : undefined} />
              <Stat label="ATR %" value={st?.atr_pct != null ? `${fmtNum(st.atr_pct, 2)}%` : '—'} />
              <Stat label="1M" value={fmtPct(st?.ret_1m, 1)} color={signColor(st?.ret_1m)} />
              <Stat label="3M" value={fmtPct(st?.ret_3m, 1)} color={signColor(st?.ret_3m)} />
              <Stat label="TREND" value={st?.above_sma200 == null ? (st?.above_sma50 == null ? '—' : st.above_sma50 ? '▲ >SMA50' : '▼ <SMA50')
                                          : st.above_sma200 ? '▲ >SMA200' : '▼ <SMA200'}
                    color={st?.above_sma200 ?? st?.above_sma50 ? T.green : st?.above_sma200 === false || st?.above_sma50 === false ? T.red : undefined} />
            </div>

            <PriorPicks rows={trackBySymbol.get(current.symbol.yahoo) ?? []} currentScan={scan?.scan_date} />

            {/* chart */}
            <div style={{ borderBottom: `1px solid ${T.border}` }}>
              <div style={{ display: 'flex', gap: 6, padding: '8px 18px', alignItems: 'center', flexWrap: 'wrap' }}>
                <Chip color={T.amber} active={mode === 'terminal'} onClick={() => setMode('terminal')}>TERMINAL</Chip>
                <Chip color={T.amber} active={mode === 'tv'} onClick={() => setMode('tv')}>TRADINGVIEW</Chip>
                <span style={{ width: 12 }} />
                {mode === 'terminal' && (curBase ? NSE_RANGES : RANGES).map(r => (
                  <Chip key={r} color={T.cyan} active={effRange === r} onClick={() => setRange(r)}
                    title={curBase ? (r === '1d' ? "today's 5-minute bars from the tick store (Breeze ticks)" : 'NSE daily bars (bhavcopy), split/bonus-adjusted') : undefined}>{RANGE_LABEL[r]}</Chip>
                ))}
                {mode === 'terminal' && <span style={{ width: 12 }} />}
                {mode === 'terminal' && ([['sma20', 'SMA20', T.cyan], ['sma50', 'SMA50', T.amber], ['sma200', 'SMA200', T.violet], ['rsi', 'RSI', T.amber]] as const).map(([k, label, c]) => (
                  <Chip key={k} color={c} active={overlays[k]} onClick={() => setOverlays(o => ({ ...o, [k]: !o[k] }))}>{label}</Chip>
                ))}
                <span style={{ flex: 1 }} />
                {mode === 'terminal' && chartState === 'loading' && <span style={{ fontSize: 10, color: T.muted }}>LOADING…</span>}
                {mode === 'terminal' && chartState !== 'loading' && chartSrc && <SourceChip info={chartSrc} />}
                {mode === 'terminal' && chartState !== 'loading' && !curBase && chart && chart.symbol === current.symbol.yahoo && <span style={{ fontSize: 10, color: T.dim }}>YAHOO BARS (non-NSE)</span>}
                {mode === 'tv' && current.symbol.region === 'US' && <span style={{ fontSize: 10, color: T.dim }}>TradingView live feed · full toolbar & indicators</span>}
              </div>
              <div style={{ padding: '0 8px 8px' }}>
                {mode === 'tv' && current.symbol.region !== 'US' ? (
                  <div style={{ height: 460, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                                gap: 14, background: T.panel, border: `1px solid ${T.border}` }}>
                    <span style={{ fontFamily: T.display, color: T.amber, fontSize: 16, letterSpacing: 2 }}>
                      {current.symbol.tv}
                    </span>
                    <span style={{ fontSize: 12, color: T.muted, maxWidth: 520, textAlign: 'center', lineHeight: 1.6 }}>
                      TradingView does not allow {current.symbol.exchange} symbols in embedded charts (exchange licensing).
                      Open the full TradingView chart, or use the TERMINAL chart ({curBase ? "NSE's own daily bars, stored bhavcopy" : 'Yahoo bars'}).
                    </span>
                    <a href={tradingViewUrl(current.symbol.tv)} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
                      <Chip color={T.amber} active>↗ OPEN {current.symbol.tv} ON TRADINGVIEW</Chip>
                    </a>
                  </div>
                ) : mode === 'tv' ? (
                  <TradingViewEmbed tvSymbol={current.symbol.tv} height={460} />
                ) : chartState === 'error' ? (
                  <div style={{ height: 460, display: 'flex', alignItems: 'center', justifyContent: 'center', color: T.muted, fontSize: 12, flexDirection: 'column', gap: 8 }}>
                    <span style={{ color: T.amber }}>NO PRICE HISTORY</span>
                    <span>{chartError}</span>
                    <span style={{ color: T.dim }}>{curBase ? 'No stored NSE bars for this range — try 1M or longer, or the TradingView view.' : 'Newly listed or unsupported on Yahoo — try the TradingView view.'}</span>
                  </div>
                ) : chart && chart.symbol === current.symbol.yahoo ? (
                  <NewsChart data={chart} overlays={overlays} height={460} />
                ) : (
                  <div style={{ height: 460 }} />
                )}
              </div>
            </div>

            {/* tabs */}
            <div style={{ display: 'flex', gap: 0, borderBottom: `1px solid ${T.border}`, padding: '0 18px' }}>
              {(['catalyst', 'thesis', 'headlines', 'technicals', 'sources'] as Tab[]).map(t => (
                <button key={t} onClick={() => setTab(t)}
                  style={{ fontFamily: T.mono, fontSize: 11, letterSpacing: 1.5, padding: '10px 14px', background: 'none', border: 'none',
                           borderBottom: `2px solid ${tab === t ? T.amber : 'transparent'}`, color: tab === t ? T.amber : T.muted, cursor: 'pointer' }}>
                  {t.toUpperCase()}{t === 'headlines' && headlines ? ` (${headlines.length})` : ''}{t === 'sources' ? ` (${current.sources.length})` : ''}
                </button>
              ))}
            </div>

            <div style={{ padding: '14px 18px 40px', fontSize: 12, lineHeight: 1.65 }}>
              {tab === 'catalyst' && (
                <div style={{ display: 'grid', gap: 14 }}>
                  {current.catalyst_category && (
                    <div><Chip color={T.amber} active>{current.catalyst_category}</Chip></div>
                  )}
                  {current.news.length === 0 && (
                    <div style={{ color: T.muted, fontSize: 12 }}>
                      {(current.catalyst_category ?? '').startsWith('Pinned from')
                        ? `You pinned ${current.symbol.base} from a chart; it did not come from a news scan.`
                        : `This scan has no news text for ${current.symbol.base} (the scanner's output schema has no news field).`}{' '}
                      <button onClick={() => setTab('headlines')} style={{ color: T.cyan, background: 'none', border: 'none',
                              cursor: 'pointer', fontFamily: T.mono, fontSize: 12, padding: 0 }}>See live HEADLINES →</button>
                    </div>
                  )}
                  {current.news.length > 0 && <div style={{ borderLeft: `2px solid ${T.border}`, paddingLeft: 14, display: 'grid', gap: 12 }}>
                    {current.news.map((n, i) => (
                      <div key={i} style={{ position: 'relative' }}>
                        <span style={{ position: 'absolute', left: -19, top: 6, width: 8, height: 8, borderRadius: 4, background: T.amber }} />
                        <div style={{ fontSize: 10, color: T.amber, letterSpacing: 1 }}>{n.date ?? 'UNDATED'}</div>
                        <div style={{ color: T.text }}>{n.text}</div>
                      </div>
                    ))}
                  </div>}
                  {current.market_consensus_gap && (
                    <div style={{ background: T.panel, border: `1px solid ${T.border}`, padding: 12 }}>
                      <div style={{ fontSize: 10, color: T.cyan, letterSpacing: 1.5, marginBottom: 4 }}>MARKET CONSENSUS GAP</div>
                      <div>{current.market_consensus_gap}</div>
                    </div>
                  )}
                </div>
              )}

              {tab === 'thesis' && current.thesis_steps.length === 0 && (
                <span style={{ color: T.muted }}>No reflexivity thesis in this scan for {current.symbol.base}.</span>
              )}
              {tab === 'thesis' && current.thesis_steps.length > 0 && (
                <div style={{ display: 'grid', gap: 10 }}>
                  {current.thesis_steps.map((s, i) => (
                    <div key={i} style={{ display: 'flex', gap: 12 }}>
                      <span style={{ fontFamily: T.display, color: T.amber, fontWeight: 700, minWidth: 22 }}>{String(i + 1).padStart(2, '0')}</span>
                      <span>{s}</span>
                    </div>
                  ))}
                  <div style={{ marginTop: 8, fontSize: 11, color: T.muted }}>
                    Conviction <span style={{ color: convictionColor(current.conviction_score) }}>{current.conviction_score}/10</span> · from scan {scan?.scan_date}
                  </div>
                </div>
              )}

              {tab === 'headlines' && (
                headlines === null ? <span style={{ color: T.muted }}>Loading headlines…</span>
                : headlines.length === 0 ? <span style={{ color: T.muted }}>No headlines found for {current.company_name} ({current.symbol.yahoo}).</span>
                : <div style={{ display: 'grid', gap: 10 }}>
                    {headlines.map((h, i) => (
                      <a key={i} href={h.link} target="_blank" rel="noreferrer" className="nt-link"
                        style={{ display: 'flex', gap: 12, padding: 10, background: T.panel, border: `1px solid ${T.border}` }}>
                        {h.thumbnail && <img src={h.thumbnail} alt="" width={84} height={56} style={{ objectFit: 'cover', flexShrink: 0 }} />}
                        <div>
                          <div style={{ color: T.text, fontSize: 12 }}>{h.title}</div>
                          <div style={{ fontSize: 10, color: T.muted, marginTop: 4 }}>
                            <span style={{ color: h.feed === 'Google News' ? T.violet : T.amber }}>{h.feed === 'Google News' ? 'GOOGLE NEWS' : 'YAHOO'}</span>
                            {' · '}{h.publisher} · {timeAgo(h.published_at)}{h.related?.length ? ` · ${h.related.slice(0, 4).join(', ')}` : ''}
                          </div>
                        </div>
                      </a>
                    ))}
                  </div>
              )}

              {tab === 'technicals' && (
                st ? (
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 10 }}>
                    {([
                      ['1D', fmtPct(st.ret_1d), signColor(st.ret_1d)], ['5D', fmtPct(st.ret_5d), signColor(st.ret_5d)],
                      ['1M', fmtPct(st.ret_1m), signColor(st.ret_1m)], ['3M', fmtPct(st.ret_3m), signColor(st.ret_3m)],
                      ['6M', fmtPct(st.ret_6m), signColor(st.ret_6m)], ['1Y', fmtPct(st.ret_1y), signColor(st.ret_1y)],
                      ['RSI 14', fmtNum(st.rsi_14), undefined], ['ATR % (14D)', st.atr_pct != null ? `${fmtNum(st.atr_pct, 2)}%` : '—', undefined],
                      ['SMA 20', fmtPrice(st.sma20, q?.currency), undefined], ['SMA 50', fmtPrice(st.sma50, q?.currency), undefined],
                      ['SMA 200', fmtPrice(st.sma200, q?.currency), undefined],
                      ['FROM 52W HIGH', fmtPct(st.pct_from_52w_high, 1), signColor(st.pct_from_52w_high)],
                      ['FROM 52W LOW', fmtPct(st.pct_from_52w_low, 1), signColor(st.pct_from_52w_low)],
                      ['AVG VOL 20D', fmtVol(st.avg_volume_20d), undefined],
                      ['HISTORY', `${st.history_days} days`, undefined],
                    ] as [string, string, string | undefined][]).map(([k, v, c]) => (
                      <div key={k} style={{ background: T.panel, border: `1px solid ${T.border}`, padding: 10 }}>
                        <div style={{ fontSize: 9, color: T.muted, letterSpacing: 1.2 }}>{k}</div>
                        <div style={{ fontSize: 14, color: c ?? T.text, marginTop: 4, fontWeight: 600 }}>{v}</div>
                      </div>
                    ))}
                  </div>
                ) : <span style={{ color: T.muted }}>{chartState === 'error' ? 'No price history for technicals.' : 'Loading…'}</span>
              )}

              {tab === 'sources' && current.sources.length === 0 && (
                <span style={{ color: T.muted }}>The scan lists no sources for {current.symbol.base}.</span>
              )}
              {tab === 'sources' && current.sources.length > 0 && (
                <div style={{ display: 'grid', gap: 8 }}>
                  {current.sources.map((s, i) => (
                    <a key={i} href={s.url} target="_blank" rel="noreferrer" className="nt-link"
                      style={{ display: 'flex', gap: 10, padding: 8, background: T.panel, border: `1px solid ${T.border}` }}>
                      <span style={{ color: T.amber, minWidth: 190, fontSize: 11 }}>{s.domain}</span>
                      <span style={{ fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.url}</span>
                    </a>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', color: T.muted, fontSize: 12 }}>
            {scan ? 'Select a ticker' : scanError ? '' : 'Loading scan…'}
          </div>
        )}
      </div>
    </div>
  )
}
