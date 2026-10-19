# R2_event: capitulation-reversal event sleeve (lab v2)

Agent R2_event, round 2. Lab v2 only: no sector data, ETFs excluded, `elig_base` as rebuilt. Entry at open[t+1] and time exit at close[t+h]. Labels are NaN unless `fw.ok(h)`, and event gates choose sample rows without changing label values. Models use `L.walk_forward2`, investability uses `L.Sim` (bit-identical copy `SimX` that also returns the daily invested fraction), and learnability uses `L.xs_metrics` plus month-cluster t. Costs are 50 bps (80 and 130 bps stress). Selection is on DEV only: signals 2023-01-01 to the last date whose exit is on or before 2025-12-31. The 2026 holdout (to 2026-10-14) is reported separately and never used to choose. PRE (2021-22) is shown for information only.

## 1. Headline

* **The capitulation reversal is real on lab v2, but it is a market-breadth effect, not a stock effect.** The round-1 gate R1dn is close < prior 20-day low, volz_20 > 1, Nifty-500 20d momentum < 0. At h=10 it has DEV excess of +57 bps per event versus the same-date universe mean (month-cluster t 6.22). That passes Bonferroni over all 720 event tests in this study (|z| > 3.98). Weighting each event *day* equally, the excess is only +16 bps (t 0.72). The edge lives on mass-breakdown days. On days when fewer than 2% of the universe make new 20-day lows, R1dn events earn -20 bps (DEV) and -112 bps (2026). On days when 20% or more do, they earn +82 / +97 bps.
* **Adding a breadth gate turns it into a tradable event label.** The gate requires at least 5% of eligible names at new 20-day lows in a falling market. The selected gate A1 (`R1|L10|v0|mom20dn_brd5`) was chosen by a pre-declared DEV rule: maximise the date-weighted t. At h=10 it has DEV excess +38 bps (t 4.35), date-weighted +36 bps (t 4.36); both pass Bonferroni. The 2026 holdout is +64 bps (t 2.57). It fires on 16% of DEV days with about 133 names per event day. There were 56 washout episodes in 2021-26.
* **As a sleeve (L.Sim, daily signal calendar, 20 slots per daily sleeve, idle cash at 0%) the edge is small in absolute terms because capital is idle about 85% of the time.** A1, all events, h=10: DEV CAGR 4.3% at 50 bps against 2.9% for a count-matched random-stock sleeve on the same days. Ranking the events with a walk-forward meta-model (relative target) and buying the top 20 gives DEV CAGR 10.4% (h=5), Sharpe 1.35, maxDD -9.6%, at 13% exposure. That is 4.4%/yr over all events (NW t 4.09) and 7.0%/yr over matched random (t 4.70).
* **2026 holdout (not used for selection):** the edge over baselines survives but absolute returns depend on the horizon. The DEV-selected h=5 meta sleeve made 0.4% against -9.2% for matched random (excess t 2.87). The h=10 version made 7.0% against 2.5% (t 1.52). Nifty 500 returned -9.9% annualised over the same window. 2026 washouts kept falling for weeks before rebounding, so 5-day holds sold too early.
* **It does not improve the relative core book.** The core is R2_rel's h20_neumom_RANK, top-20: DEV CAGR 30.9%, 2026 16.0%. Parking the sleeve's idle capital in the core (overlay, 20%) gives DEV 30.6% and 2026 13.8%, both below the core. A tilt of the core toward gate events also loses (-1.0%/yr DEV). The core already holds 25% gate events on gate days, against a 13% base rate. When the sleeve is active, its daily correlation with the core is 0.78, because both are long a falling market.
* **Other overreaction events (Bonferroni over 720 tests):** none gives an investable long edge. Large down days and recovered gap-downs *continue* when the market is quiet: quiet-day crash (Q_CR k3) has DEV excess -184 bps at h=10 (t -4.99), and all-day crashes have day-weighted excess of -90 to -136 bps (t -4.1 to -5.5). The continuation faded in 2026 (Q_CR k3 -28 bps, t -0.26), and an avoid filter built on it did not help the core in DEV. Oversold names (RSI < 20) in a falling market pass Bonferroni at h=5 as events but lose as a sleeve in 2026. 5-day cross-sectional losers and 52-week lows on volume show no edge.
* **Verdict.** The breadth-gated capitulation label is **promising** as an *event sleeve for capital that is not already in the core book*, for example the cash buffer of a client who runs below 100% gross. It is **not** promising as an add-on to a fully invested relative book. Use it as a descriptive regime fact: buy washouts, not isolated breakdowns. Variants tried: 538 (360 event-study cells x 2 statistics = 720 tests; 176 distinct DEV portfolio specs; 2 new walk-forward models plus 2 reused from R2_rel).

## 2. Definitions

```
U        = elig_base (lab v2)                                    r_h = open[t+1] -> close[t+h], NaN unless fw.ok(h)
x_h      = r_h - mean_U,same date(r_h)   (date-matched excess; removes market timing)
brd_t    = share of U rows with close[t] < min(low[t-20..t-1])  (new-20d-low breadth, PIT at close t)
R1(L,v,M)= U & close[t] < min(low[t-L..t-1]) & volz_20 > v & market filter M
           M in {none, mkt_mom20<0 (mom20dn), mkt_dist_sma200<0 (sma200dn), brd>=5%, brd>=10%, mom20dn & brd>=5%}
ANCHOR   = R1(20, 1, mom20dn)        (round-1 R1dn)
A1 (SEL) = R1(10, 0, mom20dn & brd>=5%)   (DEV-selected: max date-weighted DEV t at h=10 among cells with >=500 events)
Event label: on event rows, +1 if r_h > 50 bps (net positive) else -1 (absolute); relative view +1 if x_h > 0.
Sleeve   = L.Sim step=1 (h daily sleeves, each 1/h of capital), top_k=20 slots/sleeve (slot = 1/(20h)), idle cash 0%;
           'all events' = random tie-break among the day's events (5 seeds) = S.compare's same-mask random arm;
           'matched'    = count-matched universe random: each day as many random U names as the sleeve holds events.
```

Baselines. `S.compare` draws its random arm from the *same mask*, so on an event mask it measures only the ranking *within* events. The event effect itself is measured against the **count-matched universe random** sleeve: same days, same number of names, same exposure, random stocks. Both are reported, with NW t at lag h and month-cluster t.

## 3. Re-validation of R1dn on lab v2 (event study, no model)

Table 3.1: ANCHOR R1dn and selected A1 by horizon. 'ew' weights each event equally; 'dw' weights each event day equally (closer to a slot-sized sleeve). t uses month clusters.
| gate | h | window | events | % days | events/event-day | P(net50>0) | net50 bps | xs ew bps (t) | xs dw bps (t) | xs t (qtr clusters) |
|---|---|---|---|---|---|---|---|---|---|---|
| ANCHOR | 5 | dev | 6729 | 35% | 26 | 0.579 | +157 | +40 (3.52) | +5 (0.32) | 4.62 |
|  |  | hold | 3095 | 47% | 34 | 0.454 | +30 | +29 (0.68) | -23 (-0.84) | 1.97 |
|  |  | pre | 2417 | 37% | 17 | 0.535 | +61 | +24 (1.31) | +1 (0.04) | 1.48 |
| ANCHOR | 10 | dev | 6673 | 35% | 26 | 0.561 | +174 | +57 (6.22) | +16 (0.72) | 6.50 |
|  |  | hold | 2950 | 44% | 34 | 0.531 | +250 | +76 (1.66) | -21 (-0.54) | 2.60 |
|  |  | pre | 2417 | 37% | 17 | 0.558 | +98 | +22 (0.90) | +31 (0.74) | 0.92 |
| ANCHOR | 20 | dev | 6506 | 35% | 26 | 0.550 | +227 | +62 (3.68) | +25 (0.66) | 4.11 |
|  |  | hold | 2705 | 39% | 36 | 0.662 | +654 | +107 (2.33) | +5 (0.10) | 3.15 |
|  |  | pre | 2415 | 37% | 17 | 0.540 | +156 | +15 (0.26) | +41 (0.66) | 0.39 |
| A1 | 5 | dev | 15902 | 16% | 131 | 0.608 | +179 | +34 (4.76) | +31 (4.45) | 7.30 |
|  |  | hold | 7439 | 27% | 140 | 0.445 | +3 | +30 (1.47) | +33 (1.93) | 2.73 |
|  |  | pre | 6959 | 15% | 120 | 0.548 | +84 | +35 (2.78) | +29 (1.86) | 2.55 |
| A1 | 10 | dev | 15788 | 16% | 133 | 0.580 | +207 | +38 (4.35) | +36 (4.36) | 4.11 |
|  |  | hold | 7002 | 25% | 143 | 0.502 | +163 | +64 (2.57) | +45 (2.32) | 2.29 |
|  |  | pre | 6959 | 15% | 120 | 0.580 | +148 | +30 (2.90) | +31 (2.39) | 3.48 |
| A1 | 20 | dev | 15427 | 16% | 132 | 0.551 | +232 | +34 (2.32) | +31 (1.99) | 2.34 |
|  |  | hold | 6483 | 23% | 147 | 0.619 | +532 | +92 (3.88) | +64 (2.74) | 2.86 |
|  |  | pre | 6953 | 15% | 120 | 0.553 | +211 | +32 (1.20) | +35 (1.12) | 1.41 |

Table 3.2: by calendar year, h=10 (2021-22 = PRE, 2023-25 = DEV, 2026 = holdout).
| gate | year | events | event days | P(net50>0) | net50 bps | xs bps |
|---|---|---|---|---|---|---|
| ANCHOR | 2021 | 297 | 32 | 0.593 | +206 | +58 |
| ANCHOR | 2022 | 2120 | 108 | 0.553 | +83 | +17 |
| ANCHOR | 2023 | 1601 | 98 | 0.555 | +142 | +58 |
| ANCHOR | 2024 | 1997 | 70 | 0.717 | +529 | +52 |
| ANCHOR | 2025 | 3196 | 96 | 0.467 | -33 | +65 |
| ANCHOR | 2026 | 2950 | 86 | 0.531 | +250 | +76 |
| A1 | 2021 | 1219 | 9 | 0.667 | +290 | +5 |
| A1 | 2022 | 5740 | 49 | 0.561 | +117 | +36 |
| A1 | 2023 | 3172 | 35 | 0.596 | +215 | +67 |
| A1 | 2024 | 5463 | 37 | 0.726 | +512 | +29 |
| A1 | 2025 | 7392 | 51 | 0.462 | -29 | +31 |
| A1 | 2026 | 7002 | 49 | 0.502 | +163 | +64 |

Table 3.3: mass-day dependence for ANCHOR (h=10). Buckets are by the number of R1dn events that day, and by brd (share of U at new 20d lows).
| bucket by | window | bucket | events | days | P(net50>0) | net50 bps | xs bps |
|---|---|---|---|---|---|---|---|
| count | dev | 1-2 | 21 | 14 | 0.429 | -112 | -255 |
| count | dev | 3-9 | 503 | 88 | 0.400 | -164 | +2 |
| count | dev | 10-29 | 1740 | 97 | 0.518 | +50 | +28 |
| count | dev | 30-99 | 2457 | 46 | 0.538 | +110 | +75 |
| count | dev | 100-inf | 1952 | 12 | 0.673 | +455 | +80 |
| count | hold | 1-2 | 4 | 3 | 0.500 | -232 | -757 |
| count | hold | 3-9 | 115 | 19 | 0.513 | +100 | -56 |
| count | hold | 10-29 | 672 | 38 | 0.479 | +51 | -12 |
| count | hold | 30-99 | 1192 | 20 | 0.324 | -231 | +18 |
| count | hold | 100-inf | 967 | 6 | 0.824 | +1001 | +228 |
| brd | dev | 0.00-0.02 | 318 | 67 | 0.384 | -212 | -20 |
| brd | dev | 0.02-0.05 | 778 | 71 | 0.472 | -7 | +25 |
| brd | dev | 0.05-0.10 | 920 | 47 | 0.507 | +51 | +42 |
| brd | dev | 0.10-0.20 | 1135 | 35 | 0.565 | +106 | +37 |
| brd | dev | 0.20-1.01 | 3522 | 37 | 0.610 | +303 | +82 |
| brd | hold | 0.00-0.02 | 114 | 19 | 0.579 | +160 | -112 |
| brd | hold | 0.02-0.05 | 262 | 18 | 0.412 | -42 | -35 |
| brd | hold | 0.05-0.10 | 419 | 20 | 0.425 | -22 | +19 |
| brd | hold | 0.10-0.20 | 629 | 15 | 0.568 | +398 | +145 |
| brd | hold | 0.20-1.01 | 1526 | 14 | 0.562 | +321 | +97 |

