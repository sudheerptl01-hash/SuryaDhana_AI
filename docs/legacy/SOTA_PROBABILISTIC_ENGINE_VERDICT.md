# SOTA PROBABILISTIC / HMM RETURN-ENGINE VERDICT

**Study:** `probabilistic_return_engine_prob_up_primary`
**Date:** 2026-06-18  · **Mode:** PAPER · **DB:** `data/market.duckdb` (read-only) · **Seed:** 42 · **Capital:** ₹1 Cr
**Scripts:** `sota_probabilistic_engine_search.py` → `sota_probabilistic_engine_results.{json,csv}`, `sota_probabilistic_engine_run.log`
**Status:** ❌ **CLEAN NEGATIVE — 0 / 24 cells clear DSR > 0.95 with positive OOS alpha.**

---

## 1. Approach chosen + mechanism (why distinct from the 4 exhausted axes)

Four axes over the 27-factor **decile** library are already exhausted (single-factor screen,
orthogonal multi-factor × breadth, time-series regime-timing GATE, dollar/beta-neutral
long-short — all fail DSR > 0.95; binding wall = Amihud market impact ≈ 0.10 %/bar). Every one
of those **selects cross-sectionally on the same decile factors**.

This study tests the **last genuinely distinct return ENGINE**: the **ML `prob_up` propensity as the
PRIMARY selector**, not a screen — rank/select the book directly by the leak-safe out-of-sample
XGBoost P(up over next 5 d). Three coupled directions were exercised in one matrix:

| Direction | Mechanism | How wired | Distinct from prior axes? |
|---|---|---|---|
| **1. `prob_up` as PRIMARY** | Admit/rank names by holdout propensity itself (`prob>=0.50`, `prob>=0.55`, top-decile) | base `prob_up` filter + `selection=sector_neutral, selection_factor=prob_up` | **Yes** — new information source (model posterior), not a decile factor |
| **2. HMM regime-CONDITIONAL** | Inferred causal 2-state Gaussian-HMM P(bull) varies behavior by state | `regime_filter=True, regime_model=hmm` → `regime_scale_by_date` soft throttle | Partly — reuses validated HMM machinery; conditions the prob_up book, not a decile screen |
| **3. Probabilistic sizing** | P(bull) posterior scales new-position notional ∈ [0,1] each bar (fractional-Kelly-like exposure control) | engine `regime_scale` soft channel + `sizing_mode=risk_parity` | Partly — sizing/gating overlay on the prob_up primary |

**Reused, not re-implemented:** production `_core_wfo` / `_core_backtest`, `_wfo_windows`, the
validated causal `gaussian_hmm_regime` (via `_hmm_regime_by_date`), the Amihud impact stack
(`impact_coef`/`amihud_coef`), and risk-parity inverse-vol sizing. No look-ahead, no shuffle, no
skipped WFO.

**Architectural finding (bounds Direction 2/3):** the engine exposes the HMM state through exactly
**two** channels — a hard boolean gate (`regime_ok_by_date`, exhausted by the regime-timing
verdict) and a soft P(bull) size throttle (`regime_scale_by_date`, exercised here as HMM-SOFT).
There is **no hook for regime-conditional COHORT selection** (state-switched `selection_factor`).
In this engine, "regime selects different behavior" therefore reduces to "regime selects different
*size* or *blocks entries*" — and the gross-of-impact result below proves no such overlay can
rescue the signal, because the overlays only ever *reduce* exposure to an edge that is negative
gross.

---

## 2. MEASURED leak-safe `prob_up` coverage span — and whether it is sufficient

The engine echoes point-in-time propensity provenance per cell. **Measured, not assumed:**

- **Leak-safe `prob_up` span:** `2025-06-02 → 2026-06-04` (~1 year), **ONE frozen model**.
- **`propensity_pit = True`**, **coverage = 82.0 %**, **`propensity_coverage_start = 2025-06-02`** (echoed in every pre-flight).
- **WFO alignment:** windows are sized so the **first OOS bar == 2025-06-02 == coverage start**; every scored OOS bar lies inside the leak-safe span. No non-PIT score is ever used OOS.

**Sufficiency:** ~1 year of leak-safe OOS with **9 stitched WFO windows** (IS=120 d / OOS=45 d /
embargo=7 d) is **thin but adequate for a directional verdict** — it is enough to reject (the result
is overwhelmingly negative with effect sizes far outside noise), though too thin to *certify a
positive* edge had one appeared. The honest scope is therefore: **a positive finding here would
have required out-of-window confirmation; a negative finding is conclusive within the valid
window.** It is conclusive.

---

## 3. Experiment design

