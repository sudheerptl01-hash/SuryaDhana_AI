# Phase 3→4 integration record (PM, 14 Oct 2026 ~23:10 IST)

All five builder deliverables (build_b1…b5.md) landed; the PM applied the three cross-builder
patch blocks (single-writer files, per amendment A8) and resolved B1's two open flags, then
restarted the stack in the safe window and verified the new surface live.

## Patches applied (exactly as specified in the build reports)

| # | Patch | File | Verified |
|---|-------|------|----------|
| 1 | B3 quotes router mount | `services/ui-api/main.py:66,134` | `GET /api/quotes/live` → 200, Yahoo fallback `source:"yahoo"`, state OFF (kill switch honored) |
| 2 | B2 `fields=core` trim on ohlcv-meta | `services/data-service/main.py` (/db/ohlcv-meta) | core 198 KB vs full 598 KB (−67%); default `full` unchanged (1,496 rows, all keys) |
| 3 | B1 shared-snapshot hook | `scripts/news_scan_performance.py` (load_prices) | env var / pointer-file reuse, <24 h freshness check, falls back to private copy; compiles |

## B1 flags resolved

- **`master_controller.py --help` hang** — root cause: no arg handling at all; `--help` fell
  through and **started a second controller on :8008**. Fixed with a guard in `__main__`:
  any argument prints usage and exits (0 for `-h/--help`, 2 otherwise). Verified: answers in
  ~2 s, exit 0, no server start.
- **Pin drift** — `scikit-learn` pin 1.5.2 → **1.8.0** in `requirements.txt` + `requirements-ci.txt`
  (1.8.0 is what jupyter_env actually runs and what every artifact was trained under);
  added the four used-but-undeclared packages to `requirements.txt` with the installed versions:
  `apscheduler==3.10.4`, `psutil==6.0.0`, `scipy==1.17.1`, `playwright==1.60.0`.

## Full test sweep after integration (all green)

| Suite | Result |
|-------|--------|
| `tests/` (core unit + integration, incl. 7 live_ticks) | **281 passed** |
| `scripts/tests` (controller, bot, helpers) — rerun after the `__main__` guard | **130 passed** |
| `services/ui-api/tests` (incl. 4 quotes, errors contract, purity) | **349 passed** |
| `services/execution-service/tests` | **7 passed** |
| `alpha_lab/tests` (vendored drift + engine + shadow) | **12 passed** |
| `cd ui && npx tsc --noEmit` | **clean** |

**Total: 779 tests, 0 failures.**

## Restarts (23:0x IST — outside both freeze windows; markets closed, EOD jobs done)

`./start-local.sh restart` for data-service → ui-api → master-controller, then
`UI_MODE=prod ./start-local.sh restart frontend` (serves B4's rebuilt `.next-prod`).
All four healthy. Controller restart was REQUIRED: it activates B1's two new jobs —
confirmed registered with real next-run times:

- `shared_snapshot_build` → daily 19:20 IST (shared evening snapshot for the 19:45/19:50 jobs)
- `db_backup_daily` → **tonight 02:15 IST** (first verified DuckDB backup)

## Post-restart verification

- `GET :8010/api/quotes/live?symbols=RELIANCE,TCS` → 200 in 0.52 s cold; both symbols priced
  via Yahoo fallback with explicit `source`; `state:"OFF"` (LIVE_TICKS default off).
- `GET :8001/live/ticks` → clean state machine payload: `OFF`, 0 subscribed, no errors.
- **37/37 terminal pages audited clean** (`scripts/ui_audit.py`, two runs: 15 nav tabs +
  22 GO-bar pages): 0 console errors, 0 failed API calls, load p50 7.2 s (Playwright
  cold-navigation incl. 6 s settle wait — not user-perceived latency).

## Still open in Phase 4

- S8 latency re-measure vs `reports/production_review/endpoint_latency.csv` (153 routes) — running.
- Small concurrency/load test.
- Live tick spike (`LIVE_TICKS=1`): ICICI session verified **valid** tonight; after-hours spike
  proves connect+subscribe plumbing; true tick flow needs a market-hours run (09:15–15:30 IST).
  Permanent enable = one `.env` line (`LIVE_TICKS=1`), owner's call after the spike.
