/**
 * `/api/gold/*` client (reports/gold_program/PLAN.md §d). One function per endpoint, typed by ./types.ts.
 *
 * Every call goes through the same relative-path axios client the rest of the terminal uses (Next rewrites /api
 * in dev; ui-api serves /api on the same origin in the static release), so the page never names a host and a
 * Playwright `page.route('**\/api/gold/**')` can feed fixtures to the whole page without a live backend.
 *
 * Rules (PLAN d): no Yahoo, no Breeze and no publisher is ever called from the UI; everything is read from ui-api's
 * stores and caches. `/api/commodity/gold-preopen*` stay as aliases for one release; the page uses `/api/gold/*`.
 * Sub-view builders (B4B, B5) import from here; do not create a second gold client.
 */
import axios from 'axios'
import type {
  BarInterval, Family, GoldBars, GoldBrief, GoldCalendar, GoldCatalog, GoldContracts, GoldCot, GoldCurve, GoldFair, GoldFlows,
  GoldGlossary, GoldHealth, GoldLog, GoldLogRowX, GoldMacro, GoldOverview, GoldPositioningDaily, GoldPremiums, GoldSeries,
  GoldTooltips, Window,
} from './types'

const client = axios.create({ baseURL: '', timeout: 15_000 })

/** Base of every gold route (also the prefix the QA fixture router matches). */
export const GOLD_API = '/api/gold'

/** Every endpoint the page reads, by name: the node check asserts each one is used and none is a publisher host. */
export const GOLD_ENDPOINTS = {
  overview: `${GOLD_API}/overview`,
  health: `${GOLD_API}/health`,
  fair: `${GOLD_API}/fair`,
  series: `${GOLD_API}/series`,
  bars: `${GOLD_API}/bars`,
  cot: `${GOLD_API}/cot`,
  positioningDaily: `${GOLD_API}/positioning/daily`,
  curve: `${GOLD_API}/curve`,
  contracts: `${GOLD_API}/contracts`,
  premiums: `${GOLD_API}/premiums`,
  flows: `${GOLD_API}/flows`,
  macro: `${GOLD_API}/macro`,
  calendar: `${GOLD_API}/calendar`,
  log: `${GOLD_API}/log`,
  logActual: `${GOLD_API}/log/actual`,
  catalog: `${GOLD_API}/catalog`,
  brief: `${GOLD_API}/brief`,
  glossary: `${GOLD_API}/learn/glossary`,
  tooltips: `${GOLD_API}/learn/tooltips`,
} as const

type Params = Record<string, string | number | boolean | undefined | null>

/** Drop undefined / null / '' so the query string carries only what was set (prefs-driven inputs, PLAN d `fair`). */
function clean(p: Params): Record<string, string | number | boolean> {
  const out: Record<string, string | number | boolean> = {}
  for (const [k, v] of Object.entries(p)) if (v !== undefined && v !== null && v !== '') out[k] = v
  return out
}

export interface ContractQuery { contract?: Family | string; expiry?: string | null }

export const getGoldOverview = (q: ContractQuery & { window?: Window } = {}) =>
  client.get<GoldOverview>(GOLD_ENDPOINTS.overview, { params: clean({ contract: q.contract, expiry: q.expiry, window: q.window }), timeout: 30_000 })

export const getGoldHealth = (window: Window = 'D') =>
  client.get<GoldHealth>(GOLD_ENDPOINTS.health, { params: { window } })

/** Today's pre-open model (the CMDT desk's body + session label, accuracy and holiday). Inputs come from the desk's
 *  saved inputs; `eurusd_trigger` and topics are prefs and are sent only when set. */
export const getGoldFair = (q: { baseline?: number; mcx_price?: number; threshold?: number; eurusd_trigger?: number } & ContractQuery = {}) =>
  client.get<GoldFair>(GOLD_ENDPOINTS.fair, { params: clean(q as Params), timeout: 30_000 })

export const getGoldSeries = (ids: string[], q: { from?: string; to?: string; freq?: Window; asof?: string } = {}) =>
  client.get<GoldSeries>(GOLD_ENDPOINTS.series, { params: clean({ ids: ids.join(','), ...q }) })

export const getGoldBars = (symbol: string, interval: BarInterval = '1m', q: { from?: string; to?: string } = {}) =>
  client.get<GoldBars>(GOLD_ENDPOINTS.bars, { params: clean({ symbol, interval, ...q }), timeout: 30_000 })

export const getGoldCot = (q: { weeks?: number; report?: 'disagg' | 'legacy'; fut_or_combined?: 'F' | 'C' } = {}) =>
  client.get<GoldCot>(GOLD_ENDPOINTS.cot, { params: clean({ weeks: 52, report: 'disagg', fut_or_combined: 'F', ...q }) })

/** `?exchange=MCX&family=GOLDM`: the rows, tape and roll of THAT family (API_CONTRACT §2.6; the server defaults to GOLD,
 *  so a view that shows the picked family MUST pass `sel.family`). Ignored for COMEX (product OI, all months). */
