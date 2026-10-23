# SuryaDhana improvement phase 2: results against the pre-registered plan

**Dates:** 2026-10-23 (plan fixed at 02:34:27 UTC, commit 7c74bef, before any result; amendments and errata dated in its section 4) · **Plan:** `ml/IMPROVEMENT_PLAN_2.md` · **Trial ledger:** N = 270 (241 after phase 1; 20 planned here; ledger corrections +4; amendments A1 and A2 +3 and +2) · **Status: complete.** Every pre-registered mark has a result, and every headline was recomputed independently by an adversarial verifier from the raw predictions and price data (no implementation error that could hide a real effect was found).

Every number below is quoted from the stream's JSON named in its section. "PASS" and "FAIL" refer to marks written before the result existed. Books are net of 20 bps per side against the equal-weight benchmark of the same universe (whole universe or liquid tercile), over 105 signal months 2018-01..2026-09 on the ten-year data, unless stated.

## 1. One-page summary

| Question | Pre-registered test | Result | Verdict |
|---|---|---|---|
| Can a model built for liquid names fix capacity? (Q3) | liquid neutral book IR ≥ 0.5, CI > 0, and paired gain over the control's liquid book CI > 0 | L1 (liquid tercile only) IR 0.27 [−0.49, +1.02], paired +0.04 pp/yr; L2 (top two terciles) IR 0.40 [−0.30, +1.14], paired +1.08 pp/yr, CI includes 0 | **FAIL** |
| Does a market-neutral F&O long-short work? (Q4) | net Sharpe ≥ 1.0 with CI > 0, beta within ±0.2 | plain −0.65 [−1.43, +0.12], neutral −1.22 [−1.87, −0.53]; betas −0.15 / −0.05 | **FAIL** (the hedge works, the returns do not) |
| Is 40 days a better horizon? (Q5) | 40-day model's 40-session book beats the 20-day control's, paired CI > 0, higher break-even | +7.3% vs +6.9%/yr, paired +0.33 pp/yr [−0.83, +1.48]; break-even 88 vs 83 bps | **FAIL** |
| Do company announcements add signal? (Q6) | AUC delta ≥ +0.003, CI > 0 | −0.0008 [−0.0035, +0.0017] | **FAIL** (the earnings-reaction drift is real, rank IC +0.042, t 7.9, but already mostly in the model) |
| Does honest hyper-parameter tuning help? (Q7) | AUC delta ≥ +0.003, CI > 0 | +0.0004 [−0.0006, +0.0014] | **FAIL** |
| Is the construction robust to which months train the model? (Q2, CPCV) | positive net excess in ≥ 6 of 7 paths | full-universe neutral book 7/7 (+14.3% to +17.1%/yr); liquid neutral 7/7 (+4.8% to +8.7%) | **ROBUST** (path dependence only; CPCV trains on later data by design) |
| Does a longer training history help? (Q9, amendment A1) | AUC delta ≥ +0.003, CI > 0; Q3 book rule on the liquid book | AUC **+0.0079 [+0.0047, +0.0113]**, rank IC 0.103 vs 0.088 (t 4.6); liquid neutral book +5.2%/yr, IR 0.78 [0.06, 1.54], paired +4.06 pp/yr [+1.71, +6.39] | **PASS, both marks** (exploratory: the hypothesis came from the CPCV reading) |
| Is the Q9 book gain real or one random-seed draw? (Q10, amendment A2) | seed-averaged paired CI > 0 (iid and 3-month blocks) and every Q9 seed above every control seed | liquid neutral **+3.54 pp/yr [+1.30, +5.67]**, blocks [+1.08, +5.86], min Q9 seed +4.9% > max control seed +2.3%; full neutral +4.44 pp/yr [+2.90, +5.97] | **REAL** |
| Capital gates at N = 270 | the five gates of `ml/SCALE_UP.md` | expanding window: gate 1 **PASS** on all three seeds (+0.0112 [+0.0049, +0.0179] over the logistic benchmark, the first pass in the program), gate 3 neutral PASS, gate 2 FAIL (86%), gate 5 FAIL (liquid DSR 0.000) | **no capital** |
| The forward record (Q1) | product, no mark | inception 2026-10-19; six forward books running, including the expanding-window challenger | **running** |

