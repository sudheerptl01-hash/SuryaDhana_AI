/**
 * Small pure helpers of the 6 Nov 2026 honesty sweep (MLEN, GBOX, WHSE). Import-free, so
 * ui/components/__tests__/honesty.check.ts runs them under plain node.
 */

/** The restart freeze windows (CLAUDE.md), in IST: a heavy run inside one waits for an explicit "run anyway". */
export function inFreezeWindowIST(now: Date = new Date()): string | null {
  const ist = new Date(now.getTime() + 330 * 60_000)              // UTC → IST wall clock, read with getUTC*
  const m = ist.getUTCHours() * 60 + ist.getUTCMinutes()
  if (m >= 7 * 60 + 45 && m < 9 * 60 + 20) return '07:45–09:20 IST (ICICI login + pre-open jobs)'
  if (m >= 18 * 60 + 30 && m < 21 * 60 + 15) return '18:30–21:15 IST (EOD pipeline, desk, shadow, wrap)'
  return null
}

const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** "2026-02-05" → "5 Feb 2026": no day / month ambiguity (GBOX m116). Anything else comes back unchanged. */
export function longDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  if (!m) return iso
  const mon = MON[Number(m[2]) - 1]
  return mon ? `${Number(m[3])} ${mon} ${m[1]}` : iso
}

/** The freshness cell of WHSE's dataset table from a data-health catalog row (m114): text, tone and hover. */
export interface CatalogRowLike { state: string; lag_sessions: number | null; note?: string; expected_by?: string | null }
export function catalogFreshness(h: CatalogRowLike): { text: string; tone: 'ok' | 'warn' | 'bad'; title: string } {
  const lag = h.lag_sessions
  const behind = lag == null ? '' : ` · ${lag} sess`
  const title = `${h.note || h.state}${h.expected_by ? ` · expected by ${h.expected_by} IST` : ''} · catalog verdict (SYS › DATA)`
  if (h.state === 'fresh' || h.state === 'live') return { text: `OK${behind}`, tone: 'ok', title }
  if (h.state === 'amber') return { text: `AMBER${behind}`, tone: 'warn', title }
  if (h.state === 'gap') return { text: `GAP${behind}`, tone: 'bad', title }
  return { text: `⚠ STALE${behind}`, tone: 'bad', title }
}
