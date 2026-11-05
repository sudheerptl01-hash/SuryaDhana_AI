"""validate_top_combo_wfo.py — re-validate a decile-discovered combo through the
PRODUCTION walk-forward engine (real capital constraints, friction, embargo, DSR).

The decile_combinatorial_optimizer surfaces hypotheses on an UNCONSTRAINED equal-weight
basket (signal proxy, best-of-N selection). This script takes one of those combos — by
default the top *monotone* combo (Above-52w-Low + Dist200, the highest-Calmar combo built
only from clean-monotone factors) — translates each factor's optimal decile band into a
static production-filter threshold, and runs it through `analytics._core_wfo`: rolling
in-sample → embargoed out-of-sample, max 5 positions, 0.15% friction, auto market-impact,
and a Deflated-Sharpe multiple-testing correction.

Pinned (fixed-combo) test: the combo lives in `base_filters` with an EMPTY candidate pool,
so every window applies exactly this screen on its OOS fold — a pure out-of-sample stitch,
not a per-window re-optimization.

Caveat (honest): the optimizer uses DAILY cross-sectional deciles; the production backtest
filters on STATIC numeric thresholds. We approximate "Top X%" by the global (100−X)th
percentile of the factor. The daily-decile composition therefore differs somewhat — this
tests a static-threshold proxy of the screen, which is what the production engine supports.

MODE=PAPER. Canonical Python. Read-only DB. No secrets.

Run:
  DB_PATH=.../data/market.duckdb /Users/sudheer/Desktop/jupyter_env/bin/python \
      scripts/validate_top_combo_wfo.py
  ...  --combo above_52w_low_pct,dist_ma200_pct      # override the combo (column names)
"""
from __future__ import annotations

import os
import sys
import argparse
from pathlib import Path

import numpy as np
import duckdb

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "services" / "ui-api"))
DB_PATH = (os.environ.get("DB_PATH") or os.environ.get("DUCKDB_PATH")
           or str(REPO / "data" / "market.duckdb"))

import decile_combinatorial_optimizer as dco          # reuse the exact prep + band logic
from routers.analytics import _core_wfo, WFOBacktestRequest, FilterCondition  # noqa: E402

# Column name → production filter id (FIELD_MAP key). Identity except where they differ.
COL_TO_FILTER = {"atr_pct": "atr_14_pct"}

# The top monotone combo from DECILE_OPTIMIZATION_REPORT.md (rank 110, Calmar 1.30).
DEFAULT_COMBO = ["above_52w_low_pct", "dist_ma200_pct"]


