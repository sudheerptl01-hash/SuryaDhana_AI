/**
 * Platform bridge: one API for the browser and SuryaDhana.app (Tauri v2, WKWebView).
 *
 * Contract: reports/desktop_app/PLAN.md §5 (FROZEN v1). In a browser every function keeps
 * today's exact behavior (Web Notification, `<a download>` + object URL, `window.open`), so the
 * browser terminal is unchanged. Inside the app (`isDesktop()`), the same calls are routed to the
 * shell's 9 remote commands, which re-validate everything in Rust.
 *
 * Rules every export follows:
 *  - SSR-safe (no window access at import time) and never throws into callers;
 *  - browser branches run synchronously up to the user-visible effect (popup blockers and download
 *    heuristics need the click's user activation), desktop branches are async;
 *  - nothing here logs URLs or payloads (the ICICI login_url carries the API key).
 */
import { invokeShell, isDesktop, ShellError } from './invoke'
import { classifyHref, decideClick, TAB_ID_RE, type LinkAction } from './links'
import { blobToBase64, MAX_DOWNLOAD_BYTES, sanitizeFilename, toBlob } from './encoding'
import { hydratePrefs, installPrefsWriteThrough } from '../prefs/sync'
import {
  SHELL_EVENT,
  type BootstrapOptions,
  type NotificationPermissionState,
  type ShellEvent,
  type ShellInfo,
  type ShellStatus,
} from './types'

export type {
  BootstrapOptions,
  IciciState,
  NotificationPermissionState,
  ShellCommand,
  ShellCommands,
  ShellEvent,
  ShellInfo,
  ShellMarker,
  ShellStatus,
  Svc,
} from './types'
export { SHELL_EVENT } from './types'
export { isDesktop, shellMarker, ShellError, type ShellErrorKind } from './invoke'
export { PREFS_CHANGED_EVENT } from '../prefs/sync'

const hasWindow = () => typeof window !== 'undefined'

function warn(what: string, e?: unknown): void {
  // Messages only; never URLs, titles or payloads.
  const msg = e instanceof ShellError ? `${e.kind}: ${e.message}` : e instanceof Error ? e.message : ''
  try {
    console.warn(`[platform] ${what}${msg ? ` (${msg})` : ''}`)
  } catch {
    /* console unavailable */
  }
}

// ── shell info / status ────────────────────────────────────────────────────────────────────────

/** `shell_info` from the app, or null in a browser / on error. */
export async function shellInfo(): Promise<ShellInfo | null> {
  if (!isDesktop()) return null
  try {
    return await invokeShell('shell_info')
  } catch (e) {
    warn('shell_info failed', e)
    return null
  }
}

/** The shell's cached health snapshot, or null in a browser / on error. Never blocks (Rust returns the cache). */
export async function shellStatus(): Promise<ShellStatus | null> {
  if (!isDesktop()) return null
  try {
    return await invokeShell('shell_status')
  } catch (e) {
    warn('shell_status failed', e)
    return null
  }
}

// ── notifications ──────────────────────────────────────────────────────────────────────────────

const clip = (s: string, n: number) => {
  const t = String(s ?? '')
  return t.length > n ? `${t.slice(0, n - 1)}…` : t
}

/**
 * Show a notification. Browser: exactly today's behavior (only when permission is granted).
 * Desktop: native macOS notification via the shell (title ≤ 120, body ≤ 1000 chars; throttled in Rust).
 */
export function notify(title: string, body: string): void {
  if (isDesktop()) {
    invokeShell('shell_notify', { title: clip(title, 120), body: clip(body, 1000) }).catch((e) => warn('notify failed', e))
    return
  }
  try {
    if (typeof Notification !== 'undefined' && Notification.permission === 'granted') new Notification(title, { body })
  } catch {
    /* notifications unavailable */
  }
}

/** 'unsupported' = no notification API in this context (browser branch only). */
export type NotificationPermissionResult = NotificationPermissionState | 'unsupported'

/** Current notification permission (desktop: the macOS authorization state via the shell). */
export async function notificationPermission(): Promise<NotificationPermissionResult> {
  if (isDesktop()) {
    try {
      return await invokeShell('shell_notification_permission')
    } catch (e) {
      warn('notification permission failed', e)
      return 'default'
    }
  }
  return typeof Notification !== 'undefined' ? (Notification.permission as NotificationPermissionState) : 'unsupported'
}

