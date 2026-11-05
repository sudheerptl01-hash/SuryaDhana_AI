"""Post-remediation WFO re-score — A/B the full institutional stack against the naive
allocation path at scale (₹10Cr, impact auto-on). Honest out-of-sample numbers: a fix is
only real if the STITCHED OOS metrics improve risk-adjusted, not just in-sample."""
import os, sys, time, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "ui-api"))
os.environ.setdefault("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "market.duckdb"))

import routers.analytics as an  # noqa: E402
FC = an.FilterCondition
def fc(field, op, value): return FC(field=field, op=op, value=value)

FAMILIES = {
    "trend/momentum (MA200/golden/dist)": [
        fc("price_gt_ma200", "gte", 1), fc("ma50_gt_ma200", "gte", 1),
        fc("dist_ma200_pct", "gt", 0.0)],
    "mean-reversion (RSI<35/52wLow/pullback)": [
        fc("rsi_14", "lt", 35.0), fc("above_52w_low_pct", "lte", 20.0),
        fc("intention_pullback", "gte", 1)],
}

# ₹10Cr = 100,000,000. Impact auto-enables at this scale (C1/C2/C3 stack).
BASE = dict(from_date="2021-06-01", to_date="2026-06-01", forward_days=5, win_threshold=0.0,
            max_stocks_per_day=50, starting_capital=100_000_000.0, friction_bps=15.0,
            max_positions=5, scope="universe", entry_timing="next_open",
            in_sample_days=252, out_sample_days=63, max_combo_size=3, monte_carlo_runs=100,
            max_participation_pct=10.0)  # explicit ADV cap (auto would also fire at scale)

CONFIGS = {
    "A naive (equal-wt, no gate)": dict(sizing_mode="equal", regime_filter=False, kelly_fraction=None),
    "B full stack (volTgt+½Kelly+HMM gate)": dict(
        sizing_mode="vol_target", vol_target_pct=2.0, kelly_fraction=0.5,
        regime_filter=True, regime_model="hmm", regime_mode="soft"),
}

def run(pool, knobs):
    for attempt in range(4):
        try:
            req = an.WFOBacktestRequest(candidate_filters=pool, **BASE, **knobs)
            r = an._core_wfo(req); wf = r.get("walk_forward", {})
            return dict(oos=r.get("total_return_pct"), sharpe=r.get("sharpe_ratio"),
                        dd=r.get("max_drawdown"), dsr=wf.get("deflated_sharpe"),
                        n=wf.get("n_windows"))
        except Exception as e:
            if "busy" in str(e).lower() and attempt < 3:
                time.sleep(2.0); continue
            return dict(err=str(e)[:90])

print("POST-REMEDIATION WFO RE-SCORE — ₹10Cr, impact auto-ON, OOS stitched", flush=True)
print("=" * 100, flush=True)
rows = []
for fam, pool in FAMILIES.items():
    print(f"\n### {fam}", flush=True)
    for cfg_name, knobs in CONFIGS.items():
        t0 = time.time(); m = run(pool, knobs); secs = time.time() - t0
        if "err" in m:
            print(f"  [{secs:5.1f}s] {cfg_name:40} ERR {m['err']}", flush=True)
        else:
            print(f"  [{secs:5.1f}s] {cfg_name:40} OOS={m['oos']:>8}%  Sharpe={m['sharpe']:>6}  "
                  f"MaxDD={m['dd']:>7}%  DSR={m['dsr']}  win={m['n']}", flush=True)
            rows.append(dict(family=fam, config=cfg_name, **m))
print("\n" + "=" * 100, flush=True)
json.dump(rows, open(os.path.join(os.path.dirname(__file__), "..", "wfo_rescore_results.json"), "w"), indent=2)
print("RESCORE_DONE", flush=True)
