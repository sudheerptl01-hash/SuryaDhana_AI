"""Stage 4: meta-labeling inside the capitulation gate.

Training/scoring mask  R1B = U & close < prior-10-bar low (broadest breakdown set, ~107k rows; contains
every R1 variant used here).  L.walk_forward2 (yearly expanding folds 2023-2026, embargo h+2,
date_step=1, n_jobs=2, min_train=2000, min_test=100, small trees), features = L.FEATURES + [brd, bdd10, bdd20].
  WF_R10 : regression on R2_rel's relative label at h=10 (per-date residual rank, neumom) - 0.5
  WF_A10 : binary 1{r_10 > 50 bps}  (absolute net-positive meta-label, round-1 style)
Free comparators (already OOS, R2_rel every-bar models on all elig rows): EB_XR10, EB_XR20.
Simple rules: DEPTH (deeper close-below-low first), LIQ (more liquid first).

Evaluation inside gate A1 (R1|L10|v0|mom20dn_brd5, DEV-selected in s2) and A0 (round-1 R1dn):
  * xs_metrics (per-date IC / AUC on days with >=30 events, non-overlap t) vs x_h and r_h
  * S (step=1, K in {10,20}, h in {5,10,20}): score top-K vs random events (S.compare semantics) and
    vs count-matched universe random; PIT threshold variant (score > 0.5 prob / > 0 rank).
"""
import numpy as np
import pandas as pd

from common import (OUT, L, T, load_base, matched_mask, counts_by_g, save, summarize_runs, excess_stats,
                    cluster_t)

t = T()
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(L.FEATURES + ["atr_pct"])
fw = L.Fwd(P)
S = L.Sim(P, F, fw)
B = load_base()
U = B["U"]
didx = S.didx
ncal = len(S.cal)
brd_day = np.load(f"{OUT}/brd_day.npy")
brd = brd_day[didx]
F["brd"] = brd.astype(np.float32)
F["bdd10"] = B["bdd10"]
F["bdd20"] = B["bdd20"]
FEATS = L.FEATURES + ["brd", "bdd10", "bdd20"]
mm20 = B["mkt_mom20"]
R1B = U & (B["bdd10"] < 0)
A1 = U & (B["bdd10"] < 0) & (B["volz_20"] > 0) & (mm20 < 0) & (brd >= 0.05)
A0 = U & (B["bdd20"] < 0) & (B["volz_20"] > 1) & (mm20 < 0)
t(f"init R1B {R1B.sum()} A1 {A1.sum()} A0 {A0.sum()}")

lab10 = np.load(f"{L.LAB}/results/R2_rel/labels_h10.npz")["pct_neumom"].astype("float64")
y_r = lab10 - 0.5
y_a = np.where(np.isfinite(B["r10"]), (B["r10"] > 0.005).astype(float), np.nan)
prm = dict(num_leaves=15, min_child_samples=100, n_estimators=300, learning_rate=0.03)
scores = {}
import os
cache = f"{OUT}/s4_scores.npz"
if os.path.exists(cache):
    z = np.load(cache)
    scores = {k: z[k].astype("float64") for k in z.files}
    t("scores loaded from cache")
else:
    for nm, y, kind in (("WF_R10", y_r, "regression"), ("WF_A10", y_a, "binary")):
        sc = L.walk_forward2(y, R1B, P, F, 10, kind=kind, features=FEATS, date_step=1, n_jobs=2,
                             min_train=2000, min_test=100, params=prm, verbose=True)
        scores[nm] = sc
        t(f"wf {nm} scored {np.isfinite(sc).sum()}")
    np.savez_compressed(cache, **{k: v.astype(np.float32) for k, v in scores.items()})
scores["EB_XR10"] = np.load(f"{L.LAB}/results/R2_rel/wf_h10_neumom_RANK.npz")["score"].astype("float64")
scores["EB_XR20"] = np.load(f"{L.LAB}/results/R2_rel/wf_h20_neumom_RANK.npz")["score"].astype("float64")
scores["DEPTH"] = -B["bdd10"].astype("float64")
scores["LIQ"] = B["log_turn20"].astype("float64")
THR = {"WF_R10": 0.0, "WF_A10": 0.5, "EB_XR10": 0.0, "EB_XR20": 0.0}

