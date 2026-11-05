"""The five drivers tables (R-DRIVERS §6.1 DDL adopted). Every row carries ``computed_at`` and the PIT inputs it used
(``shares_filed_at``, ``promoter_public_at``).

Vintages (PLAN §0.3 as amended by the PM on 5 Nov 2026, superseding PLAN 1.2's "revisions are new rows by computed_at"):
these DERIVED tables keep the LATEST computation per natural key — a re-run (the 20:35 top-10 retry, a backfill resume, a
later calibration) replaces the row in place through INSERT OR REPLACE with its new ``computed_at``. A past vintage is
reproducible from the archived SOURCE files (top-10 weights, constituent lists, the index file, the bhavcopies, the
filings), each versioned in ``ingest_log`` (url, fetched_at, publisher Last-Modified, sha256)."""
from __future__ import annotations

from typing import Any

DDL = """
CREATE TABLE IF NOT EXISTS index_constituents_daily (index_name VARCHAR NOT NULL, date DATE NOT NULL, symbol VARCHAR NOT NULL, industry VARCHAR,
  isin VARCHAR, company VARCHAR, source VARCHAR NOT NULL, first_seen_at TIMESTAMP NOT NULL, PRIMARY KEY (index_name, date, symbol));
CREATE TABLE IF NOT EXISTS index_weights_daily (index_name VARCHAR NOT NULL, date DATE NOT NULL, symbol VARCHAR NOT NULL, method VARCHAR NOT NULL,
  weight_pct DOUBLE, ffmc_cr DOUBLE, shares DOUBLE, shares_filed_at TIMESTAMP, promoter_pct DOUBLE, promoter_public_at DATE,
  iwf_correction DOUBLE, computed_at TIMESTAMP NOT NULL, PRIMARY KEY (index_name, date, symbol, method));
CREATE TABLE IF NOT EXISTS index_contribution_daily (index_name VARCHAR NOT NULL, date DATE NOT NULL, symbol VARCHAR NOT NULL, ret_pct DOUBLE,
  weight_pct DOUBLE, points DOUBLE, prev_index_level DOUBLE, index_close_source VARCHAR, weight_method VARCHAR, flag VARCHAR,
  computed_at TIMESTAMP NOT NULL, PRIMARY KEY (index_name, date, symbol));
CREATE TABLE IF NOT EXISTS index_contribution_fit (index_name VARCHAR NOT NULL, date DATE NOT NULL, actual_points DOUBLE, explained_points DOUBLE,
  residual_points DOUBLE, index_level DOUBLE, prev_index_level DOUBLE, index_close_source VARCHAR, weight_method VARCHAR,
  members_priced INTEGER, members_total INTEGER, computed_at TIMESTAMP NOT NULL, PRIMARY KEY (index_name, date));
CREATE TABLE IF NOT EXISTS index_driver_state (index_name VARCHAR NOT NULL, date DATE NOT NULL, window_sessions INTEGER NOT NULL, leader VARCHAR,
  leader_points DOUBLE, leader_share DOUBLE, tenure_sessions INTEGER, changed_from VARCHAR, change_date DATE, raw_leader VARCHAR,
  top5_share DOUBLE, hhi_contrib DOUBLE, weight_hhi DOUBLE, effective_n DOUBLE, ew_minus_cw_pp DOUBLE, ew_pct DOUBLE, cw_pct DOUBLE,
  members_up INTEGER, members_down INTEGER, computed_at TIMESTAMP NOT NULL, PRIMARY KEY (index_name, date, window_sessions));
"""

TABLES: tuple[str, ...] = ("index_constituents_daily", "index_weights_daily", "index_contribution_daily", "index_contribution_fit", "index_driver_state")

_TS, _D, _DBL, _INT = "TIMESTAMP", "DATE", "DOUBLE", "INTEGER"

COLUMNS: dict[str, list[str]] = {
    "index_constituents_daily": ["index_name", "date", "symbol", "industry", "isin", "company", "source", "first_seen_at"],
    "index_weights_daily": ["index_name", "date", "symbol", "method", "weight_pct", "ffmc_cr", "shares", "shares_filed_at", "promoter_pct",
                            "promoter_public_at", "iwf_correction", "computed_at"],
    "index_contribution_daily": ["index_name", "date", "symbol", "ret_pct", "weight_pct", "points", "prev_index_level", "index_close_source",
                                 "weight_method", "flag", "computed_at"],
    "index_contribution_fit": ["index_name", "date", "actual_points", "explained_points", "residual_points", "index_level", "prev_index_level",
                               "index_close_source", "weight_method", "members_priced", "members_total", "computed_at"],
    "index_driver_state": ["index_name", "date", "window_sessions", "leader", "leader_points", "leader_share", "tenure_sessions", "changed_from",
                           "change_date", "raw_leader", "top5_share", "hhi_contrib", "weight_hhi", "effective_n", "ew_minus_cw_pp", "ew_pct", "cw_pct",
                           "members_up", "members_down", "computed_at"],
}

CASTS: dict[str, dict[str, str]] = {
    "index_constituents_daily": {"date": _D, "first_seen_at": _TS},
    "index_weights_daily": {"date": _D, "shares_filed_at": _TS, "promoter_public_at": _D, "computed_at": _TS,
                            **{c: _DBL for c in ("weight_pct", "ffmc_cr", "shares", "promoter_pct", "iwf_correction")}},
    "index_contribution_daily": {"date": _D, "computed_at": _TS, **{c: _DBL for c in ("ret_pct", "weight_pct", "points", "prev_index_level")}},
    "index_contribution_fit": {"date": _D, "computed_at": _TS, "members_priced": _INT, "members_total": _INT,
                               **{c: _DBL for c in ("actual_points", "explained_points", "residual_points", "index_level", "prev_index_level")}},
    "index_driver_state": {"date": _D, "change_date": _D, "computed_at": _TS, "window_sessions": _INT, "tenure_sessions": _INT, "members_up": _INT,
                           "members_down": _INT, **{c: _DBL for c in ("leader_points", "leader_share", "top5_share", "hhi_contrib", "weight_hhi",
                                                                      "effective_n", "ew_minus_cw_pp", "ew_pct", "cw_pct")}},
}

FRESHNESS_COLUMN: dict[str, str] = {t: "date" for t in TABLES}


def ddl_statements() -> list[str]:
    body = "\n".join(line for line in DDL.splitlines() if not line.lstrip().startswith("--"))
    return [s.strip() for s in body.split(";") if s.strip()]


def ensure_schema(store: Any) -> None:
    with store.writer() as con:
        for stmt in ddl_statements():
            con.execute(stmt)


def positions_meta(store: Any) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for table, col in FRESHNESS_COLUMN.items():
        try:
            row = store.read_one(f"SELECT MIN({col}), MAX({col}), COUNT(*) FROM {table}")
            lo, hi, n = row if row else (None, None, 0)
            out[table] = {"first": str(lo)[:19] if lo else None, "last": str(hi)[:19] if hi else None, "rows": int(n or 0)}
        except Exception as exc:  # noqa: BLE001
            out[table] = {"first": None, "last": None, "rows": 0, "error": type(exc).__name__}
    return out
