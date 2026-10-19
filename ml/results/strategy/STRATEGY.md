# SuryaDhana — Strategy Verdict: is there a promising ROC?

**Date:** 2026-10-19 · **From:** portfolio quant · **Built by:** `python3 -m ml.strategy_backtest` (seed 108, ~15 s) · **Companions:** `strategy.json` (scorer → basket → cost → window), `champion_monthly.csv`, `strategy_flat.csv`, `tables.md` (every table for every window)

## Verdict

**Not yet.** The long-only books mostly earn the market's return. Net of 20 bps per side, the champion's top decile made **+30.6%** annualised; the passive equal-weight (EW) universe made **+26.1%**. The model adds **+4.2%/yr**, which is not distinguishable from zero (IR 0.99, 95% CI [−2.4, +4.3]; PSR 0.75; DSR 0.08). In the holdout, the only window no selection decision touched, the champion **trailed** EW at **−2.1%/yr**. No scorer × basket cell survives the Deflated Sharpe test.

**Recommendation: commit no capital.** Carry the champion's **liquid-tercile top decile, long-only** into the 5-year walk-forward as a pre-registered paper portfolio, and drop everything under "Bifurcate".

## How it was measured

- **Engine.** 20 overlapping tranches, one rebalanced per session; entry at the open of t+1 and exit at the open of t+21, the exact label window.
- **Marks and labels.** Exact daily open-to-open mark-to-market, which reproduces `y_raw_20d` on 99.995% of rows. Every model is scored on the clean dataset's labels.
- **Costs.** Netted against the tranche being replaced; turnover is the fraction of the basket replaced. NSE delivery costs about **15–25 bps per side** for liquid names (STT alone is 10 bps); 40 bps is the stress case.
- **Weighting.** Daily statistics are weighted by exposure (fixed 1/20 capital per tranche). The naive fully-invested average gives the first and last tranches 3.6× weight, and here would flip the champion's active return from +4.2% to −5.3%/yr.

**Two things inflate the project's usual metrics.** First, the EW universe itself beats the universe median by **+1.78% per 20 days (~22%/yr)**. That is skew, not skill, and it is why every top-decile book shows a 78–92% hit rate against the median. Second, selection leakage: the champion's features were chosen on all four CV test folds, and RF/XGB/MLP/LR were tuned on Apr–May. **Only the holdout is clean for the champion**; the momentum heuristic and `baseline_mom` are clean everywhere.

## Headline — combined OOS (113 signal dates, 1 Apr → 11 Sep 2026), 20 bps/side

**Long top decile (~155 names).** Ann. return = mean 20-session tranche net return × 252/20. Sharpe uses rf = 5.5%; IR is against the EW universe; CIs are 95% month-block bootstraps (B = 1000).

| scorer | ann. return | Sharpe [CI] | max DD | active vs EW | IR [CI] | turnover | hit vs median | hit vs EW |
|---|---:|---|---:|---:|---|---:|---:|---:|
| **lgbm_fs_selected** (champion) | +30.6% | 1.93 [−0.63, 4.63] | −3.1% | **+4.2%** | 0.99 [−2.36, 4.34] | 80% | 91% | 56% |
| lgbm_fs_selected_clean | +27.6% | 1.66 [−0.91, 4.23] | −3.6% | +1.3% | 0.30 [−2.87, 3.96] | 78% | 83% | 50% |
| random_forest | +30.6% | 1.80 [0.09, 3.93] | −3.7% | +4.7% | 0.96 [−2.38, 4.77] | 77% | 92% | 69% |
| xgboost | +16.8% | 0.98 [−0.64, 3.59] | −3.6% | −9.0% | −1.50 [−3.81, 0.59] | 65% | 78% | 42% |
| lr_l2 | +9.0% | 0.36 [−1.81, 2.38] | −4.0% | −17.0% | −2.55 [−4.04, −1.43] | 50% | 81% | 15% |
| baseline_mom | +36.9% | 1.59 [0.01, 3.23] | −6.6% | +11.5% | 1.57 [−1.20, 3.64] | 86% | 88% | 66% |
| rl_reinforce | +30.9% | 1.55 [0.43, 3.25] | −4.6% | +5.0% | 1.03 [−2.11, 4.39] | 86% | 82% | 52% |
| mlp | +19.5% | 1.09 [−0.18, 3.09] | −3.6% | −6.1% | −1.17 [−3.61, 1.14] | 76% | 81% | 44% |
| ensemble_rank3 | +25.3% | 1.61 [−0.61, 3.93] | −3.4% | −0.8% | −0.17 [−2.90, 3.00] | 74% | 92% | 54% |
| heuristic_mom20 (free) | +36.8% | 1.59 [0.02, 3.25] | −6.4% | +11.4% | 1.53 [−1.20, 3.56] | 86% | 84% | 67% |
| *EW universe (passive)* | +26.1% | 1.38 [−0.31, 3.22] | −4.8% | — | — | 5% | — | — |

