/**
 * Per-symbol flash clearing for the EQS live price cells (RUP-04).
 *
 * A tick flashes its CMP cell green/red for FLASH_MS. The old code set one timer per tick batch and cancelled it
 * in the effect cleanup, which runs before every re-run: a second symbol ticking within 700 ms (or a filter /
 * load-more changing the table's tickers) cancelled the first symbol's clear, so its cell stayed tinted until it
 * ticked again. Here every symbol owns exactly one pending clear: a new tick of that symbol restarts only its
 * own timer, other symbols' timers are never touched, and `dispose()` (unmount) cancels them all.
 *
 * Pure module (no React, no imports; timers injectable): unit-tested by ui/components/__tests__/pages.check.ts
 * under plain node with a fake clock.
 */

export const FLASH_MS = 700

type Handle = unknown
export interface Timers {
  set(fn: () => void, ms: number): Handle
  clear(h: Handle): void
}

export interface FlashClock {
  /** `sym` just flashed: clear it FLASH_MS from now (restarting only its own pending clear) */
  flashed(sym: string): void
  /** symbols with a clear still pending */
  pending(): string[]
  /** cancel every pending clear (unmount) */
  dispose(): void
}

const realTimers: Timers = {
  set: (fn, ms) => setTimeout(fn, ms),
  clear: h => clearTimeout(h as ReturnType<typeof setTimeout>),
}

/** `clear(sym)` runs once per flash, FLASH_MS after that symbol's latest tick. */
export function createFlashClock(clear: (sym: string) => void, ms: number = FLASH_MS, timers: Timers = realTimers): FlashClock {
  const pendingBySym = new Map<string, Handle>()
  return {
    flashed(sym) {
      const old = pendingBySym.get(sym)
      if (old !== undefined) timers.clear(old)
      pendingBySym.set(sym, timers.set(() => { pendingBySym.delete(sym); clear(sym) }, ms))
    },
    pending: () => [...pendingBySym.keys()],
    dispose() {
      for (const h of pendingBySym.values()) timers.clear(h)
      pendingBySym.clear()
    },
  }
}
