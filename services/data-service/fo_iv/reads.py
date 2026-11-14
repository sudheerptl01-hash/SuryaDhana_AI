"""Reads behind ``GET /db/fo-iv/*`` (the data-service half of PLAN 1.1's API contract; ui-api's ``routers/derivatives.py``
(B3) wraps them with the 60 s SWR cache). DuckDB only on the request path; every payload carries ``as_of``, ``since``,
``model_version``, ``r_source`` and the badges from ``catalog_seed``.
"""
from __future__ import annotations

import math
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from data_health import db

from fo_iv import catalog_seed, realised
from fo_iv.black76 import MODEL_VERSION, TIME_CONVENTION, TIME_CONVENTION_NOTE
from fo_iv.iv_eod import INDEX_NAMES, INDEX_SYMBOLS, NEAR_MIN_DTE, rate_for
from fo_iv.schema import FRESHNESS_COLUMN, positions_meta

SUMMARY_COLS = ["date", "spot", "iv30_cm", "iv60_cm", "iv90_cm", "monthly_atm_iv", "monthly_expiry", "near_atm_iv", "near_expiry", "near_dte",
                "skew_25d_30", "term_slope_30_90", "iv_rank_252", "iv_pctile_252", "rv20_cc", "rv20_parkinson", "rv20_yz", "fovolt_ann",
                "iv_minus_rv20", "expected_move_1d_pct", "quality_flags", "model_version", "r"]
DATE_COLS = ("date", "expiry", "near_expiry", "monthly_expiry", "pre_session", "post_session")
BADGES = {"iv": "arithmetic", "rank": "arithmetic", "pctile": "arithmetic", "rv": "arithmetic", "spread": "context", "skew": "context",
          "term": "context", "vix": "context", "events": "context", "intraday": "context"}


def _since(store: Any, symbol: str) -> str | None:
    v = db.scalar(store, "SELECT MIN(date) FROM iv_summary_daily WHERE symbol = ?", [symbol])
    return str(v)[:10] if v else None


def _as_of(store: Any, symbol: str) -> str | None:
    v = db.scalar(store, "SELECT MAX(date) FROM iv_summary_daily WHERE symbol = ?", [symbol])
    return str(v)[:10] if v else None


def summary(store: Any, symbol: str, *, days: int = 750) -> dict[str, Any]:
    sym = symbol.upper()
    rows = db.records_sql(store, f"""SELECT * FROM (SELECT {', '.join(SUMMARY_COLS)} FROM iv_summary_daily WHERE symbol = ?
                                     ORDER BY date DESC LIMIT ?) t ORDER BY date""", [sym, days], DATE_COLS)
    vix = db.records_sql(store, "SELECT * FROM (SELECT date, close FROM vix_daily ORDER BY date DESC LIMIT ?) t ORDER BY date", [days], ("date",))
    events = db.records_sql(store, "SELECT released_at, pre_session, post_session, crush_pct FROM iv_event_log WHERE symbol = ? ORDER BY released_at DESC LIMIT 40",
                            [sym], DATE_COLS)
    as_of = _as_of(store, sym)
    r, r_src = rate_for(store, date.fromisoformat(as_of)) if as_of else (None, None)
    return {"symbol": sym, "as_of": as_of, "since": _since(store, sym), "model_version": MODEL_VERSION, "r": r, "r_source": r_src,
            "rows": rows, "vix": vix,
            "events": [{"date": e["post_session"], "kind": "results", "crush_pct": e["crush_pct"]} for e in events],
            "badges": BADGES, "verdict": "IV history: describes, does not predict"}


