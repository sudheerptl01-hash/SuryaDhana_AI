'use client'

import { useEffect, useState } from 'react'
import { getFinancialsLatest, prefetchFinancials, type FinLatest } from '@/lib/api'

/**
 * Latest quarter + valuation for a set of NSE symbols (cached results filings, no NSE call on read). Companies
 * not read yet are queued once for a background read (unless `prefetch: false`, e.g. long calendars), and the hook
 * polls every 15 s (up to ~3 min) until they arrive. Returns the map and how many are still pending.
 */
export function useFinancialsLatest(symbols: string[], opts: { prefetch?: boolean } = {}): { fin: Record<string, FinLatest>; pending: number } {
  const prefetch = opts.prefetch ?? true
  const [fin, setFin] = useState<Record<string, FinLatest>>({})
  const key = [...new Set(symbols.map(s => s.toUpperCase()))].sort().join(',')
  useEffect(() => {
    const syms = key.split(',').filter(Boolean)
    if (!syms.length) { setFin({}); return }
    let live = true, tries = 0
    let iv: ReturnType<typeof setInterval> | null = null
    const load = () => getFinancialsLatest(syms).then(r => {
      if (!live) return
      setFin(r.data.latest)
      const missing = syms.filter(x => !r.data.latest[x])
      if (prefetch && tries === 0 && missing.length) prefetchFinancials(missing).catch(() => {})
      if ((!prefetch || !missing.length || ++tries > 12) && iv) { clearInterval(iv); iv = null }
    }).catch(() => {})
    load(); iv = setInterval(load, 15_000)
    return () => { live = false; if (iv) clearInterval(iv) }
  }, [key, prefetch])
  const pending = key.split(',').filter(s => s && !fin[s]).length
  return { fin, pending }
}