**Reading.** Phase 2 tested six ways to raise the signal or the economics and one way to prove them. Five failed their marks honestly, and the verifiers found no bug behind any of the failures. The one lever that worked was not a new model, feature or data source: it was giving the same model a longer training history. An expanding window raises the ranking quality on every seed (AUC 0.5534 against 0.5455; rank IC 0.103 against 0.088). It is the first configuration in the program to beat the linear benchmark with an interval clear of zero. It lifts the full-universe neutral book to +14.9% a year (IR 3.06) and the liquid, capacity-bearing book to +5.2% a year (IR 0.78, capacity ₹555 crore). That gain survives seed calibration. Three things keep it from changing the capital verdict. The hypothesis was formed after reading the CPCV result on the same months. The gain is concentrated in falling markets (AUC +0.024 in 25 down months against +0.004 in 55 up months). No Deflated Sharpe of a liquid book is above 0.001 at N = 270. **The verdict stays no capital.** The expanding-window construction is now the leading candidate, and since 2026-10-23 the forward record runs it as a challenger beside the frozen primary book.

## 2. Q1. The forward record (`ml/paper/`, `ml/results/improve2/paper/PAPER.md`)

- **Ingest.** Sessions 2026-10-19, 2026-10-21 and 2026-10-22 were loaded under the lock protocol. 2026-10-20 was the Dussehra closure: the archive served a byte-identical copy of the 19th, and no PR bundle exists. JSWDULUX's 1:10 split (ex 2026-10-22) was validated and applied.
- **A data defect caught by review.** CCAVENUE's 10-for-1 consolidation is spelled "CNSLDATN" in the exchange feed with an empty ex-date field. It was missed, giving a fake +840% one-day return. The parser was extended, the store repaired under the lock, and the ledger re-issued once from inception on 2026-10-23. The superseded rows had already been pushed in work-in-progress commits; they are kept byte for byte with their hashes in `superseded_2026-10-23/`. The same spelling gap leaves three research-period consolidations unadjusted in the research store (KAUSHALYA 2024-01-12, SHEKHAWATI 2024-08-28, VERTOZ 2025-06-25); their jump rows are not universe rows of `ml/data_10y`, and the fix is on the roadmap.
- **Books.** Primary: the frozen construction (LightGBM, 52 features, rolling 504 sessions, volatility+size-neutral full-universe top decile, about 152 names). Capacity: its liquid-tercile version (about 50 names). Challenger: the rank ensemble, neutralised. Reference: the plain control. Added by dated spec amendment 10, backfilled from inception with the existing rows byte-identical: **challenger_expanding** (the same construction with an expanding window; its October model trained on 2,170,733 rows) and its capacity version.
- **Proofs.** The paper trainer reproduces the research holdout predictions exactly. A from-inception rebuild in a sandbox reproduces every ledger file byte for byte. A second run appends nothing.
- **What the forward record cannot match.** The research books exclude rows that fail the forward-looking label screen (`y_clean_20d`): 0.33% of rows, mostly crashes (mean 20-day return −30%). That flatters research excess by about 0.4 pp a year. The live books hold every name, so live and backtest are not like-for-like.
- **Operations due.** The first tranche exits on 2026-11-18 (2026-11-19 if the 2026-11-08 Muhurat session is not added to `ml/paper/calendar_live.json` beforehand). Free disk must stay above about 5.5 GB for the backup taken before each write. Two monitors were already at alert at inception: feature drift on `ret_126d` and a pre-inception inversion month (2026-08). Since amendment 10 a third is at alert: the expanding challenger's `neutral_score_corr` (0.048 to 0.058 against 0.05, the `log_turnover` term; ALERT on 2026-10-21 and 2026-10-22; `ml/paper/RUNBOOK.md` section 8).

## 3. Q3. A model for the liquid universe: FAIL (`ml/results/improve2/liquid/LIQUID.md`)

| Liquid neutral book | Excess/yr | IR [95% CI] | Paired vs the control's liquid book, pp/yr [iid CI, annualised ×12.6] |
|---|---:|---|---|
| control (full-universe model) | +1.2% | +0.21 [−0.52, +0.93] | |
| L1: trained and scored on the liquid tercile, label vs its median | +1.2% | +0.27 [−0.49, +1.02] | +0.04 [−2.71, +2.67] |
| L2: top two terciles | +2.3% | +0.40 [−0.30, +1.14] | +1.08 [−0.44, +2.65] |

Both fail both parts of the mark. The verifier rebuilt every step independently and found a deeper reason. Scored on the same liquid rows against the restricted label, the full-universe model ranks as well as or slightly better than the liquid-only models (L1 AUC 0.5322 vs 0.5305). **Restricting the training universe throws away information; it does not add any.** Two of L2's books over the top-two-tercile universe were computed by the harness without registration and are counted (+2 trials).

## 4. Q4. F&O long-short via stock futures: FAIL (`ml/results/improve2/fo_ls/FO_LS.md`)

