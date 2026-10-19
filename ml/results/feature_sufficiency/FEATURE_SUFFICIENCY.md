# Feature sufficiency: does the bhavcopy hold information the champion lacks?

*Generated 2026-10-19T07:19:08 by `python3 -m ml.feature_sufficiency` (seed 108). Evidence: `feature_sufficiency.json`; feature definitions and leak checks: `manifest_suff.json`.*

## Verdict

**The current features are sufficient for what this sample can resolve. None of the 23 new features earns a place.** No A/B variant reached the fixed pass mark of 0.5364 with every fold at or above 0.50. The best was `lgbm_suff_top5` at 0.5342, against 0.5314 for the same-session control (paired date-block bootstrap Δ +0.0027, 95% CI [+0.0008, +0.0048]).

- **Residual information is thin and mostly not new.** 2 of 23 features pass BH q ≤ 0.1 on residual IC: `deliv_value_share_20`, `amihud_20`. Both re-express signals the pilot already carries (delivery and liquidity/size). Against all 40 pilot features the residual IC shrinks by 34% (`deliv_value_share_20`), 56% (`amihud_20`).

- **The bhavcopy fields the pilot never reads carry no robust signal.** No feature built from `trades`, `vwap`, `last` or `prev_close` passes BH (lowest q 0.24).

- **The sector proxy is real, but it adds nothing.** The clusters recover IT, PSU banks, private banks, defence and metals. Cluster-relative momentum and delivery have |residual IC| ≤ 0.020 (lowest q 0.56). Their raw IC is the champion's own momentum and delivery signal.

- **Calibration.** Engineered features from the earlier study reached residual t up to +4.65 (`deliv_surge`). They still failed the same A/B (best 0.5268). A residual t of about 3 is not expected to move harness AUC in this sample.

**Answer to management.** (1) Feature work on EOD bhavcopy has reached diminishing returns at this sample size. (2) The 10 features are sufficient for the pilot. (3) Real additions must come from external data (gap list below). The two BH survivors should be re-tested on the 5-year walk-forward, not added now.

## Residual-IC evidence (top 10 by |residual monthly t|, all 23 in the JSON)

IC is the per-date Spearman correlation with `y_excess_20d` on clean labelled rows, averaged within months; t is taken over 16 monthly ICs. For the residual IC, the feature's per-date rank is OLS-orthogonalized on the champion's 10 ranks plus NaN indicators, and the residual is correlated with the label. The quad column also removes squared ranks. q is the BH q-value across all 23 new features. The CV and holdout columns are mean residual IC over those months.

