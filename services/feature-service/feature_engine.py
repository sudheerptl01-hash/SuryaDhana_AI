"""
SuryaDhana ML Feature Engine
==============================
Computes ALL free-tier features defined in Trading_Data_Dictionary_and_ML_Pipeline.xlsx:
  - Price/Technical  (45 features)  — from OHLCV only
  - Fundamentals     (13 features)  — from DuckDB fundamentals table (yfinance .info)
  - Macro/Regime     ( 6 features)  — NIFTY50 + INDIAVIX via yfinance symbols
  - Promoter/Inst    ( 2 features)  — insider_hold_pct, inst_hold_pct (from fundamentals)

Features are computed per-ticker from OHLCV + fundamental data stored in DuckDB.
Macro features are computed once per date and broadcast to all tickers.

Anti-look-ahead guarantee:
  - All features use only data available AT time t (close of day t)
  - Fundamentals are forward-filled from their as_of_date (not the period end date)
  - Labels are computed SEPARATELY by build_labels() in labels/label_builder.py
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# v2: Yahoo-only adjusted history, quality-gated bars, scale-free MACD, macro ffill.
FEATURE_VERSION = "v2"

# ── Helpers ────────────────────────────────────────────────────────────────────

def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(span=period, adjust=False).mean()


def _bollinger(close: pd.Series, period: int = 20, std: float = 2.0):
    sma = close.rolling(period).mean()
    sigma = close.rolling(period).std()
    upper = sma + std * sigma
    lower = sma - std * sigma
    pctb = (close - lower) / (upper - lower + 1e-9)
    width = (upper - lower) / (sma + 1e-9)
    return upper, lower, pctb, width


def _stochastic(high: pd.Series, low: pd.Series, close: pd.Series, k: int = 14, d: int = 3):
    ll = low.rolling(k).min()
    hh = high.rolling(k).max()
    k_line = 100 * (close - ll) / (hh - ll + 1e-9)
    d_line = k_line.rolling(d).mean()
    return k_line, d_line


def _obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff()).fillna(0)
    return (direction * volume).cumsum()


def _mfi(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, period: int = 14) -> pd.Series:
    tp = (high + low + close) / 3
    mf = tp * volume
    pos = mf.where(tp > tp.shift(1), 0).rolling(period).sum()
    neg = mf.where(tp < tp.shift(1), 0).rolling(period).sum()
    mfr = pos / (neg.replace(0, np.nan))
    return 100 - (100 / (1 + mfr))


def _cmf(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, period: int = 20) -> pd.Series:
    mfm = ((close - low) - (high - close)) / (high - low + 1e-9)
    mfv = mfm * volume
    return mfv.rolling(period).sum() / volume.rolling(period).sum().replace(0, np.nan)


# ── Category 1: Price / Technical ─────────────────────────────────────────────

def compute_price_technical(df: pd.DataFrame) -> pd.DataFrame:
    """
    Input:  df with columns [date, open, high, low, close, volume] sorted by date.
    Output: df with 45 new feature columns added (NaN where insufficient history).
    """
    df = df.copy().sort_values("date").reset_index(drop=True)
    c, o, h, l, v = df["close"], df["open"], df["high"], df["low"], df["volume"]

    # ── Returns ──────────────────────────────────────────────────────────────
    df["ret_1d"]  = c.pct_change(1)
    df["ret_5d"]  = c.pct_change(5)
    df["ret_20d"] = c.pct_change(20)
    df["log_ret"] = np.log(c / c.shift(1))

    # Lagged returns (for sequence models)
    for lag in [1, 2, 3, 5, 10]:
        df[f"return_lag_{lag}d"] = c.pct_change(lag)

    # ── Moving Averages ───────────────────────────────────────────────────────
    df["sma_20"]  = c.rolling(20).mean()
    df["sma_50"]  = c.rolling(50).mean()
    df["sma_200"] = c.rolling(200).mean()
    df["ema_12"]  = _ema(c, 12)
    df["ema_26"]  = _ema(c, 26)

    df["price_vs_sma20"]  = c / df["sma_20"] - 1
    df["price_vs_sma50"]  = c / df["sma_50"] - 1
    df["price_vs_sma200"] = c / df["sma_200"] - 1

    df["sma_ratio_20_50"] = df["sma_20"] / df["sma_50"] - 1
    df["uptrend_20_50"]   = (df["sma_20"] > df["sma_50"]).astype(int)
    df["uptrend_50_200"]  = (df["sma_50"] > df["sma_200"]).astype(int)

    # ── RSI ───────────────────────────────────────────────────────────────────
    df["rsi_7"]  = _rsi(c, 7)
    df["rsi_14"] = _rsi(c, 14)
    df["rsi_28"] = _rsi(c, 28)

    # ── MACD ──────────────────────────────────────────────────────────────────
    df["macd"]        = df["ema_12"] - df["ema_26"]
    df["macd_signal"] = _ema(df["macd"], 9)
    df["macd_hist"]   = df["macd"] - df["macd_signal"]
    # Price-scale-free MACD so a ₹50 and a ₹5,000 stock are comparable in one model.
    df["macd_pct"]      = df["macd"] / c
    df["macd_hist_pct"] = df["macd_hist"] / c

    # ── Bollinger Bands ───────────────────────────────────────────────────────
    bb_u, bb_l, bb_pctb, bb_w = _bollinger(c, 20, 2.0)
    df["bollinger_pctb"] = bb_pctb
    df["bb_width"]       = bb_w

    # ── ATR / Volatility ─────────────────────────────────────────────────────
    df["atr_14"]         = _atr(h, l, c, 14)
    df["atr_14_pct"]     = df["atr_14"] / c
    df["realized_vol_20d"] = df["log_ret"].rolling(20).std() * np.sqrt(252)

    # ── Volume ────────────────────────────────────────────────────────────────
    vol_mean = v.rolling(20).mean()
    vol_std  = v.rolling(20).std()
    df["volume_zscore"] = (v - vol_mean) / (vol_std + 1e-9)
    df["volume_ratio"]  = v / (vol_mean + 1e-9)
    df["obv"]           = _obv(c, v)
    df["mfi_14"]        = _mfi(h, l, c, v, 14)
    df["cmf_20"]        = _cmf(h, l, c, v, 20)

    # ── Stochastic ────────────────────────────────────────────────────────────
    df["stoch_k"], df["stoch_d"] = _stochastic(h, l, c)

    # ── Williams %R ───────────────────────────────────────────────────────────
    h14 = h.rolling(14).max()
    l14 = l.rolling(14).min()
    df["williams_r"] = -100 * (h14 - c) / (h14 - l14 + 1e-9)

    # ── Rate of Change ────────────────────────────────────────────────────────
    df["roc_5"]  = c.pct_change(5) * 100
    df["roc_10"] = c.pct_change(10) * 100
    df["roc_20"] = c.pct_change(20) * 100

    # ── Price Action ──────────────────────────────────────────────────────────
    df["gap_pct"]        = (o - c.shift(1)) / (c.shift(1) + 1e-9)
    df["high_low_ratio"] = h / (l + 1e-9)
    df["close_position"] = (c - l) / (h - l + 1e-9)
    df["is_green_candle"] = (c > o).astype(int)

    # ── Calendar ─────────────────────────────────────────────────────────────
    df["day_of_week"] = pd.to_datetime(df["date"]).dt.dayofweek
    df["month"]       = pd.to_datetime(df["date"]).dt.month

    return df


# ── Category 2: Fundamentals ───────────────────────────────────────────────────

def merge_fundamentals(df: pd.DataFrame, fund_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merge quarterly fundamental data into daily OHLCV rows.
    Forward-fills fundamentals by as_of_date (point-in-time safe).

    fund_df: [ticker, as_of_date, trailing_pe, price_to_book, ev_to_ebitda,
              revenue_growth, gross_margins, operating_margins, profit_margins,
              return_on_equity, return_on_assets, debt_to_equity, current_ratio,
              market_cap, total_revenue, enterprise_value, shares_outstanding,
              insider_hold_pct, inst_hold_pct]
    """
    if fund_df.empty:
        for col in _FUND_COLS:
            df[col] = np.nan
        df["altman_z"]   = np.nan
        df["peg_ratio"]  = np.nan
        return df

    fund = fund_df.copy()
    fund["as_of_date"] = pd.to_datetime(fund["as_of_date"])
    fund = fund.sort_values("as_of_date")

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])

    # Merge-asof: for each OHLCV date, take the latest fundamental snapshot ≤ date
    # Extra columns for Altman Z (not already in _FUND_COLS)
    _extra = [c for c in ["market_cap", "total_revenue", "enterprise_value", "shares_outstanding"]
              if c not in _FUND_COLS]
    _fund_select = ["as_of_date"] + _FUND_COLS + _extra
    # Keep only columns that exist in fund_df
    _fund_select = [c for c in _fund_select if c in fund.columns]
    merged = pd.merge_asof(
        df.sort_values("date"),
        fund[_fund_select].rename(columns={"as_of_date": "date"}),
        on="date",
        direction="backward",
    )

    # Altman Z-score approximation (from yfinance available fields)
    # Z = 1.2*X1 + 1.4*X2 + 3.3*X3 + 0.6*X4 + 1.0*X5  (original 5-factor)
    # X1 = working capital / assets ≈ current_ratio proxy
    # X2 = retained earnings / assets ≈ return_on_assets (proxy)
    # X3 = EBIT / assets ≈ operating_margins * (revenue/assets) = operating_margins * asset_turnover
    # X4 = market cap / total liabilities ≈ market_cap / (D/E * equity)
    # X5 = revenue / assets ≈ revenue / (market_cap / price_to_book)
    try:
        mc   = merged.get("market_cap", pd.Series(np.nan, index=merged.index))
        rev  = merged.get("total_revenue", pd.Series(np.nan, index=merged.index))
        de   = merged.get("debt_to_equity", pd.Series(np.nan, index=merged.index))
        roa  = merged.get("return_on_assets", pd.Series(np.nan, index=merged.index))
        om   = merged.get("operating_margins", pd.Series(np.nan, index=merged.index))

        equity = mc / (merged.get("price_to_book", pd.Series(np.nan, index=merged.index)) + 1e-9)
        total_assets = equity * (1 + de.fillna(0))
        total_liab   = total_assets - equity

        x1 = merged.get("current_ratio", pd.Series(np.nan, index=merged.index)).clip(0, 5) / 5
        x2 = roa.clip(-0.5, 0.5)
        x3 = (om * rev / (total_assets + 1e-9)).clip(-1, 1)
        x4 = (mc / (total_liab + 1e-9)).clip(0, 20)
        x5 = (rev / (total_assets + 1e-9)).clip(0, 5)

        merged["altman_z"] = 1.2*x1 + 1.4*x2 + 3.3*x3 + 0.6*x4 + 1.0*x5
    except Exception:
        merged["altman_z"] = np.nan

    # PEG = PE / (revenue_growth * 100)
    try:
        pe  = merged.get("trailing_pe", pd.Series(np.nan, index=merged.index))
        rg  = merged.get("revenue_growth", pd.Series(np.nan, index=merged.index)) * 100
        merged["peg_ratio"] = (pe / rg.replace(0, np.nan)).clip(-50, 100)
    except Exception:
        merged["peg_ratio"] = np.nan

    return merged.sort_values("date").reset_index(drop=True)


