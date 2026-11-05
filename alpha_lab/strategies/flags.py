"""Point-in-time avoid flags for the S1 veto and S2 features (PLAN.md §S1/§S2).

Every frame is date × symbol over the full panel index; a value at row t uses data public
by the close of session t. Results reactions use the release timestamp: a result released
during session R's hours (or after the previous close) reacts on session R; the flag exists
only from R onward.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

MARKET_CLOSE = (15, 30)


def sma(close: pd.DataFrame, n: int, min_frac: float = 0.75) -> pd.DataFrame:
    return close.rolling(n, min_periods=int(n * min_frac)).mean()


def below_200dma(close: pd.DataFrame) -> pd.DataFrame:
    m = sma(close, 200)
    return (close < m).where(m.notna() & close.notna())


def near_52w_low(close: pd.DataFrame, pct: float = 0.10) -> pd.DataFrame:
    lo = close.rolling(252, min_periods=200).min()
    return (close <= lo * (1 + pct)).where(lo.notna() & close.notna())


def near_52w_high(close: pd.DataFrame, pct: float = 0.05) -> pd.DataFrame:
    hi = close.rolling(252, min_periods=200).max()
    return (close >= hi * (1 - pct)).where(hi.notna() & close.notna())


def vol60(close: pd.DataFrame) -> pd.DataFrame:
    return close.pct_change(fill_method=None).rolling(60, min_periods=45).std()


def rsi2(close: pd.DataFrame) -> pd.DataFrame:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=0.5, min_periods=2, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=0.5, min_periods=2, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def event_frame(events: pd.DataFrame, like: pd.DataFrame) -> pd.DataFrame:
    """1.0 at each (session, symbol) event, else 0; events outside the index are dropped."""
    a = np.zeros(like.shape, np.float32)
    if events is not None and len(events):
        e = events[["date", "symbol"]].dropna()
        r = like.index.get_indexer(pd.to_datetime(e["date"]))
        c = like.columns.get_indexer(e["symbol"])
        ok = (r >= 0) & (c >= 0)
        a[r[ok], c[ok]] = 1.0
    return pd.DataFrame(a, index=like.index, columns=like.columns)


def recent(events01: pd.DataFrame, n: int) -> pd.DataFrame:
    return events01.rolling(n, min_periods=1).max()


def split_events(panel: dict) -> pd.DataFrame:
    """(date, symbol) of split/bonus ex-dates (price factor k < 1), from the panel's detected actions."""
    ca = panel["corporate_actions"]
    ev = ca[ca["k"] < 1][["date", "symbol"]].copy()
    ev["date"] = pd.to_datetime(ev["date"])
    return ev


def results_reactions(panel: dict, releases: pd.DataFrame, strong: float = 5.0,
                      min_turnover_cr: float = 1.0) -> dict[str, pd.DataFrame]:
    """(date, symbol) of strong results reactions, dated on the REACTION session (close-to-close
    1-day return minus the equal-weight liquid-universe mean, |x| ≥ `strong` %). Same timing rule
    as scripts/results_drift_study.py: released before 15:30 of a session → that session, else the
    next one. Returns {"down": events, "up": events}."""
    c, to, series, raw = panel["close"], panel["turnover_cr"], panel["series"], panel["raw_close"]
    sessions = c.index
    univ = series.eq("EQ") & (raw >= 20) & (to.rolling(20, min_periods=10).median() >= min_turnover_cr)
    r1 = c.pct_change(fill_method=None)
    ew1 = r1.where(univ.shift(1, fill_value=False)).mean(axis=1)
    react_x = r1.sub(ew1, axis=0) * 100

    rel = releases.dropna(subset=["released_at"]).copy()
    ts = pd.to_datetime(rel["released_at"])
    day = ts.dt.normalize()
    pos = sessions.searchsorted(day.to_numpy())
    in_session = (pos < len(sessions)) & (sessions.to_numpy()[np.minimum(pos, len(sessions) - 1)] == day.to_numpy())
    after_close = (ts.dt.hour * 60 + ts.dt.minute) >= MARKET_CLOSE[0] * 60 + MARKET_CLOSE[1]
    pos = np.where(in_session & after_close.to_numpy(), pos + 1, pos)
    ok = pos < len(sessions)
    rel = rel[ok].assign(date=sessions.to_numpy()[pos[ok]])

    cols = {s: j for j, s in enumerate(c.columns)}
    X = react_x.to_numpy()
    idx = {d: i for i, d in enumerate(sessions)}
    rows_dn, rows_up = [], []
    for sym, d in zip(rel["symbol"], rel["date"]):
        j = cols.get(sym)
        i = idx.get(d)
        if j is None or i is None:
            continue
        x = X[i, j]
        if np.isfinite(x) and x <= -strong:
            rows_dn.append((d, sym))
        elif np.isfinite(x) and x >= strong:
            rows_up.append((d, sym))
    mk = lambda rows: pd.DataFrame(rows, columns=["date", "symbol"]).drop_duplicates()  # noqa: E731
    return {"down": mk(rows_dn), "up": mk(rows_up)}


def s1_veto_frames(panel: dict, releases: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """The five PLAN §S1 veto conditions as boolean daily frames (True = do not newly buy)."""
    c = panel["close"]
    reacts = results_reactions(panel, releases)
    return {
        "below_200dma": below_200dma(c).fillna(False).astype(bool),
        "near_52w_low": near_52w_low(c).fillna(False).astype(bool),
        "vol60": vol60(c),                                 # decile cut happens within the universe, per date
        "split_20d": (recent(event_frame(split_events(panel), c), 20) > 0).astype(bool),
        "bad_results_60d": (recent(event_frame(reacts["down"], c), 60) > 0).astype(bool),
        "good_results_60d": (recent(event_frame(reacts["up"], c), 60) > 0).astype(bool),   # S2 feature, not a veto
    }


def lab_eligible(sig: dict, panel: dict, s: int, universe_size: int = 300,
                 min_price: float = 20.0, min_history: int = 250) -> pd.Index:
    """Universe T with the lab's RAW-close price floor (Amendments v2 §6; the vendored
    `eligible` floors on the adjusted close, which is hindsight)."""
    from lib.momentum import is_etf
    raw = panel["raw_close"].iloc[s]
    ok = (panel["series"].iloc[s] == "EQ") & (raw >= min_price) & (sig["hist"].iloc[s] >= min_history)
    ok &= ~pd.Series([is_etf(c) for c in raw.index], index=raw.index)
    liq = sig["liq"].iloc[s][ok].dropna()
    return liq.sort_values(ascending=False).index[:universe_size]
