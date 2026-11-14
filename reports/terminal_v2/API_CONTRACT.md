# Terminal v2 — the ui-api contract as implemented (B3-API, Wave 1, 5 Nov 2026)

What `services/ui-api/routers/{derivatives,markets,options_strategy,data_health,positions}.py` actually return for
PLAN 1.1–1.4, plus `shared/breeze_budget.py`. B4 builds against this file, not against PLAN §1; every deviation from the
plan is listed in §7. Source of truth for shapes: `services/ui-api/tests/test_terminal_v2_api.py` (data-service and
master-controller mocked through the process-wide client; Breeze faked; the real-format NSE SPAN subset
`tests/fixtures/span_nsccl_20261104_subset.xml`), and **§8**, the key inventory GENERATED from those fixtures by
`tests/test_terminal_v2_contract.py`: the test fails whenever this document and the code disagree (regenerate with
`TERMINAL_CONTRACT_WRITE=1`).

## 0. Rules every route obeys (PLAN §0)

- **Store, then show. No publisher on the request path.** Every stored number comes from data-service `/db/*` through
  one stale-while-revalidate cache per family (`SWRCache("derivatives.iv")`, `("market.index_drivers")`,
  `("data_health.inputs")`: refresh 60 s, bound 600 s) over the process-wide `httpx.AsyncClient`
  (`shared.http_client.get_json`, PLAN 1.5). `test_request_path_never_leaves_the_loopback` calls every route under a
  fake transport and asserts the set of hosts reached is ⊆ {localhost, 127.0.0.1}; the same test proves the recorder
  sees a publisher host when one is reached (negative control). The only non-loopback host literal in the routers is
  the SPAN file's documented origin in a docstring; `test_routers_name_no_publisher_host` scans for the forbidden list.
