'use client'

/**
 * Derivatives desk (DERV) — NSE F&O analytics from the terminal's own archives (W2, worldclass program).
 * Futures term structure + annualized basis (latest F&O bhavcopy), near-month basis history (2019→),
 * rollover tracker vs the 3-expiry average (UDiFF era, Jul-2024→), PCR & max-pain history
 * (near-expiry for NIFTY/BANKNIFTY; all-expiry aggregate for every underlying), INDIA VIX vs realized.
 * Data: /api/derivatives/* ← data-service fo_analytics.py + the existing option-chain machinery.
 *
 * Terminal v2 (reports/terminal_v2/PLAN.md 0.6 / 1.1, GO alias VOL): two sub-views in `?sub=` — DESK (this page as it
 * was) and VOL (components/vol/VolView: skew, term, cone, IV paid vs delivered, the VOL screener). Honesty fixes: the
 * India VIX tile and panel use the neutral accent (a level is context, never a buy / sell colour); PCR is printed in
 * the neutral token (≥ 1 used to be green); every panel header carries its source chip and evidence badge.
 *
 * Fix wave 2 (V-VOL, review 5 Nov 2026): the page reads and writes the shared active symbol (OMON → DERV keeps BANKNIFTY);
 * one India VIX (NSE's vix_daily close, as the strip — m001) dated, never a midnight clock (m064); the roll a long pays is
 * the CALENDAR SPREAD next − near, beside the next series' basis vs spot (m065); the past expiries' final rollover in the
 * neutral token, the pace comparison named (m066); the basis chart from DTE ≥ 3 (m067); "Volume (contracts)" (m068); the
 * realised vol named close-to-close, the IV store's RV20 cc (m069).
 *
 * Round 2: an external active symbol is adopted only when it is an F&O underlying (volModel.fnoVerdict on
 * /api/derivatives/symbols: a DEAL pick of a cash-only name used to open DERV on an error instead of NIFTY; a stock waits
 * for the list, the indices never do); the PCR panel's walls read "OI walls · call / put" in the neutral token (m003).
 */
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import { CHART_BOX, Chip, DataTable, ErrorBox, Input, Loading, Notice, PageHeader, Panel, SourceChip, Stat, T, Tabs, type Column, MINUS, fmtFixed, fmtNum, fmtPct, fmtSigned, ordinal, sourceOf, tone, useChartSize, useSubView } from '@/components/terminal'
import { useLiveQuotes } from '@/lib/liveQuotes'
import { underlyingLiveSymbol } from '@/components/liveModel'
import { VolView } from '@/components/vol/VolView'
import { FlowRadar } from '@/components/vol/FlowRadar'   // FINAL ROUND E-RADAR: the RADAR sub-view (this import + the tab item + its branch below are E-RADAR's one registration)
import { ExpiryDay } from '@/components/expiry/ExpiryDay'
import { basisForChart, fnoVerdict } from '@/components/vol/volModel'
import { useActiveSymbol } from '@/lib/activeSymbol'
import { countUnit, fmtCount } from '@/lib/format'
import { Crosshair, axisTicks, useChartInteraction } from '@/components/terminal/chart'
import { ExpandableChart } from '@/components/terminal/ExpandableChart'
import { InteractiveSeries } from '@/components/terminal/InteractiveSeries'
import { useInteractionRef, useShellWiring } from '@/components/vol/charts'

const num = fmtNum
const pct = fmtPct

// ── payload types (shaped by services/data-service/fo_analytics.py) ──────────────────────
type Leg = { rank: number; label: string; expiry: string; dte: number; close: number | null; settle: number | null
             basis_pct: number | null; basis_ann_pct: number | null; oi: number | null; oi_chg: number | null; volume: number | null }
type TermStructure = { symbol: string; as_of: string; spot: number | null; legs: Leg[]; fut_oi_total: number; source: string; lot?: number | null }
type BasisRow = { date: string; spot: number; fut: number; dte: number; basis_pct: number | null; basis_ann_pct: number | null }
type RollRow = { date: string; near_expiry: string; dte: number; roll_pct: number | null
                 near_oi: number; next_oi: number; far_oi: number; carry_next_ann_pct: number | null
                 roll_spread_pts?: number | null; roll_spread_pct?: number | null; roll_spread_ann_pct?: number | null; roll_days?: number | null }
type Rollover = { symbol: string; updating: boolean; built_through: string | null; error: string | null; note: string
                  current: RollRow | null; curve_now: RollRow[]; curve_avg: { dte: number; roll_pct: number }[]
                  history: { expiry: string; date: string; roll_pct: number; carry_next_ann_pct: number | null }[]; avg3: number | null }
type PcrRow = { date: string; call_oi: number | null; put_oi: number | null; pcr: number | null; fut_oi: number | null }
type OptHistRow = { date: string; spot: number; atm_iv: number | null; pcr: number | null; max_pain: number | null; expiry: string }
type Vix = { as_of: string; level: number; chg_1d: number | null; pctile_1y: number | null; pctile_5y: number | null; source?: string; rv20_estimator?: string
             rv20: number | null; spread: number | null; rows: { date: string; vix: number; nifty: number | null; rv20: number | null }[] }
