# SuryaDhana AI — product rating (Terminal v2 synthesis, 4 Nov 2026)

Signed by: SYNTH (product manager + chief architect), from the seven research reports under `reports/terminal_v2/`
(R-UI, R-ARCH, R-DATA, R-OPTIONS, R-IV, R-DRIVERS, R-WORLD), each read in full, each resting on read-only evidence
gathered 4 Nov 2026 22:00–23:10 IST against the live stack (UI release `20261025-223942-0ae66db`, data as of the 4 Nov
close). Scores are 0–10 where 10 is "a Bloomberg function head would ship it as is" **for this owner**: an individual who
trades NSE stocks, NSE index/stock futures and options every day, and MCX gold; PAPER ONLY.

## Overall: 6.0 / 10

**Verdict.** SuryaDhana is a 7.5/10 end-of-day analyst's terminal and a 5.5/10 trading-day terminal, which averages to a
6.0 for the owner who asked for both. What is already world-class is rare and hard to buy: every number is dated, sourced
and badged; failed ideas are banished behind RESEARCH · FAIL banners; the GO command line is 80 % of Bloomberg's `<GO>`
idiom; 42 of 43 pages render in under 205 ms p95 with zero console errors; the stack heals itself after crashes and
caught up three missed sessions unattended tonight. What is missing is the options trader's *day*: the owner's explicit
ask (daily IV history and how IV changes) exists as one saw-tooth ATM series for two indices since Jul 2024 while 1,760
per-strike F&O bhavcopies sit on disk unread; there is no F&O book, no position Greeks, no real SPAN (the estimate is 4.8×
too high), no intraday IV, no options alerts, and the pages the trader needs are behind a MORE ▾ menu. "Who drives NIFTY"
exists as today-only arithmetic with no history. Two facts weigh on every other score: the Mac was dark for 55 % of the
last ten sessions' market hours and nobody was told; and five months of production code have no git remote and no
off-machine backup. Fix those two in a day, build the IV store and the drivers table in two weeks, and the product moves
from 6.0 to 7.5 on free data; the full Terminal v2 program (`PLAN.md`) is the path to 8.5.

## Per-area ratings

| Area | Score | Researchers' scores (resolved below) |
|---|---|---|
| UI | **7.0** | R-UI 7.1 market / 4.5 options-trader; R-WORLD 8.0 |
| Architecture & scalability | **5.5** | R-ARCH 8 appliance / 4.5 platform; R-WORLD 6.5 |
| Data freshness & update | **5.0** | R-DATA 5; R-WORLD 7 |
| Options & vol | **5.0** | R-OPTIONS 5.5; R-IV 4 (IV only); R-UI 5; R-WORLD 5.5 |
| Index intelligence | **6.0** | R-DRIVERS UI 5 / data 4 / honesty 8; R-WORLD 7 |
| Commodities | **5.5** | R-WORLD 7.5 gold / 3 others; R-UI 6 |
| Research & AI | **6.0** | R-WORLD 6 |
| Platform (alerts, workspaces, phone, API) | **5.5** | R-WORLD 6.5; R-UI alerts 5 / phone 2 / watch 4 |

### 1. UI — 7.0

Strongest evidence:
1. `reports/terminal_v2/R-UI/evidence/ui_audit_report.md`: 42/43 pages PASS in Chromium and WebKit, 0 console errors, 0
   failed requests; page-ready p50 46 ms / p95 205 ms; time-to-first-number ≤ 225 ms on 36 of 42 pages.
2. `ui/app/page.tsx:610` (`tabList`) and `evidence/flow_more_menu.png`: 7 of the 21 strip slots are legacy/research pages
   (three with FAIL/NO-EDGE banners), Alt+0 opens the dormant PORT engine with a LIQUIDATE button, while OMON/OSTR/CHRT/ALRT/
   GOLD/MCXG/RSK are items 9–22 of the MORE menu.
3. `ui/lib/pageKeys.ts`, `page.tsx:677` (`<ChartStudio />` without a symbol), `StrategyBuilder.tsx:164` (`useState('NIFTY')`):
   no active-symbol context, so stock → chain → strategy → ticket → positions re-enters the symbol four times and ends in a
   page that records nothing; phone width 390 px overflows on 7 of 10 pages (`evidence/mobile_*.png`, DERV 1,027 px wide).

