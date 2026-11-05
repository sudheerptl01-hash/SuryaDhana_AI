# GS-P4 · Month-of-year seasonality of gold **in rupees** (the Indian festival lore). Pre-registered plan

Written Mon 26 Oct 2026 (B7, GOLD program phase 2) **before any result was computed**. Script:
`scripts/gold_studies/gs_p4_seasonality_in_inr.py`. Owner approval: PLAN.md §i O-13. Nothing here feeds the Decision
Desk, the S1 shadow, a directional alert or the paper ticket (PLAN 0.1 #7); a PASS changes a badge only through a
FINDINGS row and separate owner approval (PLAN f.5).

> **Id note (resolved 4 Nov 2026, `reports/gold_program/STUDIES.md`).** PLAN.md O-13 and SOURCES.md once used "GS-P4"
> for the IMF monthly central-bank-buying study; the B7 brief assigned `GS-P4` to "seasonality in INR" and the aggregate
> FINDINGS.md carries that meaning. The registry keeps **GS-P4 = seasonality in rupees (this plan)** and gives the
> central-bank-buying study the fresh id **GS-P5** (not yet pre-registered: the only E12 data on disk is one country ×
> three months, `G-PHYSICAL/samples/imf_irfcl_india.csv`; it waits for the `gold_morning` monthly ingest and a plan of
> its own). Patch requests rename it in PLAN.md O-13, SOURCES.md, `routers/gold.py`, `PhysicalView.tsx` and G-EDU.

## Question

In USD, G-STUDY found Dec and Jan at t ≥ 2 (2006–2026, 4-week horizon) and G-MACRO found **no** month passing t ≥ 2 in
both halves of 1971–2026 (CONTEXT-ONLY). An MCX trader earns gold **in rupees** = gold in USD × USD/INR, and the Indian
lore adds festival demand (Dhanteras/Diwali in Oct–Nov, Akshaya Tritiya in Apr–May, the wedding seasons). Does any
calendar month pass in rupee terms, and is a month-of-year rule tradable after costs?

## Data (stored; no network)

- **Gold, USD, long sample:** World Bank CMO monthly average $/oz 1971-01 → 2024-12
  (`reports/gold_program/G-MACRO/data/worldbank_cmo_monthly.csv`, CC BY-4.0; SOURCES.md G26) spliced with the GC=F
  month-end close from 2025-01 (`G-MACRO/data/yahoo_GC_F.csv`). Monthly averages, not month-ends: fine for a
  month-of-year statistic, **not** a tradable series.
- **Gold, USD, tradable sample:** GC=F month-end close, 2000-09 → the last complete month (`G-MACRO/data/yahoo_GC_F.csv`,
  SOURCES.md A1).
- **Rupee:** FRED `DEXINUS` (Fed H.10 noon buying rate, 1973-01-02 → 2026-10-16, published with up to a week's lag;
  `G-MACRO/data/fred_DEXINUS.csv`, SOURCES.md G7) — monthly **mean** for the average series, month-end **last** for the
  tradable series; Yahoo `INR=X` (2003-12 →, `G-MACRO/data/yahoo_INR_X.csv`) as the rate cross-check.
- **Indian-listed cross-check:** GOLDBEES.NS month-end close 2009-01 → (`G-MACRO/data/yahoo_GOLDBEES_NS.csv`, A4) — the
  instrument an Indian investor actually holds (expense ratio, tracking, duty and premium included).
- **What the proxy leaves out:** the rupee gold proxy excludes customs-duty steps (e.g. 24 Jul 2024 15 → 6 %,
  13 May 2026 6 → 15 %) and the local premium, both of which shift MCX/IBJA rupee gold in specific months. Conclusions
  apply to duty-free rupee gold; the GOLDBEES cross-check carries the duty.

## Returns and alignment

Monthly **log** returns (non-overlapping → plain t, as in G-MACRO H3). Month-of-year is calendar knowledge, so there is
no release lag; the walk-forward rule (H3) learns each year's month set from **completed prior years only** and trades
from the last close of month m−1 to the last close of month m.

## Hypotheses (stated before the data)

- **H1 festival:** September, October and November (the Dhanteras/Diwali run-up) each have a mean rupee return > 0
  with t ≥ 2 in both halves. **H1b:** April and May (Akshaya Tritiya) likewise.
- **H2 carry-over:** December and January pass in rupees as they did in USD 2006–2026.
- **H3 tradable:** at the start of each year go long only in the 6 months with the highest mean rupee return over all
  prior years (≥ 5 years of history), flat otherwise, **0.15 % per switch**; OOS from the 6th year; pass only if the
  excess vs scaled buy-and-hold has t ≥ 2 in **both** OOS halves.
- **H4 (descriptive, not graded):** decompose each month's rupee effect into the USD-gold leg and the USD/INR leg
  (`log INR return = log USD return + log USD/INR return`) — the rupee's own month-of-year pattern (fiscal year-end,
  RBI defence, remittance seasons) is reported, not traded.

## Halves

Long sample: H1 = 1973-01 → 1999-12 · H2 = 2000-01 → the last complete month. Tradable sample: 2000-09 → 2013-12 ·
2014-01 → end. H3's OOS halves: the OOS span split at its midpoint date (computed, printed in the report).

## Pass criteria (PLAN f.1, binding)

- A month **PASSes** only if t ≥ 2 with the same sign in both halves of the long sample **and** the same sign in the
  tradable month-end sample. H3 passes only with OOS t ≥ 2 in both OOS halves after costs.
