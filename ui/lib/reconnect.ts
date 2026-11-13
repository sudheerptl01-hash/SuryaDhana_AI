/**
 * After an outage (C1-trader-ux-02). Pure, no DOM, no imports (unit-tested by
 * `node ui/components/desktop/__tests__/desktop.check.ts`).
 *
 * PlatformShell dispatches RECONNECTED_EVENT on window when the connection banner goes from LINK DOWN to
 * LINK UP (desktop: the shell's status; browser: the /api/health monitor), with {outageMs} as detail. Pages that
 * poll recover on their next poll by themselves; panels whose one-shot load FAILED during the outage would keep
 * saying "Network Error" forever. So on that event app/page.tsx reloads the active page and the open stock window,
 * EACH only when its own visible text shows a trace of a failed load or a crashed render (separate reload epochs:
 * a healthy page under a failed stock window keeps its state, R-UI-SHELL-05), after a per-window random delay
 * (reconnectDelayMs). Only the page's own content is scanned (the `.sd-page` element), never the in-page LINK DOWN
 * notice next to it.
 */

export const RECONNECTED_EVENT = 'suryadhana:reconnected' as const

export interface ReconnectedDetail {
  outageMs: number | null
}

/**
 * Visible text of a load that failed because the backend was unreachable or erroring: axios ('Network Error',
 * 'timeout of 10000ms exceeded', 'Request failed with status code 502'), WebKit fetch ('Load failed'), Chromium
 * fetch ('Failed to fetch'), Firefox ('NetworkError when attempting…'), fetch wrappers ('HTTP 503'), gateway
 * pages, and the per-page error boundary ('failed to render').
 */
export const FAILED_LOAD_TEXT =
  /Network Error|Load failed|Failed to fetch|NetworkError when attempting|timeout of \d+ms exceeded|Request failed with status code 5\d\d|\bHTTP 5\d\d\b|ECONNREFUSED|ECONNRESET|Bad Gateway|Service Unavailable|Gateway Time-?out|failed to render|server unreachable|backend unreachable|waiting for the data service/i

/**
 * Each window waits a random 0–RECONNECT_JITTER_MS before it reloads what failed (R-UI-SHELL-05): every window sees
 * LINK UP at the same moment, and BRF alone sends ~30 GETs on mount, so N windows reloading at once would hit a
 * ui-api / data-service that has just recovered with N × 30 requests in the same instant.
 */
export const RECONNECT_JITTER_MS = 2000

/** The delay before this window acts on a reconnect, in [0, RECONNECT_JITTER_MS). `rand` is injectable for tests. */
export function reconnectDelayMs(rand: () => number = Math.random): number {
  const r = rand()
  return Math.floor((Number.isFinite(r) ? Math.min(Math.max(r, 0), 0.999999) : 0) * RECONNECT_JITTER_MS)
}

/** True when a page whose visible text is `text` should be reloaded after the link came back. */
export function needsReloadAfterOutage(text: string | null | undefined): boolean {
  return !!text && FAILED_LOAD_TEXT.test(text)
}
