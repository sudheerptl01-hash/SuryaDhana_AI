"""DEXP features-explorer read path (desktop review C2-performance-04): the bounded, cached reader in
routers/_features_explorer.py must return EXACTLY what the old whole-file read returned (legacy_page, the
original code kept verbatim), on fixtures built to break a naive re-implementation: ties in the sort column,
NaN/None in every type, None tickers, timestamp dates with NaT, over-long date strings, a dictionary
(categorical) column, duplicate feature names, many small row groups, pages past the end.

It must also stay bounded: never a whole-file read, at most COLUMN_BATCH columns decoded at a time, one build
per (file, filter, sort) however many threads ask, and a rebuilt file is never served from a stale cache.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from fastapi.encoders import jsonable_encoder

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from routers import _features_explorer as fx

FEATURES = ["rsi_14", "macd", "is_green_candle", "day_of_week", "rsi_14", "not_in_file", "flag_up"]
# FEATURES lists rsi_14 twice on purpose (the original keeps duplicates in display_cols); pandas warns about it
pytestmark = pytest.mark.filterwarnings("ignore:DataFrame columns are not unique:UserWarning")
N = 400


def _table(v: int, seed: int = 7, with_pandas_metadata: bool = True) -> pa.Table:
    rng = np.random.default_rng(seed)
    tickers = rng.choice(["AAA", "BBB", "CCC", "RELIANCE", "TCS"], size=N).astype(object)
    tickers[rng.random(N) < 0.03] = None
    days = pd.date_range("2024-01-01", periods=40, freq="D")
    when = rng.choice(np.arange(len(days)), size=N)
    rsi = rng.normal(50, 15, N).astype("float32")
    rsi[rng.random(N) < 0.1] = np.nan
    rsi[:30] = 55.0                                        # a block of ties
    macd = rng.normal(0, 1, N)
    macd_mask = rng.random(N) < 0.1
    green = rng.integers(0, 2, N)                          # heavy ties (0/1)
    dow = rng.integers(0, 5, N).astype("int32")
    flag = rng.random(N) < 0.5
    flag_mask = rng.random(N) < 0.1
    cols: dict[str, Any] = {
        "ticker": pa.array(list(tickers), type=pa.large_string()),
    }
    if v == 1:
        dates = [days[i].strftime("%Y-%m-%d") for i in when]
        dates[5] = "2024-02-30T00:00:00"                   # longer than 10 chars: [:10] matters
        dates[9] = None
        cols["date"] = pa.array(dates, type=pa.large_string())
    else:
        stamps = pa.array([days[i].to_pydatetime() for i in when], type=pa.timestamp("us"))
        mask = np.zeros(N, dtype=bool)
        mask[[3, 77]] = True
        cols["date"] = pa.array(stamps.to_pylist(), type=pa.timestamp("us"), mask=mask)
    cols["rsi_14"] = pa.array(rsi, type=pa.float32())
    cols["macd"] = pa.array(macd, type=pa.float64(), mask=macd_mask)
    cols["is_green_candle"] = pa.array(green, type=pa.int64())
    cols["day_of_week"] = pa.array(dow, type=pa.int32())
    cols["flag_up"] = pa.array(flag, type=pa.bool_(), mask=flag_mask)
    if v == 2:
        cols["carry_ann"] = pa.array(rng.normal(0, 0.1, N))
        reasons = rng.choice(["ok", "illiquid", "new_listing"], size=N).tolist()
        reasons[11] = None
        cols["y_elig_reason"] = pa.array(reasons).dictionary_encode()
    cols["feature_version"] = pa.array(["v1"] * N, type=pa.large_string())
    table = pa.table(cols)
    if not with_pandas_metadata:
        return table
    # the real matrices are written from pandas: carry genuine pandas metadata (index_columns [] etc.)
    meta = pa.Table.from_pandas(table.to_pandas(), preserve_index=False).schema.metadata
    return table.replace_schema_metadata(meta)


@pytest.fixture
def files(tmp_path: Path) -> dict[int, Path]:
    out = {}
    for v in (1, 2):
        path = tmp_path / f"features_v{v}.parquet"
        pq.write_table(_table(v), path, row_group_size=37)    # 11 row groups
        out[v] = path
    plain = tmp_path / "features_plain.parquet"              # written by pyarrow directly: no pandas metadata
    pq.write_table(_table(2, seed=3, with_pandas_metadata=False), plain, row_group_size=64)
    out[3] = plain
    return out


def _enc(x: Any) -> str:
    return json.dumps(jsonable_encoder(x))


def _both(ex: fx.FeaturesExplorer, src: Path, **kw: Any) -> tuple[str, str]:
    return _enc(fx.legacy_page(src, **kw)), _enc(ex.page(src, **kw))


GRID = [
    (ticker, sort_by, sort_dir)
    for ticker in (None, "", "AAA", "aaa", "RELIANCE", "ZZZ")
    for sort_by, sort_dir in (("date", "desc"), ("date", "asc"), ("ticker", "asc"), ("rsi_14", "desc"),
                              ("rsi_14", "asc"), ("is_green_candle", "desc"), ("macd", "asc"), ("flag_up", "asc"),
                              ("carry_ann", "desc"), ("y_elig_reason", "asc"), ("feature_version", "desc"),
                              ("bogus", "desc"), ("date", "sideways"))
]


@pytest.mark.parametrize("which, v", [(1, 1), (2, 2), (3, 2)])
def test_identical_to_the_original_read_on_every_combination(files: dict[int, Path], which: int, v: int) -> None:
    ex = fx.FeaturesExplorer()
    compared = 0
    for ticker, sort_by, sort_dir in GRID:
        for page, page_size in ((1, 10), (2, 10), (3, 25), (40, 10), (999, 10)):
            legacy, new = _both(ex, files[which], page=page, page_size=page_size, ticker=ticker, sort_by=sort_by,
                                sort_dir=sort_dir, v=v, feature_cols=FEATURES)
            assert new == legacy, (which, ticker, sort_by, sort_dir, page, page_size)
            compared += 1
    assert compared == len(GRID) * 5
    assert ex.stats["legacy"] == 0                        # the fast path served every one of them


def test_identical_when_reading_the_v1_file_with_the_v2_flag_and_back(files: dict[int, Path]) -> None:
    ex = fx.FeaturesExplorer()
    for v in (1, 2):
        for src in files.values():
            legacy, new = _both(ex, src, page=1, page_size=10, ticker=None, sort_by="date", sort_dir="desc", v=v,
                                feature_cols=FEATURES)
            assert new == legacy


def test_a_rebuilt_file_is_never_served_from_the_cache(files: dict[int, Path]) -> None:
    ex = fx.FeaturesExplorer()
    kw = {"page": 1, "page_size": 10, "ticker": None, "sort_by": "rsi_14", "sort_dir": "desc", "v": 1, "feature_cols": FEATURES}
    first = _enc(ex.page(files[1], **kw))
    pq.write_table(_table(1, seed=99), files[1], row_group_size=50)       # same path, new content
    st = files[1].stat()
    os.utime(files[1], ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    again = _enc(ex.page(files[1], **kw))
    assert again == _enc(fx.legacy_page(files[1], **kw))
    assert again != first


def test_repeat_requests_hit_the_caches(files: dict[int, Path]) -> None:
    ex = fx.FeaturesExplorer()
    kw = {"page_size": 10, "ticker": "AAA", "sort_by": "date", "sort_dir": "desc", "v": 2, "feature_cols": FEATURES}
    for page in (1, 2, 3, 1, 2):
        ex.page(files[2], page=page, **kw)
    assert ex.stats["base_builds"] == 1 and ex.stats["order_builds"] == 1
    assert ex.stats["page_reads"] == 3 and ex.stats["page_hits"] == 2
    ex.page(files[2], page=1, **{**kw, "sort_dir": "asc"})              # new order, same base
    assert ex.stats["base_builds"] == 1 and ex.stats["order_builds"] == 2


def test_never_reads_the_whole_file_and_decodes_few_columns_at_a_time(files: dict[int, Path],
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    src = str(files[2])
    source_reads: list[Any] = []
    real_read_parquet = fx.pd.read_parquet

    def spy_read_parquet(path: Any, *a: Any, **k: Any) -> pd.DataFrame:
        if isinstance(path, str) and path == src:
            source_reads.append(k.get("columns"))
        return real_read_parquet(path, *a, **k)

    rg_batches: list[int] = []
    real_read_row_group = pq.ParquetFile.read_row_group

    def spy_read_row_group(self: pq.ParquetFile, i: int, columns: Any = None, **k: Any) -> pa.Table:
        assert columns is not None, "a whole row group was decoded"
        rg_batches.append(len(columns))
        return real_read_row_group(self, i, columns=columns, **k)

    def no_full_read(*a: Any, **k: Any) -> Any:
        raise AssertionError("the whole file was read")

    real_read_table = pq.read_table

    def read_table_with_columns(source: Any, *a: Any, **k: Any) -> pa.Table:
        if not isinstance(source, (bytes, bytearray)) and getattr(source, "name", source) in (src, files[2]):
            assert k.get("columns") is not None, "every column of the file was read"
        return real_read_table(source, *a, **k)

    monkeypatch.setattr(fx.pd, "read_parquet", spy_read_parquet)
    monkeypatch.setattr(pq.ParquetFile, "read_row_group", spy_read_row_group)
    monkeypatch.setattr(pq.ParquetFile, "read", no_full_read)
    monkeypatch.setattr(pq, "read_table", read_table_with_columns)
    ex = fx.FeaturesExplorer()
    ex.page(files[2], page=2, page_size=10, ticker=None, sort_by="rsi_14", sort_dir="asc", v=2, feature_cols=FEATURES)
    assert source_reads and all(cols is not None and len(cols) <= 2 for cols in source_reads)
    assert rg_batches and max(rg_batches) <= fx.COLUMN_BATCH


def test_concurrent_requests_build_once(files: dict[int, Path]) -> None:
    ex = fx.FeaturesExplorer()
    kw = {"page": 1, "page_size": 10, "ticker": None, "sort_by": "macd", "sort_dir": "desc", "v": 1, "feature_cols": FEATURES}
    results: list[str] = []
    errors: list[BaseException] = []
    gate = threading.Barrier(6)

    def worker() -> None:
        try:
            gate.wait()
            results.append(_enc(ex.page(files[1], **kw)))
        except BaseException as e:  # noqa: BLE001 — surfaced by the assert below
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)
    assert not errors
    assert len(set(results)) == 1 and results[0] == _enc(fx.legacy_page(files[1], **kw))
    assert ex.stats["base_builds"] == 1 and ex.stats["order_builds"] == 1


def test_unusual_files_fall_back_to_the_original_code(tmp_path: Path) -> None:
    ex = fx.FeaturesExplorer()
    kw = {"page": 1, "page_size": 10, "sort_by": "date", "sort_dir": "desc", "v": 1, "feature_cols": FEATURES}
    indexed = tmp_path / "indexed.parquet"            # written with a real pandas index: labels != row numbers
    df = _table(1).to_pandas()
    df.index = pd.Index(np.arange(N)[::-1] * 3, name="row")
    df.to_parquet(indexed, index=True)
    assert _enc(ex.page(indexed, ticker=None, **kw)) == _enc(fx.legacy_page(indexed, ticker=None, **kw))
    no_ticker = tmp_path / "no_ticker.parquet"
    pq.write_table(_table(1).drop_columns(["ticker"]), no_ticker)
    with pytest.raises(KeyError):                      # the original raised for this file too
        fx.legacy_page(no_ticker, ticker=None, **kw)
    with pytest.raises(KeyError):
        ex.page(no_ticker, ticker=None, **kw)
    assert ex.stats["legacy"] == 2


def test_endpoint_serves_the_bounded_reader(files: dict[int, Path], monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException
    from routers import pipeline
    fx.explorer.clear()
    monkeypatch.setattr(pipeline, "FEATURES_PARQUET", files[1])
    body = asyncio.run(pipeline.features_explorer(page=2, page_size=10, ticker=None, sort_by="rsi_14",
                                                  sort_dir="desc", v=1))
    expected = fx.legacy_page(files[1], page=2, page_size=10, ticker=None, sort_by="rsi_14", sort_dir="desc", v=1,
                              feature_cols=pipeline.FEATURE_COLS)
    assert _enc(body) == _enc(expected)
    monkeypatch.setattr(pipeline, "FEATURES_PARQUET", files[1].with_name("missing.parquet"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(pipeline.features_explorer(page=1, page_size=10, ticker=None, sort_by="date", sort_dir="desc", v=2))
    assert exc.value.status_code == 404 and "build_features_v2" in str(exc.value.detail)
    fx.explorer.clear()


def test_order_cache_entries_are_compact_and_read_only(files: dict[int, Path]) -> None:
    ex = fx.FeaturesExplorer()
    ex.page(files[1], page=1, page_size=10, ticker=None, sort_by="date", sort_dir="desc", v=1, feature_cols=FEATURES)
    (order,) = list(ex._order._d.values())
    assert order.dtype == np.int32 and not order.flags.writeable and len(order) == N
