"""Stage 5: OOS learnability of meta-labels vs label-every-bar model.

For each gated setup S (R1, L7, R3, L3) and each scorer (META_S = trained on S rows only,
ALLBAR = trained on every U bar), on S rows per OOS year (2023-2025 dev, 2026 holdout):
  * pooled AUC (timing + selection), date-neutral IC = Spearman(score, date-demeaned ret)
  * precision / expectancy of score-filtered events vs all events:
      PIT filter  : score > the fold's training base rate (classifier calibration; no look-ahead)
      top tercile : score in top third of that year's S-row scores (ex-post threshold, diagnostic)
For ALLBAR on all U rows: mean daily cross-sectional AUC (XS-AUC) and daily rank IC vs ret with
non-overlapping (every 10th date) t-stats, top/bottom decile rates.
"""
import numpy as np
import pandas as pd
from scipy.stats import spearmanr
from sklearn.metrics import roc_auc_score

from common import OUT, DEV_END, load_base, load_res, save, T

t = T()
B = load_base()
names = list(B["setup_names"])
R = load_res()
U = B["U"]
lab = B["lab_L"].astype("float64")
ok = U & ~np.isnan(lab)
idx = np.flatnonzero(ok)
day = B["day"][idx].astype("datetime64[D]")
ret = B["ret_L"][idx].astype("float64")
pos = (lab[idx] == 1).astype(float)
df = pd.DataFrame({"d": day, "ret": ret, "pos": pos})
x_ret = ret - df.groupby("d").ret.transform("mean").values
year = pd.DatetimeIndex(day).year.values
sc_all = np.load(f"{OUT}/wf_ALL.npz")["score"][idx].astype("float64")
SETMAP = {"R1": "S1_bd20", "R3": "S3_rslag", "L7": "L7_oversold_up", "L3": "L3_pullback"}
out = {}


def block(m, label):
    if m.sum() < 20:
        return {"n": int(m.sum())}
    return {"n": int(m.sum()), "P+1": pos[m].mean(), "net50_bps": 1e4 * (ret[m].mean() - 0.005),
            "xs_bps": 1e4 * x_ret[m].mean()}


rows = []
for tag, sname in SETMAP.items():
    sm = B["setups"][:, names.index(sname)][idx]
    sc_meta = np.load(f"{OUT}/wf_{tag}.npz")["score"][idx].astype("float64")
    folds_meta = {f["year"]: f for f in R[f"s4_wf_{tag}"]["folds"]}
    folds_all = {f["year"]: f for f in R["s4_wf_ALL"]["folds"]}
    for scn, sc, folds in (("META", sc_meta, folds_meta), ("ALLBAR", sc_all, folds_all)):
        for Y in (2023, 2024, 2025, 2026):
            m = sm & (year == Y) & np.isfinite(sc)
            if m.sum() < 50:
                continue
            s = sc[m]
            r = {"setup": tag, "scorer": scn, "year": Y, "n_events": int(m.sum()),
                 "auc_pooled": roc_auc_score(pos[m], s) if 0 < pos[m].mean() < 1 else None,
                 "ic_date_neutral": spearmanr(s, x_ret[m]).correlation,
                 "ic_raw": spearmanr(s, ret[m]).correlation}
            allb = block(m, "all")
            thr = folds[Y].get("train_base_rate") if scn == "META" else None
            if thr is None:  # ALLBAR: training base rate of the all-bar fold (from labels before cutoff)
                cut = np.datetime64(f"{Y}-01-01") - np.timedelta64(16, "D")
                tr = (day < cut) & (day >= np.datetime64("2021-09-01"))
                thr = pos[tr].mean()
            pit = m.copy()
            pit[m] = s > thr
            q = pd.Series(s).rank(pct=True).values
            top3 = m.copy()
            top3[m] = q > 2 / 3
            bot3 = m.copy()
            bot3[m] = q <= 1 / 3
            for nm, bb in (("all", allb), ("pit_pass", block(pit, "")), ("top_tercile", block(top3, "")),
                           ("bottom_tercile", block(bot3, ""))):
                for k, v in bb.items():
                    r[f"{nm}_{k}"] = v
            r["pit_threshold"] = thr
            r["pit_pass_share"] = float(pit.sum() / m.sum())
            rows.append(r)
    t(tag)
