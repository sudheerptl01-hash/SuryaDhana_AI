# Label study: which label should SuryaDhana model?

**Date:** 2026-10-19 · **From:** label-design quant · **Script:** `python3 -m ml.label_study` (seed 108, OMP_NUM_THREADS=2)
**Companions (this folder):** `TABLES.md` (generated), `ic_matrix.json/.csv` (+ `_t_wide`, `_mean_wide`), `auc_matrix.json/.csv`, `label_summary.json`, `label_variants.json`, `composite_econ.json`, `model_level.json`, harness JSONs `lgbm_lbl_*`. Rebuilt labels: `ml/results/preds/label_study/label_variants.parquet`.

## Verdict

1. **Do the features predict the labels?** In-sample, yes, but weakly. The best significant feature's mean monthly IC is 0.05–0.08 at 1–20 days (always a delivery feature) and 0.10 at 40 days (dist_52w_high). The mean |IC| across all 40 features is 0.02–0.04. Predictability falls steadily with horizon: 21–22 of 40 features pass BH q<0.05 at 1 day, but only 4–5 at 20 days. At 40 days none survives a correction for overlapping windows. The honest test is to select features on the first 8 months and score them on the rest. Out of sample, the IC is +0.05 at 1–2 days (t 2.8–4.2), +0.03 at 5 days (t ≈ 1), and around zero or negative from 10 to 20 days. The cause is the March-2026 regime break, when the low-vol and quality features that dominated 2025 inverted. One pillar survives everywhere: **delivery** (deliv_pct, deliv_pct_z_20, deliv_pct_sma_20). It ranks in the top 5 at every horizon and for both entry conventions, and it holds up with ETFs excluded (t 4.5 at 20 days ex-ETF).
2. **Most predictable by the model:** the excess (ex>0) label, at any horizon. The model's rank-IC is flat at about 0.044 from 3 to 20 days and 0.052 at 2 days (Newey-West t 4.8). CV AUC sits between 0.518 and 0.524 at every horizon. The worst fold (Apr-2026) is below 0.50 at every horizon. The **raw>0 labels post the highest CV AUC (0.559) but it is market timing, not stock selection.** Their fold base rates swing from 0.44 to 0.72, the holdout AUC (a down market) falls to 0.47–0.51, and their cross-sectional rank-IC is a quarter to two-fifths of the excess label's (0.010–0.018 vs 0.044).
3. **Most tradable after costs:** the **20-day next-open** label is the only one where the long-short decile spread clears 20 bps per side. Its break-even cost is 27 bps per side at 100% turnover, and the net return is +3% to +6% a year. The gross spread is not significant, though (t 1.3 over 6 OOS months). Horizons of 5 days or less lose 8–61% a year, and 2 days needs costs below 8 bps per side. **Long-only, every horizon is negative after costs:** at h≥3d the top decile does worse than deciles 7–9 (a lottery tail), and its alpha against the equal-weight universe mean is about zero. Nothing here is a demonstrated tradable edge.
4. **Keep `label_beat_mkt_20d` (20-day next-open excess, clean-masked) as the primary label.** Shorter labels are statistically easier to predict but costs dominate them. Model rank-IC is flat from 3 to 20 days, so the longer horizon earns the same IC at 1/4 to 1/7 of the turnover. Next-open entry is realistic and costs nothing in predictability, since it matches or beats close-to-close. Raw/ex/rank give **identical** per-date ICs, so the cross-sectional target choice does not matter, and vol-scaling adds nothing. **What should change:**
   - (a) Judge the economics against the equal-weight universe *mean*, not the median. Right skew puts the universe's own mean "excess" at +1.4% to +2.0% per 20 days. MODEL_SELECTION.md says the champion's top decile was positive in all five windows (+0.96, +4.58, +1.02, +2.82, +2.12%). Measured against the universe mean, those become −0.88, +2.69, −0.36, +1.24, +0.22%: 3 of 5 positive, and 2 of 5 on the cleaned re-run.
   - (b) Report rank-IC and net spread next to AUC.
   - (c) Carry **40 days** to the 5-year run as a candidate horizon. Its feature IC is larger (mean |IC| 0.040 vs 0.028), its turnover is half, and here it is untestable (it needs an embargo of 41 or more sessions).
   - (d) Drop the roughly 137 ETFs (6% of rows) from the stock universe.
