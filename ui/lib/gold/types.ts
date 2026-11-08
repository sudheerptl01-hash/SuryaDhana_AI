/**
 * GOLD page contracts — the TypeScript shapes of every `/api/gold/*` response (reports/gold_program/PLAN.md §d) and
 * the page-level state the sub-views share (contract selection, unit, window, layer).
 *
 * Rules carried by the types themselves (PLAN §f):
 *  - `GoldHealth` has NO `score` field: the verdict is a sentence of thresholded clauses and ends
 *    "describes, does not predict" (`ui/lib/gold/format.ts` `healthLine` enforces the suffix).
 *  - every published number carries a `Badge` from the catalog and a `Freshness` block (value · source · as-of · lag).
 *  - numbers are numbers (never pre-formatted strings); the UI formats with the terminal kit (U+2212, en-IN grouping).
 *
 * Pure module (no React, no DOM): imported by the sub-views (B4A/B4B/B5), by `api.ts` and by the node check
 * `ui/components/__tests__/gold.check.ts`. Builders of other sub-views import from here; do not redeclare these.
 */
import type { GoldPreOpen } from '@/lib/api'

// ── vocabulary ──────────────────────────────────────────────────────────────────────────────────

/** Evidence badge (PLAN §f.1). `signal`: none today. */
export type Badge = 'signal' | 'context' | 'arithmetic' | 'heuristic'
/** Catalog verdict per series (SOURCES.md §1). Nothing without PUBLISH-CORE / PUBLISH-CONTEXT renders a number. */
export type Verdict = 'PUBLISH-CORE' | 'PUBLISH-CONTEXT' | 'LINK-ONLY' | 'DO-NOT-PUBLISH'
export type FreshState = 'live' | 'delayed' | 'stale' | 'unavailable'
export type Window = 'D' | 'W' | 'M'
export type Freq = 'I' | 'D' | 'W' | 'M' | 'Q'
export type Quality = 'official' | 'derived' | 'proxy'
export type Layer = 'B' | 'P'

/** The nine sub-views, in tab order (PLAN a.1). */
export const GOLD_SUBS = ['health', 'daily', 'weekly', 'monthly', 'positioning', 'physical', 'macro', 'contracts', 'learn'] as const
export type GoldSub = (typeof GOLD_SUBS)[number]

/** MCX gold families (PLAN a.1; GOLDTEN added by B3's `/api/gold/contracts`). */
export const GOLD_FAMILIES = ['GOLD', 'GOLDM', 'GOLDTEN', 'GOLDGUINEA', 'GOLDPETAL'] as const
export type Family = (typeof GOLD_FAMILIES)[number]
export type Exchange = 'MCX' | 'NSE' | 'BSE'

/** Page-global unit picker (a.1). */
export const GOLD_UNITS = ['usd_oz', 'inr_10g', 'inr_g', 'usd_g', 'tola'] as const
export type Unit = (typeof GOLD_UNITS)[number]

/** Per-block freshness (every panel shows value · source · as-of · lag chip, PLAN 0.1 #10). */
export interface Freshness {
  state: FreshState
  source?: string | null
  as_of?: string | null
  /** seconds since the publisher's as-of, when known */
  age_s?: number | null
  age_days?: number | null
  /** why a stale/unavailable block is in that state (429, blocked, not yet ingested, "since 27 Oct 2026") */
  reason?: string | null
}

/** The prefs-synced contract selection (key `gold.contract.v1`, shared with MCXG). */
export interface GoldContractSel {
  exchange: Exchange
  family: Family
  /** ISO date; null = front by open interest (the server picks) */
  expiry: string | null
  /** options overlay in the selector (CE/PE) */
  options: boolean
}

/** Props every sub-view receives from GoldPage (B4B / B5 views take the same). */
export interface GoldSubViewProps {
  sel: GoldContractSel
  unit: Unit
  window: Window
  layer: Layer
  /** the matched COMEX month for `sel` once the overview has resolved it (e.g. "GCZ26.CMX") */
  comexMatched: string | null
  /** USD/INR from the header strip, for unit conversion in the view (null before the strip loads) */
  usdinr: number | null
  /** one-line micro-copy per payload field (`/api/gold/learn/tooltips`), keyed by field name */
  tooltips: Record<string, string>
  /** the catalog, keyed by series_id (for "about" popovers and the rendering gate) */
  catalog: Record<string, CatalogRow>
  /**
   * THE fair block of this page load — `/api/gold/overview`'s `health.fair` (landed · duty-paid landed · basis ·
   * settlement · the live legs with their as-of), fetched ONCE by GoldPage and handed to every sub-view, so a landed or
   * duty-paid price prints the same rupee on HEALTH, PHYSICAL and CONTRACTS (PLAN §f.6; C-TRADER-19). A view that shows
   * one of these numbers reads it from here, never from its own fetch.
   */
  fair: HealthFair | null
  /** the whole overview the strip was built from (same load as `fair`): strip, contract, session, freshness */
  overview: GoldOverview | null
  /**
   * the overview's load state (wave 1e, M-A): HEALTH and LEARN render `overview.health` — built for the PICKED contract with
   * the live MCX quote applied during MCX hours, the same load as the header strip — and fall back to `/api/gold/health`
   * only once the overview has failed ('error'), never while it is still loading (no GOLD-contract flash).
   */
  overviewStatus?: 'loading' | 'ok' | 'error'
  onNavigate: (sub: GoldSub) => void
  /** change the page-global contract selection (prefs `gold.contract.v1`); the CONTRACTS selector uses it */
  onSel?: (patch: Partial<GoldContractSel>) => void
}

// ── catalog ─────────────────────────────────────────────────────────────────────────────────────

export interface CatalogRow {
  series_id: string
  name: string
  source_entry: string
  publisher: string
  url: string
  freq: Freq
  unit: string
  publish_time_ist?: string | null
  lag_note?: string | null
  access: 'FREE' | 'FREE-KEY' | 'FREE-REGISTRATION' | 'PAID' | 'BLOCKED' | 'UNVERIFIED' | string
  terms?: string | null
  verdict: Verdict
  verdict_reason?: string | null
  badge: Badge
  evidence?: string | null
  beginner_note?: string | null
  pro_note?: string | null
  how_pros_use_it?: string | null
  resample: 'last' | 'sum' | 'mean'
  ingest_job?: string | null
  max_age_days: number
  verified_at?: string | null
  verified_by?: string | null
}

// ── /api/gold/health ────────────────────────────────────────────────────────────────────────────

export interface HealthClause {
  text: string
  rule_id: string
  /** H4: the clock of `value` ('now' = live MCX vs duty-paid now; 'settlement'); H2: the date of the real-yield point (wave 1e) */
  clock?: string | null
  report_date?: string | null
  series_id?: string | null
  value?: number | string | Record<string, number | string | null> | null
  /** routers/gold.py HEALTH_RULES: numbers, strings or objects ({weak_pct, strong_pct, flat_pct}, {usd_share, min_move_pct, real_yield_bp}); never render as a React child */
  threshold?: number | string | Record<string, number | string | null> | null
}

export type GoldDirection = 'supportive' | 'headwind' | 'neutral'

