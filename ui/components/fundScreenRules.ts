/**
 * FUND screener guards (5 Nov 2026 review m080 / m081). Pure, unit-tested under plain node by
 * ui/components/__tests__/honesty.check.ts.
 *
 * - outlierReason: growth this large usually means a low base, a one-off gain, a merger / demerger or a parsing
 *   artefact (COALINDIA revenue +199.6 %, SIEMENS profit +406.2 % on revenue +8.4 %). The row is flagged
 *   "verify on FA", never silently hidden or silently trusted. A house rule: badge heuristic.
 * - staleRow: a company two or more quarters behind the newest reported quarter is not "late this season": it is
 *   almost always merged, delisted or suspended (TATACOFFEE, TINPLATE on Q2 FY24). Those rows are hidden by default.
 */

export interface GrowthRow { revenue_yoy: number | null; pat_yoy: number | null; period_end: string }

export const OUTLIER_RULE = Object.freeze({ revUp: 100, revDown: -50, patUp: 300, patUpRevBelow: 50 })
/** Days behind the newest quarter from which a row counts as stale (two quarters ≈ 182 days; 150 leaves slack). */
export const STALE_DAYS = 150

/** Signed with U+2212 for losses (the kit's rule; this module stays import-free for plain node). */
const signed = (v: number, dp: number): string => `${v > 0 ? '+' : v < 0 ? '\u2212' : ''}${Math.abs(v).toFixed(dp)}`

export function outlierReason(r: GrowthRow): string | null {
  const { revenue_yoy: rv, pat_yoy: pt } = r
  if (rv != null && rv >= OUTLIER_RULE.revUp) return `revenue ${signed(rv, 1)}% y/y: a merger, a low base or a parsing artefact; verify on FA`
  if (rv != null && rv <= OUTLIER_RULE.revDown) return `revenue ${signed(rv, 1)}% y/y: a demerger, a sale or a parsing artefact; verify on FA`
  if (pt != null && pt >= OUTLIER_RULE.patUp && (rv == null || rv < OUTLIER_RULE.patUpRevBelow))
    return `profit ${signed(pt, 0)}% on revenue ${rv == null ? 'n/a' : `${signed(rv, 1)}%`}: usually a one-off gain or a low base; verify on FA`
  return null
}

export function daysBetween(a: string, b: string): number {
  return Math.round((new Date(`${b}T00:00:00Z`).getTime() - new Date(`${a}T00:00:00Z`).getTime()) / 86_400_000)
}

export function staleRow(periodEnd: string, latestQ: string | null): boolean {
  return !!latestQ && daysBetween(periodEnd, latestQ) >= STALE_DAYS
}
