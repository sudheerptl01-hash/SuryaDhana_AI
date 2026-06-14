"""run_direction_aware_sweep.py — the DIRECTION-AWARE single-factor sweep.

The uniform top-decile sweep (`run_all_filters_backtest.py`) went 0-for-27, but it screened
EVERY continuous factor at the top decile — which inverts the thesis for mean-reverting /
value / low-vol / decoupling factors (a high P/E, a high ATR%, a high market-correlation, or
a price stretched far above its 200-DMA is the *wrong* tail to be long). This script maps each
factor to its STRUCTURALLY CORRECT execution tail via `FACTOR_TAIL_MAP`, then re-runs the
identical 5-position concentrated book (Pillar A decile selection + Pillar B auto-Amihud impact
+ Pillar C inverse-vol sizing, ₹1 Cr) so we can see whether aligning the math to the right tail
uncovers a genuine standalone edge.

Tail convention (decile target for a LONG book):
  • Momentum / trend / accumulation / quality / income → DECILE 10 (top 10%).
  • Mean-reversion / value / low-vol / decoupling        → DECILE  1 (bottom 10%).
  • Boolean flags                                        → native truth (gte 1), no tail.

Researcher's notes on judgment calls (surfaced, not hidden):
  • `squeeze_ratio` is kept at D10 per the directive's momentum bucket — i.e. a volatility-
    EXPANSION/breakout read. The compression thesis (BB/KC < 1 ⇒ squeeze) would instead target
    D1; flip the map entry to test it.
  • `div_yld_pct` → D10 (the value/income signal is HIGH yield, not low).
  • `mktcap_cr` → D10 (prefer liquid large-caps in an impact-charged book; the small-cap-premium
    read would be D1). It is near-inert anyway — PIT fundamentals are sparse (<20 trades).

MODE=PAPER. Canonical Python. Read-only DB. No secrets. Capital = ₹1,00,00,000.
NOT promoted to WFO — this is an in-sample direction-alignment screen only.

Run:
  /Users/sudheer/Desktop/jupyter_env/bin/python scripts/run_direction_aware_sweep.py
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
MIN_TRADES = 120

# Boolean flags — screened by native truth (gte 1), NOT decile-ranked.
BOOLEAN_FILTERS = {
    "price_gt_ma50", "price_gt_ma200", "ma50_gt_ma200", "volume_gt_avg",
    "vipt_breakout", "intention_pullback", "squeeze_on", "sector_positive_regime",
    "decoupled_leader",
}

# Each continuous factor → structurally correct decile target for a LONG book.
FACTOR_TAIL_MAP = {
    # ── Momentum / trend / accumulation → TOP decile (D10) ──
    "rsi_14": 10,
    "above_52w_low_pct": 10,
    "within_52w_high_pct": 10,
    "vmi_ratio": 10,
    "vol_zscore_20": 10,
    "intraday_intention": 10,
    "squeeze_ratio": 10,            # directive's momentum bucket (expansion read); see header note
    "sector_rel_mom_14_pct": 10,
    "beta_resid_5d": 10,
    "vol_adj_sector_alpha_14": 10,
    "prob_up": 10,
    # ── Quality / income → TOP decile (high is good) ──
    "roce_pct": 10,
    "div_yld_pct": 10,             # value/income = HIGH yield
    "mktcap_cr": 10,               # liquid large-cap (judgment); near-inert (sparse PIT data)
    # ── Mean-reversion / value / low-vol / decoupling → BOTTOM decile (D1) ──
    "pe_ratio": 1,                 # cheap = low P/E
    "atr_14_pct": 1,               # low volatility
    "dist_ma200_pct": 1,           # most oversold relative to long-term trend
    "corr_nifty_30": 1,            # most decoupled (lowest 30d market correlation)
}


def date_span(con) -> tuple[str, str]:
    mn, mx = con.execute("SELECT min(date), max(date) FROM ohlcv").fetchone()
    return str(mn), str(mx)


def tail_label(field: str) -> str:
    if field in BOOLEAN_FILTERS:
        return "bool"
    return "D10" if FACTOR_TAIL_MAP[field] == 10 else "D1"


def build_filter(field: str) -> FilterCondition:
    if field in BOOLEAN_FILTERS:
        return FilterCondition(field=field, op="gte", value=1.0, mode="absolute")
    tail = FACTOR_TAIL_MAP[field]
    if tail == 10:
        return FilterCondition(field=field, op="gte", value=10.0, mode="decile")   # top decile
    return FilterCondition(field=field, op="lte", value=1.0, mode="decile")        # bottom decile


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
    # Coverage check: every catalog filter must be classified.
    unmapped = [f for f in FILTER_CATALOG if f not in BOOLEAN_FILTERS and f not in FACTOR_TAIL_MAP]
    if unmapped:
        raise SystemExit(f"unmapped filters (classify them first): {unmapped}")

    print(f"MODE=PAPER  DB={DB_PATH}  CAPITAL=₹{CAPITAL:,.0f}", flush=True)
    print("=== DIRECTION-AWARE SWEEP — structurally correct tails (decile + Amihud + inverse-vol) ===",
          flush=True)
    con = duckdb.connect(DB_PATH, read_only=True)
    try:
        from_date, to_date = date_span(con)
    finally:
        con.close()
    fields = list(FILTER_CATALOG.keys())
    flips = [f for f in fields if f in FACTOR_TAIL_MAP and FACTOR_TAIL_MAP[f] == 1]
    print(f"  span {from_date} → {to_date} · {len(fields)} filters · max_positions=5 · "
          f"friction=15bps + auto-Amihud · sizing=inverse-vol", flush=True)
    print(f"  tail flips vs uniform-top sweep (now bottom-decile D1): {flips}\n", flush=True)
    print(f"  {'#':>2} {'filter':26s} {'tail':6s} {'CAGR%':>8} {'MaxDD%':>8} {'Sharpe':>7} "
          f"{'Win%':>6} {'PF':>6} {'trades':>7}", flush=True)

    rows = []
    t0 = time.time()
    for i, field in enumerate(fields, 1):
        tl = tail_label(field)
        try:
            res = _core_backtest(build_req(field, from_date, to_date))
            rec = {
                "field": field, "label": FILTER_CATALOG[field].get("label", field), "tail": tl,
                "cagr": g(res, "cagr_pct"), "total_return": g(res, "total_return_pct"),
                "maxdd": g(res, "max_drawdown"), "sharpe": g(res, "sharpe_ratio"),
                "sortino": g(res, "sortino_ratio"), "calmar": g(res, "calmar_ratio"),
                "win": g(res, "win_rate"), "pf": g(res, "profit_factor"),
                "trades": int(g(res, "total_trades")), "alpha": g(res, "alpha_annual_pct"),
                "beta": g(res, "beta"), "bench_return": g(res, "benchmark_total_return_pct"),
                "impact_active": bool((res.get("config") or {}).get("impact_full_stack_auto", False)),
                "error": "",
            }
        except Exception as e:  # never let one filter kill the sweep
            rec = {"field": field, "label": FILTER_CATALOG[field].get("label", field), "tail": tl,
                   "cagr": 0.0, "total_return": 0.0, "maxdd": 0.0, "sharpe": 0.0, "sortino": 0.0,
                   "calmar": 0.0, "win": 0.0, "pf": 0.0, "trades": 0, "alpha": 0.0, "beta": 0.0,
                   "bench_return": 0.0, "impact_active": False, "error": f"{type(e).__name__}: {e}"}
            print(f"     ! {field}: {type(e).__name__}: {e}", flush=True)
            traceback.print_exc()
        rows.append(rec)
        flag = "" if not rec["error"] else "  ✖ERR"
        print(f"  {i:>2} {field:26s} {tl:6s} {rec['cagr']:>8.2f} {rec['maxdd']:>8.2f} "
              f"{rec['sharpe']:>7.3f} {rec['win']:>6.1f} {rec['pf']:>6.2f} "
              f"{rec['trades']:>7,}{flag}", flush=True)

    elapsed = time.time() - t0

    # ── Leaderboard — CREDIBLE ONLY (≥120 trades, no error), ranked by CAGR ──
    credible = sorted([r for r in rows if r["trades"] >= MIN_TRADES and not r["error"]],
                      key=lambda r: r["cagr"], reverse=True)
    print(f"\n══════ DIRECTION-AWARE LEADERBOARD — credible only (≥{MIN_TRADES} trades), ₹1Cr NET ══════",
          flush=True)
    print(f"  {'rank':>4} {'filter':26s} {'tail':6s} {'CAGR%':>8} {'MaxDD%':>8} {'Calmar':>7} "
          f"{'Sharpe':>7} {'Win%':>6} {'PF':>6} {'trades':>7}", flush=True)
    for rnk, r in enumerate(credible, 1):
        print(f"  {rnk:>4} {r['field']:26s} {r['tail']:6s} {r['cagr']:>8.2f} {r['maxdd']:>8.2f} "
              f"{r['calmar']:>7.2f} {r['sharpe']:>7.3f} {r['win']:>6.1f} {r['pf']:>6.2f} "
              f"{r['trades']:>7,}", flush=True)

    pos = [r for r in credible if r["cagr"] > 0]
    print("\n── Verdict ──", flush=True)
    if pos:
        print(f"  POSITIVE standalone edges found: {len(pos)} / {len(credible)} credible", flush=True)
        for r in pos:
            print(f"    + {r['field']} ({r['tail']}): CAGR {r['cagr']:+.2f}%  MaxDD {r['maxdd']:.2f}%  "
                  f"Sharpe {r['sharpe']:.3f}  PF {r['pf']:.2f}  trades {r['trades']:,}", flush=True)
    else:
        best = credible[0] if credible else None
        print(f"  STILL 0 positive standalone edges across {len(credible)} credible configs.", flush=True)
        if best:
            print(f"  LEAST-BAD: {best['field']} ({best['tail']}) — CAGR {best['cagr']:+.2f}%  "
                  f"MaxDD {best['maxdd']:.2f}%  Sharpe {best['sharpe']:.3f}", flush=True)

    # ── Persist ──
    out = REPO / "direction_aware_results.csv"
    cols = ["field", "label", "tail", "cagr", "total_return", "maxdd", "calmar", "sharpe",
            "sortino", "win", "pf", "trades", "alpha", "beta", "bench_return",
            "impact_active", "error"]
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in sorted(rows, key=lambda r: r["cagr"], reverse=True):
            w.writerow({k: r.get(k, "") for k in cols})
    print(f"\nSWEEP_DONE — {len(rows)} filters in {elapsed:,.0f}s  ·  wrote {out.name}", flush=True)
    print("  NB: in-sample direction-alignment screen. NOT promoted to WFO.", flush=True)


if __name__ == "__main__":
    main()
