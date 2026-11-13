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
 * else the 12 %-of-notional heuristic — and prints which answered (BREEZE / NSE SPAN FILE / HEURISTIC); the heuristic's
 * measured 4.8× error is printed only when the heuristic is the answer (review m059). No order route exists.
 *
 * Live program round 2 (reports/live_nse, L2-UI): while NSE trades the legs, spot and forward are seeded from NSE's
 * live option chain (GET /api/market/option-chain-live, option-chain-v3 through data-service, ≈ 1 min behind) with its
 * own timestamp and a DELAYED · NSE · <age> chip — never LIVE; the seed is taken once (↻ CHAIN re-seeds) and the
 * underlying's spot now (live quote service: Breeze websocket → NSE) is shown beside it as context. After the close the
 * F&O bhavcopy chain, labelled CLOSE · <date>. Rules + chips: ./strategySeed.ts.
 *
 * OSTR v2 (PLAN 2.2, review M39 / M40 / m059–m063, W2-BOOK, 6 Nov 2026): every leg has its OWN expiry (calendars and
 * diagonals: each expiry's chain is read once, the leg priced on its forward and margined on its contract); T+n and
 * IV-shift sliders draw a third payoff curve; the 2-D P&L grid (spot ±5 % × IV ±10 pts × dates, ./fobook/PnlGrid);
 * the probability of profit from the risk-neutral lognormal, badge heuristic; templates seeded by delta; net delta in
 * lots and ₹ per 1 %; costs whose items add up, the exercise STT if held, a bid–ask input, shares as a leg (covered call
 * on holdings, costed by shared/trading_costs.py); save / name a structure; "Book paper" writes the F&O legs to the
 * PAPER book (./fobook/PaperBook, ui-api SQLite) — still no order route anywhere.
 *
 * Round 2 (6 Nov): every leg is valued at its chain's own T (review M04, 'cal365-1530': the chain's `t_days`, no half-day —
 * the book and OMON use the same T, so one contract has one IV); each leg is sized with ITS expiry's lot; a FUT leg lives on
 * a monthly expiry and is seeded the way the book marks it (the traded near-month future, else that expiry's parity
 * forward, labelled); the expiry chips are the BASE expiry (they re-seed a template; a custom book keeps its legs); GO's
 * `NIFTY OSTR IC` hand-off (lib/goAliases.ts OSTR_TEMPLATE_KEY) is read once on mount and on its event, then removed.
 */
import axios from 'axios'
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { getOptionChain, getOptionChainLive, type OptionChain as Chain } from '@/lib/api'
import { apiError } from '@/lib/errors'
import { useRequestSeq } from '@/components/useRequestSeq'
import { BadgeChip, Btn, CHART_BOX, Chip, ErrorBox, Input, Label, Loading, Notice, PageHeader, Panel, Select, SourceChip, Stat, T, fmtInr, inputSource, sourceOf, useChartSize, type SourceInfo } from '@/components/terminal'
import { useMarketOpen } from '@/components/shell/useFeed'
import { isStaleEod, useLiveQuotes } from '@/lib/liveQuotes'
import { underlyingLiveSymbol } from '@/components/liveModel'
import { chainSeedSource, seedMode, seedPhrase, spotDriftPct, stampClock, type SeedMode } from '@/components/strategySeed'
import type { MarginAnswer, MarginLeg } from '@/components/vol/api'
import { legsFromStrikes } from '@/components/vol/volModel'
import { readActiveSymbol, useActiveSymbol, type ActiveSymbol } from '@/lib/activeSymbol'
import { draftAlert } from '@/lib/alerts'
import { OSTR_TEMPLATE_EVENT, OSTR_TEMPLATE_KEY, parseOstrTemplate } from '@/lib/goAliases'
import { Crosshair, fmtAxisRupees, niceAxis, niceStep, rupeeAxisUnit, staggerRows, textWidth, useChartInteraction } from '@/components/terminal/chart'
import { ExpandableChart, useChartShell } from '@/components/terminal/ExpandableChart'
import { SymbolTypeahead } from '@/components/SymbolTypeahead'
import { PreTradeChecklist } from '@/components/risk/PreTradeChecklist'
import { DELTA_RULE, TEMPLATES, bookLegs, defaultName, deltaUnits, futSeed, legDays, marginLegs, marginView, monthlyExpiries, pickTemplate, templateSpecs, type FutBasis, type Template } from '@/components/fobook/ostrModel'
import { PnlGrid, type PnlGridData } from '@/components/fobook/PnlGrid'
import { PaperBook } from '@/components/fobook/PaperBook'
import { deleteSaved, getSaved, postBook, postSaved, type SavedStructure } from '@/components/fobook/api'

// ── types ───────────────────────────────────────────────────────────────────────

type Side = 'buy' | 'sell'
type Kind = 'CE' | 'PE' | 'FUT' | 'EQ'
interface UiLeg { id: number; side: Side; kind: Kind; strike: number | null; premium: string; iv: string; lots: string; expiry: string; seeded: string
                 /** FUT legs: what the seeded price is (the traded future, or that expiry's parity forward) */
                 basis?: FutBasis }

interface Analysis {
  entry_cashflow: number; net_label: 'CREDIT' | 'DEBIT' | 'FLAT'; single_expiry: boolean; multi_expiry: boolean
  nearest_expiry_days: number; time_convention: string; extremes_basis: string
  breakevens: number[]
  max_profit: { value: number | null; unbounded: boolean; at: number | null }
  max_loss: { value: number | null; unbounded: boolean; at: number | null }
  greeks: { per_leg: Record<string, number | null>[]; net: Record<string, number>
            net_units: { delta_lots: number | null; delta_inr_per_1pct: number; gamma_pnl_1pct_inr: number; lot_size: number }; note: string }
  payoff: { s: number; expiry: number; now: number; scenario: number }[]
  scenario: { days_forward: number; iv_shift: number; note: string }
  pop: { value: number; iv_used: number; horizon_days: number; badge: string; method: string; note: string } | null
  /** T-07b: levels where the expiry P&L equals the round-trip costs (badge arithmetic) */
  breakevens_net_of_costs?: { values: number[]; costs_inr: number; badge: string; note: string }
  grid?: PnlGridData
  margin: { estimate: boolean; total: number; per_leg: number[]; premium_outflow: number
            defined_risk_floor: number | null; fut_margin_pct: number; note: string; excludes_shares?: boolean }
  costs: { estimate: boolean; entry: number; exit: number; round_trip: Record<string, number>; note: string
           display: { items: [string, number][]; total: number; exact_total: number; note: string }
           exercise_stt: { value: number; rate_pct: number; at_forward: number; note: string }
           spread: { value: number; per_unit_per_side: number; note: string }
           equity: { round_trip: Record<string, number>; source: string; note: string } | null }
}

const n2 = (v: number | null | undefined, d = 2) =>
  v == null || !Number.isFinite(v) ? '—' : v.toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d })

// ── template seeding (strikes picked from the chain by delta, so every leg is tradeable — review m060) ──

let legSeq = 1
const mk = (side: Side, kind: Kind, strike: number | null, premium: number | null, iv: number | null, expiry: string): UiLeg => {
  const p = premium != null ? String(premium) : ''
  return { id: legSeq++, side, kind, strike, premium: p, iv: iv != null ? String(iv) : '', lots: '1', expiry, seeded: p }
}

/** price + IV for a strike from the chain; IV falls back to the other side (parity) then ATM. */
function fromChain(chain: Chain, strike: number, kind: 'CE' | 'PE'): { premium: number | null; iv: number | null } {
  const row = chain.rows.find(r => r.strike === strike)
  if (!row) return { premium: null, iv: chain.atm_iv }
  const leg = kind === 'CE' ? row.ce : row.pe, other = kind === 'CE' ? row.pe : row.ce
  return { premium: leg.price, iv: leg.iv ?? other.iv ?? chain.atm_iv }
}

const nearestStrike = (chain: Chain, k: number) =>
  chain.rows.reduce((b, r) => Math.abs(r.strike - k) < Math.abs(b - k) ? r.strike : b, chain.rows[0]?.strike ?? k)

