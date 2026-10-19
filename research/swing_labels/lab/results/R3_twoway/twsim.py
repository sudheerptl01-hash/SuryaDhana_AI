"""twsim — R3_twoway two-leg staggered-sleeve simulator (generalises L.Sim.run; validated bit-exact against it
for long-only and short-only books in s2_engine.py) + index-futures hedge overlay.

Sleeve value path on day d (sleeve equity Eq at the signal close g):
  cash-long  : cash_m * cg1d(d) + cash_slot * cgslot(d) + sum_i wL * grossL_i(d) + sum_j wS * (grossS_j(d) - 1 + carry_j(d))
  fut-long   : cg1d(d) + sum_i wL * (grossL_i(d) - 1 - carry_i(d)) + sum_j wS * (grossS_j(d) - 1 + carry_j(d))
  gross = L.Sim's per-position value: 1 before entry; entry at the entity's next open with cost/2; marked at closes;
  exit at the close of bar h (or the last valid bar: suspension / label_block / sleeve rebalance) with cost/2.
  carry_j(d) = 1D-rate index ratio from the signal close g to min(d, exit day) while entered (futures carry).
  wL = aL / kL, wS = aS / kS (slot sizing); cash_m = 1 - aL (margin cash, earns 1D rate if cash='1d');
  cash_slot = aL - wL * nL (unfilled long slots; 0 yield, as the frozen L.Sim book).
All decisions use data <= the signal close; fills at the next open."""
import numpy as np
import pandas as pd

NAN = np.nan


