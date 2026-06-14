"""run_all_filters_backtest.py — run EVERY filter in the production FILTER_CATALOG as a
solo screen through the institutional backtest engine, then rank them.

This is a one-factor-at-a-time SWEEP (not a combinatorial search): for each of the 27
catalog filters we build a single-filter `BacktestRequest` and push it through
`analytics._core_backtest` with the full institutional physics ACTIVE —
  • Pillar A  — continuous factors filtered in `mode='decile'` (top decile of the day's
               cross-section), so the screen tracks the best *relative* names each bar
               instead of a frozen static threshold. Boolean flags use their native truth.
  • Pillar B  — auto-calibrated Amihud / √-law market impact + ADV participation cap
               (impact_coef=None ⇒ engine auto-fires at ₹1 Cr / 5 positions on NSE ADV).
  • Pillar C  — sizing_mode='risk_parity' (wᵢ∝1/σᵢ via ATR), inverse-vol 5-position book.

CONVENTION (stated plainly): continuous factors are screened at the TOP decile (highest
values). For mean-reverting / "lower-is-better" factors (P/E, ATR%, market-correlation) a
poor result is EXPECTED and is itself informative — it is not a claim that the top decile is
the favourable tail. This sweep is a hypothesis-ranking pass over a single full-period
in-sample backtest; it is NOT an out-of-sample certification. Promote any winner to
`scripts/suryadhana_wfo_gauntlet.py` (rolling WFO + Deflated Sharpe) before trusting it.

MODE=PAPER. Canonical Python. Read-only DB. No secrets. Capital = ₹1,00,00,000.

Run:
  /Users/sudheer/Desktop/jupyter_env/bin/python scripts/run_all_filters_backtest.py
"""
from __future__ import annotations

import os
import sys
import csv
import time
import traceback
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "services" / "ui-api"))
DB_PATH = (os.environ.get("DB_PATH") or os.environ.get("DUCKDB_PATH")
           or str(REPO / "data" / "market.duckdb"))

from routers.analytics import (  # noqa: E402
    _core_backtest, FILTER_CATALOG, BacktestRequest, FilterCondition,
)

CAPITAL = 10_000_000.0          # ₹1 Crore
FORWARD_DAYS = 5
FRICTION_BPS = 15.0             # 0.15% floor (CLAUDE.md hard rule); impact is ADDITIVE on top

# Boolean flags — screened by native truth (gte 1), NOT decile-ranked.
BOOLEAN_FILTERS = {
    "price_gt_ma50", "price_gt_ma200", "ma50_gt_ma200", "volume_gt_avg",
    "vipt_breakout", "intention_pullback", "squeeze_on", "sector_positive_regime",
    "decoupled_leader",
}
# Filters that need the market-relative pass (Nifty/sector) — engine loads it on demand.
MARKET_RELATIVE = {
    "sector_rel_mom_14_pct", "sector_positive_regime", "corr_nifty_30",
    "decoupled_leader", "beta_resid_5d", "vol_adj_sector_alpha_14",
}


def date_span(con) -> tuple[str, str]:
    mn, mx = con.execute("SELECT min(date), max(date) FROM ohlcv").fetchone()
    return str(mn), str(mx)


def build_filter(field: str) -> FilterCondition:
    """Boolean → native truth (absolute, gte 1). Continuous → top decile (Pillar A)."""
    if field in BOOLEAN_FILTERS:
        return FilterCondition(field=field, op="gte", value=1.0, mode="absolute")
    return FilterCondition(field=field, op="gte", value=10.0, mode="decile")


def build_req(field: str, from_date: str, to_date: str) -> BacktestRequest:
    return BacktestRequest(
        from_date=from_date, to_date=to_date, forward_days=FORWARD_DAYS,
        starting_capital=CAPITAL, friction_bps=FRICTION_BPS,
        max_positions=5, scope="universe",
        sizing_mode="risk_parity",   # Pillar C — inverse-vol
        impact_coef=None,            # Pillar B — auto-calibrated at this scale
        filters=[build_filter(field)],
    )


def g(res: dict, k: str, d=0.0):
    v = res.get(k, d)
    return d if v is None else v