export interface HealthGauge {
  key: string
  label: string
  value: number | null
  unit: string
  change?: number | null
  /** the unit of `change` ('%', 'bp', '$/oz', 't', 'contracts', 'index'); the UI branches on it (C-DATA-7) */
  change_unit?: string | null
  change_window?: string | null
  report_date?: string | null
  release_at?: string | null
  age_days?: number | null
  state: FreshState
  direction_for_gold?: GoldDirection | null
  rule?: string | null
  percentile_1y?: number | null
  percentile_3y?: number | null
  series_id?: string | null
  source?: string | null
  badge: Badge
  evidence?: string | null
  /** 60-day sparkline values when the server attaches them */
  spark?: number[] | null
  /** gauge-specific extras the server attaches (B3 build_health): all optional, all numbers or short strings */
  change_bp?: number | null
  change_pct?: number | null
  vs_20d_pct?: number | null
  vs_200d_pct?: number | null
  drawdown_52w_pct?: number | null
  /** TREND (wave 1d contract): drawdown from the 52-week high, % (alias of drawdown_52w_pct) and the words the values earn */
  drawdown_pct?: number | null
  trend_words?: 'below both averages' | 'between' | 'above both' | string | null
  /** INDIA BASIS (wave 1d): the purity of the landed price the basis divides by, and the duty-paid landed it used now */
  basis_reference?: BasisReference | null
  duty_paid_landed_now?: number | null
  mcx_live?: number | null
  net_pct_oi?: number | null
  cot_index_52?: number | null
  /** POSITIONING: "long, not crowded" etc. (a description, never a colour) */
  words?: string | null
  /** POSITIONING: the G-STUDY §5.2 fund-driver label with the Tue→Tue GC=F change — identical to /cot.driver_label (API_CONTRACT §2.1) */
  driver_label?: string | null
  week_price_chg_pct?: number | null
  ibja_premium_pct?: number | null
  ibja_premium_date?: string | null
  duty_pct?: number | null
  duty_effective?: string | null
  settlement_session_label?: string | null
  /** INDIA BASIS (wave 1d/1e): the contract the basis is for ('GOLDTEN NOV-26'), its purity, and its settlement's source / quality */
  basis_contract?: string | null
  /** INDIA BASIS (wave 1e, G2-API): the server's chip naming the clock ('LIVE · GOLDTEN NOV-26 · 09:16 IST' / 'SETTLEMENT · VWAP30 PROXY · Thu 05 Nov') */
  clock_label?: string | null
  purity?: number | null
  duty_paid_landed_purity_now?: number | null
  settlement_source?: SettlementSource | string | null
  settlement_quality?: SettlementQuality | string | null
  /** REAL YIELD (wave 1e, M-B): the series the value came from when the fresher twin won ('UST_REAL_10Y: fresher than FRED_DFII10 (last …)') */
  label_note?: string | null
  /** INDIA BASIS (wave 1c): the clock of `value` ('now' with a live quote, else 'settlement') and the other clock's figure beside it */
  clock?: string | null
  basis_label?: string | null
  live_basis_pct?: number | null
  settle_basis_pct?: number | null
  settle_basis_date?: string | null
  settle_basis_label?: string | null
  settle_basis_source?: string | null
  ibja_premium_note?: string | null
  /** DOLLAR: which read the tile used ('series DXY_CLOSE' | 'daily bars DX-Y.NYB' | 'series FRED_DTWEXBGS (stand-in)') */
  read_from?: string | null
  /** POSITIONING: the week's two legs the label was computed from */
  chg_long?: number | null
  chg_short?: number | null
  /** CURVE / ROLL: the front month's last trade and where its FND came from */
  ltd_date?: string | null
  fnd_source?: string | null
  chg_5d?: number | null
  /** CURVE / ROLL: front and next month codes, annualised carry, days to COMEX first notice */
  front?: string | null
  next?: string | null
  annualised_pct?: number | null
  days_to_fnd?: number | null
  fnd_date?: string | null
  /** false when the catalog has no PUBLISH verdict for the series (the tile then shows "no verdict — not published") */
  published?: boolean
  note?: string | null
  /** TREND: the server's wording of the window it measured ('week to date (since the Fri 30 Oct close)' / '5 sessions'); the verdict's week label follows it (C-TRADER-16) */
  window_label?: string | null
  window_from?: string | null
  window_sessions?: number | null
  /** TREND: today's bar is a partial Globex day, not a settlement (C-DATA-21) */
  last_bar_partial?: boolean | null
  last_bar_note?: string | null
}

/**
 * Wave 1d (the settlement blocker): WHERE the MCX settlement every gold number divides by came from. The ICICI master's
 * price-band midpoint is one MCX session stale (its band is set around the session BEFORE the one the file names), so the
 * server prefers the latest COMPLETED session's last-30-minute volume-weighted average of the Breeze 1-minute bars — MCX's
 * own settlement method, a proxy because it is not the bhavcopy — and keeps the band midpoint for reference, labelled with
 * the session it really belongs to. `settlement_check.flagged` when the two differ by more than 0.6 %
 * (`SETTLEMENT_CHECK_PCT` in ./format; the accuracy log's `stale_baseline` uses the same test).
 * Carried by `/health.fair`, `/overview.strip`, `/fair.baseline` (same names; the UI reads whichever block it holds).
 */
export type SettlementSource = 'breeze_vwap30' | 'band_midpoint' | 'breeze_previous_close' | 'user_entry'
export type SettlementQuality = 'vwap30_proxy' | 'band_proxy' | 'proxy'
export interface SettlementCheck { band_vs_vwap30_pct: number | null; flagged: boolean }
export interface SettlementFields {
  settlement?: number | null
  settlement_source?: SettlementSource | string | null
  /** ISO date of the session the number belongs to (never the file date) */
  settlement_session?: string | null
  /** 'Wed 04 Nov settlement' */
  settlement_session_label?: string | null
  settlement_quality?: SettlementQuality | string | null
  /** the ICICI band midpoint, kept for reference, and the session it REALLY belongs to */
  band_midpoint?: number | null
  band_session?: string | null
  settlement_check?: SettlementCheck | null
  /** wave 1d/1e: false when the settlement is NOT the latest completed MCX session's (its VWAP is not in yet, or a special
   *  session such as Muhurat was skipped); `latest_session` names the session that should have been used */
  settlement_is_latest?: boolean | null
  latest_session?: string | null
  latest_session_label?: string | null
  /** `/fair.baseline` (wave 1e, M-D): the 08:45 flag and its sentence (names a special session such as Muhurat) */
  older_than_expected?: boolean | null
  older_note?: string | null
  expected_session?: string | null
}

/**
 * India basis purity (wave 1d; PM decision D1): MCX GOLD / GOLDM are 995 fine, GOLDTEN, GOLDPETAL and GOLDGUINEA 999; the
 * basis divides the contract's price, scaled to ₹/10 g, by the landed price of THAT purity. The server names it in
 * `basis_reference`.
 */
export type BasisReference = 'landed_995' | 'landed_999' | string

/** A live leg of the fair model as the server sends it (`mcx._fair_value`): `{symbol, price, as_of}`. */
export interface FairLeg { symbol?: string | null; price: number | null; as_of?: string | null }

/** `/health.fair` (API_CONTRACT §2.1; the SERVER shape). `comex` / `usdinr` are legs, not numbers: read them with
 *  `legPrice()` from ./format (a bare number is tolerated for the legacy MCXG composer only). */
export interface HealthFair extends Omit<SettlementFields, 'settlement' | 'settlement_session' | 'settlement_session_label' | 'settlement_quality'> {
  contract?: string | null
  expiry?: string | null
  expiry_source?: string | null
  fair_value: number | null
  mcx_live: number | null
  mcx_live_source?: string | null
  premium_rupees: number | null
  premium_pct: number | null
  comex: FairLeg | number | null
  comex_symbol?: string | null
  usdinr: FairLeg | number | null
  landed: number | null
  duty_pct: number | null
  duty_effective?: string | null
  duty_note?: string | null
  duty_paid_landed: number | null
  basis_pct: number | null
  settlement: number | null
  settlement_session?: string | null
  settlement_session_label?: string | null
  settlement_quality?: SettlementQuality | string | null
  /** the landed price of the contract's purity the basis divides by (wave 1d) */
  basis_reference?: BasisReference | null
  /** fair − settlement in ₹ (the "gap" of BRF's before-open line), from the server */
  gap_vs_settlement?: number | null
  /** today's captured MCX open (gold_preopen_log) once the 09:10 capture ran: BRF's "Gold opened … (miss …)" line */
  actual_open?: number | null
  actual_open_source?: string | null
  /** the 08:45 snapshot's fair open and its measured error (the morning call; NOT the live fair value) */
  snapshot_fair?: number | null
  snapshot_error?: number | null
  /** today's MCX closure, when `mcx_specs.holiday_on(today)` is set: BRF's "MCX closed (…)" line */
  mcx_holiday?: { name: string; closure: 'full' | 'morning' | 'evening'; opens_at?: string | null } | null
  /** @deprecated one release alias of basis_pct (B3) */
  implied_premium_pct?: number | null
  /** the desk's ₹300 rule on the cached MCX quote: OK / WAIT once a price exists, AWAITING_OPEN / NEED_PRICE before (what brf_line prints) */
  desk_verdict_state?: 'OK' | 'WAIT' | 'AWAITING_OPEN' | 'NEED_PRICE' | string | null
  badge?: Badge
  freshness?: Freshness
}

