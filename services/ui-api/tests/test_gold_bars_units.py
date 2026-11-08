"""`/api/gold/bars` states its unit, and the SGE bars are CONVERTED (CT-01 / F1, 8 Nov 2026).

The SGE Au99.99 quotes are stored in CNY per gram. Nothing between the store and the 24-h chart converted them, so
868.0 CNY/g was pushed into the USD/oz y-domain (stretching it to 1,000–4,000 and pressing the COMEX line flat) and
printed as "$868.00" under a panel whose own copy said "CNY/g converted to $/oz by the server".

Every rule here has a negative control:
  · the payload names its unit per symbol — and INR=X, which is a rate, is never called a gold price
  · ONE vintage per DRAWN SESSION, dated ON OR BEFORE that session's first Shanghai date: a future-dated weekend stub
    (FX_CNY 2026-11-09, written Sun 8 Nov) never prices Friday's bars, AND the vintage never changes inside a session
    (round 1 picked it per bar; a CME trade date straddles Beijing midnight, so the real 2026-11-05 session served
    native 880.0 CNY/g as both $4,110.82 and $4,092.56 — a phantom −$18.26 with no price move)
  · a session with no rate on or before it is DROPPED and COUNTED — raw yuan is never served under a USD field, and a
    short series never reads as a short store
  · hi / lo, prev_day and the daily closes are the CONVERTED numbers, with the native ones read off the SAME bar

Offline: test_gold's pinned clock and fakes; no network, no broker, no store.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from routers import gold  # noqa: E402
from test_gold import _app, _offline  # noqa: E402,F401 — the autouse offline fixture (pinned clock, no network)

# the live Fri 6 Nov 2026 prints (verify_ct01/sge_bars.json): 884.09 on the Thursday night session, 868.0 last
SGE_BARS = [
    {"ts": "2026-11-05T12:00:00", "open": 884.09, "high": 884.09, "low": 884.09, "close": 884.09, "volume": 0},
    {"ts": "2026-11-06T14:20:00", "open": 868.0, "high": 868.0, "low": 868.0, "close": 868.0, "volume": 0},
]
# FX_CNY as the store actually holds it: Thursday, Friday — and a PARTIAL row dated next Monday, written on the Sunday
CNY_PTS = [
    {"series_id": "FX_CNY", "report_date": "2026-11-05", "value": 6.6583, "release_at": "2026-11-06T02:00:00"},
    {"series_id": "FX_CNY", "report_date": "2026-11-06", "value": 6.688, "release_at": "2026-11-07T02:00:00"},
    {"series_id": "FX_CNY", "report_date": "2026-11-09", "value": 6.671, "release_at": "2026-11-08T04:47:43"},
]
FRI_USD = 4036.76        # 868.0 × 31.1034768 ÷ 6.688  (Friday's rate, NOT Monday's 6.671 → 4,047.04)
THU_USD = 4129.92        # 884.09 × 31.1034768 ÷ 6.6583

# ONE DRAWN SESSION (CME trade date 2026-11-05 = New York 18:00 → 18:00, Beijing 07:00 → 06:00) that straddles Beijing
# midnight: the same native close on either side of it. Round 1 chose the rate per bar, so these served $18.26 apart.
SESSION_BARS = [
    {"ts": "2026-11-05T12:39:00", "open": 880.0, "high": 880.0, "low": 880.0, "close": 880.0, "volume": 0},   # Beijing 11-05 20:39
    {"ts": "2026-11-05T16:00:00", "open": 880.0, "high": 880.0, "low": 880.0, "close": 880.0, "volume": 0},   # Beijing 11-06 00:00
]
SESSION_USD = 4110.82    # 880.0 × 31.1034768 ÷ 6.6583 — the session's own first-bar vintage, for BOTH bars
STEPPED_USD = 4092.56    # … what the per-bar rule printed for the bar after Beijing midnight (the phantom step)


def _fake(bars: list[dict[str, Any]], series: list[dict[str, Any]]) -> Any:
    async def fetch(path: str, params: dict[str, Any]) -> Any:
        if path == "/db/gold/bars":
            return {"rows": bars if params.get("interval") != "1d" else []}
        if path == "/db/gold/series":
            ids = set(str(params.get("ids", "")).split(","))
            return {"rows": [r for r in series if r["series_id"] in ids]}
        return {"rows": []}

    return fetch


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(gold, "_db_fetch", _fake(SGE_BARS, CNY_PTS))
    with TestClient(_app()) as c:
        yield c


# ══ the unit of every payload ═════════════════════════════════════════════════════════════════════════════════════


def test_bars_unit_names_the_unit_of_every_symbol_and_claims_none_it_does_not_know() -> None:
    assert gold.bars_unit("SGE_AU9999") == ("USD/oz", "CNY/g")
    assert gold.bars_unit("GC=F") == ("USD/oz", None) and gold.bars_unit("GCZ26.CMX") == ("USD/oz", None)
    assert gold.bars_unit("XAUUSD=X") == ("USD/oz", None)
    # negative controls: INR=X is an FX RATE, not a gold price; an unknown symbol claims no unit at all
    assert gold.bars_unit("INR=X") == ("INR per USD", None)
    assert gold.bars_unit("MCX_GOLD") == (None, None) and gold.bars_unit("") == (None, None)


def test_the_sge_payload_is_usd_per_ounce_with_the_native_price_and_the_rate_beside_it(client: Any) -> None:
    r = client.get("/api/gold/bars", params={"symbol": "SGE_AU9999", "interval": "1m"})
    assert r.status_code == 200
    p = r.json()
    assert p["unit"] == "USD/oz" and p["unit_native"] == "CNY/g" and "31.1034768" in p["conversion"]
    assert p["instrument"].startswith("SGE Au99.99")
    last = p["bars"][-1]
    assert last["c"] == FRI_USD and last["c_cny_g"] == 868.0 and last["usdcny"] == 6.688 and last["usdcny_date"] == "2026-11-06"
    assert p["bars"][0]["c"] == THU_USD and p["bars"][0]["usdcny_date"] == "2026-11-05"
    # the FX leg the page prints, from the LAST bar; the window's hi / lo are the CONVERTED numbers
    assert p["fx"]["series"] == "FX_CNY" and p["fx"]["value"] == 6.688 and p["fx"]["report_date"] == "2026-11-06"
    assert p["hi"] == FRI_USD and p["lo"] == FRI_USD and p["hi_native"] == 868.0 and p["lo_native"] == 868.0
    assert p["prev_day"][-1]["c"] == THU_USD
    # negative control: no USD field anywhere in the payload still carries a yuan-per-gram number
    assert not [b for b in p["bars"] if b["c"] is not None and b["c"] < 2000]


def test_a_future_dated_rate_never_prices_an_earlier_bar() -> None:
    """The store held FX_CNY 2026-11-09 (written Sun 8 Nov). Taking 'the latest' rate would price Friday at 4,047.04."""
    bars = gold._bar_rows({"rows": [SGE_BARS[1]]})
    out, conv = gold.sge_usd_oz_bars(bars, CNY_PTS, "FX_CNY")
    assert out[0]["c"] == FRI_USD and conv["fx"]["report_date"] == "2026-11-06" and conv["dropped_no_fx"] == 0
    # negative control: with ONLY the Monday row the bar has no rate on or before its session and is dropped, not mispriced
    dropped, no_fx = gold.sge_usd_oz_bars(bars, [CNY_PTS[2]], "FX_CNY")
    assert dropped == [] and no_fx["fx"] is None and no_fx["dropped_no_fx"] == 1 and no_fx["fx_vintages"] == []
    assert round(868.0 * gold.GRAMS_PER_TROY_OZ / 6.671, 2) == 4047.04     # what 'the latest rate' (Monday's) would print
    assert FRI_USD != 4047.04                                              # … $10 away from the honest number


def test_one_fx_vintage_per_drawn_session_so_the_line_never_steps_at_beijing_midnight() -> None:
    """A CME trade date runs Beijing 07:00 → 06:00, so it ALWAYS straddles Beijing midnight. Choosing the rate per bar
    (round 1) moved the served price without any price move: on the real stored rows the drawn session 2026-11-05 held
    both the 11-05 and the 11-06 vintage and native 880.0 CNY/g served as $4,110.82 then $4,092.56."""
    bars = gold._bar_rows({"rows": SESSION_BARS})
    assert gold._cme_trade_date(bars[0]["ts"]) == gold._cme_trade_date(bars[1]["ts"]) == "2026-11-05"
    assert gold._shanghai_day(bars[0]["ts"]) == "2026-11-05" and gold._shanghai_day(bars[1]["ts"]) == "2026-11-06"
    out, conv = gold.sge_usd_oz_bars(bars, CNY_PTS, "FX_CNY")
    # the rule: identical native close inside ONE drawn session ⇒ identical served close, at ONE named vintage
    assert [b["c"] for b in out] == [SESSION_USD, SESSION_USD]
    assert {b["usdcny_date"] for b in out} == {"2026-11-05"} and conv["fx_vintages"] == ["2026-11-05"]
    # negative control 1: that is what the old per-bar rule printed, and it is NOT what is served now
    assert round(880.0 * gold.GRAMS_PER_TROY_OZ / 6.688, 2) == STEPPED_USD
    assert out[1]["c"] != STEPPED_USD and SESSION_USD - STEPPED_USD == pytest.approx(18.26, abs=0.01)
    # negative control 2: a vintage is still never LATER than the bar's own Shanghai date, and a NEW session takes its own
    two = gold._bar_rows({"rows": [*SESSION_BARS, SGE_BARS[1]]})
    out2, conv2 = gold.sge_usd_oz_bars(two, CNY_PTS, "FX_CNY")
    assert [b["usdcny_date"] for b in out2] == ["2026-11-05", "2026-11-05", "2026-11-06"]
    assert conv2["fx_vintages"] == ["2026-11-05", "2026-11-06"] and out2[-1]["c"] == FRI_USD
    assert all(b["usdcny_date"] <= gold._shanghai_day(b["ts"]) for b in out2)


def test_each_extreme_is_ONE_bar_read_in_both_units(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Two drawn sessions inside one IST day (the Globex open is 04:30 IST) convert at different vintages, so the HIGHEST
    native bar need not be the highest served one: 887.0 ÷ 6.6583 beats 890.0 ÷ 6.688. Four independent max()/min() would
    then print one bar's `hi` beside another bar's `hi_native` as though they were one price in two units."""
    bars = [
        SESSION_BARS[0],                                                                                        # IST 11-05 18:09, session 11-05 → its vintage
        {"ts": "2026-11-05T19:00:00", "open": 887.0, "high": 887.0, "low": 887.0, "close": 887.0, "volume": 0},  # IST 11-06 00:30, session 11-05
        {"ts": "2026-11-06T04:00:00", "open": 890.0, "high": 890.0, "low": 890.0, "close": 890.0, "volume": 0},  # IST 11-06 09:30, session 11-06
    ]
    monkeypatch.setattr(gold, "_db_fetch", _fake(bars, CNY_PTS))
    gold.STORE.invalidate()
    p = client.get("/api/gold/bars", params={"symbol": "SGE_AU9999", "interval": "1m"}).json()
    assert p["day"] == "2026-11-06" and len(p["bars"]) == 3        # the last IST day holds two drawn sessions
    assert p["fx_vintages"] == ["2026-11-05", "2026-11-06"]
    assert [b["usdcny_date"] for b in p["bars"]] == ["2026-11-05", "2026-11-05", "2026-11-06"]
    # the converted extreme and the native extreme are the SAME print
    assert p["hi"] == 4143.52 and p["hi_native"] == 887.0
    assert p["lo"] == 4139.07 and p["lo_native"] == 890.0
    # negative control: the independent-max answer over the SAME IST-day bucket (native 890.0 beside the converted
    # 4,143.52 of a different bar, native 887.0 beside the converted 4,139.07 of a different bar) is NOT what is served
    day = [b for b in p["bars"] if str(b["ts"]).startswith(p["day"])]
    assert max(b["h_cny_g"] for b in day) == 890.0 and p["hi_native"] != 890.0
    assert min(b["l_cny_g"] for b in day) == 887.0 and p["lo_native"] != 887.0


