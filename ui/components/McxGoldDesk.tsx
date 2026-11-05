'use client'

/**
 * MCXG — MCX gold desk (worldclass program W4; gold program PLAN §b). The trading desk next to the GOLD page:
 *   1. session clock  — OPEN/CLOSED with time-to-close, MCX's own 2026 holiday calendar, Muhurat
 *   2. live quote     — ICICI Breeze when the account can serve MCX, otherwise an HONEST
 *                       degrade with the two fallbacks that always work: the ICICI price-band
 *                       settlement and the COMEX × USD/INR fair value (each source-labeled)
 *   3. overlay        — ONE line from /api/mcx/overlay (COMEX · ₹/$ · duty-paid landed · fair · live vs fair · GOLD ›);
 *                       the India price stack, the premium history and the four-stat prose live on GOLD
 *   4. contracts      — the shared contract selector (GOLD › CONTRACTS, same component, prefs-synced
 *                       `gold.contract.v1`): GOLD / GOLDM / GOLDTEN / GOLDGUINEA / GOLDPETAL cards, OI ladder, diff strip
 *   5. paper ticket   — lot-aware pricing (notional, margin, round-trip MCX costs, sizing arithmetic). PAPER:
 *                       it prices the trade and records nothing; no gold series feeds it (PLAN 0.1 #7).
 *
 * Data: /api/mcx/* (services/ui-api/routers/mcx.py; reference data shared/mcx_specs.py), /api/gold/contracts.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Chip, DataTable, Input, Loading, Notice, PageHeader, Panel, Select, Stat, T,
         fmtInr, fmtNum, type Column, sourceOf, inputSource, undatedSource } from '@/components/terminal'
import { fmtSigned, fmtSignedInr } from '@/lib/format'   // +₹ / −₹ with U+2212 (C1-18)
import { ContractSelector } from '@/components/gold/ContractsView'
import { goToPage } from '@/lib/navigate'
import { getGoldContracts } from '@/lib/gold/api'
import { mcxOverlayLine } from '@/lib/gold/format'
import { setGoldSubInUrl, useGoldContract } from '@/lib/gold/prefs'
import { GOLD_FAMILIES, type ContractFamily, type GoldContractSel } from '@/lib/gold/types'

const SESSION_MS = 30_000
const QUOTE_MS = 30_000
const OVERLAY_MS = 60_000
const CONTRACTS_MS = 300_000

interface SessionState {
  as_of: string; is_open: boolean; segment: 'morning' | 'evening' | null; weekend: boolean
  holiday: { name: string; closure: 'full' | 'morning' | 'evening' } | null
  opens_at: string; closes_at: string
  seconds_to_close: number | null; seconds_to_open: number | null
  note: string; calendar_warning?: string
  upcoming_holidays: { date: string; day: string; name: string; closure: string }[]
  special_sessions: { date: string; name: string; note: string }[]
  calendar_source: string
}
interface FairValue {
  comex: { symbol: string; price: number; as_of: string | null }
  usdinr: { symbol: string; price: number; as_of: string | null }
  landed: number; landed_note: string; source: string
  fair?: number; gap_vs_settlement?: number; implied_premium_pct?: number; settlement_session?: string
  duty_pct?: number; duty_paid_landed?: number; settlement_session_label?: string
}
interface QuotePayload {
  as_of: string; contract: string; expiry: string; expiry_source: string
  tick_value: number; lot: string
  available: boolean; reason?: string; live_verify_pending?: boolean
  quote: { ltp: number | null; open: number | null; high: number | null; low: number | null
           previous_close: number | null; time: string | null; source: string } | null
  fallbacks: {
    band: { settlement: number; band_low: number; band_high: number; open_interest_lots: number; source: string } | null
    fair_value: FairValue | null
  }
  best: { price: number; source: string } | null
}
interface OverlayPayload {
  as_of: string; contract: string; expiry: string
  overlay: FairValue | null
  mcx_price: number | null
  premium: { vs: string; rupees: number; pct: number } | null
  /** PLAN §b: the one line (B3 mcx.py overlay_line) and its fields; `link` names the page the chip opens */
  line?: string; link?: string
  fields?: { comex_symbol: string; comex_price: number; usdinr: number; landed: number; duty_pct: number; duty_paid_landed: number; fair: number | null
             settlement_session_label?: string | null; live_vs_fair?: { rupees: number; pct: number } | null } | null
}
interface TicketPayload {
  paper: boolean; recorded: boolean; contract: string; lot: string; lots: number; price: number
  notional: number; tick_value_per_lot: number; tick_value_position: number
  indicative_margin: number; margin_pct_indicative: number
  round_trip: {
    turnover_per_side: number
    buy: CostLeg; sell: CostLeg; total: number
    pct_of_notional: number | null; breakeven_ticks: number | null; breakeven_price_move: number | null
    assumptions: string
  }
  note: string
  /** sizing arithmetic added by the gold program (B3 /api/mcx/ticket); optional until it lands */
  max_lots_at_risk_pct?: number | null; hedge_usdinr_lots?: number | null; atr14_rupees?: number | null; margin_source?: string | null
}
interface CostLeg { brokerage: number; exchange_txn: number; sebi: number; stamp: number; ctt: number; gst: number; total: number }
type LegRow = CostLeg & { side: 'buy' | 'sell' }

