#!/usr/bin/env python3
"""Stage 4: common-yardstick evaluation of every walk-forward model score.

usage: python3 s4_eval.py [names...]   (default: every wf_*.npz present; 'RANDOM' = baselines)

For each OOS score (multiclass P(+1)-P(-1)):
  learnability: daily cross-sectional AUC on its own label (up & down), daily rank IC vs the
                executable 5/10/20-day returns (same yardstick for every label), non-overlapping
                t-stats, top/bottom-decile excess return (bps) -- per year, 2026 separate.
  investability: long top-20 every 5 days (eq universe), exits: fixed 10d (S=2 sleeves),
                fixed 20d, ATR trailing stop (m=2,3; max 20 bars), running trend-scan exit
                (t<0, from bar 5; max 20) (all S=4); 50 & 80 bps; short bottom-20 on fno_proxy
                (fixed 10d).  Dev window (cohorts whose exit <= 2025-12-31) and 2026 holdout.
"""
import glob
import os
import sys
import time

import numpy as np
import pandas as pd

from common import OUT, L, eq_universe, make_label, save, load_res
from simlib import Engine, run

t0 = time.time()
names = sys.argv[1:] or sorted(os.path.basename(p)[3:-4] for p in glob.glob(f"{OUT}/wf_*.npz"))
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["elig_base", "fno_proxy", "atr_pct", "vol_20"])
fw = L.Fwd(P)
eng = Engine(P, F, fw)
eq = eq_universe(P, F)
fno = eq & F["fno_proxy"].values
Z = dict(np.load(f"{OUT}/labels.npz"))
dates = P["date"].values.astype("datetime64[D]")
cal = np.unique(dates)
year = pd.DatetimeIndex(dates).year.values
print("loaded", round(time.time() - t0, 1), flush=True)

START, END = "2023-01-01", "2026-09-10"


def dev_end(h):
    """last signal date whose exit (t+h trading days) is <= 2025-12-31."""
    j = np.searchsorted(cal, np.datetime64("2026-01-01")) - 1  # last 2025 session
    return cal[j - h]


def windows(picks, h):
    de = dev_end(h)
    return {"full": picks,
            "dev": [(d, p) for d, p in picks if d <= de],
            "hold2026": [(d, p) for d, p in picks if d >= np.datetime64("2026-01-01")]}


def strip(res):
    return {k: v for k, v in res.items() if not k.startswith("_")}


def sim_block(picks, side="long", rules=None):
    out = {}
    rules = rules or [("fixed10", dict(rule="fixed", h=10), 10), ("fixed20", dict(rule="fixed", h=20), 20),
                      ("atr2", dict(rule="atr", m=2.0), 20), ("atr3", dict(rule="atr", m=3.0), 20),
                      ("tsexit", dict(rule="tsexit", t_exit=0.0), 20)]
    for nm, kw, hs in rules:
        for cost in (50.0, 80.0):
            if cost == 80.0 and nm not in ("fixed10", "fixed20"):
                continue
            for wn, pk in windows(picks, hs).items():
                r = run(eng, pk, side=side, h_slots=hs, step=5, cost_bps=cost, **kw)
                out[f"{nm}_c{int(cost)}_{wn}"] = strip(r)
    return out


# ---------------------------------------------------------------- learnability helpers
def xs_auc(score, ybin, m):
    df = pd.DataFrame({"d": dates[m], "s": score[m], "y": ybin[m].astype(float), "yr": year[m]})
    df["r"] = df.groupby("d").s.rank()
    df["rp"] = df.r * df.y
    g = df.groupby("d").agg(n=("y", "size"), npos=("y", "sum"), rs=("rp", "sum"), yr=("yr", "first"))
    g = g[(g.npos > 0) & (g.npos < g.n)]
    g["auc"] = (g.rs - g.npos * (g.npos + 1) / 2) / (g.npos * (g.n - g.npos))
    return g


def daily_ic(score, ret, m):
    m = m & np.isfinite(score) & np.isfinite(ret)
    df = pd.DataFrame({"d": dates[m], "a": score[m], "b": ret[m], "yr": year[m]})
    df["ra"] = df.groupby("d").a.rank()
    df["rb"] = df.groupby("d").b.rank()
    df["ra"] -= df.groupby("d").ra.transform("mean")
    df["rb"] -= df.groupby("d").rb.transform("mean")
    df["ab"] = df.ra * df.rb
    df["aa"] = df.ra ** 2
    df["bb"] = df.rb ** 2
    g = df.groupby("d").agg(ab=("ab", "sum"), aa=("aa", "sum"), bb=("bb", "sum"), n=("ab", "size"), yr=("yr", "first"))
    g = g[g.n > 20]
    g["ic"] = g.ab / np.sqrt(g.aa * g.bb)
    return g[["ic", "yr"]]


