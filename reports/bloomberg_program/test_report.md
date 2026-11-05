# Phase 4 TEST report (PM, 14 Oct 2026 23:00 → 15 Oct 00:00 IST)

Everything below ran against the restarted stack (all five builders' code + the three PM-applied
patches). Companion: `integration.md` (what was applied), `latency_after.csv` (raw timings).

## 1. Regression — 779 tests, 0 failures
core 281 · scripts 130 · ui-api 349 · execution 7 · alpha_lab 12 · `tsc --noEmit` clean.

## 2. Terminal pages — 37/37 clean
`scripts/ui_audit.py` over the 15 nav tabs + the 22 GO-bar pages: **0 console errors,
0 failed API calls** on every page (screenshots: `reports/ui_audit/after*`). Playwright
cold-load p50 7.2 s includes the harness' fixed 6 s settle wait — not user latency.

## 3. Latency vs baseline (S8) — PASS with 3 explained flags
Method: all 153 baseline routes re-hit 3× (`latency_after.csv`); warm = min(hit2, hit3);
flag if >25 % slower AND >20 ms absolute. Parametrized routes re-measured with real values
(the baseline CSV stores `{ticker}` templates; first pass sent them literally — corrected).

- **148/152 routes within bounds.** Warm p50 5.4 → 4.1 ms.
- `/api/pipeline/features-explorer` 1 ms → 745 ms: **not a regression** — baseline returned a
  150-byte stub; it now returns the real 103 KB features payload (B2's parquet offload path works).
- `/api/alpha/universe` 197→1 417 ms, `/api/lw/screener` 1 712→2 914 ms: stable across repeated
  hits, no cache anywhere on the path; hop decomposition shows data-service alone takes 0.72 s to
  serialize the 69.5 MB `/db/ohlcv-bulk` payload both routes pull **per call**, so the baseline
  figures were never physically achievable end-to-end — baseline rows unreliable for these two.
  Tonight's diffs only *protect the loop* (`to_thread`) and *narrow* work (`equity_only=True`).
  **Pre-existing scale debt, ticketed:** a 60 s TTL on the bulk frame would cut both to <50 ms.
- Status changes: the two bare 404s are the prod-review C3 dead routes deliberately deleted
  (B1: `data/db/screener`, B2: `dashboard/data-check`). `desk/preview` SKIP→200 (improvement).
  `/api/telemetry/logs/stream` unmeasurable by design (SSE, 25 s heartbeats) — same as baseline;
  it hung the first sweep (httpx read-timeout never fires between heartbeats) — sweep tooling
  note, not a product bug.
- Payloads >150 KB (S2 list, all full-table pages): ohlcv-meta 584 KB (core variant now exists,
  −67 % for opted-in consumers) · fundamentals-screen 516 KB · mtf-monitor 369 KB · events 240 KB ·
  announcements 218 KB. Candidates for later `fields=` trims; none blocks.

## 4. Load test — PASS
20 concurrent clients × 15 s over 5 hot routes (quotes/live, dashboard/summary, alerts/feed,
stocks/list, positions/summary): **2 670 requests, 178 rps, p50 88 ms, p95 185 ms, p99 243 ms,
0 errors.**

**Event-loop isolation** (the test the 8-Oct freeze would have failed): `/health` hammered while
4 full T1 screener scans ran concurrently — p95 0.7 ms quiet → **0.8 ms contended (1.2×, PASS)**.
All 4 screeners returned 200. B2's purity work holds under real contention.

## 5. Live tick spike (F3) — PASS (plumbing); tick flow needs market hours
ICICI session verified valid. `LIVE_TICKS=1` restart → first `/live/ticks?symbols=…` request
lazily armed the engine: **CONNECTING → LIVE in ~12 s, 3/3 symbols subscribed, zero sub_errors,
zero REST quota spent** (websocket only). No ticks after-hours (23:56 IST) = expected; ui-api
merge verified: engine state `LIVE` surfaced while per-symbol quotes honestly fell back to Yahoo
with `source:"yahoo"`. Engine then **disarmed back to default OFF** and confirmed.
**Owner action to enable for real:** add `LIVE_TICKS=1` to `.env` (shared/config loads it into the
process env) — prices on WATCH/DESK/Profile then go tick-sourced 09:15–15:30 with Yahoo fallback.

## 6. Ops jobs
`shared_snapshot_build` (19:20) + `db_backup_daily` (02:15) registered with real next-run times
after the controller restart. First backup fires tonight 02:15 — verify in the morning:
`ls data/backups/duckdb/`.

## Verdict
Phase 4 **GREEN**: no regression introduced by the program's changes anywhere we can measure;
two pre-existing uncached-bulk routes flagged + ticketed; live-data plumbing proven end-to-end
up to the exchange being open. → Phase 5 CRITIQUE.
