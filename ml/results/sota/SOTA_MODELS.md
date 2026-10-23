# SuryaDhana pilot: state-of-the-art challengers vs the champion

**Date:** 2026-10-19 · **From:** ML/DL modeling lead

**Code and outputs:** `ml/models/sota.py` writes to `ml/results/sota/`: harness-schema JSONs, `league_summary.json`, `exposures.json` and `train_log.txt`. Predictions go to `ml/results/preds/sota/`.

**Setup:** primary task `beat_mkt_20d`, seed 108, the league's folds and its 175,951 out-of-sample rows.

**Verdict: nothing beats the gradient-boosted champion.** No challenger cleared the bar fixed before any run: CV AUC ≥ 0.5364 (champion 0.5314 + 0.005) with every fold ≥ 0.50. The closest is a no-fit rank blend of three tree models, 0.0007 short. Both transformers and DLinear finish at the bottom.

## League

CV covers four monthly folds, Apr–Jul 2026. The holdout (Aug 3 → Sep 11) was never used to choose anything. Rank-IC is the per-date Spearman correlation of score against 20-day excess return. NW-t is a Newey-West (19-lag) t-stat; it corrects for overlapping 20-day windows and is the honest figure.

| model | #feat | CV AUC ± std | worst fold | holdout AUC (decile spread) | rank-IC CV, t / NW-t | train s/fold* | pass |
|---|---:|---|---:|---|---|---:|---|
| ensemble_rank (champion + lambdarank + catboost) | 10 | **0.5357 ± 0.0077** | **0.5236** | 0.5482 (+3.9%) | +0.065, 7.37 / **3.64** | 0 (no fit) | no (−0.0007) |
| *champion_ref = lgbm_fs_selected* | 10 | *0.5314 ± 0.0143* | *0.5069* | *0.5180 (−0.4%)* | *+0.057, 6.70 / 3.26* | *5* | *reference* |
| catboost_fixed600 (diagnostic) | 10 | 0.5299 ± 0.0120 | 0.5115 | 0.5231 (−0.2%) | +0.055, 6.04 / 3.51 | 69 | no |
| lgbm_lambdarank | 10 | 0.5293 ± 0.0243 | 0.4967 | 0.5661 (+6.0%) | +0.050, 6.37 / 2.13 | 56 | no |
| catboost (early-stopped) | 10 | 0.5260 ± 0.0193 | 0.4938 | 0.5096 (−0.2%) | +0.050, 4.16 / 2.02 | 18 | no |
| lgbm_huber | 10 | 0.5223 ± **0.0068** | 0.5128 | 0.5303 (+1.2%) | +0.046, 6.30 / 3.27 | 12 | no |
| cs_transformer (set attention) | 10 | 0.5197 ± 0.0348 | 0.4926 | 0.5010 (−0.4%) | +0.027, 1.87 / 0.70 | 595 | no |
| catboost_f51 | 51 | 0.5193 ± 0.0180 | 0.4888 | 0.5497 (+1.2%) | +0.037, 3.09 / 1.45 | 92 | no |
| lgbm_lambdarank_f51 | 51 | 0.5160 ± 0.0167 | 0.4943 | 0.5642 (+6.0%) | +0.029, 4.00 / 1.38 | 93 | no |
| catboost_es_logloss (superseded) | 10 | 0.5154 ± 0.0142 | 0.4938 | 0.5096 (−0.2%) | +0.034, 3.02 / 1.54 | 6 | no |
| patchtst_lite | 14 | 0.5143 ± 0.0442 | 0.4516 | 0.4480 (−1.9%) | +0.024, 1.65 / 0.61 | 334 | no |
| dlinear (sequence control) | 14 | 0.5103 ± 0.0394 | 0.4568 | 0.4605 (−4.2%) | +0.016, 1.09 / 0.41 | 72 | no |

\*Wall-clock was measured while other agents held the 4-core box at a load average of 10–18. Use it for relative cost only; idle-box times are roughly 2–5× lower.

## Why each model did or did not beat the champion

