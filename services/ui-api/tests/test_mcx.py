"""MCXG desk (W4): session clock (holidays, 23:30/23:55 edge), expiry cycle, tick-value
and cost math, and the degrade-first Breeze quote path — all offline (master + Yahoo mocked)."""
from datetime import date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.gold_preopen as gp
import routers.mcx as mcx
from shared import mcx_specs as specs

IST = specs.IST

HEADER = ('"Token","InstrumentName","ShortName","Series","CompanyName","TickSize","LotSize","ExpiryDate","OptionType",'
          '"StrikePrice","StartDate","EndDate","ExpiryMonth","MarketLot","MarginPercentage","LowerCktLimit","UpperCktLimit",'
          '"OpenInterest","LifeTimeLow","LifeTimeHigh","LowPriceRange","HighPriceRange","QuantityUnit","PriceUnit",'
          '"DeliveryUnit","Exchange","ExchangeCode"\n')
ROWS = ('"495213","FUTSTK","GOLD","FUTURE","GOLD",100,1,"04-Dec-2026","XX",0,"","","","",16574,"","","","","",144630,153576,"KGS","RS/10GRMS","KGS","","GOLD"\n'
        '"559933","FUTSTK","GOLD","FUTURE","GOLD",100,1,"05-Feb-2027","XX",0,"","","","",519,"","","","","",146640,155710,"KGS","RS/10GRMS","KGS","","GOLD"\n'
        '"580006","OPTSTK","GOLD","OPTION","GOLD",50,1,"30-Oct-2026","CE",116500,"","","","",0,"","","","","",6049.5,59227,"KGS","RS/10GRMS","KGS","","GOLD"\n'
        # ICICI truncates ShortName to 6 chars in the real master (GOLDMI/GOLDPE/GOLDGU; GOLDTE = Gold Ten, not on this desk)
        '"111","FUTSTK","GOLDMI","FUTURE","GOLDM",100,1,"05-Nov-2026","XX",0,"","","","",900,"","","","","",145000,153970,"KGS","RS/10GRMS","KGS","","GOLDM"\n'
        '"444","FUTSTK","GOLDTE","FUTURE","GOLDTEN",100,1,"05-Nov-2026","XX",0,"","","","",5,"","","","","",1450000,1539700,"KGS","RS/100GRMS","KGS","","GOLDTEN"\n'
        '"222","FUTSTK","GOLDPETAL","FUTURE","GOLDPETAL",100,1,"30-Oct-2026","XX",0,"","","","",50,"","","","","",14500,15400,"KGS","RS/1GRMS","KGS","","GOLDPETAL"\n'
        '"333","FUTSTK","GOLDGUINEA","FUTURE","GOLDGUINEA",100,1,"30-Oct-2026","XX",0,"","","","",10,"","","","","",116000,123200,"KGS","RS/8GRMS","KGS","","GOLDGUINEA"\n')
MASTER = HEADER + ROWS
PUBLISHED = date(2026, 10, 15)

# Yahoo fakes: MCX closed Wed 14 Oct 2026 23:30 IST (US daylight time); refs sit inside
# the 30-minute settlement window, "now" is the live price.
CLOSE_AT = datetime(2026, 10, 14, 23, 30, tzinfo=IST)
COMEX_REF, COMEX_NOW = 4150.0, 4200.0
INR_REF, INR_NOW = 88.0, 88.5


async def _fake_yahoo(client, symbol, rng="5d", interval="5m"):
    ref, now = (COMEX_REF, COMEX_NOW) if symbol.startswith("GC") else (INR_REF, INR_NOW)
    return {"symbol": symbol, "bars": [(CLOSE_AT - timedelta(minutes=10), ref)],
            "price": now, "time": CLOSE_AT + timedelta(hours=10)}


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    """No network, no stale caches: the master is the fixture, Yahoo is faked."""
    mcx._cache.clear()
    gp._cache.clear()
    monkeypatch.setattr(gp, "_load_mcx_master", lambda: (MASTER, PUBLISHED))
    monkeypatch.setattr(gp, "_yahoo_bars", _fake_yahoo)
    yield
    mcx._cache.clear()
    gp._cache.clear()


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(mcx.router, prefix="/api/mcx")
    return TestClient(app)


# ── session clock ────────────────────────────────────────────────────────────────

def test_normal_day_open_with_dst_close_2330():
    s = specs.session_state(datetime(2026, 10, 14, 12, 0, tzinfo=IST))   # Wed, US DST
    assert s["is_open"] and s["segment"] == "morning" and s["closes_at"].endswith("23:30:00+05:30")
    assert s["seconds_to_close"] == (23 * 60 + 30 - 12 * 60) * 60


