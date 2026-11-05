"""Reads behind ``GET /db/index-drivers*`` (PLAN 1.2 API, data-service half; ui-api ``routers/markets.py`` (B3) wraps them).
DuckDB only; badges: members / sectors / concentration ``arithmetic`` (an identity with its residual shown), regime / breadth /
monthly leader ``context``; the regime sentence ends "describes, does not predict"; no colour, no composite score."""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from data_health import db

from index_drivers import catalog_seed
from index_drivers.schema import positions_meta

HORIZONS = {"1d": 1, "5d": 5, "1m": 21, "3m": 63, "60s": 60}
MAE_DEGRADED = 25.0
BADGES = {"members": "arithmetic", "sectors": "arithmetic", "concentration": "arithmetic", "fit": "arithmetic", "driver": "context",
          "breadth": "context", "monthly": "context"}
DESCRIBES = "describes, does not predict"


def _dates(store: Any, index_name: str) -> list[date]:
    df = db.query_df(store, "SELECT DISTINCT date FROM index_contribution_fit WHERE index_name = ? ORDER BY date", [index_name])
    return [d for d in (db.to_date(v) for v in df["date"]) if d]


def _window(store: Any, index_name: str, horizon: str, dates: list[date]) -> tuple[date, date, int] | None:
    if not dates:
        return None
    last = dates[-1]
    if horizon in HORIZONS:
        n = HORIZONS[horizon]
        sel = dates[-n:]
        return sel[0], last, len(sel)
    if horizon == "ytd":
        sel = [d for d in dates if d.year == last.year]
        return sel[0], last, len(sel)
    if horizon == "since_change":
        cd = db.scalar(store, "SELECT change_date FROM index_driver_state WHERE index_name = ? AND window_sessions = 20 AND date = ?", [index_name, last])
        cd = db.to_date(cd) or dates[-20:][0]
        sel = [d for d in dates if d >= cd]
        return sel[0], last, len(sel)
    return None


def fit_stats(store: Any, index_name: str, as_of: date, sessions: int = 60) -> dict[str, Any]:
    df = db.query_df(store, """SELECT date, actual_points, explained_points, residual_points FROM index_contribution_fit
                               WHERE index_name = ? AND date <= ? ORDER BY date DESC LIMIT ?""", [index_name, as_of, sessions])
    if df.empty:
        return {"mae_60s": None, "r2_60s": None, "residual_today": None, "degraded": True, "sessions": 0}
    err = df["residual_points"].astype(float)
    act = df["actual_points"].astype(float)
    ss = float(((act - act.mean()) ** 2).sum())
    r2 = round(1 - float((err ** 2).sum()) / ss, 4) if ss > 0 else None
    mae = round(float(err.abs().mean()), 2)
    return {"mae_60s": mae, "r2_60s": r2, "residual_today": round(float(err.iloc[0]), 2), "degraded": bool(mae > MAE_DEGRADED), "sessions": len(df)}


