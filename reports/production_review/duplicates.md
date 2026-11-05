# Duplicate-intent functions: findings and consolidations (agent DUP, 14 Oct 2026)

Pipeline per superpowers-lab `finding-duplicate-functions` (extraction → categorize → intent-detection → report →
consolidate). The skill's `extract-functions.sh` matched 0 functions on this codebase's arrow/const style, so both
catalogs were built by equivalent in-repo extractors (same schema): **1,920 Python** functions (services/, shared/,
scripts/ minus frozen research) and **593 TS/TSX** (ui/ minus .next, tests) → `dup_work/catalog_{py,ts}.json`.
Deviation from the skill noted: categorize + detect ran in-process (single strong model) instead of haiku/opus
subagents. Frozen zones (research record, alpha_lab vendoring, trading-rule modules) were report-only by design.

## Consolidations APPLIED (all HIGH confidence; behaviour-preserving unless noted; NO commits — edits only)

Survivor for all TS items: **`ui/components/terminal/index.tsx`** (the terminal kit — already the canonical format
module with tests upstreamed in usage across 59 imports).

| # | What | Deleted from | Survivor | Note |
|---|---|---|---|---|
| T1 | `ordinal` | MarketMonitor.tsx | kit `ordinal` | local had the 110–113 suffix edge wrong; kit correct |
| T2 | `tone` (pos/neg/zero colour) | Brief, StockProfile, ParticipantPositioning, WatchMonitor, WorldMarkets, MarketMonitor, PreOpen (7 locals) | kit `tone` | PreOpen variant now treats NaN as muted (improvement); StockProfile:600's percentile `tone` is a different intent and stays |
| T3 | `num`/`fmt`/`fx`/`fNum` locale formatters (9 locals) | MarketMonitor, PriceHistory, OptionChain, WorldMarkets, WarehouseHealth, BacktestTradeGrid, GoldPreOpen, BacktestPanel, FactorDiagnosticStudio | kit `fmtNum` (thin local aliases keep call sites unchanged) | identical semantics (en-IN, min=max digits) |
| T4 | `inr` ₹ formatters (3 locals) | StockProfile, TradeTicket, GoldAccuracyLog | kit `fmtInr` | kit renders negatives as −₹x (true minus) — cosmetic improvement |
| T5 | `median` | IpoMonitor.tsx | kit `median` | kit averages the middle pair on even counts and filters non-finite — slight correctness improvement to the GMP median display |
| T6 | `fmtDay` | EconomicCalendar, ResultsImpliedMoves | kit `fmtDay` (**new export**, byte-identical body) | EventCalendar's parse()-based variant intentionally left (different input handling) |
| T7 | `tradingViewUrl` | news/format.ts | re-export from terminal/ChartActions | one URL builder |
| P1 | `services/feature-service/indicators/` package (momentum/trend/volatility/volume.py, **188 LOC**) | entire directory deleted | `feature_engine.py` (the in-use copies) | abandoned parallel refactor: zero imports anywhere in the repo; `_rsi` there was byte-identical to feature_engine's |

**Verification:** `tsc --noEmit` clean · pytest 264 + 452 passed (tests/, scripts/tests, ui-api, execution) ·
no service restarted (running processes still serve pre-edit code until next restart).
**LOC removed:** ≈ 233 (188 Python + ~45 TS definition lines).

## DEFERRED — MEDIUM confidence (real duplication, but consolidation changes behaviour or crosses a boundary)

| What | Where | Why deferred / recommendation |
|---|---|---|
| `fmtPct` ×2, `fmtNum` ×2 | news/format.ts vs terminal kit | semantics differ (news signs zero as `+0.00%`; news fmtNum is `toFixed`, no locale). News module is a deliberate sub-theme. Recommend: align news on kit in a UI pass with visual review |
| news `T` palette | news/format.ts vs kit `T` | separate palette object with its own values — unify only with a design decision |
| `_rsi` list variant | ui-api/routers/news_scanner.py:426 vs feature-service | different I/O (incremental list, no pandas) across service boundaries; a shared/ta.py would couple deployables. Keep; name it `_rsi_series` for clarity |
| `_cache_get/_cache_set` TTL pairs | news_scanner.py (monotonic) vs commodity.py (time.time) | 2 copies with different clocks; below the 3+ bar. Recommend `services/ui-api/cache.py` with `time.monotonic` when a third user appears |
| `ago` ×3 | GoldPreOpen (iso→m/h/d), WorldMarkets (epoch→m/h/d), ResearchLibrary (iso→words) | two short-style copies could share a kit `agoShort(ms)`; adapters ≈ same LOC. Marginal |
| `signed` ×2 | GoldPreOpen vs GoldAccuracyLog | near-dup ₹-signed; kit has `fmtSignedPct` but no signed-₹; add `fmtSignedInr` if a third user appears |
| DuckDB "snapshot copy" helpers | 8 scripts + ui-api/recalibrate_yi.py + study scripts (frozen) | propose `shared/db_snapshot.py:connect_snapshot()` for FUTURE scripts; retrofitting operational/research scripts is outside the editable zone |
| `newey_west_t` ×3+ | held_overnight_study, evidence_probability_study, ml_label_study, alpha_lab quick_tests | research record is frozen; propose `shared/stats.py` for future studies only |

## INTENTIONAL — same name/shape, different purpose (do NOT merge; flagged as naming hazards)

| What | Where | Reality |
|---|---|---|
| `cr` ×5 | InsiderMonitor/DealsMonitor (input = **rupees**) vs StockProfile/LiveMovers/MarginMonitor (input = **crores**) | same name, different units — merging would corrupt displays. Hazard: rename to `rupeesAsCr` / `crCompact` in a later pass |
| `fmtTime` ×3 | CommodityTab (epoch→datetime), LivePortfolio (iso→time), MLEngineWorkspace (**seconds→duration**) | three different intents under one name; MLEngineWorkspace's should be `fmtDuration` |
| `fmt` in StockDetailModal / MLEngineWorkspace / LivePortfolio | format-spec dispatcher / fixed-4 / K-L compactor | distinct semantics |
| providers' `get_live_quote` ×6, `fetch_historical` ×5, `get_ohlcv` ×4 | services/*-service/providers/* | polymorphic interface implementations, not duplicates |
| `main`/`lifespan`/`health` ×10 | every FastAPI service | the service idiom |
| `date_span` ×5 | sota/wfo research runners | frozen research record |
| alpha_lab/lib/* vs shared/* | vendored by pre-registered design; a drift test enforces byte-equality | the one *sanctioned* duplication |
| `tone` IndexMembers (T.dim null), OwnershipShifts/LiveMovers (±0.005 deadband), IpoMonitor (±0.05) | deliberate per-view thresholds | kept; consider kit `tone(v, {deadband})` someday |

## Dead code found while scanning
- `services/feature-service/indicators/` — removed (P1 above).
- `scripts/nse_panel_qa_old.py` — superseded by nse_panel_qa.py; left in place (scripts zone not in my edit
  whitelist beyond the three named files) — recommend deletion.

Artifacts: `dup_work/catalog_py.json`, `dup_work/catalog_ts.json`, `dup_work/pre_edit_dirty.txt` (165 files dirty
before my edits — none of my reverts would have touched them; no reverts were needed).