def test_a_bar_with_no_rate_is_dropped_counted_and_said_so(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gold, "_db_fetch", _fake(SGE_BARS, []))
    gold.STORE.invalidate()
    p = client.get("/api/gold/bars", params={"symbol": "SGE_AU9999", "interval": "1m"}).json()
    assert p["bars"] == [] and p["fx"] is None and p["hi"] is None and p["unit"] == "USD/oz"
    # a truncated series says it is truncated, so it cannot be read as a short store (the FX ladder, not the bar store)
    assert p["dropped_no_fx"] == 2 and "no stored USDCNY vintage on or before their session" in p["note"]
    # negative control: the SAME request with the rates stored serves two converted bars, drops none and says nothing
    monkeypatch.setattr(gold, "_db_fetch", _fake(SGE_BARS, CNY_PTS))
    gold.STORE.invalidate()
    q = client.get("/api/gold/bars", params={"symbol": "SGE_AU9999", "interval": "1m"}).json()
    assert len(q["bars"]) == 2 and q["dropped_no_fx"] == 0 and "not served" not in q["note"]


def test_a_partial_usdcny_print_is_labelled_as_one() -> None:
    """The page labels a partial price everywhere else (wave 1e); the RATE is a price too. FX_CNY's stored 2026-11-05
    point really is `partial: true`."""
    thu = gold._bar_rows({"rows": [SGE_BARS[0]]})
    _, conv = gold.sge_usd_oz_bars(thu, [{**CNY_PTS[0], "partial": True}, CNY_PTS[1]], "FX_CNY")
    assert conv["fx"]["report_date"] == "2026-11-05" and conv["fx"]["partial"] is True
    # negative control: a final rate carries no qualifier (and a point with no flag claims nothing either way)
    _, final = gold.sge_usd_oz_bars(thu, [{**CNY_PTS[0], "partial": False}], "FX_CNY")
    assert final["fx"]["partial"] is False
    _, silent = gold.sge_usd_oz_bars(thu, CNY_PTS, "FX_CNY")
    assert silent["fx"]["partial"] is None


