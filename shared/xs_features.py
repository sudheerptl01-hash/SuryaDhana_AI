"""
Point-in-time stock features for cross-sectional ranking models (feature set v3).

Every value at row t uses only data public by the evening of session t:
  * prices, volume, delivery: that day's bhavcopy;
  * F&O open interest, bulk deals: published the same evening;
  * MTF (margin-funded) positions: the file for day T appears on T+1, so shifted one session;
  * insider (PIT) disclosures: dated by the first session on or after the intimation date;
  * shareholding patterns: dated by the first session on or after the broadcast date.

Coverage matters as much as timing. Market-wide files (bhavcopy, F&O, deals, MTF) cover
every stock from their start date, so "no event" after that date is a real 0. Insider and
shareholding data were fetched per company for the symbols liquid in 2026: for any other
symbol those features are NaN, and even for covered symbols, membership itself is
survivorship-selected — compare within the covered set only (see scripts/ml_label_study.py).

Inputs are wide frames (date × symbol) from shared.nse_panel.load_panel.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from shared.deal_filters import net_bulk_deals
from shared.momentum import signals as desk_signals

NSE_EVENTS_START = pd.Timestamp("2019-10-01")     # F&O, bulk deals, insider backfill
MTF_START = pd.Timestamp("2022-01-03")
KEY_PEOPLE = re.compile(r"promoter|director|key managerial", re.I)
_GAP = -9.99e12          # "filed, value unknown" marker while forward-filling filings

TECHNICAL = ["ret_1d", "ret_5d", "ret_20d", "ret_60d", "mom_6m", "mom_12_1", "mom_nse", "high_52w", "low_52w",
             "px_sma20", "px_sma50", "px_sma200", "sma50_sma200", "rsi_14", "bb_pctb", "vol_20d", "vol_60d",
             "vol_252d", "vol_ratio", "atr_pct", "max_ret_20d", "skew_60d", "liquidity", "turnover_trend",
             "amihud_60d", "gap_1d", "close_loc", "beta_252"]
MARKET_WIDE = ["deliv_pct_20d", "deliv_surge", "fno", "oi_chg_5d", "oi_chg_20d", "pcr_oi", "oi_days",
               "bulk_inst_buy_60d", "bulk_inst_sell_60d", "bulk_other_buy_20d", "bulk_other_sell_20d",
               "mtf_intensity", "mtf_chg_20d"]
PER_COMPANY = ["insider_buy_63d", "insider_sell_63d", "insider_fresh_buy_21d",
               "shp_d_holders", "shp_d_inst", "shp_inst", "shp_retail", "shp_promoter", "shp_d_promoter"]
# Counts, flags and log-values are comparable across dates as they are; everything else is
# converted to a per-date percentile so bull and bear years share one scale.
UNRANKED = {"fno", "bulk_inst_buy_60d", "bulk_inst_sell_60d", "bulk_other_buy_20d", "bulk_other_sell_20d",
            "insider_buy_63d", "insider_sell_63d", "insider_fresh_buy_21d"}


def _live_from(frame: pd.DataFrame, start: pd.Timestamp) -> pd.DataFrame:
    """NaN for rows before a dataset existed (unknown, not zero)."""
    return frame.where(pd.Series(frame.index >= start, index=frame.index), axis=0)


def _rsi(close: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, min_periods=n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def technical_features(panel: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    c, o, h, lo, to = panel["close"], panel["open"], panel["high"], panel["low"], panel["turnover_cr"]
    r = c.pct_change(fill_method=None)
    f: dict[str, pd.DataFrame] = {"ret_1d": r}
    for name, n in (("ret_5d", 5), ("ret_20d", 20), ("ret_60d", 60), ("mom_6m", 126)):
        f[name] = c / c.shift(n) - 1
    f["mom_12_1"] = c.shift(21) / c.shift(252) - 1
    f["mom_nse"] = desk_signals(panel)["mom_nse"]                 # the Desk's own ranking score
    f["high_52w"] = c / c.rolling(252, min_periods=200).max()
    f["low_52w"] = c / c.rolling(252, min_periods=200).min()
    sma20, sd20 = c.rolling(20, min_periods=15).mean(), c.rolling(20, min_periods=15).std()
    sma50, sma200 = c.rolling(50, min_periods=40).mean(), c.rolling(200, min_periods=150).mean()
    f["px_sma20"], f["px_sma50"], f["px_sma200"] = c / sma20 - 1, c / sma50 - 1, c / sma200 - 1
    f["sma50_sma200"] = sma50 / sma200 - 1
    f["rsi_14"] = _rsi(c)
    f["bb_pctb"] = (c - (sma20 - 2 * sd20)) / (4 * sd20)
    f["vol_20d"] = r.rolling(20, min_periods=15).std()
    f["vol_60d"] = r.rolling(60, min_periods=45).std()
    f["vol_252d"] = r.rolling(252, min_periods=200).std()
    f["vol_ratio"] = f["vol_20d"] / f["vol_252d"]
    prev = c.shift(1)
    true_range = np.maximum(h - lo, np.maximum((h - prev).abs(), (lo - prev).abs()))
    f["atr_pct"] = true_range.rolling(14, min_periods=10).mean() / c
    f["max_ret_20d"] = r.rolling(20, min_periods=15).max()
    f["skew_60d"] = r.rolling(60, min_periods=45).skew()
    f["liquidity"] = np.log(to.rolling(126, min_periods=100).median())
    f["turnover_trend"] = to.rolling(20, min_periods=15).mean() / to.rolling(252, min_periods=200).mean()
    f["amihud_60d"] = (r.abs() / to.where(to > 0)).rolling(60, min_periods=45).mean()
    f["gap_1d"] = o / prev - 1
    f["close_loc"] = (c - lo) / (h - lo).where(h > lo)
    m = r.mean(axis=1)                                            # equal-weight market return
    cov = r.mul(m, axis=0).rolling(252, min_periods=200).mean() - r.rolling(252, min_periods=200).mean().mul(
        m.rolling(252, min_periods=200).mean(), axis=0)
    f["beta_252"] = cov.div(m.rolling(252, min_periods=200).var(ddof=0), axis=0)
    return f


def _wide(long: pd.DataFrame, value: str, like: pd.DataFrame, agg: str = "sum") -> pd.DataFrame:
    if long is None or long.empty:
        return pd.DataFrame(np.nan, index=like.index, columns=like.columns)
    w = long.pivot_table(index="date", columns="symbol", values=value, aggfunc=agg)
    w.index = pd.to_datetime(w.index)
    return w.reindex(index=like.index, columns=like.columns)


def to_session(dates: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """First trading session on or after each date (NaT outside the index)."""
    d = pd.to_datetime(dates)
    pos = index.searchsorted(d.values)
    return pd.Series([index[p] if (p < len(index) and v >= index[0]) else pd.NaT for p, v in zip(pos, d)],
                     index=dates.index)


def market_wide_features(panel: dict[str, pd.DataFrame], fo: pd.DataFrame | None, deals: pd.DataFrame | None,
                         mtf: pd.DataFrame | None) -> dict[str, pd.DataFrame]:
    c = panel["close"]
    f: dict[str, pd.DataFrame] = {}
    delivered = panel["volume"] * panel["deliv_pct"] / 100.0
    f["deliv_pct_20d"] = panel["deliv_pct"].rolling(20, min_periods=15).mean()
    f["deliv_surge"] = delivered.rolling(5, min_periods=4).mean() / delivered.shift(5).rolling(60, min_periods=40).mean()

    stock_fo = fo[fo["kind"] == "stock"] if fo is not None and len(fo) else None
    oi = _wide(stock_fo, "fut_oi", c)
    f["fno"] = _live_from(oi.notna().astype(float), NSE_EVENTS_START)
    f["oi_chg_5d"] = oi / oi.shift(5) - 1
    f["oi_chg_20d"] = oi / oi.shift(20) - 1
    f["pcr_oi"] = _wide(stock_fo, "put_oi", c) / _wide(stock_fo, "call_oi", c).where(lambda x: x > 0)
    f["oi_days"] = oi * c / 1e7 / panel["turnover_cr"].rolling(20, min_periods=15).mean()

    bulk = deals[deals["kind"] == "bulk"] if deals is not None and len(deals) else None
    net = net_bulk_deals(bulk) if bulk is not None and len(bulk) else pd.DataFrame(
        columns=["date", "symbol", "institution", "direction"])
    for name, inst, direction, window in (("bulk_inst_buy_60d", True, "buy", 60), ("bulk_inst_sell_60d", True, "sell", 60),
                                          ("bulk_other_buy_20d", False, "buy", 20), ("bulk_other_sell_20d", False, "sell", 20)):
        ev = net[(net["institution"] == inst) & (net["direction"] == direction)][["date", "symbol"]].drop_duplicates()
        counts = _wide(ev.assign(n=1.0), "n", c).fillna(0.0)
        f[name] = _live_from(counts.rolling(window, min_periods=1).sum(), NSE_EVENTS_START)

    q = _wide(mtf, "qty_financed", c).shift(1)                      # day-T file is published on T+1
    f["mtf_intensity"] = _live_from(q / panel["volume"].rolling(20, min_periods=15).mean(), MTF_START)
    f["mtf_chg_20d"] = _live_from(q / q.shift(20) - 1, MTF_START)
    return f


def per_company_features(panel: dict[str, pd.DataFrame], insider: pd.DataFrame | None, shp: pd.DataFrame | None,
                         covered: set[str]) -> dict[str, pd.DataFrame]:
    """Insider buying/selling and quarterly ownership change. NaN outside `covered`."""
    c = panel["close"]
    idx = c.index
    cover = pd.DataFrame(np.broadcast_to(c.columns.isin(sorted(covered)), c.shape), index=idx, columns=c.columns)
    f: dict[str, pd.DataFrame] = {}

    ins = insider.copy() if insider is not None else pd.DataFrame()
    if len(ins):
        ins = ins[ins["category"].fillna("").str.contains(KEY_PEOPLE)
                  & (pd.to_numeric(ins["value"], errors="coerce") >= 1_000_000)]
        lag = (pd.to_datetime(ins["intimation_date"]) - pd.to_datetime(ins["to_date"].fillna(ins["from_date"]))).dt.days
        ins = ins[lag.between(0, 30)].copy()                        # typo dates (1925, 2028) never map
        ins["date"] = to_session(ins["intimation_date"], idx)
        ins = ins.dropna(subset=["date"])
        ins["mode_l"] = ins["mode"].fillna("").str.lower()
        ins["lakh"] = pd.to_numeric(ins["value"], errors="coerce") / 1e5
    buys = ins[ins["mode_l"].str.contains("market purchase")] if len(ins) else ins
    sells = ins[ins["mode_l"].str.contains("market sale")] if len(ins) else ins
    for name, rows in (("insider_buy_63d", buys), ("insider_sell_63d", sells)):
        daily = _wide(rows, "lakh", c).fillna(0.0) if len(rows) else pd.DataFrame(0.0, index=idx, columns=c.columns)
        f[name] = _live_from(np.log1p(daily.rolling(63, min_periods=1).sum()), NSE_EVENTS_START).where(cover)
    fresh = pd.DataFrame(0.0, index=idx, columns=c.columns)
    if len(buys):
        b = buys[["date", "symbol"]].drop_duplicates().sort_values(["symbol", "date"])
        prev = b.groupby("symbol")["date"].shift()
        b = b[prev.isna() | ((b["date"] - prev).dt.days > 90)]
        fresh = _wide(b.assign(n=1.0), "n", c).fillna(0.0)
    f["insider_fresh_buy_21d"] = _live_from(fresh.rolling(21, min_periods=1).max(), NSE_EVENTS_START).where(cover)

    names = ["shp_d_holders", "shp_d_inst", "shp_inst", "shp_retail", "shp_promoter", "shp_d_promoter"]
    if shp is None or shp.empty:
        return {**f, **{n: pd.DataFrame(np.nan, index=idx, columns=c.columns) for n in names}}
    s = shp.copy()
    s["period_end"] = pd.to_datetime(s["period_end"])
    s = s[s["period_end"].dt.is_quarter_end & s["total_holders"].notna()]
    s["broadcast"] = pd.to_datetime(s["broadcast_ts"].astype(str).str.slice(0, 11), format="%d-%b-%Y", errors="coerce")
    s = s.sort_values(["symbol", "period_end", "broadcast"]).drop_duplicates(["symbol", "period_end"], keep="last")
    s["inst"] = (s["fpi_pct"].fillna(0) + s["mf_pct"].fillna(0)).where(s["fpi_pct"].notna() | s["mf_pct"].notna())
    g = s.groupby("symbol")
    consecutive = (s["period_end"] - g["period_end"].shift()).dt.days.between(80, 100)
    s["shp_d_holders"] = g["total_holders"].pct_change().where(consecutive)
    s["shp_d_inst"] = g["inst"].diff().where(consecutive)
    s["shp_d_promoter"] = g["promoter_pct"].diff().where(consecutive)
    s["shp_inst"], s["shp_retail"], s["shp_promoter"] = s["inst"], s["retail_pct"], s["promoter_pct"]
    s["date"] = to_session(s["broadcast"], idx)
    s = s.dropna(subset=["date"]).sort_values("broadcast").drop_duplicates(["symbol", "date"], keep="last")
    for n in names:
        # A new filing replaces the old value even when its own value is missing; values go
        # stale after ~6 months (130 sessions) without a newer filing.
        w = _wide(s.assign(**{n: s[n].fillna(_GAP)}), n, c, agg="last").ffill(limit=130)
        f[n] = w.where(w != _GAP).where(cover)
    return f


def stack(features: dict[str, pd.DataFrame], dates: pd.DatetimeIndex, universe: pd.DataFrame,
          rank: bool = True) -> pd.DataFrame:
    """Long rows (date, symbol, features…) for universe members on `dates`; continuous
    features become per-date percentiles within the universe."""
    mask = universe.reindex(index=dates).fillna(False).astype(bool)
    mask = mask.loc[:, mask.any(axis=0)]
    rows, cols = np.nonzero(mask.to_numpy())
    out: dict[str, np.ndarray] = {"date": dates[rows], "symbol": mask.columns[cols]}
    for name, frame in features.items():
        v = frame.reindex(index=dates, columns=mask.columns).where(mask)
        if rank and name not in UNRANKED:
            v = v.rank(axis=1, pct=True)
        out[name] = v.to_numpy(dtype=float)[rows, cols]
    return pd.DataFrame(out)
