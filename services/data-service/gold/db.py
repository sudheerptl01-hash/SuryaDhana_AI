"""Thin, memory-bounded access to the DuckDB store for the gold package.

Writes go through ``DuckDBStore._upsert`` (``INSERT OR REPLACE`` with the casts from ``schema.CASTS``) in
chunks of at most ``schema.BATCH_ROWS`` rows, so no ingest ever hands DuckDB a whole archive at once (15 Oct
OOM incident). Reads return pandas frames with NaN → None already applied for JSON responses.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

from gold.schema import BATCH_ROWS, CASTS, COLUMNS


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def iso_utc(v: Any) -> str | None:
    """ISO-8601 with an EXPLICIT offset for every datetime the package serialises (wave 1c, C-TRADER-1 / C-DATA-1 / C-DATA-6).

    The store keeps UTC-naive timestamps; a naive value is stamped ``+00:00``, an aware one is converted to UTC. A plain
    ``date`` stays ``YYYY-MM-DD``. No reader may ever guess the zone of a bar, a release or an as-of again."""
    if v is None or v is pd.NaT or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, pd.Timestamp):
        v = v.to_pydatetime()
    if isinstance(v, datetime):
        if v.tzinfo is not None:
            v = v.astimezone(timezone.utc).replace(tzinfo=None)
        return v.isoformat() + "+00:00"
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def upsert(store: Any, table: str, df: pd.DataFrame | None) -> int:
    """INSERT OR REPLACE ``df`` into ``table`` in ≤ BATCH_ROWS chunks. Missing columns are filled with NULL."""
    if df is None or df.empty:
        return 0
    cols = COLUMNS[table]
    frame = df.copy()
    for c in cols:
        if c not in frame.columns:
            frame[c] = None
    frame = frame[cols]
    written = 0
    for start in range(0, len(frame), BATCH_ROWS):
        chunk = frame.iloc[start:start + BATCH_ROWS]
        written += store._upsert(table, chunk, cols, CASTS.get(table))
    return written


def query_df(store: Any, sql: str, params: list[Any] | None = None) -> pd.DataFrame:
    return store.read(sql, params or [])                    # shared lock, per-call cursor (PLAN 1.5)


def execute(store: Any, sql: str, params: list[Any] | None = None) -> None:
    store.write(sql, params or [])                          # exclusive lock on the primary connection


def scalar(store: Any, sql: str, params: list[Any] | None = None) -> Any:
    row = store.read_one(sql, params or [])
    return row[0] if row else None


DATE_COLUMNS: frozenset[str] = frozenset(c for casts in CASTS.values() for c, t in casts.items() if t == "DATE") | {"day"}


def records(df: pd.DataFrame) -> list[dict[str, Any]]:
    """JSON-safe records: NaN → None, DATE columns → 'YYYY-MM-DD', timestamps → ISO strings with ``+00:00`` (``iso_utc``)."""
    if df is None or df.empty:
        return []
    out = df.astype(object).where(df.notna(), None)
    for c in out.columns:
        s = out[c]
        if s.map(lambda v: isinstance(v, (pd.Timestamp, datetime, date))).any():
            if c in DATE_COLUMNS:
                out[c] = s.map(_iso_date)
            else:
                out[c] = s.map(_iso_ts)
    return out.to_dict(orient="records")


def _iso_ts(v: Any) -> Any:
    return iso_utc(v) if isinstance(v, (pd.Timestamp, datetime, date)) else v


def _iso_date(v: Any) -> Any:
    d = to_date(v) if isinstance(v, (pd.Timestamp, datetime, date)) else None
    return d.isoformat() if d else v


def max_of(store: Any, table: str, column: str, where: str = "", params: list[Any] | None = None) -> Any:
    sql = f"SELECT MAX({column}) FROM {table}" + (f" WHERE {where}" if where else "")
    return scalar(store, sql, params)


def get_state(store: Any, key: str) -> str | None:
    """A bookkeeping value (conditional-GET validator, backfill cursor, last run) or None."""
    v = scalar(store, "SELECT value FROM gold_ingest_state WHERE key = ?", [key])
    return None if v is None else str(v)


def set_state(store: Any, key: str, value: str | None, *, now: datetime | None = None) -> None:
    upsert(store, "gold_ingest_state", pd.DataFrame([{"key": key, "value": value, "updated_at": now or utcnow()}]))


def to_date(v: Any) -> date | None:
    """A date from a date / Timestamp / ISO string; None when it is not one."""
    if v is None or (isinstance(v, float) and math.isnan(v)) or v is pd.NaT:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return pd.Timestamp(v).date()
    except (ValueError, TypeError):
        return None


def strptime(s: str, fmt: str) -> datetime:
    """``datetime.strptime`` for publisher dates that carry no zone (we keep the DATE part or convert explicitly)."""
    return datetime.strptime(s, fmt)  # noqa: DTZ007 — publisher calendar dates, naive by design
