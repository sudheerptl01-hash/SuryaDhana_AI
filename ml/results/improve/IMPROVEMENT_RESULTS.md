# SuryaDhana improvement phase: results against the pre-registered plan

**Dates:** 2026-10-19 (plan fixed, streams started) to 2026-10-22 · **Plan:** `ml/IMPROVEMENT_PLAN.md` (pass marks fixed before any result; amendments A1-A4 dated in its section 5) · **Trial ledger:** N = 241 (177 from the five-year run + 64 new configurations and books) · **Status: PARTIAL. Pending: AB1-AB6 and AB2P on the corrected data (training), the ten-year re-runs, the final gate table.**

Every number below is quoted from the stream's JSON/Markdown named in its section. "PASS" and "FAIL" refer to the pass marks written in the plan before the result existed.

## 1. One-page summary (provisional until the pending runs land)

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
| Does information outside the bhavcopy add signal? | AB1-AB6, AB2P: +0.003 with CI > 0 | *pending (training)* | |
| Does the signal hold across eight years and three cycles? | ten-year re-runs, Stage-0 criteria | *pending (history loaded, dataset building)* | |

**Provisional reading.** The data are now clean enough to trust and the economics have a mechanism: the equal-weight universe is beaten by a deliberately volatility- and size-neutral book built from any of the LightGBM scores, on the frozen data and on the corrected data alike (+7.8%/yr, IR 1.99 [0.91, 3.17] for the v2 control). What has not changed is the proof: the liquid, capacity-bearing versions of those books earn +5% to +6% a year with intervals that barely clear or include zero, every Deflated Sharpe is far below 0.95 at N = 241, and the neutralisation idea was read from the same 43 folds it is tested on. The verdict stays **no capital; paper-trade one frozen construction**, now a deliberate one.

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

## 8. Pending

- AB1 market state, AB2 sector, AB2P placebo, AB3 F&O, AB4 flows, AB5 all, AB6 ensemble on 52 features: training on v2 (`ab/v2/queue_ab.log`).
- Ten-year re-runs (control, logistic, momentum on 103 folds): queued behind the A/Bs (`ab/10y/queue_10y.log`).
- Final gate table at N = 241, program report section, goals ladder, HTML page, roadmap.
