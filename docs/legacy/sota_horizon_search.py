"""SOTA LONGER-HOLDING-HORIZON SEARCH — attack the terminal binding constraint (market impact).

THESIS
======
Across five prior axes (single-factor decile, PCA-orthogonal multi-factor×breadth, regime-timing,
dollar/beta-neutral long-short, prob_up-primary+HMM) the 27-factor / prob_up stack never cleared
DSR>0.95 OOS. Two distinct failure modes were isolated:
  (1) IMPACT-BOUND: the decile factors carry real-but-tiny cross-sectional info; GROSS is ~flat /
      slightly positive but Amihud market impact (≈0.10%/bar) — which scales with TURNOVER — erases
      it. Prior runs churned the book 22–51×/yr at the engine's native 5-day horizon.
  (2) NO-INFO: prob_up propensity is gross-NEGATIVE OOS (no information). Longer holds cannot add
      information that is not there → prob_up is NOT tested here.

This study attacks failure-mode (1) ONLY. Stretching the holding horizon `forward_days` ∈ {5,10,20,40,60}:
  • cuts rebalance frequency → cuts cumulative impact drag (the mechanical turnover-trick), AND
  • is a genuine SIGNAL test — cross-sectional momentum/reversal dynamics are horizon-dependent, so
    the GROSS sign/magnitude itself may change with horizon.
For EVERY cell we report BOTH gross and net so we can separate "horizon changed the signal" from
"horizon merely lowered impact".

COHORTS (gross-positive in the inversion run — the only ones worth a horizon test)
  COH-A  vol_adj_sector_alpha_14 ↑ top-decile  (offensive, market-relative; gross +12…+29% @ fd5)
  COH-B  sector_rel_mom_14_pct   ↑ top-decile  (offensive, market-relative; gross positive @ fd5)
  COH-C  atr_pct                 ↓ bottom-decile(low-ATR defensive; only marginally NET-positive @ fd5, +11%)

METHOD (non-negotiable, reuses the PRODUCTION engine — never re-implements it)
  • routers.analytics._core_wfo over the FULL 5y span (2021-05-17 → 2026-06-17). IS=365 / OOS=90 /
    embargo auto-raised to max(7, forward_days+2) → leak-safe across ALL horizons by construction.
    candidate_filters=[] ⇒ pure OOS stitch (fixed screen, NO per-window re-selection, NO OOS peeking).
    Full 5y span (not the prob_up 1y holdout) keeps trade counts credible even at a 60-day hold.
  • Pillar B (Amihud impact): impact_coef=amihud_coef=1.0 FORCED EXPLICIT on every cell (at ₹1Cr/N
    the auto-calibrator may stand down below the ADV trigger — we never let impact be silently zero).
    A per-cell pre-flight reads _auto_impact_status to PROVE the legs are live.
  • Pillar C (inverse-vol): sizing_mode="risk_parity" on every cell.
  • Both gross and net OOS CAGR reported. Net = engine NAV (impact baked in via eff=net−impact,
    backtest_engine.py:901). Gross-of-impact = net + reconstructed impact-drag (per-trade
    impact_pct × capital_allocated; the engine's compute_metrics does NOT emit turnover/impact keys).
  • DSR (Bailey & López de Prado) on the daily OOS equity-curve returns, freq=252, deflated against
    n_eff = TOTAL trial count (every cell tried — honest multiple-testing denominator).

HYGIENE: MODE=PAPER · DuckDB read_only=True · seed fixed · NO secrets hardcoded · NO look-ahead /
NO shuffle / NO skipped WFO · nothing staged / committed / pushed.
"""

from __future__ import annotations

import json
import logging
import random
import sys
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import numpy as np

# ── Bootstrap: production engine on sys.path (engine-anchors) ────────────────────────
REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "services" / "ui-api"))

import duckdb  # noqa: E402
from routers.analytics import (  # noqa: E402
    WFOBacktestRequest,
    FilterCondition,
    _core_wfo,
    _load_context,
    _auto_impact_status,
)
import backtest_engine as be  # noqa: E402
import db as _db  # noqa: E402

# ── CONFIG (all magic numbers surfaced; reproducible) ───────────────────────────────
SEED: int = 42
MODE: str = "PAPER"
CAPITAL: float = 10_000_000.0          # ₹1 Cr
FRICTION_BPS: float = 15.0             # compliance floor (CLAUDE.md: never < 0.15% round-trip)
SIZING_MODE: str = "risk_parity"       # Pillar C — inverse-vol, every cell