_FUND_COLS = [
    "trailing_pe", "price_to_book", "ev_to_ebitda",
    "revenue_growth", "gross_margins", "operating_margins", "profit_margins",
    "return_on_equity", "return_on_assets", "debt_to_equity", "current_ratio",
    "insider_hold_pct", "inst_hold_pct",
]


# ── Category 3: Triple-Barrier Labels ─────────────────────────────────────────

def build_triple_barrier_labels(
    df: pd.DataFrame,
    horizon: int = 5,
    profit_target_pct: float = 2.0,
    stop_loss_pct: float = 2.0,
) -> pd.DataFrame:
    """
    Implements Lopez de Prado's triple-barrier labeling.
    Returns:
      label_barrier   : +1 = profit target hit, -1 = stop loss hit, 0 = timeout
      label_direction : 1 = close[t+horizon] > close[t], else 0 (simple direction)
      label_return_pct: actual % return over horizon
    """
    df = df.copy().sort_values("date").reset_index(drop=True)
    closes = df["close"].values
    highs  = df["high"].values
    lows   = df["low"].values
    n = len(closes)

    labels_barrier   = np.full(n, np.nan)
    labels_direction = np.full(n, np.nan)
    labels_return    = np.full(n, np.nan)

    for i in range(n - horizon):
        entry  = closes[i]
        target = entry * (1 + profit_target_pct / 100)
        stop   = entry * (1 - stop_loss_pct  / 100)

        barrier = 0  # default: timeout
        for j in range(i + 1, min(i + horizon + 1, n)):
            if highs[j] >= target:
                barrier = 1
                break
            if lows[j] <= stop:
                barrier = -1
                break

        labels_barrier[i]   = barrier
        labels_direction[i] = 1 if closes[i + horizon] > entry else 0
        labels_return[i]    = (closes[i + horizon] - entry) / entry * 100

    df["label_barrier"]    = labels_barrier
    df["label_direction"]  = labels_direction
    df["label_return_pct"] = labels_return
    df["horizon_days"]     = horizon
    df["profit_target_pct"] = profit_target_pct
    df["stop_loss_pct"]    = stop_loss_pct

    return df


