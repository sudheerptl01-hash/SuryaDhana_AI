"""
C6 (§3.6 / §4.8) — per-name Y_i recalibration math + persistence tests.

Validates that the origin-OLS regression recovers a KNOWN Y_i from synthetic fills
(IS_bps = Y · σ_bps · √participation), that degenerate inputs are safe no-ops, that the
[YI_FLOOR, YI_CEIL] clip binds, and that the full slippage→recalibration→persist loop
round-trips through DuckDB.
"""
import math
import os
import sys

import duckdb
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import recalibrate_yi as rc  # noqa: E402
import slippage_store as ss  # noqa: E402


def _synthetic_rows(ticker, y_true, atr_pct=3.0, parts=(0.02, 0.05, 0.08, 0.10, 0.12, 0.15)):
    """Rows whose IS_bps is EXACTLY y_true · σ_bps · √part (the √-law model)."""
    sigma_bps = atr_pct * 100.0
    rows = []
    for p in parts:
        rows.append({
            "ticker": ticker,
            "atr_pct": atr_pct,
            "participation": p,
            "is_bps": y_true * sigma_bps * math.sqrt(p),
            "fill_ratio": 1.0,
            "y_i": 1.0,
        })
    return rows


# ── Math: the regression recovers a known coefficient ──────────────────────────────
def test_recovers_known_y_i_from_clean_fills():
    rows = _synthetic_rows("CLEAN", y_true=1.7)
    out = rc.recalibrate_from_rows(rows, min_fills=3)
    assert "CLEAN" in out
    c = out["CLEAN"]
    assert c["used_prior"] is False
    assert c["y_i_realised"] == pytest.approx(1.7, rel=1e-6)
    assert c["r2"] == pytest.approx(1.0, abs=1e-9)   # perfect fit on noiseless data
    assert c["n_fills"] == 6


def test_recovers_distinct_coefficients_per_name():
    rows = _synthetic_rows("CHEAP", 0.8) + _synthetic_rows("PRICEY", 2.6)
    out = rc.recalibrate_from_rows(rows, min_fills=3)
    assert out["CHEAP"]["y_i_realised"] == pytest.approx(0.8, rel=1e-6)
    assert out["PRICEY"]["y_i_realised"] == pytest.approx(2.6, rel=1e-6)


def test_clip_binds_at_ceiling_and_floor():
    # A true slope above the ceiling clips to YI_CEIL; below the floor clips to YI_FLOOR.
    hi = rc.recalibrate_from_rows(_synthetic_rows("HI", 5.0), min_fills=3)["HI"]
    lo = rc.recalibrate_from_rows(_synthetic_rows("LO", 0.1), min_fills=3)["LO"]
    assert hi["y_i_realised"] == pytest.approx(rc.YI_CEIL)
    assert lo["y_i_realised"] == pytest.approx(rc.YI_FLOOR)


# ── Degenerate / safety: keep the prior, never raise ───────────────────────────────
def test_too_few_fills_keeps_prior():
    rows = _synthetic_rows("THIN", 2.0, parts=(0.05, 0.10))   # only 2 fills
    out = rc.recalibrate_from_rows(rows, prior_y_i={"THIN": 1.3}, min_fills=5)
    assert out["THIN"]["used_prior"] is True
    assert out["THIN"]["y_i_realised"] == pytest.approx(1.3)


def test_zero_participation_rows_ignored():
    rows = [
        {"ticker": "Z", "atr_pct": 3.0, "participation": 0.0, "is_bps": 50.0,
         "fill_ratio": 1.0, "y_i": 1.0},
        {"ticker": "Z", "atr_pct": 3.0, "participation": 0.0, "is_bps": 60.0,
         "fill_ratio": 1.0, "y_i": 1.0},
    ]
    out = rc.recalibrate_from_rows(rows, prior_y_i={"Z": 1.1}, min_fills=1)
    # All rows filtered (zero regressor) → name never accumulates → not in output.
    assert "Z" not in out


