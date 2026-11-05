# SOTA Quant Gap Report — SuryaDhana_AI

**Audit scope:** alpha mining, backtesting, and ML for 2–5 day swing trading on the NSE DuckDB database.
**Branch:** `feature/backtest-lab-institutional` · **Mode:** PAPER (verified locked throughout) · **Date:** 2026-06-11
**Auditor:** SuryaDhana-Quant-Architect (Institutional Quantitative Systems Architect & Financial Engineering Auditor)

> **Honesty mandate.** A substantial P0–P4 hardening phase has landed and is verified live in this audit. Real walk-forward optimization, López de Prado purge/embargo CV, vol-scaled square-root market impact, ADV participation caps, k×ATR stops, vol-target sizing, sector caps, and benchmark-SMA regime gating are **already implemented (opt-in)**. This report **credits that work explicitly** and then assesses the *sophistication ceiling* — what an institutional (Bloomberg PORT / BlackRock Aladdin / Barra) tier still lacks. Gaps that are already closed are marked **[ADDRESSED — residual ceiling]**, not re-litigated as open.

---

## Executive Summary

### Severity / Effort / Impact matrix

| # | Gap | Layer | Status | Severity | Effort | Risk-Adj-Return Impact |
|---|-----|-------|--------|----------|--------|------------------------|
| G1 | Fundamental look-ahead: `stock_metrics` is a 4-date current snapshot applied to all 2021–26 dates | Data | **OPEN** | 🔴 Critical | M | High — inflates any pe/roce/mktcap edge; not real alpha |
| G2 | Survivorship: universe = current NSE-1500 constituents; 0 delisted names; corp-action tables empty | Data | **OPEN** | 🔴 Critical | L→H | High — systematically over-states CAGR/Sharpe |
| G3 | Multiple-testing: WFO + 63-combo grid rank by raw Sharpe, no Deflated Sharpe / PBO / Harvey-Liu haircut | Backtest | **OPEN** | 🔴 Critical | L | High — selected Sharpe is upward-biased by trial count |
| G4 | Market impact is opt-in static √-law, OFF by default; not endogenous (no Kyle λ / Amihud / Almgren-Chriss) | Backtest | **[ADDRESSED — ceiling]** | 🟠 High | M | Med — frictionless fills at scale when knob off |
| G5 | Regime detection is benchmark-SMA(200) + VIX-z; laggy/whipsaw; no HMM / GMM / change-point | Signal | **[ADDRESSED — ceiling]** | 🟠 High | M | Med — late regime flips bleed 2–5d edge |
| G6 | No factor attribution: only single-beta vs proxy; no Fama-French/Carhart, no sector-neutral score, no Barra | Risk | **OPEN** | 🟠 High | M | High — cannot prove α is not repackaged β/size/value |
| G7 | Live ML trains on binary `label_direction`; triple-barrier + meta-labeling exist but are orphaned | ML | **[PARTIAL]** | 🟠 High | M | Med — leaves path-dependent / asymmetric-payoff signal on the table |
| G8 | Single chronological holdout + purge gap; no purged K-fold / CPCV for live ML | ML | **[ADDRESSED — ceiling]** | 🟡 Med | M | Med — one OOS estimate, high variance |
| G9 | Execution is naive market-on-close; no order-book, partial fills, TWAP/VWAP/IS, slippage reconciliation | Infra | **OPEN** | 🟠 High | H | Med — backtest fills will not be reproduced live |
| G10 | Kelly sizing, sector-concentration risk-checks exist but are orphaned from backtest + execution sizing | Risk | **[PARTIAL]** | 🟡 Med | L | Med — capital efficiency left on the table |
| G11 | NDJSON telemetry queue is unbounded; daemon worker thread; no booster-memory release telemetry | Infra | **[ADDRESSED — ceiling]** | 🟢 Low | L | Low — robustness/memory under many runs |

### Data-flow map (end-to-end, with file references)

