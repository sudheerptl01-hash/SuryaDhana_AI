# ML labels and features: audit and walk-forward test

Generated 2026-09-29 09:07 by `scripts/ml_label_study.py` (pre-registered rules in its docstring). 277,802 stock-dates, 1018 symbols that were ever in the Desk's top-300 universe, 927 signal dates. Costs: 1.002% round trip at ₹25,000 a position.

## Audit of the v2 labels

| Measure | Value |
|---|---|
| market_share_of_5d_variance_pct | 26.2 |
| market_share_of_20d_variance_pct | 27.5 |
| weeks_label_mostly_market_pct | 42.6 |
| label_up_rate_range_by_year | [0.432, 0.541] |
| up_labels_losing_after_real_costs_pct | 16.4 |
| corr_close_vs_next_open_5d | 0.958 |
| ic_ret1d_vs_close_label | -0.0219 |
| ic_ret1d_vs_next_open_label | -0.0312 |
| barrier_2pct_touched_pct | 96.3 |
| barrier_2pct_same_bar_ambiguous_pct | 5.8 |
| median_daily_vol_pct | 2.19 |
| universe_rows_missing_from_ml_labels_pct | 6.2 |
| missing_names_mean_20d_excess_pct | -0.2 |
| ml_labels_start | 2020-09-16 00:00:00 |
| panel_start | 2010-01-04 |
| covered_names_mean_20d_excess_2019_2023_pct | 0.21 |
| uncovered_names_mean_20d_excess_2019_2023_pct | -0.27 |

## Ranking quality (rank IC vs next-open excess return; weekly; Newey-West t)

| Run | IC 20d all | t | IC 20d ≤2023 | t | IC 20d 2024+ | t | IC 5d all | t | weeks IC>0 % |
|---|---|---|---|---|---|---|---|---|---|
| A0 v2 label (5d close > 0.15%) | 0.0588 | 7.63 | 0.0617 | 7.21 | 0.0466 | 2.7 | 0.0603 | 13.44 | 67.3 |
| A1 5d next-open excess rank | 0.0705 | 6.7 | 0.0749 | 6.24 | 0.052 | 2.5 | 0.0716 | 12.03 | 65.4 |
| A2 20d next-open excess rank | 0.0719 | 5.59 | 0.0763 | 5.12 | 0.0537 | 2.3 | 0.0588 | 8.34 | 62.9 |
| B1 technical (2021+) | 0.0532 | 3.26 | 0.0529 | 2.32 | 0.0537 | 2.3 | 0.0524 | 5.68 | 63.1 |
| B2 technical + market-wide NSE (2021+) | 0.0521 | 3.89 | 0.0471 | 2.45 | 0.0578 | 3.17 | 0.0535 | 8.15 | 67.1 |
| C1 technical, covered symbols (2021+) | 0.0414 | 2.94 | 0.0506 | 2.31 | 0.0309 | 1.86 | 0.0404 | 5.73 | 59.7 |
| C2 technical + per-company NSE, covered (2021+) | 0.0473 | 3.96 | 0.0605 | 3.87 | 0.0322 | 1.81 | 0.0407 | 6.51 | 66.4 |
| mom_nse (Desk baseline) | 0.0473 | 4.39 | 0.0522 | 4.22 | 0.0267 | 1.35 | 0.0253 | 4.14 | 64.5 |

## 20-stock book, net of costs, excess over the universe's equal-weight return (annualised %)

