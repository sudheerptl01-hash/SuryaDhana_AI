"""R3_risk items 3 + 4: circular block bootstrap (dependence-preserving) of the phase-averaged daily
excess (PROD book - 5-seed random) jointly with the daily matured rank IC, shifted to planning means.
  item 3: 6/12/24-month excess distribution, P(negative excess year), absolute ranges (EW + excess)
  item 4: kill/review rules K1 (6m excess < -5%), K2 (3m mean matured IC < 0.02), K3 (12m excess < 0),
          C1 = any, C2 = K3 & K2, C3 = K1 & K2; weekly checks over 24 months; false alarm under H1a/H1b,
          detection under H0; plus their historical behaviour on the actual 2023-2026 book.
An iid bootstrap (block = 1) is computed ONLY as an illustration of the dependence bias."""
import sys

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
import r3common as C  # noqa: E402

OUT = C.set_agent("R3_risk")
z = np.load(f"{OUT}/pa_series.npz")
icz = np.load(f"{OUT}/ic_series.npz")
mon = C.load_res()["item4_monitor_metrics"]
dev_last_sig = mon["dev_last_signal_date_with_matured_label"]


def S_(key):
    return pd.Series(z[key], index=pd.DatetimeIndex(z[key + "_dates"]))


ex_dev = S_("dev_c50_book") - S_("dev_c50_rand")
ew_dev = S_("dev_c50_ew")
ex_con = S_("contig_c50_book") - S_("contig_c50_rand")
ew_con = S_("contig_c50_ew")
IC = pd.Series(icz["ic"], index=pd.DatetimeIndex(icz["dates"]))
IC_dev = IC[(IC.index <= dev_last_sig)].dropna()
ic_dev_mean = float(IC_dev.mean())
dev_ex_ann = float(ex_dev.mean() * 252)
PLAN = 0.05
ic_h1b = ic_dev_mean * PLAN / dev_ex_ann
C.log("DEV excess ann", dev_ex_ann, "IC dev mean", ic_dev_mean, "IC H1b", ic_h1b)

NP = 10000
L = 504
rng = np.random.default_rng(20261015)


def cbb(n, b, npaths=NP, length=L):
    nb = int(np.ceil(length / b))
    st = rng.integers(0, n, size=(npaths, nb))
    idx = (st[:, :, None] + np.arange(b)[None, None, :]) % n
    return idx.reshape(npaths, nb * b)[:, :length]


def pct(x, qs=(5, 25, 50, 75, 95)):
    return {f"p{q}": float(np.percentile(x, q)) for q in qs}


# ======================= item 3: expectations =======================
exp = {"dev_excess_ann_observed": dev_ex_ann, "contig_excess_ann_observed": float(ex_con.mean() * 252),
       "iid_tracking_error_dev": float(ex_dev.std() * np.sqrt(252)),
       "iid_tracking_error_contig": float(ex_con.std() * np.sqrt(252)),
       "ew_dev_cagr": float((1 + ew_dev).prod() ** (252 / len(ew_dev)) - 1),
       "ew_contig_cagr": float((1 + ew_con).prod() ** (252 / len(ew_con)) - 1),
       "excess_autocorr_dev": {k: float(ex_dev.autocorr(k)) for k in (1, 5, 10, 20, 40)}}