def test_winter_close_moves_to_2355():
    s = specs.session_state(datetime(2026, 12, 2, 23, 40, tzinfo=IST))   # Wed, NY standard time
    assert s["is_open"] and s["segment"] == "evening" and s["closes_at"].endswith("23:55:00+05:30")
    assert not specs.session_state(datetime(2026, 12, 2, 23, 56, tzinfo=IST))["is_open"]


def test_after_2330_closed_and_next_open_is_9am():
    s = specs.session_state(datetime(2026, 10, 15, 23, 31, tzinfo=IST))  # Thu after the DST close
    assert not s["is_open"] and s["opens_at"] == "2026-10-16T09:00:00+05:30"


def test_weekend_closed_until_monday():
    s = specs.session_state(datetime(2026, 10, 17, 12, 0, tzinfo=IST))   # Saturday
    assert not s["is_open"] and s["weekend"] and s["opens_at"] == "2026-10-19T09:00:00+05:30"


def test_full_holiday_closed_all_day():
    s = specs.session_state(datetime(2026, 1, 26, 12, 0, tzinfo=IST))    # Republic Day
    assert not s["is_open"] and s["holiday"] == {"name": "Republic Day", "closure": "full"}
    assert s["opens_at"] == "2026-01-27T09:00:00+05:30"


def test_morning_closure_opens_at_5pm():
    at_10 = specs.session_state(datetime(2026, 10, 20, 10, 0, tzinfo=IST))   # Dussehra
    assert not at_10["is_open"] and at_10["opens_at"] == "2026-10-20T17:00:00+05:30"
    at_18 = specs.session_state(datetime(2026, 10, 20, 18, 0, tzinfo=IST))
    assert at_18["is_open"] and at_18["segment"] == "evening" and at_18["closes_at"].endswith("23:30:00+05:30")


def test_evening_closure_trades_morning_only():
    at_10 = specs.session_state(datetime(2026, 1, 1, 10, 0, tzinfo=IST))     # New Year Day
    assert at_10["is_open"] and at_10["closes_at"] == "2026-01-01T17:00:00+05:30"
    at_18 = specs.session_state(datetime(2026, 1, 1, 18, 0, tzinfo=IST))
    assert not at_18["is_open"] and at_18["opens_at"] == "2026-01-02T09:00:00+05:30"


def test_close_rule_agrees_with_gold_preopen():
    for d in (date(2026, 10, 8), date(2026, 12, 1), date(2026, 3, 9), date(2026, 11, 2)):
        assert specs.evening_close(d) == gp.mcx_close_time(d).timetz().replace(tzinfo=None)


def test_upcoming_holidays_sorted_from_today():
    rows = specs.upcoming_holidays(date(2026, 10, 15), count=3)
    assert [r["date"] for r in rows] == ["2026-10-20", "2026-11-10", "2026-11-24"]
    assert rows[0] == {"date": "2026-10-20", "day": "Tue", "name": "Dussehra", "closure": "morning"}


# ── expiry cycle ─────────────────────────────────────────────────────────────────

def test_gold_bimonthly_cycle_with_weekend_shift():
    # 5 Dec 2026 is a Saturday → Fri 4 Dec; both match the ICICI master fixture.
    assert specs.active_expiries("GOLD", date(2026, 10, 15), 3) == [
        date(2026, 12, 4), date(2027, 2, 5), date(2027, 4, 5)]
    assert specs.active_expiries("GOLD", date(2026, 10, 1), 1) == [date(2026, 10, 5)]


def test_goldm_monthly_fifth():
    assert specs.active_expiries("GOLDM", date(2026, 10, 15), 3) == [
        date(2026, 11, 5), date(2026, 12, 4), date(2027, 1, 5)]


def test_month_end_contracts_shift_for_weekends_and_morning_holidays():
    # 31 Jan 2026 = Saturday → 30 Jan; 31 Mar = Mahavir Jayanti (morning closed) → 30 Mar
    # (Zerodha/Fyers expiry bulletins); 28 Feb = Saturday → 27 Feb.
    assert specs.active_expiries("GOLDPETAL", date(2026, 1, 15), 1) == [date(2026, 1, 30)]
    assert specs.active_expiries("GOLDGUINEA", date(2026, 3, 15), 1) == [date(2026, 3, 30)]
    assert specs.active_expiries("GOLDPETAL", date(2026, 2, 16), 1) == [date(2026, 2, 27)]


# ── tick value and cost math ─────────────────────────────────────────────────────

def test_tick_values_and_multipliers():
    assert [specs.CONTRACTS[c].tick_value for c in ("GOLD", "GOLDM", "GOLDPETAL", "GOLDGUINEA")] == [100.0, 10.0, 1.0, 1.0]
    assert specs.notional("GOLD", 125_000, 1) == 12_500_000
    assert specs.notional("GOLDM", 125_000, 2) == 2_500_000
    assert specs.indicative_margin("GOLD", 125_000, 1) == pytest.approx(750_000)   # 6% indicative


