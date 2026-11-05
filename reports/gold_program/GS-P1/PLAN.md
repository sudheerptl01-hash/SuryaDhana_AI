# GS-P1 · Do daily GLD tonnes (SPDR Gold Shares holdings) predict COMEX gold? Pre-registered plan

Written Mon 26 Oct 2026 (B7, GOLD program phase 2) **before any result was computed**. Script:
`scripts/gold_studies/gs_p1_gld_tonnes.py`. Owner approval: PLAN.md §i O-13. Nothing in this study feeds the Decision
Desk, the S1 shadow, a directional alert or the paper ticket (PLAN 0.1 #7); a PASS changes a badge only through a
FINDINGS row and separate owner approval (PLAN f.5).

## Question

The GLD trust publishes its gold holdings every day. The desk lore says "tonnes up = investment demand = gold up".
G-STUDY (weekly, 4-week change) found nothing (t ≤ 1.0). Does the **daily** series, at 5- and 20-session horizons,
forecast the COMEX front-month return after costs? Separately (not graded as a forecast): how tightly do the tonnes move
*with* the price on the same day and week?

## Data (stored; no network)

- **Holdings:** SPDR GLD historical archive XLSX (SOURCES.md E1): `reports/gold_program/G-STUDY/data/spdr_gld_historical_archive.bin`
  (identical to `G-MACRO/data/spdr_gld_historical_archive.xlsx`), sheet "US GLD Historical Archive", 5,720 rows,
  18 Nov 2004 → 22 Oct 2026, `Tonnes of Gold`; "US Holiday" rows dropped. In production the same series is
  `gold_etf_holdings` (fund `GLD`) read through `--db` (read-only snapshot copy).
- **Price:** COMEX front-month settlement proxy `GC=F` daily close, `G-STUDY/data/yahoo_GC_F_1d.csv` (2000-08-30 →);
  in production `gold_daily_bars` symbol `COMEX_GC_FRONT`.
- **Terms:** display-only data under SPDR's disclaimer (O-1); the study reads it, nothing re-serves it; only
  statistics are published.

## Release alignment (the look-ahead guard)

The trust posts day T's holdings on T by 16:45 New York, i.e. **after** the 13:30 ET COMEX settlement of T, and the
archive row for T is visible at ≈06:00 IST on T+1. A signal dated T is therefore known before session T+1 ends:
**entry = close of session T+1; forward return = close(T+1) → close(T+1+h)**, h ∈ {5, 20} sessions. No forward window
contains a close that was public when the signal was. Robustness: entry one session later (T+2).

## Signals (fixed)

- **S1** · 1-day change in tonnes, in % of holdings: `tonnes_T / tonnes_{T−1} − 1`.
- **S2** · 5-day change, %: `tonnes_T / tonnes_{T−5} − 1`.
- **S3** · 20-day change, %: `tonnes_T / tonnes_{T−20} − 1`.

Each signal is ranked only against its own strictly earlier values (expanding percentile / expanding tercile cut-offs,
minimum 250 observations), so every rank is walk-forward.

## Tests

1. **Rank IC:** Spearman(signal, fwd_h) with a Newey-West t of the rank slope (Bartlett, lags h−1 — the 5- and 20-session
   windows overlap).
2. **Tercile spread:** mean fwd_h in the top tercile minus the bottom tercile (expanding cut-offs), NW t of the signed
   de-meaned series.
3. **Walk-forward long/flat rule after costs:** one tranche per session held h sessions; long when the signal's expanding
   percentile is in the favourable tercile; direction learned from completed forward windows strictly before the
   decision, re-fitted every 20 sessions; in-sample = first 40 % of sessions, out-of-sample = the rest (≈2013 →);
   **0.15 % per round trip** (the project floor; MCX GOLD's exchange + brokerage cost is ≈0.018 %); benchmark =
   buy-and-hold scaled to the rule's average exposure. Reported: OOS excess %/yr and its NW t.
4. **Descriptive (not graded as a forecast):** Spearman of Δtonnes vs the same-day and same-week price change; lead/lag
   cross-correlation at −5 … +5 sessions (negative = price leads tonnes).

## Halves

H1 = 18 Nov 2004 → 31 Dec 2015 (the ETF build-up era) · H2 = 1 Jan 2016 → the last stored date.

## Pass criteria (PLAN f.1, binding)

For a signal at a horizon:

- **PASS (→ `signal` badge candidate):** |t_IC| ≥ 2 in the full sample **and** the same sign with |t_IC| ≥ 2 in both halves
  **and** the walk-forward rule's OOS excess after costs has t ≥ 2.
- **CONTEXT-ONLY:** |t_IC| ≥ 2 in the full sample but not in both halves, **or** the forecast tests fail while the
  same-day/same-week descriptive relation is strong (|ρ| ≥ 0.2 and stable in sign across halves) — the panel then says
  "moves with the price, does not lead it".
- **FAIL:** everything else.

Multiple testing: 3 signals × 2 horizons = 6 forecast tests (+2 robustness entries); ≈0.3 of them would show |t| ≥ 2
by chance in the full sample alone — the both-halves and OOS conditions are the guard.

## Negative controls (pre-registered; the study is void if a control "passes")

- **Placebo lag:** S3 lagged by 60 sessions (a stale number that cannot carry news) must FAIL at both horizons.
- **Shuffle:** S3 permuted across dates with seed 20261026 must FAIL at both horizons.

## Prior and what each outcome would mean

Honest prior: **FAIL as a forecast, PASS as a description** (G-STUDY weekly: same-week R² 16 %, next-week ρ ≈ 0;
G-MACRO: weekly correlation 0.33–0.37 contemporaneous, ≈0 predictive; WGC's own attribution model treats flows as
contemporaneous). A PASS would be surprising and would still need the owner's separate approval before any badge
changes. A split result across halves (2004–2015 ETF build-up vs 2016+ when the marginal buyer moved outside the
report) is CONTEXT-ONLY by rule.

## Outputs

`reports/gold_program/GS-P1/results/*.csv`, `summary.json`, `REPORT.md` (every table), `FINDINGS.md` (the verdict rows
in the `reports/fii_positioning` format) and `FINDINGS_ROW.md` (the rows to paste into `reports/gold_program/FINDINGS.md`).
Runnable today: `/Users/sudheer/Desktop/jupyter_env/bin/python scripts/gold_studies/gs_p1_gld_tonnes.py`.

## Run record (26 Oct 2026)

- 07:18 first run (draft, before the review) and 10:45 re-run (after it) agree row for row (`FINDINGS_ROW.md` identical);
  the re-run adds `FINDINGS.md`, written by the script from `summary.json`. `tests/test_gold_study_reproduce.py` re-runs
  the study and asserts the headline numbers (every forecast test FAIL; same-week Spearman 0.29 ± 0.02; controls ok).

## Run record (4 Nov 2026, wave 1b)

- Re-run after the adversarial review: every number identical. Changes that touch no number: `control_ok` now means
  verdict == FAIL at both horizons (the plan's wording; the draft accepted anything not PASS — all four controls do
  FAIL); the `--db` path keeps the stored `release_at` per trust date and enters at the first session whose settlement
  follows it, never earlier than the T+1 rule (`common.entry_after_release`; the archive path is unchanged, T+1); the
  DuckDB copy is removed when the run ends and is never taken from the live store inside an IST busy window (exit 5);
  `FINDINGS_ROW.md` is 4-column (verdict in its own cell).