/** Ask for notification permission (browser: `Notification.requestPermission()` as today). */
export async function requestNotificationPermission(): Promise<NotificationPermissionResult> {
  if (isDesktop()) {
    try {
      return await invokeShell('shell_request_notification_permission', undefined, 60_000)
    } catch (e) {
      warn('notification permission request failed', e)
      return 'default'
    }
  }
  if (typeof Notification === 'undefined') return 'unsupported'
  return (await Notification.requestPermission()) as NotificationPermissionState
}

// ── downloads ──────────────────────────────────────────────────────────────────────────────────

/** Fired on `window` after every desktop save attempt, so the UI can show "Saved to ~/Downloads/…". */
export const DOWNLOAD_EVENT = 'suryadhana:download' as const
export interface DownloadEventDetail {
  ok: boolean
  filename: string
  path?: string
  error?: string
}

function emitDownload(detail: DownloadEventDetail): void {
  try {
    window.dispatchEvent(new CustomEvent<DownloadEventDetail>(DOWNLOAD_EVENT, { detail }))
  } catch {
    /* no window */
  }
}

/** Browser download exactly as the call sites did it: anchor + object URL, revoked after 1 s. */
function browserBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

async function desktopSave(blob: Blob, filename: string): Promise<string | null> {
  const name = sanitizeFilename(filename)
  try {
    if (blob.size > MAX_DOWNLOAD_BYTES) throw new Error(`file is larger than ${MAX_DOWNLOAD_BYTES / 1048576} MB`)
    const base64 = await blobToBase64(blob)
    const { path } = await invokeShell('shell_save_download', { filename: name, base64 }, 60_000)
    emitDownload({ ok: true, filename: name, path })
    return path
  } catch (e) {
    const error = e instanceof Error ? e.message : 'save failed'
    warn('save download failed', e)
    emitDownload({ ok: false, filename: name, error })
    return null
  }
}

/**
 * Save `data` as `filename`. Browser: today's anchor download (returns null: the browser owns the
 * path). Desktop: written by the shell into ~/Downloads (unique suffix) and the full path returned;
 * null on failure (a `suryadhana:download` event reports the outcome either way). Never rejects.
 */
export function saveDownload(data: Blob | string, filename: string, mime?: string): Promise<string | null> {
  let blob: Blob
  try {
    blob = toBlob(data, mime)
  } catch (e) {
    warn('save download: bad data', e)
    return Promise.resolve(null)
  }
  if (isDesktop()) return desktopSave(blob, filename)
  try {
    browserBlobDownload(blob, filename)
  } catch (e) {
    warn('download failed', e)
  }
  return Promise.resolve(null)
}

function sameOrigin(url: string): URL | null {
  try {
    const u = new URL(url, window.location.href)
    return u.origin === window.location.origin || u.protocol === 'blob:' ? u : null
  } catch {
    return null
  }
}

/**
 * Download a same-origin URL (e.g. `/api/research/file?...`). Browser: an `<a href download>` click,
 * as today. Desktop: fetched same-origin into a Blob, then `saveDownload`. Cross-origin URLs are
 * refused in desktop mode (use openExternal). Never rejects.
 */
export function downloadUrl(url: string, filename: string): Promise<string | null> {
  if (!hasWindow()) return Promise.resolve(null)
  if (!isDesktop()) {
    try {
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
    } catch (e) {
      warn('download failed', e)
    }
    return Promise.resolve(null)
  }
  const u = sameOrigin(url)
  if (!u) {
    warn('download refused: not a same-origin url')
    emitDownload({ ok: false, filename, error: 'not a same-origin url' })
    return Promise.resolve(null)
  }
  return (async () => {
    try {
      const r = await fetch(u.href, { credentials: 'same-origin' })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      const blob = await r.blob()
      return await desktopSave(blob, filename)
    } catch (e) {
      warn('download fetch failed', e)
      emitDownload({ ok: false, filename: sanitizeFilename(filename), error: e instanceof Error ? e.message : 'fetch failed' })
      return null
    }
  })()
}

// ── windows / external links ───────────────────────────────────────────────────────────────────

