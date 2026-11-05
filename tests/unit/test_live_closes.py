"""L2-API (live-NSE program round 2, 5 Nov 2026): data-service ``GET /db/closes`` — stored NSE closes for history panes.

On a temp DuckDB (never data/): the closes are the bhavcopy's EQ/BE rows (EQ preferred), split/bonus-adjusted exactly as
``shared.nse_panel`` does it (proved against ``load_panel`` on the same rows), point in time (only sessions stored up to
today), ``tail`` trims the series but not the window's high/low, company names come from NSE's EQUITY_L copy, indices
come from ``index_ohlc_daily`` only, ``missing`` says why. The new batch read gives the hover card the same 22-session
spark and 52-week range as the per-symbol ``/db/security/{sym}/history`` path it replaces. Negative controls: the raw
closes show the bonus as a crash; a BZ-only stock and a market_index_daily-only index are not served."""
from __future__ import annotations

import math
import socket
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from fastapi import HTTPException

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "services/data-service"))

import main as data_service  # noqa: E402
from storage import DuckDBStore  # noqa: E402

from shared.nse_panel import load_panel  # noqa: E402

TODAY = date.today()  # noqa: DTZ011 — the route PITs on the local (IST) date, as data-service does
SESSIONS = 40


def _sessions(n: int) -> list[date]:
    """The last ``n`` weekdays up to yesterday (oldest first)."""
    out: list[date] = []
    d = TODAY - timedelta(days=1)
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return out[::-1]


DAYS = _sessions(SESSIONS)
BONUS_AT = 25                       # RELIANCE: a 1:1 bonus on DAYS[25] (price halves overnight)
SPLIT_AT = 30                       # TCS: a 2-for-1 split on DAYS[30], listed in the splits table as TCS.NS


