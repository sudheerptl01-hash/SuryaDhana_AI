"""Stage 6: investability of OOS scores (fast replica of L.portfolio_sim, verified exactly once).
Usage: python3 s6_invest.py <h> <step> <top_k> name=path [name=path ...]
Windows: full 2023-01-01..2026-09-10; dev = signals 2023-01-01..(last date with t+h <= 2025-12-31);
holdout = 2026-01-01..2026-09-10. Costs 50 / 80 bps round trip per leg.
Strategies per score:
  LO      long-only top_k by score on U (U = elig_base & equity ISIN, valid window)
  LO_reg  same but cash when Nifty500 < 200dma at signal (fixed a-priori rule, not tuned)
  LS_fno  50/50 long top_k + short bottom_k among fno_proxy names (market-neutral spread)
  SO_fno  short-only bottom_k among fno_proxy names
  AVOID   random top_k among U excluding the bottom 30% of score that day (10 seeds)
Baselines: random top_k from the same mask (10 seeds); random L/S on fno (10 seeds); Nifty 500.
"""
import sys
import time

import numpy as np
import pandas as pd

from common import OUT, L, save, Sim, stats_from_cohorts

h, step, K = int(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3])
specs = [a.split("=", 1) for a in sys.argv[4:]]
t0 = time.time()
P = L.load_panel(["date", "entity", "open", "close", "seg_break", "label_block"])
F = L.load_features(["mkt_dist_sma200", "mkt_mom20", "sector", "elig_base", "atr_pct"])
fw = L.Fwd(P)
meta = np.load(f"{OUT}/meta.npz")
U, fno = meta["U"], meta["fno"]
Z = np.load(f"{OUT}/labels_h{h}.npz")
r = Z["r"].astype("float64")
M = U & np.isfinite(r)
MF = M & fno
dates = P["date"].values.astype("datetime64[D]")
cal = np.unique(dates)
dev_end = str(cal[np.searchsorted(cal, np.datetime64("2025-12-31"), side="right") - 1 - h])
WIN = {"full": ("2023-01-01", "2026-09-10"), "dev": ("2023-01-01", dev_end), "hold": ("2026-01-01", "2026-09-10")}
bull = F["mkt_dist_sma200"].values > 0
reg = np.where(bull, "bull", "bear")
reg = np.char.add(reg.astype(str), np.where(F["mkt_mom20"].values > 0, "_up20", "_dn20"))
sim = Sim(P, fw, h)
tr = sim.tr_long
print("loaded", round(time.time() - t0, 1), "dev_end", dev_end, flush=True)
SEEDS = range(10)
out = {"params": {"h": h, "step": step, "top_k": K, "dev_end": dev_end, "windows": WIN}}


def summarize(cd, cr, picks, side, cost):
    trs = tr if side == "long" else -tr
    st = stats_from_cohorts(cd, cr, h, step, picks, trs, cost)
    return st


def window_stats(cd, cr, picks, side, cost):
    res = {}
    for w, (a, b) in WIN.items():
        sel = (cd >= np.datetime64(a)) & (cd <= np.datetime64(b))
        if sel.sum() < 3:
            continue
        res[w] = summarize(cd[sel], cr[sel], [p for p, s_ in zip(picks, sel) if s_], side, cost)
    return res


def keep(st):
    return {k: st[k] for k in ("cagr", "sharpe", "sharpe_adj", "max_dd", "hit_rate", "mean_trade_net", "trades", "by_year") if k in st}


# ---------- verification against lablib.portfolio_sim (once) ----------
if specs:
    sc0 = np.load(specs[0][1])["score"].astype("float64")
    ref = L.portfolio_sim(sc0, M, P, F, fw, h, step=step, top_k=K, cost_bps=50.0, start="2023-01-01", end="2026-09-10")
    cd, cr, pk = sim.cohorts(sc0, M, "M", step=step, top_k=K, cost_bps=50.0)
    mine = summarize(cd, cr, pk, "long", 50.0)
    out["verify_vs_lablib"] = {"lablib_cagr": ref["cagr"], "mine_cagr": mine["cagr"], "lablib_sharpe": ref["sharpe"],
                               "mine_sharpe": mine["sharpe"], "lablib_trades": ref["trades"], "mine_trades": mine["trades"]}
    print("verify", out["verify_vs_lablib"], flush=True)