def test_round_trip_cost_hand_calculation():
    c = specs.round_trip_costs("GOLD", 125_000, 1, brokerage_per_order=20.0)
    assert c["turnover_per_side"] == 12_500_000
    assert c["buy"] == {"brokerage": 20.0, "exchange_txn": 262.5, "sebi": 12.5,
                        "stamp": 250.0, "ctt": 0.0, "gst": 53.1, "total": 598.1}
    assert c["sell"] == {"brokerage": 20.0, "exchange_txn": 262.5, "sebi": 12.5,
                         "stamp": 0.0, "ctt": 1250.0, "gst": 53.1, "total": 1598.1}
    assert c["total"] == 2196.2
    assert c["breakeven_ticks"] == pytest.approx(21.96, abs=0.01)
    assert c["breakeven_price_move"] == pytest.approx(21.96, abs=0.01)
    assert c["pct_of_notional"] == pytest.approx(0.0176, abs=0.0002)
    assert c["indicative"] is True


def test_master_parse_covers_all_four_contracts():
    fam = mcx.parse_gold_family(MASTER)
    assert [r["expiry"] for r in fam["GOLD"]] == [date(2026, 12, 4), date(2027, 2, 5)]  # option row skipped
    assert fam["GOLD"][0]["settlement"] == 149_103.0
    assert fam["GOLDM"][0]["settlement"] == 149_485.0            # via ICICI's truncated "GOLDMI"
    assert fam["GOLDPETAL"][0]["settlement"] == 14_950.0
    assert fam["GOLDGUINEA"][0]["settlement"] == 119_600.0
    assert all(len(rows) == 1 for c, rows in fam.items() if c != "GOLD")   # GOLDTE (Gold Ten) skipped


# ── endpoints ────────────────────────────────────────────────────────────────────

def test_session_endpoint_shape():
    r = _client().get("/api/mcx/session")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["is_open"], bool) and body["opens_at"] and body["closes_at"]
    assert isinstance(body["upcoming_holidays"], list) and "23:30" in body["note"]
    assert body["special_sessions"][0]["date"] == "2026-11-08"


def test_specs_endpoint_merges_computed_and_observed():
    r = _client().get("/api/mcx/specs")
    assert r.status_code == 200
    body = r.json()
    gold = next(c for c in body["contracts"] if c["code"] == "GOLD")
    assert gold["tick_value"] == 100.0 and gold["lot"] == "1 kg"
    assert gold["observed_expiries"][0] == "2026-12-04"
    assert gold["computed_expiries"][0] == "2026-12-04"          # rule reproduces the master
    assert gold["front"]["settlement"] == 149_103.0
    assert gold["indicative_margin_rupees"] == round(149_103.0 * 100 * 0.06, 0)
    assert body["master"]["available"] is True


def test_specs_endpoint_degrades_without_master(monkeypatch):
    def boom():
        raise RuntimeError("file server down")
    monkeypatch.setattr(gp, "_load_mcx_master", boom)
    r = _client().get("/api/mcx/specs")
    assert r.status_code == 200
    body = r.json()
    assert body["master"]["available"] is False
    gold = next(c for c in body["contracts"] if c["code"] == "GOLD")
    assert gold["observed_expiries"] is None and gold["computed_expiries"][0] == "2026-12-04"


def test_quote_degrades_honestly_when_session_invalid(monkeypatch):
    import routers.positions as pos
    calls = {"n": 0}

    def no_session():
        calls["n"] += 1
        return None, "Could not authenticate credentials"
    monkeypatch.setattr(pos, "_get_breeze_client", no_session)
    c = _client()
    r = c.get("/api/mcx/quote", params={"contract": "GOLD"})
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False and body["ok"] is False
    assert body["error_info"]["code"] == "degraded"
    assert "session invalid" in body["reason"].lower() or "session" in body["reason"].lower()
    assert body["live_verify_pending"] is True
    assert body["expiry"] == "2026-12-04" and body["expiry_source"] == "observed"
    # fallbacks carry the desk: band settlement + COMEX×INR fair value
    assert body["fallbacks"]["band"]["settlement"] == 149_103.0
    fair = body["fallbacks"]["fair_value"]
    assert fair["fair"] == pytest.approx(149_103 * (COMEX_NOW / COMEX_REF) * (INR_NOW / INR_REF), abs=1)
    assert fair["landed"] == pytest.approx(COMEX_NOW * INR_NOW * 10 / 31.1034768, abs=1)
    assert body["best"]["source"] == "fair value (COMEX × USD/INR model)"
    # the 15 s payload cache means a second poll does not touch the broker again
    c.get("/api/mcx/quote", params={"contract": "GOLD"})
    assert calls["n"] == 1


