/**
 * DESK momentum-watchlist layout (CT-03): every column (# · Stock · Industry · Last · 6M · 12M · Next event · P/E ·
 * Profit y/y) must be visible at the app's default 1600 px window and degrade gracefully down to the 1100 px
 * minimum, never with silently clipped columns.
 *
 * - Side by side (watchlist | Book vs NIFTY + Rules) only when the row is wide enough for the whole table next to
 *   a fixed-width side column; otherwise the watchlist goes full width and the side panels sit below it.
 * - Whatever still does not fit (long risk chips, a narrow window) scrolls inside the table, and the panel names
 *   the columns that are out of view (`hiddenHeaders`), so nothing is hidden without a cue.
 *
 * Pure module (no React, no imports): unit-tested by ui/components/__tests__/pages.check.ts under plain node.
 */

/**
 * Width the watchlist table needs for every column (Industry capped at INDUSTRY_MAX_W, 11.5 px tabular text), with
 * headroom: WebKit measured 973 px with live data (risk chips, 'RESULTS 27 OCT · 2d' badges) on 25 Oct, so 960 put
 * a 1,440 px window (row 1,412) side by side with PROFIT Y/Y scrolled out of view.
 */
export const WATCH_TABLE_W = 1000
/** The side column (Book vs NIFTY chart, Rules) next to the watchlist. */
export const DESK_SIDE_W = 440
/** Grid gap between the two. */
export const DESK_GAP = 10
/** Industry names ('Automobile and Auto Components') are cut with an ellipsis here; the full name is the title. */
export const INDUSTRY_MAX_W = 140

export type DeskWatchLayout = 'side' | 'stacked'

/** Side by side when the measured row width fits the whole table plus the side column; stacked otherwise. */
export function deskWatchLayout(rowW: number): DeskWatchLayout {
  return Number.isFinite(rowW) && rowW >= WATCH_TABLE_W + DESK_SIDE_W + DESK_GAP ? 'side' : 'stacked'
}

/** CSS grid template for the layout. */
export function deskGridColumns(layout: DeskWatchLayout): string {
  return layout === 'side' ? `minmax(0, 1fr) ${DESK_SIDE_W}px` : 'minmax(0, 1fr)'
}

export interface HeaderBox { label: string; left: number; right: number }

/**
 * Column headers not fully inside the visible scroll box [boxLeft, boxRight] (1 px tolerance), in table order:
 * those cut on the right (scroll right to see them) and on the left (scrolled past). Both empty = all in view.
 */
export function hiddenHeaders(boxLeft: number, boxRight: number, headers: readonly HeaderBox[]): { left: string[]; right: string[] } {
  return {
    left: headers.filter(h => h.left < boxLeft - 1).map(h => h.label),
    right: headers.filter(h => h.right > boxRight + 1 && !(h.left < boxLeft - 1)).map(h => h.label),
  }
}

const names = (xs: readonly string[]) => (xs.length > 3 ? `${xs.slice(0, 3).join(', ')} +${xs.length - 3}` : xs.join(', '))

/** The panel's cue for out-of-view columns: '⇢ scroll for NEXT EVENT, P/E' / '⇠ #, STOCK' ('' when all are in view). */
export function hiddenColumnsCue(hidden: { left: readonly string[]; right: readonly string[] }): string {
  const parts: string[] = []
  if (hidden.left.length) parts.push(`⇠ ${names(hidden.left)}`)
  if (hidden.right.length) parts.push(`⇢ scroll for ${names(hidden.right)}`)
  return parts.join(' · ')
}
