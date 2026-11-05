# Vendored code — origins (copied 14 Oct 2026)

| File | Copied from | Why |
|---|---|---|
| nse_panel.py | shared/nse_panel.py | survivorship-free adjusted panel loader |
| trading_costs.py | shared/trading_costs.py | real ICICI cost + tax model |
| momentum.py | shared/momentum.py | Desk universe/signals/select (single source of momentum truth) |
| xs_labels.py | shared/xs_labels.py | next-open excess labels |
| deal_filters.py | shared/deal_filters.py | bulk-deal classification |

`tests/test_vendored_drift.py` fails if any copy differs from its origin, so drift is detected, not silent.
imports inside these copies still say `from shared...` — `lib/__init__.py` aliases `shared` → this package so the
copies run self-contained.