# ---------- baselines ----------
bench = {w: L.benchmark(P, start=a, end=b) for w, (a, b) in WIN.items()}
out["nifty500"] = {w: {k: v for k, v in b.items()} for w, b in bench.items()}
base = {}
for cost in (50.0, 80.0):
    runs = []
    for sd in SEEDS:
        cd, cr, pk = sim.cohorts(None, M, "M", step=step, top_k=K, cost_bps=cost, random_seed=sd)
        runs.append(window_stats(cd, cr, pk, "long", cost))
    agg = {}
    for w in WIN:
        agg[w] = {k: float(np.mean([r_[w][k] for r_ in runs])) for k in ("cagr", "sharpe", "sharpe_adj", "max_dd", "hit_rate", "mean_trade_net")}
        agg[w]["cagr_sd"] = float(np.std([r_[w]["cagr"] for r_ in runs]))
        agg[w]["cagr_p95"] = float(np.percentile([r_[w]["cagr"] for r_ in runs], 95))
        agg[w]["by_year"] = {y: float(np.mean([r_[w]["by_year"].get(y, np.nan) for r_ in runs])) for y in runs[0][w]["by_year"]}
    base[f"LO_random_{int(cost)}"] = agg
    # random long/short on fno
    runs = []
    for sd in SEEDS:
        cdl, crl, pkl = sim.cohorts(None, MF, "MF", step=step, top_k=K, cost_bps=cost, random_seed=sd)
        cds, crs, pks = sim.cohorts(None, MF, "MF", step=step, top_k=K, cost_bps=cost, random_seed=1000 + sd, side="short")
        crls = 0.5 * (crl + crs)
        res = {}
        for w, (a, b) in WIN.items():
            sel = (cdl >= np.datetime64(a)) & (cdl <= np.datetime64(b))
            res[w] = stats_from_cohorts(cdl[sel], crls[sel], h, step)
        runs.append(res)
    base[f"LS_fno_random_{int(cost)}"] = {w: {k: float(np.mean([r_[w][k] for r_ in runs])) for k in ("cagr", "sharpe", "max_dd")} for w in WIN}
out["baselines"] = base
print("baselines", round(time.time() - t0, 1), {k: round(v["full"]["cagr"], 4) for k, v in base.items()}, flush=True)