type MaxPain = { symbol: string; date: string; expiry: string; days_to_expiry: number; spot: number | null; atm_iv: number | null
                 pcr_oi: number | null; max_pain: number | null; expected_move_pct: number | null; resistance: number[]; support: number[] }

const INDICES = ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50']
const CHAIN_HISTORY = new Set(['NIFTY', 'BANKNIFTY'])    // option_history.json covers these two

async function j<X>(path: string): Promise<X> {
  const r = await window.fetch(path)
  if (!r.ok) {
    let d = ''
    try { d = (await r.json()).detail } catch { /* non-JSON body */ }
    throw new Error(typeof d === 'string' && d ? d : `HTTP ${r.status}`)
  }
  return r.json()
}

/** Open interest in shares → Indian units (cr / L), for a value on its own (a table column uses one unit: countUnit). */
function oiFmt(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const sign = v < 0 ? MINUS : ''
  if (Math.abs(v) >= 1e7) return `${sign}${(Math.abs(v) / 1e7).toFixed(2)} cr`
  if (Math.abs(v) >= 1e5) return `${sign}${(Math.abs(v) / 1e5).toFixed(1)} L`
  return num(v)
}

// ── charts (FINAL ROUND W3, chart plan B8/B9): the four time-series are lightweight-charts through the kit's
// InteractiveSeries (wheel zoom / drag pan / crosshair are LWC's own; FIT + PNG + ⛶ from the ExpandableChart shell);
// the rollover curve keeps SVG (its x-axis is DTE, not time) and gains the SVG kit v2 interaction below. ──────────

/**
 * Rollover % vs days-to-expiry: this cycle against the average of the prior ones. SVG kit v2 (charts/PLAN.md §4):
 * wheel + pinch zoom and drag pan over the DTE axis, double-click reset, and a nearest-point crosshair that prints
 * T−DTE with this cycle's rollover % beside the prior-cycle average in the panel legend (never tooltip-only).
 */
function RollCurve({ now, avg, lUnit = '%' }: { now: RollRow[]; avg: { dte: number; roll_pct: number }[]; lUnit?: string }) {
  const { ref, w: W, h: H } = useChartSize(1000, 230, { maxRatio: 1.25 })   // CSS px (C1-17)
  const { box, setRef } = useInteractionRef(ref)
  const clipId = useId().replace(/[^a-zA-Z0-9_-]/g, '')
  const padL = 48, padR = 16, top = 10, chartH = H - 46
  const plotW = W - padL - padR
  const maxDte = Math.max(25, ...now.map(r => r.dte), ...avg.map(a => a.dte))
  // the interaction domain rises to the right (u = maxDte − dte), so the expiry (T−0) stays at the right edge
  const nowPts = useMemo(() => [...now].filter(r => r.roll_pct != null).sort((a, b) => b.dte - a.dte), [now])
  const ia = useChartInteraction(box, { min: 0, max: maxDte }, { points: nowPts.map(r => maxDte - r.dte) })
  ia.setPlot(padL, plotW)
  const view = ia.view
  const x = (dte: number) => padL + ((maxDte - dte - view.min) / (view.max - view.min || 1)) * plotW
  // R11-style y-axis: round ticks over the padded range, one per ~30 px, the % unit on every label
  const allVals = [...now.map(r => r.roll_pct), ...avg.map(a => a.roll_pct)].filter((v): v is number => v != null && Number.isFinite(v))
  let lLo = 0, lHi = Math.max(100, ...allVals)
  const lPad = (lHi - lLo || 1) * 0.05; lLo -= lPad; lHi += lPad
  const lAxis = axisTicks(lLo, lHi, chartH)
  const y = (v: number) => top + (1 - (v - lLo) / (lHi - lLo || 1)) * chartH
  const line = (pts: { dte: number; v: number | null }[]) => pts
    .sort((a, b) => b.dte - a.dte)
    .map((p, i, a) => (p.v == null ? '' : `${i === 0 || a[i - 1].v == null ? 'M' : 'L'}${x(p.dte).toFixed(1)},${y(p.v).toFixed(1)}`)).join('')
  // T−d labels at round DTEs inside the visible window
  const dteLo = Math.max(0, maxDte - view.max), dteHi = maxDte - view.min
  const dteTicks = axisTicks(dteLo, dteHi, Math.max(60, plotW / 2.2)).ticks.filter(d => d >= 0 && Number.isInteger(d))
  const cr = ia.cursor != null ? nowPts[ia.cursor.i] ?? null : null
  const crVisible = cr != null && maxDte - cr.dte >= view.min - 0.5 && maxDte - cr.dte <= view.max + 0.5
  const avgAt = cr ? avg.find(a => a.dte === cr.dte)?.roll_pct ?? null : null
  const readout = !crVisible || cr == null ? null : (
    <span>
      <span style={{ color: T.dim }}>T−{cr.dte}</span> · this cycle <b style={{ color: T.amber, fontWeight: 400 }}>{num(cr.roll_pct, 1)}%</b>
      <span> · prior cycles {avgAt != null ? `${num(avgAt, 1)}%` : '—'}</span>
    </span>
  )
  const hasShell = useShellWiring(readout, ia.reset)
  return (
    <div ref={setRef} style={{ ...CHART_BOX, position: 'relative', touchAction: 'none', cursor: 'crosshair' }}>
    {!hasShell && readout && (
      <div style={{ position: 'absolute', top: 2, right: 8, fontFamily: T.mono, fontSize: 10, color: T.muted,
                    background: 'rgba(10,13,19,0.88)', border: `1px solid ${T.border}`, padding: '1px 6px',
                    pointerEvents: 'none', zIndex: 2 }}>{readout}</div>
    )}
    <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} style={{ display: 'block' }} role="img" aria-label="rollover curve">
      <defs><clipPath id={clipId}><rect x={padL} y={0} width={Math.max(plotW, 0)} height={H} /></clipPath></defs>
      {lAxis.ticks.map(v => (
        <g key={v}>
          <line x1={padL} x2={W - padR} y1={y(v)} y2={y(v)} stroke={T.border} strokeDasharray="2 4" />
          <text x={padL - 6} y={y(v) + 3} fill={T.dim} fontSize={10} fontFamily={T.mono} textAnchor="end">{fmtFixed(v, lAxis.dp)}{lUnit}</text>
        </g>
      ))}
      {dteTicks.map(d => (
        <text key={d} x={x(d)} y={H - 6} fill={T.dim} fontSize={10} fontFamily={T.mono} textAnchor="middle">T−{d}</text>
      ))}
      <g clipPath={`url(#${clipId})`}>
        <path d={line(avg.map(a => ({ dte: a.dte, v: a.roll_pct })))} fill="none" stroke={T.muted} strokeWidth={1.4} strokeDasharray="5 4" />
        <path d={line(now.map(r => ({ dte: r.dte, v: r.roll_pct })))} fill="none" stroke={T.amber} strokeWidth={2} />
        {now.length > 0 && now[now.length - 1].roll_pct != null && (
          <circle cx={x(now[now.length - 1].dte)} cy={y(now[now.length - 1].roll_pct!)} r={3.5} fill={T.amber} />
        )}
        {crVisible && cr != null && cr.roll_pct != null && (
          <Crosshair x={x(cr.dte)} y={y(cr.roll_pct)} top={top} height={chartH} left={padL} width={plotW} />
        )}
      </g>
    </svg>
    </div>
  )
}

