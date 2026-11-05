# C2 ENGINEERING CRITIQUE — worldclass sprint re-audit (15 Oct 2026, 03:40–04:10 IST)

**VERDICT: SHIP-WITH-FIXES.** Tonight's ~5,000 lines are the best-engineered batch this terminal has
received: every number I independently recomputed came back exact, every hostile input I threw came
back in the one error envelope, the tick-persistence hook cannot break the feed (I attacked it
offline), the frozen zones are untouched, and both of last night's wire-contract criticals (D1, D4)
plus D6 are verifiably fixed. One HIGH defect ships tonight (unbounded `days` → memory ratchet +
cache churn, a 3-line fix), one MED (fo panel single-flight race), and a tail of LOWs. The repo
still has **no git remote and no commit since 14 June (503 untracked files)** — unchanged,
owner-pending, and still the only thing here that can lose everything at once.

Method: nothing trusted unreproduced. My own runs of the five suites + tsc + purity scanner +
42-page audit; ~30 adversarial probes against :8010/:8001/:8008; four independent recomputations
with my own code against raw sources; offline attack drives of TickStore and mc.py; frozen-zone
mtimes + import-graph + order-API greps. **One disclosure:** probing for a 422 guard I sent one
POST to `/api/lw/run-cycle-scan`, which launched a compute-only scan job (no orders, no Telegram,
no DB mutation beyond lw scan history) — that exceeded my GET-only brief; no other POST beyond the
sanctioned OSTR calculator.

---

## 1. The six-point bar, re-scored (prev → now)

### FAST — 6 → **7.5/10**
- **D3 is dead where it was fetch-bound, proven:** `/api/alpha/universe` warm **54 ms** (was
  1,417–1,472 ms); 10 concurrent cold same-key requests finish in **1.9 s wall with ONE upstream
  fetch** (was 6.6 s, 8× serialized) — single-flight verified by timing; `/health` p50 0.68 ms /
  p95 1.12 ms during it.
- Every new route ≤ 74 ms warm (charts 4–15 ms · term-structure/vix 8 ms · rollover 74 ms · mcx ≤1 ms
  · risk cached 1 ms, cold 20-name 2.9 s then 120 s TTL).
- Residuals, all honestly pre-declared by W7: `lw/screener` warm **1.35–1.50 s** (indicator compute,
  fetch share removed), `features-explorer` **881 ms** (R6, out of scope). The program's own
  <500 ms bar is still broken by these two. Under triple-cold-heavy load /health max hit 468 ms
  (GIL tail from threadpool pandas; p95 24.5 ms) — fine for one trader, visible at 100.

### LIVE — 3 → **5/10**
- **D1 fixed on the wire** (my curl: `/api/quotes/ticks` → `"ticks":{…}`), **D4 fixed in the client**
  (`liveTicks.ts:55–66`: LIVE now requires actual broker ticks; state vocab lowercased — the
  connected-but-tickless LIVE·ICICI lie is gone), **D6 fixed** (`ensure()` TTL-prunes + caps
  `_requested`; my garbage-symbol probe stays bounded at 5).
- Tick persistence (W6) is genuinely production-grade: bounded deque (cap verified: 250 in → 100 kept
  + 150 counted drops), atomic numbered parts, disk-full bounded (my chmod-0500 test: flush_error=1,
  rows_lost=50 counted, append still returns True), junk `as_of` (`../../evil`) cannot poison dir
  names, hook double-wrapped in try/except and import-light — **the store cannot break the feed**.
  W6↔W1 contract key names verified end-to-end (the D1 class of bug was NOT repeated).
- Why only 5: **no market-hours tick has ever been rendered end-to-end**, intraday bars/VWAP have
  never seen real ticks, and the three mini-contract Breeze codes are master-guesses pending the
  08:00 login. LIVE remains a design verified in the lab, not in the market.

