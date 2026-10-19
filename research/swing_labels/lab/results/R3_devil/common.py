"""R3_devil shared helpers (devil's advocate). Independent code: no refiner scripts are imported.
Only lablib (shared lab infrastructure: Sim, walk_forward2, nw_t, Fwd) is used."""
import fcntl
import hashlib
import json
import os
import sys
import time

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = os.path.join(LAB, "results", "R3_devil")
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402

RES = os.path.join(OUT, "results.json")
RB = os.path.join(OUT, "rb_cache")
os.makedirs(RB, exist_ok=True)
DEV = L.DEV
HOLD = ("2026-01-01", None)
PER = {"dev": DEV, "hold": HOLD}
SEEDS = (1, 2, 3, 4, 5)
T0 = time.time()


def log(*a):
    print(f"[{time.time() - T0:7.1f}s]", *a, flush=True)


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
    lock = RES + ".lock"
    with open(lock, "w") as lk:
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
    log(f"[saved] {section}")


def load_res():
    if os.path.exists(RES):
        with open(RES) as fh:
            return json.load(fh)
    return {}


def load_sim():
    P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
    F = L.load_features(["atr_pct", "elig_base"])
    fw = L.Fwd(P)
    S = L.Sim(P, F, fw)
    E = F["elig_base"].values.astype(bool)
    return P, F, fw, S, E


def key_of(tag, h, kw):
    s = json.dumps({"u": tag, "h": h, **{k: (list(v) if isinstance(v, tuple) else v) for k, v in sorted(kw.items())}},
                   sort_keys=True)
    return hashlib.md5(s.encode()).hexdigest()[:16]


def random_band(S, mask, mask_tag, h, kw, seeds=SEEDS):
    """Cached horizon-matched random baseline (identical maths to Sim.random_band)."""
    fn = os.path.join(RB, key_of(mask_tag, h, kw) + ".npz")
    if os.path.exists(fn):
        z = np.load(fn, allow_pickle=True)
        return json.loads(str(z["summary"])), z["daily"], z["dates"]
    rb = S.random_band(mask, h, seeds=seeds, **kw)
    summ = {k: v for k, v in rb.items() if not k.startswith("_")}
    summ["by_year_mean"] = {str(a): b for a, b in summ["by_year_mean"].items()}
    tmp = fn + ".tmp.npz"
    np.savez(tmp, summary=json.dumps(_clean(summ)), daily=rb["_daily_ret_mean"],
             dates=rb["_dates"].astype("datetime64[D]").astype(str))
    os.replace(tmp, fn)
    return summ, rb["_daily_ret_mean"], rb["_dates"].astype("datetime64[D]").astype(str)


def ew_band(S, mask, mask_tag, h, kw):
    """Cached equal-weight universe book (all mask names, equal weight), same calendar."""
    kw2 = dict(kw)
    kw2["select_quantile"] = (0.0, 1.0)
    kw2["sizing"] = "equal"
    kw2.pop("top_k", None)
    fn = os.path.join(RB, "EW_" + key_of(mask_tag, h, kw2) + ".npz")
    if os.path.exists(fn):
        z = np.load(fn, allow_pickle=True)
        return json.loads(str(z["summary"])), z["daily"], z["dates"]
    st = S.run(np.ones(S.n), mask, h, **kw2)
    summ = {k: v for k, v in st.items() if not k.startswith("_") and k != "params"}
    summ["by_year"] = {str(a): b for a, b in summ["by_year"].items()}
    tmp = fn + ".tmp.npz"
    np.savez(tmp, summary=json.dumps(_clean(summ)), daily=st["_daily_ret"],
             dates=st["_dates"].astype("datetime64[D]").astype(str))
    os.replace(tmp, fn)
    return summ, st["_daily_ret"], st["_dates"].astype("datetime64[D]").astype(str)


