"""
Security profile (the terminal's DES page for one NSE stock), assembled from data already in DuckDB:

  price        NSE bhavcopy, split/bonus adjusted (shared.nse_panel.adjust): returns, 52-week range, ATR,
               moving averages, turnover, delivery % today vs its 20-session average, volume vs 50-session average
  ownership    nse_shareholding: promoter / FPI / MF / retail share and holder counts, last 8 quarters
  insiders     nse_insider_trades: last 12 months (market buys and sells by promoters, directors, KMP)
  deals        nse_deals: bulk / block / short deals, last 6 months
  derivatives  nse_fo_daily: futures OI and its 20-session change, put/call OI ratio (F&O stocks only)
  margin       nse_mtf: shares bought on exchange margin funding (MTF) now vs 20 sessions ago
  events       nse_events: upcoming and the last 90 days

Everything is end-of-day and point-in-time as stored. No signal is computed here.
"""
from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd

from shared.nse_panel import adjust, pick_equity_rows


def _f(x: Any, d: int = 2) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, d) if math.isfinite(v) else None


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            out[c] = out[c].dt.strftime("%Y-%m-%d")
    out = out.astype(object).where(out.notna(), None)
    return out.to_dict(orient="records")


def price_block(bars: pd.DataFrame) -> dict[str, Any] | None:
    """`bars`: adjusted long rows of one symbol (date, adj_open/high/low/close, adj_volume, close, deliv_pct,
    turnover_lacs), oldest first."""
    if bars.empty:
        return None
    b = bars.sort_values("date").reset_index(drop=True)
    c, h, lo = b["adj_close"], b["adj_high"], b["adj_low"]
    last = len(b) - 1

    def ret(n: int) -> float | None:
        return _f((c.iloc[-1] / c.iloc[-1 - n] - 1) * 100) if len(c) > n else None

    tr = pd.concat([h - lo, (h - c.shift()).abs(), (lo - c.shift()).abs()], axis=1).max(axis=1)
    atr14 = tr.rolling(14).mean().iloc[-1]
    win = b.tail(252)
    hi52, lo52 = win["adj_high"].max(), win["adj_low"].min()
    sma = {n: c.rolling(n, min_periods=int(n * 0.8)).mean().iloc[-1] for n in (20, 50, 200)}
    vol50 = b["adj_volume"].iloc[-51:-1].mean() if len(b) > 50 else np.nan
    deliv20 = b["deliv_pct"].iloc[-21:-1].mean() if len(b) > 20 else np.nan
    return {
        "date": b["date"].iloc[last].strftime("%Y-%m-%d"),
        "close": _f(b["close"].iloc[last]),
        "series": b["series"].iloc[last] if "series" in b else None,
        "chg_pct": ret(1),
        "returns": {"1W": ret(5), "1M": ret(21), "3M": ret(63), "6M": ret(126), "1Y": ret(252)},
        "high_52w": _f(hi52 / b["adj_factor"].iloc[last]), "low_52w": _f(lo52 / b["adj_factor"].iloc[last]),
        "from_high_pct": _f((c.iloc[-1] / hi52 - 1) * 100), "from_low_pct": _f((c.iloc[-1] / lo52 - 1) * 100),
        "atr_pct": _f(atr14 / c.iloc[-1] * 100),
        "above": {f"sma{n}": (bool(c.iloc[-1] > v) if pd.notna(v) else None) for n, v in sma.items()},
        "sma": {f"sma{n}": _f(v / b["adj_factor"].iloc[last]) for n, v in sma.items()},
        "turnover_cr": _f(b["turnover_lacs"].iloc[last] / 100, 1),
        "turnover_cr_20d": _f(b["turnover_lacs"].iloc[-20:].median() / 100, 1),
        "volume_x50": _f(b["adj_volume"].iloc[last] / vol50) if vol50 and np.isfinite(vol50) else None,
        "deliv_pct": _f(b["deliv_pct"].iloc[last], 1), "deliv_pct_20d": _f(deliv20, 1),
        "sessions": len(b),
    }