class TwoWay:
    def __init__(self, S, fw, cl1d):
        self.S, self.fw = S, fw
        self.cl = np.asarray(cl1d, dtype="float64")          # 1D-rate index level aligned to S.cal

    def _leg(self, g, g_next, days, cand, score, k, side, rng, h, cost):
        Sm, fw = self.S, self.fw
        if rng is not None:
            kk = min(k, len(cand))
            pick = rng.choice(cand, size=kk, replace=False) if kk else cand[:0]
        else:
            cand = cand[np.isfinite(score[cand])]
            sc = score[cand]
            ordr = np.argsort(-sc if side == "long" else sc, kind="stable")
            pick = cand[ordr[:k]]
        sig_pick = pick
        if len(pick) == 0:
            return None, sig_pick
        hk = np.arange(1, h + 1)
        rows_k = pick[:, None] + hk[None, :]
        rk = np.clip(rows_k, 0, Sm.n - 1)
        v = (rows_k <= fw.end[pick][:, None]) & ((fw.lb_cs[rk] - fw.lb_cs[pick][:, None]) == 0) \
            & (Sm.didx[rk] <= g_next)
        v = np.cumprod(v, axis=1).astype(bool)
        e = np.where(v[:, 0], Sm.o[rk[:, 0]], NAN)
        ok = v[:, 0] & np.isfinite(e) & (e > 0)
        pick, rk, v, e = pick[ok], rk[ok], v[ok], e[ok]
        npk = len(pick)
        if npk == 0:
            return None, sig_pick
        sgn = 1.0 if side == "long" else -1.0
        nvalid = v.sum(1)
        px = np.where(v, Sm.c[rk], NAN)
        Kx = nvalid.copy()
        X = px[np.arange(npk), Kx - 1]
        bd = np.where(v, Sm.didx[rk], 10 ** 9)
        bd = np.where(hk[None, :] <= Kx[:, None], bd, 10 ** 9)
        exit_day = Sm.didx[rk[np.arange(npk), Kx - 1]]
        cnt = (bd[:, None, :] <= days[None, :, None]).sum(2)
        idx = np.clip(cnt - 1, 0, h - 1)
        price = np.take_along_axis(np.nan_to_num(px, nan=0.0), idx, axis=1)
        rel = price / e[:, None]
        gross = np.where(cnt == 0, 1.0, (1 + sgn * (rel - 1)) * (1 - cost / 2))
        after = days[None, :] >= exit_day[:, None]
        gross = np.where(after, gross * (1 - cost / 2), gross)
        entered = cnt > 0
        cday = np.minimum(days[None, :], exit_day[:, None])
        carry = np.where(entered, self.cl[cday] / self.cl[g] - 1, 0.0)
        net = sgn * (X / e - 1) - cost
        return dict(pick=pick, gross=gross, entered=entered, after=after, carry=carry, net=net, npk=npk), sig_pick

    def run(self, score, maskL, maskS, h=20, step=5, kL=20, kS=20, aL=1.0, aS=0.0, long_mode="cash",
            cL=0.005, cS=0.0025, start="2023-01-01", end_exit="2025-12-31", cash="zero", carry=True,
            seedL=None, seedS=None, beta_row=None, beta_clip=(0.5, 1.5), margin_stock=0.25, scoreS=None):
        """long_mode: 'cash' | 'futures' | 'none'. cash: 'zero' (margin cash earns 0) | '1d'.
        beta_row: if given (X1), short notional per sleeve = aL * clip(mean beta(long)/mean beta(short)) and
        aL re-solved as 1/(1 + 0.5*margin_stock*ratio) (cash-long)."""
        Sm = self.S
        maskL = np.asarray(maskL, bool) if maskL is not None else None
        maskS = np.asarray(maskS, bool) if maskS is not None else None
        score = np.asarray(score, dtype="float64") if score is not None else None
        scoreS = score if scoreS is None else np.asarray(scoreS, dtype="float64")
        rngL = np.random.default_rng(seedL) if seedL is not None else None
        rngS = np.random.default_rng(seedS) if seedS is not None else None
        g0, g_sig_last, g_end = Sm._window(start, end_exit, h, step)
        Sx = int(np.ceil(h / step))
        period = Sx * step
        sigs = list(range(g0, g_sig_last + 1, step))
        D0, D1 = g0, min(g_end, sigs[-1] + period)
        nd = D1 - D0 + 1
        sleeve_eq = np.ones((Sx, nd))
        mvL = np.zeros((Sx, nd))        # long market value (fraction of the sleeve's start equity units)
        mvS = np.zeros((Sx, nd))
        last_w = np.zeros(Sx, dtype=int)
        netsL, netsS, ratios = [], [], []
        useL = (aL > 0 or beta_row is not None) and long_mode != "none"
        useS = aS > 0 or beta_row is not None
        for j, g in enumerate(sigs):
            s = j % Sx
            g_next = min(g + period, D1)
            Eq = sleeve_eq[s, g - D0]
            days = np.arange(g + 1, g_next + 1)
            cg1 = self.cl[days] / self.cl[g] if cash == "1d" else np.ones(len(days))
            cand_all = Sm.rows_on(g)
            legL = legS = None
            sigL = sigS = np.zeros(0, dtype=int)
            if useL:
                legL, sigL = self._leg(g, g_next, days, cand_all[maskL[cand_all]], score, kL, "long", rngL, h, cL)
            if useS:
                legS, sigS = self._leg(g, g_next, days, cand_all[maskS[cand_all]], scoreS, kS, "short", rngS, h, cS)
            aL_, aS_ = aL, aS
            if beta_row is not None:
                bl = np.nanmean(beta_row[sigL]) if len(sigL) else np.nan
                bs = np.nanmean(beta_row[sigS]) if len(sigS) else np.nan
                ratio = float(np.clip(bl / bs, *beta_clip)) if np.isfinite(bl) and np.isfinite(bs) and bs > 0 else 1.0
                ratios.append(ratio)
                aL_ = 1.0 / (1.0 + 0.5 * margin_stock * ratio)
                aS_ = aL_ * ratio
            if len(days) == 0:
                last_w[s] = g_next - D0
                continue
            if long_mode == "cash":
                wL = aL_ / kL
                nL = legL["npk"] if legL is not None else 0
                cash_m = 1.0 - aL_
                cash_slot = max(0.0, aL_ - wL * nL)
                if cash_m == 0.0:
                    # identical arithmetic to L.Sim.run (validation path)
                    path = cash_slot * np.ones(len(days)) if cash == "zero" else cash_slot * cg1
                    if legL is not None:
                        path = cash_slot * 1.0 + wL * legL["gross"].sum(0) if cash == "zero" else \
                            cash_slot * cg1 + wL * legL["gross"].sum(0)
                else:
                    path = cash_m * cg1 + cash_slot * 1.0
                    if legL is not None:
                        path = path + wL * legL["gross"].sum(0)
                if legL is not None:
                    mvL[s, g - D0 + 1:g_next - D0 + 1] = Eq * wL * (legL["gross"] * (legL["entered"] & ~legL["after"])).sum(0)
            else:  # futures-long or no long: all equity is collateral
                path = cg1.copy() if cash == "1d" else np.ones(len(days))
                if legL is not None:
                    wL = aL_ / kL
                    cr = legL["carry"] if carry else 0.0
                    path = path + wL * (legL["gross"] - 1 - cr).sum(0)
                    mvL[s, g - D0 + 1:g_next - D0 + 1] = Eq * wL * (legL["gross"] * (legL["entered"] & ~legL["after"])).sum(0)
            if legS is not None:
                wS = aS_ / kS
                cr = legS["carry"] if carry else 0.0
                if long_mode == "cash" and aL_ == 0.0 and cash == "zero" and not carry:
                    # identical arithmetic to L.Sim.run(side='short') (validation path)
                    path = max(0.0, 1 - wS * legS["npk"]) + wS * legS["gross"].sum(0)
                else:
                    path = path + wS * (legS["gross"] - 1 + cr).sum(0)
                mvS[s, g - D0 + 1:g_next - D0 + 1] = Eq * wS * (legS["entered"] & ~legS["after"]).sum(0)
            sleeve_eq[s, g - D0 + 1:g_next - D0 + 1] = Eq * path
            last_w[s] = g_next - D0
            if legL is not None:
                netsL.append(legL["net"])
            if legS is not None:
                netsS.append(legS["net"])
        for s_ in range(Sx):
            lw = last_w[s_]
            if 0 < lw < nd - 1:
                sleeve_eq[s_, lw + 1:] = sleeve_eq[s_, lw]
        eq = sleeve_eq.mean(0)
        dates = Sm.cal[D0:D1 + 1]
        r = np.r_[0.0, eq[1:] / eq[:-1] - 1]
        yrs = max((dates[-1] - dates[0]).astype(int) / 365.25, 1e-9)
        tl = np.concatenate(netsL) if netsL else np.array([])
        ts = np.concatenate(netsS) if netsS else np.array([])
        return {"cagr": float(eq[-1] ** (1 / yrs) - 1), "max_dd": float((eq / np.maximum.accumulate(eq) - 1).min()),
                "long_trades": int(len(tl)), "long_mean_net": float(tl.mean()) if len(tl) else NAN,
                "long_hit": float((tl > 0).mean()) if len(tl) else NAN,
                "short_trades": int(len(ts)), "short_mean_net_price_only": float(ts.mean()) if len(ts) else NAN,
                "short_hit_price_only": float((ts > 0).mean()) if len(ts) else NAN,
                "beta_ratio_mean": float(np.mean(ratios)) if ratios else NAN,
                "_daily": r, "_dates": dates, "_eq": eq,
                "_expL": mvL.sum(0) / np.maximum(sleeve_eq.sum(0), 1e-12),
                "_expS": mvS.sum(0) / np.maximum(sleeve_eq.sum(0), 1e-12)}