async function getJson<T>(url: string, init?: RequestInit): Promise<T> {
  const r = await fetch(url, init)
  const body = await r.json().catch(() => null)
  if (!r.ok) {
    const msg = body?.error?.message ?? (typeof body?.detail === 'string' ? body.detail : null)
    throw new Error(msg ?? `HTTP ${r.status}`)
  }
  return body as T
}

const hms = (s: number | null): string => {
  if (s == null || s < 0) return '—'
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60
  return h > 0 ? `${h}h ${m}m ${sec}s` : m > 0 ? `${m}m ${sec}s` : `${sec}s`
}
const istClock = (iso?: string | null) => iso
  ? new Date(iso).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })
  : '—'
const num = (s: string): number | undefined => {
  const v = Number(String(s).replace(/[,₹\s]/g, ''))
  return Number.isFinite(v) && v > 0 ? v : undefined
}

const CLOSURE_CHIP: Record<string, { label: string; color: string }> = {
  full: { label: 'FULL DAY', color: T.red },
  morning: { label: 'EVE ONLY (17:00→)', color: T.amber },
  evening: { label: 'MORNING ONLY (→17:00)', color: T.cyan },
}

/** The one-line overlay: the server's line when it sends one, else composed from the legacy fair-value block. */
export function overlayText(p: OverlayPayload | null): string {
  if (!p) return 'COMEX × rupee: loading…'
  if (p.line) return p.line.replace(/\s*·\s*GOLD ›\s*$/, '').replace(/\s*·\s*live vs fair[^·]*$/, '')
  const f = p.overlay
  if (!f) return 'COMEX × rupee: unavailable'
  const line = mcxOverlayLine({
    fair_value: f.fair ?? null, mcx_live: p.mcx_price, premium_rupees: null, premium_pct: null,
    comex: f.comex.price, comex_symbol: f.comex.symbol, usdinr: f.usdinr.price, landed: f.landed, duty_pct: f.duty_pct ?? null,
    duty_paid_landed: f.duty_paid_landed ?? null, basis_pct: null, settlement: null,
  }).replace(/\s*·\s*live vs fair —\s*$/, '')
  return f.duty_paid_landed == null ? line.replace('duty-paid landed —', `landed (no duty) ${fmtInr(f.landed)}`) : line
}

const openGold = (sub: 'health' | 'contracts' | 'physical') => { setGoldSubInUrl(sub); goToPage('gold') }