export interface HealthVerdict {
  line: string
  clauses: HealthClause[]
  /** the head words ("WEAK WEEK, DOLLAR-DRIVEN"), the source of the ≤ 24-char verdict words on WEI / BRF */
  headline?: string | null
  /** the window the week label describes ('Mon 02 Nov → Wed 04 Nov' once the week has started, else '5 sessions'): the UI prints it verbatim (C-TRADER-16) */
  window_label?: string | null
  badge?: Badge
  ends_with?: string
}

/** `GET /api/gold/health` — no `score`, no `of`, no composite (PLAN §f.4). */
export interface GoldHealth {
  as_of: string
  window: Window
  /** the server's wording of the window (see HealthVerdict.window_label) */
  window_label?: string | null
  verdict: HealthVerdict
  gauges: HealthGauge[]
  fair: HealthFair
  /** WEI's second line, built by the server (verdict words · basis · COT MM · roll · GOLD ›); rendered verbatim */
  line: string
  /** BRF's one line, built by the server from the same rule it logs with (before / after the captured open / holiday) */
  brf_line?: string | null
  lines?: { wei?: string | null; brf?: string | null } | null
  freshness: { state: FreshState; oldest?: string | number | null; age_days?: number | null; unavailable?: string[]; stale?: string[] }
  /** which stored reads failed, by block (never a reason to blank the page) */
  store_errors?: Record<string, string> | null
}

// ── /api/gold/fair (today's /api/commodity/gold-preopen + additions) ────────────────────────────

export interface FairAccuracy {
  days: number
  median_abs_error?: number | null
  mean_abs_error?: number | null
  p90?: number | null
  within_threshold_pct?: number | null
  naive_mean_abs_error?: number | null
  bias?: number | null
  threshold?: number | null
  badge?: Badge
}

export interface GoldFair extends Omit<GoldPreOpen, 'baseline' | 'verdict'> {
  /** wave 1d: the baseline carries the same settlement block as `/health.fair` (source, session, quality, band, check) */
  baseline: GoldPreOpen['baseline'] & { session_label?: string | null; stale?: boolean | null; master_published?: string | null } & SettlementFields
  /** the `/health.fair` block for a non-GOLD family or an explicit expiry (API_CONTRACT §2.2) */
  contract_fair?: HealthFair | null
  verdict: GoldPreOpen['verdict'] & { badge?: 'heuristic' }
  accuracy?: FairAccuracy | null
  /** today's accuracy-log row once the 08:45 snapshot ran (API_CONTRACT §2.2) */
  today_log?: GoldLogRowX | null
  holiday?: { closure: 'full' | 'morning' | 'evening'; name?: string | null; opens_at?: string | null; note?: string | null } | null
  badge?: Badge
  freshness?: Freshness
}

// ── /api/gold/overview ──────────────────────────────────────────────────────────────────────────

export interface OverviewContract {
  mcx: Family | string
  name?: string | null
  expiry: string | null
  expiry_source: 'observed' | 'computed' | string
  comex_matched: string | null
  comex_matched_calendar?: string | null
  comex_matched_note?: string | null
  comex_front: string
  spot_proxy_note?: string | null
  lot?: string | null
  tick_value?: number | null
  quote_unit?: string | null
  master_published?: string | null
  band?: Record<string, unknown> | null
}

export interface OverviewSession {
  mcx: { is_open: boolean; segment?: string | null; opens_at?: string | null; closes_at?: string | null; holiday?: { name: string; closure: string } | null
         seconds_to_open?: number | null; seconds_to_close?: number | null; weekend?: boolean | null }
  comex: { is_open: boolean; note?: string | null }
}

/** The five numbers of the header strip (a.1) + the gold-api cross-check chip (A12). */
export interface OverviewStrip extends SettlementFields {
  /** wave 1d: the purity of the landed price `basis_*` divides by */
  basis_reference?: BasisReference | null
  comex_matched?: string | null
  comex_matched_settle: number | null
  comex_matched_settle_date?: string | null
  comex_live: number | null
  comex_live_chg_pct?: number | null
  comex_live_as_of?: string | null
  comex_live_source?: string | null
  comex_ref_note?: string | null
  /** the matched month's stored daily close / last trade when no bulletin settlement exists ('last 4,078.3 · Yahoo, not settlement') */
  comex_matched_last?: number | null
  comex_matched_last_date?: string | null
  comex_matched_last_source?: string | null
  /** 'last trade (Yahoo per-month daily bar), not a settlement' */
  comex_matched_last_label?: string | null
  /** the nearest LIQUID COMEX month is `comex_matched`; the calendar month the desk's fair leg prices, and the note when they differ (C-BEGINNER-26) */
  comex_matched_calendar?: string | null
  comex_matched_note?: string | null
  /** the month the desk's live COMEX leg prices (the calendar month) */
  comex_live_symbol?: string | null
  usdinr: number | null
  usdinr_as_of?: string | null
  real_10y: number | null
  real_10y_date?: string | null
  /** wave 1e (M-B): the series the strip's real yield came from (the fresher twin: UST_REAL_10Y over FRED_DFII10) and its note */
  real_10y_series_id?: string | null
  real_10y_series?: string | null
  real_10y_source?: string | null
  real_10y_note?: string | null
  real_10y_label_note?: string | null
  mcx_settle: number | null
  mcx_settle_session: string | null
  mcx_settle_session_label?: string | null
  mcx_settle_quality?: string | null
  /** the live MCX quote (ICICI Breeze) while the session runs; the strip shows it above the settlement (C-TRADER-10) */
  mcx_live?: number | null
  mcx_live_source?: string | null
  mcx_live_as_of?: string | null
  /** the settlement-clock basis: MCX settle ÷ that session's duty-paid landed − 1 (the stored MCX_BASIS_PCT) */
  basis_pct: number | null
  basis_session?: string | null
  basis_session_label?: string | null
  /** live MCX ÷ duty-paid landed now − 1, when a live quote exists */
  basis_live_pct?: number | null
  /** which clock `basis_pct` is at ('now' while the page holds a quote, else 'settlement') and its label; the settlement figure beside it */
  basis_clock?: 'now' | 'settlement' | string | null
  basis_label?: string | null
  basis_settle_pct?: number | null
  basis_settle_date?: string | null
  /** live MCX vs the settlement, and which of the two the header shows ('live' during MCX hours with a quote) */
  mcx_live_vs_settle_pct?: number | null
  mcx_shown?: 'live' | 'settlement' | string | null
  cot_mm_net: number | null
  cot_mm_chg: number | null
  cot_as_of: string | null
  crosscheck?: { price: number | null; at?: string | null; source?: string | null } | null
  instruments?: Partial<Record<InstrumentKey, string>> | null
}

export interface GoldHeadline { topic: string; title: string; publisher: string; link: string; published_at: string }

export interface GoldBriefDoc {
  available: boolean
  report_date?: string | null
  bias?: string | null
  confidence?: number | null
  overnight_summary?: string | null
  open_plan?: string | null
  key_risks_today?: string[]
}

export interface GoldEvent {
  event_date: string
  date?: string
  time_ist?: string | null
  kind: string
  name: string
  detail?: string | null
  country?: string | null
  impact?: string | null
  forecast?: string | null
  previous?: string | null
  actual?: string | null
  in_session?: boolean | null
  /** time_ist after the MCX close (23:30) */
  after_close?: boolean | null
  days?: number | null
  source?: string
  /** wave 1c (API_CONTRACT §2.12): the page kind (FOMC_SPEECH / FOMC_MINUTES split off the store's FOMC; `kind_stored` keeps the original),
   *  ★ only on High impact or an FOMC decision, the sort rank (0 = decision / High … 4 = Low) and whether today's row is already past */
  kind_stored?: string | null
  star?: boolean
  impact_rank?: number
  past?: boolean
}