| Run | Monthly: all | ≤2023 | 2024+ | IR all | gross | costs | turnover | Weekly: all | 2024+ | costs |
|---|---|---|---|---|---|---|---|---|---|---|
| A0 v2 label (5d close > 0.15%) | 0.96 | 3.14 | -8.33 | 0.08 | 9.48 | 8.53 | 0.709 | -17.71 | -22.48 | 31.28 |
| A1 5d next-open excess rank | 1.32 | 4.01 | -10.14 | 0.11 | 9.57 | 8.25 | 0.686 | -10.22 | -14.57 | 29.68 |
| A2 20d next-open excess rank | 6.73 | 9.39 | -4.64 | 0.54 | 13.0 | 6.27 | 0.522 | -2.9 | -7.09 | 16.98 |
| B1 technical (2021+) | 0.7 | 5.3 | -4.64 | 0.07 | 7.01 | 6.31 | 0.525 | nan | nan | nan |
| B2 technical + market-wide NSE (2021+) | -0.43 | -0.19 | -0.69 | -0.04 | 6.87 | 7.29 | 0.607 | nan | nan | nan |
| C1 technical, covered symbols (2021+) | 11.95 | 14.2 | 9.33 | 1.22 | 16.96 | 5.02 | 0.417 | nan | nan | nan |
| C2 technical + per-company NSE, covered (2021+) | 10.66 | 13.46 | 7.4 | 1.2 | 15.9 | 5.24 | 0.436 | nan | nan | nan |
| mom_nse (Desk baseline) | 13.0 | 17.04 | -4.19 | 0.91 | 16.2 | 3.2 | 0.266 | 11.88 | 0.12 | 4.47 |

## Where the ranking skill sits: mean 20-session excess by score decile (%, weekly, 2013+)

| decile | A0 v2 label (5d close > 0.15%) | A2 20d next-open excess rank | mom_nse (Desk baseline) |
|---|---|---|---|
| 1 | -0.9 | -0.84 | -0.66 |
| 2 | -0.18 | -0.15 | -0.38 |
| 3 | -0.14 | -0.31 | -0.4 |
| 4 | -0.05 | -0.12 | -0.2 |
| 5 | 0.11 | -0.08 | -0.33 |
| 6 | -0.0 | 0.01 | -0.2 |
| 7 | 0.18 | -0.05 | -0.02 |
| 8 | 0.18 | 0.17 | 0.26 |
| 9 | 0.29 | 0.53 | 0.64 |
| 10 | 0.48 | 0.79 | 1.25 |

Average per-date rank correlation between the A2 model and mom_nse: 0.431.


## Feature groups (paired weekly IC_20 difference, label A2)

| Added group | Mean IC gain | t (NW) | Weeks |
|---|---|---|---|
| B2 technical + market-wide NSE (2021+) | -0.0011 | -0.17 | 295 |
| C2 technical + per-company NSE, covered (2021+) | 0.0059 | 0.57 | 295 |

## Each NSE feature alone (rank IC vs 20-session excess, weekly, 2020+)

| Feature | IC | t (NW) | Weeks |
|---|---|---|---|
| deliv_pct_20d | 0.0252 | 1.58 | 347 |
| deliv_surge | -0.0031 | -0.46 | 347 |
| fno | 0.0142 | 1.04 | 347 |
| oi_chg_5d | 0.0051 | 0.96 | 347 |
| oi_chg_20d | 0.008 | 1.05 | 346 |
| pcr_oi | 0.0243 | 2.41 | 347 |
| oi_days | 0.0144 | 1.46 | 347 |
| bulk_inst_buy_60d | 0.0084 | 1.46 | 347 |
| bulk_inst_sell_60d | -0.0114 | -1.56 | 347 |
| bulk_other_buy_20d | -0.0157 | -3.17 | 347 |
| bulk_other_sell_20d | -0.0033 | -0.61 | 347 |
| mtf_intensity | -0.0162 | -0.97 | 234 |
| mtf_chg_20d | -0.0052 | -0.58 | 227 |
| insider_buy_63d | 0.0062 | 0.85 | 347 |
| insider_sell_63d | -0.0023 | -0.34 | 347 |
| insider_fresh_buy_21d | 0.0159 | 2.46 | 347 |
| shp_d_holders | 0.0028 | 0.23 | 242 |
| shp_d_inst | 0.0124 | 1.28 | 242 |
| shp_inst | -0.0079 | -0.52 | 242 |
| shp_retail | 0.0033 | 0.26 | 242 |
| shp_promoter | 0.0077 | 0.57 | 242 |
| shp_d_promoter | 0.0193 | 1.93 | 242 |