def drivers(store: Any, index_name: str, horizon: str = "1m") -> dict[str, Any]:
    dates = _dates(store, index_name)
    win = _window(store, index_name, horizon, dates)
    if win is None:
        return {"as_of": None, "index": index_name, "horizon": {"name": horizon}, "members": [], "badges": BADGES, "history_since": None,
                "note": "no stored attribution yet (run index_drivers_daily)"}
    start, end, n = win
    c = db.query_df(store, """SELECT c.symbol, c.ret_pct, c.weight_pct, c.points, c.date FROM index_contribution_daily c
                              WHERE c.index_name = ? AND c.date >= ? AND c.date <= ?""", [index_name, start, end])
    members_ind = db.query_df(store, """SELECT symbol, industry FROM index_constituents_daily WHERE index_name = ? AND date = (
                                          SELECT MAX(date) FROM index_constituents_daily WHERE index_name = ? AND date <= ?)""", [index_name, index_name, end])
    ind = dict(zip(members_ind["symbol"], members_ind["industry"], strict=True)) if not members_ind.empty else {}
    pts = c.groupby("symbol")["points"].sum(min_count=1)
    rets = c.pivot_table(index="date", columns="symbol", values="ret_pct", aggfunc="first")
    comp = ((1 + rets.fillna(0.0) / 100.0).prod() - 1) * 100 if not rets.empty else pd.Series(dtype=float)
    last_w = c[c["date"].map(db.to_date) == end].set_index("symbol")["weight_pct"]
    fit = db.query_df(store, "SELECT date, index_level, prev_index_level, explained_points, actual_points, weight_method FROM index_contribution_fit "
                             "WHERE index_name = ? AND date >= ? AND date <= ? ORDER BY date", [index_name, start, end])
    level_start = float(fit["prev_index_level"].iloc[0]) if not fit.empty else None
    level_end = float(fit["index_level"].iloc[-1]) if not fit.empty else None
    index_move = round(level_end - level_start, 2) if (level_start is not None and level_end is not None) else None
    explained = round(float(fit["explained_points"].sum()), 2) if not fit.empty else None
    a = pts.abs()
    tot = float(a.sum()) if len(a) else 0.0
    members = [{"symbol": s, "industry": ind.get(s), "weight_pct": round(float(last_w.get(s, np.nan)), 4) if s in last_w.index else None,
                "ret_pct": round(float(comp.get(s)), 4) if s in comp.index and np.isfinite(comp.get(s)) else None, "points": round(float(v), 2),
                "share_abs": round(float(abs(v) / tot), 6) if tot else None} for s, v in pts.sort_values(ascending=False).items()]
    sec = pd.Series({s: v for s, v in pts.items()}).groupby(lambda s: ind.get(s, "Unclassified")).sum().sort_values(ascending=False)
    secw = last_w.groupby(lambda s: ind.get(s, "Unclassified")).sum() if len(last_w) else pd.Series(dtype=float)
    sectors = [{"industry": k, "points": round(float(v), 2), "weight_pct": round(float(secw.get(k, 0.0)), 4)} for k, v in sec.items()]
    hhi_w = float(((last_w / 100.0) ** 2).sum()) if len(last_w) else None
    conc = {"top5_abs_share": round(float(a.sort_values(ascending=False).head(5).sum() / tot), 4) if tot else None,
            "hhi_contrib": round(float(((a / tot) ** 2).sum()), 4) if tot else None, "weight_hhi": round(hhi_w, 4) if hhi_w else None,
            "effective_n": round(1 / hhi_w, 1) if hhi_w else None, "top5_weight_pct": round(float(last_w.sort_values(ascending=False).head(5).sum()), 2) if len(last_w) else None}
    ew = float(comp.mean()) if len(comp) else None
    cw = round((level_end / level_start - 1) * 100, 4) if (level_start and level_end) else None
    breadth = {"ew_pct": round(ew, 4) if ew is not None else None, "cw_pct": cw, "ew_minus_cw_pp": round(ew - cw, 4) if (ew is not None and cw is not None) else None,
               "up": int((comp > 0).sum()) if len(comp) else 0, "down": int((comp < 0).sum()) if len(comp) else 0,
               "word": None if ew is None or cw is None else ("narrow" if ew - cw < -1 else "broad" if ew - cw > 1 else "even")}
    st = db.query_df(store, """SELECT window_sessions, leader, leader_share, tenure_sessions, changed_from, change_date, top5_share, ew_minus_cw_pp
                               FROM index_driver_state WHERE index_name = ? AND date = ? ORDER BY window_sessions""", [index_name, end])
    driver = {}
    for r in db.records(st, ("change_date",)):
        driver[str(r["window_sessions"])] = {"window": int(r["window_sessions"]), "leader": r["leader"], "tenure": r["tenure_sessions"],
                                             "leader_share": r["leader_share"], "changed_from": r["changed_from"], "change_date": r["change_date"],
                                             "top5_share": r["top5_share"], "ew_minus_cw_pp": r["ew_minus_cw_pp"]}
    d20 = driver.get("20")
    sentence = None
    if d20:
        sentence = (f"20-session leader {d20['leader']} for {d20['tenure']} sessions, {round((d20['leader_share'] or 0) * 100, 1)} % of member points; "
                    f"top-5 of the move {round((d20['top5_share'] or 0) * 100, 0):.0f} %; EW − CW {breadth['ew_minus_cw_pp']} pp: {breadth['word']} — {DESCRIBES}")
    return {"as_of": end.isoformat(), "index": index_name, "horizon": {"name": horizon, "from": start.isoformat(), "to": end.isoformat(), "sessions": n},
            "index_move_pts": index_move, "explained_pts": explained, "fit": fit_stats(store, index_name, end),
            "weight_method": str(fit["weight_method"].iloc[-1]) if not fit.empty else None, "members": members, "sectors": sectors,
            "concentration": conc, "breadth": breadth, "driver": driver, "regime_sentence": sentence, "history_since": dates[0].isoformat(),
            "members_note": members_note(store, index_name, end), "badges": BADGES}


