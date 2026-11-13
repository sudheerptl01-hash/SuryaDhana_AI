/**
 * RSK › DISCIPLINE — the pure model (FINAL ROUND wave B, B-COCKPIT; risk/SPEC.md §§1–5, owner decision O-F3).
 *
 * Everything React-free and DOM-free lives here so the node check (__tests__/discipline.check.ts) can exercise
 * the cap math, the streak rule, the 09:15 IST session reset, the trip/acknowledge state machine, the SPEC §3
 * banner copy (verbatim) and the scenario-strip parsing under plain node.
 *
 * Binding rules carried in code:
 *  - the cockpit NEVER blocks anything (O-F3): nothing here returns a "disallowed" state, only facts;
 *  - no direction words, no composite "discipline score";
 *  - badges: `heuristic` on the house rules, `arithmetic` on the sums — a `signal` badge does not exist;
 *  - wording is always "your rule" / "your cap": the terminal reports the owner's own limit back, it does not
 *    instruct; never "stop trading", never "don't", never a forecast.
 */

// ── prefs keys (stored through the generic PUT /api/prefs/{key}, LWW; 409 → adopt the server value) ──────────

export const DISCIPLINE_KEY = 'suryadhana.risk.discipline.v1'
export const STANDDOWN_KEY = 'suryadhana.risk.standdown.v1'
export const CHECKLIST_KEY = 'suryadhana.risk.checklist.v1'

// ── settings (SPEC §1) ────────────────────────────────────────────────────────────────────────────────────────

export interface DisciplineSettings {
  trading_capital_inr: number
  daily_loss_cap_pct: number
  daily_loss_warn_pct: number
  consecutive_loss_standdown_n: number
  max_trades_per_day: number
  trade_warn_at: number
  /** minutes; 0 = off */
  revenge_timer_min: number
  enabled: boolean
}

/** SPEC §1 defaults. The capital is a SEED (PAPER_FO_CAPITAL's default): the card opens in the
 *  "set your capital" state until the owner types it (configured = the pref key exists on the server). */
export const DEFAULT_SETTINGS: Readonly<DisciplineSettings> = Object.freeze({
  trading_capital_inr: 1_000_000,
  daily_loss_cap_pct: 2.0,
  daily_loss_warn_pct: 1.0,
  consecutive_loss_standdown_n: 3,
  max_trades_per_day: 5,
  trade_warn_at: 4,
  revenge_timer_min: 15,
  enabled: true,
})

const num = (v: unknown, fallback: number, min = 0, max = Number.MAX_SAFE_INTEGER): number => {
  const n = typeof v === 'number' && Number.isFinite(v) ? v : typeof v === 'string' && v.trim() !== '' ? Number(v) : NaN
  return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : fallback
}

/** Parse the stored JSON; null for absent/garbage (→ unconfigured: defaults shown, "set your capital" state). */
export function parseSettings(raw: string | null | undefined): DisciplineSettings | null {
  if (!raw) return null
  let o: unknown
  try { o = JSON.parse(raw) } catch { return null }
  if (typeof o !== 'object' || o === null || Array.isArray(o)) return null
  const d = o as Record<string, unknown>
  const s: DisciplineSettings = {
    trading_capital_inr: num(d.trading_capital_inr, DEFAULT_SETTINGS.trading_capital_inr, 1),
    daily_loss_cap_pct: num(d.daily_loss_cap_pct, DEFAULT_SETTINGS.daily_loss_cap_pct, 0.1, 100),
    daily_loss_warn_pct: num(d.daily_loss_warn_pct, DEFAULT_SETTINGS.daily_loss_warn_pct, 0, 100),
    consecutive_loss_standdown_n: Math.round(num(d.consecutive_loss_standdown_n, DEFAULT_SETTINGS.consecutive_loss_standdown_n, 1, 99)),
    max_trades_per_day: Math.round(num(d.max_trades_per_day, DEFAULT_SETTINGS.max_trades_per_day, 1, 999)),
    trade_warn_at: Math.round(num(d.trade_warn_at, DEFAULT_SETTINGS.trade_warn_at, 0, 999)),
    revenge_timer_min: Math.round(num(d.revenge_timer_min, DEFAULT_SETTINGS.revenge_timer_min, 0, 24 * 60)),
    enabled: d.enabled !== false,
  }
  return s
}

