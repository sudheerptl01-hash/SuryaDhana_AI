"""Derived series (SOURCES.md §10): the India price ladder and premiums (``derive_india``, after the IBJA PM fix) and
the global arithmetic (``derive_global``, 21:30): Shanghai premium, COMEX carry, the KGX "gold or the dollar" split
with a rupee leg, gold in currencies, ratios, the GVZ sigma day, ATR14 in rupees, the OG put/call OI ratio.

Everything here is an identity over stored rows (badge ``arithmetic``) or a descriptive ratio (``context``); nothing
forecasts and nothing feeds a trade. Inputs are read as-of now through the PIT view, so a later revision of an input
appears as a new vintage of the derived row (``pit.upsert_series``).
"""
from __future__ import annotations

import math
import os
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from gold import db, mcx_close, pit
from gold.db import utcnow
from gold.ingest_india import duty_on, landed_factor, purity_factor
from shared.logging import get_logger

logger = get_logger(__name__)

GRAMS_PER_OZ = 31.1034768
DXY_WEIGHTS: dict[str, tuple[float, bool]] = {   # series → (weight share, quoted as USD per unit?)  EUR 57.6 JPY 13.6 GBP 11.9 CAD 9.1 SEK 4.2 CHF 3.6
    "FX_EURUSD": (0.576, True), "FX_JPY": (0.136, False), "FX_GBPUSD": (0.119, True), "FX_CAD": (0.091, False),
    "FX_SEK": (0.042, False), "FX_CHF": (0.036, False),
}
CARRY_RATE_PCT = float(os.getenv("GOLD_MCX_CARRY_RATE_PCT", "6.5"))      # rupee funding + storage, p.a. (M8)


def _env_duty() -> tuple[date, float] | None:
    pct, eff = os.getenv("GOLD_IMPORT_DUTY_PCT", "").strip(), os.getenv("GOLD_IMPORT_DUTY_EFFECTIVE", "").strip()
    if not pct or not eff:
        return None
    try:
        return date.fromisoformat(eff), float(pct)
    except ValueError:
        return None


def _bars(store: Any, symbol: str, days: int, now: datetime | None = None) -> pd.DataFrame:
    """Bars in the ``days`` window ending at ``now`` (the run's as-of instant, so a replay with ``now`` sees what it saw)."""
    return db.query_df(store, """
        SELECT trade_date, open, high, low, close FROM gold_daily_bars
        WHERE symbol = ? AND trade_date >= ? ORDER BY trade_date""", [symbol, (now or utcnow()).date() - timedelta(days=days)])


def _series(store: Any, sid: str, days: int, asof: datetime | None = None, now: datetime | None = None) -> pd.Series:
    df = pit.asof_series(store, [sid], start=(now or utcnow()).date() - timedelta(days=days), asof=asof)
    if df.empty:
        return pd.Series(dtype="float64")
    s = pd.Series(df["value"].to_numpy(dtype="float64"), index=pd.to_datetime(df["report_date"]))
    return s[~s.index.duplicated(keep="last")].sort_index()


def _align(*series: pd.Series, how: str = "inner") -> pd.DataFrame:
    return pd.concat(series, axis=1, join=how)


def _frame(sid: str, s: pd.Series, *, now: datetime, quality: str = "derived") -> pd.DataFrame:
    pts = [(d.date(), float(v)) for d, v in s.dropna().items() if math.isfinite(float(v))]
    return pit.series_frame(sid, pts, freq="D", source="derived", quality=quality, now=now)


# ── derive_india (M5–M8, ATR14) ─────────────────────────────────────────────────────────────────────

