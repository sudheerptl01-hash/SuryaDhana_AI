# SuryaDhana AI — Independent Product & Engineering Audit

**Repository:** sudheerptl01-hash/SuryaDhana_AI · **Commit audited:** `6885f8d` · **Date:** 15 Oct 2026
**Scope:** every file and function (1,389 LoC) — ingestion pipeline, ML feature layer, promoter-data fetcher, tests, CI.

> Interactive version with severity filtering: https://claude.ai/artifact/CLqkMGatda5QGjuD7AQR1X

---

## Verdict

**A strong research prototype with honest engineering — and a dishonest headline.**

The craft is genuinely above average: idempotent storage, an offline self-verifying demo, defensive parsing earned from real NSE quirks, and a clean, warning-free test suite. But the README's "production-grade" claim does not survive contact with institutional requirements, and the audit found defects that make the current output **unsafe to trade or train on**: the post-July-2024 bhavcopy parser has never worked, ML labels are silently corrupted at every series end, transient network failures become permanent invisible holes in the history, and the promoter parser can return confidently wrong numbers. Nothing is beyond repair — the fix-now list is small and surgical — but the data products this code emits today should not be trusted until the Critical items are closed.

**56 findings** after de-duplication: **7 Critical, 12 High, 12 Medium, 25 Low**, plus **14 verified strengths**. Severity is judged against the product's institutional ambition; the register notes where an item only bites at scale.

## Method

Five specialist reviews ran independently over the full codebase: a **quantitative researcher**, a **staff code reviewer**, a **principal architect**, a **security & market-data compliance reviewer**, and a **quality-engineering lead**. Findings were merged, de-duplicated, then pushed through a second verification stage:

- **Proven by execution** — reproduced by running code against the repo (pandas 3.0.x / duckdb 1.5.6 / Python 3.13). Most Critical/High findings carry this tag.
- **Confirmed against primary sources** — external claims fact-checked, including downloading NSE's real UDiFF bhavcopy (headers match the broken lookups verbatim), NSE's symbolchange.csv (1,067 renames; 50–71/year), CM bhavcopies published on days the code would skip, SEBI's SHP circular, and pandas 3.0 release notes.
- **Adjudicated** — where panels disagreed, a referee traced call paths and ran both scenarios; one finding was downgraded, one claim softened (see appendix).
- **Completeness sweep** — two final critics hunted for defects all five panels missed; eight new verified findings were added.

The repo's own 19 tests pass cleanly (1.7s, zero warnings); both demos exit 0. Several of the worst defects live precisely where the suite has no coverage.

## Maturity scorecard

| Dimension | Rating | Rationale |
|---|---|---|
| Data architecture (identity, schema, lineage, PIT) | **Prototype** | Ticker-keyed identity, overwrite-in-place, no raw zone, no bitemporality |
| Pipeline & orchestration | **Internal tool** | Real idempotency and per-day durability; resume and error handling silently lose data |
| ML feature & label layer | **Unsafe as-is** | Label corruption, unadjusted volume, unadjusted-by-default prices; indicator math mostly right |
| Data quality controls | **Absent** | Not one validation gate; a truncated file permanently counts as a complete day |
| Observability & operations | **Prototype** | Logs only — no manifest, metrics, gap report, alerting, runbook |
| Security posture (code) | **Sound** | No injection paths, no secrets, timeouts everywhere, in-memory-only zip |
| Sourcing & compliance | **Blocking for firm use** | Deliberate bot-control circumvention of NSE cannot be signed off institutionally |
| Testing & CI | **Internal tool** | Strong parser/storage coverage; zero coverage of network, resume, UDiFF |
| Packaging & reproducibility | **Prototype** | Two scripts, floating deps, constants in code, no lockfile or releases |

## What is genuinely strong

