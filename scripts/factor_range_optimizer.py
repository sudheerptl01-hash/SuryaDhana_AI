#!/usr/bin/env python
"""
factor_range_optimizer.py — close the loop: Decile Profiler → best ranges → Backtest.

Methodology (data-snooping-safe):
  1. PROFILE each bias-free technical factor on an IN-SAMPLE window via
     POST /api/analytics/factor-profile. Identify the contiguous "outperforming
     tail" — the run of deciles (from the favourable extreme) whose forward win
     rate beats the universe base rate — and derive a one-sided threshold from the
     base-rate crossover edge. Direction is taken from the monotonicity sign.
  2. BACKTEST those thresholds on a DISJOINT OUT-OF-SAMPLE window via
     POST /api/analytics/backtest, so the thresholds never peek at the returns they
     are judged on. Baseline (no filter), each single factor, and a combined
     top-2-factor strategy are all run on the same OOS window for apples-to-apples.

MODE = PAPER. Friction is floored server-side to 15 bps regardless of payload.
Run:  /Users/sudheer/Desktop/jupyter_env/bin/python scripts/factor_range_optimizer.py
"""
from __future__ import annotations

import json
import urllib.request
from typing import Optional

BASE = "http://localhost:8010"

# Disjoint windows — thresholds are chosen on IS, judged on OOS.
IS_FROM, IS_TO = "2023-06-01", "2024-12-31"     # in-sample: discover ranges
OOS_FROM, OOS_TO = "2025-01-01", "2026-06-01"   # out-of-sample: evaluate

FORWARD_DAYS = 5
WIN_THRESHOLD = 0.0
CAPITAL = 10_000_000
MAX_POS = 5

# Bias-free technical factors only (fundamentals carry point-in-time look-ahead).
FACTORS = ["rsi_14", "atr_14_pct", "dist_ma200_pct", "above_52w_low_pct", "within_52w_high_pct"]