def ownership_block(sh: pd.DataFrame) -> dict[str, Any] | None:
    if sh.empty:
        return None
    s = sh.sort_values(["period_end", "broadcast_ts"]).drop_duplicates("period_end", keep="last").tail(8)
    rows = _records(s[["period_end", "promoter_pct", "fpi_pct", "mf_pct", "retail_pct", "total_holders", "retail_holders"]])
    first, last = s.iloc[0], s.iloc[-1]
    chg = {k: _f(last[k] - first[k]) if pd.notna(last[k]) and pd.notna(first[k]) else None
           for k in ("promoter_pct", "fpi_pct", "mf_pct", "retail_pct")}
    holders = _f((last["total_holders"] / first["total_holders"] - 1) * 100, 1) \
        if pd.notna(last["total_holders"]) and pd.notna(first["total_holders"]) and first["total_holders"] else None
    return {"quarters": rows[::-1], "change_over_window": chg, "holders_change_pct": holders,
            "window": f"{s['period_end'].iloc[0]:%b %Y} → {s['period_end'].iloc[-1]:%b %Y}"}


def insider_block(ins: pd.DataFrame) -> dict[str, Any]:
    if ins.empty:
        return {"rows": [], "net_market_buy_cr": 0.0, "buyers": 0, "sellers": 0}
    d = ins.sort_values("intimation_date", ascending=False)
    # on-market trades only: "Market Purchase" / "Market Sale" (not "Off Market" transfers, pledges, gifts)
    market = d[d["mode"].fillna("").str.match(r"(?i)\s*market\b")]
    buys = market[market["txn_type"].fillna("").str.contains("buy|acqui", case=False)]
    sells = market[market["txn_type"].fillna("").str.contains("sell|dispos", case=False)]
    return {
        "rows": _records(d[["intimation_date", "person", "category", "txn_type", "mode", "qty", "value"]].head(25)),
        "net_market_buy_cr": _f((buys["value"].sum() - sells["value"].sum()) / 1e7, 2),
        "buyers": int(buys["person"].nunique()), "sellers": int(sells["person"].nunique()),
    }


def deals_block(deals: pd.DataFrame) -> dict[str, Any]:
    """Bulk and block deals as rows; short-sale disclosures (no price, no client) as a one-line summary."""
    empty_short = {"days": 0, "qty": 0.0}
    if deals.empty:
        return {"rows": [], "net_value_cr": 0.0, "short": empty_short}
    d = deals.sort_values("date", ascending=False).copy()
    shorts, d = d[d["kind"] == "short"], d[d["kind"] != "short"]
    # NSE repeats a large block deal in the bulk file: keep one row per trade (the block one)
    d = d.assign(_r=np.where(d["kind"] == "block", 0, 1)).sort_values(["date", "_r"], ascending=[False, True])
    d = d.drop_duplicates(["date", "client_name", "side", "qty"], keep="first").drop(columns="_r")
    d["value_cr"] = d["qty"] * d["price"] / 1e7
    sign = np.where(d["side"].str.upper().eq("BUY"), 1.0, np.where(d["side"].str.upper().eq("SELL"), -1.0, 0.0))
    return {"rows": _records(d[["date", "kind", "client_name", "side", "qty", "price", "value_cr"]].head(30)),
            "net_value_cr": _f(float((d["value_cr"] * sign).sum()), 2),
            "short": {"days": int(shorts["date"].nunique()), "qty": _f(shorts["qty"].sum(), 0) or 0.0}}


def fo_block(fo: pd.DataFrame, spot: float | None) -> dict[str, Any] | None:
    if fo.empty:
        return None
    f = fo.sort_values("date")
    last = f.iloc[-1]
    prev = f.iloc[-21] if len(f) > 20 else f.iloc[0]
    return {
        "date": f"{last['date']:%Y-%m-%d}", "near_expiry": f"{last['near_expiry']:%Y-%m-%d}" if pd.notna(last["near_expiry"]) else None,
        "fut_close": _f(last["fut_close"]), "basis_pct": _f((last["fut_close"] / spot - 1) * 100) if spot else None,
        "fut_oi": _f(last["fut_oi"], 0), "fut_oi_chg_20d_pct": _f((last["fut_oi"] / prev["fut_oi"] - 1) * 100, 1) if prev["fut_oi"] else None,
        "pcr_oi": _f(last["put_oi"] / last["call_oi"]) if last["call_oi"] else None,
        "history": _records(f.tail(60)[["date", "fut_oi", "fut_close"]]),
    }