1. **Idempotent upsert on a declared PK**, test- and demo-proven — the hardest habit to retrofit, already here.
2. **Per-day commit durability** — a crash loses at most one day; only the resume *keying* is wrong.
3. **The offline demo is a small masterpiece of self-verification** (both formats synthesized, a simulated split pushed through adjustment with a continuity check).
4. **Flawless group-boundary hygiene** in feature math — zero cross-ticker bleed found.
5. **Correct Wilder smoothing** (`alpha=1/period`) where most implementations wrongly use `span=14`.
6. **Corporate-action direction, compounding, ex-date boundary all correct**; refusing to fabricate adjustments is the right philosophy.
7. **Survivorship-bias-free ingestion** — delisted names retained, rarer than many vendor feeds.
8. **Correct data semantics** — lakhs→rupees tested; VWAP from NSE's true traded average; `' - '` nulls handled.
9. **Defensive parsing earned from real NSE quirks** + visible bug→regression-test discipline in git history.
10. **Honest README limitations** (unadjusted prices, label leakage, egress constraints) — the dissonance is the headline above them.
11. **Clean code-level security**: parameterized runtime query, data as values into DuckDB, in-memory-only zip (no Zip Slip), timeouts on 100% of HTTP calls, no secrets.
12. **Per-symbol error containment** in the promoter fetcher.
13. **Fully offline, deterministic, zero-warning test suite** across the pandas-3 transition.
14. **Polite scraping mechanics** — the volume isn't the compliance problem; identity misrepresentation is.

---

## Critical findings

### CR-1 · The UDiFF bhavcopy parser is dead code — it has never worked
`nse_historical_ingest.py:225` vs `:238–253`. Line 225 uppercases every header before the UDiFF branch looks up mixed-case names (`TckrSymb`, `SctySrs`, `OpnPric`…). Parsing any well-formed UDiFF file raises `AttributeError`, swallowed at DEBUG by `fetch_day`. NSE discontinued the legacy format on 08-Jul-2024, so for every day since, the advertised ISIN enrichment has silently never happened. Even with matching names, the branch stores series unstripped (breaking the merge key) and crashes on any missing column.
**Fix:** case-correct lookups; strip series; guard each lookup; golden-file test from the real UDiFF header; WARNING-level logging; ISIN-coverage DQ alert.
*Proven by execution ×3; real NSE file downloaded — headers match verbatim.*

### CR-2 · ML labels silently corrupted: unknown forward returns become "down"
`:479–481`. `(fwd > 0).astype("Int8")` maps NaN→0, not missing. The last *h* rows of every ticker and every delisted stock's final week get `label_up=0` while `fwd_ret` stays NULL — ~10,000 guaranteed-wrong negative labels at the newest dates, exactly where time-ordered validation lands. A backtest filtering `label IS NOT NULL` filters nothing.
**Fix (one line):** mask the label where fwd is NaN; add a `label NULL ⇔ fwd NULL` test.
*Proven by execution ×3.*

### CR-3 · Transient failures become permanent, invisible holes
`:148–173, 584–587, 610`. Holiday 404, retriable failure, and permanent failure all collapse into one `None` ("no file (holiday/unpublished)"). Resume restarts at `MAX(date)+1`, so holes are never revisited — and an explicit repair `--start` is silently fast-forwarded past its own window ("Nothing to ingest", proven). A 60-second NSE 503 burst permanently corrupts every rolling window crossing the gap.
**Fix:** tri-state fetch outcome; per-day ingest manifest; gap-scan resume (`trading_days − loaded_dates`, ~20 lines); `--start` always wins; post-run completeness check.
*Proven by execution; flagged independently by 4 of 5 panels.*

### CR-4 · Volume never split-adjusted — fake post-split "volume surge" features
`:380–382, 462–465`. Only prices are adjusted. After a 1:2 split, measured `vol_z_20 ≈ 4.1, 3.2, 2.1…` vs ±1 baseline — a model learns splits are followed by four weeks of abnormal volume. Pure artifact.
**Fix:** `adj_volume = volume / adj_factor`; compute volume features on it.
*Proven by execution.*

