'use client'

/**
 * CONTRACTS — which contract, what it costs, when it rolls (PLAN a.9).
 *
 *  - `ContractSelector` (c.selector): the cascaded exchange × family × expiry choice with a card per family (lot, quote
 *    unit, purity, expiry rule, next expiries, tick value, OI by expiry, NRML margin from the Zerodha mirror with its
 *    date, round-trip cost, breakeven ticks, "1 % move = ₹", delivery unit, tender period, COMEX hedge ratio, options
 *    toggle) and a diff strip of what changes when you switch. It is ONE component: GOLD › CONTRACTS renders it with
 *    the page-global pickers above, MCXG renders it with its own pickers (`pickers`) in place of the old specs card
 *    (PLAN §b). The selection is the prefs-synced `gold.contract.v1`, shared by both pages.
 *  - c.comex: the COMEX term structure (six months) with the "1 week ago" ghost, calendar spreads and implied carry —
 *    "last trade, not settlement" while bulletin settlements are not allowed.
 *  - c.mcx: the MCX chain (expiry · settle PROXY · band · vs front · carry) with the roll warning. The chain is ONE session
 *    (D4, round 2): its settles are the ICICI band of `chain_session` (the server's), printed with that session and source,
 *    never the request date; the basis under it names its own session (the latest VWAP) and the note says they differ.
 *  - c.roll: the roll calendar (MCX expiries, COMEX first intent / FND / LTD, broker tender cut-off) with countdowns.
 *  - c.spec: the DES-style card of the matched COMEX contract (size, settlement, tick, InitMargin and % of notional).
 *  - c.links: the linked-only pages (TradingView, FedWatch, CME contract pages, MCX circulars, QuikStrike, DGCX, JPX).
 *
 * Data: /api/gold/contracts (MCX families; ?exchange=COMEX for the spec card), /api/gold/curve (COMEX, MCX),
 * /api/gold/calendar. All arithmetic (costs, carry, specs): no claim about the future anywhere on this view.
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { CHART_BOX, Chip, DataTable, KV, Select, Spark, T, fmtFixed, fmtSigned, useChartSize, type Column } from '@/components/terminal'
import { axisTicks } from '@/components/terminal/chart'
import { getGoldCalendar, getGoldContracts, getGoldCurve } from '@/lib/gold/api'
import { annualisedCarry, basisSettleLabel, basisTileWords, chainRowSettlement, chainSession, chainSettleNote, comexMonthLabel, contractDiff, curveBasisSettlement, dayLabel, daysBetween,
         daysWord, expiryMonthLabel, fmtInr0, fmtSignedPctSp, fmtUsd, marginHistoryDates, marginHistoryPoints, mmyLabel, onePctMove, quoteGrams, quoteUnitShort, rollWarning,
         settlementLine, settlementQualityChip, settlMethodWord, specMatches, specTick, stripSettlement, toPer10g, uomWord } from '@/lib/gold/format'
import { istDateISO } from '@/lib/format'
import { GOLD_FAMILIES, type ContractExpiryRow, type ContractFamily, type CurvePoint, type GoldContractSel, type GoldEvent, type GoldSubViewProps, type Layer } from '@/lib/gold/types'
import { Term } from './ViewBits'
import { GoldPanel, NoVerdict, Pending, useGoldLoad } from './kit'

const CONTRACTS_MS = 5 * 60_000
const EXCHANGES: { value: GoldContractSel['exchange']; label: string; disabled?: boolean; reason?: string }[] = [
  { value: 'MCX', label: 'MCX' },
  { value: 'NSE', label: 'NSE (n/a)', disabled: true, reason: 'NSE gold futures: negligible OI and no free data feed (G-INDIA §4.3)' },
  { value: 'BSE', label: 'BSE (n/a)', disabled: true, reason: 'BSE gold contracts: negligible OI (G-INDIA §4.3)' },
]
const LINKS: { name: string; url: string; what: string }[] = [
  { name: 'TradingView GC1!', url: 'https://www.tradingview.com/symbols/COMEX-GC1!/', what: 'the continuous COMEX front, charted' },
  { name: 'CME FedWatch', url: 'https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html', what: 'rate-path probabilities (the Atlanta Fed tracker is the stored source)' },
  { name: 'CME gold contract specs', url: 'https://www.cmegroup.com/markets/metals/precious/gold.contractSpecs.html', what: 'GC / MGC / 1OZ / QO specs, FND and LTD rules' },
  { name: 'MCX circulars', url: 'https://www.mcxindia.com/market-operations/circulars', what: 'expiry, holiday and Muhurat circulars (scripts are blocked; open in the browser)' },
  { name: 'QuikStrike / CVOL', url: 'https://www.cmegroup.com/tools-information/quikstrike/cme-group-volatility-index.html', what: 'gold options volatility and skew' },
  { name: 'DGCX gold', url: 'https://www.dgcx.ae/products/gold', what: 'the Dubai contract (INR-denominated gold exists there too)' },
  { name: 'JPX gold', url: 'https://www.jpx.co.jp/english/derivatives/products/precious-metals/gold-futures/', what: 'the Osaka contract (JPY/g)' },
]

/** The front contract of a family: the highest-OI expiry (the server's rule when `oi` is missing: the first row). */
export function frontExpiry(f: ContractFamily | null | undefined): ContractExpiryRow | null {
  if (!f?.expiries.length) return null
  return f.expiries.reduce<ContractExpiryRow | null>((best, e) => (best == null || (e.oi ?? -1) > (best.oi ?? -1) ? e : best), null)
}

