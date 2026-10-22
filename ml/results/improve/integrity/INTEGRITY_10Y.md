# P1 data integrity: ten-year extension (2016-10..2026-10)

Source of every number: `ml/results/improve/integrity/integrity_10y.json` (built 2026-10-22T14:42:50). History rows: stream P4 (`ml/data_hist/equity_eod_2016_2021.parquet`, CM bhavcopy + MTO delivery). Rules: `ml/IMPROVEMENT_PLAN.md`, P1 (I1, I2). No model was trained.

## Pass marks on the extended window

| Mark | Criterion | Result | Verdict |
|---|---|---|---|
| I1 (10 years) | no session > 5% prev_close mismatches | max 0.31%, flagged [] (141 mismatching rows, 18 on a parsed ex-date) | **PASS** |
| I2 (2016-10..2021-09) | split/bonus within ±15% of observed, ≥ 95% | 254 of 266 = 95.49% | **PASS** |
| I2 (whole feed) | same | 754 of 776 = 97.16% (2021-10..2026-10: 500 of 510 = 98.04%) | **PASS** |

## 1. Corporate actions 2016-10..2026-10

PR bundles from ['ml/data_raw/pr', 'ml/data_raw/hist/pr']: {'bundles': 2490, 'with_member': 2488, 'empty': 1, 'unreadable': 0, 'misfiled_skipped': ['PR020118.zip holds 2019-01-02', 'PR060424.zip holds 2024-06-04'], 'rows_rejoined': 8, 'rows_dropped': 0, 'files_with_overlong_rows': ['PR111019.zip/Bc111019.csv', 'PR141019.zip/Bc141019.csv', 'PR151019.zip/Bc151019.csv', 'PR210824.zip/Bc210824.csv'], 'rows': 909787, 'rows_without_ex_date': 101976, 'records': 45549}. Split/bonus/consolidation (ticker, ex-date) groups 971, evaluated 776; alternative listings resolved 2; superseded by a revised ex-date 22. Feed: 755 validated events {'ex_date < 2021-10-01': 254, 'ex_date >= 2021-10-01': 501} by kind {'split': 371, 'bonus': 348, 'bonus+split': 36}. Price-break flags: {'rights': 306, 'demerger': 106, 'capital_reduction': 63, 'scheme_of_arrangement': 41, 'split_unvalidated': 11, 'bonus_unvalidated': 9, 'bonus_other_security': 1, 'bonus+split_unvalidated': 1}.

Disagreements with ex-dates in 2016-10..2021-09 (listed ex-date; observed = open(ex)/close(ex−1)):

| Ticker | Ex-date | Purpose | Ratio | Observed | close(ex−1) | open(ex) | Resolved by shift | Same-day unadjustable |
|---|---|---|---:|---:|---:|---:|---|---|
| SUNILHITEC | 2016-10-27 | FV SPLT FRM RS 10 TO RE 1 | 0.1000 | 1.0767 | 408.65 | 440.0 | False | - |
| STAMPEDE | 2017-01-10 | BONUS 1:4 | 0.8000 | 0.9782 | 27.5 | 26.9 | False | - |
| GMBREW | 2018-05-21 | BONUS 1:4 | 0.8000 | 0.9248 | 1027.2 | 950.0 | False | - |
| CUPID | 2018-10-11 | BONUS 1:5 | 0.8333 | 0.9589 | 203.35 | 195.0 | False | - |
| JMA | 2019-05-14 | FVSPLT FRM RS 10 TO RS 2 | 0.2000 | 0.2386 | 168.05 | 40.1 | False | - |
| PSUBNKBEES | 2019-12-19 | FVSPLT FRM RS 10 TO RS 1 | 0.1000 | 0.1191 | 276.32 | 32.9 | False | - |
| RADIOCITY | 2020-03-12 | BONUS 1:4 | 0.8000 | 0.9505 | 25.25 | 24.0 | False | - |
| HDFCMFGETF | 2020-03-26 | FV SPLT FRM RS100 TO RS1 | 0.0100 | 1.0113 | 4004.75 | 4050.0 | False | - |
| HDFCNIFETF | 2020-03-26 | FV SPLT FRM761.25TO76.125 | 0.1000 | 0.9721 | 959.06 | 932.3 | False | - |
| HDFCSENETF | 2020-03-26 | FV SPLT2503.61TO250.361 | 0.1000 | 1.0074 | 3291.49 | 3316.0 | False | - |
| AXISNIFTY | 2020-07-23 | FVSPLTFRM RS 100 TO RS 10 | 0.1000 | 0.1165 | 1139.8 | 132.8 | False | - |
| MAHESHWARI | 2020-10-13 | BONUS 1:1 | 0.5000 | 0.5826 | 205.8 | 119.9 | False | - |

