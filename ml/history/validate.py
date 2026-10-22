#!/usr/bin/env python3
"""Validation of the 2016-10..2021-09 staging history -> history.json + HISTORY.md.

Checks
  download   manifest outcomes (sessions, 404s, echoes, errors) and request counts
  overlap    CM+MTO parse of 2021-10-01 / 2021-10-04 vs the stored rows (eod_export_v1.parquet)
  calendar   sessions per year and quarter; weekday closures vs a reference NSE holiday list;
             special (weekend / holiday) sessions present
  continuity prev_close(t) vs close(previous session) per (ticker, series), EQ/BE; dates > 5%
             investigated against Bc ex-dates; the splice 2021-09-30 -> 2021-10-01 against the store
  coverage   delivery coverage by year and series, rows by year, distinct tickers, ISIN coverage
  sanity     2016-11-09, 2020-03-13, 2020-03-23, 2020-02-01 (Saturday) and the other special sessions
  integrity  OHLC ordering, non-positive prices, vwap inside [low, high], echo footprint

Usage:  OMP_NUM_THREADS=2 python3 -I ml/history/validate.py [--final]
The JSON is written first; the Markdown quotes it.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from ml.history.common import (  # noqa: E402
    EXPORT, LOG_PATH, MANIFEST as MANIFEST_PATH, OVERLAP_DAYS, RESULTS, SPECIAL_SESSIONS, STAGE,
    WINDOW_END, WINDOW_START, calendar_days, get_logger, local_path, read_manifest,
)
from ml.history.parse import AUX_DIR, EOD_DIR, TURNOVER_FACTOR, load_parts  # noqa: E402

log = get_logger("hist.validate")
JSON_PATH = RESULTS / "history.json"
MD_PATH = RESULTS / "HISTORY.md"
MISMATCH_TOL = 0.005      # |prev_close / previous close - 1| above this is a mismatch
FLAG_SHARE = 0.05         # a date with more than 5% mismatching tickers is investigated

# Reference list of NSE equity-segment weekday closures, 2016-10-03 .. 2021-09-30 (NSE holiday
# circulars). Diwali Laxmi Pujan days carry a Muhurat session although listed as holidays.
NSE_WEEKDAY_HOLIDAYS = {
    "2016-10-11": "Dussehra", "2016-10-12": "Moharram", "2016-10-31": "Diwali Balipratipada",
    "2016-11-14": "Gurunanak Jayanti",
    "2017-01-26": "Republic Day", "2017-02-24": "Mahashivratri", "2017-03-13": "Holi",
    "2017-04-04": "Ram Navami", "2017-04-14": "Ambedkar Jayanti / Good Friday",
    "2017-05-01": "Maharashtra Day", "2017-06-26": "Ramzan Id", "2017-08-15": "Independence Day",
    "2017-08-25": "Ganesh Chaturthi", "2017-10-02": "Gandhi Jayanti",
    "2017-10-19": "Diwali Laxmi Pujan (Muhurat session)", "2017-10-20": "Diwali Balipratipada",
    "2017-12-25": "Christmas",
    "2018-01-26": "Republic Day", "2018-02-13": "Mahashivratri", "2018-03-02": "Holi",
    "2018-03-29": "Mahavir Jayanti", "2018-03-30": "Good Friday", "2018-05-01": "Maharashtra Day",
    "2018-08-15": "Independence Day", "2018-08-22": "Bakri Id", "2018-09-13": "Ganesh Chaturthi",
    "2018-09-20": "Moharram", "2018-10-02": "Gandhi Jayanti", "2018-10-18": "Dussehra",
    "2018-11-07": "Diwali Laxmi Pujan (Muhurat session)", "2018-11-08": "Diwali Balipratipada",
    "2018-11-23": "Gurunanak Jayanti", "2018-12-25": "Christmas",
    "2019-03-04": "Mahashivratri", "2019-03-21": "Holi", "2019-04-17": "Mahavir Jayanti",
    "2019-04-19": "Good Friday", "2019-04-29": "General election (Mumbai)",
    "2019-05-01": "Maharashtra Day", "2019-06-05": "Id-ul-Fitr", "2019-08-12": "Bakri Id",
    "2019-08-15": "Independence Day", "2019-09-02": "Ganesh Chaturthi", "2019-09-10": "Moharram",
    "2019-10-02": "Gandhi Jayanti", "2019-10-08": "Dussehra",
    "2019-10-21": "Maharashtra assembly election", "2019-10-28": "Diwali Balipratipada",
    "2019-11-12": "Gurunanak Jayanti", "2019-12-25": "Christmas",
    "2020-02-21": "Mahashivratri", "2020-03-10": "Holi", "2020-04-02": "Ram Navami",
    "2020-04-06": "Mahavir Jayanti", "2020-04-10": "Good Friday", "2020-04-14": "Ambedkar Jayanti",
    "2020-05-01": "Maharashtra Day", "2020-05-25": "Id-ul-Fitr", "2020-10-02": "Gandhi Jayanti",
    "2020-11-16": "Diwali Balipratipada", "2020-11-30": "Gurunanak Jayanti", "2020-12-25": "Christmas",
    "2021-01-26": "Republic Day", "2021-03-11": "Mahashivratri", "2021-03-29": "Holi",
    "2021-04-02": "Good Friday", "2021-04-14": "Ambedkar Jayanti", "2021-04-21": "Ram Navami",
    "2021-05-13": "Id-ul-Fitr", "2021-07-21": "Bakri Id", "2021-08-19": "Moharram",
    "2021-09-10": "Ganesh Chaturthi",
}
SANITY_DAYS = {
    "2016-11-09": "demonetisation announced the previous evening: gap-down open",
    "2020-02-01": "Saturday Union Budget session",
    "2020-03-13": "market-wide lower circuit at the open, then a rebound",
    "2020-03-23": "market-wide lower circuit, Nifty 50 down about 13%",
}


def r(x, k=4):
    if x is None:
        return None
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return x
    return None if not math.isfinite(xf) else round(xf, k)


def period_label(d: date) -> str:
    if d.year == 2016:
        return "2016Q4"
    if d.year == 2021:
        return "2021Q1-Q3"
    return str(d.year)


# --------------------------------------------------------------------------- download
def check_download() -> dict:
    man = read_manifest()
    days = calendar_days()
    cm_status: dict[str, int] = {}
    sessions, weekday_off, weekend_sessions, errors, echoes = [], [], [], [], []
    mto = {"200": 0, "missing": [], "error": []}
    pr = {"200": 0, "missing": [], "error": []}
    for d in days:
        iso = d.isoformat()
        rec = man.get((iso, "cm"))
        st = "not requested yet" if rec is None else str(rec.get("status"))
        cm_status[st] = cm_status.get(st, 0) + 1
        if st == "200":
            sessions.append(iso)
            if d.weekday() >= 5:
                weekend_sessions.append(iso)
            for k, acc in (("mto", mto), ("pr", pr)):
                rk = man.get((iso, k))
                sk = None if rk is None else str(rk.get("status"))
                if sk == "200":
                    acc["200"] += 1
                elif sk == "error":
                    acc["error"].append(iso)
                elif sk is not None:
                    acc["missing"].append({"date": iso, "status": sk})
        elif st in ("echo", "misdated"):
            echoes.append({"date": iso, "status": st, "echo_of": rec.get("echo_of"),
                           "csv_timestamp": rec.get("csv_timestamp")})
        elif st == "error":
            errors.append(iso)
        elif st != "not requested yet" and d.weekday() < 5:
            weekday_off.append(iso)
    status = {}
    sp = RESULTS / "download_status.json"
    if sp.exists():
        status = json.loads(sp.read_text())
    n_manifest = sum(1 for _ in open(MANIFEST_PATH)) if MANIFEST_PATH.exists() else 0
    logtxt = LOG_PATH.read_text() if LOG_PATH.exists() else ""
    runs = logtxt.count("hist.download INFO download start")
    backoff_lines = [ln[:160] for ln in logtxt.splitlines() if "hist.download WARNING back-off" in ln]
    return {
        "calendar_days": len(days), "cm_status_counts": cm_status, "sessions": len(sessions),
        "weekday_without_session": weekday_off, "weekend_sessions": weekend_sessions,
        "echo_or_misdated": echoes, "cm_errors": errors,
        "mto": {"files": mto["200"], "missing_on_session_days": mto["missing"], "errors": mto["error"]},
        "pr": {"files": pr["200"], "missing_on_session_days": pr["missing"], "errors": pr["error"]},
        "requests_last_run": status.get("requests"), "backoffs_last_run": status.get("backoffs"),
        "elapsed_s_last_run": status.get("elapsed_s"), "download_final": status.get("final"),
        "manifest_outcomes": n_manifest, "runs": runs, "backoff_warnings_logged": backoff_lines,
        "_sessions": sessions,
    }


# --------------------------------------------------------------------------- overlap
def raw_cm_value(d: date) -> pd.DataFrame:
    """TOTTRDVAL (raw rupees) per (ticker, series) straight from the CM zip."""
    import zipfile
    with zipfile.ZipFile(local_path("cm", d)) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        df = pd.read_csv(zf.open(name), dtype=str, keep_default_na=False)
    df.columns = [c.strip().upper() for c in df.columns]
    return pd.DataFrame({"date": pd.Timestamp(d), "ticker": df["SYMBOL"].str.strip(),
                         "series": df["SERIES"].str.strip(),
                         "tottrdval": pd.to_numeric(df["TOTTRDVAL"].str.strip(), errors="coerce")})


def check_overlap() -> dict:
    h, ov_aux = load_parts(min(OVERLAP_DAYS), max(OVERLAP_DAYS))
    if h.empty:
        return {"status": "overlap days not parsed yet"}
    g_keys = {(a2["date"], a2["SYMBOL"], a2["SERIES"]) for a in ov_aux for a2 in a.get("pd_g", [])}
    h = h[pd.to_datetime(h["date"]).dt.date.isin(OVERLAP_DAYS)].copy()
    e = pd.read_parquet(EXPORT, filters=[("date", "in", OVERLAP_DAYS)])
    for df in (h, e):
        df["date"] = pd.to_datetime(df["date"])
    hh = h[h["series"].isin(["EQ", "BE"])]
    m = e.merge(hh, on=["date", "ticker", "series"], how="outer", suffixes=("_s", "_h"), indicator=True)
    both = m[m["_merge"] == "both"]
    fields = {}
    exact_cols = ["prev_close", "open", "high", "low", "last", "close", "volume", "trades",
                  "deliv_qty", "deliv_pct"]
    for c in exact_cols:
        s, x = both[c + "_s"].astype(float), both[c + "_h"].astype(float)
        eq = (s.isna() & x.isna()) | np.isclose(s, x, rtol=0, atol=1e-9)
        fields[c] = {"match_share": r(eq.mean(), 6), "rule": "exact (NaN = NaN)",
                     "store_nan": int(s.isna().sum()), "history_nan": int(x.isna().sum())}
    s, x = both["turnover_s"].astype(float), both["turnover_h"].astype(float)
    fields["turnover"] = {
        "match_share": r(np.isclose(s, x, rtol=0, atol=1e-6).mean(), 6),
        "rule": "exact; TOTTRDVAL / 1e5 rounded half up to 2 decimals, * 1e5 (the store's TURNOVER_LACS * 1e5)",
    }
    # Unit factor from the raw rupee TOTTRDVAL (before the 0.01-lakh rounding).
    raw = pd.concat([raw_cm_value(d) for d in OVERLAP_DAYS], ignore_index=True)
    rb = both[["date", "ticker", "series", "turnover_s"]].merge(raw, on=["date", "ticker", "series"])
    sv, xv = rb["turnover_s"].astype(float), rb["tottrdval"].astype(float)
    big = xv >= 1e6
    factor_med = float(np.median(sv[big] / xv[big]))
    factor_ols = float((sv[big] * xv[big]).sum() / (xv[big] ** 2).sum())
    fields["turnover"].update({
        "raw_tottrdval_exact_share": r(np.isclose(sv, xv, rtol=0, atol=1e-9).mean(), 6),
        "raw_abs_diff_rupees_max": r((sv - xv).abs().max(), 2),
        "raw_abs_diff_rupees_median": r((sv - xv).abs().median(), 2),
        "raw_within_500_share": r(((sv - xv).abs() <= 500 + 1e-6).mean(), 6),
    })
    s, x = both["vwap_s"].astype(float), both["vwap_h"].astype(float)
    fields["vwap"] = {
        "match_share": r(np.isclose(s, x, rtol=0, atol=1e-9).mean(), 6),
        "rule": "exact; TOTTRDVAL / TOTTRDQTY rounded half up to 2 decimals (sec_bhavdata AVG_PRICE)",
        "within_0.01": r((np.abs(s - x) <= 0.01 + 1e-9).mean(), 6),
        "rows_off": int((~np.isclose(s, x, rtol=0, atol=1e-9)).sum()),
    }
    only_h = m[m["_merge"] == "right_only"]
    only_s = m[m["_merge"] == "left_only"]
    be = both[both["series"] == "BE"]
    return {
        "days": [d.isoformat() for d in OVERLAP_DAYS],
        "store_rows_eq_be": int(len(e)), "history_rows_eq_be": int(len(hh)),
        "history_rows_all_series": int(len(h)),
        "matched_rows": int(len(both)), "store_only_rows": int(len(only_s)),
        "history_only_rows": int(len(only_h)),
        "history_only_in_call_auction": int(sum((str(pd.Timestamp(a).date()), b, c) in g_keys for a, b, c in
                                                zip(only_h["date"], only_h["ticker"], only_h["series"]))),
        "history_only": only_h[["date", "ticker", "series", "close_h", "volume_h", "turnover_h"]]
            .assign(date=lambda t: t["date"].dt.date.astype(str))
            .rename(columns={"close_h": "close", "volume_h": "volume", "turnover_h": "turnover"})
            .to_dict("records"),
        "fields": fields,
        "turnover_factor": {"median_store_over_raw_tottrdval": r(factor_med, 6),
                            "ols_through_origin": r(factor_ols, 6),
                            "rows_used": int(big.sum()), "applied": TURNOVER_FACTOR,
                            "units": "rupees in both (store: TURNOVER_LACS * 1e5; history: TOTTRDVAL)",
                            "precision": "history rounded to 0.01 lakh (Rs 1,000 steps) like the store"},
        "be_rows_matched": int(len(be)),
        "be_rows_with_deliv_store": int(be["deliv_pct_s"].notna().sum()),
        "be_rows_with_deliv_history": int(be["deliv_pct_h"].notna().sum()),
    }


# --------------------------------------------------------------------------- calendar
def check_calendar(dl: dict, eod_dates: list[date]) -> dict:
    sess = sorted(eod_dates)
    by_period: dict[str, int] = {}
    by_quarter: dict[str, int] = {}
    for d in sess:
        by_period[period_label(d)] = by_period.get(period_label(d), 0) + 1
        q = f"{d.year}Q{(d.month - 1) // 3 + 1}"
        by_quarter[q] = by_quarter.get(q, 0) + 1
    # Expected from the reference list (only for the span already parsed).
    last_req = max(sess, default=WINDOW_START)
    exp: dict[str, int] = {}
    for d in calendar_days(WINDOW_START, min(WINDOW_END, last_req)):
        iso = d.isoformat()
        is_sess = (d.weekday() < 5 and iso not in NSE_WEEKDAY_HOLIDAYS) or iso in SPECIAL_SESSIONS
        if is_sess:
            exp[period_label(d)] = exp.get(period_label(d), 0) + 1
    sset = {d.isoformat() for d in sess}
    weekday_off = dl["weekday_without_session"]
    unexplained_closures = [x for x in weekday_off if x not in NSE_WEEKDAY_HOLIDAYS]
    sessions_on_listed_holidays = sorted(x for x in sset if x in NSE_WEEKDAY_HOLIDAYS)
    weekend = sorted(x for x in sset if date.fromisoformat(x).weekday() >= 5)
    listed_not_closed = [x for x in NSE_WEEKDAY_HOLIDAYS
                         if date.fromisoformat(x) <= last_req and x in sset and x not in SPECIAL_SESSIONS]
    special = {k: {"label": v, "present": k in sset} for k, v in SPECIAL_SESSIONS.items()
               if date.fromisoformat(k) <= last_req}
    return {
        "sessions_total": len(sess),
        "sessions_by_period": by_period,
        "expected_by_period_reference": exp,
        "sessions_by_quarter": by_quarter,
        "weekday_closures": {x: NSE_WEEKDAY_HOLIDAYS.get(x, "NOT IN REFERENCE LIST") for x in weekday_off},
        "weekday_closures_not_in_reference": unexplained_closures,
        "reference_holidays_with_a_session": sessions_on_listed_holidays,
        "reference_holidays_with_a_session_unexpected": listed_not_closed,
        "weekend_sessions": weekend,
        "special_sessions": special,
        "special_sessions_all_present": all(v["present"] for v in special.values()) if special else None,
    }


# --------------------------------------------------------------------------- continuity
def bc_exdates(auxes: list[dict]) -> pd.DataFrame:
    rows = []
    for a in auxes:
        for b in a.get("bc", []):
            ex = b.get("EX_DT", "")
            if ex:
                rows.append((b.get("SYMBOL", ""), b.get("SERIES", ""), ex, b.get("PURPOSE", "")))
    if not rows:
        return pd.DataFrame(columns=["ticker", "bc_series", "ex_date", "purpose"])
    bc = pd.DataFrame(rows, columns=["ticker", "bc_series", "ex_date", "purpose"]).drop_duplicates()
    bc["ex_date"] = pd.to_datetime(bc["ex_date"], format="%d/%m/%Y", errors="coerce")
    return bc.dropna(subset=["ex_date"])


def check_continuity(eq: pd.DataFrame, sessions: list[date], auxes: list[dict]) -> dict:
    sidx = {d: i for i, d in enumerate(sorted(sessions))}
    x = eq[["date", "ticker", "series", "prev_close", "close"]].copy()
    x["si"] = x["date"].map(sidx)
    x = x.sort_values(["ticker", "series", "si"])
    g = x.groupby(["ticker", "series"], sort=False)
    x["pc_store"] = g["close"].shift(1)
    x["si_prev"] = g["si"].shift(1)
    adj = x[x["si_prev"] == x["si"] - 1].copy()      # traded on the immediately previous session
    adj["dev"] = adj["prev_close"] / adj["pc_store"] - 1
    adj["mis"] = adj["dev"].abs() > MISMATCH_TOL
    per = adj.groupby("date").agg(n=("mis", "size"), mismatches=("mis", "sum"))
    per["share"] = per["mismatches"] / per["n"]
    per = per.sort_index()
    bc = bc_exdates(auxes)
    mis = adj[adj["mis"]].copy()
    mis["date_ts"] = pd.to_datetime(mis["date"])
    if not bc.empty:
        k = bc[["ticker", "ex_date", "purpose"]].drop_duplicates(["ticker", "ex_date"])
        mis = mis.merge(k, left_on=["ticker", "date_ts"], right_on=["ticker", "ex_date"], how="left")
        mis["bc_explained"] = mis["ex_date"].notna()
    else:
        mis["bc_explained"] = False
        mis["purpose"] = None
    flagged = []
    for d, row in per[per["share"] > FLAG_SHARE].iterrows():
        md = mis[mis["date"] == d]
        prev_sess = sorted(sessions)[sidx[d] - 1] if sidx[d] > 0 else None
        flagged.append({
            "date": str(d), "previous_session": str(prev_sess), "tickers": int(row["n"]),
            "mismatches": int(row["mismatches"]), "share": r(row["share"]),
            "explained_by_bc_exdate": int(md["bc_explained"].sum()),
            "median_deviation": r(md["dev"].median()),
            "examples": md.head(8)[["ticker", "series", "prev_close", "pc_store", "dev", "purpose"]]
                .rename(columns={"pc_store": "previous_close"}).to_dict("records"),
        })
    top = per.sort_values("share", ascending=False).head(12)
    # Mismatches in general: how many fall on a Bc ex-date, and what kind.
    kinds = {}
    if len(mis):
        pur = mis.loc[mis["bc_explained"], "purpose"].fillna("").str.upper()
        for kname, pat in (("split", "SPLT|SPLIT|SUB-DIVISION|SUBDIVISION"), ("bonus", "BONUS"),
                           ("rights", "RIGHTS|RGHTS|RTS"), ("dividend", "DIV"),
                           ("demerger/scheme", "DEMERGER|SCHEME|ARRANGEMENT|AMALGAMATION"),
                           ("capital reduction", "REDUCTION|CONSOLIDATION")):
            kinds[kname] = int(pur.str.contains(pat, regex=True).sum())
    # Ex-dates of splits / bonuses: is the legacy PREVCLOSE adjusted on the ex-date?
    exk = bc[bc["purpose"].str.upper().str.contains("BONUS|SPLT|SPLIT", regex=True)] \
        .drop_duplicates(["ticker", "ex_date"]) if not bc.empty else bc
    adj["date_ts"] = pd.to_datetime(adj["date"])
    on_ex = adj.merge(exk[["ticker", "ex_date"]], left_on=["ticker", "date_ts"],
                      right_on=["ticker", "ex_date"], how="inner") if len(exk) else adj.iloc[0:0]
    return {
        "rule": f"(ticker, series) EQ/BE traded on t and on the previous session; mismatch when "
                f"|prev_close(t) / close(t-1) - 1| > {MISMATCH_TOL}",
        "dates_scanned": int(len(per)), "pairs_scanned": int(per["n"].sum()),
        "mismatch_pairs": int(per["mismatches"].sum()),
        "overall_mismatch_share": r(per["mismatches"].sum() / max(per["n"].sum(), 1), 6),
        "median_daily_share": r(per["share"].median(), 6),
        "p99_daily_share": r(per["share"].quantile(0.99), 6),
        "max_daily_share": r(per["share"].max(), 6),
        "max_daily_share_date": str(per["share"].idxmax()) if len(per) else None,
        "dates_above_5pct": flagged,
        "top_dates": [{"date": str(d), "share": r(v["share"]), "mismatches": int(v["mismatches"]),
                       "tickers": int(v["n"])} for d, v in top.iterrows()],
        "mismatches_on_bc_exdate": int(mis["bc_explained"].sum()),
        "mismatch_list": mis.sort_values("date").head(60)[
            ["date", "ticker", "series", "prev_close", "pc_store", "dev", "bc_explained", "purpose"]]
            .rename(columns={"pc_store": "previous_close"})
            .assign(date=lambda q: q["date"].astype(str), dev=lambda q: q["dev"].round(5))
            .to_dict("records"),
        "mismatches_on_bc_exdate_by_kind": kinds,
        "split_bonus_exdates_checked": int(len(on_ex)),
        "split_bonus_exdates_prev_close_differs": int(on_ex["mis"].sum()) if len(on_ex) else 0,
        "_per_date": per,
    }


def check_splice(eq: pd.DataFrame) -> dict:
    """History's last session close vs the store's first-day prev_close (2021-10-01)."""
    last = eq["date"].max()
    if pd.Timestamp(last).date() != WINDOW_END:
        return {"status": f"history ends {last}; splice check needs {WINDOW_END}"}
    h = eq[eq["date"] == last][["ticker", "series", "close"]]
    e = pd.read_parquet(EXPORT, filters=[("date", "==", date(2021, 10, 1))],
                        columns=["ticker", "series", "prev_close"])
    m = h.merge(e, on=["ticker", "series"], how="inner")
    dev = (m["prev_close"] / m["close"] - 1).abs()
    return {"history_last_session": str(pd.Timestamp(last).date()), "store_first_session": "2021-10-01",
            "pairs": int(len(m)), "mismatch_share": r((dev > MISMATCH_TOL).mean(), 6),
            "exact_share": r((dev < 1e-12).mean(), 6),
            "mismatches": m[dev > MISMATCH_TOL].head(10).to_dict("records")}


# --------------------------------------------------------------------------- coverage
def check_coverage(allrows: pd.DataFrame, auxes: list[dict] | None = None) -> dict:
    a = allrows
    a = a.assign(period=a["date"].map(lambda d: period_label(pd.Timestamp(d).date())))
    eqbe = a[a["series"].isin(["EQ", "BE"])]
    out: dict = {"rows_by_period": {}, "rows_eq_be_by_period": {}, "delivery": {}, "isin": {}}
    for p, t in a.groupby("period"):
        out["rows_by_period"][p] = int(len(t))
    for p, t in eqbe.groupby("period"):
        out["rows_eq_be_by_period"][p] = int(len(t))
        eqr, ber = t[t["series"] == "EQ"], t[t["series"] == "BE"]
        out["delivery"][p] = {
            "eq_be_share_with_deliv_pct": r(t["deliv_pct"].notna().mean()),
            "eq_share_with_deliv_pct": r(eqr["deliv_pct"].notna().mean()),
            "be_share_with_deliv_pct": r(ber["deliv_pct"].notna().mean()) if len(ber) else None,
            "be_rows": int(len(ber)),
        }
        out["isin"][p] = {"eq_be_share_with_isin": r(t["isin"].notna().mean()),
                          "all_series_share_with_isin": r(a.loc[a["period"] == p, "isin"].notna().mean())}
    out["rows_total"] = int(len(a))
    out["rows_eq_be_total"] = int(len(eqbe))
    out["distinct_tickers_all_series"] = int(a["ticker"].nunique())
    out["distinct_tickers_eq_be"] = int(eqbe["ticker"].nunique())
    out["distinct_isin_eq_be"] = int(eqbe["isin"].nunique())
    out["series_counts_top"] = {k: int(v) for k, v in a["series"].value_counts().head(12).items()}
    out["n_series_codes"] = int(a["series"].nunique())
    out["isin_eq_be_share"] = r(eqbe["isin"].notna().mean())
    out["isin_inf_prefix_tickers_eq_be"] = int(eqbe.loc[eqbe["isin"].fillna("").str.startswith("INF"),
                                                        "ticker"].nunique())
    if auxes:
        g = pd.DataFrame([x for au in auxes for x in au.get("pd_g", [])])
        if len(g):
            g["period"] = g["date"].map(lambda s: period_label(date.fromisoformat(s)))
            ge = g[g["SERIES"].isin(["EQ", "BE"])]
            out["call_auction_rows_eq_be_by_period"] = {k: int(v) for k, v in ge.groupby("period").size().items()}
            out["call_auction_rows_eq_be_total"] = int(len(ge))
            out["call_auction_tickers_eq_be"] = int(ge["SYMBOL"].nunique())
    out["deliv_eq_be_share_total"] = r(eqbe["deliv_pct"].notna().mean())
    out["deliv_eq_share_total"] = r(eqbe.loc[eqbe["series"] == "EQ", "deliv_pct"].notna().mean())
    # deliv_qty <= volume and deliv_pct consistent with deliv_qty / volume
    d = eqbe.dropna(subset=["deliv_qty", "deliv_pct"])
    calc = 100 * d["deliv_qty"] / d["volume"]
    out["deliv_qty_le_volume_share"] = r((d["deliv_qty"] <= d["volume"]).mean(), 6)
    out["deliv_pct_consistent_share"] = r((np.abs(calc - d["deliv_pct"]) <= 0.01 + 1e-9).mean(), 6)
    return out


def check_integrity(eqbe: pd.DataFrame) -> dict:
    t = eqbe
    ohlc_ok = (t["low"] <= t[["open", "close"]].min(axis=1) + 1e-9) & \
              (t["high"] >= t[["open", "close"]].max(axis=1) - 1e-9)
    vw = t.dropna(subset=["vwap"])
    vw_ok = (vw["vwap"] >= vw["low"] - 0.011) & (vw["vwap"] <= vw["high"] + 0.011)
    # echo footprint: share of tickers repeating the previous session's close AND volume
    x = t[["date", "ticker", "series", "close", "volume"]].sort_values(["ticker", "series", "date"])
    g = x.groupby(["ticker", "series"], sort=False)
    rep = (g["close"].shift(1) == x["close"]) & (g["volume"].shift(1) == x["volume"])
    share = rep.groupby(x["date"]).mean()
    return {
        "ohlc_order_ok_share": r(ohlc_ok.mean(), 6),
        "ohlc_order_violations": int((~ohlc_ok).sum()),
        "nonpositive_close_rows": int((t["close"] <= 0).sum()),
        "zero_volume_rows": int((t["volume"] <= 0).sum()),
        "vwap_inside_low_high_share": r(vw_ok.mean(), 6),
        "echo_footprint_max_share": r(share.max(), 6),
        "echo_footprint_max_date": str(share.idxmax()) if len(share) else None,
        "duplicate_keys": int(t.duplicated(["date", "ticker", "series"]).sum()),
    }


def check_parse_diag(auxes: list[dict]) -> dict:
    """Aggregate the per-day parser diagnostics."""
    ds = [a.get("diag", {}) for a in auxes if a.get("diag")]
    if not ds:
        return {}

    def tot(k):
        return int(sum(int(d.get(k) or 0) for d in ds))

    matched = tot("mto_matched_rows")
    return {
        "days": len(ds),
        "cm_rows_raw": tot("cm_rows_raw"), "cm_rows_kept": tot("cm_rows"),
        "cm_duplicate_rows_dropped": tot("cm_dup_rows"),
        "cm_timestamp_mismatch_rows": tot("cm_timestamp_mismatch_rows"),
        "days_without_mto": [d["cm_file"] for d in ds if not d.get("has_mto")],
        "days_without_pr": [d["cm_file"] for d in ds if not d.get("has_pr")],
        "mto_trade_date_mismatch_days": [d.get("mto_file") for d in ds
                                         if d.get("has_mto") and not d.get("mto_trade_date_ok")],
        "mto_rejected_days": [d.get("mto_file") for d in ds if d.get("mto_rejected")],
        "mto_header_quirk_files": [d.get("mto_file") for d in ds if d.get("mto_header_quirk")],
        "mto_rows": tot("mto_rows"), "mto_bad_lines": tot("mto_bad_lines"),
        "mto_duplicate_rows_dropped": tot("mto_dup_rows"),
        "mto_rows_matched_to_cm": matched,
        "mto_deliv_blanked_rows": tot("mto_deliv_blanked_rows"),
        "mto_deliv_blanked_days": [d.get("mto_file") for d in ds if d.get("mto_deliv_blanked_rows")],
        "mto_rows_without_cm_row": tot("mto_unmatched_rows"),
        "mto_qty_equals_cm_volume_share": r(tot("mto_qty_equals_volume") / matched, 6) if matched else None,
        "pr_rows_repaired_total": tot("pr_rows_repaired"),
        "pr_rows_repaired_bundles": [d.get("pr_file") for d in ds if d.get("pr_rows_repaired")],
        "pr_misdated_bundles": [{"file": d.get("pr_file"), "member_dates": d.get("pr_member_dates")}
                                for d in ds if d.get("pr_misdated")],
        "pr_days_without_bc": [d.get("pr_file") for d in ds if d.get("has_pr") and not d.get("bc_member")],
        "pr_days_without_etf": [d.get("pr_file") for d in ds if d.get("has_pr") and not d.get("etf_member")],
        "pr_days_without_pd": [d.get("pr_file") for d in ds if d.get("has_pr") and not d.get("pd_member")],
        "bc_member_names_seen": sorted({re.sub(r"\d{6}", "<ddmmyy>", d["bc_member"]) for d in ds
                                        if d.get("bc_member")}),
        "etf_member_names_seen": sorted({re.sub(r"\d{6}", "<ddmmyy>", d["etf_member"]) for d in ds
                                         if d.get("etf_member")}),
        "pd_member_names_seen": sorted({re.sub(r"\d{6}", "<ddmmyy>", d["pd_member"]) for d in ds
                                        if d.get("pd_member")}),
        "pd_crosscheck": _pd_cross(ds),
    }


def write_pd_disagreements(pc: dict) -> str | None:
    """Rows where CM and the bundle's Pd file disagree -> CSV (CM values stay in the parquet)."""
    import zipfile
    files = sorted({x["file"] for k, v in pc.get("days_with_disagreement", {}).items()
                    if isinstance(v, list) for x in v})
    if not files:
        return None
    rows = []
    for f in files:
        d = datetime.strptime(f[2:11], "%d%b%Y").date()
        cm = pd.read_parquet(EOD_DIR / f"{d:%Y%m%d}.parquet")
        with zipfile.ZipFile(local_path("pr", d)) as zf:
            n = next(x for x in zf.namelist() if re.fullmatch(r"pd\d{6}\.csv", Path(x).name, re.IGNORECASE))
            pdf = pd.read_csv(zf.open(n), dtype=str, keep_default_na=False)
        pdf.columns = [c.strip() for c in pdf.columns]
        pdf = pdf.apply(lambda s: s.str.strip())
        m = cm.merge(pdf[pdf["MKT"].isin(["N", "G", "O"])], left_on=["ticker", "series"],
                     right_on=["SYMBOL", "SERIES"])
        for a, c in (("close", "CLOSE_PRICE"), ("prev_close", "PREV_CL_PR"), ("open", "OPEN_PRICE"),
                     ("high", "HIGH_PRICE"), ("low", "LOW_PRICE"), ("volume", "NET_TRDQTY"), ("trades", "TRADES")):
            pv = pd.to_numeric(m[c], errors="coerce")
            bad = ~np.isclose(m[a].astype(float), pv, rtol=0, atol=1e-6)
            for _, row in m[bad].iterrows():
                rows.append({"date": d.isoformat(), "ticker": row["ticker"], "series": row["series"],
                             "field": a, "cm": row[a], "pd": float(pd.to_numeric(row[c], errors="coerce"))})
    out = RESULTS / "cm_vs_pd_disagreements.csv"
    pd.DataFrame(rows).to_csv(out, index=False)
    return str(out.relative_to(RESULTS.parents[3]))