| Knob | Value | Rationale |
|---|---|---|
| Prob filters | `prob>=0.50`, `prob>=0.55`, `prob-top-decile` | admit-threshold sweep on the primary |
| Regime variants | `OFF`, `HMM-SOFT` (P(bull) throttle) | isolates the HMM-conditional contribution |
| Breadth grid N | 10, 20, 30, 50 | breadth-vs-impact transition (5-pos trap → wide book) |
| Sizing | `risk_parity` (inverse-vol) — STRICTLY ON every cell | Pillar C |
| Impact | Amihud forced explicit (`impact_coef=amihud_coef=1.0`, `max_participation=10 %`) at N≥20; auto-Amihud at N=10 (pre-flight proves which fires) | Pillar B — IMPACT IS THE WALL |
| Friction floor | 15.0 bps (CLAUDE.md hard rule); Amihud is ADDITIVE on top | cost realism |
| WFO | IS=120 d / OOS=45 d / embargo=7 d, 9 windows | longer OOS blocks ⇒ fewer rebalances |
| **DSR trial count** | **n_eff = 24** (3 × 2 × 4 = ALL cells), deflated | honest multiple-testing correction |
| DSR gate | **0.95** · CAGR gate > 0.0 % | survivor definition |

**Turnover / impact-drag attribution (corrected this run):** the core backtest charges impact
*inside* NAV (`eff_return = net_return − impact_pct`, `backtest_engine.py:901`), so reported CAGR is
already net. The per-cell **turnover** and **impact-drag** columns are reconstructed from the
per-trade `impact_pct` × `capital_allocated` records the engine actually emits (capital-weighted,
annualized, scaled for the 1000-trade surface cap). They **attribute** the cost already paid — they
do not re-charge it.

---

## 4. MEASURED results — full 24-cell OOS matrix (net of 15 bps friction + Amihud + inverse-vol)

Benchmark (equal-weight) OOS total return **+11.0 %**. Every cell: 9 WFO windows.

| prob | regime | N | CAGR % | MaxDD % | Sharpe | Calmar | Turn %/yr | Impact %/yr | study-DSR |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| prob-top-dec | HMM-SOFT | 10 | **−4.17** | −5.00 | −3.81 | 0.83 | 2338 | 0.42 | 7e-19 |
| prob>=0.55 | HMM-SOFT | 10 | −4.54 | −5.45 | −4.16 | 0.83 | 2360 | 0.42 | 3e-24 |
| prob-top-dec | OFF | 10 | −5.17 | −6.21 | −3.78 | 0.83 | 3129 | 0.66 | 2e-13 |
| prob>=0.55 | HMM-SOFT | 20 | −5.18 | −6.23 | −3.89 | 0.83 | 2782 | 0.80 | 8e-11 |
| prob>=0.50 | HMM-SOFT | 10 | −5.62 | −8.12 | −1.96 | 0.69 | 2193 | 1.12 | 3e-14 |
| prob>=0.55 | OFF | 10 | −5.72 | −6.86 | −4.32 | 0.83 | 3192 | 0.65 | 8e-18 |
| prob>=0.55 | OFF | 20 | −5.82 | −7.19 | −2.97 | 0.81 | 3915 | 1.29 | 9e-08 |
| prob>=0.50 | HMM-SOFT | 20 | −5.95 | −8.93 | −1.98 | 0.67 | 2723 | 1.13 | 3e-12 |
| prob>=0.55 | HMM-SOFT | 30 | −5.99 | −7.52 | −3.20 | 0.80 | 2860 | 0.68 | 3e-08 |
| prob>=0.55 | OFF | 30 | −6.07 | −9.36 | −2.02 | 0.65 | 4448 | 1.49 | 2e-05 |
| prob-top-dec | OFF | 30 | −6.08 | −9.45 | −1.96 | 0.64 | 4334 | 1.29 | 2e-05 |
| prob-top-dec | HMM-SOFT | 20 | −6.16 | −7.43 | −3.93 | 0.83 | 2758 | 0.75 | 5e-15 |
| prob-top-dec | HMM-SOFT | 30 | −6.61 | −8.06 | −3.32 | 0.82 | 2763 | 0.60 | 9e-10 |
| prob-top-dec | OFF | 20 | −6.61 | −8.19 | −3.04 | 0.81 | 3861 | 1.15 | 6e-09 |
| prob>=0.50 | OFF | 10 | −6.63 | −9.45 | −2.03 | 0.70 | 2971 | 1.42 | 9e-14 |
| prob>=0.50 | OFF | 20 | −6.80 | −10.13 | −1.90 | 0.67 | 3835 | 1.59 | 6e-10 |
| prob>=0.50 | OFF | 30 | −6.93 | −10.45 | −1.61 | 0.66 | 4392 | 2.02 | 2e-06 |
| prob>=0.50 | HMM-SOFT | 30 | −7.42 | −10.81 | −2.24 | 0.69 | 2855 | 1.24 | 4e-11 |
| prob>=0.55 | OFF | 50 | −7.84 | −12.94 | −1.62 | 0.61 | 5120 | 2.52 | 8e-05 |
| prob>=0.50 | OFF | 50 | −7.87 | −12.54 | −1.41 | 0.63 | 5044 | **3.50** | 5e-05 |
| prob>=0.50 | HMM-SOFT | 50 | −8.19 | −12.01 | −2.00 | 0.68 | 2494 | 1.79 | 2e-07 |
| prob-top-dec | OFF | 50 | −8.29 | −14.30 | −1.59 | 0.58 | 4905 | 2.30 | 1e-04 |
| prob>=0.55 | HMM-SOFT | 50 | −8.75 | −11.32 | −2.95 | 0.77 | 2509 | 0.81 | 8e-08 |
| prob-top-dec | HMM-SOFT | 50 | −9.31 | −11.95 | −2.98 | 0.78 | 2343 | 0.63 | 2e-08 |

