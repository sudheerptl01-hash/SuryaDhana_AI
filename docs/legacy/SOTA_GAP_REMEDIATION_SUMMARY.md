# SOTA Gap Remediation Summary — SuryaDhana_AI

**Companion to `SOTA_QUANT_GAP_REPORT.md`.** The audit report is the *before* (problem,
retail shortcut, SOTA standard, blueprint). This document is the *after*: what actually
shipped for each gap, the files touched, the system impact, and the honest residual.

- **Status:** G1–G11 all implemented. 103 unit tests green (90 `services/ui-api/tests`, 13 `tests/unit/test_execution_scheduler.py`).
- **Verified live** in the running Docker stack (`ui-api` `:8010`, `execution-service` healthy). `MODE=PAPER` preserved throughout; no secrets touched.
- **Two data-starved gaps (G1, G2)** are *mechanism-complete but inert* until historical NSE tables are backfilled — they degrade gracefully and flag themselves.

---

## How to read the impact column

> **Impact = what changes in the numbers you act on.** Most of these gaps were making
> your backtest/Sharpe/drawdown look *better than reality*. Fixing them generally makes
> headline returns **lower but honest** — which is the entire point: you want to discover
> a strategy is weak in a backtest, not with real capital.

---

## LAYER 1 — Data Integrity (bias invalidation)

### G1 — Fundamental look-ahead  🔴→ mechanism live (data-starved)
- **Was:** today's P/E, ROCE, market-cap broadcast onto every historical bar — a 2022 "cheap value" screen was really selecting names cheap *as of June 2026*.
- **Shipped:** `_load_prepared` now joins fundamentals **point-in-time** via `pd.merge_asof(direction="backward")` (bar T ← latest snapshot with `as_of_date ≤ T`). Config surfaces `fundamentals_pit`, `fundamentals_coverage_start`; selection ordering falls back to `adv20` where PIT market-cap is unavailable. `allow_lookahead_fundamentals` opt-out retained.
- **System impact:** fundamental-filter backtests can no longer see the future. **Caveat:** DuckDB `stock_metrics` has only 4 snapshot dates (2026-05-26 → 06-04), so PIT coverage *starts 2026-05-26* — earlier bars get NaN fundamentals (correctly, not a fabricated value). Until you backfill quarterly PIT snapshots, **fundamental screens over historical windows are effectively disabled rather than biased** — the honest trade-off.

### G2 — Survivorship bias  🔴→ mechanism live (data-starved)
- **Was:** the universe was "names in the index *today*" — every delisted/merged/relegated loser was structurally absent, inflating CAGR/Sharpe and understating drawdown (Brown-Goetzmann-Ibbotson-Ross 1992: ~1–4%/yr bias).
- **Shipped:** as-of `index_membership(ticker, index, effective_from, effective_to)` resolver (vectorized `merge_asof` → per-bar `index_member` flag, candidates filtered on it) + delisting force-close in `simulate_portfolio` (`delist_by_ticker` → a held name exits at its terminal delisting return, e.g. −100%, instead of vanishing). Config surfaces `membership_pit`, `survivorship_adjusted`, `n_delistings`.
- **System impact:** when the `index_membership`/`delistings` tables exist, your backtest universe and exits become survivorship-free. **Caveat:** those tables don't exist yet (`corporate_events` is empty), so it reports `membership_pit=False` and runs on the current universe — same as before, but now *explicitly flagged* instead of silently biased.

---

## LAYER 2 — Signal & microstructure reality

### G4 — Endogenous market impact  🟠 fully live
- **Was:** impact was opt-in and OFF by default → headline numbers assumed infinite liquidity at the printed price; the coefficient was a hand-set scalar.
- **Shipped:** **temporary** √-law leg (`2·impact_coef·ATR%·√(alloc/ADV)`, Tóth-Lillo-Bouchaud) **+ permanent** Amihud/Kyle-λ leg (`amihud_coef·ILLIQ·alloc`, where `ILLIQ = |ret|/dollar_vol` is computed per-name in `_compute_advanced_factors`). **Auto-enabled at scale**: when per-position notional > 0.5% of the median name's ADV, impact turns on automatically (`impact_auto_enabled` in config).
- **System impact:** **your edge now decays with size.** A strategy that looks great at ₹10k but trades illiquid microcaps will show degraded returns at ₹10M because impact is charged per-trade (verified live: all trades carry a non-zero `impact_pct`). This is the single most important realism fix for scaling capital.

