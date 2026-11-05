"""Black-76 on an undiscounted forward (R-IV §4.1; the prototype's math, ``r`` passed explicitly so every row records it).

``MODEL_VERSION`` names the whole convention: Black-76 on the parity forward, T = calendar days / 365 at the 15:30 close
(no half day), price = ``ClsPric`` only when traded, OTM wings plus 3 % ITM, ATM interpolated at the forward in strike,
25Δ / 10Δ by inverting each strike's own delta, constant maturity by variance interpolation. A change to any of these
is a new ``MODEL_VERSION`` and re-derives into new rows (PLAN §0.3).
"""
from __future__ import annotations

import math

MODEL_VERSION = "b76-pcp-v1"
IV_LO, IV_HI = 1e-3, 5.0            # bisection bounds (annualised)
IV_MIN, IV_MAX = 0.01, 4.0          # outside: no IV (a stale or crossed price)
INTRINSIC_PAD = 0.05                # price must exceed intrinsic by this (₹) to carry time value
ITM_BAND = 0.03                     # calls for K ≥ 0.97 F, puts for K ≤ 1.03 F


def ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def npdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def price(f: float, k: float, t: float, vol: float, call: bool, r: float) -> float:
    """Black-76 premium of a European option on forward ``f`` (discounted at ``r``)."""
    if t <= 0 or vol <= 0:
        return max(0.0, (f - k) if call else (k - f)) * math.exp(-r * t)
    sq = vol * math.sqrt(t)
    d1 = (math.log(f / k) + 0.5 * vol * vol * t) / sq
    d2 = d1 - sq
    df = math.exp(-r * t)
    return df * ((f * ncdf(d1) - k * ncdf(d2)) if call else (k * ncdf(-d2) - f * ncdf(-d1)))


def implied_vol(premium: float | None, f: float, k: float, t: float, call: bool, r: float) -> float | None:
    """Bisection on Black-76; ``None`` when the premium is outside the no-arbitrage band or the vol is outside (IV_MIN, IV_MAX)."""
    if premium is None or premium <= 0 or t <= 0 or f <= 0 or k <= 0:
        return None
    df = math.exp(-r * t)
    intrinsic = df * max(0.0, (f - k) if call else (k - f))
    if premium <= intrinsic + INTRINSIC_PAD or premium >= df * (f if call else k):
        return None
    lo, hi = IV_LO, IV_HI
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if price(f, k, t, mid, call, r) > premium:
            hi = mid
        else:
            lo = mid
    v = 0.5 * (lo + hi)
    return v if IV_MIN < v < IV_MAX else None


def delta(f: float, k: float, t: float, vol: float, call: bool, r: float) -> float:
    """Black-76 delta w.r.t. the forward (discounted), the convention NSE's Contract_Delta uses for its factor."""
    if t <= 0 or vol <= 0:
        itm = (f > k) if call else (f < k)
        return math.exp(-r * t) * ((1.0 if itm else 0.0) if call else (-1.0 if itm else 0.0))
    d1 = (math.log(f / k) + 0.5 * vol * vol * t) / (vol * math.sqrt(t))
    return math.exp(-r * t) * (ncdf(d1) if call else ncdf(d1) - 1.0)


def vega(f: float, k: float, t: float, vol: float, r: float) -> float:
    """Premium change per 1.00 of vol (divide by 100 for per vol-point)."""
    if t <= 0 or vol <= 0:
        return 0.0
    d1 = (math.log(f / k) + 0.5 * vol * vol * t) / (vol * math.sqrt(t))
    return math.exp(-r * t) * f * npdf(d1) * math.sqrt(t)


def forward_from_parity(k: float, call_px: float, put_px: float, t: float, r: float) -> float:
    """F = K + (C − P)·e^{rT}: the put-call-parity forward at a strike where both sides traded."""
    return k + (call_px - put_px) * math.exp(r * t)


def cm_variance_interp(near_dte: float, near_iv: float, far_dte: float, far_iv: float, target_days: float) -> float | None:
    """VIX-style constant-maturity interpolation of ATM *variance* between the expiries bracketing ``target_days``."""
    if not (near_dte < target_days <= far_dte) and not (near_dte <= target_days < far_dte):
        return None
    ta, tb, tt = near_dte / 365.0, far_dte / 365.0, target_days / 365.0
    if tb <= ta:
        return None
    va, vb = (near_iv ** 2) * ta, (far_iv ** 2) * tb
    w = (tb - tt) / (tb - ta)
    var = (va * w + vb * (1.0 - w)) / tt
    return math.sqrt(max(var, 0.0))
