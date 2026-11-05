'use client'

/**
 * OSTR — options strategy builder (W3). Build up to 4 legs (buy/sell · CE/PE/FUT) seeded
 * from the cached EOD option chain, price them with the backend engine
 * (POST /api/options/strategy/analyze: Black-76 Greeks, EXACT breakevens, bounded/unbounded
 * max P&L, margin + NSE-cost ESTIMATES) and draw the payoff to scale.
 *
 * PRICES ONLY — paper terminal: there is no order button here and never will be.
 * Chain: GET /api/market/option-chain/{symbol} (NSE F&O bhavcopy, works at any hour —
 * no broker session involved).
 *
 * Terminal v2 (reports/terminal_v2/PLAN.md 1.3): opens on the active symbol (lib/activeSymbol: OMON's "OPEN IN OSTR"
 * carries symbol + expiry + up to 4 picked strikes, seeded as straddle / strangle / iron fly / iron condor); the margin
 * block asks POST /api/options/margin — Breeze's margin calculator when a session is live, else NSE's SPAN risk file,
 * else the 12 %-of-notional heuristic — and prints which answered (BREEZE / NSE SPAN FILE / HEURISTIC) with the
 * heuristic's measured 4.8× error beside it. Prices only; paper terminal; no order route exists.
 *
 * Live program round 2 (reports/live_nse, L2-UI): while NSE trades the legs, spot and forward are seeded from NSE's
 * live option chain (GET /api/market/option-chain-live, option-chain-v3 through data-service, ≈ 1 min behind) with its
 * own timestamp and a DELAYED · NSE · <age> chip — never LIVE; the seed is taken once (↻ CHAIN re-seeds) and the
 * underlying's spot now (live quote service: Breeze websocket → NSE) is shown beside it as context. After the close the
 * F&O bhavcopy chain, labelled CLOSE · <date>. Rules + chips: ./strategySeed.ts. The pricing math is unchanged.
 */
import axios from 'axios'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getOptionChain, getOptionChainLive, type OptionChain as Chain } from '@/lib/api'
import { apiError } from '@/lib/errors'
import { useRequestSeq } from '@/components/useRequestSeq'
import { BadgeChip, Btn, CHART_BOX, Chip, ErrorBox, Input, Label, Loading, Notice, PageHeader, Panel, Select, SourceChip, Stat, T, fmtInr, inputSource, sourceOf, useChartSize, type SourceInfo } from '@/components/terminal'
import { useMarketOpen } from '@/components/shell/useFeed'
import { isStaleEod, useLiveQuotes } from '@/lib/liveQuotes'
import { underlyingLiveSymbol } from '@/components/liveModel'
import { chainSeedSource, seedMode, seedPhrase, spotDriftPct, stampClock, type SeedMode } from '@/components/strategySeed'
import { postMargin, type MarginAnswer, type MarginLeg } from '@/components/vol/api'
import { legsFromStrikes } from '@/components/vol/volModel'
import { readActiveSymbol, useActiveSymbol, type ActiveSymbol } from '@/lib/activeSymbol'
import { fmtAxisRupees, niceAxis, niceStep, rupeeAxisUnit, staggerRows, textWidth } from '@/components/terminal/chart'

// ── types ───────────────────────────────────────────────────────────────────────

type Side = 'buy' | 'sell'
type Kind = 'CE' | 'PE' | 'FUT'
interface UiLeg { id: number; side: Side; kind: Kind; strike: number | null; premium: string; iv: string; lots: string }

interface Analysis {
  entry_cashflow: number; net_label: 'CREDIT' | 'DEBIT' | 'FLAT'; single_expiry: boolean
  breakevens: number[]
  max_profit: { value: number | null; unbounded: boolean; at: number | null }
  max_loss: { value: number | null; unbounded: boolean; at: number | null }
  greeks: { per_leg: Record<string, number | null>[]; net: Record<string, number>; note: string }
  payoff: { s: number; expiry: number; now: number }[]
  margin: { estimate: boolean; total: number; per_leg: number[]; premium_outflow: number
            defined_risk_floor: number | null; fut_margin_pct: number; note: string }
  costs: { estimate: boolean; entry: number; exit: number; round_trip: Record<string, number>; note: string }
}

const n2 = (v: number | null | undefined, d = 2) =>
  v == null || !Number.isFinite(v) ? '—' : v.toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d })

// ── template seeding (strikes picked from the chain so every leg is tradeable) ──

const TEMPLATES = [
  'Long call', 'Long put', 'Bull call spread', 'Bear put spread',
  'Straddle', 'Strangle', 'Iron condor', 'Covered call (fut+CE)',
] as const
type Template = typeof TEMPLATES[number]

let legSeq = 1
const mk = (side: Side, kind: Kind, strike: number | null, premium: number | null, iv: number | null): UiLeg =>
  ({ id: legSeq++, side, kind, strike, premium: premium != null ? String(premium) : '', iv: iv != null ? String(iv) : '', lots: '1' })

