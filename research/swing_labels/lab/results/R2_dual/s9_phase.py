"""Stage 9: signal-calendar phase sensitivity. Same books (K20, step 5, h=20, 50 bp), but the signal
calendar starts 0..4 trading days later. The paired differences between label choices should be
judged against this phase noise."""
import numpy as np
import pandas as pd

from common import OUT, L, save, xs_pct

P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["atr_pct"])
fw = L.Fwd(P)
S = L.Sim(P, F, fw)
U = np.load(f"{OUT}/meta.npz")["U"]
dates = P["date"].values.astype("datetime64[D]")
sc = {k: np.load(f"{OUT}/wf_M_{k}.npz")["score"].astype("float64") for k in ("REL", "RUP", "DUAL", "DUALP", "ABS")}
sc["SUM_REL_RUP"] = xs_pct(sc["REL"], dates, U) + xs_pct(sc["RUP"], dates, U)
sc["SUM_REL_DUAL"] = xs_pct(sc["REL"], dates, U) + xs_pct(sc["DUAL"], dates, U)
rows = []
for win, (a, b) in (("dev", L.DEV), ("hold", (L.HOLDOUT[0], None))):
    g0 = int(np.searchsorted(S.cal, np.datetime64(a)))
    for ph in range(5):
        start = str(S.cal[g0 + ph])
        kw = dict(step=5, top_k=20, cost_bps=50.0, start=start, end_exit=b)
        rb = S.random_band(U, 20, seeds=(1, 2, 3, 4, 5), **kw)
        rr = {}
        for k, s in sc.items():
            st = S.run(s, U, 20, **kw)
            rr[k] = st["_daily_ret"]
            rows.append({"win": win, "phase": ph, "name": k, "cagr": st["cagr"], "max_dd": st["max_dd"],
                         "excess_cagr": st["cagr"] - rb["cagr_mean"],
                         "excess_nw_t": L.nw_t(st["_daily_ret"] - rb["_daily_ret_mean"], lag=20)})
        for a_, b_ in (("DUAL", "RUP"), ("DUAL", "REL"), ("DUALP", "RUP"), ("RUP", "REL"), ("SUM_REL_DUAL", "SUM_REL_RUP")):
            d = rr[a_] - rr[b_]
            rows.append({"win": win, "phase": ph, "name": f"{a_}-{b_}", "ann_diff": float(d.mean() * 252),
                         "nw_t": L.nw_t(d, lag=20)})
df = pd.DataFrame(rows)
summ = {}
for win in ("dev", "hold"):
    g = df[(df.win == win) & df.cagr.notna()]
    summ[win] = {k: {"cagr_mean": float(x.cagr.mean()), "cagr_min": float(x.cagr.min()), "cagr_max": float(x.cagr.max()),
                     "excess_mean": float(x.excess_cagr.mean()), "excess_min": float(x.excess_cagr.min()),
                     "maxdd_mean": float(x.max_dd.mean())} for k, x in g.groupby("name")}
    g2 = df[(df.win == win) & df.ann_diff.notna()]
    summ[win]["pairs"] = {k: {"diff_mean": float(x.ann_diff.mean()), "diff_min": float(x.ann_diff.min()),
                              "diff_max": float(x.ann_diff.max()), "n_positive": int((x.ann_diff > 0).sum()),
                              "t_mean": float(x.nw_t.mean())} for k, x in g2.groupby("name")}
save("s9_phase", {"rows": rows, "summary": summ})
pd.set_option("display.width", 200)
for win in ("dev", "hold"):
    print(win)
    print(pd.DataFrame({k: v for k, v in summ[win].items() if k != "pairs"}).T.round(3).to_string())
    print(pd.DataFrame(summ[win]["pairs"]).T.round(3).to_string())