def surface(store: Any, symbol: str, *, day: date | None = None, compare_days: int | None = None) -> dict[str, Any]:
    sym = symbol.upper()
    d = day or db.to_date(db.scalar(store, "SELECT MAX(date) FROM iv_expiry_daily WHERE symbol = ?", [sym]))
    if d is None:
        return {"symbol": sym, "as_of": None, "expiries": [], "smile": {}, "badges": BADGES}
    exp = db.records_sql(store, """SELECT expiry, dte, forward, forward_source, atm_iv, iv_25d_put, iv_25d_call, skew_25d, iv_10d_put, iv_10d_call,
                                   n_iv_strikes, call_oi, put_oi, pcr, expected_move_pct, quality_flags, model_version, r
                                   FROM iv_expiry_daily WHERE symbol = ? AND date = ? ORDER BY expiry""", [sym, d], DATE_COLS)
    # the smile key keeps the shipped shape exactly: groupby on a datetime64 expiry produced Timestamp.isoformat(),
    # i.e. 'YYYY-MM-DDT00:00:00' (verified live on /db/fo-iv/surface/NIFTY before this change)
    smile_rows = db.records_sql(store, """SELECT strftime(expiry, '%Y-%m-%dT00:00:00') AS _k, strike, opt_type, iv, delta, log_moneyness,
                                          price_source, oi, oi_chg, volume
                                          FROM iv_surface_daily WHERE symbol = ? AND date = ? ORDER BY expiry, strike, opt_type""", [sym, d], ())
    smile: dict[str, list[dict[str, Any]]] = {}
    for rrow in smile_rows:
        smile.setdefault(rrow.pop("_k"), []).append(rrow)
    out: dict[str, Any] = {"symbol": sym, "as_of": d.isoformat(), "model_version": MODEL_VERSION, "expiries": exp,
                           "smile": smile, "surface_stored": bool(smile_rows), "badges": BADGES}
    if compare_days:
        ghost_day = db.to_date(db.scalar(store, "SELECT MAX(date) FROM iv_expiry_daily WHERE symbol = ? AND date <= ?",
                                         [sym, d - pd.Timedelta(days=compare_days).to_pytimedelta()]))
        if ghost_day:
            g = db.query_df(store, "SELECT expiry, dte, atm_iv, skew_25d FROM iv_expiry_daily WHERE symbol = ? AND date = ? ORDER BY expiry", [sym, ghost_day])
            out["compare"] = {"as_of": ghost_day.isoformat(), "expiries": db.records(g, DATE_COLS)}
    return out


def cone(store: Any, symbol: str, *, years: tuple[int, ...] = (1, 3, 5)) -> dict[str, Any]:
    sym = symbol.upper()
    as_of = _as_of(store, sym)
    if not as_of:
        return {"symbol": sym, "as_of": None, "cone": {}, "today": {}, "badges": BADGES}
    end = date.fromisoformat(as_of)
    out: dict[str, Any] = {}
    for y in years:
        start = end.replace(year=end.year - y) if end.month != 2 or end.day != 29 else end.replace(year=end.year - y, day=28)
        df = db.query_df(store, "SELECT iv30_cm, iv60_cm, iv90_cm FROM iv_summary_daily WHERE symbol = ? AND date > ? AND date <= ?", [sym, start, end])
        tenors: dict[str, Any] = {}
        for col, tenor in (("iv30_cm", "30"), ("iv60_cm", "60"), ("iv90_cm", "90")):
            s = pd.to_numeric(df[col], errors="coerce").dropna()
            tenors[tenor] = None if len(s) < 20 else {"min": round(float(s.min()), 2), "p25": round(float(s.quantile(0.25)), 2),
                                                      "p50": round(float(s.quantile(0.5)), 2), "p75": round(float(s.quantile(0.75)), 2),
                                                      "max": round(float(s.max()), 2), "n": len(s)}
        out[f"{y}y"] = tenors
    today = db.query_df(store, "SELECT dte, atm_iv FROM iv_expiry_daily WHERE symbol = ? AND date = ? AND atm_iv IS NOT NULL ORDER BY dte", [sym, end])
    return {"symbol": sym, "as_of": as_of, "cone": out, "today": db.records(today, ()), "badges": BADGES, "verdict": "IV cone: describes, does not predict"}


def events(store: Any, symbol: str, *, n: int = 8) -> dict[str, Any]:
    sym = symbol.upper()
    rows = db.records_sql(store, """SELECT released_at, expiry, pre_session, post_session, iv_pre_5d, iv_pre_1d, iv_post_1d, crush_pct, implied_move_pct,
                                    realised_move_pct, implied_method FROM iv_event_log WHERE symbol = ? ORDER BY released_at DESC LIMIT ?""", [sym, n], DATE_COLS)
    return {"symbol": sym, "rows": rows, "badges": {"crush": "context", "implied_vs_realised": "context"},
            "verdict": "Results IV-crush ledger: describes past events, does not predict the next"}


