#!/usr/bin/env python3
"""P2 book construction and costs (ml/IMPROVEMENT_PLAN.md, stream P2) -- single entry point.

    cd /home/user/SuryaDhana_AI && python3 -m ml.books.construct

1. Acceptance test: the 24 five-year books of ml/scale5y_report.py portfolio() rebuilt from the parquet prices and
   compared leaf by leaf with ml/results/scale5y/portfolio_5y.json (stop if any number differs at 3 decimals).
2. The fixed grid of 42 trials: scorers {nested_lgbm, all51, nested_ensemble_rank} x neutralisation {none, vol,
   vol+size, vol+size+industry} x basket {top_decile, top_quintile, buffered_decile} (36), the liquid-tercile
   buffered decile under vol+size (3), the vol+size top decile held 40 sessions (3).
3. Every book (24 + 42 = 66) at 10/20/40 bps per side, 20 bps without netting and the pre-specified name-level cost
   model; break-even flat cost; PSR/DSR on the daily net 20 bps skill series with V[SR] across all 66 books at
   N = 177 (comparability), N = 238 (this phase's headline) and N = 239 (plan amendment A1).
4. Pass marks B1, B2, B3 and gates 3 and 5 for any book passing B1.

Outputs (ml/results/improve/books/): reproduction_check.json, books.json, monthly_series.json, BOOKS.md, log.txt.
Seed 108, OMP_NUM_THREADS=2, single process. Prices: ml/results/improve/cache/features_prices_export_v1.parquet.
"""
from __future__ import annotations

import os

os.environ["OMP_NUM_THREADS"] = "2"
os.environ.setdefault("OPENBLAS_NUM_THREADS", "2")
os.environ.setdefault("MKL_NUM_THREADS", "2")

import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd

import ml.strategy_backtest as sb
from ml.books import data as D
from ml.books import engine as E
from ml.books import reproduce as RP
from ml.books.report import write_markdown

ML_DIR = Path(__file__).resolve().parents[1]
OUT = ML_DIR / "results" / "improve" / "books"
SEED = 108
SCORERS = ["nested_lgbm", "all51", "nested_ensemble_rank"]
NEUTS = ["none", "vol", "vol+size", "vol+size+industry"]
P2_BASKETS = ["top_decile", "top_quintile", "buffered_decile"]
H_LONG = 40
N_5Y, N_PHASE, N_AMENDED = 177, 238, 239
N_LIST = (N_5Y, N_PHASE, N_AMENDED)
COST_KEYS = ("gross", "10bps", "20bps", "40bps", "20bps_no_netting", E.NAME_KEY)
YEARS = ("2023", "2024", "2025", "2026")
TRIAL_LEDGER = {
    "scale5y_books_reproduced": 24, "p2_grid_scorer_x_neutralisation_x_basket": 36,
    "p2_liquid_buffered_vol_size": 3, "p2_hold40_vol_size_top_decile": 3,
    "note": "N = 238 is this phase's headline (plan section 1: 177 + 61 new trials, of which these 42). Plan "
            "amendment A1 (2026-10-19 13:00, AB0) raised the ledger to N = 239; DSR is also reported at 239. "
            "The three none|top_decile grid books are the same baskets as the frozen scorer|top_decile books; the "
            "plan counts them as trials and V[SR] uses all 66 books as instructed, duplicates included."}

T0 = time.time()
_LOG = None


def log(msg: str) -> None:
    line = f"[books +{time.time() - T0:6.0f}s] {msg}"
    print(line, flush=True)
    if _LOG is not None:
        with open(_LOG, "a") as fh:
            fh.write(line + "\n")


def wjson(path: Path, obj) -> None:
    path.write_text(json.dumps(sb.clean_json(obj), indent=1, allow_nan=False) + "\n")


# --------------------------------------------------------------------------- diagnostics
def per_date_spearman(codes: np.ndarray, a: np.ndarray, b: np.ndarray) -> float:
    ok = np.isfinite(a) & np.isfinite(b)
    df = pd.DataFrame({"d": codes[ok], "a": a[ok], "b": b[ok]})
    ra, rb = df.groupby("d")["a"].rank().to_numpy(), df.groupby("d")["b"].rank().to_numpy()
    d = df["d"].to_numpy()
    nd = int(codes.max()) + 1
    n = np.bincount(d, minlength=nd).astype(float)
    sx, sy = np.bincount(d, ra, nd), np.bincount(d, rb, nd)
    sxx, syy, sxy = np.bincount(d, ra * ra, nd), np.bincount(d, rb * rb, nd), np.bincount(d, ra * rb, nd)
    with np.errstate(invalid="ignore", divide="ignore"):
        cov = sxy / n - sx * sy / n ** 2
        c = cov / np.sqrt((sxx / n - (sx / n) ** 2) * (syy / n - (sy / n) ** 2))
    return float(np.nanmean(c[n >= 50]))


