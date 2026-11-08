/**
 * Pure helpers for the GOLD sub-views built by B4B (POSITIONING, PHYSICAL, MACRO, LEARN): wording, unit arithmetic,
 * freshness labels and the labelling rules of reports/gold_program/PLAN.md §f, kept out of React so the node check
 * (`ui/components/__tests__/gold_views.check.ts`) can exercise them under plain node.
 *
 * Rules carried here:
 *  - signed numbers use U+2212 (never ASCII '-') on screen (C1-trader-ux-18);
 *  - context metrics get the neutral token (`contextTone` is always T.muted-like); green/red is reserved for price
 *    changes and the arithmetic fair-vs-live comparison; this module never emits the words "bull…"/"bear…";
 *  - the CFTC "who did what" wording: Δlong < 0 closed longs · Δshort < 0 covered shorts · Δlong > 0 new longs ·
 *    Δshort > 0 new shorts (SOURCES.md §10 M14);
 *  - the crowd gauge is worded "crowdedness, not a signal" (M17/M18, G-STUDY FAIL).
 *
 * No imports: safe for the node check (type stripping only).
 */

export const MINUS = '−'
export const OZ_G = 31.1034768
export const CONTRACT_OZ = 100

// ── numbers ─────────────────────────────────────────────────────────────────────────────────────

const finite = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)

/**
 * Western (thousands) grouping for contracts, ounces, tonnes and dollars — the convention of every gold desk and of the
 * server's own verdict sentence ("funds net 105,562"); only rupees take the Indian lakh grouping (`inr`). C-TRADER-20.
 * `dp` decimals, U+2212 for negatives, '—' for null.
 */
export function num(v: number | null | undefined, dp = 0): string {
  if (!finite(v)) return '—'
  const s = Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp })
  return v < 0 ? `${MINUS}${s}` : s
}

/** Signed: '+1,234' / '−1,234' / '0'. A value that rounds to zero prints without a sign. */
export function signed(v: number | null | undefined, dp = 0): string {
  if (!finite(v)) return '—'
  const r = Number(v.toFixed(dp))
  if (r === 0) return (0).toFixed(dp)
  const s = Math.abs(r).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp })
  return r > 0 ? `+${s}` : `${MINUS}${s}`
}

export function signedPct(v: number | null | undefined, dp = 2): string {
  return finite(v) ? `${signed(v, dp)}%` : '—'
}

export function pct(v: number | null | undefined, dp = 1): string {
  return finite(v) ? `${num(v, dp)}%` : '—'
}

/** ₹ with en-IN grouping (₹1,46,079), U+2212 for negatives. */
export function inr(v: number | null | undefined, dp = 0): string {
  if (!finite(v)) return '—'
  const s = Math.abs(v).toLocaleString('en-IN', { minimumFractionDigits: dp, maximumFractionDigits: dp })
  return `${v < 0 ? MINUS : ''}₹${s}`
}

export function usd(v: number | null | undefined, dp = 1): string {
  if (!finite(v)) return '—'
  const s = Math.abs(v).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp })
  return `${v < 0 ? MINUS : ''}$${s}`
}

/**
 * A COUNT — contracts, lots, troy ounces, tonnes — with Western grouping (105562 → '105,562'), U+2212. Rupees keep the
 * Indian grouping (`inr`); CFTC contracts, COMEX OI and ounces do not (C-TRADER-20; the verdict sentence the server
 * builds prints '105,562', so the page shows one grouping per quantity, C-BEGINNER-18).
 */
export function count(v: number | null | undefined, dp = 0): string {
  if (!finite(v)) return '—'
  const r = Number(v.toFixed(dp))
  const s = Math.abs(r).toLocaleString('en-US', { minimumFractionDigits: dp, maximumFractionDigits: dp })
  return r < 0 ? `${MINUS}${s}` : s
}

/** Signed count: '+1,356' / '−2,883' / '0'. */
export function signedCount(v: number | null | undefined, dp = 0): string {
  if (!finite(v)) return '—'
  const r = Number(v.toFixed(dp))
  if (r === 0) return (0).toFixed(dp)
  return r > 0 ? `+${count(r, dp)}` : count(r, dp)
}

/** 1 → '1st', 2 → '2nd', 3 → '3rd', 11–13 → 'th', 93 → '93rd' (C-BEGINNER-19: never '93th'). */
export function ordinal(n: number | null | undefined): string {
  if (!finite(n)) return '—'
  const i = Math.round(n)
  const mod100 = Math.abs(i) % 100
  const suffix = mod100 >= 11 && mod100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' } as Record<number, string>)[Math.abs(i) % 10] ?? 'th'
  return `${i}${suffix}`
}

/** Observations a percentile needs before it is printed (C-TRADER-23 / C-DATA-14: 14 months or 160 reports are not "history"). */
export const PERCENTILE_MIN_N = 60

/** '93rd percentile (3 y)' — the word is 'percentile' (C-BEGINNER-19); below PERCENTILE_MIN_N observations the text says what history exists. */
export function percentileText(p: number | null | undefined, window?: string | null, n?: number | null, since?: string | null): string {
  if (finite(n) && n < PERCENTILE_MIN_N) return `${n} obs.${since ? ` since ${since}` : ''} — too few for a percentile`
  if (!finite(p)) return '—'
  return `${ordinal(p)} percentile${window ? ` (${window})` : ''}`
}

/**
 * 'basis +1.50% at the Tue 03 Nov settlement vs that session's duty-paid' (C-BEGINNER-5 / C-DATA-11): a settlement
 * basis always names its clock, so nobody divides the settlement bar by a duty-paid bar sampled hours later.
 */
export function basisClockLabel(basisPct: number | null | undefined, sessionLabel: string | null | undefined): string {
  if (!finite(basisPct)) return 'basis —'
  return `basis ${signedPct(basisPct, 2)} ${sessionLabel ? `at the ${sessionLabel}` : 'at the last settlement'} vs that session's duty-paid`
}

/** Contracts → million troy ounces / tonnes / $bn (SOURCES.md M13). */
export function contractsToMoz(contracts: number | null | undefined): number | null {
  return finite(contracts) ? (contracts * CONTRACT_OZ) / 1e6 : null
}
export function contractsToTonnes(contracts: number | null | undefined): number | null {
  return finite(contracts) ? (contracts * CONTRACT_OZ * OZ_G) / 1e6 : null
}
export function contractsToUsdBn(contracts: number | null | undefined, price: number | null | undefined): number | null {
  return finite(contracts) && finite(price) ? (contracts * CONTRACT_OZ * price) / 1e9 : null
}

