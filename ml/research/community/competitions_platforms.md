# How Good Is Good Enough? Competition, Platform and Practitioner Benchmarks

**Date:** 2026-10-19 · **From:** benchmark research (area C: competitions, platforms, rules of thumb) · **Companion:** `competitions_platforms.json` (42 entries)

This file covers the competition, platform and practitioner layer. The academic literature is in `ml/research/SOTA_FORECASTING.md` and is not repeated here. Where that review already covers an item (Grinold's law, the DSR, Harvey's t > 3, Kling on Medallion), this file only cross-references it.

**Markers**
- **[V]**: the page was fetched and read (PDF text extracted where needed).
- **[S]**: unverified (snippet only). The page could not be opened (JavaScript-rendered Kaggle pages, HTTP 403/404/503), so the number comes from search-result text.
- **"Our arithmetic"**: a number we derived; the working is shown.

**SuryaDhana's numbers used for comparison** (from the brief and `ml/results/strategy/STRATEGY.md`):
- ROC AUC 0.5366, above 0.50 in 81% of 43 monthly folds.
- Per-date rank IC 0.04–0.05, Newey–West t ≈ 3; directional hit rate ≈ 52%.
- Paper book (5.5 months, net of 20 bps per side): +4.2%/yr versus the equal-weight (EW) universe, IR 0.99 (95% CI [−2.36, 4.34]), PSR 0.75, DSR 0.08. Turnover is 80% per 20-session rebalance.

---

## 1. Competition benchmarks

| Competition | Year | Metric | Winning or reference value | Translation (our arithmetic unless marked) |
|---|---|---|---|---|
| Two Sigma Financial Modeling (Kaggle) | 2017 | R, which the organisers call "similar to R squared" [S] | Winner not found. Rank ≈130 of 2,000+ scored ≈0.02 [V]. A +0.002 change moved one entrant from #12 to #51 [V]. | If R = √R², then R = 0.02 gives R² = 0.0004, i.e. 0.04% of variance explained. Ranks are separated by thousandths. |
| Two Sigma: Using News to Predict Stock Movements (Kaggle) | 2018–19 | Daily mean/std of a beta-neutral book's P&L on 10-day residual returns [V] | Winner not found | A daily Sharpe on overlapping 10-day returns. Do not annualise it with √252. |
| Jane Street Market Prediction (Kaggle) | 2020–21 | Utility u = min(max(t,0),6) × Σp, where t is the annualised Sharpe of daily P&L [V] | Winner not found. 241st of 4,245 scored 4,272.6 [V]; 173rd scored 4,369.3 [S]. | Sharpe × total P&L, so it cannot be mapped to an IC. An intraday, many-trade setting. |
| Optiver Realized Volatility (Kaggle) | 2021 | RMSPE | 0.19548 (2nd 0.19720) [S] | ≈19.5% relative error on 10-minute **volatility**. Not a return task. |
| G-Research Crypto Forecasting (Kaggle) | 2022 | Weighted Pearson correlation | 0.0326; 2nd 0.0283; 3rd 0.0232 [S]. Three months of live evaluation [V]. | **A live IC of about 0.03 won**, on 14 assets at a short horizon. |
| Ubiquant Market Prediction (Kaggle) | 2022 | Mean per-time-step Pearson correlation | 0.126987; 15th (last gold) 0.118069; 2,436 teams [S] | Per-date IC ≈0.13 on an obfuscated, probably short-horizon target. 1st and 15th differ by only 0.009. |
| JPX Tokyo Stock Exchange Prediction (Kaggle) | 2022 | Daily Sharpe of the top-200 minus bottom-200 rank-weighted spread over ≈3 live months [V] (definition [S]) | 0.381; 2nd 0.356; 10th 0.280 [V], from the official J-Quants repo | 0.381 × √245 = **5.96 annualised, gross**. Over ≈60 days, SE = 1/√60 = 0.129, so the winner is 2.95 SE. The expected best of 2,033 zero-skill entries is ≈3.4 SE = 0.44 (Blom approximation, independent entries). **The winning score is within the range luck can produce.** |
| Optiver Trading at the Close (Kaggle) | 2023–24 | MAE (bps) on 60-second relative moves | 5.4030; 2nd 5.4041; 50th 5.4621 [S] | (6.4 − 5.403)/6.4 = 15.6% better than a zero forecast (zero MAE ≈6.4 [S], possibly a different period). An independent holdout found GBM only 1.8% better than a median forecast (5.708 vs 5.815) [V]. |
| M6 (Makridakis) | 2022–23 | RPS (forecasts) and IR (portfolios), 12 monthly live rounds | Of 163 teams, 23.3% beat the forecast benchmark, 28.8% beat the EW portfolio and 6.7% beat both. **No team beat the investment benchmark in all 12 months** [V]. | The closest live analogue to SuryaDhana: a monthly cross-sectional ranking judged against equal weight. Beating EW at all over a year is top-third (28.8% did). |

