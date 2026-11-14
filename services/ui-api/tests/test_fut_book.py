"""The PAPER MCX futures book (FINAL ROUND R5-FUTBOOK) — every rule with a negative control.

Nothing here touches data/: the store is a temp SQLite (PAPER_FUT_DB) and data-service is never reached — the router's
``get_json`` is faked per test with payloads shaped like ``/db/gold/mcx/settlement`` (gold/reads._settlement_block) and
``/db/gold/mcx/daily``. Accepts (task): book → mark → close round trip point-in-time; expired-contract settle at the
stored settlement of record; labelling clean (badge arithmetic, "describes, does not predict", settlement_source
labelled, PAPER ONLY at the database level, no order method in the module).
"""
from __future__ import annotations

import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fut_book_store as fts  # noqa: E402
from routers import fut_book  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
TODAY = datetime.now(IST).date()
LIVE_EXPIRY = (TODAY + timedelta(days=40)).isoformat()
PAST_EXPIRY = (TODAY - timedelta(days=3)).isoformat()
PREV_SESSION = (TODAY - timedelta(days=1)).isoformat()
ORDER_METHODS = re.compile(r"\b(place_order|modify_order|cancel_order|square_off|squareoff|placeOrder|cancelOrder)\b")


def settlement_block(symbol: str, expiry: str, *, settlement: float | None, session: str | None,
                     source: str = "breeze_vwap30", quality: str = "vwap30_proxy") -> dict[str, Any]:
    """Shaped like gold/reads._settlement_block (the keys the router reads)."""
    return {"symbol": symbol, "expiry": expiry, "settlement": settlement, "settlement_source": source if settlement else None,
            "settlement_session": session, "settlement_quality": quality if settlement else None,
            "band_midpoint": None, "band_session": None, "settlement_is_latest": True}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    monkeypatch.setenv(fts.ENV_DB, str(tmp_path / "paper_fut.sqlite"))
    state: dict[str, Any] = {
        "settlement": {},   # (symbol, expiry, day|None) -> block
        "daily": {},        # (family, expiry) -> rows
        "calls": [],
    }

    async def fake_get_json(url: str, *, route: str = "read", params: dict[str, Any] | None = None, **kw: Any) -> Any:
        params = params or {}
        state["calls"].append((url, dict(params)))
        if url.endswith("/db/gold/mcx/settlement"):
            key = (params.get("symbol"), params.get("expiry"), params.get("date"))
            block = state["settlement"].get(key)
            if block is None:
                raise fut_book.UpstreamError(503, "no stored settlement fixture for this key")
            return block
        if url.endswith("/db/gold/mcx/daily"):
            rows = state["daily"].get((params.get("family"), params.get("expiry")), [])
            return {"rows": rows, "quality": "broker"}
        raise AssertionError(f"unexpected data-service read: {url}")

    monkeypatch.setattr(fut_book, "get_json", fake_get_json)
    app = FastAPI()
    app.include_router(fut_book.router, prefix="/api/mcx/book")
    state["client"] = TestClient(app)
    return state


def book_one(client: TestClient, *, expiry: str = LIVE_EXPIRY, side: str = "buy", lots: int = 2,
             price: float = 125_000.0, contract: str = "GOLD") -> dict[str, Any]:
    r = client.post("/api/mcx/book", json={
        "contract": contract, "expiry": expiry, "side": side, "lots": lots, "price": price,
        "price_source": "ICICI band midpoint (reference)", "brokerage_per_order": 20, "mode": "paper",
        "context": {"ticket": {"lots": lots, "price": price}}})
    assert r.status_code == 200, r.text
    return r.json()


# ── the store itself ─────────────────────────────────────────────────────────────────────────────────────────────


def test_store_paper_only_at_the_database_level(env: dict[str, Any]) -> None:
    """The CHECK (mode = 'paper') refuses any other value, whatever a caller sends — the negative control."""
    store = fts.get_store()
    pos = store.book(family="GOLD", expiry=LIVE_EXPIRY, side="buy", lots=1, multiplier=100.0,
                     entry_price=125_000.0, entry_price_source="test")
    assert pos["mode"] == "paper"
    with sqlite3.connect(str(store.path)) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE paper_fut_positions SET mode = 'live' WHERE id = ?", (pos["id"],))
    with sqlite3.connect(str(store.path)) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("""INSERT INTO paper_fut_positions(family, expiry, side, lots, multiplier, entry_price,
                        entry_price_source, opened_at, mode) VALUES ('GOLD', ?, 'buy', 1, 100, 1, 'x', 'now', 'live')""",
                     (LIVE_EXPIRY,))


