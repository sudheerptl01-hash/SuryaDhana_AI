#!/usr/bin/env python3
"""Probability of backtest overfitting (PBO) by combinatorially symmetric cross-validation (CSCV).

Bailey, Borwein, Lopez de Prado & Zhu (2017), "The probability of backtest overfitting",
Journal of Computational Finance 20(4), 39-69.

Generic method (``cscv``), for a T x M matrix of period performance of M trials:

1. split the T periods into S contiguous blocks of equal length L = T // S; the remainder
   T - S*L is dropped (from the end by default; the dropped periods are reported);
2. enumerate all C(S, S/2) ways of choosing S/2 blocks as in-sample (IS); the other S/2
   blocks are out-of-sample (OOS);
3. in each combination pick the trial n* with the best IS statistic (the IS mean for AUC,
   the IS Sharpe = mean / sd with ddof 1 for return series);
4. rank n*'s OOS statistic among the M trials' OOS statistics (average ranks, 1 = worst,
   M = best); relative rank r = (rank - 0.5) / M, logit lambda = ln(r / (1 - r));
5. PBO = share of combinations with lambda <= 0 (n* finished in the OOS bottom half).

Also reported, as in the paper: the performance-degradation regression (OOS statistic of
n* on its IS statistic across combinations), the probability of loss (n*'s OOS statistic
below zero skill: 0 for returns, 0.5 for AUC; and below the OOS median of the M trials),
and first-order stochastic dominance of n*'s OOS distribution over the pooled OOS
distribution of all trials (plus the second-order integral).

Chance level.  If no trial has skill, n*'s OOS rank is uniform on 1..M, so the expected PBO
is 1/2 for even M; for odd M the median rank (M+1)/2 has lambda = 0 exactly and the rule
"lambda <= 0" gives (M+1)/(2M) (5/9 = 0.556 for M = 9), "lambda < 0" gives (M-1)/(2M).
Both are reported, with the mid-rank convention (ties at lambda = 0 counted one half).

Pre-registered applications (ml/IMPROVEMENT_PLAN.md P5; reading fixed in advance: PBO above
0.5 means selection among those trials was no better than chance):
  (a) configurations: 43 monthly fold AUCs (2023-01..2026-07, holdout excluded) x 9 models;
  (b) books: 45 monthly net-of-20-bps values x 24 books (long-only books: net 20d return
      minus their EW benchmark's; long-short books: their own net 20d return);
  (c) the 16 long-only books of (b).

Run:  PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 python3 -m ml.hygiene.pbo
"""
from __future__ import annotations

import itertools
import json
import math
import time

import numpy as np
from scipy.stats import rankdata

from ml.hygiene.common import MODELS9, OUT, SCALE, SEED, input_record, log, wjson

S_PRIMARY = 16


# ============================================================================================= #
# generic CSCV
# ============================================================================================= #
def partition(T: int, S: int, mode: str = "drop_end") -> dict:
    """Contiguous blocks over the T periods.
    drop_end   : S equal blocks of L = T // S periods, remainder dropped from the end (primary);
    drop_start : the same, remainder dropped from the start;
    near_equal : all T periods in S contiguous blocks whose lengths differ by at most one."""
    if S < 2 or S % 2:
        raise ValueError("S must be even and >= 2")
    if mode == "near_equal":
        blocks = [b for b in np.array_split(np.arange(T), S)]
        used = np.arange(T)
    else:
        L = T // S
        if L < 1:
            raise ValueError(f"T = {T} is too short for S = {S}")
        if mode == "drop_end":
            used = np.arange(S * L)
        elif mode == "drop_start":
            used = np.arange(T - S * L, T)
        else:
            raise ValueError(mode)
        blocks = [used[i * L:(i + 1) * L] for i in range(S)]
    dropped = np.setdiff1d(np.arange(T), used)
    return {"blocks": blocks, "used": used, "dropped": dropped}


def _stat(n: np.ndarray, s1: np.ndarray, s2: np.ndarray, stat: str) -> np.ndarray:
    mu = s1 / n[:, None]
    if stat == "mean":
        return mu
    if stat == "sharpe":
        var = (s2 - n[:, None] * mu ** 2) / (n[:, None] - 1)
        return mu / np.sqrt(np.maximum(var, 1e-300))
    raise ValueError(stat)


