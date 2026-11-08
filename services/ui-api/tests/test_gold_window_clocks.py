"""GOLD, the 8 Nov 2026 RCA round — one window and one clock per page (C-DATA-03, C-DATA-04, F4, F5).

Every rule here has a negative control that fails on the behaviour this round removed:

* C-DATA-03 / F4 — the KGX panel, badged "arithmetic · identity · the same window as HEALTH's", summed six Yahoo "=X"
  legs whose stored closes are start-of-day prints about a session behind gold's and DXY's. On Sun 8 Nov it said the
  dollar ADDED 0.17 % to the week HEALTH's verdict said it took 0.4 % off, and three of its legs came from rows dated
  Mon 09 Nov under a line dated "as of Fri 06 Nov". `dollar_effect` is now the one helper both views read.
* C-DATA-04 / F4 — "W" meant two things on MACRO: the KGX block used HEALTH's `window_anchor` while the driver tiles'
  tag and the six-currency table used a trailing 7 / 30 calendar days. On the M window HEALTH said "real yield +3 bp
  month to date" beside a tile tagged SUPPORTIVE on −29 bp over 30 days.
* F5 — the verdict sentence dated only its real-yield clause. "funds −1.8 % w/w (new shorts)" was the COT week
  Tue 27 Oct → Tue 3 Nov, in which gold fell 3.3 %, printed beside "gold +4.5 % week to date"; "GLD +2.9 t on the day"
  was Wed 4 Nov while the price clause was Fri 6 Nov.

Offline: test_gold's data-service fake and pinned clock (no broker, no Yahoo, no data-service), plus pure synthetic
gauges for the sentence.
"""

from __future__ import annotations

import math
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from routers import gold  # noqa: E402
from test_gold import NOW, _app, _offline  # noqa: E402,F401 — the autouse offline fakes and the app


@pytest.fixture
def client() -> Any:
    with TestClient(_app()) as c:
        yield c


# ── 1. dollar_effect: one number, from DXY_CLOSE, never a row after gold's close ─────────────────────────────────────


def _dxy(rows: list[tuple[str, float]]) -> list[dict[str, Any]]:
    return [{"report_date": d, "value": v} for d, v in rows]


def test_dollar_effect_is_minus_dln_dxy_over_golds_own_window() -> None:
    pts = _dxy([("2026-10-29", 102.04), ("2026-10-30", 101.88), ("2026-11-05", 101.606), ("2026-11-06", 102.30)])
    de = gold.dollar_effect(pts, date(2026, 10, 30), date(2026, 11, 6))
    assert de["value"] == pytest.approx(-math.log(102.30 / 101.88) * 100, abs=1e-9)
    assert de["value"] == pytest.approx(-0.411, abs=0.002) and de["dxy_pct"] == pytest.approx(0.412, abs=0.002)
    assert de["from_date"] == "2026-10-30" and de["to_date"] == "2026-11-06" and de["aligned"] is True
    assert de["source"] == "DXY_CLOSE" and de["note"] is None
    # negative control: the trailing-7-calendar-day anchor (Thu 29 Oct) is NOT the week-to-date one and gives another number
    assert gold.dollar_effect(pts, date(2026, 10, 29), date(2026, 11, 6))["value"] != pytest.approx(de["value"], abs=0.01)


def test_dollar_effect_ignores_rows_dated_after_golds_last_close() -> None:
    pts = _dxy([("2026-10-30", 101.88), ("2026-11-06", 102.30), ("2026-11-09", 104.00)])
    de = gold.dollar_effect(pts, date(2026, 10, 30), date(2026, 11, 6))
    assert de["to_date"] == "2026-11-06" and de["value"] == pytest.approx(-math.log(102.30 / 101.88) * 100, abs=1e-9)
    # negative control: reading the store's newest row (the future-dated weekend stub) would give this instead
    assert de["value"] != pytest.approx(-math.log(104.00 / 101.88) * 100, abs=0.01)