def test_store_marks_are_append_only_point_in_time(env: dict[str, Any]) -> None:
    """Same (position, as_of, price) is skipped (idempotent); a revised price is a NEW row, never an overwrite."""
    store = fts.get_store()
    pos = store.book(family="GOLD", expiry=LIVE_EXPIRY, side="buy", lots=1, multiplier=100.0,
                     entry_price=125_000.0, entry_price_source="test")
    m = {"position_id": pos["id"], "as_of": PREV_SESSION, "price": 125_500.0, "price_source": "breeze_vwap30",
         "session": PREV_SESSION, "quality": "vwap30_proxy"}
    assert store.add_marks([m]) == 1
    assert store.add_marks([m]) == 0                      # idempotent
    assert store.add_marks([{**m, "price": 125_600.0}]) == 1   # a revision is its own row
    rows = store.marks([int(pos["id"])])
    assert [r["price"] for r in rows] == [125_500.0, 125_600.0]
    latest = store.latest_marks([int(pos["id"])])
    assert latest[int(pos["id"])]["price"] == 125_600.0   # the latest revision wins; the old row still stands


def test_store_realised_recorded_net_of_costs(env: dict[str, Any]) -> None:
    store = fts.get_store()
    pos = store.book(family="GOLDM", expiry=LIVE_EXPIRY, side="sell", lots=2, multiplier=10.0,
                     entry_price=125_000.0, entry_price_source="test", entry_costs=50.0)
    store.close([{"position_id": pos["id"], "exit_price": 124_000.0, "exit_price_source": "stored mark", "exit_costs": 40.0}])
    closed = store.position(int(pos["id"]))
    g, c, n = fts.realised_from_row(closed)
    # sell 2 lots × ₹10/₹1: price fell ₹1,000 → gross +₹20,000; net of ₹90 recorded costs
    assert (g, c, n) == (20_000.0, 90.0, 19_910.0)
    j = store.journal()
    settle_row = next(r for r in j if r["action"] == "close")
    assert settle_row["payload"]["realised_inr"] == 19_910.0   # recorded point-in-time, read back, never recomputed
    with pytest.raises(fts.BookError):                        # negative control: a closed position cannot close again
        store.close([{"position_id": pos["id"], "exit_price": 1.0, "exit_price_source": "x"}])


# ── the API round trip: book → mark → close, point-in-time ──────────────────────────────────────────────────────


def test_book_mark_close_round_trip(env: dict[str, Any]) -> None:
    client: TestClient = env["client"]
    booked = book_one(client)
    assert booked["paper"] is True and booked["recorded"] is True
    pid = booked["position"]["id"]
    assert booked["position"]["mode"] == "paper"
    assert booked["position"]["entry_costs"] > 0          # entry-side statutory cost recorded at booking

    # the journal keeps the booking context (the ticket as shown) point-in-time
    j = client.get("/api/mcx/book/journal").json()
    assert j["rows"][0]["action"] == "book" and j["rows"][0]["payload"]["context"]["ticket"]["price"] == 125_000.0

    env["settlement"][("GOLD", LIVE_EXPIRY, None)] = settlement_block(
        "GOLD", LIVE_EXPIRY, settlement=126_000.0, session=PREV_SESSION)
    r = client.post("/api/mcx/book/mark").json()
    assert r["marks_written"] == 1 and r["settled"] == [] and r["badge"] == "arithmetic"
    r2 = client.post("/api/mcx/book/mark").json()
    assert r2["marks_written"] == 0                        # idempotent per session+price

    body = client.get("/api/mcx/book").json()
    row = next(p for p in body["open"] if p["id"] == pid)
    assert row["mark"]["price"] == 126_000.0
    assert "breeze_vwap30" in row["mark"]["source"]        # settlement_source labelled on the mark
    # buy 2 lots × ₹100/₹1 × (126,000 − 125,000) = +₹200,000 (arithmetic, gross of exit costs)
    assert row["unrealised_inr"] == 200_000.0
    assert row["day_mtm_inr"] == 200_000.0 and "entry price" in row["day_mtm_basis"]

    done = client.post("/api/mcx/book/close", json={"position_ids": [pid], "mode": "paper"}).json()
    closed = done["closed"][0]
    assert closed["status"] == "closed" and closed["exit_price"] == 126_000.0
    assert "stored mark" in closed["exit_price_source"] and "breeze_vwap30" in closed["exit_price_source"]
    totals = client.get("/api/mcx/book").json()["totals"]
    assert 0 < totals["realised_inr"] < 200_000.0          # net of the recorded entry + exit costs
    assert totals["realised_gross_inr"] == 200_000.0
    assert totals["costs_inr"] == round(totals["realised_gross_inr"] - totals["realised_inr"], 2)


