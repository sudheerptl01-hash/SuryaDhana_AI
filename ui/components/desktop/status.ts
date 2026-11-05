/**
 * Shell status freshness for the title strip's service dots (C1-desktop-native-03). Pure, no DOM (unit-tested by
 * `node ui/components/desktop/__tests__/desktop.check.ts`).
 *
 * The shell's poller checks the services every 5 s and pushes a `status` event on change and at least every
 * SHELL_STATUS_MAX_INTERVAL_MS (contract with desktop/src-tauri: ≤ 10 s). The dots turn grey ("status is stale")
 * only after about three missed pushes, never between two normal ones. When no push arrives for
 * STATUS_PULL_MS the UI also asks the shell for its cached status (`shell_status`, cheap, never blocks), so an
 * older shell with a slower heartbeat still reads as fresh. Freshness is the poller's own `at`, not the arrival
 * time, so a cached status from a poller that has stopped still goes stale.
 */

/** The shell pushes a status at least this often (desktop contract). */
export const SHELL_STATUS_MAX_INTERVAL_MS = 10_000
/** Grey dots after ~3 missed pushes plus one 5 s poll of jitter. */
export const STATUS_STALE_MS = 3 * SHELL_STATUS_MAX_INTERVAL_MS + 5_000
/** No push for this long: pull the shell's cached status. */
export const STATUS_PULL_MS = SHELL_STATUS_MAX_INTERVAL_MS

/**
 * When the status was true: the poller's `at` (ISO), capped at the arrival time; the arrival time when `at` is
 * missing or unparseable.
 */
export function statusFreshAt(at: unknown, receivedAt: number): number {
  const t = typeof at === 'string' ? Date.parse(at) : NaN
  return Number.isFinite(t) ? Math.min(t, receivedAt) : receivedAt
}

/** True when a status that was true at `freshAt` is too old to show (0 = no status yet). */
export function isStatusStale(freshAt: number, now: number): boolean {
  return freshAt <= 0 || now - freshAt > STATUS_STALE_MS
}