def mtf_block(mtf: pd.DataFrame) -> dict[str, Any] | None:
    if mtf.empty:
        return None
    m = mtf.sort_values("date")
    last = m.iloc[-1]
    prev = m.iloc[-21] if len(m) > 20 else m.iloc[0]
    return {"date": f"{last['date']:%Y-%m-%d}", "amount_cr": _f(last["amount_lakh"] / 100, 2),
            "qty": _f(last["qty_financed"], 0),
            "qty_chg_20d_pct": _f((last["qty_financed"] / prev["qty_financed"] - 1) * 100, 1) if prev["qty_financed"] else None}


def profile(con, symbol: str, industries: dict[str, str], today: date | None = None) -> dict[str, Any]:
    """Assemble the profile. `con` is a DuckDB connection (caller holds the store lock)."""
    sym = symbol.upper().strip()
    today = today or date.today()
    start = (today - timedelta(days=560)).isoformat()
    raw = con.execute("SELECT * FROM nse_bhavcopy WHERE symbol = ? AND date >= ?::DATE", [sym, start]).df()
    if raw.empty:
        return {"symbol": sym, "found": False}
    raw["date"] = pd.to_datetime(raw["date"])
    splits = con.execute("SELECT ticker, date, ratio FROM splits WHERE ratio > 0 AND ticker IN (?, ?)",
                         [sym, f"{sym}.NS"]).df()
    splits["date"] = pd.to_datetime(splits["date"]).dt.tz_localize(None).dt.normalize()
    splits["ticker"] = sym
    eq = pick_equity_rows(raw)
    bars = adjust(eq, splits) if not eq.empty else eq
    # adjust() keeps the detected actions in .attrs; a DataFrame there breaks pd.concat on derived series
    ca = bars.attrs.pop("corporate_actions", None)
    price = price_block(bars) if not eq.empty else None

    q = lambda sql, *p: con.execute(sql, list(p)).df()  # noqa: E731
    sh = q("SELECT * FROM nse_shareholding WHERE symbol = ? ORDER BY period_end", sym)
    if not sh.empty:
        sh["period_end"] = pd.to_datetime(sh["period_end"])
    ins = q("SELECT * FROM nse_insider_trades WHERE symbol = ? AND intimation_date >= ?::DATE", sym,
            (today - timedelta(days=365)).isoformat())
    deals = q("SELECT * FROM nse_deals WHERE symbol = ? AND date >= ?::DATE", sym, (today - timedelta(days=183)).isoformat())
    fo = q("SELECT * FROM nse_fo_daily WHERE symbol = ? AND kind = 'stock' AND date >= ?::DATE", sym,
           (today - timedelta(days=120)).isoformat())
    for frame, cols in ((fo, ("date", "near_expiry")), (deals, ("date",)), (ins, ("intimation_date",))):
        for col in cols:
            if not frame.empty:
                frame[col] = pd.to_datetime(frame[col])
    mtf = q("SELECT * FROM nse_mtf WHERE symbol = ? AND date >= ?::DATE", sym, (today - timedelta(days=60)).isoformat())
    if not mtf.empty:
        mtf["date"] = pd.to_datetime(mtf["date"])
    ev = q("""SELECT CAST(event_date AS VARCHAR) AS event_date, kind, tags, purpose, detail, source, url FROM nse_events
              WHERE symbol = ? AND event_date >= ?::DATE ORDER BY event_date""", sym, (today - timedelta(days=90)).isoformat())
    return {
        "symbol": sym, "found": True, "industry": industries.get(sym),   # company names: the UI's symbol directory
        "price": price,
        "corporate_actions": _records(ca[["date", "k", "source"]]) if ca is not None and len(ca) else [],
        "ownership": ownership_block(sh),
        "insiders": insider_block(ins),
        "deals": deals_block(deals),
        "derivatives": fo_block(fo, price["close"] if price else None),
        "margin_funding": mtf_block(mtf),
        "events": _records(ev.astype(object).where(ev.notna(), None)) if not ev.empty else [],
    }


def drawdown_stats(b: pd.DataFrame) -> dict[str, Any]:
    """Largest peak-to-trough fall inside the window on adjusted closes (with its dates), and how far the last close
    is below the window's peak. `b`: bars oldest first with date, adj_close."""
    c = pd.Series(b["adj_close"].to_numpy(dtype=float), index=pd.to_datetime(b["date"]))
    if c.empty:
        return {"max_dd_pct": None, "dd_peak": None, "dd_trough": None, "dd_now_pct": None}
    peak = c.cummax()
    dd = c / peak - 1
    trough = dd.idxmin()
    peak_day = c[:trough].idxmax()
    return {"max_dd_pct": _f(dd.min() * 100), "dd_peak": peak_day.date().isoformat(), "dd_trough": trough.date().isoformat(),
            "dd_now_pct": _f(dd.iloc[-1] * 100)}


