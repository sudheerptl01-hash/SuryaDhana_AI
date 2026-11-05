'use client'

import { useEffect, useState } from 'react'
import { getSurveillance, type RiskFlags } from '@/lib/api'

// NSE's surveillance files change once a day: share one answer per symbol set for 30 minutes
const memo = new Map<string, { at: number; flags: Record<string, RiskFlags> }>()

/** NSE surveillance / risk flags for a set of symbols (ASM, GSM, ESM, IRP, tight band, T2T, F&O ban). */
export function useSurveillance(symbols: string[]): Record<string, RiskFlags> {
  const key = [...new Set(symbols.map(s => s.toUpperCase()))].sort().join(',')
  const [flags, setFlags] = useState<Record<string, RiskFlags>>(() => memo.get(key)?.flags ?? {})
  useEffect(() => {
    if (!key) { setFlags({}); return }
    const hit = memo.get(key)
    if (hit && Date.now() - hit.at < 30 * 60_000) { setFlags(hit.flags); return }
    let live = true
    getSurveillance(key.split(',')).then(r => {
      memo.set(key, { at: Date.now(), flags: r.data.flags })
      if (live) setFlags(r.data.flags)
    }).catch(() => {})
    return () => { live = false }
  }, [key])
  return flags
}
