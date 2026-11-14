/**
 * The broker-session face (F7-05, 14 Nov 2026).
 *
 * The defect this answers: on 14 Nov the ledger held 121 `generate_session` calls, EVERY ONE failed, and the
 * `errors_today` the API serves had zero readers in `ui/`. So a dead broker session looked exactly like a healthy
 * one on every page — the terminal would have let the owner trade a morning believing the quotes were live. That
 * is the one failure mode this product otherwise does not have: it fails quietly.
 *
 * Deliberately NOT read here: `/api/positions/connection-status`, whose payload carries a `login_url` containing
 * the API key. This model reads only `/api/positions/breeze-budget` (credential-free: counters and quotas) and
 * `/live/status`'s derived booleans. Nothing it returns can carry a secret.
 *
 * Facts only, no advice: the chip says what the session IS, never what to do about it.
 */

export type BudgetSnap = {
  errors_today?: number | null
  by_method?: Record<string, number> | null
  refused_today?: number | null
}

export type LiveSnap = {
  /** data-service's own word for the socket: LIVE | DISCONNECTED | … */
  state?: string | null
  breeze_session?: boolean | null
}

export type BrokerFace = {
  label: string
  tone: 'ok' | 'warn' | 'bad' | 'idle'
  title: string
}

/** The session is only ever EXPECTED while an Indian market is open — 09:15–15:30 (NSE) or up to 23:30 (MCX). */
export function sessionExpected(ist: Date, nseOnly = false): boolean {
  const day = ist.getDay()
  if (day === 0 || day === 6) return false                       // weekend: the token dies at midnight by design
  const hm = ist.getHours() * 100 + ist.getMinutes()
  return nseOnly ? hm >= 915 && hm <= 1530 : hm >= 915 && hm <= 2330
}

/**
 * The chip, or null when there is genuinely nothing to say.
 *
 * `idle` (outside market hours, no session) renders nothing: the token expiring overnight is normal and a chip
 * that cries every night teaches the owner to ignore it. During market hours a missing session is `bad`, and
 * repeated login failures are worth saying even when a session did eventually come up — they are the early
 * warning that the 08:00 job is failing.
 */
export function brokerFace(live: LiveSnap | null, budget: BudgetSnap | null, ist: Date): BrokerFace | null {
  const expected = sessionExpected(ist)
  const connected = live?.breeze_session === true
  const errors = Number(budget?.errors_today ?? 0)
  const logins = Number(budget?.by_method?.generate_session ?? 0)

  if (!live && !budget) return null                               // nothing fetched yet: say nothing, never guess

  if (!connected && expected) {
    return {
      label: 'BRKR DOWN',
      tone: 'bad',
      title: `No broker session while the market is open${errors ? ` · ${errors} broker error${errors === 1 ? '' : 's'} today` : ''}`
        + (logins ? ` · ${logins} login attempt${logins === 1 ? '' : 's'}` : '')
        + '. Live quotes, the option chain and margin fall back to stored or delayed data, each labelled on its own panel.',
    }
  }
  // a session that exists but was expensive to get: the 08:00 job is struggling and only this says so
  if (errors >= 20) {
    return {
      label: `BRKR ${errors} ERR`,
      tone: 'warn',
      title: `${errors} broker errors today across ${logins} login attempt${logins === 1 ? '' : 's'}`
        + `${connected ? ' (a session is up now)' : ''}. Each failed attempt still counts against the daily broker quota.`,
    }
  }
  if (!connected && !expected) {
    return { label: 'BRKR IDLE', tone: 'idle', title: 'No broker session outside market hours — the token expires at midnight IST by design.' }
  }
  return null                                                     // connected, few errors: the header stays quiet
}
