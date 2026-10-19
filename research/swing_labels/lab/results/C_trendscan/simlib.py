"""Fast, exact replica of lablib.portfolio_sim (exit_rule='time') + adaptive-exit trade engine.

Selection, RNG sequence, sleeve accounting and statistics follow lablib.portfolio_sim line by line
(verified in s4_eval.py against L.portfolio_sim).  Extra: cohorts can be re-costed without re-picking,
and the same picks can be exited with alternative executable rules (ATR trailing stop, running
trend-scan exit), all decided only from information available at the decision time.
"""
import numpy as np
import pandas as pd

NAN = np.nan


class Engine:
    def __init__(self, P, F, fw, hmax=20):
        self.n = len(P)
        self.dates = P["date"].values.astype("datetime64[D]")
        self.o = P["open"].values.astype("float64")
        self.hi = P["high"].values.astype("float64")
        self.lo = P["low"].values.astype("float64")
        self.c = P["close"].values.astype("float64")
        self.atr = F["atr_pct"].values.astype("float64")
        self.end = fw.end
        self.fw = fw
        self.entry = fw.at(self.o, 1)
        self._fixed = {}
        self._groups = {}

    # ---------------------------------------------------------------- per-row helpers
    def at_rows(self, arr, idx, k):
        j = idx + k
        ok = j <= self.end[idx]
        out = np.full(len(idx), NAN)
        out[ok] = arr[j[ok]]
        return out

    def fixed_ret(self, h):
        """portfolio_sim time-exit long return incl. forced-exit fallback (last available close)."""
        if h in self._fixed:
            return self._fixed[h]
        e = self.entry
        x = self.fw.at(self.c, h)
        tr = x / e - 1
        if np.isnan(tr).any():
            last = np.full(self.n, NAN)
            for k in range(1, h + 1):
                xk = self.fw.at(self.c, k)
                last = np.where(np.isnan(xk), last, xk)
            fb = last / e - 1
            tr = np.where(np.isnan(tr) & np.isfinite(e), fb, tr)
        self._fixed[h] = tr
        return tr

    def groups(self, key, mask, h):
        k2 = (key, h)
        if k2 in self._groups:
            return self._groups[k2]
        ok = np.asarray(mask, bool) & np.isfinite(self.fixed_ret(h))
        idx = np.flatnonzero(ok)
        d = self.dates[idx]
        order = np.argsort(d, kind="stable")
        idx_s, d_s = idx[order], d[order]
        b = np.flatnonzero(np.r_[True, d_s[1:] != d_s[:-1]])
        e_ = np.r_[b[1:], len(idx_s)]
        g = {d_s[s]: idx_s[s:t] for s, t in zip(b, e_)}
        self._groups[k2] = g
        return g

    # ---------------------------------------------------------------- selection (= portfolio_sim)
    def pick(self, score, mask, key, h, step=5, top_k=20, side="long", start="2023-01-01", end=None,
             random_seed=None):
        dates = self.dates
        mask = np.asarray(mask, bool)
        if random_seed is None:
            s = np.asarray(score, dtype="float64")
            m = mask & ~np.isnan(s)
        else:
            s = None
            m = mask
        groups = self.groups(key, mask, h)
        cal = np.unique(dates[m])
        cal = cal[cal >= np.datetime64(start)]
        if end is not None:
            cal = cal[cal <= np.datetime64(end)]
        sig_dates = cal[::step]
        rng = np.random.default_rng(random_seed if random_seed is not None else 0)
        out = []
        for d in sig_dates:
            cand = groups.get(d)
            if cand is None or len(cand) == 0:
                out.append((d, np.array([], int)))
                continue
            if random_seed is not None:
                pk = rng.choice(cand, size=min(top_k, len(cand)), replace=False)
            else:
                cand = cand[~np.isnan(s[cand])]
                sc = s[cand]
                order = np.argsort(-sc if side == "long" else sc)
                pk = cand[order][:top_k]
            out.append((d, pk))
        return out

    # ---------------------------------------------------------------- exits for a set of rows
    def exit_returns(self, idx, rule, side="long", h=10, m=3.0, hmax=20, t_exit=0.0):
        """Gross side-signed return and bars held for rows idx (entry open[t+1]).
        rule: 'fixed' (close[t+h], forced exit = last close), 'atr' (trailing stop m*atr_pct[t]
        from the highest close, gap-aware, max hmax bars), 'tsexit' (exit next open once the
        running trend-scan t-value of the realised path since entry drops below t_exit, checked
        from bar 5 on, max hmax bars)."""
        sg = 1.0 if side == "long" else -1.0
        idx = np.asarray(idx, int)
        e = self.entry[idx]
        if rule == "fixed":
            r = sg * self.fixed_ret(h)[idx]
            return r, np.full(len(idx), float(h))
        N = len(idx)
        ret = np.full(N, NAN)
        held = np.full(N, NAN)
        open_ = np.isfinite(e)
        last_c = np.full(N, NAN)
        last_k = np.zeros(N)
        if rule == "atr":
            a = self.atr[idx]
            stop = e * (1 - sg * m * a)
            for k in range(1, hmax + 1):
                ok_, hk, lk, ck = (self.at_rows(x, idx, k) for x in (self.o, self.hi, self.lo, self.c))
                avail = np.isfinite(ck)
                if side == "long":
                    gap = open_ & avail & (ok_ <= stop)
                    hit = open_ & avail & ~gap & (lk <= stop)
                else:
                    gap = open_ & avail & (ok_ >= stop)
                    hit = open_ & avail & ~gap & (hk >= stop)
                ret[gap] = sg * (ok_[gap] / e[gap] - 1)
                held[gap] = k
                ret[hit] = sg * (stop[hit] / e[hit] - 1)
                held[hit] = k
                open_ = open_ & ~(gap | hit)
                upd = open_ & avail
                last_c = np.where(upd, ck, last_c)
                last_k = np.where(upd, k, last_k)
                if side == "long":
                    stop = np.where(upd, np.maximum(stop, ck * (1 - m * a)), stop)
                else:
                    stop = np.where(upd, np.minimum(stop, ck * (1 + m * a)), stop)
            fin = open_
            ret[fin] = sg * (last_c[fin] / e[fin] - 1)
            held[fin] = last_k[fin]
            return ret, held
        if rule == "tsexit":
            Sy = np.zeros(N)
            Sxy = np.zeros(N)
            Syy = np.zeros(N)
            pending = np.zeros(N, bool)  # exit decided at close of k -> fill at open k+1
            for k in range(1, hmax + 1):
                ok_, ck = self.at_rows(self.o, idx, k), self.at_rows(self.c, idx, k)
                avail = np.isfinite(ck)
                # execute pending exits at today's open
                ex = open_ & pending & avail
                ret[ex] = sg * (ok_[ex] / e[ex] - 1)
                held[ex] = k - 1 + 0.0  # held through close k-1, sold at open k
                open_ = open_ & ~ex
                upd = open_ & avail
                last_c = np.where(upd, ck, last_c)
                last_k = np.where(upd, k, last_k)
                y = np.where(upd, sg * np.log(ck / e), 0.0)
                Sy += y
                Sxy += k * y
                Syy += y * y
                if k >= 5 and k < hmax:
                    Nn = k + 1
                    Sx = k * (k + 1) / 2.0
                    Sxx = k * (k + 1) * (2 * k + 1) / 6.0
                    sxx = Sxx - Sx * Sx / Nn
                    sxy = Sxy - Sx * Sy / Nn
                    syy = Syy - Sy * Sy / Nn
                    b = sxy / sxx
                    s2 = np.maximum(np.maximum(syy - b * sxy, 0) / (Nn - 2), 1e-6)
                    t = b / np.sqrt(s2 / sxx)
                    pending = upd & (t < t_exit)
            fin = open_
            ret[fin] = sg * (last_c[fin] / e[fin] - 1)
            held[fin] = last_k[fin]
            return ret, held
        raise ValueError(rule)


