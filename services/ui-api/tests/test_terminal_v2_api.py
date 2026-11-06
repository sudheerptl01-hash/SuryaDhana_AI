"""Terminal v2 Wave 1 — the B3 routes (PLAN 1.1 / 1.2 / 1.3 / 1.4; gate G6).

* /api/derivatives/iv/* and /vol-screen: shapes, rank vs percentile (the R-IV fixture: iv30_cm 12.81 on 4 Nov 2026 →
  rank ≈ 21, percentile ≈ 60), the cone, surface + ghost, the crush ledger, the intraday path, the screen filters;
* /api/market/index-drivers*: the additive identity (Σ points = explained; residual shown), horizons, hysteresis
  state (latest revision wins), monthly leaderboard, the regime sentence ends "describes, does not predict";
* /api/desk/attribution: risk_off when the paper book is in cash; lots × closes otherwise;
* POST /api/options/margin: Breeze (mocked) → NSE SPAN file (the real-format subset) → heuristic, in that order,
  with the 4.8× note; the budget ledger refusing past the cap pushes the chain to the file;
* /api/data/health: states fresh / amber / red / gap with negative controls, trading-day aware;
* zero outbound calls: every request the routers make under the fake transport stays on the loopback.
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import _terminal_v2_fixtures as fx  # noqa: E402
import routers.data_health as dh  # noqa: E402
import routers.derivatives as drv  # noqa: E402
import routers.markets as mk  # noqa: E402
import routers.options_strategy as osr  # noqa: E402
from shared import breeze_budget as bb  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


@pytest.fixture
def rec(monkeypatch: pytest.MonkeyPatch) -> fx.Recorder:
    return fx.install_fake_transport(monkeypatch)


@pytest.fixture
def client(rec: fx.Recorder) -> TestClient:
    return TestClient(fx.make_app())


@pytest.fixture(autouse=True)
def _fresh_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv(bb.ENV_DB, str(tmp_path / "budget.sqlite"))
    monkeypatch.delenv(bb.ENV_CAP_DAY, raising=False)
    bb.reset_ledger()
    osr._SPAN_CACHE.clear()
    yield
    bb.reset_ledger()


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# 1.1 IV history
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
def test_iv_rank_and_percentile_are_distinct_and_match_the_r_iv_fixture() -> None:
    vals = [r["iv30_cm"] for r in fx.IV_SUMMARY if r["iv30_cm"] is not None]
    assert vals[-1] == 12.81
    rank, pct = drv.iv_rank(vals), drv.iv_percentile(vals)
    assert rank == pytest.approx(21.2, abs=0.6)          # (12.81 − 8.50) / (28.87 − 8.50) → 21 (R-IV §3)
    assert pct == pytest.approx(60.0, abs=1.5)           # share of the past 252 sessions below today → 60
    assert rank != pct                                   # the two numbers are not the same thing (Wave 0.6)
    # negative controls: a flat series has no rank; too short → None; today at the max → rank 100, pctile 100
    assert drv.iv_rank([10.0, 10.0, 10.0]) is None and drv.iv_rank([12.0]) is None
    assert drv.iv_rank([8.0, 9.0, 20.0]) == 100.0 and drv.iv_percentile([8.0, 9.0, 20.0]) == 100.0
    assert drv.iv_percentile([20.0, 9.0, 8.0]) == 0.0


def test_iv_history_payload(client: TestClient) -> None:
    r = client.get("/api/derivatives/iv/NIFTY", params={"days": 300})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["ok"] and b["symbol"] == "NIFTY" and b["as_of"] == "2026-11-04" and b["sessions"] == 300 and b["since"] == b["rows"][0]["date"]
    assert b["model_version"] == "b76-pcp-v1" and "rate_curve" in b["r_source"]
    last = b["rows"][-1]
    assert last["iv30_cm"] == 12.81 and last["monthly_atm_iv"] == 13.06 and last["near_dte"] == 5 and last["rv20_cc"] == 16.01
    assert set(drv.SUMMARY_FIELDS) <= set(last)
    assert b["rank"]["iv_rank_252"] == pytest.approx(21.2, abs=0.6) and b["rank"]["iv_pctile_252"] == pytest.approx(60.0, abs=1.5)
    assert b["rank"]["stored"]["iv_rank_252"] == pytest.approx(b["rank"]["iv_rank_252"], abs=0.1)
    assert b["badges"] == {"iv": "arithmetic", "rank": "arithmetic", "pctile": "arithmetic", "rv": "arithmetic", "spread": "context",
                           "skew": "context", "term": "context", "vix": "arithmetic"}
    assert b["vix"][-1] == {"date": "2026-11-04", "close": 15.27} and len(b["vix"]) == 300
    assert {e["kind"] for e in b["events"]} <= {"results", "expiry"} and any(e["kind"] == "expiry" for e in b["events"])
    assert b["note"].endswith("describes, does not predict") and "IV percentile" in b["definitions"]["iv_pctile_252"]
    assert r.headers["X-Cache"] in ("miss", "hit") and "X-Cache-Age" in r.headers


def test_iv_history_degrades_without_the_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    fx.install_fake_transport(monkeypatch, iv_tables=False)
    c = TestClient(fx.make_app())
    b = c.get("/api/derivatives/iv/NIFTY").json()
    assert b["ok"] is False and b["rows"] == [] and b["as_of"] is None and "404" in b["store_errors"]["/db/iv/summary"]
    assert b["rank"] == {"iv_rank_252": None, "iv_pctile_252": None, "stored": {"iv_rank_252": None, "iv_pctile_252": None},
                         "window_sessions": 0, "window_target": 252, "on": "iv30_cm"}       # nothing stored → a 0-observation window, said so


def test_iv_rank_window_is_252_sessions_whatever_days_the_chart_asks(client: TestClient, rec: fx.Recorder) -> None:
    """check:B3-API minor: days=20 labelled a 20-observation rank as `window_sessions: 252`. The rank now always looks back
    252 sessions (the read asks for max(days, 252) rows) while the chart rows stay at `days`."""
    short = client.get("/api/derivatives/iv/NIFTY", params={"days": 20}).json()
    full = client.get("/api/derivatives/iv/NIFTY", params={"days": 300}).json()
    assert short["sessions"] == 20 and len(short["rows"]) == 20 and short["rows"][-1]["date"] == "2026-11-04"
    assert short["rank"]["window_sessions"] == 252 and short["rank"]["window_target"] == 252
    assert short["rank"]["iv_rank_252"] == full["rank"]["iv_rank_252"] and short["rank"]["iv_pctile_252"] == full["rank"]["iv_pctile_252"]
    # 253 = today + the 252 sessions before it: the store's percentile window (m058, review 5 Nov 2026)
    assert any(p == "/db/iv/summary" and q.get("days") == "253" for _, p, q in rec.requests)
    # negative control: the old computation (rank over the 20 chart rows only) differs from the 252-session rank
    twenty = [r["iv30_cm"] for r in short["rows"] if r["iv30_cm"] is not None]
    assert drv.iv_rank(twenty) != short["rank"]["iv_rank_252"]
    # a store holding less than 252 sessions says how many it used
    rows = fx.IV_SUMMARY[-30:]
    assert drv.summary_rows(rows, 252)[-1]["date"] == "2026-11-04" and len(drv.summary_rows(rows, 252)) == 30


def test_iv_history_rejects_a_bad_symbol_and_series(client: TestClient) -> None:
    assert client.get("/api/derivatives/iv/BAD SYMBOL").status_code == 422
    assert client.get("/api/derivatives/iv/NIFTY", params={"series": "vix"}).status_code == 422


def test_iv_surface_with_ghost(client: TestClient) -> None:
    b = client.get("/api/derivatives/iv/NIFTY/surface", params={"compare": "1m"}).json()
    assert b["as_of"] == "2026-11-04" and b["n_expiries"] == 3
    exp_day, near, nxt = b["expiries"]                       # ascending by expiry: the expiry-day row first
    assert near["expiry"] == "2026-11-09" and near["near"] is True and near["atm_iv"] == 14.56 and near["skew_25d"] == 2.5
    assert exp_day["expiry"] == "2026-11-04" and exp_day["near"] is False and exp_day["quality_flags"] == "expiry_day" and exp_day["smile"] == []
    assert len(near["smile"]) == 13 and near["untraded_strikes"] == 1          # 7 strikes × 2 sides − 1 untraded
    assert near["smile"] == sorted(near["smile"], key=lambda p: p["log_moneyness"])
    assert all(p["iv"] is not None for p in near["smile"])
    assert b["compare"]["requested"] == "2026-10-05" and b["compare"]["as_of"] == "2026-10-05" and b["compare"]["expiries"][0]["atm_iv"] == 11.2
    assert b["badges"]["skew"] == "context"


def test_iv_cone(client: TestClient) -> None:
    rows = drv.summary_rows(fx.IV_SUMMARY, 3000)
    cone = drv.iv_cone(rows)
    y1 = cone["years"][0]
    assert y1["years"] == 1 and y1["sessions"] == 250 and y1["tenors"]["iv30_cm"]["n"] == 250
    t = y1["tenors"]["iv30_cm"]
    assert t["min"] <= t["p25"] <= t["p50"] <= t["p75"] <= t["max"] and t["min"] == pytest.approx(8.5, abs=0.3)
    assert cone["today"]["iv30_cm"] == 12.81 and cone["as_of"] == "2026-11-04"
    assert drv.iv_cone([])["years"][0]["tenors"]["iv30_cm"]["n"] == 0        # negative control: empty store → nulls
    b = client.get("/api/derivatives/iv/NIFTY/cone").json()
    assert [y["years"] for y in b["years"]] == [1, 3, 5] and b["badge"] == "context"
    assert [t["expiry"] for t in b["term_today"]] == ["2026-11-04", "2026-11-09", "2026-11-23"]


def test_iv_events_ledger(client: TestClient) -> None:
    b = client.get("/api/derivatives/iv/INFY/events", params={"n": 8}).json()
    assert b["n"] == 2 and b["rows"][0]["released_at"] > b["rows"][1]["released_at"]      # newest first
    assert b["rows"][0]["crush_pct"] == -41.0 and b["rows"][0]["implied_move_pct"] == 4.1 and b["rows"][0]["realised_move_pct"] == 2.9
    assert b["badge"] == "context" and b["note"].endswith("describes, does not predict")
    assert client.get("/api/derivatives/iv/TCS/events").json()["rows"] == []


def test_iv_intraday_path(client: TestClient) -> None:
    path = drv.intraday_path(fx.IV_INTRADAY)
    assert path["source"] == "BREEZE" and path["snapshots"] == 2
    p0 = path["points"][0]
    assert p0["expiry"] == "2026-11-09" and p0["atm_strike"] == 24000 and p0["atm_iv"] == pytest.approx(15.0, abs=0.01)
    assert p0["straddle"] == 302.0 and p0["pcr"] == 1.2 and p0["nse_atm_iv"] == pytest.approx(15.3, abs=0.01) and p0["n_strikes"] == 6
    assert drv.intraday_path([]) == {"points": [], "source": "OFFLINE", "sources": [], "snapshots": 0}
    b = client.get("/api/derivatives/iv/NIFTY/intraday").json()
    assert b["date"] == "2026-11-05" and b["source"] == "BREEZE" and b["badge"] == "context"
    assert client.get("/api/derivatives/iv/TCS/intraday", params={"date": "2026-11-05"}).json()["source"] == "OFFLINE"


def test_vol_screen_sorts_and_filters(client: TestClient) -> None:
    b = client.get("/api/derivatives/vol-screen").json()
    assert b["as_of"] == "2026-11-04" and b["sort"] == "iv_pctile" and b["n"] == 5
    assert [r["symbol"] for r in b["rows"]][:4] == ["KAYNES", "INFY", "NIFTY", "RELIANCE"] and b["rows"][-1]["symbol"] == "IDEA"  # nulls last
    assert b["rows"][0]["ban"] is True and b["rows"][0]["mwpl_pct"] == 96.0
    b2 = client.get("/api/derivatives/vol-screen", params={"sort": "iv_minus_rv", "results_within": 10}).json()
    assert [r["symbol"] for r in b2["rows"]] == ["KAYNES", "INFY"] or [r["symbol"] for r in b2["rows"]] == ["KAYNES", "INFY", "IDEA"]
    assert all(r["results_in_days"] <= 10 for r in b2["rows"])
    # pure negative control: a fixed today keeps the window deterministic (RELIANCE reports in 2027 → excluded)
    rows = drv.screen_rows(fx.SCREEN_ROWS, "skew", 10, today=date(2026, 11, 5))
    assert [r["symbol"] for r in rows] == ["KAYNES", "INFY", "IDEA"]
    assert client.get("/api/derivatives/vol-screen", params={"sort": "alpha"}).status_code == 422
    assert b["badges"]["iv_minus_rv20"] == "context" and b["badges"]["iv30_cm"] == "arithmetic" and "score" not in b


def test_legacy_option_history_serves_both_rank_and_percentile_defined(client: TestClient) -> None:
    b = client.get("/api/market/option-history/NIFTY").json()
    assert b["rows"] and b["iv_rank_252"] is not None and b["iv_pctile_252"] is not None and b["iv_rank_252"] != b["iv_pctile_252"]
    assert "percentile" in b["definitions"]["iv_pctile_252"].lower() and "rank" in b["definitions"]["iv_rank_252"].lower()
    assert mk.with_iv_rank_and_percentile({"rows": "nope"}) == {"rows": "nope"}      # negative control: untouched


def _err_code(r: Any) -> str:
    """errors.fail() body: {detail: {code, message, hint}} on a bare app ({error: {...}} behind main.py's handler)."""
    b = r.json()
    block = b.get("error") if isinstance(b.get("error"), dict) else b.get("detail")
    return str(block["code"])


def test_legacy_option_history_uses_the_shared_client_only(client: TestClient, rec: fx.Recorder, monkeypatch: pytest.MonkeyPatch) -> None:
    """check:B3-API major: the route used a per-request httpx.AsyncClient (invisible to the fake transport, so its test
    leaned on the live :8001). With any raw AsyncClient construction blocked it must still answer from the fixture."""
    def no_raw_client(*_: Any, **__: Any) -> Any:
        raise AssertionError("a per-request httpx.AsyncClient was built on the request path")

    import types

    stub = types.SimpleNamespace(AsyncClient=no_raw_client, Timeout=lambda *a, **k: None, HTTPError=Exception)
    monkeypatch.setattr(mk, "httpx", stub)                      # markets.py's own httpx name only; the fake transport is real
    r = client.get("/api/market/option-history/NIFTY", params={"days": 300})
    assert r.status_code == 200, r.text
    assert r.json()["rows"] and ("localhost", "/db/option-history/NIFTY", {"days": "300"}) in rec.requests
    # negative controls: an unknown symbol maps the upstream 404 to the structured error; a bad symbol never leaves
    miss = client.get("/api/market/option-history/ZZZZ")
    assert miss.status_code == 404 and _err_code(miss) == "not_found"
    n = len(rec.requests)
    assert client.get("/api/market/option-history/BAD%20SYM").status_code == 422 and len(rec.requests) == n


def test_legacy_option_history_upstream_down_is_a_structured_503(monkeypatch: pytest.MonkeyPatch) -> None:
    fx.install_fake_transport(monkeypatch)
    from shared import http_client

    def dead(request: Any) -> Any:
        raise __import__("httpx").ConnectError("down", request=request)

    import httpx as _hx
    monkeypatch.setattr(http_client, "get_async_client", lambda: _hx.AsyncClient(transport=_hx.MockTransport(dead)))
    r = TestClient(fx.make_app()).get("/api/market/option-history/NIFTY")
    assert r.status_code == 503 and _err_code(r) == "upstream_down"


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# 1.2 index drivers
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
def test_drivers_identity_and_horizons() -> None:
    d = fx.DRIVERS
    dates = sorted({r["date"] for r in d["contribution"]})
    win = mk.horizon_window(dates, "1m")
    assert len(win) == 21 and win[-1] == dates[-1]
    s = mk.slice_contributions(d["contribution"], d["fit"], d["weights"], win)
    explained = sum(m["points"] for m in s["members"])
    assert s["explained_pts"] == pytest.approx(explained, abs=0.2)
    assert s["index_move_pts"] - s["explained_pts"] == pytest.approx(s["residual_pts"], abs=0.11)     # the residual is shown, never hidden
    assert sum(m["weight_pct"] for m in s["members"]) == pytest.approx(100.0)
    assert s["members"][0]["points"] >= s["members"][-1]["points"] and s["members"][0]["share_abs"] <= 1.0
    assert {m["industry"] for m in s["members"]} == {"Financial Services", "Information Technology", "Fast Moving Consumer Goods"}
    assert sum(sec["points"] for sec in s["sectors"]) == pytest.approx(explained, abs=0.2)
    c = s["concentration"]
    assert c["weight_hhi"] == pytest.approx(0.38) and c["effective_n"] == pytest.approx(2.6, abs=0.05) and c["top5_weight_pct"] == 100.0
    assert s["breadth"]["up"] + s["breadth"]["down"] <= 3 and s["breadth"]["word"] in ("narrow", "even", "broad")
    assert mk.horizon_window(dates, "ytd")[0][:4] == "2026" and mk.horizon_window(dates, "1d") == dates[-1:]
    assert mk.horizon_window(dates, "since_change", "2026-10-14")[0] == "2026-10-14"
    assert mk.horizon_window(dates, "since_change", None) == dates[-20:]
    assert mk.horizon_window([], "5d") == []


def test_drivers_fit_state_and_sentence() -> None:
    f = mk.fit_summary(fx.DRIVERS["fit"])
    assert f["sessions"] == 60 and f["mae_60s"] < 1 and f["degraded"] is False and f["r2_60s"] > 0.99
    degraded = mk.fit_summary([{**r, "residual_points": 40.0} for r in fx.DRIVERS["fit"]])
    assert degraded["degraded"] is True and "degraded" in degraded["note"]
    assert mk.fit_summary([])["degraded"] is True
    st = mk.driver_state_row(fx.DRIVERS["state"], 20)
    assert st["leader"] == "HDFCBANK" and st["tenure"] == 14 and st["changed_from"] == "INFY"    # the newer computed_at wins over "STALE"
    assert st["sentence"].endswith("describes, does not predict") and "narrow" in st["sentence"] and "HDFCBANK" in st["sentence"]
    assert mk.driver_state_row(fx.DRIVERS["state"], 60)["changed_from"] is None
    assert mk.driver_state_row([], 20) is None and mk.regime_sentence(20, None, None, None, None).endswith("describes, does not predict")
    assert mk.breadth_word(-1.3) == "narrow" and mk.breadth_word(0.2) == "even" and mk.breadth_word(2.0) == "broad" and mk.breadth_word(None) is None
    for word in ("bullish", "bearish"):
        assert word not in st["sentence"]


def test_index_drivers_route(client: TestClient) -> None:
    r = client.get("/api/market/index-drivers", params={"index": "NIFTY 50", "horizon": "5d"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["ok"] and b["index"] == "NIFTY 50" and b["horizon"]["sessions"] == 5 and b["horizon"]["to"] == b["as_of"]
    assert len(b["members"]) == 3 and b["weight_method"]["method"] == "rebuilt_calibrated" and "calibrated" in b["weight_method"]["label"]
    assert b["driver"]["window"] == 20 and b["driver"]["sentence"].endswith("describes, does not predict")
    assert b["badges"] == {"members": "arithmetic", "sectors": "arithmetic", "concentration": "arithmetic", "fit": "arithmetic",
                           "driver": "context", "breadth": "context", "monthly": "context"}
    assert b["history_since"] == fx.DRIVERS["contribution"][0]["date"] and b["fit"]["degraded"] is False
    assert client.get("/api/market/index-drivers", params={"index": "NIFTY 500"}).status_code == 422
    assert client.get("/api/market/index-drivers", params={"horizon": "2y"}).status_code == 422


def test_index_drivers_timeline_and_monthly(client: TestClient) -> None:
    t = client.get("/api/market/index-drivers/timeline", params={"window": 20}).json()
    assert t["points"] and t["points"][-1]["leader"] == "HDFCBANK" and t["points"][-1]["changed"] is False and t["changes"] == []
    assert t["badge"] == "context" and "hysteresis" in t["note"]
    m = client.get("/api/market/index-drivers/monthly", params={"months": 3}).json()
    assert 1 <= m["n"] <= 3 and all(x["leader"] in {"HDFCBANK", "INFY", "ITC"} for x in m["months"])
    last = m["months"][-1]
    assert len(last["top3_add"]) == 3 and last["top3_add"][0]["points"] >= last["top3_add"][-1]["points"]
    assert last["explained_pts"] == pytest.approx(sum(x["points"] for x in last["top3_add"]), abs=0.2)   # 3 members: top-3 is everything
    months = mk.monthly_leaderboard(fx.DRIVERS["contribution"], fx.DRIVERS["fit"], 12)
    assert months[0]["leader_changed"] is False and all(0 < x["leader_share"] <= 1 for x in months)


def test_index_drivers_degrade_without_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    fx.install_fake_transport(monkeypatch, drivers_tables=False)
    b = TestClient(fx.make_app()).get("/api/market/index-drivers").json()
    assert b["ok"] is False and b["members"] == [] and b["driver"] is None and b["as_of"] is None


def test_desk_attribution_risk_off_and_invested(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def cash() -> dict[str, Any]:
        return fx.DESK_STATUS_CASH

    monkeypatch.setattr(mk, "_desk_status", cash)
    b = client.get("/api/desk/attribution", params={"horizon": "5d"}).json()
    assert b["risk_off"] is True and b["since"] == "2026-10-29" and b["rows"] == [] and b["paper_only"] is True
    assert "liquid fund" in b["note"] and b["nifty"]["top5_add"] and b["badges"] == {"book": "arithmetic", "nifty": "arithmetic"}
    mk._DESK_STORE.invalidate()

    async def invested() -> dict[str, Any]:
        return fx.DESK_STATUS_INVESTED

    monkeypatch.setattr(mk, "_desk_status", invested)
    b = client.get("/api/desk/attribution", params={"horizon": "5d"}).json()
    assert b["risk_off"] is False and len(b["rows"]) == 1
    row = b["rows"][0]
    assert row["symbol"] == "INFY" and row["qty"] == 100 and row["close_to"] >= row["close_from"] and row["pp_of_nav"] is not None
    assert b["book_pp"] == pytest.approx(row["pp_of_nav"])
    # pure: a book with no closes → nulls, never a crash
    out = mk.desk_attribution(fx.DESK_STATUS_INVESTED, {}, ["2026-11-01", "2026-11-04"], None)
    assert out["rows"][0]["pp_of_nav"] is None and out["risk_off"] is False


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# 1.3 margin: Breeze → SPAN file → heuristic
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
class FakeBreeze:
    def __init__(self) -> None:
        self.calls: list[tuple[list[dict[str, str]], str]] = []

    def margin_calculator(self, lists: list[dict[str, str]], exchange_code: str) -> dict[str, Any]:
        self.calls.append((lists, exchange_code))
        return fx.BREEZE_MARGIN_SAMPLE


def _no_session(*_: Any, **__: Any) -> tuple[None, str]:
    return None, "ICICI credentials not configured in .env"


def test_margin_breeze_first_through_the_ledger(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import routers.positions as pos
    fake = FakeBreeze()
    monkeypatch.setattr(pos, "_get_breeze_client", lambda: (fake, None))
    b = client.post("/api/options/margin", json={"symbol": "NIFTY", "legs": fx.CONDOR_LEGS}).json()
    assert b["source"] == "BREEZE" and b["source_chip"] == "BREEZE" and b["span_margin_required"] == 81497.07
    assert b["non_span_margin_required"] == 31135.78 and b["total_margin"] == pytest.approx(112632.85) and b["badge"] == "arithmetic"
    assert b["attempts"] == [{"source": "BREEZE", "ok": True, "reason": "ok"}] and b["paper_only"] is True
    legs, exch = fake.calls[0]
    assert exch == "NFO" and legs[0] == {"strike_price": "23700", "quantity": "65", "right": "Put", "product": "Options", "action": "Sell",
                                         "price": "73.5", "expiry_date": "09-Nov-2026", "stock_code": "NIFTY"}
    assert bb.ledger().status()["by_caller"] == {"ui-api.margin": 1} and bb.ledger().status()["by_method"] == {"margin_calculator": 1}
    assert b["heuristic"]["error_factor_measured"] == 4.8          # the heuristic rides along, labelled, even when Breeze answers


def test_margin_budget_exhausted_falls_to_the_span_file(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import routers.positions as pos
    fake = FakeBreeze()
    monkeypatch.setattr(pos, "_get_breeze_client", lambda: (fake, None))
    monkeypatch.setenv(bb.ENV_CAP_DAY, "1")
    bb.reset_ledger()
    bb.ledger().acquire("someone", "get_quotes")                     # the day's budget is gone
    monkeypatch.setenv(osr.SPAN_DIR_ENV, str(fx.span_zip(tmp_path)))
    b = client.post("/api/options/margin", json={"symbol": "NIFTY", "legs": fx.CONDOR_LEGS}).json()
    assert fake.calls == []                                           # refused BEFORE the SDK ran
    assert b["attempts"][0]["source"] == "BREEZE" and b["attempts"][0]["ok"] is False and "budget" in b["attempts"][0]["reason"]
    assert b["source"] == "NSE_SPAN_FILE" and b["source_chip"] == "NSE SPAN FILE" and b["as_of"] == "2026-11-04"
    assert b["span_margin_required"] == pytest.approx(8123.7, abs=1.0)        # scanning risk of the condor from the real arrays
    d = b["detail"]
    assert d["file"] == "nsccl.20261104.s.zip" and d["settlement_file"] is True and d["calendar_spread_charge"] == 0.0 and d["short_option_minimum"] == 0.0
    assert d["worst_scenario"] == 10 and len(d["scenario_losses"]) == 16          # price up 2/3 of the range, vol down (1-based CME order)
    assert d["exposure"]["pct_of_notional"] == 2.0 and d["exposure"]["badge"] == "heuristic" and b["non_span_margin_required"] == d["exposure"]["value"]
    assert d["exposure"]["value"] == pytest.approx(2 * 65 * 23970.70 * 0.02, rel=1e-6)   # the file's near future as the reference
    assert b["badge"] == "heuristic" and b["heuristic"]["total"] > 5 * b["span_margin_required"]
    assert b["badges"] == {"span_margin_required": "arithmetic", "non_span_margin_required": "heuristic", "total_margin": "heuristic"}


def test_span_parser_on_the_real_format_subset() -> None:
    text = fx.SPAN_FIXTURE.read_text(encoding="utf-8")
    p = osr.parse_span_product(text, "NIFTY")
    assert p is not None and p.file_date == "20261104" and p.settlement is True
    assert ("F", "20261123", 0.0) in p.arrays and ("P", "20261109", 23700.0) in p.arrays and ("C", "20261109", 24400.0) in p.arrays
    short_put = p.arrays[("P", "20261109", 23700.0)]
    assert short_put.price == 73.5 and short_put.delta == pytest.approx(-0.2663, abs=1e-3) and len(short_put.losses) == 16
    assert p.scan_ranges["20261109"] == 2228.34 and p.som_rate == 0.0 and [s["rate"] for s in p.calendar_spreads] == [424.0, 424.0, 424.0]
    # a lone short 23700 PE: scanning risk per lot from the arrays (Breeze said ₹1,72,460.67 for the same leg on 4 Nov — the
    # file is the 17:00 settlement set; exposure sits on top; the gap is recorded in API_CONTRACT §7)
    one = osr.span_margin(p, [osr.MarginLegIn(side="sell", kind="PE", strike=23700, expiry=date(2026, 11, 9), premium=73.5, lots=1, lot_size=65)])
    assert one["ok"] and one["span_margin"] == pytest.approx(122247.45, abs=1.0) and one["net_option_value"] == pytest.approx(-73.5 * 65)
    # a calendar spread forms the flat ₹424 charge per spread between a long delta in 20261109 and a short in 20261123
    cal = osr.span_margin(p, [osr.MarginLegIn(side="buy", kind="CE", strike=23700, expiry=date(2026, 11, 9), premium=303.25, lots=1, lot_size=65),
                              osr.MarginLegIn(side="sell", kind="FUT", strike=None, expiry=date(2026, 11, 23), premium=23970.7, lots=1, lot_size=65)])
    assert cal["ok"] and cal["spreads"] and cal["spreads"][0]["long"] == "20261109" and cal["spreads"][0]["short"] == "20261123"
    assert cal["calendar_spread_charge"] == pytest.approx(424 * 0.5951 * 65, rel=1e-3) and cal["span_margin"] >= cal["calendar_spread_charge"]
    # negative controls: a contract outside the file; an underlying outside the file; a file without arrays
    miss = osr.span_margin(p, [osr.MarginLegIn(side="sell", kind="PE", strike=25000, expiry=date(2026, 11, 9), premium=1, lots=1, lot_size=65)])
    assert miss == {"ok": False, "missing": ["PE 25000.0 2026-11-09"]}
    assert osr.parse_span_product(text, "BANKNIFTY") is None and osr.parse_span_product("<spanFile></spanFile>", "NIFTY") is None


def test_margin_heuristic_last_with_the_measured_error(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import routers.positions as pos
    monkeypatch.setattr(pos, "_get_breeze_client", _no_session)
    monkeypatch.setenv(osr.SPAN_DIR_ENV, str(tmp_path / "empty"))
    b = client.post("/api/options/margin", json={"symbol": "NIFTY", "forward": 23931.0, "legs": fx.CONDOR_LEGS}).json()
    assert [a["source"] for a in b["attempts"]] == ["BREEZE", "NSE_SPAN_FILE", "HEURISTIC"]
    assert b["attempts"][0]["ok"] is False and "no live Breeze session" in b["attempts"][0]["reason"]
    assert b["attempts"][1]["ok"] is False and "no SPAN file" in b["attempts"][1]["reason"]
    assert b["source"] == "HEURISTIC" and b["source_chip"] == "HEURISTIC" and b["badge"] == "heuristic"
    assert b["heuristic"]["error_factor_measured"] == 4.8 and "4.8×" in b["note"] and "81,497.07" in b["note"]
    assert b["span_margin_required"] == pytest.approx(2 * 0.12 * 23931.0 * 65 + (73.5 + 66.1 + 35.45 + 31.7) * 65, rel=1e-6)
    assert b["span_margin_required"] > 3.5e5 and b["non_span_margin_required"] == 0.0


def test_margin_span_file_misses_a_contract_then_heuristic(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import routers.positions as pos
    monkeypatch.setattr(pos, "_get_breeze_client", _no_session)
    monkeypatch.setenv(osr.SPAN_DIR_ENV, str(fx.span_zip(tmp_path)))
    legs = [{**fx.CONDOR_LEGS[0], "strike": 25000}]
    b = client.post("/api/options/margin", json={"symbol": "NIFTY", "legs": legs, "sources": "span_file,heuristic"}).json()
    assert b["attempts"][0]["source"] == "NSE_SPAN_FILE" and "not in SPAN file" in b["attempts"][0]["reason"] and b["source"] == "HEURISTIC"
    # Breeze answering without a margin block is a failed attempt, not a crash
    monkeypatch.setattr(pos, "_get_breeze_client", lambda: (type("B", (), {"margin_calculator": lambda self, l, e: {"Success": "", "Status": 500, "Error": "boom"}})(), None))
    b = client.post("/api/options/margin", json={"symbol": "NIFTY", "legs": fx.CONDOR_LEGS, "sources": "breeze,heuristic"}).json()
    assert b["attempts"][0]["source"] == "BREEZE" and b["attempts"][0]["ok"] is False and b["source"] == "HEURISTIC"
    assert client.post("/api/options/margin", json={"symbol": "NIFTY", "legs": []}).status_code == 422


def test_strategy_analyze_prints_the_measured_error(client: TestClient) -> None:
    body = {"symbol": "NIFTY", "forward": 23931.0, "days_to_expiry": 5, "default_iv": 14.0,
            "legs": [{"side": "sell", "kind": "PE", "strike": 23700, "premium": 73.5, "lots": 1, "lot_size": 65}]}
    b = client.post("/api/options/strategy/analyze", json=body).json()
    assert b["margin"]["estimate"] is True and b["margin"]["error_factor_measured"] == 4.8 and "/api/options/margin" in b["margin"]["real_margin"]


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# 1.4 data health
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
def test_trading_day_helpers() -> None:
    hol = [date(2026, 11, 20)]
    assert dh.last_close_session(datetime(2026, 11, 5, 22, 0, tzinfo=IST), hol) == date(2026, 11, 5)
    assert dh.last_close_session(datetime(2026, 11, 5, 9, 0, tzinfo=IST), hol) == date(2026, 11, 4)
    assert dh.last_close_session(datetime(2026, 11, 8, 12, 0, tzinfo=IST), hol) == date(2026, 11, 6)       # Sunday → Friday
    assert dh.last_close_session(datetime(2026, 11, 20, 18, 0, tzinfo=IST), hol) == date(2026, 11, 19)     # holiday → Thursday
    assert dh.trading_days(date(2026, 10, 30), date(2026, 11, 5), hol) == [date(2026, 11, d) for d in (2, 3, 4, 5)]
    assert dh.next_trading_day(date(2026, 11, 19), hol) == date(2026, 11, 23)


def test_classify_states_with_negative_controls() -> None:
    row = dh.FALLBACK_CATALOG[2]                                         # nse_fo_daily: expected by 21:00, max_age 2
    now = datetime(2026, 11, 5, 22, 0, tzinfo=IST)
    assert dh.classify(row, date(2026, 11, 5), now, [])["state"] == "fresh"
    one_behind_due = dh.classify(row, date(2026, 11, 4), now, [])
    assert one_behind_due["state"] == "amber" and one_behind_due["lag_sessions"] == 1 and "1 session behind" in one_behind_due["note"]
    not_due = dh.classify(row, date(2026, 11, 4), datetime(2026, 11, 5, 20, 0, tzinfo=IST), [])
    assert not_due["state"] == "fresh" and "not due yet" in not_due["note"]            # 20:00 < 21:00: nothing is late yet
    assert dh.classify(row, date(2026, 11, 3), now, [])["state"] == "amber"             # 2 behind ≤ max_age
    red = dh.classify(row, date(2026, 10, 30), now, [])
    assert red["state"] == "red" and red["lag_sessions"] == 4
    assert dh.classify(row, None, now, [])["state"] == "red" and dh.classify(row, None, now, [], gap=True)["state"] == "gap"
    mtf = dh.FALLBACK_CATALOG[5]                                          # T−1 file: stored 3 Nov on the evening of 5 Nov = 1 session behind
    assert dh.classify(mtf, date(2026, 11, 4), now, [])["state"] == "fresh"
    assert dh.classify(mtf, date(2026, 11, 3), now, [])["state"] == "fresh"           # 22:00 < 23:00: not due
    assert dh.classify(mtf, date(2026, 11, 3), datetime(2026, 11, 5, 23, 30, tzinfo=IST), [])["state"] == "amber"
    # a holiday between as_of and now is not a missed session
    assert dh.classify(row, date(2026, 11, 19), datetime(2026, 11, 20, 22, 0, tzinfo=IST), [date(2026, 11, 20)])["state"] == "fresh"


def test_expected_by_is_trading_day_aware_after_weekends_and_holidays() -> None:
    """check:B3-API: T−1 files and morning slots are due on the NEXT TRADING DAY, not the next calendar day."""
    mtf = dh.FALLBACK_CATALOG[5]                                          # nse_mtf: T−1 file, expected by 23:00
    insider = dh.FALLBACK_CATALOG[16]                                     # a morning slot: gold_series by 08:00 (the insider row
    assert mtf.id == "nse_mtf" and insider.id == "gold_series"            # moved to a 22:30 evening slot on 5 Nov: nse_insider_daily)
    assert dh.FALLBACK_CATALOG[7].id == "nse_insider_trades" and dh._expected_at(dh.FALLBACK_CATALOG[7], date(2026, 11, 6), []) == \
        datetime(2026, 11, 6, 22, 30, tzinfo=IST)                         # the daily insider run: due the same evening
    mon_20 = datetime(2026, 11, 9, 20, 0, tzinfo=IST)                     # Monday 20:00, stored Thu 5 Nov: Friday's file lands Monday 22:12
    r = dh.classify(mtf, date(2026, 11, 5), mon_20, [])
    assert r["state"] == "fresh" and "not due yet" in r["note"] and r["lag_sessions"] == 1
    assert dh._expected_at(mtf, date(2026, 11, 6), []) == datetime(2026, 11, 9, 23, 0, tzinfo=IST)        # Fri → Mon 23:00, not Sat
    assert dh._expected_at(insider, date(2026, 11, 6), []) == datetime(2026, 11, 9, 8, 0, tzinfo=IST)     # Fri → Mon 08:00, not Sat
    # negative control: the same row on Monday 23:30 IS due → amber
    assert dh.classify(mtf, date(2026, 11, 5), datetime(2026, 11, 9, 23, 30, tzinfo=IST), [])["state"] == "amber"
    # a holiday: Thu 19 Nov's T−1 file is due on Mon 23 Nov (Fri 20 Nov = Guru Nanak Jayanti), not Fri 20 Nov
    hol = [date(2026, 11, 20)]
    assert dh._expected_at(mtf, date(2026, 11, 19), hol) == datetime(2026, 11, 23, 23, 0, tzinfo=IST)
    assert dh._expected_at(insider, date(2026, 11, 19), hol) == datetime(2026, 11, 23, 8, 0, tzinfo=IST)
    # negative control: without the holiday in the calendar the deadline is Friday
    assert dh._expected_at(mtf, date(2026, 11, 19), []) == datetime(2026, 11, 20, 23, 0, tzinfo=IST)
    # same-day evening slots are unchanged by the fix (the session itself)
    assert dh._expected_at(dh.FALLBACK_CATALOG[2], date(2026, 11, 6), []) == datetime(2026, 11, 6, 21, 0, tzinfo=IST)


def test_data_health_route(client: TestClient) -> None:
    r = client.get("/api/data/health")
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["status"] == "ok" and b["service"] == "data-health" and b["data_service"]["reachable"] is True and b["controller_online"] is True
    assert b["catalog_source"].startswith("ui-api fallback seed") and b["last_session"] == "2026-11-05"
    by_id = {row["id"]: row for row in b["rows"]}
    assert by_id["nse_fo_daily"]["state"] == "fresh" and by_id["nse_fo_daily"]["as_of"] == "2026-11-05" and by_id["nse_fo_daily"]["lag_sessions"] == 0
    assert by_id["nse_fo_daily"]["last_run"] == {"ts": "2026-11-05T20:31:00+05:30", "status": "ok", "ms": 41000}
    assert by_id["nse_results"]["state"] == "red" and by_id["nse_results"]["lag_sessions"] == 4
    # M30 (6 Nov): no catch-up is claimed for results_capture_daily (none scheduled; its 3-day window does not reach 4
    # sessions back)
    assert by_id["nse_results"]["catchup_at"] is None     # (the positive control, a self-catching job's next run:
                                                          # nse_combined_oi in test_data_health_prefers_the_data_service_catalog)
    assert by_id["archive:internals"]["state"] == "gap" and by_id["archive:internals"]["unrecoverable"] is True
    assert by_id["nse_mtf"]["state"] == "fresh" and by_id["gold_etf_holdings"]["state"] == "red"
    assert by_id["iv_summary_daily"]["state"] == "red" and by_id["iv_summary_daily"]["note"] == "nothing stored"
    assert b["summary"]["rows"] == len(b["rows"]) and b["summary"]["gaps"] == 1 and b["summary"]["red"] >= 3
    assert b["rows"][0]["state"] == "gap" and "score" not in b and b["note"].endswith("describes, does not predict")
    assert all("stored" in row["note"] or row["note"] in ("nothing stored",) or row["state"] == "gap" for row in b["rows"])
    assert client.get("/api/data/health", params={"page": "DERV"}).json()["summary"]["rows"] < len(b["rows"])


def test_data_health_prefers_the_data_service_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """B1 deployed: /db/data-health (B1's computed rows, its real key names: max_age_sessions, expected_offset_days,
    freshness_kind, job_id, cadence) is composed — B1's state kept, unknown endpoint rows completed from the controller."""
    rec = fx.install_fake_transport(monkeypatch, catalog=True)
    b = TestClient(fx.make_app()).get("/api/data/health").json()
    assert b["catalog_source"] == "data-service dataset_catalog (/db/data-health)" and b["status"] == "ok" and b["ok"] is True
    by_id = {r["id"]: r for r in b["rows"]}
    assert set(by_id) == {r["id"] for r in fx.B1_HEALTH["rows"]}
    assert by_id["nse_fo_daily"]["state"] == "fresh" and by_id["nse_fo_daily"]["label"] == "nse_fo_daily (B1 catalog)"
    assert by_id["nse_fo_daily"]["last_run"]["status"] == "ok" and by_id["nse_fo_daily"]["note"] == "stored 05 Nov · expected by 21:00"
    assert by_id["nse_mtf"]["state"] == "fresh" and "1 session behind" in by_id["nse_mtf"]["note"]          # B1: not due yet → kept fresh
    assert by_id["nse_combined_oi"]["state"] == "amber" and by_id["nse_combined_oi"]["catchup_at"] == "2026-11-06T20:30:00+05:30"
    assert by_id["nse_results"]["state"] == "red" and by_id["nse_results"]["lag_sessions"] == 4 and by_id["nse_results"]["max_age_sessions"] == 1
    assert by_id["archive:internals"]["state"] == "gap" and by_id["archive:internals"]["unrecoverable"] is True
    # B1's `unknown` (endpoint / live) rows: judged by the job's last run, never guessed green
    assert by_id["option_chain_eod"]["state"] == "fresh" and "ran 05 Nov 20:31 (ok)" in by_id["option_chain_eod"]["note"]
    assert by_id["desk_mark"]["state"] == "amber" and "(error)" in by_id["desk_mark"]["note"]                # last run failed on 30 Oct
    assert by_id["nse_live"]["state"] == "live" and by_id["nse_live"]["catchup_at"] is None
    assert by_id["market_monitor"]["state"] == "unknown" and "not in the controller's schedule" in by_id["market_monitor"]["note"]
    assert b["summary"] == {"green": 4, "amber": 2, "red": 1, "gaps": 1, "unknown": 1, "rows": 9}
    assert [r["state"] for r in b["rows"]][:2] == ["gap", "red"] and "score" not in b
    # the legacy inputs are not read when B1 answers (one source per view)
    assert "/db/nse-positions-meta" not in rec.paths() and "/db/data-health" in rec.paths()
    # page filter on B1's comma-split pages
    assert [r["id"] for r in TestClient(fx.make_app()).get("/api/data/health", params={"page": "MRGN"}).json()["rows"]] == ["nse_mtf"]


def test_data_health_composition_negative_controls() -> None:
    now = fx.NOW
    # the fixture mirrors B1's real row keys (tests/test_data_health.py::UI_API_READS asserts them on reads.health())
    reads = {"id", "label", "pages", "publisher", "published_ist", "expected_by", "as_of", "lag_sessions", "state", "unrecoverable",
             "job_id", "dictionary_anchor", "badge", "max_age_sessions", "cadence", "note"}
    assert all(reads <= set(r) for r in fx.B1_HEALTH["rows"])
    assert dh.compose_b1_health({"rows": []}, [], [], now) is None                     # no rows → the seed path, not an empty view
    assert dh.compose_b1_health({"detail": "Not Found"}, [], [], now) is None
    row = fx.B1_HEALTH["rows"][5]                                                        # option_chain_eod, job nse_positions_catchup
    stale_job = [{"id": "nse_positions_catchup", "last_status": "ok", "last_run_ts": "2026-11-04T20:31:00+05:30"}]
    out = dh.compose_b1_health({"rows": [row]}, stale_job, [], now)
    assert out is not None and out["rows"][0]["state"] == "amber"                         # ok but before the due session → not fresh
    never = dh.compose_b1_health({"rows": [row]}, [{"id": "nse_positions_catchup", "last_status": None, "last_run_ts": None}], [], now)
    assert never is not None and never["rows"][0]["state"] == "red"
    # an evening job is judged against the session it must cover BY NOW: Thursday 16:00, the 20:00 desk run of Wednesday is
    # current (Thursday's is not due) → fresh; Thursday 21:00 the same run is a session old → amber
    desk = {**row, "id": "desk_mark", "job_id": "desk_daily", "expected_by": "20:00"}
    wed_run = [{"id": "desk_daily", "last_status": "done", "last_run_ts": "2026-11-04T19:31:00+05:30"}]
    at_16 = dh.compose_b1_health({"rows": [desk]}, wed_run, [], datetime(2026, 11, 5, 16, 0, tzinfo=IST))
    at_21 = dh.compose_b1_health({"rows": [desk]}, wed_run, [], datetime(2026, 11, 5, 21, 0, tzinfo=IST))
    assert at_16 is not None and at_16["rows"][0]["state"] == "fresh"
    assert at_21 is not None and at_21["rows"][0]["state"] == "amber"
    assert dh._due_session("20:00", 0, datetime(2026, 11, 9, 10, 0, tzinfo=IST), []) == date(2026, 11, 6)     # Monday morning → Friday
    assert dh._due_session("08:00", 1, datetime(2026, 11, 9, 9, 0, tzinfo=IST), []) == date(2026, 11, 6)      # Friday's T+1 slot is Monday 08:00


def test_data_health_degrades_when_inputs_are_down(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = fx.install_fake_transport(monkeypatch)
    from shared import http_client

    def dead(request: Any) -> Any:
        raise __import__("httpx").ConnectError("down", request=request)

    import httpx as _hx
    monkeypatch.setattr(http_client, "get_async_client", lambda: _hx.AsyncClient(transport=_hx.MockTransport(dead)))
    b = TestClient(fx.make_app()).get("/api/data/health").json()
    assert b["status"] == "degraded" and b["data_service"]["reachable"] is False and b["controller_online"] is False
    assert all(row["state"] == "red" for row in b["rows"]) and b["ok"] is False and rec.requests == []


# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
# G6: zero outbound calls on the request path
# ══════════════════════════════════════════════════════════════════════════════════════════════════════════════
def test_request_path_never_leaves_the_loopback(client: TestClient, rec: fx.Recorder, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import routers.positions as pos
    monkeypatch.setattr(pos, "_get_breeze_client", _no_session)
    monkeypatch.setenv(osr.SPAN_DIR_ENV, str(fx.span_zip(tmp_path)))

    async def cash() -> dict[str, Any]:
        return fx.DESK_STATUS_CASH

    monkeypatch.setattr(mk, "_desk_status", cash)
    for path, params in (("/api/derivatives/iv/NIFTY", {}), ("/api/derivatives/iv/NIFTY/surface", {"compare": "1m"}), ("/api/derivatives/iv/NIFTY/cone", {}),
                         ("/api/derivatives/iv/INFY/events", {}), ("/api/derivatives/iv/NIFTY/intraday", {}), ("/api/derivatives/vol-screen", {}),
                         ("/api/market/index-drivers", {}), ("/api/market/index-drivers/timeline", {}), ("/api/market/index-drivers/monthly", {}),
                         ("/api/desk/attribution", {}), ("/api/data/health", {}), ("/api/market/option-history/NIFTY", {})):
        assert client.get(path, params=params).status_code == 200, path
    assert client.post("/api/options/margin", json={"symbol": "NIFTY", "legs": fx.CONDOR_LEGS}).status_code == 200
    assert rec.requests, "the fake transport saw nothing — the recorder is not wired"
    assert rec.hosts() <= {"localhost", "127.0.0.1"}, rec.hosts()
    assert not any("nseindia" in h or "yahoo" in h or "icicidirect" in h for h in rec.hosts())
    # negative control: the recorder DOES see a publisher host when one is reached through the same client
    import asyncio

    from shared.http_client import UpstreamError, get_json

    async def reach_publisher() -> None:
        with pytest.raises(UpstreamError):
            await get_json("https://www.nseindia.com/api/option-chain-v3?symbol=NIFTY", route="live")

    asyncio.run(reach_publisher())
    assert "www.nseindia.com" in rec.hosts()


def test_routers_name_no_publisher_host() -> None:
    import re
    forbidden = ("www.cmegroup.com", "mcxindia.com", "kitco.com", "prices.lbma.org.uk", "stooq.com", "goldprice.org", "investing.com",
                 "query1.finance.yahoo.com", "query2.finance.yahoo.com", "yfinance")
    url_host = re.compile(r"https?://([A-Za-z0-9.\-]+)")
    for name in ("derivatives.py", "data_health.py", "options_strategy.py"):
        text = (Path(drv.__file__).parent / name).read_text(encoding="utf-8")
        for frag in forbidden:
            assert frag not in text, (name, frag)
        hosts = {h.lower() for h in url_host.findall(text)}
        assert hosts <= {"nsearchives.nseindia.com", "localhost", "127.0.0.1"}, (name, hosts)   # the SPAN file's documented origin only
    text = Path(mk.__file__).read_text(encoding="utf-8")
    for frag in forbidden:
        assert frag not in text, ("markets.py", frag)