def members_note(store: Any, index_name: str, day: date) -> str | None:
    first = db.to_date(db.scalar(store, "SELECT MIN(date) FROM index_constituents_daily WHERE index_name = ?", [index_name]))
    if first is None:
        return "no constituent list stored"
    return f"members as of {first.isoformat()} applied before that date" if day < first else None


def timeline(store: Any, index_name: str, *, window: int = 20, days: int = 250) -> dict[str, Any]:
    df = db.query_df(store, """SELECT date, leader, raw_leader, leader_share, tenure_sessions, changed_from, change_date, top5_share, hhi_contrib,
                               effective_n, ew_minus_cw_pp, ew_pct, cw_pct, members_up, members_down FROM index_driver_state
                               WHERE index_name = ? AND window_sessions = ? ORDER BY date DESC LIMIT ?""", [index_name, window, days]).sort_values("date")
    rows = db.records(df, ("date", "change_date"))
    changes = [r for i, r in enumerate(rows) if i == 0 or r["leader"] != rows[i - 1]["leader"]]
    return {"index": index_name, "window": window, "rows": rows, "changes": changes, "as_of": rows[-1]["date"] if rows else None,
            "badges": {"timeline": "context"}, "verdict": f"Driver timeline: {DESCRIBES}"}


def monthly(store: Any, index_name: str, *, months: int = 12) -> dict[str, Any]:
    c = db.query_df(store, """SELECT date, symbol, points FROM index_contribution_daily WHERE index_name = ? AND points IS NOT NULL
                              AND date >= (SELECT MAX(date) FROM index_contribution_daily WHERE index_name = ?) - INTERVAL (?) MONTH""",
                    [index_name, index_name, months + 1])
    if c.empty:
        return {"index": index_name, "rows": [], "badges": {"monthly": "context"}}
    c["ym"] = pd.to_datetime(c["date"]).dt.strftime("%Y-%m")
    fit = db.query_df(store, "SELECT date, index_level, prev_index_level FROM index_contribution_fit WHERE index_name = ? ORDER BY date", [index_name])
    fit["ym"] = pd.to_datetime(fit["date"]).dt.strftime("%Y-%m")
    out = []
    prev_leader = None
    for ym, g in sorted(c.groupby("ym"), key=lambda kv: kv[0]):
        s = g.groupby("symbol")["points"].sum().sort_values(ascending=False)
        a = s.abs().sort_values(ascending=False)
        f = fit[fit["ym"] == ym]
        move = round(float(f["index_level"].iloc[-1] - f["prev_index_level"].iloc[0]), 2) if not f.empty else None
        leader = str(a.index[0])
        out.append({"month": ym, "sessions": int(g["date"].nunique()), "index_move_pts": move, "explained_pts": round(float(s.sum()), 2),
                    "leader": leader, "leader_pts": round(float(s[leader]), 2), "leader_share": round(float(a.iloc[0] / a.sum()), 4),
                    "leader_changed": prev_leader is not None and leader != prev_leader,
                    "top3_add": [(k, round(float(v), 2)) for k, v in s.head(3).items()], "top3_drag": [(k, round(float(v), 2)) for k, v in s.tail(3)[::-1].items()]})
        prev_leader = leader
    return {"index": index_name, "rows": out[-months:], "badges": {"monthly": "context"}, "verdict": f"Monthly leaderboard: {DESCRIBES}"}


def catalog() -> dict[str, Any]:
    rows = catalog_seed.build_rows()
    return {"rows": rows, "count": len(rows)}


def meta(store: Any) -> dict[str, Any]:
    return {"tables": positions_meta(store), "indices": sorted({str(v) for v in db.query_df(store, "SELECT DISTINCT index_name FROM index_contribution_fit")["index_name"]}),
            "as_of": db.iso_utc(db.utcnow())}
