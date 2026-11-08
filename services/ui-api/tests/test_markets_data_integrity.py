"""Review fixes in routers/markets.py (builder D-DATA, 6 Nov 2026): M11 announcements whole day + cursor, M10 / m022 wrap
archive status and the section marker, M28 ECO (US releases, F&O expiries, special sessions), m042 / m043 / m044 results
panels, m025 / m026 / m028 / m029 / M46 index drivers. Every rule has a negative control."""
from __future__ import annotations

# ruff: noqa: DTZ001

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import routers.markets as mk  # noqa: E402


# ── M11: the whole day, a time cursor, truthful counts ─────────────────────────────────────────────────────────────
def _filings(n: int) -> list[dict]:
    """n filings newest first, one a minute back from 20:50 (a results-season day: 1,421 on 5 Nov 2026)."""
    out = []
    for i in range(n):
        m = 20 * 60 + 50 - i * (12 * 60) // n
        out.append({"symbol": f"S{i}", "time": f"2026-11-05 {m // 60:02d}:{m % 60:02d}:00", "category": "results" if i % 6 == 0 else "other"})
    return out


def test_default_limit_keeps_a_results_season_day_whole():
    items = _filings(1421)
    page, meta = mk.page_announcements(items, mk.ANNOUNCEMENTS_DEFAULT_LIMIT)
    assert len(page) == 1421 and meta["truncated"] is False and meta["next_before"] is None
    assert meta["total"] == meta["returned"] == 1421 and page[-1]["time"] < "2026-11-05 09:00"     # the morning is there


def test_old_cap_truncates_and_the_cursor_pages_back():
    items = _filings(1421)
    page, meta = mk.page_announcements(items, 1000)                                                 # the 5 Nov behaviour
    assert meta["truncated"] is True and meta["returned"] == 1000 and meta["next_before"].startswith(page[-1]["time"] + "#")
    rest, meta2 = mk.page_announcements(items, 1000, before=meta["next_before"])
    assert meta2["truncated"] is False and len(page) + len(rest) == 1421                     # filings sharing a time never fall between pages
    assert {r["symbol"] for r in page}.isdisjoint({r["symbol"] for r in rest})
    small, n = [], None
    while True:                                                                                  # small pages walk the whole day exactly once
        got, m = mk.page_announcements(items, 97, before=n)
        small += got
        n = m["next_before"]
        if not n:
            break
    assert [r["symbol"] for r in small] == [r["symbol"] for r in items]
    hh, _ = mk.page_announcements(items, 5000, before="12:00")
    assert hh and all(r["time"][11:16] < "12:00" for r in hh)


# ── M10 / m022: the wrap archive ───────────────────────────────────────────────────────────────────────────────────
MARKER_OK = '<!-- wrap-sections {"breadth": "ok", "sectors": "ok"} -->'
MARKER_GAP = '<!-- wrap-sections {"breadth": "not_stored", "sectors": "ok"} -->'


def test_split_wrap_strips_the_marker_for_the_renderer():
    body, st = mk.split_wrap("# Market wrap\n\n- NIFTY +2.40%\n\n" + MARKER_GAP + "\n")
    assert "wrap-sections" not in body and st == {"breadth": "not_stored", "sectors": "ok"}
    assert mk.split_wrap("# legacy\n- x\n") == ("# legacy\n- x\n", None)                           # negative control


def test_wrap_entry_flags_incomplete_and_stale_legacy_wraps():
    assert mk.wrap_entry("2026-11-05", "- a\n" + MARKER_OK)["complete"] is True
    e = mk.wrap_entry("2026-11-05", "- a\n" + MARKER_GAP)
    assert e["complete"] is False and e["not_stored"] == ["breadth"]
    legacy = "# Market wrap · Wed 04 Nov 2026\n\nWritten 21:30 IST from the terminal's data (NSE end of day 2026-10-30).\n- NIFTY"
    assert mk.wrap_entry("2026-11-04", legacy)["complete"] is False
    assert mk.wrap_entry("2026-10-30", legacy.replace("Wed 04 Nov", "Fri 30 Oct"))["complete"] is True


