"""FINAL round R2-DRIV (RATING R9-I3): the within-day contribution timeline on a synthetic session in a temp DuckDB +
temp tick-store parquet — the additive identity per minute (explained = Σ member points; residual = actual − explained),
honest gaps (null before a name's first print; a name on neither source is listed, never interpolated), the session
bounds (a post-close arrival row never enters), the 2-min-tape fallback with the bhavcopy previous close, the 5-minute
buckets, the live grid cut, and the labelling rules (context badge, "describes, does not predict", no direction words)."""
from __future__ import annotations

# ruff: noqa: DTZ001
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "data-service"))

from data_health import db  # noqa: E402
from index_drivers import intraday as it  # noqa: E402
from index_drivers import schema  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
DAY = date(2026, 11, 13)
CLOSED = datetime(2026, 11, 13, 22, 0, tzinfo=IST)         # after the close: the stored session renders in full
INDEX = "NIFTY 50"
L_PREV = 10_000.0


@pytest.fixture
def store(tmp_path: Path):
    from storage.duckdb_store import DuckDBStore

    s = DuckDBStore(str(tmp_path / "intraday.duckdb"))
    schema.ensure_schema(s)
    yield s
    s.close()


def _tick(sym: str, hhmmss: str, price: float, prev: float | None, day: date = DAY) -> dict:
    return {"symbol": sym, "ts": f"{day.isoformat()}T{hhmmss}+05:30", "price": price, "qty": None, "ttq": None,
            "bid": None, "ask": None, "prev_close": prev}


def _write_parquet(base: Path, rows: list[dict], day: date = DAY) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    day_dir = base / day.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    cols = ["symbol", "ts", "price", "qty", "ttq", "bid", "ask", "prev_close"]
    sch = pa.schema([(c, pa.string() if c in ("symbol", "ts") else pa.float64()) for c in cols])
    n = len(list(day_dir.glob("part-*.parquet")))
    pq.write_table(pa.Table.from_pylist(rows, schema=sch), day_dir / f"part-{n:04d}.parquet")


def _seed(store, tmp_path: Path) -> Path:
    now = datetime(2026, 11, 13, 8, 0)
    members = [("A", "Financial Services", 60.0), ("B", "Information Technology", 30.0),
               ("C", "Oil Gas & Consumable Fuels", 8.0), ("E", "Automobile", 2.0)]
    db.upsert(store, "index_constituents_daily",
              pd.DataFrame([{"index_name": INDEX, "date": DAY, "symbol": s, "industry": ind, "isin": None, "company": s,
                             "source": "fixture", "first_seen_at": now} for s, ind, _ in members]),
              schema.COLUMNS["index_constituents_daily"], schema.CASTS["index_constituents_daily"])
    w_rows = [{"index_name": INDEX, "date": DAY, "symbol": s, "method": "rebuilt_calibrated", "weight_pct": w,
               "computed_at": now} for s, _, w in members]
    w_rows.append({"index_name": INDEX, "date": DAY, "symbol": "A", "method": "official_top10", "weight_pct": 59.0,
                   "computed_at": now})                       # the worse-ranked method must lose
    db.upsert(store, "index_weights_daily", pd.DataFrame(w_rows),
              schema.COLUMNS["index_weights_daily"], schema.CASTS["index_weights_daily"])
    store.write("CREATE TABLE IF NOT EXISTS index_ohlc_daily (symbol VARCHAR, date DATE, close DOUBLE)")
    store.write("INSERT INTO index_ohlc_daily (symbol, date, close, source, first_seen_at) "
                "VALUES (?, ?, ?, 'fixture', ?), (?, ?, ?, 'fixture', ?)",
                [INDEX, DAY - timedelta(days=1), L_PREV, now, INDEX, DAY - timedelta(days=4), 9_900.0, now])
    # the previous-session bhavcopy close for C (the tape name whose ticks carry no prev_close)
    store.write("CREATE TABLE IF NOT EXISTS nse_bhavcopy (symbol VARCHAR, series VARCHAR, date DATE, close DOUBLE)")
    store.write("INSERT INTO nse_bhavcopy (symbol, series, date, close) VALUES ('C','EQ',?,50.0), ('C','EQ',?,49.0)",
                [DAY - timedelta(days=1), DAY - timedelta(days=2)])
    # the 2-min tape: C printed spot 50.5 at 09:16 IST (03:46 UTC); a null-spot row never counts
    store.write("CREATE TABLE IF NOT EXISTS iv_intraday (ts TIMESTAMP, symbol VARCHAR, spot DOUBLE)")
    store.write("INSERT INTO iv_intraday (ts, symbol, expiry, strike, opt_type, spot, source, model_version, first_seen_at) "
                "VALUES (TIMESTAMP '2026-11-13 03:46:00', 'C', ?, 50.0, 'CE', 50.5, 'fixture', 'b76-pcp-v1', ?),"
                " (TIMESTAMP '2026-11-13 03:46:00', 'C', ?, 51.0, 'CE', NULL, 'fixture', 'b76-pcp-v1', ?)",
                [DAY, now, DAY, now])
    base = tmp_path / "ticks"
    _write_parquet(base, [
        _tick("A", "09:15:01", 100.5, 100.0), _tick("A", "09:15:40", 101.0, 100.0),   # last print in the minute wins
        _tick("A", "09:17:10", 102.0, 100.0),
        _tick("B", "09:16:05", 198.0, 200.0),
        _tick("A", "19:40:00", 999.0, 100.0),                                          # post-close arrival: excluded
        _tick(INDEX, "09:15:02", 10_030.0, L_PREV), _tick(INDEX, "09:17:30", 10_090.0, L_PREV),
    ])
    return base