# WFO discipline — FULL 5y span keeps trade counts credible even at the 60-day hold
IN_SAMPLE_DAYS: int = 365
OUT_SAMPLE_DAYS: int = 90
BASE_EMBARGO_DAYS: int = 7             # auto-raised by the engine to max(7, forward_days+2)

# PRIMARY variable — the holding horizon
HORIZON_GRID: tuple[int, ...] = (5, 10, 20, 40, 60)   # 5 = native control
# Breadth: focused (horizon is primary). N=5 = the concentrated trap; N=20 = breadth-saturation point.
BREADTH_GRID: tuple[int, ...] = (5, 20)

# Forced-explicit Amihud full stack (Pillar B) — never silently zero at ₹1Cr/N
IMPACT_COEF: float = 1.0               # vol-scaled √-law temporary leg
AMIHUD_COEF: float = 1.0               # endogenous Amihud/Kyle-λ permanent leg

DSR_GATE: float = 0.95
TRADING_DAYS: int = be.TRADING_DAYS    # 252

DB_PATH: str = _db.DB_PATH
SPAN_FROM: str = "2021-05-17"
SPAN_TO: str = "2026-06-17"

OUT_CSV = REPO / "sota_horizon_results.csv"
OUT_JSON = REPO / "sota_horizon_results.json"
LOG_PATH = REPO / "sota_horizon_run.log"


@dataclass(frozen=True)
class Cohort:
    """A single long-only decile screen. `side`='top' ⇒ gte decile 10; 'bottom' ⇒ lte decile 1."""
    key: str
    label: str
    field: str
    side: str               # "top" | "bottom"
    market_relative: bool
    note: str

    def filter_condition(self) -> FilterCondition:
        if self.side == "top":
            return FilterCondition(field=self.field, op="gte", value=10.0, mode="decile")
        return FilterCondition(field=self.field, op="lte", value=1.0, mode="decile")


# The three gross-positive cohorts from the inversion run — the ONLY ones worth a horizon test.
COHORTS: list[Cohort] = [
    Cohort("COH-A", "vol_adj_sector_alpha↑D10", "vol_adj_sector_alpha_14", "top", True,
           "Offensive market-relative axis. Inversion run: GROSS +12…+29%/yr @ fd5, impact-killed NET."),
    Cohort("COH-B", "sector_rel_mom↑D10", "sector_rel_mom_14_pct", "top", True,
           "Offensive sector-relative momentum. Inversion run: GROSS positive @ fd5, impact-killed NET."),
    Cohort("COH-C", "low-ATR↓D1", "atr_pct", "bottom", False,
           "Defensive low-vol axis. Inversion run: the ONLY marginally NET-positive cohort (+11%) @ fd5."),
]


@dataclass
class CellResult:
    """One (cohort × horizon × breadth) WFO cell — measured, never asserted."""
    cohort_key: str
    cohort_label: str
    field: str
    forward_days: int
    breadth_n: int
    embargo_days: int
    n_windows: int
    total_trades: int
    surfaced_trades: int
    median_holding_days: float
    # NET (engine NAV — impact baked in)
    oos_cagr_net_pct: float
    oos_total_return_net_pct: float
    max_drawdown_pct: float
    sharpe: float
    calmar: float
    sortino: float
    win_rate: float
    # GROSS-of-impact (net + reconstructed impact drag)
    oos_cagr_gross_pct: float
    # frictions
    turnover_annual_pct: float
    impact_drag_annual_pct: float
    # benchmark + alpha
    benchmark_total_return_pct: float
    alpha_annual_pct: float
    # statistics
    dsr_engine: float
    sr_annual: float                    # the cell's own annualized Sharpe (for the trial pool)
    dsr_study: float = 0.0              # filled after the full trial pool is known
    dsr_study_n_eff: float = 0.0
    passes_dsr_gate: bool = False
    # provenance
    impact_temp_leg_on: bool = False
    impact_permanent_leg_on: bool = False
    impact_active: bool = False
    note: str = ""


# ── helpers ─────────────────────────────────────────────────────────────────────────
def _g(res: dict, k: str, d: float = 0.0) -> float:
    v = res.get(k, d)
    return d if v is None else float(v)