for src, exs, ews in (("dev", ex_dev, ew_dev), ("contig", ex_con, ew_con)):
    exv = exs.values - exs.values.mean()
    ewv = ews.reindex(exs.index).fillna(0.0).values
    for b in ((1, 20, 40, 60) if src == "dev" else (40,)):
        idx = cbb(len(exv), b)
        for tgt in (PLAN, 0.0):
            x = exv[idx] + tgt / 252
            cs = np.cumsum(x, 1)
            e6, e12, e24 = cs[:, 125], cs[:, 251], cs[:, 503]
            y2 = e24 - e12
            rec = {"excess_6m": {**pct(e6), "p_neg": float((e6 < 0).mean()), "sd": float(e6.std())},
                   "excess_12m": {**pct(e12), "p_neg": float((e12 < 0).mean()), "sd": float(e12.std()),
                                  "p_below_minus5": float((e12 < -0.05).mean()), "p_above_plus5": float((e12 > 0.05).mean())},
                   "excess_24m": {**pct(e24), "p_neg": float((e24 < 0).mean()), "sd": float(e24.std())},
                   "p_negative_excess_year": float((e12 < 0).mean()),
                   "p_at_least_one_negative_year_in_2": float(((e12 < 0) | (y2 < 0)).mean())}
            if b == 40 or (src == "dev" and b in (20, 60)):
                ab = ewv[idx] + x                      # absolute = EW universe + shifted excess (joint blocks)
                eq = np.cumprod(1 + ab, 1)
                a12 = eq[:, 251] - 1
                a24 = eq[:, 503] ** 0.5 - 1
                dd = (eq / np.maximum.accumulate(eq, 1) - 1).min(1)
                eqe = np.cumprod(1 + ewv[idx], 1)
                rec["absolute_12m"] = {**pct(a12), "p_neg": float((a12 < 0).mean())}
                rec["absolute_24m_annualised"] = {**pct(a24), "p_neg": float((a24 < 0).mean())}
                rec["maxdd_24m"] = {**pct(dd), "p_worse_than_minus20": float((dd < -0.20).mean()),
                                    "p_worse_than_minus30": float((dd < -0.30).mean())}
                rec["ew_alone_12m"] = {**pct(eqe[:, 251] - 1), "p_neg": float((eqe[:, 251] < 1).mean())}
            exp[f"{src}_b{b}_t{int(tgt * 100)}"] = rec
            C.log(src, b, tgt, "e12", C.short(rec["excess_12m"]), "pneg_year", round(rec["p_negative_excess_year"], 3))
C.save("item3_expectations", exp)

# ======================= item 4: kill rules (joint excess + IC) =======================
CHK = np.arange(5, L + 1, 5)          # check days (1-based count of live trading days)
RULES = ("K1", "K2", "K3", "C1_review", "C2_kill", "C3_kill_fast")


def rule_matrix(x, icp):
    """x, icp: (npaths, L) daily excess and IC (IC of signal day k, matured at k+20).
    Returns dict rule -> bool (npaths, len(CHK))."""
    n = x.shape[0]
    cs = np.c_[np.zeros(n), np.cumsum(x, 1)]
    ci = np.c_[np.zeros(n), np.cumsum(icp, 1)]
    T = CHK
    k1 = np.where(T >= 126, (cs[:, T] - cs[:, np.maximum(T - 126, 0)]) < -0.05, False)
    k3 = np.where(T >= 252, (cs[:, T] - cs[:, np.maximum(T - 252, 0)]) < 0.0, False)
    te = T - 20
    k2 = np.where(te >= 63, (ci[:, np.maximum(te, 0)] - ci[:, np.maximum(te - 63, 0)]) / 63 < 0.02, False)
    return {"K1": k1, "K2": k2, "K3": k3, "C1_review": k1 | k2 | k3, "C2_kill": k3 & k2, "C3_kill_fast": k1 & k2}


def first_fire(M):
    any_ = M.any(1)
    ff = np.where(any_, CHK[np.argmax(M, 1)], np.inf)
    return ff


def summarise(R):
    out = {}
    for k, M in R.items():
        ff = first_fire(M)
        fired = np.isfinite(ff)
        out[k] = {"p_fire_12m": float((ff <= 252).mean()), "p_fire_24m": float((ff <= 504).mean()),
                  "median_first_fire_days": float(np.median(ff[fired])) if fired.any() else None,
                  "p25_first_fire_days": float(np.percentile(ff[fired], 25)) if fired.any() else None,
                  "share_of_checks_on": float(M[:, CHK >= 252].mean())}
    return out


# joint DEV rows (excess day d, IC of signal day d)
J = pd.concat([ex_dev.rename("ex"), IC_dev.rename("ic")], axis=1, join="inner").dropna()
exj, icj = J.ex.values - J.ex.values.mean(), J.ic.values - J.ic.values.mean()
corr_ex_ic = float(np.corrcoef(pd.Series(J.ex.values).rolling(20).sum().values[19:],
                               J.ic.values[19:])[0, 1])
