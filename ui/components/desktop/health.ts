/**
 * Browser-mode ui-api health monitor (the desktop app gets the same signal from the shell's status events).
 *
 * Probe (C3-logic-unchanged-09): GET /api/health first. ui-api answers it with the same body as /health, and it is
 * the one path that reaches ui-api through EVERY front server: same origin at :8010 and Next's /api rewrite on
 * :3000 (next dev / next start), so neither origin logs a 404 every 10 s. Fallbacks, each latched for the page's
 * life so a steady state costs one request per probe:
 *  - /api/health answers a JSON 404 (a ui-api without the alias yet): ui-api is alive; probe /health from now on;
 *  - /health answers non-JSON (a front server that does not route it, e.g. :3000 with that older ui-api): ANY
 *    JSON answer from /api/health (ui-api's JSON 404 envelope included, PLAN AC-2) proves ui-api is alive.
 * A 5xx, a network error or a timeout means down, and never changes the latched path.
 *
 * Schedule (cheap by design): every 10 s while up; the first failure is confirmed 2 s later (no banner for a
 * single blip); then down with backoff 5 → 10 → 15 s (cap) so recovery is noticed within 15 s. No probes while
 * the document is hidden; an immediate probe on focus, visibility and `online`.
 */

export type HealthState = 'unknown' | 'up' | 'down'

export interface HealthSnapshot {
  state: HealthState
  /** Consecutive failed probes. */
  failures: number
  /** Date.now() of the last successful probe. */
  lastOkAt: number | null
  /** Date.now() when the current state began. */
  since: number
  /** Round-trip of the last successful probe. */
  latencyMs: number | null
  /** Date.now() of the next scheduled probe (null while hidden/stopped). */
  nextProbeAt: number | null
}

export const UP_INTERVAL_MS = 10_000
export const CONFIRM_DELAY_MS = 2_000
export const PROBE_TIMEOUT_MS = 3_000
const DOWN_BACKOFF_MS = [5_000, 10_000, 15_000] as const

/** Failures needed before the state flips to down (1 = the confirm probe must fail too). */
export const DOWN_AFTER_FAILURES = 2

/** Delay before the next probe given the consecutive failure count (pure; unit-tested). */
export function nextDelayMs(failures: number): number {
  if (failures <= 0) return UP_INTERVAL_MS
  if (failures < DOWN_AFTER_FAILURES) return CONFIRM_DELAY_MS
  const i = Math.min(failures - DOWN_AFTER_FAILURES, DOWN_BACKOFF_MS.length - 1)
  return DOWN_BACKOFF_MS[i]
}

/** State after a probe result (pure; unit-tested). */
export function reduceProbe(prev: HealthSnapshot, ok: boolean, now: number, latencyMs: number | null): HealthSnapshot {
  if (ok) {
    return {
      state: 'up', failures: 0, lastOkAt: now, latencyMs,
      since: prev.state === 'up' ? prev.since : now, nextProbeAt: null,
    }
  }
  const failures = prev.failures + 1
  const state: HealthState = failures >= DOWN_AFTER_FAILURES ? 'down' : prev.state
  return { ...prev, state, failures, since: state !== prev.state ? now : prev.since, nextProbeAt: null }
}

/** 'api' = GET /api/health (first choice) · 'health' = GET /health · 'api-any' = any JSON from /api/health. */
type ProbeMode = 'api' | 'health' | 'api-any'

const isJson = (r: Response) => (r.headers.get('content-type') || '').toLowerCase().includes('json')

async function fetchWithTimeout(url: string, timeoutMs: number): Promise<Response> {
  const ctl = typeof AbortController !== 'undefined' ? new AbortController() : null
  const timer = setTimeout(() => ctl?.abort(), timeoutMs)
  try {
    return await fetch(url, { cache: 'no-store', credentials: 'same-origin', signal: ctl?.signal, headers: { Accept: 'application/json' } })
  } finally {
    clearTimeout(timer)
  }
}