/** Open an external http(s) URL. Browser: `window.open(url, '_blank', 'noopener')` (today's call). Desktop: default browser. */
export function openExternal(url: string): void {
  if (!hasWindow()) return
  if (isDesktop()) {
    invokeShell('shell_open_external', { url: String(url) }).catch((e) => warn('open external failed', e))
    return
  }
  window.open(url, '_blank', 'noopener')
}

/** NSE symbol rule shared with the shell's shell_new_window {sym} validation (contract K4). */
export const SYM_ARG_RE = /^[A-Z0-9&_.-]{1,20}$/

/** Same-origin path for a terminal window on `tab` (and the stock window of `sym`). */
export function terminalPath(tab?: string, sym?: string): string {
  const t = tab && TAB_ID_RE.test(tab) ? tab : undefined
  const s = sym && SYM_ARG_RE.test(sym) ? sym : undefined
  if (!t && !s) return '/'
  const q = new URLSearchParams()
  if (t) q.set('tab', t)
  if (s) q.set('sym', s)
  return `/?${q.toString()}`
}

/**
 * Open another terminal window on `tab` (one of the 42 ids), optionally with the stock window of `sym` open
 * (contract K4). Browser: `window.open('/?tab=<id>[&sym=<SYM>]')`. Desktop: a native window (≤ 8, enforced in
 * Rust); resolves to its label, or null. Invalid values are dropped, never sent.
 */
export function newWindow(tab?: string, sym?: string): Promise<string | null> {
  if (!hasWindow()) return Promise.resolve(null)
  const t = tab && TAB_ID_RE.test(tab) ? tab : undefined
  const s = sym && SYM_ARG_RE.test(sym) ? sym : undefined
  if (isDesktop()) {
    const args: { tab?: string; sym?: string } = {}
    if (t) args.tab = t
    if (s) args.sym = s
    return invokeShell('shell_new_window', args).then(
      (r) => r?.label ?? null,
      (e) => {
        warn('new window failed', e)
        return null
      },
    )
  }
  try {
    window.open(terminalPath(t, s), '_blank')
  } catch (e) {
    warn('new window failed', e)
  }
  return Promise.resolve(null)
}

/** Native window title (desktop only; plain text ≤ 120 chars). The browser tab title is left alone. */
export function setWindowTitle(title: string): void {
  if (!isDesktop()) return
  // eslint-disable-next-line no-control-regex
  const plain = clip(String(title ?? '').replace(/[\u0000-\u001f\u007f]+/g, ' ').trim(), 120)
  invokeShell('shell_set_title', { title: plain }).catch((e) => warn('set title failed', e))
}

// ── shell → UI events ──────────────────────────────────────────────────────────────────────────

/** Shape check for a `suryadhana:shell` detail (the page never trusts event payloads blindly). */
export function isShellEvent(d: unknown): d is ShellEvent {
  if (!d || typeof d !== 'object') return false
  const e = d as Record<string, unknown>
  switch (e.type) {
    case 'status':
      return !!e.status && typeof e.status === 'object'
    case 'goto':
      return typeof e.tab === 'string' && TAB_ID_RE.test(e.tab)
    case 'command-bar':
      return true
    case 'build-changed':
      return typeof e.build === 'string'
    case 'zoom':
      return typeof e.factor === 'number' && Number.isFinite(e.factor) && e.factor > 0.2 && e.factor <= 5
    default:
      return false
  }
}

/** Subscribe to shell events. Returns the unsubscribe function (a no-op during SSR). */
export function onShellEvent(cb: (e: ShellEvent) => void): () => void {
  if (!hasWindow()) return () => {}
  const handler = (ev: Event) => {
    const detail = (ev as CustomEvent<unknown>).detail
    if (!isShellEvent(detail)) return
    try {
      cb(detail)
    } catch (e) {
      warn('shell event handler threw', e)
    }
  }
  window.addEventListener(SHELL_EVENT, handler)
  return () => window.removeEventListener(SHELL_EVENT, handler)
}

// ── desktop link interceptor ───────────────────────────────────────────────────────────────────

