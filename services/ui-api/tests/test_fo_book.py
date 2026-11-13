"""The PAPER F&O book (PLAN 2.2 / review M40) + OSTR v2 (M39) + RSK sizing and minors (M18, m106–m108) — W2-BOOK.

Every rule has a test and a negative control. Nothing here touches data/: the store is a temp SQLite (PAPER_FO_DB),
the chains are fixtures shaped like data-service's /db/option-chain payload (NIFTY, F&O bhavcopy 5 Nov 2026: forward
24,545.75 by put-call parity, 24,550 CE 156.15 / PE 160.40, lot 65, priced at the app's one time convention — review M04,
fo_iv.black76 'cal365-1530': T = calendar days to 15:30 IST on expiry ÷ 365, no half-day, so 4 days and 15.45 % for the
9-Nov contract), Breeze is a recorder that fails the test if any attribute other than the read-only margin calculator is
touched, and data-service is never reached (``get_json`` refuses unless a test fakes it).
"""
from __future__ import annotations

import importlib.util
import math
import re
import sqlite3
import sys
from datetime import date, datetime
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fo_book_store as fbs  # noqa: E402
import options_math as om  # noqa: E402
from routers import fo_book, options_strategy as osr, riskdash  # noqa: E402

from shared import breeze_budget as bb  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
UI_API = Path(__file__).resolve().parents[1]
REPO = UI_API.parents[1]
EVENING = datetime(2026, 11, 5, 21, 0, tzinfo=IST)          # after the close: EOD marks
SESSION = datetime(2026, 11, 6, 10, 0, tzinfo=IST)          # Friday in session: the live chain
EXPIRIES = ["2026-11-09", "2026-11-17", "2026-11-23", "2026-12-01", "2026-12-08", "2026-12-29", "2027-01-25"]
ORDER_METHODS = re.compile(r"\b(place_order|modify_order|cancel_order|square_off|squareoff|placeOrder|cancelOrder)\b")


def _rows(forward: float, iv: float, days: float, overrides: dict[tuple[float, str], float] | None = None) -> list[dict[str, Any]]:
    rows = []
    for k in range(23800, 25301, 50):
        t = om.t_years(days)                                   # cal365-1530 (M04): the chain's own T, no half-day
        ce = round(om.black76("CE", forward, k, t, iv / 100).price, 2)
        pe = round(om.black76("PE", forward, k, t, iv / 100).price, 2)
        if overrides:
            ce = overrides.get((k, "CE"), ce)
            pe = overrides.get((k, "PE"), pe)
        rows.append({"strike": float(k), "ce": {"price": ce, "iv": iv if k >= forward * 0.97 else None},
                     "pe": {"price": pe, "iv": iv if k <= forward * 1.03 else None}})
    return rows


def chain_fixture(expiry: str, *, live: bool = False) -> dict[str, Any]:
    if live:                                                # 6 Nov 10:00 → 9 Nov 15:30 = 3 d 5 h 30 min (fractional in session)
        fwd, iv, as_of, d = 24440.0, 15.5, "06-Nov-2026 10:00:00", "2026-11-06"
        days = (datetime(2026, 11, 9, 15, 30, tzinfo=IST) - datetime(2026, 11, 6, 10, 0, tzinfo=IST)).total_seconds() / 86400
    elif expiry == "2026-11-09":
        fwd, iv, days, as_of, d = 24545.75, 15.45, 4, None, "2026-11-05"
    else:
        fwd, iv, as_of, d = 24585.0, 13.96, None, "2026-11-05"
        days = (date.fromisoformat(expiry) - date(2026, 11, 5)).days
    over = {(24550, "CE"): 156.15, (24550, "PE"): 160.40} if expiry == "2026-11-09" and not live else None
    return {"symbol": "NIFTY", "found": True, "date": d, "expiry": expiry, "expiries": EXPIRIES,
            "days_to_expiry": int(days) if not live else 3, "t_days": round(days, 4), "time_convention": "cal365-1530",
            "spot": fwd - 9.0, "future": 24588.0, "forward": fwd, "forward_source": "put-call parity", "atm": 24550.0, "lot": 65,
            "atm_iv": iv, "rows": _rows(fwd, iv, days, over), **({"live": True, "as_of": as_of} if live else {})}


