"""sota_alpha_search.py — PHASE 2: Dynamic Breadth vs. Concentration Solver.

Tests the open thesis: is the 5-position book a CONCENTRATION TRAP that destroys
breadth-based alpha, and do ORTHOGONAL factor intersections + WIDER books (N=10/20/30)
recover (or even flip the sign of) OOS alpha — or do they merely bleed slower?

Design (config-driven, typed, seeded, reproducible — no magic numbers in the body):
  * 3 mutually-orthogonal intersections from PHASE 1 (`sota_phase1_orthogonality.py`),
    each a pure decile screen pairing decorrelated axes. The resolved combos are listed
    in COMBOS below; their Phase-1 pairwise Spearman rho are cited in each combo's note
    and must match `sota_phase1_orthogonality.json`.
  * Each combo routed through the PRODUCTION WFO engine `routers.analytics._core_wfo`
    (rolling IS->embargoed OOS, pure out-of-sample stitch: base_filters fixed, EMPTY
    candidate pool => no per-window re-selection / no OOS peeking).
  * BREADTH SWEEP: max_positions N in [5, 10, 20, 30] for every combo => 12 WFO runs.
  * Pillar B (auto-Amihud √-law + permanent Amihud + ADV cap, impact_coef=None) and
    Pillar C (inverse-vol sizing, sizing_mode="risk_parity") ACTIVE on every run. As N
    grows, per-slot notional (= CAPITAL/N) shrinks, so the Amihud penalty is DYNAMIC, not
    static — proven per N via `_auto_impact_status`.
  * Per cell: OOS CAGR, MaxDD, Calmar, Sharpe, Win%, PF, total_trades, n_windows,
    engine-DSR, realized Amihud impact status, and a STUDY-LEVEL Deflated Sharpe
    (`be.deflated_sharpe_ratio`) deflated against the FULL honest trial count
    = len(COMBOS) * len(BREADTH_GRID) = 12 trials (passed via n_eff so the multiple-
    testing denominator counts every cell searched, not just survivors).
  * Sidecar CSV -> repo root (sota_alpha_search_results.csv).

ANTI-CURVE-FIT: selection happens IN-SAMPLE inside _core_wfo; OOS is report-only. DSR
deflates against all 12 trials. No factor is reported as an edge unless it clears the
Phase-3 gate (OOS CAGR > 0 AND study-DSR > 0.95).

MODE=PAPER. Canonical Python. Read-only DB. No secrets. Capital = ₹1,00,00,000.

Run:
  /Users/sudheer/Desktop/jupyter_env/bin/python scripts/sota_alpha_search.py
"""
from __future__ import annotations

import os
import sys
import csv
import json
import random
from pathlib import Path
from datetime import datetime
from typing import Optional

import numpy as np
import duckdb

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "services" / "ui-api"))
DB_PATH = (os.environ.get("DB_PATH") or os.environ.get("DUCKDB_PATH")
           or str(REPO / "data" / "market.duckdb"))

import backtest_engine as be  # noqa: E402
from routers.analytics import (  # noqa: E402
    _core_wfo, _load_context, _auto_impact_status,
    WFOBacktestRequest, FilterCondition,
)

# ── Reproducibility ────────────────────────────────────────────────────────────
SEED = 42
random.seed(SEED)
np.random.seed(SEED)

# ── Config (all knobs surfaced; no magic numbers below this block) ───────────────
CAPITAL = 10_000_000.0          # ₹1 Crore
FORWARD_DAYS = 5
FRICTION_BPS = 15.0             # 0.15% floor (CLAUDE.md hard rule); Amihud is ADDITIVE
IN_SAMPLE_DAYS = 365
OUT_SAMPLE_DAYS = 90
SIZING_MODE = "risk_parity"     # Pillar C — inverse-vol, STRICTLY ON every run
BREADTH_GRID = [5, 10, 20, 30]  # THE concentration-vs-breadth sweep knob
DSR_GATE = 0.95                 # Phase-3 hard gate
CAGR_GATE = 0.0                 # positive OOS alpha floor

MARKET_RELATIVE = {"vol_adj_sector_alpha_14", "sector_rel_mom_14_pct", "corr_nifty_30",
                   "sector_positive_regime", "decoupled_leader", "beta_resid_5d"}