Long the top quintile of F&O names in cash, short the bottom quintile through near-month futures, rolled at expiry, 20-session tranches. Costs: 20 bps a side long, 40 bps a side plus 10 bps a roll short.

| Book | Net Sharpe (rf 5.5%) [95% CI] | Beta to Nifty 50 (daily / Dimson) | DSR (N = 270) |
|---|---|---|---:|
| plain score | −0.65 [−1.43, +0.12] | −0.15 / −0.11 | 0.000 |
| neutral score | −1.22 [−1.87, −0.53] | −0.05 / +0.00 | 0.000 |

The hedge works: each leg carries a beta near one and they cancel. The returns do not. The score separates the quintiles (about 5 to 6 points a year gross), but the short leg loses net of carry and costs. The verifier tried every reasonable convention: risk-free rate 0, open-to-open marks, statutory-level costs, dividends, and dropping the look-ahead screen within hindsight bounds. None reaches a Sharpe of 1.0 except stacks that combine near-zero costs with rf 0. The stream's own conventions Q4-a and Q4-b, one of them chosen after a smoke run's betas, are recorded as amendments and counted (+2 trials); both conventions fail.

## 5. Q5. The 40-day horizon: FAIL (`ml/results/improve2/h40/H40.md`)

| 40-session neutral book (104 signal months) | Excess/yr | IR [95% CI] | Break-even (bps/side) | Years positive |
|---|---:|---|---:|---:|
| 20-day control's score | +6.9% | +1.80 [+1.07, +2.52] | 83 | 8/9 |
| 40-day model | +7.3% | +1.81 [+1.06, +2.50] | 88 | 9/9 |

Paired difference +0.33 pp/yr, CI [−0.83, +1.48] (months) and [−0.82, +1.58] (3-month blocks): FAIL. Training on the 40-day label did not improve the ranking of 40-day outcomes: rank IC 0.079 for the 40-day model against 0.087 for the 20-day model. The 42-session embargo makes its training data 20 sessions staler. The liquid 40-session books earn about zero for both. Both 40-session books also earn less than the control's own 20-session book (+10.5%/yr) at half the turnover.

## 6. Q6. Company events from the exchange's announcement files: FAIL (`ml/results/improve2/events/EVENTS.md`)

All 2,488 PR bundles (2016-10..2026-10) were parsed: 4,956,205 announcement records and 91,226 board-meeting list rows, classified by rules fixed from text alone. Ten point-in-time features came out of this: sessions since the results release, the earnings-announcement return (`ear_3d`) and volume reaction, announcement counts, rating, management-change, order-win and insolvency flags. All point-in-time checks passed (100 random cells, 80 rare-value cells, delete-the-future, shift test).

- **Primary mark:** AE1 (control + family E) − control = −0.0008 AUC [−0.0035, +0.0017], 51/103 folds: FAIL.
- **Why, given a real anomaly:** `ear_3d` has rank IC +0.042 (Newey-West t 7.9) among the 75% of rows with a results release in the last 60 sessions, positive in every year. About 17% of it is already spanned by the control's score, and the most a model can add is about +0.002 AUC (a post-hoc blend, descriptive only). The source has three coverage gaps (2022-02..2022-12, 2023-09/10, 2024-01) whose folds carry most of the negative point estimate. FAIL means "below the bar", not "no information".

## 7. Q7. Nested hyper-parameter tuning: FAIL (`ml/results/improve2/tune/TUNE.md`)

Nine settings were chosen per calendar year on inner training blocks only. Six of nine years switched away from the incumbent. Tuned minus control: +0.0004 AUC [−0.0006, +0.0014]; on the 67 folds that could differ, +0.00065. The inner margins were tiny (0.00005 to 0.009) and did not predict the outer deltas. In 2021 every setting scored below 0.50 on the inner blocks. **The champion configuration was not the bottleneck.**

## 8. Q2. Combinatorial purged cross-validation (`ml/results/improve2/cpcv/CPCV.md`)

The 103 fold months were split into 8 groups, giving 28 splits and 7 paths. Training used every row outside the two test groups, with purge, a 22-session embargo and no holdout.

| Reading (103 months) | 7 CPCV paths | Walk-forward control, same months |
|---|---|---|
| mean fold AUC | 0.5559 to 0.5611 | 0.5455 |
| full-universe neutral book | +14.3% to +17.1%/yr, IR 2.91 to 3.55; positive 7/7 | +10.3%, IR 2.26 |
| liquid neutral book | +4.8% to +8.7%/yr; positive 7/7; IR CI above 0 on 5 to 7 of 7 depending on the bootstrap seed | +0.8%, IR 0.14 |