def test_the_partial_flag_survives_the_shared_points_helper() -> None:
    """8 Nov 2026: `sge_usd_oz_bars` read `partial` correctly, but every series reaches it through `_points`, which
    rebuilt each point with three keys and DROPPED the flag — so `/bars.fx.partial` could never be true in production
    and a genuinely partial rate went out unlabelled. The test above injected the flag by hand and so could not see it."""
    rows = [{"report_date": "2026-11-05", "value": 6.6583, "release_at": "2026-11-05T12:00:00+00:00", "partial": True},
            {"report_date": "2026-11-06", "value": 6.6880, "release_at": "2026-11-06T12:00:00+00:00", "partial": False}]
    pts = gold._points(rows)
    assert [p.get("partial") for p in pts] == [True, False]          # the flag is carried, not invented
    thu = gold._bar_rows({"rows": [SGE_BARS[0]]})
    _, conv = gold.sge_usd_oz_bars(thu, pts, "FX_CNY")
    assert conv["fx"]["report_date"] == "2026-11-05" and conv["fx"]["partial"] is True
    # negative controls: a row with no flag still claims nothing, and the other keys are unchanged
    assert "partial" not in gold._points([{"report_date": "2026-11-05", "value": 6.6583}])[0]
    assert gold._points(rows)[0]["value"] == 6.6583 and gold._points(rows)[0]["report_date"] == "2026-11-05"