def _post(path: str, payload: dict, timeout: int = 240) -> dict:
    req = urllib.request.Request(
        f"{BASE}{path}", data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def profile(factor: str) -> dict:
    return _post("/api/analytics/factor-profile", {
        "factor": factor, "from_date": IS_FROM, "to_date": IS_TO,
        "forward_days": FORWARD_DAYS, "win_threshold": WIN_THRESHOLD,
        "friction_bps": 15.0, "scope": "universe", "n_deciles": 10,
    })


def derive_range(prof: dict) -> Optional[dict]:
    """
    From a decile profile, derive a one-sided 'outperforming tail' threshold.
    Returns {field, op, value, region, expected_rate, samples} or None.
    """
    deciles = prof.get("deciles", [])
    base = prof.get("global_base_rate", 0.0)
    total = max(prof.get("total_samples", 0), 1)
    rho = prof.get("monotonicity_spearman", 0.0)
    if len(deciles) < 3:
        return None
    min_samples = max(500, int(0.004 * total))   # ignore illiquid low-sample buckets
    low_better = rho <= 0                          # ↓factor → ↑win  (e.g. RSI oversold)

    ordered = sorted(deciles, key=lambda d: d["decile"], reverse=not low_better)
    # Walk from the favourable extreme, extend while the bucket beats the base rate.
    tail = []
    for d in ordered:
        if d["event_rate"] >= base and d["samples"] >= min_samples:
            tail.append(d)
        else:
            break
    if not tail:
        # Fall back to the single best sample-guarded decile.
        cand = [d for d in deciles if d["samples"] >= min_samples]
        if not cand:
            return None
        best = max(cand, key=lambda d: d["event_rate"])
        tail = [best]

    samples = sum(d["samples"] for d in tail)
    pos = sum(d["positives"] for d in tail)
    exp_rate = pos / samples * 100 if samples else 0.0
    if low_better:
        cut = max(d["hi"] for d in tail)
        op, lo, hi = "lte", min(d["obs_lo"] for d in tail), cut
    else:
        cut = min(d["lo"] for d in tail)
        op, lo, hi = "gte", cut, max(d["obs_hi"] for d in tail)
    return {
        "field": prof["factor"], "op": op, "value": round(cut, 4),
        "region": f"[{lo:.2f} → {hi:.2f}]", "expected_rate": round(exp_rate, 2),
        "base": round(base, 2), "lift": round(exp_rate - base, 2),
        "samples": samples, "rho": rho, "low_better": low_better,
    }


def backtest(filters: list[dict], label: str) -> dict:
    res = _post("/api/analytics/backtest", {
        "from_date": OOS_FROM, "to_date": OOS_TO, "forward_days": FORWARD_DAYS,
        "win_threshold": WIN_THRESHOLD, "filters": filters, "friction_bps": 15.0,
        "starting_capital": CAPITAL, "max_positions": MAX_POS, "stop_loss_pct": 2.0,
        "scope": "universe", "entry_timing": "next_open",
    })
    return {"label": label, **res}


def fmt_stats(r: dict) -> dict:
    return {
        "label": r["label"],
        "trades": r.get("total_trades", 0),
        "ret%": r.get("total_return_pct", 0.0),
        "bmk%": r.get("benchmark_total_return_pct", 0.0),
        "cagr%": r.get("cagr_pct", 0.0),
        "alpha%": r.get("alpha_annual_pct", 0.0),
        "beta": r.get("beta", 0.0),
        "sharpe": r.get("sharpe_ratio", 0.0),
        "sortino": r.get("sortino_ratio", 0.0),
        "maxDD%": r.get("max_drawdown", 0.0),
        "win%": r.get("win_rate", 0.0),
        "expectancy%": r.get("expectancy", 0.0),
        "PF": r.get("profit_factor", 0.0),
    }


def main() -> None:
    print("=" * 92)
    print("STEP 1 — PROFILE FACTORS (in-sample)   window:", IS_FROM, "→", IS_TO)
    print("=" * 92)
    ranges: list[dict] = []
    for f in FACTORS:
        try:
            prof = profile(f)
        except Exception as e:
            print(f"  {f:<22} profile failed: {e}")
            continue
        rng = derive_range(prof)
        if not rng:
            print(f"  {f:<22} no tradeable range (degenerate)")
            continue
        ranges.append(rng)
        arrow = "≤" if rng["op"] == "lte" else "≥"
        print(f"  {prof['factor_label']:<24} dir={'LOW' if rng['low_better'] else 'HIGH'}-is-better "
              f"ρ={rng['rho']:+.2f} | rule: {f} {arrow} {rng['value']:<8} "
              f"range {rng['region']:<22} | IS win {rng['expected_rate']:.1f}% vs base {rng['base']:.1f}% "
              f"(+{rng['lift']:.1f}) n={rng['samples']:,}")

    # Rank by in-sample lift; top-2 form the combined strategy.
    ranges.sort(key=lambda d: d["lift"], reverse=True)
    top2 = ranges[:2]

    print()
    print("=" * 92)
    print("STEP 2 — BACKTEST ON OUT-OF-SAMPLE   window:", OOS_FROM, "→", OOS_TO,
          "| SL -2% | friction 15bps | cap ₹1cr | 5 pos")
    print("=" * 92)

    runs: list[dict] = []
    runs.append(backtest([], "BASELINE (no filter)"))
    for rng in ranges:
        flt = [{"field": rng["field"], "op": rng["op"], "value": rng["value"]}]
        runs.append(backtest(flt, f"{rng['field']} {('≤' if rng['op']=='lte' else '≥')} {rng['value']}"))
    if len(top2) == 2:
        combo = [{"field": r["field"], "op": r["op"], "value": r["value"]} for r in top2]
        cl = " + ".join(f"{r['field']}{'≤' if r['op']=='lte' else '≥'}{r['value']}" for r in top2)
        runs.append(backtest(combo, f"COMBINED top-2: {cl}"))

    rows = [fmt_stats(r) for r in runs]
    cols = ["label", "trades", "ret%", "bmk%", "cagr%", "alpha%", "beta", "sharpe",
            "sortino", "maxDD%", "win%", "expectancy%", "PF"]
    widths = {c: max(len(c), *(len(f"{row[c]}") for row in rows)) for c in cols}
    widths["label"] = max(widths["label"], 34)

    print()
    header = " | ".join(c.rjust(widths[c]) if c != "label" else c.ljust(widths["label"]) for c in cols)
    print(header)
    print("-" * len(header))
    for row in rows:
        line = " | ".join(
            (f"{row[c]}").ljust(widths["label"]) if c == "label" else (f"{row[c]}").rjust(widths[c])
            for c in cols
        )
        print(line)

    # Verdict
    base = rows[0]
    best = max(rows[1:], key=lambda r: r["sharpe"]) if len(rows) > 1 else base
    print()
    print("=" * 92)
    print(f"VERDICT (vs BASELINE ret {base['ret%']}%, Sharpe {base['sharpe']}):")
    print(f"  Best risk-adjusted: '{best['label']}'  ret {best['ret%']}%  Sharpe {best['sharpe']}  "
          f"maxDD {best['maxDD%']}%  win {best['win%']}%  trades {best['trades']}")
    print("=" * 92)


if __name__ == "__main__":
    main()
