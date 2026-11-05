"""The attribution arithmetic (R-DRIVERS §3): returns from the split-adjusted bhavcopy, the index level from NSE's daily
file, ``points = L_{d−1} × w × r``, the per-day identity residual, the driver leader with hysteresis, concentration and
breadth. Pure functions over frames so the tests can run them on fixtures (G3)."""
from __future__ import annotations

from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from data_health import db

JUMP = 0.25
WINDOWS: dict[int, tuple[float, int]] = {20: (1.3, 5), 60: (1.2, 5)}      # window → (challenger ratio, consecutive sessions)
INDEX_LEVEL_SYMBOL: dict[str, str] = {"NIFTY 50": "NIFTY 50", "NIFTY BANK": "NIFTY BANK", "NIFTY NEXT 50": "NIFTY NEXT 50", "NIFTY IT": "NIFTY IT"}


# ── returns ────────────────────────────────────────────────────────────────────────────────────────────────────────

def load_returns(store: Any, symbols: list[str], start: date, end: date, splits: pd.DataFrame) -> pd.DataFrame:
    """Long frame (symbol, date, prev_close, close, ret, flag) from nse_bhavcopy through shared.nse_panel.adjust + splits.
    A residual |move| > 25 % after adjustment is a corporate action missing from ``splits``: ret NaN, flag set."""
    from shared.nse_panel import adjust, pick_equity_rows

    cols = ["symbol", "date", "prev_close", "close", "ret", "flag"]
    if not symbols or not db.table_exists(store, "nse_bhavcopy"):
        return pd.DataFrame(columns=cols)
    raw = db.query_df(store, """SELECT symbol, series, date, open, high, low, close, prev_close, avg_price, volume FROM nse_bhavcopy
                                WHERE date >= ? AND date <= ? AND list_contains(?, symbol) ORDER BY date""",
                      [start - pd.Timedelta(days=12).to_pytimedelta(), end, symbols])
    if raw.empty:
        return pd.DataFrame(columns=cols)
    raw["date"] = pd.to_datetime(raw["date"])
    adj = adjust(pick_equity_rows(raw), splits if len(splits) else None).sort_values(["symbol", "date"])
    adj["ret"] = adj.groupby("symbol")["adj_close"].pct_change()
    df = adj[adj["date"] >= pd.Timestamp(start)][["symbol", "date", "prev_close", "close", "ret"]].copy()
    jump = df["ret"].abs() > JUMP
    df["flag"] = pd.Series("jump_gt_25pct_excluded", index=df.index).where(jump, None)
    df.loc[jump, "ret"] = np.nan
    df["date"] = df["date"].dt.date
    return df.reset_index(drop=True)


# ── the index level ────────────────────────────────────────────────────────────────────────────────────────────────

def index_levels(store: Any, index_name: str, start: date, end: date) -> pd.DataFrame:
    """(date, close, source) for the index: index_ohlc_daily first (nse_daily_file preferred, then the valuation-history
    close), market_index_daily NIFTY50 (Yahoo) only as a flagged last resort for NIFTY 50."""
    sym = INDEX_LEVEL_SYMBOL.get(index_name, index_name)
    out = pd.DataFrame(columns=["date", "close", "source"])
    if db.table_exists(store, "index_ohlc_daily"):
        out = db.query_df(store, """SELECT date, close, source FROM index_ohlc_daily WHERE symbol = ? AND date >= ? AND date <= ?
                                    QUALIFY ROW_NUMBER() OVER (PARTITION BY date ORDER BY CASE WHEN source = 'nse_daily_file' THEN 0 ELSE 1 END) = 1
                                    ORDER BY date""", [sym, start - pd.Timedelta(days=12).to_pytimedelta(), end])
    if index_name == "NIFTY 50" and db.table_exists(store, "market_index_daily"):
        y = db.query_df(store, "SELECT date, close, 'yahoo_fallback' AS source FROM market_index_daily WHERE symbol = 'NIFTY50' AND date >= ? AND date <= ?",
                        [start - pd.Timedelta(days=12).to_pytimedelta(), end])
        have = {db.to_date(d) for d in out["date"]}
        y = y[~y["date"].map(db.to_date).isin(have)]
        out = pd.concat([out, y], ignore_index=True)
    out["date"] = out["date"].map(db.to_date)
    return out.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)


