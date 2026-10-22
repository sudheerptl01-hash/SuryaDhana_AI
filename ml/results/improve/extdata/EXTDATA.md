# P3 external data: sources, staging tables, feature families F1-F4

Build tag **v1**: prices from `/home/user/SuryaDhana_AI/ml/results/improve/cache/eod_export_v1.parquet`, spot and sessions from `/home/user/SuryaDhana_AI/ml/results/improve/cache/eod_export_v1.parquet`, comparison dataset `/home/user/SuryaDhana_AI/ml/data_5y/model_dataset.parquet`.

Built 2026-10-22T13:43:59 by `ml/extdata/run_all.py` (seed 108). Every number below is quoted from `ml/results/improve/extdata/extdata.json`. The feature families are the pre-registered F1-F4 of `ml/IMPROVEMENT_PLAN.md` section 2-P3; this stream builds them, the lead runs the A/Bs. Nothing here touched `nse_market.duckdb`.

## 1. Summary

| Check | Result |
|---|---|
| (a) 100 random cells of F2/F3 recomputed by an independent code path from raw files dated <= t | **PASS** (900 of 900 values equal) |
| (b) inputs dated after t removed, every session of 2024-07 | **PASS** (22 sessions) |
| (c) shift test (future bars appended; rows <= T0 unchanged) | **PASS** (T0 = 2023-12-29, 2025-06-30) |
| Base series (mom_20, ret_63d, ret_126d, deliv_pct_sma_20, atr_pct) vs the v1 dataset | **exact** (max abs diff 0, identical row set and NaN pattern) |
| F&O unit continuity at the 2024-07 format switch | OI identity holds for 542 of 542 futures contracts |
| F&O stock symbols found in the EOD export on the same date | 1.0000 |

