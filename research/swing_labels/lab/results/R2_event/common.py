"""R2_event shared helpers: capitulation-reversal event sleeve on lab v2.

Conventions (TEAM_BRIEF + ROUND2_BRIEF):
  * entry open[t+1], time exit close[t+h]; r_h = L.fwd_return (NaN unless fw.ok(h)).
  * U = F.elig_base (lab v2: EQ, INE ISIN, >=Rs20, >=Rs2cr 20d turnover, seasoned, unlocked, ATR band).
  * events are SAMPLE filters on U; they never change label values.
  * date-matched excess x_h = r_h - mean_{U, same date}(r_h)  (removes market timing).
  * DEV = signals 2023-01-01 .. last date whose t+h exit <= 2025-12-31; HOLDOUT = signals >= 2026-01-01.
"""
import fcntl
import json
import os
import sys
import time

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
OUT = os.path.join(LAB, "results", "R2_event")
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402

RES = os.path.join(OUT, "results.json")
HS = (5, 10, 20)
DEV = L.DEV
HOLD0 = "2026-01-01"


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
    if isinstance(o, np.datetime64):
        return str(o)[:10]
    return o


def save(section, obj):
    """Merge one section into results.json (file-locked)."""
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
    print(f"[saved] {section}", flush=True)


def load_res():
    if os.path.exists(RES):
        with open(RES) as fh:
            return json.load(fh)
    return {}


class T:
    def __init__(self):
        self.t0 = time.time()

    def __call__(self, msg):
        print(f"[{time.time() - self.t0:6.1f}s] {msg}", flush=True)


def load_base():
    z = np.load(os.path.join(OUT, "base.npz"), allow_pickle=False)
    return {k: z[k] for k in z.files}


# --------------------------------------------------------------------------- #
# event-study statistics
# --------------------------------------------------------------------------- #
def cluster_t(vals, groups):
    """t of the mean of vals with cluster-robust SE (clusters = groups)."""
    vals = np.asarray(vals, dtype="float64")
    n = len(vals)
    if n < 5:
        return np.nan, 0
    mu = vals.mean()
    g = pd.Series(vals - mu).groupby(np.asarray(groups)).sum().values
    G = len(g)
    if G < 3:
        return np.nan, G
    se = np.sqrt((g ** 2).sum() * G / (G - 1)) / n
    return (float(mu / se) if se > 0 else np.nan), G