/** price + IV for a strike from the chain; IV falls back to the other side (parity) then ATM. */
function fromChain(chain: Chain, strike: number, kind: 'CE' | 'PE'): { premium: number | null; iv: number | null } {
  const row = chain.rows.find(r => r.strike === strike)
  if (!row) return { premium: null, iv: chain.atm_iv }
  const leg = kind === 'CE' ? row.ce : row.pe, other = kind === 'CE' ? row.pe : row.ce
  return { premium: leg.price, iv: leg.iv ?? other.iv ?? chain.atm_iv }
}

function seedTemplate(t: Template, chain: Chain): UiLeg[] {
  const strikes = chain.rows.map(r => r.strike)
  const atmIdx = strikes.reduce((best, s, i) => Math.abs(s - chain.atm) < Math.abs(strikes[best] - chain.atm) ? i : best, 0)
  const at = (off: number) => strikes[Math.max(0, Math.min(strikes.length - 1, atmIdx + off))]
  const opt = (side: Side, kind: 'CE' | 'PE', off: number) => {
    const k = at(off); const { premium, iv } = fromChain(chain, k, kind)
    return mk(side, kind, k, premium, iv)
  }
  switch (t) {
    case 'Long call':         return [opt('buy', 'CE', 0)]
    case 'Long put':          return [opt('buy', 'PE', 0)]
    case 'Bull call spread':  return [opt('buy', 'CE', 0), opt('sell', 'CE', 2)]
    case 'Bear put spread':   return [opt('buy', 'PE', 0), opt('sell', 'PE', -2)]
    case 'Straddle':          return [opt('buy', 'CE', 0), opt('buy', 'PE', 0)]
    case 'Strangle':          return [opt('buy', 'CE', 2), opt('buy', 'PE', -2)]
    case 'Iron condor':       return [opt('sell', 'PE', -2), opt('buy', 'PE', -4), opt('sell', 'CE', 2), opt('buy', 'CE', 4)]
    case 'Covered call (fut+CE)':
      return [mk('buy', 'FUT', null, chain.future ?? chain.forward ?? chain.spot, null), opt('sell', 'CE', 2)]
  }
}

/** Legs seeded from strikes picked on OMON (PLAN 1.3); a strike missing from this chain is skipped, never invented. */
function seedFromStrikes(strikes: readonly number[], chain: Chain): UiLeg[] {
  const have = new Set(chain.rows.map(r => r.strike))
  return legsFromStrikes(strikes).filter(l => have.has(l.strike)).map(l => {
    const { premium, iv } = fromChain(chain, l.strike, l.kind)
    return mk(l.side, l.kind, l.strike, premium, iv)
  })
}

/** An OMON pick younger than 30 minutes seeds the legs; an older one only names the symbol / expiry. */
const SEED_FRESH_MS = 30 * 60_000
function freshSeed(a: ActiveSymbol | null, now = Date.now()): ActiveSymbol | null {
  return a && a.strikes.length > 0 && now - Date.parse(a.at) < SEED_FRESH_MS ? a : null
}

/** The margin answer's chip: BREEZE (live) / NSE SPAN FILE (its file date) / HEURISTIC (no feed: your legs). */
function marginSource(m: MarginAnswer | null, err: string | null): SourceInfo {
  if (!m) return err ? sourceOf(null, { source: 'margin route', hint: err }) : inputSource('your legs (margin not asked yet)')
  const chip = String(m.source_chip ?? '').toUpperCase()
  if (chip === 'BREEZE') return sourceOf(m.as_of, { live: true, source: 'BREEZE' })
  if (chip === 'NSE SPAN FILE') {
    // the route's as_of is the file date as YYYY-MM-DD; detail.file_date is NCL's raw YYYYMMDD
    const raw = (m.detail as { file_date?: string } | undefined)?.file_date ?? ''
    const d = m.as_of ?? (/^\d{8}$/.test(raw) ? `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}` : null)
    return sourceOf(d, { source: 'NSE SPAN file', maxAgeDays: 4 })
  }
  return inputSource('the 12 %-of-notional heuristic on your legs')
}

// ── payoff chart (repo SVG pattern — no chart lib) ──────────────────────────────

