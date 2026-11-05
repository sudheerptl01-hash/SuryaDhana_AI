/**
 * Code + label of the 43 terminal pages for the desktop title strip and the native window title.
 *
 * Source of truth: `COMMAND_PAGES` in ui/app/page.tsx (PLAN §5). A Next.js page module may only export the
 * page itself, so the list cannot be imported from there; this is a checked copy. `desktop.check.ts` parses
 * page.tsx and fails on any drift (id, code or label), so a page added there without updating this file is
 * caught by the check, and at runtime an unknown id still renders (code from document.title, else the id).
 */

export interface PageMeta {
  readonly code: string
  readonly label: string
}

export const PAGE_META: Readonly<Record<string, PageMeta>> = Object.freeze({
  brief: { code: 'BRF', label: 'Morning brief' },
  watch: { code: 'WTCH', label: 'Watch monitor' },
  charts: { code: 'CHRT', label: 'Chart studio' },
  world: { code: 'WEI', label: 'World markets' },
  eco: { code: 'ECO', label: 'Economic calendar' },
  memb: { code: 'MEMB', label: 'Index members' },
  seag: { code: 'SEAG', label: 'Seasonality' },
  preopen: { code: 'PRE', label: 'Pre-open auction' },
  movers: { code: 'MOV', label: 'Live movers' },
  filings: { code: 'CF', label: 'Company filings' },
  options: { code: 'OMON', label: 'Option monitor' },
  derivatives: { code: 'DERV', label: 'Derivatives desk' },
  ostrategy: { code: 'OSTR', label: 'Options strategies' },
  deals: { code: 'DEAL', label: 'Block & bulk deals' },
  margin: { code: 'MRGN', label: 'Margin monitor' },
  screen: { code: 'FUND', label: 'Fundamentals screener' },
  alerts: { code: 'ALRT', label: 'Alerts' },
  holders: { code: 'HDS', label: 'Ownership shifts' },
  insiders: { code: 'INSD', label: 'Insider monitor' },
  ipo: { code: 'IPO', label: 'IPO monitor' },
  wrap: { code: 'WRAP', label: 'Daily market wrap' },
  compare: { code: 'COMP', label: 'Compare stocks' },
  desk: { code: 'DESK', label: 'Decision Desk' },
  markets: { code: 'MKT', label: 'Market Monitor' },
  events: { code: 'EVTS', label: 'Corporate calendar' },
  overview: { code: 'OVRV', label: 'Overview' },
  stocks: { code: 'EQS', label: 'Stocks / screener' },
  backtest: { code: 'BTST', label: 'Backtest lab' },
  positions: { code: 'PORT', label: 'Portfolio' },
  broker: { code: 'BRKR', label: 'Broker (ICICI)' },
  pipeline: { code: 'PIPE', label: 'Pipeline / watchlist' },
  scanner: { code: 'LWSC', label: 'LW scanner' },
  discovery: { code: 'ALFA', label: 'Alpha discovery' },
  commodity: { code: 'CMDT', label: 'Commodities' },
  mcxgold: { code: 'MCXG', label: 'MCX gold desk' },
  gold: { code: 'GOLD', label: 'Gold terminal' },
  glassbox: { code: 'GBOX', label: 'Glass-Box studio' },
  mlengine: { code: 'MLEN', label: 'ML engine' },
  explorer: { code: 'DEXP', label: 'Data explorer' },
  warehouse: { code: 'WHSE', label: 'Warehouse health' },
  research: { code: 'RSCH', label: 'Research library' },
  risk: { code: 'RSK', label: 'Risk dashboard' },
  system: { code: 'SYS', label: 'System telemetry' },
})

/** The landing page when the URL has no (valid) ?tab= (page.tsx starts on the brief). */
export const DEFAULT_TAB = 'brief'

/** Page id from a location search string (`?tab=desk&x=1`); DEFAULT_TAB when absent or unknown. */
export function tabFromSearch(search: string): string {
  try {
    const t = new URLSearchParams(search).get('tab')
    return t && Object.prototype.hasOwnProperty.call(PAGE_META, t) ? t : DEFAULT_TAB
  } catch {
    return DEFAULT_TAB
  }
}

/** Code + label for an id; falls back to the code page.tsx put in document.title ("CODE · SuryaDhana"). */
export function pageMeta(id: string, documentTitle = ''): PageMeta {
  const m = PAGE_META[id]
  if (m) return m
  const code = /^([A-Z0-9]{2,6}) · /.exec(documentTitle)?.[1]
  return { code: code ?? id.toUpperCase().slice(0, 6), label: '' }
}

/**
 * BRF's own title for an IST weekday (0 = Sunday) and minute of the day: the rule components/Brief.tsx uses for its
 * page header (Session / Evening / Overnight / Morning brief; desktop.check fails if Brief.tsx's thresholds drift).
 * The title strip shows this instead of the static "Morning brief", so the strip never says MORNING BRIEF over an
 * EVENING BRIEF page (CT-13).
 */
export function briefTitle(istWeekday: number, istMinutes: number): string {
  if (istWeekday >= 1 && istWeekday <= 5 && istMinutes >= 9 * 60 + 15 && istMinutes < 15 * 60 + 30) return 'Session brief'
  if (istMinutes >= 15 * 60 + 30) return 'Evening brief'
  if (istMinutes < 4 * 60) return 'Overnight brief'
  return 'Morning brief'
}

/** The strip's label for a page at an IST weekday / minute: BRF follows its time-of-day title, the rest are static. */
export function stripLabel(meta: PageMeta, istWeekday: number, istMinutes: number): string {
  return meta.code === 'BRF' ? briefTitle(istWeekday, istMinutes) : meta.label
}

/** Native window title, PLAN pattern "<CODE> · <label> — SuryaDhana" (≤ 120 chars, enforced again in Rust). */
export function windowTitle(meta: PageMeta): string {
  const t = meta.label ? `${meta.code} · ${meta.label} — SuryaDhana` : `${meta.code} — SuryaDhana`
  return t.length > 120 ? `${t.slice(0, 119)}…` : t
}