/** $/oz → ₹/10 g before duty (M5). */
export function landedInr10g(usdOz: number | null | undefined, usdinr: number | null | undefined): number | null {
  return finite(usdOz) && finite(usdinr) ? (usdOz * usdinr * 10) / OZ_G : null
}

// ── dates and clocks (IST first) ────────────────────────────────────────────────────────────────

const IST = 'Asia/Kolkata'

const DAY_NAMES = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const MONTH_NAMES = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** The IST wall-clock parts of an instant (no locale punctuation: 'Thu 22 Oct', never 'Thu, 22 Oct'). */
function istParts(d: Date): { wd: string; dd: string; mon: string; hh: string; mm: string } {
  const f = new Intl.DateTimeFormat('en-GB', { timeZone: IST, weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })
  const p: Record<string, string> = {}
  for (const x of f.formatToParts(d)) p[x.type] = x.value
  const wdIdx = DAY_NAMES.findIndex(n => (p.weekday ?? '').startsWith(n))
  const monIdx = MONTH_NAMES.findIndex(n => (p.month ?? '').startsWith(n))
  return { wd: wdIdx >= 0 ? DAY_NAMES[wdIdx] : (p.weekday ?? ''), dd: p.day ?? '', mon: monIdx >= 0 ? MONTH_NAMES[monIdx] : (p.month ?? ''), hh: p.hour === '24' ? '00' : (p.hour ?? ''), mm: p.minute ?? '' }
}

/** '2026-10-20' → 'Tue 20 Oct'; an ISO timestamp with `withTime` → 'Sat 24 Oct 01:00 IST'. Invalid → '—'. */
export function istLabel(iso: string | null | undefined, withTime = false): string {
  if (!iso) return '—'
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(iso)
  const d = new Date(dateOnly ? `${iso}T00:00:00+05:30` : iso)
  if (Number.isNaN(d.getTime())) return '—'
  const p = istParts(d)
  const day = `${p.wd} ${p.dd} ${p.mon}`
  if (dateOnly || !withTime) return day
  return `${day} ${p.hh}:${p.mm} IST`
}

/** '2026-05-13' → 'Wed 13 May 2026' (a dated constant such as the duty keeps its year). Invalid → '—'. */
export function dateLabel(iso: string | null | undefined): string {
  if (!iso) return '—'
  const dateOnly = /^\d{4}-\d{2}-\d{2}$/.test(iso)
  const d = new Date(dateOnly ? `${iso}T00:00:00+05:30` : iso)
  if (Number.isNaN(d.getTime())) return '—'
  const p = istParts(d)
  const year = new Intl.DateTimeFormat('en-GB', { timeZone: IST, year: 'numeric' }).format(d)
  return `${p.wd} ${p.dd} ${p.mon} ${year}`
}

/** '2026-09' or '2026-09-30' → 'Sep 2026' (a data month: IMF, the LBMA vault file). Invalid → '—'. */
export function monthLabel(ym: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})/.exec(ym ?? '')
  if (!m) return '—'
  const mon = MONTH_NAMES[Number(m[2]) - 1]
  return mon ? `${mon} ${m[1]}` : '—'
}

/** Age in whole days between an ISO date/timestamp and `now`. */
export function ageDays(iso: string | null | undefined, now: Date = new Date()): number | null {
  if (!iso) return null
  const d = new Date(/^\d{4}-\d{2}-\d{2}$/.test(iso) ? `${iso}T00:00:00+05:30` : iso)
  if (Number.isNaN(d.getTime())) return null
  return Math.max(0, Math.floor((now.getTime() - d.getTime()) / 86_400_000))
}

/** The latest ISO date among the dates a block carries (its own as-of; never the request clock). Unparsable → skipped. */
export function latestDate(dates: readonly (string | null | undefined)[]): string | null {
  let best: string | null = null
  for (const d of dates) {
    const m = /^(\d{4}-\d{2}-\d{2})/.exec(d ?? '')
    if (m && (best === null || m[1] > best)) best = m[1]
  }
  return best
}

/**
 * "percentile 26 of the last 160 reports (≈ 3 y)" / "all-history percentile 50 (1,040 reports)": the window the server
 * computed it over, from its own `n_reports` — never "all-history" for a 160-report window (C-DATA-14), never an ordinal
 * ("93th", C-BEGINNER-19). `null` percentile → '—'. A server-sent label (`percentile_label`) wins verbatim.
 */
export const ALL_HISTORY_MIN_REPORTS = 900          // 2006→ weekly ≈ 1,040 reports; 1986→ ≈ 2,080
export function percentileLabel(pctile: number | null | undefined, nReports: number | null | undefined, serverLabel?: string | null): string {
  if (!finite(pctile)) return '—'
  const p = `percentile ${num(pctile, 0)}`
  if (serverLabel) return `${p} · ${serverLabel}`
  if (!finite(nReports) || nReports <= 0) return p
  if (nReports >= ALL_HISTORY_MIN_REPORTS) return `all-history ${p} (${num(nReports)} reports)`
  const years = nReports / 52
  return `${p} of the last ${num(nReports)} reports (≈ ${years >= 1 ? `${Math.round(years)} y` : `${Math.round(nReports / 4.33)} mo`})`
}

/** Calendar days from a to b (ISO dates), or null. */
export function calendarDays(a: string | null | undefined, b: string | null | undefined): number | null {
  const ma = /^(\d{4})-(\d{2})-(\d{2})/u.exec(a ?? ''), mb = /^(\d{4})-(\d{2})-(\d{2})/u.exec(b ?? '')
  if (!ma || !mb) return null
  return Math.round((Date.UTC(+mb[1], +mb[2] - 1, +mb[3]) - Date.UTC(+ma[1], +ma[2] - 1, +ma[3])) / 86_400_000)
}

/** Weekday sessions from `a` (exclusive) to `b` (inclusive): 1 for consecutive sessions, 3 when two rows are missing. Junk → null. */
export function sessionsBetween(a: string | null | undefined, b: string | null | undefined): number | null {
  const ma = /^(\d{4})-(\d{2})-(\d{2})/.exec(a ?? ''), mb = /^(\d{4})-(\d{2})-(\d{2})/.exec(b ?? '')
  if (!ma || !mb) return null
  const da = Date.UTC(+ma[1], +ma[2] - 1, +ma[3]), db = Date.UTC(+mb[1], +mb[2] - 1, +mb[3])
  if (db <= da) return null
  let n = 0
  for (let t = da + 86_400_000; t <= db; t += 86_400_000) { const wd = new Date(t).getUTCDay(); if (wd !== 0 && wd !== 6) n++ }
  return n
}

