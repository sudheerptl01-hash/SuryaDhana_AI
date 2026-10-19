"""R2_alpha shared helpers: alpha source & ensemble study on lab v2.

Paths, results.json persistence (file-locked), feature groups for the ablation, per-date ranking
helpers, a verbatim copy of L.walk_forward2 that additionally records per-fold gain importance,
and a fast per-date cross-sectional metric routine (identical maths to L.xs_metrics).
"""
import fcntl
import json
import os
import sys

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = os.path.join(LAB, "results", "R2_alpha")
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402

RES = os.path.join(OUT, "results.json")
H = 20
DEV = L.DEV
HOLD = ("2026-01-01", None)

# --------------------------------------------------------------------------- feature groups
# Disjoint partition of the 52 PIT features in L.FEATURES (age is never dropped).
GROUPS = {
    "momentum": ["mom_5", "mom_10", "mom_20", "mom_60", "mom_120", "mom_12_1",
                 "dist_sma20", "dist_sma50", "dist_sma200", "rel_mom20", "rel_mom60"],
    "volrisk": ["vol_20", "vol_60", "vol_ratio", "atr_pct", "beta_60", "idio_vol_60",
                "max_ret_20", "min_ret_20"],
    "volume": ["volz_20", "log_turn20"],
    "delivery": ["deliv_pct", "deliv_z20", "deliv_ratio", "xr_deliv_z"],
    "market": ["mkt_mom5", "mkt_mom20", "mkt_mom60", "mkt_dist_sma50", "mkt_dist_sma200",
               "mkt_vol20", "vix", "breadth50", "breadth_ad", "dispersion"],
    "xsrank": ["xr_mom20", "xr_mom60", "xr_mom120", "xr_vol20", "xr_volz", "xr_dist_sma50", "xr_hi52"],
    "technical": ["rsi_14", "range_pos", "hl_range", "gap_open", "intraday",
                  "hi52_dist", "lo52_dist", "hi20_dist", "up_frac_20"],
    "other": ["age"],
}
_all = sum(GROUPS.values(), [])
assert sorted(_all) == sorted(L.FEATURES) and len(_all) == len(set(_all)) == 52, "groups must partition FEATURES"
FEAT_GROUP = {f: g for g, fs in GROUPS.items() for f in fs}
ABLATE = ["momentum", "volrisk", "volume", "delivery", "market", "xsrank", "technical"]


def feats_without(group):
    return [f for f in L.FEATURES if FEAT_GROUP[f] != group]


# --------------------------------------------------------------------------- persistence
def _clean(o):
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        f = float(o)
        return None if f != f else f
    if isinstance(o, float) and o != o:
        return None
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, np.ndarray):
        return _clean(o.tolist())
    if hasattr(o, "isoformat"):
        return str(o)[:10]
    return o


