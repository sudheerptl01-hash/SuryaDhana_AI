"""R3_book item 2: exit / hold / sizing add-ons vs the frozen baseline E0 (phase-averaged, DEV select, 2026 report).
Pre-declared: E0, E1 carry, E2w, E2d, E3, S1; extras X1 (E0 with idle cash at Nifty 1D Rate) and X2 (conditional:
E1 + better early-exit rule, only if both pass the adoption rule on DEV)."""
import numpy as np
import pandas as pd

from bk_setup import setup, C, L, phase_runs, avg_series, frozen_baselines, pa_stats, turnover_summary

T = setup()
S, E, BS, prod = T["S"], T["E"], T["BS"], T["prod"]
VARS = {
    "E0": dict(),
    "X1": dict(cash="1d"),
    "E1": dict(carry=True),
    "E2w": dict(exit_rule="e2w", cash="1d"),
    "E2d": dict(exit_rule="e2d", cash="1d"),
    "E3": dict(exit_rule="e3", cash="1d"),
    "S1": dict(sizing="invvol"),
    "X3": dict(carry="exec"),
}
# daily cash (Nifty 1D Rate) and EW series for beta-adjusting paired differences
cl = pd.Series(T["cash_level"], index=pd.DatetimeIndex(S.cal))
cash_d = cl.pct_change().fillna(0.0)

res, ser, base = {}, {}, {}


def run_variant(name, kw):
    res[name] = {}
    for per in ("dev", "hold"):
        for cost in (50, 80):
            key = f"{per}_c{cost}"
            if (per, cost) not in base:
                rds, eds = frozen_baselines(S, E, per, cost)
                base[(per, cost)] = (rds, eds)
            rds, eds = base[(per, cost)]
            runs, _ = phase_runs(BS, prod, E, per, dict(kw, cost_bps=cost))
            sm = avg_series(runs)
            common = sm.index
            for x in rds + eds:
                common = common.intersection(x.index)
            rm = pd.Series(np.mean([x.reindex(common).values for x in rds], 0), index=common)
            em = pd.Series(np.mean([x.reindex(common).values for x in eds], 0), index=common)
            sm = sm.reindex(common)
            st = pa_stats(sm, rm, em)
            st["turnover"] = turnover_summary(runs)
            st["avg_names_held"] = float(np.mean([r["avg_names_held"] for r in runs]))
            st["exposure_approx"] = st["avg_names_held"] / 80.0
            st["mean_trade_net"] = float(np.mean([r["mean_trade_net"] for r in runs]))
            st["hit_rate"] = float(np.mean([r["hit_rate"] for r in runs]))
            npos = float(np.mean([r["n_positions"] for r in runs]))
            st["early_exit_share"] = float(np.mean([r["n_early_exits"] for r in runs])) / npos
            st["carried_share"] = float(np.mean([r["n_carried"] for r in runs])) / npos
            st["check_obs_without_prod"] = float(np.mean([r["n_check_nan_held"] for r in runs]))
            st["phase_cagr"] = [r["cagr"] for r in runs]
            tr_ = [r["trim"] for r in runs]
            cn = float(np.mean([t_["carried_notional"] for t_ in tr_]))
            st["carry_trim_over_carried_notional"] = float(np.mean([t_["trim"] for t_ in tr_])) / cn if cn > 0 else None
            st["carry_uncharged_trim_cost_per_yr"] = float(np.mean([t_["trim"] for t_ in tr_])) * cost / 2e4 / (len(sm) / 252) if cn > 0 else None
            st["legacy_sold_per_phase"] = float(np.mean([t_["legacy_sold"] for t_ in tr_]))
            # by-year
            df = pd.DataFrame({"s": sm.values, "r": rm.values, "e": em.values}, index=common)
            st["by_year"] = {int(y): {"strat": float(np.prod(1 + g.s) - 1), "ex_vs_random_ann": float((g.s - g.r).mean() * 252)}
                             for y, g in df.groupby(df.index.year)}
            ser[(name, key)] = sm
            if name != "E0":
                b0 = ser[("E0", key)]
                pr = C.paired(sm, b0)
                st["paired_vs_E0"] = pr
                st["delta_maxdd_vs_E0"] = st["pa_maxdd"] - res["E0"][key]["pa_maxdd"]
                st["delta_cagr_vs_E0"] = st["pa_cagr"] - res["E0"][key]["pa_cagr"]
                c2 = sm.index.intersection(b0.index)
                dd = sm.reindex(c2) - b0.reindex(c2)
                st["paired_vs_E0_by_year"] = {int(y): float(g.mean() * 252) for y, g in dd.groupby(dd.index.year)}
                # beta-adjusted paired difference: regress diff on (EW - cash); alpha t (NW) of the residual mean
                x = (em.reindex(c2) - cash_d.reindex(c2).fillna(0.0)).values
                y = dd.values
                bb = np.polyfit(x, y, 1)[0]
                st["paired_vs_E0_beta_to_EW"] = float(bb)
                st["paired_vs_E0_beta_adj_alpha_ann"] = float((y - bb * x).mean() * 252)
                st["paired_vs_E0_beta_adj_alpha_t"] = L.nw_t(y - bb * x, lag=20)
                if name in ("E2w", "E2d", "E3", "X2"):
                    bx = ser[("X1", key)]
                    st["paired_vs_X1"] = C.paired(sm, bx)
                    st["delta_maxdd_vs_X1"] = st["pa_maxdd"] - res["X1"][key]["pa_maxdd"]
            res[name][key] = st
            C.log(name, key, C.short({k: st.get(k) for k in ("pa_cagr", "pa_excess_ann", "pa_nw_t", "pa_maxdd")}),
                  "paired", C.short(st.get("paired_vs_E0")), "vsX1", C.short(st.get("paired_vs_X1")),
                  "turn", C.short(st["turnover"], 3), "early", round(st["early_exit_share"], 4),
                  "carry", round(st["carried_share"], 4))


for nm, kw in VARS.items():
    run_variant(nm, kw)
    C.save("item2_exits", res)


def passes(nm):
    st = res[nm]["dev_c50"]
    ok = st["paired_vs_E0"]["nw_t"] >= 2 and st["delta_maxdd_vs_E0"] >= -0.03
    if "paired_vs_X1" in st:
        ok = ok and st["paired_vs_X1"]["nw_t"] >= 2 and st["delta_maxdd_vs_X1"] >= -0.03
    return bool(ok)


adopt = {nm: passes(nm) for nm in VARS if nm not in ("E0", "X1")}
res["adoption_rule_dev_c50"] = adopt
C.log("adoption", adopt)
best_e2 = max(("E2w", "E2d"), key=lambda n: res[n]["dev_c50"]["paired_vs_E0"]["nw_t"])
if adopt["E1"] and adopt[best_e2]:
    kw = dict(VARS[best_e2], carry=True)
    run_variant("X2", kw)
    res["X2_definition"] = f"E1 carry + {best_e2}"
    res["adoption_rule_dev_c50"]["X2"] = passes("X2")
else:
    res["X2_definition"] = f"not run: E1 pass={adopt['E1']}, best early-exit rule {best_e2} pass={adopt[best_e2]}"
C.save("item2_exits", res)
np.savez_compressed(f"{C.OUT}/pa_series_item2.npz",
                    **{f"{a}__{b}": v.values for (a, b), v in ser.items()},
                    **{f"{a}__{b}__dates": v.index.values.astype("datetime64[D]").astype(str) for (a, b), v in ser.items()})
C.log("done")
