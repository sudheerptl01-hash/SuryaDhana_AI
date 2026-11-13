/**
 * GPLN — Morning Game Plan, the pure view model (terminal_final PLAN W7 / F-11, wave E).
 *
 * Everything here runs under plain node (type stripping) for __tests__/gameplan.check.ts: payload typing,
 * the per-tile SourceChip mapping, small formatters and the one-number-once-per-page dedupe (an EXPIRY row in
 * the events tile whose date the chain tile already prints is dropped). No React, no DOM, no fetch.
 *
 * Labelling rules (PLAN §1, binding): badges come FROM the payload (`context` / `arithmetic`); no direction
 * words in any string this module produces; context is never coloured — tone stays with the kit's neutral chips.
 *
 * Import-free on purpose (like disciplineModel.ts / volModel.ts): plain node runs this file directly, so the
 * SourceChip mapping is returned as a PLAN the React layer feeds into the kit's `sourceOf` (one chip logic,
 * owned by terminal/source.ts — never re-implemented here).
 */

export interface Tile {
  ok: boolean
  badge: string
  source?: string
  as_of?: string | null
  error?: string
  [k: string]: unknown
}

export interface GiftBlock { last?: number | null; implied_gap_pct?: number | null; time?: string | null; as_of?: string | null }
export interface GoldBlock {
  symbol?: string; last?: number | null; last_date?: string | null; prev_close?: number | null
  prev_date?: string | null; change_pct?: number | null; partial?: boolean
}
export interface EcoRow { date?: string | null; kind?: string | null; what?: string | null; time?: string | null }
export interface CorpBlock { count?: number; date?: string; rows?: { symbol?: string; date?: string; kind?: string; label?: string }[] }
export interface FireRow { symbol?: string | null; series?: string | null; at?: string | null; text?: string | null }

export interface GamePlanPayload {
  symbol: string
  date: string
  as_of: string
  symbols: string[]
  tiles: Record<'overnight' | 'levels' | 'oi' | 'iv' | 'events' | 'focus', Tile>
  badges: Record<string, string>
  note: string
  feeds: string
}

export const TILE_ORDER = ['overnight', 'levels', 'oi', 'iv', 'events', 'focus'] as const
export type TileKey = (typeof TILE_ORDER)[number]

/** Panel titles — facts, never a call. */
export const TILE_TITLES: Readonly<Record<TileKey, string>> = Object.freeze({
  overnight: 'Overnight moves',
  levels: 'Prior session',
  oi: 'Chain · OI walls & max pain',
  iv: 'IV regime vs prior session',
  events: 'Today’s events',
  focus: 'Focus list',
})

/** The page's mandatory footer line (PLAN §1). */
export const PAGE_NOTE = 'assembled from stored/live reads — describes, does not predict'

/**
 * The SourceChip plan of one tile: its own as-of and source, `dead` when the read failed (the React layer
 * renders a dead plan as OFFLINE with the calm error as the hint, and feeds a live plan into `sourceOf`).
 */
export interface TileChipPlan { dead: boolean; asOf: string | null; source: string | null; hint: string | null }

export function tileChipPlan(tile: Tile | undefined): TileChipPlan {
  if (!tile) return { dead: true, asOf: null, source: null, hint: 'tile missing from the payload' }
  if (!tile.ok) return { dead: true, asOf: tile.as_of ?? null, source: tile.source ?? null, hint: tile.error ?? 'read failed' }
  return { dead: false, asOf: tile.as_of ?? null, source: tile.source ?? null, hint: null }
}

/** Indian-grouped number ('26,050'), em dash when absent. */
export function num(v: number | null | undefined, digits = 0): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return v.toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

/** '+0.21%' / '—' (a signed fact, not a tone). */
export function pct(v: number | null | undefined, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}%`
}

/** '+0.3' points ('—' when absent). */
export function pts(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return '—'
  return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}`
}

/** 'YYYY-MM-DD…' → 'DD Mon' ('' when unparsable). */
export function day(iso: string | null | undefined): string {
  const s = String(iso ?? '').slice(0, 10)
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s)
  if (!m) return ''
  const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const mo = +m[2]
  if (mo < 1 || mo > 12) return ''
  return `${+m[3]} ${MONTHS[mo - 1]}`
}

/**
 * One number once per page: the chain tile already prints its expiry date, so an eco EXPIRY row on that same
 * date is dropped from the events tile (every other row passes through untouched).
 */
export function dedupeEcoRows(eco: EcoRow[] | undefined, oiExpiry: string | null | undefined): EcoRow[] {
  const exp = String(oiExpiry ?? '').slice(0, 10)
  return (eco ?? []).filter(e => !(exp && e?.kind === 'EXPIRY' && String(e?.date ?? '').slice(0, 10) === exp))
}

/** The watchlist line: first 8 names + a '+N' tail ('empty' when none). */
export function watchlistLine(names: string[] | undefined): string {
  const xs = (names ?? []).filter(s => typeof s === 'string' && s)
  if (!xs.length) return 'empty — add names on WTCH'
  return xs.slice(0, 8).join(', ') + (xs.length > 8 ? ` +${xs.length - 8}` : '')
}
