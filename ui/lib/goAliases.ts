/**
 * Bloomberg mnemonics and GO arguments for the GO bar (C1-trader-ux-09 remainder, R-UI-SHELL-07 / CT-09; page review
 * 5 Nov M37: `TCS OMON 27NOV`, `NIFTY OSTR IC`, `ALRT TCS >3200`, `TCS VS INFY`, `GOLD COT`). Pure, no DOM, no imports
 * (unit-tested by `node ui/components/desktop/__tests__/desktop.check.ts`); components/CommandBar.tsx turns the
 * targets into GO items and ranks them, with exact page codes, above every ticker match.
 *
 * Without these, Bloomberg muscle memory landed on unrelated tickers: GP opened GPIL, TOP opened SHOPERSTOP, MOST a
 * ticker called MOST, and BACK the Backtest lab (now that real Back exists).
 */

export type AliasTarget =
  | { kind: 'page'; id: string; sub?: string; view?: string }   // `sub`: a GOLD sub-view handed over through the URL (gold program PLAN a.1);
                                                                // `view`: another page's sub-view (`?sub=`), terminal_v2 PLAN 1.1 / 1.4
  | { kind: 'news' }
  | { kind: 'back' }
  | { kind: 'omon'; sym: string }

/** Single-word mnemonic → what it opens, in rank order. Page ids are app/page.tsx COMMAND_PAGES ids. */
export const GO_ALIASES: Readonly<Record<string, readonly AliasTarget[]>> = Object.freeze({
  GP: [{ kind: 'page', id: 'charts' }],          // graph price
  GIP: [{ kind: 'page', id: 'charts' }],         // graph intraday price
  TOP: [{ kind: 'news' }],                       // top news
  N: [{ kind: 'news' }],
  MOST: [{ kind: 'page', id: 'movers' }],        // most active
  BACK: [{ kind: 'back' }],                      // history back (⌘[ in the app)
  BRIEF: [{ kind: 'page', id: 'brief' }],
  NIFTY: [{ kind: 'omon', sym: 'NIFTY' }, { kind: 'page', id: 'memb' }],
  BANKNIFTY: [{ kind: 'omon', sym: 'BANKNIFTY' }, { kind: 'page', id: 'memb' }],
  FINNIFTY: [{ kind: 'omon', sym: 'FINNIFTY' }],
  // gold program (reports/gold_program/PLAN.md a.1): the spot code and the COMEX root open the GOLD page; the four
  // sub-view mnemonics open it on PHYSICAL / MACRO / LEARN / POSITIONING (CommandBar hands `sub` over in the URL)
  XAU: [{ kind: 'page', id: 'gold' }],
  GC: [{ kind: 'page', id: 'gold' }],
  GPHY: [{ kind: 'page', id: 'gold', sub: 'physical' }],
  GMAC: [{ kind: 'page', id: 'gold', sub: 'macro' }],
  LRN: [{ kind: 'page', id: 'gold', sub: 'learn' }],
  COT: [{ kind: 'page', id: 'gold', sub: 'positioning' }],
  // terminal v2 (reports/terminal_v2/PLAN.md 1.1 / 1.2 / 1.4; O-T14 default: sub-views, no new page): VOL opens
  // DERV on its VOL sub-view, DRVR / IMAP / CONTRIB open MEMB ("Index members & drivers"), DATA opens SYS on DATA
  VOL: [{ kind: 'page', id: 'derivatives', view: 'vol' }],
  IVR: [{ kind: 'page', id: 'derivatives', view: 'vol' }],     // IV rank / percentile live on the VOL screener (the review's GO IVR → nothing)
  SKEW: [{ kind: 'page', id: 'derivatives', view: 'vol' }],
  XPRY: [{ kind: 'page', id: 'derivatives', view: 'xpry' }],   // PLAN 2.4: the expiry-day view (DERV › XPRY)
  DRVR: [{ kind: 'page', id: 'memb' }],
  IMAP: [{ kind: 'page', id: 'memb' }],
  CONTRIB: [{ kind: 'page', id: 'memb' }],
  DATA: [{ kind: 'page', id: 'system', view: 'data' }],
  // R2-ASK (RATING §7 R9-R1): the cited read-only analyst — RSCH › ASK (`?sub=ask`, like VOL / DATA)
  ASK: [{ kind: 'page', id: 'research', view: 'ask' }],
})

