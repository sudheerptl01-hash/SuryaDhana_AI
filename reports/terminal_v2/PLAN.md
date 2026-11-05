# Terminal v2 — the build program (4 Nov 2026)

Author: SYNTH (product manager + chief architect). Inputs: the seven research reports under `reports/terminal_v2/`
(R-UI, R-ARCH, R-DATA, R-OPTIONS, R-IV, R-DRIVERS, R-WORLD) and `RATING.md` beside this file. Posture of this document:
a plan, not a change — nothing under `services/`, `ui/`, `scripts/`, `tests/`, `docs/` or `CLAUDE.md` was edited; the
GOLD fix round running concurrently owns those paths today and ships first.

Goal in one sentence: make SuryaDhana the day-to-day terminal of an NSE options trader and MCX gold trader — IV history
and daily IV analysis, "who drives NIFTY", a real options desk (margin, book, Greeks, alerts, expiry day), a data tier that
says when it is stale, and a platform that is an appliance — without loosening a single honesty rule.

Owner's asks (verbatim brief → where they land): "IV analysis day to day, how IV is changing, that history" → Wave 1.1;
"which companies are driving Nifty (earlier Infosys, now some other)" → Wave 1.2; "things very important for option
trading day to day" → Wave 1.3 + Wave 2.1–2.4; "UI side, scalability side, data update side" → Wave 1.4, 1.5, Wave 2.6–2.7,
Wave 3; "commodity trading" → Wave 2.5 and Wave 4.2; "make this the greatest terminal" → Waves 3–4 (R-WORLD's 25).

---

## 0. Binding principles (acceptance criteria, not advice)

Carried over from `reports/gold_program/PLAN.md` §0.1 and §f, generalised to the whole terminal. A wave is not done while
any of these fails its gate.

1. **Badges, not colours.** Every derived number carries `signal` / `context` / `arithmetic` / `heuristic`. `signal` only by
   a FINDINGS PASS row from a pre-registered study (PLAN before results, PIT data, |t| ≥ 2 full sample and both halves, after
   the project cost floor). **No `signal` exists today in F&O, gold or index attribution.** Context metrics render in the
   neutral token; green/red only on price changes and `arithmetic` fair-vs-live comparisons; no "bullish/bearish" words on
   context. Verdict sentences end "describes, does not predict". No composite score, no "N of 7".
2. **Store, then show.** No publisher on the request path. Every panel reads DuckDB, the parquet tick/chain store or an
   SWR cache. Histories begin the day their job starts and the page says so ("since 10 Nov 2026"), backfills say
   "backfilled from stored files".
3. **Point-in-time.** Every stored observation carries the period it describes (`date` / `report_date`), `release_at` where
   a publisher time exists, `first_seen_at` (our fetch time), and `model_version` / `source` where a model or a choice of
   publisher is involved; revisions are new rows, never overwrites. `r` is recorded on every IV row.
4. **Same number once per page.** The repetition test fails the build otherwise; the tape and the BRF/WEI one-liners are
   the only off-page echoes.
5. **Every number: value · source · as-of · lag chip.** `SourceChip` (LIVE Breeze / LIVE NSE / DELAYED age / STALE / OFFLINE
   / GAP) on every panel header of every page by the end of Wave 1; daily data shows its date, not a clock.
6. **Host allowlist discipline.** Every fetcher goes through a host-allowlisted, paced client (the gold `hosts.py` pattern
   lifted to `shared/`): `nsearchives.nseindia.com`, `www.nseindia.com` (cookie-primed, browser UA, 403/429 → 600 s breaker),
   `niftyindices.com`, the gold list (§c.6), `api.icicidirect.com` / `breezeapi.icicidirect.com` (via the SDK). Never
   `mcxindia.com`, `www.cmegroup.com`, `kitco.com`, `investing.com`, `stooq`, `goldprice.org`, the LBMA price pages. ≥ 1.2 s
   between requests to one host; 20 s timeouts; one static test per package scans the sources for hosts.
7. **No Yahoo callers.** No new `query1`/`query2.finance.yahoo.com` or `yfinance` caller anywhere; the Yahoo leg under
   `/db/market-monitor`'s lock is removed (Wave 1.5). Where this plan needs an index close it uses NSE's `ind_close_all`.
8. **Trading rules frozen.** `shared/momentum.py`, `shared/decision_desk.py`, the crash filter and the Desk's cost model are
   not changed by this program. Nothing built here feeds the Decision Desk, the S1 shadow, a directional alert or the
   paper ticket's price. The only touch on a Desk input is O-T9 (NSE index file as the NIFTY series), which is the owner's
   call under "DO NOT CHANGE without review".
9. **PAPER ONLY.** Any F&O or futures book built here is a paper book under the same `EXECUTION_LIVE_ALLOWED` gate; no order
   route for F&O exists; Breeze is read-only (quotes, chain, history, margin calculator) in this program.
10. **Freeze windows.** Jobs only fetch and compute; none is placed inside 07:45–09:20 or 18:30–21:15 IST except the light
    EOD-chain compute jobs that already live there (19:15 / 19:25 / 19:30 / 20:30 / 20:45 class: stored data + ≤ 4 small
    GETs, no restart). data-service / master-controller restarts only outside both windows; ui-api deploys avoid 07:55–08:10;
    no backfill inside a window or beside the 02:15 backup; UI ships as an atomic `build-ui` release with rollback.
11. **Breeze budget is owned by one module.** A `shared/breeze_budget.py` ledger (per-minute and per-day counters persisted
    to SQLite, per-caller quotas, hard stop at the owner's cap) that every Breeze caller — live-quote provider, tick engine,
    chain poller, margin calls, gold capture — passes through. The 100/min · 5,000/day documented limits are the ceiling,
    the owner's cap (O-T6) is the budget.
12. **Catalog-gated rendering, terminal-wide.** The gold `gold_series_catalog` pattern becomes `dataset_catalog` (one row per
    dataset with publisher, cadence, `expected_by` IST, `max_age`, `ingest_job`, `verdict`, `badge`, dictionary anchor); a
    panel reads only catalogued datasets; `scripts/tests` assert every ingest job and every page's data source has a row.
13. **No new npm dependency, no pip install into `jupyter_env`** (shared env; see memory `jupyter_env_shared`). New charts use
    the existing canvas kit.
14. **Evidence over opinion.** Every new panel cites its precedent (Bloomberg mnemonic / product) in its tooltip and its
    data source in the dictionary; every claim of "predicts" is a pre-registered study first.

---

## 1. Builders and ownership (disjoint paths; the gold B1–B7 pattern)

| Builder | Owns (paths) | Produces |
|---|---|---|
| **B1 data** | `services/data-service/fo_iv/` (new package: `schema.py`, `iv_eod.py`, `legacy_parser.py`, `intraday.py`, `catalog_seed.py`), `services/data-service/index_drivers/` (new), `services/data-service/data_health/` (new: `dataset_catalog.py`, `ingest_log.py`), `storage/duckdb_store.py` (new DDL + the `read()` API), `nse_positions.py` (new file ingests, `If-Modified-Since`), `main.py` (`/jobs/*`, `/db/*` for the above) | tables, ingest jobs, read endpoints |
| **B2 controller** | `scripts/master_controller.py` (new jobs, the 22:45 and 08:35 passes, extended catch-up, alert conditions), `scripts/stack_watchdog.sh` (dead-man second heartbeat only), `scripts/daily_session_refresh.py` (Keychain TOTP path, already supported) | the IST schedule, catch-up, Telegram lines |
| **B3 api** | `services/ui-api/routers/{derivatives,markets,alerts,options_strategy,positions,data_health,prefs}.py`, `routers/research.py` (CATALOG rows), `cache.py`, `main.py` (middleware), `shared/http_client.py` (new), `shared/breeze_budget.py` (new) | the `/api/*` contracts below |
| **B4 ui** | `ui/components/{OptionChain,DerivativesDesk,IndexMembers,StrategyBuilder,AlertsCenter,SystemTab,...}.tsx`, new `ui/components/vol/`, `ui/components/drivers/`, `ui/components/data/`, `ui/lib/activeSymbol.ts` (new), `ui/lib/goAliases.ts`, `ui/app/page.tsx` (strip), `ui/components/terminal/index.tsx` (kit additions only) | pages, panels, chips |
| **B5 docs + LEARN** | `docs/NSE_DATA_DICTIONARY.md` (verified rows), `docs/TERMINAL_DATA_DICTIONARY.md` (generated from `dataset_catalog`), `docs/RUNBOOK_RESTORE.md`, `docs/IMPROVEMENT_LOG.md`, `CLAUDE.md` (fix the `/metrics` claim, the new tables/jobs), `reports/terminal_v2/LEARN/` (IV, drivers, SPAN glossary entries) | docs, glossary, tooltips |
| **B6 gates** | `tests/`, `services/ui-api/tests/`, `scripts/tests/`, `ui/components/__tests__/*.check.ts`, `scripts/ui_audit.py` TABS, `.github/workflows/ci.yml` (ruff/mypy/pin-drift steps), `pyproject.toml` (new, starter) | the gates |
| **B7 arch** | `services/data-service/storage/duckdb_store.py` (`read()`/`write()` + RW lock; shared with B1 by contract: B7 lands first), `services/ui-api/main.py` + `shared/logging.py` + `shared/metrics.py` (new), `start-local.sh` (Redis bind/auth), `shared/config.py` (`SecretStr`), `scripts/db_backup.py` (off-machine copy hook) | concurrency, observability, hardening |
| **B8 studies** | `reports/terminal_v2/studies/*/PLAN.md` (pre-registered), `scripts/terminal_studies/*.py`, FINDINGS rows | the verdict rows that gate any badge |

Order inside a wave: B7 → B1 ∥ B3 (against written contracts; B4 starts on fixtures) → B2 → B4 ∥ B5 → B6 → B8.
The GOLD fix round and its deploy precede Wave 0's deploys; Wave 1 code starts in a branch immediately.

---

## Wave 0 — Stop the bleeding (days 1–3; owner actions + S fixes; no new features)

Nothing in later waves is safe until these are done. Each line names its evidence.

| # | Item | Owner / builder | Cost | Evidence |
|---|---|---|---|---|
| 0.1 | **Disaster recovery**: `git rm --cached ui/node_modules ui/.next`, `.gitignore`, commit the 642 dirty paths, add a **private remote** (GitHub/GitLab, O-T1), push; rclone/`cp` `data/backups` to an off-machine target nightly from `db_backup.py` (O-T1 decides where); configure a Time Machine destination; `scripts/db_backup.py` gains `--offsite` using the existing `.zst` path | owner + B7 | S | R-ARCH §3 row 2: no remote, last commit 14 Jun, `tmutil` no destination, 20 GB backups on one SSD |
| 0.2 | **Appliance**: `HEALTHCHECK_PING_URL` (healthchecks.io, Telegram integration) in `.env`; `sudo pmset -a autorestart 1`; decide the FileVault pre-login pause (auto-login for the service account or accept it, O-T2); a second heartbeat from the watchdog; UPS if the 31 Oct outage was power | owner | S | R-DATA §2: 106 h + 43 h silent outages, 55 % market-hours availability |
| 0.3 | **Breeze without a human**: store the ICICI TOTP secret in the Keychain (gold O-4; the BRKR panel + `daily_session_refresh.py` already support it), `chmod 600 .env`, one attended `--force` run after 15:40 | owner | S | R-DATA row 22: 4/4 scheduled logins "needs you"; every intraday feature below depends on a live session |
| 0.4 | **Fix the two rotten gold feeds**: override `FTP.makepasv` for the CME `229` EPSV reply (or `curl --ftp-pasv`); FRED → keyed REST (`api.stlouisfed.org`, `FRED_API_KEY` already read by `commodity.py`; 8 s timeout, per-series breaker, stop after 3 consecutive timeouts) — **after** the gold fix round merges; owner gets a free FRED key (O-T3) | B1 (gold package) | S | R-DATA §5/§6: CME 0 rows ever, 18 FRED series dead since 30 Oct, 378 s/run |
| 0.5 | **Reschedule to the measured clock**: 18:30 EOD becomes equity-only (no F&O attempt), 20:30 unchanged, **new 22:45 pass** (MTF T−1 file at 22:12, equity bhavcopy re-publication at 22:05 via `If-Modified-Since` → versioned row, FII/DII second attempt, results capture, `iv_eod` retry), **new 08:35 sweep** (anything missing from last night with `backfill_from`); `ingest_log` table (`dataset, date, url, fetched_at, last_modified, sha256, rows, status`) | B2 + B1 | S | R-DATA §4: F&O 20:10, MWPL 19:23, FOVOLT 17:01, bhavcopy 22:05, MTF 22:12 |
| 0.6 | **Three honesty fixes in the next UI release**: OMON "IV rank" → "IV percentile (share of the past year below today)"; PCR no longer coloured green ≥ 1; DERV VIX accent neutral; `?tab=` unknown → toast "GOLD is not in this release (built 25 Oct)" instead of a silent BRF; MOV's two INTRADAY panels get distinct titles | B4 | S | R-IV §3, R-OPTIONS §3.1/§3.4, R-UI S7/S9 |
| 0.7 | **Hardening**: `redis-server --bind 127.0.0.1 --requirepass <keychain>` in `start_redis` (mirror in the legacy compose), `SecretStr` for the 5 secret fields, a test that `repr(Settings())` leaks nothing (O-T10) | B7 | S | R-ARCH §3 security: Redis on `*:6379` without auth, `.env` 644 |
| 0.8 | **CI quality gates (starter)**: `pyproject.toml` with ruff `select = ["F","E9","B","ASYNC","DTZ"]`, mypy per package with `explicit_package_bases`, a pin-drift step (`pip freeze` vs `requirements.txt`), `pip-audit`; fix `F821` in `providers/direct_yahoo_provider.py:219` and the two `ASYNC230` (`routers/dashboard.py:309`, `routers/pipeline.py:1189`) | B6 | S | R-ARCH §5: 1,315 ruff findings, 247 mypy errors, CI pins ≠ prod |
| 0.9 | **Extend start-up catch-up** to `results_capture_daily` (window = days down + 3), `index_valuation_daily`, `desk_daily`, `alpha_shadow_daily`, `gold_asia_close`, `gold_morning`, `gold_india_*`, `gold_health_snapshot` (back-dated rows `backfilled=true`); write explicit gap rows for session-bound captures (pre-open, internals, FII/DII, gold open) so MOV/WRAP/BRF say "no intraday data for 2–4 Nov" | B2 + B1 | S | R-DATA §3 rows 10, 14, 26–28, 36–43 stale tonight despite the catch-up; §6.8 |

Deploy: 0.4/0.5/0.9 need a data-service + controller restart → outside 07:45–09:20 and 18:30–21:15 (e.g. 21:30 on a
weekday or a Sunday morning); 0.6 is a `./start-local.sh build-ui` release (not 07:55–08:10); 0.7 is a Redis restart with the
stack (same window). Gate: the five suites green, `ui_audit --tabs all` 43/43, `start-local.sh status` shows `dead-man-ping:
set`, `git remote -v` non-empty, the first off-machine backup verified by sha256.

---

## Wave 1 — History and the drivers (weeks 1–4)

Wave 1 contains, as required: IV history + daily IV analysis (R-IV), the NIFTY drivers leaderboard (R-DRIVERS), the
options-trader toolkit gaps R-OPTIONS ranked highest (the PIT IV archive = 1.1, the IV dashboard + VOL screener = 1.1,
real SPAN margin = 1.3; the paper F&O book and the intraday tape at 2-min are Wave 2), the data-health view (R-DATA) and
the architecture fixes that unblock scale (R-ARCH 2, 4, 5). Everything is free or already licensed.

### 1.1 IV history and daily IV analysis (the owner's ask #1)

**Scope.** A point-in-time IV store for every F&O underlying from the files on disk (2024-07-08 → today in UDiFF format,
2019-10-01 → 2024-07-05 in the legacy format), rebuilt nightly; constant-maturity and fixed-expiry series; rank and
percentile both; skew and term; IV vs three realised-vol estimators; a results IV-crush ledger; a 15-minute intraday
pilot from Breeze; the OMON history chart and a DERV › VOL sub-view; a VOL screener across the 224 underlyings.

**Method** (R-IV §4, adopted): Black-76 on the forward per expiry; forward from put-call parity at the strike nearest spot
where both sides traded, else the matching-month future, else spot·e^{rT} (`forward_source` stored; fall back to the
future when |F_pcp − F_future| > 0.5 %); price = `ClsPric` only when `TtlTradgVol > 0` (untraded strikes → no IV, flag);
OTM wings plus 3 % ITM; ATM IV interpolated at the forward; 25Δ/10Δ by inverting each strike's own delta; T = calendar
days / 365 at the 15:30 close (one convention, `model_version` recorded; the product's +0.5 day retired); expiry-day and
T ≤ 2 d rows kept in the surface, excluded from "near"; constant-maturity 30/60/90 by VIX-style variance interpolation;
`r` from a dated `rate_curve` table (seeded 6.5 %; FRED India 10-y already cached as context; RBI 91-day T-bill optional,
O-T5). Prototype agreement: corr 0.998 vs the product's ATM IV, 0.983 vs India VIX (`R-IV/iv_compare_NIFTY.csv`).

**Data sources (verified).**

| Source | Exact access | Cadence · publication (IST) · pacing | Use |
|---|---|---|---|
| NSE UDiFF F&O bhavcopy (cached) | `data/nse_archive/fo/<year>/BhavCopy_NSE_FO_0_0_0_YYYYMMDD_F_0000.csv.zip` (from `https://nsearchives.nseindia.com/content/fo/...`; 578 files, 655 MB) | daily, Last-Modified **20:10** (4 Nov); already fetched by the 20:30 job | the EOD IV source |
| NSE legacy F&O bhavcopy (cached) | `data/nse_archive/fo/2019..2024/foDDMONYYYYbhav.csv.zip` (from `https://nsearchives.nseindia.com/content/historical/DERIVATIVES/YYYY/MON/`; 1,182 files, 712 MB; 16 cols, no underlying price) | static; parsed by `nse_positions.parse_fo_bhavcopy` | backfill 2019-10 → 2024-07 (forward from parity, no spot needed) |
| NSE daily index file | `https://nsearchives.nseindia.com/content/indices/ind_close_all_DDMMYYYY.csv` | daily ≈ 17:50; one GET already made by the 19:15 job | NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY OHLC (Parkinson/Yang-Zhang), **India VIX OHLC** → `vix_daily`, every index close → `market_index_daily` (source `nse_daily_file`) |
| NSE India VIX history API | `https://www.nseindia.com/api/historicalOR/vixhistory?from=DD-MM-YYYY&to=DD-MM-YYYY` (cookie-primed, browser UA, ≤ 1 year per call) — R-IV got 200; the `api/historical/vixhistory` path R-WORLD tried returned 503 | one-off backfill only, paced 2 s | `vix_daily` 2014 → 2026 OHLC |
| NSE F&O daily volatility | `https://nsearchives.nseindia.com/archives/nsccl/volt/FOVOLT_DDMMYYYY.csv` | daily, by 17:05 (measured 17:01 / 11:28 on two days); fetch in the 20:30 pass | the exchange's EWMA vol per underlying (`fovolt_ann`), a third RV line |
| NSE contract delta factors | `https://nsearchives.nseindia.com/content/nsccl/Contract_Delta_DDMMYYYY.csv` (6.9 MB) | daily, between ≈ 13:00 and 19:20 (two measurements); fetch in the 20:30 pass | NSE's own delta per contract as a cross-check (log |Δ_ours − Δ_nse| > 0.05) and the model-free delta column |
| NSE combined delta-equivalent OI | `https://nsearchives.nseindia.com/archives/nsccl/mwpl/combineoi_deleq_DDMMYYYY.csv` and `.../mwpl/combineoi_DDMMYYYY.zip` | daily 19:18 / 19:23; 20:30 pass | MWPL crowding context columns (OMON/DERV) |
| NSE F&O ban list / lot sizes | `https://nsearchives.nseindia.com/archives/fo/sec_ban/fo_secban_DDMMYYYY.csv` (named for the next session, 19:24), `.../content/fo/fo_mktlots.csv` | daily / on change | ban chip (have), expiry calendar |
| ICICI Breeze option chain | `breeze.get_option_chain_quotes(stock_code, exchange_code="NFO", product_type="options", expiry_date="YYYY-MM-DDT06:00:00.000Z", right="call"\|"put")` → 60 strikes/side, 26 fields: ltp, ltt, best bid/offer price+qty, OHLC, prev close, OI, chnge_oi, volumes, spot — **no IV, no Greeks** | snapshot 0.35–0.44 s; 100/min, 5,000/day shared; own-account use, no redistribution | intraday IV from bid/ask mid (pilot: every 15 min, NIFTY + BANKNIFTY × 2 expiries × 2 sides = 200 calls/day + watchlist ≤ 500 = ≈ 700/day) |
| ICICI Breeze option history | `breeze.get_historical_data_v2(interval="1minute"\|"1day", stock_code, exchange_code="NFO", product_type="options", expiry_date, right, strike_price, from_date, to_date)` → OHLC, volume (units), open_interest; expired contracts served (2020–2026 verified); ≤ 1,000 bars/call | on demand, paced; same licence; daily close = last trade (198.00 vs NSE 193.20 on 3 Nov) so **never the EOD source** | expiry-day / event-day replays (Wave 2), option charts |
| NSE option-chain-v3 (live) | `https://www.nseindia.com/api/option-chain-contract-info?symbol=X` → `.../api/option-chain-v3?type=Indices\|Equity&symbol=X&expiry=DD-Mon-YYYY` (NSE's `impliedVolatility`, bid/ask, OI, ΔOI) | live only, 30 s cache exists (`nse_live.py` 272–318), 403/429 → 600 s breaker | NSE's IV stored beside ours in the same intraday tick (O-T7); fallback when Breeze is down |
| Access traps (do not use) | `api/quote-equity` 403 Akamai; `api/quote-derivative` 404; old `api/option-chain-indices` 404; market-wide `api/corporates-pit` empty; `api/equity-stockIndices` 404 | — | recorded in the dictionary |

**DuckDB point-in-time tables** (R-IV §6 DDL adopted verbatim; the `fo_*` names in R-OPTIONS/R-WORLD are aliases of these):

- `iv_surface_daily` (date, symbol, expiry, strike, opt_type, price, price_source, forward, forward_source, t_years, r, iv,
  delta, vega, oi, oi_chg, volume, lot, log_moneyness, model_version, source_file, first_seen_at; PK date·symbol·expiry·strike·
  opt_type). Scope: indices + the owner's F&O watchlist + any name in a paper book, ±15 % moneyness, first three expiries
  (≈ 0.3 GB for 7 years); all 224 if O-T4 says so (≈ 2–3 GB). Kept out of the ui-api `/tmp` snapshot copy.
- `iv_expiry_daily` (date, symbol, expiry, dte, forward, forward_source, atm_iv, iv_25d_put, iv_25d_call, skew_25d,
  iv_10d_put, iv_10d_call, n_iv_strikes, call_oi, put_oi, pcr, expected_move_pct, quality_flags, model_version,
  first_seen_at). All 224 underlyings, ≈ 400 rows/day.
- `iv_summary_daily` (date, symbol, spot, iv30_cm, iv60_cm, iv90_cm, near_atm_iv, near_expiry, near_dte, monthly_atm_iv,
  monthly_expiry, skew_25d_30, term_slope_30_90, iv_rank_252, iv_pctile_252, rv20_cc, rv20_parkinson, rv20_yz, fovolt_ann,
  iv_minus_rv20, expected_move_1d_pct, quality_flags, model_version, first_seen_at). ≈ 224 rows/day; the series every page charts.
- `vix_daily` (date, open, high, low, close, prev_close, source, first_seen_at) and `index_ohlc_daily` (symbol, date, OHLC,
  source, first_seen_at) from `ind_close_all`; `market_index_daily` gains every NSE index (source `nse_daily_file`; Yahoo rows kept
  as a second source, readers prefer `nse_daily_file`).
- `iv_event_log` (symbol, released_at, expiry, iv_pre_5d, iv_pre_1d, iv_post_1d, crush_pct, implied_move_pct, realised_move_pct,
  first_seen_at) from `nse_results` release timestamps.
- `iv_intraday` (ts, symbol, expiry, strike, opt_type, mid, iv, nse_iv, oi, source) in DuckDB for the derived per-snapshot
  rows; the raw Breeze/NSE chain snapshots as parquet parts under `data/ticks/chain/<date>/` (bounded like `tick_store`).
- `rate_curve` (date, tenor, rate, source) and `nse_fo_volt` (date, symbol, close, prev_close, log_return, ewma_daily_vol,
  ann_vol, fut_vol, first_seen_at), `nse_contract_delta` (date, symbol, expiry, strike, opt_type, delta_factor, first_seen_at),
  `nse_combined_oi` (date, symbol, mwpl, oi, fut_equiv_oi, limit_next_day, notional_oi, first_seen_at).

**Jobs (B2 → data-service `POST /jobs/iv-eod`, `POST /jobs/iv-intraday`; fetch + compute, never a restart).**
- `iv_eod`: the last step of the 20:30 `nse_positions_catchup` once the day's F&O file is stored (the file lands 20:10;
  R-IV's 19:35 is too early — resolved with R-DATA's measurement); parses the day's file (≈ 3 s for all 224 underlyings),
  writes the three daily tables, `vix_daily`/`index_ohlc_daily` from the already-fetched `ind_close_all`, FOVOLT,
  Contract_Delta (one GET each, paced), the event ledger for releases since yesterday; retry in the 22:45 pass; SLO 21:30;
  a Telegram `info` line on a miss. Expiry calendar read from the file, never assumed (Thursday → Tuesday → Monday changes).
- `iv_intraday` (pilot): trading days 09:20–15:30 every 15 min; skipped when the Breeze session is not live or the budget
  ledger says no; NIFTY + BANKNIFTY near + next expiry, both sides, plus the owner's F&O watchlist near expiry; NSE v3 in the
  same tick only if O-T7 approves; ≤ 800 calls/day, ≤ 30/min.
- `iv_weekly` (Sat 03:00): recompute the 252-session rank/percentile windows after late corrections; `dataset_catalog --check`.
- Backfill (one-off, owner-approved O-T4): UDiFF 578 files ≈ 30 min; legacy 1,182 files ≈ 1 h; both from cached files,
  resumable by date, outside the freeze windows and not beside the 02:15 backup (a Sunday 10:00 start). Optional 2001 → 2019
  download (≈ 4,500 files, 3.6 GB, 1 file / 2 s ≈ 2.5 h) only on O-T4b.

**API contract (B3, `routers/derivatives.py`; all reads from DuckDB, 60 s SWR).**
- `GET /api/derivatives/iv/{symbol}?days=750&series=iv30_cm|iv60_cm|iv90_cm|monthly|near` → `{symbol, as_of, since,
  model_version, r_source, rows:[{date, spot, iv30_cm, monthly_atm_iv, near_atm_iv, near_dte, skew_25d_30, term_slope_30_90,
  iv_rank_252, iv_pctile_252, rv20_cc, rv20_parkinson, rv20_yz, fovolt_ann, iv_minus_rv20}], vix:[{date, close}],
  events:[{date, kind}], badges:{iv:"arithmetic", rank:"arithmetic", spread:"context"}}`.
- `GET /api/derivatives/iv/{symbol}/surface?date=` → per-expiry rows (ATM, 25Δ/10Δ, skew, counts, flags) + the smile in
  log-moneyness for each expiry; `?compare=1m` adds the ghost surface.
- `GET /api/derivatives/iv/{symbol}/cone` → min/25/50/75/max of constant-maturity IV by tenor over 1/3/5 years + today's term.
- `GET /api/derivatives/iv/{symbol}/events?n=8` → the crush ledger rows.
- `GET /api/derivatives/vol-screen?sort=iv_pctile|iv_rank|iv_minus_rv|term_slope|skew&results_within=10` → 224 rows
  (`iv30_cm, rank, pctile, rv20_yz, spread, term_slope, skew, next_results, ban, mwpl_pct`), `as_of`, badges.
- `GET /api/derivatives/iv/{symbol}/intraday?date=` → the 15-minute path (ATM IV, skew, straddle, PCR; `source` chip).
- OMON's existing `/api/derivatives/option-history/{sym}` keeps serving until the UI switches, then is an alias for 1 release.

**Pages and panels (B4; each badged; each ends "describes, does not predict" where it is a sentence).**

| Where | Panel | Badge | Precedent |
|---|---|---|---|
| OMON › history (replaces the saw-tooth chart) | `iv30_cm` with the monthly line and **India VIX overlay**, results/budget/expiry markers; chips "IV percentile 60 · IV rank 21 (252 sessions, iv30_cm)" both defined on hover | `arithmetic` (IV, rank, pctile) | Bloomberg HIVG / "IVOL %ile / rank", Sensibull IV chart, tastytrade IVR |
| OMON › chain header | term strip (near / next / far ATM IV + 30/60/90), 25Δ skew with its 1-y percentile, straddle price vs its history, IV vs RV20 (cc / Parkinson / YZ / FOVOLT) | `arithmetic` / `context` | Bloomberg OVDV term tab, Opstra, Market Chameleon IV30 vs HV |
| OMON › chain | Greeks columns Δ Γ Θ ν per strike from the existing Black-76 lib; NSE delta column beside ours; MWPL % column for stocks | `arithmetic` | Bloomberg OMON, Sensibull chain |
| DERV › VOL (new sub-view, GO `VOL`) | skew history (25Δ / 10Δ, smile today vs 1 month ago), term structure + slope history, IV cone, IV vs realised with the "IV paid vs vol delivered" ledger over the last 12 monthly expiries, expected-move hit-rate over 60 sessions, the VOL screener table (sort/filter/export) | `context` / `arithmetic` | Bloomberg SKEW, VCA, GV cone, OSA expected move, GV/WVOL screen; Quantsapp IV percentile |
| EVTS | per-stock results IV-crush ledger (last 8 releases: IV before/after, crush %, implied vs realised), sortable by next results date | `context` | ORATS / Market Chameleon earnings |
| Stock window › Profile | IV strip: `iv30_cm`, rank, pctile, skew, IV − RV, next results | `context` | Bloomberg DES implied-vol strip |
| OMON › LIVE | today's IV path (15-min pilot) with `SourceChip` LIVE Breeze / LIVE NSE / OFFLINE | `context` | Quantsapp IV live |

Rules: the VIX appears on DERV's header strip and as the overlay on the IV chart only (one source: `vix_daily`); nothing
from these tables feeds a trade; OSTR may read `iv_summary_daily` for its default IV (what it does today from the chain).

### 1.2 NIFTY drivers (the owner's ask #2: "earlier Infosys drove NIFTY, now someone else")

**Scope.** A nightly point-in-time index-contribution table for NIFTY 50 and NIFTY BANK (NEXT 50 / IT on O-T12), PIT
weights rebuilt from stored filings and calibrated to NSE's daily top-10 file, points per name per day (additive, so every
horizon is a slice), a fit row with the residual, a driver state with hysteresis, sector and breadth; MEMB becomes "Index
members & drivers"; MOV keeps the live today panel; DESK gains "Book vs NIFTY" (real lots only).

**Method** (R-DRIVERS §3, adopted): `points_i,d = L_{d−1} × w_i,d × r_i,d` with `L` = NSE's closing index value (never Yahoo),
`r` from `shared.nse_panel.adjust` + `splits` (the `nse_bhavcopy.prev_close` trap), `w` = shares (newest XBRL filing with
`filed_at ≤ d`, split-scaled) × prev close × (1 − promoter % with `broadcast_ts ≤ d`), normalised; calibrated on each day
the top-10 file exists (`iwf_correction = official / rebuilt`, the other 40 pro rata); identity check per day stored as
`residual`; driver leader on 20- and 60-session windows with hysteresis (challenger ≥ 1.3× / 1.2× the incumbent for 5
consecutive sessions); breadth = equal-weight minus cap-weight over 20 sessions; NIFTY BANK with NSE's 33 % / 62 % capping
(approximate until O-T13 settles the 12-vs-14 member count and the official cap factors). Prototype fit: R² 0.996, MAE 9.4
pts/day over 229 sessions (`R-DRIVERS/evidence/drivers_results.json`).

**Data sources (verified).**

| Source | Exact access | Cadence · publication (IST) · pacing | Use |
|---|---|---|---|
| NIFTY 50 daily top-10 weights | `https://nsearchives.nseindia.com/content/indices/top10nifty50_DDMMYY.csv` (SYMBOL, SECURITY, WEIGHTAGE(%); 10 rows, Σ 53.13 % on 4 Nov) | daily after close (present by 22:18; exact minute unverified) — read in the 19:25 job with a 20:35 retry; 1 GET | calibration of the rebuilt weights; display-only with attribution (O-T11) |
| NIFTY 50 / NIFTY BANK constituents | `https://niftyindices.com/IndexConstituent/ind_nifty50list.csv` (50 rows), `.../ind_niftybanklist.csv` (14 rows) — Company Name, Industry, Symbol, Series, ISIN | on reconstitution (semi-annual, last trading day of Mar/Sep; ad hoc); archived daily (2 conditional GETs) to build the PIT history | membership + NSE industry |
| NSE daily index file | `ind_close_all_DDMMYYYY.csv` (as in 1.1) | 19:15 job | the index level `L` for every index incl. the 1 Feb 2026 special session |
| Stored inputs | `nse_bhavcopy` (2010→, unadjusted `prev_close`), `splits`, `nse_shareholding` (`promoter_pct`, `broadcast_ts`), `data/nse_archive/financials/<SYM>.json` (`shares`, `filed_at`) | daily / quarterly | PIT weights and returns |
| Monthly factsheet | `https://www.niftyindices.com/Factsheet/ind_nifty50.pdf` | monthly | LINK-ONLY; the bank factsheet's top-10 is the only free bank calibration (monthly) |
| Dead endpoint | `https://www.nseindia.com/api/equity-stockIndices?index=NIFTY%2050` → 404 (also via the warmed session) | — | DO NOT USE; no free per-constituent free-float cap exists |
| Paid, not needed | NSE Indices constituent weights / IWF; Bloomberg MEMB | — | the free top-10 file + calibrated rebuild explains 99.6 % of daily variance |

**DuckDB point-in-time tables** (R-DRIVERS §6.1 DDL adopted): `index_constituents_daily` (index_name, date, symbol,
industry, isin, source, first_seen_at), `index_weights_daily` (…, method ∈ official_top10 | rebuilt | rebuilt_calibrated,
weight_pct, ffmc_cr, shares, shares_filed_at, promoter_pct, promoter_public_at, iwf_correction, computed_at),
`index_contribution_daily` (index_name, date, symbol, ret_pct, weight_pct, points, prev_index_level, index_close_source,
flag, computed_at), `index_contribution_fit` (index_name, date, actual_points, explained_points, residual_points,
members_priced, members_total, computed_at), `index_driver_state` (index_name, date, window_sessions, leader, leader_points,
leader_share, tenure_sessions, changed_from, change_date, top5_share, hhi_contrib, weight_hhi, effective_n, ew_minus_cw_pp,
members_up, members_down, computed_at). Revisions are new rows by `computed_at`.

**Jobs.** 19:15 `index_valuation_daily` (exists) also upserts every index close from `ind_close_all` into
`market_index_daily` (source `nse_daily_file`). **19:25 `index_drivers_daily`** (new; stored data + 3 small GETs; same
class as the 19:15/19:30 jobs inside the window; retry 20:35 inside `nse_positions_catchup` if the top-10 file is not yet
there): weights (rebuilt + calibrated), contributions, fit, driver state for NIFTY 50 and NIFTY BANK. Backfill 2019-10 →
today from stored data (no fetch; current membership applied before the first archived list, the page says "members as of
today applied before <date>"; Mar/Sep 2024–2026 reconstitutions entered by hand from niftyindices press releases, Wave 2).

**API (B3, `routers/markets.py`; DuckDB only on the request path).**
- `GET /api/market/index-drivers?index=NIFTY%2050&horizon=1d|5d|1m|3m|ytd|since_change` → `{as_of, index, horizon:{from,to,
  sessions}, index_move_pts, explained_pts, fit:{mae_60s, r2_60s, residual_today, degraded}, weight_method, members:[{symbol,
  industry, weight_pct, ret_pct, points, share_abs}], sectors:[{industry, points, weight_pct}], concentration:{top5_abs_share,
  hhi_contrib, weight_hhi, effective_n, top5_weight_pct}, breadth:{ew_pct, cw_pct, ew_minus_cw_pp, up, down},
  driver:{window, leader, tenure, leader_share, changed_from, change_date}, history_since, badges:{members:"arithmetic",
  driver:"context"}}`.
- `GET /api/market/index-drivers/timeline?index=&window=20|60&days=250`; `GET /api/market/index-drivers/monthly?index=&months=12`.
- `GET /api/desk/attribution?horizon=` → the Desk's real lots × stored closes in pp of NAV beside NIFTY's leaderboard;
  `{risk_off:true, since}` when in cash (today).

**Pages and panels (B4; no new page).** MEMB → "Index members & drivers" (GO aliases `DRVR`, `IMAP`, `CONTRIB`):
horizon selector; the PTS column follows the horizon (the wrong YTD PTS column is replaced by the linked daily sum); a
DRIVER REGIME strip ("20-session leader BHARTIARTL for N sessions, 12.5 % of member points; 60-session leader HDFCBANK since
11 Sep; top-5 of the move 44 %; EW − CW −0.95 pp: narrow — describes, does not predict") in the neutral token; a SECTOR
CONTRIBUTION bar; a MONTHLY LEADERBOARD (12 months: leader, top-3 add/drag); a CONCENTRATION & BREADTH chart; the fit chip on
the table header ("explains −2,132 of −2,169 YTD points · MAE 9 pts/day · weights rebuilt, calibrated to NSE's top-10 on
04 Nov"); index switcher 50 / BANK (/ NEXT 50 / IT on O-T12). MOV keeps "WHO MOVED THE INDEX" (live, today; footer "history
on MEMB ›"). DESK gains "Book vs NIFTY" (real lots only; "in the liquid fund since 30 Oct" today). BRF keeps its one line.
Badges: members/sectors/concentration `arithmetic` (identity with residual shown); regime, breadth, monthly leader
`context`; no colour on the leader; nothing enters `momentum.py`, `decision_desk.py`, directional alerts or the ticket.

### 1.3 Options-trader toolkit, wave-1 slice (R-OPTIONS #2, #3, #11, #12 + R-UI #4)

| Item | Scope | Source | Cost | Badge |
|---|---|---|---|---|
| **Real SPAN margin on OSTR** | `POST /api/options/margin` (B3): Breeze `margin_calculator(legs, "NFO")` when the session is live (0.3 s; through the budget ledger); an offline parser of the NSE SPAN risk-parameter file (`https://nsearchives.nseindia.com/archives/nsccl/span/nsccl.YYYYMMDD.s.zip`, EOD ≈ 17:02, fetched in the 20:30 pass into `data/nse_archive/span/`) as the fallback; the 12 %-of-notional heuristic stays as last resort **with its measured 4.8× error printed**; the ticket shows `span_margin_required`, `non_span_margin_required`, source chip BREEZE / NSE SPAN FILE / HEURISTIC | Breeze (verified: condor ₹81,497.07; short 23700 PE alone ₹1,72,460.67), NSE SPAN file (verified 206 on a range GET) | S (Breeze) + M (parser) | `arithmetic` |
| **Chain-first OMON** | chain above the fold (history collapses to a strip), Greeks columns, inline OI-change bars, straddle/strangle row, IV percentile + rank chips, expiry ladder of ATM IV, keyboard j/k over strikes, "OPEN IN OSTR" carrying symbol + expiry + chosen strikes via the new active-symbol store (`ui/lib/activeSymbol.ts`, prefs-synced, per window) | 1.1 tables + the live chain | M | `arithmetic` |
| **Context columns** | delta-equivalent OI / % of MWPL and NSE contract delta on OMON and DERV; ban list + expiry calendar (weekly index, monthly stocks, holiday shifts from the Breeze master) on EVTS/ECO | `combineoi_deleq`, `Contract_Delta`, `fo_secban`, `fo_mktlots` (all verified) | S | `context` |
| **Excess-carry screen on DERV** | discount-quintile names with the alpha_lab Q1 verdict text attached ("lead, not a rule"; t −4.2 / −2.9), no colour | UDiFF futures + `nse_bhavcopy` | S | `context` |
| **"Who is short options" line** | Pro/Client/FII call & put short OI from `nse_participant_oi` as a context line beside the chain; the GEX-style proxy itself waits for Wave 3 + a study | have | S | `heuristic` |

### 1.4 Data health and freshness (R-DATA #2, #3, #6, #11; R-UI #11)

**Scope.** `dataset_catalog` (the gold catalog pattern terminal-wide), `ingest_log`, `GET /api/data/health`, a SYS › DATA
sub-view (GO alias `DATA`), a `DATA n STALE` header chip, `SourceChip` on every panel header of every page, the ingest of the
verified-but-missing NSE evening files, insider PIT nightly for the F&O universe, point-in-time columns on the NSE tables.

**Catalog row** (seeded from R-DATA §3's 45 rows): `{id, label, pages[], publisher, publish_time_ist, expected_by (HH:MM,
trading-day aware via /db/market-holidays), max_age, unrecoverable:bool, ingest_job, dictionary_anchor, verdict, badge}`.

**API.** `GET /api/data/health` (60 s SWR) → `{as_of, rows:[{id, label, pages, publisher, published_ist, expected_by, as_of,
lag_sessions, state: live|fresh|amber|red|gap, unrecoverable, job_id, last_run{ts,status,ms}, next_run, catchup_at, note,
dictionary_anchor}], summary{green, amber, red, gaps}}` from `/db/nse-positions-meta`, `/db/archive-meta`, `/db/freshness`,
`/db/stats`, `/db/market-holidays`, `/api/telemetry/status`, `/api/gold/catalog` + the gold `freshness()` helper,
`data/.scheduler_history.json`, `ingest_log`.

**Jobs.** Hourly controller check reading the same endpoint; one Telegram line per transition (green→amber→red); an 08:35
digest; the dead-man ping stays the only alert that works when the Mac is off. `DATASET_MAX_AGE_DAYS` (days) retired in favour
of `expected_by`.

**Ingests added** (`nse_positions.ingest_daily` pattern; all verified; 20:30 pass): combined OI/MWPL (19:23), clients ≥ 3 %
MWPL (`content/nsccl/mwpl_cli_DDMMYYYY.xls`, T−1), participant volumes (`fao_participant_vol_DDMMYYYY.csv`), FII derivative
stats (`fii_stats_DD-Mon-YYYY.xls`), FOVOLT, Contract_Delta (1.1), insider PIT per stock nightly for the F&O universe
(the per-stock `corporates-pit` path works; the market-wide one is empty). PIT columns (`release_at`, `first_seen_at`,
revision rows) on `nse_bhavcopy` (re-publications), `nse_deals` (late additions), `nse_results` (`exchdisstime`).

**UI.** SYS › DATA: kit `DataTable` with RAG chips, sort by lag, filter by page; honest wording ("stored 30 Oct · expected by
21:00 · 3 sessions behind · catch-up 19:30 tomorrow"); no composite score. Header chip `DATA 2 STALE` linking to it.
`SourceChip` with age on every panel (`ui/components/terminal/index.tsx` already exports it; the payloads already carry
`as_of`); staleness never in body prose only (RSK, WRAP, CMDT, WTCH fixed).

### 1.5 Architecture unblockers (R-ARCH 2, 4, 5; owned by B7, land first)

| Item | What | Evidence · expected effect | Cost |
|---|---|---|---|
| **DuckDB read concurrency** | `DuckDBStore.read(sql, params) -> df` on a per-call `self._conn.cursor()` behind a readers-writer lock (`write()` exclusive, `read()` shared); the 42 `store._conn` bypasses retired behind it; `anyio` thread limiter raised to match; **Yahoo removed from `/db/market-monitor`'s locked request path** (`_nifty500_close` → NSE's `ind_close_all` row stored nightly) | R-ARCH §2.3: 10 concurrent reads 1,243 ms vs 1,456 ms sequential sum → expected wall ≈ max single (≈ 250 ms); the §2.3 harness becomes a perf test | M |
| **One HTTP client per process** | module-level `httpx.AsyncClient` in `shared/http_client.py` with `Limits(max_connections=32, max_keepalive_connections=16)`, per-route timeouts, a per-upstream circuit breaker and stale-serve for `nifty-live` / `gift-nifty` / `indices-live` | ~130 per-request client constructions; 312 + 40 upstream-flake 5xx passed through | S |
| **Observability contract** | Prometheus `/metrics` on all three (request count/latency histograms by route family, DuckDB lock wait, job durations, cache hit ratio, Breeze budget used, tick/chain lag); request-id middleware calling `set_correlation_id` and echoing `X-Request-ID`; JSON access log through the structured logger with `/health`, `/`, `/live` excluded; CLAUDE.md corrected | `/metrics` 404 today; 0 request-path callers of `set_correlation_id`; json=4 vs access=19,992 per 20 k lines | M |
| **Snapshot policy** | one evening read-only snapshot (exists) + one per-process read-only connection to it for analytics instead of `/tmp/bt_snapshot.*` per ui-api boot; prune orphans at start | 4.4 GB in `/tmp` per boot | S |

### 1.6 Docs and LEARN (B5)

`docs/NSE_DATA_DICTIONARY.md`: verified rows for the top-10 weights file, constituent lists, FOVOLT, Contract_Delta,
combineoi_deleq, SPAN file, `historicalOR/vixhistory`, the legacy F&O format, the dead `equity-stockIndices`; the 22:05 /
22:12 publication times. `docs/TERMINAL_DATA_DICTIONARY.md` generated from `dataset_catalog` (`--check` in tests, as the gold
dictionary). RSCH CATALOG rows: "IV history (DESCRIPTIVE)", "Index drivers (DESCRIPTIVE)", "SPAN margin (ARITHMETIC)".
LEARN entries (glossary + tooltips): IV rank vs percentile, constant-maturity IV, put-call-parity forward, 25Δ skew, Parkinson /
Yang-Zhang, FOVOLT, SPAN vs exposure margin, points attribution and its residual, hysteresis. `CLAUDE.md`: the `/metrics`
claim fixed, the new tables and jobs listed, the freeze-window note extended. `IMPROVEMENT_LOG.md` entry.

### 1.7 Tests and gates (B6)

| # | Gate | Pass condition |
|---|---|---|
| G1 | `tests/unit/test_iv_eod.py`: parity forward (fixture 3 Nov NIFTY: 23,931.23), untraded strikes → no IV, expiry-day rows excluded from "near", `iv30_cm` bracketing, rank vs percentile on a synthetic series (rank 21 / pctile 60 fixture), legacy parser on `fo01APR2022bhav` (monthly ATM 17.13 %, 96 IV strikes), `model_version` + `r` on every row | green |
| G2 | Replay: `iv_eod` on 23 cached Oct-2026 files reproduces `R-IV/iv_compare_NIFTY.csv` within 0.05 vol-pt; corr vs `option_history.json` ≥ 0.99 | green |
| G3 | `tests/test_index_drivers.py`: PIT (no `shares_filed_at` / `promoter_public_at` > date), identity (Σ weights 100 ± 0.01, Σ points = explained), KOTAKBANK 14 Jan 2026 split within ±5 %, 1 Feb 2026 present with `index_close_source = nse_daily_file`, 60-session MAE ≤ 25 pts else `fit.degraded`, calibration equals the official top-10 to 0.01 pp, hysteresis fixture (63 raw changes → 5) | green |
| G4 | `tests/test_data_health.py`: every ingest job and every page data source has a catalog row; `expected_by` trading-day aware; gap rows render as GAP; `ingest_log` sha256 dedupe; `If-Modified-Since` re-fetch writes a revision row | green |
| G5 | `tests/test_hosts_allowlist_terminal.py`: static scan of `fo_iv/`, `index_drivers/`, `data_health/`, `nse_positions.py`, the new routers — hosts ⊆ §0.6; no `query1`/`query2`/`yfinance` in new code; Yahoo absent from `/db/market-monitor` | green |
| G6 | `services/ui-api/tests`: `/api/derivatives/iv/*`, `/vol-screen`, `/api/market/index-drivers*`, `/api/data/health`, `/api/options/margin` (Breeze mocked; fallback order Breeze → SPAN file → heuristic with the 4.8× note); budget ledger refuses past the cap; no publisher on the request path (assert zero outbound calls under a fake transport) | green |
| G7 | Concurrency: the R-ARCH §2.3 harness as a test — 10 concurrent history reads wall ≤ 2 × single; `/health` ≤ 10 ms during the burst | green |
| G8 | Observability: `/metrics` 200 on :8001/:8010/:8008 with the named series; `X-Request-ID` echoed; access log excludes `/health` | green |
| G9 | UI checks (`*.check.ts`): "IV percentile" and "IV rank" both defined; context panels use the neutral token; the regime strip ends "describes, does not predict"; `SourceChip` present on every `Panel` (static scan); the live today panel renders on MOV and BRF only, the horizon table on MEMB only; VIX once per page; unknown `?tab=` shows a toast | green; `npx tsc --noEmit` |
| G10 | `scripts/ui_audit.py --tabs all --browser both` 43/43, 0 console errors; `scripts/ui_perf.py` budgets (OMON chain ready ≤ 400 ms; first-load gz ≤ 300 KB) | green |
| G11 | `scripts/tests`: the new jobs in `missed_jobs()`; 22:45 / 08:35 passes; `iv_intraday` skipped without a session and past the budget; freeze-window deferral unchanged | green |
| G12 | CI: ruff/mypy/pin-drift/pip-audit steps green; `tests/test_gold_study_reproduce.py` collects (the `NameError: dataclass` in `scripts/gold_studies/gs_p2_wgc_flows.py:64` fixed by the gold round or here) | green |
| G13 | Live acceptance (first week): `iv_eod` lands by 21:30 five days running; the Saturday recompute runs; `index_drivers_daily` finds the top-10 file by 20:35; the DATA view shows ≤ 2 amber at 22:00; one 15-min intraday day stored end to end | owner reads it |

### 1.8 Deploy (respecting the freeze windows)

1. Branch from the post-GOLD-fix state; B7 lands first (concurrency, HTTP client, metrics) and is deployed alone on a
   Sunday morning (data-service + ui-api + controller restart outside both windows; `start-local.sh restart` each with
   `/health` checks; the G7/G8 gates re-run live).
2. B1 + B2 (tables, jobs, passes) deploy on a weekday at ≥ 21:30 or a Sunday; the one-off backfills start the following
   Sunday 10:00 (UDiFF 30 min, legacy 1 h, drivers 2 min), never beside the 02:15 backup; `db_backup.py` runs once after.
3. B3 (ui-api) deploys any time outside 07:55–08:10 with `UI_API_RELOAD` off; B4 ships as one `./start-local.sh build-ui`
   release (rollback with `--rollback`); `scripts/build_desktop.sh --install` only if the shell changed (it does not).
4. Jobs are enabled with their histories starting that day; the pages say "since <date> · backfilled from stored files to
   2019-10-01".

### 1.9 Owner decisions needed for Wave 1

O-T1 private git remote + off-machine backup target · O-T2 dead-man ping / autorestart / FileVault this week ·
O-T3 free FRED API key · O-T4 IV backfills (30 min + 1 h from cached files) and surface scope (indices + watchlist vs all 224);
O-T4b the 2001–2019 archive download (3.6 GB, 2.5 h) · O-T5 risk-free policy (dated 6.5 % constant vs weekly RBI 91-day) ·
O-T6 Breeze budget cap for the chain poller (≈ 700/day pilot; 1,100–1,500 in Wave 2) · O-T7 NSE option-chain-v3 beside
Breeze intraday (NSE site terms, ban risk) · O-T8 relabel "IV rank" now (yes recommended) · O-T9 NSE's daily index file as the
NIFTY series everywhere incl. the crash filter (shifts the 200-DMA by one session; "DO NOT CHANGE without review") ·
O-T10 Redis bind + password, `.env` 600 · O-T11 display-only posture for the top-10 weights and constituent files ·
O-T12 indices beyond NIFTY 50 / BANK in the first release · O-T13 confirm the NIFTY Bank member count (file lists 14) and
obtain the official cap factors · O-T14 VOL / DATA / DRVR as sub-views (recommended for Wave 1) or 44th–46th pages later.

---

## Wave 2 — The trading day (weeks 5–9)

Builds the options trader's intraday and book layer on the Wave 1 tables, re-cuts the shell for the trader, and finishes
the data-tier split. Takes R-WORLD #3 (2-min), #5 (scanner extensions), #6, #7, #9, #10 (panel), #13, #15, #17, #22;
R-OPTIONS #4–#9; R-UI #1, #2, #5, #6, #9, #10, #15; R-DRIVERS 5–7; R-DATA 8–9 (if not in Wave 0); R-ARCH 3, 7.

| # | Item | Scope | Source · cadence | Tables / API | Panels · badge | Cost | Owner |
|---|---|---|---|---|---|---|---|
| 2.1 | **Intraday OI / IV tape** (R-OPTIONS #5, R-WORLD #3) | NIFTY / BANKNIFTY / FINNIFTY near + next expiry, both sides, every 2 min 09:15–15:30 through the budget ledger (≈ 1,100/day; the 15-min pilot's month of data decides); OI change by strike since open, ATM IV and straddle through the day, bid/ask on OMON LIVE; NSE v3 as fallback | Breeze chain quotes (verified); raw parquet `data/ticks/chain/`, derived `iv_intraday`; `GET /api/derivatives/iv/{sym}/intraday`, `/oi-tape` | OMON › LIVE: OI-by-strike time-lapse, straddle decay, IV path; `context`, `SourceChip` LIVE Breeze | M | O-T6 |
| 2.2 | **Paper F&O book + position Greeks + what-if** (R-OPTIONS #4, R-UI #5, R-WORLD #6, #17) | "Book paper" on OSTR writes legs to `paper_fo_positions` (ui-api SQLite, PAPER ONLY, separate from the cash book); marked daily from `iv_surface_daily` closes and from Breeze quotes in session; net Δ Γ Θ ν per underlying and total; P&L grid spot (±5 %) × IV (±10 pts) × days; probability of profit from N(d2) labelled `heuristic` (lognormal); roll helper; RSK gains Greeks exposure, delta-gamma VaR, vega, margin utilisation (real SPAN), IV-shock and gap scenarios beside the equity VaR; a POS page view = Desk book + demat + paper F&O/futures (PORT's legacy engine moves under RESEARCH) | own math (`options_math.py`), Breeze quotes, 1.3 SPAN | `paper_fo_positions`, `paper_fo_marks`; `POST /api/options/book` (paper), `GET /api/options/book/greeks`, `GET /api/risk/fo` | OSTR v2 (save/name, sliders, 2-D heat map, multi-expiry legs), RSK › F&O, POS; `arithmetic` / `heuristic` (POP) | L | O-T15 paper F&O book approved |
| 2.3 | **Event-driven alert engine** (R-WORLD #22, R-UI #6, R-OPTIONS #6) | rule JSON `{series, op, value, window, cooldown, repeat, channel}` over any stored series: IV pctile cross, IV − RV extreme, straddle price, OI wall moved, basis / rollover pace, ban entry/exit, results in N days, FII net extreme, VIX ±10 % intraday, driver changed, gold health clause changed, data stale; created from a chart level or a chain strike; alert lines on CHRT; inbox grouped by symbol; Telegram parity; **no alert implies direction** | 1.1 / 1.2 / 2.1 tables; scheduler each minute in session + after each EOD step | `alert_rules`, `alert_fires` (successor of `data/alerts.json`); `/api/alerts/rules` CRUD | ALRT v2; `context` | M | — |
| 2.4 | **Expiry-day view** (R-OPTIONS #7, R-WORLD #7) | OMON › XPRY sub-view on expiry days: OI unwind by strike, max-pain drift, straddle decay vs the historical expiry-day curve, pin-risk strikes, an implied-vs-realised scorecard kept like the gold accuracy log | 2.1 tape + Breeze 1-min bars of past expiries (verified; ≈ 400 calls per index-year, paced, outside the windows) | `iv_expiry_replay`; `GET /api/derivatives/expiry-day` | `arithmetic` (scorecard) / `context` | M | O-T16 replay budget |
| 2.5 | **Options scanner extensions + vol-crush + participants full** (R-WORLD #5, #9, #10; R-OPTIONS #9, #14) | VOL screener gains OI build-up class (H2: no edge → `context`), unusual volume, % of MWPL, results within N; EVTS vol-crush ledger (1.1) gets the 8-quarter priced-vs-realised table; participant OI options side + volumes + FII derivative stats panel (the gold COT "who did what" wording); futures-equivalent OI panel; commodity + expiry calendar on ECO/EVTS (gold PLAN §b, R-WORLD #13) | 1.4 ingests, `gold_events` | — | `context` | S–M | — |
| 2.6 | **Shell re-cut for the trader** (R-UI #1, #2, #9, #10, #15) | strip = BRF WTCH CHRT OMON OSTR DERV MOV EVTS ALRT POS GOLD MCXG RSK MKT, user-orderable in prefs, Alt/⌘ 1–0 follow; RESEARCH ▾ menu for BTST PIPE LWSC ALFA GBOX MLEN DEXP WHSE OVRV RSCH; active-symbol context everywhere (stock window gains OMON and CHRT tabs; GP opens CHRT on the active symbol; COMP/DEAL/DERV read it); GO v2 arguments (`TCS OMON 27NOV`, `NIFTY OSTR IC`, `ALRT TCS >3200`, `TCS VS INFY`, `GOLD COT`) with hints and a visible recent row; chrome budget (first data row ≤ 180 px: settings banner → toast, NEW-SINCE → bell, NEEDS-YOU → one chip, collapsible tape); BTST/GBOX/MLEN show the last result; BTST defaults to `COST_PROFILE` costs; one gold fair value on one page once GOLD deploys | — | `/api/prefs` keys `strip.order.v1`, `activeSymbol.v1` | — | M | O-T17 confirm the ten Alt/⌘ pages |
| 2.7 | **Pre-trade gate** (R-WORLD #15) | one `POST /api/pretrade/check` called by every paper ticket (equity, OSTR, MCXG): edge ÷ cost, liquidity (≤ 1 % of 20-d ADV; chain bid-ask for options), surveillance flags, F&O ban, position / industry / drawdown limits, real SPAN, tax lot, REFUSE with the reason written to the journal store | existing cost model + 1.3 SPAN + NSE ban/ASM | `pretrade_log` | ticket panels; `arithmetic` | M | — |
| 2.8 | **Data-tier split + push** (R-ARCH 3, 7) | `ml_features` / `ml_labels` / `ml_oos_predictions` (25 M rows, dormant) → parquet archive or an attached `ml.duckdb` for the ML jobs only; `EXPORT/IMPORT` or `VACUUM` the hot file (reclaims 0.7 GB free blocks); `.zst` backups; `/ws/monitor` → typed multiplexed channels (`nifty`, `notifications`, `alerts`, `ticks:<sym>`, `chain:<sym>`) fed once from data-service via Redis with a per-client bounded queue (drop-oldest) and a lag chip; polling kept as fallback; precondition for `LIVE_TICKS=1` reaching the browser | — | — | — | M + M | O-T18 ML tables may leave the hot file; O-T19 browser receives ticks over WS |
| 2.9 | **Drivers follow-ups** (R-DRIVERS 5–7, R-WORLD #8 variance share) | membership history Mar/Sep 2024–2026 entered by hand from niftyindices press releases; the 2-min `internals_sample` gains heatmap members' % change → within-day contribution timeline on MOV (zero extra NSE budget); variance-share column (w·β·σ over 60 d); live MOV panel applies the top-10 calibration (O-T20) | `heatmap-symbols` (already allowed) | `index_constituents_daily` rows; `index_intraday_contribution` | MOV › "driving the move now"; `arithmetic` | M | O-T20 |

Gates: G1–G13 stay green; new: paper-book PAPER-only test (no route reaches Breeze order methods; `EXECUTION_LIVE_ALLOWED`
unset refuses), budget-ledger test at 2 min, alert-rule test that no rule carries a direction word, strip/alias drift
check (`desktop.check.ts`), chrome-budget check (first data row y ≤ 180 px in `ui_perf`), WS backpressure test (slow client
dropped, hub alive), VACUUM/ATTACH tests for the ML split, `pages.check.ts` repetition rule for the new sub-views.
Deploy: as Wave 1; the ML split runs on a Sunday with a verified backup first; the WS change ships ui-api + UI together.

---

## Wave 3 — The learning loop and the platform (weeks 10–15)

| # | Item | Scope | Source | Cost | Owner |
|---|---|---|---|---|---|
| 3.1 | **JRNL trade journal with attribution** (R-WORLD #16) | per paper fill: thesis + tag, invalidation, planned vs filled, MAE/MFE, exit reason; P&L split beta / factor / alpha / cost / slippage; expectancy by tag, hour, DTE; folded into the Friday 20:10 journal | `data/paper_trades.db`, `decision_desk.db`, `paper_fo_positions` | M | — |
| 3.2 | **Tracking band + auto-demotion** (R-WORLD #21; PRODUCT_STRATEGY §3.5) | bootstrap bands from the gate backtests vs live NAV for the Desk and S1/S1H; breach rule (3 months below the 5th percentile → flag/paper-only) on DESK and in the journal | gate backtests, shadow NAV | M | O-T21 the breach rule |
| 3.3 | **GEX proxy + pre-registered study** (R-WORLD #4) | gamma exposure by strike with the "writers are short" assumption, zero-gamma level, net GEX history; `heuristic`, never coloured, shown beside participant OI; B8 study (`reports/terminal_v2/studies/gex/PLAN.md` before results) before it may become `context` | `iv_surface_daily`, `nse_contract_delta`, `nse_participant_oi` | S + study | — |
| 3.4 | **Launchpad workspaces + chart linking** (R-UI #3, #8; R-WORLD #23) | saved 2–4 panel layouts in one window (chain + chart + strategy + positions), resizable grid, linked symbol groups; CHRT opens on the active symbol, drawings persisted per symbol, results/ex-date markers, OI-wall and max-pain lines, compare overlay, VWAP from the tick store, 2×2 | prefs | L | O-T22 Launchpad vs ⌘N first |
| 3.5 | **Watch columns + sections** (R-UI #7) | column picker in prefs, sections (Holdings / Desk / F&O underlyings / Gold), per-panel source chip, F&O columns (IV rank, PCR, next expiry, basis) | 1.1 tables | S–M | — |
| 3.6 | **Phone** (R-UI #12, R-WORLD #24) | compact ≤ 720 px layout for BRF, WTCH, ALRT, MOV, OMON summary, MCXG/GOLD health (single column, 44 px targets, bottom tab bar, tables as cards or scroll-with-cue); Telegram bot gains chart PNGs (NIFTY intraday, IV today, DRVR) rendered server-side; read-only over Tailscale only, never a LAN bind | — | M | O-T23 phone as a first-class surface |
| 3.7 | **Kit unification + DESIGN.md** (R-UI #13) | EQS/BTST/PIPE/ALFA/GBOX/MLEN/DEXP on `Panel/DataTable/Input/Btn`; `tabular-nums` in the kit; one amber; virtualised `DataTable` > 300 rows; `DESIGN.md` | — | M | — |
| 3.8 | **Persisted job queue, SLOs, chaos drills, env isolation** (R-ARCH 6, 8, 10, 12) | `jobs` table with lease/attempts/progress owned by the controller, exactly-once by (kind, date), catch-up = re-enqueue; SLOs (p95 ≤ 150 ms warm on the 20 routes, first paint ≤ 1.5 s, freshness ≤ 1 session, job success ≥ 99 %/30 d) with a 5-min synthetic probe on SYS and an error budget; monthly Sunday chaos drills (SIGSTOP ui-api, SIGKILL data-service mid-ingest, Redis down, disk 95 %, Breeze expired, clock skew) against a staging DB copy; a per-stack venv or `uv` lockfile so CI installs what prod runs | — | L + S + M + M | O-T24 per-stack venv |
| 3.9 | **Notebook client `sd`** (R-WORLD #20) | `shared/sd.py`: `sd.read("iv_summary_daily", since=…)`, `sd.get("/api/…")` on the read-only snapshot; Jupyter templates for the pre-registered study format | — | S–M | — |
| 3.10 | **Legacy archive 2001–2019 + satellite collector** (R-IV 8; R-DATA 10) | the paced 3.6 GB F&O archive download (25-year IV cone) if O-T4b; a ₹730/mo Mumbai VM running the light pollers (pre-open, internals, FII/DII, chain snapshots) to object storage if the Mac cannot be made an appliance (O-T25) | nsearchives; cloud | L / L | O-T4b, O-T25 |

---

## Wave 4 — Frontier (after week 15; each behind an owner decision)

| # | Item | Scope | Owner decision |
|---|---|---|---|
| 4.1 | **ASK — LLM analyst over the terminal's tables with citations** (R-WORLD #19) | read-only SQL on the 19:20 snapshot (SELECT only, no ATTACH/COPY/PRAGMA, row/time caps), GET-only API, no writes/orders/Telegram, forecast refusal by policy + output classifier, prompt-injection isolation (news/filings as quoted data), every answer logged with SQL + row hashes, provider switch (`settings.llm_provider`, local Ollama for private holdings), nightly 50-question eval set gating deploys, "I could not verify" instead of an estimate | O-T26 cloud vs local |
| 4.2 | **MCX options chain + IV** (R-WORLD #12; gold O-8) | one read-only Breeze probe for MCX option chain/history on a trading day; if served, reuse 1.1/2.1 with `exchange_code=MCX` for GOLD / SILVER / CRUDEOIL; else O-8 | O-T27 probe approved; O-8 |
| 4.3 | **Silver and crude desks from the GOLD template** (R-WORLD #14) | catalog-gated panels, PIT tables, COT (same CFTC family), CME FTP OI; badge rules unchanged | O-T28 |
| 4.4 | **Tape replay RPLY** (R-WORLD #18) | replay any stored session at 1×/10×: NSE 1-min index feed, tick-store parquet (after a `LIVE_TICKS=1` season), the chain as of T from the intraday tape, filings by `release_at` | O-T29 `LIVE_TICKS=1` supervised session (R-DATA 12) |
| 4.5 | **Excel / Sheets functions** (R-WORLD #25) | `=SD.PX`, `=SD.HIST` via Power Query against the loopback API behind a local bearer token | O-T30 token on the loopback API |
| 4.6 | **Overnight lead strip with an accuracy log** (R-WORLD #11) | GIFT gap + US close + Asia + USD/INR + Brent + gold → one "implied open" line, `heuristic`, measured like the gold log; stored tape values, no new Yahoo caller | — |
| 4.7 | **Multi-user groundwork** (R-ARCH 15) | only when a second user exists: auth in front of ui-api, per-user prefs/alerts/paper books, rate limits, stateless ui-api (caches to Redis), N workers behind a local proxy, per-instance read-only replicas on the nightly snapshot | O-T31 second user in 6 months? |

---

## Appendix A — R-WORLD's 25 capabilities → waves

#1 → 1.1 · #2 → 1.1 (DERV › VOL) · #3 → 1.1 pilot, 2.1 · #4 → 3.3 · #5 → 1.1 screener, 2.5 · #6 → 2.2 · #7 → 2.4 · #8 → 1.2 ·
#9 → 2.5 · #10 → 1.3 (ingest), 2.5 (panel) · #11 → 4.6 · #12 → 4.2 · #13 → 2.5 · #14 → 4.3 · #15 → 2.7 · #16 → 3.1 ·
#17 → 2.2 · #18 → 4.4 · #19 → 4.1 · #20 → 3.9 · #21 → 3.2 · #22 → 2.3 · #23 → 3.4 · #24 → 3.6 · #25 → 4.5.

## Appendix B — What needs paid data (said plainly)

Exact daily NSE index weights / IWF (NSE Indices data product) — not needed, the free top-10 file calibrates. Historical
tick / order-level options data (NSE, ≈ ₹1.1 L/yr/segment) — not needed for anything above. Consensus estimates, a news
wire, an outstanding-short-interest number, a dealer/customer option split, an options trade tape — no free Indian source;
the pages say so instead of approximating. ICICI Breeze is already licensed (own-account use, no redistribution).

## Appendix C — Consolidated owner decisions (O-T1 … O-T31)

O-T1 remote + off-machine backup target · O-T2 dead-man / autorestart / FileVault · O-T3 FRED key · O-T4 IV backfills +
surface scope; O-T4b 2001–2019 archive · O-T5 risk-free policy · O-T6 Breeze budget cap · O-T7 NSE v3 beside Breeze ·
O-T8 relabel IV rank now · O-T9 NSE index file as the NIFTY series (crash filter) · O-T10 Redis/`.env` hardening ·
O-T11 display-only posture for the index files · O-T12 extra indices · O-T13 NIFTY Bank count + cap factors · O-T14 sub-views
vs new pages · O-T15 paper F&O book · O-T16 expiry replay budget · O-T17 the ten Alt/⌘ pages · O-T18 ML tables leave the hot
file · O-T19 ticks to the browser · O-T20 calibrate the live MOV panel · O-T21 tracking-band breach rule · O-T22 Launchpad vs
⌘N · O-T23 phone surface · O-T24 per-stack venv · O-T25 satellite collector · O-T26 LLM provider · O-T27 Breeze MCX probe /
O-8 · O-T28 silver/crude · O-T29 `LIVE_TICKS=1` session · O-T30 API token for Excel · O-T31 second user. Plus one
clarification: which events
count as NIFTY "events" for the vol tools (RBI, Budget, US CPI/NFP/FOMC, elections; `gold_events` already carries the US set).
