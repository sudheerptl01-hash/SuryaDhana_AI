"""Acceptance test: rebuild the 24 five-year books of ml/scale5y_report.py portfolio() from the parquet prices and
compare every number with the frozen ml/results/scale5y/portfolio_5y.json.

The replica below is portfolio() line for line (same engine import, same scorers, baskets, costs, DSR trial
constants); only the price source differs (parquet export of the equity_features rows instead of the DuckDB).
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

import ml.strategy_backtest as sb
from ml.books.data import SCALE5Y

ENS = "nested_ensemble_rank"
HEUR = "heuristic_mom20"
PORT_SCORERS = ["nested_lgbm", "all51", ENS, "champion10", "lr_l2", "nested_lr_l2", "baseline_mom", HEUR]
BASKETS = ("top_decile", "ls_decile", "liq_top_decile")
COST_KEY = "20bps"
# scale5y_report.py trial constants (fixed there before any portfolio number existed)
TRIALS = {"5y_model_configs": 10, "5y_portfolio_books": 24, "pilot_configs_audit_T7_77": 77,
          "pilot_portfolio_cells_STRATEGY_md": 66}
N_HEADLINE = 177
N_SENSITIVITY = {"5y_only": 34, "headline": 177, "conservative_incl_univariate_screens": 251}


def replica_portfolio(eng: sb.Engine, blocks, scores: dict, n_tick: int, check: dict) -> tuple[dict, dict]:
    """portfolio() of ml/scale5y_report.py on an already built engine. Returns (portfolio dict, skill series)."""
    H = sb.HORIZON
    cal = eng.cal
    EX = cal.expo["combined"]
    month_of = np.array([b.month for b in blocks])
    ew_R = eng.bench["ew_universe"]["R"]
    direction = {mo: ("up" if ew_R[month_of == mo].mean() > 0 else "down") for mo in sorted(set(month_of))}
    up_mask = np.array([direction[mo] == "up" for mo in month_of])
    bench = {}
    for name, bd in eng.bench.items():
        bench[name] = {"turnover_per_rebalance": bd["turnover"], "names_mean": float(bd["size"].mean())}
        for seg in sb.SEGMENTS:
            mk = cal.masks[seg]
            x = cal.seg_series(bd["D"], seg)
            bench[name][seg] = {"tranche": sb.tranche_stats(bd["R"][mk], bd["R"][mk], eng.med[mk], H=H),
                                "daily": sb.series_stats(x, cal.expo[seg], cal.month_codes[seg], cal.draws[seg],
                                                         rf=sb.RF_ANNUAL)}
    c20 = int(COST_KEY.replace("bps", "")) / 1e4
    books, skill, raw = {}, {}, {}
    scorers = [s_ for s_ in PORT_SCORERS if s_ in scores and np.isfinite(scores[s_]).all()]
    for sc in scorers:
        for bk in BASKETS:
            r = eng.run(scores[sc], bk)
            is_ls = bk.endswith("ls_decile")
            res = r["results"]
            segs = {}
            for seg in sb.SEGMENTS:
                e = {}
                for ck in ("gross", "10bps", "20bps", "40bps", "20bps_no_netting"):
                    t, dl = res[ck][seg]["tranche"], res[ck][seg]["daily"]
                    row = {"ann_return_252_20": t["ann_return_252_h"], "sharpe": dl["sharpe"],
                           "sharpe_ci95": dl["sharpe_ci95"], "p_sharpe_gt0": dl["p_sharpe_gt0"],
                           "ann_vol": dl["ann_vol"], "max_dd": dl["max_dd"]}
                    if is_ls:
                        row["hit_net_positive_tranches"] = t["hit_rate_net_positive"]
                    else:
                        da = res[ck][seg]["daily_active"]
                        ba = res[ck][seg]["beta_alpha_vs_benchmark"]
                        row.update({"excess_ann_vs_ew_252_20": t["active_ann_252_h"],
                                    "excess_ann_vs_ew_daily": da["ann_mean_daily"], "ir": da["sharpe"],
                                    "ir_ci95": da["sharpe_ci95"], "excess_max_dd": da["max_dd"],
                                    "hit_vs_ew_tranches": t["hit_rate_vs_ew"],
                                    "beta_vs_bench": ba["beta_vs_benchmark"], "alpha_ann_vs_bench": ba["alpha_ann"]})
                    e[ck] = row
                segs[seg] = e
            R = r["_tranche"][COST_KEY]["R"]
            val = R if is_ls else R - eng.bench[eng.bench_for(bk)]["R"]
            mon = pd.Series(val).groupby(month_of).mean()
            cvmon = mon[[mo for mo in mon.index if mo < "2026-08"]]
            ent = {"benchmark": None if is_ls else eng.bench_for(bk), "basket_size_mean": r["basket_size_mean"],
                   "turnover_per_rebalance": r["turnover_per_rebalance"],
                   "turnover_per_rebalance_short": r.get("turnover_per_rebalance_short"),
                   "capacity": r["capacity"], "segments": segs,
                   "monthly_20bps": {k: float(v) for k, v in mon.items()},
                   "months_positive": int((mon > 0).sum()), "n_months": int(len(mon)),
                   "share_months_positive": float((mon > 0).mean()),
                   "cv_months_positive": int((cvmon > 0).sum()), "n_cv_months": int(len(cvmon)),
                   "share_cv_months_positive": float((cvmon > 0).mean()),
                   "by_direction_20d": {"up": float(val[up_mask].mean()), "down": float(val[~up_mask].mean())},
                   "by_year_20d": {yy: float(val[np.char.startswith(month_of.astype(str), yy)].mean())
                                   for yy in ("2023", "2024", "2025", "2026")}}
            Lp, Wl, _ = sb.leg(blocks, [x[0] for x in r["_mem"]], n_tick, H)
            tl = sb.trade_fracs(Wl, H)
            if is_ls:
                Sp, Ws, _ = sb.leg(blocks, [x[1] for x in r["_mem"]], n_tick, H)
                rr, _ = sb.ls_net(Lp, Sp, tl, sb.trade_fracs(Ws, H), c20)
                skill[(sc, bk)] = cal.seg_series(cal.to_days(rr), "combined")
            else:
                rr, _ = sb.long_net(Lp, tl["buy"], tl["sell"], c20)
                x = cal.seg_series(cal.to_days(rr), "combined")
                xb = cal.seg_series(eng.bench[eng.bench_for(bk)]["D"], "combined")
                skill[(sc, bk)] = x - xb
                raw[(sc, bk)] = x - sb.RF_ANNUAL / sb.PPY
            books[f"{sc}|{bk}"] = ent
            del r
    keys = list(skill)
    assert len(keys) == TRIALS["5y_portfolio_books"], f"grid has {len(keys)} books"
    sr = {k: sb.wmoments(skill[k], EX)[0] / sb.wmoments(skill[k], EX)[1] for k in keys}
    srr = {k: sb.wmoments(raw[k], EX)[0] / sb.wmoments(raw[k], EX)[1] for k in raw}
    var_sr = float(np.var(list(sr.values()), ddof=1))
    var_srr = float(np.var(list(srr.values()), ddof=1))
    dsr = {"trials": TRIALS, "N_headline": N_HEADLINE, "N_sensitivity": N_SENSITIVITY,
           "var_sr_skill_daily": var_sr, "var_sr_absolute_daily": var_srr, "books": {}}
    for k in keys:
        lab = f"{k[0]}|{k[1]}"
        e = {"skill": {str(N): sb.dsr_block(skill[k], EX, var_sr, N, lab + " skill", sb.PPY)
                       for N in N_SENSITIVITY.values()}}
        if k in raw:
            e["absolute_net_minus_rf"] = {str(N): sb.dsr_block(raw[k], EX, var_srr, N, lab + " abs", sb.PPY)
                                          for N in N_SENSITIVITY.values()}
        dsr["books"][lab] = e
    ew_raw = cal.seg_series(eng.bench["ew_universe"]["D"], "combined") - sb.RF_ANNUAL / sb.PPY
    dsr["ew_universe_absolute_reference"] = sb.dsr_block(ew_raw, EX, var_srr, N_HEADLINE, "ew_universe abs", sb.PPY)
    port = {"n_signal_dates": len(blocks), "path_check": check, "direction_by_month": direction,
            "benchmarks": bench, "books": books, "dsr": dsr, "scorers": scorers, "baskets": list(BASKETS),
            "costs_bps_per_side": [10, 20, 40], "headline_cost": COST_KEY}
    return sb.clean_json(port), {f"{k[0]}|{k[1]}": v for k, v in skill.items()}


SKIP = {"generated_at", "generated_by", "seconds", "engine", "method", "T_note", "series", "monthly_metric"}


def _walk(a, b, path, out):
    if isinstance(b, dict):
        if not isinstance(a, dict):
            out["structure"].append(path)
            return
        for k, v in b.items():
            if k in SKIP:
                continue
            if k not in a:
                out["missing"].append(f"{path}/{k}")
                continue
            _walk(a[k], v, f"{path}/{k}", out)
    elif isinstance(b, list):
        if not isinstance(a, list) or len(a) != len(b):
            out["structure"].append(path)
            return
        for i, (x, y) in enumerate(zip(a, b)):
            _walk(x, y, f"{path}[{i}]", out)
    elif isinstance(b, bool) or isinstance(b, str) or b is None:
        out["n_other"] += 1
        if a != b:
            out["other_mismatch"].append({"path": path, "replica": a, "frozen": b})
    elif isinstance(b, (int, float)):
        if not isinstance(a, (int, float)) or isinstance(a, bool):
            out["structure"].append(path)
            return
        d = abs(float(a) - float(b))
        out["n_numeric"] += 1
        if d > out["max_abs"][0]:
            out["max_abs"] = (d, path, a, b)
        if abs(b) > 1e-6:
            rel = d / abs(b)
            if rel > out["max_rel"][0]:
                out["max_rel"] = (rel, path, a, b)
        if d > 5e-4:
            out["beyond_3_decimals"].append({"path": path, "replica": a, "frozen": b})


def compare(replica: dict, frozen: dict) -> dict:
    out = {"n_numeric": 0, "n_other": 0, "max_abs": (0.0, None, None, None), "max_rel": (0.0, None, None, None),
           "beyond_3_decimals": [], "missing": [], "structure": [], "other_mismatch": []}
    _walk(replica, {k: v for k, v in frozen.items() if k not in SKIP}, "", out)
    ok = not (out["beyond_3_decimals"] or out["missing"] or out["structure"] or out["other_mismatch"])
    return {"numeric_leaves_compared": out["n_numeric"], "other_leaves_compared": out["n_other"],
            "max_abs_diff": out["max_abs"][0], "max_abs_diff_at": out["max_abs"][1],
            "max_rel_diff": out["max_rel"][0], "max_rel_diff_at": out["max_rel"][1],
            "max_rel_diff_note": "relative difference over numeric leaves with |frozen value| > 1e-6",
            "n_beyond_3_decimals": len(out["beyond_3_decimals"]), "beyond_3_decimals": out["beyond_3_decimals"][:50],
            "missing_keys": out["missing"][:50], "structure_mismatches": out["structure"][:50],
            "non_numeric_mismatches": out["other_mismatch"][:50],
            "matches_to_3_decimals": bool(ok)}


def headline_checks(rep: dict, frozen: dict) -> list[dict]:
    """The numbers the lead named, side by side."""
    def g(d, *ks):
        for k in ks:
            d = d[k]
        return d
    B, C = ("books", "nested_ensemble_rank|top_decile", "segments", "combined", "20bps"), ("books", "nested_lgbm|top_decile")
    items = [  # (label, path, value quoted by the lead, half a unit of the quoted precision)
        ("nested_ensemble_rank|top_decile excess vs EW, 20 bps (ann.)", B + ("excess_ann_vs_ew_252_20",), 0.070, 5e-4),
        ("nested_ensemble_rank|top_decile IR", B + ("ir",), 1.26, 5e-3),
        ("nested_ensemble_rank|top_decile IR CI low", B + ("ir_ci95", 0), 0.32, 5e-3),
        ("nested_ensemble_rank|top_decile IR CI high", B + ("ir_ci95", 1), 2.37, 5e-3),
        ("nested_lgbm|top_decile excess vs EW, 20 bps (ann.)",
         C + ("segments", "combined", "20bps", "excess_ann_vs_ew_252_20"), -0.007, 5e-4),
        ("EW universe annual return", ("benchmarks", "ew_universe", "combined", "tranche", "ann_return_252_h"), 0.194,
         5e-4),
        ("signal dates", ("n_signal_dates",), 913, 0.0),
        ("nested_lgbm|top_decile turnover per rebalance", C + ("turnover_per_rebalance",), 0.666, 5e-4),
        ("nested_ensemble_rank|top_decile DSR at N=177 (24-book V[SR])",
         ("dsr", "books", "nested_ensemble_rank|top_decile", "skill", "177", "dsr"), 0.163, 5e-4),
    ]
    out = []
    for lab, ks, quoted, tol in items:
        a, b = g(rep, *ks), g(frozen, *ks)
        out.append({"item": lab, "replica": a, "frozen_portfolio_5y": b, "quoted_by_lead": quoted,
                    "abs_diff_vs_frozen": abs(a - b), "agrees_with_quote": bool(abs(a - quoted) <= tol + 1e-12)})
    return out


def load_frozen() -> dict:
    return json.loads((SCALE5Y / "portfolio_5y.json").read_text())


def isfinite_tree(x) -> bool:
    if isinstance(x, dict):
        return all(isfinite_tree(v) for v in x.values())
    if isinstance(x, list):
        return all(isfinite_tree(v) for v in x)
    if isinstance(x, float):
        return math.isfinite(x)
    return True
