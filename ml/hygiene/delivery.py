#!/usr/bin/env python3
"""Delivery durability (ml/IMPROVEMENT_PLAN.md P5; ml/PROGRAM_REPORT.md section 11 item 5).

Universe: v1 dataset rows (ml/data_5y/model_dataset.parquet) with y_clean_20d True and a
y_excess_20d label; signal dates 2023-01-02..2026-09-16 (the walk-forward out-of-sample
window) and, separately, 2022-10-03..2022-12-30 (pre-OOS).

Features: deliv_pct_sma_20 (dataset) and deliv_value_share_20 (ml/results/scale5y/cache/
extra_5y.parquet, joined on date and ticker).  Controls: log_turnover, atr_pct, mom_12_1.

Per signal date and per name subset (all names; liquidity terciles cs_rank_turnover < 0.33,
0.33-0.67, >= 0.67; halves < 0.5 / >= 0.5), on the complete cases of feature, controls and
label, with at least 100 names:
  IC          = Spearman(feature, y_excess_20d);
  residual IC = Spearman(e, y_excess_20d), e = residual of the per-date OLS (with intercept)
                of the feature's percentile rank on the percentile ranks of the three controls.
Ranks are recomputed inside each subset.  The raw IC is computed on the same complete-case rows
as the residual IC so that the two differ only by the orthogonalisation; the raw IC on every
row with the feature and the label is reported for the full window as a coverage check.

Aggregation over dates: mean, Newey-West t (Bartlett, 20 lags) and a circular 20-session
moving-block bootstrap 95% CI (B = 1000, seed 108), the formulas of ml/scale5y_report.py; for
date groups that are not contiguous (market direction) the blocks run over the group's own
chronological date sequence.  Groups: calendar year, market direction of the month
(portfolio_5y.json direction_by_month), calendar half-year, and their crosses with the liquidity
subsets.  Pre/post March 2026: mean on dates < 2026-03-01 vs >= 2026-03-01 inside the OOS window,
difference with independent block bootstraps of the two segments (seeds 108 and 109).

Pre-registered reading: a feature is "durable" if its residual IC (all names) is > 0 with the
95% block-bootstrap CI excluding zero in at least 3 of the 4 calendar years (2023-2026) AND, over
the whole OOS window, in both liquidity halves.

Run:  PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=2 python3 -m ml.hygiene.delivery
"""
from __future__ import annotations

import json
import time

import numpy as np
import pandas as pd
from scipy.stats import rankdata

from ml.hygiene.common import (B_BOOT, BLOCK, CACHE5Y, DATA_5Y, NW_LAG, OUT, SCALE, SEED, block_index, ci95,
                               input_record, log, nw_t, nw_var_of_mean, wjson)

FEATURES = ["deliv_pct_sma_20", "deliv_value_share_20"]
CONTROLS = ["log_turnover", "atr_pct", "mom_12_1"]
TARGET = "y_excess_20d"
MIN_NAMES = 100
PRE = ("2022-10-03", "2022-12-30")
OOS = ("2023-01-02", "2026-09-16")
SPLIT = "2026-03-01"
YEARS = [2023, 2024, 2025, 2026]
SUBSETS = {"all": (None, None), "tercile_low": (None, 0.33), "tercile_mid": (0.33, 0.67),
           "tercile_high": (0.67, None), "half_illiquid": (None, 0.5), "half_liquid": (0.5, None)}
STATS = ("ic", "resid_ic")


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    den = np.sqrt((a @ a) * (b @ b))
    return float(a @ b / den) if den > 0 else float("nan")


