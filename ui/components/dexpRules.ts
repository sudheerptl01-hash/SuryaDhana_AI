/**
 * DEXP grid annotations (5 Nov 2026 review m115). Pure, unit-tested under plain node by
 * ui/components/__tests__/honesty.check.ts.
 */

/** The fundamental columns of ml_features: one undated snapshot exists, so they are NULL on dated rows by design. */
export const FUNDAMENTAL_FEATURES: readonly string[] = [
  'trailing_pe', 'price_to_book', 'ev_to_ebitda', 'peg_ratio', 'revenue_growth', 'gross_margins', 'operating_margins',
  'profit_margins', 'return_on_equity', 'return_on_assets', 'debt_to_equity', 'current_ratio', 'altman_z',
  'insider_hold_pct', 'inst_hold_pct',
]

/** Columns whose every non-null value on the page equals an EARLIER column's (same row), with at least `minRows` rows
 *  compared: { duplicate → the column it repeats }. A page of nulls proves nothing, so it is never a duplicate. */
export function duplicateColumns(columns: readonly string[], rows: readonly Record<string, unknown>[], minRows = 10): Record<string, string> {
  const out: Record<string, string> = {}
  const numeric = columns.filter(c => c !== 'ticker' && c !== 'date' && rows.some(r => typeof r[c] === 'number'))
  for (let j = 0; j < numeric.length; j++) {
    const b = numeric[j]
    for (let i = 0; i < j; i++) {
      const a = numeric[i]
      if (out[a]) continue                       // compare against an original, never against a duplicate
      let n = 0
      let same = true
      for (const r of rows) {
        const x = r[a], y = r[b]
        if (x == null && y == null) continue
        if (typeof x !== 'number' || typeof y !== 'number' || Math.abs(x - y) > 1e-12 * Math.max(1, Math.abs(x))) { same = false; break }
        n++
      }
      if (same && n >= minRows) { out[b] = a; break }
    }
  }
  return out
}
