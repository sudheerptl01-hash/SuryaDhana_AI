"""
recalibrate_yi.py — C6 (§3.6 / §4.8) nightly recalibration of the per-name temporary
market-impact coefficient Y_i from REALISED implementation shortfall.

The backtest's temporary-impact leg is the √-law

        IS_bps  ≈  Y_i · σ_bps · √(participation)            (Almgren / Tóth-Lillo-Bouchaud)

where σ_bps = ATR% · 100 and participation = Q / ADV. The Phase-0 auto-path seeds Y_i
from a *static* Amihud transform (g(ILLIQ_i)); over time, as the scheduler books real
fills into the `slippage` table, we can ground Y_i in what actually happened: regress
realised IS_bps on the model regressor x = σ_bps · √(participation) through the origin
(participation = 0 ⇒ zero impact, so NO intercept), and read off the slope as the
measured coefficient

        Ŷ_i  =  Σ(x · y) / Σ(x²)                              (origin OLS / least squares)

This closes the loop: the backtest's Y_i self-corrects toward live reality instead of a
frozen Amihud transform.

Design:
  • Pure regression math (`recalibrate_from_rows`) is numpy-free and unit-testable in
    isolation — degenerate inputs (no rows, zero regressor, NaN/inf) resolve to the prior
    Y_i (a safe no-op), never raising.
  • The DuckDB reader + the persisted `y_i_calibration` table live behind a defensive
    wrapper; a missing/locked store yields an empty result, never a crash.
  • A small CLI entry point lets a nightly cron run the recalibration; ACTUAL cron/
    scheduler wiring is out of scope (Phase-later) — this provides the correct, tested
    math + persistence only.
"""
from __future__ import annotations

import argparse
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Bound the recalibrated coefficient to the same band the static calibrator uses, so a
# noisy fit on a handful of fills can never push Y_i outside the √-law's calibrated domain.
YI_FLOOR, YI_CEIL = 0.5, 3.0
# Minimum filled executions per name before we trust a measured slope over the prior.
MIN_FILLS_PER_NAME = 5
# ATR% → bps (σ_bps = ATR% · 100), matching scheduled_impact._ATR_PCT_TO_BPS.
_ATR_PCT_TO_BPS = 100.0

_DB_PATH = (
    os.environ.get("DATABASE_URL")
    or os.environ.get("DUCKDB_PATH")
    or str(Path(__file__).resolve().parent.parent.parent / "data" / "market.duckdb")
)

Y_I_CALIB_DDL = """
CREATE TABLE IF NOT EXISTS y_i_calibration (
    ts            TIMESTAMP,
    ticker        VARCHAR,
    y_i_prior     DOUBLE,
    y_i_realised  DOUBLE,
    n_fills       INTEGER,
    r2            DOUBLE
);
"""


def _origin_ols_slope(xs: list[float], ys: list[float]) -> Optional[tuple[float, float]]:
    """Least-squares slope of y = b·x through the origin, plus R². None if undetermined.

    b = Σ(x·y) / Σ(x²). Returns (slope, r2). Filters non-finite pairs; if Σ(x²) is zero
    (no participation variation) the slope is undetermined → None (caller keeps the prior).
    """
    sxx = 0.0
    sxy = 0.0
    syy = 0.0
    n = 0
    for x, y in zip(xs, ys):
        if not (math.isfinite(x) and math.isfinite(y)):
            continue
        sxx += x * x
        sxy += x * y
        syy += y * y
        n += 1
    if n == 0 or sxx <= 0.0:
        return None
    slope = sxy / sxx
    # R² for an origin model: 1 - SS_res / SS_tot_about_origin (Σy²).
    ss_res = syy - slope * sxy
    r2 = 1.0 - (ss_res / syy) if syy > 0 else 0.0
    if not math.isfinite(slope):
        return None
    return slope, max(0.0, min(1.0, r2))


def recalibrate_from_rows(
    rows: list[dict],
    prior_y_i: Optional[dict[str, float]] = None,
    min_fills: int = MIN_FILLS_PER_NAME,
) -> dict[str, dict]:
    """Recalibrate per-name Y_i from realised slippage rows. Pure; never raises.

    Each row needs: ticker, is_bps (realised implementation shortfall), atr_pct,
    participation (Q/ADV), fill_ratio. Only FILLED rows (fill_ratio > 0, participation > 0)
    contribute. For each name with >= `min_fills` usable rows we fit Ŷ_i = slope of
    IS_bps on σ_bps·√(participation) through the origin, clip to [YI_FLOOR, YI_CEIL], and
    return {ticker → {y_i_realised, y_i_prior, n_fills, r2}}. Names with too few fills, or
    a degenerate fit, keep their prior Y_i (a safe no-op).
    """
    prior_y_i = prior_y_i or {}
    by_name: dict[str, tuple[list[float], list[float]]] = {}
    for r in rows:
        try:
            tkr = str(r.get("ticker", "")).upper()
            if not tkr:
                continue
            fill_ratio = float(r.get("fill_ratio", 1.0) or 0.0)
            part = float(r.get("participation", 0.0) or 0.0)
            is_bps = float(r.get("is_bps", 0.0) or 0.0)
            atr_pct = float(r.get("atr_pct", 0.0) or 0.0)
        except (TypeError, ValueError):
            continue
        if fill_ratio <= 0.0 or part <= 0.0 or not math.isfinite(is_bps):
            continue
        sigma_bps = max(0.0, atr_pct) * _ATR_PCT_TO_BPS
        x = sigma_bps * math.sqrt(part)
        if x <= 0.0:
            continue
        xs, ys = by_name.setdefault(tkr, ([], []))
        xs.append(x)
        ys.append(is_bps)

    out: dict[str, dict] = {}
    for tkr, (xs, ys) in by_name.items():
        prior = float(prior_y_i.get(tkr, 1.0))
        if len(xs) < int(min_fills):
            out[tkr] = {"y_i_realised": prior, "y_i_prior": prior,
                        "n_fills": len(xs), "r2": 0.0, "used_prior": True}
            continue
        fit = _origin_ols_slope(xs, ys)
        if fit is None:
            out[tkr] = {"y_i_realised": prior, "y_i_prior": prior,
                        "n_fills": len(xs), "r2": 0.0, "used_prior": True}
            continue
        slope, r2 = fit
        y_realised = max(YI_FLOOR, min(YI_CEIL, slope))
        out[tkr] = {"y_i_realised": float(y_realised), "y_i_prior": prior,
                    "n_fills": len(xs), "r2": float(r2), "used_prior": False}
    return out


