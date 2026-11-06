/**
 * The typed alert engine, UI half (Terminal v2 PLAN 2.3, review M41). Pure, no imports: unit-tested under plain node by
 * `ui/lib/__tests__/alertsEngine.check.ts`. The rule model and the evaluator live on the server
 * (services/ui-api/alert_engine.py, routes /api/alerts/rules · /series · /fires · /run); this file holds the types, the
 * builder's presets, the direction-word scan (the same vocabulary as the server's), the fired-inbox grouping, the
 * create-alert hand-off other pages use (lib/alerts.ts `draftAlert`) and the inbox hints for stale or unlabelled note
 * figures (review m084 / m085).
 *
 * Binding (PLAN §0): an alert describes a level, never a direction; nothing here feeds the Decision Desk, the S1
 * shadow or a ticket price; every fire carries its badge (arithmetic / context), as-of and source.
 */

export type AlertOp = 'above' | 'below' | 'cross_up' | 'cross_down' | 'change_pct' | 'pctile_above' | 'pctile_below' | 'changed'
export type AlertChannel = 'mac' | 'telegram' | 'both'
export type AlertRepeat = 'once' | 'repeat'

export const OPS: readonly AlertOp[] = ['above', 'below', 'cross_up', 'cross_down', 'change_pct', 'pctile_above', 'pctile_below', 'changed']

/** What each op means, in the builder (direction-free: "at or over", never "breaks out"). */
export const OP_LABEL: Readonly<Record<AlertOp, string>> = {
  above: 'at or over', below: 'at or under', cross_up: 'crosses from under', cross_down: 'crosses from over',
  change_pct: 'moves ± % (either way)', pctile_above: 'percentile at or over', pctile_below: 'percentile at or under', changed: 'changes',
}
export const CHANNEL_LABEL: Readonly<Record<AlertChannel, string>> = { mac: 'Mac', telegram: 'Telegram', both: 'Mac + Telegram' }

export interface SeriesKind {
  kind: string
  /** the builder's picker name ("OI at a strike"); older catalogues may lack it */
  name?: string
  label: string
  unit: string
  badge: string
  cadence: 'live' | 'eod' | 'hourly' | string
  params: string[]
  optional: string[]
  ops: AlertOp[]
  source: string
  group: string
  definition: string
  example: string
  history: boolean
  category: boolean
}

export interface AlertRuleDraft {
  series: string
  op: AlertOp
  value?: number | null
  window?: number | null
  cooldown_min?: number | null
  repeat?: AlertRepeat
  channel?: AlertChannel
  note?: string | null
}

export interface AlertRule extends AlertRuleDraft {
  id: string
  kind: string
  symbol: string | null
  params: Record<string, string | number>
  status: 'active' | 'snoozed' | 'paused' | 'fired'
  snooze_until: string | null
  origin: 'rule' | 'price'
  created_at: string
  updated_at: string
  state: { last_value?: number | string | null; last_as_of?: string | null; last_fired_at?: string; fires?: number; last_error?: string | null; checked_at?: string }
  summary?: string
  label?: string
  condition?: string
  unit?: string
  badge?: string
  cadence?: string
  source?: string
  last_fired_at?: string | null
}

export interface AlertFire {
  seq: number
  origin: 'rule' | 'price'
  rule_id: string | null
  series: string | null
  kind: string | null
  symbol: string | null
  at: string
  as_of: string | null
  text: string
  channel: AlertChannel | string
  badge: string | null
  label?: string | null
  source?: string | null
  dispatched?: boolean
}

export interface FireGroup { symbol: string; count: number; last_at: string; fires: AlertFire[] }

export interface DryRow {
  id: string
  value: number | string | null
  as_of: string | null
  source: string
  metric: number | null
  satisfied: boolean | null
  reason: string | null
  unit: string
  badge: string
  history_n: number
}

