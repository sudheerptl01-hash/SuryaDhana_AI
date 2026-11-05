# SOTA Combinatorial Verdict — Orthogonal Multi-Factor Breadth Study

**Status:** COMPLETE · **Verdict:** CLEAN NEGATIVE (no surviving edge) · **Date:** 2026-06-18
**Mode:** PAPER · **DB:** read-only `data/market.duckdb` · **Capital:** ₹1,00,00,000 (₹1 Cr)
**Seed:** 42 (deterministic; least-bad cell re-run reproduces to the basis point)
**OOS span:** 2021-05-17 → 2026-06-17 · **WFO:** rolling IS=365d → embargoed OOS=90d · **17 OOS windows / cell**
**Friction:** 15.0 bps floor + **additive** Amihud impact (√-law temporary + permanent + ADV cap) · **Sizing:** inverse-vol (`risk_parity`)

---

## 1. Executive Verdict (the thesis, answered)

> **(a) Is there a mathematically sound combination of existing filters yielding positive OOS alpha?**
> **NO.** Across the full 12-cell search (3 orthogonal intersections × 4 breadths N∈{5,10,20,30}),
> **zero cells** produce positive OOS CAGR. The *least-bad* cell loses **−21.84%/yr** (ORTHO-A, N=5).
> Every cell has a **negative OOS Sharpe** (range −1.28 to −3.20), so the study-level **Deflated
> Sharpe Ratio is 0.0000 for all 12 cells** — none clears, or comes remotely close to, the DSR > 0.95 gate.

> **(b) What is the exact minimum portfolio breadth N required to survive the institutional (Amihud) impact penalty?**
> **No finite N survives.** Breadth is not the missing lever for these factors. Widening the book
> 5 → 10 → 20 → 30 **does not flip the sign** of OOS alpha for any combo; in two of three combos breadth
> makes the bleed *worse* at N=10 before partially mean-reverting, and in all three the curve **saturates**
> at N≈20 (N=20 and N=30 are numerically identical — the orthogonal decile screen simply does not yield
> 30 distinct qualifying names on most bars, so the 20th-name book and the 30th-name book are the same book).
> The Amihud penalty is *not* the binding constraint here: the signals are **negative gross of nothing** —
> they lose money on **price**, long before impact cost is debited.

**Bottom line:** The 5-position book is **not** a concentration trap for these factors. Concentration is
not destroying a latent breadth edge — **there is no edge to destroy.** This extends, and does not
contradict, the prior finding that no single factor beats the 5-position book OOS: the same verdict now
holds for orthogonally-constructed multi-factor intersections across the full breadth spectrum.

---

## 2. Method Integrity Ledger (anti-curve-fit attestation)

| Guard | Status | Evidence |
|---|---|---|
| Pillar B — auto-Amihud (`impact_coef=None`) ACTIVE every cell | ✅ 12/12 | `impact_active=true` in all 12 rows of `sota_alpha_search_results.json` |
| → full auto-stack fired (N=5, N=10) | ✅ 6/6 | `impact_full_stack_auto=true`, `auto_participation_pct=10.0` |
| → auto-calibrator stood down at low per-slot notional (N=20, N=30) → explicit Amihud forced | ✅ 6/6 | `impact_full_stack_auto=false` + documented `forced_explicit` fallback in run log |
| Pillar C — inverse-vol sizing (`sizing_mode="risk_parity"`) every cell | ✅ 12/12 | `build_req()` wires `sizing_mode=SIZING_MODE` on every request (script L141) |
| No OOS leakage — selection in-sample only | ✅ | `candidate_filters=[]` ⇒ pure OOS stitch, no per-window re-selection (script L144) |
| Honest multiple-testing denominator | ✅ | study-DSR deflated with `n_eff=12.0` (every cell counted, not just survivors) on all rows |
| Full WFO depth | ✅ | `n_windows=17` on all 12 cells |
| Determinism | ✅ | seed=42; least-bad cell (ORTHO-A N=5) re-run reproduces −21.84% / −66.44% / Sharpe −2.67 / DSR 0.0000 |
| Clean execution | ✅ | zero tracebacks / NaN / errors in `sota_phase2_run.log` |

