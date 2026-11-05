"""charts.py (W1 — CHRT chart studio): W/M resample exactness, the degraded intraday
path while the W6 tick store is not live, and the one error contract on every failure.

Same mirror pattern as test_errors_contract.py: the real router on a bare app with
main.py's exception handler re-wired, upstream fetches monkeypatched — no live
data-service in CI.
"""
import inspect
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routers import charts  # noqa: E402


def _app() -> FastAPI:
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    from errors import code_for_status, error_block

    app = FastAPI()

    @app.exception_handler(StarletteHTTPException)
    async def handler(request, exc):  # mirror of main.py's contract handler
        d = exc.detail
        if isinstance(d, dict) and "code" in d and "message" in d:
            block = error_block(d["code"], str(d["message"]), d.get("hint"))
            message = str(d["message"])
        else:
            message = d if isinstance(d, str) else str(d)
            block = error_block(code_for_status(exc.status_code), message)
        return JSONResponse({"detail": message, "error": block}, status_code=exc.status_code)

    app.include_router(charts.router, prefix="/api/charts")
    return app


def _client() -> TestClient:
    return TestClient(_app())


def _row(d: str, o: float, h: float, lo: float, c: float, v: int) -> dict:
    return {"ticker": "RELIANCE", "date": d, "open": o, "high": h, "low": lo, "close": c, "volume": v}


# Two ISO trading weeks (the first with a mid-week holiday on 2026-10-07) plus a
# September stub — DELIBERATELY unsorted to prove the resample sorts first.
ROWS = [
    _row("2026-10-08", 108, 109, 101, 102, 1500),
    _row("2026-09-29", 10, 12, 9, 11, 100),
    _row("2026-10-05", 100, 105, 99, 104, 1000),
    _row("2026-10-13", 96, 101, 96, 100, 1200),
    _row("2026-09-30", 11, 13, 10, 12, 200),
    _row("2026-10-06", 104, 110, 103, 108, 2000),
    _row("2026-10-12", 99, 100, 95, 96, 800),
    _row("2026-10-09", 102, 103, 98, 99, 500),
]


def _patch_daily(monkeypatch, rows=ROWS):
    calls: list[tuple[str, str]] = []

    def fake(symbol, start):
        calls.append((symbol, start.isoformat()))
        return rows

    monkeypatch.setattr(charts, "_fetch_daily", fake)
    return calls


# ── daily ────────────────────────────────────────────────────────────────────────

def test_daily_passthrough_is_sorted_and_bar_shaped(monkeypatch):
    _patch_daily(monkeypatch)
    r = _client().get("/api/charts/ohlcv", params={"symbol": "RELIANCE", "tf": "D", "days": 365})
    assert r.status_code == 200
    body = r.json()
    assert body["symbol"] == "RELIANCE" and body["tf"] == "D"
    assert body["rows"] == len(body["bars"]) == 8
    assert [b["t"] for b in body["bars"]] == sorted(b["t"] for b in body["bars"])
    assert body["bars"][0] == {"t": "2026-09-29", "o": 10, "h": 12, "l": 9, "c": 11, "v": 100}
    assert body["as_of"] == "2026-10-13"
    assert body["source"] == "duckdb-eod"


def test_prices_rounded_to_paise(monkeypatch):
    _patch_daily(monkeypatch, [_row("2026-10-01", 1180.0999755859375, 1183.9000244140625,
                                    1160.800048828125, 1167.699951171875, 16771221)])
    bar = _client().get("/api/charts/ohlcv", params={"symbol": "RELIANCE"}).json()["bars"][0]
    assert bar == {"t": "2026-10-01", "o": 1180.1, "h": 1183.9, "l": 1160.8, "c": 1167.7, "v": 16771221}


# ── weekly / monthly resample exactness ──────────────────────────────────────────

def test_weekly_bar_aggregates_the_weeks_ohlcv_exactly(monkeypatch):
    """The W bar = first open, max high, min low, last close, summed volume of the
    week's TRADING days, labelled with the week's last trading day."""
    _patch_daily(monkeypatch)
    bars = _client().get("/api/charts/ohlcv", params={"symbol": "RELIANCE", "tf": "W"}).json()["bars"]
    assert [b["t"] for b in bars] == ["2026-09-30", "2026-10-09", "2026-10-13"]
    # week Mon 05 – Fri 09 Oct, Wed 07 Oct a holiday (absent): aggregates span only traded days
    assert bars[1] == {"t": "2026-10-09", "o": 100, "h": 110, "l": 98, "c": 99, "v": 5000}
    # a part-week (Mon–Tue so far) still forms a bar labelled by its last trading day
    assert bars[2] == {"t": "2026-10-13", "o": 99, "h": 101, "l": 95, "c": 100, "v": 2000}


def test_monthly_bar_aggregates_the_month_exactly(monkeypatch):
    _patch_daily(monkeypatch)
    bars = _client().get("/api/charts/ohlcv", params={"symbol": "RELIANCE", "tf": "M"}).json()["bars"]
    assert [b["t"] for b in bars] == ["2026-09-30", "2026-10-13"]
    assert bars[0] == {"t": "2026-09-30", "o": 10, "h": 13, "l": 9, "c": 12, "v": 300}
    assert bars[1] == {"t": "2026-10-13", "o": 100, "h": 110, "l": 95, "c": 100, "v": 7000}


def test_days_window_is_clamped(monkeypatch):
    calls = _patch_daily(monkeypatch)
    assert _client().get("/api/charts/ohlcv", params={"days": 999999}).json()["days"] == 7320
    assert _client().get("/api/charts/ohlcv", params={"days": 1}).json()["days"] == 10
    assert len(calls) == 2  # both reached the (patched) upstream with a clamped start


