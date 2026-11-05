/**
 * PORT (legacy execution engine) presentation policy on a PAPER-ONLY terminal (C1-trader-ux-04, RUP-02).
 *
 * ui-api's PAPER ONLY guard (services/ui-api/routers/execution.py) adds `live_allowed` and `mode_policy` to
 * GET /api/execution/status: it refuses LIVE mode, switches a restored LIVE engine back to PAPER and refuses
 * every order path while the engine is LIVE. The page must say so plainly: PAPER ONLY, the LIVE toggle
 * disabled with an explanation, LIVE never drawn as the selected mode, and LIQUIDATE & HALT offered only for
 * a running PAPER engine (with its confirmation).
 *
 * Fail CLOSED (RUP-02): LIVE is offered only when the server says so in BOTH fields (`live_allowed: true` and
 * `mode_policy: 'LIVE_ALLOWED'`, i.e. the owner set EXECUTION_LIVE_ALLOWED=1). A missing status (the first
 * refresh failed or timed out), a status without the fields, or contradicting fields all mean PAPER ONLY. With
 * no status at all the chip says STATUS UNKNOWN and LIQUIDATE is disabled too (there is no engine to act on).
 * The UI is served by the same ui-api release (:8010 static export; :3000 proxies to the same repo), so there is
 * no older ui-api whose behaviour the page has to keep.
 *
 * Pure module (no React, no imports): unit-tested by ui/components/__tests__/pages.check.ts under plain node.
 */

export interface ExecStatusLike {
  available?: boolean | null
  mode?: string | null
  state?: string | null
  live_allowed?: boolean | null
  mode_policy?: string | null
}

export interface ExecPolicy {
  /** the server reported its mode policy (ui-api with the PAPER ONLY guard) */
  known: boolean
  /** a status was read at all (false: the first refresh failed, nothing is known about the engine) */
  statusKnown: boolean
  /** the server does not explicitly allow LIVE: the terminal is PAPER ONLY */
  paperOnly: boolean
  /** header chip text */
  modeLabel: string
  /** header chip tone */
  modeTone: 'paper' | 'live' | 'unknown'
  /** the PAPER/LIVE toggle may offer LIVE */
  liveSelectable: boolean
  /** LIVE is drawn as the selected mode */
  showLiveSelected: boolean
  /** the engine reports LIVE although the terminal is PAPER ONLY (the guard switches it back on the next call) */
  engineLiveMismatch: boolean
  /** LIQUIDATE & HALT may be pressed */
  liquidateAllowed: boolean
  /** its label */
  liquidateLabel: string
}

const upper = (v: unknown): string => (typeof v === 'string' ? v.trim().toUpperCase() : '')

export function executionPolicy(s: ExecStatusLike | null | undefined): ExecPolicy {
  const statusKnown = s != null
  const mode = upper(s?.mode) === 'LIVE' ? 'LIVE' : 'PAPER'
  const halted = upper(s?.state) === 'HALTED'
  const policy = upper(s?.mode_policy)
  const known = typeof s?.live_allowed === 'boolean' || policy === 'PAPER_ONLY' || policy === 'LIVE_ALLOWED'
  // an engine to act on: a status was read, the engine is loaded and not UNAVAILABLE
  const engineUp = statusKnown && s?.available !== false && upper(s?.state) !== 'UNAVAILABLE'
  // fail closed: LIVE only when BOTH fields say the owner allowed it
  const liveAllowed = s?.live_allowed === true && policy === 'LIVE_ALLOWED'
  if (!liveAllowed) {
    return {
      known, statusKnown, paperOnly: true,
      modeLabel: statusKnown ? 'PAPER ONLY' : 'STATUS UNKNOWN · PAPER ONLY',
      modeTone: statusKnown ? 'paper' : 'unknown',
      liveSelectable: false, showLiveSelected: false,
      engineLiveMismatch: statusKnown && mode === 'LIVE',
      liquidateAllowed: engineUp && !halted && mode === 'PAPER',
      liquidateLabel: '■ LIQUIDATE & HALT · PAPER',
    }
  }
  return {
    known, statusKnown, paperOnly: false, modeLabel: mode, modeTone: mode === 'LIVE' ? 'live' : 'paper',
    liveSelectable: true, showLiveSelected: mode === 'LIVE',
    engineLiveMismatch: false,
    liquidateAllowed: engineUp && !halted,
    liquidateLabel: '■ LIQUIDATE & HALT',
  }
}
