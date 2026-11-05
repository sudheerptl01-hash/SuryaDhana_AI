#!/usr/bin/env python3
"""
SOTA PROBABILISTIC RETURN-ENGINE SEARCH — ML prob_up as a PRIMARY, + HMM-conditional sizing.

CONTEXT (four axes already exhausted, all CLEAN NEGATIVE under DSR>0.95):
  1. single-factor decile screens          2. orthogonal multi-factor x breadth
  3. time-series regime-timing GATE overlay 4. dollar/beta-neutral long-short inversion
The terminal binding constraint is MARKET IMPACT (Amihud ~0.10%/bar ~3-4x borrow), NOT signal
absence. Every prior axis SELECTS cross-sectionally on the SAME 27-factor decile library, which
carries no positive OOS info net of cost (the equal-weight benchmark rose +109..+122% while every
screened cohort underperformed it).

THIS STUDY — a genuinely DIFFERENT return ENGINE (not another screen over the same factors):

  APPROACH 1 (the last distinct untested lever) — `prob_up` as the PRIMARY.
    Rank/select the book by the leak-safe out-of-sample XGBoost propensity P(up over next 5d)
    ITSELF, via:
      * a `prob_up` threshold/decile BASE filter (admit only high-propensity names), AND
      * selection="sector_neutral", selection_factor="prob_up" -> the book's final N names are the
        highest within-sector-z prob_up names (the engine's existing ranking path).
    propensity_missing="exclude" -> ONLY scored names are ever held (a pure propensity book).
    This is a NEW return engine: the cross-section is driven by the ML model's P(up), not by any
    decile factor. It is the lever the prior three verdicts each named as the only credible next bet.

  APPROACH 2 — HMM regime-CONDITIONAL sizing of the prob_up primary (not a gate over a static screen).
    The causal 2-state Gaussian-HMM posterior P(bull|data<=t) SOFT-throttles gross exposure on the
    propensity book (regime_model="hmm", regime_mode="soft"). Tests whether the propensity edge is
    regime-DEPENDENT and whether de-risking in the HMM's high-vol state improves Calmar/DSR. The HMM
    is the SAME validated causal machinery (be.gaussian_hmm_regime, separates states by VOLATILITY
    1.67% vs 0.90%); reused, not reimplemented.

LEAK-SAFE COVERAGE (MEASURED, the honesty check that gates this whole study):
  ml_oos_predictions horizon=5 spans 2025-06-02 -> 2026-06-04 (~253 trading days = exactly 1 year),
  1461 tickers, 0 leak rows (every model_trained_until=2025-05-23 < its score date). ONE frozen
  model applied forward => an EXPANDING-WINDOW HOLDOUT, not a walk-forward-retrained sequence. The
  WFO windows below are sized so EVERY OOS bar falls INSIDE this span (prob_up is NaN outside it and
  is NEVER used OOS). The IS window sits BEFORE coverage — legitimate because candidate_filters=[]
  (pure OOS stitch, the screen is FIXED, no in-sample re-selection needs prob_up). The ~1yr span is
  thin; this is reported as the limiting factor, not hidden.

METHOD (non-negotiable, identical rigor to the prior four studies):
  * Certifier: PRODUCTION routers.analytics._core_wfo — rolling IS -> embargoed OOS via the same
    _wfo_windows, contiguous OOS stitch, NO look-ahead, NO time-series shuffle, NO skipped walk-forward.
  * Pillar B (Amihud impact): impact_coef=None lets the engine auto-calibrate; a per-N pre-flight
    PROVES whether auto-Amihud fires, and FORCES the explicit full stack (impact_coef=amihud_coef=1.0,
    max_participation_pct=10) wherever it does not, so cost realism is NEVER weakened to manufacture a
    positive. friction_bps=15.0 floor (CLAUDE.md hard rule); Amihud is ADDITIVE on top.
  * Pillar C (inverse-vol): sizing_mode="risk_parity" on every cell.
  * Deflated Sharpe gate 0.95, deflated against the TOTAL trial count (every cell tried; n_eff = all
    trials), via be.deflated_sharpe_ratio(..., n_eff=n_trials).
  * Turnover / realized impact drag reported per cell (favour fewer rebalances -> longer OOS blocks).
  * MODE=PAPER, read-only DuckDB, no secrets, seed=42.

Artifacts (repo root, UNSTAGED): sota_probabilistic_engine_results.{csv,json}, this script,
SOTA_PROBABILISTIC_ENGINE_VERDICT.md. Nothing committed/pushed/staged.
"""
from __future__ import annotations