function PayoffChart({ a, forward, lotNote }: { a: Analysis; forward: number; lotNote: string }) {
  // drawn in CSS px (C1-17): 9.5 px labels at any width; round ticks; one ₹ unit per axis; BE labels never overlap
  const { ref, w: W, h: H } = useChartSize(680, 300, { maxRatio: 1.3 })
  const padL = 64, padR = 14, padT = 14, padB = 34
  const g = a.payoff
  const xs = g.map(p => p.s), ys = g.flatMap(p => [p.expiry, p.now])
  const xmin = xs[0], xmax = xs[xs.length - 1]
  let ymin = Math.min(...ys, 0), ymax = Math.max(...ys, 0)
  const span = (ymax - ymin) || 1; ymin -= span * 0.06; ymax += span * 0.06
  const x = (s: number) => padL + (s - xmin) / (xmax - xmin || 1) * (W - padL - padR)
  const y = (v: number) => padT + (ymax - v) / (ymax - ymin) * (H - padT - padB)
  // expiry curve split at its zero crossings (breakevens ARE grid points, so the cut is
  // exact for single-expiry books) → green above zero, red below
  const segs: { d: string; pos: boolean }[] = []
  let d = `M${x(g[0].s).toFixed(1)},${y(g[0].expiry).toFixed(1)}`
  let pos = (g[0].expiry !== 0 ? g[0].expiry : g[1]?.expiry ?? 0) >= 0
  for (let i = 1; i < g.length; i++) {
    d += `L${x(g[i].s).toFixed(1)},${y(g[i].expiry).toFixed(1)}`
    if (i < g.length - 1 && Math.abs(g[i].expiry) < 0.01) {   // breakeven grid point: cut here
      segs.push({ d, pos })
      d = `M${x(g[i].s).toFixed(1)},${y(g[i].expiry).toFixed(1)}`
      pos = g[i + 1].expiry >= 0
    }
  }
  segs.push({ d, pos })
  const nowPath = g.map((p, i) => `${i ? 'L' : 'M'}${x(p.s).toFixed(1)},${y(p.now).toFixed(1)}`).join('')
  // y: round rupee ticks (always including 0) in ONE unit for the whole axis (was ₹1.3L next to ₹88.9k)
  const yAxis = useMemo(() => {
    const ticks = niceAxis(ymin, ymax, 5).ticks
    const step = niceStep(ymax - ymin, 5)
    const unit = rupeeAxisUnit(ticks)
    return { ticks, step, unit }
  }, [ymin, ymax])
  // x: round underlying levels (were 19865 / 20948 / …), as many as fit 70 px apart
  const xTicks = useMemo(() => niceAxis(xmin, xmax, Math.max(3, Math.min(8, Math.floor((W - padL - padR) / 70)))).ticks,
    [xmin, xmax, W])
  // breakeven labels: stagger overlapping ones onto a second row (BE 22,324.9 / BE 22,875.1 used to collide)
  const beText = (b: number) => `BE ${b.toLocaleString('en-IN', { minimumFractionDigits: 1, maximumFractionDigits: 1 })}`
  const beRows = staggerRows(a.breakevens.map(b => ({ x: x(b), w: textWidth(beText(b), 9.5) })), 6)
  return (
    <div>
      <div ref={ref} style={CHART_BOX}>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }} role="img"
           aria-label="Strategy payoff at expiry and today">
        {yAxis.ticks.map(v => (
          <g key={v}>
            <line x1={padL} x2={W - padR} y1={y(v)} y2={y(v)} stroke={T.border} strokeWidth={Math.abs(v) < 1e-9 ? 1.4 : 0.6} />
            <text x={padL - 6} y={y(v) + 3} fontSize={9.5} fill={T.dim} textAnchor="end" fontFamily={T.mono}>{fmtAxisRupees(v, yAxis.unit, yAxis.step)}</text>
          </g>
        ))}
        {xTicks.map(s => (
          <text key={s} x={x(s)} y={H - padB + 14} fontSize={9.5} fill={T.dim} textAnchor="middle" fontFamily={T.mono}>{s.toLocaleString('en-IN')}</text>
        ))}
        {/* forward */}
        <line x1={x(forward)} x2={x(forward)} y1={padT} y2={H - padB} stroke={T.amber} strokeDasharray="3 3" opacity={0.8} />
        <text x={x(forward) + 4} y={padT + 10} fontSize={9.5} fill={T.amber} fontFamily={T.mono}>fwd {forward.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</text>
        {/* breakevens: labelled, exact */}
        {a.breakevens.map((b, i) => (
          <g key={b}>
            <line x1={x(b)} x2={x(b)} y1={padT} y2={H - padB} stroke={T.cyan} strokeDasharray="5 4" opacity={0.75} />
            <text x={x(b)} y={H - padB - 4 - beRows[i] * 12} fontSize={9.5} fill={T.cyan} textAnchor="middle" fontFamily={T.mono}
                  stroke={T.panel} strokeWidth={3} paintOrder="stroke">{beText(b)}</text>
          </g>
        ))}
        {/* value today (cyan) then expiry (green/red by sign) on top */}
        <path d={nowPath} fill="none" stroke={T.cyan} strokeWidth={1.3} opacity={0.85} />
        {segs.map((s, i) => <path key={i} d={s.d} fill="none" stroke={s.pos ? T.green : T.red} strokeWidth={2} />)}
      </svg>
      </div>
      <div style={{ fontSize: 10.5, color: T.muted, marginTop: 4 }}>
        <span style={{ color: T.green }}>— P&L at expiry</span> (red where losing) ·{' '}
        <span style={{ color: T.cyan }}>— today (Black-76)</span> · <span style={{ color: T.cyan }}>┆ breakevens (exact)</span> · {lotNote}
      </div>
    </div>
  )
}

// ── main page ───────────────────────────────────────────────────────────────────

