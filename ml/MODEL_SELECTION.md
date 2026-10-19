# SuryaDhana Pilot — Model Selection Memo

**Date:** 2026-10-15 · **From:** evaluation (quant-eval) · **Companion:** `ml/results/model_selection.json`, built by `python3 -m ml.eval_aggregate` (seed 108)

**Decision: carry LightGBM on the 10-feature selected subset to the 5-year run, with L2 logistic regression retained as the interpretable benchmark. Drop RL and the RNNs.**

## Correction after the red-team audit (2026-10-19)

The audit (`ml/results/audit/AUDIT.md`) found the pipeline clean — labels and
features recompute exactly from raw data, no leakage, shuffled labels score
0.500 ± 0.001 — but the champion's CV AUC of 0.531 is partly in-sample: its 10
features and k were chosen on the same four CV test months. Re-running the
identical selection with only pre-fold data gives **CV AUC 0.5132**, level with
`lr_l2_clean` (0.517) and with random 10-feature subsets (0.513 ± 0.006); on
the untouched holdout the champion (0.518) was no better than the one-feature
momentum rule (0.531). The phrase "only model above chance at 95%" was wrong
by the program's own bootstrap (random forest and `lr_l2_clean` also clear it
on CV), and "≥ 0.50 in all five windows" fails under honest selection (April
0.494). The honest reading of the pilot is the audit's wording:

> In a six-month pilot, a LightGBM model on ten price and delivery features
> ranked NSE stocks by 20-day relative performance slightly better than chance:
> AUC 0.518 on an untouched six-week holdout, and about 0.513 across four
> monthly test folds when its features are chosen without seeing those months.
> The signal is not a data or code artefact. But it is small, rests on five
> monthly windows, and on the holdout it was no better than a one-feature
> momentum rule. It justifies the five-year walk-forward test; it is not
> evidence of a tradable edge.

The model-family ranking below still stands as a comparison run under one
protocol; the absolute numbers are validation scores, not estimates of live
performance. The 5-year run nests feature selection inside each training
window, purges on each label's actual exit date and reports 20-session block
bootstraps.

## What we ran

Six-month pilot on the NSE EOD universe (~2,100 tickers, 507k rows), purged walk-forward with a 22-session embargo: four monthly CV folds (Apr–Jul 2026) plus one untouched holdout (Aug 1 → mid-Sep 2026). Primary task `beat_mkt_20d`: will a stock beat the universe median over the next 20 sessions (base rate 0.500 by construction, regime-robust). Headline metric ROC AUC; economics via score-decile spreads of 20-day excess return. The question: **which algorithm earns the 5-year run** — not whether the edge is already tradable.

## League table — primary task (frozen runs; `_clean` rows = post-fix re-validation)

| Model | Family | #feat | CV AUC (±std) | Min fold | Holdout AUC | Holdout decile spread |
|---|---|---:|---|---:|---:|---:|
| **lgbm_fs_selected** | GBM, selected feats | 10 | **0.5307 ± 0.018** | **0.5014** | 0.5219 | +0.86% |
| &nbsp;&nbsp;└ re-validated, cleaned data | | 10 | 0.5314 ± 0.014 | 0.5069 | 0.5180 | −0.40% |
| random_forest | trees | 51 | 0.5167 ± 0.027 | 0.4710 | 0.5328 | +1.62% |
| lr_l2 (≈ l1 ≈ elastic) | linear | 51 | 0.5126 ± 0.035 | 0.4721 | 0.5227 | −2.33% |
| &nbsp;&nbsp;└ re-validated, cleaned data | | 51 | 0.5171 ± 0.031 | 0.4873 | 0.5265 | −2.41% |
| rl_reinforce | RL | 13 | 0.5085 ± 0.022 | 0.4829 | 0.5680 | +4.47% |
| decision_tree | trees | 51 | 0.5058 ± 0.014 | 0.4884 | 0.5358 | +1.02% |
| lightgbm (all features) | trees | 51 | 0.5044 ± 0.023 | 0.4806 | 0.5627 | +2.87% |
| mlp | deep | 51 | 0.5025 ± 0.017 | 0.4809 | 0.5377 | +2.62% |
| xgboost | trees | 51 | 0.5023 ± 0.020 | 0.4795 | 0.5646 | +3.49% |
| lstm | deep | 14 | 0.5018 ± 0.023 | 0.4822 | 0.5415 | +0.83% |
| baseline_mom (momentum floor) | baseline | 1 | 0.4934 ± 0.006 | 0.4874 | 0.5298 | +2.82% |
| gru | deep | 14 | 0.4889 ± 0.011 | 0.4725 | 0.5467 | +0.34% |

