# SuryaDhana AI — CLAUDE.md

## Project

Quantitative trading terminal + research stack for NSE Indian stocks.
- **Live posture**: PAPER ONLY — Decision Desk (monthly momentum, owner-approved) + S1 shadow (alpha_lab, from 15 Oct 2026); no live orders
- **Terminal**: Bloomberg-style UI on http://127.0.0.1:8010, a static release served by ui-api (ui/dist/current, `./start-local.sh build-ui`) and wrapped by the SuryaDhana.app desktop shell (43 pages via GO bar; incl. CHRT charts, DERV, OSTR, MCXG gold desk, GOLD gold terminal, RSK risk) backed by ui-api + data-service; Telegram bot for phone control
- **Data**: survivorship-free NSE bhavcopy panel 2010→ in DuckDB (4.4 GB, git-ignored — see docs/RUNBOOK_RESTORE.md) + ICICI Breeze live
- **Legacy**: the 5-day XGBoost→RL pipeline is dormant (autopilot OFF; kept for reference)

## Python Environment

Always use:
```bash
/Users/sudheer/Desktop/jupyter_env/bin/python
/Users/sudheer/Desktop/jupyter_env/bin/pip install <package>
```

Never use system Python, pyenv, or conda.

## Architecture — what actually runs

Local stack (the real spine, 3 processes, all on 127.0.0.1 only — see reports/production_review/architecture_reality.md and reports/desktop_app/PLAN.md):

| Process | Port | Role |
|---|---|---|
| data-service | 8001 | DuckDB owner, NSE live/EOD ingest, panels, Breeze live ticks |
| ui-api | 8010 | the terminal's single backend; proxies data-service; alerts, desk, research |
| master-controller | 8008 | IST job scheduler, Telegram bot, telemetry |
| (optional) Next dev server | 3000 | dev UI with hot reload, and the one-time settings migration (docs/RUNBOOK_RESTORE.md §8); not the terminal |

Dormant legacy (code + tests kept, not running; autopilot OFF — do not plan against these):
api-gateway :8000 · feature :8002 · ml :8003 · rl :8004 · risk :8005 · execution :8006 · monitoring :8007
(the 5-day ML pipeline era; Breeze execution lives in ui-api/positions + scripts/live_execution today).

## Key Files

- `shared/models/` — Pydantic v2 schemas (Stock, OHLCV, Signal, Order, Portfolio)
- `shared/config.py` — All config via Pydantic Settings (reads `.env`)
- `shared/logging.py` — Structured JSON logging with correlation IDs
- `shared/trading_costs.py` — Real NSE cost + tax model (broker profile via `COST_PROFILE`, overrides `COST_*`). Use it for every backtest/order; ICICI delivery round trip ≈ 0.93% + ₹24 DP on the default MoneySaver plan (0.29%), not 0.15%
- `docs/PRODUCT_STRATEGY.md` — product plan (sleeves, Decision Desk, promotion gates, phases A–E)
- `docs/NSE_DATA_DICTIONARY.md` — every free NSE dataset (verified live), exact files/APIs, publication timing, access traps, swing-research playbook; probe: `scripts/nse_free_data_catalog.py`
- `shared/xs_labels.py` + `shared/xs_features.py` — v3 ML labels (20-session next-open excess vs the universe, ranked per date) and point-in-time features on the NSE panel. The production `ml_labels` (v2: 5-day close > 0.15%, ±2% barrier) failed the comparison; evidence `reports/ml_labels/FINDINGS.md` (`scripts/ml_label_study.py`)
- DuckDB `nse_bhavcopy` — NSE full bhavcopy (all securities incl. delisted, raw prices, delivery %); `POST /jobs/ingest-bhavcopy`, also run by the EOD daily pipeline
- `docs/IMPROVEMENT_LOG.md` — terminal sprint (11 Oct 2026): BRIEF/WATCH/MKT/EVTS/RSCH/COMP pages, GO command bar, stock Profile (DES + ERN + trade ticket); read it before UI work
- `services/data-service/market_monitor.py` (breadth, regime, market map, industry rotation), `nse_events.py` (`nse_events`: NSE calendar, ex-dates), `security.py` (stock profile), `results_history.py` (`nse_results`: results release times and reactions)
- `services/ui-api/routers/research.py` — curated verdict per study (RSCH tab); add a CATALOG row for every new report
- `data/FINAL_100_STOCKS.csv` — Locked stock universe (100 NSE stocks)
- `data/market.duckdb` — Central time-series database
- **Desktop app (25 Oct 2026)**: `desktop/` (Tauri v2 shell `SuryaDhana.app`, Rust in `desktop/src-tauri/src/`, boot page
  `desktop/boot/`), `services/ui-api/static_ui.py` (serves the static UI release `ui/dist/current`), `ui/lib/platform/` (shell
  bridge), `ui/lib/prefs/` + `services/ui-api/routers/prefs.py` (settings sync, `data/ui_prefs.sqlite`), `ui/components/desktop/`
  (title strip, boot gate, banners), `shared/http_guard.py` (Host/Origin guard on all 3 services). Spec + contract:
  `reports/desktop_app/PLAN.md`; final report `reports/desktop_app/FINAL_REPORT.md`; reviews `reports/desktop_app/review/`