## Feature importance (share of total gain, summed over refits)

| Feature | A0 | A1 | A2 | B1 | B2 | C1 | C2 |
|---|---|---|---|---|---|---|---|
| beta_252 | 0.051 | 0.052 | 0.091 | 0.081 | 0.072 | 0.089 | 0.078 |
| vol_252d | 0.050 | 0.077 | 0.079 | 0.101 | 0.093 | 0.062 | 0.055 |
| mom_12_1 | 0.063 | 0.056 | 0.079 | 0.079 | 0.072 | 0.080 | 0.067 |
| mom_nse | 0.058 | 0.045 | 0.072 | 0.075 | 0.085 | 0.057 | 0.058 |
| vol_60d | 0.027 | 0.043 | 0.071 | 0.076 | 0.077 | 0.053 | 0.046 |
| high_52w | 0.031 | 0.034 | 0.060 | 0.048 | 0.035 | 0.030 | 0.025 |
| amihud_60d | 0.041 | 0.036 | 0.043 | 0.043 | 0.034 | 0.064 | 0.055 |
| liquidity | 0.034 | 0.025 | 0.041 | 0.041 | 0.031 | 0.062 | 0.054 |
| skew_60d | 0.029 | 0.029 | 0.038 | 0.034 | 0.028 | 0.037 | 0.031 |
| low_52w | 0.033 | 0.029 | 0.037 | 0.035 | 0.030 | 0.038 | 0.031 |
| sma50_sma200 | 0.032 | 0.025 | 0.035 | 0.037 | 0.032 | 0.050 | 0.043 |
| turnover_trend | 0.034 | 0.033 | 0.030 | 0.033 | 0.031 | 0.040 | 0.035 |
| mom_6m | 0.022 | 0.022 | 0.029 | 0.031 | 0.026 | 0.035 | 0.027 |
| px_sma50 | 0.024 | 0.023 | 0.028 | 0.029 | 0.025 | 0.033 | 0.031 |
| ret_1d | 0.063 | 0.069 | 0.027 | 0.029 | 0.025 | 0.019 | 0.015 |
| ret_60d | 0.025 | 0.021 | 0.025 | 0.026 | 0.024 | 0.030 | 0.026 |
| vol_20d | 0.027 | 0.023 | 0.025 | 0.022 | 0.021 | 0.024 | 0.020 |
| px_sma200 | 0.018 | 0.018 | 0.022 | 0.020 | 0.016 | 0.020 | 0.016 |
| atr_pct | 0.031 | 0.038 | 0.021 | 0.021 | 0.019 | 0.027 | 0.022 |
| gap_1d | 0.043 | 0.045 | 0.018 | 0.018 | 0.015 | 0.011 | 0.008 |
| max_ret_20d | 0.029 | 0.022 | 0.018 | 0.019 | 0.016 | 0.024 | 0.019 |
| ret_5d | 0.051 | 0.069 | 0.018 | 0.018 | 0.015 | 0.016 | 0.013 |
| rsi_14 | 0.023 | 0.020 | 0.016 | 0.016 | 0.011 | 0.018 | 0.014 |
| vol_ratio | 0.024 | 0.019 | 0.016 | 0.015 | 0.012 | 0.021 | 0.019 |
| px_sma20 | 0.037 | 0.030 | 0.016 | 0.015 | 0.015 | 0.015 | 0.012 |
| ret_20d | 0.026 | 0.021 | 0.015 | 0.013 | 0.010 | 0.018 | 0.015 |
| bb_pctb | 0.025 | 0.025 | 0.015 | 0.014 | 0.013 | 0.016 | 0.013 |
| close_loc | 0.049 | 0.052 | 0.014 | 0.012 | 0.011 | 0.010 | 0.007 |
| mtf_intensity | 0.000 | 0.000 | 0.000 | 0.000 | 0.008 | 0.000 | 0.000 |
| shp_d_inst | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.014 |
| bulk_inst_buy_60d | 0.000 | 0.000 | 0.000 | 0.000 | 0.004 | 0.000 | 0.000 |
| bulk_inst_sell_60d | 0.000 | 0.000 | 0.000 | 0.000 | 0.002 | 0.000 | 0.000 |
| bulk_other_buy_20d | 0.000 | 0.000 | 0.000 | 0.000 | 0.005 | 0.000 | 0.000 |
| bulk_other_sell_20d | 0.000 | 0.000 | 0.000 | 0.000 | 0.003 | 0.000 | 0.000 |
| shp_retail | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.014 |
| shp_promoter | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.017 |
| shp_inst | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.019 |
| shp_d_promoter | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.024 |
| shp_d_holders | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.011 |
| mtf_chg_20d | 0.000 | 0.000 | 0.000 | 0.000 | 0.005 | 0.000 | 0.000 |
| deliv_pct_20d | 0.000 | 0.000 | 0.000 | 0.000 | 0.022 | 0.000 | 0.000 |
| deliv_surge | 0.000 | 0.000 | 0.000 | 0.000 | 0.009 | 0.000 | 0.000 |
| fno | 0.000 | 0.000 | 0.000 | 0.000 | 0.002 | 0.000 | 0.000 |
| insider_buy_63d | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.019 |
| insider_fresh_buy_21d | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.006 |
| insider_sell_63d | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.023 |
| pcr_oi | 0.000 | 0.000 | 0.000 | 0.000 | 0.014 | 0.000 | 0.000 |
| oi_days | 0.000 | 0.000 | 0.000 | 0.000 | 0.020 | 0.000 | 0.000 |
| oi_chg_5d | 0.000 | 0.000 | 0.000 | 0.000 | 0.006 | 0.000 | 0.000 |
| oi_chg_20d | 0.000 | 0.000 | 0.000 | 0.000 | 0.004 | 0.000 | 0.000 |

