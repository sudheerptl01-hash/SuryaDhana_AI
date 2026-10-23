# SuryaDhana improvement phase: results against the pre-registered plan

**Dates:** 2026-10-19 (plan fixed, streams started) to 2026-10-22 · **Plan:** `ml/IMPROVEMENT_PLAN.md` (pass marks fixed before any result; amendments A1-A4 dated in its section 5) · **Trial ledger:** N = 241 (177 from the five-year run + 64 new configurations and books) · **Status: complete (every pre-registered test has a result).**

**Corrections (2026-10-23, from improvement phase 2; `ml/results/improve2/IMPROVEMENT_RESULTS.md` sections 2 and 10):** (1) research books exclude the 0.33% of rows that fail the forward-looking `y_clean_20d` screen (mostly crashes), which flatters their excess by about 0.4 pp a year; the live paper books hold every name. (2) The seed-108 control's liquid neutral book is its unluckiest of four seeds (+1.2% a year against +1.8% to +2.3% on the ten-year data), so paired book comparisons against it were slightly flattered; ranking (AUC) comparisons are not affected (seed sd 0.0003). (3) Three research-period consolidations (KAUSHALYA 2024-01-12, SHEKHAWATI 2024-08-28, VERTOZ 2025-06-25) remain unadjusted in the research store because the parser missed the "CNSLDATN" spelling; their jump rows are not universe rows of the ten-year dataset (`ml/ROADMAP.md` section 3).

Every number below is quoted from the stream's JSON/Markdown named in its section. "PASS" and "FAIL" refer to the pass marks written in the plan before the result existed.

## 1. One-page summary

| Question the plan asked | Pre-registered test | Result | Verdict |
|---|---|---|---|
| Is the data sound? | I1-I4 (sessions complete, corporate actions validated, split flags fall, no ETFs) | 6 missing and 3 mis-dated sessions fixed; 501 split/bonus events adjusted, 98.0% agree with observed prices; split flags 0.557% → 0.095% of rows; 0 ETFs left | **4 of 4 PASS** |
| Can a single model's book beat the universe by construction rather than by accident? | B1: vol+size-neutral top decile beats EW net of 20 bps, IR CI > 0, IR ≥ 0.5 | nested LightGBM −0.7% → **+6.9%/yr**, IR 1.92 [0.99, 3.01]; all-features LightGBM −1.2% → **+6.5%/yr**, IR 1.85 [0.93, 2.93] | **PASS** |
| Is turnover the first economic lever? | B2 (buffer cuts turnover ≥ 30% at no cost); B3 (40-session hold within 1 pp at half the turnover) | buffer cuts 18-26%, never costs excess (11 of 12 pairs higher); 40-session hold: excess −0.2 to −1.0 pp, turnover 0.54-0.55× | **B2 FAIL, B3 FAIL** |
| Does any book clear the capital gates? | gates 3 and 5 at N = 238 | gate 3: all-features book 34/45 months PASS, nested 33/45 FAIL; gate 5: liquid-book DSR 0.000 both | **FAIL: no capital** |
| Was the five-year selection luck? | CSCV probability of backtest overfitting > 0.5 = chance | 0.248 (models), 0.184 (books), 0.227 (long-only books); winner's out-of-sample Sharpe about 20-30% of in-sample | **better than chance; record inflated** |
| Is the delivery signal durable? | residual IC > 0 in ≥ 3 of 4 years and both liquidity halves | `deliv_pct_sma_20` 3 of 4 years, both halves; `deliv_value_share_20` 4 of 4 | **PASS, both** |
| Do the two sufficiency features earn their place? | AB0: 52 vs 50 features, +0.003 with CI > 0 | +0.0014 [+0.0002, +0.0026] | **FAIL** (real but below the bar) |
| Do overlapping labels distort the fit? | AB7 (every fifth date), AB8 (uniqueness weights) vs control | −0.0020 [−0.0041, −0.0000]; +0.0011 [−0.0002, +0.0023] | **FAIL both; item closed** |
| Does the corrected data change the signal? | re-run on v2 (descriptive) | control 0.5359 ± 0.032 (v1 0.5379 ± 0.042), worst month 0.466 (0.453), 88% of months ≥ 0.50 (84%), rank IC 0.069 (NW t 7.3) | **same signal, less dispersion** |
| Does information outside the bhavcopy add signal? | AB1-AB6, AB2P: +0.003 with CI > 0 | market state −0.0047; sector +0.0013 (placebo −0.0020); F&O **+0.0020 [+0.0006, +0.0032]**; flows −0.0004; all +0.0024 [−0.0043, +0.0082]; ensemble on 52 features −0.0017 | **all FAIL** (F&O real but below the bar) |
| Does the signal hold across eight years and three cycles? | ten-year re-runs, Stage-0 criteria | 103 folds: AUC 0.5455 [0.5359, 0.5549], above 0.50 in every calendar year 2018-2026, 0.5434 without the best six-month run and the worst month; rank IC 0.088 (NW t 9.8) | **met over eight years** |

