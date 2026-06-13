"""Phase 4 / audit §3.5 — regime-adaptive filter gating.

Extends the existing causal 2-state Gaussian HMM (and the SMA fallback) from a *sizing*
throttle into a *filter-set selector*. A mean-reversion / dip-buying filter (RSI<35,
52w-low pullback, intention_pullback, below-MA pullback) is *toxic* in a crash (you catch
a falling knife) and equally toxic in an expansionary breakout (you fade the trend). When
the regime posterior signals CRASH or BREAKOUT, the mean-reversion filters are removed
from the active screen for that bar while trend / momentum / breakout filters stay live.

§3.5 regime map (from the causal P(bull | 𝓕ₜ) posterior):
    P(bull) > 0.60                       → BREAKOUT / expansionary  (disable mean-reversion)
    P(bull) < 0.40                       → CRASH / risk-off         (disable mean-reversion)
    0.40 ≤ P(bull) ≤ 0.60                → NEUTRAL / range          (all filters active)

Design (zero-regression, modular):
  • Pure, side-effect-free. Owns NO engine/analytics state.
  • Gate is consulted ONLY when `regime_filter=True` (same flag that already enables the
    sizing throttle); otherwise it never runs and behaviour is identical to today.
  • Every function degrades to "all filters active" (the legacy behaviour) on any
    degenerate input — never raises into the candidate-selection hot path. The analytics
    caller additionally wraps it in try/except (mirrors the membership_pit=False pattern).

The classification is OP- and VALUE-aware: a numeric field is mean-reverting only in its
dip-buying *direction* (e.g. `rsi_14 < 35` is mean-reversion; `rsi_14 > 70` is momentum),
so a momentum use of the same field is never mistakenly disabled.
"""
from __future__ import annotations

from typing import Optional

# Regime labels.
BREAKOUT = "breakout"     # expansionary / strong-trend
CRASH = "crash"           # risk-off / drawdown
NEUTRAL = "neutral"       # range / transitional

# §3.5 posterior thresholds.
BULL_HI = 0.60
BULL_LO = 0.40

# Regimes in which mean-reversion (dip-buying) filters are TOXIC and get disabled.
_MEAN_REVERSION_TOXIC_REGIMES = frozenset({CRASH, BREAKOUT})

# Boolean filters that are inherently mean-reverting (buy a dip / fade weakness).
_MEAN_REVERSION_BOOL: frozenset = frozenset({
    "intention_pullback",     # high close-location value DURING a 3-day price dip (dip-buy)
})

# Numeric filters that are mean-reverting only in a specific direction. Maps
# field → the set of comparison ops that make it a dip-buy. RSI below a low threshold,
# price near the 52-week low, or price below its 200d MA are all "buy the weakness".
_MEAN_REVERSION_NUMERIC: dict = {
    "rsi_14": {"lt", "lte"},            # RSI<35 oversold dip-buy (vs RSI>70 momentum)
    "above_52w_low_pct": {"lt", "lte"},  # close hugging the 52-week low (pullback)
    "dist_ma200_pct": {"lt", "lte"},     # close below the 200d MA (mean-revert to MA)
}

# Explicit trend / momentum / breakout filters that must STAY active in trending regimes.
# (Documented for clarity / audit; the gate keeps anything not classified mean-reverting,
# so this set is the positive complement and is asserted in tests.)
TREND_MOMENTUM_FILTERS: frozenset = frozenset({
    "price_gt_ma50", "price_gt_ma200", "ma50_gt_ma200", "volume_gt_avg",
    "vipt_breakout", "squeeze_on", "sector_positive_regime", "decoupled_leader",
    "within_52w_high_pct", "sector_rel_mom_14_pct",
})


def classify_regime(
    p_bull: Optional[float] = None,
    *,
    regime_ok: Optional[bool] = None,
) -> str:
    """Map a causal regime signal to a {breakout, crash, neutral} label (§3.5).

    Prefers the HMM/GMM posterior `p_bull` ∈ [0,1] when available (BREAKOUT>0.6,
    CRASH<0.4, else NEUTRAL). Falls back to the boolean SMA gate `regime_ok` (True ⇒
    BREAKOUT, False ⇒ CRASH) when no posterior is given. Returns NEUTRAL on degenerate
    input so the gate is inert (all filters active) — never raises.
    """
    try:
        if p_bull is not None:
            p = float(p_bull)
            if p != p:  # NaN
                return NEUTRAL
            if p > BULL_HI:
                return BREAKOUT
            if p < BULL_LO:
                return CRASH
            return NEUTRAL
    except (TypeError, ValueError):
        return NEUTRAL
    if regime_ok is not None:
        return BREAKOUT if bool(regime_ok) else CRASH
    return NEUTRAL


def is_mean_reversion_filter(fc: dict) -> bool:
    """True iff a single filter clause is a mean-reversion (dip-buying) screen.

    Boolean dip-buy filters are unconditional; numeric fields are mean-reverting only in
    their dip-buy comparison direction (e.g. rsi_14 with op in {lt, lte}). Never raises.
    """
    try:
        field = fc.get("field")
    except AttributeError:
        return False
    if field in _MEAN_REVERSION_BOOL:
        return True
    if field in _MEAN_REVERSION_NUMERIC:
        op = str(fc.get("op", "gt")).lower()
        return op in _MEAN_REVERSION_NUMERIC[field]
    return False


def active_filters_for_regime(filters: list, regime: str) -> tuple[list, list]:
    """Return (active_filters, disabled_filters) for the given regime (§3.5).

    In a CRASH or BREAKOUT regime the mean-reversion clauses are removed (they are toxic
    in a trending tape — catching a falling knife or fading a breakout). In NEUTRAL all
    filters stay active. Trend / momentum / breakout filters are NEVER disabled. The input
    order of the surviving clauses is preserved. Never raises; on any error returns the
    original list unchanged (legacy behaviour).
    """
    try:
        if not filters or regime not in _MEAN_REVERSION_TOXIC_REGIMES:
            return list(filters or []), []
        active, disabled = [], []
        for fc in filters:
            if is_mean_reversion_filter(fc):
                disabled.append(fc)
            else:
                active.append(fc)
        return active, disabled
    except Exception:
        return list(filters or []), []


def gate_filters(
    filters: list,
    *,
    p_bull: Optional[float] = None,
    regime_ok: Optional[bool] = None,
    enabled: bool = True,
) -> dict:
    """Top-level safe entry point used by the analytics candidate loop.

    Returns a dict: {regime, active, disabled, gated}. When `enabled` is False (the
    `regime_filter=False` default) the gate is a no-op: every filter stays active and
    `gated=False`. Never raises — on any failure it falls back to all-filters-active.
    """
    if not enabled:
        return {"regime": NEUTRAL, "active": list(filters or []), "disabled": [],
                "gated": False}
    try:
        regime = classify_regime(p_bull, regime_ok=regime_ok)
        active, disabled = active_filters_for_regime(filters, regime)
        return {"regime": regime, "active": active, "disabled": disabled,
                "gated": bool(disabled)}
    except Exception:
        return {"regime": NEUTRAL, "active": list(filters or []), "disabled": [],
                "gated": False}
