"""FINAL ROUND wave E, E-JRNL (F-12): journal context captured point-in-time on book / close, and the weekly
debrief read (``GET /api/options/book/debrief``) — the realised money split Θ/Δ/ν + residual (labelled
arithmetic · approximation with its method), the shape-template tally, per-day facts. No composite score exists.

Same conventions as test_fo_book_day.py: temp SQLite (PAPER_FO_DB), chain fixtures shaped like data-service's
payload, data-service never reached (get_json is patched: the IV summary read is served from a fixture the test can
mutate, proving the journalled context is the recorded fact, not a re-read), both clocks patched.
"""
from __future__ import annotations

import sys
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fo_book_store as fbs  # noqa: E402
import options_math as om  # noqa: E402
from routers import fo_book  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
EVENING = datetime(2026, 11, 5, 21, 0, tzinfo=IST)

SUMMARY_ROW = {"date": "2026-11-05", "spot": 24536.75, "iv30_cm": 15.42, "iv_pctile_252": 61.9,
               "iv_rank_252": 57.3, "iv_minus_rv20": 2.1}


def chain_fixture(expiry: str = "2026-11-09", *, day: str = "2026-11-05", forward: float = 24545.75,
                  iv: float = 15.45, days: float = 4.0) -> dict[str, Any]:
    rows = []
    for k in range(24300, 24801, 50):
        t = om.t_years(days)
        ce = round(om.black76("CE", forward, k, t, iv / 100).price, 2)
        pe = round(om.black76("PE", forward, k, t, iv / 100).price, 2)
        rows.append({"strike": float(k), "ce": {"price": ce, "iv": iv}, "pe": {"price": pe, "iv": iv}})
    return {"symbol": "NIFTY", "found": True, "date": day, "expiry": expiry, "expiries": [expiry, "2026-11-17"],
            "t_days": round(days, 4), "spot": forward - 9.0, "future": 24588.0, "forward": forward,
            "atm": 24550.0, "lot": 65, "atm_iv": iv, "rows": rows}


STRADDLE = [{"side": "buy", "kind": "CE", "strike": 24550, "expiry": "2026-11-09", "premium": 156.15, "iv": 15.45,
             "lots": 1, "lot_size": 65, "forward": 24545.75, "price_source": "NSE F&O bhavcopy 2026-11-05"},
            {"side": "buy", "kind": "PE", "strike": 24550, "expiry": "2026-11-09", "premium": 160.40, "iv": 15.45,
             "lots": 1, "lot_size": 65, "forward": 24545.75, "price_source": "NSE F&O bhavcopy 2026-11-05"}]
VERTICAL = [{"side": "buy", "kind": "CE", "strike": 24500, "expiry": "2026-11-09", "premium": 180.0, "iv": 15.45,
             "lots": 1, "lot_size": 65, "forward": 24545.75, "price_source": "fixture"},
            {"side": "sell", "kind": "CE", "strike": 24600, "expiry": "2026-11-09", "premium": 130.0, "iv": 15.45,
             "lots": 1, "lot_size": 65, "forward": 24545.75, "price_source": "fixture"}]
CHECKLIST = {"session": "2026-11-05", "symbol": "NIFTY", "ticked": 3, "total": 4,
             "items": {"event": True, "iv": True, "max_loss": True, "margin": False},
             "max_loss_inr": 8000, "note": "checklist: 3/4", "iv30_cm": 15.42, "iv_pctile_252": 61.9,
             "event_hint": None, "margin_total": 87381.0, "margin_source": "BREEZE"}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[dict[str, Any]]:
    monkeypatch.setenv(fbs.ENV_DB, str(tmp_path / "paper_fo.sqlite"))
    for c in (fo_book._chain_cache, fo_book._margin_cache, fo_book._history_cache):
        c.clear()
    state: dict[str, Any] = {"now": EVENING, "summary_rows": [dict(SUMMARY_ROW)], "summary_calls": 0}

    async def fake_chain(symbol: str, expiry: str, live: bool) -> dict[str, Any]:
        return chain_fixture(expiry if expiry == "2026-11-09" else "2026-11-17")

    async def fake_get_json(url: str, **kw: Any) -> Any:
        if "/db/iv/summary" in url:
            state["summary_calls"] += 1
            if state.get("summary_down"):
                raise fo_book.UpstreamError(503, "iv summary offline (fixture)")
            return {"rows": [dict(r) for r in state["summary_rows"]]}
        raise fo_book.UpstreamError(503, "tests never reach data-service")

    monkeypatch.setattr(fo_book, "fetch_chain", fake_chain)
    monkeypatch.setattr(fo_book, "get_json", fake_get_json)
    monkeypatch.setattr(fo_book, "now_ist", lambda: state["now"])
    monkeypatch.setattr(fbs, "now_ist", lambda: state["now"].isoformat(timespec="seconds"))
    app = FastAPI()
    app.include_router(fo_book.router, prefix="/api/options/book")
    state["client"] = TestClient(app)
    yield state


