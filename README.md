# NSE Market Data Toolkit

This repo contains two NSE data tools:

1. **`nse_historical_ingest.py`** — production-grade historical EOD ingestion
   into DuckDB (see [NSE Historical Ingestion](#nse-historical-ingestion)).
2. **`promoter_data.py`** — promoter / shareholding fetcher (below).

---

## NSE Historical Ingestion

`nse_historical_ingest.py` is a resilient, four-layer pipeline that fetches up
to ~5 years of free NSE cash-market EOD data for **all equities** and lands it
in a **DuckDB** analytical database, then derives a swing-trading ML feature
matrix.

### Architecture

| Layer | Responsibility |
|-------|----------------|
| **1. Resilient archive scraper** | `requests.Session` cookie warm-up against the NSE home/reports pages, rotating browser User-Agent pool, randomized 1.5–3.5s throttle, exponential-backoff retries, clean 404 (holiday) handling |
| **2. Processing & compression** | In-memory `zipfile` extraction + vectorized pandas standardization to a uniform lower_case schema; merges the security-wise delivery bhavcopy (OHLC + **deliverable volume**) with the price bhavcopy (ISIN) |
| **3. DuckDB storage** | Typed schema, `PRIMARY KEY (date, ticker, series)`, **idempotent** `ON CONFLICT` upsert, **resume-from-last-date** incremental loads |
| **4. Adjustment & features** | Corporate-action back-adjustment hook + a 2–5 day swing feature/label matrix (RSI, ATR%, SMA/EMA distances, MACD, momentum, rolling vol, volume & **delivery z-scores**, gaps, 52-week distances, forward-return labels) |

### Data sources (NSE public archives)

- `sec_bhavdata_full_<DDMMYYYY>.csv` — security-wise full bhavcopy (OHLC, traded
  qty/turnover/trades, **deliverable qty & %** — a key micro-structure signal). Primary.
- `cm<DD><MON><YYYY>bhav.csv.zip` (legacy) / UDiFF `BhavCopy_..._F_0000.csv.zip`
  (post-Jul-2024) — price bhavcopy; enriches ISIN and exercises the zip path.

### Usage

```bash
pip install -r requirements.txt

# ~5y of all equities into ./nse_market.duckdb, then build features
python3 nse_historical_ingest.py --build-features

# Bounded backfill
python3 nse_historical_ingest.py --start 2023-01-01 --end 2023-03-31

# Offline synthetic self-test of layers 2-4 (no network)
python3 nse_historical_ingest.py --demo
```

Resulting tables: **`equity_eod`** (raw clean EOD) and **`equity_features`**
(ML features + `fwd_ret_{2,3,5}d` / `label_up_{2,3,5}d` labels).

### Notes & honest limitations

- **Network:** NSE serves these files only to browser-like sessions, and many
  sandboxes (incl. Claude Code on the web) block `nseindia.com` via an egress
  allowlist. Run locally, add `nseindia.com` to the allowlist, or use `--demo`.
- **Adjustment:** bhavcopy prices are **raw/unadjusted**. Split/bonus
  back-adjustment requires a corporate-actions feed (`--ca` hook,
  `[ticker, ex_date, ratio]`); without it the pipeline flags prices as
  unadjusted rather than fabricating an adjustment.
- **Labels are forward-looking** (`shift(-h)`) — only for training/backtests;
  never feed `fwd_ret_*` / `label_*` as model inputs at inference.

---

# Promoter Data Fetcher (Nifty 50 + any NSE stock)

`promoter_data.py` pulls **promoter / promoter-group holding**, **public holding**
and **pledged (encumbered)** percentages for Indian listed companies from
**NSE** (the National Stock Exchange of India), which publishes the quarterly
Shareholding Pattern (SHP) for every listed company.

By default it runs over the **Nifty 50** constituents, but you can point it at
any list of NSE symbols.

## Install

```bash
pip install -r requirements.txt
```

(Only dependency is `requests`.)

## Usage

```bash
# Whole Nifty 50 -> promoter_data.csv
python3 promoter_data.py

# A few specific symbols
python3 promoter_data.py --symbols RELIANCE TCS INFY

# Symbols from a file (one per line, '#' for comments)
python3 promoter_data.py --symbols-file my_symbols.txt

# JSON output, and also keep the raw NSE payloads for inspection
python3 promoter_data.py --format json --out promoters.json --raw

# Offline DEMO -- no network, uses bundled illustrative figures
python3 promoter_data.py --demo --symbols RELIANCE TCS INFY HDFCBANK ITC
```

### Output

A table is printed to the terminal and the full dataset is written to CSV/JSON
with these columns:

| column         | meaning                                            |
|----------------|----------------------------------------------------|
| `symbol`       | NSE trading symbol                                 |
| `company`      | Company name                                       |
| `period`       | Reporting quarter (e.g. `31-Mar-2025`)             |
| `promoter_pct` | Promoter & promoter-group holding %                |
| `public_pct`   | Public shareholding %                              |
| `pledged_pct`  | Pledged / encumbered % of promoter holding         |
| `source`       | `NSE` (live) or `DEMO (illustrative)`              |
| `error`        | Populated if that symbol could not be fetched      |

## Network requirements

NSE blocks non-browser clients, so the script:

1. Warms up a `requests.Session` against the NSE home page to obtain the
   cookies the API expects.
2. Sends browser-like headers and a `Referer`.
3. Rate-limits itself (`--delay`, default 1s) and retries with backoff.

**Sandbox / egress allowlist:** if you run this where outbound network is
restricted (e.g. Claude Code on the web with a network policy), NSE hosts are
likely blocked. Either:

- add `nseindia.com` to the environment's egress allowlist, **or**
- run the script on your local machine, **or**
- use `--demo` to see the script work against bundled sample data.

## Notes

- The Nifty 50 list is hard-coded as of 2025 and is rebalanced periodically by
  NSE — override with `--symbols`/`--symbols-file` to stay current.
- NSE's JSON shapes change over time; the parser searches the payload
  defensively rather than relying on fixed indexes, and `--raw` dumps the
  original responses so you can verify/extend the parsing.
- `sample_data.json` figures are **illustrative approximations** for the demo
  only — always use the live NSE fetch for accurate, current numbers.
