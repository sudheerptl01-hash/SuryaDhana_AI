"""
effective_trials.py — C9: cluster-adjusted effective number of trials.

The Deflated Sharpe Ratio (Bailey & López de Prado 2014) deflates the selected
Sharpe by the *expected maximum Sharpe under the null across N independent trials*
(`backtest_engine.expected_max_sharpe`). That N enters via two extreme-order-statistic
quantiles, Φ⁻¹(1 − 1/N) and Φ⁻¹(1 − 1/(N·e)) — both **monotone increasing in N**, so a
larger N raises the bar SR₀ and lowers DSR.

The catch (audit §3.6, finding C9): the 2⁶−1 = 63 filter combinations are NOT
independent. They share factors (e.g. `VMI` and `VMI+VIPT` overlap completely on the
VMI leg), so their daily-return series are heavily correlated. Feeding the *nominal*
count (63, or all surviving combos across a campaign) over-counts the true search
breadth: K perfectly-correlated trials are statistically ONE trial, not K. The
perverse failure mode is that *adding a near-duplicate combo* raises nominal N and
mechanically drops DSR — penalising a robust signal for the search's redundancy.

The fix (Harvey & Liu 2015, "Backtesting", §"Number of tests"; see also Harvey, Liu
& Zhu 2016): replace the nominal N with an **effective** number of independent tests
derived from the correlation structure of the trials' return series. We implement two
established estimators and a blend:

  1. Eigenvalue / participation-ratio estimator (Cattell-style spectral count). For
     the T×K matrix of de-meaned trial returns, let {λ_i} be the eigenvalues of the
     K×K correlation matrix C (Σ λ_i = K). The participation ratio

         N_eff = (Σ λ_i)² / Σ λ_i²  =  K² / Σ λ_i²

     collapses to 1 when all trials are perfectly correlated (one dominant eigenvalue
     λ₁ = K, rest 0  ⇒  N_eff = K²/K² = 1) and equals K when the trials are orthogonal
     (all λ_i = 1  ⇒  N_eff = K²/K = K). This is the spectral effective-rank used
     throughout multiple-testing-under-dependence literature.

  2. Average-pairwise-correlation estimator (the simple Harvey-Liu cluster proxy). With
     mean off-diagonal correlation ρ̄ ∈ [−1/(K−1), 1],

         N_eff = K / (1 + (K − 1) · ρ̄_+),   ρ̄_+ = max(ρ̄, 0)

     which also collapses K identical trials (ρ̄=1 ⇒ N_eff=1) to 1 and recovers K when
     ρ̄=0. Negative average correlation is floored at 0 so N_eff never *exceeds* K
     (you cannot manufacture independent tests by anti-correlation).

Both are pure functions of a correlation matrix, exactly handle the degenerate
endpoints, and are clamped to [1, K]. The public entry point `effective_n` accepts
either a return matrix or a precomputed correlation matrix and returns the spectral
estimate by default (it uses the full eigen-spectrum, not just the mean), with the
pairwise estimate available for cross-checking and as a fallback when the spectral
decomposition is ill-conditioned.

All functions are NaN/degenerate-safe: empty or single-trial inputs return N_eff=1;
non-finite correlations are zeroed; the result is always a finite float in [1, K].
"""
from __future__ import annotations

from typing import Optional

import numpy as np

__all__ = [
    "trial_correlation_matrix",
    "effective_n_spectral",
    "effective_n_pairwise",
    "effective_n",
    "stack_return_series",
    "campaign_effective_n",
]


def _sanitize_corr(corr: np.ndarray) -> Optional[np.ndarray]:
    """Coerce an input to a square, finite, symmetric correlation matrix with unit
    diagonal, or return None if it cannot be made into one. Non-finite entries are
    zeroed (treated as 'no measurable correlation')."""
    C = np.asarray(corr, dtype=float)
    if C.ndim != 2 or C.shape[0] != C.shape[1] or C.shape[0] == 0:
        return None
    C = np.where(np.isfinite(C), C, 0.0)
    # Symmetrize (a numerically-estimated corr may drift) and pin the diagonal to 1.
    C = 0.5 * (C + C.T)
    np.fill_diagonal(C, 1.0)
    # Clamp off-diagonals to a valid correlation range.
    C = np.clip(C, -1.0, 1.0)
    np.fill_diagonal(C, 1.0)
    return C


