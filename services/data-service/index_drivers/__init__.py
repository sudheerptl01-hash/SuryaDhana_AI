"""Terminal v2 — "who drives NIFTY" (PLAN 1.2; R-DRIVERS §3 / §6 adopted; builder B1-DATA).

A nightly point-in-time index-contribution store for NIFTY 50 and NIFTY BANK: ``points_i,d = L_{d−1} × w_i,d × r_i,d`` with
``L`` NSE's closing index value (never Yahoo), ``r`` from the split-adjusted bhavcopy, ``w`` rebuilt from stored filings
(shares with ``filed_at ≤ d``, promoter % with ``broadcast_ts ≤ d``) and calibrated to NSE's daily top-10 file; the identity
residual stored per day; the driver leader with hysteresis; concentration and breadth. Descriptive attribution only —
``arithmetic`` for the identity, ``context`` for the regime; "describes, does not predict"; nothing here enters
``momentum.py``, ``decision_desk.py``, a directional alert or the ticket.
"""
from __future__ import annotations

__all__ = ["api", "catalog_seed", "compute", "ingest", "jobs", "reads", "schema", "weights"]
