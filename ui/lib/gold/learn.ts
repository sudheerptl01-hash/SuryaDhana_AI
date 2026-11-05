/**
 * LEARN layer helpers for the GOLD page (reports/gold_program/PLAN.md §e): glossary index and search, the tooltip
 * lookup by payload field, the curriculum parser (CURRICULUM.md → parts → sections), the Part 9 reading routines with
 * their deep links, the "what is not free" list, the Bloomberg function map and the Part 8 → panel-id rename map.
 *
 * Pure module: no React, no DOM, no imports. The JSON assets (`./tooltips.json`, `./glossary.json`) are imported by
 * the components and passed in, so this file runs unchanged under plain node in
 * `ui/components/__tests__/gold_views.check.ts` (type stripping, no deps).
 */

/** `aliases` (G-EDU, wave 1c): the page's own shorthands ("MM" → managed money, "OI" → open interest, "FND" → first notice day). */
export interface GlossaryEntry { term: string; short: string; long?: string; see_also?: string[]; aliases?: string[] }

/** Lower-cased term → entry (also indexes the aliases and a few spelling variants so dotted terms resolve). */
export function indexGlossary(terms: readonly GlossaryEntry[]): Map<string, GlossaryEntry> {
  const m = new Map<string, GlossaryEntry>()
  for (const t of terms) {
    m.set(t.term.toLowerCase(), t)
    const bare = t.term.toLowerCase().replace(/\s*\(.*\)\s*$/, '')
    if (bare && !m.has(bare)) m.set(bare, t)
  }
  for (const t of terms) for (const a of t.aliases ?? []) { const k = a.trim().toLowerCase(); if (k && !m.has(k)) m.set(k, t) }
  return m
}

/**
 * The "start here" dozen (C-BEGINNER-10): pinned above the alphabet while the search box is empty, in reading order —
 * the units, the two prices, the two venues, then the positioning words and the two prices-of-money. Every name must be
 * a glossary term (the node check asserts it).
 */
export const START_HERE: readonly string[] = ['troy ounce', 'spot', 'futures', 'COMEX', 'MCX', 'open interest', 'COT', 'managed money', 'net position', 'basis', 'roll', 'real yield']
export function startHereEntries(index: Map<string, GlossaryEntry>): GlossaryEntry[] {
  return START_HERE.map(t => lookupTerm(index, t)).filter((e): e is GlossaryEntry => !!e)
}

/** The long line prints only when it says more than the short one (C-BEGINNER-17: 50 entries carry long === short). */
export function longIfDifferent(e: GlossaryEntry): string | null {
  const l = (e.long ?? '').trim()
  return l && l !== e.short.trim() ? l : null
}

export function lookupTerm(index: Map<string, GlossaryEntry>, term: string): GlossaryEntry | undefined {
  const k = term.trim().toLowerCase()
  return index.get(k) ?? index.get(k.replace(/\s*\(.*\)\s*$/, ''))
}

/** Cross-reference check: every `see_also` must name an existing term. Returns the dangling pairs. */
export function danglingSeeAlso(terms: readonly GlossaryEntry[]): [string, string][] {
  const have = new Set(terms.map(t => t.term))
  const out: [string, string][] = []
  for (const t of terms) for (const s of t.see_also ?? []) if (!have.has(s)) out.push([t.term, s])
  return out
}

/** Ranked search: exact term → exact alias → term / alias starts with → term contains → short contains → long contains. Empty query = alphabetical. */
export function searchGlossary(terms: readonly GlossaryEntry[], q: string, limit = 40): GlossaryEntry[] {
  const needle = q.trim().toLowerCase()
  const sorted = [...terms].sort((a, b) => a.term.localeCompare(b.term, 'en', { sensitivity: 'base' }))
  if (!needle) return sorted.slice(0, limit)
  const rank = (t: GlossaryEntry): number => {
    const term = t.term.toLowerCase()
    const aliases = (t.aliases ?? []).map(a => a.toLowerCase())
    if (term === needle) return 0
    if (aliases.includes(needle)) return 1
    if (term.startsWith(needle) || aliases.some(a => a.startsWith(needle))) return 2
    if (term.includes(needle)) return 3
    if (t.short.toLowerCase().includes(needle)) return 4
    if ((t.long ?? '').toLowerCase().includes(needle)) return 5
    return 9
  }
  return sorted.map(t => [rank(t), t] as const).filter(([r]) => r < 9).sort((a, b) => a[0] - b[0]).slice(0, limit).map(([, t]) => t)
}

