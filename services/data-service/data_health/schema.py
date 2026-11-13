"""The data-health tables (PLAN 1.4, Wave 0 0.5 / 0.9): ``dataset_catalog``, ``ingest_log``, ``data_gaps`` and the
package bookkeeping ``terminal_ingest_state``. Every statement is ``IF NOT EXISTS`` so a restart creates them; the
store's ``_init_schema`` runs ``ddl_statements()`` (guarded import, like the gold package)."""
from __future__ import annotations

from typing import Any

DDL = """
-- one row per dataset the terminal shows (the gold catalog pattern terminal-wide; PLAN §0.12)
CREATE TABLE IF NOT EXISTS dataset_catalog (
  id VARCHAR PRIMARY KEY, label VARCHAR NOT NULL, pages VARCHAR NOT NULL,
  publisher VARCHAR NOT NULL, publish_time_ist VARCHAR,
  expected_by VARCHAR, expected_offset_days INTEGER NOT NULL DEFAULT 0,
  cadence VARCHAR NOT NULL, max_age_sessions INTEGER NOT NULL,
  unrecoverable BOOLEAN NOT NULL DEFAULT FALSE,
  ingest_job VARCHAR, freshness_kind VARCHAR NOT NULL, table_name VARCHAR, freshness_column VARCHAR, freshness_where VARCHAR,
  dictionary_anchor VARCHAR, verdict VARCHAR NOT NULL, badge VARCHAR NOT NULL, note VARCHAR,
  verified_at TIMESTAMP, verified_by VARCHAR);

-- every file fetch (Wave 0 0.5): a re-fetch that changed the body is a new row with revision + 1
CREATE TABLE IF NOT EXISTS ingest_log (
  dataset VARCHAR NOT NULL, date DATE NOT NULL, url VARCHAR NOT NULL, fetched_at TIMESTAMP NOT NULL,
  last_modified VARCHAR, etag VARCHAR, sha256 VARCHAR, bytes BIGINT, rows INTEGER, status VARCHAR NOT NULL,
  revision INTEGER NOT NULL DEFAULT 0, note VARCHAR,
  PRIMARY KEY (dataset, date, fetched_at));

-- explicit gap rows for session-bound captures lost to downtime (Wave 0 0.9)
CREATE TABLE IF NOT EXISTS data_gaps (
  dataset VARCHAR NOT NULL, date DATE NOT NULL, reason VARCHAR NOT NULL, unrecoverable BOOLEAN NOT NULL,
  source VARCHAR NOT NULL, first_seen_at TIMESTAMP NOT NULL, PRIMARY KEY (dataset, date));

CREATE TABLE IF NOT EXISTS terminal_ingest_state (key VARCHAR PRIMARY KEY, value VARCHAR, updated_at TIMESTAMP);

-- silent-rot escalations (FINAL P0-2/P0-3): one record per (dataset, session, kind) — the PK IS the
-- "one Telegram line per dataset per day" dedupe; the controller reads them and sends the line
CREATE TABLE IF NOT EXISTS data_health_escalations (
  dataset VARCHAR NOT NULL, date DATE NOT NULL, kind VARCHAR NOT NULL,
  detail VARCHAR, first_seen_at TIMESTAMP NOT NULL,
  PRIMARY KEY (dataset, date, kind));
"""

TABLES: tuple[str, ...] = ("dataset_catalog", "ingest_log", "data_gaps", "terminal_ingest_state", "data_health_escalations")

COLUMNS: dict[str, list[str]] = {
    "dataset_catalog": ["id", "label", "pages", "publisher", "publish_time_ist", "expected_by", "expected_offset_days", "cadence",
                        "max_age_sessions", "unrecoverable", "ingest_job", "freshness_kind", "table_name", "freshness_column",
                        "freshness_where", "dictionary_anchor", "verdict", "badge", "note", "verified_at", "verified_by"],
    "ingest_log": ["dataset", "date", "url", "fetched_at", "last_modified", "etag", "sha256", "bytes", "rows", "status", "revision", "note"],
    "data_gaps": ["dataset", "date", "reason", "unrecoverable", "source", "first_seen_at"],
    "terminal_ingest_state": ["key", "value", "updated_at"],
    "data_health_escalations": ["dataset", "date", "kind", "detail", "first_seen_at"],
}

CASTS: dict[str, dict[str, str]] = {
    "dataset_catalog": {"expected_offset_days": "INTEGER", "max_age_sessions": "INTEGER", "unrecoverable": "BOOLEAN", "verified_at": "TIMESTAMP"},
    "ingest_log": {"date": "DATE", "fetched_at": "TIMESTAMP", "bytes": "BIGINT", "rows": "INTEGER", "revision": "INTEGER"},
    "data_gaps": {"date": "DATE", "unrecoverable": "BOOLEAN", "first_seen_at": "TIMESTAMP"},
    "terminal_ingest_state": {"updated_at": "TIMESTAMP"},
    "data_health_escalations": {"date": "DATE", "first_seen_at": "TIMESTAMP"},
}

FRESHNESS_COLUMN: dict[str, str] = {"ingest_log": "fetched_at", "data_gaps": "date"}


def ddl_statements() -> list[str]:
    body = "\n".join(line for line in DDL.splitlines() if not line.lstrip().startswith("--"))
    return [s.strip() for s in body.split(";") if s.strip()]


def ensure_schema(store: Any) -> None:
    """Create the tables on ``store`` (idempotent; ``DuckDBStore._init_schema`` does the same at start-up)."""
    with store.writer() as con:
        for stmt in ddl_statements():
            con.execute(stmt)


def positions_meta(store: Any) -> dict[str, dict[str, Any]]:
    """{table: {first, last, rows}} for the freshness-bearing tables (the WHSE panel / pre_market_sync rows)."""
    out: dict[str, dict[str, Any]] = {}
    for table, col in FRESHNESS_COLUMN.items():
        try:
            row = store.read_one(f"SELECT MIN({col}), MAX({col}), COUNT(*) FROM {table}")
            lo, hi, n = row if row else (None, None, 0)
            out[table] = {"first": str(lo)[:19] if lo else None, "last": str(hi)[:19] if hi else None, "rows": int(n or 0)}
        except Exception as exc:  # noqa: BLE001 — a store opened before this DDL ran
            out[table] = {"first": None, "last": None, "rows": 0, "error": type(exc).__name__}
    return out