def save(section, obj):
    """Merge one section into results.json (file-locked; safe across concurrent scripts)."""
    with open(RES + ".lock", "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        d = {}
        if os.path.exists(RES):
            with open(RES) as fh:
                d = json.load(fh)
        d[section] = _clean(obj)
        tmp = RES + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(d, fh, indent=1, default=str)
        os.replace(tmp, RES)
        fcntl.flock(lk, fcntl.LOCK_UN)
    print(f"[saved] {section}", flush=True)


def load_res():
    if os.path.exists(RES):
        with open(RES) as fh:
            return json.load(fh)
    return {}


# --------------------------------------------------------------------------- per-date helpers
def date_blocks(dates, idx):
    """Sort idx by date; return (idx_sorted, starts, ends)."""
    order = np.argsort(dates[idx], kind="stable")
    idx = idx[order]
    d = dates[idx]
    b = np.flatnonzero(np.r_[True, d[1:] != d[:-1]])
    e = np.r_[b[1:], len(idx)]
    return idx, b, e


def xs_pct(x, dates, mask):
    """Per-date percentile rank (0,1] among mask rows with finite x; NaN elsewhere."""
    v = np.where(mask & np.isfinite(x), x, np.nan)
    return pd.Series(v).groupby(dates).rank(pct=True, method="average").values


def regime_of(mds200, mm20):
    reg = np.where(mds200 > 0, "bull", "bear").astype(object)
    reg = reg + np.where(mm20 > 0, "_up20", "_dn20")
    reg[~(np.isfinite(mds200) & np.isfinite(mm20))] = "na"
    return reg


# --------------------------------------------------------------------------- walk-forward copy
def wf2_imp(target, mask, P, F, h, kind="regression", features=None,
            test_years=(2023, 2024, 2025, 2026), params=None, train_start="2021-09-01",
            date_step=2, n_jobs=2, min_train=5000, min_test=200, verbose=True, X=None):
    """VERBATIM copy of L.walk_forward2 (same folds, embargo h+2, date_step training subsample,
    same LightGBM params, scores all mask rows of each test year) that also returns per-fold
    normalised gain importance. Verified bit-identical to L.walk_forward2 in s3_wf.py."""
    import lightgbm as lgb
    feats = features or L.FEATURES
    y = np.asarray(target, dtype="float64")
    mask = np.asarray(mask, bool)
    m_lab = mask & np.isfinite(y)
    dates = P["date"].values.astype("datetime64[D]")
    cal = np.unique(dates)
    sub = np.isin(dates, cal[::date_step]) if date_step > 1 else np.ones(len(dates), bool)
    if X is None:
        X = F[feats].values.astype(np.float32)
    base = dict(n_estimators=400, learning_rate=0.03, num_leaves=31, min_child_samples=400,
                subsample=0.7, subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0,
                n_jobs=n_jobs, verbose=-1)
    if params:
        base.update(params)
    score = np.full(len(y), np.nan)
    imps = {}
    for Y in test_years:
        ts, te = np.datetime64(f"{Y}-01-01"), np.datetime64(f"{Y + 1}-01-01")
        ti = int(np.searchsorted(cal, ts))
        if ti >= len(cal):
            continue
        cutoff = cal[max(0, ti - h - 2)]
        tr = m_lab & sub & (dates < cutoff) & (dates >= np.datetime64(train_start))
        tm = mask & (dates >= ts) & (dates < te)
        if tr.sum() < min_train or tm.sum() < min_test:
            if verbose:
                print(f"skip fold {Y}: train {tr.sum()} test {tm.sum()}")
            continue
        if kind == "binary":
            mdl = lgb.LGBMClassifier(**base)
            mdl.fit(X[tr], y[tr].astype(int))
            score[tm] = mdl.predict_proba(X[tm])[:, 1]
        elif kind == "multiclass":
            mdl = lgb.LGBMClassifier(objective="multiclass", **base)
            mdl.fit(X[tr], (y[tr] + 1).astype(int))
            pr = mdl.predict_proba(X[tm])
            cls = list(mdl.classes_)
            pu = pr[:, cls.index(2)] if 2 in cls else 0.0
            pdn = pr[:, cls.index(0)] if 0 in cls else 0.0
            score[tm] = pu - pdn
        else:
            mdl = lgb.LGBMRegressor(**base)
            mdl.fit(X[tr], y[tr])
            score[tm] = mdl.predict(X[tm])
        g = mdl.booster_.feature_importance("gain").astype("float64")
        imps[Y] = dict(zip(feats, (g / g.sum()).tolist()))
        if verbose:
            print(f"fold {Y}: train {int(tr.sum())} test {int(tm.sum())}", flush=True)
    return score, imps


# --------------------------------------------------------------------------- xs metrics
def per_date_metrics(score, targets, binaries, mask, dates, min_n=30):
    """Per-date Spearman IC of score vs each continuous target and per-date AUC vs each binary
    target (sign=-1 inverts the score, for 'down' classes). Same maths as L.xs_metrics."""
    from scipy.stats import rankdata
    m = mask & np.isfinite(score)
    idx, b, e = date_blocks(dates, np.flatnonzero(m))
    rows = []
    for s_, t_ in zip(b, e):
        i0 = idx[s_:t_]
        rec = {"d": dates[i0[0]]}
        for k, t in targets.items():
            ii = i0[np.isfinite(t[i0])]
            if len(ii) >= min_n:
                rec[f"ic_{k}"] = np.corrcoef(rankdata(score[ii]), rankdata(t[ii]))[0, 1]
        for k, (bb, sign) in binaries.items():
            ii = i0[np.isfinite(bb[i0])]
            if len(ii) < min_n:
                continue
            pos = bb[ii] == 1
            n1, n0 = pos.sum(), (~pos).sum()
            if n1 > 5 and n0 > 5:
                rr = rankdata(score[ii] * sign)
                rec[f"auc_{k}"] = (rr[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)
        if len(rec) > 1:
            rows.append(rec)
    return pd.DataFrame(rows).set_index("d")


def summarize_pd(t, h=H):
    """dev/holdout means and non-overlapping t (every h-th date) for every column; by-year means."""
    out = {}
    for name, (a, b) in (("dev", DEV), ("hold", ("2026-01-01", "2100-01-01"))):
        sub = t[(t.index >= np.datetime64(a)) & (t.index <= np.datetime64(b))]
        if not len(sub):
            continue
        nov = sub.iloc[::max(1, h)]
        for col in sub.columns:
            x = nov[col].dropna()
            out[f"{name}_{col}"] = float(sub[col].mean())
            if len(x) > 3:
                ctr = 0.5 if col.startswith("auc") else 0.0
                out[f"{name}_{col}_t"] = float((x.mean() - ctr) / (x.std(ddof=1) / np.sqrt(len(x))))
        out[f"{name}_n_dates"] = int(len(sub))
    yrs = pd.DatetimeIndex(t.index).year
    out["by_year"] = {int(y): {c: float(g[c].mean()) for c in t.columns} for y, g in t.groupby(yrs)}
    return out


def nw_reg(y, X, lag):
    """OLS with Newey-West (Bartlett) standard errors. Returns coef, t, R2."""
    X = np.column_stack([np.ones(len(y)), X])
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    e = y - X @ b
    n = len(y)
    XtX_inv = np.linalg.inv(X.T @ X)
    Xe = X * e[:, None]
    Sm = Xe.T @ Xe / n
    for k in range(1, lag + 1):
        w = 1 - k / (lag + 1)
        G = Xe[k:].T @ Xe[:-k] / n
        Sm += w * (G + G.T)
    V = n * XtX_inv @ Sm @ XtX_inv
    se = np.sqrt(np.diag(V))
    r2 = 1 - e.var() / y.var()
    return b, b / se, r2
