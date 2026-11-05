# Terminal v2 — study registry (the one list of study ids)

One row per pre-registered study of the Terminal v2 program (PLAN §1 B8, §0.1 #1 and #14: a `signal` badge exists only
through a FINDINGS PASS row of a study whose PLAN predates its results). **This file is the source of truth for the
ids**; `services/ui-api/routers/research.py` CATALOG rows, panel evidence strings and LEARN entries must use them. An id
is never reused once a plan or a FINDINGS row carries it. Maintained by B8 (studies). **No study result reaches a badge
without the PM** (and the owner's separate approval for any `signal`).

## Verdict vocabulary

PASS · PASS as description · CONTEXT-ONLY · FAIL · VOID (a pre-registered statistic voided by its own negative control;
badge = FAIL) · PENDING (pre-registered, inputs not stored or too short) — the gold program's vocabulary
(`scripts/gold_studies/FINDINGS_ROW_TEMPLATE.md`), with the Terminal v2 rule that every graded statistic is **signed**
(the registered direction is the claim's; a t ≥ 2 the other way is a FAIL) and needs |t| ≥ 2 in the full sample **and**
both halves **after costs** (`shared/trading_costs.py` for cash legs; the dated F&O schedule in
`scripts/terminal_studies/common.py` for option legs, never below the 0.15 % floor). **PROVISIONAL** marks a result
computed on inputs recomputed from the cached files in a scratch store rather than on the stored, backfilled tables.

## Registry

| Id | Hypothesis (one line) | Data | Status (5 Nov 2026) | Verdict | Plan / script | FINDINGS |
|---|---|---|---|---|---|---|
| TV-IVRV | Do the IV − RV spread and the IV percentile forecast the next-20-session realised vol (seller's edge; information) or the next-20-session index return ("buy fear"), after costs? NIFTY graded, NIFTY BANK replication | `iv_summary_daily` (production) · recomputed from the 1,760 cached F&O bhavcopies 2019-10 → 2026-11 with the production `fo_iv` code · NSE index closes | pre-registered 5 Nov 2026 07:57 IST; **PROVISIONAL** run 5 Nov 08:20 (scratch recomputation, 1,487 NIFTY / 1,459 BANKNIFTY graded sessions 2020-10 → 2026-10) | **0 PASS** · 8 FAIL · 4 CONTEXT-ONLY: the spread / percentile carry information about next month's RV (G2 CONTEXT-ONLY by ceiling) but time neither the seller's edge (G1 FAIL) nor the index return (G3 FAIL) | `reports/terminal_v2/studies/iv_rv/PLAN.md` · `scripts/terminal_studies/tv_ivrv.py` | `reports/terminal_v2/studies/iv_rv/FINDINGS.md` |
| TV-DRIVERS | Does the 20-session NIFTY leader keep its share of the move (beyond weight) and keep driving relative to NIFTY 20 sessions ahead; does a leader change precede a different return or a vol expansion? | `index_contribution_daily` / `_fit` / `index_driver_state` (production) · rebuilt by the production backfill from a read-only extract of the 30 Oct evening snapshot, today's members applied before 4 Nov (fit-gated) | pre-registered 5 Nov 2026 08:00 IST; **PROVISIONAL** run 5 Nov 08:20 (583 fit-gated sessions, Nov 2023 → Oct 2026: the cached XBRL share counts start in late 2023, so H1 of the pre-registered split is empty) | D1 **FAIL** (the leader's share does not persist beyond the weight leader's; t −3.2 the wrong way) · D2 **FAIL** (t −0.3; long-only after costs −1.0 %/tranche) · D3 **PENDING** (15 events < 20) | `reports/terminal_v2/studies/drivers/PLAN.md` · `scripts/terminal_studies/tv_drivers.py` | `reports/terminal_v2/studies/drivers/FINDINGS.md` |
| TV-GEX | Does a GEX-style dealer-gamma proxy (C1 vendor convention: net gamma share; C2 "writers are short": gamma load) forecast NIFTY's next-day range beyond recent ranges, IV and the expiry calendar; does "sell premium on long-gamma days" pay? (Wave 3.3 precondition) | `iv_surface_daily` / `iv_expiry_daily` (production) · recomputed from the cached F&O files; range from the most-traded NIFTY future's high / low; participant OI as a cross-check | pre-registered 5 Nov 2026 08:00 IST; **PROVISIONAL** run 5 Nov 08:20 (1,740 sessions 2019-10 → 2026-11) | X1 **FAIL** (net gamma share, t −0.3) · X2 **FAIL** (gamma load: smaller ranges, t −3.2 both halves — against the registered sign); the panel stays `heuristic` | `reports/terminal_v2/studies/gex/PLAN.md` · `scripts/terminal_studies/tv_gex.py` | `reports/terminal_v2/studies/gex/FINDINGS.md` |

## Not pre-registered yet (ideas parked here so the ids are not reused)

| Id | Idea | Waits for |
|---|---|---|
| TV-CRUSH | Does the results IV-crush ledger (implied vs realised move) forecast the next release's crush? | `iv_event_log` with ≥ 8 quarters per name (backfill) |
| TV-SKEW | Does the 25Δ skew percentile forecast the next-20-session index return or downside RV? | `iv_summary_daily.skew_25d_30` backfilled |
| TV-OIBUILD | OI build-up classes (long build-up / short covering …) on the VOL screener: H2 found no edge on futures; an options-side replication | participant / per-strike OI history |

## Running a study

Outside the IST busy windows when the input is a copy of the live file (Mon–Fri 07:45–15:45 and 18:30–21:15 the scripts
refuse to copy `data/market.duckdb`: exit 5; `--allow-market-hours` overrides). On a scratch inputs store the window does
not apply. Each script opens its `--db` read-only, writes `summary.json`, `REPORT.md`, `FINDINGS.md`, `FINDINGS_ROW.md` and
`results/*.csv` under its study directory, and never touches the network:

```bash
P=/Users/sudheer/Desktop/jupyter_env/bin/python
S=~/.suryadhana_pm_scratch/v2/B8-STUDIES/inputs.duckdb
nice -n 10 $P scripts/terminal_studies/build_inputs.py --fo --drivers \
    --snapshot data/snapshots/evening/evening-20261030-1920.duckdb --out $S     # resumable; never writes data/
$P scripts/terminal_studies/tv_ivrv.py    --db $S --provisional
$P scripts/terminal_studies/tv_drivers.py --db $S --provisional
$P scripts/terminal_studies/tv_gex.py     --db $S --provisional
```

After the owner-approved backfill (O-T4 IV, the drivers backfill) the same scripts run on a snapshot of the stored
tables without `--provisional` (the study-only inputs — option closes and the futures range — still come from the cached
files through `build_inputs.py --fo --out <aux>` and `--aux <aux>`); the PROVISIONAL stamp drops only when the stored run
reproduces the provisional numbers.