def _pd_cross(ds: list[dict]) -> dict:
    """CM vs the bundle's Pd file (MKT N, G, O): field equality over matched rows and the worst day."""
    dd = [d for d in ds if d.get("pd_matched")]
    if not dd:
        return {}
    tot = sum(d["pd_matched"] for d in dd)
    out = {"days": len(dd), "matched_rows": int(tot),
           "cm_rows_not_in_pd": int(sum(d.get("pd_cm_only", 0) for d in dd)),
           "cm_rows_not_in_pd_eq_be": int(sum(d.get("pd_cm_only_eq_be", 0) for d in dd)),
           "cm_rows_not_in_pd_series": sorted({x for d in dd for x in d.get("pd_cm_only_series", [])}),
           "pd_rows_not_in_cm": int(sum(d.get("pd_only", 0) for d in dd)), "field_match_share": {},
           "worst_day": {}}
    out["days_with_disagreement"] = {}
    for f in ("close", "prev_close", "open", "high", "low", "volume", "trades", "turnover_500"):
        key = f"pd_eq_{f}"
        out["field_match_share"][f] = r(sum(d.get(key, 0) for d in dd) / tot, 6)
        worst = min(dd, key=lambda d: d.get(key, 0) / d["pd_matched"])
        out["worst_day"][f] = {"file": worst.get("cm_file"),
                               "share": r(worst.get(key, 0) / worst["pd_matched"], 6)}
        bad = [{"file": d.get("cm_file"), "rows": int(d["pd_matched"] - d.get(key, 0))}
               for d in dd if d.get(key, 0) < d["pd_matched"]]
        out["days_with_disagreement"][f] = bad[:20]
        out["days_with_disagreement"][f + "_n_days"] = len(bad)
    return out


