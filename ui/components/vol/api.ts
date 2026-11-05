/**
 * `/api/derivatives/iv/*`, `/api/derivatives/vol-screen` and `/api/options/margin` client (reports/terminal_v2/API_CONTRACT.md
 * §2 and §4), typed by what B3's routes return. Every call is a relative path through the same axios pattern as
 * lib/api.ts (Next rewrites /api in dev; ui-api serves /api on the same origin in the static release), so a Playwright
 * `page.route('**\/api/**')` can feed fixtures to the whole page without a live backend. No publisher is ever called
 * from the UI; `ok: false` + `store_errors` means B1's tables are not deployed yet and the block degrades, never the page.
 */
import axios from 'axios'
import { apiError } from '@/lib/errors'

const client = axios.create({ baseURL: '', timeout: 20_000 })

export const IV_API = '/api/derivatives/iv'

export type Badge = 'signal' | 'context' | 'arithmetic' | 'heuristic'

export interface StoreMeta { ok: boolean; store_errors: Record<string, string>; note: string; precedent?: string }

export interface IvSummaryRow {
  date: string; spot: number | null; iv30_cm: number | null; iv60_cm: number | null; iv90_cm: number | null
  near_atm_iv: number | null; near_expiry: string | null; near_dte: number | null; monthly_atm_iv: number | null; monthly_expiry: string | null
  skew_25d_30: number | null; term_slope_30_90: number | null; iv_rank_252: number | null; iv_pctile_252: number | null
  rv20_cc: number | null; rv20_parkinson: number | null; rv20_yz: number | null; fovolt_ann: number | null; iv_minus_rv20: number | null
  expected_move_1d_pct: number | null; quality_flags: string
}

export interface IvHistory extends StoreMeta {
  symbol: string; as_of: string | null; since: string | null; sessions: number; series: string
  model_version: string | null; r_source: string
  rows: IvSummaryRow[]
  vix: { date: string; close: number | null }[]
  events: { date: string; kind: string }[]
  rank: { iv_rank_252: number | null; iv_pctile_252: number | null; stored: { iv_rank_252: number | null; iv_pctile_252: number | null }; window_sessions: number; on: string }
  definitions: Record<string, string>
  badges: Record<string, Badge>
}

export interface SmilePoint { strike: number; opt_type: string; iv: number; delta: number; log_moneyness: number; oi: number }
export interface ExpiryRow {
  expiry: string; dte: number; forward: number; forward_source: string; atm_iv: number | null
  iv_25d_put: number | null; iv_25d_call: number | null; skew_25d: number | null; iv_10d_put: number | null; iv_10d_call: number | null
  n_iv_strikes: number; call_oi: number; put_oi: number; pcr: number | null; expected_move_pct: number | null; quality_flags: string
  near: boolean; smile: SmilePoint[]; untraded_strikes: number
}
export interface IvSurface extends StoreMeta {
  symbol: string; as_of: string | null; expiries: ExpiryRow[]; n_expiries: number
  compare: { requested: string; as_of: string | null; expiries: ExpiryRow[]; n_expiries: number } | null
  badges: Record<string, Badge>
}

export interface ConeTenor { min: number; p25: number; p50: number; p75: number; max: number; n: number }
export interface IvCone extends StoreMeta {
  symbol: string; as_of: string | null; badge: Badge
  years: { years: number; sessions: number; tenors: Record<string, ConeTenor> }[]
  today: Record<string, number | null>
  term_today: { expiry: string; dte: number | null; atm_iv: number | null }[]
}

export interface CrushRow {
  symbol: string; released_at: string; expiry: string | null; iv_pre_5d: number | null; iv_pre_1d: number | null; iv_post_1d: number | null
  crush_pct: number | null; implied_move_pct: number | null; realised_move_pct: number | null
}
export interface IvEvents extends StoreMeta { symbol: string; rows: CrushRow[]; n: number; badge: Badge }

export interface IntradayPoint { ts: string; expiry: string; atm_strike: number | null; atm_iv: number | null; nse_atm_iv: number | null; straddle: number | null; pcr: number | null; n_strikes: number }
export interface IvIntraday extends StoreMeta { symbol: string; date: string | null; points: IntradayPoint[]; source: 'BREEZE' | 'NSE' | 'OFFLINE' | string; sources: string[]; snapshots: number; badge: Badge }