/** A FUT leg seeded on the near monthly (futures exist on monthly expiries only) at NSE's traded near-month future (the
 *  chain's `future` is NSE's nearest future whatever expiry the chain is for); without one it waits for the near monthly's
 *  chain and takes its parity forward (futSeed), labelled. */
function seedFut(side: Side, chain: Chain): UiLeg {
  const near = monthlyExpiries(chain.expiries)[0] ?? chain.expiry
  if (chain.future != null) return { ...mk(side, 'FUT', null, chain.future, null, near), basis: 'future' }
  if (chain.expiry === near) { const f = futSeed(chain); return { ...mk(side, 'FUT', null, f.price, null, near), basis: f.basis } }
  return { ...mk(side, 'FUT', null, null, null, near), seeded: '\u0000' }          // priced when the near monthly's chain lands
}

function seedTemplate(t: Template, chain: Chain): UiLeg[] {
  return templateSpecs(t, chain).map(s => {
    if (s.kind === 'FUT') return seedFut(s.side, chain)
    if (s.kind === 'EQ') return mk(s.side, 'EQ', null, chain.spot ?? chain.forward, null, chain.expiry)
    const { premium, iv } = fromChain(chain, s.strike as number, s.kind)
    return mk(s.side, s.kind, s.strike, premium, iv, chain.expiry)
  })
}

/** Legs seeded from strikes picked on OMON (PLAN 1.3); a strike missing from this chain is skipped, never invented. */
function seedFromStrikes(strikes: readonly number[], chain: Chain): UiLeg[] {
  const have = new Set(chain.rows.map(r => r.strike))
  return legsFromStrikes(strikes).filter(l => have.has(l.strike)).map(l => {
    const { premium, iv } = fromChain(chain, l.strike, l.kind)
    return mk(l.side, l.kind, l.strike, premium, iv, chain.expiry)
  })
}

/**
 * The pre-trade checklist payload (B-COCKPIT's component, SPEC §5) → the booking's journal note (≤ 300 chars server-side).
 * Defensive on shape: the component's own note string wins; else "checklist: t/n"; an unticked checklist still books —
 * the checklist never gates the Book button (O-F3: the cockpit blocks nothing).
 */
function checklistNote(p: unknown): string | undefined {
  if (!p || typeof p !== 'object') return undefined
  const o = p as Record<string, unknown>
  for (const k of ['journal_note', 'note']) {
    if (typeof o[k] === 'string' && (o[k] as string).trim()) return (o[k] as string).slice(0, 280)
  }
  const t = typeof o.ticked === 'number' ? o.ticked : typeof o.done === 'number' ? o.done : null
  const n = typeof o.total === 'number' ? o.total : null
  if (t != null && n != null) return `checklist: ${t}/${n}`
  return undefined
}

/** An OMON pick younger than 30 minutes seeds the legs; an older one only names the symbol / expiry. */
const SEED_FRESH_MS = 30 * 60_000
function freshSeed(a: ActiveSymbol | null, now = Date.now()): ActiveSymbol | null {
  return a && a.strikes.length > 0 && now - Date.parse(a.at) < SEED_FRESH_MS ? a : null
}

/** P0-8: the margin answer plus the server cache's honesty fields (vol/api's MarginAnswer is not this builder's file). */
type MarginAnswerX = MarginAnswer & { served_from_cache?: boolean; cache_age_s?: number | null; hit?: boolean }

/** The full margin ask — vol/api's call plus `stale_ok` (a dead/slow Breeze degrades to the cached answer, age shown). */
const postMargin = (symbol: string, legs: MarginLeg[], forward?: number | null) =>
  axios.post<MarginAnswerX>('/api/options/margin',
    { symbol, legs, exchange_code: 'NFO', forward: forward ?? undefined, stale_ok: true }, { timeout: 25_000 })

/** The instant cache probe (`cached_only`): the server's last Breeze answer for these legs, or `{hit:false}` — no SDK call. */
const probeMarginCache = (symbol: string, legs: MarginLeg[], forward?: number | null) =>
  axios.post<MarginAnswerX>('/api/options/margin',
    { symbol, legs, exchange_code: 'NFO', forward: forward ?? undefined, cached_only: true }, { timeout: 4_000 })

const cacheAge = (s: number | null | undefined): string =>
  s == null ? 'age unknown' : s < 90 ? `${s}s old` : s < 5400 ? `${Math.round(s / 60)}m old` : `${(s / 3600).toFixed(1)}h old`

/** The margin answer's chip: BREEZE (live) / NSE SPAN FILE (its file date) / HEURISTIC (no feed: your legs). */
function marginSource(m: MarginAnswerX | null, err: string | null,
                      market: { state?: string | null; session_date?: string | null } | null = null): SourceInfo {
  if (!m) return err ? sourceOf(null, { source: 'margin route', hint: err }) : inputSource('your legs (margin not asked yet)')
  const chip = String(m.source_chip ?? '').toUpperCase()
  if (m.served_from_cache) {
    // the cached last Breeze answer: never LIVE, the ORIGINAL time on the face, the age in the hint (P0-8 honesty)
    return sourceOf(m.as_of, { source: 'BREEZE · CACHED', maxAgeDays: 4,
      hint: `the last successful ICICI SPAN answer for these legs (${cacheAge(m.cache_age_s)}), served instantly from the ui-api cache — a fresh ask replaces it` })
  }
  if (chip === 'BREEZE') {
    // ICICI's margin API answers on demand: LIVE while NSE trades; after the close (or before the open) the answer is
    // priced off the session's close, so CLOSE · <session> (5 Nov closed-market audit: it read LIVE · BREEZE at 17:02)
    if (market?.state && market.state !== 'open') {
      return { state: 'closed', source: 'BREEZE', asOf: market.session_date ?? null, ageDays: null,
               hint: `ICICI's margin API answered${m.as_of ? ` at ${String(m.as_of).slice(11, 16)}` : ''}; NSE is closed, so it is priced off the session's close` }
    }
    return sourceOf(m.as_of, { live: true, source: 'BREEZE' })
  }
  if (chip === 'NSE SPAN FILE') {
    // the route's as_of is the file date as YYYY-MM-DD; detail.file_date is NCL's raw YYYYMMDD
    const raw = (m.detail as { file_date?: string } | undefined)?.file_date ?? ''
    const d = m.as_of ?? (/^\d{8}$/.test(raw) ? `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}` : null)
    return sourceOf(d, { source: 'NSE SPAN file', maxAgeDays: 4 })
  }
  return inputSource('the 12 %-of-notional heuristic on your legs')
}

// ── payoff chart (SVG kit v2, chart plan B6: wheel zoom · drag pan · double-click reset · crosshair → shell legend) ──

