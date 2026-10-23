# How SuryaDhana improves a model: the process

**Date:** 2026-10-23 · **Owner:** program lead · **Companion:** `ml/PROMPT.md` (the same process as a prompt an AI agent team can run) · **Evidence for every rule below:** `ml/PROGRAM_REPORT.md` (§8, §13), `ml/IMPROVEMENT_PLAN.md`, `ml/IMPROVEMENT_PLAN_2.md`.

This is the cycle the program ran in October 2026. Each step exists because skipping it produced a wrong number at least once in this program; the failure that taught it is named next to it.

## The cycle in one table

| # | Step | What it produces | The failure it prevents (seen in this program) |
|---|---|---|---|
| 1 | Write the decision question | One sentence: what result would change what we do | Studies that end in "interesting" instead of a decision |
| 2 | Audit the data before the model | Session calendar, corporate actions, universe composition, duplicates, all checked against an independent source | Nine wrong sessions, 501 unadjusted splits and bonuses, and 215 ETFs inside the "stock" universe went unnoticed through two model studies |
| 3 | Pre-register | Hypotheses, metrics, pass marks, the trial count N, dated and committed before any result | The pilot's headline (AUC 0.531, "only model above chance") came from features chosen on the test months; honest value 0.513 |
| 4 | Fix the harness, then never touch it | Purged walk-forward folds, embargo ≥ label horizon + 1, exit-date purge, a holdout scored once, paired block bootstrap, one book engine with costs | Overlapping labels leaking across the train/test boundary; CV and holdout ranking models in opposite order on one regime break |
| 5 | Measure signal and economics separately | AUC and rank IC for the ranking; net excess over the equal-weight universe for the book | AUC 0.536 with IC t-stat 6 coexisting with a book that lost to the universe for five years |
| 6 | Split the work into streams with one owner each | Parallel streams, one writer for shared state, read-only exports for everyone else | Two processes writing the same database; agents reading a half-written table |
| 7 | Review adversarially before computing | Two reviewers per stream: a point-in-time lens and a spec-fidelity lens; blocking only with evidence | Look-ahead in an index-membership snapshot that would have made a sector feature look like a discovery |
| 8 | Run one compute queue | Serialized jobs on fixed seeds; JSON first, Markdown quotes JSON | Results that cannot be reproduced; numbers retyped by hand that disagree with the files |
| 9 | Score against the marks, deflate for N | Pass/fail per pre-registered mark; Deflated Sharpe at the cumulative trial count; placebo controls where look-ahead is possible | Treating the best of 177 tries as if it were the only try |
| 10 | Report what failed as prominently as what passed | Results of record, corrections, "what this does not claim" | Inflated claims that management would act on |
| 11 | Decide and write the next cycle | Roadmap with the exact next action and the data each item needs; the forward record if anything is a candidate | Endless backtesting instead of the one test that cannot be overfit |

## Step details

### 1. The decision question
State it as a choice: "fund / paper-trade / drop", "promote model B over A", "add data source X". Write next to it what result would move the choice. If no result would move it, the study is not worth running.