def vol_screen(store: Any, *, sort: str = "iv_pctile", results_within: int | None = None, day: date | None = None) -> dict[str, Any]:
    sort_col = {"iv_pctile": "iv_pctile_252", "iv_rank": "iv_rank_252", "iv_minus_rv": "iv_minus_rv20", "term_slope": "term_slope_30_90",
                "skew": "skew_25d_30", "iv30": "iv30_cm"}.get(sort, "iv_pctile_252")
    d = day or db.to_date(db.scalar(store, "SELECT MAX(date) FROM iv_summary_daily"))
    if d is None:
        return {"as_of": None, "rows": [], "badges": BADGES}
    rows = db.records_sql(store, f"""SELECT s.symbol, s.spot, s.iv30_cm, s.iv_rank_252, s.iv_pctile_252, s.rv20_yz, s.rv20_cc, s.iv_minus_rv20, s.term_slope_30_90,
                                     s.skew_25d_30, s.near_expiry, s.near_dte, s.quality_flags,
                                     (SELECT MIN(e.event_date) FROM nse_events e WHERE e.symbol = s.symbol AND e.kind = 'RESULTS' AND e.event_date >= s.date) AS next_results,
                                     (SELECT c.fut_equiv_oi / NULLIF(c.mwpl, 0) * 100 FROM nse_combined_oi c WHERE c.symbol = s.symbol AND c.date = s.date) AS mwpl_pct
                                     FROM iv_summary_daily s WHERE s.date = ? ORDER BY {sort_col} DESC NULLS LAST""", [d], ("near_expiry", "next_results")) \
        if db.table_exists(store, "nse_events") else \
        db.records_sql(store, f"""SELECT symbol, spot, iv30_cm, iv_rank_252, iv_pctile_252, rv20_yz, rv20_cc, iv_minus_rv20, term_slope_30_90, skew_25d_30,
                                  near_expiry, near_dte, quality_flags, NULL AS next_results, NULL AS mwpl_pct FROM iv_summary_daily WHERE date = ?
                                  ORDER BY {sort_col} DESC NULLS LAST""", [d], ("near_expiry", "next_results"))
    if results_within is not None:
        lim = (d + pd.Timedelta(days=results_within).to_pytimedelta()).isoformat()
        rows = [r for r in rows if r.get("next_results") and r["next_results"] <= lim]
    return {"as_of": d.isoformat(), "sort": sort, "rows": rows, "count": len(rows), "badges": BADGES,
            "verdict": "VOL screener: describes, does not predict"}


def intraday(store: Any, symbol: str, *, day: date | None = None) -> dict[str, Any]:
    sym = symbol.upper()
    d = day or db.to_date(db.scalar(store, "SELECT MAX(ts)::DATE FROM iv_intraday WHERE symbol = ?", [sym]))
    if d is None:
        return {"symbol": sym, "as_of": None, "rows": [], "source": "OFFLINE", "badges": BADGES}
    df = db.query_df(store, """SELECT ts, expiry, strike, opt_type, mid, iv, nse_iv, oi, forward, spot, source FROM iv_intraday
                               WHERE symbol = ? AND ts::DATE = ? ORDER BY ts, expiry, strike, opt_type""", [sym, d])
    path: list[dict[str, Any]] = []
    for (ts, expiry), g in df.groupby(["ts", "expiry"]):
        fwd = float(g["forward"].iloc[0]) if pd.notna(g["forward"].iloc[0]) else None
        ivs = g.dropna(subset=["iv"])
        if ivs.empty or fwd is None:
            continue
        pooled = ivs.groupby("strike")["iv"].mean().sort_index()
        atm = float(pd.Series(pooled.values, index=pooled.index).reindex(sorted({*pooled.index, fwd})).interpolate(method="index").get(fwd, float("nan")))
        ce, pe = ivs[ivs["opt_type"] == "CE"], ivs[ivs["opt_type"] == "PE"]
        exp_d = db.to_date(expiry)
        path.append({"ts": db.iso_utc(ts), "expiry": exp_d.isoformat() if exp_d is not None else None, "forward": round(fwd, 2),
                     "atm_iv": round(atm, 2) if not pd.isna(atm) else None, "n_strikes": len(pooled),
                     "call_oi": float(ce["oi"].fillna(0).sum()), "put_oi": float(pe["oi"].fillna(0).sum()), "source": str(g["source"].iloc[0])})
    return {"symbol": sym, "as_of": d.isoformat(), "rows": path, "source": "breeze" if path else "OFFLINE", "badges": BADGES,
            "verdict": "Intraday IV path: describes, does not predict"}


def vix(store: Any, *, days: int = 3000) -> dict[str, Any]:
    rows = db.records_sql(store, "SELECT * FROM (SELECT date, open, high, low, close, prev_close, source FROM vix_daily ORDER BY date DESC LIMIT ?) t ORDER BY date",
                          [days], ("date",))
    return {"rows": rows, "as_of": rows[-1]["date"] if rows else None, "badge": "context"}


