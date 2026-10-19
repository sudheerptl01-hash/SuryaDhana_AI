"""booksim — R3_book extension of L.Sim.run (long book, time exit), derived from the devil's per-trade-cost
copy (results/R3_devil/s7_capacity.py::run_cost). Validated bit-exact against L.Sim.run on the baseline
(see s2_validate.py). Extensions (all decisions use data <= the decision date; fills at the next open):
  * cost_row      per-row round-trip cost (fraction), half at entry, half at exit (impact models)
  * sizing        'slot' (1/top_k each, as L.Sim) | 'invvol' (1/vol_20, cap 2x equal weight, same total)
  * fill          per-row fraction of the slot actually bought (participation cap); rest stays in cash
  * cash          'zero' (L.Sim default) | '1d' (idle cash grows with the Nifty 1D Rate index level)
  * exit_rule     'time' | 'e2w' (PROD pct <= thr on the book's weekly signal dates inside the hold -> exit next
                  open) | 'e2d' (daily check) | 'e3' (close <= stop_frac x entry -> exit next open)
  * carry         E1: names in the sleeve's new top-K that it holds at the rebalance close are kept (no exit or
                  entry cost; the new leg is marked from the rebalance close, so it earns the overnight gap)
Turnover accounting (book units = sleeve units / n_sleeves): buys, sells, costs paid, round trips by year."""
import numpy as np
import pandas as pd

NAN = np.nan