def test_archive_status_lists_missing_sessions_and_todays_pending_note():
    have = ["2026-10-27", "2026-10-30", "2026-11-04", "2026-11-05"]
    sessions = ["2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"]
    st = mk.wrap_archive_status(have, sessions, "2026-11-06", True)
    assert st["missing_sessions"] == ["2026-10-28", "2026-10-29", "2026-11-02", "2026-11-03"]
    assert st["today_pending"] is True and "21:00" in st["note"]
    hol = mk.wrap_archive_status(have, sessions, "2026-11-10", False)                               # NSE holiday: nothing pending
    assert hol["today_pending"] is False and hol["note"] is None


# ── M28: ECO ───────────────────────────────────────────────────────────────────────────────────────────────────────
GOLD_EVENTS = [
    {"event_date": "2026-11-06", "time_ist": "19:00", "kind": "US_DATA", "name": "Unemployment Rate", "impact": "High", "forecast": "4.2%",
     "previous": "4.2%", "actual": None},
    {"event_date": "2026-11-06", "time_ist": "19:00", "kind": "US_NFP", "name": "Non-Farm Employment Change", "impact": "High",
     "forecast": "65K", "previous": "29K", "actual": None},
    {"event_date": "2026-11-06", "time_ist": "15:00", "kind": "FOMC_SPEECH", "name": "FOMC Member Williams Speaks", "impact": "Low"},
    {"event_date": "2026-11-05", "time_ist": "19:00", "kind": "US_CLAIMS", "name": "Unemployment Claims", "impact": "High",
     "forecast": "197K", "previous": "194K", "actual": "201K"},
    {"event_date": "2026-10-28", "time_ist": "20:00", "kind": "US_DATA", "name": "API Weekly Statistical Bulletin", "impact": "Low"},
]


def test_us_releases_one_row_per_day_with_forecast_previous_actual():
    rows = mk.us_release_rows(GOLD_EVENTS, date(2026, 10, 23), date(2026, 11, 20))
    assert [r["date"] for r in rows] == ["2026-11-05", "2026-11-06"]                                # Low impact and speeches left out
    nfp = rows[1]
    assert nfp["kind"] == "US" and nfp["time"] == "19:00" and nfp["id"] == "US-2026-11-06"
    assert nfp["what"].startswith("US data: Non-Farm Employment Change 19:00 (forecast 65K, previous 29K)")
    assert "actual 201K" in rows[0]["what"]                                                           # m012: a stored print shows
    assert mk.us_release_rows(GOLD_EVENTS, date(2026, 12, 1), date(2026, 12, 31)) == []            # negative control: outside


def test_fo_expiries_shift_on_nse_holidays():
    hol = {"2026-11-10", "2026-11-24"}
    listed = ["2026-11-09", "2026-11-17", "2026-11-23", "2026-12-01", "2026-12-29"]
    rows = {r["date"]: r for r in mk.fo_expiry_rows(listed, hol, date(2026, 11, 6), date(2026, 12, 31))}
    assert rows["2026-11-09"]["moved_from"] == "2026-11-10" and not rows["2026-11-09"]["monthly"] and "NSE holiday" in rows["2026-11-09"]["what"]
    assert rows["2026-11-23"]["monthly"] and rows["2026-11-23"]["moved_from"] == "2026-11-24"
    assert rows["2026-12-29"]["monthly"] and rows["2026-12-29"]["shifted"] is False                    # negative control: an ordinary Tuesday
    assert all(r["moved"] is False for r in rows.values())             # 'moved' stays ECO's weekend-release flag (the UI labels it so)
    assert "listed" in rows["2026-11-17"]["source"] and rows["2026-12-15"]["source"] == mk.FO_RULE   # beyond the listed weeks: the rule
    assert "2026-11-10" not in rows and "2026-11-24" not in rows
    past = {r["date"]: r for r in mk.fo_expiry_rows([], {"2026-10-20"}, date(2026, 10, 12), date(2026, 10, 31))}
    assert "2026-10-19" in past and past["2026-10-27"]["monthly"]                                    # rule for past weeks