import os
import sys
import csv
import json
import random
from pathlib import Path
from datetime import datetime, timedelta, date
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

# ── Config (every knob surfaced; no magic numbers in the body) ────────────────────
CAPITAL = 10_000_000.0          # ₹1 Crore (matches every prior study for cost comparability)
FORWARD_DAYS = 5                # the propensity model's horizon (P(up over next 5d))
FRICTION_BPS = 15.0             # 0.15% floor (CLAUDE.md hard rule); Amihud is ADDITIVE on top
SIZING_MODE = "risk_parity"     # Pillar C — inverse-vol, STRICTLY ON every cell

# WFO windows sized so EVERY OOS bar lies inside the leak-safe prob_up span. With
# candidate_filters=[] the IS window only spaces the embargo (no in-sample re-selection),
# so from_date = PROB_FROM - (IS + EMBARGO) makes the FIRST OOS window start exactly at
# PROB_FROM and OOS tiles contiguously to PROB_TO. IS=120/OOS=45/emb=7 -> 9 OOS windows.
IN_SAMPLE_DAYS = 120
OUT_SAMPLE_DAYS = 45            # longer OOS blocks => fewer rebalances => lower turnover/impact drag
EMBARGO_DAYS = 7                # > forward horizon, so no IS forward-label leaks into OOS

# MEASURED leak-safe prob_up coverage (calendar dates of ml_oos_predictions horizon=5).
PROB_FROM = date(2025, 6, 2)
PROB_TO = date(2026, 6, 4)

# Breadth grid — the propensity book's capacity. Prior studies saturated by N~=20 on the
# DECILE library; re-tested here because a propensity book is a DIFFERENT cross-section and
# because larger N lowers per-slot notional -> lower per-name Amihud (the dynamic wall).
BREADTH_GRID = [10, 20, 30, 50]

DSR_GATE = 0.95                 # Phase-3 hard gate
CAGR_GATE = 0.0                 # positive OOS alpha floor

# ── The propensity-primary cell grid ─────────────────────────────────────────────
# PROB_THRESHOLD: the prob_up BASE-filter cutoff. The panel's mean is 0.505, std 0.041, max
# 0.794. A 0.50 cutoff admits ~half the scored universe (loose -> ranking does the work); a
# 0.55 cutoff (~mean+1.2std) is a tighter conviction book. "decile" admits only the daily top
# decile of prob_up (the most aggressive conviction screen). All three are pure prob_up engines.
PROB_FILTERS: list[dict] = [
    {"label": "prob>=0.50",  "kw": {"value": 0.50, "op": "gte", "mode": "absolute"}},
    {"label": "prob>=0.55",  "kw": {"value": 0.55, "op": "gte", "mode": "absolute"}},
    {"label": "prob-top-dec", "kw": {"value": 10.0, "op": "gte", "mode": "decile"}},
]

# Regime-conditional sizing variants applied on top of the prob_up primary.
#   OFF  = the bare propensity engine (control).
#   HMM-SOFT = HMM posterior P(bull) soft-throttles gross exposure (regime-CONDITIONAL sizing).
REGIME_VARIANTS: list[dict] = [
    {"label": "OFF",      "kw": {"regime_filter": False}},
    {"label": "HMM-SOFT", "kw": {"regime_filter": True, "regime_model": "hmm", "regime_mode": "soft"}},
]

# prob_up needs no market-relative join (it is a standalone attached column).
PRIMARY_FIELD = "prob_up"


def prob_base_filters(prob_kw: dict) -> list[FilterCondition]:
    """The prob_up PRIMARY screen (a pure propensity admission gate). Identical across the
    OFF and HMM-SOFT cells at a given (threshold, N), so any delta is attributable SOLELY to
    the regime-conditional sizing overlay."""
    return [FilterCondition(field=PRIMARY_FIELD, op=prob_kw["op"],
                            value=prob_kw["value"], mode=prob_kw["mode"])]


