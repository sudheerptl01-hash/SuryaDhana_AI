"""FINAL ROUND wave B, B-BOOKAPI (risk/SPEC.md §6): M3 realised recorded point-in-time on close, M1 the day-scoped
book read (``GET /api/options/book/day``), M2 the ±1 % gaps and the T−1d theta row in ``/api/risk/fo`` scenarios.

Same conventions as test_fo_book.py: the store is a temp SQLite (PAPER_FO_DB), chains are fixtures shaped like
data-service's payload, data-service is never reached, and both clocks (the router's and the store's) are patched so
IST-midnight scoping is exercised deterministically.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fo_book_store as fbs  # noqa: E402
import options_math as om  # noqa: E402
from routers import fo_book, riskdash  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
EVENING = datetime(2026, 11, 5, 21, 0, tzinfo=IST)            # after the close: EOD marks, journal ts 2026-11-05


def chain_fixture(expiry: str = "2026-11-09", *, day: str = "2026-11-05", forward: float = 24545.75,
                  iv: float = 15.45, days: float = 4.0) -> dict[str, Any]:
    rows = []
    for k in range(24300, 24801, 50):
        t = om.t_years(days)
        ce = round(om.black76("CE", forward, k, t, iv / 100).price, 2)
        pe = round(om.black76("PE", forward, k, t, iv / 100).price, 2)
        if k == 24550:
            ce, pe = 156.15, 160.40
        rows.append({"strike": float(k), "ce": {"price": ce, "iv": iv}, "pe": {"price": pe, "iv": iv}})
    return {"symbol": "NIFTY", "found": True, "date": day, "expiry": expiry, "expiries": [expiry, "2026-11-17"],
            "t_days": round(days, 4), "spot": forward - 9.0, "future": 24588.0, "forward": forward,
            "atm": 24550.0, "lot": 65, "atm_iv": iv, "rows": rows}


STRADDLE = [{"side": "buy", "kind": "CE", "strike": 24550, "expiry": "2026-11-09", "premium": 156.15, "iv": 15.45,
             "lots": 1, "lot_size": 65, "forward": 24545.75, "price_source": "NSE F&O bhavcopy 2026-11-05"},
            {"side": "buy", "kind": "PE", "strike": 24550, "expiry": "2026-11-09", "premium": 160.40, "iv": 15.45,
             "lots": 1, "lot_size": 65, "forward": 24545.75, "price_source": "NSE F&O bhavcopy 2026-11-05"}]


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[dict[str, Any]]:
    monkeypatch.setenv(fbs.ENV_DB, str(tmp_path / "paper_fo.sqlite"))
    for c in (fo_book._chain_cache, fo_book._margin_cache, fo_book._history_cache):
        c.clear()
    state: dict[str, Any] = {"now": EVENING}

    async def fake_chain(symbol: str, expiry: str, live: bool) -> dict[str, Any]:
        return chain_fixture(expiry if expiry == "2026-11-09" else "2026-11-17")

    async def no_network(url: str, **kw: Any) -> Any:
        raise fo_book.UpstreamError(503, "tests never reach data-service")

    monkeypatch.setattr(fo_book, "fetch_chain", fake_chain)
    monkeypatch.setattr(fo_book, "get_json", no_network)
    monkeypatch.setattr(fo_book, "now_ist", lambda: state["now"])
    monkeypatch.setattr(fbs, "now_ist", lambda: state["now"].isoformat(timespec="seconds"))  # the store's journal clock
    app = FastAPI()
    app.include_router(fo_book.router, prefix="/api/options/book")
    app.include_router(riskdash.router, prefix="/api/risk")
    state["client"] = TestClient(app)
    yield state


def _book(client: TestClient, legs: list[dict[str, Any]] = STRADDLE, **kw: Any) -> dict[str, Any]:
    r = client.post("/api/options/book", json={"symbol": "NIFTY", "name": "straddle", "legs": legs, **kw})
    assert r.status_code == 200, r.text
    return r.json()["structure"]


def _leg(entry: float = 100.0, **kw: Any) -> dict[str, Any]:
    return {"side": "buy", "kind": "CE", "strike": 24550.0, "expiry": "2026-11-09", "lots": 1, "lot_size": 65,
            "entry_price": entry, "entry_price_source": "fixture", "entry_costs": 0.0, **kw}


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# M3: the close journal records realised point-in-time — read back, never recomputed against moved rows
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def test_close_journal_records_realised_point_in_time(env: dict[str, Any]) -> None:
    c = env["client"]
    s = _book(c)
    ce = s["positions"][0]["id"]
    done = c.post("/api/options/book/close", json={"position_ids": [ce], "prices": {str(ce): 200.0}}).json()
    fill = done["fills"][0]
    row = next(j for j in fbs.get_store().journal() if j["action"] == "close")
    (jf,) = row["payload"]["fills"]                                    # one row per structure, that structure's fills only
    entry_costs = float(fbs.get_store().position(ce)["entry_costs"])
    gross = (200.0 - 156.15) * 65
    assert jf["position_id"] == ce and jf["symbol"] == "NIFTY"
    assert jf["gross_inr"] == pytest.approx(round(gross, 2))
    assert jf["costs_inr"] == pytest.approx(round(entry_costs + fill["exit_costs"], 2))
    assert jf["realised_inr"] == pytest.approx(round(gross - entry_costs - fill["exit_costs"], 2))
    # the recorded figure is the fact: a later drift in the position row never changes the day read
    con = sqlite3.connect(str(fbs.default_db_path()))
    con.execute("UPDATE paper_fo_positions SET exit_price = 999.0 WHERE id = ?", (ce,))
    con.commit()
    con.close()
    day = fbs.get_store().day_summary("2026-11-05")
    trade = next(t for t in day["trades"] if t["action"] == "close")
    assert trade["realised_inr"] == jf["realised_inr"] and trade["realised_source"] == "journal"
    assert day["realised_inr"] == jf["realised_inr"]
    # negative control: with the recorded figures stripped (a pre-M3 row), the derivation reads the moved row instead
    _strip_realised(fbs.default_db_path())
    derived = next(t for t in fbs.get_store().day_summary("2026-11-05")["trades"] if t["action"] == "close")
    assert derived["realised_source"] == "derived from the stored fills"
    assert derived["realised_inr"] != jf["realised_inr"] and derived["gross_inr"] == pytest.approx((999.0 - 156.15) * 65)


def _strip_realised(db: Path) -> None:
    """Rewrite close/settle journal payloads without the M3 fields (simulates rows written before this build)."""
    con = sqlite3.connect(str(db))
    for rid, payload in con.execute("SELECT id, payload FROM paper_fo_journal WHERE action IN ('close', 'settle')").fetchall():
        p = json.loads(payload)
        p["fills"] = [{k: v for k, v in f.items() if k not in ("gross_inr", "costs_inr", "realised_inr", "symbol")}
                      for f in p.get("fills", [])]
        con.execute("UPDATE paper_fo_journal SET payload = ? WHERE id = ?", (json.dumps(p), rid))
    con.commit()
    con.close()


def test_historical_closes_are_derived_from_stored_fills_else_null_with_a_note(env: dict[str, Any]) -> None:
    store = fbs.get_store()
    s1 = store.book(name="a", symbol="NIFTY", legs=[_leg(100.0)], source="t")
    s2 = store.book(name="b", symbol="NIFTY", legs=[_leg(50.0)], source="t")
    p1, p2 = s1["positions"][0]["id"], s2["positions"][0]["id"]
    store.close([{"position_id": p1, "exit_price": 110.0, "exit_price_source": "t", "exit_costs": 25.0}])
    store.close([{"position_id": p2, "exit_price": 45.0, "exit_price_source": "t"}])
    _strip_realised(fbs.default_db_path())
    day = store.day_summary("2026-11-05")
    by = {t["position_ids"][0]: t for t in day["trades"] if t["action"] == "close"}
    assert by[p1]["realised_inr"] == pytest.approx((110.0 - 100.0) * 65 - 25.0)
    assert by[p1]["realised_source"] == "derived from the stored fills" and day["notes"] == []
    # underivable (the position row is gone): realised null + the "recorded from" note; the derivable trade still counts
    con = sqlite3.connect(str(fbs.default_db_path()))
    con.execute("DELETE FROM paper_fo_positions WHERE id = ?", (p2,))
    con.commit()
    con.close()
    day2 = store.day_summary("2026-11-05")
    by2 = {t["position_ids"][0]: t for t in day2["trades"] if t["action"] == "close"}
    assert by2[p2]["realised_inr"] is None and by2[p1]["realised_inr"] is not None
    assert any(fbs.REALISED_RECORDED_FROM in n for n in day2["notes"])
    assert day2["realised_inr"] == by2[p1]["realised_inr"]            # the unknown event is excluded, not guessed


def test_legacy_duplicate_journal_rows_count_as_one_event(env: dict[str, Any]) -> None:
    store = fbs.get_store()
    s = store.book(name="a", symbol="NIFTY", legs=[_leg(100.0)], source="t")
    pid = s["positions"][0]["id"]
    store.close([{"position_id": pid, "exit_price": 90.0, "exit_price_source": "t"}])
    con = sqlite3.connect(str(fbs.default_db_path()))                  # the pre-fix shape: one close journalled twice
    ts, action, sid, payload = con.execute(
        "SELECT ts, action, structure_id, payload FROM paper_fo_journal WHERE action = 'close'").fetchone()
    con.execute("INSERT INTO paper_fo_journal(ts, action, structure_id, payload) VALUES (?, ?, ?, ?)",
                (ts, action, sid, payload))
    con.commit()
    con.close()
    day = store.day_summary("2026-11-05")
    assert day["closes"] == 1 and day["loss_streak"] == 1
    assert day["realised_inr"] == pytest.approx((90.0 - 100.0) * 65)   # counted once, not twice


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# M1: day scoping at IST midnight, loss streak, MTM change
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def test_day_scoping_across_ist_midnight(env: dict[str, Any]) -> None:
    assert fbs.ist_day("2026-11-12T23:59:00+05:30") == "2026-11-12"
    assert fbs.ist_day("2026-11-12T23:59:00") == "2026-11-12"          # naive = IST (the store's own stamps)
    assert fbs.ist_day("2026-11-12T19:00:00+00:00") == "2026-11-13"    # 00:30 IST: the NEXT session date
    assert fbs.ist_day("2026-11-12T18:29:59+00:00") == "2026-11-12"    # 23:59:59 IST: still the 12th
    assert fbs.ist_day("not a time") is None and fbs.ist_day(None) is None
    store = fbs.get_store()
    s = store.book(name="a", symbol="NIFTY", legs=[_leg(100.0), _leg(100.0)], source="t")
    p1, p2 = (p["id"] for p in s["positions"])
    env["now"] = datetime(2026, 11, 12, 23, 59, tzinfo=IST)
    store.close([{"position_id": p1, "exit_price": 90.0, "exit_price_source": "t"}])
    env["now"] = datetime(2026, 11, 12, 19, 0, tzinfo=timezone.utc)    # a UTC journal stamp: 13 Nov 00:30 IST
    store.close([{"position_id": p2, "exit_price": 90.0, "exit_price_source": "t"}])
    d12, d13 = store.day_summary("2026-11-12"), store.day_summary("2026-11-13")
    assert d12["closes"] == 1 and d12["trades"][-1]["position_ids"] == [p1]
    assert d13["closes"] == 1 and d13["trades"][-1]["position_ids"] == [p2]
    assert d13["loss_streak"] == 2 and d12["loss_streak"] == 1         # the streak is as of the END of the asked day


def test_loss_streak_counts_closes_only_chronological(env: dict[str, Any]) -> None:
    store = fbs.get_store()
    env["now"] = datetime(2026, 11, 10, 15, 0, tzinfo=IST)             # day 0: book five single-leg structures
    ids = [store.book(name=f"s{i}", symbol="NIFTY", legs=[_leg(100.0)], source="t")["positions"][0]["id"] for i in range(5)]
    env["now"] = datetime(2026, 11, 11, 10, 0, tzinfo=IST)             # day 1, chronological:
    store.close([{"position_id": ids[0], "exit_price": 90.0, "exit_price_source": "t"}])          # loss → 1
    store.close([{"position_id": ids[1], "exit_price": 95.0, "exit_price_source": "t"}])          # loss → 2
    store.close([{"position_id": ids[2], "exit_price": 150.0, "exit_price_source": "t"}])         # non-negative → 0
    store.close([{"position_id": ids[3], "exit_price": 80.0, "exit_price_source": "t"}])          # loss → 1
    rolled = store.roll([{"position_id": ids[4], "exit_price": 150.0, "exit_price_source": "t"}],
                        [_leg(30.0, expiry="2026-11-17")])             # a GAIN realised by a roll: never a close event
    new_id = rolled["opened"][0]["id"]
    store.close([{"position_id": new_id, "exit_price": 10.0, "exit_price_source": "t"}])          # loss → 2
    d0, d1 = store.day_summary("2026-11-10"), store.day_summary("2026-11-11")
    assert d0["bookings"] == 5 and d0["closes"] == 0 and d0["loss_streak"] == 0
    assert d1["closes"] == 5 and d1["rolls"] == 1
    # 2 proves BOTH facts: the winning close reset the first streak of 2, and the gaining roll did NOT reset the
    # later one (counted as a close it would have ended at 1; never resetting it would have ended at 3)
    assert d1["loss_streak"] == 2
    assert [t["action"] for t in d1["trades"]] == ["close", "close", "close", "close", "roll", "close"]
    roll_trade = d1["trades"][4]
    assert roll_trade["realised_inr"] == pytest.approx((150.0 - 100.0) * 65)
    assert d1["realised_inr"] == pytest.approx(((90 - 100) + (95 - 100) + (150 - 100) + (80 - 100) + (150 - 100) + (10 - 30)) * 65)
    assert d1["realised_gross_inr"] == d1["realised_inr"] and d1["costs_inr"] == 0.0    # costless fixture legs


def test_mtm_change_reads_the_stored_marks_against_the_prior_eod(env: dict[str, Any]) -> None:
    store = fbs.get_store()
    env["now"] = datetime(2026, 11, 10, 15, 0, tzinfo=IST)
    s = store.book(name="a", symbol="NIFTY", legs=[_leg(100.0), _leg(100.0)], source="t")
    p1, p2 = (p["id"] for p in s["positions"])
    store.add_marks([{"position_id": p1, "kind": "eod", "as_of": "2026-11-10T15:30:00+05:30", "price": 120.0, "price_source": "t"},
                     {"position_id": p1, "kind": "session", "as_of": "2026-11-11T10:00:00+05:30", "price": 130.0, "price_source": "t"}])
    d0 = store.day_summary("2026-11-10")
    assert d0["mtm_change_inr"] == pytest.approx((120.0 - 100.0) * 65)   # no prior EOD mark: entry is the baseline
    assert d0["mtm_positions"] == 1 and d0["mtm_unmarked"] == [p2]
    d1 = store.day_summary("2026-11-11")
    assert d1["mtm_change_inr"] == pytest.approx((130.0 - 120.0) * 65)   # against the prior session's EOD mark
    # a revised prior close (the 22:05 re-publication) moves the baseline: the latest revision wins
    store.add_marks([{"position_id": p1, "kind": "eod", "as_of": "2026-11-10T15:30:00+05:30", "price": 125.0, "price_source": "t"}])
    assert store.day_summary("2026-11-11")["mtm_change_inr"] == pytest.approx((130.0 - 125.0) * 65)
    # a position opened after the asked day never counts
    env["now"] = datetime(2026, 11, 12, 10, 0, tzinfo=IST)
    store.book(name="later", symbol="NIFTY", legs=[_leg(10.0)], source="t")
    assert store.day_summary("2026-11-11")["mtm_change_inr"] == pytest.approx((130.0 - 125.0) * 65)


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# the route: GET /api/options/book/day
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def test_day_endpoint_shape_defaults_and_paper_only(env: dict[str, Any]) -> None:
    c = env["client"]
    r = c.get("/api/options/book/day")
    assert r.status_code == 200
    d = r.json()
    assert d["date"] == "2026-11-05"                                   # default: today IST (the patched clock)
    for k in ("date", "realised_inr", "mtm_change_inr", "bookings", "closes", "loss_streak", "trades"):
        assert k in d, k
    assert d["realised_inr"] == 0.0 and d["loss_streak"] == 0 and d["trades"] == []
    assert d["paper_only"] is True and d["badge"] == "arithmetic" and "PAPER ONLY" in d["note"]
    assert not fbs.default_db_path().exists()                          # an empty read creates no file
    assert c.get("/api/options/book/day", params={"date": "not-a-date"}).status_code == 422
    s = _book(c)
    ce = s["positions"][0]["id"]
    done = c.post("/api/options/book/close", json={"position_ids": [ce], "prices": {str(ce): 200.0}}).json()
    d2 = c.get("/api/options/book/day").json()
    assert d2["bookings"] == 1 and d2["closes"] == 1
    assert d2["realised_inr"] == pytest.approx(done["fills"][0]["pnl"]["net"], abs=0.02)
    # today's open marks were freshened before aggregating: the PE leg carries an EOD mark dated today
    assert d2["mtm_positions"] == 1 and d2["mtm_change_inr"] == pytest.approx((160.40 - 160.40) * 65)
    assert d2["mark_source"] is not None and d2["marks_meta"]["used"] == "eod"
    # a historical date aggregates the stored rows only (no mark freshening meta)
    d3 = c.get("/api/options/book/day", params={"date": "2026-11-04"}).json()
    assert d3["date"] == "2026-11-04" and d3["bookings"] == 0 and d3["closes"] == 0 and d3["marks_meta"] is None


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# M2: /api/risk/fo scenarios carry ±1 % and the theta row; the existing table is intact
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def test_risk_scenarios_carry_plus_minus_one_percent_and_theta(env: dict[str, Any]) -> None:
    c = env["client"]
    _book(c)
    b = c.get("/api/risk/fo", params={"margin": "false"}).json()
    sc = b["scenarios"]
    gaps = {s["spot_pct"] for s in sc["gap"]}
    assert {-1.0, 1.0} <= gaps and gaps == set(fo_book.GAPS)
    assert sc["theta"] == [{"days_fwd": 1, "pnl_inr": sc["theta_1d_inr"]}]
    assert sc["theta_1d_inr"] < 0                                      # a long straddle pays theta
    by_gap = {s["spot_pct"]: s["pnl_inr"] for s in sc["gap"]}
    assert 0 <= by_gap[1.0] < by_gap[5.0] and 0 <= by_gap[-1.0] < by_gap[-5.0]   # long gamma: instant gaps gain, convex
    # the existing table's keys are untouched (RSK › F&O renders gap / iv_shock / combined / theta_1d_inr)
    assert set(sc) >= {"gap", "iv_shock", "combined", "theta", "theta_1d_inr", "badge", "note"}
    assert b["paper_only"] is True
