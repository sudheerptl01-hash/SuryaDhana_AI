/**
 * Lifecycle of the page's one live-quote WebSocket (/api/monitor/ws/monitor). No React and no DOM (one pure import),
 * so the rules are unit-tested under plain node against the real lib/wsManager.ts singleton (ui/lib/__tests__/ws.check.ts).
 *
 * Rules (PM request, 25 Oct: the live ui-api logged 95 socket accepts and 0 closes before it hung):
 *  - ONE socket per window: the wsManager singleton never opens a second one while one is OPEN or CONNECTING, and
 *    this module is attached once, by AppProvider (context/AppContext.tsx). Page switches, the per-page error
 *    boundaries and the post-outage reload of a page do not remount AppProvider, so they never open a socket.
 *  - closed on unmount: the cleanup disconnects with a clean close (code 1000), so the server's handler sees the
 *    close at once instead of when TCP gives up;
 *  - closed on page hide: 'pagehide' (navigation, reload, window close, and the back-forward cache, where the page
 *    may be kept frozen with its socket) disconnects the same way; 'pageshow' of a page restored from that cache
 *    reconnects. A first load's pageshow (persisted=false) never opens a second socket;
 *  - the status flag reads the manager's real state: a superseded socket's late close event (it can arrive after
 *    the reconnect) cannot mark the live socket as down;
 *  - LINK UP kicks it (R-UI-SHELL-10): on the terminal's reconnected event (lib/reconnect.ts, PlatformShell's LINK
 *    DOWN → LINK UP edge) a socket that is not connected reconnects at once with a fresh backoff, instead of waiting
 *    up to 32 s on the manager's backoff timer while the banner already says the link is back.
 * A hidden (not unloaded) window keeps its socket: today's behaviour for the app's windows hidden to the menu bar.
 */

import { RECONNECTED_EVENT } from './reconnect'

/** The parts of lib/wsManager.ts MonitorWebSocketManager this module drives. */
export interface MonitorSocket {
  connect(url: string, onStatus?: (connected: boolean) => void): void
  disconnect(): void
  readonly isConnected: boolean
  /** Reconnect now with a fresh backoff (no-op while open / connecting). */
  reconnectNow?(): void
}

/** The window events this module listens to (`window` in the app; an EventTarget in the checks). */
export interface PageEvents {
  addEventListener(type: string, cb: (e: Event) => void): void
  removeEventListener(type: string, cb: (e: Event) => void): void
}

/** Connect `socket` for this page and keep it closed while the page is hidden. Returns the cleanup (disconnects). */
export function attachMonitorSocket(
  page: PageEvents,
  socket: MonitorSocket,
  url: string,
  onStatus: (connected: boolean) => void,
): () => void {
  let live = true
  let hiddenClosed = false
  const status = () => {
    if (live) onStatus(socket.isConnected)
  }
  const open = () => socket.connect(url, status)
  const onHide = () => {
    if (!live) return
    hiddenClosed = true
    socket.disconnect()
  }
  // only after our own pagehide close: a page restored from the back-forward cache, or shown again after an unload
  // that did not happen. The first load's pageshow finds hiddenClosed false and changes nothing.
  const onShow = () => {
    if (!live || !hiddenClosed) return
    hiddenClosed = false
    open()
  }
  // ui-api is reachable again: a socket waiting on its backoff timer reconnects now (never a second socket)
  const onReconnected = () => {
    if (!live || hiddenClosed || socket.isConnected) return
    socket.reconnectNow?.()
  }
  page.addEventListener('pagehide', onHide)
  page.addEventListener('pageshow', onShow)
  page.addEventListener(RECONNECTED_EVENT, onReconnected)
  open()
  return () => {
    page.removeEventListener('pagehide', onHide)
    page.removeEventListener('pageshow', onShow)
    page.removeEventListener(RECONNECTED_EVENT, onReconnected)
    socket.disconnect()
    live = false
  }
}

// ── P10: the server's monitored set (Redis monitored.stocks) ─────────────────────────────────────────────────────

/** How often a visible window re-checks that the server still monitors its watchlist (P10). */
export const MONITOR_RESYNC_MS = 10 * 60_000
/** The same while the window is hidden. */
export const MONITOR_RESYNC_HIDDEN_MS = 30 * 60_000

/**
 * Watchlist symbols missing from the server's monitored set (`server` = GET /api/monitor/list `symbols`), in watchlist
 * order, each once, compared case-insensitively. Anything that is not a list (an error body, a missing field) means
 * "unknown" and gives nothing: never a blind re-subscribe of the whole list.
 */
export function missingMonitorSymbols(watchlist: readonly unknown[], server: unknown): string[] {
  if (!Array.isArray(server)) return []
  const have = new Set(server.filter((s): s is string => typeof s === 'string').map(s => s.trim().toUpperCase()))
  const out: string[] = []
  const seen = new Set<string>()
  for (const t of watchlist) {
    if (typeof t !== 'string') continue
    const u = t.trim().toUpperCase()
    if (!u || have.has(u) || seen.has(u)) continue
    seen.add(u)
    out.push(t.trim())
  }
  return out
}
