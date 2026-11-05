'use client'

/**
 * Upcoming corporate events per NSE symbol (results, ex-dates…), shared across the app with one cached fetch.
 *   const events = useCorpEvents();  events.get('TCS') → [{ kind: 'RESULTS', event_date: '2026-10-14', … }]
 * Source: /api/market/events (EVTS tab). Cached for 10 minutes; past events are dropped.
 */
import { useEffect, useState } from 'react'
import { getMarketEvents, getRecentResults, type CorpEvent, type RecentResult } from '@/lib/api'

const TTL_MS = 10 * 60_000
let cache: { at: number; map: Map<string, CorpEvent[]> } | null = null
let inflight: Promise<Map<string, CorpEvent[]>> | null = null

function todayIso(): string {
  return new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' })
}

async function load(): Promise<Map<string, CorpEvent[]>> {
  if (cache && Date.now() - cache.at < TTL_MS) return cache.map
  inflight ??= getMarketEvents().then(r => {
    const today = todayIso()
    const map = new Map<string, CorpEvent[]>()
    for (const e of r.data.rows) if (e.event_date >= today) map.set(e.symbol, [...(map.get(e.symbol) ?? []), e])
    cache = { at: Date.now(), map }
    return map
  }).finally(() => { inflight = null })
  return inflight
}

export function useCorpEvents(): Map<string, CorpEvent[]> {
  const [map, setMap] = useState<Map<string, CorpEvent[]>>(cache?.map ?? new Map())
  useEffect(() => {
    let live = true
    load().then(m => { if (live) setMap(m) }).catch(() => { /* calendar optional */ })
    return () => { live = false }
  }, [])
  return map
}

/** Days from today (IST) to an ISO date. */
export function daysUntil(iso: string): number {
  return Math.round((new Date(`${iso}T00:00:00`).getTime() - new Date(`${todayIso()}T00:00:00`).getTime()) / 86_400_000)
}

// ── research avoid-flag: strong negative results reaction in the last 60 sessions ─────────────
let avoidCache: { at: number; map: Map<string, RecentResult> } | null = null
let avoidInflight: Promise<Map<string, RecentResult>> | null = null

/** Stocks whose last results reaction was ≤ −5% vs NIFTY within 60 sessions (reports/results_drift: H2 PASS). */
export function useResultsAvoid(): Map<string, RecentResult> {
  const [map, setMap] = useState<Map<string, RecentResult>>(avoidCache?.map ?? new Map())
  useEffect(() => {
    let live = true
    if (avoidCache && Date.now() - avoidCache.at < TTL_MS) { setMap(avoidCache.map); return }
    avoidInflight ??= getRecentResults(95).then(r => {
      const m = new Map<string, RecentResult>()
      for (const x of r.data.rows) if (x.avoid && !m.has(x.symbol)) m.set(x.symbol, x)
      avoidCache = { at: Date.now(), map: m }
      return m
    }).finally(() => { avoidInflight = null })
    avoidInflight.then(m => { if (live) setMap(m) }).catch(() => { /* optional */ })
    return () => { live = false }
  }, [])
  return map
}
