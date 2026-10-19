"""Independent verifier simulator for R3_book (written from scratch; does NOT import R3_book's booksim/bk_setup).

Book conventions re-implemented from the frozen spec (PREREG_R3 / lablib docstring):
weekly signals (step 5), 4 staggered sleeves (each rebalances every 20 trading days), top-20 by score among the
mask (finite score), slot sizing 1/20 of sleeve equity, entry at the entity's next open, exit at the close of
bar 20 or at the last valid bar (segment end / label_block / bar date beyond the sleeve's next rebalance),
half the round-trip cost at entry and half at exit, idle cash at 0 (or Nifty 1D Rate if cash_lv given).
Modes:  'E0' = frozen;  'X3' = hold every position due at the rebalance close through that close, at the next
open sell names not in the new top-20 (exit cost there) and keep names still in the new top-20 (no costs,
re-referenced at the rebalance close, reset to 1/20 of sleeve equity).
ew=True: all mask names, equal weight over the valid ones (the EW-universe yardstick)."""
import sys

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402  (data loading only)

H, STEP, NSL, TOPK = 20, 5, 4, 20
PERIOD = NSL * STEP
HK = np.arange(1, H + 1)


def my_nw_t(x, lag=20):
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    n = len(x)
    m = x.mean()
    u = x - m
    v = u @ u / n
    for k in range(1, lag + 1):
        v += 2.0 * (1.0 - k / (lag + 1.0)) * (u[k:] @ u[:-k]) / n
    return float(m / np.sqrt(v / n))


class Data:
    def __init__(self, extra_panel=(), extra_feat=()):
        P = L.load_panel(["date", "entity", "open", "close", "seg_break", "label_block"] + list(extra_panel))
        F = L.load_features(["elig_base"] + list(extra_feat))
        self.P, self.F = P, F
        self.E = F["elig_base"].values.astype(bool)
        d = P["date"].values.astype("datetime64[D]")
        ent = P["entity"].values
        self.o = P["open"].values.astype(float)
        self.c = P["close"].values.astype(float)
        self.n = len(P)
        newseg = np.r_[True, ent[1:] != ent[:-1]] | P["seg_break"].values.astype(bool)
        segid = np.cumsum(newseg) - 1
        lastrow = np.flatnonzero(np.r_[segid[1:] != segid[:-1], True])
        self.segid = segid
        self.seg_end = lastrow[segid]
        self.seg_start = np.flatnonzero(newseg)[segid]
        self.lbc = np.cumsum(P["label_block"].values.astype(bool))
        self.cal = np.unique(d)
        self.di = np.searchsorted(self.cal, d)
        order = np.argsort(self.di, kind="stable")
        self.order = order
        self.bnd = np.searchsorted(self.di[order], np.arange(len(self.cal) + 1))

    def rows_on(self, g):
        return self.order[self.bnd[g]:self.bnd[g + 1]]

    def gidx(self, date_str):
        return int(np.searchsorted(self.cal, np.datetime64(date_str)))

    def g_last(self, end):
        if end is None:
            return len(self.cal) - 1
        return int(np.searchsorted(self.cal, np.datetime64(end), side="right")) - 1


def _valid(D, p, g_next):
    rows = p[:, None] + HK[None, :]
    rc = np.minimum(rows, D.n - 1)
    ok = (rows <= D.seg_end[p][:, None]) & (D.lbc[rc] == D.lbc[p][:, None]) & (D.di[rc] <= g_next)
    ok = np.cumprod(ok, axis=1).astype(bool)
    return ok.sum(1), rc


