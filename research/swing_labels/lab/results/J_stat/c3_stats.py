"""J_stat check 3: dependence-robust inference on the phase-averaged excess series from c2."""
import sys
import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402

Z = np.load(f"{LAB}/results/J_stat/pa_series.npz")
rng = np.random.default_rng(12345)


def mbb_p(x, block, nboot=4000):
    """Circular moving-block bootstrap: one-sided p for mean>0 (resample the centred series)
    and a 90% percentile CI of the annualised mean."""
    x = np.asarray(x, float)
    n = len(x)
    nb = int(np.ceil(n / block))
    xc = x - x.mean()
    starts = rng.integers(0, n, size=(nboot, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(nboot, -1)[:, :n] % n
    mc = xc[idx].mean(1)
    mb = x[idx].mean(1)
    p = float((mc >= x.mean()).mean())
    lo, hi = np.percentile(mb * 252, [5, 95])
    return p, float(lo), float(hi)


def report(name, x, dates):
    x = np.asarray(x, float)
    d = pd.to_datetime(dates)
    r = {"ann_mean": x.mean() * 252}
    for lag in (20, 60, 120, 250):
        if lag < len(x) // 2:
            r[f"nw{lag}"] = L.nw_t(x, lag=lag)
    for bl in (20, 60, 120):
        p, lo, hi = mbb_p(x, bl)
        r[f"mbb{bl}_p"] = p
        r[f"mbb{bl}_ci90"] = (round(lo * 100, 1), round(hi * 100, 1))
    s = pd.Series(x, index=d)
    by = s.groupby(s.index.year).agg(["mean", "count"])
    r["by_year_ann"] = {int(y): round(v * 252 * 100, 1) for y, v in by["mean"].items()}
    if len(by) > 1:
        r["loyo_ann"] = {int(y): round(s[s.index.year != y].mean() * 252 * 100, 1) for y in by.index}
    # month-level t (calendar months as blocks, no overlap correction beyond the month)
    m = s.groupby([s.index.year, s.index.month]).sum()
    r["months"] = len(m)
    r["month_t"] = float(m.mean() / (m.std(ddof=1) / np.sqrt(len(m))))
    q = s.groupby([s.index.year, s.index.quarter]).sum()
    r["quarters_pos"] = f"{int((q > 0).sum())}/{len(q)}"
    r["quarter_t"] = float(q.mean() / (q.std(ddof=1) / np.sqrt(len(q))))
    print(f"\n== {name}: ann mean {r['ann_mean']*100:.2f}%")
    for k, v in r.items():
        if k != "ann_mean":
            print(f"   {k}: {round(v, 3) if isinstance(v, float) else v}")
    return r


res = {}
for per in ("dev", "hold"):
    dates = Z[f"{per}__dates"]
    rnd = Z[f"{per}__long_random"]
    ew = Z[f"{per}__ew"]
    print(f"\n######## {per}  n={len(dates)} days   random CAGR {np.prod(1+rnd)**(252/len(rnd))-1:.3f}  EW CAGR {np.prod(1+ew)**(252/len(ew))-1:.3f}")
    for nm in ("neumom_RANK", "neu_RANK", "dual_REL", "neumom_T30"):
        x = Z[f"{per}__long_{nm}"]
        print(f"   {nm}: PA CAGR {np.prod(1+x)**(252/len(x))-1:.3f}")
        res[f"{per}_long_{nm}"] = report(f"{per} long {nm} - random", x - rnd, dates)
    for nm in ("neumom_RANK", "neumom_T30"):
        x = Z[f"{per}__avoid_{nm}"]
        res[f"{per}_avoid_{nm}"] = report(f"{per} avoid30 {nm} - EW", x - ew, dates)
    pairs = [("neumom_RANK", "neu_RANK"), ("neu_RANK", "dual_REL"), ("neumom_T30", "neumom_RANK"), ("neumom_RANK", "dual_REL")]
    for a, b in pairs:
        xa, xb = Z[f"{per}__long_{a}"], Z[f"{per}__long_{b}"]
        print(f"   corr daily {a} vs {b}: {np.corrcoef(xa - rnd, xb - rnd)[0,1]:.3f}")
        res[f"{per}_pair_{a}_minus_{b}"] = report(f"{per} PAIRED {a} - {b}", xa - xb, dates)
import json
json.dump(res, open(f"{LAB}/results/J_stat/c3_stats.json", "w"), indent=1, default=str)