**What winners and organisers said about the size of the signal**
- **G-Research (organiser):** "With such a noisy dataset, it was unsurprising that the leaderboard saw many big jumps and precipitous drops." All top three teams used LightGBM, and features mattered far more than models [V].
- **Two Sigma 2017:**
  - "my R value went up by about .002, which made me drop from #12 to #51" [V].
  - Another entrant fell from 71st to 1,086th of 2,071 between the public and private leaderboards: "there is a lot of luck involved" [V].
- **Jane Street 2021** (a top-6% team): "CV too good but leaderboard bad" [V].
- **Chan & Hunter (QTS Capital), on Two Sigma News** [V]:
  - A price model's Sharpe fell from 1.2 (validation) to 0.28 (test), so it kept only 23%. A rule with no training fell from 1.0 to 0.75.
  - "Simple technical features do not work."
  - They cite Beckers (2018): news-sentiment information ratios were below 0.5 over 2008–2017.

**Read-across.**
- **Size of winning scores.** Where the target is a real return and the evaluation is live and blind, winning correlations run from about 0.03 (G-Research) to about 0.13 (Ubiquant, obfuscated target). Daily long–short contests post high gross Sharpe ratios, and luck decides the order.
- **Our numbers.** SuryaDhana's IC of 0.04–0.05 sits in the range that wins competitions. But ours comes from our own walk-forward, not a blind live test.

---

## 2. Numerai

**How the score is defined** [V]
- CORR is `numerai_corr`. Predictions are gauss-ranked, the target is centred, and both are raised to the power 1.5 before a Pearson correlation is taken.
- The docs describe it as "a good proxy for actual portfolio returns". It is the same family of statistic as our per-date rank IC.
- Scores are computed against 20-day (CORR20V2) and 60-day (CORR60) targets with a 2-day lag.
- The docs give **no numeric "good" CORR**. They warn that "past performance is no guarantee of future performance".

**Payouts** [V]
- Formula: `round_return = clip(payout_factor × Σ score × multiplier, −1, 1)`.
- In v3, payout_factor is 1 and the clip is ±1. The legacy clip was 5% (Classic and Crypto) or 3.5% (Signals), and maximal legacy payouts were "closer to 1–2% per round".
- From round 1343, Numerai Classic pays **3 × CORR60 + 15 × MMC60**. So a CORR60 of 0.02 earns 3 × 0.02 = 6% of stake per round from CORR alone; the MMC term is extra (our arithmetic).

**What participants achieve**
| Who | Value | Status |
|---|---|---|
| Best small LightGBM, validation | CORRV2 0.0247 (CatBoost best trial 0.0255) | [V] user forum, Oct 2023 |
| Independent participant, **live** 60-day diagnostics | CORR 0.0171, per-era Sharpe 1.32, benchmark-neutral tBMC 0.0030 | [V] self-reported README |
| Numerai's own example model | "can achieve a correlation Sharpe of 2 on our validation dataset" | [V] Numerai team post, Aug 2024 |
| Unique contribution | "Average MMC is about 10x smaller than average CORR"; MMC Sharpe is about half CORR Sharpe | [V] user forum, Dec 2023 |
| Community view of "good" | "If you have held out a test set and got similar Sharpe and correlation on that, then I'd say those are excellent." | [V] user forum, 2020 |

**What the meta-model and fund achieve**
- **2019 backtest:** the meta-model scored Sharpe 1.55, against 0.91 for a single ML model and 0.13 for a linear model. After a data update it scored 2.09. Numerai labels these "for illustrative purposes only" [V].
- **Numerai One, 2024:** +25.45% net, **Sharpe 2.75** net of fees with rf = 0, and a single down month [V, self-reported]. Assets are about $700m (July 2026) [S, press release].
- **Not found in text:** a per-round CORR for the meta-model itself. Forum figures are images.

**Numerai Signals** [V]
- Current payout: 0.3 × Alpha + 0.8 × MPC. From round 1363 the plan is 0.5 × NCORR + 2 × NMMC.
- Signals are scored only after neutralising them against signals Numerai already has. The docs say: "Numerai Signals is not about predicting stock returns".

