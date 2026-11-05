'use client'

/**
 * OMON › chain header strip (reports/terminal_v2/PLAN.md 1.1 panel 2; precedent Bloomberg OVDV term tab, Opstra,
 * Market Chameleon IV30 vs HV): the term strip (near / next / far ATM IV + IV30 / 60 / 90), the 25Δ skew with its
 * 1-year percentile, the ATM straddle beside the lognormal 1σ it implies, and IV30 against three realised-vol
 * estimators (close-to-close, Parkinson, Yang-Zhang) and NSE's FOVOLT. Term and the IV levels are `arithmetic`;
 * skew and the spread are `context` (neutral tone, never bullish / bearish). The same number appears once per page:
 * the IV30 level lives in the history chip, so here it is the comparison, not the level.
 *
 * `greeksFor` is the per-strike Δ Γ Θ ν column of the chain from the existing Black-76 lib.
 */
import { BadgeChip, T, fmtNum, ordinal } from '@/components/terminal'
import { percentileOf } from '@/components/terminal/source'
import { black76 } from '@/lib/black76'
import type { OptionChain as Chain } from '@/lib/api'
import type { IvHistory, IvSurface } from './api'
import { ivVsRv, straddleView, termWord } from './volModel'

export interface Greeks { delta: number; gamma: number; thetaDay: number; vega: number }

/** Δ Γ Θ ν for one side of a strike from its own IV (per unit of the underlying); null without a traded IV. */
export function greeksFor(side: 'call' | 'put', forward: number | null | undefined, strike: number, ivPct: number | null | undefined,
                          daysToExpiry: number | null | undefined, r = 0.065): Greeks | null {
  if (forward == null || !Number.isFinite(forward) || forward <= 0 || ivPct == null || !Number.isFinite(ivPct) || ivPct <= 0) return null
  const T = Math.max(0, (daysToExpiry ?? 0)) / 365
  const g = black76(side, forward, strike, T, ivPct / 100, r)
  return { delta: g.delta, gamma: g.gamma, thetaDay: g.thetaDay, vega: g.vega }
}