def index_ohlc(store: Any, symbol: str, *, days: int = 3000) -> dict[str, Any]:
    rows = db.records_sql(store, """SELECT * FROM (SELECT date, open, high, low, close, source FROM index_ohlc_daily WHERE symbol = ?
                                    ORDER BY date DESC LIMIT ?) t ORDER BY date""", [symbol.upper(), days], ("date",))
    return {"symbol": symbol.upper(), "rows": rows, "as_of": rows[-1]["date"] if rows else None}


def catalog() -> dict[str, Any]:
    rows = catalog_seed.build_rows()
    return {"rows": rows, "count": len(rows), "model_version": MODEL_VERSION}


def meta(store: Any) -> dict[str, Any]:
    pm = positions_meta(store)
    syms = db.scalar(store, "SELECT COUNT(DISTINCT symbol) FROM iv_summary_daily") if db.table_exists(store, "iv_summary_daily") else 0
    return {"tables": pm, "freshness_columns": FRESHNESS_COLUMN, "symbols": int(syms or 0), "model_version": MODEL_VERSION,
            "as_of": db.iso_utc(db.utcnow())}


# ── API_CONTRACT §6: the raw-table reads ui-api's routers/derivatives.py composes ──────────────────────────────────────
# 5 Nov 2026: ui-api read /db/iv/* (the contract) while this package served only /db/fo-iv/*, so every IV pane (OMON, DERV,
# EVTS, VOL) read OFFLINE "no IV tables yet (404)" with 2,718 surface rows stored. These are thin SELECTs; the derived
# /db/fo-iv/* payloads above stay for their own callers.
def _latest_on_or_before(store: Any, table: str, symbol: str, day: date | None) -> date | None:
    if day is None:
        return db.to_date(db.scalar(store, f"SELECT MAX(date) FROM {table} WHERE symbol = ?", [symbol]))
    return db.to_date(db.scalar(store, f"SELECT MAX(date) FROM {table} WHERE symbol = ? AND date <= ?", [symbol, day]))


def contract_summary(store: Any, symbol: str, *, days: int = 750) -> dict[str, Any]:
    """``iv_summary_daily`` for ``symbol``, the last ``days`` sessions, ascending; ``model_version`` / ``r_source`` on the payload."""
    sym = symbol.upper()
    rows = db.records_sql(store, "SELECT * FROM (SELECT * FROM iv_summary_daily WHERE symbol = ? ORDER BY date DESC LIMIT ?) t ORDER BY date",
                          [sym, days], DATE_COLS)
    as_of = rows[-1]["date"] if rows else None
    r, r_src = rate_for(store, date.fromisoformat(as_of)) if as_of else (None, None)
    return {"symbol": sym, "as_of": as_of, "model_version": MODEL_VERSION, "r": r, "r_source": r_src, "rows": rows}


def contract_expiry(store: Any, symbol: str, *, day: date | None = None) -> dict[str, Any]:
    """``iv_expiry_daily`` on ``day`` (the latest stored session on or before it; default the latest)."""
    sym = symbol.upper()
    d = _latest_on_or_before(store, "iv_expiry_daily", sym, day)
    rows = db.records_sql(store, "SELECT * FROM iv_expiry_daily WHERE symbol = ? AND date = ? ORDER BY expiry", [sym, d], DATE_COLS) if d else []
    return {"symbol": sym, "requested": day.isoformat() if day else None, "as_of": d.isoformat() if d else None, "rows": rows}


def contract_surface(store: Any, symbol: str, *, day: date | None = None) -> dict[str, Any]:
    """``iv_surface_daily`` on ``day`` (same date rule as ``contract_expiry``)."""
    sym = symbol.upper()
    d = _latest_on_or_before(store, "iv_surface_daily", sym, day)
    rows = db.records_sql(store, "SELECT * FROM iv_surface_daily WHERE symbol = ? AND date = ? ORDER BY expiry, strike, opt_type", [sym, d], DATE_COLS) if d else []
    return {"symbol": sym, "requested": day.isoformat() if day else None, "as_of": d.isoformat() if d else None, "rows": rows}


def contract_events(store: Any, symbol: str, *, n: int = 8) -> dict[str, Any]:
    """``iv_event_log`` for ``symbol``, newest first."""
    sym = symbol.upper()
    rows = db.records_sql(store, "SELECT * FROM iv_event_log WHERE symbol = ? ORDER BY released_at DESC LIMIT ?", [sym, n], DATE_COLS)
    return {"symbol": sym, "rows": rows}