**Max study-DSR over all 24 cells = 0.0001** (gate 0.95). **Survivors = 0.**

### 4a. The decisive number — GROSS-of-impact signal sign

Adding the realized Amihud drag back into CAGR isolates the **raw `prob_up` signal before any
impact**:

> **Best GROSS-of-impact OOS CAGR across all 24 cells = −3.75 %** (`prob-top-dec | HMM-SOFT | N=10`),
> vs benchmark **+11.0 %**.

The propensity signal is **negative gross of cost**. Impact only deepens the loss — it is **not the
cause** for this engine.

### 4b. The HMM conditioning provably bit (Direction 2/3 measured, not asserted)

Matched OFF→HMM-SOFT pairs show the P(bull) throttle is **non-degenerate**: it cut turnover
**25–52 %** and roughly **halved impact drag** (e.g. `prob>=0.50 | N=50`: impact 3.50 % → 1.79 %;
turnover 5044 % → 2494 %). Yet OOS CAGR stayed negative and at high N often *worsened* — the throttle
correctly reduces exposure, but reducing exposure to a gross-negative edge cannot manufacture alpha.

---

## 5. VERDICT

**(a) Does any probabilistic / HMM approach clear DSR > 0.95 with positive OOS alpha?**
**No. 0 / 24 cells.** Max study-DSR = 0.0001 vs the 0.95 gate; every cell is negative OOS
(−4.17 % to −9.31 % CAGR) against a +11.0 % benchmark.

**(b) Minimal config if yes:** N/A — no survivor.

**(c) Precise reason for the negative (signal vs impact vs regime):**
- **Primary cause = the propensity signal has no positive OOS edge in this window.** The best cohort
  is **−3.75 % CAGR GROSS of all impact**. This is a *different* failure mode from the decile axes
  (where gross was ~flat and impact was the wall): here the signal itself is OOS-negative, so impact
  is a secondary aggravator, not the binding constraint.
- **The impact wall is still real and correctly scaled** (0.42 %–3.50 %/yr; rising with N as more
  notional is deployed, falling under HMM-SOFT as the throttle cuts turnover). The prob_up engine's
  5-day horizon forces brutal turnover (2200–5100 %/yr ≈ 22–51× book replacement), so impact bites
  hard — but even zero impact leaves the strategy losing.
- **No regime-dependence rescue.** The causal HMM split is non-degenerate and demonstrably moved
  cost (turnover −25–52 %), but never moved the *sign* of the edge. Direction 2 (regime-conditional
  behavior) and Direction 3 (probabilistic sizing / meta-labeling) can only ever *reduce* exposure;
  they cannot create a positive edge from a gross-negative primary. And the engine has no
  regime-conditional-cohort hook, so the only untested form of Direction 2 is architecturally
  out of scope for this engine without a bespoke split-stitch harness — which the gross-negative
  result renders pointless to build.

**Bottom line:** the **probabilistic / HMM return-engine axis is exhausted and CLEAN NEGATIVE.** The
last distinct lever (ML propensity as primary) does not carry positive OOS information in the
leak-safe window, before or after the institutional impact penalty. Combined with the four prior
verdicts, **no axis over the current factor + propensity stack produces a DSR>0.95 positive OOS
strategy.** The indicated next move is *new information* (alternative-data signals, longer-horizon
or fundamentally-driven labels that lower turnover, or a propensity model retrained on a longer
leak-safe span) — not another recombination of the existing signals.

---

## 6. Reproducibility & hygiene

- Scripts on disk (repo root, **unstaged, not committed, not pushed**):
  `sota_probabilistic_engine_search.py`, `sota_probabilistic_engine_results.json`,
  `sota_probabilistic_engine_results.csv`, `sota_probabilistic_engine_run.log`, this verdict.
- MODE=PAPER, DuckDB read-only, seed=42, no secrets hardcoded.
- DSR deflated against **n_eff = 24** (every cell). Honest trial count, not just winners.
- No look-ahead (PIT propensity, fundamentals PIT), no shuffle, no skipped WFO, no fabricated metrics.
