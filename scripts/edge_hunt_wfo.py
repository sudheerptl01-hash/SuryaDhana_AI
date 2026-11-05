"""Out-of-sample edge hunt — run WFO across diverse strategy families at scale (₹10M,
G4 impact ON) and keep only what survives walk-forward. A strategy is only interesting
if its STITCHED OOS return is positive AND its Deflated Sharpe clears the multiple-
testing haircut. Everything else is in-sample curve-fit. Honest by construction."""
import os, sys, time, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "ui-api"))
os.environ.setdefault("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "data", "market.duckdb"))

import routers.analytics as an  # noqa: E402

FC = an.FilterCondition

def fc(field, op, value):
    return FC(field=field, op=op, value=value)

# Candidate pools per strategy family (WFO selects the best combo per window).
FAMILIES = {
    "micro (VMI/VIPT/Intention/VolThrust)": [
        fc("vmi_ratio", "gte", 1.0), fc("vipt_breakout", "gte", 1),
        fc("intraday_intention", "gte", 0.8), fc("vol_zscore_20", "gte", 2.0)],
    "momentum/trend (MA200/golden/dist/52wHigh)": [
        fc("price_gt_ma200", "gte", 1), fc("ma50_gt_ma200", "gte", 1),
        fc("dist_ma200_pct", "gt", 0.0), fc("within_52w_high_pct", "lte", 10.0)],
    "mean-reversion (RSI/52wLow/pullback)": [
        fc("rsi_14", "lt", 35.0), fc("above_52w_low_pct", "lte", 20.0),
        fc("intention_pullback", "gte", 1)],
    "squeeze/vol-breakout (squeeze/VIPT/thrust)": [
        fc("squeeze_on", "gte", 1), fc("vipt_breakout", "gte", 1),
        fc("vol_zscore_20", "gte", 2.0)],
    "sector RS (regime/sectorMom/decouple)": [
        fc("sector_positive_regime", "gte", 1), fc("sector_rel_mom_14_pct", "gt", 0.0),
        fc("decoupled_leader", "gte", 1)],
    "trend+micro (MA200/VMI/Intention)": [
        fc("price_gt_ma200", "gte", 1), fc("vmi_ratio", "gte", 1.0),
        fc("intraday_intention", "gte", 0.8)],
}

# Two risk profiles: RAW (just the participation cap that makes impact survivable) and
# SAFE (full de-grossing stack). Both at ₹10M with impact auto-on.
PROFILES = {
    "raw":  dict(max_participation_pct=5.0),
    "safe": dict(max_participation_pct=2.0, vol_target_pct=2.0, max_position_pct=12.0,
                 max_sector_pct=35.0, regime_filter=True, regime_model="hmm", regime_mode="soft"),
}

BASE = dict(from_date="2021-06-01", to_date="2026-06-01", forward_days=5, win_threshold=0.0,
            max_stocks_per_day=50, starting_capital=10_000_000.0, friction_bps=15.0,
            max_positions=5, scope="universe", entry_timing="next_open",
            in_sample_days=252, out_sample_days=63, max_combo_size=3, monte_carlo_runs=100)

results = []
print("EDGE HUNT — WFO out-of-sample, ₹10M, impact ON", flush=True)
print("=" * 96, flush=True)
for fam, pool in FAMILIES.items():
    for prof_name, knobs in PROFILES.items():
        t0 = time.time()
        try:
            req = an.WFOBacktestRequest(candidate_filters=pool, **BASE, **knobs)
            r = an._core_wfo(req)
            wf = r.get("walk_forward", {})
            row = dict(family=fam, profile=prof_name,
                       oos_ret=r.get("total_return_pct"), oos_sharpe=r.get("sharpe_ratio"),
                       maxdd=r.get("max_drawdown"), dsr=wf.get("deflated_sharpe"),
                       n_win=wf.get("n_windows"), secs=round(time.time() - t0, 1))
            results.append(row)
            print(f"[{row['secs']:5.1f}s] {prof_name:4} | {fam[:44]:44} "
                  f"OOS={row['oos_ret']}% Sharpe={row['oos_sharpe']} DD={row['maxdd']}% "
                  f"DSR={row['dsr']} win={row['n_win']}", flush=True)
        except Exception as e:
            print(f"[ERR ] {prof_name:4} | {fam[:44]:44} -> {str(e)[:70]}", flush=True)

print("=" * 96, flush=True)
# Survivors: positive OOS return, ranked; flag DSR-significant ones.
survivors = sorted([x for x in results if (x["oos_ret"] or -99) > 0],
                   key=lambda x: x["oos_ret"], reverse=True)
print(f"\nSURVIVORS (positive OOS return): {len(survivors)} of {len(results)}", flush=True)
for s in survivors:
    verdict = "✅ DSR-significant" if (s["dsr"] or 0) >= 0.95 else "⚠️ DSR weak (likely luck)"
    print(f"  {s['oos_ret']:+6.1f}%  Sharpe {s['oos_sharpe']}  DD {s['maxdd']}%  "
          f"DSR {s['dsr']}  [{s['profile']}] {s['family']}  {verdict}", flush=True)
print("\nHUNT_DONE", flush=True)
json.dump(results, open(os.path.join(os.path.dirname(__file__), "..", "edge_hunt_results.json"), "w"), indent=2)
