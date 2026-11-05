#!/usr/bin/env python
"""The deterministic monthly flow for S1 (research/paper only — nothing trades).

    PYTHONPATH=alpha_lab python alpha_lab/run_today.py

Prints, for the LATEST session in the panel:
  - the regime (NIFTY vs 200-DMA → invested or liquid fund / hedge),
  - the S1 target book exactly as the backtest would pick it at the next month-end,
  - every universe name currently blocked, with the veto(s) that fired,
and writes alpha_lab/reports/today_book.md. Run it any day; the book only changes at month ends.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# argparse BEFORE the heavy imports (F5.5): `--help` must answer in <1 s, not run the 20 s panel load.
if __name__ == "__main__":
    _ap = argparse.ArgumentParser(description="Print today's S1 target book, fired vetoes and regime "
                                              "(paper/research only; writes alpha_lab/reports/today_book.md).")
    _ap.parse_args()

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

LAB = Path(__file__).resolve().parent
sys.path.insert(0, str(LAB))
import lib  # noqa: F401,E402
from backtest.data_access import load  # noqa: E402
from lib.momentum import select  # noqa: E402
from lib.momentum import signals as desk_signals  # noqa: E402
from strategies import flags as fl  # noqa: E402
from strategies.s1_sentinel import BUFFER, N, VOL_DECILE  # noqa: E402

VETOES = ("below_200dma", "near_52w_low", "split_20d", "bad_results_60d")


def main() -> None:
    t0 = time.time()
    data = load()
    panel = data["panel"]
    sig = desk_signals(panel)
    veto = fl.s1_veto_frames(panel, data["releases"])
    sessions = panel["close"].index
    s = len(sessions) - 1
    day = sessions[s]
    nifty = data["nifty"].reindex(sessions).ffill()
    ma = nifty.rolling(200, min_periods=180).mean()
    risk_on = bool(nifty.iloc[s] > ma.iloc[s])

    uni = fl.lab_eligible(sig, panel, s)
    v60 = veto["vol60"].loc[day, uni]
    hi_vol = set(v60.index[(v60.rank(pct=True) >= VOL_DECILE).to_numpy(dtype=bool)])
    why: dict[str, list[str]] = {}
    for name in VETOES:
        m = veto[name].loc[day, uni].to_numpy(dtype=bool)
        for sym in uni[m]:
            why.setdefault(sym, []).append(name)
    for sym in hi_vol:
        why.setdefault(sym, []).append("vol60_top_decile")
    blocked = set(why)
    picks = select(sig["mom_nse"].iloc[s][uni], set(), N, buffer=BUFFER, blocked=blocked)
    score = sig["mom_nse"].iloc[s]
    ranked = score[uni].dropna().sort_values(ascending=False)
    rank_of = {sym: i + 1 for i, sym in enumerate(ranked.index)}

    lines = [f"# S1 book as of {day.date()} (research/paper only)",
             f"- Regime: NIFTY {nifty.iloc[s]:,.0f} vs 200-DMA {ma.iloc[s]:,.0f} → "
             + ("**RISK-ON: invested**" if risk_on else "**RISK-OFF: liquid fund (S1) / hedged (S1H)**"),
             f"- Universe: top {len(uni)} by liquidity (raw close ≥ ₹20) · blocked today: {len(blocked)}",
             "", "## Target book (top 20 by momentum, vetoes applied; next rebalance = next month-end)", ""]
    lines += [f"{i+1:2d}. {sym}  (momentum rank {rank_of.get(sym, '—')})" for i, sym in enumerate(picks)]
    skipped = [(sym, why[sym]) for sym in ranked.index[:40] if sym in blocked]
    lines += ["", "## Momentum leaders refused by the avoid rules (top-40 ranks only)", ""]
    lines += [f"- {sym} (rank {rank_of[sym]}): {', '.join(r)}" for sym, r in skipped] or ["- none"]
    lines += ["", f"Generated in {time.time()-t0:.0f}s from the panel snapshot of {day.date()}. "
              "Rules: alpha_lab/PLAN.md §S1 + Amendments v2. Not a trade instruction."]
    out = "\n".join(lines)
    (LAB / "reports" / "today_book.md").write_text(out + "\n")
    print(out)


if __name__ == "__main__":
    main()