**ROBUST** by the registered reading for both books. That means the result does not depend on which months train the model. It does not mean seven independent confirmations: the paths share 28 models, and their monthly returns correlate 0.89 to 0.93. The verifier decomposed the CPCV-over-walk-forward gain. About 38% of the liquid gain sits in the first group (2018-01..2019-01), where CPCV trains on 2019-2026 data and walk-forward had only a few months, so that part is look-ahead by construction. The last group (2025-26), which has no later-dated training rows, gains at least as much as the others. **More history, not knowledge of the future, explains most of the rest.** That is what motivated Q9.

## 9. Q9. An expanding training window (amendment A1): PASS, exploratory (`ml/results/improve2/expanding/EXPANDING.md`)

| 103 folds | CV AUC [95% CI] | Months ≥ 0.50 | Worst | Holdout | Rank IC (NW t) |
|---|---|---:|---:|---:|---|
| control, rolling 504 sessions | 0.5455 [0.5359, 0.5549] | 84% | 0.399 | 0.5193 | +0.088 (9.8) |
| **expanding window** | **0.5534 [0.5435, 0.5624]** | 86% | 0.414 | 0.5401 | **+0.103 (11.4)** |

Mean fold AUC by year (control / expanding): 2018 0.548 / 0.548 (identical: the window is under 504 sessions until 2019-11), 2019 0.575 / 0.575, 2020 0.561 / 0.562, 2021 0.527 / 0.530, 2022 0.528 / 0.548, 2023 0.535 / 0.540, 2024 0.553 / 0.565, 2025 0.544 / 0.563, 2026 0.534 / 0.550.

| Book (net 20 bps vs EW, 105 months; DSR at N = 270) | Excess/yr | IR [95% CI] | Months ahead | Capacity (₹ cr) | Name-level excess | Break-even (bps/side) | DSR |
|---|---:|---|---:|---:|---:|---:|---:|
| control, neutral top decile | +10.5% | +2.32 [+1.51, +3.10] | 83 | 157 | +3.9% | 72 | 0.066 |
| **expanding, neutral top decile** | **+14.9%** | **+3.06 [+2.29, +3.86]** | 85 | 147 | +8.2% | 97 | 0.761 |
| control, neutral liquid top decile | +1.2% | +0.21 [−0.52, +0.93] | 55 | 603 | −3.1% | 26 | 0.000 |
| **expanding, neutral liquid top decile** | **+5.2%** | **+0.78 [+0.06, +1.54]** | 67 | 555 | +0.6% | 45 | 0.000 |

- **Marks:** the primary AUC mark PASSES. The Q3 book rule on the liquid book PASSES: IR 0.78 with its CI above 0, and a paired gain of +4.06 pp/yr [+1.71, +6.39] (3-month blocks [+1.50, +6.47]).
- **Independent verification** (a post-hoc substitute for the pre-compute reviews Q9 skipped). The training sets were rebuilt for every fold; no row's label reaches its test month. Folds 2018-01..2019-11 are bit-identical to the control. A from-scratch refit of fold 2024-06 reproduces the saved scores exactly. The AUC delta survives dropping 2026 (+0.0073 [+0.0035, +0.0116]), 2025-26 (+0.0056 [+0.0018, +0.0101]) and 2022 with 2026. No leakage mechanism was found.
- **Caveats the reader must keep.** (1) The hypothesis was formed after the CPCV reading on the same months: this is evidence for a forward test, not a promotion. (2) The gain is regime-concentrated: +0.024 AUC in 25 down months against +0.004 in 55 up months, no significant gain over 2019-12..2021-12, and +0.0043 without the 8 best folds. A model trained on two bull years generalises badly into sell-offs; one that remembers earlier sell-offs does better. (3) The liquid book's own IR interval leans on 2026: without 2026 and the holdout it is IR 0.51 with an interval including zero. (4) The expanding model costs about three times the training time (about 100 s per fit at 2.1M rows).

## 10. Q10. Seed calibration (amendment A2): the Q9 book gain is REAL (`ml/results/improve2/seeds/SEEDS.md`)

The verification had found that paired book tests against the seed-108 control also "passed" for configurations with no ranking gain (AE1, Q7). Fixed seeds carry one tree-randomness draw through every fold. Replicates: control seeds 108-111, expanding seeds 108-110.