**Read-across.**
- **Our IC level.** Good Numerai models reach a correlation of about 0.02–0.025 against a factor-neutralised target. Our raw-label IC is about twice that. Part of it is probably common factor exposure (momentum, size), which Numerai's targets remove.
- **Our stability.** Our per-month IC stability is 0.46–0.88. Numerai's benchmarks reach 1.3 (live) to 2 (validation). The working:
  - 81% of months above 0.50 implies a mean/sd of 0.88 (inverse normal of 0.81).
  - A Newey–West t of 3 over 43 months gives 3/√43 = 0.46 per month.

---

## 3. WorldQuant BRAIN submission criteria

WorldQuant does not publish the thresholds on open pages; the platform is login-gated [S, search of worldquant.com]. The table uses community and third-party sources.

| Test (US, delay-1) | Threshold | Source |
|---|---|---|
| Sharpe (in-sample, 5-year) | > 1.25 (stricter for delay-0 and China) | quantt.co.uk review, Oct 2026 [V]; third-party |
| Fitness = Sharpe × √(\|returns\| / max(turnover, 0.125)) | > 1.0 | alexisdpc GitHub docs [V]; jglazar [V] |
| Turnover (daily) | 1%–70% | quantt [V] |
| Weight concentration | ≤ 10% of book in one stock | quantt [V] |
| Sub-universe Sharpe | Must hold in smaller universes, threshold scaled by universe size | quantt [V]; exact formula [S] |
| Self-correlation | < 0.7 against own alphas | community; "not confirmed in official material" [V] |

**What the community reports**
- **Selection ratio.** An IQC 2023 entrant "tested 1,103 alphas and submitted the 28 best for scoring", or 2.5%. The highlighted alphas had Sharpe 1.58–2.00, fitness 1.03–1.35 and turnover 9–51%, on a 5-year backtest (2016–2021) [V].
- **Pay.** Payment tiers are vague; the review notes "Reaching Gold is a threshold, not a guarantee" [V].
- **Typical consultant alpha Sharpe.** We found no verifiable statement.

**WorldQuant's own research** [V]
- Kakushadze's "101 Formulaic Alphas" (2016) describes real production alphas.
- Average holding period is 0.6–6.4 days, and average pairwise correlation is 15.9%.
- Returns are "strongly correlated with volatility" and do not depend on turnover.

**Our arithmetic**
- **Noise pass rate.** Over a 5-year in-sample, the SE of an annualised Sharpe is about 1/√5 = 0.447. Sharpe 1.25 is therefore z = 2.80, so pure noise passes with a one-sided p = 0.26%, which matches the review. Trying 1,000 variants yields 2–3 noise passes, hence the extra robustness tests.
- **SuryaDhana's fitness, indicatively.** IR 0.99 × √(0.042 / max(0.80/20, 0.125)) = 0.99 × √(0.042/0.125) = **0.57**, below the 1.0 pass mark. BRAIN returns are for a dollar-neutral long–short book, so this is only a rough comparison.

---

## 4. Microsoft Qlib benchmark (China A-shares)

**Settings** [V], from `workflow_config_lightgbm_Alpha158.yaml`:
- Market and benchmark: CSI300 against SH000300.
- Periods: train 2008–2014, valid 2015–2016, test 2017-01-01 to 2020-08-01.
- Strategy: TopkDropoutStrategy with topk 50 and n_drop 5.
- Costs and execution: open cost 5 bps, close cost 15 bps, deal price close.

**Reporting conventions** [V], from the README:
- Every value is the mean ± std over 20 seeds.
- The README says the backtest changed substantially from version 0.8.0.
- The label is not stated. Qlib's docs use next-day return as an example label; that this is Alpha158's default is unverified [S].

**LightGBM row, CSI300 Alpha158, quoted exactly** [V]:

> `| LightGBM(Guolin Ke, et al.) | Alpha158 | 0.0448±0.00 | 0.3660±0.00 | 0.0469±0.00 | 0.3877±0.00 | 0.0901±0.00 | 1.0164±0.00 | -0.1038±0.00 |`

Columns, in order: IC, ICIR, Rank IC, Rank ICIR, annualised (excess) return, information ratio, max drawdown.

