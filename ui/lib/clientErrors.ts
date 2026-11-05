/**
 * Client error reporting (contract K1, completeness-02 / C1-trader-ux-01).
 *
 * UI exceptions used to reach only a debug overlay or the global error page, so a WebKit-only crash after hours in
 * the app left no trace anywhere. Every caught exception now goes, fire-and-forget, to ui-api:
 *
 *     POST /api/client-errors   JSON {message, stack?, tab?, build?, url?, kind?}   → 204
 *
 * (W2-API: 8 KB body cap, ~30/min per process, one structured 'client_error' log line, no cookies or PII).
 * Sources: the per-tab error boundaries (kind 'render'), app/global-error.tsx ('global') and the window
 * 'error' / 'unhandledrejection' handlers ('error' / 'rejection'), installed once by PlatformShell.
 *
 * Client-side rules, so a render loop can never flood the server or the network:
 *  - one report per fingerprint (kind + message + first stack frame) per DEDUPE_MS;
 *  - at most MAX_PER_MINUTE reports per rolling minute and MAX_PER_PAGE per page load;
 *  - fields are clipped (the JSON stays well under the server's 8 KB cap) and control characters are removed;
 *  - `url` is the path and query only (no host, no #fragment); nothing else about the page is sent;
 *  - QA browser contexts (prefs mode 'readonly', set by scripts/desktop_qa before page scripts run) never POST,
 *    so audits against the live stack stay GET-only; the error is still recorded locally (UI chip, overlay).
 *
 * Pure parts (buildReport, fingerprint, ReportGate) take no DOM and are unit-tested by
 * `node ui/components/desktop/__tests__/desktop.check.ts`.
 */

export const CLIENT_ERRORS_URL = '/api/client-errors'

export type ClientErrorKind = 'render' | 'global' | 'error' | 'rejection' | 'chunk'

/** Wire shape (K1). */
export interface ClientErrorReport {
  message: string
  stack?: string
  tab?: string
  build?: string
  url?: string
  kind?: ClientErrorKind
}

export const LIMITS = { message: 500, stack: 4000, url: 300, tab: 40, build: 64 } as const
export const DEDUPE_MS = 60_000
export const MAX_PER_MINUTE = 10
export const MAX_PER_PAGE = 50
/** localStorage key/value the QA harness sets before page scripts (scripts/desktop_qa/probe.new_qa_context). */
export const QA_MODE_KEY = 'suryadhana.prefs.mode'

// eslint-disable-next-line no-control-regex
const CONTROL = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g

function clip(s: unknown, n: number): string {
  const t = String(s ?? '').replace(CONTROL, ' ')
  return t.length > n ? `${t.slice(0, n - 1)}…` : t
}

/** Message + stack of any thrown value (Error, string, object with message, anything). Never throws. */
export function errorParts(err: unknown): { message: string; stack: string } {
  try {
    if (err instanceof Error) return { message: `${err.name && err.name !== 'Error' ? `${err.name}: ` : ''}${err.message}`, stack: err.stack ?? '' }
    if (typeof err === 'string') return { message: err, stack: '' }
    if (err && typeof err === 'object') {
      const o = err as { message?: unknown; stack?: unknown }
      if (typeof o.message === 'string') return { message: o.message, stack: typeof o.stack === 'string' ? o.stack : '' }
    }
    return { message: String(err), stack: '' }
  } catch {
    return { message: 'unprintable error', stack: '' }
  }
}

/** Path + query of a URL (no origin, no fragment); '' when unparsable. */
export function pathAndQuery(href: string): string {
  try {
    const u = new URL(href, 'http://x.invalid')
    return `${u.pathname}${u.search}`
  } catch {
    return ''
  }
}

