"""R3_book item 2b: decompose the X3 (executable carry) gain. Diagnostic baselines (not candidate strategies):
 * random top-20 with X3 timing (hold through the rebalance close, trade at the next open), 5 seeds x 5 phases,
   so the X3 excess can be measured against a timing-matched random book;
 * X3 - E1 (= overnight gap earned by the non-carried names that X3 sells at the next open instead of the close)
   and E1 - E0 (= cost saving + gap on carried names), by calendar year."""
import numpy as np
import pandas as pd

from bk_setup import setup, C, L, phase_runs, avg_series, frozen_baselines, pa_stats

T = setup()
S, E, BS, prod = T["S"], T["E"], T["BS"], T["prod"]
z = np.load(f"{C.OUT}/pa_series_item2.npz")


def ser(name, key):
    return pd.Series(z[f"{name}__{key}"], index=pd.DatetimeIndex(z[f"{name}__{key}__dates"]))


out = {}
for per in ("dev", "hold"):
    for cost in (50, 80):
        key = f"{per}_c{cost}"
        rds, eds = frozen_baselines(S, E, per, cost)
        _, rr = phase_runs(BS, prod, E, per, dict(carry="exec", cost_bps=cost), seeds=(1, 2, 3, 4, 5))
        # phase-average of the 5-seed mean random X3-timed books
        rx = [avg_series(r5) * 0 + np.mean([pd.Series(x["_daily"], index=pd.DatetimeIndex(x["_dates"])).values
                                            for x in r5], 0) for r5 in rr]
        rx_pa = avg_series([{"_daily": s.values, "_dates": s.index.values} for s in rx])
        x3, e0, e1 = ser("X3", key), ser("E0", key), ser("E1", key)
        common = x3.index.intersection(rx_pa.index)
        for s_ in rds:
            common = common.intersection(s_.index)
        r0 = pd.Series(np.mean([s_.reindex(common).values for s_ in rds], 0), index=common)
        rx_c = rx_pa.reindex(common)
        st = {"random_E0timing_cagr": pa_stats(r0)["pa_cagr"], "random_X3timing_cagr": pa_stats(rx_c)["pa_cagr"],
              "random_timing_gain": C.paired(rx_c, r0),
              "X3_excess_vs_timing_matched_random": C.paired(x3.reindex(common), rx_c),
              "E0_excess_vs_random": C.paired(e0.reindex(common), r0),
              "X3_minus_E1": C.paired(x3, e1), "E1_minus_E0": C.paired(e1, e0)}
        d1 = (x3 - e1).dropna()
        d2 = (e1 - e0).dropna()
        d3 = (rx_c - r0).dropna()
        st["by_year"] = {int(y): {"X3_minus_E1_ann": float(d1[d1.index.year == y].mean() * 252),
                                  "E1_minus_E0_ann": float(d2[d2.index.year == y].mean() * 252),
                                  "randomX3_minus_randomE0_ann": float(d3[d3.index.year == y].mean() * 252)}
                         for y in sorted(set(d1.index.year))}
        out[key] = st
        C.log(key, C.short({k: v for k, v in st.items() if k != "by_year"}), C.short(st["by_year"]))
C.save("item2b_x3_decomposition", out)
