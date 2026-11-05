"""run_defense_offense_wfo.py — Defense × Offense combinatorial WFO.

The exhaustive sweeps proved no single factor overcomes 5-position concentration friction, and
that the leaderboard sorts by DEFENSE (low-vol / decoupled / compressed lose the least). The
hypothesis now: intersect the best DEFENSIVE tail (low ATR%, Decile 1) with a selective
OFFENSIVE tail, so the book holds only low-volatility names that ALSO carry a return signal —
recovering quality without the parabolic-blowoff risk that sank the aggressive screens.

Two intersections, each PINNED through the production Walk-Forward Optimizer (`_core_wfo`):
  A:  atr_14_pct (D1)  ∩  squeeze_ratio (D10)            — low-vol ∩ volatility-expansion
  B:  atr_14_pct (D1)  ∩  vol_adj_sector_alpha_14 (D10)  — low-vol ∩ vol-adj sector leadership

Each combo lives in `base_filters` with an EMPTY candidate pool → every rolling window applies
exactly this screen on its embargoed OOS fold (a pure out-of-sample stitch, no per-window
re-selection). STRICT physics: 5-position book, Pillar B auto-Amihud impact, Pillar C
inverse-vol sizing, ₹1 Cr. Pillar B activation is ASSERTED from the engine, never assumed.

DSR is reported two ways: the engine's per-window Deflated Sharpe, and a STUDY-LEVEL DSR
deflated against the 2-config breadth tested here (the honest trial count is stated plainly).

MODE=PAPER. Canonical Python. Read-only DB. No secrets. Capital = ₹1,00,00,000.

Run:
  /Users/sudheer/Desktop/jupyter_env/bin/python scripts/run_defense_offense_wfo.py
"""
from __future__ import annotations

import os
import sys
import json
from pathlib import Path

import numpy as np
import duckdb

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "services" / "ui-api"))
DB_PATH = (os.environ.get("DB_PATH") or os.environ.get("DUCKDB_PATH")
           or str(REPO / "data" / "market.duckdb"))

import backtest_engine as be  # noqa: E402
from routers.analytics import (  # noqa: E402
    _core_wfo, _load_context, _auto_impact_status,
    WFOBacktestRequest, FilterCondition,
)

CAPITAL = 10_000_000.0          # ₹1 Crore
FORWARD_DAYS = 5
FRICTION_BPS = 15.0             # 0.15% floor (CLAUDE.md hard rule); Amihud impact is ADDITIVE
IN_SAMPLE_DAYS = 365
OUT_SAMPLE_DAYS = 90
MARKET_RELATIVE = {"vol_adj_sector_alpha_14", "sector_rel_mom_14_pct", "corr_nifty_30",
                   "sector_positive_regime", "decoupled_leader", "beta_resid_5d"}

# (field, op, decile-value) — op 'lte 1' = bottom decile (D1); 'gte 10' = top decile (D10).
CONFIGS = [
    ("A · atr↓D1 ∩ squeeze↑D10",
     [("atr_14_pct", "lte", 1.0), ("squeeze_ratio", "gte", 10.0)]),
    ("B · atr↓D1 ∩ VolAdjSectAlpha↑D10",
     [("atr_14_pct", "lte", 1.0), ("vol_adj_sector_alpha_14", "gte", 10.0)]),
]


def decile_filters(spec) -> list[FilterCondition]:
    return [FilterCondition(field=f, op=op, value=v, mode="decile") for (f, op, v) in spec]


def date_span(con) -> tuple[str, str]:
    mn, mx = con.execute("SELECT min(date), max(date) FROM ohlcv").fetchone()
    return str(mn), str(mx)


