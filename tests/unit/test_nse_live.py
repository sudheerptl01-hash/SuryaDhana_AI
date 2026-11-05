"""MOV page (services/data-service/nse_live.py): NSE live-analysis parsers."""
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "data-service"))
import nse_live as nl  # noqa: E402


def test_variations_per_universe_and_turnover_in_crore():
    payload = {"FOSec": {"data": [{"symbol": "DELHIVERY", "ltp": 419.6, "prev_price": 400.5, "perChange": 4.77, "open_price": 400.95,
                                   "high_price": 424.5, "low_price": 400.95, "trade_quantity": 5713205, "turnover": 23974.89}]},
               "NIFTY": {"data": []}}
    rows = nl.parse_variations(payload, "FOSec")
    assert rows[0]["symbol"] == "DELHIVERY" and rows[0]["change_pct"] == 4.77
    assert rows[0]["value_cr"] == pytest.approx(239.7489)                     # ₹ lakh → ₹ cr
    assert nl.parse_variations(payload, "NIFTY") == [] and nl.parse_variations({}, "FOSec") == []


def test_active_volume_52w_oi_and_indices():
    act = nl.parse_active({"data": [{"symbol": "X", "lastPrice": 63.58, "pChange": 1.91, "totalTradedVolume": 1.8e8, "totalTradedValue": 1.1452e10}]})
    assert act[0]["value_cr"] == pytest.approx(1145.2)
    vol = nl.parse_volume_gainers({"data": [{"symbol": "G", "volume": 13125150, "week1volChange": 184.87, "turnover": 74584.98, "pChange": 13.55}]})
    assert vol[0]["vs_week"] == 184.87 and vol[0]["value_cr"] == pytest.approx(745.8498)
    hi = nl.parse_52w({"high": 61, "data": [{"symbol": "AEROFLEX", "comapnyName": "Aeroflex", "ltp": 588, "new52WHL": 599, "pChange": 12.97}]})
    assert hi["count"] == 61 and hi["rows"][0]["company"] == "Aeroflex" and hi["rows"][0]["new_level"] == 599
    assert nl.parse_52w({"low": 88, "data": []})["count"] == 88
    oi = nl.parse_oi_spurts({"data": [{"symbol": "A", "avgInOI": 5.0}, {"symbol": "B", "avgInOI": 37.1, "changeInOI": 31886}]})
    assert [r["symbol"] for r in oi] == ["B", "A"]
    idx = nl.parse_indices({"data": [
        {"key": "SECTORAL INDICES", "index": "NIFTY IT", "last": 30000, "percentChange": 1.2, "advances": "7", "declines": "3"},
        {"key": "STRATEGY INDICES", "index": "NIFTY ALPHA 50"}]})
    assert len(idx) == 1 and idx[0]["advances"] == 7 and idx[0]["change_pct"] == 1.2


def test_market_hours():
    assert nl.market_open(datetime(2026, 10, 12, 11, 0))
    assert not nl.market_open(datetime(2026, 10, 12, 9, 10))
    assert not nl.market_open(datetime(2026, 10, 11, 11, 0))                    # Sunday


def test_heatmap_rows_value_in_crore_and_series_filter():
    rows = [{"symbol": "HDFCBANK", "series": "EQ", "lastPrice": "705.6", "pChange": "-0.23", "VWAP": "707.77", "quantityTraded": "6364400192.99"},
            {"symbol": "XYZ", "series": "SM", "lastPrice": "10", "pChange": "1"}, {"series": "EQ"}]
    q = nl.parse_heatmap(rows)
    assert list(q) == ["HDFCBANK"] and q["HDFCBANK"]["change_pct"] == -0.23
    assert q["HDFCBANK"]["value_cr"] == pytest.approx(636.44, abs=0.01)


@pytest.mark.parametrize("subject,text,cat", [
    ("Certificate under SEBI (Depositories and Participants) Regulations, 2018", "", "routine"),
    ("Outcome of Board Meeting", "Gammon India Limited has submitted to the Exchange, the financial results for the period", "results"),
    ("Outcome of Board Meeting", "approved the appointment of Mr X as director", "people"),
    ("Bagging/Receiving of orders/contracts", "", "orders"),
    ("Credit Rating- Revision", "", "rating"),
    ("Amalgamation/Merger", "", "m&a"),
    ("Record Date", "interim dividend", "capital"),
    ("Press Release", "", "press"),
    ("Spurt in Volume", "", "other"),
    # 12 Oct 2026: earnings-call notices were counted as results (ICICIBANK, JIOFIN, INDIANB)
    ("Analysts/Institutional Investor Meet/Con. Call Updates", "Earnings call on financial results for the quarter and six months", "analyst"),
    ("General Updates", "ICICI Bank Limited has informed the Exchange about Call with media on financial results", "press"),
    ("Integrated Filing- Governance", "", "routine"),
    ("Integrated Filing- Financial", "", "results"),
    ("Reasons for Delayed/Non-submission of Financial Results", "", "other"),
    ("Financial Result Updates", "", "results"),
    ("Outcome of Board Meeting", "Unaudited standalone and consolidated financial results of the Bank, for the quarter and half year", "results"),
    ("Board Meeting Intimation", "to consider and approve the financial results for the quarter", "board"),
])
def test_filing_category(subject, text, cat):
    assert nl.filing_category(subject, text) == cat


