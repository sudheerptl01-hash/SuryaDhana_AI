/**
 * Pure read models for the GOLD feed-honesty fixes (8 Nov 2026 RCA, lane G-FEED). No React, no DOM: importable by the
 * plain-node checks (`ui/components/__tests__/gold_feed.check.ts`) and type-checked by `cd ui && npx tsc --noEmit`.
 *
 *  - `cotOverdueWords` — the COT reports the store OWES (CT-03 / F2 / C-DATA-01). `next_release_*` keeps meaning the
 *    next UPCOMING release (API_CONTRACT §2.5, the Saturday digest prints it verbatim), so once a scheduled release
 *    passed with nothing stored the panel read "next Tue 17 Nov" and implied no report was due before then. The server
 *    now sends `latest.overdue`; this names the newest due report beside the release line.
 *  - `tapeDoiByDate` / `tapeScopeLabel` — the two scopes the MCX tape carries (CT-06): `doi` is the PICKED contract's
 *    ΔOI when the server read the Breeze daily bars, `doi_family` always the 07:35 master's sum over every expiry.
 *    WEEKLY printed the family sum under a per-expiry header, so it read −9,871 for GOLDM on 03 Nov (NOV −22,119 of
 *    expiry run-off + DEC +9,389) while POSITIONING said the traded DEC contract opened +9,389.
 *  - `settleStandIn` — which stand-in a settle cell holds, and nothing at all for an empty cell ('— PROXY' was printed
 *    on every blank row because `quality` defaults to 'proxy').
 *  - `coverageSubtitle` — 'US through Sat 07 Nov' for a panel subtitle (CT-04 / F3).
 *
 * Server fields are read structurally so ui/lib/gold/types.ts does not have to widen for them.
 */

/** One row of the server's `latest.overdue`: a report due by the CFTC calendar and not in the store. */
export interface CotOverdueRow { report_date: string; at?: string | null; ist?: string | null; source?: string | null }

/** The rows of `latest.overdue`, oldest first; `[]` when the store owes nothing (or the server is older than this fix). */
export function cotOverdueRows(latest: unknown): CotOverdueRow[] {
  const v = latest && typeof latest === 'object' ? (latest as Record<string, unknown>).overdue : null
  if (!Array.isArray(v)) return []
  return (v as CotOverdueRow[]).filter(r => !!r && typeof r.report_date === 'string')
}

/**
 * `overdue: Tue 03 Nov report due Sat 07 Nov 02:00 IST — not stored yet` (plus `· N reports behind` past one).
 * `dayLabel` is the caller's own day formatter so this module stays free of the date helpers. null when nothing is due.
 */
export function cotOverdueWords(latest: unknown, dayLabel: (d: string) => string | null | undefined): string | null {
  const od = cotOverdueRows(latest)
  if (!od.length) return null
  const due = od[od.length - 1]
  const more = od.length > 1 ? ` · ${od.length} reports behind` : ''
  return `overdue: ${dayLabel(due.report_date) || due.report_date} report due ${due.ist ?? '—'} — not stored yet${more}`
}

/**
 * The ΔOI a tape row carries in BOTH scopes, plus whether the family sum holds an expiring month's run-off.
 *
 * `fill` marks a session the server had no Breeze bar for: it kept the ICICI master's price and the all-expiry sum,
 * and `doi` — the PICKED contract's own ΔOI — is unknown there (checker, 8 Nov 2026: those rows used to carry the
 * family sum as `doi`, so WEEKLY printed the same −9,871 twice, once under a per-contract header).
 */
export interface TapeDoi { doi: number | null; family: number | null; familyMech: boolean; fill: string | null; note: string | null }

export function tapeDoiByDate(tape: readonly unknown[] | null | undefined): Map<string, TapeDoi> {
  const out = new Map<string, TapeDoi>()
  const n = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)
  const s = (v: unknown): string | null => (typeof v === 'string' && v ? v : null)
  for (const row of tape ?? []) {
    const r = (row ?? {}) as Record<string, unknown>
    const d = typeof r.trade_date === 'string' ? r.trade_date : null
    if (!d) continue
    out.set(d, { doi: n(r.doi), family: n(r.doi_family), familyMech: r.family_mechanical === true, fill: s(r.fill), note: s(r.note) })
  }
  return out
}

/** What the tape's ΔOI sums, as the SERVER labelled it ('GOLDM DEC-26' or 'all GOLDM expiries') — never invented here. */
export function tapeScopeLabel(data: unknown, family: string): string {
  const v = data && typeof data === 'object' ? (data as Record<string, unknown>).tape_oi_scope : null
  return typeof v === 'string' && v ? v : `all ${family} expiries`
}

/** What `doi_family` sums, as the SERVER labelled it: its own header, never the per-contract one. */
export function tapeFamilyScopeLabel(data: unknown, family: string): string {
  const v = data && typeof data === 'object' ? (data as Record<string, unknown>).tape_family_scope : null
  return typeof v === 'string' && v ? v : `all ${family} expiries`
}

/**
 * The tape's own first session when it differs from the ladder's `since` — the Breeze bars reach years further back
 * than the 07:35 master's history, and one printed range cannot describe both (PLAN §f.6). null when they agree.
 */
export function tapeSinceLabel(data: unknown): string | null {
  const o = data && typeof data === 'object' ? (data as Record<string, unknown>) : {}
  const tape = typeof o.tape_since === 'string' ? o.tape_since : null
  const since = typeof o.since === 'string' ? o.since : null
  return tape && tape !== since ? tape : null
}

/** Which stand-in a settle cell holds; null for an empty cell and for a real published settlement. */
export function settleStandIn(row: unknown): { text: string; why: string } | null {
  const r = (row ?? {}) as Record<string, unknown>
  const px = r.settle_or_close
  if (typeof px !== 'number' || !Number.isFinite(px)) return null
  const src = typeof r.settle_source === 'string' ? r.settle_source : null
  if (src === 'breeze_close') return { text: 'BREEZE CLOSE', why: "close of the Breeze daily bar (broker), not MCX's settlement" }
  if (src === 'breeze_vwap30') return { text: 'VWAP30 PROXY', why: "last-30-min VWAP of the Breeze 1-minute bars (MCX's DSP method), not the published settlement" }
  if (r.quality === 'proxy') return { text: 'BAND PROXY', why: "midpoint of the ICICI master's price band for the session it belongs to, not the published settlement" }
  return null
}

/** How far a feed's own window reaches; `state` drives the amber/dim tone of the note row. */
export interface FeedCoverage {
  state?: 'live' | 'delayed' | 'stale' | 'unavailable' | string | null
  note?: string | null
  covers_through_label?: string | null
  uncovered?: string[] | null
}

/** 'US through Sat 07 Nov' for a panel subtitle — the one place the coverage end is named beside the chip. */
export function coverageSubtitle(cov?: FeedCoverage | null): string | null {
  return cov?.covers_through_label ? `US through ${cov.covers_through_label}` : null
}

/** A coverage note is amber (something real is missing) rather than dim (a day or two not published yet). */
export function coverageIsAmber(cov?: FeedCoverage | null): boolean {
  return cov?.state === 'stale' || cov?.state === 'unavailable'
}
