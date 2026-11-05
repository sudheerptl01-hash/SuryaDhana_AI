"""
Market Monitor — the terminal's "how is the market today" screen, from NSE's own bhavcopy.

Universe (breadth): EQ-series stocks priced ≥ ₹20 with a 20-session median turnover ≥ ₹1 crore and at least 60
sessions of history, ETFs excluded (prices split/bonus adjusted by shared.nse_panel). Everything is end-of-day.

Regime score 0–4 (the SuryaDhana Scanner Handbook, Stage 2), one point each:
  trend          Nifty 500 above a rising 200-DMA (rising = higher than 20 sessions ago)
  breadth        ≥ 50% of the universe above both its 50- and 200-DMA
  participation  Stockbee Market Monitor 10-day ratio (≥ +4% on higher volume ÷ ≤ −4% on higher volume) ≥ 1.5
                 and the 10-day average of new 52-week highs − lows > 0
  risk           ≤ 4 distribution days in 25 sessions (index ≤ −0.2% on higher universe turnover) and India VIX
                 below its 1-year 80th percentile
A market-health gauge, not a buy signal: in the handbook backtest (reports/handbook_swing/) breakouts entered on
score-4 days did worst.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

EXPOSURE = {4: ("100%", "breakouts and pullbacks"), 3: ("75%", "breakouts and pullbacks"),
            2: ("40%", "pullbacks only, tighter stops"), 1: ("0–20%", "mostly cash"), 0: ("0–20%", "mostly cash")}


def _f(x: Any, d: int = 2) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return round(v, d) if math.isfinite(v) else None


def _ordinal(x: float) -> str:
    n = int(round(x))
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def universe(panel: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Liquid EQ stocks, no ETFs (same ETF rule as the Desk: shared.momentum.is_etf)."""
    from shared.momentum import is_etf
    c, to = panel["close"], panel["turnover_cr"]
    hist = c.notna().cumsum()
    not_etf = pd.Series([not is_etf(str(s)) for s in c.columns], index=c.columns)
    return (panel["series"].eq("EQ") & (panel["raw_close"] >= 20)
            & (to.rolling(20, min_periods=10).median() >= 1.0) & (hist >= 60)) & not_etf


def breadth_series(panel: dict[str, pd.DataFrame], index_close: pd.Series, vix: pd.Series) -> pd.DataFrame:
    """Daily market-health series over the panel's dates."""
    c, h, lo, v = panel["close"], panel["high"], panel["low"], panel["volume"]
    u = universe(panel)
    ret = c.pct_change(fill_method=None)
    n = u.sum(axis=1).replace(0, np.nan)
    sma = {k: c.rolling(k, min_periods=int(k * 0.8)).mean() for k in (20, 50, 200)}
    # Denominator = universe stocks whose average exists; NaN while most of the universe is still warming up
    def share(cond: pd.DataFrame, valid: pd.DataFrame) -> pd.Series:
        d = (valid & u).sum(axis=1)
        return ((cond & u).sum(axis=1) / d.replace(0, np.nan) * 100).where(d >= 0.5 * n)
    above = {k: share(c > sma[k], sma[k].notna()) for k in sma}
    both = share((c > sma[50]) & (c > sma[200]), sma[200].notna())
    adv, dec = ((ret > 0) & u).sum(axis=1), ((ret < 0) & u).sum(axis=1)
    vol_up = v > v.shift(1)
    up4, dn4 = ((ret >= 0.04) & vol_up & u).sum(axis=1), ((ret <= -0.04) & vol_up & u).sum(axis=1)
    hi52 = h.rolling(252, min_periods=120).max()
    lo52 = lo.rolling(252, min_periods=120).min()
    nh, nl = ((h >= hi52) & u).sum(axis=1), ((lo <= lo52) & u).sum(axis=1)
    idx = index_close.reindex(c.index).ffill()
    i200 = idx.rolling(200, min_periods=180).mean()
    turnover = panel["turnover_cr"].where(u).sum(axis=1)
    dist = (idx.pct_change() <= -0.002) & (turnover > turnover.shift(1))
    vx = vix.reindex(c.index).ffill()
    vix_pct = vx.rolling(252, min_periods=120).apply(lambda w: (w[:-1] < w[-1]).mean() * 100, raw=True)
    s = pd.DataFrame({
        "universe": n, "adv": adv, "dec": dec, "pct_above20": above[20], "pct_above50": above[50],
        "pct_above200": above[200], "pct_above50_and_200": both, "up4": up4, "dn4": dn4,
        "mm_ratio5": up4.rolling(5).sum() / dn4.rolling(5).sum().replace(0, np.nan),
        "mm_ratio10": up4.rolling(10).sum() / dn4.rolling(10).sum().replace(0, np.nan),
        "new_highs": nh, "new_lows": nl, "nh_nl_10d": (nh - nl).rolling(10).mean(),
        "index": idx, "index_sma200": i200, "dist_days_25": dist.rolling(25).sum(), "vix": vx, "vix_pct": vix_pct,
        "turnover_cr": turnover,
    })
    s["ad_line"] = (adv - dec).cumsum()
    s["trend_ok"] = (idx > i200) & (i200 > i200.shift(20))
    s["breadth_ok"] = both >= 50
    s["participation_ok"] = (s["mm_ratio10"] >= 1.5) & (s["nh_nl_10d"] > 0)
    s["risk_ok"] = (s["dist_days_25"] <= 4) & (s["vix_pct"] < 80)
    s["score"] = s[["trend_ok", "breadth_ok", "participation_ok", "risk_ok"]].astype(int).sum(axis=1)
    return s