```
┌──────────────── INGESTION ────────────────┐
│ yfinance / ICICI Breeze                    │
│  → services/data-service/storage/duckdb_store.py
│  → data/market.duckdb  (ohlcv 1.06M rows, 1496 tkr, 2021-05→2026-06)
│  tables: ohlcv, stock_metrics(4 as_of_dates!), ml_features, ml_labels,
│          corporate_events/splits/dividends (ALL EMPTY)
└────────────────────┬───────────────────────┘
                     │
┌──────────── FEATURE / LABEL GEN ───────────┐
│ services/feature-service/feature_engine.py │
│  compute_price_technical (45 trailing tech)│  ← clean, trailing
│  merge_fundamentals (merge_asof backward)  │  ← PIT-SAFE join, but source snapshot is G1
│  compute_macro_features (SMA50/200 regime) │  ← G5 fixed-lookback regime
│  build_triple_barrier_labels (LdP)         │  → ml_labels.label_barrier  (UNUSED downstream — G7)
│ services/feature-service/labels/label_builder.py
│  build_labels → label_direction (binary)   │  → the ONLY label live ML consumes
└────────────────────┬───────────────────────┘
       ┌─────────────┴──────────────┐
       ▼                            ▼
┌──── ALPHA MINING ────┐   ┌──── BACKTEST / WFO ────┐
│ scripts/             │   │ services/ui-api/        │
│  novel_alpha_engine  │   │  backtest_engine.py     │  ← engine math (unit-tested)
│  combinatorial_grid_ │   │   simulate_portfolio    │  ← opt-in vol-target/sector/ADV/impact/k×ATR (G4,G10)
│   search.py (63 combos│   │  routers/analytics.py   │
│   ranked by Sharpe—G3)│   │   _core_wfo (REAL WFO)  │  ← per-window IS opt → embargo → OOS stitch
│  ml_quant_pipeline.py │   │   _SimContext (memoized)│     reports IS→OOS degradation, efficiency
│   (LdP CPCV/meta —    │   │   factor_decile_engine  │     NO DSR/PBO correction (G3)
│    SYNTHETIC, orphaned)│  │  routers/ml_workspace.py│  ← live XGBoost desk, purge gap (G8), binary label (G7)
└──────────┬───────────┘   └────────────┬────────────┘
           │                            │
           ▼                            ▼
┌──────────────── UI (Next.js App Router) ────────────────┐
│ ui/components/ BacktestPanel · MLEngineWorkspace ·       │
│   GlassBoxStudio · FactorDiagnosticStudio · RRG/VolProf  │
│ ui/lib/ mlTraining.ts (NDJSON reader) · backtest.ts      │
└────────────────────────┬─────────────────────────────────┘
                         ▼
┌──────────────── (PAPER) EXECUTION ──────────────┐
│ services/execution-service/live_execution.py    │
│  translate_weights_to_orders → naive market-on- │  ← G9 (no OB/partial/TWAP/VWAP/IS)
│   close; MODE=PAPER locked; 2% daily kill-switch │
└──────────────────────────────────────────────────┘
```

---

# LAYER 1 — DATA INTEGRITY (Bias Invalidation)

## G1 — Fundamental look-ahead via snapshot fundamentals (OPEN, 🔴 Critical)

**[FILE LOCATION]**
- `services/ui-api/backtest_engine.py:26-28, 33-50` — `FUNDAMENTAL_FIELDS = {pe_ratio, div_yld_pct, mktcap_cr, roce_pct}`.
- `services/ui-api/routers/analytics.py:272-281` — `_load_prepared` loads `stock_metrics` and `mdf.drop_duplicates(subset=["ticker"], keep="last")` then `df.merge(mdf, on="ticker")` — a single value broadcast to **every historical date**.
- DuckDB verified: `stock_metrics` holds **only 4 distinct `as_of_date` values, 2026-05-26 → 2026-06-04**, for 1496 tickers. There is no per-date fundamental history.

**[THE RETAIL SHORTCUT]**
Today's P/E, ROCE, market-cap and dividend yield are stamped onto a 2021 backtest bar. A 2022 "low-P/E value screen" is actually selecting names that are cheap *as of June 2026*, after five years of price discovery — the definition of look-ahead. The code *honestly flags* this (`fundamental_filters_active()` → `"fundamental_lookahead_active": true` in the result, and `lookahead_bias_present` in the factor profiler), which is good hygiene, but the bias is still **live** whenever a fundamental filter is used. The PIT path in `feature_engine.merge_fundamentals` (`pd.merge_asof(direction="backward")`, analytics:215-220) is correct *in mechanism* but is fed the same degenerate 4-date source, so it too cannot be point-in-time before 2026-05.

**[THE SOTA INSTITUTIONAL STANDARD]**
Point-in-time fundamental databases with as-reported snapshots and report-lag stamping — Compustat Point-in-Time, S&P Capital IQ PIT, FactSet Fundamentals. The canonical treatment of look-ahead from restated/late fundamentals is Banz (1981) and the survivorship/PIT discussion in Elton, Gruber, Blake (1996); the report-lag convention (lag fundamentals by ≥ the filing delay, e.g. 45–90 days for Indian quarterly results per SEBI LODR) is standard in Grinold & Kahn, *Active Portfolio Management* (2000).

**[REMEDIATION BLUEPRINT]**
1. **Schema change (data-service).** Make `stock_metrics` an append-only PIT table keyed `(ticker, as_of_date)`. Ingest each quarterly result-announcement snapshot with its *announcement date* (not period-end), via `services/data-service/providers/fundamentals_provider.py`. Backfill from screener.in / NSE corporate-announcements archives.
2. **Report-lag guard.** When stamping `as_of_date`, set it to `max(filing_date, period_end + 45 trading days)` so a Q-end 31-Mar number is not visible until it could have been filed.
3. **Backtest join (analytics.py `_load_prepared`).** Replace the broadcast merge with a per-date as-of merge identical to the feature-service path:
   ```python
   df = df.sort_values("date")
   mdf = mdf.sort_values("as_of_date").rename(columns={"as_of_date": "date"})
   df = pd.merge_asof(df, mdf, on="date", by="ticker", direction="backward")
   ```
   This makes a fundamental filter on bar T consume only the latest snapshot with `as_of_date ≤ T`.