def stats_from_cohorts(cohort_gross, cohort_dates, h_slots, step, cost_bps, trade_net=None, hold=None):
    """lablib.portfolio_sim statistics from cohort mean GROSS returns (cost subtracted here).
    h_slots = holding length used for sleeve count S = ceil(h_slots/step)."""
    cr = np.array([g - cost_bps / 1e4 if np.isfinite(g) else 0.0 for g in cohort_gross])
    S = int(np.ceil(h_slots / step))
    sleeves = np.ones(S)
    eq = []
    for c, r in enumerate(cr):
        sleeves[c % S] *= (1 + r)
        eq.append(sleeves.mean())
    eq = np.array(eq)
    stepret = np.r_[eq[0] - 1, eq[1:] / eq[:-1] - 1]
    years = max((cohort_dates[-1] - cohort_dates[0]).astype(int) / 365.25, 1e-9) + h_slots / 252
    dd = eq / np.maximum.accumulate(eq) - 1
    yr = pd.Series(stepret, index=pd.DatetimeIndex(cohort_dates))
    by_year = yr.groupby(yr.index.year).apply(lambda s_: float(np.prod(1 + s_) - 1)).to_dict()
    sh = float(stepret.mean() / stepret.std() * np.sqrt(252 / step)) if stepret.std() > 0 else NAN
    rho1 = float(pd.Series(stepret).autocorr(1)) if len(stepret) > 3 else NAN
    res = {"cagr": float(eq[-1] ** (1 / years) - 1), "total_return": float(eq[-1] - 1), "sharpe": sh,
           "sharpe_rho_adj": float(sh / np.sqrt(max(1 + 2 * rho1, 0.1))) if np.isfinite(rho1) else NAN,
           "max_dd": float(dd.min()), "by_year": {int(k): float(v) for k, v in by_year.items()}}
    if trade_net is not None and len(trade_net):
        res["trades"] = int(len(trade_net))
        res["hit_rate"] = float(np.mean(trade_net > 0))
        res["mean_trade_net"] = float(np.mean(trade_net))
        if hold is not None:
            res["avg_bars_held"] = float(np.nanmean(hold))
            res["net_per_bar_bps"] = float(np.mean(trade_net) / np.nanmean(hold) * 1e4)
    return res


def run(engine, picks, rule, side, h_slots, step, cost_bps, **kw):
    """Exit every cohort's picks with `rule`; return stats + cohort arrays."""
    dates = [d for d, _ in picks]
    sizes = np.array([len(pk) for _, pk in picks])
    allpk = np.concatenate([pk for _, pk in picks if len(pk)]) if sizes.sum() else np.array([], int)
    r_all, k_all = engine.exit_returns(allpk, rule, side=side, **kw)
    r_all = np.where(np.isfinite(r_all), r_all, 0.0)  # (never hit: entry exists for every candidate)
    gross, pos = [], 0
    for sz in sizes:
        gross.append(float(np.mean(r_all[pos:pos + sz])) if sz else NAN)
        pos += sz
    tn = r_all - cost_bps / 1e4
    hl = k_all
    yrs = np.repeat([pd.Timestamp(d).year for d in dates], sizes)
    res = stats_from_cohorts(gross, np.array(dates), h_slots, step, cost_bps, tn, hl)
    res["mean_trade_net_by_year"] = {int(y): float(tn[yrs == y].mean()) for y in np.unique(yrs)}
    res["_gross"] = gross
    res["_dates"] = dates
    return res