### G5 — HMM regime detection  🟠 fully live
- **Was:** SMA(200) benchmark gate — lags ~100 days, whipsaws in chop, binary on/off.
- **Shipped:** 2-state Gaussian **HMM** (Hamilton 1989) with Baum-Welch EM and a **causal forward-filtered** posterior `P(bull | data ≤ t)` (no look-ahead). Two modes: `gate` (hard) or `soft` (continuous exposure throttle — scales each new position's size by `P(bull)`, de-grossing smoothly). Falls back to SMA if the series is too short.
- **System impact:** the book **de-grosses gradually as the regime weakens** instead of slamming entries off after the move. Live fit on the benchmark: bear state σ=2.2%/μ=−0.72%, bull σ=0.8%/μ=+0.31%, 0.93 bull-state persistence. Open positions are never force-closed by the regime — only new entries are throttled (correct for a 2–5d book).

---

## LAYER 3 — Statistical rigor & factor isolation

### G3 — Deflated Sharpe + PBO  🔴 fully live
- **Was:** the grid search swept 63 filter combos and reported the top by raw Sharpe; the WFO selected the per-window winner by raw objective. No multiple-testing correction → the "best edge" was partly luck-of-the-draw, Sharpe statistically inflated.
- **Shipped:** **Deflated Sharpe Ratio** + **Probabilistic Sharpe Ratio** (Bailey-LdP 2014: haircuts the SR for #trials, trial-SR variance, skew/kurtosis) and **PBO via CSCV** (Bailey-Borwein-LdP-Zhu 2017). Wired into both `combinatorial_grid_search.py` and the live `_core_wfo` (`deflated_sharpe`, `dsr_n_trials`, `dsr_sr_annual`, `dsr_sr0_annual` in the `walk_forward` block).
- **System impact:** **you now get a verdict on whether a backtest's Sharpe is real or a selection artefact.** Live WFO example returned `deflated_sharpe ≈ 0.005` (SR=−1.72 below the SR₀=0.156 null-haircut) → correctly says "no skill here." Grid search showed the top combo's high Sharpe collapses to DSR≈0 — i.e. overfit. This stops you from deploying a lucky-looking combo.

### G6 — Factor attribution (Fama-French/Carhart)  🟠 fully live
- **Was:** no α-vs-β deconstruction — you couldn't tell if an "edge" was genuine alpha or just repackaged market/size/momentum exposure.
- **Shipped:** daily long-short factor returns (**MKT / SMB / UMD**) + OLS attribution with t-stats and R² (`factor_attribution`). SMB uses market-cap where available, **falling back to dollar-volume (`adv20`)** as a PIT-safe size proxy so the size factor survives historical windows.
- **System impact:** every backtest now reports **annualized α with a t-stat**. Live example: α=−2.28%/yr, **t=−1.57 (not significant)** — i.e. the strategy's returns were explained by factor exposure, *not* skill. This is how you prove an edge is idiosyncratic before trusting it.

---

## LAYER 3b — ML pipeline rigor

### G7 — Triple-barrier + meta-labeling  🟠 live (terminal-barrier)
- **Was:** live ML trained on a binary up/down direction label; López de Prado's triple-barrier + meta-labeling code was orphaned.
- **Shipped:** `label_kind` selector ("direction" | "barrier"); barrier labels derived from `label_return_pct` vs `profit_target_pct`; **meta-labeling** secondary model (`_train_meta_model`) that learns *when to trust* the primary signal (reports precision lift). `TrainRequest` gains `label_kind`, `meta_labeling`.
- **System impact:** you can train on **profit-targeted labels** (did it hit +2% before −2%) instead of raw direction, and meta-labeling **filters low-confidence signals** to raise precision. **Caveat:** the DuckDB `label_barrier` column is entirely NULL, so this uses a *terminal*-barrier label (target vs realized return) — the full path-dependent triple-barrier needs the intraday-path labels populated.

### G8 — Purged K-fold / CPCV  🟡 live
- **Was:** single chronological holdout with a purge gap — one OOS estimate, high variance.
- **Shipped:** `_purged_kfold_bounds` + `_robust_purged_eval` — K-fold CV with a purge+embargo zone bracketing every test block (AFML ch.7), so no train row leaks its forward label into a neighboring test fold. `TrainRequest` gains `robust_eval`, `robust_folds`.
- **System impact:** model validation AUC is now a **K-fold average with leakage control**, not a single lucky/unlucky split — a far more reliable estimate of whether the model generalizes.

---

## LAYER 4 — Infrastructure & execution

### G9 — Execution scheduler (TWAP/VWAP/POV)  🟠 fully live
- **Was:** naive market-on-close — the whole order filled instantly at one price, no partials, no slippage schedule.
- **Shipped:** new `execution_scheduler.py` — child-order scheduling (**TWAP / VWAP / POV**), a **partial-fill state machine** (a child fills only `max_participation · bucket_volume`; the remainder carries or is left honestly unfilled), **√-law slippage with horizon-accruing liquidity**, and **implementation-shortfall** reconciliation (executed VWAP vs arrival price). Wired into `ExecutionEngine.execute_scheduled()` + the `order_fills` audit table + live endpoint `POST /api/execution/order/scheduled`.
- **System impact:** **paper execution now models real fills.** Live: a VWAP 40k-share order booked at 16.2 bps implementation shortfall across 8 child fills; a POV 50k order into a thin name filled only 19.6% (40,181 shares honestly left unfilled) instead of pretending a full fill. The kill-switch correctly halted an oversized order. This is what stops a strategy that "works on paper" from dying on real fills.

### G10 — Fractional Kelly sizing  🟡 live
- **Was:** Kelly sizing and sector risk-checks existed in `risk-service` but were orphaned — never called from the sizing path (flat equal-weight / 15% cap).
- **Shipped:** fractional-Kelly cap in `simulate_portfolio` (`f* = W − (1−W)/R` from a **rolling window of the strategy's own closed trades**, strictly point-in-time; per-bet capped at `min(equal-weight, NAV·κ·f*)`), plus the sector-exposure cap wired into entry.
- **System impact:** position size now **shrinks below equal-weight when the live edge is weak** (κ·f* < 1/N) and never over-concentrates a multi-position book. Sizing reacts to the strategy's *own* realized win-rate/payoff, not a static fraction.

### G11 — Bounded telemetry + disconnect-cancel  🟢 live
- **Was:** unbounded telemetry queue (memory-growth risk under a slow UI consumer); training kept running after the UI disconnected.
- **Shipped:** bounded `queue.Queue(maxsize=2000)` that drops epoch frames under backpressure but block-puts critical frames; `generate()` sets `state.cancel` on client disconnect so the booster stops at the next round boundary.
- **System impact:** the ML training stream **can't OOM the ui-api process** under a slow client, and closing the browser tab **actually stops the training job** (frees the booster) instead of orphaning it.

---

## What's verified live vs. what's mechanism-only

| Gap | Code | Unit test | Live in container | Notes |
|-----|------|-----------|-------------------|-------|
| G1  | ✅ | ✅ | ✅ banner | PIT coverage starts 2026-05-26 (data) |
| G2  | ✅ | ✅ | ✅ fallback | inert until membership/delisting tables exist |
| G3  | ✅ | ✅ | ✅ WFO + grid | |
| G4  | ✅ | ✅ | ✅ all trades | auto-on at scale |
| G5  | ✅ | ✅ | ✅ HMM fit | |
| G6  | ✅ | ✅ | ✅ α t-stat | SMB via adv20 fallback |
| G7  | ✅ | ✅ | ✅ schema | terminal-barrier (path labels NULL) |
| G8  | ✅ | ✅ | ✅ schema | |
| G9  | ✅ | ✅ | ✅ endpoint | partial fills + IS verified |
| G10 | ✅ | ✅ | ✅ config | |
| G11 | ✅ | ✅ | ✅ | |

## To fully unlock G1, G2, G7
Backfill three things into DuckDB (none of which can be fabricated from current data):
1. **PIT fundamental snapshots** — `stock_metrics` keyed `(ticker, as_of_date)` with announcement-date stamping → unlocks G1 over history.
2. **Index membership + delisting tables** — `index_membership(ticker, index, effective_from, effective_to)` + `delistings(ticker, delist_date, delist_return_pct)` → unlocks G2.
3. **Intraday-path / triple-barrier labels** — populate `label_barrier` → unlocks the full path-dependent G7.
