# P4 history: NSE cash-market EOD 2016-10-03 to 2021-09-30

Generated 2026-10-22T14:31:32+00:00 from `ml/results/improve/history/history.json` (every number below is quoted from it). Status: final.

## What was built

- `ml/data_hist/equity_eod_2016_2021.parquet`: 2,356,697 rows over 1,238 sessions, exactly the `EOD_COLUMNS` of `nse_historical_ingest.py`, one row per (date, ticker, series), every series the CM file carries (123 codes; 2,035,125 EQ/BE rows), `source = cm_mto`.
- `ml/data_hist/bc_records_2016_2021.csv`: 598,236 Bc rows from 1,237 PR bundles (44,247 distinct events; 262 face-value splits, 513 bonuses, 142 rights), raw columns plus `source_file` and `bundle_date`.
- `ml/data_hist/etf_records_2016_2021.csv`: 129 ETF symbols with first_seen, last_seen, underlying.
- Also in `ml/data_hist/`: `pd_corp_ind_2016_2021.csv` (Pd rows with a CORP_IND flag such as XD, XB, XR), `index_close_2016_2021.csv` (Pd index rows incl. Nifty 50 and India VIX), `sessions_2016_2021.csv` (one row per session), `call_auction_rows_2016_2021.csv` (periodic call-auction rows), `overlap_cm_mto_2021-10.parquet` (the two overlap days; validation only, not for upsert).

Mapping: `prev_close` = PREVCLOSE, `open` = OPEN, `high` = HIGH, `low` = LOW, `last` = LAST, `close` = CLOSE, `volume` = TOTTRDQTY, `turnover` = TOTTRDVAL * 1.0 (rupees), rounded half up to 0.01 lakh like the store, `trades` = TOTALTRADES, `vwap` = TOTTRDVAL / TOTTRDQTY, rounded half up to 2 decimals, `isin` = ISIN, `deliv_qty` = MTO Deliverable Quantity (join SYMBOL + SERIES; NaN when MTO has no row or its traded quantity differs from the CM volume), `deliv_pct` = MTO % of Deliverable Quantity to Traded Quantity, `source` = cm_mto.

## Overlap with the stored window (2021-10-01, 2021-10-04)

Matched 3,594 (ticker, series) EQ/BE rows of the store's 3,594; store-only rows: 0; history-only rows: 14.