- **CONTEXT-ONLY:** |t| ≥ 2 in the full long sample only (the caption case, as the USD strip already is).
- **FAIL:** everything else.

Multiple testing: 12 months in rupees (+12 for the FX leg, reported) → ≈1.2 false |t| ≥ 2 expected in a full sample;
the both-halves condition is the guard.

## Negative controls (pre-registered; the study is void if a control "passes")

- **Relabel:** month labels permuted by a fixed permutation (seed 20261026) — no month may PASS.
- **Shuffle:** H3 run on a seed-shuffled return series — OOS |t| must be < 2.

## Prior

**CONTEXT-ONLY at best.** The rupee adds a steady depreciation drift (≈3–4 %/yr since 1973) that is not seasonal;
G-INDIA 6a: "no study shows a tradable MCX effect; Baur's autumn effect is small and unstable"; G-MACRO: Diwali shows
nothing in USD gold. A festival month passing in both halves would be new evidence and would still need the owner's
separate approval before any badge changes.

## Outputs

`reports/gold_program/GS-P4/results/*.csv`, `summary.json`, `REPORT.md`, `FINDINGS.md`, `FINDINGS_ROW.md`. Runnable today:
`/Users/sudheer/Desktop/jupyter_env/bin/python scripts/gold_studies/gs_p4_seasonality_in_inr.py`.

## Implementation notes and run record (26 Oct 2026)

- **N1 · tradable agreement = sign.** "The same sign in the tradable month-end sample" is implemented as written: the
  sign of the month's mean return 2000 → must match the long sample's. The first draft of the script (07:18 run) also
  demanded |t| ≥ 1 there; that extra bar was removed to match this plan. No verdict depends on it: no month passes
  both halves of the long sample, so no month reaches the agreement check.
- **N2 · "0.15 % per switch"** is charged on every flat→long and long→flat transition (0.30 % per round trip — twice the
  per-round-trip floor the other gold studies use; stricter, never laxer). The first draft charged 0.15 % per round
  trip: H3 then read OOS excess 1.67 %/yr (t 0.89) — FAIL; with the plan's cost it reads 1.10 %/yr (t 0.59) — FAIL.
- **N3 · the relabel control shuffles labels across observations.** "Month labels permuted by a fixed permutation" above
  would only *rename* the twelve months (a real March effect would reappear under another name and the control could
  never fail), so it is implemented as a seeded shuffle of each observation's month label — same count per month, the
  calendar structure destroyed — which is what a negative control must do. The test file proves it on a planted month.
- **N4 · the pre-registered month statistic is void; a drift-adjusted one is reported post hoc, capped.** This plan tests
  each month's mean rupee return **against zero**. On the real series the N3 shuffle control "passes" far too often:
  **44 % of the script's 100 seeds (seeds 20261027–20261126; 4.42 months at t ≥ 2 per shuffled run)** — the one figure the
  script publishes in `summary.json`, `FINDINGS.md` and `FINDINGS_ROW.md`; independent probes with other seed sets agree
  (B7's 26 Oct probe: 34 % of 200 fresh seeds, 3.75 such months per run; the wave-1 reviewer's: 37 % of 300, 4.19) — all far
  above the 10 % bar (`VOID_NULL_RATE`); 2 months "pass" at the pre-registered seed itself. The cause is drift: rupee gold
  rises about +1.03 %/month (USD gold ≈ +0.6, the rupee ≈ +0.4), so any random grouping of ~54 months reaches t ≥ 2 one
  time in three. By this plan's own rule ("the study is void if a control passes") the vs-zero statistic is **VOID**; the
  months it flagged (Jan, Feb, Aug, Sep — the first draft's CONTEXT-ONLY months) are what drift alone delivers.
  The script therefore also reports the **drift-adjusted** statistic — the month's mean minus the all-month mean of the
  same sample / half, the form G-STUDY's seasonality table used — with its own shuffle control and null rates over 100
  further seeds. Because that statistic was chosen after the results were seen, PLAN f.1 forbids a PASS from it: a
  drift-adjusted PASS is reported as CONTEXT-ONLY with `post_hoc_cap = true`; promoting it would need a fresh
  pre-registration (GS-P4b) on data not used here. Both verdicts are printed side by side (`verdict_pre`, `verdict_adj`,
  `verdict`).
- **Runs:** 07:18 (first draft, before the review: vs-zero statistic, fixed-permutation "control" → "CONTEXT-ONLY, Jan/Feb/
  Aug/Sep"), 10:50 (shuffle control added → the vs-zero statistic found void), 11:05 (drift-adjusted statistic added,
  capped → every month and hypothesis FAIL, largest |t| 1.58 for Jan; H3 FAIL; **overall FAIL — drift, not a calendar**).
  `FINDINGS.md` and `FINDINGS_ROW.md` are written by the script from `summary.json`, never by hand.
- **4 Nov 2026 (wave 1b, after the adversarial review):** the study-level verdict is now worded with both statistics —
  **"VOID (pre-registered statistic) / FAIL (post-hoc drift-adjusted, capped) — drift, not a calendar"** (`overall_label`;
  the machine verdict / badge consequence stays FAIL); H3's verdict is **signed** (`common.verdict_traded`: the rule must
  pay, t ≥ 2 in the OOS span and both OOS halves — a consistent loser is a FAIL, never a PASS; no number changed: t 0.59,
  halves 0.97 / −0.26); every `FINDINGS_ROW.md` row is 4-column (verdict in its own cell) and names the seed set. Re-run
  22:26 IST 4 Nov: every number identical to the 11:05 run of 26 Oct.
