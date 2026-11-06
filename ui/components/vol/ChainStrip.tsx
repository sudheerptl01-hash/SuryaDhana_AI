'use client'

/**
 * OMON › chain header strip (reports/terminal_v2/PLAN.md 1.1 panel 2; precedent Bloomberg OVDV term tab, Opstra,
 * Market Chameleon IV30 vs HV): the term strip (near / next / far ATM IV + IV30 / 60 / 90), the 25Δ skew — the near
 * expiry's and the 30-day one, EACH with the percentile of its OWN series (M03: the tile printed the weekly's −0.78
 * beside the 30-day series' 34th percentile) — the ATM straddle's breakeven against the moves the underlying actually
 * made over windows of the same length (m053: "0.80× the priced move" was the √(2/π) identity), and IV30 against the
 * three realised-vol estimators, the spread of record being CLOSE-TO-CLOSE (M01: the tile said "(YZ)" over a cc number)
 * with the Parkinson / Yang-Zhang spreads named beside it, and NSE's FOVOLT on both annualisations (m054). Term and the
 * IV levels are `arithmetic`; skew and the spread are `context` (neutral tone, never bullish / bearish). The same number
 * appears once per page: the IV30 level lives in the history chip, so here it is the comparison, not the level.
 *
 * `greeksFor` is the per-strike Δ Γ Θ ν column of the chain from the existing Black-76 lib, on the app's one time
 * convention (M04: T = calendar time to 15:30 IST on expiry ÷ 365 — the chain's `t_days`, fractional intraday).
 */
import { BadgeChip, T, fmtNum, ordinal } from '@/components/terminal'
import { percentileOf } from '@/components/terminal/source'
import { black76 } from '@/lib/black76'
import type { OptionChain as Chain } from '@/lib/api'
import type { IvHistory, IvSurface, NearSkew } from './api'
import { ivVsRv, lastYear, straddleHitRate, straddleView, termWord, weekdaysBetween } from './volModel'

export interface Greeks { delta: number; gamma: number; thetaDay: number; vega: number }

/** Δ Γ Θ ν for one side of a strike from its IV, per unit of the underlying; null without a traded IV. `tDays` is the
 *  chain's `t_days` — calendar days to 15:30 IST on expiry (fractional intraday), the one convention (M04). */
export function greeksFor(side: 'call' | 'put', forward: number | null | undefined, strike: number, ivPct: number | null | undefined,
                          tDays: number | null | undefined, r = 0.065): Greeks | null {
  if (forward == null || !Number.isFinite(forward) || forward <= 0 || ivPct == null || !Number.isFinite(ivPct) || ivPct <= 0) return null
  const T = Math.max(0, (tDays ?? 0)) / 365
  const g = black76(side, forward, strike, T, ivPct / 100, r)
  return { delta: g.delta, gamma: g.gamma, thetaDay: g.thetaDay, vega: g.vega }
}

