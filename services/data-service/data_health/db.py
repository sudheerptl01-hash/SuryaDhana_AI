"""Thin, memory-bounded access to the DuckDB store for the terminal v2 packages (data_health, fo_iv, index_drivers).

Built on B7's ``DuckDBStore.read()`` / ``read_one()`` / ``write()`` API (shared reads on per-call cursors, exclusive
writes): never ``store._conn`` / ``store._lock`` directly. Writes are ``INSERT OR REPLACE`` with explicit casts, in chunks
of at most ``BATCH_ROWS`` rows (the 15 Oct OOM incident rule: never hand DuckDB a whole archive at once). Timestamps are
UTC-naive by the store's convention; ``iso_utc`` serialises them with an explicit ``+00:00``.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from typing import Any

import pandas as pd

BATCH_ROWS = 50_000


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def iso_utc(v: Any) -> str | None:
    """ISO-8601 with an explicit offset for every datetime serialised; a plain ``date`` stays ``YYYY-MM-DD``."""
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


def to_date(v: Any) -> date | None:
    if v is None or v is pd.NaT or (isinstance(v, float) and math.isnan(v)):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return pd.Timestamp(v).date()
    except (ValueError, TypeError):
        return None


def _frame_for(df: pd.DataFrame, cols: Sequence[str]) -> pd.DataFrame:
    frame = df.copy()
    for c in cols:
        if c not in frame.columns:
            frame[c] = None
    frame = frame[list(cols)]
    for c in frame.columns:                       # pandas string extension dtypes are rejected by DuckDB's scan
        if isinstance(frame[c].dtype, pd.StringDtype) or str(frame[c].dtype) in ("str", "string"):
            frame[c] = frame[c].astype(object)
    return frame


def upsert(store: Any, table: str, df: pd.DataFrame | None, cols: Sequence[str], casts: Mapping[str, str] | None = None) -> int:
    """INSERT OR REPLACE ``df[cols]`` into ``table`` in ≤ BATCH_ROWS chunks through ``store.write``; missing columns → NULL."""
    if df is None or df.empty:
        return 0
    casts = dict(casts or {})
    frame = _frame_for(df, cols)
    select = ", ".join(f"{c}::{casts[c]} AS {c}" if c in casts else c for c in cols)
    sql = f"INSERT OR REPLACE INTO {table} ({', '.join(cols)}) SELECT {select} FROM _b1_frame"
    written = 0
    for start in range(0, len(frame), BATCH_ROWS):
        chunk = frame.iloc[start:start + BATCH_ROWS]
        store.write(sql, frames={"_b1_frame": chunk})
        written += len(chunk)
    return written


def query_df(store: Any, sql: str, params: Sequence[Any] | None = None) -> pd.DataFrame:
    return store.read(sql, list(params or []))


def scalar(store: Any, sql: str, params: Sequence[Any] | None = None) -> Any:
    row = store.read_one(sql, list(params or []))
    return row[0] if row else None


def execute(store: Any, sql: str, params: Sequence[Any] | None = None) -> None:
    store.write(sql, list(params or []))


def max_of(store: Any, table: str, column: str, where: str = "", params: Sequence[Any] | None = None) -> Any:
    sql = f"SELECT MAX({column}) FROM {table}" + (f" WHERE {where}" if where else "")
    return scalar(store, sql, params)


def table_exists(store: Any, table: str) -> bool:
    return scalar(store, "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = ?", [table]) == 1


def records(df: pd.DataFrame | None, date_columns: Sequence[str] = ()) -> list[dict[str, Any]]:
    """JSON-safe records: NaN → None, named DATE columns → 'YYYY-MM-DD', other timestamps → ISO with ``+00:00``."""
    if df is None or df.empty:
        return []
    out = df.astype(object).where(df.notna(), None)
    dates = set(date_columns)
    for c in out.columns:
        s = out[c]
        if s.map(lambda v: isinstance(v, (pd.Timestamp, datetime, date))).any():
            if c in dates or c.endswith(("_date", "date", "expiry", "_at_date")) and c not in ("first_seen_at", "release_at"):
                out[c] = s.map(_iso_date)
            else:
                out[c] = s.map(lambda v: iso_utc(v) if isinstance(v, (pd.Timestamp, datetime, date)) else v)
    return out.to_dict(orient="records")


def _iso_date(v: Any) -> Any:
    d = to_date(v) if isinstance(v, (pd.Timestamp, datetime, date)) else None
    return d.isoformat() if d is not None else v


def get_state(store: Any, key: str) -> str | None:
    v = scalar(store, "SELECT value FROM terminal_ingest_state WHERE key = ?", [key])
    return None if v is None else str(v)


def set_state(store: Any, key: str, value: str | None, *, now: datetime | None = None) -> None:
    upsert(store, "terminal_ingest_state", pd.DataFrame([{"key": key, "value": value, "updated_at": now or utcnow()}]),
           ["key", "value", "updated_at"], {"updated_at": "TIMESTAMP"})
