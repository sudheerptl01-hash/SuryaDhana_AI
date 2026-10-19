"""Stage 7 (devil): capacity and market impact.
 * ADV = 20-day MEDIAN daily traded value (Rs, rows t-19..t in the same segment) of each pick at its signal date.
 * Participation = position / ADV for fixed per-name positions of Rs 5 lakh, 25 lakh, 1 crore
   (slot weight 1/80 of capital -> AUM about Rs 4 cr, 20 cr, 80 cr).
 * Square-root impact per side = Y * sigma_daily * sqrt(position / ADV), Y in {0.5, 1.0}, sigma = vol_20,
   capped at 10% per side; round-trip cost = base (flat 50 bps, or tiered 30/50/95 bps by liquidity tier)
   + 2 x impact. Applied per trade in a per-row-cost copy of L.Sim.run (validated against L.Sim at a flat
   cost); the random baseline pays the same impact model on its own picks.
 * Also: how often the entry bar (t+1) or the exit bar is circuit-locked (high == low).
"""
import numpy as np
import pandas as pd

from common import OUT, L, PER, log, save, load_sim, short

P, F, fw, S, E = load_sim()
H = 20
sc = np.load(f"{OUT}/wf_main.npz")["score"].astype("float64")
P2 = L.load_panel(["turnover", "high", "low", "open", "close"])
X = L.load_features(["vol_20", "elig_liq5", "fno_proxy"])
n = len(P2)
turn = P2["turnover"].values.astype("float64")
NAN = np.nan

# ------------------------------------------------------------ 20d median traded value (Rs) on elig rows
ie = np.flatnonzero(E)
W = np.full((len(ie), 20), np.nan, dtype=np.float32)
for k in range(20):
    j = ie - k
    ok = (j >= fw.start[ie])
    W[ok, k] = turn[j[ok]]
adv = np.full(n, NAN)
adv[ie] = np.nanmedian(W, axis=1)
del W
sig = X["vol_20"].values.astype("float64")
liq5 = X["elig_liq5"].values.astype(bool)
fno = X["fno_proxy"].values.astype(bool)
tier = np.where(fno, 30.0, np.where(liq5, 50.0, 95.0))
log("ADV ready; median ADV on elig (cr)", float(np.nanmedian(adv[ie]) / 1e7))


