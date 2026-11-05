/**
 * Keyboard model of the terminal shell (C1-trader-ux-09). Pure, no DOM, no imports (unit-tested by
 * `node ui/components/desktop/__tests__/desktop.check.ts`).
 *
 *  - type-to-GO: a printable ticker character typed while nothing editable has focus opens the GO bar seeded
 *    with it (Bloomberg: just start typing). Keys another handler already consumed (defaultPrevented: the
 *    DataTable cursor's j/k, Shift+N for NEWS) and every modifier chord are left alone;
 *  - the help card and the status line teach the shortcuts of the host: ⌘ in SuryaDhana.app (its menu owns
 *    ⌘1–9, ⌘N, ⌘W, ⌘[ / ⌘], ⌘= / ⌘− / ⌘0), Alt in a browser (where ⌘/Ctrl+digit switches browser tabs). Browser
 *    Back / Forward is ⌘[ / ⌘] on a Mac (Safari, Chrome; Alt+← moves by word there) and Alt+← / Alt+→ elsewhere
 *    (R-UI-SHELL-08).
 */

/** The parts of `navigator` isMacPlatform reads (the real navigator in the app; a plain object in the checks). */
export interface PlatformHints {
  userAgentData?: { platform?: string } | null
  platform?: string
  userAgent?: string
}

/** True on macOS (and iPadOS with a keyboard, which uses the same ⌘ bindings). */
export function isMacPlatform(nav: PlatformHints | null | undefined): boolean {
  if (!nav) return false
  const p = nav.userAgentData?.platform || nav.platform || ''
  if (p) return /mac|iphone|ipad|ipod/i.test(p)
  return /Macintosh|Mac OS X/.test(nav.userAgent ?? '')
}

/** isMacPlatform for the running page (false outside a browser). */
export function onMac(): boolean {
  try {
    return typeof navigator !== 'undefined' && isMacPlatform(navigator as unknown as PlatformHints)
  } catch {
    return false
  }
}

/** Characters that start a GO query: ticker letters and digits (M&M, BAJAJ-AUTO start with a letter). */
const GO_START = /^[A-Za-z0-9]$/

export interface KeyFacts {
  key: string
  ctrlKey: boolean
  metaKey: boolean
  altKey: boolean
  shiftKey: boolean
  isComposing?: boolean
  repeat?: boolean
  defaultPrevented: boolean
}

/**
 * The character to seed the GO bar with, or null to leave the key alone. `typing` = focus is in an input,
 * textarea, select or contentEditable; `blocked` = a dialog other than the stock window is open (help card,
 * News Terminal, GO bar itself).
 */
export function typeToGoChar(e: KeyFacts, ctx: { typing: boolean; blocked: boolean }): string | null {
  if (ctx.typing || ctx.blocked || e.defaultPrevented || e.isComposing || e.repeat) return null
  if (e.ctrlKey || e.metaKey || e.altKey) return null
  if (!GO_START.test(e.key)) return null
  if (e.shiftKey && (e.key === 'N' || e.key === 'n')) return null // Shift+N opens NEWS
  return e.key.toUpperCase()
}

/** The window event that opens the GO bar (components/CommandBar.tsx); a string `detail` seeds its input. */
export const GO_COMMAND_EVENT = 'suryadhana:command'

/**
 * R-UI-SHELL-04: after the GO bar's error boundary retried on the user's key press (the bar was down, so that key went
 * nowhere), the open command to send once the bar is back: ⌘K / Ctrl+K and '/' open it, a ticker character opens it
 * seeded (type-to-GO), anything else nothing. `typing` / `blocked` as in typeToGoChar.
 */
export function goOpenAfterRetry(e: KeyFacts & { type?: string }, ctx: { typing: boolean; blocked: boolean }): { seed: string | null } | null {
  if (e.type === GO_COMMAND_EVENT) return { seed: null }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') return { seed: null }
  if (e.key === '/' && !ctx.typing && !e.ctrlKey && !e.metaKey && !e.altKey) return { seed: null }
  const ch = typeToGoChar(e, ctx)
  return ch ? { seed: ch } : null
}

export type ShortcutRow = readonly [keys: string, what: string]

/** Help card rows for the host (`mac`: a browser on macOS, see isMacPlatform). */
export function helpKeys(desktop: boolean, mac = false): ShortcutRow[] {
  const mod = desktop ? '⌘' : 'Ctrl/⌘'
  return [
    [`/  or  ${mod} K`, 'Command bar: type a page code, a ticker or a company'],
    ['just type', 'Typing a ticker anywhere outside a text box opens the command bar with it'],
    ['TICKER  ↵', 'Open the stock: Profile (DES), chart, events'],
    ['⇧ ↵ in the command bar', 'Open the page or stock in a NEW WINDOW'],
    ['TICKER DES / FA / ERN / HP / SEAG', 'Profile · financials · results history · historical prices · seasonality'],
    ['TABLE ↑ ↓ / J K · ENTER', 'click a table, move the row cursor, open that stock (Esc clears) · ⤓ CSV on hover'],
    ['TICKER TV / YF / W', 'TradingView · Yahoo Finance · watchlist on/off'],
    ['COMP TCS INFY …', 'Compare up to 8 stocks against NIFTY'],
    ['OMON  /  OMON RELIANCE', 'Option chain: OI walls, implied volatility, PCR, max pain'],
    ['TICKER OMON · TICKER DEAL', "The stock's option chain · its block and bulk deals"],
    ['GP · TOP · MOST · BACK', 'Bloomberg mnemonics: chart studio · news · movers · back (NIFTY: index option chain)'],
    ...(desktop
      ? ([
          ['⌘ 1 … 9  ·  Alt 0', 'Jump to the first ten pages'],
          ['⌘ [  ·  ⌘ ]', 'Back · forward between pages and stock windows'],
          ['⌘ N  ·  ⌘ W', 'New window · close this window'],
          ['⌘ =  ·  ⌘ −  ·  ⌘ 0', 'Zoom in · out · actual size'],
          ['⌘ F  ·  ⌘ G  ·  ⇧⌘ G', 'Find on this page · next match · previous match (Esc closes)'],
        ] as ShortcutRow[])
      : ([
          ['Alt 1 … 0', 'Jump to the first ten pages'],
          [mac ? '⌘ [  ·  ⌘ ]' : 'Alt ←  ·  Alt →', 'Back · forward between pages and stock windows (browser history)'],
        ] as ShortcutRow[])),
    ['Shift N', 'News Catalyst Terminal'],
    ['?', 'This help'],
    ['Esc', 'Close the stock window, the command bar or any overlay'],
  ]
}

/** The status line's shortcut hint for the host (`mac`: a browser on macOS). */
export function footerHint(desktop: boolean, mac = false): string {
  if (desktop) return '⌘1…9 PAGES · ⌘[ ⌘] BACK/FWD · ⌘N WINDOW · ⇧N NEWS · ? HELP · ESC CLOSE'
  return mac
    ? 'ALT+1…0 PAGES · ⌘[ ⌘] BACK/FWD · SHIFT+N NEWS · ? HELP · ESC CLOSE'
    : 'ALT+1…0 PAGES · ALT+←/→ BACK/FWD · SHIFT+N NEWS · ? HELP · ESC CLOSE'
}

/** Tooltip of a page-strip tab (index 0-based; the 10th is Alt+0 in both hosts). */
export function tabKeyHint(index: number, desktop: boolean): string | undefined {
  if (index < 9) return desktop ? `⌘${index + 1} · Alt+${index + 1}` : `Alt+${index + 1}`
  if (index === 9) return 'Alt+0'
  return undefined
}