ev = pd.DataFrame(rows)
ev.to_csv(f"{OUT}/s5_meta_eval.csv", index=False)


# dev (2023-2025 pooled) and holdout summaries, event-weighted
def agg(g):
    w = g.n_events
    o = {"n_events": int(w.sum())}
    for c in ("auc_pooled", "ic_date_neutral", "ic_raw"):
        o[c] = float(np.average(g[c].astype(float), weights=w))
    for nm in ("all", "pit_pass", "top_tercile", "bottom_tercile"):
        ww = g[f"{nm}_n"]
        o[f"{nm}_n"] = int(ww.sum())
        for k in ("P+1", "net50_bps", "xs_bps"):
            col = f"{nm}_{k}"
            if col in g:
                vv = g[col].astype(float)
                okk = vv.notna()
                o[f"{nm}_{k}"] = float(np.average(vv[okk], weights=ww[okk])) if okk.any() else None
    return pd.Series(o)


ev["period"] = np.where(ev.year == 2026, "hold_2026", "dev_2023_2025")
summ = ev.groupby(["setup", "scorer", "period"]).apply(agg, include_groups=False).reset_index()
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 40)
print(summ[["setup", "scorer", "period", "n_events", "auc_pooled", "ic_date_neutral", "all_P+1", "all_net50_bps",
            "all_xs_bps", "pit_pass_n", "pit_pass_P+1", "pit_pass_net50_bps", "pit_pass_xs_bps", "top_tercile_P+1",
            "top_tercile_net50_bps", "top_tercile_xs_bps", "bottom_tercile_xs_bps"]].round(3).to_string())
print(ev[["setup", "scorer", "year", "n_events", "auc_pooled", "ic_date_neutral", "all_xs_bps", "pit_pass_share",
          "pit_pass_xs_bps", "top_tercile_xs_bps", "bottom_tercile_xs_bps"]].round(3).to_string())
out["per_year"] = ev.to_dict(orient="records")
out["summary"] = summ.to_dict(orient="records")

# ALLBAR on all U rows: daily XS-AUC and rank IC (selection skill) vs pooled AUC (timing+selection)
d2 = pd.DataFrame({"d": day, "y": pos, "r": ret, "s": sc_all, "year": year}).dropna(subset=["s"])


def daily(g):
    if len(g) < 30 or g.y.nunique() < 2:
        return pd.Series({"xs_auc": np.nan, "ic": np.nan})
    return pd.Series({"xs_auc": roc_auc_score(g.y, g.s), "ic": g.s.rank().corr(g.r.rank())})


dd = d2.groupby("d").apply(daily, include_groups=False).dropna()
dd["year"] = pd.DatetimeIndex(dd.index).year
xs = {}
for Y, g in dd.groupby("year"):
    sub = g.iloc[::10]
    xs[int(Y)] = {"days": int(len(g)), "xs_auc_mean": g.xs_auc.mean(), "ic_mean": g.ic.mean(),
                  "xs_auc_t_nonoverlap": (sub.xs_auc.mean() - 0.5) / (sub.xs_auc.std() / np.sqrt(len(sub))),
                  "ic_t_nonoverlap": sub.ic.mean() / (sub.ic.std() / np.sqrt(len(sub)))}
    q = d2[d2.year == Y]
    rk = q.groupby("d").s.rank(pct=True)
    xs[int(Y)].update({"base": q.y.mean(), "top_decile": q.y[rk > 0.9].mean(), "bottom_decile": q.y[rk <= 0.1].mean(),
                       "top_decile_xs_bps": 1e4 * (q.r[rk > 0.9].mean() - q.r.mean()),
                       "top_decile_net50_bps": 1e4 * (q.r[rk > 0.9].mean() - 0.005)})
devg = dd[(dd.index >= np.datetime64("2023-01-01")) & (dd.index <= np.datetime64(DEV_END))].iloc[::10]
xs["dev_pooled"] = {"xs_auc_mean": devg.xs_auc.mean(),
                    "xs_auc_t": (devg.xs_auc.mean() - 0.5) / (devg.xs_auc.std() / np.sqrt(len(devg))),
                    "ic_mean": devg.ic.mean(), "ic_t": devg.ic.mean() / (devg.ic.std() / np.sqrt(len(devg)))}
print(pd.DataFrame(xs).T.round(4).to_string())
out["allbar_xs"] = xs
save("s5_eval", out)
t("done")