export interface GoldOverview {
  as_of: string
  window?: Window
  contract: OverviewContract
  session: OverviewSession
  strip: OverviewStrip
  health?: GoldHealth | null
  fair?: GoldFair | null
  quote?: Record<string, unknown> | null
  headlines?: GoldHeadline[]
  brief?: GoldBriefDoc | null
  calendar?: GoldEvent[]
  freshness: Record<string, Freshness | null | undefined>
  errors?: Record<string, string> | null
}

// ── /api/gold/series ────────────────────────────────────────────────────────────────────────────

export interface SeriesPoint { report_date: string; value: number; release_at?: string | null; n?: number | null }

export interface GoldSeriesRow {
  series_id: string
  name: string
  unit: string
  freq_native: Freq
  quality: Quality
  resample: 'last' | 'sum' | 'mean'
  /** false when the catalog has no PUBLISH verdict: the server sends NO points (PLAN §f.2) */
  published?: boolean
  note?: string | null
  points: SeriesPoint[]
  n?: number | null
  catalog: { publisher: string; verdict: Verdict; badge: Badge; lag_note?: string | null; terms?: string | null; evidence?: string | null }
  freshness?: Freshness
}

export interface GoldSeries { as_of: string; asof_applied?: string | null; freq: Window; series: GoldSeriesRow[]; store_errors?: Record<string, string> | null }

// ── /api/gold/bars (the DAILY chart) ────────────────────────────────────────────────────────────

export type BarInterval = '1m' | '5m' | '1d'

/** `ts`: an ISO instant WITH offset (B1 wave 1c), a zone-less ISO datetime (= UTC, the store's older form), 'YYYY-MM-DD', or epoch s/ms — `sessions.barMs` reads all four */
export interface Bar {
  ts: string | number; o: number | null; h: number | null; l: number | null; c: number | null; v?: number | null; partial?: boolean | null
  /** wave 1e `ohlc_sane`: a price outside the bar's [low, high] is WITHHELD (`o` / `c` null) and kept here with the reason.
   *  A withheld open must be treated exactly like an impossible one (C-DATA-06: `o ?? c` silently resurrected it as the close). */
  o_raw?: number | null
  c_raw?: number | null
  ohlc_note?: string | null
  /** SGE Au99.99 only (CT-01 / F1): the server converts CNY/g → $/oz and keeps the native price and the rate it used —
   *  ONE rate per drawn session, so the line cannot step at Beijing midnight without a price move. */
  o_cny_g?: number | null
  h_cny_g?: number | null
  l_cny_g?: number | null
  c_cny_g?: number | null
  /** the native twins of a WITHHELD price (`o_raw` / `c_raw` are the converted ones) */
  o_raw_cny_g?: number | null
  c_raw_cny_g?: number | null
  usdcny?: number | null
  usdcny_date?: string | null
}

export interface SessionBand { name: string; start_ist: string; end_ist: string; hatched?: boolean; bar?: boolean; closed?: boolean }

/** `/bars` takes Yahoo symbols as data-service stores them (`GC=F`, `GCZ26.CMX`, `INR=X`, `SGE_AU9999`; API_CONTRACT §2.4). */
export interface GoldBars {
  symbol: string
  interval: BarInterval
  bars: Bar[]
  sessions?: SessionBand[]
  /** wave 1c (C-TRADER-2 / C-TRADER-17): the dashed line is a CME settlement when stored, else the PREVIOUS session's daily close (`is_settlement: false`), never the live last;
   *  `matched_last` is the symbol's own month on the stored curve (labelled 'last trade (Yahoo), not a settlement'); `daily_closes` feed the legend (partial-day flagged) */
  settle_line?: { value: number | null; label: string; source?: string | null; quality?: string | null; is_settlement?: boolean } | null
  matched_last?: { value: number | null; label: string; source?: string | null; quality?: string | null; is_settlement?: boolean } | null
  prev_close?: { date: string; close: number | null; partial?: boolean; label?: string | null } | null
  daily_closes?: { date: string; close: number | null; partial?: boolean; label?: string | null }[]
  prev_day?: { ts: string | number; c: number }[]
  /** which instrument these bars are (spot proxy · COMEX front GC1 · matched month · MCX) */
  instrument?: string | null
  day?: string | null
  hi?: number | null
  lo?: number | null
  since?: string | null
  note?: string | null
  freshness?: Freshness
  /** what `bars`, `hi` / `lo`, `prev_day` and the lines are in — every payload states it (CT-01 / F1). An overlay whose
   *  unit is not the chart's own is NEVER drawn: raw CNY/g on the USD/oz axis stretched the 24-h y-range to 1,000–4,000. */
  unit?: string | null
  /** the unit the store keeps (SGE Au99.99: 'CNY/g'), beside each bar as `c_cny_g` … */
  unit_native?: string | null
  /** the USDCNY leg the conversion used — the SAME ladder the Shanghai premium reads, the LAST drawn session's vintage.
   *  `partial` is the rate's own flag: a USDCNY point can itself be a pre-close print, and the page labels it. */
  fx?: { series: string | null; value: number | null; report_date: string | null; release_at?: string | null; partial?: boolean | null; conversion?: string | null } | null
  conversion?: string | null
  /** every USDCNY vintage the window used, one per drawn session (> 1 = the window spans sessions priced at different rates) */
  fx_vintages?: string[] | null
  /** rows the conversion refused: no stored USDCNY vintage on or before their session, so a short series is not a short store */
  dropped_no_fx?: number | null
  /** the same bar as `hi` / `lo`, read in the native unit (never a different bar's extreme) */
  hi_native?: number | null
  lo_native?: number | null
  /** when the live last is appended by the server from the SWR cache */
  last?: { price: number; as_of: string; source: string; age_s?: number | null } | null
  store_errors?: Record<string, string> | null
}

// ── /api/gold/cot (POSITIONING; B4B) ────────────────────────────────────────────────────────────

export interface CotGroup {
  key: 'mm' | 'or' | 'nr' | 'sd' | 'pm' | 'nc' | 'c' | string
  label: string
  long: number | null
  short: number | null
  spread?: number | null
  net: number | null
  net_moz?: number | null
  net_t?: number | null
  net_usd_bn?: number | null
  chg_long?: number | null
  chg_short?: number | null
  chg_net?: number | null
  pct_oi_long?: number | null
  pct_oi_short?: number | null
  net_pct_oi?: number | null
  traders_long?: number | null
  traders_short?: number | null
  who_did?: string[]
}

export interface CotHistoryRow {
  report_date: string
  price?: number | null
  mm_net?: number | null
  or_net?: number | null
  nr_net?: number | null
  sd_net?: number | null
  pm_net?: number | null
  oi?: number | null
  cot_index_52?: number | null
}

export interface CotDecompRow {
  span: string
  price_from?: number | null
  price_to?: number | null
  d_mm_long?: number | null
  d_mm_short?: number | null
  d_mm_net?: number | null
  d_comm_net?: number | null
  d_sd_net?: number | null
  d_pm_net?: number | null
  d_or_net?: number | null
  d_nr_net?: number | null
  d_oi?: number | null
  d_gld_t?: number | null
}

/** `/cot` with nothing stored answers 200 `{ok: false, error_info: {code: "state"}, latest: null}` (API_CONTRACT §2.5):
 *  read `latest` with `?.` — the field stays typed non-null so the B4B view compiles unchanged. */