def history_rows(bars: pd.DataFrame, actions: pd.DataFrame | None = None) -> dict[str, Any]:
    """Bloomberg HP for one stock: daily bars as traded (raw OHLC, VWAP, volume, ₹ value, trades, delivery %), the
    day's change on split/bonus-adjusted closes (an ex-date is not a crash), and the corporate actions inside the
    window. `bars` = adjust(pick_equity_rows(...)) for one symbol, oldest first. Rows come back newest first."""
    if bars.empty:
        return {"rows": [], "summary": None, "actions": []}
    b = bars.sort_values("date").reset_index(drop=True)
    chg = b["adj_close"].pct_change() * 100
    acts = {}
    if actions is not None and len(actions):
        acts = {pd.Timestamp(d).date().isoformat(): float(k) for d, k in zip(actions["date"], actions["k"])}
    rows = []
    for i in range(len(b) - 1, -1, -1):
        r = b.iloc[i]
        d = pd.Timestamp(r["date"]).date().isoformat()
        rows.append({"date": d, "open": _f(r["open"]), "high": _f(r["high"]), "low": _f(r["low"]), "close": _f(r["close"]),
                     "vwap": _f(r.get("avg_price")), "change_pct": _f(chg.iat[i]), "volume": int(r["volume"] or 0),
                     "value_cr": _f((r.get("turnover_lacs") or 0) / 100, 2), "trades": int(r["trades"]) if pd.notna(r.get("trades")) else None,
                     "deliv_pct": _f(r.get("deliv_pct"), 1), "series": r.get("series"),
                     "action_k": acts.get(d)})           # price multiplier on an ex-date (0.5 = 1:1 bonus / 2-for-1 split)
    first, last = b.iloc[0], b.iloc[-1]
    summary = {"from": pd.Timestamp(first["date"]).date().isoformat(), "to": pd.Timestamp(last["date"]).date().isoformat(),
               "sessions": int(len(b)),
               "return_pct": _f((last["adj_close"] / first["adj_close"] - 1) * 100) if first["adj_close"] else None,
               "high": _f(b["adj_high"].max()), "low": _f(b["adj_low"].min()),
               "avg_value_cr": _f(b["turnover_lacs"].mean() / 100, 2) if "turnover_lacs" in b else None,
               "avg_deliv_pct": _f(b["deliv_pct"].mean(), 1) if "deliv_pct" in b and b["deliv_pct"].notna().any() else None,
               "up_days": int((chg > 0).sum()), "down_days": int((chg < 0).sum()), **drawdown_stats(b)}
    return {"rows": rows, "summary": summary, "actions": [{"date": d, "k": k} for d, k in sorted(acts.items())]}


def price_history(con, symbol: str, days: int = 90, today: date | None = None) -> dict[str, Any]:
    """HP: the last `days` calendar days of `symbol` from the NSE bhavcopy. `con`: DuckDB (caller holds the lock)."""
    sym = symbol.upper().strip()
    today = today or date.today()
    start = (today - timedelta(days=days)).isoformat()
    raw = con.execute("SELECT * FROM nse_bhavcopy WHERE symbol = ? AND date >= ?::DATE", [sym, start]).df()
    if raw.empty:
        return {"symbol": sym, "found": False, "rows": [], "summary": None, "actions": []}
    raw["date"] = pd.to_datetime(raw["date"])
    splits = con.execute("SELECT ticker, date, ratio FROM splits WHERE ratio > 0 AND ticker IN (?, ?)",
                         [sym, f"{sym}.NS"]).df()
    splits["date"] = pd.to_datetime(splits["date"]).dt.tz_localize(None).dt.normalize()
    splits["ticker"] = sym
    eq = pick_equity_rows(raw)
    if eq.empty:
        return {"symbol": sym, "found": False, "rows": [], "summary": None, "actions": []}
    bars = adjust(eq, splits)
    ca = bars.attrs.pop("corporate_actions", None)
    return {"symbol": sym, "found": True, **history_rows(bars, ca)}
