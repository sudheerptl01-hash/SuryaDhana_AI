"""
backtest_engine.py — Institutional-grade simulation core for the Backtest Lab.

Pure-Python / numpy / pandas. No FastAPI, no DuckDB imports here so the math is
unit-testable in isolation (see tests/test_backtest_engine.py). All I/O (DuckDB
loads, HTTP, streaming) lives in routers/analytics.py.

Design pillars enforced here:
  1. Friction realism      — every trade's return is net of a round-trip cost.
  2. Risk controls         — stop-loss, trailing-stop, time-stop trade resolution.
  3. Capital compounding   — finite capital, max concurrent positions, MTM NAV.
  4. Benchmark + factors   — equal-weight benchmark, beta/alpha (Jensen, rf=0).
  5. Bias isolation        — fundamental fields are tagged separately from
                             trailing/point-in-time technicals.

MODE is always PAPER: this module never places an order, it only replays history.
"""
from __future__ import annotations

from typing import Callable, Optional, Any
import numpy as np
import pandas as pd

# Phase 4 / §3.3 — dynamic capital allocation (risk-parity / vol-target / Kelly book).
# Defensive import so the engine still loads (and legacy equal-weight still works) even
# if the optional module is absent — sizing_mode then silently stays "equal".
try:
    import portfolio_sizing as _psize          # type: ignore
    _PSIZE_OK = True
except Exception:  # pragma: no cover - import-guard only
    _psize = None                              # type: ignore
    _PSIZE_OK = False

TRADING_DAYS = 252

# Fundamental fields come from a single current snapshot (stock_metrics) and are
# therefore NOT point-in-time. Technicals below are trailing and bias-free.
FUNDAMENTAL_FIELDS: set[str] = {"pe_ratio", "div_yld_pct", "mktcap_cr", "roce_pct"}

# Numeric filter field -> dataframe column produced by compute_indicators()
# / compute_market_relative(). Every column here is strictly trailing (no
# look-ahead): the value on day T only consumes prices/volume up to and incl. T.
FIELD_MAP: dict[str, str] = {
    "pe_ratio": "pe_ratio",
    "div_yld_pct": "div_yld_pct",
    "mktcap_cr": "mktcap_cr",
    "roce_pct": "roce_pct",
    "rsi_14": "rsi_14",
    "atr_14_pct": "atr_pct",
    "above_52w_low_pct": "above_52w_low_pct",
    "within_52w_high_pct": "within_52w_high_pct",
    "dist_ma200_pct": "dist_ma200_pct",
    # ── Advanced alpha factors (Pillar 1) ──────────────────────────────────
    "vmi_ratio": "vmi_ratio",                       # Volume Market Impact ratio
    "vol_zscore_20": "vol_zscore_20",               # VIPT volume thrust z-score
    "intraday_intention": "intraday_intention",     # 3-day aggregated close-location value
    "squeeze_ratio": "squeeze_ratio",               # BB-width / KC-width (<1 ⇒ compression)
    "sector_rel_mom_14_pct": "sector_rel_mom_14_pct",  # 14d momentum vs sector composite
    "corr_nifty_30": "corr_nifty_30",               # rolling 30d Pearson corr to market
}


def _boolcol(name: str) -> "Callable[[pd.DataFrame], pd.Series]":
    """
    Predicate that reads a *pre-computed* boolean column, degrading to all-False
    when the column is absent (e.g. compute_market_relative wasn't run). Keeps
    apply_filters crash-proof on partially-prepared frames.
    """
    def _pred(d: pd.DataFrame) -> "pd.Series":
        if name in d.columns:
            return d[name].fillna(False).astype(bool)
        return pd.Series(False, index=d.index)
    return _pred


# Boolean toggle filters -> vectorised predicate over the day's dataframe
BOOLEAN_FILTERS: dict[str, Callable[[pd.DataFrame], "pd.Series[bool]"]] = {
    "price_gt_ma50": lambda d: d["close"] > d["ma50"],
    "price_gt_ma200": lambda d: d["close"] > d["ma200"],
    "ma50_gt_ma200": lambda d: d["ma50"] > d["ma200"],
    "volume_gt_avg": lambda d: d["volume"] > d["vol20"],
    # ── Advanced alpha factors (Pillar 1) ──────────────────────────────────
    "vipt_breakout": _boolcol("vipt_breakout"),                # N-day breakout on >3σ volume
    "squeeze_on": _boolcol("squeeze_on"),                      # Bollinger inside Keltner
    "intention_pullback": _boolcol("intention_pullback"),      # high CLV during 3-day dip
    "sector_positive_regime": _boolcol("sector_positive_regime"),  # sector composite mom > 0
    "decoupled_leader": _boolcol("decoupled_leader"),          # low corr in a market pullback
}


# ── Indicator engine (trailing / point-in-time, no look-ahead) ──────────────────

