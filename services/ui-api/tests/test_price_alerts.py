"""Server-side price alerts (routers/alerts.py): crossing logic and the HTTP round trip on a temp store."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import alerts


def test_check_levels_fires_once_and_keeps_the_other_side():
    left, hits = alerts.check_levels({"TCS": {"above": 2200, "below": 2050, "yahoo": "TCS.NS"}, "INFY": {"below": 1400}},
                                     {"TCS": 2210.0, "INFY": None}, now="t")
    assert hits == [{"sym": "TCS", "side": "above", "level": 2200, "price": 2210.0, "at": "t"}]
    assert left == {"TCS": {"below": 2050, "yahoo": "TCS.NS"}, "INFY": {"below": 1400}}
    left2, hits2 = alerts.check_levels(left, {"TCS": 2000.0})
    assert [h["side"] for h in hits2] == ["below"] and "TCS" not in left2


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ALERTS_PATH", str(tmp_path / "a.json"))
    app = FastAPI()
    app.include_router(alerts.router, prefix="/api/alerts")
    return TestClient(app)


def test_put_get_delete_round_trip(client):
    assert client.get("/api/alerts").json() == {"alerts": {}, "history": []}
    r = client.put("/api/alerts/TCS", json={"above": 2200})
    assert r.json()["alerts"]["TCS"] == {"above": 2200.0, "yahoo": "TCS.NS"}
    client.put("/api/alerts/TCS", json={"above": 2200, "below": 2000})
    assert client.get("/api/alerts").json()["alerts"]["TCS"]["below"] == 2000.0
    client.put("/api/alerts/TCS", json={"above": None, "below": None})
    assert client.get("/api/alerts").json()["alerts"] == {}
    assert client.put("/api/alerts/BAD%20SYM", json={"above": 1}).status_code == 400
    assert client.put("/api/alerts/TCS", json={"above": -5}).status_code == 422


def test_run_fires_with_stubbed_quotes(client, monkeypatch):
    from routers import news_scanner

    async def fake_quotes(symbols: str, fresh: bool = False):
        assert fresh is True                                  # the check decides on prices: fresh quotes only
        return {"quotes": {s: {"available": True, "price": 2300.0} for s in symbols.split(",")}}
    monkeypatch.setattr(news_scanner, "get_quotes", fake_quotes)
    client.put("/api/alerts/TCS", json={"above": 2200, "below": 1900})
    out = client.post("/api/alerts/run").json()
    assert [h["side"] for h in out["hits"]] == ["above"] and out["priced"] == 1
    state = client.get("/api/alerts").json()
    assert state["alerts"]["TCS"] == {"below": 1900.0, "yahoo": "TCS.NS"} and state["history"][0]["sym"] == "TCS"


def test_stock_news_terms():
    from routers.markets import _news_terms
    q, must = _news_terms("TCS", "Tata Consultancy Services Limited")
    assert q.startswith('"Tata Consultancy Services"') and must == "TCS|Tata"
    q2, must2 = _news_terms("XYZ", None)
    assert q2.startswith("XYZ") and must2 == "XYZ"


def test_setup_checks_never_echo_secrets():
    from routers.config import setup_checks
    env = {"TELEGRAM_BOT_TOKEN": "123:Zq9TokenValue", "TELEGRAM_CHAT_ID": "8877665", "ICICI_TOTP_SECRET": ""}
    out = setup_checks(env, False, {"reason": "ICICI rejected the login: Invalid Credentials"}, None)
    flat = str(out)
    assert "Zq9TokenValue" not in flat and "8877665" not in flat
    by = {c["key"]: c for c in out}
    assert by["telegram"]["ok"] and not by["totp"]["ok"] and not by["icici_credentials"]["ok"]
    ok = setup_checks({}, True, None, {"status": "valid", "at": "2026-10-12T11:33:30", "detail": "current token still works"})
    assert {c["key"]: c["ok"] for c in ok} == {"telegram": False, "totp": True, "icici_credentials": True}


def test_parse_fomc_years_and_cross_month_meetings():
    from routers.markets import parse_fomc
    html = ("<h4>2026 FOMC Meetings</h4>"
            '<div class="fomc-meeting__month"><strong>October</strong></div><div class="fomc-meeting__date">27-28</div>'
            '<div class="fomc-meeting__month"><strong>December</strong></div><div class="fomc-meeting__date">8-9*</div>'
            "<h4>2025 FOMC Meetings</h4>"
            '<div class="fomc-meeting__month"><strong>Apr/May</strong></div><div class="fomc-meeting__date">30-1</div>')
    rows = parse_fomc(html)
    assert [r["end"] for r in rows] == ["2025-05-01", "2026-10-28", "2026-12-09"]
    assert rows[0]["start"] == "2025-04-30" and rows[2]["projections"] and not rows[1]["projections"]


def test_notification_feed_newest_first(client, tmp_path):
    import json
    p = tmp_path / "notifications.jsonl"
    p.write_text("\n".join(json.dumps({"at": f"2026-10-12T1{i}:00:00+05:30", "kind": "move", "title": "t", "body": f"b{i}"})
                           for i in range(3)) + "\nnot json\n")
    items = client.get("/api/alerts/feed").json()["items"]
    assert [x["body"] for x in items] == ["b2", "b1", "b0"]


def test_last_known_holdings_round_trip(tmp_path, monkeypatch):
    import routers.positions as pos
    monkeypatch.setattr(pos, "_last_holdings_path", lambda: tmp_path / "last_holdings.json")
    assert pos._last_known() is None
    pos._remember_holdings([{"symbol": "CUPID", "quantity": 200, "buy_price": 355.5, "invested": 71100.0, "pnl": 9}])
    lk = pos._last_known()
    assert lk["positions"] == [{"symbol": "CUPID", "quantity": 200, "buy_price": 355.5, "invested": 71100.0}] and lk["as_of"]


def test_move_alert_fires_on_a_big_day_either_way():
    lv = {"TCS": {"move": 3.0, "yahoo": "TCS.NS"}, "INFY": {"move": 3.0, "above": 2000}, "HDFC": {"move": 3.0}}
    left, hits = alerts.check_levels(lv, {"TCS": 2269.3, "INFY": 1062.1, "HDFC": 714.0},
                                     now="t", changes={"TCS": 6.79, "INFY": -4.1, "HDFC": 1.29})
    assert sorted((h["sym"], h["side"], h["change_pct"]) for h in hits) == [("INFY", "move", -4.1), ("TCS", "move", 6.79)]
    assert "TCS" not in left                                  # nothing else set → dropped
    assert left["INFY"] == {"above": 2000}                    # one-shot: the move level is used up
    assert left["HDFC"]["move"] == 3.0                        # +1.3% < 3%: still waiting


def test_setting_price_levels_keeps_a_move_alert():
    alerts.set_alert("TCS", alerts.Levels(move=3.0))
    d = alerts.set_alert("TCS", alerts.Levels(above=2400.0, below=None))     # WTCH 🔔 sends only above / below
    assert d["alerts"]["TCS"]["move"] == 3.0 and d["alerts"]["TCS"]["above"] == 2400.0
    d = alerts.set_alert("TCS", alerts.Levels(above=None, below=None, move=None))   # explicit nulls clear everything
    assert "TCS" not in d["alerts"]