/** The K1 body for one error. `extraStack` (a React component stack) is appended to the JS stack. */
export function buildReport(input: {
  error: unknown
  kind: ClientErrorKind
  tab?: string | null
  build?: string | null
  href?: string | null
  extraStack?: string | null
}): ClientErrorReport {
  const { message, stack } = errorParts(input.error)
  const fullStack = [stack, input.extraStack ? `component stack:${input.extraStack}` : ''].filter(Boolean).join('\n')
  const r: ClientErrorReport = { message: clip(message.trim() || 'unknown error', LIMITS.message), kind: input.kind }
  if (fullStack) r.stack = clip(fullStack, LIMITS.stack)
  if (input.tab) r.tab = clip(input.tab, LIMITS.tab)
  if (input.build) r.build = clip(input.build, LIMITS.build)
  const url = input.href ? pathAndQuery(input.href) : ''
  if (url) r.url = clip(url, LIMITS.url)
  return r
}

/** Dedupe key: kind + message + the first stack frame line. */
export function fingerprint(r: ClientErrorReport): string {
  const frame = (r.stack ?? '').split('\n').map(l => l.trim()).find(l => /^at |@|:\d+:\d+/.test(l)) ?? ''
  return `${r.kind ?? ''}|${r.message}|${frame}`
}

/** Benign browser noise that is not a terminal bug. */
export function isNoise(r: ClientErrorReport): boolean {
  return /ResizeObserver loop|^Script error\.?$/i.test(r.message) || /(?:chrome|moz|safari(?:-web)?)-extension:\/\//.test(r.stack ?? '')
}

/** Dedupe + rate limit + per-page cap. `allow` records the report when it returns true. */
export class ReportGate {
  private seen = new Map<string, number>()
  private times: number[] = []
  private total = 0

  allow(fp: string, now: number): boolean {
    const last = this.seen.get(fp)
    if (last !== undefined && now - last < DEDUPE_MS) return false
    this.times = this.times.filter(t => now - t < 60_000)
    if (this.times.length >= MAX_PER_MINUTE || this.total >= MAX_PER_PAGE) return false
    this.seen.set(fp, now)
    if (this.seen.size > 200) this.seen.delete(this.seen.keys().next().value as string)
    this.times.push(now)
    this.total++
    return true
  }
}

// ── runtime (browser only) ─────────────────────────────────────────────────────────────────────────

/**
 * What became of one report (R-UI-SHELL-09): the UI says "reported" only once ui-api answered 2xx.
 *  - 'sending': the POST is in flight;
 *  - 'reported': ui-api accepted it (2xx);
 *  - 'failed': the POST failed (ui-api unreachable, 4xx/5xx, offline);
 *  - 'not-sent': never POSTed (readonly QA context, not an http(s) page, fetch unavailable).
 */
export type ClientErrorDelivery = 'sending' | 'reported' | 'failed' | 'not-sent'

export interface ClientErrorEntry {
  at: number
  report: ClientErrorReport
  /** True when the POST was started (false: readonly QA mode or no fetch). See `delivery` for the outcome. */
  sent: boolean
  /** Outcome of the POST; updated in place when it settles (listeners are notified). */
  delivery: ClientErrorDelivery
}

/**
 * One honest sentence about a report for the error panels (R-UI-SHELL-09). `entry` is reportClientError's return:
 * null = this error was not recorded again (the same error within the dedupe window, or the per-minute / per-page cap).
 */
export function deliveryText(entry: Pick<ClientErrorEntry, 'delivery'> | null | undefined): string {
  if (!entry) return 'It was not reported again (the same error was reported a moment ago, or the report limit was reached).'
  switch (entry.delivery) {
    case 'reported': return 'It was reported to ui-api for diagnosis.'
    case 'sending': return 'Reporting it to ui-api…'
    case 'failed': return 'It could not be reported (ui-api unreachable or it refused the report): use COPY DETAILS to keep it.'
    default: return 'It was not reported from this window: use COPY DETAILS to keep it.'
  }
}