def compare(S, score, mask, mask_tag, h, kw, with_ew=False, keep=False):
    """Sim.compare equivalent with a cached random band. Returns (summary, strat daily, random daily, dates)."""
    st = S.run(score, mask, h, keep_trades=keep, **kw)
    rb, rbd, rdates = random_band(S, mask, mask_tag, h, kw)
    sd = st["_daily_ret"]
    n = min(len(sd), len(rbd))
    diff = sd[:n] - rbd[:n]
    res = {k: v for k, v in st.items() if not k.startswith("_") and k != "params"}
    res["random"] = {k: v for k, v in rb.items()}
    res["excess_cagr_vs_random"] = st["cagr"] - rb["cagr_mean"]
    res["excess_daily_nw_t"] = L.nw_t(diff, lag=h)
    res["excess_ann_return"] = float(diff.mean() * 252)
    if with_ew:
        ew, ewd, _ = ew_band(S, mask, mask_tag, h, kw)
        d2 = sd[:n] - ewd[:n]
        res["ew"] = {"cagr": ew["cagr"], "max_dd": ew["max_dd"], "sharpe": ew["sharpe"]}
        res["excess_cagr_vs_ew"] = st["cagr"] - ew["cagr"]
        res["excess_vs_ew_ann"] = float(d2.mean() * 252)
        res["excess_vs_ew_nw_t"] = L.nw_t(d2, lag=h)
    out = (res, sd, rbd, st["_dates"].astype("datetime64[D]").astype(str))
    if keep:
        out = out + (st["_trades"],)
    return out


def phase_avg(S, score, mask, mask_tag, h, kw, period, with_ew=False):
    """Phase-averaged book: shift the signal calendar by k=0..step-1 trading days, average the daily
    returns of all phases on common dates (== a book that staggers entries every day)."""
    a, b = PER[period]
    step = kw["step"]
    g0 = int(np.searchsorted(S.cal, np.datetime64(a)))
    sds, rds, eds, ex, tt = [], [], [], [], []
    for k in range(step):
        kk = dict(kw, start=str(S.cal[g0 + k]), end_exit=b)
        res, sd, rbd, dts = compare(S, score, mask, mask_tag, h, kk)
        ex.append(res["excess_cagr_vs_random"])
        tt.append(res["excess_daily_nw_t"])
        sds.append(pd.Series(sd, index=pd.DatetimeIndex(dts)))
        rds.append(pd.Series(rbd[:len(dts)], index=pd.DatetimeIndex(dts)))
        if with_ew:
            _, ewd, _ = ew_band(S, mask, mask_tag, h, kk)
            eds.append(pd.Series(ewd[:len(dts)], index=pd.DatetimeIndex(dts)))
    common = sds[0].index
    for x in sds + rds + eds:
        common = common.intersection(x.index)
    sm = np.mean([x.reindex(common).values for x in sds], 0)
    rm = np.mean([x.reindex(common).values for x in rds], 0)
    yrs = len(common) / 252
    eq = np.cumprod(1 + sm)
    out = {"phase_excess": [float(e) for e in ex], "phase_t": [float(t) for t in tt],
           "phase_excess_mean": float(np.mean(ex)), "phase_excess_min": float(np.min(ex)),
           "phase_excess_max": float(np.max(ex)),
           "pa_cagr": float(np.prod(1 + sm) ** (1 / yrs) - 1),
           "pa_random_cagr": float(np.prod(1 + rm) ** (1 / yrs) - 1),
           "pa_excess_ann": float((sm - rm).mean() * 252), "pa_nw_t": L.nw_t(sm - rm, lag=h),
           "pa_sharpe": float(sm.mean() / sm.std() * np.sqrt(252)),
           "pa_maxdd": float((eq / np.maximum.accumulate(eq) - 1).min()), "n_days": int(len(common))}
    em = None
    if with_ew:
        em = np.mean([x.reindex(common).values for x in eds], 0)
        out["pa_ew_cagr"] = float(np.prod(1 + em) ** (1 / yrs) - 1)
        out["pa_excess_vs_ew_ann"] = float((sm - em).mean() * 252)
        out["pa_vs_ew_nw_t"] = L.nw_t(sm - em, lag=h)
    return out, pd.Series(sm, index=common), pd.Series(rm, index=common), \
        (pd.Series(em, index=common) if em is not None else None)


def entity_half(entity_values, salt="R3"):
    """Deterministic 50/50 split by a hash of the entity id (md5, not Python's salted hash)."""
    u = pd.unique(entity_values)
    hv = np.array([int(hashlib.md5((salt + str(e)).encode()).hexdigest()[:8], 16) & 1 for e in u], dtype=np.int8)
    m = dict(zip(u, hv))
    return pd.Series(entity_values).map(m).values.astype(np.int8)


def short(d, nd=4):
    if isinstance(d, dict):
        return {k: short(v, nd) for k, v in d.items()}
    if isinstance(d, float):
        return round(d, nd)
    if isinstance(d, list):
        return [short(v, nd) for v in d]
    return d
