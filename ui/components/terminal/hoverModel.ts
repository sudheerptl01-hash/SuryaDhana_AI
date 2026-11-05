/**
 * The ticker hover card's stored half (live program, reports/live_nse): the 52-week range and the one-month sparkline
 * come from NSE's own bhavcopy (`/api/stocks/{t}/history`, EOD), not from Yahoo, and say so. The live half (price,
 * day move, day range, time + source line) is lib/liveQuotes.ts. Pure, no DOM, no React (unit-tested by
 * ui/components/__tests__/live.check.ts).
 */

export interface HistRow { date: string; close: number | null; change_pct: number | null }

export interface HoverHistory {
  /** 52-week high / low on split- and bonus-adjusted prices (NSE bhavcopy), null when unknown */
  high_52w: number | null
  low_52w: number | null
  /** the last SPARK_SESSIONS daily closes, oldest first, adjusted so a split is not a cliff */
  spark: number[]
  /** the last session in the store ('YYYY-MM-DD') */
  last_date: string | null
}

export const SPARK_SESSIONS = 22

/**
 * Daily rows (NEWEST FIRST, as /history returns them; `change_pct` on adjusted closes) → adjusted closes, oldest first.
 * Walking back from the latest raw close with each day's adjusted change keeps a split / bonus from showing as a crash;
 * a day without a change falls back to the ratio of raw closes.
 */
export function adjustedSpark(rows: readonly HistRow[], n = SPARK_SESSIONS): number[] {
  const out: number[] = []
  let prevAdj: number | null = null
  let prevRow: HistRow | null = null
  for (const r of rows) {
    if (out.length >= n) break
    if (r.close == null || !Number.isFinite(r.close) || r.close <= 0) continue
    let adj: number
    if (prevAdj == null || prevRow == null) adj = r.close
    else if (prevRow.change_pct != null && Number.isFinite(prevRow.change_pct) && prevRow.change_pct > -100) adj = prevAdj / (1 + prevRow.change_pct / 100)
    else adj = prevRow.close ? prevAdj * (r.close / prevRow.close) : r.close
    out.push(Math.round(adj * 100) / 100)
    prevAdj = adj
    prevRow = r
  }
  return out.reverse()
}

/** The history payload → the hover card's stored half. */
export function hoverHistory(h: { rows?: readonly HistRow[] | null; summary?: { high: number | null; low: number | null; to: string } | null } | null | undefined): HoverHistory | null {
  if (!h || !h.rows?.length) return null
  return {
    high_52w: h.summary?.high ?? null,
    low_52w: h.summary?.low ?? null,
    spark: adjustedSpark(h.rows),
    last_date: h.summary?.to ?? h.rows[0]?.date ?? null,
  }
}

/** Where `price` sits in [low, high] (0–1, clipped), null when either end is unknown or the range is empty. */
export function rangePos(price: number | null | undefined, low: number | null | undefined, high: number | null | undefined): number | null {
  if (price == null || low == null || high == null || !(high > low)) return null
  return Math.max(0, Math.min(1, (price - low) / (high - low)))
}

/** '04 NOV' for '2026-11-04'; '' when unparsable. */
export function shortDay(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '')
  if (!m) return ''
  const MON = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
  const mo = Number(m[2])
  return mo >= 1 && mo <= 12 ? `${m[3]} ${MON[mo - 1]}` : ''
}

/**
 * The fallback line when the live NSE service does not answer at all (404 before deploy, or down): whatever the
 * old quotes route says about itself. A row that names its own source/state (the live-backed route) is printed as
 * such; a bare Yahoo row says YAHOO · DELAYED with its last trade time, never LIVE.
 */
export function fallbackLine(q: { source?: unknown; state?: unknown; age_s?: unknown; market_time?: unknown; gmtoffset?: unknown } | null | undefined): string {
  if (!q) return 'no quote'
  const src = typeof q.source === 'string' && q.source ? q.source : null
  const st = typeof q.state === 'string' && q.state ? q.state : null
  if (src && src !== 'yahoo' && st) {
    const name = src === 'breeze_ws' ? 'BREEZE' : src === 'nse_api' ? 'NSE' : src === 'eod' ? 'NSE EOD' : src.toUpperCase()
    const age = typeof q.age_s === 'number' && Number.isFinite(q.age_s) ? ` · ${Math.round(q.age_s)}s old` : ''
    return `${name} ${st === 'live' ? 'LIVE' : st.toUpperCase()}${age}`
  }
  const t = typeof q.market_time === 'number' && Number.isFinite(q.market_time) ? q.market_time : null
  if (t == null) return 'YAHOO · DELAYED · time n/a'
  const ist = new Date(t * 1000 + 330 * 60_000).toISOString().slice(11, 19)
  return `YAHOO · DELAYED · last trade ${ist} IST`
}