def oos_daily_returns(res: dict) -> np.ndarray:
    """Per-period (daily) returns from the stitched OOS equity curve."""
    eq = res.get("equity") or res.get("equity_curve") or []
    nav = np.asarray([e.get("nav") for e in eq if e.get("nav") is not None], dtype=float)
    return (nav[1:] / nav[:-1] - 1.0) if nav.size > 1 else np.array([])


def turnover_and_impact(res: dict, oos_span_days: int) -> tuple[float, float]:
    """Realized turnover (ann. % of book replaced) and realized Amihud impact drag (ann. % of NAV),
    reconstructed from the per-trade records the engine ACTUALLY emits (compute_metrics emits NO
    aggregate turnover/impact keys). Each closed trade carries `impact_pct` (temp + amihud_coef·illiq·
    alloc) and `capital_allocated`; the engine already subtracts impact from NAV (eff=net−impact,
    backtest_engine.py:901) — this ATTRIBUTES the cost, it does not re-charge it. The surfaced `trades`
    list is capped at the last 1000; `total_trades` is the truth → scale by total/len to stay unbiased.
    Returns (0.0, 0.0) only if zero OOS trades exist."""
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
    ann = (TRADING_DAYS / max(oos_span_days, 1))
    turnover_annual_pct = (deployed / cap0) * 100.0 * ann if cap0 else 0.0
    impact_drag_annual_pct = (impact_rupees / cap0) * 100.0 * ann if cap0 else 0.0
    return turnover_annual_pct, impact_drag_annual_pct


def gross_of_impact_cagr(net_cagr_pct: float, impact_drag_annual_pct: float) -> float:
    """Decompose the engine's NET (impact-baked) CAGR into GROSS-of-impact. Per-trade accounting is
    eff = net − impact (backtest_engine.py:901), so at the annualized book level the impact drag is
    additive in return space: gross-of-impact ≈ net + impact_drag. This is an attribution, not a
    re-simulation — it isolates whether HORIZON moved the SIGNAL (gross) vs merely the IMPACT."""
    return net_cagr_pct + impact_drag_annual_pct


def median_holding_days(res: dict) -> float:
    trades = res.get("trades", []) or []
    hd = [float(t.get("holding_days", 0) or 0) for t in trades if t.get("holding_days") is not None]
    return float(np.median(hd)) if hd else 0.0


def oos_span_days_for(res: dict) -> int:
    """Trading-day length of the stitched OOS track (denominator for annualization)."""
    eq = res.get("equity") or res.get("equity_curve") or []
    n = len([e for e in eq if e.get("nav") is not None])
    return max(n - 1, 1)


def build_req(cohort: Cohort, forward_days: int, n: int) -> WFOBacktestRequest:
    """One WFO request for a (cohort × horizon × breadth) cell. base_filters applies the decile screen;
    candidate_filters=[] ⇒ pure OOS stitch (fixed screen, no per-window re-selection, no OOS peeking).
    selection ranks survivors by within-sector-z of the SAME factor → the highest-conviction N names win.
    Pillars B (forced explicit Amihud) + C (risk_parity) ON. forward_days is the ONLY variable swept
    vs the fd=5 control; feature lookbacks are unchanged (the holding horizon is independent of them)."""
    fc = cohort.filter_condition()
    return WFOBacktestRequest(
        from_date=SPAN_FROM, to_date=SPAN_TO, forward_days=forward_days,
        starting_capital=CAPITAL, friction_bps=FRICTION_BPS,
        max_positions=n, scope="universe",
        sizing_mode=SIZING_MODE,
        impact_coef=IMPACT_COEF, amihud_coef=AMIHUD_COEF,   # Pillar B — FORCED explicit full stack
        base_filters=[fc],
        candidate_filters=[],                                # pure OOS stitch
        in_sample_days=IN_SAMPLE_DAYS, out_sample_days=OUT_SAMPLE_DAYS,
        embargo_days=BASE_EMBARGO_DAYS,                      # engine auto-raises to max(7, fd+2)
        selection="sector_neutral",
        selection_factor=cohort.field,
    )