// ── GO arguments (page review 5 Nov, M37): `TCS OMON 27NOV` · `NIFTY OSTR IC` · `ALRT TCS >3200` · `TCS VS INFY` ·
// `GOLD COT`. Pure: CommandBar turns a parsed command into one GO item and the hand-offs below. ─────────────────────

/** Pages that take an underlying after (or before) their code: `TCS OMON`, `OMON TCS`, `BANKNIFTY DERV`. */
export const SYMBOL_PAGES: Readonly<Record<string, string>> = Object.freeze({
  OMON: 'options', OSTR: 'ostrategy', DERV: 'derivatives', CHRT: 'charts', DEAL: 'deals', COMP: 'compare', VOL: 'derivatives',
})

/** OSTR template codes → the builder's template names (components/StrategyBuilder.tsx TEMPLATES). */
export const OSTR_TEMPLATES: Readonly<Record<string, string>> = Object.freeze({
  IC: 'Iron condor', CONDOR: 'Iron condor', STRD: 'Straddle', STRADDLE: 'Straddle', STRG: 'Strangle', STRANGLE: 'Strangle',
  BCS: 'Bull call spread', BPS: 'Bear put spread', LC: 'Long call', CALL: 'Long call', LP: 'Long put', PUT: 'Long put',
  CC: 'Covered call (fut+CE)',
})

/** GOLD sub-view words after `GOLD` (the nine sub-views plus their mnemonics). */
export const GOLD_SUB_WORDS: Readonly<Record<string, string>> = Object.freeze({
  HEALTH: 'health', HLTH: 'health', DAILY: 'daily', WEEKLY: 'weekly', MONTHLY: 'monthly', POSITIONING: 'positioning', COT: 'positioning',
  POS: 'positioning', PHYSICAL: 'physical', PHY: 'physical', GPHY: 'physical', MACRO: 'macro', MAC: 'macro', GMAC: 'macro',
  CONTRACTS: 'contracts', CTR: 'contracts', LEARN: 'learn', LRN: 'learn',
})

/** LOCAL one-shot hand-offs GO writes before it opens the page (lib/prefs/keys.ts LOCAL_KEYS; read + removed there). */
export const OSTR_TEMPLATE_KEY = 'suryadhana.ostr.template.v1'
export const OSTR_TEMPLATE_EVENT = 'suryadhana:ostr-template'
export const ALRT_PREFILL_KEY = 'suryadhana.alrt.prefill.v1'
export const ALRT_PREFILL_EVENT = 'suryadhana:alrt-prefill'
/** GO handed a sub-view to the page it opens (app/page.tsx keeps `?sub=` on that switch; a plain switch drops it). */
export const PAGE_HANDOFF_EVENT = 'suryadhana:page-handoff'
/** How long after a hand-off the page switch still counts as carrying it. */
export const HANDOFF_SUB_WINDOW_MS = 1500

/**
 * The search string for a page switch: a plain switch to ANOTHER page drops the previous page's `?sub=` (SYS › DATA's
 * `sub=data` used to ride along to OMON: `?tab=options&sub=data`); a switch right after a hand-off (GO VOL, a "VOL ›"
 * chip, GO GOLD COT) keeps it. `fromTab` = the page being left.
 */
export function stripStaleSub(search: string, fromTab: string, toTab: string, msSinceHandoff: number): string {
  if (fromTab === toTab || msSinceHandoff <= HANDOFF_SUB_WINDOW_MS) return search
  try {
    const p = new URLSearchParams(search)
    if (!p.has('sub')) return search
    p.delete('sub')
    const q = p.toString()
    return q ? `?${q}` : ''
  } catch { return search }
}