def _read_slippage_rows(db_path: str, run_id: Optional[str] = None) -> list[dict]:
    """Read slippage rows from DuckDB. Returns [] on any failure (never raises)."""
    try:
        import duckdb
    except Exception:
        return []
    try:
        con = duckdb.connect(db_path, read_only=True)
    except Exception:
        return []
    try:
        tbls = {r[0] for r in con.execute("SHOW TABLES").fetchall()}
        if "slippage" not in tbls:
            return []
        sql = ("SELECT ticker, is_bps, atr_pct, participation, fill_ratio, y_i "
               "FROM slippage")
        params: list = []
        if run_id:
            sql += " WHERE run_id = ?"
            params.append(run_id)
        cur = con.execute(sql, params)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception:
        return []
    finally:
        try:
            con.close()
        except Exception:
            pass


def _read_prior_y_i(rows: list[dict]) -> dict[str, float]:
    """Best-available prior Y_i: the most recent y_i seen per name in the slippage rows."""
    prior: dict[str, float] = {}
    for r in rows:
        tkr = str(r.get("ticker", "")).upper()
        try:
            y = float(r.get("y_i", 1.0))
        except (TypeError, ValueError):
            continue
        if tkr and math.isfinite(y) and y > 0:
            prior[tkr] = y
    return prior


def _persist_calibration(db_path: str, calib: dict[str, dict]) -> dict:
    """Write the recalibration to `y_i_calibration`. Defensive; never raises."""
    if not calib:
        return {"written": 0, "ok": True, "reason": "no calibration"}
    try:
        import duckdb
    except Exception:
        return {"written": 0, "ok": False, "reason": "duckdb unavailable"}
    try:
        con = duckdb.connect(db_path, read_only=False)
    except Exception:
        return {"written": 0, "ok": False, "reason": "write lock unavailable"}
    try:
        con.execute(Y_I_CALIB_DDL)
        ts = datetime.now(timezone.utc).replace(tzinfo=None)
        tuples = [(ts, tkr, c["y_i_prior"], c["y_i_realised"], c["n_fills"], c["r2"])
                  for tkr, c in calib.items()]
        con.executemany(
            "INSERT INTO y_i_calibration (ts, ticker, y_i_prior, y_i_realised, n_fills, r2) "
            "VALUES (?, ?, ?, ?, ?, ?)", tuples)
        return {"written": len(tuples), "ok": True, "reason": None}
    except Exception as exc:   # pragma: no cover - lock/IO dependent
        return {"written": 0, "ok": False, "reason": str(exc)}
    finally:
        try:
            con.close()
        except Exception:
            pass


def recalibrate(db_path: Optional[str] = None, run_id: Optional[str] = None,
                persist: bool = False, min_fills: int = MIN_FILLS_PER_NAME) -> dict:
    """End-to-end: read `slippage`, recalibrate per-name Y_i, optionally persist + echo.

    Returns {"calibration": {ticker → {...}}, "n_names": int, "persisted": {...}|None}.
    Safe to call against a missing/locked store — yields an empty calibration, no crash.
    """
    path = db_path or _DB_PATH
    rows = _read_slippage_rows(path, run_id)
    prior = _read_prior_y_i(rows)
    calib = recalibrate_from_rows(rows, prior_y_i=prior, min_fills=min_fills)
    persisted = _persist_calibration(path, calib) if persist else None
    return {"calibration": calib, "n_names": len(calib), "n_rows": len(rows),
            "persisted": persisted}


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Recalibrate per-name temporary-impact Y_i from realised slippage (C6).")
    ap.add_argument("--db", default=None, help="DuckDB path (default: env / repo data/market.duckdb)")
    ap.add_argument("--run-id", default=None, help="restrict to one backtest run_id")
    ap.add_argument("--persist", action="store_true", help="write y_i_calibration table")
    ap.add_argument("--min-fills", type=int, default=MIN_FILLS_PER_NAME)
    args = ap.parse_args(argv)
    res = recalibrate(db_path=args.db, run_id=args.run_id, persist=args.persist,
                      min_fills=args.min_fills)
    print(f"recalibrated {res['n_names']} names from {res['n_rows']} slippage rows")
    for tkr, c in sorted(res["calibration"].items()):
        flag = "(prior)" if c.get("used_prior") else f"R2={c['r2']:.2f}"
        print(f"  {tkr:<14} Y_i {c['y_i_prior']:.3f} → {c['y_i_realised']:.3f}  "
              f"n={c['n_fills']} {flag}")
    if res["persisted"] is not None:
        p = res["persisted"]
        print(f"persisted: {p['written']} rows (ok={p['ok']}"
              + (f", reason={p['reason']}" if p["reason"] else "") + ")")
    return 0


if __name__ == "__main__":   # pragma: no cover - CLI entry
    raise SystemExit(main())