export function McxGoldDesk() {
  const [session, setSession] = useState<SessionState | null>(null)
  const [quote, setQuote] = useState<QuotePayload | null>(null)
  const [overlay, setOverlay] = useState<OverlayPayload | null>(null)
  const [ticket, setTicket] = useState<TicketPayload | null>(null)
  const [families, setFamilies] = useState<ContractFamily[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [sel, updateSel] = useGoldContract()                // prefs gold.contract.v1, shared with GOLD
  const contract = sel.family
  const expiry = sel.expiry ?? ''                            // '' = front by open interest
  const [lots, setLots] = useState('1')
  const [priceIn, setPriceIn] = useState('')                // '' = use the desk's best price
  const [brokerage, setBrokerage] = useState('20')
  const [countdown, setCountdown] = useState<number | null>(null)
  const quoteReq = useRef(0)

  // ── session clock (30 s poll + 1 s local tick) ─────────────────────────────────
  const loadSession = useCallback(async () => {
    try {
      const s = await getJson<SessionState>('/api/mcx/session')
      setSession(s)
      setCountdown(s.is_open ? s.seconds_to_close : s.seconds_to_open)
      setErr(null)
    } catch (e: unknown) { setErr(e instanceof Error ? e.message : 'MCX desk unavailable') }
  }, [])
  useEffect(() => {
    loadSession()
    const iv = setInterval(loadSession, SESSION_MS)
    return () => clearInterval(iv)
  }, [loadSession])
  useEffect(() => {
    const t = setInterval(() => setCountdown(c => (c == null ? c : Math.max(0, c - 1))), 1000)
    return () => clearInterval(t)
  }, [])

  // ── contract families (5 min): the selector's cards, lots and expiries ──────────
  useEffect(() => {
    let alive = true
    const load = () => getGoldContracts(sel.exchange).then(r => { if (alive) setFamilies(r.data?.families ?? []) }).catch(() => { if (alive) setFamilies(f => f ?? []) })
    load()
    const iv = setInterval(load, CONTRACTS_MS)
    return () => { alive = false; clearInterval(iv) }
  }, [sel.exchange])

  // ── quote (30 s, per contract+expiry) ──────────────────────────────────────────
  const loadQuote = useCallback(async () => {
    const id = ++quoteReq.current
    try {
      const q = await getJson<QuotePayload>(
        `/api/mcx/quote?contract=${contract}${expiry ? `&expiry=${expiry}` : ''}`)
      if (id === quoteReq.current) setQuote(q)
    } catch { /* the session/specs panels still stand */ }
  }, [contract, expiry])
  useEffect(() => {
    setQuote(null)
    loadQuote()
    const iv = setInterval(loadQuote, QUOTE_MS)
    return () => clearInterval(iv)
  }, [loadQuote])

  // ── overlay (60 s; live vs fair only against a LIVE broker price, never circular) ─
  useEffect(() => {
    let alive = true
    const live = quote?.available && quote.quote?.ltp ? `&mcx_price=${quote.quote.ltp}` : ''
    const load = () =>
      getJson<OverlayPayload>(`/api/mcx/overlay?contract=${contract}${expiry ? `&expiry=${expiry}` : ''}${live}`)
        .then(p => { if (alive) setOverlay(p) }).catch(() => {})
    load()
    const iv = setInterval(load, OVERLAY_MS)
    return () => { alive = false; clearInterval(iv) }
  }, [contract, expiry, quote?.available, quote?.quote?.ltp])

  // ── paper ticket (debounced POST; prices only, records nothing) ────────────────
  const ticketPrice = num(priceIn) ?? quote?.best?.price
  useEffect(() => {
    const lotsN = Math.max(1, Math.floor(num(lots) ?? 1))
    if (!ticketPrice) { setTicket(null); return }
    let alive = true
    const t = setTimeout(() => {
      getJson<TicketPayload>('/api/mcx/ticket', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ contract, lots: lotsN, price: ticketPrice,
                               brokerage_per_order: num(brokerage) ?? 20 }),
      }).then(p => { if (alive) setTicket(p) }).catch(() => { if (alive) setTicket(null) })
    }, 400)
    return () => { alive = false; clearTimeout(t) }
  }, [contract, lots, ticketPrice, brokerage])

  const codes = useMemo(() => (families?.length ? families.map(f => f.code as GoldContractSel['family']) : [...GOLD_FAMILIES]), [families])
  const fam = useMemo(() => families?.find(f => f.code === contract) ?? null, [families, contract])
  const expiryOptions = useMemo(() => [{ value: '', label: 'front (by OI)' }, ...(fam?.expiries ?? []).map(e => ({ value: e.expiry, label: `${e.expiry}${e.source === 'computed' ? ' · computed' : ''}` }))], [fam])
  const fv = quote?.fallbacks.fair_value ?? overlay?.overlay ?? null
  const stateColor = session ? (session.is_open ? T.green : T.red) : T.muted
  const holidayRows = session?.upcoming_holidays ?? []
  const setContract = (c: GoldContractSel['family']) => updateSel({ family: c, expiry: null })
  const setExpiry = (e: string) => updateSel({ expiry: e || null })

  const holCols: Column<SessionState['upcoming_holidays'][number]>[] = [
    { key: 'date', label: 'Date', render: r => <span style={{ color: T.text }}>{r.date} <span style={{ color: T.dim }}>{r.day}</span></span> },
    { key: 'name', label: 'MCX holiday', render: r => <span style={{ color: T.text }}>{r.name}</span> },
    { key: 'closure', label: 'Closure', align: 'right', render: r => {
        const c = CLOSURE_CHIP[r.closure] ?? { label: r.closure.toUpperCase(), color: T.muted }
        return <Chip color={c.color}>{c.label}</Chip>
      } },
  ]

  const legRows: LegRow[] = ticket ? (['buy', 'sell'] as const).map(side => ({ side, ...ticket.round_trip[side] })) : []
  const legCols: Column<LegRow>[] = [
    { key: 'side', label: 'Leg', render: r => <span style={{ color: r.side === 'buy' ? T.green : T.red, fontWeight: 600 }}>{r.side.toUpperCase()}</span> },
    { key: 'brokerage', label: 'Brokerage', align: 'right', render: r => <span style={{ color: T.text }}>{fmtInr(r.brokerage, 2)}</span> },
    { key: 'exchange_txn', label: 'Exch 0.0021%', align: 'right', render: r => <span style={{ color: T.text }}>{fmtInr(r.exchange_txn, 2)}</span> },
    { key: 'ctt', label: 'CTT 0.01% (sell)', align: 'right', render: r => <span style={{ color: r.ctt ? T.amber : T.dim }}>{fmtInr(r.ctt, 2)}</span> },
    { key: 'stamp', label: 'Stamp (buy)', align: 'right', render: r => <span style={{ color: r.stamp ? T.text : T.dim }}>{fmtInr(r.stamp, 2)}</span> },
    { key: 'sebi', label: 'SEBI', align: 'right', render: r => <span style={{ color: T.text }}>{fmtInr(r.sebi, 2)}</span> },
    { key: 'gst', label: 'GST 18%', align: 'right', render: r => <span style={{ color: T.text }}>{fmtInr(r.gst, 2)}</span> },
    { key: 'total', label: 'Total', align: 'right', render: r => <span style={{ color: T.bright, fontWeight: 700 }}>{fmtInr(r.total, 2)}</span> },
  ]
  const liveVsFair = overlay?.fields?.live_vs_fair ?? (overlay?.premium ? { rupees: overlay.premium.rupees, pct: overlay.premium.pct } : null)

  return (
    <div>
      <PageHeader code="MCXG" title="MCX gold desk"
        subtitle="session clock · live quotes (degrade-honest) · COMEX × rupee in one line · contract selector · paper ticket"
        right={session && (
          <span style={{ display: 'inline-flex', gap: 10, alignItems: 'center' }}>
            <Chip color={stateColor}>{session.is_open ? `● OPEN · ${session.segment?.toUpperCase()}` : '■ CLOSED'}</Chip>
            <span style={{ fontFamily: T.mono, fontSize: 11, color: stateColor }}>
              {session.is_open ? `closes in ${hms(countdown)}` : `opens in ${hms(countdown)}`}
            </span>
            <Chip color={T.amber} onClick={() => openGold('health')} title="The gold terminal: health, positioning, physical, macro, contracts">GOLD ›</Chip>
          </span>
        )} />

      {err && <Notice color={T.red}>MCX desk unavailable: {err}</Notice>}
      {!session && !err && <Loading label="Reading the MCX session clock" />}

      {session && (
        <div style={{ display: 'grid', gap: 12 }}>
          {/* 1. session + calendar */}
          <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'minmax(0, 1.3fr) minmax(300px, 1fr)' }}>
            <Panel source={sourceOf(session.as_of, { source: 'MCX session clock', live: session.is_open })} title="Session" accent={stateColor}
              subtitle={`Mon–Fri 09:00 → ${session.closes_at.includes('23:55') ? '23:55' : '23:30'} IST · as of ${istClock(session.as_of)}`}
              bodyStyle={{ display: 'grid', gap: 10 }}>
              <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))' }}>
                <Stat label="State" value={session.is_open ? 'OPEN' : 'CLOSED'} color={stateColor} accent={stateColor}
                  sub={session.holiday ? `${session.holiday.name} (${session.holiday.closure} closure)` : session.weekend ? 'weekend' : session.segment ? `${session.segment} session` : undefined} />
                <Stat label={session.is_open ? 'Closes' : 'Opens'} value={istClock(session.is_open ? session.closes_at : session.opens_at)}
                  accent={T.cyan} sub={session.is_open ? `in ${hms(countdown)}` : `in ${hms(countdown)}`} />
                <Stat label="Evening close" value={session.closes_at.includes('23:55') ? '23:55 IST' : '23:30 IST'}
                  accent={T.violet} sub="US-linked: 23:30 in NY summer, 23:55 in winter" />
              </div>
              {session.calendar_warning && <Notice color={T.amber}>{session.calendar_warning}</Notice>}
              <div style={{ fontSize: 10, color: T.dim, lineHeight: 1.5 }}>{session.note}</div>
            </Panel>
            <Panel source={undatedSource('MCX holiday calendar')} title="MCX holidays ahead" subtitle="MCX's own calendar — not NSE's" accent={T.amber} pad={0}>
              <DataTable columns={holCols} rows={holidayRows} rowKey={r => r.date} dense
                empty="No MCX holidays left in the 2026 table" />
              {(session.special_sessions ?? []).map(s => (
                <div key={s.date} style={{ padding: '6px 12px', fontSize: 10, color: T.muted, borderTop: `1px solid ${T.border}` }}>
                  ◆ {s.date}: <span style={{ color: T.amber }}>{s.name}</span> — {s.note}
                </div>
              ))}
            </Panel>
          </div>

          {/* 2. quote (+ 3. the overlay line at its foot) */}
          <Panel source={sourceOf(quote?.as_of ?? null, { source: 'Breeze', live: !!quote?.available, maxAgeDays: 1 })} title="Quote" accent={quote?.available ? T.green : T.amber}
            subtitle={quote ? `${quote.contract} ${quote.expiry} (${quote.expiry_source}) · lot ${quote.lot} · tick ${fmtInr(quote.tick_value)}` : 'resolving the front contract'}
            right={
              <span style={{ display: 'inline-flex', gap: 8 }}>
                <Select value={contract} onChange={setContract} options={codes.map(c => ({ value: c, label: c }))} />
                <Select value={expiry} onChange={setExpiry} options={expiryOptions} />
              </span>
            }
            bodyStyle={{ display: 'grid', gap: 10 }}>
            {!quote && <Loading label="Asking the broker, the price band and the model" />}
            {quote?.available && quote.quote && (
              <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))' }}>
                <Stat label={`LTP · ${quote.quote.source}`} value={fmtInr(quote.quote.ltp)} color={T.green} accent={T.green}
                  sub={quote.quote.time ?? undefined} />
                <Stat label="Open" value={fmtInr(quote.quote.open)} accent={T.cyan} />
                <Stat label="High / Low" value={`${fmtInr(quote.quote.high)} / ${fmtInr(quote.quote.low)}`} accent={T.violet} />
                <Stat label="Prev close" value={fmtInr(quote.quote.previous_close)} accent={T.border} />
              </div>
            )}
            {quote && !quote.available && (
              <>
                <Notice color={T.amber}>
                  <b>Broker quote unavailable</b> — {quote.reason ?? 'not served'}{' '}
                  {quote.live_verify_pending && <Chip color={T.violet}>LIVE-VERIFY PENDING · after the 08:00 login</Chip>}
                </Notice>
                <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))' }}>
                  <Stat label="Prev settlement · price band" value={fmtInr(quote.fallbacks.band?.settlement)}
                    accent={T.cyan}
                    sub={quote.fallbacks.band ? `band ${fmtInr(quote.fallbacks.band.band_low)}–${fmtInr(quote.fallbacks.band.band_high)} · OI ${fmtNum(quote.fallbacks.band.open_interest_lots)} lots · PROXY` : 'ICICI master unavailable'} />
                  <Stat label="Fair value · COMEX×INR model" value={fmtInr(fv?.fair ?? fv?.landed)}
                    color={T.amber} accent={T.amber}
                    sub={fv?.fair ? `vs settlement ${fmtSignedInr(fv.gap_vs_settlement)}` : fv?.landed_note} />
                  {quote.best && <Stat label="Desk price in use" value={fmtInr(quote.best.price)} accent={T.green}
                    sub={quote.best.source} />}
                </div>
              </>
            )}
            {/* 3. the COMEX × rupee overlay, one line (PLAN §b): no implied-premium prose; the ladder is on GOLD › PHYSICAL */}
            <div data-mcx-overlay style={{ display: 'flex', alignItems: 'center', gap: 8, borderTop: `1px solid ${T.border}`, paddingTop: 8, flexWrap: 'wrap' }}>
              <span style={{ fontFamily: T.mono, fontSize: 9.5, letterSpacing: 1.2, color: T.muted }}>COMEX × RUPEE</span>
              <span style={{ fontFamily: T.mono, fontSize: 11, color: T.text, flex: 1, minWidth: 0 }}
                    title={overlay?.fields?.settlement_session_label ? `fair value against the ${overlay.fields.settlement_session_label} (PROXY); live vs fair only against a live broker price, never against the model itself` : 'live vs fair appears when a live broker quote exists — never computed against the model itself'}>
                {overlayText(overlay)}
                {liveVsFair && <span style={{ color: Math.abs(liveVsFair.rupees) <= 300 ? T.green : T.red, marginLeft: 6 }}>({fmtSignedInr(liveVsFair.rupees)} · {fmtSigned(liveVsFair.pct, 2)} %)</span>}
                {overlay?.as_of && <span style={{ color: T.dim }}> · {istClock(overlay.as_of)} IST</span>}
              </span>
              <Chip color={T.amber} onClick={() => openGold('physical')} title="The India price stack: COMEX → × USD/INR → landed → + duty → IBJA → MCX, with the premium history">GOLD ›</Chip>
            </div>
          </Panel>

          {/* 4. the shared contract selector (replaces the specs card; same component as GOLD › CONTRACTS) */}
          <Panel source={undatedSource('MCX contract master', 'margins from the Zerodha NRML mirror, dated')} title="Contracts — MCX gold family" accent={T.cyan}
            subtitle="the selector GOLD › CONTRACTS uses · synced (prefs gold.contract.v1) · margins from the Zerodha NRML mirror, dated"
            right={<Chip color={T.amber} onClick={() => openGold('contracts')} title="Term structure, MCX chain, roll calendar, COMEX spec card">GOLD › CONTRACTS</Chip>}>
            <ContractSelector families={families} sel={sel} onSel={updateSel} dense />
          </Panel>

          {/* 5. paper ticket */}
          <Panel source={inputSource('the ticket you fill in (PAPER, records nothing)')} title="Paper gold ticket" accent={T.green}
            subtitle="prices the trade — PAPER, records nothing, no order API exists on this desk"
            bodyStyle={{ display: 'grid', gap: 12 }}>
            <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', alignItems: 'end' }}>
              <Select label="Contract" value={contract} onChange={setContract}
                options={codes.map(c => ({ value: c, label: `${c} (${families?.find(x => x.code === c)?.lot ?? ''})` }))} />
              <Input label="Lots" value={lots} onChange={setLots} />
              <Input label="Price (₹, blank = desk price)" value={priceIn} onChange={setPriceIn}
                placeholder={quote?.best ? `${quote.best.price} · ${quote.best.source}` : 'no price source yet'} />
              <Input label="Brokerage / order (₹)" value={brokerage} onChange={setBrokerage} />
            </div>
            {!ticket && <div style={{ fontSize: 11, color: T.muted }}>Enter a price (or wait for a desk price) to size the trade.</div>}
            {ticket && (
              <>
                <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))' }}>
                  <Stat label="Notional" value={fmtInr(ticket.notional)} accent={T.cyan}
                    sub={`${ticket.lots} × ${ticket.lot} @ ${fmtInr(ticket.price)}`} />
                  <Stat label={ticket.margin_source ? `Margin · ${ticket.margin_source}` : 'Indicative margin*'} value={fmtInr(ticket.indicative_margin)} color={T.amber} accent={T.amber}
                    sub={`${ticket.margin_pct_indicative}% ${ticket.margin_source ? 'NRML mirror' : 'SPAN+exposure'} — exchange revises daily`} />
                  <Stat label="Tick value" value={fmtInr(ticket.tick_value_position)} accent={T.violet}
                    sub={`${fmtInr(ticket.tick_value_per_lot)} per lot`} />
                  <Stat label="Round-trip cost" value={fmtInr(ticket.round_trip.total, 2)} accent={T.red} color={T.red}
                    sub={`${fmtNum(ticket.round_trip.pct_of_notional, 4)}% of notional · breakeven ${fmtNum(ticket.round_trip.breakeven_ticks, 1)} ticks (₹${fmtNum(ticket.round_trip.breakeven_price_move, 1)})`} />
                  {ticket.atr14_rupees != null && <Stat label="ATR14 (₹/10 g)" value={fmtInr(ticket.atr14_rupees)} accent={T.border}
                    sub={`≈ ${fmtInr(ticket.atr14_rupees * ticket.tick_value_per_lot)} per lot at a ₹1 tick · a normal day's range`} />}
                  {ticket.max_lots_at_risk_pct != null && <Stat label="Max lots at 1 % risk" value={fmtNum(ticket.max_lots_at_risk_pct, 1)} accent={T.border}
                    sub="lots whose ATR14 loss is 1 % of the paper capital (sizing arithmetic, not a signal)" />}
                  {ticket.hedge_usdinr_lots != null && <Stat label="USD/INR hedge" value={`${fmtNum(ticket.hedge_usdinr_lots, 2)} lots`} accent={T.border}
                    sub="currency futures to neutralise the rupee leg of this position" />}
                </div>
                <DataTable columns={legCols} rows={legRows} rowKey={r => r.side} dense empty="" />
                <div style={{ fontSize: 10, color: T.dim, lineHeight: 1.6 }}>
                  {ticket.note} Rates: exchange txn ₹2.10/lakh (0.0021%), CTT 0.01% sell side (squared-off futures),
                  SEBI ₹10/crore, stamp 0.002% buy side, GST 18% on brokerage+txn+SEBI — indicative; the source of every rate is listed in the terminal's MCX reference data.
                </div>
              </>
            )}
          </Panel>
        </div>
      )}
    </div>
  )
}

export default McxGoldDesk
