"""routers/expiry.py — the FINAL ROUND B-XPRY additions (wave B, F-08), each rule with a negative control.

1. The replay curve carries an HONEST as-of: ``curve.as_of`` = the latest REPLAYED expiry, and ``replay_pending``
   names the lag when ``iv_expiry_daily`` holds newer expiries than ``iv_expiry_replay`` (the 13 Nov finding: the
   curve read was already current — the STORE ends at 2026-11-03 because the after-close replay job had not run;
   the read must say so instead of a bare old stamp).
2. The expiry-day cockpit's series (max-pain drift, intraday PCR path, the straddle tracker) ride the existing
   ``live.path`` / ``decay`` / ``vs_curve`` payload untouched — fixture: the REAL stored NIFTY expiry day
   2026-11-09 (115 snapshots in the store; trimmed here). No ``signal`` badge; "describes, does not predict".
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from routers import expiry  # noqa: E402


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(expiry.router, prefix="/api/derivatives")
    return app


@pytest.fixture(autouse=True)
def _fresh_cache():
    expiry._down.clear()
    expiry.TAPE.invalidate()
    yield
    expiry._down.clear()
    expiry.TAPE.invalidate()


# Trimmed from the live store's /db/fo-iv/expiry-day/NIFTY?date=2026-11-09 (the stored expiry-day tape, 115 snapshots).
DAY_9NOV = {
    "symbol": "NIFTY", "date": "2026-11-09", "is_expiry_day": True, "next_expiry": "2026-11-17", "last_expiry": "2026-11-03",
    "live": {
        "snapshots": 115, "first": "09:16", "last": "15:26", "last_ts": "2026-11-09T09:56:00+00:00", "spot": 25003.65,
        "open_strike": 25000.0, "source": "breeze",
        "path": [
            {"ts": "2026-11-09T03:46:00+00:00", "ist": "09:16", "forward": 24996.7, "spot": 24999.9, "max_pain": 24800.0,
             "straddle": 228.6, "straddle_open_strike": 228.6, "atm_iv": 42.94, "pcr": 0.953},
            {"ts": "2026-11-09T06:30:00+00:00", "ist": "12:00", "forward": 25015.2, "spot": 25010.0, "max_pain": 24900.0,
             "straddle": 140.2, "straddle_open_strike": 150.9, "atm_iv": 38.1, "pcr": 0.91},
            {"ts": "2026-11-09T09:56:00+00:00", "ist": "15:26", "forward": 25040.67, "spot": 25003.65, "max_pain": 25000.0,
             "straddle": 20.68, "straddle_open_strike": 43.12, "atm_iv": None, "pcr": 0.849},
        ],
        "unwind": [{"strike": 24250.0, "ce_oi_open": 268125.0, "ce_oi": 216580.0, "ce_chg_open": -51545.0,
                    "pe_oi_open": 2976805.0, "pe_oi": 3299595.0, "pe_chg_open": 322790.0}],
        "pin_risk": [{"strike": 25000.0, "distance_pts": -3.65, "distance_pct": -0.015, "ce_oi": 20175480.0,
                      "pe_oi": 22861410.0, "total_oi": 43036890.0}],
        "decay": [{"minute": 1, "ist": "09:16", "pct_of_open": 100.0, "straddle": 228.6},
                  {"minute": 371, "ist": "15:26", "pct_of_open": 18.86, "straddle": 43.12}],
        "vs_curve": {"minute": 371, "today_pct": 18.86, "median_pct": 101.9, "p25": 46.68, "p75": 144.69, "n": 26},
    },
    "curve": {"n": 26, "start_minute": 0, "points": [{"minute": 0, "median": 100.0, "p25": 100.0, "p75": 100.0, "n": 26}],
              "expiries": ["2026-10-27", "2026-11-03"], "source": "breeze 1-minute bars (backfilled)",
              "note": "last-trade closes of the ATM call + put at the expiry-day open strike; today's line uses bid/ask mids"},
    "scorecard": {"rows": [], "stats": {"n": 0}},
}


def _get(monkeypatch, body, url="/api/derivatives/expiry-day?symbol=NIFTY&date=2026-11-09"):
    async def fake(path, params):
        return body
    monkeypatch.setattr(expiry, "_fetch", fake)
    r = TestClient(_app()).get(url)
    assert r.status_code == 200
    return r.json()


def test_curve_as_of_is_the_latest_replayed_expiry_and_a_store_lag_is_named(monkeypatch):
    # The live 13 Nov shape: not an expiry day; iv_expiry_daily holds the 2026-11-09 expiry but the replay store
    # ends at 2026-11-03 (the after-close job had not run — PM runs it, never this service).
    nov13 = {**DAY_9NOV, "date": "2026-11-13", "is_expiry_day": False, "last_expiry": "2026-11-09",
             "live": {"snapshots": 0}}
    j = _get(monkeypatch, nov13, url="/api/derivatives/expiry-day?symbol=NIFTY&date=2026-11-13")
    c = j["curve"]
    assert c["as_of"] == "2026-11-03"                                   # the newest REPLAYED expiry, not the page date
    # 2026-11-09 is stored in iv_expiry_daily (last_expiry) but not replayed: the read says so instead of lagging silently
    assert "replay_pending" in c
    assert "2026-11-03" in c["replay_pending"] and "2026-11-09" in c["replay_pending"]
    assert "not replayed yet" in c["replay_pending"] and "O-T16" in c["replay_pending"]
    # no re-scoring, no direction words in the honesty line
    for word in ("bullish", "bearish", "buy", "sell", "should"):
        assert word not in c["replay_pending"].lower()


def test_no_pending_note_when_the_replay_is_current_or_empty(monkeypatch):
    # On its own expiry morning (9 Nov) the replay through 3 Nov IS current: last_expiry == the newest replayed expiry
    j = _get(monkeypatch, DAY_9NOV)
    assert j["curve"]["as_of"] == "2026-11-03" and "replay_pending" not in j["curve"]
    # negative control: an empty curve keeps its own store note, invents no as-of
    empty = {**DAY_9NOV, "curve": {"n": 0, "points": [], "note": "no replay stored yet (the PM's after-close job, O-T16)"}}
    expiry.TAPE.invalidate()
    j2 = _get(monkeypatch, empty, url="/api/derivatives/expiry-day?symbol=NIFTY&date=2026-11-10")
    assert j2["curve"]["as_of"] is None and "replay_pending" not in j2["curve"]
    assert "no replay stored yet" in j2["curve"]["note"]


def test_the_cockpit_series_ride_the_stored_tape_untouched(monkeypatch):
    """Max-pain drift, intraday PCR and the straddle tracker all come from live.path / decay / vs_curve — the shaping
    must pass the stored rows through point-in-time, never recompute them."""
    j = _get(monkeypatch, DAY_9NOV)
    assert j["is_expiry_day"] is True and j["live"]["snapshots"] == 115
    path = j["live"]["path"]
    assert [p["max_pain"] for p in path] == [24800.0, 24900.0, 25000.0]          # the drift series
    assert [p["pcr"] for p in path] == [0.953, 0.91, 0.849]                      # the intraday PCR path
    assert [p["straddle_open_strike"] for p in path] == [228.6, 150.9, 43.12]    # the tracker's priced path
    assert path[-1]["atm_iv"] is None                                            # a null stays a gap, never filled
    assert j["live"]["decay"][-1]["pct_of_open"] == 18.86
    assert j["live"]["vs_curve"]["n"] == 26 and j["live"]["vs_curve"]["median_pct"] == 101.9
    # chip: stored snapshots are DELAYED (never LIVE) with the tape's own stamp
    assert j["chip"]["state"] == "delayed" and j["chip"]["as_of"] == "2026-11-09T09:56:00+00:00"
    # labelling rules: no signal badge, the verdict describes
    assert "signal" not in j["badges"].values()
    assert j["verdict"].endswith("describes, does not predict")


# ── R3-NITS (F1-TRADER): the bogus 329-days-before-priced scorecard row is dropped, explicitly ───────────────────────

ROW_OK = {"expiry": "2026-11-03", "priced_on": "2026-11-02", "dte": 1, "forward": 25000.0, "strike": 25000.0,
          "straddle": 163.0, "implied_move_pct": 0.652, "implied_1sd_pct": 0.5, "settle": 25510.0,
          "realised_move_pct": 2.042, "ratio": 3.132, "exceeded": True, "naive_move_pct": 0.5,
          "implied_recorded_at": "2026-11-02T15:40:00+00:00"}
ROW_LONG_WEEKEND = {**ROW_OK, "expiry": "2026-09-15", "priced_on": "2026-09-11", "dte": 4,
                    "implied_move_pct": 0.852, "realised_move_pct": -1.401, "ratio": 1.644, "exceeded": True}
# the live find (13 Nov walk): a store hole paired 2026-06-25 with a session 329 days earlier — unscored, like the store serves it
ROW_BOGUS = {**ROW_OK, "expiry": "2026-06-25", "priced_on": "2025-07-31", "dte": 329, "straddle": None,
             "implied_move_pct": None, "implied_1sd_pct": None, "realised_move_pct": -8.103, "ratio": None,
             "exceeded": None, "naive_move_pct": None}


def _with_scorecard(rows, stats):
    return {**DAY_9NOV, "date": "2026-11-13", "is_expiry_day": False, "live": {"snapshots": 0},
            "scorecard": {"rows": rows, "stats": stats, "badge": "arithmetic"}}


def test_the_bogus_stale_priced_row_is_dropped_and_named(monkeypatch):
    stats = {"n": 2, "exceeded_pct": 100.0, "fair_exceeded_pct": 42.5, "median_ratio": 2.388, "mean_ratio": 2.388,
             "mean_abs_miss_pct": 0.97, "naive_mean_abs_miss_pct": 1.221, "implied_closer": 1, "compared": 2}
    j = _get(monkeypatch, _with_scorecard([ROW_OK, ROW_BOGUS, ROW_LONG_WEEKEND], stats),
             url="/api/derivatives/expiry-day?symbol=NIFTY&date=2026-11-13")
    sc = j["scorecard"]
    assert [r["expiry"] for r in sc["rows"]] == ["2026-11-03", "2026-09-15"]     # the 329d pairing is gone
    assert sc["excluded"] == 1
    assert "2026-06-25" in sc["excluded_note"] and "2025-07-31" in sc["excluded_note"] and "329d" in sc["excluded_note"]
    assert "store hole, not an observation" in sc["excluded_note"]
    # the bogus row was UNSCORED (implied null, exactly the live shape): the store's stats pass through untouched
    assert sc["stats"] == stats
    # a long weekend (dte 4) is a healthy pairing and is kept — the filter is a bound, not a dte==1 rule
    assert any(r["dte"] == 4 for r in sc["rows"])


def test_a_scored_stale_row_rescores_the_stats_over_the_kept_rows(monkeypatch):
    # negative control for the stats path: if a stale pairing ever arrives SCORED, the served stats are re-derived
    # from the kept rows (never counting a row the table does not show)
    bogus_scored = {**ROW_BOGUS, "implied_move_pct": 9.0, "ratio": 0.9, "exceeded": False, "naive_move_pct": 8.0}
    stats_with_bogus = {"n": 3, "exceeded_pct": 66.7, "fair_exceeded_pct": 42.5, "median_ratio": 1.644,
                        "mean_ratio": 1.722, "mean_abs_miss_pct": 1.0, "naive_mean_abs_miss_pct": 1.1,
                        "implied_closer": 1, "compared": 3}
    j = _get(monkeypatch, _with_scorecard([ROW_OK, bogus_scored, ROW_LONG_WEEKEND], stats_with_bogus),
             url="/api/derivatives/expiry-day?symbol=NIFTY&date=2026-11-14")
    sc = j["scorecard"]
    assert sc["excluded"] == 1 and len(sc["rows"]) == 2
    s = sc["stats"]
    assert s["n"] == 2 and s["compared"] == 2                                    # over the KEPT rows only
    assert s["exceeded_pct"] == 100.0                                            # both kept rows exceeded
    assert s["median_ratio"] == round((3.132 + 1.644) / 2, 3)
    assert s["fair_exceeded_pct"] == 42.5                                        # the fair reference is carried over


def test_a_clean_scorecard_passes_through_byte_identical(monkeypatch):
    sc_in = {"rows": [ROW_OK, ROW_LONG_WEEKEND], "stats": {"n": 2}, "badge": "arithmetic"}
    j = _get(monkeypatch, _with_scorecard(sc_in["rows"], sc_in["stats"]),
             url="/api/derivatives/expiry-day?symbol=NIFTY&date=2026-11-15")
    sc = j["scorecard"]
    assert "excluded" not in sc and "excluded_note" not in sc
    assert [r["expiry"] for r in sc["rows"]] == ["2026-11-03", "2026-09-15"] and sc["stats"] == {"n": 2}
