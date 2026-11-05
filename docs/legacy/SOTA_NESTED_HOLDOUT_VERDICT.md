# SOTA Nested Walk-Forward-of-Search — Held-Out Confirmation Verdict

**Date:** 2026-06-20 · **Mode:** PAPER · **Branch:** `feature/backtest-lab-institutional`
**Script:** `scripts/sota_nested_holdout.py` · **Sidecars (untracked):** `sota_nested_holdout_results.{csv,json}`, `sota_nested_holdout_run.log`
**Engine (reused, never re-implemented):** `routers.analytics._core_wfo` / `_wfo_windows` / `_load_context` / `_auto_impact_status` · `backtest_engine.deflated_sharpe_ratio`
**Seed:** 42 · **DB:** `data/market.duckdb` (read-only) span `2021-05-17 → 2026-06-17`, 1,065,929 rows

---

## ONE-LINE VERDICT

**REJECTED.** The horizon near-miss candidate (`vol_adj_sector_alpha↑D10 / fd60 / N20 / risk_parity / forced Amihud`) is an **in-sample artifact of the 2022–2024 sub-period.** A mechanical re-search confined to a TRAIN portion independently re-crowned the *exact same cell*, but that train-winner **collapsed on the strictly-later, never-searched 2025-01-01 → 2026-06-17 held-out tail**: train-OOS Sharpe **1.45 → test-OOS Sharpe 0.08** (~18× degradation), NET CAGR **+11.82% → +0.30%**, alpha **−1.14%/yr**, **DSR@n=1 = 0.5502 (fails the 0.95 gate even with the multiple-testing denominator removed).**

---

## (a) Train/Test split + leak-safe boundary proof

| | TRAIN (search universe) | HELD-OUT TEST (scored once) |
|---|---|---|
| Span passed to engine | `2021-05-17 → 2024-12-31` | `2023-11-01 → 2026-06-17` (fd60) |
| First **scored** OOS bar | 2022-07-18 | **2025-01-01** |
| Last **scored** OOS bar | **2024-12-31** | 2026-06-17 |
| WFO windows (IS365/OOS90/emb62) | 10–11 | 6 |

**Boundary proof (logged, `GAP_ok=True` at both horizons):** train's last *scored* OOS bar = **2024-12-31**; test's first *scored* OOS bar = **2025-01-01**, separated by the engine's embargo (`max(7, fd+2)=62` at fd60). **No bar that the TRAIN search evaluated is ever scored by the TEST, and vice-versa.**

**On the test IS warm-up:** the test span starts `2023-11-01` so that its first *scored* OOS fold lands exactly at the cut+1. Its IS warm-up window therefore looks *back* into pre-cut data. This is admissible because the candidate is a **fixed decile screen, not a fitted model** — `candidate_filters=[]` ⇒ pure OOS stitch with **no per-window parameter estimation**, so the IS warm-up injects zero fitted information into the scored bars (it only seeds indicator lookbacks, which the engine pads 400d regardless). The *strict all-bar-non-overlap* alternative (test IS_start after train OOS_end) was rejected because it yields only **2** test windows — uselessly thin. We chose the 6-window eval-non-overlap design and flag the warm-up overlap honestly here.

**Why this cut:** fd60 + IS365 + embargo62 consumes ~427 calendar days at the front before the first OOS bar. Cutting at `2024-12-31` leaves the train search 10 credible windows (enough for a stable selection) and reserves ~1.5y of genuinely-unseen tail (6 windows) for the single confirmation. MODE=PAPER, DuckDB read-only, no look-ahead, no shuffle, no skipped WFO.

---

## (b) The TRAIN-winner (mechanical selection, no test access)

The discovery grid — **same logic as the prior horizon sweep**: 3 cohorts (`vol_adj_sector_alpha↑D10`, `sector_rel_mom↑D10`, `low-ATR↓D1`) × forward_days {40, 60} × N {5, 20}, long-only `_core_wfo`, risk_parity, forced Amihud — ran on the TRAIN span **only**. Winner picked by the single pre-declared rule: **argmax train-OOS annualized Sharpe**, tie-broken by train-OOS net CAGR.