def trial_correlation_matrix(returns_matrix) -> Optional[np.ndarray]:
    """Pearson correlation matrix across trials from a (T_obs × K_trials) return matrix.

    Rows = time, columns = trials. Trials with zero variance (a flat/degenerate combo)
    correlate undefined with everything; we set their off-diagonal correlations to 0
    (no measurable co-movement) and keep a unit diagonal so they count as their own
    independent test rather than poisoning the matrix with NaNs.

    Returns a K×K matrix, or None if there are fewer than 2 usable observations/trials.
    """
    R = np.asarray(returns_matrix, dtype=float)
    if R.ndim != 2:
        return None
    T, K = R.shape
    if K < 1:
        return None
    if K == 1:
        return np.array([[1.0]])
    if T < 2:
        # Cannot estimate correlation; treat every trial as independent.
        return np.eye(K)
    R = np.where(np.isfinite(R), R, np.nan)
    mu = np.nanmean(R, axis=0)
    Rc = R - mu
    Rc = np.where(np.isfinite(Rc), Rc, 0.0)
    sd = np.sqrt(np.nansum(Rc * Rc, axis=0))
    # np.errstate guards the divide for zero-variance (flat) trial columns AND the
    # benign over/invalid FP flags some BLAS matmul kernels raise on the unit-norm Gram.
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        Z = np.where(sd > 1e-12, Rc / sd, 0.0)
        C = Z.T @ Z
    np.fill_diagonal(C, 1.0)          # zero-variance trials → unit self-correlation
    return _sanitize_corr(C)


def effective_n_spectral(corr) -> float:
    """Spectral (participation-ratio) effective number of independent trials.

        N_eff = (Σ λ_i)² / Σ λ_i²  = K² / Σ λ_i²

    for the eigenvalues {λ_i} of the K×K correlation matrix. Returns a float in [1, K].
    K identical trials → 1; K orthogonal trials → K.
    """
    C = _sanitize_corr(corr)
    if C is None:
        return 1.0
    K = C.shape[0]
    if K <= 1:
        return 1.0
    # eigvalsh: symmetric/Hermitian — real eigenvalues, numerically stable.
    try:
        w = np.linalg.eigvalsh(C)
    except np.linalg.LinAlgError:
        return float(K)               # ill-conditioned → fall back to nominal (no haircut relief)
    w = np.clip(w, 0.0, None)          # tiny negative eigenvalues from FP noise → 0
    denom = float(np.sum(w * w))
    if denom <= 1e-12:
        return 1.0
    n_eff = float(K * K) / denom
    return float(np.clip(n_eff, 1.0, K))


def effective_n_pairwise(corr) -> float:
    """Average-pairwise-correlation effective number of independent trials.

        N_eff = K / (1 + (K − 1) · max(ρ̄, 0))

    where ρ̄ is the mean off-diagonal correlation. Returns a float in [1, K]. This is
    the closed-form Harvey-Liu cluster proxy; cheaper and more robust than the spectral
    estimate when the correlation matrix is tiny or noisy.
    """
    C = _sanitize_corr(corr)
    if C is None:
        return 1.0
    K = C.shape[0]
    if K <= 1:
        return 1.0
    off = C[~np.eye(K, dtype=bool)]
    if off.size == 0:
        return float(K)
    rho_bar = float(np.mean(off))
    rho_pos = max(rho_bar, 0.0)        # anti-correlation can't manufacture extra tests
    denom = 1.0 + (K - 1) * rho_pos
    if denom <= 1e-12:
        return float(K)
    n_eff = float(K) / denom
    return float(np.clip(n_eff, 1.0, K))