def _book(c: TestClient, legs: list[dict[str, Any]] = STRADDLE, name: str = "straddle", **kw: Any) -> dict[str, Any]:
    r = c.post("/api/options/book", json={"symbol": "NIFTY", "name": name, "legs": legs, **kw})
    assert r.status_code == 200, r.text
    return r.json()["structure"]


def _journal_rows(action: str) -> list[dict[str, Any]]:
    return [j for j in fbs.get_store().journal(limit=200) if j["action"] == action]


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# context capture: point-in-time on book and close, best-effort, never blocking
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def test_booking_journals_point_in_time_context(env: dict[str, Any]) -> None:
    c = env["client"]
    _book(c, context=CHECKLIST)
    (row,) = _journal_rows("book")
    ctx = row["payload"]["context"]
    assert ctx["client"]["max_loss_inr"] == 8000 and ctx["client"]["margin_source"] == "BREEZE"
    m = ctx["market"]
    assert m["symbol"] == "NIFTY" and m["captured_at"].startswith("2026-11-05T21:00")
    assert m["iv"] == {**SUMMARY_ROW, "source": "iv_summary_daily (EOD store)"}
    assert m["nearest_expiry"] == "2026-11-09"
    # DTE: 2026-11-05 21:00 → 2026-11-09 15:30 IST = 3 days 18.5 h
    assert m["dte_days"] == pytest.approx(3.771, abs=0.01)
    # the stored snapshot is the fact: a later change in the summary store never rewrites it
    env["summary_rows"] = [{**SUMMARY_ROW, "date": "2026-11-06", "iv30_cm": 99.9}]
    (row2,) = _journal_rows("book")
    assert row2["payload"]["context"]["market"]["iv"]["iv30_cm"] == SUMMARY_ROW["iv30_cm"]


def test_close_journals_market_context_and_a_failed_read_never_blocks(env: dict[str, Any]) -> None:
    c = env["client"]
    s = _book(c)
    ids = [p["id"] for p in s["positions"]]
    env["summary_down"] = True                                  # the IV store is down at the close
    r = c.post("/api/options/book/close", json={"position_ids": ids, "prices": {str(i): 150.0 for i in ids}})
    assert r.status_code == 200, r.text                         # the action is never blocked by a context read
    (row,) = _journal_rows("close")
    m = row["payload"]["context"]["market"]                     # the same {"market": …} shape a booking journals
    assert m["symbol"] == "NIFTY" and "unavailable at capture" in m["note"] and "iv" not in m
    assert m["dte_days"] is not None                            # arithmetic needs no upstream


def test_booking_with_no_summary_row_notes_it(env: dict[str, Any]) -> None:
    env["summary_rows"] = []
    _book(env["client"])
    (row,) = _journal_rows("book")
    m = row["payload"]["context"]["market"]
    assert "no IV summary stored" in m["note"] and "client" not in row["payload"]["context"]


def test_oversized_client_context_is_refused(env: dict[str, Any]) -> None:
    r = env["client"].post("/api/options/book",
                           json={"symbol": "NIFTY", "legs": STRADDLE, "context": {"blob": "x" * 7000}})
    assert r.status_code == 422 and "context over" in r.text


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# the weekly debrief: Θ/Δ/ν split sums to the gross exactly; templates; days; facts only
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════


