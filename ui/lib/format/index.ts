/**
 * Display formatting for prices, index levels and signed numbers on the terminal pages (C1-trader-ux-08).
 *
 * Rules (presentation only: no computed value changes, only how it is printed):
 * - Prices are printed the way the exchange shows them: NSE equity, index and MCX prices always with exactly
 *   2 decimals (311.65 stays 311.65, never 311.7; 22,600 prints 22,600.00), so a right-aligned column lines up
 *   on the decimal point.
 * - Indian digit grouping (en-IN: 1,44,376.00) everywhere, also for numbers inside server-built sentences.
 * - One minus glyph: U+2212 (−) for every negative number on screen. CSV exports turn it back into ASCII '-'
 *   (terminal kit downloadCsv) so spreadsheets still parse the numbers.
 * - Missing or non-finite values print as an em dash.
 *
 * Pure module (no React, no imports): unit-tested by ui/components/__tests__/pages.check.ts under plain node.
 */

/** U+2212 MINUS SIGN: the only minus glyph the terminal prints. */
export const MINUS = '−'

/** Exchange price precision: NSE equity, indices, MCX bullion. */
export const PRICE_DP = 2

const EM_DASH = '—'

const finite = (v: number | null | undefined): v is number => v != null && Number.isFinite(v)

/** |v| with en-IN grouping and exactly `dp` decimals; never "-0.00". */
function grouped(v: number, dp: number): string {
  return Math.abs(v).toLocaleString('en-IN', { minimumFractionDigits: dp, maximumFractionDigits: dp })
}

/** True when `v` prints as zero at `dp` decimals (so no sign is shown for −0.001 → 0.00). */
function roundsToZero(v: number, dp: number): boolean {
  return Number(Math.abs(v).toFixed(dp)) === 0
}

/** A number with fixed decimals, Indian grouping and the U+2212 minus: 125.99 → "125.99", -1234.5 → "−1,234.50". */
export function fmtFixed(v: number | null | undefined, dp: number = PRICE_DP): string {
  if (!finite(v)) return EM_DASH
  const neg = v < 0 && !roundsToZero(v, dp)
  return `${neg ? MINUS : ''}${grouped(v, dp)}`
}

/** A price as the exchange shows it (2 dp): 311.65 → "311.65", 22600 → "22,600.00". */
export function fmtPx(v: number | null | undefined, dp: number = PRICE_DP): string {
  return fmtFixed(v, dp)
}

/** A rupee price (2 dp): 311.65 → "₹311.65", −5 → "−₹5.00". */
export function fmtInrPx(v: number | null | undefined, dp: number = PRICE_DP): string {
  if (!finite(v)) return EM_DASH
  const neg = v < 0 && !roundsToZero(v, dp)
  return `${neg ? MINUS : ''}₹${grouped(v, dp)}`
}

/** An index level (NIFTY, BANKNIFTY, sector indices): always 2 dp, like NSE prints it. */
export function fmtIdx(v: number | null | undefined): string {
  return fmtFixed(v, PRICE_DP)
}

/** A signed number with an explicit '+' (and U+2212 for negatives): +12.50 / −3.25 / 0.00. */
export function fmtSigned(v: number | null | undefined, dp: number = PRICE_DP): string {
  if (!finite(v)) return EM_DASH
  if (roundsToZero(v, dp)) return grouped(0, dp)
  return `${v > 0 ? '+' : MINUS}${grouped(v, dp)}`
}

/** A signed rupee amount: +₹1,234 / −₹1,234 / ₹0 (`dp` decimals, Indian grouping, U+2212). */
export function fmtSignedInr(v: number | null | undefined, dp = 0): string {
  if (!finite(v)) return EM_DASH
  if (roundsToZero(v, dp)) return `₹${grouped(0, dp)}`
  return `${v > 0 ? '+' : MINUS}₹${grouped(v, dp)}`
}