export const serializeSettings = (s: DisciplineSettings): string => JSON.stringify(s)

/** The daily loss cap in ₹ (realised + MTM against it). */
export const capInr = (s: DisciplineSettings): number => (s.trading_capital_inr * s.daily_loss_cap_pct) / 100
export const warnInr = (s: DisciplineSettings): number => (s.trading_capital_inr * s.daily_loss_warn_pct) / 100

// ── ₹ formatting (pure; the terminal kit's fmtInr lives in a React module) ──────────────────────────────────

/** ₹ with en-IN grouping and the U+2212 minus, 0 decimals: −₹21,400. */
export function inr(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const a = Math.abs(Math.round(v))
  return `${v < 0 ? '−' : ''}₹${a.toLocaleString('en-IN')}`
}

const pct1 = (v: number): string => v.toFixed(1)

// ── IST session (reset at the next session's 09:15, SPEC §1) ────────────────────────────────────────────────

const IST_OFFSET_MS = 330 * 60_000
const SESSION_OPEN_MIN = 9 * 60 + 15

/**
 * The discipline session a moment belongs to: the IST calendar day once 09:15 IST has passed, else the previous
 * day. A record whose `session` differs from the current one is expired (the automatic clear — never a button).
 */
export function sessionKey(nowMs: number): string {
  const ist = new Date(nowMs + IST_OFFSET_MS)
  const mins = ist.getUTCHours() * 60 + ist.getUTCMinutes()
  if (mins < SESSION_OPEN_MIN) ist.setUTCDate(ist.getUTCDate() - 1)
  return ist.toISOString().slice(0, 10)
}

/** The calendar day on which a session's stand-down actually resets (09:15 IST the day after `session`). */
export function resetDateOf(session: string): string {
  const d = new Date(`${session}T00:00:00Z`)
  if (!Number.isFinite(d.getTime())) return session
  d.setUTCDate(d.getUTCDate() + 1)
  return d.toISOString().slice(0, 10)
}

// ── the day read (SPEC §6 M1: GET /api/options/book/day) ────────────────────────────────────────────────────

export interface DayTrade {
  at?: string | null
  action?: string | null
  kind?: string | null
  structure_id?: number | null
  symbol?: string | null
  realised_inr?: number | null
  [k: string]: unknown
}

export interface DayBook {
  date: string
  realised_inr: number | null
  mtm_change_inr: number | null
  bookings: number
  closes: number
  loss_streak: number
  trades: DayTrade[]
  as_of?: string | null
  capital?: { value: number; source: string } | null
  paper_only?: boolean
  note?: string | null
}

/** realised + MTM change for the day; null only when both halves are unknown. */
export function dayPnl(day: Pick<DayBook, 'realised_inr' | 'mtm_change_inr'> | null | undefined): number | null {
  if (!day) return null
  const r = day.realised_inr, m = day.mtm_change_inr
  if (r == null && m == null) return null
  return (r ?? 0) + (m ?? 0)
}

// ── stand-down record + trip/acknowledge state machine (SPEC §1/§3) ─────────────────────────────────────────

export type StandDownRule = 'daily_cap' | 'consec_losses'

export interface StandDownRecord {
  tripped_at: number
  rule: StandDownRule
  /** e.g. "−₹21,400 vs ₹20,000 cap" (SPEC §1's example shape) */
  detail: string
  session: string
  acknowledged: boolean
  /** extra context captured at the trip so the banner can print SPEC §3's copy verbatim (optional, additive) */
  lost_inr?: number
  cap_inr?: number
  cap_pct?: number
  losses_n?: number
}

export function parseStandDown(raw: string | null | undefined): StandDownRecord | null {
  if (!raw) return null
  let o: unknown
  try { o = JSON.parse(raw) } catch { return null }
  if (typeof o !== 'object' || o === null) return null
  const d = o as Record<string, unknown>
  if (typeof d.session !== 'string' || (d.rule !== 'daily_cap' && d.rule !== 'consec_losses')) return null
  return {
    tripped_at: num(d.tripped_at, 0),
    rule: d.rule,
    detail: typeof d.detail === 'string' ? d.detail : '',
    session: d.session,
    acknowledged: d.acknowledged === true,
    lost_inr: typeof d.lost_inr === 'number' ? d.lost_inr : undefined,
    cap_inr: typeof d.cap_inr === 'number' ? d.cap_inr : undefined,
    cap_pct: typeof d.cap_pct === 'number' ? d.cap_pct : undefined,
    losses_n: typeof d.losses_n === 'number' ? d.losses_n : undefined,
  }
}

