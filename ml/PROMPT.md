# Prompts that run the SuryaDhana improvement process

**Date:** 2026-10-23 · **Process they encode:** `ml/PROCESS.md`

Three prompts. Paste one into an agent harness with repository, shell and sub-agent access, at the root of this repository. Each is self-contained; fill in the bracketed parts. They are written for an AI agent team but read equally well as a brief for people.

---

## 1. One full improvement cycle

```text
You are the lead of a quantitative research team improving the SuryaDhana NSE equity-ranking
program in this repository. Run ONE improvement cycle and stop.

CONTEXT TO READ FIRST
- ml/PROGRAM_REPORT.md (verdict, sections 1, 9-14), ml/results/improve2/IMPROVEMENT_RESULTS.md (latest
  results of record; its section 12 holds the current trial ledger, N = 270 after phase 2), ml/GOALS.md
  (what "good enough" means by stage), ml/ROADMAP.md (open items, data each needs, decisions pending),
  ml/PROCESS.md (the method you must follow, with owners, exit criteria and decision rules), the latest
  ml/IMPROVEMENT_PLAN*.md (every pass mark used; its final N is in its last dated amendment, not in its
  section 1).

THE QUESTION FOR THIS CYCLE
[One sentence, e.g. "Can a liquid-universe book beat the equal-weight liquid universe with an
interval clear of zero?" or "Does source X add information to the 20-day ranking?"]
Write next to it which result would change what we do.

NON-NEGOTIABLE RULES
1. Data before models. Before any model work, audit what your question touches: session calendar
   against the exchange's PR-bundle calendar, split/bonus adjustment against observed ex-date
   ratios, universe composition against the exchange's own lists, continuity of previous closes.
   Fix what is wrong first and report it.
2. Pre-register. Before any result exists, commit ml/IMPROVEMENT_PLAN_<n>.md with: each
   configuration and book you will score, the primary metric, the pass mark, secondary readings,
   and the new cumulative trial count N (start from 270; the N in a plan's section 1 is superseded by
   its last dated amendment). Later changes are dated amendments that add to N (each amendment's date
   and time is its commit's, copied from git log; books the harness computes that were not registered
   are counted as soon as they are found).
3. Use the existing harness unchanged: ml/improve/ab.py (purged monthly walk-forward, embargo >= label
   horizon + 1, exit-date purge, holdout scored once, paired 20-session block bootstrap),
   ml/improve/ab_books.py and ml/books/ (book engine, neutralisation, costs), ml/improve/gates.py (the five
   capital gates at N). The training window (rolling 504 sessions or expanding) is a model choice, not part
   of the harness: state which one the control uses. Until the forward record decides, the control is
   the rolling-window `control`; state in the plan whether `q9_expanding` is also a comparator (each
   comparator's books are trials).
4. Never choose a feature, parameter, threshold or rule by looking at test-month results.
   Nested selection on training data only.
5. Report signal and economics separately: AUC, months >= 0.50, worst month, rank IC with
   Newey-West t; and the book's net excess over the EQUAL-WEIGHT universe with its information
   ratio, interval, months ahead, turnover, capacity, break-even cost and Deflated Sharpe at N.
   Report no threshold hit-rate metric; AUC and rank IC are the ranking metrics.
6. Where a feature could carry look-ahead (snapshots, survivorship), register a placebo with the
   same coverage; the feature counts only if it beats the placebo. A book-level comparison between two
   configurations must be calibrated for model randomness: register seed replicates of both
   configurations (3 to 4 seeds each; control replicates control_s109-s111 already exist in 10y_p2),
   average each configuration's monthly net excess series over its seeds, and call the gain real only if
   the paired difference of the averages has iid and 3-month-block 95% intervals excluding zero and every
   seed of the candidate beats every seed of the control (ml/PROCESS.md step 9). Replicates add no
   trial; the seed-averaged books are the trials.
7. One writer for nse_market.duckdb (lock file ml/results/improve/LOCK_duckdb_write); everyone
   else reads the parquet exports in ml/results/improve/cache/.
8. Work in streams with explicit owned paths. For each stream, before its main compute, run two
   adversarial reviews: a point-in-time lens (can anything dated after t reach t?) and a spec lens
   (does the code do exactly what the plan says; recompute samples by hand). Blocking findings
   need evidence; fix them before computing.
9. One compute queue on the shared machine (OMP_NUM_THREADS=2, at most two worker processes),
   seed 108 for every primary run (seed replicates only as registered), JSON outputs first, Markdown
   and HTML quote the JSON.
10. Report every pre-registered mark as PASS or FAIL, failures as prominently as passes, plus a
   "what this does not claim" list. If an earlier claim turns out wrong, correct it at the top of
   the document that made it.

DELIVERABLES
- ml/results/improve<n>/IMPROVEMENT_RESULTS.md (results of record) and a new section in
  ml/PROGRAM_REPORT.md; ml/GOALS.md, ml/ROADMAP.md, the gate-status section of ml/SCALE_UP.md and the
  ml/README.md layout updated; the HTML report regenerated
  (python3 -m ml.make_program_report); everything committed and pushed on the working branch;
  the draft pull request description updated.
- A final message of under 300 words: what passed, what failed, what changed in the verdict,
  the next action under the decision rules of ml/PROCESS.md step 11.

STOP CONDITIONS
Stop when every pre-registered mark has a result. Do not add trials to rescue a failed mark. A new
hypothesis that a result suggests may be tested in the same cycle only as a dated amendment, committed
before its job starts, added to N, reviewed like any stream, and reported as exploratory (a pass is
evidence for a forward test, not a promotion); otherwise propose it for the next cycle.
```