Output rows: `extra_features.parquet` 1,357,383 rows x 18 features (2,480 tickers, 2022-10-03 to 2026-10-16; the row set equals the dataset's row set exactly); `market_state.parquet` one row per EOD date from 2022-10-03 with 14 features.

**The one material finding is a look-ahead in the industry lists (section 8).** The NSE constituent lists are a 2026-10-19 snapshot. Being in them predicts the 20-day label: the snapshot flag's pooled AUC exceeds a point-in-time size flag's by about 0.015 to 0.03 in 2022-2025, roughly five to ten times the A/B pass mark of +0.003. F2 is built so that no NaN pattern marks membership (two deviations from the brief, section 4), but F2 still makes the partition easier to recover. The lead registered the placebo control AB2P as plan amendment A3 (section 8).

## 2. Sources and coverage

Expected sessions: 1251 = 1245 EOD-export dates + the six special sessions P1 adds (2023-11-12, 2024-03-02, 2024-05-18, 2025-02-01, 2025-10-21, 2026-02-01). Downloads: archives.nseindia.com, browser user agent, one request in flight per file type, random 1.0-2.0 s pause, 60 s back-off with halved rate on 403/429/5xx (log: `ml/results/improve/extdata/log.txt`). Every file's internal date (F&O TIMESTAMP / TradDt, index `Index Date`, participant title line) is checked against its file-name date.

| Source | Files in window | HTTP 404 dates | Content-date exclusions | EOD sessions without a file |
|---|---:|---|---|---|
| F&O bhavcopy | 1,251 | 75 dates: 2016-10-11, 2016-10-12, 2016-10-31, 2016-11-14, 2017-01-26, 2017-02-24, 2017-03-13, 2017-04-04, 2017-04-14, 2017-05-01, 2017-06-26, 2017-08-15, ... (full list in the JSON) | 0 | none |
| ind_close_all | 1,251 | 74 dates: 2016-10-11, 2016-10-12, 2016-10-31, 2016-11-14, 2017-01-26, 2017-02-24, 2017-03-13, 2017-04-04, 2017-04-14, 2017-05-01, 2017-06-26, 2017-08-15, ... (full list in the JSON) | 0 | none |
| participant OI | 1,249 | 76 dates: 2016-10-11, 2016-10-12, 2016-10-31, 2016-11-14, 2017-01-26, 2017-02-24, 2017-03-13, 2017-04-04, 2017-04-14, 2017-05-01, 2017-06-26, 2017-08-15, ... (full list in the JSON) | 92 | 2023-10-31, 2025-09-19 |

Files per year (files with a valid internal date / expected sessions):

| Year | F&O bhavcopy | ind_close_all | participant OI |
|---|---:|---:|---:|
| 2021 | 62 / 63 | 62 / 63 | 62 / 63 |
| 2022 | 248 / 248 | 248 / 248 | 248 / 248 |
| 2023 | 245 / 246 | 245 / 246 | 244 / 246 |
| 2024 | 248 / 249 | 248 / 249 | 248 / 249 |
| 2025 | 249 / 249 | 249 / 249 | 248 / 249 |
| 2026 | 196 / 196 | 196 / 196 | 196 / 196 |

Special sessions (status per source):

| Session | F&O bhavcopy | ind_close_all | participant OI |
|---|---|---|---|
| 2023-11-12 | ok | ok | ok |
| 2024-03-02 | ok | ok | ok |
| 2024-05-18 | ok | ok | ok |
| 2025-02-01 | ok | ok | ok |
| 2025-10-21 | ok | ok | ok |
| 2026-02-01 | ok | ok | ok |

**Mis-dated EOD sessions (finding for P1).** Three EOD-export dates hold a session that traded on another day. The bar sequence is continuous, so a prev_close scan cannot see them; the archive does, because every external file for those dates is a 404 while the true date's files exist and carry their own date inside:

| Archive date (true session) | EOD-export date | Evidence |
|---|---|---|
| 2021-11-04 | 2021-11-05 | Muhurat session; volumes about 1/7 of normal (P1 already re-dates this one) |
| 2023-06-28 | 2023-06-29 | NSE moved the Bakri Id holiday to 06-29; the ingest's calendar skipped 06-28 |
| 2024-01-20 | 2024-01-22 | Saturday session; 22 Jan 2024 was a market holiday; volumes about 1/4 of normal |

External series are joined to the EOD dates through this alias, applied only where the export holds the alias date and not the true date (inert on a re-dated v2 export).

F&O membership (stocks with a stock future, per F&O file):

| Year | Mean per day | Min | Max | Distinct tickers | Universe rows that are members |
|---|---:|---:|---:|---:|---:|
| 2016 | 175.0 | 175 | 175 | 175 | n/a |
| 2017 | 200.3 | 174 | 214 | 218 | n/a |
| 2018 | 206.4 | 200 | 211 | 211 | n/a |
| 2019 | 175.6 | 144 | 200 | 202 | n/a |
| 2020 | 140.2 | 136 | 144 | 153 | n/a |
| 2021 | 163.5 | 140 | 197 | 197 | n/a |
| 2022 | 196.2 | 191 | 199 | 203 | 0.1836 |
| 2023 | 186.8 | 183 | 191 | 192 | 0.1605 |
| 2024 | 184.9 | 178 | 223 | 231 | 0.1279 |
| 2025 | 216.2 | 208 | 227 | 258 | 0.1517 |
| 2026 | 209.3 | 206 | 213 | 225 | 0.1353 |

Industry-map coverage of the universe (rows with an NSE industry; `industry_map.csv` has 755 symbols from the Nifty 500, Midcap 150, Smallcap 250, Microcap 250 and Nifty 50 lists, no conflicting labels):

| Year | Universe rows | Share of rows with industry | Same, ex-ETF | ETF-group share | Share of tickers |
|---|---:|---:|---:|---:|---:|
| 2022 | 64,791 | 0.5143 | 0.5289 | 0.0275 | 0.4395 |
| 2023 | 284,086 | 0.4896 | 0.5033 | 0.0272 | 0.3781 |
| 2024 | 356,596 | 0.4329 | 0.4540 | 0.0466 | 0.3489 |
| 2025 | 350,554 | 0.4805 | 0.5154 | 0.0677 | 0.3838 |
| 2026 | 301,356 | 0.4770 | 0.5196 | 0.0819 | 0.3759 |

## 3. Staging tables (`ml/data_ext/`)

| File | Rows | Key / content |
|---|---:|---|
| `fo_daily_stock.parquet` | 465,528 | (date, ticker) with a stock future or option: near/next settle and expiry, days to expiry, total futures OI (shares) and its change, futures volume (contracts) and turnover (rupees), call/put OI (shares) and volume (contracts), n_strikes, spot_close (EOD export), basis_near, source_format |
| `index_daily.parquet` | 247,808 | (date, index_name): open, high, low, close, pct_change, volume, turnover_cr, pe, pb, div_yield |
| `fo_participant_oi.parquet` | 11,975 | (date, client_type in Client/DII/FII/Pro/TOTAL), 14 numeric columns in contracts (wide in instruments, long in client type) |
| `industry_map.csv` | 755 | symbol, industry, source_list (first list wins: Nifty 500, Midcap 150, Smallcap 250, Microcap 250, Nifty 50) |
| `sector_index_map.csv` | 15 | industry -> index name in ind_close_all (+ fallback) |
| `equity_master.csv` | 2,619 | EQUITY_L.csv: symbol, company_name, series, listing_date, paid_up_value, market_lot, isin, face_value (kept from P1) |

All three tables carry a `window` column: `main` for rows from 2021-10-01 and `hist` for 2016-10-03..2021-09-30 (section 11). The schemas and the participant column map are in `extdata.json` (`staging_schemas`).

Units and conventions (verified, section 7): open interest is in **shares** in both F&O formats (legacy `OPEN_INT`, UDiFF `OpnIntrst`); traded volume in **contracts** in both (`CONTRACTS`, `TtlTradgVol`); turnover in rupees (`VAL_INLAKH` x 1e5, `TtlTrfVal`). Roll: near = the smallest expiry >= t (on the expiry day the expiring contract is still near, 0 days to expiry); next = the second smallest; days to expiry in calendar days; UDiFF uses `FininstrmActlXpryDt`. basis_near = (near settle / spot close - 1) x 365 / days to expiry, NaN below 2 days. n_strikes = distinct strike prices over all option expiries. Futures rows without a spot close: 219,509 (sessions without an EOD bar in the v1 export).

Sector-index map, checked against all 2,489 parsed index files (share of files containing each index, and its first date in the files):

| Industry | Index | Fallback | Share of files with the index | First date |
|---|---|---|---:|---|
| Financial Services | Nifty Financial Services | - | 1.0000 | 2016-10-03 |
| Information Technology | Nifty IT | - | 1.0000 | 2016-10-03 |
| Healthcare | Nifty Healthcare Index | Nifty Pharma | 0.5870 | 2020-11-19 |
| Automobile and Auto Components | Nifty Auto | - | 1.0000 | 2016-10-03 |
| Fast Moving Consumer Goods | Nifty FMCG | - | 1.0000 | 2016-10-03 |
| Metals & Mining | Nifty Metal | - | 1.0000 | 2016-10-03 |
| Realty | Nifty Realty | - | 1.0000 | 2016-10-03 |
| Oil Gas & Consumable Fuels | Nifty Oil & Gas | - | 0.6710 | 2020-01-27 |
| Power | Nifty Energy | - | 1.0000 | 2016-10-03 |
| Consumer Durables | Nifty Consumer Durables | - | 0.6710 | 2020-01-27 |
| Media Entertainment & Publication | Nifty Media | - | 1.0000 | 2016-10-03 |
| Capital Goods | Nifty Infrastructure | - | 1.0000 | 2016-10-03 |
| Construction | Nifty Infrastructure | - | 1.0000 | 2016-10-03 |
| Chemicals | Nifty Commodities | - | 1.0000 | 2016-10-03 |
| Construction Materials | Nifty Commodities | - | 1.0000 | 2016-10-03 |

Unmapped industries (Consumer Services, Services, Telecommunication, Textiles, Utilities, Diversified, Forest Materials) follow the brief's 'others -> none'. `Nifty Consumer Services` exists in the files but was not added, because the map was proposed before any result existed.

## 4. Feature families

- **F1_market_state** (10): `mkt_ret_20`, `mkt_ret_63`, `mkt_dd_252`, `mkt_vol_20`, `mkt_breadth_200`, `sessions_since_selloff`, `cs_dispersion_20`, `vix_close`, `vix_chg_20`, `nifty50_pe`
- **F2_sector** (10): `ind_mom_20`, `ind_ret_63`, `rel_mom_20`, `rel_ret_126`, `rel_deliv`, `indn_rank_mom_20`, `indn_rank_ret_126`, `indn_rank_deliv_sma`, `indn_rank_atr`, `secidx_ret_20`
- **F3_fo** (8): `fo_member`, `fut_basis_near`, `fut_oi_chg_5`, `fut_oi_chg_20`, `fut_oi_z_60`, `pcr_oi`, `pcr_chg_5`, `opt_oi_to_turnover`
- **F4_flows** (4): `fii_idx_fut_net`, `fii_idx_fut_net_chg_5`, `fii_stk_fut_net`, `client_idx_pcr`

Definitions are in `extdata.json` (`definitions`) and `ml/data_ext/extra_features_manifest.json`. Each external source's sessions are counted on its own file calendar, and EOD-derived series on the EOD export's calendar. Same-day end-of-day prints are allowed (labels enter at the next open).

Conventions fixed before any IC was computed:

1. Market and industry aggregates exclude ETFs (the v2 universe definition), so stock values are the same joined to v1 or v2. ETF rows (v1 only) get F2 values inside their own `ETF` group. ETF source: ml/data_ext/etf_list.csv (P1; 469 rows; sha256 7b9163f85448f256) (469 tickers).
2. The EW market return drops single-day moves above 22% (the repo's corporate-action threshold; 424 name-days dropped). cs_dispersion_20 is taken over names with `flag_split_20d` == 0. The median EW membership is 1304.0000 names.
3. **Deviation from the brief: names without an NSE industry form an explicit `Unclassified` group** (the brief did not say). A NaN would mark today's index members (section 8).
4. **Deviation from the brief: `secidx_ret_20` for unmapped industries, Unclassified names and ETFs is the Nifty 500 20-session return, not NaN** (796,441 rows). Under the brief, the NaN pattern itself carries the membership look-ahead (section 8). `build(policy={'unclassified': 'nan', 'secidx_unmapped': 'nan'})` reproduces the literal brief.
5. Industry groups with fewer than 5 non-NaN names that date give NaN (the brief). This affects Diversified, Forest Materials and Utilities, about 0.4% of rows.
6. `fo_member` is NaN on a date whose F&O file is missing. The other F3 values are NaN for non-members. Zero futures OI is treated as missing in the log changes and the z-score.

## 5. Point-in-time checks

**(a) Independent recomputation: **PASS**.** Sample: 25 random dates (seed 108), 2 F2 cells and 2 F3 cells each, 100 cells in total (100 fully equal). 900 of 900 values are equal. Method: independent code path: csv-module readers of the raw F&O zips and ind_close_all files dated <= t, numpy loops over EOD bars dated <= t (Wilder ATR by explicit recursion, medians/ranks by counting). Tolerance: rtol 1e-09, 1e-06 for the rolling z-score, and NaN equals NaN. Runtime 503.2 s.

**(b) File removal, 2024-07: **PASS**.** For each of the 22 sessions t, every raw file dated after t and every EOD bar after t was removed from the input set, and the whole pipeline (parse + features) was re-run. The rows at t were then compared with the full build. For the last session the removal was literal: a directory holding only the files dated <= t, parsed from the raw bytes with no cache. Runtime 373.9 s.

| t | Files removed (F&O / index / participant) | Stock rows at t | Identical (stock / market) |
|---|---|---:|---|
| 2024-07-01 | 570 / 570 / 569 | 1,485 | yes / yes |
| 2024-07-02 | 569 / 569 / 568 | 1,485 | yes / yes |
| 2024-07-03 | 568 / 568 / 567 | 1,487 | yes / yes |
| 2024-07-04 | 567 / 567 / 566 | 1,496 | yes / yes |
| 2024-07-05 | 566 / 566 / 565 | 1,505 | yes / yes |
| 2024-07-08 | 565 / 565 / 564 | 1,501 | yes / yes |
| 2024-07-09 | 564 / 564 / 563 | 1,505 | yes / yes |
| 2024-07-10 | 563 / 563 / 562 | 1,513 | yes / yes |
| 2024-07-11 | 562 / 562 / 561 | 1,510 | yes / yes |
| 2024-07-12 | 561 / 561 / 560 | 1,512 | yes / yes |
| 2024-07-15 | 560 / 560 / 559 | 1,522 | yes / yes |
| 2024-07-16 | 559 / 559 / 558 | 1,520 | yes / yes |
| 2024-07-18 | 558 / 558 / 557 | 1,515 | yes / yes |
| 2024-07-19 | 557 / 557 / 556 | 1,514 | yes / yes |
| 2024-07-22 | 556 / 556 / 555 | 1,514 | yes / yes |
| 2024-07-23 | 555 / 555 / 554 | 1,515 | yes / yes |
| 2024-07-24 | 554 / 554 / 553 | 1,515 | yes / yes |
| 2024-07-25 | 553 / 553 / 552 | 1,516 | yes / yes |
| 2024-07-26 | 552 / 552 / 551 | 1,515 | yes / yes |
| 2024-07-29 | 551 / 551 / 550 | 1,517 | yes / yes |
| 2024-07-30 | 550 / 550 / 549 | 1,520 | yes / yes |
| 2024-07-31 (literal) | 549 / 549 / 548 | 1,523 | yes / yes |

**(c) Shift test: **PASS**.** Inputs were truncated at T0 and every row dated <= T0 was compared with the full build, for all 32 features. Runtime 20.1 s.

| T0 | Stock rows compared | Identical | Market rows compared | Identical |
|---|---:|---|---:|---|
| 2023-12-29 | 348,877 | yes | 307 | yes |
| 2025-06-30 | 877,128 | yes | 676 | yes |

The static inputs are held fixed in (b) and (c): the industry lists, the sector map and the ETF list. Their point-in-time status is the subject of section 8.

## 6. Base series vs the v1 dataset

Dataset `/home/user/SuryaDhana_AI/ml/data_5y/model_dataset.parquet`. Row sets: dataset 1,357,383, this stream 1,357,383, common 1,357,383, only in the dataset 0, only here 0 (rows only here are ETF rows when the dataset excludes ETFs).

| Series | Rows both finite | Max abs diff | Rows with diff > 1e-9 | NaN-pattern mismatches |
|---|---:|---:|---:|---:|
| mom_20 | 1,350,680 | 0.0 | 0 | 0 |
| ret_63d | 1,325,992 | 0.0 | 0 | 0 |
| ret_126d | 1,291,363 | 0.0 | 0 | 0 |
| deliv_pct_sma_20 | 1,307,477 | 0.0 | 0 | 0 |
| atr_pct | 1,354,925 | 0.0 | 0 | 0 |

## 7. Integrity of the external data

- **Units across the format switch.** For 542 futures contracts, the legacy 2024-07-05 OPEN_INT equals the UDiFF 2024-07-08 OpnIntrst minus ChngInOpnIntrst in 542 cases (max relative deviation 0.0). UDiFF turnover / (contracts x lot x close) has median 1.0007, and UDiFF OI is divisible by the lot size in 1.0000 of rows. OI is in shares in both formats (identity holds across the switch); UDiFF TtlTradgVol is in contracts (turnover = contracts x lot x price).
- **Symbols.** 246,019 futures rows on EOD dates; the share whose ticker exists in the EOD export the same day is 1.00000 (0 unmatched: {}).
- **Participant OI.** 2,395 files. Long equals short in the TOTAL row for futures in a share 0.9983 of files. The four client types sum to TOTAL within 1 contract in 0.9491 (exactly in 0.5031; NSE rounds index-option sums by up to 1 contract; max deviation 2.0).
- **Annualised near-month basis** (median by year, the cost of carry): 2021 0.060, 2022 0.057, 2023 0.074, 2024 0.068, 2025 0.058, 2026 0.047. The 1st-99th percentiles are in the JSON.

## 8. The industry-list look-ahead

The constituent lists exist only as of the download date (2026-10-19), so the industry label is not point in time. The label itself barely changes over time; the problem is *which* names carry one. A name is classified only if it is in one of the five indices today, and names that rose since 2022 are over-represented among them. Reporting-only diagnostics follow (labels from the v1 dataset, ex-ETF universe rows, y_clean_20d):

| Year | Share classified | Beat rate classified | Beat rate unclassified | AUC of snapshot flag | AUC of PIT size flag (top N by turnover) |
|---|---:|---:|---:|---:|---:|
| 2022 | 0.5312 | 0.5260 | 0.4638 | 0.5310 | 0.5013 |
| 2023 | 0.5053 | 0.5360 | 0.4719 | 0.5320 | 0.5174 |
| 2024 | 0.4546 | 0.5479 | 0.4569 | 0.5451 | 0.5236 |
| 2025 | 0.5162 | 0.5408 | 0.4297 | 0.5555 | 0.5393 |
| 2026 | 0.5247 | 0.5105 | 0.4893 | 0.5106 | 0.5079 |

Reading: part of the snapshot flag's edge is a genuine size effect, since the PIT top-N flag also exceeds 0.5 in 2023-2025. The gap between the two columns is the future information in the snapshot. It shrinks to almost nothing in 2026, when the snapshot is nearly current.

Can a model recover the partition from the features it would see? LightGBM predicting the snapshot flag (no return labels), trained on 2023 and scored on 2025:

| Feature set | Leak-safe F2 (this build) | Literal brief (NaN for unclassified/unmapped) |
|---|---:|---:|
| base10 | 0.9027 | 0.9027 |
| base10+F2 | 0.9329 | 0.9973 |
| base10+F2+F1 | 0.9520 | 0.9974 |
| F2_only | 0.6745 | 0.9955 |

Under the literal brief, F2 alone identifies the partition almost perfectly, because its NaN pattern is the partition. The leak-safe build lowers that, but F2 still adds to what the base features already reveal. In this build the non-NaN indicator of secidx_ret_20 has AUC 0.5000 against the label.

**Placebo control (plan amendment A3, 2026-10-22).** `ml/data_ext/extra_features_placebo_f2.parquet` holds the F2 columns rebuilt with the industry labels permuted among the classified symbols (seed 108), with the same Unclassified and ETF groups, the same coverage, the same column names and the same F3 columns, so the harness loads it with `--extra`. AB2P = control + these columns. AB2, and the F2 share of AB5, counts as industry information only if AB2 passes the primary mark **and** beats AB2P by >= +0.003 with the paired CI excluding zero. The secondary reading is the AUC on classified rows only. F1, F3 and F4 do not depend on the lists: F&O membership comes from the daily bhavcopy, and the market state from the point-in-time universe.

## 9. NaN share per feature

| Feature | NaN share (all rows) | Among F&O members | By year |
|---|---:|---:|---|
| ind_mom_20 | 0.0040 | n/a | 2022 0.005, 2023 0.004, 2024 0.004, 2025 0.004, 2026 0.004 |
| ind_ret_63 | 0.0040 | n/a | 2022 0.005, 2023 0.004, 2024 0.004, 2025 0.004, 2026 0.004 |
| rel_mom_20 | 0.0089 | n/a | 2022 0.008, 2023 0.008, 2024 0.008, 2025 0.010, 2026 0.009 |
| rel_ret_126 | 0.0526 | n/a | 2022 0.036, 2023 0.040, 2024 0.053, 2025 0.056, 2026 0.063 |
| rel_deliv | 0.0406 | n/a | 2022 0.029, 2023 0.031, 2024 0.058, 2025 0.039, 2026 0.034 |
| indn_rank_mom_20 | 0.0089 | n/a | 2022 0.008, 2023 0.008, 2024 0.008, 2025 0.010, 2026 0.009 |
| indn_rank_ret_126 | 0.0526 | n/a | 2022 0.036, 2023 0.040, 2024 0.053, 2025 0.056, 2026 0.063 |
| indn_rank_deliv_sma | 0.0406 | n/a | 2022 0.029, 2023 0.031, 2024 0.058, 2025 0.039, 2026 0.034 |
| indn_rank_atr | 0.0058 | n/a | 2022 0.006, 2023 0.006, 2024 0.005, 2025 0.006, 2026 0.006 |
| secidx_ret_20 | 0.0000 | n/a | 2022 0.000, 2023 0.000, 2024 0.000, 2025 0.000, 2026 0.000 |
| fo_member | 0.0000 | n/a | 2022 0.000, 2023 0.000, 2024 0.000, 2025 0.000, 2026 0.000 |
| fut_basis_near | 0.8678 | 0.0889 | 2022 0.831, 2023 0.855, 2024 0.884, 2025 0.862, 2026 0.876 |
| fut_oi_chg_5 | 0.8552 | 0.0024 | 2022 0.816, 2023 0.840, 2024 0.873, 2025 0.849, 2026 0.865 |
| fut_oi_chg_20 | 0.8563 | 0.0099 | 2022 0.817, 2023 0.840, 2024 0.875, 2025 0.850, 2026 0.866 |
| fut_oi_z_60 | 0.8577 | 0.0195 | 2022 0.817, 2023 0.840, 2024 0.875, 2025 0.854, 2026 0.867 |
| pcr_oi | 0.8549 | 0.0000 | 2022 0.816, 2023 0.840, 2024 0.872, 2025 0.848, 2026 0.865 |
| pcr_chg_5 | 0.8552 | 0.0024 | 2022 0.816, 2023 0.840, 2024 0.873, 2025 0.849, 2026 0.865 |
| opt_oi_to_turnover | 0.8549 | 0.0000 | 2022 0.816, 2023 0.840, 2024 0.872, 2025 0.848, 2026 0.865 |
| mkt_ret_20 (by date) | 0.0000 | - | 0 NaN dates:  |
| mkt_ret_63 (by date) | 0.0000 | - | 0 NaN dates:  |
| mkt_dd_252 (by date) | 0.0000 | - | 0 NaN dates:  |
| mkt_vol_20 (by date) | 0.0000 | - | 0 NaN dates:  |
| mkt_breadth_200 (by date) | 0.0000 | - | 0 NaN dates:  |
| sessions_since_selloff (by date) | 0.0000 | - | 0 NaN dates:  |
| cs_dispersion_20 (by date) | 0.0000 | - | 0 NaN dates:  |
| vix_close (by date) | 0.0000 | - | 0 NaN dates:  |
| vix_chg_20 (by date) | 0.0000 | - | 0 NaN dates:  |
| nifty50_pe (by date) | 0.0000 | - | 0 NaN dates:  |
| fii_idx_fut_net (by date) | 0.0020 | - | 2 NaN dates: 2023-10-31, 2025-09-19 |
| fii_idx_fut_net_chg_5 (by date) | 0.0020 | - | 2 NaN dates: 2023-10-31, 2025-09-19 |
| fii_stk_fut_net (by date) | 0.0020 | - | 2 NaN dates: 2023-10-31, 2025-09-19 |
| client_idx_pcr (by date) | 0.0020 | - | 2 NaN dates: 2023-10-31, 2025-09-19 |

## 10. Descriptive monthly IC (REPORTING ONLY)

REPORTING ONLY - descriptive; not used to add, drop or transform any feature; family membership fixed in ml/IMPROVEMENT_PLAN.md. Target: y_excess_20d on y_clean_20d rows (v1 dataset). Each value is the mean of daily Spearman ICs within a calendar month (dates with >= 50 pairs). F1 and F4 are one value per date, so they have no cross-sectional IC.

| Feature | Months | Months > 0 | Mean monthly IC |
|---|---:|---:|---:|
| ind_mom_20 | 48 | 31 | 0.0396 |
| ind_ret_63 | 48 | 31 | 0.0394 |
| rel_mom_20 | 48 | 24 | -0.0067 |
| rel_ret_126 | 48 | 27 | 0.0114 |
| rel_deliv | 48 | 35 | 0.0446 |
| indn_rank_mom_20 | 48 | 25 | -0.0050 |
| indn_rank_ret_126 | 48 | 28 | 0.0122 |
| indn_rank_deliv_sma | 48 | 37 | 0.0454 |
| indn_rank_atr | 48 | 22 | -0.0087 |
| secidx_ret_20 | 48 | 29 | 0.0062 |
| fo_member | 48 | 27 | 0.0257 |
| fut_basis_near | 48 | 38 | 0.0341 |
| fut_oi_chg_5 | 48 | 26 | 0.0061 |
| fut_oi_chg_20 | 48 | 27 | 0.0096 |
| fut_oi_z_60 | 48 | 33 | 0.0141 |
| pcr_oi | 48 | 33 | 0.0367 |
| pcr_chg_5 | 48 | 29 | 0.0006 |
| opt_oi_to_turnover | 48 | 25 | 0.0095 |

## 11. History extension (2016-10-03..2021-09-30, for P4)

Candidate days 1308 (every weekday plus the weekend special sessions; a 404 marks a holiday). The rows are appended to the same staging tables with the same schema. Spot close for the F&O rows: P4 equity_eod_2016_2021.parquet not final yet: hist spot_close/basis NaN (share of futures rows with a spot: 0.0000). P4 session list: not available at build time.

| Source | Sessions with a file | 404 days | Content-date exclusions | P4 sessions without a file | Files on non-P4 days |
|---|---:|---:|---:|---|---|
| F&O bhavcopy | 1,237 | 71 | 0 | none | none |
| ind_close_all | 1,238 | 70 | 0 | none | none |
| participant OI | 1,146 | 70 | 92 | none | none |

Files per year: F&O bhavcopy 2016 62, 2017 248, 2018 246, 2019 245, 2020 252, 2021 184; ind_close_all 2016 62, 2017 248, 2018 246, 2019 245, 2020 252, 2021 185; participant OI 2016 62, 2017 248, 2018 245, 2019 240, 2020 248, 2021 103.

F&O members per day (mean by year): 2016 175.0, 2017 200.3, 2018 206.4, 2019 175.6, 2020 140.2, 2021 155.8.

## 12. Reproduction

```
OMP_NUM_THREADS=2 python3 -I ml/extdata/download.py --window main   # resume-safe
OMP_NUM_THREADS=2 python3 -I ml/extdata/run_all.py                  # parse, lists, features, checks, report
```

Code: `ml/extdata/` (common, download, parse, lists, features, checks, report, run_all). Raw files: `ml/data_raw/{fo,indices,participant,lists}/` (gitignored). Staging: `ml/data_ext/` (gitignored).
