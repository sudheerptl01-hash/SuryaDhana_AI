"""Yahoo quote change: previous close is the last session *before* the live price's session."""
import calendar

from routers.news_scanner import _quote_from

KST = 9 * 3600


def _ts(day: str, hhmm: str = "00:00", off: int = KST) -> int:
    """Exchange-local day + time → epoch seconds."""
    y, m, d = map(int, day.split("-"))
    h, mi = map(int, hhmm.split(":"))
    return calendar.timegm((y, m, d, h, mi, 0)) - off


def _bar(day: str, close: float) -> dict:
    return {"time": _ts(day, "09:00"), "open": close, "high": close, "low": close, "close": close, "volume": 0}


def test_today_bar_missing_uses_last_bar():
    # KOSPI 13 Oct 2026: Yahoo's 13 Oct daily bar had no close, so candles end on 12 Oct (9 Oct was a holiday)
    candles = [_bar("2026-10-08", 6625.93), _bar("2026-10-12", 6384.24)]
    meta = {"regularMarketPrice": 6035.35, "regularMarketTime": _ts("2026-10-13", "15:30"), "gmtoffset": KST}
    q = _quote_from({"meta": meta}, candles)
    assert q["prev_close"] == 6384.24
    assert round(q["change_pct"], 2) == -5.46
    assert (q["prev_date"], q["market_date"]) == ("2026-10-12", "2026-10-13")


def test_today_bar_present_uses_the_one_before():
    candles = [_bar("2026-10-12", 6384.24), _bar("2026-10-13", 6035.35)]
    meta = {"regularMarketPrice": 6035.35, "regularMarketTime": _ts("2026-10-13", "15:30"), "gmtoffset": KST}
    assert _quote_from({"meta": meta}, candles)["prev_close"] == 6384.24


def test_closed_market_shows_its_last_session_change():
    # Saturday: the last print is Friday's close, and Friday's bar is there → change is Friday's
    candles = [_bar("2026-10-08", 100.0), _bar("2026-10-09", 102.0)]
    meta = {"regularMarketPrice": 102.0, "regularMarketTime": _ts("2026-10-09", "15:30"), "gmtoffset": KST}
    q = _quote_from({"meta": meta}, candles)
    assert q["prev_close"] == 100.0 and round(q["change_pct"], 2) == 2.0