5. **`up_5d`** is not a stock-selection label:
   - It is regime-exposed (monthly base rate 0.37–0.72).
   - Its 0.559 CV AUC is mostly timing (holdout 0.507, rank-IC 0.010, t 0.9).
   - Its entry is close-to-close.
   - It carries 730 rows poisoned by splits or suspensions, because it is unmasked.

   It is useful only as a **negative control**: the gap between its pooled AUC and its cross-sectional AUC measures how much "skill" is really market timing.

**Multiple testing.** The full grid has 1,106 testable hypotheses (40 features × 28 distinct labels, minus 14 tests where flag_split_20d is constant). Under a global null with independent tests, chance would give about 55 results at p<0.05, and BH at q<0.05 would reject nothing with at least 95% probability. We observe 407 results at p<0.05 and 297 at q<0.05. But the tests are strongly dependent: 6 features duplicate others exactly, the horizons are nested, and the features are correlated. Under a month-sign-flip null that preserves this dependence, the 95th percentile is **229** nominal p<0.05 hits, not 55, and 2.8% of null draws yield BH discoveries (99th percentile 164). The observed 297 is therefore significant at p ≈ 0.005. Effectively, the evidence is about 17 monthly draws, not 1,106 independent tests, and the selection test shows it does not carry forward beyond about 5 days.

## Label table (excess family; coverage over labelable dates)

| label | coverage | raw>0 base rate by month | xs std(ex) | lag-1 ac of mkt mean | #feat q<0.05 (NW-adj) | #q<0.05 vol-scaled | composite IC: IS (8m) → OOS (t) |
|---|---|---|---|---|---|---|---|
| cc_1d | 99.96% | 0.41–0.59 | 2.2% | 0.01 | 22 (21) | 18 | 0.092 → **0.049** (4.2) |
| no_1d | 99.92% | 0.42–0.58 | 2.4% | 0.01 | 21 (20) | 20 | 0.083 → **0.050** (3.7) |
| cc_2d | 99.92% | 0.39–0.65 | 3.2% | 0.47 | 17 (17) | 16 | 0.101 → 0.046 (2.8) |
| no_2d | 99.88% | 0.41–0.63 | 3.3% | 0.50 | 20 (19) | 18 | 0.092 → 0.046 (3.0) |
| cc_3d | 99.88% | 0.38–0.67 | 3.9% | 0.65 | 15 (15) | 13 | 0.108 → 0.036 (1.8) |
| no_3d | 99.85% | 0.39–0.67 | 4.0% | 0.68 | 19 (18) | 12 | 0.102 → 0.044 (2.1) |
| cc_5d | 99.81% | 0.37–0.72 | 5.1% | 0.79 | 9 (9) | 6 | 0.115 → 0.031 (1.0) |
| no_5d | 99.77% | 0.36–0.71 | 5.2% | 0.81 | 8 (8) | 7 | 0.112 → 0.033 (1.2) |
| cc_10d | 99.63% | 0.30–0.69 | 7.2% | 0.91 | 5 (5) | 5 | 0.134 → 0.023 (0.7) |
| no_10d | 99.59% | 0.28–0.69 | 7.3% | 0.91 | 5 (4) | 5 | 0.131 → 0.019 (0.6) |
| cc_20d | 99.25% | 0.18–0.75 | 10.4% | 0.95 | 5 (5) | 3 | 0.169 → −0.017 (−0.4) |
| **no_20d** (primary) | 99.22% | 0.17–0.77 | 10.4% | 0.96 | 4 (4) | 5 | 0.167 → −0.018 (−0.4) |
| cc_40d | 98.53% | 0.24–0.82 | 15.1% | 0.97 | 6 (**0**) | 4 | 0.218 → 0.022 (0.7) |
| no_40d | 98.49% | 0.24–0.82 | 15.1% | 0.97 | 5 (**0**) | 4 | 0.231 → 0.028 (0.9) |

The ex>0 base rate is 0.50 in every month by construction. The IS→OOS drop shows the selection bias directly. The OOS window has only 5–9 months.

## Model level (champion LightGBM, all 51 features, harness folds + holdout; economics on all OOS dates, Apr–Sep 2026)

