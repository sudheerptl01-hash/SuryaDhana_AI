# How SuryaDhana improves a model: the process

**Date:** 2026-10-23 · **Owner:** program lead · **Companion:** `ml/PROMPT.md` (the same process as a prompt an AI agent team can run) · **Evidence for every rule below:** `ml/PROGRAM_REPORT.md` (§8, §13, §14), `ml/IMPROVEMENT_PLAN.md`, `ml/IMPROVEMENT_PLAN_2.md`, `ml/results/improve2/IMPROVEMENT_RESULTS.md`.

This is the cycle the program ran in October 2026. Each step exists because skipping it produced a wrong number at least once in this program; the failure that taught it is named next to it.

## The cycle in one table

| # | Step | Owner | What it produces | Done when | The failure it prevents (seen in this program) |
|---|---|---|---|---|---|
| 1 | Write the decision question | program lead (management names the decision) | One sentence: what result would change what we do | the sentence and the result that would move it are committed | Studies that end in "interesting" instead of a decision |
| 2 | Audit the data before the model | data-integrity owner (the single DuckDB writer) | Session calendar, corporate actions, universe composition, duplicates, all checked against an independent source | the stored calendar matches the PR-bundle calendar on every day; ≥ 95% of corporate actions within ±15% of the observed ex-date ratio; 0 ETFs in the stock universe; continuity mismatches near 0 on every session | Nine wrong sessions, 501 unadjusted splits and bonuses, and 215 ETFs inside the "stock" universe went unnoticed through two model studies |
| 3 | Pre-register | program lead | Hypotheses, metrics, pass marks, the trial count N, dated and committed before any result; in-cycle follow-ups as dated amendments committed before their job starts | the plan is committed before the first job, with N stated; each amendment is committed before its job starts, its time copied from `git log` | The pilot's headline (AUC 0.531, "only model above chance") came from features chosen on the test months; honest value 0.513. In phase 2 two amendment timestamps were written later than their commits, and one follow-up (Q9) skipped its pre-compute reviews; its job started 20 s before its amendment was committed |
| 4 | Fix the harness, then never touch it | harness owner (no edits inside a study) | Purged walk-forward folds, embargo ≥ label horizon + 1, exit-date purge, a holdout scored once, paired block bootstrap, one book engine with costs | the harness commit hash is recorded in the plan | Overlapping labels leaking across the train/test boundary; CV and holdout ranking models in opposite order on one regime break |
| 5 | Measure signal and economics separately | each stream owner | AUC and rank IC for the ranking; net excess over the equal-weight universe for the book | both tables are in every stream report | AUC 0.536 with IC t-stat 6 coexisting with a book that lost to the universe for five years |
| 6 | Split the work into streams with one owner each | program lead (assigns the streams, the one writer and the owned paths) | Parallel streams, one writer for shared state, read-only exports for everyone else | each stream's owned paths and the lock file are listed in the plan | Two processes writing the same database; agents reading a half-written table |
| 7 | Review adversarially before computing | two reviewers who did not write the stream, plus a fixer | Two reviewers per stream: a point-in-time lens and a spec-fidelity lens; blocking only with evidence | no blocking finding is open | Look-ahead in an index-membership snapshot that would have made a sector feature look like a discovery |
| 8 | Run one compute queue | queue operator (the program lead) | Serialized jobs on fixed seeds; JSON first, Markdown quotes JSON | every output is a JSON written by a queued job | Results that cannot be reproduced; numbers retyped by hand that disagree with the files |
| 9 | Score against the marks, deflate for N | stream owner scores; an independent verifier recomputes the headlines | Pass/fail per pre-registered mark; Deflated Sharpe at the cumulative trial count; placebo controls where look-ahead is possible; seed replicates before any paired book test | every mark is PASS or FAIL; every DSR is at the cumulative N; every book mark is read on seed-averaged series | Treating the best of 177 tries as if it were the only try; paired book tests "passing" for configurations with no ranking gain because the seed-108 control was its own unluckiest liquid book |
| 10 | Report what failed as prominently as what passed | program lead; reviewers check every number against the JSON | Results of record, corrections, "what this does not claim" | the results of record and the "does not claim" list are committed, with corrections at the top of each document they correct | Inflated claims that management would act on |
| 11 | Decide and write the next cycle | program lead proposes, management decides | Roadmap with the exact next action and the data each item needs; the forward record if anything is a candidate | `ml/ROADMAP.md` and the forward-record decision (under the rules of step 11) are written | Endless backtesting instead of the one test that cannot be overfit |

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
A dated file in the repository, committed before results, with: the streams; every configuration and book that will be scored (this is the trial count N, cumulative across the program); the primary metric and its pass mark; secondary readings; what would change the verdict. Changes after that point are dated amendments that add to N, never edits. A follow-up that a result suggests may run in the same cycle only as such an amendment: its timestamp is the commit time (copy it from `git log`, do not type it), it is committed before its job starts, it gets the same two reviews as any stream, and its result is reported as exploratory: a pass is evidence for a forward test, not a promotion. Books the harness computes that were not registered are counted as soon as they are found.

Pass marks used in this program, as templates:
- Model change: paired fold-level AUC delta ≥ +0.003 with the 20-session block-bootstrap 95% interval excluding zero.
- Book: information ratio ≥ 0.5 with its month-block 95% interval excluding zero; for a comparison, the paired monthly difference's interval excluding zero.
- Capital: Deflated Sharpe ≥ 0.95 at the cumulative N on a book that can carry the intended capital.