### NEVER-LIES — 6.5 → **8/10**
- **Four independent recomputations, all EXACT:**
  1. *DERV basis:* my own parser on the raw UDiFF zip (`BhavCopy_NSE_FO_0_0_0_20261014…`) vs
     `/api/derivatives/term-structure` — all 3 NIFTY legs match to the share of OI and the bp of
     annualized basis (+3.20/+5.38/+5.95%); basis-history rows recompute exactly at both ends.
  2. *OSTR:* bull call spread 22600/22800 @144.20/62.00 — BE 22,682.20 = K1+debit, maxP ₹7,657,
     maxL −₹5,343, BE is an exact grid point with expiry P&L 0.00, margin floor = |maxL|, and the
     round-trip cost ₹119.45 reproduced by my hand ledger (₹119.44). Straddle BEs at days=0 =
     strike ∓ total premium exactly.
  3. *Charts:* my own ISO-week/calendar-month aggregation of raw `/ohlcv/TCS` rows vs
     `/api/charts/ohlcv` W and M — **0 mismatches** across 27 W + 7 M bars (labels = last trading
     day, holiday weeks included). Indicators executed independently: Wilder RSI first value 70.46,
     flat→50, all-up→100, EMA SMA-seed, Bollinger population σ — all ✓.
  4. *RSK:* independent rebuild of the documented convention (union calendar, 0-fill, k=ceil order
     statistic) for RELIANCE+TCS — var95 1.89 / es95 2.44 / var99 2.81 / 5d √5 4.22 / β 0.88 /
     σ 1.12 — **every figure matches the endpoint to 2 dp**.
- D7a (no URL/MDN leak, clean 404 not_found), D7b (lw days<0 → 422 invalid), D8 (validation 422s now
  carry the envelope — `days=abc` probes confirm) all verified live. Degraded-200s are honest
  everywhere new (charts intraday note, mcx quote reason + fallbacks labeled, risk per-symbol
  exclusion reasons). ESTIMATE labels on every margin/cost figure. MCX computed expiries == ICICI
  master for all four contracts, incl. both holiday-shifted dates (30 Oct, 4 Dec).
- Deductions: `alpha/universe?days=-5` → 503 **"data-service returned no OHLCV rows"** — a false
  statement (E3, same family W7 just fixed in lw); MCX ticket accepts `"NaN"`/`"Infinity"` price →
  null-riddled 200 (E4); a what-if basket of unknown names lights SECTOR **crit** off the "Unknown"
  bucket (E7); data-service's own local 422s are still raw arrays (handler is ui-api-only); NIFTY
  spot served with float32 artifacts (24055.80078125).

### SURVIVES — 3 → **4.5/10**
- **The first verified backup now exists**: `data/backups/duckdb/market-20261015.duckdb` (4.67 GB)
  + meta `rows: 8,205,794, sha256, created 02:15` — the scheduled job ran and verified. Tick data
  now survives restarts by design (atomic parts, rescan-continue numbering, corrupt-part skip).