// ── sections ─────────────────────────────────────────────────────────────────────────────

function TermPanel({ term, basis, basisNote }: { term: TermStructure; basis: BasisRow[]; basisNote: string | null }) {
  // CT-11: one unit per column (it was picked per cell: 1.13 cr above 85.5 L), shown in the header
  const oiU = countUnit(term.legs.map(r => r.oi)), chgU = countUnit(term.legs.map(r => r.oi_chg))
  const cols: Column<Leg>[] = [
    { key: 'label', label: 'Series', render: r => <span style={{ color: r.rank === 0 ? T.amber : T.text, fontWeight: r.rank === 0 ? 700 : 400 }}>{r.label.toUpperCase()}</span> },
    { key: 'expiry', label: 'Expiry', render: r => <span style={{ fontFamily: T.mono }}>{r.expiry}</span> },
    { key: 'dte', label: 'DTE', align: 'right', render: r => num(r.dte) },
    { key: 'close', label: 'Close', align: 'right', render: r => num(r.close, 2) },
    { key: 'basis_pct', label: 'Basis', align: 'right', render: r => <span style={{ color: tone(r.basis_pct) }}>{pct(r.basis_pct, 3)}</span> },
    { key: 'basis_ann_pct', label: 'Ann %', align: 'right', render: r => <span style={{ color: tone(r.basis_ann_pct), fontWeight: 600 }}>{pct(r.basis_ann_pct, 2)}</span> },
    { key: 'oi', label: `OI (shares${oiU.suffix ? ` ·${oiU.suffix}` : ''})`, align: 'right', render: r => <span style={{ color: T.cyan }}>{fmtCount(r.oi, oiU)}</span> },
    { key: 'oi_chg', label: `OI chg${chgU.suffix ? ` ·${chgU.suffix}` : ''}`, align: 'right', render: r => <span style={{ color: tone(r.oi_chg) }}>{fmtCount(r.oi_chg, chgU, true)}</span> },
    { key: 'volume', label: 'Volume (contracts)', align: 'right', render: r => <span style={{ color: T.muted }} title="contracts traded on the session (not open contracts)">{num(r.volume)}</span> },
  ]
  const shape = term.legs.length >= 2 && term.legs[0].basis_ann_pct != null && term.legs[term.legs.length - 1].basis_ann_pct != null
    ? (term.legs[term.legs.length - 1].basis_ann_pct! >= term.legs[0].basis_ann_pct! ? 'upward carry curve' : 'inverted carry curve')
    : null
  return (
    <Panel title={`Futures term structure — ${term.symbol}`} accent={T.amber} pad={0}
      source={sourceOf(term.as_of, { source: 'NSE F&O bhavcopy' })} badge="arithmetic"
      subtitle={`EOD ${term.as_of}${shape ? ` · ${shape}` : ''}`}>
      <DataTable columns={cols} rows={term.legs} rowKey={r => r.expiry} dense empty="No futures" />
      <div style={{ padding: 12, borderTop: `1px solid ${T.border}` }}>
        {basis.length > 0 ? (
          <>
            <ExpandableChart title="Near-month annualized basis %" height={210}
              legend={<span style={{ color: T.dim }}>amber = annualized basis · {basis[0].date} → {basis[basis.length - 1].date}</span>}>
              <InteractiveSeries height={210} ariaLabel="annualized basis history"
                series={[{ id: 'basis', label: 'basis ann', color: T.amber, w: 2, format: v => `${fmtFixed(v, 1)}%`,
                           points: basisForChart(basis, 3).map((v, i) => ({ t: basis[i].date, v })) }]} />
            </ExpandableChart>
            <div style={{ fontSize: 10, color: T.dim, marginTop: 6 }}>
              above 0 = contango (longs pay carry) · sessions ≥ 3 days to expiry only (annualising the last 1–2 days divides by noise and set the axis)
            </div>
          </>
        ) : basisNote ? <Notice color={T.violet}>{basisNote}</Notice> : <Loading label="Basis history" />}
      </div>
    </Panel>
  )
}

