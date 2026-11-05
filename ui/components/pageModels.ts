/**
 * Small presentation rules for terminal pages (desktop review round 4, FEATURE_PARITY P5 / P11 / P16).
 *
 * Pure module (no React, no imports): unit-tested by ui/components/__tests__/pages.check.ts under plain node.
 */

// ── MOV: keep polling once the session opens (P5) ───────────────────────────────────────────────────────────

/**
 * MOV's 30 s movers refresh. It used to run only while the last reply said the market was open, so a page opened
 * before 09:15 (or left open overnight) got 'closed' once and never asked again: the table stayed on the previous
 * session all day. It now also polls whenever the client's NSE session clock says OPEN (`clientOpen`:
 * components/desktop/session.ts nseSession(now).state === 'OPEN', IST whatever the machine's zone), so the first
 * in-session reply brings it back to life.
 */
export function moversPollDue(serverMarketOpen: boolean | null | undefined, clientOpen: boolean): boolean {
  return serverMarketOpen !== false || clientOpen
}

// ── INSD: one order for the 'Who' categories (P16) ─────────────────────────────────────────────────────────

const CATEGORY_RANK = ['promoter', 'promoters', 'promoter and director', 'promoter group', 'promoter immediate relative',
  'director', 'directors immediate relative', 'kmp', 'key managerial personnel']

/**
 * data-service builds the list with DuckDB `string_agg(DISTINCT category, ', ')`, whose order is not defined, so the
 * same stock read 'Promoter, Promoter Group' on one refresh and 'Promoter Group, Promoter' on the next. Sorted
 * here: promoters first, then directors, then key managers, anything else alphabetically after them.
 */
export function orderCategories(text: string | null | undefined): string {
  const parts = [...new Set((text ?? '').split(',').map(x => x.trim()).filter(Boolean))]
  const rank = (c: string) => { const i = CATEGORY_RANK.indexOf(c.toLowerCase()); return i < 0 ? CATEGORY_RANK.length : i }
  return parts.sort((a, b) => rank(a) - rank(b) || a.localeCompare(b)).join(', ')
}

// ── ALERT form: show the saved levels (P11) ──────────────────────────────────────────────────────────────────

export interface AlertFields { up: string; down: string; move: string }
export interface AlertLevelsLike { above?: number | null; below?: number | null; move?: number | null }

const level = (v: number | null | undefined) => (v != null && v > 0 ? String(v) : '')

/**
 * The alert form's boxes after the saved levels arrive. The form mounts before useAlerts' first server read, so it
 * used to start (and stay) empty: a re-opened form showed blank boxes and SET then cleared the untouched levels.
 * Each box the user has not typed in takes the saved level; a box the user typed in keeps the typed text.
 */
export function alertFormFill(fields: AlertFields, touched: Readonly<Partial<Record<keyof AlertFields, boolean>>>,
  saved: AlertLevelsLike | null | undefined): AlertFields {
  if (!saved) return fields
  const next: AlertFields = {
    up: touched.up ? fields.up : level(saved.above),
    down: touched.down ? fields.down : level(saved.below),
    move: touched.move ? fields.move : level(saved.move),
  }
  return next.up === fields.up && next.down === fields.down && next.move === fields.move ? fields : next
}
