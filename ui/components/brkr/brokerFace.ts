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

/**
 * The IST wall clock, as the weekday and HHMM this model reasons about.
 *
 * F8-05: `sessionExpected` used to take a `Date` and read `getDay()` / `getHours()` off it, which are the
 * BROWSER's timezone, not India's. Every sibling in the same header converts explicitly (MarketCommandHeader
 * and lib/format both pass timeZone 'Asia/Kolkata'), and this one did not: from a non-IST machine the weekday
 * and the window both slide, so 20:30 UTC Friday — 02:00 IST Saturday, markets shut — reads as a weekday
 * inside market hours and paints a false red BRKR DOWN at two in the morning. The node checks could not catch
 * it either, because their fixtures built local-time Dates on the same assumption.
 */
export type IstClock = { day: number; hm: number }

export function istClock(now: Date): IstClock {
  const p = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Kolkata', weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(now)
  const get = (t: string) => p.find(x => x.type === t)?.value ?? ''
  const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
  // An unexpected ICU rendering would make indexOf return -1, which is neither 0 nor 6 — so a Saturday would
  // have read as a weekday and the market window would have applied. Fall back to the host's own weekday,
  // which is wrong by at most a day rather than wrong in a way that invents a trading session.
  const idx = days.indexOf(get('weekday'))
  const day = idx >= 0 ? idx : now.getUTCDay()
  const hour = Number(get('hour'))
  // 'en-GB' with hour12:false renders midnight as 24 in some ICU versions; normalise so 24:05 is not > 23:30
  return { day, hm: (hour === 24 ? 0 : hour) * 100 + Number(get('minute')) }
}

/** The session is only ever EXPECTED while an Indian market is open — 09:15–15:30 (NSE) or up to 23:30 (MCX). */
export function sessionExpected(ist: IstClock, nseOnly = false): boolean {
  if (ist.day === 0 || ist.day === 6) return false               // weekend: the token dies at midnight by design
  return nseOnly ? ist.hm >= 915 && ist.hm <= 1530 : ist.hm >= 915 && ist.hm <= 2330
}

/**
 * The chip, or null when there is genuinely nothing to say.
 *
 * The ladder, quietest first (F9-02: this used to claim `idle` "renders nothing", which was never true — it
 * renders a grey chip, and the one state that renders nothing is a healthy session returning null):
 *   null  — connected, few errors. The header says nothing at all; that silence is the healthy state.
 *   idle  — no session outside market hours. Grey. The token expiring overnight is normal, and a chip that
 *           cries every night teaches the owner to ignore it.
 *   warn  — BRKR PRE: no session between 08:15 and the 09:15 open on a trading day, i.e. the 08:00 login has
 *           not produced one while there is still time to fix it; or BRKR n ERR: a session exists but the day
 *           has cost a lot of failed calls, which is the early warning that the login job is struggling.
 *   bad   — no session while a market is open. Red, because quotes, the chain and margin are all degraded.
 */
export function brokerFace(live: LiveSnap | null, budget: BudgetSnap | null, ist: IstClock): BrokerFace | null {
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
  // F9-01: the hour that matters most, which F8-04's reorder had silently handed to IDLE.
  //
  // `sessionExpected` is false until 09:15, so between 08:15 and the open a dead session fell through to the
  // grey "the token expires at midnight IST by design" — a sentence that is true at 2 a.m. and actively
  // misleading at 08:30, because by then the 08:00 login job has run and either produced a session or failed.
  // That hour is the ONLY window in which a failed login is still repairable (Telegram /login with the SMS
  // OTP) before quotes are needed, and the terminal was reassuring the owner through exactly it.
  //
  // This is deliberately NOT folded into `sessionExpected`: a session is genuinely not *expected* before the
  // open — the login job may legitimately still be running at 08:05 — it is merely OVERDUE, which is a
  // different thing and earns amber rather than red. Trading days only, so the nightly-silence contract and
  // F8-05's 02:00-Saturday case both still hold.
  if (!connected && ist.day >= 1 && ist.day <= 5 && ist.hm >= 815 && ist.hm < 915) {
    return {
      label: 'BRKR PRE',
      tone: 'warn',
      title: 'No broker session yet and the market opens at 09:15 — the 08:00 login has not produced one'
        + `${errors ? ` (${errors} failed broker call${errors === 1 ? '' : 's'} today)` : ''}. There is still `
        + 'time: /login on Telegram and reply with the SMS OTP. Live quotes, the chain and margin stay on '
        + 'stored or delayed data until a session exists, each labelled on its own panel.',
    }
  }
  // F8-04: the error branch used to be tested BEFORE this one, so a closed Saturday carrying a dead token
  // showed an amber "BRKR 127 ERR" — exactly the nightly noise the contract above promises to avoid. Outside
  // market hours a failing login is expected and tells the owner nothing new, so IDLE wins the tie.
  if (!connected && !expected) {
    return { label: 'BRKR IDLE', tone: 'idle', title: 'No broker session outside market hours — the token expires at midnight IST by design.' }
  }
  // a session that exists but was expensive to get: the 08:00 job is struggling and only this says so
  if (errors >= 20) {
    return {
      label: `BRKR ${errors} ERR`,
      tone: 'warn',
      // F8-04: `errors_today` counts failures across ALL methods, not just logins, so the old wording
      // ("errors across N login attempts") attributed them to a denominator that does not contain them.
      // The two numbers are now stated side by side as the different things they are.
      // F9-05: `connected` is necessarily true here (every !connected case returned above) and `errors` is
      // necessarily >= 20, so the ternaries this line used to carry could never take their other branch.
      title: `A session is up, but ${errors} broker calls have failed today (all methods), alongside ${logins} `
        + `login attempt${logins === 1 ? '' : 's'}. Each failed call still counts against the daily broker quota.`,
    }
  }
  return null                                                     // connected, few errors: the header stays quiet
}
