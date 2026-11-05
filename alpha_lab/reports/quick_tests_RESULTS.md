# Appendix Q quick tests — results (run once, as pre-registered)
Generated 2026-10-14 21:03 by `alpha_lab/strategies/quick_tests.py`. Gross diagnostics, weekly frame, NW t; NOT strategies and NOT net of costs. Pass bar fixed in PLAN.md Appendix Q before the run.

                             test                             H                       P-a                 P-b                        verdict
         Q1 excess carry (FUT-04)    discount quintile lags h20           -0.49% (t -4.2)     -0.38% (t -2.9)                         Robust
          Q2 O/S ₹-proxy (OPT-08)    top quintile lags h5 & h20       -0.10% (t -0.7) h20 -0.13% (t -0.9) h20 h5: No effect · h20: No effect
Q3 variance risk premium (POS-05) high VRP → higher fwd returns +0.10pp (t 0.1) h20 NIFTY     +0.39pp (t 0.2)                      No effect
         Q4 index OI-PCR (POS-06)      exploratory (both signs)                 see table           see table                      No effect
       Q5 F&O entry/exit (EVT-03)                   descriptive         entry +60s: 0.51%   exit +60s: -6.35%          descriptive (no gate)

A 'Robust'/'Lead' here is a candidate for a future pre-registered strategy study — never a live rule.

## Q1 — Excess carry (stock-futures basis − 6.5%), FUT-04
Weekly quintiles within F&O names; ex-div symbol-weeks stripped: 3,639; |basis|>40%/yr dropped: 1,079; days-to-expiry ≥ 3.

 h  quintile  events  P-a mean%  P-a t  P-b mean%  P-b t
 5         1   12309     -0.184  -2.50     -0.091  -1.82
 5         2   12444     -0.118  -1.98      0.018   0.39
 5         3   12442      0.106   1.93      0.044   0.95
 5         4   12449      0.160   3.01      0.102   2.30
 5         5   12591      0.156   2.45      0.063   1.07
20         1   12309     -0.493  -4.16     -0.376  -2.86
20         2   12444     -0.204  -1.54      0.115   1.09
20         3   12442      0.221   1.96      0.145   1.45
20         4   12449      0.338   3.34      0.065   0.72
20         5   12591      0.223   2.04      0.413   3.27

- Bottom (discount) quintile, h20: P-a -0.49% (t -4.16) · P-b -0.38% (t -2.86) → **Robust**
- Q5−Q1 spread h20: P-a +0.72% (t 3.61) · P-b +0.79% (t 3.72)
- Redundancy probe (reporting only, after the verdict): discount-quintile names are momentum-NEUTRAL (mean momentum pct 0.495), and the bottom-quintile h20 effect survives restricted to momentum-middle names (P-a −0.69%, t −3.17 · P-b −0.41%, t −1.92) — not the momentum factor in disguise.

## Q2 — Option-to-stock ₹-volume (O/S proxy), OPT-08
5-session option ₹-value / 5-session cash turnover, weekly quintiles within F&O names.

 h  quintile  P-a mean%  P-a t  P-b mean%  P-b t
 5         1     -0.003  -0.04      0.073   1.20
 5         5     -0.099  -1.81     -0.102  -1.97
20         1     -0.080  -0.53      0.007   0.04
20         5     -0.103  -0.70     -0.131  -0.90

- Top-quintile verdicts: **h5: No effect · h20: No effect**

## Q3 — Variance risk premium (POS-05)
(VIX/100)² − 21-session realised NIFTY variance; monthly terciles within each period; index close-to-close forward returns (no open series for indices). EW-L leg starts ~2011 (panel history).

            period  h ret of  High%  Low%  High−Low%  t(diff)  n
P1 2009-10→2019-12 20  NIFTY   0.80  0.70       0.10     0.10 82
P1 2009-10→2019-12 20   EW-L   1.01 -0.25       1.26     0.92 79
P1 2009-10→2019-12 60  NIFTY   1.82  2.02      -0.20    -0.12 82
P1 2009-10→2019-12 60   EW-L   0.58  1.46      -0.88    -0.33 79
   P2 2020→2026-10 20  NIFTY   1.14  0.75       0.39     0.24 54
   P2 2020→2026-10 20   EW-L   1.72  2.37      -0.66    -0.30 54
   P2 2020→2026-10 60  NIFTY   4.21  3.60       0.60     0.19 53
   P2 2020→2026-10 60   EW-L   6.07  7.50      -1.43    -0.35 53

- Primary (NIFTY h20 High−Low): **No effect**

## Q4 — NIFTY OI put-call ratio (POS-06)
Level percentile (252-session window; usable from 2020-10, so P-a* = 2020-10→2023-12) and 5-session change; terciles per period; NIFTY close-to-close forward returns. Exploratory: best verdict = Lead.

          signal period  h  High−Low%     t
      level pctl   P-a*  5       0.44  1.23
      level pctl   P-a* 10       0.63  1.05
      level pctl   P-a* 20       1.84  1.81
      level pctl    P-b  5       0.45  1.26
      level pctl    P-b 10       0.57  1.01
      level pctl    P-b 20       0.23  0.30
5-session change   P-a*  5       0.05  0.14
5-session change   P-a* 10       0.05  0.08
5-session change   P-a* 20       0.66  0.65
5-session change    P-b  5       0.17  0.45
5-session change    P-b 10      -0.31 -0.52
5-session change    P-b 20      -0.67 -0.69

- Verdict: **No effect**

## Q5 — F&O inclusion / exclusion events (EVT-03)
Cumulative excess vs EW liquid universe, sessions +1…+20 and +1…+60; exits require the stock to keep trading in cash (≥ 40 of 60 sessions) so delistings are excluded; entry events within 60 days of the 2019-10 data start dropped (left-censoring). Same-date clusters averaged first (NSE revises in batches).

event  h  events  clusters  mean%            CI95
entry 20     163        41  -1.17  [-3.23, +0.90]
entry 60     163        41   0.51  [-1.90, +2.92]
 exit 20      80        33  -2.21  [-4.49, +0.07]
 exit 60      80        33  -6.35 [-11.22, -1.48]

- Descriptive only (pre-registered: no gate; small n, clustered revision dates).