def pillar_b_status(req: WFOBacktestRequest) -> dict:
    """Rebuild the sim context exactly as _core_wfo does and PROVE the Amihud legs are live."""
    fd = datetime.strptime(SPAN_FROM, "%Y-%m-%d").date()
    td = datetime.strptime(SPAN_TO, "%Y-%m-%d").date()
    need_mr = True
    ctx = _load_context(req, fd, td, need_mr, lambda *a, **k: None)
    if ctx is None:
        return {"impact_temp_leg_on": False, "impact_permanent_leg_on": False, "impact_active": False}
    st = _auto_impact_status(req, ctx)
    st["impact_active"] = bool(
        st.get("impact_temp_leg_on") or st.get("impact_permanent_leg_on")
        or st.get("impact_full_stack_auto")
    )
    return st


# ── main ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    random.seed(SEED)
    np.random.seed(SEED)

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH, mode="w"), logging.StreamHandler(sys.stdout)],
    )
    log = logging.getLogger("horizon")

    log.info("MODE=%s  DB=%s  CAPITAL=Rs%s  SEED=%d", MODE, DB_PATH, f"{CAPITAL:,.0f}", SEED)
    log.info("=== LONGER-HOLDING-HORIZON SEARCH (attack the impact wall via turnover) ===")
    log.info("Horizons fd=%s · Breadth N=%s · %d cohorts → %d cells",
             HORIZON_GRID, BREADTH_GRID, len(COHORTS),
             len(COHORTS) * len(HORIZON_GRID) * len(BREADTH_GRID))
    log.info("Pillar B Amihud FORCED explicit (impact_coef=%.1f, amihud_coef=%.1f) · Pillar C %s",
             IMPACT_COEF, AMIHUD_COEF, SIZING_MODE)

    # DB sanity (read-only) — never mutate
    con = duckdb.connect(DB_PATH, read_only=True)
    span = con.execute("SELECT min(date), max(date), count(*) FROM ohlcv").fetchone()
    con.close()
    log.info("DB span %s → %s (%s rows) [read_only]", span[0], span[1], f"{span[2]:,}")

    cells: list[CellResult] = []
    for cohort in COHORTS:
        for fd in HORIZON_GRID:
            for n in BREADTH_GRID:
                tag = f"{cohort.key} fd={fd:>2} N={n:>2}"
                req = build_req(cohort, fd, n)
                # Pillar B proof BEFORE the run
                pb = pillar_b_status(req)
                try:
                    res = _core_wfo(req)
                except Exception as exc:  # never fabricate — record the failure
                    log.exception("%s — _core_wfo FAILED: %s", tag, exc)
                    continue

                wf = res.get("walk_forward", {}) or {}
                oos_days = oos_span_days_for(res)
                turn, impact_drag = turnover_and_impact(res, oos_days)
                net_cagr = _g(res, "cagr_pct")
                gross_cagr = gross_of_impact_cagr(net_cagr, impact_drag)
                ret = oos_daily_returns(res)
                _RETURNS_CACHE[(cohort.key, fd, n)] = ret   # for the honest study-DSR pass
                sr_annual = (float(np.mean(ret) / np.std(ret, ddof=1)) * np.sqrt(TRADING_DAYS)
                             if ret.size > 2 and np.std(ret, ddof=1) > 1e-12 else 0.0)

                cell = CellResult(
                    cohort_key=cohort.key, cohort_label=cohort.label, field=cohort.field,
                    forward_days=fd, breadth_n=n,
                    embargo_days=max(BASE_EMBARGO_DAYS, fd + 2),
                    n_windows=int(wf.get("n_windows", 0) or 0),
                    total_trades=int(res.get("total_trades", 0) or 0),
                    surfaced_trades=len(res.get("trades", []) or []),
                    median_holding_days=median_holding_days(res),
                    oos_cagr_net_pct=round(net_cagr, 4),
                    oos_total_return_net_pct=round(_g(res, "total_return_pct"), 4),
                    max_drawdown_pct=round(_g(res, "max_drawdown"), 4),
                    sharpe=round(_g(res, "sharpe_ratio"), 4),
                    calmar=round(_g(res, "calmar_ratio"), 4),
                    sortino=round(_g(res, "sortino_ratio"), 4),
                    win_rate=round(_g(res, "win_rate"), 4),
                    oos_cagr_gross_pct=round(gross_cagr, 4),
                    turnover_annual_pct=round(turn, 2),
                    impact_drag_annual_pct=round(impact_drag, 4),
                    benchmark_total_return_pct=round(_g(res, "benchmark_total_return_pct"), 2),
                    alpha_annual_pct=round(_g(res, "alpha_annual_pct"), 4),
                    dsr_engine=round(float(wf.get("deflated_sharpe", 0.0) or 0.0), 4),
                    sr_annual=round(sr_annual, 4),
                    impact_temp_leg_on=bool(pb.get("impact_temp_leg_on")),
                    impact_permanent_leg_on=bool(pb.get("impact_permanent_leg_on")),
                    impact_active=bool(pb.get("impact_active")),
                    note=cohort.note,
                )
                cells.append(cell)
                log.info(
                    "%s | trades=%4d win=%2d hold~%2.0fd | NET CAGR=%7.2f%% GROSS=%7.2f%% "
                    "MaxDD=%6.1f%% Sh=%5.2f Cal=%5.2f | turn=%6.0f%%/yr impact=%5.2f%%/yr "
                    "| dsr_eng=%.3f | impact_active=%s",
                    tag, cell.total_trades, cell.n_windows, cell.median_holding_days,
                    cell.oos_cagr_net_pct, cell.oos_cagr_gross_pct, cell.max_drawdown_pct,
                    cell.sharpe, cell.calmar, cell.turnover_annual_pct,
                    cell.impact_drag_annual_pct, cell.dsr_engine, cell.impact_active,
                )

    # ── Study-level DSR: deflate every cell against the TOTAL trial count (honest n_eff) ──
    n_trials = len(cells)
    all_sharpes = [c.sr_annual for c in cells]
    n_eff = float(n_trials)
    log.info("--- STUDY DSR: deflating %d cells against n_eff=%d (ALL trials) ---", n_trials, n_trials)

    # Honest multiple-testing: each cell's FULL DSR (PSR with skew/kurt) is recomputed from its OWN
    # daily OOS returns (cached during the loop in _RETURNS_CACHE) against the pool of ALL trial Sharpes,
    # deflated with n_eff = total cell count. The engine's per-run `deflated_sharpe` (dsr_engine) deflates
    # only that run's per-window selections; this study-DSR is the cross-cell, anti-curve-fit denominator.
    for cell in cells:
        key = (cell.cohort_key, cell.forward_days, cell.breadth_n)
        ret = _RETURNS_CACHE.get(key, np.array([]))
        if ret.size > 2:
            d = be.deflated_sharpe_ratio(ret, all_sharpes, freq=TRADING_DAYS, n_eff=n_eff)
            cell.dsr_study = round(float(d.get("dsr", 0.0)), 6)
            cell.dsr_study_n_eff = float(d.get("n_eff") or n_eff)
        else:
            cell.dsr_study = 0.0
            cell.dsr_study_n_eff = n_eff
        cell.passes_dsr_gate = bool(cell.dsr_study > DSR_GATE and cell.oos_cagr_net_pct > 0.0)

    # ── persist ──
    rows = [asdict(c) for c in cells]
    OUT_JSON.write_text(json.dumps({
        "mode": MODE, "seed": SEED, "capital": CAPITAL, "db_path": DB_PATH,
        "span": [SPAN_FROM, SPAN_TO], "horizon_grid": list(HORIZON_GRID),
        "breadth_grid": list(BREADTH_GRID), "n_trials": n_trials, "n_eff": n_eff,
        "dsr_gate": DSR_GATE, "in_sample_days": IN_SAMPLE_DAYS, "out_sample_days": OUT_SAMPLE_DAYS,
        "impact_coef": IMPACT_COEF, "amihud_coef": AMIHUD_COEF, "sizing_mode": SIZING_MODE,
        "cohorts": [asdict(c) for c in COHORTS], "cells": rows,
    }, indent=2, default=str))

    import csv
    if rows:
        with OUT_CSV.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    survivors = [c for c in cells if c.passes_dsr_gate]
    log.info("=== DONE: %d cells · %d DSR>%.2f survivors · max study-DSR=%.4f ===",
             n_trials, len(survivors), DSR_GATE,
             max((c.dsr_study for c in cells), default=0.0))
    log.info("Artifacts: %s · %s · %s", OUT_CSV.name, OUT_JSON.name, LOG_PATH.name)


# Returns cache populated inside _core_wfo loop. Declared at module scope so the post-loop DSR pass
# can read each cell's daily OOS returns without a second (costly) _core_wfo call per cell.
_RETURNS_CACHE: dict[tuple, np.ndarray] = {}


if __name__ == "__main__":
    main()