- **GOLD program (26 Oct 2026)**: the 43rd page `GOLD` (`ui/components/gold/`: `GoldPage.tsx`, one file per sub-view
  HEALTH / DAILY / WEEKLY / MONTHLY / POSITIONING / PHYSICAL / MACRO / CONTRACTS / LEARN; the pre-open desk lives here now),
  `services/ui-api/routers/gold.py` (`/api/gold/*`) + the `/api/positions/totp/*` section at the end of `routers/positions.py`
  (the BRKR auto-login panel; the secret lives in the Keychain and is never echoed), `services/data-service/gold/`
  (`schema.py`: 21 point-in-time `gold_*` tables in market.duckdb — PLAN §c.1's 20 plus `gold_ingest_state` — and the
  `gold_cot_metrics` view; `catalog_seed.py`: the `gold_series_catalog` that gates rendering — no verdict row, no panel;
  `ingest_{cot,cme,macro,yahoo,india,physical,local}.py`, `derive.py`, `jobs.py`, `reads.py`, `api.py` mounted by
  data-service `main.py`; `hosts.py` allowlist), `GOLD_JOBS` in `scripts/master_controller.py`. Contract + plan: `reports/gold_program/PLAN.md`; source
  verdicts: `reports/gold_program/SOURCES.md` (140 entries) rendered as `docs/GOLD_DATA_DICTIONARY.md` by
  `scripts/gold_data_dictionary.py` (generated — never edit by hand; `--check` runs in `scripts/tests`); study verdicts:
  `reports/gold_program/FINDINGS.md` (every positioning / flow / macro / seasonal series FAILS as a forecast, PASSES as a
  description); owner's guide: `reports/gold_program/OWNER_GUIDE.md`; LEARN content: `reports/gold_program/G-EDU/`
  (`parts/*.md` → `CURRICULUM.md`, `glossary.json`, `tooltips.json`; `validate_learn.py --write` rebuilds and checks, incl.
  §8.4 against `HEALTH_RULES` in `routers/gold.py` and every field tooltip against the `ui/` source).
  Labelling rules (PLAN §f, binding): badges `signal` (none exists) / `context` / `arithmetic` / `heuristic`; no composite
  score; context metrics never coloured bullish/bearish; the health verdict ends "describes, does not predict"; the same
  number appears once per page; **nothing gold feeds the Decision Desk, the S1 shadow, directional alerts or the paper
  ticket's price**. Duty is a dated constant (15 % since 2026-05-13, `GOLD_IMPORT_DUTY_PCT`; owner confirms at CBIC).
  **MCX settlement (wave 1d, 5 Nov)**: the ICICI master's price band is one session stale, so the settlement of record is
  the last-30-minute VWAP of Breeze 1-minute bars (MCX's DSP method): `gold/mcx_close.py`, job `gold_mcx_close` 23:58
  Mon–Fri (the ICICI session dies at midnight IST, so a run after midnight finds no session), `/db/gold/mcx/settlement`;
  ui-api computes it when the store has none; fields `settlement_source` / `_session` / `_quality`. Purity: basis =
  price ÷ (landed × purity/1000), GOLD / GOLDM 995, GOLDTEN / PETAL / GUINEA 999. **Special sessions (wave 1e, 6 Nov)**:
  `shared/mcx_specs.SPECIAL_SESSIONS_2026` (Muhurat Sun 8 Nov 14:20–15:30, pre-open 14:05–14:19) counted by every session
  helper, so Monday's fair-open baseline uses Sunday's VWAP (flagged when it has to fall back). HEALTH's India basis is
  contract-aware and labels its clock (`/api/gold/health?contract=&expiry=` == `/overview`'s health); one real yield per
  page (the fresher twin); the Shanghai premium is recomputed from its printed legs. Build records `reports/gold_program/build/`.
- **Terminal v2, wave 1 (5 Nov 2026; DEPLOYED 5 Nov 13:01, IV / VIX / drivers history backfilled to 2019)**: plan `reports/terminal_v2/PLAN.md` (binding §0, ownership §1), `RATING.md`,
  research `R-*/REPORT.md`, `API_CONTRACT.md`. data-service packages, each a `schema.py` (DDL) + `api.py` router mounted by
  `main.py`: `fo_iv/` (Black-76 on the put-call-parity forward, `model_version` `b76-pcp-v1`; tables `iv_surface_daily`,
  `iv_expiry_daily`, `iv_summary_daily`, `iv_event_log`, `iv_intraday`, `vix_daily`, `index_ohlc_daily`, `rate_curve` (a dated
  6.5 %), `nse_fo_volt`, `nse_contract_delta`, `nse_combined_oi`; `POST /jobs/iv-eod?job=iv_eod|iv_weekly|iv_backfill|vix_backfill`,
  `POST /jobs/iv-intraday`, `POST /jobs/ingest-nse-files`; reads `/db/fo-iv/*`, `/db/vix-daily`, `/db/index-ohlc/{symbol}`),
  `index_drivers/` (`index_constituents_daily`, `index_weights_daily`, `index_contribution_daily`, `index_contribution_fit`,
  `index_driver_state`; `POST /jobs/index-drivers`, `/db/index-drivers*`), `data_health/` (`dataset_catalog`, whose seed
  `catalog.py` gates rendering — no row, no panel; `ingest_log` with url / Last-Modified / sha256 / revision; `data_gaps`;
  `terminal_ingest_state`; `POST /jobs/data-health`, `/db/data-health*`); `nse_positions.py` file ingests (`nse_participant_vol`,
  `nse_fii_stats`, `nse_mwpl_clients`, the FOVOLT / Contract_Delta / combined-OI / `ind_close_all` files, the bhavcopy
  `If-Modified-Since` revision pass) and PIT columns (`first_seen_at`, `release_at` on `nse_bhavcopy`; `first_seen_at` on
  `nse_deals` / `nse_results`). ui-api: `routers/derivatives.py` (`/api/derivatives/iv/{symbol}` + `/surface` `/cone`
  `/events` `/intraday`, `/vol-screen`), `routers/markets.py` (`/api/market/index-drivers` + `/timeline` `/monthly`,
  `/api/desk/attribution`), `routers/options_strategy.py` (`POST /api/options/margin`: Breeze → NSE SPAN file → the 12 %
  heuristic with its measured 4.8× error), `routers/data_health.py` (`GET /api/data/health`). shared: `http_client.py`
  (host allowlist; `PacedClient` ≥ 1.2 s per host, 20 s, NSE 403/429 → 600 s breaker; one `AsyncClient` per process with a
  breaker and stale-serve), `breeze_budget.py` (the one Breeze ledger, SQLite `data/breeze_budget.sqlite`, default cap
  60/min · 4,000/day under the documented 100 · 5,000; `BREEZE_BUDGET_*`), `metrics.py` (see Development Workflow);
  `storage/duckdb_store.py` readers-writer lock (`read()` / `reader()` shared, `write()` / `writer()` exclusive; never use
  `store._conn`). UI (B4, in progress): `ui/components/vol/`, `ui/components/drivers/`, `ui/lib/activeSymbol.ts`. Docs:
  `docs/TERMINAL_DATA_DICTIONARY.md` generated from `dataset_catalog` by `scripts/terminal_data_dictionary.py` (never edit
  by hand; `--check` runs in `scripts/tests`); LEARN `reports/terminal_v2/LEARN/` (`build_assets.py` → `glossary.json`,
  `tooltips.json`; `validate_learn.py --write` rebuilds and checks: ≤ 200 chars a line, no direction words, every tooltip
  key a real column or payload field; a copy bundled under `ui/` must match). Hardening: Redis bound to 127.0.0.1 with an
  optional password (`REDIS_PASSWORD` or the Keychain item `suryadhana-redis`), secrets are `SecretStr` in
  `shared/config.py`, `scripts/db_backup.py --offsite` (sha256-verified copy to `OFFSITE_BACKUP_DIR`; the 02:15 job does
  not pass it yet). GOLD's labelling rules apply: no `signal` badge exists in F&O or index attribution; nothing here feeds
  the Decision Desk, the S1 shadow, a directional alert or a ticket price. NSE's `Last-Modified` header is GMT (add 5:30).
- **Terminal v2, wave 2 + the 5 Nov review fixes (6 Nov 2026, commit `0b27dcc`, DEPLOYED 6 Nov 15:36)**: build record
  `reports/terminal_v2/build/wave2_and_fixes.md` (two rounds, each builder adversarially re-checked). **Paper F&O book**
  (PAPER ONLY, no order path): ui-api `routers/fo_book.py` (`/api/options/book`, `/greeks`, `/marks`, `/close`, `/roll`,
  `/journal`) + `fo_book_store.py` (SQLite `data/paper_fo.sqlite`, `PAPER_FO_DB`); expired legs settle at the stored
  expiry-day mark (point-in-time); RSK › F&O is `/api/risk/fo` (net Greeks, delta-gamma VaR, SPAN utilisation, shocks);
  OSTR v2 in `routers/options_strategy.py` + `ui/components/fobook/`. **Typed alerts**: `alert_engine.py` +
  `routers/alerts.py` (`/api/alerts/series` lists the kinds; rules, fires, feed; SQLite `data/alerts.sqlite`, the legacy
  `data/price_alerts.json` is imported and kept current; backed up nightly by `db_backup.py`); the controller evaluates
  them after each EOD step (`_alerts_after_soon`) and sends Telegram lines; no alert kind carries a direction word.
  **Tape + expiry day**: `iv_intraday` every 2 min 09:15–15:30 through the Breeze budget (tiers: NIFTY / BANKNIFTY /
  FINNIFTY near + next, watch names at 15 min); `routers/expiry.py` (`/api/derivatives/iv/{s}/oi-tape`,
  `/api/derivatives/expiry-day`), UI `ui/components/expiry/` (DERV › XPRY; OMON LIVE tape); `POST :8001/jobs/expiry-replay`.
  **One time convention**: T = calendar time to 15:30 IST on the expiry day ÷ 365 (`fo_iv/black76.TIME_CONVENTION`
  `cal365-1530`, no half day) in the store, the chain, OVME, OSTR and the book. IV − RV20 is close-to-close and says so
  (Parkinson and Yang-Zhang shown beside it); range-outlier sessions leave Parkinson / YZ only; `POST /jobs/iv-eod?job=iv_repair`
  re-derives RV / IV30 fill / ranks from stored rows. Results filing times live in `nse_results.filed_at` (+ `filed_source`),
  read by EVTS as `COALESCE(filed_at, released_at)`; **`released_at` is unchanged and is what the S1 shadow reads** (adopting
  filed_at there is an owner review item). FII/DII sums say "n of m sessions" (`POST :8001/jobs/fii-dii-backfill`);
  `scripts/daily_wrap.py --backfill-missing --since <d>` (one date per wrap). GO arguments are read by the target page
  (`TCS OMON 27NOV`, `NIFTY OSTR IC`, `ALRT TCS >3200`, `GO IMPORT` for the one-time settings import).

## Data Sources

- **Historical**: yfinance (5 years of NSE OHLCV data, free)
- **Live/Execution**: ICICI Direct Breeze API (requires credentials in `.env`)
- **Gold**: CFTC COT (Socrata), CME **FTP** only (never `www.cmegroup.com`), FRED keyless CSV + US Treasury, Yahoo through the
  one cached fetcher, GLD / WGC / IBJA / SGE displayed with attribution and never re-served (owner decision O-1), IMF, RBI,
  AMFI, the ICICI security master; Kitco / LBMA price pages / MCX site are links only. Verdict per source:
  `reports/gold_program/SOURCES.md`; allowed hosts: PLAN §c.6, enforced by `tests/gold/test_hosts_allowlist.py` (data-service)
  and `tests/integration/test_gold_gates.py` T8 (ui-api)

## Trading Rules (DO NOT CHANGE without review)

### Monthly momentum allocator: the Decision Desk (owner-approved 2026-09-27, PAPER mode)
Code: `shared/momentum.py` (`StrategyConfig` defaults = these rules), `shared/decision_desk.py`. Evidence: `reports/phase_b/`, `reports/phase_b_extended/`.
- Monthly rebalance: signal at the last close of the month, execution at the next session's open
- NSE momentum score (6m & 12m return ÷ 1-yr volatility) within the 300 most liquid EQ stocks (≥ ₹20, no ETFs)
- Up to **20 positions**, equal weight; holdings kept while rank ≤ 30 (buffer 1.5×)
- Max 15% of portfolio per stock · max 40% of positions per NSE industry
- Crash filter: NIFTY below its 200-day average → everything in the liquid fund; volatility target 15%
- **Equity share 66%** of capital (Option B, historical worst drawdown ≈ −22%); rest in a liquid fund (`DESK_EQUITY_SHARE`)
- **No per-trade ATR stop and no 5-day time stop** (they would sell winners on normal dips); exits come from the monthly ranking and the crash filter
- Max drawdown −20% from peak → sell everything at the next open; manual re-enable (HARD)
- Real costs from `shared/trading_costs.py` (ICICI MoneySaver default)
- Candidate filter, **OFF until the owner reviews it**: `avoid_bulk_buy_days=20` (no new entries after a non-institutional bulk-deal net buy in the last 20 sessions; `DESK_AVOID_BULK_BUY_DAYS`). Evidence: `reports/desk_filter/REPORT.md`, `reports/held_overnight/FINDINGS.md`

### Legacy 5-day system (kept for reference; autopilot OFF: loses ~45–50%/yr to costs, see docs/PRODUCT_STRATEGY.md)
- Max 5 simultaneous positions
- Max 15% of portfolio per stock
- Max 40% of portfolio per sector
- Per-trade stop-loss: **k·ATR volatility-adaptive** (k=2.0 default), optional minimum-width floor (`stop_floor_pct`, default off). _Approved review change (audit §3.4): relaxed from the old fixed -2% cap so high-ATR storm names get a wider stop (≈6.5% on the median name) instead of being knocked out on noise. Applies to the per-trade stop only._
- Time-stop: exit after 5 trading days
- Daily loss limit: -2% → halt trading for the day (HARD — unchanged)
- Max drawdown: -20% → emergency stop (HARD — unchanged)

## Anti-Patterns (Critical)

- **NEVER** use future data in feature calculation (look-ahead bias)
- **NEVER** shuffle time-series data before train/test split
- **NEVER** hardcode API keys, secrets, or credentials
- **NEVER** skip walk-forward validation for backtests
- **NEVER** account for < 0.15% total transaction costs per trade
- **NEVER** commit `data/` (market.duckdb, backups, archives, ticks, SQLite stores), logs, screenshots, `.env` or any
  credential, token, account number or holdings: `origin` (github.com/sudheerptl01-hash/SuryaDhana_AI) is a **PUBLIC**
  repository since 5 Nov 2026. `.gitignore` covers `data/`, `*.log`, `.logs/`, `reports/**/*.png|jpg|webp`, `.env`;
  never `git add -f` past it, and never paste PORT / BRKR / RSK / DESK output into a committed file. Every push follows a
  secret scan of the staged diff (keys, tokens, session ids, account numbers; `git ls-files data` empty), run by the
  PM / owner; workflow builders never run git commit / push / reset / checkout
- **NEVER** add a Yahoo Finance caller (`query1`/`query2.finance.yahoo.com`, a new `yfinance` poller): gold goes through the
  app's single fetcher (`gold_preopen._yahoo_bars_cached`) or data-service's gold jobs, which own the budget (≤ 6 chart
  calls/min app-wide, app UA, `period1/period2` never `range=max`). The existing NSE-history scripts (`yfinance`, see Data
  Sources) stay, but never run them beside the 03:10 gold pull or the 08:45 snapshot: extra callers get the machine
  throttled (a 429 on 26 Oct 2026 took the 08:45 gold snapshot down). Gold studies and tests read the stored tables or the
  saved fixtures under `reports/gold_program/G-*/`

## Running Services

```bash
# Local stack (canonical): start / stop / restart / status per service, or all
./start-local.sh start            # data-service, ui-api (serves the terminal UI), master-controller
./start-local.sh status
./start-local.sh build-ui         # build + atomically publish a new terminal UI release (--rollback, --list)
scripts/build_desktop.sh --install # build, sign (ad-hoc) and install SuryaDhana.app (--rollback restores the previous app)
./start-local.sh start frontend   # optional Next dev UI on 127.0.0.1:3000 (hot reload); not part of the core

# Docker (legacy full 8-service stack; local work uses start-local.sh)
docker compose -f infra/docker-compose.yml up
```

**Self-healing (19 Oct 2026):** LaunchAgents start the core stack at login and restart crashed services
(`scripts/stack_watchdog.sh`, `scripts/install_launch_agents.sh install|status|uninstall`) and keep the Mac awake.
`./start-local.sh stop <svc>` marks the service paused (watchdog leaves it alone) until `start`; plain `start`
launches only the 3 core services (`start legacy` for ml/feature/rl); ui-api hot reload is opt-in
(`UI_API_RELOAD=1`). After downtime the controller reports missed runs and catches data up itself.
The watchdog also restarts a **hung** core service (listening but `/health` failing 2 runs in a row, about 3.5–5.5 min
after it hangs; diagnostics in `.logs/hangs/`; never data-service/master-controller inside a freeze window; a busy one
above 50 % CPU gets about 16 min; master-controller waits at most 10 min for a running ICICI login; at most 3 hang
restarts per service per hour, then it only alerts). ui-api logs a `loop_stall` WARNING with every thread's stack if
its event loop stalls ≥ 5 s. `kill -USR1 <pid>` writes every thread's stack to the service's log, but ONLY for a process
whose log announced `"stack_dump_signal": "SIGUSR1"` since its last start (ui-api; data-service and master-controller
once restarted on the 25 Oct round-3 code; never the `UI_API_RELOAD=1` supervisor): without that handler USR1 kills it.
**SuryaDhana.app** starts at login (`~/Library/LaunchAgents/SuryaDhana.plist`); launchd relaunches the copy it started after a crash, never after Quit. A copy reopened by hand after ⌘Q runs a crash guard (`suryadhana-crash-guard` in `ps`; app builds from 25 Oct round 3) that has launchd start it again after an unclean end; an older build is not relaunched until the next login. The menu-bar item and the `./start-local.sh status` desktop-app row say which applies (RUNBOOK §5).
**PAPER ONLY is enforced in code**: ui-api refuses LIVE execution unless `EXECUTION_LIVE_ALLOWED=1` (never set it casually).
Outage recipe: docs/RUNBOOK_RESTORE.md → "After an outage".
**Terminal v2 jobs (live since 5 Nov 2026; wave 2 adds the 2-minute OI / IV tape and the alert dispatch, live 6 Nov):** the 18:30 pipeline is equity-only (`skip_steps: ["nse_positions"]`); the 20:30
`nse_positions_catchup` is the evening pass (positions → FII/DII → the NSE evening files via `/jobs/ingest-nse-files` →
the 20:35 `index_drivers_daily` retry when the top-10 file was missing → `iv_eod` LAST, `/jobs/iv-eod?job=iv_eod`);
19:25 `index_drivers_daily`; 22:45 `nse_evening_pass` (MTF T−1, the 22:05 bhavcopy re-publication as a revision row,
FII/DII 2nd attempt, results, `iv_eod` retry; a miss of its 21:30 SLO is one Telegram info line); 08:35 `morning_sweep`
(amber/red rows of `/api/data/health` re-run as ≤ 6 light NSE fetches, then the DATA digest); `iv_intraday` every 15 min
09:20–15:30 on trading days (skipped without a live Breeze session or when the budget ledger refuses; quiet); Sat 03:00
`iv_weekly`; hourly `data_health_check` (one Telegram line per state transition, state in `data/.data_health_state.json`).
`DATASET_MAX_AGE_DAYS` is retired: freshness = the catalog's `expected_by` + `max_age` sessions as classified by
`/api/data/health` (red → critical). After downtime the start-up catch-up also re-runs results (window = days down + 3),
index valuation, the IV store and drivers with `backfill_from`, writes the gap rows (`/jobs/data-health`), the Desk mark
and the S1 shadow, and the gold key jobs incl. Asia-close / morning / India / health. `TERMINAL_JOBS_ENABLED=0` opts out;
a 404 from data-service (packages not deployed) pauses these jobs an hour. The watchdog's second heartbeat:
`HEALTHCHECK_WATCHDOG_URL` (optional).
**Gold jobs (26 Oct 2026):** `GOLD_JOBS` in `scripts/master_controller.py` (03:10 overnight: Treasury / Yahoo daily / CME
final OI / FRED / US calendar · 1-minute bars every 5 min while COMEX trades · 06:40 ETF, Fed path, monthly series due ·
07:35 MCX master + margins (retry 08:35) · 08:40 health snapshot · 08:45 pre-open snapshot (exists) · 09:05 brief · hourly US-calendar refresh 09:00–23:00 · 13:45 / 18:10 IBJA +
the India ladder · 15:45 CME daily OI (retry 17:15) · 16:10 SGE / SHFE · 21:30 FRED, EFRP, derived · Sat 02:30 COT with
hourly retries to 06:30 and a Telegram digest line · Mon / Fri / Sat WGC, RBI, LBMA · Sun 04:00 CME calendar), each a
`POST :8001/jobs/ingest-gold?job=<id>` with its groups: they fetch and never restart anything; a 404 (gold package not
deployed) pauses them for an hour; after downtime the key ones (`gold_overnight`, `gold_mcx_master`, `gold_cot_weekly`)
re-run with `backfill_from`. 6 Nov additions: `gold_sge_quotes` every 5 min in SGE hours (06:30–13:00, 17:30–00:00 IST;
light) and `gold_breeze_daily` 09:35 Mon–Fri (O-8: ICICI Breeze daily OHLC + OI per live MCX gold expiry into
`gold_mcx_daily`, read at `/db/gold/mcx/daily`; a session job). Dormant by owner decision O-8 (6 Nov): `gold_mcx_bhavcopy`,
`gold_mcx_category` (MCX's site blocks bots). O-1 / O-2 decided 6 Nov: keep as built / CME files link-only.

**Restart order:** never restart data-service while ui-api is up and data-service is down for a moment (ui-api grabs a read lock on market.duckdb and data-service comes back READ-ONLY, every ingest 503s): stop ui-api → restart data-service (`/ready` 200) → start ui-api (RUNBOOK 'After an outage').

**Restart freeze windows (IST):** never restart data-service or master-controller 07:45–09:20 (ICICI login +
pre-open jobs) or 18:30–21:15 (EOD pipeline, desk, shadow, wrap). The gold jobs only fetch and none is scheduled inside
the windows except the two small `light` ones (07:35 / 08:35 MCX master, 08:40 health snapshot); never start a gold
backfill (CME FTP ≈ 2 h, the Yahoo history pull) inside them or next to the 02:15 backup, and ui-api deploys avoid 07:55–08:10.
The Terminal v2 jobs inside the windows are the light class only (08:35 `morning_sweep` ≤ 6 small fetches, 19:25
`index_drivers_daily` on stored data + 3 GETs, the 20:30 pass with `iv_eod` last); they fetch and compute, never restart.
Never start an IV or drivers backfill (`iv_backfill`: UDiFF ≈ 30 min + legacy ≈ 1 h from cached files;
`index_drivers_backfill`; `vix_backfill`) inside a window or beside the 02:15 backup: a Sunday 10:00 start (PLAN 1.8).

## How to run things

```bash
P=/Users/sudheer/Desktop/jupyter_env/bin/python
# The five test suites (run all before claiming green)
$P -m pytest tests -q                       # core (unit + integration)
$P -m pytest scripts/tests -q               # controller, Telegram bot, studies' helpers
$P -m pytest services/ui-api/tests -q       # ui-api routers
$P -m pytest services/execution-service/tests -q
(cd alpha_lab && $P -m pytest tests -q)     # strategy lab (vendored-drift + engine + shadow)
(cd ui && npx tsc --noEmit)                 # frontend types

# Desktop program gates (also in CI's macOS 'desktop' job)
(cd desktop/src-tauri && cargo test && cargo clippy --all-targets && cargo fmt --check)
node desktop/scripts/boot_check.mjs         # boot page states (login grace, hung ui-api, down, no release)
for f in $(find ui -name node_modules -prune -o -path '*/__tests__/*.check.ts' -print | sort); do head -c 600 "$f" | grep -q 'npx tsx' || node "$f"; done   # every plain-node UI check, as CI runs them (desktop, pages, no-dialogs, prefs, platform, alerts, ws, streamProxy, …)
node --test ui/scripts/*.test.mjs           # UI release builder (build_ui.sh / release.mjs)
$P scripts/desktop_qa/run_selftest.py --app /Applications/SuryaDhana.app --live   # installed-app E2E (no other instance running)
$P scripts/desktop_qa/parity.py --a <old> --b <new> --browser both --out <dir>     # per-page A/B parity (reports/desktop_app/qa_harness.md)

# Generated docs and LEARN assets (both run inside scripts/tests too)
$P scripts/terminal_data_dictionary.py --check          # docs/TERMINAL_DATA_DICTIONARY.md vs dataset_catalog
$P scripts/gold_data_dictionary.py --check              # docs/GOLD_DATA_DICTIONARY.md vs SOURCES.md
$P reports/terminal_v2/LEARN/validate_learn.py          # v2 glossary / tooltips (--write rebuilds)

# Terminal page audit (43 pages, console + API errors; default --base http://127.0.0.1:8010; default set 16/16 incl. gold)
$P scripts/ui_audit.py --tabs all --browser both

# Alpha lab (PYTHONPATH convention)
PYTHONPATH=alpha_lab $P alpha_lab/run_today.py            # today's S1 book + vetoes (research view)
PYTHONPATH=alpha_lab $P alpha_lab/paper/shadow.py --status  # paper-shadow NAV/status (daily job: 19:50)

# Type check
$P -m mypy shared/ services/ --ignore-missing-imports
```

## Development Workflow

1. Each service is independently runnable with `uvicorn main:app --reload`
2. The three core services expose `/health`; data-service and ui-api `/ready`; ui-api `/live` and `/version`.
   `GET /metrics` (Prometheus text: `sd_http_requests_total`, `sd_http_request_seconds`, `sd_http_inflight`,
   `sd_duckdb_lock_wait_seconds`, `sd_job_seconds`, `sd_cache_events_total`, `sd_breeze_budget_used`,
   `sd_upstream_requests_total`, `sd_upstream_breaker_open`, `sd_feed_lag_seconds`), the `X-Request-ID` echo (bound as
   the log correlation id) and the JSON access log (no `/health`, `/api/health`, `/live`, `/`, `/metrics` lines unless
   they fail) come from `shared/metrics.install_observability`, installed on data-service, ui-api and master-controller
   inside the Host/Origin guard. Live on all three services since the 5 Nov deploy. The dormant legacy services are not covered.
3. Inter-service calls: httpx over 127.0.0.1 (ui-api → data-service :8001, the controller → both); the hot proxies share
   one `AsyncClient` per process (`shared/http_client.get_json`). Docker DNS only in the legacy compose.
4. Redis (127.0.0.1:6379, optional password) carries live quotes from data-service to ui-api's `/ws/monitor` hub
   (`live.quotes`); `signal.generated` / `order.filled` / `stop_loss.triggered` belong to the dormant legacy pipeline.
5. All config reads from `.env` via `shared/config.py`

## Where the plan lives

Product plan: `docs/PRODUCT_STRATEGY.md` (sleeves, Decision Desk, promotion gates) · Operations journal:
`docs/IMPROVEMENT_LOG.md` (newest first — read it before UI work) · Research verdicts: the RSCH tab /
`reports/*/FINDINGS.md` · Strategy lab + S1 paper shadow: `alpha_lab/` (PLAN, FINDINGS, paper/).
