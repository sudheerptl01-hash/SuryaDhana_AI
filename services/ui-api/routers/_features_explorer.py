"""DEXP read path for GET /api/pipeline/features-explorer (desktop review C2-performance-04).

The endpoint used to load the whole feature matrix on every page click: ``pd.read_parquet`` of
computed_features.parquet (73 columns x 1.66 M rows, 352 MB on disk), then a full-frame sort, then a
50-row slice. That cost 0.86-0.95 s per click and about 830 MB of ui-api RSS each time, and two windows
paging at once allocated about 1.7 GB in the process that also serves the terminal UI.

This module returns the SAME response (byte for byte after JSON encoding; tests compare it with the
original code, kept below as ``legacy_page``) from three bounded pieces:

* **base** per (file signature, ticker filter): the health block and the file row numbers of the
  filtered rows. ``ticker`` and ``date`` are read with pandas and go through the original expressions
  (date transform, filter, ``nunique``, ``min``/``max``). The null counts are taken with pyarrow, one row
  group and ``COLUMN_BATCH`` columns at a time: ``is_null(nan_is_null=True)`` counts exactly what pandas'
  ``isna`` counts after the parquet->pandas conversion (NaN and null floats, nulls of every other type).
* **order** per (file signature, ticker filter, sort column, direction): the display order as file row
  numbers. It reads only the sort column (and applies the same ``date`` transform), then calls the same
  ``DataFrame.sort_values``. A one-column sort yields the same indexer as the full-frame sort, because
  pandas computes the indexer from the sort column's values alone.
* **page**: the 50 (``page_size``) rows. Only the row groups that hold them are read, ``COLUMN_BATCH``
  columns at a time, and only the wanted rows are kept. The small table goes through an in-memory
  parquet round trip and ``pd.read_parquet``, so pandas applies exactly the dtype mapping of the
  original full read; the original ``date`` / ``display_cols`` / ``replace`` / ``to_dict`` code then runs
  on it.

The caches are keyed by the file signature (path, inode, size, mtime_ns), so a rebuilt matrix is never
served stale, and they are LRU-bounded (orders are stored as int32 row numbers: 6.6 MB per order of the
whole file). Builds are serialized by one lock (two windows never build twice or in parallel) and at
most ``MAX_PAGE_READS`` page reads run at once, so memory stays bounded however many windows page.

Anything this path does not model falls back to ``legacy_page`` (the original code): a file without a
``ticker`` or ``date`` column, or one written with a pandas index (row labels would not be row numbers).
The fallback is logged once per file signature as a JSON WARNING ``features_explorer.legacy_fallback`` with the
reason, so a writer that drops ``index=False`` does not silently bring back whole-file reads (RAPI-10).

Consistency (RAPI-09): the signature is taken BEFORE the file is opened and checked again before every cache
store and before the response is returned. If a rebuild replaced the file in between (writers use os.replace),
nothing read in that request is cached and the request is served again from the new file (up to
``CONSISTENT_READ_ATTEMPTS`` times, then by ``legacy_page``, one whole-file read).
"""
from __future__ import annotations

import io
import json
import logging
import os
import sys
import threading
from collections import OrderedDict
from collections.abc import Hashable, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

COLUMN_BATCH = 8            # columns decoded at a time (bounds the transient memory of one read)
MAX_PAGE_READS = 2          # concurrent page reads
BASE_CACHE_MAX = 16         # (file, ticker) health blocks; tiny, plus row numbers when filtered
ORDER_CACHE_MAX = 6         # sort orders (<= 6.6 MB each for the whole file)
PAGE_CACHE_MAX = 32         # finished responses (~50 rows each, ~0.4 MB)
CONSISTENT_READ_ATTEMPTS = 3
FALLBACK_WARNED_MAX = 64    # file signatures already warned about (bounded)

FileSig = tuple[str, int, int, int]


class _FileChanged(Exception):
    """The file was replaced while one request was reading it."""


log = logging.getLogger("suryadhana.features_explorer")
if not log.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
    log.propagate = False


# ── the original implementation (reference for tests, and the fallback) ─────────────────────────

