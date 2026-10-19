"""R3_verify_R3_risk v2: own drawdown episodes, monthly stats, block-bootstrap expectations and kill-rule
calibration (joint excess + IC), plus single-phase (live-like) variants. Inputs: v1_series.npz, v3_ic.npz."""
import json
import sys

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = LAB + "/results/R3_verify_R3_risk"
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402

z = np.load(f"{OUT}/v1_series.npz")
icz = np.load(f"{OUT}/v3_ic.npz")


def S_(k):
    return pd.Series(z[k], index=pd.DatetimeIndex(z[k + "_dates"]))


out = {}
# ================= drawdown anatomy (contiguous) =================
b, r, e = S_("contig_book"), S_("contig_rand"), S_("contig_ew")
idx = b.index
eqb, eqr, eqe = (1 + b).cumprod(), (1 + r).cumprod(), (1 + e).cumprod()
n5 = L.market_series("Nifty 500")["close"].astype(float)
n5c = n5.reindex(idx)
out["n500_missing_on_book_calendar"] = int(n5c.isna().sum())
idx_only = n5.index[(n5.index >= idx[0]) & (n5.index <= idx[-1])].difference(idx)
out["n500_dates_not_in_book_calendar"] = [str(x)[:10] for x in idx_only]
n5c = n5c.ffill()


def episodes(eq):
    v = eq.values
    cm = np.maximum.accumulate(v)
    under = v < cm
    eps, i, n = [], 0, len(v)
    while i < n:
        if not under[i]:
            i += 1
            continue
        j = i
        while j < n and under[j]:
            j += 1
        pk, tr = i - 1, i + int(np.argmin(v[i:j]))
        eps.append({"peak": pk, "trough": tr, "rec": (j if j < n else None), "depth": float(v[tr] / v[pk] - 1)})
        i = j
    return sorted(eps, key=lambda x: x["depth"])


eps = episodes(eqb)[:5]
top = []
for ep in eps:
    pk, tr, rc = ep["peak"], ep["trough"], ep["rec"]
    top.append({"peak": str(idx[pk].date()), "trough": str(idx[tr].date()),
                "recovery": (str(idx[rc].date()) if rc is not None else None), "depth": ep["depth"],
                "days_pt": tr - pk, "days_rec": (rc - pk if rc is not None else None),
                "random": float(eqr.iloc[tr] / eqr.iloc[pk] - 1), "ew": float(eqe.iloc[tr] / eqe.iloc[pk] - 1),
                "n500_levels": float(n5c.iloc[tr] / n5c.iloc[pk] - 1)})
out["top5"] = top


def mdd(eq):
    v = np.asarray(eq, float)
    return float((v / np.maximum.accumulate(v) - 1).min())


out["contig_maxdd"] = {"book": mdd(eqb), "random": mdd(eqr), "ew": mdd(eqe), "n500_levels": mdd(n5c.values)}
# ================= monthly =================
mon = lambda x: (1 + x).groupby(x.index.to_period("M")).prod() - 1  # noqa: E731
n5r = n5.pct_change().reindex(idx).fillna(0.0)
M = pd.DataFrame({"book": mon(b), "rand": mon(r), "ew": mon(e), "n5": mon(n5r)})
M = M[M.index <= pd.Period("2026-09", "M")]
# month-end level based Nifty 500 (independent of reindexing)
me = n5.groupby(n5.index.to_period("M")).last()
M["n5_lvl"] = (me / me.shift(1) - 1).reindex(M.index)
dev_m, h_m = M[M.index.year <= 2025], M[M.index.year == 2026]
down = M[M.n5 < -0.03]
down_l = M[M.n5_lvl < -0.03]
out["monthly"] = {"n": int(len(M)), "first": str(M.index[0]), "mean": float(M.book.mean()), "sd": float(M.book.std()),
                  "min": float(M.book.min()), "min_month": str(M.book.idxmin()),
                  "beat_rand_dev": float((dev_m.book > dev_m.rand).mean()), "n_dev": int(len(dev_m)),
                  "beat_rand_2026": float((h_m.book > h_m.rand).mean()), "n_2026": int(len(h_m)),
                  "down_n": int(len(down)), "down_book": float(down.book.mean()), "down_n5": float(down.n5.mean()),
                  "down_beat_rand": float((down.book > down.rand).mean()),
                  "down_lvl_n": int(len(down_l)), "down_lvl_book": float(down_l.book.mean()),
                  "down_lvl_n5": float(down_l.n5_lvl.mean()), "n5_monthly_sd": float(M.n5.std())}