### CR-5 · Unadjusted prices are the silent default for features AND labels
`:367–368, 615`; README:40. The documented primary command passes no CA feed; `adj_factor=1.0` is indistinguishable from "no corporate action". Any split produces `ret_1d ≈ −50%` and `fwd_ret ≈ −50%` with `label=0`. The code also ignores a free detector it already has: the file's PREV_CLOSE is NSE's ex-adjusted base, so `close/prev_close_file` vs `close/shift(1)` disagreement flags un-fed CAs.
**Fix:** persist `is_adjusted` per row; NaN labels across unadjusted discontinuities; fail closed without `--ca` unless `--allow-unadjusted`; wire the PREV_CLOSE check.
*Proven by execution; two panels independently.*

### CR-6 · No raw retention, lineage, or point-in-time semantics — destructive overwrite
`:210, 257, 304, 333–339`. Raw bytes discarded; no file hash, fetch timestamp, or batch id; `DO UPDATE` overwrites without audit and doesn't refresh `loaded_at`. A backtest cannot reconstruct "what the platform knew on date X", and any parser bug forces a multi-hour refetch instead of a local reparse. (Whether NSE restates published bhavcopies could not be verified; the finding stands on reprocessing-cost and PIT grounds.)
**Fix:** land raw files to `raw/{source}/{date}/` with sha256 + timestamp; batch/as-of columns; keep superseded rows; `loaded_at=now()` in the UPDATE SET.

### CR-7 · Identity is the trading symbol; no instrument master
`:305, 298, 372–376, 423, 437`. NSE's symbolchange.csv records 1,067 renames (50–71/yr, verified live): each rename fragments history and restarts every rolling window; a *reused* symbol splices two unrelated companies (a ₹12 delisting followed by a ₹480 listing trains a +3,900% "return"); CA events keyed by ticker stop applying across renames. Separately, `build_features` groups by ticker while the PK includes series — a same-date EQ+BE pair makes duplicate (ticker,date) rows that misalign every shift/rolling (proven).
**Fix:** instruments dimension (surrogate id + ISIN + symbol-change history); re-key features/labels/CA by it; assert (ticker,date) uniqueness, prefer EQ.

---

## High findings

### HI-1 · Promoter parser returns confidently wrong numbers (proven, four modes)
`promoter_data.py:212–256`. (a) SEBI's real category C "Non Promoter - Non Public" contains both keywords and can poison *both* promoter% and public% (format confirmed vs SEBI circular CIR/CFD/CMD/13/2015). (b) First `*pct*` key in a row wins (`pctChange` → promoter_pct=−0.12), and the loop breaks even on an unparseable value, letting a later wrong row fill the field (→ promoter_pct=public_pct=100.0). (c) Pledge false positives ("non-encumbered" matches "encumber"; a delivery-% field returned as pledge) and the wrong ratio chosen (% of total vs % of promoter holding that the README promises). (d) `period` can be a broadcast timestamp or a stale quarter not matching the pct's quarter.
**Fix:** exact known keys before fuzzy fallback; category exact/prefix matching excluding "non promoter"/"non public"; [0,100] bounds; promoter+public≈100; select max-`asOnDate` record and extract everything from it; adversarial fixtures + golden files.

### HI-2 · Blocked network crashes the run instead of the documented fallback
`:131–143, 153, 521`. The holiday `sess.get` is outside its try; warm-up is unguarded before the retry loop. A DNS/egress failure — the scenario the README itself documents — aborts the whole backfill with a raw traceback (proven by monkeypatching).
**Fix:** wrap warm-up and the holiday fetch in the retry/except machinery (same for promoter `_warm_up`).

### HI-3 · Holiday handling can permanently skip real trading days
`:499–512, 527–531, 543–545`. (a) The API parse unions **every** segment — verified: equity bhavcopies exist for 2024-04-01 and 2025-04-01, both CD-segment holidays. (b) The static set lists 2025-10-21 (Diwali) as a full closure, but NSE held a Muhurat session and published a 3,039-row bhavcopy that day (downloaded), while inconsistently omitting the 2024 Muhurat day. (c) The comment "a stale calendar … never a data gap" is true only for *missing* holidays — a false positive is never requested, invisible to the 404 net and to resume.
**Fix:** parse `data.get("CM", [])` only; bound fetched dates to the window; handle Muhurat; persist the calendar and reconcile nightly.