# ---------------- learnability inside the gate ----------------
learn = {}
for gname, g in (("A1", A1), ("A0", A0)):
    for sn, sc in scores.items():
        o = {}
        for h in (5, 10, 20):
            x, r = B[f"x{h}"].astype("float64"), B[f"r{h}"].astype("float64")
            xm = L.xs_metrics(sc, x, g, P, h, binary_target=np.where(np.isfinite(x), (x > 0).astype(float), np.nan))
            # date-weighted within-event IC on days with >= 10 events, month-cluster t
            m = g & np.isfinite(sc) & np.isfinite(x)
            df = pd.DataFrame({"d": didx[m], "s": sc[m], "x": x[m], "r": r[m]})
            df["n"] = df.groupby("d").s.transform("size")
            df = df[df.n >= 10]
            ic = df.groupby("d").apply(lambda q: q.s.rank().corr(q.x.rank()), include_groups=False).dropna()
            dd = S.cal[ic.index.values]
            mon = dd.astype("datetime64[M]").astype(np.int64)
            dev = (dd >= np.datetime64("2023-01-01")) & (dd <= np.datetime64("2025-12-31"))
            hold = dd >= np.datetime64("2026-01-01")
            o[h] = {"xs": xm,
                    "ic10_dev_mean": float(ic[dev].mean()) if dev.any() else None,
                    "ic10_dev_t_month": cluster_t(ic[dev].values, mon[dev])[0] if dev.sum() > 5 else None,
                    "ic10_dev_days": int(dev.sum()),
                    "ic10_hold_mean": float(ic[hold].mean()) if hold.any() else None,
                    "ic10_hold_t_month": cluster_t(ic[hold].values, mon[hold])[0] if hold.sum() > 5 else None,
                    "ic10_hold_days": int(hold.sum())}
            # PIT threshold lift (cross-date comparable scores only)
            if sn in THR:
                for wn, (a, b) in (("dev", ("2023-01-01", "2025-12-31")), ("hold", ("2026-01-01", "2100-01-01"))):
                    w = g & np.isfinite(sc) & np.isfinite(x) & (S.cal[didx] >= np.datetime64(a)) & (S.cal[didx] <= np.datetime64(b))
                    hi_ = w & (sc > THR[sn])
                    o[h][f"thr_{wn}"] = {"pass_share": float(hi_.sum() / max(w.sum(), 1)),
                                         "xs_all_bps": 1e4 * float(x[w].mean()), "xs_pass_bps": 1e4 * float(x[hi_].mean()) if hi_.any() else None,
                                         "xs_fail_bps": 1e4 * float(x[w & ~hi_].mean()) if (w & ~hi_).any() else None,
                                         "net_all_bps": 1e4 * float(r[w].mean() - 0.005),
                                         "net_pass_bps": 1e4 * float(r[hi_].mean() - 0.005) if hi_.any() else None}
        learn[f"{gname}|{sn}"] = o
    t(f"learn {gname}")
save("s4_learn", learn)

