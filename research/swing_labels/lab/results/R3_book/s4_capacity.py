"""R3_book item 3: capacity tiers for the frozen book (E0 rules) with square-root impact.
impact/side = min(Y * vol_20 * sqrt(position / ADV20), 10%), Y in {0.5, 1.0}; ADV20 = 20-day median traded value
(panel turnover, Rs) over rows t-19..t in the same segment; position = AUM/80 per name (fixed rupees);
AUM tiers Rs 1, 5, 20, 50, 100 cr. Policies: (a) liq2 uncapped, (b) liq2 + 5%-of-ADV20 cap (excess stays in cash),
(c) liq5 universe, (d) liq5 + cap. Round-trip cost = 50 bps + 2 x impact. Idle cash earns the Nifty 1D Rate in every
capacity book (pre-declared). Random baselines (5 seeds) pay the same impact model on their own picks."""
import numpy as np
import pandas as pd

from bk_setup import setup, C, L, phase_runs, avg_series, pa_stats

T = setup(extra_feat=("vol_20", "elig_liq5"))
S, E, BS, prod, F, fw = T["S"], T["E"], T["BS"], T["prod"], T["F"], T["fw"]
n = S.n
turn = L.load_panel(["turnover"])["turnover"].values.astype("float64")
ie = np.flatnonzero(E)
Wm = np.full((len(ie), 20), np.nan, dtype=np.float64)
for k in range(20):
    j = ie - k
    ok = j >= fw.start[ie]
    Wm[ok, k] = turn[j[ok]]
adv = np.full(n, np.nan)
adv[ie] = np.nanmedian(Wm, axis=1)
del Wm, turn
sig = F["vol_20"].values.astype("float64")
liq5 = E & F["elig_liq5"].values.astype(bool)
C.log("ADV ready; median ADV elig (cr)", float(np.nanmedian(adv[ie]) / 1e7), "liq5 rows", int(liq5.sum()))

AUMS = {"1cr": 1e7, "5cr": 5e7, "20cr": 2e8, "50cr": 5e8, "100cr": 1e9}
POL = {"a_liq2": (E, False), "b_liq2_cap5": (E, True), "c_liq5": (liq5, False), "d_liq5_cap5": (liq5, True)}
SEEDS = (1, 2, 3, 4, 5)

# reference: EW universe (liq2, 50 bps, no impact; cached) and Nifty 500 price index on each window
n5 = L.market_series("Nifty 500")["close"].astype("float64")
n5.index = pd.DatetimeIndex(n5.index)
from bk_setup import frozen_baselines  # noqa: E402
ref = {}
for per in ("dev", "hold"):
    rds, eds = frozen_baselines(S, E, per, 50)
    common = eds[0].index
    for x in eds:
        common = common.intersection(x.index)
    em = pd.Series(np.mean([x.reindex(common).values for x in eds], 0), index=common)
    lv = n5.reindex(n5.index.union(common)).ffill().reindex(common)
    nm = lv.pct_change().fillna(0.0)
    ref[per] = {"ew_cagr": pa_stats(em)["pa_cagr"], "nifty500_cagr": pa_stats(nm)["pa_cagr"]}
C.log("refs", ref)


def book(mask, cost_row, fill, per):
    runs, rr = phase_runs(BS, prod, mask, per, dict(cost_row=cost_row, fill=fill, cash="1d"), seeds=SEEDS)
    sm = avg_series(runs)
    rser = [pd.Series(np.mean([x["_daily"] for x in r5], 0), index=pd.DatetimeIndex(r5[0]["_dates"])) for r5 in rr]
    rm = avg_series([{"_daily": s_.values, "_dates": s_.index.values} for s_ in rser])
    st = pa_stats(sm, rm)
    st["avg_names_held"] = float(np.mean([r["avg_names_held"] for r in runs]))
    return st