def _rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
    """Wilder-style RSI on a 1-D close array; trailing only."""
    if len(prices) < 2:
        return np.full(len(prices), np.nan)
    deltas = np.diff(prices)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = pd.Series(gains).rolling(window=period, min_periods=period).mean()
    avg_loss = pd.Series(losses).rolling(window=period, min_periods=period).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return np.concatenate([[np.nan], rsi.values])


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Attach trailing technical indicators. Input columns required:
    ticker, date, close, volume, high, low. All rolling windows are strictly
    backward-looking, so there is zero look-ahead on technicals.
    """
    df = df.sort_values(["ticker", "date"]).copy()
    g = df.groupby("ticker")

    df["ma50"] = g["close"].transform(lambda x: x.rolling(50, min_periods=20).mean())
    df["ma200"] = g["close"].transform(lambda x: x.rolling(200, min_periods=50).mean())
    df["vol20"] = g["volume"].transform(lambda x: x.rolling(20, min_periods=5).mean())
    df["low52w"] = g["low"].transform(lambda x: x.rolling(252, min_periods=50).min())
    df["hi52w"] = g["high"].transform(lambda x: x.rolling(252, min_periods=50).max())
    df["rsi_14"] = g["close"].transform(lambda x: pd.Series(_rsi(x.values, 14), index=x.index))

    # ATR(14) from true range. Fully vectorised + per-ticker grouped rolling — robust
    # for a single-ticker frame (a 1-name watchlist must not crash the sim) and any
    # ticker count. prev-close is the grouped shift so true range never bleeds across
    # ticker boundaries.
    prev_close = g["close"].shift(1)
    true_range = pd.concat([
        (df["high"] - df["low"]).abs(),
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = true_range.groupby(df["ticker"]).transform(
        lambda x: x.rolling(14, min_periods=14).mean())
    df["atr"] = df["atr"].fillna(0.0)
    df["atr_pct"] = (df["atr"] / df["close"] * 100).fillna(0.0)
    df["dist_ma200_pct"] = ((df["close"] - df["ma200"]) / df["ma200"] * 100).fillna(0.0)
    df["above_52w_low_pct"] = ((df["close"] - df["low52w"]) / df["low52w"] * 100).fillna(0.0)
    df["within_52w_high_pct"] = ((df["hi52w"] - df["close"]) / df["hi52w"] * 100).fillna(0.0)

    _compute_advanced_factors(df, g)
    return df


def _compute_advanced_factors(df: pd.DataFrame, g) -> None:
    """
    Attach the Pillar-1 structural alpha factors in place. Every window below is
    strictly backward-looking. Division-by-zero / flat-bar / warm-up cases resolve
    to NaN (numeric) or False (boolean) so a degenerate row never breaks the sim.

    `g` is the (ticker)-groupby of `df` created by the caller; we also build a few
    fresh groupbys for columns added after `g` was constructed.
    """
    if df.empty:
        for c in ("dollar_vol", "adv20", "amihud_illiq", "vmi_ratio", "vol_zscore_20",
                  "intraday_intention", "squeeze_ratio"):
            df[c] = pd.Series(dtype=float)
        for c in ("vipt_breakout", "squeeze_on", "intention_pullback"):
            df[c] = pd.Series(dtype=bool)
        return

    # ── Volume Market Impact (VMI) ────────────────────────────────────────────
    # VMI = (dollarVol_T / mean_20d dollarVol) / ATR%_T. Captures an outsized print
    # relative to its own liquidity baseline, dampened by the name's volatility.
    df["dollar_vol"] = df["close"] * df["volume"]
    gdv = df.groupby("ticker")["dollar_vol"]
    adv20 = gdv.transform(lambda x: x.rolling(20, min_periods=10).mean()).to_numpy()
    df["adv20"] = adv20      # 20-day avg dollar volume — liquidity base for ADV cap + impact

    # ── Amihud (2002) illiquidity — empirical Kyle-λ proxy ─────────────────────
    # ILLIQ_t = |ret_t| / dollar_vol_t, rolled 60d. Units: price impact (return) per
    # rupee traded. Higher ⇒ a given order moves the price more → endogenous, per-name
    # market-impact coefficient (replaces a single hand-set global scalar).
    ret1d = df.groupby("ticker")["close"].pct_change().abs().to_numpy()
    dvv = df["dollar_vol"].to_numpy()
    daily_illiq = np.full(dvv.shape, np.nan)
    np.divide(ret1d, dvv, out=daily_illiq, where=dvv > 0)
    df["_daily_illiq"] = daily_illiq
    df["amihud_illiq"] = df.groupby("ticker")["_daily_illiq"].transform(
        lambda x: x.rolling(60, min_periods=20).mean())
    df.drop(columns=["_daily_illiq"], inplace=True, errors="ignore")

    dv = df["dollar_vol"].to_numpy()
    atr_pct = df["atr_pct"].to_numpy()
    rel_dv = np.full(dv.shape, np.nan)
    np.divide(dv, adv20, out=rel_dv, where=adv20 > 0)
    vmi = np.full(dv.shape, np.nan)
    np.divide(rel_dv, atr_pct, out=vmi, where=atr_pct > 0)
    df["vmi_ratio"] = vmi

    # ── Volume-Induced Price Thrust (VIPT) ────────────────────────────────────
    # Volume z-score vs the *prior* 20-day baseline (shift(1) → today excluded, so
    # the spike is measured against an established mean, never against itself).
    gvol = df.groupby("ticker")["volume"]
    vmean_prev = gvol.transform(lambda x: x.shift(1).rolling(20, min_periods=10).mean())
    vstd_prev = gvol.transform(lambda x: x.shift(1).rolling(20, min_periods=10).std())
    df["vol_zscore_20"] = np.where(vstd_prev > 0, (df["volume"] - vmean_prev) / vstd_prev, np.nan)
    # Breakout out of an N=20-day consolidation: close clears the prior 20-day high
    # on a >3σ volume thrust. Prior high uses shift(1) so the break is genuine.
    prior_high = df.groupby("ticker")["high"].transform(
        lambda x: x.shift(1).rolling(20, min_periods=10).max())
    df["vipt_breakout"] = (
        (df["close"] > prior_high) & (df["vol_zscore_20"] > 3.0)
    ).fillna(False)

    # ── Intraday Intention (3-day aggregated close-location value) ─────────────
    # CLV_t = (C-L)/(H-L) ∈ [0,1]; flat bars (H==L) are undefined → NaN. The 3-day
    # mean skips NaNs (nanmean) and only emits NaN when *all* 3 bars are flat.
    rng = (df["high"] - df["low"]).to_numpy()
    clv = np.full(rng.shape, np.nan)
    np.divide((df["close"].to_numpy() - df["low"].to_numpy()), rng, out=clv, where=rng > 0)
    df["_clv"] = clv

    def _nanmean3(x: np.ndarray) -> float:
        return float(np.nanmean(x)) if np.isfinite(x).any() else np.nan

    df["intraday_intention"] = df.groupby("ticker")["_clv"].transform(
        lambda s: s.rolling(3, min_periods=1).apply(_nanmean3, raw=True))
    close_3ago = g["close"].transform(lambda x: x.shift(3))
    # Setup: buyers defending the close (>0.8) through a 3-day price pullback.
    df["intention_pullback"] = (
        (df["intraday_intention"] > 0.8) & (df["close"] < close_3ago)
    ).fillna(False)

    # ── Volatility Compression (the Squeeze: Bollinger inside Keltner) ─────────
    ma20 = g["close"].transform(lambda x: x.rolling(20, min_periods=20).mean())
    std20 = g["close"].transform(lambda x: x.rolling(20, min_periods=20).std())
    bb_w = 4.0 * std20                 # Bollinger(20, 2σ) full width = 4σ
    kc_w = 3.0 * df["atr"]             # Keltner(20, 1.5·ATR) full width = 3·ATR
    df["squeeze_ratio"] = np.where(kc_w > 0, bb_w / kc_w, np.nan)
    bb_u, bb_l = ma20 + 2 * std20, ma20 - 2 * std20
    kc_u, kc_l = ma20 + 1.5 * df["atr"], ma20 - 1.5 * df["atr"]
    df["squeeze_on"] = ((bb_u < kc_u) & (bb_l > kc_l)).fillna(False)

    df.drop(columns=["_clv"], inplace=True, errors="ignore")


def compute_market_relative(
    df: pd.DataFrame,
    sector_of: dict[str, str],
    mom_window: int = 14,
    corr_window: int = 30,
    market_ret_by_date: Optional[dict] = None,
) -> pd.DataFrame:
    """
    Attach reference-relative factors (Sector Momentum Dispersion + Beta-Adjusted
    Market Coupling). No external index is required: the *market* is the equal-weight
    daily return of the loaded constituents and each *sector* is the equal-weight
    return of its members (sector_of: TICKER→sector). A real index can be injected
    via `market_ret_by_date` (date→daily return) to override the internal proxy.

    Bias note: the day-T market/sector composite uses only day-T constituent returns
    (a contemporaneous cross-sectional average — not look-ahead). The rolling
    correlation/momentum windows are strictly trailing.
    """
    if df is None or df.empty:
        return df
    df = df.sort_values(["ticker", "date"]).copy()
    g = df.groupby("ticker")

    df["ret_1d"] = g["close"].transform(lambda x: x.pct_change())

    if market_ret_by_date is None:
        market_ret_by_date = df.groupby("date")["ret_1d"].mean().to_dict()
    df["mkt_ret_1d"] = df["date"].map(market_ret_by_date).astype(float)

    # Market index level (for a trailing 5-day market return used by the de-coupling
    # regime flag). Built once from the daily series, then mapped back by date.
    mser = pd.Series(market_ret_by_date, dtype=float).sort_index()
    mlevel = (1.0 + mser.fillna(0.0)).cumprod()
    mret5 = (mlevel / mlevel.shift(5) - 1.0)
    df["mkt_ret5"] = df["date"].map(mret5.to_dict()).astype(float)

    # ── Sector Momentum Dispersion ────────────────────────────────────────────
    df["_mom14"] = g["close"].transform(lambda x: x.pct_change(mom_window)) * 100.0
    df["_sector"] = df["ticker"].astype(str).str.upper().map(sector_of).fillna("Unknown")
    df["_sector_mom14"] = df.groupby(["_sector", "date"])["_mom14"].transform("mean")
    df["sector_rel_mom_14_pct"] = (df["_mom14"] - df["_sector_mom14"]).astype(float)
    df["sector_positive_regime"] = (df["_sector_mom14"] > 0).fillna(False)

    # ── Beta-Adjusted Market Coupling (rolling 30d Pearson corr to the market) ──
    def _roll_corr(s: pd.DataFrame) -> pd.Series:
        return s["ret_1d"].rolling(corr_window, min_periods=corr_window).corr(s["mkt_ret_1d"])

    corr = df.groupby("ticker", group_keys=False)[["ret_1d", "mkt_ret_1d"]].apply(_roll_corr)
    df["corr_nifty_30"] = corr.reindex(df.index).astype(float)

    # De-coupled leader: correlation collapses (<0.2) while the market is pulling
    # back (5d<0) yet the name itself holds positive idiosyncratic momentum (5d>0).
    df["_ret5"] = g["close"].transform(lambda x: x.pct_change(5))
    df["decoupled_leader"] = (
        (df["corr_nifty_30"] < 0.2) & (df["mkt_ret5"] < 0) & (df["_ret5"] > 0)
    ).fillna(False)

    df.drop(columns=["_mom14", "_sector", "_sector_mom14", "_ret5"], inplace=True, errors="ignore")
    return df


# ── Non-linear regime detection (Gaussian HMM, causal forward filter) ──────────────
# A 2-state Gaussian HMM (Hamilton 1989) on benchmark daily returns. Parameters are
# fit by Baum-Welch on the full series; the emitted per-day signal is the *forward-
# filtered* posterior P(bull | data ≤ t) — no backward smoothing, so it is causal and
# look-ahead-free given the (slowly-varying) parameters. This replaces the laggy,
# whipsaw-prone SMA(200) crossover with a probabilistic, fast-reacting regime weight.

def gaussian_hmm_regime(returns, n_iter: int = 20, min_obs: int = 100):
    """Fit a 2-state Gaussian HMM and return (p_bull_filtered, params).

    `p_bull_filtered[t]` = causal P(bull state | returns₀..ₜ). The bull state is the
    higher-mean component. Returns None when the series is too short. NaN inputs are
    skipped and re-aligned to the original index (leading gap forward-filled).
    """
    r_all = np.asarray(returns, dtype=float)
    finite = np.isfinite(r_all)
    r = r_all[finite]
    T = len(r)
    if T < min_obs:
        return None
    base_sd = float(r.std()) + 1e-9
    mu = np.array([r.mean() - base_sd, r.mean() + base_sd])       # [bear, bull] init
    sd = np.array([base_sd * 1.5, base_sd * 0.8])
    A = np.array([[0.95, 0.05], [0.05, 0.95]])                    # persistent regimes
    pi = np.array([0.5, 0.5])

    def _emissions(mu, sd):
        d = r[:, None] - mu[None, :]
        return np.exp(-0.5 * (d / sd) ** 2) / (sd * np.sqrt(2 * np.pi)) + 1e-300

    def _forward(B, A, pi):
        alpha = np.zeros((T, 2)); c = np.zeros(T)
        alpha[0] = pi * B[0]; c[0] = alpha[0].sum() + 1e-300; alpha[0] /= c[0]
        for t in range(1, T):
            alpha[t] = (alpha[t - 1] @ A) * B[t]
            c[t] = alpha[t].sum() + 1e-300
            alpha[t] /= c[t]
        return alpha, c

    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        for _ in range(max(1, int(n_iter))):
            B = _emissions(mu, sd)
            alpha, c = _forward(B, A, pi)
            beta = np.zeros((T, 2)); beta[-1] = 1.0
            for t in range(T - 2, -1, -1):
                beta[t] = (A @ (B[t + 1] * beta[t + 1])) / c[t + 1]
            gamma = alpha * beta
            gamma /= gamma.sum(1, keepdims=True) + 1e-300
            xi_sum = np.zeros((2, 2))
            for t in range(T - 1):
                num = (alpha[t][:, None] * A) * (B[t + 1] * beta[t + 1])[None, :]
                xi_sum += num / (num.sum() + 1e-300)
            pi = gamma[0]
            A = xi_sum / (xi_sum.sum(1, keepdims=True) + 1e-300)
            w = gamma.sum(0)
            mu = (gamma * r[:, None]).sum(0) / (w + 1e-300)
            var = (gamma * (r[:, None] - mu[None, :]) ** 2).sum(0) / (w + 1e-300)
            sd = np.sqrt(np.maximum(var, 1e-12)) + 1e-9

        # Causal forward filter only (NO backward pass) → look-ahead-free posterior.
        B = _emissions(mu, sd)
        alpha, _ = _forward(B, A, pi)

    bull = int(np.argmax(mu))
    p_filtered = alpha[:, bull]
    out = np.full(len(r_all), np.nan)
    out[np.where(finite)[0]] = p_filtered
    # forward-fill leading NaNs (pre-first-observation) with the first valid posterior
    first = next((i for i, v in enumerate(out) if np.isfinite(v)), None)
    if first is not None:
        out[:first] = out[first]
        out = pd.Series(out).ffill().to_numpy()
    return out, {"mu": [round(float(x), 6) for x in mu], "sd": [round(float(x), 6) for x in sd],
                 "bull_state": bull, "transition": A.round(4).tolist()}


def apply_filters(day_df: pd.DataFrame, filters: list[dict]) -> pd.DataFrame:
    """Apply numeric + boolean filters (AND) to one day's candidate rows."""
    candidates = day_df
    for fc in filters:
        field, op, value = fc["field"], fc.get("op", "gt"), fc.get("value", 0.0)
        if field in FIELD_MAP:
            col = FIELD_MAP[field]
            if op == "lt":
                candidates = candidates[candidates[col] < value]
            elif op == "gt":
                candidates = candidates[candidates[col] > value]
            elif op == "lte":
                candidates = candidates[candidates[col] <= value]
            elif op == "gte":
                candidates = candidates[candidates[col] >= value]
        elif field in BOOLEAN_FILTERS:
            candidates = candidates[BOOLEAN_FILTERS[field](candidates)]
    return candidates