# ── Category 4: Macro / Regime ────────────────────────────────────────────────

def compute_macro_features(nifty_df: pd.DataFrame, vix_df: pd.DataFrame) -> pd.DataFrame:
    """
    Build market-wide macro features from NIFTY50 and INDIAVIX OHLCV data.
    Both DataFrames must have [date, close] columns.
    Returns a DataFrame keyed by date with macro feature columns.
    """
    nifty = nifty_df[["date", "close"]].copy().rename(columns={"close": "nifty_close"})
    vix   = vix_df[["date", "close"]].copy().rename(columns={"close": "india_vix"})

    macro = pd.merge(nifty, vix, on="date", how="outer").sort_values("date")
    macro["nifty_close"] = macro["nifty_close"].ffill()
    macro["india_vix"]   = macro["india_vix"].ffill()

    # NIFTY 5-day return
    macro["nifty_ret_5d"] = macro["nifty_close"].pct_change(5)

    # VIX rolling z-score (252-day window)
    vix_mean = macro["india_vix"].rolling(252, min_periods=60).mean()
    vix_std  = macro["india_vix"].rolling(252, min_periods=60).std()
    macro["vix_zscore"] = (macro["india_vix"] - vix_mean) / (vix_std + 1e-9)

    # NIFTY regime: bull/bear/range using SMA crossover + VIX threshold
    sma50  = macro["nifty_close"].rolling(50).mean()
    sma200 = macro["nifty_close"].rolling(200).mean()
    macro["nifty_regime"] = "range"
    macro.loc[
        (macro["nifty_close"] > sma50) & (sma50 > sma200),
        "nifty_regime"
    ] = "bull"
    macro.loc[
        (macro["nifty_close"] < sma50) & (sma50 < sma200),
        "nifty_regime"
    ] = "bear"

    return macro[["date", "india_vix", "vix_zscore", "nifty_ret_5d", "nifty_regime"]].copy()


