/**
 * Find on page (R9), the pure part: which key does what, how many matches, what the bar says. No React, no DOM:
 * unit-tested by `node ui/components/desktop/__tests__/desktop.check.ts`. The bar itself is FindBar.tsx.
 *
 * SuryaDhana.app only: WKWebView has no find UI of its own, so ⌘F opens the terminal's find bar (window.find()),
 * ⌘G / ⇧⌘G (or ↵ / ⇧↵ in the bar) go to the next / previous match, Esc closes it. A browser keeps its native ⌘F:
 * the bar is never mounted there. No menu accelerator claims ⌘F or ⌘G (desktop/src-tauri/src/menu.rs).
 */

export interface FindKeyEvent {
  key: string
  metaKey: boolean
  ctrlKey: boolean
  altKey: boolean
  shiftKey: boolean
}

export type FindShortcut = 'open' | 'next' | 'prev' | null

/** ⌘F → open (and select the query), ⌘G → next, ⇧⌘G → previous; anything else → null. */
export function findShortcut(e: FindKeyEvent): FindShortcut {
  if (!e.metaKey || e.ctrlKey || e.altKey) return null
  const k = (e.key || '').toLowerCase()
  if (k === 'f') return e.shiftKey ? null : 'open'
  if (k === 'g') return e.shiftKey ? 'prev' : 'next'
  return null
}

/** Case-insensitive, non-overlapping occurrences of `q` in `text` (the page's rendered text), capped at `cap`. */
export function countMatches(text: string, q: string, cap = 999): number {
  const needle = q.toLocaleLowerCase()
  if (!needle) return 0
  const hay = text.toLocaleLowerCase()
  let n = 0
  for (let i = hay.indexOf(needle); i !== -1 && n < cap + 1; i = hay.indexOf(needle, i + needle.length)) n++
  return n
}

/** The bar's status: '' (no query yet), 'NO MATCH', '1 MATCH', '12 MATCHES', '999+ MATCHES'. */
export function findStatus(q: string, found: boolean | null, count: number, cap = 999): string {
  if (!q || found === null) return ''
  if (!found || count === 0) return 'NO MATCH'
  if (count > cap) return `${cap}+ MATCHES`
  return count === 1 ? '1 MATCH' : `${count} MATCHES`
}