Resolution: R-WORLD scored *craft* (8.0) and R-UI scored *workflow* (4.5 for the trader). Both are right; the kit, density
and honesty are Bloomberg-grade on the market pages, the trader's path is not. 7.0 reflects a terminal whose pages are
excellent and whose linking, strip and staleness states are not. Minor defects that cost real points: staleness in prose
(RSK, WRAP, CMDT), `?tab=gold` silently landing on BRF (`pages.ts` `tabFromSearch`), gold fair value differing by ₹39
between CMDT and MCXG, kit drift on EQS/BTST/PIPE/ALFA/GBOX/MLEN/DEXP, "IV rank 73" that is a percentile.

What a 9 looks like: the strip is the trader's day (BRF WTCH CHRT OMON OSTR DERV MOV EVTS ALRT POS GOLD MCXG RSK), one
active-symbol store feeds every page, OMON's chain is above the fold with Greeks and a strike → leg handoff, a
`SourceChip` (LIVE / DELAYED age / STALE / OFFLINE) sits on every panel, GO accepts arguments (`TCS OMON 27NOV`,
`ALRT TCS >3200`), saved Launchpad layouts exist, and the phone gets a compact mode for BRF/WTCH/ALRT/MOV/OMON summary.

### 2. Architecture & scalability — 5.5

Strongest evidence:
1. `R-ARCH` §2.3 `contention.json`: 10 concurrent distinct-symbol history reads cost 1,243 ms wall vs 134–165 ms each
   (sequential sum 1,456 ms): one DuckDB connection behind one `threading.Lock` (`duckdb_store.py:505-540`, 42 `store._conn`
   bypasses) gives zero read parallelism on a 12-core machine; `/db/market-monitor` calls Yahoo under `_monitor_lock` on the
   request path (`main.py:2290-2313`, a CLAUDE.md anti-pattern).
2. `git remote -v` empty; last commit `0ae66db` 14 Jun 2026; `git status --porcelain` 642 lines (348 untracked source
   files); `tmutil destinationinfo` "No destinations configured"; 20 GB of backups on the same SSD; 14,455 `node_modules`
   files tracked. `GET :8001/metrics` and `:8010/metrics` → 404 although CLAUDE.md says every service exposes `/metrics`;
   `set_correlation_id` has 0 request-path callers; 99.9 % of ui-api log lines are uvicorn access noise.
3. On the credit side: `scripts/stack_watchdog.sh` (hang detection, diagnostics, 3 restarts/hour cap, freeze windows),
   `startup_catchup` re-ran the EOD pipeline at 21:30 tonight, verified 02:15 backups, atomic UI releases with rollback,
   Host/Origin guard on all three services, PAPER ONLY enforced in code; warm p50 ≈ 25 ms across 20 key endpoints,
   `/health` 2–3 ms during a 10-client burst (the event loop is clean).

Resolution: R-ARCH's two numbers (8 as an appliance, 4.5 as a platform) are both true; R-WORLD's 6.5 sits between them.
5.5 rather than 6.5 because the disaster-recovery finding (2/10) is not a "scale" problem that can wait — it is the
single largest risk to the product's existence, and the CI pins differ from production (fastapi 0.115 vs 0.141, pandas
2.2 vs 3.0) so "CI green" does not mean "prod green". Nothing here needs a rewrite: per-call DuckDB cursors behind a
readers-writer lock, one shared `httpx.AsyncClient`, `/metrics` + request ids, and a private git remote are all S–M.

What a 9 looks like: read concurrency ≈ max-single (≈ 250 ms for the 10-client burst), cold ML tables out of the hot
file (57 % of rows), one HTTP client per process with circuit breakers and stale-serve, Prometheus metrics + request ids
+ JSON access logs with SLOs on SYS, a persisted job queue with leases, push (typed WebSocket channels) instead of 3,343
`nifty-live` polls per 60 k lines, ruff/mypy/pin-drift gates in CI, the repo on a remote with a restore drill actually run.

### 3. Data freshness & update — 5.0