| label | CV AUC ± sd | worst fold | holdout AUC | holdout spread (harness) | xs AUC | rank-IC (t NW) | mean spread / period (t) | break-even bps/side | L/S net ann. 100% / measured TO | long-only net ann. |
|---|---|---|---|---|---|---|---|---|---|---|
| ex_no_2d | 0.524 ± 0.020 | 0.492 | 0.543 | +0.69% | 0.529 | 0.052 (4.83) | +0.32% (2.54) | 7.9 | −61.0% / −19.7% | −16.4% |
| ex_no_3d | 0.522 ± 0.022 | 0.484 | 0.536 | +0.49% | 0.526 | 0.046 (3.82) | +0.29% (1.63) | 7.2 | −43.0% / −15.6% | −17.6% |
| ex_no_5d | 0.518 ± 0.030 | 0.467 | 0.538 | +0.69% | 0.524 | 0.044 (2.88) | +0.34% (1.37) | 8.6 | −23.0% / −8.4% | −10.2% |
| ex_no_10d | 0.518 ± 0.024 | 0.478 | 0.532 | +1.17% | 0.521 | 0.043 (2.77) | +0.63% (1.5) | 15.7 | −4.3% / +2.2% | −3.9% |
| **ex_no_20d** | 0.522 ± 0.021 | 0.487 | 0.527 | +0.23% | 0.523 | 0.044 (2.47) | +1.07% (1.28) | **26.7** | **+3.4% / +5.6%** | −2.5% |
| raw_cc_5d (≈up_5d) | 0.559 ± 0.040 | 0.504 | 0.507 | +0.39% | 0.521 | 0.010 (0.93) | +0.17% (0.85) | 4.2 | −31.8% / −18.5% | −8.8% |
| raw_cc_20d | 0.558 ± 0.019 | 0.533 | **0.471** | −2.54% | 0.513 | 0.018 (1.25) | +0.00% (0.0) | 0.1 | −10.0% / −6.8% | −0.05% |

Notes on the economics:
- **Costs:** 20 bps per side on every rebalance, every h sessions. A long-short rebalance pays 4 sides and long-only pays 2.
- **Measured turnover** is the decile churn between rebalances: 59–78% for long-short (top and bottom averaged) and 52–80% for the top decile.
- **Spreads** are per-date top-minus-bottom decile means. The t-stats are Newey-West with lag h−1.
- **Holdout vs CV:** the holdout ICs (0.057–0.079) are friendlier than the CV ICs (0.034–0.042), the same pattern MODEL_SELECTION.md reports.

## Other things worth knowing
- **Close-to-close entry does not inflate short-term reversal.** Next-open entry shows *more* reversal (ret_1d IC −0.029 vs −0.015 at 1 day; gap_pct −0.014 vs −0.002). After a big day the overnight gap continues and the next session reverses.
- **Rank skill and dollar P&L can disagree in sign.** Out of sample, the 5-day composite has rank-IC +0.03, a median decile spread of +0.66% and hit rates of 53% vs 46%, yet its *mean* decile spread is −0.27%. The low-composite (high-vol) deciles hold the few lottery winners. Median-split labels (ex>0) train for the median, not the mean.
- **ETFs are ~6% of the cross-section.** They have higher delivery and higher mean excess. Excluding them cuts delivery's 20-day IC by about 20% (0.069 → 0.055), but its t-stat holds (4.35 → 4.53).
- **Validation.** The rebuilt labels match the dataset exactly (cc_5d vs fwd_ret_5d to 3e-8, no_20d vs y_raw_20d to 6e-8). The clean masks agree 99.98%, and ex>0 next-open 20d agrees 99.74% with `label_beat_mkt_20d` (the residual comes from the median being taken over clean rows only).
- **Span guard.** It allows max(2.2h, h+4) calendar days. Market-wide holiday clusters are exempt. Example: the 26-Mar/31-Mar/3-Apr-2026 holidays make 25-Mar → 6-Apr a 5-session window of 12 calendar days, which is not a suspension.

