# Q4 smoke run (three folds; not a result)

<!-- RESULTS (written by ml/improve/fo_ls.py from fo_ls.json; everything above this line was fixed before any result) -->

## 2. Results

Signal dates 2019-01-01 to 2019-03-29 (62), P&L sessions to 2019-05-03. Universe: 192 F&O names per date on average (199 stocks over the sample). Costs: long 20 bps per side, short 40 bps per side + 10 bps per roll. Sharpe uses rf 5.5% (FO_LS.md §1.6 D4). DSR at N = 261, V[SR] = 0.00387.

### 2.1 Pass mark

| Book | Net Sharpe [95% CI] | Sharpe ≥ 1.0 | CI lower > 0 | Beta plain | Beta Dimson | Both within ±0.2 | Verdict |
|---|---|---|---|---:|---:|---|---|
| plain | +2.62 [+1.34, +4.43] | yes | yes | -0.33 | -0.13 | no | **FAIL** |
| neutral | +0.82 [-2.57, +6.47] | no | no | -0.03 | +0.08 | yes | **FAIL** |

### 2.2 The two books (all signal dates, net of costs unless stated)

| | plain | neutral |
|---|---:|---:|
| Annualised net return | +35.9% | +10.6% |
|   of which long leg (net) | +39.1% | +26.4% |
|   of which short leg (net, incl. basis and rolls) | -3.1% | -15.8% |
|   short leg's basis convergence (gross) | +4.9% | +4.0% |
| Annualised gross return | +48.6% | +23.5% |
| Annualised net, no netting | +32.3% | +7.3% |
| Annualised volatility | 11.6% | 6.2% |
| Sharpe, rf 5.5% [95% CI] | +2.62 [+1.34, +4.43] | +0.82 [-2.57, +6.47] |
| Sharpe, rf 0 [95% CI] | +3.09 [+1.87, +4.86] | +1.72 [-1.76, +7.53] |
| Gross Sharpe, rf 5.5% | +3.72 | +2.94 |
| Max drawdown (fixed capital); peak → trough | -3.1%; 2019-03-25 → 2019-04-01 | -2.2%; 2019-01-21 → 2019-02-15 |
| Max drawdown gross; peak → trough | -2.8%; 2019-03-25 → 2019-04-01 | -1.7%; 2019-02-08 → 2019-02-15 |
| Months positive (excess over rf) | 3/3 | 2/3 |
| Months positive (net > 0) | 3/3 | 2/3 |
| Beta to Nifty 50, plain | -0.33 | -0.03 |
| Beta to Nifty 50, Dimson (lag 0 + lag 1) | -0.13 | +0.08 |
|   long leg / short leg Dimson beta | +1.04 / -1.16 | +1.13 / -1.04 |
| Turnover per rebalance, long / short | 77% / 75% | 78% / 77% |
| Rolls per tranche; tranches entering next month | 0.88; 15% | 0.88; 15% |
| Names per leg (long / short); universe | 38.5 / 38.5; 192 | 38.5 / 38.5; 192 |
| Holdout (2026-08..09) net Sharpe | +1.14 | +2.36 |
| DSR (N = 261) | 0.457 | 0.150 |

The expected best null Sharpe at N = 261 and V[SR] = 0.00387 is 2.82 a year.

### 2.3 By year (calendar year of the P&L session; net)

| Year | plain: net / Sharpe / long / short / beta | neutral: net / Sharpe / long / short / beta |
|---|---|---|
| 2019 | +35.9% / +2.62 / +39.1% / -3.1% / -0.33 | +10.6% / +0.82 / +26.4% / -15.8% / -0.03 |

### 2.4 Context (not trials): long-only F&O quintiles vs the equal-weight F&O universe (cash)

| Score | Basket | Excess vs EW F&O, 20 bps | IR [95% CI] | Name-level cost excess | Months beating EW | Turnover |
|---|---|---:|---|---:|---:|---:|
| plain | top_quintile | +15.6% | +3.01 [+0.83, +6.29] | +12.8% | 3/3 | 77% |
| plain | bottom_quintile | -26.4% | -3.67 [-5.34, -2.52] | -29.6% | 0/3 | 75% |
| neutral | top_quintile | +2.9% | +0.68 [-2.99, +6.15] | -0.2% | 2/3 | 78% |
| neutral | bottom_quintile | -15.7% | -3.74 [-8.10, -0.84] | -18.6% | 0/3 | 77% |

