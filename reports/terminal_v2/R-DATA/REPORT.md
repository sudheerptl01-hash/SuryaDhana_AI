# R-DATA — the data-update side of the SuryaDhana terminal

Written Wed 4 Nov 2026, 22:00–22:40 IST, read-only against the live stack (data-service :8001, ui-api :8010,
master-controller :8008; GET only, ≤ 2 req/s), `.logs/*` for the last 14 days, `data/.scheduler_history.json`,
`last reboot`/`pmset`, and 13 paced external probes (one GET/HEAD each, browser UA; results in
`probe_results_2026-11-04.json` beside this file). No file under `data/` was opened.

## Executive summary (10 lines)

1. **Overall data-update rating: 5 / 10.** The pipes are well built; the platform they run on is not. Every EOD dataset the terminal shows was current to 4 Nov by 21:45 tonight, but only because the owner rebooted the Mac at 21:24 and the controller's catch-up re-ran three missed sessions in seven minutes.
2. **The stack was dark for 106 hours (31 Oct 11:29 → 4 Nov 21:29) and for 43 hours (28 Oct 12:46 → 30 Oct 08:11).** Over the 10 trading sessions of the last 14 days the terminal was alive during market hours for 5½ (55 %). Nobody was told: the only alerter (the controller) was down with the Mac and the off-machine dead-man ping (`HEALTHCHECK_PING_URL`) is still "not set".
3. **Intraday captures from those sessions are gone for good**: pre-open book (2, 3 Nov), breadth samples (29 Oct, 2–4 Nov), FII/DII cash (NSE serves only the latest day; 3 of 18 days missing since 9 Oct), ICICI gold open captures, every price/move/filing alert. Archives: pre-open 13 of 19 sessions, internals 10 of 16.
4. **Silently rotted (job says "done", table does not move)**: CME COMEX daily OI / EFRP / product reference — **0 rows since the gold program launched** (Python `ftplib` chokes on the CME FTP's `229 Extended Passive Mode` reply; reproduced tonight in 1 s); **all 18 FRED daily series fail on every run since 30 Oct** (keyless `fredgraph.csv` times out at 20 s with both user agents from this machine; each run burns 378 s); `gold_brief_docs` stuck at 23 Oct although the 09:05 job ran; `gold_health_daily` has 1 row in 7 trading days; `gold_preopen_log` table 0 rows.
5. **Not caught up by the start-up catch-up and still stale tonight**: Decision Desk mark (30 Oct; the Nov rebalance plan is PENDING and its orders will be EXPIRED tomorrow), S1 shadow (30 Oct), results release times (30 Oct 20:49 — in the middle of Q2 results season), news track record (30 Oct), index valuation history (30 Oct), SGE/SHFE (30 Oct), GLD/ETF holdings (30 Oct), Atlanta Fed path (29 Oct, shown STALE).
6. **Measured publication times tonight (HTTP Last-Modified, IST)**: F&O UDiFF bhavcopy and participant OI **20:10**, combined OI/MWPL 19:23, F&O volatility 17:01, equity full bhavcopy **re-published 22:05** (after the stack had stored it), MTF file for T−1 **22:12** → the 20:30 catch-up job can never see it, so MTF is T+2 in the terminal (today: 2 Nov). The 18:30 EOD job is an hour too early for every F&O file; the 20:30 job is what actually delivers them.
7. **Access traps verified (one GET each)**: `quote-equity` 403 Akamai, `quote-derivative` 404, old `option-chain-indices` 404, market-wide `corporates-pit` returns `{"data":[]}`, and `option-chain-v3` works (NIFTY 23-Nov: 123 strikes, NSE ts 15:40:00). `historical/bulk-deals` without `csv=true` answered 503 to a cookie-less client (the 70-row cap could not be re-verified).
8. **Freshness observability is GOLD-only.** The gold package has a 211-row catalog with `max_age_days` and `publish_time_ist` and every panel carries live/delayed/stale/unavailable; the other 42 pages have none of that. The NSE check (`DATASET_MAX_AGE_DAYS`) tolerates 5 days for daily sets, runs only after the EOD job and the Saturday filings job, and alerts only on Telegram. SYS shows job latencies, WHSE shows Yahoo bar coverage; **no page shows dataset lag against an SLO**.
9. **Options/IV data is thin for the owner's stated goal**: the only IV history is NIFTY and BANKNIFTY near-expiry ATM IV / PCR / max pain, daily from the F&O bhavcopy since 8 Jul 2024 (578 rows, refreshed lazily on request); no stock-option IV history, no intraday chain snapshots (the live chain is polled with a 30-s TTL and thrown away), tick store never armed (`LIVE_TICKS=0`, `data/ticks` empty), Breeze session depends on a morning SMS OTP that the scheduled job has failed to obtain on all 4 recent runs ("needs you").
10. **Top fixes, in order**: (1) off-machine dead-man ping + `pmset autorestart` + no FileVault pause (S, owner); (2) a DATA health page + `/api/data/health` with a per-dataset SLO and RAG, and the GOLD `SourceChip` pattern on every panel (M); (3) reschedule to the measured publication times and add a 22:45 pass (MTF, FII/DII, bhavcopy revisions) (S); (4) fix CME FTP EPSV and move FRED to the keyed REST API with a circuit breaker (S); (5) daily option-chain snapshots + per-strike IV history from the cached F&O files 2019→ (M); (6) extend start-up catch-up to every replayable daily job (S).

---

## 1. What runs, when, and what it writes (the job → dataset map)

Source: `scripts/master_controller.py` (job registration lines 3081–3310, `GOLD_JOBS` 831–870), `services/data-service/main.py`
(`/jobs/daily-pipeline` steps 586–591), `nse_positions.py`, `eod_steps.py`. All times IST.

| Job (id) | Schedule | Fetches / writes | Dataset(s) |
|---|---|---|---|
| `icici_session_refresh` | Mon–Fri 08:00 (+ once at start-up on a trading morning) | `daily_session_refresh.py` TOTP/SMS login → token into ui-api | Breeze session (live quotes, MCX, holdings) |
| `pre_market_sync` | 08:30 daily | `POST /jobs/refresh-universe` incremental (Yahoo bars) + `/db/freshness` check (CRITICAL if ML features stale) | `ohlcv` (1,496 tickers) |
| `gold_mcx_master` | Mon–Fri 07:35, retry 08:35 | ICICI security master + NRML margins | `gold_curve` (MCX contracts), margins |
| `gold_health_snapshot` | Mon–Fri 08:40 | health verdict snapshot | `gold_health_daily` |
| `gold_preopen_snapshot` / `gold_open_capture` | 08:45 / 09:10 (17:10 on morning-closure days) | fair open → accuracy log; actual open from Breeze 1-min bars | gold pre-open log (ui-api store) |
| `morning_note` | 08:50 | Telegram brief | — |
| `preopen_capture` | 09:09:30 | `GET /db/preopen?key=FO|ALL` → `data/nse_archive/preopen/<date>_*.json` | pre-open book (order imbalance) |
| `internals_sample` | every 2 min 09:15–15:31 | `POST /db/internals/sample` → `nse_archive/internals/<date>.jsonl` | intraday breadth (MOV, WRAP) |
| `price_alerts_check` / `move_alerts` / `filing_alerts` | 1 min / 5 min / 5 min (08:00–22:55 Mon–Sat) | NSE live quotes, announcements | alerts only (filing "seen" file) |
| `gold_intraday_bars` | every 5 min while COMEX trades | Yahoo 1-min GC=F, INR=X | `gold_bars_intraday` |
| `gold_calendar_refresh` | hourly 09:00–23:00 | Forex Factory US calendar | `gold_events` |
| `gold_india_midday` / `gold_india_pm` | 13:45 / 18:10 | IBJA AM/PM, RBI reference rate, India ladder | `gold_series` |
| `close_note` | 15:40 | Telegram | — |
| `gold_cme_daily` | Mon–Sat 15:45, retry 17:15 | CME FTP daily volume/OI, product reference | `gold_cme_daily_voi` (**0 rows**) |
| `gold_asia_close` | 16:10 | SGE daily + benchmark, SHFE | `gold_asia_daily` |
| **`eod_data_pipeline`** | Mon–Fri 18:30 | `/jobs/daily-pipeline`: Yahoo refresh (fatal) → NSE equity bhavcopy → NSE positions (F&O, participant OI, deals, MTF) → market monitor → corporate events → ML build (non-fatal, last); then `_check_dataset_freshness` | `ohlcv`, `nse_bhavcopy`, `nse_fo_daily`, `nse_participant_oi`, `nse_deals`, `nse_mtf`, market monitor, `nse_events`, `ml_features/labels` |
| `index_valuation_daily` | 19:15 | `backfill_index_valuation.py --recent 10` (NSE daily index file) | index P/E, P/B, DY history |
| `shared_snapshot_build` | 19:20 | APFS clone of market.duckdb for the evening jobs | evening snapshot |
| `desk_daily` | 19:30 | Decision Desk paper cycle (mark, plans, orders) | `data/desk*.sqlite` |
| `news_track_record_daily` | 19:45 | `news_scan_performance.py` | `reports/news_scanner/` track record |
| `alpha_shadow_daily` | 19:50 | `alpha_lab/paper/shadow.py --daily` | `alpha_lab/paper/state.json` |
| `nse_positions_catchup` | 20:30 | `/jobs/ingest-nse-positions` (datasets resume after last stored day) + `POST /db/fii-dii-cash/refresh` | F&O, participant OI, deals, MTF, **FII/DII cash (latest day only)** |
| `results_capture_daily` | 20:45 | `/jobs/ingest-results` for companies with a RESULTS event in the last 3 days | `nse_results` (release timestamps, ERN/PEAD) |
| `daily_wrap` | 21:00 | `reports/daily_wrap/<date>.md` + Telegram | — |
| `gold_fred_daily` | 21:30 | FRED daily (**all fail**), LBMA/WGC, CME EFRP (**fails**), derived | `gold_series` |
| `overnight_rl_retrain` | 23:00 | legacy, autopilot OFF | — |
| `db_backup_daily` | 02:15 | verified DuckDB backup (+ start-up catch-up) | `data/backups/duckdb/` |
| `gold_overnight` | Mon–Sat 03:10 | Treasury, Yahoo daily, CME final VOI (**fails**), FRED (**fails**), US calendar | `gold_series`, `gold_daily_bars` |
| `gold_morning` | 06:40 | GLD/IAU ETF holdings, Fed path, GPR, monthly series due | `gold_etf_holdings`, `gold_fed_path` |
| `gold_cot_weekly` | Sat 02:30, hourly retries to 06:30 | CFTC Socrata | `gold_cot` |
| `nse_filings_weekly` | Sat 09:00 | insider trades (PIT, per stock, top-300) + new shareholding XBRL | `nse_insider_trades`, `nse_shareholding` |
| `financials_sweep` | Sat 10:00 | NSE results XBRL prefetch | `archive:financials` |
| `gold_weekly` | Mon/Fri/Sat | WGC, RBI WSS, LBMA turnover, premiums, FRED weekly | `gold_series` |
| `weekly_journal` | Fri 20:10 | `reports/journal/<YYYY-WW>.md` | — |
| Lazy, on request | — | `GET /db/option-history/{sym}` spawns a background thread when a newer F&O file exists | `nse_archive/derived/option_history.json` (NIFTY, BANKNIFTY) |
| None | — | combined OI/MWPL, clients ≥ 3 % MWPL, delta-equivalent OI, F&O volatility (FOVOLT), participant volumes, FII derivative stats, 52-week file, P/E file, option-chain snapshots, OI spurts | **not ingested** (all are in `docs/NSE_DATA_DICTIONARY.md`) |

Not registered (owner decision O-8): `gold_mcx_bhavcopy`, `gold_mcx_category`, `gold_breeze_daily`. Dormant legacy: `intraday_inference`, `eod_rebalancing`, `overnight_rl_retrain` (autopilot OFF; they "run" in 0.2 ms).

## 2. Availability of the platform, last 14 days (why freshness fails)

Evidence: `last reboot shutdown`, `pmset -g log` ("powerd process is started" 30 Oct 08:09 and 4 Nov 21:26 = cold boots),
`.logs/watchdog.log`, the controller's own "controller was down since …" lines (`.logs/master-controller.log` 60604, 82102).

| Window (IST) | Duration | Cause (as far as the logs say) | Sessions lost |
|---|---|---|---|
| 22 Oct 09:25–09:28 | 3 min | watchdog preflight: "python cannot start from launchd (macOS Desktop-folder permission)" | — |
| 22 Oct 16:32–16:34, 24 Oct 15:28–15:42, 25 Oct 10:57–10:59 | minutes | reboots (program work) | — |
| 24 Oct 16:36 → 25 Oct 10:59 | 18 h | Mac off (weekend) | — |
| 25 Oct 14:40–14:48 | 8 min | ui-api event-loop hang (documented incident) | — |
| **28 Oct 12:46 → 30 Oct 08:11** | **43 h** | `shutdown` 28 Oct 12:46; reboot 29 Oct 16:56 but nothing ran until the 30 Oct 08:09 cold boot (FileVault/login wait) | 28 Oct (after 12:46), 29 Oct |
| **31 Oct 11:29 → 4 Nov 21:29** | **106 h** | heartbeat stops 31 Oct 11:29; next event is the 4 Nov 21:24 reboot. No sleep/wake rows survive in `pmset` → power-off or a hard freeze | 2, 3, 4 Nov |

Market-hours availability over the 10 sessions 22 Oct–4 Nov: **5½ of 10 (55 %)**. Both long outages were **silent**: the Telegram
"the stack was down" note is sent by the watchdog *after* the Mac comes back (4 Nov 21:29:06), `./start-local.sh status`
reports `dead-man-ping: not set`, `reboot-recovery: power-on after a power failure: off · FileVault: on`.

What the controller did on its own at 21:29 tonight (good, and the reason every EOD table is current): detected the gap from the
heartbeat, counted 3 missed `eod_data_pipeline` runs, ran `/jobs/daily-pipeline` (Yahoo 1,485 tickers refreshed; bhavcopy
+3 days, the 1 Nov request correctly rejected as a 30 Oct file; F&O +3; participant OI, deals; monitor as of 4 Nov; events
776 upserted; ML features through 4 Nov) in 6 m 49 s, captured the 4 Nov pre-open book (NSE keeps it until the next
session), wrote the 4 Nov wrap, ran the gold key jobs and the missed 02:15 backup (4.77 GB, from a private copy because the
evening snapshot is from 30 Oct).

## 3. Freshness matrix — every dataset the terminal shows, as of 4 Nov 2026 22:20 IST

Columns: source publication time (IST; **measured** = HTTP Last-Modified tonight, otherwise `docs/NSE_DATA_DICTIONARY.md`),
job, stored as-of (from `GET /db/nse-positions-meta`, `/db/freshness`, `/db/archive-meta`, `/db/stats`, ui-api payload
`as_of`/`date` fields), lag in sessions behind the last close (4 Nov), the proposed SLO, and the RAG against that SLO.

| # | Dataset (table / endpoint) | Pages | Published (IST) | Job | Stored as-of | Lag | Proposed SLO | RAG tonight |
|---|---|---|---|---|---|---|---|---|
| 1 | Yahoo daily bars `ohlcv` 1,496 tickers (`/db/freshness`, `/db/stats`) | EQS, CHRT, WHSE, DESK, BTST | ~18:00 | 18:30 EOD, 08:30 incremental | 2026-11-04 (1,482 fresh, 8 stale, 6 very stale: zero-volume ETFs/delisted, quarantined) | 0 | T+0 by 19:00 | G (via catch-up) |
| 2 | NSE equity full bhavcopy `nse_bhavcopy` (8.26 M rows, 2010→) | DES, EQS, DEAL, MKT, Desk universe | first copy by ~18:30; **re-published 22:05 (measured)** | 18:30 EOD (+ catch-up) | 2026-11-04 | 0 | T+0 by 19:00, re-fetch on revision | G, revisions never re-fetched (`_cached_get` keeps the first copy forever) |
| 3 | F&O UDiFF bhavcopy → `nse_fo_daily` (per-symbol aggregate, 330 k rows) + cached files `nse_archive/fo/` (2019-10→, 1,720 files) | DERV, OMON, OSTR, MKT | **20:10 (measured)** | 18:30 EOD (too early) → 20:30 catch-up | 2026-11-04 | 0 | T+0 by 21:00 | G |
| 4 | Participant-wise OI `nse_participant_oi` | MKT › participants, FII panel | **20:10 (measured)** | 20:30 | 2026-11-04 | 0 | T+0 by 21:00 | G |
| 5 | Bulk / block / short deals `nse_deals` (API, `csv=true`) | DEAL, Desk filter | evening | 20:30 | 2026-11-04 | 0 | T+0 by 21:00 | G |
| 6 | MTF financed positions `nse_mtf` (T−1 file) | MRGN | **22:12 for T−1 (measured)** | 20:30 (misses it) | 2026-11-02 | 2 (T+2) | T+1 by 23:00 | **A** (structural) |
| 7 | FII/DII cash `nse_fii_dii_cash` (API serves latest day only) | BRF, WRAP, MKT | same evening (provisional) | 20:30 | 2026-11-04 (30 rows = 15 of 18 days since 9 Oct) | 0 today; **3 days lost for good** | T+0 by 21:00, never lose a day | **A** (lossy) |
| 8 | Insider trades (PIT) `nse_insider_trades` (per stock, top-300) | INSD, H4b tracking | intimation ≈ T+2 days | **Sat 09:00 weekly** (14 min) | 2026-10-30 | up to 7 days | T+1 daily | **A** |
| 9 | Shareholding XBRL `nse_shareholding` | HDS | quarterly, ≤ 21 days | Sat 09:00 | 2026-10-27 | ok | 7 days after broadcast | G |
| 10 | Results release times `nse_results` | ERN, results-reacting, PEAD | filing timestamp (real time) | 20:45 (events of last 3 days) | **2026-10-30 20:49** | 3 sessions, in results season | T+0 by 21:30 | **R** (not in start-up catch-up; the live `results-reacting` panel still shows 3 Nov filings from the announcements feed) |
| 11 | Corporate calendar `nse_events` (results dates, board, actions) | EVTS, ERN | forward-looking | 18:30 EOD | through 2026-12-05 (776 upserted tonight) | 0 | daily | G |
| 12 | Index closes NIFTY 50 + INDIA VIX `market_index_daily` (`/api/derivatives/vix`) | DERV, MKT, RSK | 15:30 close | 18:30 EOD | 2026-11-04 | 0 | T+0 by 19:00 | G |
| 13 | Market monitor (breadth, regime, market map) | MKT, BRF, WRAP | derived | 18:30 EOD | as_of 2026-11-04 | 0 | T+0 by 19:00 | G |
| 14 | Index valuation history (P/E, P/B, DY) | MKT › valuation, BRF | NSE daily index file, evening | 19:15 | last run **30 Oct** (live panel reads NSE at 15:30) | 3 (recoverable: `--recent 10`) | T+0 by 20:00 | **A** |
| 15 | EOD option chain + IV (B-S on bhavcopy) `/api/market/option-chain/{sym}` | OMON, OSTR | from #3 | on request from cached file | 2026-11-04 (NIFTY ATM IV 13.9, PCR 1.07) | 0 | T+0 by 21:00 | G |
| 16 | **IV history** `option_history.json` — NIFTY, BANKNIFTY only: near-expiry ATM IV, PCR, max pain, daily since 2024-07-08 (578 rows) | DERV | from #3 | lazy background thread on request | 2026-11-04 (file 21:49) | 0 | T+0 by 21:00; **stock options + per-strike + intraday missing** | G for what exists; **R for the owner's goal** |
| 17 | Live option chain `option-chain-v3` (30-s TTL in session) | OMON | live | on request | live (verified 15:40:00 print) | — | snapshot 6×/day into a PIT table | **R** (never stored; trap 8) |
| 18 | Pre-open book `archive:preopen` | PRE | 09:00–09:08, kept until next session | 09:09:30 | 2026-11-04 (13 of 19 sessions since 9 Oct) | 0 | every session | A (lossy on outages) |
| 19 | Intraday breadth `archive:internals` | MOV, WRAP | live | every 2 min | **2026-10-30** (10 of 16 sessions since 13 Oct) | 3, unrecoverable | every session | **R** |
| 20 | NSE live quotes / movers / indices / GIFT / announcements (`nse_live` 30 s in session, 10 min outside) | MOV, WTCH, CF, BRF | live | on request | live (GIFT 22:17, announcements 22:08) | — | ≤ 60 s in session | G |
| 21 | Surveillance / price bands / F&O ban list | EQS, Desk filter | evening | on request, cached | surveillance 2026-11-04, ban for 2026-11-05 | 0 | T+0 | G |
| 22 | Breeze session (quotes, MCX, holdings, gold open capture) | BRKR, PORT, MCXG, GOLD | 08:00 login | `icici_session_refresh` | **live tonight only because the owner replied on Telegram** (`telegram_login rc=0` at 21:3x); scheduled job: 4 of 4 recent runs "needs you: no OTP received in time"; "Session key is expired" in data-service 25 Oct, 30 Oct, 4 Nov | — | logged in by 08:30 every trading day without a human | **A** |
| 23 | Breeze live ticks / tick store (`LIVE_TICKS`) | CHRT intraday, VWAP | live | websocket | **never armed** (`live_ticks.state=OFF`, `data/ticks` empty) | — | one live session | R (by decision) |
| 24 | ICICI security master `data/cache/breeze/SecurityMaster.zip` | MCXG, GOLD contracts | daily | 20-h cache on connect | 2026-11-04 21:28 | 0 | daily | G |
| 25 | News scanner `new_scnner/*.json` (54 files) | NEWS | owner-run | manual | 20261104 (21:43 tonight) | 0 | — | G |
| 26 | News scanner track record | NEWS | derived | 19:45 | generated 30 Oct, prices through 30 Oct | 3 | T+0 | A |
| 27 | Decision Desk mark / plans | DESK | derived | 19:30 | last_mark 2026-10-30; plan `2026-11-REB` PENDING (signal 30 Oct, risk-off → cash) | 3 | T+0 | **A** (orders will be EXPIRED on the next run, `decision_desk.py` 367–375) |
| 28 | S1 paper shadow `alpha_lab/paper/state.json` | ALFA, RSCH | derived | 19:50 | 2026-10-30 19:50 | 3 | T+0 | A |
| 29 | ML features / labels (`/db/ml-stats`) | MLEN, GBOX | derived | 18:30 EOD (last, non-fatal) | features 2026-11-04, labels 2026-10-28 (5-day forward, by design) | 0 | T+0 | G |
| 30 | DuckDB backup | — | — | 02:15 | 2026-11-04 21:38 (catch-up; from a private copy) | 0 | daily | G |
| 31 | Gold: Yahoo daily series / GC curve / 1-min bars (`gold_series`, `gold_daily_bars`, `gold_bars_intraday`) | GOLD, MCXG, WEI | continuous | 03:10, every 5 min | 2026-11-04; bars 22:00 IST | 0 | ≤ 10 min in session | G |
| 32 | Gold: CFTC COT `gold_cot` | GOLD › POSITIONING | Fri 15:30 ET for Tue | Sat 02:30 | 2026-10-27 (released 30 Oct; next 6 Nov) | 0 | Sat 07:00 | G |
| 33 | **Gold: CME daily OI / EFRP / product reference** (`gold_cme_daily_voi`, `gold_cme_efrp`) | GOLD › POSITIONING daily, CONTRACTS | daily | 15:45 / 21:30 / 03:10 | **0 rows ever** (`error_reply: 229 Extended Passive Mode Entered`, every run since 30 Oct; reproduced tonight) | ∞ | T+0 by 17:30 | **R** |
| 34 | **Gold: FRED daily (18 series: DFII5–30, DGS2/10, T10Y2Y, T10YIE, T5YIFR, VIXCLS, GVZCLS, EFFR, SOFR, DFEDTARU, Brent, HY OAS, RRP)** | GOLD › MACRO, HEALTH | ~07:00 next day | 03:10, 21:30 | **every series "The read operation timed out" on all 5 runs since 30 Oct**; both UAs time out at 25 s from this machine tonight | ≥ 5 d | T+1 by 08:00 | **R** (real yields survive via the Treasury CSV, 2026-11-03) |
| 35 | Gold: Treasury real/nominal curves | GOLD › MACRO | ~04:00 IST | 03:10 | 2026-11-03 | 0 | T+1 by 08:00 | G |
| 36 | Gold: GLD/IAU holdings `gold_etf_holdings` | GOLD › HEALTH, PHYSICAL | ~06:00 IST | 06:40 | 2026-10-30 | 3 | T+1 by 07:00 | A |
| 37 | Gold: SGE / SHFE `gold_asia_daily` | GOLD › PHYSICAL | 16:00 | 16:10 | 2026-10-30 | 3 | T+0 | A (not in catch-up) |
| 38 | Gold: Atlanta Fed path `gold_fed_path` | GOLD › MACRO | weekly | 06:40 | 2026-10-29 (`state: stale` on the page) | — | 7 d | A |
| 39 | Gold: MCX master / margins / price band (`master_published`) | GOLD, MCXG | 07:30 | 07:35 | 2026-11-04 | 0 | daily | G |
| 40 | Gold: IBJA AM/PM, RBI reference | GOLD › PHYSICAL | 13:30 / 18:00 | 13:45 / 18:10 | last run 30 Oct (jobs not in catch-up) | 3 | T+0 | A |
| 41 | Gold: health snapshot `gold_health_daily` | GOLD › HEALTH history | — | 08:40 | **1 row (30 Oct) in 7 trading days** | — | every trading day | R |
| 42 | Gold: brief docs `gold_brief_docs` | GOLD › brief | — | 09:05 | **2026-10-23** although the job ran 30 and 31 Oct "done" | 8 d | daily | R (silent rot) |
| 43 | Gold: `gold_preopen_log` DuckDB table | GOLD › accuracy | — | 08:45 | **0 rows** (the accuracy log is served from ui-api's own store: `/api/gold/log` has rows to 30 Oct) | — | — | A (schema promise unmet) |
| 44 | Gold: US calendar `gold_events` | GOLD › HEALTH/MACRO | — | hourly | through 2027-12-04 | 0 | daily | G |
| 45 | Not ingested: combined OI/MWPL (**19:23 measured**), clients ≥ 3 % MWPL (T+1), delta-equivalent OI, F&O volatility FOVOLT (**17:01 measured**), participant volumes, FII derivative stats, OI spurts, 52-week/P-E daily files | would feed OMON/DERV/EQS | evening | none | — | — | T+0 by 21:00 | gap |

Tally tonight: 22 green, 15 amber, 8 red. Had the owner not rebooted at 21:24, rows 1–5, 7, 11–13, 15, 18, 29, 31 would all read **30 Oct**.

## 4. Publication times measured tonight (HEAD on nsearchives, IST) — the schedule does not match them

| File | Last-Modified | Job that should get it | Verdict |
|---|---|---|---|
| `sec_bhavdata_full_04112026.csv` | **22:05:35** | 18:30 EOD | the stack stored a 4 Nov copy at 21:36, so NSE **re-published** it afterwards; revisions are never re-fetched |
| `BhavCopy_NSE_FO_0_0_0_20261104_F_0000.csv.zip` | 20:10:32 | 18:30 EOD (fails) → 20:30 | the 20:30 job is the real path; 18:30 wastes an attempt and logs a "missing" |
| `fao_participant_oi_04112026.csv` | 20:10:32 | 20:30 | ok, 20 min of margin |
| `combineoi_04112026.zip` | 19:23:04 | none | not ingested |
| `mrg_trading_031126.zip` (MTF for 3 Nov) | **22:12:02 on 4 Nov** | 20:30 (cannot) | effectively T+2 |
| `FOVOLT_04112026.csv` | 17:01:10 | none | not ingested; NSE's own daily volatility per underlying |

## 5. Access traps re-verified (one paced GET each; `probe_results_2026-11-04.json`)

| Trap (dictionary row) | Tonight | Status |
|---|---|---|
| `www.nseindia.com/api/quote-equity` blocked for scripts | 403 `AkamaiGHost` "Access Denied" | confirmed |
| `api/quote-derivative` returns 404 | 404 "Resource not found" | confirmed |
| old `api/option-chain-indices` | 404 | confirmed; `option-chain-v3` 200, 265 KB, 123 strikes, `records.timestamp 04-Nov-2026 15:40:00` |
| market-wide `api/corporates-pit?index=equities&from_date…` empty | 200 `{"acqNameList":[],"data":[]}` | confirmed (per-stock path is what the Saturday job uses) |
| `api/historical/bulk-deals` 70-row cap without `csv=true` | **503** (NSE's anti-bot page; the home page also 403'd the cookie-less client) | not re-verifiable tonight; the stack's deals path (`csv=true`, Referer) works: deals through 4 Nov |
| CME `ftp.cmegroup.com` (gold allowlist) | `error_reply 229 Extended Passive Mode Entered` from `ftplib` | **new trap**: the server answers PASV with an EPSV reply; stock `ftplib` raises. Fix: override `FTP.makepasv` (parse `229 (|||port|)`), or use `curl`/`lftp` |
| FRED keyless `fredgraph.csv` | ReadTimeout at 25 s with both the app UA and a browser UA | **new trap** tonight (memory note said plain UA answered in 0.3 s on 26 Oct): rate-limited or network; move to the keyed REST API |

## 6. What has silently rotted (job "done", data not moving)

1. CME daily VOI / EFRP / PRF: 0 rows since 26 Oct; every group ends `error` but the *job* ends `done` (one failing group never fails the group — by design) and the Telegram "told once a day" line is the only trace. The POSITIONING daily "what got closed" and CONTRACTS OI ladder therefore never had COMEX data.
2. FRED daily: 18 series × 5 runs × 20 s timeouts = 30 min of a blocked worker per day; `gold_series` for VIX/GVZ/HY-OAS/SOFR/Brent is as old as the 26 Oct backfill.
3. `gold_brief_docs` last 23 Oct with the 09:05 job reporting `done` on 30 and 31 Oct.
4. `gold_health_daily` 1 row; `gold_preopen_log` 0 rows (the page reads a different store, so nothing looks wrong).
5. FII/DII cash: 3 of 18 days lost since 9 Oct with no gap marker in the series.
6. Equity bhavcopy revisions: the 22:05 re-publication is invisible to a date-keyed cache.
7. `results_capture_daily` not in `_KEY_JOBS`: after a multi-day outage results-season release times are only partially recovered (3-day window).
8. Intraday archives (internals, pre-open) have no "session missing" rows: MOV/WRAP show the last day with data (`day: 2026-10-30` tonight), which is honest but unlabelled.

## 7. What already exists and is good (credit where due)

- Start-up catch-up with missed-run counts from the heartbeat (`downtime_missed`), data catch-up (bhavcopy, positions, events, full pipeline when the EOD was missed), freeze-window deferral, backup catch-up, gold `backfill_from`. Tonight it recovered three sessions unattended.
- `eod_steps.py`: isolated steps, ML build last and non-fatal, WARNING on soft failures (15 Oct incident fix).
- Bhavcopy date-mismatch guard (rejected the "1 Nov" file tonight).
- `_check_dataset_freshness` + `DATASET_MAX_AGE_DAYS` (NSE 5/6/14/120/21 days, gold per catalog) with a Telegram CRITICAL naming the dictionary to consult.
- The gold package's catalog (`/api/gold/catalog`: 211 rows with `publisher`, `freq`, `publish_time_ist`, `lag_note`, `max_age_days`, `ingest_job`, `verdict`) and per-panel `freshness()` → `live / delayed / stale / unavailable` with `age_s`. This is exactly the pattern the whole terminal needs.
- `/db/freshness` (bars vs features lag), `/db/stats` + WHSE page (per-ticker `sessions_behind`), `/db/quarantine`, `/db/archive-meta`, `/db/nse-positions-meta` — the raw material for a data-health page is already served.
- Watchdog, log rotation, hang diagnostics, heartbeat, evening snapshot, PAPER-only enforcement.

## 8. Proposed freshness SLOs (per dataset, IST, trading days)

| Class | Datasets | SLO (stored by) | Check cadence | Breach → |
|---|---|---|---|---|
| Live-session | NSE live quotes, indices, GIFT, announcements, Breeze quotes, gold 1-min bars | ≤ 60 s (NSE), ≤ 10 min (gold bars) during the session | every poll | header chip LINK DOWN / DELAYED (exists for some) |
| EOD-T0-early | Yahoo bars, equity bhavcopy, index closes, VIX, market monitor, surveillance, ML features | 19:00 | 19:05, 23:00, 08:35 | amber at 19:00, red at 21:00 + Telegram |
| EOD-T0-late | F&O bhavcopy, participant OI, combined OI, deals, FII/DII, results release times, index valuation, option IV history, Desk, shadow, wraps | 21:00 (FII/DII, results: 21:30) | 21:35, 23:00, 08:35 | amber 21:30, red 23:00 |
| T+1 | MTF (T−1 file at ~22:10), clients ≥ 3 % MWPL, insider PIT, gold ETF holdings, FRED/Treasury | 08:00 next day | 08:35 | amber 08:35, red 12:00 |
| Weekly/periodic | COT (Sat 07:00), shareholding (7 d after broadcast), Fed path (7 d), WGC/LBMA (per catalog) | per catalog | daily 08:35 | amber at +1 cadence, red at +2 |
| Session captures | pre-open book, internals, gold open capture, option-chain snapshots (new) | each session | 09:12 / 15:35 | red = unrecoverable gap, written as an explicit gap row |

Replace `DATASET_MAX_AGE_DAYS` (days) with `expected_by` (HH:MM, trading-day aware via `/db/market-holidays`) and
`unrecoverable: bool`; run the check from the controller hourly, and surface it in the terminal, not only on Telegram.

## 9. Gaps and recommendations (ranked; cost S < 1 day, M 1–3 days, L a week+)

| # | Recommendation | Why (evidence) | Cost | Depends on |
|---|---|---|---|---|
| 1 | **Make the Mac an appliance**: set `HEALTHCHECK_PING_URL` (healthchecks.io, Telegram integration), `sudo pmset -a autorestart 1`, disable FileVault's pre-login pause or enable auto-login for the service account, UPS. Add a second heartbeat from the *watchdog* (it survives a controller crash but not a power-off; only the off-machine check survives that). | 106 h and 43 h silent outages; 55 % session availability; RUNBOOK already documents every step | S (owner) | — |
| 2 | **DATA health page (GO `DATA`) + `GET /api/data/health`**: one row per dataset in §3 with publisher, published-at, expected-by, stored as-of, lag in sessions, RAG, last job result, next run, "catch-up scheduled at", unrecoverable-gap count; a header-strip chip "DATA 2 STALE"; the GOLD `SourceChip` (LIVE/DELAYED/STALE/OFFLINE + as-of) on every panel of every page. Bloomberg equivalents: the as-of stamp on every screen and `WECO`-style timestamps; Refinitiv Workspace's "Data Quality" status. | §3: nothing outside GOLD shows lag; `_check_dataset_freshness` is Telegram-only and 5-day loose | M | the catalog pattern in `routers/gold.py` and `catalog_seed.py` generalised to a `dataset_catalog` table |
| 3 | **Reschedule to the measured clock**: drop the F&O attempt from 18:30 (or make 18:30 equity-only), keep 20:30, add a **22:45 pass** (MTF T−1 at 22:12, bhavcopy re-publication at 22:05 via `If-Modified-Since`/ETag with a versioned row, FII/DII second attempt, results capture) and an **08:35 sweep** (anything still missing from last night, with `backfill_from`). Persist `fetched_at`, `last_modified`, `sha256` per file in an `ingest_log` table (the gold `first_seen_at` idea for NSE). | §4 Last-Modified times; MTF T+2; FII/DII lost days; cached-forever first copy | S | — |
| 4 | **Fix CME FTP** (`makepasv` override for the `229` reply, or shell out to `curl --ftp-pasv`) and **FRED → keyed REST** (`FRED_API_KEY` is already supported in `commodity.py`; 8-s timeout, per-series circuit breaker, stop after 3 consecutive timeouts in a run). | §5/§6: 0 CME rows ever; 378 s/run of FRED timeouts | S | owner gets a free FRED key |
| 5 | **Options data for a day-to-day IV trader** (data side only; R-OPTIONS owns the analytics): (a) snapshot `option-chain-v3` for NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY and all F&O stocks at 09:20, 10:30, 12:00, 13:30, 15:00, 15:25 into a PIT table `nse_option_chain_snap` (strike, CE/PE LTP, IV, OI, ΔOI, volume, bid/ask, `nse_ts`, `fetched_at`) — ~230 underlyings × 6 = 1,400 paced calls/day inside the existing 30-s cache; (b) build `nse_option_iv_daily` (per underlying × expiry × strike IV, ATM IV, 25Δ skew, term structure) from the 1,720 cached F&O files 2019-10→ in one offline pass and then nightly; (c) when a Breeze session is live, `get_option_chain_quotes` every 5 min for the watchlist (IV/greeks from ICICI's feed) — Breeze also serves historical 1-min option bars (`get_historical_data_v2`, from 2022) for a one-off backfill, to be verified by R-OPTIONS. Reference products: Sensibull/Opstra "IV chart", Quantsapp "IV percentile", thinkorswim IV Rank, Bloomberg `OVDV`/`OMON`. | §3 rows 16–17: only NIFTY/BANKNIFTY ATM IV daily since Jul 2024; the live chain is discarded | M | Breeze session reliability (#7) |
| 6 | **Ingest the verified-but-missing NSE evening files** with the existing `ingest_daily` pattern: combined OI/MWPL (19:23), delta-equivalent OI, clients ≥ 3 % MWPL (T+1), FOVOLT (17:01), participant volumes, FII derivative stats; move insider PIT from weekly to nightly for the F&O universe. | §3 row 45; dictionary verified them live; crowding/ban-approach is an options-trader staple | S each | — |
| 7 | **Breeze login without a human**: store the TOTP secret in the Keychain (owner action O-4, the `BRKR` panel already supports it); then the 08:00 job stops ending in "needs you". Add an 08:25 verification that quotes actually flow and a 09:20 re-check. | row 22: 4 of 4 scheduled logins "needs you"; session expired on three days | S (owner) | — |
| 8 | **Extend start-up catch-up** to every replayable daily job: `results_capture_daily` (with `recent_events_days = days down + 3`), `index_valuation_daily`, `desk_daily`/`alpha_shadow_daily` (replay-safe already — run them at start-up instead of waiting for 19:30/19:50), `gold_asia_close`, `gold_morning`, `gold_india_*`, `gold_health_snapshot` (back-dated rows marked `backfilled=true`). | §3 rows 10, 14, 26–28, 36–41 stale tonight despite the catch-up | S | — |
| 9 | **Explicit gap rows** for session-bound captures (pre-open, internals, FII/DII, gold open): write `{date, dataset, reason: "stack down"}` so MOV/WRAP/BRF say "no intraday data for 2–4 Nov" instead of showing 30 Oct. | §6.8 | S | #2 |
| 10 | **Satellite collector** (optional, L): the light pollers (pre-open 09:09, internals 2-min, FII/DII 20:30, option-chain snapshots) on an always-on ₹730/mo Mumbai VM writing to object storage; the Mac ingests on return. Removes the "Mac off = history lost" class entirely. The memory note `cloud_hosting_costs` already prices it. | §2, §3 rows 7, 18, 19 | L | owner decision |
| 11 | **Point-in-time storage for NSE tables** as the gold schema does (`report_date`, `release_at`, `first_seen_at`, revisions as new rows), starting with bhavcopy (re-publications), deals (late additions), results (`exchdisstime`). | PLAN §0.1 principle 4; §4 bhavcopy 22:05 | M | #3 ingest_log |
| 12 | **Arm `LIVE_TICKS=1` for one supervised session** so the tick store and VWAP/bars endpoints are validated before any intraday feature depends on them. | row 23 | S (owner) | #7 |

## 10. Data-health page — minimum spec

- Backend `GET /api/data/health` (ui-api, served from a 60-s SWR cache): `{as_of, rows:[{id, label, pages[], publisher, published_ist, expected_by, as_of, lag_sessions, state: live|fresh|amber|red|gap, unrecoverable, job_id, last_run{ts,status,ms}, next_run, catchup_at, note, dictionary_anchor}], summary{green,amber,red,gaps}}`. Inputs already exist: `/db/nse-positions-meta`, `/db/archive-meta`, `/db/freshness`, `/db/stats`, `/db/market-holidays`, `/api/telemetry/status` (scheduler), `/api/gold/catalog` + the gold `freshness()` helper, `data/.scheduler_history.json`.
- Catalog: one `dataset_catalog` seed (YAML or the gold `catalog_seed.py` style) carrying the §3 rows; `scripts/tests` assert every ingest job and every page's data source appears in it (the gold "no catalog row, no panel" rule, applied terminal-wide).
- UI: terminal kit `DataTable` with RAG `Chip`s, sort by lag, filter by page; header-strip chip; honest wording ("stored 30 Oct · expected by 21:00 · 3 sessions behind · catch-up 19:30 tomorrow"); no composite score.
- Alerting: the controller's hourly check reads the same endpoint; one Telegram line per *transition* (green→amber→red), a daily 08:35 digest, and the dead-man ping as the only alert that works when the Mac is off.

## 11. Ratings (data-update side)

| Area | Score | Evidence |
|---|---|---|
| Coverage of free sources | 7 | 12 of the 68 verified NSE datasets ingested; MWPL, FOVOLT, ≥ 3 % clients, delta-eq OI, FII derivative stats absent (§3 row 45) |
| Timeliness vs publication | 6 | EOD sets by 20:30 same day when the Mac is on; MTF T+2 (22:12 file); insider weekly; FII/DII lossy (§4, §3) |
| Resilience / catch-up | 5 | excellent catch-up logic (3 sessions in 7 min) on a platform that was off for 55 % of market hours in 14 days (§2) |
| Observability of freshness | 4 | GOLD has chips + catalog; everything else has a Telegram-only 5-day check; SYS = jobs, WHSE = Yahoo bars; no dataset-lag page (§7, §8) |
| Options / intraday data | 3 | ATM IV history for 2 indices since Jul 2024; live chain discarded; ticks never armed; Breeze login needs a human (§3 rows 16–17, 22–23) |
| Gold feeds | 5 | Yahoo/COT/Treasury/MCX current; CME 0 rows ever; FRED dead; Asia/ETF/health/brief stale (§3 rows 31–44) |
| Point-in-time discipline | 6 | gold PIT columns; NSE tables date-keyed without `fetched_at`; bhavcopy revisions invisible (§4) |
| **Overall** | **5** | |

## 12. Open questions for the owner

1. Why was the Mac off from 31 Oct 11:29 to 4 Nov 21:24 (deliberate shutdown, power cut, freeze)? The answer decides between a UPS/autorestart fix and a satellite collector.
2. Will you set the healthchecks.io dead-man ping and `pmset autorestart` this week (RUNBOOK §"Off-machine dead-man ping", §"Unattended reboots")?
3. O-4: store the ICICI TOTP secret in the Keychain so the 08:00 login stops depending on an SMS reply?
4. A free FRED API key (fixes 18 dead macro series and 30 min/day of timeouts)?
5. Is the Desk's expiry of the PENDING November rebalance plan (risk-off, all cash) acceptable, or should missed-session plans execute at the next open after recovery?
6. `LIVE_TICKS=1` for one supervised session?
7. Do you want intraday option-chain snapshots (≈ 1,400 paced NSE calls/day) and the per-strike IV history built from the cached F&O files? This is the data prerequisite for the IV analysis you asked for.
8. O-8 (MCX bhavcopy / Breeze daily collectors) remains open; it is the only path to MCX gold OI history.