- **LambdaRank:** it wins April (0.562) and the holdout but drops below 0.50 in July. Its 2^g − 1 grade gains reward landing in the top return decile, which is mostly volatile names. Its score correlates +0.66 per date with `atr_pct`, against +0.03 for the champion. So its folds follow the sign of the volatility factor's IC (+0.095 Apr, −0.059 Jul, +0.10 holdout), not stock-specific skill. With 51 features it gets worse, as the classifier did.
- **Huber:** the most stable model here (std 0.007, every window ≥ 0.51), and its NW-t equals the champion's. Its AUC is lower because it forecasts return size, not the median crossing. With α = 0.9 above the ±0.30 clip, it is effectively least squares.
- **CatBoost:** early stopping on the time-ordered inner tail kept 43/79/0/186/5 trees, and Logloss stopping kept 0–1 trees on 4 of 5 folds. The tails straddle the March-2026 break: on two folds inner-val AUC never rose above 0.5. With the champion's protocol (fixed 600 trees), CatBoost ties LightGBM: 0.5299, floor 0.5115. The gap was the protocol, not the algorithm.
- **PatchTST-lite and DLinear:** both have nearly identical fold paths (April ≈ 0.45, July ≈ 0.57, holdout < 0.47), so attention adds about 0.004 AUC over a two-layer linear model. The 60-session window repeats trailing-return information the features already carry. Early stopping then locks in whichever regime filled the tail; inner-val AUC was about 0.60 on the pre-break Jan–Feb tail. Their scores are essentially a low-volatility, near-52-week-high bet: per date they correlate −0.52 with `atr_pct` and +0.59 to +0.64 with `dist_52w_high`. That is the mirror image of LambdaRank, hence weak in April and strong in July. This matches the pilot's GRU/LSTM.
- **Cross-sectional transformer:** fails. CV is 0.5197 ± 0.035, with April and May below 0.50 (0.493 and 0.493) and a big July (0.578): the same regime-bet profile as the sequence models. The holdout is a coin flip (0.501), and its rank-IC is not significant (NW-t 0.70). The label is already cross-sectional (beat the median) and the `cs_rank_*` features already normalise across stocks, so attention over about 1,450 names has little to add. Meanwhile 140–210 training dates, one optimiser step each, give it far more capacity than data. It hits the same early-stopping trap: on fold 2026-06 the inner-val AUC never exceeded 0.44. It ends up with the same low-volatility tilt as the sequence models (atr −0.59, 52-week-high +0.56).
- **ensemble_rank:** the best mean, floor, dispersion, holdout and NW-t in the study, with nothing fitted, yet still 0.0007 short. The gain is diversification. The champion and LambdaRank correlate only 0.26 per date, and their opposite volatility tilts offset each other across months.

## Why trees still win here

1. **Weak signal in a few slow features.** Per-date IC is about 0.05. Extra capacity (51 features, sequences, attention) mainly buys the ability to fit the train window's regime. Each challenger family collapsed onto a volatility factor: high-vol for LambdaRank, low-vol for the networks. The champion stays roughly vol-neutral (atr +0.03).
2. **Tiny effective sample.** There are 140–230 train dates per fold with overlapping 20-day labels, so only about 7–11 independent cross-sections. Most networks' best epoch fell between 1 and 5.
3. **A regime break against early stopping.** March 2026 flipped the volatility and momentum factors, so any validation tail spanning it misleads model selection. The champion's fixed 300 trees are immune; every early-stopped model here paid for it.

## What the 5-year run should carry

1. **lgbm_fs_selected, unchanged.** It has the best single-model CV with an above-0.50 floor and costs about 5 s per fold.
2. **ensemble_rank as a pre-registered challenger.** It is the per-date rank average of the champion, LambdaRank and CatBoost, with nothing to tune. Hold it to the same bar on the multi-year walk-forward, and fit its members with fixed tree budgets rather than early stopping on the tail.

**Drop:** both transformers, DLinear, the 51-feature variants, and Huber as a scorer (it can stay as an IC monitor). RL and the RNNs stay dropped.

## Protocol notes and deviations

- **Rows:** all models score the champion's rows. The 5% of test rows with fewer than 60 sessions of history are zero-padded (pad = train mean), not dropped.
- **Inner validation** is the last 15% of train rows (CatBoost) or dates (networks), with the 20 sessions before it purged from the inner-fit set.
- **Champion predictions** come from the post-fix `lgbm_fs_selected_clean` file. The frozen file still holds 11,728 rows from the phantom holiday-echo days. `champion_ref` reproduces the clean file exactly.
- **CatBoost** stops on inner-val AUC, the networks' metric, then refits on all train rows. The Logloss-stopped run is kept as `catboost_es_logloss`. `catboost_fixed600` was added as a diagnostic after the early-stopping failure, so it is not eligible for promotion.
- **Halving rule** (> 90 s/epoch), triggered by box contention:
  - `cs_transformer` took 67 s for its first epoch on the smallest fold. It ran at d_model 32, with each training step on a random 50% of the date's stocks; val/test use the full set.
  - `patchtst_lite` was projected at 164 s/epoch. It ran with a 60k sequence cap and d_model 32.
  - `dlinear` used the same 60k cap, so the comparison is like for like.
  - Epoch budgets were unchanged.
- **Transformer implementation:** fused SDPA attention without attention-probability dropout (dropout 0.2 elsewhere), pre-LN, gradient clipping at 1.0, and no RevIN, which would erase the level signal.
- **Missing data:** a channel that is entirely NaN in a train window (`mom_12_1` before March 2026) is zeroed.
- **Non-probability scores** (ranker, Huber, blend): Brier and acc@0.5 in their JSONs are not meaningful.
