"""Terminal v2 data health (PLAN 1.4 data half, Wave 0 0.5 / 0.9; builder B1-DATA).

``dataset_catalog`` (the gold ``gold_series_catalog`` pattern terminal-wide: one row per dataset with publisher,
cadence, ``expected_by`` IST, lag budget, ingest job, verdict, badge, dictionary anchor), ``ingest_log`` (every file
fetch: url, Last-Modified, sha256, rows, status; ``If-Modified-Since`` re-fetches write a revision row), ``data_gaps``
(explicit gap rows for session-bound captures lost to downtime, so a page says "no intraday data for 2–4 Nov"
instead of showing an older day) and the ``/db/data-health`` read that ui-api's ``/api/data/health`` (B3) composes.

Nothing here feeds the Decision Desk, the S1 shadow, a directional alert or a ticket price. The helpers in
``data_health.db`` are shared by the ``fo_iv`` and ``index_drivers`` packages (one implementation of the batched,
cast ``INSERT OR REPLACE`` on B7's ``store.write()`` / ``store.read()`` API).
"""
from __future__ import annotations

__all__ = ["api", "calendar", "catalog", "db", "gaps", "ingest_log", "reads", "schema"]