// ── direction words (the server's vocabulary: alert_engine.DIRECTION_PATTERNS; the check compares the two) ──────
export const DIRECTION_PATTERNS: readonly string[] = [
  'bullish', 'bearish', 'buy(s|ing)?', 'sell(s|ing)?', 'sold', 'overbought', 'oversold', 'break(out|down)s?',
  'upside', 'downside', 'up-?trend', 'down-?trend', 'out-?perform\\w*', 'under-?perform\\w*', 'rall(y|ies)',
  'long', 'short', 'short[- ]covering', 'long[- ]unwinding', '(will|should|likely to|expected to)\\s+(rise|fall|go up|go down)',
  'price target', 'support level', 'resistance', 'go (long|short)', 'targets?', 'forecast\\w*',
]
/** Position names (both sides alike) and the options term "expected move": removed before the scan, never after "go ". */
export const ALLOWED_PHRASES: readonly string[] = [
  'short-option minimum', 'short-option', 'short option', 'long-option', 'long option', 'short strangle', 'short straddle',
  'long strangle', 'long straddle', 'short call', 'short put', 'long call', 'long put', 'expected move',
]
/** A note is also refused for predictive phrasing ("bounce expected", "goes higher from here"): alert_engine.NOTE_PATTERNS. */
export const NOTE_PATTERNS: readonly string[] = [
  'bounc\\w*', 'expect\\w*', '(go|goes|going|head|heads|heading|move|moves|moving|push|pushes|pushing|trade|trades|trading)\\s+(higher|lower)',
  '(higher|lower) (high|low)s?', '(will|could|may|might|going to)\\s+(rise|fall|climb|drop|recover|crash|go up|go down)',
]
const DIRECTION_RE = new RegExp(`\\b(${DIRECTION_PATTERNS.join('|')})\\b`, 'gi')
const NOTE_RE = new RegExp(`\\b(${NOTE_PATTERNS.join('|')})\\b`, 'gi')

function stripAllowed(text: string): string {
  let t = text
  for (const p of ALLOWED_PHRASES) t = t.replace(new RegExp(`(?<!go )${p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}`, 'gi'), ' ')
  return t
}

/** The direction words in a text (empty = clean). */
export function directionWords(text: string | null | undefined): string[] {
  const out = new Set<string>()
  for (const m of stripAllowed(String(text ?? '')).matchAll(DIRECTION_RE)) out.add(m[0].toLowerCase())
  return [...out].sort()
}

/** The direction words AND the predictive phrases in an owner's note (empty = clean): the server's note_words. */
export function noteWords(text: string | null | undefined): string[] {
  const t = stripAllowed(String(text ?? ''))
  const out = new Set<string>()
  for (const rx of [DIRECTION_RE, NOTE_RE]) for (const m of t.matchAll(rx)) out.add(m[0].toLowerCase())
  return [...out].sort()
}

// ── series ids and the builder ─────────────────────────────────────────────────────────────────────────────────
const SYMBOL_RE = /^[A-Z0-9&_-]{1,20}$/
const ISO_DAY = /^\d{4}-\d{2}-\d{2}$/

/** 'oi_strike' + {symbol: 'NIFTY', strike: 24500, side: 'CE'} → 'oi_strike:NIFTY:24500:CE' (null when a required param is missing). */
export function seriesId(kind: SeriesKind, params: Record<string, string | number | null | undefined>): string | null {
  const parts = [kind.kind]
  for (const p of kind.params) {
    const v = params[p]
    if (v === null || v === undefined || String(v).trim() === '') return null
    parts.push(String(v).trim())
  }
  for (const p of kind.optional) {
    const v = params[p]
    if (v === null || v === undefined || String(v).trim() === '') break
    parts.push(String(v).trim())
  }
  return parts.join(':')
}

/** A param's own check (the server re-checks): '' = fine, else what to change. */
export function paramProblem(name: string, raw: string | number | null | undefined): string {
  const v = String(raw ?? '').trim()
  if (name === 'symbol') return SYMBOL_RE.test(v.toUpperCase().replace(/\.NS$/, '')) ? '' : 'an NSE symbol (TCS, M&M, NIFTY)'
  if (name === 'strike') return Number(v) > 0 ? '' : 'a strike (e.g. 24500)'
  if (name === 'side') return v.toUpperCase() === 'CE' || v.toUpperCase() === 'PE' ? '' : 'CE or PE'
  if (name === 'expiry') return v === '' || ISO_DAY.test(v) ? '' : 'YYYY-MM-DD'
  if (name === 'index') return v.toUpperCase() === 'NIFTY' || v.toUpperCase() === 'BANKNIFTY' ? '' : 'NIFTY or BANKNIFTY'
  if (name === 'dataset') return v === 'any' || /^[a-z0-9_]{1,60}$/.test(v) ? '' : "a dataset id from SYS › DATA, or 'any'"
  return ''
}