Feature-count ablation: top-10 beats top-5/15/20/30 (CV 0.5307 vs 0.5125–0.5231). **Secondary task `up_5d`** is regime-exposed (monthly base rate 0.37–0.72), its CV means inflated by the one-sided 2026-04 fold in every family (linear 0.553 → 0.514 ex-April) — sanity check only; the champion still leads it ex-April (0.533).

## CV vs holdout: how we adjudicated

12 of 13 candidates scored **better** on the single holdout than on CV (mean +3.2 AUC pts), and the two views rank models in near-opposite order (Spearman −0.60): RF is best-CV among trees, full-feature XGB/LGBM best-holdout (~0.56). The paired bootstrap shows both directions are "significant" under date-resampling — so the disagreement is **regime-window dependence, not sampling noise**. Four monthly folds (including the adversarial April) outvote one friendly 6-week window used once: algorithm choice rests on CV mean + worst-fold floor, with the holdout as a no-catastrophe check. The champion is the only model whose holdout ≈ CV (−0.9pt vs +1 to +6pts for everyone else) — the least window-sensitive model in the league.

## Significance (date-block bootstrap: test dates resampled within folds, B=1000, seed 108, models paired on identical draws)

- **Above chance on pooled CV at 95%:** only lgbm_fs_selected — 0.5299, CI [0.5216, 0.5388], P(>0.5)=1.000 (clean rerun 0.5311, CI [0.5226, 0.5399]) — plus random_forest (0.5138, CI [0.5025, 0.5255], P=0.993) and lr_l2_clean (P=0.981). Everything else — full-feature XGB/LGBM (P=0.61/0.65), MLP, LSTM, RL, decision tree, frozen lr_l2 (P=0.90) — is **not distinguishable from coin-flipping on CV**; GRU and the cleaned baseline sit significantly *below* 0.5 (frozen baseline P(>0.5)=0.04 — raw momentum rank was mildly contrarian in this sample). On the holdout every model clears 0.5 (P=1.000): the friendly-window effect in one line.
- **Champion vs lr_l2:** paired CV delta +0.0181, CI [0.0111, 0.0256] — significant under date-resampling — but a **dead heat on the holdout** (−0.0008, P=0.46). With only 4 regime-months the bootstrap cannot capture fold-level regime risk, so the CV gap is suggestive, not settled; the recommendation leans on stability, cost and headroom, not this delta alone.
- **Champion, paired CV:** vs baseline_mom +0.0373 [0.0257, 0.0490]; vs RF +0.0140 [0.0101, 0.0176]; vs XGB +0.0284 [0.0195, 0.0365] — but **−0.0426 on holdout** (the contradiction above).
- Mid-table differences of ~0.01–0.02 sit inside the noise (individual CIs are ±0.009–0.012 wide); do not read order into them.

## Stability and economics