def contract_intraday(store: Any, symbol: str, *, day: date | None = None) -> dict[str, Any]:
    """``iv_intraday`` rows for ``day`` (default the latest stored day; a named day is that day only, never an older one)."""
    sym = symbol.upper()
    d = day or db.to_date(db.scalar(store, "SELECT MAX(ts)::DATE FROM iv_intraday WHERE symbol = ?", [sym]))
    rows = db.records_sql(store, "SELECT * FROM iv_intraday WHERE symbol = ? AND ts::DATE = ? ORDER BY ts, expiry, strike, opt_type", [sym, d], DATE_COLS) if d else []
    return {"symbol": sym, "as_of": d.isoformat() if d else None, "rows": rows}


def contract_vix(store: Any, *, days: int = 3000) -> dict[str, Any]:
    return vix(store, days=days)


# ── M02: IV paid vs vol delivered, over each MONTHLY option's own life ────────────────────────────────────────────────
PAID_ENTRY_DTE = 30
PAID_ENTRY_TOL = 5
PAID_ALIVE_DAYS = 7          # a contract is "alive" when its last stored row is within a week of min(expiry, the last session)
PAID_DEFINITION = ("monthly expiry = the last expiry of each calendar month that traded into its final week (a contract NSE "
                   "re-dated for a holiday leaves a dead twin under the old date, which is skipped); entry = the session nearest 30 calendar days "
                   "before it (25–35); IV paid = that expiry's stored ATM IV at entry (iv_expiry_daily); vol delivered = the "
                   "close-to-close realised vol from the entry close to the expiry close, zero-mean (√(252 · mean r²), the "
                   "variance a held straddle is paid on); paid − delivered in vol points")


def monthly_expiries(expiries: list[date], last_seen: dict[date, date] | None = None, last_session: date | None = None) -> list[date]:
    """The last expiry of each calendar month (NSE's monthly series; a weekly is never chosen).

    With ``last_seen`` (expiry → its last stored session) and ``last_session``, only ALIVE contracts count: the last stored
    row lies within ``PAID_ALIVE_DAYS`` of min(expiry, last_session). Round 2 (checker): NSE re-dated the March 2026
    NIFTY / BANKNIFTY monthly from 31 to 30 March; the 2026-03-31 rows stop at 95 DTE (Dec 2025), so "the last listed
    expiry" picked the dead twin, no row sat 25–35 DTE and March vanished from the ledger with no note."""
    last: dict[tuple[int, int], date] = {}
    for e in expiries:
        if last_seen is not None and last_session is not None:
            seen = last_seen.get(e)
            if seen is None or (min(e, last_session) - seen).days > PAID_ALIVE_DAYS:
                continue
        k = (e.year, e.month)
        if k not in last or e > last[k]:
            last[k] = e
    return sorted(last.values())


def _underlying_closes(store: Any, symbol: str, start: date, end: date) -> pd.DataFrame:
    """(date, close, prev_close) for an index (index_ohlc_daily, the NSE name) or a stock (nse_bhavcopy EQ, NSE's prev_close)."""
    if symbol in INDEX_SYMBOLS:
        if not db.table_exists(store, "index_ohlc_daily"):
            return pd.DataFrame(columns=["date", "open", "high", "low", "close", "prev_close"])
        df = db.query_df(store, "SELECT date, open, high, low, close FROM index_ohlc_daily WHERE symbol = ? AND date >= ? AND date <= ? ORDER BY date",
                         [INDEX_NAMES.get(symbol, symbol), start, end])
        df["prev_close"] = df["close"].shift(1)
        return df
    if not db.table_exists(store, "nse_bhavcopy"):
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "prev_close"])
    return db.query_df(store, """SELECT date, open, high, low, close, prev_close FROM nse_bhavcopy WHERE symbol = ? AND series = 'EQ'
                                 AND date >= ? AND date <= ? ORDER BY date""", [symbol, start, end])


