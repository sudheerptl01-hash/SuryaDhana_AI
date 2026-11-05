#!/usr/bin/env python
"""S1 — Sentinel momentum (PLAN.md §S1): the Desk's monthly momentum with a robust avoid-veto
on new entries and the NIFTY-200DMA crash filter; variant H hedges with short NIFTY futures
instead of exiting.

    PYTHONPATH=alpha_lab python alpha_lab/strategies/s1_sentinel.py --start 2025-10-01 [--hedge] [--label smoke]

Research only. Writes alpha_lab/reports/s1_<label>.md + equity CSV.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))
import lib  # noqa: F401,E402
from backtest import engine  # noqa: E402
from backtest.data_access import load  # noqa: E402
from lib.momentum import select  # noqa: E402
from lib.momentum import signals as desk_signals  # noqa: E402
from strategies import flags as fl  # noqa: E402

N, BUFFER, VOL_DECILE = 20, 1.5, 0.9


def month_end_rows(sessions: pd.DatetimeIndex, start: pd.Timestamp) -> list[int]:
    ends = sessions.to_series().groupby(sessions.to_period("M")).max()
    return [sessions.get_loc(d) for d in ends if d >= start and sessions.get_loc(d) + 1 < len(sessions)]


def build(data: dict, use_veto: bool = True):
    panel = data["panel"]
    sig = desk_signals(panel)
    veto = fl.s1_veto_frames(panel, data["releases"])
    nifty = data["nifty"].reindex(panel["close"].index).ffill()
    nifty_ma = nifty.rolling(200, min_periods=180).mean()
    held: set[str] = set()

    def targets(s: int) -> tuple[list[str], bool]:
        # Picks are computed every month regardless of the regime; the ENGINE decides what a
        # risk-off month means (plain: sell to cash; hedge variant: keep the book, short NIFTY).
        nonlocal held
        risk_on = bool(np.isfinite(nifty_ma.iloc[s]) and nifty.iloc[s] > nifty_ma.iloc[s])
        uni = fl.lab_eligible(sig, panel, s)
        blocked: set[str] = set()
        if use_veto:
            day = panel["close"].index[s]
            v60 = veto["vol60"].loc[day, uni]
            hi_vol = set(v60.index[(v60.rank(pct=True) >= VOL_DECILE).to_numpy(dtype=bool)])
            mask = lambda name: veto[name].loc[day, uni].to_numpy(dtype=bool)  # noqa: E731
            blocked = (set(uni[mask("below_200dma")]) | set(uni[mask("near_52w_low")])
                       | set(uni[mask("split_20d")]) | set(uni[mask("bad_results_60d")]) | hi_vol)
        picks = select(sig["mom_nse"].iloc[s][uni], held, N, buffer=BUFFER, blocked=blocked)
        held = set(picks)
        return picks, risk_on

    return targets


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2020-01-01")
    ap.add_argument("--end", default="2026-10-13")
    ap.add_argument("--hedge", action="store_true")
    ap.add_argument("--no-veto", action="store_true")
    ap.add_argument("--capital", type=float, default=1_000_000)
    ap.add_argument("--label", default="run")
    args = ap.parse_args()
    t0 = time.time()
    data = load()
    panel = data["panel"]
    sessions = panel["close"].index
    end_row = len(sessions) - 1 if not args.end else sessions.searchsorted(pd.Timestamp(args.end))
    rows = [r for r in month_end_rows(sessions, pd.Timestamp(args.start) - pd.DateOffset(days=40)) if r < end_row]
    print(f"[{time.time()-t0:5.0f}s] panel {panel['close'].shape}, {len(rows)} rebalances from {sessions[rows[0]].date()}")
    cfg = engine.EngineConfig(capital=args.capital, hedge=args.hedge,
                              sleeve_frac=0.15 if args.hedge else 0.0)
    if args.hedge and args.capital == 1_000_000:
        cfg.capital = 5_000_000                      # Amendments v2 §3: hedged variants assume a ₹50L book
    res = engine.run(panel, data["nifty"], rows, build(data, use_veto=not args.no_veto), cfg)
    sig2 = desk_signals(panel)
    ew = engine.ew_benchmark(panel, rows, lambda s_: fl.lab_eligible(sig2, panel, s_))
    eq = res.equity[args.start:args.end]
    eq = eq / eq.iloc[0] * cfg.capital
    bench = res.bench.reindex(eq.index)
    bench = bench / bench.iloc[0] * cfg.capital
    ewb = engine.rebase(ew, eq, cfg.capital)
    s, b = engine.stats(eq), engine.stats(bench)
    ir = engine.monthly_excess_ir(eq, bench)
    yt = engine.yearly_table(eq, bench, ewb)
    n_reb = int((res.rebalances["date"] >= pd.Timestamp(args.start)).sum())
    ga = engine.gate_a(eq, bench, ewb, n_reb)
    gb = engine.gate_b(eq, bench, ewb)
    out = LAB / "reports"
    tag = f"s1{'H' if args.hedge else ''}{'_noveto' if args.no_veto else ''}_{args.label}"
    eq.to_csv(out / f"{tag}_equity.csv")
    import json
    gate_block = engine.render_gate("Gate A" if args.label.startswith("gateA") else
                                    "Gate B" if args.label.startswith("gateB") else "Gates (informational)",
                                    ga if not args.label.startswith("gateB") else gb)
    lines = [f"# S1{'H' if args.hedge else ''} {args.label}: {s['start']} → {s['end']}",
             f"- CAGR **{s['cagr']:.2f}%** vs NIFTY {b['cagr']:.2f}% / EW-T {engine.stats(ewb)['cagr']:.2f}%"
             f" · maxDD **{s['max_dd']:.1f}%** vs {b['max_dd']:.1f}% · IR {ir:.2f}"
             f" · rebalances {n_reb} · costs ₹{res.costs_paid:,.0f}",
             f"- {res.notes[0]}",
             "", gate_block, "",
             "```", yt.to_string(), "```", "",
             f"config: `{json.dumps(res.config.as_dict())}` · panel snapshot {pd.Timestamp.now():%Y-%m-%d %H:%M}"]
    (out / f"{tag}.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(f"[{time.time()-t0:5.0f}s] done → reports/{tag}.md")


if __name__ == "__main__":
    main()