# excess by year sums, Q4-2025
ex_c = b - r
out["excess_sum_by_year"] = {int(y): float(g.sum()) for y, g in ex_c.groupby(ex_c.index.year)}
out["excess_2025Q4"] = float(ex_c[(ex_c.index >= "2025-10-01") & (ex_c.index <= "2025-12-31")].sum())
print(json.dumps({k: out[k] for k in ("top5", "contig_maxdd", "monthly", "excess_sum_by_year", "excess_2025Q4",
                                      "n500_missing_on_book_calendar", "n500_dates_not_in_book_calendar")}, indent=1), flush=True)

# ================= bootstrap: expectations =================
rng = np.random.default_rng(777)
NP, LEN = 10000, 504


def cbb(n, bl):
    nb = -(-LEN // bl)
    st = rng.integers(0, n, (NP, nb))
    return ((st[:, :, None] + np.arange(bl)[None, None, :]) % n).reshape(NP, -1)[:, :LEN]


def stationary(n, mean_bl):
    """Politis-Romano stationary bootstrap index paths."""
    p = 1.0 / mean_bl
    idxp = np.empty((NP, LEN), dtype=np.int64)
    idxp[:, 0] = rng.integers(0, n, NP)
    newb = rng.random((NP, LEN)) < p
    jump = rng.integers(0, n, (NP, LEN))
    for t in range(1, LEN):
        idxp[:, t] = np.where(newb[:, t], jump[:, t], (idxp[:, t - 1] + 1) % n)
    return idxp


ex_dev = S_("dev_book") - S_("dev_rand")
ew_dev = S_("dev_ew")
out["dev_excess_ann"] = float(ex_dev.mean() * 252)
out["te_phaseavg_dev"] = float(ex_dev.std() * np.sqrt(252))
# single-phase excess: phase-k book minus the phase-averaged random (25 random books ~ the random expectation)
ph_ex = []
for k in range(5):
    bk = S_(f"dev_phase{k}_book")
    rr_ = S_("dev_rand")
    c = bk.index.intersection(rr_.index)
    ph_ex.append(bk.reindex(c) - rr_.reindex(c))
out["te_single_phase_dev"] = [float(x.std() * np.sqrt(252)) for x in ph_ex]
out["te_single_phase_own_random_dev"] = [float(S_(f"dev_phase{k}_ex").std() * np.sqrt(252)) for k in range(5)]
out["single_phase_excess_ann_dev"] = [float(x.mean() * 252) for x in ph_ex]


def expect(exs, ews=None, bl=40, method="cbb"):
    v = exs.values - exs.values.mean()
    I = cbb(len(v), bl) if method == "cbb" else stationary(len(v), bl)
    res = {}
    for tgt in (0.05, 0.0):
        x = v[I] + tgt / 252
        e12 = x[:, :252].sum(1)
        res[f"t{int(tgt * 100)}"] = {"p_neg_12m": float((e12 < 0).mean()), "sd_12m": float(e12.std()),
                                     "p_above5_12m": float((e12 > 0.05).mean()),
                                     "p5_12m": float(np.percentile(e12, 5)), "p95_12m": float(np.percentile(e12, 95))}
        if ews is not None and tgt == 0.05:
            w = ews.reindex(exs.index).fillna(0.0).values
            ab = w[I] + x
            eq = np.cumprod(1 + ab, 1)
            res["abs"] = {"p_loss_12m": float((eq[:, 251] < 1).mean()),
                          "median_maxdd_24m": float(np.median((eq / np.maximum.accumulate(eq, 1) - 1).min(1)))}
    return res


out["boot_cbb40_phaseavg"] = expect(ex_dev, ew_dev, 40, "cbb")
out["boot_stat40_phaseavg"] = expect(ex_dev, None, 40, "stationary")
out["boot_cbb40_single_phase"] = [expect(x, None, 40, "cbb") for x in ph_ex]
print("expectations", json.dumps({k: out[k] for k in ("dev_excess_ann", "te_phaseavg_dev", "te_single_phase_dev",
                                                      "te_single_phase_own_random_dev", "boot_cbb40_phaseavg",
                                                      "boot_stat40_phaseavg")}, indent=1), flush=True)

# ================= kill rules (joint excess + IC) =================
IC = pd.Series(icz["ic"], index=pd.DatetimeIndex(icz["dates"]))
IC_dev = IC[IC.index <= "2025-12-02"].dropna()
icm = float(IC_dev.mean())
icb = icm * 0.05 / out["dev_excess_ann"]
checks = np.arange(5, LEN + 1, 5)


def rules(x, ic):
    """x, ic: (NP, LEN). Returns dict of (NP, nchecks) bool."""
    cx = np.concatenate([np.zeros((x.shape[0], 1)), x.cumsum(1)], 1)
    ci = np.concatenate([np.zeros((x.shape[0], 1)), ic.cumsum(1)], 1)
    K1 = np.zeros((x.shape[0], len(checks)), bool)
    K2 = np.zeros_like(K1)
    K3 = np.zeros_like(K1)
    for j, t in enumerate(checks):          # t days have elapsed (days 0..t-1)
        if t >= 126:
            K1[:, j] = (cx[:, t] - cx[:, t - 126]) < -0.05
        if t >= 252:
            K3[:, j] = (cx[:, t] - cx[:, t - 252]) < 0
        hi = t - 21                          # latest signal day whose 20d label has matured by day t-1
        lo = hi - 62
        if lo >= 0:
            K2[:, j] = (ci[:, hi + 1] - ci[:, lo]) / 63 < 0.02
    return {"K1": K1, "K2": K2, "K3": K3, "C1": K1 | K2 | K3, "C2": K3 & K2, "C3": K1 & K2}


def fire_stats(Rm):
    o = {}
    for k, M_ in Rm.items():
        anyf = M_.any(1)
        first = np.where(anyf, checks[np.argmax(M_, 1)], np.nan)
        o[k] = {"p24": float(anyf.mean()), "median_days": (float(np.nanmedian(first)) if anyf.any() else None)}
    return o


def kill(exs, bl=40):
    J = pd.concat([exs.rename("x"), IC_dev.rename("ic")], axis=1, join="inner").dropna()
    xv, iv = J.x.values - J.x.values.mean(), J.ic.values - J.ic.values.mean()
    I = cbb(len(xv), bl)
    res = {"n_rows": int(len(J))}
    for hn, (te_, ti_) in {"H1a": (0.05, icm), "H1b": (0.05, icb), "H0": (0.0, 0.0)}.items():
        res[hn] = fire_stats(rules(xv[I] + te_ / 252, iv[I] + ti_))
    return res


out["ic_dev_mean"], out["ic_h1b"] = icm, icb
out["kill_cbb40_phaseavg"] = kill(ex_dev, 40)
print("kill phase-avg", json.dumps(out["kill_cbb40_phaseavg"]), flush=True)
out["kill_cbb40_single_phase"] = [kill(x, 40) for x in ph_ex]
agg = {}
for hn in ("H1a", "H1b", "H0"):
    agg[hn] = {k: float(np.mean([kk[hn][k]["p24"] for kk in out["kill_cbb40_single_phase"]])) for k in ("K1", "K2", "K3", "C1", "C2", "C3")}
out["kill_single_phase_mean_p24"] = agg
print("kill single-phase mean", json.dumps(agg), flush=True)

# ================= historical rule behaviour on the actual contiguous book =================
ICc = IC.reindex(idx)
cs = ex_c.cumsum().values
rows = []
for j in range(4, len(ex_c), 5):
    r6 = cs[j] - cs[j - 126] if j >= 126 else np.nan
    r12 = cs[j] - cs[j - 252] if j >= 252 else np.nan
    w = ICc.values[max(j - 20 - 62, 0):j - 20 + 1] if j - 20 - 62 >= 0 else np.array([np.nan])
    ic3 = np.nanmean(w) if np.isfinite(w).sum() >= 50 else np.nan
    rows.append((idx[j], r6, r12, ic3))
Hh = pd.DataFrame(rows, columns=["d", "r6", "r12", "ic3"]).set_index("d")
out["hist"] = {"K1_dates": [str(x.date()) for x in Hh.index[Hh.r6 < -0.05]],
               "K2_dates": [str(x.date()) for x in Hh.index[Hh.ic3 < 0.02]],
               "K3_dates": [str(x.date()) for x in Hh.index[Hh.r12 < 0]],
               "min_r12": float(Hh.r12.min()), "min_ic3": float(Hh.ic3.min()),
               "last": {"date": str(Hh.index[-1].date()), "r6": float(Hh.r6.iloc[-1]), "r12": float(Hh.r12.iloc[-1]),
                        "ic3": float(Hh.ic3.iloc[-1])}}
print("hist", json.dumps(out["hist"]), flush=True)
with open(f"{OUT}/v2_out.json", "w") as fh:
    json.dump(out, fh, indent=1, default=float)
print("done")
