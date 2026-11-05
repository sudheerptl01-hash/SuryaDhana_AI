"""Reads behind ``GET /db/fo-iv/*`` (the data-service half of PLAN 1.1's API contract; ui-api's ``routers/derivatives.py``
(B3) wraps them with the 60 s SWR cache). DuckDB only on the request path; every payload carries ``as_of``, ``since``,
``model_version``, ``r_source`` and the badges from ``catalog_seed``.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
from data_health import db

from fo_iv import catalog_seed
from fo_iv.black76 import MODEL_VERSION
from fo_iv.iv_eod import rate_for
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
    df = db.query_df(store, f"""SELECT {', '.join(SUMMARY_COLS)} FROM iv_summary_daily WHERE symbol = ? ORDER BY date DESC LIMIT ?""", [sym, days])
    df = df.sort_values("date")
    rows = db.records(df, DATE_COLS)
    vix = db.query_df(store, "SELECT date, close FROM vix_daily ORDER BY date DESC LIMIT ?", [days]).sort_values("date")
    events = db.query_df(store, "SELECT released_at, pre_session, post_session, crush_pct FROM iv_event_log WHERE symbol = ? ORDER BY released_at DESC LIMIT 40", [sym])
    as_of = _as_of(store, sym)
    r, r_src = rate_for(store, date.fromisoformat(as_of)) if as_of else (None, None)
    return {"symbol": sym, "as_of": as_of, "since": _since(store, sym), "model_version": MODEL_VERSION, "r": r, "r_source": r_src,
            "rows": rows, "vix": db.records(vix, ("date",)),
            "events": [{"date": e["post_session"], "kind": "results", "crush_pct": e["crush_pct"]} for e in db.records(events, DATE_COLS)],
            "badges": BADGES, "verdict": "IV history: describes, does not predict"}


def surface(store: Any, symbol: str, *, day: date | None = None, compare_days: int | None = None) -> dict[str, Any]:
    sym = symbol.upper()
    d = day or db.to_date(db.scalar(store, "SELECT MAX(date) FROM iv_expiry_daily WHERE symbol = ?", [sym]))
    if d is None:
        return {"symbol": sym, "as_of": None, "expiries": [], "smile": {}, "badges": BADGES}
    exp = db.query_df(store, """SELECT expiry, dte, forward, forward_source, atm_iv, iv_25d_put, iv_25d_call, skew_25d, iv_10d_put, iv_10d_call,
                                n_iv_strikes, call_oi, put_oi, pcr, expected_move_pct, quality_flags, model_version, r
                                FROM iv_expiry_daily WHERE symbol = ? AND date = ? ORDER BY expiry""", [sym, d])
    smile = db.query_df(store, """SELECT expiry, strike, opt_type, iv, delta, log_moneyness, price_source, oi, oi_chg, volume
                                  FROM iv_surface_daily WHERE symbol = ? AND date = ? ORDER BY expiry, strike, opt_type""", [sym, d])
    out: dict[str, Any] = {"symbol": sym, "as_of": d.isoformat(), "model_version": MODEL_VERSION, "expiries": db.records(exp, DATE_COLS),
                           "smile": {k.isoformat() if hasattr(k, "isoformat") else str(k)[:10]: db.records(g.drop(columns=["expiry"]), ())
                                     for k, g in smile.groupby("expiry")} if not smile.empty else {},
                           "surface_stored": not smile.empty, "badges": BADGES}
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
    df = db.query_df(store, """SELECT released_at, expiry, pre_session, post_session, iv_pre_5d, iv_pre_1d, iv_post_1d, crush_pct, implied_move_pct,
                               realised_move_pct, implied_method FROM iv_event_log WHERE symbol = ? ORDER BY released_at DESC LIMIT ?""", [sym, n])
    return {"symbol": sym, "rows": db.records(df, DATE_COLS), "badges": {"crush": "context", "implied_vs_realised": "context"},
            "verdict": "Results IV-crush ledger: describes past events, does not predict the next"}


def vol_screen(store: Any, *, sort: str = "iv_pctile", results_within: int | None = None, day: date | None = None) -> dict[str, Any]:
    sort_col = {"iv_pctile": "iv_pctile_252", "iv_rank": "iv_rank_252", "iv_minus_rv": "iv_minus_rv20", "term_slope": "term_slope_30_90",
                "skew": "skew_25d_30", "iv30": "iv30_cm"}.get(sort, "iv_pctile_252")
    d = day or db.to_date(db.scalar(store, "SELECT MAX(date) FROM iv_summary_daily"))
    if d is None:
        return {"as_of": None, "rows": [], "badges": BADGES}
    df = db.query_df(store, f"""SELECT s.symbol, s.spot, s.iv30_cm, s.iv_rank_252, s.iv_pctile_252, s.rv20_yz, s.rv20_cc, s.iv_minus_rv20, s.term_slope_30_90,
                                s.skew_25d_30, s.near_expiry, s.near_dte, s.quality_flags,
                                (SELECT MIN(e.event_date) FROM nse_events e WHERE e.symbol = s.symbol AND e.kind = 'RESULTS' AND e.event_date >= s.date) AS next_results,
                                (SELECT c.fut_equiv_oi / NULLIF(c.mwpl, 0) * 100 FROM nse_combined_oi c WHERE c.symbol = s.symbol AND c.date = s.date) AS mwpl_pct
                                FROM iv_summary_daily s WHERE s.date = ? ORDER BY {sort_col} DESC NULLS LAST""", [d]) if db.table_exists(store, "nse_events") else \
        db.query_df(store, f"""SELECT symbol, spot, iv30_cm, iv_rank_252, iv_pctile_252, rv20_yz, rv20_cc, iv_minus_rv20, term_slope_30_90, skew_25d_30,
                               near_expiry, near_dte, quality_flags, NULL AS next_results, NULL AS mwpl_pct FROM iv_summary_daily WHERE date = ?
                               ORDER BY {sort_col} DESC NULLS LAST""", [d])
    rows = db.records(df, ("near_expiry", "next_results"))
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
    df = db.query_df(store, "SELECT date, open, high, low, close, prev_close, source FROM vix_daily ORDER BY date DESC LIMIT ?", [days]).sort_values("date")
    return {"rows": db.records(df, ("date",)), "as_of": str(df["date"].iloc[-1])[:10] if not df.empty else None, "badge": "context"}


def index_ohlc(store: Any, symbol: str, *, days: int = 3000) -> dict[str, Any]:
    df = db.query_df(store, "SELECT date, open, high, low, close, source FROM index_ohlc_daily WHERE symbol = ? ORDER BY date DESC LIMIT ?",
                     [symbol.upper(), days]).sort_values("date")
    return {"symbol": symbol.upper(), "rows": db.records(df, ("date",)), "as_of": str(df["date"].iloc[-1])[:10] if not df.empty else None}


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
    df = db.query_df(store, "SELECT * FROM iv_summary_daily WHERE symbol = ? ORDER BY date DESC LIMIT ?", [sym, days]).sort_values("date")
    as_of = str(df["date"].iloc[-1])[:10] if not df.empty else None
    r, r_src = rate_for(store, date.fromisoformat(as_of)) if as_of else (None, None)
    return {"symbol": sym, "as_of": as_of, "model_version": MODEL_VERSION, "r": r, "r_source": r_src, "rows": db.records(df, DATE_COLS)}


def contract_expiry(store: Any, symbol: str, *, day: date | None = None) -> dict[str, Any]:
    """``iv_expiry_daily`` on ``day`` (the latest stored session on or before it; default the latest)."""
    sym = symbol.upper()
    d = _latest_on_or_before(store, "iv_expiry_daily", sym, day)
    df = db.query_df(store, "SELECT * FROM iv_expiry_daily WHERE symbol = ? AND date = ? ORDER BY expiry", [sym, d]) if d else None
    return {"symbol": sym, "requested": day.isoformat() if day else None, "as_of": d.isoformat() if d else None, "rows": db.records(df, DATE_COLS)}


def contract_surface(store: Any, symbol: str, *, day: date | None = None) -> dict[str, Any]:
    """``iv_surface_daily`` on ``day`` (same date rule as ``contract_expiry``)."""
    sym = symbol.upper()
    d = _latest_on_or_before(store, "iv_surface_daily", sym, day)
    df = db.query_df(store, "SELECT * FROM iv_surface_daily WHERE symbol = ? AND date = ? ORDER BY expiry, strike, opt_type", [sym, d]) if d else None
    return {"symbol": sym, "requested": day.isoformat() if day else None, "as_of": d.isoformat() if d else None, "rows": db.records(df, DATE_COLS)}


def contract_events(store: Any, symbol: str, *, n: int = 8) -> dict[str, Any]:
    """``iv_event_log`` for ``symbol``, newest first."""
    sym = symbol.upper()
    df = db.query_df(store, "SELECT * FROM iv_event_log WHERE symbol = ? ORDER BY released_at DESC LIMIT ?", [sym, n])
    return {"symbol": sym, "rows": db.records(df, DATE_COLS)}


def contract_intraday(store: Any, symbol: str, *, day: date | None = None) -> dict[str, Any]:
    """``iv_intraday`` rows for ``day`` (default the latest stored day; a named day is that day only, never an older one)."""
    sym = symbol.upper()
    d = day or db.to_date(db.scalar(store, "SELECT MAX(ts)::DATE FROM iv_intraday WHERE symbol = ?", [sym]))
    df = db.query_df(store, "SELECT * FROM iv_intraday WHERE symbol = ? AND ts::DATE = ? ORDER BY ts, expiry, strike, opt_type", [sym, d]) if d else None
    return {"symbol": sym, "as_of": d.isoformat() if d else None, "rows": db.records(df, DATE_COLS)}


def contract_vix(store: Any, *, days: int = 3000) -> dict[str, Any]:
    return vix(store, days=days)


def _ban(mwpl_pct: Any) -> bool | None:
    """NSE's rule: a stock enters the F&O ban above 95 % of MWPL and leaves below 80 %; between, the state needs yesterday's."""
    if mwpl_pct is None or (isinstance(mwpl_pct, float) and pd.isna(mwpl_pct)):
        return None
    return True if mwpl_pct > 95 else False if mwpl_pct < 80 else None


def contract_screen(store: Any) -> dict[str, Any]:
    """The latest ``iv_summary_daily`` row per symbol + ``next_results``, ``mwpl_pct``, ``ban``; payload ``date``."""
    d = db.to_date(db.scalar(store, "SELECT MAX(date) FROM iv_summary_daily"))
    if d is None:
        return {"date": None, "rows": []}
    nxt = ("(SELECT MIN(e.event_date) FROM nse_events e WHERE e.symbol = s.symbol AND e.kind = 'RESULTS' AND e.event_date >= s.date)"
           if db.table_exists(store, "nse_events") else "NULL")
    mw = ("(SELECT c.fut_equiv_oi / NULLIF(c.mwpl, 0) * 100 FROM nse_combined_oi c WHERE c.symbol = s.symbol AND c.date = s.date)"
          if db.table_exists(store, "nse_combined_oi") else "NULL")
    df = db.query_df(store, f"SELECT s.*, {nxt} AS next_results, {mw} AS mwpl_pct FROM iv_summary_daily s WHERE s.date = ? ORDER BY s.symbol", [d])
    rows = db.records(df, (*DATE_COLS, "next_results"))
    for r in rows:
        r["ban"] = _ban(r.get("mwpl_pct"))
    return {"date": d.isoformat(), "rows": rows}