4. **Hard banner (already partially present).** Keep emitting `fundamental_lookahead_active`; additionally surface a red UI banner in `BacktestPanel.tsx` whenever `config.fundamentals_as_of` is within the backtest window (i.e. coverage starts after `from_date`), stating *"Fundamental data is not point-in-time before {first as_of_date}; results over earlier dates carry look-ahead."*

---

## G2 — Survivorship bias (OPEN, 🔴 Critical)

**[FILE LOCATION]**
- `data/NSE_1500.csv` (1500 rows) and `data/nifty500_universe.csv` (504 rows) — **current** index constituents only (columns: ticker, company_name, sector, isin, index, cap_category).
- `scripts/nifty500_pipeline.py` — keeps only the latest row per ticker (`QUALIFY ROW_NUMBER() … ORDER BY as_of_date DESC = 1`).
- DuckDB verified: `ohlcv` has 1496 tickers; **0 tickers have their last bar more than 60 days before the global max date** → every name in the database is still trading. No delisted/merged/suspended constituents. `corporate_events`, `splits`, `dividends` tables are **empty (0 rows)**.

**[THE RETAIL SHORTCUT]**
The backtest universe is "the companies that are in the Nifty-500/1500 *today*." Names that were in the index in 2021 but later delisted, merged, were suspended, or fell out (the losers) are structurally absent. The strategy is being graded only on the survivors, which inflates CAGR, win-rate and Sharpe and *understates* drawdown — a well-documented upward bias of 1–4% annualized for equity strategies (Brown, Goetzmann, Ibbotson, Ross 1992).

**[THE SOTA INSTITUTIONAL STANDARD]**
Survivorship-bias-free historical constituents with point-in-time index membership and delisting returns — CRSP delisting-adjusted files (Shumway 1997 delisting-return correction), or reconstructed NSE index-membership change logs. The bias and its magnitude are formalized in Brown, Goetzmann, Ibbotson & Ross (1992), *Survivorship Bias in Performance Studies*, and Elton, Gruber & Blake (1996).