The free momentum heuristic leads on raw active return, but with daily beta 1.28. Its beta-adjusted alpha (+4.0%) is below the champion's (+8.6%; the champion's beta of 0.83 is stable across daily, Dimson and 20-day estimates). No model clearly beats momentum, so momentum is the floor to clear.

**Long–short decile ($1 long / $1 short).**

| scorer | net ann. | Sharpe [CI] | max DD | hit (net > 0) |
|---|---:|---|---:|---:|
| lgbm_fs_selected | +15.8% | 2.17 [−1.86, 6.60] | −4.0% | 65% |
| random_forest | +11.4% | 1.27 [−1.76, 5.62] | −5.6% | 87% |
| rl_reinforce | +12.7% | 1.51 [−1.80, 4.31] | −4.4% | 57% |
| heuristic_mom20 | +1.9% | 0.19 [−2.28, 1.99] | −5.0% | 58% |
| lr_l2 | −21.6% | −1.82 [−3.26, −0.60] | −9.6% | 35% |

## Capacity-restricted book (liquid tercile, `cs_rank_turnover ≥ 0.67`, ~51 names)

The champion keeps essentially all of its net edge in the liquid tercile, with 4.4× the capacity. Capacity = the AUM at which the 10th-percentile entering name trades 5% of its 20-day ADV.

| book (20 bps) | ann. return | active vs EW-liquid | IR | capacity | breakeven cost/side |
|---|---:|---:|---:|---:|---:|
| champion, full-universe top decile | +30.6% | +4.2% | 0.99 | ₹257 cr (35% of names < ₹5 cr ADV) | ~41 bps |
| **champion, liquid top decile** | +24.2% | **+4.0%** (CV +7.1%, holdout −4.5%) | 0.72 [−1.62, 2.57] | **₹1,129 cr** (median name ADV ₹101 cr) | ~39 bps |

## Windows and regimes

The window split is also the regime split: all four CV months were up months (by the sign of the median `y_raw_20d`), and both holdout months were down months.

- **Champion, active vs EW:** CV +6.5%/yr (IR 1.42); holdout −2.1%/yr (IR −0.63; the CI is uninformative with only 3 month blocks). Per 20 days, net active is +0.54% in up months and −0.13% in down months; the long–short book is +1.59% and +0.30%.
- **Rankings flip between windows.** The holdout leaders were RL (+33.6%/yr), momentum (+28.3%), RF (+17.4%) and XGB (+8.7%); in CV they were −5.4%, +5.3%, +0.1% and −15.4%. This is the memo's AUC contradiction again: one regime change cannot separate skill from regime fit.
- **Adversarial months.** April was adversarial: 7 of 10 scorers had negative IC and a negative long–short spread. The March-2026 inversion carried into April signals and cost the champion −0.9% per 20 days. July was borderline (5 of 10 negative IC).

## Deflated Sharpe (Bailey & López de Prado)

- **N = 96 trials:** 60 grid cells (10 scorers × 6 baskets), 6 diagnostics (up_5d and 5-day holds), and 30 program configurations on this label. The 30 is a floor: 26 are logged, and the tuning grids add more.
- **Inputs:** T = 120 effective daily observations (132 raw days); daily Sharpe, skew and kurtosis of the net 20 bps series; SR0 (expected maximum under the null) = 3.09 annualised.

| strategy (combined, 20 bps) | SR (ann.) | skew | kurt | PSR(SR*=0) | DSR | days needed for PSR 95% |
|---|---:|---:|---:|---:|---:|---:|
| best cell: rl_reinforce, liquid long–short | 2.67 | +0.43 | 4.22 | 0.970 | **0.383** | 92 |
| champion top decile, active vs EW | 0.99 | −0.19 | 4.27 | 0.751 | **0.076** | 705 |
| best absolute long-only (champion top decile, net − rf) | 1.93 | +0.01 | 5.03 | 0.906 | 0.655 | 187 |
| passive EW universe (net − rf) | 1.38 | −0.12 | 5.14 | 0.827 | 0.511 | 365 |

