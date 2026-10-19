"""Copy of L.Sim.run (time exit only) with two additions, both decided at the sleeve's signal date g:
  * exposure x_g in [0, 1]: each pick gets x_g * w of sleeve equity (w = 1/top_k slot, or 1/npk equal);
  * idle cash (1 - x_g * w * npk) earns a cash INDEX (Nifty 1D Rate) from close g onwards
    (cash_level=None -> 0% exactly like L.Sim with cash_yield=0).
With x_g = 1 and cash_level = None the output is identical to L.Sim.run (validated in s2_expo.py)."""
import numpy as np
import pandas as pd

NAN = np.nan


def run_x(S, score, mask, h, step=5, top_k=20, cost_bps=50.0, start="2023-01-01", end_exit="2025-12-31",
          xfun=None, cash_level=None, sizing="slot", select_quantile=None):
    fw = S.fw
    mask = np.asarray(mask, bool)
    score = None if score is None else np.asarray(score, dtype="float64")
    g0, g_sig_last, g_end = S._window(start, end_exit, h, step)
    NS = int(np.ceil(h / step))
    period = NS * step
    sigs = list(range(g0, g_sig_last + 1, step))
    D0, D1 = g0, min(g_end, sigs[-1] + period)
    nd = D1 - D0 + 1
    sleeve_eq = np.ones((NS, nd))
    invested = np.zeros((NS, nd))
    cost = cost_bps / 1e4
    last_w = np.zeros(NS, dtype=int)
    lb_cs = fw.lb_cs
    hk = np.arange(1, h + 1)
    xs = []
    for j, g in enumerate(sigs):
        s = j % NS
        g_next = min(g + period, D1)
        Eq = sleeve_eq[s, g - D0]
        x = 1.0 if xfun is None else float(xfun(g))
        xs.append(x)
        days = np.arange(g + 1, g_next + 1)
        cg = np.ones(len(days)) if cash_level is None else cash_level[days] / cash_level[g]
        cand = S.rows_on(g)
        cand = cand[mask[cand]]
        if score is not None:
            cand = cand[np.isfinite(score[cand])]
        if select_quantile is not None:
            sc = score[cand]
            pr = pd.Series(sc).rank(pct=True).values if len(sc) else sc
            lo_q, hi_q = select_quantile
            pick = cand[(pr >= lo_q) & (pr <= hi_q)]
        else:
            sc = score[cand]
            ordr = np.argsort(-sc, kind="stable")
            pick = cand[ordr[:top_k]]
        if len(pick) == 0 or len(days) == 0:
            sleeve_eq[s, g - D0 + 1:g_next - D0 + 1] = Eq * cg
            last_w[s] = g_next - D0
            continue
        rows_k = pick[:, None] + hk[None, :]
        rk = np.clip(rows_k, 0, S.n - 1)
        v = (rows_k <= fw.end[pick][:, None]) & ((lb_cs[rk] - lb_cs[pick][:, None]) == 0) \
            & (S.didx[rk] <= g_next)
        v = np.cumprod(v, axis=1).astype(bool)
        e = np.where(v[:, 0], S.o[rk[:, 0]], NAN)
        ok = v[:, 0] & np.isfinite(e) & (e > 0)
        pick, rk, v, e = pick[ok], rk[ok], v[ok], e[ok]
        npk = len(pick)
        if npk == 0:
            sleeve_eq[s, g - D0 + 1:g_next - D0 + 1] = Eq * cg
            last_w[s] = g_next - D0
            continue
        nvalid = v.sum(1)
        px = np.where(v, S.c[rk], NAN)
        Kx = nvalid.copy()
        bd = np.where(v, S.didx[rk], 10 ** 9)
        bd = np.where(hk[None, :] <= Kx[:, None], bd, 10 ** 9)
        exit_day = S.didx[rk[np.arange(npk), Kx - 1]]
        cnt = (bd[:, None, :] <= days[None, :, None]).sum(2)
        idx = np.clip(cnt - 1, 0, h - 1)
        price = np.take_along_axis(np.nan_to_num(px, nan=0.0), idx, axis=1)
        rel = price / e[:, None]
        gross = np.where(cnt == 0, 1.0, rel * (1 - cost / 2))
        after = days[None, :] >= exit_day[:, None]
        gross = np.where(after, gross * (1 - cost / 2), gross)
        w = (1.0 / top_k) if sizing == "slot" and select_quantile is None else (1.0 / npk)
        w = w * x
        cash_frac = max(0.0, 1 - w * npk)
        path = cash_frac * cg + w * gross.sum(0)
        sleeve_eq[s, g - D0 + 1:g_next - D0 + 1] = Eq * path
        invested[s, g - D0 + 1:g_next - D0 + 1] = w * (~after).sum(0)
        last_w[s] = g_next - D0
    for s_ in range(NS):
        lw = last_w[s_]
        if 0 < lw < nd - 1:
            sleeve_eq[s_, lw + 1:] = sleeve_eq[s_, lw]
    eq = sleeve_eq.mean(0)
    dates = S.cal[D0:D1 + 1]
    r = np.r_[0.0, eq[1:] / eq[:-1] - 1]
    return {"_daily_ret": r, "_dates": dates, "exposure": float(invested.mean()),
            "x_signals": np.array(xs), "sig_g": np.array(sigs)}


def phase_avg_x(S, score, mask, h, kw, period, **kx):
    """Phase-averaged daily series (k = 0..step-1 shifts), common dates (same as C.phase_avg)."""
    a, b = period
    step = kw["step"]
    g0 = int(np.searchsorted(S.cal, np.datetime64(a)))
    sers, expo, xsig = [], [], []
    for k in range(step):
        out = run_x(S, score, mask, h, start=str(S.cal[g0 + k]), end_exit=b, **kw, **kx)
        sers.append(pd.Series(out["_daily_ret"], index=pd.DatetimeIndex(out["_dates"])))
        expo.append(out["exposure"])
        xsig.append(out["x_signals"])
    common = sers[0].index
    for x in sers[1:]:
        common = common.intersection(x.index)
    sm = np.mean([x.reindex(common).values for x in sers], 0)
    return pd.Series(sm, index=common), float(np.mean(expo)), xsig