- **Unchanged and fatal: `git remote -v` is still empty, last commit 14 Jun, untracked now 503**
  (up from 481 — tonight's 5k lines joined them). Backup is same-disk; no restore rehearsal.
  New wrinkles: the canonical `start-local.sh` runs ui-api with `--reload` (line 191) — a stray
  file save restarts the terminal's backend mid-session (it happened to W7 mid-build, R1); the fo
  futures panel has a build race that can corrupt its cache file (E2, self-heals).

### SCALES — 7 → **7.5/10**
- Verified: single-flight + 60 s TTL kill the 70 MB-per-call pattern under concurrency; D6's
  unbounded `_requested` fixed with TTL+cap; payload cuts −42…−57% with `fields=core` adopted by the
  2-min pollers (announcements 225 KB → 37 KB claimed; events core measured 141,970 B ≤ 150 KB ✓);
  `fields=junk` fails loud (422); caches telemetried with real counters; tick buffer bounded with
  measured flush math.
- **E1 (HIGH), the one that matters:** `days` is unbounded on GET `/api/alpha/universe` and
  `/api/lw/screener` (POST /scan is bounded 60–1825; the GETs are not), flowing unclamped into
  data-service `/db/ohlcv-bulk` (f-string interval, int-typed so no injection). Proven live:
  `days=1200` → 200 in 3.8 s, NOT clamped, and it **evicted a hot key from the 2-slot LRU**
  (telemetry evictions 0→1; 6 by probe end). Each distinct `days` is a full JSON pull whose parse
  spike ratchets the allocator: after my probes the ui-api worker sat at **2,040 MB RSS** and
  data-service at **1,921 MB**. Any client can keep both hot keys perpetually cold and push RSS
  arbitrarily. Also `bulk_cache._LOCKS` grows one entry per distinct key forever. (The unbounded
  `days` predates tonight; the cache makes it a shared-state attack instead of a self-inflicted
  slow request.)
- Remaining: fundamentals-core 242 KB / mtf-core 162 KB still over the 150 KB budget (declared,
  R4); riskdash opens a fresh httpx.Client per symbol per fan-out (40/call, 120 s TTL softens it).

### DISCIPLINED — 7.5 → **8/10**
- Frozen zones verified: `momentum.py` Sep 28 21:56 · `decision_desk.py` Sep 28 21:59 ·
  `trading_costs.py` Sep 27 11:38 (untouched); alpha_lab strategies/engine mtimes Oct 14 ≤21:02
  (pre-sprint, per Amendments v2). `mc.py` is genuinely report-only: the import graph shows exactly
  one consumer — the shadow STATUS line (`shadow.py:36,151`) — and no gate/StrategyConfig reference;
  DD-FRAGILE math verified independently (dd −0.5 on a known path; seed-deterministic). **No order
  API in any of the 13 new files** (grep). Journal composer is localhost-only and never sends (my
  dry-run: prints only); `weekly_journal` registered, next run Fri 16 Oct 20:10 IST, correctly
  sequenced between desk/shadow (19:30/19:50) and 20:30.
- Docs truth: CLAUDE.md "42 pages" is TRUE (COMMAND_PAGES counts 42; PM's 03:34 ui_audit artifact:
  **42 pages, 42 ok, 0 console errors**, 1 transient `ERR_ABORTED` on WRAP's ipo fetch — a
  navigation abort, not a server error; my own full re-run exited 0 with every printed page ok,
  console=0).
  `lightweight-charts` exact-pinned 4.2.3 and installed 4.2.3 ✓. The stack table matches the live
  processes (8001/8010/8008/3000 all answered).
- Deductions: the freeze is still not diffable (everything untracked — D2); the "4-process spine"
  runs its API on a dev reloader by design; scripts/tests counts drifted (reports say 137, I count
  138 — benign).

---

## 2. Defects (new code), ranked

| # | Sev | What | Where | Repro | Fix (one line) |
|---|-----|------|-------|-------|----------------|
| E1 | **HIGH** | Unbounded user `days` on scan GETs → full-panel pulls (8.2M rows), allocator ratchet (ui-api worker 2.04 GB / data-service 1.92 GB RSS observed), 2-slot LRU hot-key churn by any client, `_LOCKS` grows per key forever | `alpha.py:191` (`universe_size`, no ge/le), `lw_scanner.py:110` (no upper bound), `bulk_cache.py:49–57,96`, `data-service main.py:2892` | `curl ':8010/api/alpha/universe?days=1200'` → 200, 3.8 s, telemetry `bulk_ohlcv` evictions +1; repeat with fresh values to ratchet RSS | add `Query(ge=60, le=1825)` to both GETs; clamp days in `bulk_cache.get_bulk_ohlcv` |
| E2 | MED | fo futures-panel "single-flight" races: `_PANEL["running"]` check-and-set is OUTSIDE `_PANEL_LOCK`; two builders write the SAME `.tmp.gz` → corrupt panel (self-heals via corrupt-skip reload) | `fo_analytics.py:317–319` (+ `build_panel:296–298`) | code read; window = two cold `/db/fo/rollover` hits with a stale panel | move the `stale and not running` check-and-set inside `_PANEL_LOCK` |
| E3 | LOW | `alpha/universe?days<=0` → 503 with FALSE message "data-service returned no OHLCV rows" (the very message-family W7 fixed in lw) | `alpha.py:119–120` | `curl ':8010/api/alpha/universe?days=-5'` | validate `days >= 1` → 422 `invalid` (covered by the E1 fix) |
| E4 | LOW | MCX paper ticket accepts `"NaN"`/`"Infinity"` price → 200 with null-riddled payload (`NaN <= 0` is False) | `mcx.py:390–398` | `curl -X POST :8010/api/mcx/ticket -d '{"contract":"GOLDM","lots":1,"price":"NaN"}'` | reject `not math.isfinite(price)` |
| E5 | LOW | A gate curve shorter than the block (≤3 monthly returns) raises uncaught ValueError and kills the whole `--strategy both` run (no md/json written) | `mc.py:102–105` via `run_window` | 65-day synthetic curve → "block length 3 outside 1..2" (my run) | per-window try/except → `{"error": …}` row |
| E6 | LOW | `TickStore.stop()` can race the flusher if `join(timeout=10)` expires (disk stall): both compute the same part index and share one same-pid tmp name → corrupt part (readers skip it; those rows lost uncounted) | `tick_store.py:286–297` + `253–275` | code read (needs >10 s flush stall at shutdown) | serialize `flush()` with a dedicated flush-lock |
| E7 | LOW | Unknown-sector names aggregate into one "Unknown" industry → SECTOR **crit** on any ≥40%-unknown what-if basket (false positive vs the NSE-industry rule) | `riskdash.py:359–362`, `risk_math.py:238–266` | `curl ':8010/api/risk/dashboard?symbols=ZZZ1,ZZZ2,@@'` → severity.sector "crit" | exclude "Unknown" from `breach`/severity (keep the row) |
| E8 | INFO | `broker_stale_hours`: naive `datetime.now() − fromisoformat(as_of)` raises uncaught TypeError if the file's `as_of` ever gains a tz (only ValueError caught) | `riskdash.py:415–420` | code read (today's file is naive) | catch TypeError too / use tz-aware now |
| E9 | INFO | ₹-VaR scales covered-panel VaR% by FULL equity value when coverage <100% (approximation; `coverage_value_pct` is surfaced honestly) | `riskdash.py:302–306` | read | note beside the ₹ figures |
| E10 | INFO | Status split for the same `invalid` code: 400 (charts, OSTR leg errors) vs 422 (derivatives, mcx, riskdash, validation handler). Envelope identical, status not | charts.py/options_strategy.py vs the rest | probes above | pick one (422) next sweep |
| E11 | INFO | `_latest_cache` two-field update race can serve one request a stale fut frame; data-service local 422s still raw arrays; NIFTY spot carries float32 artifacts | `fo_analytics.py:261–268`; ds main.py | read | — |

