/**
 * Which localStorage keys a window event says changed OUTSIDE the component that listens (multi-window, C3-02).
 *
 * Two sources reach a page:
 *  - a native 'storage' event: ANOTHER window of this origin wrote localStorage (two app windows after ⌘N or a
 *    session restore, two browser tabs). Browsers never deliver it to the window that wrote. `key === null`
 *    means that window called localStorage.clear(); events for sessionStorage are ignored;
 *  - the prefs sync engine after it applied a newer SERVER value in this window (sync.ts dispatchApplied): a
 *    synthetic 'storage' event per key AND 'suryadhana:prefs-changed' {keys}. Both fire for one change, so a
 *    consumer must be idempotent (useExternalPrefChange coalesces them into one call).
 *
 * Pure (no DOM globals): unit-tested by ui/lib/__tests__/prefs.check.ts.
 */
import { PREFS_CHANGED_EVENT } from './sync'

/** `all` = every key may have changed (localStorage.clear() in another window, or a key-less 'storage' event). */
export type ExternalChange = { all: true } | { all: false; keys: readonly string[] }

/** The parts of a StorageEvent / CustomEvent this module reads. */
export interface ChangeEventLike {
  type: string
  key?: unknown
  storageArea?: unknown
  detail?: unknown
}

/**
 * The change an event describes, or null when it is not a localStorage change at all. `localArea` is this
 * page's `window.localStorage` (null when storage is blocked): a 'storage' event for any other area
 * (sessionStorage) is not ours.
 */
export function externalChange(ev: ChangeEventLike, localArea: unknown): ExternalChange | null {
  if (ev.type === 'storage') {
    if (ev.storageArea != null && localArea != null && ev.storageArea !== localArea) return null
    return typeof ev.key === 'string' ? { all: false, keys: [ev.key] } : { all: true }
  }
  if (ev.type === PREFS_CHANGED_EVENT) {
    const keys = (ev.detail as { keys?: unknown } | null | undefined)?.keys
    if (!Array.isArray(keys)) return null
    return { all: false, keys: keys.filter((k): k is string => typeof k === 'string') }
  }
  return null
}

/** True when `change` touches at least one of `watched`. */
export function affects(change: ExternalChange | null, watched: readonly string[]): boolean {
  if (!change) return false
  if (change.all) return true
  return change.keys.some((k) => watched.includes(k))
}

/** The event target the subscription listens on (`window` in the app; a fake EventTarget in the checks). */
export interface ListenTarget {
  addEventListener(type: string, cb: (e: Event) => void): void
  removeEventListener(type: string, cb: (e: Event) => void): void
}

/**
 * The core of useExternalPrefChange (useExternalChange.ts), without React, so the coalescing, filtering and
 * listener-lifetime rules are unit-tested under plain node (round-1 leftover of C3-02):
 *  - listens to 'storage' (another window wrote; ignores other storage areas) and PREFS_CHANGED_EVENT (the sync
 *    engine applied a newer server value here), only for `watched` keys (clear() = every key);
 *  - the engine fires BOTH for one change, so calls are coalesced into one per microtask (`schedule`);
 *  - a throwing callback never breaks the other listeners; the returned function removes both listeners, and a
 *    call already queued when it runs is dropped.
 */
export function subscribeExternalPrefChange(
  target: ListenTarget,
  watched: readonly string[],
  cb: () => void,
  localArea: unknown,
  schedule: (fn: () => void) => void = (fn) => queueMicrotask(fn),
): () => void {
  let queued = false
  let live = true
  const on = (e: Event) => {
    if (!live || !affects(externalChange(e as unknown as ChangeEventLike, localArea), watched)) return
    if (queued) return
    queued = true
    schedule(() => {
      queued = false
      if (!live) return
      try {
        cb()
      } catch {
        /* a consumer bug must not break the other listeners */
      }
    })
  }
  target.addEventListener('storage', on)
  target.addEventListener(PREFS_CHANGED_EVENT, on)
  return () => {
    live = false
    target.removeEventListener('storage', on)
    target.removeEventListener(PREFS_CHANGED_EVENT, on)
  }
}
