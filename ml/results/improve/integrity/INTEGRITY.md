# P1 data integrity: results

Source of every number: `ml/results/improve/integrity/integrity.json` (built 2026-10-22T13:50:55). Pre-registration: `ml/IMPROVEMENT_PLAN.md`, P1. Integrity criteria only; no model was trained.

## Pass marks

| Mark | Criterion | Result | Verdict |
|---|---|---|---|
| I1 | no session > 5% prev_close mismatches after the fix | before: max 99.04% (7 sessions flagged); after (written store): max 0.15%, flagged [] (68 mismatching rows in all, 7 of them on a parsed corporate-action ex-date) | **PASS** |
| I2 | split/bonus ratio within ±15% of observed for ≥ 95% of events | 500 of 510 = 98.04% (listed ex-dates, no shift) | **PASS** |
| I3 | flag_split_20d falls and y_clean_20d rises (v2 vs v1) | flag_split_20d 0.557% → 0.095%; y_clean_20d 96.67% → 97.23% | **PASS** |
| I4 | zero ETFs in the v2 universe (daily etf lists) | 0 tickers in the etf-file union; 0 rows listed in that date's etf file | **PASS** |

## 1. Sessions

**Added (six sessions the ingest never requested).** Each file's own DATE1 column names the session and none is an echo of the previous stored session.

| Session | Rows (all series) | EQ+BE rows | ISIN enrichment |
|---|---:|---:|---|
| 2023-11-12 | 2,279 | 2,070 | cm12NOV2023bhav.csv.zip (100.0% ISIN) |
| 2024-03-02 | 2,307 | 2,107 | cm02MAR2024bhav.csv.zip (100.0% ISIN) |
| 2024-05-18 | 2,374 | 2,137 | cm18MAY2024bhav.csv.zip (100.0% ISIN) |
| 2025-02-01 | 2,635 | 2,262 | BhavCopy_NSE_CM_0_0_0_20250201_F_0000.csv.zip (parse failed) (0.0% ISIN) |
| 2025-10-21 | 2,843 | 2,430 | BhavCopy_NSE_CM_0_0_0_20251021_F_0000.csv.zip (parse failed) (0.0% ISIN) |
| 2026-02-01 | 2,955 | 2,507 | BhavCopy_NSE_CM_0_0_0_20260201_F_0000.csv.zip (parse failed) (0.0% ISIN) |

**Re-dated (mis-dated sessions found by the calendar audit).** On these closures the archive serves the preceding special or moved session's file. The ingest had skipped that session, so its duplicate-day guard compared the file with an older day and stored it under the closure's date.

| Stored under | True session | Rows | Evidence |
|---|---|---:|---|
| 2021-11-05 | 2021-11-04 | 1,874 | file `sec_bhavdata_full_05112021.csv` carries DATE1 = 2021-11-04; stored rows identical to it; no PR bundle for 2021-11-05 |
| 2023-06-29 | 2023-06-28 | 2,153 | file `sec_bhavdata_full_29062023.csv` carries DATE1 = 2023-06-28; stored rows identical to it; no PR bundle for 2023-06-29 |
| 2024-01-22 | 2024-01-20 | 2,341 | file `sec_bhavdata_full_22012024.csv` carries DATE1 = 2024-01-20; stored rows identical to it; no PR bundle for 2024-01-22 |

**2022-03-08 (10.7% mismatch): the store is wrong because the archive file is partial.** `sec_bhavdata_full_07032022.csv` holds {'EQ': 1653, 'SM': 59, 'ST': 2} and no BE or BZ rows, while 2022-03-08 holds {'EQ': 1651, 'BE': 210, 'SM': 60, 'BZ': 26, 'ST': 1}. The stored 2022-03-07 rows equal the file exactly. All 205 mismatches on 2022-03-08 are BE tickers whose stored previous row is 2022-03-04 ({'2022-03-04': 203, '2022-03-02': 1, '2022-02-28': 1}). Fix: the missing rows ({'BE': 241, 'BZ': 34}) are rebuilt from the CM bhavcopy `cm07MAR2022bhav.csv.zip` with the security-wise conventions (VWAP = value/qty, turnover in lakh at 2 dp, delivery empty for BE/BZ as everywhere in the store). The construction reproduces 2022-03-08's complete file exactly on BE/BZ (every column max |diff| = 0). The rebuilt closes equal the prev_close that 2022-03-08 reports for 210 of 210 BE tickers.