def sector_table(panel: dict[str, pd.DataFrame], industries: dict[str, str]) -> list[dict[str, Any]]:
    c = panel["close"]
    u = universe(panel).iloc[-1]
    syms = u.index[u.fillna(False).to_numpy(dtype=bool)]
    ind = pd.Series({s: industries.get(s, "Unknown") for s in syms})
    last = c.iloc[-1][syms]
    rets = {k: last / c.iloc[-1 - k][syms] - 1 for k in (1, 5, 21, 63)}
    sma50 = c[syms].rolling(50, min_periods=40).mean().iloc[-1]
    df = pd.DataFrame({"industry": ind, **{f"r{k}": v for k, v in rets.items()}, "above50": last > sma50})
    rows = []
    for name, g in df.groupby("industry"):
        if name == "Unknown" or len(g) < 3:
            continue
        rows.append({"industry": name, "stocks": len(g), **{f"ret_{k}d_pct": _f(g[f"r{k}"].mean() * 100) for k in (1, 5, 21, 63)},
                     "pct_above50": _f(g["above50"].mean() * 100, 0)})
    return sorted(rows, key=lambda r: -(r["ret_21d_pct"] or -1e9))


def movers(panel: dict[str, pd.DataFrame], industries: dict[str, str], top: int = 12) -> dict[str, list[dict[str, Any]]]:
    c, h, lo, v, to = panel["close"], panel["high"], panel["low"], panel["volume"], panel["turnover_cr"]
    u = universe(panel).iloc[-1].fillna(False).astype(bool)
    liquid = u & (to.rolling(20, min_periods=10).median().iloc[-1] >= 5)     # movers need real liquidity
    r1 = (c.iloc[-1] / c.iloc[-2] - 1) * 100
    volx = v.iloc[-1] / v.rolling(50, min_periods=30).mean().iloc[-2]
    hi52 = h.rolling(252, min_periods=120).max().iloc[-1]
    lo52 = lo.rolling(252, min_periods=120).min().iloc[-1]
    df = pd.DataFrame({"close": c.iloc[-1], "chg_pct": r1, "turnover_cr": to.iloc[-1], "vol_x": volx,
                       "from_52w_high_pct": (c.iloc[-1] / hi52 - 1) * 100,
                       "new_high": h.iloc[-1] >= hi52, "new_low": lo.iloc[-1] <= lo52})

    def rows(sel: pd.Series, key: str, asc: bool) -> list[dict[str, Any]]:
        d = df[sel].dropna(subset=["close", "chg_pct"]).sort_values(key, ascending=asc).head(top)
        return [{"symbol": s, "industry": industries.get(s, "—"), "close": _f(r.close), "chg_pct": _f(r.chg_pct),
                 "turnover_cr": _f(r.turnover_cr, 1), "vol_x": _f(r.vol_x, 1),
                 "from_52w_high_pct": _f(r.from_52w_high_pct, 1)} for s, r in d.iterrows()]
    return {
        "gainers": rows(liquid, "chg_pct", False),
        "losers": rows(liquid, "chg_pct", True),
        "most_active": rows(u, "turnover_cr", False),
        "volume_shockers": rows(liquid & (df["vol_x"] >= 3), "vol_x", False),
        "new_highs": rows(u & df["new_high"], "turnover_cr", False),
        "new_lows": rows(u & df["new_low"], "turnover_cr", False),
    }


