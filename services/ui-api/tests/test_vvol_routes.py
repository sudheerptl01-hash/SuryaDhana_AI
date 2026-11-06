"""V-VOL (fix wave 2, 6 Nov 2026) ui-api half: the IV − RV label names close-to-close and the other two spreads ride beside
it (M01), the screener's ban / MWPL / 30→60 slope / flat-IV30 marker (M43, m070), the store's rank formula (m058), and the
three new read routes (M02 paid-delivered, M03 near-skew, M44 contract-delta). Every rule has a negative control."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from collections.abc import Iterator

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _terminal_v2_fixtures as fx  # noqa: E402
import routers.derivatives as drv  # noqa: E402

PAID = {"symbol": "NIFTY", "as_of": "2026-11-05", "closed": 2, "mean_paid_minus_delivered": 1.25, "paid_above": 1, "definition": "monthly …",
        "rows": [{"expiry": "2026-09-29", "entry": "2026-08-31", "entry_dte": 29, "iv_paid": 9.73, "rv_delivered": 10.97, "rv_demeaned": 10.2,
                  "rv_yz": 10.09, "sessions": 20, "open": False, "paid_minus_delivered": -1.24},
                 {"expiry": "2026-10-27", "entry": "2026-09-28", "entry_dte": 29, "iv_paid": 12.68, "rv_delivered": 8.94, "rv_demeaned": 9.0,
                  "rv_yz": 9.1, "sessions": 19, "open": False, "paid_minus_delivered": 3.74},
                 {"expiry": "2026-11-23", "entry": "2026-10-23", "entry_dte": 31, "iv_paid": 16.0, "rv_delivered": None, "rv_demeaned": None,
                  "rv_yz": None, "sessions": 0, "open": True, "paid_minus_delivered": None}]}
NEAR = {"symbol": "NIFTY", "rows": [{"date": f"2026-{m:02d}-{d:02d}", "expiry": "2026-11-09", "dte": 4, "skew_25d": 1.0 + (m * 31 + d) % 7 * 0.1}
                                    for m in (8, 9, 10) for d in range(1, 29)] + [{"date": "2026-11-05", "expiry": "2026-11-09", "dte": 4, "skew_25d": -0.78}]}
CDELTA = {"symbol": "NIFTY", "as_of": "2026-11-05", "expiry": "2026-11-09",
          "rows": [{"strike": 24550.0, "opt_type": "CE", "delta_factor": 0.504765}, {"strike": 24550.0, "opt_type": "PE", "delta_factor": -0.495235}]}
SCREEN = {"date": "2026-11-05", "ban_date": "2026-11-06", "ban_source": "NSE fo_secban", "rows": [
    {"symbol": "NIFTY", "date": "2026-11-05", "iv30_cm": 12.80, "iv60_cm": 12.5, "rv20_cc": 17.20, "rv20_parkinson": 13.51, "rv20_yz": 15.09,
     "iv_minus_rv20": -4.40, "iv_rank_252": 20.6, "iv_pctile_252": 59.9, "term_slope_30_90": -0.3, "skew_25d_30": 1.35, "ban": False, "mwpl_pct": None,
     "near_atm_iv": 15.44, "near_dte": 4, "next_atm_iv": 13.96, "next_dte": 12},
    {"symbol": "KAYNES", "date": "2026-11-05", "iv30_cm": 55.0, "iv60_cm": None, "rv20_cc": 60.0, "rv20_parkinson": 50.0, "rv20_yz": 52.0,
     "iv_minus_rv20": -5.0, "ban": True, "mwpl_pct": 85.51, "mwpl_date": "2026-11-05", "quality_flags": "few_expiries,cm30_flat"},
]}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    base = fx.make_handler

    def make_handler(rec: Any, **kw: Any):
        inner = base(rec, **kw)

        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if path == "/db/iv/paid-delivered":
                return httpx.Response(200, json=PAID)
            if path == "/db/iv/near-skew":
                return httpx.Response(200, json=NEAR)
            if path == "/db/iv/contract-delta":
                return httpx.Response(200, json=CDELTA)
            if path == "/db/iv/screen":
                return httpx.Response(200, json=SCREEN)
            return inner(request)
        return handler

    monkeypatch.setattr(fx, "make_handler", make_handler)
    fx.install_fake_transport(monkeypatch)
    _clear()
    yield TestClient(fx.make_app())
    _clear()


def _clear() -> None:
    drv.STORE.invalidate()                          # the SWR / down caches are process-wide: never leak these fixtures
    drv._ttl.clear()


def test_the_spread_label_names_close_to_close_and_the_screen_carries_all_three(client: TestClient) -> None:
    b = client.get("/api/derivatives/vol-screen").json()
    assert b["spread_estimator"] == "cc" and "close-to-close" in b["definitions"]["iv_minus_rv20"]
    assert "Yang-Zhang" not in b["definitions"]["iv_minus_rv20"]                       # negative control: the 5 Nov mislabel is gone
    n = {r["symbol"]: r for r in b["rows"]}["NIFTY"]
    assert n["iv_minus_rv20"] == pytest.approx(12.80 - 17.20) and n["iv_minus_rv20_yz"] == pytest.approx(12.80 - 15.09, abs=1e-4)
    assert n["iv_minus_rv20_parkinson"] == pytest.approx(12.80 - 13.51, abs=1e-4) and n["rv20_cc"] == 17.2
    assert n["term_slope_30_60"] == pytest.approx(-0.3, abs=1e-4) and n["iv30_flat"] is False
    k = {r["symbol"]: r for r in b["rows"]}["KAYNES"]
    assert k["ban"] is True and k["mwpl_pct"] == 85.51 and k["iv30_flat"] is True and k["term_slope_30_60"] is None
    assert n["term_near_next"] == pytest.approx(13.96 - 15.44, abs=1e-4) and k["term_near_next"] is None      # m070: a stock's term read
    assert b["ban_date"] == "2026-11-06" and b["ban_source"] == "NSE fo_secban" and b["badges"]["rv20_cc"] == "arithmetic"


def test_rank_uses_the_stores_formula_and_base() -> None:
    prior = [8.5 + i * 0.05 for i in range(252)]
    rank, pct, n = drv.store_rank_and_percentile([*prior, 12.81])
    assert n == 252 and pct == pytest.approx(sum(1 for v in prior if v < 12.81) / 252 * 100, abs=0.01)
    # the store's fallback base: a missing iv30 day uses the ~1-month IV, so the observation is not lost
    rank2, pct2, n2 = drv.store_rank_and_percentile([*prior[:-1], None, 12.81])
    assert n2 == 251
    # negative control: below 20 prior observations there is no rank (the store says the same)
    assert drv.store_rank_and_percentile([10.0] * 10 + [11.0])[:2] == (None, None)


def test_paid_delivered_route(client: TestClient) -> None:
    b = client.get("/api/derivatives/iv/NIFTY/paid-delivered").json()
    assert b["ok"] and b["badge"] == "context" and b["closed"] == 2 and b["mean_paid_minus_delivered"] == 1.25
    assert "close-to-close" in b["estimator"] and b["entry_dte"] == 30 and b["note"].endswith("describes, does not predict")
    assert b["rows"][-1]["open"] is True and b["rows"][-1]["rv_delivered"] is None
    assert client.get("/api/derivatives/iv/BAD SYM/paid-delivered").status_code == 422          # negative control


def test_near_skew_percentile_is_against_its_own_series(client: TestClient) -> None:
    b = client.get("/api/derivatives/iv/NIFTY/near-skew").json()
    assert b["today"] == -0.78 and b["pctile"] == 0.0 and b["series"].startswith("near expiry")   # below every prior near-expiry value
    # negative control: the 30-day series' percentile (34th on 5 Nov) is a different number from a different series
    assert b["pctile"] != 34.0 and b["badge"] == "context"


def test_contract_delta_route_pairs_by_strike(client: TestClient) -> None:
    b = client.get("/api/derivatives/iv/NIFTY/contract-delta", params={"expiry": "2026-11-09"}).json()
    assert b["rows"] == [{"strike": 24550.0, "ce": 0.504765, "pe": -0.495235}] and b["as_of"] == "2026-11-05" and b["badge"] == "context"
    assert client.get("/api/derivatives/iv/NIFTY/contract-delta", params={"expiry": "9 Nov"}).status_code == 422   # negative control


def test_new_routes_degrade_without_the_store(monkeypatch: pytest.MonkeyPatch) -> None:
    fx.install_fake_transport(monkeypatch, iv_tables=False)
    _clear()
    c = TestClient(fx.make_app())
    try:
        for path in ("/api/derivatives/iv/NIFTY/paid-delivered", "/api/derivatives/iv/NIFTY/near-skew", "/api/derivatives/iv/NIFTY/contract-delta"):
            b = c.get(path).json()
            assert b["ok"] is False and b["rows"] == [] and b["badge"] == "context", path
    finally:
        _clear()