def test_parse_announcements_sorts_newest_first_and_drops_blank_symbols():
    rows = [{"symbol": "A", "sort_date": "2026-10-12 10:00:00", "desc": "Press Release", "attchmntFile": "x.pdf"},
            {"symbol": "B", "sort_date": "2026-10-12 11:00:00", "desc": "Credit Rating- Revision"}, {"desc": "x"}]
    out = nl.parse_announcements(rows)
    assert [x["symbol"] for x in out] == ["B", "A"] and out[1]["pdf"] == "x.pdf" and out[0]["category"] == "rating"


def test_sast_disclosure_is_insider_not_mna():
    assert nl.filing_category("Disclosure under SEBI Takeover Regulations", "Regulation 10 (5) ... Substantial Acquisition") == "insider"
    assert nl.filing_category("Open Offer", "") == "m&a"


def test_circuit_breaker_serves_stale_copy_and_backs_off(monkeypatch):
    monkeypatch.setattr(nl, "market_open", lambda now=None: True)    # in-session TTLs, whatever the time of day
    calls = []

    class Resp:
        def __init__(self, code):
            self.status_code = code
        def json(self):
            return {"ok": True}
        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(str(self.status_code))

    class Client:
        def __init__(self):
            self.code = 200
        def get(self, url, **kw):
            calls.append(url)
            return Resp(self.code if "api" in url else 200)

    feed = nl.NseLive({})
    c = Client()
    feed._client, feed._warm = c, 1e18                      # skip the cookie warm-up
    assert feed.get("x", ttl_open=0) == {"ok": True}        # first fetch caches
    c.code = 429
    assert feed.get("x", ttl_open=0) == {"ok": True}        # throttled → stale copy, breaker trips
    assert feed.blocked_until > 0
    n = len(calls)
    assert feed.get("x", ttl_open=0) == {"ok": True} and len(calls) == n   # no request while backing off
    with pytest.raises(RuntimeError):
        feed.get("never-cached", ttl_open=0)


def test_gift_nifty_implied_gap():
    status = {"giftnifty": {"LASTPRICE": 22369.5, "DAYCHANGE": -1, "PERCHANGE": 0, "EXPIRYDATE": "27-Oct-2026",
                            "TIMESTMP": "12-Oct-2026 18:11", "CONTRACTSTRADED": 50419},
              "marketState": [{"market": "Capital Market", "marketStatus": "Closed", "last": 22363.35}]}
    g = nl.parse_gift_nifty(status)
    assert g["last"] == 22369.5 and g["nifty_last"] == 22363.35 and g["time"] == "12-Oct-2026 18:11"
    assert g["implied_gap_pct"] == pytest.approx(0.03, abs=0.01)
    assert nl.parse_gift_nifty({})["implied_gap_pct"] is None


def test_index_quote_from_all_indices():
    payload = {"timestamp": "13-Oct-2026 09:56:00", "data": [
        {"index": "NIFTY BANK", "last": 1}, {"index": "NIFTY 50", "last": 22579.35, "variation": 216.0, "percentChange": 0.97,
                                             "open": 22450, "high": 22600, "low": 22440, "previousClose": 22363.35}]}
    q = nl.parse_index_quote(payload)
    assert q["last"] == 22579.35 and q["change_pct"] == 0.97 and q["previous_close"] == 22363.35 and q["time"] == "13-Oct-2026 09:56:00"
    assert nl.parse_index_quote({})["last"] is None


def test_symbol_chart_buckets_normal_market_into_ohlc():
    from nse_live import parse_symbol_chart
    base = 1791882900_000                    # 2026-10-13 09:15:00 IST-as-UTC
    payload = {"closePrice": 1223, "grapthData": [
        [base - 300_000, 1280, "PO"],        # pre-open point: dropped
        [base, 1245.4, "NM"], [base + 59_000, 1248.6, "NM"], [base + 119_000, 1240.0, "NM"],
        [base + 299_000, 1250.0, "NM"],      # still the 09:15 bar
        [base + 300_000, 1251.0, "NM"]]}     # 09:20 bar
    out = parse_symbol_chart(payload, 5)
    assert out["day"] == "2026-10-13" and out["previous_close"] == 1223
    a, b = out["rows"]
    assert a["date"] == "2026-10-13 09:15:00" and a["ts"] == base // 1000
    assert (a["open"], a["high"], a["low"], a["close"]) == (1245.4, 1250.0, 1240.0, 1250.0)
    assert b["date"] == "2026-10-13 09:20:00" and b["open"] == b["close"] == 1251.0
    assert parse_symbol_chart({"grapthData": []})["rows"] == []


