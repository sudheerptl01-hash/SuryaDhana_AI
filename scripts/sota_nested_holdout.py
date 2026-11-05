"""SOTA NESTED WALK-FORWARD-OF-SEARCH — legitimate held-out confirmation of the horizon near-miss.

PURPOSE
=======
The 6th-axis near-miss candidate (`vol_adj_sector_alpha_14 ↑D10, forward_days=60, N=20, risk_parity,
forced Amihud`, NET +7.54%/Sharpe 0.98) scored DSR=0.995 at honest n=1 but DIED under the n_eff=30
multiple-testing haircut of the discovery sweep. The prior OOS-confirmation attempt (UPDATE 6) proved a
*later* held-out span is impossible: the DB ends 2026-06-17 and the 30-cell sweep consumed the ENTIRE
history as its OOS track — testing the *already-known* candidate on an *earlier carve of the same data*
is circular (that data crowned it) and FORBIDDEN.

THIS SCRIPT does the ONLY legitimate alternative: a NESTED WALK-FORWARD-OF-SEARCH (a.k.a. combinatorial
purged holdout of the SELECTION step itself).

  STAGE 0  SPLIT history into a TRAIN (earlier) portion and a strictly-later HELD-OUT TEST tail.
           The search is FORBIDDEN to touch the test tail. Leak-safe boundary: every bar the TRAIN
           search *evaluates* (its OOS folds) ends on/before the cut; every bar the TEST *scores*
           (its OOS folds) begins strictly after the cut, separated by an embargo ≥ forward_days+2.

  STAGE 1  RE-RUN the mechanical discovery grid (same cohorts × horizons × breadths as the prior
           sweep) on the TRAIN span ONLY. Select the SINGLE winner by a FIXED TRAIN-ONLY criterion
           (train-OOS Sharpe, tie-broken by train-OOS net CAGR). NO peeking at the test tail.

  STAGE 2  Run that ONE train-winner ONCE through production `_core_wfo` on the strictly-later TEST
           tail. The final trial count is genuinely 1 → DSR is computed at n=1 on the test-tail daily
           returns and graded against 0.95.

  STAGE 3  COVERAGE HONESTY — report train/test window counts; if the test tail is too thin (e.g. a
           ~1.5y tail at OOS=90 yields ~6 windows or fewer), grade INCONCLUSIVE rather than oversell.

WHY THIS IS NOT CIRCULAR (and the residual caveat that remains):
  • The selection in STAGE 1 has NO access to the test tail — the train grid's `to_date` is the cut.
    Whatever the train criterion crowns, it is crowned without seeing a single scored test bar. If the
    train-winner is the SAME cell as the full-span candidate AND it survives clean on the unseen tail,
    that is strong corroboration that the edge is not a full-span in-sample artifact.
  • RESIDUAL ANALYST-KNOWLEDGE CAVEAT (stated honestly): I (the analyst) already know from the prior
    full-span sweep that vol_adj_sector_alpha won. A prior sweep's OOS track DID see the test-tail
    dates. So this is NOT a pristine never-seen holdout. The protection is MECHANICAL DISCIPLINE: the
    grid is fixed, the winner is picked by a fixed train criterion (argmax train-OOS Sharpe), there is
    NO human thumb on the scale toward the known answer. This makes the result "strong corroboration,"
    not "pristine confirmation."

ENGINE REUSE (never re-implemented): routers.analytics._core_wfo / _wfo_windows / _load_context /
_auto_impact_status ; backtest_engine.deflated_sharpe_ratio. The TRAIN/TEST confinement is achieved
purely by setting `from_date`/`to_date` — the engine's own rolling-window machinery does the rest.

HYGIENE: MODE=PAPER · DuckDB read_only=True · seed fixed · NO secrets · NO look-ahead / NO shuffle /
NO skipped WFO · embargo ≥ fd+2 at the boundary · friction 15bps floor · Amihud additive forced ·
nothing staged / committed / pushed. Result sidecars at repo root are gitignored — left unstaged.
"""

from __future__ import annotations

import csv
import json
import logging
import random
import sys
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np

