"""Stage 4: OOS diagnostics + investability for walk-forward scores.
Usage: python3 s4_eval.py <wf_tag> [<wf_tag> ...]
wf_tag like B20_f2.0_2.0_long_binary_2023-2024-2025-2026
Portfolio: L.portfolio_sim (unchanged code), exit_rule='barrier' matching the label
geometry (pt/sl multiples of atr_pct), top_k=20, step=5, 2023-01-01..2026-09-10,
50 & 80 bps, vs random baseline (5 seeds, same mask) and Nifty 500.
Sub-period (2023-25 selection / 2026 holdout) stats are computed from the
cohort equity curve (cohorts attributed to signal date).
"""
import json
import sys
import time

import numpy as np
import pandas as pd

from abar import L, OUT, update_results, save_json

START, END = "2023-01-01", "2026-09-10"
SEEDS = (11, 22, 33, 44, 55)
GEOM = {"B20_f2.0_2.0": (20, 2.0, 2.0), "B20_f3.0_1.5": (20, 3.0, 1.5), "B10_f2.0_1.5": (10, 2.0, 1.5),
        "B15_f2.0_2.0": (15, 2.0, 2.0), "B10_s0.75_0.75": (10, 0.75 * np.sqrt(10), 0.75 * np.sqrt(10)),
        "B10_s1.5_1.0": (10, 1.5 * np.sqrt(10), 1.0 * np.sqrt(10)),
        "T20_time_pm50": (20, 2.0, 2.0)}  # control: time label; barrier sims use the 2/2 geometry for comparison

t0 = time.time()
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["atr_pct", "elig_base", "fno_proxy", "sector"])
fw = L.Fwd(P)
elig = F["elig_base"].values.astype(bool)
fno = F["fno_proxy"].values.astype(bool)
dates = P["date"].values.astype("datetime64[D]")
year = pd.DatetimeIndex(P["date"].values).year.values
print("loaded", round(time.time() - t0, 1), flush=True)

_orig = L.barrier_labels
_cache = {}


def _memo(P_, F_, fw_, h, pt, sl, side="long", **kw):
    key = (h, round(float(pt), 6), round(float(sl), 6), side, tuple(sorted(kw.items())))
    if key not in _cache:
        _cache[key] = _orig(P_, F_, fw_, h, pt, sl, side=side, **kw)
    return _cache[key]


L.barrier_labels = _memo


def substats(res, step, lo, hi):
    eq = pd.Series(res["equity"])
    eq.index = pd.to_datetime(eq.index)
    sr = np.r_[eq.iloc[0] - 1, eq.values[1:] / eq.values[:-1] - 1]
    sr = pd.Series(sr, index=eq.index)
    s = sr[(sr.index >= pd.Timestamp(lo)) & (sr.index <= pd.Timestamp(hi))]
    if len(s) < 3:
        return None
    e = np.cumprod(1 + s.values)
    yrs = len(s) * step / 252
    return {"total": float(e[-1] - 1), "cagr": float(e[-1] ** (1 / yrs) - 1),
            "sharpe": float(s.mean() / s.std() * np.sqrt(252 / step)) if s.std() > 0 else None,
            "max_dd": float((e / np.maximum.accumulate(e) - 1).min())}


def slim(res, step):
    out = {k: res[k] for k in ("trades", "hit_rate", "mean_trade_net", "median_trade_net", "avg_bars_held",
                               "cagr", "sharpe", "max_dd", "by_year")}
    out["sel_2023_25"] = substats(res, step, "2023-01-01", "2025-12-31")
    out["hold_2026"] = substats(res, step, "2026-01-01", "2026-12-31")
    return out


def run_sims(score, mask, h, pt, sl, side, step=5, top_k=20, exit_rule="barrier", costs=(50, 80), rand=True):
    out = {}
    for c in costs:
        r = L.portfolio_sim(score, mask, P, F, fw, h, step=step, top_k=top_k, side=side, exit_rule=exit_rule,
                            pt=pt, sl=sl, cost_bps=c, start=START, end=END)
        out[f"model_{c}"] = slim(r, step)
        if rand:
            rr = [slim(L.portfolio_sim(score, mask, P, F, fw, h, step=step, top_k=top_k, side=side,
                                       exit_rule=exit_rule, pt=pt, sl=sl, cost_bps=c, start=START, end=END,
                                       random_seed=sd), step) for sd in SEEDS]
            agg = {}
            for k in ("cagr", "sharpe", "max_dd", "hit_rate", "mean_trade_net"):
                vals = [x[k] for x in rr]
                agg[k] = float(np.mean(vals))
                agg[k + "_sd"] = float(np.std(vals))
            for sub in ("sel_2023_25", "hold_2026"):
                agg[sub] = {k: float(np.mean([x[sub][k] for x in rr if x[sub] and x[sub][k] is not None]))
                            for k in ("total", "cagr", "sharpe", "max_dd")}
            yrs = sorted(rr[0]["by_year"].keys())
            agg["by_year"] = {y: float(np.mean([x["by_year"][y] for x in rr])) for y in yrs}
            out[f"random_{c}"] = agg
    return out


