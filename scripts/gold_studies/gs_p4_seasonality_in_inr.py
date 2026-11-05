#!/usr/bin/env python
"""GS-P4 — month-of-year seasonality of gold in rupees (the Indian festival lore). Pre-registered in
reports/gold_program/GS-P4/PLAN.md (read it first; the pass bars there are binding).

    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/gold_studies/gs_p4_seasonality_in_inr.py [--out DIR]

Stored data only, no network: World Bank CMO monthly gold (1971 → 2024) spliced with GC=F month-ends, FRED DEXINUS
(USD/INR, 1973 →), Yahoo INR=X (cross-check) and GOLDBEES.NS (the Indian-listed instrument), all under
reports/gold_program/G-MACRO/data. Monthly log returns; the walk-forward rule learns each year's month set from
completed prior years only.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gold_studies import common as C

STUDY = "GS-P4"
TITLE = "Month-of-year seasonality of gold in rupees"
SCRIPT = "scripts/gold_studies/gs_p4_seasonality_in_inr.py"
LONG_START = "1973-01-31"                # DEXINUS begins Jan 1973 (World Bank gold from 1971 is cut to match)
WB_END = "2024-12-31"                    # the World Bank file ends Dec 2024; GC=F month-ends splice after it
LONG_SPLIT = "1999-12-31"                # halves of the long sample
TRADABLE_START = "2000-09-30"
TRADABLE_SPLIT = "2013-12-31"
MIN_YEARS = 5                            # years of history before the walk-forward month set is used
BEST_K = 6
SEED = 20261026
NULL_SEEDS = 100                         # further shuffles behind the null rates of the negative controls (N4)
VOID_NULL_RATE = 0.10                    # a statistic whose shuffle control "passes" more often than this is void
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
HYPOTHESES = {"H1 festival (Sep/Oct/Nov)": (9, 10, 11), "H1b Akshaya Tritiya (Apr/May)": (4, 5), "H2 Dec/Jan carry-over": (12, 1)}
DEFAULT_OUT = C.GOLD_PROGRAM / "GS-P4"


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Data
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def load_inputs(data_dir: Path | None = None) -> dict[str, pd.Series]:
    """World Bank monthly gold, GC=F daily close, DEXINUS daily, INR=X daily (optional), GOLDBEES daily (optional)."""
    d = data_dir or C.G_MACRO_DATA
    out: dict[str, pd.Series] = {"wb": C.load_worldbank_monthly(d / "worldbank_cmo_monthly.csv"),
                                 "gc": C.load_yahoo_daily(d / "yahoo_GC_F.csv")["close"],
                                 "dexinus": C.load_fred(d / "fred_DEXINUS.csv", "DEXINUS")}
    for key, name in (("inr_x", "yahoo_INR_X.csv"), ("goldbees", "yahoo_GOLDBEES_NS.csv")):
        p = d / name
        if p.exists():
            out[key] = C.load_yahoo_daily(p)["close"]
    return out


def complete_month_ends(daily: pd.Series) -> pd.Series:
    """Month-end closes of a daily series, keeping only months that are complete (the last observation of the month
    is within 4 calendar days of the month end)."""
    s = pd.Series(daily, dtype=float).dropna().sort_index()
    last_obs = s.groupby(s.index.to_period("M")).apply(lambda x: x.index[-1])
    me = s.resample("ME").last()
    ok = [(pd.Timestamp(me_date) - pd.Timestamp(last_obs.get(me_date.to_period("M"), pd.NaT))).days <= 4
          if me_date.to_period("M") in last_obs.index else False for me_date in me.index]
    return me[np.array(ok, dtype=bool)]


def monthly_series(inputs: dict[str, pd.Series]) -> dict[str, pd.Series]:
    """Monthly price levels: long USD (WB average + GC=F splice), long INR, tradable USD/INR (GC=F month-ends),
    the FX rate series used for each, and GOLDBEES month-ends when available."""
    rate_mean = inputs["dexinus"].resample("ME").mean()
    rate_last = complete_month_ends(inputs["dexinus"])
    gc_me = complete_month_ends(inputs["gc"])
    wb = inputs["wb"].loc[LONG_START:WB_END]
    splice = gc_me[gc_me.index > wb.index[-1]]
    long_usd = pd.concat([wb, splice]).sort_index()
    long_fx = pd.concat([rate_mean.reindex(wb.index), rate_last.reindex(splice.index)]).sort_index()
    long_inr = (long_usd * long_fx).dropna()
    trad_usd = gc_me.loc[TRADABLE_START:]
    trad_fx = rate_last.reindex(trad_usd.index).ffill(limit=1)
    trad_inr = (trad_usd * trad_fx).dropna()
    out = {"long_usd": long_usd.reindex(long_inr.index), "long_fx": long_fx.reindex(long_inr.index), "long_inr": long_inr,
           "trad_usd": trad_usd.reindex(trad_inr.index), "trad_fx": trad_fx.reindex(trad_inr.index), "trad_inr": trad_inr}
    if "goldbees" in inputs:
        out["goldbees"] = complete_month_ends(inputs["goldbees"])
    if "inr_x" in inputs:
        out["inr_x_me"] = complete_month_ends(inputs["inr_x"])
    return out


def log_returns(level: pd.Series) -> pd.Series:
    s = pd.Series(level, dtype=float).dropna()
    return (100 * np.log(s).diff()).dropna()


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def _cap(v: str) -> str:
    """PLAN f.1: only a pre-registered statistic can produce a PASS. The drift-adjusted statistic (N4) was adopted after
    the pre-registered one was voided by its own control, so its PASS is reported as CONTEXT-ONLY (`post_hoc_cap`)."""
    return C.CONTEXT_ONLY if v == C.PASS else v


def month_table(ret: pd.Series, split: str, month_labels: pd.Series | None = None) -> list[dict[str, Any]]:
    """Per calendar month, in the full sample and in each half (plain t: non-overlapping monthly returns):

    * `t` — the month's mean against **zero** (the pre-registered statistic; `verdict_pre`). Its shuffle control fails on
      rupee gold (a +1 %/month drift makes random month groupings "pass"), so it is reported but void (PLAN N4);
    * `t_excess` — the month's mean minus the **all-month mean of the same sample / half** (drift-adjusted, the form
      G-STUDY used; `verdict_adj`), and `verdict` = `verdict_adj` capped at CONTEXT-ONLY (`_cap`).

    `month_labels` lets a negative control shuffle the months."""
    r = pd.Series(ret, dtype=float).dropna()
    months = (month_labels.reindex(r.index) if month_labels is not None else pd.Series(r.index.month, index=r.index)).astype(int)
    h1, h2 = C.halves(r.index, split)
    mu, mu1, mu2 = float(r.mean()), float(r[h1].mean()) if h1.any() else float("nan"), float(r[h2].mean()) if h2.any() else float("nan")
    rows = []
    for m in range(1, 13):
        x = r[months == m]
        x1, x2 = r[(months == m) & h1], r[(months == m) & h2]
        t_full, t1, t2 = C.plain_t(x), C.plain_t(x1), C.plain_t(x2)
        e_full, e1, e2 = C.plain_t(x - mu), C.plain_t(x1 - mu1), C.plain_t(x2 - mu2)
        v_adj = C.verdict(e_full, e1, e2)
        rows.append({"month": MONTHS[m - 1], "m": m, "n": len(x), "mean_pct": round(float(x.mean()), 2) if len(x) else float("nan"),
                     "median_pct": round(float(x.median()), 2) if len(x) else float("nan"),
                     "hit_pct": round(float((x > 0).mean() * 100), 0) if len(x) else float("nan"), "t": round(t_full, 2),
                     "sample_mean_pct": round(mu, 2), "excess_pct": round(float(x.mean()) - mu, 2) if len(x) else float("nan"),
                     "t_excess": round(e_full, 2),
                     "h1_mean": round(float(x1.mean()), 2) if len(x1) else float("nan"), "h1_t": round(t1, 2), "h1_t_excess": round(e1, 2),
                     "h1_n": len(x1),
                     "h2_mean": round(float(x2.mean()), 2) if len(x2) else float("nan"), "h2_t": round(t2, 2), "h2_t_excess": round(e2, 2),
                     "h2_n": len(x2),
                     "verdict_pre": C.verdict(t_full, t1, t2), "verdict_adj": v_adj, "verdict": _cap(v_adj), "post_hoc_cap": v_adj == C.PASS})
    return rows


def confirm_with_tradable(long_rows: list[dict[str, Any]], trad_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """PLAN 'Pass criteria', literally: a month PASSes only if the long sample passes (t >= 2, same sign, both halves) AND
    the tradable month-end sample has the same sign — applied to the drift-adjusted excess (N4); a long-sample PASS
    without that agreement is CONTEXT-ONLY. The pre-registered (vs-zero) verdict gets the same check on the raw mean
    (`verdict_pre`). `tradable_*` columns carry the month-end sample's numbers for the report."""
    trad = {r["m"]: r for r in trad_rows}
    out = []
    for r in long_rows:
        row = dict(r)
        tr = trad.get(r["m"], {})
        row["tradable_mean"], row["tradable_t"] = tr.get("mean_pct"), tr.get("t")
        row["tradable_excess_pct"], row["tradable_t_excess"] = tr.get("excess_pct"), tr.get("t_excess")
        row["tradable_verdict"] = tr.get("verdict_adj")          # the month-end sample's own both-halves verdict (drift-adjusted, uncapped)

        def agrees(a: float | None, b: float | None) -> bool:
            return a is not None and b is not None and not (math.isnan(a) or math.isnan(b)) and a != 0 and np.sign(a) == np.sign(b)

        if r["verdict_pre"] == C.PASS:
            row["verdict_pre"] = C.PASS if agrees(tr.get("mean_pct"), r["mean_pct"]) else C.CONTEXT_ONLY
        if r["verdict_adj"] == C.PASS:
            row["verdict_adj"] = C.PASS if agrees(tr.get("excess_pct"), r["excess_pct"]) else C.CONTEXT_ONLY
            row["verdict"], row["post_hoc_cap"] = _cap(row["verdict_adj"]), row["verdict_adj"] == C.PASS
        out.append(row)
    return out