## Monthly book, net excess by year (%)

| date | A0 v2 label (5d close > 0.15%) | A1 5d next-open excess rank | A2 20d next-open excess rank | B1 technical (2021+) | B2 technical + market-wide NSE (2021+) | C1 technical, covered symbols (2021+) | C2 technical + per-company NSE, covered (2021+) | mom_nse (Desk baseline) |
|---|---|---|---|---|---|---|---|---|
| 2013 | 14.9 | 16.7 | 12.4 |  |  |  |  | 28.6 |
| 2014 | 6.8 | 4.5 | -2.5 |  |  |  |  | 13.2 |
| 2015 | -0.5 | 1.8 | 13.1 |  |  |  |  | 11.0 |
| 2016 | -1.0 | -4.3 | 2.7 |  |  |  |  | -9.9 |
| 2017 | -5.9 | -4.2 | -5.8 |  |  |  |  | 32.2 |
| 2018 | 24.0 | 23.3 | 30.6 |  |  |  |  | 16.4 |
| 2019 | -0.3 | -0.0 | 18.6 |  |  |  |  | 14.1 |
| 2020 | -8.4 | -7.3 | 17.9 |  |  |  |  | 18.8 |
| 2021 | -14.0 | -5.7 | 6.0 | 5.6 | -5.1 | 17.7 | 21.7 | 22.8 |
| 2022 | 20.9 | 17.8 | 7.4 | 7.4 | 18.2 | 13.6 | 12.8 | 2.6 |
| 2023 | -2.0 | 1.4 | 2.8 | 2.8 | -13.7 | 11.3 | 6.0 | 37.7 |
| 2024 | 10.9 | -4.3 | -4.2 | -4.2 | -0.9 | 5.9 | 2.4 | -14.7 |
| 2025 | -14.0 | -6.6 | -0.8 | -0.8 | -1.7 | 5.1 | 4.7 | -6.9 |
| 2026 | -18.4 | -15.3 | -7.0 | -7.0 | 0.8 | 13.1 | 12.0 | 10.8 |

Runtime 93 s.
