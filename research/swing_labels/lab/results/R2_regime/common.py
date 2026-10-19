"""R2_regime shared helpers: paths, results.json persistence, NW t, date-level helpers,
and a cohort-path re-implementation of L.Sim.run that allows per-signal exposure scaling.

Exposure scaling is exact and linear: for sleeve-level gating, a signal with exposure x
invests x of the sleeve's equity in the book (slot or equal sizing) and keeps 1-x in cash
earning cash_yield; trading costs are paid only on the invested part. Because each sleeve
fully turns over every period, scaling the NEW entries costs nothing extra.
    path_x(d) = (1-x) * cash_growth(d) + x * path_1(d)
so we store path_1 for every signal once and compose any exposure series in milliseconds.
"""
import fcntl
import json
import os
import sys

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = os.path.join(LAB, "results", "R2_regime")
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402

RES = os.path.join(OUT, "results.json")
DEV = L.DEV
HOLD = ("2026-01-01", None)
CASH = 0.065
NAN = np.nan

MKT_FEATS = ["mkt_mom5", "mkt_mom20", "mkt_mom60", "mkt_dist_sma50", "mkt_dist_sma200",
             "mkt_vol20", "vix", "breadth50", "breadth_ad", "dispersion"]


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


# --------------------------------------------------------------------------- stats
def nw_t(x, lag):
    return L.nw_t(x, lag)


def hac_slope(y, x, lag):
    """OLS y = a + b*x with Newey-West (Bartlett, `lag`) standard error. Returns (b, t)."""
    y = np.asarray(y, float)
    x = np.asarray(x, float)
    ok = np.isfinite(y) & np.isfinite(x)
    y, x = y[ok], x[ok]
    if len(y) < 30 or x.std() == 0:
        return NAN, NAN
    X = np.column_stack([np.ones(len(y)), x])
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    n = len(y)
    XtX_inv = np.linalg.inv(X.T @ X)
    u = X * e[:, None]
    S = u.T @ u
    for k in range(1, min(lag, n - 1) + 1):
        w = 1 - k / (lag + 1)
        G = u[k:].T @ u[:-k]
        S += w * (G + G.T)
    V = XtX_inv @ S @ XtX_inv
    return float(b[1]), float(b[1] / np.sqrt(max(V[1, 1], 1e-30)))


def nw_mean_diff_t(y, on, lag):
    """Mean of y on on==1 dates minus mean on on==0 dates, with NW t (regression on dummy)."""
    return hac_slope(y, on, lag)


def nw_corr_t(x, y, lag):
    """Spearman rank correlation of x and y with a NW t (slope of standardized ranks)."""
    from scipy.stats import rankdata
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    if ok.sum() < 30:
        return NAN, NAN
    rx = rankdata(x[ok])
    ry = rankdata(y[ok])
    rx = (rx - rx.mean()) / rx.std()
    ry = (ry - ry.mean()) / ry.std()
    rho = float(np.mean(rx * ry))
    _, t = hac_slope(ry, rx, lag)
    return rho, t


