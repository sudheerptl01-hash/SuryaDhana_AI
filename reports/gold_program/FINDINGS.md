# Gold program: findings (26 Oct 2026)

Program-level verdict rows for the GOLD page, in the format of `reports/fii_positioning/FINDINGS.md`. Each row points at
the study that produced it: positioning `G-STUDY/FINDINGS.md` (+ `REPORT.md`, `RESULTS_TABLES.md`, `g_study.py`,
`data/`); drivers `G-MACRO/study.json` (`g_study.py`); India flows `G-INDIA/REPORT.md` (`scratch/amfi_study_results.json`);
GLD tonnes `GS-P1/REPORT.md` (`scripts/gold_studies/gs_p1_gld_tonnes.py`); seasonality in rupees `GS-P4/REPORT.md`
(`scripts/gold_studies/gs_p4_seasonality_in_inr.py`). Sources and the 71 derived metrics with their badges: `SOURCES.md`
(§10–§11); the labelling rules: `PLAN.md` §f. Every signal is dated at its public release (`release_at`: CFTC Friday
15:30 ET with holiday and shutdown shifts, GLD T+1, FRED T+1), entered at the next session's close, charged 0.15 % per
round trip (the project floor; MCX GOLD's exchange + brokerage cost is 0.018 %), with Newey-West t-statistics for the
overlapping windows. A PASS as a forecast needs |t| ≥ 2 in the full sample and the same sign with |t| ≥ 2 in both halves.

**Verdict: FAIL as a forecast for every positioning, flow, macro and seasonal series tested, at every horizon. PASS as a
description of the week that just ended (the funds' net change, the commercials, open interest, GLD, real yields and the
dollar all move with the week's price, none with the next week's). No `signal` badge exists; every gold number on the
terminal is `context`, `arithmetic` or `heuristic`, and nothing gold feeds the Decision Desk, the S1 shadow, a directional
alert or the paper ticket's price.**

| Study · signal (known at release) | Result | Both halves | Verdict |
|---|---|---|---|
| G-STUDY · managed-money net: level, % of OI, 52-wk COT index, z-score (1,063 reports 2006→2026, GC=F) | 1 wk IC −0.01 to −0.05 (t ≤ 1.2); 4 wk IC 0.00–0.01; 13 wk IC 0.07–0.09 (t ≤ 1.1) | sign flips: 2011–19 (−) vs 2020–26 (+) | **FAIL** |
| G-STUDY · classic rule: COT index ≥ 90 "crowded" vs ≤ 10 "washed out" | next 4 wk: crowded +1.08 % vs washed-out +0.63 % (t +0.4 / −0.5) — the lore points the wrong way; 13 wk 2.97 % vs 2.15 % | — | **FAIL** |
| G-STUDY · managed-money net, 4-week change | 1 wk IC −0.055 (t −2.3, the only \|t\| ≥ 2 of 45 tests); 4 wk IC +0.01; OOS long/flat +2.0 %/yr (t 0.95) | — | **WEAK → FAIL** |
| G-STUDY · commercial net (producer/merchant + swap dealers) and its COT index | t 0.3–0.7 (1 wk), −0.5 to −0.9 (4 wk), −1.0 (13 wk) | 2020–26 IC −0.25 (wrong sign) | **FAIL** |
| G-STUDY · small-speculator net · OI 1-/4-wk change · options-only managed-money net (combined − futures) | \|t\| ≤ 1.6 at 1 / 4 / 13 wk; options-only t ≤ 0.2 | — | **FAIL** |
| G-STUDY · GLD tonnes 4-wk Δ · 10-y real yield (DFII10) 4-wk Δ · DXY 4-wk Δ | \|t\| ≤ 1.4 at 1 / 4 / 13 wk | — | **FAIL** (contemporaneous only) |
| G-STUDY · OI × price quadrant of the report week (new longs / new shorts / short covering / long unwinding) | 1 of 12 cells at \|t\| ≥ 2 ("new shorts", 13 wk 1.03 % vs 2.74 % avg, t −2.0) | — | **CONTEXT-ONLY** |
| G-STUDY · month of year (GC=F 2006→); G-MACRO H3 (World Bank 1971→ spliced) | Dec +2.5 % (t 2.5), Jan +2.4 % (t 2.2), Apr–Jun ≈ 0; walk-forward "best 6 months" +0.3 %/yr (t 0.2) | no month passes both halves | **CONTEXT-ONLY** |
| G-STUDY · 45 learned + 24 fixed-direction long/flat rules, walk-forward after costs | 0 of 69 beat scaled buy-and-hold at t ≥ 2; 3 lost at t ≤ −2; mean OOS excess −0.8 %/yr (learned), +0.2 %/yr (fixed) | — | **FAIL** |
| GS-P1 · GLD daily tonnes: 1-, 5- and 20-day Δ → 5 and 20 sessions (5,515 trust dates 2004-11-18 → 2026-10-22, split 2015-12-31) | IC 0.005–0.036 (\|t\| ≤ 1.06); tercile spreads −0.04 to +0.24 % (\|t\| ≤ 0.69); OOS long/flat after costs −2.31 to +2.14 %/yr (\|t\| ≤ 1.80) | IC +0.02 / −0.01 (S1·5d) … +0.01 / +0.07 (S3·20d) | **FAIL** (all six) |
| GS-P1 · same-week Δ tonnes vs Δ price | Spearman +0.29 (n 1,144) | +0.28 / +0.31 | **PASS as description** |
| GS-P4 · H1 festival (Sep/Oct/Nov) (rupee gold, 1973 →, drift-adjusted) | Sep 2.00 % (t vs 0 2.75; excess 0.97 % t 1.33) FAIL; Oct 0.98 % (t vs 0 1.97; excess −0.05 % t −0.10) FAIL; Nov 0.61 % (t vs 0 1.00; excess −0.42 % t −0.70) FAIL | Sep excess t 1.10 · Oct excess t 0.76 · Nov excess t −1.02 / Sep excess t 0.74 · Oct excess t −1.33 · Nov excess t 0.24 | **VOID (pre-registered) / FAIL (drift-adjusted, capped)** |
| GS-P4 · H1b Akshaya Tritiya (Apr/May) (rupee gold, 1973 →, drift-adjusted) | Apr 0.42 % (t vs 0 0.79; excess −0.61 % t −1.15) FAIL; May 0.80 % (t vs 0 1.56; excess −0.23 % t −0.46) FAIL | Apr excess t −1.03 · May excess t −0.73 / Apr excess t −0.64 · May excess t 0.10 | **VOID (pre-registered) / FAIL (drift-adjusted, capped)** |
| GS-P4 · H2 Dec/Jan carry-over (rupee gold, 1973 →, drift-adjusted) | Jan 2.58 % (t vs 0 2.64; excess 1.55 % t 1.58) FAIL; Dec 0.79 % (t vs 0 1.33; excess −0.24 % t −0.41) FAIL | Jan excess t 0.97 · Dec excess t −0.04 / Jan excess t 1.74 · Dec excess t −0.72 | **VOID (pre-registered) / FAIL (drift-adjusted, capped)** |
| GS-P4 · H3 · walk-forward best-6-months long/flat in rupees (GC=F × USD/INR month-ends, 0.15 % per switch = 0.30 % per round trip) | OOS 2005 →: excess vs scaled B&H 1.10 %/yr (t 0.59), exposure 50 %; shuffled returns reach \|t\| ≥ 2 in 7% of seeds | t 0.97 / t −0.26 (OOS cut 2015-11-30) | **FAIL** |
| GS-P4 · the pre-registered statistic (each month's mean vs zero), for the record | Jan, Feb, Aug, Sep at t ≥ 2 in the full sample — but shuffled month labels 'pass' in 44% of 100 seeds (seeds 20261027–20261126; 4.42 such months per run): the statistic measures the 1.03 %/month drift, not the calendar | null PASS rate vs 0 44% / drift-adjusted 3% | **VOID (PLAN N4; the drift-adjusted rows above replace it)** |
| G-MACRO H1 · 10-y real yield, level and change (6,049 daily obs 2003→2026) | contemporaneous weekly beta −9.9 %/100 bp 2010–21, −5.0 since 2022; the level fit sign-flipped after 2022; the 4-wk change forecasts nothing (G-STUDY) | present in every regime, weaker since 2022 | **CONTEXT** (explainer, no lead) |
| G-MACRO H2 · the dollar (DXY) | contemporaneous beta ≈ −1 in every regime; no lead | ≈ −1 / ≈ −1 | **CONTEXT** (explainer, no lead) |
| G-MACRO H4 · geopolitical risk (GPR) · H5 · fair-value regression (real yield + DXY) | H4: GPR change → next month t 1.0; H5: the model says $788 with gold at $4,000 and a trailing refit has the wrong sign | — | **FAIL** (H4) · **DO-NOT-PUBLISH** (H5) |
| G-INDIA-1 · AMFI gold-ETF monthly flows (79 months) | flows chase last month's rupee return (ρ +0.25, p 0.03); flow → next month ρ +0.12 (p 0.31) | — | **FAIL** as timing |
| Accuracy log (SOURCES.md H2) · the 08:45 fair-open model and the ₹300 chase limit | 3 scored mornings: model mean miss ₹2,496 vs naive (open = settlement) ₹2,147; 0 % within ₹300; the 15 Oct row looks like a stale baseline | — | **HEURISTIC** (chip on the verdict; re-decide at 20 rows) |

Descriptive use — the other job the owner asked for ("who did what this week") — PASS, strong and stable:

| Same report week (G-STUDY) | Spearman vs gold's weekly move | R² | same sign | …and the NEXT week |
|---|---|---|---|---|
| Δ managed-money net | **+0.65** (+0.66 / +0.70 / +0.60 by sub-period) | 31 % | 76 % | −0.02 |
| Δ commercial net | −0.66 | 34 % | 23 % (the mirror) | +0.01 |
| Δ managed-money gross long / gross short | +0.63 / −0.40 | 29 % / 12 % | 76 % / 35 % | −0.02 / 0.00 |
| Δ open interest · Δ small-spec net · Δ GLD tonnes | +0.39 · +0.30 · +0.32 | 12 · 11 · 16 % | | ≈ 0 |
| Δ real yield · Δ DXY · Δ USD/INR | −0.40 · −0.45 · −0.22 | 14 · 21 · 3 % | | ≈ 0 |
| Δ other reportables net | −0.07 | 0.3 % | 45 % | ≈ 0 |

- The 2024-11 → 2026-03 doubling ($2,606 → $5,242) happened while managed money **cut** net length by 66,900 contracts
  and COMEX OI **fell** by 122,000; commercials covered 62,600 shorts; GLD added 202 t. The COT shows who was *not*
  driving it, which is exactly why its level cannot time the market. The −21 % since the high: managed money flat
  (+5,800), commercials −32,600, "other reportables" +30,900. Latest report (20 Oct, released 23 Oct): three straight
  weeks of fund long liquidation, net 104,206 (COT index 26, 49th percentile of history, 26 % of OI), OI 402,279
  (22nd percentile; record 796,883 on 14 Jan 2020).
- Seasonality in rupees only *looks* stronger than in dollars because rupee gold drifts +1.03 %/month (USD gold ≈ +0.6,
  the rupee ≈ +0.4 against the dollar): testing each month's mean against zero flags Jan, Feb, Aug and Sep, but shuffled
  month labels do the same in 44 % of seeds, so that statistic is void (GS-P4 PLAN N4). Measured against the all-month
  mean no month reaches |t| ≥ 2 even in the full sample, the festival months do not pass, and the rupee best-6-months
  rule earns t 0.59 after 0.15 % per switch. The `m.season` grid shows the cells with that caption; no month is a
  position.
- G-COT's own horizon test (`G-COT/data/study_tables.md`: bottom-decile fund net % OI → +5.2 % over 65 sessions, t 2.6
  full, 1.4 / 1.3 halves) fails the halves rule the same way; "washed-out positioning has preceded good quarters more
  often than not" may appear as a LEARN sentence, never as a badge (SOURCES.md disagreement 19).
- **Pre-registered, waiting for stored history (PLAN §i O-13; PLAN.md written before any result):** G-STUDY-2 daily
  OI × price quadrant on CME product OI 2014→ (`scripts/gold_studies/g_study_2_oi_quadrant.py`; needs the CME FTP
  backfill, O-6); GS-P2 WGC weekly ETF flows by region 2003→ (`gs_p2_wgc_flows.py`; needs the WGC terms decision O-1
  and backfill); GS-P3 SGE premium + Au(T+D) direction and the G-INDIA MCX OI matrix (after ≈ 60 sessions of stored
  rows); GS-PREMIUM India / Shanghai premiums (after two years). Honest prior from everything above: FAIL as timing,
  PASS as context. A badge moves from `context` to `signal` only through a PASS row added to this file from one of these
  plans (PLAN §f.5), and even then the Decision Desk and the paper ticket stay decoupled until the owner approves separately.
- **Use:** the GOLD page's POSITIONING view is a weekly "who did what" strip (gross long/short changes by trader group,
  OI change, the quadrant label, the fund-driver label) labelled *explains the week — does not forecast*; the health
  verdict is a sentence of thresholded clauses that ends "describes, does not predict"; the COT index / z-score /
  percentile render as a crowdedness gauge worded "not a signal — no forecasting power 2006–2026 (G-STUDY)" and never
  coloured; real yields and the dollar live once, on MACRO, as contemporaneous explainers with their rolling correlation;
  GLD, WGC flows and the seasonality grid are `context`. No COT alert, no COT rule, no composite score, no fair-value
  forecast panel, nothing into the Desk, the S1 shadow or the ticket's price.
