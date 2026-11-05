/**
 * Pure URL classification for the desktop link interceptor and the window.open override.
 *
 * No DOM access: every function takes the page origin explicitly, so the logic is unit-tested
 * under plain node (ui/lib/__tests__/platform.check.ts). Nothing here is a security boundary —
 * the Rust shell re-validates (`shell_open_external` refuses loopback/file/javascript, the
 * navigation allowlist blocks the rest); this only decides which bridge call to make.
 */

/** What a click / window.open target should become in the desktop app. */
export type LinkAction =
  /** http(s) URL on another origin: open in the default browser (`shell_open_external`). */
  | { kind: 'external'; url: string }
  /** Same-origin terminal page link (`/?tab=<id>[&sym=<SYM>]` or `/`): a native terminal window. */
  | { kind: 'tab'; tab: string | null; sym?: string | null }
  /** Same-origin API file (`/api/...`) or `blob:` URL: save into ~/Downloads. */
  | { kind: 'download'; url: string; filename: string }
  /** Loopback URL on another port (e.g. the old :3000 build): never opened externally. */
  | { kind: 'blocked'; reason: string }
  /** Leave the browser default alone (hash links, mailto:, javascript:, unparsable…). */
  | { kind: 'ignore' }

/** Same shape the shell enforces for `shell_new_window {tab}` (the 42 ids are all lowercase words). */
export const TAB_ID_RE = /^[a-z][a-z0-9_-]{0,39}$/

/** NSE symbol in a terminal link (`?sym=`), the rule the shell enforces for shell_new_window {sym} (contract K4). */
const SYM_LINK_RE = /^[A-Z0-9&_.-]{1,20}$/

/** `shell_open_external` limit (PLAN §5). */
export const MAX_EXTERNAL_URL = 2048

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]', '::1', '0.0.0.0'])

/** True for localhost / 127.0.0.0/8 / ::1 hostnames (as returned by URL.hostname). */
export function isLoopbackHost(hostname: string): boolean {
  const h = hostname.toLowerCase()
  return LOOPBACK_HOSTS.has(h) || /^127\.\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(h) || h.endsWith('.localhost')
}

/** Last path segment of a URL, decoded, or a fallback; used as the default download name. */
export function basenameFromUrl(u: URL, fallback = 'download'): string {
  const name = u.searchParams.get('name') || u.pathname.split('/').filter(Boolean).pop() || ''
  let decoded = name
  try {
    decoded = decodeURIComponent(name)
  } catch {
    /* keep raw */
  }
  return decoded.trim() || fallback
}

/**
 * Classify `href` (absolute or relative to `pageHref`) for a page at `origin`.
 * `hasDownloadAttr` marks `<a download>`: same-origin/blob targets become downloads.
 */
export function classifyHref(
  href: string | null | undefined,
  pageHref: string,
  opts: { hasDownloadAttr?: boolean; downloadName?: string | null } = {},
): LinkAction {
  if (href == null) return { kind: 'ignore' }
  const raw = String(href).trim()
  if (!raw || raw.startsWith('#')) return { kind: 'ignore' }
  let u: URL
  let page: URL
  try {
    page = new URL(pageHref)
    u = new URL(raw, page)
  } catch {
    return { kind: 'ignore' }
  }
  const proto = u.protocol
  if (proto === 'blob:') {
    return opts.hasDownloadAttr
      ? { kind: 'download', url: u.href, filename: (opts.downloadName || '').trim() || 'download' }
      : { kind: 'ignore' }
  }
  if (proto !== 'http:' && proto !== 'https:') return { kind: 'ignore' } // mailto:, tel:, javascript:, data:, file:
  const sameOrigin = u.origin === page.origin
  if (!sameOrigin) {
    if (isLoopbackHost(u.hostname)) return { kind: 'blocked', reason: 'loopback url on another port' }
    if (u.href.length > MAX_EXTERNAL_URL) return { kind: 'blocked', reason: 'url too long' }
    return { kind: 'external', url: u.href }
  }
  // same origin
  if (u.pathname.startsWith('/api/') || opts.hasDownloadAttr) {
    const filename = (opts.downloadName || '').trim() || basenameFromUrl(u)
    return { kind: 'download', url: u.href, filename }
  }
  if (u.pathname === '/' || u.pathname === '' || u.pathname === '/index.html') {
    const t = u.searchParams.get('tab')
    const s = (u.searchParams.get('sym') || '').trim().toUpperCase()
    const tab = t && TAB_ID_RE.test(t) ? t : null
    return SYM_LINK_RE.test(s) ? { kind: 'tab', tab, sym: s } : { kind: 'tab', tab }
  }
  // Any other same-origin path is a terminal route as well (the export has one page): open a window.
  return { kind: 'tab', tab: null }
}

/** Minimal click facts the interceptor needs (a structural subset of MouseEvent + the anchor). */
export interface ClickFacts {
  button: number
  metaKey: boolean
  ctrlKey: boolean
  shiftKey: boolean
  altKey: boolean
  defaultPrevented: boolean
  href: string | null
  target: string | null
  hasDownloadAttr: boolean
  downloadName: string | null
}

/** Decision for one anchor click: what to do, or null to leave the event alone. */
export function decideClick(c: ClickFacts, pageHref: string): LinkAction | null {
  if (c.defaultPrevented) return null
  if (c.button !== 0 && c.button !== 1) return null // right-click etc.
  if (c.altKey) return null // ⌥-click = "download linked file" in Safari; leave it
  const action = classifyHref(c.href, pageHref, { hasDownloadAttr: c.hasDownloadAttr, downloadName: c.downloadName })
  const newContext = (c.target || '').toLowerCase() === '_blank' || c.button === 1 || c.metaKey || c.ctrlKey || c.shiftKey
  switch (action.kind) {
    case 'ignore':
      return null
    case 'external':
    case 'download':
    case 'blocked':
      return action // the webview can never show these in place
    case 'tab':
      // a plain same-window click on an internal link stays an in-app navigation
      return newContext ? action : null
  }
}