def market_map(panel: dict[str, pd.DataFrame], industries: dict[str, str], n: int = 250) -> list[dict[str, Any]]:
    """The n most traded stocks (20-session median turnover) with 1D / 1W / 1M returns, for the heatmap.
    Size = median turnover (a liquidity proxy: free-float market cap is not in the free NSE files)."""
    c, to = panel["close"], panel["turnover_cr"]
    u = universe(panel).iloc[-1].fillna(False).astype(bool)
    med = to.rolling(20, min_periods=10).median().iloc[-1][u].dropna().sort_values(ascending=False).head(n)
    last = c.iloc[-1]
    out = []
    for sym, size in med.items():
        rets = {k: (last[sym] / c.iloc[-1 - k][sym] - 1) * 100 if len(c) > k else np.nan for k in (1, 5, 21)}
        out.append({"symbol": sym, "industry": industries.get(sym, "Unclassified"), "size": _f(size, 1),
                    "r1": _f(rets[1]), "r5": _f(rets[5]), "r21": _f(rets[21])})
    return out


def rotation(panel: dict[str, pd.DataFrame], industries: dict[str, str], tail_weeks: int = 8,
             min_stocks: int = 5) -> list[dict[str, Any]]:
    """Relative rotation (RRG-style) of NSE industries against the equal-weight universe.

    Industry index = equal-weight daily returns of its liquid members; RS = industry ÷ universe;
    RS-ratio = 100 × RS ÷ its 50-session mean, EMA(10)-smoothed (above 100 = outperforming its own recent trend);
    RS-momentum = 100 × RS-ratio ÷ RS-ratio 10 sessions earlier, EMA(5)-smoothed (above 100 = improving).
    Points are weekly (every 5 sessions); the tail shows the last `tail_weeks` weeks. Descriptive, not a signal.
    """
    c = panel["close"]
    u = universe(panel)
    ret = c.pct_change(fill_method=None).where(u.shift(1, fill_value=False))      # member yesterday → counts today
    bench = (1 + ret.mean(axis=1).fillna(0)).cumprod()
    members = pd.Series({s: industries.get(s) for s in c.columns}).dropna()
    out = []
    for name, syms in members.groupby(members).groups.items():
        cols = [s for s in syms if s in ret.columns]
        if int(u.iloc[-1][cols].sum()) < min_stocks:
            continue
        idx = (1 + ret[cols].mean(axis=1).fillna(0)).cumprod()
        rs = idx / bench
        ratio = (100 * rs / rs.rolling(50, min_periods=40).mean()).ewm(span=10, min_periods=5).mean()
        mom = (100 * ratio / ratio.shift(10)).ewm(span=5, min_periods=3).mean()
        pts = pd.DataFrame({"x": ratio, "y": mom}).dropna().iloc[::-1].iloc[::5].iloc[:tail_weeks].iloc[::-1]
        if len(pts) < 2:
            continue
        x, y = pts["x"].iloc[-1], pts["y"].iloc[-1]
        quadrant = "Leading" if x >= 100 and y >= 100 else "Weakening" if x >= 100 else "Lagging" if y < 100 else "Improving"
        out.append({"industry": name, "stocks": int(u.iloc[-1][cols].sum()), "quadrant": quadrant,
                    "tail": [{"date": str(d.date()), "x": _f(r.x, 2), "y": _f(r.y, 2)} for d, r in pts.iterrows()]})
    return sorted(out, key=lambda r: r["industry"])


