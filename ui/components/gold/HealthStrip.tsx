'use client'

/**
 * The GOLD page header strip (PLAN a.1): the only place live prices appear on the page — the five numbers of
 * CURRICULUM §0 (COMEX matched-month settle + live, USD/INR, 10-y real yield, MCX settlement by session + basis, COT
 * managed-money net) plus the MCX countdown, the gold-api cross-check chip (A12) and the four-instrument labels.
 * Also exports `GoldHoverCard`, the same five numbers as WEI's hover card (PLAN §b), and `Pickers`, the page-global
 * contract × unit × window × [B]/[P] row.
 */
import { useEffect, useState } from 'react'
import { Chip, Select, T, fmtFixed, fmtSigned } from '@/components/terminal'
import { getGoldOverview } from '@/lib/gold/api'
import { bandReferenceLine, basisPurityMismatch, basisPurityShort, basisReferenceLabel, basisSettleLabel, comexCode, comexMonthLabel, countdown, dayLabel, delayedIfOld, expiryMonthLabel, fmtCount, fmtInr0, fmtK, fmtSignedCount,
         fmtSignedPctSp, fmtUsd, istClock, mcxLiveClock, pageRealYield, realYieldPrint, realYieldSeriesWords, sameComexPrint, settlementDay, settlementLine, settlementNote, settlementQualityChip,
         stripBasis, stripSettlement, utcClock, UNIT_LABEL } from '@/lib/gold/format'
import { GOLD_FAMILIES, GOLD_UNITS, INSTRUMENTS, type ContractFamily, type GoldContractSel, type GoldOverview, type Layer, type Unit,
         type Window } from '@/lib/gold/types'
import { Cell, LagChipEl } from './kit'

/** The four instruments, named (PLAN 0.1 #8) — every price on the page says which it is. */
export function instrumentLine(o: GoldOverview | null | undefined, sel: GoldContractSel): string {
  const matched = comexCode(o?.contract.comex_matched)
  const mcx = `${INSTRUMENTS.mcx === 'MCX GOLD' ? `MCX ${sel.family}` : INSTRUMENTS.mcx} ${expiryMonthLabel(o?.contract.expiry ?? sel.expiry)}`
  return `${INSTRUMENTS.spot} · ${INSTRUMENTS.front} · ${INSTRUMENTS.matched} ${matched} · ${mcx}`
}

