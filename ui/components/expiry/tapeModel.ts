/**
 * Pure helpers for OMON › LIVE (the intraday OI / IV tape, PLAN 2.1) and OMON › XPRY (the expiry-day view, PLAN 2.4).
 * No React, no imports with side effects: unit-tested under plain node by ui/components/expiry/__tests__/expiry.check.ts.
 *
 * Rules carried here (PLAN §0): stored 2-minute snapshots are DELAYED with their age, never LIVE; every sentence that reads
 * a context number ends "describes, does not predict"; OI is in shares (the exchange unit) unless converted with the lot;
 * times are IST (the API sends UTC ISO stamps with +00:00 — the 5 Nov pilot panel printed them as IST, five and a half
 * hours early).
 */

export type Badge = 'signal' | 'context' | 'arithmetic' | 'heuristic'
export type ChipState = 'live' | 'delayed' | 'stale' | 'offline' | 'gap' | 'degraded' | 'input' | 'reference' | 'closed'

export interface TapePoint {
  ts: string; ist: string; forward: number; spot: number | null; atm_strike: number | null; atm_iv: number | null; nse_atm_iv: number | null
  straddle: number | null; open_strike: number | null; straddle_open_strike: number | null; call_oi: number; put_oi: number
  pcr: number | null; max_pain: number | null; n_strikes: number; source: string
}
export interface StrikeRow {
  strike: number
  ce_oi_open: number | null; ce_oi: number | null; ce_chg_open: number | null; ce_mid: number | null; ce_bid: number | null; ce_ask: number | null; ce_chg_prev: number | null
  pe_oi_open: number | null; pe_oi: number | null; pe_chg_open: number | null; pe_mid: number | null; pe_bid: number | null; pe_ask: number | null; pe_chg_prev: number | null
}
export interface Frame { ts: string; ist: string; ce: (number | null)[]; pe: (number | null)[] }
export interface Chip { state: ChipState; source: string; as_of: string | null; age_s: number | null; hint: string }
export interface OiTape {
  symbol: string; date: string | null; expiry: string | null; expiries: string[]; lot: number | null; dte_calendar: number | null
  path: TapePoint[]; strikes: StrikeRow[]; frames: Frame[]; snapshots: number; first: string | null; last: string | null
  last_ts: string | null; median_gap_min: number | null; source: string; units: Record<string, string>; model_version: string | null
  chip: Chip; badges: Record<string, Badge>; coverage: string; precedent: string; note: string; ok: boolean; store_errors: Record<string, string>
}
export interface CurvePoint { minute: number; median: number; p25: number; p75: number; n: number }
export interface DecayPoint { minute: number; ist: string; pct_of_open: number; straddle: number }
export interface PinRow { strike: number; distance_pts: number; distance_pct: number; ce_oi: number | null; pe_oi: number | null; total_oi: number }
export interface ScoreRow {
  expiry: string; priced_on: string; dte: number; forward: number; strike: number | null; straddle: number | null
  implied_move_pct: number | null; implied_1sd_pct: number | null; settle: number; realised_move_pct: number; ratio: number | null
  exceeded: boolean | null; naive_move_pct: number | null
}
export interface ScoreStats {
  n: number; exceeded_pct?: number; fair_exceeded_pct?: number; median_ratio?: number; mean_ratio?: number; mean_abs_miss_pct?: number
  naive_mean_abs_miss_pct?: number; implied_closer?: number; compared?: number
}
export interface ExpiryLive {
  snapshots: number; first?: string | null; last?: string | null; last_ts?: string | null; spot?: number | null; open_strike?: number | null
  path?: Pick<TapePoint, 'ts' | 'ist' | 'forward' | 'spot' | 'max_pain' | 'straddle' | 'straddle_open_strike' | 'atm_iv' | 'pcr'>[]
  unwind?: StrikeRow[]; pin_risk?: PinRow[]; decay?: DecayPoint[]; source?: string
  vs_curve?: { minute: number; today_pct: number; median_pct: number; p25: number; p75: number; n: number }
}
export interface ExpiryDay {
  symbol: string; date: string | null; is_expiry_day: boolean; next_expiry: string | null; last_expiry: string | null; live: ExpiryLive
  curve: { n: number; points: CurvePoint[]; expiries?: string[]; source?: string | null; note?: string; start_minute?: number }
  scorecard: { rows: ScoreRow[]; stats: ScoreStats; definition?: string; verdict?: string; note?: string }
  chip: Chip; badges: Record<string, Badge>; precedent: string; verdict: string; ok: boolean; store_errors: Record<string, string>
}