| CSI300 | Dataset | IC | ICIR | Rank IC | Rank ICIR | Ann. return | IR | Max DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Linear | Alpha158 | 0.0397 | 0.3000 | 0.0472 | 0.3531 | 0.0692 | 0.9209 | −0.1509 |
| MLP | Alpha158 | 0.0376 | 0.2846 | 0.0429 | 0.3220 | 0.0895 | 1.1408 | −0.1103 |
| LSTM (20 features) | Alpha158 | 0.0318 | 0.2367 | 0.0435 | 0.3389 | 0.0381 | 0.5561 | −0.1207 |
| GRU (20 features) | Alpha158 | 0.0315 | 0.2450 | 0.0428 | 0.3440 | 0.0344 | 0.5160 | −0.1017 |
| Transformer | Alpha158 | 0.0264 | 0.2053 | 0.0407 | 0.3273 | 0.0273 | 0.3970 | −0.1101 |
| TRA | Alpha158 | 0.0440 | 0.3535 | 0.0540 | 0.4451 | 0.0718 | 1.0835 | −0.0760 |
| CatBoost | Alpha158 | 0.0481 | 0.3366 | 0.0454 | 0.3311 | 0.0765 | 0.8032 | −0.1092 |
| XGBoost | Alpha158 | 0.0498 | 0.3779 | 0.0505 | 0.4131 | 0.0780 | 0.9070 | −0.1168 |
| **LightGBM** | Alpha158 | **0.0448** | **0.3660** | **0.0469** | **0.3877** | **0.0901** | **1.0164** | **−0.1038** |
| DoubleEnsemble (LGBM base) | Alpha158 | 0.0521 | 0.4223 | 0.0502 | 0.4117 | 0.1158 | 1.3432 | −0.0920 |
| LightGBM | Alpha360 | 0.0400 | 0.3037 | 0.0499 | 0.4042 | 0.0558 | 0.7632 | −0.0659 |
| GRU | Alpha360 | 0.0493 | 0.3772 | 0.0584 | 0.4638 | 0.0720 | 0.9730 | −0.0821 |
| HIST (graph) | Alpha360 | 0.0522 | 0.3530 | 0.0667 | 0.4576 | 0.0987 | 1.3726 | −0.0681 |
| Transformer | Alpha360 | 0.0114 | 0.0716 | 0.0327 | 0.2248 | −0.0270 | −0.3378 | −0.1653 |

**CSI500.** The README marks these results as "not complete", and some rows look duplicated.

| CSI500 | Dataset | IC | ICIR | Rank IC | Rank ICIR | Ann. return | IR | Max DD |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| LightGBM | Alpha158 | 0.0399 | 0.4065 | 0.0482 | 0.5101 | 0.1284 | 1.5650 | −0.0635 |
| LightGBM | Alpha360 | 0.0400 | 0.3605 | 0.0536 | 0.5431 | 0.0505 | 0.7658 | −0.1880 |

**Translation (our arithmetic)**
- **Daily IC stability.** A daily ICIR of 0.366 is 0.366 × √252 = 5.8 annualised. Over ≈880 test days that gives t ≈ 0.366 × √880 = 10.9, assuming daily ICs are close to independent (likely with a 1-day label).
- **Our level matches; our consistency does not.** SuryaDhana matches Qlib's IC level (0.045 vs 0.04–0.05), but its t of about 3 on overlapping 20-day labels is far less consistent.
- **Qlib's portfolio result.** LightGBM's excess return is 9.0%/yr at IR 1.02 after 5/15 bps costs over 3.6 test years. On CSI500 it is 12.8%/yr at IR 1.57.

---

## 5. Platform acceptance criteria

| Platform | Criterion | Value | Status |
|---|---|---|---|
| **Quantopian** (contest, 2017–19) | \|beta to SPY\|; position size; mean daily turnover; gross leverage; sector; style | < 0.3; ≤ 5%; 5–65% (63-day window); 0.8–1.1×; < 20% per sector; within ±40% | [S] tutorial page returns 503; limits changed over time |
| Quantopian (purpose) | Staff, Dan Dunn: "We're seeking algorithms that we can use to manage capital provided by external investors." | qualitative | [V] archive |
| Quantopian (evidence) | 888 algorithms with ≥ 6 months out of sample; in-sample Sharpe explains out-of-sample Sharpe with R² < 0.025 | R² < 0.025 | [V] Quantpedia summary |
| Quantopian (community) | Keep a factor if the "mean IC [is] above 0.01" with "p-values below 0.05"; "a Q Sharpe of 1 and above is likely a good candidate" | IC > 0.01; Sharpe ≥ 1 | [V] archive |
| **QuantConnect** (Alpha Streams) | PSR > 80%, where PSR is "the probability of the out of sample being greater than 1.0 Sharpe" | 80% | [V] staff, about 2021 |
| QuantConnect | "only 9 from 280 or 3.21% currently have PSR > 80" | 3.2% pass | [V] |
| QuantConnect | Score = PSR × Sharpe × capacity × min(daysLive/180, 1) | live weight full after 6 months | [V] |
| QuantConnect | "80-90% rejection rate"; drawdowns must recover within 6 months; profitable over a 5+ year backtest | — | [V] |
| QuantConnect (docs) | 5–7-year backtest; correlation < 85% with own alphas; "a good minimum to aim for is an annualized Sharpe ratio of 1" | Sharpe 1 | [S] docs page now 404 |
| **Numerai Signals** | Scored after neutralising against Numerai's existing signals | see §2 | [V] |
| **Alpaca** | No published alpha-acceptance or performance criteria found | none | search only |