export function HeaderStrip({ overview, sel, loading, error }: { overview: GoldOverview | null; sel: GoldContractSel; loading: boolean; error: string | null }) {
  const s = overview?.strip
  const c = overview?.contract
  const fx = overview?.freshness ?? {}
  const live = s?.comex_live
  const chg = s?.comex_live_chg_pct
  const mcxOpen = overview?.session?.mcx
  const hf = overview?.health?.fair ?? null
  // the live COMEX leg is the desk's cached Yahoo last: its freshness block is `fair`'s when the strip carries none; a leg
  // minutes behind real-time MCX reads DELAYED with its age, never LIVE (wave 1e minor: ~10 min behind Breeze)
  const liveFresh = delayedIfOld(fx.comex_live ?? fx.strip ?? fx.fair ?? null)
  // a bulletin settlement for the matched month exists only once the CME backfill lands (O-2): until then the cell says
  // so and prints the stored daily close / last trade labelled as what it is — never "NO DATA" beside a live price
  const settle = s?.comex_matched_settle
  const matchedLast = s?.comex_matched_last ?? null
  // MCX: the live quote above the settlement while the session runs (C-TRADER-10); the basis names its clock
  const mcxLive = s?.mcx_live ?? hf?.mcx_live ?? null
  const mcxLiveSource = s?.mcx_live_source ?? hf?.mcx_live_source ?? 'ICICI Breeze'
  // ONE basis per clock, never mixed (wave-1c re-check): the server's strip.basis_pct is the LIVE figure whenever a quote
  // exists (basis_clock 'now'), so the settlement figure must come from basis_settle_pct (or basis_pct only when the
  // server says the clock is 'settlement'); the live figure is shown only while MCX trades. The client never recomputes a
  // basis (wave 1d: the purity of the landed price is the server's `basis_reference`, a client ratio would mix 995 and 999)
  const { live: basisLive, settle: basisSettle, trading: mcxTrading } = stripBasis(s, mcxOpen?.is_open)
  // the live quote's own minute (Breeze's IST bar time; a served time in the future is never printed — wave 1e minor)
  const mcxLiveAt = mcxLiveClock(overview)
  // ONE 10-y real yield per page (wave 1e, M-B): the fresher of the strip's point and the HEALTH gauge's, named by its series
  const ry = pageRealYield(s, overview?.health)
  // wave 1d: the settlement names its source, session and quality ('Wed 04 Nov · last-30-min VWAP (Breeze) — proxy'); the
  // band midpoint is kept for reference with the session it really belongs to; an amber note when the two disagree > 0.6 %
  const st = stripSettlement(s, hf)
  const stLine = settlementLine(st)
  const stNote = settlementNote(st)
  const bandRef = bandReferenceLine(st)
  const basisSettleText = basisSettleLabel(s?.basis_session_label ?? s?.basis_label ?? null, s?.basis_settle_date ?? s?.basis_session ?? null)
  const basisRef = s?.basis_reference ?? hf?.basis_reference ?? null
  const refWords = basisReferenceLabel(basisRef)
  const refShort = basisPurityShort(basisRef)
  // the strip's basis is for the overview's own contract: a landed reference of another purity is flagged, never silently mixed
  const purityOff = basisPurityMismatch(basisRef, c?.mcx ?? sel.family)
  const tip = `Four instruments on this page: ${instrumentLine(overview, sel)}. Spot proxy = Yahoo XAU; GC1 = continuous front future; ` +
    'matched month = the COMEX contract that expires nearest after the MCX expiry; MCX GOLD = the picked family and expiry.'
  // the COMEX cell: a bulletin settle when stored, else ONE last-trade number (the matched month's daily bar and the live
  // last are the same quantity when they agree — printed once, REREVIEW N7); never a leading 'settle —'
  const comexOnce = settle == null && sameComexPrint(matchedLast, live)
  const comexHead = settle ?? live ?? matchedLast
  const dim = { color: T.dim, fontSize: 9.5, fontWeight: 400 } as const
  return (
    <div data-gold-strip title={tip}
      style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 18px', alignItems: 'flex-end', padding: '8px 14px', border: `1px solid ${T.border}`,
               background: T.panel, marginBottom: 8 }}>
      <Cell label={`COMEX ${comexCode(c?.comex_matched) !== '—' ? comexMonthLabel(c?.comex_matched) : 'matched'}`}
        value={settle != null
          ? <>{fmtUsd(settle, 1)}<span style={dim}> settle {dayLabel(s?.comex_matched_settle_date) || '—'}</span></>
          : <span data-gold-strip-settle="none">{comexHead != null
              ? <>{fmtUsd(comexHead, 1)}<span style={dim}> last trade{live == null && s?.comex_matched_last_date ? ` ${dayLabel(s.comex_matched_last_date)}` : ''} · {s?.comex_matched_last_source ?? s?.comex_live_source ?? 'Yahoo'}, not settlement</span></>
              : <span style={dim}>no last trade stored (arrives with the CME backfill)</span>}
            </span>}
        sub={<>{settle != null && <>{live != null ? `last ${fmtUsd(live, 1)}` : 'last —'} </>}
          {chg != null && <span style={{ color: chg > 0 ? T.green : chg < 0 ? T.red : T.muted }}>{chg > 0 ? '▲' : chg < 0 ? '▼' : ''}{fmtSignedPctSp(chg, 2)}</span>}
          {/* the change's reference, named where it prints (DAILY's chart change is vs the previous COMEX close: another reference) */}
          {chg != null && <span style={{ color: T.dim }} data-gold-strip-chg-ref> {s?.comex_ref_note ?? 'vs the 30-min reference before the last MCX close'}</span>}
          {live != null && <span style={{ color: T.dim }}>{settle != null ? ` ${s?.comex_live_source ?? 'Yahoo'}, not settlement` : ''}{s?.comex_live_as_of ? ` · ${istClock(s.comex_live_as_of)}` : ''}</span>}
          {settle == null && !comexOnce && live != null && matchedLast != null && <span style={{ color: T.dim }} data-gold-strip-dailybar> · daily bar {fmtUsd(matchedLast, 1)} {dayLabel(s?.comex_matched_last_date)}</span>}
          {settle == null && <span style={{ color: T.dim }}> · settle: CME bulletin (O-2)</span>}
          {live != null && <LagChipEl freshness={liveFresh} style={{ marginLeft: 4 }} />}</>}
        title={`${INSTRUMENTS.matched} ${comexCode(c?.comex_matched)}: bulletin settlement when stored (CME backfill, O-2); last = the desk's cached Yahoo last of the matched month, a trade, not a settlement${s?.comex_ref_note ? `; Δ ${s.comex_ref_note}` : ''}`} />
      <Cell label="USD/INR" value={fmtFixed(s?.usdinr, 2)} sub={s?.usdinr_as_of ? `Yahoo INR=X · ${istClock(s.usdinr_as_of)}` : 'Yahoo INR=X · last print (no overnight feed)'} />
      <Cell label="10-y real" value={<span data-gold-strip-ry={realYieldPrint(ry.value, ry.date)}>{ry.value != null ? `${fmtFixed(ry.value, 2)} %` : '—'}</span>}
        sub={`${realYieldSeriesWords(ry.seriesId)}${ry.date ? ` · ${dayLabel(ry.date)}` : ''}`}
        title={`10-y real yield, one value per page: the fresher of the Treasury real curve (UST_REAL_10Y) and FRED DFII10 (the same quantity; the later date wins) — HEALTH's REAL YIELD tile, the H2 clause and MACRO print the same point${ry.note ? `; ${ry.note}` : ''}`} />
      {mcxLive != null && mcxTrading
        ? <Cell label={`MCX ${c?.mcx ?? sel.family} ${expiryMonthLabel(c?.expiry ?? sel.expiry)}`} value={<>{fmtInr0(mcxLive)}<span style={dim} data-gold-strip-mcx-clock={mcxLiveAt}> live{mcxLiveAt ? ` · ${mcxLiveAt}` : ''} · {mcxLiveSource}</span></>}
            sub={<span data-gold-strip-mcx>settle {fmtInr0(st.settlement)} <span data-gold-strip-settle-source>{stLine}</span>
              {basisLive != null && <> · basis live vs duty-paid now <b style={{ color: T.text }}>{fmtSignedPctSp(basisLive, 2)}</b></>}
              {/* the settlement basis is dated by ITS OWN session (a stored-row fallback can be an older one), then the strip's settlement */}
              {basisSettle != null && <> · at the {dayLabel(s?.basis_settle_date ?? s?.basis_session) || settlementDay(st)} settle <b style={{ color: T.text }}>{fmtSignedPctSp(basisSettle, 2)}</b></>}
              {(basisLive != null || basisSettle != null) && <span style={{ color: purityOff ? T.amber : T.dim }} data-gold-basis-ref title={refWords}> · {refShort}{purityOff ? ` (not ${c?.mcx ?? sel.family}'s purity)` : ''}</span>}
              {stNote && <span data-gold-settle-note={stNote.tone} style={{ display: 'block', color: stNote.tone === 'amber' ? T.amber : T.muted, whiteSpace: 'normal', maxWidth: 640 }}>⚠ {stNote.text}</span>}</span>}
            title={`Live = ${mcxLiveSource} quote; settlement = ${stLine} (${settlementQualityChip(st.settlement_quality, st.settlement_source)})${bandRef ? `; ${bandRef}` : ''}; basis live = live MCX ÷ duty-paid landed now − 1 (same clock); the settlement basis is ${basisSettleText}; ${refWords}`} />
        : <Cell label={`MCX ${c?.mcx ?? sel.family} ${expiryMonthLabel(c?.expiry ?? sel.expiry)}`} value={fmtInr0(st.settlement)}
            sub={<span data-gold-strip-mcx><span data-gold-strip-settle-source>{stLine}</span>{basisSettle != null && <> · basis <b style={{ color: T.text }}>{fmtSignedPctSp(basisSettle, 2)}</b> {basisSettleText}</>}
              {basisSettle != null && <span style={{ color: purityOff ? T.amber : T.dim }} data-gold-basis-ref title={refWords}> · {refShort}{purityOff ? ` (not ${c?.mcx ?? sel.family}'s purity)` : ''}</span>}
              {stNote && <span data-gold-settle-note={stNote.tone} style={{ display: 'block', color: stNote.tone === 'amber' ? T.amber : T.muted, whiteSpace: 'normal', maxWidth: 640 }}>⚠ {stNote.text}</span>}</span>}
            title={`Settlement = ${stLine} (${settlementQualityChip(st.settlement_quality, st.settlement_source)}), labelled by the session it belongs to, never the file date${bandRef ? `; ${bandRef}` : ''}; the basis is settle ÷ duty-paid landed − 1 with both legs at the settlement clock; ${refWords}`} />}
      <Cell label="COT funds net (managed money)" value={s?.cot_mm_net != null ? fmtSignedCount(s.cot_mm_net) : '—'}
        sub={s?.cot_mm_net != null ? `${fmtSignedCount(s.cot_mm_chg)} w/w · as of ${dayLabel(s.cot_as_of) || '—'}` : 'CFTC weekly, Tuesday positions'}
        title="Managed-money (funds) net futures, CFTC disaggregated report: describes the week, does not forecast (G-STUDY). Contracts: Western grouping." />
      <span style={{ flex: 1 }} />
      <div style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
        {s?.crosscheck?.price != null && (
          <Chip color={T.muted} title="gold-api.com real-time XAU, a keyless cross-check of the Yahoo last (≤ 1 call/min)">gold-api {fmtUsd(s.crosscheck.price, 1)} {utcClock(s.crosscheck.at)}</Chip>
        )}
        {mcxOpen && (
          <Chip color={mcxOpen.is_open ? T.green : T.amber} title={mcxOpen.holiday ? `MCX holiday: ${mcxOpen.holiday.name} (${mcxOpen.holiday.closure})` : 'MCX session clock (shared/mcx_specs)'}>
            ◷ MCX {mcxOpen.is_open ? `open · closes in ${countdown(mcxOpen.seconds_to_close)}` : mcxOpen.holiday ? `closed · ${mcxOpen.holiday.name}` : `opens in ${countdown(mcxOpen.seconds_to_open)}`}
          </Chip>
        )}
        {loading && !overview && <span className="t-pulse" style={{ fontSize: 10, color: T.amber }}>LOADING</span>}
        {error && !overview && <span style={{ fontSize: 10, color: T.amber }}>strip unavailable: {error}</span>}
      </div>
      <div style={{ flexBasis: '100%', fontSize: 9.5, color: T.dim, fontFamily: T.mono, letterSpacing: .4 }} data-gold-instruments>
        {instrumentLine(overview, sel)}
      </div>
    </div>
  )
}