def compute_market_breadth(ohlcv_all: pd.DataFrame) -> pd.DataFrame:
    """
    Compute daily advance-decline ratio from the full universe.
    ohlcv_all: [date, ticker, close] for all stocks.
    Returns: [date, market_breadth]
    """
    df = ohlcv_all[["date", "ticker", "close"]].copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["ticker", "date"])
    df["prev_close"] = df.groupby("ticker")["close"].shift(1)
    df["up"] = (df["close"] > df["prev_close"]).astype(int)
    df["dn"] = (df["close"] < df["prev_close"]).astype(int)

    breadth = df.groupby("date").agg(up=("up", "sum"), dn=("dn", "sum")).reset_index()
    breadth["market_breadth"] = breadth["up"] / (breadth["up"] + breadth["dn"] + 1e-9)
    return breadth[["date", "market_breadth"]]


# ── Master feature builder ─────────────────────────────────────────────────────

FEATURE_COLS = [
    # Price/Technical
    "ret_1d", "ret_5d", "ret_20d", "log_ret",
    "return_lag_1d", "return_lag_2d", "return_lag_3d", "return_lag_5d", "return_lag_10d",
    "sma_20", "sma_50", "sma_200", "ema_12", "ema_26",
    "price_vs_sma20", "price_vs_sma50", "price_vs_sma200",
    "sma_ratio_20_50", "uptrend_20_50", "uptrend_50_200",
    "rsi_7", "rsi_14", "rsi_28",
    "macd", "macd_signal", "macd_hist", "macd_pct", "macd_hist_pct",
    "bollinger_pctb", "bb_width",
    "atr_14", "atr_14_pct", "realized_vol_20d",
    "volume_zscore", "volume_ratio", "obv",
    "mfi_14", "cmf_20",
    "stoch_k", "stoch_d",
    "williams_r",
    "roc_5", "roc_10", "roc_20",
    "gap_pct", "high_low_ratio", "close_position", "is_green_candle",
    "day_of_week", "month",
    # Fundamentals
    "trailing_pe", "price_to_book", "ev_to_ebitda",
    "peg_ratio", "revenue_growth",
    "gross_margins", "operating_margins", "profit_margins",
    "return_on_equity", "return_on_assets",
    "debt_to_equity", "current_ratio",
    "altman_z",
    # Promoter / Institutional
    "insider_hold_pct", "inst_hold_pct",
    # Macro / Regime
    "india_vix", "vix_zscore", "nifty_ret_5d", "nifty_regime",
    "market_breadth",
]

