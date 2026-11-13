/**
 * The paper F&O book + OSTR v2 routes (services/ui-api/routers/fo_book.py, options_strategy.py; W2-BOOK).
 * PAPER ONLY: every call here reads or writes ui-api's paper book; there is no order route and none is named here.
 */
import client from '@/lib/api'

export interface BookMark {
  position_id: number; kind: 'eod' | 'session'; as_of: string; mark_date: string; price: number; iv: number | null
  forward: number | null; spot: number | null; t_days: number | null; price_source: string
  /** close · live · future · parity-forward · model (heuristic) · settlement (NSE final settlement, expiry-day close) ·
   *  expired-unsettled (heuristic: the expiry-day close is not stored yet; never closed at) */
  mark_method: string; settled?: boolean
}
export interface PosGreeks { delta: number; gamma: number; theta_day: number; vega: number; delta_inr_per_1pct: number; gamma_pnl_1pct_inr: number }
export interface BookPosition {
  id: number; structure_id: number; symbol: string; kind: 'CE' | 'PE' | 'FUT'; side: 'buy' | 'sell'; strike: number | null
  expiry: string; lots: number; lot_size: number; entry_price: number; entry_iv: number | null; entry_forward: number | null
  entry_price_source: string; entry_costs: number; opened_at: string; status: 'open' | 'closed' | 'rolled'
  exit_price: number | null; exit_price_source: string | null; exit_costs: number | null; closed_at: string | null
  rolled_from: number | null; rolled_to: number | null; mode: 'paper'
  mark: BookMark | null; pnl: { unrealised: number | null; realised: number; costs: number; net: number | null }
  greeks: PosGreeks; days_to_expiry: number | null
}
export interface StructureSummary {
  entry_cashflow: number; net_label: string; pnl_gross: number; pnl_unrealised: number; pnl_realised: number; costs: number; pnl_net: number
  marks_complete: boolean; max_profit: { value: number | null; unbounded: boolean } | null; max_loss: { value: number | null; unbounded: boolean } | null
  pct_of_max_profit: number | null; loss_x_credit: number | null; nearest_expiry: string | null; open_legs: number
}
export interface BookStructure {
  id: number; name: string; symbol: string; created_at: string; source: string; note: string | null; status: 'open' | 'closed'
  closed_at: string | null; positions: BookPosition[]; summary: StructureSummary
}
export interface UnderlyingGreeks extends PosGreeks { symbol: string; lot_size: number; positions: number; delta_lots: number | null; forward: number | null }
export interface BookGreeks {
  by_underlying: UnderlyingGreeks[]
  total: { theta_day: number; vega: number; delta_inr_per_1pct: number; gamma_pnl_1pct_inr: number }; total_note: string
}
export interface MarksMeta { requested: string; used: 'live' | 'eod'; notes: string[]; chains: { symbol: string; expiry: string; date: string | null; live: boolean; as_of?: string | null }[] }
export interface BookPayload {
  as_of: string; structures: BookStructure[]; open_positions: number; greeks: BookGreeks
  totals: { pnl_gross: number; pnl_unrealised: number; pnl_realised: number; costs: number; pnl_net: number }
  marks_meta: MarksMeta; mark_source: { state: string; source: string; as_of: string | null }; time_convention: string
  capital: { value: number; source: string }; paper_only: true; note: string
}
export interface BookLegBody {
  side: 'buy' | 'sell'; kind: 'CE' | 'PE' | 'FUT' | 'EQ'; strike: number | null; expiry: string; premium: number; iv: number | null
  lots: number; lot_size: number; forward: number | null; price_source: string
}
export interface RollPreview {
  preview: boolean; as_of: string; symbol: string; to_expiry: string; strike_shift: number
  legs: { position_id: number; close_at: number; close_source: string; open_at: number; open_source: string; new_strike: number | null; cash: number; costs: number }[]
  net_cash: number; net_label: string; costs: number; marks_meta: MarksMeta
}
export interface CloseFill { position_id: number; exit_price: number; exit_price_source: string; exit_costs: number; basis: string; pnl: { realised: number; net: number | null } }
export interface ClosePreview { preview: boolean; as_of: string; fills: CloseFill[]; marks_meta: MarksMeta }
export interface VarRow { method: string; var95_1d_inr: number | null; es95_1d_inr: number | null; var99_1d_inr: number | null; es99_1d_inr: number | null; sessions: number }
export interface RiskFo {
  as_of: string; open_positions: number; empty: boolean; message?: string; greeks: BookGreeks
  mark_source: BookPayload['mark_source']; marks_meta: MarksMeta; capital: { value: number; source: string }
  var: { delta_gamma: VarRow; full_revaluation: VarRow; from: string; to: string; covered: string[]; excluded: string[]
         history_source: Record<string, string | null>; note: string } | null
  scenarios: { iv_shock: { iv_shift: number; pnl_inr: number }[]; gap: { spot_pct: number; pnl_inr: number }[]
               combined: { spot_pct: number; iv_shift: number; pnl_inr: number }[]; theta_1d_inr: number; note: string } | null
  margin: { by_underlying: { symbol: string; total_margin: number; sources: string[]; badge: string; note: string }[]
            total_margin: number; capital: number; utilisation_pct: number | null; badge: string; note: string } | null
  notes?: string[]; vega_total_inr?: number; theta_total_inr?: number; paper_only: true
}
export interface SavedLeg {
  side: 'buy' | 'sell'; kind: 'CE' | 'PE' | 'FUT' | 'EQ'; strike: number | null; expiry: string | null; premium: number
  iv: number | null; lots: number; lot_size: number; price_source: string | null
}
export interface SavedStructure { id: number; name: string; symbol: string; legs: SavedLeg[]; note: string | null; created_at: string; updated_at: string }

