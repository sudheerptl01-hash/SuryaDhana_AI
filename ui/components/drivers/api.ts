/**
 * `/api/market/index-drivers*` and `/api/desk/attribution` client (reports/terminal_v2/API_CONTRACT.md §3), typed by what
 * B3's routes return. Relative paths through axios (same origin in the static release, Next rewrites in dev). No
 * publisher is ever called from the UI; `ok: false` + `store_errors` means B1's drivers tables are not deployed yet:
 * the block says so ("history starts … · backfill pending") and degrades, never the page.
 *
 * Shares (`share_abs`, `leader_share`, `top5_share`, `top5_abs_share`) are FRACTIONS (0–1); weights and returns are %.
 */
import axios from 'axios'
import type { Badge } from '@/components/terminal/source'

const client = axios.create({ baseURL: '', timeout: 20_000 })

export const DRIVER_INDICES = ['NIFTY 50', 'NIFTY BANK'] as const
export type DriverIndex = (typeof DRIVER_INDICES)[number]
export const HORIZONS = ['1d', '5d', '1m', '3m', 'ytd', 'since_change'] as const
export type Horizon = (typeof HORIZONS)[number]
export const HORIZON_LABEL: Record<Horizon, string> = { '1d': '1D', '5d': '5D', '1m': '1M', '3m': '3M', ytd: 'YTD', since_change: 'SINCE CHANGE' }

export interface DriverStoreMeta { ok?: boolean; store_errors?: Record<string, string>; note?: string; precedent?: string }

export interface DriverMember { symbol: string; industry: string | null; weight_pct: number | null; ret_pct: number | null; points: number | null; share_abs: number | null; flag: string | null }
export interface DriverState {
  window: number; leader: string | null; tenure: number | null; leader_share: number | null; leader_points?: number | null
  changed_from: string | null; change_date: string | null; top5_share?: number | null; hhi_contrib?: number | null
  ew_minus_cw_pp?: number | null; members_up?: number | null; members_down?: number | null; as_of?: string | null; sentence: string
}
export interface IndexDrivers extends DriverStoreMeta {
  as_of: string | null; index: string
  horizon: { name: Horizon; from: string | null; to: string | null; sessions: number }
  index_move_pts: number | null; explained_pts: number | null; residual_pts?: number | null; members_priced?: number | null
  members: DriverMember[]; sectors: { industry: string; points: number; weight_pct: number | null }[]
  concentration: { top5_abs_share: number | null; hhi_contrib: number | null; weight_hhi: number | null; effective_n: number | null; top5_weight_pct: number | null } | null
  breadth: { ew_pct: number | null; cw_pct: number | null; ew_minus_cw_pp: number | null; up: number | null; down: number | null; word?: string | null } | null
  fit: { mae_60s: number | null; r2_60s: number | null; residual_today: number | null; degraded: boolean; sessions?: number; members_priced?: number; members_total?: number; note?: string } | null
  weight_method: { method: string | null; label: string } | null
  driver: DriverState | null
  history_since: string | null
  badges: Record<string, Badge>
}
export interface DriverTimeline extends DriverStoreMeta {
  index: string; window: number; as_of: string | null; badge: Badge
  points: { date: string; leader: string | null; leader_share: number | null; top5_share: number | null; hhi_contrib: number | null; effective_n: number | null; ew_minus_cw_pp: number | null; changed: boolean }[]
  changes: { date: string; to: string | null }[]
}
export interface MonthRow {
  month: string; sessions: number; leader: string | null; leader_pts: number | null; leader_share: number | null; leader_changed: boolean
  index_move_pts: number | null; explained_pts: number | null
  top3_add: { symbol: string; points: number }[]; top3_drag: { symbol: string; points: number }[]
}
export interface DriverMonthly extends DriverStoreMeta { index: string; months: MonthRow[]; n: number; as_of: string | null; badge: Badge }

export interface DeskAttribution extends DriverStoreMeta {
  as_of: string | null; horizon: { name: Horizon; from: string | null; to: string | null; sessions: number }
  risk_off: boolean; since: string | null; nav: number | null; nav_from?: number | null; book_pp: number
  rows: { symbol: string; sector: string | null; qty: number | null; close_from: number | null; close_to: number | null; pnl_inr: number | null; pp_of_nav: number | null }[]
  nifty: { index_move_pts: number | null; explained_pts: number | null; top5_add: DriverMember[]; top5_drag: DriverMember[] } | null
  badges: Record<string, Badge>; paper_only: boolean; note_rules?: string
}

export const getIndexDrivers = (index: string, horizon: Horizon = '1m', window = 20) =>
  client.get<IndexDrivers>('/api/market/index-drivers', { params: { index, horizon, window } })
export const getDriverTimeline = (index: string, window = 20, days = 250) =>
  client.get<DriverTimeline>('/api/market/index-drivers/timeline', { params: { index, window, days } })
export const getDriverMonthly = (index: string, months = 12) =>
  client.get<DriverMonthly>('/api/market/index-drivers/monthly', { params: { index, months } })
export const getDeskAttribution = (horizon: Horizon = '1m') =>
  client.get<DeskAttribution>('/api/desk/attribution', { params: { horizon } })

/** A drivers block that answered but holds nothing yet (tables empty until the backfill), or is not deployed. */
export function driversNote(m: DriverStoreMeta | null | undefined, rows: number): string | null {
  if (!m) return null
  const errs = Object.entries(m.store_errors ?? {})
  if (m.ok === false || errs.length) return errs.length ? errs.map(([p, r]) => `${p.replace(/^\/db\//, '')}: ${r}`).join(' · ') : 'store not available'
  return rows ? null : 'no stored rows yet'
}

/** A failed request in words (404 = the route is not on this ui-api yet). */
export function driversError(e: unknown): string {
  const st = (e as { response?: { status?: number } } | null)?.response?.status
  if (st === 404) return 'route not on this ui-api yet (Terminal v2 not deployed) · backfill pending'
  const d = (e as { response?: { data?: { detail?: unknown } } } | null)?.response?.data?.detail
  if (typeof d === 'string' && d) return d
  return e instanceof Error ? e.message : 'unavailable'
}

/** Signed points with U+2212 and Indian grouping: +1,234.5 / −56.0 / 0.0. */
export function fmtPts(v: number | null | undefined, d = 1): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const r = Number(v.toFixed(d)) || 0
  return `${r > 0 ? '+' : r < 0 ? '−' : ''}${Math.abs(r).toLocaleString('en-IN', { minimumFractionDigits: d, maximumFractionDigits: d })}`
}

/** A fraction (0–1) as a percent string: 0.125 → "12.5 %". */
export function fmtShare(v: number | null | undefined, d = 1): string {
  return v == null || !Number.isFinite(v) ? '—' : `${(v * 100).toFixed(d)} %`
}