function PayoffSvg({ a, forward, showScenario, width: W, height: H }: {
  a: Analysis; forward: number; showScenario: boolean; width: number; height: number
}) {
  // drawn in CSS px (C1-17): 9.5 px labels at any width; round ticks; one ₹ unit per axis; BE labels never overlap
  const shell = useChartShell()
  const svgRef = useRef<SVGSVGElement | null>(null)
  const clipId = useId()
  const padL = 64, padR = 14, padT = 14, padB = 34
  const plotW = Math.max(1, W - padL - padR)
  const plotH = Math.max(1, H - padT - padB)
  const g = a.payoff
  const xs = useMemo(() => g.map(p => p.s), [g])
  const full = useMemo(() => ({ min: xs[0] ?? 0, max: xs[xs.length - 1] ?? 1 }), [xs])
  // crosshair values go to the panel legend (ExpandableChart slot) — readable in the header, never tooltip-only
  const onCrosshair = useCallback((i: number | null) => {
    if (!shell) return
    const p = i != null ? g[i] ?? null : null
    shell.setLegend(p ? (
      <span>
        <span style={{ color: T.text }}>spot {p.s.toLocaleString('en-IN', { maximumFractionDigits: 0 })}</span>
        {' · '}<span style={{ color: p.expiry >= 0 ? T.green : T.red }}>expiry {fmtInr(p.expiry, 0)}</span>
        {' · '}<span style={{ color: T.cyan }}>today {fmtInr(p.now, 0)}</span>
        {showScenario && <> · <span style={{ color: T.violet }}>scenario {fmtInr(p.scenario, 0)}</span></>}
      </span>
    ) : null)
  }, [shell, g, showScenario])
  const ia = useChartInteraction(svgRef, full, { points: xs, onCrosshair })
  ia.setPlot(padL, plotW)                                 // every render: events map px → data through the plot box
  // FIT in the shell header = back to the full x-domain
  const resetRef = useRef(ia.reset)
  resetRef.current = ia.reset
  useEffect(() => {
    if (!shell) return
    return shell.registerActions({ fit: () => resetRef.current() })
  }, [shell])
  const view = ia.view
  const xmin = view.min, xmax = view.max
  const x = (s: number) => padL + (s - xmin) / (xmax - xmin || 1) * plotW
  // B6 jitter fix: the y-domain comes from the EXPIRY + TODAY curves only — the same numbers on every slider frame,
  // so the baseline is frozen unless the legs / chain change; the scenario curve is CLIPPED, never re-measures the axis
  const { ymin, ymax } = useMemo(() => {
    const ys = g.flatMap(p => [p.expiry, p.now])
    const lo = Math.min(...ys, 0), hi = Math.max(...ys, 0)
    const pad = ((hi - lo) || 1) * 0.06
    return { ymin: lo - pad, ymax: hi + pad }
  }, [g])
  const y = (v: number) => padT + (ymax - v) / (ymax - ymin) * plotH
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
  const scenPath = g.map((p, i) => `${i ? 'L' : 'M'}${x(p.s).toFixed(1)},${y(p.scenario).toFixed(1)}`).join('')
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
  const cur = ia.cursor != null ? g[ia.cursor.i] ?? null : null   // a stale index after new data never crashes
  return (
    <svg ref={svgRef} width={W} height={H} viewBox={`0 0 ${W} ${H}`} role="img"
         aria-label="Strategy payoff at expiry and today (wheel zooms, drag pans, double-click resets)"
         style={{ display: 'block', touchAction: 'none', cursor: 'crosshair' }}>
      <clipPath id={clipId}><rect x={padL} y={padT} width={plotW} height={plotH} /></clipPath>
      {yAxis.ticks.map(v => (
        <g key={v}>
          <line x1={padL} x2={W - padR} y1={y(v)} y2={y(v)} stroke={T.border} strokeWidth={Math.abs(v) < 1e-9 ? 1.4 : 0.6} />
          <text x={padL - 6} y={y(v) + 3} fontSize={9.5} fill={T.dim} textAnchor="end" fontFamily={T.mono}>{fmtAxisRupees(v, yAxis.unit, yAxis.step)}</text>
        </g>
      ))}
      {xTicks.filter(s => s >= xmin && s <= xmax).map(s => (
        <text key={s} x={x(s)} y={H - padB + 14} fontSize={9.5} fill={T.dim} textAnchor="middle" fontFamily={T.mono}>{s.toLocaleString('en-IN')}</text>
      ))}
      <g clipPath={`url(#${clipId})`}>
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
        {/* value today (cyan), the T+n / IV-shift scenario (violet, dashed), then expiry (green/red by sign) on top */}
        <path d={nowPath} fill="none" stroke={T.cyan} strokeWidth={1.3} opacity={0.85} />
        {showScenario && <path d={scenPath} fill="none" stroke={T.violet} strokeWidth={1.5} strokeDasharray="6 3" data-ostr-scenario-curve />}
        {segs.map((s, i) => <path key={i} d={s.d} fill="none" stroke={s.pos ? T.green : T.red} strokeWidth={2} />)}
      </g>
      <Crosshair x={cur ? x(cur.s) : null} y={cur ? y(cur.expiry) : null} top={padT} height={plotH} left={padL} width={plotW} />
      {ia.zoomed && <text x={W - padR} y={padT + 10} fontSize={9} fill={T.dim} textAnchor="end" fontFamily={T.mono}>zoomed · double-click or FIT resets</text>}
    </svg>
  )
}

/** The payoff in the ExpandableChart shell (FIT · ⛶ EXPAND · crosshair legend); the colour key stays below the chart;
 *  the seed's SourceChip sits on the surrounding "Payoff" Panel header (one chip, not two). */
