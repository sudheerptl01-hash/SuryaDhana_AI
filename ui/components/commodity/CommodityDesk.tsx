'use client'

/**
 * CommodityDesk — ONE MCX desk component, parameterized by family group (FINAL ROUND R5-CMDTY):
 * SILVER (SILVER / SILVERM / SILVERMIC) and CRUDE (CRUDEOIL / CRUDEOILM), from the MCXG template.
 *
 *   1. session clock  — the shared MCX calendar (/api/commodity/desk/families carries it; silver and
 *                       crude are non-agri and trade the same 09:00 → 23:30/23:55 session as gold)
 *   2. live quote     — ICICI Breeze through the SAME degrade-first path MCXG uses; otherwise an
 *                       HONEST degrade with the one fallback that always works: the ICICI price-band
 *                       midpoint, labelled with its real session (band proxy)
 *   3. daily chart    — InteractiveSeries candles from STORED rows only (/api/commodity/desk/daily →
 *                       data-service gold_mcx_daily). Until the gold_breeze_daily family extension
 *                       lands (pending patch request) the store has no silver/crude bars and the
 *                       panel says so — nothing is fetched client-side.
 *   4. contract card  — specs cross-checked against ICICI's security master (observed expiries, OI,
 *                       band settlement); margins are an INDICATIVE constant, badged heuristic
 *   5. paper ticket   — the MCXG ticket mechanics (notional, margin, round-trip costs, breakeven).
 *                       PAPER: it prices the trade and records nothing; no order API exists here.
 *
 * NO fair-value model (gold's COMEX-parity machinery is gold-only): prices and context, no verdicts.
 * Badges context / arithmetic / heuristic only; this desk describes, does not predict. Nothing here
 * feeds the Decision Desk, the S1 shadow, a directional alert or a ticket price.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Chip, DataTable, DESCRIBES, Input, Loading, Notice, Panel, Select, Stat, T,
         fmtInr, fmtNum, type Column, sourceOf, inputSource, undatedSource } from '@/components/terminal'
import { InteractiveSeries, type CandlePoint } from '@/components/terminal/InteractiveSeries'

const BOARD_MS = 300_000
const QUOTE_MS = 30_000

export type DeskGroup = 'SILVER' | 'CRUDE'

interface BandBlock {
  settlement: number; band_low: number; band_high: number; open_interest_lots: number
  session: string | null; session_label: string | null; band_applies_to: string | null
  quality: string; source: string
}
interface FamilyRow {
  code: string; name: string; group: DeskGroup; lot: string; multiplier: number
  tick_rupees: number; tick_value: number; quotation: string; delivery_unit: string
  purity: string | null; expiry_rule: string; cycle: string
  span_margin_pct_indicative: number; margin_source: string; notes: string; breeze_code: string
  computed_expiries: string[]
  observed_expiries: { expiry: string; open_interest_lots: number; band: BandBlock | null }[] | null
  front?: BandBlock & { expiry: string }
  indicative_margin_rupees?: number
}
interface BoardPayload {
  as_of: string; group: string | null; families: FamilyRow[]
  session: {
    is_open: boolean; segment: 'morning' | 'evening' | null; weekend: boolean
    holiday: { name: string; closure: string } | null
    opens_at: string; closes_at: string
    seconds_to_close: number | null; seconds_to_open: number | null
    note: string; calendar_warning?: string
    upcoming_holidays: { date: string; day: string; name: string; closure: string }[]
  }
  session_note: string
  master: { available: boolean; published: string | null; source: string }
  margin_note: string; fair_value_note: string; badge_note: string
}
interface QuotePayload {
  as_of: string; contract: string; breeze_code: string; expiry: string; expiry_source: string
  tick_value: number; lot: string; quote_unit: string
  available: boolean; reason?: string
  quote: { ltp: number | null; open: number | null; high: number | null; low: number | null
           previous_close: number | null; time: string | null; source: string } | null
  fallbacks: { band: BandBlock | null }
  best: { price: number; source: string } | null
  fair_value_note: string
}
interface DailyPayload {
  family: string; expiry: string | null; quote_unit: string; source: string; quality: string
  rows: { trade_date: string; open: number | null; high: number | null; low: number | null
          close: number | null; volume: number | null; open_interest: number | null; expiry: string }[]
  count: number
  degraded?: boolean
  error?: { message?: string; hint?: string } | null
}
interface TicketPayload {
  paper: boolean; recorded: boolean; contract: string; lot: string; lots: number; price: number
  quote_unit: string; notional: number; tick_value_per_lot: number; tick_value_position: number
  indicative_margin: number; margin_pct_indicative: number; margin_source: string; margin_basis: string
  round_trip: {
    turnover_per_side: number; buy: CostLeg; sell: CostLeg; total: number
    pct_of_notional: number | null; breakeven_ticks: number | null; breakeven_price_move: number | null
    assumptions: string
  }
  note: string
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
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60)
  return h > 0 ? `${h}h ${m}m` : `${m}m ${s % 60}s`
}
const istClock = (iso?: string | null) => iso
  ? new Date(iso).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })
  : '—'
const num = (s: string): number | undefined => {
  const v = Number(String(s).replace(/[,₹\s]/g, ''))
  return Number.isFinite(v) && v > 0 ? v : undefined
}

const GROUP_TITLE: Record<DeskGroup, string> = { SILVER: 'MCX silver desk', CRUDE: 'MCX crude desk' }

export function CommodityDesk({ group }: { group: DeskGroup }) {
  const [board, setBoard] = useState<BoardPayload | null>(null)
  const [quote, setQuote] = useState<QuotePayload | null>(null)
  const [daily, setDaily] = useState<DailyPayload | null>(null)
  const [ticket, setTicket] = useState<TicketPayload | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [contract, setContract] = useState<string>(group === 'SILVER' ? 'SILVER' : 'CRUDEOIL')
  const [expiry, setExpiry] = useState('')            // '' = front by open interest
  const [lots, setLots] = useState('1')
  const [priceIn, setPriceIn] = useState('')          // '' = use the desk's best price
  const [brokerage, setBrokerage] = useState('20')
  const [countdown, setCountdown] = useState<number | null>(null)
  const quoteReq = useRef(0)

  // ── board: specs + session + master (5 min) ───────────────────────────────────
  const loadBoard = useCallback(async () => {
    try {
      const b = await getJson<BoardPayload>(`/api/commodity/desk/families?group=${group}`)
      setBoard(b)
      setCountdown(b.session.is_open ? b.session.seconds_to_close : b.session.seconds_to_open)
      setErr(null)
    } catch (e: unknown) { setErr(e instanceof Error ? e.message : 'desk unavailable') }
  }, [group])
  useEffect(() => {
    loadBoard()
    const iv = setInterval(loadBoard, BOARD_MS)
    return () => clearInterval(iv)
  }, [loadBoard])
  useEffect(() => {
    const t = setInterval(() => setCountdown(c => (c == null ? c : Math.max(0, c - 1))), 1000)
    return () => clearInterval(t)
  }, [])

  // ── quote (30 s, degrade-honest) ──────────────────────────────────────────────
  const loadQuote = useCallback(async () => {
    const id = ++quoteReq.current
    try {
      const q = await getJson<QuotePayload>(
        `/api/commodity/desk/quote?contract=${contract}${expiry ? `&expiry=${expiry}` : ''}`)
      if (id === quoteReq.current) setQuote(q)
    } catch { /* the board panels still stand */ }
  }, [contract, expiry])
  useEffect(() => {
    setQuote(null)
    loadQuote()
    const iv = setInterval(loadQuote, QUOTE_MS)
    return () => clearInterval(iv)
  }, [loadQuote])

  // ── stored daily bars (per contract+expiry; EOD data, no poll) ────────────────
  useEffect(() => {
    let alive = true
    setDaily(null)
    getJson<DailyPayload>(`/api/commodity/desk/daily?family=${contract}${expiry ? `&expiry=${expiry}` : ''}`)
      .then(d => { if (alive) setDaily(d) })
      .catch(() => { if (alive) setDaily(null) })
    return () => { alive = false }
  }, [contract, expiry])

  // ── paper ticket (debounced POST; prices only, records nothing) ───────────────
  const ticketPrice = num(priceIn) ?? quote?.best?.price
  useEffect(() => {
    const lotsN = Math.max(1, Math.floor(num(lots) ?? 1))
    if (!ticketPrice) { setTicket(null); return }
    let alive = true
    const t = setTimeout(() => {
      getJson<TicketPayload>('/api/commodity/desk/ticket', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ contract, lots: lotsN, price: ticketPrice, brokerage_per_order: num(brokerage) ?? 20 }),
      }).then(p => { if (alive) setTicket(p) }).catch(() => { if (alive) setTicket(null) })
    }, 400)
    return () => { alive = false; clearTimeout(t) }
  }, [contract, lots, ticketPrice, brokerage])

  const fams = board?.families ?? []
  const fam = useMemo(() => fams.find(f => f.code === contract) ?? null, [fams, contract])
  const expiryOptions = useMemo(() => [
    { value: '', label: 'front (by OI)' },
    ...(fam?.observed_expiries ?? []).map(e => ({ value: e.expiry, label: e.expiry })),
    ...((fam?.observed_expiries?.length ? [] : fam?.computed_expiries ?? []).map(e => ({ value: e, label: `${e} · computed` }))),
  ], [fam])
  const session = board?.session ?? null
  const stateColor = session ? (session.is_open ? T.green : T.red) : T.muted
  const band = quote?.fallbacks.band ?? null

  const candles: CandlePoint[] = useMemo(() => {
    const rows = daily?.rows ?? []
    const byDate = new Map<string, DailyPayload['rows'][number]>()
    for (const r of rows) byDate.set(r.trade_date, r)   // one bar per date (the asked expiry, or the ladder's last)
    return [...byDate.values()]
      .sort((a, b) => a.trade_date.localeCompare(b.trade_date))
      .map(r => ({ t: r.trade_date, o: r.open, h: r.high, l: r.low, c: r.close }))
  }, [daily])

  const specCols: Column<FamilyRow>[] = [
    { key: 'code', label: 'Contract', render: r => (
        <span>
          <span style={{ color: r.code === contract ? T.bright : T.text, fontWeight: 600 }}>{r.code}</span>
          <span style={{ color: T.dim, marginLeft: 6 }}>{r.lot}</span>
        </span>) },
    { key: 'quotation', label: 'Quote', render: r => <span style={{ color: T.text }}>{r.quotation}</span> },
    { key: 'tick_value', label: 'Tick value', align: 'right', render: r => <span style={{ color: T.text }}>{fmtInr(r.tick_value)}</span> },
    { key: 'cycle', label: 'Cycle · expiry', render: r => <span style={{ color: T.muted }}>{r.cycle} · {r.expiry_rule}</span> },
    { key: 'front', label: 'Front (master)', align: 'right', render: r => r.front
        ? <span style={{ color: T.text }}>{r.front.expiry} <span style={{ color: T.dim }}>· OI {fmtNum(r.front.open_interest_lots)} lots</span></span>
        : <span style={{ color: T.dim }}>{r.computed_expiries[0]} · computed</span> },
    { key: 'margin', label: 'Margin / lot (indicative)', align: 'right', render: r => (
        <span style={{ color: T.text }} title={r.margin_source}>
          {r.indicative_margin_rupees != null ? fmtInr(r.indicative_margin_rupees) : '—'}
          <span style={{ color: T.dim }}> · {fmtNum(r.span_margin_pct_indicative)}%</span>
        </span>) },
  ]

  const legRows: LegRow[] = ticket ? (['buy', 'sell'] as const).map(side => ({ side, ...ticket.round_trip[side] })) : []
  const legCols: Column<LegRow>[] = [
    { key: 'side', label: 'Leg', render: r => <span style={{ color: T.text, fontWeight: 600 }}>{r.side.toUpperCase()}</span> },
    { key: 'brokerage', label: 'Brokerage', align: 'right', render: r => <span style={{ color: T.text }}>{fmtInr(r.brokerage, 2)}</span> },
    { key: 'exchange_txn', label: 'Exch 0.0021%', align: 'right', render: r => <span style={{ color: T.text }}>{fmtInr(r.exchange_txn, 2)}</span> },
    { key: 'ctt', label: 'CTT 0.01% (sell)', align: 'right', render: r => <span style={{ color: r.ctt ? T.amber : T.dim }}>{fmtInr(r.ctt, 2)}</span> },
    { key: 'stamp', label: 'Stamp (buy)', align: 'right', render: r => <span style={{ color: r.stamp ? T.text : T.dim }}>{fmtInr(r.stamp, 2)}</span> },
    { key: 'sebi', label: 'SEBI', align: 'right', render: r => <span style={{ color: T.text }}>{fmtInr(r.sebi, 2)}</span> },
    { key: 'gst', label: 'GST 18%', align: 'right', render: r => <span style={{ color: T.text }}>{fmtInr(r.gst, 2)}</span> },
    { key: 'total', label: 'Total', align: 'right', render: r => <span style={{ color: T.bright, fontWeight: 700 }}>{fmtInr(r.total, 2)}</span> },
  ]

  return (
    <div data-cmdty-desk={group} style={{ display: 'grid', gap: 12 }}>
      {/* header strip: group title · session chip · family + expiry selectors */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span style={{ fontFamily: T.display, fontSize: 13, fontWeight: 700, letterSpacing: 1.6, color: T.bright, textTransform: 'uppercase' }}>
          {GROUP_TITLE[group]}
        </span>
        {session && (
          <>
            <Chip color={stateColor}>{session.is_open ? `● OPEN · ${session.segment?.toUpperCase()}` : '■ CLOSED'}</Chip>
            <span style={{ fontFamily: T.mono, fontSize: 11, color: stateColor }}>
              {session.is_open ? `closes in ${hms(countdown)}` : `opens in ${hms(countdown)}`}
            </span>
            {session.holiday && <Chip color={T.amber}>{session.holiday.name} · {session.holiday.closure} closure</Chip>}
          </>
        )}
        <span style={{ flex: 1 }} />
        {fams.map(f => (
          <Chip key={f.code} color={f.code === contract ? T.cyan : T.muted} active={f.code === contract}
            onClick={() => { setContract(f.code); setExpiry('') }} title={`${f.name} · ${f.notes}`}>{f.code}</Chip>
        ))}
        <Select value={expiry} onChange={setExpiry} options={expiryOptions} />
      </div>

      {err && <Notice color={T.red}>Desk unavailable: {err}</Notice>}
      {!board && !err && <Loading label={`Reading the ${group.toLowerCase()} board`} />}

      {board && (
        <>
          {/* 2. quote — Breeze when served, else the band midpoint, each source-labelled */}
          <Panel title="Quote" badge="context" accent={T.cyan}
            source={sourceOf(quote?.as_of ?? null, { source: 'Breeze', live: !!quote?.available, maxAgeDays: 1 })}
            subtitle={quote
              ? `${quote.contract} ${quote.expiry} (${quote.expiry_source}) · broker code ${quote.breeze_code} · lot ${quote.lot} · ${quote.quote_unit} · tick ${fmtInr(quote.tick_value)}`
              : 'resolving the front contract'}
            bodyStyle={{ display: 'grid', gap: 10 }}>
            {!quote && <Loading label="Asking the broker and the price band" />}
            {quote?.available && quote.quote && (
              <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))' }}>
                <Stat label={`LTP · ${quote.quote.source}`} value={fmtInr(quote.quote.ltp)} accent={T.cyan}
                  sub={quote.quote.time ?? undefined} />
                <Stat label="Open" value={fmtInr(quote.quote.open)} accent={T.cyan} />
                <Stat label="High / Low" value={quote.quote.high == null && quote.quote.low == null
                  ? 'not served' : `${fmtInr(quote.quote.high)} / ${fmtInr(quote.quote.low)}`} accent={T.violet} />
                <Stat label="Prev close" value={quote.quote.previous_close == null ? 'not served' : fmtInr(quote.quote.previous_close)}
                  accent={T.border} />
              </div>
            )}
            {quote && !quote.available && (
              <>
                <Notice color={T.amber}><b>Broker quote unavailable</b> — {quote.reason ?? 'not served'}</Notice>
                <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))' }}>
                  <Stat label="ICICI band midpoint (reference)" value={fmtInr(band?.settlement)} accent={T.cyan}
                    sub={band
                      ? `band ${fmtInr(band.band_low)}–${fmtInr(band.band_high)} · OI ${fmtNum(band.open_interest_lots)} lots · BAND PROXY: the midpoint is the ${band.session_label ?? 'earlier session'}'s settlement`
                      : 'ICICI master unavailable'} />
                  {quote.best && <Stat label="Desk price in use" value={fmtInr(quote.best.price)} accent={T.cyan}
                    sub={quote.best.source} />}
                </div>
              </>
            )}
            <div style={{ fontSize: 10, color: T.dim }}>{quote?.fair_value_note ?? board.fair_value_note}</div>
          </Panel>

          {/* 3. daily chart — STORED broker bars only; honest empty until the family extension lands */}
          <Panel title="Daily bars" badge="context" accent={T.cyan}
            source={candles.length
              ? sourceOf(candles[candles.length - 1]?.t as string ?? null, { source: 'Breeze daily (stored)', maxAgeDays: 6 })
              : undatedSource('Breeze daily (stored)', 'no rows stored for this family yet')}
            subtitle={daily ? `${contract}${expiry ? ` · ${expiry}` : ''} · ${daily.quote_unit ?? ''} · ${candles.length} sessions · broker bars, not MCX's official bhavcopy` : undefined}>
            {!daily && <Loading label="Reading stored bars" />}
            {daily && candles.length >= 2 && (
              <InteractiveSeries height={240} ariaLabel={`${contract} stored daily bars`} calendar="mcx"
                series={[{ id: 'px', label: contract, type: 'candles', points: candles }]} />
            )}
            {daily && candles.length < 2 && (
              <div style={{ padding: '18px 8px', fontSize: 11, color: T.muted, lineHeight: 1.6 }}>
                No stored daily bars for {contract} yet. The store (gold_mcx_daily) is family-generic, but the
                09:35 gold_breeze_daily job fetches the gold families only — extending it to silver/crude is a
                pending owner/PM patch request. This panel reads the store and never fetches anything itself;
                the quote, contract card and ticket above stand on their own.
                {daily.error?.message && <div style={{ marginTop: 6, color: T.dim }}>({daily.error.message})</div>}
              </div>
            )}
          </Panel>

          {/* 4. contract card — specs + observed expiries from the master; margins badged heuristic */}
          <Panel title={`Contracts — MCX ${group.toLowerCase()} family`} badge="heuristic" accent={T.violet} pad={0}
            source={board.master.available && board.master.published
              ? sourceOf(board.master.published, { source: 'ICICI MCX master', maxAgeDays: 4 })
              : undatedSource('ICICI MCX master', 'master unavailable — computed expiries shown')}
            subtitle="lot · tick · cycle from the ICICI security master (MCX's own site is never fetched) · margin = indicative constant, no NRML mirror stored">
            <DataTable columns={specCols} rows={fams} rowKey={r => r.code} dense empty="no contracts" />
            <div style={{ padding: '6px 12px', fontSize: 10, color: T.dim, borderTop: `1px solid ${T.border}`, lineHeight: 1.6 }}>
              {board.margin_note} {board.session_note}
            </div>
          </Panel>

          {/* 5. paper ticket — arithmetic only */}
          <Panel title={`Paper ${group.toLowerCase()} ticket`} badge="arithmetic" accent={T.green}
            source={inputSource('the ticket you fill in (PAPER, records nothing)')}
            subtitle="prices the trade — PAPER, records nothing, no order API exists on this desk"
            bodyStyle={{ display: 'grid', gap: 12 }}>
            <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', alignItems: 'end' }}>
              <Select label="Contract" value={contract} onChange={c => { setContract(c); setExpiry('') }}
                options={fams.map(f => ({ value: f.code, label: `${f.code} (${f.lot})` }))} />
              <Input label="Lots" value={lots} onChange={setLots} />
              <Input label={`Price (${fam?.quotation ?? '₹'}, blank = desk price)`} value={priceIn} onChange={setPriceIn}
                placeholder={quote?.best ? `${quote.best.price} · ${quote.best.source}` : 'no price source yet'} />
              <Input label="Brokerage / order (₹)" value={brokerage} onChange={setBrokerage} />
            </div>
            {!ticket && <div style={{ fontSize: 11, color: T.muted }}>Enter a price (or wait for a desk price) to size the trade.</div>}
            {ticket && (
              <>
                <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))' }}>
                  <Stat label="Notional" value={fmtInr(ticket.notional)} accent={T.cyan}
                    sub={`${ticket.lots} × ${ticket.lot} @ ${fmtInr(ticket.price)}`} />
                  <Stat label="Margin (indicative)" value={fmtInr(ticket.indicative_margin)} color={T.amber} accent={T.amber}
                    sub={`${fmtNum(ticket.margin_pct_indicative)}% × notional · ${ticket.margin_source}`} />
                  <Stat label="Tick value" value={fmtInr(ticket.tick_value_position)} accent={T.violet}
                    sub={`${fmtInr(ticket.tick_value_per_lot)} per lot`} />
                  <Stat label="Round-trip cost" value={fmtInr(ticket.round_trip.total, 2)} accent={T.red} color={T.red}
                    sub={`${fmtNum(ticket.round_trip.pct_of_notional, 4)}% of notional · breakeven ${fmtNum(ticket.round_trip.breakeven_ticks, 1)} ticks (₹${fmtNum(ticket.round_trip.breakeven_price_move, 1)})`} />
                </div>
                <DataTable columns={legCols} rows={legRows} rowKey={r => r.side} dense empty="" />
                <div style={{ fontSize: 10, color: T.dim, lineHeight: 1.6 }}>{ticket.note}</div>
              </>
            )}
          </Panel>

          {/* the standing line (labelling rules §f): context only, one number once, no verdicts */}
          <div style={{ fontSize: 10, color: T.dim, lineHeight: 1.6 }}>
            {board.badge_note} — this desk {DESCRIBES}. Session clock: shared MCX calendar; data: ICICI Breeze +
            the ICICI security master + stored tables only. As of {istClock(board.as_of)} IST.
          </div>
        </>
      )}
    </div>
  )
}

export default CommodityDesk