function Cell({ label, value, sub, title, color = T.text }: { label: string; value: React.ReactNode; sub?: React.ReactNode; title?: string; color?: string }) {
  return (
    <div title={title} style={{ minWidth: 0, padding: '6px 10px', borderRight: `1px solid ${T.border}` }}>
      <div style={{ fontFamily: T.mono, fontSize: 9, letterSpacing: 1.2, textTransform: 'uppercase', color: T.muted, whiteSpace: 'nowrap' }}>{label}</div>
      <div style={{ fontFamily: T.mono, fontSize: 13, fontWeight: 600, color, marginTop: 2, whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>{value}</div>
      {sub && <div style={{ fontSize: 9.5, color: T.dim, marginTop: 1, lineHeight: 1.35 }}>{sub}</div>}
    </div>
  )
}

const pct1 = (v: number | null | undefined, d = 1) => (v == null || !Number.isFinite(v) ? '—' : `${fmtNum(v, d)}%`)
/** b − a in vol points; null when either leg is missing */
const gap = (b: number | null | undefined, a: number | null | undefined) => (b == null || a == null ? null : b - a)
const signed = (v: number | null | undefined, d = 1) => (v == null || !Number.isFinite(v) ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(d)}`)

export function ChainStrip({ chain, history, surface, nearSkew }: { chain: Chain; history: IvHistory | null; surface: IvSurface | null; nearSkew?: NearSkew | null }) {
  const rows = history?.ok ? history.rows : []
  const last = rows.length ? rows[rows.length - 1] : null
  const atmRow = chain.rows.find(r => r.strike === chain.atm)
  const straddle = straddleView(atmRow?.ce.price, atmRow?.pe.price, chain.forward, chain.atm_iv, chain.days_to_expiry)
  const sessionsLeft = weekdaysBetween(chain.date, chain.expiry)
  const hit = straddleHitRate(rows, straddle.pct_of_forward, sessionsLeft)
  const vsRv = ivVsRv(rows)
  // the term ladder: the surface's per-expiry ATM IV when stored, else the chain's own ATM IV for the picked expiry
  const expiries = (surface?.ok ? surface.expiries : []).filter(e => e.atm_iv != null)
  const near = expiries.find(e => e.near) ?? expiries[0] ?? null
  const next = near ? expiries.find(e => e.expiry > near.expiry) ?? null : null
  const far = next ? expiries.find(e => e.expiry > next.expiry) ?? null : null
  // M03: two skews, each beside the percentile of ITS OWN series — the near expiry's (stored per session, /near-skew) and the
  // 30-day constant-maturity one (iv_summary_daily) — never one value with the other's percentile
  const nearNow = near?.skew_25d ?? null
  const nearPct = nearSkew?.ok && nearSkew.today != null && nearNow != null && Math.abs(nearSkew.today - nearNow) < 1e-6 ? nearSkew.pctile : null
  const skew30 = last?.skew_25d_30 ?? null
  const skew30Pct = percentileOf(lastYear(rows).map(r => r.skew_25d_30), skew30, 60)
  const termSlope = last?.term_slope_30_90 ?? null
  return (
    <div data-omon-strip style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(118px, 1fr))', border: `1px solid ${T.border}`, background: T.panel, marginBottom: 10, alignItems: 'stretch' }}>
      <Cell label="Term · next − near / far − next" title="The spread between the stored ATM IVs of consecutive expiries (iv_expiry_daily), in vol points; each expiry's own ATM IV is on the ladder chips above (printed once per page; the ATM tile shows the same number for the picked expiry, one method). The expiry-day series is excluded from near. Arithmetic."
        value={near ? `${signed(gap(next?.atm_iv, near.atm_iv), 2)} / ${signed(gap(far?.atm_iv, next?.atm_iv), 2)} pts` : '— / —'}
        sub={near ? `${near.expiry.slice(5)} · ${next?.expiry.slice(5) ?? '—'} · ${far?.expiry.slice(5) ?? '—'}` : 'surface not stored yet · backfill pending (the chain ATM IV is in the tiles above)'} />
      <Cell label="IV 30 / 60 / 90 (cm)" title={history?.definitions?.iv30_cm ?? 'constant-maturity ATM IV by VIX-style variance interpolation'}
        value={last ? `${pct1(last.iv30_cm)} / ${pct1(last.iv60_cm)} / ${pct1(last.iv90_cm)}` : '—'}
        sub={last ? <>slope 30→90 {signed(termSlope, 2)} pts · {termWord(termSlope)}{String(last.quality_flags ?? '').includes('cm30_flat') ? ' · IV30 flat from one expiry' : ''}</> : 'iv_summary_daily not stored'} />
      <Cell label={`25Δ skew · near ${near ? near.expiry.slice(5) : '—'} / 30-day`}
        title={`Two series, each with ITS OWN percentile of the past year. Near: ${nearSkew?.definition ?? history?.definitions?.near_skew_25d ?? 'the first expiry more than 2 days out'} 30-day: ${history?.definitions?.skew_25d_30 ?? '25-delta put IV minus 25-delta call IV on the 30-day surface'} Context.`}
        value={`${signed(nearNow, 2)} / ${signed(skew30, 2)} pts`}
        sub={<>near {nearPct != null ? `${ordinal(nearPct)} pct` : nearSkew && !nearSkew.ok ? 'pct pending' : '—'} · 30-day {skew30Pct != null ? `${ordinal(skew30Pct)} pct` : rows.length ? 'needs 60 sessions' : '—'} · <BadgeChip badge="context" /></>} />
      <Cell label={`ATM straddle · ${chain.atm}`} title={`Call + put at the ATM strike as a % of the forward: the breakeven move by expiry. Beside it, the share of the past ${hit.windows} windows of ${hit.sessions} sessions (the sessions left to this expiry) in which the underlying moved further than that (stored spot history). Arithmetic: a description of the past, does not predict.`}
        value={straddle.price == null ? '—' : `₹${fmtNum(straddle.price, 2)}`}
        sub={straddle.pct_of_forward == null ? '' : <>breakeven ±{pct1(straddle.pct_of_forward, 2)}{hit.share != null ? <> · beyond it in {fmtNum(hit.share, 0)}% of past {hit.sessions}-session windows</> : null}</>} />
      <Cell label="IV30 − RV20 (close-to-close)" title={`${history?.definitions?.iv_minus_rv20 ?? 'IV30 minus the 20-session close-to-close realised vol, vol points'} The Parkinson and Yang-Zhang spreads are printed beside it, each named. FOVOLT is NSE's EWMA vol annualised × √365; on the √252 basis of the three RVs it is the second number. Context: a volatility risk premium, not a direction.`}
        value={vsRv?.spread == null ? '—' : `${signed(vsRv.spread, 2)} pts`}
        sub={vsRv ? <>vs Parkinson {signed(vsRv.spreadParkinson, 1)} · vs YZ {signed(vsRv.spreadYz, 1)} · RV cc {pct1(vsRv.cc)} · Park {pct1(vsRv.parkinson)} · YZ {pct1(vsRv.yz)} · FOVOLT {pct1(vsRv.fovolt)} (√365; {pct1(vsRv.fovolt252)} √252)</> : 'realised vol needs the stored index OHLC'} />
      <Cell label="Priced 1-day move" title="iv30_cm ÷ √252: the one-session 1σ move the 30-day IV implies. Arithmetic."
        value={last?.expected_move_1d_pct == null ? '—' : `±${pct1(last.expected_move_1d_pct, 2)}`}
        sub={last ? `as of ${last.date}` : ''} />
    </div>
  )
}