Isolated breakdowns continue down. The reversal is a *market* washout phenomenon. Excess rises with breadth from the lowest to the highest bucket: DEV -20 to +82 bps, 2026 -112 to +97/+145 bps. It is not strictly monotone in the middle buckets. This is why the breadth gate, not the volume or lookback threshold, is the parameter that matters.

Table 3.4: month concentration of the excess (h=10).
| gate | window | months w/ events | share months xs>0 | top1 share xs | top3 | top5 | top5 share net | top5 share events | xs excl top1 | excl top3 | excl top5 | leave-one-month-out min | eff. # months |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| ANCHOR | dev | 26 | 0.69 | 0.15 | 0.41 | 0.60 | 0.94 | 0.47 | +52 | +48 | +44 | +52 | 11.6 |
| ANCHOR | hold | 9 | 0.67 | 0.92 | 1.10 | 1.15 | 1.14 | 0.90 | +10 | -28 | -108 | +10 | 1.5 |
| A1 | dev | 22 | 0.82 | 0.18 | 0.41 | 0.58 | 0.88 | 0.36 | +33 | +31 | +25 | +33 | 11.3 |
| A1 | hold | 8 | 0.50 | 0.69 | 1.03 | 1.03 | 1.19 | 0.79 | +33 | -6 | -9 | +33 | 1.9 |

ANCHOR's top DEV months: 2023-03 (422 events, +141 bps, 15% of xs), 2025-01 (1021 events, +56 bps, 15% of xs), 2024-10 (503 events, +81 bps, 11% of xs), 2025-02 (821 events, +48 bps, 10% of xs), 2023-02 (352 events, +89 bps, 8% of xs).
In 2026, ANCHOR's excess is one month (top1 share 0.92; excluding it +10 bps). A1 is less concentrated (top1 0.69; excluding it +33 bps). Washout episodes (runs of days with brd >= 10%): 56 in 2021-26, by start year {'2021': 6, '2022': 10, '2023': 7, '2024': 12, '2025': 13, '2026': 8}.

## 4. Parameter sensitivity: how event rates and the edge move (h=10 unless noted)

Table 4.1: volume threshold (L=20, M=mom20dn).
| variant | DEV events | events/yr | % DEV days | events/event-day | P(net50>0) | net50 bps | xs ew (t) | xs dw (t) | 2026 xs (t) | 2026 events |
|---|---|---|---|---|---|---|---|---|---|---|
| vnone | 23780 | 7927 | 35% | 92 | 0.529 | +103 | +15 (2.00) | +1 (0.07) | +43 (1.83) | 10360 |
| v0 | 15365 | 5122 | 35% | 60 | 0.552 | +148 | +31 (3.72) | +12 (0.77) | +63 (2.28) | 6780 |
| v0.5 | 10670 | 3557 | 35% | 41 | 0.559 | +167 | +43 (5.32) | +2 (0.12) | +76 (2.34) | 4712 |
| v1 | 6673 | 2224 | 35% | 26 | 0.561 | +174 | +57 (6.22) | +16 (0.72) | +76 (1.66) | 2950 |
| v2 | 2304 | 768 | 33% | 9 | 0.530 | +102 | +47 (2.65) | +11 (0.33) | +20 (0.62) | 985 |

Table 4.2: lookback (v=1, M=mom20dn).
| variant | DEV events | events/yr | % DEV days | events/event-day | P(net50>0) | net50 bps | xs ew (t) | xs dw (t) | 2026 xs (t) | 2026 events |
|---|---|---|---|---|---|---|---|---|---|---|
| L10 | 7555 | 2518 | 35% | 29 | 0.569 | +188 | +52 (5.80) | +14 (0.67) | +67 (1.48) | 3237 |
| L20 | 6673 | 2224 | 35% | 26 | 0.561 | +174 | +57 (6.22) | +16 (0.72) | +76 (1.66) | 2950 |
| L40 | 5521 | 1840 | 35% | 22 | 0.566 | +176 | +57 (4.94) | +20 (0.79) | +98 (1.79) | 2405 |

Table 4.3: market filter (L=20, v=1).
| variant | DEV events | events/yr | % DEV days | events/event-day | P(net50>0) | net50 bps | xs ew (t) | xs dw (t) | 2026 xs (t) | 2026 events |
|---|---|---|---|---|---|---|---|---|---|---|
| none | 10658 | 3553 | 95% | 15 | 0.525 | +110 | +35 (2.38) | -19 (-1.16) | +56 (1.30) | 3968 |
| mom20dn | 6673 | 2224 | 35% | 26 | 0.561 | +174 | +57 (6.22) | +16 (0.72) | +76 (1.66) | 2950 |
| sma200dn | 3040 | 1013 | 16% | 26 | 0.512 | +81 | +79 (5.04) | +47 (1.19) | +107 (2.88) | 2616 |
| brd5 | 7304 | 2435 | 25% | 39 | 0.555 | +175 | +62 (4.19) | +51 (2.89) | +86 (1.99) | 2979 |
| brd10 | 5586 | 1862 | 13% | 58 | 0.570 | +207 | +66 (4.31) | +63 (3.58) | +110 (2.63) | 2322 |
| mom20dn_brd5 | 5577 | 1859 | 16% | 47 | 0.584 | +221 | +66 (5.54) | +51 (2.83) | +96 (2.11) | 2574 |

Table 4.4: market filter (L=10, v=0; the selected cell is mom20dn_brd5).
| variant | DEV events | events/yr | % DEV days | events/event-day | P(net50>0) | net50 bps | xs ew (t) | xs dw (t) | 2026 xs (t) | 2026 events |
|---|---|---|---|---|---|---|---|---|---|---|
| none | 32729 | 10910 | 98% | 45 | 0.522 | +109 | +17 (2.09) | -7 (-0.56) | +35 (1.34) | 11167 |
| mom20dn | 18457 | 6152 | 35% | 72 | 0.562 | +170 | +35 (4.70) | +14 (0.93) | +51 (1.86) | 7852 |
| sma200dn | 8432 | 2811 | 16% | 70 | 0.526 | +121 | +44 (2.81) | +51 (2.46) | +69 (2.51) | 7196 |
| brd5 | 22025 | 7342 | 25% | 119 | 0.545 | +151 | +32 (4.03) | +31 (3.42) | +52 (2.10) | 8360 |
| brd10 | 16880 | 5627 | 13% | 176 | 0.558 | +177 | +33 (3.53) | +34 (3.36) | +69 (3.19) | 6367 |
| mom20dn_brd5 | 15788 | 5263 | 16% | 133 | 0.580 | +207 | +38 (4.35) | +36 (4.36) | +64 (2.57) | 7002 |

Table 4.5: plateau map. DEV date-weighted xs t at h=10 for every lookback x volume cell under three market filters (2026 date-weighted xs bps in brackets).
| filter | lookback | v none | v>0 | v>0.5 | v>1 | v>2 |
|---|---|---|---|---|---|---|
| mom20dn | L10 | 0.25 [-44] | 0.93 [-26] | 0.37 [-14] | 0.67 [-26] | 0.25 [-27] |
|  | L20 | 0.07 [-40] | 0.77 [-18] | 0.12 [-6] | 0.72 [-21] | 0.33 [-35] |
|  | L40 | -0.02 [-32] | 0.49 [-9] | 0.09 [+11] | 0.79 [-26] | 0.51 [-10] |
| mom20dn_brd5 | L10 | 2.99 [+35] | 4.36 [+45] | 3.85 [+49] | 2.89 [+35] | 1.01 [+2] |
|  | L20 | 1.51 [+39] | 3.66 [+56] | 3.29 [+61] | 2.83 [+44] | 0.80 [-0] |
|  | L40 | 1.58 [+38] | 3.04 [+56] | 2.62 [+65] | 2.50 [+24] | 1.36 [+18] |
| brd10 | L10 | 1.17 [+38] | 3.36 [+50] | 3.32 [+54] | 3.56 [+59] | 1.19 [+43] |
|  | L20 | 0.51 [+46] | 2.57 [+59] | 3.12 [+64] | 3.58 [+65] | 0.78 [+54] |
|  | L40 | -0.68 [+50] | 0.54 [+71] | 1.58 [+71] | 1.99 [+50] | 0.59 [+28] |

Reading the sensitivity. (i) Event rates scale with the filters as expected. Volume > 2 cuts events about 10x relative to no volume filter. L=40 fires about 1.2x less than L=20. The breadth gate cuts the share of event days from about 35% to 13-16% but *raises* events per event day to more than 100. (ii) Event-weighted excess is positive in 90/90 R1 cells and in 2026 in 90/90. It is a broad plateau and not a lucky cell. (iii) The day-weighted excess depends on the market filter. Its DEV t ranges by filter: none -2.2 to -0.3 (median -1.2), mom20dn -0.0 to 0.9 (median 0.4), sma200dn 0.3 to 3.6 (median 1.2), brd5 0.6 to 3.4 (median 2.1), brd10 -0.7 to 3.6 (median 1.6), mom20dn_brd5 0.8 to 4.4 (median 2.8). With no market filter it is negative in every cell, because isolated breakdowns continue. Filters that select washout conditions (breadth, bear market) create it. Within a filter, lookback matters little. High volume thresholds (v>2) weaken it because they leave too few names per washout day.

Table 4.6: horizon for A1 (event study).
| h | DEV events | P(net50>0) | net50 bps | xs ew (t) | xs dw (t) | 2026 xs (t) | 2026 net50 bps |
|---|---|---|---|---|---|---|---|
| 5 | 15902 | 0.608 | +179 | +34 (4.76) | +31 (4.45) | +30 (1.47) | +3 |
| 10 | 15788 | 0.580 | +207 | +38 (4.35) | +36 (4.36) | +64 (2.57) | +163 |
| 20 | 15427 | 0.551 | +232 | +34 (2.32) | +31 (1.99) | +92 (3.88) | +532 |

## 5. Event-rate scorecard (h=10)

**A1 (selected).** Monthly P(net50>0) on months with events: mean 0.59, std 0.21, min 0.08, max 0.99. Corr with the Nifty-500 monthly return: 0.47 for P(net>0), -0.18 for the excess, and -0.76 for the monthly event count. Events fire in 41/65 months.

| window | regime (N500 vs SMA200 x 20d mom) | events | share of events | share of U rows | P(net50>0) | net50 bps | xs bps |
|---|---|---|---|---|---|---|---|
| dev | bull_up20 | 0 | 0% | 60% | n/a | n/a | n/a |
| dev | bull_dn20 | 9078 | 57% | 24% | 0.639 | +314 | +33 |
| dev | bear_up20 | 0 | 0% | 6% | n/a | n/a | n/a |
| dev | bear_dn20 | 6710 | 43% | 10% | 0.500 | +62 | +44 |
| hold | bull_up20 | 0 | 0% | 37% | n/a | n/a | n/a |
| hold | bull_dn20 | 1299 | 19% | 10% | 0.209 | -448 | -37 |
| hold | bear_up20 | 0 | 0% | 16% | n/a | n/a | n/a |
| hold | bear_dn20 | 5703 | 81% | 37% | 0.568 | +302 | +88 |

