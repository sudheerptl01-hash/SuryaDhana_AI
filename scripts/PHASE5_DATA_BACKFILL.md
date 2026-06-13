# Phase 5 — D1 Data Backfill (Survivorship / PIT / Corporate Actions)

Closes the *achievable* half of **D1** in `BILLIONAIRE_SCALE_AUDIT.md`. The G1/G2/G7
mechanisms in `services/ui-api/routers/analytics.py` and `backtest_engine.py` were
**mechanism-complete but data-starved**: the corporate-action and membership tables in
`data/market.duckdb` were empty/absent, so the engine fell back to the current survivor
universe and honestly flagged `membership_pit=False`.

This phase backfills **only real, look-ahead-safe data from free sources**. Where no honest
free source exists (delisting returns, PIT fundamentals history), the table is **wired and
ready but left empty** — we do **not** fabricate rows, because a wrong delisting return or a
backdated fundamental would silently bias every CAGR/Sharpe across every AUM band.

## Scripts

| Script | Populates | Source | Idempotent | Look-ahead-safe |
|---|---|---|---|---|
| `backfill_corporate_actions.py` | `splits`, `dividends` | yfinance `Ticker.splits` / `.dividends` | yes (`INSERT OR REPLACE` on `(ticker,date)` PK) | yes — rows dated after `--max-date` (default today) are dropped; the action's ex-date is its `date`, and the backtest's as-of joins gate on `date` |
| `backfill_index_membership.py` | `index_membership` (snapshot), `delistings` (empty) | `data/NSE_1500.csv` (`index == 'NIFTY500'`) | yes | n/a (single anchor `effective_from`) |

Both open a **dedicated read-write DuckDB connection** and abort cleanly if the single-writer
lock is held (data-service running) — they never crash a concurrent reader. The ui-api shared
connection is read-only; reads stay non-blocking throughout.

### Run

```bash
PY=/Users/sudheer/Desktop/jupyter_env/bin/python

# 1. splits + dividends (network, ~1500 names; --sleep for politeness)
$PY scripts/backfill_corporate_actions.py --db data/market.duckdb \
    --universe data/NSE_1500.csv --sleep 0.05

# 2. membership + delistings schema; load NIFTY500 SNAPSHOT (clearly snapshot-only)
$PY scripts/backfill_index_membership.py --db data/market.duckdb \
    --universe data/NSE_1500.csv --load-membership --index NIFTY500 \
    --effective-from 2021-05-17

# tests (no network, temp DBs)
$PY -m pytest scripts/tests/test_backfill_corporate_actions.py -q
```

## What is REAL after Phase 5

- **`splits`** — every yfinance-reported split ex-date for the surviving universe. Real,
  dated, look-ahead-safe. Feeds G7 split adjustment.
- **`dividends`** — every yfinance-reported cash-dividend ex-date for the surviving universe.
  Real, dated, look-ahead-safe. Feeds G7 dividend adjustment / total-return.

These are genuine corporate-action histories for the names that **survived** to today.

## What is SNAPSHOT-ONLY (honestly flagged, NOT point-in-time)

- **`index_membership`** — the **current** NIFTY500 constituent list, loaded as open
  intervals: `effective_from = 2021-05-17` (the OHLCV span start, a conservative anchor),
  `effective_to = NULL` (still a member). Every row carries `_snapshot_only = TRUE`.
  - This is **NOT reconstitution history.** We have no honest free source for the historical
    add/drop (effective) dates, so we do not invent them.
  - **Consequence for honesty:** the as-of merge in `_attach_membership` will *mechanically*
    set `membership_pit = True` once a non-empty `index_membership` exists (it can't tell a
    snapshot seed from real intervals). That flag therefore **overstates** PIT coverage when
    only the snapshot is loaded. The **load-bearing honesty signal is the survivorship
    haircut banner** driven by `delist_by_ticker`, which stays **LIVE** because `delistings`
    is empty. If you require `membership_pit` itself to read `False`, run
    `backfill_index_membership.py` **without** `--load-membership` (tables wired, unloaded).

## What remains GENUINELY UN-BACKFILLABLE from free sources

- **`delistings` (returns)** — created EMPTY. Free NSE delisting history *with delisting
  returns* (final traded price / scheme consideration vs prior close) is not reliably
  obtainable without a paid/official feed. A real backfill needs **one of**:
  1. An official **NSE corporate-actions / delisting-circular** feed (paid), or
  2. A crawl of the **NSE bhavcopy archive** + delisting circulars to reconstruct the last
     traded price and compute `delist_return_pct` per name, cross-checked against the circular.
  Until then the survivorship premium (Brown-Goetzmann-Ibbotson-Ross **+1–4 %/yr**) is a
  **live, unquantified upward bias** on every reported CAGR/Sharpe — and the engine says so.

- **PIT `stock_metrics` (fundamentals history)** — still only 4 snapshot dates
  (2026-05-26 → 06-04). True PIT fundamentals need an **announcement-date-stamped** quarterly
  feed with a report-lag (≥ ~45 trading days) so a quarter is only visible after it was
  actually filed. yfinance does not expose dated historical fundamentals reliably. We do
  **not** backdate the 4 existing snapshots into fake history. A real fix needs a historical
  fundamentals vendor (e.g. an official filings feed) keyed on filing date.

- **Historical `index_membership` reconstitution dates** — see snapshot note above; needs the
  NSE index-reconstitution circular archive (semi-annual review effective dates).

## Truthful state after Phase 5

- `splits` / `dividends`: **REAL and live** for the surviving universe.
- `index_membership`: **snapshot-only** (current NIFTY500), not PIT. `_snapshot_only=TRUE`.
- `delistings`: **empty by design** — survivorship haircut banner **stays LIVE**.
- `stock_metrics` PIT: **gap unchanged** — documented, not faked.

**D1 status: mechanism-complete, data-PARTIAL.** The free-sourced half (corporate actions) is
closed; the survivorship/PIT half remains honestly open until a paid/official feed lands. No
fabricated rows. `MODE=PAPER`.