export interface GoldCot {
  as_of: string
  ok?: boolean
  error_info?: { code: string; message?: string | null; hint?: string | null } | null
  report?: string
  fut_or_combined?: string
  /** `release_ist` / `next_release_ist` are LABELS ("Sat 31 Oct 01:00 IST", rendered verbatim); `next_release_at` is the ISO instant (API_CONTRACT §2.5) */
  latest: { report_date: string; release_at?: string | null; release_ist?: string | null; next_report_date?: string | null; next_release_at?: string | null
            next_release_ist?: string | null; next_release_source?: 'rule' | 'published' | string | null; age_days?: number | null; stale?: boolean; catch_up_note?: string | null } | null
  open_interest: { total: number | null; chg: number | null; pct_rank?: number | null; pct_rank_label?: string | null }
  groups: CotGroup[]
  driver_label?: string | null
  /** the rule's text, mirrored from data-service driver_rule.py (the [P] line can print it) */
  driver_rule?: string | null
  quadrant_label?: string | null
  week_price_chg_pct?: number | null
  price_tue?: number | null
  price_prev_tue?: number | null
  crowd?: { cot_index_26?: number | null; cot_index_52?: number | null; cot_index_156?: number | null; z52?: number | null; z156?: number | null; percentile_all?: number | null
            /** wave 1c (C-DATA-14): `percentile_all` is data-service's 1986→ figure (null when absent); the fetched-window figure is labelled '3-y percentile (160 reports)' */
            percentile_window?: number | null; window_reports?: number | null; window_label?: string | null; percentile_label?: string | null
            n_reports?: number | null; label: string; badge?: Badge }
  options_overlay?: { mm_net_options_only?: number | null; combined_oi?: number | null; mm_net_combined?: number | null; line?: string | null }
  history?: CotHistoryRow[]
  decomposition?: (CotDecompRow & { from_date?: string | null; to_date?: string | null })[]
  drawer?: Record<string, unknown>
  badge: Badge
  evidence?: string | null
  footer?: string | null
  freshness?: Freshness
  store_errors?: Record<string, string> | null
}

// ── /api/gold/positioning/daily (d.quadrant, p.daily.*) ─────────────────────────────────────────

export type QuadrantLabel = 'long build-up' | 'short build-up' | 'short covering' | 'long unwinding' | string

export interface DailyPositioningRow {
  trade_date: string
  /** COMEX: the product ("GC", "MGC", "OG:C" …); MCX: the FAMILY code the request named (`?family=`) */
  symbol_or_product: string
  product_desc?: string | null
  expiry?: string | null
  open_interest: number | null
  oi_change: number | null
  volume?: number | null
  globex_volume?: number | null
  settle_or_close?: number | null
  quality?: Quality | string
  source?: string | null
  /** MCX: the session the proxy settlement belongs to (PLAN 0.1 #8), never the file date */
  session_date?: string | null
}

export interface QuadrantTapeRow {
  trade_date: string; dprice_pct: number | null; doi: number | null; label: QuadrantLabel | null; mechanical?: boolean
  volume?: number | null; volume_vs_20d?: number | null; volume_avg_sessions?: number | null; churn?: number | null
  /** wave 1c: why there is no quadrant word ('no OI yet (CME file lands T+1 ≈ 15:30 IST)'); MCX: how many sessions the delta spans */
  label_note?: string | null
  sessions_spanned?: number | null; multi_session?: boolean; span_note?: string | null
}

/** `?exchange=MCX&family=GOLDM` — rows, tape and roll are for THAT family; the client sends `sel.family` (API_CONTRACT §2.6). */
export interface GoldPositioningDaily {
  exchange: 'COMEX' | 'MCX'
  family?: Family | string | null
  rows: DailyPositioningRow[]
  quadrant_tape: QuadrantTapeRow[]
  put_call_oi_ratio?: number | null
  roll?: { front?: string | null; next?: string | null; front_oi?: number | null; next_oi?: number | null; ratio?: number | null; days_to_tender_or_fnd?: number | null
           fnd_date?: string | null; ltd_date?: string | null; fnd_source?: string | null; days_unit?: string | null; tender_start?: string | null; note?: string | null
           /** wave 1d: the server clamps days to 0 once the tender has begun and says so (`in_tender`, 'in tender since Sun 01 Nov (5 d)') */
           in_tender?: boolean | null; tender_note?: string | null } | null
  /** "since 27 Oct 2026": the day the history began */
  since?: string | null
  badge?: Badge
  evidence?: string | null
  read?: string | null
  freshness?: Freshness
  as_of?: string
  store_errors?: Record<string, string> | null
}

// ── /api/gold/positioning/mcx-history (p.mcx.history; catalog row BREEZE_DAILY, O-8 6 Nov 2026) ──────────────

/** What ΔOI says happened to positions in the period: OI up = opened, down = closed (exchange OI never says who). */
export type PositionsWord = 'opened' | 'closed' | 'unchanged'

/** One session (D), ISO week (W) or calendar month (M) of ONE contract: its last close and OI vs the previous period's. */
export interface McxHistoryPeriod {
  /** '2026-11-05' (D) · '2026-W45' (W) · '2026-11' (M) */
  period: string
  /** 'Thu 05 Nov' · 'W45 · 02 Nov–05 Nov' · 'Nov 2026' */
  period_label: string
  period_start: string
  /** the period's LAST stored session */
  period_end: string
  sessions: number
  /** W / M: the week / month can still gain a session ('to date') */
  partial: boolean
  close: number | null
  close_chg_pct: number | null
  /** lots */
  oi: number | null
  /** lots, vs the previous period's last OI; null for the first stored period */
  oi_chg: number | null
  /** lots, summed over the period; `volume_missing` sessions had none */
  volume: number | null
  volume_missing: number
  positions: PositionsWord | null
  /** the daily tape's quadrant word (the server's `quadrant_label`, M28) */
  label: QuadrantLabel | null
  /** the period ends in the contract's expiry month (tender from the 1st): OI falls as positions roll — greyed like the tape */
  mechanical: boolean
  /** D: sessions the delta spans (> 1 = the store skipped a session); null for W / M */
  sessions_spanned: number | null
  note: string | null
}

/** A live expiry of the family on its newest stored session: where the open positions sit. */
export interface McxHistoryContract {
  expiry: string
  expiry_label: string | null
  oi: number | null
  share_pct: number | null
  close: number | null
  selected: boolean
}

/** `?family=GOLDTEN&expiry=2026-11-30&window=D|W|M` — the server defaults to GOLD and the family's front live expiry. */
export interface GoldMcxHistory {
  family: Family | string
  expiry: string | null
  expiry_label: string | null
  expiry_source: string
  window: Window
  window_label?: string | null
  /** oldest first */
  periods: McxHistoryPeriod[]
  contracts: McxHistoryContract[]
  contracts_date: string | null
  family_oi: number | null
  since: string | null
  /** '₹ per 10 g' (the family's quotation unit, shared/mcx_specs) */
  unit: string | null
  oi_unit: string
  /** PLAN §f.2 on the server: false → no periods, no contracts, `note` says why */
  published: boolean
  note: string | null
  badge: Badge
  catalog_ids: string[]
  evidence?: string | null
  read: string
  rule: string
  source: string
  quality: string
  freshness?: Freshness
  as_of?: string
  store_errors?: Record<string, string> | null
  /** degraded 200 (data-service away / no rows stored): `ok: false` with the reason */
  ok?: boolean
  error_info?: { code: string; message: string; hint?: string } | null
}

// ── /api/gold/curve (CONTRACTS c.comex / c.mcx) ─────────────────────────────────────────────────

export interface CurvePoint {
  expiry: string
  symbol?: string | null
  settle_or_last: number | null
  source: string
  quality: Quality | string
  open_interest?: number | null
  oi_change?: number | null
  volume?: number | null
  band_lo?: number | null
  band_hi?: number | null
  days_to_expiry?: number | null
  spread_vs_front?: number | null
  annualised_carry_pct?: number | null
  flags?: string[]
  /** COMEX only (wave 1c, C-TRADER-24): that month's first notice / last trade from the CME PRF — a long must leave by FND */
  first_notice?: string | null
  days_to_fnd?: number | null
  last_trade?: string | null
  days_to_ltd?: number | null
  /** the file / fetch date and the SESSION the settlement belongs to (PLAN 0.1 #8) */
  trade_date?: string | null
  session_date?: string | null
  /** wave 1d: where `settle_or_last` came from ('breeze_vwap30' | 'band_midpoint') and the session the band really belongs to */
  settle_source?: SettlementSource | string | null
  band_session?: string | null
}