| window | group | events | share of events | P(net50>0) | net50 bps | xs bps |
|---|---|---|---|---|---|---|
| dev | liq tercile 0 (universe terciles) | 5932 | 38% | 0.552 | +175 | +6 |
| dev | liq tercile 1 (universe terciles) | 4932 | 31% | 0.587 | +246 | +72 |
| dev | liq tercile 2 (universe terciles) | 4924 | 31% | 0.608 | +206 | +42 |
| dev | fno=True | 2798 |  |  | +174 | +18 |
| dev | fno=False | 12990 |  |  | +214 | +42 |
| dev | liq5=True | 11625 |  |  | +219 | +52 |
| dev | liq5=False | 4163 |  |  | +172 | -2 |
| hold | liq tercile 0 (universe terciles) | 2620 | 37% | 0.498 | +212 | +105 |
| hold | liq tercile 1 (universe terciles) | 2201 | 31% | 0.523 | +192 | +88 |
| hold | liq tercile 2 (universe terciles) | 2181 | 31% | 0.485 | +76 | -9 |
| hold | fno=True | 1197 |  |  | +32 | -38 |
| hold | fno=False | 5805 |  |  | +190 | +85 |
| hold | liq5=True | 5212 |  |  | +141 | +45 |
| hold | liq5=False | 1790 |  |  | +227 | +122 |

**ANCHOR R1dn.** Monthly P(net50>0) on months with events: mean 0.57, std 0.22, min 0.00, max 0.99. Corr with the Nifty-500 monthly return: 0.45 for P(net>0), -0.20 for the excess, and -0.70 for the monthly event count. Events fire in 48/65 months.

| window | regime (N500 vs SMA200 x 20d mom) | events | share of events | share of U rows | P(net50>0) | net50 bps | xs bps |
|---|---|---|---|---|---|---|---|
| dev | bull_up20 | 0 | 0% | 60% | n/a | n/a | n/a |
| dev | bull_dn20 | 3832 | 57% | 24% | 0.608 | +268 | +40 |
| dev | bear_up20 | 0 | 0% | 6% | n/a | n/a | n/a |
| dev | bear_dn20 | 2841 | 43% | 10% | 0.499 | +47 | +81 |
| hold | bull_up20 | 0 | 0% | 37% | n/a | n/a | n/a |
| hold | bull_dn20 | 522 | 18% | 10% | 0.205 | -463 | -85 |
| hold | bear_up20 | 0 | 0% | 16% | n/a | n/a | n/a |
| hold | bear_dn20 | 2428 | 82% | 37% | 0.601 | +403 | +111 |

| window | group | events | share of events | P(net50>0) | net50 bps | xs bps |
|---|---|---|---|---|---|---|
| dev | liq tercile 0 (universe terciles) | 2597 | 39% | 0.555 | +179 | +35 |
| dev | liq tercile 1 (universe terciles) | 1945 | 29% | 0.572 | +219 | +94 |
| dev | liq tercile 2 (universe terciles) | 2131 | 32% | 0.559 | +127 | +51 |
| dev | fno=True | 1285 |  |  | +85 | +29 |
| dev | fno=False | 5388 |  |  | +195 | +64 |
| dev | liq5=True | 4807 |  |  | +169 | +69 |
| dev | liq5=False | 1866 |  |  | +188 | +27 |
| hold | liq tercile 0 (universe terciles) | 1155 | 39% | 0.558 | +364 | +148 |
| hold | liq tercile 1 (universe terciles) | 878 | 30% | 0.543 | +278 | +98 |
| hold | liq tercile 2 (universe terciles) | 917 | 31% | 0.484 | +81 | -36 |
| hold | fno=True | 545 |  |  | +49 | -44 |
| hold | fno=False | 2405 |  |  | +296 | +103 |
| hold | liq5=True | 2132 |  |  | +197 | +42 |
| hold | liq5=False | 818 |  |  | +388 | +166 |

By construction the label is regime-conditional: it fires only in falling markets. The *class shares* of the absolute event label move with the market (monthly P(net>0) corr about 0.45-0.49; P(net>0) ranges from below 0.1 to 0.99 across months). The *excess* is nearly market-neutral (corr about -0.2). Large caps (F&O proxy, top liquidity tercile) show weaker or negative 2026 excess, so the effect is mid/small-cap.

Table 5.1: scorecard learnability of the event indicator (score = 1 for event rows, 0 for other U rows; `L.xs_metrics` per-date IC vs x_h, non-overlap t). Also shown is the per-date AUC of event vs non-event rows (common-language effect size: P(a random event beats a random same-day non-event)), event-weighted and day-weighted, with month-cluster t.
| event | h | xs IC DEV (t) | xs IC 2026 (t) | AUC ev-vs-rest DEV ew | AUC DEV dw (t) | AUC 2026 ew | AUC 2026 dw (t) | xs IC by DEV year |
|---|---|---|---|---|---|---|---|---|
| A1 | 5 | 0.0338 (2.37) | 0.0277 (1.14) | 0.537 | 0.532 (7.50) | 0.527 | 0.529 (2.88) | {"2023": 0.041, "2024": 0.031, "2025": 0.03} |
| A1 | 10 | 0.0289 (2.09) | 0.0335 (0.82) | 0.530 | 0.527 (5.30) | 0.540 | 0.529 (4.15) | {"2023": 0.044, "2024": 0.019, "2025": 0.025} |
| A1 | 20 | 0.0241 (1.34) | n/a (n/a) | 0.526 | 0.524 (3.96) | 0.539 | 0.528 (4.40) | {"2023": 0.037, "2024": 0.017, "2025": 0.021} |
| ANCHOR | 5 | 0.0118 (2.05) | 0.0062 (0.31) | 0.532 | 0.519 (2.50) | 0.525 | 0.497 (-0.19) | {"2023": 0.007, "2024": 0.014, "2025": 0.015} |
| ANCHOR | 10 | 0.0151 (3.04) | 0.0111 (0.89) | 0.534 | 0.526 (3.38) | 0.541 | 0.502 (0.17) | {"2023": 0.014, "2024": 0.01, "2025": 0.019} |
| ANCHOR | 20 | 0.0142 (0.77) | n/a (n/a) | 0.531 | 0.526 (2.61) | 0.538 | 0.506 (0.48) | {"2023": 0.013, "2024": 0.007, "2025": 0.021} |
| Q_CR|k3 | 5 | -0.0109 (-1.87) | -0.0028 (0.56) | 0.429 | 0.435 (-3.78) | 0.475 | 0.488 (-0.49) | {"2023": -0.011, "2024": -0.008, "2025": -0.014} |
| Q_CR|k3 | 10 | -0.0099 (-1.43) | -0.0008 (0.25) | 0.436 | 0.438 (-3.24) | 0.495 | 0.490 (-0.31) | {"2023": -0.01, "2024": -0.004, "2025": -0.015} |
| Q_CR|k3 | 20 | -0.0060 (0.38) | n/a (n/a) | 0.457 | 0.455 (-2.51) | 0.469 | 0.452 (-1.48) | {"2023": -0.005, "2024": -0.003, "2025": -0.01} |
| Q_BO|k3 | 5 | -0.0105 (-1.94) | -0.0081 (0.63) | 0.477 | 0.480 (-3.49) | 0.486 | 0.481 (-1.68) | {"2023": -0.014, "2024": -0.013, "2025": -0.004} |
| Q_BO|k3 | 10 | -0.0079 (-2.49) | -0.0038 (1.14) | 0.481 | 0.485 (-2.57) | 0.498 | 0.488 (-1.04) | {"2023": -0.009, "2024": -0.013, "2025": -0.001} |
| Q_BO|k3 | 20 | -0.0064 (-1.98) | n/a (n/a) | 0.484 | 0.487 (-2.20) | 0.495 | 0.487 (-1.16) | {"2023": -0.01, "2024": -0.011, "2025": 0.002} |

The indicator IC is tiny (about 0.01-0.03) because events are 1-3% of rows. Its pooled xs-AUC is about 0.50 for the same reason. The event-vs-rest AUC (about 0.53) is the meaningful learnability number for a sparse gate.

## 6. Investability of the sleeve (L.Sim)

Nifty 500 price index over the same windows: DEV CAGR 15.5% (maxDD -18.8%), 2026 -9.9% annualised (maxDD -14.8%). Universe random top-20 (fully invested, same h/step) is in the `urand` column.

Table 6.1: all-events sleeves, K=20, step=1, 50 bps (80 bps CAGR in brackets). 'exc' is the strategy minus the count-matched random sleeve, with NW t at lag h.
| mask | h | DEV CAGR50 [80] | Sharpe | maxDD | exposure | mean trade bps | matched CAGR | exc vs matched (t) | urand CAGR | 2026 CAGR50 [80] | 2026 matched | 2026 exc (t) | 2026 urand |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A0_R1dn_L20v1_mom20dn | 5 | 1.9% [-1.5%] | 0.25 | -15.9% | 18% | 23 | -0.9% | 2.7% (1.77) | -16.4% | -8.9% [-13.5%] | -10.2% | 1.3% (0.48) | -21.2% |
|  | 10 | 2.9% [1.3%] | 0.42 | -14.5% | 20% | 61 | 0.9% | 2.1% (2.25) | 0.4% | 3.4% [0.9%] | 3.2% | 0.2% (0.13) | -4.9% |
|  | 20 | 1.8% [1.0%] | 0.31 | -12.6% | 20% | 79 | 0.7% | 1.1% (1.43) | 10.2% | 12.7% [11.6%] | 11.2% | 1.6% (1.37) | 7.7% |
| A1_L10v0_mom20dn_brd5 | 5 | 5.7% [3.2%] | 0.80 | -10.5% | 13% | 73 | 3.0% | 2.7% (2.93) | -16.4% | -4.2% [-7.9%] | -9.2% | 5.0% (1.92) | -21.2% |
|  | 10 | 4.3% [3.1%] | 0.77 | -9.5% | 14% | 114 | 2.9% | 1.4% (2.37) | 0.4% | 4.8% [2.8%] | 2.5% | 2.2% (1.35) | -4.9% |
|  | 20 | 1.8% [1.2%] | 0.37 | -9.0% | 15% | 100 | 1.2% | 0.6% (1.43) | 10.2% | 10.3% [9.4%] | 8.2% | 2.2% (1.83) | 7.7% |
| N1_L20v1_mom20dn_brd5 | 5 | 5.0% [2.7%] | 0.73 | -10.5% | 12% | 72 | 3.1% | 2.0% (1.63) | -16.4% | -6.5% [-9.8%] | -9.5% | 3.0% (1.23) | -21.2% |
|  | 10 | 4.1% [2.9%] | 0.77 | -8.4% | 13% | 118 | 2.8% | 1.2% (1.55) | 0.4% | 3.3% [1.6%] | 1.5% | 1.8% (1.04) | -4.9% |
|  | 20 | 2.1% [1.5%] | 0.47 | -7.4% | 14% | 127 | 1.3% | 0.8% (1.68) | 10.2% | 9.5% [8.6%] | 7.6% | 1.8% (1.73) | 7.7% |
| N2_L20v1_brd10 | 5 | 4.8% [2.8%] | 0.77 | -5.2% | 10% | 78 | 3.4% | 1.4% (1.39) | -16.4% | -2.2% [-4.6%] | -4.5% | 2.4% (1.06) | -21.2% |
|  | 10 | 3.9% [2.9%] | 0.88 | -4.8% | 11% | 127 | 2.3% | 1.6% (2.37) | 0.4% | 2.6% [1.4%] | -0.4% | 3.0% (1.80) | -4.9% |
|  | 20 | 2.4% [2.0%] | 0.66 | -5.2% | 11% | 167 | 1.5% | 0.9% (2.05) | 10.2% | 8.1% [7.5%] | 5.2% | 2.9% (1.75) | 7.7% |
| N3_L10v0.5_brd10 | 5 | 4.3% [2.3%] | 0.69 | -5.5% | 10% | 67 | 3.5% | 0.8% (0.93) | -16.4% | -1.4% [-3.9%] | -3.8% | 2.5% (1.42) | -21.2% |
|  | 10 | 3.1% [2.1%] | 0.71 | -5.7% | 12% | 101 | 2.3% | 0.9% (1.45) | 0.4% | 2.3% [1.1%] | 0.1% | 2.3% (1.59) | -4.9% |
|  | 20 | 2.1% [1.6%] | 0.56 | -5.8% | 12% | 142 | 1.5% | 0.6% (1.48) | 10.2% | 7.6% [7.0%] | 5.7% | 2.0% (1.41) | 7.7% |
| N4_L20v0.5_mom20dn_brd5 | 5 | 4.6% [2.2%] | 0.66 | -10.9% | 13% | 60 | 2.9% | 1.8% (1.62) | -16.4% | -3.4% [-7.2%] | -9.3% | 5.8% (2.11) | -21.2% |
|  | 10 | 4.2% [3.0%] | 0.75 | -9.0% | 14% | 113 | 2.9% | 1.3% (1.86) | 0.4% | 5.8% [3.9%] | 2.5% | 3.3% (1.60) | -4.9% |
|  | 20 | 1.9% [1.4%] | 0.41 | -8.3% | 15% | 110 | 1.3% | 0.7% (1.54) | 10.2% | 10.8% [9.9%] | 8.2% | 2.7% (1.94) | 7.7% |
| N5_L40v1_mom20dn_brd5 | 5 | 5.4% [3.3%] | 0.83 | -9.0% | 11% | 82 | 3.5% | 2.0% (1.69) | -16.4% | -6.6% [-9.6%] | -9.8% | 3.2% (1.13) | -21.2% |
|  | 10 | 4.1% [3.0%] | 0.81 | -7.3% | 12% | 127 | 2.8% | 1.3% (1.65) | 0.4% | 2.1% [0.6%] | 0.0% | 2.1% (1.05) | -4.9% |
|  | 20 | 2.2% [1.7%] | 0.51 | -6.7% | 13% | 140 | 1.4% | 0.8% (1.67) | 10.2% | 8.4% [7.7%] | 6.6% | 1.8% (1.41) | 7.7% |
| N6_L20v1_brd5 | 5 | 2.8% [-0.6%] | 0.36 | -11.1% | 18% | 30 | -1.4% | 4.3% (2.76) | -16.4% | -10.9% [-15.1%] | -12.9% | 1.9% (0.64) | -21.2% |
|  | 10 | 4.6% [2.9%] | 0.71 | -8.8% | 20% | 87 | 1.8% | 2.9% (2.40) | 0.4% | 0.2% [-2.0%] | -1.3% | 1.5% (0.71) | -4.9% |
|  | 20 | 2.4% [1.6%] | 0.45 | -8.2% | 20% | 97 | 0.6% | 1.8% (2.36) | 10.2% | 7.6% [6.5%] | 5.5% | 2.1% (1.54) | 7.7% |

