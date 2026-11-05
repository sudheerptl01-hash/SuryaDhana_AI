/**
 * The active-symbol store (reports/terminal_v2/PLAN.md 1.3 "chain-first OMON", R-UI #4): one place that remembers
 * the underlying (and, from OMON, the expiry and the strikes the trader picked) so OMON → "OPEN IN OSTR" → the
 * builder never asks for the symbol again.
 *
 * Two layers:
 *  - per window (sessionStorage `activeSymbol.window.v1`): two terminal windows can look at different underlyings;
 *  - synced default (localStorage `activeSymbol.v1`, PLAN 2.6's prefs key): the last pick on any window / device
 *    seeds a new window. The key is a SYNC key in lib/prefs/keys.ts, so the prefs engine stores it on ui-api and
 *    every window / the desktop app / the browser share it.
 *
 * Pure parse / merge functions live in lib/activeSymbolCore.ts (unit-tested by ui/components/vol/__tests__/terminal_v2.check.ts); the
 * hook follows lib/prefs/useExternalChange's rule (re-read on an external write, never echo an adopted value).
 */
import { useCallback, useEffect, useState } from 'react'
import { useExternalPrefChange } from '@/lib/prefs/useExternalChange'
import { ACTIVE_SYMBOL_EVENT, ACTIVE_SYMBOL_KEY, readActiveSymbol, writeActiveSymbol, type ActiveSymbol } from './activeSymbolCore'

export * from './activeSymbolCore'

/** The active symbol for a page, re-read on this window's picks and on another window's / the server's writes. */
export function useActiveSymbol(): [ActiveSymbol | null, (patch: { symbol?: string; expiry?: string | null; strikes?: number[] | null }) => ActiveSymbol | null] {
  const [value, setValue] = useState<ActiveSymbol | null>(() => (typeof window === 'undefined' ? null : readActiveSymbol()))
  const adopt = useCallback(() => {
    const v = readActiveSymbol()
    setValue(prev => (JSON.stringify(prev) === JSON.stringify(v) ? prev : v))
  }, [])
  useEffect(() => {
    window.addEventListener(ACTIVE_SYMBOL_EVENT, adopt)
    return () => window.removeEventListener(ACTIVE_SYMBOL_EVENT, adopt)
  }, [adopt])
  useExternalPrefChange(ACTIVE_SYMBOL_KEY, adopt)
  const write = useCallback((patch: { symbol?: string; expiry?: string | null; strikes?: number[] | null }) => writeActiveSymbol(patch), [])
  return [value, write]
}
