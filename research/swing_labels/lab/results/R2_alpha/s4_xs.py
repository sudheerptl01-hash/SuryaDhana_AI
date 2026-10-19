"""Stage 4: cross-sectional learnability of every OOS score (per-date IC / AUC, non-overlapping t),
ensembles, score correlations, and paired ablation deltas.

Ensembles (pre-declared, equal weight, no fitting): per-date percentile rank of each model score among
U rows, averaged:  ENS3 = XR+BAR+TSX ; ENS_XB = XR+BAR ; ENS_XT = XR+TSX ; ENS_BT = BAR+TSX.

Metrics per model (dates with >= 30 names; t from every 20th date; DEV 2023-25 / HOLD 2026):
  ic_xr   : Spearman(score, XR_neu20 pct)      (relative target; common R2 yardstick)
  ic_raw  : Spearman(score, r20)               (what a long book ranks on)
  ic_tsx  : Spearman(score, TSX t*)            (trend-scan target)
  auc_top : AUC of score for XR +1 (pct>0.7)   ; auc_bot : AUC of -score for XR -1 (pct<=0.3)
  auc_bar : AUC of score for BAR=+1            ; auc_tsxup : AUC of score for TSX=+1
Cross-check: L.xs_metrics(XR score, pct, U, P, 20, binary=pct>0.7) must equal ic_xr / auc_top.
Ablation: paired per-date difference (base XR_all minus XR_no_<group>) of ic_xr and ic_raw, mean and
non-overlapping t.
Usage: python3 s4_xs.py [tags...]   (default: all wf_*.npz present)
"""
import glob
import os
import sys
import time

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from common import OUT, L, H, save, load_res, xs_pct, per_date_metrics, summarize_pd, date_blocks

t0 = time.time()
P = L.load_panel(["date"])
dates = P["date"].values.astype("datetime64[D]")
Z = np.load(f"{OUT}/labels.npz")
U = Z["U"]
pct = Z["pct"].astype("float64")
r20 = Z["r20"].astype("float64")
tsx_t = Z["tsx_t"].astype("float64")
bar = Z["bar"].astype("float64")
tsx = Z["tsx"].astype("float64")
TGT = {"xr": pct, "raw": r20, "tsx": tsx_t}
top = np.where(np.isfinite(pct), (pct > 0.7).astype(float), np.nan)
bot = np.where(np.isfinite(pct), (pct <= 0.3).astype(float), np.nan)
barup = np.where(np.isfinite(bar), (bar == 1).astype(float), np.nan)
tsxup = np.where(np.isfinite(tsx), (tsx == 1).astype(float), np.nan)
BIN = {"top": (top, 1.0), "bot": (bot, -1.0), "bar": (barup, 1.0), "tsxup": (tsxup, 1.0)}


def load_score(tag):
    return np.load(f"{OUT}/wf_{tag}.npz")["score"].astype("float64")


# ---------------------------------------------------------------- ensembles
base = {k: load_score(f"{k}_all") for k in ("XR", "BAR", "TSX") if os.path.exists(f"{OUT}/wf_{k}_all.npz")}
if len(base) == 3:
    rk = {k: xs_pct(v, dates, U) for k, v in base.items()}
    for nm, parts in (("ENS3", ("XR", "BAR", "TSX")), ("ENS_XB", ("XR", "BAR")), ("ENS_XT", ("XR", "TSX")),
                      ("ENS_BT", ("BAR", "TSX"))):
        s = np.mean(np.vstack([rk[p] for p in parts]), axis=0)
        np.savez_compressed(f"{OUT}/wf_{nm}.npz", score=s.astype(np.float32))
    print("ensembles saved", round(time.time() - t0, 1), flush=True)

tags = sys.argv[1:] or sorted(os.path.basename(f)[3:-4] for f in glob.glob(f"{OUT}/wf_*.npz"))
done = load_res()
tables = {}
for tag in tags:
    sc = load_score(tag)
    t = per_date_metrics(sc, TGT, BIN, U, dates)
    tables[tag] = t
    summ = summarize_pd(t, H)
    save(f"s4_xs_{tag}", summ)
    print(tag, {k: round(v, 4) for k, v in summ.items() if k.startswith(("dev_ic", "hold_ic", "dev_auc", "hold_auc"))
                and not k.endswith("_t")}, round(time.time() - t0, 1), flush=True)
    t.to_parquet(f"{OUT}/xs_daily_{tag}.parquet")