function FamilyCard({ f, selected, onPick, today, tip, livePrice }: { f: ContractFamily; selected: boolean; onPick: () => void; today: string; tip: (k: string) => string | undefined; livePrice?: number | null }) {
  const front = frontExpiry(f)
  const move = onePctMove(f, livePrice)
  const next3 = f.expiries.slice(0, 3)
  const maxOi = Math.max(1, ...f.expiries.map(e => e.oi ?? 0))
  const accent = selected ? T.amber : T.border
  return (
    <div role="button" tabIndex={0} onClick={onPick} onKeyDown={e => { if (e.key === 'Enter') onPick() }} data-gold-family={f.code} data-selected={selected ? '1' : '0'}
      style={{ border: `1px solid ${accent}`, borderTop: `2px solid ${selected ? T.amber : T.borderHi}`, background: selected ? '#0d1119' : T.panel, padding: '8px 10px', cursor: 'pointer', minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
        <span style={{ fontFamily: T.display, fontSize: 13, fontWeight: 700, letterSpacing: 1.2, color: selected ? T.amber : T.bright }}>{f.code}</span>
        <span style={{ fontSize: 10, color: T.muted }}>{f.name ?? ''}</span>
        <span style={{ flex: 1 }} />
        <span style={{ fontFamily: T.mono, fontSize: 9.5, color: T.dim }}>{f.lot} · {f.quote_unit} · {f.purity}</span>
      </div>
      <KV items={[
        ['tick value', <span key="t" title={tip('tick_value')}>{f.tick_rupees != null ? `₹${fmtFixed(f.tick_rupees, 0)} = ` : ''}{fmtInr0(f.tick_value)}</span>],
        ['NRML margin', front?.margin_inr != null ? <span key="m" title={tip('indicative_margin')}>{fmtInr0(front.margin_inr)}{front.margin_pct != null ? ` (${fmtFixed(front.margin_pct, 2)} %)` : ''}<span style={{ color: T.dim }}> · {front.margin_source ?? 'mirror'}{front.margin_date ? ` ${dayLabel(front.margin_date)}` : ''}</span></span> : '—'],
        ['round trip', f.round_trip?.total != null ? <span key="r" title={tip('round_trip_total')}>{fmtInr0(f.round_trip.total)}{f.round_trip.pct != null ? ` (${fmtFixed(f.round_trip.pct, 3)} %)` : ''}{f.round_trip.breakeven_ticks != null ? ` · ${fmtFixed(f.round_trip.breakeven_ticks, 1)} ticks` : ''}</span> : '—'],
        ['1 % move', move.value != null ? <span key="1p" data-gold-one-pct={move.at} title={tip('one_pct_move_inr')}>{fmtInr0(move.value)}<span style={{ color: T.dim }}> · {move.at === 'live' ? 'at the live price' : `at the settlement (proxy${f.price_basis ? `, ${f.price_basis}` : ''})`}</span></span> : '—'],
        ['delivery', `${f.delivery_unit ?? '—'} · ${f.expiry_rule}`],
        ['tender', <span key="tn" title="tender period: from this date a short can tender delivery; the broker's own cut-off (ICICI, O-9) is earlier and decides when a swing position must be rolled">{front?.tender_start ? `${dayLabel(front.tender_start)} (${daysWord(front.tender_start, today)})` : f.tender_cutoff_note ?? 'broker cut-off: ask ICICI (O-9)'}</span>],
        ['COMEX hedge', f.hedge_ratio_oz != null ? `≈ ${fmtFixed(f.hedge_ratio_oz, 2)} oz per lot` : '—'],
      ]} />
      <div style={{ marginTop: 6, display: 'grid', gap: 2 }}>
        {next3.map(e => (
          <div key={e.expiry} style={{ display: 'grid', gridTemplateColumns: '64px 1fr 70px', gap: 6, alignItems: 'center', fontFamily: T.mono, fontSize: 10 }}>
            <span style={{ color: e === front ? T.amber : T.text }}>{expiryMonthLabel(e.expiry)}</span>
            <span style={{ height: 6, background: T.border }} title={`OI ${e.oi != null ? fmtFixed(e.oi, 0) : '—'} lots`}>
              <span style={{ display: 'block', height: 6, width: `${((e.oi ?? 0) / maxOi) * 100}%`, background: e === front ? T.amber : T.muted }} />
            </span>
            <span style={{ color: T.dim, textAlign: 'right' }}>{e.oi != null ? `${fmtFixed(e.oi, 0)}` : '—'}{e.source === 'computed' ? ' ·c' : ''}</span>
          </div>
        ))}
        {f.expiries.length === 0 && <span style={{ fontSize: 10, color: T.dim }}>no expiries from the master yet</span>}
      </div>
    </div>
  )
}

/** The shared contract selector (c.selector; MCXG's specs card): pickers (optional), family cards, diff strip, expiry ladder. */
export function ContractSelector({ families, sel, onSel, pickers = false, layer = 'B', tooltips = {}, dense = false, chainOnPage = false, livePrice = null }: {
  families: ContractFamily[] | null; sel: GoldContractSel; onSel: (p: Partial<GoldContractSel>) => void
  pickers?: boolean; layer?: Layer; tooltips?: Record<string, string>; dense?: boolean
  /** GOLD › CONTRACTS renders the MCX chain (c.mcx) below: the ladder then omits settle / band / carry, which the chain prints once (PLAN §f.6) */
  chainOnPage?: boolean
  /** the live MCX price of the SELECTED family (GOLD's strip / MCXG's quote): its card's '1 % move' is computed on it */
  livePrice?: number | null
}) {
  const today = istDateISO()
  const tip = (k: string) => tooltips[k]
  const fam = families?.find(f => f.code === sel.family) ?? null
  const prevCode = useRef<string | null>(null)
  const [from, setFrom] = useState<ContractFamily | null>(null)
  useEffect(() => {
    if (prevCode.current && prevCode.current !== sel.family) setFrom(families?.find(f => f.code === prevCode.current) ?? null)
    prevCode.current = sel.family
  }, [sel.family, families])
  const diff = useMemo(() => contractDiff(from, fam), [from, fam])
  const front = frontExpiry(fam)
  const picked = fam?.expiries.find(e => e.expiry === sel.expiry) ?? front
  const roll = fam && fam.expiries.length > 1 ? rollWarning(fam.expiries[0].oi_change, fam.expiries[1].oi_change) : null
  const exch = EXCHANGES.find(e => e.value === sel.exchange) ?? EXCHANGES[0]
  // the family's own quote unit (D3): PETAL is ₹/1 g, GUINEA ₹/8 g — never headed '₹/10 g'
  const famUnit = quoteUnitShort(fam?.quote_unit ?? fam?.code ?? sel.family)
  const ladderCols: Column<ContractExpiryRow>[] = [
    { key: 'expiry', label: 'Expiry', render: e => <span style={{ color: e === picked ? T.amber : T.text, fontWeight: e === picked ? 700 : 400 }}>{expiryMonthLabel(e.expiry)} <span style={{ color: T.dim }}>{e.expiry}</span>{e === front ? <Chip color={T.amber} style={{ marginLeft: 6, fontSize: 8.5, padding: '0 4px' }}>FRONT</Chip> : null}</span> },
    { key: 'source', label: 'Source', render: e => <span style={{ color: e.source === 'observed' ? T.green : T.dim }} title={e.source === 'observed' ? 'expiry observed in the ICICI MCX security master' : 'expiry computed from the family\'s rule (5th / month-end, holiday-shifted) until the master lists it'}>{e.source}</span> },
    ...(chainOnPage ? [] : [
      { key: 'settle', label: `settle ${famUnit}`, align: 'right' as const, render: (e: ContractExpiryRow) => {
        const st = { settlement: e.settle ?? null, settlement_source: e.settle_source ?? (e.settle != null ? 'band_midpoint' : null), settlement_session: e.settle_session ?? null, settlement_session_label: e.settle_session_label ?? null }
        return <span data-gold-ladder-settle={st.settlement_source ?? ''} title={settlementLine(st)}>{fmtInr0(e.settle)}{e.settle != null ? <span style={{ color: T.dim, fontSize: 9 }}> {settlementQualityChip(e.settle_quality, st.settlement_source)}{dayLabel(e.settle_session) ? ` · ${dayLabel(e.settle_session)}` : ''}</span> : null}</span>
      } },
      { key: 'band', label: `band ${famUnit}`, align: 'right' as const, render: (e: ContractExpiryRow) => { const bs = e.band_session ?? (e.settle_source === 'band_midpoint' ? e.settle_session : null)
        return <span style={{ color: T.muted }} title={bs ? `ICICI ±3 % band set around the ${dayLabel(bs)} settlement` : 'ICICI ±3 % band (the session it was set around is not stated)'}>{e.band_lo != null && e.band_hi != null ? `${fmtFixed(e.band_lo, 0)}–${fmtFixed(e.band_hi, 0)}` : '—'}</span> } },
    ]),
    { key: 'oi', label: 'OI lots', align: 'right', sort: e => e.oi, title: tip('open_interest_lots'), render: e => fmtFixed(e.oi, 0) },
    { key: 'oi_change', label: 'ΔOI lots', align: 'right', title: `${tip('oi_change') ?? ''} — vs the previous STORED master row, which can be more than one session back (POSITIONING names the span)`.trim(), render: e => <span style={{ color: T.muted }}>{fmtSigned(e.oi_change, 0)}</span> },
    // ONE carry convention, named by the server ('annualised vs the front expiry (as /curve)', C-DATA-16); on GOLD › CONTRACTS the chain prints it
    ...(chainOnPage ? [] : [
      { key: 'carry', label: 'carry vs front % p.a.', align: 'right' as const, title: `${tip('carry_ann') ?? ''} — ${fam?.expiries.find(x => x.carry_convention)?.carry_convention ?? 'annualised vs the front expiry'}`.trim(), render: (e: ContractExpiryRow) => <span style={{ color: T.muted }} title={e.carry_note ?? undefined}>{e.carry_pct != null ? fmtSignedPctSp(e.carry_pct, 1) : e.carry_note ? '— (2 sessions)' : '—'}</span> },
    ]),
    { key: 'comex', label: 'COMEX month', render: e => <span style={{ color: T.muted }}>{e.comex_matched ? comexMonthLabel(e.comex_matched) : '—'}</span> },
    { key: 'tender', label: 'Tender', render: e => <span style={{ color: T.muted }}>{e.tender_start ? `${dayLabel(e.tender_start)} · ${daysWord(e.tender_start, today)}` : '—'}</span> },
  ]
  return (
    <div data-gold-selector style={{ display: 'grid', gap: 10 }}>
      {pickers && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 10px', alignItems: 'center', fontSize: 10.5 }}>
          <span style={{ fontFamily: T.mono, fontSize: 9.5, letterSpacing: 1.2, color: T.muted }}>CONTRACT</span>
          <span title={exch.reason}>
            <Select value={sel.exchange} onChange={v => { const e = EXCHANGES.find(x => x.value === v); if (e && !e.disabled) onSel({ exchange: v }) }} options={EXCHANGES.map(e => ({ value: e.value, label: e.label }))} />
          </span>
          <Select value={sel.family} onChange={v => onSel({ family: v, expiry: null })} options={(families?.length ? families.map(f => f.code) : [...GOLD_FAMILIES]).map(c => ({ value: c as GoldContractSel['family'], label: c }))} />
          <Select value={sel.expiry ?? ''} onChange={v => onSel({ expiry: v || null })}
            options={[{ value: '', label: 'front (by OI)' }, ...(fam?.expiries ?? []).map(e => ({ value: e.expiry, label: `${expiryMonthLabel(e.expiry)} · ${e.expiry}` }))]} />
          <Chip color={sel.options ? T.violet : T.muted} active={sel.options} onClick={() => onSel({ options: !sel.options })} title="options (CE/PE) on the selected family">OPTIONS</Chip>
          <span style={{ color: T.dim, fontFamily: T.mono, fontSize: 10 }}>synced with GOLD (prefs gold.contract.v1)</span>
        </div>
      )}
      {!families && <div style={{ fontSize: 11, color: T.dim }}>Loading the contract families…</div>}
      {families && families.length === 0 && <NoVerdict what="/api/gold/contracts returned no families (the ICICI master is unavailable)" />}
      {families && families.length > 0 && (
        <div style={{ display: 'grid', gap: 8, gridTemplateColumns: `repeat(auto-fit, minmax(${dense ? 220 : 260}px, 1fr))` }}>
          {families.map(f => <FamilyCard key={f.code} f={f} selected={f.code === sel.family} onPick={() => onSel({ family: f.code as GoldContractSel['family'], expiry: null })} today={today} tip={tip}
            livePrice={f.code === sel.family ? livePrice : null} />)}
        </div>
      )}
      {diff.length > 0 && from && fam && (
        <div data-gold-diff style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 14px', alignItems: 'baseline', padding: '6px 10px', border: `1px solid ${T.border}`, background: '#07090d', fontFamily: T.mono, fontSize: 10 }}>
          <span style={{ color: T.muted, letterSpacing: 1 }}>{from.code} → {fam.code}</span>
          {diff.map(d => (
            <span key={d.key} style={{ color: d.changed ? T.text : T.dim }}>{d.label} <span style={{ color: T.dim }}>{d.from}</span> → <span style={{ color: d.changed ? T.amber : T.dim }}>{d.to}</span></span>
          ))}
        </div>
      )}
      {fam && (
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
            <span style={{ fontFamily: T.mono, fontSize: 9.5, letterSpacing: 1.2, color: T.muted }}>{fam.code} EXPIRIES · OI LADDER</span>
            {roll && <Chip color={T.amber} title="front-month OI falling faster than the next month is rising">⟳ {roll.split(':')[0].toUpperCase()}</Chip>}
            <span style={{ flex: 1 }} />
            <span style={{ fontSize: 10, color: T.dim }}>{layer === 'P' ? 'click a row to pick the expiry; the front is the highest-OI expiry more than 5 sessions from the tender period' : 'click a row to trade that month on MCXG and read it on every GOLD panel'}{chainOnPage ? ' · settle, band and carry: the MCX chain below' : ''}</span>
          </div>
          <DataTable columns={ladderCols} rows={fam.expiries} rowKey={e => e.expiry} dense onRowClick={e => onSel({ expiry: e.expiry })} exportName={`gold-${fam.code.toLowerCase()}-expiries`}
            empty="No expiries from the ICICI master yet (computed expiries appear once the rule runs)." />
          {sel.options && (
            <div data-gold-options style={{ marginTop: 8, padding: '6px 10px', border: `1px solid ${T.violet}55`, fontSize: 10.5, color: T.text }}>
              <b style={{ color: T.violet }}>OPTIONS</b>{' '}
              {fam.options?.available
                ? <>CE/PE on {fam.code}: expiries {fam.options.expiries?.map(expiryMonthLabel).join(' · ') || '—'}{fam.options.strike_step != null ? ` · strike step ₹${fmtFixed(fam.options.strike_step, 0)}` : ''}. </>
                : <>no option series on {fam.code} in the master. </>}
              <span style={{ color: T.muted }}>An exercised option becomes the underlying future; short-option margin is SPAN-based and far above the premium.</span>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

/** The COMEX term structure as dots and lines (price vs days to expiry), with the 1-week-ago ghost. */
function CurveChart({ points, ghost, ghostDate, label, fnd }: { points: CurvePoint[]; ghost: CurvePoint[]; ghostDate: string | null; label: string; fnd?: { days: number; month: string } | null }) {
  const { ref, w, h } = useChartSize(640, 220, { minRatio: 0.8, maxRatio: 1.2 })
  const padL = 56, padR = 16, padT = 14, padB = 30
  const plotW = Math.max(100, w - padL - padR), plotH = Math.max(80, h - padT - padB)
  const all = [...points, ...ghost].filter(p => p.settle_or_last != null)
  if (all.length < 2) return <NoVerdict what="needs at least two contract months" />
  const xs = all.map(p => p.days_to_expiry ?? 0), ys = all.map(p => p.settle_or_last as number)
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys)
  const pad = Math.max((y1 - y0) * 0.15, 1)
  const yAxis = axisTicks(y0 - pad, y1 + pad, plotH, 26)
  const x = (d: number) => padL + ((d - x0) / Math.max(1, x1 - x0)) * plotW
  const y = (v: number) => padT + plotH - ((v - (y0 - pad)) / (y1 + 2 * pad - y0)) * plotH
  const path = (pts: CurvePoint[]) => pts.filter(p => p.settle_or_last != null).map((p, i) => `${i ? 'L' : 'M'}${x(p.days_to_expiry ?? 0).toFixed(1)},${y(p.settle_or_last as number).toFixed(1)}`).join(' ')
  return (
    <div ref={ref} style={CHART_BOX}>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} role="img" aria-label={label}>
        {yAxis.ticks.map(t => (
          <g key={t}><line x1={padL} x2={padL + plotW} y1={y(t)} y2={y(t)} stroke={T.border} strokeDasharray="2 4" />
            <text x={padL - 6} y={y(t) + 3} textAnchor="end" fontSize={9.5} fill={T.muted} fontFamily={T.mono}>{fmtFixed(t, yAxis.dp)}</text></g>
        ))}
        <text x={padL - 6} y={padT - 3} textAnchor="end" fontSize={9} fill={T.dim} fontFamily={T.mono}>$/oz</text>
        {ghost.length > 1 && <path d={path(ghost)} fill="none" stroke={T.dim} strokeWidth={1} strokeDasharray="3 3" />}
        <path d={path(points)} fill="none" stroke={T.amber} strokeWidth={1.4} />
        {points.filter(p => p.settle_or_last != null).map((p, i) => (
          <g key={p.expiry}>
            <circle cx={x(p.days_to_expiry ?? 0)} cy={y(p.settle_or_last as number)} r={3} fill={i === 0 ? T.amber : T.panel} stroke={T.amber} />
            <text x={x(p.days_to_expiry ?? 0)} y={y(p.settle_or_last as number) + (i % 2 ? 13 : -7)} textAnchor="middle" fontSize={9} fill={T.text} fontFamily={T.mono}>{expiryMonthLabel(p.expiry)} {fmtFixed(p.settle_or_last, 1)}</text>
          </g>
        ))}
        {fnd && fnd.days >= x0 && fnd.days <= x1 && (
          <g data-gold-fnd-tick>
            <line x1={x(fnd.days)} x2={x(fnd.days)} y1={padT} y2={padT + plotH} stroke={T.violet} strokeDasharray="3 3" />
            <text x={x(fnd.days) + 3} y={padT + 10} fontSize={9} fill={T.violet} fontFamily={T.mono}>FND {fnd.month} · {fnd.days} d</text>
          </g>
        )}
        <line x1={padL} x2={padL + plotW} y1={padT + plotH} y2={padT + plotH} stroke={T.borderHi} />
        {points.map(p => <text key={`x-${p.expiry}`} x={x(p.days_to_expiry ?? 0)} y={padT + plotH + 12} textAnchor="middle" fontSize={9} fill={T.dim} fontFamily={T.mono}>{p.days_to_expiry ?? '—'} d</text>)}
        <text x={padL + plotW} y={padT + plotH + 24} textAnchor="end" fontSize={9} fill={T.dim} fontFamily={T.mono}>days to last trade{fnd ? ` · a long leaves by FND (${fnd.days} d)` : ''}{ghostDate ? ` · dotted = ${dayLabel(ghostDate)}` : ''}</text>
      </svg>
    </div>
  )
}

export function ContractsView({ sel, layer, comexMatched, tooltips, catalog, onSel, fair, overview }: GoldSubViewProps) {
  const today = istDateISO()
  const tip = (k: string) => tooltips[k]
  const mcx = useGoldLoad(() => getGoldContracts(sel.exchange), [sel.exchange], CONTRACTS_MS)
  const comexSpec = useGoldLoad(() => getGoldContracts('COMEX'), [], CONTRACTS_MS)
  const comexCurve = useGoldLoad(() => getGoldCurve('COMEX'), [], CONTRACTS_MS)
  const mcxCurve = useGoldLoad(() => getGoldCurve('MCX', undefined, sel.family), [sel.family], CONTRACTS_MS)   // THAT family's chain (API_CONTRACT §2.7)
  const cal = useGoldLoad(() => getGoldCalendar(90), [], 30 * 60_000)
  const families = mcx.data?.families ?? null
  const fam = families?.find(f => f.code === sel.family) ?? null
  const cc = comexCurve.data
  const pts = useMemo(() => (cc?.points ?? []).filter(p => p.settle_or_last != null).slice(0, 6), [cc])
  const spreads = useMemo(() => pts.slice(1).map((p, i) => ({ from: pts[i], to: p, spread: (p.settle_or_last as number) - (pts[i].settle_or_last as number),
    pct: ((p.settle_or_last as number) / (pts[i].settle_or_last as number) - 1) * 100,
    // the front→next pair is the number the verdict / header print: the server's figure, so one rounding appears on the page
    ann: i === 0 && p.annualised_carry_pct != null ? p.annualised_carry_pct : annualisedCarry(pts[i].settle_or_last, p.settle_or_last, daysBetween(pts[i].expiry, p.expiry)) })), [pts])
  const mc = mcxCurve.data
  // the server already answers for `?family=`; rows that name another family (a stale cache, a mixed store) are dropped by EQUALITY
  const mcxRows = useMemo(() => (mc?.points ?? []).filter(p => !p.symbol || (p.symbol ?? '').toUpperCase() === sel.family), [mc, sel.family])
  const mcxRoll = mcxRows.length > 1 ? rollWarning(mcxRows[0].oi_change, mcxRows[1].oi_change) : null
  // the live MCX price of the selected family (the strip's quote, same page load) — the card's '1 % move' uses it (wave 1d)
  const livePrice = overview?.strip?.mcx_shown === 'live' && (overview.contract?.mcx ?? sel.family) === sel.family ? overview.strip.mcx_live ?? null : null
  // D4 (round 2): the chain is ONE session — the band of the server's `chain_session` — never the request date (`mc.date`)
  const chain = useMemo(() => chainSession(mc), [mc])
  // the basis's settlement: the curve's own basis block (its `mcx_front_*` names, same family), else this page's fair block
  // when it is the same family — the latest session's VWAP when the server has it, a DIFFERENT session from the chain's band
  const pageFair = (fair?.contract ?? sel.family) === sel.family ? fair : null
  const chainSettle = useMemo(() => curveBasisSettlement(mc?.basis) ?? (pageFair ? stripSettlement(overview?.strip, pageFair) : null), [mc?.basis, pageFair, overview?.strip])
  const chainNote = chainSettleNote(chain, chainSettle)
  const famQuote = fam?.quote_unit ?? sel.family
  const chainUnit = quoteUnitShort(famQuote)
  const scaledFamily = (quoteGrams(famQuote) ?? 10) !== 10
  // MCX carry vs COMEX carry (the analyst: 12–13 % p.a. vs 5.2 % unexplained): the gap printed as arithmetic, explained in words
  const mcxCarry = mcxRows.find(p => p.annualised_carry_pct != null)?.annualised_carry_pct ?? null
  const mcxCols: Column<CurvePoint>[] = [
    { key: 'expiry', label: 'Expiry', render: p => <span style={{ color: T.text }}>{expiryMonthLabel(p.expiry)} <span style={{ color: T.dim }}>{p.expiry}</span>{p.symbol ? <span style={{ color: T.dim }}> · {p.symbol}</span> : null}</span> },
    // every settle names its session and source (D4): the column head carries the chain's one session; a row of another session says so
    { key: 'settle', label: `settle ${chainUnit}${chain.day ? ` · ${chain.day}` : ''}`, align: 'right', title: `${chain.source === 'breeze_vwap30' ? 'last-30-min VWAP (Breeze)' : 'ICICI band midpoint'} of the ${chain.day || '(not stated)'} session — proxy until the official bhavcopy (O-8)`,
      render: p => { const rs = chainRowSettlement(p, chain); const rDay = dayLabel(rs.settlement_session)
        return <span data-gold-chain-row-session={rs.settlement_session ?? ''} title={settlementLine(rs)}>{fmtInr0(p.settle_or_last)} <span style={{ color: T.dim, fontSize: 9 }}>{(p.quality ?? '').toLowerCase() === 'official' ? 'OFFICIAL' : settlementQualityChip(null, rs.settlement_source)}{rDay && rDay !== chain.day ? ` · ${rDay}` : ''}</span></span> } },
    // D3: a PETAL (₹/1 g) / GUINEA (₹/8 g) chain also prints its ₹/10 g equivalent, labelled as scaled
    ...(scaledFamily ? [{ key: 'per10g', label: '₹/10 g eq.', align: 'right' as const, title: toPer10g(1, famQuote).label,
      render: (p: CurvePoint) => <span style={{ color: T.muted }} data-gold-per10g>{fmtInr0(toPer10g(p.settle_or_last, famQuote).value)}</span> }] : []),
    { key: 'band', label: `band ${chainUnit}`, align: 'right', render: p => { const bs = p.band_session ?? (chainRowSettlement(p, chain).settlement_source === 'band_midpoint' ? chain.session : null)
      return <span style={{ color: T.muted }} title={bs ? `ICICI ±3 % band set around the ${dayLabel(bs)} settlement` : 'ICICI ±3 % band (the session it was set around is not stated)'}>{p.band_lo != null && p.band_hi != null ? `${fmtFixed(p.band_lo, 0)}–${fmtFixed(p.band_hi, 0)}` : '—'}</span> } },
    // OI and ΔOI print once on this view: in the expiry ladder above (PLAN §f.6)
    { key: 'spread', label: `vs front ${chainUnit}`, align: 'right', render: p => <span style={{ color: T.muted }}>{fmtSigned(p.spread_vs_front, 0)}</span> },
    { key: 'carry', label: 'carry % p.a.', align: 'right', title: tip('carry_ann'), render: p => <span style={{ color: T.muted }}>{p.annualised_carry_pct != null ? fmtSignedPctSp(p.annualised_carry_pct, 1) : '—'}</span> },
    { key: 'dte', label: 'days', align: 'right', render: p => <span style={{ color: T.dim }}>{p.days_to_expiry ?? '—'}</span> },
  ]
  const spec = comexSpec.data?.comex_spec ?? null
  // the DES card must describe the MATCHED month (C-BEGINNER-4 / C-DATA-8): a PRF row of another month is shown with its
  // own month in the title and a notice, never under the matched-month title
  const specIsMatched = specMatches(spec, comexMatched)
  const specMonth = spec ? (spec.month ?? mmyLabel(spec.mmy)) : null
  const tick = specTick(spec)
  const fndTick = spec?.first_notice && specIsMatched !== false ? (() => { const d = daysBetween(today, spec.first_notice); return d != null && d >= 0 && specMonth ? { days: d, month: specMonth } : null })() : null
  const events = useMemo(() => {
    const rows = (cal.data?.events ?? []).filter(e => /expir|notice|intent|ltd|fnd|last trade|tender|roll/i.test(`${e.kind} ${e.name}`))
    // the stored calendar wins; the contracts and the CME spec card only fill the dates it does not carry
    const covered = (date: string, word: string) => rows.some(e => e.event_date === date && new RegExp(word, 'i').test(e.name))
    const extra: GoldEvent[] = []
    for (const f of families ?? []) for (const e of f.expiries.slice(0, 2)) {
      if (covered(e.expiry, f.code)) continue
      extra.push({ event_date: e.expiry, kind: 'MCX_EXPIRY', name: `MCX ${f.code} ${expiryMonthLabel(e.expiry)} expiry`, detail: e.tender_start ? `tender from ${dayLabel(e.tender_start)}` : null, source: 'contracts' })
    }
    // every COMEX row names its contract month (the Nov month was unlabelled, C-TRADER-13)
    const mon = spec ? ` ${spec.month ?? mmyLabel(spec.mmy)}` : ''
    if (spec?.first_notice && !covered(spec.first_notice, 'first notice')) extra.push({ event_date: spec.first_notice, kind: 'COMEX_FND', name: `COMEX ${spec.symbol}${mon} first notice`, detail: 'a long can be assigned delivery from here', source: 'cme_prf' })
    if (spec?.last_trade && !covered(spec.last_trade, 'last trade')) extra.push({ event_date: spec.last_trade, kind: 'COMEX_LTD', name: `COMEX ${spec.symbol}${mon} last trade`, detail: spec.ltd_end_time ? `${spec.ltd_end_time} CT` : null, source: 'cme_prf' })
    if (spec?.first_intent && !covered(spec.first_intent, 'first intent')) extra.push({ event_date: spec.first_intent, kind: 'COMEX_INTENT', name: `COMEX ${spec.symbol}${mon} first intent`, source: 'cme_prf' })
    const seen = new Set<string>()
    return [...rows, ...extra].filter(e => { const k = `${e.event_date}|${e.name}`; if (seen.has(k)) return false; seen.add(k); return true })
      .filter(e => e.event_date >= today).sort((a, b) => a.event_date.localeCompare(b.event_date)).slice(0, 14)
  }, [cal.data, families, spec, today])

  return (
    <div style={{ display: 'grid', gap: 12 }}>
      {/* c.selector */}
      <GoldPanel id="c.selector" title="Choose the contract" badge="arithmetic" layer={layer} accent={T.amber} catalog={catalog} series={['MCX_CURVE_ICICI', 'MCX_MARGIN_ZERODHA']}
        subtitle={fam ? `${fam.code} · ${fam.lot} · ${fam.purity} · ${fam.expiry_rule}` : 'MCX gold family · expiry · options'}
        freshness={mcx.data ? (mcx.data.freshness ?? { state: 'delayed', source: 'ICICI master + Zerodha margin mirror', as_of: mcx.data.as_of ?? null }) : null}
        copyB={<>Which contract for which purpose: GOLD and GOLDM carry the liquidity (<Term t="open interest" />); TEN, GUINEA and PETAL are small but cost more per rupee traded (PETAL&apos;s round trip is 0.34 % of notional vs 0.018 % on GOLD, G-INDIA §4.2). The <Term t="tick value" /> is what one price step is worth per lot. Click a card, then an expiry.</>}
        copyP="GOLD/GOLDM are 995 fine settling on the 5th; the smaller families settle month-end at the purity their card prints (the basis divides by the landed price of that purity); options expire before the future they settle into. Margins are the Zerodha NRML mirror with their date; costs from shared/mcx_specs round_trip_costs at ₹20/order; '1 % move' at the live price when the page holds one, else at the settlement proxy.">
        <ContractSelector families={families} sel={sel} onSel={p => onSel?.(p)} layer={layer} tooltips={tooltips} chainOnPage livePrice={livePrice} />
      </GoldPanel>

      <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 620px), 1fr))', alignItems: 'start' }}>
        {/* c.comex */}
        <GoldPanel id="c.comex" title="COMEX term structure" badge="arithmetic" layer={layer} accent={T.cyan}
          subtitle={<>{cc?.price_label ?? 'last trade, not settlement'} · {cc?.date ? dayLabel(cc.date) : '—'}{comexMatched ? ` · matched ${comexMonthLabel(comexMatched)}` : ''}</>}
          freshness={cc ? (cc.freshness ?? { state: 'delayed', source: 'Yahoo per-month prices', as_of: cc.date }) : null}
          catalogRow={catalog.COMEX_CARRY_ANN_PCT ?? null} catalog={catalog} series={['COMEX_CURVE_YAHOO', 'COMEX_CARRY_ANN_PCT']}
          copyB={<><Term t="contango" /> (later months dearer) is the normal state for gold; backwardation is news. The <Term t="term structure" /> is read against days to last trade, with the matched month&apos;s first notice day marked: a long must leave by then. The dotted line is the same curve a week ago.</>}
          copyP="Carry = (F2/F1 − 1) × 365/days; implied lease ≈ SOFR − carry. Yahoo's per-month LAST TRADE until bulletin settlements are allowed (C7, O-2); front-next OI appears then too.">
          <Pending s={comexCurve} label="the COMEX curve">
            {pts.length < 2 ? <NoVerdict what="per-month COMEX prices are stored by the overnight job" />
              : <>
                <CurveChart points={pts} ghost={cc?.ghost_1w ?? []} ghostDate={cc?.ghost_date ?? null} label="COMEX gold term structure" fnd={fndTick} />
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '2px 14px', fontFamily: T.mono, fontSize: 10, color: T.muted, marginTop: 4 }} title="calendar spread = next month − front; carry = (F2/F1 − 1) × 365/days p.a.; implied lease ≈ SOFR − carry">
                  {spreads.map(s => <span key={s.to.expiry}>{expiryMonthLabel(s.from.expiry)}→{expiryMonthLabel(s.to.expiry)} {fmtSigned(s.spread, 1)} = {fmtSignedPctSp(s.pct, 2)}{s.ann != null ? ` (${fmtSignedPctSp(s.ann, 1)}/yr)` : ''}</span>)}
                </div>
              </>}
          </Pending>
        </GoldPanel>

        {/* c.spec */}
        <GoldPanel id="c.spec" title={`COMEX spec · ${spec ? `${spec.symbol} ${specMonth}` : comexMatched ? comexMonthLabel(comexMatched) : 'matched month'}`} badge="arithmetic" layer={layer} accent={T.cyan}
          subtitle={spec ? (specIsMatched === false ? `PRF row ${specMonth}, not the matched ${comexMonthLabel(comexMatched)}` : specIsMatched ? `the matched month ${comexMonthLabel(comexMatched)}` : undefined) : undefined}
          catalog={catalog} series={['CME_PRF']}
          // the card's source is the CME product reference file, not the ICICI master the contracts payload's freshness describes (REREVIEW)
          freshness={comexSpec.data ? (spec ? { state: 'delayed', source: 'CME PRF (FTP)', as_of: spec.margin_date ?? null } : (comexSpec.data.freshness ?? null)) : null}
          copyB={<>The DES card of the matched month: how big one contract is, how it settles, what a tick is worth, how much margin the exchange asks, and the two dates that end it (<Term t="FND / LTD" />: first notice day, then last trade).</>}
          copyP="GC: 100 troy oz, physical delivery, tick $0.10 = $10 (PRF MinPxIncr × DisplayFactor 0.1); InitMargin from the CME product reference file (speculator vs hedger rate unresolved, j.2 #6); % of notional at the matched month's last price — ≈ 5 % means 20× leverage, a 5 % move wipes the margin. The card is the PRF row whose month equals the matched month; a fallback row says which month it is.">
          <Pending s={comexSpec} label="the spec card">
            {!spec ? <NoVerdict what="the CME product reference file (C4) is fetched by the 15:45 job" /> : (
              <>
                {specIsMatched === false && (
                  <div data-gold-spec-mismatch style={{ fontSize: 10.5, color: T.amber, marginBottom: 6 }}>
                    This PRF row is {spec.symbol} {specMonth}, not the matched {comexMonthLabel(comexMatched)}: its first notice / last trade are {specMonth}&apos;s. The matched month&apos;s row arrives with the CME product-reference refresh.
                  </div>
                )}
                <KV cols={2} items={[
                  ['contract', `${spec.symbol} ${specMonth}${spec.mmy ? ` (${spec.mmy})` : ''}${spec.description ? ` · ${spec.description}` : ''}`],
                  ['size', spec.uom_qty != null ? `${fmtFixed(spec.uom_qty, 0)} ${uomWord(spec.uom)}` : '—'],
                  ['settlement', settlMethodWord(spec.settl_method_label ?? spec.settl_method)],
                  ['tick', tick ? `$${fmtFixed(tick.tick, 2)} = $${fmtFixed(tick.value, 0)} per contract` : '—'],
                  ['init margin', spec.init_margin_usd != null ? `$${fmtFixed(spec.init_margin_usd, 0)}${spec.margin_pct_of_notional != null ? ` ≈ ${fmtFixed(spec.margin_pct_of_notional, 1)} % of notional` : ''}${spec.margin_date ? ` · ${dayLabel(spec.margin_date)}` : ''}` : '—'],
                  ['ref price', fmtUsd(spec.ref_price, 1)],
                  [`first notice ${specMonth}`, spec.first_notice ? `${dayLabel(spec.first_notice)} · ${daysWord(spec.first_notice, today)}` : '—'],
                  [`last trade ${specMonth}`, spec.last_trade ? `${dayLabel(spec.last_trade)}${spec.ltd_end_time ? ` ${spec.ltd_end_time} CT` : ''} · ${daysWord(spec.last_trade, today)}` : '—'],
                  ['eligibility', [spec.elig_efp ? 'EFP' : null, spec.elig_block ? 'block' : null].filter(Boolean).join(' · ') || '—'],
                ]} />
                {(() => { const hist = marginHistoryPoints(spec.margin_history); return hist.length > 2 ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 10, color: T.dim, marginTop: 6 }} title={spec.margin_history_note ?? 'outright InitMargin per trade date; rows under $1,000 (other products) dropped'}>
                    margin history · {hist.length} dates <Spark values={hist} width={160} height={20} color={T.muted} />
                  </div>
                ) : (() => { const n = marginHistoryDates(spec.margin_history); return <div data-gold-margin-dates={n} style={{ fontSize: 10, color: T.dim, marginTop: 6 }}>margin history: {n} date{n === 1 ? '' : 's'} stored (a sparkline needs three){spec.margin_history_note ? ` · ${spec.margin_history_note}` : ''}</div> })() })()}
              </>
            )}
          </Pending>
        </GoldPanel>

        {/* c.mcx — its own full-width row: eight columns need the width (they were clipped in a 3-column grid at 1600 px) */}
        <GoldPanel id="c.mcx" title={`MCX chain · ${sel.family}`} badge="arithmetic" layer={layer} accent={T.amber} pad={0} style={{ gridColumn: '1 / -1' }}
          catalog={catalog} series={['MCX_CURVE_ICICI', 'MCX_BASIS_PCT']}
          // D4: the settles' session is the server's chain_session (the band's own), the OI's is oi_session — never the request date
          subtitle={<span data-gold-chain-session={chain.session ?? ''} title={mc?.price_label ?? undefined}>settles: {mc?.chain_session_label ?? (chain.day ? `${chain.day} settlement` : 'session not stated')} · {chain.source === 'breeze_vwap30' ? 'last-30-min VWAP (Breeze)' : 'ICICI band midpoint'} (proxy){chain.oiSession ? ` · OI at the ${dayLabel(chain.oiSession)} close` : ''}{mc?.family ? ` · ${mc.family} · ${chainUnit}` : ''}{mc?.since ? ` · since ${mc.since}` : ''}{mcxRoll ? ' · roll warning' : ''}</span>}
          freshness={mc ? (mc.freshness ?? { state: 'delayed', source: 'ICICI master (proxy settlement)', as_of: chain.session }) : null}
          copyB={<>Every listed month of the chosen family with its settlement (the ICICI band midpoint of ONE session, a proxy, dated by that session) and what it costs to hold the later month instead (carry vs the front). The <Term t="MCX basis" /> under the table names its own session — the latest close&apos;s last-30-min VWAP when it is known, which can be a later session than the chain&apos;s band.</>}
          copyP="MCX back months carry more than COMEX: rupee interest rates run above dollar rates and a duty / local-demand expectation sits on top — a cost a long pays at each roll, not free money. The chain's settles are the ICICI ±3 % band midpoints of one session (the band of a master file is the settlement two sessions before it), labelled with that session — never the file or request date — until official bhavcopy rows exist (O-8); vs-front and carry are taken inside that one session. The basis uses the latest session's last-30-min VWAP of the Breeze 1-minute bars (VWAP30 PROXY) when known, else the band (BAND PROXY). PETAL (₹/1 g) and GUINEA (₹/8 g) also print a ₹/10 g equivalent."
          right={mcxRoll ? <Chip color={T.amber} title={mcxRoll}>⟳ ROLL</Chip> : undefined}>
          <Pending s={mcxCurve} label="the MCX chain">
            <DataTable columns={mcxCols} rows={mcxRows} rowKey={p => `${p.symbol ?? ''}-${p.expiry}`} dense exportName="gold-mcx-chain" onRowClick={p => onSel?.({ expiry: p.expiry })}
              empty="No MCX curve rows yet — history begins the day the 07:35 master job starts." />
            {mc?.basis && (
              <div data-gold-mcx-basis style={{ padding: '6px 12px', fontSize: 10.5, color: T.muted, borderTop: `1px solid ${T.border}` }} title={tip('mcx_basis_pct')}>
                {/* the basis names its clock (C-BEGINNER-5 / C-DATA-11); the landed / duty-paid rupees are the page's ONE fair block (C-TRADER-19) */}
                {/* the basis's OWN session (never the request date): the server's label verbatim, its purity once, its settle source once */}
                {(() => {
                  const lbl = basisSettleLabel(mc.basis.basis_label ?? (mc.basis.mcx_front_session_label ?? null), mc.basis.basis_date ?? mc.basis.mcx_front_session ?? null)
                  const words = basisTileWords(lbl, mc.basis.basis_reference)
                  return <>basis <b style={{ color: T.text }}>{fmtSignedPctSp(mc.basis.basis_pct, 2)}</b> {words}
                    {chainSettle && !/VWAP|band/iu.test(words) && <span data-gold-chain-settle-source> · settle {settlementLine(chainSettle)}</span>}</>
                })()}
                {' · '}landed {fmtInr0(pageFair?.landed ?? mc.basis.landed_inr)} · duty {(pageFair?.duty_pct ?? mc.basis.duty_pct) != null ? `${fmtFixed(pageFair?.duty_pct ?? mc.basis.duty_pct, 0)} %` : '—'}{(pageFair?.duty_effective ?? mc.basis.duty_effective) ? ` since ${dayLabel(pageFair?.duty_effective ?? mc.basis.duty_effective)}` : ''} (confirm at CBIC) · duty-paid landed now {fmtInr0(pageFair?.duty_paid_landed ?? mc.basis.duty_paid_landed_inr)} {chainUnit} (the same rupee as HEALTH and PHYSICAL) · USD/INR {fmtFixed(mc.basis.usdinr, 2)}{mc.basis.usdinr_source ? ` ${mc.basis.usdinr_source}` : ''}
              </div>
            )}
            {chainNote && <div data-gold-settle-note={chainNote.tone} data-gold-chain-note style={{ padding: '4px 12px', fontSize: 10.5, color: chainNote.tone === 'amber' ? T.amber : T.muted }}>⚠ {chainNote.text}</div>}
            {mcxCarry != null && spreads[0]?.ann != null && (
              <div data-gold-carry-gap style={{ padding: '4px 12px', fontSize: 10.5, color: T.muted }} title={tip('annualised_carry_pct')}>
                carry: MCX {fmtSignedPctSp(mcxCarry, 1)} p.a. (band, {chain.day || 'its session'}) vs COMEX {expiryMonthLabel(spreads[0].from.expiry)}→{expiryMonthLabel(spreads[0].to.expiry)} {fmtSignedPctSp(spreads[0].ann, 1)} p.a. · gap {fmtSigned(mcxCarry - spreads[0].ann, 1)} pp —
                the rupee–dollar interest differential (not stored on this page) explains part of it; the rest is local demand / duty expectation. A long pays it at each roll.
              </div>
            )}
            {(mc?.history?.length ?? 0) > 2 && (
              <div style={{ padding: '4px 12px 8px', display: 'flex', alignItems: 'center', gap: 8, fontSize: 10, color: T.dim }}>
                basis history <Spark values={mc!.history!.map(h => h.basis_pct ?? NaN)} width={160} height={20} color={T.muted} baseline={0} />
              </div>
            )}
          </Pending>
        </GoldPanel>

        {/* c.roll */}
        <GoldPanel id="c.roll" title="Roll calendar" badge="arithmetic" layer={layer} accent={T.violet} pad={0} style={{ gridColumn: '1 / -1' }}
          catalog={catalog} series={['GOLD_EVENTS', 'CME_CALENDAR']}
          freshness={cal.data ? { state: 'delayed', source: 'gold_events · contracts · cme_prf' } : null}
          copyB={<>When each month stops being tradeable — the <Term t="roll" /> dates. Before COMEX <Term t="first notice day" /> a long can be assigned delivery; speculators leave the front month in the two weeks before. MCX GOLD DEC-26 expires Fri 4 Dec (the 5th is a Saturday).</>}
          copyP="Sources: MCX expiries from the ICICI master (computed fallback), COMEX first intent / FND / LTD from the CME product reference file, the broker tender cut-off from the owner (O-9). The pre-open desk maps GCZ26 → GCG27 around 25 Nov while MCX DEC runs to 4 Dec.">
          <Pending s={cal} label="the calendar">
            {events.length === 0 && <div style={{ padding: 12, fontSize: 11, color: T.muted }}>No roll events in the next 90 days (or the calendar is not ingested yet).</div>}
            {events.map(e => (
              <div key={`${e.event_date}-${e.name}`} style={{ display: 'grid', gridTemplateColumns: '88px 1fr auto', gap: 8, padding: '5px 12px', borderBottom: `1px solid ${T.border}`, fontSize: 11 }}>
                <span style={{ color: T.muted, fontFamily: T.mono }}>{dayLabel(e.event_date)}</span>
                <span style={{ color: T.text }}>{e.name}{e.detail ? <span style={{ color: T.dim }}> · {e.detail}</span> : null}</span>
                <span style={{ color: (daysBetween(today, e.event_date) ?? 99) <= 7 ? T.amber : T.dim, fontFamily: T.mono, fontSize: 10 }}>{daysWord(e.event_date, today)}</span>
              </div>
            ))}
            <div style={{ padding: '6px 12px', fontSize: 10, color: T.dim }}>Broker tender cut-off for MCX GOLD/GOLDM: not in the repo — ask ICICI (owner action O-9); it decides when a swing position must be rolled.</div>
          </Pending>
        </GoldPanel>
      </div>

      {/* c.links — no evidence badge (PLAN a.9 gives link panels none; §f.1 reserves `context` for a study verdict) */}
      <GoldPanel id="c.links" title="Linked (no free feed)" layer={layer} accent={T.border} pad={8} catalog={catalog} series={[]}
        copyB="Pages worth opening in a browser; the terminal never fetches them (terms or bot blocks)."
        copyP="LINK-ONLY per SOURCES.md: www.cmegroup.com and mcxindia.com are never fetched by the stack; the CME FTP route is the data source."
        right={<Chip color={T.muted} title="Links only: the stack never fetches these hosts (SOURCES.md LINK-ONLY)">LINK-ONLY</Chip>}>
        <div style={{ display: 'grid', gap: 6, gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))' }}>
          {LINKS.map(l => (
            <a key={l.name} href={l.url} target="_blank" rel="noreferrer" data-link-only style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 8, alignItems: 'center', padding: '6px 10px', border: `1px solid ${T.border}`, textDecoration: 'none', color: T.text }}>
              <span><span style={{ fontSize: 11.5 }}>{l.name}</span><div style={{ fontSize: 9.5, color: T.dim }}>{l.what}</div></span>
              <Chip color={T.cyan}>↗ OPEN</Chip>
            </a>
          ))}
        </div>
      </GoldPanel>
    </div>
  )
}

export default ContractsView
