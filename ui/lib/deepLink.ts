/**
 * Terminal location: `?tab=<page>&sym=<NSE ticker>` (contract K4, C1-trader-ux-09 / -16). Pure, no DOM, no imports
 * (unit-tested by `node ui/components/desktop/__tests__/desktop.check.ts`).
 *
 *  - `tab`: one of the 42 page ids (app/page.tsx COMMAND_PAGES); anything else falls back to the landing page.
 *  - `sym`: an NSE symbol for the stock window, ^[A-Z0-9&_.-]{1,20}$ after upper-casing (the same rule the shell
 *    enforces for shell_new_window {sym}); anything else is ignored.
 *  - History: every page switch and every stock window opened from a page is its own entry, so Back / Forward
 *    (browser buttons, ⌘[ / ⌘] from the app's Go menu) move between screens instead of leaving the terminal.
 *    Entries this page pushed carry `pushed: true`; closing a stock window that was pushed goes Back (one press
 *    of Back is never wasted on a duplicate entry), while one that came from the address (a deep link) is
 *    removed in place, never by leaving the terminal.
 */

export const SYM_RE = /^[A-Z0-9&_.-]{1,20}$/

/** Upper-cased valid NSE symbol, or null. */
export function normalizeSym(s: unknown): string | null {
  if (typeof s !== 'string') return null
  const t = s.trim().toUpperCase()
  return SYM_RE.test(t) ? t : null
}

export interface TerminalLocation {
  tab: string
  sym: string | null
}

/** `tab` + `sym` from a location.search string. */
export function parseLocation(search: string, tabs: readonly string[], fallback: string): TerminalLocation {
  let p: URLSearchParams
  try {
    p = new URLSearchParams(search)
  } catch {
    return { tab: fallback, sym: null }
  }
  const t = p.get('tab')
  return { tab: t && tabs.includes(t) ? t : fallback, sym: normalizeSym(p.get('sym')) }
}

/**
 * The `?tab=` value when it names no page of this release (terminal v2 PLAN 0.6, R-UI S7: an old window or a link
 * from a newer build used to land silently on BRF). Null when there is no `tab` or it is a known page.
 */
export function unknownTab(search: string, tabs: readonly string[]): string | null {
  let p: URLSearchParams
  try {
    p = new URLSearchParams(search)
  } catch {
    return null
  }
  const t = p.get('tab')
  if (t == null || t === '' || tabs.includes(t)) return null
  return t.replace(/[^A-Za-z0-9_-]/g, '').slice(0, 24) || '?'
}

/** "GOLD is not in this release (built 25 Oct) — showing BRF": `build` is the release id YYYYmmdd-HHMMSS-<sha>. */
export function unknownTabText(tab: string, build: string | null, landing = 'BRF'): string {
  const m = /^(\d{4})(\d{2})(\d{2})-/.exec(build ?? '')
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const built = m && +m[2] >= 1 && +m[2] <= 12 ? `built ${m[3]} ${MONTHS[+m[2] - 1]}` : 'a development build'
  return `${tab.toUpperCase()} is not in this release (${built}) — showing ${landing}`
}

/** location.search for (tab, sym), keeping every other parameter of `current` in place. */
export function buildSearch(current: string, tab: string, sym: string | null): string {
  let p: URLSearchParams
  try {
    p = new URLSearchParams(current)
  } catch {
    p = new URLSearchParams()
  }
  p.set('tab', tab)
  if (sym) p.set('sym', sym)
  else p.delete('sym')
  return `?${p.toString()}`
}

/** What page.tsx stores in history.state. */
export interface TerminalHistoryState {
  sd: 1
  tab: string
  sym: string | null
  /** True when this page pushed the entry (closing its stock window may then go Back). */
  pushed: boolean
}

export function isTerminalState(x: unknown): x is TerminalHistoryState {
  if (!x || typeof x !== 'object') return false
  const s = x as Record<string, unknown>
  return s.sd === 1 && typeof s.tab === 'string' && (s.sym === null || typeof s.sym === 'string') && typeof s.pushed === 'boolean'
}

/** How to close a stock window: go Back when this page pushed the entry that opened it, else replace in place. */
export function closeStockAction(state: unknown, sym: string | null): 'back' | 'replace' {
  return isTerminalState(state) && state.pushed && !!state.sym && state.sym === sym ? 'back' : 'replace'
}
