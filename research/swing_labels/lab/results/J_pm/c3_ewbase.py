"""J_pm check 3: seed-free baseline. The expectation of a random top-20 book on the same mask is the
equal-weight universe book (same h, step, fully invested). Phase-averaged excess of the main candidates
vs that EW book, DEV and 2026, plus the Nifty 500 over the same dates. Also 20-seed random for one case."""
import sys, json, numpy as np, pandas as pd
LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB); import lablib as L
R = LAB + "/results"
P = L.load_panel(["date", "entity", "seg_break", "label_block", "open", "high", "low", "close"])
F = L.load_features(["elig_base"])
mask = F.elig_base.values.astype(bool)
fw = L.Fwd(P); S = L.Sim(P, None, fw); cal = S.cal
def ld(p): return np.load(p)["score"].astype("float64")
scores = {
 "neumom_RANK": ld(R + "/R2_rel/wf_h20_neumom_RANK.npz"),
 "neu_RANK": ld(R + "/R2_rel/wf_h20_neu_RANK.npz"),
 "neumom_C20": ld(R + "/R2_rel/wf_h20_neumom_C20.npz"),
 "neumom_T30": ld(R + "/R2_rel/wf_h20_neumom_T30.npz"),
 "dual_RUP": ld(R + "/R2_dual/wf_M_RUP.npz"),
 "dual_REL": ld(R + "/R2_dual/wf_M_REL.npz"),
}
# rank-sum blend of RANK and T30 on the same neumom residual (pre-declared as the robustness alternative)
def prank(x):
    s = pd.Series(np.where(mask, x, np.nan)); g = pd.Series(S.didx)
    return s.groupby(g).rank(pct=True).values
scores["blend_neumom_RANK+T30"] = prank(scores["neumom_RANK"]) + prank(scores["neumom_T30"])
mk = L.market_series("Nifty 500")["close"]; mk.index = pd.DatetimeIndex(mk.index)
out = {}
for win, kw in {"dev": dict(start=L.DEV[0], end_exit=L.DEV[1]), "hold": dict(start="2026-01-01", end_exit=None)}.items():
    ew_l = {}; st_l = {k: [] for k in scores}
    for ph in range(5):
        st = str(cal[int(np.searchsorted(cal, np.datetime64(kw["start"]))) + ph])
        ew = S.run(scores["neumom_RANK"], mask, 20, step=5, cost_bps=50.0, start=st, end_exit=kw["end_exit"],
                   sizing="equal", select_quantile=(0.0, 1.0))
        ew_l[ph] = pd.Series(ew["_daily_ret"], index=pd.DatetimeIndex(ew["_dates"]))
        for k, sc in scores.items():
            r = S.run(sc, mask, 20, step=5, top_k=20, cost_bps=50.0, start=st, end_exit=kw["end_exit"])
            st_l[k].append(pd.Series(r["_daily_ret"], index=pd.DatetimeIndex(r["_dates"])))
    idx = ew_l[4].index
    for ph in range(5): idx = idx.intersection(ew_l[ph].index)
    ewm = np.mean([ew_l[p].loc[idx].values for p in range(5)], 0)
    yrs = (idx[-1] - idx[0]).days / 365.25
    cg = lambda x: float(np.prod(1 + x) ** (1 / yrs) - 1)
    m = mk.reindex(idx).ffill()
    res = {"ew_universe_pa_cagr": cg(ewm), "nifty500_cagr_same_dates": float((m.iloc[-1] / m.iloc[0]) ** (1 / yrs) - 1),
           "days": int(len(idx))}
    for k in scores:
        sm = np.mean([s.loc[idx].values for s in st_l[k]], 0)
        eq = np.cumprod(1 + sm)
        res[k] = dict(pa_cagr=cg(sm), excess_vs_ew_ann=float((sm - ewm).mean() * 252), nw_t=float(L.nw_t(sm - ewm, lag=20)),
                      maxdd=float((eq / np.maximum.accumulate(eq) - 1).min()),
                      ew_maxdd=float((np.cumprod(1 + ewm) / np.maximum.accumulate(np.cumprod(1 + ewm)) - 1).min()))
    # paired differences vs neumom_RANK
    base = np.mean([s.loc[idx].values for s in st_l["neumom_RANK"]], 0)
    res["paired_vs_neumom_RANK"] = {k: dict(ann=float((np.mean([s.loc[idx].values for s in st_l[k]], 0) - base).mean() * 252),
                                            t=float(L.nw_t(np.mean([s.loc[idx].values for s in st_l[k]], 0) - base, lag=20)))
                                    for k in scores if k != "neumom_RANK"}
    out[win] = res
    print(win, json.dumps(res, indent=1), flush=True)
json.dump(out, open(R + "/J_pm/c3_ewbase.json", "w"), indent=1)