def fundamental_filters_active(filters: list[dict]) -> bool:
    return any(fc.get("field") in FUNDAMENTAL_FIELDS for fc in filters)


# ── Trade-level risk engine ─────────────────────────────────────────────────────

# Default ATR-stop multiplier (k) when ATR-scaled stops are active. The universe
# median ATR% ≈ 3.24%, so k=2.0 ⇒ a ~6.5% stop on the median name — wide enough not
# to be knocked out by ordinary noise in a storm, tight enough to cap a tail loss.
DEFAULT_ATR_STOP_MULT: float = 2.0
# APPROVED REVIEW CHANGE (audit §3.4): the per-trade stop is now a TRUE volatility-
# adaptive ATR stop (k·ATR%) with NO hard upper cap, so a high-ATR storm name gets a
# WIDER stop (≈6.5% on the median name) instead of being knocked out on noise by a
# rigid -2% clamp. The old -2% behaviour was a *cap*; it is now an optional *floor*
# (minimum stop width) that is OFF by default. A caller may set `stop_floor_pct` to
# guarantee the stop is never *tighter* than that width on ultra-calm names. The hard
# -2% DAILY realised-loss halt (C7b) and the -20% max-drawdown e-stop are unchanged.
DEFAULT_STOP_FLOOR_PCT: Optional[float] = None   # no minimum stop width by default
# Back-compat alias for the legacy constant name (referenced by older tests/imports).
LOCKED_STOP_FLOOR_PCT: Optional[float] = DEFAULT_STOP_FLOOR_PCT

# C6 — block-level participation gate for routing an entry through the live execution
# scheduler. Below this fraction of ADV the single instantaneous √-law hit and the
# multi-session schedule are numerically indistinguishable (a tiny order clears in one
# slice), so the scheduler is skipped and the legacy term applies exactly — keeping
# small orders bit-for-bit identical to legacy (zero regression). At/above it the block
# is worked across sessions for true backtest↔live parity.
SCHEDULED_IMPACT_TRIGGER: float = 0.01   # alloc/ADV ≥ 1% ⇒ route through the scheduler
_SCHEDULED_IMPACT_TRIGGER = SCHEDULED_IMPACT_TRIGGER


def effective_stop_pct(
    atr_pct: Optional[float],
    atr_stop_mult: Optional[float],
    fixed_stop_pct: Optional[float],
    stop_floor_pct: Optional[float] = DEFAULT_STOP_FLOOR_PCT,
    *,
    floor_pct: Optional[float] = "__unset__",  # type: ignore[assignment]
) -> Optional[float]:
    """C7a (revised, audit §3.4) — resolve a single trade's stop distance (% below
    entry) as a TRUE volatility-adaptive ATR stop. Independent, side-effect-free unit.

    APPROVED REVIEW CHANGE: the stop is now ``k · ATR%`` with **no hard upper cap**, so
    a high-ATR storm name gets a *wider* stop (e.g. median ATR 3.24% × k=2 ≈ 6.48%) and
    volatility no longer stops you out on ordinary noise. The previous -2% behaviour was
    a *cap*; it is now an optional *floor* on the stop **width** (``stop_floor_pct``,
    default None ⇒ no floor). Policy:

      • If `atr_stop_mult` (k) is set AND a positive signal-day `atr_pct` is available,
        the volatility-adjusted distance is ``k · ATR%``. If `stop_floor_pct` is set
        (>0), the stop is widened to at least that width — i.e. ``max(k·ATR%, floor)`` —
        so an ultra-calm name (ATR<1%) is never stopped on an unrealistically tight
        distance. With no floor (the default) the stop is exactly ``k·ATR%``, allowed to
        widen arbitrarily in a storm.

      • If ATR data is missing/degenerate (None, ≤0, NaN), fall back to the legacy
        `fixed_stop_pct` exactly — zero behavioural change for names without ATR.

      • If neither an ATR stop nor a fixed stop applies, return None (no stop, time-stop
        only) — identical to the pre-C7a default when the caller passes nothing.

    SCOPE: this governs ONLY the per-trade stop-loss. The -2% daily realised-loss halt
    (`DailyLossGovernor`, C7b) and the -20% max-drawdown e-stop remain HARD and are not
    affected by this function.

    Returns the stop distance as a positive percentage (e.g. 6.48 ⇒ stop 6.48% below
    entry), or None for "no per-trade stop". Never raises on degenerate input.
    """
    # Back-compat: the pre-revision signature used `floor_pct` (a *cap*). Accept it as a
    # deprecated alias mapping to `stop_floor_pct` so older call sites/imports do not
    # break; the *semantics* below are the new floor-not-cap behaviour regardless.
    if floor_pct != "__unset__":
        stop_floor_pct = floor_pct  # type: ignore[assignment]
    try:
        floor = abs(float(stop_floor_pct)) if stop_floor_pct is not None else None
    except (TypeError, ValueError):
        floor = None
    # ATR-scaled branch (only when k>0 and a usable ATR% is present).
    if atr_stop_mult is not None:
        try:
            k = float(atr_stop_mult)
        except (TypeError, ValueError):
            k = 0.0
        try:
            a = float(atr_pct) if atr_pct is not None else float("nan")
        except (TypeError, ValueError):
            a = float("nan")
        if k > 0 and np.isfinite(a) and a > 0:
            atr_stop = k * a
            if floor is not None and floor > 0:
                # Floor on protection: never *tighter* (smaller %) than the configured
                # minimum width — but free to WIDEN past it in a high-ATR storm.
                return float(max(atr_stop, floor))
            return float(atr_stop)
    # Fallback: legacy fixed-% stop (or None for no stop).
    if fixed_stop_pct is not None:
        try:
            f = float(fixed_stop_pct)
            return f if f > 0 else None
        except (TypeError, ValueError):
            return None
    return None


def resolve_trade_exit(
    highs: np.ndarray,
    lows: np.ndarray,
    closes: np.ndarray,
    entry_price: float,
    forward_days: int,
    friction_bps: float = 15.0,
    stop_loss_pct: Optional[float] = None,
    trailing_stop_pct: Optional[float] = None,
    win_threshold: float = 0.0,
    opens: Optional[np.ndarray] = None,
) -> dict:
    """
    Resolve a single trade's exit under real trading physics.

    Walks the forward price path (day 1..N). Priority each day:
      1. Stop-loss   — if the day's LOW pierces entry*(1 - sl%), fill at the stop.
      2. Trailing    — else if LOW pierces peak*(1 - trail%), fill at the trail level.
      3. Time-stop   — if neither triggers by day N, exit at the Nth close.

    Gap realism: if `opens` is supplied and the bar OPENS already below the stop
    level (overnight gap-down), the fill is the open, not the stop — you cannot
    fill better than where the market reopened.

    `peak` trails the highest HIGH seen on *prior* days (conservative: a high that
    occurs the same day as the low cannot be assumed to precede it). Returns are
    net of `friction_bps` round-trip (basis points, e.g. 15 = 0.15%).
    """
    n = min(forward_days, len(closes))
    exit_price = float(closes[n - 1]) if n > 0 else float(entry_price)
    holding = n
    reason = "time_stop"
    peak = float(entry_price)

    for i in range(n):
        hi, lo = float(highs[i]), float(lows[i])
        op = float(opens[i]) if (opens is not None and i < len(opens)) else None
        sl_price = entry_price * (1 - stop_loss_pct / 100.0) if stop_loss_pct else None
        trail_price = peak * (1 - trailing_stop_pct / 100.0) if trailing_stop_pct else None

        if sl_price is not None and lo <= sl_price:
            fill = sl_price if (op is None or op >= sl_price) else op   # gap-down → fill at open
            exit_price, holding, reason = fill, i + 1, "stop_loss"
            break
        if trail_price is not None and lo <= trail_price:
            fill = trail_price if (op is None or op >= trail_price) else op
            exit_price, holding, reason = fill, i + 1, "trailing_stop"
            break
        peak = max(peak, hi)  # trail off prior peaks only

    gross_return_pct = (exit_price - entry_price) / entry_price * 100.0
    net_return_pct = gross_return_pct - friction_bps / 100.0  # round-trip friction
    return {
        "exit_price": round(float(exit_price), 4),
        "gross_return_pct": round(gross_return_pct, 4),
        "net_return_pct": round(net_return_pct, 4),
        "holding_days": int(holding),
        "exit_reason": reason,
        "is_win": bool(net_return_pct > win_threshold),
    }


