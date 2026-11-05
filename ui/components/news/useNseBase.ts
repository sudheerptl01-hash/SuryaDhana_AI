'use client'

/**
 * useNseBase — the stored half of WTCH's and the news dock's NSE rows (name, one-month spark, 52-week range) from NSE's
 * own stored closes, one request per ≤ 300 symbols (GET /api/market/closes, L2-API), re-read every 10 min; the last good
 * answer is kept through an error. Rules in ./nseBase.ts (pure, node-tested). Never a Yahoo request.
 */
import { useEffect, useRef, useState } from 'react'
import { getMarketCloses } from '@/lib/api'
import { BASE_CHUNK, BASE_DAYS, BASE_REFRESH_MS, nseBaseFromCloses, nseCode, type NseBase } from './nseBase'

export type NseBaseStatus = 'idle' | 'loading' | 'ok' | 'error' | 'missing'

export interface NseBaseResult {
  base: Record<string, NseBase | null>
  status: NseBaseStatus
  /** the newest stored session over the answered rows */
  asOf: string | null
  error: string | null
}

export function useNseBase(symbols: readonly string[], opts: { enabled?: boolean } = {}): NseBaseResult {
  const enabled = opts.enabled !== false
  const key = enabled ? [...new Set(symbols.map(s => nseCode(s)).filter((s): s is string => !!s))].sort().join(',') : ''
  const [state, setState] = useState<NseBaseResult>({ base: {}, status: 'idle', asOf: null, error: null })
  const seq = useRef(0)
  useEffect(() => {
    if (!key) { setState(s => (s.status === 'idle' ? s : { base: {}, status: 'idle', asOf: null, error: null })); return }
    const syms = key.split(',')
    let alive = true
    const pull = async () => {
      const mine = ++seq.current
      setState(s => (s.status === 'idle' ? { ...s, status: 'loading' } : s))
      const got: Record<string, NseBase | null> = {}
      let err: string | null = null, missing = false
      for (let i = 0; i < syms.length; i += BASE_CHUNK) {
        const chunk = syms.slice(i, i + BASE_CHUNK)
        try {
          Object.assign(got, nseBaseFromCloses((await getMarketCloses(chunk, BASE_DAYS)).data, chunk))
        } catch (e: unknown) {
          const r = (e as { response?: { status?: number; data?: { detail?: unknown } } })?.response
          missing = missing || (r?.status === 404 && r?.data?.detail === 'Not Found')
          err = r?.status ? `HTTP ${r.status}` : 'closes route unreachable'
        }
      }
      if (!alive || mine !== seq.current) return
      setState(prev => {
        const base = err ? { ...prev.base, ...got } : got                       // an error keeps the last good rows
        const dates = Object.values(base).map(b => b?.last_date).filter((d): d is string => !!d).sort()
        return { base, status: missing ? 'missing' : err ? 'error' : 'ok', asOf: dates.length ? dates[dates.length - 1] : null, error: err }
      })
    }
    void pull()
    const iv = setInterval(() => { void pull() }, BASE_REFRESH_MS)
    return () => { alive = false; clearInterval(iv) }
  }, [key])
  return state
}