def snapshot(panel: dict[str, pd.DataFrame], index_close: pd.Series, index_name: str, vix: pd.Series,
             industries: dict[str, str], history: int = 250) -> dict[str, Any]:
    s = breadth_series(panel, index_close, vix)
    last, prev = s.iloc[-1], s.iloc[-2]
    score = int(last["score"])
    hist = s.tail(history)
    return {
        "as_of": str(s.index[-1].date()),
        "index_name": index_name,
        "regime": {
            "score": score, "exposure": EXPOSURE[score][0], "setups": EXPOSURE[score][1],
            "components": [
                {"key": "trend", "label": f"{index_name} above a rising 200-DMA", "ok": bool(last["trend_ok"]),
                 "detail": f"{last['index']:,.0f} vs 200-DMA {last['index_sma200']:,.0f}" if pd.notna(last["index_sma200"]) else "—"},
                {"key": "breadth", "label": "≥ 50% of stocks above their 50- and 200-DMA", "ok": bool(last["breadth_ok"]),
                 "detail": f"{last['pct_above50_and_200']:.0f}% above both"},
                {"key": "participation", "label": "Market Monitor 10-day ≥ 1.5 and new highs > new lows",
                 "ok": bool(last["participation_ok"]),
                 "detail": f"ratio {last['mm_ratio10']:.2f} · NH−NL 10d avg {last['nh_nl_10d']:+.0f}" if pd.notna(last["mm_ratio10"]) else "—"},
                {"key": "risk", "label": "≤ 4 distribution days in 25 and VIX below its 80th percentile",
                 "ok": bool(last["risk_ok"]),
                 "detail": f"{int(last['dist_days_25'])} distribution days · VIX {last['vix']:.1f} ({_ordinal(last['vix_pct'])} percentile)"
                 if pd.notna(last["vix_pct"]) else "—"},
            ],
            "changed_from": int(prev["score"]),
            "days_at_score": int((s["score"][::-1] != score).cumsum().eq(0).sum()),
        },
        "breadth": {k: _f(last[k], 2) for k in ("universe", "adv", "dec", "pct_above20", "pct_above50", "pct_above200",
                                                 "up4", "dn4", "mm_ratio5", "mm_ratio10", "new_highs", "new_lows",
                                                 "nh_nl_10d", "dist_days_25", "vix", "vix_pct", "turnover_cr")}
                   | {"index": _f(last["index"]), "index_chg_pct": _f((last["index"] / prev["index"] - 1) * 100),
                      "index_sma200": _f(last["index_sma200"]),
                      "pct_above20_chg": _f(last["pct_above20"] - prev["pct_above20"], 1)},
        "history": [{"date": str(d.date()), "score": int(r.score), "pct_above50": _f(r.pct_above50, 1),
                     "pct_above200": _f(r.pct_above200, 1), "ad_line": int(r.ad_line), "nh_nl": int(r.new_highs - r.new_lows),
                     "index": _f(r["index"]), "mm_ratio10": _f(r.mm_ratio10)} for d, r in hist.iterrows()],
        "sectors": sector_table(panel, industries),
        "movers": movers(panel, industries),
        "map": market_map(panel, industries),
        "rotation": rotation(panel, industries),
    }