function Cell({ label, value, sub, title, color = T.text }: { label: string; value: React.ReactNode; sub?: React.ReactNode; title?: string; color?: string }) {
  return (
    <div title={title} style={{ minWidth: 0, padding: '6px 10px', borderRight: `1px solid ${T.border}` }}>
      <div style={{ fontFamily: T.mono, fontSize: 9, letterSpacing: 1.2, textTransform: 'uppercase', color: T.muted, whiteSpace: 'nowrap' }}>{label}</div>
      <div style={{ fontFamily: T.mono, fontSize: 13, fontWeight: 600, color, marginTop: 2, whiteSpace: 'nowrap', fontVariantNumeric: 'tabular-nums' }}>{value}</div>
      {sub && <div style={{ fontSize: 9.5, color: T.dim, marginTop: 1, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{sub}</div>}
    </div>
  )
}

const pct1 = (v: number | null | undefined, d = 1) => (v == null || !Number.isFinite(v) ? '—' : `${fmtNum(v, d)}%`)
const signed = (v: number | null | undefined, d = 1) => (v == null || !Number.isFinite(v) ? '—' : `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(d)}`)

export function ChainStrip({ chain, history, surface }: { chain: Chain; history: IvHistory | null; surface: IvSurface | null }) {
  const rows = history?.ok ? history.rows : []
  const last = rows.length ? rows[rows.length - 1] : null
  const atmRow = chain.rows.find(r => r.strike === chain.atm)
  const straddle = straddleView(atmRow?.ce.price, atmRow?.pe.price, chain.forward, chain.atm_iv, chain.days_to_expiry)
  const vsRv = ivVsRv(rows)
  // the term ladder: the surface's per-expiry ATM IV when stored, else the chain's own ATM IV for the picked expiry
  const expiries = (surface?.ok ? surface.expiries : []).filter(e => e.atm_iv != null)
  const near = expiries.find(e => e.near) ?? expiries[0] ?? null
  const next = near ? expiries.find(e => e.expiry > near.expiry) ?? null : null
  const far = next ? expiries.find(e => e.expiry > next.expiry) ?? null : null
  const skewNow = near?.skew_25d ?? last?.skew_25d_30 ?? null
  const skewPct = percentileOf(rows.map(r => r.skew_25d_30), last?.skew_25d_30, 60)
  const termSlope = last?.term_slope_30_90 ?? null
  return (
    <div data-omon-strip style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(118px, 1fr))', border: `1px solid ${T.border}`, background: T.panel, marginBottom: 10, alignItems: 'stretch' }}>
      <Cell label="Term · near / next / far" title="ATM IV per expiry from the stored surface (iv_expiry_daily), nearest first; the expiry-day series is excluded from near. Arithmetic."
        value={near ? `${pct1(near.atm_iv)} / ${next ? pct1(next.atm_iv) : '—'} / ${far ? pct1(far.atm_iv) : '—'}` : `${pct1(chain.atm_iv)} / — / —`}
        sub={near ? `${near.expiry.slice(5)} · ${next?.expiry.slice(5) ?? '—'} · ${far?.expiry.slice(5) ?? '—'}` : `${chain.expiry.slice(5)} (chain) · surface not stored`} />
      <Cell label="IV 30 / 60 / 90 (cm)" title={history?.definitions?.iv30_cm ?? 'constant-maturity ATM IV by VIX-style variance interpolation'}
        value={last ? `${pct1(last.iv30_cm)} / ${pct1(last.iv60_cm)} / ${pct1(last.iv90_cm)}` : '—'}
        sub={last ? <>slope 30→90 {signed(termSlope, 2)} pts · {termWord(termSlope)}</> : 'iv_summary_daily not stored'} />
      <Cell label="25Δ skew (put − call)" title={history?.definitions?.skew_25d_30 ?? '25-delta put IV minus 25-delta call IV, vol points'}
        value={skewNow == null ? '—' : `${signed(skewNow, 2)} pts`}
        sub={skewPct != null ? <>{ordinal(skewPct)} pctile of the past year · <BadgeChip badge="context" /></> : rows.length ? 'needs 60 stored sessions for a percentile' : 'stored series needed'} />
      <Cell label={`ATM straddle · ${chain.atm}`} title="Call + put price at the ATM strike as a % of the forward, beside the lognormal 1σ to expiry that the chain's ATM IV implies (ATM IV × √(days/365)). Arithmetic: a comparison, not a view."
        value={straddle.price == null ? '—' : `₹${fmtNum(straddle.price, 2)}`}
        sub={straddle.pct_of_forward == null ? '' : <>{pct1(straddle.pct_of_forward, 2)} of fwd · 1σ to expiry {pct1(straddle.sigma_to_expiry_pct, 2)} · ratio {fmtNum(straddle.straddle_over_sigma, 2)}×</>} />
      <Cell label="IV30 − RV20 (YZ)" title={history?.definitions?.iv_minus_rv20 ?? 'IV30 minus the 20-session Yang-Zhang realised vol, vol points'}
        value={vsRv?.spread == null ? '—' : `${signed(vsRv.spread, 2)} pts`}
        sub={vsRv ? <>cc {pct1(vsRv.cc)} · Parkinson {pct1(vsRv.parkinson)} · YZ {pct1(vsRv.yz)} · FOVOLT {pct1(vsRv.fovolt)}</> : 'realised vol needs the stored index OHLC'} />
      <Cell label="Priced 1-day move" title="iv30_cm ÷ √252: the one-session 1σ move the 30-day IV implies. Arithmetic."
        value={last?.expected_move_1d_pct == null ? '—' : `±${pct1(last.expected_move_1d_pct, 2)}`}
        sub={last ? `as of ${last.date}` : ''} />
    </div>
  )
}
