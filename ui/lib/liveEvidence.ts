/**
 * Live-market evidence shared by every chip of a window (R-UI-SHELL-03, tightened in round 4b):
 *  - when the last LIVE monitor-socket tick arrived. AppProvider (context/AppContext.tsx) hands every socket message
 *    to noteQuoteMessage; only a quote whose own exchange time is fresh and that is a new print for its symbol
 *    counts (lib/feedState.ts quotePrint / isLivePrint). Heartbeat replies, subscription acks, errors and the
 *    previous session's quotes (data-service keeps publishing ICICI REST quotes on a weekday NSE holiday) never do,
 *    so a holiday never reads LIVE / STREAMING. components/shell/useFeed.ts reads it, so a session the calendar does
 *    not know (a special session) reads live once real prints flow;
 *  - NSE's latest index stamp ("23-Oct-2026 15:30", /api/market/nifty-live, noted by the header's NIFTY poll), so
 *    the stock window can say CLOSE 23-OCT, or DELAYED while NSE prints, without a request of its own (CT-07).
 * No React, no DOM; the rules are lib/feedState.ts (unit-tested in desktop.check).
 */
import { isLivePrint, isLiveTick, quotePrint } from './feedState'

let lastTickAt = 0
const listeners = new Set<() => void>()
/** The last print key seen per symbol (bounded: a window watches at most a few hundred symbols). */
const prints = new Map<string, string>()
const PRINTS_MAX = 2000

/** Record a live tick at `now`. Listeners hear only the edge from "no recent tick" to "ticking" (not every tick). */
export function noteLiveTick(now: number = Date.now()): void {
  const was = isLiveTick(lastTickAt, now)
  lastTickAt = now
  if (was) return
  for (const l of listeners) {
    try {
      l()
    } catch {
      /* a listener must not break the socket callback */
    }
  }
}

/**
 * Every monitor-socket message goes through here. Returns true (and notes a live tick) only for a quote with a fresh
 * exchange time that differs from the previous print of its symbol; everything else is remembered or ignored.
 */
export function noteQuoteMessage(msg: unknown, now: number = Date.now()): boolean {
  const p = quotePrint(msg)
  if (!p) return false
  const prev = prints.get(p.sym)
  if (prints.size >= PRINTS_MAX && prev === undefined) prints.clear()
  prints.set(p.sym, p.key)
  if (!isLivePrint(p, prev, now)) return false
  noteLiveTick(now)
  return true
}

/** Epoch ms of the last live tick (0 = none since the window loaded). */
export function lastLiveTickAt(): number {
  return lastTickAt
}

export function subscribeLiveEvidence(cb: () => void): () => void {
  listeners.add(cb)
  return () => {
    listeners.delete(cb)
  }
}

let nsePrint: string | null = null

/** The header's latest NSE index stamp (any string NSE sent; parsed by the readers). */
export function noteNsePrint(asOf: string | null | undefined): void {
  if (typeof asOf === 'string' && asOf.trim()) nsePrint = asOf.trim()
}

/** NSE's latest index stamp seen by this window, or null before the header's first poll. */
export function lastNsePrint(): string | null {
  return nsePrint
}

/** Tests only: forget everything. */
export function resetLiveEvidence(): void {
  lastTickAt = 0
  nsePrint = null
  prints.clear()
}