Table 6.2: slots per daily sleeve K (h=10, 50 bps). With step=1 each day can deploy at most 1/h of capital, so K changes diversification and how much light-event days count, not peak exposure.
| mask | K | DEV CAGR | Sharpe | exposure | mean trade bps | exc vs matched (t) | 2026 CAGR | 2026 exc (t) |
|---|---|---|---|---|---|---|---|---|
| A0_R1dn_L20v1_mom20dn | 5 | -0.5% | 0.01 | 29% | 2 | 1.7% (0.90) | 7.9% | 3.7% (1.07) |
|  | 10 | 1.3% | 0.19 | 25% | 29 | 1.8% (1.36) | 5.1% | 0.4% (0.18) |
|  | 20 | 2.9% | 0.42 | 20% | 61 | 2.1% (2.25) | 3.4% | 0.2% (0.13) |
| A1_L10v0_mom20dn_brd5 | 5 | 4.4% | 0.75 | 14% | 118 | 1.0% (1.11) | 3.5% | 3.9% (1.86) |
|  | 10 | 3.5% | 0.62 | 14% | 93 | 0.1% (0.13) | 5.2% | 3.7% (1.87) |
|  | 20 | 4.3% | 0.77 | 14% | 114 | 1.4% (2.37) | 4.8% | 2.2% (1.35) |
| N2_L20v1_brd10 | 5 | 3.8% | 0.80 | 12% | 119 | 1.7% (1.80) | 2.3% | 3.5% (1.92) |
|  | 10 | 4.0% | 0.87 | 12% | 125 | 1.6% (2.07) | 2.2% | 2.7% (1.40) |
|  | 20 | 3.9% | 0.88 | 11% | 127 | 1.6% (2.37) | 2.6% | 3.0% (1.80) |

Reading. The all-events sleeve beats count-matched random in every breadth-gated configuration at K=20: DEV excess t 0.93 to 2.93, 2026 t 0.64 to 2.11, all 21 + 21 positive. Without the breadth gate (ANCHOR) the K=5/10 sleeves have DEV CAGR -5.6% to 1.3%, because light-event days dominate. K=20 gives the best excess t in most cells because it gives mass days more names. No all-events sleeve clears the portfolio-level Bonferroni hurdle (best t 2.93).

## 7. Meta-labeling inside the gate

Models (`L.walk_forward2`, training mask = U & close < prior 10-day low, 106,859 rows; date_step=1, min_train=2000, min_test=100, num_leaves 15, min_child_samples 100, 300 trees; features = 52 lab features + brd, bdd10, bdd20). **WF_R10** is a regression on R2_rel's relative label at h=10 (per-date neumom residual rank - 0.5). **WF_A10** is binary, 1{r_10 > 50 bps} (absolute meta-label, round-1 style). Free comparators are R2_rel's every-bar OOS models **EB_XR10** / **EB_XR20** (neumom RANK, h=10/20). **DEPTH** ranks deeper breakdowns first. **LIQ** ranks more liquid names first.

Table 7.1: learnability inside A1. Within-event IC per day, on days with >= 10 events, averaged over days, with month-cluster t. `xs_metrics` IC needs >= 30 events per day and uses non-overlap t.
| score | h | within-event IC DEV (t) | IC 2026 (t) | xs_metrics IC DEV (t non-ovl) | xs AUC DEV | xs AUC 2026 | PIT threshold DEV: xs pass / fail bps (pass %) | 2026 pass / fail (pass %) |
|---|---|---|---|---|---|---|---|---|
| WF_R10 | 5 | 0.068 (6.31) | 0.045 (4.36) | 0.068 (5.62) | 0.535 | 0.518 | +46 / -1 (72%) | +40 / -13 (82%) |
|  | 10 | 0.057 (4.66) | 0.029 (1.49) | 0.056 (3.41) | 0.527 | 0.517 | +55 / -7 (72%) | +72 / +31 (82%) |
|  | 20 | 0.069 (4.28) | 0.001 (0.02) | 0.065 (1.83) | 0.528 | n/a | +65 / -47 (72%) | +85 / +126 (83%) |
| WF_A10 | 5 | 0.099 (6.65) | 0.053 (3.36) | 0.098 (3.75) | 0.553 | 0.524 | +41 / +2 (79%) | +44 / +15 (53%) |
|  | 10 | 0.085 (4.83) | 0.034 (1.96) | 0.087 (3.86) | 0.539 | 0.525 | +45 / +10 (79%) | +104 / +13 (56%) |
|  | 20 | 0.062 (3.74) | 0.012 (0.31) | 0.059 (-1.24) | 0.528 | n/a | +41 / +2 (79%) | +137 / +25 (60%) |
| EB_XR10 | 5 | 0.077 (6.63) | 0.054 (2.96) | 0.079 (4.95) | 0.541 | 0.524 | +47 / -7 (75%) | +31 / +28 (76%) |
|  | 10 | 0.066 (3.53) | 0.041 (1.72) | 0.066 (2.06) | 0.534 | 0.519 | +51 / -4 (75%) | +58 / +84 (76%) |
|  | 20 | 0.080 (5.19) | 0.027 (0.68) | 0.077 (0.71) | 0.539 | n/a | +62 / -52 (75%) | +79 / +136 (76%) |
| EB_XR20 | 5 | 0.074 (6.78) | 0.055 (4.44) | 0.076 (3.97) | 0.543 | 0.529 | +47 / +1 (70%) | +40 / +5 (73%) |
|  | 10 | 0.048 (3.19) | 0.042 (2.11) | 0.043 (1.74) | 0.519 | 0.520 | +49 / +10 (70%) | +68 / +55 (73%) |
|  | 20 | 0.070 (5.32) | 0.021 (1.19) | 0.066 (1.35) | 0.533 | n/a | +65 / -42 (70%) | +74 / +142 (74%) |
| DEPTH | 5 | 0.023 (1.39) | 0.011 (0.40) | 0.026 (0.96) | 0.516 | 0.505 |  |  |
|  | 10 | 0.016 (0.82) | 0.053 (2.23) | 0.015 (-1.04) | 0.506 | 0.525 |  |  |
|  | 20 | -0.015 (-0.85) | 0.037 (1.41) | -0.010 (-1.59) | 0.495 | n/a |  |  |
| LIQ | 5 | 0.053 (3.66) | 0.028 (1.16) | 0.054 (2.77) | 0.530 | 0.521 |  |  |
|  | 10 | 0.046 (1.79) | -0.029 (-1.10) | 0.046 (1.66) | 0.522 | 0.492 |  |  |
|  | 20 | 0.075 (2.50) | -0.047 (-0.88) | 0.074 (0.54) | 0.541 | n/a |  |  |