export interface CurveBasis extends SettlementFields {
  /** the basis block's own names for the settlement (gold.py `_basis_block`): read with `curveBasisSettlement` */
  mcx_front_source?: SettlementSource | string | null
  purity?: number | string | null
  /** wave 1d: the purity of the landed price the basis divides by */
  basis_reference?: BasisReference | null
  mcx_front_inr: number | null
  mcx_front_session?: string | null
  mcx_front_session_label?: string | null
  mcx_front_quality?: string | null
  landed_inr: number | null
  duty_pct: number | null
  duty_effective?: string | null
  duty_notification?: string | null
  duty_note?: string | null
  duty_paid_landed_inr: number | null
  basis_pct: number | null
  /** wave 1c: the settlement-clock basis (the stored MCX_BASIS_PCT row) with its clock named; the live pair beside it only while a quote exists */
  basis_clock?: 'settlement' | string | null
  basis_label?: string | null
  basis_date?: string | null
  basis_source?: string | null
  live_basis_pct?: number | null
  live_basis_label?: string | null
  mcx_live?: number | null
  ts_note?: string | null
  carry_pct?: number | null
  basis_carry_adj_pct?: number | null
  usdinr: number | null
  usdinr_source?: string | null
  ts?: string | null
  badge?: Badge
}

/** `?exchange=MCX&family=GOLDM` — the points are THAT family's chain; the client sends `sel.family` (API_CONTRACT §2.7). */
export interface GoldCurve {
  exchange: 'COMEX' | 'MCX'
  family?: Family | string | null
  date: string
  points: CurvePoint[]
  ghost_1w?: CurvePoint[]
  ghost_date?: string | null
  basis?: CurveBasis | null
  /** MCX: basis / premium history; COMEX: the annualised carry history */
  history?: { trade_date: string; basis_pct?: number | null; premium_pct?: number | null; carry_ann_pct?: number | null }[]
  /** "last trade, not settlement" (Yahoo per-month) until bulletin settlements are allowed; MCX: whose band the settles are */
  price_label?: string | null
  /** MCX (wave 1d, D4): the ONE session the chain's settles belong to (the band's own session), its label, and the OI's session */
  chain_session?: string | null
  chain_session_label?: string | null
  oi_session?: string | null
  since?: string | null
  badge?: Badge
  freshness?: Freshness
  store_errors?: Record<string, string> | null
}

// ── /api/gold/contracts (c.selector) ────────────────────────────────────────────────────────────

export interface ContractExpiryRow {
  expiry: string
  source: 'observed' | 'computed' | string
  settle?: number | null
  settle_quality?: string | null
  /** wave 1d: 'breeze_vwap30' | 'band_midpoint', the settle's session and the session the band belongs to */
  settle_source?: SettlementSource | string | null
  settle_session?: string | null
  settle_session_label?: string | null
  band_session?: string | null
  band_midpoint?: number | null
  band_lo?: number | null
  band_hi?: number | null
  oi?: number | null
  oi_change?: number | null
  margin_inr?: number | null
  margin_pct?: number | null
  margin_source?: string | null
  margin_date?: string | null
  carry_pct?: number | null
  /** 'annualised vs the front expiry (as /curve)' — the one carry convention; null on the front row (C-DATA-16) */
  carry_convention?: string | null
  /** wave 1d: why no carry is printed (front and this expiry settle on different sessions) */
  carry_note?: string | null
  comex_matched?: string | null
  comex_matched_calendar?: string | null
  comex_matched_note?: string | null
  tender_start?: string | null
  days_unit?: string | null
  days_to_tender?: number | null
  days_to_expiry?: number | null
  /** wave 1d: the tender of this expiry has begun (MCX tender period), and the server's words for it */
  in_tender?: boolean | null
  tender_note?: string | null
}

export interface ContractFamily {
  code: Family | string
  name?: string | null
  breeze_code?: string | null
  lot: string
  lot_grams?: number | null
  quote_unit: string
  purity: string
  /** wave 1d: the landed reference its basis divides by, and the session / quality the 1 % move and costs are taken at */
  basis_reference?: string | null
  price_basis?: string | null
  expiry_rule: string
  cycle?: string | null
  expiries: ContractExpiryRow[]
  tick_rupees?: number | null
  tick_value: number | null
  multiplier?: number | null
  round_trip?: { legs?: Record<string, number>; total: number | null; pct: number | null; breakeven_ticks: number | null; price?: number | null; assumptions?: string | null } | null
  one_pct_move_inr?: number | null
  notional_inr?: number | null
  hedge_ratio_oz?: number | null
  delivery_unit?: string | null
  tender_cutoff_note?: string | null
  options?: { available: boolean; expiries?: string[]; strike_step?: number | null; note?: string | null } | null
  notes?: string[] | null
  badge?: Badge
}

/** DES-style spec of the matched COMEX contract (c.spec): gold_cme_prf + gold_margins (C4). */
export interface ComexSpec {
  symbol: string
  mmy?: string | null
  description?: string | null
  sec_type?: string | null
  uom?: string | null
  uom_qty?: number | null
  multiplier?: number | null
  min_px_incr?: number | null
  tick_value_usd?: number | null
  /** PRF DisplayFactor (GC 0.1): MinPxIncr × display_factor = the tick in $/oz as quoted; `tick_usd` when the server already scaled it */
  display_factor?: number | null
  tick_usd?: number | null
  settl_method?: string | null
  settl_method_label?: string | null
  uom_label?: string | null
  init_margin_usd?: number | null
  margin_pct_of_notional?: number | null
  margin_date?: string | null
  ref_price?: number | null
  first_notice?: string | null
  last_notice?: string | null
  last_trade?: string | null
  ltd_end_time?: string | null
  first_intent?: string | null
  elig_block?: boolean | null
  elig_efp?: boolean | null
  margin_history?: { trade_date: string; margin_usd: number | null }[]
  margin_history_note?: string | null
  /** 'DEC-26' from mat_date; `picked_by` says whether the row IS the matched month ('matched month') or a fallback (C-BEGINNER-4 / C-DATA-8) */
  month?: string | null
  picked_by?: string | null
  yahoo_symbol?: string | null
  days_to_first_notice?: number | null
  days_to_last_trade?: number | null
  mat_date?: string | null
  first_trade?: string | null
}

export interface GoldContracts {
  as_of?: string
  exchange: 'MCX' | 'COMEX' | string
  families: ContractFamily[]
  comex_matched_by_family?: Record<string, string | null> | null
  comex_front?: { expiry?: string | null; symbol?: string | null; price?: number | null; source?: string | null } | null
  /** which fields the diff strip compares when the family changes */
  diff_keys?: string[]
  other_exchanges?: { exchange: Exchange; available: boolean; reason?: string | null }[]
  master?: { available: boolean; published?: string | null; session?: string | null; session_label?: string | null } | null
  margin_note?: string | null
  /** `?exchange=COMEX`: the matched month's spec card (c.spec); null until gold_cme_prf is readable */
  comex_spec?: ComexSpec | null
  badge?: Badge
  freshness?: Freshness
  store_errors?: Record<string, string> | null
}

// ── /api/gold/premiums (PHYSICAL; B4B) ──────────────────────────────────────────────────────────

export interface LadderStep { step: string; label: string; value: number | null; ts?: string | null; ts_label?: string | null; source?: string | null; unit?: string | null
  /** D3 (round 2): the quote unit a PETAL (₹/1 g) / GUINEA (₹/8 g) value was scaled FROM, when the server scaled it to ₹/10 g */
  scaled_from?: string | null
  quote_unit?: string | null
  settlement_source?: string | null
  /** wave 1d: the MCX bar's settlement quality / check, its native value and unit (PETAL ₹/1 g …), whether it was scaled to ₹/10 g */
  settlement_quality?: string | null
  settlement_check?: SettlementCheck | null
  value_native?: number | null
  unit_native?: string | null
  scaled_to_10g?: boolean | null
  basis_reference?: BasisReference | null
  reference_value?: number | null
  reference_label?: string | null
  /** wave 1c: the clock of this bar — 'now' | 'fix' | 'settlement' | 'dated constant' — never divide across clocks */
  clock?: string | null }

