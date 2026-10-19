"""Stage 11: selection precision ("event rates of the book"): among each model's daily top-20 (elig rows
with a defined label), share landing in the label's +1 / 0 / -1 class (30/40/30 of the neu residual at the
model's h; base rates 0.30/0.40/0.30), hit rate (net of 50 bps > 0) and mean net; among the model's daily
bottom-30%, share landing in -1 and mean net. By year (all dates; overlapping windows).
Usage: python3 s11_precision.py tag1 tag2 ...
"""
import sys

import numpy as np
import pandas as pd

from common import OUT, L, save, form_label, load_res

tags = sys.argv[1:]
P = L.load_panel(["date"])
dates = P["date"].values.astype("datetime64[D]")
yr = pd.DatetimeIndex(dates).year.values
E = np.load(f"{OUT}/meta.npz")["E"]
res = load_res().get("s11_precision", {})
cache = {}
for tag in tags:
    h = int(tag.split("_")[0][1:])
    if h not in cache:
        Z = np.load(f"{OUT}/labels_h{h}.npz")
        cache[h] = (Z["r"].astype("float64"), form_label(Z["pct_neu"].astype("float64"), "C30"))
    r, lab = cache[h]
    sc = np.load(f"{OUT}/wf_{tag}.npz")["score"].astype("float64")
    m = E & np.isfinite(sc) & np.isfinite(lab)
    df = pd.DataFrame({"d": dates[m], "y": yr[m], "s": sc[m], "lab": lab[m], "net": r[m] - 0.005})
    df["rk"] = df.groupby("d").s.rank(ascending=False, method="first")
    df["pr"] = df.groupby("d").s.rank(pct=True)
    top = df[df.rk <= 20]
    bot = df[df.pr <= 0.3]
    o = {}
    for y in sorted(df.y.unique()):
        t, b, a = top[top.y == y], bot[bot.y == y], df[df.y == y]
        o[int(y)] = {"top20_p_plus": float((t.lab == 1).mean()), "top20_p_zero": float((t.lab == 0).mean()),
                     "top20_p_minus": float((t.lab == -1).mean()), "top20_hit": float((t.net > 0).mean()),
                     "top20_mean_net_bps": float(t.net.mean() * 1e4), "all_hit": float((a.net > 0).mean()),
                     "all_mean_net_bps": float(a.net.mean() * 1e4),
                     "bot30_p_minus": float((b.lab == -1).mean()), "bot30_mean_net_bps": float(b.net.mean() * 1e4)}
    res[tag] = o
    print(tag, {y: {k: round(v, 3) for k, v in x.items()} for y, x in o.items()}, flush=True)
save("s11_precision", res)