def test_special_sessions_name_their_circular_and_never_guess_nse_time():
    from shared.mcx_specs import SPECIAL_SESSIONS_2026
    rows = mk.special_session_rows(list(SPECIAL_SESSIONS_2026), date(2026, 11, 1), date(2026, 11, 30))
    assert len(rows) == 1 and rows[0]["date"] == "2026-11-08" and rows[0]["kind"] == "SESSION" and rows[0]["time"] is None
    assert "MCX/TRD/590/2026" in rows[0]["what"] and "O-11" in rows[0]["what"]
    assert mk.special_session_rows(list(SPECIAL_SESSIONS_2026), date(2026, 12, 1), date(2026, 12, 31)) == []


# ── m042 / m043: results panels ────────────────────────────────────────────────────────────────────────────────────
def test_session_labels_after_the_close():
    assert mk.session_labels(datetime(2026, 11, 5, 11, 0), "2026-11-05")["session_open"] is True
    late = mk.session_labels(datetime(2026, 11, 5, 20, 57), "2026-11-05")
    assert late["session_open"] is False and late["data_date"] == "2026-11-05" and "closed" in late["label"]


def test_intraday_reporters_are_marked_post_event():
    rows = [{"symbol": "M&M", "results_date": "2026-11-05", "ratio": 1.28}, {"symbol": "TITAN", "results_date": "2026-11-05", "ratio": 0.52},
            {"symbol": "HINDALCO", "results_date": "2026-11-06", "ratio": 3.3}]
    rel = [{"symbol": "M&M", "released_at": "2026-11-05 12:57"}, {"symbol": "TITAN", "released_at": "2026-11-05 16:50"}]
    out = {r["symbol"]: r for r in mk.mark_post_event(rows, rel, "2026-11-05")}
    assert out["M&M"]["post_event"] is True and "12:57" in out["M&M"]["post_event_note"]
    assert out["TITAN"]["post_event"] is False                                                        # after the close: still priced
    assert out["HINDALCO"]["post_event"] is False


# ── index drivers ─────────────────────────────────────────────────────────────────────────────────────────────────
def test_challenger_pending_is_named():
    rows = [{"date": f"2026-11-0{i}", "window_sessions": 20, "leader": "HDFCBANK", "raw_leader": r}
            for i, r in ((1, "HDFCBANK"), (2, "ICICIBANK"), (3, "ICICIBANK"), (4, "ICICIBANK"))]
    ch = mk.challenger_of(rows, "HDFCBANK", 20)
    assert ch["symbol"] == "ICICIBANK" and ch["sessions_leading"] == 3 and ch["sessions_needed"] == 2
    assert ch["sentence"].endswith("describes, does not predict")
    assert mk.challenger_of(rows[:1], "HDFCBANK", 20) is None                                          # negative control


def test_tab_state_degrades_honestly():
    assert mk.tab_state({"sessions": 2, "mae_60s": 90.8, "degraded": True}, 2, 2, "2026-11-04")["state"] == "insufficient"
    # 8 Nov 2026: after the 2019 backfill ran, NIFTY BANK still had 3 sessions (its first archived list is 4 Nov) and the
    # page said "the backfill has not run". A point-in-time index names the archive, not the job; every other index does not.
    bank = mk.tab_state({"sessions": 3, "mae_60s": 75.1, "degraded": True}, 3, 3, "2026-11-04", index="NIFTY BANK")
    assert bank["limit"] == "archive" and "point-in-time" in bank["sentence"] and "backfill" not in bank["sentence"]
    assert "2026-11-04" in bank["sentence"] and bank["state"] == "insufficient"
    other = mk.tab_state({"sessions": 3, "mae_60s": 75.1, "degraded": True}, 3, 3, "2026-11-04", index="NIFTY 50")
    assert other["limit"] == "backfill" and "the backfill has not run" in other["sentence"]      # negative control
    assert mk.tab_state({"sessions": 3, "mae_60s": 75.1, "degraded": True}, 3, 3, "2026-11-04")["limit"] == "backfill"
    assert mk.tab_state({"sessions": 60, "mae_60s": 55.3, "degraded": True}, 21, 400, "2019-10-01")["state"] == "degraded"
    ok = mk.tab_state({"sessions": 60, "mae_60s": 5.8, "degraded": False}, 21, 700, "2023-11-01")
    assert ok["state"] == "ok" and "6 pts" in ok["sentence"]