function RolloverPanel({ roll, term }: { roll: Rollover; term: TermStructure }) {
  const c = roll.current
  const histCols: Column<Rollover['history'][number]>[] = [
    { key: 'expiry', label: 'Expiry', render: r => <span style={{ fontFamily: T.mono }}>{r.expiry}</span> },
    { key: 'roll_pct', label: 'Final rollover', align: 'right', render: r => <span style={{ color: T.amber, fontWeight: 600 }}>{num(r.roll_pct, 1)}%</span> },
    { key: 'carry_next_ann_pct', label: 'Carry into next (ann)', align: 'right', render: r => <span style={{ color: tone(r.carry_next_ann_pct) }}>{pct(r.carry_next_ann_pct, 2)}</span> },
  ]
  const avgAtDte = c ? roll.curve_avg.find(a => a.dte === c.dte)?.roll_pct ?? null : null
  const vsAvg = c?.roll_pct != null && avgAtDte != null ? c.roll_pct - avgAtDte : null
  return (
    <Panel title={`Rollover tracker — ${roll.symbol}`} accent={T.cyan}
      source={sourceOf(roll.built_through, { source: 'NSE F&O bhavcopy', hint: roll.error })} badge="context"
      subtitle={`near → next OI migration · panel through ${roll.built_through ?? '—'} · ${roll.note}`}>
      {roll.updating && <Notice color={T.amber}>Building the futures panel from cached F&O bhavcopies (~1 min, incremental afterwards) — this page refreshes itself.</Notice>}
      {roll.error && <Notice color={T.red}>Panel build error: {roll.error}</Notice>}
      {c ? (
        <div style={{ display: 'grid', gap: 12 }}>
          <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
            <Stat label={`Rolled so far (T−${c.dte})`} value={`${num(c.roll_pct, 1)}%`} accent={T.amber}
              color={T.amber} sub={avgAtDte != null ? `prior cycles at T−${c.dte}: ${num(avgAtDte, 1)}%` : 'no prior-cycle baseline yet'} />
            <Stat label="Past 3 expiries · final rollover (avg)" value={roll.avg3 != null ? `${num(roll.avg3, 1)}%` : '—'} accent={T.cyan} color={T.text}
              sub={vsAvg != null && avgAtDte != null ? `pace: this cycle ${num(c.roll_pct, 1)}% vs prior cycles ${num(avgAtDte, 1)}% at T−${c.dte} (${vsAvg >= 0 ? '+' : MINUS}${num(Math.abs(vsAvg), 1)} pts) · context` : 'the final rollover of the last three expiries · pace unknown'} />
            <Stat label="Calendar roll · near → next" value={c.roll_spread_pts != null ? `${fmtSigned(c.roll_spread_pts, 1)} pts` : '—'} accent={T.muted} color={T.text}
              sub={c.roll_spread_pts != null
                ? `${pct(c.roll_spread_pct, 2)} over ${c.roll_days} d ≈ ${pct(c.roll_spread_ann_pct, 2)} ann${term.lot ? ` · ₹${num(Math.abs(c.roll_spread_pts) * term.lot, 0)} per lot` : ''} · what rolling a long pays today (sell near, buy next) · arithmetic`
                : 'needs both series in the panel'} />
            <Stat label="Next series vs spot (ann)" value={pct(c.carry_next_ann_pct, 2)} accent={T.muted} color={T.text}
              sub="the next future's basis over its own days (carry), not the roll cost" />
            {/* CT-11: one unit for the three legs (it read '1.13 cr' over 'next 85.5 L · far 8.5 L') */}
            {(() => { const u = countUnit([c.near_oi, c.next_oi, c.far_oi]); return (
              <Stat label="OI near / next / far" value={fmtCount(c.near_oi, u)} accent={T.violet}
                sub={`next ${fmtCount(c.next_oi, u)} · far ${fmtCount(c.far_oi, u)}`} />) })()}
            <Stat label="Near expiry" value={c.near_expiry.slice(5)} accent={T.amber} sub={`${c.dte} calendar days`} />
          </div>
          <ExpandableChart title="Rollover % by days to expiry" height={230}
            legend={<span><span style={{ color: T.amber }}>amber = this cycle</span> · <span style={{ color: T.dim }}>dashed = average of prior cycles</span></span>}>
            <RollCurve now={roll.curve_now} avg={roll.curve_avg} lUnit="%" />
          </ExpandableChart>
          <DataTable columns={histCols} rows={[...roll.history].reverse()} rowKey={r => r.expiry} dense
            maxHeight={240} empty="No completed expiries in the panel yet" />
        </div>
      ) : !roll.updating ? <Notice>No futures panel rows for {roll.symbol} yet.</Notice> : <Loading label="Futures panel" />}
    </Panel>
  )
}

