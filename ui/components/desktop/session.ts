/**
 * NSE session clock: the ONE session rule for the desktop title strip and the page header (MarketCommandHeader),
 * so the two can never disagree (C3-06: on a trading holiday the header used to say NSE OPEN next to the strip's
 * CLOSED · holiday). Pure functions, no imports, no DOM (unit-tested by
 * `node ui/components/desktop/__tests__/desktop.check.ts`).
 *
 * Rules (IST, Asia/Kolkata, which has no DST):
 *   PRE-OPEN  09:00–09:15 on a trading day (call auction; orders 09:00–09:08)
 *   OPEN      09:15–15:30 on a trading day
 *   CLOSED    otherwise; `reason` says why: WEEKEND, HOLIDAY (with the name), BEFORE OPEN, AFTER CLOSE or SPECIAL
 * A trading day is a weekday that is not in `holidays` (ISO date → name, from NSE's holiday master via the ECO
 * calendar API). Unknown holidays (API down) degrade to the weekday rule, exactly like the header's clock.
 *
 * Special sessions (R-UI-SHELL-03 / CT-10): a date in `specials` (default SPECIAL_SESSIONS, e.g. the Sun 8 Nov 2026
 * Muhurat session) is never plain WEEKEND / HOLIDAY. Inside its published IST window it is OPEN; outside it, or while
 * NSE has not published the timings, it is CLOSED with reason SPECIAL and the session's name, so the strip and the
 * header say MUHURAT instead of WEEKEND. The live chips do not rely on the window: a live tick or a fresh NSE print
 * makes them live whatever this calendar says (lib/feedState.ts, components/shell/useFeed.ts).
 */

/** One NSE special session (IST minutes since midnight; null while NSE has not published the timings). */
export interface SpecialSession {
  name: string
  label: 'MUHURAT' | 'SPECIAL'
  from: number | null
  to: number | null
}

/**
 * NSE special sessions. Same dates as shared/mcx_specs.py SPECIAL_SESSIONS_2026 (desktop.check fails on drift).
 * Fill in `from` / `to` from the NSE circular when it is published (Muhurat is about one hour in the evening).
 */
export const SPECIAL_SESSIONS: Readonly<Record<string, SpecialSession>> = Object.freeze({
  '2026-11-08': { name: 'Muhurat trading (Diwali Laxmi Pujan)', label: 'MUHURAT', from: null, to: null },
})

export type NseState = 'PRE-OPEN' | 'OPEN' | 'CLOSED'
export type ClosedReason = 'WEEKEND' | 'HOLIDAY' | 'BEFORE OPEN' | 'AFTER CLOSE' | 'SPECIAL'

export interface NseSession {
  state: NseState
  reason: ClosedReason | null
  /** Holiday name when reason === 'HOLIDAY'. */
  holiday: string | null
  /** The special session of this IST date (Muhurat…), whatever the state; null on an ordinary day. */
  special: SpecialSession | null
  /** IST calendar date, YYYY-MM-DD. */
  istDate: string
  /** IST wall clock HH:MM:SS (24 h). */
  istTime: string
  /** 0 = Sunday … 6 = Saturday, in IST. */
  istWeekday: number
  /** Minutes since IST midnight. */
  istMinutes: number
}

/** IST is a fixed UTC+05:30 offset (no DST since 1945), so plain arithmetic is exact and allocation-free. */
export const IST_OFFSET_MS = 330 * 60 * 1000

const PRE_OPEN_FROM = 9 * 60
const OPEN_FROM = 9 * 60 + 15
const CLOSE_AT = 15 * 60 + 30
/** End of the closing session (15:30–16:00: closing price, post-close orders); the header shows CLOSING until then. */
export const CLOSING_UNTIL = 16 * 60

const pad = (n: number) => (n < 10 ? `0${n}` : String(n))

/** Wall-clock parts of `epochMs` in IST. */
export function istParts(epochMs: number): { date: string; time: string; weekday: number; minutes: number; seconds: number } {
  const d = new Date(epochMs + IST_OFFSET_MS) // read with getUTC* = IST wall clock
  const date = `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`
  const h = d.getUTCHours()
  const m = d.getUTCMinutes()
  const s = d.getUTCSeconds()
  return { date, time: `${pad(h)}:${pad(m)}:${pad(s)}`, weekday: d.getUTCDay(), minutes: h * 60 + m, seconds: s }
}