def delivered_vol(frame: pd.DataFrame, entry: date, expiry: date) -> dict[str, Any]:
    """Realised vol over (entry close → expiry close]: close-to-close zero-mean (the delivered number), plus the demeaned σ and
    Yang-Zhang over the same sessions for the tooltip. Corporate-action jumps (> 25 %) are dropped as everywhere."""
    d = realised._clean(frame)
    if d.empty:                                           # no underlying closes stored (a name without EQ rows): nothing delivered
        return {"rv_delivered": None, "rv_demeaned": None, "rv_yz": None, "sessions": 0}
    d = d.assign(_d=[db.to_date(x) for x in d["date"]])
    life = d[(d["_d"] > entry) & (d["_d"] <= expiry)]
    r = np.log(life["close"] / life["prev_close"]).replace([np.inf, -np.inf], np.nan).dropna()
    n = int(len(r))
    if n < 5:
        return {"rv_delivered": None, "rv_demeaned": None, "rv_yz": None, "sessions": n}
    zero_mean = math.sqrt(float((r ** 2).mean()) * 252.0) * 100.0
    life_frame = d[(d["_d"] <= expiry)].drop(columns=["_d"])
    yz = realised.yang_zhang(life_frame, n=n)
    return {"rv_delivered": round(zero_mean, 4), "rv_demeaned": round(float(r.std(ddof=1)) * math.sqrt(252.0) * 100.0, 4),
            "rv_yz": round(yz, 4) if yz is not None else None, "sessions": n}


def paid_vs_delivered(store: Any, symbol: str, *, n: int = 12) -> dict[str, Any]:
    """M02 (review 5 Nov 2026): the old ledger took the first expiry 20–60 days out (a weekly), the trailing RV20 ≈ 20
    sessions BEFORE expiry, and close-to-close under a Yang-Zhang header (mean +2.22 pts; the review's −1.76 was its own
    re-computation over those weekly rows). Here: true monthlies (alive contracts only, see ``monthly_expiries``), entry
    ≈ 30 DTE, realised over the option's own life (``PAID_DEFINITION``): NIFTY +0.63 pts over the 11 closed months to 27 Oct
    2026, 6 of 11 paid above, March 2026 −14.90 (it was +2.35 while the re-dated March monthly was dropped).
    A month with no usable row is listed in ``skipped`` with its reason, never dropped silently."""
    sym = symbol.upper()
    out: dict[str, Any] = {"symbol": sym, "rows": [], "definition": PAID_DEFINITION, "estimator": "cc_zero_mean", "entry_dte": PAID_ENTRY_DTE,
                           "badge": "context", "verdict": "IV paid vs vol delivered: describes past months, does not predict the next"}
    if not db.table_exists(store, "iv_expiry_daily"):
        return out
    allx = db.query_df(store, "SELECT date, expiry, dte, atm_iv FROM iv_expiry_daily WHERE symbol = ? ORDER BY date", [sym])
    if allx.empty:
        return out
    allx["date"], allx["expiry"] = allx["date"].map(db.to_date), allx["expiry"].map(db.to_date)
    exp = allx[allx["atm_iv"].notna()]
    if exp.empty:
        return out
    last_session = max(allx["date"])
    last_seen: dict[date, date] = {}
    for k, v in allx.groupby("expiry")["date"].max().items():
        ek, ev = db.to_date(k), db.to_date(v)
        if ek is not None and ev is not None:
            last_seen[ek] = ev
    months = monthly_expiries(sorted(set(allx["expiry"])), last_seen, last_session)
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for e in months:
        cand = exp[(exp["expiry"] == e) & (exp["dte"] >= PAID_ENTRY_DTE - PAID_ENTRY_TOL) & (exp["dte"] <= PAID_ENTRY_DTE + PAID_ENTRY_TOL)]
        if cand.empty:
            if (e - last_session).days > PAID_ENTRY_DTE - PAID_ENTRY_TOL:
                continue                                  # its entry window has not come yet: not a gap
            skipped.append({"month": f"{e.year:04d}-{e.month:02d}", "expiry": e,
                            "reason": f"no stored ATM IV {PAID_ENTRY_DTE - PAID_ENTRY_TOL}–{PAID_ENTRY_DTE + PAID_ENTRY_TOL} days before the expiry"})
            continue
        c = cand.assign(gap=(cand["dte"] - PAID_ENTRY_DTE).abs()).sort_values(["gap", "dte"], ascending=[True, False]).iloc[0]
        rows.append({"expiry": e, "entry": c["date"], "entry_dte": int(c["dte"]), "iv_paid": round(float(c["atm_iv"]), 4)})
    # months with no alive expiry at all inside the span (a data gap), named too
    if rows:
        have = {(r["expiry"].year, r["expiry"].month) for r in rows} | {(x["expiry"].year, x["expiry"].month) for x in skipped}
        y, mth = rows[0]["expiry"].year, rows[0]["expiry"].month
        end = (rows[-1]["expiry"].year, rows[-1]["expiry"].month)
        while (y, mth) < end:
            if (y, mth) not in have:
                skipped.append({"month": f"{y:04d}-{mth:02d}", "expiry": None, "reason": "no contract of the month in the store (out of F&O, or a data gap)"})
            y, mth = (y + 1, 1) if mth == 12 else (y, mth + 1)
    rows = rows[-n:]
    first = f"{rows[0]['expiry'].year:04d}-{rows[0]['expiry'].month:02d}" if rows else None
    skipped = sorted([x for x in skipped if first is None or x["month"] >= first], key=lambda x: x["month"])[-n:]
    out["skipped"] = [{**x, "expiry": x["expiry"].isoformat() if x["expiry"] else None} for x in skipped]
    if rows:
        frame = _underlying_closes(store, sym, min(r["entry"] for r in rows) - pd.Timedelta(days=10).to_pytimedelta(), max(r["expiry"] for r in rows))
        for r in rows:
            closed = r["expiry"] <= last_session
            dv = delivered_vol(frame, r["entry"], r["expiry"]) if closed else {"rv_delivered": None, "rv_demeaned": None, "rv_yz": None, "sessions": 0}
            r.update(dv)
            r["open"] = not closed
            r["paid_minus_delivered"] = round(r["iv_paid"] - dv["rv_delivered"], 4) if dv["rv_delivered"] is not None else None
            r["expiry"], r["entry"] = r["expiry"].isoformat(), r["entry"].isoformat()
    done = [r["paid_minus_delivered"] for r in rows if r["paid_minus_delivered"] is not None]
    out.update(rows=rows, closed=len(done), mean_paid_minus_delivered=round(float(np.mean(done)), 4) if done else None,
               paid_above=sum(1 for v in done if v > 0), as_of=last_session.isoformat())
    return out


