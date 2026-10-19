"""Round-3 shared helpers (promoted from results/R3_devil/common.py, whose maths was validated
bit-exact against L.Sim). Usage inside an agent script:

    import sys; sys.path.insert(0, "<LAB>")
    import r3common as C
    C.set_agent("R3_book")                # results go to results/R3_book/results.json
    P, F, fw, S, E = C.load_sim()         # E = elig_base (liq2)
    Z = C.load_prod()                     # Z["prod"] (frozen PROD score), Z["pct"] (label), Z["members"]
    pa, sm, rm, em = C.phase_avg(S, Z["prod"], E, "liq2", 20, C.BASE_KW, "dev", with_ew=True)
    C.save("section_name", pa)

phase_avg = the book shifted by k = 0..step-1 trading days, daily returns averaged on common
dates (== a daily-staggered book); random baseline = 5-seed horizon-matched random top-K on the
same mask; EW = equal-weight all mask names on the same calendar. Random/EW books are cached in
results/_lead/rb_cache (shared, keyed by mask tag + h + kwargs; use a distinct mask_tag for every
distinct mask!)."""
import fcntl
import hashlib
import json
import os
import sys
import time

import numpy as np
import pandas as pd

LAB = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402

RB = os.path.join(LAB, "results", "_lead", "rb_cache")
os.makedirs(RB, exist_ok=True)
DEV = L.DEV
HOLD = ("2026-01-01", None)
PER = {"dev": DEV, "hold": HOLD}
SEEDS = (1, 2, 3, 4, 5)
H = 20
BASE_KW = dict(top_k=20, step=5, cost_bps=50)
T0 = time.time()
OUT = None
RES = None


def set_agent(name):
    global OUT, RES
    OUT = os.path.join(LAB, "results", name)
    os.makedirs(OUT, exist_ok=True)
    RES = os.path.join(OUT, "results.json")
    return OUT


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
    if isinstance(o, pd.Series):
        return {str(k)[:10]: _clean(v) for k, v in o.items()}
    if hasattr(o, "isoformat"):
        return str(o)[:10]
    return o


def save(section, obj):
    """Merge obj under `section` into this agent's results.json (file-locked, atomic)."""
    assert RES is not None, "call set_agent() first"
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


def load_res(agent=None):
    fn = RES if agent is None else os.path.join(LAB, "results", agent, "results.json")
    if fn and os.path.exists(fn):
        with open(fn) as fh:
            return json.load(fh)
    return {}


def load_sim(extra_panel=(), extra_feat=()):
    P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"]
                     + [c for c in extra_panel if c not in ("date", "entity", "open", "high", "low", "close",
                                                             "seg_break", "label_block")])
    F = L.load_features(["atr_pct", "elig_base"] + [c for c in extra_feat if c not in ("atr_pct", "elig_base")])
    fw = L.Fwd(P)
    S = L.Sim(P, F, fw)
    E = F["elig_base"].values.astype(bool)
    return P, F, fw, S, E


def load_prod():
    z = np.load(os.path.join(LAB, "results", "_lead", "prod_h20.npz"), allow_pickle=True)
    return {k: z[k] for k in z.files}


def market_daily(name):
    """Daily close-to-close returns of an NSE index (pd.Series indexed by date)."""
    s = L.market_series(name)["close"].astype("float64")
    return s.pct_change()


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
    tmp = fn + f".{os.getpid()}.tmp.npz"
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
    tmp = fn + f".{os.getpid()}.tmp.npz"
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
    returns of all phases on common dates (== a book that staggers entries every day).
    Returns (summary, strategy daily Series, random daily Series, EW daily Series or None)."""
    a, b = PER[period] if isinstance(period, str) else period
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
           "pa_vol": float(sm.std() * np.sqrt(252)),
           "pa_maxdd": float((eq / np.maximum.accumulate(eq) - 1).min()), "n_days": int(len(common))}
    em = None
    if with_ew:
        em = np.mean([x.reindex(common).values for x in eds], 0)
        out["pa_ew_cagr"] = float(np.prod(1 + em) ** (1 / yrs) - 1)
        out["pa_excess_vs_ew_ann"] = float((sm - em).mean() * 252)
        out["pa_vs_ew_nw_t"] = L.nw_t(sm - em, lag=h)
        eqe = np.cumprod(1 + em)
        out["pa_ew_maxdd"] = float((eqe / np.maximum.accumulate(eqe) - 1).min())
    return out, pd.Series(sm, index=common), pd.Series(rm, index=common), \
        (pd.Series(em, index=common) if em is not None else None)


def paired(a, b, h=H):
    """Annualised mean of (a - b) daily on common dates, with Newey-West t (lag h)."""
    c = a.index.intersection(b.index)
    d = a.reindex(c).values - b.reindex(c).values
    return {"diff_ann": float(d.mean() * 252), "nw_t": L.nw_t(d, lag=h), "n_days": int(len(c))}


def stats_from_daily(r):
    """CAGR / vol / Sharpe / maxDD / worst month / % positive months from a daily return Series."""
    r = r.dropna()
    eq = (1 + r).cumprod()
    yrs = len(r) / 252
    m = (1 + r).groupby(r.index.to_period("M")).prod() - 1
    return {"cagr": float(eq.iloc[-1] ** (1 / yrs) - 1), "vol": float(r.std() * np.sqrt(252)),
            "sharpe": float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else None,
            "maxdd": float((eq / eq.cummax() - 1).min()), "worst_month": float(m.min()),
            "best_month": float(m.max()), "pct_pos_months": float((m > 0).mean()), "n_days": int(len(r))}


def entity_half(entity_values, salt="R3"):
    """Deterministic 50/50 split by a hash of the entity id (md5, not Python's salted hash)."""
    u = pd.unique(entity_values)
    hv = np.array([int(hashlib.md5((salt + str(e)).encode()).hexdigest()[:8], 16) & 1 for e in u], dtype=np.int8)
    m = dict(zip(u, hv))
    return pd.Series(entity_values).map(m).values.astype(np.int8)


def table(title, columns, rows, note=""):
    """Standard HTML-ready table record: rows are lists aligned to columns (numbers as floats)."""
    return {"title": title, "columns": list(columns), "rows": [list(r) for r in rows], "note": note}


def short(d, nd=4):
    if isinstance(d, dict):
        return {k: short(v, nd) for k, v in d.items()}
    if isinstance(d, float):
        return round(d, nd)
    if isinstance(d, list):
        return [short(v, nd) for v in d]
    return d