# ── contributions and fit ──────────────────────────────────────────────────────────────────────────────────────────

def contributions(index_name: str, day: date, weights: pd.DataFrame, rets: pd.DataFrame, prev_level: float, level: float, level_source: str,
                  weight_method: str, members_total: int, *, now: Any) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Rows of index_contribution_daily and the fit row for one session."""
    w = weights.set_index("symbol")["weight_pct"] / 100.0
    r = rets.set_index("symbol")
    rows = []
    for sym, wt in w.items():
        if sym not in r.index:
            continue
        ret = r.at[sym, "ret"]
        flag = r.at[sym, "flag"] if "flag" in r.columns else None
        if ret is None or (isinstance(ret, float) and np.isnan(ret)):
            rows.append({"index_name": index_name, "date": day, "symbol": sym, "ret_pct": None, "weight_pct": round(float(wt) * 100, 6), "points": None,
                         "prev_index_level": prev_level, "index_close_source": level_source, "weight_method": weight_method,
                         "flag": flag or "no_return", "computed_at": now})
            continue
        rows.append({"index_name": index_name, "date": day, "symbol": sym, "ret_pct": round(float(ret) * 100, 6), "weight_pct": round(float(wt) * 100, 6),
                     "points": round(prev_level * float(wt) * float(ret), 6), "prev_index_level": prev_level, "index_close_source": level_source,
                     "weight_method": weight_method, "flag": flag, "computed_at": now})
    df = pd.DataFrame(rows)
    explained = float(df["points"].dropna().sum()) if not df.empty else 0.0
    actual = level - prev_level
    fit = {"index_name": index_name, "date": day, "actual_points": round(actual, 4), "explained_points": round(explained, 4),
           "residual_points": round(actual - explained, 4), "index_level": level, "prev_index_level": prev_level, "index_close_source": level_source,
           "weight_method": weight_method, "members_priced": int(df["points"].notna().sum()) if not df.empty else 0, "members_total": members_total,
           "computed_at": now}
    return df, fit


# ── driver state (hysteresis), concentration, breadth ───────────────────────────────────────────────────────────────

def hysteresis_leaders(roll_abs: pd.DataFrame, ratio: float, confirm: int) -> pd.DataFrame:
    """Per date: the hysteresis leader. ``roll_abs`` is date × symbol of |rolling points| (NaN rows before the window fills).
    A challenger replaces the incumbent only after ``confirm`` consecutive sessions of ≥ ``ratio`` × the incumbent's value.
    Returns (date, leader, raw_leader, changed_from, change_date, tenure_sessions)."""
    out = []
    leader: str | None = None
    change_date: date | None = None
    changed_from: str | None = None
    tenure = 0
    streak_name: str | None = None
    streak = 0
    for d, row in roll_abs.iterrows():
        row = row.dropna()
        if row.empty:
            continue
        raw = str(row.idxmax())
        if leader is None:
            leader, change_date, tenure = raw, db.to_date(d), 1
            out.append({"date": db.to_date(d), "leader": leader, "raw_leader": raw, "changed_from": None, "change_date": change_date, "tenure_sessions": tenure})
            continue
        inc = float(row.get(leader, 0.0))
        if raw != leader and float(row[raw]) >= ratio * inc:
            if streak_name == raw:
                streak += 1
            else:
                streak_name, streak = raw, 1
        else:
            streak_name, streak = None, 0
        if streak >= confirm and streak_name is not None:
            changed_from, leader, change_date, tenure = leader, streak_name, db.to_date(d), 1
            streak_name, streak = None, 0
        else:
            tenure += 1
        out.append({"date": db.to_date(d), "leader": leader, "raw_leader": raw, "changed_from": changed_from, "change_date": change_date,
                    "tenure_sessions": tenure})
    return pd.DataFrame(out, columns=["date", "leader", "raw_leader", "changed_from", "change_date", "tenure_sessions"])


def driver_states(contrib: pd.DataFrame, rets: pd.DataFrame, levels: pd.DataFrame, weights_last: pd.DataFrame | None, index_name: str,
                  *, windows: dict[int, tuple[float, int]] | None = None, now: Any) -> pd.DataFrame:
    """index_driver_state rows for every date in ``contrib`` (long: date, symbol, points) for each window."""
    windows = windows or WINDOWS
    piv = contrib.pivot_table(index="date", columns="symbol", values="points", aggfunc="sum").sort_index()
    rpiv = rets.pivot_table(index="date", columns="symbol", values="ret", aggfunc="first").reindex(piv.index)
    lv = levels.set_index("date")["close"].reindex(piv.index)
    rows: list[dict[str, Any]] = []
    for win, (ratio, confirm) in windows.items():
        roll = piv.fillna(0.0).rolling(win, min_periods=win).sum()
        roll = roll[roll.notna().any(axis=1)]
        if roll.empty:
            continue
        lead = hysteresis_leaders(roll.abs(), ratio, confirm).set_index("date")
        ew = (1 + rpiv.fillna(0.0)).rolling(win, min_periods=win).apply(np.prod, raw=True).mean(axis=1) - 1
        cw = lv.pct_change(win)
        wpiv = contrib.pivot_table(index="date", columns="symbol", values="weight_pct", aggfunc="first").sort_index() / 100.0
        for d, r in roll.iterrows():
            dd = db.to_date(d)
            a = r.abs()
            tot = float(a.sum())
            if tot <= 0 or dd not in lead.index:
                continue
            l_row = lead.loc[dd]
            top5 = float(a.sort_values(ascending=False).head(5).sum() / tot)
            hhi_c = float(((a / tot) ** 2).sum())
            wl = wpiv.loc[d].dropna() if d in wpiv.index else pd.Series(dtype=float)
            hhi_w = float((wl ** 2).sum()) if len(wl) else None
            rw = rpiv.loc[d].dropna() if d in rpiv.index else pd.Series(dtype=float)
            win_rets = (1 + rpiv.loc[:d].tail(win).fillna(0.0)).prod() - 1 if len(rpiv.loc[:d]) >= win else pd.Series(dtype=float)
            ewv = ew.get(d)
            cwv = cw.get(d)
            rows.append({"index_name": index_name, "date": dd, "window_sessions": win, "leader": l_row["leader"],
                         "leader_points": round(float(r[l_row["leader"]]), 4) if l_row["leader"] in r.index else None,
                         "leader_share": round(float(a[l_row["leader"]] / tot), 6) if l_row["leader"] in a.index else None,
                         "tenure_sessions": int(l_row["tenure_sessions"]), "changed_from": l_row["changed_from"], "change_date": l_row["change_date"],
                         "raw_leader": l_row["raw_leader"], "top5_share": round(top5, 6), "hhi_contrib": round(hhi_c, 6),
                         "weight_hhi": round(hhi_w, 6) if hhi_w else None, "effective_n": round(1 / hhi_w, 4) if hhi_w else None,
                         "ew_minus_cw_pp": round(float(ewv - cwv) * 100, 4) if (ewv is not None and cwv is not None and np.isfinite(ewv) and np.isfinite(cwv)) else None,
                         "ew_pct": round(float(ewv) * 100, 4) if ewv is not None and np.isfinite(ewv) else None,
                         "cw_pct": round(float(cwv) * 100, 4) if cwv is not None and np.isfinite(cwv) else None,
                         "members_up": int((win_rets > 0).sum()) if len(win_rets) else int((rw > 0).sum()),
                         "members_down": int((win_rets < 0).sum()) if len(win_rets) else int((rw < 0).sum()), "computed_at": now})
    return pd.DataFrame(rows)