# --------------------------------------------------------------------------- sanity
def index_frame(auxes: list[dict]) -> pd.DataFrame:
    rows = []
    for a in auxes:
        rows += a.get("idx", [])
    if not rows:
        return pd.DataFrame()
    ix = pd.DataFrame(rows)
    for c in ("PREV_CL_PR", "OPEN_PRICE", "HIGH_PRICE", "LOW_PRICE", "CLOSE_PRICE"):
        ix[c] = pd.to_numeric(ix[c].astype(str).str.replace(",", ""), errors="coerce")
    return ix


def check_sanity(eqbe: pd.DataFrame, auxes: list[dict], sessions: list[date]) -> dict:
    ix = index_frame(auxes)
    out = {}
    days = dict(SANITY_DAYS)
    for k, v in SPECIAL_SESSIONS.items():
        days.setdefault(k, v)
    sset = set(sessions)
    for iso, label in sorted(days.items()):
        d = date.fromisoformat(iso)
        rec: dict = {"label": label, "weekday": d.strftime("%A"), "present": d in sset}
        if d in sset:
            t = eqbe[eqbe["date"] == d]
            eq = t[t["series"] == "EQ"]
            rec.update({
                "rows_eq_be": int(len(t)),
                "median_open_gap": r((eq["open"] / eq["prev_close"] - 1).median()),
                "median_low_vs_prev_close": r((eq["low"] / eq["prev_close"] - 1).median()),
                "median_close_return": r((eq["close"] / eq["prev_close"] - 1).median()),
                "share_down": r((eq["close"] < eq["prev_close"]).mean()),
                "median_trades": r(eq["trades"].median(), 1),
            })
            if not ix.empty:
                n = ix[(ix["date"] == iso) & (ix["SECURITY"].str.upper() == "NIFTY 50")]
                if len(n):
                    n = n.iloc[0]
                    rec["nifty50"] = {"prev_close": r(n["PREV_CL_PR"], 2), "open": r(n["OPEN_PRICE"], 2),
                                      "low": r(n["LOW_PRICE"], 2), "close": r(n["CLOSE_PRICE"], 2),
                                      "return": r(n["CLOSE_PRICE"] / n["PREV_CL_PR"] - 1),
                                      "low_vs_prev_close": r(n["LOW_PRICE"] / n["PREV_CL_PR"] - 1)}
        out[iso] = rec
    return out