### HI-4 · Re-ingesting a day erases previously-enriched ISINs
`:333–334`. `SET isin=excluded.isin` unconditionally — any re-run without PR enrichment (i.e. **every** post-Jul-2024 day under CR-1, or `--rebuild`) nulls stored ISINs (proven). The idempotency test asserts only row count.
**Fix:** `isin = COALESCE(excluded.isin, equity_eod.isin)` + preservation test.

### HI-5 · Suspension gaps turn "2-day" labels into multi-month returns
`:267, 439–441, 477–481`. Row-positional math with no calendar awareness: a 6-month suspension makes `ret_1d` a 6-month return, and the last pre-suspension row's `fwd_ret_2d` is the return over the whole suspension (often −60%+ after a fraud halt), presented as a 2-day outcome.
**Fix:** NaN returns/gaps over >~5 calendar days; NaN labels whose t→t+h span exceeds h+5 calendar days.

### HI-6 · Sourcing posture: deliberate bot-control circumvention
`:92–99, 118–143`; `promoter_data.py:77–141`. Rotating spoofed UAs, forged Referers, warm-up to harvest anti-bot cookies, automatic re-circumvention on 401/403. Request volume is polite; identity misrepresentation is the problem — unsignoffable for a regulated firm (licensed channel: NSE Data & Analytics / authorized vendors) and operationally fragile. Per-request UA rotation within one cookie session is also an inconsistent fingerprint.
**Fix:** sourcing decision before firm/production use (license or official bulk archives without impersonation); demote the scraper to a labeled personal/dev fallback.

### HI-7 · Zero data-quality controls, and the implied ones are wrong
`:268, 314–318`. `has_date` treats *any* rows as day-complete (a 50-of-2,000-row truncated file is permanently "done"); `_finalize` silently coin-flips conflicting duplicates with `keep="last"`. No row-count anomaly, OHLC invariants, coherence, reconciliation, outlier quarantine, or coverage checks exist — the cheapest of them would have caught CR-1 and CR-3 on day one.
**Fix:** per-day DQ gate persisted to `dq_report` with quarantine (12-point checklist in the roadmap).

### HI-8 · A 200-status HTML block page kills the backfill
`:560`. NSE's WAF serves block pages as 200; `parse_sec_delivery` is called unguarded → `KeyError: 'SERIES'` (proven), aborting a multi-hour run mid-loop without `store.close()`.
**Fix:** guard the primary parse; treat as a failed day in the CR-3 manifest; sniff HTML prefixes.

### HI-9 · Full-rebuild feature layer and single-writer store are the scale ceiling
`:287–289, 421–424, 484`. Every feature run pulls all of `equity_eod` into pandas (several GB RSS at 5y/all-NSE) and recomputes everything; a daily increment pays the full rebuild. The single DuckDB file allows one writer OR many readers — never both.
**Fix:** incremental trailing-window recompute (or DuckDB SQL window functions); publish partitioned Parquet to separate read/write paths.

### HI-10 · `--raw` auditability flag is an advertised no-op
`promoter_data.py:336, 346–348`; README:106–107. The flag creates `raw/` and nothing ever writes to it; demo mode ignores the flag entirely (verified). For the one script whose parser is heuristic, the single lineage affordance is dead code. Found independently by four panels.
**Fix:** pass the dir into `fetch()`, dump `{symbol}_shp.json`/`{symbol}_quote.json`; CLI-level test.

### HI-11 · Two hand-rolled NSE clients have already diverged
`nse_historical_ingest.py:102–173` vs `promoter_data.py:109–176`. Same concern, two implementations, already divergent in backoff, UA strategy, warm-up pages, and failure semantics. Any NSE anti-bot change gets fixed once and breaks the other.
**Fix:** one shared `nse_http` module in the package restructure.