def _summ(x: np.ndarray) -> dict:
    x = np.asarray(x, float)
    q = np.percentile(x, [1, 5, 25, 50, 75, 95, 99])
    return {"n": int(len(x)), "mean": float(x.mean()), "sd": float(x.std(ddof=1)) if len(x) > 1 else None,
            "min": float(x.min()), "q01": float(q[0]), "q05": float(q[1]), "q25": float(q[2]),
            "median": float(q[3]), "q75": float(q[4]), "q95": float(q[5]), "q99": float(q[6]),
            "max": float(x.max())}


def chance_pbo(M: int) -> dict:
    """Expected PBO when no trial has skill (n*'s OOS rank uniform on 1..M)."""
    if M % 2:
        return {"le_0": (M + 1) / (2 * M), "lt_0": (M - 1) / (2 * M), "mid": 0.5}
    return {"le_0": 0.5, "lt_0": 0.5, "mid": 0.5}


def cscv(perf, S: int = S_PRIMARY, stat: str = "mean", mode: str = "drop_end", zero: float = 0.0,
         trial_names: list[str] | None = None, period_labels: list[str] | None = None,
         keep_draws: bool = False) -> dict:
    perf = np.asarray(perf, float)
    T, M = perf.shape
    if not np.isfinite(perf).all():
        raise ValueError("perf must be finite")
    names = list(trial_names) if trial_names is not None else [f"trial_{j}" for j in range(M)]
    labels = list(period_labels) if period_labels is not None else [str(t) for t in range(T)]
    part = partition(T, S, mode)
    blocks = part["blocks"]
    nb = np.array([len(b) for b in blocks], float)
    s1 = np.stack([perf[b].sum(0) for b in blocks])                 # S x M
    s2 = np.stack([(perf[b] ** 2).sum(0) for b in blocks])
    combos = np.array(list(itertools.combinations(range(S), S // 2)))
    K = len(combos)
    C = np.zeros((K, S))
    C[np.arange(K)[:, None], combos] = 1.0
    n_is = C @ nb
    n_os = nb.sum() - n_is
    s1_is, s2_is = C @ s1, C @ s2
    s1_os, s2_os = s1.sum(0)[None, :] - s1_is, s2.sum(0)[None, :] - s2_is
    R = _stat(n_is, s1_is, s2_is, stat)                              # K x M, IS statistic
    Rb = _stat(n_os, s1_os, s2_os, stat)                             # K x M, OOS statistic
    nstar = R.argmax(1)
    kk = np.arange(K)
    ranks = rankdata(Rb, axis=1)                                     # 1 = worst OOS, M = best
    rk = ranks[kk, nstar]
    r = (rk - 0.5) / M
    lam = np.log(r / (1 - r))
    is_best, oos_best = R[kk, nstar], Rb[kk, nstar]
    oos_med = np.median(Rb, axis=1)
    mid_rank = (M + 1) / 2
    le = rk <= mid_rank + 1e-9
    lt = rk < mid_rank - 1e-9
    eq = ~lt & le
    # exact distribution of n*'s OOS rank (integer ranks unless the OOS statistics tie)
    vals, cnts = np.unique(np.round(rk, 6), return_counts=True)
    rank_dist = [{"oos_rank": float(v), "rank_fraction": float((v - 0.5) / M),
                  "logit": float(np.log(((v - 0.5) / M) / (1 - (v - 0.5) / M))),
                  "count": int(c), "share": float(c / K)} for v, c in zip(vals, cnts)]
    # performance degradation: OOS statistic of n* regressed on its IS statistic
    slope, intercept = np.polyfit(is_best, oos_best, 1)
    corr = float(np.corrcoef(is_best, oos_best)[0, 1])
    # stochastic dominance of n*'s OOS distribution over all trials' pooled OOS distribution
    allv = np.sort(Rb.ravel())
    bestv = np.sort(oos_best)
    grid = np.unique(np.concatenate([allv, bestv]))
    F_all = np.searchsorted(allv, grid, side="right") / allv.size
    F_best = np.searchsorted(bestv, grid, side="right") / bestv.size
    d = F_best - F_all                                               # FSD of best over all <=> d <= 0 everywhere
    sd2 = np.concatenate([[0.0], np.cumsum((F_all - F_best)[:-1] * np.diff(grid))])
    qs = [5, 25, 50, 75, 95]
    sel = np.bincount(nstar, minlength=M)
    full = _stat(np.array([nb.sum()]), s1.sum(0)[None, :], s2.sum(0)[None, :], stat)[0]
    full_rank = rankdata(full)
    trials = []
    for j in range(M):
        mj = nstar == j
        trials.append({"trial": names[j], "stat_on_used_periods": float(full[j]),
                       "rank_on_used_periods": float(full_rank[j]),
                       "share_combinations_selected_is_best": float(sel[j] / K),
                       "mean_oos_rank_fraction_when_selected": float(r[mj].mean()) if mj.any() else None,
                       "share_lambda_le0_when_selected": float(le[mj].mean()) if mj.any() else None})
    used, dropped = part["used"], part["dropped"]
    out = {
        "design": {"T_input": int(T), "M_trials": int(M), "S": int(S), "mode": mode, "statistic": stat,
                   "block_lengths": [int(len(b)) for b in blocks],
                   "periods_used": int(len(used)), "periods_dropped": int(len(dropped)),
                   "first_used": labels[int(used[0])], "last_used": labels[int(used[-1])],
                   "dropped_labels": [labels[int(i)] for i in dropped],
                   "blocks": [[labels[int(b[0])], labels[int(b[-1])]] for b in blocks],
                   "n_combinations": int(K), "zero_skill_level": float(zero),
                   "rank_convention": "average ranks of the OOS statistic, 1 = worst, M = best; "
                                      "r = (rank - 0.5) / M; logit = ln(r / (1 - r))"},
        "pbo": float(le.mean()),
        "pbo_strict_lt0": float(lt.mean()),
        "pbo_mid_rank": float(lt.mean() + 0.5 * eq.mean()),
        "share_lambda_eq0": float(eq.mean()),
        "chance_level": chance_pbo(M),
        "logit": _summ(lam),
        "oos_rank_fraction_of_is_best": _summ(r),
        "oos_rank_distribution": rank_dist,
        "degradation": {"slope": float(slope), "intercept": float(intercept), "corr": corr,
                        "r2": corr ** 2, "is_best_stat": _summ(is_best), "oos_best_stat": _summ(oos_best),
                        "share_oos_below_is": float((oos_best < is_best).mean()),
                        "note": "OLS of n*'s OOS statistic on its IS statistic across the combinations; "
                                "combinations overlap, so no standard errors are given. With complementary "
                                "halves a single trial's IS and OOS means sum to twice its full-sample mean, "
                                "so a negative slope is partly mechanical."},
        "prob_loss": {"below_zero_skill": float((oos_best < zero).mean()),
                      "zero_skill_level": float(zero),
                      "below_oos_median_of_trials": float((oos_best < oos_med).mean()),
                      "note": "below_oos_median equals PBO except for combinations where n* sits exactly "
                              "at the OOS median (possible only for odd M)"},
        "stochastic_dominance": {
            "first_order_holds": bool(d.max() <= 1e-12),
            "max_F_best_minus_F_all": float(d.max()),
            "x_at_max_violation": float(grid[int(d.argmax())]),
            "F_all_at_max_violation": float(F_all[int(d.argmax())]),
            "max_F_all_minus_F_best": float((-d).max()),
            "share_grid_F_best_le_F_all": float((d <= 1e-12).mean()),
            "second_order_holds": bool(sd2.min() >= -1e-12),
            "min_second_order_integral": float(sd2.min()),
            "quantiles_oos_is_best": {f"q{q:02d}": float(np.percentile(oos_best, q)) for q in qs},
            "quantiles_oos_all_trials": {f"q{q:02d}": float(np.percentile(Rb, q)) for q in qs},
            "mean_oos_is_best": float(oos_best.mean()), "mean_oos_all_trials": float(Rb.mean()),
            "note": "first-order dominance of n* over all trials <=> F_best(x) <= F_all(x) for every x"},
        "trials": trials,
    }
    if keep_draws:
        out["_draws"] = {"lambda": lam, "is_best": is_best, "oos_best": oos_best, "nstar": nstar}
    return out


# ============================================================================================= #
# self-test: brute force on small S, null and skill simulations
# ============================================================================================= #
def _naive(perf: np.ndarray, S: int, stat: str, mode: str) -> tuple[float, np.ndarray]:
    part = partition(perf.shape[0], S, mode)
    lams = []
    for c in itertools.combinations(range(S), S // 2):
        ins = np.concatenate([part["blocks"][i] for i in c])
        oos = np.concatenate([part["blocks"][i] for i in range(S) if i not in c])
        f = (lambda x: x.mean(0)) if stat == "mean" else (lambda x: x.mean(0) / x.std(0, ddof=1))
        a, b = f(perf[ins]), f(perf[oos])
        n = int(np.argmax(a))
        rank = 1 + (b < b[n]).sum() + 0.5 * ((b == b[n]).sum() - 1)
        r = (rank - 0.5) / perf.shape[1]
        lams.append(np.log(r / (1 - r)))
    lams = np.array(lams)
    return float((lams <= 1e-12).mean()), lams


def selftest(reps: int = 200) -> dict:
    rng = np.random.default_rng(SEED)
    out = {"brute_force_agreement": [], "null": {}, "skill": {}}
    for stat in ("mean", "sharpe"):
        for mode in ("drop_end", "drop_start", "near_equal"):
            X = rng.normal(size=(31, 6))
            fast = cscv(X, S=6, stat=stat, mode=mode, keep_draws=True)
            p_naive, lam_naive = _naive(X, 6, stat, mode)
            out["brute_force_agreement"].append({
                "stat": stat, "mode": mode, "pbo_fast": fast["pbo"], "pbo_naive": p_naive,
                "max_abs_logit_diff": float(np.max(np.abs(fast["_draws"]["lambda"] - lam_naive)))})
    for M, stat in ((9, "mean"), (24, "sharpe"), (16, "sharpe")):
        le, lt, mid = [], [], []
        for _ in range(reps):
            res = cscv(rng.normal(size=(32, M)), S=16, stat=stat)
            le.append(res["pbo"]); lt.append(res["pbo_strict_lt0"]); mid.append(res["pbo_mid_rank"])
        out["null"][f"M{M}_{stat}"] = {"reps": reps, "T": 32, "S": 16,
                                       "mean_pbo_le0": float(np.mean(le)), "mean_pbo_lt0": float(np.mean(lt)),
                                       "mean_pbo_mid": float(np.mean(mid)), "sd_pbo_le0": float(np.std(le)),
                                       "expected": chance_pbo(M)}
    pb = []
    for _ in range(reps):
        X = rng.normal(size=(32, 9)) + 0.15 * np.arange(9)[None, :]
        pb.append(cscv(X, S=16, stat="mean")["pbo"])
    out["skill"] = {"design": "T = 32, M = 9, trial j has mean 0.15*j and sd 1 (true ordering known)",
                    "reps": reps, "mean_pbo": float(np.mean(pb)), "q95_pbo": float(np.percentile(pb, 95))}
    ok_bf = all(abs(x["pbo_fast"] - x["pbo_naive"]) < 1e-12 and x["max_abs_logit_diff"] < 1e-9
                for x in out["brute_force_agreement"])
    ok_null = all(abs(v["mean_pbo_le0"] - v["expected"]["le_0"]) < 0.05 for v in out["null"].values())
    out["passed"] = bool(ok_bf and ok_null and out["skill"]["mean_pbo"] < 0.2)
    return out


# ============================================================================================= #
# inputs
# ============================================================================================= #
def load_config_auc() -> tuple[np.ndarray, list[str], list[str]]:
    cols, folds_ref = [], None
    for m in MODELS9:
        d = json.loads((SCALE / f"{m}__beat_mkt_20d.json").read_text())
        folds = [f for f in d["folds"] if f["fold"] != "holdout"]
        names = [f["fold"] for f in folds]
        if folds_ref is None:
            folds_ref = names
        if names != folds_ref:
            raise ValueError(f"{m}: fold order differs")
        cols.append([float(f["auc"]) for f in folds])
    X = np.array(cols).T
    if folds_ref != sorted(folds_ref) or len(folds_ref) != 43:
        raise ValueError("expected 43 chronological folds")
    return X, folds_ref, list(MODELS9)


def load_books() -> tuple[np.ndarray, list[str], list[str], dict]:
    d = json.loads((SCALE / "portfolio_5y.json").read_text())
    books = d["books"]
    names = list(books.keys())
    months = sorted(books[names[0]]["monthly_20bps"].keys())
    X = np.array([[float(books[b]["monthly_20bps"][m]) for b in names] for m in months])
    meta = {b: {"benchmark": books[b]["benchmark"], "monthly_metric": books[b]["monthly_metric"]} for b in names}
    for b in names:
        if sorted(books[b]["monthly_20bps"].keys()) != months:
            raise ValueError(f"{b}: months differ")
    return X, months, names, meta


# ============================================================================================= #
def _reading(res: dict, what: str) -> dict:
    p = res["pbo"]
    M = res["design"]["M_trials"]
    verdict = "no better than chance" if p > 0.5 else "better than chance"
    txt = (f"PBO = {p:.3f} ({'above' if p > 0.5 else 'not above'} 0.5): by the pre-registered reading, "
           f"selection among these {M} {what} was {verdict}.")
    if p <= 0.5:
        txt += " PBO at or below 0.5 says only that the in-sample best usually finished in the out-of-sample top half; it is not by itself evidence of skill."
    ch = res["chance_level"]["le_0"]
    if abs(ch - 0.5) > 1e-12:
        txt += (f" With M = {M} (odd) the chance level of the 'lambda <= 0' rule is {ch:.3f}; "
                f"strict rule PBO = {res['pbo_strict_lt0']:.3f}, mid-rank PBO = {res['pbo_mid_rank']:.3f} (chance 0.5).")
    return {"pbo": p, "above_0_5": bool(p > 0.5), "selection_no_better_than_chance": bool(p > 0.5), "text": txt}


def main() -> None:
    t0 = time.time()
    log("pbo: start (inputs read-only: per-model fold JSONs, portfolio_5y.json)", "pbo")
    st = selftest()
    log(f"pbo: self-test passed={st['passed']} null={json.dumps(st['null'])} skill={st['skill']['mean_pbo']:.3f}", "pbo")
    if not st["passed"]:
        raise SystemExit("self-test failed")
    Xa, folds, models = load_config_auc()
    Xb, months, books, bmeta = load_books()
    lo = [j for j, b in enumerate(books) if bmeta[b]["benchmark"] is not None]
    Xc, books_lo = Xb[:, lo], [books[j] for j in lo]
    if len(books_lo) != 16 or len(books) != 24 or Xb.shape[0] != 45:
        raise ValueError("expected 24 books x 45 months with 16 long-only")
    dup = {}
    for bk in ("top_decile", "ls_decile", "liq_top_decile"):
        a_, b_ = Xb[:, books.index(f"baseline_mom|{bk}")], Xb[:, books.index(f"heuristic_mom20|{bk}")]
        dup[bk] = int((np.abs(a_ - b_) < 1e-15).sum())
    dup_txt = ", ".join(f"{v} ({k})" for k, v in dup.items())
    dup_note = (f"baseline_mom and heuristic_mom20 books are identical in {dup_txt} of 45 months (one-feature logistic "
                "on the momentum rank vs the momentum rank itself), so 3 pairs among the 24 books are near-duplicates; "
                "OOS ties are average-ranked, which is why some OOS ranks are fractional.")
    log(f"pbo: {dup_note}", "pbo")
    analyses = {
        "a_configurations_auc": dict(X=Xa, labels=folds, names=models, stat="mean", zero=0.5,
                                     what="model configurations",
                                     input="fold AUC, 43 monthly folds 2023-01..2026-07 (holdout excluded) x 9 models"),
        "b_books_all24": dict(X=Xb, labels=months, names=books, stat="sharpe", zero=0.0, what="books",
                              input="monthly_20bps, 45 months 2023-01..2026-09 x 24 books; long-only = net 20d "
                                    "return minus the book's EW benchmark (ew_universe or ew_liquid); "
                                    "long-short = own net 20d return"),
        "c_books_long_only16": dict(X=Xc, labels=months, names=books_lo, stat="sharpe", zero=0.0,
                                    what="long-only books",
                                    input="the 16 long-only books of (b): top_decile vs ew_universe, "
                                          "liq_top_decile vs ew_liquid"),
    }
    variants = {"primary_S16_drop_end": (16, "drop_end"),
                "sens_S16_drop_start": (16, "drop_start"),
                "sens_S16_near_equal_all_periods": (16, "near_equal"),
                "sens_S14_drop_end": (14, "drop_end")}
    results, readings = {}, {}
    for key, a in analyses.items():
        res_k = {"input": a["input"], "statistic": "IS/OOS mean of fold AUC" if a["stat"] == "mean"
                 else "IS/OOS Sharpe (mean / sd, ddof 1) of the monthly series, not annualised",
                 "trial_names": a["names"]}
        for vk, (S, mode) in variants.items():
            res_k[vk] = cscv(a["X"], S=S, stat=a["stat"], mode=mode, zero=a["zero"],
                             trial_names=a["names"], period_labels=a["labels"])
            r = res_k[vk]
            log(f"pbo: {key} {vk}: PBO={r['pbo']:.4f} (lt {r['pbo_strict_lt0']:.4f}, mid {r['pbo_mid_rank']:.4f}) "
                f"logit mean={r['logit']['mean']:+.3f} slope={r['degradation']['slope']:+.3f} "
                f"p_loss0={r['prob_loss']['below_zero_skill']:.3f} p_below_med={r['prob_loss']['below_oos_median_of_trials']:.3f} "
                f"FSD={r['stochastic_dominance']['first_order_holds']} used {r['design']['first_used']}.."
                f"{r['design']['last_used']} dropped {r['design']['periods_dropped']}", "pbo")
        readings[key] = _reading(res_k["primary_S16_drop_end"], a["what"])
        readings[key]["sensitivity_pbo"] = {vk: res_k[vk]["pbo"] for vk in variants}
        results[key] = res_k
    payload = {
        "generated_by": "ml/hygiene/pbo.py (seed 108)",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "method": "CSCV (Bailey, Borwein, Lopez de Prado & Zhu 2017): S = 16 contiguous equal blocks "
                  "(L = T // 16, remainder dropped from the end), all C(16, 8) = 12,870 IS/OOS splits; "
                  "IS-best = highest IS mean (AUC) or IS Sharpe (returns); OOS relative rank r = (rank - 0.5) / M; "
                  "logit = ln(r / (1 - r)); PBO = share of logits <= 0. Sensitivity variants (not the reading): "
                  "remainder dropped from the start; all periods in 16 near-equal blocks; S = 14 equal blocks of 3.",
        "pre_registered_reading": "PBO above 0.5 means selection among those trials was no better than chance "
                                  "(ml/IMPROVEMENT_PLAN.md P5).",
        "inputs": [input_record(SCALE / f"{m}__beat_mkt_20d.json") for m in MODELS9]
                  + [input_record(SCALE / "portfolio_5y.json")],
        "dropped_periods_warning": "With T = 43 (configurations) or 45 (books) and S = 16, equal blocks are 2 periods "
                                   "long and the primary analysis uses 32 periods (2023-01..2025-08): 11 folds "
                                   "(2025-09..2026-07) or 13 months (2025-09..2026-09) are dropped from the end. The "
                                   "dropped stretch holds the 2025-09..2026-02 run and the March-2026 inversion, so "
                                   "the sensitivity variants that keep it are reported next to the reading.",
        "duplicate_trials_note": dup_note,
        "self_test": st,
        "readings": readings,
        "analyses": results,
        "seconds": round(time.time() - t0, 1),
    }
    wjson(OUT / "pbo.json", payload)
    log(f"pbo: wrote {OUT / 'pbo.json'} ({payload['seconds']} s)", "pbo")
    for k, v in readings.items():
        log(f"pbo: READING {k}: {v['text']}", "pbo")


if __name__ == "__main__":
    main()