const MAX_LOG = 20
const log: ClientErrorEntry[] = []
const listeners = new Set<() => void>()
const gate = new ReportGate()
const OWN_BUILD = typeof process !== 'undefined' ? (process.env.NEXT_PUBLIC_UI_BUILD ?? '') : ''

function currentTab(): string {
  try {
    return new URLSearchParams(window.location.search).get('tab') ?? ''
  } catch {
    return ''
  }
}

function qaReadonly(): boolean {
  try {
    return window.localStorage.getItem(QA_MODE_KEY) === 'readonly'
  } catch {
    return false
  }
}

/** Start the POST; null when it is not sent at all. The promise resolves to the outcome and never rejects. */
function send(r: ClientErrorReport): Promise<'reported' | 'failed'> | null {
  try {
    if (typeof fetch === 'undefined' || !/^https?:$/.test(window.location.protocol) || qaReadonly()) return null
    return fetch(CLIENT_ERRORS_URL, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(r),
      credentials: 'same-origin',
      keepalive: true,
    }).then(res => (res.ok ? 'reported' as const : 'failed' as const), () => 'failed' as const)
  } catch {
    return null
  }
}

let logVersion = 0

/** Bumped on every change of the log (useSyncExternalStore snapshots). */
export function clientErrorsVersion(): number {
  return logVersion
}

function emit(): void {
  logVersion++
  for (const l of listeners) {
    try {
      l()
    } catch {
      /* a listener must not break reporting */
    }
  }
}

/**
 * Record (and, within the limits, report) one error. Never throws; safe to call from render-phase handlers.
 * Returns the entry, or null for noise / duplicates.
 */
export function reportClientError(error: unknown, ctx: { kind: ClientErrorKind; tab?: string | null; componentStack?: string | null }): ClientErrorEntry | null {
  try {
    if (typeof window === 'undefined') return null
    const report = buildReport({
      error, kind: ctx.kind, tab: ctx.tab ?? currentTab(), build: OWN_BUILD || null, href: window.location.href,
      extraStack: ctx.componentStack ?? null,
    })
    if (isNoise(report)) return null
    const now = Date.now()
    if (!gate.allow(fingerprint(report), now)) return null
    const pending = send(report)
    const entry: ClientErrorEntry = { at: now, report, sent: pending !== null, delivery: pending ? 'sending' : 'not-sent' }
    log.push(entry)
    if (log.length > MAX_LOG) log.splice(0, log.length - MAX_LOG)
    emit()
    pending?.then(outcome => { entry.delivery = outcome; emit() })
    return entry
  } catch {
    return null
  }
}

/** The errors recorded in this window since it loaded (newest last), on every page it showed. */
export function clientErrorLog(): readonly ClientErrorEntry[] {
  return log
}

export function clearClientErrors(): void {
  log.length = 0
  emit()
}

export function subscribeClientErrors(cb: () => void): () => void {
  listeners.add(cb)
  return () => {
    listeners.delete(cb)
  }
}

let installed: (() => void) | null = null

/**
 * window 'error' + 'unhandledrejection' → reportClientError. Idempotent; returns the uninstall function.
 * `skip` lets the caller keep errors it handles itself (PlatformShell's ChunkLoadError recovery) out of the log.
 */
export function installClientErrorReporting(skip: (reason: unknown) => boolean = () => false): () => void {
  if (typeof window === 'undefined') return () => {}
  if (installed) return installed
  const onError = (e: ErrorEvent) => {
    const err = e.error ?? e.message
    if (skip(err)) return
    reportClientError(err, { kind: 'error' })
  }
  const onRejection = (e: PromiseRejectionEvent) => {
    if (skip(e.reason)) return
    reportClientError(e.reason, { kind: 'rejection' })
  }
  window.addEventListener('error', onError)
  window.addEventListener('unhandledrejection', onRejection)
  installed = () => {
    window.removeEventListener('error', onError)
    window.removeEventListener('unhandledrejection', onRejection)
    installed = null
  }
  return installed
}