export interface DraftForm {
  kind: string
  params: Record<string, string>
  op: AlertOp
  value: string
  window: string
  cooldown: string
  repeat: AlertRepeat
  channel: AlertChannel
  note: string
}

/** The builder's form → a rule body, or the reason it cannot be sent yet. */
export function draftFromForm(f: DraftForm, kinds: readonly SeriesKind[]): { draft: AlertRuleDraft | null; problem: string } {
  const kind = kinds.find(k => k.kind === f.kind)
  if (!kind) return { draft: null, problem: 'pick a series' }
  for (const p of [...kind.params, ...kind.optional]) {
    const why = paramProblem(p, f.params[p])
    if (why && (kind.params.includes(p) || String(f.params[p] ?? '').trim() !== '')) return { draft: null, problem: `${p}: ${why}` }
  }
  const norm: Record<string, string> = {}
  for (const [k, v] of Object.entries(f.params)) norm[k] = k === 'symbol' || k === 'side' || k === 'index' ? String(v).trim().toUpperCase().replace(/\.NS$/, '') : String(v).trim()
  const series = seriesId(kind, norm)
  if (!series) return { draft: null, problem: 'fill every series field' }
  if (!kind.ops.includes(f.op)) return { draft: null, problem: `${kind.kind} supports ${kind.ops.join(', ')}` }
  const num = (s: string): number | null => (s.trim() === '' || !Number.isFinite(Number(s)) ? null : Number(s))
  const value = f.op === 'changed' ? null : num(f.value)
  if (f.op !== 'changed' && value === null && kind.unit !== 'flag') return { draft: null, problem: 'a value (a number)' }
  if ((f.op === 'pctile_above' || f.op === 'pctile_below') && value !== null && (value < 0 || value > 100)) return { draft: null, problem: 'a percentile is 0–100' }
  if (f.op === 'change_pct' && value !== null && value <= 0) return { draft: null, problem: 'the size of the move in %, above 0' }
  const words = noteWords(f.note)
  if (words.length) return { draft: null, problem: `the note carries direction words (${words.join(', ')}): describe the level or the position, not a direction` }
  return {
    draft: {
      series, op: f.op, value, window: num(f.window), cooldown_min: num(f.cooldown), repeat: f.repeat, channel: f.channel,
      note: f.note.trim() || null,
    },
    problem: '',
  }
}

/** A draft (from a preset or another page) → the builder's form. Unknown series → null. */
export function formFromDraft(d: AlertRuleDraft, kinds: readonly SeriesKind[]): DraftForm | null {
  const [head, ...args] = String(d.series || '').split(':')
  const kind = kinds.find(k => k.kind === head)
  if (!kind) return null
  const params: Record<string, string> = {}
  ;[...kind.params, ...kind.optional].forEach((p, i) => { if (args[i] !== undefined) params[p] = args[i] })
  const op = kind.ops.includes(d.op) ? d.op : kind.ops[0]
  return {
    kind: kind.kind, params, op, value: d.value === null || d.value === undefined ? '' : String(d.value),
    window: d.window ? String(d.window) : '', cooldown: d.cooldown_min === null || d.cooldown_min === undefined ? '' : String(d.cooldown_min),
    repeat: d.repeat ?? 'repeat', channel: d.channel ?? 'both', note: d.note ?? '',
  }
}

export interface Preset { id: string; label: string; needs: 'symbol' | 'none'; draft: (symbol: string) => AlertRuleDraft }

