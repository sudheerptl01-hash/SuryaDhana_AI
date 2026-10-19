"""Stage 3: 'both conditions accept' -- conjunctions of setups (+ regime filters).

Long side only (label = long barrier). Building blocks are pre-registered:
  L1..L9 (L8 leaky sector leader excluded; its leak-free analogue L8b kept)
  R1 = S1_bd20 taken LONG (capitulation/breakdown reversal), R3 = S3_rslag taken LONG
  (both were measured as 'long_avoid' in s2 and turned out to be buy signals).
Regime filters: none / bull (mkt_dist_sma200>0) / mkt_dn20 (mkt_mom20<0).
For each config: dev (2023-01-01..DEV_END) n, P(+1), lift, net50, date-matched excess (bps) with
month-block bootstrap t/p; per-year excess; 2026 holdout reported but NEVER used for selection.
Also: sector-leak demonstration (L8b split by sector-known vs sector-NA).
"""
import itertools

import numpy as np
import pandas as pd

from common import L, OUT, DEV_END, load_base, save, T

t = T()
B = load_base()
names = list(B["setup_names"])
U = B["U"]
lab = B["lab_L"].astype("float64")
ok = U & ~np.isnan(lab)
idx = np.flatnonzero(ok)
day = B["day"][idx].astype("datetime64[D]")
ret = B["ret_L"][idx].astype("float64")
pos = (lab[idx] == 1).astype(float)
dfd = pd.DataFrame({"d": day, "ret": ret, "pos": pos})
x_ret = ret - dfd.groupby("d").ret.transform("mean").values
x_pos = pos - dfd.groupby("d").pos.transform("mean").values
mdist = B["mkt_dist_sma200"][idx]
mm20 = B["mkt_mom20"][idx]
year = pd.DatetimeIndex(day).year.values
month_code = pd.factorize(pd.DatetimeIndex(day).to_period("M"))[0]
dev = (day >= np.datetime64("2023-01-01")) & (day <= np.datetime64(DEV_END))
hold = day >= np.datetime64("2026-01-01")
SM = B["setups"][idx]
blk = {
    "L1": SM[:, names.index("L1_bo20")], "L2": SM[:, names.index("L2_bo52")],
    "L3": SM[:, names.index("L3_pullback")], "L4": SM[:, names.index("L4_vcp")],
    "L5": SM[:, names.index("L5_deliv")], "L6": SM[:, names.index("L6_rslead")],
    "L7": SM[:, names.index("L7_oversold_up")], "L8b": SM[:, names.index("L8b_mktlead")],
    "L9": SM[:, names.index("L9_gaphold")], "R1": SM[:, names.index("S1_bd20")],
    "R3": SM[:, names.index("S3_rslag")],
}
filters = {"none": np.ones(len(idx), bool), "bull": mdist > 0, "mkt_dn20": mm20 < 0}
rng = np.random.default_rng(11)
NB = 2000
M = month_code.max() + 1
dev_months = np.unique(month_code[dev])
hold_months = np.unique(month_code[hold])
BI_dev = rng.integers(0, len(dev_months), size=(NB, len(dev_months)))
BI_hold = rng.integers(0, len(hold_months), size=(NB, len(hold_months)))
base_dev_pos = pos[dev].mean()
base_hold_pos = pos[hold].mean()


def boot(m, months, BI, v):
    s = np.bincount(month_code[m], weights=v[m], minlength=M)[months]
    c = np.bincount(month_code[m], minlength=M)[months].astype(float)
    if c.sum() == 0:
        return None, None, None
    bs = s[BI].sum(1) / np.maximum(c[BI].sum(1), 1)
    mu = s.sum() / c.sum()
    sd = bs.std()
    return mu, (mu / sd if sd > 0 else None), float((bs <= 0).mean())