def test_monthly_flags_a_month_with_a_failed_session():
    contrib = [{"date": "2026-02-02", "symbol": "A", "points": 260.0}, {"date": "2026-02-03", "symbol": "A", "points": 632.0},
               {"date": "2026-03-02", "symbol": "A", "points": 10.0}]
    fit = [{"date": "2026-02-02", "actual_points": -232.25, "residual_points": -492.5}, {"date": "2026-02-03", "actual_points": 639.2,
            "residual_points": 7.2}, {"date": "2026-03-02", "actual_points": 11.0, "residual_points": 1.0}]
    rows = {r["month"]: r for r in mk.monthly_leaderboard(contrib, fit, 12)}
    assert rows["2026-02"]["bad_sessions"] == ["2026-02-02"] and "not reliable" in rows["2026-02"]["note"]
    assert rows["2026-03"]["bad_sessions"] == [] and rows["2026-03"]["note"] is None
    assert rows["2026-02"]["residual_pts"] == round(-232.25 + 639.2 - 892.0, 1)


def test_slice_prefers_the_weights_the_points_were_computed_with():
    contrib = [{"date": "2026-11-05", "symbol": "A", "points": 10.0, "ret_pct": 1.0, "weight_pct": 60.0},
               {"date": "2026-11-05", "symbol": "B", "points": 5.0, "ret_pct": 1.0, "weight_pct": 40.0}]
    weights = [{"date": "2026-11-05", "symbol": "A", "method": "rebuilt", "weight_pct": 70.0},
               {"date": "2026-11-05", "symbol": "C", "method": "rebuilt", "weight_pct": 1.0},
               {"date": "2026-11-05", "symbol": "C", "method": "rebuilt_fitted", "weight_pct": 2.0}]
    out = mk.slice_contributions(contrib, [], weights, ["2026-11-05"])
    w = {m["symbol"]: m["weight_pct"] for m in out["members"]}
    assert w["A"] == 60.0 and w["B"] == 40.0                                                          # not the 'rebuilt' 70 %
    assert mk._weight_method(weights, "2026-11-05")["method"] == "rebuilt_fitted"


def test_stored_attribution_replaces_the_live_rebuild_after_the_close():
    live = {"time": "05-Nov-2026 15:30", "explained_points": 573.3, "members": [{"symbol": "ICICIBANK", "points": 113.32, "weight_pct": 8.87}]}
    stored = [{"date": "2026-11-05", "symbol": "ICICIBANK", "points": 113.5, "weight_pct": 8.89, "weight_method": "rebuilt_calibrated"}]
    out = mk.prefer_stored_contribution(live, stored, {"explained_points": 582.3105, "weight_method": "rebuilt_calibrated"})
    assert out["explained_points"] == 582.3 and out["members"][0]["points"] == 113.5 and "same figure as MEMB" in out["explained_source"]
    during = mk.prefer_stored_contribution({**live, "time": "05-Nov-2026 13:10"}, stored, None)            # negative control: in session
    assert during["explained_points"] == 573.3 and during["explained_source"].startswith("live")
    other_day = mk.prefer_stored_contribution(live, [{**stored[0], "date": "2026-11-04"}], None)
    assert other_day["explained_points"] == 573.3


def test_memb_tile_follows_the_stored_weights():
    live = {"time": "05-Nov-2026 15:30", "explained_points": 2037.9, "summary": {"top5_weight_pct": 87.4},
            "members": [{"symbol": f"B{i}", "points": 1.0, "weight_pct": w} for i, w in enumerate((30.5, 27.5, 10.8, 9.5, 9.1, 12.6))]}
    stored = [{"date": "2026-11-05", "symbol": f"B{i}", "points": 1.0, "weight_pct": w}
              for i, w in enumerate((20.0, 19.0, 12.0, 11.0, 10.0, 28.0))]
    out = mk.prefer_stored_contribution(live, stored, {"explained_points": 1870.0, "weight_method": "rebuilt_fitted"})
    assert out["summary"]["top5_weight_pct"] == 90.0 and out["explained_points"] == 1870.0
    assert mk.prefer_stored_contribution({**live, "time": "05-Nov-2026 11:00"}, stored, None)["summary"]["top5_weight_pct"] == 87.4