/** One cheap liveness probe. Mutates `mode` along the fallback chain above (never back). */
export async function probeUiApi(state: { mode: ProbeMode }, timeoutMs = PROBE_TIMEOUT_MS): Promise<boolean> {
  try {
    if (state.mode === 'api') {
      const r = await fetchWithTimeout('/api/health', timeoutMs)
      if (r.ok && isJson(r)) return true
      if (r.status >= 500) return false
      state.mode = 'health'
      if (isJson(r)) return true // ui-api's JSON 404 envelope: alive, just without the alias
    }
    if (state.mode === 'health') {
      const r = await fetchWithTimeout('/health', timeoutMs)
      if (r.ok && isJson(r)) return true
      if (r.status >= 500) return false
      state.mode = 'api-any' // HTML / 404 from a front server: fall through to the /api probe
    }
    const r = await fetchWithTimeout('/api/health', timeoutMs)
    return r.status < 500 && isJson(r)
  } catch {
    return false
  }
}

/** Polling monitor with subscribe/start/stop. One instance per page (PlatformShell owns it). */
export class HealthMonitor {
  private snap: HealthSnapshot = { state: 'unknown', failures: 0, lastOkAt: null, since: Date.now(), latencyMs: null, nextProbeAt: null }
  private readonly listeners = new Set<(s: HealthSnapshot) => void>()
  private readonly probeState: { mode: ProbeMode } = { mode: 'api' }
  private timer: ReturnType<typeof setTimeout> | null = null
  private running = false
  private inFlight = false
  private readonly onWake = () => { if (!document.hidden) this.probeNow() }
  private readonly onHidden = () => { if (document.hidden) this.clearTimer(); else this.probeNow() }

  private readonly probe: (s: { mode: ProbeMode }) => Promise<boolean>

  /** `probe` is injectable for tests; production uses probeUiApi. */
  constructor(probe: (s: { mode: ProbeMode }) => Promise<boolean> = probeUiApi) {
    this.probe = probe
  }

  get snapshot(): HealthSnapshot { return this.snap }

  subscribe(cb: (s: HealthSnapshot) => void): () => void {
    this.listeners.add(cb)
    return () => { this.listeners.delete(cb) }
  }

  start(): void {
    if (this.running || typeof window === 'undefined') return
    this.running = true
    window.addEventListener('focus', this.onWake)
    window.addEventListener('online', this.onWake)
    document.addEventListener('visibilitychange', this.onHidden)
    this.probeNow()
  }

  stop(): void {
    this.running = false
    this.clearTimer()
    if (typeof window === 'undefined') return
    window.removeEventListener('focus', this.onWake)
    window.removeEventListener('online', this.onWake)
    document.removeEventListener('visibilitychange', this.onHidden)
  }

  /** Probe immediately (skipped when one is already in flight). */
  probeNow(): void {
    if (!this.running || this.inFlight) return
    this.clearTimer()
    this.inFlight = true
    const t0 = performance.now()
    this.probe(this.probeState).then(
      (ok) => this.settle(ok, Math.round(performance.now() - t0)),
      () => this.settle(false, null),
    )
  }

  private settle(ok: boolean, latency: number | null): void {
    this.inFlight = false
    if (!this.running) return
    this.snap = reduceProbe(this.snap, ok, Date.now(), ok ? latency : null)
    this.schedule()
    for (const cb of this.listeners) {
      try { cb(this.snap) } catch { /* a listener must not break the monitor */ }
    }
  }

  private schedule(): void {
    this.clearTimer()
    if (!this.running || (typeof document !== 'undefined' && document.hidden)) return
    const delay = nextDelayMs(this.snap.failures)
    this.snap = { ...this.snap, nextProbeAt: Date.now() + delay }
    this.timer = setTimeout(() => this.probeNow(), delay)
  }

  private clearTimer(): void {
    if (this.timer) clearTimeout(this.timer)
    this.timer = null
  }
}