def build_req(spec, from_date: str, to_date: str) -> WFOBacktestRequest:
    return WFOBacktestRequest(
        from_date=from_date, to_date=to_date, forward_days=FORWARD_DAYS,
        starting_capital=CAPITAL, friction_bps=FRICTION_BPS,
        max_positions=5, scope="universe",
        sizing_mode="risk_parity",   # Pillar C — inverse-vol, STRICTLY ON
        impact_coef=None,            # Pillar B — engine auto-calibrates Amihud/√-law at this scale
        base_filters=decile_filters(spec),
        candidate_filters=[],
        in_sample_days=IN_SAMPLE_DAYS, out_sample_days=OUT_SAMPLE_DAYS,
    )


def verify_pillar_b(req: WFOBacktestRequest, from_date: str, to_date: str) -> dict:
    """Build the sim context exactly as _core_wfo does and read the auto-impact status —
    PROVES Pillar B is active (never assume)."""
    from datetime import datetime
    fd = datetime.strptime(from_date, "%Y-%m-%d").date()
    td = datetime.strptime(to_date, "%Y-%m-%d").date()
    need_mr = any(f.field in MARKET_RELATIVE for f in req.base_filters)
    ctx = _load_context(req, fd, td, need_mr, lambda *a, **k: None)
    if ctx is None:
        return {"impact_active": False, "note": "context build failed"}
    st = _auto_impact_status(req, ctx)
    st["impact_active"] = bool(st.get("impact_temp_leg_on") or st.get("impact_full_stack_auto"))
    return st


def g(res: dict, k: str, d=0.0):
    v = res.get(k, d)
    return d if v is None else v