function perform(action: LinkAction): void {
  switch (action.kind) {
    case 'external':
      openExternal(action.url)
      return
    case 'tab':
      void newWindow(action.tab ?? undefined, action.sym ?? undefined)
      return
    case 'download':
      void downloadUrl(action.url, action.filename)
      return
    case 'blocked':
      warn(`link blocked: ${action.reason}`)
      return
    case 'ignore':
      return
  }
}

let uninstallInterceptor: (() => void) | null = null

/**
 * Desktop only (no-op in a browser): route `target=_blank`, external, `<a download>` and ⌘/middle-click
 * links through the shell, and override `window.open` (external → default browser, same-origin →
 * new terminal window). Capture phase so React handlers that call stopPropagation (row-click
 * guards) cannot hide the click. Idempotent; returns the uninstall function.
 */
export function installLinkInterceptor(): () => void {
  if (!hasWindow() || !isDesktop()) return () => {}
  if (uninstallInterceptor) return uninstallInterceptor

  const onClick = (ev: MouseEvent) => {
    try {
      const el = ev.target instanceof Element ? ev.target : (ev.target as Node | null)?.parentElement ?? null
      const a = el?.closest('a[href]') as HTMLAnchorElement | SVGAElement | null
      if (!a) return
      const href = typeof (a as HTMLAnchorElement).href === 'string' ? (a as HTMLAnchorElement).href : a.getAttribute('href')
      const action = decideClick(
        {
          button: ev.button,
          metaKey: ev.metaKey,
          ctrlKey: ev.ctrlKey,
          shiftKey: ev.shiftKey,
          altKey: ev.altKey,
          defaultPrevented: ev.defaultPrevented,
          href,
          target: a.getAttribute('target'),
          hasDownloadAttr: a.hasAttribute('download'),
          downloadName: a.getAttribute('download'),
        },
        window.location.href,
      )
      if (!action) return
      ev.preventDefault()
      perform(action)
    } catch (e) {
      warn('link interceptor error', e)
    }
  }

  const originalOpen = window.open
  const patchedOpen = function (this: Window, url?: string | URL, target?: string, features?: string): Window | null {
    const href = url == null ? '' : String(url)
    const action = classifyHref(href, window.location.href)
    if (action.kind === 'ignore') return originalOpen.call(window, url, target, features)
    perform(action)
    return null
  } as typeof window.open

  document.addEventListener('click', onClick, true)
  document.addEventListener('auxclick', onClick, true)
  window.open = patchedOpen
  uninstallInterceptor = () => {
    document.removeEventListener('click', onClick, true)
    document.removeEventListener('auxclick', onClick, true)
    if (window.open === patchedOpen) window.open = originalOpen
    uninstallInterceptor = null
  }
  return uninstallInterceptor
}

// ── bootstrap ──────────────────────────────────────────────────────────────────────────────────

let bootPromise: Promise<void> | null = null

/**
 * The single entry point (D4's PlatformShell awaits it before first render):
 * hydrate prefs from ui-api (bounded by `hydrateTimeoutMs`, default 1500 ms), install the prefs
 * write-through, and in the desktop app install the link interceptor. Idempotent, SSR-safe,
 * never rejects, never takes longer than the timeout (+ a small grace).
 */
export function bootstrapPlatform(opts: BootstrapOptions = {}): Promise<void> {
  if (!hasWindow()) return Promise.resolve()
  if (bootPromise) return bootPromise
  const timeoutMs = Math.max(0, opts.hydrateTimeoutMs ?? 1500)
  const apiBase = opts.apiBase ?? ''
  const run = async () => {
    try {
      if (isDesktop()) installLinkInterceptor()
    } catch (e) {
      warn('link interceptor install failed', e)
    }
    if (opts.skipPrefs) return
    try {
      installPrefsWriteThrough({ apiBase })
    } catch (e) {
      warn('prefs write-through install failed', e)
    }
    try {
      await hydratePrefs({ timeoutMs, apiBase })
    } catch (e) {
      warn('prefs hydration failed', e)
    }
  }
  bootPromise = new Promise<void>((resolve) => {
    const guard = setTimeout(resolve, timeoutMs + 250) // hard ceiling whatever happens inside
    run().then(
      () => {
        clearTimeout(guard)
        resolve()
      },
      () => {
        clearTimeout(guard)
        resolve()
      },
    )
  })
  return bootPromise
}