def test_breeze_broken_shape_remembered_no_retry_storm(monkeypatch):
    import routers.positions as pos

    class BrokenBreeze:
        calls = 0

        def get_quotes(self, **kw):
            BrokenBreeze.calls += 1
            return {"Status": 500, "Error": "Object reference not set to an instance of an object"}

        def get_historical_data_v2(self, **kw):
            return {"Status": 500, "Error": "nope"}

    monkeypatch.setattr(pos, "_get_breeze_client", lambda: (BrokenBreeze(), None))
    first = mcx._breeze_quote("GOLD", date(2026, 12, 4), date(2026, 10, 15), after_open=True)
    again = mcx._breeze_quote("GOLD", date(2026, 12, 4), date(2026, 10, 15), after_open=True)
    assert first["available"] is False and "Object reference" in first["reason"]
    assert again["attempted"] is False          # remembered for 10 min
    assert BrokenBreeze.calls == 1              # zero retry storms


def test_breeze_quote_served_when_entitled(monkeypatch):
    import routers.positions as pos

    class LiveBreeze:
        def get_quotes(self, **kw):
            assert kw["exchange_code"] == "MCX" and kw["product_type"] == "futures"
            assert kw["stock_code"] == "GOLD"                    # ICICI short name, verified code
            return {"Status": 200, "Success": [{"ltp": "125500", "open": "125050", "high": "125600",
                                                "low": "124900", "previous_close": "124800",
                                                "ltt": "15-Oct-2026 20:15:00"}]}

    monkeypatch.setattr(pos, "_get_breeze_client", lambda: (LiveBreeze(), None))
    r = _client().get("/api/mcx/quote", params={"contract": "GOLD", "expiry": "2026-12-04"})
    body = r.json()
    assert body["available"] is True and "ok" not in body
    assert body["quote"]["ltp"] == 125_500.0 and body["quote"]["source"] == "ICICI Breeze"
    assert body["best"] == {"price": 125_500.0, "source": "ICICI Breeze"}


def test_breeze_falls_back_to_minute_bars_when_get_quotes_500s(monkeypatch):
    import routers.positions as pos

    class BarsOnly:
        def get_quotes(self, **kw):
            return {"Status": 500, "Error": "Object reference not set"}

        def get_historical_data_v2(self, **kw):
            return {"Status": 200, "Success": [
                {"datetime": "2026-10-15 09:00:00", "open": "125100", "close": "125150"},
                {"datetime": "2026-10-15 20:14:00", "open": "125480", "close": "125520"}]}

    monkeypatch.setattr(pos, "_get_breeze_client", lambda: (BarsOnly(), None))
    out = mcx._breeze_quote("GOLD", date(2026, 12, 4), date(2026, 10, 15), after_open=True)
    assert out["available"] is True
    assert out["quote"]["ltp"] == 125_520.0 and out["quote"]["open"] == 125_100.0
    assert out["quote"]["source"] == "ICICI Breeze (1-min bars)"


def test_overlay_premium_vs_fair(monkeypatch):
    import routers.positions as pos
    monkeypatch.setattr(pos, "_get_breeze_client", lambda: (None, "no session"))
    r = _client().get("/api/mcx/overlay", params={"contract": "GOLD", "mcx_price": 152_000})
    body = r.json()
    fair = 149_103 * (COMEX_NOW / COMEX_REF) * (INR_NOW / INR_REF)
    assert body["overlay"]["comex"]["price"] == COMEX_NOW and body["overlay"]["usdinr"]["price"] == INR_NOW
    assert body["premium"]["vs"] == "fair model"
    assert body["premium"]["rupees"] == pytest.approx(152_000 - fair, abs=1)


def test_paper_ticket_prices_and_records_nothing():
    r = _client().post("/api/mcx/ticket", json={"contract": "GOLDM", "lots": 2, "price": 125_000})
    assert r.status_code == 200
    body = r.json()
    assert body["paper"] is True and body["recorded"] is False
    assert body["notional"] == 2_500_000 and body["tick_value_position"] == 20.0
    assert body["indicative_margin"] == 150_000                   # 6% of ₹25 L
    assert body["round_trip"]["total"] == pytest.approx(
        specs.round_trip_costs("GOLDM", 125_000, 2)["total"])


def test_ticket_and_quote_validation():
    c = _client()
    assert c.post("/api/mcx/ticket", json={"contract": "SILVER", "lots": 1, "price": 100}).status_code == 422
    assert c.post("/api/mcx/ticket", json={"contract": "GOLD", "lots": 0, "price": 100}).status_code == 422
    assert c.post("/api/mcx/ticket", json={"contract": "GOLD", "lots": 1}).status_code == 422
    assert c.get("/api/mcx/quote", params={"contract": "PLATINUM"}).status_code == 422
    assert c.get("/api/mcx/quote", params={"contract": "GOLD", "expiry": "04-12-2026"}).status_code == 422