/** WEI's hover card: the five numbers, fetched once when the card opens (60 s cache in ui-api; no Breeze on the path). */
export function GoldHoverCard() {
  const [o, setO] = useState<GoldOverview | null | undefined>(undefined)
  useEffect(() => {
    let alive = true
    getGoldOverview().then(r => { if (alive) setO(r.data) }).catch(() => { if (alive) setO(null) })
    return () => { alive = false }
  }, [])
  const s = o?.strip
  const row = (k: string, v: string, sub?: string) => (
    <div key={k} style={{ display: 'flex', justifyContent: 'space-between', gap: 10, padding: '2px 0', borderBottom: `1px dashed ${T.border}` }}>
      <span style={{ color: T.muted, fontSize: 10 }}>{k}</span><span style={{ color: T.text }}>{v}{sub && <span style={{ color: T.dim, fontSize: 9.5 }}> {sub}</span>}</span>
    </div>
  )
  return (
    <div style={{ fontFamily: T.mono, fontSize: 11, minWidth: 300 }}>
      <div style={{ color: T.amber, fontWeight: 700, marginBottom: 4 }}>GOLD · the five numbers</div>
      {o === undefined && <div style={{ color: T.dim }}>loading…</div>}
      {o === null && <div style={{ color: T.dim }}>gold overview unavailable</div>}
      {o && s && <>
        {row(`COMEX ${comexMonthLabel(o.contract.comex_matched)}`, s.comex_matched_settle != null ? fmtUsd(s.comex_matched_settle, 1) : `last ${fmtUsd(s.comex_matched_last ?? s.comex_live, 1)}`,
          s.comex_matched_settle != null ? `settle ${dayLabel(s.comex_matched_settle_date)} · last ${fmtUsd(s.comex_live, 1)}`
            : `settle — (CME backfill) · ${s.comex_matched_last != null ? `${dayLabel(s.comex_matched_last_date)} ` : ''}Yahoo, not settlement`)}
        {row('USD/INR', fmtFixed(s.usdinr, 2))}
        {(() => { const r = pageRealYield(s, o.health); return row('10-y real', r.value != null ? `${fmtFixed(r.value, 2)} %` : '—', dayLabel(r.date)) })()}
        {row(`MCX ${o.contract.mcx} ${expiryMonthLabel(o.contract.expiry)}`, fmtInr0(stripSettlement(s, o.health?.fair).settlement), settlementLine(stripSettlement(s, o.health?.fair)))}
        {row('COT funds net (MM)', s.cot_mm_net != null ? fmtSignedCount(s.cot_mm_net) : '—', `${fmtK(s.cot_mm_chg)} w/w · ${dayLabel(s.cot_as_of)}`)}
        <div style={{ color: T.dim, fontSize: 9.5, marginTop: 4 }}>{instrumentLine(o, { exchange: 'MCX', family: (o.contract.mcx as GoldContractSel['family']) ?? 'GOLD', expiry: o.contract.expiry, options: false })}</div>
      </>}
    </div>
  )
}