class EventStudy:
    """Fast per-event statistics for many event masks. B = base dict."""

    def __init__(self, B):
        self.B = B
        self.day = B["day"].astype("datetime64[D]")
        self.cal = np.unique(self.day)
        self.didx = np.searchsorted(self.cal, self.day)
        self.month = (self.day.astype("datetime64[M]")).astype(np.int64)        # months since 1970
        self.quarter = self.month // 3
        self.year = self.day.astype("datetime64[Y]").astype(int) + 1970
        self.U = B["U"]
        pos = np.searchsorted(self.cal, np.datetime64(DEV[1]), side="right") - 1
        self.dev_end = {h: self.cal[pos - h] for h in HS}
        self.d_dev0 = np.datetime64(DEV[0])
        self.d_hold0 = np.datetime64(HOLD0)
        # trading days per window (for event frequency)
        self.ndays_U = pd.Series(self.U).groupby(self.didx).sum().reindex(range(len(self.cal))).fillna(0).values

    def windows(self, h):
        d = self.day
        return {"dev": (d >= self.d_dev0) & (d <= self.dev_end[h]),
                "hold": d >= self.d_hold0,
                "pre": d < self.d_dev0,
                "all": np.ones(len(d), bool)}

    def stats(self, m, h, cost=0.005, detail=False):
        """m: bool event mask (rows of U). Returns dict of window stats."""
        B = self.B
        r = B[f"r{h}"]
        x = B[f"x{h}"]
        v = m & np.isfinite(r)
        out = {}
        W = self.windows(h)
        for wn, wm in W.items():
            if not detail and wn in ("all",):
                continue
            mm = v & wm
            n = int(mm.sum())
            if n == 0:
                out[wn] = {"n": 0}
                continue
            rr, xx = r[mm], x[mm]
            mo = self.month[mm]
            di = self.didx[mm]
            t_m, G = cluster_t(xx, mo)
            t_q, _ = cluster_t(xx, self.quarter[mm])
            # date-weighted
            ds = pd.Series(xx).groupby(di).mean()
            dmo = self.month[np.searchsorted(self.didx, ds.index.values)] if False else None
            dates_with = ds.index.values
            dmonth = (self.cal[dates_with].astype("datetime64[M]")).astype(np.int64)
            t_dw, _ = cluster_t(ds.values, dmonth)
            ndays_win = int((wm & self.U).any() and len(np.unique(self.didx[wm & self.U])))
            o = {"n": n, "event_days": int(len(ds)), "trading_days": ndays_win,
                 "share_days_with_event": len(ds) / max(ndays_win, 1),
                 "events_per_event_day": n / max(len(ds), 1),
                 "share_of_U_rows": n / max(int((wm & self.U & np.isfinite(r)).sum()), 1),
                 "p_net_pos": float((rr > cost).mean()), "net_bps": 1e4 * float(rr.mean() - cost),
                 "gross_bps": 1e4 * float(rr.mean()),
                 "xs_bps": 1e4 * float(xx.mean()), "xs_t_month": t_m, "xs_t_quarter": t_q, "months": G,
                 "p_xs_pos": float((xx > 0).mean()),
                 "xs_dw_bps": 1e4 * float(ds.mean()), "xs_dw_t_month": t_dw}
            out[wn] = o
        if detail:
            mm = v
            yrs = self.year[mm]
            out["by_year"] = {}
            for y in np.unique(yrs):
                k = mm & (self.year == y)
                if y == 2025:   # keep calendar-year view; dev cut handled in 'dev'
                    pass
                rr, xx = r[k], x[k]
                out["by_year"][int(y)] = {"n": int(k.sum()), "p_net_pos": float((rr > cost).mean()),
                                          "net_bps": 1e4 * float(rr.mean() - cost), "xs_bps": 1e4 * float(xx.mean()),
                                          "event_days": int(len(np.unique(self.didx[k])))}
        return out