def run_book(D, g0, end, score=None, mask=None, seed=None, mode="E0", cost_rt=None, flat=0.005, cash_lv=None,
             ew=False, wfun=None, fill=None, early=None):
    """wfun(pick)->fraction of sleeve equity per valid pick (default 1/20); fill: per-row multiplier of the weight
    (participation cap); early: None | ('e2w', prank, thr) | ('e2d', prank, thr) | ('e3', frac) -> exit at the
    next bar's open after the first trigger close (bars 1..K-1)."""
    mask = D.E if mask is None else mask
    g_le = D.g_last(end)
    sigs = list(range(g0, g_le - H - 1 + 1, STEP))
    D0, D1 = g0, min(g_le, sigs[-1] + PERIOD)
    nd = D1 - D0 + 1
    rng = np.random.default_rng(seed) if seed is not None else None
    wins = []
    for j, g in enumerate(sigs):
        g_next = min(g + PERIOD, D1)
        cand = D.rows_on(g)
        cand = cand[mask[cand]]
        if ew:
            pick = cand
        elif rng is None:
            cand = cand[np.isfinite(score[cand])]
            pick = cand[np.argsort(-score[cand], kind="stable")[:TOPK]]
        else:
            kk = min(TOPK, len(cand))
            pick = rng.choice(cand, size=kk, replace=False) if kk else cand[:0]
        if len(pick):
            K, rc = _valid(D, pick, g_next)
            e = D.o[np.minimum(pick + 1, D.n - 1)]
            good = (K > 0) & np.isfinite(e) & (e > 0)
            pick, K, e, rc = pick[good], K[good], e[good], rc[good]
        else:
            K, e, rc = np.zeros(0, int), np.zeros(0), np.zeros((0, H), int)
        npk = len(pick)
        pm = D.c[rc].copy() if npk else np.zeros((0, H))
        n_early = 0
        if early is not None and npk:
            bars_ok = HK[None, :] <= (K[:, None] - 1)                     # trigger bar b must have a next bar
            if early[0] == "e3":
                cond = bars_ok & (D.c[rc] <= early[1] * e[:, None])
            else:
                pr = early[1][rc]
                cond = bars_ok & (pr <= early[2])
                if early[0] == "e2w":
                    cond &= np.isin(D.di[rc], [g + STEP * mm for mm in range(1, NSL)])
            hit = cond.any(1)
            if hit.any():
                b1 = np.argmax(cond, 1) + 1                                 # 1-based trigger bar
                ii = np.flatnonzero(hit)
                K = K.copy()
                K[ii] = b1[ii] + 1
                pm[ii, K[ii] - 1] = D.o[rc[ii, K[ii] - 1]]
                n_early = int(hit.sum())
        wins.append({"g": g, "g_next": g_next, "p": pick, "K": K, "e": e, "rc": rc, "ex": pick + K, "pm": pm,
                     "n_early": n_early,
                     "carried": np.zeros(npk, bool), "hold": np.zeros(npk, bool), "leg_idx": np.zeros(0, int)})
    if mode == "X3":
        for j in range(NSL, len(wins)):
            w, pw = wins[j], wins[j - NSL]
            if pw["g_next"] != w["g"] or len(pw["p"]) == 0:
                continue
            at_close = D.di[pw["ex"]] == w["g"]
            pos_new = {int(r): i for i, r in enumerate(w["p"])}
            leg = []
            for i in np.flatnonzero(at_close):
                exr = int(pw["ex"][i])
                if exr in pos_new:
                    pw["hold"][i] = True
                    w["carried"][pos_new[exr]] = True
                else:
                    x = exr + 1
                    if x <= D.seg_end[exr] and D.lbc[x] == D.lbc[exr] and D.di[x] <= w["g_next"] \
                            and np.isfinite(D.o[x]) and D.o[x] > 0:
                        pw["hold"][i] = True
                        leg.append(i)
            w["leg_idx"] = np.array(leg, dtype=int)
    seq = np.ones((NSL, nd))
    last = [-1] * NSL
    st = {"n_pos": 0, "n_carried": 0, "n_legacy_open": 0, "buys": 0.0, "sells": 0.0, "cost": 0.0, "rt": 0,
          "n_early": 0, "by_year_trade": {}}
    for j, w in enumerate(wins):
        s = j % NSL
        g, g_next = w["g"], w["g_next"]
        Eq = seq[s, g - D0]
        days = np.arange(g + 1, g_next + 1)
        cg = (cash_lv[days] / cash_lv[g]) if cash_lv is not None else np.ones(len(days))
        npk = len(w["p"])
        if ew:
            wts = np.full(npk, 1.0 / npk) if npk else np.zeros(0)
        elif wfun is not None and npk:
            wts = wfun(w["p"])
        else:
            wts = np.full(npk, 1.0 / TOPK)
        if fill is not None and npk:
            wts = wts * fill[w["p"]]
        A = Eq * wts
        val = Eq * max(0.0, 1.0 - float(wts.sum())) * cg
        if npk:
            p, K, rc = w["p"], w["K"], w["rc"]
            cr = cost_rt[p] if cost_rt is not None else np.full(npk, flat)
            w["cr"] = cr
            bday = np.where(HK[None, :] <= K[:, None], D.di[rc], 10 ** 9)          # (npk, H)
            m = (bday[:, None, :] <= days[None, :, None]).sum(2)                  # (npk, nd_w)
            px = np.take_along_axis(w["pm"], np.maximum(m - 1, 0), axis=1)
            ref = np.where(w["carried"], D.c[p], w["e"])
            fin = np.where(w["carried"], 1.0, 1.0 - cr / 2)
            v = np.where(m > 0, A[:, None] * fin[:, None] * px / ref[:, None], A[:, None])
            exd = D.di[w["ex"]]
            fout = np.where(w["hold"], 1.0, 1.0 - cr / 2)
            v = np.where(days[None, :] >= exd[:, None], v * fout[:, None], v)
            if cash_lv is not None:
                v = np.where(days[None, :] > exd[:, None], v * cash_lv[days][None, :] / cash_lv[exd][:, None], v)
            val = val + v.sum(0)
            w["v_end"] = A * fin * w["pm"][np.arange(npk), K - 1] / ref
            nb = ~w["carried"]
            st["buys"] += float(A[nb].sum()) / NSL
            st["cost"] += float((A[nb] * cr[nb] / 2).sum()) / NSL
            ns = ~w["hold"]
            st["sells"] += float(w["v_end"][ns].sum()) / NSL
            st["cost"] += float((w["v_end"][ns] * cr[ns] / 2).sum()) / NSL
            ent_y = D.cal[D.di[p + 1]].astype("datetime64[Y]").astype(int) + 1970
            ex_y = D.cal[exd].astype("datetime64[Y]").astype(int) + 1970
            for yy, aa in zip(ent_y[nb], A[nb]):
                st["by_year_trade"][int(yy)] = st["by_year_trade"].get(int(yy), 0.0) + float(aa) / NSL
            for yy, aa in zip(ex_y[ns], w["v_end"][ns]):
                st["by_year_trade"][int(yy)] = st["by_year_trade"].get(int(yy), 0.0) + float(aa) / NSL
            st["n_early"] += w["n_early"]
            st["rt"] += int(ns.sum())
            st["n_pos"] += npk
            st["n_carried"] += int(w["carried"].sum())
        if len(w["leg_idx"]):
            pw = wins[j - NSL]
            li = w["leg_idx"]
            exr = pw["ex"][li]
            gap = D.o[exr + 1] / D.c[exr]
            Lv = pw["v_end"][li]
            adj = Lv * (gap * (1.0 - pw["cr"][li] / 2) - 1.0)
            val = val + (adj[:, None] * (days[None, :] >= D.di[exr + 1][:, None])).sum(0)
            st["n_legacy_open"] += len(li)
            ly = D.cal[D.di[exr + 1]].astype("datetime64[Y]").astype(int) + 1970
            for yy, aa in zip(ly, Lv * gap):
                st["by_year_trade"][int(yy)] = st["by_year_trade"].get(int(yy), 0.0) + float(aa) / NSL
            st["sells"] += float((Lv * gap).sum()) / NSL
            st["cost"] += float((Lv * gap * pw["cr"][li] / 2).sum()) / NSL
            st["rt"] += len(li)
        seq[s, g - D0 + 1:g_next - D0 + 1] = val
        last[s] = g_next - D0
    for s in range(NSL):
        if 0 <= last[s] < nd - 1:
            seq[s, last[s] + 1:] = seq[s, last[s]]
    eq = seq.mean(0)
    r = np.r_[0.0, eq[1:] / eq[:-1] - 1.0]
    return {"dates": D.cal[D0:D1 + 1], "r": r, "eq": eq, "stats": st}