**Note on the Pillar-B dynamic (this is the thesis, observed):** per-slot notional = CAPITAL / N.
At N=5 each slot is ₹20 L and trips the auto-Amihud trigger (per-position notional / median-ADV > 0.005)
→ full √-law stack fires at 10% participation. At N=20/30 each slot is ≤ ₹5 L, falls *below* the ADV
trigger, so the auto-calibrator correctly judges per-name impact negligible and stands down — at which
point the script's fallback **forces an explicit Amihud penalty** so impact is *never silently zero*.
Impact is therefore debited in **every** cell; it simply shifts from the auto-leg to the explicit-leg as
the book widens. This is exactly the "as N grows the per-name penalty shrinks" behaviour the mandate
required — and it is *not* what kills these strategies.

---

## 3. PHASE TRANSITION MATRIX — OOS CAGR & MaxDD as the book shifts 5 → 10 → 20 → 30

Net of 15 bps + Amihud impact + inverse-vol sizing, ₹1 Cr, 17 OOS windows. **All values OOS.**

### 3a. OOS CAGR (%) — the sign never transitions to positive

| Combo (orthogonal axes) | N=5 | N=10 | N=20 | N=30 | Breadth verdict |
|---|---:|---:|---:|---:|---|
| **ORTHO-A** · atr14%↓D1 ∩ VolAdjSectAlpha↑D10 | **−21.84** | −31.26 | −28.43 | −28.44 | worsens 5→10, saturates ≥20 |
| **ORTHO-B** · corr_nifty30↓D1 ∩ beta_resid_5d↑D10 | −43.88 | −54.90 | −47.62 | −47.62 | worsens 5→10, saturates ≥20 |
| **ORTHO-C** · corr_nifty30↓D1 ∩ squeeze_ratio↓D1 ∩ beta_resid_5d↑D10 | −59.26 | −61.16 | −53.56 | −53.56 | worst combo, saturates ≥20 |

**No phase transition from negative → positive OOS alpha occurs anywhere in the 5→30 sweep.**
The least-negative point of the *entire surface* is ORTHO-A at **N=5 (−21.84%)** — i.e. the **narrowest**
book of the best combo is the *least bad*, the exact opposite of the "breadth recovers alpha" hypothesis.

### 3b. OOS MaxDD (%) — drawdown deepens with breadth, then saturates

| Combo | N=5 | N=10 | N=20 | N=30 |
|---|---:|---:|---:|---:|
| ORTHO-A | −66.44 | −80.88 | −77.61 | −77.62 |
| ORTHO-B | −91.92 | −96.85 | −93.95 | −93.95 |
| ORTHO-C | −97.97 | −98.35 | −96.43 | −96.43 |

Every cell breaches the −20% hard emergency-stop in live trading; these books are catastrophic on a
walk-forward basis. The N=20 ≡ N=30 identity in both CAGR and MaxDD (and in `total_trades`:
ORTHO-A 2481≈2483, ORTHO-B 2140=2140, ORTHO-C 707=707) is the **breadth-saturation signature** — the
orthogonal triple in particular admits only ~700 trades over 17 windows, so a 30-slot book can never fill
past ~20 names and the extra capacity is inert.

### 3c. Full metric grid (per cell)

