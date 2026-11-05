'use client'

/**
 * useLiveTicks — the terminal's ONLY client of the live-tick snapshot endpoint
 * (`GET /api/quotes/ticks?symbols=…`, ui-api ← data-service Breeze websocket store, program F3.2).
 * The response shape is isolated HERE: if the endpoint or its fields move, this file is the whole diff.
 *
 * Contract (A1): the GET itself ensures the server-side subscription (union + TTL on data-service) —
 * no POST from the frontend, so a restart on either side self-heals within one poll.
 *
 * Behaviour: 2 s poll while the tab is visible and symbols are non-empty; pauses on hidden tabs;
 * on failure backs off 2→4→8→30 s and reports 'offline'; AbortController cancels in-flight polls
 * on unmount/symbol change. Yahoo flows elsewhere are untouched — consumers OVERLAY these ticks.
 *
 * Dev without a broker session: NEXT_PUBLIC_MOCK_TICKS=1 synthesizes a slow random walk.
 */
import { useEffect, useRef, useState } from 'react'
import { normalizeError } from '@/lib/errors'

export type TickState = 'live' | 'delayed' | 'degraded' | 'offline'

export interface LiveTick {
  price: number
  chg_pct: number | null
  prev_close: number | null
  ttq: number | null            // total traded quantity today
  as_of: string | null
  source: 'icici-ws' | 'yahoo' | string
}

export interface LiveTicks {
  state: TickState | null       // null = idle (no symbols requested)
  connected: boolean
  asOf: string | null
  ticks: Record<string, LiveTick>
}

const IDLE: LiveTicks = { state: null, connected: false, asOf: null, ticks: {} }
const POLL_MS = 2_000
const BACKOFF_MS = [2_000, 4_000, 8_000, 30_000]
const MOCK = process.env.NEXT_PUBLIC_MOCK_TICKS === '1'

/* ── the one place that knows the wire shape ───────────────────────────────── */
interface WireTick { price?: number; ltp?: number; chg_pct?: number | null; prev_close?: number | null; ttq?: number | null; as_of?: string | null; source?: string }
interface WireResp { connected?: boolean; state?: string; as_of?: string | null; ticks?: Record<string, WireTick>; error?: unknown; detail?: unknown }

function parse(data: WireResp): LiveTicks {
  const ticks: Record<string, LiveTick> = {}
  for (const [sym, t] of Object.entries(data.ticks ?? {})) {
    const price = t.price ?? t.ltp
    if (typeof price !== 'number') continue
    ticks[sym.toUpperCase()] = { price, chg_pct: t.chg_pct ?? null, prev_close: t.prev_close ?? null,
                                 ttq: t.ttq ?? null, as_of: t.as_of ?? null, source: t.source ?? 'icici-ws' }
  }
  const connected = data.connected === true
  // state: `live` must be EARNED by at least one broker-sourced row (row truth — bloomberg_verdict
  // defect #1b: a connected-but-tickless feed previously lit LIVE·ICICI chips over Yahoo prices).
  // The server speaks UPPERCASE (OFF/CONNECTING/LIVE/DEGRADED/DISCONNECTED); map it, don't trust it blindly.
  const s = typeof data.state === 'string' ? data.state.toLowerCase() : ''
  const hasBrokerRow = Object.values(ticks).some(t => t.source.startsWith('icici'))
  let state: TickState
  if (data.error != null) state = 'degraded'
  else if (s === 'degraded' || s === 'disconnected') state = 'degraded'
  else if (s === 'off' || s === 'offline') state = 'offline'
  else if (hasBrokerRow) state = 'live'
  else state = 'delayed'                      // feed up but first tick pending, or not connected: prices are Yahoo
  return { state, connected, asOf: data.as_of ?? null, ticks }
}
/* ──────────────────────────────────────────────────────────────────────────── */

function mockWalk(syms: string[], prev: LiveTicks): LiveTicks {
  const ticks: Record<string, LiveTick> = {}
  for (const s of syms) {
    const last = prev.ticks[s]?.price ?? 100 + (s.charCodeAt(0) % 40) * 25
    const price = Math.max(1, +(last * (1 + (Math.random() - 0.5) * 0.002)).toFixed(2))
    ticks[s] = { price, chg_pct: +((Math.random() - 0.45) * 2).toFixed(2), prev_close: +(price * 0.99).toFixed(2),
                 ttq: Math.round(Math.random() * 1e6), as_of: new Date().toISOString(), source: 'icici-ws' }
  }
  return { state: 'live', connected: true, asOf: new Date().toISOString(), ticks }
}

/** Poll live ticks for `symbols` (NSE codes, no .NS). Empty list = idle, nothing polled. */
export function useLiveTicks(symbols: string[]): LiveTicks {
  const key = [...new Set(symbols.filter(Boolean).map(s => s.toUpperCase().replace(/\.NS$/, '')))].sort().join(',')
  const [out, setOut] = useState<LiveTicks>(IDLE)
  const outRef = useRef(out); outRef.current = out

  useEffect(() => {
    if (!key) { setOut(IDLE); return }
    let timer: ReturnType<typeof setTimeout> | null = null
    let ctl: AbortController | null = null
    let fails = 0
    let stopped = false

    const tick = async () => {
      if (stopped) return
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') { schedule(POLL_MS); return }
      if (MOCK) { setOut(mockWalk(key.split(','), outRef.current)); schedule(POLL_MS); return }
      ctl = new AbortController()
      try {
        const r = await fetch(`/api/quotes/ticks?symbols=${encodeURIComponent(key)}`, { signal: ctl.signal })
        const body = (await r.json().catch(() => ({}))) as WireResp
        if (!r.ok) {
          const code = normalizeError(body, '').code
          setOut({ ...IDLE, state: code === 'degraded' ? 'degraded' : 'offline' })
          fails++
        } else { setOut(parse(body)); fails = 0 }
      } catch {
        if (stopped) return
        fails++
        setOut(o => ({ ...o, state: 'offline' }))
      }
      schedule(fails ? BACKOFF_MS[Math.min(fails - 1, BACKOFF_MS.length - 1)] : POLL_MS)
    }
    const schedule = (ms: number) => { if (!stopped) timer = setTimeout(tick, ms) }
    const onVisible = () => { if (document.visibilityState === 'visible' && timer) { clearTimeout(timer); tick() } }

    tick()
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
      ctl?.abort()
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [key])

  return out
}