function PayoffChart({ a, forward, lotNote, showScenario }: {
  a: Analysis; forward: number; lotNote: string; showScenario: boolean
}) {
  const { ref, h: H } = useChartSize(680, 300, { maxRatio: 1.3 })   // responsive collapsed height, as the old chart sized itself
  const expiryLabel = a.multi_expiry ? 'P&L at the nearest expiry (later legs by Black-76)' : 'P&L at expiry'
  return (
    <div ref={ref} style={CHART_BOX}>
      <ExpandableChart title="Payoff to scale" accent={T.green}
        badges={[{ label: 'arithmetic', note: a.extremes_basis }]}
        legend={<span style={{ color: T.dim }}>wheel zoom · drag pan · double-click reset · hover for values</span>}
        height={H}>
        {({ width, height }) => <PayoffSvg a={a} forward={forward} showScenario={showScenario} width={width} height={height} />}
      </ExpandableChart>
      <div style={{ fontSize: 10.5, color: T.muted, marginTop: 4 }}>
        <span style={{ color: T.green }}>— {expiryLabel}</span> (red where losing) ·{' '}
        <span style={{ color: T.cyan }}>— today (Black-76)</span>
        {showScenario && <> · <span style={{ color: T.violet }}>┄ +{a.scenario.days_forward}d, IV {a.scenario.iv_shift >= 0 ? '+' : '−'}{Math.abs(a.scenario.iv_shift)} pts</span></>}
        {' '}· <span style={{ color: T.cyan }}>┆ breakevens{a.multi_expiry ? ' (root-found)' : ' (exact)'}</span> · {lotNote}
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
  const [margin, setMargin] = useState<MarginAnswerX | null>(null)
  const [marginErr, setMarginErr] = useState<string | null>(null)
  const [marginRefreshing, setMarginRefreshing] = useState(false)
  const [chain, setChain] = useState<Chain | null>(null)
  const [underlyings, setUnderlyings] = useState<string[]>([])
  const [chainErr, setChainErr] = useState<unknown>(null)
  const [loading, setLoading] = useState(false)
  const [legs, setLegs] = useState<UiLeg[]>([])
  const [template, setTemplate] = useState<Template | null>('Straddle')
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [anErr, setAnErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  // OSTR v2: the other expiries' chains (calendars / diagonals), the scenario sliders, the bid–ask input, save / book
  const [extraChains, setExtraChains] = useState<Record<string, Chain>>({})
  const [extraErr, setExtraErr] = useState<Record<string, string>>({})
  const [scenDays, setScenDays] = useState(0)
  const [ivShift, setIvShift] = useState(0)
  const [slippage, setSlippage] = useState('0')
  const [name, setName] = useState('')
  const [saved, setSaved] = useState<SavedStructure[]>([])
  const [savedPick, setSavedPick] = useState('')
  const [bookAsk, setBookAsk] = useState(false)
  const [bookMsg, setBookMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [bookKey, setBookKey] = useState(0)
  const checklistPayload = useRef<unknown>(null)          // B-COCKPIT's PreTradeChecklist hands its payload up here
  const chainRef = useRef<Chain | null>(null)            // the chain on screen, for the GO hand-off (a stable callback)
  const keepLegs = useRef(false)                         // a base-expiry chip on a custom book keeps its legs

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
        setExtraChains({}); setExtraErr({})
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

  // GO `NIFTY OSTR IC [27NOV]` (lib/goAliases.ts, U-PLATFORM): a ONE-SHOT hand-off, read once on mount and on its event,
  // removed as soon as it is read (a stale or malformed one is ignored); it opens that symbol / expiry on that template,
  // over an OMON pick. GO also wrote the active symbol: that write is marked handled so it cannot reset the expiry.
  const applyTemplateHandoff = useCallback(() => {
    let raw: string | null = null
    try { raw = localStorage.getItem(OSTR_TEMPLATE_KEY); if (raw != null) localStorage.removeItem(OSTR_TEMPLATE_KEY) } catch { return }
    const h = parseOstrTemplate(raw, Date.now())
    const t = pickTemplate(h?.template)
    if (!h || !t) return
    pendingSeed.current = null
    keepLegs.current = false
    handledAt.current = readActiveSymbol()?.at ?? handledAt.current
    setTemplate(t); setSeededFrom(null)
    const cur = chainRef.current
    if (cur && cur.symbol === h.symbol && (!h.expiry || h.expiry === cur.expiry)) setLegs(seedTemplate(t, cur))
    else { setSymbol(h.symbol); setExpiry(h.expiry) }
  }, [])
  useEffect(() => {
    applyTemplateHandoff()
    window.addEventListener(OSTR_TEMPLATE_EVENT, applyTemplateHandoff)
    return () => window.removeEventListener(OSTR_TEMPLATE_EVENT, applyTemplateHandoff)
  }, [applyTemplateHandoff])

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
    const keep = keepLegs.current
    keepLegs.current = false
    if (template) { setSeededFrom(null); setLegs(seedTemplate(template, chain)) }
    else if (!keep) { setSeededFrom(null); setLegs([]) }   // custom book: ↻ CHAIN / a new symbol means new prices — start clean
    // keep: a BASE-expiry chip on a custom book — every leg keeps its own expiry, price and source (its chain is re-read)
  }, [chain])                                            // eslint-disable-line react-hooks/exhaustive-deps
  chainRef.current = chain

  const lot = chain?.lot ?? 1
  const forward = chain?.forward ?? chain?.future ?? chain?.spot ?? null
  const strikes = useMemo(() => chain?.rows.map(r => r.strike) ?? [], [chain])

  // ── the chain of each leg's expiry (calendars / diagonals): the main one, or fetched once per expiry ──
  const chainFor = useCallback((e: string): Chain | null => (chain && e === chain.expiry ? chain : extraChains[e] ?? null), [chain, extraChains])
  // each leg is sized with ITS expiry's lot (NSE revises lots per series: a calendar across a revision has two sizes)
  const lotOf = useCallback((l: Pick<UiLeg, 'kind' | 'expiry'>) => (l.kind === 'EQ' ? chain?.lot : chainFor(l.expiry)?.lot) ?? lot, [chain, chainFor, lot])
  // a leg's reference level: its expiry's forward; a FUT leg's is its own seed (traded future / parity forward), so a
  // future booked at the market shows no basis P&L at T+0
  const legForward = useCallback((l: Pick<UiLeg, 'kind' | 'expiry'>): number | null => {
    if (l.kind === 'EQ') return chain?.spot ?? null
    const c = chainFor(l.expiry)
    if (!c) return null
    return l.kind === 'FUT' ? (futSeed(c).price ?? c.forward ?? c.future ?? null) : (c.forward ?? c.future ?? null)
  }, [chain, chainFor])
  const wantExpiries = useMemo(() => [...new Set(legs.filter(l => l.kind !== 'EQ').map(l => l.expiry))].filter(e => chain && e !== chain.expiry), [legs, chain])
  useEffect(() => {
    if (!chain) return
    for (const e of wantExpiries) {
      if (extraChains[e] || extraErr[e]) continue
      const sym = chain.symbol
      const req = loadedMode === 'live' ? getOptionChainLive(sym, e).catch(() => getOptionChain(sym, e)) : getOptionChain(sym, e)
      req.then(r => {
        if (r.data.symbol !== sym) return
        if (r.data.expiry !== e) { setExtraErr(x => ({ ...x, [e]: `${e} is not a listed expiry` })); return }
        setExtraChains(x => ({ ...x, [e]: r.data }))
      }).catch(err => setExtraErr(x => ({ ...x, [e]: apiError(err).slice(0, 80) })))
    }
  }, [wantExpiries, chain, loadedMode])                 // eslint-disable-line react-hooks/exhaustive-deps
  // a leg moved to another expiry is re-priced from that expiry's chain once it lands (same strike, else the nearest;
  // a FUT leg by the one futures rule, ./fobook/ostrModel futSeed)
  useEffect(() => {
    setLegs(ls => {
      let changed = false
      const next = ls.map(l => {
        if (l.kind === 'EQ' || l.seeded !== '\u0000') return l
        const c = chainFor(l.expiry)
        if (!c) return l
        changed = true
        if (l.kind === 'FUT') { const f = futSeed(c); const fp = f.price != null ? String(f.price) : ''; return { ...l, premium: fp, basis: f.basis, seeded: fp } }
        const k = l.strike != null && c.rows.some(r => r.strike === l.strike) ? l.strike : nearestStrike(c, l.strike ?? c.atm)
        const { premium, iv } = fromChain(c, k, l.kind)
        const p = premium != null ? String(premium) : ''
        return { ...l, strike: k, premium: p, iv: iv != null ? String(iv) : l.iv, seeded: p }
      })
      return changed ? next : ls
    })
  }, [extraChains, chain, chainFor])
  const nearestLegDays = useMemo(() => {
    const ds = legs.filter(l => l.kind === 'CE' || l.kind === 'PE').map(l => chainFor(l.expiry)).filter(Boolean).map(c => legDays(c as Chain))
    return ds.length ? Math.min(...ds) : chain ? legDays(chain) : 0
  }, [legs, chainFor, chain])
  useEffect(() => { if (scenDays > nearestLegDays) setScenDays(Math.floor(nearestLegDays * 2) / 2) }, [nearestLegDays, scenDays])

  // ── analyze (debounced) ──
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (!chain || forward == null || legs.length === 0) { anSeq.cancel(); setAnalysis(null); setBusy(false); return }
    const bad = legs.find(l => (l.kind !== 'FUT' && l.kind !== 'EQ' && l.strike == null) || !(Number(l.premium) >= 0) || !(Number(l.lots) >= 1))
    if (bad) { anSeq.cancel(); setBusy(false); setAnErr('finish the highlighted leg (strike, premium ≥ 0, lots ≥ 1)'); return }
    const waiting = legs.find(l => l.kind !== 'EQ' && !chainFor(l.expiry))
    if (waiting) { anSeq.cancel(); setBusy(true); setAnErr(extraErr[waiting.expiry] ? `the ${waiting.expiry} chain: ${extraErr[waiting.expiry]}` : null); return }
    setAnErr(null)
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      const mine = anSeq.begin(), current = () => anSeq.isCurrent(mine)
      setBusy(true)
      const near = legs.filter(l => l.kind === 'CE' || l.kind === 'PE').map(l => chainFor(l.expiry) as Chain).sort((a, b) => a.days_to_expiry - b.days_to_expiry)[0]
      axios.post<Analysis>('/api/options/strategy/analyze', {
        symbol,
        forward,
        days_to_expiry: (chain as { t_days?: number | null }).t_days ?? Math.max(0, chain.days_to_expiry),
        default_iv: chain.atm_iv ?? 15,
        is_index: ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50'].includes(symbol.toUpperCase()),
        scenario_days: scenDays, iv_shift: ivShift, grid: true,
        pop_iv: near?.atm_iv ?? undefined,
        slippage_per_unit: Math.max(0, Number(slippage) || 0),
        legs: legs.map(l => {
          const c = l.kind === 'EQ' ? chain : (chainFor(l.expiry) as Chain)
          return {
            side: l.side, kind: l.kind, strike: l.kind === 'FUT' || l.kind === 'EQ' ? null : l.strike,
            premium: Number(l.premium) || 0, lots: Math.max(1, Math.round(Number(l.lots) || 1)),
            lot_size: lotOf(l), iv: Number(l.iv) > 0 ? Number(l.iv) : null,
            days: l.kind === 'CE' || l.kind === 'PE' ? legDays(c) : null,
            forward: l.kind === 'EQ' ? (chain.spot ?? null) : legForward(l),
            expiry: l.kind === 'EQ' ? null : l.expiry,
          }
        }),
      }, { timeout: 15000 })
        .then(r => { if (current()) { setAnalysis(r.data); setAnErr(null) } })
        .catch(e => { if (current()) setAnErr(String(e?.response?.data?.detail ?? e?.message ?? 'analyze failed')) })
        .finally(() => { if (current()) setBusy(false) })
    }, 350)
    return () => { if (timer.current) clearTimeout(timer.current) }
  }, [legs, chain, forward, symbol, lot, anSeq, chainFor, extraErr, scenDays, ivShift, slippage, lotOf, legForward])

  // ── real margin (PLAN 1.3 + FINAL ROUND P0-8): the block never blanks — the server's cached last Breeze answer is
  // probed INSTANTLY (`cached_only`, no SDK call) and shown with its age while the full ask (Breeze through the budget
  // ledger → cached-on-failure via `stale_ok` → NSE SPAN file → labelled heuristic) refreshes behind, debounced, latest
  // wins. Every leg on ITS contract (a calendar is margined per leg); shares are not margined here.
  const marginSeq = useRequestSeq()
  const mTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const marginFullFor = useRef(-1)                        // the seq whose FULL answer landed (the cached probe never overwrites it)
  useEffect(() => {
    if (!chain || legs.length === 0 || !legs.some(l => l.kind !== 'EQ')) { marginSeq.cancel(); setMargin(null); setMarginErr(null); setMarginRefreshing(false); return }
    const bad = legs.find(l => (l.kind !== 'FUT' && l.kind !== 'EQ' && l.strike == null) || !(Number(l.premium) >= 0) || !(Number(l.lots) >= 1))
    if (bad) { marginSeq.cancel(); return }
    const mine = marginSeq.begin(), current = () => marginSeq.isCurrent(mine)
    const body: MarginLeg[] = marginLegs(legs, lotOf)
    setMarginRefreshing(true)
    probeMarginCache(symbol, body, forward)
      .then(r => { if (current() && marginFullFor.current !== mine && r.data.hit) { setMargin(r.data); setMarginErr(null) } })
      .catch(() => { /* the probe is best-effort; the full ask below answers */ })
    if (mTimer.current) clearTimeout(mTimer.current)
    mTimer.current = setTimeout(() => {
      if (!current()) return
      postMargin(symbol, body, forward)
        .then(r => { if (current()) { marginFullFor.current = mine; setMargin(r.data); setMarginErr(null); setMarginRefreshing(false) } })
        .catch(e => { if (current()) { marginFullFor.current = mine; setMargin(null); setMarginRefreshing(false)
          setMarginErr(e?.response?.status === 404 ? 'margin route not deployed on this ui-api' : String(e?.response?.data?.detail ?? e?.message ?? 'margin unavailable')) } })
    }, 600)
    return () => { if (mTimer.current) clearTimeout(mTimer.current) }
  }, [legs, chain, forward, symbol, lot, marginSeq, lotOf])

  // ── saved structures (save / name; not a booking) ──
  const loadSaved = useCallback(() => {
    let alive = true
    getSaved(symbol).then(r => { if (alive) setSaved(r.data.rows) }).catch(() => { if (alive) setSaved([]) })
    return () => { alive = false }
  }, [symbol])
  useEffect(() => loadSaved(), [loadSaved])

  // ── leg edits ──
  const edit = (id: number, patch: Partial<UiLeg>) => {
    setTemplate(null)
    setLegs(ls => ls.map(l => {
      if (l.id !== id) return l
      const next = { ...l, ...patch }
      const c = chainFor(next.expiry)
      if (patch.expiry !== undefined && patch.expiry !== l.expiry && next.kind !== 'EQ') {
        // another expiry: re-price from its chain (now, or when it lands); FUT by the one futures rule (futSeed)
        if (next.kind === 'FUT') {
          if (!c) { next.seeded = '\u0000'; return next }
          const f = futSeed(c)
          next.premium = f.price != null ? String(f.price) : next.premium; next.basis = f.basis; next.seeded = next.premium
          return next
        }
        if (!c) { next.seeded = '\u0000'; return next }
        const k = next.strike != null && c.rows.some(r => r.strike === next.strike) ? next.strike : nearestStrike(c, next.strike ?? c.atm)
        const { premium, iv } = fromChain(c, k, next.kind as 'CE' | 'PE')
        next.strike = k; next.premium = premium != null ? String(premium) : ''; next.iv = iv != null ? String(iv) : next.iv; next.seeded = next.premium
        return next
      }
      // kind/strike changed → re-seed premium + IV from the chain of this leg's expiry
      if (c && next.kind !== 'FUT' && next.kind !== 'EQ' && (patch.kind || patch.strike !== undefined) && next.strike != null) {
        const { premium, iv } = fromChain(c, next.strike, next.kind as 'CE' | 'PE')
        next.premium = premium != null ? String(premium) : next.premium
        next.iv = iv != null ? String(iv) : next.iv
        next.seeded = next.premium
      }
      if (patch.kind === 'FUT' && chain) {               // futures live on monthly expiries: the near monthly, at the traded future
        const f = seedFut(next.side, chain)
        next.strike = null; next.expiry = f.expiry; next.premium = f.premium; next.basis = f.basis; next.iv = ''; next.seeded = next.premium
      }
      if (patch.kind === 'EQ') { next.strike = null; next.premium = String(chain?.spot ?? chain?.forward ?? ''); next.iv = ''; next.seeded = next.premium }
      if (patch.kind && patch.kind !== 'FUT' && patch.kind !== 'EQ' && (l.kind === 'FUT' || l.kind === 'EQ') && c) {
        const k = nearestStrike(c, c.atm)
        next.strike = k
        const { premium, iv } = fromChain(c, k, patch.kind as 'CE' | 'PE')
        next.premium = premium != null ? String(premium) : ''; next.iv = iv != null ? String(iv) : ''; next.seeded = next.premium
      }
      return next
    }))
  }
  const addLeg = () => {
    if (!chain || legs.length >= 4) return
    setTemplate(null)
    const k = strikes.reduce((b, s) => Math.abs(s - chain.atm) < Math.abs(b - chain.atm) ? s : b, strikes[0])
    const { premium, iv } = fromChain(chain, k, 'CE')
    setLegs(ls => [...ls, mk('buy', 'CE', k, premium, iv, chain.expiry)])
  }
  const removeLeg = (id: number) => { setTemplate(null); setLegs(ls => ls.filter(l => l.id !== id)) }

  // ── where each leg's price came from (booked and saved with the leg; PIT) ──
  const priceSource = (l: UiLeg): string => {
    if (l.premium !== l.seeded) return 'edited by hand on OSTR'
    const c = l.kind === 'EQ' ? chain : chainFor(l.expiry)
    if (!c) return 'unstated'
    if (l.kind === 'EQ') return `spot on the ${c.live ? 'NSE option chain' : `F&O bhavcopy ${c.date}`}`
    const base = c.live ? `NSE option chain in session ${stampClock(c.as_of) || c.as_of || ''} IST` : `NSE F&O bhavcopy ${c.date}`
    if (l.kind === 'FUT') return l.basis === 'parity-forward' ? `${base} · the ${l.expiry} put-call-parity forward (no traded future for it in the payload)` : `${base} · traded future`
    return base
  }
  const structName = () => name.trim() || defaultName(symbol, legs, template)
  const saveNow = async () => {
    if (!legs.length) return
    try {
      await postSaved(symbol, structName(), legs.map(l => ({ side: l.side, kind: l.kind, strike: l.kind === 'FUT' || l.kind === 'EQ' ? null : l.strike,
        expiry: l.kind === 'EQ' ? null : l.expiry, premium: Number(l.premium) || 0, iv: Number(l.iv) > 0 ? Number(l.iv) : null,
        lots: Math.max(1, Math.round(Number(l.lots) || 1)), lot_size: lotOf(l), price_source: priceSource(l) })))
      setBookMsg({ ok: true, text: `saved "${structName()}"` }); loadSaved()
    } catch (e) { setBookMsg({ ok: false, text: `save failed: ${apiError(e)}` }) }
  }
  const loadSavedPick = (id: string) => {
    setSavedPick(id)
    const s = saved.find(x => String(x.id) === id)
    if (!s || !chain) return
    setTemplate(null)
    setLegs(s.legs.map(l => ({ ...mk(l.side, l.kind, l.strike, l.premium, l.iv, l.expiry ?? chain.expiry), lots: String(l.lots), seeded: String(l.premium) })))
    setSeededFrom(`saved "${s.name}" (premiums as saved ${s.updated_at.slice(0, 16).replace('T', ' ')}; ${s.legs[0]?.price_source ?? 'source unstated'})`)
    setName(s.name)
  }
  const removeSaved = async () => {
    if (!savedPick) return
    try { await deleteSaved(Number(savedPick)); setSavedPick(''); loadSaved() } catch (e) { setBookMsg({ ok: false, text: apiError(e) }) }
  }
  const bookNow = async () => {
    setBookAsk(false)
    try {
      const r = await postBook(symbol, structName(), bookLegs(legs, lotOf, legForward, priceSource), checklistNote(checklistPayload.current),
                               checklistPayload.current ?? undefined)
      setBookMsg({ ok: true, text: `booked #${r.data.structure.id} "${r.data.structure.name}" to the PAPER F&O book (below) — no order was sent` })
      setBookKey(k => k + 1)
    } catch (e) { setBookMsg({ ok: false, text: `book failed: ${apiError(e)}` }) }
  }

  const net = analysis?.greeks.net
  const units = analysis?.greeks.net_units
  const du = net && forward != null ? deltaUnits(net.delta, lot, forward) : null
  // the seed's chip (DELAYED · NSE · age in session — never LIVE — / CLOSE · <date> after the close) and the spot now
  const seedSrc: SourceInfo | null = chain ? chainSeedSource(chain, { mode: loadedMode, nowMs: ul.now || Date.now(), marketState: ul.market?.state ?? null,
    sessionDate: ul.market?.session_date ?? null, liveNote }) : null
  const spotNow = chain?.live && ulRow && ulRow.price != null && ulRow.state !== 'unavailable' && !isStaleEod(ulRow) ? ulRow.price : null
  const drift = spotDriftPct(chain?.spot, spotNow)
  const mView = marginView(margin?.source_chip, marginErr)
  const fnoLegs = legs.filter(l => l.kind !== 'EQ')
  const expiriesInBook = [...new Set(fnoLegs.map(l => l.expiry))].sort()
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
          {/* T-15: filter-as-you-type over the full F&O underlying list (recents first, Enter selects) — no chip wall */}
          <SymbolTypeahead value={symbol} options={[...new Set(['NIFTY', 'BANKNIFTY', 'FINNIFTY', symbol, ...underlyings])]}
            onPick={s => { keepLegs.current = false; setExpiry(null); setSymbol(s); writeActive({ symbol: s }) }} />
          <Btn size="sm" onClick={() => { keepLegs.current = false; loadChain() }}>↻ CHAIN</Btn>
        </div>} />

      {loading && !chain && <Loading label={`option chain · ${symbol}`} />}
      {chainErr != null && <ErrorBox error={chainErr} onRetry={loadChain} />}
      {liveNote && chain && !chain.live && <div style={{ fontSize: 11, color: T.amber, marginBottom: 8 }} data-ostr-live-note>⚠ {liveNote}</div>}

      {chain && (
        <>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10, alignItems: 'center' }}>
            <span title="the chain the templates seed from and a new leg starts on; each leg has its own expiry below, and a custom book keeps its legs when the base changes" data-ostr-base-expiry>
              <Label>Base expiry · re-seeds the template</Label></span>
            {chain.expiries.slice(0, 7).map(e => (
              <Chip key={e} color={T.cyan} active={e === chain.expiry}
                onClick={() => { keepLegs.current = !template && legs.length > 0; setExpiry(e) }}>{e}</Chip>
            ))}
            <span style={{ flex: 1 }} />
            <Label>Templates</Label>
            {TEMPLATES.map(t => (
              <Chip key={t} color={T.amber} active={template === t} title={DELTA_RULE}
                onClick={() => { setTemplate(t); setLegs(seedTemplate(t, chain)) }}>{t}</Chip>
            ))}
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(420px, 1fr))', gap: 12 }}>
            {/* ── left: legs ── */}
            <Panel title={`Legs (${legs.length}/4)`} subtitle={`lot ${lot} · ${seedPhrase(chain)}, every field editable${seededFrom ? ` · seeded from the ${seededFrom}` : template ? ' · strikes by delta' : ''}`}
              source={seedSrc ?? sourceOf(chain.date, { source: 'NSE F&O bhavcopy' })} badge="arithmetic"
              right={<Btn size="sm" onClick={addLeg} disabled={legs.length >= 4}>+ LEG</Btn>}>
              {legs.length === 0 && <Notice>Pick a template above or add a leg — up to four.</Notice>}
              <div style={{ display: 'grid', gap: 8 }}>
                {legs.map((l, i) => {
                  const incomplete = (l.kind !== 'FUT' && l.kind !== 'EQ' && l.strike == null) || !(Number(l.premium) >= 0)
                  const pl = analysis?.greeks.per_leg[i]
                  const lc = chainFor(l.expiry)
                  const legStrikes = lc?.rows.map(r => r.strike) ?? strikes
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
                          {(['CE', 'PE', 'FUT', 'EQ'] as Kind[]).map(k => (
                            <button key={k} style={toggleStyle(l.kind === k, T.amber)} onClick={() => edit(l.id, { kind: k })}
                              title={k === 'EQ' ? 'shares (a covered call on holdings): costed by the cash model, not margined here, never booked in the F&O book' : undefined}>{k === 'EQ' ? 'SHARES' : k}</button>
                          ))}
                        </div>
                      </div>
                      {l.kind !== 'EQ' && (
                        <Select label="Expiry" value={l.expiry} onChange={v => edit(l.id, { expiry: v })}
                          options={(l.kind === 'FUT' ? monthlyExpiries(chain.expiries).slice(0, 3) : chain.expiries.slice(0, 7)).map(e => ({ value: e, label: e }))} />
                      )}
                      {l.kind !== 'FUT' && l.kind !== 'EQ' && (
                        <Select label="Strike" value={String(l.strike ?? '')} onChange={v => edit(l.id, { strike: Number(v) })}
                          options={legStrikes.map(s => ({ value: String(s), label: String(s) }))} />
                      )}
                      <Input label={l.kind === 'FUT' ? 'Entry price' : l.kind === 'EQ' ? 'Share price' : 'Premium ₹'} value={l.premium} width={84}
                        onChange={v => edit(l.id, { premium: v })} aria-label={`leg ${i + 1} premium`} />
                      {l.kind !== 'FUT' && l.kind !== 'EQ' &&
                        <Input label="IV %" value={l.iv} width={56} onChange={v => edit(l.id, { iv: v })} aria-label={`leg ${i + 1} iv`} />}
                      <Input label="Lots" value={l.lots} width={48} onChange={v => edit(l.id, { lots: v })} aria-label={`leg ${i + 1} lots`} />
                      {pl && (
                        <span style={{ fontFamily: T.mono, fontSize: 10, color: T.muted, lineHeight: 1.7 }}>
                          Δ {n2(pl.delta as number, 1)} · θ {fmtInr(pl.theta_day as number, 0)}/d<br />
                          ν {fmtInr(pl.vega as number, 0)}{pl.price != null && <> · model ₹{n2(pl.price as number)}</>}
                        </span>
                      )}
                      {l.kind !== 'EQ' && !lc && <span style={{ fontSize: 10, color: extraErr[l.expiry] ? T.red : T.amber }}>{extraErr[l.expiry] ?? `loading the ${l.expiry} chain…`}</span>}
                      <span style={{ flex: 1 }} />
                      <Btn size="sm" variant="danger" onClick={() => removeLeg(l.id)} title="remove leg">✕</Btn>
                    </div>
                  )
                })}
              </div>

              {/* save / name · book paper (PAPER ONLY: the legs go to ui-api's paper book; no order route exists) */}
              {legs.length > 0 && (
                <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', flexWrap: 'wrap', marginTop: 10 }} data-ostr-save-book>
                  <Input label="Name" value={name} width={200} placeholder={defaultName(symbol, legs, template)} onChange={setName} aria-label="structure name" />
                  <Btn size="sm" onClick={saveNow}>SAVE</Btn>
                  {saved.length > 0 && <>
                    <Select label="Saved" value={savedPick} onChange={loadSavedPick}
                      options={[{ value: '', label: `— ${saved.length} saved —` }, ...saved.map(s => ({ value: String(s.id), label: s.name }))]} />
                    {savedPick && <Btn size="sm" variant="danger" onClick={removeSaved} title="delete the saved structure">✕</Btn>}
                  </>}
                  <span style={{ flex: 1 }} />
                  <Btn size="sm" variant="primary" disabled={fnoLegs.length === 0 || !!anErr || !analysis} onClick={() => setBookAsk(true)}
                    title="write the F&O legs to the PAPER book at the prices shown; no order is sent anywhere">BOOK PAPER</Btn>
                </div>
              )}
              {/* B-COCKPIT's pre-trade checklist (risk/SPEC.md §5) beside Book paper: auto-states from the IV / events /
                  margin reads + the typed max loss; its payload rides into the booking's journal note. It NEVER gates
                  the BOOK PAPER button (O-F3: the cockpit blocks nothing). */}
              {fnoLegs.length > 0 && (
                <div style={{ marginTop: 8 }} data-ostr-checklist>
                  <PreTradeChecklist symbol={symbol} onPayload={(p: unknown) => { checklistPayload.current = p }}
                    margin={margin ? { total: margin.total_margin, source: `${margin.source_chip ?? ''}${margin.served_from_cache ? ' (cached)' : ''}`, asOf: margin.as_of } : null} />
                </div>
              )}
              {bookAsk && (
                <Notice color={T.violet}>
                  <div style={{ display: 'grid', gap: 6 }} data-ostr-book-confirm>
                    <div>Book {fnoLegs.length} F&amp;O leg(s) as &quot;{structName()}&quot; on PAPER at the prices shown ({[...new Set(fnoLegs.map(priceSource))].join(' · ')}).
                      {legs.some(l => l.kind === 'EQ') && ' The shares leg stays in the cash book.'} No order is sent anywhere.</div>
                    <div style={{ display: 'flex', gap: 8 }}>
                      <Btn size="sm" variant="primary" onClick={bookNow}>CONFIRM (PAPER)</Btn>
                      <Btn size="sm" onClick={() => setBookAsk(false)}>CANCEL</Btn>
                    </div>
                  </div>
                </Notice>
              )}
              {bookMsg && <div style={{ fontSize: 10.5, color: bookMsg.ok ? T.cyan : T.red, marginTop: 6 }} data-ostr-book-msg>{bookMsg.text}</div>}

              {(analysis != null || fnoLegs.length > 0) && (
                <div style={{ marginTop: 12, display: 'grid', gap: 10 }}>
                  {analysis && (
                  <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
                    <Chip color={analysis.net_label === 'CREDIT' ? T.green : T.red}>
                      NET {analysis.net_label} {fmtInr(Math.abs(analysis.entry_cashflow), 0)}
                    </Chip>
                    {analysis.breakevens.map(b => <Chip key={b} color={T.cyan} title="open ALRT with a rule: the underlying crosses this breakeven"
                      onClick={() => { if (chain) draftAlert({ series: `price:${chain.symbol}`, op: forward != null && b < forward ? 'cross_down' : 'cross_up',
                                                              value: Math.round(b * 100) / 100, repeat: 'repeat', cooldown_min: 30, note: 'strategy breakeven' }) }}>
                      BE {n2(b, 1)} ＋ALERT</Chip>)}
                    {/* T-07b: the same breakevens with the round-trip costs on top — arithmetic, same payoff curve */}
                    {analysis.breakevens_net_of_costs && analysis.breakevens_net_of_costs.values.length > 0 && (
                      <span data-ostr-be-costs title={analysis.breakevens_net_of_costs.note}
                        style={{ display: 'inline-flex', gap: 4, alignItems: 'center', fontFamily: T.mono, fontSize: 10.5, color: T.muted }}>
                        breakeven incl. {fmtInr(analysis.breakevens_net_of_costs.costs_inr, 0)} costs: {analysis.breakevens_net_of_costs.values.map(b => n2(b, 1)).join(' / ')}
                        <BadgeChip badge="arithmetic" note={analysis.breakevens_net_of_costs.note} />
                      </span>
                    )}
                    <Chip color={T.green} title={analysis.extremes_basis}>
                      MAX PROFIT {analysis.max_profit.unbounded ? 'UNLIMITED ↑' : fmtInr(analysis.max_profit.value, 0)}
                    </Chip>
                    <Chip color={T.red} title={analysis.extremes_basis}>
                      MAX LOSS {analysis.max_loss.unbounded ? 'UNLIMITED (upside)' : fmtInr(analysis.max_loss.value, 0)}
                    </Chip>
                    {analysis.pop && (
                      <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }} data-ostr-pop title={analysis.pop.note}>
                        <Chip color={T.violet}>P(PROFIT) {analysis.pop.value.toFixed(1)}%</Chip>
                        <BadgeChip badge="heuristic" note={`${analysis.pop.method}, IV ${analysis.pop.iv_used}%, ${analysis.pop.horizon_days} d. ${analysis.pop.note}`} />
                      </span>
                    )}
                  </div>
                  )}
                  {/* P0-8: the margin block renders the moment F&O legs exist — cached / asking BREEZE… — never a blank */}
                  <Panel title="Margin & costs" accent={T.violet} pad={10} source={marginSource(margin, marginErr, ul.market)} badge={margin?.badge ?? 'heuristic'}
                    subtitle={margin ? `answered by ${margin.source_chip}${margin.served_from_cache ? ' (cached, age shown)' : ''}${marginRefreshing ? ' · refreshing' : ''}` : marginErr ? 'heuristic only' : 'asking BREEZE…'}>
                    <div style={{ fontFamily: T.mono, fontSize: 11, display: 'grid', gap: 3 }} data-ostr-margin={margin?.source_chip ?? 'HEURISTIC'}>
                      {mView === 'real' && margin ? (
                        <div>
                          <Chip color={String(margin.source_chip).toUpperCase() === 'BREEZE' ? T.green : T.cyan} active style={{ marginRight: 6 }}
                            title={String(margin.source_chip).toUpperCase() === 'BREEZE' ? "ICICI Breeze margin calculator (exchange SPAN + the broker's house rules), live session" : "NSE's SPAN risk-parameter file (scanning risk + calendar spread charge, short option minimum); exposure margin by NSE's published rule"}>
                            {margin.source_chip}</Chip>
                          SPAN <span style={{ color: T.amber }}>{fmtInr(margin.span_margin_required, 0)}</span>
                          <span style={{ color: T.muted }}> · exposure / non-SPAN {fmtInr(margin.non_span_margin_required, 0)} · total </span>
                          <span style={{ color: T.amber, fontWeight: 600 }}>{fmtInr(margin.total_margin, 0)}</span>
                          {/* P0-8 honesty: a cached SPAN never poses as fresh — the original time and the age are on the face */}
                          {margin.served_from_cache && <span style={{ color: T.cyan }} data-ostr-margin-cached> · as of {String(margin.as_of ?? '').slice(11, 16) || '—'} · cached {cacheAge(margin.cache_age_s)}</span>}
                          {marginRefreshing && <span style={{ color: T.dim }}> · asking BREEZE…</span>}
                          {expiriesInBook.length > 1 && <span style={{ color: T.muted }}> · {expiriesInBook.length} expiries, each leg on its own contract</span>}
                        </div>
                      ) : mView === 'heuristic' ? (
                        <>
                          <div>
                            <Chip color={T.violet} active style={{ marginRight: 6 }} title="No broker session and no stored SPAN file answered: the house rule (12 % of notional per short leg + premium) is all there is.">HEURISTIC</Chip>
                            {marginErr && <span style={{ color: T.amber }}>{marginErr} · </span>}
                            {margin?.attempts?.filter(a => !a.ok).map(a => <span key={a.source} style={{ color: T.dim }}>{a.source}: {a.reason} · </span>)}
                          </div>
                          {/* review m059: the heuristic line and its measured error print ONLY when the heuristic is the answer */}
                          <div>Heuristic est. <span style={{ color: T.violet }}>{fmtInr(margin?.heuristic?.total ?? analysis?.margin.total ?? null, 0)}</span>
                            {analysis != null && analysis.margin.premium_outflow > 0 && <span style={{ color: T.muted }}> (incl. {fmtInr(analysis.margin.premium_outflow, 0)} premium paid)</span>}
                            {analysis?.margin.defined_risk_floor != null &&
                              <span style={{ color: T.muted }}> · defined-risk floor {fmtInr(analysis.margin.defined_risk_floor, 0)}</span>}
                            {' '}<BadgeChip badge="heuristic" note={margin?.heuristic?.evidence ?? 'Measured 4.8× above Breeze SPAN on the NIFTY 09-Nov-2026 iron condor (₹3.9 L vs ₹81,497.07).'} />
                          </div>
                          <div style={{ color: T.violet, fontSize: 10.5 }} data-ostr-heuristic-error>
                            measured error {(margin?.heuristic?.error_factor_measured ?? 4.8).toFixed(1)}× (12 % of notional vs Breeze SPAN on the NIFTY 09-Nov-2026 iron condor: ₹3.9 L vs ₹81,497) — a real answer (BREEZE / NSE SPAN FILE) replaces this line
                          </div>
                        </>
                      ) : <div style={{ color: T.dim }} data-ostr-margin-asking>● asking BREEZE… — the cached last answer, the NSE SPAN file or the labelled heuristic answers if it is slow</div>}
                      {analysis?.margin.excludes_shares && <div style={{ color: T.dim, fontSize: 10 }}>shares are not margined here (held in the demat; a call written against them is margined by SPAN unless pledged as cover)</div>}
                      {analysis ? <>
                      {/* review m061: the items shown add up to the total shown */}
                      <div>Costs est. round trip <span style={{ color: T.amber }}>{fmtInr(analysis.costs.display.total, 0)}</span>
                        <span style={{ color: T.muted }} title={`${analysis.costs.display.note}; exact ₹${n2(analysis.costs.display.exact_total)}`}> — {analysis.costs.display.items.map(([k, v]) => `${k} ${fmtInr(v, 0)}`).join(' · ')}</span></div>
                      {/* review m063: exercise STT if held, the bid–ask (your input), shares by the cash model */}
                      <div style={{ color: T.muted }} title={analysis.costs.exercise_stt.note}>+ if held to expiry and exercised at fwd {n2(analysis.costs.exercise_stt.at_forward, 0)}: STT {fmtInr(analysis.costs.exercise_stt.value, 0)} ({analysis.costs.exercise_stt.rate_pct} % of intrinsic, long ITM legs)</div>
                      <div style={{ display: 'flex', gap: 6, alignItems: 'center', color: T.muted }} title={analysis.costs.spread.note}>
                        + bid–ask <Input value={slippage} width={56} onChange={setSlippage} aria-label="bid-ask per unit per side" /> ₹/unit/side (your input)
                        = <span style={{ color: T.amber }}>{fmtInr(analysis.costs.spread.value, 0)}</span>
                      </div>
                      {analysis.costs.equity && <div style={{ color: T.muted }} title={analysis.costs.equity.note}>shares: {fmtInr(analysis.costs.equity.round_trip.total, 0)} delivery round trip if bought for the structure ({analysis.costs.equity.source})</div>}
                      </> : <div style={{ color: T.dim, fontSize: 10 }}>costs itemise here once the legs are priced</div>}
                      {margin?.note && mView === 'real' && <div style={{ color: T.dim, fontSize: 10, lineHeight: 1.5 }}>{margin.note}</div>}
                      <div style={{ color: T.dim, fontSize: 10, lineHeight: 1.5 }}>{analysis ? `${analysis.costs.note} · ` : ''}prices only, PAPER terminal: no order route exists.</div>
                    </div>
                  </Panel>
                </div>
              )}
            </Panel>

            {/* ── right: payoff + Greeks ── */}
            <Panel title="Payoff" accent={T.green} source={seedSrc ?? sourceOf(chain.date, { source: 'NSE F&O bhavcopy' })} badge="arithmetic"
              subtitle={busy ? 'pricing…' : analysis ? `to scale · ${analysis.single_expiry ? 'at expiry + today' : 'at the NEAREST expiry (calendar) + today'}${scenDays || ivShift ? ' + scenario' : ''}` : undefined}>
              {chain.live && (
                <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap', fontFamily: T.mono, fontSize: 10.5, color: T.muted, marginBottom: 8 }} data-ostr-spot>
                  <span>chain spot <span style={{ color: T.text }}>{n2(chain.spot, 2)}</span> · fwd <span style={{ color: T.amber }}>{n2(forward, 2)}</span> at {stampClock(chain.as_of) || '—'} IST (the book is priced on these)</span>
                  {spotNow != null && ul.sourceFor(ulSym ?? '') && <span title="the underlying's price now (live quote service: Breeze websocket, else NSE's website); context only — the legs keep their seeded prices until ↻ CHAIN">
                    · spot now <span style={{ color: T.text }}>{n2(spotNow, 2)}</span>{drift != null && <span style={{ color: T.dim }}> ({drift >= 0 ? '+' : '−'}{Math.abs(drift).toFixed(2)}% since the seed)</span>}{' '}
                    <SourceChip info={ul.sourceFor(ulSym ?? '')!} style={{ fontSize: 8.5 }} /></span>}
                </div>
              )}
              {/* T+n and IV-shift sliders (review M39): a third curve, the whole book revalued */}
              <div style={{ display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap', fontFamily: T.mono, fontSize: 10.5, color: T.muted, marginBottom: 8 }} data-ostr-sliders>
                <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>T+
                  <input type="range" min={0} max={Math.max(0, Math.floor(nearestLegDays * 2) / 2)} step={0.5} value={scenDays}
                    onChange={e => setScenDays(Number(e.target.value))} aria-label="days forward" />
                  <span style={{ color: T.text, minWidth: 44 }}>{scenDays} d</span></label>
                <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>IV
                  <input type="range" min={-10} max={10} step={0.5} value={ivShift} onChange={e => setIvShift(Number(e.target.value))} aria-label="IV shift" />
                  <span style={{ color: T.text, minWidth: 54 }}>{ivShift >= 0 ? '+' : '−'}{Math.abs(ivShift)} pts</span></label>
                {(scenDays !== 0 || ivShift !== 0) && <Btn size="sm" onClick={() => { setScenDays(0); setIvShift(0) }}>RESET</Btn>}
              </div>
              {anErr && <ErrorBox error={anErr} />}
              {!analysis && !anErr && legs.length > 0 && <Loading label="pricing" />}
              {!analysis && legs.length === 0 && <Notice>The payoff draws here once the book has a leg.</Notice>}
              {analysis && forward != null && (
                <>
                  <PayoffChart a={analysis} forward={forward} lotNote={`lot ${lot} · ${expiriesInBook.join(' / ') || chain.expiry}`}
                    showScenario={scenDays !== 0 || ivShift !== 0} />
                  {net && (
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(118px, 1fr))', gap: 8, marginTop: 12 }}>
                      {/* review m062: delta in lots and ₹ per 1 % move; context-neutral colour (a sign is not a view) */}
                      <Stat big={false} label="Net delta" value={`${n2(units?.delta_lots ?? du?.lots, 3)} lots`} accent={T.amber}
                        sub={`${n2(net.delta, 1)} units · ≈ ${fmtInr(units?.delta_inr_per_1pct ?? du?.inrPer1pct, 0)} per 1 % move`} />
                      <Stat big={false} label="Gamma" value={n2(net.gamma, 4)} sub={`Δ change / ₹1 · a 1 % move adds ${fmtInr(units?.gamma_pnl_1pct_inr, 0)}`} />
                      <Stat big={false} label="Theta / day" value={fmtInr(net.theta_day, 0)}
                        color={net.theta_day >= 0 ? T.green : T.red} sub="₹ per calendar day" />
                      <Stat big={false} label="Vega" value={fmtInr(net.vega, 0)} sub="₹ per IV point" />
                      <Stat big={false} label="Rho" value={fmtInr(net.rho, 0)} sub="₹ per +1% rate" />
                    </div>
                  )}
                  <div style={{ fontSize: 10, color: T.dim, marginTop: 8, lineHeight: 1.5 }}>{analysis.greeks.note} · time: {analysis.time_convention}</div>
                  {analysis.grid && (
                    <div style={{ marginTop: 12 }}>
                      {/* review M39; the grid carries its own ExpandableChart shell (title, badge, ⛶ EXPAND — chart plan B7) */}
                      <PnlGrid grid={analysis.grid} />
                    </div>
                  )}
                </>
              )}
            </Panel>
          </div>

          <div style={{ marginTop: 12 }}>
            <PaperBook refreshKey={bookKey} />
          </div>
        </>
      )}
    </div>
  )
}
