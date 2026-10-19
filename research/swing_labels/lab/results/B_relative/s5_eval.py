"""Stage 5: cross-evaluation of OOS walk-forward scores against common yardsticks.
Usage: python3 s5_eval.py <h> name=path [name=path ...]
For every score and test year (2023-2025 dev, 2026 holdout):
  * daily Spearman IC vs xs-rank of raw r (== market-excess rank), vol-normalised, neutral residual
    (+ non-overlapping t-stat: every h-th date)
  * mean daily cross-sectional AUC for +1 (top 30%) and -1 (bottom 30%, inverted score) of each
    rank label, for MX_dz(+1) and ABS_dz(+1); pooled AUC of ABS_dz (includes timing)
  * top-decile hit rate of XR_*_30 (+1) vs base 0.30; decile mean returns (raw r, excess r-m)
"""
import sys
import time

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from common import OUT, L, save

h = int(sys.argv[1])
specs = [a.split("=", 1) for a in sys.argv[2:]]
t0 = time.time()
P = L.load_panel(["date"])
dates = P["date"].values.astype("datetime64[D]")
U = np.load(f"{OUT}/meta.npz")["U"]
FNO = np.load(f"{OUT}/meta.npz")["fno"]
Z = np.load(f"{OUT}/labels_h{h}.npz")
V = np.load(f"{OUT}/labels_h{h}_v.npz")
r = Z["r"].astype("float64")
ex = Z["ex"].astype("float64")
pcts = {"raw": Z["pct_raw"].astype("float64"), "vn": Z["pct_vn"].astype("float64"),
        "neu": V["pct_neu"].astype("float64"), "br50": V["pct_br50"].astype("float64")}
labs = {f"XR_{k}_30": None for k in pcts}
for k, p in pcts.items():
    lab = np.where(p > 0.7, 1.0, np.where(p <= 0.3, -1.0, 0.0))
    lab[np.isnan(p)] = np.nan
    labs[f"XR_{k}_30"] = lab
labs["MX_dz"] = Z["MX_dz"].astype("float64")
labs["ABS_dz"] = Z["ABS_dz"].astype("float64")
years = pd.DatetimeIndex(dates).year.values
print("loaded", round(time.time() - t0, 1), flush=True)


def daily_corr(d, a, b):
    """Per-date Pearson corr of a,b (already per-date ranks)."""
    df = pd.DataFrame({"d": d, "a": a, "b": b, "ab": a * b, "aa": a * a, "bb": b * b})
    g = df.groupby("d")
    n = g.size()
    s = g[["a", "b", "ab", "aa", "bb"]].sum()
    cov = s.ab / n - s.a / n * s.b / n
    va = s.aa / n - (s.a / n) ** 2
    vb = s.bb / n - (s.b / n) ** 2
    c = cov / np.sqrt(va * vb)
    return c[n > 20]


def daily_auc(d, score_rank, y):
    df = pd.DataFrame({"d": d, "r": score_rank, "y": y, "ry": score_rank * y})
    g = df.groupby("d")
    npos = g.y.sum()
    n = g.size()
    nneg = n - npos
    auc = (g.ry.sum() - npos * (npos + 1) / 2) / (npos * nneg)
    return auc[(npos > 5) & (nneg > 5)]


def tstat_nonoverlap(series):
    sub = series.iloc[::h]
    return float(sub.mean() / (sub.std() / np.sqrt(len(sub)))) if len(sub) > 3 else np.nan