def near_skew(store: Any, symbol: str, *, days: int = 750) -> dict[str, Any]:
    """M03: the NEAR expiry's own 25Δ skew history (the first expiry with dte > 2 each session — the series OMON's skew
    tile prints), so its percentile is taken against itself, never against the 30-day series."""
    sym = symbol.upper()
    if not db.table_exists(store, "iv_expiry_daily"):
        return {"symbol": sym, "rows": []}
    rows = db.records_sql(store, """SELECT * FROM (SELECT date, expiry, dte, skew_25d FROM iv_expiry_daily WHERE symbol = ? AND dte >= ? AND atm_iv IS NOT NULL
                                    QUALIFY ROW_NUMBER() OVER (PARTITION BY date ORDER BY expiry) = 1 ORDER BY date DESC LIMIT ?) t ORDER BY date""",
                          [sym, NEAR_MIN_DTE, days], DATE_COLS)
    return {"symbol": sym, "rows": rows, "series": "near expiry (dte > 2) 25Δ put − call", "badge": "context"}


def contract_delta(store: Any, symbol: str, *, expiry: date | None = None, day: date | None = None) -> dict[str, Any]:
    """M44: NSE Clearing's own delta per contract (Contract_Delta file, ``nse_contract_delta``) for one expiry, on the latest
    stored session on or before ``day``; the chain shows it beside the model delta (context)."""
    sym = symbol.upper()
    if not db.table_exists(store, "nse_contract_delta"):
        return {"symbol": sym, "as_of": None, "rows": []}
    d = _latest_on_or_before(store, "nse_contract_delta", sym, day)
    if d is None:
        return {"symbol": sym, "as_of": None, "rows": []}
    exp = expiry or db.to_date(db.scalar(store, "SELECT MIN(expiry) FROM nse_contract_delta WHERE symbol = ? AND date = ? AND expiry >= ?", [sym, d, d]))
    df = db.query_df(store, "SELECT strike, opt_type, delta_factor FROM nse_contract_delta WHERE symbol = ? AND date = ? AND expiry = ? ORDER BY strike, opt_type",
                     [sym, d, exp]) if exp else None
    return {"symbol": sym, "as_of": d.isoformat(), "expiry": exp.isoformat() if exp else None, "rows": db.records(df, ()),
            "source": "NSE Clearing Contract_Delta", "badge": "context"}


def _ban(mwpl_pct: Any) -> bool | None:
    """NSE's rule: a stock enters the F&O ban above 95 % of MWPL and leaves below 80 %; between, the state needs yesterday's."""
    if mwpl_pct is None or (isinstance(mwpl_pct, float) and pd.isna(mwpl_pct)):
        return None
    return True if mwpl_pct > 95 else False if mwpl_pct < 80 else None