# ── Bootstrap: production engine on sys.path (engine-anchors) ────────────────────────
REPO = Path(__file__).resolve().parents[1]
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
FRICTION_BPS: float = 15.0             # compliance floor (never < 0.15% round-trip)
SIZING_MODE: str = "risk_parity"       # Pillar C — inverse-vol
IMPACT_COEF: float = 1.0               # Pillar B temp leg — FORCED explicit
AMIHUD_COEF: float = 1.0               # Pillar B permanent (Amihud/Kyle-λ) leg — FORCED explicit

IN_SAMPLE_DAYS: int = 365
OUT_SAMPLE_DAYS: int = 90
BASE_EMBARGO_DAYS: int = 7             # engine auto-raises to max(7, forward_days+2)

# Mechanical search grid — SAME logic as the prior horizon sweep (cohorts × horizons × breadths).
HORIZON_GRID: tuple[int, ...] = (40, 60)
BREADTH_GRID: tuple[int, ...] = (5, 20)

DSR_GATE: float = 0.95
TRADING_DAYS: int = be.TRADING_DAYS

# ── STAGE 0: the leak-safe split. Full usable history 2021-05-17 → 2026-06-17. ──────
# The DISCOVERY search is confined to [DB_FROM, CUT]. The HELD-OUT TEST scores OOS folds strictly
# after CUT. We report BOTH boundary regimes (eval-nonoverlap = 6 test windows ; strict all-bar
# nonoverlap = 2 test windows) and lead with the conservative caveat.
DB_FROM: str = "2021-05-17"
DB_TO: str = "2026-06-17"
CUT: str = "2024-12-31"                # TRAIN search runs [DB_FROM, CUT]; its last OOS_end == CUT

# Test-span start under the "eval-nonoverlap" rule: the test's IS warm-up may look back into pre-CUT
# data (legitimate for a FIXED decile screen — no parameters are fitted on the IS window; candidate_
# filters=[] ⇒ pure OOS stitch), but every SCORED OOS bar starts strictly after CUT. This date is
# derived per-horizon so the first test OOS_start == CUT+1 day (= 2025-01-01). Computed in main().
TEST_TO: str = DB_TO

OUT_CSV = REPO / "sota_nested_holdout_results.csv"
OUT_JSON = REPO / "sota_nested_holdout_results.json"
LOG_PATH = REPO / "sota_nested_holdout_run.log"


@dataclass(frozen=True)
class Cohort:
    """A single long-only decile screen. side='top' ⇒ gte decile 10; 'bottom' ⇒ lte decile 1."""
    key: str
    label: str
    field: str
    side: str               # "top" | "bottom"
    note: str

    def filter_condition(self) -> FilterCondition:
        if self.side == "top":
            return FilterCondition(field=self.field, op="gte", value=10.0, mode="decile")
        return FilterCondition(field=self.field, op="lte", value=1.0, mode="decile")


# Same 3 cohorts as the discovery sweep — the mechanical grid is unchanged.
COHORTS: list[Cohort] = [
    Cohort("COH-A", "vol_adj_sector_alpha↑D10", "vol_adj_sector_alpha_14", "top",
           "Offensive market-relative slow mean-reversion axis (the full-span near-miss cohort)."),
    Cohort("COH-B", "sector_rel_mom↑D10", "sector_rel_mom_14_pct", "top",
           "Offensive sector-relative momentum."),
    Cohort("COH-C", "low-ATR↓D1", "atr_pct", "bottom",
           "Defensive low-vol axis."),
]


@dataclass
class CellResult:
    """One WFO cell (train OR test). Measured, never asserted."""
    stage: str                          # "train" | "test"
    cohort_key: str
    cohort_label: str
    field: str
    forward_days: int
    breadth_n: int
    from_date: str
    to_date: str
    embargo_days: int
    n_windows: int
    total_trades: int
    median_holding_days: float
    oos_cagr_net_pct: float
    oos_total_return_net_pct: float
    max_drawdown_pct: float
    sharpe: float
    calmar: float
    sortino: float
    win_rate: float
    oos_cagr_gross_pct: float
    turnover_annual_pct: float
    impact_drag_annual_pct: float
    benchmark_total_return_pct: float
    alpha_annual_pct: float
    dsr_engine: float
    sr_annual: float
    dsr_n1: float = 0.0                 # DSR at n=1 (only filled for the STAGE-2 test winner)
    passes_dsr_gate: bool = False
    impact_temp_leg_on: bool = False
    impact_permanent_leg_on: bool = False
    impact_active: bool = False
    note: str = ""