def _black76_store_module() -> Any:
    """data-service's fo_iv/black76.py (pure stdlib), loaded by path: the IV store's own T rule, to pin the book to it."""
    spec = importlib.util.spec_from_file_location("ds_black76", REPO / "services" / "data-service" / "fo_iv" / "black76.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class BreezeRecorder:
    """Records every attribute read; the only one a paper route may reach is the read-only margin calculator."""

    def __init__(self) -> None:
        self.touched: list[str] = []

    def __getattr__(self, name: str) -> Any:
        self.touched.append(name)
        if name == "margin_calculator":
            return lambda legs, exchange_code: {"Success": {"span_margin_required": "81497.07", "non_span_margin_required": "0",
                                                            "order_value": "0"}, "Status": 200, "Error": None}
        raise AssertionError(f"paper route reached breeze.{name}")


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[dict[str, Any]]:
    import routers.positions as pos
    monkeypatch.setenv(fbs.ENV_DB, str(tmp_path / "paper_fo.sqlite"))
    monkeypatch.setenv(bb.ENV_DB, str(tmp_path / "budget.sqlite"))
    bb.reset_ledger()
    for c in (fo_book._chain_cache, fo_book._margin_cache, fo_book._history_cache):
        c.clear()
    rec = BreezeRecorder()
    monkeypatch.setattr(pos, "_get_breeze_client", lambda: (rec, None))
    state: dict[str, Any] = {"now": EVENING, "live_fails": False, "calls": [], "breeze": rec}

    async def fake_chain(symbol: str, expiry: str, live: bool) -> dict[str, Any]:
        state["calls"].append((symbol, expiry, live))
        if live and state["live_fails"]:
            raise fo_book.UpstreamError(503, "data-service unreachable")
        if expiry not in EXPIRIES:
            return chain_fixture(EXPIRIES[0], live=live)          # data-service serves the nearest expiry instead
        return chain_fixture(expiry, live=live)

    async def no_network(url: str, **kw: Any) -> Any:
        state["calls"].append(("get_json", url, False))
        raise fo_book.UpstreamError(503, "tests never reach data-service")

    monkeypatch.setattr(fo_book, "fetch_chain", fake_chain)
    monkeypatch.setattr(fo_book, "get_json", no_network)
    monkeypatch.setattr(fo_book, "now_ist", lambda: state["now"])
    app = FastAPI()
    app.include_router(osr.router, prefix="/api/options")
    app.include_router(fo_book.router, prefix="/api/options/book")
    app.include_router(riskdash.router, prefix="/api/risk")
    state["client"] = TestClient(app)
    yield state
    bb.reset_ledger()


STRADDLE = [{"side": "buy", "kind": "CE", "strike": 24550, "expiry": "2026-11-09", "premium": 156.15, "iv": 15.45, "lots": 1, "lot_size": 65,
             "forward": 24545.75, "price_source": "NSE F&O bhavcopy 2026-11-05"},
            {"side": "buy", "kind": "PE", "strike": 24550, "expiry": "2026-11-09", "premium": 160.40, "iv": 15.45, "lots": 1, "lot_size": 65,
             "forward": 24545.75, "price_source": "NSE F&O bhavcopy 2026-11-05"}]


def _book(client: TestClient, legs: list[dict[str, Any]] = STRADDLE, **kw: Any) -> dict[str, Any]:
    r = client.post("/api/options/book", json={"symbol": "NIFTY", "name": "straddle", "legs": legs, **kw})
    assert r.status_code == 200, r.text
    return r.json()["structure"]


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# PAPER ONLY (PLAN §0.9 gate): no order method anywhere, the DB refuses non-paper rows, no live mode exists
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def test_no_order_method_is_named_in_any_path_this_builder_added() -> None:
    files = [UI_API / "fo_book_store.py", UI_API / "routers" / "fo_book.py", UI_API / "routers" / "options_strategy.py",
             UI_API / "routers" / "riskdash.py"]
    for f in files:
        text = f.read_text(encoding="utf-8")
        assert not ORDER_METHODS.search(text), (f.name, ORDER_METHODS.search(text))
        assert "_breeze_call(" not in text and "execution" not in re.sub(r"EXECUTION_LIVE_ALLOWED", "", text).lower().replace(
            "execution_live", ""), f.name
    # negative control: the scan catches a planted order call
    assert ORDER_METHODS.search("resp = breeze.place_order(stock_code='NIFTY')")


def test_the_database_refuses_a_non_paper_row(env: dict[str, Any]) -> None:
    struct = _book(env["client"])
    path = fbs.default_db_path()
    con = sqlite3.connect(str(path))
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("UPDATE paper_fo_positions SET mode = 'live' WHERE id = ?", (struct["positions"][0]["id"],))
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO paper_fo_structures(name, symbol, created_at, source, mode) VALUES ('x', 'NIFTY', 'now', 't', 'live')")
    con.execute("INSERT INTO paper_fo_structures(name, symbol, created_at, source, mode) VALUES ('x', 'NIFTY', 'now', 't', 'paper')")  # control
    con.close()


@pytest.mark.parametrize("live_allowed", ["", "1"])
def test_book_has_no_live_mode_even_with_execution_live_allowed(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch, live_allowed: str) -> None:
    monkeypatch.setenv("EXECUTION_LIVE_ALLOWED", live_allowed)
    c = env["client"]
    for path, body in (("/api/options/book", {"symbol": "NIFTY", "legs": STRADDLE, "mode": "live"}),
                       ("/api/options/book/close", {"structure_id": 1, "mode": "live"}),
                       ("/api/options/book/roll", {"position_ids": [1], "to_expiry": "2026-11-17", "mode": "LIVE"})):
        r = c.post(path, json=body)
        assert r.status_code == 422 and "PAPER ONLY" in str(r.json()), (path, r.text)
    struct = _book(c)                                             # control: paper books
    assert all(p["mode"] == "paper" for p in struct["positions"])


def test_every_book_route_touches_no_breeze_order_method(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    c = env["client"]
    struct = _book(c)
    pids = [p["id"] for p in struct["positions"]]
    assert c.get("/api/options/book").status_code == 200
    assert c.get("/api/options/book/marks").status_code == 200
    assert c.get("/api/options/book/greeks").status_code == 200
    assert c.post("/api/options/book/mark").status_code == 200
    assert c.post("/api/options/book/roll", json={"position_ids": pids[:1], "to_expiry": "2026-11-17", "preview": True}).status_code == 200

    async def fake_returns(symbol: str, sessions: int = 750) -> tuple[dict[str, float], str, None]:
        return {f"2024-01-{(i % 28) + 1:02d}-{i}": 0.01 * math.sin(i) for i in range(300)}, "fixture", None

    monkeypatch.setattr(fo_book, "underlying_returns", fake_returns)
    assert c.get("/api/risk/fo").status_code == 200              # margin_calculator only (read-only, budget ledger)
    assert c.post("/api/options/book/close", json={"structure_id": struct["id"]}).status_code == 200
    assert set(env["breeze"].touched) <= {"margin_calculator"}, env["breeze"].touched
    # negative control: the recorder does catch an order method
    with pytest.raises(AssertionError):
        _ = env["breeze"].place_order


def test_reads_of_a_book_that_does_not_exist_create_no_file(env: dict[str, Any]) -> None:
    c = env["client"]
    path = fbs.default_db_path()
    assert not path.exists()
    assert c.get("/api/risk/fo").json()["empty"] is True
    assert c.get("/api/options/book").json()["structures"] == [] and c.get("/api/options/book/marks").json()["marks"] == []
    assert c.get("/api/options/strategy/saved", params={"symbol": "NIFTY"}).json()["count"] == 0
    assert c.get("/api/options/book/journal").json()["rows"] == []
    assert not path.exists()                                           # RSK / OSTR opened on a fresh install: no file
    _book(c)
    assert path.exists()                                               # control: the first write creates it


def test_shares_are_refused_by_the_f_and_o_book(env: dict[str, Any]) -> None:
    legs = [{**STRADDLE[0], "kind": "EQ", "strike": None}]
    r = env["client"].post("/api/options/book", json={"symbol": "NIFTY", "legs": legs})
    assert r.status_code == 422 and "cash book" in r.text


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# store: point-in-time marks, journal
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def test_marks_are_append_only_and_revisions_are_new_rows(env: dict[str, Any]) -> None:
    store = fbs.get_store()
    struct = _book(env["client"])
    pid = struct["positions"][0]["id"]
    m = {"position_id": pid, "kind": "eod", "as_of": "2026-11-05T15:30:00+05:30", "price": 156.15, "price_source": "bhavcopy"}
    assert store.add_marks([m]) == 1
    assert store.add_marks([m]) == 0                              # the same close again: idempotent
    assert store.add_marks([{**m, "price": 157.0}]) == 1          # the 22:05 re-publication: a revision row
    rows = store.marks([pid], kind="eod")
    assert [r["price"] for r in rows] == [156.15, 157.0]
    assert store.latest_eod_marks([pid])[pid]["price"] == 157.0
    s = {**m, "kind": "session", "as_of": "2026-11-06T10:00:00+05:30"}
    assert store.add_marks([s]) == 1
    assert store.add_marks([{**s, "as_of": "2026-11-06T10:05:00+05:30"}]) == 0     # throttled (15 min)
    assert store.add_marks([{**s, "as_of": "2026-11-06T10:20:00+05:30"}]) == 1
    actions = [j["action"] for j in store.journal()]
    assert actions == ["book"]


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# marks: EOD close, implied IV, model / future marks, live in session, fallbacks
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def test_mark_from_the_eod_chain_is_the_close_with_an_implied_iv() -> None:
    pos = {"id": 1, "kind": "CE", "side": "buy", "strike": 24550.0, "expiry": "2026-11-09", "lots": 1, "lot_size": 65, "entry_price": 156.15}
    mk = fo_book.mark_from_chain(pos, chain_fixture("2026-11-09"), live=False, as_of=EVENING)
    assert mk["price"] == 156.15 and mk["mark_method"] == "close" and mk["kind"] == "eod"
    assert mk["t_days"] == pytest.approx(4.0) and mk["mark_date"] == "2026-11-05"    # 5 Nov 15:30 → 9 Nov 15:30, no half-day (M04)
    # the IV reproduces the close at the book's T, and that T is the chain's: the book shows the chain's 15.45 % (one number)
    assert om.black76("CE", 24545.75, 24550, om.t_years(mk["t_days"]), mk["iv"] / 100).price == pytest.approx(156.15, abs=0.01)
    assert mk["iv"] == pytest.approx(15.45, abs=0.02)
    # negative control: the retired half-day rule (T = 4.5 d) makes the same close read 14.57 % — a second IV for one contract
    iv_half = fo_book.implied_vol("CE", 156.15, 24545.75, 24550, 4.5 / 365)
    assert iv_half is not None and mk["iv"] - iv_half > 0.5
    # negative control: a chain for ANOTHER expiry (data-service falls back to the nearest) never marks the position
    assert fo_book.mark_from_chain({**pos, "expiry": "2026-11-17"}, chain_fixture("2026-11-09"), live=False, as_of=EVENING) is None


def test_the_books_time_is_the_iv_stores_cal365_1530_rule() -> None:
    b76 = _black76_store_module()
    assert b76.TIME_CONVENTION == om.TIME_CONVENTION == "cal365-1530" and fo_book.TIME_CONVENTION.startswith("cal365-1530")
    exp = date(2026, 11, 9)
    for when in (EVENING, SESSION, datetime(2026, 11, 9, 15, 0, tzinfo=IST), datetime(2026, 11, 9, 16, 0, tzinfo=IST)):
        assert fo_book.t_days(exp, when) / 365 == pytest.approx(b76.t_years(exp, when), abs=1e-12), when
    assert fo_book.t_days(exp, fo_book.eod_as_of("2026-11-05")) == pytest.approx(b76.t_years(exp, date(2026, 11, 5)) * 365)
    # the chain's own t_days wins when it carries one (fractional live chains): the book's T is the chain's
    pos = {"id": 1, "kind": "CE", "side": "buy", "strike": 24550.0, "expiry": "2026-11-09", "lots": 1, "lot_size": 65, "entry_price": 1.0}
    live = chain_fixture("2026-11-09", live=True)
    mk = fo_book.mark_from_chain(pos, live, live=True, as_of=SESSION)
    assert mk["t_days"] == pytest.approx(3.2292, abs=1e-4) and mk["kind"] == "session"
    no_t = {k: v for k, v in live.items() if k != "t_days"}       # an older payload: the same rule computed here
    assert fo_book.mark_from_chain(pos, no_t, live=True, as_of=SESSION)["t_days"] == pytest.approx(3.2292, abs=1e-4)
    # negative control: the retired rule (+ half a day) is not what the book uses
    assert abs(fo_book.t_days(exp, SESSION) - (b76.t_years(exp, SESSION) * 365 + 0.5)) > 0.49


def test_model_mark_outside_the_window_and_future_marks() -> None:
    far = {"id": 2, "kind": "PE", "side": "sell", "strike": 22000.0, "expiry": "2026-11-09", "lots": 1, "lot_size": 65, "entry_price": 1.0}
    mk = fo_book.mark_from_chain(far, chain_fixture("2026-11-09"), live=False, as_of=EVENING)
    assert mk["mark_method"] == "model" and "nearest strike" in mk["price_source"]
    fut = {"id": 3, "kind": "FUT", "side": "buy", "strike": None, "expiry": "2026-11-23", "lots": 1, "lot_size": 65, "entry_price": 24500}
    near = fo_book.mark_from_chain(fut, chain_fixture("2026-11-23"), live=False, as_of=EVENING)
    assert near["mark_method"] == "future" and near["price"] == 24588.0
    far_fut = {**fut, "expiry": "2026-12-29"}
    m2 = fo_book.mark_from_chain(far_fut, chain_fixture("2026-12-29"), live=False, as_of=EVENING)
    assert m2["mark_method"] == "parity-forward" and m2["price"] == 24585.0       # control: not the near future's price
    assert fo_book.monthly_expiries(EXPIRIES) == ["2026-11-23", "2026-12-29", "2027-01-25"]


def test_in_session_marks_come_from_the_live_chain_and_fall_back_to_eod(env: dict[str, Any]) -> None:
    c = env["client"]
    _book(c)
    env["now"] = SESSION
    b = c.get("/api/options/book/marks").json()
    assert b["marks_meta"]["used"] == "live" and all(m["kind"] == "session" for m in b["marks"])
    assert b["mark_source"]["state"] == "delayed"                  # never LIVE: NSE's chain is ≈ 1 min behind
    env["live_fails"] = True
    fo_book._chain_cache.clear()
    b2 = c.get("/api/options/book/marks").json()
    assert b2["marks_meta"]["used"] == "eod" and any("live chain unavailable" in n for n in b2["marks_meta"]["notes"])
    assert all(m["kind"] == "eod" for m in b2["marks"])
    env["now"] = EVENING                                           # control: after the close no live call is made
    env["calls"].clear()
    fo_book._chain_cache.clear()
    c.get("/api/options/book/marks")
    assert env["calls"] and not any(live for _, _, live in env["calls"])


def test_eod_mark_job_is_idempotent(env: dict[str, Any]) -> None:
    c = env["client"]
    _book(c)
    first = c.post("/api/options/book/mark").json()
    assert first["marked"] == 2 and first["written"] == 2
    again = c.post("/api/options/book/mark").json()
    assert again["written"] == 0


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# expired contracts: NSE's final settlement, point-in-time (checker major 2, 6 Nov) — never a later spot
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════

EXPIRY_EVENING = datetime(2026, 11, 9, 20, 0, tzinfo=IST)     # the 9-Nov bhavcopy is in: the expiry-day chain
LATER = datetime(2026, 11, 12, 20, 0, tzinfo=IST)             # 9 Nov is no longer listed; NIFTY has moved on


def _expiry_day_chain(expiry: str, *, spot: float = 24600.0, day: str = "2026-11-09") -> dict[str, Any]:
    """The stored chain dated the expiry day itself (t = 0): CE 24,550 last traded 52 (≠ intrinsic 50 on spot 24,600)."""
    ch = chain_fixture(expiry if expiry in EXPIRIES else EXPIRIES[1])
    ch.update({"date": day, "spot": spot, "forward": spot, "future": spot, "t_days": 0.0, "days_to_expiry": 0})
    if ch["expiry"] == "2026-11-09":
        for r in ch["rows"]:
            if r["strike"] == 24550.0:
                r["ce"]["price"], r["pe"]["price"] = 52.0, 0.05
    return ch


def _moved_on_chain(expiry: str, *, spot: float = 25000.0) -> dict[str, Any]:
    """12 Nov: data-service serves the 17-Nov chain for any request (9 Nov expired); spot 25,000."""
    ch = chain_fixture("2026-11-17")
    ch.update({"date": "2026-11-12", "spot": spot, "forward": spot})
    return ch


def _patch_chain(monkeypatch: pytest.MonkeyPatch, fn: Any) -> None:
    async def fc(symbol: str, expiry: str, live: bool) -> dict[str, Any]:
        return fn(expiry)
    fo_book._chain_cache.clear()
    monkeypatch.setattr(fo_book, "fetch_chain", fc)


def test_an_expired_leg_is_marked_and_closed_at_the_expiry_day_settlement(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    c = env["client"]
    s = _book(c)
    ce, pe = (p["id"] for p in s["positions"])
    _patch_chain(monkeypatch, _expiry_day_chain)
    env["now"] = EXPIRY_EVENING
    b9 = {p["id"]: p for p in c.get("/api/options/book").json()["structures"][0]["positions"]}
    m9 = b9[ce]["mark"]
    # NSE's final settlement: intrinsic on the expiry day's underlying close (24,600 − 24,550), not the CE's last trade (52)
    assert m9["mark_method"] == "settlement" and m9["price"] == 50.0 and m9["t_days"] == 0.0 and m9["mark_date"] == "2026-11-09"
    assert "NSE final settlement 2026-11-09" in m9["price_source"] and b9[pe]["mark"]["price"] == 0.0
    assert b9[ce]["greeks"]["delta"] == 0.0 and b9[ce]["greeks"]["theta_day"] == 0.0          # settled: no exposure left
    # 12 Nov: the chain no longer lists 9 Nov and NIFTY is at 25,000 — the mark stays the stored settlement
    _patch_chain(monkeypatch, _moved_on_chain)
    env["now"] = LATER
    m12 = {p["id"]: p for p in c.get("/api/options/book").json()["structures"][0]["positions"]}[ce]["mark"]
    assert m12["mark_method"] == "settlement" and m12["price"] == 50.0 and "stored expiry-day mark" in m12["price_source"]
    # negative control: intrinsic on the LATER spot would have been 450 (the 5 Nov reproduction's +₹19,100)
    assert max(25000.0 - 24550.0, 0.0) == 450.0 != m12["price"]
    env["calls"].clear()                           # scope the no-fetch claim to the CLOSE below (E-JRNL books now capture context)
    done = c.post("/api/options/book/close", json={"position_ids": [ce]}).json()
    fill = done["fills"][0]
    assert fill["exit_price"] == 50.0 and fill["exit_price_source"].startswith("NSE final settlement 2026-11-09")
    assert fill["pnl"]["realised"] == pytest.approx((50.0 - 156.15) * 65)                      # −₹6,900, not +₹19,100
    assert fill["exit_costs"] == pytest.approx(50.0 * 65 * 0.00125, abs=0.01)                  # exercise STT only (long ITM)
    assert not any(call[0] == "get_json" for call in env["calls"])                              # the stored spot sufficed
    # RSK › F&O: the settled PE carries no margin and no scenario P&L (its value is fixed at the settlement)
    rf = c.get("/api/risk/fo").json()
    assert rf["open_positions"] == 1 and rf["margin"] is None and all(x["pnl_inr"] == 0 for x in rf["scenarios"]["gap"])
    assert env["breeze"].touched == []                                                          # no margin call for a dead contract
    # CONFIRM of a previewed settlement keeps settlement costs: the worthless PE pays nothing (a trade would pay ₹20 + GST)
    pv = c.post("/api/options/book/close", json={"position_ids": [pe], "preview": True}).json()
    seen = pv["fills"][0]
    assert seen["exit_price"] == 0.0 and seen["exit_costs"] == 0.0
    assert fo_book.leg_costs(fbs.get_store().position(pe), 0.0, "exit") > 0                    # control: the trade schedule
    done_pe = c.post("/api/options/book/close", json={"position_ids": [pe], "previewed_at": pv["as_of"],
                                                      "confirm": {str(pe): {"price": 0.0, "source": seen["exit_price_source"]}}}).json()
    assert done_pe["fills"][0]["exit_costs"] == 0.0 and "confirmed as previewed at 20:00 IST" in done_pe["fills"][0]["exit_price_source"]


def test_an_expired_leg_never_marked_on_its_expiry_day_reads_that_days_close(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    c = env["client"]
    s = _book(c)
    ce = s["positions"][0]["id"]
    c.get("/api/options/book")                                     # 5 Nov evening: an ordinary close is stored, nothing later
    urls: list[str] = []

    async def closes(url: str, **kw: Any) -> dict[str, Any]:
        urls.append(url)
        if "/db/index-ohlc/NIFTY 50" in url:
            return {"rows": [{"date": "2026-11-06", "close": 24480.0}, {"date": "2026-11-09", "close": 24620.0},
                             {"date": "2026-11-10", "close": 24900.0}, {"date": "2026-11-12", "close": 25000.0}]}
        raise fo_book.UpstreamError(404, "not here")

    monkeypatch.setattr(fo_book, "get_json", closes)
    _patch_chain(monkeypatch, _moved_on_chain)
    env["now"] = LATER
    m = c.get("/api/options/book/marks").json()
    mk = next(x for x in m["marks"] if x["position_id"] == ce)
    assert mk["mark_method"] == "settlement" and mk["price"] == 70.0 and "index_ohlc_daily NIFTY 50 2026-11-09" in mk["price_source"]
    assert urls and all(u.startswith(fo_book.DATA_SVC) for u in urls)
    # derived from stored data on read, never written as a mark (a later read recomputes the same value)
    assert all(r["mark_method"] != "settlement" for r in fbs.get_store().marks([ce]))
    # negative control: without the 9-Nov row (only later closes stored) there is NO settlement — never the 10-Nov / 12-Nov close
    async def later_only(url: str, **kw: Any) -> dict[str, Any]:
        return {"rows": [{"date": "2026-11-10", "close": 24900.0}, {"date": "2026-11-12", "close": 25000.0}]}

    monkeypatch.setattr(fo_book, "get_json", later_only)
    fo_book._history_cache.clear()
    m2 = c.get("/api/options/book/marks").json()
    mk2 = next(x for x in m2["marks"] if x["position_id"] == ce)
    assert mk2["mark_method"] == "expired-unsettled" and mk2["price"] == 156.15 and mk2["mark_date"] == "2026-11-05"
    assert any("not stored yet" in n for n in m2["marks_meta"]["notes"])
    r = c.post("/api/options/book/close", json={"position_ids": [ce]})
    assert r.status_code == 409 and "settlement" in r.text                                       # never closed at a pre-expiry mark
    typed = c.post("/api/options/book/close", json={"position_ids": [ce], "prices": {str(ce): 70.0}})
    assert typed.status_code == 200 and typed.json()["fills"][0]["exit_price_source"] == "edited by hand at close"   # control


def test_the_mark_job_settles_expired_legs_once(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    c = env["client"]
    s = _book(c)
    _patch_chain(monkeypatch, _expiry_day_chain)
    env["now"] = EXPIRY_EVENING
    held = c.post("/api/options/book/mark", params={"settle": "false"}).json()
    assert held["settled"] == [] and c.get("/api/options/book").json()["open_positions"] == 2   # control: settle=false closes nothing
    first = c.post("/api/options/book/mark").json()
    assert sorted(x["id"] for x in first["settled"]) == sorted(p["id"] for p in s["positions"])
    assert all(x["status"] == "closed" and x["exit_price_source"].startswith("NSE final settlement") for x in first["settled"])
    assert {x["kind"]: x["exit_price"] for x in first["settled"]} == {"CE": 50.0, "PE": 0.0}
    again = c.post("/api/options/book/mark").json()
    assert again["settled"] == [] and again["positions"] == 0
    assert [j["action"] for j in fbs.get_store().journal()][0] == "settle"
    # a live contract is never settled by the job (the 17-Nov chain marks it at its close)
    s2 = _book(c, [{**STRADDLE[0], "expiry": "2026-11-17", "premium": 300.0}])
    _patch_chain(monkeypatch, lambda e: chain_fixture("2026-11-17"))
    assert c.post("/api/options/book/mark").json()["settled"] == []
    assert fbs.get_store().position(s2["positions"][0]["id"])["status"] == "open"


def test_an_expired_leg_cannot_be_rolled(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    c = env["client"]
    s = _book(c)
    _patch_chain(monkeypatch, _moved_on_chain)
    env["now"] = LATER
    r = c.post("/api/options/book/roll", json={"position_ids": [s["positions"][0]["id"]], "to_expiry": "2026-11-17"})
    assert r.status_code == 422 and "cannot be rolled" in r.text


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# confirm fills at the previewed prices; state errors are 409; exit prices are ≥ 0; the margin cache ignores the mark
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def test_confirm_fills_at_the_previewed_price_labelled(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    c = env["client"]
    s = _book(c)
    ce = s["positions"][0]["id"]
    env["now"] = SESSION
    pv = c.post("/api/options/book/close", json={"position_ids": [ce], "preview": True}).json()
    seen = pv["fills"][0]
    assert pv["as_of"].startswith("2026-11-06T10:00")
    # the chain moves before CONFIRM
    _patch_chain(monkeypatch, lambda e: {**chain_fixture(e, live=True), "rows": _rows(24600.0, 15.5, 3.2292)})
    moved = c.post("/api/options/book/close", json={"position_ids": [ce], "preview": True}).json()["fills"][0]["exit_price"]
    assert moved != seen["exit_price"]                                                            # control: a re-price differs
    done = c.post("/api/options/book/close", json={"position_ids": [ce], "previewed_at": pv["as_of"],
                                                   "confirm": {str(ce): {"price": seen["exit_price"], "source": seen["exit_price_source"]}}}).json()
    f = done["fills"][0]
    assert f["exit_price"] == seen["exit_price"] and f["exit_price_source"].endswith("confirmed as previewed at 10:00 IST")
    assert f["exit_price_source"].startswith("NSE option chain in session")


def test_a_close_raced_by_another_window_is_409_not_500(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    c = env["client"]
    s = _book(c)
    ce = s["positions"][0]["id"]
    real = fo_book.marks_with_fallback

    async def raced(positions: list[dict[str, Any]], mode: str = "auto", **kw: Any) -> Any:
        out = await real(positions, mode, **kw)
        fbs.get_store().close([{"position_id": ce, "exit_price": 1.0, "exit_price_source": "the other window"}])
        return out

    monkeypatch.setattr(fo_book, "marks_with_fallback", raced)
    r = c.post("/api/options/book/close", json={"position_ids": [ce]})
    assert r.status_code == 409 and "already closed" in r.text
    monkeypatch.setattr(fo_book, "marks_with_fallback", real)
    assert c.post("/api/options/book/close", json={"position_ids": [s["positions"][1]["id"]]}).status_code == 200   # control


def test_exit_prices_are_never_negative(env: dict[str, Any]) -> None:
    c = env["client"]
    s = _book(c)
    ce = s["positions"][0]["id"]
    assert c.post("/api/options/book/close", json={"position_ids": [ce], "prices": {str(ce): -5.0}}).status_code == 422
    store = fbs.get_store()
    with pytest.raises(fbs.BookError):
        store.close([{"position_id": ce, "exit_price": -1.0}])
    con = sqlite3.connect(str(fbs.default_db_path()))
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("UPDATE paper_fo_positions SET exit_price = -2 WHERE id = ?", (ce,))
    con.close()
    ok = c.post("/api/options/book/close", json={"position_ids": [ce], "prices": {str(ce): 0.0}})          # control: 0 is a price
    assert ok.status_code == 200 and ok.json()["fills"][0]["exit_price"] == 0.0


def test_the_margin_cache_is_keyed_on_contracts_not_marks(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    leg = {"side": "buy", "kind": "CE", "strike": 24550.0, "expiry": "2026-11-09", "lots": 1, "lot_size": 65}
    k1 = fo_book.margin_cache_key("NIFTY", [{**leg, "mark": {"price": 150.0}}])
    assert k1 == fo_book.margin_cache_key("nifty", [{**leg, "mark": {"price": 162.4}}])          # a moving mark: same key
    assert k1 != fo_book.margin_cache_key("NIFTY", [{**leg, "lots": 2}])                          # control: a new size asks again
    c = env["client"]
    _book(c)

    async def fake_returns(symbol: str, sessions: int = 750) -> tuple[dict[str, float], str, None]:
        return {f"d{i:04d}": 0.01 * math.sin(i) for i in range(300)}, "fixture", None

    monkeypatch.setattr(fo_book, "underlying_returns", fake_returns)
    env["now"] = SESSION
    assert c.get("/api/risk/fo").status_code == 200
    _patch_chain(monkeypatch, lambda e: {**chain_fixture(e, live=True), "rows": _rows(24600.0, 15.5, 3.2292)})   # marks move
    assert c.get("/api/risk/fo").status_code == 200
    assert env["breeze"].touched.count("margin_calculator") == 1                                   # one Breeze call, not two


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# Greeks per underlying and total; P&L; close; roll
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def test_net_greeks_per_underlying_and_total_in_rupee_terms_only(env: dict[str, Any]) -> None:
    c = env["client"]
    _book(c)
    g = c.get("/api/options/book/greeks").json()["greeks"]
    (u,) = g["by_underlying"]
    assert u["symbol"] == "NIFTY" and u["positions"] == 2
    assert abs(u["delta_lots"]) < 0.05 and u["gamma"] > 0 and u["theta_day"] < 0 and u["vega"] > 0
    assert u["delta_lots"] == pytest.approx(u["delta"] / 65, abs=1e-5)
    assert u["delta_inr_per_1pct"] == pytest.approx(u["delta"] * 24545.75 * 0.01, rel=1e-3)
    assert set(g["total"]) == {"theta_day", "vega", "delta_inr_per_1pct", "gamma_pnl_1pct_inr"}   # no unit sum across names
    # negative control: two underlyings' units never add into the total
    rows = [{"symbol": "NIFTY", "lot_size": 65, "forward": 24500, "greeks": {"delta": 10.0, "gamma": 0.1, "theta_day": -5, "vega": 3,
                                                                                "delta_inr_per_1pct": 2450.0, "gamma_pnl_1pct_inr": 300.0}},
            {"symbol": "RELIANCE", "lot_size": 500, "forward": 1500, "greeks": {"delta": 100.0, "gamma": 1.0, "theta_day": -2, "vega": 1,
                                                                                   "delta_inr_per_1pct": 1500.0, "gamma_pnl_1pct_inr": 112.5}}]
    agg = fo_book.aggregate_greeks(rows)
    assert "delta" not in agg["total"] and agg["total"]["delta_inr_per_1pct"] == 3950.0


def test_close_at_the_mark_realises_pnl_net_of_costs_and_closes_the_structure(env: dict[str, Any]) -> None:
    c = env["client"]
    struct = _book(c)
    prev = c.post("/api/options/book/close", json={"structure_id": struct["id"], "preview": True}).json()
    assert prev["preview"] is True and len(c.get("/api/options/book").json()["structures"]) == 1    # preview writes nothing
    done = c.post("/api/options/book/close", json={"structure_id": struct["id"], "prices": {str(struct["positions"][0]["id"]): 200.0}}).json()
    by = {f["position_id"]: f for f in done["fills"]}
    ce_id, pe_id = struct["positions"][0]["id"], struct["positions"][1]["id"]
    assert by[ce_id]["exit_price"] == 200.0 and by[ce_id]["exit_price_source"] == "edited by hand at close"
    assert by[pe_id]["exit_price"] == 160.40 and "bhavcopy" in by[pe_id]["exit_price_source"]
    assert by[ce_id]["pnl"]["realised"] == pytest.approx((200.0 - 156.15) * 65)
    assert by[ce_id]["pnl"]["net"] < by[ce_id]["pnl"]["realised"]                     # costs come off
    book_all = c.get("/api/options/book", params={"status": "all"}).json()
    assert book_all["structures"][0]["status"] == "closed" and c.get("/api/options/book").json()["structures"] == []
    again = c.post("/api/options/book/close", json={"structure_id": struct["id"]})
    assert again.status_code == 404                                                     # nothing open left


def test_roll_preview_then_execute_links_the_legs(env: dict[str, Any]) -> None:
    c = env["client"]
    struct = _book(c)
    pid = struct["positions"][0]["id"]
    pv = c.post("/api/options/book/roll", json={"position_ids": [pid], "to_expiry": "2026-11-17", "strike_shift": 50}).json()
    assert pv["preview"] is True and pv["legs"][0]["new_strike"] == 24600.0 and pv["legs"][0]["close_at"] == 156.15
    assert c.get("/api/options/book").json()["open_positions"] == 2                     # preview wrote nothing
    done = c.post("/api/options/book/roll", json={"position_ids": [pid], "to_expiry": "2026-11-17", "strike_shift": 50, "preview": False}).json()
    old, new = done["closed"][0], done["opened"][0]
    assert old["status"] == "rolled" and old["rolled_to"] == new["id"] and new["rolled_from"] == pid
    assert new["expiry"] == "2026-11-17" and new["strike"] == 24600.0 and new["structure_id"] == struct["id"]
    # negative controls: an unlisted expiry and the same expiry are refused
    assert c.post("/api/options/book/roll", json={"position_ids": [new["id"]], "to_expiry": "2026-11-18"}).status_code == 422
    assert c.post("/api/options/book/roll", json={"position_ids": [new["id"]], "to_expiry": "2026-11-17"}).status_code == 422


def test_structure_summary_reports_share_of_max_profit_and_loss_vs_credit() -> None:
    legs = [{"id": 1, "side": "sell", "kind": "PE", "strike": 24300.0, "expiry": "2026-11-09", "lots": 1, "lot_size": 65, "entry_price": 64.85,
             "status": "open", "entry_costs": 0.0, "rolled_from": None},
            {"id": 2, "side": "buy", "kind": "PE", "strike": 24100.0, "expiry": "2026-11-09", "lots": 1, "lot_size": 65, "entry_price": 30.90,
             "status": "open", "entry_costs": 0.0, "rolled_from": None}]
    credit = (64.85 - 30.90) * 65
    half = fo_book.structure_summary({"positions": legs}, {1: {"price": 64.85 - 20.0}, 2: {"price": 30.90 - 3.0}})
    assert half["net_label"] == "CREDIT" and half["entry_cashflow"] == pytest.approx(credit)
    assert half["pct_of_max_profit"] == pytest.approx((20.0 - 3.0) * 65 / credit * 100, abs=0.1) and half["loss_x_credit"] is None
    bad = fo_book.structure_summary({"positions": legs}, {1: {"price": 140.0}, 2: {"price": 60.0}})
    assert bad["loss_x_credit"] == pytest.approx(((140 - 64.85) - (60 - 30.90)) * 65 / credit, abs=0.01)


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# RSK › F&O: delta-gamma VaR, scenarios, margin utilisation
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def test_risk_fo_payload(env: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    c = env["client"]
    empty = c.get("/api/risk/fo").json()
    assert empty["empty"] is True and "Book paper" in empty["message"]
    _book(c)

    async def fake_returns(symbol: str, sessions: int = 750) -> tuple[dict[str, float], str, None]:
        return {f"d{i:04d}": 0.012 * math.sin(i * 1.7) for i in range(400)}, "fixture", None

    monkeypatch.setattr(fo_book, "underlying_returns", fake_returns)
    b = c.get("/api/risk/fo").json()
    dg, full = b["var"]["delta_gamma"], b["var"]["full_revaluation"]
    assert dg["sessions"] == 400 and dg["var95_1d_inr"] is not None and full["var95_1d_inr"] is not None
    # a long straddle: big moves either way make money, so the 1-day tail is theta on the quiet days — both methods agree
    assert dg["var95_1d_inr"] == pytest.approx(full["var95_1d_inr"], rel=0.35)
    iv = {s["iv_shift"]: s["pnl_inr"] for s in b["scenarios"]["iv_shock"]}
    assert iv[5.0] > 0 > iv[-5.0]                                 # long vega
    gaps = {s["spot_pct"]: s["pnl_inr"] for s in b["scenarios"]["gap"]}
    assert gaps[-5.0] > 0 and gaps[5.0] > 0                       # long gamma
    m = b["margin"]
    assert m["total_margin"] == pytest.approx(81497.07) and m["utilisation_pct"] == pytest.approx(81497.07 / 1_000_000 * 100, abs=0.01)
    assert b["capital"]["value"] == 1_000_000 and "unset" in b["capital"]["source"]
    no_margin = c.get("/api/risk/fo", params={"margin": "false"}).json()
    assert no_margin["margin"] is None
    assert b["var"]["note"].endswith("describes, does not predict")


def test_underlying_returns_read_data_service_only(monkeypatch: pytest.MonkeyPatch) -> None:
    urls: list[str] = []

    async def fake_get_json(url: str, **kw: Any) -> dict[str, Any]:
        urls.append(url)
        if "/db/index-ohlc/" in url:
            return {"rows": [{"date": f"2026-10-{d:02d}", "close": 24000 + 10 * d} for d in range(1, 29)] * 1}
        if "/db/index-daily" in url:
            return {"rows": [{"date": f"2025-{m:02d}-{d:02d}", "close": 20000 + m * 30 + d} for m in range(1, 13) for d in range(1, 28)]}
        return {"rows": [{"date": "2026-11-05", "change_pct": 1.5}, {"date": "2026-11-04", "change_pct": -0.5}]}

    import asyncio
    fo_book._history_cache.clear()
    monkeypatch.setattr(fo_book, "get_json", fake_get_json)
    rets, src, err = asyncio.run(fo_book.underlying_returns("NIFTY"))
    assert err is None and src == "market_index_daily (NIFTY50)" and len(rets) > 60     # 27 index-file rows < 60 → the fallback
    rets2, src2, _ = asyncio.run(fo_book.underlying_returns("RELIANCE"))
    assert rets2 == {"2026-11-05": 0.015, "2026-11-04": -0.005} and "bhavcopy" in src2
    assert all(u.startswith(fo_book.DATA_SVC) for u in urls) and not any("yahoo" in u for u in urls)


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# OSTR v2 (M39 + minors)
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def _analyze(c: TestClient, legs: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
    body = {"symbol": "NIFTY", "forward": 24545.75, "days_to_expiry": 4.0, "default_iv": 15.45, "legs": legs, **kw}
    r = c.post("/api/options/strategy/analyze", json=body)
    assert r.status_code == 200, r.text
    return r.json()


CALENDAR = [{"side": "sell", "kind": "CE", "strike": 24500, "premium": 180.30, "lots": 1, "lot_size": 65, "days": 4.0, "forward": 24545.75, "iv": 15.0},
            {"side": "buy", "kind": "CE", "strike": 24500, "premium": 278.95, "lots": 1, "lot_size": 65, "days": 12.0, "forward": 24585.0, "iv": 13.96}]


def test_calendar_is_priced_at_the_nearest_expiry_with_per_leg_forwards(env: dict[str, Any]) -> None:
    d = _analyze(env["client"], CALENDAR)
    assert d["multi_expiry"] is True and d["net_label"] == "DEBIT" and d["entry_cashflow"] == pytest.approx(-6412.25)
    at = min(d["payoff"], key=lambda p: abs(p["s"] - 24500))
    # by hand: short leg at intrinsic 0 at 24,500; the long 17-Nov call with 8 days left at 13.96 % on 24,500 × 24585 / 24545.75
    lvl = 24500 * 24585.0 / 24545.75
    by_hand = (om.black76("CE", lvl, 24500, 8 / 365, 0.1396).price - 278.95) * 65 + (180.30 - 0.0) * 65
    assert at["expiry"] == pytest.approx(by_hand, abs=1.0)
    assert len(d["breakevens"]) == 2 and d["max_loss"]["unbounded"] is False and d["max_profit"]["unbounded"] is False
    # negative control: a diagonal that is net SHORT calls above has an open-ended loss
    naked = [{**CALENDAR[0], "lots": 2}, CALENDAR[1]]
    assert _analyze(env["client"], naked)["max_loss"]["unbounded"] is True


def test_scenario_curve_grid_and_probability_of_profit(env: dict[str, Any]) -> None:
    straddle = [{k: v for k, v in leg.items() if k not in ("expiry", "price_source", "forward")} for leg in STRADDLE]
    base = _analyze(env["client"], straddle, grid=True)
    assert all(p["scenario"] == pytest.approx(p["now"], abs=1.0) for p in base["payoff"])        # T+0, IV +0 = today (s is rounded to 0.01)
    shifted = _analyze(env["client"], straddle, scenario_days=2, iv_shift=-2)
    centre = min(shifted["payoff"], key=lambda p: abs(p["s"] - 24550))
    assert centre["scenario"] < centre["now"]                         # control: theta + a lower IV cost a long straddle
    g = base["grid"]
    assert len(g["pnl"]) == len(g["days"]) and len(g["pnl"][0]) == 11 and len(g["pnl"][0][0]) == 9 and g["days"][0] == 0.0
    i0, j0 = g["spot_pct"].index(0.0), g["iv_shift"].index(0.0)
    now_at_f = min(base["payoff"], key=lambda p: abs(p["s"] - 24545.75))
    assert g["pnl"][0][i0][j0] == pytest.approx(now_at_f["now"], abs=40)
    pop = base["pop"]
    assert pop["badge"] == "heuristic" and pop["note"].endswith("describes, does not predict.")
    # closed form: P(outside both breakevens) under the lognormal at 15.45 % over 4 days (cal365-1530)
    s = 0.1545 * math.sqrt(4.0 / 365)
    above = lambda k: om.norm_cdf((math.log(24545.75 / k) - s * s / 2) / s)  # noqa: E731
    lo_be, hi_be = base["breakevens"]
    assert pop["value"] == pytest.approx((1 - above(lo_be) + above(hi_be)) * 100, abs=0.15)
    short = [{**leg, "side": "sell"} for leg in straddle]
    assert _analyze(env["client"], short)["pop"]["value"] == pytest.approx(100 - pop["value"], abs=0.2)   # the mirror


def test_cost_items_add_up_and_exercise_stt_and_spread(env: dict[str, Any]) -> None:
    straddle = [{k: v for k, v in leg.items() if k not in ("expiry", "price_source", "forward")} for leg in STRADDLE]
    d = _analyze(env["client"], straddle, slippage_per_unit=0.5)
    disp = d["costs"]["display"]
    assert sum(v for _, v in disp["items"]) == disp["total"] and any(k == "stamp + SEBI + IPFT" for k, _ in disp["items"])
    assert abs(disp["total"] - disp["exact_total"]) <= 2
    # the review's evidence: 80 + 21 + 14 + 17 = 132 printed against ₹133 — the old four items do not add up
    rt = d["costs"]["round_trip"]
    assert round(rt["brokerage"]) + round(rt["stt"]) + round(rt["txn"]) + round(rt["gst"]) != round(rt["total"])
    assert d["costs"]["spread"]["value"] == pytest.approx(130 * 0.5 * 2)
    itm = [{"side": "buy", "kind": "CE", "strike": 24000, "premium": 600, "lots": 1, "lot_size": 65, "iv": 15}]
    assert _analyze(env["client"], itm)["costs"]["exercise_stt"]["value"] == pytest.approx((24545.75 - 24000) * 65 * 0.00125, abs=0.01)
    otm = [{**itm[0], "strike": 25000, "premium": 30}]
    assert _analyze(env["client"], otm)["costs"]["exercise_stt"]["value"] == 0.0       # control: OTM pays none


def test_covered_call_on_shares_uses_the_cash_cost_model_and_no_margin(env: dict[str, Any]) -> None:
    legs = [{"side": "buy", "kind": "EQ", "premium": 24536.6, "lots": 1, "lot_size": 65, "forward": 24536.6},
            {"side": "sell", "kind": "CE", "strike": 24800, "premium": 69.85, "lots": 1, "lot_size": 65, "iv": 14.6}]
    d = _analyze(env["client"], legs)
    assert d["costs"]["equity"]["source"].startswith("shared/trading_costs.py") and d["costs"]["equity"]["round_trip"]["total"] > 0
    assert d["margin"]["excludes_shares"] is True
    assert d["max_loss"]["unbounded"] is False and d["max_profit"]["unbounded"] is False
    assert d["greeks"]["net"]["delta"] > 0


def test_net_delta_in_lots_and_rupees_per_one_percent(env: dict[str, Any]) -> None:
    straddle = [{k: v for k, v in leg.items() if k not in ("expiry", "price_source", "forward")} for leg in STRADDLE]
    u = _analyze(env["client"], straddle)["greeks"]["net_units"]
    net = _analyze(env["client"], straddle)["greeks"]["net"]
    assert u["delta_lots"] == pytest.approx(net["delta"] / 65, abs=1e-5) and u["delta_inr_per_1pct"] == pytest.approx(net["delta"] * 245.4575, abs=1e-3)
    assert abs(u["delta_inr_per_1pct"]) < 100                       # the review: "≈ ₹33 per 1 %" for tonight's straddle


def test_saved_structures_crud(env: dict[str, Any]) -> None:
    c = env["client"]
    legs = [{**STRADDLE[0]}, {**STRADDLE[1]}]
    s = c.post("/api/options/strategy/saved", json={"symbol": "nifty", "name": "Mon straddle", "legs": legs}).json()["saved"]
    assert s["symbol"] == "NIFTY" and s["legs"][0]["price_source"] == "NSE F&O bhavcopy 2026-11-05"
    again = c.post("/api/options/strategy/saved", json={"symbol": "NIFTY", "name": "Mon straddle", "legs": legs[:1]}).json()["saved"]
    assert again["id"] == s["id"] and len(again["legs"]) == 1                          # same name + symbol: overwritten
    assert c.get("/api/options/strategy/saved", params={"symbol": "NIFTY"}).json()["count"] == 1
    assert c.get("/api/options/book").json()["structures"] == []                       # saving books nothing
    assert c.delete(f"/api/options/strategy/saved/{s['id']}").status_code == 200
    assert c.delete(f"/api/options/strategy/saved/{s['id']}").status_code == 404


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# RSK: M18 sizing at the Desk's equity share, m107 legacy rule apart, m108 stress coverage
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def _fake_rsk(monkeypatch: pytest.MonkeyPatch) -> None:
    import pandas as pd
    days = pd.bdate_range("2023-10-02", periods=760)
    desk = {"meta": {"cash": 503131.31, "peak": 503131.31, "stopped": 0, "config": {"equity_share": 0.66, "sector_cap": 0.4}},
            "latest": {"nav": 503131.31}, "positions": [], "nav": [{"date": "2026-11-04", "nav": 503000.0}, {"date": "2026-11-05", "nav": 503131.31}]}
    monkeypatch.setattr(riskdash, "_desk_book", lambda notes: desk)
    monkeypatch.setattr(riskdash, "_broker_book", lambda notes: ([], None))
    monkeypatch.setattr(riskdash, "_industries", lambda: {})

    long_days = pd.bdate_range("2019-12-02", "2026-11-05")

    def fetch(sym: str, start: date, stress_days: int) -> dict[str, Any]:
        seed = sum(map(ord, sym))
        vals = [0.03 * math.sin(i * 0.37 + seed) * (1 if i % 7 else 1.8) for i in range(len(days))]
        s = pd.Series(vals, index=days)
        long = pd.Series([0.01 * math.sin(i * 0.11 + seed) for i in range(len(long_days))], index=long_days)
        stress = long if sym != "YOUNG" else long[long.index >= "2024-01-01"]
        return {"symbol": sym, "panel": s, "stress": stress, "panel_err": None, "stress_err": None, "panel_src": "ohlcv"}

    monkeypatch.setattr(riskdash, "_fetch_symbol", fetch)
    monkeypatch.setattr(riskdash, "_fetch_nifty_returns", lambda: (pd.Series([0.001 * math.sin(i) for i in range(len(days))], index=days), None))
    riskdash._cache.clear()


def test_what_if_is_sized_at_the_desks_equity_share_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_rsk(monkeypatch)
    basket = "AAA,BBB,CCC,DDD"
    desk = riskdash.risk_dashboard(symbols=basket, lookback=750, refresh=True, size="desk", notional=None)
    nav = riskdash.risk_dashboard(symbols=basket, lookback=750, refresh=True, size="nav", notional=None)
    assert desk["sizing"]["mode"] == "desk" and desk["sizing"]["equity_share"] == 0.66
    assert desk["sizing"]["notional_inr"] == pytest.approx(503131.31 * 0.66, abs=1)
    assert desk["holdings"][0]["value_inr"] == pytest.approx(503131.31 * 0.66 / 4, abs=1)
    assert "equity share 66%" in " ".join(desk["notes"])
    ratio = desk["var"]["pct_of_book"]["var95_1d"] / nav["var"]["pct_of_book"]["var95_1d"]
    assert ratio == pytest.approx(0.66, abs=0.01)                    # the negative control: 100 % of NAV reads 1.5× higher
    custom = riskdash.risk_dashboard(symbols=basket, lookback=750, refresh=True, size="custom", notional=100000.0)
    assert custom["sizing"]["notional_inr"] == 100000


def test_rsk_lists_the_legacy_halt_apart_and_names_stress_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_rsk(monkeypatch)
    d = riskdash.risk_dashboard(symbols="AAA,BBB,YOUNG", lookback=750, refresh=True, size="desk", notional=None)
    rules = " ".join(d["ladder"]["rules"])
    assert "−2%" not in rules and "Daily loss" not in rules
    assert any("Legacy 5-day system" in r and "−2%" in r for r in d["ladder"]["legacy_rules"])
    assert "trips the −2% daily halt" not in d["severity"]["thresholds"]["var"]
    covid = next(s for s in d["stress"] if s["id"] == "covid_2020")
    assert covid["names_total"] == 3 and covid["names_covered"] == 2 and covid["partial"] is True
    election = next(s for s in d["stress"] if s["id"] == "election_2024")
    assert election["names_covered"] == 3 and election["partial"] is False             # control: full coverage


def test_custom_size_needs_a_notional() -> None:
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as e:
        riskdash.risk_dashboard(symbols="AAA", lookback=750, refresh=True, size="custom", notional=None)
    assert e.value.status_code == 422
