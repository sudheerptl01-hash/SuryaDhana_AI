/**
 * The page strip, re-cut for the trader's day (page review 5 Nov 2026, M37). Pure: no React, no DOM, no imports, so
 * `node ui/components/desktop/__tests__/desktop.check.ts` runs it directly.
 *
 *   numbered slots (Alt 1 … 0 follow the strip, ⌘1 … 9 in SuryaDhana.app follow the native Go menu, see below):
 *     BRF WTCH CHRT OMON OSTR DERV MOV EVTS ALRT RSK · then GOLD MCXG MKT DESK
 *   RESEARCH ▾  the research / legacy pages (OVRV EQS BTST PIPE LWSC ALFA GBOX MLEN DEXP WHSE RSCH PORT)
 *   MORE ▾      every other page (WEI ECO MEMB SEAG PRE CF DEAL MRGN FUND HDS INSD IPO WRAP COMP BRKR CMDT SYS)
 *
 * The owner can re-order, add and remove strip pages: the order lives in the SYNC prefs key `strip.order.v1` (a JSON
 * array of page ids, lib/prefs/keys.ts), so the app, every browser and every window share it. A page outside the
 * strip goes to RESEARCH ▾ when it is a research page, else to MORE ▾. Nothing here creates or removes a page: the 43
 * pages and their codes stay those of COMMAND_PAGES (ui/app/page.tsx) and desktop/src-tauri/src/pages.rs.
 *
 * ⌘ digits in the app: the native Go menu binds ⌘1 … 9 to the DEFAULT strip's first nine pages (pages.rs `shortcut`);
 * a re-ordered strip keeps its Alt digits, and a slot shows ⌘N only while the native digit opens that same page.
 */

export const STRIP_ORDER_KEY = 'strip.order.v1'
export const STRIP_ORDER_EVENT = 'suryadhana:strip-order'

/** The default strip: the trader's day, left to right (M37). Slots 1 … 9 and 0 are the first ten. */
export const DEFAULT_STRIP: readonly string[] = Object.freeze([
  'brief', 'watch', 'charts', 'options', 'ostrategy', 'derivatives', 'movers', 'events', 'alerts', 'risk',
  'gold', 'mcxgold', 'markets', 'desk',
])

/** Research and legacy pages: under RESEARCH ▾ unless the owner put them on the strip. */
export const RESEARCH_PAGES: readonly string[] = Object.freeze([
  'overview', 'stocks', 'backtest', 'pipeline', 'scanner', 'discovery', 'glassbox', 'mlengine', 'explorer', 'warehouse',
  'research', 'positions',
])

/** Most pages the strip holds (the rest stay one click away under the menus and on GO). */
export const MAX_STRIP = 20

const ID_RE = /^[a-z]{2,20}$/

/**
 * A stored strip order → a clean list of known page ids (unknown, duplicate and malformed entries dropped, capped at
 * MAX_STRIP), or null when nothing usable is stored (the caller then uses DEFAULT_STRIP). Never throws.
 */
export function parseStripOrder(raw: string | null | undefined, known: readonly string[]): string[] | null {
  if (!raw) return null
  let v: unknown
  try { v = JSON.parse(raw) } catch { return null }
  const list = Array.isArray(v) ? v : v && typeof v === 'object' && Array.isArray((v as { order?: unknown }).order) ? (v as { order: unknown[] }).order : null
  if (!list) return null
  const ok = new Set(known)
  const out: string[] = []
  for (const x of list) {
    if (typeof x !== 'string' || !ID_RE.test(x) || !ok.has(x) || out.includes(x)) continue
    out.push(x)
    if (out.length >= MAX_STRIP) break
  }
  return out.length ? out : null
}

/** The strip to show: the stored order when usable, else the default (only pages that exist). */
export function resolveStrip(raw: string | null | undefined, known: readonly string[]): string[] {
  return parseStripOrder(raw, known) ?? DEFAULT_STRIP.filter(id => known.includes(id))
}

/** Pages for the two menus, in `known` order: research pages off the strip, and everything else off the strip. */
export function splitMenus(strip: readonly string[], known: readonly string[]): { research: string[]; more: string[] } {
  const on = new Set(strip)
  const research = known.filter(id => !on.has(id) && RESEARCH_PAGES.includes(id))
  const more = known.filter(id => !on.has(id) && !RESEARCH_PAGES.includes(id))
  return { research, more }
}

/** Move one page up (−1) or down (+1); unchanged at the ends or when absent. */
export function moveInStrip(strip: readonly string[], id: string, delta: -1 | 1): string[] {
  const i = strip.indexOf(id)
  const j = i + delta
  if (i < 0 || j < 0 || j >= strip.length) return [...strip]
  const out = [...strip]
  ;[out[i], out[j]] = [out[j], out[i]]
  return out
}

/** Add a page at the end (no duplicates, capped). */
export function addToStrip(strip: readonly string[], id: string): string[] {
  if (strip.includes(id) || strip.length >= MAX_STRIP || !ID_RE.test(id)) return [...strip]
  return [...strip, id]
}

/** Remove a page (the strip always keeps at least one page). */
export function removeFromStrip(strip: readonly string[], id: string): string[] {
  if (strip.length <= 1) return [...strip]
  return strip.filter(x => x !== id)
}

/** The digit of a strip slot: '1' … '9', then '0' for the tenth, null after. */
export function slotDigit(index: number): string | null {
  if (index >= 0 && index < 9) return String(index + 1)
  return index === 9 ? '0' : null
}

/** Strip index for an Alt+digit key code ('Digit1' … 'Digit9', 'Digit0'), or -1. */
export function slotForDigitCode(code: string): number {
  const m = /^Digit([0-9])$/.exec(code)
  if (!m) return -1
  return m[1] === '0' ? 9 : Number(m[1]) - 1
}

/** True when the app's native ⌘(index+1) opens the page in this slot (the native menu follows DEFAULT_STRIP). */
export function nativeCmdMatches(strip: readonly string[], index: number): boolean {
  return index >= 0 && index < 9 && strip[index] === DEFAULT_STRIP[index]
}

/** The tooltip of a strip slot: Alt+N always (both hosts), ⌘N in the app only while the native digit opens the same page. */
export function slotKeyHint(strip: readonly string[], index: number, desktop: boolean): string | undefined {
  const d = slotDigit(index)
  if (!d) return undefined
  return desktop && nativeCmdMatches(strip, index) ? `⌘${d} · Alt+${d}` : `Alt+${d}`
}

/** Same order as the default? (the editor's RESET is then disabled, and nothing needs storing) */
export function isDefaultStrip(strip: readonly string[]): boolean {
  return strip.length === DEFAULT_STRIP.length && strip.every((id, i) => id === DEFAULT_STRIP[i])
}
