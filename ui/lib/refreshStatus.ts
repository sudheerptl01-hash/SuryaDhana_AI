/**
 * UPDATE DATA outcome (CT-04, round 4b). Pure, no imports: unit-tested by
 * `node ui/components/desktop/__tests__/desktop.check.ts`.
 *
 * The universe download runs in ui-api (routers/dashboard.py _do_refresh_background) and its progress lives in
 * ui-api's memory: a ui-api restart mid-download (watchdog hang restart, crash) resets /api/dashboard/refresh-status
 * to {active: false, total: 0}. "Not active" is therefore not "complete". COMPLETE needs positive evidence: the
 * status is not active, it covers stocks (total > 0), every stock has an outcome (done + current + errors = total)
 * and, when this window started the download, it is the same size as the one it started. Anything else is
 * STATUS UNKNOWN with the reason.
 */

export interface RefreshStatusLike {
  active?: unknown
  total?: unknown
  done?: unknown
  current?: unknown
  errors?: unknown
}

export type RefreshVerdict =
  | { kind: 'running' }
  | { kind: 'complete'; failed: number }
  | { kind: 'unknown'; reason: string }

const n = (v: unknown): number => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : 0)

/** What a refresh-status reply proves. `expectedTotal`: the stock count the start request reported (null: unknown). */
export function refreshVerdict(st: RefreshStatusLike | null | undefined, expectedTotal: number | null = null): RefreshVerdict {
  if (!st || typeof st !== 'object') return { kind: 'unknown', reason: 'no status from ui-api' }
  if (st.active === true) return { kind: 'running' }
  const total = n(st.total)
  if (total === 0) return { kind: 'unknown', reason: 'progress was lost (ui-api restarted?)' }
  if (expectedTotal !== null && expectedTotal > 0 && total !== expectedTotal) {
    return { kind: 'unknown', reason: `the status is for another download (${total} stocks, not ${expectedTotal})` }
  }
  const failed = n(st.errors)
  if (n(st.done) + n(st.current) + failed !== total) {
    return { kind: 'unknown', reason: 'the download stopped before every stock had a result' }
  }
  return { kind: 'complete', failed }
}