// ── freshness and badges (PLAN 0.1 #10, §f) ─────────────────────────────────────────────────────

export type FreshState = 'live' | 'delayed' | 'stale' | 'unavailable'
export interface FreshLike { state?: FreshState | string | null; source?: string | null; as_of?: string | null; age_days?: number | null; age_s?: number | null; reason?: string | null }

/**
 * The freshness a panel may wear: the block's own `freshness` from the server or nothing (`null` → the kit's NO DATA
 * chip). The client never invents a state — a fabricated 'delayed' would hide STALE / UNAVAILABLE (PLAN 0.1 #10, §f.7).
 */
export function serverFreshness<F extends FreshLike>(f: F | null | undefined): F | null {
  return f && typeof f === 'object' && typeof f.state === 'string' && f.state ? f : null
}

/** 'LIVE · Breeze' / 'DELAYED · Yahoo' / 'STALE · 12 d · 429' / 'UNAVAILABLE · not yet ingested'. */
export function freshLabel(f: FreshLike | null | undefined): string {
  if (!f || !f.state) return 'UNAVAILABLE'
  const head = String(f.state).toUpperCase()
  const bits: string[] = [head]
  if (f.source) bits.push(f.source)
  if (f.state === 'stale' && finite(f.age_days)) bits.push(`${f.age_days} d`)
  else if (f.state === 'stale' && finite(f.age_s)) bits.push(`${Math.round(f.age_s / 3600)} h`)
  if (f.reason && (f.state === 'stale' || f.state === 'unavailable')) bits.push(f.reason)
  return bits.join(' · ')
}

export type Badge = 'signal' | 'context' | 'arithmetic' | 'heuristic'

/** Chip text per badge (PLAN §f.1): the context chip names the study and the date. */
export function badgeText(badge: Badge, evidence?: string | null): string {
  switch (badge) {
    case 'signal': return `SIGNAL · ${evidence ?? 'pre-registered PASS'}`
    case 'context': return `CONTEXT · ${evidence ?? 'G-STUDY 26 Oct 2026: no forecasting power'}`
    case 'arithmetic': return `ARITHMETIC · ${evidence ?? 'identity, cost or spec'}`
    case 'heuristic': return `HEURISTIC · ${evidence ?? 'house rule, no study'}`
  }
}

// ── CFTC wording (M14 / M15) ─────────────────────────────────────────────────────────────────────

/**
 * "closed 3,777 longs" · "covered 894 shorts" · "added 3,761 new longs" · "added 466 new shorts" (zero → no clause).
 * The four verbs are the PLAN a.6 chips: closed longs / covered shorts / new longs / new shorts.
 */
export function whoDidWords(dLong: number | null | undefined, dShort: number | null | undefined): string[] {
  const out: string[] = []
  if (finite(dLong) && dLong !== 0) out.push(dLong < 0 ? `closed ${num(Math.abs(dLong))} longs` : `added ${num(dLong)} new longs`)
  if (finite(dShort) && dShort !== 0) out.push(dShort < 0 ? `covered ${num(Math.abs(dShort))} shorts` : `added ${num(dShort)} new shorts`)
  return out
}

/** Arrow glyph for a Δ: ▲ opened / ▼ closed / · flat. */
export function deltaArrow(d: number | null | undefined): '▲' | '▼' | '·' {
  return !finite(d) || d === 0 ? '·' : d > 0 ? '▲' : '▼'
}

/**
 * The fund-driver label from the managed-money week (G-STUDY §5.1 rules), used when the server gives none:
 * price up & longs added → "new longs"; price up & shorts covered → "short covering"; price down & longs closed →
 * "long liquidation"; price down & shorts added → "new shorts"; price up & net down → "funds sold into it"; price down
 * & net up → "funds bought the dip".
 */
export function fundDriverLabel(dLong: number | null | undefined, dShort: number | null | undefined, priceChgPct: number | null | undefined): string | null {
  // a byte-for-byte mirror of services/data-service/gold/driver_rule.py (wave 1c): the net sign first, then the bigger
  // leg (a tie goes to the closing leg); no word without a price change or when neither leg moved. The server's label
  // wins on screen; this mirror is the fallback and the node check pins both on the critics' week (+1,538 / +182 / −1.64 %)
  if (!finite(dLong) || !finite(dShort) || !finite(priceChgPct)) return null
  if (priceChgPct === 0 || (dLong === 0 && dShort === 0)) return null
  const net = dLong - dShort
  if (priceChgPct < 0) {
    if (net > 0) return 'funds bought the dip'
    if (dLong < 0 && Math.abs(dLong) >= Math.max(dShort, 0)) return 'long liquidation'
    return 'new shorts'
  }
  if (net < 0) return 'funds sold into it'
  if (dShort < 0 && Math.abs(dShort) >= Math.max(dLong, 0)) return 'short covering'
  return 'new longs'
}

/** The four OI × price quadrants (M28): sign(Δprice) × sign(ΔOI). */
export function quadrantLabel(dPrice: number | null | undefined, dOi: number | null | undefined): 'long build-up' | 'short build-up' | 'short covering' | 'long unwinding' | null {
  if (!finite(dPrice) || !finite(dOi) || dPrice === 0 || dOi === 0) return null
  if (dPrice > 0) return dOi > 0 ? 'long build-up' : 'short covering'
  return dOi > 0 ? 'short build-up' : 'long unwinding'
}

/**
 * What the tape prints for a session (C-BEGINNER-24, C-DATA-19, C-TRADER-18): the server's label when it has one; 'flat'
 * only when BOTH deltas are known and one is zero; "no OI for this session" when ΔOI is missing (never 'flat'); and
 * "Δ over N sessions" when the row's delta spans missing sessions (`prevDate` → `tradeDate` is more than one weekday).
 */