def span_for_windows() -> tuple[str, str]:
    """from_date / to_date that make the FIRST OOS window start at PROB_FROM and the LAST OOS
    window end at PROB_TO, so every OOS bar carries a leak-safe prob_up score."""
    frm = PROB_FROM - timedelta(days=IN_SAMPLE_DAYS + EMBARGO_DAYS)
    return frm.isoformat(), PROB_TO.isoformat()


def build_req(prob_kw: dict, regime_kw: dict, n: int,
              from_date: str, to_date: str) -> WFOBacktestRequest:
    """One WFO request for a (prob-threshold, regime-variant, breadth-N) cell.

    The book is the prob_up PRIMARY: base_filters admit high-propensity names; selection ranks
    the survivors by within-sector-z prob_up and keeps the top max_positions. candidate_filters=[]
    => pure OOS stitch, fixed screen, no per-window re-selection, no OOS peeking. propensity_missing
    ="exclude" => ONLY scored names are ever held (a pure leak-safe propensity book). Pillars B+C ON.
    """
    return WFOBacktestRequest(
        from_date=from_date, to_date=to_date, forward_days=FORWARD_DAYS,
        starting_capital=CAPITAL, friction_bps=FRICTION_BPS,
        max_positions=n, scope="universe",
        sizing_mode=SIZING_MODE,                 # Pillar C — inverse-vol
        impact_coef=None,                        # Pillar B — engine auto-calibrates Amihud at this N
        base_filters=prob_base_filters(prob_kw),
        candidate_filters=[],                    # empty => pure OOS stitch, no per-window re-selection
        in_sample_days=IN_SAMPLE_DAYS, out_sample_days=OUT_SAMPLE_DAYS,
        selection="sector_neutral",              # rank survivors by within-sector-z of selection_factor
        selection_factor=PRIMARY_FIELD,          # ...which IS prob_up -> highest-propensity names win
        propensity_missing="exclude",            # ONLY leak-safe scored names are held
        **regime_kw,                             # regime-conditional sizing lever (OFF | HMM-SOFT)
    )


def pillar_b_status(req: WFOBacktestRequest, from_date: str, to_date: str) -> dict:
    """Rebuild the sim context exactly as _core_wfo does and read the auto-impact status —
    PROVES whether Pillar B (Amihud) is active at this N. Never assume."""
    fd = datetime.strptime(from_date, "%Y-%m-%d").date()
    td = datetime.strptime(to_date, "%Y-%m-%d").date()
    ctx = _load_context(req, fd, td, False, lambda *a, **k: None)
    if ctx is None:
        return {"impact_active": False, "note": "context build failed",
                "propensity_pit": False, "propensity_coverage_pct": 0.0}
    st = _auto_impact_status(req, ctx)
    st["impact_active"] = bool(st.get("impact_temp_leg_on") or st.get("impact_full_stack_auto"))
    # Echo the leak-safe propensity coverage the engine itself measured over this span — the
    # honesty proof that the OOS book is on scored names, not a non-PIT fallback.
    st["propensity_pit"] = bool(getattr(ctx, "propensity_pit", False))
    st["propensity_coverage_pct"] = float(getattr(ctx, "propensity_coverage_pct", 0.0))
    st["propensity_coverage_start"] = getattr(ctx, "propensity_coverage_start", None)
    return st


def g(res: dict, k: str, d: float = 0.0) -> float:
    v = res.get(k, d)
    return d if v is None else v


def oos_daily_returns(res: dict) -> np.ndarray:
    nav = np.asarray([e["nav"] for e in res.get("equity_curve", [])], dtype=float)
    return (nav[1:] / nav[:-1] - 1.0) if nav.size > 1 else np.array([])


