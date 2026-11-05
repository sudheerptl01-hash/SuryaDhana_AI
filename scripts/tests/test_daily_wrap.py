"""Daily market wrap (scripts/daily_wrap.py): formatting helpers and section assembly on canned endpoint data."""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import daily_wrap as dw  # noqa: E402


def test_formatters():
    assert dw.inr(501042) == "₹5,01,042" and dw.inr(999) == "₹999" and dw.inr(12345678) == "₹1,23,45,678"
    assert dw.pct(-0.004) == "0.00%" and dw.pct(1.234, 1) == "+1.2%" and dw.pct(None) == "—"
    assert dw.crore(-3568.9) == "−₹3,569 cr" and dw.crore(4743.26) == "+₹4,743 cr"
    assert dw.next_weekday(date(2026, 10, 9)) == date(2026, 10, 12)      # Friday → Monday


class FakeApi(dw.Api):
    def __init__(self, data):
        self.data, self.missing = data, []

    def get(self, path, **params):
        if path not in self.data:
            self.missing.append(path)
            return None
        return self.data[path]


def test_build_marks_stale_eod_and_lists_missing_sources():
    api = FakeApi({
        "/api/market/monitor": {"as_of": "2026-10-09", "index_name": "Nifty 500", "breadth": {"adv": 844, "dec": 561},
                                "regime": {"score": 0, "exposure": "0–20%", "days_at_score": 6},
                                "sectors": [{"industry": "IT", "ret_1d_pct": 2.3}], "movers": {}},
        "/api/market/fii-dii-cash": {"summary": {"latest_date": "2026-10-12", "latest": {"FII": -100.0, "DII": 50.0}, "sessions_mtd": 1}},
        "/api/desk/status": {"latest": {"nav": 501042.0, "positions": 0, "drawdown": 0.0}, "meta": {"start_capital": 500000.0}},
    })
    md, summary = dw.build(api, date(2026, 10, 12))
    assert "⚠ End-of-day breadth is from 2026-10-09" in md
    assert "Sectors (NSE industries, equal-weighted, 1 day) · as of 2026-10-09" in md
    assert "FII −₹100 cr · DII +₹50 cr" in md and "Cash market (today" in md
    assert "NAV ₹5,01,042 (+0.21% since start)" in md
    assert "Sources that did not answer" in md and "/api/market/deals" in md
    assert "FII −₹100 cr" in summary and "regime 0/4" in summary and "breadth" not in summary   # stale breadth left out


def test_internals_lines_flag_a_narrow_rally():
    from daily_wrap import internals_lines
    sm = {"samples": 180, "first": "13-Oct-2026 09:16", "last": "13-Oct-2026 15:30", "net_worst": -120, "net_best": 95,
          "net_now": -82, "small_minus_n50": -1.31, "divergence": "narrow: NIFTY up, most stocks down"}
    out = internals_lines(sm)
    assert "09:16–15:30" in out[0] and "-120 to 95, ended -82" in out[0] and "small caps" in out[0]
    assert "Narrow: NIFTY up" in out[1]
    assert internals_lines({}) == []


def test_numbers_note_only_for_that_days_filing():
    from daily_wrap import numbers_note
    f = {"filed_at": "2026-10-13T17:05:00", "revenue_yoy": 11.46, "pat_yoy": 21.2}
    assert numbers_note(f, "2026-10-13") == ", revenue +11% / profit +21% y/y"
    assert numbers_note(f, "2026-10-14") == ""
    assert numbers_note({**f, "pat_yoy": None, "pat_yoy_turn": "to loss"}, "2026-10-13") == ", revenue +11% / profit to loss y/y"
    assert numbers_note(None, "2026-10-13") == ""