/** NSE cash-market session state at `epochMs`. */
export function nseSession(epochMs: number, holidays: ReadonlyMap<string, string> | null = null,
  specials: Readonly<Record<string, SpecialSession>> | null = SPECIAL_SESSIONS): NseSession {
  const p = istParts(epochMs)
  const base = { istDate: p.date, istTime: p.time, istWeekday: p.weekday, istMinutes: p.minutes, holiday: null, special: null }
  const sp = specials && Object.prototype.hasOwnProperty.call(specials, p.date) ? specials[p.date] : null
  if (sp) {
    const inside = sp.from != null && sp.to != null && p.minutes >= sp.from && p.minutes < sp.to
    return inside ? { ...base, state: 'OPEN', reason: null, special: sp } : { ...base, state: 'CLOSED', reason: 'SPECIAL', special: sp }
  }
  if (p.weekday === 0 || p.weekday === 6) return { ...base, state: 'CLOSED', reason: 'WEEKEND' }
  const hol = holidays?.get(p.date)
  if (hol) return { ...base, state: 'CLOSED', reason: 'HOLIDAY', holiday: hol }
  if (p.minutes >= PRE_OPEN_FROM && p.minutes < OPEN_FROM) return { ...base, state: 'PRE-OPEN', reason: null }
  if (p.minutes >= OPEN_FROM && p.minutes < CLOSE_AT) return { ...base, state: 'OPEN', reason: null }
  return { ...base, state: 'CLOSED', reason: p.minutes < PRE_OPEN_FROM ? 'BEFORE OPEN' : 'AFTER CLOSE' }
}

/**
 * Holiday map from the ECO calendar payload (`/api/market/eco-calendar`): events with kind HOLIDAY,
 * name = the last ' · ' segment of `what` (the same parsing Brief.tsx uses).
 */
export function holidaysFromEco(events: ReadonlyArray<{ date?: unknown; kind?: unknown; what?: unknown }> | null | undefined): Map<string, string> {
  const out = new Map<string, string>()
  for (const e of events ?? []) {
    if (e?.kind !== 'HOLIDAY' || typeof e.date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(e.date)) continue
    const what = typeof e.what === 'string' ? e.what : ''
    out.set(e.date, (what.split(' · ').pop() || 'holiday').trim())
  }
  return out
}

/** The page header's single session label (the header's original wording, now holiday-aware). */
export type HeaderLabel = 'WEEKEND' | 'HOLIDAY' | 'PRE-OPEN' | 'NSE OPEN' | 'CLOSING' | 'CLOSED' | 'MUHURAT' | 'SPECIAL'

export interface HeaderSession {
  label: HeaderLabel
  tone: 'muted' | 'amber' | 'green'
  /** Holiday name when label === 'HOLIDAY'; the special session's name when label is MUHURAT / SPECIAL. */
  holiday: string | null
}

/**
 * The header's label for a session from nseSession(): the same words and colours the header always used, plus
 * HOLIDAY. OPEN and PRE-OPEN map one to one onto the strip's state, so header and strip always agree.
 */
export function headerSession(s: NseSession): HeaderSession {
  if (s.reason === 'SPECIAL' && s.special) return { label: s.special.label, tone: 'amber', holiday: s.special.name }
  if (s.reason === 'WEEKEND') return { label: 'WEEKEND', tone: 'muted', holiday: null }
  if (s.reason === 'HOLIDAY') return { label: 'HOLIDAY', tone: 'muted', holiday: s.holiday }
  if (s.state === 'PRE-OPEN') return { label: 'PRE-OPEN', tone: 'amber', holiday: null }
  if (s.state === 'OPEN') return { label: 'NSE OPEN', tone: 'green', holiday: null }
  if (s.reason === 'AFTER CLOSE' && s.istMinutes < CLOSING_UNTIL) return { label: 'CLOSING', tone: 'amber', holiday: null }
  return { label: 'CLOSED', tone: 'muted', holiday: null }
}