**Coverage repair.** Rule (fixed before the repair): rebuild a session when >= 10 traded EQ/BE securities of the PR bundle's pd file are missing from the store; rows = CM bhavcopy rows of series BE/BZ absent from that day's security-wise file (delivery empty, as for every BE/BZ row of the store); the EQ/SM call-auction securities the security-wise file omits on every session are not added. Before: 29 sessions met the rule (4,049 traded securities missing over all sessions, 1,416 of them priced ≥ ₹10). Repaired: 28 sessions, 1,679 BE/BZ rows (108 EQ call-auction rows, absent from the security-wise file on every session, left out). After: 0 sessions meet the rule, max 9 missing on any session (105 priced ≥ ₹10). The residual is penny stocks the security-wise file never lists.

**Calendar audit** (1842 calendar days 2021-10-01..2026-10-16; a PR bundle exists on 1251 days and is absent on 591; unknown: []). Weekend sessions: ['2023-11-12', '2024-01-20', '2024-03-02', '2024-05-18', '2025-02-01', '2026-02-01']. Holiday list vs closures: {'closures_not_in_list': [], 'listed_but_session': []}. After the fix, `trading_days()` vs the PR calendar: {'trading_days_without_pr': [], 'pr_sessions_not_in_trading_days': []}.

## 2. Corporate actions

bc files: {'bundles': 1252, 'with_member': 1251, 'empty': 1, 'unreadable': 0, 'misfiled_skipped': ['PR060424.zip holds 2024-06-04'], 'rows_rejoined': 2, 'rows_dropped': 0, 'files_with_overlong_rows': ['PR210824.zip/Bc210824.csv'], 'rows': 311551, 'rows_without_ex_date': 25110, 'records': 21963}. Records by kind: {'interest_redemption': 8872, 'dividend': 8334, 'meeting': 2843, 'bonus': 348, 'other': 334, 'split': 316, 'distribution': 311, 'rights': 236, 'buyback': 152, 'demerger': 73, 'merger': 60, 'capital_reduction': 57, 'call_money': 17, 'scheme_of_arrangement': 10}.

Split/bonus/consolidation (ticker, ex-date) groups: 628; superseded by a revised ex-date 17; outside the stored price history 104; evaluated 510. **I2: 500 agree = 98.04%** (bonus orientation flips 1 of 248 bonus events). The feed holds 501 validated events {'split': 258, 'bonus': 216, 'bonus+split': 27}. With the ex-date shift (an action effected 1 to 3 sessions away from the listed date, accepted only when the listed date disagrees and the other session agrees): {'events': 510, 'agree': 501, 'rate': 0.9823529411764705, 'shifted': 1, 'shift_sessions': {'1': 1}}.

Known events: NESTLEIND 2024-01-05 ratio 0.1 (expected 0.1, observed 0.1016) found; IRCTC 2021-10-28 ratio 0.2 (expected 0.2, observed 0.1978) found; TATASTEEL 2022-07-28 ratio 0.1 (expected 0.1, observed 0.1023) found; RELIANCE 2024-10-28 ratio 0.5 (expected 0.5, observed 0.5034) found.

Disagreements (listed ex-date; observed = open(ex)/close(ex−1)):