def test_nan_and_unfilled_rows_are_dropped():
    rows = _synthetic_rows("OK", 1.5)
    rows += [
        {"ticker": "OK", "atr_pct": 3.0, "participation": 0.08,
         "is_bps": float("nan"), "fill_ratio": 1.0, "y_i": 1.0},     # NaN IS — dropped
        {"ticker": "OK", "atr_pct": 3.0, "participation": 0.08,
         "is_bps": 999.0, "fill_ratio": 0.0, "y_i": 1.0},            # unfilled — dropped
    ]
    out = rc.recalibrate_from_rows(rows, min_fills=3)
    assert out["OK"]["y_i_realised"] == pytest.approx(1.5, rel=1e-6)
    assert out["OK"]["n_fills"] == 6   # only the 6 clean rows counted


def test_empty_input_is_empty_output():
    assert rc.recalibrate_from_rows([]) == {}


def test_malformed_rows_never_raise():
    rows = [{"ticker": None}, {"is_bps": "x"}, {}, {"ticker": "A", "participation": "y"}]
    out = rc.recalibrate_from_rows(rows)   # must not raise
    assert isinstance(out, dict)


# ── Origin-OLS helper directly ─────────────────────────────────────────────────────
def test_origin_ols_slope_basic():
    # y = 2x exactly through the origin.
    res = rc._origin_ols_slope([1.0, 2.0, 3.0], [2.0, 4.0, 6.0])
    assert res is not None
    slope, r2 = res
    assert slope == pytest.approx(2.0, rel=1e-9)
    assert r2 == pytest.approx(1.0, abs=1e-9)


def test_origin_ols_slope_degenerate_returns_none():
    assert rc._origin_ols_slope([0.0, 0.0], [1.0, 2.0]) is None   # Σx² = 0
    assert rc._origin_ols_slope([], []) is None


# ── Full DB loop: slippage → recalibrate → persist ─────────────────────────────────
def test_end_to_end_recalibrate_through_duckdb(tmp_path):
    db = str(tmp_path / "m.duckdb")
    # Seed the slippage table via the real collector (the production write path).
    col = ss.SlippageCollector(run_id="r1", db_path=db)
    for r in _synthetic_rows("REAL", y_true=2.1):
        # SlippageCollector expects the engine's slippage_sink dict shape.
        col.add({
            "ticker": "REAL", "entry_date": "2024-01-01",
            "arrival_price": 1000.0, "realised_vwap": 1000.0,
            "alloc": 2e7, "adv": 1e8, "participation": r["participation"],
            "n_slices": 13, "n_sessions": 1, "fill_ratio": 1.0,
            "is_bps": r["is_bps"], "y_i": 1.0, "unfilled_notional": 0.0,
            "atr_pct": r["atr_pct"],
        })
    assert col.flush()["written"] == 6

    res = rc.recalibrate(db_path=db, persist=True, min_fills=3)
    assert res["n_rows"] == 6
    assert res["calibration"]["REAL"]["y_i_realised"] == pytest.approx(2.1, rel=1e-6)
    assert res["persisted"]["ok"] is True
    assert res["persisted"]["written"] == 1

    # The y_i_calibration table now holds the recalibrated coefficient.
    con = duckdb.connect(db, read_only=True)
    row = con.execute("SELECT ticker, y_i_realised, n_fills FROM y_i_calibration").fetchone()
    con.close()
    assert row[0] == "REAL"
    assert row[1] == pytest.approx(2.1, rel=1e-6)
    assert row[2] == 6


def test_recalibrate_on_missing_store_is_safe(tmp_path):
    # No slippage table exists → empty calibration, no crash.
    db = str(tmp_path / "empty.duckdb")
    duckdb.connect(db).close()   # create an empty DB file
    res = rc.recalibrate(db_path=db, persist=False)
    assert res["n_names"] == 0
    assert res["n_rows"] == 0