# ---------------------------------------------------------------- cross-check vs L.xs_metrics
if "XR_all" in tables:
    sc = load_score("XR_all")
    lib = L.xs_metrics(sc, pct, U, P, H, binary_target=top)
    mine = summarize_pd(tables["XR_all"], H)
    chk = {"lib_dev_ic": lib.get("dev_ic_mean"), "mine_dev_ic": mine.get("dev_ic_xr"),
           "lib_dev_ic_t": lib.get("dev_ic_t_nonoverlap"), "mine_dev_ic_t": mine.get("dev_ic_xr_t"),
           "lib_dev_auc": lib.get("dev_auc_mean"), "mine_dev_auc": mine.get("dev_auc_top"),
           "lib_hold_ic": lib.get("holdout_ic_mean"), "mine_hold_ic": mine.get("hold_ic_xr"),
           "lib_ic_by_year": lib.get("dev_ic_by_year")}
    save("s4_xcheck_xs_metrics", chk)
    print("xcheck", chk, flush=True)

# ---------------------------------------------------------------- paired ablation deltas
all_tabs = {os.path.basename(f)[9:-8]: f for f in glob.glob(f"{OUT}/xs_daily_*.parquet")}
if "XR_all" in all_tabs:
    tb = pd.read_parquet(all_tabs["XR_all"])
    abl = {}
    for tag, fn in sorted(all_tabs.items()):
        if not tag.startswith("XR_no_"):
            continue
        ta = pd.read_parquet(fn)
        j = tb.join(ta, lsuffix="_b", rsuffix="_a", how="inner")
        rec = {}
        for name, (a, b) in (("dev", L.DEV), ("hold", ("2026-01-01", "2100-01-01"))):
            sub = j[(j.index >= np.datetime64(a)) & (j.index <= np.datetime64(b))]
            nov = sub.iloc[::H]
            for col in ("ic_xr", "ic_raw", "auc_top", "auc_bot"):
                d = sub[f"{col}_a"] - sub[f"{col}_b"]
                dn = (nov[f"{col}_a"] - nov[f"{col}_b"]).dropna()
                rec[f"{name}_d_{col}"] = float(d.mean())
                rec[f"{name}_d_{col}_t"] = float(dn.mean() / (dn.std(ddof=1) / np.sqrt(len(dn)))) if len(dn) > 3 else None
        yrs = pd.DatetimeIndex(j.index).year
        rec["d_ic_xr_by_year"] = {int(y): float((g["ic_xr_a"] - g["ic_xr_b"]).mean()) for y, g in j.groupby(yrs)}
        abl[tag] = rec
        print("ablation", tag, {k: round(v, 4) for k, v in rec.items() if isinstance(v, float)}, flush=True)
    save("s4_ablation_dIC", abl)

# ---------------------------------------------------------------- score correlations (per-date Spearman)
names = [k for k in ("XR_all", "BAR_all", "TSX_all", "ENS3") if os.path.exists(f"{OUT}/wf_{k}.npz")]
if len(names) >= 3:
    S = {k: load_score(k) for k in names}
    m = U & np.all(np.vstack([np.isfinite(v) for v in S.values()]), axis=0)
    idx, b0, e0 = date_blocks(dates, np.flatnonzero(m))
    recs = []
    for s_, t_ in zip(b0, e0):
        ii = idx[s_:t_]
        if len(ii) < 30:
            continue
        rks = {k: rankdata(v[ii]) for k, v in S.items()}
        rec = {"d": dates[ii[0]]}
        for i, a in enumerate(names):
            for bname in names[i + 1:]:
                rec[f"{a}~{bname}"] = np.corrcoef(rks[a], rks[bname])[0, 1]
        # top-20 overlap between single models
        top20 = {k: set(ii[np.argsort(-S[k][ii])[:20]]) for k in names}
        for i, a in enumerate(names):
            for bname in names[i + 1:]:
                rec[f"ov20_{a}~{bname}"] = len(top20[a] & top20[bname]) / 20.0
        recs.append(rec)
    cdf = pd.DataFrame(recs).set_index("d")
    out = {}
    for name, (a, b) in (("dev", L.DEV), ("hold", ("2026-01-01", "2100-01-01"))):
        sub = cdf[(cdf.index >= np.datetime64(a)) & (cdf.index <= np.datetime64(b))]
        out[name] = sub.mean().to_dict()
    out["by_year"] = {int(y): g.mean().to_dict() for y, g in cdf.groupby(pd.DatetimeIndex(cdf.index).year)}
    save("s4_score_corr", out)
    print("score corr", {k: round(v, 3) for k, v in out["dev"].items()}, flush=True)
print("total", round(time.time() - t0, 1))
