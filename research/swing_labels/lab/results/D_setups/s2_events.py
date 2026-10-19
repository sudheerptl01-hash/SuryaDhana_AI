"""Stage 2: per-setup event study on the common barrier label (no model).

For every setup: frequency, NaN share, class shares vs base (lift), touch mix, net expectancy
(50/80 bps), DATE-MATCHED excess (event minus same-date universe mean -> removes market timing),
by year / regime / liquidity tercile, monthly stability + corr with market, fresh-event variant,
month-block bootstrap on the 2023-2025 dev window, Jaccard overlap.
"""
import numpy as np
import pandas as pd

from common import L, OUT, DEV_END, LONG_SETUPS, SHORT_SETUPS, load_base, save, T

t = T()
B = load_base()
names = list(B["setup_names"])
U = B["U"]
day = B["day"].astype("datetime64[D]")
seg = B["seg"]
start, _ = L._start_end(seg)
REG = {0: "bull_up20", 1: "bull_dn20", 2: "bear_up20", 3: "bear_dn20"}
rng = np.random.default_rng(7)
NB = 2000

# Nifty 500 monthly return for regime-dependence
mk = L.market_series("Nifty 500")["close"]
mret = mk.resample("ME").last().pct_change()
mret.index = mret.index.to_period("M").astype(str)


def fresh_mask(sm):
    """Setup fires today and did NOT fire on any of the previous 10 rows of the same segment."""
    prev = L.roll(sm.astype(float), 10, start, "sum", minp=1, exclusive=True)
    return sm & ~(np.nan_to_num(prev, nan=0.0) > 0)


def frame(side):
    s = side[0].upper()
    lab = B[f"lab_{s}"].astype("float64")
    ok = U & ~np.isnan(lab)
    idx = np.flatnonzero(ok)
    d = pd.DataFrame({"i": idx, "day": day[idx], "lab": lab[idx], "ret": B[f"ret_{s}"][idx].astype("float64"),
                      "touch": B[f"touch_{s}"][idx], "k": B[f"k_{s}"][idx], "reg": B["reg"][idx],
                      "liq": B["liq"][idx], "fno": B["fno"][idx]})
    d["pos"] = (d.lab == 1).astype(float)
    d["neg"] = (d.lab == -1).astype(float)
    d["year"] = pd.DatetimeIndex(d.day).year
    d["month"] = pd.DatetimeIndex(d.day).to_period("M").astype(str)
    for c in ("ret", "pos", "neg"):
        d[f"x_{c}"] = d[c] - d.groupby("day")[c].transform("mean")
    # fno-only date means (for short side realism)
    return d


def boot(sub, col):
    """Month-block bootstrap of the event-weighted mean of `col` (dev window)."""
    g = sub.groupby("month")[col].agg(["sum", "count"])
    if len(g) < 6:
        return {"mean": None, "lo95": None, "hi95": None, "p_le0": None, "t": None, "months": int(len(g))}
    sm, ct = g["sum"].values, g["count"].values
    ii = rng.integers(0, len(g), size=(NB, len(g)))
    bs = sm[ii].sum(1) / np.maximum(ct[ii].sum(1), 1)
    m = sm.sum() / ct.sum()
    return {"mean": m, "lo95": float(np.percentile(bs, 2.5)), "hi95": float(np.percentile(bs, 97.5)),
            "p_le0": float((bs <= 0).mean()), "t": float(m / bs.std()) if bs.std() > 0 else None,
            "months": int(len(g))}


def stats(sub, base, ndays):
    if len(sub) == 0:
        return {"n": 0}
    r = {"n": int(len(sub)), "events_per_day": len(sub) / max(ndays, 1),
         "P+1": sub.pos.mean(), "P0": 1 - sub.pos.mean() - sub.neg.mean(), "P-1": sub.neg.mean(),
         "base_P+1": base.pos.mean(), "lift_P+1": sub.pos.mean() / base.pos.mean(),
         "lift_P-1": sub.neg.mean() / base.neg.mean(),
         "touch_pt": (sub.touch == 1).mean(), "touch_sl": (sub.touch == -1).mean(),
         "touch_time": (sub.touch == 0).mean(), "mean_k": float(sub.k.mean()),
         "gross_bps": 1e4 * sub.ret.mean(), "net50_bps": 1e4 * (sub.ret.mean() - 0.005),
         "net80_bps": 1e4 * (sub.ret.mean() - 0.008), "median_net50_bps": 1e4 * (sub.ret.median() - 0.005),
         "base_net50_bps": 1e4 * (base.ret.mean() - 0.005),
         "xs_excess_ret_bps": 1e4 * sub.x_ret.mean(), "xs_excess_P+1": sub.x_pos.mean(),
         "xs_excess_P-1": sub.x_neg.mean(), "hit_net50": float((sub.ret > 0.005).mean())}
    return r