# --------------------------------------------------------------------------- one book's summary
def summarize(key: str, r: dict, eng: E.BookEngine, meta: dict, direction: dict) -> dict:
    H, blocks = eng.H, eng.blocks
    is_ls = meta["basket"].endswith("ls_decile")
    month_of = np.array([b.month for b in blocks])
    up = np.array([direction[m] == "up" for m in month_of])
    res = r["results"]

    def row(ck: str, seg: str) -> dict:
        t, dl = res[ck][seg]["tranche"], res[ck][seg]["daily"]
        o = {"ann_return": t["ann_return_252_h"], "sharpe": dl["sharpe"], "sharpe_ci95": dl["sharpe_ci95"],
             "ann_vol": dl["ann_vol"], "max_dd": dl["max_dd"]}
        if is_ls:
            o["hit_net_positive_tranches"] = t["hit_rate_net_positive"]
        else:
            da, ba = res[ck][seg]["daily_active"], res[ck][seg]["beta_alpha_vs_benchmark"]
            o.update({"excess_ann_vs_ew": t["active_ann_252_h"], "excess_ann_vs_ew_daily": da["ann_mean_daily"],
                      "ir": da["sharpe"], "ir_ci95": da["sharpe_ci95"], "p_ir_gt0": da["p_sharpe_gt0"],
                      "excess_max_dd": da["max_dd"], "hit_vs_ew_tranches": t["hit_rate_vs_ew"],
                      "beta_vs_bench": ba["beta_vs_benchmark"], "alpha_ann_vs_bench": ba["alpha_ann"]})
        return o

    segs = {"combined": {ck: row(ck, "combined") for ck in COST_KEYS},
            "cv": {ck: row(ck, "cv") for ck in ("20bps", E.NAME_KEY)},
            "holdout": {ck: row(ck, "holdout") for ck in ("20bps", E.NAME_KEY)}}
    R = r["_tranche"]["20bps"]["R"]
    val = R if is_ls else R - r["_bench_R"]
    mon = pd.Series(val).groupby(month_of).mean()
    cvmon = mon[[mo for mo in mon.index if mo < "2026-08"]]
    per20 = sb.HORIZON / H
    by_year = {yy: float(val[np.char.startswith(month_of.astype(str), yy)].mean()) for yy in YEARS
               if np.char.startswith(month_of.astype(str), yy).any()}
    by_dir = {"up": float(val[up].mean()), "down": float(val[~up].mean())}
    be = r["breakeven_cost_per_side"]
    return {
        "key": key, **meta, "H": H, "benchmark": None if is_ls else r["benchmark"],
        "n_signal_dates": len(blocks), "basket_size_mean": r["basket_size_mean"],
        "turnover_per_rebalance": r["turnover_per_rebalance"],
        "turnover_annualised": r["turnover_per_rebalance"] * sb.PPY / H,
        "turnover_per_rebalance_short": r.get("turnover_per_rebalance_short"),
        "daily_churn": r["daily_churn"], "capacity": r["capacity"],
        "breakeven_flat_cost_bps_per_side": None if be is None else 1e4 * be,
        "breakeven_note": None if be is not None else "gross excess <= 0: no positive break-even cost",
        "name_level_trade_weighted_cost_bps_per_side": r["name_level_trade_weighted_cost_bps_per_side"],
        "name_level_cost_decomposition": r["name_level_cost_decomposition"],
        "segments": segs,
        "monthly_metric": ("net (20 bps) long-short return per tranche" if is_ls else
                          f"net (20 bps) {H}-session tranche return minus the EW benchmark's") + ", mean by signal month",
        "monthly_net_20bps": {k: float(v) for k, v in mon.items()},
        "months_positive": int((mon > 0).sum()), "n_months": int(len(mon)),
        "share_months_positive": float((mon > 0).mean()),
        "cv_months_positive": int((cvmon > 0).sum()), "n_cv_months": int(len(cvmon)),
        "by_year_per_tranche": by_year, "by_direction_per_tranche": by_dir,
        "by_year_per_20_sessions": {k: v * per20 for k, v in by_year.items()},
        "by_direction_per_20_sessions": {k: v * per20 for k, v in by_dir.items()},
    }


# --------------------------------------------------------------------------- pass marks
def boot_mean_ci(d: np.ndarray, draws: np.ndarray) -> list[float]:
    m = d[draws].mean(1)
    return [float(np.percentile(m, 2.5)), float(np.percentile(m, 97.5))]