export function tapeReadout(row: { trade_date: string; dprice_pct: number | null; doi: number | null; label?: string | null; mechanical?: boolean }, prevDate: string | null | undefined, missingOiNote = 'ΔOI not stored for this session'):
  { label: string | null; word: string; note: string | null; sessions: number | null } {
  const sessions = sessionsBetween(prevDate, row.trade_date)
  const span = sessions != null && sessions > 1 ? `Δ over ${sessions} sessions (rows missing between)` : null
  const label = row.label ?? quadrantLabel(row.dprice_pct, row.doi)
  if (label) return { label, word: label, note: span, sessions }
  if (!finite(row.doi)) return { label: null, word: 'no OI for this session', note: [missingOiNote, span].filter(Boolean).join(' · ') || null, sessions }
  if (!finite(row.dprice_pct)) return { label: null, word: 'no price for this session', note: span, sessions }
  return { label: null, word: 'flat', note: span, sessions }
}

/** Quadrant → [B] one-liner. */
export const QUADRANT_READ: Record<string, string> = {
  'long build-up': 'price up with new positions: buyers opened',
  'short covering': 'price up with positions closed: shorts bought back',
  'short build-up': 'price down with new positions: sellers opened',
  'long unwinding': 'price down with positions closed: longs sold out',
}

export const CROWD_LABEL = 'crowdedness, not a signal — no forecasting power 2006–2026 (G-STUDY)'

/** `/api/gold/cot?weeks=` is bounded `le=2000` (routers/gold.py); 2000 weeks ≈ 38 y covers the 2006→ disaggregated and the
 *  1986→ legacy history, so 'all' asks for the server's maximum instead of a number the route rejects (422). */
export const COT_WEEKS_MAX = 2000
export const COT_RANGES = { '1y': 52, '3y': 156, '10y': 520, all: COT_WEEKS_MAX } as const
export type CotRange = keyof typeof COT_RANGES

/** "52 reports · since Tue 28 Oct 2025": the real range the history panel shows, from the rows that came back. */
export function cotRangeLabel(n: number, firstDate: string | null | undefined): string {
  if (!n) return 'no reports'
  return `${num(n)} report${n === 1 ? '' : 's'}${firstDate ? ` · since ${dateLabel(firstDate)}` : ''}`
}

/** The CFTC concentration block as the server names it (`drawer.concentration{gross4_long, …, net8_short}`, API_CONTRACT §2.5). */
export const CONCENTRATION_KEYS = ['gross4_long', 'gross4_short', 'gross8_long', 'gross8_short', 'net4_long', 'net4_short', 'net8_long', 'net8_short'] as const
export function concentrationLines(v: unknown): { net: string; gross: string } {
  const o = (v && typeof v === 'object' ? v : {}) as Record<string, unknown>
  const f = (k: string) => (finite(o[k]) ? pct(o[k] as number, 1) : '—')
  return {
    net: `L ${f('net4_long')} / ${f('net8_long')} · S ${f('net4_short')} / ${f('net8_short')}`,
    gross: `L ${f('gross4_long')} / ${f('gross8_long')} · S ${f('gross4_short')} / ${f('gross8_short')}`,
  }
}

/**
 * A health-rule threshold / value as text. routers/gold.py HEALTH_RULES carries objects (`{weak_pct: −2, strong_pct: 2,
 * flat_pct: 0.5}`, `{usd_share: 0.4, …}`) as well as numbers and strings; React refuses an object as a child, so LEARN's
 * rule table prints them as 'weak_pct −2 · strong_pct 2 · flat_pct 0.5'. null → '—'.
 */
export function thresholdText(v: unknown): string {
  if (v == null) return '—'
  if (typeof v === 'number') return finite(v) ? `${v < 0 ? MINUS : ''}${Math.abs(v).toLocaleString('en-US', { maximumFractionDigits: 2 })}` : '—'
  if (typeof v === 'string') return v
  if (typeof v === 'boolean') return v ? 'yes' : 'no'
  if (Array.isArray(v)) return v.map(thresholdText).join(' / ')
  if (typeof v === 'object') return Object.entries(v as Record<string, unknown>).map(([k, x]) => `${k} ${thresholdText(x)}`).join(' · ')
  return String(v)
}

// ── MACRO rules ─────────────────────────────────────────────────────────────────────────────────

export type Direction = 'supportive' | 'headwind' | 'neutral'

/**
 * The printed sign rule per driver when the payload carries none (`drivers[].rule` is the server's text and wins).
 * Text only: the client never derives a tag from these (the server tags from the selected window, API_CONTRACT §2.11).
 */
export const DRIVER_RULES: Record<string, string> = {
  real_10y: 'falling = supportive, rising = headwind',
  real_2y: 'falling = supportive, rising = headwind',
  nominal_2y: 'falling = supportive, rising = headwind',
  breakeven_10y: 'rising = supportive',
  dxy: 'falling = supportive, rising = headwind',
  usdinr: 'rising = MCX supportive',
  gvz: 'size, not direction',
  brent: 'rising = supportive',
  gld_t: 'contemporaneous; no lead',
}

/**
 * The tile label follows the SERIES the server actually used (`drivers[].series_id`), never the key's nominal name: the
 * Fed broad index must not print under "Dollar index (DXY)" (C-DATA-4, C-TRADER-8). Unknown series → the server label.
 */
export const SERIES_LABEL: Record<string, string> = {
  DXY_CLOSE: 'Dollar index (DXY)',
  FRED_DTWEXBGS: 'Fed broad USD index (DTWEXBGS)',
  USDINR_CLOSE: 'USD/INR',
  USDINR_FBIL: 'USD/INR (FBIL reference)',
  FRED_DFII10: '10-y real yield',
  UST_REAL_10Y: '10-y real yield (Treasury)',
  FRED_DGS2: '2-y Treasury',
  UST_NOM_2Y: '2-y Treasury (Treasury)',
  FRED_T10YIE: '10-y breakeven',
  GVZ_CLOSE: 'GVZ (gold vol)',
  FRED_GVZCLS: 'GVZ (gold vol, FRED)',
  FRED_DCOILBRENTEU: 'Brent (dated spot, FRED)',
  BRENT_FRONT: 'Brent front-month future (BZ=F)',
  WTI_FRONT: 'WTI front (not Brent)',
}
export function driverTileLabel(d: { key: string; label?: string | null; series_id?: string | null }): string {
  return (d.series_id && SERIES_LABEL[d.series_id]) || d.label || d.key
}

