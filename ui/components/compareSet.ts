/**
 * COMP compare-set edits (C3-logic-unchanged-02): pure helpers so an edit can be applied to the LATEST saved set
 * ("merge on write") instead of the copy a window read when it mounted. Max 8 symbols, no duplicates, order kept.
 * Pure module: unit-tested by ui/components/__tests__/pages.check.ts under plain node.
 */
export const COMPARE_MAX = 8

/** `base` plus `sym` (when not already there and below the cap); `base` itself when nothing changes. */
export function compareAdd(base: readonly string[], sym: string): string[] {
  const s = sym.trim().toUpperCase()
  if (!s || base.includes(s) || base.length >= COMPARE_MAX) return base as string[]
  return [...base, s]
}

/** `base` without `sym`; `base` itself when it was not there. */
export function compareRemove(base: readonly string[], sym: string): string[] {
  return base.includes(sym) ? base.filter(x => x !== sym) : (base as string[])
}

/** Same symbols in the same order. */
export function sameList(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((x, i) => x === b[i])
}

/** The symbols of a stored compare-set string, or null when nothing is stored or it cannot be read. */
export function parseCompareSyms(raw: string | null): string[] | null {
  if (raw == null) return null
  try {
    const v = JSON.parse(raw) as { syms?: unknown }
    return Array.isArray(v?.syms) && v.syms.every(x => typeof x === 'string') ? (v.syms as string[]).slice(0, COMPARE_MAX) : null
  } catch { return null }
}

/**
 * The set an add / ✕ applies to (merge on write). `shown` is this window's set, `raw` the stored string now and
 * `known` the string this window last read or wrote. When another window wrote since (raw ≠ known and readable),
 * its set; otherwise this window's own. RUP-03: an emptied set is never written, so storage can still hold the
 * symbol the user just removed: it must not come back on the next add. An unreadable stored value never merges
 * into the default set either.
 */
export function compareBase(shown: readonly string[], raw: string | null, known: string | null): string[] {
  const stored = raw !== known ? parseCompareSyms(raw) : null
  return [...(stored ?? shown)]
}