| Ticker | Ex-date | Purpose | Ratio | Observed | close(ex−1) | open(ex) | Resolved by shift | Same-day unadjustable |
|---|---|---|---:|---:|---:|---:|---|---|
| KRITIKA | 2022-08-29 | FVSPLT FRM RS 10 TO RS 2 | 0.2000 | 1.0497 | 133.85 | 140.5 | True | - |
| DANGEE | 2022-09-06 | BONUS 1:2 + FVSPLT FRM RS 10 TO RE1 | 0.0667 | 0.0799 | 406.1 | 32.45 | False | - |
| AHLEAST | 2022-10-06 | BONUS 1:2 | 0.6667 | 0.5280 | 350.35 | 185.0 | False | demerger |
| VCL | 2023-02-15 | FVSPLT FRM RS 2 TO RE 1 | 0.5000 | 0.5798 | 5.95 | 3.45 | False | - |
| SADHNANIQ | 2023-07-05 | BONUS 2:9 | 0.8182 | 0.9473 | 122.45 | 116.0 | False | - |
| ALPL30IETF | 2024-05-10 | FVSPLT FRM RS 10 TO RE 1 | 0.1000 | 0.1198 | 267.09 | 32.0 | False | - |
| MIDSELIETF | 2024-05-10 | FVSPLT FRM RS 10 TO RE 1 | 0.1000 | 0.1216 | 153.78 | 18.7 | False | - |
| NIF100IETF | 2024-05-10 | FVSPLT FRM RS 10 TO RE 1 | 0.1000 | 0.1196 | 250.67 | 29.99 | False | - |
| SAKUMA | 2024-08-09 | BONUS 4:1 | 0.2000 | 0.2374 | 32.39 | 7.69 | False | - |
| AXITA | 2024-09-20 | BONUS 1:3 | 0.7500 | 0.8661 | 21.59 | 18.7 | False | - |

Completeness: 336 (ticker, date) rows carry a CORP_IND code in the pd file and |ret_1d| > 22%; 271 are in the feed; 65 are not, by bc kind on that date: {'demerger': 34, 'rights': 19, '(no bc record)': 5, 'dividend': 3, 'bonus': 2, 'bonus,demerger': 1, 'other': 1} (5 without any bc record). All are listed in the JSON. Unadjustable price breaks written to `price_break_flags.csv`: {'rights': 235, 'demerger': 71, 'capital_reduction': 35, 'bonus_unvalidated': 4, 'split_unvalidated': 4, 'bonus+split_unvalidated': 1}.

## 3. ETFs and equity master

Union of the etf files: **469 symbols**. In the v1 dataset: 215 ETF tickers by the list (5.49% of rows) vs 156 by the label study's name rule; regex only (not in any etf file): ['GOLDTECH', 'JETFREIGHT']; list only (missed by the regex): ['ABSLPSE', 'ALPHA', 'BFSI', 'CHEMICAL', 'DEFENCE', 'ELM250', 'ENERGY', 'EVINDIA', 'GROWWCAPM', 'GROWWDEFNC', 'GROWWEV', 'GROWWHOSPI', 'GROWWMETAL', 'GROWWPOWER', 'GROWWRAIL', 'GROWWSLVR', 'HDFCBSE500', 'HDFCMID150', 'HDFCMOMENT', 'HDFCNEXT50', 'HDFCNIFBAN', 'HDFCNIFIT', 'HDFCPSUBK', 'HDFCPVTBAN', 'HDFCSML250', 'ICICIALPLV', 'ICICIB22', 'ICICIBANKN', 'ICICILIQ', 'ICICILOVOL', 'ICICITECH', 'IT', 'KOTAKALPHA', 'KOTAKPSUBK', 'LOWVOL1', 'MAFANG', 'MAHKTECH', 'MAKEINDIA', 'MASPTOP50', 'METAL', 'MIDCAP', 'MIDSMALL', 'MOCAPITAL', 'MODEFENCE', 'MOENERGY', 'MOM100', 'MOMENTUM50', 'MOMMIDCAP', 'MOMOMENTUM', 'MON100', 'MONQ50', 'MOREALTY', 'MOSMALL250', 'MOVALUE', 'NEXT50', 'PSUBANK', 'PSUBANKICI', 'SBIBPB', 'SMALL250', 'SMALLCAP', 'UTINEXT50']. Equity master (EQUITY_L.csv): 2619 listed equities, ISIN prefixes {'INE': 2617, 'IN9': 2}.

## 4. Write phase (the one read-write window on nse_market.duckdb)

