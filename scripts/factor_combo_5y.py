#!/usr/bin/env python
"""
factor_combo_5y.py — full-filter sweep, multi-filter combos, 5-year + YoY.

Builds on factor_range_optimizer.py. Adds:
  • the boolean trend/volume toggle filters (price>MA50/200, golden cross, vol>avg)
    alongside the decile-derived numeric ranges,
  • multi-filter COMBINED strategies (intersection of complementary signals),
  • a full 5-year run and a YEAR-ON-YEAR breakdown of the best logic.

Exit = time-stop only (no flat SL). Rationale established empirically: a flat 2%
stop is structurally incompatible with high-ATR selection (the stop fires on
normal intraday noise and churns the edge to zero). Friction floored to 15 bps.
MODE = PAPER.

Numeric ranges were derived by the decile profiler on an in-sample window
(2023-06..2024-12); the boolean filters are parameter-free. 2023-24 is therefore
in-sample for the numeric thresholds — flagged in the YoY table.
"""
from __future__ import annotations

import json
import sys
import urllib.request

BASE = "http://localhost:8010"
FORWARD_DAYS, CAPITAL, MAX_POS = 5, 10_000_000, 5
FULL = ("2021-06-01", "2026-06-01")

# Decile-derived numeric ranges (in-sample 2023-06..2024-12) + parameter-free booleans.
SINGLES: dict[str, list[dict]] = {
    "rsi_14 ≤ 47.8":          [{"field": "rsi_14", "op": "lte", "value": 47.8163}],
    "atr_14_pct ≥ 4.21":      [{"field": "atr_14_pct", "op": "gte", "value": 4.2071}],
    "dist_ma200 ≤ -8.63":     [{"field": "dist_ma200_pct", "op": "lte", "value": -8.629}],
    "above_52w_low ≥ 53.4":   [{"field": "above_52w_low_pct", "op": "gte", "value": 53.4412}],
    "within_52w_high ≥ 25.4": [{"field": "within_52w_high_pct", "op": "gte", "value": 25.4132}],
    "price > MA50":           [{"field": "price_gt_ma50", "op": "gt", "value": 0}],
    "price > MA200":          [{"field": "price_gt_ma200", "op": "gt", "value": 0}],
    "MA50 > MA200 (golden)":  [{"field": "ma50_gt_ma200", "op": "gt", "value": 0}],
    "volume > 20d avg":       [{"field": "volume_gt_avg", "op": "gt", "value": 0}],
}

ATR = {"field": "atr_14_pct", "op": "gte", "value": 4.2071}
RSI = {"field": "rsi_14", "op": "lte", "value": 47.8163}
COMBOS: dict[str, list[dict]] = {
    "ATR≥4.21 + RSI≤47.8":              [ATR, RSI],
    "ATR≥4.21 + price>MA200":           [ATR, {"field": "price_gt_ma200", "op": "gt", "value": 0}],
    "ATR≥4.21 + vol>avg":               [ATR, {"field": "volume_gt_avg", "op": "gt", "value": 0}],
    "ATR≥4.21 + golden cross":          [ATR, {"field": "ma50_gt_ma200", "op": "gt", "value": 0}],
    "ATR≥4.21 + RSI≤47.8 + price>MA200": [ATR, RSI, {"field": "price_gt_ma200", "op": "gt", "value": 0}],
    "ATR≥4.21 + RSI≤47.8 + vol>avg":     [ATR, RSI, {"field": "volume_gt_avg", "op": "gt", "value": 0}],
    "ATR≥4.21 + RSI≤47.8 + golden":      [ATR, RSI, {"field": "ma50_gt_ma200", "op": "gt", "value": 0}],
}


def post(path: str, p: dict, t: int = 300) -> dict:
    r = urllib.request.Request(f"{BASE}{path}", data=json.dumps(p).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(r, timeout=t).read().decode())


def bt(filters: list[dict], frm: str, to: str) -> dict:
    return post("/api/analytics/backtest", {
        "from_date": frm, "to_date": to, "forward_days": FORWARD_DAYS, "win_threshold": 0.0,
        "filters": filters, "friction_bps": 15.0, "starting_capital": CAPITAL,
        "max_positions": MAX_POS, "stop_loss_pct": None, "scope": "universe",
        "entry_timing": "next_open",
    })


def row(label: str, r: dict) -> dict:
    return {"label": label, "trades": r.get("total_trades", 0),
            "ret": r.get("total_return_pct", 0.0), "bmk": r.get("benchmark_total_return_pct", 0.0),
            "cagr": r.get("cagr_pct", 0.0), "alpha": r.get("alpha_annual_pct", 0.0),
            "sharpe": r.get("sharpe_ratio", 0.0), "dd": r.get("max_drawdown", 0.0),
            "win": r.get("win_rate", 0.0), "exp": r.get("expectancy", 0.0),
            "pf": r.get("profit_factor", 0.0)}