Table 7.2: investability. A1 gate, K=20, step=1. 'vs all' is against random events from the same gate (= `S.compare`). 'vs matched' is against count-matched universe random. 'thr' buys every event whose score passes the PIT threshold (prob > 0.5 / rank > 0) instead of the top 20.
| score / variant | h | DEV CAGR50 [80] | Sharpe | maxDD | exposure | mean trade bps | DEV exc vs all (t) | DEV exc vs matched (t) | 2026 CAGR50 | 2026 exc vs all (t) | 2026 exc vs matched (t) |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ALL_EVENTS random | 5 | 5.7% [3.2%] | 0.80 | -10.5% | 13% | 73 | 0.0% (n/a) | 2.7% (2.93) | -4.2% | 0.0% (n/a) | 5.0% (1.92) |
|  | 10 | 4.3% [3.1%] | 0.77 | -9.5% | 14% | 114 | 0.0% (n/a) | 1.4% (2.37) | 4.8% | 0.0% (n/a) | 2.2% (1.35) |
|  | 20 | 1.8% [1.2%] | 0.37 | -9.0% | 15% | 100 | 0.0% (n/a) | 0.6% (1.43) | 10.3% | 0.0% (n/a) | 2.2% (1.83) |
| WF_R10 topK | 5 | 10.4% [7.7%] | 1.35 | -9.6% | 13% | 127 | 4.7% (4.09) | 7.3% (4.70) | 0.4% | 4.6% (1.60) | 9.6% (2.87) |
|  | 10 | 6.6% [5.4%] | 1.13 | -8.3% | 14% | 172 | 2.3% (2.74) | 3.7% (3.34) | 7.0% | 2.2% (0.97) | 4.4% (1.52) |
|  | 20 | 3.1% [2.4%] | 0.60 | -8.1% | 15% | 167 | 1.3% (2.94) | 1.9% (3.10) | 11.6% | 1.3% (0.61) | 3.4% (1.27) |
| WF_R10 thr | 5 | 5.7% [3.2%] | 0.82 | -10.9% | 13% | 72 | 0.0% (-0.00) | 2.7% (2.50) | -2.8% | 1.3% (1.22) | 6.4% (2.34) |
|  | 10 | 4.4% [3.2%] | 0.80 | -9.4% | 14% | 117 | 0.1% (0.28) | 1.5% (2.42) | 5.4% | 0.6% (0.82) | 2.8% (1.67) |
|  | 20 | 2.2% [1.6%] | 0.46 | -8.6% | 15% | 121 | 0.4% (1.72) | 1.1% (2.32) | 10.4% | 0.0% (0.01) | 2.2% (1.74) |
| WF_A10 topK | 5 | 11.1% [8.5%] | 1.24 | -11.3% | 13% | 136 | 5.4% (3.63) | 8.1% (4.00) | -0.6% | 3.6% (1.11) | 8.6% (2.64) |
|  | 10 | 7.5% [6.2%] | 1.10 | -10.4% | 14% | 193 | 3.2% (3.44) | 4.6% (3.90) | 6.9% | 2.1% (0.77) | 4.4% (1.34) |
|  | 20 | 3.6% [2.9%] | 0.61 | -9.1% | 15% | 196 | 1.8% (2.73) | 2.4% (3.31) | 9.6% | -0.8% (-0.35) | 1.4% (0.59) |
| WF_A10 thr | 5 | 5.2% [3.2%] | 0.79 | -10.4% | 10% | 82 | -0.5% (-0.34) | 1.8% (1.90) | -3.7% | 0.5% (0.07) | 3.8% (1.68) |
|  | 10 | 4.0% [3.0%] | 0.77 | -8.5% | 11% | 132 | -0.3% (-0.37) | 1.3% (2.25) | 5.0% | 0.2% (0.03) | 2.7% (1.58) |
|  | 20 | 2.0% [1.5%] | 0.46 | -7.5% | 12% | 137 | 0.2% (0.21) | 0.6% (1.72) | 10.1% | -0.3% (-0.10) | 1.7% (1.36) |
| EB_XR10 topK | 5 | 9.5% [6.9%] | 1.22 | -10.5% | 13% | 118 | 3.8% (3.07) | 6.5% (3.55) | 0.1% | 4.3% (1.68) | 9.3% (2.81) |
|  | 10 | 6.6% [5.3%] | 1.10 | -9.3% | 14% | 170 | 2.3% (2.57) | 3.7% (3.05) | 8.1% | 3.3% (1.67) | 5.6% (1.89) |
|  | 20 | 3.2% [2.6%] | 0.62 | -8.2% | 15% | 175 | 1.4% (2.40) | 2.1% (2.72) | 12.0% | 1.6% (0.83) | 3.8% (1.60) |
| EB_XR10 thr | 5 | 6.6% [4.0%] | 0.92 | -10.2% | 13% | 83 | 0.9% (1.40) | 3.6% (3.32) | -2.6% | 1.6% (1.26) | 6.6% (2.58) |
|  | 10 | 4.8% [3.6%] | 0.86 | -9.4% | 14% | 125 | 0.5% (0.98) | 1.9% (2.59) | 5.2% | 0.4% (0.40) | 2.6% (1.48) |
|  | 20 | 2.2% [1.6%] | 0.46 | -8.7% | 15% | 122 | 0.4% (1.37) | 1.1% (2.19) | 10.6% | 0.3% (0.21) | 2.4% (1.70) |
| EB_XR20 topK | 5 | 9.5% [6.9%] | 1.21 | -10.9% | 13% | 118 | 3.8% (3.27) | 6.5% (3.78) | -0.1% | 4.0% (1.78) | 9.0% (3.28) |
|  | 10 | 5.6% [4.4%] | 0.94 | -10.5% | 14% | 146 | 1.3% (1.57) | 2.7% (2.39) | 7.5% | 2.8% (1.41) | 5.0% (1.71) |
|  | 20 | 3.0% [2.4%] | 0.57 | -8.9% | 15% | 160 | 1.2% (2.63) | 1.8% (2.77) | 11.6% | 1.3% (0.89) | 3.4% (1.58) |
| EB_XR20 thr | 5 | 7.1% [4.6%] | 1.00 | -10.2% | 13% | 89 | 1.4% (1.85) | 4.1% (3.60) | -3.4% | 0.7% (0.62) | 5.8% (2.22) |
|  | 10 | 5.1% [3.8%] | 0.92 | -9.2% | 14% | 132 | 0.7% (1.30) | 2.2% (2.75) | 4.5% | -0.2% (-0.23) | 2.0% (1.01) |
|  | 20 | 2.6% [2.0%] | 0.55 | -8.4% | 15% | 144 | 0.9% (2.64) | 1.5% (2.75) | 10.3% | -0.0% (-0.04) | 2.2% (1.48) |
| DEPTH topK | 5 | 6.2% [3.7%] | 0.74 | -12.5% | 13% | 79 | 0.5% (0.39) | 3.2% (1.62) | -0.3% | 3.9% (1.46) | 8.9% (2.07) |
|  | 10 | 4.6% [3.4%] | 0.72 | -10.7% | 14% | 126 | 0.3% (0.40) | 1.7% (1.44) | 9.8% | 5.1% (2.69) | 7.3% (2.22) |
|  | 20 | 1.6% [1.0%] | 0.30 | -9.2% | 15% | 96 | -0.2% (-0.39) | 0.4% (0.76) | 13.2% | 2.9% (1.97) | 5.1% (2.00) |
| LIQ topK | 5 | 5.0% [2.5%] | 0.75 | -7.7% | 13% | 63 | -0.7% (-0.42) | 1.9% (1.09) | -7.1% | -3.0% (-0.95) | 2.0% (0.74) |
|  | 10 | 4.1% [2.9%] | 0.81 | -7.3% | 14% | 107 | -0.2% (-0.20) | 1.2% (0.90) | -1.0% | -5.8% (-2.25) | -3.5% (-1.72) |
|  | 20 | 2.1% [1.4%] | 0.46 | -7.1% | 15% | 116 | 0.3% (0.25) | 0.9% (0.83) | 6.0% | -4.3% (-1.50) | -2.2% (-0.87) |

Reading. (i) Ranking inside the gate works. Every model score has a positive within-event IC in every window: DEV 0.05-0.10 (t 3.2-6.8); 2026 0.03-0.055 at h=5/10 but only 0.00-0.03 at h=20. Simple rules do not: DEPTH has IC of -0.01 to 0.02 in DEV, and LIQ flips sign in 2026 at h=10/20. (ii) The general every-bar relative model (EB_XR10/20) ranks events about as well as the event-specific models, so no special model is needed. This confirms round 1. (iii) Top-20 by score is the right use. PIT thresholds cut exposure and lose most of the gain. (iv) In 2026 the score's lift over all-events stays positive at h=5/10 (+2 to +5%/yr) but is not significant (t 0.8-1.8). At h=20 it is about zero.

**DEV selection** (rule: highest DEV t of 'vs all' at 50 bps, among model scores x h): WF_R10 at h=5 (t 4.09). h=10 is the cost-robust near-tie on DEV: Sharpe at 130 bps 0.58 vs 0.49 for h=5, 2x the net per trade, half the turnover. The h=5 vs h=10 choice is not resolved by DEV at central costs.

## 8. Robustness of the meta sleeve (A1 + WF_R10 top-20)

| h | cost | window | meta CAGR | Sharpe | maxDD | exposure | mean trade bps | all-events CAGR | matched CAGR | meta - matched /yr (NW t / month t) | excl. best month (t) | meta - all /yr (NW t / month t) | all - matched /yr (t) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 5 | 50 | dev | 10.4% | 1.35 | -9.6% | 13% | 127 | 5.7% | 3.0% | 7.0% (4.70 / 4.43) | 6.2% (4.32) | 4.4% (4.09 / 3.82) | 2.6% (2.93) |
| 5 | 50 | hold | 0.4% | 0.09 | -5.8% | 22% | 8 | -4.2% | -9.2% | 10.3% (2.87 / 2.84) | 7.2% (2.12) | 4.8% (1.60 / 1.06) | 5.5% (1.92) |
| 5 | 80 | dev | 7.7% | 1.03 | -10.3% | 13% | 97 | 3.2% | 0.6% | 7.0% (4.70 / 4.43) | 6.2% (4.32) | 4.4% (4.08 / 3.82) | 2.6% (2.93) |
| 5 | 80 | hold | -3.5% | -0.28 | -6.1% | 22% | -22 | -7.9% | -12.7% | 10.3% (2.87 / 2.85) | 7.2% (2.12) | 4.8% (1.61 / 1.07) | 5.5% (1.91) |
| 5 | 130 | dev | 3.5% | 0.49 | -12.1% | 13% | 47 | -0.9% | -3.4% | 7.0% (4.70 / 4.43) | 6.2% (4.31) | 4.4% (4.07 / 3.81) | 2.6% (2.93) |
| 5 | 130 | hold | -9.7% | -0.90 | -8.1% | 22% | -72 | -13.9% | -18.4% | 10.3% (2.88 / 2.85) | 7.2% (2.12) | 4.8% (1.62 / 1.07) | 5.5% (1.91) |
| 10 | 50 | dev | 6.6% | 1.13 | -8.3% | 14% | 172 | 4.3% | 2.9% | 3.6% (3.34 / 3.82) | 3.1% (3.10) | 2.2% (2.74 / 2.67) | 1.4% (2.37) |
| 10 | 50 | hold | 7.0% | 0.71 | -5.3% | 22% | 118 | 4.8% | 2.5% | 4.4% (1.52 / 2.14) | 3.4% (1.69) | 2.2% (0.97 / 0.82) | 2.2% (1.35) |
| 10 | 80 | dev | 5.4% | 0.92 | -8.8% | 14% | 142 | 3.1% | 1.7% | 3.6% (3.34 / 3.82) | 3.1% (3.10) | 2.2% (2.74 / 2.67) | 1.4% (2.37) |
| 10 | 80 | hold | 5.0% | 0.53 | -5.7% | 22% | 88 | 2.8% | 0.7% | 4.4% (1.51 / 2.14) | 3.4% (1.68) | 2.2% (0.97 / 0.81) | 2.2% (1.35) |
| 10 | 130 | dev | 3.3% | 0.58 | -9.7% | 14% | 92 | 1.0% | -0.3% | 3.6% (3.34 / 3.82) | 3.1% (3.10) | 2.2% (2.73 / 2.67) | 1.4% (2.36) |
| 10 | 130 | hold | 1.8% | 0.22 | -6.2% | 22% | 38 | -0.3% | -2.4% | 4.4% (1.51 / 2.13) | 3.4% (1.68) | 2.2% (0.96 / 0.81) | 2.2% (1.35) |
| 20 | 50 | dev | 3.1% | 0.60 | -8.1% | 15% | 167 | 1.8% | 1.2% | 1.9% (3.10 / 3.21) | 1.6% (2.90) | 1.3% (2.94 / 2.75) | 0.6% (1.43) |
| 20 | 50 | hold | 11.6% | 1.28 | -6.1% | 21% | 410 | 10.3% | 8.2% | 3.3% (1.27 / 1.58) | 1.7% (1.03) | 1.2% (0.61 / 0.63) | 2.1% (1.83) |
| 20 | 80 | dev | 2.4% | 0.49 | -8.3% | 15% | 137 | 1.2% | 0.6% | 1.9% (3.10 / 3.21) | 1.6% (2.90) | 1.3% (2.94 / 2.75) | 0.6% (1.43) |
| 20 | 80 | hold | 10.7% | 1.19 | -6.2% | 21% | 380 | 9.4% | 7.3% | 3.3% (1.26 / 1.57) | 1.7% (1.02) | 1.2% (0.60 / 0.62) | 2.1% (1.83) |
| 20 | 130 | dev | 1.4% | 0.30 | -8.7% | 15% | 87 | 0.2% | -0.4% | 1.9% (3.10 / 3.21) | 1.6% (2.90) | 1.3% (2.94 / 2.75) | 0.6% (1.43) |
| 20 | 130 | hold | 9.1% | 1.03 | -6.5% | 21% | 330 | 7.9% | 5.8% | 3.3% (1.26 / 1.56) | 1.7% (1.01) | 1.2% (0.60 / 0.62) | 2.1% (1.82) |