/** The builder's quick picks (each a full rule; the owner edits before saving). Labels are direction-free. */
export const PRESETS: readonly Preset[] = [
  { id: 'ivp80', label: 'IV percentile ≥ 80', needs: 'symbol', draft: s => ({ series: `iv_pctile:${s}`, op: 'above', value: 80, repeat: 'repeat', cooldown_min: 1440 }) },
  { id: 'ivp20', label: 'IV percentile ≤ 20', needs: 'symbol', draft: s => ({ series: `iv_pctile:${s}`, op: 'below', value: 20, repeat: 'repeat', cooldown_min: 1440 }) },
  { id: 'ivrv', label: 'IV − RV20 (cc) ≤ −3 vol pts', needs: 'symbol', draft: s => ({ series: `iv_rv:${s}`, op: 'below', value: -3, repeat: 'repeat', cooldown_min: 1440 }) },
  { id: 'skew', label: '25Δ skew pctile ≥ 90', needs: 'symbol', draft: s => ({ series: `skew25:${s}`, op: 'pctile_above', value: 90, window: 252, repeat: 'repeat', cooldown_min: 1440 }) },
  { id: 'wallce', label: 'Call OI wall moved', needs: 'symbol', draft: s => ({ series: `oi_wall:${s}:CE`, op: 'changed', repeat: 'repeat', cooldown_min: 0 }) },
  { id: 'wallpe', label: 'Put OI wall moved', needs: 'symbol', draft: s => ({ series: `oi_wall:${s}:PE`, op: 'changed', repeat: 'repeat', cooldown_min: 0 }) },
  { id: 'banin', label: 'F&O ban entry', needs: 'symbol', draft: s => ({ series: `fo_ban:${s}`, op: 'cross_up', value: 0.5, repeat: 'repeat', cooldown_min: 0 }) },
  { id: 'banout', label: 'F&O ban exit', needs: 'symbol', draft: s => ({ series: `fo_ban:${s}`, op: 'cross_down', value: 0.5, repeat: 'repeat', cooldown_min: 0 }) },
  { id: 'res5', label: 'Results within 5 days', needs: 'symbol', draft: s => ({ series: `results_days:${s}`, op: 'below', value: 5, repeat: 'repeat', cooldown_min: 0 }) },
  { id: 'roll', label: 'Rollover ≥ 60 %', needs: 'symbol', draft: s => ({ series: `rollover:${s}`, op: 'above', value: 60, repeat: 'once' }) },
  { id: 'rollpace', label: 'Rollover ≥ +10 pp vs 3-cycle avg', needs: 'symbol', draft: s => ({ series: `rollover_pace:${s}`, op: 'above', value: 10, repeat: 'repeat', cooldown_min: 1440 }) },
  { id: 'basis0', label: 'Futures basis at or under 0', needs: 'symbol', draft: s => ({ series: `basis:${s}`, op: 'below', value: 0, repeat: 'repeat', cooldown_min: 1440 }) },
  { id: 'vix10', label: 'India VIX ±10 % on the day', needs: 'none', draft: () => ({ series: 'vix', op: 'change_pct', value: 10, window: 1, repeat: 'repeat', cooldown_min: 120 }) },
  { id: 'fii95', label: 'FII net pctile ≥ 95', needs: 'none', draft: () => ({ series: 'fii_net', op: 'pctile_above', value: 95, window: 252, repeat: 'repeat', cooldown_min: 0 }) },
  { id: 'fii5', label: 'FII net pctile ≤ 5', needs: 'none', draft: () => ({ series: 'fii_net', op: 'pctile_below', value: 5, window: 252, repeat: 'repeat', cooldown_min: 0 }) },
  { id: 'driver', label: 'NIFTY driver changed', needs: 'none', draft: () => ({ series: 'nifty_driver:NIFTY', op: 'changed', repeat: 'repeat', cooldown_min: 0 }) },
  { id: 'gold', label: 'Gold health clause changed', needs: 'none', draft: () => ({ series: 'gold_health', op: 'changed', repeat: 'repeat', cooldown_min: 0 }) },
  { id: 'stale', label: 'Any dataset amber / red', needs: 'none', draft: () => ({ series: 'data_stale:any', op: 'above', value: 1, repeat: 'repeat', cooldown_min: 240 }) },
]

// ── the fired inbox ───────────────────────────────────────────────────────────────────────────────────────────
/** Fires (any order) → groups by symbol, the group with the newest fire first; fires newest first inside. */
export function groupFires(fires: readonly AlertFire[]): FireGroup[] {
  const by = new Map<string, FireGroup>()
  for (const f of fires) {
    const sym = f.symbol || '—'
    const g = by.get(sym) ?? { symbol: sym, count: 0, last_at: f.at, fires: [] }
    g.count++
    g.fires.push(f)
    if (String(f.at) > String(g.last_at)) g.last_at = f.at
    by.set(sym, g)
  }
  const out = [...by.values()]
  for (const g of out) g.fires.sort((a, b) => (String(a.at) < String(b.at) ? 1 : String(a.at) > String(b.at) ? -1 : b.seq - a.seq))
  return out.sort((a, b) => (String(a.last_at) < String(b.last_at) ? 1 : String(a.last_at) > String(b.last_at) ? -1 : a.symbol.localeCompare(b.symbol)))
}