def test_the_fred_fallback_is_used_only_when_yahoos_cny_is_missing() -> None:
    fred = [{**p, "series_id": "FRED_DEXCHUS"} for p in CNY_PTS]
    assert next((s for s in gold.SGE_FX_SERIES if {"FX_CNY": [], "FRED_DEXCHUS": fred}.get(s)), None) == "FRED_DEXCHUS"
    assert next((s for s in gold.SGE_FX_SERIES if {"FX_CNY": CNY_PTS, "FRED_DEXCHUS": fred}.get(s)), None) == "FX_CNY"


def test_a_stored_sge_daily_close_is_converted_or_not_served_at_all() -> None:
    pts = [{"report_date": "2026-11-06", "value": 868.0}, {"report_date": "2000-01-03", "value": 70.0}]
    out, dropped = gold.sge_usd_oz_closes(pts, CNY_PTS)
    assert len(out) == 1 and out[0]["value"] == FRI_USD and out[0]["value_cny_g"] == 868.0   # the 2000 date predates the ladder
    assert dropped == 1                                       # … and the row it refused is counted, not swallowed
    # negative control: no rates at all → no rows (never a yuan close under a '$/oz' label), both counted
    assert gold.sge_usd_oz_closes(pts, []) == ([], 2)


def test_a_withheld_open_survives_the_conversion_with_its_native_twin() -> None:
    """`ohlc_sane` runs first: an impossible open is withheld as `o_raw`. The conversion must convert that too, so the
    UI's withheld-open guard (C-DATA-06) sees a $/oz raw value, never a yuan one."""
    bar = gold.ohlc_sane({"ts": "2026-11-06T14:20:00+05:30", "o": 700.0, "h": 868.0, "l": 866.0, "c": 868.0, "v": 0.0})
    assert bar["o"] is None and bar["o_raw"] == 700.0
    out, _ = gold.sge_usd_oz_bars([bar], CNY_PTS, "FX_CNY")
    assert out[0]["o"] is None and out[0]["o_raw"] == round(700.0 * gold.GRAMS_PER_TROY_OZ / 6.688, 2)
    assert out[0]["o_raw_cny_g"] == 700.0 and out[0]["c"] == FRI_USD


def test_the_comex_payload_states_usd_oz_and_carries_no_conversion(client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    gc = [{"ts": "2026-11-06T14:20:00", "open": 4074.0, "high": 4080.0, "low": 4070.0, "close": 4074.9, "volume": 12}]
    monkeypatch.setattr(gold, "_db_fetch", _fake(gc, CNY_PTS))
    gold.STORE.invalidate()
    p = client.get("/api/gold/bars", params={"symbol": "GC=F", "interval": "1m"}).json()
    assert p["unit"] == "USD/oz" and p["unit_native"] is None and p["fx"] is None and p["conversion"] is None
    assert p["bars"][-1]["c"] == 4074.9 and "c_cny_g" not in p["bars"][-1]
    # negative control: INR=X is a rate — its payload says so and is never labelled $/oz
    monkeypatch.setattr(gold, "_db_fetch", _fake([{"ts": "2026-11-06T14:20:00", "close": 93.91}], CNY_PTS))
    gold.STORE.invalidate()
    inr = client.get("/api/gold/bars", params={"symbol": "INR=X", "interval": "1m"}).json()
    assert inr["unit"] == "INR per USD" and inr["bars"][-1]["c"] == 93.91