Table 8.2: perturbations (50 bps). LAG1 means the signal is acted on one day late, with entry at open t+2. The entity halves are a random 50% split of entities (seed 7), with the matched baseline drawn from the same half.
| variant | h | window | CAGR | Sharpe | matched CAGR | exc vs matched /yr (NW t / month t) |
|---|---|---|---|---|---|---|
| LAG1_ALL | h5 | dev | 6.6% | 0.97 | 4.1% | 2.4% (2.62 / 2.47) |
| LAG1_META | h5 | dev | 8.9% | 1.27 | 4.1% | 4.7% (3.04 / 3.05) |
| LAG0_ALL | h5 | dev | 5.7% | 0.80 | 3.0% | 2.6% (2.93 / 2.97) |
| LAG0_META | h5 | dev | 10.4% | 1.35 | 3.0% | 7.0% (4.70 / 4.43) |
| LAG1_ALL | h5 | hold | -5.1% | -0.47 | -8.4% | 3.6% (1.37 / 1.69) |
| LAG1_META | h5 | hold | -1.6% | -0.10 | -8.4% | 7.3% (2.25 / 2.14) |
| LAG0_ALL | h5 | hold | -4.2% | -0.36 | -9.2% | 5.5% (1.92 / 2.15) |
| LAG0_META | h5 | hold | 0.4% | 0.09 | -9.2% | 10.3% (2.87 / 2.84) |
| LAG1_ALL | h10 | dev | 3.4% | 0.61 | 2.2% | 1.2% (2.06 / 2.17) |
| LAG1_META | h10 | dev | 4.7% | 0.83 | 2.2% | 2.5% (2.43 / 2.66) |
| LAG0_ALL | h10 | dev | 4.3% | 0.77 | 2.9% | 1.4% (2.37 / 2.88) |
| LAG0_META | h10 | dev | 6.6% | 1.13 | 2.9% | 3.6% (3.34 / 3.82) |
| LAG1_ALL | h10 | hold | 5.2% | 0.57 | 3.4% | 1.8% (1.05 / 1.52) |
| LAG1_META | h10 | hold | 7.2% | 0.73 | 3.4% | 3.8% (1.11 / 1.26) |
| LAG0_ALL | h10 | hold | 4.8% | 0.53 | 2.5% | 2.2% (1.35 / 1.74) |
| LAG0_META | h10 | hold | 7.0% | 0.71 | 2.5% | 4.4% (1.52 / 2.14) |
| halfA_ALL | h5 | dev | 5.5% | 0.79 | 2.2% | 3.2% (3.95 / 3.82) |
| halfA_META | h5 | dev | 7.8% | 1.08 | 2.2% | 5.5% (4.32 / 4.63) |
| halfA_ALL | h5 | hold | -2.5% | -0.20 | -9.0% | 7.0% (2.42 / 2.87) |
| halfA_META | h5 | hold | -1.1% | -0.06 | -9.0% | 8.5% (2.52 / 2.24) |
| halfA_ALL | h10 | dev | 4.3% | 0.80 | 2.8% | 1.5% (2.42 / 2.89) |
| halfA_META | h10 | dev | 5.4% | 0.98 | 2.8% | 2.5% (2.87 / 3.66) |
| halfA_ALL | h10 | hold | 6.4% | 0.70 | 1.3% | 5.1% (2.38 / 2.93) |
| halfA_META | h10 | hold | 6.2% | 0.67 | 1.3% | 5.0% (1.76 / 2.24) |
| halfB_ALL | h5 | dev | 4.6% | 0.65 | 1.9% | 2.7% (2.69 / 2.97) |
| halfB_META | h5 | dev | 8.6% | 1.15 | 1.9% | 6.4% (4.34 / 4.06) |
| halfB_ALL | h5 | hold | -4.1% | -0.35 | -7.0% | 3.1% (1.10 / 1.38) |
| halfB_META | h5 | hold | -3.5% | -0.29 | -7.0% | 3.8% (1.14 / 1.52) |
| halfB_ALL | h10 | dev | 3.6% | 0.64 | 1.8% | 1.8% (2.85 / 3.32) |
| halfB_META | h10 | dev | 5.7% | 0.98 | 1.8% | 3.8% (3.93 / 3.74) |
| halfB_ALL | h10 | hold | 4.2% | 0.46 | 1.9% | 2.3% (1.24 / 1.28) |
| halfB_META | h10 | hold | 3.8% | 0.43 | 1.9% | 2.0% (0.79 / 0.92) |

Table 8.3: quarterly sum of daily excess (meta minus matched), 50 bps.
| sleeve|window | q1 | q2 | q3 | q4 | q5 | q6 | q7 | q8 | q9 | q10 | q11 | q12 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| h5|dev | 2023Q1: +3.9% | 2023Q2: +1.4% | 2023Q3: -0.2% | 2023Q4: +0.5% | 2024Q1: +0.8% | 2024Q2: +1.9% | 2024Q3: +0.3% | 2024Q4: +4.7% | 2025Q1: +4.1% | 2025Q2: -0.3% | 2025Q3: +1.5% | 2025Q4: +2.1% |
| h5|hold | 2026Q1: +5.0% | 2026Q2: +1.0% | 2026Q3: +2.0% | 2026Q4: -0.1% |  |  |  |  |  |  |  |  |
| h10|dev | 2023Q1: +2.3% | 2023Q2: +1.3% | 2023Q3: +0.1% | 2023Q4: +0.1% | 2024Q1: +0.2% | 2024Q2: +0.4% | 2024Q3: +0.4% | 2024Q4: +1.0% | 2025Q1: +2.6% | 2025Q2: +0.1% | 2025Q3: +1.2% | 2025Q4: +1.0% |
| h10|hold | 2026Q1: +2.6% | 2026Q2: +0.2% | 2026Q3: +0.0% | 2026Q4: +0.5% |  |  |  |  |  |  |  |  |

**Capacity** (meta sleeve trades 2023-01..2026-10, n=3500). Median 20d ADV of bought names is Rs 19.8 cr (p25 7.1, p10 3.3). 81% are >= Rs 5 cr ADV and 23% are F&O proxy names. Position as % of ADV, median / p90: Rs 5 lakh 0.25% / 1.5%; Rs 25 lakh 1.3% / 7.6% (19% of trades > 5% ADV); Rs 1 crore 5.1% / 30% (50% > 5% ADV). Up to 20 names per event day, each 1/(20h) of sleeve capital, so a Rs 1-5 cr sleeve is comfortable and Rs 20 cr+ is not, given panic-day spreads.
**Fills.** The t+1 entry bar is locked (high == low) for 0.07% of A1 events (0.00% locked limit-up). 0.8% gap up > 5%. The mean t+1 gap is 26 bps, the same as the universe (26). The open[t+1] fill assumption is not flattering the sleeve.

## 9. Other overreaction / reversal events (scan) under Bonferroni

Families (each x market filter none / mom20dn x h 5/10/20): **CR** crash day r1 <= -k*vol20[t-1] (k=3,4) & volz>1; **GR** gap-down reclaimed gap_open <= -m*ATR[t-1] (m=1,2) & close>open; **SL** 5-day xs loser rank(mom_5) <= 1%/3%; **OS** oversold rsi_14 < 20/25; **LV** within 0.5% of the 52w low & volz > 1/2; **BO** upside blow-off r1 >= +k*vol20[t-1] & volz>1 (avoid side). Added after s2 (flagged as data-driven): **Q_** = the same events on *quiet* days (brd < 2%), to test continuation. Bonferroni: 360 cells x 2 statistics (event- and day-weighted month-cluster t) = 720 tests, two-sided 5% means |z| > 3.98.

| event | h | DEV events | % DEV days | P(net50>0) | DEV xs ew (t) | DEV xs dw (t) | 2026 xs (t) | PRE xs | Bonferroni |
|---|---|---|---|---|---|---|---|---|---|
| CR|k3|-|none | 10 | 3941 | 79% | 0.530 | -27 (-1.26) | -126 (-5.47) | -56 (-1.31) | -72 | yes |
| CR|k3|-|mom20dn | 10 | 2217 | 30% | 0.598 | +18 (0.73) | -105 (-4.07) | -42 (-1.12) | -38 | yes |
| CR|k4|-|none | 10 | 1676 | 57% | 0.540 | -54 (-2.33) | -136 (-4.32) | -91 (-1.52) | -123 | yes |
| CR|k4|-|mom20dn | 10 | 997 | 23% | 0.622 | -6 (-0.25) | -96 (-1.86) | -78 (-2.06) | -83 |  |
| GR|m1|-|none | 10 | 2663 | 62% | 0.655 | -6 (-0.44) | -59 (-1.70) | -36 (-1.11) | -48 |  |
| GR|m1|-|mom20dn | 10 | 1479 | 22% | 0.752 | -15 (-1.08) | -36 (-0.80) | -38 (-0.99) | -39 |  |
| GR|m2|-|none | 10 | 777 | 26% | 0.739 | -60 (-2.52) | -180 (-3.93) | +25 (0.36) | -198 |  |
| GR|m2|-|mom20dn | 10 | 596 | 10% | 0.832 | -51 (-3.39) | -195 (-3.63) | +52 (0.74) | +1 |  |
| SL|q1|-|none | 10 | 7347 | 100% | 0.445 | -31 (-1.65) | -32 (-1.58) | -3 (-0.10) | -60 |  |
| SL|q1|-|mom20dn | 10 | 2475 | 35% | 0.468 | -6 (-0.15) | -9 (-0.21) | +9 (0.23) | +33 |  |
| SL|q3|-|none | 10 | 22764 | 100% | 0.455 | -7 (-0.58) | -6 (-0.49) | +3 (0.10) | -20 |  |
| SL|q3|-|mom20dn | 10 | 7685 | 35% | 0.480 | +22 (0.99) | +23 (0.96) | +48 (1.26) | +41 |  |
| OS|r20|-|none | 5 | 24520 | 98% | 0.474 | +26 (3.19) | +25 (1.82) | +14 (1.14) | +20 |  |
| OS|r20|-|none | 10 | 24268 | 98% | 0.467 | +13 (0.97) | +8 (0.45) | +29 (0.73) | -15 |  |
| OS|r20|-|mom20dn | 5 | 15465 | 35% | 0.521 | +41 (4.67) | +31 (3.72) | +21 (1.47) | +29 | yes |
| OS|r20|-|mom20dn | 10 | 15247 | 35% | 0.497 | +28 (1.74) | +19 (1.24) | +43 (0.88) | +3 |  |
| OS|r25|-|none | 5 | 49135 | 100% | 0.462 | +17 (2.75) | +14 (1.42) | +12 (1.13) | +12 |  |
| OS|r25|-|none | 10 | 48641 | 100% | 0.460 | +8 (0.69) | -5 (-0.38) | +13 (0.44) | -13 |  |
| OS|r25|-|mom20dn | 5 | 30074 | 35% | 0.504 | +27 (4.51) | +22 (4.48) | +22 (1.99) | +21 | yes |
| OS|r25|-|mom20dn | 10 | 29665 | 35% | 0.489 | +20 (1.45) | +13 (1.18) | +33 (0.91) | +4 |  |
| LV|v1|-|none | 10 | 520 | 36% | 0.469 | -58 (-1.16) | -91 (-1.64) | +37 (0.59) | +88 |  |
| LV|v1|-|mom20dn | 10 | 332 | 18% | 0.494 | -61 (-0.80) | -97 (-1.03) | +53 (0.73) | -1 |  |
| LV|v2|-|none | 10 | 168 | 18% | 0.488 | -40 (-0.56) | -49 (-0.61) | +58 (0.76) | +146 |  |
| LV|v2|-|mom20dn | 10 | 107 | 10% | 0.533 | -28 (-0.26) | -38 (-0.28) | +77 (0.73) | -67 |  |
| BO|k3|-|none | 10 | 12015 | 99% | 0.443 | -14 (-1.04) | -27 (-1.86) | -15 (-0.58) | -51 |  |
| BO|k3|-|mom20dn | 10 | 3068 | 35% | 0.430 | -22 (-1.52) | -50 (-2.17) | -15 (-0.33) | -76 |  |
| BO|k4|-|none | 10 | 5581 | 96% | 0.441 | -21 (-1.37) | -46 (-2.02) | -65 (-3.68) | -26 |  |
| BO|k4|-|mom20dn | 10 | 1402 | 33% | 0.427 | -41 (-1.70) | -109 (-2.70) | -44 (-1.39) | -48 |  |
| Q_R1|L20v1 | 5 | 1389 |  | 0.420 | -32 (-1.47) | -40 (-1.72) | -51 (-1.00) | -24 |  |
| Q_R1|L20v1 | 10 | 1357 |  | 0.457 | -38 (-1.37) | -56 (-2.08) | -48 (-0.61) | -25 |  |
| Q_CR|k3 | 5 | 568 |  | 0.331 | -130 (-5.96) | -130 (-4.65) | -20 (-0.26) | -205 | yes |
| Q_CR|k3 | 10 | 565 |  | 0.375 | -184 (-4.99) | -191 (-4.27) | -28 (-0.26) | -218 | yes |
| Q_CR|k4 | 5 | 213 |  | 0.291 | -152 (-4.13) | -164 (-3.90) | +4 (0.03) | -361 | yes |
| Q_CR|k4 | 10 | 213 |  | 0.347 | -206 (-4.60) | -226 (-4.68) | +8 (0.05) | -354 | yes |
| Q_GR|m2 | 5 | 83 |  | 0.289 | -217 (-3.72) | -254 (-4.39) | +18 (0.30) | -277 | yes |
| Q_GR|m2 | 10 | 83 |  | 0.361 | -247 (-2.80) | -318 (-3.27) | +69 (0.92) | -340 |  |
| Q_BO|k3 | 5 | 7130 |  | 0.430 | -7 (-0.68) | -5 (-0.44) | -14 (-0.42) | -39 |  |
| Q_BO|k3 | 10 | 7051 |  | 0.444 | -12 (-0.79) | -2 (-0.11) | +20 (0.50) | -30 |  |
| Q_BO|k4 | 5 | 3204 |  | 0.436 | -9 (-0.64) | -17 (-1.04) | -64 (-1.66) | -30 |  |
| Q_BO|k4 | 10 | 3174 |  | 0.446 | -21 (-1.12) | -16 (-0.70) | -29 (-0.73) | +1 |  |

