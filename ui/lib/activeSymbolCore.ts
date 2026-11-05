/**
 * The pure half of lib/activeSymbol.ts (no React, no imports): keys, parse / merge / newest-wins, read and write over
 * two Storage-like layers. Unit-tested under plain node by ui/components/vol/__tests__/terminal_v2.check.ts;
 * lib/activeSymbol.ts re-exports everything here and adds the React hook.
 */

export const ACTIVE_SYMBOL_KEY = 'activeSymbol.v1'
export const ACTIVE_SYMBOL_WINDOW_KEY = 'activeSymbol.window.v1'
export const ACTIVE_SYMBOL_EVENT = 'suryadhana:active-symbol'

export interface ActiveSymbol {
  symbol: string
  /** ISO expiry picked on OMON, when any */
  expiry: string | null
  /** strikes picked on the chain (≤ 4), ascending */
  strikes: number[]
  /** ISO time of the pick (the newest wins across layers) */
  at: string
}

export const SYMBOL_RE = /^[A-Z0-9&_.-]{1,20}$/
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/

interface StorageLike { getItem(k: string): string | null; setItem(k: string, v: string): void; removeItem?(k: string): void }

function local(): StorageLike | null { try { return typeof window !== 'undefined' ? window.localStorage : null } catch { return null } }
function session(): StorageLike | null { try { return typeof window !== 'undefined' ? window.sessionStorage : null } catch { return null } }

/** Upper-cased valid symbol or null. */
export function normalizeSymbol(s: unknown): string | null {
  if (typeof s !== 'string') return null
  const t = s.trim().toUpperCase().replace(/\.(NS|BO)$/, '')
  return SYMBOL_RE.test(t) ? t : null
}

/** A stored value → ActiveSymbol, or null when malformed (a corrupt value never crashes a page). */
export function parseActiveSymbol(raw: string | null | undefined): ActiveSymbol | null {
  if (!raw) return null
  try {
    const o = JSON.parse(raw) as Partial<ActiveSymbol> | null
    if (!o || typeof o !== 'object') return null
    const symbol = normalizeSymbol(o.symbol)
    if (!symbol) return null
    const strikes = Array.isArray(o.strikes)
      ? [...new Set(o.strikes.filter((k): k is number => typeof k === 'number' && Number.isFinite(k) && k > 0))].sort((a, b) => a - b).slice(0, 4)
      : []
    return {
      symbol,
      expiry: typeof o.expiry === 'string' && ISO_DAY.test(o.expiry) ? o.expiry : null,
      strikes,
      at: typeof o.at === 'string' && Number.isFinite(Date.parse(o.at)) ? o.at : '1970-01-01T00:00:00.000Z',
    }
  } catch {
    return null
  }
}

/** The newer of two values (by `at`); either may be null. */
export function newerActive(a: ActiveSymbol | null, b: ActiveSymbol | null): ActiveSymbol | null {
  if (!a) return b
  if (!b) return a
  return Date.parse(b.at) > Date.parse(a.at) ? b : a
}

/** What a page reads: this window's pick when it is the newest, else the synced default. */
export function readActiveSymbol(win: StorageLike | null = session(), shared: StorageLike | null = local()): ActiveSymbol | null {
  let w: ActiveSymbol | null = null, s: ActiveSymbol | null = null
  try { w = parseActiveSymbol(win?.getItem(ACTIVE_SYMBOL_WINDOW_KEY)) } catch { w = null }
  try { s = parseActiveSymbol(shared?.getItem(ACTIVE_SYMBOL_KEY)) } catch { s = null }
  return newerActive(w, s)
}

/** Merge a pick over the current value; a new symbol drops the old expiry / strikes (they belonged to the old chain). */
export function mergeActive(current: ActiveSymbol | null, patch: { symbol?: string; expiry?: string | null; strikes?: number[] | null }, at: string): ActiveSymbol | null {
  const symbol = normalizeSymbol(patch.symbol ?? current?.symbol)
  if (!symbol) return null
  const sameSymbol = current?.symbol === symbol
  const base: ActiveSymbol = sameSymbol && current ? current : { symbol, expiry: null, strikes: [], at }
  const next: ActiveSymbol = {
    symbol,
    expiry: patch.expiry === undefined ? base.expiry : (patch.expiry && ISO_DAY.test(patch.expiry) ? patch.expiry : null),
    strikes: patch.strikes === undefined ? base.strikes : [...new Set((patch.strikes ?? []).filter(k => Number.isFinite(k) && k > 0))].sort((a, b) => a - b).slice(0, 4),
    at,
  }
  return next
}

/** Write a pick to both layers and tell this window's pages. */
export function writeActiveSymbol(patch: { symbol?: string; expiry?: string | null; strikes?: number[] | null },
                                  win: StorageLike | null = session(), shared: StorageLike | null = local(), now: Date = new Date()): ActiveSymbol | null {
  const next = mergeActive(readActiveSymbol(win, shared), patch, now.toISOString())
  if (!next) return null
  const raw = JSON.stringify(next)
  try { win?.setItem(ACTIVE_SYMBOL_WINDOW_KEY, raw) } catch { /* storage unavailable */ }
  try { shared?.setItem(ACTIVE_SYMBOL_KEY, raw) } catch { /* storage unavailable */ }
  try { window.dispatchEvent(new CustomEvent<ActiveSymbol>(ACTIVE_SYMBOL_EVENT, { detail: next })) } catch { /* no DOM */ }
  return next
}
