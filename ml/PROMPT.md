# Prompts that run the SuryaDhana improvement process

**Date:** 2026-10-23 · **Process they encode:** `ml/PROCESS.md`

Three prompts. Paste one into Claude Code (or any agent harness with repository, shell and sub-agent access) at the root of this repository. Each is self-contained; fill in the bracketed parts. They are written for an AI agent team but read equally well as a brief for people.

---

## 1. One full improvement cycle

```text
You are the lead of a quantitative research team improving the SuryaDhana NSE equity-ranking
program in this repository. Run ONE improvement cycle and stop.

CONTEXT TO READ FIRST
- ml/PROGRAM_REPORT.md (verdict, sections 1, 9-13), ml/GOALS.md (what "good enough" means by stage),
  ml/ROADMAP.md (open items, data each needs), ml/PROCESS.md (the method you must follow),
  the latest ml/IMPROVEMENT_PLAN*.md (the trial ledger N so far and every pass mark used).

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
   and the new cumulative trial count N. Later changes are dated amendments that add to N.
3. Use the existing harness unchanged: ml/improve/ab.py (purged monthly walk-forward, rolling
   504-session window, embargo >= label horizon + 1, exit-date purge, holdout scored once,
   paired 20-session block bootstrap), ml/improve/ab_books.py and ml/books/ (book engine,
   neutralisation, costs), ml/improve/gates.py (the five capital gates at N).
4. Never choose a feature, parameter, threshold or rule by looking at test-month results.
   Nested selection on training data only.
5. Report signal and economics separately: AUC, months >= 0.50, worst month, rank IC with
   Newey-West t; and the book's net excess over the EQUAL-WEIGHT universe with its information
   ratio, interval, months ahead, turnover, capacity, break-even cost and Deflated Sharpe at N.
   Never report "accuracy".
6. Where a feature could carry look-ahead (snapshots, survivorship), register a placebo with the
   same coverage; the feature counts only if it beats the placebo.
7. One writer for nse_market.duckdb (lock file ml/results/improve/LOCK_duckdb_write); everyone
   else reads the parquet exports in ml/results/improve/cache/.
8. Work in streams with explicit owned paths. For each stream, before its main compute, run two
   adversarial reviews: a point-in-time lens (can anything dated after t reach t?) and a spec lens
   (does the code do exactly what the plan says; recompute samples by hand). Blocking findings
   need evidence; fix them before computing.
9. One compute queue on the shared machine (OMP_NUM_THREADS=2, at most two worker processes),
   fixed seed 108, JSON outputs first, Markdown and HTML quote the JSON.
10. Report every pre-registered mark as PASS or FAIL, failures as prominently as passes, plus a
   "what this does not claim" list. If an earlier claim turns out wrong, correct it at the top of
   the document that made it.

DELIVERABLES
- ml/results/improve<n>/IMPROVEMENT_RESULTS.md (results of record) and a new section in
  ml/PROGRAM_REPORT.md; ml/GOALS.md and ml/ROADMAP.md updated; the HTML report regenerated
  (python3 -m ml.make_program_report); everything committed and pushed on the working branch;
  the draft pull request description updated.
- A final message of under 300 words: what passed, what failed, what changed in the verdict,
  the next action.

STOP CONDITIONS
Stop when every pre-registered mark has a result. Do not add trials to rescue a failed mark;
propose them for the next cycle instead.
```

---

## 2. The daily paper book (forward record)

```text
Run the SuryaDhana paper book for today. Follow ml/paper/RUNBOOK.md exactly.

1. Run the daily job: python3 -m ml.paper.job (it ingests new sessions, rebuilds features,
   scores with the frozen specification, appends the ledger and recomputes the monitors;
   it is idempotent).
2. If the job reports a holiday echo, a corporate action, a failed download or a monitor alert,
   follow the runbook's response for it; do not change the frozen specification.
3. Never retrain outside the monthly schedule, never change parameters, features, the
   neutralisation or the basket rule. The paper book is one trial (N = 1) and stays one.
4. Commit only ml/paper/ledger/ and ml/results/improve2/paper/PAPER.md with the message
   "Paper book <session date>", push, and report in three lines: sessions processed,
   today's baskets (size, turnover), and any alert.
```

---

## 3. Testing one new idea (a single pre-registered A/B)

```text
Test one idea against the SuryaDhana control without changing anything else.

IDEA: [e.g. "add feature family X built from source Y"]
MECHANISM: [why it should predict 20-day relative returns; cite evidence]

1. Read ml/PROCESS.md and the latest ml/IMPROVEMENT_PLAN*.md (current N).
2. Write and commit an amendment before any result: the exact feature definitions (point in
   time: only data dated <= t), the configuration name, the pass mark (paired AUC delta >= +0.003
   with the block-bootstrap interval excluding zero; book marks if economics are the point),
   and N + the number of configurations and books you will score.
3. Build the data with point-in-time checks: recompute random cells from raw files dated <= t,
   delete-the-future test for one month, shift test. Add a placebo if look-ahead is possible.
4. Add the configuration to ml/improve/ab.py (FAMILIES/CONFIGS) without changing existing
   behaviour; run it against the ten-year control (tag 10y_p2), compare, books, gates.
5. Report PASS or FAIL with the numbers, in one table and three sentences.
```
