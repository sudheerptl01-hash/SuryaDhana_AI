"""Stage 2: date-level market-timing signals.

(a) Single-feature diagnostics: Spearman of each PIT market feature with the next-20d executable
    Nifty-500 and EW-universe returns, NW t (lag 20), per window.
(b) Pre-declared parameter-free rules (state 1 = risk-on):
      R200  N500 close > 200d SMA          (mkt_dist_sma200 > 0)
      RBR   breadth50 > 0.5                 (share of liquid names above their 50d SMA)
      RVIX  India VIX < trailing-250d median (vix_rel < 0)
      RM60  N500 60d momentum > 0           (mkt_mom60 > 0)
      VOTE  graded exposure = (#rules on)/4
(c) Walk-forward models (yearly expanding folds 2023..2026, embargo h+2 = 22 trading days,
    train from 2021-01-01 on dates with complete features+target; every test-year date scored):
      LOG4  L2 logistic (C=0.1, standardized) on [mkt_dist_sma200, breadth50, vix_rel, mkt_mom60]
      LOG10 L2 logistic (C=0.1) on the 10 lab market features
      LGB10 LightGBM depth-2, 100 trees, lr 0.05, min_child 60, on the 10 features
    x 3 targets: N0 = 1{N500 f20 > 0}, N1 = 1{N500 f20 > +1%}, E0 = 1{EW-universe f20 > 0}.
    Risk-on state = 1{p >= 0.5} (pre-declared; no threshold tuning).
All selection is on DEV (2023-2025); 2026 and PRE (2021-09..2022-12, rules only) are reported.
"""
import time
import warnings

import numpy as np
import pandas as pd

from common import OUT, L, save, MKT_FEATS, nw_corr_t, nw_mean_diff_t, auc, flips_per_year

warnings.filterwarnings("ignore")
t0 = time.time()
D = pd.read_parquet(f"{OUT}/dateset.parquet")
cal = D.index.values.astype("datetime64[D]")
H = 20
WIN = {"PRE": ("2021-09-01", "2022-12-31"), "DEV": ("2023-01-01", "2025-12-31"),
       "HOLD": ("2026-01-01", "2026-12-31")}


def wmask(name, idx=D.index):
    a, b = WIN[name]
    return (idx >= a) & (idx <= b)


targets = {
    "N0": np.where(np.isfinite(D.n500_f20), (D.n500_f20 > 0).astype(float), np.nan),
    "N1": np.where(np.isfinite(D.n500_f20), (D.n500_f20 > 0.01).astype(float), np.nan),
    "E0": np.where(np.isfinite(D.ew_f20), (D.ew_f20 > 0).astype(float), np.nan),
}
rets = {"n500": D.n500_f20.values, "ew": D.ew_f20.values}

# ------------------------------------------------------------------ (a) single features
FEATS = MKT_FEATS + ["vix_rel"]
single = {}
for f in FEATS:
    single[f] = {}
    for w in WIN:
        m = wmask(w)
        rec = {}
        for rn, rv in rets.items():
            rho, t = nw_corr_t(D[f].values[m], rv[m], H)
            rec[f"rho_{rn}"], rec[f"t_{rn}"] = rho, t
        single[f][w] = rec
save("s2_single_feature", single)

# ------------------------------------------------------------------ (b) rules
S = pd.DataFrame(index=D.index)


def st(cond, feat):
    return np.where(np.isfinite(D[feat].values), cond.astype(float), np.nan)


S["R200"] = st(D.mkt_dist_sma200.values > 0, "mkt_dist_sma200")
S["RBR"] = st(D.breadth50.values > 0.5, "breadth50")
S["RVIX"] = st(D.vix_rel.values < 0, "vix_rel")
S["RM60"] = st(D.mkt_mom60.values > 0, "mkt_mom60")
S["VOTE"] = S[["R200", "RBR", "RVIX", "RM60"]].mean(axis=1, skipna=False)

# ------------------------------------------------------------------ (c) walk-forward models
from sklearn.linear_model import LogisticRegression  # noqa: E402
import lightgbm as lgb  # noqa: E402