function PcrPanel({ symbol, pcrRows, optHist, maxPain }: {
  symbol: string; pcrRows: PcrRow[]; optHist: OptHistRow[] | null; maxPain: MaxPain | null
}) {
  return (
    <Panel title={`PCR & max pain — ${symbol}`} accent={T.violet}
      source={sourceOf(maxPain?.date ?? pcrRows[pcrRows.length - 1]?.date ?? null, { source: 'NSE F&O bhavcopy' })} badge="context"
      subtitle="aggregate PCR = put÷call OI across ALL strikes and expiries (2019→) · chain PCR / max pain are near-expiry">
      <div style={{ display: 'grid', gap: 12 }}>
        {maxPain && (
          <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
            <Stat label={`Max pain (${maxPain.expiry.slice(5)})`} value={num(maxPain.max_pain, 0)} accent={T.violet} color={T.violet}
              sub={maxPain.spot != null && maxPain.max_pain != null ? `spot ${num(maxPain.spot, 0)} · ${pct((maxPain.max_pain / maxPain.spot - 1) * 100, 1)} away` : undefined} />
            <Stat label="Chain PCR (near expiry)" value={num(maxPain.pcr_oi, 2)} accent={T.cyan}
              color={T.text} sub={`EOD ${maxPain.date} · ${maxPain.days_to_expiry}d to expiry`} />
            <Stat label="ATM IV" value={maxPain.atm_iv != null ? `${num(maxPain.atm_iv, 1)}%` : '—'} accent={T.amber}
              sub={maxPain.expected_move_pct != null ? `±${num(maxPain.expected_move_pct, 1)}% priced to expiry` : undefined} />
            <Stat label="OI walls · call / put" value={`${num(maxPain.resistance?.[0], 0)} / ${num(maxPain.support?.[0], 0)}`} accent={T.muted} color={T.text}
              sub="the strikes with the most call / put OI (where writers sit) · context, not a level" />
          </div>
        )}
        {optHist && optHist.length > 0 && (
          <ExpandableChart title="Near-expiry max pain vs spot" height={230}
            legend={<span><span style={{ color: T.amber }}>amber = spot</span> · <span style={{ color: T.violet }}>violet = max pain</span> · <span style={{ color: T.cyan }}>cyan = chain PCR (left)</span></span>}>
            <InteractiveSeries height={230} ariaLabel="max pain vs spot history" series={[
              { id: 'spot', label: 'spot', color: T.amber, w: 2, points: optHist.map(r => ({ t: r.date, v: r.spot })), format: v => fmtNum(v, 0) },
              { id: 'maxpain', label: 'max pain', color: T.violet, points: optHist.map(r => ({ t: r.date, v: r.max_pain })), format: v => fmtNum(v, 0) },
              { id: 'pcr', label: 'chain PCR', color: T.cyan, axis: 'L', points: optHist.map(r => ({ t: r.date, v: r.pcr })), format: v => v.toFixed(2) },
            ]} />
          </ExpandableChart>
        )}
        {pcrRows.length > 0 && (
          <ExpandableChart title="Aggregate put/call OI ratio" height={190}
            legend={<span style={{ color: T.dim }}>all strikes and expiries · {pcrRows[0].date} → {pcrRows[pcrRows.length - 1].date}</span>}>
            <InteractiveSeries height={190} ariaLabel="aggregate PCR history"
              series={[{ id: 'pcr', label: 'aggregate PCR', color: T.cyan, points: pcrRows.map(r => ({ t: r.date, v: r.pcr })), format: v => v.toFixed(2) }]} />
          </ExpandableChart>
        )}
      </div>
    </Panel>
  )
}