| Book | Control seeds (mean, range) | Expanding seeds (mean, range) | Seed-averaged paired, pp/yr [iid CI] [3-month-block CI] | Every expanding seed above every control seed | Reading |
|---|---|---|---|---|---|
| neutral liquid top decile | +1.8% (+1.2 .. +2.3) | +5.2% (+4.9 .. +5.6) | **+3.54 [+1.30, +5.67] [+1.08, +5.86]** | yes | **REAL** |
| neutral full-universe top decile | +10.3% (+9.9 .. +10.5) | +14.8% (+14.5 .. +14.9) | **+4.44 [+2.90, +5.97] [+2.59, +6.56]** | yes | **REAL** |
| plain liquid top decile | +0.7% (−0.0 .. +1.1) | +1.6% (+1.3 .. +2.0) | +1.08 [−1.31, +3.48] | yes | not shown |
| plain full-universe top decile | +7.6% (+7.3 .. +8.0) | +9.4% (+9.3 .. +9.5) | +1.82 [−0.23, +3.93] | yes | not shown |

- **AUC is not a seed artefact.** The seed sd is 0.0003 (control) and 0.0001 (expanding). The seed-averaged delta is +0.0078 [+0.0044, +0.0116].
- **The seed-108 control was its unluckiest liquid book** (+1.2% against +1.8% to +2.3% for the other seeds). That explains why unrelated configurations seemed to beat it in paired tests, and it means every phase-1 and phase-2 comparison against the control's liquid book was slightly flattered.
- **The expanding liquid book's own IR interval is seed-sensitive:** [+0.06, +1.54] for seed 108, [−0.05, +1.51] for 109, [+0.07, +1.67] for 110.

## 11. Gates at N = 270 (`ml/results/improve/ab/10y_p2/GATES.md`)

| Configuration | Gate 1: beats the logistic benchmark | Gate 2: ≥ 90% of months ≥ 0.50 | Gate 3: neutral top decile ahead in ≥ 75% of months | Gate 5: liquid-book DSR ≥ 0.95 | Passed |
|---|---|---|---|---|---|
| control (seeds 108-111) | +0.0032 to +0.0038, CI includes 0, **FAIL** | 83-84% **FAIL** | 74-79%, PASS on 2 of 4 seeds | 0.000 **FAIL** | 0-1 of 6 |
| events, tuned | CI includes 0 **FAIL** | 84% **FAIL** | 75%, 78% PASS | 0.000 **FAIL** | 1 of 6 |
| **expanding (seeds 108-110)** | **+0.0112 [+0.0049, +0.0179] PASS** (all seeds) | 86-87% **FAIL** | 80-82% **PASS** | 0.000 **FAIL** | **2 of 6** |

Gate 4 does not apply (nothing is selected). The logistic benchmark ran on the rolling window; whether a logistic model with an expanding window would close the gate-1 gap is untested. **Nothing is promoted.**

## 12. Trial ledger

N = 270 = 241 (phase 1) + 20 (planned: Q2 1, Q3 6, Q4 2, Q5 5, Q6 3, Q7 3) + 2 (L2's unregistered top-two-tercile books) + 2 (Q4's open-mark books under its stream amendments) + 3 (A1: Q9 and two books) + 2 (A2: two seed-averaged books). Not counted, as in phase 1: plain books of AE1, Q7 and Q9; smoke runs; seed replicates (measurement of noise in counted configurations); the verifiers' post-hoc variants (none may be cited as a result). Stream reports quote DSR at N = 261 or 264 where they ran earlier; at N = 270 the values fall by at most about 0.01. V[SR] is still the phase-1 cross-trial variance (0.00387); it does not include phase-2 books.

## 13. What this phase changes

1. **The training window is a model choice, and the expanding window is better.** That is the only model-side gain above the bar in either phase. It is calibrated against seed noise and verified for leakage, but it is exploratory and regime-concentrated. The forward record now runs it beside the frozen book; after six to twelve months the live comparison decides, not another backtest.
2. **Capacity moved, but not enough to clear the gates.** The expanding liquid book earns +5.2% a year with capacity ₹555 crore. That is the first capacity-bearing book on the ten-year walk-forward with an IR interval above zero (on two of three seeds). Its Deflated Sharpe is 0.000 at N = 270, and its edge after name-level costs is +0.6% a year.
3. **Five ideas were closed with evidence:** a liquid-only model, a futures-hedged long-short, a 40-day horizon, announcement-event features, and hyper-parameter tuning. None should be retried without new information.
4. **Two process lessons.** Paired book tests need seed calibration. In-cycle follow-ups must be dated amendments committed before their job starts, and reviewed like any stream; Q9 met neither strictly: its amendment was committed 20 s after its job started (though before its first result), and it ran without the two reviews; an independent post-hoc verification stands in for them. Both lessons are now written into `ml/PROCESS.md` and `ml/PROMPT.md`.
5. **Integrity work is never finished.** A consolidation spelling the parser missed was caught by review in the live book, and three research-period cases remain to fix.