class BookSim:
    def __init__(self, S, fw, prank=None, vol20=None, cash_level=None):
        self.S, self.fw = S, fw
        self.prank, self.vol20 = prank, vol20
        self.cash_level = cash_level          # float array aligned to S.cal (index level, ffilled)
        self.years = pd.DatetimeIndex(S.cal).year.values

    # ------------------------------------------------------------------ weights
    def _weights(self, pick, top_k, sizing, fill):
        npk = len(pick)
        if sizing == "slot":
            w = np.full(npk, 1.0 / top_k)
        elif sizing == "invvol":
            T = npk / top_k
            iv = 1.0 / np.maximum(self.vol20[pick], 1e-4)
            cap = 2.0 / top_k
            w = T * iv / iv.sum()
            fixed = np.zeros(npk, bool)
            for _ in range(50):
                over = (w > cap + 1e-15) & ~fixed
                if not over.any():
                    break
                fixed |= over
                w[fixed] = cap
                rem = T - cap * fixed.sum()
                w[~fixed] = rem * iv[~fixed] / iv[~fixed].sum()
        else:
            raise ValueError(sizing)
        if fill is not None:
            w = w * fill[pick]
        return w

    # ------------------------------------------------------------------ main
    def run(self, score, mask, h=20, step=5, top_k=20, start="2023-01-01", end_exit="2025-12-31",
            random_seed=None, cost_bps=50.0, cost_row=None, sizing="slot", fill=None, cash="zero",
            exit_rule="time", carry=False, early_thr=0.30, stop_frac=0.75):
        Sm, fw = self.S, self.fw
        mask = np.asarray(mask, bool)
        if score is not None:
            score = np.asarray(score, dtype="float64")
        rng = np.random.default_rng(random_seed) if random_seed is not None else None
        g0, g_sig_last, g_end = Sm._window(start, end_exit, h, step)
        Sx = int(np.ceil(h / step))
        period = Sx * step
        sigs = list(range(g0, g_sig_last + 1, step))
        D0, D1 = g0, min(g_end, sigs[-1] + period)
        nd = D1 - D0 + 1
        lb_cs, didx, o, c = fw.lb_cs, Sm.didx, Sm.o, Sm.c
        hk = np.arange(1, h + 1)
        flat = cost_bps / 1e4
        uniform = (sizing == "slot") and (fill is None)
        # ---------------- pass A/B: picks (same RNG order as L.Sim.run), validity, carry flags, early exits
        W = []
        n_nan_check = 0
        for j, g in enumerate(sigs):
            g_next = min(g + period, D1)
            cand = Sm.rows_on(g)
            cand = cand[mask[cand]]
            if rng is None:
                cand = cand[np.isfinite(score[cand])]
                pick = cand[np.argsort(-score[cand], kind="stable")[:top_k]]
            else:
                k = min(top_k, len(cand))
                pick = rng.choice(cand, size=k, replace=False) if k else cand[:0]
            if len(pick) == 0 or g_next <= g:
                W.append(None)
                continue
            rows_k = pick[:, None] + hk[None, :]
            rk = np.clip(rows_k, 0, Sm.n - 1)
            v = (rows_k <= fw.end[pick][:, None]) & ((lb_cs[rk] - lb_cs[pick][:, None]) == 0) & (didx[rk] <= g_next)
            v = np.cumprod(v, axis=1).astype(bool)
            e = np.where(v[:, 0], o[rk[:, 0]], NAN)
            ok = v[:, 0] & np.isfinite(e) & (e > 0)
            pick, rk, v, e = pick[ok], rk[ok], v[ok], e[ok]
            npk = len(pick)
            if npk == 0:
                W.append(None)
                continue
            cin = np.zeros(npk, bool)
            cidx = np.zeros(0, dtype=int)
            legacy = None
            if carry and j >= Sx and W[j - Sx] is not None and W[j - Sx]["g_next"] == g:
                pw = W[j - Sx]
                ex_rows = pw["rk"][np.arange(len(pw["pick"])), pw["Kx"] - 1]
                elig = (~pw["early"]) & (didx[ex_rows] == g)
                cin = np.isin(pick, ex_rows[elig])
                pos_prev = {int(r_): i_ for i_, r_ in enumerate(ex_rows) if elig[i_]}
                cidx = np.array([pos_prev[int(r_)] for r_ in pick[cin]], dtype=int)
                if carry == "exec":
                    # executable timing: every time-exit due at the rebalance close is held through it; at the next
                    # open the names not in the new top-K are sold (legacy), the others are carried untouched.
                    cout = elig.copy()
                    leg = elig & ~np.isin(ex_rows, pick[cin])
                    lr = ex_rows[leg]
                    nx = np.clip(lr + 1, 0, Sm.n - 1)
                    okn = (lr + 1 <= fw.end[lr]) & ((lb_cs[nx] - lb_cs[lr]) == 0) & (didx[nx] <= g_next) & (o[nx] > 0)
                    li = np.flatnonzero(leg)
                    cout[li[~okn]] = False            # no next bar: exit at the rebalance close as in E0
                    pw["cout"] = cout
                    legacy = dict(idx=li[okn], row=lr[okn], nxt=nx[okn])
                else:
                    pw["cout"] = elig & np.isin(ex_rows, pick[cin])
                e = np.where(cin, c[pick], e)
            Kx = v.sum(1)
            early = np.zeros(npk, bool)
            if exit_rule in ("e2w", "e2d", "e3"):
                if exit_rule == "e3":
                    cond = v & (c[rk] <= stop_frac * e[:, None])
                else:
                    pr = self.prank[rk]
                    cond = v & (pr <= early_thr)
                    if exit_rule == "e2w":
                        chk = np.isin(didx[rk], [g + step * m for m in range(1, Sx)])
                        cond &= chk
                        n_nan_check += int((v & chk & ~np.isfinite(pr) & (np.arange(h)[None, :] <= Kx[:, None] - 2)).sum())
                    else:
                        n_nan_check += int((v & ~np.isfinite(pr) & (np.arange(h)[None, :] <= Kx[:, None] - 2)).sum())
                cond &= np.arange(h)[None, :] <= (Kx[:, None] - 2)
                early = cond.any(1)
                Kx = np.where(early, np.argmax(cond, 1) + 2, Kx)
            W.append(dict(g=g, g_next=g_next, pick=pick, rk=rk, v=v, e=e, Kx=Kx, early=early, cin=cin,
                          cout=np.zeros(npk, bool), cidx=cidx, legacy=legacy))
        # ---------------- pass C: mark-to-market paths
        sleeve_eq = np.ones((Sx, nd))
        last_w = np.zeros(Sx, dtype=int)
        nyr = {}
        acc = {"buy": nyr.copy(), "sell": nyr.copy(), "cost": nyr.copy(), "rt": nyr.copy(), "orders": nyr.copy()}
        nets, early_n, carry_n, pos_n = [], 0, 0, 0
        trim = {"trim": 0.0, "carried_notional": 0.0, "legacy_sold": 0}
        held = np.zeros(nd)
        cl = self.cash_level

        def addy(key, day, val):
            y = int(self.years[day])
            acc[key][y] = acc[key].get(y, 0.0) + float(val)

        for j, g in enumerate(sigs):
            s = j % Sx
            g_next = min(g + period, D1)
            Eq = sleeve_eq[s, g - D0]
            days = np.arange(g + 1, g_next + 1)
            if cash == "1d":
                cgr = cl[days] / cl[g]
            else:
                cgr = 1.0
            w_ = W[j]
            if w_ is None:
                if len(days):
                    sleeve_eq[s, g - D0 + 1:g_next - D0 + 1] = Eq * cgr
                last_w[s] = g_next - D0
                continue
            pick, rk, v, e, Kx = w_["pick"], w_["rk"], w_["v"], w_["e"], w_["Kx"]
            early, cin, cout = w_["early"], w_["cin"], w_["cout"]
            npk = len(pick)
            cst = np.full(npk, flat) if cost_row is None else cost_row[pick]
            px = np.where(v, c[rk], NAN)
            if early.any():
                ii = np.flatnonzero(early)
                px[ii, Kx[ii] - 1] = o[rk[ii, Kx[ii] - 1]]
            X = px[np.arange(npk), Kx - 1]
            bd = np.where(v, didx[rk], 10 ** 9)
            bd = np.where(hk[None, :] <= Kx[:, None], bd, 10 ** 9)
            exit_day = didx[rk[np.arange(npk), Kx - 1]]
            cnt = (bd[:, None, :] <= days[None, :, None]).sum(2)
            idx = np.clip(cnt - 1, 0, h - 1)
            price = np.take_along_axis(np.nan_to_num(px, nan=0.0), idx, axis=1)
            rel = price / e[:, None]
            ent_f = np.where(cin, 1.0, 1 - cst / 2)
            ext_f = np.where(cout, 1.0, 1 - cst / 2)
            gross = np.where(cnt == 0, 1.0, (1 + (rel - 1)) * ent_f[:, None])
            after = days[None, :] >= exit_day[:, None]
            gross = np.where(after, gross * ext_f[:, None], gross)
            if cash == "1d":
                post = days[None, :] > exit_day[:, None]
                gross = np.where(post, gross * (cl[days][None, :] / cl[exit_day][:, None]), gross)
            w = self._weights(pick, top_k, sizing, fill)
            if uniform:
                wv = 1.0 / top_k
                cash_frac = max(0.0, 1 - wv * npk)
                path = cash_frac * cgr + wv * gross.sum(0)
            else:
                cash_frac = max(0.0, 1 - w.sum())
                path = cash_frac * cgr + (w[:, None] * gross).sum(0)
            wfull = np.full(npk, 1.0 / top_k) if uniform else w
            w_["endval"] = wfull * Eq * gross[:, -1]
            w_["cst"] = cst
            if cin.any():
                pw = W[j - Sx]
                tgt = wfull[cin] * Eq
                prv = pw["endval"][w_["cidx"]]
                trim["trim"] += float(np.abs(tgt - prv).sum()) / Sx
                trim["carried_notional"] += float(tgt.sum()) / Sx
            lg = w_["legacy"]
            if lg is not None and len(lg["idx"]):
                pw = W[j - Sx]
                Lk = pw["endval"][lg["idx"]]
                cstk = pw["cst"][lg["idx"]]
                gap = o[lg["nxt"]] / c[lg["row"]]
                dayk = didx[lg["nxt"]]
                path = path + ((Lk * (gap * (1 - cstk / 2) - 1))[:, None] * (days[None, :] >= dayk[:, None])).sum(0) / Eq
                for k_ in range(len(Lk)):
                    ns = Lk[k_] * gap[k_] / Sx
                    addy("sell", dayk[k_], ns)
                    addy("cost", dayk[k_], ns * cstk[k_] / 2)
                    addy("rt", dayk[k_], 1)
                    addy("orders", dayk[k_], 1)
                trim["legacy_sold"] += int(len(Lk))
            sleeve_eq[s, g - D0 + 1:g_next - D0 + 1] = Eq * path
            held[g - D0 + 1:g_next - D0 + 1] += ((~after) & (cnt > 0)).sum(0)
            last_w[s] = g_next - D0
            # trade accounting (book units)
            ent_day = didx[rk[:, 0]]
            for i in range(npk):
                if not cin[i]:
                    nb = w[i] * Eq / Sx
                    addy("buy", ent_day[i], nb)
                    addy("cost", ent_day[i], nb * cst[i] / 2)
                    addy("orders", ent_day[i], 1)
                if not cout[i]:
                    ns = w[i] * Eq * (X[i] / e[i]) * ent_f[i] / Sx
                    addy("sell", exit_day[i], ns)
                    addy("cost", exit_day[i], ns * cst[i] / 2)
                    addy("rt", exit_day[i], 1)
                    addy("orders", exit_day[i], 1)
            nets.append(X / e - 1 - np.where(cin, 0, cst / 2) - np.where(cout, 0, cst / 2))
            early_n += int(early.sum())
            carry_n += int(cin.sum())
            pos_n += npk
        for s_ in range(Sx):
            lw = last_w[s_]
            if 0 < lw < nd - 1:
                sleeve_eq[s_, lw + 1:] = sleeve_eq[s_, lw]
        eq = sleeve_eq.mean(0)
        dates = Sm.cal[D0:D1 + 1]
        r = np.r_[0.0, eq[1:] / eq[:-1] - 1]
        yrs = max((dates[-1] - dates[0]).astype(int) / 365.25, 1e-9)
        tn = np.concatenate(nets) if nets else np.array([])
        # average equity per calendar year for turnover ratios
        ser = pd.Series(eq, index=pd.DatetimeIndex(dates))
        avg_eq = {int(y): float(gq.mean()) for y, gq in ser.groupby(ser.index.year)}
        ndays_y = {int(y): int(len(gq)) for y, gq in ser.groupby(ser.index.year)}
        return {"cagr": float(eq[-1] ** (1 / yrs) - 1), "max_dd": float((eq / np.maximum.accumulate(eq) - 1).min()),
                "mean_trade_net": float(tn.mean()) if len(tn) else NAN,
                "hit_rate": float((tn > 0).mean()) if len(tn) else NAN, "n_positions": pos_n,
                "n_early_exits": early_n, "n_carried": carry_n, "n_check_nan_held": n_nan_check,
                "avg_names_held": float(held.mean()), "acc": acc, "trim": trim, "avg_eq": avg_eq, "ndays_y": ndays_y,
                "_daily": r, "_dates": dates, "_eq": eq}


