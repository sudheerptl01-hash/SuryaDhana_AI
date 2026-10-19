"""Stage 5: investability with L.Sim (daily MTM, staggered sleeves, next-open entry, slot sizing,
horizon-matched random baseline on the same mask, NW t of daily excess, lag h).
Blocks (python3 s5_invest.py BLOCK [BLOCK ...]):
  main    long top-20, step 5, h=20, 50/80 bps, dev/holdout: pure relative, pure absolute, label-side
          DUAL, two-model combinations
  ksens   K in {10,30,50} x step {5,10} for the main candidates (50 bps)
  gates   input-side sample filters (close>sma200, xr_mom60>0.7, both) with REL / DUAL scores
  avoid   equal-weight universe minus model bottom 30% (select_quantile=(0.3,1), sizing='equal')
  liq5    main candidates on elig_liq5
Each result row also has: book beta vs Nifty 500 (daily), down-day capture, worst 20d, and the
paired daily-difference NW t vs the pure-relative book with identical settings."""
import os
import sys
import time

import numpy as np
import pandas as pd

from common import OUT, L, save, xs_pct

BLOCKS = sys.argv[1:] or ["main"]
t0 = time.time()
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["atr_pct", "dist_sma200", "xr_mom60", "elig_liq5", "mkt_dist_sma200"])
fw = L.Fwd(P)
S = L.Sim(P, F, fw)
U = np.load(f"{OUT}/meta.npz")["U"]
dates = P["date"].values.astype("datetime64[D]")
H = 20
WIN = {"dev": (L.DEV[0], L.DEV[1]), "hold": (L.HOLDOUT[0], None)}
mk = L.market_series("Nifty 500")["close"]
mk = mk.reindex(pd.DatetimeIndex(S.cal)).ffill()
mret = pd.Series(mk.pct_change().values, index=S.cal)


def ld(tag):
    fn = f"{OUT}/wf_{tag}.npz"
    return np.load(fn)["score"].astype("float64") if os.path.exists(fn) else None


SC = {k: ld(k) for k in ("M_REL", "M_RUP", "M_RDN", "M_ABS", "M_BAR", "M_DUAL", "M_DUALP", "M_DDN", "M_DUALmc", "M_RELG",
                         "M_DUALt300")}
PCT = {k: xs_pct(v, dates, U) for k, v in SC.items() if v is not None}


def scores_main():
    s = {}
    for nm, k in (("REL", "M_REL"), ("DUAL", "M_DUAL"), ("DUALP", "M_DUALP"), ("ABS", "M_ABS"),
                  ("BAR", "M_BAR"), ("DUALmc", "M_DUALmc"), ("RUP", "M_RUP"),
                  ("DUALt300", "M_DUALt300")):
        if SC.get(k) is not None:
            s[nm] = SC[k]
    if "M_ABS" in PCT and "M_REL" in PCT:
        s["SUM_REL_ABS"] = PCT["M_REL"] + PCT["M_ABS"]                        # rank(rel)+rank(abs)
        s["AND_REL_ABS50"] = np.where(PCT["M_ABS"] >= 0.5, SC["M_REL"], np.nan)  # both models accept
    if "M_BAR" in PCT and "M_REL" in PCT:
        s["SUM_REL_BAR"] = PCT["M_REL"] + PCT["M_BAR"]
    if "M_RUP" in SC and "M_ABS" in SC and SC["M_RUP"] is not None and SC["M_ABS"] is not None:
        s["PROD_RUP_ABS"] = SC["M_RUP"] * SC["M_ABS"]                          # P(top30) x P(abs up)
    if "M_DUAL" in PCT and "M_REL" in PCT:
        s["SUM_REL_DUAL"] = PCT["M_REL"] + PCT["M_DUAL"]
    if "M_RUP" in PCT and "M_REL" in PCT:
        s["SUM_REL_RUP"] = PCT["M_REL"] + PCT["M_RUP"]       # pure-relative control for SUM_REL_DUAL
    return s


RB = {}
DAILY = {}


