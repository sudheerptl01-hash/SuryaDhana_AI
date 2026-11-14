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
from decimal import Decimal
from typing import Any

import numpy as np
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


def _is_date_named(name: str, dates: set[str]) -> bool:
    """The one naming rule for 'this column is a calendar DATE, not a timestamp' (unchanged from the original records())."""
    return name in dates or (name.endswith(("_date", "date", "expiry", "_at_date")) and name not in ("first_seen_at", "release_at"))


def _shape_cell(v: Any, is_date_col: bool) -> Any:
    """One cell under records()' rules: NaN/NaT/NA → None, datetimes → 'YYYY-MM-DD' or ISO ``+00:00``, Decimal → float."""
    if v is None or v is pd.NaT or v is pd.NA:
        return None
    if isinstance(v, float):                              # covers np.float64; NaN → None as .where(df.notna(), None) did
        return None if v != v else v
    if isinstance(v, (pd.Timestamp, datetime, date)):
        return _iso_date(v) if is_date_col else iso_utc(v)
    if isinstance(v, Decimal):                            # DuckDB DECIMAL via fetchall; .df() made these float already
        return float(v)
    return v


def records(df: pd.DataFrame | None, date_columns: Sequence[str] = ()) -> list[dict[str, Any]]:
    """JSON-safe records: NaN → None, named DATE columns → 'YYYY-MM-DD', other timestamps → ISO with ``+00:00``.

    R5-GIL: one dtype-aware pass per column instead of the frame-wide ``astype(object)/.where/.map`` chain — the same
    output, a fraction of the GIL-held time (this was ~70 % of a hot read call at days=3000, r4-conc/BENCH.md)."""
    if df is None or df.empty:
        return []
    dates = set(date_columns)
    names = [str(c) for c in df.columns]
    cols: list[list[Any]] = []
    for c, name in zip(df.columns, names, strict=False):   # same length by construction (names := df.columns)
        s = df[c]
        is_date_col = _is_date_named(name, dates)
        kind = getattr(s.dtype, "kind", "O")
        if kind == "M":                                   # datetime64, tz-naive or tz-aware
            conv = _iso_date if is_date_col else iso_utc
            cols.append([None if v is pd.NaT else conv(v) for v in s.tolist()])
        elif isinstance(s.dtype, np.dtype) and kind == "f":
            cols.append([None if v != v else v for v in s.tolist()])
        elif isinstance(s.dtype, np.dtype) and kind in "iub":   # plain int / uint / bool: nothing to shape
            cols.append(s.tolist())
        else:                                             # object / extension / mixed: per-cell, the original rules exactly
            cols.append([_shape_cell(v, is_date_col) for v in s.tolist()])
    return [dict(zip(names, row, strict=False)) for row in zip(*cols, strict=False)]   # one entry per column, by construction


def query_rows(store: Any, sql: str, params: Sequence[Any] | None = None) -> tuple[list[str], list[tuple]]:
    """(column names, ``fetchall()`` rows) on a per-call reader cursor — no DataFrame built (R5-GIL).

    A store/double without ``reader()`` falls back to the frame path, so every existing test double keeps working."""
    reader = getattr(store, "reader", None)
    if reader is None:
        df = store.read(sql, list(params or []))
        return [str(c) for c in df.columns], list(df.itertuples(index=False, name=None))
    with reader() as con:
        res = con.execute(sql, list(params or []))
        return [str(d[0]) for d in res.description or []], res.fetchall()


def records_sql(store: Any, sql: str, params: Sequence[Any] | None = None, date_columns: Sequence[str] = ()) -> list[dict[str, Any]]:
    """``records()`` straight off the cursor: the same shaping rules (named / suffixed DATE columns → 'YYYY-MM-DD', other
    datetimes → ISO ``+00:00``, NaN → None) applied to ``fetchall()`` tuples, skipping pandas entirely. Ordering (e.g. the
    ascending re-sort the callers did with ``sort_values``) belongs in the SQL."""
    names, rows = query_rows(store, sql, params)
    dates = set(date_columns)
    flags = [_is_date_named(n, dates) for n in names]
    shape = _shape_cell
    return [{n: shape(v, f) for n, v, f in zip(names, row, flags, strict=False)} for row in rows]   # names/flags per column


def _iso_date(v: Any) -> Any:
    d = to_date(v) if isinstance(v, (pd.Timestamp, datetime, date)) else None
    return d.isoformat() if d is not None else v


def get_state(store: Any, key: str) -> str | None:
    v = scalar(store, "SELECT value FROM terminal_ingest_state WHERE key = ?", [key])
    return None if v is None else str(v)


def set_state(store: Any, key: str, value: str | None, *, now: datetime | None = None) -> None:
    upsert(store, "terminal_ingest_state", pd.DataFrame([{"key": key, "value": value, "updated_at": now or utcnow()}]),
           ["key", "value", "updated_at"], {"updated_at": "TIMESTAMP"})