LABEL_COLS = [
    "ticker", "date", "horizon_days",
    "label_direction", "label_return_pct", "label_barrier",
    "profit_target_pct", "stop_loss_pct", "cost_hurdle_pct",
]

MACRO_COLS = ["india_vix", "vix_zscore", "nifty_ret_5d", "nifty_regime", "market_breadth"]

# Default model inputs: scale-free, cross-sectionally comparable features only.
# Excluded on purpose:
#   - absolute price levels (sma_*, ema_*, macd*, atr_14, obv) — a ₹5,000 stock's
#     SMA is not comparable to a ₹50 stock's; the *_pct / price_vs_* forms are used.
#   - duplicates (log_ret, return_lag_1d == ret_1d, return_lag_5d == ret_5d, roc_*).
#   - fundamentals — only one snapshot exists, so they are NULL on every historical
#     date under a point-in-time join. Re-enable once dated history is collected.
DEFAULT_TRAIN_FEATURES = [
    "ret_1d", "ret_5d", "ret_20d",
    "return_lag_2d", "return_lag_3d", "return_lag_10d",
    "price_vs_sma20", "price_vs_sma50", "price_vs_sma200",
    "sma_ratio_20_50", "uptrend_20_50", "uptrend_50_200",
    "rsi_7", "rsi_14", "rsi_28",
    "macd_pct", "macd_hist_pct",
    "bollinger_pctb", "bb_width",
    "atr_14_pct", "realized_vol_20d",
    "volume_zscore", "volume_ratio", "mfi_14", "cmf_20",
    "stoch_k", "stoch_d", "williams_r",
    "gap_pct", "high_low_ratio", "close_position", "is_green_candle",
    "day_of_week", "month",
    "india_vix", "vix_zscore", "nifty_ret_5d", "nifty_regime", "market_breadth",
]

NIFTY_REGIME_CODES = {"bull": 1, "range": 0, "bear": -1}

# Label parameters. Round-trip friction floor per CLAUDE.md: never < 0.15%.
LABEL_HORIZON = 5
LABEL_COST_HURDLE_PCT = 0.15
LABEL_PROFIT_TARGET_PCT = 2.0
LABEL_STOP_LOSS_PCT = 2.0
# A label window may not span a data hole (>12 calendar days for 5 bars) or an
# overnight move beyond any NSE price band (>50%), which signals a data break.
LABEL_MAX_WINDOW_CALENDAR_DAYS = 12
LABEL_MAX_OVERNIGHT_LOG_MOVE = float(np.log(1.5))