# ── Portfolio-level tail-risk governor ──────────────────────────────────────────

# Daily realised-loss limit (% of the day-open NAV) that halts NEW entries for the
# rest of the session. Mirrors the LIVE kill-switch (live_execution.py
# DAILY_LOSS_LIMIT_PCT=0.02 → 2%) so backtest and live enforce the SAME daily tail
# limit. The peak-to-trough max_drawdown_halt is a separate, slower control.
DEFAULT_DAILY_LOSS_HALT_PCT: float = 2.0


class DailyLossGovernor:
    """C7b — per-bar realised-daily-loss VaR governor for `simulate_portfolio`.

    Independent, single-responsibility state machine. One backtest bar = one trading
    day, so "realised daily loss" is the move from the NAV at the *open* of today's bar
    (i.e. yesterday's close NAV) to the current intraday MTM NAV. When that loss breaches
    the configured limit ℓ, the governor *halts new entries* for the remainder of the
    bar — the same lever the existing drawdown-halt and regime-gate use (open positions
    are never force-liquidated mid-bar; the sim has no intra-bar exit mechanism). This
    mirrors the live 2% kill-switch so sim and live share an identical daily tail limit,
    closing the asymmetry where the backtest could ride a one-day −5% gap that live would
    have halted.

    Math (audit §3.4):
        halt new entries if  (NAV_t / NAV_open_of_day − 1)·100  ≤  −ℓ,   ℓ = 2%.

    Disabled (limit None ⇒ inert) the governor is a no-op: it never halts, so passing
    None reproduces the legacy behaviour byte-for-byte. Never raises on degenerate NAV.
    """

    __slots__ = ("limit_pct", "_day_open_nav", "days_halted")

    def __init__(self, limit_pct: Optional[float]) -> None:
        # Store as a positive magnitude; None ⇒ governor inert.
        self.limit_pct: Optional[float] = (abs(float(limit_pct))
                                           if limit_pct is not None else None)
        self._day_open_nav: Optional[float] = None
        self.days_halted: int = 0

    def open_day(self, nav: float) -> None:
        """Capture the day-open NAV (called at the top of each bar, pre-entry)."""
        try:
            v = float(nav)
            self._day_open_nav = v if np.isfinite(v) and v > 0 else None
        except (TypeError, ValueError):
            self._day_open_nav = None

    def is_halted(self, nav: float) -> bool:
        """True if today's realised loss breaches the limit ⇒ suppress new entries."""
        if self.limit_pct is None or self._day_open_nav is None:
            return False
        try:
            cur = float(nav)
        except (TypeError, ValueError):
            return False
        if not np.isfinite(cur) or self._day_open_nav <= 0:
            return False
        day_loss_pct = (cur / self._day_open_nav - 1.0) * 100.0
        halted = day_loss_pct <= -self.limit_pct
        if halted:
            self.days_halted += 1
        return halted


# ── Capital-managed compounding portfolio simulation ────────────────────────────