def _series(payload: dict, sym: str) -> list:
    for grp in ("add", "drag", "rest"):
        for m in payload["members"][grp]:
            if m["symbol"] == sym:
                return m["series"]
    raise AssertionError(f"{sym} not in payload members")


def test_identity_gaps_bounds_and_fallbacks(store, tmp_path):
    base = _seed(store, tmp_path)
    p = it.intraday(store, INDEX, day=DAY, ticks_base=base, now=CLOSED)
    assert p["date"] == DAY.isoformat() and p["live"] is False
    assert p["minutes"][0] == "09:15" and p["minutes"][-1] == "15:30" and len(p["minutes"]) == 376
    a, b, c = _series(p, "A"), _series(p, "B"), _series(p, "C")
    # A: 1 % at 09:15 → 60 pts; 2 % from 09:17, carried to the close (the 19:40 arrival row never enters)
    assert a[0] == pytest.approx(60.0) and a[1] == pytest.approx(60.0) and a[2] == pytest.approx(120.0)
    assert a[-1] == pytest.approx(120.0)
    # honest gaps: null before a name's first print, never a backfill
    assert b[0] is None and b[1] == pytest.approx(-30.0) and b[-1] == pytest.approx(-30.0)
    # C comes from the 2-min tape (spot 50.5 vs the bhavcopy prev 50.0 → +1 % × 8 % × 10,000 = 8 pts)
    assert c[0] is None and c[1] == pytest.approx(8.0)
    c_row = next(m for m in p["members"]["add"] if m["symbol"] == "C")
    assert c_row["source"] == it.SOURCE_TAPE and c_row["ret_pct"] == pytest.approx(1.0)
    # the additive identity, minute by minute: explained = Σ member points; residual = actual − explained
    assert p["explained_pts"][0] == pytest.approx(60.0) and p["explained_pts"][1] == pytest.approx(38.0)
    assert p["explained_pts"][2] == pytest.approx(98.0)
    assert p["actual_pts"][0] == pytest.approx(30.0) and p["actual_pts"][2] == pytest.approx(90.0)
    assert p["residual_pts"][2] == pytest.approx(-8.0) and p["residual_now"] == pytest.approx(-8.0)
    assert p["priced"][0] == 1 and p["priced"][1] == 3
    # E has weight but no prints on either source: an honest gap, listed with its weight
    assert p["coverage"]["gaps"] == [{"symbol": "E", "weight_pct": 2.0, "reason": "no prints on either source"}]
    assert p["coverage"]["members_total"] == 4 and p["coverage"]["members_priced"] == 3
    # the best stored weight method won (A at 60, not official_top10's 59)
    assert p["weight_method"] == "rebuilt_calibrated" and p["weights_as_of"] == DAY.isoformat()
    a_row = next(m for m in p["members"]["add"] if m["symbol"] == "A")
    assert a_row["weight_pct"] == pytest.approx(60.0) and a_row["points"] == pytest.approx(120.0)
    assert p["index_source"] == it.SOURCE_TICKS and p["prev_index_level"] == pytest.approx(L_PREV)
    assert p["first_minute"] == "09:15"