/** The rules table's state words (never green/red: a rule holding is not good or bad news). */
export function ruleStateText(r: Pick<AlertRule, 'status' | 'snooze_until' | 'state'>): string {
  if (r.status === 'snoozed') return `snoozed to ${String(r.snooze_until ?? '').slice(11, 16) || '—'}`
  if (r.status === 'paused') return 'paused'
  if (r.status === 'fired') return 'fired (one-shot)'
  if (r.state?.last_error) return 'no reading'
  return 'watching'
}

/** "18.2 %", "₹3,212.40", "+₹14,975 cr" (the server's units). */
export function fmtAlertValue(v: number | string | null | undefined, unit: string): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'string') return v
  const g = (x: number, d: number) => Math.abs(x).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d })
  const neg = v < 0 ? '−' : ''
  if (unit === '₹') return `${neg}₹${g(v, 2)}`
  if (unit === '%' || unit === '% a.') return `${neg}${g(v, 2)} %`
  if (unit === 'vol pts') return `${neg}${g(v, 2)} vol pts`
  if (unit === 'pctile') return `${neg}${g(v, 1)}`
  if (unit === 'count' || unit === 'flag' || unit === 'strike') return `${neg}${g(v, 0)}`
  if (unit === 'contracts') return `${neg}${g(v, Number.isInteger(v) ? 0 : 1)} contracts`
  if (unit === 'pp') return `${v > 0 ? '+' : neg}${g(v, 1)} pp`
  if (unit === '₹ cr') return `${v > 0 ? '+' : neg}₹${g(v, 0)} cr`
  if (unit === 'days') return `${neg}${g(v, 0)} day${Math.abs(v) === 1 ? '' : 's'}`
  return `${neg}${g(v, 2)}`
}

// ── the create-alert hand-off (lib/alerts.ts draftAlert → ALRT) ─────────────────────────────────────────────
export const ALERT_DRAFT_KEY = 'suryadhana.alerts.draft.v1'
export const ALERT_DRAFT_EVENT = 'suryadhana:alert-draft'

/** A stored hand-off → a draft (null when malformed: a corrupt value never crashes ALRT). */
export function parseDraft(raw: string | null | undefined): AlertRuleDraft | null {
  if (!raw) return null
  try {
    const o = JSON.parse(raw) as Partial<AlertRuleDraft> | null
    if (!o || typeof o.series !== 'string' || !o.series || !OPS.includes(o.op as AlertOp)) return null
    const n = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null)
    return {
      series: o.series.slice(0, 120), op: o.op as AlertOp, value: n(o.value), window: n(o.window), cooldown_min: n(o.cooldown_min),
      repeat: o.repeat === 'once' ? 'once' : 'repeat', channel: o.channel === 'mac' || o.channel === 'telegram' ? o.channel : 'both',
      note: typeof o.note === 'string' ? o.note.slice(0, 200) : null,
    }
  } catch {
    return null
  }
}

// ── inbox hints (review m084 / m085): a figure older than its note, a breadth line without its universe ────────
/**
 * NSE holidays the inbox may count sessions with: `days` = holiday dates (ISO), known for dates on or after `from`
 * (ALRT reads them from ui-api's eco calendar, NSE's holiday master). Outside that span, or with none, the hint counts
 * weekdays and says that holidays are not counted.
 */
export interface HolidayCover { days: ReadonlySet<string>; from: string }

/** Weekdays strictly after `a` and strictly before `b`; with `cover` spanning them, NSE sessions (holidays dropped). */
export function daysBetween(a: string, b: string, cover?: HolidayCover | null): { n: number; sessions: boolean } {
  const d0 = Date.parse(`${a}T00:00:00Z`), d1 = Date.parse(`${b}T00:00:00Z`)
  const sessions = !!cover && a >= cover.from
  if (!Number.isFinite(d0) || !Number.isFinite(d1) || d1 <= d0) return { n: 0, sessions }
  let n = 0
  for (let t = d0 + 86_400_000; t < d1; t += 86_400_000) {
    const day = new Date(t)
    const wd = day.getUTCDay()
    if (wd === 0 || wd === 6) continue
    if (sessions && cover!.days.has(day.toISOString().slice(0, 10))) continue
    n++
  }
  return { n, sessions }
}

const FII_DATE = /\bFII [+\-−]?[\d,.]+ cr \/ DII [+\-−]?[\d,.]+ cr \((\d{4}-\d{2}-\d{2})\)/
const WRAP_BREADTH = /\bbreadth (\d[\d,]*)\/(\d[\d,]*)\b/
const toInt = (s: string) => Number(s.replace(/,/g, ''))