### HI-12 · Tests and CI are blind exactly where the risk lives
Zero mocked-HTTP tests (delete the 403 re-warm and nothing fails); only the legacy zip layout is tested (CR-1 undetectable); the features test asserts presence only (RSI∉[0,100] would pass); CI smokes only the promoter demo; no lint/type/coverage; and the floating floor means the Python 3.10 leg silently tests pandas 2.x while 3.11/3.12 test 3.x (confirmed: pandas 3.0 requires ≥3.11).
**Fix:** mocked-HTTP tests; golden UDiFF fixture; value-level feature asserts on a hand-computed fixture; ingest demo in CI (~5s); ruff+mypy; coverage gate; lockfile; Python 3.13 in matrix.

---

## Medium findings

- **MD-1 · RSI returns NaN instead of 100 on zero-loss streaks** (`:392`) — 25 straight up-days → NaN until the first down day (proven); circuit-locked NSE names lose the strongest signal exactly when it fires. Fix: 100 where avg_loss==0 & avg_gain>0.
- **MD-2 · RSI/ATR seed bias** (`:390–391, 458–459`) — ewm seeds on the first observation, not Wilder's 14-bar SMA; up to ~9.9 RSI points off exactly at first emission (proven vs reference); fresh listings biased ~2 months. Fix: SMA seed or min_periods≈3–4×period.
- **MD-3 · Z-scores include the current bar** (`:462–470`) — z mathematically capped at (n−1)/√n ≈ 4.25 (proven exactly); spikes compressed and the window std inflated for the next 19 days. Fix: trailing window via `.shift(1)`.
- **MD-4 · Absolute-level features leak ticker identity and break PIT** (`:446–450, 458–459, 484`) — raw sma/ema/macd/atr levels are price-scale-dependent and get rescaled retroactively by later splits on rebuild (backtests irreproducible). Fix: drop levels; MACD→PPO.
- **MD-5 · The demo corrupts its own dataset, then presents it as healthy** (`:693–698, 705`) — the idempotency check re-upserts day 0 from end-of-run state before the feature build: phantom +85% day-0 jump, ISIN nulled, RSI ~98 for weeks, visible in the demo's own output; checks assert row counts only. Fix: re-upsert the identical frame + content-hash assert; make the CA check assert.
- **MD-6 · CA feed trusted blindly** (`:370–376`) — ratio unvalidated (0/negative accepted), unknown tickers silently ignored (proven), duplicate events double-compound, ambiguous dates parse month-first, O(events×rows) loop. Fix: validate; report unmatched; dayfirst/ISO; vectorize.
- **MD-7 · Promoter data has no history and invites lookahead** — snapshot CSV overwritten per run; SHP filings publish weeks after quarter-end but only `period` is captured; joining by period-end is textbook lookahead. Fix: quarterly history table + `filing_date`.
- **MD-8 · Supply chain** — floor-only pins, no lockfile/hashes/pip-audit; Actions pinned to mutable tags; no `permissions:` block. Fix: lockfile+hashes, pip-audit, SHA pins, `contents: read`, cache, concurrency.
- **MD-9 · No response-size caps; unbounded zip decompression** — full bodies buffered; requests transparently decompresses (bomb expands before code sees a byte); DEFLATE ~1032:1 on the zip path. Medium for a CLI; High if ever a shared service. Fix: stream with caps; member size/ratio limits.
- **MD-10 · No package/config/operability surface** — sys.path test hacks, constants in code (series whitelist ×3, URLs, Nifty-50, holidays), no manifest/metrics/alerting/runbook. Fix: package restructure + minimal ops surface.
- **MD-11 · Backfill economics** — 2–5h single-threaded for 5y, and under CR-6 that is also the reprocessing path; the legacy-then-UDiFF fallback wastes a guaranteed 404 per post-Jul-2024 day (cutover is known). Fix: branch on the cutover; bulk-download-then-parse.
- **MD-12 · Clients advertise brotli they cannot decode** (`:123`; promoter `:84`) — `Accept-Encoding: br` with no brotli dependency: urllib3 returns the body **undecoded** (proven with a local server) → UnicodeDecodeError on the primary path, silent empty set on holidays, silent BadZipFile on enrichment. Fix: add brotli or advertise `gzip, deflate` only.

