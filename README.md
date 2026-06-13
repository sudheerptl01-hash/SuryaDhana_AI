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