# ── The 3 ORTHOGONAL intersections (resolved from Phase 1) ───────────────────────
# spec entries: (field, op, decile). op "lte 1" = bottom decile (D1, defensive tail);
# "gte 10" = top decile (D10, offensive tail). Each combo pairs decorrelated axes so the
# screen compounds INDEPENDENT signal. Pairwise Spearman rho from Phase 1 are in `note`.
COMBOS: list[dict] = [
    {
        "name": "ORTHO-A · atr14%↓D1 ∩ VolAdjSectAlpha↑D10",
        "spec": [("atr_14_pct", "lte", 1.0),
                 ("vol_adj_sector_alpha_14", "gte", 10.0)],
        "note": "DEFENSIVE low-vol axis x OFFENSIVE vol-adjusted sector-leadership axis. "
                "Phase-1 measured Spearman rho = +0.161 (< 0.20 gate). Distinct PCs: ATR% "
                "dominates the volatility PC2 (+0.71); vol_adj_sector_alpha loads the "
                "cross-sectional-alpha PC1 (+0.48).",
    },
    {
        "name": "ORTHO-B · corr_nifty30↓D1 ∩ beta_resid_5d↑D10",
        "spec": [("corr_nifty_30", "lte", 1.0),
                 ("beta_resid_5d", "gte", 10.0)],
        "note": "DEFENSIVE market-decoupling axis (low β-correlation) x OFFENSIVE "
                "idiosyncratic-momentum axis. Phase-1 measured Spearman rho = -0.051 "
                "(strongly orthogonal): corr-to-market vs residual-of-market-beta span "
                "different axes.",
    },
    {
        # REPAIRED after Phase 1 (2026-06-18): the original triple
        # (dist_ma200_pct ∩ sector_rel_mom_14_pct ∩ atr_14_pct) FAILED the |rho|<0.20 gate —
        # measured Spearman dist_ma200 x sector_rel_mom = +0.39 and dist_ma200 x atr = +0.22,
        # i.e. dist_ma200_pct is collinear with both the momentum cluster (shares PC1/PC3) and
        # the volatility axis. Reporting it would have been a curve-fit redundancy.
        # Replaced with the cleanest orthogonal triple in the measured matrix:
        "name": "ORTHO-C · corr_nifty30↓D1 ∩ squeeze_ratio↓D1 ∩ beta_resid_5d↑D10",
        "spec": [("corr_nifty_30", "lte", 1.0),
                 ("squeeze_ratio", "lte", 1.0),
                 ("beta_resid_5d", "gte", 10.0)],
        "note": "3-way orthogonal triple, all pairwise |rho| < 0.06 (Phase-1 measured): "
                "corr_nifty_30 x squeeze_ratio = -0.034, corr_nifty_30 x beta_resid_5d = -0.051, "
                "squeeze_ratio x beta_resid_5d = +0.027. Spans 3 distinct PCs — corr_nifty_30 "
                "(market-decoupling, PC2/PC4), squeeze_ratio (volatility-compression, dominant "
                "PC4 loader +0.77), beta_resid_5d (idiosyncratic momentum, PC1). "
                "DEFENSIVE decoupling x DEFENSIVE compression x OFFENSIVE residual-momentum.",
    },
]


def decile_filters(spec: list[tuple]) -> list[FilterCondition]:
    """Resolve a combo spec into production decile FilterConditions."""
    return [FilterCondition(field=f, op=op, value=v, mode="decile") for (f, op, v) in spec]


def date_span(con) -> tuple[str, str]:
    mn, mx = con.execute("SELECT min(date), max(date) FROM ohlcv").fetchone()
    return str(mn), str(mx)


def build_req(spec: list[tuple], n: int, from_date: str, to_date: str) -> WFOBacktestRequest:
    """One WFO request for a (combo, breadth-N) cell. Pillars B+C wired ON."""
    return WFOBacktestRequest(
        from_date=from_date, to_date=to_date, forward_days=FORWARD_DAYS,
        starting_capital=CAPITAL, friction_bps=FRICTION_BPS,
        max_positions=n, scope="universe",
        sizing_mode=SIZING_MODE,        # Pillar C — inverse-vol
        impact_coef=None,               # Pillar B — engine auto-calibrates Amihud at this N
        base_filters=decile_filters(spec),
        candidate_filters=[],           # empty => pure OOS stitch, no per-window re-selection
        in_sample_days=IN_SAMPLE_DAYS, out_sample_days=OUT_SAMPLE_DAYS,
    )


def pillar_b_status(req: WFOBacktestRequest, from_date: str, to_date: str) -> dict:
    """Build the sim context exactly as _core_wfo does and read the auto-impact status —
    PROVES Pillar B is (or is not) active at this N. Never assume."""
    fd = datetime.strptime(from_date, "%Y-%m-%d").date()
    td = datetime.strptime(to_date, "%Y-%m-%d").date()
    need_mr = any(f.field in MARKET_RELATIVE for f in req.base_filters)
    ctx = _load_context(req, fd, td, need_mr, lambda *a, **k: None)
    if ctx is None:
        return {"impact_active": False, "note": "context build failed"}
    st = _auto_impact_status(req, ctx)
    st["impact_active"] = bool(st.get("impact_temp_leg_on") or st.get("impact_full_stack_auto"))
    return st