function VixPanel({ vix }: { vix: Vix }) {
  return (
    <Panel title="INDIA VIX" accent={T.muted}
      source={sourceOf(String(vix.as_of).slice(0, 10), { source: vix.source === 'vix_daily' ? 'NSE daily index file' : 'NSE' })} badge="arithmetic"
      subtitle={`vs NIFTY 20-day realised volatility (close-to-close, √252: the IV store's RV20 cc on DERV › VOL) · as of ${String(vix.as_of).slice(0, 10)}`}>
      <div style={{ display: 'grid', gap: 12 }}>
        <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))' }}>
          <Stat label="VIX change (1 session)" value={fmtSigned(vix.chg_1d, 2)} accent={T.muted}
            color={T.text} sub="the level is in the strip above" />
          <Stat label="5y percentile" value={ordinal(vix.pctile_5y)} accent={T.muted}
            color={T.text} sub="share of the past 5 years' sessions below today (1y in the strip)" />
          <Stat label="NIFTY realised (20d, cc)" value={vix.rv20 != null ? num(vix.rv20, 2) : '—'} accent={T.violet} sub="close-to-close, annualised % (RV20 cc)" />
          <Stat label="VIX − realized" value={fmtSigned(vix.spread, 2)}
            accent={T.muted} color={T.text}
            sub={(vix.spread ?? 0) >= 0 ? 'VIX above the 20d realized · describes, does not predict' : 'VIX below the 20d realized · describes, does not predict'} />
        </div>
        <ExpandableChart title="VIX vs 20d realised" height={210}
          legend={<span><span style={{ color: T.text }}>white = INDIA VIX</span> · <span style={{ color: T.violet }}>violet = NIFTY 20d realised (close-to-close)</span></span>}>
          <InteractiveSeries height={210} ariaLabel="India VIX vs realised volatility" series={[
            { id: 'vix', label: 'VIX', color: T.text, w: 2, points: vix.rows.map(r => ({ t: r.date, v: r.vix })), format: v => fmtFixed(v, 1) },
            { id: 'rv', label: 'realised (cc)', color: T.violet, points: vix.rows.map(r => ({ t: r.date, v: r.rv20 })), format: v => fmtFixed(v, 1) },
          ]} />
        </ExpandableChart>
      </div>
    </Panel>
  )
}

// ── the tab ──────────────────────────────────────────────────────────────────────────────