Bonferroni passes (66 cells): R1 family 52, and also CR|k3|-|none h=5 (ew t -1.32, dw t -5.29), CR|k3|-|none h=10 (ew t -1.26, dw t -5.47), CR|k3|-|none h=20 (ew t -0.41, dw t -4.24), CR|k3|-|mom20dn h=10 (ew t 0.73, dw t -4.07), CR|k4|-|none h=10 (ew t -2.33, dw t -4.32), CR|k4|-|none h=20 (ew t -2.03, dw t -4.11), GR|m2|-|none h=5 (ew t -2.03, dw t -4.86), OS|r20|-|mom20dn h=5 (ew t 4.67, dw t 3.72), OS|r25|-|mom20dn h=5 (ew t 4.51, dw t 4.48), Q_CR|k3 h=5 (ew t -5.96, dw t -4.65), Q_CR|k3 h=10 (ew t -4.99, dw t -4.27), Q_CR|k4 h=5 (ew t -4.13, dw t -3.90), Q_CR|k4 h=10 (ew t -4.60, dw t -4.68), Q_GR|m2 h=5 (ew t -3.72, dw t -4.39).

OS as a sleeve (rsi_14<20 & mom20dn, K=20, step=1): h5|50|dev: CAGR -1.6%, exc vs matched 4.6%/yr (t 2.48); h5|50|hold: CAGR -10.5%, exc vs matched -1.1%/yr (t -0.24); h10|50|dev: CAGR -0.5%, exc vs matched 1.1%/yr (t 0.78); h10|50|hold: CAGR 5.7%, exc vs matched -1.6%/yr (t -0.45).

Reading. Only the *washout* version of overreaction reverses. Crash days and recovered gap-downs on quiet days continue: Q_CR / Q_GR DEV excess -130 to -250 bps (t -2.5 to -6.0), and PRE is even stronger at -205 to -460 bps. In 2026 that continuation was weak or reversed (Q_CR k3 -28 bps, t -0.3), so it is not a dependable avoid flag. 52-week lows on volume are negative but not significant. Removing quiet-day crash and blow-off names from the core book changed it by -0.1%/yr in DEV (t -0.52). Not selected; 2026 shows 0.6% (t 1.61). Upside blow-offs (BO) underperform by 10-50 bps (avoid side) but miss Bonferroni in DEV. Short-term (5-day) losers have no reversal edge on NSE at 5-20 days.

## 10. Combination with the relative core book

CORE = R2_rel `h20_neumom_RANK` walk_forward2 OOS score (reused, not retrained), U, top-20, step 5, h=20, reproduced exactly (DEV CAGR 30.88%). Sleeves use step=1, K=20. MIX w = (1-w) core + w sleeve, with sleeve idle cash at 0%. OVL w = idle sleeve capital parked in the core, r = r_core + w (r_sleeve - x_t r_core) - w |dx_t| cost/2. 'vs matched' compares the same combo with the sleeve replaced by its count-matched random twin.

| cost|window | book | CAGR | Sharpe | maxDD | sleeve alone CAGR / Sharpe | corr daily / active days / monthly | corr of excess | t vs core | t vs matched combo |
|---|---|---|---|---|---|---|---|---|---|
| 50|dev | CORE | 30.9% | 1.46 | -25.6% |  |  |  |  |  |
| 50|dev | 80% core + 20% cash | 24.8% | 1.46 | -21.0% |  |  |  |  |  |
| 50|dev | S5_META MIX20 | 26.8% | 1.50 | -22.1% | 10.4% / 1.35 | 0.57 / 0.78 / 0.33 | 0.12 | -1.77 | 4.23 |
| 50|dev | S5_META OVL20 | 30.6% | 1.44 | -25.5% | 10.4% / 1.35 | 0.57 / 0.78 / 0.33 | 0.12 | -0.70 | 4.26 |
| 50|dev | S10_META MIX20 | 25.9% | 1.48 | -22.2% | 6.7% / 1.13 | 0.62 / 0.78 / 0.53 | 0.18 | -2.16 | 3.52 |
| 50|dev | S10_META OVL20 | 30.2% | 1.44 | -25.7% | 6.7% / 1.13 | 0.62 / 0.78 / 0.53 | 0.18 | -1.86 | 3.73 |
| 50|dev | S10_CORE MIX20 | 25.7% | 1.46 | -22.6% | 5.7% / 0.95 | 0.62 / 0.78 / 0.57 | 0.26 | -2.32 | 2.49 |
| 50|dev | S10_CORE OVL20 | 30.0% | 1.42 | -26.1% | 5.7% / 0.95 | 0.62 / 0.78 / 0.57 | 0.26 | -2.22 | 2.61 |
| 50|dev | S10_ALL MIX20 | 25.4% | 1.45 | -22.4% | 4.3% / 0.78 | 0.63 / 0.80 / 0.63 | 0.13 | -2.47 | 2.65 |
| 50|dev | S10_ALL OVL20 | 29.6% | 1.41 | -26.0% | 4.3% / 0.78 | 0.63 / 0.80 / 0.63 | 0.13 | -3.13 | 2.72 |
| 50|dev | S10_R1DN MIX20 | 25.0% | 1.41 | -23.4% | 3.0% / 0.43 | 0.63 / 0.78 / 0.65 | 0.12 | -2.81 | 2.45 |
| 50|dev | S10_R1DN OVL20 | 29.6% | 1.41 | -25.8% | 3.0% / 0.43 | 0.63 / 0.78 / 0.65 | 0.12 | -3.01 | 2.60 |
| 50|dev | S20_META MIX20 | 25.1% | 1.43 | -22.2% | 3.1% / 0.60 | 0.70 / 0.80 / 0.60 | 0.22 | -2.56 | 3.10 |
| 50|dev | S20_META OVL20 | 30.4% | 1.45 | -25.5% | 3.1% / 0.60 | 0.70 / 0.80 / 0.60 | 0.22 | -1.79 | 3.19 |
| 50|hold | CORE | 16.0% | 0.80 | -17.2% |  |  |  |  |  |
| 50|hold | 80% core + 20% cash | 13.3% | 0.80 | -13.9% |  |  |  |  |  |
| 50|hold | S5_META MIX20 | 12.9% | 0.74 | -14.7% | 0.2% / 0.07 | 0.70 / 0.84 / 0.86 | 0.08 | -0.89 | 3.25 |
| 50|hold | S5_META OVL20 | 13.8% | 0.70 | -17.5% | 0.2% / 0.07 | 0.70 / 0.84 / 0.86 | 0.08 | -2.10 | 3.27 |
| 50|hold | S10_META MIX20 | 14.3% | 0.80 | -14.9% | 6.9% / 0.69 | 0.80 / 0.87 / 0.94 | 0.26 | -0.63 | 1.77 |
| 50|hold | S10_META OVL20 | 15.1% | 0.75 | -17.4% | 6.9% / 0.69 | 0.80 / 0.87 / 0.94 | 0.26 | -1.17 | 1.75 |
| 50|hold | S10_CORE MIX20 | 14.5% | 0.80 | -15.0% | 7.4% / 0.75 | 0.81 / 0.89 / 0.96 | 0.41 | -0.61 | 1.89 |
| 50|hold | S10_CORE OVL20 | 15.2% | 0.76 | -17.5% | 7.4% / 0.75 | 0.81 / 0.89 / 0.96 | 0.41 | -1.32 | 1.89 |
| 50|hold | S10_ALL MIX20 | 13.9% | 0.78 | -15.0% | 4.7% / 0.52 | 0.82 / 0.90 / 0.98 | 0.33 | -0.77 | 1.66 |
| 50|hold | S10_ALL OVL20 | 14.7% | 0.74 | -17.5% | 4.7% / 0.52 | 0.82 / 0.90 / 0.98 | 0.33 | -1.97 | 1.64 |
| 50|hold | S10_R1DN MIX20 | 13.5% | 0.75 | -15.6% | 3.3% / 0.32 | 0.83 / 0.90 / 0.98 | 0.28 | -1.00 | 0.13 |
| 50|hold | S10_R1DN OVL20 | 13.5% | 0.69 | -17.7% | 3.3% / 0.32 | 0.83 / 0.90 / 0.98 | 0.28 | -2.08 | 0.14 |
| 50|hold | S20_META MIX20 | 15.4% | 0.85 | -15.1% | 11.7% / 1.28 | 0.86 / 0.90 / 0.95 | 0.36 | -0.41 | 1.27 |
| 50|hold | S20_META OVL20 | 15.3% | 0.77 | -17.3% | 11.7% / 1.28 | 0.86 / 0.90 / 0.95 | 0.36 | -1.37 | 1.22 |
| 80|dev | CORE | 26.2% | 1.28 | -26.2% |  |  |  |  |  |
| 80|dev | S5_META MIX20 | 22.5% | 1.30 | -22.9% | 7.8% / 1.03 | 0.57 / 0.78 / 0.39 | 0.12 | -1.70 | 4.23 |
| 80|dev | S5_META OVL20 | 24.9% | 1.22 | -26.4% | 7.8% / 1.03 | 0.57 / 0.78 / 0.39 | 0.12 | -2.63 | 4.26 |
| 80|dev | S10_META MIX20 | 22.0% | 1.28 | -22.8% | 5.4% / 0.92 | 0.61 / 0.77 / 0.57 | 0.18 | -1.95 | 3.52 |
| 80|dev | S10_META OVL20 | 25.2% | 1.23 | -26.4% | 5.4% / 0.92 | 0.61 / 0.77 / 0.57 | 0.18 | -2.75 | 3.73 |
| 80|dev | S10_CORE MIX20 | 21.8% | 1.27 | -23.2% | 4.4% / 0.74 | 0.62 / 0.78 / 0.61 | 0.26 | -2.10 | 2.50 |
| 80|dev | S10_CORE OVL20 | 24.9% | 1.22 | -26.9% | 4.4% / 0.74 | 0.62 / 0.78 / 0.61 | 0.26 | -2.94 | 2.61 |
| 80|dev | S10_ALL MIX20 | 21.5% | 1.26 | -23.0% | 3.1% / 0.56 | 0.63 / 0.80 / 0.66 | 0.13 | -2.24 | 2.65 |
| 80|dev | S10_ALL OVL20 | 24.6% | 1.21 | -26.7% | 3.1% / 0.56 | 0.63 / 0.80 / 0.66 | 0.13 | -3.70 | 2.72 |
| 80|dev | S10_R1DN MIX20 | 21.0% | 1.22 | -24.0% | 1.3% / 0.21 | 0.63 / 0.78 / 0.67 | 0.12 | -2.63 | 2.45 |
| 80|dev | S10_R1DN OVL20 | 24.5% | 1.21 | -26.6% | 1.3% / 0.21 | 0.63 / 0.78 / 0.67 | 0.12 | -3.76 | 2.60 |
| 80|dev | S20_META MIX20 | 21.3% | 1.25 | -22.8% | 2.5% / 0.49 | 0.70 / 0.80 / 0.62 | 0.22 | -2.27 | 3.10 |
| 80|dev | S20_META OVL20 | 25.6% | 1.26 | -26.2% | 2.5% / 0.49 | 0.70 / 0.80 / 0.62 | 0.22 | -2.31 | 3.19 |
| 80|hold | CORE | 12.1% | 0.64 | -17.6% |  |  |  |  |  |
| 80|hold | S5_META MIX20 | 9.0% | 0.55 | -15.1% | -3.7% / -0.30 | 0.69 / 0.84 / 0.86 | 0.08 | -0.93 | 3.25 |
| 80|hold | S5_META OVL20 | 8.8% | 0.49 | -18.1% | -3.7% / -0.30 | 0.69 / 0.84 / 0.86 | 0.08 | -2.87 | 3.27 |
| 80|hold | S10_META MIX20 | 10.8% | 0.64 | -15.3% | 4.9% / 0.51 | 0.80 / 0.87 / 0.94 | 0.26 | -0.53 | 1.77 |
| 80|hold | S10_META OVL20 | 10.7% | 0.58 | -17.9% | 4.9% / 0.51 | 0.80 / 0.87 / 0.94 | 0.26 | -1.75 | 1.74 |
| 80|hold | S10_CORE MIX20 | 11.0% | 0.64 | -15.4% | 5.5% / 0.57 | 0.81 / 0.89 / 0.96 | 0.41 | -0.51 | 1.89 |
| 80|hold | S10_CORE OVL20 | 10.8% | 0.58 | -17.9% | 5.5% / 0.57 | 0.81 / 0.89 / 0.96 | 0.41 | -2.07 | 1.89 |
| 80|hold | S10_ALL MIX20 | 10.4% | 0.62 | -15.4% | 2.8% / 0.33 | 0.82 / 0.90 / 0.98 | 0.33 | -0.67 | 1.66 |
| 80|hold | S10_ALL OVL20 | 10.3% | 0.56 | -18.0% | 2.8% / 0.33 | 0.82 / 0.90 / 0.98 | 0.33 | -2.50 | 1.64 |
| 80|hold | S10_R1DN MIX20 | 9.9% | 0.58 | -16.0% | 0.8% / 0.13 | 0.83 / 0.90 / 0.98 | 0.28 | -0.92 | 0.13 |
| 80|hold | S10_R1DN OVL20 | 9.0% | 0.51 | -18.1% | 0.8% / 0.13 | 0.83 / 0.90 / 0.98 | 0.28 | -2.44 | 0.13 |
| 80|hold | S20_META MIX20 | 12.1% | 0.70 | -15.4% | 10.7% / 1.18 | 0.86 / 0.90 / 0.96 | 0.36 | -0.23 | 1.26 |
| 80|hold | S20_META OVL20 | 11.3% | 0.60 | -17.7% | 10.7% / 1.18 | 0.86 / 0.90 / 0.96 | 0.36 | -1.75 | 1.22 |

