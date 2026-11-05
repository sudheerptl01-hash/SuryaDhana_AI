/**
 * One in-flight / recent request per key, shared by every caller on the page (round-1 leftover of C3-06: the
 * page header, the desktop title strip and BRIEF each fetched the ECO calendar on every page load). Pure, no DOM,
 * no imports (unit-tested by `node ui/components/desktop/__tests__/desktop.check.ts`).
 *
 * A cached promise is reused while BOTH hold: same key, same IST calendar date, younger than `ttlMs`. A rejected
 * request is dropped at once, so the next caller retries instead of inheriting the failure.
 */

/** IST calendar date (YYYY-MM-DD) of an epoch-ms instant. IST is a fixed UTC+05:30 (no DST). */
export function istDate(epochMs: number): string {
  return new Date(epochMs + 330 * 60_000).toISOString().slice(0, 10)
}

export interface SharedCache<T> {
  get(key: string, fetcher: () => Promise<T>): Promise<T>
  clear(): void
  readonly size: number
}

export function createSharedCache<T>(opts: { ttlMs: number; now?: () => number }): SharedCache<T> {
  const now = opts.now ?? (() => Date.now())
  const entries = new Map<string, { at: number; day: string; p: Promise<T> }>()
  return {
    get(key, fetcher) {
      const t = now()
      const day = istDate(t)
      const hit = entries.get(key)
      if (hit && hit.day === day && t - hit.at < opts.ttlMs) return hit.p
      const p = fetcher()
      const entry = { at: t, day, p }
      entries.set(key, entry)
      p.catch(() => {
        if (entries.get(key) === entry) entries.delete(key)
      })
      return p
    },
    clear() {
      entries.clear()
    },
    get size() {
      return entries.size
    },
  }
}
