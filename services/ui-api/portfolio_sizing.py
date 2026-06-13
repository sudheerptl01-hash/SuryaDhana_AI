"""Phase 4 / audit §3.3 — dynamic capital allocation.

Replaces the engine's flat equal-weight book (`base = NAV / max_positions`) with
**inverse-volatility / risk-parity** position weights, an optional **portfolio
volatility target**, and **fractional-Kelly** sizing of the *book gross* (not just a
per-bet cap). Liquidity-capped so a weight can never exceed what the name's ADV can
absorb.

Design (zero-regression, modular):
  • This module is a *pure*, side-effect-free unit. It computes a per-ticker target
    NAV weight for the slate of names entering on a single bar. It owns NONE of the
    engine's state, caps, impact, or exit logic — those continue to apply downstream
    exactly as before.
  • `sizing_mode="equal"` reproduces the legacy `1/max_positions` weight bit-for-bit,
    so the default path is unchanged.
  • `compute_slate_weights` never raises on degenerate input (NaN/0/∞ σ, empty slate);
    it degrades to equal-weight. The engine additionally wraps the call in try/except
    and falls back to legacy sizing on ANY failure — mirroring the `membership_pit=False`
    graceful-degradation pattern used elsewhere in the backtest.

Math (audit §3.3):
    Risk parity (inverse-vol):   wᵢ = (1/σᵢ) / Σⱼ(1/σⱼ)
    Liquidity cap:               wᵢ ≤ min(w_cap, φ·ADVᵢ / NAV)
    Vol target:                  scale the weight vector by min(σ_target/σ_port, 1)
                                 where σ_port ≈ √(wᵀΣw); with no covariance we use the
                                 conservative independent-name proxy σ_port = √(Σ wᵢ²σᵢ²)
    Fractional Kelly (book):     gross = clip(κ·f*, 0, 1),  f* = W − (1−W)/R
                                 applied as a multiplier on the whole weight vector so
                                 Kelly sizes the *book*, capped at fully-invested.
"""
from __future__ import annotations

from typing import Optional, Sequence

import numpy as np

# ── Locked institutional bounds (CLAUDE.md "Trading Rules") ──────────────────────
MAX_POSITION_WEIGHT: float = 0.15      # ≤15% of NAV per stock (hard cap)
# Default liquidity participation used when a per-name ADV cap is not otherwise set;
# φ = fraction of a name's ADV a single position may represent.
DEFAULT_LIQUIDITY_PHI: float = 0.10
# Per-name vol-target scale bounds (mirror the engine's existing [0.25×, 2.5×] clamp so
# behaviour is continuous with the legacy `vol_target_pct` per-bet path).
_VOL_SCALE_LO, _VOL_SCALE_HI = 0.25, 2.5
# Half-Kelly is the institutional norm (full Kelly's variance is ruinous at scale).
DEFAULT_KELLY_KAPPA: float = 0.5
_KELLY_KAPPA_CAP: float = 0.5          # never deploy more than half-Kelly

_VALID_MODES = ("equal", "risk_parity", "vol_target")


def _clean_sigma(sigmas: Sequence[Optional[float]]) -> np.ndarray:
    """Coerce a slate's σ (ATR%) inputs to a finite, strictly-positive array.

    Degenerate entries (None/NaN/≤0/∞) are replaced by the slate's *median* finite σ so
    one bad name cannot blow up the inverse-vol normaliser; if no σ is finite the array
    is all-ones (⇒ equal-weight). Never raises.
    """
    arr = np.array(
        [float(s) if s is not None else np.nan for s in sigmas],
        dtype=float,
    )
    arr = np.where(np.isfinite(arr) & (arr > 0), arr, np.nan)
    finite = arr[np.isfinite(arr)]
    fill = float(np.median(finite)) if finite.size else 1.0
    if not np.isfinite(fill) or fill <= 0:
        fill = 1.0
    arr = np.where(np.isfinite(arr), arr, fill)
    return arr


def kelly_book_gross(
    win_rate: float,
    payoff_ratio: float,
    kappa: float = DEFAULT_KELLY_KAPPA,
) -> float:
    """Fractional-Kelly gross-exposure multiplier (audit §3.3), strictly bounded.

        f* = W − (1−W)/R           (W = win rate, R = avg win / |avg loss|)
        gross = clip(min(κ, ½)·f*, 0, 1)

    κ is hard-capped at ½ (half-Kelly) regardless of the caller's value — full Kelly's
    variance is ruinous at scale. A non-positive edge ⇒ 0 (stand down). Never raises;
    returns a fraction in [0, 1].
    """
    try:
        W = float(win_rate)
        R = float(payoff_ratio)
        k = min(abs(float(kappa)), _KELLY_KAPPA_CAP)
    except (TypeError, ValueError):
        return 1.0  # degrade to fully-invested (legacy) on garbage input
    if not (np.isfinite(W) and np.isfinite(R)) or R <= 1e-9 or W <= 0.0 or W >= 1.0:
        return 1.0
    f_star = W - (1.0 - W) / R
    if not np.isfinite(f_star) or f_star <= 0.0:
        return 0.0
    return float(np.clip(k * f_star, 0.0, 1.0))


