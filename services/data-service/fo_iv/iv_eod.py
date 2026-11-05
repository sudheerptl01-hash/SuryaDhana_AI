"""``iv_eod`` — one session of the F&O file → ``iv_surface_daily`` / ``iv_expiry_daily`` / ``iv_summary_daily`` (PLAN 1.1 method,
R-IV §3–§4 adopted; the prototype's math reproduced so the G2 replay matches ``R-IV/iv_compare_NIFTY.csv``).

Per underlying and expiry: the forward from put-call parity at the strike nearest spot where both sides traded (else the
matching-month future, else spot·e^{rT}; the parity forward is replaced by the future when they differ by more than
``PCP_FUTURE_TOL``); Black-76 IV for traded OTM strikes plus 3 % ITM (mean when both sides exist); ATM IV interpolated at
the forward; 25Δ / 10Δ IVs by inverting each strike's own delta; T = calendar days / 365. Per underlying: near (dte > 2)
and monthly (20–60 d) series, constant-maturity 30 / 60 / 90 by variance interpolation, 25Δ skew at 30 d, term slope,
IV rank AND percentile over 252 sessions, RV20 cc / Parkinson / Yang-Zhang, FOVOLT, IV − RV, the 1-day expected move.
``model_version`` and ``r`` on every row; untraded strikes carry ``price_source = 'none'`` and no IV.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from data_health import db
from fo_iv import black76 as b76
from fo_iv import files as fo_files
from fo_iv import realised
from fo_iv.black76 import MODEL_VERSION
from fo_iv.schema import CASTS, COLUMNS
from shared.logging import get_logger

logger = get_logger(__name__)

INDEX_SYMBOLS: tuple[str, ...] = ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "NIFTYNXT50")
INDEX_NAMES: dict[str, str] = {"NIFTY": "NIFTY 50", "BANKNIFTY": "NIFTY BANK", "FINNIFTY": "NIFTY FINANCIAL SERVICES",
                               "MIDCPNIFTY": "NIFTY MIDCAP SELECT", "NIFTYNXT50": "NIFTY NEXT 50"}
DEFAULT_R = 0.065
RATE_SEED_DATE = date(2019, 10, 1)
RATE_TENOR = "3m"
NEAR_MIN_DTE = 3                  # near series: dte > 2 (expiry-day and T ≤ 2 d rows stay in the surface, out of "near")
MONTHLY_DTE = (20, 60)
CM_TENORS = (30, 60, 90)
RANK_WINDOW = 252
RANK_MIN_OBS = 20
SURFACE_MONEYNESS = 0.15
SURFACE_EXPIRIES = 3
PCP_FUTURE_TOL = 0.005
MIN_IV_STRIKES = 4
FEW_STRIKES = 8
DELTA_TARGETS = ((0.25, "25d"), (0.10, "10d"))


# ── rate ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def seed_rate_curve(store: Any, *, now: datetime | None = None) -> int:
    """The dated constant (O-T5 default): 6.5 % at tenor 3m from 2019-10-01. Idempotent."""
    row = {"date": RATE_SEED_DATE, "tenor": RATE_TENOR, "rate": DEFAULT_R, "source": "constant_seed_6.5pct", "first_seen_at": now or db.utcnow()}
    if db.scalar(store, "SELECT COUNT(*) FROM rate_curve WHERE date = ? AND tenor = ? AND source = ?", [RATE_SEED_DATE, RATE_TENOR, row["source"]]):
        return 0
    return db.upsert(store, "rate_curve", pd.DataFrame([row]), COLUMNS["rate_curve"], CASTS["rate_curve"])


def rate_for(store: Any, day: date, tenor: str = RATE_TENOR) -> tuple[float, str]:
    """(rate, source) in force on ``day``: the newest rate_curve row dated ≤ day for the tenor, else the default constant."""
    row = store.read_one("SELECT rate, source FROM rate_curve WHERE tenor = ? AND date <= ? ORDER BY date DESC, first_seen_at DESC LIMIT 1", [tenor, day])
    if row is None:
        return DEFAULT_R, "default_constant"
    return float(row[0]), str(row[1])


# ── per expiry ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _px(close: float, volume: float) -> float | None:
    """NSE's close only when the strike traded (an untraded strike's settle is a model price: no IV)."""
    if volume is None or not np.isfinite(volume) or volume <= 0 or close is None or not np.isfinite(close) or close <= 0:
        return None
    return float(close)


def _at_delta(deltas: dict[float, float], target: float, strikes: np.ndarray, side_ivs: np.ndarray) -> float | None:
    """Strike whose (own-IV) delta equals ``target`` by inverse interpolation, then the IV at that strike."""
    if len(deltas) < 2:
        return None
    ks = np.array(sorted(deltas))
    ds = np.array([deltas[k] for k in ks])
    order = np.argsort(ds)
    if not (ds.min() <= target <= ds.max()):
        return None
    k_t = float(np.interp(target, ds[order], ks[order]))
    return float(np.interp(k_t, strikes, side_ivs))


def expiry_surface(symbol: str, kind: str, opts: pd.DataFrame, futs: pd.DataFrame, day: date, r: float, *, want_surface: bool,
                   spot: float | None, now: datetime, source_file: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str | None]:
    """All expiries of one underlying → (expiry rows, surface rows, spot_source)."""
    expiry_rows: list[dict[str, Any]] = []
    surface_rows: list[dict[str, Any]] = []
    fut_close: dict[date, float] = {}
    for e, c in zip(futs["expiry"], futs["close"], strict=True):
        if c is not None and np.isfinite(c) and c > 0:
            fut_close[e] = float(c)
    spot_source = "underlying_price" if spot else None
    s_ref = spot
    if s_ref is None and fut_close:
        s_ref = fut_close[min(fut_close)]
        spot_source = "near_future"
    if s_ref is None:
        return [], [], None
    rank = 0
    for expiry, o in sorted(opts.groupby("expiry", sort=True), key=lambda kv: kv[0]):
        dte = (expiry - day).days
        if dte <= 0:
            continue
        t = dte / 365.0
        ce = o[o["opt_type"] == "CE"].drop_duplicates("strike").set_index("strike")
        pe = o[o["opt_type"] == "PE"].drop_duplicates("strike").set_index("strike")
        ks = sorted(set(ce.index) & set(pe.index))
        if not ks:
            continue
        rank += 1
        flags: list[str] = []
        c_px = {k: _px(ce.at[k, "close"], ce.at[k, "volume"]) for k in ks}
        p_px = {k: _px(pe.at[k, "close"], pe.at[k, "volume"]) for k in ks}
        fwd: float | None = None
        fsrc: str | None = None
        for k in sorted(ks, key=lambda k: abs(k - s_ref))[:3]:
            cpx, ppx = c_px[k], p_px[k]
            if cpx is not None and ppx is not None:
                fwd, fsrc = b76.forward_from_parity(k, cpx, ppx, t, r), "pcp"
                break
        fut = fut_close.get(expiry)
        if fwd is not None and fut is not None and abs(fwd / fut - 1.0) > PCP_FUTURE_TOL:
            fwd, fsrc = fut, "future"
            flags.append("pcp_fallback_future")
        if fwd is None:
            if fut is not None:
                fwd, fsrc = fut, "future"
            else:
                fwd, fsrc = s_ref * math.exp(r * t), "spot"
                flags.append("forward_from_spot")
        ivs: dict[float, tuple[float, float | None, float | None]] = {}
        for k in ks:
            civ = b76.implied_vol(c_px[k], fwd, k, t, True, r) if (c_px[k] is not None and k >= fwd * (1 - b76.ITM_BAND)) else None
            piv = b76.implied_vol(p_px[k], fwd, k, t, False, r) if (p_px[k] is not None and k <= fwd * (1 + b76.ITM_BAND)) else None
            vals = [v for v in (civ, piv) if v]
            if vals:
                ivs[k] = (float(np.mean(vals)), civ, piv)
        call_oi = float(pd.to_numeric(ce["oi"], errors="coerce").fillna(0).sum())
        put_oi = float(pd.to_numeric(pe["oi"], errors="coerce").fillna(0).sum())
        if len(ivs) < MIN_IV_STRIKES:
            expiry_rows.append({"date": day, "symbol": symbol, "expiry": expiry, "dte": dte, "forward": round(fwd, 2), "forward_source": fsrc,
                                "atm_iv": None, "iv_25d_put": None, "iv_25d_call": None, "skew_25d": None, "iv_10d_put": None, "iv_10d_call": None,
                                "n_iv_strikes": len(ivs), "call_oi": call_oi, "put_oi": put_oi, "pcr": (put_oi / call_oi) if call_oi else None,
                                "expected_move_pct": None, "quality_flags": ",".join([*flags, "too_few_strikes"]), "model_version": MODEL_VERSION,
                                "r": r, "first_seen_at": now})
            continue
        kk = np.array(sorted(ivs))
        vv = np.array([ivs[k][0] for k in kk])
        atm = float(np.interp(fwd, kk, vv))
        if not (kk[0] <= fwd <= kk[-1]):
            flags.append("atm_extrapolated")
        d_c = {k: b76.delta(fwd, k, t, civ_k, True, r) for k, (_, civ_k, _) in ivs.items() if civ_k}
        d_p = {k: b76.delta(fwd, k, t, piv_k, False, r) for k, (_, _, piv_k) in ivs.items() if piv_k}
        c_side = np.array([ivs[k][1] or ivs[k][0] for k in kk])
        p_side = np.array([ivs[k][2] or ivs[k][0] for k in kk])
        wings: dict[str, float | None] = {}
        for target, tag in DELTA_TARGETS:
            wings[f"iv_{tag}_call"] = _at_delta(d_c, target, kk, c_side)
            wings[f"iv_{tag}_put"] = _at_delta(d_p, -target, kk, p_side)
        if len(ivs) < FEW_STRIKES:
            flags.append("few_strikes")
        if dte <= NEAR_MIN_DTE - 1:
            flags.append("short_dte")
        skew = (wings["iv_25d_put"] - wings["iv_25d_call"]) * 100 if (wings["iv_25d_put"] and wings["iv_25d_call"]) else None
        expiry_rows.append({"date": day, "symbol": symbol, "expiry": expiry, "dte": dte, "forward": round(fwd, 2), "forward_source": fsrc,
                            "atm_iv": round(atm * 100, 4),
                            "iv_25d_put": round(wings["iv_25d_put"] * 100, 4) if wings["iv_25d_put"] else None,
                            "iv_25d_call": round(wings["iv_25d_call"] * 100, 4) if wings["iv_25d_call"] else None,
                            "skew_25d": round(skew, 4) if skew is not None else None,
                            "iv_10d_put": round(wings["iv_10d_put"] * 100, 4) if wings["iv_10d_put"] else None,
                            "iv_10d_call": round(wings["iv_10d_call"] * 100, 4) if wings["iv_10d_call"] else None,
                            "n_iv_strikes": len(ivs), "call_oi": call_oi, "put_oi": put_oi, "pcr": round(put_oi / call_oi, 4) if call_oi else None,
                            "expected_move_pct": round(atm * math.sqrt(t) * 100, 4), "quality_flags": ",".join(flags) or None,
                            "model_version": MODEL_VERSION, "r": r, "first_seen_at": now})
        if want_surface and rank <= SURFACE_EXPIRIES:
            lo, hi = fwd * (1 - SURFACE_MONEYNESS), fwd * (1 + SURFACE_MONEYNESS)
            for k in ks:
                if not (lo <= k <= hi):
                    continue
                for side, frame, px, call in (("CE", ce, c_px[k], True), ("PE", pe, p_px[k], False)):
                    iv = (ivs[k][1] if call else ivs[k][2]) if k in ivs else None
                    row = frame.loc[k]
                    lot = row.get("lot")
                    surface_rows.append({"date": day, "symbol": symbol, "expiry": expiry, "strike": float(k), "opt_type": side,
                                         "price": px, "price_source": "close" if px is not None else "none", "forward": round(fwd, 4),
                                         "forward_source": fsrc, "t_years": t, "r": r, "iv": round(iv * 100, 4) if iv else None,
                                         "delta": round(b76.delta(fwd, k, t, iv, call, r), 6) if iv else None,
                                         "vega": round(b76.vega(fwd, k, t, iv, r) / 100.0, 4) if iv else None,
                                         "oi": _f(row.get("oi")), "oi_chg": _f(row.get("oi_chg")), "volume": _f(row.get("volume")),
                                         "lot": int(lot) if lot is not None and np.isfinite(lot) else None,
                                         "log_moneyness": round(math.log(k / fwd), 6), "model_version": MODEL_VERSION,
                                         "source_file": source_file, "first_seen_at": now})
    return expiry_rows, surface_rows, spot_source


def _f(v: Any) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) else None


# ── per underlying ──────────────────────────────────────────────────────────────────────────────────────────────────

def cm_iv(rows: list[dict[str, Any]], target_days: int) -> float | None:
    """VIX-style constant maturity at ``target_days`` from the expiries bracketing it (dte ≥ 1, atm_iv present); None without a bracket."""
    r = sorted([x for x in rows if x.get("atm_iv") is not None and (x.get("dte") or 0) >= 1], key=lambda x: x["dte"])
    near = [x for x in r if x["dte"] <= target_days]
    far = [x for x in r if x["dte"] > target_days]
    if not (near and far):
        return None
    a, b = near[-1], far[0]
    v = b76.cm_variance_interp(a["dte"], a["atm_iv"] / 100.0, b["dte"], b["atm_iv"] / 100.0, target_days)
    return round(v * 100, 4) if v is not None else None


def cm_skew(rows: list[dict[str, Any]], target_days: int = 30) -> float | None:
    """25Δ skew at ``target_days``: linear in dte between the bracketing expiries that both carry a skew; else the nearest with one."""
    r = sorted([x for x in rows if x.get("skew_25d") is not None and (x.get("dte") or 0) >= NEAR_MIN_DTE], key=lambda x: x["dte"])
    if not r:
        return None
    near = [x for x in r if x["dte"] <= target_days]
    far = [x for x in r if x["dte"] > target_days]
    if near and far:
        a, b = near[-1], far[0]
        w = (b["dte"] - target_days) / (b["dte"] - a["dte"])
        return round(a["skew_25d"] * w + b["skew_25d"] * (1 - w), 4)
    pick = min(r, key=lambda x: abs(x["dte"] - target_days))
    return round(float(pick["skew_25d"]), 4)


def summarise(symbol: str, expiry_rows: list[dict[str, Any]], day: date, r: float, *, spot: float | None, spot_source: str | None,
              legacy: bool, now: datetime) -> dict[str, Any]:
    near = sorted([x for x in expiry_rows if x.get("atm_iv") is not None and x["dte"] >= NEAR_MIN_DTE], key=lambda x: x["dte"])
    monthly = sorted([x for x in expiry_rows if x.get("atm_iv") is not None and MONTHLY_DTE[0] <= x["dte"] <= MONTHLY_DTE[1]], key=lambda x: x["dte"])
    cm = {d: cm_iv(expiry_rows, d) for d in CM_TENORS}
    flags: list[str] = []
    if cm[30] is None:
        flags.append("no_cm30")
    if spot_source == "near_future":
        flags.append("spot_from_future")
    if legacy:
        flags.append("legacy_file")
    if len([x for x in expiry_rows if x.get("atm_iv") is not None]) < 2:
        flags.append("few_expiries")
    base = cm[30] if cm[30] is not None else (near[0]["atm_iv"] if near else None)
    return {"date": day, "symbol": symbol, "spot": spot, "spot_source": spot_source,
            "iv30_cm": cm[30], "iv60_cm": cm[60], "iv90_cm": cm[90],
            "near_atm_iv": near[0]["atm_iv"] if near else None, "near_expiry": near[0]["expiry"] if near else None,
            "near_dte": near[0]["dte"] if near else None,
            "monthly_atm_iv": monthly[0]["atm_iv"] if monthly else None, "monthly_expiry": monthly[0]["expiry"] if monthly else None,
            "skew_25d_30": cm_skew(expiry_rows, 30),
            "term_slope_30_90": round(cm[90] - cm[30], 4) if (cm[30] is not None and cm[90] is not None) else None,
            "iv_rank_252": None, "iv_pctile_252": None, "rv20_cc": None, "rv20_parkinson": None, "rv20_yz": None, "fovolt_ann": None,
            "iv_minus_rv20": None, "expected_move_1d_pct": round(base / math.sqrt(252.0), 4) if base is not None else None,
            "quality_flags": ",".join(flags) or None, "model_version": MODEL_VERSION, "r": r, "first_seen_at": now}


def rank_and_percentile(history: list[float], today: float | None) -> tuple[float | None, float | None]:
    """IV rank = position of today in the trailing window's [min, max] incl. today; IV percentile = share of the trailing
    (prior) sessions below today. Both over at most RANK_WINDOW sessions; None below RANK_MIN_OBS observations."""
    if today is None:
        return None, None
    prior = [v for v in history if v is not None][-RANK_WINDOW:]
    if len(prior) < RANK_MIN_OBS:
        return None, None
    window = [*prior, today][-RANK_WINDOW:]
    lo, hi = min(window), max(window)
    rank = round((today - lo) / (hi - lo) * 100.0, 2) if hi > lo else None
    pct = round(sum(1 for v in prior if v < today) / len(prior) * 100.0, 2)
    return rank, pct


# ── the day ────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class DayResult:
    day: date
    expiry: pd.DataFrame
    surface: pd.DataFrame
    summary: pd.DataFrame
    symbols: int = 0
    seconds: float = 0.0
    flags: dict[str, int] = field(default_factory=dict)


def compute_day(contracts: pd.DataFrame, day: date, r: float, *, surface_symbols: set[str] | None = None, symbols: set[str] | None = None,
                now: datetime | None = None, source_file: str = "", legacy: bool = False) -> DayResult:
    """Pure: the contracts frame of one session → the three frames (summary without rank / RV / FOVOLT, added by ``enrich``)."""
    now = now or db.utcnow()
    t0 = datetime.now().timestamp()  # noqa: DTZ005 — wall-clock duration only
    opts = contracts[contracts["instrument"] == "OPT"]
    futs = contracts[contracts["instrument"] == "FUT"].sort_values("expiry")
    want_surface = set(surface_symbols) if surface_symbols is not None else set(INDEX_SYMBOLS)
    exp_rows: list[dict[str, Any]] = []
    surf_rows: list[dict[str, Any]] = []
    summ_rows: list[dict[str, Any]] = []
    for symbol, o in opts.groupby("symbol", sort=True):
        if symbols is not None and symbol not in symbols:
            continue
        f = futs[futs["symbol"] == symbol]
        kind = str(o["kind"].iloc[0])
        spot_vals = pd.to_numeric(o["underlying"], errors="coerce").dropna() if "underlying" in o else pd.Series(dtype=float)
        spot = float(spot_vals.iloc[0]) if len(spot_vals) and spot_vals.iloc[0] > 0 else None
        e_rows, s_rows, spot_source = expiry_surface(str(symbol), kind, o, f, day, r, want_surface=str(symbol) in want_surface, spot=spot,
                                                     now=now, source_file=source_file)
        if not e_rows:
            continue
        exp_rows.extend(e_rows)
        surf_rows.extend(s_rows)
        spot_used = spot if spot is not None else (float(f["close"].iloc[0]) if len(f) and np.isfinite(f["close"].iloc[0]) else None)
        summ_rows.append(summarise(str(symbol), e_rows, day, r, spot=spot_used, spot_source=spot_source, legacy=legacy, now=now))
    res = DayResult(day, pd.DataFrame(exp_rows, columns=COLUMNS["iv_expiry_daily"]), pd.DataFrame(surf_rows, columns=COLUMNS["iv_surface_daily"]),
                    pd.DataFrame(summ_rows, columns=COLUMNS["iv_summary_daily"]), symbols=len(summ_rows),
                    seconds=round(datetime.now().timestamp() - t0, 2))  # noqa: DTZ005
    flags: dict[str, int] = defaultdict(int)
    for q in res.expiry["quality_flags"].dropna():
        for fl in str(q).split(","):
            flags[fl] += 1
    res.flags = dict(flags)
    return res


# ── enrichment: rank, realised vol, FOVOLT ─────────────────────────────────────────────────────────────────────────

class IvHistory:
    """Trailing iv30_cm per symbol (falls back to monthly_atm_iv when iv30_cm is missing) for rank / percentile."""

    def __init__(self, store: Any, until: date, symbols: set[str] | None = None) -> None:
        self.values: dict[str, list[tuple[date, float | None]]] = defaultdict(list)
        if not db.table_exists(store, "iv_summary_daily"):
            return
        df = db.query_df(store, """SELECT symbol, date, COALESCE(iv30_cm, monthly_atm_iv) AS v FROM iv_summary_daily WHERE date < ?
                                   QUALIFY ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY date DESC) <= ? ORDER BY symbol, date""",
                          [until, RANK_WINDOW])
        for r in df.itertuples(index=False):
            if symbols is None or r.symbol in symbols:
                self.values[str(r.symbol)].append((db.to_date(r.date) or until, None if pd.isna(r.v) else float(r.v)))

    def prior(self, symbol: str, day: date) -> list[float]:
        return [v for d, v in self.values.get(symbol, []) if d < day and v is not None][-RANK_WINDOW:]

    def push(self, symbol: str, day: date, value: float | None) -> None:
        lst = self.values[symbol]
        if lst and lst[-1][0] == day:
            lst[-1] = (day, value)
        else:
            lst.append((day, value))
        if len(lst) > RANK_WINDOW + 5:
            del lst[0]


def rv_frame_stock(store: Any, symbol: str, day: date, n: int = 90) -> pd.DataFrame:
    if not db.table_exists(store, "nse_bhavcopy"):
        return pd.DataFrame(columns=["date", "open", "high", "low", "close", "prev_close"])
    df = db.query_df(store, """SELECT date, open, high, low, close, prev_close FROM nse_bhavcopy WHERE symbol = ? AND series = 'EQ' AND date <= ?
                               ORDER BY date DESC LIMIT ?""", [symbol, day, n])
    return df.sort_values("date").reset_index(drop=True)


def rv_frame_index(store: Any, symbol: str, day: date, n: int = 90) -> pd.DataFrame:
    name = INDEX_NAMES.get(symbol, symbol)
    cols = ["date", "open", "high", "low", "close", "prev_close"]
    if not db.table_exists(store, "index_ohlc_daily"):
        return pd.DataFrame(columns=cols)
    df = db.query_df(store, "SELECT date, open, high, low, close FROM index_ohlc_daily WHERE symbol = ? AND date <= ? ORDER BY date DESC LIMIT ?",
                     [name, day, n]).sort_values("date").reset_index(drop=True)
    if df.empty:
        return pd.DataFrame(columns=cols)
    df["prev_close"] = df["close"].shift(1)
    return df


class RvCache:
    """Rolling RV20 (cc / Parkinson / YZ) per symbol for a date range, computed once for a backfill (the per-day path would
    issue 224 queries per session). Same formulas as ``realised``; a test asserts they agree."""

    def __init__(self) -> None:
        self.rows: dict[str, pd.DataFrame] = {}

    @staticmethod
    def rolling(frame: pd.DataFrame, n: int = 20) -> pd.DataFrame:
        d = realised._clean(frame).reset_index(drop=True)
        if d.empty:
            return pd.DataFrame(columns=["date", "rv20_cc", "rv20_parkinson", "rv20_yz"])
        lr = np.log(d["close"] / d["prev_close"]).replace([np.inf, -np.inf], np.nan)
        cc = lr.rolling(n, min_periods=max(5, n // 2)).std(ddof=1) * realised.ANNUALISE * 100
        hl = (np.log(d["high"] / d["low"]) ** 2).where((d["high"] > 0) & (d["low"] > 0))
        park = np.sqrt(hl.rolling(n, min_periods=max(5, n // 2)).mean() / (4 * math.log(2))) * realised.ANNUALISE * 100
        o = np.log(d["open"] / d["prev_close"])
        c = np.log(d["close"] / d["open"])
        u, dn = np.log(d["high"] / d["open"]), np.log(d["low"] / d["open"])
        rs = u * (u - c) + dn * (dn - c)
        k = 0.34 / (1.34 + (n + 1) / (n - 1))
        vo = o.rolling(n, min_periods=n).var(ddof=1)
        vc = c.rolling(n, min_periods=n).var(ddof=1)
        rsm = rs.rolling(n, min_periods=n).mean()
        yz = np.sqrt((vo + k * vc + (1 - k) * rsm).clip(lower=0)) * realised.ANNUALISE * 100
        return pd.DataFrame({"date": d["date"].map(db.to_date), "rv20_cc": cc, "rv20_parkinson": park, "rv20_yz": yz})

    def load(self, store: Any, symbols: list[str], start: date, end: date) -> None:
        idx = [s for s in symbols if s in INDEX_SYMBOLS]
        stocks = [s for s in symbols if s not in INDEX_SYMBOLS]
        lo = start - pd.Timedelta(days=60).to_pytimedelta()
        if stocks and db.table_exists(store, "nse_bhavcopy"):
            df = db.query_df(store, """SELECT symbol, date, open, high, low, close, prev_close FROM nse_bhavcopy
                                       WHERE series = 'EQ' AND date >= ? AND date <= ? AND list_contains(?, symbol) ORDER BY symbol, date""",
                             [lo, end, stocks])
            for sym, g in df.groupby("symbol"):
                self.rows[str(sym)] = self.rolling(g.reset_index(drop=True))
        if idx and db.table_exists(store, "index_ohlc_daily"):
            names = [INDEX_NAMES.get(s, s) for s in idx]
            df = db.query_df(store, """SELECT symbol, date, open, high, low, close FROM index_ohlc_daily
                                       WHERE date >= ? AND date <= ? AND list_contains(?, symbol) ORDER BY symbol, date""", [lo, end, names])
            back = {v: k for k, v in INDEX_NAMES.items()}
            for name, g in df.groupby("symbol"):
                g = g.reset_index(drop=True)
                g["prev_close"] = g["close"].shift(1)
                self.rows[back.get(str(name), str(name))] = self.rolling(g)

    def get(self, symbol: str, day: date) -> dict[str, float | None]:
        df = self.rows.get(symbol)
        if df is None or df.empty:
            return {"rv20_cc": None, "rv20_parkinson": None, "rv20_yz": None}
        hit = df[df["date"] == day]
        if hit.empty:
            return {"rv20_cc": None, "rv20_parkinson": None, "rv20_yz": None}
        r = hit.iloc[-1]
        return {k: (None if pd.isna(r[k]) else round(float(r[k]), 4)) for k in ("rv20_cc", "rv20_parkinson", "rv20_yz")}


def fovolt_for(store: Any, day: date) -> dict[str, float]:
    if not db.table_exists(store, "nse_fo_volt"):
        return {}
    df = db.query_df(store, "SELECT symbol, ann_vol FROM nse_fo_volt WHERE date = ?", [day])
    return {str(r.symbol): round(float(r.ann_vol) * 100, 4) for r in df.itertuples(index=False) if r.ann_vol is not None and np.isfinite(r.ann_vol)}


def enrich(store: Any, summary: pd.DataFrame, day: date, *, history: IvHistory, rv: RvCache | None = None, per_day_rv: bool = True) -> pd.DataFrame:
    """Add rank / percentile, RV20 (three estimators), FOVOLT and IV − RV to the day's summary rows."""
    if summary.empty:
        return summary
    fov = fovolt_for(store, day)
    out = summary.copy()
    for i, row in out.iterrows():
        sym = str(row["symbol"])
        base = row["iv30_cm"] if row["iv30_cm"] is not None and not pd.isna(row["iv30_cm"]) else row["monthly_atm_iv"]
        base = None if base is None or pd.isna(base) else float(base)
        rank, pct = rank_and_percentile(history.prior(sym, day), base)
        history.push(sym, day, base)
        out.at[i, "iv_rank_252"], out.at[i, "iv_pctile_252"] = rank, pct
        if rv is not None:
            vols = rv.get(sym, day)
        elif per_day_rv:
            frame = rv_frame_index(store, sym, day) if sym in INDEX_SYMBOLS else rv_frame_stock(store, sym, day)
            vols = {k: (round(v, 4) if v is not None else None) for k, v in realised.all_three(frame).items()} if len(frame) else \
                {"rv20_cc": None, "rv20_parkinson": None, "rv20_yz": None}
        else:
            vols = {"rv20_cc": None, "rv20_parkinson": None, "rv20_yz": None}
        for k, v in vols.items():
            out.at[i, k] = v
        out.at[i, "fovolt_ann"] = fov.get(sym)
        rv20 = vols.get("rv20_cc")
        out.at[i, "iv_minus_rv20"] = round(base - rv20, 4) if (base is not None and rv20 is not None) else None
    return out