def test_day_mtm_against_previous_stored_mark(env: dict[str, Any]) -> None:
    client: TestClient = env["client"]
    pid = book_one(client)["position"]["id"]
    store = fts.get_store()
    two_back = (TODAY - timedelta(days=2)).isoformat()
    store.add_marks([{"position_id": pid, "as_of": two_back, "price": 125_400.0, "price_source": "breeze_vwap30"}])
    env["settlement"][("GOLD", LIVE_EXPIRY, None)] = settlement_block(
        "GOLD", LIVE_EXPIRY, settlement=125_900.0, session=PREV_SESSION)
    client.post("/api/mcx/book/mark")
    row = client.get("/api/mcx/book").json()["open"][0]
    assert row["day_mtm_inr"] == 2 * 100 * (125_900.0 - 125_400.0)   # vs the PREVIOUS stored mark, not entry
    assert two_back in row["day_mtm_basis"]
    assert row["unrealised_inr"] == 2 * 100 * (125_900.0 - 125_000.0)


# ── expired contracts: the stored settlement of record, never a later price ─────────────────────────────────────


def test_expired_settles_at_the_stored_settlement_of_record(env: dict[str, Any]) -> None:
    client: TestClient = env["client"]
    store = fts.get_store()
    pos = store.book(family="GOLD", expiry=PAST_EXPIRY, side="buy", lots=1, multiplier=100.0,
                     entry_price=124_000.0, entry_price_source="test", entry_costs=30.0)
    # the record OF the expiry session (MCX's DSP method: the last-30-min VWAP of that session)
    env["settlement"][("GOLD", PAST_EXPIRY, PAST_EXPIRY)] = settlement_block(
        "GOLD", PAST_EXPIRY, settlement=124_800.0, session=PAST_EXPIRY)
    # F5 (14 Nov 2026): a plain mark NEVER closes anything — the page mounts it, and a page view must not
    # mutate the track record. The expired contract is reported with its stored exit price instead.
    plain = client.post("/api/mcx/book/mark").json()
    assert plain["settled"] == [] and len(plain["awaiting_settlement"]) == 1
    assert plain["awaiting_settlement"][0]["exit_price"] == 124_800.0
    assert store.positions(status="open") and len(store.positions(status="open")) == 1   # still open
    # closing is the explicit action
    r = client.post("/api/mcx/book/mark?settle=true").json()
    assert len(r["settled"]) == 1 and r["expired_unsettled"] == []
    settled = r["settled"][0]
    assert settled["status"] == "closed" and settled["exit_kind"] == "settle"
    assert settled["exit_price"] == 124_800.0
    assert "settlement of record" in settled["exit_price_source"] and "breeze_vwap30" in settled["exit_price_source"]
    assert settled["closed_at"] is not None
    j = client.get("/api/mcx/book/journal").json()["rows"]
    assert j[0]["action"] == "settle" and j[0]["payload"]["gross_inr"] == 100 * (124_800.0 - 124_000.0)
    # point-in-time: the settle used the expiry session's record even though a LATER session's read exists
    env["settlement"][("GOLD", PAST_EXPIRY, None)] = settlement_block(
        "GOLD", PAST_EXPIRY, settlement=130_000.0, session=PREV_SESSION)
    assert store.position(int(pos["id"]))["exit_price"] == 124_800.0


def test_expired_record_of_a_different_session_does_not_settle(env: dict[str, Any]) -> None:
    """A settlement read whose session is NOT the expiry session is not the settlement of record — the position stays
    open as expired-unsettled and cannot be closed (negative control), at a typed price either."""
    client: TestClient = env["client"]
    store = fts.get_store()
    pos = store.book(family="GOLD", expiry=PAST_EXPIRY, side="buy", lots=1, multiplier=100.0,
                     entry_price=124_000.0, entry_price_source="test")
    env["settlement"][("GOLD", PAST_EXPIRY, PAST_EXPIRY)] = settlement_block(
        "GOLD", PAST_EXPIRY, settlement=123_500.0, session=(TODAY - timedelta(days=5)).isoformat())
    r = client.post("/api/mcx/book/mark").json()
    assert r["settled"] == [] and len(r["expired_unsettled"]) == 1
    assert r["expired_unsettled"][0]["status"] == "expired-unsettled"
    assert store.position(int(pos["id"]))["status"] == "open"
    body = client.get("/api/mcx/book").json()
    assert body["open"][0]["state"] == "expired-unsettled"
    rc = client.post("/api/mcx/book/close", json={"position_ids": [pos["id"]], "mode": "paper"})
    assert rc.status_code == 409 and "settlement of record" in rc.text
    rt = client.post("/api/mcx/book/close", json={"position_ids": [pos["id"]], "prices": {str(pos["id"]): 130_000.0},
                                                  "mode": "paper"})
    assert rt.status_code == 409                           # expired: never a typed price