| Combo | N | CAGR% | MaxDD% | Calmar | Sharpe | Sortino | Win% | PF | Trades | α_ann% | β | study-DSR | Impact |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|:--:|
| ORTHO-A | 5 | −21.84 | −66.44 | 0.330 | −2.67 | −3.03 | 29.5 | 0.53 | 1157 | −26.77 | 0.123 | 0.000 | ON |
| ORTHO-A | 10 | −31.26 | −80.88 | 0.390 | −3.20 | −3.57 | 29.4 | 0.54 | 2119 | −40.04 | 0.157 | 0.000 | ON |
| ORTHO-A | 20 | −28.43 | −77.61 | 0.370 | −2.80 | −3.22 | 31.2 | 0.67 | 2481 | −36.14 | 0.164 | 0.000 | ON |
| ORTHO-A | 30 | −28.44 | −77.62 | 0.370 | −2.80 | −3.22 | 31.2 | 0.67 | 2483 | −36.14 | 0.164 | 0.000 | ON |
| ORTHO-B | 5 | −43.88 | −91.92 | 0.480 | −2.63 | −3.14 | 37.6 | 0.59 | 1049 | −57.76 | 0.112 | 0.000 | ON |
| ORTHO-B | 10 | −54.90 | −96.85 | 0.570 | −2.84 | −3.36 | 36.5 | 0.57 | 1840 | −79.33 | 0.167 | 0.000 | ON |
| ORTHO-B | 20 | −47.62 | −93.95 | 0.510 | −2.31 | −2.82 | 37.6 | 0.65 | 2140 | −64.79 | 0.181 | 0.000 | ON |
| ORTHO-B | 30 | −47.62 | −93.95 | 0.510 | −2.31 | −2.82 | 37.6 | 0.65 | 2140 | −64.79 | 0.181 | 0.000 | ON |
| ORTHO-C | 5 | −59.26 | −97.97 | 0.600 | −1.55 | −1.56 | 29.2 | 0.29 | 665 | −73.15 | 0.125 | 0.000 | ON |
| ORTHO-C | 10 | −61.16 | −98.35 | 0.620 | −1.65 | −1.66 | 27.7 | 0.27 | 703 | −77.98 | 0.128 | 0.000 | ON |
| ORTHO-C | 20 | −53.56 | −96.43 | 0.560 | −1.28 | −1.29 | 30.6 | 0.39 | 707 | −60.46 | 0.124 | 0.000 | ON |
| ORTHO-C | 30 | −53.56 | −96.43 | 0.560 | −1.28 | −1.29 | 30.6 | 0.39 | 707 | −60.46 | 0.124 | 0.000 | ON |

> **Calmar caveat — DO NOT misread the 0.33–0.62 Calmar values as positive.** The WFO engine reports
> Calmar as |CAGR| / |MaxDD| (a magnitude ratio); with *negative* CAGR these are **negative-return**
> ratios, not edge. The benchmark returned **+109% to +122%** over the same OOS span, so every cell is
> a deep *negative-alpha* book (α_ann −27% to −80%). Calmar is reported for completeness but is **gated
> out by the DSR and CAGR filters** and carries no positive signal here.

---

## 4. Pareto Verdict — maximize Calmar **subject to DSR > 0.95**

**Hard gate:** a candidate is admissible only if (study-DSR > 0.95 **AND** OOS CAGR > 0).

| Gate | Cells passing |
|---|---|
| study-DSR > 0.95 | **0 / 12** |
| OOS CAGR > 0 | **0 / 12** |
| **Joint (Pareto-admissible)** | **0 / 12** |

**The Pareto front is empty.** There is no point on the (Calmar, return) frontier that satisfies the DSR
constraint, so no candidate can be reported as an edge. Per the anti-curve-fit mandate, **every cell is
REJECTED regardless of raw return** — and here even raw return is negative, so the rejection is doubly
clean. No cell is promoted; no edge is claimed.

**Rejected-but-recorded (so they are never re-explored):** all 12 cells. The least-bad, ORTHO-A @ N=5
(CAGR −21.84%, study-DSR 0.000), is recorded as the *floor* of the search surface, **not** as a survivor.

---

## 5. Why the math says NO — the mathematical reason for the negative result