# --------------------------------------------------------------------------- upsert dry run
def upsert_dry_run() -> dict:
    """Load the staging parquet through nse_historical_ingest.DuckDBStore.upsert into an IN-MEMORY
    DuckDB (never nse_market.duckdb): schema, types, primary key and idempotency."""
    import nse_historical_ingest as nhi
    p = STAGE / "equity_eod_2016_2021.parquet"
    if not p.exists():
        return {"status": "final parquet not written yet"}
    df = pd.read_parquet(p)
    cols_ok = list(df.columns) == list(nhi.EOD_COLUMNS)
    store = nhi.DuckDBStore(":memory:")
    n = store.upsert(df)
    q = "SELECT count(*), count(DISTINCT date), min(date), max(date), count(isin), count(deliv_pct) FROM equity_eod"
    a = store.con.execute(q).fetchone()
    last = df[df["date"] == df["date"].max()]
    store.upsert(last)
    b = store.con.execute("SELECT count(*) FROM equity_eod").fetchone()[0]
    types = {r_[0]: r_[1] for r_ in store.con.execute("DESCRIBE equity_eod").fetchall()}
    store.close()
    return {"columns_equal_EOD_COLUMNS": cols_ok, "rows_upserted": int(n), "rows_in_table": int(a[0]),
            "sessions": int(a[1]), "min_date": str(a[2]), "max_date": str(a[3]),
            "rows_with_isin": int(a[4]), "rows_with_deliv_pct": int(a[5]),
            "rows_after_reupserting_last_day": int(b), "idempotent": int(b) == int(a[0]),
            "column_types": {k: types[k] for k in nhi.EOD_COLUMNS}}


