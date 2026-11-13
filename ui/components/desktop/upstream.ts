/**
 * Upstream (data-service) health model for the shell strip (O-F5a, RISK §b; D-BOOT).
 *
 * ui-api can be up while data-service is still starting (the 13 Nov cold-boot incident) or while DuckDB is
 * READ-ONLY (a stale write lock). The shell polls ONE cheap ui-api endpoint (`/api/health/upstream`, 1 s probe,
 * 5 s server cache) and shows one calm terminal-wide strip instead of 43 panels of raw transport errors.
 *
 * Precedence (applied by PlatformShell, not here): LINK DOWN > WARMING UP > DB READ-ONLY > STAND DOWN.
 *
 * Pure + DOM-free so Node runs the checks directly (`node ui/components/desktop/__tests__/upstream.check.ts`);
 * the React half (the poller hook + the strip) lives in ShellNotices.tsx.
 */

export const UPSTREAM_URL = '/api/health/upstream'

export type UpstreamState = 'unknown' | 'ok' | 'warming' | 'readonly'

/** What one successful GET of UPSTREAM_URL said. */
export interface UpstreamProbeResult {
  dataService: 'up' | 'down'
  dbReadOnly: boolean
}

export interface UpstreamSnapshot {
  state: UpstreamState
  /** Consecutive probes that saw data-service down (drives the 5 → 10 → 15 s backoff copy). */
  downCount: number
  /** Date.now() when the current state began. */
  since: number
  /** Date.now() of the next scheduled probe (drives the strip's "retry in N s"); null while unscheduled. */
  nextProbeAt: number | null
}

/** Cadences (RISK §b): warming retries 5 → 10 → 15 s; READ-ONLY re-probes every 30 s; healthy stays cheap. */
export const UPSTREAM_OK_INTERVAL_MS = 15_000
export const UPSTREAM_WARMING_BACKOFF_MS = [5_000, 10_000, 15_000] as const
export const UPSTREAM_READONLY_INTERVAL_MS = 30_000
export const UPSTREAM_UNKNOWN_INTERVAL_MS = 10_000

/** Strip copy, SPEC verbatim (RISK §b table). No direction words, no blame, no raw transport text. */
export const WARMING_TAG = 'WARMING UP'
export const WARMING_MAIN = 'market data service is starting'
export const WARMING_DETAIL = 'panels fill in as it answers'
export const READONLY_TAG = 'DB READ-ONLY'
export const READONLY_MAIN = 'showing stored data; tonight’s ingest is paused until the lock clears'
export const READONLY_DETAIL = 'the watchdog fixes start order'

export function initialUpstream(now = 0): UpstreamSnapshot {
  return { state: 'unknown', downCount: 0, since: now, nextProbeAt: null }
}

/**
 * State after one probe. `probe: null` means the request itself failed or the route does not exist yet
 * (ui-api down → ConnectionBanner's territory; an older ui-api build → no signal): never a strip of its own.
 */
export function reduceUpstreamProbe(prev: UpstreamSnapshot, probe: UpstreamProbeResult | null, now: number): UpstreamSnapshot {
  if (!probe) {
    return { state: 'unknown', downCount: 0, since: prev.state === 'unknown' ? prev.since : now, nextProbeAt: null }
  }
  if (probe.dataService === 'down') {
    return { state: 'warming', downCount: prev.downCount + 1, since: prev.state === 'warming' ? prev.since : now, nextProbeAt: null }
  }
  const state: UpstreamState = probe.dbReadOnly ? 'readonly' : 'ok'
  return { state, downCount: 0, since: prev.state === state ? prev.since : now, nextProbeAt: null }
}

/** Delay until the next probe for a snapshot (pure; the hook schedules with it). */
export function upstreamDelayMs(s: UpstreamSnapshot): number {
  if (s.state === 'warming') {
    const i = Math.min(Math.max(s.downCount - 1, 0), UPSTREAM_WARMING_BACKOFF_MS.length - 1)
    return UPSTREAM_WARMING_BACKOFF_MS[i]
  }
  if (s.state === 'readonly') return UPSTREAM_READONLY_INTERVAL_MS
  if (s.state === 'unknown') return UPSTREAM_UNKNOWN_INTERVAL_MS
  return UPSTREAM_OK_INTERVAL_MS
}

/** Which strip (if any) this snapshot asks for; LINK DOWN precedence is PlatformShell's. */
export function upstreamStripKind(s: UpstreamSnapshot): 'warming' | 'readonly' | null {
  return s.state === 'warming' ? 'warming' : s.state === 'readonly' ? 'readonly' : null
}

/**
 * True when data-service just came back from warming: panels whose one-shot load failed during the warm-up
 * reload through the SAME path as after a ui-api outage (lib/reconnect.ts RECONNECTED_EVENT; each page scans
 * its own text). readonly → ok is NOT a recovery (reads worked throughout).
 */
export function upstreamRecovered(prev: UpstreamSnapshot, next: UpstreamSnapshot): boolean {
  return prev.state === 'warming' && (next.state === 'ok' || next.state === 'readonly')
}

// ── module store: the latest verdict for ANY component (UPDATE DATA's read-only reason, panels) ──────────
let current: UpstreamSnapshot = initialUpstream()
const listeners = new Set<(s: UpstreamSnapshot) => void>()

export function latestUpstream(): UpstreamSnapshot { return current }

export function publishUpstream(s: UpstreamSnapshot): void {
  current = s
  for (const cb of listeners) {
    try { cb(s) } catch { /* a listener must never break the publisher */ }
  }
}

export function subscribeUpstream(cb: (s: UpstreamSnapshot) => void): () => void {
  listeners.add(cb)
  return () => { listeners.delete(cb) }
}