def simulate_portfolio(
    all_dates: list,
    from_idx: int,
    to_idx: int,
    entries_by_idx: dict[int, list[dict]],
    price_at: Callable[[int, str], Optional[float]],
    starting_capital: float = 10_000_000.0,
    max_positions: int = 5,
    max_drawdown_halt_pct: Optional[float] = None,
    vol_target_pct: Optional[float] = None,
    max_position_pct: Optional[float] = None,
    max_sector_pct: Optional[float] = None,
    regime_ok_by_date: Optional[dict] = None,
    regime_scale_by_date: Optional[dict] = None,
    impact_coef: Optional[float] = None,
    max_participation_pct: Optional[float] = None,
    amihud_coef: Optional[float] = None,
    kelly_fraction: Optional[float] = None,
    delist_by_ticker: Optional[dict] = None,
    impact_coef_map: Optional[dict] = None,
    daily_loss_halt_pct: Optional[float] = None,
    scheduled_impact_fn: Optional[Callable[..., Any]] = None,
    slippage_sink: Optional[Callable[[dict], None]] = None,
    sizing_mode: str = "equal",
    liquidity_phi: float = 0.10,
) -> tuple[list[dict], list[dict]]:
    """
    Event-driven, finite-capital portfolio simulation with daily mark-to-market.

    entries_by_idx[idx] = ordered list of candidate dicts, each:
        {ticker, entry_price, exit_idx, net_return_pct, gross_return_pct,
         exit_price, exit_reason, entry_date, exit_date, [atr_pct], [sector]}

    Sizing (all opt-in; defaults reproduce plain equal-weight exactly):
      • base allocation = min(cash, NAV / max_positions).
      • `vol_target_pct` — volatility-target sizing: scale the base by
        (vol_target_pct / σ_i), σ_i = the name's signal-day ATR%, bounded to
        [0.25×, 2.5×]. Calm names get more capital, jumpy names less — equalising
        risk contribution and de-grossing the book's tail (the −55% MaxDD fix).
      • `max_position_pct` — hard cap per position as a % of NAV.
      • `kelly_fraction` — fractional-Kelly sizing (e.g. 0.5 = half-Kelly). The Kelly
        fraction f* = W − (1−W)/R is estimated from a rolling window of the strategy's
        OWN closed trades (W = win rate, R = avg win / |avg loss|) — strictly
        point-in-time. Per-bet allocation is capped at min(equal-weight, NAV·κ·f*), so
        Kelly only *de-risks* a weak edge below equal-weight (never over-concentrates a
        multi-position book). Falls back to equal-weight until enough trades have closed.
      • `sizing_mode` (Phase 4, audit §3.3) — book-level capital allocation:
          - "equal" (default) — every concurrent slot gets NAV/max_positions, exactly
            as before (bit-for-bit legacy; the per-candidate `vol_target_pct`/`kelly_cap`
            scaling below still applies on top, unchanged).
          - "risk_parity" — the bar's candidate slate is weighted wᵢ ∝ 1/σᵢ (inverse-vol,
            σᵢ = signal-day ATR%), normalised, liquidity-capped (φ·ADVᵢ/NAV) and
            ≤max_position cap; calm names get more capital, jumpy names less, equalising
            each name's risk contribution and de-grossing the tail.
          - "vol_target" — the risk-parity weights are then scaled so the book targets
            `vol_target_pct` realised σ (independent-name proxy σ_port=√Σwᵢ²σᵢ²; scale
            clamped ≤1 so it only ever de-grosses).
        When `kelly_fraction` is set, the resulting slate weights are additionally scaled
        by the fractional-Kelly *book gross* κ·f* (sizes the whole book, capped at fully
        invested) — §3.3's "Kelly sizes the book, not just a bet". The weight computation
        is delegated to the pure `portfolio_sizing` module and wrapped so ANY failure or
        a missing module degrades to legacy equal-weight (zero regression). `liquidity_phi`
        is the per-name ADV fraction used for the liquidity cap (default 0.10).

    Risk gates (opt-in):
      • `max_sector_pct` — reject an entry that would push its sector's exposure
        above this % of NAV (uses cand["sector"]).
      • `regime_ok_by_date` — {date_str → bool}; entries are blocked on days the
        regime flag is False (risk-off). Open positions are never force-closed by
        the regime gate — only *new* entries are suppressed.
      • `regime_scale_by_date` — {date_str → float∈[0,1]}; a *soft* exposure throttle
        (e.g. an HMM P(bull) posterior) that scales each new position's allocation
        instead of a hard on/off — the book de-grosses smoothly as the regime weakens.
      • `daily_loss_halt_pct` — C7b daily realised-loss VaR governor (% of the
        day-open NAV). When today's intraday MTM loss breaches this limit, NEW entries
        are suppressed for the rest of the bar (open positions untouched, like the DD
        halt). Mirrors the LIVE 2% kill-switch so sim and live share an identical daily
        tail limit. None ⇒ inert (legacy behaviour exactly).

    Liquidity realism (opt-in; needs cand["adv"] = 20-day avg dollar volume):
      • `max_participation_pct` — hard ADV cap: an entry cannot deploy more than
        this % of the name's average daily dollar volume (you can't fill ₹10M into
        a microcap). Allocation is clipped down to the cap.
      • `impact_coef` — vol-scaled square-root *temporary* impact. Round-trip cost in %
        ≈ 2 · impact_coef · ATR%ᵢ · √(alloc / ADVᵢ), deducted from the realised
        return so a strategy's edge degrades with size (the flat-friction lie at
        scale). impact_coef≈1 is a reasonable Almgren-style default.
      • `amihud_coef` — endogenous *permanent* (Kyle-λ / Amihud) impact, linear in
        order size: perm% ≈ amihud_coef · ILLIQᵢ · alloc · 100, where ILLIQᵢ is the
        per-name Amihud illiquidity (cand["amihud"]). Captures that an order in an
        illiquid name permanently moves the price against you (the temporary √-law
        leg alone understates impact for thin names). Added to the round-trip cost.
      • `scheduled_impact_fn` — C6 backtest↔live parity. A callable
        `(alloc, adv, atr_pct, arrival_price, y_i) → ScheduledFill` (typically
        `scheduled_impact.schedule_block_impact`) that works the parent block through the
        LIVE child-order scheduler (TWAP/VWAP/POV, partial fills, U-shaped intraday
        liquidity) over multiple sessions, replacing the single instantaneous √-law
        temporary leg with the realised VWAP-style execution cost. Only consulted for an
        at-scale block (participation alloc/ADV ≥ the scheduler trigger); on ANY failure
        or a degenerate result the engine transparently falls back to the inline
        single-hit √-law term (zero regression). None ⇒ legacy single-hit exactly. The
        PERMANENT Amihud/Kyle-λ leg is unaffected (it is session-independent).
      • `slippage_sink` — optional callable invoked once per scheduled fill with a dict
        of realised-execution telemetry (arrival price, realised VWAP, participation,
        slices, IS bps, per-name Y_i). Used to persist the `slippage` table for nightly
        Y_i recalibration. Wrapped in try/except by the caller; a write failure never
        affects the simulation.

    Survivorship realism (opt-in; G2):
      • `delist_by_ticker` — {ticker → (delist_gidx, delist_return_pct)}. A held name
        that reaches its delisting bar is force-closed THAT bar at the terminal
        delisting return (e.g. −100% for a wipe-out, or a buy-out premium), instead of
        silently riding to its natural exit. Models that only ever see survivors
        systematically overstate returns; a real delisting/acquisition path lets a dead
        name actually hurt (or reward) the book. Positions whose natural exit lands on
        or before the delist bar are unaffected (already realised).

    Positions are capped at `max_positions` concurrent. Exits realise proceeds
    back to cash; the equity curve is the true compounded NAV (cash + MTM longs).

    Returns (equity_curve, trades). The calendar auto-extends past `to_idx` to let
    late entries fully wind down, so every entered trade is realised.
    """
    cash = float(starting_capital)
    peak_nav = float(starting_capital)
    open_pos: dict[str, dict] = {}
    trades: list[dict] = []
    equity: list[dict] = []
    recent_rets: list[float] = []      # rolling closed-trade returns for fractional Kelly
    _KELLY_LOOKBACK, _KELLY_MIN = 50, 20
    # C7b — daily realised-loss VaR governor (inert when daily_loss_halt_pct is None).
    daily_governor = DailyLossGovernor(daily_loss_halt_pct)
    prev_close_nav = float(starting_capital)   # NAV at the open of the current bar

    last_exit_idx = to_idx
    for idx in range(from_idx, to_idx + 1):
        for cand in entries_by_idx.get(idx, []):
            last_exit_idx = max(last_exit_idx, cand["exit_idx"])
    end_idx = min(len(all_dates) - 1, last_exit_idx)

    def _mtm_nav() -> float:
        total = cash
        for p in open_pos.values():
            px = price_at(p["mtm_idx_ticker_idx"], p["ticker"])
            total += p["shares"] * (px if px is not None else p["entry_price"])
        return total

    for idx in range(from_idx, end_idx + 1):
        date = all_dates[idx]

        # 1) Exits first (free up capital before sizing new entries)
        for pid in [k for k, p in open_pos.items() if p["exit_idx"] == idx]:
            p = open_pos.pop(pid)
            # Realised return net of round-trip market impact (0 unless impact modelled).
            impact_pct = p.get("impact_pct", 0.0)
            eff_return_pct = p["net_return_pct"] - impact_pct
            proceeds = p["alloc"] * (1 + eff_return_pct / 100.0)
            cash += proceeds
            trades.append({
                "entry_date": p["entry_date"],
                "exit_date": p["exit_date"],
                "ticker": p["ticker"],
                "entry_price": round(p["entry_price"], 2),
                "exit_price": round(p["exit_price"], 2),
                "gross_return_pct": round(p["gross_return_pct"], 2),
                "return_pct": round(eff_return_pct, 2),
                "holding_days": p["holding_days"],
                "exit_reason": p["exit_reason"],
                "capital_allocated": round(p["alloc"], 2),
                "impact_pct": round(impact_pct, 4),
                "pnl": round(proceeds - p["alloc"], 2),
                "is_win": bool(eff_return_pct > p["win_threshold"]),
                "sector": p.get("sector", "Unknown"),
            })
            recent_rets.append(eff_return_pct)   # feed the rolling Kelly estimator

        # 1b) Delisting sweep (G2): any name still open on its delist bar is force-closed
        # at the terminal delisting return — survivorship is not rewarded. Re-reads
        # open_pos so a name already exited above is never double-counted.
        if delist_by_ticker:
            for pid in [k for k, p in open_pos.items()
                        if (dl := delist_by_ticker.get(p["ticker"])) is not None and dl[0] == idx]:
                p = open_pos.pop(pid)
                dret = float(delist_by_ticker[p["ticker"]][1])
                proceeds = p["alloc"] * (1 + dret / 100.0)
                cash += proceeds
                trades.append({
                    "entry_date": p["entry_date"],
                    "exit_date": str(all_dates[idx])[:10],
                    "ticker": p["ticker"],
                    "entry_price": round(p["entry_price"], 2),
                    "exit_price": round(p["entry_price"] * (1 + dret / 100.0), 2),
                    "gross_return_pct": round(dret, 2),
                    "return_pct": round(dret, 2),
                    "holding_days": p["holding_days"],
                    "exit_reason": "delisted",
                    "capital_allocated": round(p["alloc"], 2),
                    "impact_pct": 0.0,
                    "pnl": round(proceeds - p["alloc"], 2),
                    "is_win": bool(dret > p["win_threshold"]),
                    "sector": p.get("sector", "Unknown"),
                })
                recent_rets.append(dret)

        # update MTM index pointer for open positions to today
        for p in open_pos.values():
            p["mtm_idx_ticker_idx"] = idx

        # 2) Risk gate + entries (only within the requested [from, to] window).
        # Mark-to-market NAV drives both position sizing and the drawdown halt.
        nav = cash
        for p in open_pos.values():
            px = price_at(idx, p["ticker"])
            nav += p["shares"] * (px if px is not None else p["entry_price"])
        peak_nav = max(peak_nav, nav)
        dd_halt = (
            max_drawdown_halt_pct is not None and peak_nav > 0
            and (nav / peak_nav - 1) * 100.0 <= -abs(max_drawdown_halt_pct)
        )
        # C7b — daily realised-loss VaR governor: halt NEW entries for the rest of the
        # bar once today's MTM loss (vs the day-open NAV) breaches the limit. Mirrors
        # the live 2% kill-switch. Inert (always False) when the limit is None.
        daily_governor.open_day(prev_close_nav)
        daily_loss_halt = daily_governor.is_halted(nav)
        # Regime gate: block *new* entries on risk-off days (open positions untouched).
        date_str = str(all_dates[idx])[:10]
        regime_ok = True if regime_ok_by_date is None else bool(regime_ok_by_date.get(date_str, True))
        # Soft regime throttle: scale new-position size by P(bull) ∈ [0,1] (HMM gate).
        regime_scale = (min(max(float(regime_scale_by_date.get(date_str, 1.0)), 0.0), 1.0)
                        if regime_scale_by_date is not None else 1.0)
        # Rolling fractional-Kelly stats (point-in-time: closed trades only). `kelly_cap`
        # is the legacy per-bet NAV-fraction cap (κ·f*); `kelly_gross` is the Phase-4
        # book-level multiplier (§3.3 — Kelly sizes the *book*, not just a bet) consumed
        # only by the risk-parity / vol-target slate weights below.
        kelly_cap = None
        kelly_gross = 1.0
        if kelly_fraction is not None and len(recent_rets) >= _KELLY_MIN:
            arr = np.asarray(recent_rets[-_KELLY_LOOKBACK:], dtype=float)
            wins, losses = arr[arr > 0], arr[arr < 0]
            if len(wins) and len(losses):
                w_rate = len(wins) / len(arr)
                r_ratio = float(wins.mean()) / abs(float(losses.mean()))
                f_star = w_rate - (1.0 - w_rate) / r_ratio if r_ratio > 1e-9 else 0.0
                kelly_cap = max(0.0, float(kelly_fraction) * f_star)   # NAV fraction per bet
                if _PSIZE_OK and _psize is not None:
                    kelly_gross = _psize.kelly_book_gross(
                        win_rate=w_rate, payoff_ratio=r_ratio, kappa=float(kelly_fraction)
                    )
        if (from_idx <= idx <= to_idx and not dd_halt and not daily_loss_halt
                and regime_ok and len(open_pos) < max_positions):
            held = {p["ticker"] for p in open_pos.values()}
            # Current per-sector $ exposure (MTM) — only needed when the sector cap is on.
            sector_exposure: dict[str, float] = {}
            if max_sector_pct is not None:
                for p in open_pos.values():
                    px = price_at(idx, p["ticker"]) or p["entry_price"]
                    sct = p.get("sector", "Unknown")
                    sector_exposure[sct] = sector_exposure.get(sct, 0.0) + p["shares"] * px
            # Phase 4 / §3.3 — book-level slate weights (risk-parity / vol-target). When
            # `sizing_mode != "equal"` the bar's candidate slate is weighted by 1/σ (and
            # optionally vol-targeted + Kelly-gross-scaled), replacing the flat
            # NAV/max_positions base. Computed ONCE per bar over the concurrent slate; the
            # legacy per-bet vol-target/Kelly scaling is then bypassed (the slate weight
            # already embeds them) to avoid double-counting. ANY failure or a missing
            # module degrades to legacy equal-weight (zero regression).
            _slate_w: Optional[dict] = None
            if sizing_mode != "equal" and _PSIZE_OK and _psize is not None:
                _slate = entries_by_idx.get(idx, [])
                if _slate:
                    _w = _psize.safe_compute_slate_weights(
                        [c.get("atr_pct") for c in _slate],
                        sizing_mode=sizing_mode,
                        max_positions=max_positions,
                        nav=float(nav),
                        advs=[c.get("adv") for c in _slate],
                        vol_target_pct=vol_target_pct,
                        liquidity_phi=liquidity_phi,
                        max_position_weight=(max_position_pct / 100.0
                                             if max_position_pct is not None else 0.15),
                        kelly_gross=kelly_gross,
                    )
                    if _w is not None and len(_w) == len(_slate):
                        # Key by id() of the candidate dict so order/duplicate names are safe.
                        _slate_w = {id(c): float(_w[i]) for i, c in enumerate(_slate)}
            for cand in entries_by_idx.get(idx, []):
                if len(open_pos) >= max_positions or cash <= 1.0:
                    break
                # No double-holding the same name (also makes the open_pos key safe).
                if cand["ticker"] in held:
                    continue
                _use_slate = _slate_w is not None and id(cand) in _slate_w
                if _use_slate:
                    # Slate weight already embeds inverse-vol, vol-target, liquidity cap
                    # and Kelly book-gross; only the soft regime throttle is applied on top.
                    base = nav * _slate_w[id(cand)] * regime_scale
                else:
                    base = nav / max_positions * regime_scale
                    # Volatility-target sizing: scale inversely with the name's ATR%.
                    atr_pct = cand.get("atr_pct")
                    if vol_target_pct is not None and atr_pct and atr_pct > 0:
                        base *= min(max(vol_target_pct / atr_pct, 0.25), 2.5)
                # Hard per-position cap as a % of NAV (always enforced, both paths).
                if max_position_pct is not None:
                    base = min(base, nav * max_position_pct / 100.0)
                # Fractional-Kelly per-bet cap (legacy equal-weight path only — the slate
                # weight already applied the Kelly book gross).
                if kelly_cap is not None and not _use_slate:
                    base = min(base, nav * kelly_cap)
                alloc = min(cash, base)
                # ADV participation cap: clip the fill to a slice of avg daily $ volume.
                adv = cand.get("adv")
                if max_participation_pct is not None and adv and adv > 0:
                    alloc = min(alloc, adv * max_participation_pct / 100.0)
                if alloc < 1.0 or cand["entry_price"] <= 0:
                    continue
                # Sector exposure cap: skip an entry that would breach max_sector_pct.
                if max_sector_pct is not None and nav > 0:
                    sct = cand.get("sector", "Unknown")
                    if (sector_exposure.get(sct, 0.0) + alloc) / nav * 100.0 > max_sector_pct:
                        continue
                    sector_exposure[sct] = sector_exposure.get(sct, 0.0) + alloc
                # Market impact charged to the trade: vol-scaled √-law TEMPORARY leg
                # (round-trip) + endogenous Amihud/Kyle-λ PERMANENT leg (linear in size).
                impact_pct = 0.0
                # C2 — per-name temporary-leg coefficient Y_i: an endogenous map calibrated
                # from each name's Amihud illiquidity (microcaps cost more) overrides the flat
                # scalar when present; falls back to `impact_coef` so legacy callers are exact.
                _temp_coef = impact_coef
                if impact_coef_map is not None:
                    _temp_coef = impact_coef_map.get(cand["ticker"], impact_coef)
                atrp = cand.get("atr_pct") or 0.0
                if _temp_coef is not None and adv and adv > 0:
                    # C6 — backtest↔live parity. Default temporary leg is the single
                    # instantaneous √-law round-trip hit. When a scheduler is supplied AND
                    # the block is at-scale, replace it with the realised multi-session
                    # scheduled cost (worked across thinning intraday liquidity), so the
                    # backtest charges what the live child-order scheduler would. ANY failure
                    # or degenerate result transparently falls back to the single hit below
                    # (zero regression — mirrors the membership_pit=False degradation).
                    _single_hit = 2.0 * float(_temp_coef) * float(atrp) * (alloc / adv) ** 0.5
                    _temp_leg = _single_hit
                    if scheduled_impact_fn is not None and (alloc / adv) >= _SCHEDULED_IMPACT_TRIGGER:
                        try:
                            _fill = scheduled_impact_fn(
                                alloc=float(alloc), adv=float(adv), atr_pct=float(atrp),
                                arrival_price=float(cand["entry_price"]),
                                y_i=float(_temp_coef),
                            )
                            if _fill is not None and getattr(_fill, "scheduled", False) \
                                    and getattr(_fill, "fill_ratio", 0.0) > 0.0:
                                # Scheduler returns a ONE-WAY entry cost; the engine charges a
                                # round trip, so double it to keep the cost basis identical to
                                # the legacy single-hit (which is the round-trip 2·Y·…).
                                _temp_leg = 2.0 * float(_fill.impact_pct)
                                if slippage_sink is not None:
                                    try:
                                        slippage_sink({
                                            "ticker": cand["ticker"],
                                            "entry_date": cand.get("entry_date"),
                                            "arrival_price": float(_fill.arrival_price),
                                            "realised_vwap": float(_fill.realised_vwap),
                                            "alloc": float(alloc),
                                            "adv": float(adv),
                                            "participation": float(_fill.participation),
                                            "n_slices": int(_fill.n_slices),
                                            "n_sessions": int(_fill.n_sessions),
                                            "fill_ratio": float(_fill.fill_ratio),
                                            "is_bps": float(_fill.is_bps),
                                            "y_i": float(_fill.y_i),
                                            "unfilled_notional": float(_fill.unfilled_notional),
                                            "atr_pct": float(atrp),
                                        })
                                    except Exception:
                                        pass   # telemetry must never break a backtest
                        except Exception:
                            _temp_leg = _single_hit   # graceful fallback to single hit
                    impact_pct += _temp_leg
                if amihud_coef is not None:
                    illiq = cand.get("amihud")
                    if illiq and illiq > 0:
                        impact_pct += float(amihud_coef) * float(illiq) * alloc * 100.0
                held.add(cand["ticker"])
                shares = alloc / cand["entry_price"]
                cash -= alloc
                open_pos[f"{idx}-{cand['ticker']}"] = {
                    "ticker": cand["ticker"],
                    "entry_date": cand["entry_date"],
                    "exit_date": cand["exit_date"],
                    "exit_idx": cand["exit_idx"],
                    "entry_price": cand["entry_price"],
                    "exit_price": cand["exit_price"],
                    "net_return_pct": cand["net_return_pct"],
                    "gross_return_pct": cand["gross_return_pct"],
                    "holding_days": cand["holding_days"],
                    "exit_reason": cand["exit_reason"],
                    "win_threshold": cand.get("win_threshold", 0.0),
                    "sector": cand.get("sector", "Unknown"),
                    "impact_pct": impact_pct,
                    "alloc": alloc,
                    "shares": shares,
                    "mtm_idx_ticker_idx": idx,
                }

        # 3) Mark-to-market NAV snapshot
        nav = cash
        for p in open_pos.values():
            px = price_at(idx, p["ticker"])
            nav += p["shares"] * (px if px is not None else p["entry_price"])
        equity.append({
            "date": str(date)[:10],
            "nav": round(nav, 2),
            "cash": round(cash, 2),
            "positions": len(open_pos),
        })
        # This bar's close NAV is the open NAV for tomorrow's daily-loss governor.
        prev_close_nav = nav

    return equity, trades