def extra(r, dts):
    mr = mret.reindex(dts).values
    ok = np.isfinite(r) & np.isfinite(mr)
    beta = float(np.cov(r[ok], mr[ok])[0, 1] / np.var(mr[ok], ddof=1))
    dn = ok & (mr < 0)
    up = ok & (mr > 0)
    eq = np.cumprod(1 + r)
    w20 = float(np.min(eq[20:] / eq[:-20] - 1)) if len(eq) > 21 else np.nan
    return {"beta": beta, "down_capture": float(r[dn].mean() / mr[dn].mean()),
            "up_capture": float(r[up].mean() / mr[up].mean()), "worst_20d": w20}


def run(name, score, mask, mkey, win, cost=50.0, step=5, top_k=20, sizing="slot", sq=None, h=H, ref=None):
    a, b = WIN[win]
    kw = dict(step=step, top_k=top_k, cost_bps=cost, start=a, end_exit=b, sizing=sizing, select_quantile=sq)
    st = S.run(score, mask, h, **kw)
    key = (mkey, h, step, top_k, cost, win, sizing, sq)
    if key not in RB:
        RB[key] = S.random_band(mask, h, seeds=(1, 2, 3, 4, 5), **kw)
    rb = RB[key]
    diff = st["_daily_ret"] - rb["_daily_ret_mean"]
    res = {k: v for k, v in st.items() if not k.startswith("_") and k != "params"}
    res.update({"name": name, "mask": mkey, "win": win, "cost": cost, "step": step, "top_k": top_k,
                "sizing": sizing, "sq": sq, "h": h,
                "rand_cagr": rb["cagr_mean"], "rand_cagr_sd": rb["cagr_sd"], "rand_sharpe": rb["sharpe_mean"],
                "rand_maxdd": rb["max_dd_mean"], "rand_by_year": rb["by_year_mean"],
                "excess_cagr": st["cagr"] - rb["cagr_mean"], "excess_nw_t": L.nw_t(diff, lag=h),
                "excess_ann": float(diff.mean() * 252)})
    res.update(extra(st["_daily_ret"], st["_dates"]))
    rk = (name, mkey, win, cost, step, top_k, sizing, sq)
    DAILY[rk] = st["_daily_ret"]
    refs = [] if ref is None else ([ref] if isinstance(ref, str) else list(ref))
    for i, rf in enumerate(refs):
        rr = DAILY.get((rf, mkey, win, cost, step, top_k, sizing, sq))
        if rr is not None and len(rr) == len(st["_daily_ret"]) and rf != name:
            d2 = st["_daily_ret"] - rr
            if i == 0:
                res["vs_ref"] = rf
                res["vs_ref_ann"] = float(d2.mean() * 252)
                res["vs_ref_nw_t"] = L.nw_t(d2, lag=h)
                res["corr_daily_with_ref"] = float(np.corrcoef(st["_daily_ret"], rr)[0, 1])
            res[f"vs_{rf}_ann"] = float(d2.mean() * 252)
            res[f"vs_{rf}_nw_t"] = L.nw_t(d2, lag=h)
    return res


def show(rows):
    for x in rows:
        x.setdefault("vs_RUP_ann", float("nan")); x.setdefault("vs_RUP_nw_t", float("nan"))
        print(f"{x['name']:>14} {x['mask']:>8} {x['win']:>4} c{int(x['cost'])} K{x['top_k']} s{x['step']} "
              f"cagr {x['cagr']:.3f} rnd {x['rand_cagr']:.3f} ex {x['excess_cagr']:.3f} t {x['excess_nw_t']:.2f} "
              f"dd {x['max_dd']:.3f} sh {x['sharpe']:.2f} b {x['beta']:.2f} "
              f"vsREL {x.get('vs_REL_ann', x.get('vs_ref_ann', float('nan'))):.3f}/{x.get('vs_REL_nw_t', x.get('vs_ref_nw_t', float('nan'))):.2f} "
              f"vsRUP {x['vs_RUP_ann']:.3f}/{x['vs_RUP_nw_t']:.2f}", flush=True)