/**
 * What the instrument IS when the served series is not the primary's quantity (wave 1e minor: the NYMEX BZ=F front future
 * printed as 'BRENT 98.68' under 'Source: FRED'): a future is said to be a future, with its own source. Null otherwise.
 */
export function driverInstrumentNote(d: { series_id?: string | null }): string | null {
  if (d.series_id === 'BRENT_FRONT') return 'front-month future (Yahoo BZ=F, last trade; the latest bar can be partial), not dated Brent spot'
  if (d.series_id === 'WTI_FRONT') return 'WTI front-month future (Yahoo CL=F), not Brent'
  return null
}

/**
 * A driver's served `label_note`, verbatim (wave 1e: MACRO printed 'the primary series has no stored points' while FRED had
 * points to 3 Nov — the note said 'UST_REAL_10Y: fresher than FRED_DFII10 (last 2026-11-03)'). `tone` amber only for a
 * stand-in of another quantity (the Fed broad index for DXY); a fresher twin of the same quantity is information.
 */
export function driverNote(d: { key: string; label?: string | null; label_note?: string | null; series_id?: string | null }): { text: string; tone: 'amber' | 'dim' } | null {
  const note = (d.label_note ?? '').trim()
  if (note) return { text: note, tone: /fresher than/iu.test(note) ? 'dim' : 'amber' }
  const label = driverTileLabel(d)
  if (d.series_id && label !== (d.label ?? d.key) && !driverInstrumentNote(d)) return { text: `stand-in for ${d.label ?? d.key}: ${d.series_id}`, tone: 'amber' }
  return null
}

/** The attribution lines MACRO's drivers need, from the series actually served (never 'FRED' alone under a Yahoo future). */
export function driverSources(drivers: readonly { series_id?: string | null }[]): ('FRED' | 'US Treasury' | 'Yahoo' | 'SPDR')[] {
  const out = new Set<'FRED' | 'US Treasury' | 'Yahoo' | 'SPDR'>()
  for (const d of drivers) {
    const id = d.series_id ?? ''
    if (/^FRED_/u.test(id)) out.add('FRED')
    else if (/^UST_/u.test(id)) out.add('US Treasury')
    else if (/^GLD_/u.test(id)) out.add('SPDR')
    else if (id) out.add('Yahoo')
  }
  return (['FRED', 'US Treasury', 'Yahoo', 'SPDR'] as const).filter(s => out.has(s))
}

/** A Fed-path row's mean: the tracker's `mean_bp` is a RATE LEVEL in bp (416 = 4.16 %), not a move (wave 1e minor: 'hike 89 % · 416 bp' read as a move). */
export function fedMeanText(meanBp: number | null | undefined): string {
  if (!finite(meanBp)) return 'mean rate —'
  return `mean rate ${num(meanBp / 100, 2)} %`
}

/**
 * The ZQ (30-day Fed funds future) label: the contract when the server names it ('ZQZ26'), else the observation month with
 * the honest words — the continuous ZQ=F rolls before expiry, so the month is NOT the contract's (wave 1e minor: 'NOV-26
 * 4.05 %' was the rolled December-like contract).
 */
export function zqLabel(z: { month: string; contract?: string | null; symbol?: string | null; contract_month?: string | null; month_guess?: string | null; rolled_suspect?: boolean | null }): string {
  const c = z.contract ?? z.symbol ?? null
  const continuous = !c || /ZQ=F|=F$|continuous/iu.test(c)
  if (!continuous) return `${c}${z.contract_month ? ` (${z.contract_month})` : ''}`
  if (z.rolled_suspect) return `ZQ=F front · likely ${z.month_guess ?? z.month} (rolled)`
  return `ZQ=F front · ${z.month_guess ?? z.month} (the observation month; Yahoo does not report the contract)`
}

/**
 * MACRO's KGX window caption vs HEALTH's (wave 1e minor: it said 'not HEALTH's week to date' while the windows were equal).
 * 8 Nov 2026 (C-DATA-04 / F4): the caption names the window's END too — it claimed "as of Fri 06 Nov" while legs came from
 * rows dated Mon 09 Nov.
 */
export function kgxWindowCaption(kgx: { period?: string | null; from_date?: string | null; to_date?: string | null; window_label?: string | null } | null | undefined, healthFrom: string | null | undefined): string | null {
  if (!kgx?.from_date) return null
  const span = `window from ${istLabel(kgx.from_date)}${kgx.to_date ? ` to ${istLabel(kgx.to_date)}` : ''}`
  const head = `${span}${kgx.window_label ? ` (${kgx.window_label})` : ''}`
  if (!healthFrom) return head
  return kgx.from_date === healthFrom ? `${head} — the same window as HEALTH's` : `${head} — HEALTH's window starts ${istLabel(healthFrom)}`
}

/**
 * The KGX dollar leg's label. 8 Nov 2026 (C-DATA-03 / F4): the leg was "USD effect (DXY basket)" and really summed six
 * Yahoo "=X" closes that are start-of-day prints a session behind gold's and DXY's — which put the opposite sign on it
 * on 90 of the 191 days DXY moved ≥ 0.1 %. It is now −Δln of the ICE DXY close, and the label says which.
 */
export function kgxUsdLabel(usdSource?: string | null): string {
  return usdSource === 'DXY_CLOSE' || !usdSource ? 'USD effect (−Δln DXY close)' : `USD effect (${usdSource})`
}

/** The basket caption: the server's sentence when it sends one, else the weights it carries (series ids, as before). */
export function kgxBasketText(basketLabel?: string | null, weights?: Record<string, number> | null): string | null {
  if (basketLabel) return basketLabel
  if (!weights || Object.keys(weights).length === 0) return null
  return `basket ${Object.entries(weights).map(([k, v]) => `${k} ${(v * 100).toFixed(1)} %`).join(' · ')}`
}

/**
 * The window letter the page asked for ('D' / 'W' / 'M'), for the column that carries the server's `d_window`.
 */
export function windowTag(window: string | null | undefined): string {
  const w = String(window ?? 'W').toUpperCase()
  return w === 'D' || w === 'W' || w === 'M' ? w : 'W'
}

/**
 * The one-line caption that says what each MACRO column means (C-DATA-04 / F4, 8 Nov 2026): "W" in the picker is the
 * page's window (HEALTH's and KGX's), while 1 d / 7 d / 30 d are TRAILING calendar days from the series' last stored
 * point. The two used to be called "W" and "1W" side by side, with the trailing one defined in a hover tooltip only.
 */
