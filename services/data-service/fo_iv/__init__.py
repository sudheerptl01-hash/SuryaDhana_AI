"""Terminal v2 — the point-in-time IV store (PLAN 1.1, R-IV §4/§6 adopted; builder B1-DATA).

Black-76 on the put-call-parity forward per expiry from the cached NSE F&O bhavcopies (UDiFF 2024-07-08→, legacy
``foDDMONYYYYbhav`` 2019-10-01→2024-07-05); untraded strikes carry no IV; 25Δ / 10Δ by inverting each strike's own delta;
constant-maturity 30 / 60 / 90 by VIX-style variance interpolation; IV rank AND percentile; realised vol close-to-close /
Parkinson / Yang-Zhang + NSE's FOVOLT; ``model_version`` and ``r`` on every row. A 15-minute Breeze pilot writes parquet
chain parts + ``iv_intraday`` through the budget ledger only.

Every number is ``arithmetic`` or ``context``; no ``signal`` exists; nothing here feeds the Decision Desk, the S1 shadow, a
directional alert or the paper ticket's price (the OSTR ticket may read ``iv_summary_daily`` for its default IV).
"""
from __future__ import annotations

__all__ = ["api", "black76", "catalog_seed", "events", "files", "intraday", "iv_eod", "jobs", "legacy_parser", "reads", "realised", "schema"]
