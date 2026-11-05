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
**Gold jobs (26 Oct 2026):** `GOLD_JOBS` in `scripts/master_controller.py` (03:10 overnight: Treasury / Yahoo daily / CME
final OI / FRED / US calendar · 1-minute bars every 5 min while COMEX trades · 06:40 ETF, Fed path, monthly series due ·
07:35 MCX master + margins (retry 08:35) · 08:40 health snapshot · 08:45 pre-open snapshot (exists) · 09:05 brief · hourly US-calendar refresh 09:00–23:00 · 13:45 / 18:10 IBJA +
the India ladder · 15:45 CME daily OI (retry 17:15) · 16:10 SGE / SHFE · 21:30 FRED, EFRP, derived · Sat 02:30 COT with
hourly retries to 06:30 and a Telegram digest line · Mon / Fri / Sat WGC, RBI, LBMA · Sun 04:00 CME calendar), each a
`POST :8001/jobs/ingest-gold?job=<id>` with its groups: they fetch and never restart anything; a 404 (gold package not
deployed) pauses them for an hour; after downtime the key ones (`gold_overnight`, `gold_mcx_master`, `gold_cot_weekly`)
re-run with `backfill_from`. Dormant until the owner decides O-8: `gold_mcx_bhavcopy`, `gold_mcx_category`, `gold_breeze_daily`.

**Restart order:** never restart data-service while ui-api is up and data-service is down for a moment (ui-api grabs a read lock on market.duckdb and data-service comes back READ-ONLY, every ingest 503s): stop ui-api → restart data-service (`/ready` 200) → start ui-api (RUNBOOK 'After an outage').

**Restart freeze windows (IST):** never restart data-service or master-controller 07:45–09:20 (ICICI login +
pre-open jobs) or 18:30–21:15 (EOD pipeline, desk, shadow, wrap). The gold jobs only fetch and none is scheduled inside
the windows except the two small `light` ones (07:35 / 08:35 MCX master, 08:40 health snapshot); never start a gold
backfill (CME FTP ≈ 2 h, the Yahoo history pull) inside them or next to the 02:15 backup, and ui-api deploys avoid 07:55–08:10.

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
2. All services expose `/health`, `/ready`, `/metrics` endpoints
3. Inter-service communication via async HTTP (httpx) through internal Docker DNS
4. Redis pub/sub for events: `signal.generated`, `order.filled`, `stop_loss.triggered`
5. All config reads from `.env` via `shared/config.py`

## Where the plan lives

Product plan: `docs/PRODUCT_STRATEGY.md` (sleeves, Decision Desk, promotion gates) · Operations journal:
`docs/IMPROVEMENT_LOG.md` (newest first — read it before UI work) · Research verdicts: the RSCH tab /
`reports/*/FINDINGS.md` · Strategy lab + S1 paper shadow: `alpha_lab/` (PLAN, FINDINGS, paper/).