Strongest evidence:
1. `R-DATA` §2 (`last reboot`, `pmset -g log`, `.logs/watchdog.log`): the stack was dark 31 Oct 11:29 → 4 Nov 21:29 (106 h)
   and 28 Oct 12:46 → 30 Oct 08:11 (43 h), silently; market-hours availability 5½ of 10 sessions (55 %); pre-open books,
   intraday breadth, FII/DII days and every alert for 2–4 Nov are lost for good; `HEALTHCHECK_PING_URL` "not set".
2. `R-DATA` §3 freshness matrix (45 rows: 22 green, 15 amber, 8 red) and §6: CME COMEX daily OI/EFRP **0 rows ever**
   (`ftplib` fails on the CME FTP's `229 Extended Passive Mode` reply, reproduced), all 18 FRED daily series time out on every
   run since 30 Oct (378 s/run), `gold_brief_docs` stuck at 23 Oct, Desk/shadow/results/valuation still at 30 Oct after the
   catch-up; only GOLD has a freshness catalog and chips.
3. `R-DATA` §4 measured publication times (HTTP Last-Modified, IST): F&O bhavcopy and participant OI 20:10, MWPL 19:23,
   FOVOLT 17:01, equity bhavcopy re-published 22:05 after the stack stored it, MTF T−1 file 22:12 (so MTF is T+2 in the
   terminal); the 18:30 EOD job is an hour early for every F&O file and the 20:30 job is what delivers them.

Resolution: R-WORLD rated the *pipes* (7); R-DATA measured the *platform* (5). The pipes are good (isolated EOD steps,
start-up catch-up that recovered three sessions in 7 minutes, the gold catalog). The platform is not: an appliance that is
off half the time, with silent rot in two feeds and no page showing dataset lag against an SLO. 5.0 stands; it becomes a
7 the week the dead-man ping, autorestart, the CME/FRED fixes and the DATA health view ship.

What a 9 looks like: a dead-man ping that fires when the Mac is off, `pmset autorestart`, a `dataset_catalog` with
`expected_by` per dataset and a `DATA n STALE` header chip, jobs scheduled on the measured publication clock (18:30 equity,
20:30 F&O, 22:45 MTF/revisions, 08:35 sweep), an `ingest_log` with `fetched_at`/`last_modified`/`sha256` and
`If-Modified-Since` re-fetch, explicit gap rows for lost sessions, every replayable job in the start-up catch-up.

### 4. Options & vol — 5.0

Strongest evidence:
1. `GET /api/market/option-chain/NIFTY` (4 Nov): 224 underlyings, 57 strikes, forward 23,931.23 from put-call parity, ATM IV
   13.9 %, PCR 1.07, max pain 23,800; `options_math.py` exact breakevens + Black-76 Greeks with 18 tests; `R-IV` prototype
   `iv_proto.py` reproduces the product's ATM IV at corr 0.998 and India VIX at 0.983 — **the math is right**.
2. `data/nse_archive/derived/option_history.json`: 578 rows, NIFTY + BANKNIFTY only, near-expiry ATM IV only, since
   2024-07-08; `option_chain.FILE_RE` ignores the 1,182 legacy files 2019-10 → 2024-07 on disk; the charted series is a
   calendar saw-tooth (mean 15.0 at 3 days to expiry, 11.1 at 4); OMON's "IV rank 73" is a percentile (true 252-day rank
   21–23); no term, skew, per-stock, intraday or event-crush history.
3. `R-OPTIONS/breeze_samples/margin_NIFTY_iron_condor.json`: Breeze SPAN for a NIFTY 09-Nov condor ₹81,497 vs OSTR's
   heuristic ≈ ₹3.9 L (4.8× high); `routers/positions.py` and `live_ticks.py` are `product_type="cash"` only (no F&O
   instrument in any book, RSK is cash VaR); `routers/alerts.py` `LEVEL_KEYS` = above/below/move on price only.

Resolution: R-OPTIONS 5.5 and R-WORLD 5.5 rate the whole desk; R-IV's 4 rates IV history alone; R-UI's 5 rates the pages'
workflow. 5.0 is the owner's-eye number: an 8 for the EOD analyst (chain, pricer, builder, DERV, implied event moves —
all honestly labelled), a 3 for the trading day (no book, no Greeks aggregation, no real margin, no intraday IV, no alerts,
no expiry-day view). Everything needed is free or already licensed (ICICI Breeze verified: chain quotes with bid/ask/OI, 1-
minute bars with OI for expired contracts, `margin_calculator`); nothing here needs paid data.

