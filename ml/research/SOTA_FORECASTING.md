# State of the Art in Equity Return Forecasting: Evidence Review for SuryaDhana

**Date:** 2026-10-19 · **From:** research (literature team) · **Companion:** `ml/research/sota_map.json`

**Program files read:**
- Pilot decision and plan: `ml/MODEL_SELECTION.md`, `ml/SCALE_UP.md` (re-read after today's gate changes), `ml/README.md`
- Results: `eda_features.json` (insights), `model_selection.json` (significance)
- Work added today: `ml/results/strategy/STRATEGY.md`, the red-team audit cache (`ml/results/audit/cache/T*.json`), the interim SOTA runs (`ml/results/sota/`, train log at 06:47) and `FEATURE_SUFFICIENCY.md`
- Protocol code: `evaluation.py`, `eval_aggregate.py`, `feature_selection.py`, `models/trees.py`

Notation: [n] is a reference. Status is `done`, `partial` or `gap`. "Our derivation" marks our own arithmetic.

## Executive summary

1. **The frontier finds small predictability.** In US data, trees and neural nets reach monthly out-of-sample R² of 0.33–0.40%, against 0.16% for 3-variable OLS. A neural-net decile long-short earns a Sharpe of 1.35 value-weighted and 2.45 equal-weighted, before costs [1]. Kelly & Xiu expect predictability to be "small and fiercely competed over" [2].
2. **SuryaDhana's signal is that size, but the economic edge is not yet proven.**
   - The champion's per-date rank IC is 0.057 in CV and 0.040 in the holdout (`sota/champion_ref`). GKX's 0.40% R² implies a forecast–return correlation of about 0.06 (our derivation), and Qlib's CSI300 LightGBM IC is 0.045 [10].
   - Net of 20 bps per side, the top decile beats the equal-weight universe by +4.2% a year. But the IR confidence interval is [−2.4, +4.3] and the Deflated Sharpe Ratio (DSR) is 0.08 (`STRATEGY.md`).
   - That is what a 5.5-month sample can show [58].
3. **On engineered tabular features, GBMs beat deep nets.** This holds in finance (Qlib Alpha158: LightGBM IC 0.045 vs Transformer 0.026 [10]) and in general benchmarks [23][24]. Deep and graph models gain only on raw sequences or from cross-asset structure.
4. **Transformer evidence is narrow.** Cross-asset attention helps in large US panels: AIPM Sharpe rises 3.9 → 4.6, gross [22]. Temporal transformers lose to linear models by 20–50%, and to a naive repeat-last-value forecast on FX [20]. The program's own PatchTST and cross-sectional transformer runs are still in progress.
5. **Time-series foundation models do not forecast returns.** Zero-shot on daily stock returns, Chronos has R² −1.37% and TimesFM −2.80%, with direction accuracy near 50%, worse than CatBoost [30]. Their gains over a random walk are "small and sparse" [31].
6. **Reinforcement learning (RL) is weak for this problem.** Reviews find "no decent profitability" [34]. RL works where a simulator exists: execution and hedging [33][39][40]. Dropping RL for selection was correct.
7. **Ranking losses suit stock selection.**
   - On NYSE data, LambdaMART raised gross Sharpe from 0.27 to 2.16 [11], and median-splitting a target wastes about 38% of the sample's information [16].
   - SuryaDhana's own LightGBM `lambdarank` has CV AUC 0.529, below the champion. Its holdout decile spread, though, is +6.0% against −0.4% (interim), so the evidence is mixed.
8. **The India evidence is clear on momentum and value, and silent on delivery %.**
   - Momentum 21.9% a year, value 15.3%, size about 0% (1994–2014) [42].
   - The low-volatility effect is mostly beta [43].
   - ML beats linear models in emerging markets and in India [46][47].
   - We found **no peer-reviewed test of NSE delivery %**, the program's strongest signal.
9. **Costs.** Statutory charges are about 11 bps per side: STT (securities transaction tax) 10 bps plus stamp duty 1.5 bps on buys [52].
   - The program's 20 bps/side base case and 40 bps stress are reasonable for the liquid tercile. The champion's break-even is about 39–41 bps/side.
   - **Not yet modelled:** name-level spread and impact for the illiquid tail, which ML profits favour [5].
10. **Hygiene.** The red-team audit confirmed that features were selected on the CV test folds (T9 FAIL), and that dependence widens intervals 1.7× (T14). A DSR gate now exists.
    - **Still open:** selection nested inside each training window, block length at least the 20-session label horizon, and PBO (probability of backtest overfitting) or CPCV (combinatorial purged cross-validation) [55][57][59].

## 1. Cross-sectional ML return prediction

**What worked.** GKX [1] (about 30,000 US stocks, 1957–2016) use 920 features: 94 characteristics, their interactions with 8 macro variables, and 74 industry dummies. Testing is out of sample over 1987–2016, refit yearly. R² is measured against a zero forecast (Table 1):

| Model | Monthly R²_oos |
|---|---:|
| OLS, all features | −3.46% |
| OLS-3 (size, value, momentum) | 0.16% |
| Elastic net / PCR / PLS | 0.11% / 0.26% / 0.27% |
| Trees and neural nets (peak NN3) | 0.33–0.40% |
| Same, top-1,000 stocks | 0.52–0.70% |

- **Depth and benchmark.** Deeper nets add nothing. Benchmarking against the historical mean instead of zero would add about 3 points to every R².
- **Economics.** NN4's value-weighted decile spread earns 2.3% a month, a Sharpe of 1.35 (Table 7). Equal-weighted it earns 2.45 (Internet Appendix A.9), against 0.61 and 0.83 for OLS-3. Turnover is 110–130% a month (Table 8), and no costs are deducted.
- **Top predictors** (all methods agree): price trends (reversal, momentum, industry momentum), then liquidity (turnover, dollar volume, size, Amihud, spread), then risk (volatility, beta), then valuation.

**Structure helps, and the real signal is sparse.**
- A no-arbitrage GAN reaches an out-of-sample Sharpe of 2.6. Its linear special case gets 1.7, a deep return forecaster 1.5, and FF5 0.8. On the 1,500 and 550 largest stocks it gets only 1.4 and 0.9 [3].
- In IPCA, eight characteristics are "responsible for nearly 100%" of the model's accuracy [4].
- In non-microcaps, 12 of 94 characteristics are independent predictors over 1980–2014, and only 2 after 2003 [6]. Many predictors add nothing incremental, and nonlinearity matters [7].

**Limits.**
- Deep-learning profits concentrate in hard-to-arbitrage stocks. Excluding microcaps, distressed firms or volatile periods "considerably attenuates" them [5].
- Kelly & Xiu name three constraints: small data, weak signal-to-noise, and markets in which "investors learn and markets evolve" [2].
- The claim that more complex models predict better [8] is contested; Nagel reduces it to volatility-timed momentum [9].

**What this means for SuryaDhana.** The champion's 10 features cover GKX's top groups: long momentum, 52-week high, volatility, a turnover proxy for liquidity, and inverted `cs_rank_mom_20` (short-term reversal). Size, beta, industry momentum and fundamentals are missing. The strategy layer now evaluates the model the way the frontier does: net long-only and long-short books, turnover (80%), month-block CIs, capacity by liquidity tier, and DSR. The league table still ranks models on AUC.

| Practice | Status | Program evidence |
|---|---|---|
| Nonlinear GBM + regularized linear benchmark | done | MODEL_SELECTION.md |
| Rank IC (Newey–West t) as model metric | partial | `sota/*.json` rank_ic; league headline still AUC |
| Net portfolio economics (Sharpe, turnover, DSR) | done | `strategy/STRATEGY.md` |
| GKX top feature families | partial | trend, volatility, turnover present; size, beta, industry, valuation absent (`FEATURE_SUFFICIENCY.md` adds Amihud, idiosyncratic-vol tests) |
| Results within liquid / large names | done | STRATEGY.md liquid-tercile book (₹1,129 cr capacity) |

## 2. Learning-to-rank and target design

A long-only or long-short book depends only on how stocks are ordered within each date. LambdaRank and LambdaMART optimize ranking metrics such as NDCG through pairwise gradients [12]. LightGBM supports this natively (`lambdarank`, with each date as a query group) [13].

**Evidence.**
- **Poh et al. [11]** (NYSE 1980–2019, monthly, 100 long and 100 short, momentum features, **no costs**) report Sharpe ratios of 2.156 for LambdaMART, 1.970 for ListNet and 1.502 for RankNet. An MLP that regresses and then ranks gets 0.265, and Jegadeesh–Titman momentum 0.551 (Exhibit 2). Kendall τ is 0.032 against 0.008. This is one gross study.
- **Krauss et al. [14]** use SuryaDhana's exact label, "beats the cross-sectional median". They earn 0.45% a day before costs, and profits decline over time.
- **Fischer & Krauss's LSTM [15]** earns 0.46% a day before costs, but "as of 2010, excess returns seem to have been arbitraged away".
- **Cohen [16].** Dichotomizing one variable cuts explained variance to 0.647 r², equivalent to discarding 38% of cases.
- **GKX [1]** regress returns directly, and Huber loss helps.

**What this means for SuryaDhana.** The sample is too short to judge the ranking challengers, which are already running (interim):

| Challenger | CV AUC | Holdout AUC | Holdout decile spread | Rank IC, CV (NW t) |
|---|---:|---:|---:|---:|
| `lgbm_lambdarank` | 0.529 | 0.566 | +6.0% | 0.049 (2.1) |
| `lgbm_huber` | 0.522 | 0.530 | +1.2% | 0.046 (3.3) |
| `ensemble_rank` (rank average) | 0.5357 | 0.548 | +3.9% | 0.065 (3.6) |
| Champion | 0.531 | 0.518 | −0.4% | 0.056 (3.3) |

`ensemble_rank` misses the 0.5364 pass mark by 0.0007. CV and holdout disagree, which is the pilot's regime problem again. On CV, the magnitude-aware losses do not beat the binary champion, contrary to the information-loss argument. On the holdout, `lambdarank`'s +6.0% spread fits the "gains in the tails" expectation. Run all three through the net-of-cost strategy layer with the EW benchmark and DSR, then decide at 5 years.

The STRATEGY finding that the EW universe beats the median by +1.78% per 20 days, which is skew and not skill, is a target-design lesson. Gate 3 now benchmarks against EW.

| Practice | Status | Program evidence |
|---|---|---|
| Cross-sectionally relative target | done | `beat_mkt_20d` |
| Ranking loss / magnitude target | partial | `lgbm_lambdarank`, `lgbm_huber` (interim, not adjudicated) |
| Benchmark = EW universe, not median | done | STRATEGY.md; SCALE_UP gate 3 |
| Risk-adjusted or neutralized target | gap | none |

## 3. Deep sequence models and transformers

- **Temporal Fusion Transformer** [17] was benchmarked on electricity, traffic, retail and realized-volatility series.
- **PatchTST** [18] and **iTransformer** [19] lead long-horizon benchmarks. None of these benchmarks is a cross-section of equity returns.
- **Zeng et al. [20]** find linear models beat transformer forecasters "in all cases, and often by a large margin (20% ∼ 50%)". On FX, a repeat-last-value forecast beat every transformer by about 45%.

**Finance benchmark.** Qlib [10] runs on CSI300 from January 2017 to August 2020. It holds the top 50 names and drops 5 per rebalance, at 5/15 bps entry/exit cost, averaged over 20 seeds. The table gives IC, with IR in brackets:

| Input set | LightGBM | Best GBM-based | MLP / LSTM / GRU | HIST (graph) | TFT | Transformer |
|---|---|---|---|---|---|---|
| Alpha158 (engineered features) | 0.0448 (1.02) | 0.0521 DoubleEnsemble (1.34) | 0.0376 / 0.0318 / n.a. | n.a. | 0.0358 (rank IC 0.0116) | 0.0264 (0.40) |
| Alpha360 (raw 60-day) | 0.0400 (0.76) | 0.0400 | 0.0273 / 0.0448 / 0.0493 | 0.0522 (1.37) | n.a. | 0.0114 (−0.34) |

**Cross-asset attention.**
- MASTER [21] reports CSI300 IC 0.064 against 0.051 for XGBoost (CSI800: 0.052 vs 0.040; Table 1).
- AIPM [22] (132 characteristics, US 1963–2022) reports Sharpe 3.6 → 3.9 when a linear model gets attention, and 3.9 → 4.6 for the nonlinear version. These are gross figures, and we found no cost adjustment.

**General tabular benchmarks.**
- Trees stay state of the art on medium-size data across 45 datasets [23].
- Across 176 datasets, GBDTs are "much better ... at handling skewed or heavy-tailed feature distributions" [24].

**Summary.** Transformers and graph models win only on raw sequences or cross-asset relations, in long and wide panels, measured gross of costs. On engineered, heavy-tailed, short or regime-breaking data, GBMs remain the default.

**What this means for SuryaDhana.** The pilot's MLP, LSTM and GRU scored 0.503, 0.502 and 0.489 on about 507k rows of heavy-tailed features (`atr_pct` excess kurtosis about 13,900), as the literature predicts. The interim `patchtst_lite` and `cs_transformer` runs scored 0.524 and 0.493 on the 2026-05 fold. Let them finish under the fixed pass mark; do not widen the deep search before 5 years.

| Practice | Status | Program evidence |
|---|---|---|
| Deep models vs GBM under the same protocol | done | MODEL_SELECTION.md |
| Heavy-tail transforms for neural nets | partial | prescribed in the EDA |
| Cross-sectional attention | partial | `cs_transformer` running (`models/sota.py`) |
| Temporal transformer / DLinear | partial | `patchtst_lite` running; DLinear queued |

## 4. Time-series foundation models

These are univariate pretrained forecasters:
- **Chronos** [25]: quantized tokens on T5, trained on public and Gaussian-process synthetic series.
- **TimesFM** [26]: a patched decoder.
- **Moirai** [27]: trained on "over 27B observations across nine domains".
- **TimeGPT** [28].
- **Lag-Llama** [29]: probabilistic, with lags as inputs.

All are trained on generic, seasonal series whose signal-to-noise ratio is far higher than that of returns.

**Evidence on returns.**
- **Rahimikia, Ni & Wang [30]** use daily excess returns from 94 countries, with US out-of-sample 2001–2023.
  - **Zero-shot:** Chronos-large has R² −1.37% and accuracy "just above 51%". TimesFM-500M has R² −2.80% and accuracy "just below 50%". CatBoost scores −0.10%, linear −0.47%.
  - **Fine-tuning:** "limited improvements".
  - **Pre-training on financial data:** helps (−0.59%) but stays "less effective in terms of goodness-of-fit than benchmark models".
  - **Caveat:** the paper's Sharpe ratios are daily-rebalanced, before costs.
- **Noguer i Alonso & Franklin [31]:** across five US stocks, Diebold–Mariano tests reject in only 2 cases. The models are "not universal engines for statistically reliable alpha generation".
- **M6 [32]:** live rank-quintile forecasting of 100 assets for 12 months. 23.3% of 163 teams beat the naive forecast, 6.7% beat it on both forecasts and portfolio IR, and only 3 beat it every month.

**What this means for SuryaDhana.** A univariate TSFM sees only a stock's own price path. That is the input the pilot found weakest: the short-horizon block had |t| < 1, and the RNNs scored at chance. It never sees the cross-section, delivery or market-state information that carries the edge. Expected value is low; at most, run one zero-shot sanity baseline at 5 years.

| Practice | Status | Program evidence |
|---|---|---|
| Zero-shot TSFM baseline | gap (low priority) | not tried |

## 5. Reinforcement learning

Hambly, Xu & Yang [33] survey RL across execution, portfolios, hedging, market making and order routing. The documented weaknesses:
- Studies are "proof-of-concept ... in unrealistic settings", with "no decent profitability" [34].
- The obstacles are "low signal-to-noise", "survivorship bias" and "overfitting in the backtesting stage" [35].
- The FinRL team itself rejects overfitted agents with a formal test [36].
- Results swing with random seeds and implementation choices [37].

The counter-example is 50 liquid futures (2011–2019), where DRL beat time-series momentum "despite heavy transaction costs" [38]. That is a time-series task with few instruments.

RL needs four things:
- a correct, net-of-cost reward
- a simulator with credible market impact
- many episodes
- a way to cope with non-stationarity

Execution [39] and hedging [40] meet these; end-of-day cross-sectional alpha does not.

**What this means for SuryaDhana.** The drop is well supported. REINFORCE scored 0.5085 on CV, and its own simulation lost to mom20. STRATEGY.md adds that its big numbers come from the 30 holdout dates (DSR 0.38). Cost-aware rebalancing is done better with explicit bands; Novy-Marx & Velikov find a buy/hold spread is the best cost mitigation [41].

| Practice | Status | Program evidence |
|---|---|---|
| RL tested and dropped on evidence | done | MODEL_SELECTION.md; STRATEGY.md |
| Turnover bands / hysteresis | partial | SCALE_UP Phase 3; not built |

## 6. India-specific evidence

**Factor premia.**
- In survivorship-corrected data for 1994–2014, momentum earned 21.9% a year, HML 15.3%, SMB "nearly 0%", and the market premium 11.5% [42].
- Over 2001–2015, the lowest-volatility decile earned 11.40% annualised excess return and the highest 1.30%. The gap is **not significant after controlling for beta** [43].
- Replication evidence is mixed. Most factors replicate across 93 countries [49], but 65% of 452 US anomalies fail |t| ≥ 1.96 [50].

**Momentum depends on market state.** In the US, momentum earned 0.93% a month after up-markets and −0.37% after down-markets (1929–1995) [44]. It crashes "in panic states ... contemporaneous with market rebounds"; a dynamic version roughly doubles its Sharpe [45].

**ML in emerging markets and India.**
- In emerging markets, ML beats linear models, and net returns survive costs, short-sale constraints and large-cap restriction [46].
- In NSE/BSE data over 1994–2019, 14 of 35 characteristics have |t| > 3, and ML beats OLS [47].
- In China, a retail-dominated market, liquidity is the top predictor [48].

**Delivery %.** Two targeted searches found no peer-reviewed study of delivery share as a return predictor. The nearest evidence is that Indian individual day traders, about 10% of volume, lose 3.2 bp per trade [51]. That is consistent with non-delivery volume being partly noise trading, but it is untested as a signal.

**Costs.** Delivery trades pay STT of 0.1% on each side, stamp duty of 0.015% on buys, plus exchange, SEBI and GST charges [52]. That is about 11 bps per side, or 22 bps per round trip, before brokerage, spread and impact. Nifty 50 eligibility alone allows impact cost up to 0.50% on a ₹10 crore basket [53]. Spreads can be estimated from daily highs and lows [70], and impact scales roughly with the square root of trade size [71].

**What this means for SuryaDhana.**
- **Two textbook effects, rediscovered.** Momentum IC is +0.099 in up-tapes vs +0.013 in down-tapes, the pattern in [44]. The March-2026 inversion of 25 of 40 features is a rebound crash of the kind in [45]. Both support the queued market-state A/B.
- **Delivery needs its own test.** The delivery block held its sign in 15 of 16 months (t = 4.35), and `deliv_value_share_20` carries residual information (BH q = 0.055). But its IC fell from +0.107 to +0.020, and no external study exists. It needs a pre-registered 5-year test.
- **Missing features.** Size and beta are absent, and Indian low-volatility is mostly beta.
- **Costs and shorts.** The 20 bps/side base case is consistent with about 11 bps statutory plus a liquid-name spread. STRATEGY.md already flags the illiquid tail and the shorting constraint: shorts need SLB or F&O, which covers about 200 names. A name-level spread and impact model is the remaining step.

| Practice | Status | Program evidence |
|---|---|---|
| Momentum by market state | partial | EDA; A/B queued in SCALE_UP |
| Low-vol / beta | partial | volatility features only; beta measured only in STRATEGY.md |
| Size (market cap) | gap | no shares-outstanding data |
| Delivery-% signal | partial | internal evidence only; no literature |
| India-realistic costs | partial | flat 10/20/40 bps/side; no name-level spread or impact |
| Capacity and short-sale feasibility | done | STRATEGY.md (5% ADV; short leg dropped) |

## 7. Research hygiene

**What the frontier requires.**
- **AFML [54]:**
  - purged k-fold with an embargo, purging on each label's actual end date (ch. 7)
  - uniqueness weights for overlapping labels (ch. 4)
  - CPCV (ch. 12)
  - the probabilistic and deflated Sharpe ratios, PSR and DSR (ch. 14)
- **"10 Reasons" [55][56]:** single-path walk-forward should be replaced by CPCV, and backtest overfitting should be checked with the DSR.
- **Overfitting.** The DSR deflates Sharpe for the number of trials and for non-normal returns [57]. "If only 5 years of data are available, no more than 45 independent model configurations should be tried" [58]. PBO is estimated with combinatorially symmetric cross-validation (CSCV) [59].
- **Multiple testing.** New factors need t > 3.0, and "most claimed research findings in financial economics are likely false" [60]. Sharpe ratios should be haircut for multiple testing [61].
- **Arnott, Harvey & Markowitz [62]:** "true out-of-sample tests are only possible in live trading". Track every model tried, and avoid "out-of-sample iterations".
- **Decay.** Predictor returns are 26% lower out-of-sample and 58% lower after publication [63].
- **Tools for dependent data:** block bootstraps [64] and model confidence sets [65].

**Audit of SuryaDhana**, mostly confirmed by today's red-team cache:

*Done*
- Purged walk-forward with a 22-session embargo. T3 found only 3 of 1.6M train rows crossing into test, plus 81 illiquid-name labels spanning more than 21 sessions.
- A within-date label-permutation null gives CV AUC 0.5000 ± 0.0011, so the pipeline manufactures no AUC: the champion's z is 28 (T1).
- Labels and point-in-time features recompute exactly (T4, T5).
- Pass marks are fixed in advance.
- The strategy DSR uses N = 96 trials, and gate 5 requires DSR ≥ 0.95.

*Gap: selection on the test folds (T9 FAIL)*
- Features were chosen on the four CV test folds.
- Tree hyperparameters were screened on 2026-04/05.
- Holdout labels leaked into one feature-A/B screen (`quick_ic`).

The 0.531 CV AUC is therefore a validation score. The honest estimate is the holdout's 0.518. T11, an honest nested re-selection, is pending.

*Partial: dependence*
- `eval_aggregate.py` resamples dates i.i.d., although labels overlap 20 sessions and the daily-IC autocorrelation is 0.968.
- 10-session blocks widen the SD 1.7× (T14). The rank-IC t falls from 6.70 naive to 3.26 Newey–West.
- With 20-session overlap, the 88 CV dates hold about 4–5 independent observations (our derivation). A month-level t is 3.80 (p = 0.016, 4 folds).

*Partial: trial accounting*
- The red team counts 28 full-protocol configurations, 155 including screens (T7).
- The within-date permutation null's SD (0.0011) understates regime risk. At the fold-level SE of 0.0083, the expected best of 30 nulls is about 0.517, so the champion's margin is about 0.014, not 0.031 (our calculation via [57][58]).

*Gap:* no PBO, no CPCV, no uniqueness weighting.

**What this means for SuryaDhana.** For the 5-year run, Phase 2 should:
- run feature re-selection inside each training window, not on the test folds
- purge on per-row label exit dates
- use bootstrap blocks of at least 20 sessions in the harness
- add PBO across the candidate set to the DSR gate already in place

| Practice | Status | Program evidence |
|---|---|---|
| Purged walk-forward + embargo | done | `data.py`; audit T3 (minor exceptions) |
| Leakage and null tests | done | audit T1, T4, T5, T8 |
| Holdout used only once | partial | T9: holdout entered one feature-A/B screen |
| Selection nested in training windows | gap | T9 FAIL; T11 pending |
| Overlap-aware significance | partial | T14; month-block bootstrap in STRATEGY.md; harness i.i.d. |
| Trial ledger + DSR | partial | T7 count; DSR N = 96; gate 5 |
| PBO / CPCV / uniqueness weights | gap | none |
| Pre-registered rules | done | `feature_ab_verdict.json`; SCALE_UP gates |
| Data integrity | partial | holiday echo fixed; corporate actions pending |

## 8. What is credibly known about Renaissance/Medallion

- **Returns.** Over 1988–2018, Medallion's mean gross return was 66.1% a year (SD 31.7%), or 63.3% compounded. These figures are after trading costs. Beta was negative, and the returns "cannot be interpreted as a premium for risk bearing" [67].
- **Hit rate.** Zuckerman [66] quotes Robert Mercer: "We're right 50.75 percent of the time ... but we're 100 percent right 50.75 percent of the time". We could not open the page itself. Kling's review [68] says bets worked "between 50 percent and 51 percent of the time (after allowing for transaction costs)" and were held "a few days or less".
- **Our interpretation.** Grinold's law, IR ≈ IC × √breadth [69], implies that a coin-flip edge needs huge breadth and tiny cost per bet.

**What this means for SuryaDhana.**
- **Copy:** the cost discipline, many weak signals combined, and continuous research.
- **Do not copy:** the holding horizon. The program's signals are slow, and its breadth is low (monthly bets on correlated names). It needs a higher IC per bet and less cost per unit of turnover.

| Practice | Status | Program evidence |
|---|---|---|
| Cost/impact model inside selection | gap | flat costs only |
| Continuous monitoring (IC decay, drift) | partial | planned in SCALE_UP Phase 3 |
| Many weak signals in one model | partial | 10-feature LGBM; rank ensemble (interim) |

## Recommended research agenda (ranked by expected value per unit effort)

EV and effort are judgement scores from 1 to 5. Items 2 and 4 gate the 5-year promotion decision whatever their rank.

| # | Item | EV | Effort | EV/E | 6-month data | 5-year run |
|---|---|---:|---:|---:|---|---|
| 1 | Route `lambdarank`, `ensemble_rank` and huber scores through `strategy_backtest.py`: net, EW benchmark, DSR with N updated [11][13][57] | 3 | 0.5 | 6.0 | runs; cannot decide | decides |
| 2 | Finish hygiene: nested re-selection (T11) as the Phase 2 protocol, purge on label exit, ≥20-session blocks, PBO [57][59][64] | 5 | 1 | 5.0 | build and dry-run only | required |
| 3 | Delivery validation: pre-registered IC by year, liquidity tier and state; orthogonalize vs turnover and volatility | 4 | 1.5 | 2.7 | cannot | required |
| 4 | Name-level costs: spread [70] + √-impact [71] by tier; asymmetric STT/stamp | 4 | 1.5 | 2.7 | yes (illiquid tail) | net Sharpe |
| 5 | Market-state A/B (already queued) [44][45] | 3 | 1.5 | 2.0 | cannot (one crash) | needs ≥2 sell-offs |
| 6 | Beta and idiosyncratic volatility (computable from bhavcopy); size and industry (new data) [1][43] | 3 | 2 | 1.5 | beta and idio vol only | yes |
| 7 | CPCV for the final choice [54] | 2 | 2 | 1.0 | no | yes |
| 8 | TSFM zero-shot sanity check [30][31] | 0.5 | 1 | 0.5 | low value | optional |
| 9 | Further deep or attention models beyond the running set [21][22] | 1.5 | 4 | 0.4 | no | only after items 1–6 |
| 10 | RL for execution [39] | 1 | 4 | 0.25 | no | needs live fills |

Item 1 needs no new research, only routing existing scores through the strategy engine. Its verdict will read "inconclusive" on 6 months, which is still worth knowing before Phase 2.

**Bottom line.** A 6-month window supports plumbing and one-off sanity checks, plus a turnover and cost picture. It cannot support claims that need regime diversity, decisions at 0.01-AUC resolution, or DSR power: the champion needs about 2.8 years to reach PSR 95%. The 5-year run can, if items 2 and 4 land first. The evidence does not justify spending the next unit of effort on transformers, foundation models or RL.

## References

1. Gu, S., Kelly, B., Xiu, D. (2020). Empirical Asset Pricing via Machine Learning. *Review of Financial Studies* 33(5):2223–2273. https://doi.org/10.1093/rfs/hhaa009 (PDF: https://dachxiu.chicagobooth.edu/download/ML.pdf)
2. Kelly, B., Xiu, D. (2023). Financial Machine Learning. *Foundations and Trends in Finance* 13(3–4):205–363. https://doi.org/10.1561/0500000064 (NBER w31502: https://www.nber.org/papers/w31502)
3. Chen, L., Pelger, M., Zhu, J. (2024). Deep Learning in Asset Pricing. *Management Science* 70(2):714–750. https://doi.org/10.1287/mnsc.2023.4695 (arXiv: https://arxiv.org/abs/1904.00745)
4. Kelly, B., Pruitt, S., Su, Y. (2019). Characteristics Are Covariances: A Unified Model of Risk and Return. *Journal of Financial Economics* 134(3):501–524. https://doi.org/10.1016/j.jfineco.2019.05.001
5. Avramov, D., Cheng, S., Metzker, L. (2023). Machine Learning vs. Economic Restrictions: Evidence from Stock Return Predictability. *Management Science* 69(5):2587–2619. https://doi.org/10.1287/mnsc.2022.4449
6. Green, J., Hand, J., Zhang, X.F. (2017). The Characteristics that Provide Independent Information about Average U.S. Monthly Stock Returns. *Review of Financial Studies* 30(12):4389–4436. https://doi.org/10.1093/rfs/hhx019
7. Freyberger, J., Neuhierl, A., Weber, M. (2020). Dissecting Characteristics Nonparametrically. *Review of Financial Studies* 33(5):2326–2377. https://doi.org/10.1093/rfs/hhz123
8. Kelly, B., Malamud, S., Zhou, K. (2024). The Virtue of Complexity in Return Prediction. *Journal of Finance* 79(1):459–503. https://doi.org/10.1111/jofi.13298
9. Nagel, S. (2025). Seemingly Virtuous Complexity in Return Prediction. NBER WP 34104. https://www.nber.org/system/files/working_papers/w34104/w34104.pdf
10. Microsoft Qlib (2020–2026). Benchmarks, CSI300 Alpha158/Alpha360 (accessed 2026-10). https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md ; LightGBM config (segments, strategy, costs): https://github.com/microsoft/qlib/blob/main/examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml ; Yang et al. (2020), arXiv:2009.11189: https://arxiv.org/abs/2009.11189
11. Poh, D., Lim, B., Zohren, S., Roberts, S. (2021). Building Cross-Sectional Systematic Strategies by Learning to Rank. *Journal of Financial Data Science* 3(2):70–86. https://doi.org/10.3905/jfds.2021.1.060 (arXiv: https://arxiv.org/abs/2012.07149)
12. Burges, C. (2010). From RankNet to LambdaRank to LambdaMART: An Overview. Microsoft Research MSR-TR-2010-82. https://www.microsoft.com/en-us/research/publication/from-ranknet-to-lambdarank-to-lambdamart-an-overview/
13. LightGBM documentation (2026). Parameters: objective `lambdarank`, `rank_xendcg`. https://lightgbm.readthedocs.io/en/latest/Parameters.html
14. Krauss, C., Do, X.A., Huck, N. (2017). Deep neural networks, gradient-boosted trees, random forests: Statistical arbitrage on the S&P 500. *European Journal of Operational Research* 259(2):689–702. https://doi.org/10.1016/j.ejor.2016.10.031
15. Fischer, T., Krauss, C. (2018). Deep learning with long short-term memory networks for financial market predictions. *European Journal of Operational Research* 270(2):654–669. https://doi.org/10.1016/j.ejor.2017.11.054
16. Cohen, J. (1983). The Cost of Dichotomization. *Applied Psychological Measurement* 7(3):249–253. https://doi.org/10.1177/014662168300700301
17. Lim, B., Arık, S.Ö., Loeff, N., Pfister, T. (2021). Temporal Fusion Transformers for interpretable multi-horizon time series forecasting. *International Journal of Forecasting* 37(4):1748–1764. https://doi.org/10.1016/j.ijforecast.2021.03.012
18. Nie, Y., Nguyen, N.H., Sinthong, P., Kalagnanam, J. (2023). A Time Series is Worth 64 Words: Long-term Forecasting with Transformers (PatchTST). ICLR 2023. https://arxiv.org/abs/2211.14730
19. Liu, Y., et al. (2024). iTransformer: Inverted Transformers Are Effective for Time Series Forecasting. ICLR 2024. https://arxiv.org/abs/2310.06625
20. Zeng, A., Chen, M., Zhang, L., Xu, Q. (2023; arXiv 2022). Are Transformers Effective for Time Series Forecasting? AAAI 2023. https://arxiv.org/abs/2205.13504
21. Li, T., et al. (2024). MASTER: Market-Guided Stock Transformer for Stock Price Forecasting. AAAI 38(1):162–170. https://arxiv.org/abs/2312.15235
22. Kelly, B., Kuznetsov, B., Malamud, S., Xu, T.A. (2025). Artificial Intelligence Asset Pricing Models. NBER WP 33351. https://www.nber.org/papers/w33351
23. Grinsztajn, L., Oyallon, E., Varoquaux, G. (2022). Why do tree-based models still outperform deep learning on typical tabular data? NeurIPS 2022 Datasets & Benchmarks. https://arxiv.org/abs/2207.08815
24. McElfresh, D., et al. (2023). When Do Neural Nets Outperform Boosted Trees on Tabular Data? NeurIPS 2023 Datasets & Benchmarks. https://arxiv.org/abs/2305.02997
25. Ansari, A.F., et al. (2024). Chronos: Learning the Language of Time Series. https://arxiv.org/abs/2403.07815
26. Das, A., Kong, W., Sen, R., Zhou, Y. (2024). A decoder-only foundation model for time-series forecasting (TimesFM). ICML 2024. https://arxiv.org/abs/2310.10688
27. Woo, G., et al. (2024). Unified Training of Universal Time Series Forecasting Transformers (Moirai). https://arxiv.org/abs/2402.02592
28. Garza, A., Mergenthaler-Canseco, M. (2023). TimeGPT-1. https://arxiv.org/abs/2310.03589
29. Rasul, K., et al. (2023). Lag-Llama: Towards Foundation Models for Probabilistic Time Series Forecasting. https://arxiv.org/abs/2310.08278
30. Rahimikia, E., Ni, H., Wang, W. (2025). Re(Visiting) Time Series Foundation Models in Finance. arXiv:2511.18578. https://arxiv.org/abs/2511.18578
31. Noguer i Alonso, M., Franklin, R.P. (2026). Pretrained Time-Series Foundation Models for Financial Return Forecasting. arXiv:2606.27100. https://arxiv.org/abs/2606.27100
32. Makridakis, S., Spiliotis, E., Hollyman, R., Petropoulos, F., Swanson, N., Gaba, A. (2023). The M6 forecasting competition: Bridging the gap between forecasting and investment decisions. arXiv:2310.13357 (submitted to *IJF*). https://arxiv.org/abs/2310.13357
33. Hambly, B., Xu, R., Yang, H. (2023). Recent advances in reinforcement learning in finance. *Mathematical Finance* 33(3):437–503. https://doi.org/10.1111/mafi.12382
34. Pricope, T.-V. (2021). Deep Reinforcement Learning in Quantitative Algorithmic Trading: A Review. arXiv:2106.00123. https://arxiv.org/abs/2106.00123
35. Liu, X.-Y., et al. (2022). FinRL-Meta: Market Environments and Benchmarks for Data-Driven Financial Reinforcement Learning. NeurIPS 2022 Datasets & Benchmarks. https://arxiv.org/abs/2211.03107
36. Gort, B., Liu, X.-Y., et al. (2022). Deep Reinforcement Learning for Cryptocurrency Trading: Practical Approach to Address Backtest Overfitting. https://arxiv.org/abs/2209.05559
37. Henderson, P., et al. (2018). Deep Reinforcement Learning that Matters. AAAI 2018. https://arxiv.org/abs/1709.06560
38. Zhang, Z., Zohren, S., Roberts, S. (2020). Deep Reinforcement Learning for Trading. *Journal of Financial Data Science* 2(2):25–40. https://doi.org/10.3905/jfds.2020.1.030
39. Nevmyvaka, Y., Feng, Y., Kearns, M. (2006). Reinforcement learning for optimized trade execution. ICML 2006, pp. 673–680. https://doi.org/10.1145/1143844.1143929
40. Buehler, H., Gonon, L., Teichmann, J., Wood, B. (2019). Deep hedging. *Quantitative Finance* 19(8):1271–1291. https://doi.org/10.1080/14697688.2019.1571683
41. Novy-Marx, R., Velikov, M. (2016). A Taxonomy of Anomalies and Their Trading Costs. *Review of Financial Studies* 29(1):104–147. https://doi.org/10.1093/rfs/hhv063
42. Agarwalla, S.K., Jacob, J., Varma, J.R. (2013; rev. 2014). Four factor model in Indian equities market. IIM Ahmedabad WP 2013-09-05. https://www.iima.ac.in/publication/four-factor-model-indian-equities-market ; data library: https://www.jrvarma.in/fama-french.html
43. Joshipura, M., Joshipura, N. (2016). The Volatility Effect: Evidence from India. *Applied Finance Letters* 5(1). https://ojs.aut.ac.nz/applied-finance-letters/article/view/32
44. Cooper, M., Gutierrez, R., Hameed, A. (2004). Market States and Momentum. *Journal of Finance* 59(3):1345–1365. https://doi.org/10.1111/j.1540-6261.2004.00665.x
45. Daniel, K., Moskowitz, T. (2016). Momentum crashes. *Journal of Financial Economics* 122(2):221–247. https://doi.org/10.1016/j.jfineco.2015.12.002
46. Hanauer, M.X., Kalsbach, T. (2023). Machine learning and the cross-section of emerging market stock returns. *Emerging Markets Review* 55:101022. https://doi.org/10.1016/j.ememar.2023.101022
47. Lalwani, V., Meshram, V.V. (2022). The cross-section of Indian stock returns: evidence using machine learning. *Applied Economics* 54(16):1814–1828. https://doi.org/10.1080/00036846.2021.1982132
48. Leippold, M., Wang, Q., Zhou, W. (2022). Machine learning in the Chinese stock market. *Journal of Financial Economics* 145(2):64–82. https://doi.org/10.1016/j.jfineco.2021.08.017
49. Jensen, T.I., Kelly, B., Pedersen, L.H. (2023). Is There a Replication Crisis in Finance? *Journal of Finance* 78(5):2465–2518. NBER w28432: https://www.nber.org/papers/w28432
50. Hou, K., Xue, C., Zhang, L. (2020). Replicating Anomalies. *Review of Financial Studies* 33(5):2019–2133. https://doi.org/10.1093/rfs/hhy131
51. Dalvi, M., Deuskar, P., Glosten, L., Jagannathan, R. (2023). Day Traders, Noise, and Cost of Immediacy. NBER WP 31127. https://www.nber.org/papers/w31127
52. Indian statutory trading charges for delivery equity: STT 0.1% buy and sell; stamp duty 0.015% on buys; exchange, SEBI and GST charges. Broker fee schedules (accessed 2026-10): https://www.interactivebrokers.ca/en/accounts/fees/indiaStockExchangeFees.php ; https://hdfcsky.com/pricing/other-trading-charges
53. NSE Indices. Nifty Broad Market Indices Methodology (NIFTY 50: average impact cost ≤ 0.50% for 90% of observations, ₹10 crore basket). https://nsearchives.nseindia.com/content/indices/Nifty_Broad_Market_Indices_Methodology.pdf ; press release (2017): https://niftyindices.com/Press_Release/ind_prs22082017.pdf
54. López de Prado, M. (2018). *Advances in Financial Machine Learning*. Wiley. https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086
55. López de Prado, M. (2018). The 10 Reasons Most Machine Learning Funds Fail. *Journal of Portfolio Management* 44(6):120–133. https://doi.org/10.3905/jpm.2018.44.6.120 (PDF: https://www.garp.org/hubfs/Whitepapers/a1Z1W0000054x6lUAA.pdf)
56. López de Prado, M. (2017). The 7 Reasons Most Machine Learning Funds Fail (presentation). SSRN 3031282. https://papers.ssrn.com/abstract=3031282
57. Bailey, D., López de Prado, M. (2014). The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality. *Journal of Portfolio Management* 40(5):94–107. https://doi.org/10.3905/jpm.2014.40.5.094 (SSRN: https://papers.ssrn.com/abstract=2460551)
58. Bailey, D., Borwein, J., López de Prado, M., Zhu, Q.J. (2014). Pseudo-Mathematics and Financial Charlatanism: The Effects of Backtest Overfitting on Out-of-Sample Performance. *Notices of the AMS* 61(5):458–471. https://doi.org/10.1090/noti1105 (PDF: https://carmamaths.org/jon/backtest.pdf)
59. Bailey, D., Borwein, J., López de Prado, M., Zhu, Q.J. (2017). The Probability of Backtest Overfitting. *Journal of Computational Finance* 20(4):39–69. https://doi.org/10.21314/JCF.2016.322 (SSRN: https://papers.ssrn.com/abstract=2326253)
60. Harvey, C., Liu, Y., Zhu, H. (2016). … and the Cross-Section of Expected Returns. *Review of Financial Studies* 29(1):5–68. https://doi.org/10.1093/rfs/hhv059
61. Harvey, C., Liu, Y. (2015). Backtesting. *Journal of Portfolio Management* 42(1):13–28. https://doi.org/10.3905/jpm.2015.42.1.013
62. Arnott, R., Harvey, C., Markowitz, H. (2019). A Backtesting Protocol in the Era of Machine Learning. *Journal of Financial Data Science* 1(1):64–74. https://doi.org/10.3905/jfds.2019.1.064 (SSRN: https://papers.ssrn.com/abstract=3275654)
63. McLean, R.D., Pontiff, J. (2016). Does Academic Research Destroy Stock Return Predictability? *Journal of Finance* 71(1):5–32. https://doi.org/10.1111/jofi.12365
64. Politis, D., Romano, J. (1994). The Stationary Bootstrap. *Journal of the American Statistical Association* 89(428):1303–1313. https://doi.org/10.1080/01621459.1994.10476870
65. Hansen, P.R., Lunde, A., Nason, J. (2011). The Model Confidence Set. *Econometrica* 79(2):453–497. https://doi.org/10.3982/ECTA5771
66. Zuckerman, G. (2019). *The Man Who Solved the Market: How Jim Simons Launched the Quant Revolution*. Portfolio/Penguin. https://www.penguinrandomhouse.com/books/557104/the-man-who-solved-the-market-by-gregory-zuckerman/9780593148198
67. Cornell, B. (2020). Medallion Fund: The Ultimate Counterexample? Cornell Capital Group. https://www.cornell-capital.com/blog/2020/02/medallion-fund-the-ultimate-counterexample.html
68. Kling, A. (2020). Wall Street Mysteries (review of Zuckerman 2019). Econlib. https://www.econlib.org/library/Columns/y2020/Klingmysteries.html
69. Grinold, R. (1989). The Fundamental Law of Active Management. *Journal of Portfolio Management* 15(3):30–37. https://doi.org/10.3905/jpm.1989.409211
70. Corwin, S., Schultz, P. (2012). A Simple Way to Estimate Bid-Ask Spreads from Daily High and Low Prices. *Journal of Finance* 67(2):719–760. https://doi.org/10.1111/j.1540-6261.2012.01729.x
71. Tóth, B., et al. (2011). Anomalous Price Impact and the Critical Nature of Liquidity in Financial Markets. *Physical Review X* 1:021006. https://doi.org/10.1103/PhysRevX.1.021006