def per_date(u: pd.DataFrame, feat: str) -> pd.DataFrame:
    """One row per (date, subset): n, IC, residual IC, R^2 of the control regression."""
    cols = [feat] + CONTROLS + [TARGET]
    cc = u[cols].notna().all(axis=1).to_numpy()
    v = u.loc[cc, ["date", "cs_rank_turnover"] + cols]
    d = v["date"].to_numpy()
    X = v[cols].to_numpy(float)
    liq = v["cs_rank_turnover"].to_numpy(float)
    cuts = np.flatnonzero(np.r_[True, d[1:] != d[:-1], True])
    rows = []
    for i in range(len(cuts) - 1):
        a, b = cuts[i], cuts[i + 1]
        Xd, ld = X[a:b], liq[a:b]
        for sname, (lo, hi) in SUBSETS.items():
            m = np.ones(len(Xd), bool)
            if lo is not None:
                m &= ld >= lo
            if hi is not None:
                m &= ld < hi
            n = int(m.sum())
            rec = {"date": d[a], "subset": sname, "n": n, "ic": np.nan, "resid_ic": np.nan, "r2": np.nan}
            if n >= MIN_NAMES:
                Z = Xd[m]
                R = rankdata(Z, axis=0)
                P = R / n
                A = np.column_stack([np.ones(n), P[:, 1:4]])
                beta, *_ = np.linalg.lstsq(A, P[:, 0], rcond=None)
                e = P[:, 0] - A @ beta
                rec["ic"] = _corr(R[:, 0], R[:, 4])
                rec["resid_ic"] = _corr(rankdata(e), R[:, 4])
                tss = ((P[:, 0] - P[:, 0].mean()) ** 2).sum()
                rec["r2"] = float(1 - (e @ e) / tss) if tss > 0 else np.nan
            rows.append(rec)
    out = pd.DataFrame(rows)
    out["date"] = pd.to_datetime(out["date"])
    return out


def feature_only_ic(u: pd.DataFrame, feat: str) -> pd.Series:
    """Raw IC on every row with the feature and the label (no control requirement), all names."""
    v = u.loc[u[[feat, TARGET]].notna().all(axis=1), ["date", feat, TARGET]]
    d = v["date"].to_numpy()
    X = v[[feat, TARGET]].to_numpy(float)
    cuts = np.flatnonzero(np.r_[True, d[1:] != d[:-1], True])
    vals, dates = [], []
    for i in range(len(cuts) - 1):
        a, b = cuts[i], cuts[i + 1]
        dates.append(d[a])
        if b - a >= MIN_NAMES:
            R = rankdata(X[a:b], axis=0)
            vals.append(_corr(R[:, 0], R[:, 1]))
        else:
            vals.append(np.nan)
    return pd.Series(vals, index=pd.to_datetime(dates))


def summarise(x: np.ndarray, names: np.ndarray | None = None, seed: int = SEED) -> dict:
    x = np.asarray(x, float)
    ok = np.isfinite(x)
    xs = x[ok]
    n = int(len(xs))
    if n < 2 * BLOCK:
        return {"n_dates": n, "mean": float(xs.mean()) if n else None, "nw_t": None, "ci95": [None, None],
                "share_dates_positive": float((xs > 0).mean()) if n else None,
                "note": "fewer than 40 dates: no t or CI"}
    boots = xs[block_index(n, B_BOOT, BLOCK, seed)].mean(1)
    lo, hi = ci95(boots)
    res = {"n_dates": n, "mean": float(xs.mean()), "nw_t": nw_t(xs, NW_LAG), "ci95": [lo, hi],
           "ci_excludes_zero_positive": bool(lo > 0), "ci_excludes_zero_negative": bool(hi < 0),
           "share_dates_positive": float((xs > 0).mean())}
    if names is not None:
        res["mean_names_per_date"] = float(np.asarray(names, float)[ok].mean())
    return res


def date_groups(dates: pd.DatetimeIndex, direction: dict) -> dict:
    """name -> boolean mask over `dates` (chronological)."""
    oos = (dates >= OOS[0]) & (dates <= OOS[1])
    g = {"oos_all": oos, "pre_oos_2022q4": (dates >= PRE[0]) & (dates <= PRE[1])}
    for y in YEARS:
        g[f"year_{y}"] = oos & (dates.year == y)
    mon = dates.strftime("%Y-%m")
    dirs = np.array([direction.get(m, "") for m in mon])
    g["direction_up"] = oos & (dirs == "up")
    g["direction_down"] = oos & (dirs == "down")
    for y in YEARS:
        g[f"half_{y}H1"] = oos & (dates.year == y) & (dates.month <= 6)
        g[f"half_{y}H2"] = oos & (dates.year == y) & (dates.month >= 7)
        for dname in ("up", "down"):
            g[f"year_{y}_x_direction_{dname}"] = oos & (dates.year == y) & (dirs == dname)
    g["pre_split_lt_2026-03-01"] = oos & (dates < SPLIT)
    g["post_split_ge_2026-03-01"] = oos & (dates >= SPLIT)
    return {k: np.asarray(v, bool) for k, v in g.items() if np.asarray(v, bool).any()}


