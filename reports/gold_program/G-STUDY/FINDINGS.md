# G-STUDY · Is CFTC positioning (and the usual gold "health" indicators) useful to a gold trader? Findings (26 Oct 2026)

Long form in `REPORT.md`; every table in `RESULTS_TABLES.md`; script `g_study.py` (reproducible from `./data`, see `DATA_SOURCES.md`).
1,063 weekly COT reports for COMEX gold, 13 Jun 2006 → 20 Oct 2026 (legacy report 2000 → 2026 for the long sample), priced on
GC=F (COMEX front-month settlement). **Every signal is dated at its CFTC release (Friday 15:30 ET, holiday and shutdown delays
applied from the CFTC's own tables) and the entry is the next session's close (Monday).** Costs 0.15 % per round trip (the project
floor; MCX GOLD's exchange + brokerage cost is 0.018 %). Newey-West t-statistics for the overlapping 4- and 13-week windows.

**Verdict: FAIL as a forecasting tool, at every horizon, for every positioning metric. PASS (strong, stable) as a description of
what just happened. Publish the COT as a "who did what this week" panel, never as a buy/sell signal.**

| Signal (known at release) | 1 wk | 4 wk | 13 wk | Verdict |
|---|---|---|---|---|
| Managed-money net (level; also % of OI, 52-wk COT index, z-score) | IC −0.01 to −0.05, t ≤ 1.2 | IC 0.00–0.01 | IC 0.07–0.09, t ≤ 1.1; sign flips 2011-19 (−) vs 2020-26 (+) | **FAIL** |
| Classic rule: COT index ≥ 90 "crowded" vs ≤ 10 "washed out" | 0.07 % vs 0.26 % (t −0.8 / +0.2) | 1.08 % vs 0.63 % (t +0.4 / −0.5) — crowded weeks did *better* | 2.97 % vs 2.15 % | **FAIL** (lore not supported) |
| Managed-money net, 4-week change | IC −0.055, t −2.3 (the only \|t\| ≥ 2 of 45) | IC +0.01 | IC −0.02 | **WEAK → FAIL**: OOS long/flat +2.0 %/yr, t 0.95 |
| Commercial net (producer/merchant + swap dealers) and its COT index | t 0.3–0.7 | t −0.5 to −0.9 | t −1.0; 2020-26 IC −0.25 (wrong sign) | **FAIL** |
| Small-speculator (non-reportable) net | t −0.4 | t −0.2 | t 0.0 | **FAIL** |
| Open interest, 1- and 4-week change | t −1.4 / −0.1 | t −0.4 / +0.7 | t −1.6 / −0.4 | **FAIL** |
| Options-only managed-money net (combined − futures-only) | t −0.2 | t −0.1 | t 0.0 | **FAIL** (no information) |
| GLD tonnes, 4-week change | t −0.8 | t +0.1 | t +0.1 | **FAIL** |
| 10-y real yield (DFII10), 4-week change | t −0.6 | t −1.3 | t −0.2 | **FAIL** (contemporaneous only) |
| DXY, 4-week change | t −0.4 | t −1.4 | t −0.6 | **FAIL** (contemporaneous only) |
| OI-price quadrant (report week) | "new shorts" 0.11 % (t −0.6) | 0.29 % (t −1.6) | 1.03 % vs 2.74 % avg (t −2.0; 1 of 12 cells) | **CONTEXT-ONLY** |
| Month of year | — | Dec +2.5 % (t 2.5), Jan +2.4 % (t 2.2), Apr–Jun ≈ 0 | — | **CONTEXT-ONLY**: walk-forward "best 6 months" +0.3 %/yr, t 0.2 |
| Walk-forward long/flat rules after costs (45 learned + 24 fixed-direction) | — | — | — | **0 of 69 beat scaled buy-and-hold at t ≥ 2; 3 lost at t ≤ −2**; mean OOS excess −0.8 %/yr (learned), +0.2 %/yr (fixed) |

Descriptive use (the other job the owner asked for) — PASS:

| Same report week | Spearman vs gold's weekly move | R² | same sign | …and the NEXT week |
|---|---|---|---|---|
| Δ managed-money net | **+0.65** (stable: +0.66 / +0.70 / +0.60 by sub-period) | 31 % | 76 % | −0.02 |
| Δ commercial net | −0.66 | 34 % | 23 % (the mirror) | +0.01 |
| Δ managed-money gross long / gross short | +0.63 / −0.40 | 29 % / 12 % | 76 % / 35 % | −0.02 / 0.00 |
| Δ open interest · Δ small-spec net · Δ GLD tonnes | +0.39 · +0.30 · +0.32 | 12 · 11 · 16 % | | ≈ 0 |
| Δ real yield · Δ DXY · Δ USD/INR | −0.40 · −0.45 · −0.22 | 14 · 21 · 3 % | | ≈ 0 |
| Δ other reportables net | −0.07 | 0.3 % | 45 % | ≈ 0 |

- The 2024-11 → 2026-03 doubling ($2,606 → $5,242) happened while managed money **cut** net length by 66,900 contracts and COMEX OI
  **fell** by 122,000; commercials covered 62,600 shorts; GLD added 202 t. The COT shows who was *not* driving it, which is exactly
  why its level cannot time the market. The −21 % since the high: managed money flat (+5,800), commercials −32,600, "other
  reportables" +30,900. Latest report (20 Oct, released 23 Oct): three straight weeks of fund long liquidation, net 104,206
  (COT index 26, 49th percentile of history, 26 % of OI), OI 402,279 (22nd percentile; record 796,883 on 14 Jan 2020).
- **Use:** a weekly "who did what" strip (gross long/short changes by trader group, OI change, the quadrant label, the driver label)
  on the gold desk, labelled *explains the week — does not forecast*. Real yields and DXY are already on the Gold Pre-Open page:
  do not duplicate them. No COT alert, no COT index gauge presented as a signal, no long/flat COT rule.
