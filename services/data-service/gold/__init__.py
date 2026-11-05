"""Gold intelligence layer for data-service (GOLD program phase 2, builder B1).

Layout (one concern per module; parsers are pure functions over bytes/text so every one of them is
replayable from the saved research samples in ``reports/gold_program/G-*/``):

- ``hosts``            the host allowlist (PLAN §c.6, enforced by test T8) and the paced HTTP / FTP wrappers
- ``schema``           the 19 DuckDB tables (PLAN §c.1) + a bookkeeping table, their casts, the ``gold_cot_metrics`` view
- ``catalog_seed``     the data dictionary rows (PLAN §c.2) — every series_id, verdict, badge, max_age_days
- ``pit``              point-in-time helpers: release rules, revision-aware upserts, the as-of read, resampling
- ``ingest_cot``       CFTC COT (four Socrata datasets) → gold_cot_raw / gold_cot (+ the release calendar rows)
- ``ingest_cme``       CME FTP: daily volume & OI, EFRP, product calendar (iterparse), product reference + margins
- ``ingest_macro``     Treasury, FRED fredgraph.csv, ForexFactory, GPR, World Bank, Atlanta Fed
- ``ingest_yahoo``     Yahoo chart API (daily, intraday, per-month curve) — CODE ONLY in this build
- ``ingest_physical``  GLD / IAU, WGC (display-only), IMF, SGE, SHFE, LBMA pages, Swiss customs
- ``ingest_india``     ICICI master → MCX curve by session, Zerodha margins, IBJA, RBI WSS / reference rate, AMFI, duty
- ``ingest_local``     briefs, the pre-open accuracy log, the health snapshot, the compiled gold calendar
- ``cot_metrics``      nets, COT index / z / percentile, quadrant + fund-driver labels (G-STUDY rules)
- ``derive``           the derived India / global series (landed, duty-paid, basis, premiums, KGX, ratios)
- ``jobs``             the named group registry with due rules, failure isolation and backfill runners
- ``reads``            the ``/db/gold/*`` query functions
- ``api``              the FastAPI router mounted by data-service ``main.py``
- ``backfill``         the ordered one-off backfill plan (PLAN §c.4) as data

Nothing here feeds the Decision Desk, the S1 shadow, directional alerts or the paper ticket (PLAN 0.1 #7).
"""
from __future__ import annotations

__all__ = ["api", "backfill", "catalog_seed", "db", "hosts", "jobs", "pit", "reads", "schema"]
