# R2_rel - Relative (selection) label architecture, lab v2

Agent: R2_rel. Scope: the definitive cross-sectional relative label for a 5-20 day NSE swing trader, h in {10, 15, 20}. Lab v2 only (no sector data, ETFs excluded, elig_base as rebuilt). Entry open[t+1], exit close[t+h]; labels NaN where `fw.ok(h)` fails; eligibility selects rows and never changes a label. Models: `L.walk_forward2` (yearly expanding folds 2023-2026, embargo h+2, date_step 2, n_jobs 2, default LightGBM, 52 PIT features). Learnability: per-date cross-sectional IC/AUC with non-overlapping t (identical to `L.xs_metrics`; cross-checked to 1e-12 on the first model). Investability: `L.Sim` maths with the horizon-matched 5-seed random baseline on the same mask (random bands cached on disk, otherwise identical to `S.compare`), 50/80/130 bps. Selection on DEV 2023-2025 only; 2026 (Jan 1 - Oct 14) is reported separately and never used to choose.

## 1. Headline

* **Selected on DEV (composite of 7 DEV-only criteria, fixed before the last 6 models were trained; Section 9): `h20_neumom_RANK`** (runner-up `h20_neumom_C20`).
* `h20_neumom_RANK`, long top-20, step 5, 50 bps: DEV CAGR 30.9% vs horizon-matched random 11.8% (excess +19.1%, NW t 4.25); maxDD -25.6%; 80 bps 26.2%. Phase-averaged (all 5 entry phases) DEV excess +15.8%/yr, t 4.11.
* 2026 holdout (not used for selection): CAGR 16.0% vs random 6.9% (excess +9.2%, t 1.54); 80 bps 12.1%; phase-averaged excess +3.9%/yr (t 0.60). Nifty 500 2026 YTD -7.8%.
* AVOID overlay with the same score (equal-weight all elig names except the model's bottom 30%): DEV 15.1% vs random-70% 11.2% / universe EW 11.2%, excess +3.8% (t 3.40); 2026 8.2% vs EW 6.4% (excess +1.8%, t 1.02).
* Variants: 75 label constructions screened for event rates, 23 walk-forward models, 1120 S.compare configurations on DEV, 30 reference sorts, 18 cross-horizon runs and 920 phase-shift runs = 2088 DEV portfolio runs; **477 distinct DEV strategy specifications at 50 bps** (costs 80/130 and phase shifts are not new specs). One-sided 5% Bonferroni hurdle: t = 3.71 for the distinct specs, 3.91 adding round 1's ~600 variants, 4.07 counting every run (all very conservative: the tests are highly correlated).


**What the DEV evidence supports (and how strongly)**

1. **Horizon: hold 20 days.** Skill is highest at h=10 (phase-averaged DEV excess +23.8%/yr, t 4.79) but
   costs decide: DEV CAGR at 80 bps is 16.2% (h=10) vs 19.6% (h=15) vs 25.2% (h=20); at 130 bps 2.6% vs
   10.2% vs 17.7%. The training horizon barely matters: any of the three scores held 20 days earns
   +15.1..+18.1% DEV excess (t 3.3-4.0).
2. **Neutraliser: the per-date OLS residual on [shrunk beta, vol_20, log_turn20, mom_12_1] ("neumom")**
   beats neu, which beats size and none. Phase-averaged DEV t at h=20: 4.11 / 3.81 / 2.90 / 3.27; at h=10:
   4.90 (neumom) / 4.79 (neu) / 3.70 (none). Dropping beta/vol neutralisation is a cliff. It turns the 2026
   phase-averaged excess negative (none -7.7%, size -1.8%). It also restores the market-direction-dependent
   beta tilt (corr 0.60 with the window's market return vs 0.06 for neumom).
3. **Label form: continuous rank (RANK), 20/60/20 and top-30% binary are statistically tied on DEV.**
   With neumom the phase-averaged t values are 4.11 / 5.07 / 4.57, and the composite mean ranks are
   2.9 / 3.3 / 3.6. The 30/40/30 and 33/33/33 forms are slightly weaker (3.61 / 3.30 with neu). Rare or
   symmetric binary cuts fall off cliffs: T10 3.01, T20 3.39, T50 1.23. An explicit bottom-30% AVOID
   model fails as a long score (0.09) and as an avoid list. The pre-declared composite picks
   **neumom RANK**.
4. **The robust edge is still the avoid side.** Bottom-30% AUC is 0.548 (DEV) and 0.554 (2026) for
   neumom RANK, while top-30% AUC is only 0.517 and 0.508. Dropping the model's bottom 10-30% from an
   equal-weight book adds +1.7..+3.8%/yr on DEV (t 3.4-3.8). It adds +1.3..+1.8% in 2026 (t 1.0-1.8),
   with factor-adjusted alpha +2.5%/yr (t 3.73) in 2026.
5. **2026 holdout (never used to choose): positive but weak for the selected label.** Single-phase
   excess is +9.2% (t 1.54). The phase-averaged excess, which is phase-robust, is **+3.9%/yr (t 0.60)**.
   The default calendar phase happened to be the best of 5. Net CAGR was 13.9% phase-averaged vs a 10.2%
   random baseline and a Nifty 500 down 7.8%. The tail forms did better in 2026 (neumom T30 +11.6%,
   t 2.14). Most of that came from a high-vol loading in a high-vol momentum rally: neumom T30's 2026
   factor alpha is +1.8% (t 0.31).
6. **Statistics.** The best DEV t (4.25) clears the 477-spec Bonferroni hurdle of 3.71 and the
   hurdle of 3.91 that includes round 1, but not by much. Against a persistence-matched random null the model sits
   5.5 sd above the null mean on DEV. A constant per-stock random tilt can reach +19.5% DEV excess with
   NW t 3.9 (max of 40), so Newey-West t is NOT reliable for persistent tilts (Section 7).


## 2. Label construction

```
r_h    = open[t+1] -> close[t+h]  (adjusted; NaN unless fw.ok(h))
V_h    = elig_base & isfinite(r_h)          # cross-section for winsorising, OLS and ranking
rw_h   = clip(r_h, per-date 1st pct, per-date 99th pct) over V_h
resid  = rw_h - X b_t   (per-date OLS over V_h, intercept always)
   neu    : X = [0.5*clip(beta_60,0,3)+0.5, vol_20, log_turn20]     (= round-1 XR_neu, shrunk beta)
   neumom : neu + mom_12_1 (NaN -> per-date median; 11.8% of elig rows)
   size   : X = [log_turn20]
   none   : X = []  (rank of winsorised raw return == rank of return minus index)
pct    = per-date percentile rank of resid over V_h  (0,1]
forms  : RANK = pct-0.5 (regression) | C30 +1 pct>0.7 / -1 pct<=0.3 | C20 | C33 (multiclass, score P(+1)-P(-1))
         T30/T20/T10/T50 = 1{pct > 1-q} (binary) | B30 = 1{pct <= 0.3} (binary AVOID; score = -P)
```

| h | labelled elig rows | share of elig_base | median names/date | xs R2 neu | xs R2 neu+mom | xs R2 size | rank corr neu vs none | neu vs size | neu vs neu+mom |
|---|---|---|---|---|---|---|---|---|---|
| 10 | 1,303,291 | 99.0% | 1056 | 0.035 | 0.042 | 0.011 | 0.973 | 0.982 | 0.995 |
| 15 | 1,296,467 | 98.4% | 1055 | 0.035 | 0.042 | 0.012 | 0.974 | 0.983 | 0.995 |
| 20 | 1,289,713 | 97.9% | 1054 | 0.035 | 0.042 | 0.012 | 0.974 | 0.983 | 0.995 |

Neutralisation explains only 1-4% of the cross-sectional variance of 20-day returns, so the label changes by a few percent of rows, but (Section 3) it removes the market-dependent composition tilt.

## 3. Event rates and label diagnostics

### 3a. Class shares and stability (30/40/30 form, all h x neutralisers)

| h | neutraliser | +1 share | +1 share by year (min-max) | monthly +1 std | +1 share by liquidity tercile (low/mid/high) | fno_proxy +1/-1 | liq5 +1/-1 | corr(monthly +1, Nifty month) | class disagreement vs neu |
|---|---|---|---|---|---|---|---|---|---|
| 10 | neu | 30.0% | 30.0-30.0% | 0.0001 | 29.6/30.8/29.8 | 29.3/25.4 | 30.2/29.3 | -0.12 | - |
| 10 | neumom | 30.0% | 30.0-30.0% | 0.0001 | 29.6/30.7/29.8 | 29.4/25.4 | 30.2/29.3 | -0.12 | 0.035 |
| 10 | size | 30.0% | 30.0-30.0% | 0.0001 | 29.5/30.7/29.9 | 29.5/25.5 | 30.2/29.4 | -0.12 | 0.084 |
| 10 | none | 30.0% | 30.0-30.0% | 0.0001 | 29.0/30.5/30.6 | 30.5/25.7 | 30.4/29.3 | -0.12 | 0.110 |
| 15 | neu | 30.0% | 30.0-30.1% | 0.0001 | 29.4/30.9/29.8 | 29.3/25.4 | 30.2/29.3 | -0.07 | - |
| 15 | neumom | 30.0% | 30.0-30.1% | 0.0001 | 29.5/30.8/29.9 | 29.4/25.4 | 30.2/29.3 | -0.07 | 0.037 |
| 15 | size | 30.0% | 30.0-30.1% | 0.0001 | 29.4/30.7/30.0 | 29.5/25.5 | 30.3/29.4 | -0.07 | 0.082 |
| 15 | none | 30.0% | 30.0-30.1% | 0.0001 | 28.9/30.6/30.6 | 30.5/25.8 | 30.4/29.3 | -0.07 | 0.109 |
| 20 | neu | 30.0% | 30.0-30.1% | 0.0001 | 29.3/30.9/29.9 | 29.4/25.5 | 30.3/29.4 | 0.04 | - |
| 20 | neumom | 30.0% | 30.0-30.1% | 0.0001 | 29.4/30.8/29.9 | 29.5/25.5 | 30.3/29.3 | 0.04 | 0.038 |
| 20 | size | 30.0% | 30.0-30.1% | 0.0001 | 29.3/30.8/30.0 | 29.5/25.6 | 30.3/29.4 | 0.04 | 0.081 |
| 20 | none | 30.0% | 30.0-30.1% | 0.0001 | 28.8/30.7/30.7 | 30.5/25.8 | 30.5/29.3 | 0.04 | 0.108 |


* **Rank labels make the event rate a design parameter, not a market outcome.** Every (h, neutraliser)
  has +1 = 30.0% in every year, regime and month (monthly std 0.0001). Correlation with the Nifty month is
  noise (-0.12..+0.04). The cut sets the rate exactly: 20%, 30% or 33%.
* **What does move when parameters change:**
  * **Liquidity mix.** "none" puts slightly fewer +1 in the illiquid tercile (28.8/30.7/30.7 at h=20).
    Neutralising on log_turn20 flattens this to 29.3-29.4 / 30.8-30.9 / 29.9-30.0.
  * **Sub-universes.** On fno_proxy names +1 is 29.3-30.5% but -1 is only 25.4-25.8%: large liquid names
    disperse less and sit in the middle class. A label defined on the full elig cross-section is therefore
    not 30/40/30 inside the F&O universe. On liq5, +1/-1 are 30.2-30.5% / 29.3-29.4%.
  * **Class churn from the neutraliser.** Versus neu, neumom changes 3.5-3.8% of class assignments, size
    8.1-8.4% and none 10.8-11.0%. The neutraliser explains 1.1-1.2% (size) to 4.2% (neumom) of the
    cross-sectional variance.
  * **Horizon.** Lag-1 label autocorrelation is 0.86 / 0.90 / 0.93 for h = 10 / 15 / 20 (window overlap).
    corr(pct_t, pct_t+h) is -0.016..+0.006, so successive non-overlapping labels are independent. There is
    no label-level momentum or reversal to exploit or to fear.


### 3b. Label/P&L coherence: relative classes are NOT absolute outcomes

| h | neutraliser | mean net bps +1 / 0 / -1 (50 bps cost) | excess vs same-day EW bps +1 / -1 | P(net>0 | +1) | P(net>0|+1) by year (min-max) | worst month P(net>0|+1) | corr(monthly P(net>0|+1), Nifty month) | P(net>0 | -1) | per-date +1 minus -1 spread bps |
|---|---|---|---|---|---|---|---|---|---|
| 10 | neu | 794 / -87 / -701 | 800 / -695 | 88.9% | 84.5-95.2% | 56.1% | 0.63 | 5.6% | 1495 |
| 10 | neumom | 792 / -88 / -698 | 798 / -692 | 88.8% | 84.4-95.0% | 56.0% | 0.64 | 5.8% | 1489 |
| 10 | size | 804 / -85 / -714 | 810 / -707 | 89.5% | 84.7-95.6% | 56.2% | 0.63 | 4.7% | 1517 |
| 10 | none | 809 / -85 / -720 | 816 / -713 | 89.8% | 84.9-95.7% | 56.4% | 0.63 | 4.2% | 1528 |
| 15 | neu | 1021 / -81 / -831 | 995 / -856 | 90.3% | 83.8-96.6% | 46.2% | 0.55 | 5.9% | 1850 |
| 15 | neumom | 1017 / -81 / -827 | 992 / -852 | 90.1% | 83.7-96.4% | 46.2% | 0.56 | 6.2% | 1843 |
| 15 | size | 1032 / -78 / -846 | 1006 / -871 | 90.8% | 84.2-97.1% | 46.5% | 0.55 | 5.2% | 1876 |
| 15 | none | 1039 / -77 / -853 | 1013 / -879 | 91.2% | 84.5-97.3% | 46.9% | 0.55 | 4.6% | 1891 |
| 20 | neu | 1221 / -71 / -938 | 1163 / -996 | 90.6% | 84.8-97.7% | 37.9% | 0.42 | 6.1% | 2157 |
| 20 | neumom | 1216 / -72 / -933 | 1159 / -990 | 90.4% | 84.6-97.6% | 37.9% | 0.43 | 6.4% | 2148 |
| 20 | size | 1233 / -68 / -955 | 1176 / -1013 | 91.1% | 85.2-98.1% | 38.4% | 0.42 | 5.3% | 2186 |
| 20 | none | 1241 / -67 / -964 | 1184 / -1022 | 91.6% | 85.4-98.3% | 38.7% | 0.42 | 4.7% | 2203 |

By regime and by year (h=20, neu, 30/40/30):

| regime at t (N500 vs 200dma, 20d mom) | +1 share | -1 share | P(net>0 | +1) | P(net>0 | 0) | P(net>0 | -1) |
|---|---|---|---|---|---|
| bear_dn20 | 30.0% | 29.9% | 88.1% | 56.8% | 17.4% |
| bear_up20 | 30.0% | 29.9% | 96.2% | 60.2% | 8.6% |
| bull_dn20 | 30.0% | 29.9% | 89.6% | 40.7% | 5.2% |
| bull_up20 | 30.0% | 29.9% | 90.7% | 40.6% | 2.9% |

| year | +1 share | -1 share | P(net>0 | +1) | mean net bps +1 | mean net bps -1 |
|---|---|---|---|---|---|
| 2021 | 30.0% | 29.9% | 95.0% | 1379 | -959 |
| 2022 | 30.1% | 29.9% | 84.8% | 1030 | -1063 |
| 2023 | 30.0% | 29.9% | 97.7% | 1490 | -681 |
| 2024 | 30.0% | 29.9% | 89.9% | 1271 | -972 |
| 2025 | 30.0% | 29.9% | 87.5% | 960 | -1018 |
| 2026 | 30.0% | 29.9% | 91.3% | 1299 | -942 |

### 3c. Composition tilt of the label (+1 minus -1, cross-sectional z) and persistence

| h | neutraliser | beta tilt z (+1 minus -1) | vol_20 tilt | log_turn20 tilt | mom_12_1 tilt | label autocorr lag1 | corr(pct_t, pct_t+h) |
|---|---|---|---|---|---|---|---|
| 10 | neu | -0.046 (up -0.04 / dn -0.06; corr +0.16) | -0.086 (up -0.08 / dn -0.09; corr +0.14) | +0.078 (up +0.08 / dn +0.07; corr -0.02) | +0.047 (up +0.03 / dn +0.06; corr -0.03) | 0.857 | -0.011 |
| 10 | neumom | -0.045 (up -0.04 / dn -0.06; corr +0.15) | -0.086 (up -0.08 / dn -0.09; corr +0.14) | +0.078 (up +0.08 / dn +0.07; corr -0.03) | -0.019 (up -0.02 / dn -0.02; corr -0.01) | 0.857 | -0.011 |
| 10 | size | -0.041 (up +0.12 / dn -0.25; corr +0.67) | -0.110 (up -0.02 / dn -0.22; corr +0.46) | +0.078 (up +0.08 / dn +0.08; corr -0.04) | +0.042 (up +0.06 / dn +0.03; corr +0.19) | 0.857 | -0.016 |
| 10 | none | -0.042 (up +0.12 / dn -0.25; corr +0.66) | -0.111 (up -0.02 / dn -0.22; corr +0.43) | +0.096 (up +0.07 / dn +0.13; corr -0.10) | +0.045 (up +0.05 / dn +0.03; corr +0.17) | 0.858 | -0.014 |
| 20 | neu | -0.045 (up -0.04 / dn -0.06; corr +0.09) | -0.092 (up -0.09 / dn -0.10; corr +0.07) | +0.083 (up +0.08 / dn +0.08; corr +0.03) | +0.067 (up +0.06 / dn +0.08; corr -0.09) | 0.927 | 0.004 |
| 20 | neumom | -0.045 (up -0.04 / dn -0.06; corr +0.06) | -0.093 (up -0.09 / dn -0.10; corr +0.07) | +0.084 (up +0.08 / dn +0.08; corr +0.02) | -0.021 (up -0.02 / dn -0.02; corr -0.08) | 0.926 | 0.006 |
| 20 | size | -0.037 (up +0.09 / dn -0.23; corr +0.60) | -0.111 (up -0.04 / dn -0.22; corr +0.44) | +0.084 (up +0.08 / dn +0.08; corr -0.00) | +0.063 (up +0.07 / dn +0.05; corr +0.09) | 0.927 | -0.001 |
| 20 | none | -0.036 (up +0.09 / dn -0.23; corr +0.60) | -0.112 (up -0.04 / dn -0.22; corr +0.42) | +0.102 (up +0.08 / dn +0.14; corr -0.14) | +0.067 (up +0.07 / dn +0.06; corr +0.06) | 0.927 | 0.001 |


* Without beta/vol neutralisation the label's composition follows the market. In up windows +1 names have
  higher beta (+0.09 z for none/size at h=20); in down windows they have lower beta (-0.23 z). The
  correlation with the window's market return is 0.60-0.67, and the same holds for vol (0.42-0.46). A model
  trained on such a label partly learns market timing. With neu/neumom the beta tilt is -0.04/-0.06 z in
  both states (corr 0.06-0.16) and the vol tilt correlation is 0.07-0.14.
* neu still embeds the realised 12-1 momentum premium: the mom_12_1 tilt is +0.067 z at h=20. neumom
  removes it (-0.021 z).
* Small static tilts remain after OLS (vol -0.09 z, size +0.08 z). Ranking residuals is non-linear:
  high-vol names have right-skewed residuals whose median sits below zero.
* Coherence (3b) shows that a relative +1 is not an absolute winner. P(net>0 | +1) is 89-92% overall but
  84-98% by year. In the worst month it falls to 37.9% (h=20), 46.2% (h=15) and 56.1% (h=10).
  Monthly P(net>0 | +1) correlates 0.42-0.64 with the Nifty month. P(net>0 | -1) is 2.9% in bull_up20
  windows vs 17.4% in bear_dn20 windows. The class is regime-free; its absolute payoff is not. Pair the
  label with a separate regime/exposure layer (R2_regime) if absolute drawdowns matter.


### 3d. Rank-cut sensitivity of the label (neu)

| h | form (neu) | class shares (high->low class) | mean net bps per class | P(net>0) per class | spread top-class minus bottom-class bps |
|---|---|---|---|---|---|
| 10 | C20 | 20.1% / 60.0% / 19.9% | 1035 / -78 / -838 | 94.5% / 42.2% / 2.9% | 1872 |
| 10 | C30 | 30.0% / 40.0% / 29.9% | 794 / -87 / -701 | 88.9% / 41.3% / 5.6% | 1495 |
| 10 | C33 | 33.4% / 33.3% / 33.3% | 732 / -89 / -664 | 86.8% / 41.0% / 6.7% | 1396 |
| 10 | T30 | 30.0% / 70.0% | 794 / -350 | 88.9% / 26.0% | 1143 |
| 10 | B30 | 29.9% / 70.1% | -701 / 291 | 5.6% / 61.7% | -993 |
| 20 | C20 | 20.1% / 60.0% / 19.9% | 1570 / -56 / -1122 | 95.3% / 45.5% / 3.0% | 2689 |
| 20 | C30 | 30.0% / 40.0% / 29.9% | 1221 / -71 / -938 | 90.6% / 44.9% / 6.1% | 2157 |
| 20 | C33 | 33.4% / 33.3% / 33.3% | 1130 / -75 / -887 | 88.7% / 44.7% / 7.5% | 2015 |
| 20 | T30 | 30.0% / 70.0% | 1221 / -442 | 90.6% / 28.3% | 1660 |
| 20 | B30 | 29.9% / 70.1% | -938 / 483 | 6.1% / 64.5% | -1421 |

## 4. Learnability (walk-forward OOS, per-date cross-section)

| model | dev IC own (t) | dev IC vs XR_neu20 (t) | dev IC vs raw r_h (t) | dev AUC top30 (t) | dev AUC bottom30 (t) | 2026 IC own (t) | 2026 IC XR_neu20 | 2026 IC raw | 2026 AUC top30 | 2026 AUC bottom30 | IC own by year 23/24/25/26 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| h10_neu_RANK | 0.069 (9.6) | 0.070 (10.9) | 0.079 (6.4) | 0.517 (3.8) | 0.554 (13.3) | 0.053 (5.1) | 0.050 | 0.047 | 0.497 | 0.558 | 0.046 / 0.090 / 0.069 / 0.053 |
| h15_neu_RANK | 0.065 (7.3) | 0.066 (8.7) | 0.077 (6.0) | 0.519 (3.2) | 0.548 (10.8) | 0.055 (4.8) | 0.054 | 0.049 | 0.502 | 0.556 | 0.034 / 0.088 / 0.073 / 0.055 |
| h20_neu_RANK | 0.060 (6.2) | 0.060 (6.2) | 0.072 (4.3) | 0.517 (2.5) | 0.544 (7.8) | 0.054 (4.4) | 0.054 | 0.047 | 0.503 | 0.553 | 0.023 / 0.088 / 0.070 / 0.054 |
| h20_neumom_RANK | 0.064 (9.3) | 0.063 (8.6) | 0.075 (5.3) | 0.517 (4.0) | 0.548 (11.1) | 0.061 (4.3) | 0.061 | 0.054 | 0.508 | 0.554 | 0.047 / 0.082 / 0.064 / 0.061 |
| h20_size_RANK | 0.060 (4.6) | 0.053 (5.2) | 0.063 (4.4) | 0.520 (3.1) | 0.540 (5.5) | 0.053 (3.5) | 0.050 | 0.047 | 0.496 | 0.559 | 0.026 / 0.098 / 0.055 / 0.053 |
| h20_none_RANK | 0.060 (4.1) | 0.051 (5.4) | 0.060 (4.1) | 0.521 (3.1) | 0.538 (4.7) | 0.043 (2.1) | 0.050 | 0.043 | 0.492 | 0.553 | 0.027 / 0.098 / 0.054 / 0.043 |
| h20_neu_C30 | 0.063 (6.5) | 0.063 (6.5) | 0.075 (4.4) | 0.517 (2.7) | 0.547 (8.7) | 0.063 (5.0) | 0.063 | 0.055 | 0.507 | 0.559 | 0.025 / 0.090 / 0.074 / 0.063 |
| h20_neu_C20 | 0.059 (5.8) | 0.059 (5.8) | 0.066 (4.2) | 0.517 (2.8) | 0.541 (7.3) | 0.062 (4.6) | 0.062 | 0.058 | 0.509 | 0.555 | 0.023 / 0.088 / 0.064 / 0.062 |
| h20_neu_C33 | 0.064 (6.7) | 0.064 (6.7) | 0.078 (4.6) | 0.517 (2.8) | 0.548 (8.9) | 0.060 (4.4) | 0.060 | 0.051 | 0.505 | 0.558 | 0.025 / 0.092 / 0.074 / 0.060 |
| h20_neu_T30 | 0.034 (3.0) | 0.034 (3.0) | 0.029 (1.9) | 0.542 (6.9) | 0.492 (-1.5) | 0.080 (5.6) | 0.080 | 0.094 | 0.564 | 0.516 | 0.022 / 0.062 / 0.018 / 0.080 |
| h20_neu_T20 | 0.016 (1.2) | 0.016 (1.2) | 0.003 (-0.3) | 0.547 (7.8) | 0.468 (-5.3) | 0.062 (3.3) | 0.062 | 0.089 | 0.571 | 0.490 | 0.024 / 0.036 / -0.012 / 0.062 |
| h20_neu_T10 | -0.000 (-0.7) | -0.000 (-0.7) | -0.017 (-1.3) | 0.545 (7.6) | 0.452 (-8.4) | 0.033 (1.7) | 0.033 | 0.064 | 0.563 | 0.468 | 0.014 / 0.017 / -0.031 / 0.033 |
| h20_neu_T50 | 0.066 (6.6) | 0.066 (6.6) | 0.081 (4.3) | 0.518 (2.6) | 0.550 (8.9) | 0.057 (4.3) | 0.057 | 0.047 | 0.503 | 0.557 | 0.029 / 0.092 / 0.077 / 0.057 |
| h20_neumom_T30 | 0.030 (3.2) | 0.039 (3.5) | 0.034 (2.1) | 0.541 (8.4) | 0.490 (-2.1) | 0.060 (4.0) | 0.081 | 0.097 | 0.557 | 0.504 | 0.032 / 0.044 / 0.014 / 0.060 |
| h20_neumom_C20 | 0.060 (8.4) | 0.058 (7.3) | 0.064 (5.0) | 0.517 (3.8) | 0.543 (10.1) | 0.059 (4.2) | 0.060 | 0.059 | 0.509 | 0.551 | 0.046 / 0.078 / 0.057 / 0.059 |
| h20_neu_B30 | 0.060 (7.8) | 0.060 (7.8) | 0.081 (3.7) | 0.488 (-1.6) | 0.572 (17.4) | 0.023 (2.6) | 0.023 | -0.001 | 0.465 | 0.561 | 0.017 / 0.077 / 0.085 / 0.023 |
| h10_neu_T30 | 0.035 (3.6) | 0.042 (5.8) | 0.027 (2.2) | 0.547 (10.0) | 0.490 (-3.1) | 0.054 (4.7) | 0.074 | 0.063 | 0.559 | 0.496 | 0.033 / 0.056 / 0.016 / 0.054 |
| h15_neu_T30 | 0.036 (4.0) | 0.039 (4.5) | 0.030 (2.8) | 0.547 (9.6) | 0.489 (-1.7) | 0.070 (4.6) | 0.079 | 0.083 | 0.562 | 0.510 | 0.030 / 0.058 / 0.019 / 0.070 |
| h10_neu_B30 | 0.063 (10.5) | 0.059 (11.0) | 0.081 (4.8) | 0.486 (-3.5) | 0.579 (22.0) | 0.035 (3.6) | 0.020 | 0.022 | 0.465 | 0.571 | 0.038 / 0.073 / 0.078 / 0.035 |
| h15_neu_B30 | 0.060 (7.7) | 0.059 (8.4) | 0.081 (4.4) | 0.487 (-2.7) | 0.575 (18.2) | 0.029 (3.8) | 0.022 | 0.010 | 0.466 | 0.565 | 0.026 / 0.072 / 0.082 / 0.029 |
| h10_neu_C30 | 0.068 (9.7) | 0.069 (10.9) | 0.079 (6.2) | 0.516 (3.7) | 0.555 (13.1) | 0.057 (4.8) | 0.059 | 0.053 | 0.500 | 0.559 | 0.047 / 0.090 / 0.068 / 0.057 |
| h10_neumom_RANK | 0.071 (12.0) | 0.071 (13.3) | 0.081 (6.7) | 0.516 (4.4) | 0.557 (15.9) | 0.058 (5.7) | 0.057 | 0.054 | 0.501 | 0.559 | 0.057 / 0.086 / 0.070 / 0.058 |
| h10_none_RANK | 0.069 (5.4) | 0.061 (9.5) | 0.069 (5.4) | 0.516 (2.3) | 0.554 (7.9) | 0.046 (2.6) | 0.047 | 0.046 | 0.492 | 0.557 | 0.044 / 0.102 / 0.059 / 0.046 |


* **Learnability is stable and survives 2026.** On the common yardstick (rank IC vs the XR_neu h=20
  residual rank), neutralised (neu/neumom) RANK models have DEV IC 0.060-0.071 and 2026 IC 0.050-0.061. neumom RANK has
  the most reliable DEV IC (0.063, non-overlapping t 8.6; 2026 0.061). 2023 was the weak year
  (0.023-0.047).
* **Asymmetry persists in lab v2.** For RANK models, bottom-30% AUC is 0.538-0.557 on DEV (t 4.7-15.9)
  vs top-30% AUC of 0.516-0.521. In 2026 top-30% AUC is 0.49-0.51, a coin flip, while bottom-30% AUC is
  0.553-0.559. The precision table shows the same pattern. neumom RANK's top-20 picks land in +1
  30.1 / 37.2 / 36.7 / 33.5% of the time (2023/24/25/26, base 30%) and in -1 25.4-29.7%.
* **Binary tail labels learn dispersion, not direction.** T30 has the best top-30% AUC (0.542 DEV, 0.564
  2026) but a low IC (0.034), and its score is +0.31 correlated with vol_20. B30 has the best bottom-30%
  AUC (0.572) and a score -0.73 correlated with idio_vol_60. Its "avoid" list holds high-vol names that
  appear in both tails. That list earned +138 bps vs the universe's +84 bps in 2026, so avoiding it lost
  money. A high tail-class AUC is not a high expected-return rank.


Selection precision of the long book (daily top-20, all dates, overlapping) and of the avoid list:

| model | year | top-20 in +1 (base 30%) | top-20 in -1 (base 30%) | top-20 hit (net>0) | all-names hit | top-20 mean net bps | all mean net bps | bottom-30% in -1 (base 30%) | bottom-30% mean net bps |
|---|---|---|---|---|---|---|---|---|---|
| h20_neumom_RANK | 2023 | 30.1% | 26.7% | 62.2% | 57.6% | 390 | 311 | 34.7% | 292 |
| h20_neumom_RANK | 2024 | 37.2% | 25.4% | 54.3% | 45.6% | 287 | 50 | 35.4% | -43 |
| h20_neumom_RANK | 2025 | 36.7% | 29.7% | 46.8% | 42.5% | -6 | -84 | 34.6% | -167 |
| h20_neumom_RANK | 2026 | 33.5% | 26.9% | 50.8% | 46.6% | 121 | 84 | 35.3% | 59 |
| h20_neumom_C20 | 2023 | 33.5% | 29.1% | 60.4% | 57.6% | 425 | 311 | 34.6% | 307 |
| h20_neumom_C20 | 2024 | 38.5% | 26.5% | 54.0% | 45.6% | 308 | 50 | 35.4% | -45 |
| h20_neumom_C20 | 2025 | 36.5% | 29.5% | 46.2% | 42.5% | 8 | -84 | 34.5% | -155 |
| h20_neumom_C20 | 2026 | 34.5% | 25.5% | 52.0% | 46.6% | 164 | 84 | 35.2% | 64 |
| h20_neumom_T30 | 2023 | 36.9% | 30.5% | 60.5% | 57.6% | 469 | 311 | 30.8% | 236 |
| h20_neumom_T30 | 2024 | 39.2% | 29.4% | 52.9% | 45.6% | 252 | 50 | 30.0% | -48 |
| h20_neumom_T30 | 2025 | 38.0% | 30.6% | 46.7% | 42.5% | 38 | -84 | 28.6% | -96 |
| h20_neumom_T30 | 2026 | 38.4% | 29.8% | 54.1% | 46.6% | 186 | 84 | 31.2% | -43 |
| h20_neu_RANK | 2023 | 29.9% | 27.8% | 60.8% | 57.6% | 382 | 311 | 33.9% | 320 |
| h20_neu_RANK | 2024 | 38.4% | 27.1% | 53.7% | 45.6% | 245 | 50 | 35.1% | -52 |
| h20_neu_RANK | 2025 | 37.9% | 29.2% | 48.6% | 42.5% | 32 | -84 | 34.7% | -175 |
| h20_neu_RANK | 2026 | 34.4% | 26.3% | 51.4% | 46.6% | 116 | 84 | 35.2% | 71 |
| h20_neu_T30 | 2023 | 36.5% | 30.3% | 60.8% | 57.6% | 450 | 311 | 29.9% | 256 |
| h20_neu_T30 | 2024 | 39.6% | 29.0% | 53.0% | 45.6% | 256 | 50 | 30.3% | -53 |
| h20_neu_T30 | 2025 | 38.7% | 32.3% | 47.3% | 42.5% | 44 | -84 | 28.4% | -100 |
| h20_neu_T30 | 2026 | 38.8% | 30.1% | 54.0% | 46.6% | 218 | 84 | 31.4% | -39 |
| h20_neu_B30 | 2023 | 20.5% | 17.8% | 62.0% | 57.6% | 189 | 311 | 34.6% | 365 |
| h20_neu_B30 | 2024 | 26.5% | 20.4% | 50.2% | 45.6% | 19 | 50 | 36.8% | -5 |
| h20_neu_B30 | 2025 | 29.2% | 13.9% | 53.2% | 42.5% | 112 | -84 | 36.7% | -188 |
| h20_neu_B30 | 2026 | 21.8% | 17.5% | 45.5% | 46.6% | -37 | 84 | 35.6% | 138 |
| h20_none_RANK | 2023 | 29.6% | 29.2% | 60.5% | 57.6% | 345 | 311 | 32.8% | 294 |
| h20_none_RANK | 2024 | 36.2% | 25.5% | 51.6% | 45.6% | 197 | 50 | 34.0% | -70 |
| h20_none_RANK | 2025 | 38.7% | 28.2% | 49.1% | 42.5% | 56 | -84 | 33.3% | -132 |
| h20_none_RANK | 2026 | 26.6% | 23.0% | 46.5% | 46.6% | 27 | 84 | 35.2% | 73 |
| h10_neu_RANK | 2023 | 31.9% | 24.5% | 56.4% | 51.2% | 157 | 109 | 35.0% | 103 |
| h10_neu_RANK | 2024 | 40.5% | 24.1% | 53.1% | 44.6% | 172 | 1 | 35.7% | -62 |
| h10_neu_RANK | 2025 | 36.9% | 28.8% | 46.7% | 41.8% | -10 | -71 | 35.0% | -123 |
| h10_neu_RANK | 2026 | 33.5% | 27.0% | 46.6% | 43.0% | 22 | -13 | 35.9% | -25 |

## 5. Investability headline (long top-20, step 5, liq2, S.compare vs horizon-matched random)

| model (K20, step 5, liq2) | dev CAGR 50bp | dev random | dev excess | dev NW t | dev phase-avg excess/yr (t) | dev maxDD | dev CAGR 80bp | 2026 CAGR 50bp | 2026 random | 2026 excess | 2026 NW t | 2026 phase-avg excess/yr (t) | 2026 CAGR 80bp |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| h10_neu_RANK | 25.1% | 1.2% | +23.9% | 4.36 | +23.8% (4.79) | -27.9% | 16.2% | 8.2% | -4.0% | +12.2% | 1.13 | +8.6% (0.99) | 0.6% |
| h15_neu_RANK | 25.6% | 8.5% | +17.1% | 3.20 | +17.8% (4.04) | -29.0% | 19.6% | 7.5% | 2.0% | +5.4% | 0.60 | +7.8% (0.84) | 2.5% |
| h20_neu_RANK | 29.8% | 11.8% | +18.0% | 3.75 | +15.2% (3.81) | -29.4% | 25.2% | 10.1% | 6.9% | +3.2% | 0.49 | +3.3% (0.44) | 6.4% |
| h20_neumom_RANK | 30.9% | 11.8% | +19.1% | 4.25 | +15.8% (4.11) | -25.6% | 26.2% | 16.0% | 6.9% | +9.2% | 1.54 | +3.9% (0.60) | 12.1% |
| h20_size_RANK | 22.6% | 11.8% | +10.8% | 2.65 | +12.7% (2.90) | -31.4% | 18.2% | 5.2% | 6.9% | -1.6% | -0.12 | -1.8% (-0.19) | 1.7% |
| h20_none_RANK | 25.2% | 11.8% | +13.4% | 2.85 | +13.8% (3.27) | -33.1% | 20.7% | 3.9% | 6.9% | -3.0% | -0.33 | -7.7% (-0.91) | 0.4% |
| h20_neu_C30 | 24.7% | 11.8% | +12.9% | 2.57 | +14.7% (3.61) | -28.1% | 20.3% | 12.6% | 6.9% | +5.8% | 0.84 | +1.0% (0.13) | 8.9% |
| h20_neu_C20 | 30.7% | 11.8% | +18.9% | 3.86 | +18.1% (4.87) | -28.3% | 26.0% | 19.0% | 6.9% | +12.2% | 1.87 | +10.2% (1.66) | 15.0% |
| h20_neu_C33 | 26.0% | 11.8% | +14.2% | 2.97 | +13.6% (3.30) | -27.5% | 21.5% | 10.0% | 6.9% | +3.2% | 0.44 | -0.4% (-0.05) | 6.3% |
| h20_neu_T30 | 29.9% | 11.8% | +18.1% | 3.30 | +19.4% (4.26) | -32.8% | 25.2% | 27.9% | 6.9% | +21.0% | 3.17 | +14.9% (2.45) | 23.6% |
| h20_neu_T20 | 28.3% | 11.8% | +16.5% | 2.68 | +17.1% (3.39) | -34.4% | 23.7% | 29.8% | 6.9% | +22.9% | 1.97 | +15.9% (1.79) | 25.4% |
| h20_neu_T10 | 27.9% | 11.8% | +16.1% | 2.56 | +17.8% (3.01) | -35.3% | 23.3% | 32.5% | 6.9% | +25.6% | 1.79 | +17.8% (1.52) | 28.0% |
| h20_neu_T50 | 15.9% | 11.8% | +4.1% | 0.67 | +5.9% (1.23) | -28.2% | 11.7% | 2.1% | 6.9% | -4.8% | -0.56 | -7.1% (-0.82) | -1.4% |
| h20_neumom_T30 | 30.8% | 11.8% | +19.0% | 3.82 | +19.6% (4.57) | -29.6% | 26.1% | 21.8% | 6.9% | +15.0% | 2.16 | +11.6% (2.14) | 17.7% |
| h20_neumom_C20 | 30.1% | 11.8% | +18.3% | 3.69 | +18.5% (5.07) | -28.2% | 25.4% | 22.2% | 6.9% | +15.4% | 1.97 | +8.9% (1.32) | 18.1% |
| h20_neu_B30 | 13.5% | 11.8% | +1.7% | 0.06 | +0.7% (0.09) | -20.4% | 9.4% | -4.5% | 6.9% | -11.3% | -1.15 | -15.2% (-1.66) | -7.7% |
| h10_neu_T30 | 30.0% | 1.2% | +28.8% | 4.46 | +25.1% (4.75) | -33.9% | 20.8% | 17.2% | -4.0% | +21.3% | 2.19 | +20.1% (2.26) | 9.0% |
| h15_neu_T30 | 29.9% | 8.5% | +21.4% | 3.73 | +21.2% (4.62) | -32.2% | 23.7% | 3.7% | 2.0% | +1.7% | 0.29 | +6.0% (0.83) | -1.1% |
| h10_neu_B30 | 6.1% | 1.2% | +4.9% | 0.46 | +2.9% (0.39) | -21.5% | -1.5% | -18.7% | -4.0% | -14.7% | -1.46 | -14.4% (-1.35) | -24.4% |
| h15_neu_B30 | 10.9% | 8.5% | +2.4% | 0.14 | +0.8% (0.10) | -19.2% | 5.6% | -11.1% | 2.0% | -13.2% | -1.39 | -16.1% (-1.76) | -15.2% |
| h10_neu_C30 | 27.7% | 1.2% | +26.5% | 4.48 | +23.3% (4.68) | -28.3% | 18.6% | -0.4% | -4.0% | +3.7% | 0.38 | +8.9% (0.98) | -7.3% |
| h10_neumom_RANK | 19.3% | 1.2% | +18.1% | 3.43 | +21.9% (4.90) | -27.9% | 10.7% | 3.6% | -4.0% | +7.7% | 0.86 | +8.6% (1.12) | -3.6% |
| h10_none_RANK | 19.2% | 1.2% | +18.0% | 3.14 | +18.0% (3.70) | -33.4% | 10.6% | 4.0% | -4.0% | +8.0% | 0.78 | +0.7% (0.07) | -3.3% |

By year (strategy vs 5-seed random, same mask; Nifty 500: 2023 +25.2%, 2024 +14.9%, 2025 +6.2%, 2026 YTD -7.8%):

| model (K20 s5 50bp) | 2023 strat vs random (diff) | 2024 | 2025 | 2026 YTD (holdout) |
|---|---|---|---|---|
| h10_neu_RANK | 45.0% vs 18.9% (+26.1%) | 42.9% vs 0.9% (+42.0%) | -7.8% vs -14.8% (+7.0%) | 6.2% vs -3.1% (+9.3%) |
| h15_neu_RANK | 49.6% vs 30.0% (+19.6%) | 41.5% vs 8.7% (+32.8%) | -8.5% vs -11.2% (+2.6%) | 5.7% vs 1.6% (+4.2%) |
| h20_neu_RANK | 55.1% vs 35.3% (+19.8%) | 40.7% vs 12.9% (+27.8%) | -2.3% vs -10.4% (+8.1%) | 7.7% vs 5.2% (+2.4%) |
| h20_neumom_RANK | 53.6% vs 35.3% (+18.3%) | 48.7% vs 12.9% (+35.8%) | -4.5% vs -10.4% (+5.9%) | 12.1% vs 5.2% (+6.9%) |
| h20_size_RANK | 43.4% vs 35.3% (+8.0%) | 24.6% vs 12.9% (+11.7%) | 0.9% vs -10.4% (+11.3%) | 4.0% vs 5.2% (-1.2%) |
| h20_none_RANK | 43.2% vs 35.3% (+7.8%) | 30.6% vs 12.9% (+17.6%) | 2.7% vs -10.4% (+13.1%) | 3.0% vs 5.2% (-2.3%) |
| h20_neu_C30 | 46.6% vs 35.3% (+11.3%) | 26.3% vs 12.9% (+13.4%) | 2.7% vs -10.4% (+13.1%) | 9.6% vs 5.2% (+4.4%) |
| h20_neu_C20 | 61.1% vs 35.3% (+25.7%) | 41.8% vs 12.9% (+28.9%) | -5.4% vs -10.4% (+5.0%) | 14.3% vs 5.2% (+9.1%) |
| h20_neu_C33 | 49.6% vs 35.3% (+14.2%) | 28.6% vs 12.9% (+15.7%) | 2.2% vs -10.4% (+12.6%) | 7.6% vs 5.2% (+2.4%) |
| h20_neu_T30 | 59.8% vs 35.3% (+24.4%) | 34.6% vs 12.9% (+21.7%) | -1.7% vs -10.4% (+8.7%) | 20.8% vs 5.2% (+15.6%) |
| h20_neu_T20 | 55.4% vs 35.3% (+20.1%) | 47.0% vs 12.9% (+34.1%) | -10.7% vs -10.4% (-0.3%) | 22.2% vs 5.2% (+17.0%) |
| h20_neu_T10 | 46.4% vs 35.3% (+11.1%) | 48.8% vs 12.9% (+35.9%) | -6.6% vs -10.4% (+3.8%) | 24.2% vs 5.2% (+18.9%) |
| h20_neu_T50 | 32.4% vs 35.3% (-3.0%) | 19.1% vs 12.9% (+6.1%) | -2.0% vs -10.4% (+8.4%) | 1.6% vs 5.2% (-3.6%) |
| h20_neumom_T30 | 60.0% vs 35.3% (+24.7%) | 37.3% vs 12.9% (+24.4%) | -1.6% vs -10.4% (+8.8%) | 16.4% vs 5.2% (+11.2%) |
| h20_neumom_C20 | 63.6% vs 35.3% (+28.3%) | 39.6% vs 12.9% (+26.7%) | -7.0% vs -10.4% (+3.4%) | 16.7% vs 5.2% (+11.5%) |
| h20_neu_B30 | 24.7% vs 35.3% (-10.6%) | 2.6% vs 12.9% (-10.3%) | 13.6% vs -10.4% (+24.0%) | -3.5% vs 5.2% (-8.7%) |
| h10_neu_T30 | 54.9% vs 18.9% (+36.0%) | 44.7% vs 0.9% (+43.7%) | -5.2% vs -14.8% (+9.7%) | 13.0% vs -3.1% (+16.1%) |
| h15_neu_T30 | 48.5% vs 30.0% (+18.4%) | 37.9% vs 8.7% (+29.2%) | 2.8% vs -11.2% (+13.9%) | 2.8% vs 1.6% (+1.3%) |
| h10_neu_B30 | 16.3% vs 18.9% (-2.5%) | -2.7% vs 0.9% (-3.6%) | 5.3% vs -14.8% (+20.1%) | -14.7% vs -3.1% (-11.6%) |
| h15_neu_B30 | 21.0% vs 30.0% (-9.1%) | 2.1% vs 8.7% (-6.6%) | 10.0% vs -11.2% (+21.1%) | -8.7% vs 1.6% (-10.2%) |
| h10_neu_C30 | 44.8% vs 18.9% (+26.0%) | 52.1% vs 0.9% (+51.2%) | -7.5% vs -14.8% (+7.3%) | -0.3% vs -3.1% (+2.8%) |
| h10_neumom_RANK | 38.9% vs 18.9% (+20.0%) | 33.8% vs 0.9% (+32.9%) | -10.5% vs -14.8% (+4.3%) | 2.8% vs -3.1% (+5.9%) |
| h10_none_RANK | 32.7% vs 18.9% (+13.8%) | 29.4% vs 0.9% (+28.5%) | -3.7% vs -14.8% (+11.1%) | 3.1% vs -3.1% (+6.2%) |


* All neutralised RANK, 3-class and T30 models beat the horizon-matched random by +12.9..+19.1%/yr on DEV
  (K20, step 5, 50 bps; NW t 2.6-4.3), with every DEV year positive. The h=20 random baseline itself
  earned 11.8% on DEV, so it is the bar to beat, not zero.
* The DEV maxDD of the top books (-25.6..-32.8%) is similar to random (about -30%). A relative label
  improves returns, not absolute drawdowns.
* In 2026 the neutral RANK books were weakest (+3.3..+3.9% phase-averaged). The vol-loaded tail books
  were strongest (+8.9..+14.9%). none/size were negative (-7.7 / -1.8%), which reproduces the round-1
  finding that raw-return ranks lost their edge in 2026.
* Using B30 as a long score is worthless: +0.7% phase-averaged DEV excess, -15.2% in 2026.


## 6. Parameter-sensitivity map

### 6a. Horizon x cost (neu RANK models, K=20)

| model | cost bps | step | dev CAGR | dev random | dev excess | dev t | dev mean trade net | 2026 CAGR | 2026 random | 2026 excess | 2026 t |
|---|---|---|---|---|---|---|---|---|---|---|---|
| h10_neu_RANK | 50 | 5 | 25.1% | 1.2% | +23.9% | 4.36 | 1.02% | 8.2% | -4.0% | +12.2% | 1.13 |
| h10_neu_RANK | 50 | 10 | 23.9% | 5.8% | +18.1% | 2.59 | 1.01% | 28.4% | -2.6% | +31.0% | 2.54 |
| h10_neu_RANK | 80 | 5 | 16.2% | -6.0% | +22.2% | 4.36 | 0.72% | 0.6% | -10.7% | +11.3% | 1.13 |
| h10_neu_RANK | 80 | 10 | 15.0% | -1.8% | +16.8% | 2.59 | 0.71% | 19.2% | -9.6% | +28.8% | 2.54 |
| h10_neu_RANK | 130 | 5 | 2.6% | -17.0% | +19.6% | 4.36 | 0.22% | -10.9% | -20.9% | +10.0% | 1.12 |
| h10_neu_RANK | 130 | 10 | 1.5% | -13.3% | +14.8% | 2.59 | 0.21% | 5.3% | -20.1% | +25.4% | 2.54 |
| h15_neu_RANK | 50 | 5 | 25.6% | 8.5% | +17.1% | 3.20 | 1.56% | 7.5% | 2.0% | +5.4% | 0.60 |
| h15_neu_RANK | 50 | 10 | 19.6% | 12.3% | +7.3% | 1.56 | 1.63% | 3.9% | -2.0% | +5.9% | 0.72 |
| h15_neu_RANK | 80 | 5 | 19.6% | 3.3% | +16.2% | 3.20 | 1.26% | 2.5% | -2.6% | +5.2% | 0.60 |
| h15_neu_RANK | 80 | 10 | 15.3% | 8.2% | +7.0% | 1.56 | 1.33% | 0.3% | -5.4% | +5.7% | 0.72 |
| h15_neu_RANK | 130 | 5 | 10.2% | -4.8% | +15.0% | 3.20 | 0.76% | -5.2% | -10.0% | +4.8% | 0.60 |
| h15_neu_RANK | 130 | 10 | 8.4% | 1.8% | +6.6% | 1.57 | 0.83% | -5.4% | -10.8% | +5.4% | 0.71 |
| h20_neu_RANK | 50 | 5 | 29.8% | 11.8% | +18.0% | 3.75 | 2.37% | 10.1% | 6.9% | +3.2% | 0.49 |
| h20_neu_RANK | 50 | 10 | 27.3% | 13.5% | +13.8% | 2.42 | 2.21% | 22.9% | 7.4% | +15.4% | 1.56 |
| h20_neu_RANK | 80 | 5 | 25.2% | 7.8% | +17.4% | 3.75 | 2.07% | 6.4% | 3.3% | +3.1% | 0.48 |
| h20_neu_RANK | 80 | 10 | 22.7% | 9.4% | +13.3% | 2.42 | 1.91% | 18.6% | 3.7% | +14.9% | 1.56 |
| h20_neu_RANK | 130 | 5 | 17.7% | 1.4% | +16.4% | 3.75 | 1.57% | 0.5% | -2.5% | +2.9% | 0.48 |
| h20_neu_RANK | 130 | 10 | 15.4% | 2.9% | +12.5% | 2.42 | 1.41% | 11.8% | -2.2% | +14.1% | 1.56 |

### 6b. Training horizon vs holding horizon (neu RANK scores, K20 step 5, 50 bps)

| score \ held for | h=10: dev CAGR / excess (t) / 2026 excess | h=15 | h=20 |
|---|---|---|---|
| trained h=10 | 25.1% / +23.9% (t 4.36) | 2026 +12.2% (t 1.13) | 27.1% / +18.6% (t 3.53) | 2026 +11.7% (t 1.40) | 29.9% / +18.1% (t 4.02) | 2026 +5.4% (t 0.88) |
| trained h=15 | 21.5% / +20.3% (t 3.53) | 2026 +9.8% (t 0.80) | 25.6% / +17.1% (t 3.20) | 2026 +5.4% (t 0.60) | 26.9% / +15.1% (t 3.29) | 2026 +4.4% (t 0.61) |
| trained h=20 | 21.0% / +19.7% (t 3.62) | 2026 +4.3% (t 0.42) | 26.9% / +18.4% (t 3.55) | 2026 +5.7% (t 0.71) | 29.8% / +18.0% (t 3.75) | 2026 +3.2% (t 0.49) |

### 6c. K x step map: `h20_neumom_RANK` (liq2, 50 bps; dev CAGR 80bp column = cost stress)

| K | step | dev CAGR | dev excess | dev t | dev maxDD | dev hit | dev CAGR 80bp | 2026 CAGR | 2026 excess | 2026 t |
|---|---|---|---|---|---|---|---|---|---|---|
| 10 | 5 | 39.9% | +32.1% | 4.95 | -26.6% | 55.8% | 34.8% | 20.2% | +11.3% | 1.20 |
| 10 | 10 | 35.2% | +27.8% | 4.05 | -25.8% | 55.6% | 30.3% | 32.6% | +25.1% | 2.06 |
| 20 | 5 | 30.9% | +19.1% | 4.25 | -25.6% | 54.8% | 26.2% | 16.0% | +9.2% | 1.54 |
| 20 | 10 | 30.7% | +17.2% | 3.28 | -24.5% | 55.5% | 26.0% | 26.5% | +19.0% | 2.41 |
| 30 | 5 | 27.9% | +16.9% | 4.18 | -24.7% | 54.2% | 23.3% | 9.8% | +3.7% | 0.76 |
| 30 | 10 | 26.4% | +14.6% | 3.32 | -25.5% | 54.3% | 21.8% | 16.8% | +10.6% | 1.69 |
| 50 | 5 | 22.6% | +11.9% | 3.66 | -26.9% | 53.5% | 18.2% | 9.8% | +4.8% | 1.07 |
| 50 | 10 | 23.1% | +11.3% | 3.48 | -26.5% | 53.6% | 18.7% | 16.8% | +9.5% | 1.64 |

### 6c. K x step map: `h20_neumom_C20` (liq2, 50 bps; dev CAGR 80bp column = cost stress)

| K | step | dev CAGR | dev excess | dev t | dev maxDD | dev hit | dev CAGR 80bp | 2026 CAGR | 2026 excess | 2026 t |
|---|---|---|---|---|---|---|---|---|---|---|
| 10 | 5 | 32.5% | +24.7% | 4.03 | -25.9% | 54.0% | 27.7% | 22.7% | +13.8% | 1.91 |
| 10 | 10 | 24.9% | +17.5% | 2.59 | -25.4% | 52.5% | 20.4% | 36.4% | +28.9% | 3.10 |
| 20 | 5 | 30.1% | +18.3% | 3.69 | -28.2% | 54.0% | 25.4% | 22.2% | +15.4% | 1.97 |
| 20 | 10 | 27.0% | +13.6% | 2.41 | -27.1% | 54.1% | 22.5% | 35.1% | +27.7% | 3.42 |
| 30 | 5 | 26.0% | +15.0% | 4.04 | -28.3% | 53.1% | 21.5% | 21.6% | +15.6% | 1.88 |
| 30 | 10 | 24.0% | +12.2% | 2.73 | -27.9% | 52.8% | 19.5% | 28.0% | +21.8% | 3.58 |
| 50 | 5 | 25.0% | +14.3% | 4.32 | -27.6% | 52.7% | 20.5% | 19.3% | +14.2% | 2.30 |
| 50 | 10 | 25.5% | +13.6% | 4.04 | -25.9% | 52.9% | 20.9% | 25.2% | +17.8% | 3.20 |

### 6c. K x step map: `h20_neumom_T30` (liq2, 50 bps; dev CAGR 80bp column = cost stress)

| K | step | dev CAGR | dev excess | dev t | dev maxDD | dev hit | dev CAGR 80bp | 2026 CAGR | 2026 excess | 2026 t |
|---|---|---|---|---|---|---|---|---|---|---|
| 10 | 5 | 36.7% | +28.9% | 4.81 | -30.1% | 54.2% | 31.8% | 8.9% | -0.1% | 0.08 |
| 10 | 10 | 32.3% | +24.9% | 3.90 | -27.6% | 53.9% | 27.5% | 15.5% | +8.0% | 0.74 |
| 20 | 5 | 30.8% | +19.0% | 3.82 | -29.6% | 53.3% | 26.1% | 21.8% | +15.0% | 2.16 |
| 20 | 10 | 29.3% | +15.8% | 3.11 | -26.5% | 54.0% | 24.6% | 26.0% | +18.5% | 1.75 |
| 30 | 5 | 28.8% | +17.8% | 3.40 | -30.3% | 53.1% | 24.2% | 20.3% | +14.2% | 2.18 |
| 30 | 10 | 27.3% | +15.5% | 2.93 | -28.0% | 53.0% | 22.7% | 22.0% | +15.8% | 1.84 |
| 50 | 5 | 27.8% | +17.1% | 3.93 | -29.3% | 52.6% | 23.2% | 23.0% | +17.9% | 2.60 |
| 50 | 10 | 26.7% | +14.9% | 3.60 | -27.1% | 52.5% | 22.1% | 28.1% | +20.7% | 3.13 |

### 6c. K x step map: `h20_neu_RANK` (liq2, 50 bps; dev CAGR 80bp column = cost stress)

| K | step | dev CAGR | dev excess | dev t | dev maxDD | dev hit | dev CAGR 80bp | 2026 CAGR | 2026 excess | 2026 t |
|---|---|---|---|---|---|---|---|---|---|---|
| 10 | 5 | 29.8% | +22.0% | 3.50 | -31.6% | 55.6% | 25.1% | 16.4% | +7.5% | 0.70 |
| 10 | 10 | 24.9% | +17.5% | 2.82 | -32.6% | 55.3% | 20.4% | 27.7% | +20.1% | 1.26 |
| 20 | 5 | 29.8% | +18.0% | 3.75 | -29.4% | 55.1% | 25.2% | 10.1% | +3.2% | 0.49 |
| 20 | 10 | 27.3% | +13.8% | 2.42 | -30.6% | 55.5% | 22.7% | 22.9% | +15.4% | 1.56 |
| 30 | 5 | 27.6% | +16.6% | 3.85 | -28.1% | 54.7% | 23.0% | 10.2% | +4.1% | 0.63 |
| 30 | 10 | 25.6% | +13.8% | 2.69 | -27.9% | 54.7% | 21.0% | 20.8% | +14.6% | 1.57 |
| 50 | 5 | 24.3% | +13.7% | 3.52 | -27.9% | 54.0% | 19.9% | 10.7% | +5.6% | 1.14 |
| 50 | 10 | 24.2% | +12.4% | 3.16 | -27.9% | 53.9% | 19.7% | 16.9% | +9.6% | 1.68 |

### 6d. Liquidity tier (liq2 = Rs2cr 20d turnover, liq5 = Rs5cr; model trained on liq2)

| model (K20 s5 50bp) | liq2 dev excess | liq2 dev t | liq5 dev CAGR | liq5 dev random | liq5 dev excess | liq5 dev t | liq2 2026 excess | liq5 2026 excess | liq5 2026 t |
|---|---|---|---|---|---|---|---|---|---|
| h10_neu_RANK | +23.9% | 4.36 | 23.1% | 2.0% | +21.1% | 3.65 | +12.2% | +4.2% | 0.41 |
| h15_neu_RANK | +17.1% | 3.20 | 22.4% | 8.3% | +14.2% | 3.03 | +5.4% | +1.8% | 0.22 |
| h20_neu_RANK | +18.0% | 3.75 | 25.6% | 11.8% | +13.9% | 3.10 | +3.2% | +5.0% | 0.63 |
| h20_neumom_RANK | +19.1% | 4.25 | 26.1% | 11.8% | +14.3% | 3.28 | +9.2% | +4.6% | 0.71 |
| h20_size_RANK | +10.8% | 2.65 | 18.6% | 11.8% | +6.9% | 1.70 | -1.6% | -1.4% | -0.10 |
| h20_none_RANK | +13.4% | 2.85 | 23.2% | 11.8% | +11.4% | 2.31 | -3.0% | -2.4% | -0.22 |
| h20_neu_C30 | +12.9% | 2.57 | 21.7% | 11.8% | +9.9% | 2.12 | +5.8% | +3.9% | 0.54 |
| h20_neu_C20 | +18.9% | 3.86 | 23.1% | 11.8% | +11.3% | 2.50 | +12.2% | +15.5% | 2.18 |
| h20_neu_C33 | +14.2% | 2.97 | 21.5% | 11.8% | +9.8% | 2.14 | +3.2% | +2.0% | 0.26 |
| h20_neu_T30 | +18.1% | 3.30 | 24.3% | 11.8% | +12.5% | 2.70 | +21.0% | +16.7% | 2.47 |
| h20_neu_T20 | +16.5% | 2.68 | 25.6% | 11.8% | +13.8% | 2.32 | +22.9% | +16.2% | 1.48 |
| h20_neu_T10 | +16.1% | 2.56 | 23.4% | 11.8% | +11.6% | 2.00 | +25.6% | +26.0% | 1.51 |
| h20_neu_T50 | +4.1% | 0.67 | 15.0% | 11.8% | +3.3% | 0.54 | -4.8% | -4.4% | -0.52 |
| h20_neumom_T30 | +19.0% | 3.82 | 27.3% | 11.8% | +15.5% | 3.01 | +15.0% | +12.2% | 1.72 |
| h20_neumom_C20 | +18.3% | 3.69 | 22.0% | 11.8% | +10.3% | 2.60 | +15.4% | +11.1% | 1.26 |
| h20_neu_B30 | +1.7% | 0.06 | 13.2% | 11.8% | +1.4% | 0.04 | -11.3% | -10.0% | -1.15 |
| h10_neu_T30 | +28.8% | 4.46 | 27.0% | 2.0% | +25.0% | 3.81 | +21.3% | +14.5% | 1.63 |
| h15_neu_T30 | +21.4% | 3.73 | 26.5% | 8.3% | +18.2% | 3.53 | +1.7% | +4.3% | 0.58 |
| h10_neu_B30 | +4.9% | 0.46 | 6.3% | 2.0% | +4.3% | 0.42 | -14.7% | -13.5% | -1.53 |
| h15_neu_B30 | +2.4% | 0.14 | 10.6% | 8.3% | +2.3% | 0.15 | -13.2% | -13.1% | -1.55 |
| h10_neu_C30 | +26.5% | 4.48 | 23.8% | 2.0% | +21.8% | 3.76 | +3.7% | -1.1% | -0.09 |
| h10_neumom_RANK | +18.1% | 3.43 | 16.6% | 2.0% | +14.6% | 2.96 | +7.7% | +0.4% | 0.07 |
| h10_none_RANK | +18.0% | 3.14 | 18.9% | 2.0% | +16.9% | 3.14 | +8.0% | +3.5% | 0.36 |

### 6e. AVOID overlay (EW all names except the model's bottom 30%)

| model: EW all minus model bottom 30% (step 5, 50bp) | dev CAGR | dev random-70% | dev universe EW | dev excess vs random | t vs random | t vs EW | dev phase-avg (t) | dev maxDD | EW maxDD | 2026 CAGR | 2026 EW | 2026 excess | 2026 t | 2026 phase-avg (t) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| h10_neu_RANK | 6.6% | 1.9% | 2.1% | +4.7% | 4.48 | 4.30 | +4.4% (4.47) | -29.7% | -32.2% | -5.3% | -7.0% | +1.4% | 0.63 | +1.3% (0.62) |
| h15_neu_RANK | 12.2% | 8.1% | 8.1% | +4.1% | 3.46 | 3.41 | +3.7% (3.57) | -28.0% | -30.3% | 2.6% | 0.6% | +1.7% | 0.83 | +0.9% (0.55) |
| h20_neu_RANK | 14.7% | 11.2% | 11.2% | +3.4% | 2.77 | 2.74 | +3.1% (2.99) | -27.3% | -29.4% | 7.4% | 6.4% | +0.9% | 0.45 | +0.6% (0.38) |
| h20_neumom_RANK | 15.1% | 11.2% | 11.2% | +3.8% | 3.40 | 3.37 | +3.4% (3.58) | -27.2% | -29.4% | 8.2% | 6.4% | +1.8% | 1.02 | +1.2% (0.84) |
| h20_size_RANK | 14.6% | 11.2% | 11.2% | +3.4% | 3.34 | 3.26 | +3.2% (3.51) | -28.5% | -29.4% | 7.7% | 6.4% | +1.3% | 0.74 | +0.7% (0.49) |
| h20_none_RANK | 14.6% | 11.2% | 11.2% | +3.3% | 3.45 | 3.37 | +3.3% (3.65) | -28.5% | -29.4% | 7.5% | 6.4% | +1.0% | 0.49 | +0.5% (0.31) |
| h20_neu_C30 | 14.8% | 11.2% | 11.2% | +3.5% | 2.70 | 2.67 | +3.2% (2.95) | -27.0% | -29.4% | 7.6% | 6.4% | +1.1% | 0.53 | +1.0% (0.57) |
| h20_neu_C20 | 14.5% | 11.2% | 11.2% | +3.3% | 2.65 | 2.62 | +2.9% (2.75) | -27.3% | -29.4% | 7.6% | 6.4% | +1.1% | 0.56 | +0.8% (0.52) |
| h20_neu_C33 | 15.1% | 11.2% | 11.2% | +3.8% | 2.98 | 2.96 | +3.3% (3.12) | -27.0% | -29.4% | 7.7% | 6.4% | +1.2% | 0.63 | +0.8% (0.50) |
| h20_neu_T30 | 14.4% | 11.2% | 11.2% | +3.1% | 4.15 | 4.09 | +3.1% (4.49) | -28.9% | -29.4% | 12.6% | 6.4% | +6.1% | 5.18 | +6.1% (5.93) |
| h20_neu_T20 | 13.8% | 11.2% | 11.2% | +2.6% | 2.51 | 2.49 | +2.7% (2.67) | -30.1% | -29.4% | 13.7% | 6.4% | +7.2% | 3.75 | +7.2% (4.02) |
| h20_neu_T10 | 13.2% | 11.2% | 11.2% | +2.0% | 1.56 | 1.56 | +2.2% (1.54) | -31.0% | -29.4% | 12.9% | 6.4% | +6.5% | 2.49 | +6.7% (2.72) |
| h20_neu_T50 | 15.6% | 11.2% | 11.2% | +4.3% | 3.41 | 3.38 | +3.7% (3.45) | -27.0% | -29.4% | 7.5% | 6.4% | +1.0% | 0.43 | +0.8% (0.43) |
| h20_neumom_T30 | 14.7% | 11.2% | 11.2% | +3.5% | 4.58 | 4.55 | +3.4% (4.87) | -28.8% | -29.4% | 12.7% | 6.4% | +6.3% | 5.69 | +6.3% (6.20) |
| h20_neumom_C20 | 14.5% | 11.2% | 11.2% | +3.3% | 3.00 | 2.97 | +3.0% (3.23) | -27.3% | -29.4% | 7.7% | 6.4% | +1.2% | 0.82 | +1.0% (0.75) |
| h20_neu_B30 | 13.4% | 11.2% | 11.2% | +2.2% | 1.26 | 1.26 | +1.7% (1.28) | -26.9% | -29.4% | 4.5% | 6.4% | -2.0% | -1.04 | -2.7% (-1.27) |
| h10_neu_T30 | 5.8% | 1.9% | 2.1% | +3.9% | 4.88 | 4.71 | +4.1% (5.24) | -31.9% | -32.2% | -1.0% | -7.0% | +5.8% | 4.23 | +7.0% (5.04) |
| h15_neu_T30 | 11.8% | 8.1% | 8.1% | +3.7% | 4.82 | 4.83 | +3.6% (4.91) | -29.8% | -30.3% | 6.8% | 0.6% | +5.8% | 4.94 | +6.5% (5.93) |
| h10_neu_B30 | 5.0% | 1.9% | 2.1% | +3.1% | 2.21 | 2.06 | +2.6% (2.13) | -29.8% | -32.2% | -8.3% | -7.0% | -1.5% | -0.73 | -2.0% (-0.80) |
| h15_neu_B30 | 10.2% | 8.1% | 8.1% | +2.2% | 1.32 | 1.29 | +1.8% (1.42) | -28.0% | -30.3% | -1.1% | 0.6% | -2.0% | -1.03 | -2.6% (-1.24) |
| h10_neu_C30 | 6.8% | 1.9% | 2.1% | +4.9% | 4.39 | 4.19 | +4.5% (4.42) | -29.7% | -32.2% | -5.5% | -7.0% | +1.3% | 0.52 | +1.3% (0.65) |
| h10_neumom_RANK | 6.7% | 1.9% | 2.1% | +4.8% | 4.61 | 4.41 | +4.6% (4.74) | -29.8% | -32.2% | -4.9% | -7.0% | +1.9% | 0.92 | +1.9% (1.02) |
| h10_none_RANK | 5.7% | 1.9% | 2.1% | +3.8% | 3.55 | 3.33 | +3.6% (3.53) | -31.4% | -32.2% | -4.9% | -7.0% | +1.9% | 1.04 | +0.9% (0.48) |

Avoid overlay vs cost and liquidity tier:

| model | universe | cost | dev CAGR | dev EW | dev excess | dev t | 2026 CAGR | 2026 EW | 2026 excess | 2026 t |
|---|---|---|---|---|---|---|---|---|---|---|
| h10_neu_RANK | liq2 | 50 | 6.6% | 2.1% | +4.7% | 4.48 | -5.3% | -7.0% | +1.4% | 0.63 |
| h10_neu_RANK | liq2 | 80 | -1.0% | -5.2% | +4.4% | 4.48 | -12.0% | -13.5% | +1.3% | 0.63 |
| h10_neu_RANK | liq2 | 130 | -12.6% | -16.3% | +3.9% | 4.48 | -22.0% | -23.3% | +1.2% | 0.63 |
| h10_neu_RANK | liq5 | 50 | 6.8% | 3.2% | +3.7% | 3.01 | -6.7% | -7.8% | +0.8% | 0.34 |
| h10_neu_RANK | liq5 | 80 | -0.8% | -4.1% | +3.4% | 3.01 | -13.2% | -14.3% | +0.8% | 0.34 |
| h10_neu_RANK | liq5 | 130 | -12.4% | -15.3% | +3.0% | 3.01 | -23.1% | -24.1% | +0.7% | 0.33 |
| h15_neu_RANK | liq2 | 50 | 12.2% | 8.1% | +4.1% | 3.46 | 2.6% | 0.6% | +1.7% | 0.83 |
| h15_neu_RANK | liq2 | 80 | 6.8% | 2.9% | +3.9% | 3.46 | -2.1% | -4.0% | +1.6% | 0.83 |
| h15_neu_RANK | liq2 | 130 | -1.6% | -5.2% | +3.6% | 3.45 | -9.5% | -11.2% | +1.5% | 0.83 |
| h15_neu_RANK | liq5 | 50 | 12.5% | 9.3% | +3.3% | 2.44 | 0.8% | -0.4% | +1.1% | 0.47 |
| h15_neu_RANK | liq5 | 80 | 7.1% | 4.0% | +3.1% | 2.44 | -3.8% | -5.0% | +1.0% | 0.47 |
| h15_neu_RANK | liq5 | 130 | -1.3% | -4.2% | +2.9% | 2.44 | -11.1% | -12.1% | +1.0% | 0.47 |
| h20_neu_RANK | liq2 | 50 | 14.7% | 11.2% | +3.4% | 2.77 | 7.4% | 6.4% | +0.9% | 0.45 |
| h20_neu_RANK | liq2 | 80 | 10.6% | 7.2% | +3.3% | 2.77 | 3.7% | 2.8% | +0.9% | 0.44 |
| h20_neu_RANK | liq2 | 130 | 4.0% | 0.9% | +3.1% | 2.77 | -2.0% | -2.9% | +0.8% | 0.44 |
| h20_neu_RANK | liq5 | 50 | 15.1% | 12.4% | +2.7% | 1.99 | 5.5% | 5.3% | +0.1% | -0.01 |
| h20_neu_RANK | liq5 | 80 | 11.0% | 8.4% | +2.6% | 1.99 | 2.0% | 1.8% | +0.1% | -0.01 |
| h20_neu_RANK | liq5 | 130 | 4.4% | 1.9% | +2.4% | 1.99 | -3.7% | -3.9% | +0.1% | -0.01 |
| h20_neumom_RANK | liq2 | 50 | 15.1% | 11.2% | +3.8% | 3.40 | 8.2% | 6.4% | +1.8% | 1.02 |
| h20_neumom_RANK | liq2 | 80 | 10.9% | 7.2% | +3.7% | 3.40 | 4.6% | 2.8% | +1.7% | 1.02 |
| h20_neumom_RANK | liq2 | 130 | 4.3% | 0.9% | +3.5% | 3.39 | -1.2% | -2.9% | +1.6% | 1.02 |
| h20_neumom_RANK | liq5 | 50 | 15.2% | 12.4% | +2.8% | 2.32 | 5.9% | 5.3% | +0.6% | 0.26 |
| h20_neumom_RANK | liq5 | 80 | 11.1% | 8.4% | +2.7% | 2.32 | 2.4% | 1.8% | +0.5% | 0.26 |
| h20_neumom_RANK | liq5 | 130 | 4.5% | 1.9% | +2.5% | 2.32 | -3.3% | -3.9% | +0.5% | 0.26 |
| h20_neu_T30 | liq2 | 50 | 14.4% | 11.2% | +3.1% | 4.15 | 12.6% | 6.4% | +6.1% | 5.18 |
| h20_neu_T30 | liq2 | 80 | 10.3% | 7.2% | +3.0% | 4.15 | 8.8% | 2.8% | +5.9% | 5.18 |
| h20_neu_T30 | liq2 | 130 | 3.7% | 0.9% | +2.8% | 4.14 | 2.8% | -2.9% | +5.6% | 5.18 |
| h20_neu_T30 | liq5 | 50 | 14.8% | 12.4% | +2.3% | 2.82 | 11.4% | 5.3% | +6.0% | 5.33 |
| h20_neu_T30 | liq5 | 80 | 10.6% | 8.4% | +2.2% | 2.82 | 7.6% | 1.8% | +5.8% | 5.33 |
| h20_neu_T30 | liq5 | 130 | 4.1% | 1.9% | +2.1% | 2.82 | 1.6% | -3.9% | +5.5% | 5.33 |

Avoid cut sensitivity (how much of the universe to drop):

| model | avoid cut | dev excess vs random | dev t | dev t vs EW | 2026 excess | 2026 t |
|---|---|---|---|---|---|---|
| h10_neu_RANK | drop bottom 10% | +2.4% | 5.54 | 5.28 | +1.4% | 1.51 |
| h10_neu_RANK | drop bottom 20% | +3.6% | 4.89 | 4.69 | +1.4% | 0.76 |
| h10_neu_RANK | drop bottom 30% | +4.7% | 4.48 | 4.30 | +1.4% | 0.63 |
| h10_neu_RANK | drop bottom 50% | +7.2% | 4.48 | 4.03 | +1.3% | 0.39 |
| h20_neu_RANK | drop bottom 10% | +1.8% | 3.60 | 3.58 | +1.2% | 1.46 |
| h20_neu_RANK | drop bottom 20% | +2.7% | 3.12 | 3.09 | +1.2% | 0.84 |
| h20_neu_RANK | drop bottom 30% | +3.4% | 2.77 | 2.74 | +0.9% | 0.45 |
| h20_neu_RANK | drop bottom 50% | +5.1% | 2.83 | 2.68 | +0.8% | 0.25 |
| h20_neumom_RANK | drop bottom 10% | +1.7% | 3.58 | 3.55 | +1.3% | 1.84 |
| h20_neumom_RANK | drop bottom 20% | +3.1% | 3.77 | 3.73 | +1.5% | 1.23 |
| h20_neumom_RANK | drop bottom 30% | +3.8% | 3.40 | 3.37 | +1.8% | 1.02 |
| h20_neumom_RANK | drop bottom 50% | +5.4% | 3.18 | 3.02 | +2.1% | 0.96 |
| h20_neu_T30 | drop bottom 10% | +1.1% | 3.32 | 3.47 | +2.5% | 5.58 |
| h20_neu_T30 | drop bottom 20% | +2.1% | 3.95 | 4.05 | +4.2% | 5.26 |
| h20_neu_T30 | drop bottom 30% | +3.1% | 4.15 | 4.09 | +6.1% | 5.18 |
| h20_neu_T30 | drop bottom 50% | +5.1% | 3.98 | 3.88 | +10.2% | 5.48 |
| h20_neumom_T30 | drop bottom 10% | +1.3% | 4.14 | 4.29 | +2.5% | 4.99 |
| h20_neumom_T30 | drop bottom 20% | +2.5% | 4.35 | 4.46 | +4.2% | 5.11 |
| h20_neumom_T30 | drop bottom 30% | +3.5% | 4.58 | 4.55 | +6.3% | 5.69 |
| h20_neumom_T30 | drop bottom 50% | +5.9% | 4.44 | 4.36 | +10.9% | 5.94 |
| h20_neumom_C20 | drop bottom 10% | +1.7% | 3.54 | 3.51 | +1.4% | 1.93 |
| h20_neumom_C20 | drop bottom 20% | +2.7% | 3.50 | 3.45 | +1.3% | 1.03 |
| h20_neumom_C20 | drop bottom 30% | +3.3% | 3.00 | 2.97 | +1.2% | 0.82 |
| h20_neumom_C20 | drop bottom 50% | +4.4% | 2.93 | 2.74 | +2.8% | 1.53 |

### 6f. Equal-weight quantile books (plateau check beyond top-K)

| model | book | dev CAGR | dev excess vs random | dev t | dev maxDD | 2026 CAGR | 2026 excess | 2026 t |
|---|---|---|---|---|---|---|---|---|
| h20_neu_RANK | top 10% EW | 20.5% | +8.9% | 3.12 | -27.5% | 9.1% | +3.5% | 0.84 |
| h20_neu_RANK | top 20% EW | 18.0% | +6.9% | 2.85 | -27.0% | 7.3% | +1.1% | 0.31 |
| h20_neu_RANK | top 30% EW | 17.5% | +6.6% | 2.95 | -26.9% | 7.0% | +0.8% | 0.21 |
| h20_neumom_RANK | top 10% EW | 20.3% | +8.7% | 3.35 | -26.7% | 9.5% | +4.0% | 1.31 |
| h20_neumom_RANK | top 20% EW | 18.0% | +7.0% | 2.92 | -26.6% | 9.2% | +3.1% | 1.03 |
| h20_neumom_RANK | top 30% EW | 17.8% | +6.8% | 3.08 | -26.0% | 8.8% | +2.6% | 0.92 |
| h20_neu_T30 | top 10% EW | 22.1% | +10.6% | 3.11 | -30.7% | 27.7% | +22.2% | 4.70 |
| h20_neu_T30 | top 20% EW | 19.9% | +8.8% | 3.60 | -29.5% | 24.0% | +17.8% | 5.13 |
| h20_neu_T30 | top 30% EW | 19.0% | +8.0% | 3.99 | -28.5% | 22.3% | +16.1% | 5.62 |
| h20_neumom_T30 | top 10% EW | 23.5% | +11.9% | 3.68 | -29.9% | 28.7% | +23.2% | 5.06 |
| h20_neumom_T30 | top 20% EW | 20.0% | +8.9% | 3.55 | -29.4% | 26.6% | +20.5% | 5.88 |
| h20_neumom_T30 | top 30% EW | 18.7% | +7.8% | 3.97 | -28.6% | 22.4% | +16.2% | 5.78 |
| h20_neumom_C20 | top 10% EW | 21.5% | +9.9% | 3.77 | -26.6% | 14.9% | +9.4% | 3.45 |
| h20_neumom_C20 | top 20% EW | 18.8% | +7.7% | 3.79 | -27.2% | 12.5% | +6.3% | 2.77 |
| h20_neumom_C20 | top 30% EW | 16.9% | +6.0% | 3.13 | -27.6% | 11.8% | +5.6% | 2.85 |

### 6g. Calendar-phase robustness (start shifted 0..step-1 days; phase-average = daily-staggered book)

| model | book | phases | dev excess range over phases | dev phase-avg excess/yr (t) | 2026 excess range | 2026 share phases > 0 | 2026 phase-avg excess/yr (t) | 2026 phase-avg CAGR | 2026 phase-avg random |
|---|---|---|---|---|---|---|---|---|---|
| h10_neu_RANK | K20_s5 | 5 | +23.9% .. +28.4% | +23.8% (4.79) | +0.3% .. +12.2% | 100% | +8.6% (0.99) | 4.8% | -3.6% |
| h10_neu_RANK | K20_s10 | 10 | +17.2% .. +33.0% | +22.8% (4.69) | -5.8% .. +31.0% | 80% | +9.1% (1.14) | 7.5% | -1.6% |
| h10_neu_RANK | K50_s10 | 10 | +8.9% .. +26.5% | +17.2% (4.77) | +1.7% .. +15.7% | 100% | +7.7% (1.15) | 5.3% | -2.4% |
| h10_neu_RANK | avoid30_s5 | 5 | +4.1% .. +5.0% | +4.4% (4.47) | +1.2% .. +1.8% | 100% | +1.3% (0.62) | -3.3% | -4.7% |
| h15_neu_RANK | K20_s5 | 5 | +17.1% .. +22.8% | +17.8% (4.04) | -0.9% .. +15.5% | 80% | +7.8% (0.84) | 13.6% | 5.7% |
| h15_neu_RANK | K20_s10 | 10 | +7.3% .. +23.1% | +13.7% (4.31) | -0.8% .. +13.4% | 90% | +6.3% (1.01) | 11.8% | 5.3% |
| h15_neu_RANK | K50_s10 | 10 | +5.3% .. +16.8% | +10.6% (4.23) | -1.8% .. +11.1% | 70% | +3.1% (0.70) | 7.9% | 4.8% |
| h15_neu_RANK | avoid30_s5 | 5 | +3.7% .. +4.4% | +3.7% (3.57) | +0.4% .. +1.7% | 100% | +0.9% (0.55) | 5.1% | 3.9% |
| h20_neu_RANK | K20_s5 | 5 | +15.6% .. +20.1% | +15.2% (3.81) | +0.4% .. +7.2% | 100% | +3.3% (0.44) | 13.2% | 10.2% |
| h20_neu_RANK | K20_s10 | 10 | +12.3% .. +22.8% | +15.5% (4.14) | -12.4% .. +15.4% | 80% | +4.7% (0.62) | 15.1% | 10.4% |
| h20_neu_RANK | K50_s10 | 10 | +8.3% .. +16.5% | +11.3% (3.67) | -1.6% .. +9.6% | 70% | +2.2% (0.42) | 13.1% | 11.0% |
| h20_neu_RANK | avoid30_s5 | 5 | +3.4% .. +3.9% | +3.1% (2.99) | +0.3% .. +1.3% | 100% | +0.6% (0.38) | 9.4% | 8.6% |
| h20_neumom_RANK | K20_s5 | 5 | +15.0% .. +20.4% | +15.8% (4.11) | -2.0% .. +9.2% | 60% | +3.9% (0.60) | 13.9% | 10.2% |
| h20_neumom_RANK | K20_s10 | 10 | +15.0% .. +23.6% | +16.1% (4.43) | -4.0% .. +19.0% | 80% | +5.5% (0.89) | 16.1% | 10.4% |
| h20_neumom_RANK | K50_s10 | 10 | +9.5% .. +15.3% | +11.0% (3.97) | -4.1% .. +9.5% | 60% | +0.5% (0.11) | 11.3% | 11.0% |
| h20_neumom_RANK | avoid30_s5 | 5 | +3.8% .. +4.2% | +3.4% (3.58) | +1.0% .. +1.8% | 100% | +1.2% (0.84) | 10.1% | 8.6% |
| h20_size_RANK | K20_s5 | 5 | +10.8% .. +16.8% | +12.7% (2.90) | -5.7% .. +4.5% | 20% | -1.8% (-0.19) | 7.7% | 10.2% |
| h20_size_RANK | K20_s10 | 10 | +8.7% .. +21.0% | +12.8% (3.06) | -13.4% .. +9.2% | 60% | -0.3% (-0.03) | 9.6% | 10.4% |
| h20_size_RANK | K50_s10 | 10 | +5.2% .. +15.2% | +9.6% (2.78) | -7.1% .. +9.0% | 30% | -1.5% (-0.24) | 9.2% | 11.0% |
| h20_size_RANK | avoid30_s5 | 5 | +3.3% .. +4.0% | +3.2% (3.51) | +0.7% .. +1.3% | 100% | +0.7% (0.49) | 9.5% | 8.6% |
| h20_none_RANK | K20_s5 | 5 | +13.2% .. +17.6% | +13.8% (3.27) | -13.7% .. -2.4% | 0% | -7.7% (-0.91) | 1.9% | 10.2% |
| h20_none_RANK | K20_s10 | 10 | +8.0% .. +21.0% | +14.0% (3.42) | -14.3% .. +4.5% | 10% | -6.4% (-0.73) | 3.5% | 10.4% |
| h20_none_RANK | K50_s10 | 10 | +8.2% .. +15.7% | +10.7% (3.38) | -10.0% .. +2.9% | 30% | -4.6% (-0.69) | 6.1% | 11.0% |
| h20_none_RANK | avoid30_s5 | 5 | +3.3% .. +3.9% | +3.3% (3.65) | +0.5% .. +1.0% | 100% | +0.5% (0.31) | 9.3% | 8.6% |
| h20_neu_C30 | K20_s5 | 5 | +12.9% .. +20.2% | +14.7% (3.61) | -3.1% .. +5.8% | 60% | +1.0% (0.13) | 10.7% | 10.2% |
| h20_neu_C30 | K20_s10 | 10 | +7.7% .. +24.9% | +14.9% (3.92) | -4.2% .. +12.3% | 70% | +3.0% (0.35) | 13.2% | 10.4% |
| h20_neu_C30 | K50_s10 | 10 | +8.3% .. +16.6% | +10.8% (3.53) | -6.3% .. +7.5% | 50% | +0.5% (0.10) | 11.4% | 11.0% |
| h20_neu_C30 | avoid30_s5 | 5 | +3.5% .. +4.0% | +3.2% (2.95) | +0.9% .. +1.7% | 100% | +1.0% (0.57) | 9.8% | 8.6% |
| h20_neu_C20 | K20_s5 | 5 | +18.9% .. +22.4% | +18.1% (4.87) | +6.7% .. +15.7% | 100% | +10.2% (1.66) | 21.3% | 10.2% |
| h20_neu_C20 | K20_s10 | 10 | +17.2% .. +26.7% | +18.4% (5.32) | +2.4% .. +24.6% | 100% | +12.5% (2.01) | 24.3% | 10.4% |
| h20_neu_C20 | K50_s10 | 10 | +13.3% .. +17.1% | +13.6% (4.61) | +8.2% .. +24.0% | 100% | +12.6% (3.00) | 25.4% | 11.0% |
| h20_neu_C20 | avoid30_s5 | 5 | +3.1% .. +3.7% | +2.9% (2.75) | +0.4% .. +1.5% | 100% | +0.8% (0.52) | 9.6% | 8.6% |
| h20_neu_C33 | K20_s5 | 5 | +13.8% .. +17.9% | +13.6% (3.30) | -4.4% .. +3.2% | 60% | -0.4% (-0.05) | 9.4% | 10.2% |
| h20_neu_C33 | K20_s10 | 10 | +9.7% .. +19.0% | +13.9% (3.65) | -4.8% .. +12.2% | 50% | +1.4% (0.17) | 11.7% | 10.4% |
| h20_neu_C33 | K50_s10 | 10 | +7.2% .. +16.5% | +9.6% (3.03) | -4.5% .. +6.9% | 50% | -0.0% (-0.00) | 10.9% | 11.0% |
| h20_neu_C33 | avoid30_s5 | 5 | +3.7% .. +4.2% | +3.3% (3.12) | +0.6% .. +1.3% | 100% | +0.8% (0.50) | 9.6% | 8.6% |
| h20_neu_T30 | K20_s5 | 5 | +18.1% .. +24.6% | +19.4% (4.26) | +12.5% .. +21.0% | 100% | +14.9% (2.45) | 27.0% | 10.2% |
| h20_neu_T30 | K20_s10 | 10 | +14.3% .. +27.3% | +19.7% (4.53) | +5.0% .. +34.6% | 100% | +16.8% (2.71) | 29.8% | 10.4% |
| h20_neu_T30 | K50_s10 | 10 | +12.6% .. +20.5% | +15.5% (4.39) | +13.5% .. +24.6% | 100% | +17.7% (3.53) | 31.8% | 11.0% |
| h20_neu_T30 | avoid30_s5 | 5 | +3.1% .. +3.6% | +3.1% (4.49) | +6.1% .. +6.5% | 100% | +6.1% (5.93) | 15.3% | 8.6% |
| h20_neu_T20 | K20_s5 | 5 | +15.6% .. +23.5% | +17.1% (3.39) | +12.1% .. +22.9% | 100% | +15.9% (1.79) | 28.1% | 10.2% |
| h20_neu_T20 | K20_s10 | 10 | +12.7% .. +26.5% | +17.6% (3.55) | +9.1% .. +34.5% | 100% | +18.0% (2.00) | 31.3% | 10.4% |
| h20_neu_T20 | K50_s10 | 10 | +9.6% .. +18.1% | +14.4% (3.57) | +19.3% .. +30.7% | 100% | +22.9% (3.06) | 38.6% | 11.0% |
| h20_neu_T20 | avoid30_s5 | 5 | +2.5% .. +2.9% | +2.7% (2.67) | +7.1% .. +8.0% | 100% | +7.2% (4.02) | 16.5% | 8.6% |
| h20_neu_T10 | K20_s5 | 5 | +16.1% .. +22.3% | +17.8% (3.01) | +16.0% .. +25.6% | 100% | +17.8% (1.52) | 30.2% | 10.2% |
| h20_neu_T10 | K20_s10 | 10 | +12.5% .. +24.9% | +18.3% (3.16) | +11.9% .. +28.4% | 100% | +19.9% (1.64) | 33.2% | 10.4% |
| h20_neu_T10 | K50_s10 | 10 | +13.1% .. +17.4% | +14.4% (3.21) | +16.6% .. +33.4% | 100% | +22.5% (2.28) | 37.8% | 11.0% |
| h20_neu_T10 | avoid30_s5 | 5 | +1.8% .. +2.0% | +2.2% (1.54) | +6.5% .. +7.1% | 100% | +6.7% (2.72) | 15.7% | 8.6% |
| h20_neu_T50 | K20_s5 | 5 | +3.4% .. +13.6% | +5.9% (1.23) | -9.3% .. -4.8% | 0% | -7.1% (-0.82) | 2.6% | 10.2% |
| h20_neu_T50 | K20_s10 | 10 | +3.0% .. +16.3% | +6.2% (1.32) | -12.8% .. +3.0% | 10% | -5.7% (-0.64) | 4.3% | 10.4% |
| h20_neu_T50 | K50_s10 | 10 | +3.2% .. +10.2% | +5.8% (1.43) | -9.8% .. +6.9% | 40% | -2.6% (-0.39) | 8.3% | 11.0% |
| h20_neu_T50 | avoid30_s5 | 5 | +4.1% .. +4.5% | +3.7% (3.45) | +0.8% .. +1.5% | 100% | +0.8% (0.43) | 9.6% | 8.6% |
| h20_neumom_T30 | K20_s5 | 5 | +19.0% .. +26.5% | +19.6% (4.57) | +7.5% .. +16.2% | 100% | +11.6% (2.14) | 23.0% | 10.2% |
| h20_neumom_T30 | K20_s10 | 10 | +15.8% .. +29.0% | +20.1% (4.81) | +8.9% .. +19.8% | 100% | +14.6% (2.69) | 27.0% | 10.4% |
| h20_neumom_T30 | K50_s10 | 10 | +12.0% .. +19.6% | +15.8% (4.68) | +13.3% .. +23.5% | 100% | +17.7% (3.40) | 31.8% | 11.0% |
| h20_neumom_T30 | avoid30_s5 | 5 | +3.4% .. +3.8% | +3.4% (4.87) | +6.3% .. +6.8% | 100% | +6.3% (6.20) | 15.6% | 8.6% |
| h20_neumom_C20 | K20_s5 | 5 | +18.3% .. +23.6% | +18.5% (5.07) | +2.5% .. +15.4% | 100% | +8.9% (1.32) | 19.7% | 10.2% |
| h20_neumom_C20 | K20_s10 | 10 | +13.6% .. +25.8% | +18.9% (5.45) | +0.3% .. +27.7% | 100% | +11.6% (1.85) | 23.2% | 10.4% |
| h20_neumom_C20 | K50_s10 | 10 | +11.9% .. +19.3% | +13.8% (5.21) | +4.2% .. +17.8% | 100% | +10.0% (1.94) | 22.2% | 11.0% |
| h20_neumom_C20 | avoid30_s5 | 5 | +3.3% .. +3.6% | +3.0% (3.23) | +0.8% .. +1.6% | 100% | +1.0% (0.75) | 9.8% | 8.6% |
| h20_neu_B30 | K20_s5 | 5 | +1.4% .. +3.2% | +0.7% (0.09) | -15.9% .. -11.3% | 0% | -15.2% (-1.66) | -4.8% | 10.2% |
| h20_neu_B30 | K20_s10 | 10 | -0.3% .. +3.6% | +0.9% (0.11) | -18.9% .. -7.8% | 0% | -14.1% (-1.49) | -3.5% | 10.4% |
| h20_neu_B30 | K50_s10 | 10 | -0.1% .. +3.8% | +0.5% (0.08) | -20.0% .. -10.0% | 0% | -15.9% (-1.93) | -4.7% | 11.0% |
| h20_neu_B30 | avoid30_s5 | 5 | +1.9% .. +2.4% | +1.7% (1.28) | -2.7% .. -2.0% | 0% | -2.7% (-1.27) | 6.0% | 8.6% |
| h10_neu_T30 | K20_s5 | 5 | +21.8% .. +31.2% | +25.1% (4.75) | +11.4% .. +26.7% | 100% | +20.1% (2.26) | 16.9% | -3.6% |
| h10_neu_T30 | K20_s10 | 10 | +11.7% .. +34.4% | +24.5% (4.60) | -6.2% .. +51.2% | 80% | +20.7% (2.20) | 20.0% | -1.6% |
| h10_neu_T30 | K50_s10 | 10 | +14.8% .. +24.0% | +19.3% (4.74) | +12.9% .. +45.2% | 100% | +25.8% (2.99) | 25.5% | -2.4% |
| h10_neu_T30 | avoid30_s5 | 5 | +3.8% .. +4.1% | +4.1% (5.24) | +5.2% .. +7.2% | 100% | +7.0% (5.04) | 2.0% | -4.7% |
| h15_neu_T30 | K20_s5 | 5 | +19.8% .. +29.1% | +21.2% (4.62) | -6.3% .. +16.1% | 80% | +6.0% (0.83) | 11.5% | 5.7% |
| h15_neu_T30 | K20_s10 | 10 | +13.3% .. +23.0% | +16.4% (4.76) | -10.0% .. +16.5% | 80% | +5.6% (1.04) | 11.0% | 5.3% |
| h15_neu_T30 | K50_s10 | 10 | +10.9% .. +17.3% | +12.9% (4.74) | +5.5% .. +17.0% | 100% | +11.7% (2.67) | 17.4% | 4.8% |
| h15_neu_T30 | avoid30_s5 | 5 | +3.5% .. +3.9% | +3.6% (4.91) | +5.8% .. +7.4% | 100% | +6.5% (5.93) | 10.8% | 3.9% |
| h10_neu_B30 | K20_s5 | 5 | +1.6% .. +5.2% | +2.9% (0.39) | -14.7% .. -6.6% | 0% | -14.4% (-1.35) | -15.9% | -3.6% |
| h10_neu_B30 | K20_s10 | 10 | +0.5% .. +6.9% | +2.1% (0.28) | -18.4% .. -5.1% | 0% | -14.3% (-1.33) | -14.1% | -1.6% |
| h10_neu_B30 | K50_s10 | 10 | -1.8% .. +5.4% | +1.1% (0.17) | -17.9% .. -6.4% | 0% | -15.4% (-1.68) | -15.8% | -2.4% |
| h10_neu_B30 | avoid30_s5 | 5 | +2.7% .. +3.1% | +2.6% (2.13) | -1.6% .. -1.1% | 0% | -2.0% (-0.80) | -6.4% | -4.7% |
| h15_neu_B30 | K20_s5 | 5 | +1.3% .. +2.5% | +0.8% (0.10) | -16.4% .. -11.6% | 0% | -16.1% (-1.76) | -9.5% | 5.7% |
| h15_neu_B30 | K20_s10 | 10 | -2.9% .. +5.5% | +0.7% (0.13) | -20.7% .. -2.8% | 0% | -12.2% (-1.79) | -6.5% | 5.3% |
| h15_neu_B30 | K50_s10 | 10 | -1.2% .. +3.9% | +0.5% (0.11) | -15.0% .. -1.8% | 0% | -11.0% (-1.89) | -5.8% | 4.8% |
| h15_neu_B30 | avoid30_s5 | 5 | +1.9% .. +2.7% | +1.8% (1.42) | -2.8% .. -1.6% | 0% | -2.6% (-1.24) | 1.5% | 3.9% |
| h10_neu_C30 | K20_s5 | 5 | +22.9% .. +29.9% | +23.3% (4.68) | +3.7% .. +14.1% | 100% | +8.9% (0.98) | 5.1% | -3.6% |
| h10_neu_C30 | K20_s10 | 10 | +17.6% .. +31.4% | +22.4% (4.66) | -10.3% .. +29.8% | 80% | +10.0% (1.18) | 8.5% | -1.6% |
| h10_neu_C30 | K50_s10 | 10 | +13.6% .. +18.2% | +14.3% (3.84) | +2.6% .. +24.6% | 100% | +8.9% (1.33) | 6.5% | -2.4% |
| h10_neu_C30 | avoid30_s5 | 5 | +4.3% .. +5.1% | +4.5% (4.42) | +1.1% .. +2.1% | 100% | +1.3% (0.65) | -3.3% | -4.7% |
| h10_neumom_RANK | K20_s5 | 5 | +18.1% .. +29.8% | +21.9% (4.90) | +0.7% .. +13.7% | 100% | +8.6% (1.12) | 4.7% | -3.6% |
| h10_neumom_RANK | K20_s10 | 10 | +10.9% .. +33.7% | +21.1% (4.80) | -10.9% .. +26.9% | 80% | +10.2% (1.39) | 8.6% | -1.6% |
| h10_neumom_RANK | K50_s10 | 10 | +11.5% .. +25.8% | +16.5% (4.79) | -0.5% .. +20.0% | 80% | +7.9% (1.33) | 5.4% | -2.4% |
| h10_neumom_RANK | avoid30_s5 | 5 | +4.7% .. +5.1% | +4.6% (4.74) | +1.8% .. +2.5% | 100% | +1.9% (1.02) | -2.7% | -4.7% |
| h10_none_RANK | K20_s5 | 5 | +16.0% .. +23.3% | +18.0% (3.70) | -6.5% .. +8.0% | 60% | +0.7% (0.07) | -3.1% | -3.6% |
| h10_none_RANK | K20_s10 | 10 | +9.0% .. +25.0% | +17.0% (3.63) | -10.7% .. +18.2% | 50% | +1.1% (0.12) | -0.7% | -1.6% |
| h10_none_RANK | K50_s10 | 10 | +7.5% .. +18.6% | +13.5% (3.60) | -14.1% .. +11.1% | 30% | -4.3% (-0.60) | -6.5% | -2.4% |
| h10_none_RANK | avoid30_s5 | 5 | +3.4% .. +4.2% | +3.6% (3.53) | +0.4% .. +1.9% | 100% | +0.9% (0.48) | -3.7% | -4.7% |


**Plateaus vs cliffs (DEV-based, 2026 for information)**

| parameter | robust plateau | cliff / fragile | evidence |
|---|---|---|---|
| horizon (net of cost) | h=20 (h=15 at 50 bps) | h=10 at >=80 bps | DEV CAGR 80bp 16.2/19.6/25.2%; 130bp 2.6/10.2/17.7% (h10/15/20) |
| training horizon | any of 10/15/20 when held 20d | - | held-20d DEV excess +18.1/+15.1/+18.0% (t 4.02/3.29/3.75) |
| neutraliser | neumom ~ neu | none / size (2026 negative) | phase-avg DEV t 4.11/3.81/3.27/2.90; 2026 +3.9/+3.3/-7.7/-1.8% |
| label form / rank cut | RANK, C20, T30 (C30/C33 slightly lower) | T50, T10, B30 | phase-avg DEV t (neu) RANK 3.81, C20 4.87, C30 3.61, C33 3.30, T30 4.26, T20 3.39, T10 3.01, T50 1.23, B30 0.09 |
| K (long book) | smooth slope 10..50, no cliff | - | neumom RANK DEV excess +32.1/+19.1/+16.9/+11.9% (t 4.95/4.25/4.18/3.66) for K=10/20/30/50; maxDD -25..-27% throughout |
| step | 5 ~ 10 after phase-averaging | single-phase step 10 | neu RANK K20 s10 2026 excess -12.4..+15.4% across 10 phases |
| liquidity tier | liq2 (more edge) | - | neumom RANK DEV excess +19.1% liq2 vs +14.3% liq5 (t 4.25 vs 3.28) |
| cost | excess vs random nearly cost-invariant | absolute CAGR | about -1.5%/yr per +10 bps at h=20 (about 12.6 round trips/yr) |
| avoid cut | drop worst 10-30% | - | neumom RANK DEV +1.7/+3.1/+3.8/+5.4% for 10/20/30/50% (t 3.6/3.8/3.4/3.2); 2026 t 1.84/1.23/1.02/0.96 |

The event rates of the book move with K and the cut. A K=20 book holds the top ~2% of about 1,050
names a day. The EW top-10% / top-20% / top-30% books earn +8.7 / +7.0 / +6.8% DEV excess (neumom RANK),
so the alpha decays smoothly with depth rather than collapsing.


## 7. Luck calibration

| h / period | random CAGR (5 seeds) | iid random sd (40) | iid p95 | constant-tilt excess sd | constant-tilt excess p95 | max | constant-tilt NW t sd | NW t p95 | NW t max |
|---|---|---|---|---|---|---|---|---|---|
| h10_dev | 1.2% | 3.1% | 7.0% | 6.3% | +12.1% | +18.5% | 1.27 | 2.38 | 3.67 |
| h10_hold | -4.0% | 5.2% | 1.8% | 11.9% | +17.0% | +33.4% | 1.50 | 1.53 | 3.55 |
| h15_dev | 8.5% | 2.4% | 12.0% | 6.6% | +11.8% | +18.9% | 1.33 | 2.26 | 3.79 |
| h15_hold | 2.0% | 5.7% | 11.8% | 12.5% | +18.5% | +40.0% | 1.52 | 1.56 | 3.79 |
| h20_dev | 11.8% | 1.9% | 14.6% | 6.7% | +12.2% | +19.5% | 1.37 | 2.27 | 3.89 |
| h20_hold | 6.9% | 4.7% | 13.8% | 13.0% | +19.0% | +45.4% | 1.54 | 1.52 | 3.86 |

Persistence-matched null (random scores with the model's own rank autocorrelation, 40 seeds):

| model / book | period | null persistence (fitted) | model excess | model NW t | null excess sd | null p95 | null max | null NW t sd | null t p95 | model percentile in null | model z vs null |
|---|---|---|---|---|---|---|---|---|---|---|---|
| h20_neu_RANK_K20_s5 | dev | w=0.18, rho=0.922 | +18.0% | 3.75 | 3.4% | +5.6% | +7.0% | 1.06 | 1.54 | 100% | 5.4 |
| h20_neu_RANK_K20_s5 | hold | w=0.18, rho=0.922 | +3.2% | 0.49 | 5.4% | +5.4% | +10.8% | 1.04 | 1.15 | 82% | 1.0 |
| h20_neumom_RANK_K20_s5 | dev | w=0.20, rho=0.914 | +19.1% | 4.25 | 3.5% | +5.5% | +8.1% | 1.10 | 1.80 | 100% | 5.5 |
| h20_neumom_RANK_K20_s5 | hold | w=0.20, rho=0.914 | +9.2% | 1.54 | 5.0% | +6.3% | +10.0% | 0.95 | 1.38 | 98% | 2.2 |
| h20_neu_T30_K20_s5 | dev | w=0.11, rho=0.932 | +18.1% | 3.30 | 3.4% | +5.3% | +7.6% | 1.03 | 1.44 | 100% | 5.4 |
| h20_neu_T30_K20_s5 | hold | w=0.11, rho=0.932 | +21.0% | 3.17 | 5.6% | +8.2% | +14.7% | 1.03 | 1.69 | 100% | 4.0 |
| h20_neu_C20_K20_s5 | dev | w=0.14, rho=0.927 | +18.9% | 3.86 | 3.4% | +5.9% | +8.3% | 1.03 | 1.67 | 100% | 5.7 |
| h20_neu_C20_K20_s5 | hold | w=0.14, rho=0.927 | +12.2% | 1.87 | 5.7% | +9.2% | +11.6% | 1.07 | 1.48 | 100% | 2.5 |


* **iid random picker:** sd 1.9% CAGR on DEV and 4.7% over the 9.5-month 2026 (h=20). This is the band
  `S.compare` implicitly uses.
* **Constant per-stock random tilt (picks the same names repeatedly):** excess sd 6.7% DEV and 13.0% 2026.
  NW t sd is 1.37 / 1.54 instead of 1.0, and the max of 40 seeds is +19.5% (t 3.89) on DEV, the same size
  as the models. **Newey-West t overstates significance for persistent tilts.**
* **Persistence-matched null** (random scores with the model's own rank autocorrelation, lag-5 0.71,
  lag-250 0.20): NW t sd is 1.03-1.10, so it is calibrated for rotating scores like these. Every candidate
  sits 5.4-5.7 sd above its null on DEV. In 2026 neumom RANK is at the 98th percentile (z 2.2), neu RANK
  the 82nd (z 1.0), and C20 / T30 the 100th (z 2.5 / 4.0).


## 8. What the scores load on: factor attribution and reference sorts

| model | rho vol_20 | beta_60 | log_turn20 | mom_12_1 | mom_5 | idio_vol_60 | dist_sma200 | deliv_pct | top-20 pick pctile vol/turnover/mom12-1 (dev) | top-20 fno / liq5 share (dev) |
|---|---|---|---|---|---|---|---|---|---|---|
| h20_neu_RANK | -0.19 | -0.15 | 0.24 | 0.10 | -0.04 | -0.34 | 0.16 | 0.21 | 0.64 / 0.59 / 0.60 | 28% / 85% |
| h20_neumom_RANK | -0.20 | -0.14 | 0.24 | 0.01 | -0.05 | -0.38 | 0.11 | 0.23 | 0.64 / 0.56 / 0.48 | 26% / 81% |
| h20_none_RANK | -0.05 | 0.09 | 0.14 | 0.09 | -0.08 | -0.21 | 0.13 | 0.15 | 0.64 / 0.60 / 0.60 | 31% / 84% |
| h20_size_RANK | -0.08 | 0.10 | 0.23 | 0.10 | -0.07 | -0.25 | 0.13 | 0.13 | 0.65 / 0.62 / 0.59 | 34% / 87% |
| h20_neu_C20 | -0.19 | -0.13 | 0.15 | 0.08 | -0.04 | -0.35 | 0.14 | 0.22 | 0.63 / 0.47 / 0.60 | 14% / 76% |
| h20_neu_T30 | 0.31 | 0.12 | 0.00 | 0.29 | 0.08 | 0.24 | 0.41 | 0.03 | 0.74 / 0.49 / 0.62 | 12% / 78% |
| h20_neumom_T30 | 0.30 | 0.12 | 0.02 | 0.28 | 0.08 | 0.23 | 0.42 | 0.04 | 0.77 / 0.47 / 0.54 | 12% / 77% |
| h20_neumom_C20 | -0.17 | -0.10 | 0.13 | -0.03 | -0.05 | -0.36 | 0.09 | 0.22 | 0.66 / 0.45 / 0.46 | 12% / 73% |
| h20_neu_B30 | -0.57 | -0.33 | 0.36 | -0.11 | -0.11 | -0.73 | -0.14 | 0.28 | 0.10 / 0.86 / 0.43 | 80% / 97% |
| h10_neu_RANK | -0.25 | -0.17 | 0.27 | 0.06 | -0.13 | -0.39 | 0.09 | 0.30 | 0.63 / 0.60 / 0.57 | 30% / 85% |
| h15_neu_RANK | -0.22 | -0.16 | 0.25 | 0.08 | -0.07 | -0.36 | 0.14 | 0.26 | 0.65 / 0.59 / 0.57 | 29% / 84% |

Long-short factor returns (top-30% minus bottom-30% EW, h=20 step 5):

| period | vol_20 | mom_12_1 | log_turn20 | mom_5 | beta_60 | dist_sma200 |
|---|---|---|---|---|---|---|
| dev | +1.2% | +13.3% | +4.2% | -2.3% | +1.0% | +9.6% |
| hold | +17.7% | +26.1% | -4.9% | -3.0% | +10.3% | +18.2% |

Regression of daily excess-vs-random on the 6 factor series (NW t, lag 20):

| book | excess vs random /yr | alpha /yr | alpha NW t | R2 | factor betas (t) |
|---|---|---|---|---|---|
| h20_neu_RANK_K20_s5_dev | +15.7% | +13.8% | 3.11 | 0.10 | vol_20 +0.33 (+3.2), mom_12_1 +0.09 (+0.8), log_turn20 +0.13 (+2.3), mom_5 -0.08 (-0.7), beta_60 -0.14 (-1.8), dist_sma200 -0.03 (-0.3) |
| h20_neumom_RANK_K20_s5_dev | +16.3% | +17.4% | 3.99 | 0.05 | vol_20 +0.21 (+2.1), mom_12_1 -0.00 (-0.0), log_turn20 +0.01 (+0.2), mom_5 +0.00 (+0.0), beta_60 -0.05 (-0.8), dist_sma200 -0.14 (-1.3) |
| h20_none_RANK_K20_s5_dev | +12.3% | +9.7% | 2.29 | 0.21 | vol_20 +0.26 (+2.2), mom_12_1 +0.05 (+0.5), log_turn20 +0.23 (+3.5), mom_5 -0.41 (-3.6), beta_60 +0.07 (+0.7), dist_sma200 -0.04 (-0.3) |
| h20_size_RANK_K20_s5_dev | +10.3% | +7.8% | 1.88 | 0.25 | vol_20 +0.26 (+2.2), mom_12_1 +0.01 (+0.1), log_turn20 +0.27 (+3.8), mom_5 -0.36 (-3.3), beta_60 +0.13 (+1.4), dist_sma200 +0.00 (+0.0) |
| h20_neu_C30_K20_s5_dev | +11.3% | +9.7% | 1.98 | 0.02 | vol_20 +0.16 (+1.5), mom_12_1 +0.11 (+1.0), log_turn20 +0.16 (+2.8), mom_5 -0.11 (-1.2), beta_60 -0.13 (-1.7), dist_sma200 -0.09 (-0.7) |
| h20_neu_C20_K20_s5_dev | +16.3% | +16.2% | 3.65 | 0.05 | vol_20 +0.15 (+1.5), mom_12_1 +0.02 (+0.2), log_turn20 -0.04 (-0.7), mom_5 +0.07 (+0.5), beta_60 -0.02 (-0.3), dist_sma200 -0.00 (-0.0) |
| h20_neu_C33_K20_s5_dev | +12.2% | +10.4% | 2.23 | 0.05 | vol_20 +0.10 (+0.8), mom_12_1 +0.09 (+0.8), log_turn20 +0.22 (+3.3), mom_5 -0.30 (-2.9), beta_60 -0.11 (-1.3), dist_sma200 -0.10 (-0.8) |
| h20_neu_T30_K20_s5_dev | +16.3% | +14.6% | 3.06 | 0.30 | vol_20 +0.47 (+5.7), mom_12_1 +0.01 (+0.1), log_turn20 -0.01 (-0.2), mom_5 -0.13 (-1.4), beta_60 -0.10 (-1.6), dist_sma200 +0.08 (+0.8) |
| h20_neu_T20_K20_s5_dev | +15.1% | +15.7% | 3.25 | 0.37 | vol_20 +0.52 (+6.1), mom_12_1 -0.14 (-1.5), log_turn20 -0.14 (-2.9), mom_5 +0.11 (+1.0), beta_60 -0.09 (-1.5), dist_sma200 +0.16 (+1.5) |
| h20_neu_T10_K20_s5_dev | +14.9% | +16.1% | 3.13 | 0.39 | vol_20 +0.71 (+8.1), mom_12_1 -0.18 (-1.9), log_turn20 -0.11 (-2.1), mom_5 +0.10 (+0.9), beta_60 -0.21 (-3.4), dist_sma200 +0.12 (+1.1) |
| h20_neu_T50_K20_s5_dev | +3.3% | +1.1% | 0.27 | 0.32 | vol_20 -0.13 (-0.9), mom_12_1 +0.24 (+2.4), log_turn20 +0.31 (+4.4), mom_5 -0.37 (-2.4), beta_60 -0.14 (-1.5), dist_sma200 -0.29 (-1.9) |
| h20_neu_B30_K20_s5_dev | +0.5% | +1.5% | 0.37 | 0.74 | vol_20 -0.42 (-3.9), mom_12_1 +0.05 (+0.6), log_turn20 +0.39 (+7.7), mom_5 -0.12 (-1.0), beta_60 -0.33 (-4.9), dist_sma200 -0.29 (-2.0) |
| h20_neumom_T30_K20_s5_dev | +16.9% | +17.8% | 4.15 | 0.31 | vol_20 +0.44 (+5.0), mom_12_1 -0.24 (-3.0), log_turn20 -0.03 (-0.5), mom_5 -0.00 (-0.0), beta_60 -0.01 (-0.2), dist_sma200 +0.20 (+1.8) |
| h20_neumom_C20_K20_s5_dev | +15.9% | +18.0% | 4.02 | 0.12 | vol_20 +0.19 (+1.9), mom_12_1 -0.22 (-2.6), log_turn20 -0.11 (-2.3), mom_5 +0.06 (+0.7), beta_60 +0.02 (+0.4), dist_sma200 +0.11 (+0.8) |
| h20_neu_RANK_avoid30_s5_dev | +2.9% | +2.6% | 3.51 | 0.58 | vol_20 -0.07 (-3.9), mom_12_1 +0.01 (+0.3), log_turn20 +0.04 (+5.2), mom_5 -0.00 (-0.2), beta_60 -0.02 (-1.8), dist_sma200 +0.02 (+0.6) |
| h20_neumom_RANK_avoid30_s5_dev | +3.3% | +3.1% | 4.99 | 0.62 | vol_20 -0.08 (-4.5), mom_12_1 +0.00 (+0.1), log_turn20 +0.04 (+5.4), mom_5 +0.00 (+0.1), beta_60 -0.02 (-1.8), dist_sma200 +0.01 (+0.3) |
| h20_neu_T30_avoid30_s5_dev | +2.9% | +2.3% | 3.87 | 0.53 | vol_20 +0.04 (+2.7), mom_12_1 +0.02 (+1.4), log_turn20 -0.00 (-0.0), mom_5 +0.01 (+0.5), beta_60 +0.00 (+0.1), dist_sma200 +0.04 (+1.6) |
| h20_neu_B30_avoid30_s5_dev | +1.7% | +1.7% | 3.13 | 0.87 | vol_20 -0.13 (-9.7), mom_12_1 -0.01 (-0.5), log_turn20 +0.05 (+7.3), mom_5 -0.02 (-1.2), beta_60 -0.02 (-2.7), dist_sma200 -0.00 (-0.2) |
| h20_neumom_T30_avoid30_s5_dev | +3.3% | +2.6% | 4.75 | 0.55 | vol_20 +0.04 (+2.2), mom_12_1 +0.02 (+1.3), log_turn20 -0.00 (-0.4), mom_5 +0.01 (+0.5), beta_60 +0.01 (+0.9), dist_sma200 +0.05 (+1.9) |
| h20_neumom_C20_avoid30_s5_dev | +2.8% | +2.9% | 4.48 | 0.61 | vol_20 -0.07 (-4.2), mom_12_1 -0.01 (-0.9), log_turn20 +0.03 (+4.3), mom_5 +0.00 (+0.1), beta_60 -0.01 (-1.0), dist_sma200 +0.01 (+0.2) |
| h20_neu_RANK_K20_s5_hold | +3.7% | +7.7% | 0.80 | 0.29 | vol_20 +0.59 (+4.1), mom_12_1 +0.22 (+1.1), log_turn20 +0.58 (+5.7), mom_5 -0.03 (-0.2), beta_60 -0.39 (-4.2), dist_sma200 -0.74 (-6.0) |
| h20_neumom_RANK_K20_s5_hold | +8.9% | +11.6% | 1.78 | 0.28 | vol_20 +0.55 (+4.1), mom_12_1 +0.09 (+0.5), log_turn20 +0.46 (+3.6), mom_5 -0.19 (-1.3), beta_60 -0.34 (-4.0), dist_sma200 -0.51 (-3.5) |
| h20_none_RANK_K20_s5_hold | -2.7% | +8.0% | 1.42 | 0.45 | vol_20 +0.10 (+0.8), mom_12_1 +0.42 (+3.1), log_turn20 +0.68 (+5.8), mom_5 +0.20 (+1.2), beta_60 -0.22 (-2.6), dist_sma200 -0.95 (-8.6) |
| h20_size_RANK_K20_s5_hold | -1.1% | +5.9% | 0.65 | 0.43 | vol_20 +0.34 (+2.6), mom_12_1 +0.46 (+2.9), log_turn20 +0.54 (+5.8), mom_5 +0.18 (+1.2), beta_60 -0.31 (-3.7), dist_sma200 -1.01 (-8.2) |
| h20_neu_C30_K20_s5_hold | +5.9% | +9.8% | 1.21 | 0.36 | vol_20 +0.36 (+2.4), mom_12_1 +0.47 (+2.6), log_turn20 +0.54 (+6.4), mom_5 +0.01 (+0.0), beta_60 -0.32 (-3.1), dist_sma200 -0.91 (-7.6) |
| h20_neu_C20_K20_s5_hold | +11.6% | +10.7% | 1.28 | 0.32 | vol_20 +0.57 (+4.6), mom_12_1 +0.36 (+1.9), log_turn20 +0.27 (+2.5), mom_5 +0.04 (+0.2), beta_60 -0.37 (-3.8), dist_sma200 -0.72 (-5.4) |
| h20_neu_C33_K20_s5_hold | +3.3% | +10.3% | 1.22 | 0.35 | vol_20 +0.22 (+1.6), mom_12_1 +0.39 (+2.0), log_turn20 +0.63 (+7.8), mom_5 -0.03 (-0.2), beta_60 -0.25 (-2.4), dist_sma200 -0.84 (-6.9) |
| h20_neu_T30_K20_s5_hold | +18.9% | +7.9% | 1.12 | 0.32 | vol_20 +0.86 (+7.7), mom_12_1 +0.04 (+0.3), log_turn20 +0.21 (+1.9), mom_5 -0.09 (-0.5), beta_60 -0.37 (-4.8), dist_sma200 -0.04 (-0.3) |
| h20_neu_T20_K20_s5_hold | +20.5% | +6.1% | 0.77 | 0.38 | vol_20 +0.83 (+7.0), mom_12_1 -0.18 (-0.9), log_turn20 +0.03 (+0.2), mom_5 -0.07 (-0.3), beta_60 -0.28 (-2.7), dist_sma200 +0.40 (+2.2) |
| h20_neu_T10_K20_s5_hold | +23.1% | +9.3% | 1.29 | 0.43 | vol_20 +0.89 (+9.0), mom_12_1 -0.49 (-2.9), log_turn20 +0.16 (+1.4), mom_5 -0.29 (-1.4), beta_60 -0.12 (-1.1), dist_sma200 +0.66 (+3.8) |
| h20_neu_T50_K20_s5_hold | -4.5% | +3.1% | 0.36 | 0.38 | vol_20 +0.14 (+0.9), mom_12_1 +0.34 (+2.1), log_turn20 +0.69 (+5.4), mom_5 -0.18 (-1.2), beta_60 -0.26 (-2.6), dist_sma200 -0.73 (-8.1) |
| h20_neu_B30_K20_s5_hold | -11.9% | -4.6% | -0.56 | 0.62 | vol_20 -0.34 (-3.0), mom_12_1 +0.55 (+2.6), log_turn20 +0.64 (+4.1), mom_5 +0.02 (+0.1), beta_60 -0.16 (-1.6), dist_sma200 -0.58 (-2.9) |
| h20_neumom_T30_K20_s5_hold | +13.9% | +1.8% | 0.31 | 0.35 | vol_20 +0.85 (+7.4), mom_12_1 -0.14 (-0.8), log_turn20 +0.17 (+1.6), mom_5 -0.32 (-1.5), beta_60 -0.37 (-4.0), dist_sma200 +0.24 (+1.2) |
| h20_neumom_C20_K20_s5_hold | +14.4% | +9.0% | 1.04 | 0.34 | vol_20 +0.62 (+4.1), mom_12_1 +0.29 (+1.9), log_turn20 +0.20 (+1.4), mom_5 -0.29 (-1.5), beta_60 -0.36 (-3.0), dist_sma200 -0.50 (-3.1) |
| h20_neu_RANK_avoid30_s5_hold | +0.7% | +2.1% | 2.76 | 0.71 | vol_20 -0.06 (-2.8), mom_12_1 +0.06 (+3.5), log_turn20 +0.08 (+4.7), mom_5 +0.01 (+0.4), beta_60 -0.04 (-2.8), dist_sma200 -0.06 (-4.5) |
| h20_neumom_RANK_avoid30_s5_hold | +1.5% | +2.5% | 3.73 | 0.71 | vol_20 -0.06 (-6.1), mom_12_1 +0.08 (+3.5), log_turn20 +0.07 (+4.6), mom_5 -0.01 (-0.6), beta_60 -0.03 (-3.7), dist_sma200 -0.07 (-3.7) |
| h20_neu_T30_avoid30_s5_hold | +5.8% | +2.8% | 2.75 | 0.63 | vol_20 +0.09 (+5.1), mom_12_1 +0.04 (+2.3), log_turn20 +0.01 (+1.2), mom_5 -0.03 (-1.2), beta_60 +0.00 (+0.2), dist_sma200 +0.03 (+2.1) |
| h20_neu_B30_avoid30_s5_hold | -2.1% | +1.5% | 2.23 | 0.87 | vol_20 -0.15 (-11.4), mom_12_1 +0.05 (+2.8), log_turn20 +0.08 (+5.5), mom_5 +0.02 (+1.1), beta_60 -0.02 (-2.2), dist_sma200 -0.09 (-5.4) |
| h20_neumom_T30_avoid30_s5_hold | +5.9% | +2.6% | 3.33 | 0.64 | vol_20 +0.09 (+6.3), mom_12_1 +0.05 (+2.3), log_turn20 +0.01 (+0.9), mom_5 -0.05 (-2.0), beta_60 -0.00 (-0.5), dist_sma200 +0.02 (+1.3) |
| h20_neumom_C20_avoid30_s5_hold | +1.1% | +1.7% | 2.23 | 0.62 | vol_20 -0.07 (-5.0), mom_12_1 +0.07 (+4.0), log_turn20 +0.05 (+3.1), mom_5 -0.03 (-1.8), beta_60 -0.02 (-1.4), dist_sma200 -0.06 (-3.6) |

Single-characteristic reference sorts (not candidates; same Sim, excess vs random):

| characteristic sort (h=20, 50bp) | long top-20 step 5: dev (t) / 2026 (t) | long top-20 step 10 | avoid: drop the 30% with the LOWEST score (e.g. high_vol20 drops low-vol names), step 5 |
|---|---|---|---|
| dist_sma200 | -15.9% (-1.78) / +55.6% (2.13) | -17.6% (-1.97) / +63.2% (2.38) | +2.6% (1.99) / +3.1% (0.94) |
| high_idio60 | -21.2% (-2.81) / -2.7% (-0.09) | -20.8% (-2.55) / -3.5% (-0.13) | +0.2% (0.42) / +5.4% (2.06) |
| high_vol20 | -19.0% (-2.30) / -3.0% (-0.06) | -22.0% (-2.38) / -5.3% (-0.16) | +0.5% (0.66) / +3.9% (1.64) |
| liquid_turn20 | +1.6% (0.16) / -20.3% (-1.83) | -2.9% (-0.44) / -20.0% (-1.77) | +1.6% (1.34) / -1.1% (-0.73) |
| low_beta60 | -10.4% (-2.05) / -7.4% (-0.49) | -12.4% (-2.29) / -7.6% (-0.45) | +0.8% (0.22) / -2.2% (-0.88) |
| low_idio60 | -2.6% (-0.55) / -16.6% (-1.82) | -5.5% (-0.95) / -15.7% (-1.78) | +0.8% (0.33) / -3.6% (-1.89) |
| low_vol20 | -2.0% (-0.54) / -20.2% (-1.94) | -4.1% (-0.83) / -18.5% (-1.84) | +0.7% (0.26) / -3.4% (-1.74) |
| mom_12_1 | +11.5% (1.62) / +39.0% (2.29) | +11.5% (1.59) / +44.0% (2.46) | +3.7% (3.14) / +5.4% (2.07) |
| rev_5d | -9.1% (-2.28) / +4.3% (0.60) | -6.1% (-1.10) / +5.2% (0.61) | +0.6% (0.98) / +0.2% (0.25) |
| xr_mom60 | -14.2% (-1.63) / +36.0% (1.49) | -17.4% (-1.91) / +45.8% (2.01) | +0.5% (0.46) / +2.5% (0.97) |


* **Not a boring factor tilt on the long side.** neumom RANK's DEV alpha after six long-short factors
  (vol, 12-1 momentum, liquidity, 5d reversal, beta, distance to 200dma) is +17.4%/yr (t 3.99, R2 0.05).
  The best single-characteristic sort gets +11.5% (12-1 momentum, t 1.62). Low-vol, liquidity and
  reversal sorts lose to random on DEV. Tail-binary forms carry real factor exposure: T30 R2 0.30 (vol
  beta 0.47), T10 R2 0.39.
* **2026 was a factor storm.** Annualised long-short returns: momentum +26%, distance to 200dma +18%, vol
  +18%, beta +10%, liquidity -5%. The neutral scores are short trend (dist_sma200 beta -0.51 for neumom
  RANK, -0.74 for neu RANK) and long liquidity, so their raw 2026 excess (+8.9% neumom RANK) understates
  the factor-adjusted alpha (+11.6%, t 1.78).
* **The avoid side is partly replicable by a boring rule on DEV.** Dropping the worst 30% by 12-1
  momentum earns +3.7% (t 3.14), about the same as the model avoid overlays (+3.3..+3.8%, t 2.7-3.5). In
  2026 the momentum rule did better (+5.4%, t 2.07 vs +0.9..+1.8%). The model avoid overlays still carry
  significant factor-adjusted alpha in both periods (+2.5..+3.1%/yr, t 3.7-5.0 for neumom), so they are
  not just momentum. A momentum filter plus the model's avoid list is an obvious R2_alpha ensemble
  candidate.


## 9. Selection on DEV and the holdout exam

Rule (fixed before the last six models - T20, T10, T50, neumom T30, neumom C20, h15 T30 - were trained; DEV data only; h=20 because DEV net CAGR at 80 and 130 bps is highest at h=20 for every model family, Section 6a): rank each h=20 candidate on 7 DEV-only criteria (S.compare t, phase-averaged t at step 5 and 10, mean t over the K x step grid, factor-adjusted alpha t, avoid-overlay phase-averaged t, IC t on the common XR_neu20 yardstick) and take the best mean rank. Constraints shown: DEV CAGR at 80 bps and worst DEV-year excess.

| model (h=20) | S.compare t K20 s5 | phase-avg t K20 s5 | phase-avg t K20 s10 | mean t over K x step grid | factor-alpha t | avoid30 phase-avg t | IC t vs XR_neu20 | dev CAGR 80bp | worst dev-year excess | mean rank (lower=better) |
|---|---|---|---|---|---|---|---|---|---|---|
| h20_neumom_RANK | 4.25 | 4.11 | 4.43 | 3.90 | 3.99 | 3.58 | 8.62 | 26.2% | +5.9% | 2.9 |
| h20_neumom_C20 | 3.69 | 5.07 | 5.45 | 3.48 | 4.02 | 3.23 | 7.26 | 25.4% | +3.4% | 3.3 |
| h20_neumom_T30 | 3.82 | 4.57 | 4.81 | 3.69 | 4.15 | 4.87 | 3.52 | 26.1% | +8.8% | 3.6 |
| h20_neu_C20 | 3.86 | 4.87 | 5.32 | 3.77 | 3.65 | 2.75 | 5.83 | 26.0% | +5.0% | 4.4 |
| h20_neu_T30 | 3.30 | 4.26 | 4.53 | 3.00 | 3.06 | 4.49 | 2.96 | 25.2% | +8.7% | 6.0 |
| h20_neu_RANK | 3.75 | 3.81 | 4.14 | 3.21 | 3.11 | 2.99 | 6.16 | 25.2% | +8.1% | 6.3 |
| h20_neu_C33 | 2.97 | 3.30 | 3.65 | 2.64 | 2.23 | 3.12 | 6.69 | 21.5% | +12.6% | 7.9 |
| h20_none_RANK | 2.85 | 3.27 | 3.42 | 2.58 | 2.29 | 3.65 | 5.43 | 20.7% | +7.8% | 8.4 |
| h20_neu_C30 | 2.57 | 3.61 | 3.92 | 2.35 | 1.98 | 2.95 | 6.49 | 20.3% | +11.3% | 9.1 |
| h20_neu_T20 | 2.68 | 3.39 | 3.55 | 2.58 | 3.25 | 2.67 | 1.17 | 23.7% | -0.3% | 9.6 |
| h20_size_RANK | 2.65 | 2.90 | 3.06 | 2.65 | 1.88 | 3.51 | 5.23 | 18.2% | +8.0% | 9.9 |
| h20_neu_T10 | 2.56 | 3.01 | 3.16 | 2.81 | 3.13 | 1.54 | -0.70 | 23.3% | +3.8% | 10.6 |
| h20_neu_T50 | 0.67 | 1.23 | 1.32 | 0.80 | 0.27 | 3.45 | 6.61 | 11.7% | -3.0% | 11.0 |
| h20_neu_B30 | 0.06 | 0.09 | 0.11 | 0.17 | 0.37 | 1.28 | 7.84 | 9.4% | -10.6% | 12.1 |


**Holdout exam of the leading DEV candidates (2026 shown for information only; the choice was made
above on DEV):**

| model | dev CAGR 50bp | dev CAGR 80bp | dev phase-avg CAGR vs random | dev phase-avg excess (t) | dev avoid30 phase-avg (t) | 2026 CAGR 50bp | 2026 CAGR 80bp | 2026 phase-avg CAGR vs random | 2026 phase-avg excess (t) | 2026 avoid30 phase-avg (t) | 2026 factor alpha (t) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| h20_neumom_RANK | 30.9% | 26.2% | 30.7% vs 12.0% | +15.8% (4.11) | +3.4% (3.58) | 16.0% | 12.1% | 13.9% vs 10.2% | +3.9% (0.60) | +1.2% (0.84) | +11.6% (1.78) |
| h20_neumom_C20 | 30.1% | 25.4% | 34.1% vs 12.0% | +18.5% (5.07) | +3.0% (3.23) | 22.2% | 18.1% | 19.7% vs 10.2% | +8.9% (1.32) | +1.0% (0.75) | +9.0% (1.04) |
| h20_neumom_T30 | 30.8% | 26.1% | 35.1% vs 12.0% | +19.6% (4.57) | +3.4% (4.87) | 21.8% | 17.7% | 23.0% vs 10.2% | +11.6% (2.14) | +6.3% (6.20) | +1.8% (0.31) |
| h20_neu_C20 | 30.7% | 26.0% | 33.6% vs 12.0% | +18.1% (4.87) | +2.9% (2.75) | 19.0% | 15.0% | 21.3% vs 10.2% | +10.2% (1.66) | +0.8% (0.52) | +10.7% (1.28) |
| h20_neu_T30 | 29.9% | 25.2% | 34.7% vs 12.0% | +19.4% (4.26) | +3.1% (4.49) | 27.9% | 23.6% | 27.0% vs 10.2% | +14.9% (2.45) | +6.1% (5.93) | +7.9% (1.12) |
| h20_neu_RANK | 29.8% | 25.2% | 29.8% vs 12.0% | +15.2% (3.81) | +3.1% (2.99) | 10.1% | 6.4% | 13.2% vs 10.2% | +3.3% (0.44) | +0.6% (0.38) | +7.7% (0.80) |
| h20_none_RANK | 25.2% | 20.7% | 27.5% vs 12.0% | +13.8% (3.27) | +3.3% (3.65) | 3.9% | 0.4% | 1.9% vs 10.2% | -7.7% (-0.91) | +0.5% (0.31) | +8.0% (1.42) |

* **Selected label (DEV): XR_neumom, h=20, continuous per-date residual rank (RANK)**, trained as a
  LightGBM regression on pct-0.5. 2026 net of 50 bps: 13.9% phase-averaged CAGR vs 10.2% random.
  Phase-averaged excess +3.9% (t 0.60), factor alpha +11.6% (t 1.78), 98th percentile of the
  persistence-matched null. That is a pass in sign and a weak pass in strength.
* **The top three DEV candidates (neumom RANK, neumom C20, neumom T30) are a statistical tie**: mean
  ranks 2.9 / 3.3 / 3.6, with DEV differences of under 1 t-unit. **What is robust is the neutraliser
  (neumom) and the horizon (20d), not the exact label form.** Do not read the 2026 ordering (T30 > C20 >
  RANK) as evidence for tail forms. It follows the high-vol rally and the T30 factor alpha is about 0.
* Recommended label stack from this study:
  1. **Primary selection label:** y = per-date percentile rank of the OLS residual of winsorised
     open[t+1]->close[t+20] on [0.5*clip(beta_60,0,3)+0.5, vol_20, log_turn20, mom_12_1] over elig_base. Train on
     the continuous rank. An equal-weight rank ensemble of RANK / C20 / T30 models trained on this same
     residual is the natural next step (R2_alpha).
  2. **Avoid label:** the bottom tail of the SAME score. Drop the worst 10-30%; the 10% cut was the most
     robust in 2026, t 1.84. Do NOT train a dedicated bottom-30% classifier (B30): it learns volatility.
  3. **Execution:** K=20 (10-30 is a plateau), 20-day hold, stagger entries daily or weekly (phase risk),
     liq2 universe, cost stress at 80 and 130 bps. Expect roughly random +4..+16%/yr (2026 to DEV) at
     about random-like drawdowns.


## 10. Pros, cons, failure modes


**Pros (XR_neumom h=20 RANK)**
* The event rate is fixed by construction (30/40/30 or any chosen cut) in every year, regime and month,
  with no market encoding (corr with the Nifty month about 0).
* Its composition does not depend on market direction (beta-tilt corr 0.06). Its factor R2 is low (0.05)
  and its DEV factor-alpha t is near the top (3.99; neumom C20 4.02, neumom T30 4.15).
* It is the most reliably learnable of the h=20 models (DEV IC t 8.6 on the common yardstick), with no
  IC decay in 2026 (0.061).
* Every DEV year is positive (+18.3 / +35.8 / +5.9% vs random for 2023/24/25). It is robust to K 10-50,
  step 5/10, costs of 50-130 bps and liq5.
* It passes every bias check: next-open entry, NaN where undefined, CA-adjusted, segment/suspension
  guards, labels independent of eligibility filters, walk-forward OOS only, and selection on DEV only.

**Cons and failure modes**
* The 2026 edge is small once phase luck is removed (+3.9%/yr, t 0.60). The +9.2% single-phase figure is
  the luckiest of 5 calendar phases.
* Long-side skill is weak (2026 top-30% AUC 0.508). The book makes money mostly by not holding the
  losers.
* It is structurally short trend and long liquidity, so it lags in momentum/high-vol rallies such as
  2026, where vol-loaded tail forms and plain 12-1 momentum did much better.
* It does not reduce absolute drawdowns (DEV maxDD -25.6% vs random -30%). A +1 label still loses money
  in up to 62% of cases in a bad month (h=20).
* Capacity: median pick turnover is Rs 24 cr/day. At a Rs 25 cr book, 8.5% of tickets exceed 10% of ADV.
  The edge is larger in liq2 than in liq5.
* Multiple testing: 477 distinct DEV specs plus about 600 in round 1. The best DEV t (4.25) clears
  Bonferroni (3.71 / 3.91) only narrowly, and the choice among the top-3 forms is at noise level.
* Shorts were not evaluated in round 2. Round 1 found single-stock F&O shorts lose; use -1 as avoid/exit
  only. On F&O names the -1 class is under-represented (25.5% vs 30%).


## 11. Lab issues found


1. **Calendar-phase sensitivity of single-run `S.compare` results.** The signal calendar trades only 1 of
   `step` possible phases. For neu RANK at K20 step 10, the 2026 excess ranges from -12.4% to +15.4%
   across the 10 phases, and the default phase is the best one. For the selected model at step 5 the
   default phase was also the best of 5 (+9.2% vs a phase-average of +3.9%). Recommendation: report the
   phase-averaged book (`s7_phase.py`) for every holdout claim. It is equivalent to daily-staggered entries.
2. **Newey-West t is miscalibrated for persistent tilts.** Constant per-stock random scores give NW t sd
   1.37 (DEV) and 1.54 (2026), with a max of 3.9 in 40 draws. Use a persistence-matched null
   (`s6b_matched_null.py`, sd 1.03-1.10) or block-bootstrap the excess before reading a t of 3 as
   significant.
3. **Round-trip cost on re-picked names.** `Sim` charges a full round trip on every name at every sleeve
   rebalance. For top-20 books the measured 20-day name retention is only 8-10%, so this is about right.
   For the avoid/EW books (70-100% of the universe) most names are retained in reality, so their absolute
   CAGRs are understated by up to about 6%/yr at 50 bps. Excess vs random-70% is unaffected because both
   legs pay.
4. **Score-NaN asymmetry in `Sim.run`.** The strategy draws from finite-score rows and the random
   baseline from all mask rows. This is harmless for `walk_forward2` scores (all elig rows scored). For
   characteristic sorts with NaN (mom_12_1 is NaN on 11.8% of elig rows, the young names) the baseline
   universe differs.
5. **`xs_metrics` has no down-side AUC.** The avoid side needs the score inverted and a bottom-class binary
   target (done here in `s4_xs.py`). Suggest adding `auc_down` to lablib.
6. **Sub-universe class shares.** A rank label built on the full elig cross-section is 29.5/45/25.5 inside
   fno_proxy, not 30/40/30. Re-rank inside the traded universe if the label is used as a target there.
7. **Survivorship conditioning of the ranking cross-section.** V_h needs a defined r_h, so 1.0% / 1.6% /
   2.1% of elig rows (h=10/15/20) that hit a suspension, segment break or label_block inside the window are
   NaN and excluded from that date's ranking. This is correct as a label. Sim handles these names with
   forced exits, so the investability numbers are not survivorship-biased.


## 12. Files

Scripts `s1_labels.py` (targets) `s2_events.py` (event rates) `s3_wf.py` (walk_forward2) `s4_xs.py` (IC/AUC) `s5_sim.py` (S.compare grids, cached random bands in `rb_cache/`) `s6_nulls.py` / `s6b_matched_null.py` (luck bands, reference sorts, cross-horizon) `s7_phase.py` (phase robustness) `s8_loadings.py` `s9_attrib.py` (factor attribution) `s11_precision.py` `s12_impl.py` `report_tables.py` + `s10_report.py` (this report). Arrays: `labels_h{10,15,20}.npz` (r, rw, market window, EW mean, res_*/pct_* per neutraliser), `wf_<tag>.npz` (OOS scores), `daily_*.npz` (daily returns of 50 bps configs). All numbers: `results.json`.