res = {"refs": ref, "policies": {}}
for pn, (mask, capped) in POL.items():
    res["policies"][pn] = {}
    for per in ("dev", "hold"):
        # zero-impact reference row (same cash convention)
        st0 = book(mask, np.full(n, 0.005), None, per)
        res["policies"][pn][f"zero_impact_{per}"] = st0
        C.log(pn, per, "zero-impact", C.short({k: st0[k] for k in ("pa_cagr", "pa_random_cagr", "pa_excess_ann", "pa_nw_t")}))
        for Y in (0.5, 1.0):
            for an, A in AUMS.items():
                Q = A / 80.0
                if capped:
                    fill = np.minimum(1.0, 0.05 * adv / Q)
                    fill = np.where(np.isfinite(fill), fill, 0.0)
                else:
                    fill = None
                q_eff = Q * (fill if fill is not None else 1.0)
                imp = np.minimum(Y * sig * np.sqrt(q_eff / adv), 0.10)
                imp = np.where(np.isfinite(imp), imp, 0.10)
                cost_row = 0.005 + 2 * imp
                st = book(mask, cost_row, fill, per)
                res["policies"][pn][f"Y{Y}_{an}_{per}"] = st
                C.log(pn, per, Y, an, C.short({k: st[k] for k in ("pa_cagr", "pa_random_cagr", "pa_excess_ann", "pa_nw_t",
                                                                  "pa_maxdd", "avg_names_held")}))
        C.save("item3_capacity", res)


# AUM at which absolute CAGR falls to the EW universe / Nifty 500 (log-linear interpolation between tiers)
def crossing(pn, Y, per, target):
    xs = np.log10([AUMS[a] / 1e7 for a in AUMS])
    ys = np.array([res["policies"][pn][f"Y{Y}_{a}_{per}"]["pa_cagr"] for a in AUMS])
    if ys[0] <= target:
        return "below_1cr"
    for i in range(len(ys) - 1):
        if ys[i] > target >= ys[i + 1]:
            f = (ys[i] - target) / (ys[i] - ys[i + 1])
            return float(10 ** (xs[i] + f * (xs[i + 1] - xs[i])))
    return "above_100cr"


cross = {}
for pn in POL:
    for Y in (0.5, 1.0):
        for per in ("dev", "hold"):
            cross[f"{pn}_Y{Y}_{per}"] = {"aum_cr_cagr_eq_EW": crossing(pn, Y, per, ref[per]["ew_cagr"]),
                                         "aum_cr_cagr_eq_Nifty500": crossing(pn, Y, per, ref[per]["nifty500_cagr"])}
res["crossings_aum_cr"] = cross
C.log("crossings", cross)

# participation / ADV of the actual picks (every trading day = all 5 phases), model vs random
part = {}
for per in ("dev", "hold"):
    a, b = C.PER[per]
    g0 = int(np.searchsorted(S.cal, np.datetime64(a)))
    g1 = int(np.searchsorted(S.cal, np.datetime64(b or "2026-10-14"), side="right")) - 22
    rows, rrows = [], []
    rng = np.random.default_rng(7)
    for g in range(g0, g1):
        cand = S.rows_on(g)
        cand = cand[E[cand] & np.isfinite(prod[cand])]
        rows.append(cand[np.argsort(-prod[cand], kind="stable")[:20]])
        rrows.append(rng.choice(cand, size=20, replace=False))
    rows, rrows = np.concatenate(rows), np.concatenate(rrows)
    pp = {"model_adv_cr_mean": float(adv[rows].mean() / 1e7), "model_adv_cr_median": float(np.median(adv[rows]) / 1e7),
          "model_adv_cr_p10": float(np.percentile(adv[rows], 10) / 1e7),
          "random_adv_cr_mean": float(adv[rrows].mean() / 1e7), "random_adv_cr_median": float(np.median(adv[rrows]) / 1e7),
          "model_vol20_median": float(np.median(sig[rows])), "random_vol20_median": float(np.median(sig[rrows])),
          "model_share_liq5": float(liq5[rows].mean())}
    for an, A in AUMS.items():
        Q = A / 80.0
        pr = Q / adv[rows]
        prr = Q / adv[rrows]
        pp[an] = {"position_lakh": Q / 1e5, "median_participation": float(np.median(pr)),
                  "p90_participation": float(np.percentile(pr, 90)), "share_gt5pct": float((pr > 0.05).mean()),
                  "share_gt10pct": float((pr > 0.10).mean()), "random_median_participation": float(np.median(prr)),
                  "fill_under_5pct_cap_mean": float(np.minimum(1.0, 0.05 / pr).mean()),
                  "impact_bps_side_Y1_mean": float(np.minimum(sig[rows] * np.sqrt(pr), 0.10).mean() * 1e4)}
    part[per] = pp
    C.log("participation", per, C.short(pp, 4))
res["participation"] = part
C.save("item3_capacity", res)
C.log("done")