export interface ScreenRow {
  symbol: string; date: string | null; spot: number | null; iv30_cm: number | null; iv_rank_252: number | null; iv_pctile_252: number | null
  rv20_yz: number | null; iv_minus_rv20: number | null; term_slope_30_90: number | null; skew_25d_30: number | null
  next_results: string | null; results_in_days?: number | null; ban: boolean; mwpl_pct: number | null
}
export type ScreenSort = 'iv_pctile' | 'iv_rank' | 'iv_minus_rv' | 'term_slope' | 'skew'
export interface VolScreen extends StoreMeta { as_of: string | null; sort: ScreenSort; results_within: number | null; rows: ScreenRow[]; n: number; definitions: Record<string, string>; badges: Record<string, Badge> }

export interface OptionHistoryLegacy {
  symbol: string; rows: { date: string; spot: number | null; atm_iv: number | null; pcr: number | null; max_pain: number | null; expiry: string }[]
  updating: boolean; iv_rank_252?: number | null; iv_pctile_252?: number | null; rank_series?: string; rank_window_sessions?: number
  definitions?: Record<string, string>; badges?: Record<string, Badge>
}

export const getIvHistory = (symbol: string, days = 750, series = 'iv30_cm') =>
  client.get<IvHistory>(`${IV_API}/${encodeURIComponent(symbol)}`, { params: { days, series } })
export const getIvSurface = (symbol: string, compare: '1w' | '1m' | '3m' | null = '1m', date?: string) =>
  client.get<IvSurface>(`${IV_API}/${encodeURIComponent(symbol)}/surface`, { params: { compare: compare ?? undefined, date } })
export const getIvCone = (symbol: string) => client.get<IvCone>(`${IV_API}/${encodeURIComponent(symbol)}/cone`)
export const getIvEvents = (symbol: string, n = 8) => client.get<IvEvents>(`${IV_API}/${encodeURIComponent(symbol)}/events`, { params: { n } })
export const getIvIntraday = (symbol: string, date?: string) => client.get<IvIntraday>(`${IV_API}/${encodeURIComponent(symbol)}/intraday`, { params: { date } })
export const getVolScreen = (sort: ScreenSort = 'iv_pctile', resultsWithin?: number | null) =>
  client.get<VolScreen>('/api/derivatives/vol-screen', { params: { sort, results_within: resultsWithin ?? undefined } })
export const getOptionHistoryLegacy = (symbol: string, days = 260) =>
  client.get<OptionHistoryLegacy>(`/api/market/option-history/${encodeURIComponent(symbol)}`, { params: { days } })

// ── margin (PLAN 1.3; API_CONTRACT §4): Breeze → NSE SPAN file → heuristic, the chip says which answered ──────────
export interface MarginLeg { side: 'buy' | 'sell'; kind: 'CE' | 'PE' | 'FUT'; strike: number | null; expiry: string; premium: number; lots: number; lot_size: number }
export interface MarginAnswer {
  symbol: string; exchange_code: string; legs: number; source: 'BREEZE' | 'NSE_SPAN_FILE' | 'HEURISTIC' | string
  source_chip: 'BREEZE' | 'NSE SPAN FILE' | 'HEURISTIC' | string
  span_margin_required: number | null; non_span_margin_required: number | null; total_margin: number | null; order_value: number | null
  as_of: string | null; badge: Badge; note: string; paper_only: boolean
  heuristic: { total: number; per_leg: number[]; premium_outflow: number; defined_risk_floor: number | null; fut_margin_pct: number; error_factor_measured: number; evidence: string; note: string }
  attempts: { source: string; ok: boolean; reason: string }[]
  detail: Record<string, unknown>
}
export const postMargin = (symbol: string, legs: MarginLeg[], forward?: number | null) =>
  client.post<MarginAnswer>('/api/options/margin', { symbol, legs, exchange_code: 'NFO', forward: forward ?? undefined }, { timeout: 25_000 })

/** A route that answered but whose store is not deployed (B1's tables missing): the block says so and degrades. */
export function storeNote(m: StoreMeta | null | undefined): string | null {
  if (!m || m.ok) return null
  const errs = Object.entries(m.store_errors ?? {})
  if (!errs.length) return 'store not available'
  return errs.map(([p, r]) => `${p.replace(/^\/db\//, '')}: ${r}`).join(' · ')
}

/**
 * A failed request in words: a 404 means the Terminal v2 route is not on this ui-api yet (the pre-v2 release) — said
 * as such, with "backfill pending", never as a raw "Request failed with status code 404".
 */
export function volError(e: unknown, fallback = 'unavailable'): string {
  const st = (e as { response?: { status?: number } } | null)?.response?.status
  if (st === 404) return 'route not on this ui-api yet (Terminal v2 not deployed) · backfill pending'
  return apiError(e, fallback)
}