What a 9 looks like: Bloomberg `OMON` + `OVDV` + `SKEW` + `HIVG` + `OSA` in one place: a point-in-time IV store for all
224 underlyings back to 2019 with constant-maturity IV, rank *and* percentile (labelled), 25Δ skew and term history, IV vs
three realised-vol estimators, a results IV-crush ledger, a VOL screener, a paper F&O book with net Greeks and a spot × IV
× time grid, real SPAN from Breeze (NSE SPAN file offline), an intraday IV/OI tape, expiry-day replays, and typed options
alerts — every panel `arithmetic` or `context`, ending "describes, does not predict".

### 5. Index intelligence — 6.0

Strongest evidence:
1. `services/data-service/main.py:1617` `/db/index-contribution` and `evidence/movers_2026-11-04.png`: "actual +149.8 ·
   explained +154.4 (3 % off)" with the formula printed on the panel — honest, today-only, rebuilt live per request.
2. `R-DRIVERS/evidence/drivers_results.json`: the prototype with PIT weights explains 229 sessions of NIFTY moves at
   R² 0.996 / MAE 9.4 points per day and −2,132 of −2,169 YTD points; MEMB's on-page YTD attribution explains −5.4 % of a
   −11.8 % year because it multiplies today's weight by the YTD return.
3. Verified free sources: `top10nifty50_041126.csv` (10 names = 53.13 % of the index, rebuilt weights within 0.22 pp MAE),
   `ind_nifty50list.csv` (50) / `ind_niftybanklist.csv` (14 — needs a check), `ind_close_all_04112026.csv` (every index's
   OHLC incl. the Sunday 1 Feb 2026 Budget session that the Yahoo NIFTY50 series lacks); `equity-stockIndices` is dead (404).

Resolution: R-WORLD's 7 credits MKT regime/breadth/rotation and the participant panels, which are genuinely good; R-DRIVERS'
4–5 is the drivers view specifically (nothing stored, one horizon, wrong YTD). 6.0 for the area. The owner's "which companies drive NIFTY now" ask is a 3–4 builder-day job on stored data.

What a 9 looks like: Bloomberg `IMAP`/`MEMB`/`MRR` depth — a nightly PIT contribution table for NIFTY 50 and NIFTY BANK, a
horizon selector (1d/5d/1m/3m/YTD/since-leader-change), a driver-regime strip with hysteresis (raw leaders flip every 2
sessions; with hysteresis 5 changes in 2026), sector bar, monthly leaderboard, concentration and equal-weight-minus-cap-weight
breadth, a fit chip with the residual, Desk "Book vs NIFTY", and an intraday within-day contribution timeline.

### 6. Commodities — 5.5

Strongest evidence:
1. `reports/gold_program/` (PLAN, SOURCES 140 entries, FINDINGS): 9 sub-views, 21 PIT tables, COT / CME / physical / macro /
   contracts / LEARN, badges enforced by tests — but **not in the live release** (`?tab=gold` → BRF; a fix round is running).
2. `R-DATA` §3 rows 33–43: CME daily OI/EFRP 0 rows ever, FRED daily dead since 30 Oct, SGE/ETF/IBJA/health rows at 30 Oct,
   `gold_health_daily` 1 row, `gold_preopen_log` 0 rows — the gold data tier is half-fed on the day it ships.
3. `evidence/mcxgold.png` / `commodity.png`: MCXG is a real desk (session clock with MCX holidays, Breeze LTP, contract family
   with margins, paper ticket); CMDT still carries the pre-open desk with "wait for the 09:00 open" at 22:18; no MCX options,
   no silver/crude depth, the commodity calendar is not on ECO/EVTS.

Resolution: R-WORLD's 7.5 is for the gold *source*; R-UI's 6 is for what is *deployed*. 5.5 blends the undeployed page, the
silently empty CME/FRED feeds and the 3/10 for every other commodity. Gold alone will be 7.5 when deployed and fed.