| # | feature | raw IC | raw t | resid IC | resid t | q (BH) | resid IC quad | resid IC vs all 40 pilot (t) | CV months | holdout months | in pilot already? |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | `deliv_value_share_20` | +0.0773 | +3.34 | +0.0175 | +3.64 | 0.055 | +0.0094 | +0.0115 (+2.89) | +0.0165 | +0.0071 | yes, in form: deliv_pct_sma_20 (quantity share); deliv_value_z (engineered) |
| 2 | `amihud_20` | -0.0424 | -1.69 | -0.0395 | -3.07 | 0.089 | -0.0339 | -0.0174 (-2.99) | -0.0121 | -0.0240 | partial: log_turnover / cs_rank_turnover with vol_20 (Amihud ~ vol/turnover) |
| 3 | `idio_vol_60` | -0.0508 | -1.66 | -0.0171 | -2.13 | 0.235 | -0.0175 | -0.0134 (-1.99) | -0.0056 | +0.0120 | partial: vol_20 / cs_rank_vol_20 / atr_pct are total vol |
| 4 | `cs_rank_idio_vol_60` | -0.0508 | -1.66 | -0.0171 | -2.13 | 0.235 | -0.0175 | -0.0134 (-1.99) | -0.0056 | +0.0120 | rank-equivalent of idio_vol_60 |
| 5 | `avg_trade_size_z` | +0.0486 | +1.91 | +0.0315 | +2.12 | 0.235 | +0.0305 | +0.0115 (+1.45) | -0.0021 | +0.0093 | none: `trades` is never read; nearest is size/liquidity (log_turnover) |
| 6 | `gap_fill_10` | -0.0013 | -0.19 | -0.0089 | -1.73 | 0.400 | -0.0054 | -0.0045 (-1.07) | +0.0004 | +0.0056 | partial: gap_pct is the 1-day gap size, never the retrace |
| 7 | `ats_chg_20` | -0.0090 | -1.15 | -0.0086 | -1.48 | 0.527 | -0.0072 | -0.0068 (-1.82) | -0.0142 | -0.0021 | none |
| 8 | `cluster_mom_20` | +0.0290 | +1.37 | +0.0199 | +1.33 | 0.559 | +0.0185 | +0.0170 (+1.31) | -0.0074 | -0.0090 | none (mkt_ret_20 is the whole-market analogue) |
| 9 | `cr_mom_20` | -0.0067 | -0.39 | -0.0156 | -1.28 | 0.559 | -0.0115 | -0.0119 (-1.17) | +0.0061 | -0.0043 | none: the pilot has no sector information |
| 10 | `range_position_20` | +0.0174 | +1.08 | -0.0060 | -1.05 | 0.715 | -0.0112 | +0.0094 (+1.71) | +0.0042 | -0.0142 | yes, in form: close_pos_in_range (1d), accum_20 (engineered), dist_sma_20 |

**Information the pilot already holds.** The stricter column re-runs the residual against all 40 pilot base features, not just the champion's 10. The non-champion pilot features with the largest residual IC against the champion are `dist_sma_20` -0.0224 (t -4.11), `dist_sma_10` -0.0188 (t -3.76), `mom_5` -0.0162 (t -3.52), `dist_52w_low` +0.0226 (t +3.48). Where a new feature's residual IC shrinks in the all-40 column, the 40-feature set already holds that information and the champion's selection dropped it. The fix for that is feature re-selection, not new data.

## Harness A/B (beat_mkt_20d, champion LightGBM config, pass mark 0.5364, every fold ≥ 0.50)

| variant | #feat | CV AUC ± std | folds Apr / May / Jun / Jul | min fold | Δ CV vs control [95% CI] | P(CV ≥ 0.5364) | holdout AUC | holdout spread | pass |
|---|---:|---|---|---:|---|---:|---:|---:|:-:|
| `lgbm_suff_control` | 10 | 0.5314 ± 0.014 | 0.5069 / 0.5384 / 0.5374 / 0.5430 | 0.5069 | -- | 0.135 | 0.5180 | -0.0040 | no |
| `lgbm_suff_top5` | 15 | 0.5342 ± 0.017 | 0.5057 / 0.5441 / 0.5358 / 0.5511 | 0.5057 | +0.0027 [+0.0008, +0.0048] | 0.316 | 0.5333 | +0.0108 | no |
| `lgbm_suff_cluster` | 18 | 0.5257 ± 0.014 | 0.5041 / 0.5375 / 0.5380 / 0.5234 | 0.5041 | -0.0057 [-0.0094, -0.0019] | 0.011 | 0.5071 | -0.0030 | no |
| `lgbm_suff_micro` | 20 | 0.5309 ± 0.018 | 0.5014 / 0.5470 / 0.5292 / 0.5460 | 0.5014 | -0.0005 [-0.0028, +0.0016] | 0.135 | 0.5350 | +0.0146 | no |
| `lgbm_suff_swap_resid` | 10 | 0.5276 ± 0.014 | 0.5061 / 0.5356 / 0.5256 / 0.5430 | 0.5061 | -0.0039 [-0.0074, -0.0004] | 0.016 | 0.5335 | -0.0022 | no |
| `lgbm_suff_swap_resid_rank` | 10 | 0.5275 ± 0.013 | 0.5063 / 0.5353 / 0.5273 / 0.5412 | 0.5063 | -0.0039 [-0.0070, -0.0008] | 0.021 | 0.5314 | -0.0010 | no |