def hypothesis_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """H1 / H1b / H2 from the per-month verdicts (drift-adjusted, capped), with the pre-registered verdict beside it."""
    by_m = {r["m"]: r for r in rows}

    def combine(vs: list[str]) -> str:
        return C.PASS if all(v == C.PASS for v in vs) else (C.CONTEXT_ONLY if any(v in (C.PASS, C.CONTEXT_ONLY) for v in vs) else C.FAIL)

    out = []
    for name, months in HYPOTHESES.items():
        out.append({"hypothesis": name, "months": ", ".join(MONTHS[m - 1] for m in months),
                    "per_month": "; ".join(f"{MONTHS[m - 1]} {C.fmt(by_m[m]['mean_pct'])} % (t vs 0 {C.fmt(by_m[m]['t'])}; excess "
                                           f"{C.fmt(by_m[m]['excess_pct'])} % t {C.fmt(by_m[m]['t_excess'])}, halves "
                                           f"{C.fmt(by_m[m]['h1_t_excess'])}/{C.fmt(by_m[m]['h2_t_excess'])}) {by_m[m]['verdict']}" for m in months),
                    "verdict_pre": combine([by_m[m]["verdict_pre"] for m in months]),
                    "verdict": combine([by_m[m]["verdict"] for m in months])})
    return out