| Train cell | windows | trades | NET % | GROSS % | Sharpe | Calmar | MaxDD % |
|---|---|---|---|---|---|---|---|
| **COH-A vol_adj_sector_alpha↑ fd60 N20** | 10 | 507 | **+11.82** | +13.23 | **1.45** | 1.59 | −7.5 |
| COH-B sector_rel_mom↑ fd60 N20 | 10 | 475 | +13.41 | +14.93 | 1.42 | 1.37 | −9.8 |
| COH-A vol_adj_sector_alpha↑ fd40 N20 | 11 | 719 | +8.37 | +12.48 | 1.10 | 0.73 | −11.5 |
| COH-B sector_rel_mom↑ fd40 N20 | 11 | 664 | +6.23 | +13.02 | 0.62 | 0.27 | −23.2 |
| COH-C low-ATR↓ fd40 N20 | 11 | 525 | +6.35 | +8.83 | 0.79 | 0.51 | −12.4 |
| COH-A vol_adj_sector_alpha↑ fd60 N5 | 10 | 120 | +4.10 | +4.65 | 0.71 | 0.87 | −4.7 |
| COH-C low-ATR↓ fd60 N20 | 10 | 387 | +4.23 | +5.86 | 0.61 | 0.28 | −15.4 |
| COH-B sector_rel_mom↑ fd60 N5 | 10 | 137 | +1.91 | +2.33 | 0.81 | 0.33 | −5.8 |
| COH-C low-ATR↓ fd40 N5 | 11 | 127 | +0.52 | +1.04 | 0.19 | 0.15 | −3.5 |
| COH-C low-ATR↓ fd60 N5 | 10 | 94 | −0.19 | +0.21 | −0.07 | 0.04 | −4.2 |
| COH-A vol_adj_sector_alpha↑ fd40 N5 | 11 | 179 | −1.74 | +2.92 | −0.24 | 0.09 | −19.2 |
| COH-B sector_rel_mom↑ fd40 N5 | 11 | 191 | −1.97 | +1.45 | −0.28 | 0.10 | −19.6 |

**TRAIN-WINNER = `COH-A vol_adj_sector_alpha↑D10, forward_days=60, N=20` — the EXACT SAME cell as the full-span near-miss candidate** (`stage1_winner_same_as_candidate = True`). The selection step is therefore independently corroborated: train data alone, with a fixed mechanical rule, re-discovers the candidate. The breadth pattern from UPDATE 5 also re-confirms (N=20 ≫ N=5 at fd≥40; fd60 ≫ fd40 for COH-A).

---

## (c) The TRAIN-winner on the HELD-OUT TEST tail (trial count = 1)

That one cell, run **once** through production `_core_wfo` on the strictly-later unseen span `2025-01-01 → 2026-06-17`:

| Metric | TRAIN (search) | **TEST (held-out, n=1)** |
|---|---|---|
| OOS windows | 10 | **6** |
| Trades | 507 | 312 |
| **NET CAGR** | +11.82% | **+0.30%** |
| GROSS-of-impact CAGR | +13.23% | +0.82% |
| **Sharpe (annual)** | **1.45** | **0.08** |
| Calmar | 1.59 | 0.03 |
| MaxDD | −7.5% | −10.05% |
| Alpha (annual) | (positive) | **−1.14%** |
| Turnover | 251%/yr | 396%/yr |
| Amihud impact drag | 1.41%/yr | 0.52%/yr |
| Amihud temp leg / perm leg | on / on | **on / on** |
| **DSR @ n=1** | — | **0.5502 → FAILS (gate 0.95)** |

**The signal itself evaporated — this is not an impact story.** Test GROSS-of-impact is only **+0.82%**; impact drag was a trivial 0.52%/yr. The cross-sectional edge that delivered Sharpe 1.45 on 2022–2024 simply is not present on 2025–2026. Sharpe degraded ~18×. DSR @ n=1 = **0.5502**, failing 0.95 **even though the multiple-testing denominator is removed** — i.e. this candidate fails the *easiest possible* statistical bar on genuinely unseen data.