export type GoCommand =
  /** an underlying + a page (+ an expiry for OMON / OSTR / DERV): written to the active-symbol store */
  | { kind: 'symbolPage'; sym: string; page: string; code: string; expiry: string | null; view: string | null }
  | { kind: 'ostrTemplate'; sym: string; template: string; code: string; expiry: string | null }
  | { kind: 'alert'; sym: string; op: 'above' | 'below'; level: number }
  | { kind: 'compare'; syms: string[] }
  | { kind: 'goldSub'; sub: string }
  /** the shape of a command with an argument GO cannot read: shown as a hint, never run */
  | { kind: 'invalid'; reason: string }

const MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
const SYM_SHAPE = /^[A-Z][A-Z0-9&_-]{0,19}$/
const iso = (y: number, m: number, d: number) => `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`

/**
 * An expiry token → ISO day, or null: `27NOV` (the next 27 Nov on or after today), `27NOV26`, `27NOV2026`, `2026-11-27`.
 * `today` is the IST calendar day (YYYY-MM-DD). A day that does not exist (31NOV) is null, never rolled over.
 */
export function parseExpiryToken(tok: string, today: string): string | null {
  const t = tok.trim().toUpperCase()
  const ty = Number(today.slice(0, 4))
  let y: number, m: number, d: number
  const isoM = /^(\d{4})-(\d{2})-(\d{2})$/.exec(t)
  const dm = /^(\d{1,2})([A-Z]{3})(\d{2}|\d{4})?$/.exec(t)
  if (isoM) { y = Number(isoM[1]); m = Number(isoM[2]); d = Number(isoM[3]) }
  else if (dm) {
    m = MONTHS.indexOf(dm[2]) + 1
    if (m === 0) return null
    d = Number(dm[1])
    y = dm[3] ? (dm[3].length === 2 ? 2000 + Number(dm[3]) : Number(dm[3])) : ty
  } else return null
  if (!(m >= 1 && m <= 12 && d >= 1 && Number.isFinite(y))) return null
  const dt = new Date(Date.UTC(y, m - 1, d))
  if (dt.getUTCMonth() !== m - 1 || dt.getUTCDate() !== d) return null
  let out = iso(y, m, d)
  if (dm && !dm[3] && out < today) out = iso(y + 1, m, d)        // no year: the next one on or after today
  return out
}

function level(tok: string): number | null {
  const v = Number(tok.replace(/,/g, ''))
  return Number.isFinite(v) && v > 0 ? v : null
}

/** `>3200` · `> 3200` · `ABOVE 3200` · `<3100` · `BELOW 3100` (≥ / ≤ read as > / <) → {op, level}, or null. */
function parseLevel(toks: string[]): { op: 'above' | 'below'; level: number } | null {
  const s = toks.join(' ').replace(/\s+/g, ' ').trim()
  const m = /^(>=?|<=?|ABOVE|BELOW|≥|≤)\s*([\d,]+(?:\.\d+)?)$/.exec(s)
  if (!m) return null
  const lv = level(m[2])
  if (lv == null) return null
  return { op: /^(>|ABOVE|≥)/.test(m[1]) ? 'above' : 'below', level: lv }
}

/**
 * Parse a multi-word GO line into one command, or null (single words, a ticker + DES/FA/TV… and anything unknown keep
 * the existing ranking). `pageIds` maps page code → page id (COMMAND_PAGES) so a symbol page always exists.
 */