def month_concentration(m, h, ES, window="dev"):
    """How concentrated is the event excess across calendar months / episodes."""
    B = ES.B
    r, x = B[f"r{h}"], B[f"x{h}"]
    v = m & np.isfinite(r) & ES.windows(h)[window]
    if v.sum() < 10:
        return {}
    df = pd.DataFrame({"mo": ES.month[v], "x": x[v], "net": r[v] - 0.005, "d": ES.didx[v]})
    g = df.groupby("mo").agg(xs_sum=("x", "sum"), net_sum=("net", "sum"), n=("x", "size"), x_mean=("x", "mean"))
    tot_x, tot_n = g.xs_sum.sum(), g.net_sum.sum()
    gs = g.sort_values("xs_sum", ascending=False)
    gn = g.sort_values("net_sum", ascending=False)
    pos = g.xs_sum.clip(lower=0)
    eff = (pos.sum() ** 2 / (pos ** 2).sum()) if (pos ** 2).sum() > 0 else np.nan
    # leave-one-month-out mean xs (event weighted)
    lomo = [(tot_x - row.xs_sum) / (g.n.sum() - row.n) for _, row in g.iterrows()]
    out = {"months_with_events": int(len(g)), "share_months_xs_pos": float((g.x_mean > 0).mean()),
           "top1_share_xs": float(gs.xs_sum.iloc[:1].sum() / tot_x) if tot_x != 0 else np.nan,
           "top3_share_xs": float(gs.xs_sum.iloc[:3].sum() / tot_x) if tot_x != 0 else np.nan,
           "top5_share_xs": float(gs.xs_sum.iloc[:5].sum() / tot_x) if tot_x != 0 else np.nan,
           "top5_share_net": float(gn.net_sum.iloc[:5].sum() / tot_n) if tot_n != 0 else np.nan,
           "top5_share_events": float(gs.n.iloc[:5].sum() / g.n.sum()),
           "eff_n_months_pos_xs": float(eff),
           "lomo_min_xs_bps": 1e4 * float(np.min(lomo)), "lomo_max_xs_bps": 1e4 * float(np.max(lomo)),
           "xs_excl_top1_bps": 1e4 * float((tot_x - gs.xs_sum.iloc[0]) / (g.n.sum() - gs.n.iloc[0])),
           "xs_excl_top3_bps": 1e4 * float((tot_x - gs.xs_sum.iloc[:3].sum()) / max(g.n.sum() - gs.n.iloc[:3].sum(), 1)),
           "xs_excl_top5_bps": 1e4 * float((tot_x - gs.xs_sum.iloc[:5].sum()) / max(g.n.sum() - gs.n.iloc[:5].sum(), 1)),
           "top_months": [{"month": str(np.datetime64(int(k), "M")), "n": int(rw.n),
                           "xs_bps": 1e4 * float(rw.x_mean), "share_xs": float(rw.xs_sum / tot_x) if tot_x else None}
                          for k, rw in gs.head(6).iterrows()]}
    return out


# --------------------------------------------------------------------------- #
# Sim helpers (L.Sim maths; custom baselines for sparse event masks)
# --------------------------------------------------------------------------- #
def strip(res):
    return {k: v for k, v in res.items() if not k.startswith("_")}


def matched_mask(count_by_g, U, didx, seed):
    """Random U rows, exactly count_by_g[g] per trading day g (count-matched baseline)."""
    rng = np.random.default_rng(10_000 + seed)
    idx = np.flatnonzero(U)
    key = rng.random(len(idx))
    rk = pd.Series(key).groupby(didx[idx]).rank(method="first").values
    keep = rk <= count_by_g[didx[idx]]
    m = np.zeros(len(U), bool)
    m[idx[keep]] = True
    return m


def counts_by_g(mask, score, didx, ncal, top_k):
    """Per trading day: number of candidate rows the strategy can pick (min(top_k, n))."""
    m = mask.copy()
    if score is not None:
        m &= np.isfinite(score)
    c = np.bincount(didx[m], minlength=ncal).astype(float)
    return np.minimum(c, top_k)


def compare_custom(S, score, mask_strat, h, base_runs, **kw):
    """Strategy vs an already computed list of baseline runs (daily returns aligned)."""
    st = S.run(score, mask_strat, h, **kw)
    if "error" in st:
        return st
    rr = np.vstack([b["_daily_ret"] for b in base_runs])
    diff = st["_daily_ret"] - rr.mean(0)
    res = strip(st)
    res["base"] = {"cagr_mean": float(np.mean([b["cagr"] for b in base_runs])),
                   "cagr_sd": float(np.std([b["cagr"] for b in base_runs])),
                   "sharpe_mean": float(np.mean([b["sharpe"] for b in base_runs])),
                   "max_dd_mean": float(np.mean([b["max_dd"] for b in base_runs])),
                   "exposure_mean": float(np.mean([b["exposure"] for b in base_runs])),
                   "mean_trade_net": float(np.mean([b["mean_trade_net"] for b in base_runs])),
                   "by_year_mean": {y: float(np.mean([b["by_year"].get(y, np.nan) for b in base_runs]))
                                    for y in base_runs[0]["by_year"]}}
    res["excess_cagr"] = st["cagr"] - res["base"]["cagr_mean"]
    res["excess_nw_t"] = L.nw_t(diff, lag=h)
    res["excess_ann_return"] = float(diff.mean() * 252)
    res["_daily_ret"] = st["_daily_ret"]
    res["_dates"] = st["_dates"]
    res["_base_daily"] = rr.mean(0)
    return res