export const DESCRIBES = 'describes, does not predict'
export const SESSION_START_MIN = 9 * 60 + 15
export const SESSION_LEN_MIN = 375
export const TAPE_INDICES = ['NIFTY', 'BANKNIFTY', 'FINNIFTY'] as const

/** The chip the panel header shows, from the API's chip: DELAYED with the age recomputed at render time, never LIVE. */
export function tapeSource(chip: Chip | null | undefined, nowMs: number = Date.now()):
  { state: ChipState; source: string; asOf: string | null; ageS: number | null; hint: string } {
  if (!chip || chip.state === 'offline' || !chip.as_of) {
    return { state: 'offline', source: chip?.source ?? 'Breeze chain tape', asOf: chip?.as_of ?? null, ageS: null, hint: chip?.hint ?? 'no snapshot stored for this session' }
  }
  const t = Date.parse(chip.as_of)
  const ageS = Number.isFinite(t) ? Math.max(0, (nowMs - t) / 1000) : chip.age_s
  return { state: 'delayed', source: chip.source, asOf: chip.as_of, ageS: ageS ?? null, hint: chip.hint }
}

/** 'HH:MM' IST of an ISO stamp (the tape's ts are UTC with +00:00). '' when unparsable. */
export function istClock(iso: string | null | undefined): string {
  if (!iso) return ''
  const t = Date.parse(iso)
  if (!Number.isFinite(t)) return ''
  const d = new Date(t + 5.5 * 3600_000)
  return `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`
}

/** Minutes after 09:15 IST → 'HH:MM'. */
export function minuteLabel(m: number): string {
  const t = SESSION_START_MIN + Math.round(m)
  return `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`
}

/** 'HH:MM' IST → minutes after 09:15 (null when unparsable). */
export function minuteOf(hhmm: string | null | undefined): number | null {
  const m = /^(\d{1,2}):(\d{2})$/.exec(hhmm ?? '')
  return m ? Number(m[1]) * 60 + Number(m[2]) - SESSION_START_MIN : null
}

/** What "since the open" really means for this tape: the first snapshot's time, flagged when it is not the session open. */
export function sinceLabel(first: string | null | undefined): { text: string; late: boolean } {
  const m = minuteOf(first)
  if (m == null) return { text: 'since the first snapshot', late: false }
  const late = m > 6
  return { text: late ? `since ${first} (the first snapshot today: the tape started late)` : `since the open (${first})`, late }
}

/** Shares → lakh shares, or contracts when the lot is known. */
export function fmtOi(v: number | null | undefined, lot: number | null | undefined, asContracts: boolean): string {
  if (v == null || !Number.isFinite(v)) return '—'
  if (asContracts && lot && lot > 0) {
    const c = v / lot
    return Math.abs(c) >= 1e5 ? `${(c / 1e5).toFixed(2)} L` : Math.round(c).toLocaleString('en-IN')
  }
  return Math.abs(v) >= 1e5 ? `${(v / 1e5).toFixed(1)} L` : Math.round(v).toLocaleString('en-IN')
}

export function fmtSignedOi(v: number | null | undefined, lot: number | null | undefined, asContracts: boolean): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const s = fmtOi(Math.abs(v), lot, asContracts)
  return v > 0 ? `+${s}` : v < 0 ? `−${s}` : s
}

/** The OI-unwind read on an expiry day: how much of the morning's open interest has left, both sides. Context. */
export function unwindRead(rows: StrikeRow[]): { ceOpen: number; ceNow: number; peOpen: number; peNow: number; cePct: number | null; pePct: number | null } {
  const sum = (k: keyof StrikeRow) => rows.reduce((a, r) => a + (typeof r[k] === 'number' && Number.isFinite(r[k] as number) ? (r[k] as number) : 0), 0)
  const ceOpen = sum('ce_oi_open'), ceNow = sum('ce_oi'), peOpen = sum('pe_oi_open'), peNow = sum('pe_oi')
  return { ceOpen, ceNow, peOpen, peNow, cePct: ceOpen ? (ceNow / ceOpen - 1) * 100 : null, pePct: peOpen ? (peNow / peOpen - 1) * 100 : null }
}