lgbm_fs_selected is the **only candidate never below AUC 0.50 in any of the five OOS windows** (worst 0.5014; cleaned 0.5069); every alternative dips below chance at least once (RF 0.471, lr_l2 0.472, XGB 0.480, …). For scale-up, a 0.50 floor with a modest mean beats a spikier profile. Its top-decile mean 20-day **excess** return is positive in all five windows (+0.96, +4.58, +1.02, +2.82, +2.12%); decile spread positive in 3/4 folds plus holdout. The lr_l2 anchor's holdout spread is negative (−2.3%: its score extremes invert economically) and it sat below 0.50 in 2 of 4 folds — a benchmark, not a scorer.

## Recommendation

1. **LightGBM on the 10-feature selected subset** (long momentum + delivery block + atr_pct + dist_52w_high + inverted cs_rank_mom_20): best CV mean, best stability after cleaning, only ≥0.50-everywhere model, smallest CV↔holdout gap, all-window positive top-decile excess, native missing-value handling for the early-history NaNs at 5y, cheap (~32s per protocol run).
2. **lr_l2 (C=0.01)** as the interpretable benchmark/sanity layer: near-zero cost, per-1σ coefficients for drift monitoring, dead heat with the champion on the holdout.

**Revisit at 5y if:** full-feature XGB/LGBM beat the 10-feature subset on the multi-year walk-forward *mean* (their holdout showing — 0.5646/0.5627, +3.5/+2.9pt spreads — is one window, not evidence); the re-run feature selection changes the subset; or the champion's mildly negative cleaned-holdout spread (−0.4pt) persists.

**Dropped:** **RL** — CV 0.5085, REINFORCE failed to beat its own init on 2/4 folds, and its own portfolio sim loses to the free mom20 heuristic out-of-sample. **RNNs (GRU/LSTM)** — at or below chance on CV (0.489/0.502): a 20-session temporal view adds nothing at this scale, and the MLP (~3 AUC pts under LGBM) shows the deep stack isn't paying either. **decision_tree** — dominated by its ensembles. **lr_l1/elastic** — identical to lr_l2 to three decimals.

## Data-quality event (resolved)

Mid-bake-off we found **12 phantom "holiday-echo" days** (2.9% of sessions): the archive mirror re-served the prior session's bhavcopy on 2026 NSE holidays. The ingest was fixed (holiday calendar + duplicate-day guard), the dataset rebuilt, and champion + anchors re-validated: lgbm_fs_selected 0.5307→0.5314 (std 0.018→0.014), lr_l2 0.513→0.517, baseline_mom 0.493→0.491 — **ranking unchanged**. League numbers above remain the frozen pre-fix runs; the `_clean` rows are the robustness check.

## Must be re-tested at 5-year scale

1. **Feature selection re-run** — ret_252d/mom_12_1/dist_200dma are 58/58/21% NaN in the pilot; the top-10 subset may change once they populate.
2. **Full-feature GBM vs 10-feature subset** on ~60 monthly folds — resolves the CV/holdout contradiction.
3. **Significance re-run** — the same date-block bootstrap over thousands of test dates makes the champion-vs-linear gap decidable.
4. **Regime coverage** — the ≥0.50 fold floor and decile-spread sign across full bull/bear cycles; decile economics net of costs and turnover.
5. **up_5d** — re-evaluate with its NaN-label fix, stratified by regime, before trusting any number from it.
6. **Ingest hygiene** — extend the holiday-echo scan and corporate-action handling to the full 5y history (prices unadjusted; y_clean mask re-audit).

## Feature study (follow-up)

A feature EDA and an A/B of 23 engineered features found no case for rebuilding the feature set before the 5-year run. Every engineered variant scored below the champion on clean data (best 0.5268 against 0.5314; the pass mark fixed in advance was 0.5364). The EDA did find a regime break in March 2026, when 25 of 40 features had their worst month at once. After it the volatility features changed sign and the delivery signal shrank from a monthly IC of +0.107 to +0.020. That makes item 1 above (feature re-selection on the full history) mandatory and adds a delivery-IC alert to production monitoring. Details are in `ml/report/feature_study.html` and the plan changes in `ml/SCALE_UP.md`.