export const serializeStandDown = (r: StandDownRecord): string => JSON.stringify(r)

/** A record counts only for its own session (the automatic 09:15 reset; expired records are simply ignored). */
export function standDownActive(rec: StandDownRecord | null, nowMs: number): boolean {
  return rec != null && rec.session === sessionKey(nowMs)
}

// ── the evaluation (arithmetic over the day read; decides warn / trip facts, blocks nothing) ───────────────

export interface DayEval {
  /** realised + MTM change today, ₹ (null: unknown) */
  pnl: number | null
  /** the loss side of pnl, ≥ 0 */
  lossInr: number
  /** loss ÷ cap (0–…), null when unconfigured */
  usedFrac: number | null
  /** loss as % of trading capital, null when unconfigured */
  lossPctOfCapital: number | null
  bookings: number
  closes: number
  streak: number
  /** a trip the rules call for right now (the guard writes the record once per session) */
  trip: { rule: StandDownRule; detail: string; lost_inr?: number; cap_inr?: number; cap_pct?: number; losses_n?: number } | null
  /** amber pre-stage chip text (SPEC §3), null when nothing is at warn */
  amberChip: string | null
  /** epoch ms until which the cooling note shows (SPEC §1 revenge_timer_min), null when inactive */
  revengeUntil: number | null
}

const EMPTY_EVAL: DayEval = { pnl: null, lossInr: 0, usedFrac: null, lossPctOfCapital: null, bookings: 0, closes: 0, streak: 0, trip: null, amberChip: null, revengeUntil: null }

/**
 * Evaluate the owner's rules against today's PAPER book day read. `settings == null` (unconfigured) or
 * `enabled: false` evaluates the sums but never a trip or a chip — the rules are the owner's and need the typed
 * capital to mean anything.
 */
export function evalDay(settings: DisciplineSettings | null, day: DayBook | null, nowMs: number): DayEval {
  if (!day) return EMPTY_EVAL
  const pnl = dayPnl(day)
  const lossInr = pnl != null && pnl < 0 ? -pnl : 0
  const bookings = num(day.bookings, 0)
  const closes = num(day.closes, 0)
  const streak = Math.round(num(day.loss_streak, 0))
  if (!settings) return { ...EMPTY_EVAL, pnl, lossInr, bookings, closes, streak }
  const cap = capInr(settings)
  const usedFrac = cap > 0 ? lossInr / cap : null
  const lossPctOfCapital = settings.trading_capital_inr > 0 ? (lossInr / settings.trading_capital_inr) * 100 : null
  const base: DayEval = { pnl, lossInr, usedFrac, lossPctOfCapital, bookings, closes, streak, trip: null, amberChip: null, revengeUntil: null }
  if (!settings.enabled) return base

  // trips (loss rules only — the trade counter never trips, SPEC §1)
  let trip: DayEval['trip'] = null
  if (lossInr >= cap && cap > 0) {
    trip = { rule: 'daily_cap', detail: `−${inr(lossInr).replace('−', '')} vs ${inr(cap)} cap`, lost_inr: lossInr, cap_inr: cap, cap_pct: settings.daily_loss_cap_pct }
  } else if (streak >= settings.consecutive_loss_standdown_n) {
    trip = { rule: 'consec_losses', detail: `${streak} losses in a row`, losses_n: streak }
  }

  // amber pre-stage chip (header only, no banner): DISCIPLINE · −1.2 % of 2.0 % cap · 4 of 5 trades
  const parts: string[] = []
  if (lossPctOfCapital != null && lossPctOfCapital >= settings.daily_loss_warn_pct && settings.daily_loss_warn_pct > 0 && !trip) {
    parts.push(`−${pct1(lossPctOfCapital)} % of ${pct1(settings.daily_loss_cap_pct)} % cap`)
  }
  if (bookings >= settings.trade_warn_at && settings.trade_warn_at > 0 && !trip) {
    parts.push(`${bookings} of ${settings.max_trades_per_day} trades`)
  }
  const amberChip = parts.length ? `DISCIPLINE · ${parts.join(' · ')}` : null

  // revenge timer: after any single realised loss ≥ 0.5 × the daily cap, a quiet per-card countdown
  let revengeUntil: number | null = null
  if (settings.revenge_timer_min > 0 && cap > 0) {
    for (const t of day.trades ?? []) {
      const r = typeof t?.realised_inr === 'number' ? t.realised_inr : null
      if (r == null || r > -0.5 * cap) continue
      const at = typeof t?.at === 'string' ? Date.parse(t.at) : NaN
      if (!Number.isFinite(at)) continue
      const until = at + settings.revenge_timer_min * 60_000
      if (until > nowMs && (revengeUntil == null || until > revengeUntil)) revengeUntil = until
    }
  }
  return { ...base, trip, amberChip, revengeUntil }
}