def runs_random(S, mask, h, seeds=(1, 2, 3, 4, 5), **kw):
    return [S.run(None, mask, h, random_seed=s, **kw) for s in seeds]


def summarize_runs(runs):
    """Mean of several (random) runs as a pseudo-strategy."""
    rr = np.vstack([b["_daily_ret"] for b in runs])
    out = {"cagr": float(np.mean([b["cagr"] for b in runs])), "cagr_sd": float(np.std([b["cagr"] for b in runs])),
           "sharpe": float(np.mean([b["sharpe"] for b in runs])), "max_dd": float(np.mean([b["max_dd"] for b in runs])),
           "exposure": float(np.mean([b["exposure"] for b in runs])),
           "trades": float(np.mean([b["trades"] for b in runs])),
           "hit_rate": float(np.mean([b["hit_rate"] for b in runs])),
           "mean_trade_net": float(np.mean([b["mean_trade_net"] for b in runs])),
           "by_year": {y: float(np.mean([b["by_year"].get(y, np.nan) for b in runs])) for y in runs[0]["by_year"]},
           "_daily_ret": rr.mean(0), "_dates": runs[0]["_dates"]}
    return out


def excess_stats(a_daily, b_daily, h):
    d = np.asarray(a_daily) - np.asarray(b_daily)
    return {"excess_ann_return": float(d.mean() * 252), "excess_nw_t": L.nw_t(d, lag=h)}


def eq_stats(daily, dates=None):
    r = np.asarray(daily, dtype="float64")
    eq = np.cumprod(1 + r)
    yrs = max(len(r) / 252.0, 1e-9)
    if dates is not None:
        dd_ = np.asarray(dates).astype("datetime64[D]")
        yrs = max((dd_[-1] - dd_[0]).astype(int) / 365.25, 1e-9)
    dd = eq / np.maximum.accumulate(eq) - 1
    out = {"cagr": float(eq[-1] ** (1 / yrs) - 1), "sharpe": float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else np.nan,
           "max_dd": float(dd.min()), "ann_vol": float(r.std() * np.sqrt(252)), "total_return": float(eq[-1] - 1)}
    if dates is not None:
        s = pd.Series(eq, index=pd.DatetimeIndex(np.asarray(dates).astype("datetime64[D]")))
        prev = 1.0
        by = {}
        for y, g in s.groupby(s.index.year):
            by[int(y)] = float(g.iloc[-1] / prev - 1)
            prev = g.iloc[-1]
        out["by_year"] = by
    return out