def derive_india(store: Any, *, now: datetime | None = None, days: int = 400) -> dict[str, Any]:
    """Landed ₹/10 g of FINE gold, duty-paid landed, the India premium (IBJA 999 PM vs duty-paid × 0.999), the MCX basis
    vs duty-paid landed × 0.995 (the GOLD front settlement of each session: VWAP30 proxy, else the re-keyed band midpoint;
    quality ``derived_vwap30`` / ``derived_band``), the carry-adjusted basis, ATR14 in ₹/10 g (from COMEX H/L/C × INR).
    Purity (PM decision D1): landed is per fine gold; purity P compares with landed × P / 1000 (``ingest_india``)."""
    now = now or utcnow()
    gc = _bars(store, "GC=F", days, now).set_index("trade_date")
    inr_bars = _bars(store, "INR=X", days, now).set_index("trade_date")["close"] if not _bars(store, "INR=X", 5, now).empty else pd.Series(dtype="float64")
    if gc.empty:
        return {"status": "no_inputs", "inserted": 0, "reason": "gold_daily_bars has no GC=F rows yet"}
    gc.index, inr_bars.index = pd.to_datetime(gc.index), pd.to_datetime(inr_bars.index)
    fbil = _series(store, "USDINR_FBIL", days, now=now)
    inr = fbil.combine_first(inr_bars) if not fbil.empty else inr_bars
    frames: list[pd.DataFrame] = []
    if inr.empty:
        return {"status": "no_inputs", "inserted": 0, "reason": "no USD/INR series (INR=X bars or USDINR_FBIL)"}
    j = _align(gc["close"].rename("gc"), inr.rename("inr"))
    landed = j["gc"] * j["inr"] / GRAMS_PER_OZ * 10.0
    extra = _env_duty()
    duty = pd.Series([duty_on(d.date(), extra)[0] for d in landed.index], index=landed.index)
    duty_paid = landed * (1.0 + duty / 100.0)
    frames += [_frame("GOLD_INR_LANDED", landed.round(0), now=now), _frame("GOLD_INR_DUTY_PAID", duty_paid.round(0), now=now),
               _frame("GOLD_IN_INR", landed.round(0), now=now)]
    ibja = _series(store, "IBJA_999_PM", days, now=now)
    if not ibja.empty:
        k = _align(ibja.rename("ibja"), duty_paid.rename("dp"))
        prem = (k["ibja"] / (k["dp"] * purity_factor(999)) - 1.0) * 100.0          # D1: IBJA 999 vs fine landed × 0.999
        frames.append(_frame("INDIA_PREMIUM_PCT", prem.round(3), now=now))
    # wave 1d: the GOLD front settlement of EACH session (Breeze VWAP30 proxy, else the band midpoint re-keyed to the
    # session it belongs to — the master's band is one session older than its OI), divided by THAT session's duty-paid
    # landed price at the contract's purity (D1: GOLD is 995 fine → fine landed × 0.995; ingest_india.landed_factor)
    front = mcx_close.session_settlements(store, "GOLD", asof=now)
    if not front.empty:
        f = front.set_index(pd.to_datetime(front["session"]))
        factor, _ref = landed_factor("GOLD")
        k = _align(f["settle"].rename("mcx"), (duty_paid * factor).rename("dp"))
        basis = (k["mcx"] / k["dp"] - 1.0) * 100.0
        src = f["source"].reindex(k.index)
        for source, quality in (("breeze_vwap30", "derived_vwap30"), ("band_midpoint", "derived_band")):
            mask = src == source
            frames.append(_frame("MCX_BASIS_PCT", basis[mask].round(3), now=now, quality=quality))
        dte = pd.Series([(pd.Timestamp(e) - d).days for d, e in zip(f.index, f["expiry"])], index=f.index).reindex(k.index)
        carry = CARRY_RATE_PCT * dte / 365.0
        for source, quality in (("breeze_vwap30", "derived_vwap30"), ("band_midpoint", "derived_band")):
            mask = src == source
            frames.append(_frame("MCX_BASIS_CARRY_ADJ_PCT", (basis - carry)[mask].round(3), now=now, quality=quality))
    if len(gc) >= 15:
        h, lo, c = gc["high"] * j["inr"] / GRAMS_PER_OZ * 10.0, gc["low"] * j["inr"] / GRAMS_PER_OZ * 10.0, landed
        prev_c = c.shift(1)
        tr = pd.concat([(h - lo), (h - prev_c).abs(), (lo - prev_c).abs()], axis=1).max(axis=1)
        frames.append(_frame("ATR14_INR", tr.rolling(14).mean().round(0), now=now))
    out = _write(store, frames, now)
    out["duty_pct"] = float(duty.iloc[-1]) if len(duty) else None
    return out