def _bars(sym: str, series: str, base: float, step: float, *, event_at: int | None = None, k: float = 1.0) -> list[tuple]:
    rows = []
    prev = None
    for i, d in enumerate(DAYS):
        px = (base + step * i) * (k if event_at is not None and i >= event_at else 1.0)
        o, h, lo, c = px, px * 1.01, px * 0.99, px
        rows.append((sym, series, d.isoformat(), prev if prev is not None else px, o, h, lo, c, c, 1000))
        prev = c
    return rows


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    s = DuckDBStore(str(tmp_path / "closes.duckdb"))
    rows = (_bars("RELIANCE", "EQ", 1200.0, 3.0, event_at=BONUS_AT, k=0.5)
            + [r[:1] + ("BE",) + r[2:7] + (9999.0, 9999.0, 1) for r in _bars("RELIANCE", "BE", 1.0, 0.0)[-3:]]
            + _bars("TCS", "EQ", 3000.0, 5.0, event_at=SPLIT_AT, k=0.5)
            + _bars("BEONLY", "BE", 50.0, 0.1)
            + _bars("BZONLY", "BZ", 20.0, 0.1))
    future = (TODAY + timedelta(days=3)).isoformat()                      # never stored in real life: the PIT guard
    rows.append(("RELIANCE", "EQ", future, 700.0, 700.0, 707.0, 693.0, 5000.0, 700.0, 1))
    with s.writer() as con:
        con.executemany("INSERT INTO nse_bhavcopy (symbol, series, date, prev_close, open, high, low, close, avg_price, volume)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        con.execute("INSERT INTO splits (ticker, date, ratio) VALUES ('TCS.NS', ?, 2.0)", [DAYS[SPLIT_AT].isoformat()])
        con.executemany("INSERT INTO index_ohlc_daily (symbol, date, open, high, low, close, source, first_seen_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, 'nse_daily_file', now())",
                        [("NIFTY 50", d.isoformat(), 24000.0 + i, 24100.0 + i, 23900.0 + i, 24050.0 + i) for i, d in enumerate(DAYS)])
        con.executemany("INSERT INTO market_index_daily (symbol, date, close, source) VALUES ('NIFTYBANK', ?, 51000.0, 'yahoo_v8')",
                        [[d.isoformat()] for d in DAYS])
    names = tmp_path / "nse_equity_list.csv"
    names.write_text("SYMBOL,NAME OF COMPANY, SERIES\nRELIANCE,Reliance Industries Limited,EQ\nTCS,Tata Consultancy Services Limited,EQ\n")
    monkeypatch.setattr(data_service, "_closes_names_path", lambda: names)
    data_service._closes_names_state.update(key=None, names={})
    yield s
    s.close()


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    tried: list[Any] = []

    def refuse(self: socket.socket, addr: Any) -> None:
        tried.append(addr)
        raise OSError("test: no network")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    return tried


def closes(store: Any, symbols: str, days: int = 120, tail: int | None = None) -> dict[str, Any]:
    return data_service.db_closes(symbols=symbols, days=days, tail=tail, store=store)


def test_route_is_registered() -> None:
    assert "/db/closes" in {getattr(r, "path", None) for r in data_service.app.routes}


def test_closes_are_split_and_bonus_adjusted_and_never_draw_a_crash(store: Any, no_network: list[Any]) -> None:
    out = closes(store, "RELIANCE,TCS")
    rel = [p["close"] for p in out["series"]["RELIANCE"]]
    tcs = [p["close"] for p in out["series"]["TCS"]]
    for s in (rel, tcs):
        moves = [b / a - 1 for a, b in zip(s, s[1:], strict=False)]
        assert min(moves) > -0.2, "an ex-date is drawn as a crash"
    # the latest share basis: the last close is as traded; before the bonus every close is halved
    assert rel[-1] == pytest.approx((1200.0 + 3.0 * (SESSIONS - 1)) * 0.5)
    assert rel[0] == pytest.approx(1200.0 * 0.5)
    assert out["meta"]["RELIANCE"]["actions"] == [{"date": DAYS[BONUS_AT].isoformat(), "k": 0.5}]
    assert out["meta"]["TCS"]["actions"] == [{"date": DAYS[SPLIT_AT].isoformat(), "k": 0.5}]   # the splits table (TCS.NS)
    assert no_network == []


def test_negative_control_the_raw_closes_show_the_bonus_as_a_crash(store: Any) -> None:
    with store.reader() as con:
        raw = con.execute("SELECT close FROM nse_bhavcopy WHERE symbol = 'RELIANCE' AND series = 'EQ' AND date <= ?::DATE ORDER BY date",
                          [TODAY.isoformat()]).fetchall()
    s = [r[0] for r in raw]
    assert min(b / a - 1 for a, b in zip(s, s[1:], strict=False)) < -0.4         # the check above would catch an unadjusted series


def test_same_adjustment_as_shared_nse_panel(store: Any) -> None:
    out = closes(store, "RELIANCE,TCS", days=120)
    with store.reader() as con:
        panel = load_panel(con, start=out["from"], end=out["to"])["close"]
    for sym in ("RELIANCE", "TCS"):
        ours = {p["date"]: p["close"] for p in out["series"][sym]}
        theirs = {d.strftime("%Y-%m-%d"): round(float(v), 4) for d, v in panel[sym].dropna().items()}
        assert ours == theirs, sym


def test_point_in_time_eq_before_be_and_be_only_names(store: Any) -> None:
    out = closes(store, "RELIANCE,BEONLY")
    rel = out["series"]["RELIANCE"]
    assert rel[-1]["date"] == DAYS[-1].isoformat() and all(p["date"] <= TODAY.isoformat() for p in rel)   # no future row
    assert 9999.0 not in [p["close"] for p in rel]                     # the BE duplicate loses to EQ
    assert out["meta"]["BEONLY"]["last_series"] == "BE" and len(out["series"]["BEONLY"]) == SESSIONS
    assert out["as_of"] == DAYS[-1].isoformat() and out["source"] == "nse_bhavcopy"


def test_tail_trims_the_series_not_the_window_range(store: Any) -> None:
    full = closes(store, "RELIANCE", days=120)
    out = closes(store, "RELIANCE", days=120, tail=22)
    assert out["series"]["RELIANCE"] == full["series"]["RELIANCE"][-22:] and out["tail"] == 22
    m = out["meta"]["RELIANCE"]
    assert m["sessions"] == SESSIONS and m["first_date"] == DAYS[0].isoformat() and m["last_date"] == DAYS[-1].isoformat()
    adj_highs = [p["close"] * 1.01 for p in full["series"]["RELIANCE"]]
    assert m["high"] == pytest.approx(max(adj_highs), abs=0.01)         # over all 40 sessions, adjusted
    assert m["low"] == pytest.approx(min(p["close"] * 0.99 for p in full["series"]["RELIANCE"]), abs=0.01)


def test_names_from_nse_equity_list_and_indices_from_the_nse_index_file(store: Any) -> None:
    out = closes(store, "reliance.ns,TCS,BEONLY,nifty  50")
    assert list(out["series"]) == ["RELIANCE", "TCS", "BEONLY", "NIFTY 50"]
    assert out["meta"]["RELIANCE"]["name"] == "Reliance Industries Limited"
    assert out["meta"]["BEONLY"]["name"] is None                      # not on the list: no guessed name
    nifty = out["meta"]["NIFTY 50"]
    assert nifty["source"] == "nse_index_file" and nifty["name"] == "NIFTY 50" and nifty["actions"] == []
    assert out["series"]["NIFTY 50"][-1] == {"date": DAYS[-1].isoformat(), "close": 24050.0 + SESSIONS - 1}


def test_missing_says_why_and_never_serves_bz_or_yahoo_index_rows(store: Any) -> None:
    out = closes(store, "BZONLY,NOPE,NIFTY BANK")
    assert out["series"] == {} and out["as_of"] is None
    assert set(out["missing"]) == {"BZONLY", "NOPE", "NIFTY BANK"}
    assert "EQ/BE" in out["missing"]["BZONLY"]
    assert "index file" in out["missing"]["NIFTY BANK"]               # market_index_daily's Yahoo rows are not used
    with store.writer() as con:
        con.execute("DROP TABLE index_ohlc_daily")
    gone = closes(store, "NIFTY 50,RELIANCE")
    assert "not deployed" in gone["missing"]["NIFTY 50"] and "RELIANCE" in gone["series"]


@pytest.mark.parametrize(("symbols", "days", "needle"), [
    ("RELIANCE,DROP TABLE;", 120, "bad symbol"),
    (" , ,", 120, "no symbols"),
    (",".join(f"S{i}" for i in range(301)), 5, "at most 300"),
    (",".join(f"S{i}" for i in range(40)), 3700, "symbol-day budget"),
], ids=["bad-symbol", "empty", "over-300", "over-budget"])
def test_bad_requests_are_422_before_any_read(store: Any, symbols: str, days: int, needle: str,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data_service, "_closes_frames", lambda *a, **k: pytest.fail("read before validation"))
    with pytest.raises(HTTPException) as ei:
        closes(store, symbols, days=days)
    assert ei.value.status_code == 422 and needle in str(ei.value.detail)


def test_the_batch_read_gives_the_spark_and_52_week_range_the_history_path_gave(store: Any) -> None:
    """Regression proof for the hover card: ui-api's old per-symbol path took /db/security/{sym}/history (rows newest
    first, raw closes, action_k on ex-dates, summary.high/low adjusted) and adjusted the last 22 closes itself."""
    import security
    with store.writer() as con:                       # the HP route has no upper date bound: drop the PIT-guard row
        con.execute("DELETE FROM nse_bhavcopy WHERE date > ?::DATE", [TODAY.isoformat()])
    with store.reader() as con:
        hp = security.price_history(con, "RELIANCE", 366)
    k, spark = 1.0, []
    for r in hp["rows"][:22]:
        spark.append(round(r["close"] * k, 4))
        if r.get("action_k"):
            k *= r["action_k"]
    out = closes(store, "RELIANCE", days=366, tail=22)
    assert [p["close"] for p in out["series"]["RELIANCE"]] == pytest.approx(spark[::-1])
    assert out["meta"]["RELIANCE"]["high"] == pytest.approx(hp["summary"]["high"], abs=0.01)
    assert out["meta"]["RELIANCE"]["low"] == pytest.approx(hp["summary"]["low"], abs=0.01)
    assert out["meta"]["RELIANCE"]["last_date"] == hp["rows"][0]["date"]


def test_numbers_are_finite_json(store: Any) -> None:
    out = closes(store, "RELIANCE,TCS,NIFTY 50")
    for pts in out["series"].values():
        assert all(isinstance(p["close"], float) and math.isfinite(p["close"]) and p["close"] > 0 for p in pts)
    assert pd.Series([m["high"] for m in out["meta"].values()]).notna().all()