export function DerivativesDesk({ onSelectTicker }: { onSelectTicker?: (s: string) => void }) {
  // the shared symbol convention (ui/lib/activeSymbol): open on the active underlying, follow another page's / GO's pick,
  // write our own picks (the 5 Nov capture: OMON on BANKNIFTY, DERV › VOL on NIFTY)
  const [active, writeActive] = useActiveSymbol()
  const [symbol, setSymbolState] = useState(() => active?.symbol ?? 'NIFTY')
  const [input, setInput] = useState('')
  const [symbols, setSymbols] = useState<{ symbol: string; kind: string }[]>([])
  // F&O guard (round 2): the F&O list (undefined while it loads, null if unavailable); a user's own pick is never second-guessed
  const [fnoState, setFnoState] = useState<'loading' | 'ok' | 'failed'>('loading')
  const fno = useMemo(() => (fnoState === 'loading' ? undefined : fnoState === 'ok' && symbols.length ? symbols.map(s => s.symbol) : null), [fnoState, symbols])
  const userPicked = useRef(false)
  const setSymbol = useCallback((s: string) => { userPicked.current = true; setSymbolState(s); writeActive({ symbol: s }) }, [writeActive])
  useEffect(() => {
    const s = active?.symbol
    if (s && fnoVerdict(s, fno) === 'adopt') setSymbolState(prev => (prev === s ? prev : s))
  }, [active?.symbol, fno])
  // the opening symbol came from the store: once the list is known, a cash-only name falls back to NIFTY
  useEffect(() => {
    if (fno !== undefined && !userPicked.current) setSymbolState(prev => (fnoVerdict(prev, fno) === 'reject' ? 'NIFTY' : prev))
  }, [fno])
  const symbolReady = userPicked.current || fnoVerdict(symbol, fno) === 'adopt'
  const [term, setTerm] = useState<TermStructure | null>(null)
  const [basis, setBasis] = useState<BasisRow[]>([])
  const [basisNote, setBasisNote] = useState<string | null>(null)
  const [roll, setRoll] = useState<Rollover | null>(null)
  const [pcrRows, setPcrRows] = useState<PcrRow[]>([])
  const [optHist, setOptHist] = useState<OptHistRow[] | null>(null)
  const [maxPain, setMaxPain] = useState<MaxPain | null>(null)
  const [vix, setVix] = useState<Vix | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [sub, setSub] = useSubView(['desk', 'vol', 'xpry', 'radar'] as const, 'desk')
  const seq = useRef(0)

  useEffect(() => {
    j<{ rows: { symbol: string; kind: string }[] }>('/api/derivatives/symbols').then(r => { setSymbols(r.rows); setFnoState('ok') }).catch(() => setFnoState('failed'))
    j<Vix>('/api/derivatives/vix?days=500').then(setVix).catch(() => {})
  }, [])

  const load = useCallback(async (sym: string) => {
    const mine = ++seq.current
    setError(null); setTerm(null); setBasis([]); setBasisNote(null); setRoll(null); setPcrRows([]); setOptHist(null); setMaxPain(null)
    try {
      const t = await j<TermStructure>(`/api/derivatives/term-structure?symbol=${encodeURIComponent(sym)}`)
      if (seq.current !== mine) return
      setTerm(t)
    } catch (e: any) {
      if (seq.current === mine) setError(e?.message || 'Derivatives desk unavailable')
      return
    }
    j<{ rows: BasisRow[] }>(`/api/derivatives/basis-history?symbol=${encodeURIComponent(sym)}&days=1250`)
      .then(r => { if (seq.current === mine) setBasis(r.rows) })
      .catch(e => { if (seq.current === mine) setBasisNote(e?.message || 'No basis history') })
    j<{ rows: PcrRow[] }>(`/api/derivatives/pcr-history?symbol=${encodeURIComponent(sym)}&days=1250`)
      .then(r => { if (seq.current === mine) setPcrRows(r.rows) }).catch(() => {})
    j<MaxPain>(`/api/derivatives/max-pain/${encodeURIComponent(sym)}`)
      .then(r => { if (seq.current === mine) setMaxPain(r) }).catch(() => {})
    if (CHAIN_HISTORY.has(sym)) {
      j<{ rows: OptHistRow[] }>(`/api/derivatives/option-history/${encodeURIComponent(sym)}?days=500`)
        .then(r => { if (seq.current === mine) setOptHist(r.rows) }).catch(() => {})
    }
    const pollRoll = async (tries: number) => {
      try {
        const r = await j<Rollover>(`/api/derivatives/rollover?symbol=${encodeURIComponent(sym)}&cycles=8`)
        if (seq.current !== mine) return
        setRoll(r)
        if (r.updating && tries > 0) setTimeout(() => pollRoll(tries - 1), 8000)
      } catch (e: any) {
        if (seq.current === mine) setRoll({ symbol: sym, updating: false, built_through: null, error: e?.message || 'rollover unavailable',
          note: '', current: null, curve_now: [], curve_avg: [], history: [], avg3: null })
      }
    }
    pollRoll(12)
  }, [])

  // a stock from the store waits for the F&O list (no 404 flash for a cash-only name); an index or a user pick loads at once
  useEffect(() => { if (symbolReady) load(symbol) }, [symbol, load, symbolReady])

  const pick = (s: string) => { const v = s.trim().toUpperCase(); if (v) { setSymbol(v); setInput('') } }
  const nearLeg = term?.legs?.[0]
  // live program (reports/live_nse): the underlying's spot from the live NSE quote service (Breeze websocket tick in
  // session; CLOSE <day> after) beside the EOD spot the tables use; every other DERV panel is EOD and says so
  const ulSym = underlyingLiveSymbol(symbol)
  const ul = useLiveQuotes(ulSym ? [ulSym] : [], { intervalMs: 3_000, enabled: sub === 'desk' })
  const ulRow = ulSym ? ul.quotes[ulSym] : undefined
  const ulPriced = !!ulRow && ulRow.price != null && ulRow.state !== 'unavailable'

  // PLAN 1.1 (O-T14 default: a sub-view, not a 44th page): DESK | VOL in `?sub=`; the GO alias VOL hands `vol` over
  const tabs = <Tabs items={[{ id: 'desk', label: 'Desk · basis · rollover · PCR · VIX' }, { id: 'vol', label: 'VOL · skew · term · cone · screener' }, { id: 'xpry', label: 'XPRY · expiry day · OI unwind · decay · scorecard' }, { id: 'radar', label: 'RADAR · rolling OI Δ · vol/OI · IV change' }]}
    active={sub} onChange={setSub} />
  const picker = (
    <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
      {INDICES.map(s => <Chip key={s} color={T.amber} active={symbol === s} onClick={() => setSymbol(s)}>{s}</Chip>)}
      <form onSubmit={e => { e.preventDefault(); pick(input) }} style={{ display: 'flex', gap: 6 }}>
        <Input value={input} onChange={setInput} placeholder="any F&O stock… (RELIANCE)" width={200} aria-label="F&O symbol" />
        <datalist id="derv-symbols">{symbols.map(s => <option key={s.symbol} value={s.symbol} />)}</datalist>
        <Chip color={T.cyan} onClick={() => pick(input)}>GO</Chip>
      </form>
      {symbol && !INDICES.includes(symbol) && onSelectTicker && (
        <Chip color={T.muted} onClick={() => onSelectTicker(symbol)} title="open the stock window">{symbol} PROFILE ↗</Chip>
      )}
    </div>
  )

  if (sub === 'xpry') {
    return (
      <div>
        <PageHeader code="DERV" title="Derivatives desk" subtitle={`XPRY · ${symbol} · the expiry day from the stored intraday tape + the implied-vs-realised record`} />
        <div style={{ display: 'grid', gap: 12 }}>
          {tabs}
          {picker}
          {symbolReady ? <ExpiryDay symbol={symbol} /> : <Loading label="Reading the F&O list" />}
        </div>
      </div>
    )
  }

  if (sub === 'radar') {
    return (
      <div>
        <PageHeader code="DERV" title="Derivatives desk" subtitle={`RADAR · ${symbol} · per-strike flow over a rolling window from the stored 2-minute tape`} />
        <div style={{ display: 'grid', gap: 12 }}>
          {tabs}
          {picker}
          {symbolReady ? <FlowRadar symbol={symbol} /> : <Loading label="Reading the F&O list" />}
        </div>
      </div>
    )
  }

  if (sub === 'vol') {
    return (
      <div>
        <PageHeader code="DERV" title="Derivatives desk" subtitle={`VOL · ${symbol} · implied vs realised volatility from the stored IV tables · end of day`} />
        <div style={{ display: 'grid', gap: 12 }}>
          {tabs}
          {picker}
          {symbolReady ? <VolView symbol={symbol} onPick={s => setSymbol(s)} /> : <Loading label="Reading the F&O list" />}
        </div>
      </div>
    )
  }

  if (error && !term) {
    return <div><PageHeader code="DERV" title="Derivatives desk" />{tabs}<ErrorBox error={error} onRetry={() => load(symbol)} /></div>
  }
  if (!term) return <div><PageHeader code="DERV" title="Derivatives desk" />{tabs}<Loading label="Reading the F&O archive" /></div>

  return (
    <div>
      <PageHeader code="DERV" title="Derivatives desk"
        subtitle={`NSE F&O · term structure, basis, rollover, PCR, max pain, VIX · EOD ${term.as_of}`}
        status={nearLeg ? <Chip color={tone(nearLeg.basis_ann_pct)} active>
          {symbol} BASIS {pct(nearLeg.basis_ann_pct, 2)} ANN · T−{nearLeg.dte}</Chip> : undefined}
        right={<Chip color={T.amber} onClick={() => load(symbol)}>↻ REFRESH</Chip>} />
      <div style={{ display: 'grid', gap: 12 }}>
        {tabs}
        {picker}

        {/* header strip (PLAN §0.4 same number once per page): spot, futures OI and the India VIX live here only; the
            near basis / DTE are in the header chip and the term table, PCR and rollover in their panels */}
        <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))' }}>
          {ulPriced && ul.source
            ? <Stat label={`${symbol} spot`} value={num(ulRow!.price, 2)} accent={T.amber}
                sub={<span><SourceChip info={ul.source} style={{ fontSize: 8.5 }} /> · EOD {num(term.spot, 2)} on {term.as_of} (the tables below)</span>} />
            : <Stat label={`${symbol} spot (EOD)`} value={num(term.spot, 2)} accent={T.amber} sub={`EOD ${term.as_of} · ${term.source}`} />}
          <Stat label="Futures OI (all expiries)" value={oiFmt(term.fut_oi_total)} accent={T.cyan} sub="shares, summed over the listed futures" />
          <Stat label="INDIA VIX" value={num(vix?.level, 2)} accent={T.muted} color={T.text}
            sub={vix ? `${ordinal(vix.pctile_1y)} pctile (1y) · close ${String(vix.as_of).slice(0, 10)} (${vix.source === 'vix_daily' ? 'NSE daily file, as the strip' : 'NSE'}) · context` : 'VIX unavailable'} />
        </div>

        <TermPanel term={term} basis={basis} basisNote={basisNote} />
        {roll ? <RolloverPanel roll={roll} term={term} /> : <Panel title={`Rollover tracker — ${symbol}`} accent={T.cyan} source={sourceOf(null, { source: 'NSE F&O bhavcopy', hint: 'loading' })}><Loading label="Futures panel" /></Panel>}
        <PcrPanel symbol={symbol} pcrRows={pcrRows} optHist={optHist} maxPain={maxPain} />
        {vix && <VixPanel vix={vix} />}

        <div style={{ fontSize: 10, color: T.dim, lineHeight: 1.6 }}>
          Sources: NSE F&O bhavcopy (nse_fo_daily, 2019-10 →; per-contract UDiFF files Jul-2024 →), NSE index closes. OI in shares.
          Basis history is near-month only (the stored grain); aggregate PCR spans all strikes and expiries, so it runs smoother than
          the OMON chain's near-expiry PCR. Rollover history starts Jul-2024 (UDiFF archive). BANKNIFTY, FINNIFTY, MIDCPNIFTY and NIFTYNXT50
          take their basis spot from NSE's daily index file (index_ohlc_daily); where it is not stored the basis history is empty
          (never NIFTY's close), while term structure and rollover still work. Max-pain history exists for NIFTY and BANKNIFTY
          (daily chain archive); for stocks only the current session's chain is archived — no fabricated series.
        </div>
      </div>
    </div>
  )
}
