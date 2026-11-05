# FINDINGS row template — gold studies → `reports/gold_program/FINDINGS.md`

Every pre-registered gold study (`reports/gold_program/<study>/PLAN.md`, written before any result; registry:
`reports/gold_program/STUDIES.md`) contributes rows to the programme's aggregate `reports/gold_program/FINDINGS.md`
(owned by B5). The rows are **generated**, never typed: each script renders one `common.Row` (signal, result, the two
halves, verdict) in **two shapes** from its `summary.json`, so a re-run keeps every number in step:

| File | Shape | Columns | Renderer |
|---|---|---|---|
| `<study>/FINDINGS_ROW.md` | **aggregate** — paste-ready for B5's table | 4: `Study · signal` · `Result` · `Both halves` · `Verdict` | `common.aggregate_row(study, row)` / `common.findings_rows_md` |
| `<study>/FINDINGS.md` | **study page** — the `reports/fii_positioning/FINDINGS.md` form | 3: `Signal` · `Result → **VERDICT**` · `Both halves` | `common.study_row(row)` via `common.findings_template` |

A literal `|` inside a cell (as in `|t| ≥ 2`) is escaped as `\|` by the renderers; `common.table_cells(line)` counts
cells the way a gate should (4 for the aggregate shape, 3 for the page shape).

## Aggregate shape (B5's table, header exactly as in `reports/gold_program/FINDINGS.md`)

```markdown
| Study · signal (known at release) | Result | Both halves | Verdict |
|---|---|---|---|
| GS-P1 · S3 · 20-day Δ tonnes → 20 sessions | IC 0.036 (t 1.00); tercile spread 0.02 % (t 0.11); OOS 1.50 %/yr after costs (t 0.87) | IC 0.010 (t 0.26) / IC 0.068 (t 1.43) | **FAIL** |
```

- **Study · signal** — the study id, the pre-registered signal name (S1…, H1…) and the horizon (sessions / weeks / month).
- **Result** — the test statistic(s) with their t (Newey-West for overlapping windows, plain t for non-overlapping
  months) and, where a rule is traded, its **out-of-sample excess after costs** (the project floor 0.15 % per round trip;
  GS-P4 charges 0.15 % per switch = 0.30 % per round trip). No verdict text here: it has its own cell.
- **Both halves** — the same statistic in the first / second half of the sample (`h1 / h2`), the evidence for the
  both-halves condition of PLAN f.1. Signed numbers use U+2212 for the minus.
- **Verdict** — one of the vocabulary below in bold, optionally qualified in brackets (`**FAIL** (all three)`,
  `**VOID (pre-registered) / FAIL (drift-adjusted, capped)**`).
- A description row (same-week / same-day relation, "not a forecast") may follow the forecast rows; its verdict is
  `PASS as description` or `weak as description`, never a signal.

## Study-page shape (`<study>/FINDINGS.md`)

```markdown
| Signal | Result (full sample) | Both halves |
|---|---|---|
| S3 · 20-day Δ tonnes → 20 sessions | IC 0.036 (t 1.00); … OOS 1.50 %/yr after costs (t 0.87) → **FAIL** | IC 0.010 (t 0.26) / IC 0.068 (t 1.43) |
```

## Verdict vocabulary (PLAN f.1, binding) → what the page may do

| Verdict | Means | Badge consequence |
|---|---|---|
| **PASS** | a STATISTIC (`common.verdict`, sign-free): \|t\| ≥ 2 in the full sample and the same sign with \|t\| ≥ 2 in both halves; a TRADED RULE (`common.verdict_traded`, **signed**): OOS excess after costs t ≥ 2 in the OOS span and in both OOS halves in the direction traded — a rule that loses consistently is a FAIL, never a PASS | candidate for `signal` — only after the owner's separate approval (PLAN f.5); nothing feeds the Decision Desk, the S1 shadow, an alert or the ticket |
| **CONTEXT-ONLY** | \|t\| ≥ 2 in the full sample only (a traded rule: t ≥ 2 in the OOS span only), or a strong same-week relation without forecasting power, or a PASS from a statistic adopted post hoc (capped, `post_hoc_cap`) | `context` badge; the chip names the study and date; no colour, no composite |
| **FAIL** | everything else | `context` at most, worded "no forecasting power (<study>, <date>)" |
| **VOID** | a pre-registered statistic whose own negative control "passes" (the study's plan voids it; GS-P4 N4: shuffled month labels pass in 44 % of 100 seeds); the row stays for the record, a post-hoc statistic may be reported beside it capped at CONTEXT-ONLY | = **FAIL** for the badge |
| **PENDING** | pre-registered, data not stored yet (the script exits 3 `data not yet ingested` / 4 `insufficient history`; 5 `live file busy` is a scheduling refusal, not a verdict) | the panel keeps its pre-study badge and caption ("folklore until G-STUDY-2") |

## PENDING rows (paste until the data is stored; `common.findings_pending_row(study, question, needs)` renders them)

```markdown
| G-STUDY-2 · daily OI × price quadrant (COMEX GC product OI) → 1 / 5 / 20 sessions | pre-registered, not run: needs gold_cme_daily_voi (CME FTP backfill 2014 →, owner action O-6) | — / — | **PENDING** |
| GS-P2 · WGC weekly ETF flows by region → 1 / 4 weeks | pre-registered, not run: needs gold_series WGC_ETF_HOLD_T_* (gold_weekly job + backfill, owner action O-1) | — / — | **PENDING** |
```

## Current rows (4 Nov 2026)

- `reports/gold_program/GS-P1/FINDINGS_ROW.md` — 6 forecast rows (all FAIL) + 1 description row (PASS as description).
- `reports/gold_program/GS-P4/FINDINGS_ROW.md` — 3 hypothesis rows (H1, H1b, H2: `VOID (pre-registered) / FAIL
  (drift-adjusted, capped)`), H3 (FAIL, signed) and one record row (the vs-zero statistic: `VOID (PLAN N4)`). Study verdict:
  "VOID (pre-registered statistic) / FAIL (post-hoc drift-adjusted, capped) — drift, not a calendar".
- G-STUDY-2 and GS-P2: the PENDING rows above.

## Section header for the aggregate file

```markdown
## Pre-registered studies (B7) — verdict rows

Plans in `reports/gold_program/<study>/PLAN.md` predate every result (registry `reports/gold_program/STUDIES.md`); rows are
generated by `scripts/gold_studies/*.py`; `tests/test_gold_study_reproduce.py` re-runs G-STUDY, G-MACRO (H2), GS-P1 and
GS-P4 and asserts these numbers.
```