# ---------------- investability: top-scored vs all events ----------------
WIN = {"dev": dict(start=L.DEV[0], end_exit=L.DEV[1]), "hold": dict(start="2026-01-01", end_exit=None)}
SEEDS = (1, 2, 3, 4, 5)
rows = []
daily = {}
for gname, g in (("A1", A1), ("A0", A0)):
    for K in (10, 20):
        cnt_all = counts_by_g(g, None, didx, ncal, K)
        mm_all = [matched_mask(cnt_all, U, didx, s) for s in SEEDS]
        for h in (5, 10, 20):
            for cost in (50, 80):
                for wn, w in WIN.items():
                    kw = dict(step=1, top_k=K, cost_bps=cost, sizing="slot", **w)
                    rnd = summarize_runs([S.run(None, g, h, random_seed=s, **kw) for s in SEEDS])
                    mat = summarize_runs([S.run(None, mm, h, random_seed=s, **kw) for s, mm in zip(SEEDS, mm_all)])
                    for sn, sc in scores.items():
                        gm = g & np.isfinite(sc)
                        st = S.run(sc, gm, h, **kw)
                        e_r = excess_stats(st["_daily_ret"], rnd["_daily_ret"], h)
                        e_m = excess_stats(st["_daily_ret"], mat["_daily_ret"], h)
                        row = {"gate": gname, "score": sn, "variant": "topK", "K": K, "h": h, "cost": cost, "win": wn,
                               "cagr": st["cagr"], "sharpe": st["sharpe"], "max_dd": st["max_dd"], "exposure": st["exposure"],
                               "trades": st["trades"], "hit_rate": st["hit_rate"], "mean_trade_net": st["mean_trade_net"],
                               "by_year": st["by_year"], "rnd_cagr": rnd["cagr"], "rnd_sharpe": rnd["sharpe"],
                               "rnd_mean_trade_net": rnd["mean_trade_net"], "match_cagr": mat["cagr"],
                               "exc_vs_rnd_cagr": st["cagr"] - rnd["cagr"], "exc_vs_rnd_nw_t": e_r["excess_nw_t"],
                               "exc_vs_match_cagr": st["cagr"] - mat["cagr"], "exc_vs_match_nw_t": e_m["excess_nw_t"]}
                        rows.append(row)
                        if cost == 50 and K == 20:
                            daily[f"TOP|{gname}|{sn}|h{h}|{wn}"] = st["_daily_ret"]
                        if sn in THR:
                            gt = gm & (sc > THR[sn])
                            stt = summarize_runs([S.run(None, gt, h, random_seed=s, **kw) for s in SEEDS])
                            cnt_t = counts_by_g(gt, None, didx, ncal, K)
                            mat_t = summarize_runs([S.run(None, matched_mask(cnt_t, U, didx, s), h, random_seed=s, **kw)
                                                    for s in SEEDS])
                            e_r = excess_stats(stt["_daily_ret"], rnd["_daily_ret"], h)
                            e_m = excess_stats(stt["_daily_ret"], mat_t["_daily_ret"], h)
                            rows.append({"gate": gname, "score": sn, "variant": "thr", "K": K, "h": h, "cost": cost, "win": wn,
                                         "cagr": stt["cagr"], "sharpe": stt["sharpe"], "max_dd": stt["max_dd"],
                                         "exposure": stt["exposure"], "trades": stt["trades"], "hit_rate": stt["hit_rate"],
                                         "mean_trade_net": stt["mean_trade_net"], "by_year": stt["by_year"],
                                         "rnd_cagr": rnd["cagr"], "rnd_sharpe": rnd["sharpe"],
                                         "rnd_mean_trade_net": rnd["mean_trade_net"], "match_cagr": mat_t["cagr"],
                                         "exc_vs_rnd_cagr": stt["cagr"] - rnd["cagr"], "exc_vs_rnd_nw_t": e_r["excess_nw_t"],
                                         "exc_vs_match_cagr": stt["cagr"] - mat_t["cagr"], "exc_vs_match_nw_t": e_m["excess_nw_t"]})
                    if cost == 50 and K == 20:
                        daily[f"RND|{gname}|h{h}|{wn}"] = rnd["_daily_ret"]
                        daily[f"MAT|{gname}|h{h}|{wn}"] = mat["_daily_ret"]
            t(f"sim {gname} K={K} h={h}")
df = pd.DataFrame(rows)
df.to_pickle(f"{OUT}/s4_sim.pkl")
np.savez_compressed(f"{OUT}/s4_daily.npz", **{k: np.asarray(v) for k, v in daily.items()})
save("s4_sim", {"rows": df.to_dict("records")})
pd.set_option("display.width", 260)
cols = ["gate", "score", "variant", "K", "h", "cagr", "sharpe", "max_dd", "exposure", "mean_trade_net", "rnd_cagr",
        "exc_vs_rnd_cagr", "exc_vs_rnd_nw_t", "match_cagr", "exc_vs_match_cagr", "exc_vs_match_nw_t"]
for wn in ("dev", "hold"):
    print("=====", wn)
    print(df[(df.win == wn) & (df.cost == 50) & (df.K == 20)][cols].round(4).to_string())
t("done")
