# GOLD program — the ui-api contract as implemented (B3-API, 26 Oct 2026; wave 1b 4 Nov 2026; wave 1c critics' fix round 5 Nov 2026)

What `services/ui-api/routers/gold.py` (mounted at **`/api/gold`**) and the TOTP routes on `routers/positions.py`
(**`/api/positions/totp/*`**) actually return. B4A/B4B/B5 build against this file, not against PLAN §d; every deviation
from the plan is listed in §7. Source of truth for shapes: `services/ui-api/tests/test_gold.py` and
`test_icici_totp_routes.py` (data-service mocked with the agents' samples), and **§8**, the key inventory GENERATED from
those fixtures by `tests/test_gold_contract.py`: the test fails whenever this document and the code disagree (regenerate
with `GOLD_CONTRACT_WRITE=1`). `ui/lib/gold/types.ts` follows this file (the server shape wins unless it violates PLAN §d).

## 0. Rules every route obeys

- **Store, then show.** Stored numbers come from data-service `/db/gold/*` through one stale-while-revalidate cache
  (`SWRCache("gold.store")`, refresh 120 s, bound 900 s); memoised payloads (`TTLCache("gold")`): `health` 60 s,
  `overview` 30 s, `catalog` 3600 s, LEARN files 3600 s. A data-service failure (down, 404 = tables not deployed, bad
  body) is remembered 15 s per path and **degrades the block, never the page**: the key is present with `null`s and a
  `freshness.state = "unavailable"`; `store_errors` (or `errors`) names the paths that failed.
- **No publisher on the request path.** The only live legs are the pre-open desk's cached Yahoo fetcher
  (`gold_preopen._yahoo_bars_cached`, SWR 30/120 s, single flight) and the MCX Breeze quote through `mcx.mcx_quote`
  (15 s TTL, 10-minute broken memory). `/bars` only *peeks* at the Yahoo cache; it never starts a fetch. `gold.py`
  defines no fetcher and names no publisher host except two **links** (`REUTERS_LINK`, `fed.fedwatch_link`).
- **Headers:** `X-Cache` (hit | stale | miss | bypass) and `X-Cache-Age` (seconds, the oldest stored piece) on every
  route that reads the store. Never in the body.
- **Freshness block** everywhere: `{source, as_of, age_s, state}` with `state ∈ live | delayed | stale | unavailable`
  (`stale` = older than the catalog's `max_age_days`; daily data shows its date, not a clock).
- **Badges** come from the catalog (`signal | context | arithmetic | heuristic`); `signal` never appears today. Context
  metrics are never worded bullish/bearish. The health verdict has **no `score` key** and ends
  `describes, does not predict`.
- **Rendering gate, strict (PLAN f.2).** A series / gauge / ladder step renders a number only when the catalog carries a
  PUBLISH-* row for its `series_id`. An EMPTY catalog (data-service unreachable before the 3600 s memo filled, or the seed
  not yet run) publishes **nothing**: the block says `published: false, note: "catalog unavailable — not published"`
  (`"no verdict — not published"` when the row exists without a PUBLISH verdict). Live arithmetic that is not a stored
  series (the fair value, the MCX quote, costs) is not gated.
- **CFTC release calendar.** `/cot.latest.next_*` and `/calendar`'s `COT_RELEASE` rows come from the holiday-aware rule
  data-service stamps `release_at` with (Friday 15:30 ET; the Monday after a US federal holiday that falls Wed–Fri of the
  report week; the CFTC's published 2026 Mondays pinned): `test_cot_release_calendar_matches_data_service` keeps ui-api
  and `gold/pit.py` equal week by week. IST labels follow US DST (`01:00 IST` in summer, `02:00 IST` from 1 Nov 2026).
- **Errors:** `errors.fail` → `{detail: str, error: {code, message, hint?}}` (422 for bad inputs); degraded-but-usable
  200s carry `ok: false` + `error_info{}` (`errors.degraded`).
- **Nothing here feeds a trade.** No route is read by the Decision Desk, the S1 shadow, directional alerts or the paper
  ticket's price.
- Timestamps are ISO with the IST offset (`as_of`); dates are `YYYY-MM-DD`; numbers are numbers (`null` when unknown).
- **Every datetime carries its offset (wave 1c, C-TRADER-1 / C-DATA-1 / C-DATA-6).** data-service stores zone-less UTC;
  ui-api re-stamps every such string as IST (`2026-11-04T18:19:57` → `2026-11-04T23:49:57+05:30`, `gold._iso_any`): bar
  `ts`, COT `release_at`, gauge `release_at`, `generated_at`, `first_seen_at`, ladder `ts`. Date-only strings stay dates.
  Labels that name a clock say so (`next_fomc_ist` = `2026-12-10 00:30 IST`). `test_every_datetime_string_served_carries_an_offset`
  walks every route of §8 and fails on a naive datetime string.
- **One number per page, one clock per ratio (PLAN §f.6; wave 1c).** The MCX basis is printed at ONE clock everywhere it
  appears (`/health.gauges[india_basis]`, `/overview.strip.basis_pct`, `/premiums.india.basis_pct`, `/curve.basis.basis_pct`):
  the live quote ÷ duty-paid landed now while the page holds a quote (`basis_clock: "now"`), else the stored settlement-session
  row (`"settlement"`, `basis_date`); the other clock's figure sits beside it under its own key, labelled. The India premium
  is the stored fix-minute `INDIA_PREMIUM_PCT`, never the PM fix divided by a landed price computed later. The Shanghai
  premium pairs SGE PM and LBMA PM of the SAME report date only.

## 1. Route index

| Route | Memo / cache | Reads |
|---|---|---|
| `GET /api/gold/overview?contract=GOLD&expiry=&window=W` | 30 s | health + fair + mcx quote + brief + events + series + cot |
| `GET /api/gold/health?window=D\|W\|M` | 60 s | bars, series, cot, etf, curve(COMEX), events, fair block |
| `GET /api/gold/fair?baseline=&mcx_price=&threshold=300&eurusd_trigger=&contract=&expiry=` | desk SWR | the desk (`gold_preopen._gold_preopen`) + log |
| `GET /api/gold/series?ids=A,B&from=&to=&freq=D\|W\|M&asof=` | store | `/db/gold/series`, catalog |
| `GET /api/gold/bars?symbol=GC=F&interval=1m\|5m\|1d&from=&to=` | store | `/db/gold/bars`, `/db/gold/curve` |
| `GET /api/gold/cot?weeks=52&report=disagg\|legacy&fut_or_combined=F\|C` | store | `/db/gold/cot` ×3, bars, etf |
| `GET /api/gold/positioning/daily?exchange=COMEX\|MCX&days=60&family=GOLD` | store | cme/voi, bars, curve, events · curve/history |
| `GET /api/gold/curve?exchange=COMEX\|MCX&date=&family=GOLD` | store | `/db/gold/curve` (+ghost), series, fair block |
| `GET /api/gold/contracts?exchange=MCX\|COMEX` | store + master | ICICI master, `/db/gold/margins`, curve(COMEX), (`cme/prf` optional) |
| `GET /api/gold/premiums?days=365` | store | series, fair block |
| `GET /api/gold/flows?months=24` | store | series, `/db/gold/etf`, `cme/efrp`, `cme/voi` |
| `GET /api/gold/macro?window=D` | store | series (10 y), bars (10 y), etf, fed-path, events, master |
| `GET /api/gold/calendar?days=30` | store | `/db/gold/events` + computed rows |
| `GET /api/gold/log?days=60&threshold=300` · `POST /api/gold/log/actual {date, open}` | — | `data/gold_preopen/log.json` |
| `GET /api/gold/catalog` | 3600 s | `/db/gold/catalog` |
| `GET /api/gold/brief?date=` | store | `/db/gold/brief` |
| `GET /api/gold/learn/glossary?q=&limit=40` · `GET /api/gold/learn/tooltips` | 3600 s | `ui/lib/gold/*.json` (fallback `G-EDU/`) |
| `POST /api/gold/snapshot?force=` · `POST /api/gold/capture-open` | — | aliases of `/api/commodity/gold-preopen/*` |
| `POST /api/gold/invalidate?what=all\|store\|memo` | — | drops the store cache + memos (controller calls it after an ingest) |
| `GET /api/positions/totp/status?reveal=0\|1` · `POST /totp/preview` · `POST /totp` · `DELETE /totp` | — | .env / Keychain probe |

`/api/commodity/gold-preopen`, `/gold-preopen/snapshot`, `/capture-open`, `/actual`, `/log` stay mounted as aliases for
one release (same bodies, now with `baseline.session_label`, `holiday`, `verdict.badge = "heuristic"`, `inputs_json`).

## 2. Shapes

### 2.1 `/health`
```
{ as_of, window: "D|W|M",
  verdict: { line, clauses[{text, rule_id, series_id, value, threshold}], headline, badge: "context", ends_with },
  gauges: [ {key, label, value, unit, change, change_unit: "%"|"bp"|"$/oz"|"contracts"|"t"|null, change_window, report_date,
             release_at, age_days, state, direction_for_gold, rule, percentile_1y, percentile_3y, series_id, source, badge,
             evidence, published?, note?, …extras} ×8 ],
  fair: { contract, expiry, expiry_source, fair_value, mcx_live, mcx_live_source, mcx_live_as_of, premium_rupees, premium_pct,
          comex{symbol, price, as_of}, comex_symbol, usdinr{symbol, price, as_of}, landed, duty_pct, duty_effective, duty_note,
          duty_paid_landed, basis_pct, implied_premium_pct (deprecated alias), settlement, settlement_session,
          settlement_session_label, settlement_quality: "proxy", gap_vs_settlement,
          actual_open, actual_open_source, snapshot_fair, snapshot_error, mcx_holiday{name, closure, opens_at}|null,
          desk_verdict_state: OK|WAIT|AWAITING_OPEN|NEED_PRICE|null, badge: "arithmetic", freshness },
  line: "GOLD · WEAK WEEK, DOLLAR-DRIVEN · basis +0.4 % · COT MM +104k (−2.9k) · roll DEC-26→FEB-27 2026-11-30 · GOLD ›",
  brf_line: "Gold open: fair ₹1,44,181 (gap −1,898) · WAIT · WEAK WEEK, DOLLAR-DRIVEN · GOLD ›"   (or the opened / holiday forms),
  lines: {wei: line, brf: brf_line},
  freshness: {state, oldest, age_days, unavailable[], stale[]}, store_errors }
```
Gauge keys, in order: `trend, real_yield, dollar, positioning, india_basis, shanghai, etf, curve_roll`. `change` is in
`change_unit`: a `%` change for trend / dollar, a DIFFERENCE for the rest (`bp` real yield, `$/oz` Shanghai, `contracts`
positioning, `t` ETF) — the Shanghai tile's week change is `+47.36` `$/oz`, never "+47.36 %" (C-DATA-7). Extras per gauge:
trend `vs_20d_pct, vs_200d_pct, drawdown_52w_pct, window_label, window_from, window_from_value, window_sessions,
last_bar_partial, last_bar_note` (+ `percentile_3y` from 1,100 days of stored daily bars; a bar dated today while Globex
trades is `last_bar_partial: true`); real_yield `change_bp, window_label, window_from`; dollar `read_from, window_label,
window_from` — the tile is labelled by the series actually used: `DXY_CLOSE` from the series read, else the same catalog
row read from the stored `DX-Y.NYB` daily bars, else the Fed broad index **labelled** `Fed broad USD index (DTWEXBGS, weekly
lag — not DXY)` under `series_id: FRED_DTWEXBGS` (a different basket: it never feeds the H2 driver word), else an
`unavailable` tile with a `note` (C-DATA-4 / C-BEGINNER-6); positioning `change_pct, net_pct_oi, cot_index_52, words,
driver_label, chg_long, chg_short, week_price_chg_pct` (the fund-driver label with the Tue→Tue GC=F change — the SAME
rule and price `/cot` uses, so the verdict's H3 clause and the POSITIONING hero never disagree); india_basis `clock:
"now"|"settlement", basis_label, live_basis_pct, mcx_live, duty_paid_landed_now, settle_basis_pct, settle_basis_date,
settle_basis_label, settle_basis_source, ibja_premium_pct, ibja_premium_date, ibja_premium_note, duty_pct, duty_effective,
settlement_session_label` (value = the live-clock basis while a quote exists, `state: "live"`; else the stored
settlement-session `MCX_BASIS_PCT` row, `state: "delayed"`); etf `chg_5d`; curve_roll `front, next, annualised_pct,
days_to_fnd, fnd_date, ltd_date, fnd_source` (the FRONT month's own first notice: a stored `COMEX_FND` event naming that
month in any spelling — `COMEX GC 2026-12 …`, `GCZ26`, `DEC-26` — else the CME PRF row, else the next stored FND). A gauge
the catalog does not publish carries `published: false, note` (§0 rendering gate); `fair.desk_verdict_state` is the desk's
own ₹300 rule (`gold_preopen._verdict_body`) on the cached MCX quote — OK / WAIT once a price exists, AWAITING_OPEN /
NEED_PRICE before — and is what `brf_line` prints. `fair_block` looks the quote up under the resolved expiry key AND the
`front` alias (C-DATA-13), so the desk state and the gauge never disagree with `/overview.quote`.

**Verdict rules (every clause is a threshold on a stored series; stale/unavailable gauges add no clause):**
H1 week label: Δ over the window ≤ −2 % WEAK · ≥ +2 % STRONG · |Δ| < 0.5 % FLAT · else FIRM/SOFT. **The window `W` is
Monday-to-date once the week has a session** (`window_label: "week to date (since the Fri 30 Oct close)"`), the trailing
5 sessions before it (`"5 sessions"`); `M` month-to-date the same way (else `"30 days"`); `D` `"vs the previous session"`
(C-TRADER-16) — the verdict's second clause prints that label verbatim, never "over the week" ·
H2 driver: DOLLAR-DRIVEN when the KGX dollar effect is ≥ 40 % of the move (same sign, |move| ≥ 0.5 %); YIELD-DRIVEN when
the 10-y real yield moved ≥ 5 bp against gold; GOLD-SPECIFIC **only when both legs were tested** and neither explains the
move; when either leg is missing the word is omitted and the H1/H2 clause's `note` says why (`driver untested: dollar
series offline` / `… DXY offline (the dollar tile shows the Fed broad index, a different basket)`; C-TRADER-7 / C-DATA-2) ·
H3 funds: MM net and Δ w/w % with the fund-driver label (none on a week without a change in either leg) · H4 India basis vs
duty-paid landed (stated, not judged) · H5 roll: front→next spread % (annualised), days to FND · H6 GLD Δ t on the day
(≥ 5 t "notable") · H0 closing words. `HEALTH_RULES` in the module is the audit table (G-EDU §8.4 follows it).

### 2.2 `/fair`
Today's `/api/commodity/gold-preopen` body (`contract, baseline{value, source, session, session_label, stale, close_time,
settlement_from_band, master_published}, mcx_price, model{comex{}, inr{}, fair_open, gap, gap_pct, comex_part, inr_part,
rs_per_comex_dollar, rs_per_inr_rupee, landed, duty_pct, duty_paid_landed, basis_pct, implied_premium_pct, …}, duty{pct,
effective, notification, note}, threshold, verdict{state, title, detail, diff?, badge: "heuristic"}, holiday{closure, name,
opens_at, note}|null, event_risk{flagged_headlines, badge: "heuristic", advice: null}, context[], headlines[],
manual_checks[], notes[]`) **plus** `accuracy{days, median_abs_error, mean_abs_error, p90, within_threshold_pct,
naive_mean_abs_error, bias, threshold, badge}`, `today_log` (today's log row or null), `badge: "arithmetic"`,
`freshness`, and — when `contract` ≠ GOLD or `expiry` is given — `contract_fair` (the `/health.fair` block for that
family). `eurusd_trigger` and the headline topics come from prefs `gold.triggers.v1` unless sent.

### 2.3 `/series`
```
{ as_of, asof_applied, freq, store_errors,
  series: [ { series_id, name, unit, freq_native, quality, resample: last|sum|mean, published: bool, note,
              points[{report_date, value, release_at, n?}], n,
              catalog{publisher, verdict, badge, lag_note, terms, evidence}, freshness } ] }
```
Point-in-time: `asof` (ISO) keeps the latest vintage of each `report_date` released at or before it. `freq=W` buckets to
the Friday that ends the week, `M` to the month end, with the catalog's `resample` (`last` default). An unpublished
series (verdict not PUBLISH-*) returns `published: false` and **no points**; an unknown one returns no points and
`freshness.state = "unavailable"`.

### 2.4 `/bars`
```
{ symbol, interval, instrument, day, hi, lo, bars[{ts, o, h, l, c, v}], sessions[{name, start_ist, end_ist, hatched?, bar?, closed?}],
  settle_line{value, label, source, quality, is_settlement}|null, matched_last{value, label, source, quality, is_settlement}|null,
  prev_close{date, close, partial, label}|null, daily_closes[{date, close, partial, label}], prev_day[{ts, c}],
  last{price, as_of, source, age_s}|null, since, freshness, note }
```
Symbols are Yahoo symbols as data-service stores them (`GC=F`, `GCZ26.CMX`, `INR=X`). Intraday `ts` is IST with the offset
(`2026-11-04T23:49:57+05:30`; the store's naive UTC re-stamped — C-TRADER-1 / C-DATA-1); daily `ts` is a date. `day`,
`prev_day` and `hi/lo` bucket by the IST calendar day. `sessions` are the IST bands for today (Sydney/Tokyo, SGE day/night,
London, New York, COMEX maintenance hour, MCX bar) from zoneinfo (DST-aware). `matched_last` is the stored COMEX curve
point of the symbol's OWN delivery month (`GCG27.CMX` → the FEB-27 line, never the front's; the front for `GC=F`; `null`
when that month is not on the stored curve), labelled `last trade (Yahoo), not a settlement` unless its source is a CME
settlement. `settle_line` (the dashed line) is a CME settlement of that month when one is stored, else the PREVIOUS
session's stored daily close (`prev_close`, `is_settlement: false`, label `Tue 03 Nov close (Yahoo daily bar)`) — never
the live last (C-TRADER-2 / C-TRADER-17). `daily_closes` are the last four stored daily closes for the legend; a bar dated
today while Globex trades is `partial: true` and labelled `last (partial day)`.

### 2.5 `/cot`
```
{ as_of, report, fut_or_combined,
  latest{report_date, release_at, release_ist, next_report_date, next_release_at, next_release_ist, next_release_source,
         age_days, stale, catch_up_note},
  open_interest{total, chg, pct_rank, pct_rank_label},
  groups[{key: mm|or|nr|sd|pm (+nc, c for legacy), label, long, short, spread, net, net_moz, net_t, net_usd_bn,
          chg_long, chg_short, chg_net, pct_oi_long, pct_oi_short, net_pct_oi, traders_long, traders_short,
          who_did["closed 3,777 longs", "covered 894 shorts"]}],
  driver_label, driver_rule, quadrant_label, week_price_chg_pct, price_tue, price_prev_tue,
  crowd{cot_index_26, cot_index_52, cot_index_156, z52, z156, percentile_all, percentile_window, window_reports, window_label,
        percentile_label, n_reports, label, badge},
  options_overlay{mm_net_options_only, combined_oi, mm_net_combined, line},
  history[{report_date, price, mm_net, or_net, nr_net, sd_net, pm_net, oi, cot_index_52}],
  decomposition[{span, from_date, to_date, price_from, price_to, d_mm_long, d_mm_short, d_mm_net, d_sd_net, d_pm_net, d_comm_net, d_or_net, d_nr_net, d_oi, d_gld_t}],
  drawer{traders{}, average_position{}, concentration{}, micro_gold{}|null, raw_block_url, api_query, identity_check,
         identity_gap, identity_note},
  badge: "context", evidence, footer, freshness, store_errors }
```
**Driver label (wave 1c)** = a byte-for-byte mirror of data-service `gold/driver_rule.py` (`driver_rule` carries the rule
text): the net-sign test first, then the bigger leg — down week: `funds bought the dip` if the net rose; else `long
liquidation` if ΔL<0 and |ΔL| ≥ max(ΔS,0); else `new shorts` · up week, mirrored: `funds sold into it` if the net fell;
else `short covering` if ΔS<0 and |ΔS| ≥ max(ΔL,0); else `new longs`. `null` without the week's price, on a week with no
price change or when neither leg moved (the who-did counts stand alone). The 27 Oct 2026 week (+1,538 longs, +182 shorts,
price −1.64 %) reads `funds bought the dip`, no longer `new shorts` (C-TRADER-3 / C-BEGINNER-1 / C-DATA-15);
`test_driver_label_mirrors_data_service_on_every_branch` loads data-service's file by path and checks every branch.
Quadrant = sign(Δprice Tue→Tue) × sign(ΔOI) → `long build-up / short build-up / short covering / long unwinding`. `who_did`
wording: `new|closed N longs`, `new|covered N shorts`, `no change`. **Percentiles**: `crowd.percentile_all` and
`open_interest.pct_rank` are data-service's FULL-panel (1986→) figures passed through from the summary it merges beside
`rows`, labelled `all-history percentile (1986→, data-service)`; when absent ui-api's own window figure is used under the
label `3-y percentile (160 reports)` (`percentile_window`, `window_reports`, `window_label` — never "all-history" for a
window; C-DATA-14). The drawer's `identity_check` is the disaggregated long-side identity pm + sd + mm + or (long + spread)
+ nr long = OI (C-TRADER-28). Nothing stored → 200 with `ok: false`, `error_info.code = "state"`, `latest: null`. The
controller's Saturday digest reads exactly this shape. `latest.release_at` is the IST instant with the offset
(`2026-10-24T01:00:00+05:30` — the digest's `released Sat 24 Oct` keeps the IST clock of its `next …` label; C-DATA-6/20);
`crowd.percentile_all` is data-service's expanding all-history percentile (1986→) or null; `crowd.percentile_window` / `crowd.window_reports` / `crowd.window_label` (`"3-y percentile (160 reports)"`) and `crowd.percentile_label` name the window ui-api computed over; `open_interest.pct_rank` carries `open_interest.pct_rank_label` the same way — the client prints the label verbatim and never calls a fetched window "all-history" (C-DATA-14).
`latest.release_ist` names the CURRENT report's release (`Sat 24 Oct 01:00 IST` — Friday 15:30 ET is Saturday in IST);
`next_release_*` is the NEXT scheduled release after it (and after now, so a stale store still names an upcoming one):
`next_release_ist` is the label the hero and the digest print verbatim (`Sat 31 Oct 01:00 IST`, PLAN a.6), `next_release_at`
the ISO instant with the IST offset, `next_report_date` the Tuesday it will cover, `next_release_source` `rule | published`.
`fut_or_combined=C` reports the combined (futures + options) positions as the hero; `options_overlay` is ALWAYS
combined − futures-only (same sign in both modes) and the micro-gold drawer row follows the requested mode.

### 2.6 `/positioning/daily`
COMEX: `{exchange, rows[{trade_date, symbol_or_product ("GC", "MGC", "OG:C", "OG:P"…), product_desc, expiry: null,
open_interest, oi_change, volume, globex_volume, settle_or_close, quality}], quadrant_tape[{trade_date, dprice_pct, doi,
label, label_note, mechanical, volume, volume_vs_20d, volume_avg_sessions, churn}], put_call_oi_ratio, roll{front, next,
front_oi, next_oi, ratio, days_to_tender_or_fnd, days_unit: "calendar days", fnd_date, ltd_date, fnd_source, note}, since,
badge: "context", evidence, read, freshness, as_of, store_errors}`. A tape row without an OI change has `label: null` and
`label_note: "no OI yet (CME file lands T+1 ≈ 15:30 IST)"` — never "flat"; `volume_vs_20d` is `null` until 5 prior sessions
exist (`volume_avg_sessions` counts them; C-DATA-19 / C-BEGINNER-24). `roll.fnd_date` is the FRONT month's own first
notice (gold_events in any spelling of the month, else the CME PRF, `fnd_source` says which).
MCX: the same with `family`, rows per expiry (`quality: "proxy"`, `session_date`, `sessions_spanned`), the tape rows
carrying `sessions_spanned, multi_session, span_note` (`"over 3 sessions (master skipped 2)"` when the master skipped
days — a 29 Oct → 3 Nov OI change is never printed as one day's; data-service's own count wins when the row carries it;
C-TRADER-18), `roll.tender_start` = the 1st of the expiry month (contract spec) with `roll.days_unit: "calendar days"`
(C-TRADER-28), `badge: "arithmetic"`.

### 2.7 `/curve`
`{exchange, family, date, points[{expiry, symbol, settle_or_last, source, quality, open_interest, oi_change, volume,
trade_date, session_date, days_to_expiry, band_lo, band_hi, spread_vs_front, annualised_carry_pct, flags[PROXY|LAST TRADE|EXPIRY WEEK],
first_notice, days_to_fnd, last_trade, days_to_ltd (COMEX only, from the CME PRF — a long must leave by FND, C-TRADER-24)}],
ghost_1w[…], ghost_date, basis{mcx_front_inr, mcx_front_session, mcx_front_session_label, mcx_front_quality, landed_inr,
duty_pct, duty_effective, duty_notification, duty_note, duty_paid_landed_inr, basis_pct, basis_clock: "settlement",
basis_label, basis_date, basis_source, live_basis_pct, live_basis_label, mcx_live, carry_pct, basis_carry_adj_pct,
usdinr, usdinr_source, ts, ts_note, badge}|null (MCX only), history[{trade_date, basis_pct, premium_pct}] (MCX) or
[{trade_date, carry_ann_pct}] (COMEX), price_label, since, badge: "arithmetic", freshness, store_errors}`.
`annualised_carry_pct` is ALWAYS vs the front expiry — the one carry convention of the page (`/contracts.expiries[].carry_pct`
uses the same function and the same reference; C-DATA-16). `basis.basis_pct` is the settlement-clock basis (the stored
`MCX_BASIS_PCT` row of the settlement session when it exists, the desk's figure for that session otherwise — the SAME number
the HEALTH gauge and the PHYSICAL ladder print); `landed_inr` / `duty_paid_landed_inr` are now, `ts_note` says so; the
live-clock pair (`live_basis_pct`, `mcx_live`) is present only while the page holds a quote.

### 2.8 `/contracts`
```
{ as_of, exchange: "MCX", families[{code, name, breeze_code, lot, lot_grams, quote_unit, purity, expiry_rule, cycle,
    expiries[{expiry, source: observed|computed, settle, settle_quality, band_lo, band_hi, oi, oi_change, margin_inr, margin_pct,
              margin_source, margin_date, carry_pct, carry_convention, comex_matched, comex_matched_calendar, comex_matched_note,
              tender_start, days_to_tender, days_unit, days_to_expiry}],
    tick_rupees, tick_value, multiplier, round_trip{legs{buy, sell}, total, pct, breakeven_ticks, price, assumptions}|null,
    one_pct_move_inr, notional_inr, hedge_ratio_oz, delivery_unit, tender_cutoff_note, options{available, expiries, strike_step, note},
    notes, badge: "arithmetic"}],
  comex_matched_by_family{GOLD: "GCZ26.CMX", …}, comex_front{expiry, symbol, price, source}|null,
  diff_keys[lot, tick_value, margin_pct, round_trip.pct, oi, purity, expiry_rule, hedge_ratio_oz, one_pct_move_inr],
  other_exchanges[{exchange: NSE|BSE, available: false, reason}], master{available, published, session, session_label},
  margin_note, badge, freshness, comex_spec (only ?exchange=COMEX; null until gold_cme_prf is readable), store_errors }
```
Families in selector order: `GOLD, GOLDM, GOLDTEN, GOLDGUINEA, GOLDPETAL` (GOLDTEN: 10 g lot, ₹/10 g, 999, month-end,
tick ₹1 = ₹1/lot, Breeze `GOLDTE`). `expiries[].oi_change` is joined from the latest stored MCX curve rows
(`/db/gold/curve?exchange=MCX`, by family + expiry); `null` until the India ingest has two sessions of that expiry.
`carry_pct` is annualised vs the FRONT expiry (`carry_convention`), `null` on the front row itself — the same convention
and function as `/curve` (C-DATA-16). `comex_matched` is the nearest LIQUID COMEX month (Feb/Apr/Jun/Aug/Oct/Dec): a
GOLDM / GUINEA / PETAL expiry in a serial month maps to the next liquid month with `comex_matched_note: "nearest liquid
COMEX month"`, the calendar month kept in `comex_matched_calendar` (C-BEGINNER-26). `tender_start` is the 1st of the expiry
month, `days_unit: "calendar days"`.
`comex_spec` (`?exchange=COMEX`) is the DES card of the MATCHED month: `{symbol, mmy, month, yahoo_symbol, picked_by,
description, sec_type, uom, uom_label, uom_qty, multiplier, min_px_incr, display_factor, tick_usd, tick_value_usd,
settl_method, settl_method_label, init_margin_usd, margin_pct_of_notional, margin_date, ref_price, first_notice,
days_to_first_notice, last_notice, last_trade, days_to_last_trade, first_trade, mat_date, elig_block, elig_efp,
margin_history[{trade_date, margin_usd}], margin_history_note, badge}` — the PRF row whose `mmy` equals the matched month
(`GCZ26.CMX` → 202612; else the first month still trading, `picked_by` says so), tick = MinPxIncr × the display factor
(`$0.10 = $10`), `P` → `physical delivery`, `oz_tr` → `troy oz`, margin history = that month's stored rows, one per trade
date, rows under $1,000 (spreads / stubs) dropped and a stub `init_margin` nulled (C-TRADER-13 / C-DATA-8 / C-BEGINNER-4).

### 2.9 `/premiums`
`{india{ladder[{step: comex|usdinr|landed|duty|duty_paid|ibja|mcx, label, value, ts, ts_label?, clock: now|fix|settlement|"dated constant",
source, unit}], premium_pct, premium_date, premium_clock, premium_note, ibja_date, fineness_adjustment, basis_pct, basis_date,
basis_label, basis_source, live_basis{value, mcx_live, duty_paid_landed, as_of, label, clock}|null, carry_adj_pct,
duty{pct, effective, notification, note, history[{effective, pct}]}, history[{report_date, premium_pct, basis_pct}],
badge{ladder: arithmetic, premium: context}, clock_note, freshness},
shanghai{sge_pm_cny_g, usdcny, usdcny_source, sge_usd_oz, london_pm_usd, comex_at_1415_bj, premium_usd, premium_pct, pair_date,
pairing, note, ts_sge, ts_ref, history[], badge, clock_note, freshness}, reference{wgc_india, wgc_india_week, wgc_china,
wgc_china_week, reuters_url, attribution}, as_of, store_errors}`.
**One clock per ratio (wave 1c).** `india.premium_pct` is the STORED fix-minute `INDIA_PREMIUM_PCT` (IBJA 999 PM ÷ duty-paid
landed sampled at the fix, × 995/999, derived by data-service's 21:30 job) dated `premium_date`; it is never the PM fix
divided by the ladder's live duty-paid bar (C-TRADER-4 / C-BEGINNER-2 / C-DATA-11). When IBJA has a newer fix than the
stored premium, `premium_note` says which date is shown; with nothing stored the premium is `null` with the reason. Every
ladder step names its `clock`: the five left-hand bars are `now`, IBJA is its `fix`, MCX is the `settlement` (its label
carries the settlement-clock basis `(basis +1.58 % at the Tue 03 Nov settlement vs that session's duty-paid landed)`);
`live_basis` is the live pair when a quote exists (C-BEGINNER-5). `india.history[].basis_pct` is the basis of THAT date
only, never carried forward (C-DATA-20). `shanghai.premium_usd` pairs SGE PM and LBMA PM of the SAME `pair_date` only
(`pairing: "same report date (…)"`); when today's London PM is not stored the last stored `SHANGHAI_PREMIUM_USD` stands
(`pairing: "last stored same-date pair"`, `note: "awaiting today's PM: SGE Wed 04 Nov is in, its London PM is not stored
yet"`, `ts_sge` newer than `ts_ref`); never SGE against an earlier London fix (C-TRADER-5 / C-DATA-10).

### 2.10 `/flows`
`{etf[{report_date, fund, tonnes, chg_1d, chg_5d, chg_1m, chg_ytd, cumulative_30d[], source}], wgc_weekly[{week_ending,
region: GLOBAL|NA|EU|ASIA|OTHER, flow_t, holdings_t}], wgc_india_holdings_t, official[{country, month, oz, oz_mn, tonnes,
chg_oz_mn, chg_t, chg_12m_oz_mn, chg_12m_t, unit_note}], rbi{week, usd_mn, share_pct, tonnes, tonnes_month, tonnes_source,
tonnes_est: null, inr_cr, note}, otc{lbma_turnover_usd_bn, week_ending, turnover_tonnes_est, vault_t, vault_month, vault_chg_t,
efp{today_rt, date, avg_20d, avg_sessions, since, avg_note, pct_of_volume}, read},
physical_monthly{sge_withdrawals_kg, sge_withdrawals_month, india_imports_usd_bn, india_imports_month, india_imports_yoy_pct,
swiss_exports_in_kg, amfi{net_cr, aum_cr, month, tonnes_est, evidence}}, balance_sheet[{period, series, tonnes}],
badge: "context", evidence, attribution, freshness{etf, wgc_weekly, official, rbi, otc}, as_of, store_errors}`.
**Units (wave 1c).** IMF IFS stores TROY OUNCES: `official[].oz` is the raw value, `oz_mn = oz ÷ 1e6`, `tonnes = Moz ×
31.1035` (India 28,309,311 oz → 28.309 Moz → 880.5 t; the old shape printed 21,634,000 "Moz" and 672,892,617 "t" for
Poland — C-TRADER-6 / C-BEGINNER-3 / C-DATA-5); the changes are in Moz and t; sorted by ounces. `rbi.tonnes` is the IMF's
reported ounces for India in tonnes (`tonnes_month`, `tonnes_source`), the one tonnage on the page; the price-implied
`tonnes_est` is a `null` alias for one release (C-TRADER-22). `otc.efp.avg_20d` is `null` until 5 PRIOR sessions exist
(`avg_sessions`, `since`, `avg_note: "average needs 5 prior sessions; 1 stored since Tue 3 Nov"` — C-TRADER-21 / C-DATA-19).

### 2.11 `/macro`
`{as_of, window, drivers[{key: real_10y|nominal_2y|breakeven_10y|dxy|usdinr|gvz|brent|gld_t, label, label_note, value, unit, report_date,
d1, d1w, d1m, d_window, change_unit, d1_bp, pct_1y, corr_60d, tag: supportive|headwind|null, rule, series_id, badge, evidence, state}],
kgx{period, from_date, total_pct, usd_effect_pct, pure_gold_pct, inr_effect_pct, weights{}, badge, line, note, inr_note},
currencies[{ccy: USD|INR|EUR|JPY|GBP|CNY, price, unit, d1, d1w, d1m, ytd, badge}],
fed{meetings[{meeting, p_cut, p_hike, p_hold, mean_bp, p10_bp, p90_bp}], as_of, source, zq[{month, implied_pct}], effr, effr_date,
target, next_fomc_ist, after_mcx_close, next_fomc{date_et, ist, at, statement_ist, name, kind: "FOMC", source, after_mcx_close, days}|null,
speakers[{date, time_ist, title, impact, kind: "FOMC_SPEECH"}], badge, fedwatch_link},
calendar[{date, time_ist, title, kind, country, impact, impact_rank, star, forecast, previous, actual, in_session, days}] (this week),
move{gvz, gvz_date, sigma_day_pct, usd_oz, inr_10g, per_lot{GOLD, GOLDM, GOLDTEN, GOLDGUINEA, GOLDPETAL}, realised_20d, atr14_usd, atr14_inr, read, badge},
driver_health{rolling_corr[{year, real_yield, dxy}], betas_by_regime[{regime, beta_real_yield_per_100bp, beta_dxy}], beta_units{}, dxy_series, lesson},
context{gsr, gsr_pct, gpr_m, gpr_pct_m, gpr_pct_d, hy_oas, hy_oas_date, gold_m2_pct, badge}, badge, freshness{drivers, fed, gold}, store_errors}`.
KGX identity holds on the printed numbers: `pure_gold_pct = total_pct − usd_effect_pct` (DXY weights; a stronger dollar is a
negative usd effect; the rupee leg is USD/INR's own change); when a leg is missing `kgx.note` / `kgx.inr_note` say why in
words (`USD effect unavailable: no DXY-basket FX closes stored for this window …`; C-BEGINNER-14). The `dxy` driver is
labelled by the series actually used: `Dollar index (DXY)` for `DXY_CLOSE`, `Fed broad USD index (DTWEXBGS, weekly lag —
not DXY)` with `label_note: "stand-in: …"` when the FRED fallback is used — never DTWEXBGS under the DXY name (C-DATA-4 /
C-TRADER-8); `driver_health.dxy_series` names the one the correlations / betas use and `beta_units` spell the units
(`% gold per +100 bp …`, `% gold per +1 % …`; C-DATA-21). **FOMC (wave 1c).** data-service tags every Forex-Factory
"FOMC …" title as kind `FOMC`; ui-api separates them: the decision keeps `FOMC`, `FOMC Member X Speaks` → `FOMC_SPEECH`,
the minutes → `FOMC_MINUTES`. `fed.next_fomc` is the next DECISION only (the `Federal Funds Rate` row wins on a day with
several; else the first Atlanta-Fed meeting date with the statement time computed, 14:00 ET → `23:30 IST` in summer,
`00:30 IST` the next day in winter), never a speaker (C-TRADER-12 / C-DATA-9); `next_fomc_ist` is its label
(`2026-12-10 00:30 IST`), `next_fomc.at` the instant with the offset; `fed.speakers` lists this week's speeches on their
own. `calendar` is this week's rows with nothing already past (a release out at 08:00 is not "next" at 10:00; C-DATA-21),
each with `impact_rank` (FOMC decision / High = 0 … Low = 4) and `star` (High impact or an FOMC decision only).

### 2.12 `/calendar`
`{as_of, days, count, events[{event_date, date, time_ist, kind, kind_stored, name, detail, country, impact, forecast, previous,
actual, in_session, after_close, star, impact_rank, past, days, source, first_seen_at}], badge, freshness, store_errors}` — stored
`gold_events` rows merged with computed rows (`MCX_EXPIRY` per family, `MCX_HOLIDAY`, `MCX_SPECIAL` Muhurat, `COT_RELEASE`
by the holiday-aware CFTC calendar of §0 — `detail` says `Mon 16 Nov 15:30 ET = Tue 17 Nov 02:00 IST — the Monday after a US
federal holiday`), deduped on (date, kind, name), sorted by date/time. Stored rows pass through with their own extra columns
(`first_seen_at` re-stamped with its offset). Every row is decorated (wave 1c): `kind` is the page kind (`FOMC_SPEECH` /
`FOMC_MINUTES` split off `FOMC`, `kind_stored` keeps the store's word when relabelled), `star` (High impact or an FOMC
decision), `impact_rank` (0 = decision / High … 4 = Low, 5 = unknown) and `past` (today's row whose IST time has passed).

### 2.13 `/log`, `/catalog`, `/brief`, LEARN, POSTs
- `/log` → `{rows[{date, snapshot_at, contract, expiry, comex_symbol, baseline, baseline_source, baseline_session, stale_baseline,
  fair_open, threshold, duty_pct, comex_ref, comex_now, inr_ref, inr_now, event_risk, inputs_json, actual_open, actual_source,
  captured_at, error, naive_error}], stats{days, mean_abs_error, median_abs_error, bias, within_threshold_pct,
  naive_mean_abs_error, p90_abs_error, p90, threshold}, badge, source, read}`; `POST /log/actual {date, open}` → the row.
- `/catalog` → `{as_of, rows[CatalogRow], count, verdicts{PUBLISH-CORE, PUBLISH-CONTEXT, LINK-ONLY, DO-NOT-PUBLISH}, badges{…}}`.
- `/brief` → `{available: false, report_date, note}` or `{available: true, report_date, generated_at, bias, bias_score, confidence,
  model_fair_open, overnight_summary, open_plan, key_risks_today[], doc{}, data_quality, stripped_fields[], label, badge}`.
  `bias` / `confidence` are top-level (the writer's own fields). **No trade-implying field leaves the server** (wave 1c,
  C-TRADER-15 / C-DATA-12): `open_signal` is gone from the payload and every key matching
  `signal|trade|entry|exit|stop_loss|target|recommend|position_size` is dropped from `doc` at every depth
  (`gold.scrub_trade_fields`); `stripped_fields` lists the dropped paths (`doc.gap.open_signal`, `row.open_signal`, …) so
  the omission is visible, never silent. `open_plan` / `key_risks_today` / `data_quality` stay.
- `/learn/glossary` → `{version, count, query, terms[{term, short, long, see_also[]}], dangling_see_also[], source}` (ranked:
  exact → starts with → contains → short → long; empty `q` = alphabetical). `/learn/tooltips` → `{version, count, panels[], tooltips{}, source}`.
- `POST /snapshot` (409 on weekends, full **and morning-closure** MCX holidays and after the open unless `force=1`),
  `POST /capture-open` (409 before the session opens: 17:00 on a morning closure), `POST /invalidate` → `{invalidated, before{store, memo}, at}`.

### 2.14 `/overview`
`{as_of, window, contract{mcx, name, expiry, expiry_source, comex_matched, comex_matched_calendar, comex_matched_note, comex_front: "GC=F",
spot_proxy_note, lot, tick_value, quote_unit, master_published, band{}}, session{mcx{is_open, segment, opens_at, closes_at, holiday,
seconds_to_open, seconds_to_close, weekend}, comex{is_open, note}},
strip{comex_matched, comex_matched_calendar, comex_matched_note, comex_matched_settle, comex_matched_settle_date, comex_matched_last,
comex_matched_last_date, comex_matched_last_label, comex_matched_last_source, comex_live, comex_live_symbol, comex_live_as_of,
comex_live_chg_pct, comex_ref_note, usdinr, usdinr_as_of, real_10y, real_10y_date, mcx_live, mcx_live_source, mcx_live_as_of,
mcx_live_vs_settle_pct, mcx_shown: live|settlement, mcx_settle, mcx_settle_session, mcx_settle_session_label, mcx_settle_quality,
basis_pct, basis_clock: now|settlement, basis_label, basis_live_pct, basis_settle_pct, basis_settle_date, basis_session (= basis_settle_date),
basis_session_label (= the settlement basis label), cot_mm_net, cot_mm_chg, cot_as_of, crosscheck{price, at, source}|null,
instruments{spot, front, matched, mcx}}, health{…2.1}, fair{…2.2}, quote{…/api/mcx/quote}, headlines[≤12],
brief{available, report_date, bias, confidence, overnight_summary, open_plan, key_risks_today[], stripped_fields[]},
calendar[the FULL next 7 days], freshness{health, fair, quote, cot, brief}, errors{}}`.
**The header strip (wave 1c).** `comex_matched` is the nearest LIQUID month (C-BEGINNER-26; `comex_matched_calendar` the
calendar month the desk's own fair leg prices, `comex_matched_note` when they differ). `comex_matched_settle` is a CME
bulletin settlement only (still `null` until O-2); `comex_matched_last` / `_date` / `_label` is that month's own stored
price from the curve job's per-month daily bars, labelled `last trade (Yahoo per-month daily bar), not a settlement` — the
first number of the page is never blank beside a live price (C-TRADER-9). `comex_live` is the desk's live leg
(`comex_live_symbol` names the month it prices). **During MCX hours the header is the live MCX** (`mcx_live` from the
page's own Breeze quote, `mcx_shown: "live"`) with the settlement beneath (`mcx_settle`, its session label) and
`mcx_live_vs_settle_pct`; `basis_pct` is live MCX ÷ duty-paid landed now (`basis_clock: "now"`) while a quote exists,
else the settlement-clock figure (`basis_settle_pct`, `basis_settle_date`, `basis_label` naming the session) — the same
number as `health.gauges[india_basis]`, which `/overview` re-derives on the same quote (`gold.apply_live_mcx`: the fair
block's `mcx_live` / `desk_verdict_state`, the gauge and the verdict sentence are re-run on it, so one page never shows two
desk states or two basis clocks; C-TRADER-10 / C-DATA-13 / C-BEGINNER-5). `calendar` is the FULL next 7 days (stored rows
+ the computed MCX / COT rows), nothing already past, sorted by `impact_rank` then date/time, each row decorated as in
§2.12 (`star` only on High impact or an FOMC decision) — the HEALTH event strip renders it as is (C-TRADER-11 / C-DATA-21).

## 3. TOTP routes (PLAN §g)

| Route | Body → reply |
|---|---|
| `GET /api/positions/totp/status[?reveal=1]` | `{configured, source: env\|keychain\|null, keychain_present, env_mode: "0600", env_mode_ok, auto_login_enabled, login_running, otp_pending, last_login{at, status, detail}\|null, next_run_ist, block{credentials, totp}, keychain_hint}` + with `reveal=1` `code`, `seconds_left` (computed server-side; never the secret) |
| `POST /api/positions/totp/preview {secret}` | `{valid: true, digits, period, algorithm, length, code, seconds_left}`; stores and logs nothing; accepts base32 (spaces/dashes/lower case) or `otpauth://` (percent-encoded); bad key → **400** `{detail: "<fixed message>", error{code: invalid}}` that never contains the input |
| `POST /api/positions/totp {secret, confirm_code}` | refused (400, fixed message) unless `confirm_code` equals the current **or previous** 30-s window; saves bare base32 through `icici_admin.persist_env_updates` (allowlisted `ICICI_TOTP_SECRET`, exactly one line, mode preserved) → `{saved, persisted, persisted_reason, env_path, source: "env", env_mode, env_mode_warning, keychain_present}` |
| `DELETE /api/positions/totp` | writes `ICICI_TOTP_SECRET=` → `{cleared, persisted, persisted_reason, keychain_still_present, keychain_hint}`; ui-api never deletes a Keychain item |

The RFC 6238 vector (secret `12345678901234567890` base32 `GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ`, t = 59) → `287082`.
Blocking pieces (Keychain probe, pgrep, the .env write) run in `asyncio.to_thread`.

## 4. What ui-api expects from data-service (B1 `/db/gold/*`)

Every read tolerates `{rows:[…]}`, `{data:[…]}`, `{columns, data}` or a bare list. Specifics used:
`/db/gold/series` → `{series:[{series_id, points[{report_date, value, release_at}]}]}` (or long rows);
`/db/gold/cot?weeks&report&fut_or_combined&contract` → `{rows}` in `gold_cot` columns (`contract` = 088691 / 088695);
`/db/gold/bars?symbol&interval&from&to` → `{rows[{trade_date|ts, open, high, low, close, volume}]}` with Yahoo symbols;
`/db/gold/curve?exchange&date` → `{rows, ghost_1w}` (the embedded `ghost_1w` is used; a `date=` read is the fallback);
`/db/gold/curve?exchange=MCX` → `{rows}` (the latest MCX curve: `oi_change` per family + expiry for `/contracts`);
`/db/gold/curve/history?exchange=MCX&symbol&days` → `{rows}` (the MCX daily OI tape); `/db/gold/cme/voi?from&products`,
`/db/gold/cme/efrp?from`, `/db/gold/margins?exchange&date`, `/db/gold/etf?from`, `/db/gold/fed-path`, `/db/gold/events?from&to`,
`/db/gold/catalog`, `/db/gold/brief?date` → `{available, report_date, row, doc}`. `/db/gold/cme/prf?symbol=GC` is **optional**
(the COMEX spec card is `null` without it).

## 5. Other router changes shipped by B3

- `routers/mcx.py`: `MASTER_ALIASES`/`BREEZE_CODE` carry `GOLDTEN`/`GOLDTE` (fallback spec until `shared/mcx_specs` has the row);
  `_fair_value` uses `gold_preopen._yahoo_bars_cached` (one fetcher); `/api/mcx/overlay` returns the one-line block
  (`line`, `fields`, `link: "GOLD"`) beside the legacy keys; `/api/mcx/ticket` adds `max_lots_at_risk_pct`, `hedge_usdinr_lots`,
  `atr14_rupees`, `margin_source`, `margin_date`; `/api/mcx/specs.selector_note` points at `/api/gold/contracts`.
- `routers/gold_preopen.py`: `baseline.session_label` (session, never the file date), `holiday{}`, prefs-driven
  `eurusd_trigger`/topics (`gold.triggers.v1`), `inputs_json` on every snapshot row, `stale_baseline` per row, the duty leg
  (`landed`, `duty_paid_landed`, `basis_pct`; `implied_premium_pct` deprecated alias), conditional-GET master loader
  (`If-Modified-Since`), dual-write of every log row to data-service `POST /jobs/gold-log` (daemon thread, never under pytest),
  snapshot gate skips morning-closure holidays.
- `routers/commodity.py`: keyless FRED (`fredgraph.csv`) when `FRED_API_KEY` is unset; the desk is no longer advertised.
- `routers/research.py`: CATALOG rows for the gold reports (listed when the file exists).
- `icici_admin.ICICI_ENV_KEYS` gains `ICICI_TOTP_SECRET`.

## 6. Degrade matrix

| Failure | Effect |
|---|---|
| data-service down / gold tables not deployed (404) | each stored block `unavailable`, `store_errors` names the path; `/cot` → `ok: false`; `/health` verdict says "no fresh gauge" and still ends "describes, does not predict" |
| catalog unreadable (and the 3600 s memo empty) | strict gate (§0): every catalog-gated number is `null` with `published: false, note: "catalog unavailable — not published"`; nothing renders from an unverified series |
| Yahoo 429 / down | `fair`, `comex_live`, `basis` null with `freshness.state = unavailable`; nothing retries on the request path (SWR + 60 s negative cache in `mcx._fair_value`) |
| ICICI master unreachable | computed expiries (`source: "computed"`), no settlement, `master.available: false` |
| Breeze session invalid / MCX quote 500 | `quote.available: false` with the reason (10-minute memory); `mcx_live` null |
| LEARN files missing | `{count: 0, terms: []}` / `{tooltips: {}}` |

## 7. Deviations from PLAN §d (deliberate)

1. `/health` adds `brf_line` and `lines{wei, brf}`: `line` is the WEI second line, `brf_line` the BRF form (PLAN §b).
2. `/fair` adds `today_log`, `contract_fair` and `freshness`; `accuracy.p90` mirrors `p90_abs_error`.
3. `/cot` uses the fund-driver rule of data-service `gold/driver_rule.py` (the one rule; mirrored, not imported — ui-api's
   image need not carry data-service's source tree; a test loads the file by path and pins every branch); `driver_rule`
   carries its text; `who_did` says `new … longs` / `covered … shorts`; `latest.stale` is a 10-day catch-up flag.
4. `/positioning/daily?exchange=MCX` reads `/db/gold/curve/history` (B1's range endpoint) — `family` param added.
5. `/contracts.comex_spec` is `null` until data-service exposes `gold_cme_prf` (`/db/gold/cme/prf`, not in c.5).
6. `/calendar` computes MCX expiries/holidays/Muhurat and COT releases itself so the page has them before the store does.
7. `/overview.strip.comex_matched_settle` is `null` (bulletin settlements wait on O-2); `comex_matched_last` carries the
   month's stored last trade, labelled; `comex_live` is the desk's live leg (`comex_live_symbol`).
8. The TOTP routes live on `routers/positions.py` (per the B3 brief), not a separate `routers/icici_totp.py`.
9. `/api/mcx/ticket` keeps its legacy keys; the sizing keys are additive.
10. BRF's pre-open line (PLAN §b) prints `OK` / `WAIT` only once the desk's rule has a price (the cached MCX quote or the
    manual one): before that the line carries the fair value and the gap without a verdict word, because `AWAITING_OPEN`
    is neither — the desk's own `verdict` says "trade the open only if MCX opens within ₹300 of fair".
11. `/cot.latest.next_release_ist` is a LABEL (`Sat 31 Oct 01:00 IST`), as PLAN a.6 prints it and the Saturday digest
    appends it verbatim; the machine-readable instant is `next_release_at`.
12. The ONE Yahoo fetcher (`gold_preopen._yahoo_bars_cached`) still calls `query1.finance.yahoo.com` with the GoldDesk UA
    (pre-existing code, 24 months in production); PLAN 0.1 #2 says `query2` + the app's UA. Not changed in wave 1b: the
    host string cannot be re-tested live under the no-Yahoo rule, and a 429 on the 08:45 snapshot is the known failure
    mode (26 Oct 2026). Owner / PM decision before a change; it is a one-line edit with a fixture-replay test.
13. (wave 1c) `/brief` no longer returns `open_signal`; trade-implying keys are scrubbed from `doc` and listed in
    `stripped_fields` (PLAN 0.1 #7: nothing on the page implies a trade).
14. (wave 1c) `fed.next_fomc_ist` is a LABEL with its zone (`2026-12-10 00:30 IST`); the instant is `fed.next_fomc.at`.
15. (wave 1c) `rbi.tonnes_est` is a `null` alias for one release; the tonnage is `rbi.tonnes` (IMF ounces).
16. (wave 1c) Event kinds `FOMC_SPEECH` / `FOMC_MINUTES` are ui-api's split of the store's `FOMC` (`kind_stored` keeps
    the original); data-service may adopt the split at ingest later without a contract change.
17. (wave 1c) `/health`, `/overview.health` and `/premiums` all print the settlement-clock basis from the SAME stored
    `MCX_BASIS_PCT` row (or the desk's figure for that session before the 21:30 derive); the desk's `fair.basis_pct`
    (`gold_preopen.fair_open`) stays as the fallback source and the `implied_premium_pct` alias is unchanged.

## 8. Key inventory (generated)

<!-- generated: key inventory — begin -->

Generated by `services/ui-api/tests/test_gold_contract.py` from the fixture payloads (pinned clock Mon 26 Oct
2026, the agents' samples). `path[]` = list element, `{*}` = data-keyed map (dates / series ids / tooltip keys),
types =
every JSON type the fixture produced for that key (`null` means the key may be null). Regenerate with
`GOLD_CONTRACT_WRITE=1 python -m pytest services/ui-api/tests/test_gold_contract.py -q`; the test fails until the
document matches the code.

#### `/api/gold/overview` (overview)
```
as_of: string
brief: object
brief.available: bool
calendar: array
calendar[]: object
calendar[].country: string
calendar[].days: number
calendar[].detail: string
calendar[].event_date: string
calendar[].first_seen_at: null
calendar[].impact: string
calendar[].impact_rank: number
calendar[].in_session: bool
calendar[].kind: string
calendar[].kind_stored: null|string
calendar[].name: string
calendar[].past: bool
calendar[].source: string
calendar[].star: bool
calendar[].time_ist: string
contract: object
contract.band: object
contract.band.band_high: number
contract.band.band_low: number
contract.band.expiry: string
contract.band.open_interest: number
contract.band.settlement: number
contract.comex_front: string
contract.comex_matched: string
contract.comex_matched_calendar: string
contract.comex_matched_note: null
contract.expiry: string
contract.expiry_source: string
contract.lot: string
contract.master_published: string
contract.mcx: string
contract.name: string
contract.quote_unit: string
contract.spot_proxy_note: string
contract.tick_value: number
errors: object
fair: object
fair.accuracy: object
fair.accuracy.badge: string
fair.accuracy.bias: null
fair.accuracy.days: number
fair.accuracy.mean_abs_error: null
fair.accuracy.median_abs_error: null
fair.accuracy.naive_mean_abs_error: null
fair.accuracy.p90: null
fair.accuracy.threshold: number
fair.accuracy.within_threshold_pct: null
fair.as_of: string
fair.badge: string
fair.baseline: object
fair.baseline.close_time: string
fair.baseline.master_published: string
fair.baseline.session: string
fair.baseline.session_label: string
fair.baseline.settlement_from_band: number
fair.baseline.source: string
fair.baseline.stale: bool
fair.baseline.value: number
fair.context: array
fair.context[]: object
fair.context[].at_close: number
fair.context[].change: number
fair.context[].key: string
fair.context[].label: string
fair.context[].signal: string
fair.context[].symbol: string
fair.context[].trigger: number
fair.context[].trigger_state: string
fair.context[].unit: string
fair.context[].value: number
fair.contract: object
fair.contract.band_high: number
fair.contract.band_low: number
fair.contract.band_pct: number
fair.contract.comex: string
fair.contract.expiry: string
fair.contract.name: string
fair.contract.open_interest_lots: number
fair.duty: object
fair.duty.effective: string
fair.duty.note: string
fair.duty.notification: string
fair.duty.pct: number
fair.event_risk: object
fair.event_risk.advice: null
fair.event_risk.badge: string
fair.event_risk.flagged_headlines: number
fair.freshness: object
fair.freshness.age_s: number
fair.freshness.as_of: string
fair.freshness.source: string
fair.freshness.state: string
fair.headlines: array
fair.holiday: null
fair.manual_checks: array
fair.manual_checks[]: object
fair.manual_checks[].name: string
fair.manual_checks[].url: string
fair.manual_checks[].what: string
fair.mcx_price: object
fair.mcx_price.broker: null
fair.mcx_price.source: null
fair.mcx_price.value: null
fair.model: object
fair.model.basis_pct: number
fair.model.comex: object
fair.model.comex.as_of: string
fair.model.comex.now: number
fair.model.comex.ref: number
fair.model.comex.ref_how: string
fair.model.comex.symbol: string
fair.model.comex_part: number
fair.model.duty_paid_landed: number
fair.model.duty_pct: number
fair.model.fair_open: number
fair.model.gap: number
fair.model.gap_pct: number
fair.model.implied_premium_pct: number
fair.model.inr: object
fair.model.inr.as_of: string
fair.model.inr.now: number
fair.model.inr.ref: number
fair.model.inr.ref_how: string
fair.model.inr.symbol: string
fair.model.inr_part: number
fair.model.landed: number
fair.model.lot_pnl_per_rupee: number
fair.model.rs_per_comex_dollar: number
fair.model.rs_per_inr_rupee: number
fair.model.threshold_in_comex_dollars: number
fair.notes: array
fair.notes[]: string
fair.threshold: number
fair.today_log: null
fair.verdict: object
fair.verdict.badge: string
fair.verdict.detail: string
fair.verdict.state: string
fair.verdict.title: string
freshness: object
freshness.brief: object
freshness.brief.age_s: null
freshness.brief.as_of: null
freshness.brief.source: string
freshness.brief.state: string
freshness.cot: object
freshness.cot.age_s: number
freshness.cot.as_of: string
freshness.cot.source: string
freshness.cot.state: string
freshness.fair: object
freshness.fair.age_s: number
freshness.fair.as_of: string
freshness.fair.source: string
freshness.fair.state: string
freshness.health: object
freshness.health.age_days: number
freshness.health.oldest: number
freshness.health.stale: array
freshness.health.stale[]: string
freshness.health.state: string
freshness.health.unavailable: array
freshness.health.unavailable[]: string
freshness.quote: object
freshness.quote.age_s: null
freshness.quote.as_of: null
freshness.quote.source: string
freshness.quote.state: string
headlines: array
health: object
health.as_of: string
health.brf_line: string
health.fair: object
health.fair.actual_open: null
health.fair.actual_open_source: null
health.fair.badge: string
health.fair.basis_pct: number
health.fair.comex: object
health.fair.comex.as_of: string
health.fair.comex.price: number
health.fair.comex.symbol: string
health.fair.comex_symbol: string
health.fair.contract: string
health.fair.desk_verdict_state: string
health.fair.duty_effective: string
health.fair.duty_note: string
health.fair.duty_paid_landed: number
health.fair.duty_pct: number
health.fair.expiry: string
health.fair.expiry_source: string
health.fair.fair_value: number
health.fair.freshness: object
health.fair.freshness.age_s: number
health.fair.freshness.as_of: string
health.fair.freshness.source: string
health.fair.freshness.state: string
health.fair.gap_vs_settlement: number
health.fair.implied_premium_pct: number
health.fair.landed: number
health.fair.mcx_holiday: null
health.fair.mcx_live: null
health.fair.mcx_live_as_of: null
health.fair.mcx_live_source: null
health.fair.premium_pct: null
health.fair.premium_rupees: null
health.fair.settlement: number
health.fair.settlement_quality: string
health.fair.settlement_session: string
health.fair.settlement_session_label: string
health.fair.snapshot_error: null
health.fair.snapshot_fair: null
health.fair.usdinr: object
health.fair.usdinr.as_of: string
health.fair.usdinr.price: number
health.fair.usdinr.symbol: string
health.freshness: object
health.freshness.age_days: number
health.freshness.oldest: number
health.freshness.stale: array
health.freshness.stale[]: string
health.freshness.state: string
health.freshness.unavailable: array
health.freshness.unavailable[]: string
health.gauges: array
health.gauges[]: object
health.gauges[].age_days: null|number
health.gauges[].annualised_pct: number
health.gauges[].badge: string
health.gauges[].basis_label: string
health.gauges[].change: null|number
health.gauges[].change_bp: number
health.gauges[].change_pct: number
health.gauges[].change_unit: null|string
health.gauges[].change_window: string
health.gauges[].chg_5d: number
health.gauges[].chg_long: number
health.gauges[].chg_short: number
health.gauges[].clock: string
health.gauges[].cot_index_52: number
health.gauges[].days_to_fnd: number
health.gauges[].direction_for_gold: null|string
health.gauges[].drawdown_52w_pct: number
health.gauges[].driver_label: string
health.gauges[].duty_effective: string
health.gauges[].duty_paid_landed_now: number
health.gauges[].duty_pct: number
health.gauges[].evidence: string
health.gauges[].fnd_date: string
health.gauges[].fnd_source: string
health.gauges[].front: string
health.gauges[].ibja_premium_date: string
health.gauges[].ibja_premium_note: string
health.gauges[].ibja_premium_pct: number
health.gauges[].key: string
health.gauges[].label: string
health.gauges[].last_bar_note: null
health.gauges[].last_bar_partial: bool
health.gauges[].live_basis_pct: null
health.gauges[].ltd_date: null
health.gauges[].mcx_live: null
health.gauges[].net_pct_oi: number
health.gauges[].next: string
health.gauges[].percentile_1y: null|number
health.gauges[].percentile_3y: null|number
health.gauges[].read_from: string
health.gauges[].release_at: null|string
health.gauges[].report_date: null|string
health.gauges[].rule: string
health.gauges[].series_id: string
health.gauges[].settle_basis_date: string
health.gauges[].settle_basis_label: string
health.gauges[].settle_basis_pct: number
health.gauges[].settle_basis_source: string
health.gauges[].settlement_session_label: string
health.gauges[].source: string
health.gauges[].state: string
health.gauges[].unit: string
health.gauges[].value: null|number
health.gauges[].vs_200d_pct: number
health.gauges[].vs_20d_pct: number
health.gauges[].week_price_chg_pct: number
health.gauges[].window_from: string
health.gauges[].window_from_value: number
health.gauges[].window_label: string
health.gauges[].window_sessions: number
health.gauges[].words: string
health.line: string
health.lines: object
health.lines.brf: string
health.lines.wei: string
health.store_errors: null
health.verdict: object
health.verdict.badge: string
health.verdict.clauses: array
health.verdict.clauses[]: object
health.verdict.clauses[].note: null
health.verdict.clauses[].rule_id: string
health.verdict.clauses[].series_id: string
health.verdict.clauses[].text: string
health.verdict.clauses[].threshold: null|object
health.verdict.clauses[].threshold.flat_pct: number
health.verdict.clauses[].threshold.min_move_pct: number
health.verdict.clauses[].threshold.notable_t: number
health.verdict.clauses[].threshold.real_yield_bp: number
health.verdict.clauses[].threshold.strong_pct: number
health.verdict.clauses[].threshold.usd_share: number
health.verdict.clauses[].threshold.weak_pct: number
health.verdict.clauses[].value: number
health.verdict.ends_with: string
health.verdict.headline: string
health.verdict.line: string
health.window: string
quote: object
quote.as_of: string
quote.available: bool
quote.best: object
quote.best.price: number
quote.best.source: string
quote.contract: string
quote.error_info: object
quote.error_info.code: string
quote.error_info.hint: string
quote.error_info.message: string
quote.expiry: string
quote.expiry_source: string
quote.fallbacks: object
quote.fallbacks.band: object
quote.fallbacks.band.band_high: number
quote.fallbacks.band.band_low: number
quote.fallbacks.band.open_interest_lots: number
quote.fallbacks.band.quality: string
quote.fallbacks.band.session: string
quote.fallbacks.band.session_label: string
quote.fallbacks.band.settlement: number
quote.fallbacks.band.source: string
quote.fallbacks.fair_value: object
quote.fallbacks.fair_value.basis_pct: number
quote.fallbacks.fair_value.comex: object
quote.fallbacks.fair_value.comex.as_of: string
quote.fallbacks.fair_value.comex.price: number
quote.fallbacks.fair_value.comex.symbol: string
quote.fallbacks.fair_value.duty_effective: string
quote.fallbacks.fair_value.duty_note: string
quote.fallbacks.fair_value.duty_paid_landed: number
quote.fallbacks.fair_value.duty_pct: number
quote.fallbacks.fair_value.fair: number
quote.fallbacks.fair_value.gap_vs_settlement: number
quote.fallbacks.fair_value.implied_premium_pct: number
quote.fallbacks.fair_value.landed: number
quote.fallbacks.fair_value.landed_note: string
quote.fallbacks.fair_value.settlement: number
quote.fallbacks.fair_value.settlement_session: string
quote.fallbacks.fair_value.settlement_session_label: string
quote.fallbacks.fair_value.source: string
quote.fallbacks.fair_value.usdinr: object
quote.fallbacks.fair_value.usdinr.as_of: string
quote.fallbacks.fair_value.usdinr.price: number
quote.fallbacks.fair_value.usdinr.symbol: string
quote.live_verify_pending: bool
quote.lot: string
quote.ok: bool
quote.quote: null
quote.reason: string
quote.tick_value: number
session: object
session.comex: object
session.comex.is_open: bool
session.comex.note: string
session.mcx: object
session.mcx.closes_at: string
session.mcx.holiday: null
session.mcx.is_open: bool
session.mcx.opens_at: string
session.mcx.seconds_to_close: number
session.mcx.seconds_to_open: null
session.mcx.segment: string
session.mcx.weekend: bool
strip: object
strip.basis_clock: string
strip.basis_label: string
strip.basis_live_pct: null
strip.basis_pct: number
strip.basis_session: string
strip.basis_session_label: string
strip.basis_settle_date: string
strip.basis_settle_pct: number
strip.comex_live: number
strip.comex_live_as_of: string
strip.comex_live_chg_pct: number
strip.comex_live_symbol: string
strip.comex_matched: string
strip.comex_matched_calendar: string
strip.comex_matched_last: number
strip.comex_matched_last_date: string
strip.comex_matched_last_label: string
strip.comex_matched_last_source: string
strip.comex_matched_note: null
strip.comex_matched_settle: null
strip.comex_matched_settle_date: null
strip.comex_ref_note: string
strip.cot_as_of: string
strip.cot_mm_chg: number
strip.cot_mm_net: number
strip.crosscheck: null
strip.instruments: object
strip.instruments.front: string
strip.instruments.matched: string
strip.instruments.mcx: string
strip.instruments.spot: string
strip.mcx_live: null
strip.mcx_live_as_of: null
strip.mcx_live_source: null
strip.mcx_live_vs_settle_pct: null
strip.mcx_settle: number
strip.mcx_settle_quality: string
strip.mcx_settle_session: string
strip.mcx_settle_session_label: string
strip.mcx_shown: string
strip.real_10y: number
strip.real_10y_date: string
strip.usdinr: number
strip.usdinr_as_of: string
window: string
```

#### `/api/gold/health?window=W` (health)
```
as_of: string
brf_line: string
fair: object
fair.actual_open: null
fair.actual_open_source: null
fair.badge: string
fair.basis_pct: number
fair.comex: object
fair.comex.as_of: string
fair.comex.price: number
fair.comex.symbol: string
fair.comex_symbol: string
fair.contract: string
fair.desk_verdict_state: string
fair.duty_effective: string
fair.duty_note: string
fair.duty_paid_landed: number
fair.duty_pct: number
fair.expiry: string
fair.expiry_source: string
fair.fair_value: number
fair.freshness: object
fair.freshness.age_s: number
fair.freshness.as_of: string
fair.freshness.source: string
fair.freshness.state: string
fair.gap_vs_settlement: number
fair.implied_premium_pct: number
fair.landed: number
fair.mcx_holiday: null
fair.mcx_live: null
fair.mcx_live_as_of: null
fair.mcx_live_source: null
fair.premium_pct: null
fair.premium_rupees: null
fair.settlement: number
fair.settlement_quality: string
fair.settlement_session: string
fair.settlement_session_label: string
fair.snapshot_error: null
fair.snapshot_fair: null
fair.usdinr: object
fair.usdinr.as_of: string
fair.usdinr.price: number
fair.usdinr.symbol: string
freshness: object
freshness.age_days: number
freshness.oldest: number
freshness.stale: array
freshness.stale[]: string
freshness.state: string
freshness.unavailable: array
freshness.unavailable[]: string
gauges: array
gauges[]: object
gauges[].age_days: null|number
gauges[].annualised_pct: number
gauges[].badge: string
gauges[].basis_label: string
gauges[].change: null|number
gauges[].change_bp: number
gauges[].change_pct: number
gauges[].change_unit: null|string
gauges[].change_window: string
gauges[].chg_5d: number
gauges[].chg_long: number
gauges[].chg_short: number
gauges[].clock: string
gauges[].cot_index_52: number
gauges[].days_to_fnd: number
gauges[].direction_for_gold: null|string
gauges[].drawdown_52w_pct: number
gauges[].driver_label: string
gauges[].duty_effective: string
gauges[].duty_paid_landed_now: number
gauges[].duty_pct: number
gauges[].evidence: string
gauges[].fnd_date: string
gauges[].fnd_source: string
gauges[].front: string
gauges[].ibja_premium_date: string
gauges[].ibja_premium_note: string
gauges[].ibja_premium_pct: number
gauges[].key: string
gauges[].label: string
gauges[].last_bar_note: null
gauges[].last_bar_partial: bool
gauges[].live_basis_pct: null
gauges[].ltd_date: null
gauges[].mcx_live: null
gauges[].net_pct_oi: number
gauges[].next: string
gauges[].percentile_1y: null|number
gauges[].percentile_3y: null|number
gauges[].read_from: string
gauges[].release_at: null|string
gauges[].report_date: null|string
gauges[].rule: string
gauges[].series_id: string
gauges[].settle_basis_date: string
gauges[].settle_basis_label: string
gauges[].settle_basis_pct: number
gauges[].settle_basis_source: string
gauges[].settlement_session_label: string
gauges[].source: string
gauges[].state: string
gauges[].unit: string
gauges[].value: null|number
gauges[].vs_200d_pct: number
gauges[].vs_20d_pct: number
gauges[].week_price_chg_pct: number
gauges[].window_from: string
gauges[].window_from_value: number
gauges[].window_label: string
gauges[].window_sessions: number
gauges[].words: string
line: string
lines: object
lines.brf: string
lines.wei: string
store_errors: null
verdict: object
verdict.badge: string
verdict.clauses: array
verdict.clauses[]: object
verdict.clauses[].note: null
verdict.clauses[].rule_id: string
verdict.clauses[].series_id: string
verdict.clauses[].text: string
verdict.clauses[].threshold: null|object
verdict.clauses[].threshold.flat_pct: number
verdict.clauses[].threshold.min_move_pct: number
verdict.clauses[].threshold.notable_t: number
verdict.clauses[].threshold.real_yield_bp: number
verdict.clauses[].threshold.strong_pct: number
verdict.clauses[].threshold.usd_share: number
verdict.clauses[].threshold.weak_pct: number
verdict.clauses[].value: number
verdict.ends_with: string
verdict.headline: string
verdict.line: string
window: string
```

#### `/api/gold/fair` (fair)
```
accuracy: object
accuracy.badge: string
accuracy.bias: null
accuracy.days: number
accuracy.mean_abs_error: null
accuracy.median_abs_error: null
accuracy.naive_mean_abs_error: null
accuracy.p90: null
accuracy.threshold: number
accuracy.within_threshold_pct: null
as_of: string
badge: string
baseline: object
baseline.close_time: string
baseline.master_published: string
baseline.session: string
baseline.session_label: string
baseline.settlement_from_band: number
baseline.source: string
baseline.stale: bool
baseline.value: number
context: array
context[]: object
context[].at_close: number
context[].change: number
context[].key: string
context[].label: string
context[].signal: string
context[].symbol: string
context[].trigger: number
context[].trigger_state: string
context[].unit: string
context[].value: number
contract: object
contract.band_high: number
contract.band_low: number
contract.band_pct: number
contract.comex: string
contract.expiry: string
contract.name: string
contract.open_interest_lots: number
duty: object
duty.effective: string
duty.note: string
duty.notification: string
duty.pct: number
event_risk: object
event_risk.advice: null
event_risk.badge: string
event_risk.flagged_headlines: number
freshness: object
freshness.age_s: number
freshness.as_of: string
freshness.source: string
freshness.state: string
headlines: array
holiday: null
manual_checks: array
manual_checks[]: object
manual_checks[].name: string
manual_checks[].url: string
manual_checks[].what: string
mcx_price: object
mcx_price.broker: null
mcx_price.source: null
mcx_price.value: null
model: object
model.basis_pct: number
model.comex: object
model.comex.as_of: string
model.comex.now: number
model.comex.ref: number
model.comex.ref_how: string
model.comex.symbol: string
model.comex_part: number
model.duty_paid_landed: number
model.duty_pct: number
model.fair_open: number
model.gap: number
model.gap_pct: number
model.implied_premium_pct: number
model.inr: object
model.inr.as_of: string
model.inr.now: number
model.inr.ref: number
model.inr.ref_how: string
model.inr.symbol: string
model.inr_part: number
model.landed: number
model.lot_pnl_per_rupee: number
model.rs_per_comex_dollar: number
model.rs_per_inr_rupee: number
model.threshold_in_comex_dollars: number
notes: array
notes[]: string
threshold: number
today_log: null
verdict: object
verdict.badge: string
verdict.detail: string
verdict.state: string
verdict.title: string
```

#### `/api/gold/series?ids=FRED_DFII10,DXY_CLOSE,CME_BULLETIN_SETTLE&freq=W` (series)
```
as_of: string
asof_applied: null
freq: string
series: array
series[]: object
series[].catalog: object
series[].catalog.badge: string
series[].catalog.evidence: null
series[].catalog.lag_note: null
series[].catalog.publisher: string
series[].catalog.terms: null
series[].catalog.verdict: string
series[].freq_native: string
series[].freshness: object
series[].freshness.age_s: null|number
series[].freshness.as_of: null|string
series[].freshness.source: string
series[].freshness.state: string
series[].n: number
series[].name: string
series[].note: null|string
series[].points: array
series[].points[]: object
series[].points[].n: number
series[].points[].release_at: string
series[].points[].report_date: string
series[].points[].value: number
series[].published: bool
series[].quality: string
series[].resample: string
series[].series_id: string
series[].unit: string
store_errors: null
```

#### `/api/gold/bars?symbol=GC=F&interval=1d` (bars)
```
bars: array
bars[]: object
bars[].c: number
bars[].h: number
bars[].l: number
bars[].o: number
bars[].ts: string
bars[].v: number
daily_closes: array
daily_closes[]: object
daily_closes[].close: number
daily_closes[].date: string
daily_closes[].label: string
daily_closes[].partial: bool
day: string
freshness: object
freshness.age_s: number
freshness.as_of: string
freshness.source: string
freshness.state: string
hi: number
instrument: string
interval: string
last: null
lo: number
matched_last: object
matched_last.is_settlement: bool
matched_last.label: string
matched_last.quality: string
matched_last.source: string
matched_last.value: number
note: string
prev_close: object
prev_close.close: number
prev_close.date: string
prev_close.label: string
prev_close.partial: bool
prev_day: array
prev_day[]: object
prev_day[].c: number
prev_day[].ts: string
sessions: array
sessions[]: object
sessions[].bar: bool
sessions[].closed: bool
sessions[].end_ist: string
sessions[].hatched: bool
sessions[].name: string
sessions[].start_ist: string
settle_line: object
settle_line.is_settlement: bool
settle_line.label: string
settle_line.quality: string
settle_line.source: string
settle_line.value: number
since: string
store_errors: null
symbol: string
```

#### `/api/gold/cot?weeks=4` (cot)
```
as_of: string
badge: string
crowd: object
crowd.badge: string
crowd.cot_index_156: number
crowd.cot_index_26: number
crowd.cot_index_52: number
crowd.label: string
crowd.n_reports: number
crowd.percentile_all: number
crowd.percentile_label: string
crowd.percentile_window: number
crowd.window_label: string
crowd.window_reports: number
crowd.z156: number
crowd.z52: number
decomposition: array
decomposition[]: object
decomposition[].d_comm_net: number
decomposition[].d_gld_t: null
decomposition[].d_mm_long: number
decomposition[].d_mm_net: number
decomposition[].d_mm_short: number
decomposition[].d_nr_net: number
decomposition[].d_oi: number
decomposition[].d_or_net: number
decomposition[].d_pm_net: number
decomposition[].d_sd_net: number
decomposition[].from_date: string
decomposition[].price_from: number
decomposition[].price_to: number
decomposition[].span: string
decomposition[].to_date: string
drawer: object
drawer.api_query: string
drawer.average_position: object
drawer.average_position.mm: number
drawer.average_position.or: number
drawer.average_position.pm: number
drawer.average_position.sd: number
drawer.concentration: object
drawer.concentration.gross4_long: number
drawer.concentration.gross4_short: number
drawer.concentration.gross8_long: number
drawer.concentration.gross8_short: number
drawer.concentration.net4_long: number
drawer.concentration.net4_short: number
drawer.concentration.net8_long: number
drawer.concentration.net8_short: number
drawer.identity_check: bool
drawer.identity_gap: number
drawer.identity_note: string
drawer.micro_gold: null
drawer.raw_block_url: string
drawer.traders: object
drawer.traders.mm_long: number
drawer.traders.mm_short: number
drawer.traders.mm_spread: number
drawer.traders.or_long: number
drawer.traders.or_short: number
drawer.traders.pm_long: number
drawer.traders.pm_short: number
drawer.traders.sd_long: number
drawer.traders.sd_short: number
drawer.traders.total: number
driver_label: string
driver_rule: string
evidence: string
footer: string
freshness: object
freshness.age_s: number
freshness.as_of: string
freshness.source: string
freshness.state: string
fut_or_combined: string
groups: array
groups[]: object
groups[].chg_long: number
groups[].chg_net: number
groups[].chg_short: number
groups[].key: string
groups[].label: string
groups[].long: number
groups[].net: number
groups[].net_moz: number
groups[].net_pct_oi: number
groups[].net_t: number
groups[].net_usd_bn: number
groups[].pct_oi_long: number
groups[].pct_oi_short: number
groups[].short: number
groups[].spread: null|number
groups[].traders_long: null|number
groups[].traders_short: null|number
groups[].who_did: array
groups[].who_did[]: string
history: array
history[]: object
history[].cot_index_52: number
history[].mm_net: number
history[].nr_net: number
history[].oi: number
history[].or_net: number
history[].pm_net: number
history[].price: number
history[].report_date: string
history[].sd_net: number
latest: object
latest.age_days: number
latest.catch_up_note: null
latest.next_release_at: string
latest.next_release_ist: string
latest.next_release_source: string
latest.next_report_date: string
latest.release_at: string
latest.release_ist: string
latest.report_date: string
latest.stale: bool
open_interest: object
open_interest.chg: number
open_interest.pct_rank: number
open_interest.pct_rank_label: string
open_interest.total: number
options_overlay: object
options_overlay.combined_oi: number
options_overlay.line: string
options_overlay.mm_net_combined: number
options_overlay.mm_net_options_only: number
price_prev_tue: number
price_tue: number
quadrant_label: string
report: string
store_errors: null
week_price_chg_pct: number
```

#### `/api/gold/positioning/daily?exchange=COMEX` (positioning_daily_comex)
```
as_of: string
badge: string
evidence: string
exchange: string
freshness: object
freshness.age_s: number
freshness.as_of: string
freshness.source: string
freshness.state: string
put_call_oi_ratio: number
quadrant_tape: array
quadrant_tape[]: object
quadrant_tape[].churn: number
quadrant_tape[].doi: null|number
quadrant_tape[].dprice_pct: number
quadrant_tape[].label: null|string
quadrant_tape[].label_note: null|string
quadrant_tape[].mechanical: bool
quadrant_tape[].trade_date: string
quadrant_tape[].volume: number
quadrant_tape[].volume_avg_sessions: number
quadrant_tape[].volume_vs_20d: null|number
read: string
roll: object
roll.days_to_tender_or_fnd: number
roll.days_unit: string
roll.fnd_date: string
roll.fnd_source: string
roll.front: string
roll.front_oi: number
roll.ltd_date: null
roll.next: string
roll.next_oi: number
roll.note: string
roll.ratio: number
rows: array
rows[]: object
rows[].expiry: null
rows[].globex_volume: null
rows[].oi_change: null
rows[].open_interest: number
rows[].product_desc: null
rows[].quality: string
rows[].settle_or_close: null|number
rows[].symbol_or_product: string
rows[].trade_date: string
rows[].volume: null|number
since: string
store_errors: null
```

#### `/api/gold/positioning/daily?exchange=MCX&family=GOLD` (positioning_daily_mcx)
```
as_of: string
badge: string
exchange: string
family: string
freshness: object
freshness.age_s: null
freshness.as_of: null
freshness.source: string
freshness.state: string
quadrant_tape: array
read: string
roll: object
roll.days_to_tender_or_fnd: null
roll.days_unit: string
roll.expiry: null
roll.front: null
roll.front_oi: null
roll.next: null
roll.next_oi: null
roll.note: string
roll.ratio: null
roll.tender_start: null
rows: array
since: null
store_errors: null
```

#### `/api/gold/curve?exchange=COMEX` (curve_comex)
```
badge: string
basis: null
date: string
exchange: string
family: null
freshness: object
freshness.age_s: number
freshness.as_of: string
freshness.source: string
freshness.state: string
ghost_1w: array
ghost_1w[]: object
ghost_1w[].annualised_carry_pct: null|number
ghost_1w[].band_hi: null
ghost_1w[].band_lo: null
ghost_1w[].days_to_expiry: number
ghost_1w[].expiry: string
ghost_1w[].oi_change: null
ghost_1w[].open_interest: number
ghost_1w[].quality: string
ghost_1w[].session_date: null
ghost_1w[].settle_or_last: number
ghost_1w[].source: string
ghost_1w[].spread_vs_front: number
ghost_1w[].symbol: string
ghost_1w[].trade_date: string
ghost_1w[].volume: null
ghost_date: string
history: array
points: array
points[]: object
points[].annualised_carry_pct: null|number
points[].band_hi: null
points[].band_lo: null
points[].days_to_expiry: number
points[].days_to_fnd: null
points[].days_to_ltd: null
points[].expiry: string
points[].first_notice: null
points[].flags: array
points[].flags[]: string
points[].last_trade: null
points[].oi_change: null
points[].open_interest: number
points[].quality: string
points[].session_date: null
points[].settle_or_last: number
points[].source: string
points[].spread_vs_front: number
points[].symbol: string
points[].trade_date: string
points[].volume: null
price_label: string
since: string
store_errors: null
```

#### `/api/gold/curve?exchange=MCX&family=GOLD` (curve_mcx)
```
badge: string
basis: object
basis.badge: string
basis.basis_carry_adj_pct: null
basis.basis_clock: string
basis.basis_date: string
basis.basis_label: string
basis.basis_pct: number
basis.basis_source: string
basis.carry_pct: null
basis.duty_effective: string
basis.duty_note: string
basis.duty_notification: string
basis.duty_paid_landed_inr: number
basis.duty_pct: number
basis.landed_inr: number
basis.live_basis_label: null
basis.live_basis_pct: null
basis.mcx_front_inr: number
basis.mcx_front_quality: string
basis.mcx_front_session: string
basis.mcx_front_session_label: string
basis.mcx_live: null
basis.ts: string
basis.ts_note: string
basis.usdinr: number
basis.usdinr_source: string
date: string
exchange: string
family: string
freshness: object
freshness.age_s: null
freshness.as_of: null
freshness.source: string
freshness.state: string
ghost_1w: array
ghost_date: null
history: array
history[]: object
history[].basis_pct: number
history[].premium_pct: number
history[].trade_date: string
points: array
price_label: string
since: null
store_errors: null
```

#### `/api/gold/contracts?exchange=COMEX` (contracts)
```
as_of: string
badge: string
comex_front: object
comex_front.expiry: string
comex_front.price: number
comex_front.source: string
comex_front.symbol: string
comex_matched_by_family: object
comex_matched_by_family.GOLD: string
comex_matched_by_family.GOLDGUINEA: string
comex_matched_by_family.GOLDM: string
comex_matched_by_family.GOLDPETAL: string
comex_matched_by_family.GOLDTEN: string
comex_spec: null
diff_keys: array
diff_keys[]: string
exchange: string
families: array
families[]: object
families[].badge: string
families[].breeze_code: string
families[].code: string
families[].cycle: string
families[].delivery_unit: string
families[].expiries: array
families[].expiries[]: object
families[].expiries[].band_hi: number
families[].expiries[].band_lo: number
families[].expiries[].carry_convention: string
families[].expiries[].carry_pct: null|number
families[].expiries[].comex_matched: string
families[].expiries[].comex_matched_calendar: string
families[].expiries[].comex_matched_note: null|string
families[].expiries[].days_to_expiry: number
families[].expiries[].days_to_tender: number
families[].expiries[].days_unit: string
families[].expiries[].expiry: string
families[].expiries[].margin_date: null|string
families[].expiries[].margin_inr: number
families[].expiries[].margin_pct: number
families[].expiries[].margin_source: string
families[].expiries[].oi: number
families[].expiries[].oi_change: null
families[].expiries[].settle: number
families[].expiries[].settle_quality: string
families[].expiries[].source: string
families[].expiries[].tender_start: string
families[].expiry_rule: string
families[].hedge_ratio_oz: number
families[].lot: string
families[].lot_grams: number
families[].multiplier: number
families[].name: string
families[].notes: string
families[].notional_inr: number
families[].one_pct_move_inr: number
families[].options: object
families[].options.available: bool
families[].options.expiries: array
families[].options.note: string
families[].options.strike_step: null
families[].purity: string
families[].quote_unit: string
families[].round_trip: object
families[].round_trip.assumptions: string
families[].round_trip.breakeven_ticks: number
families[].round_trip.legs: object
families[].round_trip.legs.buy: number
families[].round_trip.legs.sell: number
families[].round_trip.pct: number
families[].round_trip.price: number
families[].round_trip.total: number
families[].tender_cutoff_note: string
families[].tick_rupees: number
families[].tick_value: number
freshness: object
freshness.age_s: number
freshness.as_of: string
freshness.source: string
freshness.state: string
margin_note: string
master: object
master.available: bool
master.published: string
master.session: string
master.session_label: string
other_exchanges: array
other_exchanges[]: object
other_exchanges[].available: bool
other_exchanges[].exchange: string
other_exchanges[].reason: string
store_errors: null
```

#### `/api/gold/premiums` (premiums)
```
as_of: string
india: object
india.badge: object
india.badge.ladder: string
india.badge.premium: string
india.basis_date: string
india.basis_label: string
india.basis_pct: number
india.basis_source: string
india.carry_adj_pct: null
india.clock_note: string
india.duty: object
india.duty.effective: string
india.duty.history: array
india.duty.history[]: object
india.duty.history[].effective: string
india.duty.history[].pct: number
india.duty.note: string
india.duty.notification: string
india.duty.pct: number
india.fineness_adjustment: string
india.freshness: object
india.freshness.age_s: number
india.freshness.as_of: string
india.freshness.source: string
india.freshness.state: string
india.history: array
india.history[]: object
india.history[].basis_pct: number
india.history[].premium_pct: number
india.history[].report_date: string
india.ibja_date: string
india.ladder: array
india.ladder[]: object
india.ladder[].clock: string
india.ladder[].label: string
india.ladder[].source: string
india.ladder[].step: string
india.ladder[].ts: string
india.ladder[].ts_label: string
india.ladder[].unit: string
india.ladder[].value: number
india.live_basis: null
india.premium_clock: string
india.premium_date: string
india.premium_note: null
india.premium_pct: number
reference: object
reference.attribution: string
reference.reuters_url: string
reference.wgc_china: null
reference.wgc_china_week: null
reference.wgc_india: null
reference.wgc_india_week: null
shanghai: object
shanghai.badge: string
shanghai.clock_note: string
shanghai.comex_at_1415_bj: null
shanghai.freshness: object
shanghai.freshness.age_s: null
shanghai.freshness.as_of: null
shanghai.freshness.source: string
shanghai.freshness.state: string
shanghai.history: array
shanghai.legs_note: string
shanghai.london_pm_usd: null
shanghai.note: null
shanghai.pair_date: null
shanghai.pairing: null
shanghai.premium_pct: null
shanghai.premium_usd: null
shanghai.sge_latest_cny_g: null
shanghai.sge_latest_date: null
shanghai.sge_pm_cny_g: null
shanghai.sge_pm_date: null
shanghai.sge_usd_oz: null
shanghai.ts_ref: null
shanghai.ts_sge: null
shanghai.usdcny: null
shanghai.usdcny_date: null
shanghai.usdcny_source: null
store_errors: null
```

#### `/api/gold/flows` (flows)
```
as_of: string
attribution: string
badge: string
balance_sheet: array
etf: array
etf[]: object
etf[].chg_1d: number
etf[].chg_1m: number
etf[].chg_5d: number
etf[].chg_ytd: null
etf[].cumulative_30d: array
etf[].cumulative_30d[]: object
etf[].cumulative_30d[].report_date: string
etf[].cumulative_30d[].tonnes: number
etf[].fund: string
etf[].report_date: string
etf[].source: string
etf[].tonnes: number
evidence: string
freshness: object
freshness.etf: object
freshness.etf.age_s: number
freshness.etf.as_of: string
freshness.etf.source: string
freshness.etf.state: string
freshness.official: object
freshness.official.age_s: null
freshness.official.as_of: null
freshness.official.source: string
freshness.official.state: string
freshness.otc: object
freshness.otc.age_s: null
freshness.otc.as_of: null
freshness.otc.source: string
freshness.otc.state: string
freshness.rbi: object
freshness.rbi.age_s: null
freshness.rbi.as_of: null
freshness.rbi.source: string
freshness.rbi.state: string
freshness.wgc_weekly: object
freshness.wgc_weekly.age_s: number
freshness.wgc_weekly.as_of: string
freshness.wgc_weekly.source: string
freshness.wgc_weekly.state: string
official: array
otc: object
otc.efp: object
otc.efp.avg_20d: null
otc.efp.avg_note: null
otc.efp.avg_sessions: number
otc.efp.date: null
otc.efp.pct_of_volume: null
otc.efp.since: null
otc.efp.today_rt: null
otc.lbma_turnover_usd_bn: null
otc.read: string
otc.turnover_tonnes_est: null
otc.vault_chg_t: null
otc.vault_month: null
otc.vault_t: null
otc.week_ending: null
physical_monthly: object
physical_monthly.amfi: object
physical_monthly.amfi.aum_cr: null
physical_monthly.amfi.evidence: string
physical_monthly.amfi.month: null
physical_monthly.amfi.net_cr: null
physical_monthly.amfi.tonnes_est: null
physical_monthly.india_imports_month: null
physical_monthly.india_imports_usd_bn: null
physical_monthly.india_imports_yoy_pct: null
physical_monthly.sge_withdrawals_kg: null
physical_monthly.sge_withdrawals_month: null
physical_monthly.swiss_exports_in_kg: null
rbi: object
rbi.inr_cr: null
rbi.note: string
rbi.share_pct: null
rbi.tonnes: null
rbi.tonnes_est: null
rbi.tonnes_month: null
rbi.tonnes_source: null
rbi.usd_mn: null
rbi.week: null
store_errors: null
wgc_india_holdings_t: null
wgc_weekly: array
wgc_weekly[]: object
wgc_weekly[].flow_t: number
wgc_weekly[].holdings_t: null
wgc_weekly[].region: string
wgc_weekly[].week_ending: string
```

#### `/api/gold/macro` (macro)
```
as_of: string
badge: string
calendar: array
calendar[]: object
calendar[].actual: null
calendar[].country: string
calendar[].date: string
calendar[].days: number
calendar[].forecast: null
calendar[].impact: string
calendar[].impact_rank: number
calendar[].in_session: bool
calendar[].kind: string
calendar[].previous: null
calendar[].star: bool
calendar[].time_ist: string
calendar[].title: string
context: object
context.badge: string
context.gold_m2_pct: null
context.gpr_m: null
context.gpr_pct_d: null
context.gpr_pct_m: null
context.gsr: null
context.gsr_pct: null
context.hy_oas: null
context.hy_oas_date: null
currencies: array
currencies[]: object
currencies[].badge: string
currencies[].ccy: string
currencies[].d1: number
currencies[].d1m: number
currencies[].d1w: number
currencies[].price: null|number
currencies[].unit: null|string
currencies[].ytd: number
driver_health: object
driver_health.beta_units: object
driver_health.beta_units.beta_dxy: string
driver_health.beta_units.beta_real_yield_per_100bp: string
driver_health.beta_units.rolling_corr: string
driver_health.betas_by_regime: array
driver_health.betas_by_regime[]: object
driver_health.betas_by_regime[].beta_dxy: null|number
driver_health.betas_by_regime[].beta_real_yield_per_100bp: null|number
driver_health.betas_by_regime[].regime: string
driver_health.dxy_series: string
driver_health.lesson: string
driver_health.rolling_corr: array
driver_health.rolling_corr[]: object
driver_health.rolling_corr[].dxy: null|number
driver_health.rolling_corr[].real_yield: null|number
driver_health.rolling_corr[].year: string
drivers: array
drivers[]: object
drivers[].badge: string
drivers[].change_unit: string
drivers[].corr_60d: null|number
drivers[].d1: number
drivers[].d1_bp: null|number
drivers[].d1m: number
drivers[].d1w: number
drivers[].d_window: number
drivers[].evidence: string
drivers[].key: string
drivers[].label: string
drivers[].label_note: null
drivers[].pct_1y: number
drivers[].report_date: string
drivers[].rule: string
drivers[].series_id: string
drivers[].state: string
drivers[].tag: null|string
drivers[].unit: string
drivers[].value: null|number
fed: object
fed.after_mcx_close: bool
fed.as_of: null
fed.badge: string
fed.effr: null
fed.effr_date: null
fed.fedwatch_link: string
fed.meetings: array
fed.next_fomc: object
fed.next_fomc.after_mcx_close: bool
fed.next_fomc.at: string
fed.next_fomc.date_et: string
fed.next_fomc.days: number
fed.next_fomc.ist: string
fed.next_fomc.kind: string
fed.next_fomc.name: string
fed.next_fomc.source: string
fed.next_fomc.statement_ist: string
fed.next_fomc_ist: string
fed.source: string
fed.speakers: array
fed.speakers[]: object
fed.speakers[].date: string
fed.speakers[].impact: string
fed.speakers[].kind: string
fed.speakers[].time_ist: string
fed.speakers[].title: string
fed.target: null
fed.zq: array
freshness: object
freshness.drivers: object
freshness.drivers.age_s: number
freshness.drivers.as_of: string
freshness.drivers.source: string
freshness.drivers.state: string
freshness.fed: object
freshness.fed.age_s: null
freshness.fed.as_of: null
freshness.fed.source: string
freshness.fed.state: string
freshness.gold: object
freshness.gold.age_s: number
freshness.gold.as_of: string
freshness.gold.source: string
freshness.gold.state: string
kgx: object
kgx.badge: string
kgx.from_date: string
kgx.inr_effect_pct: number
kgx.inr_note: null
kgx.line: string
kgx.note: null
kgx.period: string
kgx.pure_gold_pct: number
kgx.total_pct: number
kgx.usd_effect_pct: number
kgx.weights: object
kgx.weights.{*}: number
move: object
move.atr14_inr: number
move.atr14_usd: number
move.badge: string
move.gvz: number
move.gvz_date: string
move.inr_10g: number
move.per_lot: object
move.per_lot.GOLD: number
move.per_lot.GOLDGUINEA: number
move.per_lot.GOLDM: number
move.per_lot.GOLDPETAL: number
move.per_lot.GOLDTEN: number
move.read: string
move.realised_20d: number
move.sigma_day_pct: number
move.usd_oz: number
store_errors: null
window: string
```

#### `/api/gold/calendar?days=30` (calendar)
```
as_of: string
badge: string
count: number
days: number
events: array
events[]: object
events[].after_close: bool
events[].country: string
events[].date: string
events[].days: number
events[].detail: string
events[].event_date: string
events[].first_seen_at: null
events[].impact: string
events[].impact_rank: number
events[].in_session: bool
events[].kind: string
events[].kind_stored: null|string
events[].name: string
events[].past: bool
events[].source: string
events[].star: bool
events[].time_ist: null|string
freshness: object
freshness.age_s: number
freshness.as_of: string
freshness.source: string
freshness.state: string
store_errors: null
```

#### `/api/gold/log` (log)
```
badge: string
read: string
rows: array
source: string
stats: object
stats.days: number
stats.p90: null
```

#### `/api/gold/catalog` (catalog)
```
as_of: string
badges: object
badges.arithmetic: number
badges.context: number
badges.heuristic: number
badges.signal: number
count: number
rows: array
rows[]: object
rows[].badge: string
rows[].evidence: null
rows[].freq: string
rows[].lag_note: null
rows[].max_age_days: number
rows[].name: string
rows[].publisher: string
rows[].resample: string
rows[].series_id: string
rows[].source_entry: string
rows[].terms: null
rows[].unit: string
rows[].url: string
rows[].verdict: string
store_errors: null
verdicts: object
verdicts.DO-NOT-PUBLISH: number
verdicts.LINK-ONLY: number
verdicts.PUBLISH-CONTEXT: number
verdicts.PUBLISH-CORE: number
```

#### `/api/gold/brief` (brief)
```
available: bool
data_quality: null
doc: null
note: string
report_date: null
store_errors: null
```

#### `/api/gold/learn/glossary?q=basis&limit=3` (learn_glossary)
```
count: number
dangling_see_also: array
query: string
source: string
terms: array
terms[]: object
terms[].aliases: array
terms[].aliases[]: string
terms[].long: string
terms[].see_also: array
terms[].see_also[]: string
terms[].short: string
terms[].term: string
version: string
```

#### `/api/gold/learn/tooltips` (learn_tooltips)
```
count: number
panels: array
panels[]: string
source: string
tooltips: object
tooltips.after_mcx_close: string
tooltips.annualised_carry_pct: string
tooltips.atr14_rupees: string
tooltips.badge: string
tooltips.balance_sheet: string
tooltips.band_high: string
tooltips.band_low: string
tooltips.baseline: string
tooltips.basis_carry_adj_pct: string
tooltips.basis_pct: string
tooltips.beta_regime: string
tooltips.bias: string
tooltips.breakeven_ticks: string
tooltips.brent: string
tooltips.c.comex: string
tooltips.c.links: string
tooltips.c.mcx: string
tooltips.c.roll: string
tooltips.c.selector: string
tooltips.c.spec: string
tooltips.cal_consensus: string
tooltips.cal_in_session: string
tooltips.carry_adj_pct: string
tooltips.carry_ann: string
tooltips.churn: string
tooltips.combined_oi: string
tooltips.comex_front: string
tooltips.comex_matched: string
tooltips.comex_part: string
tooltips.conc_gross_le_4: string
tooltips.corr_60d: string
tooltips.cot_as_of: string
tooltips.cot_index_156w: string
tooltips.cot_index_52w: string
tooltips.cot_mm_chg: string
tooltips.cot_mm_net: string
tooltips.cot_pctile_all: string
tooltips.cot_release: string
tooltips.cot_z52: string
tooltips.coverage_ratio: string
tooltips.crosscheck: string
tooltips.ctt: string
tooltips.cycle: string
tooltips.d.24h: string
tooltips.d.3day: string
tooltips.d.quadrant: string
tooltips.d.sge: string
tooltips.d.tape: string
tooltips.d1: string
tooltips.d1m: string
tooltips.d1w: string
tooltips.d_gld_t: string
tooltips.days_to_tender: string
tooltips.decomp_span: string
tooltips.delivery_unit: string
tooltips.delta_long: string
tooltips.delta_short: string
tooltips.dgs2: string
tooltips.diff_keys: string
tooltips.driver_label: string
tooltips.driver_tag: string
tooltips.duty_effective: string
tooltips.duty_paid_landed: string
tooltips.duty_pct: string
tooltips.duty_rate: string
tooltips.dxy: string
tooltips.effr: string
tooltips.efp_pct_volume: string
tooltips.efp_rt: string
tooltips.etf_chg_1d: string
tooltips.etf_chg_1m: string
tooltips.etf_flow_t: string
tooltips.etf_tonnes: string
tooltips.eurusd: string
tooltips.evening_close: string
tooltips.event_risk: string
tooltips.evidence: string
tooltips.exchange_txn: string
tooltips.expiry_source: string
tooltips.fair: string
tooltips.fair_open: string
tooltips.fed_mean_bp: string
tooltips.fed_p_cut: string
tooltips.fed_p_hike: string
tooltips.fed_target: string
tooltips.fnd: string
tooltips.freshness: string
tooltips.gap: string
tooltips.gap_pct: string
tooltips.gap_vs_settlement: string
tooltips.ghost_1w: string
tooltips.gold_in_ccy: string
tooltips.gold_m2_pct: string
tooltips.gpr_pct: string
tooltips.gsr: string
tooltips.gst: string
tooltips.gvz: string
tooltips.h.accuracy: string
tooltips.h.brief: string
tooltips.h.events: string
tooltips.h.gauges: string
tooltips.h.headlines: string
tooltips.h.moved: string
tooltips.h.open: string
tooltips.h.verdict: string
tooltips.hedge_ratio_oz: string
tooltips.hedge_usdinr_lots: string
tooltips.hy_oas: string
tooltips.ibja_999: string
tooltips.implied_premium_pct: string
tooltips.in_session: string
tooltips.india_premium_pct: string
tooltips.indicative_margin: string
tooltips.inputs_json: string
tooltips.inr_effect_pct: string
tooltips.inr_part: string
tooltips.kgx_inr_effect: string
tooltips.kgx_pure_gold: string
tooltips.kgx_total: string
tooltips.kgx_usd_effect: string
tooltips.landed: string
tooltips.landed_999_vs_995: string
tooltips.lbma_turnover_usd_bn: string
tooltips.ltd: string
tooltips.m.balance: string
tooltips.m.candles: string
tooltips.m.ladder: string
tooltips.m.liquidity: string
tooltips.m.official: string
tooltips.m.physical: string
tooltips.m.season: string
tooltips.margin_date: string
tooltips.margin_pct_indicative: string
tooltips.margin_source: string
tooltips.max_lots_at_risk_pct: string
tooltips.mc.calendar: string
tooltips.mc.ccy: string
tooltips.mc.context: string
tooltips.mc.drivers: string
tooltips.mc.fed: string
tooltips.mc.health: string
tooltips.mc.kgx: string
tooltips.mc.move: string
tooltips.mcx_basis_pct: string
tooltips.mcx_category_oi: string
tooltips.mcx_oi_by_expiry: string
tooltips.mean_abs_error: string
tooltips.mechanical: string
tooltips.micro_gold: string
tooltips.mm_net: string
tooltips.move_per_lot: string
tooltips.multiplier: string
tooltips.naive_error: string
tooltips.naive_mean_abs_error: string
tooltips.net_by_group: string
tooltips.net_moz: string
tooltips.net_pct_oi: string
tooltips.net_t: string
tooltips.net_usd_bn: string
tooltips.next_fomc_ist: string
tooltips.next_release_ist: string
tooltips.notional: string
tooltips.nr_net: string
tooltips.official_chg: string
tooltips.official_oz: string
tooltips.oi_all: string
tooltips.oi_by_product: string
tooltips.oi_change: string
tooltips.one_pct_move_inr: string
tooltips.open_interest_lots: string
tooltips.options_overlay: string
tooltips.or_net: string
tooltips.p.asia: string
tooltips.p.crowd: string
tooltips.p.daily.comex: string
tooltips.p.daily.mcx: string
tooltips.p.decomp: string
tooltips.p.drawer: string
tooltips.p.hero: string
tooltips.p.history: string
tooltips.p.mcx.category: string
tooltips.p.whois: string
tooltips.p90_abs_error: string
tooltips.p_cut: string
tooltips.p_hike: string
tooltips.pboc_streak: string
tooltips.pc_oi: string
tooltips.pct_1y: string
tooltips.per_lot: string
tooltips.percentile_all: string
tooltips.ph.comex.stocks: string
tooltips.ph.etf: string
tooltips.ph.india: string
tooltips.ph.ladder: string
tooltips.ph.links: string
tooltips.ph.official: string
tooltips.ph.otc: string
tooltips.ph.shanghai: string
tooltips.pm_net: string
tooltips.premium_pct: string
tooltips.premium_usd: string
tooltips.pure_gold_pct: string
tooltips.purity: string
tooltips.quadrant: string
tooltips.quadrant_label: string
tooltips.rbi_gold_share: string
tooltips.rbi_gold_usd: string
tooltips.realised_vol_20d: string
tooltips.registered_oz: string
tooltips.roll_ratio: string
tooltips.rolling_corr: string
tooltips.round_trip_total: string
tooltips.rs_per_comex_dollar: string
tooltips.rs_per_inr_rupee: string
tooltips.sd_net: string
tooltips.season_hit_rate: string
tooltips.season_mean: string
tooltips.sebi: string
tooltips.segment: string
tooltips.session_label: string
tooltips.settlement_from_band: string
tooltips.settlement_session: string
tooltips.sge_premium_pct: string
tooltips.sge_premium_usd: string
tooltips.sge_td_direction: string
tooltips.shfe_oi: string
tooltips.sigma_day_pct: string
tooltips.silver: string
tooltips.since: string
tooltips.spot_proxy_note: string
tooltips.spread_vs_front: string
tooltips.stale: string
tooltips.stale_baseline: string
tooltips.stamp: string
tooltips.t10yie: string
tooltips.tag: string
tooltips.tender_start: string
tooltips.threshold: string
tooltips.tick_value: string
tooltips.tips10: string
tooltips.traders_long: string
tooltips.traders_short: string
tooltips.ts_ref: string
tooltips.ts_sge: string
tooltips.usd_effect_pct: string
tooltips.usdinr: string
tooltips.vault_tonnes: string
tooltips.volume_vs_20d: string
tooltips.w.candles: string
tooltips.w.grid: string
tooltips.w.table: string
tooltips.w.whodid: string
tooltips.week_price_chg: string
tooltips.wgc_region_flow: string
tooltips.who_did: string
tooltips.within_threshold_pct: string
tooltips.z156: string
tooltips.z52: string
tooltips.zq_implied: string
version: string
```

<!-- generated: key inventory — end -->