What a 9 looks like: GOLD deployed with every catalog row green, CME FTP and FRED fixed, one gold fair value on one page,
MCX gold/silver/crude option chains with IV (after the Breeze MCX probe / O-8), silver and crude desks from the GOLD
template, the commodity calendar on ECO/EVTS, a paper futures book with daily MTM behind the MCXG ticket.

### 7. Research & AI — 6.0

Strongest evidence:
1. RSCH: 103 studies with verdict chips (`routers/research.py` CATALOG), pre-registered PLAN → FINDINGS format, every
   failed idea banished to a banner — the honesty engine is the product's brand.
2. `alpha_lab/` (S1 momentum + veto passed both gates; excess carry the only Robust F&O lead), `docs/PROGRAMMATIC_DATA_ACCESS.md`.
3. No LLM analyst over the terminal's tables, no notebook client, no tracking band / auto-demotion (PRODUCT_STRATEGY §3.5
   unbuilt), BTST defaults to the 15 bps project floor instead of the 93 bps ICICI cost.

Resolution: a single score (R-WORLD 6); nobody disputes it. The upside is unique: a citing, read-only, forecast-refusing
analyst over a private point-in-time store is something no vendor ships.

What a 9 looks like: `ASK` with eight testable guardrails (read-only SQL on the 19:20 snapshot, no writes/orders/Telegram,
forecast refusal, injection isolation, audit log, provider switch incl. local Ollama, nightly eval set), an `sd` notebook
client, tracking bands with auto-demotion on DESK and in the Friday journal, a trade journal with attribution.

### 8. Platform — 5.5

Strongest evidence:
1. `services/ui-api/routers/alerts.py` + `scripts/master_controller.py`: price above/below/±move alerts every minute to Mac +
   Telegram, 20 bot commands, multi-window + session restore, `/api/prefs` sync — a real platform base.
2. `AlertsCenter.tsx`: one-shot, price-only, no IV/PCR/basis/OI/event/gold-gap conditions, cannot be created from a chart or
   a chain strike; `WatchMonitor.tsx:174-216` twelve fixed columns with a "Yahoo ~1 minute delayed" footnote while the
   header says ICICI connected.
3. `globals.css` has no layout breakpoint below 720 px; the terminal is unusable on a phone (R-UI §4.2); no saved
   workspaces; no Excel/Sheets functions; the loopback API has no token (by design, blocks Excel).

Resolution: R-WORLD 6.5 vs R-UI's 2–5 on the sub-areas; 5.5. The scheduler-and-inbox plumbing is good; the conditions,
surfaces and layouts are thin.

What a 9 looks like: an event-driven alert engine over any stored series (IV rank, IV−RV, basis, OI spurt, ban, filings,
driver change), alerts drawn as lines on charts and created from a strike, repeat/snooze/channel per alert, Launchpad
workspaces with linked symbol groups, a phone mode or read-only PWA plus chart PNGs in the bot, Excel functions behind a
local token.

## Cross-cutting findings every researcher agreed on

1. **Honesty engineering is the moat.** Keep it binding (gold PLAN §0.1 / §f carried into `PLAN.md`): badges, no composite
   scores, context never coloured, "describes, does not predict", same number once per page, store-then-show, point-in-time.
   Three slips to fix now: "IV rank" → "IV percentile"; PCR coloured green ≥ 1 (`OptionChain.tsx` ~252); VIX accent red ≥
   80th pctile (DERV); LWSC's 0–1 composite needs a `heuristic` badge.
2. **The owner's two asks are the cheapest high-value builds in the repo**: the IV store (M) from files already on disk
   and the drivers table (S–M) from stored closes and filings. Both are pure arithmetic, both free.
3. **Nothing here needs paid data.** Said plainly where it would help: NSE Indices' exact daily weights/IWF (not needed; the
   free top-10 file calibrates), historical tick/order-level options data (₹1.1 L/yr/segment; not needed), consensus
   estimates and a news wire (no free Indian source; the page says so), US-style options flow and dealer gamma (no Indian
   equivalent; a GEX proxy is `heuristic` at best).
4. **The platform must be an appliance before it is a terminal**: dead-man ping, autorestart, no FileVault pause, git remote,
   off-machine backup, TOTP in the Keychain so the 08:00 login stops needing a human.

## Disagreements resolved (summary table)

