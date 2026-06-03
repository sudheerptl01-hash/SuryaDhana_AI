---
name: dataset-quirks
description: Data-quality quirks and look-ahead traps in market.duckdb — adjusted_close, liquidity filter, empty tables
metadata:
  type: project
---

# market.duckdb quirks & quant gotchas

**Why:** these shape every hypothesis design and prevent subtle bias. **How to apply:** bake these rules into any future mining query.

## Corporate-action / adjustment
- `adjusted_close` is **back-adjusted** (split/dividend). Per ticker `adjusted_close/close` ranges ~0.64→1.0, with ratio = 1.0 always at the LATEST date (recent unadjusted, history scaled down). 558K/1.05M rows have adj≠close.
- **Rule:** compute all RETURNS (overnight gaps, multi-day) from `adjusted_close`. Compute INTRADAY range/gap signatures `(high-low)/close`, `(close-open)/open` from RAW OHLC (adjustment factor cancels in same-day ratios). Never mix adjusted and raw in a return.
- `splits`/`dividends` tables are EMPTY — adjustment lives only in `adjusted_close`.

## Data integrity (verified clean)
- 0 rows with high<low, 0 null OHLC, 0 null volume. ~8,681 zero-volume rows (halts/illiquid) → filter `volume>0`.

## Liquidity filter (standard, reused across hypotheses)
- Median daily turnover (close*volume, since 2024) spans ₹16M (p10) → ₹1.24B (p90).
- **Canonical liquid universe = 939 tickers**: `median(close*volume) > ₹50M` AND `count(*) > 200 days` since 2024-01-01.

## Look-ahead traps specific to this DB
- `labels`, `ml_labels` columns (`label_return_pct`, `label_direction`, `label_barrier`) are FORWARD-looking outcomes. Use only as backtest targets, NEVER as entry features.
- `ml_features.created_at` / `features.created_at` may be batch-computed in the future relative to `date`; trust the `date` index, not `created_at`, for point-in-time.
- Newer listings: short history → rolling windows (e.g., 252d high) silently shrink. Always require `count rows >= window` before trusting a rolling stat.