/**
 * The dim hints the inbox shows under a note: the FII/DII figure in a morning note dated before the previous session
 * (m084: the 30 Oct note quoted 27 Oct's numbers), counted in NSE sessions when the holiday master covers the span, else
 * in weekdays with "holidays not counted"; and the wrap's breadth, which counts the market monitor's liquid NSE universe
 * while the closing note counts NIFTY 500 (m085: 239 / 1,148 beside 120 / 379), with the count the note itself carries.
 */
export function noteHints(kind: string, at: string, body: string, cover?: HolidayCover | null): string[] {
  const out: string[] = []
  const day = String(at || '').slice(0, 10)
  const m = FII_DATE.exec(body || '')
  if (m && ISO_DAY.test(day) && !/older than the previous session/.test(body || '')) {   // the controller now says it itself
    const { n, sessions } = daysBetween(m[1], day, cover)
    if (n >= 1) {
      out.push(sessions
        ? `FII / DII here are from ${m[1]}: ${n} NSE session${n > 1 ? 's' : ''} older than the previous session (NSE publishes them the evening after)`
        : `FII / DII here are from ${m[1]}: ${n} weekday${n > 1 ? 's' : ''} older than the previous session, NSE holidays not counted (NSE publishes them the evening after)`)
    }
  }
  const b = WRAP_BREADTH.exec(body || '')
  if (kind === 'wrap' && b && !/NIFTY 500 breadth|liquid NSE/i.test(body || '')) {
    const counted = toInt(b[1]) + toInt(b[2])
    out.push(`breadth here counts advancing / declining stocks in the market monitor's liquid NSE universe (${counted.toLocaleString('en-IN')} counted in this note); CLOSE notes count NIFTY 500`)
  }
  return out
}

// ── the GO hand-off `ALRT TCS >3200` (lib/goAliases.ts parseAlertPrefill → ALRT) ─────────────────────────────────
/** Index names the price form cannot hold (no NSE equity behind them): GO fills the typed builder for these. */
export const INDEX_NAMES: ReadonlySet<string> = new Set(['NIFTY', 'BANKNIFTY', 'INDIAVIX', 'NIFTYIT', 'FINNIFTY', 'MIDCPNIFTY', 'NIFTYNXT50', 'SENSEX', 'BANKEX'])

export type PrefillTarget =
  | { target: 'price'; sym: string; above: string; below: string; move: string }
  | { target: 'rule'; draft: AlertRuleDraft }

/**
 * A parsed GO pre-fill ({symbol, op, level}) → what ALRT fills: the one-shot price form for a stock (the GO hint's "alert
 * form"), the typed builder (`price:NIFTY above 25000`, one-shot) for an index. ALRT only FILLS; the owner saves.
 */
export function prefillTarget(p: { symbol: string; op: 'above' | 'below'; level: number } | null | undefined): PrefillTarget | null {
  if (!p || !SYMBOL_RE.test(String(p.symbol || '').toUpperCase()) || !(p.level > 0) || (p.op !== 'above' && p.op !== 'below')) return null
  const sym = p.symbol.toUpperCase().replace(/\.NS$/, '')
  if (INDEX_NAMES.has(sym)) return { target: 'rule', draft: { series: `price:${sym}`, op: p.op, value: p.level, repeat: 'once', channel: 'both' } }
  return { target: 'price', sym, above: p.op === 'above' ? String(p.level) : '', below: p.op === 'below' ? String(p.level) : '', move: '' }
}

/**
 * The price levels to draw on a chart of `symbol` (CHRT's dashed ALERT lines, PLAN 2.3): every active / snoozed price
 * rule and price alert on it with a level op (above, below, cross_up, cross_down), unique, ascending.
 */
export function alertLevelsFor(rules: readonly Pick<AlertRule, 'series' | 'op' | 'value' | 'status'>[], symbol: string): number[] {
  const want = `price:${String(symbol || '').toUpperCase().replace(/\.NS$/, '')}`
  const out = new Set<number>()
  for (const r of rules) {
    if (r.series !== want || (r.status !== 'active' && r.status !== 'snoozed')) continue
    if (!['above', 'below', 'cross_up', 'cross_down'].includes(r.op)) continue
    if (typeof r.value === 'number' && Number.isFinite(r.value) && r.value > 0) out.add(r.value)
  }
  return [...out].sort((a, b) => a - b)
}
