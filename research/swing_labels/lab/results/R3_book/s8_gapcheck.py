"""Diagnostic for the X3 finding: close(t) -> open(t+1) gap of the names the frozen book exits at a rebalance close
(PROD top-20 picked 20 trading days earlier) vs random exits, by year and liquidity tier (liq5 vs liq2-only).
Rows = every trading day as a signal date (= all 5 phases); exit row = pick + 20 bars when the window is clean."""
import numpy as np
import pandas as pd
from bk_setup import setup, C, L

T = setup(extra_feat=("vol_20", "elig_liq5"))
S, E, prod, F, fw = T["S"], T["E"], T["prod"], T["F"], T["fw"]
liq5 = E & F["elig_liq5"].values.astype(bool)
o, c, didx = S.o, S.c, S.didx
ok20 = fw.ok(20)
out = {}
rng = np.random.default_rng(11)
for per in ("dev", "hold"):
    a, b = C.PER[per]
    g0 = int(np.searchsorted(S.cal, np.datetime64(a)))
    g1 = int(np.searchsorted(S.cal, np.datetime64(b or "2026-10-14"), side="right")) - 22
    rows_m, rows_r = [], []
    for g in range(g0, g1):
        cand = S.rows_on(g)
        cand = cand[E[cand] & np.isfinite(prod[cand])]
        rows_m.append(cand[np.argsort(-prod[cand], kind="stable")[:20]])
        rows_r.append(rng.choice(cand, size=20, replace=False))
    res = {}
    for nm, rws in (("model_exits", np.concatenate(rows_m)), ("random_exits", np.concatenate(rows_r))):
        rws = rws[ok20[rws] & fw.exists(21)[rws]]
        ex = rws + 20
        nx = ex + 1
        clean = (fw.lb_cs[nx] - fw.lb_cs[ex]) == 0
        ex, nx, src = ex[clean], nx[clean], rws[clean]
        gap = o[nx] / c[ex] - 1
        yrs = pd.DatetimeIndex(S.cal[didx[ex]]).year.values
        d = {"n": int(len(gap)), "mean_gap": float(gap.mean()), "median_gap": float(np.median(gap)),
             "share_positive": float((gap > 0).mean()), "trimmed_mean_1_99": float(pd.Series(gap).clip(*np.percentile(gap, [1, 99])).mean()),
             "mean_gap_liq5": float(gap[liq5[src]].mean()), "mean_gap_liq2_only": float(gap[~liq5[src]].mean()),
             "share_liq5": float(liq5[src].mean()),
             "by_year_mean": {int(y): float(gap[yrs == y].mean()) for y in np.unique(yrs)},
             "by_year_median": {int(y): float(np.median(gap[yrs == y])) for y in np.unique(yrs)}}
        res[nm] = d
    out[per] = res
    C.log(per, C.short(res, 5))
C.save("item2c_overnight_gap_check", out)