# ── write ──────────────────────────────────────────────────────────────────────────────────────────────────────────

def write_day(store: Any, res: DayResult) -> dict[str, int]:
    n_e = db.upsert(store, "iv_expiry_daily", res.expiry, COLUMNS["iv_expiry_daily"], CASTS["iv_expiry_daily"])
    n_s = db.upsert(store, "iv_surface_daily", res.surface, COLUMNS["iv_surface_daily"], CASTS["iv_surface_daily"])
    n_m = db.upsert(store, "iv_summary_daily", res.summary, COLUMNS["iv_summary_daily"], CASTS["iv_summary_daily"])
    return {"expiry_rows": n_e, "surface_rows": n_s, "summary_rows": n_m}


def run_day(store: Any, path: Path, day: date, *, surface_symbols: set[str] | None = None, symbols: set[str] | None = None,
            now: datetime | None = None, history: IvHistory | None = None, rv: RvCache | None = None) -> dict[str, Any]:
    """One cached file → the three tables (rank / RV / FOVOLT included). The EOD entry point and the backfill's inner step."""
    now = now or db.utcnow()
    r, r_src = rate_for(store, day)
    contracts = fo_files.load(path)
    res = compute_day(contracts, day, r, surface_symbols=surface_symbols, symbols=symbols, now=now, source_file=path.name,
                      legacy=fo_files.is_legacy(path))
    hist = history if history is not None else IvHistory(store, day, symbols)
    res.summary = enrich(store, res.summary, day, history=hist, rv=rv)
    written = write_day(store, res)
    logger.info("fo_iv.eod", day=day.isoformat(), symbols=res.symbols, seconds=res.seconds, r=r, r_source=r_src, **written)
    return {"date": day.isoformat(), "file": path.name, "symbols": res.symbols, "seconds": res.seconds, "r": r, "r_source": r_src,
            "flags": res.flags, **written}