def evaluate(m):
    md, mh = m & dev, m & hold
    r = {"n_dev": int(md.sum()), "n_hold": int(mh.sum()),
         "ev_per_day_dev": float(md.sum() / max(len(np.unique(day[dev])), 1))}
    if md.sum() < 50:
        return r
    mu, tt, p = boot(md, dev_months, BI_dev, x_ret)
    r.update({"dev_P+1": pos[md].mean(), "dev_lift": pos[md].mean() / base_dev_pos,
              "dev_net50_bps": 1e4 * (ret[md].mean() - 0.005), "dev_xs_bps": 1e4 * mu, "dev_xs_t": tt,
              "dev_xs_p": p, "dev_xsP+1": x_pos[md].mean()})
    _, tn, pn = boot(md, dev_months, BI_dev, ret - 0.005)
    r["dev_net50_t"] = tn
    for y in (2023, 2024, 2025):
        my = md & (year == y)
        r[f"xs_{y}"] = 1e4 * x_ret[my].mean() if my.sum() >= 20 else None
        r[f"net50_{y}"] = 1e4 * (ret[my].mean() - 0.005) if my.sum() >= 20 else None
    r["dev_years_xs_pos"] = int(sum((r[f"xs_{y}"] or -1) > 0 for y in (2023, 2024, 2025)))
    if mh.sum() >= 30:
        r.update({"hold_P+1": pos[mh].mean(), "hold_lift": pos[mh].mean() / base_hold_pos,
                  "hold_net50_bps": 1e4 * (ret[mh].mean() - 0.005), "hold_xs_bps": 1e4 * x_ret[mh].mean()})
    return r


rows = []
keys = list(blk)
configs = [(k,) for k in keys] + list(itertools.combinations(keys, 2))
for combo in configs:
    base_m = np.ones(len(idx), bool)
    for k in combo:
        base_m &= blk[k]
    for fn, fm in filters.items():
        r = evaluate(base_m & fm)
        r.update({"config": "&".join(combo) + ("" if fn == "none" else f"|{fn}"), "k": len(combo), "filter": fn})
        rows.append(r)
t(f"evaluated {len(rows)} configs")
df = pd.DataFrame(rows)
tested = df[df.n_dev >= 300].copy()
n_tests = len(tested)
# Bonferroni-style hurdle on |t| for the number of configs with >=300 dev events
from scipy.stats import norm  # noqa: E402
t_hurdle = float(norm.ppf(1 - 0.05 / (2 * max(n_tests, 1))))
tested["passes_bonf"] = tested.dev_xs_t.abs() >= t_hurdle
df.to_csv(f"{OUT}/s3_conj_all.csv", index=False)
top = tested.sort_values("dev_xs_t", ascending=False)
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 30)
cols = ["config", "n_dev", "ev_per_day_dev", "dev_P+1", "dev_lift", "dev_net50_bps", "dev_net50_t", "dev_xs_bps",
        "dev_xs_t", "xs_2023", "xs_2024", "xs_2025", "dev_years_xs_pos", "n_hold", "hold_net50_bps", "hold_xs_bps"]
print("configs with >=300 dev events:", n_tests, "bonferroni |t| hurdle:", round(t_hurdle, 2))
print(top[cols].head(30).round(3).to_string())
print(top[cols].tail(10).round(3).to_string())

# event-count vs lift trade-off: best (by dev xs) config per event-count bucket
bins = [300, 1000, 3000, 10000, 30000, 1e9]
tested["bucket"] = pd.cut(tested.n_dev, bins, right=False).astype(str)
trade = tested.sort_values("dev_xs_bps", ascending=False).groupby("bucket").head(3)
trade = trade.sort_values(["bucket", "dev_xs_bps"], ascending=[True, False])

# sector-leak demonstration on L8b (and the universe)
sec = L.load_features(["sector"])["sector"].values[idx]
known = sec != "NA"
leak = {}
for nm, m in (("universe", np.ones(len(idx), bool)), ("L8b_mktlead", blk["L8b"]), ("R1_bd20_long", blk["R1"])):
    for kn, km in (("sector_known", known), ("sector_NA", ~known)):
        leak[f"{nm}|{kn}"] = evaluate(m & km)
t("leak demo")
print(pd.DataFrame(leak).T[["n_dev", "dev_xs_bps", "dev_xs_t", "xs_2023", "xs_2024", "xs_2025", "hold_xs_bps"]].round(2))
save("s3_conj", {"n_configs_evaluated": len(df), "n_configs_ge300_dev_events": n_tests,
                 "bonferroni_t_hurdle": t_hurdle, "top30_by_dev_t": top[cols + ["passes_bonf"]].head(30).to_dict(orient="records"),
                 "bottom10_by_dev_t": top[cols].tail(10).to_dict(orient="records"),
                 "tradeoff_best3_per_bucket": trade[cols + ["bucket"]].to_dict(orient="records"),
                 "singles": df[df.k == 1][cols + ["filter"]].to_dict(orient="records"),
                 "sector_leak_demo": leak})
t("done")