| Field | Match share | Rule |
|---|---:|---|
| prev_close | 100.00% | exact (NaN = NaN) |
| open | 100.00% | exact (NaN = NaN) |
| high | 100.00% | exact (NaN = NaN) |
| low | 100.00% | exact (NaN = NaN) |
| last | 100.00% | exact (NaN = NaN) |
| close | 100.00% | exact (NaN = NaN) |
| volume | 100.00% | exact (NaN = NaN) |
| trades | 100.00% | exact (NaN = NaN) |
| deliv_qty | 100.00% | exact (NaN = NaN) |
| deliv_pct | 100.00% | exact (NaN = NaN) |
| turnover | 100.00% | exact; TOTTRDVAL / 1e5 rounded half up to 2 decimals, * 1e5 (the store's TURNOVER_LACS * 1e5) |
| vwap | 100.00% | exact; TOTTRDVAL / TOTTRDQTY rounded half up to 2 decimals (sec_bhavdata AVG_PRICE) |

Turnover unit factor (store turnover / raw CM TOTTRDVAL): median 1.0, OLS through the origin 1.0, over 2,991 rows with TOTTRDVAL of at least Rs 10 lakh; applied factor 1.0; units: rupees in both (store: TURNOVER_LACS * 1e5; history: TOTTRDVAL). Against the raw rupee value the store differs by at most Rs 499.75 (median Rs 247.45; within Rs 500 on 100.00% of rows) because it keeps 0.01 lakh; the history applies the same rounding, after which the match is 100.00%.

Systematic differences:

- BE rows carry no delivery in either source (store 0 of 506, history 0 of 506): trade-for-trade BE trades settle by delivery and MTO lists no BE record.
- vwap matches on every row once value / quantity is rounded half up, as NSE prints AVG_PRICE; numpy's default half-to-even rounding misses exact half-paisa cases (QNIFTY 2021-10-04: value / quantity = 1849.125, stored 1849.13), so the parser rounds half up.
- 14 EQ/BE rows exist in the CM bhavcopy but not in the store (CREATIVEYE, DCMFINSERV, GLFL, GTNTEX, NAGREEKCAP, NORBTEAEXP, TCIFINANCE); 14 of them are the day's periodic call-auction securities (Pd market G), which sec_bhavdata_full leaves out. All close below Rs 10 with turnover under Rs 1 lakh, outside the modelling universe (median turnover of at least Rs 1 crore). The history keeps them (every CM row is kept); `ml/data_hist/call_auction_rows_2016_2021.csv` lists every such (date, ticker, series) so they can be dropped for strict homogeneity with the store.

## Calendar

Expected counts come from the reference list of NSE weekday closures in `ml/history/validate.py` (`NSE_WEEKDAY_HOLIDAYS`) plus the special sessions.

| Period | Sessions | Expected (reference calendar) | EQ/BE rows | All rows |
|---|---:|---:|---:|---:|
| 2016Q4 | 62 | 62 | 97,367 | 104,803 |
| 2017 | 248 | 248 | 394,612 | 437,241 |
| 2018 | 246 | 246 | 401,775 | 463,036 |
| 2019 | 245 | 245 | 401,795 | 472,664 |
| 2020 | 252 | 252 | 418,260 | 498,644 |
| 2021Q1-Q3 | 185 | 185 | 321,316 | 380,309 |

Weekday closures not in the reference holiday list: none. Reference holidays that nevertheless carry a non-special session: none. Weekend sessions: 2016-10-30, 2019-10-27, 2020-02-01, 2020-11-14. Mirror echoes or misdated files: 0.

Special sessions:

- 2016-10-30 (Sunday Muhurat): present, 1553 EQ/BE rows, median trades 387.0
- 2017-10-19 (Muhurat (Diwali holiday)): present, 1576 EQ/BE rows, median trades 419.0
- 2018-11-07 (Muhurat (Diwali holiday)): present, 1598 EQ/BE rows, median trades 238.0
- 2019-10-27 (Sunday Muhurat): present, 1613 EQ/BE rows, median trades 201.0
- 2020-02-01 (Saturday Budget session): present, 1639 EQ/BE rows, median trades 933.0
- 2020-11-14 (Saturday Muhurat): present, 1678 EQ/BE rows, median trades 421.5

## prev_close continuity

Rule: (ticker, series) EQ/BE traded on t and on the previous session; mismatch when |prev_close(t) / close(t-1) - 1| > 0.005. Over 1,237 dates and 2,014,426 pairs the mismatch share is 0.000% (median day 0.000%, 99th percentile 0.00%, maximum 0.12% on 2018-09-18). Dates above 5%: 0.

Every mismatching pair: 2018-09-18 CARERATING EQ prev_close 1264.05 vs previous close 1301.05 (Bc ex-date: AGM/DIV-RS 37 PER SHARE); 2018-09-18 CUPID EQ prev_close 219.75 vs previous close 222.25 (Bc ex-date: DIV RS 2/SPL DIV RE 0.50); 2019-05-30 ALLSEC BE prev_close 308.0 vs previous close 318.0 (Bc ex-date: INTERIM DIVIDEND); 2019-07-01 SHRIPISTON BE prev_close 907.45 vs previous close 913.45 (Bc ex-date: DIV-RS 6 PER SH); 2020-06-19 MOTOGENFIN BE prev_close 22.9 vs previous close 45.75 (Bc ex-date: FVSPLT FRM RS 10 TO RS 5).

Mismatches falling on a Bc ex-date of the same ticker: 5 of 5 ({'split': 1, 'bonus': 0, 'rights': 0, 'dividend': 4, 'demerger/scheme': 0, 'capital reduction': 0}): NSE adjusted the base price for these few dividends and one split. On 267 split or bonus ex-dates with a previous-session close, prev_close differs from it on 1: the legacy PREVCLOSE is otherwise the unadjusted previous close, so prev_close does not reveal splits and bonuses in this window either, and the Bc feed is needed for adjustment. No session is missing (no date above 5%, every weekday closure is a reference holiday, all special sessions present).

Splice with the store: the store's 2021-10-01 prev_close equals the history's 2021-09-30 close exactly for 100.00% of 1,787 (ticker, series) pairs (mismatch share above 0.5%: 0.00%).

## Coverage

| Period | EQ/BE with deliv_pct | EQ with deliv_pct | BE with deliv_pct | EQ/BE with ISIN |
|---|---:|---:|---:|---:|
| 2016Q4 | 97.3% | 100.0% | 0.0% | 100.0% |
| 2017 | 93.4% | 100.0% | 0.0% | 100.0% |
| 2018 | 91.6% | 100.0% | 0.0% | 100.0% |
| 2019 | 91.1% | 99.3% | 0.0% | 100.0% |
| 2020 | 90.8% | 100.0% | 0.0% | 100.0% |
| 2021Q1-Q3 | 88.8% | 100.0% | 0.0% | 100.0% |

Periodic call-auction rows (EQ/BE, Pd market G): 13,607 over 96 tickers ({'2016Q4': 1156, '2017': 3146, '2018': 1452, '2019': 1926, '2020': 4119, '2021Q1-Q3': 1808}).

Distinct tickers: 2,697 (all series), 2,218 (EQ/BE); distinct ISINs on EQ/BE rows: 2,241; EQ/BE tickers with an INF (fund) ISIN: 129. deliv_qty <= volume on 100.000% of rows with delivery; deliv_pct within 0.01 of 100 * deliv_qty / volume on 100.000%.

Integrity: OHLC ordering holds on 100.000% of EQ/BE rows (0 violations); non-positive closes 0; vwap inside [low, high] on 100.000%; duplicate keys 0; largest share of tickers repeating the previous session's close and volume 0.25% (2018-09-27).

Parser: 2,356,697 of 2,356,697 CM rows kept (0 duplicate keys dropped, 0 rows with a TIMESTAMP other than the file date); MTO 2,154,605 records, 133 without a CM row, MTO traded quantity equals CM volume on 99.885% of matched rows (the exceptions are all in MTO_17062019.DAT, MTO_18062019.DAT, which carry 66 records keyed by BSE scrip codes and quantities above the NSE volume, most likely combined NSE and BSE obligations; delivery is left NaN on those 2,485 rows); MTO trade-date mismatches: 0 (files rejected: 0; headers reading 'rade Date' without the T, date verified: 7); sessions without MTO: 0, without PR: 0; bundle CSV rows with an unquoted comma in a text field, re-joined: 6 in 3 bundles; PR bundles whose members carry another date (not used): PR020118.zip -> 020119; PR bundles without a Bc / etf / Pd member: 0 / 0 / 0; member names seen: Bc<ddmmyy>.csv, etf<ddmmyy>.csv, Pd<ddmmyy>.csv.

Independent cross-check against the Pd file of each day's PR bundle (security rows of the normal market, the periodic call auction and the block-deal window): 2,354,684 rows over 1,237 days; equal close 100.000%, prev_close 100.000%, open 100.000%, high 99.999%, low 99.994%, volume 100.000%, trades 100.000%, turnover within Rs 500 100.000%; CM rows absent from Pd 157 (0 of them EQ/BE; series GS, X1, X2), Pd rows absent from CM 0.

Disagreements by day and field: cm10JUL2017bhav.csv.zip high 28 rows; cm10JUL2017bhav.csv.zip low 133 rows. 2017-07-10 is the day of NSE's trading halt after a technical failure; only high and low differ there, and the bundle's Pr file agrees with Pd (for example ACC low 1615.25 in Pd and Pr, 1563.30 in CM). The parquet keeps the CM values (the store's product family); the rows are in `ml/results/improve/history/cm_vs_pd_disagreements.csv`.

## Sanity events

| Date | Event | Present | EQ/BE rows | Median open gap | Median low vs prev close | Median close return | Nifty 50 return | Nifty 50 low vs prev close |
|---|---|---|---:|---:|---:|---:|---:|---:|
| 2016-10-30 (Sun) | Sunday Muhurat | yes | 1553 | 0.82% | -0.21% | 0.87% | -0.14% | -0.25% |
| 2016-11-09 (Wed) | demonetisation announced the previous evening: gap-down open | yes | 1561 | -7.38% | -14.70% | -3.14% | -1.31% | -6.34% |
| 2017-10-19 (Thu) | Muhurat (Diwali holiday) | yes | 1576 | 0.49% | -0.93% | 0.11% | -0.63% | -0.86% |
| 2018-11-07 (Wed) | Muhurat (Diwali holiday) | yes | 1598 | 0.96% | -0.04% | 1.07% | 0.65% | 0.50% |
| 2019-10-27 (Sun) | Sunday Muhurat | yes | 1613 | 0.84% | -0.27% | 1.15% | 0.37% | 0.18% |
| 2020-02-01 (Sat) | Saturday Union Budget session | yes | 1639 | 0.00% | -3.81% | -2.32% | -2.51% | -2.75% |
| 2020-03-13 (Fri) | market-wide lower circuit at the open, then a rebound | yes | 1640 | -6.67% | -14.51% | 0.34% | 3.81% | -10.79% |
| 2020-03-23 (Mon) | market-wide lower circuit, Nifty 50 down about 13% | yes | 1613 | -5.25% | -13.12% | -9.88% | -12.98% | -13.29% |
| 2020-11-14 (Sat) | Saturday Muhurat | yes | 1678 | 0.99% | -0.28% | 0.89% | 0.47% | 0.23% |

## Download

1,824 calendar days requested (CM outcomes {'200': 1238, '404': 586}); MTO files 1,238, PR bundles 1,238; MTO missing on session days: 0, PR missing: 0; errors left: CM 0, MTO 0, PR 0. 4,306 request outcomes in the manifest over 2 runs: the first run stopped at 2019-09-09 when the agent proxy refused connections (1 back-off logged) and the session ended; the resumed run skipped every completed day without a request and made 1,777 requests with 0 back-offs in 3,610 s. One extra request re-fetched PR020118.zip to confirm the archive mis-file (identical bytes).

Upsert dry run (`DuckDBStore.upsert` into an in-memory DuckDB, not the store): columns equal `EOD_COLUMNS`: True; 2,356,697 rows over 1,238 sessions (2016-10-03 to 2021-09-30); re-upserting the last day leaves 2,356,697 rows (idempotent: True).

## Notes for the upsert

- The rows carry raw (unadjusted) prices like the store; the corporate-action feed must be applied over the full 2016-2026 history after the upsert.
- `isin` is populated from the CM file (the stored 2021-2026 rows have it empty).
- `turnover` is rounded to 0.01 lakh exactly like the stored rows (at most Rs 500 from the raw TOTTRDVAL, which stays in the raw CM files).
- Delivery is NaN on BE rows in both sources; features that need delivery see the same gap pattern on both sides of the splice.
- Delivery is also NaN on 2,485 rows of 2019-06-17 and 2019-06-18, where the MTO quantities are not NSE-only (see Parser above). 2017-07-10 high/low come from the CM file and differ from the PR bundle's Pd and Pr files on 161 values (listed in `cm_vs_pd_disagreements.csv`).
- Periodic call-auction rows (Pd market G) are kept; drop them with `call_auction_rows_2016_2021.csv` if the store's sec_bhavdata coverage must be matched exactly.

Upsert recipe (lead, inside P1's write window):

```python
import pandas as pd, nse_historical_ingest as nhi
df = pd.read_parquet("ml/data_hist/equity_eod_2016_2021.parquet")
ca = pd.read_csv("ml/data_hist/call_auction_rows_2016_2021.csv", parse_dates=["date"])  # optional
key = ["date", "ticker", "series"]
df = df.assign(date=pd.to_datetime(df["date"])).merge(ca.assign(_ca=1), on=key, how="left")
df = df[df["_ca"].isna()].drop(columns="_ca")                                   # optional
store = nhi.DuckDBStore("nse_market.duckdb"); store.upsert(df); store.close()
```
