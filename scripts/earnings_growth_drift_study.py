#!/usr/bin/env python
"""
Earnings-growth drift on NSE — the pre-registered study in reports/earnings_growth_drift/PLAN.md.

    PYTHONPATH=. python scripts/earnings_growth_drift_study.py [--out reports/earnings_growth_drift]

Events: every quarterly filing in the FA cache (data/nse_archive/financials/*.json), bucketed by what the
numbers said (profit / revenue growth vs the same quarter a year earlier). Entry/exit mechanics, the benchmark
and the statistics are those of scripts/results_drift_study.py (entry at the open after the reaction session,
excess vs the equal-weight liquid universe, weekly Newey-West t). Writes REPORT.md, events.csv, summary.json.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "services" / "data-service"))
import financials as fin  # noqa: E402
from results_drift_study import build_events, period_stats, snapshot_connect, table  # noqa: E402
from held_overnight_study import newey_west_t  # noqa: E402
from shared.nse_panel import load_panel  # noqa: E402
from shared.trading_costs import default_model  # noqa: E402

SPLIT = pd.Timestamp("2025-07-01")
HORIZONS = (20, 60)
POSITION_RS = 50_000
BUCKETS = ("strong growth", "growth", "decline", "collapse")


def fundamental_bucket(pat_yoy: float | None, rev_yoy: float | None, turn: str | None) -> str | None:
    """PLAN.md buckets, fixed before the data was assembled."""
    if turn == "to loss":
        return "collapse"
    if turn in ("to profit", "loss both") or pat_yoy is None:
        return None
    if pat_yoy >= 30 and rev_yoy is not None and rev_yoy >= 10:
        return "strong growth"
    if pat_yoy >= 0:
        return "growth"
    if pat_yoy > -30:
        return "decline"
    return "collapse"


def load_filings(root: Path) -> pd.DataFrame:
    rows = []
    for p in sorted(root.glob("*.json")):
        cache = fin.load(root, p.stem) or {}
        for q in fin.with_growth(cache.get("quarters") or []):
            if not q.get("filed_at"):
                continue
            b = fundamental_bucket(q.get("pat_yoy"), q.get("revenue_yoy"), q.get("pat_yoy_turn"))
            rows.append({"symbol": p.stem, "period_end": q["period_end"], "released_at": pd.Timestamp(q["filed_at"]),
                         "pat_yoy": q.get("pat_yoy"), "revenue_yoy": q.get("revenue_yoy"), "turn": q.get("pat_yoy_turn"),
                         "fbucket": b})
    return pd.DataFrame(rows)


def spread(d: pd.DataFrame, h: int) -> dict:
    d = d.dropna(subset=[f"ex{h}"])
    up = d[d["fbucket"] == "strong growth"].groupby(d["entry_date"].dt.to_period("W"))[f"ex{h}"].mean()
    dn = d[d["fbucket"] == "collapse"].groupby(d["entry_date"].dt.to_period("W"))[f"ex{h}"].mean()
    w = (up - dn).dropna()
    return {"weeks": len(w), "spread": round(float(w.mean()), 2) if len(w) else None,
            "t_nw": round(newey_west_t(w, max(1, h // 5)), 2) if len(w) > 2 else None}


def within_sample(d: pd.DataFrame, h: int, bucket: str = "strong growth") -> dict:
    """PLAN addendum check: each filing's excess minus the average excess of every sampled filing entered the same
    week (removes whatever the whole sample shares, e.g. selection bias), averaged per week for `bucket`, with a
    Newey-West t (lags h/5)."""
    d = d.dropna(subset=[f"ex{h}"]).copy()
    wk = d["entry_date"].dt.to_period("W")
    d["within"] = d[f"ex{h}"] - d.groupby(wk)[f"ex{h}"].transform("mean")
    b = d[d["fbucket"] == bucket]
    w = b.groupby(wk[d["fbucket"] == bucket])["within"].mean()
    return {"weeks": len(w), "within": round(float(w.mean()), 2) if len(w) else None,           # weekly mean (the rule)
            "within_events": round(float(b["within"].mean()), 2) if len(b) else None,           # every filing equal
            "t_nw": round(newey_west_t(w, max(1, h // 5)), 2) if len(w) > 2 else None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/earnings_growth_drift")
    args = ap.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)

    filings = load_filings(ROOT / "data" / "nse_archive" / "financials")
    if filings.empty:
        raise SystemExit("FA cache is empty: run the financials sweep first")
    start = (filings["released_at"].min() - pd.Timedelta(days=400)).date().isoformat()
    tmp = Path(tempfile.mkdtemp(prefix="egd_"))
    try:
        con = snapshot_connect(tmp)
        panel = load_panel(con, start=start)
        con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    cost = default_model().round_trip_pct(POSITION_RS)
    ev = build_events(panel, filings[["symbol", "period_end", "released_at"]])
    ev["period_end"] = ev["period_end"].astype(str)
    ev = ev.merge(filings[["symbol", "period_end", "pat_yoy", "revenue_yoy", "turn", "fbucket"]], on=["symbol", "period_end"], how="left")
    ev = ev[ev["fbucket"].notna()].reset_index(drop=True)
    ev.to_csv(out / "events.csv", index=False)
    parts = {"discovery": ev[ev["entry_date"] < SPLIT], "holdout": ev[ev["entry_date"] >= SPLIT]}

    stats: dict = {}
    for h in HORIZONS:
        for b in BUCKETS + ("all",):
            for p, d in parts.items():
                stats[(h, b, p)] = period_stats(d if b == "all" else d[d["fbucket"] == b], h, cost)
    sp = {p: spread(d, 60) for p, d in parts.items()}
    within = {p: within_sample(d, 60) for p, d in parts.items()}
    within_ok = all((within[p]["within"] or 0) > 0 for p in parts)
    g60 = {p: stats[(60, "strong growth", p)] for p in parts}
    c60 = {p: stats[(60, "collapse", p)] for p in parts}
    h1 = (g60["discovery"].get("avg_excess", -1) > 0 and g60["holdout"].get("avg_excess", -1) > 0
          and g60["discovery"].get("t_nw", 0) >= 2.0 and g60["holdout"].get("excess_after_costs", -1) > 0)
    h2 = (c60["discovery"].get("avg_excess", 1) < 0 and c60["holdout"].get("avg_excess", 1) < 0
          and c60["discovery"].get("t_nw", 0) <= -2.0)
    h3 = all((sp[p]["spread"] or 0) > 0 for p in parts)

    # descriptive: strong growth split by the price reaction (PLAN.md)
    sg = ev[ev["fbucket"] == "strong growth"].dropna(subset=["ex60"])
    by_react = {k: period_stats(d, 60, cost) for k, d in (("reaction ≥ +2%", sg[sg["reaction_x"] >= 2]), ("reaction < +2%", sg[sg["reaction_x"] < 2]))}

    companies = ev["symbol"].nunique()
    # survivorship check (PLAN addendum): companies in the sample whose last NSE close is over a month old
    last_px = panel["close"].apply(lambda c: c.last_valid_index())
    cutoff = panel["close"].index.max() - pd.Timedelta(days=30)
    gone = sorted(s for s in ev["symbol"].unique() if s in last_px.index and last_px[s] is not None and last_px[s] < cutoff)
    span = f"{ev['entry_date'].min():%Y-%m-%d} → {ev['entry_date'].max():%Y-%m-%d}" if len(ev) else "—"
    label = "" if out.name == "earnings_growth_drift" else f" ({out.name} run)"
    L = [f"# Earnings-growth drift: report{label}", "",
         f"Run {datetime.now():%Y-%m-%d %H:%M} · plan: PLAN.md (pre-registered 13 Oct 2026, 15:00) · {len(ev)} filings from "
         f"{companies} companies · entries {span} · round-trip cost {cost:.2f}% at ₹{POSITION_RS:,}", "",
         f"Companies that have since stopped trading (last close > 30 days before the data end): {len(gone)}"
         + (f" ({', '.join(gone[:12])}{'…' if len(gone) > 12 else ''})" if gone else ""), "",
         "## Verdict on the pre-registered hypotheses (60 sessions)", "",
         f"- **H1 strong growth drifts up:** {'PASS' if h1 else 'FAIL'}",
         f"- **H2 collapse drifts down (avoid):** {'PASS' if h2 else 'FAIL'}",
         f"- **H3 strong growth − collapse spread positive in both halves:** {'PASS' if h3 else 'FAIL'}",
         f"- **Addendum check, strong growth vs same-week filings (positive in both halves):** {'yes' if within_ok else 'no'} · "
         + " · ".join(f"{p} {v['within']}% weekly / {v['within_events']}% per filing (t {v['t_nw']}, {v['weeks']} weeks)" for p, v in within.items()), ""]
    for h in HORIZONS:
        rows = []
        for b in BUCKETS + ("all",):
            for p in parts:
                s = stats[(h, b, p)]
                rows.append({"bucket": b, "period": p, **{k: s.get(k) for k in ("events", "weeks", "avg_excess", "median_excess",
                                                                                  "beat_pct", "t_nw", "excess_after_costs")}})
        L += [f"## {h} sessions after entry (excess vs equal-weight liquid universe, %)", "",
              table(rows, ["bucket", "period", "events", "weeks", "avg_excess", "median_excess", "beat_pct", "t_nw", "excess_after_costs"]), ""]
    L += ["## Strong growth − collapse, weekly spread (60 sessions)", "",
          table([{"period": p, **v} for p, v in sp.items()], ["period", "weeks", "spread", "t_nw"]), "",
          "## Descriptive: strong growth by price reaction (60 sessions, both halves together)", "",
          table([{"split": k, **{x: v.get(x) for x in ("events", "avg_excess", "beat_pct", "t_nw", "excess_after_costs")}} for k, v in by_react.items()],
                ["split", "events", "avg_excess", "beat_pct", "t_nw", "excess_after_costs"]), "",
          "## Caveats (from the plan)", "",
          ("- Selection / survivorship: companies read are today's liquid names plus holdings / Desk / watchlist." if not label else
           "- Universe: every NSE EQ name with median turnover ≥ ₹1 cr since Jan 2024 whose filings NSE still serves; "
           "companies NSE no longer serves are missing (those that stopped trading are counted above)."),
          "- Short history: about eight quarters with growth per company, so both halves are small.",
          "- A year-ago quarter revised after the current filing leaks slightly (rare, not corrected).", ""]
    (out / "REPORT.md").write_text("\n".join(L), encoding="utf-8")
    summary = {"h1": h1, "h2": h2, "h3": h3, "within60": within, "within_ok": within_ok, "events": len(ev), "companies": companies, "stopped_trading": gone, "cost_pct": round(cost, 3),
               "stats": {f"{h}|{b}|{p}": v for (h, b, p), v in stats.items()}, "spread60": sp}
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
    print(f"events {len(ev)} companies {companies} · H1 {h1} H2 {h2} H3 {h3} · within {within} → {out / 'REPORT.md'}")


if __name__ == "__main__":
    main()