def walk_forward_best_months(ret: pd.Series, k: int = BEST_K, min_years: int = MIN_YEARS, cost_switch: float = C.COST_RT) -> dict[str, Any]:
    """H3: at the start of each year go long only in the k months with the highest mean return over all completed prior
    years; flat otherwise; `cost_switch` % per switch — the PLAN's wording, i.e. every flat→long and long→flat transition
    is charged 0.15 % (0.30 % per round trip, twice the per-round-trip floor the other studies use; stricter, never
    laxer). OOS = from the (min_years+1)-th year; excess vs scaled buy-and-hold with the plain t (non-overlapping
    months) in the full OOS span and in each OOS half (split at the midpoint date)."""
    r = pd.Series(ret, dtype=float).dropna()
    df = pd.DataFrame({"ret": r, "year": r.index.year, "month": r.index.month})
    years = sorted(df["year"].unique())
    if len(years) <= min_years + 2:
        return {}
    pos = pd.Series(0.0, index=df.index)
    chosen: dict[int, list[str]] = {}
    for y in years[min_years:]:
        prior = df[df["year"] < y]
        best = prior.groupby("month")["ret"].mean().sort_values(ascending=False).index[:k]
        chosen[int(y)] = [MONTHS[m - 1] for m in sorted(best)]
        pos[(df["year"] == y) & df["month"].isin(best)] = 1.0
    simple = np.exp(df["ret"] / 100) - 1
    oos_start = int(np.searchsorted(df["year"].to_numpy(), years[min_years]))
    # evaluate_long_flat charges cost_rt / 2 per unit of turnover, so cost_rt = 2 × cost_switch is 'cost_switch per switch'
    ev = C.evaluate_long_flat(pos, simple, h=1, periods_per_year=12, cost_rt=2 * cost_switch, is_end=oos_start)
    s, b, po = ev["_series"]["strat"], ev["_series"]["bh"], ev["_series"]["pos"]
    oos = pd.Series(np.arange(len(s)) >= oos_start, index=s.index)
    diff = (s - b * po[oos].mean())[oos]
    mid = diff.index[len(diff) // 2]
    h1, h2 = C.halves(diff.index, mid)
    t_full, t1, t2 = C.plain_t(diff), C.plain_t(diff[h1]), C.plain_t(diff[h2])
    return {"oos_from": int(years[min_years]), "oos_months": int(oos.sum()), "oos_mid": str(mid.date()),
            "exposure_pct": ev.get("OOS_exposure_pct"), "strat_cagr": ev.get("OOS_strat_cagr"), "bh_cagr": ev.get("OOS_bh_cagr"),
            "strat_sharpe": ev.get("OOS_strat_sharpe"), "bh_sharpe": ev.get("OOS_bh_sharpe"), "strat_maxdd": ev.get("OOS_strat_maxdd"),
            "excess_vs_scaled_pa_pct": ev.get("OOS_excess_vs_scaled_pa_pct"), "t": round(t_full, 2), "t_h1": round(t1, 2), "t_h2": round(t2, 2),
            # SIGNED: the traded rule must pay (t >= 2 in the OOS span and both OOS halves); a consistent loser is a FAIL
            "verdict": C.verdict_traded(t_full, t1, t2), "last_year_months": chosen.get(int(years[-1]), []), "cost_per_switch_pct": cost_switch}


def decomposition(usd_ret: pd.Series, fx_ret: pd.Series, split: str) -> list[dict[str, Any]]:
    """Per month: the USD-gold leg and the USD/INR leg (log INR return = log USD return + log FX return), descriptive."""
    u, f = pd.Series(usd_ret, dtype=float), pd.Series(fx_ret, dtype=float)
    idx = u.index.intersection(f.index)
    u, f = u[idx], f[idx]
    rows = []
    for m in range(1, 13):
        um, fm = u[u.index.month == m], f[f.index.month == m]
        rows.append({"month": MONTHS[m - 1], "n": len(um), "usd_mean_pct": round(float(um.mean()), 2), "usd_t": round(C.plain_t(um), 2),
                     "fx_mean_pct": round(float(fm.mean()), 2), "fx_t": round(C.plain_t(fm), 2),
                     "inr_mean_pct": round(float((um + fm).mean()), 2),
                     "dominant_leg": "USD gold" if abs(um.mean()) >= abs(fm.mean()) else "USD/INR"})
    return rows


def negative_controls(long_inr_ret: pd.Series, trad_inr_ret: pd.Series, seed: int = SEED, n_null: int = NULL_SEEDS) -> dict[str, Any]:
    """Pre-registered controls, run for both statistics: with the month labels shuffled across observations (same count
    per month, calendar structure destroyed — N3) no month may PASS; H3 on shuffled returns must have |t| < 2. The
    pre-registered seed gives the verdict (`ok_pre` for the vs-zero statistic, `ok` for the drift-adjusted one); `n_null`
    further seeds give the null rates (how often a shuffle "passes") that decide whether a statistic is void (N4)."""
    rng = np.random.default_rng(seed)
    labels = pd.Series(rng.permutation(long_inr_ret.index.month.to_numpy()), index=long_inr_ret.index)
    relabelled = month_table(long_inr_ret, LONG_SPLIT, month_labels=labels)
    shuffled = pd.Series(rng.permutation(trad_inr_ret.to_numpy()), index=trad_inr_ret.index)
    wf = walk_forward_best_months(shuffled)
    pass_pre = [r["month"] for r in relabelled if r["verdict_pre"] == C.PASS]
    pass_adj = [r["month"] for r in relabelled if r["verdict_adj"] == C.PASS]
    null = {"seeds": n_null, "pass_pre": 0, "pass_adj": 0, "ge2_pre": 0, "ge2_adj": 0, "h3_ge2": 0}
    for s in range(n_null):
        g = np.random.default_rng(seed + 1 + s)
        rows = month_table(long_inr_ret, LONG_SPLIT, month_labels=pd.Series(g.permutation(long_inr_ret.index.month.to_numpy()),
                                                                               index=long_inr_ret.index))
        null["pass_pre"] += any(r["verdict_pre"] == C.PASS for r in rows)
        null["pass_adj"] += any(r["verdict_adj"] == C.PASS for r in rows)
        null["ge2_pre"] += sum(abs(r["t"]) >= 2 for r in rows if not math.isnan(r["t"]))
        null["ge2_adj"] += sum(abs(r["t_excess"]) >= 2 for r in rows if not math.isnan(r["t_excess"]))
        w = walk_forward_best_months(pd.Series(g.permutation(trad_inr_ret.to_numpy()), index=trad_inr_ret.index))
        null["h3_ge2"] += bool(w) and abs(w.get("t", 0.0)) >= 2.0
    rates = {"null_pass_rate_pre": round(null["pass_pre"] / n_null, 3), "null_pass_rate_adj": round(null["pass_adj"] / n_null, 3),
             "null_months_ge2_pre": round(null["ge2_pre"] / n_null, 2), "null_months_ge2_adj": round(null["ge2_adj"] / n_null, 2),
             "null_h3_ge2_rate": round(null["h3_ge2"] / n_null, 3)}
    shuffle_ok = bool(wf) and abs(wf.get("t", 0.0)) < 2.0
    return {"relabel": f"month labels shuffled across observations (seed {seed}; null rates over {n_null} further seeds)",
            "relabel_pass_months_pre": pass_pre, "relabel_pass_months": pass_adj, "relabel_ok_pre": not pass_pre, "relabel_ok": not pass_adj,
            **rates, "shuffled_walk_forward_t": wf.get("t"), "shuffle_ok": shuffle_ok,
            "ok_pre": (not pass_pre) and shuffle_ok, "ok": (not pass_adj) and shuffle_ok,
            "pre_registered_statistic_void": bool(pass_pre) or rates["null_pass_rate_pre"] > VOID_NULL_RATE}


# ─────────────────────────────────────────────────────────────────────────────────────────────────
# Run
# ─────────────────────────────────────────────────────────────────────────────────────────────────

def run_study(inputs: dict[str, pd.Series], out: Path) -> dict[str, Any]:
    res = out / "results"
    res.mkdir(parents=True, exist_ok=True)
    ms = monthly_series(inputs)
    rets = {k: log_returns(v) for k, v in ms.items()}
    long_inr = month_table(rets["long_inr"], LONG_SPLIT)
    trad_inr = month_table(rets["trad_inr"], TRADABLE_SPLIT)
    long_usd = month_table(rets["long_usd"], LONG_SPLIT)
    long_fx = month_table(rets["long_fx"], LONG_SPLIT)
    months = confirm_with_tradable(long_inr, trad_inr)
    goldbees = month_table(rets["goldbees"], str(rets["goldbees"].index[len(rets["goldbees"]) // 2].date())) if "goldbees" in rets else []
    wf = walk_forward_best_months(rets["trad_inr"])
    wf_long = walk_forward_best_months(rets["long_inr"])
    decomp = decomposition(rets["long_usd"], rets["long_fx"], LONG_SPLIT)
    controls = negative_controls(rets["long_inr"], rets["trad_inr"])
    hyps = hypothesis_summary(months)
    for name, rows in (("months_inr_long", months), ("months_inr_tradable", trad_inr), ("months_usd_long", long_usd),
                       ("months_fx_long", long_fx), ("months_goldbees", goldbees), ("decomposition", decomp), ("hypotheses", hyps)):
        if rows:
            pd.DataFrame(rows).to_csv(res / f"{name}.csv", index=False)
    pd.DataFrame({"long_inr": ms["long_inr"], "long_usd": ms["long_usd"], "long_fx": ms["long_fx"]}).to_csv(res / "monthly_levels_long.csv")
    pd.DataFrame({"trad_inr": ms["trad_inr"], "trad_usd": ms["trad_usd"], "trad_fx": ms["trad_fx"]}).to_csv(res / "monthly_levels_tradable.csv")
    sample = {"long_inr": {"from": str(rets["long_inr"].index[0].date()), "to": str(rets["long_inr"].index[-1].date()), "months": len(rets["long_inr"])},
              "tradable_inr": {"from": str(rets["trad_inr"].index[0].date()), "to": str(rets["trad_inr"].index[-1].date()), "months": len(rets["trad_inr"])},
              "goldbees": {"from": str(rets["goldbees"].index[0].date()), "to": str(rets["goldbees"].index[-1].date()),
                           "months": len(rets["goldbees"])} if "goldbees" in rets else None,
              "long_split": LONG_SPLIT, "tradable_split": TRADABLE_SPLIT, "cost_per_switch_pct": C.COST_RT,
              "rupee_drift_pa_pct": round(float(rets["long_fx"].mean() * 12), 2)}
    passing = [r["month"] for r in months if r["verdict"] == C.PASS]
    context = [r["month"] for r in months if r["verdict"] == C.CONTEXT_ONLY]
    capped = [r["month"] for r in months if r.get("post_hoc_cap")]
    context_pre = [r["month"] for r in months if r["verdict_pre"] in (C.PASS, C.CONTEXT_ONLY)]
    h3 = wf.get("verdict", C.FAIL)
    overall = C.PASS if (passing and h3 == C.PASS) else (C.CONTEXT_ONLY if (passing or context or h3 == C.CONTEXT_ONLY) else C.FAIL)
    void = controls["pre_registered_statistic_void"]
    pre_months = [r["month"] for r in months if r["verdict_pre"] == C.PASS]
    verdict_pre = C.VOID if void else (C.PASS if any(r["verdict_pre"] == C.PASS for r in months) else (C.CONTEXT_ONLY if context_pre else C.FAIL))
    # the study-level verdict names both statistics: the pre-registered one (VOID by its own control) and the post-hoc one (capped)
    overall_label = (f"{C.VOID} (pre-registered statistic) / {overall} (post-hoc drift-adjusted, capped)" if void
                     else f"{verdict_pre} (pre-registered statistic) / {overall} (drift-adjusted, capped)")
    summary: dict[str, Any] = {"study": STUDY, "plan": "reports/gold_program/GS-P4/PLAN.md",
                               "generated": pd.Timestamp.now().isoformat(timespec="minutes"), "sample": sample, "months_inr_long": months,
                               "months_inr_tradable": trad_inr, "months_usd_long": long_usd, "months_fx_long": long_fx, "months_goldbees": goldbees,
                               "hypotheses": hyps, "walk_forward_tradable": wf, "walk_forward_long": wf_long, "decomposition": decomp,
                               "negative_controls": controls, "controls_ok": controls["ok"],
                               "pre_registered_statistic_void": void, "null_seed_set": f"seeds {SEED + 1}–{SEED + NULL_SEEDS}",
                               "pass_months": passing, "context_months": context, "post_hoc_capped_months": capped,
                               "context_months_pre_registered_statistic": context_pre, "pass_months_pre_registered_statistic": pre_months,
                               "verdict_pre_registered": verdict_pre, "overall": overall, "overall_label": overall_label}
    C.write_json(out / "summary.json", summary)
    (out / "REPORT.md").write_text(report_md(summary), encoding="utf-8")
    (out / "FINDINGS_ROW.md").write_text(findings_rows_md(summary), encoding="utf-8")
    (out / "FINDINGS.md").write_text(findings_md(summary), encoding="utf-8")
    return summary


def _month_verdict_cell(summary: dict[str, Any], verdict_adj: str, verdict_pre: str) -> str:
    """The verdict cell of a month-statistic row names both statistics: the pre-registered vs-zero one (VOID when its own
    control passes, N4) and the post-hoc drift-adjusted one (capped at CONTEXT-ONLY)."""
    if summary["pre_registered_statistic_void"]:
        return f"{C.VOID} (pre-registered) / {verdict_adj} (drift-adjusted, capped)"
    return f"{verdict_pre} (pre-registered) / {verdict_adj} (drift-adjusted, capped)"


def _rows(summary: dict[str, Any]) -> list[C.Row]:
    by_m = {r["m"]: r for r in summary["months_inr_long"]}
    nc = summary["negative_controls"]
    mu = summary["months_inr_long"][0]["sample_mean_pct"]
    rows = []
    for h in summary["hypotheses"]:
        months = [m for m in range(1, 13) if MONTHS[m - 1] in h["months"].split(", ")]
        result = "; ".join(f"{MONTHS[m - 1]} {C.fmt(by_m[m]['mean_pct'])} % (t vs 0 {C.fmt(by_m[m]['t'])}; excess {C.fmt(by_m[m]['excess_pct'])} % "
                           f"t {C.fmt(by_m[m]['t_excess'])}) {by_m[m]['verdict']}" for m in months)
        h1 = " · ".join(f"{MONTHS[m - 1]} excess t {C.fmt(by_m[m]['h1_t_excess'])}" for m in months)
        h2 = " · ".join(f"{MONTHS[m - 1]} excess t {C.fmt(by_m[m]['h2_t_excess'])}" for m in months)
        rows.append(C.Row(h["hypothesis"] + " (rupee gold, 1973 →, drift-adjusted)", result, h1, h2,
                          _month_verdict_cell(summary, h["verdict"], h["verdict_pre"])))
    wf = summary["walk_forward_tradable"]
    if wf:
        rows.append(C.Row("H3 · walk-forward best-6-months long/flat in rupees (GC=F × USD/INR month-ends, 0.15 % per switch = 0.30 % per round trip)",
                          (f"OOS {wf['oos_from']} →: excess vs scaled B&H {C.fmt(wf['excess_vs_scaled_pa_pct'])} %/yr (t {C.fmt(wf['t'])}), "
                           f"exposure {C.fmt(wf['exposure_pct'], 0)} %; shuffled returns reach |t| ≥ 2 in {nc['null_h3_ge2_rate']:.0%} of seeds"),
                          f"t {C.fmt(wf['t_h1'])}", f"t {C.fmt(wf['t_h2'])} (OOS cut {wf['oos_mid']})", wf["verdict"]))
    for r in summary["months_inr_long"]:
        if r["verdict"] in (C.PASS, C.CONTEXT_ONLY):
            cap = " (PASS capped: statistic adopted post hoc, N4)" if r.get("post_hoc_cap") else ""
            rows.append(C.Row(f"{r['month']} in rupees (1973 →, drift-adjusted)",
                              (f"excess {C.fmt(r['excess_pct'])} % over the all-month mean {C.fmt(mu)} % (t {C.fmt(r['t_excess'])}; vs 0: "
                               f"{C.fmt(r['mean_pct'])} %, t {C.fmt(r['t'])}, hit {C.fmt(r['hit_pct'], 0)} %); 2000 → month-ends excess "
                               f"{C.fmt(r['tradable_excess_pct'])} % (t {C.fmt(r['tradable_t_excess'])})"),
                              f"excess t {C.fmt(r['h1_t_excess'])}", f"excess t {C.fmt(r['h2_t_excess'])}", f"{r['verdict']}{cap}"))
    pre = summary["context_months_pre_registered_statistic"]
    rows.append(C.Row("the pre-registered statistic (each month's mean vs zero), for the record",
                      (f"{', '.join(pre) if pre else 'no month'} at t ≥ 2 in the full sample — but shuffled month labels 'pass' in "
                       f"{nc['null_pass_rate_pre']:.0%} of {NULL_SEEDS} seeds ({summary['null_seed_set']}; {nc['null_months_ge2_pre']} such months "
                       f"per run): the statistic measures the {C.fmt(mu)} %/month drift, not the calendar"),
                      f"null PASS rate vs 0 {nc['null_pass_rate_pre']:.0%}", f"drift-adjusted {nc['null_pass_rate_adj']:.0%}",
                      f"{summary['verdict_pre_registered']} (PLAN N4; the drift-adjusted rows above replace it)"))
    return rows


def findings_rows_md(summary: dict[str, Any]) -> str:
    """The 4-column rows to paste into reports/gold_program/FINDINGS.md (shape: scripts/gold_studies/FINDINGS_ROW_TEMPLATE.md)."""
    return C.findings_rows_md(STUDY, _rows(summary))


def findings_md(summary: dict[str, Any]) -> str:
    """The study's own FINDINGS.md in the reports/fii_positioning format, every sentence computed from the summary."""
    s, wf, nc = summary["sample"], summary["walk_forward_tradable"], summary["negative_controls"]
    months = summary["months_inr_long"]
    mu = months[0]["sample_mean_pct"]
    ctx = [r["month"] for r in months if r["verdict"] == C.CONTEXT_ONLY]
    capped = summary["post_hoc_capped_months"]
    passing = [r["month"] for r in months if r["verdict"] == C.PASS]
    pre = summary["context_months_pre_registered_statistic"]
    trad_both = [r["month"] for r in months if r.get("tradable_verdict") == C.PASS]
    hyp = {h["hypothesis"].split(" ")[0]: h["verdict"] for h in summary["hypotheses"]}
    fx = {r["month"]: r for r in summary["months_fx_long"]}
    fx_ge2 = [f"{m} {C.fmt(r['mean_pct'])} % (t {C.fmt(r['t'])})" for m, r in fx.items() if abs(r["t"]) >= 2]
    overall = summary["overall"]
    void = (f"{summary['overall_label']} — drift, not a calendar. The pre-registered statistic (each month's mean vs zero) is VOID by the "
            f"plan's own control rule: its shuffle control passes in {nc['null_pass_rate_pre']:.0%} of {NULL_SEEDS} seeds "
            f"({summary['null_seed_set']}; independent probes in PLAN N4) because rupee gold drifts {C.fmt(mu)} %/month. Drift-adjusted "
            "(month minus the all-month mean, adopted post hoc and capped at CONTEXT-ONLY), ")
    if passing:
        verdict_line = (f"PASS for {', '.join(passing)} in rupees — the owner's separate approval is still required before any badge "
                        "changes (PLAN f.5).")
    elif overall == C.CONTEXT_ONLY:
        verdict_line = (void + f"{', '.join(ctx)} reach |t| ≥ 2 in the full sample only"
                        + (f" ({', '.join(capped)} would pass both halves, capped: post-hoc statistic)" if capped else "")
                        + "; no month passes both halves of 1973 →; the festival months do not pass; the walk-forward best-6-months rule "
                        "FAILs after costs. A caption, not a rule.")
    else:
        verdict_line = (void + "no month reaches |t| ≥ 2 in both halves of 1973 → (nor in the full sample); the festival months do not pass; "
                        "the walk-forward best-6-months rule FAILs after costs (signed: it must pay).")
    bullets = [(f"Hypotheses (drift-adjusted): H1 festival Sep/Oct/Nov {hyp.get('H1')}; H1b Akshaya Tritiya Apr/May {hyp.get('H1b')}; H2 Dec/Jan "
                f"carry-over {hyp.get('H2')}; H3 tradable rule {wf.get('verdict', 'n/a')}."),
               (f"Under the vs-zero statistic {', '.join(pre) if pre else 'no month'} reached t ≥ 2 in the full sample (the first draft's "
                f"'CONTEXT-ONLY' months); shuffled month labels produce {nc['null_months_ge2_pre']} such months per run on average "
                f"({nc['null_months_ge2_adj']} drift-adjusted) — those months are what the drift alone delivers (PLAN N4)."),
               (f"H3 (long only in the 6 best months of all prior years, 0.15 % per switch, OOS {wf.get('oos_from')} → on GC=F × USD/INR "
                f"month-ends): excess vs scaled buy-and-hold {C.fmt(wf.get('excess_vs_scaled_pa_pct'))} %/yr, t {C.fmt(wf.get('t'))} "
                f"(OOS halves t {C.fmt(wf.get('t_h1'))} / {C.fmt(wf.get('t_h2'))}, cut {wf.get('oos_mid')}); exposure "
                f"{C.fmt(wf.get('exposure_pct'), 0)} %; shuffled returns reach |t| ≥ 2 in {nc['null_h3_ge2_rate']:.0%} of seeds."),
               ("In the 2000 → month-end sample alone " + ", ".join(trad_both) + " clear(s) |t| ≥ 2 drift-adjusted in both of its halves, but not "
                "in 1973–99: CONTEXT-ONLY by the both-halves rule." if trad_both else
                "No month clears |t| ≥ 2 drift-adjusted in both halves of the 2000 → month-end sample either."),
               (f"The rupee leg adds a drift of {s['rupee_drift_pa_pct']} %/yr (log) that is not seasonal; USD/INR months at |t| ≥ 2 vs zero in "
                f"1973 →: " + (", ".join(fx_ge2) if fx_ge2 else "none") + ". The decomposition per month is in REPORT.md."),
               (f"Negative controls (month labels shuffled across observations; seeded shuffle of H3's returns): drift-adjusted ok {nc['ok']} "
                f"(relabelled PASS months {nc['relabel_pass_months']}, null PASS rate {nc['null_pass_rate_adj']:.0%}, shuffled H3 t "
                f"{C.fmt(nc['shuffled_walk_forward_t'])}); vs-zero ok {nc['ok_pre']} (relabelled PASS months {nc['relabel_pass_months_pre']}, "
                f"null PASS rate {nc['null_pass_rate_pre']:.0%})."),
               (f"Sample: {s['long_inr']['months']} months {s['long_inr']['from']} → {s['long_inr']['to']} (World Bank monthly average × DEXINUS mean, "
                f"GC=F spliced after Dec 2024; halves at {s['long_split']}); tradable {s['tradable_inr']['months']} month-ends "
                f"{s['tradable_inr']['from']} → {s['tradable_inr']['to']} (halves at {s['tradable_split']}); duty steps and the local premium "
                "are outside the proxy (the GOLDBEES.NS table in REPORT.md carries them).")]
    use = ("`m.season` keeps the `context` badge: the rupee grid shows mean and hit rate per month with the caption 'once the +1 %/month "
           "drift is removed no month passes in both halves 1973 → in rupees; festival months do not pass; best-6-months walk-forward fails "
           "after costs (GS-P4, 26 Oct 2026)'; no month is coloured, no calendar rule is traded." if not passing
           else "do not change any badge from this file alone — PLAN f.5 requires the owner's separate approval.")
    return C.findings_template(STUDY, f"{STUDY} · {TITLE}", C.now_label(),
                               f"Monthly log returns of gold in rupees (USD gold × USD/INR), {s['long_inr']['months']} months "
                               f"{s['long_inr']['from']} → {s['long_inr']['to']} plus a tradable month-end sample 2000 →; month-of-year is "
                               "calendar knowledge (no release lag); plain t on non-overlapping months; the walk-forward rule learns each "
                               "year's month set from completed prior years only; 0.15 % per switch.",
                               verdict_line, _rows(summary), bullets, use, SCRIPT)


def report_md(summary: dict[str, Any]) -> str:
    s = summary["sample"]
    mcols = ["month", "n", "mean_pct", "hit_pct", "t", "excess_pct", "t_excess", "h1_mean", "h1_t", "h1_t_excess", "h1_n", "h2_mean", "h2_t",
             "h2_t_excess", "h2_n", "verdict_pre", "verdict_adj", "verdict"]
    wf, wfl, nc = summary["walk_forward_tradable"], summary["walk_forward_long"], summary["negative_controls"]
    parts = [f"# {STUDY} · {TITLE} — result tables\n",
             (f"Generated {summary['generated']} by `{SCRIPT}` from the plan in `PLAN.md`. Long sample (World Bank monthly average × DEXINUS "
              f"monthly mean, GC=F spliced after Dec 2024): {s['long_inr']['from']} → {s['long_inr']['to']}, {s['long_inr']['months']} months, "
              f"halves at {s['long_split']}. Tradable sample (GC=F month-end × DEXINUS month-end): {s['tradable_inr']['from']} → "
              f"{s['tradable_inr']['to']}, {s['tradable_inr']['months']} months, halves at {s['tradable_split']}. Rupee drift "
              f"{s['rupee_drift_pa_pct']} %/yr (log, not seasonal). Monthly log returns, plain t. Costs {s['cost_per_switch_pct']} % per switch "
              "(every flat→long and long→flat transition).\n"),
             ("## Gold in rupees, long sample, by calendar month\n\n`t` = the month's mean vs zero (pre-registered; void, N4); `t_excess` = "
              "the month's mean minus the all-month mean of the same sample / half (drift-adjusted); `verdict` = the drift-adjusted verdict "
              "capped at CONTEXT-ONLY (post-hoc statistic). PASS needs |t| ≥ 2 with the same sign in both halves + the same sign 2000 → "
              "month-ends.\n"),
             C.md_table(summary["months_inr_long"], mcols + ["tradable_excess_pct", "tradable_t_excess", "tradable_verdict", "post_hoc_cap"]),
             "\n## Hypotheses\n", C.md_table(summary["hypotheses"], ["hypothesis", "months", "per_month", "verdict_pre", "verdict"]),
             "\n## Gold in rupees, tradable month-end sample (2000 →)\n", C.md_table(summary["months_inr_tradable"], mcols),
             "\n## The two legs, long sample: gold in USD and USD/INR\n", C.md_table(summary["months_usd_long"], mcols),
             "", C.md_table(summary["months_fx_long"], mcols),
             "\n### Decomposition per month (log INR = log USD + log FX)\n",
             C.md_table(summary["decomposition"], ["month", "n", "usd_mean_pct", "usd_t", "fx_mean_pct", "fx_t", "inr_mean_pct", "dominant_leg"])]
    if summary["months_goldbees"]:
        parts += [f"\n## GOLDBEES.NS month-ends ({s['goldbees']['from']} → {s['goldbees']['to']}; duty, premium and expense ratio included)\n",
                  C.md_table(summary["months_goldbees"], mcols)]
    if wf:
        parts += ["\n## H3 · walk-forward best-6-months rule, tradable sample\n",
                  C.md_table([wf], ["oos_from", "oos_months", "oos_mid", "exposure_pct", "strat_cagr", "bh_cagr", "strat_sharpe", "bh_sharpe",
                                    "strat_maxdd", "excess_vs_scaled_pa_pct", "t", "t_h1", "t_h2", "verdict"]),
                  f"\nMonth set chosen for the last year: {', '.join(wf['last_year_months'])}."]
    if wfl:
        parts += ["\n### The same rule on the long (average-price, non-tradable) sample, for reference\n",
                  C.md_table([wfl], ["oos_from", "oos_months", "exposure_pct", "strat_cagr", "bh_cagr", "excess_vs_scaled_pa_pct", "t", "t_h1", "t_h2", "verdict"])]
    parts += [(f"\n## Negative controls\n\nRelabelled months ({nc['relabel']}). Drift-adjusted: PASS months {nc['relabel_pass_months']} → ok "
               f"{nc['relabel_ok']}; null PASS rate {nc['null_pass_rate_adj']:.0%}, months at |t| ≥ 2 per run {nc['null_months_ge2_adj']}. "
               f"Vs zero (pre-registered): PASS months {nc['relabel_pass_months_pre']} → ok {nc['relabel_ok_pre']}; null PASS rate "
               f"{nc['null_pass_rate_pre']:.0%}, months at t ≥ 2 per run {nc['null_months_ge2_pre']} → statistic void: "
               f"{nc['pre_registered_statistic_void']}. H3 on shuffled returns: t {C.fmt(nc['shuffled_walk_forward_t'])} → ok "
               f"{nc['shuffle_ok']}; |t| ≥ 2 in {nc['null_h3_ge2_rate']:.0%} of seeds.\n"),
              (f"\n## Overall: **{summary['overall_label']}** (badge consequence: {summary['overall']}) — PASS months {summary['pass_months']}, "
               f"CONTEXT-ONLY months {summary['context_months']} "
               f"(post-hoc capped: {summary['post_hoc_capped_months']}), vs-zero months at t ≥ 2 {summary['context_months_pre_registered_statistic']}"
               f" (void), H3 {wf.get('verdict', 'n/a')} (drift-adjusted controls ok: {summary['controls_ok']})\n")]
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", type=Path, default=None, help="directory with the G-MACRO CSVs (default reports/gold_program/G-MACRO/data)")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    a = ap.parse_args(argv)
    try:
        inputs = load_inputs(a.data_dir)
    except C.DataNotIngested as e:
        C.not_ingested(STUDY, "worldbank_cmo_monthly.csv, yahoo_GC_F.csv, fred_DEXINUS.csv (G-MACRO/data)",
                       "restore the G-MACRO research data or point --data-dir at it", str(e))
    if len(inputs["dexinus"]) < 252 * 20:
        C.insufficient(STUDY, ">= 20 years of USD/INR", f"{len(inputs['dexinus'])} days")
    summary = run_study(inputs, a.out)
    print(C.Status(STUDY, "ran", detail=f"overall {summary['overall_label']}; drift-adjusted controls ok {summary['controls_ok']}; "
                                        f"out {a.out}").to_json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