kill = {"joint_rows": int(len(J)), "first": str(J.index[0].date()), "last": str(J.index[-1].date()),
        "ic_dev_mean": ic_dev_mean, "ic_target_H1a": ic_dev_mean, "ic_target_H1b": ic_h1b,
        "corr_20d_excess_vs_ic": corr_ex_ic, "plan_excess": PLAN, "check_every_days": 5, "horizon_days": L}
HYP = {"H1a": (PLAN, ic_dev_mean), "H1b": (PLAN, ic_h1b), "H0": (0.0, 0.0)}
for b in (1, 20, 40, 60):
    idx = cbb(len(exj), b)
    for hname, (te_, ti_) in HYP.items():
        R = rule_matrix(exj[idx] + te_ / 252, icj[idx] + ti_)
        kill[f"b{b}_{hname}"] = summarise(R)
        C.log("kill", b, hname, {k: (round(v["p_fire_24m"], 3), v["median_first_fire_days"]) for k, v in kill[f"b{b}_{hname}"].items()})
C.save("item4_kill_bootstrap", kill)

# ---- historical behaviour of the rules on the actual contiguous book (weekly checks)
cal_all = pd.DatetimeIndex(icz["dates"])                 # all trading days from 2023-01-02 (IC calendar)
ex_c = ex_con
csum = ex_c.cumsum()
hist_rows = []
pos_all = {d: i for i, d in enumerate(cal_all)}
ICv = IC.reindex(cal_all).values
for j in range(4, len(ex_c), 5):
    T = ex_c.index[j]
    r6 = float(csum.iloc[j] - csum.iloc[j - 126]) if j >= 126 else np.nan
    r12 = float(csum.iloc[j] - csum.iloc[j - 252]) if j >= 252 else np.nan
    p = pos_all.get(T)
    ic3 = np.nan
    if p is not None and p - 20 >= 62:
        w = ICv[p - 20 - 62:p - 20 + 1]
        ic3 = float(np.nanmean(w)) if np.isfinite(w).sum() >= 50 else np.nan
    hist_rows.append((T, r6, r12, ic3))
Hh = pd.DataFrame(hist_rows, columns=["date", "ex6m", "ex12m", "ic3m"]).set_index("date")
Hh["K1"] = Hh.ex6m < -0.05
Hh["K2"] = Hh.ic3m < 0.02
Hh["K3"] = Hh.ex12m < 0
Hh["C1_review"] = Hh.K1 | Hh.K2 | Hh.K3
Hh["C2_kill"] = Hh.K3 & Hh.K2
Hh["C3_kill_fast"] = Hh.K1 & Hh.K2
hist = {}
for k in RULES:
    s = Hh[k]
    hist[k] = {"dev_share_checks_on": float(s[s.index.year <= 2025].mean()),
               "hold_share_checks_on": float(s[s.index.year == 2026].mean()),
               "first_fire": (str(s[s].index[0].date()) if s.any() else None),
               "fire_dates_2026": [str(x.date()) for x in s[(s.index.year == 2026) & s].index],
               "fire_dates_dev": [str(x.date()) for x in s[(s.index.year <= 2025) & s].index],
               "on_at_last_check": bool(s.iloc[-1])}
last = Hh.iloc[-1]
hist["last_check"] = {"date": str(Hh.index[-1].date()), "ex6m": float(last.ex6m), "ex12m": float(last.ex12m),
                      "ic3m": (float(last.ic3m) if np.isfinite(last.ic3m) else None)}
hist["min_values"] = {"ex6m_min": float(Hh.ex6m.min()), "ex6m_min_date": str(Hh.ex6m.idxmin().date()),
                      "ex12m_min": float(Hh.ex12m.min()), "ex12m_min_date": str(Hh.ex12m.idxmin().date()),
                      "ic3m_min": float(Hh.ic3m.min()), "ic3m_min_date": str(Hh.ic3m.idxmin().date())}
hist["series_weekly"] = {"dates": [str(x.date()) for x in Hh.index], "ex6m": Hh.ex6m.tolist(),
                         "ex12m": Hh.ex12m.tolist(), "ic3m": Hh.ic3m.tolist()}
C.log("historical", C.short({k: v for k, v in hist.items() if k != "series_weekly"}))
C.save("item4_kill_historical", hist)
C.log("done")