### 2. Data before models
- **Calendar:** compare the stored sessions with an independent calendar (here: the existence of the exchange's daily PR bundle). Weekend Budget sessions, Saturday special sessions and Muhurat sessions are real sessions; archive mirrors can serve the previous day's file on a holiday.
- **Corporate actions:** prices from bhavcopy are unadjusted. Adjust splits and bonuses from the exchange's own feed and validate each event against the observed ex-date price ratio (pass mark used here: ≥ 95% within ±15%).
- **Universe composition:** check what is in the "stock" universe (ETFs, call-auction securities, BE/BZ series) with the exchange's own lists, not a name pattern.
- **Continuity scan:** the share of names whose reported previous close differs from the stored one should be near zero on every session.
- **Exports:** after the one write window, every other process reads parquet exports, never the live database.

### 3. Pre-registration
A dated file in the repository, committed before results, with: the streams; every configuration and book that will be scored (this is the trial count N, cumulative across the program); the primary metric and its pass mark; secondary readings; what would change the verdict. Changes after that point are dated amendments that add to N, never edits.

Pass marks used in this program, as templates:
- Model change: paired fold-level AUC delta ≥ +0.003 with the 20-session block-bootstrap 95% interval excluding zero.
- Book: information ratio ≥ 0.5 with its month-block 95% interval excluding zero; for a comparison, the paired monthly difference's interval excluding zero.
- Capital: Deflated Sharpe ≥ 0.95 at the cumulative N on a book that can carry the intended capital.

### 4. The harness
Monthly folds; a rolling training window; an embargo of at least the label horizon plus one session; training rows whose label exits on or after the test start removed; one untouched holdout scored once per configuration; the same seed everywhere; a paired block bootstrap (identical draws for every model) for every comparison. Once fixed, the harness is never changed inside a study.

### 5. Signal and economics
Report both, always:
- **Ranking:** fold AUC, months above 0.50, worst month, rank IC with a Newey-West t.
- **Book:** net excess over the equal-weight universe (not the median, which a right-skewed universe beats by itself), its information ratio and interval, months ahead, turnover, capacity, break-even cost, Deflated Sharpe.
- **Exposures:** the score's per-date correlation with volatility and size. In this program the classifiers' books lost because the label rewards low-volatility names; neutralising the score per date fixed it.

### 6. Streams
One owner per stream, one writer per shared resource (a lock file), explicit paths each stream may edit, read-only inputs listed. Long downloads start first and run in the background while code is written.

### 7. Adversarial review
For each stream, before the compute that produces its result:
- **Point-in-time lens:** can anything dated after t reach a feature, label, training row, basket or benchmark at t?
- **Spec lens:** does the code do exactly what the pre-registration says? Recompute samples by hand.
A finding is blocking only with evidence (a command and its output). A fixer resolves blocking findings; disagreements are answered with evidence.

### 8. Compute
One queue, jobs in sequence, fixed seeds, resumable caches. Outputs are JSON; Markdown and HTML read the JSON, never retyped numbers.

### 9. Scoring
Each pre-registered mark gets PASS or FAIL in the stream's report. Deflated Sharpe uses the cumulative N and the cross-trial variance of all books scored. Where a feature could carry look-ahead (snapshots, survivorship), a placebo with the same coverage is registered and the feature counts only if it beats the placebo.

### 10. Reporting
Results of record quote the files. Failures are reported at the same prominence as passes. Every report has a "what this does not claim" list. Corrections to earlier claims are stated at the top of the document they correct.

### 11. The next cycle
A roadmap that lists what is open, the exact next action, the data it needs and whether that data is reachable. When a construction becomes a candidate, freeze it and start the forward record: it is the one test the process cannot overfit.

## What has and has not moved the numbers here

| Lever | Effect in this program | Reading |
|---|---|---|
| Data integrity (sessions, corporate actions, ETFs) | Same signal, less dispersion (fold sd 0.042 → 0.032); label coverage up | Always first; it rarely raises the mean, it makes the measurement trustworthy |
| Book construction (volatility+size neutralisation) | Single-model book −0.7%/yr → +6.9%/yr over the universe; +10.5%/yr over ten years | The largest gain in the program came from construction, not from the model |
| More history (five → ten years) | Evidence across three cycles; AUC 0.5455, rank IC t 9.8 | Proof, not signal |
| External data (market state, sector, F&O, flows) | One real but sub-threshold gain (F&O +0.0020 AUC) | Information outside the price file adds little to a 20-day ranking |
| Feature selection, more engineered features from the same file | Nothing, or worse | Stopped |
| New model families (deep nets, transformers, RL, foundation models) | Nothing beat gradient-boosted trees | Stopped |
| Overlapping-label corrections (subsampling, uniqueness weights) | Nothing beyond noise | Closed |
| Phase 2 (liquid-universe model, F&O long-short, 40-day horizon, announcement events, tuning, CPCV) | See `ml/results/improve2/` | Filled in when the phase closes |