def run_cost(score, mask, h, cost_row, step=5, top_k=20, start=L.DEV[0], end_exit=L.DEV[1], random_seed=None,
             keep=False):
    """Copy of L.Sim.run (long, time exit, slot sizing, cash_yield 0) with a per-row round-trip cost."""
    self = S
    mask = np.asarray(mask, bool)
    rng = np.random.default_rng(random_seed) if random_seed is not None else None
    g0, g_sig_last, g_end = self._window(start, end_exit, h, step)
    Sx = int(np.ceil(h / step))
    period = Sx * step
    sigs = list(range(g0, g_sig_last + 1, step))
    D0, D1 = g0, min(g_end, sigs[-1] + period)
    nd = D1 - D0 + 1
    sleeve_eq = np.ones((Sx, nd))
    last_w = np.zeros(Sx, dtype=int)
    lb_cs = fw.lb_cs
    hk = np.arange(1, h + 1)
    nets, rows_all = [], []
    for jj, g in enumerate(sigs):
        s = jj % Sx
        g_next = min(g + period, D1)
        Eq = sleeve_eq[s, g - D0]
        cand = self.rows_on(g)
        cand = cand[mask[cand]]
        if rng is None:
            cand = cand[np.isfinite(score[cand])]
            pick = cand[np.argsort(-score[cand], kind="stable")[:top_k]]
        else:
            k = min(top_k, len(cand))
            pick = rng.choice(cand, size=k, replace=False) if k else cand[:0]
        days = np.arange(g + 1, g_next + 1)
        if len(pick) == 0 or len(days) == 0:
            sleeve_eq[s, g - D0 + 1:g_next - D0 + 1] = Eq
            last_w[s] = g_next - D0
            continue
        rows_k = pick[:, None] + hk[None, :]
        rk = np.clip(rows_k, 0, self.n - 1)
        v = (rows_k <= fw.end[pick][:, None]) & ((lb_cs[rk] - lb_cs[pick][:, None]) == 0) & (self.didx[rk] <= g_next)
        v = np.cumprod(v, axis=1).astype(bool)
        e = np.where(v[:, 0], self.o[rk[:, 0]], NAN)
        ok = v[:, 0] & np.isfinite(e) & (e > 0)
        pick, rk, v, e = pick[ok], rk[ok], v[ok], e[ok]
        npk = len(pick)
        if npk == 0:
            sleeve_eq[s, g - D0 + 1:g_next - D0 + 1] = Eq
            last_w[s] = g_next - D0
            continue
        cst = cost_row[pick]
        nvalid = v.sum(1)
        px = np.where(v, self.c[rk], NAN)
        Kx = nvalid.copy()
        Xp = px[np.arange(npk), Kx - 1]
        bd = np.where(v, self.didx[rk], 10 ** 9)
        bd = np.where(hk[None, :] <= Kx[:, None], bd, 10 ** 9)
        exit_day = self.didx[rk[np.arange(npk), Kx - 1]]
        cnt = (bd[:, None, :] <= days[None, :, None]).sum(2)
        idx = np.clip(cnt - 1, 0, h - 1)
        price = np.take_along_axis(np.nan_to_num(px, nan=0.0), idx, axis=1)
        rel = price / e[:, None]
        gross = np.where(cnt == 0, 1.0, rel * (1 - cst[:, None] / 2))
        after = days[None, :] >= exit_day[:, None]
        gross = np.where(after, gross * (1 - cst[:, None] / 2), gross)
        w = 1.0 / top_k
        cash_frac = max(0.0, 1 - w * npk)
        sleeve_eq[s, g - D0 + 1:g_next - D0 + 1] = Eq * (cash_frac + w * gross.sum(0))
        last_w[s] = g_next - D0
        nets.append(Xp / e - 1 - cst)
        rows_all.append(pick)
    for s_ in range(Sx):
        lw = last_w[s_]
        if 0 < lw < nd - 1:
            sleeve_eq[s_, lw + 1:] = sleeve_eq[s_, lw]
    eq = sleeve_eq.mean(0)
    dates = self.cal[D0:D1 + 1]
    r = np.r_[0.0, eq[1:] / eq[:-1] - 1]
    yrs = max((dates[-1] - dates[0]).astype(int) / 365.25, 1e-9)
    out = {"cagr": float(eq[-1] ** (1 / yrs) - 1), "max_dd": float((eq / np.maximum.accumulate(eq) - 1).min()),
           "mean_trade_net": float(np.concatenate(nets).mean()), "_daily": r, "_dates": dates}
    if keep:
        out["_rows"] = np.concatenate(rows_all)
    return out


# ------------------------------------------------------------ validation vs L.Sim at a flat 50 bps
flat = np.full(n, 0.005)
v1 = run_cost(sc, E, H, flat)
v2 = S.run(sc, E, H, top_k=20, step=5, cost_bps=50, start=L.DEV[0], end_exit=L.DEV[1])
val = {"cagr_copy": v1["cagr"], "cagr_lablib": v2["cagr"], "max_abs_daily_diff": float(np.abs(v1["_daily"] - v2["_daily_ret"]).max())}
log("validation", val)
assert val["max_abs_daily_diff"] < 1e-12

SIZES = {"Rs5L": 5e5, "Rs25L": 2.5e6, "Rs1Cr": 1e7}
out = {"validation": val, "aum_equivalent_note": "slot weight 1/80 of capital: Rs5L~Rs4cr AUM, Rs25L~Rs20cr, Rs1Cr~Rs80cr"}


def pa_cost(score, cost_row, per, step=5, seeds=(1, 2, 3, 4, 5)):
    a, b = PER[per]
    g0 = int(np.searchsorted(S.cal, np.datetime64(a)))
    sds, rds = [], []
    for k in range(step):
        st = str(S.cal[g0 + k])
        r_ = run_cost(score, E, H, cost_row, step=step, start=st, end_exit=b)
        sds.append(pd.Series(r_["_daily"], index=pd.DatetimeIndex(r_["_dates"])))
        rr = [run_cost(None, E, H, cost_row, step=step, start=st, end_exit=b, random_seed=s_) for s_ in seeds]
        rds.append(pd.Series(np.mean([x["_daily"] for x in rr], 0), index=pd.DatetimeIndex(rr[0]["_dates"])))
    common = sds[0].index
    for x in sds + rds:
        common = common.intersection(x.index)
    sm = np.mean([x.reindex(common).values for x in sds], 0)
    rm = np.mean([x.reindex(common).values for x in rds], 0)
    yrs = len(common) / 252
    eq = np.cumprod(1 + sm)
    return {"pa_cagr": float(np.prod(1 + sm) ** (1 / yrs) - 1), "pa_random_cagr": float(np.prod(1 + rm) ** (1 / yrs) - 1),
            "pa_excess_ann": float((sm - rm).mean() * 252), "pa_nw_t": L.nw_t(sm - rm, 20),
            "pa_maxdd": float((eq / np.maximum.accumulate(eq) - 1).min())}