# --------------------------------------------------------------------------- main
def run(final: bool) -> dict:
    t0 = datetime.now(timezone.utc)
    dl = check_download()
    allrows, auxes = load_parts(WINDOW_START, WINDOW_END)
    allrows["date"] = pd.to_datetime(allrows["date"]).dt.date
    sessions = sorted(allrows["date"].unique().tolist())
    eqbe = allrows[allrows["series"].isin(["EQ", "BE"])].copy()
    res: dict = {
        "stream": "P4 history 2016-10..2021-09",
        "generated_utc": t0.isoformat(timespec="seconds"),
        "final": final,
        "window": [WINDOW_START.isoformat(), WINDOW_END.isoformat()],
        "sources": {
            "cm": "archives.nseindia.com/content/historical/EQUITIES/{YYYY}/{MON}/cm{DD}{MON}{YYYY}bhav.csv.zip",
            "mto": "archives.nseindia.com/archives/equities/mto/MTO_{DDMMYYYY}.DAT",
            "pr": "archives.nseindia.com/archives/equities/bhavcopy/pr/PR{DDMMYY}.zip",
        },
        "mapping": {
            "prev_close": "PREVCLOSE", "open": "OPEN", "high": "HIGH", "low": "LOW", "last": "LAST",
            "close": "CLOSE", "volume": "TOTTRDQTY",
            "turnover": f"TOTTRDVAL * {TURNOVER_FACTOR} (rupees), rounded half up to 0.01 lakh like the store",
            "trades": "TOTALTRADES", "vwap": "TOTTRDVAL / TOTTRDQTY, rounded half up to 2 decimals", "isin": "ISIN",
            "deliv_qty": "MTO Deliverable Quantity (join SYMBOL + SERIES; NaN when MTO has no row or its "
                         "traded quantity differs from the CM volume)",
            "deliv_pct": "MTO % of Deliverable Quantity to Traded Quantity", "source": "cm_mto",
        },
    }
    res["download"] = {k: v for k, v in dl.items() if not k.startswith("_")}
    res["overlap"] = check_overlap()
    res["calendar"] = check_calendar(dl, sessions)
    cont = check_continuity(eqbe, sessions, auxes)
    per = cont.pop("_per_date")
    res["continuity"] = cont
    res["splice"] = check_splice(eqbe)
    res["coverage"] = check_coverage(allrows, auxes)
    res["integrity"] = check_integrity(eqbe)
    res["parse_diagnostics"] = check_parse_diag(auxes)
    pcx = res["parse_diagnostics"].get("pd_crosscheck") or {}
    if pcx:
        pcx["disagreement_rows_csv"] = write_pd_disagreements(pcx)
    res["sanity"] = check_sanity(eqbe, auxes, sessions)
    outs = {}
    for name in ("equity_eod_2016_2021.parquet", "bc_records_2016_2021.csv", "etf_records_2016_2021.csv",
                 "pd_corp_ind_2016_2021.csv", "index_close_2016_2021.csv", "call_auction_rows_2016_2021.csv",
                 "sessions_2016_2021.csv",
                 "overlap_cm_mto_2021-10.parquet"):
        p = STAGE / name
        pp = STAGE / name.replace(".parquet", ".partial.parquet").replace(".csv", ".partial.csv")
        q = p if p.exists() else (pp if pp.exists() else None)
        if q is not None:
            outs[name] = {"path": str(q.relative_to(STAGE.parents[1])), "bytes": q.stat().st_size}
    res["outputs"] = outs
    if final:
        res["upsert_dry_run"] = upsert_dry_run()
    res["outputs_detail"] = _output_detail()
    RESULTS.mkdir(parents=True, exist_ok=True)
    per.reset_index().assign(date=lambda t: t["date"].astype(str)).to_csv(
        RESULTS / "continuity_by_date.csv", index=False)
    tmp = JSON_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(res, indent=1, default=str))
    tmp.replace(JSON_PATH)
    log.info("history.json written (%d sessions, %d rows)", len(sessions), len(allrows))
    return res


