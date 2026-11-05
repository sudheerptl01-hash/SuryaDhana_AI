/**
 * What BRKR, PORT and BRIEF say when ICICI Breeze is not connected (FEATURE_PARITY P4, UI half).
 *
 * ui-api adds `error_kind` to /api/positions/connection-status (always) and to the connected:false replies of
 * /summary, /open-positions, /sector-exposure and /trade-history (reports/desktop_app/review/fix_round4a.md):
 *   'expired'     ICICI refused the session token: log in again (Telegram /login, or BRKR).
 *   'network'     ICICI's API could not be reached after 3 tries: NOT a login problem, the session may be fine.
 *   'credentials' the API key / secret is missing, or ICICI rejected it: fix it on BRKR.
 *   'unknown'     any other Breeze failure.
 *   null          connected.
 * `needs_session_refresh` stays true during a network outage, so the kind is read FIRST. A missing field (an older
 * ui-api) counts as 'unknown', which keeps the old wording. Only 'network' and 'credentials' change what the
 * pages say: a network outage no longer tells the owner to send /login (a new login ends the session in use).
 *
 * Pure module (no React, no imports): unit-tested by ui/components/__tests__/pages.check.ts under plain node.
 */

export type IciciErrorKind = 'expired' | 'network' | 'credentials' | 'unknown'

const KINDS: readonly string[] = ['expired', 'network', 'credentials', 'unknown']

/** The public kind from one reply: null when connected, 'unknown' for a missing or unexpected value. */
export function iciciErrorKind(reply: { connected?: boolean | null; error_kind?: unknown } | null | undefined): IciciErrorKind | null {
  if (!reply || reply.connected === true) return null
  return typeof reply.error_kind === 'string' && KINDS.includes(reply.error_kind) ? reply.error_kind as IciciErrorKind : 'unknown'
}

/**
 * The kind a page acts on. `primary` is the reply that decided "not connected" (BRKR / PORT summary, open
 * positions), `status` the connection-status reply. The first known kind wins; 'unknown' only when neither knows.
 */
export function pickErrorKind(...replies: ({ connected?: boolean | null; error_kind?: unknown } | null | undefined)[]): IciciErrorKind | null {
  let seen = false
  for (const r of replies) {
    if (!r) continue
    const k = iciciErrorKind(r)
    if (k === null) continue
    seen = true
    if (k !== 'unknown') return k
  }
  return seen ? 'unknown' : null
}

export interface IciciIssue {
  kind: IciciErrorKind
  /** header chip on BRKR */
  chip: string
  /** one-line headline (BRKR notice, PORT banner, BRIEF line) */
  headline: string
  /** what to do; null keeps the page's existing guidance */
  detail: string | null
  /** the page may suggest logging in again (Telegram /login, LOG IN TO ICICI) */
  suggestLogin: boolean
  /** BRKR shows the API key / secret form */
  showCredentials: boolean
}

export const ICICI_UNREACHABLE = 'ICICI unreachable (network) — your session may still be valid'

/**
 * Wording for a kind. 'expired' and 'unknown' keep the pages' existing text (`fallback`, the server's error or the
 * page's default), and still offer the login; 'network' and 'credentials' get their own.
 */
export function iciciIssue(kind: IciciErrorKind, opts: { fallback?: string | null; keyMissing?: boolean } = {}): IciciIssue {
  const fallback = (opts.fallback ?? '').trim()
  if (kind === 'network') {
    return {
      kind, chip: 'ICICI UNREACHABLE', headline: ICICI_UNREACHABLE,
      detail: "ICICI's API could not be reached after 3 tries. This is not a login problem: do not log in again (a new "
        + 'login ends the session in use). The check repeats by itself; press Recheck when the network is back.',
      suggestLogin: false, showCredentials: false,
    }
  }
  if (kind === 'credentials') {
    const missing = opts.keyMissing !== false
    return {
      kind, chip: missing ? 'API KEY MISSING' : 'API KEY REJECTED',
      headline: missing ? 'ICICI API key / secret missing' : 'ICICI rejected the API key / secret',
      detail: `${missing ? 'Enter' : 'Check'} them on BRKR (Broker page): a session login cannot work until the API key and secret are right.`,
      suggestLogin: false, showCredentials: true,
    }
  }
  return {
    kind, chip: 'NOT CONNECTED', headline: fallback || 'ICICI session expired or not logged in',
    detail: null, suggestLogin: true, showCredentials: false,
  }
}

/** BRIEF's System line for a disconnected session (the old text for expired / unknown). */
export function briefSessionLine(kind: IciciErrorKind | null): string {
  if (kind === null) return 'connected'
  if (kind === 'network') return 'ICICI unreachable (network): session may still be valid'
  if (kind === 'credentials') return 'API key / secret missing or rejected (Broker tab)'
  return 'expired: log in (Broker tab) or enable TOTP auto-login'
}
