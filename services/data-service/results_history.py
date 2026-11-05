"""
Results history (Bloomberg ERN for NSE): when each quarterly result was released and how the stock reacted.

Release timestamps come from two free NSE feeds (one request each, per company):
  corporates-financial-results   2007 → early 2025 (field broadCastDate)
  integrated-filing-results      April 2025 → today (SEBI's integrated filing; field broadcast_Date)
The earliest broadcast per quarter-end is the release (consolidated and standalone are filed minutes apart).
The integrated feed also carries each quarter's "Integrated Filing- Governance", filed one to two weeks *before*
the results; only "… Financials" rows count (until 14 Oct 2026 governance filings were taken as the release for
~41% of 2025–26 quarters).
Rows are stored in `nse_results` (point-in-time; refreshed per symbol at most once a week).

Reaction, from split/bonus-adjusted NSE closes:
  released while the market is open (before 15:30 IST on a session) → previous close → that session's close
  released after 15:30 or on a holiday                              → close before → next session's close
`vs_nifty` subtracts NIFTY 50's move over the same window; `gap` is the first reaction session's open vs the
close before it.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Optional

import httpx
import numpy as np
import pandas as pd

from nse_filings import API, API_HEADERS

MARKET_OPEN, MARKET_CLOSE = (9, 15), (15, 30)
AVOID_REACTION_PCT, AVOID_SESSIONS = -5.0, 60      # reports/results_drift/FINDINGS.md (H2)
FEEDS: tuple[tuple[str, dict[str, str], str, str], ...] = (("corporates-financial-results", {"period": "Quarterly"}, "broadCastDate", "toDate"),
         ("integrated-filing-results", {}, "broadcast_Date", "qe_Date"))


def _ts(v: Any) -> Optional[datetime]:
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M", "%d-%b-%Y"):
        try:
            return datetime.strptime(str(v).strip(), fmt)
        except ValueError:
            continue
    return None


def parse_releases(rows_by_feed: list[tuple[list[dict], str, str]], symbol: str) -> pd.DataFrame:
    """Earliest broadcast per quarter-end across feeds → (symbol, period_end, released_at)."""
    out = []
    for rows, ts_key, period_key in rows_by_feed:
        for r in rows or []:
            kind = str(r.get("type") or "")
            if kind and "financ" not in kind.lower():       # integrated feed: governance etc. are not results
                continue
            ts, pe = _ts(r.get(ts_key)), _ts(r.get(period_key))
            if ts and pe:
                out.append({"symbol": symbol, "period_end": pe.date(), "released_at": ts})
    if not out:
        return pd.DataFrame(columns=["symbol", "period_end", "released_at"])
    df = pd.DataFrame(out).sort_values("released_at")
    # a quarter's results arrive within days of each other (standalone / consolidated / revised): keep the first
    return df.drop_duplicates("period_end", keep="first").reset_index(drop=True)


def fetch_releases(symbol: str, client: Optional[httpx.Client] = None, sleep_s: float = 0.6) -> pd.DataFrame:
    own = client is None
    client = client or httpx.Client(headers=API_HEADERS, timeout=30, follow_redirects=True)
    got = []
    try:
        for path, extra, ts_key, period_key in FEEDS:
            try:
                r = client.get(f"{API}/{path}", params={"index": "equities", "symbol": symbol, **extra})
                data = r.json() if r.status_code == 200 else []
                got.append((data if isinstance(data, list) else data.get("data", []), ts_key, period_key))
            except (httpx.HTTPError, ValueError):
                got.append(([], ts_key, period_key))
            time.sleep(sleep_s)
    finally:
        if own:
            client.close()
    return parse_releases(got, symbol)


def reaction_pos(released: pd.Timestamp, sessions: pd.DatetimeIndex) -> tuple[int | None, str]:
    """Index in `sessions` of the session that first trades on a release, and the timing label:
    pre-open / market hours (released before 15:30 on a session → that session) or after close (→ next session)."""
    day = released.normalize()
    pos = int(sessions.searchsorted(day, side="left"))              # first session on/after the release day
    in_session = pos < len(sessions) and sessions[pos] == day and (released.hour, released.minute) < MARKET_CLOSE
    timing = ("pre-open" if (released.hour, released.minute) < MARKET_OPEN else "market hours") if in_session else "after close"
    if not in_session and pos < len(sessions) and sessions[pos] == day:
        pos += 1
    return (pos if 0 < pos < len(sessions) else None), timing


def typical_moves(con, symbols: list[str], quarters: int = 8) -> dict[str, dict[str, float]]:
    """Average absolute results-day move over each symbol's last `quarters` releases (raw EQ closes; a reaction of
    more than 40% is treated as an unadjusted split and skipped). For the corporate calendar."""
    if not symbols:
        return {}
    since = (pd.Timestamp.now() - pd.Timedelta(days=3 * 365)).date().isoformat()
    rel = con.execute("SELECT symbol, released_at FROM nse_results WHERE list_contains(?, symbol) AND released_at >= ?::TIMESTAMP",
                      [symbols, since]).df()
    if rel.empty:
        return {}
    bars = con.execute("""SELECT symbol, date, close FROM nse_bhavcopy WHERE series = 'EQ' AND list_contains(?, symbol)
                          AND date >= ?::DATE ORDER BY symbol, date""", [sorted(rel["symbol"].unique().tolist()), since]).df()
    bars["date"] = pd.to_datetime(bars["date"])
    out: dict[str, dict[str, float]] = {}
    for sym, g in rel.groupby("symbol"):
        b = bars[bars["symbol"] == sym]
        if len(b) < 2:
            continue
        sessions, close = pd.DatetimeIndex(b["date"]), b["close"].to_numpy()
        moves = []
        for ts in sorted(pd.to_datetime(g["released_at"]), reverse=True):
            pos, _ = reaction_pos(pd.Timestamp(ts), sessions)
            if pos is not None and close[pos - 1] > 0:
                m = (close[pos] / close[pos - 1] - 1) * 100
                if abs(m) < 40:
                    moves.append(abs(m))
            if len(moves) >= quarters:
                break
        if moves:
            out[sym] = {"avg_abs_move_pct": round(float(np.mean(moves)), 2), "quarters": len(moves)}
    return out


def reactions(releases: pd.DataFrame, bars: pd.DataFrame, nifty: pd.Series, limit: int = 12) -> list[dict[str, Any]]:
    """`bars`: adjusted daily rows (date, adj_open, adj_close) of the stock; `nifty`: close by date."""
    if releases.empty or bars.empty:
        return []
    b = bars.sort_values("date").set_index("date")
    sessions = b.index
    nifty = nifty.sort_index()
    out = []
    for r in releases.sort_values("released_at", ascending=False).itertuples():
        ts = pd.Timestamp(r.released_at)
        pos, timing = reaction_pos(ts, sessions)
        if pos is None:
            continue
        before, react = sessions[pos - 1], sessions[pos]
        c0, c1, o1 = b["adj_close"].iloc[pos - 1], b["adj_close"].iloc[pos], b["adj_open"].iloc[pos]
        move = (c1 / c0 - 1) * 100
        n0, n1 = nifty.asof(before), nifty.asof(react)
        idx = (n1 / n0 - 1) * 100 if pd.notna(n0) and pd.notna(n1) and n0 else None
        out.append({"period_end": pd.Timestamp(r.period_end).strftime("%Y-%m-%d"), "released_at": ts.strftime("%Y-%m-%d %H:%M"),
                    "timing": timing, "reaction_date": react.strftime("%Y-%m-%d"),
                    "move_pct": round(float(move), 2), "gap_pct": round(float((o1 / c0 - 1) * 100), 2),
                    "vs_nifty_pct": round(float(move - idx), 2) if idx is not None else None})
        if len(out) >= limit:
            break
    return out


def summary(rx: list[dict[str, Any]]) -> dict[str, Any]:
    if not rx:
        return {"quarters": 0}
    mv = pd.Series([r["move_pct"] for r in rx])
    ex = pd.Series([r["vs_nifty_pct"] for r in rx if r["vs_nifty_pct"] is not None])
    return {"quarters": len(rx), "avg_abs_move_pct": round(float(mv.abs().mean()), 2),
            "median_abs_move_pct": round(float(mv.abs().median()), 2), "up_pct": round(float((mv > 0).mean() * 100), 0),
            "biggest_up_pct": round(float(mv.max()), 2), "biggest_down_pct": round(float(mv.min()), 2),
            "avg_abs_vs_nifty_pct": round(float(ex.abs().mean()), 2) if len(ex) else None}


def recent_reactions(con, days: int = 10, min_turnover_cr: float = 5.0) -> list[dict[str, Any]]:
    """Results released in the last `days` and how each stock reacted on its reaction session (raw EQ closes; NIFTY 50
    for context), with the stock's typical results move for comparison. Releases whose reaction session has not
    traded yet are listed with move None ("pending")."""
    since = (pd.Timestamp.now().normalize() - pd.Timedelta(days=days)).isoformat()
    rel = con.execute("SELECT symbol, period_end, released_at FROM nse_results WHERE released_at >= ?::TIMESTAMP ORDER BY released_at DESC",
                      [since]).df()
    if rel.empty:
        return []
    syms = sorted(rel["symbol"].unique().tolist())
    start = (pd.Timestamp(since) - pd.Timedelta(days=40)).date().isoformat()
    bars = con.execute("""SELECT symbol, date, close, turnover_lacs FROM nse_bhavcopy WHERE series = 'EQ'
                          AND list_contains(?, symbol) AND date >= ?::DATE ORDER BY symbol, date""", [syms, start]).df()
    bars["date"] = pd.to_datetime(bars["date"])
    n50 = con.execute("SELECT date, close FROM market_index_daily WHERE symbol = 'NIFTY50' AND date >= ?::DATE ORDER BY date",
                      [start]).df()
    nifty = pd.Series(n50["close"].to_numpy(dtype=float), index=pd.to_datetime(n50["date"]))
    all_sessions = pd.DatetimeIndex(sorted(bars["date"].unique()))
    typical = typical_moves(con, syms)
    out = []
    for r in rel.itertuples():
        b = bars[bars["symbol"] == r.symbol]
        if b.empty:
            continue
        med_to = float(b["turnover_lacs"].tail(20).median()) / 100
        if med_to < min_turnover_cr:
            continue
        ts = pd.Timestamp(r.released_at)
        pos, timing = reaction_pos(ts, all_sessions)
        row: dict[str, Any] = {"symbol": r.symbol, "period_end": pd.Timestamp(r.period_end).strftime("%Y-%m-%d"),
                               "released_at": ts.strftime("%Y-%m-%d %H:%M"), "timing": timing, "turnover_cr": round(med_to, 1),
                               "reaction_date": None, "move_pct": None, "vs_nifty_pct": None, "sessions_since": None, "avoid": False,
                               "typical_move_pct": typical.get(r.symbol, {}).get("avg_abs_move_pct")}
        if pos is not None:
            d0, d1 = all_sessions[pos - 1], all_sessions[pos]
            px = b.set_index("date")["close"]
            if d0 in px.index and d1 in px.index and px[d0] > 0:
                move = (px[d1] / px[d0] - 1) * 100
                if abs(move) < 40:
                    n0, n1 = nifty.asof(d0), nifty.asof(d1)
                    vs = round(float(move - (n1 / n0 - 1) * 100), 2) if pd.notna(n0) and pd.notna(n1) else None
                    since = len(all_sessions) - 1 - pos
                    # reports/results_drift: after a ≤ −5% excess reaction, stocks lagged for ~60 sessions (H2 PASS)
                    row.update(reaction_date=d1.strftime("%Y-%m-%d"), move_pct=round(float(move), 2), vs_nifty_pct=vs,
                               sessions_since=since, avoid=bool(vs is not None and vs <= AVOID_REACTION_PCT and since <= AVOID_SESSIONS))
        out.append(row)
    return out