# ── Benchmark + risk/return analytics ───────────────────────────────────────────

def equal_weight_benchmark_nav(
    daily_returns_by_date: dict[str, float],
    equity_dates: list[str],
    starting_capital: float,
) -> list[float]:
    """Compound an equal-weight benchmark NAV aligned to the portfolio dates."""
    nav = starting_capital
    out: list[float] = []
    for d in equity_dates:
        r = daily_returns_by_date.get(d, 0.0)
        nav *= (1 + r)
        out.append(round(nav, 2))
    return out


def daily_returns(nav: list[float]) -> np.ndarray:
    arr = np.asarray(nav, dtype=float)
    if len(arr) < 2:
        return np.array([])
    return arr[1:] / arr[:-1] - 1.0


def max_drawdown(nav: list[float]) -> float:
    """Maximum peak-to-trough drawdown of a NAV series, as a negative %."""
    arr = np.asarray(nav, dtype=float)
    if len(arr) == 0:
        return 0.0
    running_max = np.maximum.accumulate(arr)
    dd = (arr / running_max - 1.0) * 100.0
    return float(np.min(dd))


def max_drawdown_duration(nav: list[float]) -> int:
    """
    Longest peak-to-recovery span in trading days: the max number of periods the
    NAV spent below a prior peak before reclaiming it (or until series end if it
    never recovers).
    """
    arr = np.asarray(nav, dtype=float)
    if len(arr) < 2:
        return 0
    peak = arr[0]
    peak_idx = 0
    max_dur = 0
    underwater = False
    for i in range(1, len(arr)):
        if arr[i] < peak:
            underwater = True
            max_dur = max(max_dur, i - peak_idx)          # ongoing underwater span
        elif arr[i] >= peak:
            if underwater:
                max_dur = max(max_dur, i - peak_idx)       # include the recovery day
            peak = arr[i]
            peak_idx = i
            underwater = False
    return int(max_dur)


def beta_alpha(port_rets: np.ndarray, bench_rets: np.ndarray) -> tuple[float, float]:
    """
    Jensen's alpha & beta (risk-free = 0). Beta = cov(p,b)/var(b).
    Alpha is annualised and returned in percent.
    """
    n = min(len(port_rets), len(bench_rets))
    if n < 2:
        return 0.0, 0.0
    p = np.asarray(port_rets[:n], dtype=float)
    b = np.asarray(bench_rets[:n], dtype=float)
    var_b = np.var(b)
    if var_b < 1e-12:
        return 0.0, 0.0
    beta = float(np.cov(p, b, bias=True)[0, 1] / var_b)
    alpha_daily = float(np.mean(p) - beta * np.mean(b))
    alpha_annual_pct = alpha_daily * TRADING_DAYS * 100.0
    return round(beta, 3), round(alpha_annual_pct, 2)


