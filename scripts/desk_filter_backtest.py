#!/usr/bin/env python
"""
Candidate Decision Desk rule: do not open new positions in stocks that a non-institutional
client net-bought through a bulk deal in the last N sessions (shared/deal_filters.py).

Pre-registered comparison (fixed before running):
  * baseline  = the approved rules (mom_nse | N20 | nifty200_vt | sector cap 40%)
  * primary   = baseline + avoid_bulk_buy_days = 20   (the 20-session window studied in H3)
  * sensitivity = 60 sessions (reported, not a candidate)
  * window Nov-2019 → latest (bulk-deal data starts Oct-2019); discovery before Jul-2024,
    holdout from Jul-2024 (same split as the Phase B allocator); ₹5 lakh capital, 66% equity
    share + liquid fund (the approved Option B), real ICICI costs and taxes.
The rule is adopted only if it does not lower CAGR or raise drawdown in the holdout.

    python scripts/desk_filter_backtest.py [--capital 500000] [--out reports/desk_filter]
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from phase_b_allocator import (  # noqa: E402
    FIXED_MIX, HOLDOUT_START, Variant, _seg, load_data, metrics, mix_curve, signals, simulate,
)
from shared.trading_costs import default_model  # noqa: E402

START = pd.Timestamp("2019-11-01")
BASE = Variant("mom_nse", 20, "nifty200_vt", 0.40)
RUNS = {"approved rules": BASE,
        "+ avoid bulk buys (20 sessions)": Variant("mom_nse", 20, "nifty200_vt", 0.40, 20),
        "+ avoid bulk buys (60 sessions, sensitivity)": Variant("mom_nse", 20, "nifty200_vt", 0.40, 60)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=500_000)
    ap.add_argument("--out", default="reports/desk_filter")
    args = ap.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)

    panel, nifty = load_data("2010-01-01", with_bulk_events=True)
    sig = signals(panel)
    cm = default_model()
    share = FIXED_MIX[BASE.name.split("|sc")[0]]
    rows, curves, logs = [], {}, {}
    for label, v in RUNS.items():
        decisions: list = []
        curve, book = simulate(v, panel, sig, nifty, args.capital, cm, START, decisions=decisions)
        mixed = mix_curve(curve, share)
        curves[label] = mixed
        logs[label] = decisions
        for period, (a, b) in {"full": (START, None), "discovery": (START, HOLDOUT_START),
                               "holdout": (HOLDOUT_START, None)}.items():
            m = metrics(_seg(mixed, a, b))
            rows.append({"run": label, "period": period, "cagr_pct": round(100 * m["cagr"], 2),
                         "max_dd_pct": round(100 * m["max_dd"], 2), "sharpe": round(m["sharpe"], 2),
                         "vol_pct": round(100 * m["vol"], 2)})
        blocked_months = sum(1 for d in decisions if d.blocked)
        rows.append({"run": label, "period": "costs & activity", "cagr_pct": None, "max_dd_pct": None,
                     "sharpe": None, "vol_pct": None, "fees_rs": round(book.costs), "taxes_rs": round(book.taxes), "trades": book.trades,
                     "months_with_blocked_names": blocked_months,
                     "blocked_name_months": sum(len(d.blocked or []) for d in decisions)})
    res = pd.DataFrame(rows)
    res.to_csv(out / "results.csv", index=False)
    pd.DataFrame(curves).to_csv(out / "equity_curves.csv")

    # which names did the filter keep out, and how did they do over the next month?
    base_targets = {d.signal_date: set(d.targets) for d in logs["approved rules"]}
    close = panel["close"]
    skipped = []
    for d in logs["+ avoid bulk buys (20 sessions)"]:
        for sym in sorted(base_targets.get(d.signal_date, set()) - set(d.targets)):
            s = close.index.get_loc(d.signal_date)
            fwd = close[sym].iloc[s + 1: s + 22] if sym in close else pd.Series(dtype=float)
            r = fwd.iloc[-1] / fwd.iloc[0] - 1 if len(fwd) > 1 and fwd.iloc[0] > 0 else None
            skipped.append({"signal_date": d.signal_date.date(), "symbol": sym,
                            "next_month_return_pct": round(100 * r, 2) if r is not None else None})
    sk = pd.DataFrame(skipped)
    sk.to_csv(out / "skipped_names.csv", index=False)

    perf = res[res["period"].isin(["full", "discovery", "holdout"])]
    base_h = perf[(perf["run"] == "approved rules") & (perf["period"] == "holdout")].iloc[0]
    cand_h = perf[(perf["run"] == "+ avoid bulk buys (20 sessions)") & (perf["period"] == "holdout")].iloc[0]
    ok = cand_h["cagr_pct"] >= base_h["cagr_pct"] and cand_h["max_dd_pct"] >= base_h["max_dd_pct"]
    lines = ["# Decision Desk candidate filter: avoid non-institutional bulk buys", "",
             f"Generated {datetime.now():%Y-%m-%d %H:%M}. Window {START.date()} → {close.index.max().date()}, "
             f"₹{args.capital:,.0f} capital, {share:.0%} equity share + liquid fund, ICICI costs and taxes.", "",
             "## Performance", "", "| Run | Period | CAGR % | Max DD % | Sharpe | Vol % |", "|---|---|---|---|---|---|"]
    for r in perf.itertuples(index=False):
        lines.append(f"| {r.run} | {r.period} | {r.cagr_pct} | {r.max_dd_pct} | {r.sharpe} | {r.vol_pct} |")
    act = res[res["period"] == "costs & activity"]
    lines += ["", "## Activity", "", "| Run | Months with a blocked name | Blocked name-months | Fees ₹ | Taxes ₹ |",
              "|---|---|---|---|---|"]
    for r in act.itertuples(index=False):
        lines.append(f"| {r.run} | {int(r.months_with_blocked_names)} | {int(r.blocked_name_months)} | "
                     f"{int(r.fees_rs):,} | {int(r.taxes_rs):,} |")
    if len(sk):
        lines += ["", f"## Names the 20-session filter kept out ({len(sk)})", "",
                  f"Median next-month return of the skipped names: {sk['next_month_return_pct'].median():.2f}% "
                  f"(mean {sk['next_month_return_pct'].mean():.2f}%, {int((sk['next_month_return_pct'] < 0).sum())} of "
                  f"{sk['next_month_return_pct'].notna().sum()} negative)."]
    lines += ["", "## Verdict", "",
              ("PASSES the pre-registered test (holdout CAGR not lower and drawdown not deeper)." if ok else
               "FAILS the pre-registered test (holdout CAGR lower or drawdown deeper): do not adopt."),
              "", "Adoption still needs the owner's review: CLAUDE.md trading rules change only after review."]
    (out / "REPORT.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