def auc(score, y):
    from scipy.stats import rankdata
    s = np.asarray(score, float)
    y = np.asarray(y, float)
    ok = np.isfinite(s) & np.isfinite(y)
    s, y = s[ok], y[ok]
    pos = y == 1
    n1, n0 = pos.sum(), (~pos).sum()
    if n1 < 5 or n0 < 5:
        return NAN
    r = rankdata(s)
    return float((r[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0))


# --------------------------------------------------------------------------- cohort-path simulator
class PathSim(L.Sim):
    """Exact replica of L.Sim.run (time exit only) that stores each signal's normalised
    sleeve path so that exposure series can be composed afterwards."""

    def paths(self, score, mask, h, step=5, top_k=20, side="long", cost_bps=50.0,
              start=DEV[0], end_exit=DEV[1], cash_yield=0.0, random_seed=None,
              sizing="slot", select_quantile=None, phase=0):
        fw = self.fw
        mask = np.asarray(mask, bool)
        if score is not None:
            score = np.asarray(score, dtype="float64")
        rng = np.random.default_rng(random_seed) if random_seed is not None else None
        g0, g_sig_last, g_end = self._window(start, end_exit, h, step)
        g0 = g0 + phase
        S = int(np.ceil(h / step))
        period = S * step
        sigs = list(range(g0, g_sig_last + 1, step))
        D0, D1 = g0, min(g_end, sigs[-1] + period)
        cost = cost_bps / 1e4
        sgn = 1.0 if side == "long" else -1.0
        lb_cs = fw.lb_cs
        hk = np.arange(1, h + 1)
        recs = []
        tstats = []
        for j, g in enumerate(sigs):
            s = j % S
            g_next = min(g + period, D1)
            cand = self.rows_on(g)
            cand = cand[mask[cand]]
            if score is not None and rng is None:
                cand = cand[np.isfinite(score[cand])]
            if rng is not None:
                k = min(top_k, len(cand)) if select_quantile is None else len(cand)
                pick = rng.choice(cand, size=k, replace=False) if k else cand[:0]
                if select_quantile is not None and len(cand):
                    lo_q, hi_q = select_quantile
                    m_ = rng.random(len(cand))
                    pick = cand[(m_ >= lo_q) & (m_ <= hi_q)]
            elif select_quantile is not None:
                sc = score[cand]
                pr = pd.Series(sc).rank(pct=True).values if len(sc) else sc
                lo_q, hi_q = select_quantile
                pick = cand[(pr >= lo_q) & (pr <= hi_q)]
            else:
                sc = score[cand]
                ordr = np.argsort(-sc if side == "long" else sc, kind="stable")
                pick = cand[ordr[:top_k]]
            days = np.arange(g + 1, g_next + 1)
            seg_len = len(days)
            cg = (1 + cash_yield) ** ((days - g) / 252.0)
            if len(pick) == 0 or seg_len == 0:
                recs.append((s, g, g_next, cg, cg, np.zeros(seg_len), 0))
                continue
            rows_k = pick[:, None] + hk[None, :]
            rk = np.clip(rows_k, 0, self.n - 1)
            v = (rows_k <= fw.end[pick][:, None]) & ((lb_cs[rk] - lb_cs[pick][:, None]) == 0) \
                & (self.didx[rk] <= g_next)
            v = np.cumprod(v, axis=1).astype(bool)
            e = np.where(v[:, 0], self.o[rk[:, 0]], NAN)
            ok = v[:, 0] & np.isfinite(e) & (e > 0)
            pick, rk, v, e = pick[ok], rk[ok], v[ok], e[ok]
            npk = len(pick)
            if npk == 0:
                recs.append((s, g, g_next, cg, cg, np.zeros(seg_len), 0))
                continue
            nvalid = v.sum(1)
            px = np.where(v, self.c[rk], NAN)
            Kx = nvalid.copy()
            X = px[np.arange(npk), Kx - 1]
            bd = np.where(v, self.didx[rk], 10 ** 9)
            bd = np.where(hk[None, :] <= Kx[:, None], bd, 10 ** 9)
            exit_day = self.didx[rk[np.arange(npk), Kx - 1]]
            cnt = (bd[:, None, :] <= days[None, :, None]).sum(2)
            idx = np.clip(cnt - 1, 0, h - 1)
            price = np.take_along_axis(np.nan_to_num(px, nan=0.0), idx, axis=1)
            rel = price / e[:, None]
            gross = np.where(cnt == 0, 1.0, (1 + sgn * (rel - 1)) * (1 - cost / 2))
            after = days[None, :] >= exit_day[:, None]
            gross = np.where(after, gross * (1 - cost / 2), gross)
            w = (1.0 / top_k) if sizing == "slot" and select_quantile is None else (1.0 / npk)
            cash_frac = max(0.0, 1 - w * npk)
            path = cash_frac * cg + w * gross.sum(0)
            inv = w * (~after).sum(0)
            net = sgn * (X / e - 1) - cost
            recs.append((s, g, g_next, path, cg, inv, npk))
            tstats.append((g, float(net.mean()), float((net > 0).mean()), npk))
        return {"recs": recs, "S": S, "D0": D0, "D1": D1, "h": h, "step": step,
                "dates": self.cal[D0:D1 + 1], "tstats": tstats, "sigs": np.array(sigs)}


def compose(pp, x_by_g=None, x_const=None):
    """Compose the sleeve equity for an exposure series x_by_g (array over calendar index g)
    evaluated at each signal date. Returns daily equity, daily ret, invested series."""
    S, D0, D1 = pp["S"], pp["D0"], pp["D1"]
    nd = D1 - D0 + 1
    sleeve_eq = np.ones((S, nd))
    invested = np.zeros((S, nd))
    last_w = np.zeros(S, dtype=int)
    xs = []
    for (s, g, g_next, path, cg, inv, npk) in pp["recs"]:
        if x_const is not None:
            x = x_const
        elif x_by_g is None:
            x = 1.0
        else:
            x = x_by_g[g]
            if not np.isfinite(x):
                x = 1.0
        xs.append(x)
        E = sleeve_eq[s, g - D0]
        sleeve_eq[s, g - D0 + 1:g_next - D0 + 1] = E * ((1 - x) * cg + x * path)
        invested[s, g - D0 + 1:g_next - D0 + 1] = x * inv
        last_w[s] = g_next - D0
    for s_ in range(S):
        lw = last_w[s_]
        if 0 < lw < nd - 1:
            sleeve_eq[s_, lw + 1:] = sleeve_eq[s_, lw]
    eq = sleeve_eq.mean(0)
    r = np.r_[0.0, eq[1:] / eq[:-1] - 1]
    return eq, r, invested.mean(0), np.array(xs)


def metrics(eq, r, dates, inv=None, xs=None, step=5):
    yrs = max((dates[-1] - dates[0]).astype(int) / 365.25, 1e-9)
    dd = eq / np.maximum.accumulate(eq) - 1
    ser = pd.Series(eq, index=pd.DatetimeIndex(dates))
    by_year = {int(y): float(gq.iloc[-1] / gq.iloc[0] - 1) for y, gq in ser.groupby(ser.index.year)}
    cd = (1 + CASH) ** (1 / 252) - 1
    out = {"cagr": float(eq[-1] ** (1 / yrs) - 1), "sharpe": float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else NAN,
           "sharpe_xs": float((r.mean() - cd) / r.std() * np.sqrt(252)) if r.std() > 0 else NAN,
           "max_dd": float(dd.min()), "ann_vol": float(r.std() * np.sqrt(252)),
           "calmar": float((eq[-1] ** (1 / yrs) - 1) / abs(dd.min())) if dd.min() < 0 else NAN,
           "by_year": by_year}
    if inv is not None:
        out["exposure"] = float(np.mean(inv))
    if xs is not None and len(xs) > 1:
        ch = np.abs(np.diff(xs)) > 1e-9
        out["signal_exposure_mean"] = float(np.mean(xs))
        out["switches_per_yr"] = float(ch.sum() / yrs)
    return out


def flips_per_year(state, dates):
    s = np.asarray(state, float)
    ok = np.isfinite(s)
    s = s[ok]
    d = np.asarray(dates)[ok]
    if len(s) < 2:
        return NAN
    yrs = max((d[-1] - d[0]).astype("timedelta64[D]").astype(int) / 365.25, 1e-9)
    return float((np.abs(np.diff(s)) > 1e-9).sum() / yrs)
