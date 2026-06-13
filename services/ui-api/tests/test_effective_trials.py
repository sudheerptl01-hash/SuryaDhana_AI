"""C9 — cluster-adjusted effective number of trials.

Validates the two estimators against their known closed-form endpoints (K identical
trials collapse to ~1; K orthogonal trials recover K), the [1, K] clamp, degenerate-
input safety, and the monotonicity that DSR uses: deflating against the EFFECTIVE
count (< nominal for overlapping trials) yields a DSR no smaller than the nominal-count
DSR, fixing the C9 near-duplicate perversity.
"""
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import backtest_engine as be  # noqa: E402
import effective_trials as et  # noqa: E402


# ── Endpoint 1: K perfectly-correlated trials count as ~1 ──────────────────────────

def test_spectral_identical_trials_collapse_to_one():
    rng = np.random.default_rng(0)
    base = rng.standard_normal(500)
    # 8 trials that are all the same series (perfectly correlated, just rescaled/shifted).
    R = np.column_stack([base * (1.0 + 0.0 * k) + 0.0 for k in range(8)])
    n_eff = et.effective_n(R, method="spectral")
    assert n_eff == pytest.approx(1.0, abs=1e-6)


def test_pairwise_identical_trials_collapse_to_one():
    rng = np.random.default_rng(1)
    base = rng.standard_normal(500)
    R = np.column_stack([base for _ in range(5)])
    assert et.effective_n(R, method="pairwise") == pytest.approx(1.0, abs=1e-6)


# ── Endpoint 2: K orthogonal trials recover K ──────────────────────────────────────

def test_spectral_orthogonal_trials_recover_k():
    rng = np.random.default_rng(2)
    K = 10
    R = rng.standard_normal((4000, K))   # independent columns → corr ≈ I
    n_eff = et.effective_n(R, method="spectral")
    # Finite-sample noise pulls it slightly below K; must be close and ≤ K.
    assert n_eff <= K + 1e-9
    assert n_eff == pytest.approx(K, rel=0.10)


def test_pairwise_orthogonal_trials_recover_k():
    rng = np.random.default_rng(3)
    K = 10
    R = rng.standard_normal((4000, K))
    n_eff = et.effective_n(R, method="pairwise")
    assert n_eff == pytest.approx(K, rel=0.20)


# ── Exact identity-matrix and rank-one matrix endpoints (no sampling noise) ─────────

def test_spectral_identity_matrix_equals_k():
    K = 7
    assert et.effective_n_spectral(np.eye(K)) == pytest.approx(K, abs=1e-9)


def test_spectral_rank_one_matrix_equals_one():
    K = 7
    ones = np.ones((K, K))               # all-ones corr = perfect correlation (rank 1)
    assert et.effective_n_spectral(ones) == pytest.approx(1.0, abs=1e-9)


def test_pairwise_rank_one_matrix_equals_one():
    assert et.effective_n_pairwise(np.ones((6, 6))) == pytest.approx(1.0, abs=1e-9)


# ── Clamp + degenerate-input safety ────────────────────────────────────────────────

def test_effective_n_clamped_to_one_k():
    K = 5
    # Half-correlated block → strictly between 1 and K.
    C = 0.5 * np.ones((K, K)) + 0.5 * np.eye(K)
    n_eff = et.effective_n(corr=C, method="spectral")
    assert 1.0 <= n_eff <= K


def test_empty_and_single_trial_return_one():
    assert et.effective_n(np.empty((0, 0))) == pytest.approx(1.0)
    assert et.effective_n(np.zeros((100, 1))) == pytest.approx(1.0)
    assert et.effective_n_spectral(np.array([[1.0]])) == pytest.approx(1.0)


def test_non_finite_inputs_are_sanitized():
    C = np.array([[1.0, np.nan], [np.inf, 1.0]])
    n_eff = et.effective_n(corr=C, method="spectral")
    assert np.isfinite(n_eff)
    assert 1.0 <= n_eff <= 2.0


def test_negative_correlation_does_not_exceed_k():
    # Anti-correlated trials must NOT manufacture > K independent tests.
    C = np.array([[1.0, -0.9], [-0.9, 1.0]])
    assert et.effective_n_pairwise(C) <= 2.0 + 1e-9
    assert et.effective_n_spectral(C) <= 2.0 + 1e-9


# ── Nominal-cap scaling: campaign breadth scaled by the observed independence ratio ─

def test_nominal_scaling_preserves_independence_ratio():
    # 8 perfectly-correlated observed trials (ratio 1/8) over a 600-trial campaign
    # ⇒ ~75 effective; never above the nominal cap.
    rng = np.random.default_rng(4)
    base = rng.standard_normal(500)
    R = np.column_stack([base for _ in range(8)])
    n_eff = et.effective_n(R, method="spectral", nominal=600)
    assert n_eff == pytest.approx(600.0 * (1.0 / 8.0), rel=0.05)
    assert n_eff <= 600.0


# ── The C9 fix: effective-N DSR ≥ nominal-N DSR for overlapping trials ──────────────

def test_effective_dsr_geq_nominal_dsr_for_overlapping_trials():
    rng = np.random.default_rng(5)
    # A selected strategy with a modest positive daily edge.
    ret = rng.normal(0.0008, 0.01, 600)
    # 40 trial Sharpes, but the trials are redundant ⇒ effective count is small.
    trial_sharpes = list(rng.normal(0.8, 0.4, 40))
    nominal = be.deflated_sharpe_ratio(ret, trial_sharpes)            # legacy, N=40
    effective = be.deflated_sharpe_ratio(ret, trial_sharpes, n_eff=4) # honest, N_eff=4
    # Fewer effective trials ⇒ lower bar SR₀ ⇒ DSR no smaller. This is the C9 correction:
    # adding near-duplicate combos no longer perversely penalises a robust signal.
    assert effective["dsr"] >= nominal["dsr"] - 1e-12
    assert effective["sr0_annual"] <= nominal["sr0_annual"] + 1e-9
    assert effective["n_eff"] == pytest.approx(4.0)
    assert nominal["n_eff"] is None       # default path unchanged


def test_n_eff_default_is_exact_legacy():
    rng = np.random.default_rng(6)
    ret = rng.normal(0.0005, 0.012, 400)
    trials = list(rng.normal(1.0, 0.3, 30))
    a = be.deflated_sharpe_ratio(ret, trials)
    b = be.deflated_sharpe_ratio(ret, trials, n_eff=None)
    assert a["dsr"] == pytest.approx(b["dsr"])
    assert a["sr0_annual"] == pytest.approx(b["sr0_annual"])
    assert a["n_eff"] is None


def test_larger_effective_n_lowers_dsr_monotone():
    # Cross-campaign honesty (C4): a LARGER effective count (more uncounted trials
    # surfaced from the ledger) raises the bar and lowers DSR — the haircut is harsher.
    rng = np.random.default_rng(7)
    ret = rng.normal(0.001, 0.011, 600)
    trials = list(rng.normal(1.2, 0.5, 50))
    dsr_small = be.deflated_sharpe_ratio(ret, trials, n_eff=5)["dsr"]
    dsr_large = be.deflated_sharpe_ratio(ret, trials, n_eff=500)["dsr"]
    assert dsr_large <= dsr_small + 1e-12
