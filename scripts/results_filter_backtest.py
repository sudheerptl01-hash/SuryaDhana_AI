#!/usr/bin/env python
"""
Candidate Decision Desk rule: do not open new positions in stocks whose results-day reaction was
≤ −5% vs the market in the last N sessions (post-results drift study, reports/results_drift H2).

Pre-registered in reports/results_filter/PLAN.md:
  * baseline  = the approved rules (mom_nse | N20 | nifty200_vt | sector cap 40%)
  * primary   = baseline + skip names with a strong bad results reaction in the last 60 sessions
  * sensitivity = 20 sessions (reported, not a candidate)
  * window Mar-2015 → latest; discovery before Jul-2024, holdout from Jul-2024; ₹5 lakh, 66% equity + liquid fund,
    real ICICI costs and taxes.
It reuses the Desk's own entry blocklist (StrategyConfig.avoid_bulk_buy_days reads panel["bulk_buy_events"]), fed
with results events instead of deals, so no strategy code changes. Run results_drift_study.py first (events.csv).

    PYTHONPATH=. python scripts/results_filter_backtest.py [--capital 500000] [--out reports/results_filter]
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

START = pd.Timestamp("2015-03-01")
BASE = Variant("mom_nse", 20, "nifty200_vt", 0.40)
CAND = "+ skip after bad results (60 sessions)"
RUNS = {"approved rules": BASE,
        CAND: Variant("mom_nse", 20, "nifty200_vt", 0.40, 60),
        "+ skip after bad results (20 sessions, sensitivity)": Variant("mom_nse", 20, "nifty200_vt", 0.40, 20)}
BAD_REACTION_PCT = -5.0


def bad_results_events(path: Path) -> pd.DataFrame:
    """(date, symbol) of results reactions ≤ −5 % vs the equal-weight universe, dated on the reaction session."""
    ev = pd.read_csv(path, usecols=["symbol", "reaction_date", "reaction_x"], parse_dates=["reaction_date"])
    ev = ev[ev["reaction_x"] <= BAD_REACTION_PCT]
    return ev.rename(columns={"reaction_date": "date"})[["date", "symbol"]].drop_duplicates().reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--capital", type=float, default=500_000)
    ap.add_argument("--out", default="reports/results_filter")
    ap.add_argument("--events", default="reports/results_drift/events.csv")
    args = ap.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)

    panel, nifty = load_data("2010-01-01")
    panel["bulk_buy_events"] = bad_results_events(ROOT / args.events)     # the Desk's generic entry blocklist
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
    for d in logs[CAND]:
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
    cand_h = perf[(perf["run"] == CAND) & (perf["period"] == "holdout")].iloc[0]
    ok = cand_h["cagr_pct"] >= base_h["cagr_pct"] and cand_h["max_dd_pct"] >= base_h["max_dd_pct"]
    lines = ["# Decision Desk candidate filter: skip stocks after bad results", "",
             f"Plan: `PLAN.md` (pre-registered). Events: results reactions ≤ −5 % vs the market (`{args.events}`).", "",
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
        lines += ["", f"## Names the 60-session filter kept out ({len(sk)})", "",
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
