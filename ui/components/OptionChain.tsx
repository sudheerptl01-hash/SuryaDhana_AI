'use client'

import { Z } from '@/lib/z'
import { apiError } from '@/lib/errors'
/**
 * OMON — end-of-day option chain for NIFTY, BANKNIFTY or any F&O stock, from NSE's F&O bhavcopy:
 * open interest per strike (where writers sit = support / resistance), OI change, implied volatility smile,
 * put/call ratio, max pain and the move the options price in by expiry. LIVE from NSE during the session (every 30 s,
 * same engine), otherwise the last published end-of-day F&O bhavcopy.
 * Open from GO: `OMON` or `OMON RELIANCE`.
 *
 * Terminal v2 (reports/terminal_v2/PLAN.md 0.6 / 1.1 / 1.3), chain-first: the expiry ladder carries each expiry's stored
 * ATM IV; the chain header strip (term, 25Δ skew + its 1-year percentile, straddle vs 1σ, IV vs RV20 cc / Parkinson /
 * YZ / FOVOLT); the IV history collapses to a strip above the chain (iv30_cm + India VIX overlay, "IV percentile" and
 * "IV rank" each defined on hover — the old "IV rank 73" was a percentile); Greeks Δ Γ Θ ν per strike from lib/black76
 * on the strike's own IV; j / k move a strike cursor, space picks up to four strikes, "OPEN IN OSTR" carries symbol +
 * expiry + strikes through lib/activeSymbol; the 15-minute IV path in LIVE mode. PCR prints in the neutral token
 * (≥ 1 used to be green). Badges: chain / smile / Greeks `arithmetic`; OI, walls, % MWPL `context`.
 */
import { OptionPricer, type PricerPick } from '@/components/OptionPricer'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getSurveillance, getOptionChain, getOptionChainLive, getOptionHistory, type OptionChain as Chain, type OptionHistoryRow } from '@/lib/api'
import { BadgeChip, CHART_BOX, Chip, ErrorBox, Loading, PageHeader, Panel, Stat, T, fmtNum, nseStampIso, sourceOf, useChartSize } from '@/components/terminal'
import { IvHistoryChart, useIvHistory } from '@/components/vol/IvHistoryChart'
import { ChainStrip, greeksFor } from '@/components/vol/ChainStrip'
import { IvLivePath } from '@/components/vol/IvLivePath'
import { getIvSurface, getVolScreen, type IvSurface, type ScreenRow } from '@/components/vol/api'
import { legsFromStrikes } from '@/components/vol/volModel'
import { useActiveSymbol } from '@/lib/activeSymbol'
import { goToPage } from '@/lib/navigate'
import { niceAxis, niceTicks, pickRoundLabels, staggerRows, textWidth } from '@/components/terminal/chart'
import { atmIndex, edgeLabel, omonInitialSymbol, wallMarks } from '@/components/omonModel'
import { useRequestSeq } from '@/components/useRequestSeq'

export { OMON_KEY } from '@/lib/pageKeys'
import { OMON_KEY } from '@/lib/pageKeys'
const num = fmtNum
const lakh = (v?: number | null) => (v == null ? '—' : Math.abs(v) >= 1e7 ? `${(v / 1e7).toFixed(2)} cr` : Math.abs(v) >= 1e5 ? `${(v / 1e5).toFixed(1)} L` : num(v))
/** OI change with an explicit sign: '+' for builds, U+2212 for unwinds (C1-18) */
const signedLakh = (v: number) => (v > 0 ? `+${lakh(v)}` : v < 0 ? `−${lakh(-v)}` : lakh(0))
const readHandoff = (): string | null => { try { return localStorage.getItem(OMON_KEY) } catch { return null } }
const INDEX_UNDERLYINGS = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50']
/** Greeks in the chain: Δ to 2 dp, Γ in significant digits (it is per index point), Θ per day and ν per vol point in ₹ per unit */
const gfmt = (v: number | null | undefined, kind: 'd' | 'g' | 't' | 'v') => {
  if (v == null || !Number.isFinite(v)) return ''
  if (kind === 'g') return v === 0 ? '0' : v < 0.001 ? v.toFixed(5) : v.toFixed(4)
  if (kind === 'd') return `${v < 0 ? '−' : ''}${Math.abs(v).toFixed(2)}`
  return `${v < 0 ? '−' : ''}${Math.abs(v).toFixed(kind === 't' ? 1 : 2)}`
}
const SEED_NAME: Record<number, string> = { 1: 'long straddle', 2: 'long strangle', 3: 'iron fly', 4: 'iron condor' }