### 4. The harness
Monthly folds; a training window stated as part of the model (rolling 504 sessions or expanding; in this program the expanding window ranked better, so the window is a model choice, not a constant); an embargo of at least the label horizon plus one session; training rows whose label exits on or after the test start removed; one untouched holdout scored once per configuration; the same seed everywhere; a paired block bootstrap (identical draws for every model) for every comparison. Once fixed, the harness is never changed inside a study.

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
Each pre-registered mark gets PASS or FAIL in the stream's report. Deflated Sharpe uses the cumulative N and the cross-trial variance of all books scored. Where a feature could carry look-ahead (snapshots, survivorship), a placebo with the same coverage is registered and the feature counts only if it beats the placebo. A fixed seed carries one draw of tree randomness through every fold, so a paired book test between two configurations compares two draws as well as two models: register seed replicates of both (here 3 to 4 seeds each), average each configuration's monthly series over its seeds, and require the paired interval on the averages to exclude zero (iid and 3-month blocks) and every seed of the candidate to beat every seed of the control. AUC is far less seed-sensitive (sd 0.0001 to 0.0003 here) than a liquid book (range 1.1 pp a year).

### 10. Reporting
Results of record quote the files. Failures are reported at the same prominence as passes. Every report has a "what this does not claim" list. Corrections to earlier claims are stated at the top of the document they correct.

### 11. The next cycle
A roadmap that lists what is open, the exact next action, the data it needs and whether that data is reachable. When a construction becomes a candidate, freeze it and start the forward record: it is the one test the process cannot overfit.

**Decision rules.**
- **(a) A pre-registered mark FAILS:** close the idea in `ml/ROADMAP.md` (the closed list) with its evidence and the new information that would justify a retry. No rescue trials.
- **(b) A pre-registered model mark PASSES,** its book mark passes on seed-averaged series where one is registered, and an independent verifier finds no leakage: the configuration is a candidate.
- **(c) A candidate or an exploratory pass enters the forward record only as a challenger,** by a dated amendment to `ml/paper/SPEC.md` (precedent: amendment 10) with a backfill proof and a byte-identical `ml/paper/prove.py` rebuild. A backtest never replaces the book of record.
- **(d) A challenger replaces the book of record** only under the live-comparison rule registered when it entered. The expanding-window challenger entered without one; its rule was registered afterwards, before any live month had matured, as amendment 11 (`ml/paper/SPEC.md` section 6). Register the rule with the challenger next time.
- **(e) Capital** only when the book of record meets Stage 2 of `ml/GOALS.md` (among its criteria: PSR ≥ 0.95 on the live record, DSR ≥ 0.95 at the cumulative N, the five gates of `ml/SCALE_UP.md`, twelve months without a monitor alarm). Management decides on the program lead's report.

## What has and has not moved the numbers here

| Lever | Effect in this program | Reading |
|---|---|---|
| Data integrity (sessions, corporate actions, ETFs) | Same signal, less dispersion (fold sd 0.042 → 0.032); label coverage up | Always first; it rarely raises the mean, it makes the measurement trustworthy |
| Book construction (volatility+size neutralisation) | Single-model book −0.7%/yr → +6.9%/yr over the universe; +10.5%/yr over ten years | The largest gain in the program came from construction, not from a new model |
| More history for evaluation (five → ten years) | Evidence across three regimes; AUC 0.5455, rank IC t 9.8 | Proof |
| More history for training (rolling 504 sessions → expanding window) | AUC +0.0079 [+0.0047, +0.0113], rank IC 0.088 → 0.103; neutral book +10.5% → +14.9%/yr; liquid neutral book +1.2% → +5.2%/yr; robust to seeds | The one model-side gain above the bar; concentrated in falling markets; exploratory, so it runs in the forward record as a challenger |
| External data (market state, sector, F&O, flows) | One real but sub-threshold gain (F&O +0.0020 AUC) | Information outside the price file adds little to a 20-day ranking |
| Feature selection, more engineered features from the same file | Nothing, or worse | Stopped |
| New model families (deep nets, transformers, RL, foundation models) | Nothing beat gradient-boosted trees | Stopped |
| Overlapping-label corrections (subsampling, uniqueness weights) | Nothing beyond noise | Closed |
| A model trained on liquid names only | Liquid book IR 0.27 to 0.40, paired gain CI includes 0; the full-universe model ranks the liquid rows as well | Restricting the training universe loses information; closed |
| Futures-hedged long-short on F&O names | Net Sharpe −0.65 and −1.22 with betas near zero | The hedge works, the short leg's carry and costs eat the spread; closed |
| A longer label horizon (40 days) | +0.33 pp/yr over the 20-day score held 40 sessions, CI includes 0 | Closed |
| Announcement events (5 million records, 2016-2026) | −0.0008 AUC; the earnings-reaction drift is real (IC +0.042, t 7.9) but mostly already in the model | A real anomaly is not the same as new information; closed until filings data fills the coverage gaps |
| Hyper-parameter tuning, nested | +0.0004 AUC | The configuration was not the bottleneck; closed |
| Combinatorial purged CV | 7 of 7 paths positive for both neutral books | Robustness check, not new evidence (paths share models; 2018 is look-ahead by construction); it pointed at training history |
