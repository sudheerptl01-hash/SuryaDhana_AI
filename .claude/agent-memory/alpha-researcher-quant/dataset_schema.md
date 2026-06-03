---
name: dataset-schema
description: Schema, tables, columns, date-range and symbol universe of /data/market.duckdb (SuryaDhana market DB)
metadata:
  type: reference
---

# market.duckdb schema (as of 2026-06-03)

Path: `/Users/sudheer/MahaKubera_108/SuryaDhana_AI/data/market.duckdb` (~761 MB, DuckDB).
Read with `/Users/sudheer/Desktop/jupyter_env/bin/python` + `duckdb` 1.1.1, always `read_only=True`.

## Core table: `ohlcv` (the only table to mine for price edges)
Columns: `ticker VARCHAR, date DATE, open, high, low, close DOUBLE, volume BIGINT, adjusted_close DOUBLE, source VARCHAR, created_at TIMESTAMP`.
- 1,496 distinct tickers, 1,049,469 rows, date range **2021-05-17 → 2026-06-02** (~5 yrs, max 1250 trading days/ticker).
- History depth per ticker: min 17, p05 122, p25 260, median 549, p75 1249, max 1250 rows. Many newer listings have short history → require min-history filter.
- `source`: `yahoo_v8` (1.049M rows, bulk) + `icici_breeze_v2` (271 rows, recent live top-up).
- No `^NSEI` / `NIFTY500` present in ohlcv. Index-like symbols are tradeable ETFs (NIFTYBEES, NIFTYETF, BANKNIFTY1, BSLNIFTY, HDFCSENSEX, NIFTY1, LIQUIDETF, SENSEXIETF). Universe is effectively clean tradeable instruments.

## Other tables (status)
- `fundamentals` (1,502 rows): `market_cap` populated (1,359 tickers) — usable for size buckets. **`sector`, `industry` are ALL NULL** — no usable sector labels.
- `ml_features` (1.04M rows, 1452 tickers, to 2026-05-27): precomputed indicators (rsi, macd, atr, realized_vol_20d, volume_zscore, gap_pct, etc.). BUT macro cols `nifty_regime`, `india_vix`, `market_breadth`, `usd_inr` are ALL NULL.
- `features` (STRUCT feature_set), `labels`, `ml_labels` exist (precomputed; horizon labels = LOOK-AHEAD, never use as features).
- `splits`, `dividends`: **EMPTY** (0 rows). Corporate actions are baked into `adjusted_close` only.
- `corporate_events` (earnings estimates), `stock_metrics` (screener-style: pe, roce, np_qtr_cr), `live_quotes`, `orders`, `signals`, `portfolio_snapshots`: execution/ops tables, not for mining.

## Sector proxy
Since `sector` is NULL, any sector-relative / lead-lag strategy must derive groups data-drivenly (rolling return correlation clustering or beta to equal-weight market), NOT from a label column.