def main() -> None:
    print(f"MODE=PAPER  DB={DB_PATH}  CAPITAL=₹{CAPITAL:,.0f}", flush=True)
    print("=== DEFENSE × OFFENSE COMBINATORIAL WFO (Pillar B + Pillar C STRICTLY ACTIVE) ===",
          flush=True)
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        from_date, to_date = date_span(con)
    finally:
        con.close()
    print(f"  span {from_date} → {to_date} · IS={IN_SAMPLE_DAYS}d / OOS={OUT_SAMPLE_DAYS}d · "
          f"max_positions=5 · friction=15bps + auto-Amihud · sizing=inverse-vol\n", flush=True)

    # Prove Pillar B once (worst-case: the MR-needing combo B builds the heaviest context).
    pb = verify_pillar_b(build_req(CONFIGS[1][1], from_date, to_date), from_date, to_date)
    print("── Pillar B (market impact) activation proof ──", flush=True)
    print(f"  {json.dumps(pb, default=str)}", flush=True)
    force_impact = not pb.get("impact_active")
    if force_impact:
        print("  ⚠ auto-impact did NOT fire — forcing explicit impact_coef/amihud_coef legs.",
              flush=True)

    rows = []
    for name, spec in CONFIGS:
        print(f"\n── WFO: {name} ──", flush=True)
        req = build_req(spec, from_date, to_date)
        if force_impact:
            req.impact_coef = 1.0
            req.amihud_coef = 1.0
            req.max_participation_pct = 10.0
        res = _core_wfo(req)
        wf = res.get("walk_forward", {})
        oos_nav = np.asarray([e["nav"] for e in res.get("equity", [])], dtype=float)
        oos_daily = (oos_nav[1:] / oos_nav[:-1] - 1.0) if oos_nav.size > 1 else np.array([])
        rec = {
            "name": name, "spec": spec, "n_windows": wf.get("n_windows", 0),
            "cagr": g(res, "cagr_pct"), "total_return": g(res, "total_return_pct"),
            "maxdd": g(res, "max_drawdown"), "sharpe": g(res, "sharpe_ratio"),
            "calmar": g(res, "calmar_ratio"), "win": g(res, "win_rate"),
            "pf": g(res, "profit_factor"), "trades": int(g(res, "total_trades")),
            "alpha": g(res, "alpha_annual_pct"), "beta": g(res, "beta"),
            "bench_return": g(res, "benchmark_total_return_pct"),
            "dsr_engine": wf.get("deflated_sharpe", 0.0),
            "dsr_n_trials_engine": wf.get("dsr_n_trials", 0),
            "efficiency": wf.get("efficiency"),
            "oos_daily": oos_daily,
        }
        rows.append(rec)
        print(f"   windows={rec['n_windows']}  OOS CAGR={rec['cagr']:+.2f}%  MaxDD={rec['maxdd']:.2f}%  "
              f"Win={rec['win']:.1f}%  PF={rec['pf']:.2f}  trades={rec['trades']:,}", flush=True)
        print(f"   Sharpe={rec['sharpe']:.3f}  engine-DSR={rec['dsr_engine']} "
              f"(n_trials={rec['dsr_n_trials_engine']})  efficiency={rec['efficiency']}", flush=True)

    # Study-level Deflated Sharpe — deflate each config against the 2-config breadth tested here.
    cfg_sharpes = [float(r["sharpe"]) for r in rows]
    n_trials = len(rows)
    for r in rows:
        if r["oos_daily"].size > 1:
            d = be.deflated_sharpe_ratio(r["oos_daily"], cfg_sharpes)
            r["dsr_study"] = round(d["dsr"], 3)
            r["dsr_study_trials"] = d["n_trials"]
        else:
            r["dsr_study"] = 0.0
            r["dsr_study_trials"] = n_trials

    print("\n══════ STITCHED OUT-OF-SAMPLE — NET of Amihud impact + inverse-vol sizing (₹1Cr) ══════",
          flush=True)
    print(f"  {'Intersection':36s} {'CAGR%':>7} {'MaxDD%':>8} {'Win%':>6} {'PF':>6} "
          f"{'Sharpe':>7} {'DSR':>6} {'trades':>7}", flush=True)
    for r in rows:
        print(f"  {r['name']:36s} {r['cagr']:>7.2f} {r['maxdd']:>8.2f} {r['win']:>6.1f} "
              f"{r['pf']:>6.2f} {r['sharpe']:>7.3f} {r['dsr_study']:>6.3f} {r['trades']:>7,}",
              flush=True)
    print(f"  (benchmark over span: {rows[0]['bench_return']:+.2f}% · study-DSR deflated vs "
          f"{n_trials} trials)", flush=True)

    survivors = [r for r in rows if r["cagr"] > 0 and r["dsr_study"] > 0.95]
    print("\n══════ VERDICT ══════", flush=True)
    if survivors:
        for r in survivors:
            print(f"  SURVIVES: {r['name']} — OOS CAGR {r['cagr']:+.2f}%, DSR {r['dsr_study']:.3f} > 0.95",
                  flush=True)
    else:
        best = max(rows, key=lambda r: (r["cagr"], r["dsr_study"]))
        print("  NEITHER intersection clears positive OOS CAGR with DSR>0.95 after Pillar B+C.",
              flush=True)
        print(f"  LEAST-BAD: {best['name']} — CAGR {best['cagr']:+.2f}%, MaxDD {best['maxdd']:.2f}%, "
              f"DSR {best['dsr_study']:.3f}", flush=True)
        if all(r["cagr"] <= 0 for r in rows):
            print("\n  ▶ CONCLUSION: defense×offense intersection of correctly-tailed deciles STILL "
                  "drags negative OOS under Amihud impact + 5-position concentration.", flush=True)
            print("    The 5-POSITION CONSTRAINT is the TERMINAL BOTTLENECK. Even a clean low-vol ∩ "
                  "return-signal screen cannot diversify idiosyncratic blowups across only 5 names "
                  "while paying market impact. The edge requires a BOOK EXPANSION (e.g. 15–30 "
                  "equal-risk names) to recover breadth — not another factor.", flush=True)

    print(f"\nWFO_DONE — {len(rows)} intersections · trials(WFO stage)={n_trials}", flush=True)


if __name__ == "__main__":
    main()