def test_memb_flags_distorted_filing_figures():
    body = {"members": [{"symbol": "COALINDIA", "pat_yoy": 261.2, "revenue_yoy": 199.6, "pe": 5.8},
                        {"symbol": "ETERNAL", "pat_yoy": 40.0, "pe": 669.4}, {"symbol": "TMPV", "pe": 1.4},
                        {"symbol": "HDFCBANK", "pat_yoy": 6.0, "revenue_yoy": 9.0, "pe": 14.6}]}
    f = {m["symbol"]: m["flags"] for m in mk.memb_outlier_flags(body)["members"]}
    assert f["COALINDIA"] == ["pat_yoy_outlier"] and f["ETERNAL"] == ["pe_distorted"] and f["TMPV"] == ["pe_distorted"]
    assert f["HDFCBANK"] == []                                                                          # negative control
    assert mk.memb_outlier_flags(body)["flag_badge"] == "heuristic"


# ── checker 6 Nov: in-session points on the last stored (capped / calibrated) weights ──────────────────────────────
def _bank_live(time: str) -> dict:
    """NIFTY BANK at 09:07 on 6 Nov 2026: the live rebuild gives ICICIBANK 27.47 % (above the 20 % cap)."""
    w = {"ICICIBANK": 27.47, "HDFCBANK": 25.1, "SBIN": 14.0, "AXISBANK": 12.0, "KOTAKBANK": 11.0, "INDUSINDBK": 10.43}
    return {"time": time, "last": 52_100.0, "change": 100.0, "explained_points": 140.0, "summary": {"top5_weight_pct": 89.6},
            "members": [{"symbol": s, "weight_pct": v, "change_pct": 0.5, "points": 52_000 * v / 100 * 0.005} for s, v in w.items()]}


BANK_STORED = [{"date": "2026-11-05", "symbol": s, "weight_pct": w, "ret_pct": r, "points": 1.0, "weight_method": "rebuilt_fitted"}
               for s, w, r in (("ICICIBANK", 19.6, 1.0), ("HDFCBANK", 19.9, 0.0), ("SBIN", 18.0, -1.0), ("AXISBANK", 15.0, 0.0),
                               ("KOTAKBANK", 14.0, 0.0), ("INDUSINDBK", 13.5, 0.0))]


def test_live_points_use_the_last_stored_weights_in_the_session():
    out = mk.prefer_stored_contribution(_bank_live("06-Nov-2026 09:07"), BANK_STORED, None)
    w = {m["symbol"]: m["weight_pct"] for m in out["members"]}
    tot = sum(x["weight_pct"] * (1 + x["ret_pct"] / 100) for x in BANK_STORED)
    assert abs(w["ICICIBANK"] - 19.6 * 1.01 / tot * 100) < 0.01 and max(w.values()) < 20.5            # capped, drifted to the 5 Nov close
    assert abs(sum(w.values()) - 100) < 0.05
    ici = next(m for m in out["members"] if m["symbol"] == "ICICIBANK")
    assert abs(ici["points"] - 52_000 * w["ICICIBANK"] / 100 * 0.005) < 0.01                          # L(d−1) × w × change
    assert out["explained_points"] == round(sum(m["points"] for m in out["members"]), 1)
    assert "stored weights of 2026-11-05 (rebuilt_fitted" in out["explained_source"] and out["summary"]["top5_weight_pct"] < 89.6


def test_live_rebuild_stays_without_recent_or_complete_stored_weights():
    live = _bank_live("06-Nov-2026 09:07")
    old = [{**r, "date": "2026-10-20"} for r in BANK_STORED]                                          # > 7 days old
    assert mk.prefer_stored_contribution(live, old, None)["explained_source"].startswith("live rebuild")
    partial = BANK_STORED[:4]                                                                          # covers 4 of 6 members (< 90 %)
    assert mk.prefer_stored_contribution(live, partial, None)["explained_source"].startswith("live rebuild")
    no_ret = [{k: v for k, v in r.items() if k != "ret_pct"} for r in BANK_STORED]                    # cannot drift: not used
    assert mk.prefer_stored_contribution(live, no_ret, None)["members"][0]["weight_pct"] == 27.47
    # the old job's plain 'rebuilt' rows (6 Nov: the live stack stored uncapped BANK weights) are the same rebuild: not used
    plain = [{**r, "weight_method": "rebuilt"} for r in BANK_STORED]
    out = mk.prefer_stored_contribution({**live, "index": "NIFTY BANK"}, plain, None)
    assert out["members"][0]["weight_pct"] == 27.47 and "caps not applied" in out["explained_source"]
    assert "caps" not in mk.prefer_stored_contribution({**live, "index": "NIFTY 50"}, plain, None)["explained_source"]


