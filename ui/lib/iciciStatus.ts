/**
 * ICICI session wording for the terminal chrome: the header's ICICI light (P4, UI half). Pure, no imports:
 * unit-tested by `node ui/components/desktop/__tests__/desktop.check.ts`. The pages (BRIEF, BRKR, PORT) word the same
 * kinds through components/portfolio/iciciState.ts (F4B-UI-PAGES); both read error_kind before needs_session_refresh.
 *
 * ui-api's GET /api/positions/connection-status (and the connected:false replies of open-positions, summary,
 * sector-exposure and trade-history) carry `error_kind` since round 4a: 'expired' | 'network' | 'credentials' |
 * 'unknown', or null when connected. `needs_session_refresh` is ALSO true during an ICICI network outage, so the kind
 * is read first: an outage must never tell the owner to log in again (that sends an OTP for nothing).
 * An older ui-api has no field: it is read as 'unknown' (or 'credentials' when the reply says key/secret are missing).
 *
 * Only `connected`, `error_kind` and `needs_api_credentials` are read: the rest of that payload (login URL, account)
 * is never copied anywhere by this module.
 */

export type IciciErrorKind = 'expired' | 'network' | 'credentials' | 'unknown'

const KINDS: ReadonlySet<string> = new Set(['expired', 'network', 'credentials', 'unknown'])

/** The reply's error kind: null when connected (or nothing known yet), else one of the four public kinds. */
export function iciciErrorKind(status: unknown): IciciErrorKind | null {
  if (!status || typeof status !== 'object') return null
  const s = status as { connected?: unknown; error_kind?: unknown; needs_api_credentials?: unknown }
  if (s.connected === true) return null
  if (typeof s.error_kind === 'string' && KINDS.has(s.error_kind)) return s.error_kind as IciciErrorKind
  return s.needs_api_credentials === true ? 'credentials' : 'unknown'
}

/** One line per kind: what is wrong and what to do (the header light's tooltip). */
export const ICICI_KIND_TEXT: Record<IciciErrorKind, string> = {
  network: 'ICICI unreachable (network) — not a login problem; retried by itself',
  expired: 'ICICI session expired: send /login (Telegram) or log in on the Broker tab',
  credentials: 'ICICI API key/secret missing: set them on the Broker tab',
  unknown: 'ICICI not connected: see the Broker tab',
}

/**
 * The header's ICICI light tooltip. `dataConnected` is data-service's own Breeze session (the light's colour);
 * `status` is ui-api's connection-status reply when it was read (null: not read yet / unavailable).
 */
export function iciciLightTitle(dataConnected: boolean, provider: string | null, status: unknown): string {
  if (dataConnected) return `ICICI Breeze connected (${provider ?? 'provider'})`
  if (status && typeof status === 'object' && (status as { connected?: unknown }).connected === true) {
    return 'ICICI: ui-api is connected but data-service has not picked the session up yet (it retries by itself)'
  }
  const kind = status ? iciciErrorKind(status) : null
  if (kind === null) return 'ICICI not connected: click to open the Broker tab'
  return `${ICICI_KIND_TEXT[kind]}${kind === 'network' ? '' : ' · click to open the Broker tab'}`
}