/** The record the guard writes when `evalDay` calls a trip and no record exists for this session. */
export function tripRecord(trip: NonNullable<DayEval['trip']>, nowMs: number): StandDownRecord {
  return { tripped_at: nowMs, rule: trip.rule, detail: trip.detail, session: sessionKey(nowMs), acknowledged: false,
           lost_inr: trip.lost_inr, cap_inr: trip.cap_inr, cap_pct: trip.cap_pct, losses_n: trip.losses_n }
}

// ── banner copy (SPEC §3, VERBATIM — never "stop trading", never "don't", always "your rule") ───────────────

export const BANNER_SUFFIX = 'your rule, set in RSK › DISCIPLINE · resets at the next session open'

/** The banner's main sentence for a record. Falls back to the record's own detail when the context fields are absent. */
export function bannerMain(rec: StandDownRecord): string {
  if (rec.rule === 'daily_cap') {
    if (rec.lost_inr != null && rec.cap_inr != null && rec.cap_pct != null) {
      return `your daily loss cap is reached — ${inr(rec.lost_inr)} lost of your ${inr(rec.cap_inr)} cap (${pct1(rec.cap_pct)} % of capital)`
    }
    return `your daily loss cap is reached — ${rec.detail}`
  }
  return `${rec.losses_n ?? rec.detail.split(' ')[0]} losses in a row — your stand-down rule`
}

// ── checklist (SPEC §5): one key, rewritten per session, items per symbol ──────────────────────────────────

export interface ChecklistItems {
  event: boolean
  iv: boolean
  max_loss: boolean
  margin: boolean
  max_loss_inr: number | null
}

export interface ChecklistState {
  session: string
  items: Record<string, ChecklistItems>
}

export const EMPTY_ITEMS: Readonly<ChecklistItems> = Object.freeze({ event: false, iv: false, max_loss: false, margin: false, max_loss_inr: null })

/** Parse the stored state; a different session resets it (one key, rewritten daily — SPEC §1). */
export function parseChecklist(raw: string | null | undefined, session: string): ChecklistState {
  const fresh: ChecklistState = { session, items: {} }
  if (!raw) return fresh
  let o: unknown
  try { o = JSON.parse(raw) } catch { return fresh }
  if (typeof o !== 'object' || o === null) return fresh
  const d = o as Record<string, unknown>
  if (d.session !== session || typeof d.items !== 'object' || d.items === null) return fresh
  const items: Record<string, ChecklistItems> = {}
  for (const [sym, v] of Object.entries(d.items as Record<string, unknown>)) {
    if (typeof v !== 'object' || v === null) continue
    const it = v as Record<string, unknown>
    items[sym] = {
      event: it.event === true, iv: it.iv === true, max_loss: it.max_loss === true, margin: it.margin === true,
      max_loss_inr: typeof it.max_loss_inr === 'number' && Number.isFinite(it.max_loss_inr) ? it.max_loss_inr : null,
    }
  }
  return { session, items }
}

export const serializeChecklist = (s: ChecklistState): string => JSON.stringify(s)

export const tickedCount = (it: ChecklistItems): number => [it.event, it.iv, it.max_loss, it.margin].filter(Boolean).length

/** The journal note an unticked checklist books with (SPEC §5): "checklist: 2/4". */
export const checklistNote = (it: ChecklistItems): string => `checklist: ${tickedCount(it)}/4`