export interface GoldPremiums {
  india: {
    ladder: LadderStep[]
    premium_pct: number | null
    premium_date?: string | null
    /** wave 1c: the premium is the STORED fix-minute INDIA_PREMIUM_PCT; `premium_note` says when IBJA has a newer fix than the stored premium */
    premium_clock?: string | null
    premium_note?: string | null
    ibja_date?: string | null
    fineness_adjustment?: number | string | null
    basis_pct: number | null
    basis_date?: string | null
    basis_label?: string | null
    basis_source?: string | null
    /** wave 1d: the purity of the landed price the basis divides by, and where the MCX settle came from */
    basis_reference?: BasisReference | null
    settlement_source?: SettlementSource | string | null
    basis_purity_note?: string | null
    unit_note?: string | null
    /** the live-clock pair while a quote exists (both legs 'now'); null otherwise */
    live_basis?: { value: number | null; mcx_live?: number | null; duty_paid_landed?: number | null; as_of?: string | null; label?: string | null; clock?: string | null } | null
    carry_adj_pct?: number | null
    duty: { pct: number; effective: string; notification?: string | null; note?: string | null; history?: { effective: string; pct: number }[] }
    history?: { report_date: string; premium_pct?: number | null; basis_pct?: number | null }[]
    badge?: { ladder?: Badge; premium?: Badge } | Badge
    clock_note?: string | null
    freshness?: Freshness
  }
  shanghai: {
    sge_pm_cny_g: number | null
    usdcny: number | null
    usdcny_source?: string | null
    sge_usd_oz: number | null
    london_pm_usd?: number | null
    comex_at_1415_bj?: number | null
    premium_usd: number | null
    premium_pct: number | null
    ts_sge?: string | null
    ts_ref?: string | null
    /** wave 1c (C-TRADER-5): paired on the SAME report date only; `note` = "awaiting today's PM: …" when today's London PM is not stored */
    pair_date?: string | null
    /** the date of `sge_pm_cny_g` (the pair date's own SGE leg) and a newer SGE print that stands alone until its London PM is stored */
    sge_pm_date?: string | null
    sge_latest_cny_g?: number | null
    sge_latest_date?: string | null
    pairing?: string | null
    note?: string | null
    /** wave 1e (M-C): the USDCNY leg's own date and stored time (its vintage); the premium recomputed from the printed legs, whether
     *  |sge_usd_oz − london_pm_usd − premium_usd| < 0.1, the stored derive when it differs and why */
    usdcny_date?: string | null
    usdcny_as_of?: string | null
    premium_usd_stored?: number | null
    premium_source?: 'legs' | 'stored' | string | null
    reconciles?: boolean | null
    recompute_note?: string | null
    legs_note?: string | null
    history?: { report_date: string; premium_usd?: number | null; premium_pct?: number | null; source?: string | null; stored_usd?: number | null; timing_spike_suspect?: boolean | null }[]
    badge?: Badge
    clock_note?: string | null
    freshness?: Freshness
  }
  reference?: { wgc_india?: number | null; wgc_india_week?: string | null; wgc_china?: number | null; wgc_china_week?: string | null; reuters_url?: string | null; attribution?: string | null }
  as_of?: string
  freshness?: Record<string, Freshness>
  store_errors?: Record<string, string> | null
}

// ── /api/gold/flows (PHYSICAL / MONTHLY; B4B) ───────────────────────────────────────────────────

export interface GoldFlows {
  etf?: { report_date: string; fund: string; tonnes: number | null; chg_1d?: number | null; chg_5d?: number | null; chg_1m?: number | null; chg_ytd?: number | null
          /** the last 30 stored points of this fund (one row per FUND, not per day: API_CONTRACT §2.10) */
          cumulative_30d?: { report_date: string; tonnes: number | null }[] | null; source?: string | null }[]
  wgc_weekly?: { week_ending: string; region: string; flow_t?: number | null; flow_usd_bn?: number | null; holdings_t?: number | null }[]
  wgc_countries?: Record<string, unknown>[]
  wgc_india_holdings_t?: number | null
  /** wave 1c: IMF IFS stores troy ounces — `oz` raw, `oz_mn` = oz ÷ 1e6, `tonnes` = Moz × 31.1035 (C-TRADER-6) */
  official?: { country: string; month: string; oz?: number | null; oz_mn?: number | null; tonnes?: number | null; chg_oz_mn?: number | null; chg_t?: number | null
               chg_12m_oz_mn?: number | null; chg_12m_t?: number | null; unit_note?: string | null }[]
  /** `tonnes` is the IMF's reported ounces for India (C-TRADER-22); `tonnes_est` is a null alias for one release */
  rbi?: { week?: string | null; usd_mn?: number | null; share_pct?: number | null; tonnes?: number | null; tonnes_month?: string | null; tonnes_source?: string | null
          tonnes_est?: number | null; inr_cr?: number | null; note?: string | null } | null
  otc?: { lbma_turnover_usd_bn?: number | null; week_ending?: string | null; turnover_tonnes_est?: number | null; vault_t?: number | null; vault_month?: string | null; vault_chg_t?: number | null
          efp?: { today_rt?: number | null; date?: string | null; avg_20d?: number | null; avg_sessions?: number | null; since?: string | null; avg_note?: string | null
                  pct_of_volume?: number | null } | null; read?: string | null } | null
  physical_monthly?: { sge_withdrawals_kg?: number | null; sge_withdrawals_month?: string | null; india_imports_usd_bn?: number | null; india_imports_month?: string | null
                       india_imports_yoy_pct?: number | null; swiss_exports_in_kg?: number | null
                       amfi?: { net_cr?: number | null; aum_cr?: number | null; month?: string | null; tonnes_est?: number | null; evidence?: string | null } | null } | null
  balance_sheet?: { period: string; series: string; tonnes: number | null }[]
  badge?: Badge
  evidence?: string | null
  attribution?: string | null
  as_of?: string
  freshness?: Record<string, Freshness>
  store_errors?: Record<string, string> | null
}

// ── /api/gold/macro (MACRO; B4B) ────────────────────────────────────────────────────────────────

export interface MacroDriver {
  key: string
  label?: string
  /** 'stand-in: FRED_DTWEXBGS (DXY_CLOSE has no stored points)' when the fallback series is used; the label already names the series (C-DATA-4) */
  label_note?: string | null
  value: number | null
  unit: string
  report_date?: string | null
  d1?: number | null
  d1w?: number | null
  d1m?: number | null
  d_window?: number | null
  change_unit?: string | null
  d1_bp?: number | null
  pct_1y?: number | null
  corr_60d?: number | null
  tag?: GoldDirection | null
  rule?: string | null
  series_id?: string | null
  badge?: Badge
  evidence?: string | null
  state?: FreshState
  /** wave 1d/1e: the twin relation (`same_level` false = a different instrument, e.g. BZ=F vs dated Brent) and quality ('partial') */
  same_level?: boolean | null
  relation?: string | null
  quality?: string | null
  source?: string | null
}