def ban_list(ban_dir: Path | None, day: date) -> tuple[set[str] | None, str | None]:
    """NSE's securities-in-ban file for the session AFTER ``day`` (``fo_secban`` is named for the trade date it applies to and
    published the evening before; surveillance.py caches it as ``<trade date>.csv``), else the one for ``day`` itself.
    (symbols, its trade date) or (None, None) when no file is stored."""
    if ban_dir is None or not ban_dir.is_dir():
        return None, None
    files = sorted(p for p in ban_dir.glob("*.csv") if len(p.stem) == 10)
    after = [p for p in files if p.stem > day.isoformat()]
    pick = after[0] if after else next((p for p in reversed(files) if p.stem == day.isoformat()), None)
    if pick is None:
        return None, None
    syms = set()
    for line in pick.read_text(encoding="utf-8", errors="ignore").splitlines()[1:]:
        parts = [x.strip() for x in line.split(",")]
        if len(parts) >= 2 and parts[1]:
            syms.add(parts[1].upper())
    return syms, pick.stem


def contract_screen(store: Any, *, ban_dir: Path | None = None) -> dict[str, Any]:
    """The latest ``iv_summary_daily`` row per symbol + ``next_results``, ``mwpl_pct``, ``ban``; payload ``date``.

    M43: % MWPL = futures-equivalent OI ÷ MWPL on the newest ``nse_combined_oi`` row on or before the session that carries
    BOTH (the deleq file alone has no MWPL: 224 of 224 were empty); BAN = NSE's own ban list for the next session (the
    authoritative list: KAYNES sat at 85.5 % of MWPL inside its ban on 5 Nov), the 95 % / 80 % rule only without a file."""
    d = db.to_date(db.scalar(store, "SELECT MAX(date) FROM iv_summary_daily"))
    if d is None:
        return {"date": None, "rows": []}
    nxt = ("(SELECT MIN(e.event_date) FROM nse_events e WHERE e.symbol = s.symbol AND e.kind = 'RESULTS' AND e.event_date >= s.date)"
           if db.table_exists(store, "nse_events") else "NULL")
    have_oi = db.table_exists(store, "nse_combined_oi")
    mw = ("""(SELECT c.fut_equiv_oi / NULLIF(c.mwpl, 0) * 100 FROM nse_combined_oi c WHERE c.symbol = s.symbol AND c.date <= s.date
              AND c.mwpl IS NOT NULL AND c.fut_equiv_oi IS NOT NULL ORDER BY c.date DESC LIMIT 1)""" if have_oi else "NULL")
    mwd = ("""(SELECT MAX(c.date) FROM nse_combined_oi c WHERE c.symbol = s.symbol AND c.date <= s.date AND c.mwpl IS NOT NULL
               AND c.fut_equiv_oi IS NOT NULL)""" if have_oi else "NULL")
    # m070: stocks list ≈ 3 monthlies and the third is too thin for an ATM IV (iv60 on 23 of 224, iv90 on 2), so the screen also
    # carries the NEXT expiry after the near one (dte > 2): near → next is the term read a stock actually has
    nx = ("""(SELECT e.{c} FROM iv_expiry_daily e WHERE e.symbol = s.symbol AND e.date = s.date AND e.dte >= ? AND e.atm_iv IS NOT NULL
              ORDER BY e.expiry LIMIT 1 OFFSET 1)""" if db.table_exists(store, "iv_expiry_daily") else "NULL")
    nx_iv, nx_dte = nx.replace("{c}", "atm_iv"), nx.replace("{c}", "dte")
    n_ph = 2 if nx != "NULL" else 0
    rows = db.records_sql(store, f"""SELECT s.*, {nxt} AS next_results, {mw} AS mwpl_pct, {mwd} AS mwpl_date, {nx_iv} AS next_atm_iv, {nx_dte} AS next_dte
                                     FROM iv_summary_daily s WHERE s.date = ? ORDER BY s.symbol""", [*([NEAR_MIN_DTE] * n_ph), d],
                          (*DATE_COLS, "next_results", "mwpl_date"))
    banned, ban_date = ban_list(ban_dir, d)
    for r in rows:
        r["ban"] = (r["symbol"] in banned) if banned is not None else _ban(r.get("mwpl_pct"))
    return {"date": d.isoformat(), "rows": rows, "ban_date": ban_date, "ban_source": "NSE fo_secban" if banned is not None else "MWPL rule (95 % / 80 %)",
            "time_convention": TIME_CONVENTION, "time_convention_note": TIME_CONVENTION_NOTE}