# ── error contract ───────────────────────────────────────────────────────────────

def test_unknown_tf_is_invalid_with_envelope(monkeypatch):
    _patch_daily(monkeypatch)
    r = _client().get("/api/charts/ohlcv", params={"tf": "H"})
    assert r.status_code == 400
    body = r.json()
    assert isinstance(body["detail"], str) and "tf must be" in body["detail"]
    assert body["error"]["code"] == "invalid"


def test_unknown_symbol_is_404_not_found(monkeypatch):
    def gone(symbol, start):
        raise charts.UpstreamError(404, f"No OHLCV data for {symbol}")

    monkeypatch.setattr(charts, "_fetch_daily", gone)
    r = _client().get("/api/charts/ohlcv", params={"symbol": "ZZZTOP"})
    assert r.status_code == 404
    body = r.json()
    assert body["detail"] == "No OHLCV data for ZZZTOP"
    assert body["error"]["code"] == "not_found" and body["error"].get("hint")


def test_data_service_down_is_502_upstream_down(monkeypatch):
    def down(symbol, start):
        raise charts.UpstreamError(None, "data-service unreachable: ConnectError")

    monkeypatch.setattr(charts, "_fetch_daily", down)
    r = _client().get("/api/charts/ohlcv")
    assert r.status_code == 502
    assert r.json()["error"]["code"] == "upstream_down"


def test_symbol_is_normalised_and_garbage_rejected(monkeypatch):
    calls = _patch_daily(monkeypatch)
    assert _client().get("/api/charts/ohlcv", params={"symbol": "reliance.ns"}).json()["symbol"] == "RELIANCE"
    assert calls[0][0] == "RELIANCE"
    r = _client().get("/api/charts/ohlcv", params={"symbol": "RELIANCE; DROP TABLE"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "invalid"


# ── intraday: W6 tick-store contract + the degraded path ─────────────────────────

def test_intraday_degrades_to_200_while_tick_store_not_live(monkeypatch):
    """data-service has no /ticks/bars yet (404): a usable 200 with bars=[] and the
    honest note, per the errors.degraded contract — never a red error state."""
    def not_integrated(symbol, day, interval):
        raise charts.UpstreamError(404, "Not Found")

    monkeypatch.setattr(charts, "_fetch_ticks", not_integrated)
    r = _client().get("/api/charts/intraday", params={"symbol": "RELIANCE", "date": "2026-10-14", "interval": "1m"})
    assert r.status_code == 200
    body = r.json()
    assert body["bars"] == [] and body["vwap"] is None
    assert body["note"] == "tick store not live"
    assert body["ok"] is False
    assert body["error_info"]["code"] == "degraded"
    assert body["symbol"] == "RELIANCE" and body["date"] == "2026-10-14" and body["interval"] == "1m"


def test_intraday_unreachable_data_service_degrades_not_500(monkeypatch):
    def down(symbol, day, interval):
        raise charts.UpstreamError(None, "data-service unreachable: ConnectError")

    monkeypatch.setattr(charts, "_fetch_ticks", down)
    body = _client().get("/api/charts/intraday", params={"date": "2026-10-14"}).json()
    assert body["bars"] == [] and body["ok"] is False
    assert body["error_info"]["code"] == "upstream_down"


def test_intraday_passes_live_bars_through_unchanged(monkeypatch):
    upstream = {
        "symbol": "RELIANCE", "date": "2026-10-15", "interval": "5m",
        "bars": [{"t": "09:15", "o": 1180.0, "h": 1181.5, "l": 1179.2, "c": 1181.0, "v": 52000},
                 {"t": "09:20", "o": 1181.0, "h": 1183.0, "l": 1180.6, "c": 1182.4, "v": 31000}],
        "vwap": 1181.22, "source": "icici-ws",
    }
    monkeypatch.setattr(charts, "_fetch_ticks", lambda s, d, i: dict(upstream))
    r = _client().get("/api/charts/intraday", params={"symbol": "RELIANCE", "date": "2026-10-15", "interval": "5m"})
    assert r.status_code == 200
    body = r.json()
    assert body["bars"] == upstream["bars"]
    assert body["vwap"] == 1181.22 and body["source"] == "icici-ws"
    assert "error_info" not in body and "note" not in body


def test_intraday_live_but_empty_session_notes_it(monkeypatch):
    monkeypatch.setattr(charts, "_fetch_ticks",
                        lambda s, d, i: {"symbol": s, "date": d, "interval": i, "bars": [],
                                         "vwap": None, "source": "icici-ws"})
    body = _client().get("/api/charts/intraday", params={"date": "2026-10-12"}).json()
    assert body["bars"] == [] and body["note"] == "no ticks stored for this session"
    assert "error_info" not in body  # an honest empty session is not an error


def test_intraday_bad_interval_and_bad_date_are_invalid(monkeypatch):
    monkeypatch.setattr(charts, "_fetch_ticks", lambda s, d, i: {"bars": []})
    r = _client().get("/api/charts/intraday", params={"interval": "3m"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid"
    r = _client().get("/api/charts/intraday", params={"date": "14-10-2026"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid"


# ── event-loop purity: these routes block (httpx + pandas) so they MUST be sync def ──

def test_routes_are_sync_def_for_threadpool_dispatch():
    assert not inspect.iscoroutinefunction(charts.get_ohlcv)
    assert not inspect.iscoroutinefunction(charts.get_intraday)