def diag(score, lab, ret, h):
    """Per-year OOS diagnostics on elig rows with score."""
    m = elig & np.isfinite(score) & ~np.isnan(lab)
    df = pd.DataFrame({"d": dates[m], "y": year[m], "s": score[m], "pos": (lab[m] == 1).astype(float),
                       "neg": (lab[m] == -1).astype(float), "ret": ret[m] - 0.005, "fno": fno[m]})
    df["r"] = df.groupby("d").s.rank(pct=True)
    df["smean"] = df.groupby("d").s.transform("mean")
    out = {}
    from sklearn.metrics import roc_auc_score
    for y, g in df.groupby("y"):
        o = {"n": int(len(g)), "base_pos": float(g.pos.mean()),
             "top10_pos": float(g[g.r > 0.9].pos.mean()), "bot10_pos": float(g[g.r <= 0.1].pos.mean()),
             "top10_neg": float(g[g.r > 0.9].neg.mean()), "bot10_neg": float(g[g.r <= 0.1].neg.mean()),
             "base_neg": float(g.neg.mean()),
             "all_net50": float(g.ret.mean()), "top10_net50": float(g[g.r > 0.9].ret.mean()),
             "bot10_net50": float(g[g.r <= 0.1].ret.mean()),
             "pooled_auc": float(roc_auc_score(g.pos, g.s)),
             "timing_auc_datemean_only": float(roc_auc_score(g.pos, g.smean))}
        # cross-sectional AUC per date (rank-based) and IC vs barrier return
        aucs, ics = [], []
        for d, gd in g.groupby("d"):
            p = gd.pos.values
            npos = p.sum()
            if 20 < len(gd) and 0 < npos < len(gd):
                rk = gd.s.rank().values
                aucs.append((rk[p == 1].sum() - npos * (npos + 1) / 2) / (npos * (len(gd) - npos)))
                ics.append(gd.s.rank().corr(gd.ret.rank()))
        o["xs_auc_mean"] = float(np.mean(aucs))
        ics = np.array(ics)
        o["ic_ret_mean"] = float(np.nanmean(ics))
        sub = ics[::h]
        o["ic_ret_t_nonoverlap"] = float(np.nanmean(sub) / (np.nanstd(sub) / np.sqrt(len(sub))))
        gf = g[g.fno]
        if len(gf) > 1000:
            rf = gf.groupby("d").s.rank(pct=True)
            o["fno_bot10_neg"] = float(gf[rf <= 0.1].neg.mean())
            o["fno_base_neg"] = float(gf.neg.mean())
            o["fno_bot10_net50_short"] = float(-(gf[rf <= 0.1].ret + 0.005).mean() - 0.005)
            o["fno_all_net50_short"] = float(-(gf.ret + 0.005).mean() - 0.005)
        out[int(y)] = o
    return out


def main(tags):
  labz = np.load(f"{OUT}/labels_shortlist.npz")
  for tag in tags:
      cid = "_".join(tag.split("_")[:3])
      side_lab = tag.split("_")[3]
      kind = tag.split("_")[4]
      h, pt, sl = GEOM[cid]
      score = np.load(f"{OUT}/wf_{tag}.npz")["score"].astype("float64")
      lz = labz if not cid.startswith("T") else np.load(f"{OUT}/labels_control.npz")
      lab = lz[f"{cid}_{side_lab}_lab"].astype("float64")
      ret = lz[f"{cid}_{side_lab}_ret"].astype("float64")
      res = {"tag": tag, "h": h, "pt": pt, "sl": sl}
      res["diag"] = diag(score, lab, ret, h)
      print(tag, "diag", round(time.time() - t0, 1), flush=True)
      m_long = elig & np.isfinite(score)
      res["long_barrier"] = run_sims(score, m_long, h, pt, sl, "long")
      print(tag, "long", res["long_barrier"]["model_50"]["cagr"], res["long_barrier"]["random_50"]["cagr"],
            round(time.time() - t0, 1), flush=True)
      res["long_time"] = run_sims(score, m_long, h, pt, sl, "long", exit_rule="time")
      res["long_barrier_k10"] = run_sims(score, m_long, h, pt, sl, "long", top_k=10, costs=(50,), rand=False)
      res["long_barrier_k40"] = run_sims(score, m_long, h, pt, sl, "long", top_k=40, costs=(50,), rand=False)
      m_short = m_long & fno
      res["short_barrier_fno"] = run_sims(score, m_short, h, pt, sl, "short")
      res["benchmark_nifty500"] = L.benchmark(P, start=START, end=END)
      res["benchmark_nifty500_2023_25"] = L.benchmark(P, start="2023-01-01", end="2025-12-31")
      res["benchmark_nifty500_2026"] = L.benchmark(P, start="2026-01-01", end=END)
      save_json(f"{OUT}/invest_{tag}.json", res)
      update_results(f"invest_{tag}", {k: v for k, v in res.items() if k != "diag"})
      print(tag, "done", round(time.time() - t0, 1), flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