def turnover_summary(runs):
    """Average over phase runs of annualised turnover stats (book units, relative to average equity)."""
    out = {"buy_x_book_per_yr": [], "sell_x_book_per_yr": [], "traded_x_book_per_yr": [],
           "round_trips_per_yr": [], "orders_per_week": [], "cost_drag_per_yr": []}
    for rr in runs:
        ys = sorted(rr["avg_eq"])
        nday = sum(rr["ndays_y"][y] for y in ys)
        yrs = nday / 252
        # equity-weighted: sum of flows / average equity over the window
        mean_eq = sum(rr["avg_eq"][y] * rr["ndays_y"][y] for y in ys) / nday
        tot = {k: sum(rr["acc"][k].get(y, 0.0) for y in ys) for k in rr["acc"]}
        out["buy_x_book_per_yr"].append(tot["buy"] / mean_eq / yrs)
        out["sell_x_book_per_yr"].append(tot["sell"] / mean_eq / yrs)
        out["traded_x_book_per_yr"].append((tot["buy"] + tot["sell"]) / mean_eq / yrs)
        out["round_trips_per_yr"].append(tot["rt"] / yrs)
        out["orders_per_week"].append(tot["orders"] / (nday / 5))
        out["cost_drag_per_yr"].append(tot["cost"] / mean_eq / yrs)
    return {k: float(np.mean(v)) for k, v in out.items()}