def test_concentration_line():
    from daily_wrap import concentration_line
    book = [{"symbol": "CUPID", "quantity": 200}, {"symbol": "AEROFLEX", "quantity": 100}]
    q = {"CUPID.NS": {"available": True, "price": 353.1}, "AEROFLEX.NS": {"available": True, "price": 557.6}}
    line = concentration_line(book, q)
    assert line == "- Book ₹1,26,380: CUPID 56% · AEROFLEX 44% (behaves like 2.0 equal positions)"
    assert concentration_line(book[:1], q) == ""


def test_movers_line():
    from daily_wrap import movers_line
    c = {"change": 358.6, "explained_points": 357.3, "members": [{"symbol": s, "points": p} for s, p in
         (("TCS", 30.7), ("INFY", 30.6), ("ICICIBANK", 30.2), ("HDFCBANK", 29.1), ("MARUTI", -1.9), ("KOTAKBANK", -6.7))]}
    assert movers_line(c) == ("- Who moved NIFTY (points): TCS +31 · INFY +31 · ICICIBANK +30 · drag KOTAKBANK -7 · MARUTI -2"
                              " (weights rebuilt from filings explain +357 of +359)")
    assert movers_line({}) == ""


def test_next_expiry_rolls_on_expiry_day():
    from daily_wrap import next_expiry
    opt = {"found": True, "expiry": "2026-10-13", "expiries": ["2026-10-13", "2026-10-20", "2026-10-27"]}
    assert next_expiry(opt, "2026-10-13") == "2026-10-20"
    assert next_expiry({**opt, "expiry": "2026-10-20"}, "2026-10-13") is None
    assert next_expiry({"found": False}, "2026-10-13") is None


def test_valuation_line():
    from daily_wrap import valuation_line
    ix = {"NIFTY 50": {"pe": 19.41, "pb": 2.79, "dy": 1.51}, "NIFTY MIDCAP 150": {"pe": 28.34}, "NIFTY SMALLCAP 250": {"pe": 34.39}}
    assert valuation_line(ix) == "- Valuation (NSE): NIFTY P/E 19.4× · P/B 2.79 · dividend yield 1.51% · Midcap 150 28.3× · Smallcap 250 34.4×"
    assert valuation_line({}) == ""
    from daily_wrap import ordinal
    assert [ordinal(n) for n in (1, 2, 3, 4, 11, 12, 13, 21, 22, 100, 101, 111)] == \
        ["1st", "2nd", "3rd", "4th", "11th", "12th", "13th", "21st", "22nd", "100th", "101st", "111th"]
    vs = {"NIFTY 50": {"pctl": 12, "median": 22.1, "since": "2021-03-31"}}
    assert valuation_line(ix, vs).startswith("- Valuation (NSE): NIFTY P/E 19.4× (12th percentile since Mar 2021, median 22.1×) · P/B 2.79")


def test_short_line_keeps_persistent_meaningful_shorts():
    from daily_wrap import short_line
    rows = [{"symbol": "HEROMOTOCO", "short_pct_of_volume": 4.21, "days": 4},
            {"symbol": "ONEOFF", "short_pct_of_volume": 9.0, "days": 1},        # a single day: left out
            {"symbol": "TINY", "short_pct_of_volume": 0.3, "days": 5}]          # too small a share: left out
    assert short_line(rows) == "- Institutional short selling, last 5 sessions: HEROMOTOCO 4.2% of volume (4 days)"
    assert short_line([]) == ""


def test_valuation_line_flags_a_stretched_small_cap_premium():
    from daily_wrap import valuation_line
    ix = {"NIFTY 50": {"pe": 19.41, "pb": 2.79, "dy": 1.51}, "NIFTY MIDCAP 150": {"pe": 28.3}, "NIFTY SMALLCAP 250": {"pe": 34.4}}
    rel = {"NIFTY MIDCAP 150": {"ratio": 1.46, "pctl": 63}, "NIFTY SMALLCAP 250": {"ratio": 1.77, "pctl": 99}}
    line = valuation_line(ix, None, rel)
    assert line.endswith("Midcap 150 28.3× · Smallcap 250 34.4× (1.77× NIFTY, 99th percentile)")    # mid is ordinary: no note
