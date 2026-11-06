/**
 * BTST (Backtest lab) defaults — 5 Nov 2026 review, M20 / m092. Pure, unit-tested under plain node by
 * ui/components/__tests__/honesty.check.ts.
 *
 * The old defaults (5 names, a 2 % stop, a 5-day time-stop, 15 bps) were the legacy 5-day system, which FAILS after
 * costs (it loses ~45–50 %/yr to charges; the rules-only swing backtest lost 17.8 % a year after ICICI costs). The
 * defaults now follow the Decision Desk: 20 names, a 21-session hold, no per-trade stop, and the real ICICI delivery
 * round trip from shared/trading_costs.py (via GET /api/costs/ticket) at the lab's own position size.
 */

export const DESK_LIKE = Object.freeze({
  maxPositions: 20,
  holdSessions: 21,
  stopMode: 'none' as StopMode,
  ddHaltPct: 20,            // the Desk's HARD −20 % rule (the lab halts new entries; the Desk sells everything)
  dailyHalt: false,         // the −2 % daily halt belongs to the legacy 5-day system, not the Desk
})

/** What the defaults used to be: shown on the page as the configuration that FAILS. */
export const LEGACY_DEFAULTS = Object.freeze({ maxPositions: 5, holdSessions: 5, stopPct: 2, frictionBps: 15 })

/** The server's compliance floor (CLAUDE.md: never < 0.15 %); a floor, never a realistic cost. */
export const MIN_FRICTION_BPS = 15

export type StopMode = 'none' | 'atr' | 'fixed'

/** ₹ size of one position: the ₹24 DP charge makes the round-trip % depend on it. */
export function positionValue(capital: number, positions: number): number {
  return capital / Math.max(1, Math.floor(positions))
}

/** Round-trip % from the cost ticket → friction in bps, rounded UP to 0.1 bps (never below the floor). */
export function frictionFromRoundTrip(roundTripPct: number | null | undefined): number | null {
  if (roundTripPct == null || !Number.isFinite(roundTripPct) || roundTripPct <= 0) return null
  return Math.max(MIN_FRICTION_BPS, Math.ceil(roundTripPct * 1000 - 1e-9) / 10)
}

/** The two stop fields the API takes, from the page's one stop selector. 'none' sends both null: the API's ATR stop
 *  is opt-in, so nothing else can switch a stop on behind the user's back. */
export function stopPayload(mode: StopMode, atrMult: number, fixedPct: number): { atr_stop_mult: number | null; stop_loss_pct: number | null } {
  if (mode === 'atr') return { atr_stop_mult: atrMult, stop_loss_pct: fixedPct }      // fixed % = fallback when ATR is missing
  if (mode === 'fixed') return { atr_stop_mult: null, stop_loss_pct: fixedPct }
  return { atr_stop_mult: null, stop_loss_pct: null }
}

/** True when a configuration is the legacy short-hold book the research failed (a hold under 20 sessions with 5 or
 *  fewer names, or a friction at the floor): the page says so beside the Run button. */
export function looksLegacy(p: { holdSessions: number; maxPositions: number; frictionBps: number }): boolean {
  return p.holdSessions < 20 || p.frictionBps <= MIN_FRICTION_BPS || (p.maxPositions <= 5 && p.holdSessions < 21)
}
