"""sota_regime_timing_search.py — NEW AXIS: time-series REGIME-TIMING overlay on a BROAD book.

================================================================================
WHY THIS IS ORTHOGONAL TO THE FALSIFIED LIBRARY (the mechanism, not the name)
================================================================================
Everything killed so far selects CROSS-SECTIONALLY: rank the 27-factor library on a
bar, hold the top/bottom decile. The post-mortem (SOTA_COMBINATORIAL_VERDICT.md) is
unambiguous — over the OOS span the equal-weight BENCHMARK returned +109%..+122% while
every screened cohort underperformed it deeply, gross of impact. Conclusion: the
SELECTION AXIS itself carries no positive OOS information. Widening N never flipped the
sign; signals lose on PRICE before Amihud is debited.

This experiment changes the axis entirely. Instead of asking "WHICH names" (a
cross-sectional bet that has been exhaustively falsified), it asks "WHEN to hold market
exposure" — a TIME-SERIES bet on the benchmark's own regime state. The lever is the
production `regime_filter`:
  * SMA-gate : benchmark below its trailing SMA(200) ⇒ block new entries (go to cash).
  * HMM-gate : causal 2-state Gaussian-HMM P(bull|data≤t) < 0.5 ⇒ block new entries.
  * HMM-soft : scale every name's allocation by P(bull) ∈ [0,1] — a smooth gross throttle.
All three are strictly trailing / causal (no look-ahead): the SMA and the HMM filter at
bar T use only benchmark returns ≤ T. The overlay rides a BROAD, near-neutral book
(N ∈ {30,50,100}, light momentum-participation primary) so the timing signal expresses
on a diversified substrate instead of on 5 idiosyncratic names — directly testing the
prior note that hundreds of names diversify idiosyncratic blowups that the 5–30 cap
destroys.

Orthogonality is mechanical, not cosmetic: the regime signal is computed from the
BENCHMARK index series, not from any per-name cross-sectional rank. It is uncorrelated by
construction with the decile factor library — it does not touch the names; it touches the
TIME at which the book is allowed to be long.

================================================================================
EXPERIMENT DESIGN
================================================================================
  * Substrate (primary): a BROAD book over the full universe with a light, near-neutral
    trend-participation screen (`dist_ma200_pct gte 0` decile-free threshold — "above the
    200-day MA"), so the book holds a wide cross-section of uptrending names. No
    cross-sectional alpha is claimed from this screen; it is just a long-only participation
    gate. (A pure unscreened book is also run as REGIME-OFF control via the same primary.)
  * Overlay sweep: REGIME ∈ {OFF (control), SMA-GATE, HMM-GATE, HMM-SOFT}.
  * Breadth sweep:  N ∈ {30, 50, 100} (genuinely broad — past study saturated by N≈20).
  * => 4 × 3 = 12 WFO cells. The OFF cells are the CONTROL: the overlay only earns its
    keep if a regime cell beats its own N-matched OFF cell on Calmar / MaxDD.
  * Certifier: PRODUCTION `routers.analytics._core_wfo` — rolling IS=365d → embargoed
    OOS=90d, pure out-of-sample stitch (base_filters fixed, EMPTY candidate pool ⇒ no
    per-window re-selection, no OOS peeking, no look-ahead, no shuffle).
  * Pillar B (auto-Amihud √-law + permanent Amihud + ADV cap, impact_coef=None) and
    Pillar C (inverse-vol sizing, sizing_mode="risk_parity") ACTIVE on every cell. As N
    grows, per-slot notional = CAPITAL/N shrinks ⇒ the Amihud penalty is DYNAMIC.
  * DSR: study-level Deflated Sharpe deflated against the FULL honest trial count
    n_eff = 4 regimes × 3 breadths = 12 (every cell searched, not just survivors).

GATE (unchanged rigor): a cell is an EDGE only if OOS CAGR > 0 AND study-DSR > 0.95 AND
it beats its N-matched REGIME-OFF control on Calmar. Friction floor 15bps + additive
Amihud; never weakened. MODE=PAPER, read-only DuckDB, no secrets, seed=42.

Run:
  /Users/sudheer/Desktop/jupyter_env/bin/python sota_regime_timing_search.py
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

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "services" / "ui-api"))
DB_PATH = (os.environ.get("DB_PATH") or os.environ.get("DUCKDB_PATH")
           or str(REPO / "data" / "market.duckdb"))

import backtest_engine as be  # noqa: E402
from routers.analytics import (  # noqa: E402
    _core_wfo, _load_context, _auto_impact_status,
    WFOBacktestRequest, FilterCondition,
)

# ── Reproducibility ──────────────────────────────────────────────────────────────
SEED = 42
random.seed(SEED)
np.random.seed(SEED)

# ── Config (all knobs surfaced; no magic numbers in the body) ─────────────────────
CAPITAL = 10_000_000.0          # ₹1 Crore
FORWARD_DAYS = 5
FRICTION_BPS = 15.0             # 0.15% floor (CLAUDE.md hard rule); Amihud is ADDITIVE
IN_SAMPLE_DAYS = 365
OUT_SAMPLE_DAYS = 90
SIZING_MODE = "risk_parity"     # Pillar C — inverse-vol, STRICTLY ON every cell
BREADTH_GRID = [30, 50, 100]    # GENUINELY broad books (past study saturated by N≈20)
DSR_GATE = 0.95                 # Phase-3 hard gate
CAGR_GATE = 0.0                 # positive OOS alpha floor

# Light, near-neutral long-only PARTICIPATION primary: the boolean "price above its own
# 200-day MA" flag (`price_gt_ma200`). This is NOT a cross-sectional alpha claim — it is a
# broad per-NAME trend-participation gate so the book holds a wide diversified cross-section
# of uptrending names on which the TIME-SERIES regime overlay can express. It is deliberately
# the per-name flag, NOT a benchmark-level threshold, so it does not overlap the regime
# overlay's benchmark-SMA/HMM logic. Applied identically to every cell (control too), so any
# Calmar/MaxDD delta between a regime cell and its N-matched OFF cell is attributable SOLELY
# to the regime overlay, not the primary.
PRIMARY_FIELD = "price_gt_ma200"
PRIMARY_OP = "gte"
PRIMARY_VALUE = 1.0             # boolean flag == 1 (mode="absolute"): name trades above its 200DMA

MARKET_RELATIVE = {"vol_adj_sector_alpha_14", "sector_rel_mom_14_pct", "corr_nifty_30",
                   "sector_positive_regime", "decoupled_leader", "beta_resid_5d"}

# ── The regime-timing overlay variants ────────────────────────────────────────────
# Each variant is a (label, kwargs-into-WFOBacktestRequest) pair. "OFF" is the control:
# the SAME broad book with NO exposure timing — the benchmark against which the overlay
# must prove marginal Calmar.
REGIME_VARIANTS: list[dict] = [
    {"label": "OFF (control)", "kw": {"regime_filter": False}},
    {"label": "SMA-GATE",      "kw": {"regime_filter": True, "regime_model": "sma",  "regime_mode": "gate"}},
    {"label": "HMM-GATE",      "kw": {"regime_filter": True, "regime_model": "hmm",  "regime_mode": "gate"}},
    {"label": "HMM-SOFT",      "kw": {"regime_filter": True, "regime_model": "hmm",  "regime_mode": "soft"}},
]


def primary_filters() -> list[FilterCondition]:
    """The light long-only participation primary, identical across every cell."""
    return [FilterCondition(field=PRIMARY_FIELD, op=PRIMARY_OP, value=PRIMARY_VALUE, mode="absolute")]


def date_span(con) -> tuple[str, str]:
    mn, mx = con.execute("SELECT min(date), max(date) FROM ohlcv").fetchone()
    return str(mn), str(mx)


def build_req(regime_kw: dict, n: int, from_date: str, to_date: str) -> WFOBacktestRequest:
    """One WFO request for a (regime-variant, breadth-N) cell. Pillars B+C wired ON.

    candidate_filters is EMPTY ⇒ pure OOS stitch with the fixed broad primary, no
    per-window re-selection, no OOS peeking. The regime overlay is the ONLY thing that
    differs between a variant and its OFF control at a given N.
    """
    return WFOBacktestRequest(
        from_date=from_date, to_date=to_date, forward_days=FORWARD_DAYS,
        starting_capital=CAPITAL, friction_bps=FRICTION_BPS,
        max_positions=n, scope="universe",
        sizing_mode=SIZING_MODE,        # Pillar C — inverse-vol
        impact_coef=None,               # Pillar B — engine auto-calibrates Amihud at this N
        base_filters=primary_filters(),
        candidate_filters=[],           # empty ⇒ pure OOS stitch, no per-window re-selection
        in_sample_days=IN_SAMPLE_DAYS, out_sample_days=OUT_SAMPLE_DAYS,
        **regime_kw,                    # THE lever: regime_filter / model / mode
    )


def pillar_b_status(req: WFOBacktestRequest, from_date: str, to_date: str) -> dict:
    """Rebuild the sim context exactly as _core_wfo does and read the auto-impact status —
    PROVES Pillar B (Amihud) is (or is not) active at this N. Never assume."""
    fd = datetime.strptime(from_date, "%Y-%m-%d").date()
    td = datetime.strptime(to_date, "%Y-%m-%d").date()
    need_mr = any(f.field in MARKET_RELATIVE for f in req.base_filters)
    ctx = _load_context(req, fd, td, need_mr, lambda *a, **k: None)
    if ctx is None:
        return {"impact_active": False, "note": "context build failed"}
    st = _auto_impact_status(req, ctx)
    st["impact_active"] = bool(st.get("impact_temp_leg_on") or st.get("impact_full_stack_auto"))
    # Surface whether the regime classifier actually populated a per-date map (proof the
    # overlay is live, not silently inert).
    st["regime_meta"] = ctx.regime_meta
    st["regime_dates"] = (len(ctx.regime_ok) if getattr(ctx, "regime_ok", None) else 0)
    st["regime_scale_dates"] = (len(ctx.regime_scale) if getattr(ctx, "regime_scale", None) else 0)
    return st


def g(res: dict, k: str, d: float = 0.0) -> float:
    v = res.get(k, d)
    return d if v is None else v


def oos_daily_returns(res: dict) -> np.ndarray:
    nav = np.asarray([e["nav"] for e in res.get("equity_curve", [])], dtype=float)
    return (nav[1:] / nav[:-1] - 1.0) if nav.size > 1 else np.array([])


def main() -> None:
    print(f"MODE=PAPER  DB={DB_PATH}  CAPITAL=Rs{CAPITAL:,.0f}  SEED={SEED}", flush=True)
    print("=== NEW AXIS — TIME-SERIES REGIME-TIMING OVERLAY ON A BROAD BOOK ===", flush=True)
    print("    (Pillar B auto-Amihud + Pillar C inverse-vol STRICTLY ACTIVE every cell)",
          flush=True)
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        from_date, to_date = date_span(con)
    finally:
        con.close()

    n_trials = len(REGIME_VARIANTS) * len(BREADTH_GRID)   # honest multiple-testing count = 12
    print(f"  span {from_date} -> {to_date} · IS={IN_SAMPLE_DAYS}d/OOS={OUT_SAMPLE_DAYS}d · "
          f"N-grid={BREADTH_GRID} · friction=15bps+auto-Amihud · sizing=inverse-vol", flush=True)
    print(f"  primary (participation): {PRIMARY_FIELD} {PRIMARY_OP} {PRIMARY_VALUE} (value-mode)",
          flush=True)
    print(f"  HONEST TRIAL COUNT for DSR deflation = {len(REGIME_VARIANTS)} regimes x "
          f"{len(BREADTH_GRID)} breadths = {n_trials} trials\n", flush=True)

    # Decide impact forcing ONCE PER N (auto-Amihud depends only on N + ADV, not the regime
    # overlay), so the OFF control and every overlay cell at a given N carry an IDENTICAL
    # cost stack — the only thing that varies within an N-block is the regime timing.
    force_impact_by_n: dict[int, bool] = {}
    for n in BREADTH_GRID:
        probe = build_req({"regime_filter": False}, n, from_date, to_date)
        st = pillar_b_status(probe, from_date, to_date)
        force_impact_by_n[n] = not st.get("impact_active")
        print(f"  [impact pre-flight N={n}] auto_active={st.get('impact_active')} "
              f"full_stack_auto={st.get('impact_full_stack_auto')} "
              f"=> force_explicit={force_impact_by_n[n]}", flush=True)
    print("", flush=True)

    rows: list[dict] = []
    for variant in REGIME_VARIANTS:
        for n in BREADTH_GRID:
            cell = f"{variant['label']}  |  N={n}"
            print(f"-- WFO: {cell} --", flush=True)
            req = build_req(variant["kw"], n, from_date, to_date)

            if force_impact_by_n[n]:
                # Per-slot notional is below the auto-Amihud scale trigger at this N; force the
                # full explicit impact stack so cost realism is NEVER weakened to manufacture a
                # positive. Identical for OFF control and overlay at this N (parity guaranteed).
                req.impact_coef = 1.0
                req.amihud_coef = 1.0
                req.max_participation_pct = 10.0

            pb = pillar_b_status(req, from_date, to_date)
            if force_impact_by_n[n]:
                pb["forced_explicit"] = True
                pb["impact_active"] = True   # explicit legs are now on
            print(f"   Pillar B: impact_active={pb.get('impact_active')} "
                  f"full_stack_auto={pb.get('impact_full_stack_auto')} | "
                  f"regime_meta={pb.get('regime_meta')} "
                  f"regime_dates={pb.get('regime_dates')} "
                  f"regime_scale_dates={pb.get('regime_scale_dates')}", flush=True)

            res = _core_wfo(req)
            wf = res.get("walk_forward", {})
            rec = {
                "regime": variant["label"], "N": n,
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
                "regime_meta": json.dumps(pb.get("regime_meta"), default=str),
                "regime_dates": pb.get("regime_dates"),
                "regime_scale_dates": pb.get("regime_scale_dates"),
                "_oos_daily": oos_daily_returns(res),
            }
            rows.append(rec)
            print(f"   windows={rec['n_windows']}  OOS CAGR={rec['oos_cagr_pct']:+.2f}%  "
                  f"MaxDD={rec['oos_maxdd_pct']:.2f}%  Calmar={rec['calmar']:.3f}  "
                  f"Sharpe={rec['sharpe']:.3f}  Win={rec['win_pct']:.1f}%  "
                  f"benchOOS={rec['bench_return_pct']:+.1f}%  trades={rec['total_trades']:,}\n",
                  flush=True)

    # ── STUDY-LEVEL Deflated Sharpe — deflate every cell against ALL 12 trials ──
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

    # ── Marginal-overlay contrast: each regime cell vs its N-matched OFF control ──
    off_by_n = {r["N"]: r for r in rows if r["regime"].startswith("OFF")}
    for r in rows:
        ctrl = off_by_n.get(r["N"])
        if ctrl is not None and not r["regime"].startswith("OFF"):
            r["d_calmar_vs_off"] = round(r["calmar"] - ctrl["calmar"], 4)
            r["d_maxdd_vs_off"] = round(r["oos_maxdd_pct"] - ctrl["oos_maxdd_pct"], 4)
            r["d_cagr_vs_off"] = round(r["oos_cagr_pct"] - ctrl["oos_cagr_pct"], 4)
        else:
            r["d_calmar_vs_off"] = 0.0
            r["d_maxdd_vs_off"] = 0.0
            r["d_cagr_vs_off"] = 0.0

    # ── Results matrix ──
    print("====== FULL 12-CELL OOS MATRIX — NET of Amihud impact + inverse-vol (Rs1Cr) ======",
          flush=True)
    hdr = (f"  {'Regime':16s} {'N':>4} {'CAGR%':>8} {'MaxDD%':>8} {'Calmar':>7} "
           f"{'Sharpe':>7} {'DSR':>7} {'dCalmar':>8} {'dMaxDD':>8} {'benchOOS%':>9} {'imp':>4}")
    print(hdr, flush=True)
    for r in rows:
        print(f"  {r['regime']:16s} {r['N']:>4d} {r['oos_cagr_pct']:>8.2f} "
              f"{r['oos_maxdd_pct']:>8.2f} {r['calmar']:>7.3f} {r['sharpe']:>7.3f} "
              f"{r['dsr_study']:>7.3f} {r['d_calmar_vs_off']:>8.3f} {r['d_maxdd_vs_off']:>8.2f} "
              f"{r['bench_return_pct']:>9.1f} {('ON' if r['impact_active'] else 'OFF'):>4}",
              flush=True)

    # ── Sidecar CSV (repo root) ──
    csv_path = REPO / "sota_regime_timing_results.csv"
    field_order = ["regime", "N", "n_windows", "oos_cagr_pct", "oos_total_return_pct",
                   "oos_maxdd_pct", "calmar", "sharpe", "sortino", "win_pct",
                   "profit_factor", "total_trades", "alpha_annual_pct", "beta",
                   "bench_return_pct", "dsr_engine", "dsr_n_trials_engine", "efficiency",
                   "dsr_study", "dsr_study_n_trials", "dsr_study_n_eff",
                   "d_calmar_vs_off", "d_maxdd_vs_off", "d_cagr_vs_off",
                   "impact_active", "impact_full_stack_auto",
                   "regime_meta", "regime_dates", "regime_scale_dates"]
    with csv_path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=field_order, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"\n  wrote {csv_path.name}", flush=True)

    # ── Gate evaluation (Pareto over Calmar s.t. DSR>0.95 AND CAGR>0 AND beats OFF control) ──
    survivors = [r for r in rows
                 if r["oos_cagr_pct"] > CAGR_GATE and r["dsr_study"] > DSR_GATE
                 and not r["regime"].startswith("OFF")
                 and r["d_calmar_vs_off"] > 0.0]
    print("\n====== GATE (OOS CAGR>0 AND study-DSR>0.95 AND beats N-matched OFF on Calmar) ======",
          flush=True)
    if survivors:
        best = max(survivors, key=lambda r: r["calmar"])
        print(f"  {len(survivors)} cell(s) clear the bar. Pareto-best (max Calmar): "
              f"{best['regime']} @ N={best['N']} — CAGR {best['oos_cagr_pct']:+.2f}%, "
              f"Calmar {best['calmar']:.3f}, DSR {best['dsr_study']:.3f}, "
              f"dCalmar vs OFF {best['d_calmar_vs_off']:+.3f}", flush=True)
        min_n = min(r["N"] for r in survivors)
        print(f"  MINIMUM BREADTH N that survives = {min_n}", flush=True)
    else:
        best = max(rows, key=lambda r: (r["oos_cagr_pct"], r["dsr_study"]))
        print("  NO regime-overlay cell clears positive OOS CAGR with DSR>0.95 while beating "
              "its OFF control on Calmar.", flush=True)
        print(f"  BEST OVERALL CELL: {best['regime']} @ N={best['N']} — CAGR "
              f"{best['oos_cagr_pct']:+.2f}%, MaxDD {best['oos_maxdd_pct']:.2f}%, "
              f"Calmar {best['calmar']:.3f}, DSR {best['dsr_study']:.3f}", flush=True)
        # Did the overlay reduce drawdown at all (Calmar contribution), even if not gate-passing?
        for n in BREADTH_GRID:
            cells = [r for r in rows if r["N"] == n]
            ctrl = off_by_n.get(n)
            print(f"    N={n}: OFF Calmar={ctrl['calmar']:.3f} MaxDD={ctrl['oos_maxdd_pct']:.2f}% "
                  f"CAGR={ctrl['oos_cagr_pct']:+.1f}%", flush=True)
            for r in cells:
                if r["regime"].startswith("OFF"):
                    continue
                print(f"        {r['regime']:10s} Calmar={r['calmar']:.3f} "
                      f"(d{r['d_calmar_vs_off']:+.3f}) MaxDD={r['oos_maxdd_pct']:.2f}% "
                      f"(d{r['d_maxdd_vs_off']:+.2f}) CAGR={r['oos_cagr_pct']:+.1f}% "
                      f"(d{r['d_cagr_vs_off']:+.1f})", flush=True)

    out = REPO / "sota_regime_timing_results.json"
    out.write_text(json.dumps(
        [{k: v for k, v in r.items() if k != "_oos_daily"} for r in rows],
        indent=2, default=str))
    print(f"\nREGIME_TIMING_DONE — {len(rows)} cells · honest trial count={n_trials} · "
          f"wrote {out.name}", flush=True)


if __name__ == "__main__":
    main()