**[REMEDIATION BLUEPRINT]**
1. **Point-in-time membership table.** Build `index_membership(ticker, index, effective_from, effective_to)` from NSE index-reconstitution circulars (semi-annual). Store in DuckDB.
2. **As-of universe resolution.** In `analytics._load_prepared`, restrict the candidate set on bar T to `tickers where effective_from ≤ T < effective_to`, instead of "all tickers in the CSV."
3. **Delisting data.** Ingest delisted/suspended NSE symbols with their final price and a delisting return (apply Shumway's −30% convention for performance-related delistings where the final price is missing) so a position held into a delisting realizes the loss rather than silently vanishing.
4. **Populate corporate-action tables.** `splits`/`dividends` are empty; the engine currently relies entirely on yfinance `adjusted_close` (analytics:264-269). Persist explicit split/dividend events so adjustment is reproducible and auditable, and so total-return (dividend-reinvested) backtests are possible.
5. **Quantify the bias once.** Re-run the headline combo (combinatorial_grid_search) on survivor-only vs reconstructed universe; report the Sharpe/CAGR delta in `combinatorial_backtest_results.md` as the survivorship premium.

---

# LAYER 2 — SIGNAL & MICROSTRUCTURE REALITY

## G4 — Market impact: opt-in static square-root law, frictionless when off **[ADDRESSED — residual ceiling]** (🟠 High)

**[FILE LOCATION]**
- `services/ui-api/backtest_engine.py:518-522` — `impact_pct = 2.0 * impact_coef * atrp * (alloc / adv) ** 0.5` (round-trip, vol-scaled √-law). `adv` from `adv20` (`_compute_advanced_factors:154-157`). ADV cap at `simulate_portfolio:506-509`.
- Defaults: `impact_coef=None`, `max_participation_pct=None` (analytics `BacktestRequest:191-192`) → **OFF by default**; with the knob off, fills are at the signal/next-open price net only of the flat ≥15 bps friction.

**[CREDIT — what landed]** A genuine vol-scaled square-root-law cost (`Δ ∝ σ·√(Q/ADV)`), the empirically-dominant impact functional, *is* implemented, plus a hard ADV participation cap and a memoized `adv20` liquidity base. This is well beyond retail "fill at close." The √-law form matches Tóth et al. (2011) and the Almgren-style σ·√(participation) scaling.

**[THE RETAIL SHORTCUT — residual]**
1. **Off by default** → the headline numbers most users see still assume infinite liquidity at the printed price.
2. **Static, not endogenous.** `impact_coef` is a hand-set scalar, not calibrated per-name from order-flow. There is no temporary-vs-permanent impact decomposition, no decay, no participation-of-volume *schedule* (the whole order is charged one √-law cost at entry, as if executed instantaneously).
3. **No Kyle λ, no Amihud calibration.** The coefficient is not derived from the data; `corr_nifty_30` aside, nothing estimates price-impact-per-order-flow.

**[THE SOTA INSTITUTIONAL STANDARD]**
- **Kyle (1985)** λ: `ΔP = λ · Q`, λ estimated from regressing signed price changes on signed order flow (or proxied per Hasbrouck 1991 VAR).
- **Amihud (2002)** illiquidity: `ILLIQ_i = mean_t( |r_{i,t}| / DollarVol_{i,t} )` — a directly computable, per-name impact scalar from the OHLCV already in DuckDB.
- **Almgren & Chriss (2000)** optimal execution: temporary impact `η·(v)` + permanent impact `γ·Q`, with an optimal trajectory trading off impact vs. timing risk over the 2–5 day horizon.
- **Tóth, Lillo, Bouchaud (2011)** square-root law calibration: `Δ ≈ Y·σ·√(Q/V)` with `Y≈0.5–1`.

**[REMEDIATION BLUEPRINT]**
1. **Calibrate `impact_coef` from data (Amihud).** Add to `_compute_advanced_factors`:
   `amihud_i = (|ret_1d| / (close·volume)).rolling(60).mean()`. Map Amihud to a per-name `Y_i` so the √-law coefficient is *endogenous*, not a global constant. Persist as a column; pass per-candidate into `simulate_portfolio` instead of one scalar.
2. **Kyle λ panel.** Offline (DuckDB/pandas), per ticker regress daily `Δclose` on signed dollar volume `sign(ret)·close·volume`; store λ. Use `permanent_impact = λ·Q` as the *permanent* leg, the √-law term as the *temporary* leg.
3. **Temporary/permanent split + decay.** In `simulate_portfolio`, charge `temp = Y·σ·√(part)` on entry *and* exit (already round-tripped), and a separate `perm = λ·Q/ADV` that also shifts the realized exit price (permanent impact moves the market against later marks).
4. **Default-on at scale.** Auto-enable impact when `starting_capital / median(adv20) > 0.5%` so large-capital runs cannot silently assume frictionless fills. Keep `MODE=PAPER`.
5. **POV schedule for the 2–5d hold.** Spread a parent order across the holding window at a fixed participation cap (e.g. 10% of ADV/day), charging Almgren temporary impact per child slice — this is also the bridge to G9 (execution parity).

---

## G5 — Regime detection: SMA(200) + VIX-z, laggy & whipsaw-prone **[ADDRESSED — residual ceiling]** (🟠 High)

**[FILE LOCATION]**
- `services/ui-api/routers/analytics.py:461-474` — `_regime_by_date`: risk-on iff benchmark level ≥ its own 200-day SMA. Entry gate only (never force-closes), wired at `simulate_portfolio:479-482`.
- `services/feature-service/feature_engine.py:324-358` — `compute_macro_features`: `nifty_regime ∈ {bull,bear,range}` from SMA50/200 crossover; `vix_zscore` over a 252d window.
- Fixed lookbacks everywhere: `compute_indicators` (ma50/ma200/rsi14/vol20/atr14, backtest_engine:106-126); advanced factors use 20/30/3-day windows (backtest_engine:151-208).

**[CREDIT — what landed]** A trailing, look-ahead-free benchmark regime gate exists and correctly suppresses only *new* entries while leaving open positions to their own stops — the right asymmetry for a 2–5d book. VIX-z is a legitimate complementary stress proxy.

**[THE RETAIL SHORTCUT — residual]**
SMA(200) on a benchmark lags by ~100 days at the midpoint of the average; for a 2–5 day strategy it flips long after the regime has already turned, and it whipsaws in choppy markets (price oscillating around the MA toggles the gate on/off). All indicator lookbacks are hard-coded constants, ignoring that volatility regimes compress/expand the *effective* memory of a series — a fixed 20-day window is too slow in calm regimes and too noisy in violent ones.

**[THE SOTA INSTITUTIONAL STANDARD]**
- **Hamilton (1989)** regime-switching / **Hidden Markov Models**: latent states (low-vol bull / high-vol bear) with transition probabilities, estimated by Baum-Welch on returns; gives a *probabilistic* risk-on weight, not a binary laggy flip.
- **Gaussian-Mixture vol clustering** on (realized vol, return skew) to label regimes without a price-MA.
- **Change-point detection** (Bayesian online change-point, Adams & MacKay 2007; or CUSUM) for fast structural-break alarms.
- **Adaptive lookbacks**: half-life tied to realized vol (e.g. Kaufman Adaptive MA / fractional-differencing memory per López de Prado 2018, ch. 5).

**[REMEDIATION BLUEPRINT]**
1. **Add an HMM regime classifier** (`services/feature-service`): 2–3 state Gaussian HMM (`hmmlearn`) on benchmark daily log-returns; emit `P(risk_on | data_≤T)` strictly from a forward-filtered (not smoothed) posterior so it is causal/look-ahead-free. Store `regime_prob` per date.
2. **Soft gate.** Replace the boolean `regime_ok_by_date` with a continuous exposure throttle: scale `base` allocation by `regime_prob` (e.g. risk-on prob 0.3 → 30% gross), so the system de-grosses smoothly instead of slamming entries off.
3. **Change-point overlay.** Run online change-point on realized vol; on an alarm, tighten `vol_target_pct` and `max_participation_pct` for N days.
4. **Adaptive ATR/MA windows.** Let the ATR window for the k×ATR stop scale with a vol half-life so stops widen in storms and tighten in calm — feed into `_SimContext.resolve` where `atr_pct_sig` is read.
5. Validate by comparing OOS Sharpe/MaxDD of SMA-gate vs HMM-soft-gate in `_core_wfo`.

---

# LAYER 3 — STATISTICAL RIGOR & FACTOR ISOLATION

## G3 — Multiple-testing / overfitting: no Deflated Sharpe, no PBO, no haircut (OPEN, 🔴 Critical)

**[FILE LOCATION]**
- `scripts/combinatorial_grid_search.py:341-355` — sweeps all 2⁶−1 = 63 filter combinations, `results.sort(key=lambda d: (d["sharpe"], d["calmar"]), reverse=True)`, reports the top by Sharpe. Only guard: `MIN_TRADES=100` (line 66, 204).
- `services/ui-api/routers/analytics.py:757-777` (`_pick_best`), `821-873` (per-window IS selection over `_candidate_combos`, ≤63) — selects the in-sample combo maximizing the raw objective; `efficiency = avg_oos/avg_is` (line 914) is reported but no statistical correction is applied to the *selected* number.

**[CREDIT — what landed]** The new `_core_wfo` is the single biggest improvement: it is genuine walk-forward (per-window IS optimization → freeze → embargoed OOS → stitched compounded OOS curve) and it *honestly reports* IS→OOS degradation, an efficiency ratio, and a full-period in-sample "overfit contrast." That structure already kills the worst form of data-snooping (reporting an in-sample fit as if it were live). My prior note that the WFO was fake (`_augment_wfo`) is now **stale and corrected** — `_augment_wfo` has been deleted.

**[THE RETAIL SHORTCUT — residual]**
When you optimize over 63 combinations (and the WFO does this *per window*), the best in-sample Sharpe is upward-biased purely by the number of trials — even on noise, max-of-63 Sharpes is high. The grid search ranks by raw Sharpe and presents the winner; the WFO selects the per-window winner by raw objective. Neither applies a **multiple-testing correction**, so the "best edge" is partly luck-of-the-draw and the reported Sharpe is statistically inflated. There is no estimate of the probability that the selected strategy is overfit.

**[THE SOTA INSTITUTIONAL STANDARD]**
- **Deflated Sharpe Ratio (DSR)** — Bailey & López de Prado (2014): adjusts the observed SR for the number of trials `N`, the variance of trial SRs, and non-normality (skew/kurtosis). `DSR = Z[(SR − SR₀)·√(T−1) / √(1 − γ₃·SR + (γ₄−1)/4·SR²)]` with `SR₀` the expected max SR under the null given `N` trials.
- **Probability of Backtest Overfitting (PBO)** — Bailey, Borwein, López de Prado, Zhu (2017) via Combinatorially-Symmetric Cross-Validation (CSCV): fraction of CSCV splits where the in-sample-best config ranks below median OOS.
- **Harvey & Liu (2015)** multiple-testing haircut: Bonferroni/Holm/BHY-adjusted t-stats for the number of factors tried.

**[REMEDIATION BLUEPRINT]**
1. **Deflate the grid-search winner.** In `combinatorial_grid_search.evaluate`/`main`, collect the SR of *all 63* combos, compute `SR₀(N=63)` and the trial-SR variance, and report **DSR** next to Sharpe in `combinatorial_backtest_results.md`. A combo with high SR but DSR≈0 is flagged as likely overfit.
2. **PBO via CSCV in the WFO.** After `_core_wfo`, run CSCV over the candidate combos and the OOS folds: report `pbo` in the `walk_forward` block. The UI (`BacktestPanel.tsx`) should show "PBO = 0.62 → 62% chance this config is overfit."
3. **Haircut the per-window selection.** In `_pick_best`, when `len(combos) > 1`, deflate each combo's objective by the expected-max-under-null before ranking, so the optimizer prefers a robust combo over a lucky one.
4. **Trial bookkeeping.** Log the cumulative number of distinct configs ever evaluated across a research session (persist a counter), so the haircut reflects the *true* search intensity, not just one run's 63.

---

## G6 — No factor attribution / α-vs-β deconstruction (OPEN, 🟠 High)

**[FILE LOCATION]**
- `services/ui-api/backtest_engine.py:620-636` — `beta_alpha`: a **single** market beta vs the equal-weight top-100 proxy + Jensen's α (rf=0). That is the *entire* risk-decomposition.
- `compute_market_relative` (backtest_engine:213-271) produces `corr_nifty_30` and sector-relative momentum, but no factor regression.
- Candidate ranking is a static large-cap tilt: `_simulate_window` sorts candidates by `mktcap_cr` desc and takes `head(max_stocks_per_day)` (analytics:565-567). The composite score is **not sector- or factor-neutralized**.
- Grep confirms: **no** Fama-French, Carhart, Barra, or cross-sectional factor regression anywhere in `services/`, `scripts/`, or `ui/`.

**[THE RETAIL SHORTCUT]**
The system reports a single CAPM beta and calls the residual "alpha." But a low-P/E + high-momentum + small-cap screen loads heavily on the **value, momentum, and size** factors; its returns are mostly *compensated factor risk*, not skill. Without multi-factor attribution you cannot tell whether the edge is genuine idiosyncratic α or repackaged β/SMB/HML/UMD. The `mktcap`-sort candidate selection additionally bakes in an explicit, unhedged size bet.

**[THE SOTA INSTITUTIONAL STANDARD]**
- **Fama & French (1992/1993)** 3-factor (MKT, SMB, HML) and **Carhart (1997)** 4-factor (+ UMD momentum): regress strategy excess returns on factor returns; the intercept is the *true* α, the slopes are the systematic exposures.
- **Barra-style multi-factor risk model** (Grinold & Kahn 2000): cross-sectional regression of returns on style + industry exposures each day; decompose portfolio variance into factor vs specific risk.
- **Sector/beta neutralization**: rank the composite score *within* sector and beta buckets so the bet is the residual signal, not the sector/size tilt.

**[REMEDIATION BLUEPRINT]**
1. **Build NSE factor returns** (offline, DuckDB): each day, form SMB (small−big mktcap terciles), HML (high−low book-to-market — needs PIT P/B from G1), UMD (winners−losers on 12-1 momentum), plus MKT = benchmark excess return. Store `factor_returns(date, MKT, SMB, HML, UMD)`.
2. **Attribution endpoint.** Add `factor_attribution(port_rets, factor_returns)` to `backtest_engine.py`: OLS `r_p = α + β_MKT·MKT + β_SMB·SMB + β_HML·HML + β_UMD·UMD + ε`; return annualized α (with t-stat), each loading, and R². Surface in `compute_metrics` alongside the existing single beta.
3. **Sector/beta-neutral selection.** In `_simulate_window`, replace the `mktcap_cr` sort with a within-sector (and within-beta-bucket) z-score of the composite factor, so candidates are picked on *residual* signal — directly attacks the unhedged size tilt.
4. **UI.** Add a "Factor Attribution" panel to `FactorDiagnosticStudio.tsx` showing the α t-stat and the factor-loading bar chart, so a strategy can be *proven* to have residual α rather than asserted.

---

# LAYER 3b — ML PIPELINE RIGOR

## G7 — Live ML trains on binary direction; triple-barrier + meta-labeling orphaned **[PARTIAL]** (🟠 High)

**[FILE LOCATION]**
- `services/ui-api/routers/ml_workspace.py:165-172` — training SQL joins `l.label_direction AS y` with `WHERE l.horizon_days = 5`. The model is `binary:logistic` on up/down (line 342).
- `ml_labels.label_barrier` **exists in DuckDB** (verified column present, populated by `feature_engine.build_triple_barrier_labels:271-319`) but is never selected.
- `scripts/ml_quant_pipeline.py` implements the **full** López de Prado stack — `TripleBarrierLabeler` (L98), `MetaLabeler` (L446), `PurgedKFoldCV` with embargo (L504), MDA/MDI feature selection (L575), Optuna for Sortino (L724) — **but** it runs on a synthetic `DataGenerator` (L48, random data) and is imported by **nothing** in `services/` or `ui/`. It is sophistication on the shelf.

**[CREDIT — what landed]** Triple-barrier labels are computed and stored; a complete CPCV/meta-label/Optuna pipeline exists and is correct in form.

**[THE RETAIL SHORTCUT — residual]**
A binary "will close be higher in 5 days" target ignores the *path* and the *asymmetric payoff* of a 2–5d swing: a trade that hits +2% on day 2 then closes flat is a win you'd actually book, but `label_direction` may score it 0. It also wastes the meta-labeling layer that would let a primary signal decide *whether to act* (bet sizing), which is where most of LdP's edge comes from. The production engine and the research pipeline are two disconnected worlds.

**[THE SOTA INSTITUTIONAL STANDARD]**
- **Triple-barrier labeling** + **meta-labeling** — López de Prado, *Advances in Financial Machine Learning* (2018), ch. 3: primary model predicts side, meta-model predicts whether to take the trade and how big.
- **Sample weighting by label uniqueness + sequential bootstrap** (AFML ch. 4) to handle overlapping 5-day labels.

**[REMEDIATION BLUEPRINT]**
1. **Switch the live target.** Add a `label_kind` request param to `TrainRequest` (`direction` | `barrier`); when `barrier`, train on `label_barrier ∈ {-1,0,+1}` (multiclass or sign) joined from `ml_labels`. The SQL already has the column.
2. **Wire meta-labeling.** Train a primary model (existing direction model) → generate signals → train a second XGBoost on `meta_label = 1{primary correct}` using the existing `MetaLabeler.create_meta_labels` logic ported from `ml_quant_pipeline.py` into a service module. The meta-model's probability becomes the bet-size input for G10/Kelly.
3. **Label uniqueness weights.** Compute concurrency-based sample weights (overlapping 5-day windows) per AFML 4.x and pass as `weight=` to `xgb.DMatrix` (the `weight_halflife_days` decay hook at ml_workspace:309-313 already plumbs sample weights — multiply the two).
4. **Promote `ml_quant_pipeline.py` off synthetic data.** Replace `DataGenerator` with the real DuckDB loader and expose its CPCV/Optuna as an offline "deep-tune" job whose winning hyperparameters feed the live desk.

## G8 — Live ML uses single chronological holdout + purge gap; no CPCV **[ADDRESSED — ceiling]** (🟡 Med)

**[FILE LOCATION]** `services/ui-api/routers/ml_workspace.py:192-212` (`_purged_split`), `286-302` (applied with fallbacks). Telemetry: `purge_applied`, `purged_rows`, `purge_gap_days` streamed (L328-333).

**[CREDIT]** A correct López de Prado **purge gap** (`label_horizon + embargo` trading days removed before the validation start) now prevents the overlapping-5d-label leakage at the train/valid seam — exactly the leak my prior audit flagged. Chronological, no-shuffle split is preserved. This is a real, verified fix.

**[RESIDUAL CEILING]** It is still a *single* OOS estimate (one most-recent slice). For a robust generalization estimate, institutional ML uses **Purged K-Fold / CSCV** (multiple purged folds) so the OOS metric has a distribution, not a point. **Blueprint:** port `PurgedKFoldCV` from `ml_quant_pipeline.py:504` into a service module and offer a "robust eval" toggle that reports mean ± std AUC/Gini across purged folds; reuse for the PBO computation in G3.

---

# LAYER 4 — INFRASTRUCTURE & UI INTEGRATION

## G9 — Execution is naive market-on-close; no order-book / partial fills / TWAP-VWAP-IS (OPEN, 🟠 High)

**[FILE LOCATION]**
- `services/execution-service/live_execution.py:611-660` — `translate_weights_to_orders`: `target_qty = int(target_value/price)`, emits one BUY/SELL `delta` at a single `price`. No order-book, no slicing.
- `:312-368` `_breeze_place_order` sends a single `order_type="market"` (or "limit") for the full quantity, day validity.
- `reconcile_positions` (:664-708) compares quantities only; there is **no slippage reconciliation** of realized fills vs the backtester's modeled impact.

**[CREDIT — what landed]** `MODE=PAPER` is the hard default (`get_engine`:930-938, `EXECUTION_MODE` env), the 2% daily-loss kill-switch is hardwired and cannot be disabled at runtime, all state mutation is `asyncio.Lock`-guarded, and there is a full SQLite audit trail with restart-restore. The safety envelope is institutional-grade.

**[THE RETAIL SHORTCUT — residual]**
Orders assume the entire parent quantity fills instantly at one price (`prices[symbol]`). Real fills are partial, walk the book, and incur slippage that scales with size — precisely the impact G4 models in the *backtest* but which is **not enforced in execution**, so the two diverge. There is no child-order scheduling (TWAP/VWAP/Implementation-Shortfall), no participation cap on the live order, and no post-trade slippage attribution to close the loop against the backtest.

**[THE SOTA INSTITUTIONAL STANDARD]**
- **Almgren & Chriss (2000)** Implementation Shortfall optimal trajectory; **Berkowitz/Logue/Noser (1988)** VWAP benchmark; TWAP/POV child-order scheduling.
- **Slippage reconciliation**: realized IS = (avg fill − arrival price)/arrival price, attributed and fed back to recalibrate the backtest `impact_coef` (G4).

**[REMEDIATION BLUEPRINT]**
1. **Child-order scheduler.** Add `schedule_children(parent_order, adv, horizon, style)` → list of (slice_qty, target_time) for TWAP (equal slices), VWAP (slice ∝ intraday volume curve), or POV (cap each slice at p%·ADV). For the 2–5d hold, spread entry over 1–2 sessions at ≤10% POV.
2. **Partial-fill state machine.** Extend `OrderRecord` with `filled_qty`, `avg_fill_price`, `status ∈ {NEW, PARTIAL, FILLED, CANCELLED}`; poll Breeze order status and accumulate fills.
3. **Slippage reconciliation.** On parent completion, compute IS vs arrival price; persist to a `slippage` table; nightly, regress realized slippage on `√(Q/ADV)·σ` to **recalibrate** the backtest `impact_coef` so the simulator and live converge (closes the G4 loop).
4. **Keep PAPER default.** Scheduler runs in PAPER (simulated child fills against historical/sim prices) until an explicit, manual LIVE opt-in.

## G10 — Kelly sizing & sector risk-checks orphaned from sizing path **[PARTIAL]** (🟡 Med)

**[FILE LOCATION]** `services/risk-service/position_sizer.py:10-46` (`kelly_fraction`, `fractional_kelly`), `risk_checks.py:34-49` (`check_sector_concentration`). Grep confirms **zero references** from `services/ui-api` or `services/execution-service`. Backtest sizing is equal-weight / vol-target (`simulate_portfolio:497-504`); execution caps flat at `MAX_POSITION_PCT=0.15` (live_execution:636).

**[CREDIT]** The backtest *did* gain its own sector cap (`max_sector_pct`, simulate_portfolio:512-517) and vol-target sizing — so the *concept* is now in the sim. **Residual:** it is a parallel re-implementation, not the shared risk-service logic, and Kelly is used nowhere. **Blueprint:** (a) feed the meta-model win-prob/payoff (G7) into `fractional_kelly` to set `base` allocation in `simulate_portfolio` as a sizing option; (b) have both backtest and execution call the *same* `risk_checks.run_all_checks` so paper and live enforce identical limits; (c) expose Kelly fraction as a UI sizing mode in `BacktestPanel.tsx`.

## G11 — Telemetry queue unbounded; daemon worker; booster-memory release **[ADDRESSED — ceiling]** (🟢 Low)

**[FILE LOCATION]** `services/ui-api/routers/ml_workspace.py:398-431` (`_stream` worker thread + `queue.Queue`), `217-243` (`_build_callback` returns `state.cancel.is_set()` → XGBoost stops at the round boundary). UI: `ui/components/MLEngineWorkspace.tsx:91-94` (`kill` calls `stopRun`, does **not** prematurely abort the fetch), `ui/lib/mlTraining.ts:streamTraining` (NDJSON reader loop).

**[CREDIT — what landed]** The kill-switch is correct and clean: a `threading.Event` observed by an XGBoost `TrainingCallback`, so cancellation is *cooperative* — the booster keeps everything trained so far, the partial model is saved to disk (`booster.save_model`, L375), the run ends `TERMINATED_BY_USER`, and the UI waits for that result rather than tearing the stream. Training runs in a worker thread; the FastAPI event loop is **not** blocked (the heavy work and the synchronous `queue.get()` generator both live off the request coroutine). The run registry is bounded (`_MAX_RUNS=32`, evicts finished runs). No torn state, no half-written model.

**[RESIDUAL CEILING]**
1. **Unbounded queue.** `queue.Queue()` (L399) has no maxsize. With a fast booster and a slow/stalled client (TCP backpressure), epoch events accumulate in memory. The reader loop in `mlTraining.ts` has no explicit backpressure beyond TCP. **Blueprint:** `queue.Queue(maxsize=1000)` and have the callback `put_nowait` with a drop-oldest policy for `epoch` frames (telemetry is loss-tolerant; `result`/`error` must never drop).
2. **Cancellation latency = one round.** `state.cancel` is only checked in `after_iteration`, so STOP waits for the current boosting round to finish. For deep trees on the full universe a round can take seconds; acceptable, but document it.
3. **Daemon-thread lifetime.** The worker is `daemon=True` (L420); on process shutdown it is killed abruptly. For a long-lived server this is fine (registry-bounded), but the booster's C++ memory is only released when the thread function returns — a client that disconnects mid-train still runs the booster to completion (no early stop on disconnect). **Blueprint:** also set `state.cancel` when the StreamingResponse is cancelled (client disconnect) so an abandoned run frees `xgboost` memory promptly.

---

## Prioritized remediation sequence

**Phase A — Validity (do first; everything else is meaningless on biased data).**
1. **G1** — PIT fundamentals (append-only `stock_metrics`, report-lag, `merge_asof` in backtest). Until then, treat every fundamental-filter result as look-ahead-tainted (the engine already flags it — honor the flag).
2. **G2** — Survivorship-free universe (PIT membership table + delisting returns; populate corp-action tables). Quantify the survivorship premium once.
3. **G3** — Deflated Sharpe + PBO on both the grid search and the WFO selection. Cheap, and it tells you which of the *current* "edges" survive multiple-testing.

**Phase B — Honest performance (after data is valid).**
4. **G6** — Fama-French/Carhart attribution + sector/beta-neutral candidate selection (proves α vs β).
5. **G4** — Endogenous Amihud/Kyle-calibrated impact, default-on at scale; temporary/permanent split.
6. **G7** — Switch live ML to triple-barrier + meta-labeling; wire `ml_quant_pipeline.py` onto real data.

**Phase C — Robustness & live parity.**
7. **G5** — HMM soft regime gate + adaptive lookbacks.
8. **G8** — Purged K-fold / CSCV robust eval (reuses G3 PBO machinery).
9. **G9** — Child-order scheduler + partial-fill state + slippage reconciliation (closes the G4 loop, gives backtest↔live parity).
10. **G10/G11** — Unify Kelly/risk-checks across sim+execution; bound the telemetry queue and free booster memory on disconnect.

---

### Verification ledger (every claim checked against source)
- MODE=PAPER intact: `backtest_engine.py:16`, `analytics.py:38`, `ml_workspace.py:44`, `live_execution.py` default `ExecutionMode.PAPER`. ✔ Not modified.
- No secrets hardcoded; ICICI creds read from env (`live_execution.py:297-299`). ✔
- WFO is genuine (per-window IS opt → embargo → OOS stitch): `analytics.py:780-959`, embargo `max(embargo_days, forward_days+2)` at L800; corroborated by `tests/test_wfo.py`. ✔ (corrects my prior `_augment_wfo` note)
- Impact/ADV/stops/sizing knobs opt-in, defaults equal-weight: `simulate_portfolio:364-378, 497-522`. ✔
- Purge gap in live ML: `ml_workspace.py:192-212, 286-302`. ✔
- Snapshot fundamentals (4 as_of_dates) and zero delistings: DuckDB queries run live this audit. ✔
- No DSR/PBO/Fama-French/HMM/Kyle/Amihud/Almgren anywhere: grep across `services/ scripts/ ui/` returned only docstring mentions (`impact_coef ≈ Almgren-style`) and the orphaned synthetic `ml_quant_pipeline.py`. ✔
- **No system code modified; nothing committed; only this report written.** ✔
