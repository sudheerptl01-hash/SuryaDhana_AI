"""W7 fixes beyond the bulk cache (bloomberg_verdict.md D5/D7/D8).

- D7a: unknown-ticker OHLCV proxy → clean 404 `not_found`, no internal URL on the wire.
- D7b: lw screener `days<1` → 422 `invalid` (was a FALSE 404 "No OHLCV data in DuckDB").
- D8:  RequestValidationError handler → the one error envelope everywhere.
- D5/S6: `fields=core` trims on the four >150 KB market payloads; defaults byte-identical.
"""
import json
import sys
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from errors import validation_error_handler, validation_message  # noqa: E402
from routers import lw_scanner, markets, stocks  # noqa: E402


def _mirror_app(*routers_with_prefix) -> FastAPI:
    """main.py's handler wiring on a bare app (same pattern as test_errors_contract.py),
    PLUS the W7 RequestValidationError handler main.py gains via the patch block."""
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from errors import code_for_status, error_block

    app = FastAPI()

    @app.exception_handler(StarletteHTTPException)
    async def handler(request, exc):
        d = exc.detail
        if isinstance(d, dict) and "code" in d and "message" in d:
            block = error_block(d["code"], str(d["message"]), d.get("hint"))
            message = str(d["message"])
        else:
            message = d if isinstance(d, str) else str(d)
            block = error_block(code_for_status(exc.status_code), message)
        return JSONResponse({"detail": message, "error": block}, status_code=exc.status_code,
                            headers=getattr(exc, "headers", None))

    app.add_exception_handler(RequestValidationError, validation_error_handler)
    for router, prefix in routers_with_prefix:
        app.include_router(router, prefix=prefix)
    return app


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient (same pattern as test_quotes.py); serves canned responses."""
    responses: dict[str, httpx.Response] = {}

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kw):
        for frag, resp in self.responses.items():
            if frag in url:
                return resp
        raise AssertionError(f"unexpected upstream GET {url}")


# ── D7a: unknown-ticker OHLCV ────────────────────────────────────────────────────────────

def test_unknown_ticker_ohlcv_is_a_clean_404(monkeypatch):
    _FakeAsyncClient.responses = {"/ohlcv/ZZZ": httpx.Response(
        404, json={"detail": "ZZZ not found"}, request=httpx.Request("GET", "http://localhost:8001/ohlcv/ZZZ"))}
    monkeypatch.setattr(stocks.httpx, "AsyncClient", _FakeAsyncClient)
    c = TestClient(_mirror_app((stocks.router, "/api/stocks")))
    r = c.get("/api/stocks/ZZZ/ohlcv?days=5")
    assert r.status_code == 404
    body = r.json()
    assert body["detail"] == "No OHLCV data for ZZZ"
    assert body["error"]["code"] == "not_found" and "hint" in body["error"]
    wire = json.dumps(body)
    assert "localhost" not in wire and "8001" not in wire and "mozilla" not in wire


def test_upstream_500_stays_502_without_internal_url(monkeypatch):
    _FakeAsyncClient.responses = {"/ohlcv/TCS": httpx.Response(
        500, text="boom", request=httpx.Request("GET", "http://localhost:8001/ohlcv/TCS"))}
    monkeypatch.setattr(stocks.httpx, "AsyncClient", _FakeAsyncClient)
    c = TestClient(_mirror_app((stocks.router, "/api/stocks")))
    r = c.get("/api/stocks/TCS/ohlcv?days=5")
    assert r.status_code == 502
    body = r.json()
    assert body["error"]["code"] == "upstream_down"
    assert "localhost" not in json.dumps(body) and "8001" not in json.dumps(body)


# ── D7b: lw screener days validation ─────────────────────────────────────────────────────

def test_lw_screener_negative_days_is_422_invalid_not_false_404():
    c = TestClient(_mirror_app((lw_scanner.router, "/api/lw")))
    r = c.get("/api/lw/screener?days=-3")
    assert r.status_code == 422
    body = r.json()
    assert body["error"]["code"] == "invalid"
    assert "days must be >= 1" in body["detail"]
    assert "No OHLCV data" not in body["detail"]  # the old false message


# ── D8: one 422 envelope ─────────────────────────────────────────────────────────────────

def test_request_validation_422_carries_the_envelope():
    from fastapi import Query

    app = _mirror_app()

    @app.get("/probe")
    async def probe(days: int = Query(5, ge=1)):
        return {"days": days}

    c = TestClient(app)
    r = c.get("/probe?days=-10")
    assert r.status_code == 422
    body = r.json()
    assert isinstance(body["detail"], str) and "days" in body["detail"]
    assert body["error"]["code"] == "invalid" and body["error"]["message"] == body["detail"]
    assert isinstance(body["errors"], list) and body["errors"]  # raw items kept for debuggers


def test_validation_message_is_compact():
    errs = [{"loc": ("query", "days"), "msg": "Input should be greater than or equal to 1"},
            {"loc": ("query", "x"), "msg": "field required"},
            {"loc": ("body",), "msg": "value error"},
            {"loc": ("query", "y"), "msg": "bad"}]
    m = validation_message(errs)
    assert m.startswith("days: Input should be greater")
    assert "(+1 more)" in m


# ── D5/S6: fields=core trims ─────────────────────────────────────────────────────────────

_EVENT_ROW = {"symbol": "TCS", "event_date": "2026-10-20", "kind": "RESULTS", "source": "calendar",
              "tags": "RESULTS", "company": "Tata Consultancy", "purpose": "Quarterly results",
              "detail": "Quarterly results", "record_date": None, "announced_at": "2026-10-01",
              "url": "https://nseindia.com/x", "first_seen": "2026-10-01 09:00", "turnover_cr": 120.5,
              "close": 3500.0}


def test_events_core_rows_drop_unread_and_dedupe_purpose():
    rows = markets.events_core_rows([dict(_EVENT_ROW), dict(_EVENT_ROW, purpose="To consider a dividend")])
    for r in rows:
        assert not {"sources", "announced_at", "first_seen"} & set(r)
    assert rows[0]["purpose"] is None and rows[0]["detail"] == "Quarterly results"  # dup → null (client restores)
    assert rows[1]["purpose"] == "To consider a dividend"                           # distinct → kept


def test_columnar_round_trips_rows():
    rows = [{"a": 1, "b": "x"}, {"a": 2, "b": None, "c": 3.0}]
    out = markets.columnar(rows)
    assert out["columns"] == ["a", "b", "c"]
    assert out["data"] == [[1, "x", None], [2, None, 3.0]]


def test_mtf_core_rounds_and_columnarises_stocks_only():
    body = {"as_of": "2026-10-14", "market": [{"date": "2026-10-13", "end_lakh": 1.23}],
            "stocks": [{"symbol": "HDFCBANK", "name": "HDFC BANK", "amount_cr": 3130.4177,
                        "qty_chg_pct": -18.885904778319485, "days_to_unwind": 1.382817919967609, "close": 704.9}]}
    out = markets.mtf_core(body)
    assert out["market"] == body["market"]                       # small block untouched
    assert out["stocks"]["columns"][0] == "symbol"
    row = dict(zip(out["stocks"]["columns"], out["stocks"]["data"][0]))
    assert row["qty_chg_pct"] == -18.89 and row["days_to_unwind"] == 1.38 and row["amount_cr"] == 3130.42


def _markets_client(monkeypatch, responses: dict[str, httpx.Response]) -> TestClient:
    _FakeAsyncClient.responses = responses
    monkeypatch.setattr(markets.httpx, "AsyncClient", _FakeAsyncClient)
    return TestClient(_mirror_app((markets.router, "/api/market")))


def test_events_default_shape_unchanged_and_core_is_columnar(monkeypatch):
    upstream = httpx.Response(200, json={"start": "2026-10-01", "end": "2026-11-01",
                                         "rows": [dict(_EVENT_ROW)], "refreshing": False},
                              request=httpx.Request("GET", "http://x"))
    c = _markets_client(monkeypatch, {"/db/events": upstream})
    full = c.get("/api/market/events").json()
    assert isinstance(full["rows"], list) and full["count"] == 1
    assert full["rows"][0]["sources"] == ["calendar"]            # merge_events adds it; default keeps it
    assert full["rows"][0]["purpose"] == "Quarterly results"     # default: no dedupe, byte-identical shape
    core = c.get("/api/market/events?fields=core").json()
    assert "rows" not in core and core["count"] == 1
    row = dict(zip(core["columns"], core["data"][0]))
    assert row["purpose"] is None and row["detail"] == "Quarterly results"
    assert "sources" not in core["columns"] and "announced_at" not in core["columns"]
    assert c.get("/api/market/events?fields=junk").status_code == 422   # fail loud, never a silent 528 KB


def test_announcements_core_items_carry_three_fields_only(monkeypatch):
    item = {"symbol": "INFY", "company": "Infosys", "time": "2026-10-14 18:02", "subject": "Results",
            "text": "x" * 900, "pdf": "https://nse/x.pdf", "category": "results", "seq": "1"}
    upstream = httpx.Response(200, json={"date": "2026-10-14", "items": [item], "counts": {"results": 1},
                                         "market_open": False}, request=httpx.Request("GET", "http://x"))
    c = _markets_client(monkeypatch, {"/db/announcements": upstream})
    full = c.get("/api/market/announcements").json()
    assert full["items"][0]["text"].endswith("…") and len(full["items"][0]["text"]) == 401  # default trim as before
    assert full["items"][0]["pdf"] == "https://nse/x.pdf"
    core = c.get("/api/market/announcements?fields=core").json()
    assert core["items"] == [{"symbol": "INFY", "time": "2026-10-14 18:02", "category": "results"}]
    assert core["counts"] == {"results": 1} and core["date"] == "2026-10-14"


def test_fundamentals_screen_core_is_columnar_with_all_fields(monkeypatch):
    row = {"symbol": "20MICRONS", "industry": None, "period_end": "2026-06-30",
           "filed_at": "2026-07-31T16:04:16", "revenue": 2447203000.0, "pat": 177440000.0,
           "revenue_yoy": -1.0, "pat_yoy": 5.2, "pe": 10.3456}
    upstream = httpx.Response(200, json={"rows": [row]}, request=httpx.Request("GET", "http://x"))
    c = _markets_client(monkeypatch, {"/db/financials-universe": upstream})
    full = c.get("/api/market/fundamentals-screen").json()
    assert full["rows"][0]["pe"] == 10.35                        # existing default 2 dp rounding intact
    core = c.get("/api/market/fundamentals-screen?fields=core").json()
    assert set(core["columns"]) == set(row)                      # core drops NO fields here — keys only
    got = dict(zip(core["columns"], core["data"][0]))
    assert got["revenue"] == 2447203000.0 and got["filed_at"] == "2026-07-31T16:04:16" and got["pe"] == 10.35


def test_events_cut_keeps_upcoming_events_not_the_past_week():
    """5 Nov 2026: 1,737 rows from 29 Oct; the old `rows[:500]` kept 29 Oct – 3 Nov and EVTS read '0 upcoming'."""
    from datetime import date as _date

    from routers import markets as m

    rows = [{"symbol": f"S{i}", "event_date": f"2026-10-{29 + i // 100:02d}" if i < 300 else f"2026-11-{5 + (i - 300) // 100:02d}",
             "kind": "results"} for i in range(1200)]
    kept = m.keep_nearest_events(rows, 500, _date(2026, 11, 5))
    days = [r["event_date"] for r in kept]
    assert len(kept) == 500 and days == sorted(days)
    assert sum(d >= "2026-11-05" for d in days) == 500                       # 900 upcoming rows: the nearest 500 win
    assert days[0] == "2026-11-05" and days[-1] == "2026-11-09"
    few = rows[:300] + rows[300:400]                                          # 100 upcoming, 300 past
    kept2 = m.keep_nearest_events(few, 250, _date(2026, 11, 5))
    assert sum(r["event_date"] >= "2026-11-05" for r in kept2) == 100         # every upcoming row kept …
    assert min(r["event_date"] for r in kept2) == "2026-10-30"                # … then the MOST RECENT past rows
    assert m.keep_nearest_events(rows[:10], 500, _date(2026, 11, 5)) == rows[:10]   # under the limit: untouched