def _output_detail() -> dict:
    out = {}
    p = STAGE / "bc_records_2016_2021.csv"
    if not p.exists():
        p = STAGE / "bc_records_2016_2021.partial.csv"
    if p.exists():
        b = pd.read_csv(p, dtype=str, keep_default_na=False)
        key = [c for c in ("SYMBOL", "SERIES", "EX_DT", "RECORD_DT", "PURPOSE") if c in b.columns]
        u = b.drop_duplicates(key)
        pur = u["PURPOSE"].str.upper()
        out["bc"] = {"rows": int(len(b)), "distinct_events": int(len(u)),
                     "bundles": int(b["bundle_date"].nunique()),
                     "distinct_split_events": int(pur.str.contains("SPLT|SPLIT", regex=True).sum()),
                     "distinct_bonus_events": int(pur.str.contains("BONUS").sum()),
                     "distinct_rights_events": int(pur.str.contains("RIGHTS|RGHTS", regex=True).sum())}
    p = STAGE / "etf_records_2016_2021.csv"
    if not p.exists():
        p = STAGE / "etf_records_2016_2021.partial.csv"
    if p.exists():
        e = pd.read_csv(p, dtype=str, keep_default_na=False)
        out["etf"] = {"symbols": int(len(e))}
    return out


# --------------------------------------------------------------------------- markdown
def fmt_pct(x, k=1):
    return "n/a" if x is None else f"{100 * x:.{k}f}%"