# ── Factor attribution (Fama-French / Carhart) ─────────────────────────────────────
# Decompose strategy returns into systematic factor exposures + residual α, so an
# "edge" can be proven idiosyncratic rather than repackaged market/size/momentum β.

def compute_factor_returns(df: pd.DataFrame) -> pd.DataFrame:
    """Daily long-short factor returns from the prepared panel.

    MKT = equal-weight market daily return (the internal benchmark proxy).
    SMB = small-minus-big: bottom-tercile − top-tercile size daily return.
    UMD = winners-minus-losers: top-tercile − bottom-tercile 12-1 momentum return.

    Price factors (MKT/UMD) are strictly trailing/look-ahead-free. SMB uses `mktcap_cr`
    as the size proxy where available, and falls back per-bar to trailing dollar volume
    (`adv20`) where the point-in-time market cap is unavailable (G1 nulls fundamentals
    before their coverage start) — so the size factor survives over historical windows
    instead of collapsing to an all-NaN column. HML is omitted until point-in-time
    book-to-market lands. Returns a DataFrame indexed by date with columns present.
    """
    if df is None or df.empty or "close" not in df.columns:
        return pd.DataFrame()
    d = df[["ticker", "date", "close"]].copy()
    # Size proxy: mktcap_cr first, dollar-volume (adv20) as the PIT-safe fallback.
    size = None
    if "mktcap_cr" in df.columns:
        size = pd.to_numeric(df["mktcap_cr"], errors="coerce").to_numpy(dtype=float)
    if "adv20" in df.columns:
        adv = pd.to_numeric(df["adv20"], errors="coerce").to_numpy(dtype=float)
        size = adv if size is None else np.where(np.isfinite(size), size, adv)
    if size is not None:
        d["_size"] = size
    d = d.sort_values(["ticker", "date"])
    g = d.groupby("ticker")
    d["ret"] = g["close"].pct_change()
    # 12-1 momentum: cumulative return from 252 to 21 trading days ago (skip last month).
    d["mom"] = g["close"].shift(21) / g["close"].shift(252) - 1.0

    out: dict[str, pd.Series] = {}
    out["MKT"] = d.groupby("date")["ret"].mean()
    if "_size" in d.columns and d["_size"].notna().any():
        d["_size_pct"] = d.groupby("date")["_size"].rank(pct=True)
        small = d[d["_size_pct"] <= 1.0 / 3].groupby("date")["ret"].mean()
        big = d[d["_size_pct"] >= 2.0 / 3].groupby("date")["ret"].mean()
        out["SMB"] = (small - big)
    d["_mom_pct"] = d.groupby("date")["mom"].rank(pct=True)
    win = d[d["_mom_pct"] >= 2.0 / 3].groupby("date")["ret"].mean()
    los = d[d["_mom_pct"] <= 1.0 / 3].groupby("date")["ret"].mean()
    out["UMD"] = (win - los)

    fr = pd.DataFrame(out)
    fr.index = pd.to_datetime(fr.index)
    return fr.dropna(how="all")


def factor_attribution(port_rets, dates, factor_returns: pd.DataFrame,
                       freq: int = TRADING_DAYS) -> Optional[dict]:
    """OLS attribution of strategy excess returns on factor returns (Fama-French 1993 /
    Carhart 1997). The intercept is the true annualized α (with a t-stat); the slopes
    are systematic factor loadings. Aligns by date and drops missing rows.

    `port_rets` = per-period strategy returns; `dates` = their dates (len == port_rets);
    `factor_returns` = DataFrame indexed by date with factor columns.
    """
    if factor_returns is None or len(factor_returns) == 0:
        return None
    cols = [c for c in ("MKT", "SMB", "HML", "UMD") if c in factor_returns.columns]
    pr = np.asarray(port_rets, dtype=float)
    if not cols or len(pr) < 10 or len(pr) != len(dates):
        return None
    s = pd.Series(pr, index=pd.to_datetime(list(dates)))
    # Stitched walk-forward OOS curves can repeat a date at window seams → a non-unique
    # index that breaks the inner-join reindex. Collapse duplicates (mean) so attribution
    # works on both the single-backtest (unique) and WFO (stitched) equity paths.
    if s.index.has_duplicates:
        s = s.groupby(level=0).mean()
    fr = factor_returns[cols]
    if fr.index.has_duplicates:
        fr = fr.groupby(level=0).mean()
    aligned = (pd.concat([s.rename("y"), fr], axis=1, join="inner")
               .replace([np.inf, -np.inf], np.nan).dropna())
    if len(aligned) < max(10, len(cols) + 2):
        return None
    y = aligned["y"].to_numpy(dtype=float)
    X = np.column_stack([np.ones(len(aligned))] + [aligned[c].to_numpy(dtype=float) for c in cols])
    # np.errstate guards against benign FP flags some BLAS matmul paths raise.
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        if not np.all(np.isfinite(beta)):
            return None
        resid = y - X @ beta
        n, k = X.shape
        dof = max(n - k, 1)
        sigma2 = float(resid @ resid / dof)
        xtx_inv = np.linalg.pinv(X.T @ X)
        se = np.sqrt(np.maximum(np.diag(sigma2 * xtx_inv), 0.0))
        tstat = np.where(se > 1e-12, beta / se, np.nan)
        ss_tot = float(np.sum((y - y.mean()) ** 2)) or 1e-12
        r2 = 1.0 - float(resid @ resid) / ss_tot
    return {
        "alpha_annual_pct": round(float(beta[0]) * freq * 100.0, 3),
        "alpha_tstat": round(float(tstat[0]), 3) if np.isfinite(tstat[0]) else None,
        "loadings": {c: round(float(beta[i + 1]), 3) for i, c in enumerate(cols)},
        "loading_tstats": {c: (round(float(tstat[i + 1]), 3) if np.isfinite(tstat[i + 1]) else None)
                           for i, c in enumerate(cols)},
        "r_squared": round(r2, 3),
        "n_obs": int(n),
        "factors": cols,
    }


def sharpe(port_rets: np.ndarray) -> float:
    if len(port_rets) < 2:
        return 0.0
    sd = float(np.std(port_rets, ddof=1))
    if sd < 1e-12:
        return 0.0
    return round(float(np.mean(port_rets)) / sd * np.sqrt(TRADING_DAYS), 2)


def sortino(port_rets: np.ndarray, target: float = 0.0) -> float:
    if len(port_rets) < 2:
        return 0.0
    excess = np.asarray(port_rets, dtype=float) - target
    downside = np.sqrt(np.mean(np.minimum(excess, 0) ** 2))
    if downside < 1e-12:
        return 0.0
    return round(float(np.mean(excess) / downside * np.sqrt(TRADING_DAYS)), 2)


def expectancy(win_rate_pct: float, avg_win: float, avg_loss: float) -> float:
    """Expected net % per trade: (WinRate*AvgWin) - (LossRate*|AvgLoss|)."""
    wr = win_rate_pct / 100.0
    return round(wr * avg_win - (1 - wr) * abs(avg_loss), 4)


def profit_factor(returns: list[float]) -> float:
    wins = sum(r for r in returns if r > 0)
    losses = sum(r for r in returns if r < 0)
    if abs(losses) < 1e-9:
        return float("inf") if wins > 0 else 0.0
    return round(wins / abs(losses), 2)


def monte_carlo_drawdowns(trade_returns: list[float], n_runs: int = 1000) -> dict:
    """Bootstrap the distribution of max drawdown by resampling trade returns."""
    arr = np.asarray(trade_returns, dtype=float)
    if len(arr) == 0:
        return {"p5": 0, "p25": 0, "p50": 0, "p75": 0, "p95": 0, "histogram": []}
    max_dds = []
    for _ in range(int(n_runs)):
        shuffled = np.random.choice(arr, size=len(arr), replace=True)
        equity = np.cumprod(1 + shuffled / 100.0)
        running_max = np.maximum.accumulate(equity)
        dd = (equity / running_max - 1.0) * 100.0
        max_dds.append(float(np.min(dd)))
    histogram, _ = np.histogram(max_dds, bins=30)
    return {
        "p5": float(np.percentile(max_dds, 5)),
        "p25": float(np.percentile(max_dds, 25)),
        "p50": float(np.percentile(max_dds, 50)),
        "p75": float(np.percentile(max_dds, 75)),
        "p95": float(np.percentile(max_dds, 95)),
        "histogram": histogram.tolist(),
    }


# ── Multiple-testing / overfitting statistics (Bailey & López de Prado) ────────────
# When a grid search or a per-window WFO selects the best of N configurations, the
# winning Sharpe is upward-biased purely by the number of trials — even pure noise
# produces a high max-of-N Sharpe. These correct for that.

def probabilistic_sharpe_ratio(sr: float, sr_benchmark: float, n_obs: int,
                               skew: float = 0.0, kurt: float = 3.0) -> float:
    """PSR — P(true SR > benchmark) given the observed per-period SR, sample length,
    and non-normality (Bailey & López de Prado 2012). `sr`/`sr_benchmark` are
    per-period (non-annualized) Sharpes; `kurt` is non-excess (normal = 3)."""
    if n_obs < 2:
        return 0.0
    denom = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr * sr
    if denom <= 1e-12:
        return 0.0
    from scipy.stats import norm
    z = (sr - sr_benchmark) * np.sqrt(n_obs - 1.0) / np.sqrt(denom)
    return float(norm.cdf(z))