def test_dollar_effect_says_so_when_its_dates_are_not_golds() -> None:
    pts = _dxy([("2026-10-30", 101.88), ("2026-11-05", 101.606)])
    de = gold.dollar_effect(pts, date(2026, 10, 30), date(2026, 11, 6))   # gold ran to Fri, the DXY only to Thu
    assert de["value"] is not None and de["aligned"] is False
    assert "Thu 5 Nov" in de["note"] and "Fri 6 Nov" in de["note"]
    # no DXY at all: withheld with its reason, never a basket stand-in (the basket is a session behind)
    empty = gold.dollar_effect([], date(2026, 10, 30), date(2026, 11, 6))
    assert empty["value"] is None and "no DXY close stored" in empty["note"]
    # one close only: nothing to measure, said in words
    one = gold.dollar_effect(_dxy([("2026-11-06", 102.30)]), date(2026, 10, 30), date(2026, 11, 6))
    assert one["value"] is None and "no change to measure" in one["note"]
    # gold's bars missing altogether: the DXY's OWN window_anchor, so the tile and the clause stay alive (the pre-fix path)
    own = gold.dollar_effect(pts, None, None, "W", date(2026, 11, 8))
    assert own["value"] == pytest.approx(-math.log(101.606 / 101.88) * 100, abs=1e-9) and own["from_date"] == "2026-10-30"
    # the window's "then" landing on the same stored close as its "now" steps back one close and says the dates differ
    coll = gold.dollar_effect(_dxy([("2026-11-05", 101.606), ("2026-11-06", 102.30)]), date(2026, 11, 8), date(2026, 11, 8))
    assert coll["value"] == pytest.approx(-math.log(102.30 / 101.606) * 100, abs=1e-9) and coll["aligned"] is False


# ── 2. build_macro: the driver tag and the currency table on HEALTH's window (C-DATA-04) ─────────────────────────────