export function parseGoCommand(raw: string, today: string, pageIds: Readonly<Record<string, string>>): GoCommand | null {
  const toks = raw.trim().toUpperCase().split(/\s+/).filter(Boolean)
  if (toks.length < 2) return null
  const [a, b, ...rest] = toks
  // ALRT TCS >3200 · ALRT TCS > 3200 · TCS ALRT >3200 · ALRT TCS ABOVE 3200
  if ((a === 'ALRT' && SYM_SHAPE.test(b)) || (b === 'ALRT' && SYM_SHAPE.test(a))) {
    const sym = a === 'ALRT' ? b : a
    const lv = parseLevel(rest)
    if (sym === 'ALRT') return null
    return lv ? { kind: 'alert', sym, ...lv } : { kind: 'invalid', reason: `ALRT ${sym}: add a level, e.g. ALRT ${sym} >3200 or <3100` }
  }
  // GOLD COT · GOLD PHYSICAL
  if (a === 'GOLD' && toks.length === 2 && GOLD_SUB_WORDS[b]) return { kind: 'goldSub', sub: GOLD_SUB_WORDS[b] }
  // TCS VS INFY (VS HDFCBANK …): COMP, 2–8 names
  if (toks.length >= 3 && b === 'VS') {
    const syms: string[] = []
    for (let i = 0; i < toks.length; i++) {
      if (i % 2 === 1) { if (toks[i] !== 'VS') return null; continue }
      if (!SYM_SHAPE.test(toks[i])) return null
      if (!syms.includes(toks[i])) syms.push(toks[i])
    }
    return syms.length >= 2 ? { kind: 'compare', syms: syms.slice(0, 8) } : null
  }
  // TCS OMON 27NOV · OMON TCS 27NOV · NIFTY OSTR IC · OSTR NIFTY IC 27NOV · BANKNIFTY DERV · BANKNIFTY VOL
  const pageFirst = SYMBOL_PAGES[a] !== undefined && !SYMBOL_PAGES[b] && SYM_SHAPE.test(b)
  const symFirst = SYMBOL_PAGES[b] !== undefined && SYM_SHAPE.test(a) && !SYMBOL_PAGES[a]
  if (!pageFirst && !symFirst) return null
  const code = pageFirst ? a : b
  const sym = pageFirst ? b : a
  const page = pageIds[code] ?? SYMBOL_PAGES[code]
  if (!page || code === 'COMP') return code === 'COMP' && !rest.length ? { kind: 'compare', syms: [sym] } : null
  let expiry: string | null = null
  let template: string | null = null
  for (const t of rest) {
    const e = parseExpiryToken(t, today)
    if (e && !expiry) { expiry = e; continue }
    if (code === 'OSTR' && OSTR_TEMPLATES[t] && !template) { template = OSTR_TEMPLATES[t]; continue }
    return { kind: 'invalid', reason: code === 'OSTR'
      ? `${sym} OSTR: "${t}" is not an expiry (27NOV) or a template (IC STRD STRG BCS BPS LC LP CC)`
      : `${sym} ${code}: "${t}" is not an expiry (27NOV, 27NOV26 or 2026-11-27)` }
  }
  if (expiry && !['OMON', 'OSTR', 'DERV', 'VOL'].includes(code)) return { kind: 'invalid', reason: `${code} takes no expiry` }
  if (template) return { kind: 'ostrTemplate', sym, template, code, expiry }
  return { kind: 'symbolPage', sym, page, code, expiry, view: code === 'VOL' ? 'vol' : null }
}

/** How long a one-shot GO hand-off stays valid: a page opened later (another day, another window) never acts on it. */
export const HANDOFF_MAX_AGE_MS = 120_000

export interface AlertPrefill { symbol: string; op: 'above' | 'below'; level: number; at: string }
export interface OstrTemplateHandoff { template: string; symbol: string; expiry: string | null; at: string }

function fresh(at: unknown, nowMs: number): at is string {
  const t = typeof at === 'string' ? Date.parse(at) : NaN
  return Number.isFinite(t) && nowMs - t >= -5_000 && nowMs - t <= HANDOFF_MAX_AGE_MS
}

/**
 * ALRT's side of `ALRT TCS >3200`: the stored hand-off (ALRT_PREFILL_KEY) → a pre-fill for the form, or null when
 * malformed or stale. ALRT reads it on mount and on ALRT_PREFILL_EVENT, removes the key, and only FILLS the form: the
 * owner saves the alert there (GO never creates one).
 */
export function parseAlertPrefill(raw: string | null | undefined, nowMs: number): AlertPrefill | null {
  try {
    const o = raw ? JSON.parse(raw) as Partial<AlertPrefill> : null
    if (!o || typeof o.symbol !== 'string' || !SYM_SHAPE.test(o.symbol) || (o.op !== 'above' && o.op !== 'below')) return null
    if (typeof o.level !== 'number' || !Number.isFinite(o.level) || o.level <= 0 || !fresh(o.at, nowMs)) return null
    return { symbol: o.symbol, op: o.op, level: o.level, at: o.at }
  } catch { return null }
}