export function windowColumnsCaption(window: string | null | undefined, label?: string | null, from?: string | null, to?: string | null): string {
  const w = windowTag(window)
  // the label's own parenthetical names its start date ("week to date (since the Fri 30 Oct close)"); when the caption
  // prints the span itself, the words come without it, so one caption never prints one date twice (§f.6)
  const words = from ? (label ?? 'the page’s window').split(' (')[0] : (label ?? 'the page’s window')
  const win = `${w} = ${words}${from ? `, from the ${istLabel(from)} close` : ''}${to ? ` to ${istLabel(to)}` : ''}`
  return `${win} · 7 d / 30 d = trailing calendar days (not 5 / 21 sessions: a holiday week has fewer)`
}

/**
 * PLAN §f.6 (the same number appears once per page): the window column is rendered only when it is not the very figure
 * the 1 d column already prints. In the 'D' window the page's window IS the previous session, so the two coincide by
 * definition (the 8 Nov round-2 checker saw "D +0.683 · 1d +0.683" on the DXY tile and a 'D' and a '1D' column both
 * reading −0.573 for USD); in 'W' / 'M' they coincide on a day when the window happens to span one session. Compare the
 * PRINTED strings, so two values that round to the same figure are not shown twice either.
 */
export function showWindowColumn(windowText: string | null | undefined,
                                 ...others: (string | null | undefined)[]): boolean {
  // PLAN §f.6, the same number once per page: the WINDOW column is hidden when it would reprint ANY trailing column, not
  // just the 1-day one. 8 Nov 2026: W and M start at the Friday close, so on every currency row and the DXY tile the
  // window figure equalled the 7-day one and both were printed ('W +4.51 % · 7 D +4.51 %').
  return !!windowText && windowText !== '—' && !others.includes(windowText)
}

/**
 * The note the KGX panel prints. The SERVER owns the sentence — it knows which series it read and over which dates
 * (`kgx.note`) — and the client's `kgxUnavailableNote` is the fallback; when both exist the client's trailing hint
 * (which dollar series the driver strip fell back to, and when) is appended, because the server does not carry it.
 * 8 Nov round-2 checker: the client's text won whenever the leg was missing, so the server's gold-span words never
 * reached the screen.
 */
export function kgxNoteText(serverNote?: string | null, clientNote?: string | null): string | null {
  if (!serverNote) return clientNote ?? null
  if (!clientNote) return serverNote
  const hint = clientNote.split('; ').slice(1).join('; ')
  return hint ? `${serverNote}; ${hint}` : serverNote
}

/**
 * HEALTH's DOLLAR tile: the dollar's CONTRIBUTION to gold — the ONE number the H2 verdict clause and MACRO's KGX split
 * also print (C-DATA-03 / F4, 8 Nov 2026: the tile said "+0.41 % HEADWIND", the verdict "the dollar −0.4 %" and the KGX
 * panel "+0.17 % the dollar", for one labelled week). Null when the server did not measure it; the dates come with it
 * whenever the dollar leg's own span is not the window's.
 */
export function usdEffectWords(g: {
  usd_effect_pct?: number | null; usd_effect_from?: string | null; usd_effect_to?: string | null
  usd_effect_aligned?: boolean | null; usd_effect_note?: string | null; window_from?: string | null; report_date?: string | null
} | null | undefined): { text: string; note: string | null } | null {
  if (!g || !finite(g.usd_effect_pct)) return null
  const span = g.usd_effect_from && g.usd_effect_to ? ` (${istLabel(g.usd_effect_from)} → ${istLabel(g.usd_effect_to)})` : ''
  const text = `contribution to gold ${signedPct(g.usd_effect_pct, 2)}${span}`
  const off = g.usd_effect_aligned === false
  return { text, note: off ? (g.usd_effect_note ?? 'the dollar leg’s dates are not gold’s') : null }
}

/**
 * A driver's change in ONE unit, the server's `change_unit` (C-BEGINNER-20): 'bp' → basis points (a 0.02 pp move of a
 * yield prints "+2 bp"), '%' → percent, 't' → tonnes; otherwise the raw delta. `v` is the server's delta in the level's
 * own unit (pp for a yield).
 */
export function driverDelta(d: { unit: string; change_unit?: string | null; key?: string | null; series_id?: string | null }, v: number | null | undefined): string {
  if (!finite(v)) return '—'
  // a volatility index moves in vol points, not basis points (REREVIEW: 'GVZ 24.11 % · 1w +121 bp'): GVZ's change is printed
  // as '+1.21 vol pts' whatever unit the server attached (a vol point is not a basis point)
  if (isVolIndex(d)) return `${signed(v, 2)} vol pts`
  const cu = d.change_unit ?? (d.unit === '%' ? 'bp' : d.unit === 't' ? 't' : '%')
  if (cu === 'bp') return `${signed(v * 100, 0)} bp`
  if (cu === 't') return `${signed(v, 1)} t`
  if (cu === '%') return `${signed(v, 2)}%`
  return signed(v, 2)
}

/**
 * The exchange-OI quadrant word under the fund-driver label, SAID to be the OI quadrant (REREVIEW: 'funds bought the dip'
 * above 'long unwinding' read as two driver words): 'OI quadrant: long unwinding (OI −5,469)'.
 */
export function oiQuadrantWords(label: string | null | undefined, oiChg: number | null | undefined): string {
  if (!label) return 'OI quadrant: —'
  return `OI quadrant: ${label}${finite(oiChg) ? ` (OI ${signed(oiChg, 0)})` : ''}`
}

/**
 * Days to an MCX tender, never negative (the 5 Nov review: '−4 days to tender'): once it has started, 'in tender since Sun 01
 * Nov (4 d)'. Wave 1e (regression: 'tender starts today (Sun 01 Nov)' on Fri 06 Nov): the server clamps the days to 0 while
 * the tender runs and says so — `in_tender` / `tender_note` win; 'starts today' only when the tender start IS today.
 */
