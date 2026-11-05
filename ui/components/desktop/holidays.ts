'use client'

/**
 * NSE trading holidays for the session clock, shared by every consumer on the page (the desktop title strip, the
 * page header and the live-feed chips), so one window makes ONE request per IST date. The request is BRIEF's own
 * ECO-calendar query (lib/api.ts getEcoCalendar(0, 7): NSE's holiday master via ui-api, ~1 kB, served from cache),
 * and getEcoCalendar shares that query's response with BRIEF, so a BRF page load makes it once, not three times.
 * Only today's entry is read (session.ts), so the 7-day window is enough. While the API fails it retries every
 * 2 min as long as something still listens (rules: holidayStore.ts). Until holidays are known the session
 * degrades to the weekday rule (session.ts).
 */
import { useEffect, useState } from 'react'
import { ECO_SHARED_QUERY, getEcoCalendar } from '@/lib/api'
import { holidaysFromEco } from './session'
import { createHolidayStore } from './holidayStore'

export const RETRY_MS = 120_000

const store = createHolidayStore({
  fetchEvents: () => getEcoCalendar(ECO_SHARED_QUERY.back, ECO_SHARED_QUERY.ahead).then(r => (r?.data as { events?: unknown } | undefined)?.events),
  parse: events => holidaysFromEco(Array.isArray(events) ? events : []),
  setTimer: (fn, ms) => setTimeout(fn, ms),
  clearTimer: t => clearTimeout(t as ReturnType<typeof setTimeout>),
  retryMs: RETRY_MS,
})

/** Holidays (ISO date → name) for the 7 days from `istDate`, or null while unknown. Refetched per IST date. */
export function useNseHolidays(istDate: string): ReadonlyMap<string, string> | null {
  const [, setTick] = useState(0)
  useEffect(() => {
    const off = store.subscribe(() => setTick(t => t + 1))
    store.load(istDate)
    return off
  }, [istDate])
  return store.get(istDate)
}