---

## 2. The daily paper book (forward record)

```text
Run the SuryaDhana paper book for today. Follow ml/paper/RUNBOOK.md exactly; where this prompt and the
runbook differ, the runbook wins.

PRECONDITIONS (the job depends on state that exists only on the machine that holds it):
- nse_market.duckdb, ml/paper/state/ and the live CSVs in ml/data_ext/ (corporate_actions_feed_live.csv,
  etf_list_live.csv) must be present; a fresh clone cannot run the job.
- Special sessions (Muhurat, weekend Budget sessions) must be in ml/paper/calendar_live.json BEFORE that
  evening's run (for example the Muhurat session expected on Sunday 2026-11-08); check the runbook's calendar
  section first.
- About 5.5 GB of free disk (the store backup taken before each write).
- About 9 GB of free memory (free -g); the ingest and frame child processes peak near 8 GB.

1. Run after about 19:00 IST on a trading day:
   cd /home/user/SuryaDhana_AI && OMP_NUM_THREADS=2 python3 -I ml/paper/job.py
   It ingests new sessions under the lock file, rebuilds features, retrains on the first session of a month,
   scores with the frozen specification, appends the ledger, recomputes the monitors. It is idempotent.
2. If the job exits non-zero, stop: the exit message is the alert. Never pass --accept-unverified-write and never
   run ingest.py --rebuild-features yourself; both are a person's decision (runbook section 5).
3. Never change parameters, features, neutralisation, the basket rule or ml/paper/config.py, and never edit the
   ledger by hand. Each forward book is one trial and stays one.
4. Check that the ledger diff contains only added lines (runbook section 2), then commit ml/paper/ledger/,
   ml/paper/models/*.json, ml/paper/models/expanding/*.json, ml/paper/calendar_live.json,
   ml/results/improve2/paper/*.json and ml/results/improve2/paper/PAPER.md with the message
   "Paper book <session date>", push, and report: sessions processed, basket sizes and turnover per book, every
   monitor row with status ALERT, and any ingest decision left unresolved.
```

---

## 3. Testing one new idea (a single pre-registered A/B)

```text
Test one idea against the SuryaDhana control without changing anything else.

IDEA: [e.g. "add feature family X built from source Y"]
MECHANISM: [why it should predict 20-day relative returns; cite evidence]

1. Read ml/PROCESS.md and ml/results/improve2/IMPROVEMENT_RESULTS.md section 12 (current N = 270, or the
   last amendment of the latest plan if a later cycle has run).
2. Write and commit an amendment before any result and before its job starts (its time is the commit's,
   copied from git log): the exact feature definitions (point in time: only data dated <= t), the
   configuration name, the pass mark (paired AUC delta >= +0.003 with the block-bootstrap interval
   excluding zero; book marks if economics are the point), and N + the number of configurations and
   books you will score.
2b. If a book mark is registered, register seed replicates of the new configuration (CONFIGS and
   VARIANTS entries <name>_s109 and <name>_s110 with seed=109 and seed=110) and read the book mark on
   seed-averaged series as in prompt 1 rule 6.
2c. Before the run, the two adversarial reviews of prompt 1 rule 8 (point-in-time lens, spec lens); fix
   blocking findings first.
3. Build the data with point-in-time checks: recompute random cells from raw files dated <= t,
   delete-the-future test for one month, shift test. Add a placebo if look-ahead is possible.
4. Add the configuration to ml/improve/ab.py CONFIGS (and FAMILIES if it adds features) and append its
   name to VARIANTS (compare reads only "control" plus VARIANTS), without changing existing entries.
   Work in a new tag (10y_p3 here; the next free number in a later cycle) so ml/results/improve/ab/10y_p2/
   (the phase-2 record) is never rewritten, and never rely on the CLI defaults (tag v2, five-year data,
   N = 241). With N = the cumulative count you registered:
     mkdir -p ml/results/improve/ab/10y_p3/preds
     for c in control lr_l2 control_s109 control_s110 control_s111; do
       cp ml/results/improve/ab/10y_p2/${c}__beat_mkt_20d.json ml/results/improve/ab/10y_p3/
       cp ml/results/improve/ab/10y_p2/preds/${c}__beat_mkt_20d.parquet ml/results/improve/ab/10y_p3/preds/
     done
     export OMP_NUM_THREADS=2
     python3 -m ml.improve.ab run --data ml/data_10y --tag 10y_p3 --configs <name> [--extra <feature parquet>] --n-jobs 2
     python3 -m ml.improve.ab compare --data ml/data_10y --tag 10y_p3
     python3 -m ml.improve.ab_books --tag 10y_p3 --data ml/data_10y \
       --prices ml/results/improve/cache/features_prices_export_10y.parquet --price-start 2017-10-02 \
       --n-trials <N> --configs control control_s109 control_s110 control_s111 <name>
     python3 -m ml.improve.gates --tag 10y_p3 --n-trials <N>
   With seed replicates (step 2b), add <name>_s109 <name>_s110 to the run and to the books;
   ml/improve/q10.py is the template for the seed-averaged reading (it is hard-wired to 10y_p2 and
   q9_expanding: copy it under a new name, do not edit it). If q9_expanding is a registered comparator,
   copy its files the same way and add it to the books. The preds parquets are not in git: on a fresh
   clone, re-run the copied configurations in the new tag instead of copying.
5. Report PASS or FAIL with the numbers, in one table and three sentences.
```