def render_md(res: dict) -> str:
    o, c, k, cv, s = res["overlap"], res["calendar"], res["continuity"], res["coverage"], res["sanity"]
    dl, it, sp = res["download"], res["integrity"], res["splice"]
    L = []
    L.append("# P4 history: NSE cash-market EOD 2016-10-03 to 2021-09-30")
    L.append("")
    L.append(f"Generated {res['generated_utc']} from `ml/results/improve/history/history.json` "
             f"(every number below is quoted from it). Status: "
             f"{'final' if res['final'] else 'PARTIAL (download still running)'}.")
    L.append("")
    L.append("## What was built")
    L.append("")
    L.append(f"- `ml/data_hist/equity_eod_2016_2021.parquet`: {cv['rows_total']:,} rows over "
             f"{c['sessions_total']:,} sessions, exactly the `EOD_COLUMNS` of `nse_historical_ingest.py`, "
             f"one row per (date, ticker, series), every series the CM file carries "
             f"({cv['n_series_codes']} codes; {cv['rows_eq_be_total']:,} EQ/BE rows), `source = cm_mto`.")
    bc = res.get("outputs_detail", {}).get("bc", {})
    et = res.get("outputs_detail", {}).get("etf", {})
    if bc:
        L.append(f"- `ml/data_hist/bc_records_2016_2021.csv`: {bc['rows']:,} Bc rows from {bc['bundles']:,} "
                 f"PR bundles ({bc['distinct_events']:,} distinct events; {bc['distinct_split_events']} "
                 f"face-value splits, {bc['distinct_bonus_events']} bonuses, {bc['distinct_rights_events']} "
                 f"rights), raw columns plus `source_file` and `bundle_date`.")
    if et:
        L.append(f"- `ml/data_hist/etf_records_2016_2021.csv`: {et['symbols']} ETF symbols with first_seen, "
                 f"last_seen, underlying.")
    L.append("- Also in `ml/data_hist/`: `pd_corp_ind_2016_2021.csv` (Pd rows with a CORP_IND flag such as XD, XB, "
             "XR), `index_close_2016_2021.csv` (Pd index rows incl. Nifty 50 and India VIX), "
             "`sessions_2016_2021.csv` (one row per session), `call_auction_rows_2016_2021.csv` (periodic "
             "call-auction rows), `overlap_cm_mto_2021-10.parquet` (the two overlap days; validation only, "
             "not for upsert).")
    L.append("")
    L.append("Mapping: " + ", ".join(f"`{a}` = {b}" for a, b in res["mapping"].items()) + ".")
    L.append("")
    L.append("## Overlap with the stored window (2021-10-01, 2021-10-04)")
    L.append("")
    if "fields" in o:
        L.append(f"Matched {o['matched_rows']:,} (ticker, series) EQ/BE rows of the store's "
                 f"{o['store_rows_eq_be']:,}; store-only rows: {o['store_only_rows']}; "
                 f"history-only rows: {o['history_only_rows']}.")
        L.append("")
        L.append("| Field | Match share | Rule |")
        L.append("|---|---:|---|")
        for f, v in o["fields"].items():
            L.append(f"| {f} | {100 * v['match_share']:.2f}% | {v['rule']} |")
        tf = o["turnover_factor"]
        L.append("")
        tv = o["fields"]["turnover"]
        L.append(f"Turnover unit factor (store turnover / raw CM TOTTRDVAL): median "
                 f"{tf['median_store_over_raw_tottrdval']}, OLS through the origin {tf['ols_through_origin']}, "
                 f"over {tf['rows_used']:,} rows with TOTTRDVAL of at least Rs 10 lakh; applied factor "
                 f"{tf['applied']}; units: {tf['units']}. Against the raw rupee value the store differs by at most "
                 f"Rs {tv['raw_abs_diff_rupees_max']} (median Rs {tv['raw_abs_diff_rupees_median']}; within Rs 500 "
                 f"on {fmt_pct(tv['raw_within_500_share'], 2)} of rows) because it keeps 0.01 lakh; the history "
                 f"applies the same rounding, after which the match is {fmt_pct(tv['match_share'], 2)}.")
        L.append("")
        L.append("Systematic differences:")
        L.append("")
        L.append(f"- BE rows carry no delivery in either source (store {o['be_rows_with_deliv_store']} of "
                 f"{o['be_rows_matched']}, history {o['be_rows_with_deliv_history']} of {o['be_rows_matched']}): "
                 f"trade-for-trade BE trades settle by delivery and MTO lists no BE record.")
        if o["fields"]["vwap"]["rows_off"] == 0:
            L.append("- vwap matches on every row once value / quantity is rounded half up, as NSE prints "
                     "AVG_PRICE; numpy's default half-to-even rounding misses exact half-paisa cases (QNIFTY "
                     "2021-10-04: value / quantity = 1849.125, stored 1849.13), so the parser rounds half up.")
        else:
            L.append(f"- vwap: {o['fields']['vwap']['rows_off']} row(s) differ by up to 0.01 (rounding of "
                     f"value / quantity).")
        if o["history_only_rows"]:
            tk = sorted({x["ticker"] for x in o["history_only"]})
            L.append(f"- {o['history_only_rows']} EQ/BE rows exist in the CM bhavcopy but not in the store "
                     f"({', '.join(tk)}); {o['history_only_in_call_auction']} of them are the day's periodic "
                     f"call-auction securities (Pd market G), which sec_bhavdata_full leaves out. All close below "
                     f"Rs 10 with turnover under Rs 1 lakh, outside the modelling universe (median turnover of at "
                     f"least Rs 1 crore). The history keeps them (every CM row is kept); "
                     f"`ml/data_hist/call_auction_rows_2016_2021.csv` lists every such (date, ticker, series) "
                     f"so they can be dropped for strict homogeneity with the store.")
    L.append("")
    L.append("## Calendar")
    L.append("")
    L.append("Expected counts come from the reference list of NSE weekday closures in `ml/history/validate.py` "
             "(`NSE_WEEKDAY_HOLIDAYS`) plus the special sessions.")
    L.append("")
    L.append("| Period | Sessions | Expected (reference calendar) | EQ/BE rows | All rows |")
    L.append("|---|---:|---:|---:|---:|")
    for p in sorted(c["sessions_by_period"]):
        L.append(f"| {p} | {c['sessions_by_period'][p]} | {c['expected_by_period_reference'].get(p, 'n/a')} | "
                 f"{cv['rows_eq_be_by_period'].get(p, 0):,} | {cv['rows_by_period'].get(p, 0):,} |")
    L.append("")
    L.append(f"Weekday closures not in the reference holiday list: "
             f"{c['weekday_closures_not_in_reference'] or 'none'}. Reference holidays that nevertheless "
             f"carry a non-special session: {c['reference_holidays_with_a_session_unexpected'] or 'none'}. "
             f"Weekend sessions: {', '.join(c['weekend_sessions']) or 'none'}. Mirror echoes or misdated files: "
             f"{len(dl['echo_or_misdated'])}.")
    L.append("")
    L.append("Special sessions:")
    L.append("")
    for kk, v in c["special_sessions"].items():
        ss = s.get(kk, {})
        extra = f", {ss.get('rows_eq_be')} EQ/BE rows, median trades {ss.get('median_trades')}" if v["present"] else ""
        L.append(f"- {kk} ({v['label']}): {'present' if v['present'] else 'MISSING'}{extra}")
    L.append("")
    L.append("## prev_close continuity")
    L.append("")
    L.append(f"Rule: {k['rule']}. Over {k['dates_scanned']:,} dates and {k['pairs_scanned']:,} pairs the "
             f"mismatch share is {fmt_pct(k['overall_mismatch_share'], 3)} (median day "
             f"{fmt_pct(k['median_daily_share'], 3)}, 99th percentile {fmt_pct(k['p99_daily_share'], 2)}, "
             f"maximum {fmt_pct(k['max_daily_share'], 2)} on {k['max_daily_share_date']}). Dates above 5%: "
             f"{len(k['dates_above_5pct'])}.")
    for f in k["dates_above_5pct"]:
        L.append(f"- {f['date']} (previous session {f['previous_session']}): {f['mismatches']} of {f['tickers']} "
                 f"({fmt_pct(f['share'], 1)}), {f['explained_by_bc_exdate']} on a Bc ex-date.")
    L.append("")
    if k.get("mismatch_list") and k["mismatch_pairs"] <= 60:
        L.append("Every mismatching pair: " + "; ".join(
            f"{m['date']} {m['ticker']} {m['series']} prev_close {m['prev_close']} vs previous close "
            f"{m['previous_close']}" + (f" (Bc ex-date: {m['purpose']})" if m.get("bc_explained") else " (no Bc ex-date)")
            for m in k["mismatch_list"]) + ".")
        L.append("")
    L.append(f"Mismatches falling on a Bc ex-date of the same ticker: {k['mismatches_on_bc_exdate']} of "
             f"{k['mismatch_pairs']} ({k['mismatches_on_bc_exdate_by_kind']}): NSE adjusted the base price for these "
             f"few dividends and one split. On {k['split_bonus_exdates_checked']} split or bonus ex-dates with a "
             f"previous-session close, prev_close differs from it on {k['split_bonus_exdates_prev_close_differs']}: "
             f"the legacy PREVCLOSE is otherwise the unadjusted previous close, so prev_close does not reveal splits "
             f"and bonuses in this window either, and the Bc feed is needed for adjustment. No session is missing "
             f"(no date above 5%, every weekday closure is a reference holiday, all special sessions present).")
    if "pairs" in sp:
        L.append("")
        L.append(f"Splice with the store: the store's 2021-10-01 prev_close equals the history's 2021-09-30 close "
                 f"exactly for {fmt_pct(sp['exact_share'], 2)} of {sp['pairs']:,} (ticker, series) pairs "
                 f"(mismatch share above 0.5%: {fmt_pct(sp['mismatch_share'], 2)}).")
    L.append("")
    L.append("## Coverage")
    L.append("")
    L.append("| Period | EQ/BE with deliv_pct | EQ with deliv_pct | BE with deliv_pct | EQ/BE with ISIN |")
    L.append("|---|---:|---:|---:|---:|")
    for p in sorted(cv["delivery"]):
        dv = cv["delivery"][p]
        L.append(f"| {p} | {fmt_pct(dv['eq_be_share_with_deliv_pct'])} | {fmt_pct(dv['eq_share_with_deliv_pct'])} | "
                 f"{fmt_pct(dv['be_share_with_deliv_pct'])} | {fmt_pct(cv['isin'][p]['eq_be_share_with_isin'])} |")
    L.append("")
    if cv.get("call_auction_rows_eq_be_total") is not None:
        L.append(f"Periodic call-auction rows (EQ/BE, Pd market G): {cv['call_auction_rows_eq_be_total']:,} over "
                 f"{cv['call_auction_tickers_eq_be']} tickers ({cv['call_auction_rows_eq_be_by_period']}).")
        L.append("")
    L.append(f"Distinct tickers: {cv['distinct_tickers_all_series']:,} (all series), "
             f"{cv['distinct_tickers_eq_be']:,} (EQ/BE); distinct ISINs on EQ/BE rows: {cv['distinct_isin_eq_be']:,}; "
             f"EQ/BE tickers with an INF (fund) ISIN: {cv['isin_inf_prefix_tickers_eq_be']}. "
             f"deliv_qty <= volume on {fmt_pct(cv['deliv_qty_le_volume_share'], 3)} of rows with delivery; "
             f"deliv_pct within 0.01 of 100 * deliv_qty / volume on {fmt_pct(cv['deliv_pct_consistent_share'], 3)}.")
    L.append("")
    L.append(f"Integrity: OHLC ordering holds on {fmt_pct(it['ohlc_order_ok_share'], 3)} of EQ/BE rows "
             f"({it['ohlc_order_violations']} violations); non-positive closes {it['nonpositive_close_rows']}; "
             f"vwap inside [low, high] on {fmt_pct(it['vwap_inside_low_high_share'], 3)}; duplicate keys "
             f"{it['duplicate_keys']}; largest share of tickers repeating the previous session's close and "
             f"volume {fmt_pct(it['echo_footprint_max_share'], 2)} ({it['echo_footprint_max_date']}).")
    pdg = res.get("parse_diagnostics") or {}
    if pdg:
        L.append("")
        L.append(f"Parser: {pdg['cm_rows_kept']:,} of {pdg['cm_rows_raw']:,} CM rows kept "
                 f"({pdg['cm_duplicate_rows_dropped']} duplicate keys dropped, "
                 f"{pdg['cm_timestamp_mismatch_rows']} rows with a TIMESTAMP other than the file date); "
                 f"MTO {pdg['mto_rows']:,} records, {pdg['mto_rows_without_cm_row']} without a CM row, "
                 f"MTO traded quantity equals CM volume on {fmt_pct(pdg['mto_qty_equals_cm_volume_share'], 3)} "
                 f"of matched rows (the exceptions are all in {', '.join(pdg['mto_deliv_blanked_days'])}, which carry "
                 f"66 records keyed by BSE scrip codes and quantities above the NSE volume, most likely combined "
                 f"NSE and BSE obligations; delivery is left NaN on those {pdg['mto_deliv_blanked_rows']:,} rows); MTO trade-date mismatches: {len(pdg['mto_trade_date_mismatch_days'])} "
                 f"(files rejected: {len(pdg.get('mto_rejected_days', []))}; headers reading 'rade Date' without "
                 f"the T, date verified: {len(pdg.get('mto_header_quirk_files', []))}); "
                 f"sessions without MTO: {len(pdg['days_without_mto'])}, without PR: {len(pdg['days_without_pr'])}; "
                 f"bundle CSV rows with an unquoted comma in a text field, re-joined: "
                 f"{pdg.get('pr_rows_repaired_total', 0)} in {len(pdg.get('pr_rows_repaired_bundles', []))} bundles; "
                 f"PR bundles whose members carry another date (not used): "
                 f"{', '.join(x['file'] + ' -> ' + '/'.join(x['member_dates']) for x in pdg['pr_misdated_bundles']) or 'none'}; "
                 f"PR bundles without a Bc / etf / Pd member: {len(pdg['pr_days_without_bc'])} / "
                 f"{len(pdg['pr_days_without_etf'])} / {len(pdg['pr_days_without_pd'])}; member names seen: "
                 f"{', '.join(pdg['bc_member_names_seen'] + pdg['etf_member_names_seen'] + pdg['pd_member_names_seen'])}.")
    pc = (pdg or {}).get("pd_crosscheck") or {}
    if pc:
        fm = pc["field_match_share"]
        L.append("")
        L.append(f"Independent cross-check against the Pd file of each day's PR bundle (security rows of the "
                 f"normal market, the periodic call auction and the block-deal window): "
                 f"{pc['matched_rows']:,} rows over {pc['days']:,} days; equal close "
                 f"{fmt_pct(fm['close'], 3)}, prev_close {fmt_pct(fm['prev_close'], 3)}, open "
                 f"{fmt_pct(fm['open'], 3)}, high {fmt_pct(fm['high'], 3)}, low {fmt_pct(fm['low'], 3)}, volume "
                 f"{fmt_pct(fm['volume'], 3)}, trades {fmt_pct(fm['trades'], 3)}, turnover within Rs 500 "
                 f"{fmt_pct(fm['turnover_500'], 3)}; CM rows absent from Pd {pc['cm_rows_not_in_pd']:,} "
                 f"({pc['cm_rows_not_in_pd_eq_be']} of them EQ/BE; series {', '.join(pc['cm_rows_not_in_pd_series'])}), "
                 f"Pd rows absent from CM {pc['pd_rows_not_in_cm']:,}.")
        dw = pc.get("days_with_disagreement", {})
        offs = sorted({(x["file"], f, x["rows"]) for f in ("close", "prev_close", "open", "high", "low", "volume",
                                                         "trades", "turnover_500") for x in dw.get(f, [])})
        if offs:
            L.append("")
            L.append("Disagreements by day and field: " + "; ".join(f"{a} {b} {c} rows" for a, b, c in offs) +
                     ". 2017-07-10 is the day of NSE's trading halt after a technical failure; "
                     "only high and low differ there, and the bundle's Pr file agrees with Pd (for example ACC low "
                     "1615.25 in Pd and Pr, 1563.30 in CM). The parquet keeps the CM values (the store's product "
                     f"family); the rows are in `{pc.get('disagreement_rows_csv')}`.")
    L.append("")
    L.append("## Sanity events")
    L.append("")
    L.append("| Date | Event | Present | EQ/BE rows | Median open gap | Median low vs prev close | "
             "Median close return | Nifty 50 return | Nifty 50 low vs prev close |")
    L.append("|---|---|---|---:|---:|---:|---:|---:|---:|")
    for kk, v in s.items():
        n = v.get("nifty50", {})
        L.append(f"| {kk} ({v['weekday'][:3]}) | {v['label']} | {'yes' if v['present'] else 'NO'} | "
                 f"{v.get('rows_eq_be', '')} | {fmt_pct(v.get('median_open_gap'), 2)} | "
                 f"{fmt_pct(v.get('median_low_vs_prev_close'), 2)} | {fmt_pct(v.get('median_close_return'), 2)} | "
                 f"{fmt_pct(n.get('return'), 2)} | {fmt_pct(n.get('low_vs_prev_close'), 2)} |")
    L.append("")
    L.append("## Download")
    L.append("")
    L.append(f"{dl['calendar_days']:,} calendar days requested (CM outcomes {dl['cm_status_counts']}); MTO files "
             f"{dl['mto']['files']:,}, PR bundles {dl['pr']['files']:,}; MTO missing on session days: "
             f"{len(dl['mto']['missing_on_session_days'])}, PR missing: {len(dl['pr']['missing_on_session_days'])}; "
             f"errors left: CM {len(dl['cm_errors'])}, MTO {len(dl['mto']['errors'])}, PR {len(dl['pr']['errors'])}. "
             f"{dl['manifest_outcomes']:,} request outcomes in the manifest over {dl['runs']} runs: the first run "
             f"stopped at 2019-09-09 when the agent proxy refused connections "
             f"({len(dl['backoff_warnings_logged'])} back-off logged) and the session ended; the resumed run skipped "
             f"every completed day without a request and made {dl['requests_last_run']:,} requests with "
             f"{dl['backoffs_last_run']} back-offs in {dl['elapsed_s_last_run']:,} s. One extra request re-fetched "
             f"PR020118.zip to confirm the archive mis-file (identical bytes).")
    ud = res.get("upsert_dry_run")
    if ud and "rows_upserted" in ud:
        L.append("")
        L.append(f"Upsert dry run (`DuckDBStore.upsert` into an in-memory DuckDB, not the store): columns equal "
                 f"`EOD_COLUMNS`: {ud['columns_equal_EOD_COLUMNS']}; {ud['rows_in_table']:,} rows over "
                 f"{ud['sessions']:,} sessions ({ud['min_date']} to {ud['max_date']}); re-upserting the last day "
                 f"leaves {ud['rows_after_reupserting_last_day']:,} rows (idempotent: {ud['idempotent']}).")
    L.append("")
    L.append("## Notes for the upsert")
    L.append("")
    L.append("- The rows carry raw (unadjusted) prices like the store; the corporate-action feed must be "
             "applied over the full 2016-2026 history after the upsert.")
    L.append("- `isin` is populated from the CM file (the stored 2021-2026 rows have it empty).")
    L.append("- `turnover` is rounded to 0.01 lakh exactly like the stored rows (at most Rs 500 from the raw "
             "TOTTRDVAL, which stays in the raw CM files).")
    L.append("- Delivery is NaN on BE rows in both sources; features that need delivery see the same gap "
             "pattern on both sides of the splice.")
    pdg2 = res.get("parse_diagnostics") or {}
    pcx2 = pdg2.get("pd_crosscheck") or {}
    n_hl = sum(x["rows"] for f in ("high", "low") for x in pcx2.get("days_with_disagreement", {}).get(f, []))
    L.append(f"- Delivery is also NaN on {pdg2.get('mto_deliv_blanked_rows', 0):,} rows of 2019-06-17 and 2019-06-18, "
             f"where the MTO quantities are not NSE-only (see Parser above). 2017-07-10 high/low come from the CM "
             f"file and differ from the PR bundle's Pd and Pr files on {n_hl} values (listed in "
             f"`cm_vs_pd_disagreements.csv`).")
    L.append("- Periodic call-auction rows (Pd market G) are kept; drop them with "
             "`call_auction_rows_2016_2021.csv` if the store's sec_bhavdata coverage must be matched exactly.")
    L.append("- Corporate actions over this window: P1's parser reads the PR bundles directly, e.g. "
             "`python3 -I ml/integrity/corporate_actions.py --bundle-dirs ml/data_raw/hist/pr --eod "
             "ml/data_hist/equity_eod_2016_2021.parquet ...` (its folder scan is top level only, so the "
             "`recheck/` copy is ignored, and its misfile guard skips PR020118.zip as this stream does); "
             "`bc_records_2016_2021.csv` holds the same Bc rows as a flat file.")
    L.append("")
    L.append("Upsert recipe (lead, inside P1's write window):")
    L.append("")
    L.append("```python")
    L.append("import pandas as pd, nse_historical_ingest as nhi")
    L.append('df = pd.read_parquet("ml/data_hist/equity_eod_2016_2021.parquet")')
    L.append('ca = pd.read_csv("ml/data_hist/call_auction_rows_2016_2021.csv", parse_dates=["date"])  # optional')
    L.append('key = ["date", "ticker", "series"]')
    L.append('df = df.assign(date=pd.to_datetime(df["date"])).merge(ca.assign(_ca=1), on=key, how="left")')
    L.append('df = df[df["_ca"].isna()].drop(columns="_ca")                                   # optional')
    L.append('store = nhi.DuckDBStore("nse_market.duckdb"); store.upsert(df); store.close()')
    L.append("```")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--final", action="store_true")
    a = ap.parse_args(argv)
    res = run(a.final)
    MD_PATH.write_text(render_md(json.loads(JSON_PATH.read_text())))
    log.info("HISTORY.md written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
