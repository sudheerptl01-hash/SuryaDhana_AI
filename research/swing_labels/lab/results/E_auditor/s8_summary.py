#!/usr/bin/env python3
"""Stage 8: write the audit verdict, lab-issue list and multiple-testing protocol into results.json."""
from common import save
issues = [
 {"id": 1, "severity": "HIGH", "issue": "Sector map is a 2026 snapshot (Nifty Total Market constituents, 748 entities) -> look-ahead/survivorship",
  "evidence": "sector!=NA predicts +56 bps/10d date-demeaned (t=5.6, non-overlapping), +34..+75 bps every year 2021-2025, collapses to +12 bps in 2026. Sorting on sec_rel_mom20 with EITHER sign = #1 and #2 of 106 single-feature strategies on 2023-25 (Sharpe 1.04 / 0.69) -> 2026 Sharpe -0.07 / 0.14. Removing sec_rel_mom20 from the WF model cuts mean daily XS-AUC excess by 15-34% in every year and sector-known share of picks from 82.5% to 68% (universe 56.7%).",
  "fix": "Drop sec_rel_mom20 from L.FEATURES; never use F.sector (or its NaN-ness) as a feature, filter, setup condition or label benchmark split; for max_per_sector treat NA as one capped bucket; if sectors are needed, rebuild a point-in-time map (dated constituent files) covering all names."},
 {"id": 2, "severity": "MEDIUM", "issue": "ETFs / MF units (ISIN INF...) are inside elig_base and fno_proxy",
  "evidence": "48,406 elig_base rows (3.5%; 130 ETFs incl. GOLDBEES, SILVERBEES, NIFTYBEES, MON100, HNGSNGBEES; ~21/day, rising to ~5% in 2025-26); 2,504 fno_proxy rows. They also enter xr_* ranks, breadth50, breadth_ad, dispersion.",
  "fix": "Require ISIN prefix 'INE' (equity shares) in elig_series/liq universe; rebuild xr_*, breadth, dispersion, fno_proxy on equities only."},
 {"id": 3, "severity": "MEDIUM", "issue": "portfolio_sim statistics: cohort return booked on signal date + overlapping sleeves -> Sharpe overstated, maxDD understated; benchmark Sharpe uses daily returns (not comparable)",
  "evidence": "Daily mark-to-market rebuild of identical picks: random baselines sim Sharpe 0.306 vs MTM 0.278 (x1.12), maxDD -28.6% vs -31.2%; WF model 2023-25 Sharpe 1.03 vs 0.83 (x1.24), maxDD -30.7% vs -34.0%. Step-return lag-1 autocorr 0.31.",
  "fix": "Compute equity daily mark-to-market (code: s6_sim_audit.py::mtm) and book P&L at exit date for by_year; or at least scale Sharpe by 1/sqrt(1+2*rho1)."},
 {"id": 4, "severity": "MEDIUM", "issue": "Duplicate Bc records with shifted ex-dates are applied twice",
  "evidence": "11 split/bonus duplicates -> 7 double-applied (HAL 2023-09-28 factor 0.25 instead of 0.5 -> +96.9% fake jump; LIKHITHA, RPPL, RUBYMILLS, AJMERA 0.04 vs 0.2, ONEPOINT, AKSHAR 1:5 bonus -> +17.4% fake jump NOT label-blocked). 30 dividends applied on two rows (median extra 0.53%).",
  "fix": "De-duplicate Bc events per (entity, kind, desc) within +-7 days before locating; never apply two identical events to the same located row."},
 {"id": 5, "severity": "MEDIUM-LOW", "issue": "Bc archive misses some splits/demergers -> unadjusted jumps (labels safe via 35% residual guard, features contaminated)",
  "evidence": "e.g. SHRIRAMFIN 5:1 split Jan-2025, 360ONE, SIEMENS demerger Apr-2025, WEL, SBGLP, MOTISONS, DAVANGERE, NAVKARURB, DOLPHIN, AGIIL, 6 ETF splits: no Bc record. 76 split-like (factor<=0.5) jumps without CA, all label-blocked. 1.1% of elig rows (1.9% of fno_proxy rows) have a label_block event in their last 250 bars -> mom_60/120, mom_12_1, hi52_dist, lo52_dist, dist_sma200, vol_60, beta_60 wrong for up to a year. Small unrecorded bonuses (<35% drop) would not be blocked; refined detector found ~0 convincing cases (candidates were genuine -20% circuit days).",
  "fix": "Infer the factor for residual jumps that coincide with an ISIN change and match a split factor (as shares_inferred does); or set long-lookback features to NaN when their window spans a label_block row."},
 {"id": 6, "severity": "LOW", "issue": "OOS scores exist only where the label is defined -> model picks can never land on future-suspended/delisted/demerger windows; random baseline can",
  "evidence": "0.082% of random picks fall on label-undefined rows (mean forced-exit return -5.9%); random CAGR 2023-25 1.66% (all rows) vs 1.81% (label-defined rows only): ~+0.15 pp/yr free advantage to any model strategy. Undefined non-tail elig rows have mean forced-exit return -15.8% (h=10).",
  "fix": "In walk_forward predict on mask & test-year rows regardless of label (evaluate metrics on labeled rows only), or give the random baseline the same label-defined mask."},
 {"id": 7, "severity": "LOW", "issue": "elig_next uses whether t+1 trades (look-ahead)",
  "evidence": "Only 41 elig rows (0.003%) excluded apart from the last panel date; their next-bar mean return -8.9%. Immaterial.",
  "fix": "Drop elig_next (labels are already NaN when t+1 is missing) or replace with known suspension notices."},
 {"id": 8, "severity": "LOW", "issue": "Dividend / rights parser gaps",
  "evidence": "540 of 9,511 dividend-like Bc records unparsed (259 'INTERIM DIVIDEND' and 180 'DIVIDEND' carry no amount; 'AGM/DIV-20 SPLDIV-15' formats lack 'RS'); rights 'RIGHTS 1:10 PRM RS 194/-' (no '@') -> blocked; TERP uses today's face value (16 rights events had a later split -> stale FV risk).",
  "fix": "Parse bare-number amounts after DIV/SPLDIV; accept 'PRM' without '@'; use face value as of the event date."},
 {"id": 9, "severity": "LOW", "issue": "Selection window bleeds into holdout; documentation drift",
  "evidence": "Runs with end='2025-12-31' include trades exiting in Jan-2026 (up to h days). lablib.py and build_panel.py docstrings still say CA adjustment comes from PREV_CLOSE (it comes from Bc records); brief says ~3.5M rows, panel has 3,097,741. Symbol-reuse guard is untested: all 7 'reuse' cases are the same issuer relisting with a new ISIN (consolidations) - correctly not merged.",
  "fix": "End dev signals at the last date with t+h <= 2025-12-31; update docstrings/brief."},
 {"id": 10, "severity": "METHOD", "issue": "Pooled AUC of an absolute label measures market timing, not stock selection",
  "evidence": "Within-date shuffled labels (zero stock-selection information) give pooled AUC 0.521/0.545/0.488/0.544 (2023-26) vs the real model's 0.523/0.568/0.494/0.549. Mean daily cross-sectional AUC separates them: 0.499-0.501 (shuffled) vs 0.523-0.548 (real).",
  "fix": "Report mean daily cross-sectional AUC/IC with non-overlapping t-stats; report timing AUC separately."},
]
protocol = [
 "Holdout: 2026-01-01..2026-09-10 is evaluated ONCE for at most 3 pre-registered finalists (label, features, h, step, top_k, cost fixed in writing first).",
 "Dev window: signals 2023-01-01..(last date with t+h <= 2025-12-31). Selection uses only dev results.",
 "Count every configuration evaluated on dev (team-wide N, all agents). Report N with every claim.",
 "Primary dev metrics: (a) mean daily cross-sectional AUC/IC with t-stat on non-overlapping dates (every h-th date), (b) excess CAGR and MTM Sharpe over a random baseline of >=10 seeds from the SAME mask.",
 "Minimum effect: XS-AUC >= 0.52 (IC >= 0.03) with t >= 3 overall and > 0.5 in each of 2023, 2024, 2025; positive excess over random at 80 bps; positive excess in >= 2 of 3 dev years.",
 "Luck hurdle: iid random picks are too narrow a null for concentrated/persistent portfolios. Use the persistent-tilt band: dev CAGR must exceed its p95 (8.4% at 50 bps, vs iid random mean 1.7%) and sim-Sharpe must exceed mu + sigma*Phi^-1(0.95^(1/N)) = 1.01/1.10/1.19/1.30/1.38 for N = 5/10/20/50/100 (iid null: 0.69/0.74/0.79/0.85/0.90).",
 "Haircut: expect most dev excess to vanish out of sample: top-5 of 106 single-feature strategies had dev Sharpe 0.68 -> 2026 Sharpe 0.02; Spearman(dev, 2026 Sharpe) = 0.11 (p=0.26). Plan with a >=50% haircut on dev excess (Harvey-Liu style) and require the 2026 excess over random to be > 0.",
 "Leak tripwires: XS-AUC > 0.58, top-decile 10d excess > 300 bps, or Sharpe > 3 => presume leakage (one day of look-ahead produced XS-AUC 0.63-0.65 and Sharpe ~11).",
 "Effective sample size: an absolute 10d label on ~1.35M rows carries ~1,000 independent observations (ICC 0.18, overlap DE 7.1); 20d ~490. Use date-clustered / non-overlapping statistics, never row-level n.",
]
save("s8_summary", {"lab_issues": issues, "multiple_testing_protocol": protocol,
                    "verdict": "Label machinery is sound (next-open entry, NaN handling, CA adjustment, entity identity, PIT features all verified); "
                               "one HIGH leak (2026 sector snapshot via sec_rel_mom20/sector), ETFs in universe, and optimistic portfolio_sim statistics must be fixed before candidates are judged."})