def setup_report(d, sm_rows, all_rows_count_by_year, ndays_by_year, side):
    """d: frame of valid U rows; sm_rows: bool over d rows (setup fires)."""
    sub = d[sm_rows]
    rep = {}
    per = {"all": np.ones(len(d), bool),
           "dev_2023_2025": (d.day >= np.datetime64("2023-01-01")) & (d.day <= np.datetime64(DEV_END)),
           "hold_2026": d.day >= np.datetime64("2026-01-01")}
    for pn, pm in per.items():
        pm = np.asarray(pm)
        nd = d.loc[pm, "day"].nunique()
        rep[pn] = stats(d[pm & sm_rows], d[pm], nd)
        rep[pn]["share_of_U_rows"] = float((pm & sm_rows).sum() / max(pm.sum(), 1))
    rep["by_year"] = {}
    for y, gy in d.groupby("year"):
        m = sm_rows[d.year.values == y]
        sy = gy[m]
        rep["by_year"][int(y)] = stats(sy, gy, gy.day.nunique())
        rep["by_year"][int(y)]["share_of_U_rows"] = float(m.mean())
    rep["by_regime"] = {}
    for rc, rn in REG.items():
        mreg = d.reg.values == rc
        st = stats(d[sm_rows & mreg], d[mreg], d[mreg].day.nunique())
        st["share_of_events"] = float((sm_rows & mreg).sum() / max(sm_rows.sum(), 1))
        st["share_of_base"] = float(mreg.mean())
        rep["by_regime"][rn] = st
    rep["by_liq_tercile"] = {}
    for lt in (0, 1, 2):
        ml = d.liq.values == lt
        rep["by_liq_tercile"][lt] = stats(d[sm_rows & ml], d[ml], d[ml].day.nunique())
    # monthly stability of P(+1) and corr with market
    mon = sub.groupby("month").pos.mean()
    mon_n = sub.groupby("month").size()
    mon = mon[mon_n >= 20]
    j = pd.concat([mon, mret], axis=1, join="inner").dropna()
    monx = sub.groupby("month").x_ret.mean()[mon_n >= 20]
    rep["monthly_pos"] = {"months": int(len(mon)), "mean": mon.mean(), "std": mon.std(), "min": mon.min(),
                          "max": mon.max(), "corr_vs_mkt_ret": float(j.iloc[:, 0].corr(j.iloc[:, 1])) if len(j) > 5 else None,
                          "share_months_xs_excess_gt0": float((monx > 0).mean()) if len(monx) else None}
    dev = sub[(sub.day >= np.datetime64("2023-01-01")) & (sub.day <= np.datetime64(DEV_END))]
    hold = sub[sub.day >= np.datetime64("2026-01-01")]
    rep["boot_dev"] = {"xs_excess_ret": boot(dev, "x_ret"), "xs_excess_pos": boot(dev, "x_pos"),
                       "net50": boot(dev.assign(net=dev.ret - 0.005), "net")}
    rep["boot_hold"] = {"xs_excess_ret": boot(hold, "x_ret"),
                        "net50": boot(hold.assign(net=hold.ret - 0.005), "net")}
    return rep


