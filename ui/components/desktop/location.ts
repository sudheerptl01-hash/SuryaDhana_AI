/**
 * Location change notifications for the desktop strip. page.tsx keeps the current page in `?tab=` with
 * `history.replaceState` (setView) and nothing fires an event for that, so this module wraps
 * history.pushState / history.replaceState once (call-through, return value preserved) and re-dispatches
 * `suryadhana:location` on window; popstate is forwarded too. Consumers should still re-read location on a slow
 * tick (PlatformShell does, every second): if anything later replaces the history methods without calling
 * through, the strip is at most one second late, never wrong.
 */

export const LOCATION_EVENT = 'suryadhana:location' as const

const WRAPPED = '__suryadhanaLocationWrapped'

type HistoryFn = History['pushState']

function wrap(fn: HistoryFn): HistoryFn {
  if ((fn as unknown as Record<string, unknown>)[WRAPPED]) return fn
  const wrapped = function (this: History, ...args: Parameters<HistoryFn>) {
    const result = fn.apply(this, args)
    try {
      window.dispatchEvent(new Event(LOCATION_EVENT))
    } catch {
      /* never break navigation */
    }
    return result
  } as HistoryFn
  Object.defineProperty(wrapped, WRAPPED, { value: true })
  return wrapped
}

let popstateBound = false

/** Idempotent; safe to call from every mount (React strict mode, HMR). */
export function installLocationWatcher(): void {
  if (typeof window === 'undefined' || !window.history) return
  try {
    window.history.pushState = wrap(window.history.pushState)
    window.history.replaceState = wrap(window.history.replaceState)
  } catch {
    /* a locked-down history object: the 1 s re-read still works */
  }
  if (!popstateBound) {
    popstateBound = true
    window.addEventListener('popstate', () => window.dispatchEvent(new Event(LOCATION_EVENT)))
  }
}

/** Subscribe to location changes. Returns the unsubscribe function. */
export function onLocationChange(cb: () => void): () => void {
  if (typeof window === 'undefined') return () => {}
  window.addEventListener(LOCATION_EVENT, cb)
  return () => window.removeEventListener(LOCATION_EVENT, cb)
}