def legacy_page(src: Path, *, page: int, page_size: int, ticker: str | None, sort_by: str, sort_dir: str,
                v: int, feature_cols: Sequence[str]) -> dict[str, Any]:
    """routers/pipeline.py features_explorer._read as it was before C2-performance-04 (verbatim logic)."""
    FEATURE_COLS = list(feature_cols)  # the original's name, kept for a line-by-line comparison
    df = pd.read_parquet(str(src))
    df["date"] = df["date"].astype(str).str[:10]
    if ticker:
        df = df[df["ticker"] == ticker.upper()]
    total_rows = len(df)
    total_tickers = int(df["ticker"].nunique()) if "ticker" in df.columns else 0
    date_min = str(df["date"].min()) if total_rows > 0 else None
    date_max = str(df["date"].max()) if total_rows > 0 else None
    valid_feat_cols = [c for c in FEATURE_COLS if c in df.columns]
    null_counts = {col: int(df[col].isna().sum()) for col in valid_feat_cols}
    avg_null_pct = round(
        sum(null_counts.values()) / max(len(valid_feat_cols) * total_rows, 1) * 100, 2
    )
    health = {
        "total_rows": total_rows,
        "total_tickers": total_tickers,
        "date_min": date_min,
        "date_max": date_max,
        "avg_null_pct": avg_null_pct,
        "null_counts": null_counts,
        "feature_count": len(valid_feat_cols),
    }
    sort_col = sort_by if sort_by in df.columns else "date"
    df = df.sort_values(sort_col, ascending=(sort_dir == "asc"))
    total_pages = max(1, (total_rows + page_size - 1) // page_size)
    offset = (page - 1) * page_size
    page_df = df.iloc[offset: offset + page_size]
    display_cols = ["ticker", "date"] + [c for c in FEATURE_COLS if c in page_df.columns]
    if v == 2:   # v2 additions (carry/momentum/flags + y_* label columns) join the grid
        display_cols += [c for c in page_df.columns if c not in display_cols
                         and c not in ("ticker", "date", "feature_version")]
    records = page_df[display_cols].replace({float("nan"): None}).to_dict(orient="records")
    return {
        "health": health,
        "columns": display_cols,
        "rows": records,
        "page": page,
        "page_size": page_size,
        "total_rows": total_rows,
        "total_pages": total_pages,
    }


# ── helpers ──────────────────────────────────────────────────────────────────────────────────────

def file_signature(src: Path) -> FileSig:
    st = os.stat(src)
    return (str(Path(src).resolve()), int(st.st_ino), int(st.st_size), int(st.st_mtime_ns))


def _same_file(src: Path, sig: FileSig) -> None:
    """Raise _FileChanged unless ``src`` still has signature ``sig`` (same inode, size and mtime)."""
    try:
        now = file_signature(src)
    except OSError as exc:
        raise _FileChanged(str(exc)) from exc
    if now != sig:
        raise _FileChanged("replaced")


def _unique(items: Sequence[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _batches(items: Sequence[str], n: int = COLUMN_BATCH) -> list[list[str]]:
    return [list(items[i: i + n]) for i in range(0, len(items), n)]


def _read_columns(src: Path, columns: Sequence[str]) -> pd.DataFrame:
    """pd.read_parquet of a column subset: the same per-column dtype mapping as the full read."""
    return pd.read_parquet(str(src), columns=list(columns))


def _is_row_number_index(index: pd.Index, n: int) -> bool:
    return isinstance(index, pd.RangeIndex) and index.start == 0 and index.step == 1 and len(index) == n


class _LRU:
    def __init__(self, maxsize: int) -> None:
        self.maxsize = maxsize
        self._d: OrderedDict[Hashable, Any] = OrderedDict()

    def get(self, key: Hashable) -> Any | None:
        if key in self._d:
            self._d.move_to_end(key)
            return self._d[key]
        return None

    def put(self, key: Hashable, value: Any) -> None:
        self._d[key] = value
        self._d.move_to_end(key)
        while len(self._d) > self.maxsize:
            self._d.popitem(last=False)

    def clear(self) -> None:
        self._d.clear()

    def __len__(self) -> int:
        return len(self._d)


class _Base:
    __slots__ = ("health", "rows", "total_rows")

    def __init__(self, health: dict[str, Any], rows: np.ndarray | None, total_rows: int) -> None:
        self.health = health
        self.rows = rows            # file row numbers of the filtered rows; None = every row, in file order
        self.total_rows = total_rows


# ── the bounded explorer ─────────────────────────────────────────────────────────────────────────

class FeaturesExplorer:
    """Cached, memory-bounded equivalent of ``legacy_page``. Thread-safe; call from worker threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()                       # cache structure only (short sections)
        self._build = threading.Lock()                      # base/order builds: one at a time, single flight
        self._reads = threading.BoundedSemaphore(MAX_PAGE_READS)
        self._base = _LRU(BASE_CACHE_MAX)
        self._order = _LRU(ORDER_CACHE_MAX)
        self._pages = _LRU(PAGE_CACHE_MAX)
        self.stats = {"legacy": 0, "base_builds": 0, "order_builds": 0, "page_reads": 0, "page_hits": 0,
                      "file_changed": 0}
        self._warned: OrderedDict[FileSig, None] = OrderedDict()

    def clear(self) -> None:
        with self._lock:
            self._base.clear()
            self._order.clear()
            self._pages.clear()

    def _count(self, name: str) -> None:
        with self._lock:
            self.stats[name] += 1

    def _cached(self, lru: _LRU, key: Hashable) -> Any | None:
        with self._lock:
            return lru.get(key)

    def _store(self, lru: _LRU, key: Hashable, value: Any, src: Path | None = None, sig: FileSig | None = None) -> None:
        """Cache ``value``, but only while ``src`` still has signature ``sig`` (else _FileChanged)."""
        if src is not None and sig is not None:
            _same_file(src, sig)
        with self._lock:
            lru.put(key, value)

    def page(self, src: Path, *, page: int, page_size: int, ticker: str | None, sort_by: str, sort_dir: str,
             v: int, feature_cols: Sequence[str]) -> dict[str, Any]:
        """The features-explorer response for one request (same arguments as ``legacy_page``)."""
        feature_cols = list(feature_cols)
        for _ in range(CONSISTENT_READ_ATTEMPTS):
            sig = file_signature(src)                 # taken before the open: a replace after it is detected
            pf = pq.ParquetFile(str(src))
            try:
                result = self._page(pf, Path(src), sig, page=page, page_size=page_size, ticker=ticker,
                                    sort_by=sort_by, sort_dir=sort_dir, v=v, feature_cols=feature_cols)
                _same_file(Path(src), sig)
                return result
            except _FileChanged:
                self._count("file_changed")
                continue
            finally:
                pf.close()
        return self._legacy(Path(src), "the file kept changing while it was read", None, page=page,
                            page_size=page_size, ticker=ticker, sort_by=sort_by, sort_dir=sort_dir, v=v,
                            feature_cols=feature_cols)

    def _legacy(self, src: Path, reason: str, sig: FileSig | None, **kw: Any) -> dict[str, Any]:
        self._count("legacy")
        self._warn_fallback(src, reason, sig)
        return legacy_page(src, **kw)

    def _warn_fallback(self, src: Path, reason: str, sig: FileSig | None) -> None:
        """One JSON WARNING per file signature (and reason) that takes the slow whole-file path (RAPI-10)."""
        key = sig or (str(src), 0, 0, 0)
        with self._lock:
            if key in self._warned:
                return
            self._warned[key] = None
            while len(self._warned) > FALLBACK_WARNED_MAX:
                self._warned.popitem(last=False)
        log.warning(json.dumps({"level": "warning", "component": "features_explorer",
                                "event": "features_explorer.legacy_fallback", "file": Path(src).name,
                                "reason": reason, "note": "each page click now reads the whole file"}))

    def _page(self, pf: pq.ParquetFile, src: Path, sig: FileSig, *, page: int, page_size: int, ticker: str | None,
              sort_by: str, sort_dir: str, v: int, feature_cols: list[str]) -> dict[str, Any]:
        kw: dict[str, Any] = {"page": page, "page_size": page_size, "ticker": ticker, "sort_by": sort_by,
                              "sort_dir": sort_dir, "v": v, "feature_cols": feature_cols}
        names = list(pf.schema_arrow.names)
        index_cols = (pf.schema_arrow.pandas_metadata or {}).get("index_columns") or []
        if "ticker" not in names or "date" not in names:
            return self._legacy(src, "no ticker or date column", sig, **kw)
        if index_cols:
            return self._legacy(src, "written with a pandas index (index_columns in the parquet metadata); write it "
                                     "with index=False", sig, **kw)
        tkey = ticker.upper() if ticker else None
        sort_col = sort_by if sort_by in names else "date"
        ascending = sort_dir == "asc"
        page_key = (sig, tkey, sort_col, ascending, page, page_size, v, tuple(feature_cols))
        hit = self._cached(self._pages, page_key)
        if hit is not None:
            self._count("page_hits")
            return hit
        base = self._get_base(pf, src, sig, names, tkey, feature_cols)
        if base is None:                                      # rows are not labelled by row number
            return self._legacy(src, "rows are not labelled by row number", sig, **kw)
        order = self._get_order(src, sig, tkey, base, sort_col, ascending)
        total_rows = base.total_rows
        total_pages = max(1, (total_rows + page_size - 1) // page_size)
        offset = (page - 1) * page_size
        wanted = order[offset: offset + page_size]

        display_cols = ["ticker", "date"] + [c for c in feature_cols if c in names]
        if v == 2:   # v2 additions (carry/momentum/flags + y_* label columns) join the grid
            display_cols += [c for c in names if c not in display_cols and c not in ("ticker", "date", "feature_version")]
        with self._reads:
            page_df = _read_rows(pf, wanted, _unique(display_cols), names)
        self._count("page_reads")
        page_df["date"] = page_df["date"].astype(str).str[:10]
        records = page_df[display_cols].replace({float("nan"): None}).to_dict(orient="records")
        result = {
            "health": base.health,
            "columns": display_cols,
            "rows": records,
            "page": page,
            "page_size": page_size,
            "total_rows": total_rows,
            "total_pages": total_pages,
        }
        self._store(self._pages, page_key, result, src, sig)
        return result

    def _get_base(self, pf: pq.ParquetFile, src: Path, sig: FileSig, names: list[str], tkey: str | None,
                  feature_cols: list[str]) -> _Base | None:
        """Health block + filtered row numbers for (file, ticker)."""
        key = (sig, tkey, tuple(feature_cols))
        cached = self._cached(self._base, key)
        if cached is not None:
            return cached
        with self._build:
            cached = self._cached(self._base, key)          # built by the request we waited for
            if cached is not None:
                return cached
            df = _read_columns(src, ["ticker", "date"])
            if not _is_row_number_index(df.index, pf.metadata.num_rows):
                return None
            df["date"] = df["date"].astype(str).str[:10]
            if tkey:
                df = df[df["ticker"] == tkey]
            total_rows = len(df)
            total_tickers = int(df["ticker"].nunique())
            date_min = str(df["date"].min()) if total_rows > 0 else None
            date_max = str(df["date"].max()) if total_rows > 0 else None
            rows = df.index.to_numpy(dtype=np.int64) if tkey else None
            del df
            valid_feat_cols = [c for c in feature_cols if c in names]
            counts = _null_counts(pf, _unique(valid_feat_cols), rows)
            null_counts = {col: counts[col] for col in valid_feat_cols}
            avg_null_pct = round(
                sum(null_counts.values()) / max(len(valid_feat_cols) * total_rows, 1) * 100, 2
            )
            health = {
                "total_rows": total_rows,
                "total_tickers": total_tickers,
                "date_min": date_min,
                "date_max": date_max,
                "avg_null_pct": avg_null_pct,
                "null_counts": null_counts,
                "feature_count": len(valid_feat_cols),
            }
            base = _Base(health, rows, total_rows)
            self._store(self._base, key, base, src, sig)
            self._count("base_builds")
            return base

    def _get_order(self, src: Path, sig: FileSig, tkey: str | None, base: _Base, sort_col: str,
                   ascending: bool) -> np.ndarray:
        """Display order (file row numbers) for (file, ticker, sort column, direction)."""
        key = (sig, tkey, sort_col, ascending)
        cached = self._cached(self._order, key)
        if cached is not None:
            return cached
        with self._build:
            cached = self._cached(self._order, key)
            if cached is not None:
                return cached
            df = _read_columns(src, [sort_col])
            if sort_col == "date":
                df["date"] = df["date"].astype(str).str[:10]
            if base.rows is not None:
                df = df.iloc[base.rows]
            order = df.sort_values(sort_col, ascending=ascending).index.to_numpy()
            del df
            dtype = np.int32 if len(order) == 0 or int(order.max()) < 2**31 else np.int64
            order = np.ascontiguousarray(order, dtype=dtype)
            order.setflags(write=False)
            self._store(self._order, key, order, src, sig)
            self._count("order_builds")
            return order


def _row_group_starts(pf: pq.ParquetFile) -> np.ndarray:
    md = pf.metadata
    starts = np.zeros(md.num_row_groups + 1, dtype=np.int64)
    for i in range(md.num_row_groups):
        starts[i + 1] = starts[i] + md.row_group(i).num_rows
    return starts


def _null_counts(pf: pq.ParquetFile, columns: list[str], rows: np.ndarray | None) -> dict[str, int]:
    """Per-column count of what pandas' isna() would flag, restricted to ``rows`` (None = all rows)."""
    counts = {c: 0 for c in columns}
    if not columns:
        return counts
    starts = _row_group_starts(pf)
    for rg in range(pf.metadata.num_row_groups):
        idx = None
        if rows is not None:
            sel = rows[(rows >= starts[rg]) & (rows < starts[rg + 1])] - starts[rg]
            if len(sel) == 0:
                continue
            idx = pa.array(sel, type=pa.int64())
        for batch in _batches(columns):
            t = pf.read_row_group(rg, columns=batch)
            for c in batch:
                col = t.column(c)
                if idx is not None:
                    col = col.take(idx)
                counts[c] += int(pc.sum(pc.is_null(col, nan_is_null=True)).as_py() or 0)
            del t
    return counts


def _read_rows(pf: pq.ParquetFile, wanted: np.ndarray, columns: list[str], names: list[str]) -> pd.DataFrame:
    """The rows ``wanted`` (file row numbers, in this order) as pandas would read them: only the row groups
    that hold them are decoded, COLUMN_BATCH columns at a time, then an in-memory parquet round trip lets
    pd.read_parquet apply its own dtype mapping."""
    keep = set(columns)
    columns = [c for c in names if c in keep]                 # file order, like the full frame
    starts = _row_group_starts(pf)
    wanted = np.asarray(wanted, dtype=np.int64)
    schema = pf.schema_arrow
    sub_schema = pa.schema([schema.field(c) for c in columns], metadata=schema.metadata)
    pieces: list[pa.Table] = []
    got: list[np.ndarray] = []
    rgs = np.searchsorted(starts, wanted, side="right") - 1
    for rg in np.unique(rgs):
        local_rows = np.sort(wanted[rgs == rg])
        local = pa.array(local_rows - starts[rg], type=pa.int64())
        arrays: dict[str, Any] = {}
        for batch in _batches(columns):
            t = pf.read_row_group(int(rg), columns=batch)
            for c in batch:
                arrays[c] = t.column(c).take(local)
            del t
        pieces.append(pa.Table.from_arrays([arrays[c] for c in columns], schema=sub_schema))
        got.append(local_rows)
    if pieces:
        table = pa.concat_tables(pieces)
        position = {int(r): i for i, r in enumerate(np.concatenate(got))}
        table = table.take(pa.array([position[int(r)] for r in wanted], type=pa.int64()))
    else:
        table = sub_schema.empty_table()
    buf = io.BytesIO()
    pq.write_table(table, buf)
    buf.seek(0)
    return pd.read_parquet(buf)


explorer = FeaturesExplorer()