/** Replace ASCII hyphen-minus in front of a number with U+2212 ("-1.23%" → "−1.23%"); other hyphens stay. */
export function unicodeMinus(text: string): string {
  return text.replace(/(^|[\s(₹$:=/])-(?=[\d.])/g, `$1${MINUS}`)
}

/** Back to ASCII for machine-readable output (CSV): every U+2212 becomes '-'. */
export function asciiMinus(text: string): string {
  return text.replace(/−/g, '-')
}

/**
 * Re-group numbers written with Western thousands separators inside a server-built sentence into Indian
 * grouping, e.g. "within ₹300 of ₹144,376" → "within ₹300 of ₹1,44,376". Only numbers that are clearly
 * Western-grouped (1–3 digits, then groups of exactly 3) are touched, and their decimals are kept as written,
 * so dates, years, times, ratios and already-Indian numbers ("1,44,376") are left alone.
 */
export function indianGrouping(text: string): string {
  // RUP-07: no regex lookbehind (WebKit < 16.4, i.e. macOS 13.0–13.2, cannot parse it and this module is in the
  // kit chunk every page loads): the character before the number is matched as group 1 and written back
  return text.replace(/(^|[^\d,.])(\d{1,3}(?:,\d{3})+)(\.\d+)?(?!\d|,\d)/g, (m, pre: string, int: string, dec: string | undefined) => {
    const n = Number(int.replace(/,/g, ''))
    if (!Number.isSafeInteger(n)) return m
    return `${pre}${n.toLocaleString('en-IN')}${dec ?? ''}`
  })
}

// ── default date inputs (C1-trader-ux-18: no stale hard-coded ranges) ───────────────────────────

/** Today's date in IST as YYYY-MM-DD (the NSE calendar day), whatever the machine's time zone. */
export function istDateISO(now: Date = new Date()): string {
  return now.toLocaleDateString('en-CA', { timeZone: 'Asia/Kolkata' })
}

/**
 * A file-name time stamp in IST, whatever the machine's time zone: 2026-10-25-21-40-05 (P16: BTST exports were
 * named with toISOString(), i.e. UTC, so an evening export carried a time 5 h 30 m behind the clock).
 */
export function istFileStamp(now: Date = new Date()): string {
  const p = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Kolkata', year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).formatToParts(now).map(x => [x.type, x.value]))
  return `${p.year}-${p.month}-${p.day}-${p.hour}-${p.minute}-${p.second}`
}

/** `iso` (YYYY-MM-DD) moved by `months` calendar months, clamped to the target month's last day. */
export function shiftMonthsISO(iso: string, months: number): string {
  const [y, m, d] = iso.split('-').map(Number)
  const total = y * 12 + (m - 1) + months
  const ty = Math.floor(total / 12), tm = total - ty * 12
  const last = new Date(Date.UTC(ty, tm + 1, 0)).getUTCDate()
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${ty}-${pad(tm + 1)}-${pad(Math.min(d, last))}`
}

/** A default [from, to] input range ending today (IST): `months` long. */
export function trailingRange(months: number, now: Date = new Date()): { from: string; to: string } {
  const to = istDateISO(now)
  return { from: shiftMonthsISO(to, -months), to }
}

// ── closed-market wording (C1-trader-ux-13) ────────────────────────────────────────────────────

/**
 * 'today' only while NSE is open; a closed market names the session the numbers are from, from NSE's live-analysis
 * timestamp: ('23-Oct-2026 16:00:00', closed) → 'last session (23 Oct)'. Unknown open state counts as open.
 */
export function sessionWord(marketOpen: boolean | null | undefined, timestamp: string | null | undefined): string {
  if (marketOpen !== false) return 'today'
  const m = /^(\d{1,2})-([A-Za-z]{3})-\d{4}/.exec(timestamp ?? '')
  return m ? `last session (${m[1].padStart(2, '0')} ${m[2]})` : 'last session'
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/**
 * 'today' when `day` (YYYY-MM-DD, the session the numbers are from) is today's IST date, else 'on 23 Oct':
 * intraday samples on a weekend, a holiday or before the open are the last session's (MOV market internals).
 */
export function sessionDayLabel(day: string | null | undefined, today: string = istDateISO()): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(day ?? '')
  if (!m || day === today || +m[2] < 1 || +m[2] > 12) return 'today'
  return `on ${m[3]} ${MONTHS[+m[2] - 1]}`
}

// ── one unit per column for counts (CT-11 / C1-trader-ux-08) ──────────────────────────────────

/** An Indian unit for a whole column of counts (shares, contracts). */
export interface CountUnit { div: number; suffix: string; dp: number }

/**
 * The unit for a column, picked once from its largest magnitude: plain counts below 1 lakh, lakh (1 dp) up to
 * 100 crore, crore (2 dp) above. Every cell of the column then uses it, so '1.13 cr' never sits above '85.5 L'
 * (an order-of-magnitude misread when the eye compares right-aligned digits).
 */
export function countUnit(values: readonly (number | null | undefined)[]): CountUnit {
  const m = Math.max(0, ...values.filter(finite).map(v => Math.abs(v)))
  if (m >= 1e9) return { div: 1e7, suffix: ' cr', dp: 2 }
  if (m >= 1e5) return { div: 1e5, suffix: ' L', dp: 1 }
  return { div: 1, suffix: '', dp: 0 }
}

/** A count in its column's unit, en-IN grouping, U+2212 minus; `signed` adds '+' for increases. */
export function fmtCount(v: number | null | undefined, unit: CountUnit, signed = false): string {
  if (!finite(v)) return EM_DASH
  const x = v / unit.div
  if (roundsToZero(x, unit.dp)) return `${grouped(0, unit.dp)}${unit.suffix}`
  return `${x < 0 ? MINUS : signed ? '+' : ''}${grouped(x, unit.dp)}${unit.suffix}`
}
