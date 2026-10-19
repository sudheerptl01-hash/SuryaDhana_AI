"""Fast replica of lablib.portfolio_sim (exit_rule='time') with cached trade returns and
per-date candidate lists. Selection, RNG sequence, sleeve accounting and statistics are copied
from lablib so results match exactly (verified in s5_luck.py)."""
import numpy as np
import pandas as pd

NAN = np.nan


class Sim:
    def __init__(self, P, fw, h):
        self.h = h
        self.dates = P["date"].values.astype("datetime64[D]")
        e = fw.at(P["open"].values, 1)
        x = fw.at(P["close"].values, h)
        tr = x / e - 1
        if np.isnan(tr).any():
            last = np.full(len(P), NAN)
            for k in range(1, h + 1):
                xk = fw.at(P["close"].values, k)
                last = np.where(np.isnan(xk), last, xk)
            fb = last / e - 1
            tr = np.where(np.isnan(tr) & np.isfinite(e), fb, tr)
        self.tr_ret_long = tr
        self._cache = {}

    def _groups(self, m_key, m):
        if m_key in self._cache:
            return self._cache[m_key]
        ok = m & np.isfinite(self.tr_ret_long)
        idx = np.flatnonzero(ok)
        d = self.dates[idx]
        brk = np.flatnonzero(np.r_[True, d[1:] != d[:-1]]) if len(idx) else np.array([], int)
        # rows sorted by entity then date -> need grouping by date: sort stable by date
        order = np.argsort(d, kind="stable")
        idx_s, d_s = idx[order], d[order]
        b = np.flatnonzero(np.r_[True, d_s[1:] != d_s[:-1]])
        e_ = np.r_[b[1:], len(idx_s)]
        groups = {d_s[s]: idx_s[s:t] for s, t in zip(b, e_)}
        self._cache[m_key] = groups
        return groups

    def run(self, score, mask, m_key, step=5, top_k=20, side="long", cost_bps=50.0, start="2023-01-01",
            end=None, random_seed=None, return_cohorts=False):
        h = self.h
        sgn = 1.0 if side == "long" else -1.0
        tr_ret = sgn * self.tr_ret_long
        dates = self.dates
        if random_seed is None:
            s = np.asarray(score, dtype="float64")
            m = np.asarray(mask, bool) & ~np.isnan(s)
            groups = self._groups((m_key, "rand"), np.asarray(mask, bool))
        else:
            s = None
            m = np.asarray(mask, bool)
            groups = self._groups((m_key, "rand"), m)
        cal = np.unique(dates[m])
        cal = cal[cal >= np.datetime64(start)]
        if end is not None:
            cal = cal[cal <= np.datetime64(end)]
        sig_dates = cal[::step]
        rng = np.random.default_rng(random_seed if random_seed is not None else 0)
        cohort_rets, cohort_dates, picks_all = [], [], []
        for d in sig_dates:
            cand = groups.get(d)
            if cand is None or len(cand) == 0:
                cohort_rets.append(0.0)
                cohort_dates.append(d)
                continue
            if random_seed is None:
                cand = cand[~np.isnan(s[cand])]
                if len(cand) == 0:
                    cohort_rets.append(0.0)
                    cohort_dates.append(d)
                    continue
            if random_seed is not None:
                pick = rng.choice(cand, size=min(top_k, len(cand)), replace=False)
            else:
                sc = s[cand]
                order = np.argsort(-sc if side == "long" else sc)
                pick = cand[order][:top_k]
            net = tr_ret[pick] - cost_bps / 1e4
            cohort_rets.append(float(np.mean(net)))
            cohort_dates.append(d)
            picks_all.append(pick)
        cr = np.array(cohort_rets)
        S = int(np.ceil(h / step))
        sleeves = np.ones(S)
        eq = []
        for c, r in enumerate(cr):
            sleeves[c % S] *= (1 + r)
            eq.append(sleeves.mean())
        eq = np.array(eq)
        stepret = np.r_[eq[0] - 1, eq[1:] / eq[:-1] - 1]
        years = max((cohort_dates[-1] - cohort_dates[0]).astype(int) / 365.25, 1e-9) + h / 252
        allpick = np.concatenate(picks_all) if picks_all else np.array([], int)
        tnet = tr_ret[allpick] - cost_bps / 1e4
        dd = eq / np.maximum.accumulate(eq) - 1
        yr = pd.Series(stepret, index=pd.DatetimeIndex(cohort_dates))
        by_year = (yr.groupby(yr.index.year).apply(lambda s_: float(np.prod(1 + s_) - 1))).to_dict()
        res = {"trades": int(len(allpick)), "hit_rate": float((tnet > 0).mean()) if len(tnet) else NAN,
               "mean_trade_net": float(tnet.mean()) if len(tnet) else NAN,
               "cagr": float(eq[-1] ** (1 / years) - 1), "total_return": float(eq[-1] - 1),
               "sharpe": float(stepret.mean() / stepret.std() * np.sqrt(252 / step)) if stepret.std() > 0 else NAN,
               "max_dd": float(dd.min()), "by_year": {int(k): v for k, v in by_year.items()}}
        if return_cohorts:
            res["cohort_rets"] = cr
            res["cohort_dates"] = np.array(cohort_dates)
            res["picks"] = allpick
        return res