Equal-weight F&O universe: +21.8% a year, Sharpe (rf 5.5%) +0.96. Rank IC with y_raw_20d inside the F&O universe: plain +0.139, neutral +0.087. Beta check on the cash EW F&O universe: with the engine's open marks plain +0.64, Dimson +1.38; with interior close marks (A2) plain +1.08, Dimson +1.12.

### 2.5 Sensitivity: the long leg on the engine's open-to-open marks (the convention before amendment A2)

Tranche returns are identical to the primary books; only the daily marks, and so the daily statistics, differ.

| Book | Net Sharpe [95% CI] | Ann. vol | Beta plain | Beta Dimson | Max DD | DSR | Verdict under the same rule |
|---|---|---:|---:|---:|---:|---:|---|
| plain | +1.36 [+0.70, +2.49] | 22.3% | -0.71 | +0.12 | -4.8% | 0.225 | FAIL |
| neutral | +0.25 [-0.85, +1.41] | 20.4% | -0.39 | +0.41 | -5.8% | 0.091 | FAIL |

### 2.6 Data accounting

- F&O member rows among the scored rows: 11,937 of 33,415; excluded: entry contract not listed 8, price-break flag in window 7, off-calendar contract in window 0 (any window rule 7); universe 11,922 rows, of which 259 have a futures/cash gap above 5 points inside the window (kept, amendment A1).
- Futures file: 359 stocks; sessions imputed ['2021-03-30']; off-calendar rows 24 (ABFRL, HINDUNILVR, IDFC, IOC, ITC, SIEMENS, TATAMOTORS, VEDL); break sessions 333 of 812,761 comparisons.
- Short paths: 11,922 name-windows; entry settle back-filled 0, never quoted (flat) 0; settles carried forward 0; names flat after a final settlement with no roll target 34; exiting tranche not in the next entry's near contract 0.
- Long paths: exit mark matches the label on 100.000% of rows; entry open back-filled 0; interior close marks carried forward 0.
- Nifty 50 sessions missing on the price calendar (forward-filled): [].
- Independent recomputation of the short leg (seeded sample of 62 name-windows, straight from each stock's raw futures rows without the common calendar): 62 checked (55 with a roll, 0 skipped for a gap or a flat tail), largest difference in the exit value 1.3e-15.
- Split/bonus adjustment of the futures: 76 validated ex-dates of F&O stocks with quotes on both sides; the unadjusted settle moves by a median 51% on the ex-date, the adjusted settle stays within 4.0 points of the adjusted cash close (2.6% of events above 2 points).

### 2.7 Sensitivity added after the results of record: dividends (total return)

This sensitivity was added after §2.1-2.6 existed. It changes no convention, book or pass mark. The primary long leg is price-only (the engine's convention) and the futures short owes no dividends, so the book misses the long leg's dividends. Separately, NSE adjusts a stock-futures contract on the ex-date of a large dividend, and the unadjusted settle chain books that adjustment as a gain to the short. The sensitivity corrects both. Cash dividends with ex-date t+2..t+21 are credited to the long leg. On contracts classified as adjusted, the dividend is added back to the ex-date settle. Rule: adjusted if dividend >= 2% of the previous unadjusted close and the ex-date futures-minus-cash return gap < 0.5 x the dividend yield.

- Dividend events of F&O stocks with a parsed amount: 99.4% (3,423 in the price span). Events at or above 2% of price: 444, of which 158 fall outside the stock's F&O membership (no short exposure possible) and 12 are members without a quote on one side or with a split the same day (left unadjusted). Classified as adjusted contracts: 139. By year (member events at or above 2% / classified adjusted): 2017 1/0, 2018 31/3, 2019 32/4, 2020 37/10, 2021 34/9, 2022 46/11, 2023 41/40, 2024 18/17, 2025 23/23, 2026 23/22.
- Cross-check: the dividend credit of the equal-weight F&O universe is +1.71% a year. The Nifty 50's own dividend yield averages +1.20% over the same sessions.

| Book | Net ann. | Long-leg dividends | Short-leg add-back | Net Sharpe [95% CI] | Sharpe rf 0 | Beta plain / Dimson | DSR | Verdict under the same rule |
|---|---:|---:|---:|---|---:|---|---:|---|
| plain | +36.7% | +1.23% | -0.44% | +2.69 [+1.50, +4.45] | +3.16 | -0.33 / -0.13 | 0.473 | FAIL |
| neutral | +11.6% | +1.51% | -0.44% | +1.00 [-2.26, +6.57] | +1.90 | -0.03 / +0.08 | 0.172 | FAIL |

<!-- END OF GENERATED RESULTS -->
