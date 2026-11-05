import asyncio

import httpx

from routers import news_scanner as ns


class _Resp:
    status_code = 200

    def __init__(self, data):
        self._d = data

    def json(self):
        return self._d


class _Client:
    def __init__(self, *a, **k):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        assert params["before"] == "2026-10-13"
        return _Resp({"prev": {"TCS": {"close": 2125.0, "date": "2026-10-12"}}})


def test_nse_quote_is_rebased_on_the_official_previous_close(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    yahoo_tcs = {"available": True, "price": 2269.3, "prev_close": 2156.0, "change_pct": 5.26,
                 "market_time": 1791891000, "resolved_symbol": "TCS.NS"}           # 13 Oct 2026 15:30 IST
    spx = {"available": True, "price": 7807.24, "change_pct": -0.06, "market_time": 1791891000, "resolved_symbol": "^GSPC"}
    out = dict(asyncio.run(ns._official_prev_close([("TCS.NS", yahoo_tcs), ("^GSPC", spx)])))
    assert out["TCS.NS"]["prev_close"] == 2125.0 and round(out["TCS.NS"]["change_pct"], 2) == 6.79
    assert out["TCS.NS"]["prev_source"] == "NSE" and yahoo_tcs["change_pct"] == 5.26     # cached copy untouched
    assert out["^GSPC"] is spx


def test_data_service_down_keeps_yahoo(monkeypatch):
    class Down(_Client):
        async def get(self, url, params=None):
            raise httpx.ConnectError("down")
    monkeypatch.setattr(httpx, "AsyncClient", Down)
    q = {"available": True, "price": 10.0, "change_pct": 1.0, "market_time": 1791891000, "resolved_symbol": "X.NS"}
    assert asyncio.run(ns._official_prev_close([("X.NS", q)]))[0][1] is q
