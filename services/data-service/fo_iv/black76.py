"""Black-76 on an undiscounted forward (R-IV §4.1; the prototype's math, ``r`` passed explicitly so every row records it).

``MODEL_VERSION`` names the whole convention: Black-76 on the parity forward, T = calendar days / 365 at the 15:30 close
(no half day), price = ``ClsPric`` only when traded, OTM wings plus 3 % ITM, ATM interpolated at the forward in strike,
25Δ / 10Δ by inverting each strike's own delta, constant maturity by variance interpolation. A change to any of these
is a new ``MODEL_VERSION``: the derived IV tables are recomputed and keep the latest computation per key with its
``model_version`` (PLAN §0.3 as amended 5 Nov 2026; older vintages are recomputed from the archived source files).
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import date, datetime, time, timedelta, timezone

MODEL_VERSION = "b76-pcp-v1"
IV_LO, IV_HI = 1e-3, 5.0            # bisection bounds (annualised)
IV_MIN, IV_MAX = 0.01, 4.0          # outside: no IV (a stale or crossed price)
INTRINSIC_PAD = 0.05                # price must exceed intrinsic by this (₹) to carry time value
ITM_BAND = 0.03                     # calls for K ≥ 0.97 F, puts for K ≤ 1.03 F
PCP_FUTURE_TOL = 0.005              # the parity forward is replaced by the matching future beyond 0.5 %

# M04 (review 5 Nov 2026): ONE time-to-expiry convention app-wide — the IV store's, unchanged, so no MODEL_VERSION bump and
# no recompute. T = calendar time from the valuation instant to 15:30 IST on the expiry day ÷ 365 days. At end of day the
# valuation instant is the session's own 15:30 IST close, so T = (expiry − session date) calendar days ÷ 365 exactly (the
# store, the EOD chain, the chain Greeks and OSTR); an intraday snapshot (the live chain, the 15-minute pilot) values at its
# own clock, so T is fractional and reaches 0 at 15:30 on expiry day. No half-day for the expiry session (the old chain's
# +0.5/365 and OSTR's +0.5 day are retired: they made one expiry print two ATM IVs).
TIME_CONVENTION = "cal365-1530"
TIME_CONVENTION_NOTE = ("T = calendar time to 15:30 IST on the expiry day ÷ 365 (end of day: whole days from the session's 15:30 close; "
                        "intraday: from the snapshot clock); no half-day")
IST = timezone(timedelta(hours=5, minutes=30))
CLOSE_IST = time(15, 30)
YEAR_SECONDS = 365.0 * 86400.0


def t_years(expiry: date, valuation: date | datetime) -> float:
    """Years to expiry under ``TIME_CONVENTION``: a ``date`` values at that session's 15:30 close (whole calendar days); a
    ``datetime`` (naive = IST) values at that instant. Never negative."""
    if isinstance(valuation, datetime):
        v = valuation.astimezone(IST).replace(tzinfo=None) if valuation.tzinfo else valuation
        secs = (datetime.combine(expiry, CLOSE_IST) - v).total_seconds()
        return max(0.0, secs / YEAR_SECONDS)
    return max(0, (expiry - valuation).days) / 365.0


def choose_forward(pairs: Mapping[float, tuple[float | None, float | None]], s_ref: float, t: float, r: float, fut: float | None,
                   *, tol: float = PCP_FUTURE_TOL) -> tuple[float, str, list[str]]:
    """The store's forward rule, shared by ``iv_eod`` and the OMON chain so one expiry has one forward: put-call parity at the
    first of the three strikes nearest ``s_ref`` where both sides traded; the matching-month future instead when the two
    differ by more than ``tol``; the future when no parity pair exists; else spot·e^{rT}. ``pairs``: strike → (call, put)
    traded prices (None = untraded). Returns (forward, source 'pcp' | 'future' | 'spot', flags)."""
    flags: list[str] = []
    fwd: float | None = None
    src = "spot"
    for k in sorted(pairs, key=lambda k: abs(k - s_ref))[:3]:
        cpx, ppx = pairs[k]
        if cpx is not None and ppx is not None:
            fwd, src = forward_from_parity(k, cpx, ppx, t, r), "pcp"
            break
    if fwd is not None and fut is not None and abs(fwd / fut - 1.0) > tol:
        fwd, src = fut, "future"
        flags.append("pcp_fallback_future")
    if fwd is None:
        if fut is not None:
            fwd, src = fut, "future"
        else:
            fwd, src = s_ref * math.exp(r * t), "spot"
            flags.append("forward_from_spot")
    return float(fwd), src, flags


def strike_ivs(pairs: Mapping[float, tuple[float | None, float | None]], fwd: float, t: float, r: float
               ) -> dict[float, tuple[float, float | None, float | None]]:
    """Per strike (mean, call IV, put IV): calls for K ≥ (1 − ITM_BAND)·F, puts for K ≤ (1 + ITM_BAND)·F, traded prices only."""
    out: dict[float, tuple[float, float | None, float | None]] = {}
    for k, (cpx, ppx) in pairs.items():
        civ = implied_vol(cpx, fwd, k, t, True, r) if (cpx is not None and k >= fwd * (1 - ITM_BAND)) else None
        piv = implied_vol(ppx, fwd, k, t, False, r) if (ppx is not None and k <= fwd * (1 + ITM_BAND)) else None
        vals = [v for v in (civ, piv) if v]
        if vals:
            out[k] = (sum(vals) / len(vals), civ, piv)
    return out


def atm_iv_at_forward(strikes: Sequence[float], ivs: Sequence[float], fwd: float) -> float | None:
    """ATM IV interpolated linearly in strike at the forward (clamped at the ends, the store's ``np.interp``)."""
    pts = sorted(zip(strikes, ivs, strict=True))
    if not pts:
        return None
    if fwd <= pts[0][0]:
        return float(pts[0][1])
    if fwd >= pts[-1][0]:
        return float(pts[-1][1])
    for (k0, v0), (k1, v1) in zip(pts, pts[1:], strict=False):
        if k0 <= fwd <= k1:
            return float(v0 + (v1 - v0) * ((fwd - k0) / (k1 - k0) if k1 > k0 else 0.0))
    return None


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