Completeness over both windows: 489 (ticker, date) rows with a CORP_IND code and |ret_1d| > 22%; 383 in the feed; 106 not, by bc kind: {'demerger': 47, 'rights': 27, 'dividend': 11, 'scheme_of_arrangement': 7, '(no bc record)': 5, 'meeting': 3, 'bonus': 3, 'demerger,dividend': 1, 'bonus,demerger': 1, 'other': 1}.

ETF list 10y: 494 symbols (469 from 2021-10 on, 129 in 2016-2021, 25 only in 2016-2021).

## 2. Write phase (10-year load)

Lock held 2026-10-22T14:33:30 → 2026-10-22T14:35:37: **127.1 s** (build_features 99.6 s). Staging: 23,715 P1 rows (re-applied, unchanged) + 2,142,087 history rows ({'ml/data_hist/equity_eod_2016_2021.parquet': {'rows_in_file': 2356697, 'rows_other_series_dropped': 214610, 'series_dropped': 118, 'date_min': '2016-10-03', 'date_max': '2021-09-30'}}).

| | Before | After |
|---|---:|---:|
| equity_eod rows | 3,095,641 | 5,237,728 |
| sessions | 1,251 | 2,489 |
| equity_features rows | 2,737,956 | 4,773,081 |
| EQ/BE (date, ticker) pairs stored twice | – | 0 |
| rows with an adjustment factor ≠ 1 | – | 589,221 |

equity_eod rows dated from 2021-10-01 unchanged by the load: **True** (count, sums of close/volume/turnover/prev_close, sessions, tickers: [3095641.0, 2270341992.0601, 4850951077780.0, 1120440911430000.0, 2269853857.5301, 1251.0, 4219.0]).
equity_features from 2021-10-01 vs the v2 export: raw columns identical True; rows whose adjustment factor changed 0 (tickers []); rows only in one 0.

Sessions before 2021-10-01 vs the history PR calendar (bundle present, member names carrying its date): identical **True**; stored but no bundle []; bundle but not stored []. Archive bundles holding another day (their own date is decided by its CM file instead): {'2018-01-02': {'holds': '2019-01-02', 'stored': True}}. Special sessions stored: {'2016-10-30': True, '2017-10-19': True, '2018-11-07': True, '2019-10-27': True, '2020-02-01': True, '2020-11-14': True}.

| Year | Stored sessions | PR calendar |
|---|---:|---:|
| 2016 | 62 | 62 |
| 2017 | 248 | 248 |
| 2018 | 246 | 245 |
| 2019 | 245 | 245 |
| 2020 | 252 | 252 |
| 2021 | 185 | 185 |

Known corporate actions, adjusted vs raw close-to-close move on the ex-date:

| Ticker | Ex-date | Adjusted move | Raw move | Largest adjusted daily abs(log move) | Continuous |
|---|---|---:|---:|---:|---|
| HDFCBANK | 2019-09-19 | +0.66% | -49.67% | 0.135 | True |
| INFY | 2018-09-04 | +2.79% | -48.60% | 0.177 | True |
| IRCTC | 2021-10-28 | +10.59% | -77.88% | 0.207 | True |
| NESTLEIND | 2024-01-05 | -1.67% | -90.17% | 0.120 | True |
| NESTLEIND | 2025-08-08 | -1.86% | -50.93% | 0.120 | True |
| RELIANCE | 2024-10-28 | +0.49% | -49.76% | 0.141 | True |
| RELIANCE | 2017-09-07 | -0.56% | -50.28% | 0.141 | True |
| TATASTEEL | 2022-07-28 | +4.60% | -89.54% | 0.135 | True |
| TCS | 2018-05-31 | -0.91% | -50.46% | 0.099 | True |
| YESBANK | 2017-09-21 | +0.27% | -79.95% | 0.824 | True |

## 3. Ten-year dataset (`ml/data_10y/`)

2,226,504 rows, 2,514 tickers, 2,241 sessions, 2017-10-03 to 2026-10-16; 52 features (same names and order as v2: True) plus exit_date; 103 monthly folds, embargo 22 sessions, holdout 2026-08-03..2026-09-16 (equal to v2: True). Label balance beat_mkt_20d 0.4997, up_5d 0.4837; y_clean_20d share 98.24%; flag_split_20d rate 0.145%.

First fold 2018-01: train_end 2017-11-29, 32,571 rows (32,424 labeled and clean, 41 sessions). The v2 folds inside the 10-year list: {'compared': 43, 'identical': 43, 'differing': []}. ETF check: {'rows_whose_ticker_is_in_the_etf_union': 0, 'rows_whose_ticker_is_in_that_dates_etf_file': 0}.

**v2 vs 10y on the common rows (date ≥ 2022-10-03):** 1,290,062 common rows (263,859 before 2023-10-02); rows only in v2 0, only in 10y 0. Identical features: ['amihud_20', 'close_pos_in_range', 'cs_rank_deliv_z', 'cs_rank_deliv_z_isnan', 'cs_rank_mom_20', 'cs_rank_turnover', 'cs_rank_vol_20', 'deliv_pct', 'deliv_pct_isnan', 'deliv_pct_sma_20', 'deliv_pct_sma_20_isnan', 'deliv_pct_z_20', 'deliv_pct_z_20_isnan', 'deliv_value_share_20', 'dist_sma_10', 'dist_sma_20', 'dist_sma_5', 'dist_sma_50', 'flag_near_52w_low', 'flag_split_20d', 'fwd_ret_5d', 'gap_pct', 'label_beat_mkt_20d', 'log_ret_1d', 'log_turnover', 'mom_10', 'mom_20', 'mom_5', 'range_pct', 'ret_1d', 'rsi_2', 'vol_10', 'vol_20', 'vol_5', 'vol_ratio_20', 'vol_z_20', 'y_clean_20d', 'y_excess_20d', 'y_rank_20d', 'y_raw_20d'].