## Low findings

| ID | Finding | Location |
|---|---|---|
| LO-1 | merge_sources latent one-to-many join — **adjudicated: unreachable in the shipped pipeline** (all paths pass `_finalize` dedup); harden with `drop_duplicates` or `validate='many_to_one'` | ingest:272–280 |
| LO-2 | Invalid `--start/--end` → raw traceback after the DB file is already created | ingest:578–581 |
| LO-3 | `--ca` validated only after the full ingest — typo kills a multi-hour run at the end | ingest:615 |
| LO-4 | `--demo` silently ignores every other flag (`--db`, `--ca`, …) | ingest:663–735 |
| LO-5 | `date.today()` is runner-local, not IST (self-heals next run) | ingest:580–581 |
| LO-6 | SM/ST ingested but excluded from features, undocumented | ingest:191, 423 |
| LO-7 | Demo CA fixture at a fixed shared-tmp name — concurrent-run collision | ingest:702 |
| LO-8 | Docstring promises OHLC merge + "PR as fallback"; only ISIN merged and the fallback is never implemented | ingest:273, 555–574 |
| LO-9 | Legacy `TOTTRDVAL` (lakhs) stored unscaled — latent unit trap | ingest:230, 237 |
| LO-10 | EQ→BE migration pushes deliv_pct to ~100 → fake +4σ delivery "signal" | features |
| LO-11 | No dividend adjustment — special dividends create fake −5…−10% fwd_ret events | ingest:352–383 |
| LO-12 | 52-week distance with min_periods=20 — a 4-week IPO reading looks like a real 52w | ingest:472–473 |
| LO-13 | `adj_prev_close` uses the current row's factor — coincidentally right for NSE files, wrong in general (unused today) | ingest:380–382 |
| LO-14 | Backoff sleeps after the final failed attempt (~17s wasted per dead URL; both clients) | ingest:171; promoter:145 |
| LO-15 | Promoter `_warm_up` outside the retry loop | promoter:128 |
| LO-16 | Indented `#` comments in `--symbols-file` become symbols sent to NSE (proven) | promoter:322–323 |
| LO-17 | UTF-8 BOM corrupts the first symbol and defeats the comment filter (proven); use `utf-8-sig` | promoter:322–323 |
| LO-18 | `main()` exits 0 even when 100% of symbols fail — CI smoke can't detect total failure | promoter:363; tests.yml:31 |
| LO-19 | `--out` validated only after the full fetch (lost work) and silently overwrites | promoter:357–361, 287 |
| LO-20 | README "(Only dependency is requests)" stale since duckdb/pandas/numpy were added | README:92 |
| LO-21 | `_finalize` drops untraded rows uncounted; keeps literal `"nan"` tickers | ingest:261–269 |
| LO-22 | `trading_days` silently ignores holidays passed as `date` objects (proven) | ingest:546–549 |
| LO-23 | `fetch_nse_holidays` returns `set()` at DEBUG on failure; docstring claims static-set fallback | ingest:515–536 |
| LO-24 | Outputs default to CWD (covered by .gitignore) | both CLIs |
| LO-25 | No-args `main()` starts a 5-year live scrape with no confirmation | ingest:741–766 |

---

## Remediation roadmap

### Fix now — before the next backfill or any model training
1. **CR-2** label NULL mask (one line) + consistency test.
2. **CR-1** UDiFF parser repair + golden-file test from the real header.
3. **CR-3 / HI-8 / HI-2** tri-state fetch outcomes, per-day manifest, gap-scan resume, `--start` wins, guarded parse and warm-up — together these end silent data loss.
4. **CR-4 / CR-5** adjusted volume; `is_adjusted` stamped per row; fail closed without a CA feed.
5. **HI-4** COALESCE the ISIN on conflict.
6. **HI-1** promoter parser hardening (exact keys, category matching, bounds, newest-quarter selection).