out = {}
for name, path in specs:
    sc = np.load(path)["score"].astype("float64")
    res = {}
    for Y in (2023, 2024, 2025, 2026):
        mk = U & np.isfinite(sc) & (years == Y) & np.isfinite(r)
        d = dates[mk]
        s = sc[mk]
        srank = pd.Series(s).groupby(d).rank(method="average").values
        spct = pd.Series(s).groupby(d).rank(pct=True).values
        R = {"n": int(mk.sum())}
        for k, p in pcts.items():
            pr = pd.Series(p[mk]).groupby(d).rank(method="average").values
            ic = daily_corr(d, srank, pr)
            R[f"ic_{k}"] = float(ic.mean())
            R[f"ic_{k}_t"] = tstat_nonoverlap(ic)
        for k, lab in labs.items():
            y = lab[mk]
            ok = ~np.isnan(y)
            yp = (y[ok] == 1).astype(float)
            au = daily_auc(d[ok], pd.Series(s[ok]).groupby(d[ok]).rank().values, yp)
            R[f"xsauc_{k}_pos"] = float(au.mean())
            R[f"xsauc_{k}_pos_t"] = tstat_nonoverlap(au - 0.5)
            if k.startswith("XR"):
                yn = (y[ok] == -1).astype(float)
                au2 = daily_auc(d[ok], pd.Series(-s[ok]).groupby(d[ok]).rank().values, yn)
                R[f"xsauc_{k}_neg_inv"] = float(au2.mean())
                top = spct[ok] > 0.9
                R[f"top_dec_rate_{k}"] = float(yp[top].mean())
                R[f"bot_dec_rate_{k}_neg"] = float((y[ok][spct[ok] <= 0.1] == -1).mean())
        # IC restricted to fno_proxy names (relevant for the long-short / futures use)
        mf = mk & FNO
        df_ = dates[mf]
        a_ = pd.Series(sc[mf]).groupby(df_).rank().values
        b_ = pd.Series(pcts["raw"][mf]).groupby(df_).rank().values
        icf = daily_corr(df_, a_, b_)
        R["ic_raw_fno"] = float(icf.mean())
        R["ic_raw_fno_t"] = tstat_nonoverlap(icf)
        a2 = pd.Series(sc[mk & ~FNO]).groupby(dates[mk & ~FNO]).rank().values
        b2 = pd.Series(pcts["raw"][mk & ~FNO]).groupby(dates[mk & ~FNO]).rank().values
        icn = daily_corr(dates[mk & ~FNO], a2, b2)
        R["ic_raw_nonfno"] = float(icn.mean())
        yabs = (labs["ABS_dz"][mk] == 1).astype(float)
        okb = ~np.isnan(labs["ABS_dz"][mk])
        R["pooled_auc_ABS_pos"] = float(roc_auc_score(yabs[okb], s[okb]))
        dec = np.minimum((spct * 10).astype(int), 9)
        dm = pd.DataFrame({"dec": dec, "r": r[mk], "ex": ex[mk], "d": d})
        # equal weight per date then average over dates (date-balanced)
        bd = dm.groupby(["d", "dec"])[["r", "ex"]].mean().groupby("dec").mean() * 1e4
        R["decile_mean_r_bps"] = bd.r.round(1).to_dict()
        R["decile_mean_ex_bps"] = bd.ex.round(1).to_dict()
        R["top_minus_bottom_r_bps"] = float(bd.r.iloc[-1] - bd.r.iloc[0])
        R["top_ex_bps"] = float(bd.ex.iloc[-1])
        R["bottom_ex_bps"] = float(bd.ex.iloc[0])
        res[Y] = R
    dev = {k: float(np.mean([res[y][k] for y in (2023, 2024, 2025)])) for k in res[2023] if isinstance(res[2023][k], float)}
    out[name] = {"by_year": res, "dev_mean": dev}
    print(name, round(time.time() - t0, 1), {k: round(dev[k], 4) for k in dev if k.startswith(("ic_", "xsauc_XR_raw_30_pos", "xsauc_ABS", "top_minus", "top_ex", "pooled")) and not k.endswith("_t")},
          "2026", {k: round(res[2026][k], 4) for k in ("ic_raw", "ic_neu", "ic_vn", "top_minus_bottom_r_bps", "top_ex_bps")}, flush=True)
save(f"s5_eval_h{h}_" + "_".join(n for n, _ in specs), out)
