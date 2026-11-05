'use client'

/**
 * One pin list for the whole terminal. Pins made on any chart (Stocks, LW Scanner, Glass-Box,
 * Commodity…) and in the News Terminal share this store, so a pinned instrument always shows
 * in the News Terminal's PINNED list with its chart and live headlines.
 *
 * Storage keeps the News Terminal's original key and shape (PinnedPick keyed by Yahoo symbol),
 * so pins made before this change are kept. Every tab listens for changes, so pinning in one
 * place updates the others immediately.
 */
import { useCallback, useEffect, useState } from 'react'
import type { NewsSymbol, Pick, PinnedPick } from '@/components/news/types'
import { useExternalPrefChange } from '@/lib/prefs/useExternalChange'

export const PIN_KEY = 'newsTerminal.pins.v1'
const CHANGE_EVENT = 'suryadhana:pins'

export function loadPins(): Record<string, PinnedPick> {
  try { return JSON.parse(localStorage.getItem(PIN_KEY) || '{}') } catch { return {} }
}

export function savePins(pins: Record<string, PinnedPick>): void {
  try { localStorage.setItem(PIN_KEY, JSON.stringify(pins)) } catch { /* storage unavailable */ }
  window.dispatchEvent(new Event(CHANGE_EVENT))
}

/** A pin for an instrument that did not come from a news scan. */
export function pinFor(symbol: NewsSymbol, name: string, from: string): PinnedPick {
  const pick: Pick = {
    raw_ticker: symbol.base, symbol, company_name: name || symbol.base, exchange: symbol.exchange,
    news: [], news_text: '', sources: [], catalyst_category: `Pinned from ${from}`,
    market_consensus_gap: null, reflexivity_thesis: '', thesis_steps: [], conviction_score: 0,
  }
  const now = new Date()
  return { pick, scan_date: now.toISOString().slice(0, 10), pinned_at: now.toISOString() }
}

export function usePins() {
  const [pins, setPins] = useState<Record<string, PinnedPick>>({})
  useEffect(() => {
    const sync = () => setPins(loadPins())
    sync()
    window.addEventListener(CHANGE_EVENT, sync)
    return () => window.removeEventListener(CHANGE_EVENT, sync)
  }, [])
  // other windows / browser tabs, and server values applied by the prefs sync. Only the pin key: every other
  // storage write (the sync engine's bookkeeping, other settings) used to re-render every pin consumer.
  useExternalPrefChange(PIN_KEY, () => setPins(loadPins()))
  /** Pin with `make()` if not pinned, otherwise unpin. Reads storage fresh to avoid races. */
  const toggle = useCallback((key: string, make: () => PinnedPick) => {
    const next = loadPins()
    if (next[key]) delete next[key]
    else next[key] = make()
    savePins(next)
  }, [])
  return { pins, isPinned: (key: string) => !!pins[key], toggle }
}
