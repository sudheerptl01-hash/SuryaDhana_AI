# GS-P2 · Do the World Gold Council's weekly gold-ETF flows (by region) predict COMEX gold? Pre-registered plan

Written Mon 26 Oct 2026 (B7, GOLD program phase 2) **before any result was computed**. Script:
`scripts/gold_studies/gs_p2_wgc_flows.py`. Owner approval: PLAN.md §i O-13 (and O-1: the WGC terms posture — the
study reads stored WGC numbers only after the owner's decision). Nothing here feeds the Decision Desk, the S1 shadow,
a directional alert or the paper ticket (PLAN 0.1 #7); a PASS changes a badge only through a FINDINGS row and separate
owner approval (PLAN f.5).

## Question

The WGC publishes weekly gold-ETF holdings and flows by region (North America, Europe, Asia, Other) for the week
ended Friday, on Monday. Does last week's flow — global or regional — forecast the next 1 / 4 (secondary 13) weeks of
COMEX gold after costs? GLD alone (G-STUDY, GS-P1) is the North-American half; this is the first test of the European
and Asian legs.

## Data (stored; no network)

- **Primary:** `gold_series` rows `WGC_ETF_HOLD_T_GLOBAL`, `WGC_ETF_HOLD_T_NA`, `WGC_ETF_HOLD_T_EU`, `WGC_ETF_HOLD_T_ASIA`,
  `WGC_ETF_HOLD_T_OTHER` (weekly holdings, tonnes, week ending Friday, 2003-02-28 →) and `WGC_ETF_FLOW_T_*` (weekly
  flows, tonnes, 2018-01 →), each with `release_at` (SOURCES.md E5; job `gold_weekly`, Mon 12:00 IST; backfill PLAN c.4).
  The flow used is **Δ weekly holdings in tonnes** (available 2003 →); the published weekly flow series is the
  cross-check where both exist (2018 →; they must agree within rounding, else the study stops and reports it).
- **Price:** `gold_daily_bars` symbol `COMEX_GC_FRONT` (or the saved `G-STUDY/data/yahoo_GC_F_1d.csv` when running on
  fixtures).
- **Replay fixture:** `reports/gold_program/G-PHYSICAL/samples/wgc_fsapi_holdings.json` / `wgc_fsapi_flows.json` are the
  payload shape the loader understands (`--fixture-dir`), for the ingest replay test only; a verdict is computed only
  from the stored tables after O-1 and O-13.
- **Status today:** the tables do not exist → the script exits with `{"status": "data not yet ingested"}` (code 3).

## Release alignment

Week ended Friday → published Monday ≈11:30 IST (`release_at`) → the first COMEX close after the release is
**Monday's 13:30 ET settlement (23:00 IST): entry = Monday's close; forward return = close(Mon) → close(Mon + 5 / + 20 /
+ 65 sessions)** (1 / 4 / 13 weeks). Point-in-time: once ingest history exists, the vintage with the latest
`release_at ≤` the decision date is used (WGC revises); for the one-vintage backfill the study states that revisions
cannot be reconstructed and treats the result as provisional.

## Signals (fixed)

- **S1** · global 1-week flow, % of global holdings: `(H_t − H_{t−1}) / H_{t−1}`.
- **S2** · global 4-week flow, %: `(H_t − H_{t−4}) / H_{t−4}`.
- **S3** · North America 4-week flow, %.
- **S4** · Europe 4-week flow, %.
- **S5** · Asia 4-week flow, % (from the first week Asia holdings exceed 10 t).

Ranks are walk-forward (expanding percentile / tercile cut-offs on strictly earlier weeks, minimum 104 weeks).

## Tests

1. Rank IC with the NW t (lags h−1 in weeks: 0 / 3 / 12).
2. Tercile spread (expanding cut-offs), NW t.
3. Walk-forward long/flat after **0.15 % per round trip**: one tranche per week held h weeks, direction learned from
   completed windows strictly before the decision (re-fitted every week), IS = first 40 % of weeks, OOS = the rest;
   benchmark = scaled buy-and-hold.
4. Descriptive (not graded): same-week Spearman of each region's flow vs the week's price change; which region's flow
   tracks the price most closely.

## Halves

H1 = 28 Feb 2003 → 31 Dec 2014 · H2 = 1 Jan 2015 → the last stored week.

## Pass criteria (PLAN f.1, binding)

- **PASS:** |t_IC| ≥ 2 full sample **and** same sign |t_IC| ≥ 2 in both halves **and** OOS excess after costs t ≥ 2.
- **CONTEXT-ONLY:** |t_IC| ≥ 2 in the full sample only; or the forecast fails while the same-week relation is strong
  (|ρ| ≥ 0.2, same sign in both halves).
- **FAIL:** everything else.

Multiple testing: 5 signals × 2 primary horizons = 10 tests (+5 secondary at 13 weeks); ≈0.5 false |t| ≥ 2 expected.

## Negative controls (pre-registered)

- Placebo: S2 lagged by 26 weeks must FAIL at both primary horizons.
- Shuffle: S2 permuted across weeks (seed 20261026) must FAIL.

## Prior

**FAIL as a forecast, PASS as a description** (G-PHYSICAL: no verified OOS timing value; G-STUDY: GLD 4-week change
t ≤ 1.0 at every horizon; WGC's attribution model is contemporaneous). The regional split is expected to be diagnostic
(who bought last week), not predictive.

## Outputs

`reports/gold_program/GS-P2/results/*.csv`, `summary.json`, `REPORT.md`, `FINDINGS.md`, `FINDINGS_ROW.md` — written only
when the stored tables exist. Until then the script's only output is the status line.

## Amendments (26 Oct 2026, before any verdict run; no result has been computed)

- **A1 · base guard for every region.** A region's % flow is defined only from the first week its holdings are ≥ 10 t
  (the guard the plan gave Asia alone). North America holds 0 t until GLD's launch (Nov 2004) and Europe starts at a
  few tonnes in 2003, so a % change on those bases is ±inf or noise. The guard is a definition of the signal, not a
  data-driven choice; `common.pct_change_guarded` applies it uniformly.
- **A2 · the fixture path never produces a verdict.** `--fixture-dir` (the G-PHYSICAL fsapi JSON) is the ingest-replay
  check: it loads, cross-checks Δholdings against the published flows (459 overlapping weeks, median |diff| 0.006 t)
  and prints row counts; a verdict is computed only with `--db` from the stored, point-in-time rows after O-1 and O-13,
  exactly as "Data" above says. The scripts' own tests exercise the full procedure on synthetic rows in a temporary
  DuckDB, never on the WGC numbers.
- Status at 26 Oct 2026 10:45 IST: `{"status": "data not yet ingested"}` (exit 3) — the `gold_series` WGC rows wait for
  B1's `gold_weekly` job and the backfill. The aggregate `reports/gold_program/FINDINGS.md` carries the PENDING row from
  `scripts/gold_studies/FINDINGS_ROW_TEMPLATE.md` until then.
- **A3 (4 Nov 2026, still before any verdict run) · point-in-time per decision, as "Release alignment" promises.** The
  wave-1 draft read one vintage per week (the latest) and derived the release by the Monday rule, so a later revision
  could enter an earlier week's signal. Now the `--db` path reads **every vintage** (`common.read_gold_series_vintages`,
  no QUALIFY) and, for each week W, the decision instant is the stored first `release_at` of W's own holdings (the
  `wgc_weekly` rule only as the fallback for a row without one; `release_source` records which); each signal is W's
  first-vintage holdings over the holdings of W−k **as they stood at that instant** (`common.pit_lagged`: the latest
  vintage with `release_at ≤` the decision — the QUALIFY rule applied per decision); the entry is the first session whose
  settlement follows the release instant (`common.entry_after_release`). `tests/test_gold_study_reproduce.py::
  test_gs_p2_point_in_time_read_and_synthetic_run` proves on a temporary DuckDB that a +100 t revision released 20 days
  after week 0 is invisible to the weeks decided on days 3, 10 and 17 and visible to the one decided on day 31, and that a
  revision dated ten years out never appears. The description (same-week Spearman) uses first vintages.
- **A4 (4 Nov 2026) · controls must FAIL, and the live file is copied safely.** `control_ok` now means verdict == FAIL at
  both primary horizons (the draft accepted anything that was not PASS). `--db` reads a snapshot copy removed when the
  run ends; the live store is never copied inside the IST busy windows (exit 5 `live file busy`) unless
  `--allow-market-hours`; `--tmp-dir` places the copy.
- Status at 4 Nov 2026: unchanged, exit 3 (nothing gold is deployed; the rows do not exist).
