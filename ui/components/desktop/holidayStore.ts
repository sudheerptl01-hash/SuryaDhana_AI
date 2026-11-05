/**
 * The NSE holiday store behind useNseHolidays (holidays.ts), with its fetcher and timers injected so the retry
 * rules are unit-tested under plain node (`node ui/components/desktop/__tests__/desktop.check.ts`). No imports.
 *
 *  - one entry per IST date; a consumer asking for the current date reuses it (in flight, known, or waiting to
 *    retry); asking for a new date replaces it and cancels the old date's retry;
 *  - a failed load retries after `retryMs` while anything still listens. The timer belongs to its date's entry,
 *    so a failure right after the IST date changes gets its own retry (round-1 leftover: one module-wide timer
 *    from the previous date used to swallow it, leaving holidays unknown for the whole day).
 */

export interface HolidayStoreDeps {
  /** Resolves to the ECO calendar events (any shape; parse() validates). */
  fetchEvents: () => Promise<unknown>
  parse: (events: unknown) => ReadonlyMap<string, string>
  setTimer: (fn: () => void, ms: number) => unknown
  clearTimer: (t: unknown) => void
  retryMs: number
}

interface Entry {
  date: string
  holidays: ReadonlyMap<string, string> | null
  inflight: boolean
  retry: unknown
}

export interface HolidayStore {
  load(date: string): void
  get(date: string): ReadonlyMap<string, string> | null
  subscribe(l: () => void): () => void
  /** Diagnostics for tests: is a retry pending for `date`? */
  retryPending(date: string): boolean
}

export function createHolidayStore(d: HolidayStoreDeps): HolidayStore {
  let entry: Entry | null = null
  const listeners = new Set<() => void>()
  const emit = () => {
    for (const l of listeners) {
      try { l() } catch { /* a listener must not break the others */ }
    }
  }
  const load = (date: string): void => {
    if (entry && entry.date === date && (entry.holidays || entry.inflight || entry.retry != null)) return
    if (entry && entry.retry != null) d.clearTimer(entry.retry)
    const mine: Entry = { date, holidays: null, inflight: true, retry: null }
    entry = mine
    let p: Promise<unknown>
    try { p = d.fetchEvents() } catch (e) { p = Promise.reject(e) }
    p.then(events => {
      mine.inflight = false
      if (entry !== mine) return
      mine.holidays = d.parse(events)
      emit()
    }, () => {
      mine.inflight = false
      if (entry !== mine) return
      mine.retry = d.setTimer(() => {
        mine.retry = null
        if (entry === mine && listeners.size && !mine.holidays) load(date)
      }, d.retryMs)
    })
  }
  return {
    load,
    get: date => (entry && entry.date === date ? entry.holidays : null),
    subscribe: l => {
      listeners.add(l)
      return () => { listeners.delete(l) }
    },
    retryPending: date => !!entry && entry.date === date && entry.retry != null,
  }
}