def compute_slate_weights(
    sigmas: Sequence[Optional[float]],
    *,
    sizing_mode: str = "equal",
    max_positions: int = 5,
    nav: float = 0.0,
    advs: Optional[Sequence[Optional[float]]] = None,
    vol_target_pct: Optional[float] = None,
    liquidity_phi: float = DEFAULT_LIQUIDITY_PHI,
    max_position_weight: float = MAX_POSITION_WEIGHT,
    kelly_gross: float = 1.0,
) -> np.ndarray:
    """Per-name target NAV weights for a slate of concurrent candidates (audit §3.3).

    Returns a float array `w` of the same length as `sigmas`, where `wᵢ` is candidate i's
    target allocation as a fraction of NAV. The engine multiplies `wᵢ · NAV` to get the
    base allocation, then applies its own ADV / sector / cash caps and impact downstream.

    `sizing_mode`:
      • "equal"       — wᵢ = 1/max_positions  (legacy, bit-for-bit).
      • "risk_parity" — wᵢ ∝ 1/σᵢ, normalised over the slate (inverse-vol budget).
      • "vol_target"  — risk-parity weights, then the whole vector scaled by
                        min(σ_target/σ_port, 1) so the book targets `vol_target_pct`.

    All modes then apply, in order: the per-name liquidity cap (φ·ADVᵢ/NAV) and the hard
    `max_position_weight`, renormalise so capped weight redistributes, and finally scale
    the whole vector by `kelly_gross` (the fractional-Kelly book multiplier). Never raises.
    """
    n = len(sigmas)
    if n == 0:
        return np.array([], dtype=float)

    mode = sizing_mode if sizing_mode in _VALID_MODES else "equal"
    eq = 1.0 / float(max(int(max_positions), 1))

    if mode == "equal":
        # Bit-for-bit legacy: every concurrent slot gets 1/max_positions of NAV.
        return np.full(n, eq, dtype=float)

    sig = _clean_sigma(sigmas)
    # Inverse-vol (risk-parity) raw weights, normalised over the slate.
    inv = 1.0 / sig
    s = float(inv.sum())
    if not np.isfinite(s) or s <= 0:
        return np.full(n, eq, dtype=float)
    w = inv / s

    if mode == "vol_target" and vol_target_pct is not None:
        try:
            tgt = float(vol_target_pct)
        except (TypeError, ValueError):
            tgt = float("nan")
        if np.isfinite(tgt) and tgt > 0:
            # Independent-name portfolio σ proxy (no covariance available cheaply in the
            # hot loop): σ_port = √(Σ wᵢ²σᵢ²). De-grosses a jumpy slate, never up-grosses
            # past fully-invested (scale clamped ≤ 1, mirroring the legacy [.,2.5×] bound
            # but applied at book level so the gross is the controlled quantity).
            sigma_port = float(np.sqrt(np.sum((w * sig) ** 2)))
            if np.isfinite(sigma_port) and sigma_port > 0:
                scale = float(np.clip(tgt / sigma_port, _VOL_SCALE_LO, 1.0))
                w = w * scale

    # Liquidity cap: a single position can absorb at most φ·ADVᵢ of NAV.
    caps = np.full(n, float(max_position_weight), dtype=float)
    if advs is not None and nav and nav > 0:
        adv_arr = np.array(
            [float(a) if a is not None else np.nan for a in advs], dtype=float
        )
        liq_cap = np.where(
            np.isfinite(adv_arr) & (adv_arr > 0),
            float(liquidity_phi) * adv_arr / float(nav),
            np.inf,
        )
        caps = np.minimum(caps, liq_cap)
    # Apply caps, then redistribute the freed budget to uncapped names once (a single
    # water-filling pass — cheap, and the residual is harmless because the engine's own
    # cash/cap gates are the binding authority downstream).
    w_capped = np.minimum(w, caps)
    freed = float(w.sum() - w_capped.sum())
    if freed > 1e-12:
        headroom = caps - w_capped
        head_sum = float(headroom[np.isfinite(headroom)].sum())
        if head_sum > 1e-12:
            add = np.where(np.isfinite(headroom), headroom / head_sum * freed, 0.0)
            w_capped = np.minimum(w_capped + add, caps)
    w = w_capped

    # Fractional-Kelly book gross: scale the whole vector (sizes the *book*, §3.3).
    try:
        g = float(kelly_gross)
    except (TypeError, ValueError):
        g = 1.0
    if np.isfinite(g) and 0.0 <= g <= 1.0:
        w = w * g

    w = np.where(np.isfinite(w) & (w > 0), w, 0.0)
    return w.astype(float)


def safe_compute_slate_weights(*args, **kwargs) -> Optional[np.ndarray]:
    """Fallback wrapper. Returns the weight vector, or None on ANY failure so the engine
    can transparently fall back to its legacy per-candidate equal-weight sizing (zero
    regression, mirrors the `membership_pit=False` degradation pattern)."""
    try:
        w = compute_slate_weights(*args, **kwargs)
        if w is None:
            return None
        w = np.asarray(w, dtype=float)
        if w.size and not np.all(np.isfinite(w)):
            return None
        return w
    except Exception:
        return None
