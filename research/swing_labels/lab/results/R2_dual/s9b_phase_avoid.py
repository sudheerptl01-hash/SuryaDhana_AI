"""Stage 9b: phase sensitivity of the avoid overlays (equal-weight U minus bottom 30%), 50 bp."""
import numpy as np
import pandas as pd

from common import OUT, L, save

P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["atr_pct"])
fw = L.Fwd(P)
S = L.Sim(P, F, fw)
U = np.load(f"{OUT}/meta.npz")["U"]
ld = lambda k: np.load(f"{OUT}/wf_M_{k}.npz")["score"].astype("float64")
av = {"AVOID_RUPup": ld("RUP"), "AVOID_DUALup": ld("DUAL"), "AVOID_DDN": -ld("DDN"), "AVOID_RDN": -ld("RDN"),
      "AVOID_REL": ld("REL"), "AVOID_ABS": ld("ABS")}
rows = []
for win, (a, b) in (("dev", L.DEV), ("hold", (L.HOLDOUT[0], None))):
    g0 = int(np.searchsorted(S.cal, np.datetime64(a)))
    for ph in range(5):
        start = str(S.cal[g0 + ph])
        kw = dict(step=5, top_k=20, cost_bps=50.0, start=start, end_exit=b, sizing="equal")
        base = S.run(av["AVOID_REL"], U, 20, select_quantile=(0.0, 1.0), **kw)
        for k, s in av.items():
            st = S.run(s, U, 20, select_quantile=(0.3, 1.0), **kw)
            d = st["_daily_ret"] - base["_daily_ret"]
            rows.append({"win": win, "phase": ph, "name": k, "cagr": st["cagr"], "univ_cagr": base["cagr"],
                         "vs_univ_ann": float(d.mean() * 252), "vs_univ_t": L.nw_t(d, lag=20)})
df = pd.DataFrame(rows)
summ = {w: {k: {"vs_univ_mean": float(x.vs_univ_ann.mean()), "vs_univ_min": float(x.vs_univ_ann.min()),
                "vs_univ_max": float(x.vs_univ_ann.max()), "t_mean": float(x.vs_univ_t.mean()),
                "n_positive": int((x.vs_univ_ann > 0).sum())} for k, x in df[df.win == w].groupby("name")}
        for w in ("dev", "hold")}
save("s9b_phase_avoid", {"rows": rows, "summary": summ})
for w in ("dev", "hold"):
    print(w); print(pd.DataFrame(summ[w]).T.round(3).to_string())
