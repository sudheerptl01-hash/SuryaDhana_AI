"""Shared helpers for C_trendscan scripts (adaptive-horizon & move-quality labels)."""
import json
import os
import sys

import numpy as np

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = os.path.join(LAB, "results", "C_trendscan")
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402,F401

RES = os.path.join(OUT, "results.json")
# Auditor (E_auditor) HIGH issue: sec_rel_mom20 uses a 2026 sector snapshot -> look-ahead. Dropped.
FEATS = [f for f in L.FEATURES if f != "sec_rel_mom20"]
DEV_END = "2025-12-31"     # selection window end (labels must also end by then -> see dev_mask)
HOLD_START, HOLD_END = "2026-01-01", "2026-09-10"


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
    import fcntl
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


def eq_universe(P, F):
    """elig_base minus ETF / MF units (ISIN prefix INF) -- auditor MEDIUM issue #2."""
    ent = P["entity"].astype(str).values
    not_fund = ~np.char.startswith(ent.astype("U12"), "INF")
    return F["elig_base"].values & not_fund


# --------------------------------------------------------------------------- label factory
# (identical definitions to s2_events.py; labels are NaN where the window is invalid)
WF_SET = {  # name -> (embargo horizon passed to walk_forward)
    "TSA_T5": 20, "TSX_T5": 20, "MQ_vol1.0": 20, "FP20": 20, "RA10": 10, "FX10_pm50": 10, "FX20_pm50": 20,
}


def _tern(pos, neg, valid):
    y = np.where(pos, 1.0, np.where(neg, -1.0, 0.0))
    y[~valid] = np.nan
    return y


def make_label(name, Z, vol20):
    v10, v20 = Z["v10"], Z["v20"]
    vol = np.asarray(vol20, dtype=float)
    if name.startswith("TSA_T") or name.startswith("TSX_T"):
        T = float(name.split("_T")[1])
        t = Z["tsA_t" if name.startswith("TSA") else "tsX_t"].astype(float)
        return _tern(t >= T, t <= -T, v20 & np.isfinite(t))
    if name in ("RA10", "RA20"):
        h = int(name[2:])
        rr = Z[f"r{h}"].astype(float)
        thr = np.maximum(0.5 * vol * np.sqrt(h), 0.005)
        return _tern(rr >= thr, rr <= -thr, np.isfinite(rr) & np.isfinite(vol))
    if name.startswith("MQ_vol"):
        a = float(name[6:])
        mfe, mae = Z["mfe"].astype(float), Z["mae"].astype(float)
        thr = a * vol * np.sqrt(20)
        pos = (mfe >= thr) & (mfe >= 2 * np.abs(mae))
        neg = (np.abs(mae) >= thr) & (np.abs(mae) >= 2 * mfe)
        return _tern(pos, neg, v20 & np.isfinite(mfe) & np.isfinite(thr))
    if name in ("FP20", "FP10"):
        return Z[f"fp{name[2:]}_lab"].astype(float)
    if name.startswith("FX"):
        h = int(name[2:].split("_")[0])
        rr = Z[f"r{h}"].astype(float)
        return _tern(rr > 0.005, rr < -0.005, np.isfinite(rr))
    raise KeyError(name)