### Quick wins — days
- Minimal DQ gate persisted to `dq_report`: calendar completeness; per-day row count vs trailing median; OHLC invariants; deliv_qty ≤ volume and deliv_pct ≈ 100·dq/v; turnover ≈ vwap×volume; prev_close ≈ prior close (free split detector); |ret| outlier quarantine; in-file date vs requested date; ISIN coverage/day; rsi ∈ [0,100]; label NULL ⇔ fwd NULL; promoter+public ≈ 100.
- Persist raw files (`raw/{source}/{date}/` + sha256 + timestamp); branch the bhavcopy URL on the Jul-2024 cutover.
- Implement or delete `--raw`; fix the demo's self-corruption and make its checks assert.
- Holiday handling: CM segment only, bounded dates, Muhurat days, calendar persisted and reconciled.
- Indicator corrections (MD-1…4) and suspension-gap label masking (HI-5).
- CI: ingest demo smoke, mocked-HTTP tests, ruff+mypy, coverage gate, lockfile+hashes+pip-audit, SHA-pinned actions, `permissions: contents: read`, Python 3.13; brotli decision (MD-12).

### Structural — weeks (the platform track)
- **Instrument master** (CR-7): surrogate-id dimension with ISIN + symbol-change history from NSE's symbolchange.csv; re-key features/labels/CA.
- **Lineage & point-in-time** (CR-6): append-only raw zone with batch/as-of; keep superseded rows.
- **Incremental derived layer + read/write separation** (HI-9): trailing-window recompute; partitioned Parquet for readers.
- **Package restructure** (HI-11, MD-10): shared NSE HTTP module, pyproject, config, entry points, releases; manifest, metrics, alerting, runbook.
- **Sourcing decision** (HI-6): license NSE data or official bulk archives without impersonation; scraper becomes a labeled dev fallback. Promoter: quarterly history with filing dates behind a validation schema (MD-7).

---

## Verification appendix

| External claim | Verdict | Evidence |
|---|---|---|
| UDiFF uses mixed-case headers (TckrSymb, SctySrs, OpnPric…) | Confirmed | Real file downloaded from NSE archives; all 13 names verbatim; legacy format discontinued 08-Jul-2024 |
| holiday-master returns all segments; CM trades on some CD holidays | Confirmed | CM bhavcopies exist for 2024-04-01 and 2025-04-01 while CD circulars list both as Annual Bank Closing |
| 2025-10-21 Muhurat session published a bhavcopy | Confirmed | File downloaded: 3,039 rows; the static set also omits the 2024 Muhurat day inconsistently; other static dates check out |
| SEBI SHP category C is "Non Promoter - Non Public" | Confirmed | SEBI circular CIR/CFD/CMD/13/2015 + real NSE filings |
| pandas 3.0 requires Python ≥ 3.11 | Confirmed | pandas 3.0.x release notes |
| NSE symbol renames are frequent | Confirmed | symbolchange.csv: 1,067 rows; 69/50/71 renames in 2023/24/25 |
| Bhavcopy prices raw/unadjusted; NSE restates files | Partial | Unadjusted: confirmed (broker documentation, consistent). Restatement: no evidence either way — CR-6 reworded to not depend on it |

**Adjudications:** merge_sources row multiplication — proven with hand-built frames but proven unreachable in the shipped pipeline (all four call sites pass `_finalize`); downgraded to LO-1. The ISIN fill was confirmed unable to misalign. The completeness sweep also explicitly **cleared**: Int64 overflow on real NSE values, `has_date` dtype handling, sample_data.json schema and figures (plausible, clearly labeled illustrative), CSV/JSON writers on None/commas/quotes/unicode, and the git history (no regressions).

**Known limitation:** nseindia.com's cookie-walled API endpoints could not be probed live; API-shape claims rest on downloaded archive files plus multiple independent client libraries.