F4 = ["mkt_dist_sma200", "breadth50", "vix_rel", "mkt_mom60"]
F10 = list(MKT_FEATS)
MODELS = {"LOG4": ("log", F4), "LOG10": ("log", F10), "LGB10": ("lgb", F10)}
fold_info = {}
for mname, (kind, feats) in MODELS.items():
    X = D[feats].values.astype(float)
    xok = np.isfinite(X).all(1)
    for tn, y in targets.items():
        p = np.full(len(D), np.nan)
        coefs = {}
        for Y in (2023, 2024, 2025, 2026):
            ts = np.datetime64(f"{Y}-01-01")
            te = np.datetime64(f"{Y + 1}-01-01")
            ti = int(np.searchsorted(cal, ts))
            cutoff = cal[max(0, ti - H - 2)]
            tr = xok & np.isfinite(y) & (cal < cutoff) & (cal >= np.datetime64("2021-01-01"))
            tm = xok & (cal >= ts) & (cal < te)
            if tr.sum() < 150 or tm.sum() == 0:
                continue
            Xtr, ytr = X[tr], y[tr].astype(int)
            if kind == "log":
                mu, sd = Xtr.mean(0), Xtr.std(0)
                sd[sd == 0] = 1
                mdl = LogisticRegression(C=0.1, max_iter=2000)
                mdl.fit((Xtr - mu) / sd, ytr)
                p[tm] = mdl.predict_proba((X[tm] - mu) / sd)[:, 1]
                coefs[Y] = {"n_train": int(tr.sum()), "base_rate": float(ytr.mean()),
                            "intercept": float(mdl.intercept_[0]),
                            **{f: float(c) for f, c in zip(feats, mdl.coef_[0])}}
            else:
                mdl = lgb.LGBMClassifier(n_estimators=100, learning_rate=0.05, num_leaves=4, max_depth=2,
                                         min_child_samples=60, subsample=0.8, subsample_freq=1,
                                         colsample_bytree=0.8, reg_lambda=5.0, n_jobs=2, verbose=-1,
                                         random_state=0)
                mdl.fit(Xtr, ytr)
                p[tm] = mdl.predict_proba(X[tm])[:, 1]
                g = mdl.booster_.feature_importance("gain").astype(float)
                coefs[Y] = {"n_train": int(tr.sum()), "base_rate": float(ytr.mean()),
                            **{f: float(v) for f, v in zip(feats, g / max(g.sum(), 1e-12))}}
        nm = f"{mname}_{tn}"
        S[f"p_{nm}"] = p
        S[nm] = np.where(np.isfinite(p), (p >= 0.5).astype(float), np.nan)
        fold_info[nm] = coefs
save("s2_model_folds", fold_info)

# ------------------------------------------------------------------ evaluation of every signal
sig_names = ["R200", "RBR", "RVIX", "RM60", "VOTE"] + [f"{m}_{t}" for m in MODELS for t in targets]
ev = {}
for sn in sig_names:
    ev[sn] = {}
    state = S[sn].values
    score = S[f"p_{sn}"].values if f"p_{sn}" in S else state
    for w in WIN:
        m = wmask(w) & np.isfinite(state)
        if m.sum() < 40:
            continue
        rec = {"dates": int(m.sum()), "on_share": float(np.mean(state[m])),
               "flips_per_yr": flips_per_year(state[m], cal[m])}
        for tn, y in targets.items():
            rec[f"auc_{tn}"] = auc(score[m], y[m])
        for rn, rv in rets.items():
            ok = m & np.isfinite(rv)
            b, t = nw_mean_diff_t(rv[ok], state[ok], H)
            rec[f"{rn}_f20_on_minus_off"], rec[f"{rn}_t"] = b, t
            on = ok & (state >= 0.5)
            off = ok & (state < 0.5)
            rec[f"{rn}_f20_mean_on"] = float(np.mean(rv[on])) if on.any() else np.nan
            rec[f"{rn}_f20_mean_off"] = float(np.mean(rv[off])) if off.any() else np.nan
            rho, tr_ = nw_corr_t(score[ok], rv[ok], H)
            rec[f"rho_score_{rn}"], rec[f"rho_t_{rn}"] = rho, tr_
        # by year AUC on own-relevant targets
        ev[sn][w] = rec
    by = {}
    for Y in range(2021, 2027):
        m = (D.index.year == Y) & np.isfinite(state)
        if m.sum() < 40:
            continue
        by[Y] = {"on_share": float(np.mean(state[m])),
                 "auc_N0": auc(score[m], targets["N0"][m]), "auc_E0": auc(score[m], targets["E0"][m]),
                 "n500_on_minus_off": nw_mean_diff_t(rets["n500"][m], state[m], H)[0],
                 "ew_on_minus_off": nw_mean_diff_t(rets["ew"][m], state[m], H)[0]}
    ev[sn]["by_year"] = by
save("s2_signal_eval", ev)
S.to_parquet(f"{OUT}/timing_signals.parquet")

# quick print
for sn in sig_names:
    d = ev[sn].get("DEV", {})
    h_ = ev[sn].get("HOLD", {})
    print(f"{sn:10s} DEV on {d.get('on_share', np.nan):.2f} flips {d.get('flips_per_yr', np.nan):5.1f} "
          f"aucN0 {d.get('auc_N0', np.nan):.3f} aucE0 {d.get('auc_E0', np.nan):.3f} "
          f"n500 on-off {d.get('n500_f20_on_minus_off', np.nan)*100:+.2f}% t {d.get('n500_t', np.nan):+.2f} "
          f"ew on-off {d.get('ew_f20_on_minus_off', np.nan)*100:+.2f}% t {d.get('ew_t', np.nan):+.2f} | "
          f"HOLD on {h_.get('on_share', np.nan):.2f} aucN0 {h_.get('auc_N0', np.nan):.3f} "
          f"ew on-off {h_.get('ew_f20_on_minus_off', np.nan)*100:+.2f}%", flush=True)
for f in FEATS:
    d = single[f]["DEV"]
    print(f"{f:16s} DEV rho_n500 {d['rho_n500']:+.3f} (t {d['t_n500']:+.2f}) rho_ew {d['rho_ew']:+.3f} "
          f"(t {d['t_ew']:+.2f}) | PRE rho_n500 {single[f]['PRE']['rho_n500']:+.3f} | HOLD rho_n500 "
          f"{single[f]['HOLD']['rho_n500']:+.3f}")
print("total", round(time.time() - t0, 1))