def tstat_nonoverlap(s, h):
    s = s.iloc[::h]
    return float(s.mean() / (s.std() / np.sqrt(len(s)))) if len(s) > 3 else None


def decile_excess(score, ret, m):
    m = m & np.isfinite(score) & np.isfinite(ret)
    df = pd.DataFrame({"d": dates[m], "s": score[m], "r": ret[m], "yr": year[m]})
    df["pr"] = df.groupby("d").s.rank(pct=True)
    df["ex"] = df.r - df.groupby("d").r.transform("mean")
    top = df[df.pr > 0.9].groupby("d").agg(ex=("ex", "mean"), yr=("yr", "first"))
    bot = df[df.pr <= 0.1].groupby("d").agg(ex=("ex", "mean"), yr=("yr", "first"))
    return top, bot


def by_year(series_df, col, fn=np.mean):
    return {int(y): float(fn(g[col])) for y, g in series_df.groupby("yr")}


def learn_block(score, y):
    out = {}
    m = eq & np.isfinite(score) & (dates >= np.datetime64(START))
    if y is not None:
        ml = m & np.isfinite(y)
        gu = xs_auc(score, y == 1, ml)
        gd = xs_auc(-score, y == -1, ml)
        out["xs_auc_up_by_year"] = by_year(gu, "auc")
        out["xs_auc_down_by_year"] = by_year(gd, "auc")
        out["xs_auc_up_dev"] = float(gu[gu.yr <= 2025].auc.mean())
        out["xs_auc_down_dev"] = float(gd[gd.yr <= 2025].auc.mean())
        out["xs_auc_up_t_dev"] = tstat_nonoverlap(gu[gu.yr <= 2025].auc - 0.5, 20)
    for h in (5, 10, 20):
        r = Z[f"r{h}"].astype(float)
        g = daily_ic(score, r, m)
        out[f"ic_r{h}_by_year"] = by_year(g, "ic")
        out[f"ic_r{h}_dev"] = float(g[g.yr <= 2025].ic.mean())
        out[f"ic_r{h}_t_dev"] = tstat_nonoverlap(g[g.yr <= 2025].ic, h)
        out[f"ic_r{h}_2026"] = float(g[g.yr == 2026].ic.mean()) if (g.yr == 2026).any() else None
        out[f"ic_r{h}_t_2026"] = tstat_nonoverlap(g[g.yr == 2026].ic, h)
        out[f"ic_r{h}_share_pos_years_dev"] = float(np.mean([v > 0 for k, v in out[f"ic_r{h}_by_year"].items() if k <= 2025]))
        if h in (10, 20):
            top, bot = decile_excess(score, r, m)
            out[f"top_dec_ex_r{h}_bps_by_year"] = {k: v * 1e4 for k, v in by_year(top, "ex").items()}
            out[f"bot_dec_ex_r{h}_bps_by_year"] = {k: v * 1e4 for k, v in by_year(bot, "ex").items()}
            out[f"top_dec_ex_r{h}_bps_dev"] = float(top[top.yr <= 2025].ex.mean() * 1e4)
            out[f"bot_dec_ex_r{h}_bps_dev"] = float(bot[bot.yr <= 2025].ex.mean() * 1e4)
            # fno-only (shortable) bottom decile
            mf = fno & np.isfinite(score) & (dates >= np.datetime64(START))
            topf, botf = decile_excess(score, r, mf)
            out[f"fno_bot_dec_ex_r{h}_bps_by_year"] = {k: v * 1e4 for k, v in by_year(botf, "ex").items()}
            out[f"fno_top_dec_ex_r{h}_bps_by_year"] = {k: v * 1e4 for k, v in by_year(topf, "ex").items()}
    return out