def phase_series(D, start, end, **kw):
    g0 = D.gidx(start)
    out, sts = [], []
    for k in range(STEP):
        res = run_book(D, g0 + k, end, **kw)
        out.append(pd.Series(res["r"], index=pd.DatetimeIndex(res["dates"])))
        sts.append(res["stats"])
    return out, sts


def seeds_mean(D, start, end, seeds=(1, 2, 3, 4, 5), **kw):
    """per phase: mean daily return over random seeds (5-seed random band), list of 5 phase series"""
    g0 = D.gidx(start)
    out = []
    for k in range(STEP):
        rs = [run_book(D, g0 + k, end, seed=sd, **kw) for sd in seeds]
        out.append(pd.Series(np.mean([x["r"] for x in rs], 0), index=pd.DatetimeIndex(rs[0]["dates"])))
    return out


def pavg(series_list, common=None):
    if common is None:
        common = series_list[0].index
        for x in series_list[1:]:
            common = common.intersection(x.index)
    return pd.Series(np.mean([x.reindex(common).values for x in series_list], 0), index=common)


def common_of(*lists):
    c = None
    for lst in lists:
        for x in lst:
            c = x.index if c is None else c.intersection(x.index)
    return c


def cagr(r):
    r = np.asarray(r)
    return float(np.prod(1 + r) ** (252.0 / len(r)) - 1)


def maxdd(r):
    eq = np.cumprod(1 + np.asarray(r))
    return float((eq / np.maximum.accumulate(eq) - 1).min())


def sharpe(r):
    r = np.asarray(r)
    return float(r.mean() / r.std() * np.sqrt(252))
