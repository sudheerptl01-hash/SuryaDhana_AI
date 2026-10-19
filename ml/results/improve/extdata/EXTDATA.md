# P3 external data: sources, staging tables, feature families F1-F4

Built 2026-10-19T13:31:36 by `ml/extdata/run_all.py` (seed 108). Every number below is quoted from `ml/results/improve/extdata/extdata.json`. The feature families are the pre-registered F1-F4 of `ml/IMPROVEMENT_PLAN.md` section 2-P3; this stream builds them, the lead runs the A/Bs. Nothing here touched `nse_market.duckdb`.

## 1. Summary

| Check | Result |
|---|---|
| (a) - random cells of F2/F3 recomputed by an independent code path from raw files dated <= t | not run |
| (b) inputs dated after t removed, every session of - | not run |
| (c) shift test (future bars appended; rows <= T0 unchanged) | not run |
| Base series (mom_20, ret_63d, ret_126d, deliv_pct_sma_20, atr_pct) vs v1 dataset | **exact** (max abs diff 0, identical row set and NaN pattern) |
| F&O unit continuity at the 2024-07 format switch | OI identity holds for 542 of 542 futures contracts |
| F&O stock symbols found in the EOD export on the same date | 1.0000 |

Output rows: `extra_features.parquet` 1,357,383 rows x 18 features (2,480 tickers, 2022-10-03 to 2026-10-16; the row set equals the v1 dataset's exactly); `market_state.parquet` one row per EOD date from 2022-10-03 with 14 features.

**The one material finding is a look-ahead in the industry lists (section 8).** The NSE constituent lists are a 2026-10-19 snapshot. Being in them predicts the 20-day label: the snapshot flag's pooled AUC exceeds a point-in-time size flag's by about 0.015 to 0.03 in 2022-2025, roughly five to ten times the A/B pass mark of +0.003. F2 is built so that no NaN pattern marks membership (two deviations from the brief, section 4), but F2 still makes the partition easier to recover. AB2 and AB5 should not be read without the placebo control described in section 8.

## 2. Sources and coverage

Expected sessions: 1251 = 1245 EOD-export dates + the six special sessions P1 adds (2023-11-12, 2024-03-02, 2024-05-18, 2025-02-01, 2025-10-21, 2026-02-01). Downloads: archives.nseindia.com, browser user agent, one request in flight per file type, random 1.0-2.0 s pause, 60 s back-off with halved rate on 403/429/5xx (log: `ml/results/improve/extdata/log.txt`). Every file's internal date (F&O TIMESTAMP / TradDt, index `Index Date`, participant title line) is checked against its file-name date.

| Source | Files in window | HTTP 404 dates | Content-date exclusions | EOD sessions without a file |
|---|---:|---|---|---|
| F&O bhavcopy | 957 | 2021-11-05, 2023-06-29, 2024-01-22 | 0 | 2021-11-05, 2023-06-29, 2024-01-22, 2025-07-25, 2025-07-28, 2025-07-29, 2025-07-31, 2025-08-01, 2025-08-04, 2025-08-05, 2025-08-06, 2025-08-07, 2025-08-08, 2025-08-11, 2025-08-12, 2025-08-13, 2025-08-14, 2025-08-18, 2025-08-19, 2025-08-20, 2025-08-21, 2025-08-22, 2025-08-25, 2025-08-26, 2025-08-28, 2025-08-29, 2025-09-01, 2025-09-02, 2025-09-03, 2025-09-04, 2025-09-08, 2025-09-09, 2025-09-10, 2025-09-11, 2025-09-12, 2025-09-15, 2025-09-16, 2025-09-17, 2025-09-18, 2025-09-19, 2025-09-22, 2025-09-23, 2025-09-24, 2025-09-25, 2025-09-26, 2025-09-29, 2025-09-30, 2025-10-01, 2025-10-03, 2025-10-06, 2025-10-07, 2025-10-08, 2025-10-09, 2025-10-10, 2025-10-14, 2025-10-15, 2025-10-16, 2025-10-17, 2025-10-20, 2025-10-23, 2025-10-24, 2025-10-27, 2025-10-28, 2025-10-29, 2025-10-30, 2025-10-31, 2025-11-03, 2025-11-04, 2025-11-06, 2025-11-07, 2025-11-10, 2025-11-11, 2025-11-12, 2025-11-13, 2025-11-14, 2025-11-17, 2025-11-18, 2025-11-20, 2025-11-21, 2025-11-24, 2025-11-25, 2025-11-26, 2025-11-27, 2025-11-28, 2025-12-01, 2025-12-02, 2025-12-03, 2025-12-04, 2025-12-05, 2025-12-08, 2025-12-09, 2025-12-10, 2025-12-11, 2025-12-12, 2025-12-15, 2025-12-16, 2025-12-17, 2025-12-18, 2025-12-19, 2025-12-22, 2025-12-23, 2025-12-26, 2025-12-29, 2025-12-30, 2025-12-31, 2026-01-01, 2026-01-02, 2026-01-05, 2026-01-06, 2026-01-07, 2026-01-08, 2026-01-09, 2026-01-12, 2026-01-13, 2026-01-14, 2026-01-16, 2026-01-19, 2026-01-20, 2026-01-21, 2026-01-22, 2026-01-23, 2026-01-27, 2026-01-28, 2026-01-29, 2026-01-30, 2026-02-02, 2026-02-03, 2026-02-04, 2026-02-05, 2026-02-06, 2026-02-09, 2026-02-10, 2026-02-11, 2026-02-12, 2026-02-13, 2026-02-16, 2026-02-17, 2026-02-18, 2026-02-19, 2026-02-20, 2026-02-23, 2026-02-24, 2026-02-25, 2026-02-26, 2026-02-27, 2026-03-02, 2026-03-04, 2026-03-05, 2026-03-06, 2026-03-10, 2026-03-11, 2026-03-12, 2026-03-13, 2026-03-16, 2026-03-17, 2026-03-18, 2026-03-19, 2026-03-20, 2026-03-23, 2026-03-24, 2026-03-25, 2026-03-27, 2026-03-30, 2026-04-01, 2026-04-02, 2026-04-06, 2026-04-07, 2026-04-08, 2026-04-09, 2026-04-10, 2026-04-13, 2026-04-15, 2026-04-16, 2026-04-20, 2026-04-21, 2026-04-22, 2026-04-23, 2026-04-24, 2026-04-27, 2026-04-28, 2026-04-29, 2026-04-30, 2026-05-04, 2026-05-05, 2026-05-06, 2026-05-07, 2026-05-08, 2026-05-11, 2026-05-12, 2026-05-13, 2026-05-14, 2026-05-15, 2026-05-18, 2026-05-19, 2026-05-20, 2026-05-21, 2026-05-22, 2026-05-26, 2026-05-27, 2026-05-29, 2026-06-01, 2026-06-02, 2026-06-03, 2026-06-04, 2026-06-05, 2026-06-08, 2026-06-09, 2026-06-10, 2026-06-11, 2026-06-12, 2026-06-15, 2026-06-16, 2026-06-17, 2026-06-18, 2026-06-19, 2026-06-22, 2026-06-23, 2026-06-24, 2026-06-25, 2026-06-29, 2026-06-30, 2026-07-02, 2026-07-03, 2026-07-06, 2026-07-07, 2026-07-08, 2026-07-09, 2026-07-10, 2026-07-13, 2026-07-14, 2026-07-15, 2026-07-16, 2026-07-17, 2026-07-20, 2026-07-21, 2026-07-22, 2026-07-23, 2026-07-24, 2026-07-27, 2026-07-28, 2026-07-29, 2026-07-30, 2026-07-31, 2026-08-03, 2026-08-04, 2026-08-06, 2026-08-07, 2026-08-10, 2026-08-11, 2026-08-12, 2026-08-13, 2026-08-14, 2026-08-17, 2026-08-18, 2026-08-19, 2026-08-20, 2026-08-21, 2026-08-24, 2026-08-25, 2026-08-26, 2026-08-27, 2026-08-28, 2026-08-31, 2026-09-01, 2026-09-02, 2026-09-03, 2026-09-04, 2026-09-07, 2026-09-08, 2026-09-10, 2026-09-11, 2026-09-15, 2026-09-16, 2026-09-17, 2026-09-18, 2026-09-21, 2026-09-22, 2026-09-23, 2026-09-24, 2026-09-25, 2026-09-28, 2026-09-29, 2026-09-30, 2026-10-01, 2026-10-05, 2026-10-06, 2026-10-07, 2026-10-08, 2026-10-09, 2026-10-12, 2026-10-13, 2026-10-14, 2026-10-15 |
| ind_close_all | 1,136 | 2021-11-05, 2023-06-29, 2024-01-22 | 0 | 2021-11-05, 2023-06-29, 2024-01-22, 2026-04-30, 2026-05-04, 2026-05-05, 2026-05-06, 2026-05-07, 2026-05-08, 2026-05-11, 2026-05-12, 2026-05-13, 2026-05-14, 2026-05-15, 2026-05-18, 2026-05-19, 2026-05-20, 2026-05-21, 2026-05-22, 2026-05-26, 2026-05-27, 2026-05-29, 2026-06-01, 2026-06-02, 2026-06-03, 2026-06-04, 2026-06-05, 2026-06-08, 2026-06-09, 2026-06-10, 2026-06-11, 2026-06-12, 2026-06-15, 2026-06-16, 2026-06-17, 2026-06-18, 2026-06-19, 2026-06-22, 2026-06-23, 2026-06-24, 2026-06-25, 2026-06-29, 2026-06-30, 2026-07-02, 2026-07-03, 2026-07-06, 2026-07-07, 2026-07-08, 2026-07-09, 2026-07-10, 2026-07-13, 2026-07-14, 2026-07-15, 2026-07-16, 2026-07-17, 2026-07-20, 2026-07-21, 2026-07-22, 2026-07-23, 2026-07-24, 2026-07-27, 2026-07-28, 2026-07-29, 2026-07-30, 2026-07-31, 2026-08-03, 2026-08-04, 2026-08-06, 2026-08-07, 2026-08-10, 2026-08-11, 2026-08-12, 2026-08-13, 2026-08-14, 2026-08-17, 2026-08-18, 2026-08-19, 2026-08-20, 2026-08-21, 2026-08-24, 2026-08-25, 2026-08-26, 2026-08-27, 2026-08-28, 2026-08-31, 2026-09-01, 2026-09-02, 2026-09-03, 2026-09-04, 2026-09-07, 2026-09-08, 2026-09-10, 2026-09-11, 2026-09-15, 2026-09-16, 2026-09-17, 2026-09-18, 2026-09-21, 2026-09-22, 2026-09-23, 2026-09-24, 2026-09-25, 2026-09-28, 2026-09-29, 2026-09-30, 2026-10-01, 2026-10-05, 2026-10-06, 2026-10-07, 2026-10-08, 2026-10-09, 2026-10-12, 2026-10-13, 2026-10-14, 2026-10-15 |
| participant OI | 1,162 | 2021-11-05, 2023-06-29, 2023-10-31, 2024-01-22, 2025-09-19 | 0 | 2021-11-05, 2023-06-29, 2023-10-31, 2024-01-22, 2025-09-19, 2026-06-12, 2026-06-15, 2026-06-16, 2026-06-17, 2026-06-18, 2026-06-19, 2026-06-22, 2026-06-23, 2026-06-24, 2026-06-25, 2026-06-29, 2026-06-30, 2026-07-02, 2026-07-03, 2026-07-06, 2026-07-07, 2026-07-08, 2026-07-09, 2026-07-10, 2026-07-13, 2026-07-14, 2026-07-15, 2026-07-16, 2026-07-17, 2026-07-20, 2026-07-21, 2026-07-22, 2026-07-23, 2026-07-24, 2026-07-27, 2026-07-28, 2026-07-29, 2026-07-30, 2026-07-31, 2026-08-03, 2026-08-04, 2026-08-06, 2026-08-07, 2026-08-10, 2026-08-11, 2026-08-12, 2026-08-13, 2026-08-14, 2026-08-17, 2026-08-18, 2026-08-19, 2026-08-20, 2026-08-21, 2026-08-24, 2026-08-25, 2026-08-26, 2026-08-27, 2026-08-28, 2026-08-31, 2026-09-01, 2026-09-02, 2026-09-03, 2026-09-04, 2026-09-07, 2026-09-08, 2026-09-10, 2026-09-11, 2026-09-15, 2026-09-16, 2026-09-17, 2026-09-18, 2026-09-21, 2026-09-22, 2026-09-23, 2026-09-24, 2026-09-25, 2026-09-28, 2026-09-29, 2026-09-30, 2026-10-01, 2026-10-05, 2026-10-06, 2026-10-07, 2026-10-08, 2026-10-09, 2026-10-12, 2026-10-13, 2026-10-14, 2026-10-15 |

Files per year (files with a valid internal date / expected sessions):

| Year | F&O bhavcopy | ind_close_all | participant OI |
|---|---:|---:|---:|
| 2021 | 62 / 63 | 62 / 63 | 62 / 63 |
| 2022 | 248 / 248 | 248 / 248 | 248 / 248 |
| 2023 | 245 / 246 | 245 / 246 | 244 / 246 |
| 2024 | 248 / 249 | 248 / 249 | 248 / 249 |
| 2025 | 146 / 249 | 249 / 249 | 248 / 249 |
| 2026 | 8 / 196 | 84 / 196 | 112 / 196 |

Special sessions (status per source):

| Session | F&O bhavcopy | ind_close_all | participant OI |
|---|---|---|---|
| 2023-11-12 | ok | ok | ok |
| 2024-03-02 | ok | ok | ok |
| 2024-05-18 | ok | ok | ok |
| 2025-02-01 | ok | ok | ok |
| 2025-10-21 | absent | ok | ok |
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
| 2021 | 185.7 | 180 | 197 | 197 | n/a |
| 2022 | 196.2 | 191 | 199 | 203 | 0.1836 |
| 2023 | 186.8 | 183 | 191 | 192 | 0.1598 |
| 2024 | 184.9 | 178 | 223 | 231 | 0.1273 |
| 2025 | 220.2 | 208 | 227 | 254 | 0.0906 |
| 2026 | 209.5 | 206 | 213 | 224 | 0.0049 |

Industry-map coverage of the universe (rows with an NSE industry; `industry_map.csv` has 755 symbols from the Nifty 500, Midcap 150, Smallcap 250, Microcap 250 and Nifty 50 lists, no conflicting labels):

| Year | Universe rows | Share of rows with industry | Same, ex-ETF | ETF-group share | Share of tickers |
|---|---:|---:|---:|---:|---:|
| 2022 | 64,791 | 0.5143 | 0.5251 | 0.0206 | 0.4395 |
| 2023 | 284,086 | 0.4896 | 0.5003 | 0.0213 | 0.3781 |
| 2024 | 356,596 | 0.4329 | 0.4495 | 0.0371 | 0.3489 |
| 2025 | 350,554 | 0.4805 | 0.5079 | 0.0540 | 0.3838 |
| 2026 | 301,356 | 0.4770 | 0.5089 | 0.0627 | 0.3759 |

## 3. Staging tables (`ml/data_ext/`)

| File | Rows | Key / content |
|---|---:|---|
| `fo_daily_stock.parquet` | 185,610 | (date, ticker) with a stock future or option: near/next settle and expiry, days to expiry, total futures OI (shares) and its change, futures volume (contracts) and turnover (rupees), call/put OI (shares) and volume (contracts), n_strikes, spot_close (EOD export), basis_near, source_format |
| `index_daily.parquet` | 132,407 | (date, index_name): open, high, low, close, pct_change, volume, turnover_cr, pe, pb, div_yield |
| `fo_participant_oi.parquet` | 5,810 | (date, client_type in Client/DII/FII/Pro/TOTAL), 14 numeric columns in contracts (wide in instruments, long in client type) |
| `industry_map.csv` | 755 | symbol, industry, source_list (first list wins: Nifty 500, Midcap 150, Smallcap 250, Microcap 250, Nifty 50) |
| `sector_index_map.csv` | 15 | industry -> index name in ind_close_all (+ fallback) |
| `equity_master.csv` | n/a | EQUITY_L.csv: symbol, company_name, series, listing_date, paid_up_value, market_lot, isin, face_value (kept from P1) |

Units and conventions (verified, section 7): open interest is in **shares** in both F&O formats (legacy `OPEN_INT`, UDiFF `OpnIntrst`); traded volume in **contracts** in both (`CONTRACTS`, `TtlTradgVol`); turnover in rupees (`VAL_INLAKH` x 1e5, `TtlTrfVal`). Roll: near = the smallest expiry >= t (on the expiry day the expiring contract is still near, 0 days to expiry); next = the second smallest; days to expiry in calendar days; UDiFF uses `FininstrmActlXpryDt`. basis_near = (near settle / spot close - 1) x 365 / days to expiry, NaN below 2 days. n_strikes = distinct strike prices over all option expiries. Futures rows without a spot close: 982 (the special sessions, which have no EOD bars in the v1 export).

Sector-index map (every name verified present in every parsed index file, 1,136 files):

| Industry | Index | Fallback | Share of files with the index |
|---|---|---|---:|
| Financial Services | Nifty Financial Services | - | 1.0000 |
| Information Technology | Nifty IT | - | 1.0000 |
| Healthcare | Nifty Healthcare Index | Nifty Pharma | 1.0000 |
| Automobile and Auto Components | Nifty Auto | - | 1.0000 |
| Fast Moving Consumer Goods | Nifty FMCG | - | 1.0000 |
| Metals & Mining | Nifty Metal | - | 1.0000 |
| Realty | Nifty Realty | - | 1.0000 |
| Oil Gas & Consumable Fuels | Nifty Oil & Gas | - | 1.0000 |
| Power | Nifty Energy | - | 1.0000 |
| Consumer Durables | Nifty Consumer Durables | - | 1.0000 |
| Media Entertainment & Publication | Nifty Media | - | 1.0000 |
| Capital Goods | Nifty Infrastructure | - | 1.0000 |
| Construction | Nifty Infrastructure | - | 1.0000 |
| Chemicals | Nifty Commodities | - | 1.0000 |
| Construction Materials | Nifty Commodities | - | 1.0000 |

Unmapped industries (Consumer Services, Services, Telecommunication, Textiles, Utilities, Diversified, Forest Materials) follow the brief's 'others -> none'. `Nifty Consumer Services` exists in the files but was not added, because the map was proposed before any result existed.

## 4. Feature families

- **F1_market_state** (10): `mkt_ret_20`, `mkt_ret_63`, `mkt_dd_252`, `mkt_vol_20`, `mkt_breadth_200`, `sessions_since_selloff`, `cs_dispersion_20`, `vix_close`, `vix_chg_20`, `nifty50_pe`
- **F2_sector** (10): `ind_mom_20`, `ind_ret_63`, `rel_mom_20`, `rel_ret_126`, `rel_deliv`, `indn_rank_mom_20`, `indn_rank_ret_126`, `indn_rank_deliv_sma`, `indn_rank_atr`, `secidx_ret_20`
- **F3_fo** (8): `fo_member`, `fut_basis_near`, `fut_oi_chg_5`, `fut_oi_chg_20`, `fut_oi_z_60`, `pcr_oi`, `pcr_chg_5`, `opt_oi_to_turnover`
- **F4_flows** (4): `fii_idx_fut_net`, `fii_idx_fut_net_chg_5`, `fii_stk_fut_net`, `client_idx_pcr`

Definitions are in `extdata.json` (`definitions`) and `ml/data_ext/extra_features_manifest.json`. Each external source's sessions are counted on its own file calendar, and EOD-derived series on the EOD export's calendar. Same-day end-of-day prints are allowed (labels enter at the next open).

Conventions fixed before any IC was computed:

1. Market and industry aggregates exclude ETFs (the v2 universe definition), so stock values are the same joined to v1 or v2. ETF rows (v1 only) get F2 values inside their own `ETF` group. ETF source: ml/label_study.py name rule (P1 etf_list.csv absent at build time) (286 tickers).
2. The EW market return drops single-day moves above 22% (the repo's corporate-action threshold; 429 name-days dropped). cs_dispersion_20 is taken over names with `flag_split_20d` == 0. The median EW membership is 1320.0000 names.
3. **Deviation from the brief: names without an NSE industry form an explicit `Unclassified` group** (the brief did not say). A NaN would mark today's index members (section 8).
4. **Deviation from the brief: `secidx_ret_20` for unmapped industries, Unclassified names and ETFs is the Nifty 500 20-session return, not NaN** (796,441 rows). Under the brief, the NaN pattern itself carries the membership look-ahead (section 8). `build(policy={'unclassified': 'nan', 'secidx_unmapped': 'nan'})` reproduces the literal brief.
5. Industry groups with fewer than 5 non-NaN names that date give NaN (the brief). This affects Diversified, Forest Materials and Utilities, about 0.4% of rows.
6. `fo_member` is NaN on a date whose F&O file is missing. The other F3 values are NaN for non-members. Zero futures OI is treated as missing in the log changes and the z-score.

## 5. Point-in-time checks

The static inputs are held fixed in (b) and (c): the industry lists, the sector map and the ETF list. Their point-in-time status is the subject of section 8.

## 6. Base series vs the v1 dataset

Row sets: v1 1,357,383, this stream 1,357,383, common 1,357,383, only in v1 0, only here 0.

| Series | Rows both finite | Max abs diff | Rows with diff > 1e-9 | NaN-pattern mismatches |
|---|---:|---:|---:|---:|
| mom_20 | 1,350,680 | 0.0 | 0 | 0 |
| ret_63d | 1,325,992 | 0.0 | 0 | 0 |
| ret_126d | 1,291,363 | 0.0 | 0 | 0 |
| deliv_pct_sma_20 | 1,307,477 | 0.0 | 0 | 0 |
| atr_pct | 1,354,925 | 0.0 | 0 | 0 |

## 7. Integrity of the external data

- **Units across the format switch.** For 542 futures contracts, the legacy 2024-07-05 OPEN_INT equals the UDiFF 2024-07-08 OpnIntrst minus ChngInOpnIntrst in 542 cases (max relative deviation 0.0). UDiFF turnover / (contracts x lot x close) has median 1.0007, and UDiFF OI is divisible by the lot size in 1.0000 of rows. OI is in shares in both formats (identity holds across the switch); UDiFF TtlTradgVol is in contracts (turnover = contracts x lot x price).
- **Symbols.** 184,628 futures rows on EOD dates; the share whose ticker exists in the EOD export the same day is 1.00000 (0 unmatched: {}).
- **Participant OI.** 1,162 files. Long equals short in the TOTAL row for futures in a share 1.0000 of files. The four client types sum to TOTAL within 1 contract in 0.9036 (exactly in 0.1781; NSE rounds index-option sums by up to 1 contract; max deviation 2.0).
- **Annualised near-month basis** (median by year, the cost of carry): 2021 0.061, 2022 0.057, 2023 0.074, 2024 0.068, 2025 0.053, 2026 0.040. The 1st-99th percentiles are in the JSON.

## 8. The industry-list look-ahead

The constituent lists exist only as of the download date (2026-10-19), so the industry label is not point in time. The label itself barely changes over time; the problem is *which* names carry one. A name is classified only if it is in one of the five indices today, and names that rose since 2022 are over-represented among them. Reporting-only diagnostics follow (labels from the v1 dataset, ex-ETF universe rows, y_clean_20d):

| Year | Share classified | Beat rate classified | Beat rate unclassified | AUC of snapshot flag | AUC of PIT size flag (top N by turnover) |
|---|---:|---:|---:|---:|---:|
| 2022 | 0.5274 | 0.5260 | 0.4668 | 0.5295 | 0.4999 |
| 2023 | 0.5024 | 0.5360 | 0.4723 | 0.5318 | 0.5171 |
| 2024 | 0.4501 | 0.5479 | 0.4597 | 0.5437 | 0.5224 |
| 2025 | 0.5086 | 0.5408 | 0.4372 | 0.5518 | 0.5365 |
| 2026 | 0.5139 | 0.5105 | 0.4926 | 0.5089 | 0.5072 |

Reading: part of the snapshot flag's edge is a genuine size effect, since the PIT top-N flag also exceeds 0.5 in 2023-2025. The gap between the two columns is the future information in the snapshot. It shrinks to almost nothing in 2026, when the snapshot is nearly current.

Can a model recover the partition from the features it would see? LightGBM predicting the snapshot flag (no return labels), trained on 2023 and scored on 2025:

| Feature set | Leak-safe F2 (this build) | Literal brief (NaN for unclassified/unmapped) |
|---|---:|---:|
| base10 | 0.8996 | 0.8996 |
| base10+F2 | 0.9296 | 0.9973 |
| base10+F2+F1 | 0.9566 | 0.9972 |
| F2_only | 0.6701 | 0.9958 |

Under the literal brief, F2 alone identifies the partition almost perfectly, because its NaN pattern is the partition. The leak-safe build lowers that, but F2 still adds to what the base features already reveal. In this build the non-NaN indicator of secidx_ret_20 has AUC 0.4997 against the label.

**Recommendation to the lead.** Do not read an AB2 or AB5 gain as industry information until it beats a placebo with the same coverage. `ml/data_ext/extra_features_placebo_f2.parquet` is that placebo: the F2 columns rebuilt with the industry labels permuted among the classified symbols (seed 108), with the same Unclassified and ETF groups, the same coverage and the same F3 columns. It is not a registered trial; running it would need an amendment (+1 configuration). A cheaper secondary reading is the AUC on classified rows only, where the between-partition component cannot help. F1, F3 and F4 do not depend on the lists: F&O membership comes from the daily bhavcopy, and the market state from the point-in-time universe.

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
| secidx_ret_20 | 0.1323 | n/a | 2022 0.000, 2023 0.004, 2024 0.004, 2025 0.000, 2026 0.587 |
| fo_member | 0.3234 | n/a | 2022 0.000, 2023 0.004, 2024 0.004, 2025 0.416, 2026 0.964 |
| fut_basis_near | 0.9088 | 0.0890 | 2022 0.831, 2023 0.855, 2024 0.884, 2025 0.917, 2026 0.996 |
| fut_oi_chg_5 | 0.9002 | 0.0033 | 2022 0.816, 2023 0.840, 2024 0.873, 2025 0.910, 2026 0.995 |
| fut_oi_chg_20 | 0.9010 | 0.0119 | 2022 0.817, 2023 0.840, 2024 0.875, 2025 0.911, 2026 0.996 |
| fut_oi_z_60 | 0.9021 | 0.0224 | 2022 0.817, 2023 0.840, 2024 0.876, 2025 0.914, 2026 0.996 |
| pcr_oi | 0.8999 | 0.0000 | 2022 0.816, 2023 0.840, 2024 0.873, 2025 0.909, 2026 0.995 |
| pcr_chg_5 | 0.9002 | 0.0033 | 2022 0.816, 2023 0.840, 2024 0.873, 2025 0.910, 2026 0.995 |
| opt_oi_to_turnover | 0.8999 | 0.0000 | 2022 0.816, 2023 0.840, 2024 0.873, 2025 0.909, 2026 0.995 |
| mkt_ret_20 (by date) | 0.0000 | - | 0 NaN dates:  |
| mkt_ret_63 (by date) | 0.0000 | - | 0 NaN dates:  |
| mkt_dd_252 (by date) | 0.0000 | - | 0 NaN dates:  |
| mkt_vol_20 (by date) | 0.0000 | - | 0 NaN dates:  |
| mkt_breadth_200 (by date) | 0.0000 | - | 0 NaN dates:  |
| sessions_since_selloff (by date) | 0.0000 | - | 0 NaN dates:  |
| cs_dispersion_20 (by date) | 0.0000 | - | 0 NaN dates:  |
| vix_close (by date) | 0.1145 | - | 114 NaN dates: 2023-06-29, 2024-01-22, 2026-04-30, 2026-05-04, 2026-05-05, 2026-05-06 ... |
| vix_chg_20 (by date) | 0.1145 | - | 114 NaN dates: 2023-06-29, 2024-01-22, 2026-04-30, 2026-05-04, 2026-05-05, 2026-05-06 ... |
| nifty50_pe (by date) | 0.1145 | - | 114 NaN dates: 2023-06-29, 2024-01-22, 2026-04-30, 2026-05-04, 2026-05-05, 2026-05-06 ... |
| fii_idx_fut_net (by date) | 0.0884 | - | 88 NaN dates: 2023-06-29, 2023-10-31, 2024-01-22, 2025-09-19, 2026-06-12, 2026-06-15 ... |
| fii_idx_fut_net_chg_5 (by date) | 0.0884 | - | 88 NaN dates: 2023-06-29, 2023-10-31, 2024-01-22, 2025-09-19, 2026-06-12, 2026-06-15 ... |
| fii_stk_fut_net (by date) | 0.0884 | - | 88 NaN dates: 2023-06-29, 2023-10-31, 2024-01-22, 2025-09-19, 2026-06-12, 2026-06-15 ... |
| client_idx_pcr (by date) | 0.0884 | - | 88 NaN dates: 2023-06-29, 2023-10-31, 2024-01-22, 2025-09-19, 2026-06-12, 2026-06-15 ... |

## 10. Descriptive monthly IC (REPORTING ONLY)

REPORTING ONLY - descriptive; not used to add, drop or transform any feature; family membership fixed in ml/IMPROVEMENT_PLAN.md. Target: y_excess_20d on y_clean_20d rows (v1 dataset). Each value is the mean of daily Spearman ICs within a calendar month (dates with >= 50 pairs). F1 and F4 are one value per date, so they have no cross-sectional IC.

| Feature | Months | Months > 0 | Mean monthly IC |
|---|---:|---:|---:|
| ind_mom_20 | 48 | 31 | 0.0384 |
| ind_ret_63 | 48 | 30 | 0.0355 |
| rel_mom_20 | 48 | 25 | -0.0056 |
| rel_ret_126 | 48 | 27 | 0.0123 |
| rel_deliv | 48 | 36 | 0.0479 |
| indn_rank_mom_20 | 48 | 25 | -0.0047 |
| indn_rank_ret_126 | 48 | 29 | 0.0129 |
| indn_rank_deliv_sma | 48 | 37 | 0.0491 |
| indn_rank_atr | 48 | 20 | -0.0119 |
| secidx_ret_20 | 47 | 28 | 0.0037 |
| fo_member | 44 | 24 | 0.0278 |
| fut_basis_near | 43 | 35 | 0.0381 |
| fut_oi_chg_5 | 44 | 22 | 0.0006 |
| fut_oi_chg_20 | 44 | 21 | -0.0062 |
| fut_oi_z_60 | 44 | 28 | 0.0123 |
| pcr_oi | 44 | 29 | 0.0376 |
| pcr_chg_5 | 44 | 26 | 0.0097 |
| opt_oi_to_turnover | 44 | 23 | 0.0161 |

## 11. History extension (2016-10-03..2021-09-30, for P4)

Not run in this build.

## 12. Reproduction

```
OMP_NUM_THREADS=2 python3 -I ml/extdata/download.py --window main   # resume-safe
OMP_NUM_THREADS=2 python3 -I ml/extdata/run_all.py                  # parse, lists, features, checks, report
```

Code: `ml/extdata/` (common, download, parse, lists, features, checks, report, run_all). Raw files: `ml/data_raw/{fo,indices,participant,lists}/` (gitignored). Staging: `ml/data_ext/` (gitignored).