export const getBook = (status: 'open' | 'closed' | 'all' = 'open') =>
  client.get<BookPayload>('/api/options/book', { params: { status }, timeout: 30_000 })
/** `context` (E-JRNL F-12): the OSTR pre-trade checklist payload as shown at booking — journalled point-in-time
 *  with the booking (ticks, max-loss typed, margin + its source); the server stores it verbatim, size-gated. */
export const postBook = (symbol: string, name: string, legs: BookLegBody[], note?: string, context?: unknown) =>
  client.post<{ structure: BookStructure; paper_only: true; note: string }>('/api/options/book', { symbol, name, legs, note, context: context ?? undefined, mode: 'paper', source: 'OSTR' }, { timeout: 20_000 })
/** close (or preview a close). CONFIRM sends the previewed fills back (`confirm`, `previewed_at`): the paper fill is what
 *  the owner saw, labelled "confirmed as previewed at HH:MM IST" — never a silent re-price. */
export const closeBook = (body: { position_ids?: number[]; structure_id?: number; preview?: boolean; prices?: Record<number, number>
                                  confirm?: Record<number, { price: number; source: string }>; previewed_at?: string }) =>
  client.post<ClosePreview>('/api/options/book/close', { ...body, mode: 'paper' }, { timeout: 30_000 })
export const rollBook = (body: { position_ids: number[]; to_expiry: string; strike_shift?: number; preview?: boolean
                                 confirm?: Record<number, { close_at: number; close_source: string; open_at: number; open_source: string }>; previewed_at?: string }) =>
  client.post<RollPreview>('/api/options/book/roll', { ...body, mode: 'paper' }, { timeout: 30_000 })

/** the previewed close fills as the body's `confirm` map */
export const confirmFills = (fills: Pick<CloseFill, 'position_id' | 'exit_price' | 'exit_price_source'>[]) =>
  Object.fromEntries(fills.map(f => [f.position_id, { price: f.exit_price, source: f.exit_price_source }]))
/** the previewed roll legs as the body's `confirm` map */
export const confirmRoll = (legs: RollPreview['legs']) =>
  Object.fromEntries(legs.map(l => [l.position_id, { close_at: l.close_at, close_source: l.close_source, open_at: l.open_at, open_source: l.open_source }]))
export const getRiskFo = (margin = true) => client.get<RiskFo>('/api/risk/fo', { params: { margin }, timeout: 60_000 })
export const getSaved = (symbol: string) => client.get<{ rows: SavedStructure[]; count: number }>('/api/options/strategy/saved', { params: { symbol } })
export const postSaved = (symbol: string, name: string, legs: SavedLeg[], note?: string) =>
  client.post<{ saved: SavedStructure }>('/api/options/strategy/saved', { symbol, name, legs, note })
export const deleteSaved = (id: number) => client.delete(`/api/options/strategy/saved/${id}`)
