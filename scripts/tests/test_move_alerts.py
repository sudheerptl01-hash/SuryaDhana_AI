"""Move alerts (scripts/master_controller.move_alert_keys): holdings ±5/10%, NIFTY crossing its 200-day average."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
import master_controller as mc  # noqa: E402


def test_holding_levels_fire_once_each():
    first = mc.move_alert_keys({"AEROFLEX": 12.3, "CUPID": -5.5, "SYNCOMF": 0.5}, None, None, set())
    keys = [k for k, _ in first]
    assert keys == ["AEROFLEX|+5", "AEROFLEX|+10", "CUPID|-5"]
    assert "up 12.3%" in first[0][1]
    again = mc.move_alert_keys({"AEROFLEX": 12.9, "CUPID": -5.9}, None, None, set(keys))
    assert again == []


def test_nifty_cross_needs_a_starting_side():
    start = mc.move_alert_keys({}, 22_400, 24_271, set())
    assert start == [("NIFTY|below", "")]                         # silent: just remembers the opening side
    assert mc.move_alert_keys({}, 22_500, 24_271, {"NIFTY|below"}) == []
    cross = mc.move_alert_keys({}, 24_300, 24_271, {"NIFTY|below"})
    assert cross[0][0] == "NIFTY|above" and "crossed above" in cross[0][1]


def test_morning_note_puts_your_stocks_first():
    note = mc.compose_morning_note(
        {"implied_gap_pct": 0.42},
        {"^GSPC": {"available": True, "change_pct": 0.6}, "BZ=F": {"available": True, "change_pct": 1.9}, "^IXIC": {"available": False}},
        {"summary": {"latest": {"FII": -3568.9, "DII": 4743.3}, "latest_date": "2026-10-09"}},
        [{"symbol": "AEROFLEX", "kind": "OTHER", "event_date": "2026-10-14"},
         {"symbol": "HEROMOTORS", "kind": "RESULTS", "event_date": "2026-10-14", "turnover_cr": 1348},
         {"symbol": "TCS", "kind": "RESULTS", "event_date": "2026-10-15"}],
        {"AEROFLEX"}, "2026-10-14")
    assert note.startswith("GIFT NIFTY implies +0.4% at the open")
    assert "S&P +0.6%" in note and "Brent +1.9%" in note and "Nasdaq" not in note
    assert "FII -3,569 cr / DII +4,743 cr (2026-10-09)" in note
    assert "YOUR STOCKS today: AEROFLEX (board meeting)" in note and "1 results today: HEROMOTORS" in note and "TCS" not in note
    assert mc.compose_morning_note({}, {}, {}, [], set(), "2026-10-14") == "No pre-market data available."


def test_missed_jobs_after_a_late_start(tmp_path):
    from datetime import datetime
    (tmp_path / "data" / "nse_archive" / "preopen").mkdir(parents=True)
    (tmp_path / "reports" / "daily_wrap").mkdir(parents=True)
    tue_0955 = datetime(2026, 10, 13, 9, 55)
    assert mc.missed_jobs(tue_0955, tmp_path) == ["preopen_capture"]
    (tmp_path / "data" / "nse_archive" / "preopen" / "2026-10-13_FO.json").write_text("{}")
    assert mc.missed_jobs(tue_0955, tmp_path) == []
    assert mc.missed_jobs(datetime(2026, 10, 13, 8, 55), tmp_path) == ["morning_note"]
    (tmp_path / "data" / "notifications.jsonl").write_text('{"at": "2026-10-13T08:50:02+05:30", "kind": "morning"}\n')
    assert mc.missed_jobs(datetime(2026, 10, 13, 8, 55), tmp_path) == []
    assert mc.missed_jobs(datetime(2026, 10, 13, 21, 30), tmp_path) == ["daily_wrap"]
    assert mc.missed_jobs(datetime(2026, 10, 17, 10, 0), tmp_path) == []          # Saturday


def test_results_numbers_message():
    from master_controller import results_numbers_message
    f = {"period_end": "2026-09-30", "filed_at": "2026-10-12T19:38:12", "revenue_yoy": 11.5, "pat_yoy": 21.2,
         "pat_margin": 14.4, "pe": 18.1}
    assert results_numbers_message("HCLTECH", f, "2026-10-11T12:00") == \
        "HCLTECH Q2 FY27: revenue +12%, profit +21% y/y, net margin 14.4% · P/E 18.1×"
    assert results_numbers_message("HCLTECH", f, "2026-10-13T00:00") is None          # older than the window
    mar = {**f, "period_end": "2026-03-31", "pat_yoy": None, "pat_yoy_turn": "to loss", "pe": None, "pat_margin": None}
    assert results_numbers_message("X", mar, "2026-10-11T12:00") == "X Q4 FY26: revenue +12%, profit to loss y/y"


def test_morning_note_lists_overnight_results_yours_first():
    rep = [{"symbol": "HCLTECH", "revenue_yoy": 11.5, "pat_yoy": 21.2},
           {"symbol": "AGRITECH", "revenue_yoy": 34.5, "pat_yoy": None, "pat_turn": "to loss"},
           {"symbol": "ICICIAMC", "revenue_yoy": None, "pat_yoy": None}]
    note = mc.compose_morning_note({}, {}, {}, [], {"ICICIAMC"}, "2026-10-14", rep)
    assert note == ("3 reported since yesterday's close: ICICIAMC, HCLTECH (rev +11.5% / profit +21.2%), "
                    "AGRITECH (rev +34.5% / profit to loss)")


def test_morning_note_names_economic_data_due_today():
    eco = [{"date": "2026-10-14", "kind": "WPI", "what": "Wholesale inflation (WPI) · Sep 2026", "time": "12:00"},
           {"date": "2026-10-15", "kind": "CPI", "what": "CPI inflation · Sep 2026", "time": "16:00"}]   # not today: left out
    note = mc.compose_morning_note({}, {}, {}, [], set(), "2026-10-14", None, eco)
    assert note == "data today: Wholesale inflation (WPI) · Sep 2026 12:00"


def test_morning_note_leads_with_a_market_holiday():
    eco = [{"date": "2026-10-20", "kind": "HOLIDAY", "what": "NSE closed · Dussehra", "time": None},
           {"date": "2026-10-20", "kind": "CORE", "what": "Core industries index · Sep 2026", "time": "17:00"}]
    note = mc.compose_morning_note({}, {}, {}, [], set(), "2026-10-20", None, eco)
    assert note == "NSE CLOSED TODAY (Dussehra) · data today: Core industries index · Sep 2026 17:00"


def test_close_note():
    nifty = {"last": 22697.75, "change_pct": 1.5}
    internals = {"summary": {"samples": 96, "n500_adv": 335, "n500_dec": 164, "net_worst": -105, "net_best": 171,
                             "divergence": None, "small_minus_n50": -1.34}}
    book = [{"symbol": "AEROFLEX", "quantity": 100}, {"symbol": "CUPID", "quantity": 200}]
    quotes = {"AEROFLEX.NS": {"available": True, "price": 549.0, "change_pct": 5.48},
              "CUPID.NS": {"available": True, "price": 352.45, "change_pct": -3.73}}
    note = mc.compose_close_note(nifty, internals, book, quotes)
    assert note.startswith("NIFTY 22,698 (+1.50%) · NIFTY 500 breadth 335 up / 164 down (net ranged -105 to +171)")
    assert "small caps -1.34% vs NIFTY" in note
    assert note.endswith("your holdings +₹121 today (AEROFLEX +5.48%, CUPID -3.73%)")
    assert mc.compose_close_note({}, {}, [], {}) == "No closing data available."


def test_close_note_names_the_index_movers():
    contrib = {"members": [{"symbol": s, "points": p} for s, p in
                           (("TCS", 30.7), ("INFY", 30.6), ("ICICIBANK", 30.2), ("KOTAKBANK", -6.7), ("MARUTI", -1.9))]}
    note = mc.compose_close_note({"last": 22721.95, "change_pct": 1.6}, {}, [], {}, contrib)
    assert note == "NIFTY 22,722 (+1.60%) · NIFTY points: TCS +31, INFY +31, ICICIBANK +30"


def test_session_jobs_skip_an_nse_holiday(monkeypatch):
    import asyncio
    from datetime import datetime
    monkeypatch.setattr(mc, "_HOLIDAYS", {"at": 9e18, "days": {"2026-10-20": "Dussehra"}})     # fresh cache, no network
    assert asyncio.run(mc._nse_holiday(datetime(2026, 10, 20, 15, 40, tzinfo=mc.IST))) == "Dussehra"
    assert asyncio.run(mc._nse_holiday(datetime(2026, 10, 21, 15, 40, tzinfo=mc.IST))) is None


def test_morning_note_says_what_a_board_meeting_is_for():
    ev = [{"event_date": "2026-10-14", "symbol": "AEROFLEX", "kind": "OTHER",
           "detail": "To consider and approve the Company s expansion plans, including further capacity enhancements."},
          {"event_date": "2026-10-14", "symbol": "CUPID", "kind": "OTHER",
           "detail": "CUPID LIMITED has informed the Exchange about Board Meeting to be held on 14-Oct-2026."}]
    note = mc.compose_morning_note({}, {}, {}, ev, {"AEROFLEX", "CUPID"}, "2026-10-14")
    assert note.startswith("YOUR STOCKS today: AEROFLEX (board meeting: Company's expansion plans, including further capacity enhancements)")
    assert "CUPID (board meeting)" in note                                        # boilerplate: no purpose added


def test_surveillance_changes_report_only_what_moved():
    prev = {"CUPID": ["ASM LT 1"], "PCJEWELLER": ["ASM ST 1"], "AEROFLEX": []}
    now = {"CUPID": ["ASM LT 2"], "PCJEWELLER": [], "AEROFLEX": ["BAND 5%"], "SYNCOMF": []}
    assert mc.surveillance_changes(prev, now) == ["AEROFLEX added to BAND 5%", "CUPID now ASM LT 2 (was ASM LT 1)",
                                                  "PCJEWELLER out of ASM ST 1"]
    assert mc.surveillance_changes(now, now) == []
    assert mc.surveillance_changes({}, {"CUPID": ["ASM LT 1"], "TCS": []}) == ["CUPID under ASM LT 1"]   # first sighting


def test_telegram_falls_back_to_plain_text_when_markdown_is_rejected(monkeypatch):
    import asyncio
    sent = []

    class Resp:
        def __init__(self, code, text=""):
            self.status_code, self.text = code, text

    class Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, json):
            sent.append(json)
            return Resp(400, "Bad Request: can't parse entities") if "parse_mode" in json else Resp(200)

    monkeypatch.setattr(mc, "TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setattr(mc, "TELEGRAM_CHAT_ID", "1")
    monkeypatch.setattr(mc.httpx, "AsyncClient", Client)
    asyncio.run(mc.AlertDispatcher()._telegram("*[INFO]* job results_capture_daily"))
    assert len(sent) == 2 and "parse_mode" not in sent[1] and sent[1]["text"] == "[INFO] job results_capture_daily"