def pass_marks(books: dict, matched: dict) -> dict:
    c20 = lambda k: books[k]["segments"]["combined"]["20bps"]          # noqa: E731
    out = {}
    # ---- B1
    cand = {}
    for sc in ("nested_lgbm", "all51"):
        k = f"{sc}|vol+size|top_decile|H20"
        x = c20(k)
        ok = bool(x["excess_ann_vs_ew"] > 0 and x["ir"] >= 0.5 and x["ir_ci95"][0] > 0)
        cand[k] = {"excess_ann_vs_ew_20bps": x["excess_ann_vs_ew"], "ir": x["ir"], "ir_ci95": x["ir_ci95"],
                   "beats_ew": bool(x["excess_ann_vs_ew"] > 0), "ir_ge_0_5": bool(x["ir"] >= 0.5),
                   "ir_ci_excludes_0": bool(x["ir_ci95"][0] > 0), "pass": ok}
    out["B1"] = {"rule": "for nested_lgbm or all51, the vol+size top decile beats the EW universe net of 20 bps, with "
                         "the IR's 95% month-block CI excluding zero and IR >= 0.5 (either scorer suffices)",
                 "books": cand, "pass": any(v["pass"] for v in cand.values())}
    # ---- B2
    months = sorted(next(iter(books.values()))["monthly_net_20bps"])
    draws = np.random.default_rng(SEED).integers(0, len(months), size=(sb.N_BOOT, len(months)))
    pairs = {}
    for sc in SCORERS:
        for nt in NEUTS:
            kp, kb = f"{sc}|{nt}|top_decile|H20", f"{sc}|{nt}|buffered_decile|H20"
            tp, tb = books[kp]["turnover_per_rebalance"], books[kb]["turnover_per_rebalance"]
            mp_, mb = books[kp]["monthly_net_20bps"], books[kb]["monthly_net_20bps"]
            d = np.array([mb[m] - mp_[m] for m in months])
            ci = boot_mean_ci(d, draws)
            sd = float(d.std(ddof=1))
            cut = 1.0 - tb / tp
            pairs[f"{sc}|{nt}"] = {
                "plain": kp, "buffered": kb, "turnover_plain": tp, "turnover_buffered": tb, "turnover_cut": cut,
                "cut_ge_30pct": bool(cut >= 0.30),
                "excess_ann_plain_20bps": c20(kp)["excess_ann_vs_ew"], "excess_ann_buffered_20bps": c20(kb)["excess_ann_vs_ew"],
                "ir_plain": c20(kp)["ir"], "ir_buffered": c20(kb)["ir"],
                "monthly_diff_mean_20d": float(d.mean()), "monthly_diff_ann": float(d.mean() * sb.PPY / sb.HORIZON),
                "monthly_diff_ci95_month_bootstrap": ci,
                "monthly_diff_ci95_ann": [x * sb.PPY / sb.HORIZON for x in ci],
                "monthly_diff_ci95_t": [float(d.mean() - 2.0154 * sd / math.sqrt(len(d))),
                                        float(d.mean() + 2.0154 * sd / math.sqrt(len(d)))],
                "months_buffered_ahead": f"{int((d > 0).sum())}/{len(d)}",
                "not_lower": bool(ci[1] >= 0), "pass": bool(cut >= 0.30 and ci[1] >= 0)}
    n_ok = sum(v["pass"] for v in pairs.values())
    out["B2"] = {"rule": "buffered decile vs plain decile, same scorer and neutralisation: turnover per rebalance cut "
                         ">= 30% and the paired monthly net (20 bps) excess difference's 95% CI not entirely below "
                         "zero. Scored for each of the 12 scorer x neutralisation pairs; the construction passes when "
                         "every pair passes (aggregation fixed before results; per-pair verdicts below).",
                 "ci_method": f"mean of the 45 signal-month differences, months resampled with replacement, "
                              f"B={sb.N_BOOT}, seed {SEED}, identical draws for every pair; t-interval also shown",
                 "pairs": pairs, "n_pairs_pass": n_ok, "n_pairs": len(pairs), "pass": bool(n_ok == len(pairs))}
    # ---- B3
    b3 = {}
    for sc in SCORERS:
        k40, k20 = f"{sc}|vol+size|top_decile|H40", f"{sc}|vol+size|top_decile|H20"
        e40, e20 = c20(k40)["excess_ann_vs_ew"], c20(k20)["excess_ann_vs_ew"]
        ta40, ta20 = books[k40]["turnover_annualised"], books[k20]["turnover_annualised"]
        diff = e40 - e20
        b3[sc] = {"book_40": k40, "book_20": k20, "excess_ann_40_20bps": e40, "excess_ann_20_20bps": e20,
                  "diff_pp": 100 * diff, "within_1pp": bool(abs(diff) <= 0.01),
                  "not_worse_by_more_than_1pp": bool(diff >= -0.01),
                  "turnover_per_rebalance_40": books[k40]["turnover_per_rebalance"],
                  "turnover_per_rebalance_20": books[k20]["turnover_per_rebalance"],
                  "turnover_annualised_40": ta40, "turnover_annualised_20": ta20,
                  "turnover_ratio_annualised": ta40 / ta20, "turnover_at_most_half": bool(ta40 <= 0.5 * ta20),
                  "pass": bool(abs(diff) <= 0.01 and ta40 <= 0.5 * ta20),
                  "robustness_same_signal_dates": matched[sc]}
    out["B3"] = {"rule": "40-session vol+size top decile vs the 20-session one, same scorer: annual net (20 bps) excess "
                         "within 1 pp (|difference| <= 1 pp, read literally) and turnover at most half. Turnover is "
                         "compared per unit of time (per-rebalance turnover x 252/H): a 40-session tranche is replaced "
                         "half as often, so per-rebalance fractions are not comparable across H. The construction "
                         "passes when all three scorers pass (aggregation fixed before results).",
                 "scorers": b3, "n_pass": sum(v["pass"] for v in b3.values()),
                 "pass": bool(all(v["pass"] for v in b3.values()))}
    # ---- gates 3 and 5 for B1 passers (and, for information, the two B1 candidates either way)
    g = {}
    for k in cand:
        sc = k.split("|")[0]
        liq = f"{sc}|vol+size|liq_buffered_decile|H20"
        b = books[k]
        g[k] = {"b1_pass": cand[k]["pass"], "scored_because": "passes B1" if cand[k]["pass"] else
                "information only (B1 failed, so the gates are not re-scored formally)",
                "gate3": {"rule": "top decile beats the EW universe in >= 75% of months, net 20 bps",
                          "months": f"{b['months_positive']}/{b['n_months']}", "share": b["share_months_positive"],
                          "pass": bool(b["share_months_positive"] >= 0.75)},
                "gate5": {"rule": f"DSR >= 0.95 on the liquid book at N = {N_PHASE}", "liquid_book": liq,
                          "dsr": books[liq]["dsr"][str(N_PHASE)]["dsr"],
                          "dsr_at_239": books[liq]["dsr"][str(N_AMENDED)]["dsr"],
                          "pass": bool(books[liq]["dsr"][str(N_PHASE)]["dsr"] >= 0.95)},
                "own_dsr_238": b["dsr"][str(N_PHASE)]["dsr"]}
    out["gates_for_B1"] = g
    out["any_book_passes_B1_and_gates_3_and_5"] = bool(any(v["b1_pass"] and v["gate3"]["pass"] and v["gate5"]["pass"]
                                                          for v in g.values()))
    return out