| Feature | share differing | before 2023-10-02 | from 2023-10-02 | max abs diff from 2023-10-02 | v2 NaN filled in 10y |
|---|---:|---:|---:|---:|---:|
| macd_norm | 0.02% | 0.05% | 0.01% | 0.000139 | 0 |
| rsi_14 | 5.76% | 28.06% | 0.02% | 0.0906 | 0 |
| atr_pct | 0.02% | 0.03% | 0.01% | 2.19e-05 | 0 |
| dist_52w_high | 0.01% | 0.03% | 0.00% | 0.0355 | 0 |
| dist_52w_low | 0.01% | 0.06% | 0.00% | 0 | 0 |
| ret_63d | 0.00% | 0.00% | 0.00% | 0 | 13 |
| ret_126d | 0.01% | 0.02% | 0.00% | 0 | 73 |
| ret_252d | 0.25% | 1.16% | 0.01% | 0 | 3,194 |
| mom_12_1 | 0.25% | 1.16% | 0.01% | 0 | 3,194 |
| dist_200dma | 0.01% | 0.02% | 0.01% | 0.102 | 64 |
| flag_below_200dma | 0.00% | 0.01% | 0.00% | 0 | 0 |
| cs_rank_ret_126 | 6.64% | 19.98% | 3.21% | 0.00073 | 73 |
| ret_63d_isnan | 0.00% | 0.00% | 0.00% | 0 | 0 |
| ret_126d_isnan | 0.01% | 0.02% | 0.00% | 1 | 0 |
| ret_252d_isnan | 0.25% | 1.16% | 0.01% | 1 | 0 |
| mom_12_1_isnan | 0.25% | 1.16% | 0.01% | 1 | 0 |
| dist_200dma_isnan | 0.00% | 0.02% | 0.00% | 1 | 0 |
| cs_rank_ret_126_isnan | 0.01% | 0.02% | 0.00% | 1 | 0 |

Why the differing columns differ: the store now starts in 2016-10 instead of 2021-10, so (i) long windows that v2 could not fill for names with little history (ret_252d, mom_12_1, ret_126d, ret_63d, dist_200dma) now have values; (ii) the exponentially weighted features (rsi_14, macd_norm, atr_pct) start five years earlier, a difference that has decayed to the 1e-4 level by 2023-10; (iii) cs_rank_ret_126 ranks over the filled ret_126d values; (iv) no adjustment factor differs from 2021-10 on (the merged feed equals the v2 feed there, and the write phase found 0 rows with a changed factor).

## 4. Findings

- The history stream's first final assembly lacked 2019-10-11, 2019-10-14 and 2019-10-15 (its parser dropped a day when the bc member had an over-long CSV row); it re-parsed them before setting final. P1's independent CM + MTO construction (ml/integrity/hist_fill.py) reproduces P4's final rows exactly on the three re-parsed days and their six neighbours (True).
- A second archive mis-file: PR020118.zip holds the 2019-01-02 bundle (2018-01-02 is a session; its rows come from its CM file).
- Calendar: the 70 weekday closures of 2016-10..2021-09 were added to NSE_TRADING_HOLIDAYS; trading_days() now equals the stored sessions over the whole store (2016-10-03..2026-10-16), and --check-sessions reports 0 missing and 0 extra sessions.
- 2016-2019 bc spellings now parsed: 'BON 1:3', 'BONUS2:1', 'BONUS 1.5:1', 'CONSOLIDATION-RE1 TO RS10', 'INT RS 5/-', 'RET CAP' (capital reduction), 'SCH OF AGMT', 'BON 1 DVR : 4 EQ' (a bonus in another security: flagged, not adjusted); two different same-kind listings on one ex-date are treated as alternatives.
- Rows of the 118 non-equity series in the history parquet (bonds, gold bonds, funds, ...) were not loaded: the store keeps EQ/BE/BZ/SM/ST, as the ingest does.
- Backups of the store before each write are in the session scratchpad (rehearsal/nse_market_backup_pre_p1.duckdb, rehearsal/nse_market_backup_pre_hist.duckdb).

## 5. Outputs

- feed: `ml/data_ext/corporate_actions_feed_10y.csv`
- all_records: `ml/data_ext/corporate_actions_all_10y.csv`
- price_break_flags: `ml/data_ext/price_break_flags_10y.csv`
- etf_list: `ml/data_ext/etf_list_10y.csv`
- exports: `ml/results/improve/cache/{eod_export_10y.parquet, features_prices_export_10y.parquet}`
- dataset: `ml/data_10y/{model_dataset.parquet, manifest.json, splits.json}`
- reports: `ml/results/improve/integrity/{integrity_10y.json, INTEGRITY_10Y.md, corporate_actions_10y.json, etf_10y.json, write_phase_hist.json, v2_vs_10y.json}`