def wf_all(target, mask, P, F, h, kind="multiclass", features=None, test_years=(2023, 2024, 2025, 2026),
           params=None, train_start="2021-09-01", date_step=2, n_jobs=2, verbose=True):
    """Copy of L.walk_forward (same model, folds, embargo h+2, date_step subsampling for TRAINING),
    with one fix (auditor issue #6): the fitted fold model scores EVERY mask row of the test year,
    not only rows whose label is defined, so the model cannot implicitly avoid future-suspended
    names. Metrics are computed on labeled rows only (identical to L.walk_forward)."""
    import json as _json
    import lightgbm as lgb
    import pandas as _pd
    from sklearn.metrics import roc_auc_score
    feats = features or FEATS
    y = np.asarray(target, dtype="float64")
    mk = np.asarray(mask, bool)
    m = mk & ~np.isnan(y)
    dates = P["date"].values.astype("datetime64[D]")
    cal = np.unique(dates)
    m_train_sub = np.isin(dates, cal[::date_step]) if date_step > 1 else np.ones(len(dates), bool)
    X = F[feats].values.astype(np.float32)
    base = dict(n_estimators=400, learning_rate=0.03, num_leaves=31, min_child_samples=400,
                subsample=0.7, subsample_freq=1, colsample_bytree=0.7, reg_lambda=5.0,
                n_jobs=n_jobs, verbose=-1)
    if params:
        base.update(params)
    score = np.full(len(y), np.nan)
    folds = []
    for Y in test_years:
        ts = np.datetime64(f"{Y}-01-01")
        te = np.datetime64(f"{Y + 1}-01-01")
        ti = np.searchsorted(cal, ts)
        if ti >= len(cal):
            continue
        cutoff = cal[max(0, ti - h - 2)]
        tr = m & m_train_sub & (dates < cutoff) & (dates >= np.datetime64(train_start))
        tall = mk & (dates >= ts) & (dates < te)
        tm = m & (dates >= ts) & (dates < te)
        if tr.sum() < 20000 or tm.sum() < 1000:
            continue
        if kind == "binary":
            mdl = lgb.LGBMClassifier(**base)
            mdl.fit(X[tr], y[tr].astype(int))
            p_all = mdl.predict_proba(X[tall])[:, 1]
        elif kind == "multiclass":
            mdl = lgb.LGBMClassifier(objective="multiclass", **base)
            mdl.fit(X[tr], (y[tr] + 1).astype(int))
            pr = mdl.predict_proba(X[tall])
            cls = list(mdl.classes_)
            pu = pr[:, cls.index(2)] if 2 in cls else 0
            pd_ = pr[:, cls.index(0)] if 0 in cls else 0
            p_all = pu - pd_
        else:
            mdl = lgb.LGBMRegressor(**base)
            mdl.fit(X[tr], y[tr])
            p_all = mdl.predict(X[tall])
        score[tall] = p_all
        p = score[tm]
        fm = {"year": Y, "n_train": int(tr.sum()), "n_test": int(tm.sum()), "n_scored": int(tall.sum())}
        yt = y[tm]
        dd = dates[tm]
        if kind in ("binary", "multiclass"):
            yb = (yt == 1).astype(int)
            if 0 < yb.mean() < 1:
                fm["auc_up"] = float(roc_auc_score(yb, p))
            if kind == "multiclass":
                yd = (yt == -1).astype(int)
                if 0 < yd.mean() < 1:
                    fm["auc_down_inverted"] = float(roc_auc_score(yd, -p))
            t = _pd.DataFrame({"d": dd, "p": p, "y": yb})
            t["r"] = t.groupby("d").p.rank(pct=True)
            fm["base_rate"] = float(t.y.mean())
            fm["top_decile_rate"] = float(t[t.r > 0.9].y.mean())
            fm["bottom_decile_rate"] = float(t[t.r <= 0.1].y.mean())
            if kind == "multiclass":
                ydn = (yt == -1).astype(int)
                t["yd"] = ydn
                fm["down_base_rate"] = float(t.yd.mean())
                fm["down_rate_in_bottom_decile"] = float(t[t.r <= 0.1].yd.mean())
                fm["down_rate_in_top_decile"] = float(t[t.r > 0.9].yd.mean())
        folds.append(fm)
        if verbose:
            print(_json.dumps(fm), flush=True)
        try:
            imp = _pd.Series(mdl.booster_.feature_importance("gain"), index=feats)
            fm["top_features_gain"] = (imp / imp.sum()).sort_values(ascending=False).head(10).round(4).to_dict()
        except Exception:  # noqa: BLE001
            pass
    met = {"folds": folds}
    for k in ("auc_up", "auc_down_inverted", "top_decile_rate", "base_rate", "bottom_decile_rate"):
        vals = [f[k] for f in folds if k in f and f[k] == f[k]]
        if vals:
            met[f"mean_{k}"] = float(np.mean(vals))
    return score, met