# ── derive_global (M9, M31, M42, M56, M57, M60, M36) ───────────────────────────────────────────────

def derive_global(store: Any, *, now: datetime | None = None, days: int = 400) -> dict[str, Any]:
    now = now or utcnow()
    frames: list[pd.DataFrame] = []
    gc = _bars(store, "GC=F", days, now)
    if gc.empty:
        return {"status": "no_inputs", "inserted": 0, "reason": "gold_daily_bars has no GC=F rows yet"}
    g = pd.Series(gc["close"].to_numpy(dtype="float64"), index=pd.to_datetime(gc["trade_date"]))
    # ratios
    for sym, sid in (("SI=F", "GSR"), ("PL=F", "GPR_RATIO")):
        o = _bars(store, sym, days, now)
        if not o.empty:
            s = pd.Series(o["close"].to_numpy(dtype="float64"), index=pd.to_datetime(o["trade_date"]))
            frames.append(_frame(sid, (_align(g.rename("g"), s.rename("s"))["g"] / _align(g.rename("g"), s.rename("s"))["s"]).round(3), now=now))
    # gold in currencies
    fx: dict[str, pd.Series] = {}
    for sym, sid in (("EURUSD=X", "FX_EURUSD"), ("JPY=X", "FX_JPY"), ("GBPUSD=X", "FX_GBPUSD"), ("CAD=X", "FX_CAD"), ("SEK=X", "FX_SEK"),
                     ("CHF=X", "FX_CHF"), ("CNY=X", "FX_CNY")):
        o = _bars(store, sym, days, now)
        if not o.empty:
            fx[sid] = pd.Series(o["close"].to_numpy(dtype="float64"), index=pd.to_datetime(o["trade_date"]))
    for sid, ccy, per_unit in (("FX_EURUSD", "EUR", True), ("FX_JPY", "JPY", False), ("FX_GBPUSD", "GBP", True)):
        if sid in fx:
            k = _align(g.rename("g"), fx[sid].rename("f"))
            frames.append(_frame(f"GOLD_IN_{ccy}", (k["g"] / k["f"] if per_unit else k["g"] * k["f"]).round(2), now=now))
    if "FX_CNY" in fx:
        k = _align(g.rename("g"), fx["FX_CNY"].rename("f"))
        frames.append(_frame("GOLD_IN_CNY", (k["g"] * k["f"] / GRAMS_PER_OZ).round(3), now=now))
    # KGX: usd_effect = Σ wᵢ Δln(fᵢ in USD terms); pure = gold − usd_effect; rupee leg = Δln(USDINR)
    if all(k in fx for k in DXY_WEIGHTS):
        usd_terms = {sid: (fx[sid] if per_unit else 1.0 / fx[sid]) for sid, (_, per_unit) in DXY_WEIGHTS.items()}
        k = _align(*[s.rename(sid) for sid, s in usd_terms.items()], g.rename("g"))
        dln = k.apply(lambda col: (col / col.shift(1)).map(math.log) if col.name != "g" else col)
        usd_effect = sum(DXY_WEIGHTS[sid][0] * dln[sid] for sid in DXY_WEIGHTS) * 100.0
        total = (k["g"] / k["g"].shift(1)).map(math.log) * 100.0
        frames.append(_frame("KGX_USD_EFFECT_PCT", usd_effect.round(3), now=now))
        frames.append(_frame("KGX_PURE_GOLD_PCT", (total - usd_effect).round(3), now=now))
    inr = _bars(store, "INR=X", days, now)
    if not inr.empty:
        s = pd.Series(inr["close"].to_numpy(dtype="float64"), index=pd.to_datetime(inr["trade_date"]))
        frames.append(_frame("KGX_INR_EFFECT_PCT", ((s / s.shift(1)).map(math.log) * 100.0).round(3), now=now))
    # GVZ sigma day
    gvz = _bars(store, "^GVZ", days, now)
    if not gvz.empty:
        s = pd.Series(gvz["close"].to_numpy(dtype="float64"), index=pd.to_datetime(gvz["trade_date"]))
        frames.append(_frame("GVZ_SIGMA_DAY_PCT", (s / math.sqrt(252.0)).round(3), now=now))
    # Shanghai premium: SGE PM (CNY/g) × 31.1035 ÷ USDCNY − LBMA PM (fallback: GC close same date)
    sge = _series(store, "SGE_SHAU_PM", days, now=now)
    if not sge.empty and "FX_CNY" in fx:
        ref = _series(store, "LBMA_PM_USD", days, now=now)
        base = ref if not ref.empty else g
        k = _align(sge.rename("sge"), fx["FX_CNY"].rename("cny"), base.rename("ref"))
        usd_oz = k["sge"] * GRAMS_PER_OZ / k["cny"]
        frames.append(_frame("SHANGHAI_PREMIUM_USD", (usd_oz - k["ref"]).round(2), now=now, quality="derived"))
        frames.append(_frame("SHANGHAI_PREMIUM_PCT", ((usd_oz / k["ref"] - 1.0) * 100.0).round(3), now=now, quality="derived"))
    # COMEX carry front → next from the stored curve (Yahoo last trade until bulletin settlements are allowed)
    curve = db.query_df(store, """
        SELECT trade_date, expiry, COALESCE(settle, close) AS px FROM gold_curve
        WHERE exchange = 'COMEX' AND symbol = 'GC' AND expiry > trade_date AND COALESCE(settle, close) IS NOT NULL
        ORDER BY trade_date, expiry""")
    if not curve.empty:
        pts = []
        for d, grp in curve.groupby("trade_date"):
            if len(grp) >= 2:
                f1, f2 = grp.iloc[0], grp.iloc[1]
                dd = (pd.Timestamp(f2["expiry"]) - pd.Timestamp(f1["expiry"])).days
                if dd > 0 and f1["px"]:
                    pts.append((db.to_date(d), round((float(f2["px"]) / float(f1["px"]) - 1.0) * 365.0 / dd * 100.0, 3)))
        frames.append(pit.series_frame("COMEX_CARRY_ANN_PCT", pts, freq="D", source="derived", quality="derived", now=now))
    # OG put/call OI ratio
    pc = db.query_df(store, """
        SELECT trade_date, MAX(CASE WHEN fut_or_opt = 'P' THEN open_interest END) AS p,
               MAX(CASE WHEN fut_or_opt = 'C' THEN open_interest END) AS c
        FROM gold_cme_daily_voi WHERE product_code = 'OG' GROUP BY trade_date ORDER BY trade_date""")
    if not pc.empty:
        pts = [(db.to_date(r.trade_date), round(float(r.p) / float(r.c), 4)) for r in pc.itertuples(index=False) if r.p and r.c]
        frames.append(pit.series_frame("COMEX_GC_OI_PUTCALL", pts, freq="D", source="derived", quality="derived", now=now))
    return _write(store, frames, now)


def _write(store: Any, frames: list[pd.DataFrame], now: datetime) -> dict[str, Any]:
    frames = [f for f in frames if f is not None and not f.empty]
    if not frames:
        return {"status": "no_inputs", "inserted": 0}
    df = pd.concat(frames, ignore_index=True)
    res = pit.upsert_series(store, df, now=now)
    return {"status": "ok", **res, "series": sorted(df["series_id"].unique().tolist())}
