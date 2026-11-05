# Red-team design review — Phase 2 gate (14 Oct 2026, ~22:55 IST)

Reviewed: PLAN.md · REQUIREMENTS.md · DESIGN_SYSTEMS.md · DESIGN_UIX.md, verified against code (file:line) and
two live measurements. Verdict up front: **both designs are buildable tonight, but two integration gaps would
have shipped a dead live-feed and crashing error panels.** 2 BLOCKERS, 5 MAJORS, 9 MINORS.

## Findings

**1. BLOCKER — Nobody ever subscribes: the live feed would stay empty.** DESIGN_SYSTEMS §6 makes ticks flow only
after `POST /live/ticks/symbols` (data-service) via ui-api `POST /api/quotes/watch`; DESIGN_UIX §4's
`useLiveTicks` **never calls any POST** — it only polls `GET /api/quotes/ticks` ("connected flag comes from the
ticks response"). Net effect: zero subscriptions → every symbol falls to Yahoo forever; chips would honestly say
DELAYED and the centerpiece ships dead. Worse, the designed `POST` is **set-replace**, so two concurrent panels
(WATCH posts 30, stock window posts 1) would thrash each other's subscriptions even if wired.
*Amendment (smallest, fixes both + restart self-heal):* drop the frontend POST entirely. Data-service
`set_symbols` becomes **union semantics with per-symbol `last_requested` + TTL eviction** (unsubscribe symbols
unrequested for 10 min; cap 50 by LRU of `last_requested`; holdings always pinned). ui-api `GET
/api/quotes/ticks` **auto-ensures subscription**: fire-and-forget push of the requested set (∪ holdings) to
data-service on each poll (cheap, idempotent, 2 s cadence bounds churn). `POST /api/quotes/watch` is deleted
from the design; data-service POST stays as the internal mechanism. ui-api/data-service restarts now self-heal
within one poll. UIX hook unchanged except: no debounce needed beyond the 2 s cadence.

**2. BLOCKER — Structured `detail` crashes ~20 existing panels.** The §4 handler turns `{"detail": "msg"}` into
`{"detail": {code,…}}`. Grep (evidence): 20+ components render `e?.response?.data?.detail` directly as a React
child (CommodityTab:204, InsiderMonitor:23, IndexContribution:20, CompanyFilings:35, LWScanner:125/264/277,
OptionChain:139/144, GoldPreOpen:98, IndexMembers:23, OwnershipShifts:29, MarketMonitor:144,
FundamentalsScreen:55, BasketRisk:37, …). An object child throws in React → the error path itself crashes
panels. Neither design contains a normalizer-adoption map for these call-sites.
*Amendment:* the exception handler keeps **`detail` as the plain message string** and adds a SIBLING key:
`JSONResponse({"detail": msg, "error": {code, message, hint?}})`. Zero legacy breakage; `normalizeError` prefers
`error` → `detail` → legacy shapes; component migration becomes optional polish, not a gate. UIX normalizer case
list updated accordingly (the "detail as object" case is dropped; "detail string + error object" added).

**3. MAJOR — DESIGN_SYSTEMS §2 verdict for `stocks.screener` is factually wrong.** It says "async def with zero
awaits → make sync"; the body **awaits** `client.get(f"{DATA_SVC}/db/screener")` (verified in :477–665 region).
Converting to sync `def` would break the await. The actual offender is the local DuckDB block (~:635,
REQUIREMENTS F2.2). *Amendment:* keep `async def`; wrap the `get_conn()` DuckDB section in
`await asyncio.to_thread(...)`. (The dead `data_proxy:268 /db/screener` is the ui-api proxy; stocks.screener
calls data-service directly — deleting the proxy remains correct.)

**4. MAJOR — CI as designed will try to install torch.** `requirements.txt` pins `stable-baselines3==2.3.2`
(pulls torch), `xgboost`, `lightgbm` — multi-GB, slow, flaky on ubuntu-latest, and none of the five CI suites
needs them at import time (playwright isn't even in requirements; the browser test imports it inside the fixture
at :99 and self-skips). *Amendment:* F1.4 generates `requirements-ci.txt` = requirements minus
`{stable-baselines3, xgboost, lightgbm, tensorrt/torch-adjacent}`; CI installs that; a meta-test asserts the
subset stays a strict subset of requirements.txt pins. Add one local certification run in Phase 4: the five
suites executed once **with all services stopped** to prove CI-offline safety (ui-api suite ran green tonight
only while services were up — unproven offline).

**5. MAJOR — chg_pct will lie on corporate-action days.** Prev-close joined from **raw** bhavcopy close
(`nse_bhavcopy`): on a split/bonus ex-date the live ltp vs raw prev shows ±50–90% moves. *Amendment:* prefer the
exchange-provided previous-close field from the tick payload when present (Breeze L1 commonly carries `close`);
else bhavcopy raw; and clamp: if |chg_pct| > 25%, re-check against the corporate-actions detector or display
price with `chg —` and a `hint`. Record the chosen tick field in the first-tick debug log (already designed).

**6. MAJOR — B4 scope is a two-builder night squeezed into one.** Dock+Z scale, tabular, alert rebuild,
SourceChip+hook+3 adoptions, token sweep top-20 (597 hexes), GO recall, Skeleton + 10 adoptions, dynamic() ×35
components, System page, 4 mediums. *Amendment (scope order, binding):* must-land = F4.1, F4.2, F4.3, F3.3,
F4.8, F4.9 + amber/#FFF unification; time-permitting = full top-20 sweep, F4.6 GO recall, F4.7 ten skeletons
(TabSkeleton itself is required by F4.9's loading state), F4.5 polish, F-006 mobile sheet. Anything cut is
listed in build_b4.md and the F4.4 census target relaxes pro-rata (report actual).

**7. MAJOR — evening-env injection dies with a controller restart (design relies on module state).** The 19:20
job holds `SURYA_SNAPSHOT_PATH` in-process to inject into 19:45/19:50 spawns; a controller restart at 19:30
loses it. The pointer-file fallback saves consumers, but then the env path is silently never exercised.
*Amendment:* B1's job-spawn injection reads the **pointer file at spawn time** (not module state): tiny helper
`_snapshot_env()` → `{**os.environ, "SURYA_SNAPSHOT_PATH": p}` when pointer fresh. Module state dropped.

**8. MINOR — timing race resolved by measurement:** 4.4 GB `cp` = **1.12 s** on this volume (APFS clone/fast
SSD). 19:20 build (copy+verify ≈ seconds) vs 19:30 desk: no race. Honesty note for the report: with APFS clones
the "20–28 GB SSD writes/day" scale claim overstates physical writes; the real wins are RAM/verify time and
orphan hygiene.

**9. MINOR — snapshot WAL naming:** copying `market.duckdb.wal` must land as `evening-<ts>.duckdb.wal` (DuckDB
pairs by name) — state it explicitly in `shared_snapshot.build` (news_scan copy block :88–90 already does the
matching-name pattern).

**10. MINOR — backup freshness window:** the 02:15 backup reads the 19:20 snapshot → misses 20:30 F&O catch-up
and 20:45 results ingest of that evening. Acceptable loss window; must be NAMED in RUNBOOK_RESTORE ("backups
lag ≤1 trading day of positions/results data").

**11. MINOR — PRAGMA placement:** `duckdb_store.__init__` connects in **three** branches (:518–:535) — apply
`memory_limit`/`temp_directory` after whichever connect succeeds (one helper), and create `data/.duckdb_tmp`.

**12. MINOR — `git mv` violates the no-commit posture less than it seems but still mutates the index.**
Use plain `mv` for the F5.4 sweep; git will track renames at the owner's eventual commit.

**13. MINOR — UIX normalizer test harness is hand-waved** ("vitest? none configured"). Accept for tonight:
tsc-types + a 10-case `node ui/lib/__tests__/apiError.check.mjs` (plain JS re-import of compiled logic is
overkill — instead inline the cases in a tiny TS file exercised by `tsc` type-level + runtime via
`npx tsx` if available, else document as audit-covered). Not a gate; list in build_b4.md.

**14. MINOR — ALERT-fix mechanism nuance:** ChartActions ALREADY swaps its chips for the form when `alertOpen`
(:93–94); the overlap comes from the form's ~430 px width inside the modal header's `flexWrap:'nowrap'` row
(:229) spilling over the modal's OWN price/watchlist chips. The `alertLayout='row'` spec still works; builder
should fix at the modal: when alert editing, the form takes a full-width row *below* the header (or the modal
hides its own chip row) — pick whichever is fewer lines; acceptance screenshot governs.

**15. MINOR — watchdog is global:** 120 s no-tick → DEGRADED is wrong only in the all-illiquid corner; holdings
are pinned and liquid enough in practice. Accept; add "state flips back to LIVE on next tick" explicitly.

**16. MINOR — dynamic() off-by-naming risk:** spot-check confirms the sampled component filenames exist
(AlphaDiscoveryDesk, GlassBoxStudio, WarehouseHealth, SystemTelemetry, CommodityTab, DataExplorerTab ✓); builder
must derive the final list from `page.tsx` imports, not the design's prose list. ml_workspace `/health` is at
:639 (design said :630) — trivial.

**17. MINOR — ui-api `main.py` dual-writer residue:** §9 resolves B2/B3 collision ("B3 owns the mount lines…
PM applies if conflict") but the matrix line still says `ui-api/main.py → B2`. Make it explicit: **B2 is the
only writer of main.py**; B3's router mount + lifespan line ships as a 3-line patch inside build_b3.md that the
PM (or B2, if still running) applies. Same for data-service `main.py`: B3 is sole writer; B2's
`ttl_cache`/`_typical_cache` cap lands in `ttl_cache.py`/`main.py`?? — **conflict**: B2 owns
`data-service/ttl_cache.py + duckdb_store.py` but `_fo_eod_cache`/`_typical_cache` live in data-service
`main.py` (B3-owned). *Resolution:* B2 ships those two small main.py edits as a patch block in build_b2.md; B3
(sole writer) applies them with its own edits.

## Conditions for build start
1. (F1) Live-feed wiring: union+TTL subscribe in data-service; ui-api GET auto-ensures subscription; frontend
   POST removed from both designs. **[A1]**
2. (F2) Error handler keeps `detail` string + sibling `error{}`; normalizer order error→detail→legacy. **[A2]**
3. (F3) screener verdict corrected to to_thread-the-DuckDB-block, stays async. **[A3]**
4. (F4) CI uses generated `requirements-ci.txt` (minus SB3/xgb/lgbm); Phase 4 adds the services-down suite
   certification. **[A4]**
5. (F5) chg_pct: tick-provided prev close preferred, bhavcopy fallback, 25% clamp+hint. **[A5]**
6. (F6) B4 binding scope order (must-land vs time-permitting) adopted. **[A6]**
7. (F7) snapshot env injected from pointer file at spawn time, no module state. **[A7]**
8. (F17) single-writer patches: B3's ui-api main.py lines + B2's data-service main.py lines travel via build
   reports, applied by the file's sole owner/PM. **[A8]**
Minors 8–16: fold into builder prompts verbatim (no design re-write needed).

## GO / NO-GO per workstream
- **B1 GO** with A4, A7, minor 10/12.
- **B2 GO** with A2, A3, A8, minor 9/11.
- **B3 GO** with A1, A5, A8, minor 15; live spike stays Phase 4, kill-switch default ON until spike passes.
- **B4 GO** with A2 (normalizer cases), A6 scope order, minors 13/14/16.
- **B5 GO** with minor 12 (`mv` not `git mv`).