Variant (i) contains `deliv_value_share_20`, `amihud_20`, `cs_rank_idio_vol_60`, `avg_trade_size_z`, `ats_chg_20`. The selection window was all labelled dates up to 2026-07-02, so the CV months helped pick it and its CV score is biased upward. The top-5 by the pre-CV window alone overlap in 4/5 features. The control reproduces the stored `lgbm_fs_selected_clean` (0.5314 vs 0.5314).

## Three strongest cases

- `deliv_value_share_20`: residual IC +0.0175, t +3.64, q 0.055; against all 40 pilot features +0.0115 (t +2.89); sign held in 75% of 16 months; after the quadratic control +0.0094; CV months +0.0165; before vs from the March-2026 break +0.0208 / +0.0132. A/B: `lgbm_suff_top5` 0.5342 (fail); `lgbm_suff_micro` 0.5309 (fail). **Does not clear the bar.**
- `amihud_20`: residual IC -0.0395, t -3.07, q 0.089; against all 40 pilot features -0.0174 (t -2.99); sign held in 75% of 16 months; after the quadratic control -0.0339; CV months -0.0121; before vs from the March-2026 break -0.0640 / -0.0080. A/B: `lgbm_suff_top5` 0.5342 (fail); `lgbm_suff_micro` 0.5309 (fail). **Does not clear the bar.**
- `idio_vol_60`: residual IC -0.0171, t -2.13, q 0.235; against all 40 pilot features -0.0134 (t -1.99); sign held in 56% of 16 months; after the quadratic control -0.0175; CV months -0.0056; before vs from the March-2026 break -0.0305 / +0.0002. A/B: `lgbm_suff_top5` 0.5342 (fail); `lgbm_suff_swap_resid` 0.5276 (fail); `lgbm_suff_swap_resid_rank` 0.5275 (fail). **Does not clear the bar.**

## What the bhavcopy already gives the pilot

Seven of the ten microstructure features read fields the pilot never touches: `trades`, `vwap`, `last`, the CA-adjusted `prev_close` and delivery value. Three are re-expressions of pilot features: `trades_z_20` of `vol_z_20`, `deliv_value_share_20` of `deliv_pct_sma_20`, and `range_position_20` of `close_pos_in_range`/`accum_20`. The sector proxy has 1637 tickers in 12 clusters. Its mean within-cluster residual correlation is 0.0674, against -0.0057 between clusters, and it covers 92% of rows. It was fit once on 2025-08-05 to 2026-01-30, so it is point-in-time for every test fold. For training rows before Feb-2026, the grouping looks ahead; cluster ICs are also reported from Feb-2026 in the JSON.

## External-data gap list (what this repo cannot build)