**Common norms across platforms**
- Sharpe of about 1 is the floor for "good".
- Six months out of sample is the minimum observation period.
- Five years of backtest is standard.
- Low beta and factor exposure, and low correlation to existing alphas, are required.
- Most submissions fail: 80–90% at QuantConnect, and 2.5% of tried alphas submitted at WorldQuant IQC.

---

## 6. Industry rules of thumb

**IC tiers**
- **MSCI Barra (Gleiser & McKenna, 2010):** "many portfolio managers would view a 'good' IC as 0.05 and a 'very good' IC as 0.10" [V]. They apply Grinold's rule alpha = IC × residual volatility × score.
- **Grinold & Kahn**, via study notes: "A good forecaster has an IC of 0.05, a great forecaster has an IC = 0.1, and a world class..." [S, the page returned 503].
- **M6 organisers** assume IC tiers of 0.05 (Moderate), 0.10 (Good) and 0.15 (Exceptional) [V].

**Fundamental law: IR ≈ IC × √breadth**
- The source is Grinold (1989) (see SOTA [69]). The explainer [V] stresses "The formula counts independent bets."
- Our arithmetic: with IC 0.045, IR 0.5 needs (0.5/0.045)² = 123 independent bets a year, and IR 1.0 needs 494.
- Nominal breadth of 2,400 stocks × 12 months = 28,800 would imply IR = 0.045 × 169.7 = 7.6. Our realised IR of 0.99 therefore means effective breadth is about 1/60 of nominal. The causes are correlated names, the long-only constraint and a low transfer coefficient.

**Hit rate versus IC.** Using Sheppard's formula for jointly normal forecast and return, P(same sign) = ½ + arcsin(IC)/π (our arithmetic):

| IC | 0.01 | 0.02 | 0.03 | 0.045 | 0.05 | 0.10 | 0.15 |
|---|---:|---:|---:|---:|---:|---:|---:|
| Implied hit rate | 50.3% | 50.6% | 51.0% | 51.4% | 51.6% | 53.2% | 54.8% |

- **The "51–53% is a great model" lore.** We found **no primary source**. Numerically it matches the IC 0.03–0.10 band above.
- **Closest verified statements:**
  - Man AHL's chief scientist Anthony Ledford: "It's slightly more than a coin flip." and "we seek to have a tiny edge that is working in our favour" (IBTimes, 2017) [V].
  - Robert Mercer "allegedly told a friend that Medallion was right 50.75 percent of the time" (Institutional Investor, 2020, citing Zuckerman 2019) [V]. Kling's "50 to 51 percent" is in SOTA §8.