const EXCHANGES: { value: 'MCX' | 'NSE' | 'BSE'; label: string; disabled?: boolean; reason?: string }[] = [
  { value: 'MCX', label: 'MCX' },
  { value: 'NSE', label: 'NSE (n/a)', disabled: true, reason: 'NSE gold futures: no liquid contract and no free data feed (SOURCES D10)' },
  { value: 'BSE', label: 'BSE (n/a)', disabled: true, reason: 'BSE gold contracts are illiquid (SOURCES D10)' },
]

/** The page-global pickers (a.1): exchange × family × expiry · unit · window · [B]/[P]. */
export function Pickers({ sel, onSel, families, unit, onUnit, window, onWindow, layer, onLayer, comexMatched, autoExpiry }: {
  sel: GoldContractSel; onSel: (p: Partial<GoldContractSel>) => void; families: ContractFamily[] | null
  unit: Unit; onUnit: (u: Unit) => void; window: Window; onWindow: (w: Window) => void; layer: Layer; onLayer: (l: Layer) => void
  comexMatched: string | null
  /** the page's default when no expiry is picked (wave 1e): the next month when the OI front is in tender, with the reason */
  autoExpiry?: { expiry: string | null; front: string | null; reason: string | null } | null
}) {
  const fam = families?.find(f => f.code === sel.family) ?? null
  const expiries = fam?.expiries ?? []
  // 'auto' = the OI front, or the next month when the front is in its tender period (wave 1e); an in-tender month says so
  const autoLabel = autoExpiry?.expiry ? `auto: ${expiryMonthLabel(autoExpiry.expiry)} (front ${expiryMonthLabel(autoExpiry.front)} in tender)` : 'front (by OI)'
  const expiryOptions = [{ value: '', label: autoLabel }, ...expiries.map(e => ({ value: e.expiry, label: `${expiryMonthLabel(e.expiry)} · ${e.expiry}${e.oi != null ? ` · OI ${e.oi.toLocaleString('en-IN')}` : ''}${e.source === 'computed' ? ' · computed' : ''}${e.in_tender ? ' · IN TENDER' : ''}` }))]
  const exch = EXCHANGES.find(e => e.value === sel.exchange) ?? EXCHANGES[0]
  return (
    <div data-gold-pickers style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 10px', alignItems: 'center', padding: '6px 10px', border: `1px solid ${T.border}`,
                                    background: '#07090d', marginBottom: 8, fontSize: 10.5 }}>
      <span style={{ fontFamily: T.mono, fontSize: 9.5, letterSpacing: 1.2, color: T.muted }}>CONTRACT</span>
      <span title={exch.reason}>
        <Select value={sel.exchange} onChange={v => { const e = EXCHANGES.find(x => x.value === v); if (e && !e.disabled) onSel({ exchange: v }) }}
          options={EXCHANGES.map(e => ({ value: e.value, label: e.label }))} />
      </span>
      <Select value={sel.family} onChange={v => onSel({ family: v, expiry: null })}
        options={GOLD_FAMILIES.map(f => ({ value: f, label: f }))} />
      <Select value={sel.expiry ?? ''} onChange={v => onSel({ expiry: v || null })} options={expiryOptions} />
      {!sel.expiry && autoExpiry?.reason && <span data-gold-auto-expiry={autoExpiry.expiry ?? ''} style={{ color: T.amber, fontSize: 10 }} title={autoExpiry.reason}>⚠ {autoExpiry.reason}</span>}
      <Chip color={sel.options ? T.violet : T.muted} active={sel.options} onClick={() => onSel({ options: !sel.options })}
        title="Show the options chain (CE/PE) on the selector card; an exercised option becomes the future">OPTIONS</Chip>
      <span style={{ color: T.dim, fontFamily: T.mono, fontSize: 10 }} title="the COMEX contract that expires nearest after the MCX expiry (gold_cme_calendar FND/LTD)">
        ↔ COMEX {comexMatched ? comexMonthLabel(comexMatched) : '—'} ↔ GC1
      </span>
      <span style={{ flex: 1 }} />
      <span style={{ fontFamily: T.mono, fontSize: 9.5, letterSpacing: 1.2, color: T.muted }}>UNIT</span>
      <Select value={unit} onChange={onUnit} options={GOLD_UNITS.map(u => ({ value: u, label: UNIT_LABEL[u] }))} />
      <span style={{ fontFamily: T.mono, fontSize: 9.5, letterSpacing: 1.2, color: T.muted }}>WINDOW</span>
      {(['D', 'W', 'M'] as Window[]).map(w => <Chip key={w} color={T.amber} active={window === w} onClick={() => onWindow(w)} title={w === 'D' ? 'day' : w === 'W' ? 'week' : 'month'}>{w}</Chip>)}
      <span style={{ fontFamily: T.mono, fontSize: 9.5, letterSpacing: 1.2, color: T.muted, marginLeft: 6 }}>LAYER</span>
      <Chip color={T.cyan} active={layer === 'B'} onClick={() => onLayer('B')} title="Beginner: the plain line under each panel">[B]</Chip>
      <Chip color={T.violet} active={layer === 'P'} onClick={() => onLayer('P')} title="Pro: the exact definition, lag and formula under each panel">[P]</Chip>
    </div>
  )
}