export const getGoldPositioningDaily = (exchange: 'COMEX' | 'MCX', days = 60, family?: Family | string | null) =>
  client.get<GoldPositioningDaily>(GOLD_ENDPOINTS.positioningDaily, { params: clean({ exchange, days, family: exchange === 'MCX' ? family : undefined }) })

/** `?exchange=MCX&family=GOLDTEN`: that family's chain (API_CONTRACT §2.7); the server defaults to GOLD. */
export const getGoldCurve = (exchange: 'COMEX' | 'MCX', date?: string, family?: Family | string | null) =>
  client.get<GoldCurve>(GOLD_ENDPOINTS.curve, { params: clean({ exchange, date, family: exchange === 'MCX' ? family : undefined }) })

export const getGoldContracts = (exchange = 'MCX') =>
  client.get<GoldContracts>(GOLD_ENDPOINTS.contracts, { params: { exchange } })

export const getGoldPremiums = (days = 365) =>
  client.get<GoldPremiums>(GOLD_ENDPOINTS.premiums, { params: { days } })

/** p.asia: gold_asia_daily rows under SHFE_DAILY / SGE_DAILY (API_CONTRACT §2.x, once B3 serves /api/gold/asia) */
export const getGoldAsia = (exchange?: 'SGE' | 'SHFE', from?: string) =>
  client.get<{ rows: { trade_date: string; exchange: string; contract: string; open_interest: number | null; oi_change: number | null; direction: string | null; vwap: number | null; unit: string | null }[]; freshness?: unknown }>(`${GOLD_API}/asia`, { params: clean({ exchange, from }) })
export const getGoldFlows = (months = 24) =>
  client.get<GoldFlows>(GOLD_ENDPOINTS.flows, { params: { months } })

export const getGoldMacro = (window: Window = 'D') =>
  client.get<GoldMacro>(GOLD_ENDPOINTS.macro, { params: { window } })

export const getGoldCalendar = (days = 30) =>
  client.get<GoldCalendar>(GOLD_ENDPOINTS.calendar, { params: { days } })

export const getGoldLog = (threshold = 300, days = 60) =>
  client.get<GoldLog>(GOLD_ENDPOINTS.log, { params: { threshold, days } })

/** Type the actual MCX open for a day (the one write on this page; PAPER, a log row, never an order). */
export const setGoldLogActual = (date: string, open: number) =>
  client.post<GoldLogRowX>(GOLD_ENDPOINTS.logActual, { date, open })

export const getGoldCatalog = () => client.get<GoldCatalog>(GOLD_ENDPOINTS.catalog)

export const getGoldBrief = (date?: string) => client.get<GoldBrief>(GOLD_ENDPOINTS.brief, { params: clean({ date }) })

export const getGoldGlossary = (q?: string) => client.get<GoldGlossary>(GOLD_ENDPOINTS.glossary, { params: clean({ q }) })

export const getGoldTooltips = () => client.get<GoldTooltips>(GOLD_ENDPOINTS.tooltips)

// ── shared small caches (one request per window for the static reference payloads) ─────────────

const memo = new Map<string, { at: number; p: Promise<unknown> }>()
/**
 * Memoise a heavy read per window for `ttlMs` (MONTHLY's 26 years of daily bars + two daily series ≈ 1.5 MB): a tab
 * revisit remounts the view (`key={sub}`) and would otherwise download it all again. A rejected promise is evicted
 * so the next mount retries. Keys name the endpoint and its parameters.
 */
export function memoGet<T>(key: string, ttlMs: number, fn: () => Promise<T>): Promise<T> {
  const hit = memo.get(key)
  const now = Date.now()
  if (hit && now - hit.at < ttlMs) return hit.p as Promise<T>
  const p = fn().catch((e: unknown) => { if (memo.get(key)?.p === p) memo.delete(key); throw e })
  memo.set(key, { at: now, p })
  return p
}

let tooltipsP: Promise<Record<string, string>> | null = null
/** The 93 tooltips, fetched once per window; an empty map when the endpoint is down (labels still render). */
export function loadTooltips(): Promise<Record<string, string>> {
  if (!tooltipsP) {
    tooltipsP = getGoldTooltips().then(r => r.data?.tooltips ?? {}).catch(() => { tooltipsP = null; return {} })
  }
  return tooltipsP
}

let catalogP: Promise<Record<string, import('./types').CatalogRow>> | null = null
/** The catalog keyed by series_id, fetched once per window; empty when down (panels then show "no verdict"). */
export function loadCatalog(): Promise<Record<string, import('./types').CatalogRow>> {
  if (!catalogP) {
    catalogP = getGoldCatalog().then(r => {
      const out: Record<string, import('./types').CatalogRow> = {}
      for (const row of r.data?.rows ?? []) if (row?.series_id) out[row.series_id] = row
      return out
    }).catch(() => { catalogP = null; return {} })
  }
  return catalogP
}