/** Tooltip for a payload field: the server map first, the bundled JSON as the fallback; undefined when neither has it. */
export function tipFor(server: Record<string, string> | null | undefined, bundled: Record<string, string>, key: string): string | undefined {
  return server?.[key] ?? bundled[key]
}

// ── curriculum ──────────────────────────────────────────────────────────────────────────────────

export interface CurriculumSection { id: string; title: string; body: string }
export interface CurriculumPart { id: string; title: string; intro: string; sections: CurriculumSection[]; kind: 'part' | 'appendix' | 'front' }

const slug = (s: string): string => s.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 60)

/**
 * Split CURRICULUM.md into parts (`# PART n — …`, `# Appendix X — …`, and the front matter before the first part,
 * which carries "§0 the health check") and their `## n.m` sections. Code fences are respected (a `#` inside a fence
 * is not a heading). The document title line is dropped.
 */
export function parseCurriculum(md: string): CurriculumPart[] {
  const lines = md.replace(/\r\n/g, '\n').split('\n')
  const parts: CurriculumPart[] = []
  let part: CurriculumPart | null = null
  let section: CurriculumSection | null = null
  let fence = false
  let titleSeen = false
  const push = (line: string) => {
    if (section) section.body += line + '\n'
    else if (part) part.intro += line + '\n'
  }
  for (const line of lines) {
    if (line.startsWith('```')) { fence = !fence; push(line); continue }
    if (!fence && /^#\s+/.test(line)) {
      const title = line.replace(/^#\s+/, '').trim()
      if (!titleSeen) { titleSeen = true; part = { id: 'front', title: 'Before anything else', intro: '', sections: [], kind: 'front' }; parts.push(part); section = null; continue }
      const kind: CurriculumPart['kind'] = /^appendix/i.test(title) ? 'appendix' : 'part'
      part = { id: slug(title.split('—')[0]), title, intro: '', sections: [], kind }
      parts.push(part); section = null; continue
    }
    if (!fence && /^##\s+/.test(line) && part) {
      const title = line.replace(/^##\s+/, '').trim()
      section = { id: slug(title), title, body: '' }
      part.sections.push(section); continue
    }
    push(line)
  }
  return parts.filter(p => p.intro.trim() || p.sections.length)
}

/** The '[B]' / '[P]' / '[APP]' micro-copy markers: which layer a paragraph belongs to. */
export function paragraphLayer(text: string): 'B' | 'P' | 'APP' | null {
  const m = /^\*\*\[(B|P|APP)\]\*\*/.exec(text.trim())
  return m ? (m[1] as 'B' | 'P' | 'APP') : null
}

/** A paragraph that is a pipe table or a fenced code block — pro material by construction (C-BEGINNER-9). */
export function isTableOrFence(par: string): boolean {
  const t = par.trim()
  return t.startsWith('```') || t.startsWith('~~~') || /^\|.*\|\s*$/m.test(t.split('\n')[0] ?? '')
}

/**
 * "only [B] copy": keep the `**[B]**` paragraphs, the `[APP]` notes and the headings; drop `**[P]**`, every table and
 * code fence, and the unmarked paragraphs (the formulas, regime tables and CFTC anatomy a beginner was never meant to
 * wade through — C-BEGINNER-9; B5 marks the pro paragraphs, this filter hides whatever is left unmarked). A section
 * with nothing left says so. "only [P] copy" drops the `**[B]**` paragraphs and keeps everything else.
 * Paragraphs are blank-line separated; code fences are left whole.
 */
export const NO_BEGINNER_COPY = '_(no beginner copy in this section yet — switch to [P] or turn the filter off)_'
export function filterLayerParagraphs(body: string, layer: 'B' | 'P'): string {
  const pars = body.split(/\n{2,}/)
  if (layer === 'P') return pars.filter(par => paragraphLayer(par) !== 'B').join('\n\n')
  const kept = pars.filter(par => {
    const t = par.trim()
    if (!t) return false
    if (/^#{1,6}\s/.test(t)) return true
    if (isTableOrFence(t)) return false
    const l = paragraphLayer(t)
    return l === 'B' || l === 'APP'
  })
  const hasCopy = kept.some(par => paragraphLayer(par) === 'B' || paragraphLayer(par) === 'APP')
  return (hasCopy ? kept : [...kept, NO_BEGINNER_COPY]).join('\n\n')
}

// ── reading routines (CURRICULUM Part 9, structured with deep links) ─────────────────────────────

export type RoutineTarget = 'health' | 'daily' | 'weekly' | 'monthly' | 'positioning' | 'physical' | 'macro' | 'contracts' | 'learn'
export interface RoutineStep { text: string; sub: RoutineTarget; panel?: string; panels?: string[] }
export type RoutineId = 'daily' | 'weekly' | 'monthly'
export interface Routine { id: RoutineId; title: string; when: string; steps: RoutineStep[]; evening?: string }

/** PLAN panel-id prefix → the sub-view that renders it (Appendix B). */
const PREFIX_SUB: Record<string, RoutineTarget> = { h: 'health', d: 'daily', w: 'weekly', m: 'monthly', p: 'positioning', ph: 'physical', mc: 'macro', c: 'contracts' }
const PANEL_ID_RE = /`((?:h|d|w|m|p|ph|mc|c)\.[a-z0-9]+(?:\.[a-z0-9]+)*)`/g

/**
 * Every PLAN panel id → a title a novice can read (C-BEGINNER-8), with the sub-view in brackets. The routines print these
 * in place of the ids (the id stays in the chip's `title=`); the node check asserts the map covers tooltips.json's panel
 * list exactly.
 */
export const PANEL_TITLES: Readonly<Record<string, string>> = {
  'h.verdict': 'the health verdict (HEALTH)', 'h.gauges': 'the eight health gauges (HEALTH)', 'h.open': "today's open: fair value vs yesterday's settlement (HEALTH)",
  'h.moved': 'what moved since the close — COMEX part vs rupee part (HEALTH)', 'h.headlines': 'the headlines (HEALTH)', 'h.events': 'events this week (HEALTH)',
  'h.accuracy': 'the open-model accuracy log (HEALTH)', 'h.brief': 'the automated brief (HEALTH)',
  'd.24h': 'the 24-hour COMEX chart (DAILY)', 'd.3day': 'the 3-day chart (DAILY)', 'd.tape': 'the session tape (DAILY)', 'd.quadrant': "yesterday's OI × price read (DAILY)", 'd.sge': 'the Shanghai intraday line (DAILY)',
  'w.candles': 'the weekly candles (WEEKLY)', 'w.grid': "the week's grid (WEEKLY)", 'w.table': 'the Mon–Fri table with CSV (WEEKLY)', 'w.whodid': 'who did what this week (WEEKLY)',
  'm.candles': 'the monthly candles (MONTHLY)', 'm.ladder': 'the return ladder (MONTHLY)', 'm.season': 'seasonality (MONTHLY)', 'm.official': 'central-bank net purchases (MONTHLY)',
  'm.physical': 'monthly physical flows (MONTHLY)', 'm.balance': 'the WGC balance sheet (MONTHLY)', 'm.liquidity': 'liquidity and risk percentiles (MONTHLY)',
  'p.hero': 'managed money this week (POSITIONING)', 'p.whois': 'who is long, who is short (POSITIONING)', 'p.history': 'positioning history (POSITIONING)', 'p.crowd': 'crowdedness (POSITIONING)',
  'p.decomp': 'the rally / decline decomposition (POSITIONING)', 'p.daily.comex': 'COMEX open interest by product (POSITIONING)', 'p.daily.mcx': 'MCX open interest by expiry (POSITIONING)',
  'p.mcx.category': 'who holds MCX gold (POSITIONING)', 'p.asia': 'Shanghai positioning (POSITIONING)', 'p.drawer': 'the COT details drawer (POSITIONING)',
  'ph.ladder': 'the India price stack (PHYSICAL)', 'ph.india': 'India premium history (PHYSICAL)', 'ph.shanghai': 'the Shanghai premium (PHYSICAL)', 'ph.etf': 'ETF holdings and flows (PHYSICAL)',
  'ph.official': 'the official sector (PHYSICAL)', 'ph.otc': 'the OTC window (PHYSICAL)', 'ph.comex.stocks': 'the COMEX warehouse-stocks link (PHYSICAL)', 'ph.links': 'linked sources (PHYSICAL)',
  'mc.drivers': 'the driver strip (MACRO)', 'mc.kgx': 'gold or the dollar? (MACRO)', 'mc.ccy': 'gold in six currencies (MACRO)', 'mc.fed': 'the Fed path (MACRO)', 'mc.calendar': 'the US calendar in IST (MACRO)',
  'mc.move': 'the expected move per lot (MACRO)', 'mc.health': 'driver health (MACRO)', 'mc.context': 'context ratios (MACRO)',
  'c.selector': 'the contract selector and specs (CONTRACTS)', 'c.spec': 'the matched COMEX contract card (CONTRACTS)', 'c.comex': 'the COMEX term structure (CONTRACTS)', 'c.mcx': 'the MCX chain (CONTRACTS)',
  'c.roll': 'the roll calendar (CONTRACTS)', 'c.links': 'contract links (CONTRACTS)',
}
export function panelTitle(id: string): string { return PANEL_TITLES[id] ?? id }
/** The title without its "(VIEW)" suffix — for a routine line that already names the view next to the id ("(`h.verdict`, HEALTH)"). */
export function shortPanelTitle(id: string): string { return panelTitle(id).replace(/\s*\((HEALTH|DAILY|WEEKLY|MONTHLY|POSITIONING|PHYSICAL|MACRO|CONTRACTS)\)$/, '') }

const PANEL_ID_BARE_RE = /\b((?:h|d|w|m|p|ph|mc|c)\.[a-z0-9]+(?:\.[a-z0-9]+)*)\b/g
export type StepPart = { kind: 'text'; text: string } | { kind: 'panel'; id: string; title: string }
/** A routine step's text with every panel id replaced by its title (the id travels in `StepPart.id` for the chip's title=). */
export function describeStep(text: string): StepPart[] {
  const out: StepPart[] = []
  let last = 0
  for (const m of text.matchAll(PANEL_ID_BARE_RE)) {
    const id = m[1]
    if (!(id in PANEL_TITLES)) continue
    if (m.index! > last) out.push({ kind: 'text', text: text.slice(last, m.index) })
    out.push({ kind: 'panel', id, title: panelTitle(id) })
    last = m.index! + id.length
  }
  if (last < text.length) out.push({ kind: 'text', text: text.slice(last) })
  return out
}

/** The sub-view a PLAN panel id lives on ('ph.etf' → 'physical'); null for anything that is not a panel id. */
export function subForPanel(panelId: string): RoutineTarget | null {
  const prefix = panelId.split('.')[0]
  return PREFIX_SUB[prefix] ?? null
}

/**
 * CURRICULUM.md Part 9 → the three routines, live from the document (the Part 9 text names the panel it points at in
 * backticks: "2. `h.open`: fair vs settlement …"). A step's deep link is the first panel id on the line; the text keeps
 * the ids without their backticks. Returns [] when the document has no Part 9 (the caller falls back to ROUTINES).
 */
export function parseRoutines(md: string): Routine[] {
  const start = md.indexOf('# PART 9')
  if (start < 0) return []
  const rest = md.slice(start + 1)
  const endRel = rest.search(/\n# /)
  const block = endRel < 0 ? rest : rest.slice(0, endRel)
  const lines = block.replace(/\r\n/g, '\n').split('\n')
  const out: Routine[] = []
  let cur: Routine | null = null
  let step: RoutineStep | null = null
  const finish = () => { if (cur && step) { cur.steps.push(step); step = null } }
  for (const raw of lines) {
    const head = /^\*\*(Daily|Weekly|Monthly)\s*\(([^)]*)\)\*\*/.exec(raw.trim())
    if (head) {
      finish()
      cur = { id: head[1].toLowerCase() as RoutineId, title: head[1], when: head[2].trim(), steps: [] }
      out.push(cur)
      continue
    }
    if (!cur) continue
    const num = /^(\d+)\.\s+(.*)$/.exec(raw)
    if (num) {
      finish()
      const panels = [...num[2].matchAll(PANEL_ID_RE)].map(m => m[1])
      step = { text: num[2].replace(/`/g, ''), sub: (panels[0] && subForPanel(panels[0])) || 'health', panel: panels[0], panels }
      continue
    }
    if (/^Evening\s*\(/.test(raw.trim())) { finish(); cur.evening = raw.trim().replace(/`/g, ''); continue }
    if (step && /^\s+\S/.test(raw)) {               // a continuation line of the current step
      const more = [...raw.matchAll(PANEL_ID_RE)].map(m => m[1])
      step.text += ` ${raw.trim().replace(/`/g, '')}`
      step.panels = [...(step.panels ?? []), ...more]
      if (!step.panel && more[0]) { step.panel = more[0]; step.sub = subForPanel(more[0]) ?? step.sub }
    }
  }
  finish()
  return out.filter(r => r.steps.length > 0)
}

/**
 * The fallback when the curriculum document is not available (research router down): a condensed mirror of Part 9 as
 * of 26 Oct 2026. The live document wins whenever it loads (`parseRoutines`). The node check asserts every panel id
 * here is a PLAN panel with a tooltip, not the wording.
 */
export const ROUTINES: readonly Routine[] = [
  {
    id: 'daily', title: 'Daily', when: '08:30–08:55 IST, 10 minutes',
    steps: [
      { text: 'Header strip: COMEX settle and live, USD/INR, real yield (yesterday\'s), MCX settle (by session), basis, MM net (last Tuesday) — then h.verdict and the eight h.gauges.', sub: 'health', panel: 'h.verdict', panels: ['h.verdict', 'h.gauges'] },
      { text: 'h.open: fair vs settlement, COMEX part vs rupee part (h.moved), the event-risk chip; decide OK/WAIT before 09:00, remembering the chip says the ₹300 limit is unproven.', sub: 'health', panel: 'h.open', panels: ['h.open', 'h.moved'] },
      { text: 'mc.drivers: what changed overnight and why (h.headlines); any scheduled event today (h.events, after-close flag).', sub: 'macro', panel: 'mc.drivers', panels: ['mc.drivers', 'h.headlines', 'h.events'] },
      { text: 'd.quadrant: yesterday\'s OI × price for COMEX (T+1) and MCX (07:35); roll/expiry caveat.', sub: 'daily', panel: 'd.quadrant', panels: ['d.quadrant'] },
      { text: 'mc.move: ATR ₹ and the 1σ day per lot (max lots at 1 % risk: the MCXG ticket); c.roll if a tender cut-off is within 7 days.', sub: 'macro', panel: 'mc.move', panels: ['mc.move', 'c.roll'] },
    ],
    evening: 'Evening (the last 30 min before the MCX close: 23:25–23:55 in US winter, 23:00–23:30 in summer): d.24h COMEX vs the MCX close; tomorrow\'s events; MCX settles on the VWAP of those 30 min.',
  },
  {
    id: 'weekly', title: 'Weekly', when: 'Saturday morning, 20 minutes',
    steps: [
      { text: 'p.hero / p.whois: nets, Δ by group in words, who closed what, the driver label; p.crowd as crowdedness only; p.drawer for the options line and trader counts; FND distance (c.roll) for the roll footprint.', sub: 'positioning', panel: 'p.hero', panels: ['p.hero', 'p.whois', 'p.crowd', 'p.drawer', 'c.roll'] },
      { text: 'ph.etf: GLD week on week; WGC weekly flows (Monday); w.table for the week\'s rows and the CSV.', sub: 'physical', panel: 'ph.etf', panels: ['ph.etf', 'w.table'] },
      { text: 'ph.otc: LBMA turnover (weekly), EFP prints; ph.comex.stocks link (browser) for the warehouse week.', sub: 'physical', panel: 'ph.otc', panels: ['ph.otc', 'ph.comex.stocks'] },
      { text: 'c.comex / c.mcx: carry vs SOFR, implied lease; the MCX–COMEX carry gap.', sub: 'contracts', panel: 'c.comex', panels: ['c.comex', 'c.mcx'] },
      { text: 'ph.india / ph.shanghai: premium and basis history; any CBIC tariff-value or duty notification (owner, dated).', sub: 'physical', panel: 'ph.india', panels: ['ph.india', 'ph.shanghai'] },
      { text: 'h.events / mc.calendar for next week: FOMC/CPI/NFP/RBI/Budget/MCX expiry/COMEX FND.', sub: 'health', panel: 'h.events', panels: ['h.events', 'mc.calendar'] },
    ],
  },
  {
    id: 'monthly', title: 'Monthly', when: 'first weekend',
    steps: [
      { text: 'm.official / ph.official: central banks (IMF ~25th, PBoC ~7th, RBI weekly).', sub: 'monthly', panel: 'm.official', panels: ['m.official', 'ph.official'] },
      { text: 'm.physical: London vaults; SGE withdrawals; India imports (PIB ~15th); Swiss exports; AMFI AUM in tonnes.', sub: 'monthly', panel: 'm.physical', panels: ['m.physical'] },
      { text: 'mc.health + m.ladder + m.season: regime check (§5.9) — real-yield link, central-bank pace, ETF trend, 3-year COT index as context, the seasonality caveat.', sub: 'macro', panel: 'mc.health', panels: ['mc.health', 'm.ladder', 'm.season'] },
      { text: 'h.accuracy: model vs naive over the month; the chase-limit decision at 20 rows.', sub: 'health', panel: 'h.accuracy', panels: ['h.accuracy'] },
      { text: 'c.selector: any margin change (dated NRML mirror); broker rate changes.', sub: 'contracts', panel: 'c.selector', panels: ['c.selector'] },
    ],
  },
]

// ── "what is not free and where to click" (PLAN §e item 4) ───────────────────────────────────────

export interface LinkOnly { name: string; url: string; why: string }
export const NOT_FREE: readonly LinkOnly[] = [
  { name: 'LBMA Gold Price (AM/PM auction tables)', url: 'https://www.lbma.org.uk/prices-and-data/precious-metal-prices', why: 'IBA licence; the fix is a time marker here, never a scraped number' },
  { name: 'LBMA Trade Data (daily, product level)', url: 'https://www.lbma.org.uk/prices-and-data/lbma-daily-trade-reporting-data', why: 'Nasdaq subscription; only the weekly headline is public' },
  { name: 'CME Group website (specs, warehouse XLS, bulletin, FedWatch)', url: 'https://www.cmegroup.com/markets/metals/precious/gold.html', why: 'blocks non-browser clients; terms forbid automated download; the FTP daily files are used instead' },
  { name: 'MCX website (bhavcopy, circulars, category-wise OI)', url: 'https://www.mcxindia.com/market-data/bhavcopy', why: 'blocks scripts (403); the ICICI security master carries the band and OI each morning' },
  { name: 'Kitco charts', url: 'https://www.kitco.com/charts/gold', why: 'personal, non-commercial viewing only; the DAILY chart is built from our own stored bars' },
  { name: 'Bloomberg Professional / LSEG Workspace', url: 'https://www.bloomberg.com/professional/', why: 'paid, no redistribution; the function map below says where the free equivalent lives here' },
  { name: 'Reuters India premium survey', url: 'https://www.reuters.com/markets/commodities/', why: 'weekly survey behind the paywall; our IBJA-vs-landed premium is the house line' },
  { name: 'CME FedWatch', url: 'https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html', why: 'browser only; the Fed-path panel uses the Atlanta Fed tracker' },
]

// ── Bloomberg function map (G-KITCO Appendix C; public guides, unverified on a terminal) ─────────

export interface BbgRow { fn: string; what: string; here: string; sub: RoutineTarget }
export const BBG_MAP: readonly BbgRow[] = [
  { fn: 'DES', what: 'contract description (size, tick, margin, delivery)', here: 'CONTRACTS › spec card and selector', sub: 'contracts' },
  { fn: 'GP / GIP / GPO', what: 'price graphs (daily, intraday, open interest)', here: 'DAILY 24-h chart · WEEKLY candles · POSITIONING OI tapes', sub: 'daily' },
  { fn: 'HP', what: 'history table', here: 'WEEKLY Mon–Fri table (CSV export)', sub: 'weekly' },
  { fn: 'CT / CTM', what: 'contract table with volume and OI; exchange contract search', here: 'CONTRACTS › MCX chain and COMEX term structure', sub: 'contracts' },
  { fn: 'CCRV / FWCV', what: 'forward curves, today vs a week ago', here: 'CONTRACTS › COMEX curve with the ghost curve', sub: 'contracts' },
  { fn: 'CFTC <GO> · tickers …MML/MMS/…N', what: 'Commitments of Traders by trader group', here: 'POSITIONING › who is long / who is short, history, drawer', sub: 'positioning' },
  { fn: 'ECO', what: 'economic releases with consensus', here: 'MACRO › US calendar in IST', sub: 'macro' },
  { fn: 'GLCO', what: 'global commodity prices', here: 'WEI commodities row (one line + hover) and the macro tape', sub: 'health' },
  { fn: 'XAU Curncy · GC1 Comdty · GCZ6 Comdty', what: 'spot, continuous front, dated contract', here: 'the four instruments named on every price: spot proxy · COMEX front GC1 · matched month · MCX', sub: 'health' },
  { fn: 'WIRP / FedWatch', what: 'implied policy path', here: 'MACRO › Fed path (Atlanta Fed tracker, ZQ)', sub: 'macro' },
  { fn: 'GOLDLNPM Index', what: 'LBMA PM benchmark', here: 'PHYSICAL › Shanghai premium reference leg (WGC-served, provisional)', sub: 'physical' },
]

// ── Part 8 → panel id rename map (PLAN Appendix B) ──────────────────────────────────────────────

export const PART8_RENAME: readonly [string, string][] = [
  ['8.1.1 verdict', 'h.open (verdict)'], ['8.1.2 key numbers', 'h.open'], ['8.1.3 gap build-up', 'h.open waterfall / h.moved'],
  ['8.1.4 inputs', 'h.open'], ['8.1.5 context table', 'mc.drivers'], ['8.1.6 headlines', 'h.headlines'],
  ['8.1.7 manual checks', 'ph.links + c.links'], ['8.1.8 accuracy log', 'h.accuracy'], ['8.1.9 session clock', 'MCXG (unchanged)'],
  ['8.1.10 quote', 'MCXG'], ['8.1.11 overlay', 'MCXG one-line + ph.ladder'], ['8.1.12 specs', 'c.selector'],
  ['8.1.13 ticket', 'MCXG ticket (+ sizing)'], ['8.1.14 WEI row', 'WEI card'], ['8.1.15 BRF panel', 'BRF line'],
  ['8.1.16 CMDT board', 'CMDT tile'], ['8.2.1 health strip', 'header strip + h.gauges'],
  ['8.2.2 COT', 'p.hero, p.whois, p.crowd, p.drawer'], ['8.2.3 daily OI × price', 'd.quadrant, p.daily.comex, p.daily.mcx'],
  ['8.2.4 warehouse', 'ph.comex.stocks'], ['8.2.5 ETF', 'ph.etf'], ['8.2.6 OTC window', 'ph.otc'],
  ['8.2.7 premium monitor', 'ph.ladder, ph.india, ph.shanghai'], ['8.2.8 drivers', 'mc.drivers, mc.move, mc.health'],
  ['8.2.9 central banks', 'ph.official, m.official'], ['8.2.10 term structure', 'c.comex, c.mcx'],
  ['8.2.11 chooser + calendar', 'c.selector, c.roll, h.events'], ['8.2.12 events calendar', 'h.events, mc.calendar (+ ECO)'],
  ['8.2.13 Kitco-style chart', 'd.24h, d.3day'], ['8.2.14 periodicity switch', 'the window param + WEEKLY / MONTHLY views'],
]

/** The stale-duty wordings G-EDU's validate_learn.py forbids: present in the document = the duty section still reasons from 6 %. */
export const STALE_DUTY_STRINGS: readonly string[] = [
  'in force since 24 Jul 2024', '6% from 24 Jul 2024 (cut from 15%)', 'at 6%   (BCD 5% + AIDC 1%', '6% since 24 Jul 2024 as of this document', 'duty-paid at 6%',
]
export function curriculumHasStaleDuty(md: string): boolean {
  return STALE_DUTY_STRINGS.some(s => md.includes(s))
}

export interface CurriculumCorrection {
  where: string; text: string
  /** show only when the loaded document still carries the defect (always when no predicate) */
  when?: (md: string) => boolean
  /** the layers the note is for (builder-speak such as the Part 8 panel-id note is [P] only — C-BEGINNER-23); absent = both */
  layers?: readonly ('B' | 'P')[]
}

/**
 * Corrections to the G-EDU text that the LEARN view prints above the curriculum (PLAN §e required additions), each
 * gated on the loaded document so a fixed section stops being "corrected": the duty lines only while the stale 6 %
 * wording is still there; the evidence-ledger line only while Appendix C is still the ledger.
 */
export const CURRICULUM_CORRECTIONS: readonly CurriculumCorrection[] = [
  { where: '§2.6 duty', when: curriculumHasStaleDuty, text: 'The curriculum reasons from a 6 % duty (24 Jul 2024). The duty in force is 15 % (BCD 10 % + AIDC 5 %) since 13 May 2026, Notification 16/2026-Customs — confirm at CBIC (owner action O-3). Every ladder on PHYSICAL prints the dated rate.' },
  { where: '§2.6 "18 % premium"', when: md => curriculumHasStaleDuty(md) || !/0\.995 × 1\.15 × 1\.031/.test(md), text: 'The old 18 % "implied premium" was 0.995 × 1.15 × 1.031 − 1: purity × the dated 15 % duty × the MCX basis vs duty-paid landed (+3.1 % that morning, §2.6); `implied_premium_pct` is a deprecated alias for one release.' },
  { where: 'Appendix C evidence ledger', when: md => /^# Appendix C — Evidence ledger/m.test(md) && !/SOURCES\.md`? §11/.test(md), text: 'Superseded by SOURCES.md §11 (the G-STUDY, G-MACRO, G-INDIA rows the badges rest on).' },
  { where: 'Part 8 panel names', layers: ['P'], text: 'Carry the PLAN panel ids; the map is in the "Where each panel went" section below.' },
]

/** The corrections that apply to a loaded document (all of them when the document is not loaded yet) for `layer`. */
export function activeCorrections(md: string | null | undefined, layer?: 'B' | 'P'): CurriculumCorrection[] {
  const forLayer = (c: CurriculumCorrection) => !layer || !c.layers || c.layers.includes(layer)
  if (!md) return CURRICULUM_CORRECTIONS.filter(forLayer)
  return CURRICULUM_CORRECTIONS.filter(c => (!c.when || c.when(md)) && forLayer(c))
}

/** Curriculum parts the LEARN view renders as its own panels (deep links, link tiles) instead of inside the accordion. */
export const PARTS_RENDERED_AS_PANELS = /^Appendix [EF]\b/i