## Caveats
- The sample is 16–17 months with a single regime break, and model OOS covers 6 months.
- Monthly t-tests on 17 months are fragile.
- Costs are a flat assumption, with no impact model or shorting constraints. In India, an overnight short book is possible only through F&O or SLB, which makes the long-only column the realistic one.
- **Reproducibility.** The results were first produced in stages because the box was overloaded (`--skip-models`, `--models-only`, `--econ-only`). A clean end-to-end run of the default command (`python3 -m ml.label_study`, 1,025 s, finished 07:51) then reproduced every output exactly: 0 numeric differences across all 13 JSON files, byte-identical CSVs, and the same harness AUCs. Every number in this memo was checked against those regenerated files.

## Labels to carry to the 5-year run

Build these with `ml/data.py` conventions: unadjusted EQ/BE prices, the point-in-time liquidity universe, and every label masked by its own clean column. Column names match `model_dataset.parquet` (primary) and `ml/results/preds/label_study/label_variants.parquet` (candidate).

1. **Primary: `label_beat_mkt_20d`, unchanged.** 1 if `y_excess_20d > 0`, else 0; NaN where unlabelable. Train and score only where `y_clean_20d` is true.
   - `y_raw_20d` = open[t+21] / open[t+1] − 1 (next-open entry, 20 sessions).
   - `y_excess_20d` = `y_raw_20d` − the median of `y_raw_20d` over that date's universe rows.
   - `y_rank_20d` = per-date percentile rank of `y_excess_20d`.
   - `y_clean_20d`: entry and exit opens > 0, calendar span ≤ 45 days, and no |ret_1d| > 22% on bars t+1..t+21.
   - Optional tightening: also require every session of the window to be present. That rejects 81 more pilot rows.
   - Embargo: ≥ 22 sessions, as now.
2. **Candidate: 40-day next-open excess.** Run it alongside the primary; decide on the multi-year walk-forward.
   - `y_raw_40d` = open[t+41] / open[t+1] − 1 (here `raw_no_40d`).
   - `y_excess_40d` = `y_raw_40d` − per-date universe median (`ex_no_40d`).
   - `label_beat_mkt_40d` = 1(`y_excess_40d > 0`) (`bin_ex_no_40d`).
   - `y_clean_40d` (`clean_no_40d`): opens > 0, all 41 sessions present, span ≤ 88 calendar days (2.2 × 40) unless the market calendar itself spans more, and no |ret_1d| > 22% on bars t+1..t+41. Pilot coverage is 98.5%.
   - **Embargo ≥ 41 sessions** (strict minimum h+1; use 42 to keep the 20-day protocol's one-session margin). The current 22-session splits leak for this label.
3. **Reporting, for every label and model.**
   - Per-date rank-IC: Spearman of the score vs the continuous `y_excess_h`, ≥ 100 names per date. Report the mean, a Newey-West t (lag h−1) and a monthly t.
   - Net spread: the per-date top-minus-bottom decile mean of `y_excess_h`, × 252/h, minus 20 bps × 4 sides × the measured decile churn per rebalance (every h sessions). Also report the break-even cost per side.
   - AUC stays as a diagnostic, not the headline.
4. **Benchmark: the equal-weight universe mean.** Long-only alpha = mean `y_excess_h` of the top decile − mean `y_excess_h` of all clean universe rows that date, minus 20 bps × 2 sides × top-decile churn. Never measure against the median: the median-centred excess averages +1.4% to +2.0% per 20 days on its own.
5. **ETF exclusion from the stock universe**, applied before cross-sectional medians and ranks. Drop tickers matching `(?:BEES|ETF|LIQUID|LIQID|GILT|BETF|SENSEX|NIFTY|GOLD|SILV|CASE$|360$|BND$|BETA$|ADD$)`, except the operating companies BETA, SKYGOLD, SILVERTUC, SHANTIGOLD, GOLDIAM, PNBGILTS and DECNGOLD. That is 137 tickers and 6.1% of pilot rows. Once the ingest stores ISINs (empty in the snapshot), replace the name rule with the ISIN prefix INF (fund units) vs INE (equities).
6. **Not carried as selection targets:**
   - `label_up_5d`/`fwd_ret_5d`. Keep it only as a negative control, reporting pooled AUC minus cross-sectional AUC as the timing share.
   - Raw>0 binaries.
   - Vol-scaled targets.
   - Any horizon ≤ 5 days as a trading label (break-even ≤ 8.6 bps per side).