1. **Orthogonality bought independence, not edge.** Phase 1 (PCA over 9 candidate signals, 936,192
   bar-rows) confirmed the combos span genuinely distinct principal axes — ORTHO-C in particular spans
   **PC1** (cross-sectional alpha/momentum cluster: vol_adj_sector_alpha +0.48, sector_rel_mom +0.48,
   rsi +0.47, beta_resid +0.32), **PC2** (volatility: atr% +0.71, squeeze +0.43), and **PC4**
   (compression/decoupling: squeeze +0.77, corr_nifty +0.61), with all pairwise |ρ| < 0.06. The cumulative
   explained variance of the top 4 PCs is **79.8%** (PC1 41.8%, PC2 14.3%, PC3 13.0%, PC4 10.7%).
   Orthogonality is a property of the *feature geometry* — it guarantees the axes carry **independent
   information**, but says nothing about whether that information has a **positive sign** on forward
   returns. Compounding independent **noise** (or independent *negative* signal) does not manufacture alpha;
   it compounds the loss. Each combo paired a "defensive" tail with an "offensive" tail under the prior
   that the product would be drawdown-controlled growth — the WFO falsified that prior: the *intersection*
   of these decile tails selects names that **systematically underperformed** the benchmark by 27–80%/yr.

2. **Over-conditioning collapse (the more orthogonal axes you stack, the worse it gets).** ORTHO-C, the
   *cleanest* 3-way orthogonal triple, is the **worst** performer (−59% at N=5, PF 0.29). Intersecting
   three independent decile tails shrinks the eligible set to ~700 trades over 5 years — a tiny, structurally
   homogeneous cohort (short-vol, low-beta-correlation, residual-momentum names) that bled hard through the
   2022–2026 regime. Adding orthogonal *constraints* monotonically reduced breadth and worsened OOS return:
   the degrees of freedom consumed by the third filter bought negative marginal value.

3. **Breadth cannot rescue a negative-mean signal.** Widening N lowers per-name idiosyncratic variance
   (and per-name Amihud cost), but it averages toward the **population mean of the screened cohort** — and
   that mean is **negative**. So breadth converges the book *toward* its (losing) expected value rather than
   away from it. Mathematically, if E[r | screen] < benchmark, no amount of diversification within the
   screen produces positive alpha; it only tightens the distribution around the loss. The N=20≡N=30
   saturation makes the ceiling explicit: the screen is breadth-starved, so the lever is mechanically capped.

4. **Impact cost is not the binding constraint.** Because the strategies are negative on **price**, the
   Amihud/inverse-vol machinery — though fully active in all 12 cells — is second-order here. The question
   "what minimum N survives impact?" has no answer because **no N survives the gross signal**, before impact
   is ever debited. Reporting an impact-crossover N would be meaningless.

**A clean negative result is a valid, valuable verdict:** it closes the orthogonal-intersection ×
breadth-sweep hypothesis with rigor, conserves research budget, and redirects the search away from the
existing decile-filter library (which is now exhausted at both the single-factor and orthogonal-multi-factor
levels) toward fundamentally different signal families.

---

## 6. Reproduce

```bash
/Users/sudheer/Desktop/jupyter_env/bin/python scripts/sota_alpha_search.py
# emits sota_alpha_search_results.{csv,json} at repo root; seed=42, deterministic.
# Phase-1 inputs: scripts/sota_phase1_orthogonality.py -> sota_phase1_orthogonality.json
```

**Artifacts (repo root):**
- `sota_alpha_search_results.json` / `.csv` — the 12-cell matrix (machine-readable)
- `sota_phase1_orthogonality.json` — PCA EVR, correlation matrix, orthogonal pairs
- `sota_phase2_run.log` — full run trace incl. per-cell Pillar-B activation status
- `scripts/sota_alpha_search.py` — Phase-2 solver (typed, config-driven, seeded)

---
*Engine reuse: `routers.analytics._core_wfo` (WFO), `_auto_impact_status` (Pillar B proof),
`backtest_engine.deflated_sharpe_ratio` (DSR). No engine logic re-implemented.*