# ── helpers (faithful copies of the horizon-script accounting) ──────────────────────
def _g(res: dict, k: str, d: float = 0.0) -> float:
    v = res.get(k, d)
    return d if v is None else float(v)


def oos_daily_returns(res: dict) -> np.ndarray:
    """Per-period (daily) returns from the stitched OOS equity curve."""
    eq = res.get("equity") or res.get("equity_curve") or []
    nav = np.asarray([e.get("nav") for e in eq if e.get("nav") is not None], dtype=float)
    return (nav[1:] / nav[:-1] - 1.0) if nav.size > 1 else np.array([])


def turnover_and_impact(res: dict, oos_span_days: int) -> tuple[float, float]:
    """Realized annualized turnover (% book replaced) and Amihud impact drag (% NAV), reconstructed
    from per-trade records (compute_metrics emits no aggregate turnover/impact). Engine already debits
    impact from NAV (eff=net−impact) — this ATTRIBUTES, does not re-charge. Surfaced `trades` capped at
    1000 → scale by total/len to stay unbiased. (0,0) only if zero OOS trades."""
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
    """Decompose NET (impact-baked) CAGR into GROSS-of-impact: gross ≈ net + impact_drag (additive in
    return space; eff = net − impact at the trade level). Attribution, not re-simulation."""
    return net_cagr_pct + impact_drag_annual_pct


def median_holding_days(res: dict) -> float:
    trades = res.get("trades", []) or []
    hd = [float(t.get("holding_days", 0) or 0) for t in trades if t.get("holding_days") is not None]
    return float(np.median(hd)) if hd else 0.0


def oos_span_days_for(res: dict) -> int:
    eq = res.get("equity") or res.get("equity_curve") or []
    n = len([e for e in eq if e.get("nav") is not None])
    return max(n - 1, 1)


def sharpe_annual(ret: np.ndarray) -> float:
    if ret.size > 2 and np.std(ret, ddof=1) > 1e-12:
        return float(np.mean(ret) / np.std(ret, ddof=1)) * float(np.sqrt(TRADING_DAYS))
    return 0.0


def wfo_windows_local(from_str: str, to_str: str, fd: int) -> list[tuple]:
    """Mirror of analytics._wfo_windows for boundary arithmetic ONLY (the engine itself still does the
    real windowing inside _core_wfo). Used to compute leak-safe test-span start dates and window counts."""
    from_dt = datetime.strptime(from_str, "%Y-%m-%d").date()
    to_dt = datetime.strptime(to_str, "%Y-%m-%d").date()
    emb = max(BASE_EMBARGO_DAYS, fd + 2)
    out: list[tuple] = []
    cur = from_dt
    while True:
        is_s = cur
        is_e = is_s + timedelta(days=IN_SAMPLE_DAYS)
        oos_s = is_e + timedelta(days=emb)
        if oos_s > to_dt:
            break
        oos_e = min(oos_s + timedelta(days=OUT_SAMPLE_DAYS), to_dt)
        out.append((is_s, is_e, oos_s, oos_e))
        if oos_e >= to_dt:
            break
        cur = cur + timedelta(days=OUT_SAMPLE_DAYS)
    return out


def test_from_for_horizon(fd: int) -> str:
    """Leak-safe test-span start (eval-nonoverlap rule): solve test_from so the test's FIRST scored OOS
    bar == CUT + 1 day. test_from + IS + emb = first_oos_start ⇒ test_from = (CUT+1) − IS − emb.
    The test's IS warm-up consequently looks back into pre-CUT data, which is admissible for a FIXED
    decile screen (no fitted parameters on the IS window) — but EVERY scored OOS bar is strictly post-CUT."""
    emb = max(BASE_EMBARGO_DAYS, fd + 2)
    cut_dt = datetime.strptime(CUT, "%Y-%m-%d").date()
    first_oos = cut_dt + timedelta(days=1)
    tf = first_oos - timedelta(days=IN_SAMPLE_DAYS + emb)
    return tf.isoformat()