**Contrast with UPDATE 6:** on full-span data the candidate's own daily returns gave DSR @ n=1 = **0.9948**. That number was an artifact of the train-rich full span. On the held-out tail alone, DSR @ n=1 = **0.5502**. The 0.995 was never out-of-sample evidence — it was the in-sample period's Sharpe wearing an n=1 label.

---

## (d) Coverage credibility

- **Train:** 10–11 windows per cell across the grid — adequate for a stable mechanical selection.
- **Test:** **6 windows** (~1.5y tail at OOS=90). This is **thin** (< 8 folds), so on coverage grounds alone a *positive* read here would be graded INCONCLUSIVE, not certified.
- **But the test did not produce a positive read** — it produced a **clear failure** (Sharpe 0.08, DSR 0.55, GROSS +0.82%). A thin sample is far more than enough to *reject*: the candidate would have had to show ~Sharpe ≥ 1.5 on these 6 windows to clear DSR@n=1, and it showed 0.08. The thinness caveat protects against over-claiming a *win*; it does not rescue a *loss*. **Verdict stands as REJECTED, not INCONCLUSIVE.**

---

## (e) Residual analyst-knowledge caveat (stated honestly)

I (the analyst) already knew from the prior full-span sweep that `vol_adj_sector_alpha` won, and a prior sweep's OOS track *had* seen the 2025–2026 test-tail dates. **This is therefore NOT a pristine never-seen holdout.** The protection applied was **mechanical discipline**: the grid was fixed (same cohorts/horizons/breadths as the discovery sweep), the winner was chosen by a single pre-declared rule (`argmax train-OOS Sharpe`), and there was no human thumb on the scale toward the known answer — the selection code never reads a test bar. A *clean corroboration* would have been "strong corroboration, not pristine confirmation." **However, the result is a REJECTION**, and analyst foreknowledge can only bias a study *toward* confirming the known answer, never *toward* a false rejection. So the caveat **strengthens** the negative verdict: despite every incentive and prior knowledge pointing at COH-A/fd60/N20, the candidate still failed clean on unseen data.

---

## (f) Thesis answers

**(a) Is there a mathematically sound combination of existing filters yielding positive OOS alpha?**
**No — and the program's single live candidate is now falsified.** The longer-horizon `vol_adj_sector_alpha↑D10/fd60/N20` cell — the only impact-survivable, gross-positive, Sharpe~1.0 result the entire six-axis program ever produced — was driven by 2022–2024 in-sample luck. On a properly nested, leak-safe, strictly-later held-out tail it delivers Sharpe 0.08 / alpha −1.14% / DSR@n=1 0.55. The 5-position-bottleneck program is now **closed with a clean negative**: seven distinct levers tested (single-factor decile, PCA-orthogonal multi-factor × breadth, regime timing, long-short inversion, prob_up-primary, longer horizon, and now nested held-out confirmation); none yields certifiable positive OOS alpha.

**(b) Minimum portfolio breadth N to survive Amihud impact?**
N=20 *was* necessary (and sufficient on impact grounds) to lift the candidate's gross sign and shrink the impact wall — train data re-confirmed N=20 ≫ N=5 at fd≥40. **But breadth is now moot for this candidate: at N=20 on the held-out tail, impact was a trivial 0.52%/yr and the strategy still earned ~0% because the *signal* was absent.** Impact was never the binding constraint on the tail — signal persistence was. There is no N that rescues a cross-sectional edge that does not exist out-of-sample.

---

## Self-verification

- Re-read results JSON: split dates, winner identity, test metrics, DSR, coverage all consistent with the run log.
- `GAP_ok=True` at both horizons → no scored bar shared across the train/test boundary.
- Amihud temp + permanent legs both `True` on the test cell (Pillar B live); `sizing_mode=risk_parity` (Pillar C) on every cell.
- DSR @ n=1 = 0.5502 computed from the test-tail daily OOS returns with `n_eff=1` (multiple-testing denominator deliberately removed) — the candidate fails the gate at its most generous.
- friction 15bps floor, embargo = `max(7, fd+2)`, DuckDB read-only, seed 42, no look-ahead, no shuffle, no skipped WFO.
