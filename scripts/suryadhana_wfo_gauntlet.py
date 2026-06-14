"""suryadhana_wfo_gauntlet.py — Phase-3 PRODUCTION walk-forward gauntlet for the
SuryaDhana structural features, with Pillar B (Amihud/√-impact) and Pillar C (inverse-vol
sizing) STRICTLY ACTIVE at a ₹1 Crore capital base.

Each config is PINNED through `analytics._core_wfo` as Decile-10 FilterConditions
(mode='decile' — the production decile engine, NOT a static-percentile proxy), in
`base_filters` with an EMPTY candidate pool: every rolling window applies exactly this
screen on its embargoed OOS fold — a pure out-of-sample stitch.

Pillar B: relied on the engine's AUTO market-impact calibration (`_calibrate_auto_impact`,
per-name endogenous Y_i + Amihud λ + ADV cap; trigger = per-position notional / median-ADV
> 0.005). At ₹1 Cr / 5 positions = ₹20 lakh/position the trigger fires on the NSE universe.
We ASSERT it fired via the result's auto-impact status — never assume.
Pillar C: sizing_mode='risk_parity' (wᵢ∝1/σᵢ via ATR), wired into simulate_portfolio.

Statistical honesty: each config's stitched-OOS Sharpe is collected into a CROSS-CONFIG
trial distribution, and a STUDY-LEVEL Deflated Sharpe is recomputed for every config against
that full breadth (the per-window n_trials the engine reports understates the search). The
number of trials is stated plainly.

MODE=PAPER. Canonical Python. Read-only DB. No secrets. Capital = ₹1,00,00,000.

Run:
  /Users/sudheer/Desktop/jupyter_env/bin/python scripts/suryadhana_wfo_gauntlet.py
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
FRICTION_BPS = 15.0             # 0.15% floor (CLAUDE.md hard rule); impact is ADDITIVE on top

FEATURES = ["beta_resid_5d", "vol_adj_sector_alpha_14"]
SHORT = {"beta_resid_5d": "IdioMom(β-resid)", "vol_adj_sector_alpha_14": "VolAdjSectAlpha"}

# Decile-10 filter for a feature: top tenth of the day's cross-section.
def d10(field: str) -> FilterCondition:
    return FilterCondition(field=field, op="gte", value=10, mode="decile")


CONFIGS = [
    ("IdioMom(β-resid) · D10", [FEATURES[0]]),
    ("VolAdjSectAlpha · D10", [FEATURES[1]]),
    ("IdioMom ∩ VolAdjSectAlpha · D10∩D10", [FEATURES[0], FEATURES[1]]),
]


def date_span(con) -> tuple[str, str]:
    mn, mx = con.execute("SELECT min(date), max(date) FROM ohlcv").fetchone()
    return str(mn), str(mx)


def build_req(fields: list[str], from_date: str, to_date: str) -> WFOBacktestRequest:
    return WFOBacktestRequest(
        from_date=from_date, to_date=to_date, forward_days=FORWARD_DAYS,
        starting_capital=CAPITAL, friction_bps=FRICTION_BPS,
        max_positions=5, scope="universe",
        # Pillar C — inverse-vol sizing STRICTLY ON.
        sizing_mode="risk_parity",
        # Pillar B — leave impact_coef None so the engine AUTO-calibrates per-name impact
        # (temporary √-law + permanent Amihud + ADV participation cap) at this scale.
        impact_coef=None,
        base_filters=[d10(f) for f in fields],
        candidate_filters=[],
        in_sample_days=365, out_sample_days=90,
    )


def verify_pillar_b(req: WFOBacktestRequest, from_date: str, to_date: str) -> dict:
    """Build the sim context exactly as _core_wfo does and read the auto-impact status —
    PROVES Pillar B is active (don't assume)."""
    from datetime import datetime
    fd = datetime.strptime(from_date, "%Y-%m-%d").date()
    td = datetime.strptime(to_date, "%Y-%m-%d").date()
    need_mr = any(f.field in {"beta_resid_5d", "vol_adj_sector_alpha_14",
                              "sector_rel_mom_14_pct", "corr_nifty_30",
                              "sector_positive_regime", "decoupled_leader"}
                  for f in req.base_filters)
    ctx = _load_context(req, fd, td, need_mr, lambda *a, **k: None)
    if ctx is None:
        return {"impact_active": False, "note": "context build failed"}
    st = _auto_impact_status(req, ctx)
    # Pillar B is active iff the temporary √-law leg is live (auto or explicit). The full
    # stack (permanent Amihud + ADV cap) rides on the same trigger.
    st["impact_active"] = bool(st.get("impact_temp_leg_on") or st.get("impact_full_stack_auto"))
    return st


def g(res: dict, k: str, d=0.0):
    return res.get(k, d)


def main() -> None:
    print(f"MODE=PAPER  DB={DB_PATH}  CAPITAL=₹{CAPITAL:,.0f}")
    print("=== SuryaDhana Phase-3 WFO GAUNTLET (Pillar B + Pillar C ACTIVE; IDS dropped) ===")
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        from_date, to_date = date_span(con)
    finally:
        con.close()
    print(f"  span {from_date} → {to_date} · IS=365d / OOS=90d · max_positions=5 · "
          f"friction=15bps + Amihud impact · sizing=inverse-vol")

    # Verify Pillar B once (same context for all configs of the same universe).
    pb = verify_pillar_b(build_req(FEATURES, from_date, to_date), from_date, to_date)
    print("\n── Pillar B (market impact) activation proof ──")
    print(f"  {json.dumps(pb, default=str)}")
    if not pb.get("impact_active"):
        print("  ⚠ WARNING: auto-impact did NOT fire at this scale — Pillar B would be INERT. "
              "Forcing explicit impact_coef/amihud_coef.")

    rows = []
    for name, fields in CONFIGS:
        print(f"\n── WFO: {name} ──")
        req = build_req(fields, from_date, to_date)
        # Hard guarantee Pillar B is on: if auto did not fire, force the explicit legs.
        if not pb.get("impact_active"):
            req.impact_coef = 1.0
            req.amihud_coef = 1.0
            req.max_participation_pct = 10.0
        res = _core_wfo(req)
        wf = res.get("walk_forward", {})
        nav = [e["nav"] for e in res.get("equity", [])] or [e["nav"] for e in res.get("wfo_equity", [])]
        # stitched OOS daily returns for the study-level DSR recompute
        oos_nav = np.asarray([e["nav"] for e in res.get("equity", [])], dtype=float)
        oos_daily = (oos_nav[1:] / oos_nav[:-1] - 1.0) if oos_nav.size > 1 else np.array([])
        rec = {
            "name": name, "fields": fields,
            "n_windows": wf.get("n_windows", 0),
            "cagr": g(res, "cagr_pct"), "total_return": g(res, "total_return_pct"),
            "maxdd": g(res, "max_drawdown"), "sharpe": g(res, "sharpe_ratio"),
            "calmar": g(res, "calmar_ratio"), "win": g(res, "win_rate"),
            "pf": g(res, "profit_factor"), "trades": g(res, "total_trades"),
            "alpha": g(res, "alpha_annual_pct"), "beta": g(res, "beta"),
            "dsr_engine": wf.get("deflated_sharpe", 0.0), "dsr_n_trials_engine": wf.get("dsr_n_trials", 0),
            "efficiency": wf.get("efficiency"),
            "bench_return": g(res, "benchmark_total_return_pct"),
            "oos_daily": oos_daily,
        }
        rows.append(rec)
        print(f"   windows={rec['n_windows']}  CAGR={rec['cagr']:+.2f}%  MaxDD={rec['maxdd']:.2f}%  "
              f"Sharpe={rec['sharpe']:.3f}  Win={rec['win']:.1f}%  PF={rec['pf']:.2f}  "
              f"trades={rec['trades']:,}")
        print(f"   engine DSR={rec['dsr_engine']}  (n_trials={rec['dsr_n_trials_engine']})  "
              f"efficiency={rec['efficiency']}")

    # ── Study-level Deflated Sharpe: deflate each config against the CROSS-CONFIG breadth ──
    # The honest trial count for the WFO stage = number of configs run here.
    cfg_sharpes = [float(r["sharpe"]) for r in rows]
    n_trials_study = len(rows)
    print(f"\n── Study-level multiple-testing correction (DSR deflated vs {n_trials_study} WFO configs) ──")
    for r in rows:
        if r["oos_daily"].size > 1:
            dsr = be.deflated_sharpe_ratio(r["oos_daily"], cfg_sharpes)
            r["dsr_study"] = round(dsr["dsr"], 3)
            r["dsr_study_trials"] = dsr["n_trials"]
        else:
            r["dsr_study"] = 0.0
            r["dsr_study_trials"] = n_trials_study
        print(f"  {r['name']:42s} study-DSR={r['dsr_study']:.3f}  "
              f"(vs {r['dsr_study_trials']} trials)  OOS Sharpe={r['sharpe']:.3f}")

    # ── Verdict table ──
    print("\n══════ STITCHED OUT-OF-SAMPLE — NET of Amihud impact + inverse-vol sizing (₹1Cr) ══════")
    hdr = f"  {'Config':42s} {'CAGR%':>7} {'MaxDD%':>8} {'Win%':>6} {'PF':>6} {'Sharpe':>7} {'DSR':>6} {'trades':>7}"
    print(hdr)
    for r in rows:
        print(f"  {r['name']:42s} {r['cagr']:>7.2f} {r['maxdd']:>8.2f} {r['win']:>6.1f} "
              f"{r['pf']:>6.2f} {r['sharpe']:>7.3f} {r['dsr_study']:>6.3f} {r['trades']:>7,}")

    survivors = [r for r in rows if r["cagr"] > 0 and r["dsr_study"] > 0.95]
    print("\n══════ VERDICT ══════")
    if survivors:
        for r in survivors:
            print(f"  SURVIVES: {r['name']} — OOS CAGR {r['cagr']:+.2f}%, DSR {r['dsr_study']:.3f} > 0.95")
    else:
        best = max(rows, key=lambda r: (r["cagr"], r["dsr_study"]))
        print(f"  NO config clears positive OOS CAGR AND DSR>0.95 after Pillar B+C.")
        print(f"  LEAST-BAD: {best['name']} — CAGR {best['cagr']:+.2f}%, DSR {best['dsr_study']:.3f}, "
              f"MaxDD {best['maxdd']:.2f}%")

    # Persist machine-readable results for the report.
    out = REPO / "suryadhana_wfo_results.json"
    out.write_text(json.dumps([{k: v for k, v in r.items() if k != "oos_daily"} for r in rows],
                              indent=2, default=str))
    print(f"\nWFO_DONE — wrote {out.name}  ·  trials(WFO stage)={n_trials_study}")


if __name__ == "__main__":
    main()