**No strategy's Sharpe survives.** Even at N = 2, the best cell's DSR is only 0.92. A tranche-level cross-check (about 5.7 independent 20-day bets) gives PSR 0.84 and DSR 0.30.

## Bifurcate (drop)

1. **Short leg.** On paper the champion's short leg adds more than its long leg (+0.88% vs +0.36% per 20 days, net). But overnight NSE shorts need SLB or stock futures, which cover only the ~200 F&O names; this bottom decile is mostly small caps; borrow fees are unmodelled; and for momentum the short leg loses (−0.71%). Revisit later as an F&O-futures overlay.
2. **Illiquid tail.** 36% of the champion's top decile is in the illiquid tercile, which caps capacity at ₹257 cr at true costs well above 20 bps. The liquid book keeps the same edge with 4.4× the capacity.
3. **Top-20 books.** Every supervised model's top-20 book loses to EW (champion −10.5%/yr), and capacity is about ₹28 cr.
4. **Models that do not beat EW net of 20 bps:** lr_l2 (significantly negative; keep it only as a drift monitor), xgboost, mlp, and ensemble_rank3 (lr_l2 drags the rank average down).
5. **up_5d label.** Its native 5-day book nets −0.1%/yr: rebalancing every 5 days at 54% turnover costs about 11%/yr, and its close-to-close label enters at the signal bar. Its scores held for 20 days did better (+9.8%/yr), but that is one more trial, not evidence.
6. **RL stays dropped.** Its biggest numbers all come from the 30 holdout dates (liquid long–short +7.9%/yr in CV vs +85%/yr in the holdout), and its DSR is 0.38.

## Honest confidence statement

The sample is 5.5 months of signals: about 6 independent 20-day bets, one regime change sitting exactly on the CV/holdout boundary, and a single clean window for the champion. At its observed IR, the champion needs about 705 trading days (~2.8 years) of track record to reach PSR 95%. What does look solid is the cost headroom (breakeven about 39–41 bps per side against a realistic 15–25) and capacity (about ₹1,100 cr in the liquid book). That is grounds to keep researching, not to deploy.

**Before the 5-year run,** `SCALE_UP.md` gate 3 ("top-decile excess positive") should be re-stated against the **EW universe**, not the median, and a DSR ≥ 0.95 gate added.

## Per-month table — champion top-decile long (from `champion_monthly.csv`; 20-session means per tranche)

| signal month | window | state | adversarial | tranches | median 20d | EW 20d | basket gross | net excess vs median @10 / 20 / 40 bps | net active vs EW @20 | hit vs EW | mean IC | turnover |
|---|---|---|---|---:|---:|---:|---:|---|---:|---:|---:|---:|
| 2026-04 | cv | up | yes | 20 | +3.91% | +5.82% | +5.27% | +1.18 / +1.01 / +0.66% | −0.89% | 45% | +0.027 | n/a* |
| 2026-05 | cv | up | no | 19 | +0.51% | +2.47% | +5.31% | +4.62 / +4.45 / +4.10% | +2.48% | 100% | +0.101 | 84% |
| 2026-06 | cv | up | no | 21 | +1.71% | +3.14% | +2.85% | +0.99 / +0.83 / +0.51% | −0.60% | 14% | +0.054 | 81% |
| 2026-07 | cv | up | borderline | 23 | +0.26% | +1.82% | +3.35% | +2.94 / +2.78 / +2.46% | +1.21% | 74% | +0.068 | 73% |
| 2026-08 | holdout | down | no | 21 | −2.60% | −0.55% | +0.09% | +2.53 / +2.37 / +2.04% | +0.32% | 71% | +0.071 | 82% |
| 2026-09 | holdout | down | no | 9 | −4.72% | −2.87% | −3.74% | +0.83 / +0.67 / +0.37% | −1.18% | 0% | +0.013 | 78% |

\*April's tranches have no predecessor in the sample, so costs use the median steady-state turnover. Net excess against the median is positive in all six months; net active against the EW universe is positive in only three.