function Smile({ data }: { data: Chain }) {
  const { ref, w: W, h: H } = useChartSize(420, 150)   // CSS px: 9 px axis text at any width (C1-17)
  // out-of-the-money IV: puts below the forward, calls above (where prices are informative)
  const pts = data.rows.map(r => ({ k: r.strike, iv: data.forward != null && r.strike < data.forward ? (r.pe.iv ?? r.ce.iv) : (r.ce.iv ?? r.pe.iv) }))
    .filter((p): p is { k: number; iv: number } => p.iv != null)
  if (pts.length < 3) return <div ref={ref} style={{ fontSize: 11, color: T.dim, padding: 10 }}>Not enough traded strikes for a smile.</div>
  const P = 30
  const kLo = pts[0].k, kHi = pts[pts.length - 1].k
  const vLo = Math.min(...pts.map(p => p.iv)) * 0.95, vHi = Math.max(...pts.map(p => p.iv)) * 1.05
  const x = (k: number) => P + ((k - kLo) / (kHi - kLo || 1)) * (W - 2 * P)
  const y = (v: number) => 8 + (1 - (v - vLo) / (vHi - vLo || 1)) * (H - 30)
  const iv = niceAxis(vLo, vHi, 3)
  // strike ticks: round strikes, thinned to ≥ 56 px apart, kept clear of the first/last labels and 'fwd'
  const kTicks = niceTicks(kLo, kHi, Math.max(2, Math.floor((W - 2 * P) / 70)))
    .filter(k => x(k) - x(kLo) > 44 && x(kHi) - x(k) > 44 && (data.forward == null || Math.abs(x(k) - x(data.forward)) > 30))
  return (
    <div ref={ref} style={CHART_BOX}>
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }} role="img" aria-label="Implied volatility smile">
      {iv.ticks.map(v => (
        <g key={v}>
          <line x1={P} x2={W - P} y1={y(v)} y2={y(v)} stroke={T.border} strokeDasharray="2 4" />
          <text x={P - 4} y={y(v) + 3} textAnchor="end" fontSize={9} fill={T.dim} fontFamily={T.mono}>{v.toFixed(iv.dp)}%</text>
        </g>
      ))}
      {kTicks.map(k => <text key={k} x={x(k)} y={H - 6} textAnchor="middle" fontSize={9} fill={T.dim} fontFamily={T.mono}>{k.toLocaleString('en-IN')}</text>)}
      {data.forward != null && <line x1={x(data.forward)} x2={x(data.forward)} y1={6} y2={H - 22} stroke={T.amber} strokeDasharray="3 3" />}
      <path d={pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.k).toFixed(1)},${y(p.iv).toFixed(1)}`).join('')} fill="none" stroke={T.violet} strokeWidth={1.8} />
      {pts.map(p => <circle key={p.k} cx={x(p.k)} cy={y(p.iv)} r={1.8} fill={T.violet} />)}
      <text x={P} y={H - 6} fontSize={9} fill={T.dim} fontFamily={T.mono}>{kLo.toLocaleString('en-IN')}</text>
      <text x={W - P} y={H - 6} textAnchor="end" fontSize={9} fill={T.dim} fontFamily={T.mono}>{kHi.toLocaleString('en-IN')}</text>
      {data.forward != null && <text x={x(data.forward)} y={H - 6} textAnchor="middle" fontSize={9} fill={T.amber} fontFamily={T.mono}>fwd</text>}
    </svg>
    </div>
  )
}

function OiBars({ data }: { data: Chain }) {
  const { ref, w: W, h: H } = useChartSize(420, 150)   // CSS px (C1-17)
  const rows = data.rows.filter(r => (r.ce.oi ?? 0) + (r.pe.oi ?? 0) > 0)
  if (!rows.length) return <div ref={ref} />
  const P = 30, n = rows.length, TOP = 14
  const m = Math.max(...rows.flatMap(r => [r.ce.oi ?? 0, r.pe.oi ?? 0]), 1)
  const bw = (W - 2 * P) / n
  // strike axis (C1-17): ATM and the two OI walls are always labelled; other labels sit on round strikes, thinned
  // so they never overlap; the few must-labels that sit next to each other drop to a second row
  // RUP-01 / CT-02: the walls are the server's (most call / put OI over ALL strikes: the OI WALLS stat, the chain
  // highlight and BRF), never the biggest bar in this ±6 % window. A wall outside the window gets an edge marker.
  const strikes = rows.map(r => r.strike)
  const atm = atmIndex(strikes, data.atm, data.forward)
  const marks = wallMarks(strikes, data.resistance, data.support)
  const onBar = (side: 'call' | 'put') => { const m = marks.find(x => x.side === side); return m && m.at === 'bar' ? m.index : -1 }
  const callWall = onBar('call'), putWall = onBar('put')
  const widest = Math.max(...rows.map(r => textWidth(r.strike.toLocaleString('en-IN'), 9)))
  const labelled = pickRoundLabels(strikes, bw, widest + 10, [atm, callWall, putWall].filter(i => i >= 0))
  const cx = (i: number) => P + i * bw + bw / 2
  const lx = (i: number) => Math.min(Math.max(cx(i), P + widest / 2), W - P - widest / 2)
  const labelRow = staggerRows(labelled.map(i => ({ x: lx(i), w: textWidth(rows[i].strike.toLocaleString('en-IN'), 9) })), 6)
  const AXIS = H - 22 - Math.max(0, ...labelRow) * 11
  const y = (v: number) => (v / m) * (AXIS - TOP)
  // wall labels: bar labels first (they sit on their bar), then edge markers in the lowest top row that collides
  // with no label already placed (a put wall near the right edge never hides a 'CALL WALL 24,000 →' marker)
  const fmtK = (v: number) => v.toLocaleString('en-IN')
  const both = callWall >= 0 && callWall === putWall
  type WallLabel = { side: 'call' | 'put'; text: string; x: number; y: number; x0: number; x1: number; anchor: 'start' | 'middle' | 'end'; color: string; edge?: string; tip?: string }
  const wallLabels: WallLabel[] = []
  for (const wm of [...marks].sort((a, b) => Number(a.at !== 'bar') - Number(b.at !== 'bar'))) {
    const color = wm.side === 'call' ? T.red : T.green
    if (wm.at === 'bar') {
      if (both && wm.side === 'put') continue                // one label for a strike that holds both walls
      const text = both ? 'CALL · PUT WALL' : wm.side === 'call' ? 'CALL WALL' : 'PUT WALL'
      const r = rows[wm.index], v = Math.max(r.ce.oi ?? 0, r.pe.oi ?? 0)
      const tw = textWidth(text, 8.5)
      const x = Math.min(Math.max(cx(wm.index), P + tw / 2), W - P - tw / 2)
      wallLabels.push({ side: wm.side, text, x, y: Math.max(TOP - 3, AXIS - y(v) - 4), x0: x - tw / 2, x1: x + tw / 2, anchor: 'middle', color: both ? T.amber : color })
      continue
    }
    const text = wm.at === 'between' ? `${edgeLabel(wm, fmtK)} ${fmtK(wm.strike)}` : edgeLabel(wm, fmtK)
    const tw = textWidth(text, 8.5)
    const x = wm.at === 'between' ? Math.min(Math.max(P + wm.pos * bw + bw / 2, P + tw / 2), W - P - tw / 2) : wm.at === 'right' ? W - P : P
    const anchor = wm.at === 'right' ? 'end' : wm.at === 'left' ? 'start' : 'middle'
    const x0 = anchor === 'end' ? x - tw : anchor === 'start' ? x : x - tw / 2, x1 = x0 + tw
    const rowY = (k: number) => TOP - 3 + k * 10
    let row = 0
    while (row < 3 && wallLabels.some(l => Math.abs(l.y - rowY(row)) < 9 && l.x0 < x1 + 4 && x0 < l.x1 + 4)) row++
    wallLabels.push({ side: wm.side, text, x, y: rowY(row), x0, x1, anchor, color, edge: wm.at,
      tip: `${wm.side === 'call' ? 'Call' : 'Put'} wall ${fmtK(wm.strike)}: the strike with the most ${wm.side} open interest of the expiry, outside the plotted strike window` })
  }
  return (
    <div ref={ref} style={CHART_BOX}>
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }} role="img" aria-label="Open interest by strike">
      {rows.map((r, i) => (
        <g key={r.strike}>
          <rect x={P + i * bw} y={AXIS - y(r.ce.oi ?? 0)} width={Math.max(bw / 2 - 0.5, 0.5)} height={y(r.ce.oi ?? 0)} fill={T.red} opacity={0.75}>
            <title>{`${r.strike}: calls ${(r.ce.oi ?? 0).toLocaleString('en-IN')} · puts ${(r.pe.oi ?? 0).toLocaleString('en-IN')}`}</title>
          </rect>
          <rect x={P + i * bw + bw / 2} y={AXIS - y(r.pe.oi ?? 0)} width={Math.max(bw / 2 - 0.5, 0.5)} height={y(r.pe.oi ?? 0)} fill={T.green} opacity={0.75} />
        </g>
      ))}
      {atm >= 0 && <line x1={cx(atm)} x2={cx(atm)} y1={6} y2={AXIS} stroke={T.amber} strokeDasharray="3 3" />}
      <line x1={P} x2={W - P} y1={AXIS} y2={AXIS} stroke={T.border} />
      {labelled.map((i, k) => {
        const c = i === atm ? T.amber : i === callWall ? T.red : i === putWall ? T.green : T.dim
        return (
          <g key={rows[i].strike}>
            <line x1={cx(i)} x2={cx(i)} y1={AXIS} y2={AXIS + 3 + labelRow[k] * 11} stroke={c} />
            <text x={lx(i)} y={AXIS + 14 + labelRow[k] * 11} textAnchor="middle"
                  fontSize={9} fill={c} fontFamily={T.mono} fontWeight={c === T.dim ? 400 : 600}>{rows[i].strike.toLocaleString('en-IN')}</text>
          </g>
        )
      })}
      {/* the server's walls: named above their bar, or an edge marker when the strike is outside the plotted window */}
      {wallLabels.map(l => (
        <text key={l.side} x={l.x} y={l.y} textAnchor={l.anchor} fontSize={8.5} fill={l.color} fontFamily={T.mono} letterSpacing={0.5}
              data-wall={l.side} data-wall-edge={l.edge}>{l.tip && <title>{l.tip}</title>}{l.text}</text>
      ))}
    </svg>
    </div>
  )
}

export function OptionChain() {
  // CT-01: 'RELIANCE OMON' from another page writes the hand-off key before this page mounts; start on it, so the
  // first request is RELIANCE's (it used to start on NIFTY and race the RELIANCE request: the later answer won)
  const [symbol, setSymbol] = useState(() => omonInitialSymbol(readHandoff()))
  const [expiry, setExpiry] = useState<string | null>(null)
  const [data, setData] = useState<Chain | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [input, setInput] = useState('')
  const [live, setLive] = useState(() => { const d = new Date(), m = d.getHours() * 60 + d.getMinutes(); return d.getDay() >= 1 && d.getDay() <= 5 && m >= 555 && m <= 935 })
  const [liveNote, setLiveNote] = useState<string | null>(null)
  const [underlyings, setUnderlyings] = useState<string[]>([])
  const [pricer, setPricer] = useState<PricerPick | null>(null)
  const [rolled, setRolled] = useState<string | null>(null)       // the settled expiry we moved past
  const [ban, setBan] = useState<{ list: string[]; date: string | null } | null>(null)
  useEffect(() => { getSurveillance([]).then(r => setBan({ list: r.data.ban, date: r.data.dates.ban ?? null })).catch(() => {}) }, [])
  // terminal v2: picked strikes (≤ 4, carried to OSTR), the j/k strike cursor, Greeks columns, the history strip
  const [picks, setPicks] = useState<number[]>([])
  const [cursor, setCursor] = useState<number | null>(null)
  const [greeks, setGreeks] = useState(true)
  const [histOpen, setHistOpen] = useState(false)
  const [surface, setSurface] = useState<IvSurface | null>(null)
  const [screenRow, setScreenRow] = useState<ScreenRow | null>(null)
  const [, writeActive] = useActiveSymbol()

  useEffect(() => {
    const read = () => { const s = readHandoff(); if (s) { setSymbol(omonInitialSymbol(s)); setExpiry(null) } }
    read()
    window.addEventListener('suryadhana:omon', read)
    return () => window.removeEventListener('suryadhana:omon', read)
  }, [])
  // CT-01 / P1: latest request wins. A response for a superseded symbol / expiry / mode is dropped, whatever order NSE
  // and the bhavcopy cache answer in. The guard lives in a ref (useRequestSeq), never in useMemo.
  const seq = useRequestSeq()
  const selection = `${symbol}|${expiry ?? ''}|${live ? 'live' : 'eod'}`
  const load = useCallback((refresh = false) => {
    // the 30 s LIVE refresh never supersedes a slower answer for the same selection (live chain ≤ 40 s, then the EOD
    // fallback): it used to drop every answer slower than 30 s, and OMON stayed on 'Loading …' with no error
    if (refresh && seq.busy(selection)) return
    const mine = seq.begin(selection), current = () => seq.isCurrent(mine)
    setError(null)
    const eod = () => getOptionChain(symbol, expiry ?? undefined).then(r => {
      if (!current()) return
      setData(r.data); if (r.data.underlyings) setUnderlyings(r.data.underlyings)
    })
    const fail = (e: unknown) => { if (current()) { setData(null); setError(apiError(e, 'Option chain unavailable')) } }
    const run = !live ? eod().catch(fail)
      : getOptionChainLive(symbol, expiry ?? undefined).then(r => { if (current()) { setData(r.data); setLiveNote(null) } })
        .catch(e => {                                 // NSE live down or throttled: fall back to end of day
          if (!current()) return
          setLiveNote(`live chain unavailable (${apiError(e).slice(0, 80)}): showing end of day`)
          return eod().catch(fail)
        })
    void run.finally(() => seq.settle(mine))
  }, [symbol, expiry, live, seq, selection])
  // a new underlying never shows the previous one's chain while it loads (the page says LOADING <symbol>), nor its
  // pricer leg or settled-series note (the GO hand-off event changes the symbol without going through pick())
  useEffect(() => { setData(null); setLiveNote(null); setPricer(null); setRolled(null) }, [symbol])
  useEffect(() => { setPicks([]); setCursor(null) }, [symbol, expiry])
  // the stored surface (term ladder, skew) and the stored IV history: B1's tables; both degrade alone while not deployed
  useEffect(() => {
    let alive = true
    setSurface(null)
    getIvSurface(symbol, '1m').then(r => { if (alive) setSurface(r.data) }).catch(() => { if (alive) setSurface(null) })
    return () => { alive = false }
  }, [symbol])
  const ivHist = useIvHistory(symbol, 750)
  // % of the market-wide position limit for a stock (context): the VOL screener's row, read once per symbol
  useEffect(() => {
    let alive = true
    setScreenRow(null)
    if (INDEX_UNDERLYINGS.includes(symbol)) return
    getVolScreen('iv_pctile').then(r => { if (alive && r.data.ok) setScreenRow(r.data.rows.find(x => x.symbol === symbol) ?? null) }).catch(() => {})
    return () => { alive = false }
  }, [symbol])
  useEffect(() => { load() }, [load])
  useEffect(() => {   // after the close on an expiry day the default series has settled: show the next one instead
    if (!data || expiry || data.days_to_expiry > 0) return
    const next = data.expiries.find(e => e > data.expiry)
    if (next) { setRolled(data.expiry); setExpiry(next) }
  }, [data, expiry])
  useEffect(() => { if (!live) return; const iv = setInterval(() => load(true), 30_000); return () => clearInterval(iv) }, [live, load])
  useEffect(() => { getOptionChain('NIFTY').then(r => setUnderlyings(r.data.underlyings ?? [])).catch(() => {}) }, [])

  const pick = (s: string) => {
    const v = s.trim().toUpperCase()
    if (!v) return
    try { localStorage.setItem(OMON_KEY, v) } catch { /* private window */ }
    setSymbol(v); setExpiry(null); setInput(''); setPricer(null); setRolled(null)
    writeActive({ symbol: v })                         // the active-symbol store (PLAN 1.3): OSTR / DERV start here
  }
  const togglePick = (k: number) => setPicks(p => (p.includes(k) ? p.filter(x => x !== k) : p.length >= 4 ? [...p.slice(1), k] : [...p, k]).sort((a, b) => a - b))
  const openInOstr = () => {
    if (!data) return
    writeActive({ symbol: data.symbol, expiry: data.expiry, strikes: picks })
    goToPage('ostrategy')
  }
  const onChainKey = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (!data || (e.target as HTMLElement).closest('input, textarea, select')) return
    const n = data.rows.length
    const at = cursor ?? Math.max(0, data.rows.findIndex(r => r.strike === data.atm))
    const move = (i: number) => {
      const j = Math.max(0, Math.min(n - 1, i))
      setCursor(j)
      scrollRef.current?.querySelector<HTMLElement>(`[data-strike-row="${j}"]`)?.scrollIntoView({ block: 'nearest' })
    }
    if (e.key === 'j' || e.key === 'ArrowDown') { e.preventDefault(); move(cursor == null ? at : at + 1) }
    else if (e.key === 'k' || e.key === 'ArrowUp') { e.preventDefault(); move(cursor == null ? at : at - 1) }
    else if ((e.key === ' ' || e.key === 'x') && cursor != null) { e.preventDefault(); togglePick(data.rows[cursor].strike) }
    else if (e.key === 'o' && picks.length) { e.preventDefault(); openInOstr() }
    else if (e.key === 'Escape' && cursor != null) { e.stopPropagation(); setCursor(null) }
  }

  const scrollRef = useRef<HTMLDivElement>(null)
  const centred = useRef('')
  useEffect(() => {                                   // centre on the at-the-money strike once per symbol/expiry, not on every live refresh
    const key = `${data?.symbol}|${data?.expiry}`
    const box = scrollRef.current, row = box?.querySelector<HTMLElement>('[data-atm="1"]')
    if (data && box && row && centred.current !== key) { box.scrollTop = row.offsetTop - box.clientHeight / 2; centred.current = key }
  }, [data])
  const maxOi = useMemo(() => Math.max(1, ...(data?.rows ?? []).flatMap(r => [r.ce.oi ?? 0, r.pe.oi ?? 0])), [data])
  const walls = useMemo(() => new Set([...(data?.resistance ?? []).slice(0, 1), ...(data?.support ?? []).slice(0, 1)]), [data])
  const hasNseDelta = useMemo(() => (data?.rows ?? []).some(r => r.ce.nse_delta != null || r.pe.nse_delta != null), [data])
  // PLAN §0.5: LIVE · NSE in session, else the bhavcopy's date (daily data shows its date, never a clock)
  const chainSource = data?.live ? sourceOf(nseStampIso(data.as_of) ?? data.date, { live: true, source: 'NSE' })
    : sourceOf(data?.date ?? null, { source: 'NSE F&O bhavcopy', hint: liveNote })

  return (
    <div>
      <PageHeader code="OMON" title="Option Monitor"
        subtitle={data ? (data.live
          ? `${data.symbol} · LIVE NSE option chain · as of ${data.as_of ?? '—'} · expiry ${data.expiry} (${data.days_to_expiry}d) · lot ${data.lot ?? '—'} · every 30 s`
          : `${data.symbol} · NSE F&O bhavcopy ${data.date} · expiry ${data.expiry} (${data.days_to_expiry}d) · lot ${data.lot ?? '—'} · end of day`) : 'option chain'}
        right={<form onSubmit={e => { e.preventDefault(); pick(input) }} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <Chip color={T.green} active={live} onClick={() => setLive(true)}>● LIVE</Chip>
          <Chip color={T.muted} active={!live} onClick={() => setLive(false)}>EOD</Chip>
          <span style={{ width: 6 }} />
          {['NIFTY', 'BANKNIFTY', 'FINNIFTY'].map(s => <Chip key={s} color={T.amber} active={symbol === s} onClick={() => pick(s)}>{s}</Chip>)}
          <input list="omon-underlyings" value={input} onChange={e => setInput(e.target.value)} placeholder="F&O stock…"
            style={{ background: T.panel, border: `1px solid ${T.border}`, color: T.text, fontFamily: T.mono, fontSize: 11, padding: '4px 8px', width: 130, outline: 'none', textTransform: 'uppercase' }} />
          <datalist id="omon-underlyings">{underlyings.map(u => <option key={u} value={u} />)}</datalist>
        </form>} />
      {error && <ErrorBox error={error} onRetry={() => load()} />}
      {liveNote && <div style={{ fontSize: 11, color: T.amber, marginBottom: 8 }}>⚠ {liveNote}</div>}
      {ban && ban.list.includes(symbol) && <div style={{ fontSize: 11.5, color: T.red, border: `1px solid ${T.red}55`, padding: '6px 10px', marginBottom: 8 }}>
        ⚑ {symbol} is in the F&O ban period{ban.date ? ` for ${ban.date}` : ''}: open interest crossed 95% of the market-wide limit, so no new positions (only closing trades) until it drops below 80%.</div>}
      {ban && ban.list.length > 0 && <div style={{ fontSize: 10.5, color: T.muted, marginBottom: 8 }}>
        F&O ban{ban.date ? ` (${new Date(`${ban.date}T00:00:00`).toLocaleDateString('en-IN', { weekday: 'short', day: '2-digit', month: 'short' })})` : ''}:{' '}
        {ban.list.map(b => <span key={b} role="button" onClick={() => pick(b)} style={{ color: T.red, cursor: 'pointer', marginRight: 8 }}>{b}</span>)}
        <span style={{ color: T.dim }}>· NSE's securities-in-ban list; entering and leaving the ban are volatile events</span></div>}
      {rolled && data && data.expiry !== rolled && <div style={{ fontSize: 11, color: T.muted, marginBottom: 8 }}>
        The {new Date(`${rolled}T00:00:00`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' })} series settled today: showing the next expiry. Its chip is still there for the final prices.</div>}
      {!data && !error && <Loading label={`Loading ${symbol} · reading the F&O bhavcopy`} />}
      {data && <>
        {/* expiry ladder: each chip carries the expiry's stored ATM IV (iv_expiry_daily) when the surface is stored */}
        <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginBottom: 10, alignItems: 'center' }} data-omon-ladder>
          {data.expiries.slice(0, 8).map(e => {
            const iv = surface?.ok ? surface.expiries.find(x => x.expiry === e)?.atm_iv ?? null : null
            return (
              <Chip key={e} color={T.cyan} active={e === data.expiry} onClick={() => { setExpiry(e); setRolled(null); setPricer(null) }}
                title={iv != null ? `stored ATM IV ${iv.toFixed(2)}% on ${surface?.as_of} (iv_expiry_daily · arithmetic)` : 'ATM IV per expiry appears once the IV store is deployed'}>
                {new Date(`${e}T00:00:00`).toLocaleDateString('en-IN', { day: '2-digit', month: 'short' }).toUpperCase()}
                {iv != null && <span style={{ opacity: 0.75 }}>· {iv.toFixed(1)}%</span>}
              </Chip>
            )
          })}
          {screenRow?.mwpl_pct != null && (
            <span style={{ marginLeft: 8, display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: 10.5, color: T.muted, fontFamily: T.mono }}
              title="Open interest as a share of the market-wide position limit (NSE combined OI file). At 95 % the stock enters the F&O ban. Context: describes crowding, does not predict.">
              % MWPL <b style={{ color: T.text }}>{screenRow.mwpl_pct.toFixed(0)}%</b> <BadgeChip badge="context" />
            </span>
          )}
        </div>
        <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(6, minmax(0, 1fr))', marginBottom: 12 }}>
          <Stat big={false} label="Spot / forward" value={num(data.spot, 2)} sub={`forward ${num(data.forward, 2)} (${data.forward_source})`} />
          <Stat big={false} label="ATM implied vol" value={data.atm_iv != null ? `${data.atm_iv}%` : '—'} accent={T.violet}
                sub={data.expected_move_pct != null ? `priced move by expiry ±${data.expected_move_pct}%` : ''} />
          <Stat big={false} label="Expected range" accent={T.cyan}
                value={data.expected_move_pct != null && data.forward ? `${num(data.forward * (1 - data.expected_move_pct / 100))} – ${num(data.forward * (1 + data.expected_move_pct / 100))}` : '—'}
                sub="±1 standard deviation at expiry" />
          {/* PLAN 0.6 (R-OPTIONS §3.4): a put/call ratio is context — no green above 1, no red below */}
          <Stat big={false} label="Put / call OI" value={data.pcr_oi ?? '—'} color={T.text}
                sub={`calls ${lakh(data.call_oi_total)} · puts ${lakh(data.put_oi_total)} · context`} />
          <Stat big={false} label="Max pain" value={num(data.max_pain)} accent={T.amber} sub="where option buyers collect least" />
          <Stat big={false} label="OI walls" value={<span><span style={{ color: T.red }}>{num(data.resistance[0])}</span> / <span style={{ color: T.green }}>{num(data.support[0])}</span></span>}
                sub={`call wall (resistance) / put wall (support)`} />
        </div>
        <ChainStrip chain={data} history={ivHist.v2} surface={surface} />
        <IvHistoryChart symbol={data.symbol} state={ivHist} collapsed={!histOpen} onToggle={() => setHistOpen(o => !o)} />
        <IvLivePath symbol={data.symbol} enabled={live} />
        {pricer && data.rows.some(r => r.strike === pricer.strike) && <OptionPricer data={data} pick={pricer} onClose={() => setPricer(null)} />}
        <Panel title="Chain" pad={0} accent={T.amber} style={{ marginBottom: 12 }} source={chainSource} badge="arithmetic"
          subtitle="calls left · puts right · bars = open interest · OI change since the previous session · IV only for out-of-the-money strikes · click a price to open the pricer (OVME) · click a strike (or j / k + space) to pick it for OSTR"
          right={<span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
            {picks.length > 0 && <span style={{ fontFamily: T.mono, fontSize: 10.5, color: T.violet }} data-omon-picks>
              {picks.map(k => num(k, k % 1 ? 1 : 0)).join(' · ')} → {SEED_NAME[Math.min(picks.length, 4)]}</span>}
            {picks.length > 0 && <Chip color={T.muted} onClick={() => setPicks([])} title="clear the picked strikes">CLEAR</Chip>}
            <Chip color={T.violet} active={picks.length > 0} onClick={openInOstr} aria-label="open in OSTR"
              title={picks.length ? `Open the strategy builder on ${data.symbol} ${data.expiry} with ${legsFromStrikes(picks).length} legs seeded from the picked strikes (key: o)` : `Open the strategy builder on ${data.symbol} ${data.expiry}; pick up to 4 strikes first to seed the legs`}>
              OPEN IN OSTR ›</Chip>
            <Chip color={T.cyan} active={greeks} onClick={() => setGreeks(g => !g)} title="Greeks per strike from Black-76 on the forward with the strike's own IV (r 6.5 %, T = calendar days ÷ 365). Arithmetic.">Δ Γ Θ ν</Chip>
          </span>}>
          <div ref={scrollRef} tabIndex={0} onKeyDown={onChainKey} style={{ maxHeight: 640, overflowY: 'auto', position: 'relative', outline: 'none' }} data-omon-chain>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: T.mono, fontSize: 11 }}>
              <thead style={{ position: 'sticky', top: 0, background: '#080b10', zIndex: Z.raised }}>
                <tr style={{ color: T.muted, fontSize: 9.5, letterSpacing: .8 }}>
                  {['OI', 'OI CHG', 'VOLUME', 'IV', ...(greeks ? ['Δ', ...(hasNseDelta ? ['NSE Δ'] : []), 'Θ/D'] : []), 'PRICE'].map(h => <th key={`c${h}`} style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 600 }}>CALL {h}</th>)}
                  <th style={{ padding: '6px 8px', color: T.amber }}>STRIKE</th>
                  {greeks && <th style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 600 }} title="gamma: change in delta per 1 point of the underlying (same for the call and the put at one IV)">Γ</th>}
                  {greeks && <th style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 600 }} title="vega: ₹ per unit for a 1 vol-point move in IV (same for both sides)">ν</th>}
                  {['PRICE', ...(greeks ? ['Θ/D', ...(hasNseDelta ? ['NSE Δ'] : []), 'Δ'] : []), 'IV', 'VOLUME', 'OI CHG', 'OI'].map(h => <th key={`p${h}`} style={{ padding: '6px 8px', textAlign: 'left', fontWeight: 600 }}>PUT {h}</th>)}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r, ri) => {
                  const atm = r.strike === data.atm, itmCall = data.forward != null && r.strike < data.forward
                  const chg = (v: number | null) => <span style={{ color: v == null ? T.dim : v > 0 ? T.green : v < 0 ? T.red : T.dim }}>{v == null ? '—' : signedLakh(v)}</span>
                  // one IV per strike (OMON prices IV on the out-of-the-money side; parity gives the other side the same IV)
                  const kIv = r.ce.iv ?? r.pe.iv
                  const gc = greeks ? greeksFor('call', data.forward, r.strike, kIv, data.days_to_expiry) : null
                  const gp = greeks ? greeksFor('put', data.forward, r.strike, kIv, data.days_to_expiry) : null
                  const picked = picks.includes(r.strike), cur = cursor === ri
                  const gcell = (v: string, shade: boolean, align: 'left' | 'right') => <td style={{ padding: '4px 6px', textAlign: align, color: T.cyan, opacity: 0.9, background: shade ? '#0c1018' : undefined }}>{v}</td>
                  return (
                    <tr key={r.strike} data-atm={atm ? '1' : undefined} data-strike-row={ri} data-picked={picked ? '1' : undefined}
                      style={{ borderBottom: `1px solid ${T.border}`, background: cur ? '#16202e' : atm ? '#141106' : undefined, boxShadow: cur ? `inset 2px 0 0 ${T.amber}` : undefined }}>
                      <td style={{ padding: '4px 8px', textAlign: 'right', position: 'relative', background: itmCall ? '#0c1018' : undefined }}>
                        <span style={{ position: 'absolute', right: 0, top: 3, bottom: 3, width: `${((r.ce.oi ?? 0) / maxOi) * 100}%`, background: `${T.red}33` }} />
                        <span style={{ position: 'relative', color: walls.has(r.strike) && data.resistance[0] === r.strike ? T.red : T.text, fontWeight: walls.has(r.strike) ? 700 : 400 }}>{lakh(r.ce.oi)}</span>
                      </td>
                      <td style={{ padding: '4px 8px', textAlign: 'right', background: itmCall ? '#0c1018' : undefined }}>{chg(r.ce.oi_chg)}</td>
                      <td style={{ padding: '4px 8px', textAlign: 'right', color: T.muted, background: itmCall ? '#0c1018' : undefined }}>{lakh(r.ce.volume)}</td>
                      <td style={{ padding: '4px 8px', textAlign: 'right', color: T.violet, background: itmCall ? '#0c1018' : undefined }}>{r.ce.iv ?? ''}</td>
                      {greeks && gcell(gfmt(gc?.delta, 'd'), itmCall, 'right')}
                      {greeks && hasNseDelta && gcell(gfmt(r.ce.nse_delta, 'd'), itmCall, 'right')}
                      {greeks && gcell(gfmt(gc?.thetaDay, 't'), itmCall, 'right')}
                      <td onClick={() => setPricer({ strike: r.strike, side: 'call' })} title="price this call (OVME)"
                        style={{ padding: '4px 8px', textAlign: 'right', color: T.bright, cursor: 'pointer', textDecoration: pricer?.strike === r.strike && pricer.side === 'call' ? 'underline' : undefined,
                                 background: pricer?.strike === r.strike && pricer.side === 'call' ? `${T.violet}33` : itmCall ? '#0c1018' : undefined }}>{num(r.ce.price, 2)}</td>
                      <td onClick={() => togglePick(r.strike)} title={picked ? 'picked for OSTR · click to drop' : 'click to pick this strike for OSTR (up to 4)'}
                        style={{ padding: '4px 10px', textAlign: 'center', color: atm ? T.bg : T.amber, background: atm ? T.amber : T.panel, fontWeight: 700, cursor: 'pointer',
                                 outline: picked ? `1px solid ${T.violet}` : undefined, outlineOffset: -2 }}>
                        {picked && <span style={{ color: atm ? T.bg : T.violet, marginRight: 4 }}>✓</span>}{num(r.strike, r.strike % 1 ? 1 : 0)}</td>
                      {greeks && gcell(gfmt(gc?.gamma, 'g'), false, 'right')}
                      {greeks && gcell(gfmt(gc?.vega, 'v'), false, 'right')}
                      <td onClick={() => setPricer({ strike: r.strike, side: 'put' })} title="price this put (OVME)"
                        style={{ padding: '4px 8px', color: T.bright, cursor: 'pointer', textDecoration: pricer?.strike === r.strike && pricer.side === 'put' ? 'underline' : undefined,
                                 background: pricer?.strike === r.strike && pricer.side === 'put' ? `${T.violet}33` : !itmCall ? '#0c1018' : undefined }}>{num(r.pe.price, 2)}</td>
                      {greeks && gcell(gfmt(gp?.thetaDay, 't'), !itmCall, 'left')}
                      {greeks && hasNseDelta && gcell(gfmt(r.pe.nse_delta, 'd'), !itmCall, 'left')}
                      {greeks && gcell(gfmt(gp?.delta, 'd'), !itmCall, 'left')}
                      <td style={{ padding: '4px 8px', color: T.violet, background: !itmCall ? '#0c1018' : undefined }}>{r.pe.iv ?? ''}</td>
                      <td style={{ padding: '4px 8px', color: T.muted, background: !itmCall ? '#0c1018' : undefined }}>{lakh(r.pe.volume)}</td>
                      <td style={{ padding: '4px 8px', background: !itmCall ? '#0c1018' : undefined }}>{chg(r.pe.oi_chg)}</td>
                      <td style={{ padding: '4px 8px', position: 'relative', background: !itmCall ? '#0c1018' : undefined }}>
                        <span style={{ position: 'absolute', left: 0, top: 3, bottom: 3, width: `${((r.pe.oi ?? 0) / maxOi) * 100}%`, background: `${T.green}33` }} />
                        <span style={{ position: 'relative', color: data.support[0] === r.strike ? T.green : T.text, fontWeight: data.support[0] === r.strike ? 700 : 400 }}>{lakh(r.pe.oi)}</span>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {greeks && <div style={{ padding: '5px 12px', fontSize: 10, color: T.dim, borderTop: `1px solid ${T.border}` }}>
            Δ Γ Θ ν: Black-76 on the forward {num(data.forward, 2)} with each strike's own IV, {data.days_to_expiry} calendar days ÷ 365, r 6.5 % · per unit of the underlying (× lot {data.lot ?? '—'} for a contract)
            {hasNseDelta ? ' · NSE Δ from the exchange\'s Contract_Delta file' : " · NSE's own delta column appears once the Contract_Delta ingest is served"} · arithmetic
          </div>}
        </Panel>
        <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'minmax(0, 1fr) minmax(0, 1fr)', marginBottom: 12 }}>
          <Panel title="Volatility smile" accent={T.violet} pad={8} source={chainSource} badge="arithmetic"
            subtitle="out-of-the-money IV by strike · higher on the left = traders pay more for downside protection">
            <Smile data={data} />
          </Panel>
          <Panel title="Open interest by strike" accent={T.amber} pad={8} source={chainSource} badge="context" subtitle="red = calls (resistance) · green = puts (support) · walls = most open interest over every strike of the expiry">
            <OiBars data={data} />
          </Panel>
        </div>
        <div style={{ fontSize: 10, color: T.dim, marginTop: 8, lineHeight: 1.6 }}>
          Source: NSE F&O bhavcopy (UDiFF), cached nightly by the EOD pipeline. IV = Black–Scholes on the put–call-parity forward,
          r 6.5%, no dividends (an approximation for stocks). Shaded cells are in the money. Max pain and OI walls describe where
          option writers are positioned; they are context, not signals. End of day, not live.
        </div>
      </>}
    </div>
  )
}