def turnover_and_impact(res: dict, oos_span_days: int) -> tuple[float, float]:
    """Realized turnover (annualized fraction of book replaced) and realized Amihud impact drag
    (annualized % of NAV), computed from the per-trade records the engine ACTUALLY emits.

    The core backtest charges market impact INSIDE the NAV: each closed position carries an
    `impact_pct` (temp-leg + amihud_coef * illiq * alloc) and the engine subtracts it from that
    trade's return (`eff_return_pct = net_return_pct - impact_pct`, backtest_engine.py:901). So
    the impact is already baked into the reported CAGR — this function ATTRIBUTES that cost for
    transparency, it does not re-charge it.

    * impact drag  = sum over OOS trades of (impact_pct/100 * capital_allocated) expressed as an
      annualized % of starting capital. This is the rupee Amihud cost the book actually paid.
    * turnover     = sum of capital_allocated over OOS trades / starting capital, annualized
      (each 5-day entry deploys ~1 book-slot of notional; the ratio is the # of full-book
      replacements per year).

    The engine caps the surfaced `trades` list at the last 1000; `total_trades` is the true
    count. When truncated we scale the realized sums by total_trades / len(surfaced) so the
    annualized figures stay unbiased. Returns (0.0, 0.0) only if zero OOS trades exist."""
    trades = res.get("trades", []) or []
    if not trades:
        return 0.0, 0.0
    cap0 = float(res.get("starting_capital", CAPITAL) or CAPITAL)
    total_trades = int(res.get("total_trades", len(trades)) or len(trades))
    scale = (total_trades / len(trades)) if len(trades) else 1.0
    deployed = sum(float(t.get("capital_allocated", 0.0) or 0.0) for t in trades) * scale
    impact_rupees = sum(
        (float(t.get("impact_pct", 0.0) or 0.0) / 100.0) * float(t.get("capital_allocated", 0.0) or 0.0)
        for t in trades
    ) * scale
    ann = (be.TRADING_DAYS / max(oos_span_days, 1))
    turnover_annual_pct = (deployed / cap0) * 100.0 * ann if cap0 else 0.0
    impact_drag_annual_pct = (impact_rupees / cap0) * 100.0 * ann if cap0 else 0.0
    return turnover_annual_pct, impact_drag_annual_pct