def band_to_filter(df, col: str, band_label: str) -> dict:
    """Translate an optimal decile band ('Top 10%' / 'Bottom 30%') into a static production
    filter on the GLOBAL factor percentile. Top X% → factor ≥ (100−X)th pct (op gte);
    Bottom X% → factor ≤ Xth pct (op lte)."""
    side, pct = band_label.split()
    p = float(pct.rstrip("%"))
    vals = df[col].to_numpy(dtype=float)
    vals = vals[np.isfinite(vals)]
    fid = COL_TO_FILTER.get(col, col)
    if side == "Top":
        thr, op = float(np.percentile(vals, 100 - p)), "gte"
    else:
        thr, op = float(np.percentile(vals, p)), "lte"
    return {"field": fid, "op": op, "value": round(thr, 6), "_col": col, "_band": band_label}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--combo", default=",".join(DEFAULT_COMBO),
                    help="comma-separated factor COLUMN names")
    ap.add_argument("--in-sample-days", type=int, default=365)
    ap.add_argument("--out-sample-days", type=int, default=90)
    args = ap.parse_args()
    combo_cols = [c.strip() for c in args.combo.split(",") if c.strip()]

    print(f"MODE=PAPER  DB={DB_PATH}")
    print(f"=== WFO VALIDATION — combo: {[dco.SHORT.get(c, c) for c in combo_cols]} ===")

    # 1) Prep + discover each member's optimal band (reuse the optimizer's exact logic).
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        df, present = dco.load_prepared(con, combo_cols)
    finally:
        con.close()
    missing = [c for c in combo_cols if c not in present]
    if missing:
        raise SystemExit(f"factors absent: {missing}")
    dco.assign_deciles(df, present)

    filters = []
    print("\n── band → static threshold translation ──")
    for c in present:
        b = dco.pick_optimal_band(df, c)
        if b is None:
            raise SystemExit(f"{c}: no positive-edge band — not a valid combo member")
        f = band_to_filter(df, c, b["band"])
        filters.append(f)
        print(f"  {dco.SHORT.get(c,c):8s} {b['band']:9s} (mono={dco.monotonicity(dco.decile_distribution(df,c)):+.2f}) "
              f"→ filter `{f['field']}` {f['op']} {f['value']}")

    from_date, to_date = str(df["date"].min().date()), str(df["date"].max().date())

    # 2) Pinned WFO request — combo in base_filters, empty candidate pool (no re-selection).
    req = WFOBacktestRequest(
        from_date=from_date, to_date=to_date, forward_days=dco.HORIZON,
        starting_capital=10_000_000.0, friction_bps=15.0, max_positions=5, scope="universe",
        base_filters=[FilterCondition(field=f["field"], op=f["op"], value=f["value"]) for f in filters],
        candidate_filters=[],
        in_sample_days=args.in_sample_days, out_sample_days=args.out_sample_days,
    )
    print(f"\n── running production walk-forward ({from_date} → {to_date}, "
          f"IS={args.in_sample_days}d / OOS={args.out_sample_days}d, max_positions=5, friction=15bps) …")
    res = _core_wfo(req)

    wf = res.get("walk_forward", {})
    if wf.get("n_windows", 0) == 0:
        print("  ✖ no OOS windows:", wf.get("note", "")); return

    # 3) Report — stitched OUT-OF-SAMPLE track record.
    def g(k, d=0.0):
        return res.get(k, d)
    print("\n══════ STITCHED OUT-OF-SAMPLE RESULTS (capital-managed, 5 positions) ══════")
    print(f"  Total return    {g('total_return_pct'):+.2f}%   (benchmark {g('benchmark_total_return_pct'):+.2f}%)")
    print(f"  CAGR            {g('cagr_pct'):+.2f}%")
    print(f"  Sharpe          {g('sharpe_ratio'):.3f}      Sortino {g('sortino_ratio'):.3f}   Calmar {g('calmar_ratio'):.3f}")
    print(f"  Max drawdown    {g('max_drawdown'):.2f}%")
    print(f"  Win rate        {g('win_rate'):.1f}%   Trades {g('total_trades'):,}   PF {g('profit_factor'):.2f}")
    print(f"  Alpha (ann.)    {g('alpha_annual_pct'):+.2f}%   Beta {g('beta'):.2f}")

    print("\n── Walk-forward integrity ──")
    print(f"  OOS windows     {wf.get('n_windows')}  (IS {wf.get('in_sample_days')}d / "
          f"OOS {wf.get('out_sample_days')}d / embargo {wf.get('embargo_days')}d)")
    print(f"  IS→OOS efficiency {wf.get('efficiency')}   (≪1 ⇒ overfit; ~1 ⇒ holds up)")
    print(f"  avg IS obj {wf.get('avg_is_objective')}  →  avg OOS obj {wf.get('avg_oos_objective')}")
    print(f"  Deflated Sharpe {wf.get('deflated_sharpe')}  (≳0.95 survives multiple-testing; "
          f"trials={wf.get('dsr_n_trials')})")
    isf = res.get("in_sample_full") or {}
    if isf:
        print(f"  Full-period in-sample fit (same screen): Sharpe {isf.get('sharpe_ratio')}, "
              f"CAGR {isf.get('cagr_pct')}%, MaxDD {isf.get('max_drawdown')}%")
    mc = res.get("monte_carlo") or {}
    if mc:
        print(f"  Monte-Carlo OOS-trade drawdown  p50 {mc.get('p50')}%  p95 {mc.get('p95')}%")

    print("\n── Per-window OOS (in-sample → out-of-sample degradation) ──")
    print(f"  {'OOS window':23s} {'trades':>6} {'ret%':>7} {'win%':>6} {'IS Shp':>7} {'OOS Shp':>8} {'degr':>7}")
    for w in res.get("wfo_windows", []):
        print(f"  {w['start']}→{w['end']:10s} {w['trades']:>6} {w['total_return_pct']:>7.2f} "
              f"{w['win_rate']:>6.1f} {w.get('is_sharpe',0):>7.2f} {w.get('oos_sharpe',0):>8.2f} "
              f"{w.get('degradation',0):>7.2f}")

    # 4) Verdict
    dsr = wf.get("deflated_sharpe", 0.0) or 0.0
    eff = wf.get("efficiency") or 0.0
    sharpe = g("sharpe_ratio")
    verdict = ("SURVIVES — positive OOS Sharpe, DSR≳0.95, efficiency≈1" if (dsr >= 0.95 and sharpe > 0 and eff and eff > 0.5)
               else "MARGINAL — positive OOS but weak DSR / efficiency (treat as fragile)" if sharpe > 0
               else "FAILS — OOS edge does not survive capital constraints")
    print(f"\n══════ VERDICT: {verdict} ══════")
    print("  NB: the upstream decile scan selected this from 791 trials — even an OOS pass here")
    print("  should be logged to the production trial_ledger before any capital is committed.")


if __name__ == "__main__":
    main()
