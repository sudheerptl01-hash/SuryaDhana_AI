#!/usr/bin/env python
"""
Does FII index-futures positioning predict NIFTY? The pre-registered study in reports/fii_positioning/PLAN.md.

    PYTHONPATH=. python scripts/fii_positioning_study.py [--out reports/fii_positioning]

Reads a snapshot copy of data/market.duckdb (safe while data-service runs).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from held_overnight_study import newey_west_t  # noqa: E402

HORIZONS = (5, 20)
SPLIT = pd.Timestamp("2023-01-01")
MIN_HISTORY = 120          # sessions before expanding tercile cut-offs / percentile ranks are used


def load(tmp: Path) -> pd.DataFrame:
    db = ROOT / "data" / "market.duckdb"
    snap = tmp / "s.duckdb"
    shutil.copy2(db, snap)
    if Path(f"{db}.wal").exists():
        shutil.copy2(f"{db}.wal", f"{snap}.wal")
    con = duckdb.connect(str(snap))
    fii = con.execute("""SELECT date, fut_idx_long AS long, fut_idx_short AS short FROM nse_participant_oi
                         WHERE client_type = 'FII' ORDER BY date""").df()
    nifty = con.execute("SELECT date, close FROM market_index_daily WHERE symbol = 'NIFTY50' ORDER BY date").df()
    con.close()
    fii["date"], nifty["date"] = pd.to_datetime(fii["date"]), pd.to_datetime(nifty["date"])
    return fii.merge(nifty, on="date", how="inner").set_index("date").sort_index()


def build(df: pd.DataFrame) -> pd.DataFrame:
    d = df.copy()
    d["net"] = d["long"] - d["short"]
    d["long_pct"] = d["long"] / (d["long"] + d["short"]) * 100
    d["s1"] = d["net"].diff(5)
    # S2: percentile of today's long ratio within the trailing 250 sessions (past values only, today included)
    d["s2_pctile"] = d["long_pct"].rolling(250, min_periods=MIN_HISTORY).apply(lambda w: (w[:-1] < w[-1]).mean() * 100, raw=True)
    for h in HORIZONS:
        d[f"fwd{h}"] = (d["close"].shift(-(1 + h)) / d["close"].shift(-1) - 1) * 100
    # expanding tercile cut-offs for S1, from data strictly before t
    lo = d["s1"].expanding(MIN_HISTORY).quantile(1 / 3).shift(1)
    hi = d["s1"].expanding(MIN_HISTORY).quantile(2 / 3).shift(1)
    d["s1_bucket"] = np.where(d["s1"] >= hi, "top", np.where(d["s1"] <= lo, "bottom", "middle"))
    d.loc[lo.isna() | d["s1"].isna(), "s1_bucket"] = None
    return d


def spread_stats(d: pd.DataFrame, h: int) -> dict:
    """Daily series: fwd return × (+1 top tercile, −1 bottom tercile), averaged → long-short in % per window."""
    x = d.dropna(subset=[f"fwd{h}", "s1_bucket"])
    top, bot = x[x["s1_bucket"] == "top"][f"fwd{h}"], x[x["s1_bucket"] == "bottom"][f"fwd{h}"]
    sig = pd.Series(np.where(x["s1_bucket"] == "top", 1.0, np.where(x["s1_bucket"] == "bottom", -1.0, 0.0)), index=x.index)
    demeaned = (x[f"fwd{h}"] - x[f"fwd{h}"].mean()) * sig
    active = demeaned[sig != 0]
    return {"days": len(x), "top_n": len(top), "bottom_n": len(bot), "top_mean": round(top.mean(), 3),
            "bottom_mean": round(bot.mean(), 3), "spread": round(top.mean() - bot.mean(), 3),
            "t_nw": round(newey_west_t(active, h), 2)}


def extreme_stats(d: pd.DataFrame, h: int) -> dict:
    x = d.dropna(subset=[f"fwd{h}", "s2_pctile"])
    ext = x["s2_pctile"] <= 10
    excess = x[f"fwd{h}"] - x[f"fwd{h}"].mean()
    e = excess[ext]
    return {"days": len(x), "extreme_days": int(ext.sum()), "extreme_mean": round(x.loc[ext, f"fwd{h}"].mean(), 3),
            "all_mean": round(x[f"fwd{h}"].mean(), 3), "excess": round(e.mean(), 3) if len(e) else None,
            "t_nw": round(newey_west_t(e, h), 2) if len(e) > 3 else None}


def table(rows: list[dict], cols: list[str]) -> str:
    return ("| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
            + "\n".join("| " + " | ".join("" if r.get(c) is None else str(r.get(c)) for c in cols) + " |" for r in rows))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/fii_positioning")
    args = ap.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="fii_"))
    try:
        d = build(load(tmp))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    halves = {"full": d, "2019–2022": d[d.index < SPLIT], "2023–2026": d[d.index >= SPLIT]}
    s1 = {(h, k): spread_stats(v, h) for h in HORIZONS for k, v in halves.items()}
    s2 = {(h, k): extreme_stats(v, h) for h in HORIZONS for k, v in halves.items()}
    h1 = (s1[(20, "full")]["spread"] > 0 and s1[(20, "full")]["t_nw"] >= 2.0
          and s1[(20, "2019–2022")]["spread"] > 0 and s1[(20, "2023–2026")]["spread"] > 0)
    h2 = (s2[(20, "full")]["excess"] or -1) > 0 and (s2[(20, "full")]["t_nw"] or 0) >= 2.0 and \
         all((s2[(20, k)]["excess"] or -1) > 0 for k in ("2019–2022", "2023–2026"))
    L = ["# Does FII index-futures positioning predict NIFTY?", "",
         f"Generated {datetime.now():%Y-%m-%d %H:%M} by `scripts/fii_positioning_study.py`; plan fixed beforehand in `PLAN.md`.",
         f"{len(d):,} sessions {d.index.min().date()} → {d.index.max().date()}; target = NIFTY 50 return from the close after the "
         "signal day. Overlapping windows → Newey-West t with lags = horizon.", "",
         "## Verdicts (pre-registered)", "",
         table([{"hypothesis": "H1 · 5-day FII futures flow: top minus bottom tercile → next 20 sessions", "result": "**PASS**" if h1 else "**FAIL**",
                 "detail": f"spread {s1[(20, 'full')]['spread']}% (t {s1[(20, 'full')]['t_nw']}); halves {s1[(20, '2019–2022')]['spread']}% / {s1[(20, '2023–2026')]['spread']}%"},
                {"hypothesis": "H2 · FII long ratio in the bottom 10% of its year → next 20 sessions vs average", "result": "**PASS**" if h2 else "**FAIL**",
                 "detail": f"excess {s2[(20, 'full')]['excess']}% (t {s2[(20, 'full')]['t_nw']}, {s2[(20, 'full')]['extreme_days']} days); "
                           f"halves {s2[(20, '2019–2022')]['excess']}% / {s2[(20, '2023–2026')]['excess']}%"}],
               ["hypothesis", "result", "detail"]), "",
         "## S1 · flow terciles", "",
         table([{"horizon": h, "period": k, **s1[(h, k)]} for h in HORIZONS for k in halves],
               ["horizon", "period", "days", "top_n", "bottom_n", "top_mean", "bottom_mean", "spread", "t_nw"]), "",
         "## S2 · positioning extreme (bottom decile of the trailing year)", "",
         table([{"horizon": h, "period": k, **s2[(h, k)]} for h in HORIZONS for k in halves],
               ["horizon", "period", "days", "extreme_days", "extreme_mean", "all_mean", "excess", "t_nw"]), "",
         f"FII long ratio today: {d['long_pct'].iloc[-1]:.1f}% (trailing-year percentile {d['s2_pctile'].iloc[-1]:.0f})."]
    (out / "REPORT.md").write_text("\n".join(L) + "\n")
    (out / "summary.json").write_text(json.dumps({"H1": bool(h1), "H2": bool(h2)}, indent=1))
    print("\n".join(L))


if __name__ == "__main__":
    main()