def expected_max_sharpe(sr_variance: float, n_trials: int) -> float:
    """Expected maximum per-period Sharpe under the null of zero true edge across
    `n_trials` independent trials (Bailey & López de Prado 2014, eq. for SR₀).
    `sr_variance` = variance of the per-period trial Sharpes."""
    if n_trials < 2 or sr_variance <= 0:
        return 0.0
    from scipy.stats import norm
    gamma = 0.5772156649015329  # Euler–Mascheroni
    z1 = norm.ppf(1.0 - 1.0 / n_trials)
    z2 = norm.ppf(1.0 - 1.0 / (n_trials * np.e))
    return float(np.sqrt(sr_variance) * ((1.0 - gamma) * z1 + gamma * z2))


def deflated_sharpe_ratio(returns, trial_sharpes_annual, freq: int = TRADING_DAYS,
                          n_eff: Optional[float] = None) -> dict:
    """Deflated Sharpe Ratio (Bailey & López de Prado 2014): probability the selected
    strategy's true SR exceeds the maximum SR achievable by chance across the trials,
    correcting for trial count, trial-SR dispersion, sample length, skew and kurtosis.
    DSR ≳ 0.95 ⇒ survives multiple-testing; < 0.5 ⇒ likely a selection artefact.

    `returns` = the SELECTED strategy's per-period (daily) returns;
    `trial_sharpes_annual` = annualized Sharpes of ALL configurations searched.

    `n_eff` (C4+C9, audit §3.6): OPTIONAL override for the trial count fed to
    `expected_max_sharpe`. When None (default) the haircut uses the NOMINAL count
    (len of the dispersion-usable trial Sharpes) — exact legacy behaviour, byte-for-byte.
    When supplied, it should be the CROSS-CAMPAIGN, correlation-CLUSTER-ADJUSTED effective
    number of independent trials (from the `research_trials` ledger via
    `effective_trials.effective_n`). This makes the multiple-testing denominator honest:
    it counts every config ever searched (C4: parameter sweeps, profile re-runs, WFO
    per-window selections — not just one run's survivors) while collapsing near-duplicate
    overlapping combos that nominal N over-counts (C9). `n_eff` is clamped to ≥ 1; the
    per-run nominal count is still reported in `n_trials` so the legacy figure is never lost.
    """
    r = np.asarray(returns, dtype=float)
    r = r[np.isfinite(r)]
    n = int(len(r))
    out = {"dsr": 0.0, "psr_zero": 0.0, "sr_annual": 0.0, "sr0_annual": 0.0,
           "n_trials": int(len(trial_sharpes_annual)), "n_obs": n, "skew": 0.0, "kurt": 3.0,
           "n_eff": None}
    if n < 3:
        return out
    mu, sd = float(r.mean()), float(r.std(ddof=1))
    if sd <= 1e-12:
        return out
    z = (r - mu) / sd
    sk, ku = float(np.mean(z ** 3)), float(np.mean(z ** 4))
    sr_d = mu / sd
    trials_d = np.asarray(trial_sharpes_annual, dtype=float) / np.sqrt(freq)
    trials_d = trials_d[np.isfinite(trials_d)]
    var_sr = float(np.var(trials_d, ddof=1)) if len(trials_d) > 1 else 0.0
    n_trials = max(len(trials_d), 1)
    # Effective-trials override (C4/C9): deflate against the honest cross-campaign +
    # correlation-clustered count when supplied; else nominal per-run count (legacy).
    eff = None
    if n_eff is not None:
        try:
            eff = max(1.0, float(n_eff))
        except (TypeError, ValueError):
            eff = None
    n_for_haircut = eff if eff is not None else float(n_trials)
    sr0_d = expected_max_sharpe(var_sr, n_for_haircut)
    out.update({
        "dsr": probabilistic_sharpe_ratio(sr_d, sr0_d, n, sk, ku),
        "psr_zero": probabilistic_sharpe_ratio(sr_d, 0.0, n, sk, ku),
        "sr_annual": round(sr_d * np.sqrt(freq), 4),
        "sr0_annual": round(sr0_d * np.sqrt(freq), 4),
        "n_trials": n_trials, "n_obs": n, "skew": round(sk, 3), "kurt": round(ku, 3),
        "n_eff": (round(eff, 3) if eff is not None else None),
    })
    return out


def probability_of_backtest_overfitting(perf_matrix) -> Optional[dict]:
    """PBO via Combinatorially-Symmetric Cross-Validation (Bailey, Borwein, López de
    Prado & Zhu 2017). `perf_matrix` is (n_blocks, n_configs), higher = better. For
    every C(S, S/2) split of blocks into in-sample / out-of-sample halves, take the
    IS-best config and find its OOS rank; PBO = fraction of splits where the IS-best
    lands at or below the OOS median (logit ≤ 0)."""
    M = np.asarray(perf_matrix, dtype=float)
    if M.ndim != 2:
        return None
    S, N = M.shape
    if S % 2 == 1:                # CSCV needs an even number of blocks
        M, S = M[:S - 1], S - 1
    if S < 4 or N < 2:
        return None
    half = S // 2
    import itertools as _it
    logits = []
    for is_idx in _it.combinations(range(S), half):
        oos_idx = [i for i in range(S) if i not in is_idx]
        is_perf = np.nanmean(M[list(is_idx)], axis=0)
        oos_perf = np.nanmean(M[oos_idx], axis=0)
        n_star = int(np.nanargmax(is_perf))                  # in-sample-best config
        order = np.argsort(oos_perf)                          # ascending OOS performance
        rank = int(np.where(order == n_star)[0][0]) + 1       # 1 (worst) … N (best)
        w = min(max(rank / (N + 1.0), 1e-6), 1.0 - 1e-6)      # relative OOS rank
        logits.append(float(np.log(w / (1.0 - w))))
    logits = np.asarray(logits)
    return {"pbo": float(np.mean(logits <= 0.0)), "n_splits": int(len(logits)),
            "n_blocks": int(S), "n_configs": int(N)}


def compute_metrics(
    equity_curve: list[dict],
    trades: list[dict],
    bench_nav: list[float],
    starting_capital: float,
    factor_returns: Optional["pd.DataFrame"] = None,
) -> dict:
    """Assemble the full Bloomberg-style metric matrix from the simulation output.

    When `factor_returns` is supplied (a date-indexed DataFrame of MKT/SMB/UMD/…),
    a Fama-French/Carhart `factor_attribution` block is attached so the strategy's
    α can be proven idiosyncratic rather than repackaged factor β.
    """
    nav_series = [e["nav"] for e in equity_curve] or [starting_capital]
    p_rets = daily_returns(nav_series)
    b_rets = daily_returns(bench_nav) if bench_nav else np.array([])

    total = len(trades)
    rets = [t["return_pct"] for t in trades]
    win_rets = [r for r in rets if r > 0]
    loss_rets = [r for r in rets if r <= 0]
    wins = len(win_rets)
    win_rate = round(wins / total * 100, 1) if total else 0.0
    avg_win = round(sum(win_rets) / len(win_rets), 2) if win_rets else 0.0
    avg_loss = round(sum(loss_rets) / len(loss_rets), 2) if loss_rets else 0.0

    final_nav = nav_series[-1]
    n_days = max(len(nav_series) - 1, 1)
    total_return_pct = (final_nav / starting_capital - 1) * 100.0
    cagr_pct = ((final_nav / starting_capital) ** (TRADING_DAYS / n_days) - 1) * 100.0
    mdd = max_drawdown(nav_series)
    beta, alpha = beta_alpha(p_rets, b_rets)

    bench_final = bench_nav[-1] if bench_nav else starting_capital
    bench_total_return_pct = (bench_final / starting_capital - 1) * 100.0

    exit_breakdown = {"stop_loss": 0, "trailing_stop": 0, "time_stop": 0}
    for t in trades:
        exit_breakdown[t.get("exit_reason", "time_stop")] = exit_breakdown.get(t.get("exit_reason", "time_stop"), 0) + 1

    # Fama-French/Carhart attribution: the intercept is the *true* α; the loadings are
    # the systematic exposures. Aligns p_rets (which spans equity_curve[1:]) to factors.
    attribution = None
    if factor_returns is not None and len(p_rets) > 10:
        fa_dates = [e["date"] for e in equity_curve[1:]]   # p_rets aligns to diffs (skip day 0)
        attribution = factor_attribution(p_rets, fa_dates, factor_returns)

    return {
        "starting_capital": round(starting_capital, 2),
        "final_nav": round(final_nav, 2),
        "total_return_pct": round(total_return_pct, 2),
        "cagr_pct": round(cagr_pct, 2),
        "benchmark_total_return_pct": round(bench_total_return_pct, 2),
        "total_trades": total,
        "wins": wins,
        "losses": total - wins,
        "win_rate": win_rate,
        "avg_return": round(sum(rets) / len(rets), 2) if rets else 0.0,
        "avg_win_return": avg_win,
        "avg_loss_return": avg_loss,
        "win_loss_ratio": round(avg_win / abs(avg_loss), 2) if avg_loss else 0.0,
        "expectancy": expectancy(win_rate, avg_win, avg_loss),
        "profit_factor": profit_factor(rets),
        "sharpe_ratio": sharpe(p_rets),
        "sortino_ratio": sortino(p_rets),
        "calmar_ratio": round(abs(cagr_pct / mdd), 2) if mdd else 0.0,
        "max_drawdown": round(mdd, 2),
        "max_drawdown_duration_days": max_drawdown_duration(nav_series),
        "beta": beta,
        "alpha_annual_pct": alpha,
        "exit_breakdown": exit_breakdown,
        "factor_attribution": attribution,
    }