/** OSTR's side of `NIFTY OSTR IC`: the stored hand-off (OSTR_TEMPLATE_KEY) → {template, symbol, expiry}, or null. */
export function parseOstrTemplate(raw: string | null | undefined, nowMs: number): OstrTemplateHandoff | null {
  try {
    const o = raw ? JSON.parse(raw) as Partial<OstrTemplateHandoff> : null
    if (!o || typeof o.symbol !== 'string' || !SYM_SHAPE.test(o.symbol) || typeof o.template !== 'string') return null
    if (!Object.values(OSTR_TEMPLATES).includes(o.template) || !fresh(o.at, nowMs)) return null
    const expiry = typeof o.expiry === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(o.expiry) ? o.expiry : null
    return { template: o.template, symbol: o.symbol, expiry, at: o.at }
  } catch { return null }
}

/** The argument forms GO teaches (hint row + help card). */
export const GO_ARG_HINTS: readonly (readonly [string, string])[] = Object.freeze([
  ['TCS OMON 27NOV', 'option chain on that expiry'],
  ['NIFTY OSTR IC', 'strategy template: IC · STRD · STRG · BCS · BPS · LC · LP · CC'],
  ['ALRT TCS >3200', 'alert form, pre-filled (> above · < below)'],
  ['TCS VS INFY', 'compare (COMP)'],
  ['GOLD COT', 'a GOLD sub-view: HEALTH · DAILY · COT · PHYSICAL · MACRO · CONTRACTS · LEARN'],
  ['BANKNIFTY DERV', 'a page on that underlying: OMON · OSTR · DERV · VOL · CHRT · DEAL'],
])

/** Targets for a GO query: only a single word that is exactly a mnemonic (case-insensitive). */
export function aliasTargets(query: string): readonly AliasTarget[] {
  const q = query.trim().toUpperCase()
  if (!q || /\s/.test(q)) return []
  return Object.prototype.hasOwnProperty.call(GO_ALIASES, q) ? GO_ALIASES[q] : []
}

/**
 * True when Back stays inside the terminal: the current history entry was pushed by the terminal (app/page.tsx tags
 * every entry it pushes with {sd: 1, pushed: true}), so the entry behind it is a terminal screen too. The first
 * entry of a window (pushed: false) has nothing of ours behind it: Back from there would leave the terminal.
 */
export function canGoBack(state: unknown): boolean {
  if (!state || typeof state !== 'object') return false
  const s = state as { sd?: unknown; pushed?: unknown }
  return s.sd === 1 && s.pushed === true
}

/** Concatenate ranked groups, keeping the first item of each key (an alias and a scored page can be the same item). */
export function mergeRanked<T extends { key: string }>(groups: ReadonlyArray<ReadonlyArray<T>>): T[] {
  const seen = new Set<string>()
  const out: T[] = []
  for (const g of groups) {
    for (const it of g) {
      if (seen.has(it.key)) continue
      seen.add(it.key)
      out.push(it)
    }
  }
  return out
}

/**
 * GO's symbol list as the server sent it, made safe for the ranking code (R-UI-SHELL-04 / P15): rows without a
 * string ticker are dropped, and a missing or non-string company name (`n`) reads ''. One bad row used to throw
 * (`s.n.toUpperCase()` on a null name) inside the items memo and take GO down for the whole window.
 */
export function sanitizeSymbolRows<T extends { t?: unknown; n?: unknown }>(rows: unknown): Array<T & { t: string; n: string }> {
  if (!Array.isArray(rows)) return []
  const out: Array<T & { t: string; n: string }> = []
  for (const r of rows) {
    if (!r || typeof r !== 'object') continue
    const row = r as T
    if (typeof row.t !== 'string' || row.t === '') continue
    out.push({ ...row, t: row.t, n: typeof row.n === 'string' ? row.n : '' })
  }
  return out
}