def main() -> None:
    print(f"MODE=PAPER  DB={DB_PATH}  CAPITAL=Rs{CAPITAL:,.0f}  SEED={SEED}", flush=True)
    print("=== PROBABILISTIC RETURN ENGINE — prob_up as PRIMARY + HMM-conditional sizing ===",
          flush=True)
    print("    (Pillar B Amihud + Pillar C inverse-vol STRICTLY ACTIVE every cell)", flush=True)

    from_date, to_date = span_for_windows()
    n_trials = len(PROB_FILTERS) * len(REGIME_VARIANTS) * len(BREADTH_GRID)
    print(f"  leak-safe prob_up span: {PROB_FROM} -> {PROB_TO} (~1yr, ONE frozen model)", flush=True)
    print(f"  WFO span {from_date} -> {to_date} · IS={IN_SAMPLE_DAYS}d/OOS={OUT_SAMPLE_DAYS}d/"
          f"emb={EMBARGO_DAYS}d (first OOS == prob coverage start; every OOS bar is scored)", flush=True)
    print(f"  prob thresholds={[p['label'] for p in PROB_FILTERS]} · regime={[r['label'] for r in REGIME_VARIANTS]}"
          f" · N-grid={BREADTH_GRID}", flush=True)
    print(f"  HONEST TRIAL COUNT for DSR deflation = {len(PROB_FILTERS)} x {len(REGIME_VARIANTS)} x "
          f"{len(BREADTH_GRID)} = {n_trials} trials\n", flush=True)

    # Pre-flight impact forcing ONCE PER N (auto-Amihud depends only on N + ADV, not the prob
    # threshold or regime overlay) AND confirm leak-safe propensity coverage is live.
    force_impact_by_n: dict[int, bool] = {}
    probe_filters = PROB_FILTERS[0]["kw"]
    for n in BREADTH_GRID:
        probe = build_req(probe_filters, {"regime_filter": False}, n, from_date, to_date)
        st = pillar_b_status(probe, from_date, to_date)
        force_impact_by_n[n] = not st.get("impact_active")
        print(f"  [pre-flight N={n}] impact_auto_active={st.get('impact_active')} "
              f"force_explicit_Amihud={force_impact_by_n[n]} | "
              f"propensity_pit={st.get('propensity_pit')} "
              f"coverage={st.get('propensity_coverage_pct')}% "
              f"start={st.get('propensity_coverage_start')}", flush=True)
    print("", flush=True)

    rows: list[dict] = []
    for pf in PROB_FILTERS:
        for variant in REGIME_VARIANTS:
            for n in BREADTH_GRID:
                cell = f"{pf['label']} | {variant['label']} | N={n}"
                print(f"-- WFO: {cell} --", flush=True)
                req = build_req(pf["kw"], variant["kw"], n, from_date, to_date)
                if force_impact_by_n[n]:
                    # Per-slot notional below the auto-Amihud scale trigger at this N; force the
                    # full explicit impact stack so cost realism is NEVER weakened. Identical for
                    # OFF and HMM-SOFT at this (threshold,N) -> cost parity guaranteed.
                    req.impact_coef = 1.0
                    req.amihud_coef = 1.0
                    req.max_participation_pct = 10.0
                try:
                    res = _core_wfo(req)
                except Exception as e:  # never fabricate; record the failure honestly
                    print(f"   !! ERROR {type(e).__name__}: {e}", flush=True)
                    rows.append({"prob": pf["label"], "regime": variant["label"], "N": n,
                                 "error": f"{type(e).__name__}: {e}"})
                    continue
                wf = res.get("walk_forward", {}) or {}
                oos = oos_daily_returns(res)
                # OOS span in trading days = # of stitched OOS bars (equity-curve diffs).
                oos_span_days = max(len(oos), 1)
                turn, impact = turnover_and_impact(res, oos_span_days)
                r = {
                    "prob": pf["label"], "regime": variant["label"], "N": n,
                    "oos_cagr_pct": g(res, "cagr_pct"),
                    "oos_total_return_pct": g(res, "total_return_pct"),
                    "oos_max_drawdown_pct": g(res, "max_drawdown"),
                    "sharpe": g(res, "sharpe_ratio"),
                    "sortino": g(res, "sortino_ratio"),
                    "calmar": g(res, "calmar_ratio"),
                    "win_rate": g(res, "win_rate"),
                    "profit_factor": g(res, "profit_factor"),
                    "total_trades": g(res, "total_trades"),
                    "alpha_annual_pct": g(res, "alpha_annual_pct"),
                    "beta": g(res, "beta"),
                    "benchmark_total_return_pct": g(res, "benchmark_total_return_pct"),
                    "turnover_annual_pct": turn,
                    "impact_drag_pct": impact,
                    "n_windows": wf.get("n_windows", 0),
                    "dsr_engine": wf.get("deflated_sharpe", 0.0),
                    "dsr_engine_n_trials": wf.get("dsr_n_trials", 0),
                    "force_explicit_amihud": force_impact_by_n[n],
                    "_oos_daily": oos.tolist(),
                }
                print(f"   OOS CAGR={r['oos_cagr_pct']:+.2f}%  MaxDD={r['oos_max_drawdown_pct']:.2f}%  "
                      f"Sharpe={r['sharpe']:+.3f}  Calmar={r['calmar']:+.3f}  "
                      f"bench={r['benchmark_total_return_pct']:+.1f}%  "
                      f"trades={r['total_trades']:.0f}  windows={r['n_windows']}", flush=True)
                rows.append(r)

    # ── Study-level DSR: deflate each cell's OOS Sharpe against ALL trials searched ──────
    valid = [r for r in rows if "_oos_daily" in r and len(r["_oos_daily"]) > 2]
    all_sharpes: list[float] = []
    for r in valid:
        ret = np.asarray(r["_oos_daily"], dtype=float)
        mu, sd = ret.mean(), ret.std()
        all_sharpes.append(float(mu / sd * np.sqrt(be.TRADING_DAYS)) if sd > 1e-12 else 0.0)
    n_eff = float(n_trials)   # honest multiple-testing count = every cell tried
    for r in valid:
        ret = np.asarray(r["_oos_daily"], dtype=float)
        try:
            d = be.deflated_sharpe_ratio(ret, all_sharpes, n_eff=n_eff)
            r["dsr_study"] = d.get("dsr", 0.0)
            r["dsr_study_sr_annual"] = d.get("sr_annual")
            r["dsr_study_n_trials"] = d.get("n_trials")
            r["dsr_study_n_eff"] = d.get("n_eff")
        except Exception as e:
            r["dsr_study"] = 0.0
            r["dsr_study_err"] = f"{type(e).__name__}: {e}"
            r["dsr_study_n_eff"] = n_eff

    # ── Report ──────────────────────────────────────────────────────────────────────────
    print("\n" + "=" * 96, flush=True)
    print(f"FULL {n_trials}-CELL OOS MATRIX — prob_up PRIMARY, NET of Amihud + inverse-vol (Rs1Cr)",
          flush=True)
    print("=" * 96, flush=True)
    hdr = (f"{'prob':<13}{'regime':<10}{'N':>4} | {'CAGR%':>8}{'MaxDD%':>9}{'Sharpe':>8}"
           f"{'Calmar':>8}{'Turn%':>8}{'Impact%':>9}{'DSR':>8}{'wins':>6}")
    print(hdr, flush=True)
    print("-" * len(hdr), flush=True)
    survivors = []
    for r in sorted([x for x in rows if "oos_cagr_pct" in x],
                    key=lambda z: (-z.get("dsr_study", 0.0), -z.get("calmar", 0.0))):
        dsr = r.get("dsr_study", 0.0)
        passed = (dsr > DSR_GATE) and (r["oos_cagr_pct"] > CAGR_GATE)
        if passed:
            survivors.append(r)
        print(f"{r['prob']:<13}{r['regime']:<10}{r['N']:>4} | "
              f"{r['oos_cagr_pct']:>8.2f}{r['oos_max_drawdown_pct']:>9.2f}{r['sharpe']:>8.3f}"
              f"{r['calmar']:>8.3f}{r.get('turnover_annual_pct',0.0):>8.1f}"
              f"{r.get('impact_drag_pct',0.0):>9.3f}{dsr:>8.4f}{r.get('n_windows',0):>6}"
              f"{'  <== PASS' if passed else ''}", flush=True)

    print("\n" + "=" * 96, flush=True)
    print(f"DSR gate = {DSR_GATE} (deflated against n_eff={n_eff:.0f} = ALL cells tried) · "
          f"CAGR gate > {CAGR_GATE}%", flush=True)
    print(f"SURVIVORS (positive OOS alpha AND DSR>{DSR_GATE}): {len(survivors)}", flush=True)
    if survivors:
        b = survivors[0]
        print(f"  BEST: {b['prob']} | {b['regime']} | N={b['N']}  "
              f"CAGR={b['oos_cagr_pct']:+.2f}%  Calmar={b['calmar']:+.3f}  DSR={b['dsr_study']:.4f}",
              flush=True)
    else:
        best = max([x for x in rows if "dsr_study" in x], key=lambda z: z["dsr_study"], default=None)
        if best:
            print(f"  CLEAN NEGATIVE. Max study-DSR over all {n_trials} cells = "
                  f"{best['dsr_study']:.4f} (gate {DSR_GATE}); "
                  f"best cell {best['prob']}|{best['regime']}|N={best['N']} "
                  f"CAGR={best['oos_cagr_pct']:+.2f}%.", flush=True)

    # ── Persist (strip bulky per-day arrays from the CSV; keep them in JSON) ─────────────
    csv_path = REPO / "sota_probabilistic_engine_results.csv"
    json_path = REPO / "sota_probabilistic_engine_results.json"
    csv_cols = ["prob", "regime", "N", "oos_cagr_pct", "oos_total_return_pct",
                "oos_max_drawdown_pct", "sharpe", "sortino", "calmar", "win_rate",
                "profit_factor", "total_trades", "alpha_annual_pct", "beta",
                "benchmark_total_return_pct", "turnover_annual_pct", "impact_drag_pct",
                "n_windows", "dsr_engine", "dsr_study", "dsr_study_n_eff",
                "force_explicit_amihud", "error"]
    with open(csv_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=csv_cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    meta = {
        "study": "probabilistic_return_engine_prob_up_primary",
        "mode": "PAPER", "seed": SEED, "capital": CAPITAL,
        "leak_safe_prob_span": [PROB_FROM.isoformat(), PROB_TO.isoformat()],
        "wfo": {"from": from_date, "to": to_date, "in_sample_days": IN_SAMPLE_DAYS,
                "out_sample_days": OUT_SAMPLE_DAYS, "embargo_days": EMBARGO_DAYS},
        "n_trials": n_trials, "dsr_gate": DSR_GATE, "cagr_gate": CAGR_GATE,
        "breadth_grid": BREADTH_GRID,
        "prob_filters": [p["label"] for p in PROB_FILTERS],
        "regime_variants": [r_["label"] for r_ in REGIME_VARIANTS],
        "n_survivors": len(survivors),
        "rows": [{k: v for k, v in r.items() if k != "_oos_daily"} for r in rows],
    }
    with open(json_path, "w") as fh:
        json.dump(meta, fh, indent=2, default=str)
    print(f"\nWROTE {csv_path}\nWROTE {json_path}", flush=True)


if __name__ == "__main__":
    main()
