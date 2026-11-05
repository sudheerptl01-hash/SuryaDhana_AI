#!/usr/bin/env python
"""Monte-Carlo drawdown lens (A1, QuantLab adoption 15 Oct 2026) — REPORT-ONLY, never a gate.

Resamples a strategy's MONTHLY return series with a circular (wrap-around) block bootstrap and
reports the distribution of maximum drawdowns beside the realized one. Gates are FROZEN by
PLAN.md Amendments v2: this file adds a reporting lens on the gate curves; it changes no verdict,
no StrategyConfig, no strategy code. The owner decides any use of the flag below.

Method (fixed here, before any real curve was run)
- Monthly returns: month-end ("ME") resample of the persisted daily gate equity curve, then
  pct_change — the same convention as `engine.monthly_excess_ir`.
- Block bootstrap: block length 3 months (preserves regime clustering), blocks drawn circularly
  (indices wrap past the end), 10,000 resamples, each over the SAME horizon length as the input.
- Per resample: max drawdown of the compounded path measured against the running peak INCLUDING
  the starting capital (a first-month loss counts). Report p50 / p90 / p95 / max of drawdown
  depth, signed negative, beside the realized maxDD (daily and month-end granularity).
- Determinism: numpy `default_rng(seed)`, seed default 108. Vectorized (10k × 72 months in < 1 s).

PRE-REGISTERED FLAG (written in this docstring BEFORE running on real curves)
- A variant is **DD-FRAGILE** on a gate window if the p95 resampled drawdown breaches that gate's
  pre-registered absolute drawdown budget even though the realized path passed it.
- Budgets, cited from alpha_lab/PLAN.md "Stages and gates" (unchanged by Amendments v2):
  Gate A criterion 2: "Max drawdown ≥ −30% absolute" → budget **−30%**.
  Gate B criterion 2: "Max drawdown ≥ −35% absolute" → budget **−35%**.
  (Gate A's second, relative leg — "no deeper than 1.25 × NIFTY 50's max drawdown" — is NOT
  resampled here: the benchmark is a single path, so only the absolute budget is tested.)
  The full 2011→2026 window has no pre-registered budget and is reported without a flag.
- Honesty note: monthly granularity understates intramonth (daily) drawdowns, so a p95 breach at
  month-end granularity is the conservative direction for this flag. DD-FRAGILE is REPORTED,
  never gating.

Usage
    PYTHONPATH=alpha_lab python alpha_lab/backtest/mc.py                   # S1 + S1H, writes
        alpha_lab/reports/mc_drawdown.md (+ .json for the shadow status line)
    PYTHONPATH=alpha_lab python alpha_lab/backtest/mc.py --strategy s1    # one strategy, print only
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))

REPORTS = LAB / "reports"
MD_PATH = REPORTS / "mc_drawdown.md"
JSON_PATH = REPORTS / "mc_drawdown.json"

RESAMPLES = 10_000
BLOCK = 3
SEED = 108

# (window, curve file suffix, absolute DD budget % from PLAN.md — None = no pre-registered budget)
WINDOWS: list[tuple[str, str, float | None]] = [
    ("gateA", "gateA_equity.csv", -30.0),
    ("gateB", "gateB_equity.csv", -35.0),
    ("full", "full_equity.csv", None),
]
PREFIX = {"s1": "s1", "s1h": "s1H"}          # CLI name → persisted curve prefix
LABEL = {"s1": "S1", "s1h": "S1H"}


def load_equity(path: Path) -> pd.Series:
    """A persisted gate equity curve (reports/*_equity.csv: `date,0`) as a daily pd.Series."""
    df = pd.read_csv(path, index_col=0, parse_dates=True)
    return df.iloc[:, 0].dropna()


def monthly_returns(equity: pd.Series) -> np.ndarray:
    """Month-end returns of a daily equity curve (same "ME" convention as engine.monthly_excess_ir)."""
    return equity.resample("ME").last().pct_change().dropna().to_numpy(float)


def max_drawdown(returns: np.ndarray) -> float:
    """Signed max drawdown (≤ 0) of one compounded return path, peak including start capital 1.0."""
    return float(bootstrap_dd(returns[None, :])[0])


def bootstrap_dd(paths_returns: np.ndarray) -> np.ndarray:
    """Signed max drawdown per row of a (k, n) return matrix, vectorized."""
    paths = np.cumprod(1.0 + paths_returns, axis=1)
    lead = np.ones((paths.shape[0], 1))
    peaks = np.maximum.accumulate(np.concatenate([lead, paths], axis=1), axis=1)[:, 1:]
    return (paths / peaks - 1.0).min(axis=1)


def block_bootstrap(monthly: np.ndarray, n_resamples: int = RESAMPLES, block: int = BLOCK,
                    seed: int = SEED) -> np.ndarray:
    """Signed max-DD distribution from a circular block bootstrap of the monthly return series.

    Draws ceil(n/block) uniform block starts per resample; each block is `block` consecutive
    months with indices wrapping past the end (circular); the concatenation is truncated to the
    original horizon length n. Deterministic for a given seed.
    """
    n = len(monthly)
    if n < 2:
        raise ValueError(f"need ≥ 2 monthly returns, got {n}")
    if not (1 <= block <= n):
        raise ValueError(f"block length {block} outside 1..{n}")
    rng = np.random.default_rng(seed)
    n_blocks = -(-n // block)                                   # ceil
    starts = rng.integers(0, n, size=(n_resamples, n_blocks))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]) % n
    idx = idx.reshape(n_resamples, n_blocks * block)[:, :n]
    return bootstrap_dd(monthly[idx])


def dd_percentiles(dd: np.ndarray) -> dict[str, float]:
    """p50/p90/p95/max of drawdown SEVERITY, returned signed (negative %). p95 = the depth only
    5% of resamples exceed; max = the deepest resample."""
    depth = -dd * 100.0
    p50, p90, p95 = np.percentile(depth, [50, 90, 95])
    return {"p50": -float(p50), "p90": -float(p90), "p95": -float(p95), "max": -float(depth.max())}


def run_window(curve: Path, budget: float | None, n_resamples: int = RESAMPLES,
               block: int = BLOCK, seed: int = SEED) -> dict:
    """One strategy × window: realized DDs (daily + monthly) and the bootstrap DD distribution."""
    eq = load_equity(curve)
    monthly = monthly_returns(eq)
    realized_daily = float((eq / eq.cummax() - 1.0).min() * 100.0)
    realized_monthly = max_drawdown(monthly) * 100.0
    pct = dd_percentiles(block_bootstrap(monthly, n_resamples, block, seed))
    fragile = (budget is not None and pct["p95"] < budget <= realized_daily)
    return {"months": len(monthly), **pct, "realized_daily": realized_daily,
            "realized_monthly": realized_monthly, "budget": budget, "dd_fragile": bool(fragile),
            "start": str(eq.index[0].date()), "end": str(eq.index[-1].date())}


def run_strategy(strategy: str, n_resamples: int = RESAMPLES, block: int = BLOCK,
                 seed: int = SEED, reports: Path = REPORTS) -> dict[str, dict]:
    """All persisted gate windows for one strategy; a missing curve file is skipped with a note."""
    out: dict[str, dict] = {}
    for window, suffix, budget in WINDOWS:
        curve = reports / f"{PREFIX[strategy]}_{suffix}"
        if not curve.exists():
            out[window] = {"missing": str(curve.name)}
            continue
        out[window] = run_window(curve, budget, n_resamples, block, seed)
    return out


def fmt(v: float | None, suffix: str = "%") -> str:
    return "—" if v is None else f"{v:.1f}{suffix}"


def table(results: dict[str, dict[str, dict]]) -> list[str]:
    lines = ["| Run | Window | Months | Realized DD (daily) | Realized DD (ME) | p50 | p90 | p95 | Max | Budget | Verdict |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for name, windows in results.items():
        for window, r in windows.items():
            if "missing" in r:
                lines.append(f"| {name} | {window} | — | curve not persisted ({r['missing']}) "
                             "| — | — | — | — | — | — | — |")
                continue
            verdict = ("**DD-FRAGILE**" if r["dd_fragile"] else
                       "report-only (no budget)" if r["budget"] is None else
                       "realized breached too" if r["realized_daily"] < r["budget"] else "within budget")
            lines.append(f"| {name} | {window} | {r['months']} | {fmt(r['realized_daily'])} "
                         f"| {fmt(r['realized_monthly'])} | {fmt(r['p50'])} | {fmt(r['p90'])} "
                         f"| {fmt(r['p95'])} | {fmt(r['max'])} | {fmt(r['budget'])} | {verdict} |")
    return lines


def honest_paragraph(results: dict[str, dict[str, dict]]) -> str:
    flagged = [f"{n} {w}" for n, ws in results.items() for w, r in ws.items() if r.get("dd_fragile")]
    head = (f"Flagged DD-FRAGILE: {', '.join(flagged)}. " if flagged else
            "No window is flagged DD-FRAGILE at p95. ")
    return (head + "Read this as a lens, not a verdict: the bootstrap asks how much of each PASS was "
            "path luck by reshuffling 3-month blocks of the same monthly returns — it preserves "
            "regime clustering at the block scale but cuts longer dependence, and month-end "
            "granularity understates intramonth pain (compare the two realized columns). A p95 "
            "deeper than the gate budget says a modest re-ordering of the SAME history breaches "
            "the budget one resample in twenty — consistent with FINDINGS.md's warning that S1's "
            "Gate-B pass sits at the edge of its −35% bar. Gates stay frozen (Amendments v2); "
            "this report changes no verdict and places no orders.")


def render_md(results: dict[str, dict[str, dict]], n_resamples: int, block: int, seed: int) -> str:
    lines = ["# Monte-Carlo drawdown lens — S1 / S1H (A1, REPORT-ONLY)", "",
             f"Generated by `alpha_lab/backtest/mc.py` · circular block bootstrap of monthly (ME) "
             f"returns · block = {block} months · {n_resamples:,} resamples over the window's own "
             f"horizon · seed {seed}.",
             "",
             "Pre-registered flag (written in mc.py's docstring before any real curve was run): "
             "**DD-FRAGILE** = p95 resampled drawdown breaches the gate's absolute DD budget "
             "(Gate A **−30%**, Gate B **−35%**, PLAN.md \"Stages and gates\" criterion 2; "
             "Amendments v2 left both unchanged) even though the realized path passed. Gate A's "
             "relative 1.25×NIFTY leg is not resampled. The full 2011→ window has no "
             "pre-registered budget, so it carries no flag.", ""]
    lines += table(results)
    lines += ["", honest_paragraph(results), "",
              "Realized numbers, windows and gate verdicts: `alpha_lab/reports/FINDINGS.md`. "
              "Rules: `alpha_lab/PLAN.md` + Amendments v2 (gates FROZEN — this lens never gates)."]
    return "\n".join(lines) + "\n"


def shadow_status_lines(reports: Path = REPORTS) -> list[str]:
    """One status line for paper/shadow.py when the MC report exists; [] otherwise (never raises)."""
    try:
        if not (reports / "mc_drawdown.md").exists():
            return []
        runs = json.loads((reports / "mc_drawdown.json").read_text())["runs"]
        parts = []
        for name in ("S1", "S1H"):
            r = runs.get(name, {}).get("gateA") or {}
            if "p95" in r:
                parts.append(f"{name} {r['p95']:.1f}% (realized {r['realized_daily']:.1f}%)")
        if not parts:
            return []
        return ["", "MC p95 DD (Gate A, 10k×3m block bootstrap, report-only): " + " · ".join(parts)]
    except Exception:
        return []                                               # a broken report must never break status


def main() -> None:
    ap = argparse.ArgumentParser(description="Block-bootstrap max-drawdown lens on the S1/S1H gate "
                                             "equity curves (REPORT-ONLY; gates frozen).")
    ap.add_argument("--strategy", choices=["s1", "s1h", "both"], default="both",
                    help="both (default) also writes reports/mc_drawdown.md + .json")
    ap.add_argument("--resamples", type=int, default=RESAMPLES)
    ap.add_argument("--block", type=int, default=BLOCK)
    ap.add_argument("--seed", type=int, default=SEED)
    args = ap.parse_args()
    t0 = time.time()
    names = ["s1", "s1h"] if args.strategy == "both" else [args.strategy]
    try:
        results = {LABEL[n]: run_strategy(n, args.resamples, args.block, args.seed) for n in names}
    except (ValueError, FileNotFoundError, KeyError) as exc:   # C2 LOW: short/missing curve
        sys.exit(f"mc: {exc} (need a gate equity curve with >= block ({args.block}) months)")
    md = render_md(results, args.resamples, args.block, args.seed)
    print(md)
    if args.strategy == "both":
        MD_PATH.write_text(md)
        JSON_PATH.write_text(json.dumps({"as_of": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
                                         "resamples": args.resamples, "block": args.block,
                                         "seed": args.seed, "runs": results}, indent=1))
        print(f"wrote {MD_PATH} and {JSON_PATH}")
    print(f"[{time.time() - t0:.1f}s]")


if __name__ == "__main__":
    main()