**Reading.** The data are now clean enough to trust, the signal holds over eight years and three market cycles, and the economics have a mechanism: a deliberately volatility- and size-neutral top decile built from the LightGBM score beats the equal-weight universe net of 20 bps in every calendar year from 2018 to 2026 (+10.5% a year over 105 months, IR 2.32 [1.51, 3.10]). What has not changed is the proof, and one thing got worse: the liquid, capacity-bearing version of that book earned nothing over 2018-2022 (−0.08% per 20 sessions, 30 of 60 months ahead) and +0.37% per 20 sessions over 2023-2026, so its ten-year excess is +1.2% a year with an interval that includes zero. The economics sit in names trading under ₹5 to 10 crore a day, where costs are least known and the control's neutral book carries about ₹157 to 214 crore (the ensemble's ₹200 to 280 crore). Every Deflated Sharpe is far below 0.95 at N = 241, and the construction was read from the five-year folds it was first tested on. The verdict stays **no capital; paper-trade one frozen construction**, now a deliberate one, with its small-cap nature stated.

## 2. Data integrity (P1; `integrity/INTEGRITY.md`, `integrity/integrity.json`)

- **Sessions.** Six sessions the ingest never requested (two weekend Budget sessions, two Saturday special sessions, two Muhurat sessions) were loaded: 15,393 rows. Three closures carried another day's file and were re-dated (2021-11-05 → 2021-11-04, 2023-06-29 → 2023-06-28, 2024-01-22 → 2024-01-20). The 2022-03-07 security-wise file lacked every BE/BZ security; 275 rows were rebuilt from the CM bhavcopy and 1,679 more BE/BZ rows over 28 sessions in mid-2023. After the fix the ingest's `trading_days()` matches the archive's PR-bundle calendar on all 1,842 calendar days, and the continuity scan (I1) finds no session with more than 0.15% of names mismatching (before: 99%).
- **Corporate actions.** The daily `bc` files yield 21,963 records; 510 split/bonus/consolidation events fall inside the price history and 500 agree with the observed ex-date price ratio within ±15% (I2 98.0%; the 10 disagreements are listed). 501 validated events now adjust 230,722 rows. NESTLEIND's 2024-01-05 split, IRCTC 2021-10-28, TATASTEEL 2022-07-28 and RELIANCE's 2024-10-28 bonus all reduce to ordinary daily moves (−1.7%, +10.6%, +4.6%, +0.5% against −90%, −78%, −90%, −50% unadjusted). Rights issues, demergers and capital reductions (341 dates) cannot be adjusted from the feed and are written to `price_break_flags.csv` for label masking.
- **ETFs.** 469 symbols from the daily lists; the label study's name rule had missed 61 of the ETFs in the v1 data and wrongly flagged two operating companies. 215 ETF tickers (74,545 rows, 5.5%) leave the universe (I4).
- **v2 dataset.** 1,290,062 rows, 2,265 tickers, 1,002 sessions (v1: 1,357,383, 2,480, 996), 43 folds and the same holdout; eight fold boundaries move by one or two sessions. `flag_split_20d` falls from 0.557% to 0.095% of rows and `y_clean_20d` coverage rises from 96.67% to 97.23% (I3). The ₹10 price floor is applied to the raw close so that a later split cannot drop past rows from the universe.
- **Write discipline.** One read-write window of 86 s under a lock file; idempotent (a second run changes nothing); backup taken first.
- **Ten-year store** (`integrity/INTEGRITY_10Y.md`). The 2016-10..2021-09 staging rows were loaded in a second 127 s write window: 5,237,728 rows over 2,489 sessions (2016-10-03 to 2026-10-16); 2,142,087 history rows (118 non-equity series left out); zero duplicate pairs; nothing dated 2021-10 or later changed except through adjustment factors, and no factor changed. The merged corporate-action feed holds 755 validated events (I2 on the extended window 254 of 266 = 95.5%, narrowly; whole feed 754 of 776 = 97.2%); RELIANCE 2017, YESBANK 2017, TCS 2018, INFY 2018 and HDFCBANK 2019 reduce to ordinary daily moves. I1 over ten years: largest mismatch share 0.31%, no session flagged. The ten-year dataset (`ml/data_10y/`) has 2,226,504 rows, 2,514 tickers, 2,241 sessions, the same 52 features as v2, 103 monthly folds 2018-01..2026-07 (v2's 43 folds identical inside them) and the same holdout; `y_clean_20d` 98.24%, `flag_split_20d` 0.145%, 0 ETF rows. The first fold trains on 32,571 rows over 41 sessions, so 2018 is small-sample exactly as 2023 was in the five-year run.

## 3. Book construction on the five-year scores (P2; `books/BOOKS.md`, `books/books.json`)

Acceptance test: the 24 five-year books reproduce `portfolio_5y.json` exactly (8,160 numbers, max difference 0). Grid: 3 scorers × 4 neutralisations × 3 baskets + 3 liquid buffered + 3 forty-session = 42 books, DSR with the cross-trial variance of all 66 books.

| Book (net 20 bps, vs equal-weight universe) | Excess/yr | IR [95% CI] | Months ahead | Turnover | DSR (N = 238) |
|---|---:|---|---:|---:|---:|
| nested LightGBM, plain top decile (five-year run) | −0.7% | −0.11 [−1.21, +0.96] | 20/45 | 67% | 0.000 |
| nested LightGBM, **vol+size-neutral** top decile | **+6.9%** | +1.92 [+0.99, +3.01] | 33/45 | 76% | 0.053 |
| all-features LightGBM, vol+size-neutral top decile | +6.5% | +1.85 [+0.93, +2.93] | 34/45 | 77% | 0.038 |
| rank ensemble, plain top decile (five-year run) | +7.0% | +1.26 [+0.32, +2.37] | 33/45 | 70% | 0.002 |
| rank ensemble, vol+size-neutral top decile | +10.5% | +2.74 [+1.60, +3.90] | 38/45 | 73% | 0.469 |
| rank ensemble, vol+size-neutral buffered decile | +10.7% | +2.70 [+1.61, +3.88] | 39/45 | 56% | 0.434 |
| nested LightGBM, vol+size-neutral **liquid** buffered decile (paper-book shape) | +5.0% | +0.81 [−0.14, +1.93] | 29/45 | 67% | 0.000 |

- **Mechanism.** Neutralising removes the tilt (score correlation with `atr_pct` −0.31 → −0.03) while keeping the ranking (Spearman 0.92 with the raw score); the neutral book earns in up and down months and in every calendar year. Volatility does most of the work, size sharpens it, the industry step halves the excess (only 47% of names carry an NSE industry, so it partly adjusts for index membership).
- **Costs.** Neutral baskets move into smaller names (median name ADV ₹28.8 → ₹7.0 crore; 43% under ₹5 crore a day). Flat break-even 53-56 bps per side. The pre-specified name-level model (Corwin-Schultz half-spread + square-root impact, ₹100 crore book) charges about 45 bps per side and leaves +1.5% to +2.0% a year; under it the buffer and the 40-session hold add 1.1 to 2.0 points. That model is pessimistic for large caps (12-16 bps half-spreads for RELIANCE, HDFCBANK, INFY, TCS against real quoted spreads of a few bps).
- **Deflation.** Adding 42 books raises the cross-trial Sharpe variance from 0.0017 to 0.0039, so the expected best null Sharpe is 2.79 a year at N = 238. The B1 books' DSR is 0.05 and 0.04; the best book's 0.47.
- **Caveat the stream states itself:** the neutralisation idea was read from these 43 folds (program report §6.3 finding 3), so B1 is a consistency check, not an independent confirmation.

## 4. Hygiene and delivery durability (P5; `hygiene/HYGIENE.md`)

- **Probability of backtest overfitting** (CSCV, S = 16, 12,870 splits): 0.248 for the 9 configurations × 43 monthly AUCs, 0.184 for the 24 books × 45 months, 0.227 for the 16 long-only books; chance level 0.50-0.56. The in-sample winner (usually the nested logistic among models, the ensemble among books) finished in the out-of-sample top half three times out of four, but its out-of-sample Sharpe was 21-29% of its in-sample figure and the winning long-only book lost to its benchmark in 33% of splits. Ranking is informative; the size of past performance is inflated.
- **Delivery.** Residual IC (after per-date regression on turnover, volatility and 12-1 momentum) is +0.045 (t 5.6) for `deliv_pct_sma_20` and +0.047 (t 6.9) for `deliv_value_share_20`, positive with CI clear of zero in 3 of 4 and 4 of 4 calendar years and in both liquidity halves: **PASS**. The raw IC is not durable in the same sense (+0.006 in 2023; +0.013 in up months against +0.124 in down months), and its fall after March 2026 (+0.059 → +0.012) sits entirely in the part that volatility and turnover explain (+0.046 → +0.042 residual). In the most liquid third the signal is a falling-market effect (residual IC +0.003 in up months, +0.089 in down months).
- **Uniqueness.** Average uniqueness is 1/21 for 82% of training rows and within ±10% of it for 87.5% (threshold 95% fixed before computing), so the item stayed open and became AB7/AB8 (section 6): closed with evidence.

## 5. External data and history (P3, P4; `extdata/EXTDATA.md`, `history/HISTORY.md`)

- **New sources, all from the NSE archive and all reachable:** stock futures and options (2016-10 to 2026-10, 465,528 stock-day rows; 185-216 members a day), every NSE index with P/E, P/B and India VIX (247,808 index-days), participant-wise open interest (FII/DII/Pro/Client), the NSE industry classification (755 symbols, 22 industries), the equity master. Four fixed feature families (market state 10, sector 10, F&O 8, flows 4) are built point-in-time; three checks pass (independent recomputation of 900 cells, deletion of all files dated after t for one month including the July-2024 format switch, bit-identical shift test), and the base series match the v2 dataset exactly.
- **Look-ahead found and controlled.** The industry lists are a 2026 snapshot; membership in them predicts the 20-day label in 2022-2025 (AUC 0.53-0.56 against 0.50-0.54 for a point-in-time size flag) because names that rose are over-represented. Amendment A3 registers a placebo (industry labels permuted among classified names): the sector family counts only if it beats the placebo too.
- **History 2016-10 to 2021-09:** 1,238 sessions, 2,356,697 rows (2,035,125 EQ/BE) from the legacy CM bhavcopy, MTO delivery files and PR bundles; the two overlap days match the store on all 12 fields for all 3,594 rows; continuity worst day 0.12%; all six weekend/holiday sessions present; archive defects documented (a PR bundle holding another year's data, two MTO files with BSE records, the 2017-07-10 outage day).

## 6. Model A/Bs on the frozen v1 data (`ab/v1/AB.md`)

| Variant − control (52 features) | Δ CV-mean AUC | 95% CI | Folds won | Δ rank IC (NW t) | Verdict |
|---|---:|---|---:|---|---|
| 50 features (AB0, sign reversed: 52 beats 50 by) | +0.0014 | [+0.0002, +0.0026] | 27/43 | +0.0028 (2.4) | **FAIL** (below +0.003) |
| every fifth signal date (AB7) | −0.0020 | [−0.0041, −0.0000] | 18/43 | −0.0037 (−1.8) | **FAIL** |
| uniqueness weights (AB8) | +0.0011 | [−0.0002, +0.0023] | 25/43 | +0.0019 (1.5) | **FAIL** |

As books (vol+size-neutral top decile): AB7 +6.9%/yr IR 2.19, AB8 +7.8%/yr IR 2.22, control +7.2%/yr IR 2.05: all the same book within the intervals.

## 7. Corrected data (v2) re-runs (`ab/v2/AB.md`, `ab/v2/BOOKS_AB.md`)

| Configuration | CV AUC ± sd | 95% CI | Months ≥ 0.50 | Worst | Holdout | Rank IC (NW t) |
|---|---|---|---:|---:|---:|---|
| LightGBM, 52 features (control) | 0.5359 ± 0.0320 | [0.5274, 0.5456] | 88% | 0.466 | 0.5203 | +0.069 (7.3) |
| L2 logistic, 52 features | 0.5396 ± 0.0494 | [0.5264, 0.5543] | 84% | 0.402 | 0.5003 | +0.074 (5.1) |
| momentum rule | 0.4954 ± 0.0309 | [0.4866, 0.5034] | 42% | 0.431 | 0.4690 | −0.011 |

Logistic minus control +0.0037 [−0.0043, +0.0125]: gate 1 still fails for the tree model, and the logistic model still has the worst tails (worst month 0.402, holdout 0.500). Books on v2: control plain top decile −0.0%/yr (19/45 months); **vol+size-neutral top decile +7.8%/yr, IR 1.99 [0.91, 3.17], 34/45 months, capacity ₹214 crore, DSR 0.062**; liquid neutral book +5.9%/yr, IR 1.04 [0.03, 2.15], capacity ₹912 crore, DSR 0.000.

## 8. External-data A/Bs on the corrected data (`ab/v2/AB.md`, `ab/v2/BOOKS_AB.md`, `ab/v2/GATES.md`)

Control = LightGBM on the 52 features, v2 data, 43 folds; every variant adds one fixed family (plan P3) and is scored on identical folds with identical bootstrap draws.

| Variant | Features | CV AUC ± sd | Δ vs control | 95% CI | Folds won | Δ rank IC (NW t) | Holdout | Primary | Secondary |
|---|---:|---|---:|---|---:|---|---:|---|---|
| control | 52 | 0.5359 ± 0.0320 | | | | | 0.5203 | | |
| AB1 market state | 62 | 0.5312 ± 0.0363 | −0.0047 | [−0.0115, +0.0018] | 22/43 | −0.0074 (−1.1) | 0.5184 | FAIL | FAIL |
| AB2 sector (industry snapshot) | 62 | 0.5372 ± 0.0332 | +0.0013 | [−0.0013, +0.0039] | 22/43 | +0.0045 (1.7) | 0.5223 | FAIL | FAIL |
| AB2P sector placebo (industries permuted) | 62 | 0.5339 ± 0.0341 | −0.0020 | [−0.0062, +0.0014] | 22/43 | −0.0026 (−0.7) | 0.5290 | FAIL | FAIL |
| AB3 F&O (membership, basis, OI, put/call) | 60 | 0.5379 ± 0.0319 | **+0.0020** | **[+0.0006, +0.0032]** | 26/43 | +0.0032 (2.7) | 0.5198 | FAIL (below +0.003) | **PASS** |
| AB4 flows (FII/DII/client positioning) | 56 | 0.5355 ± 0.0406 | −0.0004 | [−0.0059, +0.0045] | 22/43 | −0.0011 (−0.2) | 0.5595 | FAIL | FAIL |
| AB5 all four families | 84 | 0.5383 ± 0.0396 | +0.0024 | [−0.0043, +0.0082] | 29/43 | +0.0075 (1.1) | 0.5291 | FAIL | FAIL |
| AB6 rank ensemble on 52 features, no re-selection | 52 | 0.5343 ± 0.0301 | −0.0017 | [−0.0065, +0.0024] | 23/43 | −0.0052 (−1.1) | 0.5557 | FAIL | FAIL |
| AB6 member: CatBoost, 52 features | 52 | 0.5376 ± 0.0351 | +0.0017 | [+0.0002, +0.0031] | 29/43 | +0.0024 (1.7) | 0.5211 | FAIL | FAIL |
| AB6 member: LambdaRank, 52 features | 52 | 0.5054 ± 0.0389 | −0.0305 | [−0.0469, −0.0167] | 16/43 | −0.0609 (−3.9) | 0.5926 | FAIL | FAIL |

- **No family passes the primary mark.** The one real addition is the F&O family: +0.0020 AUC with an interval clear of zero and a rank-IC gain with Newey-West t 2.7, the same size as the two sufficiency features (AB0) and below the +0.003 the plan demanded. Market state hurts (and the inversion months get worse, −0.008, not the +0.02 required); flows add nothing; everything together adds +0.0024 with an interval that includes zero.
- **The sector family is the look-ahead, not industry information.** AB2 beats the placebo by +0.0033 on AUC, but the plan's reading requires the primary mark first, which it fails; and the placebo's *book* is almost as good as the real sector book (below), which is what index-membership survivorship predicts.
- **The ensemble does not need yearly re-selection.** On 52 features without selection it scores 0.5343 (the five-year nested ensemble 0.5330) and its plain top decile earns +7.7%/yr, IR 1.57 [0.62, 2.70] (nested: +7.0%, IR 1.26). Item 4 of the program report's §11 is answered: selection buys nothing for the ensemble either.

**As books** (P2 construction: per-date volatility+size-neutral top decile; liquid-tercile version in brackets; net 20 bps vs the equal-weight universe; DSR at N = 241):

| Configuration | Plain top decile | Neutral top decile | Neutral, liquid tercile |
|---|---|---|---|
| control | −0.0%/yr, IR +0.01 | **+7.8%/yr, IR 1.99 [0.91, 3.17], 34/45 months, DSR 0.062** | +5.9%/yr, IR 1.04 [0.03, 2.15], DSR 0.000 |
| AB1 market state | +0.6%, IR 0.13 | +7.8%, IR 2.27 [1.31, 3.26], DSR 0.158 | +4.2%, IR 0.78 [−0.23, 1.88] |
| AB2 sector | +2.8%, IR 0.58 | +10.9%, IR 3.16 [2.19, 4.19], DSR 0.758 | +6.1%, IR 1.14 [0.12, 2.27] |
| AB2P placebo | +1.4%, IR 0.31 | +10.1%, IR 2.99 [2.00, 3.97], DSR 0.647 | +5.0%, IR 0.97 [−0.07, 2.08] |
| AB3 F&O | +0.7%, IR 0.16 | +8.1%, IR 2.12 [1.15, 3.18], DSR 0.099 | +5.7%, IR 1.13 [0.20, 2.13] |
| AB4 flows | +4.4%, IR 0.82 | +6.1%, IR 1.83 [0.64, 3.03], DSR 0.035 | +2.7%, IR 0.52 [−0.42, 1.54] |
| AB5 all | +5.2%, IR 1.01 | +10.4%, IR 3.18 [2.20, 4.26], DSR 0.759 | +6.3%, IR 1.27 [0.38, 2.31], DSR 0.002 |
| AB6 ensemble on 52 | +7.7%, IR 1.57 [0.62, 2.70] | +10.8%, IR 2.87 [1.76, 3.96], DSR 0.561 | **+9.1%, IR 1.58 [0.42, 2.82], DSR 0.011** |

The sector and all-family books look best, but the placebo book (industries permuted) is within a point of them: those gains are the partition of today's index members, which the live book could not know. Every liquid book's DSR is at most 0.011.

**Gates at N = 241** (`ab/v2/GATES.md`; gate 4 does not apply to configurations that select nothing): every configuration fails gate 1 (none beats the logistic benchmark with an interval clear of zero), gate 2 (best 88% of months ≥ 0.50, bar 90%) and gate 5 (liquid-book DSR ≤ 0.011). Gate 3 passes for the neutral top decile of the control (34/45), AB1, AB2, AB2P, AB5 and both AB6 ensemble books, and for the plain top decile of the ensemble (34/45). **Nothing is promoted.**

## 9. Eight years instead of five (`ab/10y/AB.md`, `ab/10y/BOOKS_AB.md`, `ab/10y/GATES.md`)

The ten-year dataset's 103 monthly folds (2018-01 to 2026-07; 2,126 CV dates) span the 2018 small-cap bear, the 2020 crash and the 2021 boom. Same protocol, same configurations, no tuning.

| Configuration | CV AUC ± sd | 95% CI | Months ≥ 0.50 | Worst | Holdout | Rank IC (NW t) | IC months positive |
|---|---|---|---:|---:|---:|---|---:|
| LightGBM, 52 features (control) | **0.5455 ± 0.0491** | [0.5359, 0.5549] | 84% | 0.399 (2020-11) | 0.5193 | +0.088 (9.8) | 87/103 |
| L2 logistic, 52 features | 0.5423 ± 0.0681 | [0.5297, 0.5545] | 74% | 0.341 | 0.5003 | +0.082 (6.6) | 79/103 |
| momentum rule | 0.5000 ± 0.0420 | [0.4930, 0.5073] | 47% | 0.369 | 0.4690 | +0.001 (0.1) | |

Mean fold AUC by calendar year (control / logistic / momentum): 2018 0.548 / 0.558 / 0.500; 2019 0.575 / 0.566 / 0.518; 2020 0.561 / 0.530 / 0.510; 2021 0.527 / 0.516 / 0.498; 2022 0.528 / 0.530 / 0.500; 2023 0.535 / 0.534 / 0.494; 2024 0.553 / 0.553 / 0.494; 2025 0.544 / 0.561 / 0.479; 2026 (7 months) 0.534 / 0.525 / 0.510. The 2018 folds train on short windows (32,571 rows for 2018-01), as 2023 did in the five-year run.

- **Stage-0 "not one regime" criterion: met.** The control's best six-month run is 2019-09 to 2020-02 (mean 0.603); without it and the worst month the other 96 folds average 0.5434. It is above 0.50 in 82% of the 2018-2022 months and 88% of the 2023-2026 months; the 2018-2022 half (0.5478) is as strong as the 2023-2026 half (0.5359 on v2).
- **The tree model now has the higher mean**, +0.0032 over the logistic [−0.0033, +0.0104], 55 of 103 folds: gate 1 still fails (interval includes zero), and the logistic still has the worst tails (worst month 0.341, 74% of months ≥ 0.50, holdout 0.500).

**Books over 105 signal months** (2018-01 to 2026-09; net 20 bps vs the equal-weight universe; per-20-session figures by period):

| Control book | Excess/yr | IR [95% CI] | Months ahead | 2018-2022 | 2023-2026 | Capacity | DSR (N = 241) |
|---|---:|---|---:|---:|---:|---:|---:|
| plain top decile | +7.5% | +1.37 [+0.51, +2.21] | 69/105 | +0.95% (45/60) | +0.07% (24/45) | ₹168 cr | 0.000 |
| volatility+size-neutral top decile | **+10.5%** | **+2.32 [+1.51, +3.10]** | 83/105 | +0.90% (47/60) | +0.74% (36/45) | ₹157 cr | 0.081 |
| plain, liquid tercile | −0.0% | +0.01 [−0.73, +0.71] | 52/105 | +0.12% (33/60) | −0.23% (19/45) | ₹785 cr | 0.000 |
| neutral, liquid tercile | +1.2% | +0.21 [−0.52, +0.93] | 55/105 | −0.08% (30/60) | +0.37% (25/45) | ₹603 cr | 0.000 |

The neutral top decile is ahead of the universe in every calendar year 2018-2026 (per 20 sessions: +0.21, +0.81, +1.56, +0.97, +0.94, +0.41, +0.88, +0.35, +1.52%) and in up and down months (+0.98% / +0.60%). The plain decile worked before 2023 (+0.95% per 20 sessions) and stopped (+0.07%): the volatility tilt's cost is a 2023-2026 phenomenon, which is why the five-year run saw it and the ten-year run dilutes it. **The liquid book does not work over ten years**: whatever its 2023-2026 excess was, 2018-2022 took it back. The logistic model's neutral top decile is also positive in both halves (+9.5%/yr, IR 1.92 [1.05, 2.78]).

**Gates at N = 241 (ten-year control):** gate 1 fail (+0.0032 [−0.0033, +0.0104]); gate 2 fail (84%); gate 3 plain fail (66%), neutral pass (79%); gate 5 fail (liquid-book DSR 0.000, plain and neutral). **Nothing is promoted.**

## 10. What this phase changes, and what it does not

1. **The data are fixed** and the fixes are reproducible from the archive (sessions, corporate actions, ETFs, ten years of history). This is the one unconditional gain.
2. **The paper book is now a deliberate construction** with a stated mechanism and eight years of in-sample support, not an accidental blend read off 43 folds. Its specification: LightGBM on 52 features, score residualised per date on volatility and size ranks, top decile (or the buffered decile), 20-session hold, equal-weight universe benchmark, 20 bps and name-level costs both reported. The all-feature rank ensemble is the champion-challenger.
3. **Its economics are a small-cap effect.** The liquid-tercile version earns nothing over ten years; the paper book that is worth watching carries about ₹160 to 215 crore (control) or ₹200 to 280 crore (ensemble) and costs that the pessimistic name-level model puts at about 45 bps a side (leaving +2% to +4% a year). Any capital decision would need the liquid book to work, and the record says it has not.
4. **Information outside the bhavcopy adds little**: the F&O family is real (+0.0020 AUC, interval clear of zero) and below the bar; sector gains are look-ahead; market state and flows add nothing. The next information gain, if any, is fundamentals and filings, which need a feed this environment does not have (`ml/ROADMAP.md`).
5. **Nothing passes the capital gates**, and the trial ledger now stands at N = 241. The forward record remains the only route to Stage 2.