export interface GoldMacro {
  as_of?: string
  window?: Window
  drivers: MacroDriver[]
  kgx?: { period: string; from_date?: string | null; window_label?: string | null; total_pct: number | null; pure_gold_pct: number | null; usd_effect_pct: number | null; inr_effect_pct?: number | null
          weights?: Record<string, number>; badge?: Badge; line?: string | null
          /** wave 1c (C-BEGINNER-14): why the split is empty, in words — print this instead of the identity assertion */
          note?: string | null; inr_note?: string | null }
  currencies?: { ccy: string; price: number | null; unit?: string | null; d1?: number | null; d1w?: number | null; d1m?: number | null; ytd?: number | null; badge?: Badge }[]
  fed?: { meetings: { meeting: string; label?: string | null; kind?: string | null; p_cut?: number | null; p_hike?: number | null; p_hold?: number | null; mean_bp?: number | null; p10_bp?: number | null; p90_bp?: number | null }[]
          as_of?: string | null; source?: string | null; zq?: { month: string; implied_pct: number | null; contract?: string | null; symbol?: string | null; contract_month?: string | null; note?: string | null
                 /** wave 1e (G2-API): the observation date, the month guess, whether the continuous ZQ=F has likely rolled, and EFFR */
                 month_guess?: string | null; observed?: string | null; rolled_suspect?: boolean | null; effr?: number | null }[]; effr?: number | null; effr_date?: string | null; target?: string | null
          /** `next_fomc_ist` is a LABEL ('2026-12-10 00:30 IST'); `next_fomc` is the DECISION only (never a speaker), `speakers` this week's speeches (C-TRADER-12) */
          next_fomc_ist?: string | null; after_mcx_close?: boolean
          next_fomc?: { date_et?: string | null; ist?: string | null; at?: string | null; statement_ist?: string | null; name?: string | null; kind?: string | null
                        source?: string | null; after_mcx_close?: boolean; days?: number | null } | null
          speakers?: { date: string; time_ist?: string | null; title?: string | null; impact?: string | null; kind?: string | null }[]
          badge?: Badge; fedwatch_link?: string | null }
  /** this week's US calendar as `{date, time_ist, title, kind, country, impact, forecast, previous, actual, in_session, days}` (API_CONTRACT §2.11) — NOT /calendar's GoldEvent (`event_date`, `name`); MacroView's MacroCalRow is the local type */
  calendar?: { date: string; time_ist?: string | null; title?: string | null; kind?: string | null; country?: string | null; impact?: string | null
               forecast?: string | null; previous?: string | null; actual?: string | null; in_session?: boolean | null; days?: number | null
               /** wave 1c: ★ only on High impact or an FOMC decision; rows already past are not sent */
               impact_rank?: number; star?: boolean }[]
  move?: { gvz?: number | null; gvz_date?: string | null; sigma_day_pct?: number | null; usd_oz?: number | null; inr_10g?: number | null
           per_lot?: Partial<Record<Family, number | null>>; realised_20d?: number | null; atr14_usd?: number | null; atr14_inr?: number | null; read?: string | null; badge?: Badge }
  driver_health?: { rolling_corr?: { year: string | number; real_yield?: number | null; dxy?: number | null }[]
                    betas_by_regime?: ({ regime?: string; beta_real_yield_per_100bp?: number | null; beta_dxy?: number | null } & Record<string, unknown>)[]
                    /** wave 1c (C-DATA-21): the units of the raw keys, and which dollar series the betas / correlations use */
                    beta_units?: Record<string, string>; dxy_series?: string | null; lesson?: string | null }
  context?: { gsr?: number | null; gsr_pct?: number | null; gpr_m?: number | null; gpr_pct_m?: number | null; gpr_pct_d?: number | null; hy_oas?: number | null; hy_oas_date?: string | null
              gold_m2_pct?: number | null; badge?: Badge }
  badge?: Badge
  freshness?: Record<string, Freshness>
  store_errors?: Record<string, string> | null
}

// ── /api/gold/calendar · /log · /brief · /learn ─────────────────────────────────────────────────

export interface GoldCalendar { as_of?: string; days?: number; count?: number; events: GoldEvent[]; badge?: Badge; freshness?: Freshness; store_errors?: Record<string, string> | null }

export interface GoldLogRowX {
  date: string; snapshot_at?: string; contract?: string; expiry?: string; comex_symbol?: string; baseline?: number; baseline_source?: string; baseline_session?: string
  fair_open?: number; threshold?: number; duty_pct?: number; comex_ref?: number; comex_now?: number; inr_ref?: number; inr_now?: number
  actual_open?: number; actual_source?: string; captured_at?: string; error?: number; naive_error?: number; event_risk?: number
  stale_baseline?: boolean; inputs_json?: string | null
  /** D2 (wave 1d): the row's settlement check — its baseline vs the last-30-min VWAP of the session it was labelled with;
   *  null = not run yet (no VWAP for that session). Stored numbers are never rewritten, only flagged and re-explained. */
  baseline_check?: (SettlementCheck & { threshold_pct?: number | null; compared?: string | null }) | null
  labelled_session_vwap30?: number | null
  baseline_session_label?: string | null
  /** wave 1d (G-API): why the row is stale ('band_rule' | 'vwap30_check' | 'older_session' | 'recorded') and the counterfactual
   *  fair / misses had the baseline been the labelled session's last-30-min VWAP (never the scored number) */
  stale_reasons?: string[] | null
  re_explained?: { labelled_session?: string | null; labelled_session_vwap30?: number | null; session_move_pct?: number | null; fair_open_on_vwap30?: number | null
                   error_on_vwap30?: number | null; naive_error_on_vwap30?: number | null; note?: string | null } | null
}
export interface GoldLogStatsX {
  days: number; mean_abs_error?: number; median_abs_error?: number; bias?: number; within_threshold_pct?: number
  naive_mean_abs_error?: number | null; p90_abs_error?: number; p90?: number; threshold?: number
  /** D2: the stale rows NAMED, the rows whose check could not run yet, the rule, and the same stats without the stale rows */
  stale_baseline_count?: number; stale_baseline_dates?: string[]; stale_baseline_unknown?: string[]; stale_baseline_rule?: string | null
  excluding_stale?: Omit<GoldLogStatsX, 'excluding_stale'> | null
  /** the counterfactual on the corrected baselines (the same mornings priced off each labelled session's VWAP30): not the score */
  on_vwap30?: { days?: number | null; mean_abs_error?: number | null; median_abs_error?: number | null; naive_mean_abs_error?: number | null
                within_threshold_pct?: number | null; dates?: string[] | null; note?: string | null } | null
  stale_by?: Record<string, string[]> | null
}
export interface GoldLog { rows: GoldLogRowX[]; stats: GoldLogStatsX; badge?: Badge; source?: string | null; read?: string | null }

/** `/brief` (API_CONTRACT §2.13): the headline fields sit at the TOP level beside the raw `doc{}`. */
export interface GoldBrief {
  available: boolean
  report_date?: string | null
  generated_at?: string | null
  bias?: string | null
  bias_score?: number | null
  confidence?: number | null
  model_fair_open?: number | null
  /** wave 1c: no trade-implying field leaves the server (open_signal is gone); the dropped paths are listed here */
  stripped_fields?: string[] | null
  overnight_summary?: string | null
  open_plan?: string | null
  key_risks_today?: string[] | null
  doc?: Record<string, unknown> | null
  data_quality?: Record<string, unknown> | null
  label?: string | null
  badge?: Badge
  note?: string | null
  store_errors?: Record<string, string> | null
}

/** `aliases` (C-BEGINNER-11): MM → managed money, OI → open interest, FND → first notice day … resolved by lib/gold/learn `lookupTerm` */
export interface GlossaryTerm { term: string; short: string; long?: string; see_also?: string[]; aliases?: string[] }
export interface GoldGlossary { terms: GlossaryTerm[]; count?: number; version?: string; query?: string | null; dangling_see_also?: string[]; source?: string | null }
export interface GoldTooltips { tooltips: Record<string, string>; count?: number; version?: string; panels?: string[]; source?: string | null }

export interface GoldCatalog { rows: CatalogRow[]; as_of?: string; count?: number; verdicts?: Record<string, number>; badges?: Record<string, number>; store_errors?: Record<string, string> | null }

// ── the four instruments (PLAN 0.1 #8): every price on the page says which one it is ────────────

export const INSTRUMENTS = {
  spot: 'spot proxy',
  front: 'COMEX front GC1',
  matched: 'COMEX matched month',
  mcx: 'MCX GOLD',
} as const
export type InstrumentKey = keyof typeof INSTRUMENTS