def build_labels_v2(
    df: pd.DataFrame,
    horizon: int = LABEL_HORIZON,
    cost_hurdle_pct: float = LABEL_COST_HURDLE_PCT,
    profit_target_pct: float = LABEL_PROFIT_TARGET_PCT,
    stop_loss_pct: float = LABEL_STOP_LOSS_PCT,
) -> pd.DataFrame:
    """Forward-looking labels on total-return (dividend + split adjusted) prices.

    Input: [date, high, low, close, adjusted_close] for ONE ticker.
    Output columns (NaN where the label is not trustworthy):
      label_return_pct : 100 * (adj[t+h] / adj[t] - 1)
      label_direction  : 1 if label_return_pct > cost_hurdle_pct else 0 — "UP" means
                         the trade beat round-trip costs, not merely closed higher
      label_barrier    : +1 profit target touched first, -1 stop first, 0 neither
                         (triple barrier; highs/lows scaled to the adjusted basis)

    These use FUTURE prices by construction — never feed them back as features.
    """
    d = df.sort_values("date").reset_index(drop=True)
    dates = pd.to_datetime(d["date"])
    adj = d["adjusted_close"].astype(float)
    factor = adj / d["close"].astype(float)
    adj_high = d["high"].astype(float) * factor
    adj_low = d["low"].astype(float) * factor

    fwd = adj.shift(-horizon)
    ret_pct = (fwd / adj - 1) * 100

    valid = fwd.notna()
    valid &= (dates.shift(-horizon) - dates).dt.days <= LABEL_MAX_WINDOW_CALENDAR_DAYS
    overnight = np.log(adj / adj.shift(1)).abs()
    max_jump_ahead = pd.concat([overnight.shift(-k) for k in range(1, horizon + 1)], axis=1).max(axis=1)
    valid &= ~(max_jump_ahead > LABEL_MAX_OVERNIGHT_LOG_MOVE)

    target = adj * (1 + profit_target_pct / 100)
    stop = adj * (1 - stop_loss_pct / 100)
    barrier = pd.Series(0.0, index=d.index)
    resolved = pd.Series(False, index=d.index)
    for k in range(1, horizon + 1):
        up = (adj_high.shift(-k) >= target) & ~resolved
        dn = (adj_low.shift(-k) <= stop) & ~resolved
        # Both barriers inside ONE daily bar: intraday order is unknowable from daily
        # data (~8% of windows). Resolve pessimistically (stop first) — assuming the
        # target won inflated +1 labels for a long-only book.
        barrier[up & ~dn] = 1.0
        barrier[dn] = -1.0
        resolved |= up | dn

    out = pd.DataFrame({
        "date": d["date"],
        "horizon_days": horizon,
        "label_return_pct": ret_pct.where(valid),
        "label_direction": (ret_pct > cost_hurdle_pct).astype(float).where(valid),
        "label_barrier": barrier.where(valid),
        "profit_target_pct": profit_target_pct,
        "stop_loss_pct": stop_loss_pct,
        "cost_hurdle_pct": cost_hurdle_pct,
    })
    return out


def build_ticker_features(
    ticker: str,
    ohlcv_df: pd.DataFrame,
    fund_df: pd.DataFrame,
    macro_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Build the full ml_features row-set for a single ticker.

    Args:
        ticker:    NSE ticker symbol
        ohlcv_df:  OHLCV DataFrame [date, open, high, low, close, volume]
        fund_df:   Fundamentals for this ticker [as_of_date, ...]
        macro_df:  Market-wide macro features [date, india_vix, ...]

    Returns:
        DataFrame with columns: ticker, date, <all FEATURE_COLS>
        Rows with insufficient history (all NaN price features) are dropped.
    """
    if ohlcv_df.empty:
        return pd.DataFrame()

    df = compute_price_technical(ohlcv_df)
    df = merge_fundamentals(df, fund_df)

    # Merge macro features by date
    if macro_df is not None and not macro_df.empty:
        macro_df = macro_df.copy()
        macro_df["date"] = pd.to_datetime(macro_df["date"])
        df["date"] = pd.to_datetime(df["date"])
        df = df.merge(macro_df, on="date", how="left").sort_values("date")
        # Index calendars occasionally miss a date the stock traded; carry the last
        # KNOWN value forward (past-only, so still point-in-time).
        present = [c for c in MACRO_COLS if c in df.columns]
        df[present] = df[present].ffill()

    df["ticker"] = ticker
    df["date"] = pd.to_datetime(df["date"]).dt.date.astype(str)
    df["feature_version"] = FEATURE_VERSION

    # Select only the columns we store
    keep = ["ticker", "date"] + [c for c in FEATURE_COLS if c in df.columns] + ["feature_version"]
    df = df[keep].copy()

    # Drop rows where ALL price features are NaN (warmup rows)
    price_feat = ["rsi_14", "macd", "sma_200"]
    valid_mask = df[[c for c in price_feat if c in df.columns]].notna().any(axis=1)
    df = df[valid_mask].reset_index(drop=True)

    return df