/** Item 3's arithmetic line: the typed max loss vs what is left under the daily cap today. */
export function maxLossLine(maxLoss: number | null, remainingCapInr: number | null): { text: string; warn: boolean } {
  if (maxLoss == null || !Number.isFinite(maxLoss)) return { text: 'type the structure’s max loss in ₹', warn: false }
  if (remainingCapInr == null) return { text: `${inr(maxLoss)} — set your capital in RSK › DISCIPLINE to compare with your daily cap`, warn: false }
  if (maxLoss <= remainingCapInr) return { text: `${inr(maxLoss)} — fits the ${inr(remainingCapInr)} left under your daily cap today`, warn: false }
  return { text: `${inr(maxLoss)} — exceeds the ${inr(remainingCapInr)} left under your daily cap today`, warn: true }
}

/** What is left of the daily cap right now (cap − today's loss), ≥ 0; null when unconfigured. */
export function remainingCap(settings: DisciplineSettings | null, ev: DayEval): number | null {
  if (!settings) return null
  const cap = capInr(settings)
  if (!(cap > 0)) return null
  return Math.max(0, cap - ev.lossInr)
}

// ── scenario strip (SPEC §4): parse GET /api/risk/fo's scenarios into the tile row ─────────────────────────

export interface ScenarioTile {
  id: string
  label: string
  pnl: number | null
  /** 'spot' | 'iv' | 'theta' — the strip groups them with separators */
  group: 'spot' | 'iv' | 'theta'
}

export interface ScenarioStripData {
  empty: boolean
  asOf: string | null
  tiles: ScenarioTile[]
  note: string | null
}

const asNum = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

/**
 * Parse a GET /api/risk/fo payload (unknown shape by design: M2 adds ±1 % gaps and a theta row that the typed
 * client does not carry yet). Missing rows render as — , never invented.
 */
export function parseScenarios(payload: unknown): ScenarioStripData {
  const d = (typeof payload === 'object' && payload !== null ? payload : {}) as Record<string, unknown>
  const empty = d.empty === true || !d.scenarios
  // SPEC §4's hover names the MARKS' as-of (mark_source.as_of); the payload's own as_of is the fallback
  const ms = (typeof d.mark_source === 'object' && d.mark_source !== null ? d.mark_source : {}) as Record<string, unknown>
  const asOf = typeof ms.as_of === 'string' ? ms.as_of : typeof d.as_of === 'string' ? d.as_of : null
  const sc = (typeof d.scenarios === 'object' && d.scenarios !== null ? d.scenarios : {}) as Record<string, unknown>
  const gap = Array.isArray(sc.gap) ? (sc.gap as Record<string, unknown>[]) : []
  const iv = Array.isArray(sc.iv_shock) ? (sc.iv_shock as Record<string, unknown>[]) : []
  const theta = Array.isArray(sc.theta) ? (sc.theta as Record<string, unknown>[]) : []
  const gapAt = (p: number): number | null => {
    const row = gap.find(g => asNum(g.spot_pct) === p)
    return row ? asNum(row.pnl_inr) : null
  }
  const ivAt = (p: number): number | null => {
    const row = iv.find(g => asNum(g.iv_shift) === p)
    return row ? asNum(row.pnl_inr) : null
  }
  const theta1 = ((): number | null => {
    const row = theta.find(t => asNum(t.days_fwd) === 1)
    if (row) return asNum(row.pnl_inr)
    return asNum(sc.theta_1d_inr)   // pre-M2 payloads carry theta_1d_inr
  })()
  const tiles: ScenarioTile[] = [
    { id: 'spot-2', label: 'SPOT −2 %', pnl: gapAt(-2), group: 'spot' },
    { id: 'spot-1', label: 'SPOT −1 %', pnl: gapAt(-1), group: 'spot' },
    { id: 'spot+1', label: 'SPOT +1 %', pnl: gapAt(1), group: 'spot' },
    { id: 'spot+2', label: 'SPOT +2 %', pnl: gapAt(2), group: 'spot' },
    { id: 'iv-5', label: 'IV −5 pts', pnl: ivAt(-5), group: 'iv' },
    { id: 'iv+5', label: 'IV +5 pts', pnl: ivAt(5), group: 'iv' },
    { id: 'theta-1d', label: 'T −1d', pnl: theta1, group: 'theta' },
  ]
  const note = typeof sc.note === 'string' ? sc.note : null
  return { empty, asOf, tiles, note }
}