def table(rows: list[dict], title: str) -> None:
    print(f"\n{title}")
    hdr = f"{'strategy':<36}{'trades':>7}{'ret%':>9}{'bmk%':>7}{'cagr%':>8}{'alpha%':>8}{'sharpe':>8}{'maxDD%':>8}{'win%':>7}{'exp%':>8}{'PF':>6}"
    print(hdr); print("-" * len(hdr))
    for x in rows:
        print(f"{x['label']:<36}{x['trades']:>7}{x['ret']:>9.2f}{x['bmk']:>7.2f}{x['cagr']:>8.2f}"
              f"{x['alpha']:>8.2f}{x['sharpe']:>8.2f}{x['dd']:>8.2f}{x['win']:>7.1f}{x['exp']:>8.3f}{x['pf']:>6.2f}")
    sys.stdout.flush()


def main() -> None:
    print("=" * 120)
    print(f"5-YEAR UNIVERSE BACKTEST  {FULL[0]} → {FULL[1]}  | time-stop only | friction 15bps | cap ₹1cr | 5 positions")
    print("=" * 120)

    # Phase 1 — single filters (incl. the boolean toggles)
    singles = [row("BASELINE (no filter)", bt([], *FULL))]
    for label, flt in SINGLES.items():
        singles.append(row(label, bt(flt, *FULL)))
    singles_sorted = [singles[0]] + sorted(singles[1:], key=lambda x: x["sharpe"], reverse=True)
    table(singles_sorted, "PHASE 1 — SINGLE FILTERS (sorted by Sharpe)")

    # Phase 2 — multi-filter combos
    combos = []
    for label, flt in COMBOS.items():
        combos.append(row(label, bt(flt, *FULL)))
    combos_sorted = sorted(combos, key=lambda x: x["sharpe"], reverse=True)
    table(combos_sorted, "PHASE 2 — MULTI-FILTER COMBINED STRATEGIES (sorted by Sharpe)")

    # Best logic = highest-Sharpe combo (risk-adjusted)
    best_label = combos_sorted[0]["label"]
    best_filters = COMBOS[best_label]
    print(f"\n>>> BEST LOGIC (risk-adjusted): {best_label}  "
          f"[5Y ret {combos_sorted[0]['ret']:.1f}%  Sharpe {combos_sorted[0]['sharpe']:.2f}  "
          f"maxDD {combos_sorted[0]['dd']:.1f}%  PF {combos_sorted[0]['pf']:.2f}]")

    # Phase 3 — year-on-year on the best logic (each year independent, fresh capital)
    years = [
        ("2021 (Jun–Dec)", "2021-06-01", "2021-12-31", "OOS"),
        ("2022",           "2022-01-01", "2022-12-31", "OOS"),
        ("2023",           "2023-01-01", "2023-12-31", "in-sample*"),
        ("2024",           "2024-01-01", "2024-12-31", "in-sample*"),
        ("2025",           "2025-01-01", "2025-12-31", "OOS"),
        ("2026 (Jan–Jun)", "2026-01-01", "2026-06-01", "OOS"),
    ]
    print(f"\nPHASE 3 — YEAR-ON-YEAR · {best_label}")
    hdr = f"{'year':<16}{'tag':<12}{'trades':>7}{'ret%':>9}{'bmk%':>8}{'alpha%':>8}{'sharpe':>8}{'maxDD%':>8}{'win%':>7}{'exp%':>8}{'PF':>6}"
    print(hdr); print("-" * len(hdr))
    for name, frm, to, tag in years:
        r = bt(best_filters, frm, to)
        x = row(name, r)
        print(f"{name:<16}{tag:<12}{x['trades']:>7}{x['ret']:>9.2f}{x['bmk']:>8.2f}{x['alpha']:>8.2f}"
              f"{x['sharpe']:>8.2f}{x['dd']:>8.2f}{x['win']:>7.1f}{x['exp']:>8.3f}{x['pf']:>6.2f}")
        sys.stdout.flush()
    full = row("FULL 5Y compounded", bt(best_filters, *FULL))
    print("-" * len(hdr))
    print(f"{'FULL 5Y':<16}{'compounded':<12}{full['trades']:>7}{full['ret']:>9.2f}{full['bmk']:>8.2f}"
          f"{full['alpha']:>8.2f}{full['sharpe']:>8.2f}{full['dd']:>8.2f}{full['win']:>7.1f}{full['exp']:>8.3f}{full['pf']:>6.2f}")
    print("\n* numeric thresholds were derived on 2023-06..2024-12, so 2023-24 are in-sample for those ranges.")
    print("=" * 120)


if __name__ == "__main__":
    main()
