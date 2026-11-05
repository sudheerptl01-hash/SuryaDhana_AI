# G-STUDY-2 · Does the daily open-interest × price quadrant (COMEX gold product OI) forecast anything? Pre-registered plan

Written Mon 26 Oct 2026 (B7, GOLD program phase 2) **before any result was computed**. Script:
`scripts/gold_studies/g_study_2_oi_quadrant.py`. Owner approval: PLAN.md §i O-13 (and O-6 for the CME FTP backfill the
study needs). Nothing here feeds the Decision Desk, the S1 shadow, a directional alert or the paper ticket
(PLAN 0.1 #7); a PASS changes a badge only through a FINDINGS row and separate owner approval (PLAN f.5).

## Question

The GOLD page's `d.quadrant` / `p.daily.comex` panels label every session by the sign of the price change × the sign of
the open-interest change — long build-up (P↑ OI↑), short build-up (P↓ OI↑), short covering (P↑ OI↓), long unwinding
(P↓ OI↓). The folklore reads the first two as continuation and the last two as weak moves. G-STUDY tested the
**weekly** version on COT open interest: 1 of 12 cells at |t| ≥ 2 → CONTEXT-ONLY ("folklore until G-STUDY-2"). This is
the **daily** test on 12 years of exchange product OI.

## Data (stored; no network)

- **Open interest:** `gold_cme_daily_voi` (SOURCES.md C1; CME FTP `daily_volume_YYYYMMDD.xlsx`, 2014-01-02 →), product
  `GC` futures, all months summed, `open_interest` and the derived `oi_change`; read through `--db` (read-only snapshot
  copy). Robustness variant adds `MGC` (micro) to the product OI.
- **Price:** `gold_daily_bars` symbol `COMEX_GC_FRONT` (fixture: `G-STUDY/data/yahoo_GC_F_1d.csv`).
- **Roll mechanics:** sessions inside the 5 sessions before the front month's first notice day and the 2 sessions after
  its last trade day are flagged `mechanical` from `gold_cme_calendar` (C3); when the calendar table is absent they are
  approximated by the last 5 sessions of Jan / Mar / May / Jul / Sep / Nov (GC's active months are Feb/Apr/Jun/Aug/Oct/Dec).
  Primary test keeps them; the robustness variant drops them.
- **Replay fixture:** `reports/gold_program/G-CME/samples/comex_gold_family_daily_oi_oct2026.csv` (40 rows = 10 sessions ×
  4 products, 9–22 Oct 2026) is the CSV shape the loader also accepts (`--fixture`); it is far below the minimum sample.
- **Minimum sample:** 500 sessions of product OI; below that the script exits `insufficient history` (code 4).
- **Status today:** the table does not exist (the ≈2 h FTP backfill waits for O-6) → `{"status": "data not yet ingested"}` (code 3).

## Release alignment

`daily_volume.xlsx` for trade date T is posted on T+1 at ≈14:00–15:30 IST, **before** session T+1's 13:30 ET settlement
(23:00 IST). A label dated T is therefore known before session T+1 ends: **entry = close(T+1); forward return =
close(T+1) → close(T+1+h)**, h ∈ {1, 5, 20} sessions. The label itself uses only Δclose_T and ΔOI_T.

## Hypotheses (the folklore, fixed direction, stated before the data)

- **H1** long build-up (P↑ OI↑): forward excess return > 0 (continuation).
- **H2** short build-up (P↓ OI↑): forward excess return < 0 (continuation).
- **H3** short covering (P↑ OI↓): forward excess return < 0 (a weak rally).
- **H4** long unwinding (P↓ OI↓): forward excess return > 0 (a washed-out decline).
- **H5** continuous OI change — 1-, 5- and 20-session % change — rank IC with fwd_h (exploratory sign).
- **H6** the tradable folklore rule: long after a P↑ OI↑ or a P↓ OI↓ session, flat otherwise, one tranche per session
  held h sessions, **0.15 % per round trip**, OOS from the first 40 % of sessions; benchmark = scaled buy-and-hold.

## Tests

- Each cell: mean fwd_h minus the unconditional mean, NW t (lags h−1), hit rate, n — in the full sample and in each half.
- H5: Spearman IC with the NW t of the rank slope.
- H6: walk-forward long/flat (fixed direction) — OOS excess vs scaled B&H, NW t, and the t in each OOS half.
- Robustness: without mechanical sessions; GC+MGC product OI; entry at T+2.

## Halves

H1 = 2 Jan 2014 → 30 Jun 2020 · H2 = 1 Jul 2020 → the last stored session.

## Pass criteria (PLAN f.1, binding)

- A cell **PASSes** only if |t| ≥ 2 in the full sample **and** the same sign with |t| ≥ 2 in both halves; H6 additionally
  needs OOS excess after costs t ≥ 2 in **both** OOS halves. A PASS cell without a passing H6 is CONTEXT-ONLY (a label
  that describes, not a rule that pays).
- **CONTEXT-ONLY:** |t| ≥ 2 in the full sample only.
- **FAIL:** everything else.

Multiple testing: 12 cells + 3 IC + 1 rule = 16 tests → ≈0.8 false |t| ≥ 2 expected in the full sample alone.

## Negative controls (pre-registered)

- Placebo: the quadrant labels lagged by 60 sessions must produce no PASS cell.
- Shuffle: labels permuted across sessions (seed 20261026) must produce no PASS cell and an H6 OOS |t| < 2.

## Prior

**CONTEXT-ONLY.** G-STUDY's weekly version: "new shorts" 13-week t −2.0 (1 of 12), everything else |t| < 1.6;
Hong & Yogo (2012) report OI growth forecasting commodity returns at monthly horizons (not re-verified here). Roll
weeks make product OI mechanical, which biases daily labels toward noise. If every cell FAILs the panel keeps the labels
as a description of yesterday with the `context` badge and the caption "folklore: no forecasting power (G-STUDY-2)".

## Outputs

`reports/gold_program/G-STUDY-2/results/*.csv`, `summary.json`, `REPORT.md`, `FINDINGS.md`, `FINDINGS_ROW.md` — written only
when ≥ 500 sessions of product OI are stored.

## Amendments (26 Oct 2026, before any verdict run; no result has been computed)

- **A1 · "both OOS halves" of H6** = the out-of-sample span cut at its own midpoint observation (printed as `oos_split`),
  not the sample-half date of 30 Jun 2020: with IS = the first 40 % of 2014 → 2026 the OOS span begins in 2019, and a
  cut at mid-2020 would leave one OOS half a few months long. The cells (H1–H4) keep the 30 Jun 2020 halves.
- **A2 · the fixture is a shape check, not a sample.** 10 sessions → `insufficient history` (exit 4), as above.
- Status at 26 Oct 2026 10:45 IST: `{"status": "data not yet ingested"}` (exit 3) — `gold_cme_daily_voi` waits for O-6
  and the CME FTP backfill. The aggregate `reports/gold_program/FINDINGS.md` carries the PENDING row from
  `scripts/gold_studies/FINDINGS_ROW_TEMPLATE.md` until then.
- **A3 (4 Nov 2026, still before any verdict run) · H6's verdict is signed.** "OOS excess after costs t ≥ 2 in both OOS
  halves" is graded with `common.verdict_traded`: PASS needs t ≥ 2 (the rule pays) in the OOS span and in each OOS half;
  t ≥ 2 in the span only is CONTEXT-ONLY; a rule that loses consistently (t ≤ −2 everywhere) is a FAIL — the opposite rule
  was never pre-registered, so a sign flip earns nothing. The cells (H1–H4) and H5 stay sign-free statistics whose
  direction is reported against the folklore sign. The negative controls' "no PASS cell" wording is unchanged.
- **A4 (4 Nov 2026) · the verdict run copies the live file safely.** `--db` reads a snapshot copy that is removed when the
  run ends (`common.open_snapshot`, a context manager); the live store is never copied inside the IST busy windows
  (Mon–Fri 07:45–15:45, 18:30–21:15 → exit 5 `live file busy`) unless `--allow-market-hours`; `--tmp-dir` places the copy.
  The CME daily file for T is final (no revisions are stored), so the T+1 entry rule above is the point-in-time rule.
- Status at 4 Nov 2026: unchanged, exit 3 (nothing gold is deployed; the table does not exist).