def _cat_rows(ids: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    return {
        sid: {"series_id": sid, "verdict": "PUBLISH", "badge": "context", "max_age_days": 9, "publisher": "fixture"}
        for sid in ids
    }


REAL_YIELD = [
    {"report_date": "2026-10-05", "value": 2.89},     # so the trailing 30-day figure exists and is NOT month to date
    {"report_date": "2026-10-29", "value": 2.63},
    {"report_date": "2026-10-30", "value": 2.60},
    {"report_date": "2026-11-02", "value": 2.62},
    {"report_date": "2026-11-03", "value": 2.65},
    {"report_date": "2026-11-04", "value": 2.64},
    {"report_date": "2026-11-05", "value": 2.60},
]
GOLD_W = [
    {"report_date": "2026-10-29", "value": 4031.40},
    {"report_date": "2026-10-30", "value": 3898.90},
    {"report_date": "2026-11-02", "value": 3950.00},
    {"report_date": "2026-11-05", "value": 4098.40},
]


def _macro(series: dict[str, list[dict[str, Any]]], window: str) -> dict[str, Any]:
    cat = _cat_rows(tuple(series) + ("COMEX_GC_FRONT",))
    return gold.build_macro(series, GOLD_W, [], [], [], None, cat, window, NOW.replace(year=2026, month=11, day=8))


def test_driver_tag_rests_on_healths_window_not_a_trailing_week() -> None:
    """Sun 8 Nov, W: week to date runs from the Fri 30 Oct close (real yield 2.60 → 2.60 = 0 bp). The trailing 7 calendar
    days ran from Thu 29 Oct (2.63 → 2.60 = −3 bp) and earned a SUPPORTIVE tag HEALTH's own gauge contradicted."""
    m = _macro({"UST_REAL_10Y": REAL_YIELD}, "W")
    d = next(x for x in m["drivers"] if x["key"] == "real_10y")
    assert d["window_from"] == "2026-10-30" and d["window_label"].startswith("week to date")
    assert d["d_window"] == pytest.approx(0.0, abs=1e-9) and d["tag"] is None      # nothing moved: no word at all
    # negative control: the trailing figure is still served, still −3 bp, and is NOT what the tag reads
    assert d["d1w"] == pytest.approx(-0.03, abs=1e-9) and d["d_window"] != pytest.approx(d["d1w"], abs=1e-6)
    assert "trailing calendar days" in d["trailing_note"]


def test_driver_window_m_is_month_to_date_not_thirty_days() -> None:
    m = _macro({"UST_REAL_10Y": REAL_YIELD}, "M")
    d = next(x for x in m["drivers"] if x["key"] == "real_10y")
    assert d["window_from"] == "2026-10-30" and d["window_label"].startswith("month to date")
    assert d["d_window"] == pytest.approx(0.0, abs=1e-9) and d["tag"] is None
    # negative control: the 30-calendar-day figure reaches back before the month and is a different number
    assert d["d1m"] is not None and d["d1m"] != pytest.approx(0.0, abs=1e-6)


def test_currency_rows_price_both_legs_on_one_date_and_carry_the_pages_window() -> None:
    """The INR row took gold from Fri 30 Oct and the rupee from Mon 2 Nov (+3.42 % where one date gives +3.15 %), and
    priced the ₹ row off a USD/INR bar keyed Mon 09 Nov while gold's last close was Fri 06 Nov."""
    inr = [
        {"report_date": "2026-10-30", "value": 95.1524},
        {"report_date": "2026-11-02", "value": 94.9050},
        {"report_date": "2026-11-05", "value": 94.4589},
        {"report_date": "2026-11-09", "value": 93.9100},   # future-dated weekend bar (session_date keys it to Monday)
    ]
    m = _macro({"USDINR_CLOSE": inr, "DXY_CLOSE": _dxy([("2026-10-30", 101.88), ("2026-11-05", 101.606)])}, "W")
    row = next(c for c in m["currencies"] if c["ccy"] == "INR")
    assert row["report_date"] == "2026-11-05"
    # the price is gold's Thu 5 Nov close × the rupee's Thu 5 Nov close, in ₹/10 g
    assert row["price"] == pytest.approx(4098.40 * 94.4589 * 10 / gold.GRAMS_PER_TROY_OZ, rel=1e-6)
    # negative control: the Mon 09 Nov rupee (the row the store holds but gold's date does not reach)
    assert row["price"] != pytest.approx(4098.40 * 93.91 * 10 / gold.GRAMS_PER_TROY_OZ, rel=1e-6)
    one_date = (4098.40 * 94.4589) / (3898.90 * 95.1524) - 1
    assert row["d_window"] == pytest.approx(one_date * 100, abs=0.01)
    # the USD row's window column IS the KGX total, and the window is named once for the table
    usd = next(c for c in m["currencies"] if c["ccy"] == "USD")
    assert usd["d_window"] == pytest.approx(m["kgx"]["total_pct"], abs=0.01)
    cw = m["currencies_window"]
    assert cw["from_date"] == m["kgx"]["from_date"] == "2026-10-30" and cw["to_date"] == "2026-11-05"
    assert cw["trailing"]["d1w"]["days"] == 7 and cw["trailing"]["d1w"]["from_date"] == "2026-10-29"


def test_kgx_and_the_currency_table_cannot_print_two_values_for_one_week() -> None:
    dxy = _dxy([("2026-10-30", 101.88), ("2026-11-05", 101.606), ("2026-11-09", 104.00)])
    m = _macro({"DXY_CLOSE": dxy}, "W")
    kgx, usd_row = m["kgx"], next(c for c in m["currencies"] if c["ccy"] == "USD")
    assert kgx["usd_source"] == "DXY_CLOSE" and kgx["usd_to_date"] == "2026-11-05"
    assert kgx["usd_effect_pct"] == pytest.approx(-math.log(101.606 / 101.88) * 100, abs=0.01)
    assert usd_row["d_window"] == pytest.approx(kgx["total_pct"], abs=0.01)
    # negative control: the future-dated 09 Nov close is never in the split dated on gold's Thu 05 Nov
    assert kgx["usd_effect_pct"] != pytest.approx(-math.log(104.00 / 101.88) * 100, abs=0.01)


# ── 3. verdict_sentence: the price clause anchored, every other clause on its own clock (F5) ─────────────────────────


TREND = {
    "key": "trend", "state": "delayed", "change": 4.51, "value": 4074.9, "report_date": "2026-11-06",
    "window_from": "2026-10-30", "window_label": "week to date (since the Fri 30 Oct close)",
    "vs_20d_pct": -0.1, "vs_200d_pct": -9.5, "drawdown_pct": -23.4, "trend_words": "below both averages",
}
POS = {
    "key": "positioning", "state": "delayed", "value": 103614.0, "change": -1948.0, "change_pct": -1.8,
    "report_date": "2026-11-03", "week_price_chg_pct": -3.29,
}
ETF = {"key": "etf", "state": "delayed", "change": 2.85, "report_date": "2026-11-04"}
ROLL = {
    "key": "curve_roll", "state": "delayed", "value": 0.80, "annualised_pct": 5.12, "days_to_fnd": 22,
    "front": "DEC-26", "next": "FEB-27", "report_date": "2026-11-06",
}


def test_the_verdict_anchors_the_price_clause_and_dates_every_other_clock() -> None:
    v = gold.verdict_sentence([TREND, POS, ETF, ROLL], "W", {"usd_effect_pct": -0.41, "driver_label": "new shorts"})
    line = v["line"]
    assert "gold +4.5 % week to date (Fri 30 Oct close → Fri 6 Nov)" in line
    assert "funds -1.8 % w/w to Tue 3 Nov (new shorts; gold -3.3 % that week)" in line
    assert "GLD +2.9 t on Wed 4 Nov" in line
    assert line.endswith(gold.DESCRIBES)
    # the dollar clause says which way the dollar itself went, so −0.4 % and the tile's +0.41 % read as one fact
    assert "of which the dollar -0.4 % (a stronger dollar)" in line
    # the roll is silent: its curve is on the price's own day
    assert "roll DEC-26→FEB-27 costs +0.80 % (+5.1 %/yr), FND in 22 d ·" in line and "(Fri 6 Nov)" not in line
    h3 = next(c for c in v["clauses"] if c["rule_id"] == "H3")
    assert h3["report_date"] == "2026-11-03" and h3["week_price_chg_pct"] == -3.29
    h2 = next(c for c in v["clauses"] if c["rule_id"] == "H2")
    assert h2["price_from"] == "2026-10-30" and h2["price_to"] == "2026-11-06"
    # negative controls: the undated wordings this round removed
    assert "funds -1.8 % w/w (new shorts)" not in line and "GLD +2.9 t on the day" not in line
    assert "gold +4.5 % week to date (since the Fri 30 Oct close)" not in line


def test_the_verdict_dates_a_stale_curve_and_a_dollar_leg_on_another_day() -> None:
    v = gold.verdict_sentence(
        [TREND, {**ROLL, "report_date": "2026-11-04"}],
        "W",
        {"usd_effect_pct": 0.33, "usd_effect": {"to_date": "2026-11-05", "from_date": "2026-10-30"}},
    )
    assert "FND in 22 d (Wed 4 Nov)" in v["line"]                      # the curve is a session behind: dated
    assert "of which the dollar +0.3 % (a weaker dollar) (to Thu 5 Nov)" in v["line"]
    # negative control: on the price's own day neither prints a date
    v2 = gold.verdict_sentence([TREND, ROLL], "W", {"usd_effect_pct": 0.33, "usd_effect": {"to_date": "2026-11-06"}})
    assert "FND in 22 d (" not in v2["line"] and "(to Fri 6 Nov)" not in v2["line"]


def test_the_verdict_keeps_its_old_wording_when_a_gauge_carries_no_date() -> None:
    """A gauge without a report_date (the synthetic ones the older suites build) keeps the pre-fix phrasing: the dating
    is additive, never a crash and never a fabricated day."""
    v = gold.verdict_sentence(
        [{"key": "trend", "state": "delayed", "change": -2.8, "window_label": "5 sessions"},
         {"key": "positioning", "state": "delayed", "value": 104206, "change": -2883, "change_pct": -2.7},
         {"key": "etf", "state": "delayed", "change": -12.0}],
        "W",
        {"usd_effect_pct": -1.4, "driver_label": "long liquidation"},
    )
    assert "gold -2.8 % 5 sessions" in v["line"] and "funds -2.7 % w/w (long liquidation)" in v["line"]
    assert "GLD -12.0 t on the day (notable)" in v["line"] and v["line"].endswith(gold.DESCRIBES)


def test_live_health_and_macro_agree_on_the_window_and_the_dollar(client: TestClient) -> None:
    """The whole chain on the served payloads: one window label, one window start, one dollar effect, per window."""
    for window in ("D", "W", "M"):
        h = client.get("/api/gold/health", params={"window": window}).json()
        m = client.get("/api/gold/macro", params={"window": window}).json()
        trend = next(g for g in h["gauges"] if g["key"] == "trend")
        dollar = next(g for g in h["gauges"] if g["key"] == "dollar")
        # the gold-move panels (KGX, the currency table) take gold's own window; the per-series tiles take the same
        # `window_anchor` on the same series, so a MACRO tile and its HEALTH gauge can no longer label one week two ways
        assert m["kgx"]["from_date"] == trend["window_from"], window
        assert m["kgx"]["window_label"] == trend["window_label"], window
        assert m["currencies_window"]["label"] == trend["window_label"], window
        assert m["currencies_window"]["to_date"] == trend["report_date"], window
        gauge_by_series = {g.get("series_id"): g for g in h["gauges"]}
        checked = 0
        for d in m["drivers"]:
            gg = gauge_by_series.get(d.get("series_id"))
            if gg and d.get("window_label") and gg.get("window_label"):
                assert d["window_label"] == gg["window_label"], (window, d["key"])
                assert d["window_from"] == gg["window_from"], (window, d["key"])
                checked += 1
        assert checked >= 2, window        # at least the real-yield and the dollar tiles were compared
        ry_g, ry_d = gauge_by_series["FRED_DFII10"], next(d for d in m["drivers"] if d["key"] == "real_10y")
        assert ry_g["change_bp"] == pytest.approx((ry_d["d_window"] or 0) * 100, abs=0.01), window
        # ONE dollar effect: the tile, the H2 clause and the split
        assert m["kgx"]["usd_effect_pct"] == pytest.approx(dollar["usd_effect_pct"], abs=0.01), window


# ── 5. round 2 (the 8 Nov checker): one rupee week per page, and a withheld leg that says the right reason ───────────


INR_WITH_A_FUTURE_ROW = [
    {"report_date": "2026-10-30", "value": 95.1524},
    {"report_date": "2026-11-02", "value": 94.9050},
    {"report_date": "2026-11-05", "value": 94.4589},
    {"report_date": "2026-11-09", "value": 93.9100},   # Yahoo's weekend stub, keyed to Monday's session
]


def test_the_driver_window_column_ends_on_golds_close_so_the_tile_and_the_kgx_rupee_leg_agree() -> None:
    """PLAN §f.6 — one quantity, one number per page. MACRO printed the rupee's week TWICE: the USD/INR tile read its own
    newest stored row (the future-dated Mon 09 Nov bar, −1.31 %) under the caption "week to date (since the Fri 30 Oct
    close)", while the KGX rupee leg — cut at gold's close — said −0.73 %. The window column now ends where gold's own
    last close does; the tile's LEVEL and date stay its newest row, so the bad row is still visible on screen."""
    m = _macro({"USDINR_CLOSE": INR_WITH_A_FUTURE_ROW}, "W")
    d = next(x for x in m["drivers"] if x["key"] == "usdinr")
    one_week = (94.4589 / 95.1524 - 1) * 100                      # Fri 30 Oct close → gold's last close, Thu 5 Nov
    assert d["d_window"] == pytest.approx(one_week, abs=0.001)
    assert d["d_window"] == pytest.approx(m["kgx"]["inr_effect_pct"], abs=0.01)   # the same number, once
    assert d["window_to"] == "2026-11-05" and d["window_from"] == "2026-10-30"
    # the tile still SHOWS the later row (level + date), and says why the window column could not use it
    assert d["value"] == 93.9100 and d["report_date"] == "2026-11-09"
    assert "Thu 5 Nov" in d["window_note"] and "Mon 9 Nov" in d["window_note"]
    # negative control: the figure the pre-fix tile printed (the Mon 09 Nov row against the Fri 30 Oct close)
    assert d["d_window"] != pytest.approx((93.91 / 95.1524 - 1) * 100, abs=0.01)


def test_a_series_that_ends_on_golds_close_keeps_its_own_newest_row_and_says_nothing() -> None:
    """Negative control for the cut: with no row after gold's close nothing changes and the tile prints no window note."""
    m = _macro({"USDINR_CLOSE": INR_WITH_A_FUTURE_ROW[:-1]}, "W")
    d = next(x for x in m["drivers"] if x["key"] == "usdinr")
    assert d["window_to"] == d["report_date"] == "2026-11-05" and d["window_note"] is None
    assert d["d_window"] == pytest.approx((94.4589 / 95.1524 - 1) * 100, abs=0.001)


def test_the_withheld_dollar_leg_names_the_reason_it_actually_hit() -> None:
    """The reason was one sentence for three different states: a window starting before the first stored DXY close read
    "only one DXY close stored up to Thu 5 Nov: no change to measure" with hundreds of them stored."""
    pts = _dxy([("2026-10-30", 101.88), ("2026-11-05", 101.606)])
    early = gold.dollar_effect(pts, date(2026, 1, 1), date(2026, 11, 6))
    assert early["value"] is None and "before the first stored DXY close" in early["note"]
    assert "Thu 1 Jan" in early["note"] and "Fri 30 Oct" in early["note"]
    # negative control: the one-row wording must NOT be used when the store holds more than one close
    assert "no change to measure" not in early["note"]
    one = gold.dollar_effect(_dxy([("2026-11-06", 102.30)]), date(2026, 10, 30), date(2026, 11, 6))
    assert one["value"] is None and "no change to measure" in one["note"]
    assert "before the first stored DXY close" not in one["note"]


# ── 8 Nov round-2 checker: the window cut must reach EVERY driver, and a leg's own SPAN must be printed ──────────────

def test_no_driver_window_reads_a_row_dated_after_today() -> None:
    """Round 1 cut the window only for the drivers the KGX split reprints (`usdinr`), so a weekend Yahoo stub still set
    the window column of every other driver. For `dxy` that is C-DATA-03 again: the DOLLAR's week +2.08 % in the tile
    against −0.41 % in the KGX split and the verdict, on one page, with nothing saying why."""
    stub = [*_dxy([("2026-10-30", 99.0), ("2026-11-06", 99.4)]), {"report_date": "2026-11-09", "value": 101.5}]
    d = next(x for x in _macro({"DXY_CLOSE": stub}, "W")["drivers"] if x["key"] == "dxy")
    assert d["window_to"] == "2026-11-06"                       # the last real session, not Monday's stub
    assert d["d_window"] == pytest.approx(0.404, abs=0.01)      # +0.4 %, the same week the KGX split prints
    assert d["window_note"] and "ahead of today" in d["window_note"]
    assert d["value"] == 101.5 and d["report_date"] == "2026-11-09"   # the stub stays VISIBLE on the tile, with its date
    # negative control: with no future row the window ends on the series' own newest point and says nothing
    clean = next(x for x in _macro({"DXY_CLOSE": _dxy([("2026-10-30", 99.0), ("2026-11-06", 99.4)])}, "W")["drivers"]
                 if x["key"] == "dxy")
    assert clean["window_to"] == "2026-11-06" and clean["window_note"] is None


def test_the_verdict_prints_the_dollar_legs_own_span_when_it_is_not_golds() -> None:
    """The clause printed only the leg's END, so a leg that STARTED elsewhere borrowed the price clause's span: 'gold
    +4.5 % week to date (Fri 30 Oct → Fri 6 Nov) · of which the dollar −0.2 %' while that −0.2 % ran from Thu 29 Oct."""
    v = gold.verdict_sentence(
        [TREND], "W",
        {"usd_effect_pct": -0.25,
         "usd_effect": {"from_date": "2026-10-29", "to_date": "2026-11-06", "aligned": False}},
    )
    assert "of which the dollar -0.2 % (a stronger dollar) (Thu 29 Oct → Fri 6 Nov)" in v["line"]
    assert "(to Fri 6 Nov)" not in v["line"]                     # the end alone would hide the differing start
    # negative control: an ALIGNED leg keeps the quiet wording (no span, no noise on the common case)
    v2 = gold.verdict_sentence(
        [TREND], "W",
        {"usd_effect_pct": -0.25, "usd_effect": {"from_date": "2026-10-30", "to_date": "2026-11-06", "aligned": True}},
    )
    clause = v2["line"][v2["line"].find("of which"):].split(" · ")[0]      # the dollar clause alone: other clauses
    assert clause == "of which the dollar -0.2 % (a stronger dollar)"      # (e.g. "roll DEC-26→FEB-27") carry arrows