| data | what it would add | mechanism | NSE source |
|---|---|---|---|
| Index and F&O membership (Nifty 50/100/500, F&O list, MWPL ban list) | inclusion/exclusion demand shocks; F&O eligibility = short-sale feasibility | index-demand price pressure (Shleifer 1986; Harris & Gurel 1986); overpricing persists where shorting is hard (Miller 1977): non-F&O NSE names cannot be shorted overnight except through SLB | NSE archives fo_mktlots.csv and the F&O UDiFF bhavcopy (membership), fo_secban.csv (ban list); niftyindices.com constituent CSVs plus NSE Indices rebalancing press releases (history) |
| Sector / industry classification | true industry momentum, sector-neutral ranking, lead-lag across linked industries | industry momentum (Moskowitz & Grinblatt 1999); slow diffusion across linked firms (Hou 2007; Cohen & Frazzini 2008). The return-correlation clusters here are only a statistical stand-in | NSE 4-level industry classification (macro sector / sector / industry / basic industry) in the NSE equity master and the niftyindices.com constituent files; AMFI half-yearly market-cap categorisation |
| Fundamentals (quarterly results, balance sheet) | value, profitability/quality, accruals, earnings surprise | value and profitability premia (Fama & French 2015; Novy-Marx 2013), accrual anomaly (Sloan 1996), post-earnings-announcement drift (Bernard & Thomas 1989) | Reg-33 LODR XBRL results filed on NSE/BSE (free, needs parsing); vendors CMIE Prowess, ACE Equity, Capitaline, LSEG, Bloomberg |
| Corporate announcements and corporate actions | event timing (results, buybacks, pledges, insider trades) and price adjustment factors | event drift and PEAD (Bernard & Thomas 1989), buyback drift (Ikenberry, Lakonishok & Vermaelen 1995), insider-trade signals (Seyhun 1986). CA factors would also remove split artefacts from every rolling feature and from the y_clean mask (which drops 0.6% of labelled rows) | NSE corporate filings (announcements, corporate actions, board meetings), BSE announcements API, SEBI PIT/SAST disclosures carried by both exchanges |
| Options-implied volatility and derivatives positioning | IV skew, call-put IV spread, implied-minus-realised vol, futures OI/basis (the README's out-of-scope 'carry') | IV skew predicts returns (Xing, Zhang & Zhao 2010); call-put IV spread (Cremers & Weinbaum 2010); volatility risk premium (Bali & Hovakimian 2009); India VIX as the regime conditioner the March-2026 break called for | NSE F&O bhavcopy (daily option settlement prices, OI, volume per strike: IV via Black-76), India VIX history (NSE), NSE participant-wise OI |
| Institutional flows (FII/FPI, DII) | flow-induced price pressure; per-stock ownership change | foreign flows predict EM returns (Froot, O'Connell & Seasholes 2001); flow-driven fire sales/purchases (Coval & Stafford 2007) | NSE/BSE daily FII/DII cash-market figures (aggregate only), NSDL FPI Monitor (aggregate, fortnightly by sector); per stock: quarterly shareholding patterns (NSE/BSE), daily bulk/block deal files (NSE archives), AMC monthly portfolio disclosures |
| News and sentiment | news tone, attention shocks, news-vs-no-news momentum | media pessimism predicts reversals (Tetlock 2007); drift after news vs reversal without news (Chan 2003); attention-driven buying (Barber & Odean 2008) | licensed feeds (LSEG MarketPsych, Bloomberg, Dow Jones/Factiva); exchange announcements as structured events; GDELT (free, coarse) |
| India-specific: surveillance, price bands, SLB, promoter pledges | ASM/GSM stage changes and price-band moves (mechanical liquidity limits); SLB borrow as short interest; pledge overhang | trading restrictions shift liquidity and returns; short interest predicts returns (Desai et al. 2002; Boehmer, Jones & Zhang 2008); forced-sale risk from pledged promoter holdings | NSE daily ASM/GSM lists and sec_list.csv price bands; NSE SLB bhavcopy; SEBI SAST pledge disclosures (NSE 'pledged data') |

## What a 6-month sample can and cannot decide

- **Can decide:** whether a feature carries a large, steady signal the champion lacks. With 16 monthly ICs and a median monthly residual-IC std of 0.036, the smallest residual IC detectable at 5% is about 0.019. Anything weaker is indistinguishable from zero here. The test also catches gross failures: no variant may sit below 0.50 in any fold.
- **Cannot decide:** gains of about +0.005 AUC. Four CV folds give a standard error on mean CV AUC of about 0.007, so the pass mark sits within about one standard error of the control. A pass would still need confirmation and a fail does not prove the gain is zero. The sample also cannot decide anything that needs a cycle. It holds one regime break (March 2026) and only 7 observable months of `mom_12_1`. Signals that pay only in some regimes, such as cluster rotation, are out of reach, as is seasonality, because the archive calendar is simulated.
- **Adjacent ICs overlap.** Labels span 20 sessions, so adjacent daily ICs share most of their window and monthly t-stats run slightly optimistic. Monthly means are used for that reason. The 5-year walk-forward (~60 monthly folds) is where a +0.005 effect becomes decidable. Re-run this module on that dataset before closing the question.