def main() -> None:
    print(f"MODE=PAPER  DB={DB_PATH}  CAPITAL=₹{CAPITAL:,.0f}", flush=True)
    print("=== ALL-FILTER BACKTEST SWEEP — institutional physics (decile + Amihud + inverse-vol) ===",
          flush=True)
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        from_date, to_date = date_span(con)
    finally:
        con.close()
    fields = list(FILTER_CATALOG.keys())
    print(f"  span {from_date} → {to_date} · {len(fields)} filters · max_positions=5 · "
          f"friction=15bps + auto-Amihud · sizing=inverse-vol\n", flush=True)
    print(f"  {'#':>2} {'filter':26s} {'mode':8s} {'CAGR%':>8} {'MaxDD%':>8} {'Sharpe':>7} "
          f"{'Win%':>6} {'PF':>6} {'trades':>7}", flush=True)

    rows = []
    t0 = time.time()
    for i, field in enumerate(fields, 1):
        mode = "bool" if field in BOOLEAN_FILTERS else "decile10"
        try:
            res = _core_backtest(build_req(field, from_date, to_date))
            rec = {
                "field": field, "label": FILTER_CATALOG[field].get("label", field), "mode": mode,
                "cagr": g(res, "cagr_pct"), "total_return": g(res, "total_return_pct"),
                "maxdd": g(res, "max_drawdown"), "sharpe": g(res, "sharpe_ratio"),
                "sortino": g(res, "sortino_ratio"), "calmar": g(res, "calmar_ratio"),
                "win": g(res, "win_rate"), "pf": g(res, "profit_factor"),
                "trades": int(g(res, "total_trades")), "alpha": g(res, "alpha_annual_pct"),
                "beta": g(res, "beta"), "bench_return": g(res, "benchmark_total_return_pct"),
                "impact_active": bool((res.get("config") or {}).get("impact_full_stack_auto", False)
                                      or g(res, "impact_full_stack_auto", False)),
                "error": "",
            }
        except Exception as e:  # never let one filter kill the sweep
            rec = {"field": field, "label": FILTER_CATALOG[field].get("label", field), "mode": mode,
                   "cagr": 0.0, "total_return": 0.0, "maxdd": 0.0, "sharpe": 0.0, "sortino": 0.0,
                   "calmar": 0.0, "win": 0.0, "pf": 0.0, "trades": 0, "alpha": 0.0, "beta": 0.0,
                   "bench_return": 0.0, "impact_active": False, "error": f"{type(e).__name__}: {e}"}
            print(f"     ! {field}: {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
        rows.append(rec)
        flag = "" if not rec["error"] else "  ✖ERR"
        print(f"  {i:>2} {field:26s} {mode:8s} {rec['cagr']:>8.2f} {rec['maxdd']:>8.2f} "
              f"{rec['sharpe']:>7.3f} {rec['win']:>6.1f} {rec['pf']:>6.2f} "
              f"{rec['trades']:>7,}{flag}", flush=True)

    elapsed = time.time() - t0

    # ── Ranked leaderboard (by CAGR), trade-count floor flagged ──
    MIN_TRADES = 120
    ranked = sorted(rows, key=lambda r: r["cagr"], reverse=True)
    print(f"\n══════ LEADERBOARD — solo filter, full-period in-sample, ₹1Cr (NET of impact) ══════",
          flush=True)
    print(f"  {'rank':>4} {'filter':26s} {'CAGR%':>8} {'MaxDD%':>8} {'Calmar':>7} {'Sharpe':>7} "
          f"{'Win%':>6} {'PF':>6} {'trades':>7}", flush=True)
    for rnk, r in enumerate(ranked, 1):
        thin = " ⚠<120" if r["trades"] < MIN_TRADES else ""
        print(f"  {rnk:>4} {r['field']:26s} {r['cagr']:>8.2f} {r['maxdd']:>8.2f} "
              f"{r['calmar']:>7.2f} {r['sharpe']:>7.3f} {r['win']:>6.1f} {r['pf']:>6.2f} "
              f"{r['trades']:>7,}{thin}", flush=True)

    credible = [r for r in ranked if r["trades"] >= MIN_TRADES and not r["error"]]
    print("\n── Read (credible = ≥120 trades, no error) ──", flush=True)
    if credible:
        best = credible[0]
        pos = [r for r in credible if r["cagr"] > 0]
        print(f"  best CAGR : {best['field']} ({best['label']})  {best['cagr']:+.2f}%  "
              f"MaxDD {best['maxdd']:.2f}%  Sharpe {best['sharpe']:.3f}  trades {best['trades']:,}",
              flush=True)
        print(f"  positive-CAGR filters: {len(pos)} / {len(credible)} credible "
              f"(of {len(rows)} total)", flush=True)
    else:
        print("  no filter cleared the 120-trade floor cleanly.", flush=True)

    # ── Persist ──
    out = REPO / "all_filters_backtest_results.csv"
    cols = ["field", "label", "mode", "cagr", "total_return", "maxdd", "calmar", "sharpe",
            "sortino", "win", "pf", "trades", "alpha", "beta", "bench_return",
            "impact_active", "error"]
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in ranked:
            w.writerow({k: r.get(k, "") for k in cols})
    print(f"\nSWEEP_DONE — {len(rows)} filters in {elapsed:,.0f}s  ·  wrote {out.name}", flush=True)
    print("  NB: full-period in-sample sweep. Promote winners to scripts/suryadhana_wfo_gauntlet.py "
          "(rolling WFO + DSR) before trusting any edge.", flush=True)


if __name__ == "__main__":
    main()