# ── m044: typical moves are asked in chunks; a failed chunk blanks only its own names ──────────────────────────────
def test_typical_moves_are_chunked_and_a_failed_chunk_blanks_only_its_names(monkeypatch):
    import asyncio

    import httpx
    import test_live_results_reacting as lr
    import test_live_support as sup

    syms = [f"S{i:03d}" for i in range(372)]                    # 5 Nov 2026: 372 results filers in the window
    fail = set(syms[150:300])

    class Fake(lr.ReactingDataService):
        async def handler(self, request: httpx.Request) -> httpx.Response:
            if request.url.host == "data-service" and request.url.path == "/db/typical-results-moves":
                self.requests.append(request)
                asked = sorted(s for s in request.url.params["symbols"].split(",") if s)[:200]   # data-service's own cap
                if set(asked) & fail:
                    return httpx.Response(500, json={"detail": "chunk failed"})
                return httpx.Response(200, json={"moves": {s: {"typical_move_pct": 3.0, "quarters": 8} for s in asked}})
            return await super().handler(request)

    fake = sup.install(monkeypatch, Fake())
    monkeypatch.setattr(mk, "DATA_SVC", sup.DS)
    fake.announcements = {"2026-11-04": [], "today": [lr.results(s, "2026-11-05 08:00:00") for s in syms]}
    fake.rows = {"NIFTY 50": sup.row(24010.0, change_pct=0.5)}

    def run(chunk: int) -> tuple[dict, list]:
        monkeypatch.setattr(mk, "TYPICAL_CHUNK", chunk)
        mk._REACTING.invalidate()
        fake.requests.clear()
        monkeypatch.setattr(mk, "_react_now", lambda: datetime(2026, 11, 5, 11, 0))
        out = asyncio.run(mk._results_reacting())
        sizes = [len(r.url.params["symbols"].split(",")) for r in fake.requests if r.url.path == "/db/typical-results-moves"]
        return {r["symbol"]: r["typical_move_pct"] for r in out["rows"]}, sizes

    got, sizes = run(150)
    assert sizes == [150, 150, 72]
    assert all(got[s] == 3.0 for s in syms[:150] + syms[300:]) and all(got[s] is None for s in fail)
    # negative control: one request for all 372 (the old code) is cut at data-service's 200, so names after S199 are blank
    fail.clear()
    got1, sizes1 = run(1000)
    assert sizes1 == [372] and got1["S199"] == 3.0 and got1["S200"] is None and got1["S371"] is None


# ── m025: the monthly board's as_of is the last stored session ─────────────────────────────────────────────────────
def test_monthly_as_of_is_the_last_stored_session(monkeypatch):
    import asyncio

    contrib = [{"date": "2026-10-30", "symbol": "A", "points": 5.0}, {"date": "2026-11-05", "symbol": "A", "points": 7.0}]
    fit = [{"date": "2026-10-30", "actual_points": 5.0, "residual_points": 0.0}, {"date": "2026-11-05", "actual_points": 7.0, "residual_points": 0.0}]

    class Reads:
        def __init__(self) -> None:
            pass

        async def get(self, table: str, **_p) -> list[dict]:
            return {"contribution": contrib, "fit": fit}[table]

        def headers(self, _response) -> None:
            return None

        def meta(self) -> dict:
            return {"ok": True}

    monkeypatch.setattr(mk, "_DriverReads", Reads)
    out = asyncio.run(mk.index_drivers_monthly(None, index="NIFTY 50", months=12))
    assert out["as_of"] == "2026-11-05" and out["as_of_month"] == "2026-11"
    assert out["as_of"] != f"{out['months'][-1]['month']}-01"                    # negative control: not the month's first day
    contrib.clear()
    fit.clear()
    empty = asyncio.run(mk.index_drivers_monthly(None, index="NIFTY 50", months=12))
    assert empty["as_of"] is None and empty["as_of_month"] is None and empty["months"] == []