**Hit rate and breadth** (de Prado's framework, AFML ch. 15; the formula is our derivation and the book was not opened)
- For independent bets with symmetric payoffs, SR = (2p − 1)·√n / (2√(p(1 − p))).
- At p = 0.52, an annual Sharpe of 1 needs n ≈ 624 independent bets a year.
- At Medallion's p = 0.5075, Sharpe 2 needs n ≈ 17,800 bets a year.
- With 12 monthly bets at p = 0.52, Sharpe is only 0.14.

**Overfitting and sample length**
- **De Prado's worked example:** a daily strategy with annualised SR 2.5 over 5 years (T = 1,250), N = 100 trials, skew −3 and kurtosis 10 has DSR = 0.90: "There is only a 90% probability that the true Sharpe ratio is above zero" [V].
- **Time to significance (our arithmetic):** reaching t = 2 takes (2/SR)² years. That is 16 years at SR 0.5, 4 at SR 1, 2.6 at SR 1.25 and 1 at SR 2.

**Practitioners on how small predictability is**
- Man AHL (above), Chan & Hunter (§1), and Quantopian's finding that R² < 0.025 (§5).
- Kelly & Xiu, "small and fiercely competed over", is in SOTA [2].
- **Not found within budget:** verifiable quantitative statements from AQR, Two Sigma or Jane Street talks or blogs.

---

## 7. India: retail platforms and SEBI

**SEBI circular SEBI/HO/MIRSD/MIRSD-PoD/P/CIR/2025/0000013 (4 Feb 2025)** [V]
- Algo orders sent through broker APIs carry exchange-issued identifiers.
- Algos that retail investors build themselves are registered only above an order-per-second threshold set by the brokers' Industry Standards Forum. Third-party blogs cite 10 orders per second [S].
- Providers of **black-box** algos must "Register as a Research Analyst and maintain a detailed research report for each such algo".
- The circular sets **no performance norms**.
- It was to apply from 1 Aug 2025. It was later extended to 1 Oct 2025 [S, Taxmann] and then to 1 Apr 2026 [S, broker blogs].

**SEBI PR 22/2024 (23 Sep 2024)** [V]
- 93% of over 1 crore individual F&O traders lost money in FY22–FY24.
- 97% of FPI profits and 96% of proprietary-trader profits came from algorithmic trading.

**Platforms**
- We found **no published performance norms** for Streak, Tradetron, AlgoTest, QuantMan or uTrade.
- Comparison blogs describe Streak as indicator-based and Tradetron as a strategy marketplace [S].
- AlgoTest's blog claims "45% of AlgoTest users ended the year in profit", with no method given [V; vendor claim].

**Read-across.** None of these is a usable benchmark for model quality. The regulator's own data say the profitable side of Indian markets is institutional algorithms.

---

## 8. The "good enough" ladder

IC is the per-date rank IC on a multi-week relative-return label. Hit rates come from §6 (Sheppard). Sharpe and IR are after costs.

| Rung | IC (level and stability) | Hit rate | Sharpe / IR after costs | Track record | Sources |
|---|---|---|---|---|---|
| **0. Noise** | < 0.01, or t < 2 | ≤ 50.3% | ≤ 0, or below a naive EW or momentum baseline | — | Quantopian community bar; M6 (≈71% of teams failed to beat EW over the year) |
| **1. Real factor: keep researching** | 0.01–0.03, t ≥ 2 (t ≥ 3 for a new factor, SOTA [60]) | 50.3–51.0% | Not yet required | Enough out-of-sample dates for the t-stat (≥ 3 years of monthly folds) | Quantopian (IC > 0.01, p < 0.05) [V]; Numerai live CORR 0.017 [V]; G-Research live winner 0.033 [S]; Two Sigma R ≈ 0.02 [V] |
| **2. Good model: paper-trade** | ≈0.04–0.05, per-period IC mean/sd ≥ 1 | 51.4–51.6% | IR ≈ 1 net in walk-forward, and beats naive baselines | ≥ 6 months live or paper, consistent with backtest | MSCI "good" 0.05 [V]; Qlib LightGBM IC 0.045 / IR 1.02 net [V]; Numerai live Sharpe 1.32, validation 2 [V]; Quantopian 6-month out of sample [V]; QuantConnect daysLive/180 [V] |
| **3. Allocatable** | ≥ 0.05 after neutralising known factors (momentum, size, sector); stable across sub-universes | ≥ 51.6% | Sharpe ≥ 1.25 over a 5-year walk-forward; PSR(true SR > 1) ≥ 80%; DSR ≥ 0.95; fitness > 1 | 5-year walk-forward plus ≥ 6–12 months live; ≈2.6 years live for t = 2 at SR 1.25 | WorldQuant thresholds [V, third-party]; QuantConnect PSR [V]; de Prado DSR [V]; Numerai Signals neutral scoring [V] |
| **4. Exceptional** | ≥ 0.10 ("very good" or "great"); 0.15 "exceptional". On a broad universe at a 20-day horizon, treat this as a leakage warning first. | ≥ 53% | Fund-level Sharpe ≥ 2, from breadth and many combined signals | Multi-year, live | MSCI 0.10 [V]; M6 0.15 [V]; Numerai One SR 2.75 (one year) [V]; Medallion 50.75% on millions of trades [V] |

---

## 9. Where SuryaDhana sits

| Dimension | SuryaDhana | Rung | Comparison |
|---|---|---|---|
| IC level | 0.04–0.05 (NW t ≈ 3) | **2** | Equals Qlib LightGBM (0.045 CSI300, 0.040 CSI500). At MSCI's "good" line; M6's "moderate". Above Numerai participants (0.017–0.025, but on neutralised targets). |
| IC stability | 0.46–0.88 per month (§2 arithmetic) | **1–2** | Below Numerai live (1.32) and validation (2), and far below Qlib's daily t ≈ 11 |
| Hit rate | ≈52% | **2** | Consistent with IC ≈ 0.063 (sin(0.02π)). AUC 0.5366 gives Somers' D = 2 × 0.5366 − 1 = 0.073. |
| Net economics | +4.2%/yr vs EW; IR 0.99, CI [−2.36, 4.34]; PSR 0.75; DSR 0.08; fitness ≈ 0.57 | **1 (unproven)** | In the same window a plain momentum baseline earned IR 1.57 (+11.5% vs EW) (`STRATEGY.md`) |
| Track record | 5.5 months paper | **below 2** | Below every platform's 6-month minimum. `STRATEGY.md` estimates ≈705 trading days (≈2.8 years) to PSR 95% at the observed IR. |

**Verdict**
- **Signal: good enough.** On signal quality SuryaDhana is a **rung-2 model**. Its IC equals what Microsoft's reference LightGBM achieves in China and what wins live crypto competitions, and its hit rate is in the range practitioners call a real edge.
- **Economics: not yet good enough.**
  - IC stability is below the Numerai and Qlib benchmarks.
  - The paper book is too short to separate skill from luck. That is the JPX lesson, where even the winner was within the luck range.
  - The model did not beat a simple momentum baseline in the same window.
  - It fails every allocator's track-record and significance test: WorldQuant's 5-year Sharpe of 1.25, QuantConnect's PSR(SR > 1) ≥ 80%, and DSR ≥ 0.95.

**What would move it up a rung**
1. Beat the momentum and EW baselines over the 5-year walk-forward.
2. Report IC after neutralising momentum, size and sector, to show the unique edge (Numerai's MMC/BMC lesson).
3. Accumulate about 2.5–3 years of live or paper record at IR ≈ 1.
4. Pass DSR ≥ 0.95 with the true number of trials.

---

## 10. Sources

**Numerai**
1. Numerai docs, CORR [V]: https://docs.numer.ai/numerai-tournament/scoring/correlation-corr
2. Numerai docs, Scoring [V]: https://docs.numer.ai/numerai-tournament/scoring
3. Numerai docs, Staking [V]: https://docs.numer.ai/numerai-tournament/staking
4. Numerai docs, Signals scoring [V]: https://docs.numer.ai/numerai-signals/scoring
5. Forum, small LGBM hyperparameters [V]: https://forum.numer.ai/t/hyperparameters-optimization-for-small-lgbm-models/6693
6. Forum, Better LGBM params (Numerai team) [V]: https://forum.numer.ai/t/better-lgbm-params-signals-v2-data-and-reducing-signals-churn/7638/1
7. Forum, MMC and other metrics [V]: https://forum.numer.ai/t/mmc-and-other-metrics-for-all-targets/6839
8. Forum, What is a good Sharpe and validation correlation [V]: https://forum.numer.ai/t/what-is-a-good-sharpe-ratio-and-validation-correlation/419
9. GitHub, vladmurnik numerai-lgbm-ensemble [V]: https://github.com/vladmurnik/numerai-lgbm-ensemble
10. Numerai blog, JPMorgan capacity / 2024 performance [V]: https://blog.numer.ai/jpmorgan-secures-500m-capacity/
11. Numerai blog, Meta Model Supremacy (2019) [V]: https://blog.numer.ai/achieving-meta-model-supremacy-at-numerai/
12. AUM ≈ $700m, July 2026 press release [S]: https://decrypt.co/373781

**Competitions**

13. Two Sigma 2017, participant talk [V]: https://notebook.community/happycube/kaggle2017/twosigma/talk-v2
14. Two Sigma 2017, participant blog [V]: https://smist08.wordpress.com/2017/03/13/playing-the-kaggle-two-sigma-challenge-part-5/
15. Jane Street 2021, team write-up [V]: https://github.com/scaomath/kaggle-jane-street
16. Jane Street 2021, silver write-up 4,369.344 [S]: https://github.com/Leo1998-Lu/Kaggle-Jane-Street-Market-Prediction-Silver-Medal-solution
17. JPX 2022, official winners table [V]: https://github.com/J-Quants/JPXTokyoStockExchangePrediction
18. JPX 2022, evaluation over 3 months (participant README) [S]: https://github.com/Adam-Chellaoui/Predicting-the-Japan-Stock-Market-Kaggle-Challenge
19. JPX 2022, metric discussion [S]: https://www.kaggle.com/competitions/jpx-tokyo-stock-exchange-prediction/discussion/335393
20. Ubiquant 2022, leaderboard [S]: https://www.kaggle.com/competitions/ubiquant-market-prediction/leaderboard
21. Ubiquant 2022, 1st-place write-up [S]: https://www.kaggle.com/competitions/ubiquant-market-prediction/writeups/k-i-y-1st-place-solution-our-betting-strategy
22. Optiver Realized Volatility 2021, 1st-place notebook [S]: https://www.kaggle.com/code/nyanpn/1st-place-public-2nd-place-solution?scriptVersionId=85907908
23. Optiver Trading at the Close 2023, leaderboard [S]: https://www.kaggle.com/competitions/optiver-trading-at-the-close/leaderboard
24. Optiver Trading at the Close, independent holdout study [V]: https://github.com/andrew-somerset/optiver-trading-at-the-close
25. G-Research Crypto 2022, organiser wrap-up [V]: https://www.gresearch.com/news/wrapping-up-the-g-research-crypto-forecasting-competition/
26. G-Research Crypto 2022, leaderboard [S]: https://www.kaggle.com/competitions/g-research-crypto-forecasting/leaderboard
27. Two Sigma News 2019, Chan & Hunter slides [V]: https://epchan.com/img/links/What-we-learned-from-Kaggle-Two-Sigma-News-Sentiment-competition.pdf
28. M6 competition paper (Makridakis et al., 2023) [V]: https://arxiv.org/pdf/2310.13357

**WorldQuant**

29. quantt.co.uk BRAIN review (Oct 2026) [V]: https://www.quantt.co.uk/resources/worldquant-brain
30. alexisdpc, BRAIN simulator docs [V]: https://github.com/alexisdpc/WorldQuant-alpha-trading
31. jglazar, IQC project [V]: https://jglazar.github.io/projects/wq_project/
32. Kakushadze, 101 Formulaic Alphas [V]: https://arxiv.org/abs/1601.00991
33. WorldQuant BRAIN pages (no thresholds published) [S]: https://www.worldquant.com/brain/

**Qlib**

34. Qlib benchmarks README [V]: https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md
35. Qlib LightGBM Alpha158 config [V]: https://github.com/microsoft/qlib/blob/main/examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml
36. Qlib docs, example label [S]: https://qlib.readthedocs.io/en/latest/advanced/alpha.html

**Platforms**

37. Quantopian study (Quantpedia summary) [V]: https://quantpedia.com/quantopians-academic-paper-about-in-vs-out-of-sample-performance-of-trading-alg/
38. Quantopian contest tutorial [S, 503]: https://www.quantopian.com/tutorials/contest
39. Quantopian archive, accept/reject alpha factors [V]: https://quantopian-archive.netlify.app/forum/threads/how-to-accept-slash-reject-alpha-factors.html
40. Quantopian archive, contest criteria thread [V]: https://quantopian-archive.netlify.app/forum/threads/quantopian-contest-criteria-and-high-risk-high-reward-algos.html
41. QuantConnect, PSR filters thread [V]: https://www.quantconnect.com/forum/discussion/11497/are-filters-required-for-alpha-market-strategies-for-example-psr-realistic/
42. QuantConnect, 9 ways to get rejected [V]: https://www.quantconnect.com/forum/discussion/6737/9-ways-to-get-your-alpha-rejected/
43. QuantConnect docs, Submitting an Alpha [S, now 404]: https://www.quantconnect.com/docs/v2/alpha-streams/user-guides/submitting-an-alpha

**Rules of thumb**

44. MSCI Barra, Converting Scores into Alphas (2010) [V]: https://www.msci.com/documents/10199/1645561/PI_Converting_Scores_Into_Alphas.pdf/7adf1f42-10aa-40eb-9e8c-ecc11eeba2d4
45. Zhipeng Yan, Active Portfolio Management notes [S, 503]: https://people.brandeis.edu/~yanzp/Study%20Notes/Active%20Portfolio%20Management.pdf
46. Fundamental law explainer [V]: https://quantmemo.com/writing/paper-grinold-fundamental-law
47. López de Prado, Nomura slides (2015) [V]: https://www.nomura.com/events/9th-annual-global-quantitative-investment-strategies-conference/resources/upload/10_00_Marcos_Lopez_de_Prado_20150510.pdf
48. Institutional Investor, Medallion and 50.75% (2020) [V]: https://www.institutionalinvestor.com/article/2bswymr8cih3jeaslxc00/portfolio/famed-medallion-fund-stretches-explanation-to-the-limit-professor-claims
49. IBTimes, Man AHL / Ledford (2017) [V]: https://www.ibtimes.co.uk/hedge-fund-firm-man-ahl-cuts-through-noise-around-machine-learning-1605637

**India**

50. SEBI circular, 4 Feb 2025 (CSE-hosted copy) [V]: https://www.cse-india.com/upload/upload/Feb_042025.pdf
51. SEBI PR 22/2024 [V]: https://www.sebi.gov.in/sebi_data/attachdocs/sep-2024/1727086965496.pdf
52. Taxmann, deadline extension [S]: https://www.taxmann.com/post/blog/sebi-extends-deadline-for-retail-algo-trading-framework
53. Tradejini, April 2026 rules [S]: https://www.tradejini.com/blogs/what-sebis-new-algo-trading-rules-mean-for-you
54. AlgoTest blog (vendor claim) [V]: https://algotest.in/blog/algo-trading-india/