def hedge_overlay(base_ret, dates, expL_next, fut_level, cl1d, beta, reset_mask, month_end, margin=0.15,
                  cash_share=0.5, c_adj=1e-4, c_roll=2e-4):
    """Index-futures hedge on top of a long book (one phase). All arrays aligned to `dates` (book calendar).
    base_ret: book daily return; expL_next: ex-ante long exposure (fraction of book NAV) to hedge at a reset;
    fut_level: futures (or synthetic futures) index level; cl1d: 1D-rate index level; beta: hedge ratio known
    at the reset close (data <= t-1); reset_mask: weekly reset days (signal closes); month_end: roll days.
    Returns daily returns of the hedged account, hedge notional / NAV, and the cost paid."""
    n = len(base_ret)
    out = np.zeros(n)
    hn = np.zeros(n)
    cost_tot = 0.0
    V = 1.0
    b0 = beta[0] if np.isfinite(beta[0]) else 1.0
    m0 = margin * cash_share * b0 * expL_next[0]
    wl = 1.0 / (1.0 + m0)
    Lv, Cm = wl * V, (1 - wl) * V
    N = b0 * expL_next[0] * Lv
    units = N / fut_level[0]
    c0 = c_adj * abs(N)
    Cm -= c0
    cost_tot += c0
    V = Lv + Cm
    out[0] = V - 1.0
    hn[0] = N / V
    for t in range(1, n):
        Vp = V
        Lv = Lv * (1 + base_ret[t])
        pnl = -units * (fut_level[t] - fut_level[t - 1])
        Cm = Cm * (cl1d[t] / cl1d[t - 1]) + pnl
        V = Lv + Cm
        if month_end[t]:
            rc = c_roll * abs(units * fut_level[t])
            Cm -= rc
            cost_tot += rc
            V = Lv + Cm
        if reset_mask[t]:
            b = beta[t] if np.isfinite(beta[t]) else 1.0
            f = expL_next[t]
            wl = 1.0 / (1.0 + margin * cash_share * b * f)
            Lv, Cm = wl * V, (1 - wl) * V
            Nn = b * f * Lv
            ca = c_adj * abs(Nn - units * fut_level[t])
            Cm -= ca
            cost_tot += ca
            units = Nn / fut_level[t]
            V = Lv + Cm
        out[t] = V / Vp - 1
        hn[t] = units * fut_level[t] / V
    return out, hn, cost_tot