if "main" in BLOCKS:
    rows = []
    sc = scores_main()
    order = ["REL", "RUP"] + [k for k in sc if k not in ("REL", "RUP")]
    for win in ("dev", "hold"):
        for cost in (50.0, 80.0):
            for nm in order:
                rows.append(run(nm, sc[nm], U, "U", win, cost=cost, ref=["REL", "RUP"]))
    show(rows)
    save("s5_main", rows)

if "ksens" in BLOCKS:
    rows = []
    sc = scores_main()
    names = [n for n in ("REL", "RUP", "DUAL", "DUALP", "DUALt300", "ABS", "SUM_REL_ABS", "AND_REL_ABS50",
                         "SUM_REL_DUAL", "SUM_REL_RUP") if n in sc]
    for win in ("dev", "hold"):
        for step in (5, 10):
            for k in (10, 20, 30, 50):
                for nm in names:
                    rows.append(run(nm, sc[nm], U, "U", win, cost=50.0, step=step, top_k=k,
                                    ref=["REL", "RUP"]))
    show(rows)
    save("s5_ksens", rows)

if "liq5" in BLOCKS:
    rows = []
    sc = scores_main()
    M5 = U & F["elig_liq5"].values.astype(bool)
    for win in ("dev", "hold"):
        for cost in (50.0, 80.0):
            for nm in ("REL", "RUP", "DUAL", "DUALP", "DUALt300", "ABS", "SUM_REL_ABS", "AND_REL_ABS50"):
                if nm in sc:
                    rows.append(run(nm, sc[nm], M5, "liq5", win, cost=cost, ref=["REL", "RUP"]))
    show(rows)
    save("s5_liq5", rows)

if "gates" in BLOCKS:
    rows = []
    sc = scores_main()
    ds200 = F["dist_sma200"].values.astype("float64")
    xr60 = F["xr_mom60"].values.astype("float64")
    mds = F["mkt_dist_sma200"].values.astype("float64")
    G = {"U": U, "G_sma200": U & (ds200 > 0), "G_rs70": U & (xr60 > 0.7),
         "G_trend": U & (ds200 > 0) & (xr60 > 0.7), "G_mkt200": U & (mds > 0)}
    gstats = {}
    for gk, gm in G.items():
        dd = pd.Series(gm[U]).groupby(dates[U]).mean()
        cnt = pd.Series(gm.astype(float)).groupby(dates).sum()
        cnt = cnt[cnt.index >= np.datetime64("2023-01-01")]
        gstats[gk] = {"share_of_U": float(gm.sum() / U.sum()), "daily_share_mean": float(dd.mean()),
                      "daily_share_std": float(dd.std()), "names_per_day_median": float(cnt.median()),
                      "days_with_lt20_names_2023+": int((cnt < 20).sum())}
    save("s5_gate_stats", gstats)
    for win in ("dev", "hold"):
        for cost in (50.0, 80.0):
            for gk, gm in G.items():
                for nm in ("REL", "DUAL", "ABS"):
                    if nm in sc:
                        rows.append(run(f"{nm}@{gk}", sc[nm], gm, gk, win, cost=cost,
                                        ref=f"REL@{gk}" if nm != "REL" else None))
                if gk == "G_trend" and SC.get("M_RELG") is not None:
                    rows.append(run("RELG@G_trend", SC["M_RELG"], gm, gk, win, cost=cost, ref="REL@G_trend"))
    # gate-only value: random within gate vs random within U (same settings)
    gate_only = []
    for win in ("dev", "hold"):
        for cost in (50.0, 80.0):
            base = RB[("U", H, 5, 20, cost, win, "slot", None)]
            for gk in G:
                rb = RB[(gk, H, 5, 20, cost, win, "slot", None)]
                diff = rb["_daily_ret_mean"] - base["_daily_ret_mean"]
                gate_only.append({"gate": gk, "win": win, "cost": cost, "rand_cagr_gate": rb["cagr_mean"],
                                  "rand_cagr_U": base["cagr_mean"], "gate_excess_cagr": rb["cagr_mean"] - base["cagr_mean"],
                                  "gate_excess_nw_t": L.nw_t(diff, lag=H), "rand_maxdd_gate": rb["max_dd_mean"],
                                  "rand_maxdd_U": base["max_dd_mean"]})
    show(rows)
    save("s5_gates", rows)
    save("s5_gate_only", gate_only)