# ------------------------------------------------------------ participation of the actual picks
for per, (a, b) in PER.items():
    st = run_cost(sc, E, H, flat, start=a, end_exit=b, keep=True)
    rows = st["_rows"]
    rr = np.concatenate([run_cost(None, E, H, flat, start=a, end_exit=b, random_seed=s_, keep=True)["_rows"]
                         for s_ in (1, 2, 3)])
    part = {"model_adv_cr": {"median": float(np.median(adv[rows]) / 1e7), "p10": float(np.percentile(adv[rows], 10) / 1e7),
                             "p25": float(np.percentile(adv[rows], 25) / 1e7)},
            "random_adv_cr": {"median": float(np.median(adv[rr]) / 1e7), "p10": float(np.percentile(adv[rr], 10) / 1e7)},
            "model_vol20_median": float(np.median(sig[rows])), "random_vol20_median": float(np.median(sig[rr])),
            "model_tier_cost_bps": float(tier[rows].mean()), "random_tier_cost_bps": float(tier[rr].mean())}
    for nm, Q in SIZES.items():
        pr = Q / adv[rows]
        prr = Q / adv[rr]
        imp = np.minimum(1.0 * sig[rows] * np.sqrt(pr), 0.10)
        part[nm] = {"median_pct_adv": float(np.median(pr) * 100), "p90_pct_adv": float(np.percentile(pr, 90) * 100),
                    "share_gt5pct": float((pr > 0.05).mean()), "share_gt10pct": float((pr > 0.10).mean()),
                    "share_gt20pct": float((pr > 0.20).mean()),
                    "random_median_pct_adv": float(np.median(prr) * 100), "random_share_gt10pct": float((prr > 0.10).mean()),
                    "model_mean_impact_bps_per_side_Y1": float(imp.mean() * 1e4),
                    "model_median_impact_bps_per_side_Y1": float(np.median(imp) * 1e4)}
    out[f"participation_{per}"] = part
    log("participation", per, short(part, 3))

# entry / exit bar circuit locks for the picks vs random
hi, lo, op, cl = (P2[c].values.astype("float64") for c in ("high", "low", "open", "close"))
for per, (a, b) in PER.items():
    stx = S.run(sc, E, H, top_k=20, step=5, cost_bps=50, start=a, end_exit=b, keep_trades=True)
    rows = np.array([t[1] for t in stx["_trades"]])
    kx = np.array([t[3] for t in stx["_trades"]])
    rnd = [S.run(None, E, H, top_k=20, step=5, cost_bps=50, start=a, end_exit=b, keep_trades=True, random_seed=s_)
           for s_ in (1, 2, 3)]
    rrows = np.concatenate([[t[1] for t in x["_trades"]] for x in rnd])
    rkx = np.concatenate([[t[3] for t in x["_trades"]] for x in rnd])

    def lk(rw, kk):
        ent = rw + 1
        ex = rw + kk
        el = (hi[ent] == lo[ent])
        el_up = el & (op[ent] > cl[rw])
        xl = (hi[ex] == lo[ex])
        xl_dn = xl & (cl[ex] < cl[ex - 1])
        return {"entry_locked": float(el.mean()), "entry_locked_up": float(el_up.mean()),
                "exit_locked": float(xl.mean()), "exit_locked_down": float(xl_dn.mean())}
    out[f"locks_{per}"] = {"model": lk(rows, kx.astype(int)), "random": lk(rrows, rkx.astype(int))}
    log("locks", per, short(out[f"locks_{per}"]))

# ------------------------------------------------------------ net returns with square-root impact
res = {}
for per in PER:
    res[f"base50_noimpact_{per}"] = pa_cost(sc, flat, per)
    log("pa", per, "base50", short(res[f"base50_noimpact_{per}"]))
    for Y in (0.5, 1.0):
        for nm, Q in SIZES.items():
            imp = np.minimum(Y * sig * np.sqrt(Q / adv), 0.10)
            imp = np.where(np.isfinite(imp), imp, 0.10)
            for base_nm, base in (("flat50", 0.005), ("tiered", tier / 1e4)):
                cost_row = base + 2 * imp
                key = f"{base_nm}_Y{Y}_{nm}_{per}"
                res[key] = pa_cost(sc, cost_row, per)
                log("pa", key, short(res[key]))
out["net_with_impact"] = res
save("s7_capacity", out)
