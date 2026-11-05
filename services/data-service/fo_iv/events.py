"""The results IV-crush ledger (R-IV §4.4; ``iv_event_log``; label ``context`` — it describes past events, it does not
forecast the next one).

For each (symbol, released_at) in ``nse_results``: the pre-event session (the last close before the release instant), the
post-event session (the first close after it), the near expiry chosen on the pre session (dte > 2), its ATM IV five
sessions before, one session before and one session after, ``crush_pct`` = post / pre − 1, the implied event move from the
term-structure split of the two nearest expiries (``implied_method = 'term_split'``; falls back to the 1-day move of the
pre-event ATM IV, ``'atm_1d'``) and the realised move of the underlying from the pre to the post close.
"""
from __future__ import annotations

import math
from datetime import date, datetime, time
from typing import Any

import numpy as np
import pandas as pd
from data_health import db

from fo_iv.black76 import MODEL_VERSION
from fo_iv.iv_eod import NEAR_MIN_DTE
from fo_iv.schema import CASTS, COLUMNS

SESSION_CLOSE = time(15, 30)


def event_variance_split(iv1: float, dte1: int, iv2: float, dte2: int) -> float | None:
    """Implied one-off event move (%, 1σ) from two expiries: v_e = (σ1²T1·n2 − σ2²T2·n1) / (n2 − n1) with n in calendar days.
    None when the far expiry is missing, the two are the same day or the implied event variance is not positive."""
    if dte2 <= dte1 or iv1 <= 0 or iv2 <= 0:
        return None
    t1, t2 = dte1 / 365.0, dte2 / 365.0
    tot1, tot2 = (iv1 / 100.0) ** 2 * t1, (iv2 / 100.0) ** 2 * t2
    v_e = (tot1 * dte2 - tot2 * dte1) / (dte2 - dte1)
    if v_e <= 0:
        return None
    return round(math.sqrt(v_e) * 100.0, 4)


def _sessions(store: Any, symbol: str, start: date, end: date) -> list[date]:
    df = db.query_df(store, "SELECT DISTINCT date FROM iv_summary_daily WHERE symbol = ? AND date >= ? AND date <= ? ORDER BY date", [symbol, start, end])
    return [d for d in (db.to_date(v) for v in df["date"]) if d]


def _expiry_rows(store: Any, symbol: str, day: date) -> pd.DataFrame:
    return db.query_df(store, """SELECT expiry, dte, atm_iv FROM iv_expiry_daily WHERE symbol = ? AND date = ? AND atm_iv IS NOT NULL
                                 ORDER BY dte""", [symbol, day])


def _spot(store: Any, symbol: str, day: date) -> float | None:
    v = db.scalar(store, "SELECT spot FROM iv_summary_daily WHERE symbol = ? AND date = ?", [symbol, day])
    if v is None and db.table_exists(store, "nse_bhavcopy"):
        v = db.scalar(store, "SELECT close FROM nse_bhavcopy WHERE symbol = ? AND series = 'EQ' AND date = ?", [symbol, day])
    return None if v is None or not np.isfinite(v) else float(v)


def ledger_row(store: Any, symbol: str, released_at: datetime, *, now: datetime) -> dict[str, Any] | None:
    rel_day = released_at.date()
    after_close = released_at.time() > SESSION_CLOSE
    sessions = _sessions(store, symbol, rel_day - pd.Timedelta(days=30).to_pytimedelta(), rel_day + pd.Timedelta(days=10).to_pytimedelta())
    if not sessions:
        return None
    pre_candidates = [d for d in sessions if d < rel_day or (d == rel_day and after_close)]
    post_candidates = [d for d in sessions if d > rel_day or (d == rel_day and not after_close)]
    if not pre_candidates or not post_candidates:
        return None
    pre = pre_candidates[-1]
    post = post_candidates[0]
    pre5 = pre_candidates[-6] if len(pre_candidates) >= 6 else None
    rows_pre = _expiry_rows(store, symbol, pre)
    near = rows_pre[rows_pre["dte"] >= NEAR_MIN_DTE]
    if near.empty:
        return None
    expiry = db.to_date(near.iloc[0]["expiry"])
    iv_pre_1d = float(near.iloc[0]["atm_iv"])
    method, implied = "atm_1d", round(iv_pre_1d / math.sqrt(252.0), 4)
    if len(near) >= 2:
        split = event_variance_split(float(near.iloc[0]["atm_iv"]), int(near.iloc[0]["dte"]), float(near.iloc[1]["atm_iv"]), int(near.iloc[1]["dte"]))
        if split is not None:
            method, implied = "term_split", split
    rows_post = _expiry_rows(store, symbol, post)
    hit = rows_post[rows_post["expiry"].map(db.to_date) == expiry]
    if hit.empty:                                      # the chosen expiry is gone / too short on the post session: the next one
        hit = rows_post[rows_post["dte"] >= 1]
    iv_post = float(hit.iloc[0]["atm_iv"]) if not hit.empty else None
    iv_pre5 = None
    if pre5 is not None:
        r5 = _expiry_rows(store, symbol, pre5)
        h5 = r5[r5["expiry"].map(db.to_date) == expiry]
        iv_pre5 = float(h5.iloc[0]["atm_iv"]) if not h5.empty else None
    s_pre, s_post = _spot(store, symbol, pre), _spot(store, symbol, post)
    realised = round((s_post / s_pre - 1.0) * 100.0, 4) if (s_pre and s_post) else None
    return {"symbol": symbol, "released_at": released_at, "expiry": expiry, "iv_pre_5d": iv_pre5, "iv_pre_1d": iv_pre_1d, "iv_post_1d": iv_post,
            "crush_pct": round((iv_post / iv_pre_1d - 1.0) * 100.0, 4) if iv_post else None, "implied_move_pct": implied,
            "realised_move_pct": realised, "pre_session": pre, "post_session": post, "implied_method": method, "model_version": MODEL_VERSION,
            "first_seen_at": now}


def build_ledger(store: Any, *, since: date, until: date | None = None, symbols: list[str] | None = None, now: datetime | None = None,
                 max_rows: int = 5000) -> dict[str, Any]:
    """Rows for every release in ``nse_results`` with ``released_at`` in [since, until] whose post session is stored."""
    now = now or db.utcnow()
    if not db.table_exists(store, "nse_results"):
        return {"inserted": 0, "candidates": 0, "note": "nse_results missing"}
    where = "released_at >= ? AND released_at <= ?" + (" AND list_contains(?, symbol)" if symbols else "")
    params: list[Any] = [datetime.combine(since, time(0, 0)), datetime.combine(until or now.date(), time(23, 59, 59))]
    if symbols:
        params.append(symbols)
    rel = db.query_df(store, f"SELECT symbol, released_at FROM nse_results WHERE {where} ORDER BY released_at DESC LIMIT {int(max_rows)}", params)
    out: list[dict[str, Any]] = []
    for r in rel.itertuples(index=False):
        ts = pd.Timestamp(r.released_at).to_pydatetime()
        row = ledger_row(store, str(r.symbol), ts, now=now)
        if row is not None and row["iv_post_1d"] is not None:
            out.append(row)
    n = db.upsert(store, "iv_event_log", pd.DataFrame(out), COLUMNS["iv_event_log"], CASTS["iv_event_log"]) if out else 0
    return {"inserted": n, "candidates": len(rel)}