def test_debrief_attribution_sums_to_gross_and_classifies_templates(env: dict[str, Any]) -> None:
    c = env["client"]
    s1 = _book(c, STRADDLE, name="straddle")
    s2 = _book(c, VERTICAL, name="vertical")
    env["now"] = datetime(2026, 11, 6, 21, 0, tzinfo=IST)       # closed the next evening
    for s, px in ((s1, 170.0), (s2, 140.0)):
        ids = [p["id"] for p in s["positions"]]
        r = c.post("/api/options/book/close", json={"position_ids": ids, "prices": {str(i): px for i in ids}})
        assert r.status_code == 200, r.text
    r = c.get("/api/options/book/debrief", params={"from": "2026-11-01", "to": "2026-11-08"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["paper_only"] is True and body["attribution_label"] == "arithmetic · approximation"
    assert "first-order at the entry Greeks" in body["attribution_method"]
    by_name = {x["name"]: x for x in body["structures"]}
    assert by_name["straddle"]["template"] == "straddle" and by_name["vertical"]["template"] == "vertical spread"
    for x in body["structures"]:
        a = x["attribution"]
        assert a["complete"] is True                            # entry IV/forward stored, EOD marks written at close
        parts = a["theta_inr"] + a["delta_inr"] + a["vega_inr"] + a["residual_inr"]
        assert parts == pytest.approx(x["gross_inr"], abs=0.05)  # the residual closes the sum exactly (± rounding)
        assert x["realised_inr"] == pytest.approx(x["gross_inr"] - x["costs_inr"], abs=0.05)
        for leg in a["legs"]:
            lp = sum(leg[k] for k in ("theta_inr", "delta_inr", "vega_inr", "residual_inr") if leg[k] is not None)
            assert lp == pytest.approx(leg["gross_inr"], abs=0.05)
    # template tally: wins = realised net > 0, arithmetic only
    tally = {t["template"]: t for t in body["by_template"]}
    assert tally["straddle"]["n"] == 1 and tally["vertical spread"]["n"] == 1
    for t in tally.values():
        assert t["wins"] in (0, 1) and (t["win_rate_pct"] in (0.0, 100.0))
    # per-day facts for the discipline card (the client compares against the owner's own rules)
    days = {d["date"]: d for d in body["days"]}
    assert days["2026-11-05"]["bookings"] == 2 and days["2026-11-06"]["closes"] == 2
    assert "no composite score" in body["facts_note"]
    assert "score" not in {k for x in body["structures"] for k in x}  # facts only: no scored field per structure


def test_debrief_unassigned_parts_sit_in_the_residual(env: dict[str, Any]) -> None:
    """A leg booked without entry IV / forward cannot be attributed: Θ/Δ/ν are null, the residual is the whole
    gross, complete is False and the notes say why — never a silent guess."""
    store = fbs.get_store()
    s = store.book(name="bare", symbol="NIFTY", legs=[{"side": "buy", "kind": "CE", "strike": 24550.0,
                   "expiry": "2026-11-09", "lots": 1, "lot_size": 65, "entry_price": 100.0,
                   "entry_price_source": "fixture", "entry_costs": 10.0}], source="t")
    pid = s["positions"][0]["id"]
    store.close([{"position_id": pid, "exit_price": 120.0, "exit_price_source": "t", "exit_costs": 5.0}])
    r = env["client"].get("/api/options/book/debrief", params={"from": "2026-11-05", "to": "2026-11-05"})
    (x,) = r.json()["structures"]
    a = x["attribution"]
    assert a["complete"] is False
    (leg,) = a["legs"]
    assert leg["theta_inr"] is None and leg["delta_inr"] is None and leg["vega_inr"] is None
    assert leg["residual_inr"] == pytest.approx((120.0 - 100.0) * 65)
    assert any("unassigned" in n for n in a["notes"])
    assert x["realised_inr"] == pytest.approx((120.0 - 100.0) * 65 - 15.0)


def test_debrief_window_validation_and_defaults(env: dict[str, Any]) -> None:
    c = env["client"]
    assert c.get("/api/options/book/debrief", params={"from": "2026-11-09", "to": "2026-11-01"}).status_code == 422
    assert c.get("/api/options/book/debrief", params={"from": "2026-01-01", "to": "2026-11-01"}).status_code == 422
    assert c.get("/api/options/book/debrief", params={"to": "not-a-date"}).status_code == 422
    r = c.get("/api/options/book/debrief")                      # default: the 7 IST days ending today
    assert r.status_code == 200
    body = r.json()
    assert body["from"] == "2026-10-30" and body["to"] == "2026-11-05"
    assert body["structures"] == [] and body["days"] == []


def test_fut_leg_is_all_delta(env: dict[str, Any]) -> None:
    store = fbs.get_store()
    s = store.book(name="fut", symbol="NIFTY", legs=[{"side": "sell", "kind": "FUT", "strike": None,
                   "expiry": "2026-11-17", "lots": 1, "lot_size": 65, "entry_price": 24588.0,
                   "entry_price_source": "fixture", "entry_costs": 0.0}], source="t")
    store.close([{"position_id": s["positions"][0]["id"], "exit_price": 24500.0, "exit_price_source": "t"}])
    r = env["client"].get("/api/options/book/debrief", params={"from": "2026-11-05", "to": "2026-11-05"})
    (x,) = r.json()["structures"]
    (leg,) = x["attribution"]["legs"]
    assert x["template"] == "futures"
    assert leg["delta_inr"] == pytest.approx((24588.0 - 24500.0) * 65) and leg["theta_inr"] == 0.0
    assert leg["vega_inr"] == 0.0 and leg["residual_inr"] == 0.0 and leg["complete"] is True


def test_iron_condor_template(env: dict[str, Any]) -> None:
    legs = [{"side": side, "kind": kind, "strike": k, "expiry": "2026-11-09", "lots": 1, "lot_size": 65,
             "entry_price": 50.0, "entry_price_source": "fixture", "entry_costs": 0.0}
            for side, kind, k in (("sell", "CE", 24700.0), ("buy", "CE", 24800.0),
                                  ("sell", "PE", 24400.0), ("buy", "PE", 24300.0))]
    assert fo_book.classify_template(legs) == "iron condor"
    legs2 = [dict(leg) for leg in legs]
    legs2[0]["strike"] = legs2[2]["strike"] = 24550.0
    assert fo_book.classify_template(legs2) == "iron butterfly"
    assert fo_book.classify_template([legs[0]]) == "single option"
    assert fo_book.classify_template([legs[0], dict(legs[1], side="sell")]) == "custom"   # two short CEs: no named shape
    assert fo_book.classify_template([legs[0], legs[1]]) == "vertical spread"