def g(res: dict, k: str, d: float = 0.0) -> float:
    v = res.get(k, d)
    return d if v is None else v


def oos_daily_returns(res: dict) -> np.ndarray:
    nav = np.asarray([e["nav"] for e in res.get("equity", [])], dtype=float)
    return (nav[1:] / nav[:-1] - 1.0) if nav.size > 1 else np.array([])


def main() -> None:
    print(f"MODE=PAPER  DB={DB_PATH}  CAPITAL=₹{CAPITAL:,.0f}  SEED={SEED}", flush=True)
    print("=== PHASE 2 — DYNAMIC BREADTH SWEEP (Pillar B + Pillar C STRICTLY ACTIVE) ===",
          flush=True)
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        from_date, to_date = date_span(con)
    finally:
        con.close()
    n_trials = len(COMBOS) * len(BREADTH_GRID)   # honest multiple-testing count = 12
    print(f"  span {from_date} -> {to_date} · IS={IN_SAMPLE_DAYS}d/OOS={OUT_SAMPLE_DAYS}d · "
          f"N-grid={BREADTH_GRID} · friction=15bps+auto-Amihud · sizing=inverse-vol", flush=True)
    print(f"  HONEST TRIAL COUNT for DSR deflation = {len(COMBOS)} combos x "
          f"{len(BREADTH_GRID)} breadths = {n_trials} trials\n", flush=True)

    rows: list[dict] = []
    for combo in COMBOS:
        for n in BREADTH_GRID:
            cell = f"{combo['name']}  |  N={n}"
            print(f"── WFO: {cell} ──", flush=True)
            req = build_req(combo["spec"], n, from_date, to_date)

            # Pillar B activation proof at THIS N (dynamic: larger N => smaller per-slot
            # notional => lower per-name Amihud impact, but the leg stays live).
            pb = pillar_b_status(req, from_date, to_date)
            if not pb.get("impact_active"):
                # Only force explicit legs if auto failed to fire AT ALL (documented fallback).
                req.impact_coef = 1.0
                req.amihud_coef = 1.0
                req.max_participation_pct = 10.0
                pb["forced_explicit"] = True
                print(f"   ⚠ auto-impact did not fire at N={n}; forced explicit "
                      f"impact_coef/amihud_coef.", flush=True)
            pb_legs = {k: pb[k] for k in pb
                       if k.startswith("impact") or k == "forced_explicit"}
            print(f"   Pillar B: {json.dumps(pb_legs, default=str)}", flush=True)

            res = _core_wfo(req)
            wf = res.get("walk_forward", {})
            rec = {
                "combo": combo["name"], "N": n,
                "n_windows": wf.get("n_windows", 0),
                "oos_cagr_pct": round(g(res, "cagr_pct"), 4),
                "oos_total_return_pct": round(g(res, "total_return_pct"), 4),
                "oos_maxdd_pct": round(g(res, "max_drawdown"), 4),
                "calmar": round(g(res, "calmar_ratio"), 4),
                "sharpe": round(g(res, "sharpe_ratio"), 4),
                "sortino": round(g(res, "sortino_ratio"), 4),
                "win_pct": round(g(res, "win_rate"), 3),
                "profit_factor": round(g(res, "profit_factor"), 4),
                "total_trades": int(g(res, "total_trades")),
                "alpha_annual_pct": round(g(res, "alpha_annual_pct"), 4),
                "beta": round(g(res, "beta"), 4),
                "bench_return_pct": round(g(res, "benchmark_total_return_pct"), 4),
                "dsr_engine": wf.get("deflated_sharpe", 0.0),
                "dsr_n_trials_engine": wf.get("dsr_n_trials", 0),
                "efficiency": wf.get("efficiency"),
                "impact_active": bool(pb.get("impact_active") or pb.get("forced_explicit")),
                "impact_full_stack_auto": bool(pb.get("impact_full_stack_auto")),
                "auto_participation_pct": pb.get("auto_participation_pct"),
                "_oos_daily": oos_daily_returns(res),
            }
            rows.append(rec)
            print(f"   windows={rec['n_windows']}  OOS CAGR={rec['oos_cagr_pct']:+.2f}%  "
                  f"MaxDD={rec['oos_maxdd_pct']:.2f}%  Calmar={rec['calmar']:.3f}  "
                  f"Sharpe={rec['sharpe']:.3f}  Win={rec['win_pct']:.1f}%  "
                  f"PF={rec['profit_factor']:.2f}  trades={rec['total_trades']:,}\n", flush=True)

    # ── STUDY-LEVEL Deflated Sharpe — deflate every cell against ALL 12 trials ──
    # Multiple-testing honesty: n_eff = full trial count (every (combo,N) cell searched),
    # and trial_sharpes = the 12 OOS Sharpes so the dispersion term is the real search.
    all_sharpes = [float(r["sharpe"]) for r in rows]
    for r in rows:
        if r["_oos_daily"].size > 1:
            d = be.deflated_sharpe_ratio(r["_oos_daily"], all_sharpes, n_eff=float(n_trials))
            r["dsr_study"] = round(d["dsr"], 4)
            r["dsr_study_n_trials"] = d["n_trials"]
            r["dsr_study_n_eff"] = d.get("n_eff")
        else:
            r["dsr_study"] = 0.0
            r["dsr_study_n_trials"] = n_trials
            r["dsr_study_n_eff"] = float(n_trials)

    # ── Results matrix ──
    print("══════ FULL 12-CELL OOS MATRIX — NET of Amihud impact + inverse-vol (₹1Cr) ══════",
          flush=True)
    hdr = (f"  {'Combo':46s} {'N':>3} {'CAGR%':>8} {'MaxDD%':>8} {'Calmar':>7} "
           f"{'Sharpe':>7} {'DSR':>7} {'Win%':>6} {'PF':>6} {'trades':>7} {'impact':>7}")
    print(hdr, flush=True)
    for r in rows:
        print(f"  {r['combo'][:46]:46s} {r['N']:>3d} {r['oos_cagr_pct']:>8.2f} "
              f"{r['oos_maxdd_pct']:>8.2f} {r['calmar']:>7.3f} {r['sharpe']:>7.3f} "
              f"{r['dsr_study']:>7.3f} {r['win_pct']:>6.1f} {r['profit_factor']:>6.2f} "
              f"{r['total_trades']:>7,} {('ON' if r['impact_active'] else 'OFF'):>7}", flush=True)

    # ── Sidecar CSV (repo root) ──
    csv_path = REPO / "sota_alpha_search_results.csv"
    field_order = ["combo", "N", "n_windows", "oos_cagr_pct", "oos_total_return_pct",
                   "oos_maxdd_pct", "calmar", "sharpe", "sortino", "win_pct",
                   "profit_factor", "total_trades", "alpha_annual_pct", "beta",
                   "bench_return_pct", "dsr_engine", "dsr_n_trials_engine", "efficiency",
                   "dsr_study", "dsr_study_n_trials", "dsr_study_n_eff", "impact_active",
                   "impact_full_stack_auto", "auto_participation_pct"]
    with csv_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=field_order, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\n  wrote {csv_path.name}", flush=True)

    # ── Phase-3 gate evaluation (Pareto over Calmar s.t. DSR>0.95 AND CAGR>0) ──
    survivors = [r for r in rows
                 if r["oos_cagr_pct"] > CAGR_GATE and r["dsr_study"] > DSR_GATE]
    print("\n══════ PHASE-3 GATE (OOS CAGR>0 AND study-DSR>0.95) ══════", flush=True)
    if survivors:
        # Pareto-max Calmar among survivors.
        best = max(survivors, key=lambda r: r["calmar"])
        print(f"  {len(survivors)} cell(s) clear the bar. Pareto-best (max Calmar): "
              f"{best['combo']} @ N={best['N']} — CAGR {best['oos_cagr_pct']:+.2f}%, "
              f"Calmar {best['calmar']:.3f}, DSR {best['dsr_study']:.3f}", flush=True)
        # Minimum surviving breadth across all surviving combos.
        min_n = min(r["N"] for r in survivors)
        print(f"  MINIMUM BREADTH N that survives the impact penalty = {min_n}", flush=True)
    else:
        best = max(rows, key=lambda r: (r["oos_cagr_pct"], r["dsr_study"]))
        print("  NO (combo,N) cell clears positive OOS CAGR with DSR>0.95.", flush=True)
        print(f"  LEAST-BAD: {best['combo']} @ N={best['N']} — CAGR "
              f"{best['oos_cagr_pct']:+.2f}%, MaxDD {best['oos_maxdd_pct']:.2f}%, "
              f"DSR {best['dsr_study']:.3f}", flush=True)
        # Did breadth monotonically improve the sign for the best combo?
        for combo in COMBOS:
            seq = sorted([r for r in rows if r["combo"] == combo["name"]], key=lambda r: r["N"])
            trend = " -> ".join(f"N{r['N']}:{r['oos_cagr_pct']:+.1f}%" for r in seq)
            print(f"    breadth trend [{combo['name'][:30]}]: {trend}", flush=True)

    # Persist machine-readable matrix for the Phase-3 report writer.
    out = REPO / "sota_alpha_search_results.json"
    out.write_text(json.dumps(
        [{k: v for k, v in r.items() if k != "_oos_daily"} for r in rows],
        indent=2, default=str))
    print(f"\nPHASE2_DONE — {len(rows)} cells · honest trial count={n_trials} · "
          f"wrote {out.name}", flush=True)


if __name__ == "__main__":
    main()