def prepost(x: np.ndarray, dates: pd.DatetimeIndex) -> dict:
    oos = (dates >= OOS[0]) & (dates <= OOS[1])
    a = x[oos & (dates < SPLIT)]
    b = x[oos & (dates >= SPLIT)]
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    ba = a[block_index(len(a), B_BOOT, BLOCK, SEED)].mean(1)
    bb = b[block_index(len(b), B_BOOT, BLOCK, SEED + 1)].mean(1)
    diff = bb - ba
    se = np.sqrt(nw_var_of_mean(a) + nw_var_of_mean(b))
    return {"n_pre": int(len(a)), "n_post": int(len(b)), "mean_pre": float(a.mean()), "mean_post": float(b.mean()),
            "diff_post_minus_pre": float(b.mean() - a.mean()), "diff_ci95": ci95(diff),
            "diff_ci_excludes_zero": bool(ci95(diff)[1] < 0 or ci95(diff)[0] > 0),
            "diff_nw_t": float((b.mean() - a.mean()) / se) if se > 0 else None,
            "ci95_pre": ci95(ba), "ci95_post": ci95(bb)}


def main() -> None:
    t0 = time.time()
    log("delivery: start (inputs read-only: v1 dataset, extra_5y.parquet, portfolio_5y.json)", "delivery")
    port = json.loads((SCALE / "portfolio_5y.json").read_text())
    direction = port["direction_by_month"]
    cols = ["date", "ticker"] + [FEATURES[0]] + CONTROLS + ["cs_rank_turnover", TARGET, "y_clean_20d"]
    df = pd.read_parquet(DATA_5Y / "model_dataset.parquet", columns=cols)
    ex = pd.read_parquet(CACHE5Y / "extra_5y.parquet", columns=["date", "ticker", "deliv_value_share_20"])
    df["date"], ex["date"] = pd.to_datetime(df["date"]), pd.to_datetime(ex["date"])
    n_ds = len(df)
    df = df.merge(ex, on=["date", "ticker"], how="left", validate="one_to_one")
    assert len(df) == n_ds
    u = df[df["y_clean_20d"].astype(bool) & df[TARGET].notna()
           & (df["date"] >= PRE[0]) & (df["date"] <= OOS[1])].sort_values(["date", "ticker"], kind="stable")
    u = u.reset_index(drop=True)
    log(f"delivery: universe rows {len(u):,} on {u['date'].nunique()} dates "
        f"({u['date'].min().date()}..{u['date'].max().date()}); y_clean_20d True and label present", "delivery")
    coverage = {"universe_rows": int(len(u)), "universe_dates": int(u["date"].nunique())}
    pdres, out = {}, {}
    for f in FEATURES:
        t1 = time.time()
        cc = u[[f] + CONTROLS + [TARGET]].notna().all(axis=1)
        coverage[f] = {"feature_present_share": float(u[f].notna().mean()),
                       "complete_case_share": float(cc.mean()),
                       "complete_case_rows_oos": int((cc & (u["date"] >= OOS[0])).sum()),
                       "complete_case_rows_pre_oos": int((cc & (u["date"] <= PRE[1])).sum())}
        pdres[f] = per_date(u, f)
        log(f"delivery: per-date IC for {f}: {len(pdres[f]):,} (date, subset) cells in {time.time() - t1:.0f} s; "
            f"complete-case share {cc.mean():.4f}", "delivery")
    # date axis shared by every series
    dates = pd.DatetimeIndex(sorted(pdres[FEATURES[0]]["date"].unique()))
    groups = date_groups(dates, direction)
    series = {}
    for f in FEATURES:
        p = pdres[f]
        series[f] = {}
        for sname in SUBSETS:
            q = p[p["subset"] == sname].set_index("date").reindex(dates)
            series[f][sname] = {"ic": q["ic"].to_numpy(float), "resid_ic": q["resid_ic"].to_numpy(float),
                                "n": q["n"].to_numpy(float), "r2": q["r2"].to_numpy(float)}
    for f in FEATURES:
        res_f = {"by_subset": {}}
        for sname in SUBSETS:
            s = series[f][sname]
            res_s = {}
            for st in STATS:
                res_s[st] = {g: summarise(s[st][m], s["n"][m]) for g, m in groups.items()}
            res_s["prepost_march_2026"] = {st: prepost(s[st], dates) for st in STATS}
            res_s["mean_r2_controls_oos"] = float(np.nanmean(s["r2"][groups["oos_all"]]))
            res_f["by_subset"][sname] = res_s
        # coverage check: raw IC without the control requirement, all names
        fo = feature_only_ic(u, f).reindex(dates).to_numpy(float)
        res_f["ic_feature_only_sample_all_names"] = {g: summarise(fo[m]) for g, m in
                                                    groups.items() if g in ("oos_all", "pre_oos_2022q4")
                                                    or g.startswith("year_") and "_x_" not in g}
        # monthly means (descriptive)
        mon = dates.strftime("%Y-%m")
        res_f["monthly_mean"] = {st: {m: float(np.nanmean(series[f]["all"][st][mon == m]))
                                      for m in sorted(set(mon))} for st in STATS}
        out[f] = res_f
    # relation between the two features and with the controls (per-date Spearman, all names, OOS)
    rel = relations(u, dates[groups["oos_all"]])
    # pre-registered reading
    readings = {}
    for f in FEATURES:
        bs = out[f]["by_subset"]
        yrs = {y: bs["all"]["resid_ic"][f"year_{y}"] for y in YEARS}
        yrs_pass = [y for y, r in yrs.items() if r["mean"] > 0 and r["ci95"][0] is not None and r["ci95"][0] > 0]
        halves = {h: bs[h]["resid_ic"]["oos_all"] for h in ("half_illiquid", "half_liquid")}
        halves_pass = {h: bool(r["mean"] > 0 and r["ci95"][0] > 0) for h, r in halves.items()}
        durable = bool(len(yrs_pass) >= 3 and all(halves_pass.values()))
        yrs_pass_t = [y for y, r in yrs.items() if r["nw_t"] is not None and r["nw_t"] > 1.96]
        halves_pass_t = {h: bool(r["nw_t"] > 1.96) for h, r in halves.items()}
        strict = {h: [y for y in YEARS if bs[h]["resid_ic"][f"year_{y}"]["ci95"][0] is not None
                      and bs[h]["resid_ic"][f"year_{y}"]["mean"] > 0 and bs[h]["resid_ic"][f"year_{y}"]["ci95"][0] > 0]
                  for h in ("half_illiquid", "half_liquid")}
        readings[f] = {
            "stricter_reading_year_x_half": {
                "rule": "residual IC CI above zero in at least 3 of 4 years inside EACH liquidity half (not the "
                        "pre-registered rule; a robustness check of its interpretation)",
                "years_pass_by_half": strict,
                "passes": bool(all(len(v) >= 3 for v in strict.values()))},
            "years_residual_ic_ci_above_zero": yrs_pass, "n_years_pass": len(yrs_pass),
            "halves_residual_ic_ci_above_zero": halves_pass,
            "durable": durable, "verdict": "PASS" if durable else "FAIL",
            "secondary_same_rule_with_nw_t_gt_1.96": {
                "years": yrs_pass_t, "halves": halves_pass_t,
                "durable": bool(len(yrs_pass_t) >= 3 and all(halves_pass_t.values()))},
            "text": (f"{f}: residual IC CI above zero in {len(yrs_pass)} of 4 years "
                     f"({', '.join(map(str, yrs_pass)) or 'none'}); illiquid half "
                     f"{'yes' if halves_pass['half_illiquid'] else 'no'}, liquid half "
                     f"{'yes' if halves_pass['half_liquid'] else 'no'} -> "
                     f"{'PASS (durable)' if durable else 'FAIL (not durable by the pre-registered rule)'}"),
        }
        log(f"delivery: READING {readings[f]['text']}", "delivery")
    payload = {
        "generated_by": "ml/hygiene/delivery.py (seed 108)",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "method": {
            "universe": "v1 dataset rows with y_clean_20d True and y_excess_20d present; OOS signal dates "
                        f"{OOS[0]}..{OOS[1]}, pre-OOS {PRE[0]}..{PRE[1]} reported separately",
            "features": FEATURES, "controls": CONTROLS, "target": TARGET,
            "per_date": "complete cases of feature, the three controls and the label; >= 100 names per date and "
                        "subset; IC = Spearman(feature, label); residual IC = Spearman(residual of per-date OLS of "
                        "the feature's percentile rank on the controls' percentile ranks with intercept, label); "
                        "ranks recomputed inside each liquidity subset",
            "subsets": {k: {"cs_rank_turnover_ge": v[0], "cs_rank_turnover_lt": v[1]} for k, v in SUBSETS.items()},
            "aggregation": "mean over dates; Newey-West t (Bartlett, 20 lags); circular 20-session moving-block "
                           "bootstrap 95% percentile CI, B = 1000, seed 108 (formulas of ml/scale5y_report.py); "
                           "non-contiguous date groups are bootstrapped over their own chronological sequence",
            "direction": "portfolio_5y.json direction_by_month: sign of the EW universe's forward 20-day return "
                         "over the month's signal dates",
            "prepost": f"OOS dates < {SPLIT} vs >= {SPLIT}; independent block bootstraps of the two segments "
                       "(seeds 108 and 109); difference = post - pre",
            "reading": "durable = residual IC (all names) > 0 with the 95% block-bootstrap CI excluding zero in at "
                       "least 3 of the 4 calendar years 2023-2026 AND, over the whole OOS window, in both "
                       "liquidity halves (cs_rank_turnover < 0.5 and >= 0.5)",
            "discovery_overlap_note": "Both delivery features were first identified on the pilot's 16 months "
                                      "(ml/data/, 2025-06-02..2026-09); 2023 and 2024 are the years that played no "
                                      "part in finding them.",
        },
        "inputs": [input_record(DATA_5Y / "model_dataset.parquet", full_hash=False),
                   input_record(CACHE5Y / "extra_5y.parquet"), input_record(SCALE / "portfolio_5y.json")],
        "coverage": coverage,
        "relations_oos": rel,
        "readings": readings,
        "results": out,
        "seconds": round(time.time() - t0, 1),
    }
    wjson(OUT / "delivery_durability.json", payload)
    log(f"delivery: wrote {OUT / 'delivery_durability.json'} ({payload['seconds']} s)", "delivery")


def relations(u: pd.DataFrame, oos_dates: pd.DatetimeIndex) -> dict:
    """Mean per-date Spearman correlation among the delivery features and the controls (OOS, all names)."""
    cols = FEATURES + CONTROLS
    v = u[u["date"].isin(oos_dates)][["date"] + cols].dropna()
    d = v["date"].to_numpy()
    X = v[cols].to_numpy(float)
    cuts = np.flatnonzero(np.r_[True, d[1:] != d[:-1], True])
    acc = []
    for i in range(len(cuts) - 1):
        a, b = cuts[i], cuts[i + 1]
        if b - a >= MIN_NAMES:
            acc.append(np.corrcoef(rankdata(X[a:b], axis=0), rowvar=False))
    C = np.nanmean(np.stack(acc), axis=0)
    return {"columns": cols, "mean_per_date_spearman": C.round(4).tolist(), "n_dates": len(acc)}


if __name__ == "__main__":
    main()