# --------------------------------------------------------------------------- main
def main() -> None:
    global _LOG
    OUT.mkdir(parents=True, exist_ok=True)
    _LOG = OUT / "log.txt"
    with open(_LOG, "a") as fh:
        fh.write(f"\n===== run started {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    splits = D.load_splits()
    base = D.load_base(splits)
    scores, smeta = D.load_scores(base, RP.PORT_SCORERS)
    log(f"base panel: {len(base):,} rows, {base['date'].nunique()} signal dates, scorers {list(scores)}")
    raw = D.read_price_parquet()
    sessions, tick, O, adv20 = D.load_prices(base, raw)
    blocks, check = sb.build_blocks(base, sessions, tick, O, adv20)
    log(f"prices from {D.PRICES_PARQUET.name}: {len(sessions)} sessions x {len(tick)} tickers; {len(blocks)} blocks; "
        f"exit-mark/label match {check['exit_mark_matches_label_frac']:.6f}")

    # ---------------- 1. acceptance test
    eng0 = sb.Engine(blocks, sessions, len(tick), sb.HORIZON)
    rep, skill_rep = RP.replica_portfolio(eng0, blocks, scores, len(tick), check)
    frozen = RP.load_frozen()
    cmp = RP.compare(rep, frozen)
    heads = RP.headline_checks(rep, frozen)
    repro = {"what": "the 24 five-year books of ml/scale5y_report.py portfolio() rebuilt with prices from "
                     "ml/results/improve/cache/features_prices_export_v1.parquet (DuckDB not opened) and compared with "
                     "every number in ml/results/scale5y/portfolio_5y.json",
             "price_source": str(D.PRICES_PARQUET.relative_to(ML_DIR.parent)),
             "base_panel": {"rows": int(len(base)), "signal_dates": int(base["date"].nunique()),
                            "first": str(base["date"].min().date()), "last": str(base["date"].max().date())},
             "comparison": cmp, "headline_numbers": heads,
             "verdict": "PASS: reproduces portfolio_5y.json to 3 decimals" if cmp["matches_to_3_decimals"] else
                        "FAIL: does not reproduce; variants not run"}
    wjson(OUT / "reproduction_check.json", repro)
    log(f"acceptance test: {cmp['numeric_leaves_compared']} numeric leaves, max abs diff {cmp['max_abs_diff']:.3g}, "
        f"max rel diff {cmp['max_rel_diff']:.3g} -> {repro['verdict']}")
    if not cmp["matches_to_3_decimals"]:
        raise SystemExit("reproduction failed; see reproduction_check.json")
    month_of0 = np.array([b.month for b in blocks])
    ew_R0 = eng0.bench["ew_universe"]["R"]
    direction = {mo: ("up" if ew_R0[month_of0 == mo].mean() > 0 else "down") for mo in sorted(set(month_of0))}
    del eng0

    # ---------------- 2. inputs of the grid
    comp = D.cost_components(raw, sessions, tick, adv20)
    log(f"name-level cost components ready (missing before fill: spread {comp['fill']['spread_nan_before_fill']:.3f}, "
        f"sigma {comp['fill']['sigma_nan_before_fill']:.3f} of the session x ticker grid)")
    pos_b = base["date"].map({d: i for i, d in enumerate(sessions)}).to_numpy()
    col_b = base["ticker"].map({t: j for j, t in enumerate(tick)}).to_numpy()
    hs_b, adv_b = 1e4 * comp["half_spread"][pos_b, col_b], comp["adv"][pos_b, col_b] / 1e7
    edges = [0, 2, 5, 10, 25, 50, 100, 250, 500, np.inf]
    bk_ = np.digitize(adv_b, edges[1:-1])
    cost_diag = {
        "what": "Corwin-Schultz half-spread (bps, 60-session median, floored at 0) on universe rows, by ADV20 bucket "
                "(Rs crore) and for the most traded names",
        "half_spread_bps_median_by_adv_bucket": {
            f"{edges[i]}-{edges[i + 1]}": {"rows": int((bk_ == i).sum()), "median": float(np.median(hs_b[bk_ == i]))}
            for i in range(len(edges) - 1) if (bk_ == i).any()},
        "large_caps": {t: {"median_half_spread_bps": float(np.median(hs_b[base["ticker"].to_numpy() == t])),
                           "median_adv20_rs_crore": float(np.median(adv_b[base["ticker"].to_numpy() == t]))}
                       for t in ("RELIANCE", "HDFCBANK", "INFY", "TCS") if (base["ticker"].to_numpy() == t).any()},
        "share_negative_two_day_estimates": float(np.nanmean(D.corwin_schultz_2day(comp["own"]) < 0)),
        "fill": comp["fill"]}
    mp, prov = D.industry_map(log)
    ind_codes, ind_cov = E.industry_groups(base, mp)
    log(f"industry map: {prov['n_symbols']} symbols, {prov['n_industries']} industries; {ind_cov}")
    dates = np.unique(base["date"].to_numpy())
    codes = np.searchsorted(dates, base["date"].to_numpy())
    atr = base["atr_pct"].to_numpy(float)
    lt = base["log_turnover"].to_numpy(float)
    nsc = {(sc, nt): E.neutralise(scores[sc], nt, codes, atr, lt, ind_codes) for sc in SCORERS for nt in NEUTS}
    expo = {f"{sc}|{nt}": {"atr_pct": per_date_spearman(codes, nsc[(sc, nt)], atr),
                           "log_turnover": per_date_spearman(codes, nsc[(sc, nt)], lt),
                           "raw_score": per_date_spearman(codes, nsc[(sc, nt)], scores[sc])}
            for sc in SCORERS for nt in NEUTS}
    log("neutralised scores ready; mean per-date Spearman with atr_pct: " +
        ", ".join(f"{k} {v['atr_pct']:+.2f}" for k, v in expo.items()))

    # ---------------- 3. 20-session books
    eng = E.BookEngine(blocks, sessions, len(tick), sb.HORIZON, comp)
    books, skill, expo_e, tr_ex = {}, {}, {}, {}
    extra = {}

    def run(key, eng_, mem, basket, meta):
        r = eng_.run_members(mem, basket)
        books[key] = summarize(key, r, eng_, meta, direction)
        if not basket.endswith("ls_decile"):
            tr_ex[key] = (r["_tranche"]["20bps"]["R"] - r["_bench_R"], np.array([b.date for b in eng_.blocks]))
        skill[key] = r["_skill_daily"]
        expo_e[key] = eng_.cal.expo["combined"]
        c = books[key]["segments"]["combined"]
        if basket.endswith("ls_decile"):
            log(f"{key}: L-S net {c['20bps']['ann_return']:+.4f}/yr Sharpe {c['20bps']['sharpe']:+.2f}, name-level "
                f"{c[E.NAME_KEY]['ann_return']:+.4f}; turnover {r['turnover_per_rebalance']:.3f}")
        else:
            log(f"{key}: excess {c['20bps']['excess_ann_vs_ew']:+.4f}/yr IR {c['20bps']['ir']:+.2f} "
                f"[{c['20bps']['ir_ci95'][0]:+.2f}, {c['20bps']['ir_ci95'][1]:+.2f}], name-level "
                f"{c[E.NAME_KEY]['excess_ann_vs_ew']:+.4f}; turnover {r['turnover_per_rebalance']:.3f}; names "
                f"{r['basket_size_mean']:.0f}")
        return r

    for sc in RP.PORT_SCORERS:
        for bk in RP.BASKETS:
            key = f"{sc}|{bk}"
            run(key, eng, E.members_simple(blocks, scores[sc], bk), bk,
                {"origin": "scale5y_reproduced", "trial_group": "five-year grid (in N = 177)", "scorer": sc,
                 "neutralisation": "none", "basket": bk})
    # cross-check: the new runner gives the frozen numbers for the 24 books
    xc = 0.0
    for k, fb in frozen["books"].items():
        nb = books[k]
        ref = fb["segments"]["combined"]["20bps"]
        new = nb["segments"]["combined"]["20bps"]
        xc = max(xc, abs(nb["turnover_per_rebalance"] - fb["turnover_per_rebalance"]),
                 abs(new["ann_return"] - ref["ann_return_252_20"]), abs(new["sharpe"] - ref["sharpe"]),
                 float(np.max(np.abs(skill[k] - skill_rep[k]))))
        if "ir" in ref:
            xc = max(xc, abs(new["excess_ann_vs_ew"] - ref["excess_ann_vs_ew_252_20"]), abs(new["ir"] - ref["ir"]),
                     abs(new["ir_ci95"][0] - ref["ir_ci95"][0]))
    log(f"runner cross-check vs portfolio_5y.json on the 24 books: max abs diff {xc:.3g}")
    assert xc < 1e-12, "book runner disagrees with the engine"
    for sc in SCORERS:
        for nt in NEUTS:
            for bk in P2_BASKETS:
                key = f"{sc}|{nt}|{bk}|H20"
                if bk == "buffered_decile":
                    mem, bi = E.members_buffered(blocks, nsc[(sc, nt)], liq_only=False, H=sb.HORIZON)
                    extra[key] = bi
                else:
                    mem = E.members_simple(blocks, nsc[(sc, nt)], bk)
                run(key, eng, mem, bk, {"origin": "p2_grid", "trial_group": "S x N x B (36)", "scorer": sc,
                                        "neutralisation": nt, "basket": bk})
                if key in extra:
                    books[key]["buffer_diagnostics"] = extra[key]
    for sc in SCORERS:
        key = f"{sc}|vol+size|liq_buffered_decile|H20"
        mem, bi = E.members_buffered(blocks, nsc[(sc, "vol+size")], liq_only=True, H=sb.HORIZON)
        run(key, eng, mem, "liq_buffered_decile", {"origin": "p2_grid", "trial_group": "liquid buffered (3)",
                                                    "scorer": sc, "neutralisation": "vol+size",
                                                    "basket": "liq_buffered_decile"})
        books[key]["buffer_diagnostics"] = bi

    # ---------------- 4. 40-session books
    pos_of = {d: i for i, d in enumerate(sessions)}
    col_of = {t: j for j, t in enumerate(tick)}
    p = base["date"].map(pos_of).to_numpy()
    cidx = base["ticker"].map(col_of).to_numpy()
    fmax = D.forward_absret_max(comp["own"], sessions, tick, H_LONG + 1)[p, cidx]
    elig = p + 1 + H_LONG <= len(sessions) - 1
    clean40 = elig & (fmax <= D.SPLIT_MOVE_THRESHOLD)
    sub = base[clean40]
    blocks40, info40 = E.build_blocks_h(sub, sessions, tick, O, adv20, H_LONG)
    # artefact the screen removes: EW mean 40-session return with and without the screened rows (tranche level)
    Of = O.ffill().to_numpy(float)
    Ob = O.bfill().to_numpy(float)
    e0 = np.where(np.isfinite(O.to_numpy(float)[p + 1, cidx]), O.to_numpy(float)[p + 1, cidx], Ob[p + 1, cidx])
    pe = np.minimum(p + 1 + H_LONG, len(sessions) - 1)
    r40 = Of[pe, cidx] / e0 - 1.0
    screen = {"rule": "a base row (already y_clean_20d) enters the 40-session universe only if its ticker's |ret_1d| "
                      "stays <= 22% over sessions t+1..t+41 -- ml/data.py's y_clean_20d split/circuit screen extended "
                      "to the 40-session window (prices are unadjusted; an unscreened split would book a fake loss)",
              "eligible_rows": int(elig.sum()), "rows_removed": int((elig & ~clean40).sum()),
              "share_removed": float((elig & ~clean40).sum() / elig.sum()),
              "ew_mean_40d_return_kept": float(np.nanmean(r40[clean40])),
              "ew_mean_40d_return_all_eligible": float(np.nanmean(r40[elig])),
              "ew_mean_40d_return_removed_rows": float(np.nanmean(r40[elig & ~clean40])), **info40}
    log(f"40-session blocks: {info40['signal_dates']} signal dates {info40['first']}..{info40['last']}, screen removed "
        f"{screen['rows_removed']:,} rows ({100 * screen['share_removed']:.2f}%)")
    eng40 = E.BookEngine(blocks40, sessions, len(tick), H_LONG, comp)
    for sc in SCORERS:
        key = f"{sc}|vol+size|top_decile|H40"
        run(key, eng40, E.members_simple(blocks40, nsc[(sc, "vol+size")], "top_decile"), "top_decile",
            {"origin": "p2_grid", "trial_group": "40-session hold (3)", "scorer": sc, "neutralisation": "vol+size",
             "basket": "top_decile"})
    month40 = np.array([b.month for b in blocks40])
    bench40 = {"turnover_per_rebalance": eng40.bench["ew_universe"]["turnover"],
               "names_mean": float(eng40.bench["ew_universe"]["size"].mean()),
               "ann_return": float(eng40.bench["ew_universe"]["R"].mean() * sb.PPY / H_LONG),
               "n_months": int(len(set(month40)))}

    # ---------------- 5. PSR / DSR over all 66 books
    keys = list(books)
    assert len(keys) == 66, len(keys)
    sr = {k: sb.wmoments(skill[k], expo_e[k])[0] / sb.wmoments(skill[k], expo_e[k])[1] for k in keys}
    var_sr = float(np.var(list(sr.values()), ddof=1))
    var_sr_5y = rep["dsr"]["var_sr_skill_daily"]
    for k in keys:
        books[k]["dsr"] = {str(N): sb.dsr_block(skill[k], expo_e[k], var_sr, N, f"{k} skill", sb.PPY) for N in N_LIST}
        books[k]["psr_vs_0"] = books[k]["dsr"][str(N_PHASE)]["psr_vs_0"]
        books[k]["sr_daily_annualised"] = sr[k] * math.sqrt(sb.PPY)
        books[k]["dsr_sensitivity_var_sr_of_the_24_five_year_books"] = {
            str(N): sb.dsr_block(skill[k], expo_e[k], var_sr_5y, N, f"{k} skill", sb.PPY)["dsr"] for N in (N_5Y, N_PHASE)}
    log(f"DSR: V[SR] across 66 books {var_sr:.6g}; SR0 at N=238 {books[keys[0]]['dsr'][str(N_PHASE)]['sr0_expected_max_annualised']:.2f}/yr")

    # ---------------- 6. pass marks and outputs
    last40 = blocks40[-1].date
    matched = {}
    for sc in SCORERS:
        k20, k40 = f"{sc}|vol+size|top_decile|H20", f"{sc}|vol+size|top_decile|H40"
        ex20, d20 = tr_ex[k20]
        mk = d20 <= last40
        matched[sc] = {"signal_dates_common": int(mk.sum()), "last_common_signal_date": str(last40.date()),
                       "excess_ann_20_on_common_dates": float(ex20[mk].mean() * sb.PPY / sb.HORIZON),
                       "excess_ann_40": float(tr_ex[k40][0].mean() * sb.PPY / H_LONG)}
        matched[sc]["diff_pp_common_dates"] = 100 * (matched[sc]["excess_ann_40"] - matched[sc]["excess_ann_20_on_common_dates"])
    pm = pass_marks(books, matched)
    for b in ("B1", "B2", "B3"):
        log(f"{b}: {'PASS' if pm[b]['pass'] else 'FAIL'}")
    ranked = sorted([k for k in keys if not books[k]["basket"].endswith("ls_decile")],
                    key=lambda k: -books[k]["segments"]["combined"]["20bps"]["ir"])
    months_all = sorted(set(month_of0))
    pnl_months = {}
    for k in keys:
        cal = (eng40 if books[k]["H"] == H_LONG else eng).cal
        x = skill[k] * expo_e[k]
        mo = cal.day_dates[cal.cols["combined"]].strftime("%Y-%m")
        pnl_months[k] = pd.Series(x).groupby(mo).sum().to_dict()
    pm_all = sorted(set().union(*[set(v) for v in pnl_months.values()]))
    monthly = {
        "what": "per-signal-month net (20 bps) excess of every book (long-only: tranche net return minus the EW "
                "benchmark's; long-short: net L-S return), mean over the month's signal dates; for the lead's "
                "probability-of-backtest-overfitting test",
        "months": months_all,
        "books": {k: [books[k]["monthly_net_20bps"].get(m) for m in months_all] for k in keys},
        "H": {k: books[k]["H"] for k in keys},
        "per_20_sessions_scale": {k: sb.HORIZON / books[k]["H"] for k in keys},
        "note": "values are per H-session tranche; multiply by per_20_sessions_scale to put the 40-session books on "
                "the 20-session scale; null = no signal date of that book in the month (40-session books end "
                "2026-08-18)",
        "pnl_calendar_months": pm_all,
        "pnl_month_active_return": {k: [pnl_months[k].get(m) for m in pm_all] for k in keys},
        "pnl_note": "sum over the calendar month's sessions of exposure x daily net (20 bps) skill return (the fixed-"
                    "capital program's monthly active return), identical units for every H",
    }
    payload = {
        "generated_by": "python3 -m ml.books.construct (seed 108, OMP_NUM_THREADS=2, single process)",
        "plan": "ml/IMPROVEMENT_PLAN.md stream P2 (fixed grid of 42 trials; pass marks B1-B3)",
        "inputs": {"scores": smeta, "prices": str(D.PRICES_PARQUET.relative_to(ML_DIR.parent)),
                   "dataset": "ml/data_5y/model_dataset.parquet (v1, frozen)",
                   "industry_map": prov, "industry_coverage": ind_cov},
        "reproduction": {"verdict": repro["verdict"], "max_abs_diff": cmp["max_abs_diff"],
                         "max_rel_diff": cmp["max_rel_diff"], "numeric_leaves": cmp["numeric_leaves_compared"],
                         "runner_cross_check_max_abs_diff": xc, "file": "reproduction_check.json"},
        "definitions": {
            "neutralisation": "per signal date on that date's clean universe rows: percentile rank of the score; vol = "
                              "OLS residual on the percentile rank of atr_pct (missing atr_pct -> rank 0.5); vol+size = "
                              "on the ranks of atr_pct and log_turnover; vol+size+industry = score rank first demeaned "
                              "within NSE industry (industries with < 5 names that date -> 'Unclassified'), then the "
                              "vol+size OLS; residual re-ranked to a percentile = the new score; none = raw score",
            "baskets": {"top_decile": "engine rule: top max(1, round(10% x n)) by score, ticker as tie-break, equal "
                                      "weight", "top_quintile": "top max(1, round(20% x n)), equal weight",
                        "buffered_decile": "tranche k inherits the names of tranche k-20 still in today's top 20%, "
                                           "fills to today's decile size with the best-ranked names not held, equal "
                                           "weight; first 20 tranches plain deciles",
                        "liq_buffered_decile": "the same inside the liquid tercile (cs_rank_turnover >= 0.67), scored "
                                               "with the full-universe vol+size score; benchmark EW liquid tercile",
                        "H40": "vol+size top decile, entry open t+1, exit open t+41 (no label pin), its own H = 40 EW "
                               "universe leg as benchmark; signal dates without a t+41 session dropped"},
            "costs": {"flat": "10/20/40 bps per side, netted against the tranche replaced (engine)",
                      "name_level": "per side per name max(11 bps, 0.5 x Corwin-Schultz spread (two-day estimator "
                                    "with the paper's overnight adjustment, 60-session rolling median, floored at 0) + "
                                    "0.1 x sigma_20d x sqrt(q / ADV20)), q = Rs 100 crore / basket size; charged on "
                                    "each name's traded fraction (entry vs tranche k-H, exit vs tranche k+H; costs "
                                    "dated at the trade's signal date); ends imputed with the steady-state median",
                      "breakeven": "flat per-side cost at which the mean tranche net excess vs the benchmark is zero "
                                   "(long-short: net L-S return zero)"},
            "annualisation": "excess_ann_vs_ew / ann_return = mean tranche value x 252/H (the program's headline); "
                             "IR = exposure-weighted daily active Sharpe x sqrt(252) with month-block bootstrap CI "
                             "(B = 1000, seed 108); turnover_annualised = per-rebalance turnover x 252/H",
            "dsr": "ml/strategy_backtest.py dsr_block on the combined daily net (20 bps) skill series (exposure-"
                   "weighted moments, T = Kish n_eff), V[SR] across all 66 books, N = 177 / 238 / 239",
        },
        "trial_ledger": TRIAL_LEDGER,
        "dsr_common": {"var_sr_daily_across_66_books": var_sr, "var_sr_daily_of_the_24_five_year_books": var_sr_5y,
                       "sensitivity_note": "dsr_sensitivity_var_sr_of_the_24_five_year_books is NOT the pre-registered "
                                           "statistic: it shows how much of the deflation comes from V[SR] (which "
                                           "doubles once the 42 new books join the trial set) rather than from N",
                       "sr0_expected_max_annualised": {str(N): books[keys[0]]["dsr"][str(N)]["sr0_expected_max_annualised"]
                                                       for N in N_LIST}},
        "direction_by_month": direction,
        "benchmarks": {"H20": {"ew_universe_ann_return": rep["benchmarks"]["ew_universe"]["combined"]["tranche"][
            "ann_return_252_h"], "ew_liquid_ann_return": rep["benchmarks"]["ew_liquid"]["combined"]["tranche"][
            "ann_return_252_h"]}, "H40_ew_universe": bench40},
        "hold40_universe_screen": screen,
        "cost_model_diagnostics": cost_diag,
        "score_exposures_mean_per_date_spearman": expo,
        "pass_marks": pm,
        "ranking_by_ir_20bps": [{"book": k, "ir": books[k]["segments"]["combined"]["20bps"]["ir"],
                                 "excess_ann_vs_ew_20bps": books[k]["segments"]["combined"]["20bps"]["excess_ann_vs_ew"],
                                 "turnover_per_rebalance": books[k]["turnover_per_rebalance"],
                                 "dsr_238": books[k]["dsr"][str(N_PHASE)]["dsr"]} for k in ranked],
        "books": books,
    }
    payload = sb.clean_json(payload)
    wjson(OUT / "books.json", payload)
    wjson(OUT / "monthly_series.json", monthly)
    write_markdown(payload, sb.clean_json(repro), OUT / "BOOKS.md")
    log(f"wrote books.json ({len(keys)} books), monthly_series.json, BOOKS.md; "
        f"runtime {time.time() - T0:.0f}s")


if __name__ == "__main__":
    main()
