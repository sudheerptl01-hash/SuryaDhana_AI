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
import { comexCode, comexMonthLabel, countdown, dayLabel, expiryMonthLabel, fmtCount, fmtInr0, fmtK, fmtSignedCount, fmtSignedPctSp, fmtUsd,
         istClock, liveBasisPct, sessionLabel, utcClock, UNIT_LABEL } from '@/lib/gold/format'
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
  // the live COMEX leg is the desk's cached Yahoo last: its freshness block is `fair`'s when the strip carries none
  const liveFresh = fx.comex_live ?? fx.strip ?? fx.fair ?? null
  // a bulletin settlement for the matched month exists only once the CME backfill lands (O-2): until then the cell says
  // so and prints the stored daily close / last trade labelled as what it is — never "NO DATA" beside a live price
  const settle = s?.comex_matched_settle
  const matchedLast = s?.comex_matched_last ?? null
  // MCX: the live quote above the settlement while the session runs (C-TRADER-10); the basis names its clock
  const mcxLive = s?.mcx_live ?? hf?.mcx_live ?? null
  const mcxLiveSource = s?.mcx_live_source ?? hf?.mcx_live_source ?? 'ICICI Breeze'
  // ONE basis per clock, never mixed (wave-1c re-check): the server's strip.basis_pct is the LIVE figure whenever a quote
  // exists (basis_clock 'now'), so the settlement figure must come from basis_settle_pct (or basis_pct only when the
  // server says the clock is 'settlement'); the live figure is shown only while MCX trades (a cached LTP after the close
  // divided by a moving duty-paid landed is the cross-clock ratio the critics rejected)
  const mcxTrading = s?.mcx_shown === 'live' || !!mcxOpen?.is_open
  const basisSettle = s?.basis_settle_pct ?? (s?.basis_clock === 'settlement' || s?.basis_clock == null ? s?.basis_pct ?? null : null)
  const basisLive = mcxTrading ? (s?.basis_live_pct ?? (s?.basis_clock === 'now' ? s?.basis_pct ?? null : liveBasisPct(mcxLive, hf?.duty_paid_landed))) : null
  const settleSession = s?.mcx_settle_session_label ?? sessionLabel(s?.mcx_settle_session)
  const basisSession = s?.basis_session_label ?? (s?.basis_settle_date ? sessionLabel(s.basis_settle_date) : settleSession)
  const tip = `Four instruments on this page: ${instrumentLine(overview, sel)}. Spot proxy = Yahoo XAU; GC1 = continuous front future; ` +
    'matched month = the COMEX contract that expires nearest after the MCX expiry; MCX GOLD = the picked family and expiry.'
  return (
    <div data-gold-strip title={tip}
      style={{ display: 'flex', flexWrap: 'wrap', gap: '6px 18px', alignItems: 'flex-end', padding: '8px 14px', border: `1px solid ${T.border}`,
               background: T.panel, marginBottom: 8 }}>
      <Cell label={`COMEX ${comexCode(c?.comex_matched) !== '—' ? comexMonthLabel(c?.comex_matched) : 'matched'}`}
        value={settle != null
          ? <>{fmtUsd(settle, 1)}<span style={{ color: T.dim, fontSize: 9.5, fontWeight: 400 }}> settle {dayLabel(s?.comex_matched_settle_date) || '—'}</span></>
          : <span data-gold-strip-settle="none"><span style={{ color: T.dim, fontSize: 9.5, fontWeight: 400 }}>settle — </span>
              {matchedLast != null ? <>{fmtUsd(matchedLast, 1)}<span style={{ color: T.dim, fontSize: 9.5, fontWeight: 400 }}> last {dayLabel(s?.comex_matched_last_date) || ''} · {s?.comex_matched_last_source ?? 'Yahoo'}, not settlement</span></>
                : <span style={{ color: T.dim, fontSize: 9.5, fontWeight: 400 }}>(arrives with the CME backfill)</span>}
            </span>}
        sub={<>{live != null ? `last ${fmtUsd(live, 1)}` : 'last —'} {chg != null && <span style={{ color: chg > 0 ? T.green : chg < 0 ? T.red : T.muted }}>{chg > 0 ? '▲' : chg < 0 ? '▼' : ''}{fmtSignedPctSp(chg, 2)}</span>}
          {live != null && <span style={{ color: T.dim }}> {s?.comex_live_source ?? 'Yahoo'}, not settlement{s?.comex_live_as_of ? ` · ${istClock(s.comex_live_as_of)}` : ''}</span>}
          {live != null && <LagChipEl freshness={liveFresh} style={{ marginLeft: 4 }} />}</>}
        title={`${INSTRUMENTS.matched} ${comexCode(c?.comex_matched)}: bulletin settlement when stored (CME backfill, O-2); last = the desk's cached Yahoo last of the matched month, a trade, not a settlement${s?.comex_ref_note ? `; Δ ${s.comex_ref_note}` : ''}`} />
      <Cell label="USD/INR" value={fmtFixed(s?.usdinr, 2)} sub={s?.usdinr_as_of ? `Yahoo INR=X · ${istClock(s.usdinr_as_of)}` : 'Yahoo INR=X · offshore before 09:00'} />
      <Cell label="10-y real" value={s?.real_10y != null ? `${fmtFixed(s.real_10y, 2)} %` : '—'} sub={s?.real_10y_date ? `TIPS · ${dayLabel(s.real_10y_date)}` : 'TIPS (FRED DFII10)'} />
      {mcxLive != null && mcxTrading
        ? <Cell label={`MCX ${c?.mcx ?? sel.family} ${expiryMonthLabel(c?.expiry ?? sel.expiry)}`} value={<>{fmtInr0(mcxLive)}<span style={{ color: T.dim, fontSize: 9.5, fontWeight: 400 }}> live · {mcxLiveSource}</span></>}
            sub={<>settle {fmtInr0(s?.mcx_settle)} {settleSession}{basisLive != null && <> · basis live vs duty-paid now <b style={{ color: T.text }}>{fmtSignedPctSp(basisLive, 2)}</b></>}{basisSettle != null && <> · vs {basisSession.replace(/ settlement$/u, '')} settle <b style={{ color: T.text }}>{fmtSignedPctSp(basisSettle, 2)}</b></>}</>}
            title={`Live = ${mcxLiveSource} quote; settlement = ICICI band midpoint (PROXY) labelled by its session; basis live = live MCX ÷ duty-paid landed now − 1 (same clock); the settlement basis is ${basisSession} ÷ that session's duty-paid − 1`} />
        : <Cell label={`MCX ${c?.mcx ?? sel.family} ${expiryMonthLabel(c?.expiry ?? sel.expiry)}`} value={fmtInr0(s?.mcx_settle)}
            sub={<>{settleSession}{basisSettle != null && <> · basis <b style={{ color: T.text }}>{fmtSignedPctSp(basisSettle, 2)}</b> at the {basisSession} vs that session&apos;s duty-paid</>}</>}
            title="Settlement = ICICI band midpoint (PROXY), labelled by the session it belongs to, never the file date; the basis is settle ÷ duty-paid landed − 1 with both legs at the settlement clock" />}
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
        {row('10-y real', s.real_10y != null ? `${fmtFixed(s.real_10y, 2)} %` : '—', dayLabel(s.real_10y_date))}
        {row(`MCX ${o.contract.mcx} ${expiryMonthLabel(o.contract.expiry)}`, fmtInr0(s.mcx_settle), sessionLabel(s.mcx_settle_session, s.mcx_settle_session_label))}
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
export function Pickers({ sel, onSel, families, unit, onUnit, window, onWindow, layer, onLayer, comexMatched }: {
  sel: GoldContractSel; onSel: (p: Partial<GoldContractSel>) => void; families: ContractFamily[] | null
  unit: Unit; onUnit: (u: Unit) => void; window: Window; onWindow: (w: Window) => void; layer: Layer; onLayer: (l: Layer) => void
  comexMatched: string | null
}) {
  const fam = families?.find(f => f.code === sel.family) ?? null
  const expiries = fam?.expiries ?? []
  const expiryOptions = [{ value: '', label: 'front (by OI)' }, ...expiries.map(e => ({ value: e.expiry, label: `${expiryMonthLabel(e.expiry)} · ${e.expiry}${e.oi != null ? ` · OI ${e.oi.toLocaleString('en-IN')}` : ''}${e.source === 'computed' ? ' · computed' : ''}` }))]
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