def test_expired_falls_back_to_the_stored_broker_daily_bar(env: dict[str, Any]) -> None:
    client: TestClient = env["client"]
    store = fts.get_store()
    store.book(family="GOLDM", expiry=PAST_EXPIRY, side="sell", lots=1, multiplier=10.0,
               entry_price=125_000.0, entry_price_source="test")
    env["settlement"][("GOLDM", PAST_EXPIRY, PAST_EXPIRY)] = settlement_block(
        "GOLDM", PAST_EXPIRY, settlement=None, session=None, source="", quality="")
    env["daily"][("GOLDM", PAST_EXPIRY)] = [
        {"trade_date": (TODAY - timedelta(days=4)).isoformat(), "close": 124_000.0},
        {"trade_date": PAST_EXPIRY, "close": 124_500.0},
    ]
    r = client.post("/api/mcx/book/mark?settle=true").json()   # F5: settling is explicit
    assert len(r["settled"]) == 1
    assert r["settled"][0]["exit_price"] == 124_500.0      # the bar ON the expiry session, not the 4-days-back one
    assert "breeze_daily_close" in r["settled"][0]["exit_price_source"]   # the fallback is labelled a broker bar


# ── refusals and labelling ──────────────────────────────────────────────────────────────────────────────────────


def test_paper_only_and_validation_refusals(env: dict[str, Any]) -> None:
    client: TestClient = env["client"]
    base = {"contract": "GOLD", "expiry": LIVE_EXPIRY, "side": "buy", "lots": 1, "price": 125_000.0,
            "price_source": "test"}
    assert client.post("/api/mcx/book", json={**base, "mode": "live"}).status_code == 422
    assert client.post("/api/mcx/book", json={**base, "contract": "SILVER"}).status_code == 422
    assert client.post("/api/mcx/book", json={**base, "expiry": PAST_EXPIRY}).status_code == 422   # expired: unbookable
    assert client.post("/api/mcx/book", json={**base, "price": 0}).status_code == 422
    pid = book_one(client)["position"]["id"]
    assert client.post("/api/mcx/book/close", json={"position_ids": [pid], "mode": "live"}).status_code == 422
    # no stored mark yet and no typed price → refused with the recipe
    r = client.post("/api/mcx/book/close", json={"position_ids": [pid], "mode": "paper"})
    assert r.status_code == 409 and "no stored mark" in r.text
    # a typed price closes, labelled 'edited'
    done = client.post("/api/mcx/book/close", json={"position_ids": [pid], "prices": {str(pid): 125_500.0},
                                                    "mode": "paper"}).json()
    assert "edited" in done["closed"][0]["exit_price_source"]
    assert client.post("/api/mcx/book/close", json={"position_ids": [999], "mode": "paper"}).status_code == 404


def test_labelling_clean_and_no_order_methods(env: dict[str, Any]) -> None:
    """Binding labelling rules: badge arithmetic, 'describes, does not predict', no composite score, no direction
    words; and no broker order method exists in the module or its store."""
    client: TestClient = env["client"]
    book_one(client)
    body = client.get("/api/mcx/book").json()
    assert body["paper"] is True and body["badge"] == "arithmetic"
    assert any("describes, does not predict" in n for n in body["notes"])
    assert any("PAPER ONLY" in n for n in body["notes"])
    blob = (client.get("/api/mcx/book").text + client.get("/api/mcx/book/journal").text).lower()
    for word in ("bullish", "bearish", "target", "signal", "score"):
        assert word not in blob
    src = (Path(fut_book.__file__).read_text() + Path(fts.__file__).read_text())
    assert not ORDER_METHODS.search(src)
    # no broker client is imported anywhere in the book: the only Breeze words are labels on stored data
    assert "breeze_connect" not in src.lower() and "import breeze" not in src.lower()
    assert "_get_breeze_client" not in src


def test_fresh_install_reads_answer_empty_without_creating_a_file(env: dict[str, Any]) -> None:
    client: TestClient = env["client"]
    store = fts.get_store()
    body = client.get("/api/mcx/book").json()
    assert body["open"] == [] and body["closed"] == []
    assert client.get("/api/mcx/book/journal").json()["rows"] == []
    assert not store.path.exists()                         # only a write creates the file
