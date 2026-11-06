'use client'

/**
 * The owner's page-strip order (M37): read from the SYNC prefs key `strip.order.v1` (components/shell/stripOrder.ts),
 * re-read when another window / the server changes it (lib/prefs/useExternalChange) or this window's editor writes
 * it. A write goes to localStorage; the prefs write-through stores it on ui-api, so every window and device follow.
 */
import { useCallback, useEffect, useState } from 'react'
import { useExternalPrefChange } from '@/lib/prefs/useExternalChange'
import { DEFAULT_STRIP, STRIP_ORDER_EVENT, STRIP_ORDER_KEY, isDefaultStrip, resolveStrip } from './stripOrder'

function readRaw(): string | null {
  try { return window.localStorage.getItem(STRIP_ORDER_KEY) } catch { return null }
}

export function useStripOrder(known: readonly string[]): [string[], (next: readonly string[] | null) => void] {
  const knownKey = known.join(',')
  const [strip, setStrip] = useState<string[]>(() => (typeof window === 'undefined' ? [...DEFAULT_STRIP] : resolveStrip(readRaw(), known)))
  const adopt = useCallback(() => {
    const next = resolveStrip(readRaw(), knownKey.split(','))
    setStrip(prev => (prev.join(',') === next.join(',') ? prev : next))
  }, [knownKey])
  useEffect(() => {
    adopt()
    window.addEventListener(STRIP_ORDER_EVENT, adopt)
    return () => window.removeEventListener(STRIP_ORDER_EVENT, adopt)
  }, [adopt])
  useExternalPrefChange(STRIP_ORDER_KEY, adopt)
  /** Store a new order (null or the default order = back to the default: the key is removed). */
  const write = useCallback((next: readonly string[] | null) => {
    try {
      if (!next || isDefaultStrip(next)) window.localStorage.removeItem(STRIP_ORDER_KEY)
      else window.localStorage.setItem(STRIP_ORDER_KEY, JSON.stringify(next))
    } catch { /* storage blocked: this window only */ }
    try { window.dispatchEvent(new Event(STRIP_ORDER_EVENT)) } catch { /* no DOM */ }
    if (!next) setStrip([...DEFAULT_STRIP])
  }, [])
  return [strip, write]
}