/**
 * Tile tone by |loss| vs the daily cap remaining (SPEC §4). Only losses take a tone: the meter/tone is a
 * position on the owner's own scale, never a direction colour. Unconfigured cockpit → always muted.
 */
export function scenarioTone(pnl: number | null, remainingCapInr: number | null): 'muted' | 'amber' | 'red' {
  if (pnl == null || pnl >= 0 || remainingCapInr == null || remainingCapInr <= 0) return 'muted'
  const loss = -pnl
  if (loss >= remainingCapInr) return 'red'
  if (loss >= 0.5 * remainingCapInr) return 'amber'
  return 'muted'
}

// ── RULES card rows (SPEC §2 card 2): value · setting · rationale hover ────────────────────────────────────

export const HOUSE_RULE_SUFFIX = 'a house rule; describes your own limits, does not predict'

export interface RuleRow { id: string; label: string; setting: string; current: string; state: 'ok' | 'warn' | 'hit'; rationale: string }

export function ruleRows(s: DisciplineSettings, ev: DayEval): RuleRow[] {
  const cap = capInr(s)
  const lossState: RuleRow['state'] = ev.lossInr >= cap && cap > 0 ? 'hit' : ev.lossInr >= warnInr(s) && warnInr(s) > 0 ? 'warn' : 'ok'
  const tradeState: RuleRow['state'] = ev.bookings >= s.max_trades_per_day ? 'hit' : ev.bookings >= s.trade_warn_at && s.trade_warn_at > 0 ? 'warn' : 'ok'
  const streakState: RuleRow['state'] = ev.streak >= s.consecutive_loss_standdown_n ? 'hit' : ev.streak >= s.consecutive_loss_standdown_n - 1 && ev.streak > 0 ? 'warn' : 'ok'
  return [
    { id: 'cap', label: 'Daily loss cap', setting: `${inr(cap)} (${pct1(s.daily_loss_cap_pct)} % of capital)`, current: `${inr(-ev.lossInr)} today`, state: lossState,
      rationale: 'At a 2 % daily cap a worst-case losing week is ≈ −9.6 % — a hole that refills; at 5 % the same week needs +29 %. Prop-desk convention is 1–3 % a day.' },
    { id: 'warn', label: 'Amber warning', setting: `${pct1(s.daily_loss_warn_pct)} % of capital`, current: ev.lossPctOfCapital != null ? `−${pct1(ev.lossPctOfCapital)} % today` : '—', state: lossState === 'hit' ? 'hit' : lossState,
      rationale: 'An early marker at half the cap: seen before the cap, not after.' },
    { id: 'streak', label: 'Consecutive-loss stand-down', setting: `${s.consecutive_loss_standdown_n} losses in a row`, current: `${ev.streak} now`, state: streakState,
      rationale: 'At a ~50 % hit rate, 3 in a row happens by chance ~12.5 % of the time a sequence starts — rare enough to respect, frequent enough not to tune out. 2 would nag; 4+ lets a tilt run.' },
    { id: 'trades', label: 'Trades per day', setting: `${s.max_trades_per_day} (amber at ${s.trade_warn_at})`, current: `${ev.bookings} booked · ${ev.closes} closed`, state: tradeState,
      rationale: 'SEBI FY22/FY24: losses scale with churn. Five round-trips is a full day for a discretionary index-options trader. A counter only — it never trips the stand-down.' },
    { id: 'revenge', label: 'Cooling timer', setting: s.revenge_timer_min > 0 ? `${s.revenge_timer_min} min after a loss ≥ half the cap` : 'off', current: ev.revengeUntil != null ? 'counting' : '—', state: 'ok',
      rationale: 'The worst trades cluster immediately after losses (Chague et al.). Optional by design; 0 switches it off.' },
  ]
}

// ── countdown text ─────────────────────────────────────────────────────────────────────────────────────────

/** "14:59" for the cooling countdown. */
export function mmss(remainingMs: number): string {
  const s = Math.max(0, Math.ceil(remainingMs / 1000))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