def build_req(cohort: Cohort, fd: int, n: int, from_date: str, to_date: str) -> WFOBacktestRequest:
    """One WFO request confined to [from_date, to_date]. base_filters = the decile screen;
    candidate_filters=[] ⇒ pure OOS stitch (fixed screen, no per-window re-selection, no OOS peeking).
    Pillars B (forced Amihud) + C (risk_parity) ON. Identical construction to the discovery sweep —
    ONLY the span dates change between TRAIN and TEST."""
    fc = cohort.filter_condition()
    return WFOBacktestRequest(
        from_date=from_date, to_date=to_date, forward_days=fd,
        starting_capital=CAPITAL, friction_bps=FRICTION_BPS,
        max_positions=n, scope="universe",
        sizing_mode=SIZING_MODE,
        impact_coef=IMPACT_COEF, amihud_coef=AMIHUD_COEF,
        base_filters=[fc], candidate_filters=[],
        in_sample_days=IN_SAMPLE_DAYS, out_sample_days=OUT_SAMPLE_DAYS,
        embargo_days=BASE_EMBARGO_DAYS,
        selection="sector_neutral", selection_factor=cohort.field,
    )


def pillar_b_status(req: WFOBacktestRequest, from_date: str, to_date: str) -> dict:
    """Rebuild the sim context as _core_wfo does and PROVE the Amihud legs are live for THIS span."""
    fd = datetime.strptime(from_date, "%Y-%m-%d").date()
    td = datetime.strptime(to_date, "%Y-%m-%d").date()
    ctx = _load_context(req, fd, td, True, lambda *a, **k: None)
    if ctx is None:
        return {"impact_temp_leg_on": False, "impact_permanent_leg_on": False, "impact_active": False}
    st = _auto_impact_status(req, ctx)
    st["impact_active"] = bool(
        st.get("impact_temp_leg_on") or st.get("impact_permanent_leg_on")
        or st.get("impact_full_stack_auto")
    )
    return st


def run_cell(stage: str, cohort: Cohort, fd: int, n: int,
             from_date: str, to_date: str, log: logging.Logger) -> Optional[CellResult]:
    """Execute one WFO cell through the PRODUCTION engine and capture every metric. Returns None only
    if the engine raised (recorded, never fabricated)."""
    req = build_req(cohort, fd, n, from_date, to_date)
    pb = pillar_b_status(req, from_date, to_date)
    try:
        res = _core_wfo(req)
    except Exception as exc:
        log.exception("[%s] %s fd=%d N=%d — _core_wfo FAILED: %s", stage, cohort.key, fd, n, exc)
        return None
    wf = res.get("walk_forward", {}) or {}
    oos_days = oos_span_days_for(res)
    turn, impact_drag = turnover_and_impact(res, oos_days)
    net_cagr = _g(res, "cagr_pct")
    gross_cagr = gross_of_impact_cagr(net_cagr, impact_drag)
    ret = oos_daily_returns(res)
    _RETURNS_CACHE[(stage, cohort.key, fd, n)] = ret
    return CellResult(
        stage=stage, cohort_key=cohort.key, cohort_label=cohort.label, field=cohort.field,
        forward_days=fd, breadth_n=n, from_date=from_date, to_date=to_date,
        embargo_days=max(BASE_EMBARGO_DAYS, fd + 2),
        n_windows=int(wf.get("n_windows", 0) or 0),
        total_trades=int(res.get("total_trades", 0) or 0),
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
        sr_annual=round(sharpe_annual(ret), 4),
        impact_temp_leg_on=bool(pb.get("impact_temp_leg_on")),
        impact_permanent_leg_on=bool(pb.get("impact_permanent_leg_on")),
        impact_active=bool(pb.get("impact_active")),
        note=cohort.note,
    )


_RETURNS_CACHE: dict[tuple, np.ndarray] = {}