res = {}
summary_rows = []
for side, setdict in (("long", LONG_SETUPS), ("short", SHORT_SETUPS)):
    d = frame(side)
    t(f"frame {side} {len(d)}")
    di = d.i.values
    base_info = {}
    for pn, pm in {"all": np.ones(len(d), bool),
                   "dev_2023_2025": ((d.day >= np.datetime64("2023-01-01")) & (d.day <= np.datetime64(DEV_END))).values,
                   "hold_2026": (d.day >= np.datetime64("2026-01-01")).values}.items():
        base_info[pn] = stats(d[pm], d[pm], d[pm].day.nunique())
    base_info["by_year"] = {int(y): stats(g, g, g.day.nunique()) for y, g in d.groupby("year")}
    base_info["by_regime"] = {REG[rc]: stats(g, g, g.day.nunique()) for rc, g in d.groupby("reg") if rc in REG}
    mon = d.groupby("month").pos.mean()
    j = pd.concat([mon, mret], axis=1, join="inner").dropna()
    base_info["monthly_pos"] = {"mean": mon.mean(), "std": mon.std(), "min": mon.min(), "max": mon.max(),
                                "corr_vs_mkt_ret": float(j.iloc[:, 0].corr(j.iloc[:, 1]))}
    res[f"base_{side}"] = base_info
    sides = [(side, d)]
    if side == "short":
        dfno = d[d.fno.values].reset_index(drop=True)
        # recompute date-matched excess within the F&O-proxy universe
        for c in ("ret", "pos", "neg"):
            dfno[f"x_{c}"] = dfno[c] - dfno.groupby("day")[c].transform("mean")
        sides.append(("short_fno", dfno))
    for sname, dd in sides:
        ddi = dd.i.values
        for k in setdict:
            j_ = names.index(k)
            smf = B["setups"][:, j_]
            for variant, smask in (("all", smf), ("fresh", fresh_mask(smf))):
                rows = smask[ddi]
                rep = setup_report(dd, rows, None, None, sname)
                rep["nan_share_of_setup_rows"] = float(np.isnan(B[f"lab_{side[0].upper()}"][smf & U]).mean())
                key = f"{sname}|{k}|{variant}"
                res[key] = rep
                dv = rep["dev_2023_2025"]
                bd = rep["boot_dev"]["xs_excess_ret"]
                yrs = rep["by_year"]
                summary_rows.append({
                    "side": sname, "setup": k, "variant": variant, "n_all": rep["all"]["n"],
                    "share_U": rep["all"]["share_of_U_rows"], "ev_per_day": rep["all"]["events_per_day"],
                    "dev_n": dv["n"], "dev_P+1": dv.get("P+1"), "dev_base_P+1": dv.get("base_P+1"),
                    "dev_lift": dv.get("lift_P+1"), "dev_net50": dv.get("net50_bps"),
                    "dev_base_net50": dv.get("base_net50_bps"), "dev_xs_bps": dv.get("xs_excess_ret_bps"),
                    "dev_xs_t": bd["t"], "dev_xs_p": bd["p_le0"],
                    "xs_2023": yrs.get(2023, {}).get("xs_excess_ret_bps"),
                    "xs_2024": yrs.get(2024, {}).get("xs_excess_ret_bps"),
                    "xs_2025": yrs.get(2025, {}).get("xs_excess_ret_bps"),
                    "hold_n": rep["hold_2026"]["n"], "hold_net50": rep["hold_2026"].get("net50_bps"),
                    "hold_xs_bps": rep["hold_2026"].get("xs_excess_ret_bps"),
                    "hold_lift": rep["hold_2026"].get("lift_P+1"),
                    "mon_std": rep["monthly_pos"]["std"], "mon_corr_mkt": rep["monthly_pos"]["corr_vs_mkt_ret"],
                    "bull_share_events": rep["by_regime"]["bull_up20"]["share_of_events"]
                    + rep["by_regime"]["bull_dn20"]["share_of_events"],
                })
            t(f"{sname} {k}")
    # long-side "avoid" view of short setups: long-label stats on short-setup rows
    if side == "long":
        dlong = d
        for k in SHORT_SETUPS:
            j_ = names.index(k)
            rows = B["setups"][:, j_][dlong.i.values]
            rep = setup_report(dlong, rows, None, None, "long_avoid")
            res[f"long_avoid|{k}|all"] = rep
            dv = rep["dev_2023_2025"]
            summary_rows.append({"side": "long_avoid", "setup": k, "variant": "all", "n_all": rep["all"]["n"],
                                 "share_U": rep["all"]["share_of_U_rows"], "ev_per_day": rep["all"]["events_per_day"],
                                 "dev_n": dv["n"], "dev_P+1": dv.get("P+1"), "dev_base_P+1": dv.get("base_P+1"),
                                 "dev_lift": dv.get("lift_P+1"), "dev_net50": dv.get("net50_bps"),
                                 "dev_base_net50": dv.get("base_net50_bps"), "dev_xs_bps": dv.get("xs_excess_ret_bps"),
                                 "dev_xs_t": rep["boot_dev"]["xs_excess_ret"]["t"],
                                 "dev_xs_p": rep["boot_dev"]["xs_excess_ret"]["p_le0"],
                                 "xs_2023": rep["by_year"].get(2023, {}).get("xs_excess_ret_bps"),
                                 "xs_2024": rep["by_year"].get(2024, {}).get("xs_excess_ret_bps"),
                                 "xs_2025": rep["by_year"].get(2025, {}).get("xs_excess_ret_bps"),
                                 "hold_n": rep["hold_2026"]["n"], "hold_net50": rep["hold_2026"].get("net50_bps"),
                                 "hold_xs_bps": rep["hold_2026"].get("xs_excess_ret_bps"),
                                 "hold_lift": rep["hold_2026"].get("lift_P+1"),
                                 "mon_std": rep["monthly_pos"]["std"], "mon_corr_mkt": rep["monthly_pos"]["corr_vs_mkt_ret"],
                                 "bull_share_events": None})
            t(f"avoid {k}")

# Jaccard overlap on U rows
SMU = B["setups"][U]
J = np.zeros((len(names), len(names)))
C = np.zeros((len(names), len(names)))
for a in range(len(names)):
    A = SMU[:, a]
    for b in range(len(names)):
        Bm = SMU[:, b]
        inter = (A & Bm).sum()
        J[a, b] = inter / max((A | Bm).sum(), 1)
        C[a, b] = inter / max(A.sum(), 1)  # P(b | a)
res["jaccard"] = {"names": names, "J": J.round(4), "cond_P_b_given_a": C.round(4)}
summ = pd.DataFrame(summary_rows)
summ.to_csv(f"{OUT}/s2_summary.csv", index=False)
res["summary"] = summ.to_dict(orient="records")
save("s2_events", res)
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
print(summ[["side", "setup", "variant", "n_all", "share_U", "ev_per_day", "dev_n", "dev_P+1", "dev_base_P+1",
            "dev_lift", "dev_net50", "dev_base_net50", "dev_xs_bps", "dev_xs_t", "xs_2023", "xs_2024", "xs_2025",
            "hold_net50", "hold_xs_bps", "mon_corr_mkt", "bull_share_events"]].round(3).to_string())
t("done")