class SimX(L.Sim):
    """L.Sim with one extra output: _invested (daily equity-weighted invested fraction).
    run() is a verbatim copy of lablib.Sim.run except for that line."""

    def run(self, score, mask, h, step=5, top_k=20, side="long", exit_rule="time",
            pt=2.0, sl=1.5, cost_bps=50.0, start=L.DEV[0], end_exit=L.DEV[1], cash_yield=0.0,
            random_seed=None, sizing="slot", select_quantile=None, keep_trades=False):
        """score: array aligned to rows (higher = better long candidate) or None
        with random_seed set. select_quantile=(lo, hi): instead of top_k, hold all
        rows whose same-date score percentile is in [lo, hi] (equal weight)."""
        fw = self.fw
        mask = np.asarray(mask, bool)
        if score is not None:
            score = np.asarray(score, dtype="float64")
        rng = np.random.default_rng(random_seed) if random_seed is not None else None
        g0, g_sig_last, g_end = self._window(start, end_exit, h, step)
        S = int(np.ceil(h / step))
        period = S * step
        sigs = list(range(g0, g_sig_last + 1, step))
        if not sigs:
            return {"error": "empty window"}
        D0, D1 = g0, min(g_end, sigs[-1] + period)
        nd = D1 - D0 + 1
        sleeve_eq = np.ones((S, nd))
        invested = np.zeros((S, nd))
        cost = cost_bps / 1e4
        sgn = 1.0 if side == "long" else -1.0
        trades = []
        n_forced = 0
        n_picks_total = 0
        last_w = np.zeros(S, dtype=int)
        lb_cs = fw.lb_cs
        hk = np.arange(1, h + 1)
        for j, g in enumerate(sigs):
            s = j % S
            g_next = min(g + period, D1)
            E = sleeve_eq[s, g - D0]
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
            if len(pick) == 0 or seg_len == 0:
                sleeve_eq[s, g - D0 + 1:g_next - D0 + 1] = E * (1 + cash_yield) ** ((days - g) / 252.0)
                last_w[s] = g_next - D0
                continue
            # bar matrix for picks
            rows_k = pick[:, None] + hk[None, :]
            rk = np.clip(rows_k, 0, self.n - 1)
            v = (rows_k <= fw.end[pick][:, None]) & ((lb_cs[rk] - lb_cs[pick][:, None]) == 0) \
                & (self.didx[rk] <= g_next)
            v = np.cumprod(v, axis=1).astype(bool)
            e = np.where(v[:, 0], self.o[rk[:, 0]], np.nan)
            ok = v[:, 0] & np.isfinite(e) & (e > 0)
            pick, rk, v, e = pick[ok], rk[ok], v[ok], e[ok]
            npk = len(pick)
            n_picks_total += npk
            if npk == 0:
                sleeve_eq[s, g - D0 + 1:g_next - D0 + 1] = E * (1 + cash_yield) ** ((days - g) / 252.0)
                last_w[s] = g_next - D0
                continue
            nvalid = v.sum(1)
            px = np.where(v, self.c[rk], np.nan)
            Kx = nvalid.copy()            # exit bar (1-based)
            X = px[np.arange(npk), Kx - 1]
            if exit_rule == "barrier":
                vol = self.atr[pick]
                up_d, dn_d = pt * vol, sl * vol
                if side == "long":
                    tgt, stp = e * (1 + up_d), e * (1 - dn_d)
                else:
                    tgt, stp = e * (1 - up_d), e * (1 + dn_d)
                done = np.zeros(npk, bool)
                for k in range(h):
                    act = v[:, k] & ~done
                    if not act.any():
                        continue
                    ok_, hk_, lk_ = self.o[rk[:, k]], self.hi[rk[:, k]], self.lo[rk[:, k]]
                    if side == "long":
                        gs, hs = act & (ok_ <= stp), act & (lk_ <= stp)
                        gt, ht = act & (ok_ >= tgt), act & (hk_ >= tgt)
                    else:
                        gs, hs = act & (ok_ >= stp), act & (hk_ >= stp)
                        gt, ht = act & (ok_ <= tgt), act & (lk_ <= tgt)
                    hs, gt = hs & ~gs, gt & ~gs & ~hs
                    ht = ht & ~gs & ~hs & ~gt
                    for m_, p_ in ((gs, ok_), (hs, stp), (gt, ok_), (ht, tgt)):
                        if m_.any():
                            X[m_] = p_[m_]
                            Kx[m_] = k + 1
                            px[m_, k] = p_[m_]
                            done |= m_
            forced = (nvalid < h) & (Kx == nvalid)
            n_forced += int(forced.sum())
            # mark-to-market path
            bd = np.where(v, self.didx[rk], 10 ** 9)
            bd = np.where(hk[None, :] <= Kx[:, None], bd, 10 ** 9)
            exit_day = self.didx[rk[np.arange(npk), Kx - 1]]
            cnt = (bd[:, None, :] <= days[None, :, None]).sum(2)          # (npk, nd)
            idx = np.clip(cnt - 1, 0, h - 1)
            price = np.take_along_axis(np.nan_to_num(px, nan=0.0), idx, axis=1)
            rel = price / e[:, None]
            gross = np.where(cnt == 0, 1.0, (1 + sgn * (rel - 1)) * (1 - cost / 2))
            after = days[None, :] >= exit_day[:, None]
            gross = np.where(after, gross * (1 - cost / 2), gross)
            w = (1.0 / top_k) if sizing == "slot" and select_quantile is None else (1.0 / npk)
            cash_frac = max(0.0, 1 - w * npk)
            cg = (1 + cash_yield) ** ((days - g) / 252.0)
            path = cash_frac * cg + w * gross.sum(0)
            sleeve_eq[s, g - D0 + 1:g_next - D0 + 1] = E * path
            invested[s, g - D0 + 1:g_next - D0 + 1] = w * (~after).sum(0)
            last_w[s] = g_next - D0
            net = sgn * (X / e - 1) - cost
            if keep_trades:
                for a in range(npk):
                    trades.append((str(self.cal[g]), int(pick[a]), float(net[a]), int(Kx[a]), bool(forced[a])))
            else:
                trades.append(np.c_[net, Kx, forced])
            # carry sleeve equity flat after g_next is handled by the next signal of this sleeve
        # sleeves that have not started yet stay at 1 (cash); after a sleeve's last
        # window ends, carry its final equity forward to the end of the window.
        for s_ in range(S):
            lw = last_w[s_]
            if 0 < lw < nd - 1:
                sleeve_eq[s_, lw + 1:] = sleeve_eq[s_, lw]
        eq = sleeve_eq.mean(0)
        inv_daily = (sleeve_eq * invested).sum(0) / np.maximum(sleeve_eq.sum(0), 1e-12)
        dates = self.cal[D0:D1 + 1]
        r = np.r_[0.0, eq[1:] / eq[:-1] - 1]
        yrs = max((dates[-1] - dates[0]).astype(int) / 365.25, 1e-9)
        dd = eq / np.maximum.accumulate(eq) - 1
        if keep_trades:
            tn = np.array([t[2] for t in trades]) if trades else np.array([])
            tk = np.array([t[3] for t in trades]) if trades else np.array([])
        else:
            T = np.vstack(trades) if trades else np.zeros((0, 3))
            tn, tk = T[:, 0], T[:, 1]
        ser = pd.Series(eq, index=pd.DatetimeIndex(dates))
        by_year = {int(y): float(gq.iloc[-1] / gq.iloc[0] - 1) for y, gq in ser.groupby(ser.index.year)}
        out = {
            "cagr": float(eq[-1] ** (1 / yrs) - 1), "total_return": float(eq[-1] - 1),
            "sharpe": float(r.mean() / r.std() * np.sqrt(252)) if r.std() > 0 else np.nan,
            "max_dd": float(dd.min()), "ann_vol": float(r.std() * np.sqrt(252)),
            "exposure": float(invested.mean()),
            "trades": int(len(tn)), "hit_rate": float((tn > 0).mean()) if len(tn) else np.nan,
            "mean_trade_net": float(tn.mean()) if len(tn) else np.nan,
            "median_trade_net": float(np.median(tn)) if len(tn) else np.nan,
            "avg_bars": float(tk.mean()) if len(tk) else np.nan, "forced_exits": int(n_forced),
            "by_year": by_year,
            "params": dict(h=h, step=step, top_k=top_k, side=side, exit_rule=exit_rule, pt=pt, sl=sl,
                           cost_bps=cost_bps, start=start, end_exit=end_exit, sizing=sizing,
                           select_quantile=select_quantile, random_seed=random_seed),
            "_daily_ret": r, "_dates": dates, "_equity": eq, "_invested": inv_daily,
        }
        if keep_trades:
            out["_trades"] = trades
        return out