if "avoid" in BLOCKS:
    rows = []
    av = {}
    if SC.get("M_DDN") is not None:
        av["AVOID_DDN"] = -SC["M_DDN"]
    if SC.get("M_RDN") is not None:
        av["AVOID_RDN"] = -SC["M_RDN"]
    if SC.get("M_RUP") is not None:
        av["AVOID_RUPup"] = SC["M_RUP"]
    if SC.get("M_REL") is not None:
        av["AVOID_REL"] = SC["M_REL"]
    if SC.get("M_DUAL") is not None:
        av["AVOID_DUALup"] = SC["M_DUAL"]
    if SC.get("M_ABS") is not None:
        av["AVOID_ABS"] = SC["M_ABS"]
    if SC.get("M_DUALmc") is not None:
        av["AVOID_DUALmc"] = SC["M_DUALmc"]
    for k_, nm_ in (("M_RUP", "AVOID_RUPup"), ("M_DUALP", "AVOID_DUALPup"), ("M_DUALt300", "AVOID_DUALt300up"),
                    ("M_BAR", "AVOID_BAR")):
        if SC.get(k_) is not None:
            av[nm_] = SC[k_]
    for mkey, mm in (("U", U), ("liq5", U & F["elig_liq5"].values.astype(bool))):
        for win in ("dev", "hold"):
            for cost in (50.0, 80.0):
                anys = next(iter(av.values()))
                rows.append(run("UNIVERSE_EW", anys, mm, mkey, win, cost=cost, sizing="equal", sq=(0.0, 1.0)))
                for nm, s in av.items():
                    x = run(nm, s, mm, mkey, win, cost=cost, sizing="equal", sq=(0.3, 1.0))
                    ref = DAILY[("UNIVERSE_EW", mkey, win, cost, 5, 20, "equal", (0.0, 1.0))]
                    d2 = DAILY[(nm, mkey, win, cost, 5, 20, "equal", (0.3, 1.0))] - ref
                    x["vs_universe_ann"] = float(d2.mean() * 252)
                    x["vs_universe_nw_t"] = L.nw_t(d2, lag=H)
                    for rn in ("AVOID_RDN", "AVOID_RUPup"):
                        rr = DAILY.get((rn, mkey, win, cost, 5, 20, "equal", (0.3, 1.0)))
                        if rr is not None and nm != rn:
                            d3 = DAILY[(nm, mkey, win, cost, 5, 20, "equal", (0.3, 1.0))] - rr
                            tag_ = "RDN" if rn == "AVOID_RDN" else "RUP"
                            x[f"vs_{tag_}_ann"] = float(d3.mean() * 252)
                            x[f"vs_{tag_}_nw_t"] = L.nw_t(d3, lag=H)
                    rows.append(x)
    for x in rows:
        print(f"{x['name']:>14} {x['mask']:>5} {x['win']:>4} c{int(x['cost'])} cagr {x['cagr']:.3f} rnd70 {x['rand_cagr']:.3f} "
              f"t {x['excess_nw_t']:.2f} vsU {x.get('vs_universe_ann', float('nan')):.3f}/{x.get('vs_universe_nw_t', float('nan')):.2f} "
              f"vsRDN {x.get('vs_RDN_ann', float('nan')):.3f}/{x.get('vs_RDN_nw_t', float('nan')):.2f} "
              f"vsRUP {x.get('vs_RUP_ann', float('nan')):.3f}/{x.get('vs_RUP_nw_t', float('nan')):.2f} dd {x['max_dd']:.3f}", flush=True)
    save("s5_avoid", rows)

np.savez_compressed(f"{OUT}/daily_{'_'.join(BLOCKS)}.npz",
                    **{"|".join(map(str, k)): v for k, v in DAILY.items()})
print("done", round(time.time() - t0, 1))