def main() -> None:
    random.seed(SEED)
    np.random.seed(SEED)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(LOG_PATH, mode="w"), logging.StreamHandler(sys.stdout)],
    )
    log = logging.getLogger("nested")

    log.info("MODE=%s  DB=%s  CAPITAL=Rs%s  SEED=%d", MODE, _db.DB_PATH, f"{CAPITAL:,.0f}", SEED)
    log.info("=== NESTED WALK-FORWARD-OF-SEARCH (legitimate held-out confirmation) ===")
    log.info("Split: TRAIN-search [%s..%s]  →  HELD-OUT TEST scores OOS strictly after %s",
             DB_FROM, CUT, CUT)

    # DB sanity (read-only)
    con = duckdb.connect(_db.DB_PATH, read_only=True)
    span = con.execute("SELECT min(date), max(date), count(*) FROM ohlcv").fetchone()
    con.close()
    log.info("DB span %s → %s (%s rows) [read_only]", span[0], span[1], f"{span[2]:,}")
    if str(span[1]) != DB_TO:
        log.warning("DB max date %s != expected %s — fresh data may exist; geometry assumes %s",
                    span[1], DB_TO, DB_TO)

    # Boundary proof per horizon
    log.info("--- STAGE 0: leak-safe boundary geometry ---")
    for fd in HORIZON_GRID:
        tf = test_from_for_horizon(fd)
        wtr = wfo_windows_local(DB_FROM, CUT, fd)
        wte = wfo_windows_local(tf, TEST_TO, fd)
        emb = max(BASE_EMBARGO_DAYS, fd + 2)
        log.info("fd=%d emb=%d | TRAIN [%s..%s] win=%d last_OOS_end=%s | TEST [%s..%s] win=%d "
                 "first_OOS_start=%s last_OOS_end=%s | GAP_ok=%s",
                 fd, emb, DB_FROM, CUT, len(wtr), wtr[-1][3] if wtr else None,
                 tf, TEST_TO, len(wte), wte[0][2] if wte else None, wte[-1][3] if wte else None,
                 (wte[0][2] > wtr[-1][3]) if (wtr and wte) else None)

    # ── STAGE 1: mechanical search on TRAIN span ONLY ──────────────────────────────
    log.info("--- STAGE 1: mechanical discovery grid on TRAIN [%s..%s] (NO test access) ---",
             DB_FROM, CUT)
    train_cells: list[CellResult] = []
    for cohort in COHORTS:
        for fd in HORIZON_GRID:
            for n in BREADTH_GRID:
                cell = run_cell("train", cohort, fd, n, DB_FROM, CUT, log)
                if cell is None:
                    continue
                train_cells.append(cell)
                log.info("TRAIN %s fd=%2d N=%2d | win=%2d trades=%4d | NET=%7.2f%% GROSS=%7.2f%% "
                         "Sh=%5.2f Cal=%5.2f MaxDD=%6.1f%% | turn=%6.0f%% impact=%4.2f%% | act=%s",
                         cohort.key, fd, n, cell.n_windows, cell.total_trades,
                         cell.oos_cagr_net_pct, cell.oos_cagr_gross_pct, cell.sharpe, cell.calmar,
                         cell.max_drawdown_pct, cell.turnover_annual_pct,
                         cell.impact_drag_annual_pct, cell.impact_active)

    if not train_cells:
        log.error("No TRAIN cells produced — aborting.")
        return

    # FIXED train-only selection criterion: argmax train-OOS annualized Sharpe (the cell's own daily-
    # returns Sharpe — the same statistic the DSR gate ultimately judges), tie-broken by train-OOS net
    # CAGR. NO test data touched. This is the single mechanical decision rule, declared in advance.
    winner = max(train_cells, key=lambda c: (c.sr_annual, c.oos_cagr_net_pct))
    log.info("=== STAGE 1 WINNER (by train-OOS Sharpe) ===")
    log.info("  %s | fd=%d | N=%d | train Sharpe=%.3f | train NET=%.2f%% | train GROSS=%.2f%%",
             winner.cohort_label, winner.forward_days, winner.breadth_n,
             winner.sr_annual, winner.oos_cagr_net_pct, winner.oos_cagr_gross_pct)
    same_as_candidate = (winner.cohort_key == "COH-A" and winner.forward_days == 60
                         and winner.breadth_n == 20)
    log.info("  Same as full-span near-miss candidate (COH-A/fd60/N20)? %s", same_as_candidate)

    # ── STAGE 2: test the ONE train-winner ONCE on the held-out tail (trial count = 1) ──
    winner_cohort = next(c for c in COHORTS if c.key == winner.cohort_key)
    test_from = test_from_for_horizon(winner.forward_days)
    log.info("--- STAGE 2: SINGLE held-out test of the train-winner on [%s..%s] (n=1) ---",
             test_from, TEST_TO)
    test_cell = run_cell("test", winner_cohort, winner.forward_days, winner.breadth_n,
                         test_from, TEST_TO, log)
    if test_cell is None:
        log.error("STAGE 2 test run failed — cannot grade.")
        return

    # DSR at honest n=1 on the test-tail daily OOS returns.
    test_ret = _RETURNS_CACHE.get(("test", winner.cohort_key, winner.forward_days, winner.breadth_n),
                                  np.array([]))
    if test_ret.size > 2:
        d = be.deflated_sharpe_ratio(test_ret, [test_cell.sr_annual], freq=TRADING_DAYS, n_eff=1.0)
        test_cell.dsr_n1 = round(float(d.get("dsr", 0.0)), 6)
    else:
        test_cell.dsr_n1 = 0.0
    test_cell.passes_dsr_gate = bool(test_cell.dsr_n1 > DSR_GATE and test_cell.oos_cagr_net_pct > 0.0)

    log.info("=== STAGE 2 HELD-OUT TEST RESULT (n=1) ===")
    log.info("  %s fd=%d N=%d | TEST win=%d trades=%d | NET=%.2f%% GROSS=%.2f%% Sharpe=%.3f "
             "Calmar=%.2f MaxDD=%.2f%% | turn=%.0f%%/yr impact=%.2f%%/yr | alpha=%.2f%%/yr",
             winner.cohort_label, winner.forward_days, winner.breadth_n, test_cell.n_windows,
             test_cell.total_trades, test_cell.oos_cagr_net_pct, test_cell.oos_cagr_gross_pct,
             test_cell.sharpe, test_cell.calmar, test_cell.max_drawdown_pct,
             test_cell.turnover_annual_pct, test_cell.impact_drag_annual_pct,
             test_cell.alpha_annual_pct)
    log.info("  DSR@n=1 = %.4f  (gate %.2f) → %s",
             test_cell.dsr_n1, DSR_GATE, "CLEARS" if test_cell.dsr_n1 > DSR_GATE else "FAILS")
    log.info("  impact_active=%s (temp=%s perm=%s)", test_cell.impact_active,
             test_cell.impact_temp_leg_on, test_cell.impact_permanent_leg_on)

    # ── STAGE 3: coverage-credibility call + verdict ───────────────────────────────
    train_win = max((c.n_windows for c in train_cells), default=0)
    test_win = test_cell.n_windows
    thin = test_win < 8                          # < 8 OOS folds → too few for a credible n=1 read
    if not test_cell.passes_dsr_gate:
        verdict = "REJECTED"
    elif thin:
        verdict = "INCONCLUSIVE"
    else:
        verdict = "CORROBORATED"
    log.info("--- STAGE 3: coverage + verdict ---")
    log.info("  train windows (max across grid)=%d | test windows=%d | thin(<8)=%s", train_win, test_win, thin)
    log.info("  VERDICT = %s", verdict)

    # ── persist (sidecars at repo root; gitignored; left unstaged) ─────────────────
    all_cells = train_cells + [test_cell]
    rows = [asdict(c) for c in all_cells]
    OUT_JSON.write_text(json.dumps({
        "mode": MODE, "seed": SEED, "capital": CAPITAL, "db_path": _db.DB_PATH,
        "db_span": [str(span[0]), str(span[1])],
        "split": {"train_from": DB_FROM, "cut": CUT, "test_to": TEST_TO,
                  "test_from_by_horizon": {fd: test_from_for_horizon(fd) for fd in HORIZON_GRID}},
        "horizon_grid": list(HORIZON_GRID), "breadth_grid": list(BREADTH_GRID),
        "in_sample_days": IN_SAMPLE_DAYS, "out_sample_days": OUT_SAMPLE_DAYS,
        "impact_coef": IMPACT_COEF, "amihud_coef": AMIHUD_COEF, "sizing_mode": SIZING_MODE,
        "dsr_gate": DSR_GATE,
        "stage1_winner": asdict(winner),
        "stage1_winner_same_as_candidate": same_as_candidate,
        "stage2_test": asdict(test_cell),
        "stage2_dsr_n1": test_cell.dsr_n1,
        "coverage": {"train_windows_max": train_win, "test_windows": test_win, "thin": thin},
        "verdict": verdict,
        "cohorts": [asdict(c) for c in COHORTS],
        "cells": rows,
    }, indent=2, default=str))
    if rows:
        with OUT_CSV.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
    log.info("Artifacts: %s · %s · %s", OUT_CSV.name, OUT_JSON.name, LOG_PATH.name)
    log.info("=== DONE — verdict=%s ===", verdict)


if __name__ == "__main__":
    main()
