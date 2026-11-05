"""Shared fixtures for the Terminal v2 B3 routes (test_terminal_v2_api.py, test_terminal_v2_contract.py).

The data-service and master-controller are replaced by ONE httpx.MockTransport behind the process-wide client
(`shared.http_client.get_async_client`): every request the routers make is recorded (host + path), the fixtures are
served in the `/db/*` shapes B1 will write (PLAN 1.1 / 1.2 / 1.4 table columns), and any other host answers 404 —
so a test can assert that the request path never leaves the loopback (G6: zero outbound calls under a fake transport).

Data: the R-IV prototype's whole-era run `reports/terminal_v2/R-IV/iv_compare_NIFTY.csv` (578 sessions, 2024-07-08 →
2026-11-04) shaped as `iv_summary_daily`; a synthetic 3-member index for the drivers (the identity holds exactly);
R-DATA §3's freshness rows for the health view; the real-format SPAN subset `fixtures/span_nsccl_20261104_subset.xml`.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI

HERE = Path(__file__).resolve().parent
UI_API = HERE.parent
REPO = UI_API.parents[1]
for p in (str(REPO), str(UI_API)):
    if p not in sys.path:
        sys.path.insert(0, p)

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 5, 22, 0, tzinfo=IST)          # Thu 5 Nov 2026 22:00 IST (after the 21:00 / 21:30 slots)
DATA_SVC = "http://localhost:8001"
MASTER_CTL = "http://localhost:8008"
SPAN_FIXTURE = HERE / "fixtures" / "span_nsccl_20261104_subset.xml"
IV_CSV = REPO / "reports" / "terminal_v2" / "R-IV" / "iv_compare_NIFTY.csv"


def _f(v: str) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── IV store (PLAN 1.1 tables) ───────────────────────────────────────────────────────────────────────────────
def iv_summary_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with IV_CSV.open(encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            iv30 = _f(r["iv30_cm"])
            rv = _f(r["rv20"])
            rows.append({
                "date": r["date"], "symbol": "NIFTY", "spot": _f(r["spot"]), "iv30_cm": iv30,
                "iv60_cm": round(iv30 + 0.4, 2) if iv30 is not None else None, "iv90_cm": round(iv30 + 0.7, 2) if iv30 is not None else None,
                "near_atm_iv": _f(r["near_atm_iv"]), "near_expiry": r["near_expiry"], "near_dte": int(r["near_dte"]),
                "monthly_atm_iv": _f(r["monthly_atm_iv"]), "monthly_expiry": r["monthly_expiry"],
                "skew_25d_30": _f(r["monthly_skew_25d"]), "term_slope_30_90": 0.7, "iv_rank_252": None, "iv_pctile_252": None,
                "rv20_cc": rv, "rv20_parkinson": round(rv * 0.9, 2) if rv is not None else None, "rv20_yz": round(rv * 0.95, 2) if rv is not None else None,
                "fovolt_ann": round(rv * 1.05, 2) if rv is not None else None, "iv_minus_rv20": round(iv30 - rv * 0.95, 2) if (iv30 is not None and rv is not None) else None,
                "expected_move_1d_pct": round(iv30 / 100 / 252 ** 0.5 * 100, 3) if iv30 is not None else None,
                "quality_flags": "", "model_version": "b76-pcp-v1", "r_source": "rate_curve 6.5 % constant", "first_seen_at": "2026-11-04T21:05:00",
            })
    # the stored rank / percentile on the last row (what iv_eod writes); earlier rows left null on purpose
    vals = [x["iv30_cm"] for x in rows if x["iv30_cm"] is not None][-252:]
    lo, hi, today = min(vals), max(vals), vals[-1]
    rows[-1]["iv_rank_252"] = round((today - lo) / (hi - lo) * 100, 1)
    rows[-1]["iv_pctile_252"] = round(sum(1 for v in vals[:-1] if v < today) / (len(vals) - 1) * 100, 1)
    return rows


IV_SUMMARY = iv_summary_rows()
VIX_ROWS = [{"date": r["date"], "close": None, "source": "nse_daily_file"} for r in IV_SUMMARY]
with IV_CSV.open(encoding="utf-8") as _fh:
    for _i, _r in enumerate(csv.DictReader(_fh)):
        VIX_ROWS[_i]["close"] = _f(_r["vix"])

IV_EXPIRY_20261104 = [
    {"date": "2026-11-04", "symbol": "NIFTY", "expiry": "2026-11-09", "dte": 5, "forward": 23975.4, "forward_source": "pcp", "atm_iv": 14.56,
     "iv_25d_put": 16.1, "iv_25d_call": 13.6, "skew_25d": 2.5, "iv_10d_put": 18.2, "iv_10d_call": 13.1, "n_iv_strikes": 61,
     "call_oi": 12_000_000, "put_oi": 13_500_000, "pcr": 1.125, "expected_move_pct": 1.73, "quality_flags": "", "model_version": "b76-pcp-v1"},
    {"date": "2026-11-04", "symbol": "NIFTY", "expiry": "2026-11-23", "dte": 19, "forward": 24010.1, "forward_source": "future", "atm_iv": 13.06,
     "iv_25d_put": 14.5, "iv_25d_call": 12.3, "skew_25d": 2.22, "iv_10d_put": 16.0, "iv_10d_call": 11.9, "n_iv_strikes": 74,
     "call_oi": 9_000_000, "put_oi": 9_900_000, "pcr": 1.1, "expected_move_pct": 2.98, "quality_flags": "", "model_version": "b76-pcp-v1"},
    {"date": "2026-11-04", "symbol": "NIFTY", "expiry": "2026-11-04", "dte": 0, "forward": 23960.6, "forward_source": "spot", "atm_iv": None,
     "iv_25d_put": None, "iv_25d_call": None, "skew_25d": None, "iv_10d_put": None, "iv_10d_call": None, "n_iv_strikes": 0,
     "call_oi": 0, "put_oi": 0, "pcr": None, "expected_move_pct": None, "quality_flags": "expiry_day", "model_version": "b76-pcp-v1"},
]
IV_EXPIRY_GHOST = [{**IV_EXPIRY_20261104[0], "date": "2026-10-05", "expiry": "2026-10-13", "dte": 8, "atm_iv": 11.2}]


def _surface(expiry: str, forward: float, base_iv: float, date_: str = "2026-11-04") -> list[dict[str, Any]]:
    out = []
    for k in (-3, -2, -1, 0, 1, 2, 3):
        strike = round(forward / 50) * 50 + k * 100
        lm = (strike / forward) ** 0.5 - 1
        for opt in ("CE", "PE"):
            untraded = k == 3 and opt == "PE"
            out.append({"date": date_, "symbol": "NIFTY", "expiry": expiry, "strike": strike, "opt_type": opt,
                        "price": None if untraded else 100.0, "price_source": "none" if untraded else "close",
                        "iv": None if untraded else round(base_iv + 0.6 * k * k, 2), "delta": None if untraded else (0.5 - 0.1 * k if opt == "CE" else -0.5 - 0.1 * k),
                        "log_moneyness": round(lm, 5), "oi": 100_000, "volume": 0 if untraded else 5000})
    return out


IV_SURFACE_20261104 = _surface("2026-11-09", 23975.4, 14.56) + _surface("2026-11-23", 24010.1, 13.06)
IV_SURFACE_GHOST = _surface("2026-10-13", 25100.0, 11.2, "2026-10-05")
IV_EVENTS_INFY = [
    {"symbol": "INFY", "released_at": "2026-10-16T15:45:00", "expiry": "2026-10-27", "iv_pre_5d": 38.1, "iv_pre_1d": 41.0, "iv_post_1d": 24.2,
     "crush_pct": -41.0, "implied_move_pct": 4.1, "realised_move_pct": 2.9, "first_seen_at": "2026-10-17T21:05:00"},
    {"symbol": "INFY", "released_at": "2026-07-23T15:50:00", "expiry": "2026-07-28", "iv_pre_5d": 33.0, "iv_pre_1d": 36.5, "iv_post_1d": 23.0,
     "crush_pct": -37.0, "implied_move_pct": 3.8, "realised_move_pct": 5.2, "first_seen_at": "2026-07-24T21:05:00"},
]
IV_EVENTS_NIFTY = [{"symbol": "NIFTY", "released_at": "2026-02-01T11:00:00", "expiry": "2026-02-03", "iv_pre_5d": 15.0, "iv_pre_1d": 16.5,
                    "iv_post_1d": 13.1, "crush_pct": -20.6, "implied_move_pct": 1.4, "realised_move_pct": 0.9, "first_seen_at": "2026-02-02T21:05:00"}]


def _intraday() -> list[dict[str, Any]]:
    out = []
    for ts, atm_iv, mid_c, mid_p in (("2026-11-05T09:20:00+05:30", 14.9, 150.0, 152.0), ("2026-11-05T09:35:00+05:30", 14.4, 140.0, 141.0)):
        for strike, dc in ((23900, 40.0), (24000, 0.0), (24100, -40.0)):
            out.append({"ts": ts, "symbol": "NIFTY", "expiry": "2026-11-09", "strike": strike, "opt_type": "CE", "mid": mid_c + dc,
                        "iv": atm_iv + abs(dc) / 100, "nse_iv": atm_iv + 0.3, "oi": 1_000_000, "source": "breeze"})
            out.append({"ts": ts, "symbol": "NIFTY", "expiry": "2026-11-09", "strike": strike, "opt_type": "PE", "mid": mid_p - dc,
                        "iv": atm_iv + abs(dc) / 100 + 0.2, "nse_iv": atm_iv + 0.5, "oi": 1_200_000, "source": "breeze"})
            out.append({"ts": ts, "symbol": "NIFTY", "expiry": "2026-11-17", "strike": strike, "opt_type": "CE", "mid": 200.0 + dc,
                        "iv": 13.5, "nse_iv": None, "oi": 500_000, "source": "breeze"})
    return out


IV_INTRADAY = _intraday()
SCREEN_ROWS = [
    {"symbol": "NIFTY", "date": "2026-11-04", "spot": 23960.6, "iv30_cm": 12.81, "iv_rank_252": 21.2, "iv_pctile_252": 60.0, "rv20_yz": 15.2,
     "iv_minus_rv20": -2.4, "term_slope_30_90": 0.7, "skew_25d_30": 2.22, "next_results": None, "ban": False, "mwpl_pct": None},
    {"symbol": "INFY", "date": "2026-11-04", "spot": 1490.0, "iv30_cm": 26.0, "iv_rank_252": 55.0, "iv_pctile_252": 71.0, "rv20_yz": 20.1,
     "iv_minus_rv20": 5.9, "term_slope_30_90": -1.2, "skew_25d_30": 1.1, "next_results": "2026-11-12", "ban": False, "mwpl_pct": 12.0},
    {"symbol": "RELIANCE", "date": "2026-11-04", "spot": 1420.0, "iv30_cm": 22.0, "iv_rank_252": 30.0, "iv_pctile_252": 44.0, "rv20_yz": 19.0,
     "iv_minus_rv20": 3.0, "term_slope_30_90": 0.4, "skew_25d_30": 1.9, "next_results": "2027-01-20", "ban": False, "mwpl_pct": 8.0},
    {"symbol": "KAYNES", "date": "2026-11-04", "spot": 5400.0, "iv30_cm": 48.0, "iv_rank_252": 80.0, "iv_pctile_252": 92.0, "rv20_yz": 40.0,
     "iv_minus_rv20": 8.0, "term_slope_30_90": -3.0, "skew_25d_30": 4.0, "next_results": "2026-11-08", "ban": True, "mwpl_pct": 96.0},
    {"symbol": "IDEA", "date": "2026-11-04", "spot": 9.0, "iv30_cm": None, "iv_rank_252": None, "iv_pctile_252": None, "rv20_yz": 60.0,
     "iv_minus_rv20": None, "term_slope_30_90": None, "skew_25d_30": None, "next_results": "2026-11-06", "ban": False, "mwpl_pct": 70.0},
]


# ── index drivers (PLAN 1.2 tables): a 3-member index whose identity holds exactly ───────────────────────────
MEMBERS = (("HDFCBANK", "Financial Services", 0.5), ("INFY", "Information Technology", 0.3), ("ITC", "Fast Moving Consumer Goods", 0.2))


def drivers_fixture(sessions: int = 70) -> dict[str, list[dict[str, Any]]]:
    contrib, fit, weights, state = [], [], [], []
    level = 24000.0
    day = date(2026, 7, 27)
    rets = {"HDFCBANK": [0.5, -0.3, 1.0, 0.2, -0.6], "INFY": [-0.8, 0.4, -1.2, 0.3, 0.9], "ITC": [0.2, 0.1, -0.1, 0.4, -0.2]}
    n = 0
    while n < sessions:
        if day.weekday() < 5 and day != date(2026, 10, 2):
            prev = level
            pts_sum = 0.0
            for sym, ind, w in MEMBERS:
                r = rets[sym][n % 5] + (0.05 if sym == "HDFCBANK" and n > 40 else 0.0)
                pts = prev * w * r / 100
                pts_sum += pts
                contrib.append({"index_name": "NIFTY 50", "date": day.isoformat(), "symbol": sym, "industry": ind, "ret_pct": r,
                                "weight_pct": w * 100, "points": round(pts, 4), "prev_index_level": prev, "index_close_source": "nse_daily_file",
                                "flag": None, "computed_at": "2026-11-04T19:25:00"})
                weights.append({"index_name": "NIFTY 50", "date": day.isoformat(), "symbol": sym, "industry": ind, "method": "rebuilt_calibrated",
                                "weight_pct": w * 100, "iwf_correction": 1.0, "computed_at": "2026-11-04T19:25:00"})
            residual = 0.5 if n % 7 == 0 else -0.25
            level = prev + pts_sum + residual
            fit.append({"index_name": "NIFTY 50", "date": day.isoformat(), "actual_points": round(pts_sum + residual, 4),
                        "explained_points": round(pts_sum, 4), "residual_points": residual, "members_priced": 3, "members_total": 3,
                        "prev_index_level": prev, "computed_at": "2026-11-04T19:25:00"})
            n += 1
        day += timedelta(days=1)
    last = contrib[-1]["date"]
    for window, leader, tenure, share, changed_from, change_date in ((20, "HDFCBANK", 14, 0.61, "INFY", "2026-10-14"), (60, "HDFCBANK", 45, 0.55, None, None)):
        state.append({"index_name": "NIFTY 50", "date": last, "window_sessions": window, "leader": leader, "leader_points": 120.5,
                      "leader_share": share, "tenure_sessions": tenure, "changed_from": changed_from, "change_date": change_date,
                      "top5_share": 1.0, "hhi_contrib": 0.45, "weight_hhi": 0.38, "effective_n": 2.6, "ew_minus_cw_pp": -1.3,
                      "members_up": 2, "members_down": 1, "computed_at": "2026-11-04T19:25:00"})
    # an older revision of the 20-session state row that the latest computed_at must beat
    state.append({**state[0], "leader": "STALE", "computed_at": "2026-11-03T19:25:00"})
    return {"contribution": contrib, "fit": fit, "weights": weights, "state": state}


DRIVERS = drivers_fixture()
HISTORY_INFY = [{"date": (date(2026, 11, 4) - timedelta(days=i)).isoformat(), "close": 1500.0 - i * 2.0} for i in range(0, 60) if (date(2026, 11, 4) - timedelta(days=i)).weekday() < 5]
DESK_STATUS_CASH = {"meta": {"cash": 500000.0}, "latest": {"date": "2026-10-30", "nav": 512345.0, "positions": 0},
                    "positions": [], "nav": [{"date": "2026-10-28", "nav": 510000.0, "positions": 12}, {"date": "2026-10-29", "nav": 511000.0, "positions": 0},
                                             {"date": "2026-10-30", "nav": 512345.0, "positions": 0}], "plans": [], "events": [], "realized": []}
DESK_STATUS_INVESTED = {"meta": {"cash": 100000.0}, "latest": {"date": "2026-11-04", "nav": 520000.0, "positions": 1},
                        "positions": [{"symbol": "INFY", "qty": 100, "avg_cost": 1400.0, "last": 1500.0, "value": 150000.0, "pnl_pct": 7.1,
                                       "since": "2026-10-01", "sector": "Information Technology"}],
                        "nav": [{"date": d["date"], "nav": 500000.0 + i * 500, "positions": 1} for i, d in enumerate(reversed(HISTORY_INFY))],
                        "plans": [], "events": [], "realized": []}

# ── data health inputs (R-DATA §3, 4 Nov 2026 column "stored as-of") ─────────────────────────────────────────
POSITIONS_META = {
    "nse_fo_daily": {"first": "2019-10-01", "last": "2026-11-05", "rows": 330000}, "nse_participant_oi": {"first": "2019-10-01", "last": "2026-11-05", "rows": 9000},
    "nse_deals": {"first": "2024-01-01", "last": "2026-11-05", "rows": 50000}, "nse_mtf": {"first": "2024-06-01", "last": "2026-11-03", "rows": 8000},
    "nse_insider_trades": {"first": "2024-01-01", "last": "2026-10-30", "rows": 12000}, "nse_shareholding": {"first": "2023-01-01", "last": "2026-10-27", "rows": 4000},
    "nse_bhavcopy": {"first": "2010-01-04", "last": "2026-11-05", "rows": 8260000}, "nse_events": {"first": "2026-01-01", "last": "2026-12-05", "rows": 776},
    "nse_results": {"first": "2024-01-01", "last": "2026-10-30 20:49:00", "rows": 9000}, "nse_fii_dii_cash": {"first": "2026-10-09", "last": "2026-11-05", "rows": 30},
    "gold_cot": {"first": "1986-01-01", "last": "2026-10-27", "rows": 2100}, "gold_series": {"first": "2000-01-01", "last": "2026-11-04", "rows": 90000},
    "gold_daily_bars": {"first": "2000-01-01", "last": "2026-11-04", "rows": 60000}, "gold_etf_holdings": {"first": "2004-11-18", "last": "2026-10-30", "rows": 5400},
    "gold_health_daily": {"first": "2026-10-30", "last": "2026-10-30", "rows": 1},
}
FRESHNESS = {"latest_bar_date": "2026-11-05", "eligible_tickers": 1496, "eligible_current": 1482, "eligible_stale": 14, "ml_features_latest_date": "2026-11-05",
             "ml_labels_latest_date": "2026-10-28", "nifty_index_latest_date": "2026-11-05", "features_lag_days": 0, "bars_quarantined": 6, "features_fresh": True}
ARCHIVE_META = {"archive:preopen": {"rows": 13, "first": "2026-10-09", "last": "2026-11-05"}, "archive:internals": {"rows": 10, "first": "2026-10-13", "last": "2026-10-30"},
                "archive:financials": {"rows": 1200, "first": None, "last": "2026-11-04"}}
HOLIDAYS = {"holidays": [{"date": "2026-11-20", "weekday": "Fri", "description": "Guru Nanak Jayanti"}, {"date": "2026-10-02", "weekday": "Fri", "description": "Gandhi Jayanti"}],
            "source": "nseindia.com/api/holiday-master?type=trading"}
SCHEDULER = {"scheduler_running": True, "jobs": [
    {"id": "nse_positions_catchup", "name": "NSE positions catch-up", "next_run_ist": "2026-11-06T20:30:00+05:30", "last_status": "ok", "last_run_ts": "2026-11-05T20:31:00+05:30", "last_latency_ms": 41000},
    {"id": "results_capture_daily", "name": "results", "next_run_ist": "2026-11-06T20:45:00+05:30", "last_status": "error", "last_run_ts": "2026-10-30T20:49:00+05:30", "last_latency_ms": 5000},
    {"id": "internals_sample", "name": "internals", "next_run_ist": "2026-11-06T09:17:00+05:30", "last_status": "ok", "last_run_ts": "2026-10-30T15:29:00+05:30", "last_latency_ms": 300},
    {"id": "startup_catchup", "name": "catch-up", "next_run_ist": None, "last_status": "ok", "last_run_ts": "2026-11-05T08:35:00+05:30", "last_latency_ms": 900}],
    "ist_now": NOW.isoformat()}
INGEST_LOG = {"rows": [{"dataset": "archive:internals", "date": "2026-11-05", "status": "gap", "note": "stack down"},
                       {"dataset": "nse_fo_daily", "date": "2026-11-05", "status": "ok", "sha256": "abc", "rows": 180000}]}

def _b1_row(id_: str, state: str, as_of: str | None, lag: int | None, *, job: str | None, cadence: str = "daily", kind: str = "table",
            expected_by: str | None = "21:00", note: str | None = None, pages: str = "DERV", unrecoverable: bool = False) -> dict[str, Any]:
    """One row in the exact shape of data-service `GET /db/data-health` (services/data-service/data_health/reads.py health())."""
    return {"id": id_, "label": f"{id_} (B1 catalog)", "pages": [p for p in pages.split(",") if p], "publisher": "NSE (nsearchives.nseindia.com)",
            "published_ist": "20:10 (measured)", "expected_by": expected_by, "expected_offset_days": 0, "cadence": cadence, "max_age_sessions": 1,
            "unrecoverable": unrecoverable, "job_id": job, "freshness_kind": kind, "dictionary_anchor": f"docs/TERMINAL_DATA_DICTIONARY.md#{id_}",
            "verdict": "PUBLISH-CORE", "badge": "arithmetic", "catalog_note": None, "last_fetch": None, "gap_dates": [],
            "as_of": as_of, "last_session": "2026-11-05", "lag_sessions": lag, "due_session": "2026-11-05", "expected_at": "2026-11-05T21:00:00+05:30",
            "state": state, "note": note}


B1_HEALTH = {"as_of": "2026-11-05T16:30:00Z", "now_ist": NOW.isoformat(), "last_session": "2026-11-05", "badges": {"state": "arithmetic"},
             "summary": {"fresh": 2, "amber": 1, "red": 1, "gap": 1, "unknown": 4},
             "note": "no composite score; endpoint rows are completed by ui-api",
             "rows": [
                 _b1_row("nse_fo_daily", "fresh", "2026-11-05", 0, job="nse_positions_catchup", pages="DERV,OMON"),
                 _b1_row("nse_mtf", "fresh", "2026-11-04", 1, job="nse_positions_catchup", expected_by="23:00", pages="MRGN",
                         note="due by 23:00 IST for the last session"),
                 _b1_row("nse_combined_oi", "amber", "2026-11-04", 1, job="nse_positions_catchup", note="1 session(s) behind the expected one"),
                 _b1_row("nse_results", "red", "2026-10-30", 4, job="results_capture_daily", expected_by="21:30", pages="ERN,EVTS",
                         note="4 session(s) behind the expected one"),
                 _b1_row("archive:internals", "gap", "2026-10-30", 4, job="internals_sample", kind="archive", cadence="session", expected_by="15:35",
                         pages="MOV,WRAP", unrecoverable=True, note="no capture for the session (gap row)"),
                 _b1_row("option_chain_eod", "unknown", None, None, job="nse_positions_catchup", kind="endpoint", cadence="derived", pages="OMON",
                         note="composed by ui-api (telemetry / live feed)"),
                 _b1_row("desk_mark", "unknown", None, None, job="results_capture_daily", kind="endpoint", cadence="derived", pages="DESK",
                         note="composed by ui-api (telemetry / live feed)"),
                 _b1_row("nse_live", "unknown", None, None, job=None, kind="endpoint", cadence="live", expected_by=None, pages="MOV,WTCH",
                         note="composed by ui-api (telemetry / live feed)"),
                 _b1_row("market_monitor", "unknown", None, None, job="eod_data_pipeline", kind="endpoint", cadence="derived", pages="MKT",
                         note="composed by ui-api (telemetry / live feed)"),
             ]}
OPTION_HISTORY_LEGACY = {"symbol": "NIFTY", "rows": [{"date": r["date"], "atm_iv": r["near_atm_iv"], "pcr": 1.0, "max_pain": 24000} for r in IV_SUMMARY[-300:]], "updating": False}


# ── the fake transport ───────────────────────────────────────────────────────────────────────────────────────
class Recorder:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict[str, str]]] = []   # (host, path, params)

    def hosts(self) -> set[str]:
        return {h for h, _, _ in self.requests}

    def paths(self) -> list[str]:
        return [p for _, p, _ in self.requests]


def _json(body: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=body)


def make_handler(rec: Recorder, *, iv_tables: bool = True, drivers_tables: bool = True, catalog: bool = False):
    def handler(request: httpx.Request) -> httpx.Response:
        host, path = request.url.host, request.url.path
        params = {k: v for k, v in request.url.params.items()}
        rec.requests.append((host, path, params))
        if host not in ("localhost", "127.0.0.1"):
            return _json({"detail": "publisher reached"}, 404)
        if path.startswith("/db/iv/"):
            if not iv_tables:
                return _json({"detail": "Not Found"}, 404)
            sym = params.get("symbol", "NIFTY")
            days = int(params.get("days", 750))
            if path == "/db/iv/summary":
                return _json({"symbol": sym, "rows": IV_SUMMARY[-days:] if sym == "NIFTY" else [], "model_version": "b76-pcp-v1", "r_source": "rate_curve 6.5 % constant"})
            if path == "/db/iv/vix":
                return _json({"rows": VIX_ROWS[-days:]})
            if path == "/db/iv/events":
                rows = IV_EVENTS_INFY if sym == "INFY" else IV_EVENTS_NIFTY if sym == "NIFTY" else []
                return _json({"symbol": sym, "rows": rows[: int(params.get("n", 8))]})
            if path == "/db/iv/expiry":
                ghost = params.get("date", "") < "2026-11-01" if params.get("date") else False
                return _json({"symbol": sym, "rows": (IV_EXPIRY_GHOST if ghost else IV_EXPIRY_20261104) if sym == "NIFTY" else []})
            if path == "/db/iv/surface":
                ghost = params.get("date", "") < "2026-11-01" if params.get("date") else False
                return _json({"symbol": sym, "rows": (IV_SURFACE_GHOST if ghost else IV_SURFACE_20261104) if sym == "NIFTY" else []})
            if path == "/db/iv/intraday":
                return _json({"symbol": sym, "rows": IV_INTRADAY if sym == "NIFTY" else []})
            if path == "/db/iv/screen":
                return _json({"date": "2026-11-04", "rows": SCREEN_ROWS})
            return _json({"detail": "Not Found"}, 404)
        if path.startswith("/db/index-drivers/"):
            if not drivers_tables:
                return _json({"detail": "Not Found"}, 404)
            table = path.rsplit("/", 1)[-1]
            rows = DRIVERS.get(table, [])
            if table == "weights" and params.get("date"):
                rows = [r for r in rows if r["date"] == params["date"]]
            if params.get("days") and table in ("contribution", "fit", "state"):
                rows = rows[-int(params["days"]) * (3 if table == "contribution" else 1):]
            return _json({"index": params.get("index"), "rows": rows})
        if path.startswith("/db/security/") and path.endswith("/history"):
            return _json({"found": True, "symbol": "INFY", "rows": HISTORY_INFY})
        if path == "/db/option-history/NIFTY":
            return _json(OPTION_HISTORY_LEGACY)
        if path == "/db/nse-positions-meta":
            return _json(POSITIONS_META)
        if path == "/db/freshness":
            return _json(FRESHNESS)
        if path == "/db/archive-meta":
            return _json(ARCHIVE_META)
        if path == "/db/market-holidays":
            return _json(HOLIDAYS)
        if path == "/db/data-health":                     # B1 deployed (catalog=True) → its computed rows; else 404 as on the live stack today
            return _json(B1_HEALTH) if catalog else _json({"detail": "Not Found"}, 404)
        if path == "/db/data-health/ingest-log":
            return _json(INGEST_LOG)
        if path == "/api/scheduler/status":
            return _json(SCHEDULER)
        return _json({"detail": f"no fixture for {path}"}, 404)
    return handler


def install_fake_transport(monkeypatch: Any, **kw: Any) -> Recorder:
    """Route the process-wide async client through a MockTransport; return the recorder of every request."""
    import routers.data_health as dh
    import routers.derivatives as drv
    import routers.markets as mk
    from shared import http_client

    rec = Recorder()
    handler = make_handler(rec, **kw)
    clients: dict[int, httpx.AsyncClient] = {}

    def fake_client() -> httpx.AsyncClient:
        import asyncio
        try:
            key = id(asyncio.get_running_loop())
        except RuntimeError:
            key = 0
        c = clients.get(key)
        if c is None or c.is_closed:
            c = clients[key] = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="")
        return c

    monkeypatch.setattr(http_client, "get_async_client", fake_client)
    monkeypatch.setattr(drv, "DATA_SVC", DATA_SVC)
    monkeypatch.setattr(mk, "DATA_SVC", DATA_SVC)
    monkeypatch.setattr(dh, "DATA_SVC", DATA_SVC)
    monkeypatch.setattr(dh, "MASTER_CTL", MASTER_CTL)
    monkeypatch.setattr(dh, "now_ist", lambda: NOW)
    http_client.reset_state()
    drv._ttl.clear()
    mk._drivers_ttl.clear()
    dh._ttl.clear()
    for cache in (drv.STORE, mk.DRIVERS_STORE, mk._DESK_STORE, dh.STORE):
        cache.invalidate()
    return rec


def make_app() -> FastAPI:
    """The Terminal v2 routers on a bare app (main.py's lifespan warms Breeze / Yahoo — never in a test)."""
    from routers import data_health, derivatives, markets, options_strategy, positions

    app = FastAPI()
    app.include_router(derivatives.router, prefix="/api/derivatives")
    app.include_router(markets.router, prefix="/api/market")
    app.include_router(markets.attribution_router, prefix="/api/desk")
    app.include_router(options_strategy.router, prefix="/api/options")
    app.include_router(data_health.router, prefix="/api/data")
    app.include_router(positions.router, prefix="/api/positions")
    return app


CONDOR_LEGS = [
    {"side": "sell", "kind": "PE", "strike": 23700, "expiry": "2026-11-09", "premium": 73.5, "lots": 1, "lot_size": 65},
    {"side": "buy", "kind": "PE", "strike": 23500, "expiry": "2026-11-09", "premium": 35.45, "lots": 1, "lot_size": 65},
    {"side": "sell", "kind": "CE", "strike": 24200, "expiry": "2026-11-09", "premium": 66.1, "lots": 1, "lot_size": 65},
    {"side": "buy", "kind": "CE", "strike": 24400, "expiry": "2026-11-09", "premium": 31.7, "lots": 1, "lot_size": 65},
]
BREEZE_MARGIN_SAMPLE = {"Success": {"margin_calulation": [{"strike_price": "23700", "quantity": "65", "right": "Put", "product": "Options", "action": "Sell",
                                                           "price": "73.5", "expiry_date": "09-Nov-2026", "stock_code": "NIFTY"}] * 4,
                                    "non_span_margin_required": "31135.78", "order_value": "4777.5", "order_margin": "0", "trade_margin": None,
                                    "block_trade_margin": "0", "span_margin_required": "81497.07"}, "Status": 200, "Error": None}


def span_zip(tmp_path: Path) -> Path:
    """The real-format SPAN subset as nsccl.20261104.s.zip in a temp archive dir (what the 20:30 pass would store)."""
    import zipfile
    d = tmp_path / "span"
    d.mkdir(exist_ok=True)
    z = d / "nsccl.20261104.s.zip"
    with zipfile.ZipFile(z, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("nsccl.20261104.s.spn", SPAN_FIXTURE.read_text(encoding="utf-8"))
    return d


def dump(obj: Any) -> str:
    return json.dumps(obj, indent=1, sort_keys=True, default=str)