export function tenderWords(days: number | null | undefined, startLabel: string | null | undefined,
  roll?: { in_tender?: boolean | null; tender_note?: string | null; tender_start?: string | null } | null, today?: string | null): string {
  if (roll?.in_tender) {
    if (roll.tender_note) return roll.tender_note
    const d = calendarDays(roll.tender_start, today)
    return `in tender since ${startLabel ?? 'the tender start'}${d != null ? ` (${d} d)` : ''}`
  }
  if (!finite(days)) return 'days to tender —'
  if (days === 0 && roll?.tender_start && today && roll.tender_start < today) {
    return `in tender since ${startLabel ?? 'the tender start'} (${calendarDays(roll.tender_start, today)} d)`
  }
  if (days < 0) return `in tender since ${startLabel ?? 'the tender start'} (${Math.abs(Math.round(days))} d)`
  if (days === 0) return `tender starts today${startLabel ? ` (${startLabel})` : ''}`
  return `${Math.round(days)} day${Math.round(days) === 1 ? '' : 's'} to tender`
}

/** GVZ (and any vol index): its level is a % but its changes are volatility points. */
export function isVolIndex(d: { key?: string | null; series_id?: string | null; change_unit?: string | null }): boolean {
  return d.change_unit === 'vol pts' || /^gvz/i.test(d.key ?? '') || /^GVZ/.test(d.series_id ?? '')
}

/** Driver-health beta with its unit (C-DATA-21): beta_real_yield_per_100bp → "$/oz per 100 bp"; beta_dxy → "% per 1 % DXY". */
export function betaText(key: string, v: unknown): string {
  const n = finite(v) ? v : null
  if (key === 'beta_real_yield_per_100bp') return `real yield ${n == null ? '—' : `${signed(n, 0)} $/oz per 100 bp`}`
  if (key === 'beta_dxy') return `DXY ${n == null ? '—' : `${signed(n, 2)} % per 1 %`}`
  return `${key} ${n == null ? (v == null ? '—' : String(v)) : signed(n, 2)}`
}

/**
 * The direction word a driver tile may wear: the server's tag or none. A `null` tag is deliberate (GLD tonnes:
 * "contemporaneous; no lead"; GVZ: size, not direction) and renders `neutral` — the client re-tags nothing (§f.3).
 */
export function driverTag(serverTag: Direction | string | null | undefined): Direction {
  return serverTag === 'supportive' || serverTag === 'headwind' ? serverTag : 'neutral'
}

/** KGX identity check (M56): total = pure + usd_effect, within rounding. */
export function kgxConsistent(total: number | null | undefined, pure: number | null | undefined, usdEffect: number | null | undefined, tol = 0.02): boolean {
  if (!finite(total) || !finite(pure) || !finite(usdEffect)) return false
  return Math.abs(total - (pure + usdEffect)) <= tol
}

/**
 * Why the "gold or the dollar?" split is empty (C-BEGINNER-14): the dollar leg needs the ICE DXY's close on gold's own two
 * dates; when `usd_effect_pct` is null the panel prints the reason (which dollar series the drivers fell back to and its
 * date) and hides the identity check — a reader never sees "identity off — check the inputs". Null when the split is
 * complete. 8 Nov 2026 (C-DATA-03): the leg is DXY_CLOSE, no longer the six Yahoo "=X" closes, so the reason says so.
 */
export function kgxUnavailableNote(usdEffect: number | null | undefined, dollar?: { series_id?: string | null; report_date?: string | null; state?: string | null } | null): string | null {
  if (finite(usdEffect)) return null
  const src = dollar?.series_id ? (SERIES_LABEL[dollar.series_id] ?? dollar.series_id) : null
  const when = dollar?.report_date ? istLabel(dollar.report_date) : null
  const head = 'USD effect unavailable: the split takes \u2212\u0394ln of the ICE DXY close (DXY_CLOSE) on gold\u2019s own two dates, and one of them has no stored point'
  return src ? `${head}; the driver strip shows ${src}${when ? ` last ${when}` : ''}${dollar?.state === 'stale' ? ' (STALE)' : ''}` : head
}

/** 1σ day per lot (M60): σ% × ₹/10 g × multiplier. */
export const LOT_MULTIPLIER: Record<string, number> = { GOLD: 100, GOLDM: 10, GOLDTEN: 1, GOLDGUINEA: 0.8, GOLDPETAL: 0.1 }
export function sigmaPerLot(sigmaPct: number | null | undefined, inr10g: number | null | undefined, family: string): number | null {
  const m = LOT_MULTIPLIER[family]
  return finite(sigmaPct) && finite(inr10g) && m ? (sigmaPct / 100) * inr10g * m : null
}

// ── PHYSICAL ────────────────────────────────────────────────────────────────────────────────────

export interface LadderStepLike { step: string; label: string; value: number | null; ts?: string | null; source?: string | null; unit?: string | null }

/** Order the India ladder the way the owner asked (COMEX → ×USD/INR → landed → +duty → IBJA → MCX); unknown steps keep their place at the end. */
export const LADDER_ORDER = ['comex', 'usdinr', 'landed', 'duty', 'duty_paid', 'ibja', 'mcx'] as const
/** The ladder step a payload `step` belongs to: the longest matching prefix ('duty_paid_landed' → duty_paid, not duty). */
export function ladderKey(step: string): (typeof LADDER_ORDER)[number] | null {
  const s = step.toLowerCase()
  let best: (typeof LADDER_ORDER)[number] | null = null
  for (const k of LADDER_ORDER) if (s.startsWith(k) && (best === null || k.length > best.length)) best = k
  return best
}
export function orderLadder<S extends LadderStepLike>(steps: readonly S[]): S[] {
  const rank = (s: S) => { const k = ladderKey(s.step); return k === null ? 99 : LADDER_ORDER.indexOf(k) }
  return [...steps].sort((a, b) => rank(a) - rank(b))
}

/**
 * IMF official-sector rows as the table prints them (C-TRADER-6, C-BEGINNER-3, C-DATA-5). `oz_mn` is million troy ounces;
 * a value above `OFFICIAL_RAW_OZ_MIN` can only be raw ounces (no holder has 1,000 Moz — the USA holds 261.5), so it is
 * scaled by 1e6 together with its changes; tonnes are always recomputed from the ounces (1 Moz = 31.1034768 t). A row
 * still above `OFFICIAL_MOZ_MAX` after scaling (Brazil's 5,544 Moz) is a unit error at the source and is excluded with
 * the reason printed, never sorted above the USA.
 */