def test_labelling_rules(store, tmp_path):
    base = _seed(store, tmp_path)
    p = it.intraday(store, INDEX, day=DAY, ticks_base=base, now=CLOSED)
    assert p["badges"]["timeline"] == "context" and p["badges"]["fit"] == "arithmetic"
    assert p["note"].endswith(it.DESCRIBES)
    import re

    text = " ".join([p["note"], *(g["reason"] for g in p["coverage"]["gaps"])])
    assert not re.search(r"\b(bullish|bearish|buy|sell)\b", text, re.I)


def test_five_minute_buckets_and_live_cut(store, tmp_path):
    base = _seed(store, tmp_path)
    p5 = it.intraday(store, INDEX, day=DAY, interval="5m", ticks_base=base, now=CLOSED)
    assert len(p5["minutes"]) == 76 and p5["minutes"][0] == "09:15" and p5["minutes"][-1] == "15:30"
    # 09:15 / 09:16 / 09:17 all land in the 09:15 bucket; the bucket close is the LAST print (A at 102 → 120 pts)
    assert _series(p5, "A")[0] == pytest.approx(120.0) and _series(p5, "B")[0] == pytest.approx(-30.0)
    live_now = datetime(2026, 11, 13, 10, 0, tzinfo=IST)
    pl = it.intraday(store, INDEX, day=DAY, ticks_base=base, now=live_now)
    assert pl["live"] is True and pl["minutes"][-1] == "10:00" and len(pl["minutes"]) == 46


def test_cache_and_day_resolution(store, tmp_path):
    base = _seed(store, tmp_path)
    p1 = it.intraday(store, INDEX, day=DAY, ticks_base=base, now=CLOSED)
    p2 = it.intraday(store, INDEX, day=DAY, ticks_base=base, now=CLOSED)
    assert p2 is p1                                            # the 30 s in-process cache serves the repeat
    # no requested day + no tick dir for "today" → the latest stored tick day renders (closed-market default)
    nxt = datetime(2026, 11, 14, 9, 0, tzinfo=IST)
    p3 = it.intraday(store, INDEX, ticks_base=base, now=nxt)
    assert p3["date"] == DAY.isoformat() and p3["explained_pts"][0] == pytest.approx(60.0)


def test_no_data_session_is_honestly_empty(store, tmp_path):
    base = tmp_path / "ticks-empty"
    base.mkdir()
    _seed(store, tmp_path)                                     # tables exist, but this base dir has no parquet
    store.write("DELETE FROM iv_intraday")                     # and no tape either
    p = it.intraday(store, INDEX, day=DAY, ticks_base=base, now=CLOSED)
    assert p["coverage"]["members_priced"] == 0 and len(p["coverage"]["gaps"]) == 4
    assert all(v is None for v in p["explained_pts"]) and p["residual_now"] is None
    assert p["index_source"] is None