def test_index_chart_drops_unlabelled_points_before_the_open():
    from nse_live import parse_symbol_chart
    base = 1791882900_000                    # 09:15 IST-as-UTC
    out = parse_symbol_chart({"closePrice": 100, "grapthData": [[base - 60_000, 99.0, "NM"], [base, 101.0, "NM"]]}, 1)
    assert [r["close"] for r in out["rows"]] == [101.0]


def test_parse_actions_dividends_specials_and_ttm():
    rows = [{"subject": "Interim Dividend Rs 11 Per Share/ Special Dividend Rs 46 Per Share", "exDate": "16-Jan-2026"},
            {"subject": "Dividend - Rs 31 Per Share", "exDate": "25-May-2026"},
            {"subject": "Interim Dividend - Rs 11 Per Share", "exDate": "15-Oct-2025"},
            {"subject": "Buy Back", "exDate": "24-Nov-2023"},
            {"subject": "Interim Dividend - Rs 9 Per Share", "exDate": "19-Oct-2023"}]
    out = nl.parse_actions(rows, datetime(2026, 10, 13))
    assert out["items"][0]["ex_date"] == "2026-05-25"
    special = [i for i in out["items"] if i["special"]][0]
    assert special["rs_per_share"] == 57.0                       # interim 11 + special 46
    assert out["ttm_dividend"] == 99.0                           # 11 (15 Oct 25) + 57 + 31
    assert out["by_fy"]["FY27"] == 31.0 and out["by_fy"]["FY26"] == 68.0
    assert [i["kind"] for i in out["items"]].count("buyback") == 1


def test_parse_actions_withholds_ttm_after_a_split():
    rows = [{"subject": "Face Value Split (Sub-Division) - From Rs 10/- Per Share To Rs 2/- Per Share", "exDate": "01-Mar-2026"},
            {"subject": "Dividend - Rs 5 Per Share", "exDate": "01-Jan-2026"}]
    out = nl.parse_actions(rows, datetime(2026, 10, 13))
    assert out["ttm_dividend"] is None and out["ttm_reshaped"] is True
    assert out["items"][0]["kind"] == "split" and out["items"][0]["rs_per_share"] is None


def test_chart_drops_the_closing_session():
    from nse_live import parse_symbol_chart
    base = 1791882900_000                    # 09:15 IST-as-UTC
    last = base + (6 * 3600 + 14 * 60) * 1000   # 15:29
    post = base + (6 * 3600 + 25 * 60) * 1000   # 15:40 closing session
    out = parse_symbol_chart({"grapthData": [[base, 1.0, "NM"], [last, 2.0, "NM"], [post, 9.0, "NM"]]}, 1)
    assert [r["close"] for r in out["rows"]] == [1.0, 2.0]


def test_fresh_nse_print_outside_the_calendar():
    """Desktop round 4b (R10): an NSE print under 5 min old means NSE is printing, whatever the calendar says."""
    from datetime import timedelta, timezone
    ist = timezone(timedelta(hours=5, minutes=30))
    now = datetime(2026, 11, 8, 18, 20, tzinfo=ist)                  # Sun 8 Nov 2026, Muhurat evening
    assert nl.fresh_nse_print("08-Nov-2026 18:19", now) and nl.fresh_nse_print("08-Nov-2026 18:16:05", now)
    assert not nl.fresh_nse_print("08-Nov-2026 18:14", now)            # 6 min: the session is over (or paused)
    assert not nl.fresh_nse_print("06-Nov-2026 15:30", now) and not nl.fresh_nse_print("08-Nov-2026 18:25", now)
    assert not nl.fresh_nse_print(None, now) and not nl.fresh_nse_print("garbage", now)
    assert not nl.market_open(now.replace(tzinfo=None))                 # the calendar alone says closed


def test_index_quote_is_re_read_every_15_s_while_nse_prints(monkeypatch):
    from datetime import timedelta, timezone
    live = nl.NseLive({})
    seen = []

    def fake_get(path, ttl_open=30, ttl_closed=600):
        seen.append(ttl_closed)
        return live._cache.get(path, (0, {}))[1]

    monkeypatch.setattr(live, "get", fake_get)
    stamp = datetime.now(timezone(timedelta(hours=5, minutes=30))).strftime("%d-%b-%Y %H:%M:%S")
    live._cache["allIndices"] = (0, {"timestamp": stamp, "data": [{"index": "NIFTY 50", "last": 24180.5}]})
    assert live.index_quote()["last"] == 24180.5
    assert seen[-1] == 15                                               # NSE printing: re-read every 15 s
    live._cache["allIndices"] = (0, {"timestamp": "23-Oct-2026 15:30", "data": []})
    live.index_quote()
    assert seen[-1] == 300                                              # a past session: 5 min as before
    live._cache.clear()
    live.index_quote()
    assert seen[-1] == 300                                              # nothing cached yet: as before