| Topic | Positions | Resolution |
|---|---|---|
| UI score | R-UI 7.1/4.5 · R-WORLD 8.0 | 7.0: craft is 8, workflow is 4.5; the terminal is judged on both |
| Architecture | R-ARCH 8/4.5 · R-WORLD 6.5 | 5.5: DR 2/10 and CI≠prod pins pull the appliance score down; fixes are S–M |
| Data update | R-DATA 5 · R-WORLD 7 | 5.0: R-WORLD rated pipes, R-DATA measured availability (55 %) and silent rot |
| Options & vol | 5.5 / 4 / 5 / 5.5 | 5.0: EOD 8, trading day 3, IV history 2–4 |
| Index intelligence | R-DRIVERS 4–5 · R-WORLD 7 | 6.0: MKT/participants are good; the drivers view itself is 4–5 |
| Commodities | R-WORLD 7.5/3 · R-UI 6 | 5.5: gold undeployed and half-fed; others 3 |
| IV tables | R-IV `iv_*` (8 tables) · R-OPTIONS `fo_option_eod`/`fo_vol_surface_daily` · R-WORLD `fo_iv_daily` | R-IV's schema (prototyped, corr 0.998) is adopted verbatim; the `fo_*` names are its aliases |
| Intraday Breeze cadence | R-IV 15-min ≈ 700 calls · R-OPTIONS 2-min ≈ 1,100 · R-WORLD 2-min ≈ 1,500 | wave 1 pilot at 15 min (≈ 700/day, after the TOTP Keychain fix); wave 2 moves the three indices to 2 min once a month of budget data exists; owner caps the budget (O-T6) |
| `iv_eod` schedule | R-IV ≈ 19:35 "after the F&O ingest" · R-DATA measured the F&O file at 20:10 | `iv_eod` runs as the last step of the 20:30 `nse_positions_catchup` once the day's file is stored, retry in the new 22:45 pass; SLO 21:30 |
| VIX OHLC source | R-IV `historicalOR/vixhistory` 200 · R-WORLD `historical/vixhistory` 503 | daily OHLC from the `ind_close_all` file already fetched at 19:15 (it carries the India VIX row); `historicalOR/vixhistory` only for the one-off backfill, paged ≤ 1 year |
| Where the IV / VOL screens live | R-IV DERV › VOL sub-view · R-WORLD `VOLS` page · R-OPTIONS asks | wave 1: DERV › VOL sub-view with GO alias `VOL` (keeps the 43-page gates); a 44th page is an owner decision for wave 2 |
| Where the drivers live | R-DRIVERS extend MEMB · R-WORLD `DRVR` page · R-UI `CONTRIB` function | MEMB → "Index members & drivers" with GO aliases `DRVR` / `IMAP` / `CONTRIB`; no new page |
| Data-health view | R-DATA GO `DATA` page | SYS › DATA sub-view + header chip `DATA n STALE` + GO alias `DATA` in wave 1; page later if the owner wants it |
| Variance share vs points | R-WORLD w·β·σ share · R-DRIVERS additive points | points first (an identity with a residual); variance share as a wave-2 column |
| Surface scope | R-IV indices + watchlist (0.3 GB) vs all 224 (2–3 GB) · R-OPTIONS ±15 % / 3 expiries ≈ 45 M rows | `iv_expiry_daily` + `iv_summary_daily` for all 224; `iv_surface_daily` for indices + the owner's F&O watchlist + any name in a paper book, ±15 % moneyness, first three expiries; owner may widen (O-T4) |
| Priority: options program vs pre-trade gate + journal | R-WORLD asks | options program first (the daily workflow the owner described), the gate in wave 2, the journal in wave 3 |

Evidence paths: `reports/terminal_v2/R-UI/REPORT.md` + `evidence/`, `R-ARCH/REPORT.md` (+ scratchpad `latency.json`,
`contention.json`), `R-DATA/REPORT.md` + `probe_results_2026-11-04.json`, `R-OPTIONS/REPORT.md` + `shots/` +
`breeze_samples/`, `R-IV/REPORT.md` + `iv_proto.py` + `iv_compare_NIFTY.csv`, `R-DRIVERS/REPORT.md` + `evidence/` +
`nifty_drivers_prototype.png`, `R-WORLD/REPORT.md` + `evidence/`.