/** Today's straddle against the historical expiry-day curve at the same minute: a sentence, never a direction. */
export function decayVsCurve(v: ExpiryLive['vs_curve'] | null | undefined): string | null {
  if (!v) return null
  const where = v.today_pct < v.p25 ? 'below the 25th percentile of' : v.today_pct > v.p75 ? 'above the 75th percentile of' : 'inside the middle half of'
  return `At ${minuteLabel(v.minute)} the straddle is ${v.today_pct.toFixed(0)} % of its value at today's first snapshot; past expiry days were at a median ` +
    `${v.median_pct.toFixed(0)} % (middle half ${v.p25.toFixed(0)}–${v.p75.toFixed(0)} %, ${v.n} expiries), so today is ${where} the record. ${cap(DESCRIBES)}.`
}

/** The scorecard's reading line. It repeats no number from the stat strip above it (PLAN §0.4: the same number once per page):
 *  it says how to read the strip. Arithmetic over past expiries; before costs. */
export function scoreRead(s: ScoreStats | null | undefined): string {
  if (!s || !s.n) return 'No scored expiry yet: the scorecard needs the last close before an expiry and NSE\'s settlement close.'
  const rate = s.exceeded_pct ?? 0
  const fair = s.fair_exceeded_pct ?? 42.5
  const side = rate > fair + 10 ? 'more often than' : rate < fair - 10 ? 'less often than' : 'about as often as'
  return `Read: the move to settlement beat the last-close straddle ${side} a fair price under a normal would allow, on these expiries; ` +
    `the RV20 guess is the naive comparator, as the gold accuracy log scores the fair open against yesterday's settlement. Before costs; ${DESCRIBES}.`
}

/** The XPRY header words. */
export function expiryWords(d: Pick<ExpiryDay, 'is_expiry_day' | 'next_expiry' | 'symbol' | 'date'> | null | undefined): string {
  if (!d) return ''
  if (d.is_expiry_day) return `${d.symbol} expires today (${d.date}): the expiring series is followed through the session until 15:30 IST.`
  return d.next_expiry
    ? `${d.date ? `${weekday(d.date)} ${d.date}` : 'Today'} is not a ${d.symbol} expiry; the next is ${weekday(d.next_expiry)} ${d.next_expiry}. The record below is kept every day.`
    : `${d.symbol}: no upcoming expiry stored.`
}

export function weekday(iso: string): string {
  const t = Date.parse(`${iso}T00:00:00Z`)
  return Number.isFinite(t) ? ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][new Date(t).getUTCDay()] : ''
}

function cap(s: string): string { return s.charAt(0).toUpperCase() + s.slice(1) }

/** A sentence start from an API phrase ('the tape snaps …' → 'The tape snaps …'). */
export function sentence(s: string | null | undefined): string { return s ? cap(s) : '' }

/** Frames index → the strike axis' OI for one frame (null-safe), for the time-lapse scrubber. */
export function frameAt(frames: Frame[], i: number): Frame | null {
  if (!frames.length) return null
  return frames[Math.max(0, Math.min(frames.length - 1, Math.round(i)))]
}

/** The series the tape chart draws, x = minutes after 09:15. */
export function tapeSeries(path: TapePoint[]): { x: number[]; iv: (number | null)[]; straddle: (number | null)[]; straddleOpen: (number | null)[]; pcr: (number | null)[]; maxPain: (number | null)[]; fwd: (number | null)[] } {
  const x = path.map(p => minuteOf(p.ist) ?? 0)
  return { x, iv: path.map(p => p.atm_iv), straddle: path.map(p => p.straddle), straddleOpen: path.map(p => p.straddle_open_strike), pcr: path.map(p => p.pcr),
           maxPain: path.map(p => p.max_pain), fwd: path.map(p => p.forward) }
}