def stack_return_series(series_list) -> Optional[np.ndarray]:
    """Stack a list of per-trial daily-return arrays (possibly ragged) into a single
    (T_common × K) matrix, truncating each to the shortest length so the correlation is
    estimated over the overlapping span. Trials shorter than 2 obs are dropped. Returns
    None if fewer than 2 usable trials remain.
    """
    cleaned: list[np.ndarray] = []
    for s in series_list or []:
        a = np.asarray(s, dtype=float).ravel()
        a = a[np.isfinite(a)]
        if a.size >= 2:
            cleaned.append(a)
    if len(cleaned) < 2:
        return None
    t_common = min(a.size for a in cleaned)
    if t_common < 2:
        return None
    # Truncate each series to the common length (tail-align would also work; head-align
    # is fine for an independence estimate — we only need shared co-movement).
    return np.column_stack([a[:t_common] for a in cleaned])


def campaign_effective_n(series_list, nominal: Optional[int] = None,
                         method: str = "spectral") -> dict:
    """Cross-campaign effective number of independent trials for the DSR haircut (C4+C9).

    Estimates the independence ratio from the correlation structure of the supplied
    per-trial daily-return series (`series_list`, one array per surviving combo), then
    scales it up to the campaign-wide `nominal` trial count from the `research_trials`
    ledger. This deflates against the TRUE search intensity (C4) while collapsing
    near-duplicate overlapping combos (C9) — the two corrections compose in one number.

    Returns a status dict (never raises):
        {"n_eff": float|None, "n_observed": int, "ratio": float|None,
         "nominal": int|None, "method": str, "ok": bool}
    `n_eff=None` ⇒ the caller should fall back to the per-run nominal DSR.
    """
    out = {"n_eff": None, "n_observed": 0, "ratio": None,
           "nominal": (int(nominal) if nominal else None), "method": method, "ok": False}
    try:
        R = stack_return_series(series_list)
        if R is None:
            return out
        K = R.shape[1]
        out["n_observed"] = int(K)
        n_eff_obs = effective_n(R, method=method)          # in [1, K]
        ratio = n_eff_obs / K if K >= 1 else 1.0
        out["ratio"] = round(float(ratio), 4)
        if nominal and int(nominal) >= 1:
            n_eff = effective_n(R, method=method, nominal=int(nominal))
        else:
            n_eff = n_eff_obs
        out["n_eff"] = round(float(max(1.0, n_eff)), 3)
        out["ok"] = True
        return out
    except Exception:
        return out


def effective_n(returns_matrix=None, corr=None, method: str = "spectral",
                nominal: Optional[int] = None) -> float:
    """Effective number of independent trials for the DSR multiple-testing haircut.

    Provide EITHER `returns_matrix` (T_obs × K_trials, time down rows) OR a precomputed
    `corr` (K×K). `method` ∈ {"spectral", "pairwise"} selects the estimator; "spectral"
    (default) uses the full eigen-spectrum (participation ratio), "pairwise" the mean
    off-diagonal correlation. The result is clamped to [1, K] (or [1, nominal] when a
    nominal cap is supplied, e.g. when K differs from the campaign's true trial count).

    Degenerate/empty input ⇒ 1.0. Any internal failure ⇒ the nominal count (no haircut
    relief), so the caller's DSR is never made *more* lenient by an estimator error.
    """
    try:
        C = corr if corr is not None else trial_correlation_matrix(returns_matrix)
        if C is None:
            return float(nominal) if nominal and nominal >= 1 else 1.0
        K = np.asarray(C, dtype=float).shape[0]
        if method == "pairwise":
            n_eff = effective_n_pairwise(C)
        else:
            n_eff = effective_n_spectral(C)
        if nominal is not None and nominal >= 1:
            # When the ledger's nominal trial count exceeds the K trials we could
            # correlation-cluster (e.g. only the surviving combos have return series),
            # scale the estimated independence ratio up to the full campaign breadth:
            #   N_eff_campaign = nominal · (N_eff_observed / K)
            # so 63 nominal trials that are spectrally ~3 independent → ~3, and 600
            # campaign trials at the same redundancy ratio → ~28, never above `nominal`.
            ratio = n_eff / K if K >= 1 else 1.0
            n_eff = float(nominal) * ratio
            return float(np.clip(n_eff, 1.0, float(nominal)))
        return float(np.clip(n_eff, 1.0, float(K)))
    except Exception:
        return float(nominal) if nominal and nominal >= 1 else 1.0