# ---------------------------------------------------------------- verification against lablib
res_all = load_res()
if "s4_verify" not in res_all and names and names[0] != "RANDOM":
    sc = np.load(f"{OUT}/wf_{names[0]}.npz")["score"].astype(float)
    ref = L.portfolio_sim(sc, eq, P, F, fw, h=10, step=5, top_k=20, cost_bps=50.0, start=START, end=END)
    mine = run(eng, eng.pick(sc, eq, "eq", 10, start=START, end=END), rule="fixed", h=10, side="long",
               h_slots=10, step=5, cost_bps=50.0)
    ref_r = L.portfolio_sim(sc, eq, P, F, fw, h=10, step=5, top_k=20, cost_bps=50.0, start=START, end=END,
                            random_seed=1)
    mine_r = run(eng, eng.pick(None, eq, "eq", 10, start=START, end=END, random_seed=1), rule="fixed", h=10,
                 side="long", h_slots=10, step=5, cost_bps=50.0)
    v = {"model": names[0], "lablib": {k: ref[k] for k in ("cagr", "sharpe", "max_dd", "trades", "mean_trade_net")},
         "mine": {k: mine[k] for k in ("cagr", "sharpe", "max_dd", "trades", "mean_trade_net")},
         "lablib_random1": {k: ref_r[k] for k in ("cagr", "sharpe", "trades")},
         "mine_random1": {k: mine_r[k] for k in ("cagr", "sharpe", "trades")}}
    print(v, flush=True)
    save("s4_verify", v)

# ---------------------------------------------------------------- per model
for name in names:
    t1 = time.time()
    if name == "RANDOM":
        out = {"seeds": [0, 1, 2, 3, 4]}
        acc = {}
        for seed in out["seeds"]:
            pk = eng.pick(None, eq, "eq", 10, start=START, end=END, random_seed=seed)
            blk = sim_block(pk)
            pks = eng.pick(None, fno, "fno", 10, side="short", start=START, end=END, random_seed=seed)
            blk.update({f"short_{k}": v for k, v in sim_block(pks, side="short", rules=[
                ("fixed10", dict(rule="fixed", h=10), 10)]).items()})
            for k, v in blk.items():
                acc.setdefault(k, []).append(v)
        # average numeric stats across seeds
        avg = {}
        for k, lst in acc.items():
            d = {}
            for fld in ("cagr", "sharpe", "sharpe_rho_adj", "max_dd", "hit_rate", "mean_trade_net", "avg_bars_held",
                        "net_per_bar_bps", "total_return"):
                vals = [x[fld] for x in lst if fld in x and x[fld] is not None]
                if vals:
                    d[fld] = float(np.mean(vals))
                    d[fld + "_sd"] = float(np.std(vals))
            yrs = sorted(set().union(*[x["by_year"].keys() for x in lst]))
            d["by_year"] = {int(y): float(np.mean([x["by_year"].get(y, np.nan) for x in lst])) for y in yrs}
            yrs = sorted(set().union(*[x.get("mean_trade_net_by_year", {}).keys() for x in lst]))
            d["mean_trade_net_by_year"] = {int(y): float(np.mean([x["mean_trade_net_by_year"].get(y, np.nan) for x in lst])) for y in yrs}
            avg[k] = d
        out["avg"] = avg
        bm = {"full": L.benchmark(P, start=START, end=END),
              "dev": L.benchmark(P, start=START, end="2025-12-31"),
              "hold2026": L.benchmark(P, start="2026-01-01", end=END)}
        out["nifty500"] = bm
        save("s4_RANDOM", out)
        print("RANDOM done", round(time.time() - t1, 1), flush=True)
        continue
    sc = np.load(f"{OUT}/wf_{name}.npz")["score"].astype(float)
    y = make_label(name, Z, F["vol_20"].values)
    out = {"learn": learn_block(sc, y)}
    print(name, "learn", round(time.time() - t1, 1), {k: v for k, v in out["learn"].items() if k.endswith("_dev")}, flush=True)
    pk = eng.pick(sc, eq, "eq", 10, start=START, end=END)
    out["long"] = sim_block(pk)
    pks = eng.pick(sc, fno, "fno", 10, side="short", start=START, end=END)
    out["short_fno"] = sim_block(pks, side="short", rules=[("fixed10", dict(rule="fixed", h=10), 10)])
    # long-only restricted to fno names (same universe as short) for a market-neutral spread reference
    pkl = eng.pick(sc, fno, "fno", 10, side="long", start=START, end=END)
    out["long_fno"] = sim_block(pkl, rules=[("fixed10", dict(rule="fixed", h=10), 10)])
    save(f"s4_{name}", out)
    L_ = out["long"]
    print(name, "sim", round(time.time() - t1, 1),
          {k: (round(L_[k]["cagr"], 4), round(L_[k]["sharpe"], 2)) for k in L_ if k.endswith("_full")}, flush=True)
print("done", round(time.time() - t0, 1))