Lock `ml/results/improve/LOCK_duckdb_write` held 2026-10-22T13:39:15 → 2026-10-22T13:40:41: **86.2 s** (build_features 59.2 s; the backup copy was taken before the lock with the store's size and mtime verified unchanged). A rehearsal of the same procedure on a copy took 107.2 s.

| | Before | After |
|---|---:|---:|
| equity_eod rows | 3,078,294 | 3,095,641 |
| sessions | 1,245 | 1,251 |
| equity_features rows | 2,722,591 | 2,737,956 |
| EQ/BE (date, ticker) pairs stored twice | – | 0 |
| rows with a split/bonus adjustment factor ≠ 1 | 0 | 230,722 |

Deleted (mis-dated) {'2021-11-05': 1874, '2023-06-29': 2153, '2024-01-22': 2341}; upserted 23,715 rows on 38 dates (existing keys overwritten: 0); row count as expected: True. Tables written: {'corporate_actions': 21927, 'etf_list': 469, 'equity_master': 2619, 'special_sessions': 16}. equity_features equals the in-memory dry run: True.

Known corporate actions, adjusted vs raw close-to-close move on the ex-date:

| Ticker | Ex-date | Adjusted move | Raw move | Largest adjusted daily abs(log move) in the series | Continuous |
|---|---|---:|---:|---:|---|
| NESTLEIND | 2024-01-05 | -1.67% | -90.17% | 0.081 | True |
| NESTLEIND | 2025-08-08 | -1.86% | -50.93% | 0.081 | True |
| IRCTC | 2021-10-28 | +10.59% | -77.88% | 0.207 | True |
| TATASTEEL | 2022-07-28 | +4.60% | -89.54% | 0.135 | True |
| RELIANCE | 2024-10-28 | +0.49% | -49.76% | 0.081 | True |

Idempotency (the write run twice on a copy): second run deleted {'2021-11-05': 0, '2023-06-29': 0, '2024-01-22': 0}, overwrote 23,715 existing keys in place, and left every count identical (True); equity_features still equal to the dry run: True. The script takes `--extra-staging` (equity_eod-schema parquet, e.g. the 2016-2021 rows of `ml/data_hist/`) and `--ca-csv` for the 10-year rebuild.

**Exports for the other streams** (same columns and types as the v1 exports): `ml/results/improve/cache/eod_export_v2.parquet` 2,737,956 rows; `ml/results/improve/cache/features_prices_export_v2.parquet` 2,737,956 rows.

## 5. v2 dataset (`ml/data_5y_v2/`)

| | v1 | v2 |
|---|---:|---:|
| rows | 1,357,383 | 1,290,062 |
| tickers | 2,480 | 2,265 |
| sessions | 996 | 1,002 |
| labeled_rows | 1,320,342 | 1,255,926 |
| labeled_clean_rows | 1,312,247 | 1,254,322 |
| label_beat_mkt_20d_mean | 0.49980 | 0.49979 |
| label_up_5d_mean | 0.48724 | 0.48371 |
| y_clean_20d_share | 0.96675 | 0.97230 |
| flag_split_20d_rate | 0.00557 | 0.00095 |
| etf_tickers_by_list | 215 | 0 |
| etf_rows_by_list | 74,545 | 0 |

Features: 52 (v1's 50 + deliv_value_share_20, amihud_20; identical order: True). Common (date, ticker) rows: 1,279,257; rows only in v1: 78,126 (of which ETF: 74,545); rows only in v2: 10,805. Fold boundaries vs v1: {'folds_changed': [{'name': '2023-12', 'train_end': {'v1': '2023-10-30', 'v2': '2023-10-31'}}, {'name': '2024-04', 'train_end': {'v1': '2024-02-26', 'v2': '2024-02-27'}}, {'name': '2024-06', 'train_end': {'v1': '2024-04-30', 'v2': '2024-05-02'}}, {'name': '2025-02', 'test_start': {'v1': '2025-02-03', 'v2': '2025-02-01'}}, {'name': '2025-03', 'train_end': {'v1': '2025-01-29', 'v2': '2025-01-30'}}, {'name': '2025-11', 'train_end': {'v1': '2025-09-29', 'v2': '2025-09-30'}}, {'name': '2026-02', 'test_start': {'v1': '2026-02-02', 'v2': '2026-02-01'}}, {'name': '2026-03', 'train_end': {'v1': '2026-01-29', 'v2': '2026-01-30'}}], 'holdout_changed': {}}.

Per-feature differences on common rows. Groups: A = tickers with an adjusted corporate action; B = other tickers before the first added session (2023-11-12); C = other tickers from then on.

| Feature | max abs diff | share differing | A | B | C |
|---|---:|---:|---:|---:|---:|
| ret_1d | 1.08 | 0.64% | 0.74% | 0.00% | 0.79% |
| log_ret_1d | 2.996 | 0.64% | 0.74% | 0.00% | 0.79% |
| gap_pct | 1.022 | 0.64% | 0.74% | 0.00% | 0.79% |
| range_pct | 2.151e-16 | 0.00% | 0.00% | 0.00% | 0.00% |
| close_pos_in_range | 3.231e-14 | 0.00% | 0.00% | 0.00% | 0.00% |
| dist_sma_5 | 1.152 | 2.54% | 2.93% | 0.00% | 3.17% |
| dist_sma_10 | 1.334 | 5.71% | 6.55% | 0.01% | 7.13% |
| dist_sma_20 | 1.513 | 12.01% | 13.68% | 0.02% | 15.02% |
| dist_sma_50 | 1.817 | 30.87% | 34.19% | 0.08% | 38.91% |
| macd_norm | 6.306 | 75.53% | 81.37% | 0.54% | 95.86% |
| mom_5 | 1.613 | 3.18% | 3.66% | 0.01% | 3.96% |
| mom_10 | 1.763 | 6.33% | 7.26% | 0.01% | 7.91% |
| mom_20 | 2.114 | 12.62% | 14.36% | 0.02% | 15.78% |
| vol_5 | 0.4487 | 3.19% | 3.66% | 0.01% | 3.97% |
| vol_10 | 0.2946 | 6.35% | 7.28% | 0.01% | 7.93% |
| vol_20 | 0.1933 | 12.66% | 14.40% | 0.02% | 15.83% |
| rsi_14 | 85.77 | 76.65% | 83.49% | 1.09% | 96.82% |
| atr_pct | 2.174 | 75.10% | 80.69% | 0.43% | 95.42% |
| vol_ratio_20 | 7.522 | 11.63% | 11.73% | 0.02% | 15.04% |
| vol_z_20 | 4.039 | 11.63% | 11.73% | 0.02% | 15.04% |
| deliv_pct | 0 | 0.00% | 0.00% | 0.00% | 0.00% |
| deliv_pct_sma_20 | 4.392 | 11.23% | 11.20% | 0.00% | 14.57% |
| deliv_pct_z_20 | 1.473 | 11.23% | 11.20% | 0.00% | 14.57% |
| dist_52w_high | 0.9521 | 7.85% | 27.86% | 0.03% | 3.65% |
| dist_52w_low | 80.69 | 8.99% | 21.60% | 0.06% | 7.53% |
| rsi_2 | 99.12 | 21.58% | 24.54% | 0.04% | 27.00% |
| ret_63d | 7.197 | 38.02% | 41.82% | 0.10% | 48.02% |
| ret_126d | 40.12 | 58.37% | 64.01% | 0.09% | 73.81% |
| ret_252d | 50.63 | 70.32% | 78.84% | 0.85% | 88.13% |
| mom_12_1 | 26.24 | 70.28% | 78.45% | 0.85% | 88.20% |
| dist_200dma | 3.412 | 74.02% | 79.46% | 0.48% | 94.04% |
| flag_below_200dma | 1 | 2.27% | 10.49% | 0.01% | 0.26% |
| flag_near_52w_low | 1 | 0.52% | 2.47% | 0.00% | 0.03% |
| flag_split_20d | 1 | 0.45% | 2.23% | 0.00% | 0.01% |
| log_turnover | 0 | 0.00% | 0.00% | 0.00% | 0.00% |
| cs_rank_mom_20 (cs) | 0.9991 | 99.45% | 99.76% | 99.53% | 99.32% |
| cs_rank_ret_126 (cs) | 0.9956 | 95.34% | 98.14% | 96.62% | 94.05% |
| cs_rank_vol_20 (cs) | 0.999 | 99.51% | 99.85% | 99.58% | 99.39% |
| cs_rank_turnover (cs) | 0.02919 | 99.92% | 99.79% | 99.95% | 99.95% |
| cs_rank_deliv_z (cs) | 0.3242 | 96.09% | 95.57% | 97.75% | 95.77% |
| deliv_pct_isnan | 0 | 0.00% | 0.00% | 0.00% | 0.00% |
| deliv_pct_sma_20_isnan | 1 | 0.01% | 0.01% | 0.00% | 0.02% |
| deliv_pct_z_20_isnan | 1 | 0.01% | 0.01% | 0.00% | 0.02% |
| ret_63d_isnan | 1 | 0.02% | 0.00% | 0.00% | 0.03% |
| ret_126d_isnan | 1 | 0.04% | 0.01% | 0.00% | 0.05% |
| ret_252d_isnan | 1 | 0.06% | 0.03% | 0.01% | 0.08% |
| mom_12_1_isnan | 1 | 0.06% | 0.03% | 0.01% | 0.08% |
| dist_200dma_isnan | 1 | 0.03% | 0.01% | 0.00% | 0.05% |
| cs_rank_ret_126_isnan (cs) | 1 | 0.04% | 0.01% | 0.00% | 0.05% |
| cs_rank_deliv_z_isnan (cs) | 1 | 0.01% | 0.01% | 0.00% | 0.02% |
| deliv_value_share_20 | 0.4835 | 11.31% | 11.29% | 0.00% | 14.68% |
| amihud_20 (cs) | 2.289 | 99.74% | 99.92% | 99.78% | 99.67% |
| y_raw_20d (cs) | 1.877 | 13.36% | 15.02% | 8.69% | 14.21% |
| y_excess_20d (cs) | 1.875 | 96.60% | 97.02% | 98.34% | 95.94% |
| label_beat_mkt_20d (cs) | 1 | 2.43% | 3.25% | 1.31% | 2.49% |
| fwd_ret_5d | 1.613 | 3.22% | 3.68% | 2.11% | 3.40% |

Per-ticker features identical in group B: ['close_pos_in_range', 'deliv_pct', 'deliv_pct_isnan', 'deliv_pct_sma_20', 'deliv_pct_sma_20_isnan', 'deliv_pct_z_20', 'deliv_pct_z_20_isnan', 'deliv_value_share_20', 'flag_near_52w_low', 'flag_split_20d', 'log_turnover', 'range_pct', 'ret_126d_isnan']; differing in group B (share of group-B rows; these are the BE tickers whose 2022-03-07 and 2023-06..08 rows were rebuilt, and window features of rows near the re-dated sessions): {'ret_1d': '0.001%', 'log_ret_1d': '0.001%', 'gap_pct': '0.001%', 'dist_sma_5': '0.005%', 'dist_sma_10': '0.010%', 'dist_sma_20': '0.018%', 'dist_sma_50': '0.077%', 'macd_norm': '0.539%', 'mom_5': '0.006%', 'mom_10': '0.011%', 'mom_20': '0.020%', 'vol_5': '0.006%', 'vol_10': '0.011%', 'vol_20': '0.020%', 'rsi_14': '1.092%', 'atr_pct': '0.433%', 'vol_ratio_20': '0.019%', 'vol_z_20': '0.019%', 'dist_52w_high': '0.029%', 'dist_52w_low': '0.063%', 'rsi_2': '0.036%', 'ret_63d': '0.103%', 'ret_126d': '0.086%', 'ret_252d': '0.845%', 'mom_12_1': '0.845%', 'dist_200dma': '0.482%', 'flag_below_200dma': '0.008%', 'ret_63d_isnan': '0.004%', 'ret_252d_isnan': '0.009%', 'mom_12_1_isnan': '0.009%', 'dist_200dma_isnan': '0.000%'}. Cross-sectional columns (cs) differ almost everywhere because the universe lost its ETFs; amihud_20 is a per-date z-score, so any change on a date moves every row of that date.

## 6. Findings for the lead

- nse_historical_ingest.parse_pr_zip, UDiFF branch: column names are upper-cased and then looked up in mixed case (TckrSymb, SctySrs, ...), so the UDiFF enrichment always fails and ISIN stays empty for every UDiFF day (2024-07 onward); not changed (outside P1's edit scope). The three legacy-era added sessions and the three re-dated ones carry ISIN from the CM bhavcopy; every other stored row has none.
- The archive serves the preceding special or moved session's file on the closures 2021-11-05, 2023-06-29 and 2024-01-22, and the ingest's duplicate-day guard cannot catch it because that session was never stored; the calendar now lists those closures and the sessions are in SPECIAL_SESSIONS.
- The archive's security-wise files omit BE/BZ rows on 2022-03-07 and a growing set of BE securities (weekly from 2023-06-19, daily 2023-07-24..2023-08-24); rebuilt from the CM bhavcopy.
- The archive file PR060424.zip holds the 2024-06-04 bundle (day and month swapped); bundles are validated by the date in their member names.
- From mid-2025 the bc files write dates as yyyy-mm-dd instead of dd/mm/yyyy; both are parsed.
- On split/bonus-adjusted equity_features the universe price floor must use the raw close: v2 passes universe_price_col='close_unadj' (an adjusted close would let a future split remove past rows: 7,806 rows of 50 tickers from 2022-10-03 have an adjusted close below Rs 10 but a raw close at or above it). This is the one addition to the briefed build call.
- amihud_20 in v2 uses adjusted-close returns (the v1 prep used raw closes); deliv_value_share_20 uses raw same-day prints as before.
- The label study's ETF name rule misses ETFs the etf files list and flags operating companies (GOLDTECH, JETFREIGHT; at store level also GOLDENTOBC and the rights entitlement JETFRE-RE).
- Unadjustable price breaks (rights, demergers, capital reductions, schemes) and unvalidated splits/bonuses are listed in ml/data_ext/price_break_flags.csv for label masking; v2 does not mask them beyond y_clean_20d.
- Backup of the pre-write store (1.42 GB): <session scratchpad>/rehearsal/nse_market_backup_pre_p1.duckdb; it can be deleted once the lead is satisfied.

History-stream special sessions confirmed by their PR bundles (member names carry the date): 2016-10-30 (Sunday), 2017-10-19 (Thursday), 2018-11-07 (Wednesday), 2019-10-27 (Sunday), 2020-02-01 (Saturday), 2020-11-14 (Saturday).

## 7. Timings (seconds)

{'sessions': 214.8, 'corporate_actions': 57.2, 'etf': 13.8, 'dry_run': 124.5, 'write_phase_lock_window': 86.2, 'rehearsal': 107.2, 'v2_build': 148.3}

## 8. Outputs

- code: `ml/integrity/`
- corporate_actions_feed: `ml/data_ext/corporate_actions_feed.csv`
- corporate_actions_all: `ml/data_ext/corporate_actions_all.csv`
- price_break_flags: `ml/data_ext/price_break_flags.csv`
- etf_list: `ml/data_ext/etf_list.csv`
- equity_master: `ml/data_ext/equity_master.csv`
- session_staging: `ml/data_ext/staging/sessions_upsert.parquet + sessions_delete.json`
- exports_v2: `ml/results/improve/cache/{eod_export_v2.parquet, features_prices_export_v2.parquet}`
- write_script: `ml/integrity/write_phase.py (idempotent; --extra-staging for ml/data_hist/ rows)`
- v2_dataset: `ml/data_5y_v2/{model_dataset.parquet, manifest.json, splits.json}`
- reports: `ml/results/improve/integrity/{integrity.json, INTEGRITY.md, sessions.json, corporate_actions.json, etf.json, write_phase_real.json, write_phase_rehearsal*.json, write_phase_dryrun.json, v1_vs_v2.json, history_special_sessions.json}`
- raw_downloads: `ml/data_raw/pr/ (PR bundles; sec/, cm/, mto/, master/ check files; _manifest.csv)`
