"""
Survivorship-free, corporate-action-adjusted daily panel from NSE full bhavcopy.

Raw bhavcopy prices are unadjusted, and (checked 2026-09-27 on IRB's 1:10 split)
NSE's PREV_CLOSE is NOT adjusted on the ex-date either. So splits/bonuses come from:
  1. the Yahoo splits table (authoritative for names Yahoo still covers; bonus
     issues appear there as splits), matched to the first NSE session on or within
     7 days after the listed date;
  2. for names Yahoo doesn't cover (mostly delisted), an overnight gap
     open / previous close < 0.78 or > 1.35 that matches a standard split/bonus
     ratio within 6%. Circuit bands (≤ 20%) make such gaps impossible for real
     trading, so they can only be corporate actions. Gaps after a >7-day trading
     halt (relisting, suspension) are left alone.
Prices before an event are multiplied by every later factor k; volumes divided.

Known limits: symbol renames split one company into two histories; ordinary
dividends are not adjusted (price returns).

Usage (research):
    from nse_panel import load_panel
    panel = load_panel(con, start="2020-01-01")      # dict of wide DataFrames
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# series that trade as ordinary equity (EQ = rolling settlement, BE/BZ = trade-to-trade)
EQUITY_SERIES = ("EQ", "BE", "BZ")
# price factor k = new/old per share: splits 1:2 .. 1:20 and bonus a:b → b/(a+b)
STANDARD_FACTORS = np.array([0.05, 0.1, 0.2, 0.25, 1 / 3, 0.4, 0.5, 0.6, 2 / 3, 1.5, 2.0, 5.0, 10.0])
GAP_LOW, GAP_HIGH, SNAP_TOL, MAX_HALT_DAYS = 0.78, 1.35, 0.06, 7
RAW_LOW, RAW_HIGH = 0.6, 1.6        # beyond any circuit band: when Yahoo confirms an event nearby, use the actual ratio


def _snap(gap: float) -> float | None:
    rel = np.abs(STANDARD_FACTORS / gap - 1)
    i = int(np.argmin(rel))
    return float(STANDARD_FACTORS[i]) if rel[i] <= SNAP_TOL else None


def corporate_action_factors(df: pd.DataFrame, splits: pd.DataFrame | None = None) -> pd.DataFrame:
    """Rows (symbol, date, k, source) for every detected split/bonus. `df` is long
    bhavcopy sorted by symbol, date with columns symbol, date, open, close."""
    df = df.reset_index(drop=True)
    events: list[tuple[str, pd.Timestamp, float, str]] = []
    yahoo_hit: set[tuple[str, pd.Timestamp]] = set()
    g = df.groupby("symbol", sort=False)
    prev_close, prev_date = g["close"].shift(1), g["date"].shift(1)
    gap = df["open"] / prev_close
    if splits is not None and len(splits):
        # Yahoo's split date is sometimes off by days: apply the event on the NSE
        # session within [date−3, date+7] whose overnight gap best matches 1/ratio
        # (within 15%); skip it when no session shows that gap.
        sp = splits.assign(date=pd.to_datetime(splits["date"]))
        rows_by_sym = {s: idx.to_numpy() for s, idx in g.groups.items()} if hasattr(g, "groups") else {}
        for sym, d, ratio in zip(sp["ticker"], sp["date"], sp["ratio"]):
            rows = rows_by_sym.get(sym)
            if rows is None or ratio <= 0:
                continue
            k = 1.0 / ratio
            win = rows[(df.loc[rows, "date"] >= d - pd.Timedelta(days=3)).to_numpy()
                       & (df.loc[rows, "date"] <= d + pd.Timedelta(days=7)).to_numpy()]
            if not len(win):
                continue
            err = (gap.loc[win] / k - 1).abs()
            if err.notna().any() and err.min() <= 0.15:
                i = err.idxmin()
                events.append((sym, df.at[i, "date"], k, "yahoo_split"))
                yahoo_hit.add((sym, df.at[i, "date"]))
                continue
            # Yahoo says an event happened but the ratio differs (combined split + bonus):
            # take the one session in the window with an untradeable gap, at its actual ratio
            g_win = gap.loc[win]
            extreme = g_win[(g_win < RAW_LOW) | (g_win > RAW_HIGH)]
            if len(extreme) == 1:
                i = extreme.index[0]
                events.append((sym, df.at[i, "date"], float(extreme.iloc[0]), "yahoo_confirmed_raw"))
                yahoo_hit.add((sym, df.at[i, "date"]))
    cand = ((gap < GAP_LOW) | (gap > GAP_HIGH)) & ((df["date"] - prev_date).dt.days <= MAX_HALT_DAYS)
    yahoo_syms = set(splits["ticker"]) if splits is not None and len(splits) else set()
    for i in np.flatnonzero(cand.to_numpy()):
        sym, d = df.at[i, "symbol"], df.at[i, "date"]
        if any((sym, d + pd.Timedelta(days=o)) in yahoo_hit for o in range(-7, 8)):
            continue                                         # Yahoo already explains it
        gi = float(gap.iat[i])
        k = _snap(gi)
        if k is not None:
            events.append((sym, d, k, "gap_heuristic" if sym not in yahoo_syms else "gap_heuristic_yahoo_name"))
    return pd.DataFrame(events, columns=["symbol", "date", "k", "source"]).drop_duplicates(["symbol", "date"])


def adjust(bhav: pd.DataFrame, splits: pd.DataFrame | None = None) -> pd.DataFrame:
    """Long bhavcopy rows (one series per symbol-day) → adjusted long frame."""
    df = bhav.sort_values(["symbol", "date"]).reset_index(drop=True)
    ev = corporate_action_factors(df, splits)
    k = pd.Series(1.0, index=df.index)
    if len(ev):
        hit = df.reset_index().merge(ev, on=["symbol", "date"], how="inner")
        k.loc[hit["index"].to_numpy()] = hit["k"].to_numpy()
    # Π k over later rows of the same symbol = reverse cumulative product / own k
    rev = k[::-1].groupby(df["symbol"][::-1], sort=False).cumprod()[::-1]
    df["adj_factor"] = (rev / k).astype(float)
    for c in ("open", "high", "low", "close", "prev_close", "avg_price"):
        df[f"adj_{c}"] = df[c] * df["adj_factor"]
    df["adj_volume"] = df["volume"] / df["adj_factor"]
    df.attrs["corporate_actions"] = ev
    return df


def pick_equity_rows(bhav: pd.DataFrame) -> pd.DataFrame:
    """One row per symbol-day from the equity series (EQ preferred over BE/BZ)."""
    eq = bhav[bhav["series"].isin(EQUITY_SERIES)].copy()
    eq["_rank"] = eq["series"].map({s: i for i, s in enumerate(EQUITY_SERIES)})
    eq = eq.sort_values(["symbol", "date", "_rank"]).drop_duplicates(["symbol", "date"], keep="first")
    return eq.drop(columns="_rank")


def load_panel(con, start: str = "2019-10-01", end: str | None = None) -> dict[str, pd.DataFrame]:
    """Wide adjusted panel (date × symbol): open/high/low/close/volume/deliv_pct/turnover_cr/series.
    The detected corporate actions are in panel["corporate_actions"] (long frame)."""
    q = "SELECT * FROM nse_bhavcopy WHERE date >= ?::DATE" + (" AND date <= ?::DATE" if end else "")
    raw = con.execute(q, [start] + ([end] if end else [])).df()
    raw["date"] = pd.to_datetime(raw["date"])
    splits = con.execute("SELECT ticker, date, ratio FROM splits WHERE ratio > 0").df()
    splits["date"] = pd.to_datetime(splits["date"]).dt.tz_localize(None).dt.normalize()
    long = adjust(pick_equity_rows(raw), splits)
    out = {}
    for name, col in (("open", "adj_open"), ("high", "adj_high"), ("low", "adj_low"), ("close", "adj_close"),
                      ("volume", "adj_volume"), ("deliv_pct", "deliv_pct"), ("turnover_cr", "turnover_lacs"),
                      ("series", "series"), ("raw_close", "close")):
        out[name] = long.pivot(index="date", columns="symbol", values=col).sort_index()
    out["turnover_cr"] = out["turnover_cr"] / 100.0           # lakhs → crores
    out["corporate_actions"] = long.attrs["corporate_actions"]
    return out


def survivorship_report(panel: dict[str, pd.DataFrame], current_symbols: set[str]) -> dict:
    """How many symbols traded in the window but are not in today's universe."""
    traded = set(panel["close"].columns)
    last = panel["close"].ffill().iloc[-1]
    last_seen = panel["close"].apply(lambda s: s.last_valid_index())
    gone = sorted(s for s in traded if s not in current_symbols)
    stale = last_seen[last_seen < panel["close"].index[-1] - pd.Timedelta(days=30)]
    return {"symbols_traded": len(traded), "not_in_current_universe": len(gone),
            "stopped_trading_30d_plus": int(len(stale)), "examples_gone": gone[:25],
            "last_close_nonnull": int(last.notna().sum())}