Tail behaviour (DEV, S5_META). On the core's worst 5% of days, the core averages -317 bps and the sleeve -64 bps (it is mostly in cash). In the core's three worst months the sleeve made: 2025-02 core -13.7% / sleeve -4.9%, 2025-01 core -9.5% / sleeve -1.4%, 2024-03 core -4.8% / sleeve 1.9%.

Table 10.2: one-model stack variants (core rebalances unchanged, 50 bps).
| variant | window | CAGR | Sharpe | maxDD | exc vs random (t) | vs core /yr (t) |
|---|---|---|---|---|---|---|
| CORE | dev | 30.9% | 1.46 | -25.6% | 19.1% (4.25) |  |
| CORE | hold | 16.0% | 0.80 | -17.2% | 9.2% (1.54) |  |
| CORE_TILT_A1_0.3 | dev | 29.7% | 1.43 | -24.6% | 17.9% (4.09) | -1.0% (-0.76) |
| CORE_TILT_A1_0.3 | hold | 14.4% | 0.73 | -17.7% | 7.6% (1.51) | -1.4% (-0.56) |
| CORE_AVOID_QCR3_QBO3 | dev | 30.7% | 1.46 | -25.6% | 19.0% (4.19) | -0.1% (-0.52) |
| CORE_AVOID_QCR3_QBO3 | hold | 16.7% | 0.82 | -17.2% | 9.9% (1.61) | 0.6% (1.61) |

Core overlap on gate days (178 days, about 134 events each): 25% of the core's top-20 are A1 events, against a 13% base share. The core's mean percentile of A1 events is 0.58. The relative model already leans into washout names, which is why a separate sleeve adds little to it.

Reading. The sleeve's daily correlation with the core is 0.57-0.70 (DEV) and 0.70-0.86 (2026) over all days, and 0.78-0.80 on the days it is active. The correlation of the two excess streams is low: 0.12-0.26 DEV, 0.08-0.41 2026. The sleeve's *selection* alpha is fairly independent of the core's, but its capital is long the same falling market at the same time. Every OVL20 combination is below the core (t vs core -3.13 to -0.70 DEV, -2.10 to -1.17 2026), even though the same combos beat their matched-random twins (t 2.6-4.3 DEV). MIX20 (meta sleeves h=5/10/20) versus 80% core + 20% cash changes CAGR by +0.3 to +2.0% in DEV and -0.4 to +2.1% in 2026. That is just 20% x the sleeve's own CAGR.

## 11. Candidate scorecards (summary)

| candidate | h | DEV CAGR 50 | DEV CAGR 80 | DEV excess t | DEV maxDD | DEV baseline CAGR | 2026 CAGR 50 | 2026 excess t | 2026 baseline CAGR | IC DEV | IC 2026 | verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| E1_R1DN_ANCHOR | 10d (5/20 also tested) | 2.9% | 1.3% | 2.25 | -14.5% | 0.9% | 3.4% | 0.13 | 3.2% | 0.015 | 0.011 | weak |
| E2_CAPIT_BREADTH_A1 | 10d (5d similar on DEV; 20d best in 2026) | 4.3% | 3.1% | 2.37 | -9.5% | 2.9% | 4.8% | 1.35 | 2.5% | 0.029 | 0.033 | promising |
| E3_CAPIT_META_A1_WFR10 | 5d DEV-selected; 10d cost-robust near-tie | 10.4% | 7.7% | 4.09 | -9.6% | 5.7% | 0.4% | 1.60 | -4.2% | 0.068 | 0.045 | promising |
| E4_QUIET_CRASH_AVOID | 5-20d | 30.7% | 26.1% | -0.52 | -25.6% | 30.9% | 16.7% | 1.61 | 16.0% | -0.010 | -0.001 | weak |
| E5_OVERSOLD_DOWNMKT | 5d | -1.6% | -6.3% | 2.48 | -26.0% | -5.9% | -10.5% | -0.24 | -9.5% | n/a | n/a | reject |

Baselines: E1/E2 use count-matched universe random (same days, same counts). E3 uses all events from the same gate (`S.compare` semantics); against matched random E3's DEV t is 4.70 and 2026 t is 2.87. E4 uses the core book itself (t of core-with-exclusion minus core). E5 uses matched random. IC: E1/E2/E4 use the event-indicator `xs_metrics` IC vs x_10. E3 uses the within-event day-weighted IC vs x_5.

## 12. Pros, cons, failure modes and how to use it

**Pros.** (1) The cleanest reversal fact in the lab. Buying washouts beats random stocks bought the same day in every year 2021-2026. Event-weighted excess is positive in 264/270 R1 cells in DEV and 268/270 in 2026, and it rises with breadth (lowest to highest bucket). It survives a 1-day signal lag, random entity halves, the best-month drop and 130 bps costs (h=10). (2) In the 2026 bear market (Nifty 500 -9.9% annualised), every breadth-gated sleeve at h=10/20 was positive at 50 bps (CAGR 0.2% to 10.8%), with maxDD -4.2% to -7.5%. (3) The event label is regime-conditional by design, but its excess is market-neutral (corr about -0.2). (4) The general relative model ranks the events, so no separate model is needed. (5) No execution artefact: t+1 entry bars are almost never locked.

**Cons / failure modes.** (1) It is episodic. There are 56 washout episodes in 5.75 years, the top 5 DEV months supply 58-60% of the excess, and the 2026 excess is mostly January and March (March alone is 69-92%). (2) Low exposure (13-22%) means low absolute CAGR (about 3-10%). The sleeve is a cash-deployment rule, not a book. (3) Horizon depends on the regime: 5-day holds win in bull-market corrections (2023-25) and lose in drawn-out bear markets (2026). (4) It adds nothing to the relative core book, because the core already leans into the same names and is long the same market. (5) Weak in large caps: 2026 excess for F&O-proxy names is negative, and capacity is about Rs 5-25 lakh per name. (6) Absolute class shares swing with the market. The monthly P(net>0) ranges from about 0.1 to 0.99. Read the label's +1 as 'beats same-day stocks', not 'goes up'.

**How to invest with it (if at all).** Each evening, compute brd (the share of eligible stocks closing below their prior 20-day low). If brd >= 5% and Nifty-500 20-day momentum < 0, take the stocks that closed below their prior 10-day low on above-average volume. Rank them with the relative model and buy the top 20 at the next open, each at 1/(20h) of the sleeve's capital. Hold h days (h=10 is recommended on DEV cost-robustness; h=5 was best at 50/80 bps) and exit at the close with a time exit, no stops. Fund it from capital that is not in the core relative book (a cash buffer or a separate sleeve). Expect 0-2 active weeks in most months and none in calm bull phases.

## 13. Statistics and variants tried

* Event-study cells: 360 (R1 family 3 lookbacks x 5 volume x 6 market filters x 3 h = 270; 6 other families x 2 params x 2 filters x 3 h = 72; 6 quiet-day events x 3 h = 18). Each is tested with event-weighted and day-weighted t, giving 720 tests and a Bonferroni |z| of 3.98.
* Portfolio specs at DEV / 50 bps (cost/window/seed/perturbation repeats not counted): s3 72 (8 masks x 3 K x 3 h), s4 60 (2 gates x 3 h x 6 scores topK + 4 thresholds), s5 36 (6 sleeves x MIX/OVL x 3 weights), 8 others. Total 176, giving a one-sided Bonferroni z of 3.45. The DEV-selected meta sleeve (t 4.09 vs all events, 4.70 vs matched) clears it. No all-events sleeve does (best t about 2.9).
* Walk-forward models: 2 new (WF_R10, WF_A10), within the budget of 6. R2_rel's EB_XR10/EB_XR20 OOS scores were reused. Total variants: about 538. Round 1 tried about 600 more.
* Holdout discipline. 2026 columns are printed next to DEV in every table (lab convention). Every *selection* used DEV columns only. The gate rule (max DEV day-weighted t at h=10, >= 500 events) was coded into s2 before it ran. The meta-sleeve rule (max DEV t vs all events) was applied mechanically. The recommendation of h=10 over the DEV-best h=5 is a judgment call made after 2026 was visible. It rests on DEV cost-robustness (Sharpe at 130 bps), but the reader should discount it accordingly. Round 1 had already reported 2026 for R1dn, so the holdout is lightly contaminated for the R1 family.
* NW t and month-cluster t for the sleeve excess agree within about 0.6 (Table 8.1). Effective sample: about 30 DEV washout episodes, so treat sleeve-level t as an upper bound.

## 14. Lab notes

* `S.compare`'s random arm draws from the same mask. On a sparse event mask it tests only the ranking within events and cannot measure the event effect. A count-matched universe baseline (`matched_mask` here) is needed. Suggest a `baseline_mask` / count-matching option in `Sim.compare`.
* `Sim.run` ends its window at the last signal plus one period, so daily series from different (h, step) configurations have different lengths (741 vs 743 days). Combining books needs date alignment.
* With step=1 and slot sizing, a sleeve can deploy at most 1/h of capital per day. Mass-capitulation days cannot be sized up beyond that. This is a structural cap on event sleeves in the v2 Sim.
* `xs_metrics` needs >= 30 rows per date, so event masks count only mass days. Its 'non-overlap' subsample takes every h-th *available* date, which is not calendar non-overlap for clustered event dates, so its t-stats are erratic. Use month-cluster t for event masks.
* `walk_forward2` default LightGBM params (num_leaves 31, min_child_samples 400) are too coarse for event-row training sets of 20-60k rows. Pass smaller params.