def recompute_ranks(store: Any, *, symbols: list[str] | None = None) -> int:
    """The Saturday pass (``iv_weekly``): rank / percentile windows recomputed over the whole stored history after late corrections."""
    where = " WHERE list_contains(?, symbol)" if symbols else ""
    df = db.query_df(store, f"SELECT symbol, date, iv30_cm, monthly_atm_iv FROM iv_summary_daily{where} ORDER BY symbol, date", [symbols] if symbols else [])
    if df.empty:
        return 0
    updates = []
    for sym, g in df.groupby("symbol"):
        base = g["iv30_cm"].where(g["iv30_cm"].notna(), g["monthly_atm_iv"]).tolist()
        hist: list[float] = []
        for d, v in zip(g["date"], base, strict=True):
            v = None if v is None or pd.isna(v) else float(v)
            rank, pct = rank_and_percentile(hist, v)
            updates.append({"symbol": sym, "date": db.to_date(d), "iv_rank_252": rank, "iv_pctile_252": pct})
            if v is not None:
                hist.append(v)
                hist = hist[-RANK_WINDOW:]
    up = pd.DataFrame(updates)
    for start in range(0, len(up), db.BATCH_ROWS):
        chunk = up.iloc[start:start + db.BATCH_ROWS]
        store.write("""UPDATE iv_summary_daily SET iv_rank_252 = u.iv_rank_252, iv_pctile_252 = u.iv_pctile_252
                       FROM _b1_ranks u WHERE iv_summary_daily.symbol = u.symbol AND iv_summary_daily.date = u.date::DATE""",
                    frames={"_b1_ranks": chunk})
    return len(up)
