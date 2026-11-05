#!/usr/bin/env python
"""
Post-results drift (PEAD) on NSE — the pre-registered study in reports/results_drift/PLAN.md.

    PYTHONPATH=. python scripts/results_drift_study.py [--out reports/results_drift]

Reads a snapshot copy of data/market.duckdb (safe while data-service runs). Release times: nse_results
(fill it first: POST data-service /jobs/ingest-results). Prices: the split/bonus-adjusted NSE bhavcopy panel.
Writes REPORT.md (+ events.csv, summary.json) to --out.
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
from shared.nse_panel import load_panel  # noqa: E402
from shared.momentum import is_etf  # noqa: E402
from shared.trading_costs import default_model  # noqa: E402
from held_overnight_study import newey_west_t  # noqa: E402

PANEL_START = "2014-06-01"
DISCOVERY_START, DISCOVERY_END = pd.Timestamp("2015-01-01"), pd.Timestamp("2021-12-31")
HORIZONS = (20, 60)
POSITION_RS = 50_000
MIN_TURNOVER_CR, MIN_PRICE = 5.0, 20.0
BUCKETS = [("strong up", 5.0, np.inf), ("up", 2.0, 5.0), ("flat", -2.0, 2.0), ("down", -5.0, -2.0), ("strong down", -np.inf, -5.0)]
MARKET_OPEN, MARKET_CLOSE = (9, 15), (15, 30)


def snapshot_connect(tmp: Path) -> duckdb.DuckDBPyConnection:
    db = ROOT / "data" / "market.duckdb"
    snap = tmp / "s.duckdb"
    shutil.copy2(db, snap)
    if Path(f"{db}.wal").exists():
        shutil.copy2(f"{db}.wal", f"{snap}.wal")
    return duckdb.connect(str(snap))


def bucket(x: float) -> str | None:
    """PLAN.md cut-offs, symmetric: ≥ +5 strong up, ≥ +2 up, ≤ −5 strong down, ≤ −2 down, else flat."""
    if not np.isfinite(x):
        return None
    if x >= 5:
        return "strong up"
    if x >= 2:
        return "up"
    if x <= -5:
        return "strong down"
    if x <= -2:
        return "down"
    return "flat"


def reaction_index(released: pd.Timestamp, sessions: pd.DatetimeIndex) -> tuple[int | None, str]:
    """Row of the reaction session R in `sessions` and the timing label (same rule as results_history)."""
    day = released.normalize()
    pos = int(sessions.searchsorted(day, side="left"))
    in_session = pos < len(sessions) and sessions[pos] == day and (released.hour, released.minute) < MARKET_CLOSE
    timing = ("pre-open" if (released.hour, released.minute) < MARKET_OPEN else "market hours") if in_session else "after close"
    if not in_session and pos < len(sessions) and sessions[pos] == day:
        pos += 1
    return (pos if 0 < pos < len(sessions) else None), timing


def build_events(panel: dict, releases: pd.DataFrame) -> pd.DataFrame:
    o, c, to = panel["open"], panel["close"], panel["turnover_cr"]
    sessions = c.index
    series, raw = panel["series"], panel["raw_close"]
    med_to = to.rolling(20, min_periods=10).median()
    tradable = series.eq("EQ") & (raw >= MIN_PRICE) & (med_to >= MIN_TURNOVER_CR)
    tradable &= pd.Series([not is_etf(str(s)) for s in c.columns], index=c.columns)
    # equal-weight liquid universe (≥ ₹1 cr, EQ, ≥ ₹20): daily close-to-close and the open→close-h windows
    univ = series.eq("EQ") & (raw >= MIN_PRICE) & (to.rolling(20, min_periods=10).median() >= 1.0)
    ret1 = c.pct_change(fill_method=None)
    ew1 = ret1.where(univ.shift(1, fill_value=False)).mean(axis=1)
    cols = {s: i for i, s in enumerate(c.columns)}
    C, O, TR, U = c.to_numpy(), o.to_numpy(), tradable.to_numpy(), univ.to_numpy()

    def bench(i_entry: int, i_exit: int) -> float:
        m = U[i_entry - 1]
        r = C[i_exit, m] / O[i_entry, m] - 1
        r = r[np.isfinite(r)]
        return float(r.mean()) if len(r) else np.nan

    bench_cache: dict[tuple[int, int], float] = {}
    rows = []
    for ev in releases.itertuples():
        j = cols.get(ev.symbol)
        if j is None:
            continue
        R, timing = reaction_index(pd.Timestamp(ev.released_at), sessions)
        if R is None or R + 1 >= len(sessions) or not TR[R - 1, j]:
            continue
        c0, c1, o1 = C[R - 1, j], C[R, j], O[R, j]
        if not (np.isfinite(c0) and np.isfinite(c1)) or c0 <= 0:
            continue
        react = (c1 / c0 - 1) * 100
        react_x = react - ew1.iloc[R] * 100
        row = {"symbol": ev.symbol, "period_end": ev.period_end, "released_at": pd.Timestamp(ev.released_at),
               "timing": timing, "reaction_date": sessions[R], "entry_date": sessions[R + 1],
               "reaction_pct": react, "reaction_x": react_x, "gap_pct": (o1 / c0 - 1) * 100 if np.isfinite(o1) else np.nan,
               "held_gap": bool(np.isfinite(o1) and c1 >= o1), "turnover_cr": float(to.iloc[R - 1, j]),
               "bucket": bucket(react_x)}
        e_open = O[R + 1, j]
        for h in HORIZONS:
            x = R + h
            if x >= len(sessions) or not np.isfinite(e_open) or e_open <= 0 or not np.isfinite(C[x, j]):
                row[f"fwd{h}"] = row[f"bench{h}"] = row[f"ex{h}"] = np.nan
                continue
            key = (R + 1, x)
            if key not in bench_cache:
                bench_cache[key] = bench(R + 1, x)
            fwd = (C[x, j] / e_open - 1) * 100
            row[f"fwd{h}"], row[f"bench{h}"] = fwd, bench_cache[key] * 100
            row[f"ex{h}"] = fwd - bench_cache[key] * 100
        rows.append(row)
    return pd.DataFrame(rows)


def period_stats(ev: pd.DataFrame, h: int, cost: float) -> dict:
    d = ev.dropna(subset=[f"ex{h}"])
    if d.empty:
        return {"events": 0}
    weekly = d.groupby(d["entry_date"].dt.to_period("W"))[f"ex{h}"].mean()
    lags = max(1, h // 5)
    return {"events": len(d), "weeks": len(weekly), "avg_excess": round(d[f"ex{h}"].mean(), 2),
            "median_excess": round(d[f"ex{h}"].median(), 2), "beat_pct": round((d[f"ex{h}"] > 0).mean() * 100, 1),
            "t_nw": round(newey_west_t(weekly, lags), 2), "avg_return": round(d[f"fwd{h}"].mean(), 2),
            "excess_after_costs": round(d[f"ex{h}"].mean() - cost, 2)}


def split(ev: pd.DataFrame) -> dict[str, pd.DataFrame]:
    disc = ev[(ev["entry_date"] >= DISCOVERY_START) & (ev["entry_date"] <= DISCOVERY_END)]
    hold = ev[ev["entry_date"] > DISCOVERY_END]
    return {"discovery": disc, "holdout": hold}


def table(rows: list[dict], cols: list[str]) -> str:
    head = "| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n"
    return head + "\n".join("| " + " | ".join("" if r.get(c) is None else str(r.get(c)) for c in cols) + " |" for r in rows)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="reports/results_drift")
    args = ap.parse_args()
    out = ROOT / args.out
    out.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="pead_"))
    try:
        con = snapshot_connect(tmp)
        releases = con.execute("SELECT symbol, period_end, released_at FROM nse_results WHERE released_at >= ?::TIMESTAMP",
                               [PANEL_START]).df()
        panel = load_panel(con, start=PANEL_START)
        con.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    cost = default_model().round_trip_pct(POSITION_RS)
    ev = build_events(panel, releases)
    ev = ev[ev["entry_date"] >= DISCOVERY_START].reset_index(drop=True)
    ev.to_csv(out / "events.csv", index=False)
    parts = split(ev)
    last_entry = ev.dropna(subset=["ex60"])["entry_date"].max()

    stats: dict = {}
    for h in HORIZONS:
        for b, _, _ in BUCKETS:
            for p, d in parts.items():
                stats[(h, b, p)] = period_stats(d[d["bucket"] == b], h, cost)
        for p, d in parts.items():
            stats[(h, "all", p)] = period_stats(d, h, cost)

    def spread(p: str, h: int) -> dict:
        d = parts[p].dropna(subset=[f"ex{h}"])
        up = d[d["bucket"] == "strong up"].groupby(d["entry_date"].dt.to_period("W"))[f"ex{h}"].mean()
        dn = d[d["bucket"] == "strong down"].groupby(d["entry_date"].dt.to_period("W"))[f"ex{h}"].mean()
        w = (up - dn).dropna()
        return {"weeks": len(w), "spread": round(float(w.mean()), 2) if len(w) else None,
                "t_nw": round(newey_west_t(w, max(1, h // 5)), 2) if len(w) > 2 else None}

    s60 = {p: stats[(60, "strong up", p)] for p in parts}
    d60 = {p: stats[(60, "strong down", p)] for p in parts}
    sp = {p: spread(p, 60) for p in parts}
    h1 = (s60["discovery"].get("avg_excess", -1) > 0 and s60["holdout"].get("avg_excess", -1) > 0
          and s60["discovery"].get("t_nw", 0) >= 2.0 and s60["holdout"].get("excess_after_costs", -1) > 0)
    h2 = (d60["discovery"].get("avg_excess", 1) < 0 and d60["holdout"].get("avg_excess", 1) < 0
          and d60["discovery"].get("t_nw", 0) <= -2.0)
    h3 = all((sp[p]["spread"] or 0) > 0 for p in parts)

    L = ["# Post-results drift on NSE (PEAD)", "",
         f"Generated {datetime.now():%Y-%m-%d %H:%M} by `scripts/results_drift_study.py`; plan fixed beforehand in "
         "`PLAN.md` (read it first). Release times from NSE (`nse_results`), prices: split/bonus-adjusted bhavcopy.", "",
         f"- Events: **{len(ev):,}** quarterly results of {ev['symbol'].nunique()} stocks; entries {ev['entry_date'].min():%Y-%m-%d} → "
         f"{ev['entry_date'].max():%Y-%m-%d} (60-session results through entries of {last_entry:%Y-%m-%d}).",
         f"- Discovery {len(parts['discovery']):,} events (2015–2021) · holdout {len(parts['holdout']):,} (2022 →).",
         f"- Round-trip cost {cost:.2f}% (ICICI, ₹{POSITION_RS:,}). Excess = vs the equal-weight liquid NSE universe, entry at the "
         "next open after the reaction session.", "",
         "## Verdicts (pre-registered)", "",
         table([
             {"hypothesis": "H1 · drift after strong good news (≥ +5% excess reaction)", "result": "**PASS**" if h1 else "**FAIL**",
              "detail": f"60d excess {s60['discovery'].get('avg_excess')}% (t {s60['discovery'].get('t_nw')}) / "
                        f"{s60['holdout'].get('avg_excess')}% (t {s60['holdout'].get('t_nw')}); holdout after costs {s60['holdout'].get('excess_after_costs')}%"},
             {"hypothesis": "H2 · drift after strong bad news (≤ −5%)", "result": "**PASS**" if h2 else "**FAIL**",
              "detail": f"60d excess {d60['discovery'].get('avg_excess')}% (t {d60['discovery'].get('t_nw')}) / "
                        f"{d60['holdout'].get('avg_excess')}% (t {d60['holdout'].get('t_nw')})"},
             {"hypothesis": "H3 · strong-up minus strong-down spread > 0", "result": "**PASS**" if h3 else "**FAIL**",
              "detail": f"{sp['discovery']['spread']}% (t {sp['discovery']['t_nw']}) / {sp['holdout']['spread']}% (t {sp['holdout']['t_nw']})"},
         ], ["hypothesis", "result", "detail"]), ""]
    for h in HORIZONS:
        L += [f"## Forward excess by reaction bucket — {h} sessions", ""]
        rows = []
        for b in [x[0] for x in BUCKETS] + ["all"]:
            for p in parts:
                s = stats[(h, b, p)]
                rows.append({"bucket": b, "period": p, **s})
        L += [table(rows, ["bucket", "period", "events", "weeks", "avg_excess", "median_excess", "beat_pct", "t_nw",
                           "avg_return", "excess_after_costs"]), ""]

    # ── exploratory (not pre-registered) ──
    L += ["## Exploratory (not pre-registered; qualifies, never overturns, the verdicts)", ""]
    ex_rows = []
    for name, mask in [("strong up · gap held (close ≥ open)", (ev["bucket"] == "strong up") & ev["held_gap"]),
                       ("strong up · gap faded (close < open)", (ev["bucket"] == "strong up") & ~ev["held_gap"]),
                       ("strong up · after-close releases", (ev["bucket"] == "strong up") & (ev["timing"] == "after close")),
                       ("strong up · market-hours releases", (ev["bucket"] == "strong up") & (ev["timing"] == "market hours")),
                       ("strong up · turnover ≥ ₹50 cr", (ev["bucket"] == "strong up") & (ev["turnover_cr"] >= 50)),
                       ("strong up · turnover < ₹50 cr", (ev["bucket"] == "strong up") & (ev["turnover_cr"] < 50)),
                       ("strong down · turnover ≥ ₹50 cr", (ev["bucket"] == "strong down") & (ev["turnover_cr"] >= 50)),
                       ("reaction ≥ +10%", ev["reaction_x"] >= 10), ("reaction ≤ −10%", ev["reaction_x"] <= -10)]:
        for p, d in split(ev[mask]).items():
            ex_rows.append({"slice": name, "period": p, **period_stats(d, 60, cost)})
    L += [table(ex_rows, ["slice", "period", "events", "weeks", "avg_excess", "median_excess", "beat_pct", "t_nw", "excess_after_costs"]), ""]

    by_year = []
    for y, d in ev.dropna(subset=["ex60"]).groupby(ev["entry_date"].dt.year):
        su, sd = d[d["bucket"] == "strong up"]["ex60"], d[d["bucket"] == "strong down"]["ex60"]
        by_year.append({"year": y, "events": len(d), "strong_up_n": len(su), "strong_up_ex60": round(su.mean(), 2) if len(su) else None,
                        "strong_down_n": len(sd), "strong_down_ex60": round(sd.mean(), 2) if len(sd) else None})
    L += ["### Strong buckets by year (60 sessions)", "", table(by_year, ["year", "events", "strong_up_n", "strong_up_ex60", "strong_down_n", "strong_down_ex60"]), ""]
    rx = ev["reaction_x"]
    L += ["### Reaction sizes", "",
          f"Median absolute excess reaction {rx.abs().median():.2f}%; share ≥ +5%: {(rx >= 5).mean() * 100:.1f}%, ≤ −5%: {(rx <= -5).mean() * 100:.1f}%. "
          f"Timing: {ev['timing'].value_counts().to_dict()}.", ""]
    (out / "REPORT.md").write_text("\n".join(L) + "\n")
    (out / "summary.json").write_text(json.dumps({"H1": h1, "H2": h2, "H3": h3, "events": len(ev), "cost_pct": cost,
                                                  "strong_up_60": s60, "strong_down_60": d60, "spread_60": sp}, indent=1, default=str))
    print("\n".join(L[:22]))


if __name__ == "__main__":
    main()