export function StrategyBuilder() {
  // the active symbol (PLAN 1.3): OMON's "OPEN IN OSTR" or the last underlying picked anywhere; NIFTY otherwise
  const [symbol, setSymbol] = useState(() => readActiveSymbol()?.symbol ?? 'NIFTY')
  const [expiry, setExpiry] = useState<string | null>(() => freshSeed(readActiveSymbol())?.expiry ?? null)
  const pendingSeed = useRef<ActiveSymbol | null>(freshSeed(readActiveSymbol()))
  const [active, writeActive] = useActiveSymbol()
  const handledAt = useRef<string | null>(readActiveSymbol()?.at ?? null)
  const [seededFrom, setSeededFrom] = useState<string | null>(null)
  const [margin, setMargin] = useState<MarginAnswer | null>(null)
  const [marginErr, setMarginErr] = useState<string | null>(null)
  const [chain, setChain] = useState<Chain | null>(null)
  const [underlyings, setUnderlyings] = useState<string[]>([])
  const [chainErr, setChainErr] = useState<unknown>(null)
  const [loading, setLoading] = useState(false)
  const [legs, setLegs] = useState<UiLeg[]>([])
  const [template, setTemplate] = useState<Template | null>('Straddle')
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [anErr, setAnErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  // live program round 2: the underlying's spot now (live quote service) and the market state that picks the seed
  const calendarOpen = useMarketOpen()
  const ulSym = underlyingLiveSymbol(symbol)
  const ul = useLiveQuotes(ulSym ? [ulSym] : [], { intervalMs: 3_000 })
  const ulRow = ulSym ? ul.quotes[ulSym] : undefined
  const [liveNote, setLiveNote] = useState<string | null>(null)
  const [loadedMode, setLoadedMode] = useState<SeedMode>('eod')
  // read at load time (never a dependency): crossing 15:30 does not reload, so a book on screen is never wiped by the clock
  const modeNow = useRef<() => SeedMode>(() => 'eod')
  modeNow.current = () => seedMode({ marketState: ul.market?.state ?? null, calendarOpen, nowMs: Date.now() })

  // CT-01: latest request wins. A slower chain for the previous underlying / expiry never lands under the new
  // selection (it would seed the legs with the old strikes and analyse them against the new symbol), and an older
  // analysis never replaces the newer book's.
  const chainSeq = useRequestSeq()                    // in refs, never useMemo (P1); cancelled on unmount
  const anSeq = useRequestSeq()
  const loadChain = useCallback(() => {
    const mine = chainSeq.begin(), current = () => chainSeq.isCurrent(mine)
    setLoading(true); setChainErr(null)
    const mode = modeNow.current()
    const eod = () => getOptionChain(symbol, expiry ?? undefined)
    // in session NSE's live chain (≈ 1 min behind, never live); it failing falls back to end of day, with the reason
    const seedReq = mode === 'live'
      ? getOptionChainLive(symbol, expiry ?? undefined)
          .then(r => { if (current()) setLiveNote(null); return r })
          .catch(e => { if (current()) setLiveNote(`live chain unavailable (${apiError(e).slice(0, 80)}): seeded from end of day`); return eod() })
      : eod().then(r => { if (current()) setLiveNote(null); return r })
    seedReq
      .then(r => {
        if (!current()) return
        setChain(r.data)
        setLoadedMode(mode)
        if (r.data.underlyings?.length) setUnderlyings(r.data.underlyings)
      })
      .catch(e => { if (current()) { setChainErr(e?.response?.data?.detail ?? e?.message ?? 'chain unavailable'); setChain(null) } })
      .finally(() => { if (current()) setLoading(false) })
  }, [symbol, expiry, chainSeq])
  useEffect(() => { loadChain() }, [loadChain])
  // the first load may run before the live quote service has said whether NSE trades (the client calendar decided): when
  // its first answer disagrees (a holiday, a clock off), reload once with the right seed. Later market-state changes
  // (15:30) never reload: a book on screen is not wiped by the clock.
  const marketState = ul.market?.state ?? null
  const checkedSeed = useRef(false)
  useEffect(() => {
    if (!marketState || !chain || checkedSeed.current) return
    checkedSeed.current = true
    if (modeNow.current() !== loadedMode) loadChain()
  }, [marketState, chain])                               // eslint-disable-line react-hooks/exhaustive-deps
  // the live chain carries no F&O underlyings list: read it once from the stored chain (as OMON does)
  const needUnderlyings = !!chain?.live && underlyings.length === 0
  useEffect(() => {
    if (!needUnderlyings) return
    let alive = true
    getOptionChain('NIFTY').then(r => { if (alive) setUnderlyings(r.data.underlyings ?? []) }).catch(() => {})
    return () => { alive = false }
  }, [needUnderlyings])

  // a pick written while OSTR is open (another window, or OMON in a split view): adopt it once
  useEffect(() => {
    if (!active || active.at === handledAt.current) return
    handledAt.current = active.at
    const seed = freshSeed(active)
    if (seed) pendingSeed.current = seed
    if (active.symbol !== symbol || (seed && seed.expiry && seed.expiry !== expiry)) { setSymbol(active.symbol); setExpiry(seed?.expiry ?? null) }
  }, [active])                                           // eslint-disable-line react-hooks/exhaustive-deps

  // chain (re)loaded → re-seed the active template so strikes/premiums always match it; an OMON pick wins once
  useEffect(() => {
    if (!chain) return
    const seed = pendingSeed.current
    if (seed && seed.symbol === chain.symbol && (!seed.expiry || seed.expiry === chain.expiry)) {
      pendingSeed.current = null
      const seeded = seedFromStrikes(seed.strikes, chain)
      if (seeded.length) {
        setTemplate(null); setLegs(seeded)
        setSeededFrom(`OMON pick ${seed.strikes.join(' · ')} (${chain.expiry})`)
        return
      }
    }
    setSeededFrom(null)
    if (template) setLegs(seedTemplate(template, chain))
    else setLegs([])                                    // custom book: a new chain means new prices — start clean
  }, [chain])                                            // eslint-disable-line react-hooks/exhaustive-deps

  const lot = chain?.lot ?? 1
  const forward = chain?.forward ?? chain?.future ?? chain?.spot ?? null
  const strikes = useMemo(() => chain?.rows.map(r => r.strike) ?? [], [chain])

  // ── analyze (debounced) ──
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (!chain || forward == null || legs.length === 0) { anSeq.cancel(); setAnalysis(null); setBusy(false); return }
    const bad = legs.find(l => (l.kind !== 'FUT' && l.strike == null) || !(Number(l.premium) >= 0) || !(Number(l.lots) >= 1))
    if (bad) { anSeq.cancel(); setBusy(false); setAnErr('finish the highlighted leg (strike, premium ≥ 0, lots ≥ 1)'); return }
    setAnErr(null)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      const mine = anSeq.begin(), current = () => anSeq.isCurrent(mine)
      setBusy(true)
      axios.post<Analysis>('/api/options/strategy/analyze', {
        symbol,
        forward,
        days_to_expiry: Math.max(0, chain.days_to_expiry) + 0.5,
        default_iv: chain.atm_iv ?? 15,
        is_index: ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50'].includes(symbol.toUpperCase()),
        legs: legs.map(l => ({
          side: l.side, kind: l.kind, strike: l.kind === 'FUT' ? null : l.strike,
          premium: Number(l.premium) || 0, lots: Math.max(1, Math.round(Number(l.lots) || 1)),
          lot_size: lot, iv: Number(l.iv) > 0 ? Number(l.iv) : null,
        })),
      }, { timeout: 15000 })
        .then(r => { if (current()) { setAnalysis(r.data); setAnErr(null) } })
        .catch(e => { if (current()) setAnErr(String(e?.response?.data?.detail ?? e?.message ?? 'analyze failed')) })
        .finally(() => { if (current()) setBusy(false) })
    }, 350)
    return () => { if (timer.current) clearTimeout(timer.current) }
  }, [legs, chain, forward, symbol, lot, anSeq])

  // ── real margin (PLAN 1.3): Breeze → NSE SPAN file → heuristic; the answer says which (debounced, latest wins) ──
  const marginSeq = useRequestSeq()
  const mTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (!chain || legs.length === 0) { marginSeq.cancel(); setMargin(null); setMarginErr(null); return }
    const bad = legs.find(l => (l.kind !== 'FUT' && l.strike == null) || !(Number(l.premium) >= 0) || !(Number(l.lots) >= 1))
    if (bad) { marginSeq.cancel(); return }
    if (mTimer.current) clearTimeout(mTimer.current)
    mTimer.current = setTimeout(() => {
      const mine = marginSeq.begin(), current = () => marginSeq.isCurrent(mine)
      const body: MarginLeg[] = legs.map(l => ({ side: l.side, kind: l.kind, strike: l.kind === 'FUT' ? null : l.strike, expiry: chain.expiry,
        premium: Number(l.premium) || 0, lots: Math.max(1, Math.round(Number(l.lots) || 1)), lot_size: lot }))
      postMargin(symbol, body, forward)
        .then(r => { if (current()) { setMargin(r.data); setMarginErr(null) } })
        .catch(e => { if (current()) { setMargin(null); setMarginErr(e?.response?.status === 404 ? 'margin route not deployed on this ui-api' : String(e?.response?.data?.detail ?? e?.message ?? 'margin unavailable')) } })
    }, 600)
    return () => { if (mTimer.current) clearTimeout(mTimer.current) }
  }, [legs, chain, forward, symbol, lot, marginSeq])

  // ── leg edits ──
  const edit = (id: number, patch: Partial<UiLeg>) => {
    setTemplate(null)
    setLegs(ls => ls.map(l => {
      if (l.id !== id) return l
      const next = { ...l, ...patch }
      // kind/strike changed → re-seed premium + IV from the chain
      if (chain && next.kind !== 'FUT' && (patch.kind || patch.strike !== undefined) && next.strike != null) {
        const { premium, iv } = fromChain(chain, next.strike, next.kind as 'CE' | 'PE')
        next.premium = premium != null ? String(premium) : next.premium
        next.iv = iv != null ? String(iv) : next.iv
      }
      if (patch.kind === 'FUT') { next.strike = null; next.premium = String(chain?.future ?? chain?.forward ?? chain?.spot ?? ''); next.iv = '' }
      if (patch.kind && patch.kind !== 'FUT' && l.kind === 'FUT' && chain) {
        const k = strikes.reduce((b, s) => Math.abs(s - chain.atm) < Math.abs(b - chain.atm) ? s : b, strikes[0])
        next.strike = k
        const { premium, iv } = fromChain(chain, k, patch.kind as 'CE' | 'PE')
        next.premium = premium != null ? String(premium) : ''; next.iv = iv != null ? String(iv) : ''
      }
      return next
    }))
  }
  const addLeg = () => {
    if (!chain || legs.length >= 4) return
    setTemplate(null)
    const k = strikes.reduce((b, s) => Math.abs(s - chain.atm) < Math.abs(b - chain.atm) ? s : b, strikes[0])
    const { premium, iv } = fromChain(chain, k, 'CE')
    setLegs(ls => [...ls, mk('buy', 'CE', k, premium, iv)])
  }
  const removeLeg = (id: number) => { setTemplate(null); setLegs(ls => ls.filter(l => l.id !== id)) }

  const net = analysis?.greeks.net
  // the seed's chip (DELAYED · NSE · age in session — never LIVE — / CLOSE · <date> after the close) and the spot now
  const seedSrc: SourceInfo | null = chain ? chainSeedSource(chain, { mode: loadedMode, nowMs: ul.now || Date.now(), marketState: ul.market?.state ?? null,
    sessionDate: ul.market?.session_date ?? null, liveNote }) : null
  const spotNow = chain?.live && ulRow && ulRow.price != null && ulRow.state !== 'unavailable' && !isStaleEod(ulRow) ? ulRow.price : null
  const drift = spotDriftPct(chain?.spot, spotNow)
  const toggleStyle = (on: boolean, color: string) => ({
    fontFamily: T.mono, fontSize: 10, padding: '3px 7px', cursor: 'pointer', letterSpacing: 1,
    border: `1px solid ${on ? color : T.border}`, color: on ? T.bg : T.muted, background: on ? color : 'transparent',
  } as const)

  return (
    <div>
      <PageHeader code="OSTR" title="Options strategies"
        subtitle={chain ? `${chain.symbol} · ${chain.live ? `NSE option chain in session (≈1 min behind) as of ${stampClock(chain.as_of) || chain.as_of || '—'} IST` : `NSE F&O bhavcopy ${chain.date}`} · expiry ${chain.expiry} (${chain.days_to_expiry}d) · lot ${chain.lot ?? '?'} · fwd ${n2(forward, 2)} (${chain.forward_source}) · ATM IV ${chain.atm_iv ?? '—'}%` : 'payoffs · Greeks · breakevens'}
        status={<Chip color={T.violet}>PRICES ONLY · NO ORDERS</Chip>}
        right={<div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <Select value={symbol} onChange={s => { setExpiry(null); setSymbol(s); writeActive({ symbol: s }) }}
            options={[...new Set(['NIFTY', 'BANKNIFTY', 'FINNIFTY', symbol, ...underlyings])].map(u => ({ value: u, label: u }))} />
          <Btn size="sm" onClick={loadChain}>↻ CHAIN</Btn>
        </div>} />

      {loading && !chain && <Loading label={`option chain · ${symbol}`} />}
      {chainErr != null && <ErrorBox error={chainErr} onRetry={loadChain} />}
      {liveNote && chain && !chain.live && <div style={{ fontSize: 11, color: T.amber, marginBottom: 8 }} data-ostr-live-note>⚠ {liveNote}</div>}

      {chain && (
        <>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10, alignItems: 'center' }}>
            <Label>Expiry</Label>
            {chain.expiries.slice(0, 7).map(e => (
              <Chip key={e} color={T.cyan} active={e === chain.expiry} onClick={() => setExpiry(e)}>{e}</Chip>
            ))}
            <span style={{ flex: 1 }} />
            <Label>Templates</Label>
            {TEMPLATES.map(t => (
              <Chip key={t} color={T.amber} active={template === t}
                onClick={() => { setTemplate(t); setLegs(seedTemplate(t, chain)) }}>{t}</Chip>
            ))}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: 12 }}>
            {/* ── left: legs ── */}
            <Panel title={`Legs (${legs.length}/4)`} subtitle={`lot ${lot} · ${seedPhrase(chain)}, every field editable${seededFrom ? ` · seeded from the ${seededFrom}` : ''}`}
              source={seedSrc ?? sourceOf(chain.date, { source: 'NSE F&O bhavcopy' })} badge="arithmetic"
              right={<Btn size="sm" onClick={addLeg} disabled={legs.length >= 4}>+ LEG</Btn>}>
              {legs.length === 0 && <Notice>Pick a template above or add a leg — up to four.</Notice>}
              <div style={{ display: 'grid', gap: 8 }}>
                {legs.map((l, i) => {
                  const incomplete = (l.kind !== 'FUT' && l.strike == null) || !(Number(l.premium) >= 0)
                  const pl = analysis?.greeks.per_leg[i]
                  return (
                    <div key={l.id} style={{ border: `1px solid ${incomplete ? T.red : T.border}`, padding: '8px 10px',
                                             display: 'flex', flexWrap: 'wrap', gap: 8, alignItems: 'flex-end', background: T.panel2 }}>
                      <div style={{ display: 'grid', gap: 4 }}>
                        <Label>Side</Label>
                        <div style={{ display: 'flex' }}>
                          <button style={toggleStyle(l.side === 'buy', T.green)} onClick={() => edit(l.id, { side: 'buy' })}>BUY</button>
                          <button style={toggleStyle(l.side === 'sell', T.red)} onClick={() => edit(l.id, { side: 'sell' })}>SELL</button>
                        </div>
                      </div>
                      <div style={{ display: 'grid', gap: 4 }}>
                        <Label>Type</Label>
                        <div style={{ display: 'flex' }}>
                          {(['CE', 'PE', 'FUT'] as Kind[]).map(k => (
                            <button key={k} style={toggleStyle(l.kind === k, T.amber)} onClick={() => edit(l.id, { kind: k })}>{k}</button>
                          ))}
                        </div>
                      </div>
                      {l.kind !== 'FUT' && (
                        <Select label="Strike" value={String(l.strike ?? '')} onChange={v => edit(l.id, { strike: Number(v) })}
                          options={strikes.map(s => ({ value: String(s), label: String(s) }))} />
                      )}
                      <Input label={l.kind === 'FUT' ? 'Entry price' : 'Premium ₹'} value={l.premium} width={84}
                        onChange={v => edit(l.id, { premium: v })} aria-label={`leg ${i + 1} premium`} />
                      {l.kind !== 'FUT' &&
                        <Input label="IV %" value={l.iv} width={56} onChange={v => edit(l.id, { iv: v })} aria-label={`leg ${i + 1} iv`} />}
                      <Input label="Lots" value={l.lots} width={48} onChange={v => edit(l.id, { lots: v })} aria-label={`leg ${i + 1} lots`} />
                      {pl && (
                        <span style={{ fontFamily: T.mono, fontSize: 10, color: T.muted, lineHeight: 1.7 }}>
                          Δ {n2(pl.delta as number, 1)} · θ {fmtInr(pl.theta_day as number, 0)}/d<br />
                          ν {fmtInr(pl.vega as number, 0)}{pl.price != null && <> · model ₹{n2(pl.price as number)}</>}
                        </span>
                      )}
                      <span style={{ flex: 1 }} />
                      <Btn size="sm" variant="danger" onClick={() => removeLeg(l.id)} title="remove leg">✕</Btn>
                    </div>
                  )
                })}
              </div>

              {analysis && (
                <div style={{ marginTop: 12, display: 'grid', gap: 10 }}>
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    <Chip color={analysis.net_label === 'CREDIT' ? T.green : T.red}>
                      NET {analysis.net_label} {fmtInr(Math.abs(analysis.entry_cashflow), 0)}
                    </Chip>
                    {analysis.breakevens.map(b => <Chip key={b} color={T.cyan}>BE {n2(b, 1)}</Chip>)}
                    <Chip color={T.green}>
                      MAX PROFIT {analysis.max_profit.unbounded ? 'UNLIMITED ↑' : fmtInr(analysis.max_profit.value, 0)}
                    </Chip>
                    <Chip color={T.red}>
                      MAX LOSS {analysis.max_loss.unbounded ? 'UNLIMITED (upside)' : fmtInr(analysis.max_loss.value, 0)}
                    </Chip>
                  </div>
                  <Panel title="Margin & costs" accent={T.violet} pad={10} source={marginSource(margin, marginErr)} badge={margin?.badge ?? 'heuristic'}
                    subtitle={margin ? `answered by ${margin.source_chip}` : marginErr ? 'heuristic only' : 'asking…'}>
                    <div style={{ fontFamily: T.mono, fontSize: 11, display: 'grid', gap: 3 }} data-ostr-margin={margin?.source_chip ?? 'HEURISTIC'}>
                      {margin && String(margin.source_chip).toUpperCase() !== 'HEURISTIC' ? (
                        <div>
                          <Chip color={String(margin.source_chip).toUpperCase() === 'BREEZE' ? T.green : T.cyan} active style={{ marginRight: 6 }}
                            title={String(margin.source_chip).toUpperCase() === 'BREEZE' ? "ICICI Breeze margin calculator (exchange SPAN + the broker's house rules), live session" : "NSE's SPAN risk-parameter file (scanning risk + calendar spread charge, short option minimum); exposure margin by NSE's published rule"}>
                            {margin.source_chip}</Chip>
                          SPAN <span style={{ color: T.amber }}>{fmtInr(margin.span_margin_required, 0)}</span>
                          <span style={{ color: T.muted }}> · exposure / non-SPAN {fmtInr(margin.non_span_margin_required, 0)} · total </span>
                          <span style={{ color: T.amber, fontWeight: 600 }}>{fmtInr(margin.total_margin, 0)}</span>
                        </div>
                      ) : (
                        <div>
                          <Chip color={T.violet} active style={{ marginRight: 6 }} title="No broker session and no stored SPAN file answered: the house rule (12 % of notional per short leg + premium) is all there is.">HEURISTIC</Chip>
                          {marginErr && <span style={{ color: T.amber }}>{marginErr} · </span>}
                          {margin?.attempts?.filter(a => !a.ok).map(a => <span key={a.source} style={{ color: T.dim }}>{a.source}: {a.reason} · </span>)}
                        </div>
                      )}
                      <div>Heuristic est. <span style={{ color: T.violet }}>{fmtInr(margin?.heuristic?.total ?? analysis.margin.total, 0)}</span>
                        {analysis.margin.premium_outflow > 0 && <span style={{ color: T.muted }}> (incl. {fmtInr(analysis.margin.premium_outflow, 0)} premium paid)</span>}
                        {analysis.margin.defined_risk_floor != null &&
                          <span style={{ color: T.muted }}> · defined-risk floor {fmtInr(analysis.margin.defined_risk_floor, 0)}</span>}
                        {' '}<BadgeChip badge="heuristic" note={margin?.heuristic?.evidence ?? 'Measured 4.8× above Breeze SPAN on the NIFTY 09-Nov-2026 iron condor (₹3.9 L vs ₹81,497.07).'} />
                      </div>
                      <div style={{ color: T.violet, fontSize: 10.5 }} data-ostr-heuristic-error>
                        measured error {(margin?.heuristic?.error_factor_measured ?? 4.8).toFixed(1)}× (12 % of notional vs Breeze SPAN on the NIFTY 09-Nov-2026 iron condor: ₹3.9 L vs ₹81,497) — use the chip above when it says BREEZE or NSE SPAN FILE
                      </div>
                      <div>Costs est. round trip <span style={{ color: T.amber }}>{fmtInr(analysis.costs.round_trip.total, 0)}</span>
                        <span style={{ color: T.muted }}> — brokerage {fmtInr(analysis.costs.round_trip.brokerage, 0)} ·
                          STT {fmtInr(analysis.costs.round_trip.stt, 0)} · txn {fmtInr(analysis.costs.round_trip.txn, 0)} ·
                          GST {fmtInr(analysis.costs.round_trip.gst, 0)}</span></div>
                      {/* the heuristic's own note repeats the 4.8× sentence above: print the route's note only for a real answer */}
                      {margin?.note && String(margin.source_chip).toUpperCase() !== 'HEURISTIC' && <div style={{ color: T.dim, fontSize: 10, lineHeight: 1.5 }}>{margin.note}</div>}
                      <div style={{ color: T.dim, fontSize: 10, lineHeight: 1.5 }}>{analysis.costs.note} · prices only, PAPER terminal: no order route exists.</div>
                    </div>
                  </Panel>
                </div>
              )}
            </Panel>

            {/* ── right: payoff + Greeks ── */}
            <Panel title="Payoff" accent={T.green} source={seedSrc ?? sourceOf(chain.date, { source: 'NSE F&O bhavcopy' })} badge="arithmetic"
              subtitle={busy ? 'pricing…' : analysis ? `to scale · ${analysis.single_expiry ? 'at expiry + today' : 'at NEAREST expiry (calendar) + today'}` : undefined}>
              {chain.live && (
                <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', fontFamily: T.mono, fontSize: 10.5, color: T.muted, marginBottom: 8 }} data-ostr-spot>
                  <span>chain spot <span style={{ color: T.text }}>{n2(chain.spot, 2)}</span> · fwd <span style={{ color: T.amber }}>{n2(forward, 2)}</span> at {stampClock(chain.as_of) || '—'} IST (the book is priced on these)</span>
                  {spotNow != null && ul.sourceFor(ulSym ?? '') && <span title="the underlying's price now (live quote service: Breeze websocket, else NSE's website); context only — the legs keep their seeded prices until ↻ CHAIN">
                    · spot now <span style={{ color: T.text }}>{n2(spotNow, 2)}</span>{drift != null && <span style={{ color: T.dim }}> ({drift >= 0 ? '+' : '−'}{Math.abs(drift).toFixed(2)}% since the seed)</span>}{' '}
                    <SourceChip info={ul.sourceFor(ulSym ?? '')!} style={{ fontSize: 8.5 }} /></span>}
                </div>
              )}
              {anErr && <ErrorBox error={anErr} />}
              {!analysis && !anErr && legs.length > 0 && <Loading label="pricing" />}
              {!analysis && legs.length === 0 && <Notice>The payoff draws here once the book has a leg.</Notice>}
              {analysis && forward != null && (
                <>
                  <PayoffChart a={analysis} forward={forward} lotNote={`lot ${lot} · ${chain.expiry}`} />
                  {net && (
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(118px, 1fr))', gap: 8, marginTop: 12 }}>
                      <Stat big={false} label="Net delta" value={n2(net.delta, 1)} accent={T.amber}
                        sub={`≈ ${fmtInr(net.delta * forward, 0)} of ${chain.symbol}`} color={net.delta >= 0 ? T.green : T.red} />
                      <Stat big={false} label="Gamma" value={n2(net.gamma, 4)} sub="Δ change / ₹1 move" />
                      <Stat big={false} label="Theta / day" value={fmtInr(net.theta_day, 0)}
                        color={net.theta_day >= 0 ? T.green : T.red} sub="₹ per calendar day" />
                      <Stat big={false} label="Vega" value={fmtInr(net.vega, 0)} sub="₹ per IV point"
                        color={net.vega >= 0 ? T.green : T.red} />
                      <Stat big={false} label="Rho" value={fmtInr(net.rho, 0)} sub="₹ per +1% rate" />
                    </div>
                  )}
                  <div style={{ fontSize: 10, color: T.dim, marginTop: 8, lineHeight: 1.5 }}>{analysis.greeks.note}</div>
                </>
              )}
            </Panel>
          </div>
        </>
      )}
    </div>
  )
}