export const OFFICIAL_RAW_OZ_MIN = 1_000
export const OFFICIAL_MOZ_MAX = 400
export interface OfficialRowLike { country: string; month: string; oz_mn?: number | null; tonnes?: number | null; chg_oz_mn?: number | null; chg_12m_oz_mn?: number | null }
export interface OfficialRow extends OfficialRowLike { oz_mn: number | null; tonnes: number | null; scaled: boolean; excluded: string | null }
export function normaliseOfficial(r: OfficialRowLike): OfficialRow {
  const raw = finite(r.oz_mn) ? r.oz_mn : null
  const scaled = raw != null && Math.abs(raw) > OFFICIAL_RAW_OZ_MIN
  const k = scaled ? 1e-6 : 1
  const oz = raw == null ? null : raw * k
  const chg = finite(r.chg_oz_mn) ? r.chg_oz_mn * k : null
  const chg12 = finite(r.chg_12m_oz_mn) ? r.chg_12m_oz_mn * k : null
  const excluded = oz != null && Math.abs(oz) > OFFICIAL_MOZ_MAX ? `${num(oz, 0)} Moz stored — unit error at the source (IMF SDMX unit), excluded until the series is fixed` : null
  return { ...r, oz_mn: oz, tonnes: oz == null ? null : oz * OZ_G, chg_oz_mn: chg, chg_12m_oz_mn: chg12, scaled, excluded }
}
export function officialTable(rows: readonly OfficialRowLike[]): { rows: OfficialRow[]; excluded: OfficialRow[] } {
  const all = rows.map(normaliseOfficial)
  return { rows: all.filter(r => !r.excluded).sort((a, b) => (b.oz_mn ?? -1) - (a.oz_mn ?? -1)), excluded: all.filter(r => !!r.excluded) }
}

/**
 * The clock of a ladder bar (C-BEGINNER-5, C-TRADER-4): the live legs (an ISO timestamp with a time) are "now"; IBJA is
 * its PM fix of a date; MCX is a settlement (the server sends the session label); the duty is a dated constant.
 */
export type LadderClock = 'now' | 'fix' | 'settlement' | 'constant' | 'unknown'
export function ladderClock(step: LadderStepLike): LadderClock {
  const k = ladderKey(step.step)
  if (k === 'duty') return 'constant'
  if (k === 'mcx') return 'settlement'
  if (k === 'ibja') return 'fix'
  if (!step.ts) return 'unknown'
  return /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(step.ts) ? 'now' : 'unknown'
}
/** 'now · Thu 05 Nov 00:06 IST' / 'PM fix · Tue 03 Nov' / 'Tue 03 Nov settlement' / 'Wed 13 May 2026' / 'as of —'. */
export function ladderTsLabel(step: LadderStepLike): string {
  const c = ladderClock(step)
  if (c === 'constant') return step.ts ? dateLabel(step.ts) : 'as of —'
  if (c === 'settlement') return step.ts ? (/^\d{4}-\d{2}-\d{2}/.test(step.ts) ? settlementLabel(step.ts) : step.ts) : 'settlement (session unknown)'
  if (c === 'fix') return step.ts ? `PM fix · ${istLabel(step.ts)}` : 'PM fix · —'
  if (c === 'now') return `now · ${istLabel(step.ts, true)}`
  return step.ts ? istLabel(step.ts, true) : 'as of —'
}

/**
 * The stored same-minute India premium for the IBJA date (INDIA_PREMIUM_PCT, computed at the fix minute by data-service)
 * — the only premium the ladder prints (C-TRADER-4, C-BEGINNER-2, C-DATA-11). A premium divided across clocks (today's
 * duty-paid over yesterday's fix) is clock error and is never shown. Null when the date has no stored row yet.
 */
export function storedPremiumOn(history: readonly { report_date: string; premium_pct?: number | null }[] | null | undefined, date: string | null | undefined): { value: number; date: string } | null {
  if (!date) return null
  const row = (history ?? []).find(h => h.report_date === date.slice(0, 10))
  return row && finite(row.premium_pct) ? { value: row.premium_pct, date: row.report_date } : null
}

/**
 * The Shanghai pairing rule (C-TRADER-5, C-DATA-10): the premium is printed only when the SGE PM and the reference leg
 * carry the SAME date; otherwise the panel shows the last stored same-day premium and says which PM it is waiting for.
 * The clock gap is real, not "7 hours": SGE PM 14:15 Beijing = 06:15 UTC; LBMA PM 15:00 London = 15:00 UTC on GMT
 * (8 h 45 min) and 14:00 UTC in British summer time (7 h 45 min); COMEX at 14:15 Beijing has no gap.
 */
export function ukIsBst(iso: string | null | undefined): boolean {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '')
  if (!m) return false
  const y = +m[1]
  const lastSunday = (month: number) => { const d = new Date(Date.UTC(y, month + 1, 0)); return d.getUTCDate() - d.getUTCDay() }
  const t = Date.UTC(y, +m[2] - 1, +m[3], 12)
  return t >= Date.UTC(y, 2, lastSunday(2), 1) && t < Date.UTC(y, 9, lastSunday(9), 1)
}
export function shanghaiPairing(tsSge: string | null | undefined, tsRef: string | null | undefined, refIsComex: boolean): { sameDate: boolean; gap: string; sgeDate: string | null; refDate: string | null } {
  const sgeDate = tsSge ? tsSge.slice(0, 10) : null
  const refDate = tsRef ? tsRef.slice(0, 10) : null
  const gap = refIsComex ? 'COMEX at 14:15 Beijing — no clock gap' : ukIsBst(sgeDate) ? 'SGE PM 14:15 Beijing → LBMA PM 15:00 London: 7 h 45 min apart (British summer time)' : 'SGE PM 14:15 Beijing → LBMA PM 15:00 London: 8 h 45 min apart (UK on GMT)'
  return { sameDate: !!sgeDate && !!refDate && sgeDate === refDate, gap, sgeDate, refDate }
}

/** 'avg = today (one session stored)' when a 20-day average equals today's print (n = 1, C-TRADER-21 / C-DATA-19); else the average. */
export function avgLabel(today: number | null | undefined, avg: number | null | undefined, window = '20-d'): string {
  if (!finite(avg)) return `${window} avg —`
  if (finite(today) && Math.abs(avg - today) < 1e-9) return `${window} avg = today (one session stored)`
  return `${window} avg ${num(avg, 0)}`
}

/** "Thu 22 Oct settlement" — the session label rule (PLAN 0.1 #8): never the file date. */
export function settlementLabel(session: string | null | undefined, explicit?: string | null): string {
  if (explicit) return explicit
  if (!session) return 'settlement (session unknown)'
  return `${istLabel(session)} settlement`
}
