"""Verifier's own staggered-sleeve book engine (written from the brief's conventions, not from twsim.py).
Per-position loop. Legs: cash long, futures long, futures short. Margin/collateral cash earns the Nifty 1D Rate.
Also records the open long market value per day and the ex-ante planned long capital at each signal close."""
import numpy as np


class VBook:
    def __init__(self, o, c, didx, seg_end, lb_cs, cal, cl):
        self.o, self.c, self.didx = o, c, didx
        self.end, self.lb = seg_end, lb_cs
        self.cal, self.cl = cal, cl
        order = np.argsort(didx, kind="stable")
        self.order = order
        self.bnd = np.searchsorted(didx[order], np.arange(len(cal) + 1))

    def rows_on(self, g):
        return self.order[self.bnd[g]:self.bnd[g + 1]]

    def _pos(self, i, gn, h):
        last = min(i + h, self.end[i])
        if last <= i:
            return None
        rows = np.arange(i + 1, last + 1)
        ok = (self.lb[rows] == self.lb[i]) & (self.didx[rows] <= gn)
        nv = len(ok) if ok.all() else int(np.argmin(ok))
        if nv == 0:
            return None
        rows = rows[:nv]
        e = self.o[rows[0]]
        if not (np.isfinite(e) and e > 0):
            return None
        return rows, e

    def run(self, start, end_exit, legs, h=20, step=5, carry_from="signal", record=False, zero_cash=False):
        """legs: list of dict(score, mask, k, side 'long'|'short', mode 'cash'|'fut', a (notional per unit sleeve
        equity), c (round-trip cost), seed (None = by score)). Margin cash = 1 - sum(a of cash-long legs)."""
        cal, cl = self.cal, self.cl
        g0 = int(np.searchsorted(cal, np.datetime64(start)))
        gl = len(cal) - 1 if end_exit is None else int(np.searchsorted(cal, np.datetime64(end_exit), side="right")) - 1
        sigs = list(range(g0, gl - h - 1 + 1, step))
        Sx = int(np.ceil(h / step))
        per = Sx * step
        D0, D1 = g0, min(gl, sigs[-1] + per)
        nd = D1 - D0 + 1
        eq = np.ones((Sx, nd))
        mv = np.zeros(nd)
        plan = np.zeros(nd)
        last = np.full(Sx, -1)
        rng = [np.random.default_rng(L["seed"]) if L.get("seed") is not None else None for L in legs]
        a_cash_long = sum(L["a"] for L in legs if L["mode"] == "cash")
        m_cash = 1.0 - a_cash_long
        for j, g in enumerate(sigs):
            s = j % Sx
            gn = min(g + per, D1)
            Eq = eq[s, g - D0]
            days = np.arange(g + 1, gn + 1)
            if len(days) == 0:
                continue
            path = m_cash * (np.ones(len(days)) if zero_cash else cl[days] / cl[g])
            cand_all = self.rows_on(g)
            for li, Lg in enumerate(legs):
                cand = cand_all[Lg["mask"][cand_all]]
                k = Lg["k"]
                if rng[li] is not None:
                    pick = rng[li].choice(cand, size=min(k, len(cand)), replace=False) if len(cand) else cand
                else:
                    sc = Lg["score"][cand]
                    cand = cand[np.isfinite(sc)]
                    sc = sc[np.isfinite(sc)]
                    o_ = np.argsort(-sc if Lg["side"] == "long" else sc, kind="stable")
                    pick = cand[o_[:k]]
                w = Lg["a"] / k
                c = Lg["c"]
                nok = 0
                for i in pick:
                    ps = self._pos(i, gn, h)
                    if ps is None:
                        continue
                    rows, e = ps
                    nok += 1
                    bd = self.didx[rows]
                    cnt = np.searchsorted(bd, days, side="right")
                    ent = cnt > 0
                    px = self.c[rows[np.maximum(cnt - 1, 0)]]
                    rel = px / e
                    ex = days >= bd[-1]
                    cf = (1 - c / 2) * np.where(ex, 1 - c / 2, 1.0)
                    if Lg["side"] == "long":
                        v = np.where(ent, rel * cf, 1.0)
                    else:
                        v = np.where(ent, (2.0 - rel) * cf, 1.0)
                    if Lg["mode"] == "cash":
                        path = path + w * v
                    else:
                        if carry_from == "none":
                            cr = 0.0
                        else:
                            base = cl[g] if carry_from == "signal" else cl[bd[0]]
                            cr = np.where(ent, cl[np.minimum(days, bd[-1])] / base - 1, 0.0)
                        path = path + w * ((v - 1 - cr) if Lg["side"] == "long" else (v - 1 + cr))
                    if record and Lg["side"] == "long":
                        mv[days - D0] += Eq * w * v * (ent & ~ex)
                if Lg["mode"] == "cash":
                    path = path + (Lg["a"] - w * nok)          # unfilled long slots: idle cash at 0% (frozen book)
                if record and Lg["side"] == "long":
                    plan[g - D0] += Eq * w * len(pick) * (1 - c / 2)   # ex-ante: all picks, valued at entry (known at t)
            eq[s, g - D0 + 1:gn - D0 + 1] = Eq * path
            last[s] = gn - D0
        for s in range(Sx):
            if 0 <= last[s] < nd - 1:
                eq[s, last[s] + 1:] = eq[s, last[s]]
        book = eq.mean(0)
        r = np.r_[0.0, book[1:] / book[:-1] - 1]
        res = {"r": r, "dates": cal[D0:D1 + 1], "g_idx": np.arange(D0, D1 + 1), "sig_mask": np.isin(np.arange(D0, D1 + 1), sigs)}
        if record:
            tot = eq.sum(0)
            res["expL"] = mv / tot                          # open long MV / NAV at each close (as recorded)
            res["plan"] = (mv + plan) / tot                 # ex-ante planned long exposure at signal closes
        return res


def hedge(book_r, f_plan, fut, clv, beta, reset, month_end, margin=0.15, cash_share=0.5, c_adj=1e-4, c_roll=2e-4):
    """Own index-futures hedge account: long book L scaled to V/(1+margin*cash_share*beta*f) at each reset,
    margin cash M earns the 1D rate and takes the futures MTM; fixed futures units between resets."""
    n = len(book_r)
    out = np.zeros(n)
    hn = np.zeros(n)
    V, Lv, M, u = 1.0, 1.0, 0.0, 0.0
    for t in range(n):
        Vp = V
        if t > 0:
            Lv *= 1 + book_r[t]
            M = M * clv[t] / clv[t - 1] - u * (fut[t] - fut[t - 1])
            if month_end[t]:
                M -= c_roll * abs(u * fut[t])
            V = Lv + M
        if reset[t]:
            b, f = beta[t], f_plan[t]
            Lv = V / (1 + margin * cash_share * b * f)
            M = V - Lv
            N = b * f * Lv
            M -= c_adj * abs(N - u * fut[t])
            u = N / fut[t]
            V = Lv + M
        out[t] = V / Vp - 1
        hn[t] = u * fut[t] / V
    return out, hn