- **Degrade the block, never the page.** A data-service failure (down, 404 = B1's tables not deployed, bad body) is
  remembered 15 s per path; the route answers 200 with empty rows, `ok: false` and `store_errors{path: reason}`.
- **Headers:** `X-Cache` (hit | stale | miss | bypass) and `X-Cache-Age` (seconds, the oldest stored piece) on every
  store-reading route. Never in the body.
- **Badges, not colours.** Every derived number carries `arithmetic` / `context` / `heuristic` in `badge` / `badges`.
  **No route serves `signal`** (none exists; `test_every_route_in_the_inventory_carries_a_badge_or_badges`). Context
  metrics are never worded bullish/bearish. No composite score, no `score` key.
- **Rank AND percentile, each defined** (`definitions{}` on every payload that carries them; Wave 0.6 server side on the
  legacy `/api/market/option-history/{symbol}` too).
- **Sentences end "describes, does not predict"** (`note`, `driver.sentence`, the timeline note, the health note).
- **Point-in-time.** Revisions are new rows by `computed_at` / `first_seen_at`; the routes take the latest revision per
  date (`test_drivers_fit_state_and_sentence`: an older `computed_at` row never wins). Daily data shows its date
  (`as_of = YYYY-MM-DD`), never a clock; the only clocks are the margin route's `as_of` when Breeze answered and the
  health view's `as_of` (IST with offset).
- **Trading rules frozen; PAPER ONLY.** Nothing here is read by `momentum.py`, `decision_desk.py`, the S1 shadow, a
  directional alert or a ticket price. `/api/desk/attribution` reads the paper ledger and writes nothing. The margin
  route prices only (`paper_only: true`); no order route exists.
- **Breeze budget is one module.** Every Breeze SDK call in ui-api runs inside `shared.breeze_budget.ledger().guard(
  caller, method)` (`positions._breeze_call` — holdings, positions, funds and the trade-history route's
  `get_order_list` —, the client's `generate_session` login, the margin route); a call past the cap raises
  `BudgetExceeded` BEFORE the SDK runs (`/api/positions/trade-history` then answers 200 `ok: false, error_kind:
  "budget"`; a refused login is error kind `budget`, retried after a minute). Counters: `GET /api/positions/breeze-budget`.
  (ICICI's `probe_breeze_connection` in `icici_admin.py`, the BRKR connection probe, is outside these routers and still
  logs in unmetered — open item.)
- **Errors:** `errors.fail` → `{detail: str, error: {code, message, hint?}}` (422 for bad symbols / enums).
- Timestamps are ISO; dates are `YYYY-MM-DD`; numbers are numbers (`null` when unknown).

## 1. Route index

| Route | Cache | Reads (data-service, B1 contract §6) |
|---|---|---|
| `GET /api/derivatives/iv/{symbol}?days=750&series=iv30_cm` | SWR 60/600 s | `/db/iv/summary`, `/db/iv/vix` (indices only), `/db/iv/events` |
| `GET /api/derivatives/iv/{symbol}/surface?date=&compare=1w\|1m\|3m` | SWR | `/db/iv/expiry`, `/db/iv/surface` (× 2 with `compare`) |
| `GET /api/derivatives/iv/{symbol}/cone` | SWR | `/db/iv/summary` (5 y), `/db/iv/expiry` (today's term) |
| `GET /api/derivatives/iv/{symbol}/events?n=8` | SWR | `/db/iv/events` |
| `GET /api/derivatives/iv/{symbol}/intraday?date=` | SWR | `/db/iv/intraday` |
| `GET /api/derivatives/vol-screen?sort=iv_pctile\|iv_rank\|iv_minus_rv\|term_slope\|skew&results_within=` | SWR | `/db/iv/screen` |
| `GET /api/market/option-history/{symbol}` (legacy, + rank/percentile) | none (process-wide client, `errors.fail` mapping) | `/db/option-history/{symbol}` |
| `GET /api/market/index-drivers?index=NIFTY 50&horizon=1d\|5d\|1m\|3m\|ytd\|since_change&window=20\|60` | SWR | `/db/index-drivers/{contribution,fit,state,weights}` |
| `GET /api/market/index-drivers/timeline?index=&window=&days=` | SWR | `/db/index-drivers/state` |
| `GET /api/market/index-drivers/monthly?index=&months=12` | SWR | `/db/index-drivers/{contribution,fit}` |
| `GET /api/desk/attribution?horizon=` | SWR (desk 60/600 s) | the paper ledger (`routers.desk.get_desk().status()` on a thread) + `/db/index-drivers/*` + `/db/security/{sym}/history` |
| `POST /api/options/margin` | none | Breeze (live session, ledger) → `data/nse_archive/span/nsccl.YYYYMMDD.s.zip` (disk) → heuristic |
| `POST /api/options/strategy/analyze` (v2: per-leg `days` / `forward` / `expiry`; `scenario_days`, `iv_shift`, `grid`, `pop_iv`, `slippage_per_unit`; `kind: EQ`) | none | arithmetic only (options_math Black-76; shares costed by `shared/trading_costs.py`) |
| `GET` · `POST /api/options/strategy/saved`, `DELETE /api/options/strategy/saved/{id}` | none | ui-api SQLite `data/paper_fo.sqlite` (`fo_saved_structures`) |
| `GET /api/options/book` (`/list`) · `POST /api/options/book` · `POST /api/options/book/close` · `POST /api/options/book/roll` · `GET /api/options/book/marks` · `POST /api/options/book/mark` · `GET /api/options/book/greeks` · `GET /api/options/book/journal` | chains TTL 60 s (live) / 600 s (EOD) | `/db/option-chain/{symbol}?expiry=`, `/db/option-chain-live/{symbol}?expiry=` + `data/paper_fo.sqlite` (PAPER ONLY, §4a) |
| `GET /api/risk/fo?mode=&margin=` | history 30 min · margin 10 min | the paper book + `/db/index-ohlc/{index}` (fallback `/db/index-daily`), `/db/security/{sym}/history`, `POST /api/options/margin` in-process |
| `GET /api/data/health?page=` | SWR 60/600 s | `/db/data-health` (B1) + `/db/market-holidays` + master-controller `/api/scheduler/status`; until B1 is deployed (404): `/db/nse-positions-meta`, `/db/freshness`, `/db/archive-meta`, `/db/data-health/ingest-log` and the built-in seed |
| `GET /api/positions/breeze-budget` | none | the SQLite ledger |

## 2. IV history (PLAN 1.1)

`/iv/{symbol}` returns the `iv_summary_daily` rows (ascending, `SUMMARY_FIELDS`), `vix[]` from `vix_daily` (the ONE VIX
source; indices only), `events[]` markers (`results` from the crush ledger, `expiry` where the monthly expiry rolls —
Budget / RBI / US-data markers wait for the owner's clarification in PLAN Appendix C and are never guessed),
`rank{iv_rank_252, iv_pctile_252, stored{…}, window_sessions, window_target, on}` recomputed from the stored `iv30_cm`
over the last 252 sessions whatever `days` the chart asks for (the read takes max(days, 252) rows; `window_sessions` =
the observations actually used, < 252 only while the store holds less history) beside the stored values (`test_iv_rank_and_percentile_are_distinct_and_match_the_r_iv_fixture`: 12.81 on 4 Nov 2026 → rank
≈ 21, percentile ≈ 60, R-IV §3), `definitions{}`, `badges{iv, rank, pctile, rv: arithmetic; spread, skew, term:
context; vix: arithmetic}`, `model_version`, `r_source`, `since`, `sessions`, `precedent`.

`/surface` returns `expiries[]` ascending by expiry (the expiry-day row first, `near: false` when `dte ≤ 2`), each with
the per-expiry row (`EXPIRY_FIELDS`), `smile[]` sorted by `log_moneyness` with only traded strikes (`untraded_strikes`
counts the rest), and `compare{requested, as_of, expiries[]}` (the ghost surface; `as_of` is the stored date nearest
the request that data-service answered with). `/cone` returns `years[]` (1/3/5 years × `iv30_cm`/`iv60_cm`/`iv90_cm`:
min / p25 / p50 / p75 / max / n) + `today{}` + `term_today[]`. `/events` returns the ledger newest first. `/intraday`
returns `points[]` per snapshot of the NEAR expiry (ATM by the parity strike, `atm_iv` = mean of both sides, NSE's IV
beside ours, `straddle`, `pcr`, `n_strikes`) and `source` = BREEZE / NSE / OFFLINE. `/vol-screen` sorts nulls last and
`results_within=N` keeps names with `next_results` inside N days (`results_in_days` added).

## 3. Index drivers (PLAN 1.2)

Points are additive, so a horizon is a sum: `members[]` (symbol, industry, weight_pct on the last session of the
window, compounded `ret_pct`, `points`, `share_abs`, `flag`), `sectors[]`, `concentration{top5_abs_share, hhi_contrib,
weight_hhi, effective_n, top5_weight_pct}`, `breadth{ew_pct, cw_pct, ew_minus_cw_pp, up, down, word}` (narrow < −1 pp,
broad > +1 pp, else even), `index_move_pts` (Σ actual), `explained_pts` (Σ points), `residual_pts` (shown, never
hidden), `fit{mae_60s, r2_60s, residual_today, degraded (MAE > 25 pts), sessions, note}`, `weight_method{method, label}`,
`driver{window, leader, tenure, leader_share, changed_from, change_date, …, sentence}`, `history_since`, `badges`.
`since_change` uses the 20-session driver's `change_date` (falls back to 20 sessions). `/timeline` returns one point per
date (the latest `computed_at` per date wins) and `changes[]`; `/monthly` the leaderboard (leader by |points|, top-3
add / drag, `leader_changed`).

`/api/desk/attribution`: `{risk_off: true, since}` when the paper book has no lots (today: "book = liquid fund since
<date>; nothing to attribute"); otherwise `rows[]` of real lots × stored closes in `pp_of_nav` (NAV at the window's
first session) and `book_pp`; `nifty{index_move_pts, explained_pts, top5_add, top5_drag}` over the same window.

## 4. Margin (PLAN 1.3)

`POST /api/options/margin` body: `{symbol, legs[≤4]{side, kind CE|PE|FUT, strike, expiry YYYY-MM-DD, premium, lots,
lot_size}, exchange_code: "NFO", forward?, stock_code?, sources?}`. Fallback chain, in order, each attempt listed in
`attempts[]{source, ok, reason}`:

1. `BREEZE` — `breeze.margin_calculator(list_of_positions, "NFO")` when `positions._get_breeze_client()` yields a live
   client, inside `ledger().guard("ui-api.margin", "margin_calculator")`; `span_margin_required`,
   `non_span_margin_required`, `order_value` from `Success{}`. A refused budget, an SDK error or an answer without a
   margin block are failed attempts (never a 5xx).
2. `NSE_SPAN_FILE` — the newest `data/nse_archive/span/nsccl.YYYYMMDD.s.zip` (`SPAN_ARCHIVE_DIR` overrides), the
   CME SPAN expanded-XML format 4.00 NCL publishes (verified on nsccl.20261104.s.spn, 51 MB: `futPf`/`oopPf` per
   underlying, one `series` per expiry, one `opt` per strike × C/P, each with a 16-scenario risk array in ₹ per unit
   for a long position, positive = loss; `ccDef` with the flat calendar-spread charge (`dSpread`, ₹424 per NIFTY
   spread) and the short-option-minimum tiers (0 for NIFTY)). `span_margin_required` = max(scanning risk + calendar
   spread charge, short option minimum); `detail{scanning_risk, worst_scenario (1-based), scenario_losses[16],
   calendar_spread_charge, spreads[], short_option_minimum, net_delta_by_expiry, net_option_value, file, file_date,
   settlement_file, exposure{}}`. `non_span_margin_required` is NSE's published exposure rule (index 2 %, stock 3.5 % of
   short / futures notional), labelled `heuristic` inside `detail.exposure`. One parse per (file, underlying) is memoised.
3. `HEURISTIC` — `options_math.margin_estimate` (12 % of notional per short leg + premium) with
   `error_factor_measured: 4.8` and the evidence sentence (₹3.9 L vs Breeze SPAN ₹81,497.07 on the NIFTY 09-Nov-2026
   iron condor, R-OPTIONS §3.3) in `note`; `badge: heuristic`.

Every answer carries `source`, `source_chip` (BREEZE / NSE SPAN FILE / HEURISTIC), `span_margin_required`,
`non_span_margin_required`, `total_margin`, `heuristic{}` (always, labelled), `badge` (`arithmetic` for 1–2),
`paper_only: true`. `/strategy/analyze` keeps its ESTIMATE block and now prints `error_factor_measured: 4.8` and the
pointer to this route.

## 4a. OSTR v2 and the PAPER F&O book (PLAN 2.2, Wave 2 — W2-BOOK, 6 Nov 2026)

**PAPER ONLY.** No route here names a broker order method (`tests/test_fo_book.py` scans the four modules, with a planted
negative control); every request model takes `mode: "paper"` only (anything else → 422 "PAPER ONLY", whatever
`EXECUTION_LIVE_ALLOWED` says — there is no live mode to enable); `paper_fo_positions` / `paper_fo_structures` carry
`CHECK (mode = 'paper')`. The only broker method reachable is the read-only `margin_calculator`, through
`POST /api/options/margin`'s ledger guard, for the RSK margin figure. Nothing here feeds the Desk, the S1 shadow, an alert
or a ticket price.

`POST /api/options/strategy/analyze` (v2, backward compatible): legs may carry `days`, `forward` (that expiry's chain
forward; FUT: the future; `kind: "EQ"` shares: spot) and `expiry`; body adds `scenario_days`, `iv_shift`, `grid`,
`pop_iv`, `slippage_per_unit`. A spot move x moves every leg's reference by the same ratio (stated). New keys:
`multi_expiry`, `nearest_expiry_days`, `time_convention`, `extremes_basis`, `payoff[].scenario`, `scenario{}`,
`pop{value %, iv_used, horizon_days, profit_bounds[], badge: heuristic, method, note … "describes, does not predict."}`,
`grid{spot_pct[11], spot[], iv_shift[9], days[], pnl[day][spot][iv], badge: arithmetic, note}` (when `grid=true`),
`greeks.net_units{delta_lots, delta_inr_per_1pct, gamma_pnl_1pct_inr, lot_size}`,
`costs.display{items[[name, ₹]], total (= the sum of the items), exact_total, note}`, `costs.exercise_stt{value,
rate_pct 0.125, at_forward}`, `costs.spread{value, per_unit_per_side, badge: input}`, `costs.equity` (shares: the delivery
round trip from `shared/trading_costs.py`), `margin.excludes_shares`. A mixed-expiry book's breakevens are root-found on
the nearest-expiry curve (later legs by Black-76) and its max P&L is read on the plotted range with the upside tail from
the net call / futures slope (a basis drift under 5 % of a leg's units is not "unlimited").

`GET /api/options/strategy/saved?symbol=` · `POST /api/options/strategy/saved {name, symbol, legs[≤4]{side, kind, strike,
expiry, premium, iv, lots, lot_size, price_source}, note}` (upsert by name + symbol) · `DELETE /api/options/strategy/saved/{id}`
— saving books nothing.

`/api/options/book` (store `data/paper_fo.sqlite`, `PAPER_FO_DB` overrides; tables `paper_fo_structures`,
`paper_fo_positions`, `paper_fo_marks`, `paper_fo_journal`, `fo_saved_structures`):
- `POST ""` `{symbol, name?, legs[≤4]{side, kind CE|PE|FUT, strike, expiry, premium, iv?, lots, lot_size, forward?,
  price_source}, note?, source, mode: "paper"}` → `{structure{…, positions[]}, paper_only}`; shares (`EQ`) → 422 (they live
  in the cash book). The fill is the premium sent and its `price_source` (chain + date, or "edited by hand on OSTR");
  `entry_costs` = the entry side of the F&O statutory schedule.
- `GET ""` / `GET /list` `?status=open|closed|all&mode=auto|eod|live` → `{structures[]{…, positions[]{…, mark, pnl{unrealised,
  realised, costs, net}, greeks{delta, gamma, theta_day, vega, delta_inr_per_1pct, gamma_pnl_1pct_inr}, days_to_expiry},
  summary{entry_cashflow, net_label, pnl_gross, pnl_unrealised, pnl_realised, costs, pnl_net, marks_complete, max_profit,
  max_loss, pct_of_max_profit, loss_x_credit, nearest_expiry, open_legs}}, open_positions, greeks{by_underlying[]{symbol,
  lot_size, positions, delta, delta_lots, gamma, theta_day, vega, delta_inr_per_1pct, gamma_pnl_1pct_inr, forward},
  total{theta_day, vega, delta_inr_per_1pct, gamma_pnl_1pct_inr}, total_note}, totals{}, marks_meta{requested, used,
  notes[], chains[]}, mark_source{state delayed|closed|offline, source, as_of}, time_convention, capital{value, source},
  badges, paper_only, note}`. Units never add across underlyings: the total is ₹ only.
- Marks: in session (`auto` between 09:15 and 15:30 IST on a weekday, or `live`) NSE's live chain through
  `/db/option-chain-live/{symbol}?expiry=` (a chain dated another day, or a failure → EOD with the reason in
  `marks_meta.notes`; in session that read reaches NSE through data-service's paced client, cached 30 s there and 60 s
  here); else `/db/option-chain/{symbol}?expiry=` (the F&O bhavcopy close, settlement where untraded — the file the IV
  surface is computed from). A chain served for another expiry never marks a position. IV is implied from the mark by
  Black-76 on the chain's forward at the chain's own T (`t_days`; the same rule computed here when absent): review M04's
  app-wide `cal365-1530` — calendar time to 15:30 IST on expiry ÷ 365, whole days at end of day, fractional in session,
  no half-day (`fo_book.t_days` = `fo_iv.black76.t_years` × 365), so the book's IV for a contract is the chain's.
  `mark_method`: `close` / `live` / `future` (the near monthly's traded future) / `parity-forward` / `model` (strike
  outside the chain window: Black-76 at the nearest strike's IV, heuristic) / `settlement` (an expired contract at NSE's
  final settlement: intrinsic on the underlying's close ON the expiry day — the expiry-day chain's underlying price, kept
  with the stored EOD marks, else `/db/index-ohlc/{index}` · `/db/index-daily` · `/db/security/{sym}/history` for that
  date; never a later spot; Greeks 0, no margin, no scenario P&L) / `expired-unsettled` (heuristic: that close is not
  stored yet; the last mark on or before the expiry is shown and a close at it is refused, 409).
  EOD marks are appended (an unchanged close is not re-written; a revised one is a new row with its own `first_seen_at`);
  session marks at most every 15 min; settlements derived from stored data are recomputed on read, never stored. A read
  of a book that does not exist yet answers empty and creates no file.
- `POST /close {position_ids | structure_id, prices?{id: ₹ ≥ 0} (labelled "edited by hand at close"), confirm?{id: {price,
  source}} + previewed_at (the previewed fills, confirmed as shown: "… · confirmed as previewed at HH:MM IST"), mark_mode,
  preview, mode: "paper"}` → `{preview, as_of, fills[]{position_id, exit_price, exit_price_source, exit_costs, basis, pnl},
  closed?}`; 404 when nothing open matches; 409 when a leg was closed meanwhile (another window) or an expired leg has no
  settlement yet; a negative price → 422 (and `CHECK (exit_price >= 0)`); an expired leg pays only the exercise STT
  (0.125 % of the settlement value of a long ITM option); a structure closes when its last leg does.
- `POST /roll {position_ids[≤8] (one underlying), to_expiry, strike_shift, confirm?{id: {close_at, close_source, open_at,
  open_source}} + previewed_at, mark_mode, preview (default true), mode}` → `{preview, as_of, legs[]{position_id, close_at,
  close_source, open_at, open_source, new_strike, cash, costs}, net_cash, net_label, costs, closed?, opened?}`; closes at
  the mark (status `rolled`, `rolled_to`) and opens the same side / kind / lots at the target chain's price (`rolled_from`),
  one transaction; an unlisted expiry, the same expiry, a strike outside the target window or an expired leg → 422; a
  leg closed meanwhile → 409.
- `GET /marks?mode=&history=` · `POST /mark?settle=true` (store today's EOD marks, idempotent; with `settle` (default)
  close every expired leg at its `settlement` mark, journal action `settle`, `settled[]` in the answer; for the evening
  scheduler) · `GET /greeks?mode=` · `GET /journal?limit=`.

`GET /api/risk/fo?mode=&margin=true` (routers/riskdash.py → `fo_book.risk_payload`): `{empty, message?, open_positions,
greeks{…}, var{delta_gamma{method, var95_1d_inr, es95_1d_inr, var99_1d_inr, es99_1d_inr, sessions}, full_revaluation{…},
from, to, covered[], excluded[], history_source{}, badge, note}, scenarios{iv_shock[]{iv_shift, pnl_inr},
gap[]{spot_pct, pnl_inr}, combined[]{spot_pct, iv_shift, pnl_inr}, theta_1d_inr, badge, note}, margin{by_underlying[]{symbol,
total_margin, sources[], chunks[], badge, note}, total_margin, capital, utilisation_pct, badge, note}, capital{value,
source}, notes[], vega_total_inr, theta_total_inr, paper_only}`. Delta-gamma VaR: Δ·dS + ½Γ·dS² per underlying on each of
the last 750 common sessions (indices: `/db/index-ohlc/{NIFTY 50|NIFTY BANK|…}`, fallback `/db/index-daily`; stocks:
`/db/security/{sym}/history` change), IV held, plus one day of theta; the full Black-76 revaluation beside it. Scenarios
are instant full revaluations. Margin: `POST /api/options/margin`'s chain per underlying in ≤ 4-leg chunks per structure
(no offset across chunks, stated), cached 10 min per contract set (side, kind, strike, expiry, lots, lot size — never
the mark, so in session an RSK refresh spends at most one Breeze margin call per chunk every 10 min); expired legs are not
margined; capital `PAPER_FO_CAPITAL` (default ₹10,00,000, labelled).

`GET /api/risk/dashboard` gains `size=desk|nav|custom` (+ `notional=` ₹ for custom; default `desk`: the ledger's
`config.equity_share`, 66 %) and `sizing{mode, equity_share, nav_inr, notional_inr, per_name_inr, label}`; VaR "% of
book" stays against the full NAV. `ladder.rules` lists the Desk rules only; `ladder.legacy_rules` carries the legacy
5-day −2 % daily halt, labelled; `stress[]` adds `names_total`, `names_covered`, `partial`.

## 4b. Alerts (PLAN 2.3, Wave 2 — W2-ALERTS, 6 Nov 2026)

Router `services/ui-api/routers/alerts.py` (mounted at `/api/alerts`, unchanged); the rule model, series catalogue and
evaluator are pure (`services/ui-api/alert_engine.py`). Storage: ui-api SQLite `data/alerts.sqlite` (`alert_rules`,
`alert_fires` append-only, `alert_meta`; WAL), mirrored to `data/price_alerts.json` for the legacy price levels.

| Route | Answer |
|---|---|
| `GET /api/alerts` · `PUT /api/alerts/{sym}` | the legacy price levels `{alerts, history}` (unchanged) |
| `POST /api/alerts/run?scope=all\|live\|eod&dispatch=0\|1` | `{hits, checked, priced, fires[], rules_checked, scope}` + `dispatch[]` (dispatch=1) or `page_notify` (dispatch=0) |
| `GET /api/alerts/series` | `{kinds[{kind, name, label, unit, badge, cadence, params, optional, ops, source, group, definition, example}], ops, op_words, …}` |
| `GET /api/alerts/rules?origin=&symbol=` · `POST /api/alerts/rules` · `PUT /api/alerts/rules/{id}` · `DELETE /api/alerts/rules/{id}` | rules with `summary, label, condition, unit, badge, cadence, source, state, last_fired_at` (422 + the reason) |
| `PUT /api/alerts/rules/{id}/action` `{action: snooze\|resume\|pause\|delete, minutes}` · `PUT /api/alerts/rules/from-text` `{text}` | the rule · always 200 `{ok, rule\|error}` |
| `GET /api/alerts/rules/evaluate?ids=` | dry run `{rows[{id, value, as_of, source, metric, satisfied, reason, unit, badge, history_n}]}`: no state change |
| `GET /api/alerts/fires?symbol=&limit=&origin=` | `{fires[], groups[{symbol, count, last_at, fires}], count, as_of}` |
| `GET /api/alerts/feed?limit=` | the scheduler's notifications (`data/notifications.jsonl`) |

**Badges**: every series and fire carries `arithmetic` or `context`; no `signal` exists; no composite score; no template,
label or note carries a direction word (the note scan also refuses predictive phrasing; position names such as a long or
short straddle pass). **Delivery is at most once**: a `dispatch=1` run marks the fires it returns before the controller
delivers them; a fire unclaimed for 30 min is `expired`. **Reads**: stored series through data-service
(`/db/iv/summary`, `/db/option-chain/{sym}`, `/db/fo/basis-history`, `/db/vix-daily`, `/db/index-drivers?index=NIFTY 50|NIFTY BANK`,
`/db/gold/health-daily`) and four routes that can start a refresh of their own (`/db/fii-dii-cash`, `/db/events`,
`/db/surveillance`, `/db/fo/rollover`), which `POST /run` skips inside the restart freeze windows (07:45–09:20,
18:30–21:15 IST); quotes from the live NSE hub only (never Yahoo). Units: OI at a strike in contracts (OMON's unit);
IV − RV20 is close-to-close (`iv_minus_rv20`, catalog `IV_MINUS_RV20`). Nothing here feeds the Decision Desk, the S1
shadow, a ticket price or an order (PAPER ONLY).

## 5. Data health (PLAN 1.4)

`GET /api/data/health` → `{as_of, rows[], summary{green, amber, red, gaps, unknown, rows}, last_session, catalog_source,
inputs_unavailable{}, controller_online, status, service, data_service{reachable}, note, badge, ok}`. A row:
`{id, label, pages[], publisher, published_ist, expected_by, as_of, lag_sessions, state, unrecoverable, job_id,
last_run{ts, status, ms}, next_run, catchup_at, note, dictionary_anchor, badge, max_age_sessions}`.

Two sources (`catalog_source` says which):

1. **data-service `/db/data-health`** (B1 `dataset_catalog`, deployed): B1 computes as-of / lag / state where the tables
   live (`MAX(column)` per table, dated archive files, NSE trading-day deadlines `expected_by` on the session +
   `expected_offset_days` trading days, the `data_gaps` rows) and ui-api keeps that state, adding the job's
   `last_run` / `next_run`, `catchup_at` and the honest sentence. Rows B1 reports `unknown` (`freshness_kind =
   endpoint`, `cadence = live`) are completed here: a row with an ingest job is `fresh` when the job's last run was ok
   on or after the session it must cover by now (the latest session whose `expected_by` deadline has passed, trading-day
   aware), `amber` when it failed or is older, `red` when it never ran; a never-stored live feed
   with no job is `live` (its age is the page's SourceChip); a job the controller does not schedule stays `unknown`
   (counted in `summary.unknown`, never guessed green).
2. **the built-in seed** of R-DATA §3's evaluable rows (until B1's package answers; a 404 there is not an input
   failure), classified by `classify`: trading-day aware through `/db/market-holidays` (`last_session` = the last
   session whose 15:30 has passed); `fresh` when nothing is missing or the latest session is not yet due
   (`expected_by`, IST; a morning slot or a T−1 file is due on the NEXT TRADING DAY — Friday's MTF file on Monday
   23:00, a Thursday-before-holiday file on the next session); `amber` when due and ≤ `max_age` sessions behind; `red`
   beyond `max_age` or nothing stored; `gap` when `ingest_log` carries a `status: gap` row for the last session.

States: `live | fresh | amber | red | gap | unknown`. Rows sort gap → red → amber → unknown → fresh → live, then by lag.
The note is the honest sentence ("stored 30 Oct · expected by 21:00 · 4 sessions behind"). `catchup_at` = the next run
of a catch-up job while the row is amber / red. `?page=DERV` filters by terminal page.

## 6. What B1 must serve (data-service `/db/*`, built against PLAN 1.1 / 1.2 table names)

Rows in any of `{rows:[…]}`, `{data:[…]}`, `{columns, data}` or a bare list; dates `YYYY-MM-DD`; a 404 while a package
is not deployed is tolerated (the block degrades).

| Path | Params | Rows (table) |
|---|---|---|
| `/db/iv/summary` | `symbol`, `days` | `iv_summary_daily` (+ `model_version`, `r_source` on the payload or the rows), ascending |
| `/db/iv/expiry` | `symbol`, `date?` (default latest) | `iv_expiry_daily` for that date |
| `/db/iv/surface` | `symbol`, `date?` | `iv_surface_daily` for that date (`expiry, strike, opt_type, iv, delta, log_moneyness, oi, volume, price_source`) |
| `/db/iv/events` | `symbol`, `n` | `iv_event_log` |
| `/db/iv/intraday` | `symbol`, `date?` | `iv_intraday` (`ts` with offset, `expiry, strike, opt_type, mid, iv, nse_iv, oi, source`) |
| `/db/iv/vix` | `days` | `vix_daily` |
| `/db/iv/screen` | — | latest `iv_summary_daily` per symbol + `next_results`, `ban`, `mwpl_pct`; payload `date` |
| `/db/index-drivers/contribution` | `index`, `days` | `index_contribution_daily` (+ `industry`) |
| `/db/index-drivers/fit` | `index`, `days` | `index_contribution_fit` (+ `prev_index_level`) |
| `/db/index-drivers/state` | `index`, `days` | `index_driver_state` (both windows; revisions by `computed_at`) |
| `/db/index-drivers/weights` | `index`, `date` | `index_weights_daily` (`method`, `weight_pct`, `industry`) |
| `/db/data-health` | — | B1 `reads.health()`: `{last_session, summary, rows[{id, label, pages[], publisher, published_ist, expected_by, expected_offset_days, cadence, max_age_sessions, unrecoverable, job_id, freshness_kind, dictionary_anchor, verdict, badge, catalog_note, last_fetch, gap_dates[], as_of, lag_sessions, due_session, expected_at, state fresh\|amber\|red\|gap\|unknown, note}]}` — the keys ui-api reads are asserted on B1's real output by `tests/test_data_health.py::test_health_rows_carry_the_keys_ui_api_composes` |
| `/db/data-health/ingest-log` | `days` | `ingest_log` rows (`dataset, date, status ok\|gap, …`; read only on the seed path) |

`data/nse_archive/span/nsccl.YYYYMMDD.s.zip` is the 20:30 pass's file (B1/B2); the margin route only reads the newest.

## 7. Deviations from PLAN §1 (said plainly)

- `/iv/{symbol}` adds `rank{}` (recomputed beside the stored rank / percentile), `definitions{}`, `sessions`,
  `precedent`, `ok`, `store_errors` to the planned keys; `series` is echoed, the rows always carry every series.
- `/api/desk/attribution` lives in `routers/markets.py` (`attribution_router`, mounted by `main.py` at `/api/desk`) because
  `routers/desk.py` is not a B3 path; the Brinson-lite allocation / selection split (R-DRIVERS §3 "second step") is not
  built — the book is in cash today and the plan lists it as a follow-up.
- The margin route's SPAN-file leg computes scanning risk + calendar-spread charge + short-option minimum from the EOD
  (17:00) file; it does not fetch intraday files, and exposure is NSE's published rule rather than a file field. On
  4 Nov 2026 the file gives ₹8,124 scanning risk for the NIFTY 09-Nov condor (1 lot) and ₹1,22,247 for the lone short
  23700 PE, against Breeze's ₹81,497.07 and ₹1,72,460.67 (R-OPTIONS): Breeze applies ICICI's house rules on top of
  exchange SPAN — the chip says which source answered, and `heuristic{}` rides along labelled.
- `/api/data/health` replaces the never-called data-service `/health` relay of `routers/data_proxy.py` at that path
  (`status` / `data_service.reachable` kept for liveness).
- `GET /api/positions/breeze-budget` (not in the plan) exposes the ledger for SYS / BRKR.
- `DATASET_MAX_AGE_DAYS` (controller) is not retired here — B2's job; the view uses `expected_by` + `max_age` sessions.
- F-BACKEND (5 Nov, wave 1 second half): `/db/data-health/catalog` is no longer read — its rows carry B1's key names
  (`max_age_sessions`, `expected_offset_days`, `freshness_kind`), not the `max_age` / `t_plus` / `source_kind` this file
  first assumed, so a deployed B1 would have turned every row red; the view composes `/db/data-health` instead and adds
  the `unknown` state for what neither side can judge. The legacy `/api/market/option-history/{symbol}` now goes through
  the process-wide client (it built a per-request `httpx.AsyncClient`, so its test silently reached the live :8001).

## 8. Key inventory (generated)

<!-- generated: key inventory — begin -->

Generated by `services/ui-api/tests/test_terminal_v2_contract.py` from the fixture payloads (pinned clock Thu 5 Nov 2026
22:00 IST; the R-IV NIFTY run, a synthetic 3-member index, R-DATA §3's rows, the real-format SPAN subset). `path[]` = list
element, `{*}` = data-keyed map (dates / symbols / callers / paths), types are the JSON types seen (`null` means the fixture
had no value there). Regenerate with `TERMINAL_CONTRACT_WRITE=1`.

### `iv_history` — `GET /api/derivatives/iv/NIFTY?days=300`

| key path | types |
|---|---|
| `as_of` | string |
| `badges` | object |
| `badges.iv` | string |
| `badges.pctile` | string |
| `badges.rank` | string |
| `badges.rv` | string |
| `badges.skew` | string |
| `badges.spread` | string |
| `badges.term` | string |
| `badges.vix` | string |
| `definitions` | object |
| `definitions.fovolt_ann` | string |
| `definitions.iv30_cm` | string |
| `definitions.iv_minus_rv20` | string |
| `definitions.iv_minus_rv20_parkinson` | string |
| `definitions.iv_minus_rv20_yz` | string |
| `definitions.iv_pctile_252` | string |
| `definitions.iv_rank_252` | string |
| `definitions.monthly_atm_iv` | string |
| `definitions.near_skew_25d` | string |
| `definitions.rv20_cc` | string |
| `definitions.rv20_parkinson` | string |
| `definitions.rv20_yz` | string |
| `definitions.skew_25d_30` | string |
| `definitions.term_near_next` | string |
| `definitions.term_slope_30_60` | string |
| `definitions.term_slope_30_90` | string |
| `definitions.time_to_expiry` | string |
| `events` | array |
| `events[]` | object |
| `events[].date` | string |
| `events[].kind` | string |
| `model_version` | string |
| `note` | string |
| `ok` | bool |
| `precedent` | string |
| `r_source` | string |
| `rank` | object |
| `rank.iv_pctile_252` | number |
| `rank.iv_rank_252` | number |
| `rank.on` | string |
| `rank.stored` | object |
| `rank.stored.{*}` | number |
| `rank.window_sessions` | number |
| `rank.window_target` | number |
| `rank_base` | string |
| `rank_prior_observations` | number |
| `rows` | array |
| `rows[]` | object |
| `rows[].date` | string |
| `rows[].expected_move_1d_pct` | number |
| `rows[].fovolt_ann` | null, number |
| `rows[].iv30_cm` | number |
| `rows[].iv60_cm` | number |
| `rows[].iv90_cm` | number |
| `rows[].iv_minus_rv20` | null, number |
| `rows[].iv_pctile_252` | null, number |
| `rows[].iv_rank_252` | null, number |
| `rows[].monthly_atm_iv` | number |
| `rows[].monthly_expiry` | string |
| `rows[].near_atm_iv` | number |
| `rows[].near_dte` | number |
| `rows[].near_expiry` | string |
| `rows[].quality_flags` | string |
| `rows[].rv20_cc` | null, number |
| `rows[].rv20_parkinson` | null, number |
| `rows[].rv20_yz` | null, number |
| `rows[].skew_25d_30` | null, number |
| `rows[].spot` | number |
| `rows[].term_slope_30_90` | number |
| `series` | string |
| `sessions` | number |
| `since` | string |
| `spread_estimator` | string |
| `store_errors` | object |
| `symbol` | string |
| `time_convention` | string |
| `vix` | array |
| `vix[]` | object |
| `vix[].close` | null, number |
| `vix[].date` | string |

### `iv_surface` — `GET /api/derivatives/iv/NIFTY/surface?compare=1m`

| key path | types |
|---|---|
| `as_of` | string |
| `badges` | object |
| `badges.atm_iv` | string |
| `badges.skew` | string |
| `badges.smile` | string |
| `compare` | object |
| `compare.as_of` | string |
| `compare.expiries` | array |
| `compare.expiries[]` | object |
| `compare.expiries[].atm_iv` | number |
| `compare.expiries[].call_oi` | number |
| `compare.expiries[].dte` | number |
| `compare.expiries[].expected_move_pct` | number |
| `compare.expiries[].expiry` | string |
| `compare.expiries[].forward` | number |
| `compare.expiries[].forward_source` | string |
| `compare.expiries[].iv_10d_call` | number |
| `compare.expiries[].iv_10d_put` | number |
| `compare.expiries[].iv_25d_call` | number |
| `compare.expiries[].iv_25d_put` | number |
| `compare.expiries[].n_iv_strikes` | number |
| `compare.expiries[].near` | bool |
| `compare.expiries[].pcr` | number |
| `compare.expiries[].put_oi` | number |
| `compare.expiries[].quality_flags` | string |
| `compare.expiries[].skew_25d` | number |
| `compare.expiries[].smile` | array |
| `compare.expiries[].smile[]` | object |
| `compare.expiries[].smile[].delta` | number |
| `compare.expiries[].smile[].iv` | number |
| `compare.expiries[].smile[].log_moneyness` | number |
| `compare.expiries[].smile[].oi` | number |
| `compare.expiries[].smile[].opt_type` | string |
| `compare.expiries[].smile[].strike` | number |
| `compare.expiries[].untraded_strikes` | number |
| `compare.n_expiries` | number |
| `compare.requested` | string |
| `expiries` | array |
| `expiries[]` | object |
| `expiries[].atm_iv` | null, number |
| `expiries[].call_oi` | number |
| `expiries[].dte` | number |
| `expiries[].expected_move_pct` | null, number |
| `expiries[].expiry` | string |
| `expiries[].forward` | number |
| `expiries[].forward_source` | string |
| `expiries[].iv_10d_call` | null, number |
| `expiries[].iv_10d_put` | null, number |
| `expiries[].iv_25d_call` | null, number |
| `expiries[].iv_25d_put` | null, number |
| `expiries[].n_iv_strikes` | number |
| `expiries[].near` | bool |
| `expiries[].pcr` | null, number |
| `expiries[].put_oi` | number |
| `expiries[].quality_flags` | string |
| `expiries[].skew_25d` | null, number |
| `expiries[].smile` | array |
| `expiries[].smile[]` | object |
| `expiries[].smile[].delta` | number |
| `expiries[].smile[].iv` | number |
| `expiries[].smile[].log_moneyness` | number |
| `expiries[].smile[].oi` | number |
| `expiries[].smile[].opt_type` | string |
| `expiries[].smile[].strike` | number |
| `expiries[].untraded_strikes` | number |
| `n_expiries` | number |
| `note` | string |
| `ok` | bool |
| `precedent` | string |
| `store_errors` | object |
| `symbol` | string |

### `iv_cone` — `GET /api/derivatives/iv/NIFTY/cone`

| key path | types |
|---|---|
| `as_of` | string |
| `badge` | string |
| `note` | string |
| `ok` | bool |
| `precedent` | string |
| `store_errors` | object |
| `symbol` | string |
| `term_today` | array |
| `term_today[]` | object |
| `term_today[].atm_iv` | null, number |
| `term_today[].dte` | number |
| `term_today[].expiry` | string |
| `today` | object |
| `today.iv30_cm` | number |
| `today.iv60_cm` | number |
| `today.iv90_cm` | number |
| `years` | array |
| `years[]` | object |
| `years[].sessions` | number |
| `years[].tenors` | object |
| `years[].tenors.iv30_cm` | object |
| `years[].tenors.iv30_cm.max` | number |
| `years[].tenors.iv30_cm.min` | number |
| `years[].tenors.iv30_cm.n` | number |
| `years[].tenors.iv30_cm.p25` | number |
| `years[].tenors.iv30_cm.p50` | number |
| `years[].tenors.iv30_cm.p75` | number |
| `years[].tenors.iv60_cm` | object |
| `years[].tenors.iv60_cm.max` | number |
| `years[].tenors.iv60_cm.min` | number |
| `years[].tenors.iv60_cm.n` | number |
| `years[].tenors.iv60_cm.p25` | number |
| `years[].tenors.iv60_cm.p50` | number |
| `years[].tenors.iv60_cm.p75` | number |
| `years[].tenors.iv90_cm` | object |
| `years[].tenors.iv90_cm.max` | number |
| `years[].tenors.iv90_cm.min` | number |
| `years[].tenors.iv90_cm.n` | number |
| `years[].tenors.iv90_cm.p25` | number |
| `years[].tenors.iv90_cm.p50` | number |
| `years[].tenors.iv90_cm.p75` | number |
| `years[].years` | number |

### `iv_events` — `GET /api/derivatives/iv/INFY/events?n=8`

| key path | types |
|---|---|
| `badge` | string |
| `n` | number |
| `note` | string |
| `ok` | bool |
| `precedent` | string |
| `rows` | array |
| `rows[]` | object |
| `rows[].crush_pct` | number |
| `rows[].expiry` | string |
| `rows[].implied_move_pct` | number |
| `rows[].iv_post_1d` | number |
| `rows[].iv_pre_1d` | number |
| `rows[].iv_pre_5d` | number |
| `rows[].realised_move_pct` | number |
| `rows[].released_at` | string |
| `rows[].symbol` | string |
| `store_errors` | object |
| `symbol` | string |

### `iv_intraday` — `GET /api/derivatives/iv/NIFTY/intraday`

| key path | types |
|---|---|
| `badge` | string |
| `date` | string |
| `note` | string |
| `ok` | bool |
| `points` | array |
| `points[]` | object |
| `points[].atm_iv` | number |
| `points[].atm_strike` | number |
| `points[].expiry` | string |
| `points[].n_strikes` | number |
| `points[].nse_atm_iv` | number |
| `points[].pcr` | number |
| `points[].straddle` | number |
| `points[].ts` | string |
| `precedent` | string |
| `snapshots` | number |
| `source` | string |
| `sources` | array |
| `sources[]` | string |
| `store_errors` | object |
| `symbol` | string |

### `vol_screen` — `GET /api/derivatives/vol-screen?sort=iv_pctile&results_within=10`

| key path | types |
|---|---|
| `as_of` | string |
| `badges` | object |
| `badges.iv30_cm` | string |
| `badges.iv60_cm` | string |
| `badges.iv_minus_rv20` | string |
| `badges.iv_minus_rv20_parkinson` | string |
| `badges.iv_minus_rv20_yz` | string |
| `badges.iv_pctile_252` | string |
| `badges.iv_rank_252` | string |
| `badges.mwpl_pct` | string |
| `badges.near_atm_iv` | string |
| `badges.next_atm_iv` | string |
| `badges.rv20_cc` | string |
| `badges.rv20_parkinson` | string |
| `badges.rv20_yz` | string |
| `badges.skew_25d_30` | string |
| `badges.term_near_next` | string |
| `badges.term_slope_30_60` | string |
| `badges.term_slope_30_90` | string |
| `ban_date` | null |
| `ban_source` | string |
| `definitions` | object |
| `definitions.fovolt_ann` | string |
| `definitions.iv30_cm` | string |
| `definitions.iv_minus_rv20` | string |
| `definitions.iv_minus_rv20_parkinson` | string |
| `definitions.iv_minus_rv20_yz` | string |
| `definitions.iv_pctile_252` | string |
| `definitions.iv_rank_252` | string |
| `definitions.monthly_atm_iv` | string |
| `definitions.near_skew_25d` | string |
| `definitions.rv20_cc` | string |
| `definitions.rv20_parkinson` | string |
| `definitions.rv20_yz` | string |
| `definitions.skew_25d_30` | string |
| `definitions.term_near_next` | string |
| `definitions.term_slope_30_60` | string |
| `definitions.term_slope_30_90` | string |
| `definitions.time_to_expiry` | string |
| `n` | number |
| `note` | string |
| `ok` | bool |
| `precedent` | string |
| `results_within` | number |
| `rows` | array |
| `rows[]` | object |
| `rows[].ban` | bool |
| `rows[].date` | string |
| `rows[].iv30_cm` | null, number |
| `rows[].iv30_flat` | bool |
| `rows[].iv60_cm` | null |
| `rows[].iv_minus_rv20` | null, number |
| `rows[].iv_minus_rv20_parkinson` | null |
| `rows[].iv_minus_rv20_yz` | null, number |
| `rows[].iv_pctile_252` | null, number |
| `rows[].iv_rank_252` | null, number |
| `rows[].mwpl_date` | null |
| `rows[].mwpl_pct` | number |
| `rows[].near_atm_iv` | null |
| `rows[].near_dte` | null |
| `rows[].next_atm_iv` | null |
| `rows[].next_dte` | null |
| `rows[].next_results` | string |
| `rows[].quality_flags` | null |
| `rows[].results_in_days` | number |
| `rows[].rv20_cc` | null |
| `rows[].rv20_parkinson` | null |
| `rows[].rv20_yz` | number |
| `rows[].skew_25d_30` | null, number |
| `rows[].spot` | number |
| `rows[].symbol` | string |
| `rows[].term_near_next` | null |
| `rows[].term_slope_30_60` | null |
| `rows[].term_slope_30_90` | null, number |
| `sort` | string |
| `spread_estimator` | string |
| `store_errors` | object |

### `option_history_legacy` — `GET /api/market/option-history/NIFTY`

| key path | types |
|---|---|
| `badges` | object |
| `badges.iv_pctile_252` | string |
| `badges.iv_rank_252` | string |
| `definitions` | object |
| `definitions.iv_pctile_252` | string |
| `definitions.iv_rank_252` | string |
| `iv_pctile_252` | number |
| `iv_rank_252` | number |
| `rank_series` | string |
| `rank_window_sessions` | number |
| `rows` | array |
| `rows[]` | object |
| `rows[].atm_iv` | number |
| `rows[].date` | string |
| `rows[].max_pain` | number |
| `rows[].pcr` | number |
| `symbol` | string |
| `updating` | bool |

### `index_drivers` — `GET /api/market/index-drivers?index=NIFTY 50&horizon=1m`

| key path | types |
|---|---|
| `as_of` | string |
| `badges` | object |
| `badges.breadth` | string |
| `badges.concentration` | string |
| `badges.driver` | string |
| `badges.fit` | string |
| `badges.members` | string |
| `badges.monthly` | string |
| `badges.sectors` | string |
| `breadth` | object |
| `breadth.cw_pct` | number |
| `breadth.down` | number |
| `breadth.ew_minus_cw_pp` | number |
| `breadth.ew_pct` | number |
| `breadth.up` | number |
| `breadth.word` | string |
| `concentration` | object |
| `concentration.effective_n` | number |
| `concentration.hhi_contrib` | number |
| `concentration.top5_abs_share` | number |
| `concentration.top5_weight_pct` | number |
| `concentration.weight_hhi` | number |
| `driver` | object |
| `driver.as_of` | string |
| `driver.challenger` | null |
| `driver.change_date` | string |
| `driver.changed_from` | string |
| `driver.ew_minus_cw_pp` | number |
| `driver.hhi_contrib` | number |
| `driver.leader` | string |
| `driver.leader_points` | number |
| `driver.leader_share` | number |
| `driver.members_down` | number |
| `driver.members_up` | number |
| `driver.sentence` | string |
| `driver.tenure` | number |
| `driver.top5_share` | number |
| `driver.window` | number |
| `explained_pts` | number |
| `fit` | object |
| `fit.degraded` | bool |
| `fit.mae_60s` | number |
| `fit.members_priced` | number |
| `fit.members_total` | number |
| `fit.note` | string |
| `fit.r2_60s` | number |
| `fit.residual_today` | number |
| `fit.sessions` | number |
| `history_since` | string |
| `horizon` | object |
| `horizon.from` | string |
| `horizon.name` | string |
| `horizon.sessions` | number |
| `horizon.to` | string |
| `index` | string |
| `index_move_pts` | number |
| `members` | array |
| `members[]` | object |
| `members[].flag` | null |
| `members[].industry` | string |
| `members[].points` | number |
| `members[].ret_pct` | number |
| `members[].share_abs` | number |
| `members[].symbol` | string |
| `members[].weight_pct` | number |
| `members_priced` | number |
| `note` | string |
| `ok` | bool |
| `precedent` | string |
| `residual_pts` | number |
| `sectors` | array |
| `sectors[]` | object |
| `sectors[].industry` | string |
| `sectors[].points` | number |
| `sectors[].weight_pct` | number |
| `store_errors` | object |
| `tab` | object |
| `tab.sentence` | string |
| `tab.sessions` | number |
| `tab.state` | string |
| `weight_method` | object |
| `weight_method.label` | string |
| `weight_method.method` | string |

### `index_drivers_timeline` — `GET /api/market/index-drivers/timeline?window=20&days=250`

| key path | types |
|---|---|
| `as_of` | string |
| `badge` | string |
| `changes` | array |
| `index` | string |
| `note` | string |
| `ok` | bool |
| `points` | array |
| `points[]` | object |
| `points[].changed` | bool |
| `points[].date` | string |
| `points[].effective_n` | number |
| `points[].ew_minus_cw_pp` | number |
| `points[].hhi_contrib` | number |
| `points[].leader` | string |
| `points[].leader_share` | number |
| `points[].top5_share` | number |
| `store_errors` | object |
| `window` | number |

### `index_drivers_monthly` — `GET /api/market/index-drivers/monthly?months=12`

| key path | types |
|---|---|
| `as_of` | string |
| `as_of_month` | string |
| `badge` | string |
| `index` | string |
| `months` | array |
| `months[]` | object |
| `months[].bad_sessions` | array |
| `months[].explained_pts` | number |
| `months[].index_move_pts` | number |
| `months[].leader` | string |
| `months[].leader_changed` | bool |
| `months[].leader_pts` | number |
| `months[].leader_share` | number |
| `months[].month` | string |
| `months[].note` | null |
| `months[].residual_pts` | number |
| `months[].sessions` | number |
| `months[].top3_add` | array |
| `months[].top3_add[]` | object |
| `months[].top3_add[].points` | number |
| `months[].top3_add[].symbol` | string |
| `months[].top3_drag` | array |
| `months[].top3_drag[]` | object |
| `months[].top3_drag[].points` | number |
| `months[].top3_drag[].symbol` | string |
| `n` | number |
| `note` | string |
| `ok` | bool |
| `store_errors` | object |

### `desk_attribution_risk_off` — `GET /api/desk/attribution?horizon=1m`

| key path | types |
|---|---|
| `as_of` | string |
| `badges` | object |
| `badges.book` | string |
| `badges.nifty` | string |
| `book_pp` | number |
| `horizon` | object |
| `horizon.from` | string |
| `horizon.name` | string |
| `horizon.sessions` | number |
| `horizon.to` | string |
| `nav` | number |
| `nifty` | object |
| `nifty.explained_pts` | number |
| `nifty.index_move_pts` | number |
| `nifty.top5_add` | array |
| `nifty.top5_add[]` | object |
| `nifty.top5_add[].flag` | null |
| `nifty.top5_add[].industry` | string |
| `nifty.top5_add[].points` | number |
| `nifty.top5_add[].ret_pct` | number |
| `nifty.top5_add[].share_abs` | number |
| `nifty.top5_add[].symbol` | string |
| `nifty.top5_add[].weight_pct` | number |
| `nifty.top5_drag` | array |
| `nifty.top5_drag[]` | object |
| `nifty.top5_drag[].flag` | null |
| `nifty.top5_drag[].industry` | string |
| `nifty.top5_drag[].points` | number |
| `nifty.top5_drag[].ret_pct` | number |
| `nifty.top5_drag[].share_abs` | number |
| `nifty.top5_drag[].symbol` | string |
| `nifty.top5_drag[].weight_pct` | number |
| `note` | string |
| `note_rules` | string |
| `ok` | bool |
| `paper_only` | bool |
| `risk_off` | bool |
| `rows` | array |
| `since` | string |
| `store_errors` | object |

### `margin_breeze` — `POST /api/options/margin` body: {symbol, legs[4], sources=breeze}

| key path | types |
|---|---|
| `as_of` | string |
| `attempts` | array |
| `attempts[]` | object |
| `attempts[].ok` | bool |
| `attempts[].reason` | string |
| `attempts[].source` | string |
| `badge` | string |
| `badges` | object |
| `badges.non_span_margin_required` | string |
| `badges.span_margin_required` | string |
| `badges.total_margin` | string |
| `detail` | object |
| `detail.legs_echo` | number |
| `detail.non_span_margin_required` | number |
| `detail.order_value` | number |
| `detail.span_margin_required` | number |
| `detail.trade_margin` | null |
| `exchange_code` | string |
| `heuristic` | object |
| `heuristic.defined_risk_floor` | number |
| `heuristic.error_factor_measured` | number |
| `heuristic.evidence` | string |
| `heuristic.fut_margin_pct` | number |
| `heuristic.note` | string |
| `heuristic.per_leg` | array |
| `heuristic.per_leg[]` | number |
| `heuristic.premium_outflow` | number |
| `heuristic.total` | number |
| `legs` | number |
| `non_span_margin_required` | number |
| `note` | string |
| `order_value` | number |
| `paper_only` | bool |
| `served_from_cache` | bool |
| `source` | string |
| `source_chip` | string |
| `span_margin_required` | number |
| `symbol` | string |
| `total_margin` | number |

### `margin_span_file` — `POST /api/options/margin` body: {symbol, legs[4], sources=span_file}

| key path | types |
|---|---|
| `as_of` | string |
| `attempts` | array |
| `attempts[]` | object |
| `attempts[].ok` | bool |
| `attempts[].reason` | string |
| `attempts[].source` | string |
| `badge` | string |
| `badges` | object |
| `badges.non_span_margin_required` | string |
| `badges.span_margin_required` | string |
| `badges.total_margin` | string |
| `detail` | object |
| `detail.calendar_spread_charge` | number |
| `detail.exposure` | object |
| `detail.exposure.badge` | string |
| `detail.exposure.note` | string |
| `detail.exposure.pct_of_notional` | number |
| `detail.exposure.reference_price` | number |
| `detail.exposure.value` | number |
| `detail.file` | string |
| `detail.file_date` | string |
| `detail.net_delta_by_expiry` | object |
| `detail.net_delta_by_expiry.{*}` | number |
| `detail.net_option_value` | number |
| `detail.ok` | bool |
| `detail.scanning_risk` | number |
| `detail.scenario_losses` | array |
| `detail.scenario_losses[]` | number |
| `detail.settlement_file` | bool |
| `detail.short_option_minimum` | number |
| `detail.span_margin` | number |
| `detail.spreads` | array |
| `detail.worst_scenario` | number |
| `exchange_code` | string |
| `heuristic` | object |
| `heuristic.defined_risk_floor` | number |
| `heuristic.error_factor_measured` | number |
| `heuristic.evidence` | string |
| `heuristic.fut_margin_pct` | number |
| `heuristic.note` | string |
| `heuristic.per_leg` | array |
| `heuristic.per_leg[]` | number |
| `heuristic.premium_outflow` | number |
| `heuristic.total` | number |
| `legs` | number |
| `non_span_margin_required` | number |
| `note` | string |
| `order_value` | null |
| `paper_only` | bool |
| `served_from_cache` | bool |
| `source` | string |
| `source_chip` | string |
| `span_margin_required` | number |
| `symbol` | string |
| `total_margin` | number |

### `margin_heuristic` — `POST /api/options/margin` body: {symbol, legs[4], sources=heuristic}

| key path | types |
|---|---|
| `as_of` | string |
| `attempts` | array |
| `attempts[]` | object |
| `attempts[].ok` | bool |
| `attempts[].reason` | string |
| `attempts[].source` | string |
| `badge` | string |
| `badges` | object |
| `badges.non_span_margin_required` | string |
| `badges.span_margin_required` | string |
| `badges.total_margin` | string |
| `detail` | object |
| `exchange_code` | string |
| `heuristic` | object |
| `heuristic.defined_risk_floor` | number |
| `heuristic.error_factor_measured` | number |
| `heuristic.evidence` | string |
| `heuristic.fut_margin_pct` | number |
| `heuristic.note` | string |
| `heuristic.per_leg` | array |
| `heuristic.per_leg[]` | number |
| `heuristic.premium_outflow` | number |
| `heuristic.total` | number |
| `legs` | number |
| `non_span_margin_required` | number |
| `note` | string |
| `order_value` | null |
| `paper_only` | bool |
| `served_from_cache` | bool |
| `source` | string |
| `source_chip` | string |
| `span_margin_required` | number |
| `symbol` | string |
| `total_margin` | number |

### `data_health` — `GET /api/data/health`

| key path | types |
|---|---|
| `as_of` | string |
| `badge` | string |
| `catalog_source` | string |
| `controller_online` | bool |
| `data_service` | object |
| `data_service.reachable` | bool |
| `data_service.url_role` | string |
| `inputs_unavailable` | object |
| `last_session` | string |
| `note` | string |
| `ok` | bool |
| `rows` | array |
| `rows[]` | object |
| `rows[].as_of` | null, string |
| `rows[].badge` | string |
| `rows[].catchup_at` | null |
| `rows[].dictionary_anchor` | string |
| `rows[].expected_by` | null, string |
| `rows[].id` | string |
| `rows[].job_id` | string |
| `rows[].label` | string |
| `rows[].lag_sessions` | null, number |
| `rows[].last_run` | null, object |
| `rows[].last_run.ms` | number |
| `rows[].last_run.status` | string |
| `rows[].last_run.ts` | string |
| `rows[].max_age_sessions` | number |
| `rows[].next_run` | null, string |
| `rows[].note` | string |
| `rows[].pages` | array |
| `rows[].pages[]` | string |
| `rows[].published_ist` | string |
| `rows[].publisher` | string |
| `rows[].running_since` | null |
| `rows[].state` | string |
| `rows[].unrecoverable` | bool |
| `service` | string |
| `status` | string |
| `summary` | object |
| `summary.amber` | number |
| `summary.gaps` | number |
| `summary.green` | number |
| `summary.red` | number |
| `summary.rows` | number |
| `summary.unknown` | number |

### `breeze_budget` — `GET /api/positions/breeze-budget`

| key path | types |
|---|---|
| `badge` | string |
| `by_caller` | object |
| `by_caller.{*}` | number |
| `by_method` | object |
| `by_method.{*}` | number |
| `cap_day` | number |
| `cap_minute` | number |
| `ceiling_day` | number |
| `ceiling_minute` | number |
| `day_ist` | string |
| `errors_today` | number |
| `holidays_known` | bool |
| `last_call` | object |
| `last_call.at` | string |
| `last_call.caller` | string |
| `last_call.method` | string |
| `last_call.ok` | number |
| `note` | string |
| `path` | string |
| `quotas` | object |
| `quotas.{*}` | number |
| `refused_today` | number |
| `remaining_day` | number |
| `trading_day` | bool |
| `used_day` | number |
| `used_minute` | number |

<!-- generated: key inventory — end -->