# ---------- strategies per score ----------
for name, path in specs:
    sc = np.load(path)["score"].astype("float64")
    R = {}
    for cost in (50.0, 80.0):
        c = int(cost)
        cd, cr, pk = sim.cohorts(sc, M, "M", step=step, top_k=K, cost_bps=cost)
        R[f"LO_{c}"] = {w: keep(v) for w, v in window_stats(cd, cr, pk, "long", cost).items()}
        if cost == 50.0:
            # absolute-loss share of picked trades by regime (key risk) + pick characteristics
            allp = np.concatenate([p for p in pk if len(p)])
            df = pd.DataFrame({"reg": reg[allp], "r": tr[allp]})
            R["LO_picks_by_regime"] = {k: {"n": int(len(g)), "p_abs_loss_gross": float((g.r <= 0).mean()),
                                           "p_loss_net50": float((g.r < 0.005).mean()), "mean_r_bps": float(g.r.mean() * 1e4)}
                                       for k, g in df.groupby("reg")}
            R["LO_picks_atr_pct_median"] = float(np.median(F["atr_pct"].values[allp]))
            R["LO_picks_fno_share"] = float(fno[allp].mean())
            # random picks by regime (seed 0) for comparison
            cdr, crr, pkr = sim.cohorts(None, M, "M", step=step, top_k=K, cost_bps=cost, random_seed=0)
            allr = np.concatenate([p for p in pkr if len(p)])
            dfr = pd.DataFrame({"reg": reg[allr], "r": tr[allr]})
            R["RAND_picks_by_regime"] = {k: {"p_abs_loss_gross": float((g.r <= 0).mean()), "mean_r_bps": float(g.r.mean() * 1e4)}
                                         for k, g in dfr.groupby("reg")}
        # regime overlay: zero return cohorts when bear at signal date
        bull_c = np.array([bull[p[0]] if len(p) else False for p in pk])
        cr_reg = np.where(bull_c, cr, 0.0)
        R[f"LO_reg_{c}"] = {w: keep(v) for w, v in window_stats(cd, cr_reg, [p if b_ else np.array([], int) for p, b_ in zip(pk, bull_c)], "long", cost).items()}
        # long/short on fno
        cdl, crl, pkl = sim.cohorts(sc, MF, "MF", step=step, top_k=K, cost_bps=cost)
        cds, crs, pks = sim.cohorts(sc, MF, "MF", step=step, top_k=K, cost_bps=cost, side="short")
        crls = 0.5 * (crl + crs)
        R[f"LS_fno_{c}"] = {}
        R[f"SO_fno_{c}"] = {w: keep(v) for w, v in window_stats(cds, crs, pks, "short", cost).items()}
        R[f"LO_fno_{c}"] = {w: keep(v) for w, v in window_stats(cdl, crl, pkl, "long", cost).items()}
        for w, (a, b) in WIN.items():
            sel = (cdl >= np.datetime64(a)) & (cdl <= np.datetime64(b))
            st = stats_from_cohorts(cdl[sel], crls[sel], h, step)
            st["mean_cohort_spread_bps"] = float(np.mean(crls[sel]) * 1e4)
            st["cohort_hit"] = float((crls[sel] > 0).mean())
            R[f"LS_fno_{c}"][w] = {k: st[k] for k in ("cagr", "sharpe", "sharpe_adj", "max_dd", "by_year", "mean_cohort_spread_bps", "cohort_hit")}
        # AVOID: random picks among names not in bottom 30% of score that day
        pct = pd.Series(np.where(M & np.isfinite(sc), sc, np.nan)).groupby(dates).rank(pct=True).values
        MA = M & (pct > 0.3)
        runs = []
        for sd in SEEDS:
            cda, cra, pka = sim.cohorts(None, MA, f"MA_{name}", step=step, top_k=K, cost_bps=cost, random_seed=sd)
            runs.append(window_stats(cda, cra, pka, "long", cost))
        R[f"AVOID30_random_{c}"] = {w: {k: float(np.mean([r_[w][k] for r_ in runs])) for k in ("cagr", "sharpe", "max_dd", "hit_rate", "mean_trade_net")} for w in WIN}
    # gross / futures-like cost sensitivity for the fno long-short spread (not a central case)
    for cost in (0.0, 20.0):
        cdl, crl, pkl = sim.cohorts(sc, MF, "MF", step=step, top_k=K, cost_bps=cost)
        cds, crs, pks = sim.cohorts(sc, MF, "MF", step=step, top_k=K, cost_bps=cost, side="short")
        crls = 0.5 * (crl + crs)
        R[f"LS_fno_{int(cost)}"] = {}
        for w, (a, b) in WIN.items():
            sel = (cdl >= np.datetime64(a)) & (cdl <= np.datetime64(b))
            st = stats_from_cohorts(cdl[sel], crls[sel], h, step)
            st["mean_cohort_spread_bps"] = float(np.mean(crls[sel]) * 1e4)
            R[f"LS_fno_{int(cost)}"][w] = {k: st[k] for k in ("cagr", "sharpe", "max_dd", "by_year", "mean_cohort_spread_bps")}
    out[name] = R
    f = R["LO_50"]
    print(name, round(time.time() - t0, 1), "LO50", {w: (round(v["cagr"], 3), round(v["sharpe"], 2)) for w, v in f.items()},
          "LO80", {w: round(v["cagr"], 3) for w, v in R["LO_80"].items()},
          "LS50", {w: (round(v["cagr"], 3), round(v["sharpe"], 2)) for w, v in R["LS_fno_50"].items()},
          "AVOID50", {w: round(v["cagr"], 3) for w, v in R["AVOID30_random_50"].items()}, flush=True)
save(f"s6_invest_h{h}_s{step}_k{K}_" + "_".join(n for n, _ in specs), out)
print("done", round(time.time() - t0, 1))