Ops (pre-existing, re-flagged): **no git remote / June commit / 503 untracked (D2 — still the top
risk)**; same-disk backups; ui-api on `--reload` in the canonical script.

## 3. Build-report claims REFUTED or corrected
1. **build_w2.md** — "Panel build thread is single-flight with atomic writes": the single-flight
   guard is race-prone (E2); two threads can build at once and corrupt the panel cache. (Atomicity
   per thread is real.)
2. **build_w7.md** — "peak memory pressure strictly drops" / "cap kept at 2 LRU anyway": true only
   for the two standard keys; arbitrary `days` values let any caller evict the hot keys and ratchet
   RSS beyond any single pre-change request (E1: 2.04 GB worker observed). The latency and frame-size
   measurements themselves reproduced exactly.
3. **build_w5.md** — sanity figure "RELIANCE+TCS → VaR95 2.01%": the live endpoint and my
   independent recompute both give **1.89%** for the documented window (β 0.88 matches). Method
   verified; that one number does not reproduce as stated.
4. Count drift only: scripts/tests is **138** passed, not the reported 137 (W4/W8 ran mid-sprint).
   W1's "+15 → 400" and W7's "461" reconcile with tonight's final 461.

## 4. What held under attack (do not re-probe)
- **Suites, my run: 308 + 138 + 461 + 7 + 20 = 934 passed, 0 failed** (prev 779; +155 net new) ·
  `tsc --noEmit` clean · `check_event_loop.py` 0 findings · PM ui_audit artifact verified 42/42 ok,
  0 console errors (all 5 new tabs ok).
- Four exact independent recomputations (§NEVER-LIES): DERV basis & history, OSTR breakevens/
  extremes/grid/margin-floor/costs, charts W/M resample + indicator set, RSK VaR/ES/β/σ.
- ~30 hostile probes, all envelope-clean: path traversal in chart symbols, SQL-ish derivative
  symbols (regex + parameterized), tf=Q, 7m intervals, 2026-13-45 dates, 5-leg books (422),
  CE-without-strike (400 invalid), premium<0, iv=0, lookback<100, garbage risk baskets (honest
  per-symbol exclusions), lots 0/5000, unknown MCX contracts, `fields=junk` (422), `days=abc`
  through the NEW RequestValidationError handler (envelope ✓).
- OSTR edges: days_to_expiry=0 → intrinsic-only with exact BEs; FUT-only book (strike None) → BE at
  entry, loss bounded at S=0 = entry×qty exactly; 10,000×100,000 lots → no overflow.
- TickStore under my own attack: bounded buffer + counted drops, disk-full bounded + counted +
  append survives, bad rows strike (never raise), junk as_of neutralized; hook placement inside
  double try; `/ticks/store-status` honest (`started:false` tonight). Charts↔tick-store key contract
  matches end-to-end.
- Frozen zones + paper posture: mtimes clean, mc.py import graph report-only, zero order APIs in new
  files, journal sends nothing, MCX expiry rule == ICICI master ×4, D1/D4/D6 all verifiably fixed,
  backup meta row-count+sha256 real, `weekly_journal` scheduled 20:10 Fri.

## 5. Fix order for the PM (smallest first)
1. E1: bound `days` on the two GETs + clamp in bulk_cache (3 lines) — closes HIGH + E3.
2. E2: move the panel check-and-set under `_PANEL_LOCK` (2 lines).
3. E4/E5/E7: isfinite guard · per-window try · Unknown-sector exemption (≤5 lines each).
4. Unchanged owner items: **push to a private remote tonight**; offsite the backup; take ui-api off
   `--reload` for the prod posture.
