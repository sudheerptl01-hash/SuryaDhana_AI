#!/usr/bin/env python3
"""Generate ml/report/feature_study.html: feature EDA + engineered-feature A/B.

One self-contained page in the pilot report's design system (same colour
tokens, theme handling and tooltip). Every number on the page is read from:

  ml/results/feature_study/eda_features.json              the EDA (8 analyses)
  ml/results/feature_study/feature_ab_verdict.json        A/B summary + pass mark
  ml/results/feature_study/<variant>__beat_mkt_20d.json   per-fold A/B results
  ml/results/feature_study/manifest_fe.json               engineered-feature build
  ml/results/lgbm_fs_selected_clean__beat_mkt_20d.json    the A/B control
  ml/results/lr_l2_clean__beat_mkt_20d.json               logistic benchmark

Run: cd /home/user/SuryaDhana_AI && python3 -m ml.make_feature_study
"""
from __future__ import annotations

import html
import json
import math
from datetime import datetime
from pathlib import Path

ML = Path(__file__).resolve().parent
RES = ML / "results"
FS = RES / "feature_study"
OUT = ML / "report" / "feature_study.html"
PILOT_URL = "https://claude.ai/artifact/NvmH4oxd4TcPHQqfEo8LBF"

BREAK = "2026-03"                       # first month after the Feb-2026 sell-off
FOLD1_TRAIN_END = "25 February 2026"    # splits.json, fold 2026-04
CV_MONTHS = ["2026-04", "2026-05", "2026-06", "2026-07"]
HOLDOUT_MONTHS = ["2026-08", "2026-09"]
MINUS = "−"


def load(p: Path) -> dict:
    return json.loads(p.read_text())


eda = load(FS / "eda_features.json")
verdict = load(FS / "feature_ab_verdict.json")
fe = load(FS / "manifest_fe.json")
control = load(RES / "lgbm_fs_selected_clean__beat_mkt_20d.json")
lr_bench = load(RES / "lr_l2_clean__beat_mkt_20d.json")

IC = eda["ic_stability"]
MONTHS = sorted({m for v in IC.values() for m in v["monthly_ic"]})
PRE = [m for m in MONTHS if m < BREAK]
POST = [m for m in MONTHS if m >= BREAK]
CHAMPION = eda["meta"]["champion_features"]
META = eda["meta"]

E = html.escape


def sgn(x: float, d: int = 3) -> str:
    return f"{x:+.{d}f}".replace("-", MINUS)


def pts(x: float, d: int = 2) -> str:
    """Fraction -> signed percentage points."""
    return sgn(x * 100, d)


def mean_over(f: str, months: list[str]) -> float | None:
    xs = [IC[f]["monthly_ic"].get(m) for m in months]
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def months_same_sign(v: dict) -> int:
    return round(v["ic_sign_consistency"] * v["n_months"])


def hbar(x0: float, x1: float, yc: float, h: float, r: float = 4) -> str:
    """Horizontal bar, square at the baseline x0, rounded at the data end x1."""
    y0, y1 = yc - h / 2, yc + h / 2
    w = abs(x1 - x0)
    r = min(r, w, h / 2)
    if w < 0.5:
        return ""
    if x1 >= x0:
        return (f"M{x0:.1f},{y0:.1f} H{x1 - r:.1f} A{r},{r} 0 0 1 {x1:.1f},{y0 + r:.1f} "
                f"V{y1 - r:.1f} A{r},{r} 0 0 1 {x1 - r:.1f},{y1:.1f} H{x0:.1f} Z")
    return (f"M{x0:.1f},{y0:.1f} H{x1 + r:.1f} A{r},{r} 0 0 0 {x1:.1f},{y0 + r:.1f} "
            f"V{y1 - r:.1f} A{r},{r} 0 0 0 {x1 + r:.1f},{y1:.1f} H{x0:.1f} Z")


def vbar(xc: float, w: float, yb: float, yt: float, r: float = 4) -> str:
    """Vertical column, square at the baseline yb, rounded at the data end yt."""
    x0, x1 = xc - w / 2, xc + w / 2
    hgt = abs(yb - yt)
    r = min(r, w / 2, hgt)
    if hgt < 0.5:
        return ""
    if yt <= yb:
        return (f"M{x0:.1f},{yb:.1f} V{yt + r:.1f} A{r},{r} 0 0 1 {x0 + r:.1f},{yt:.1f} "
                f"H{x1 - r:.1f} A{r},{r} 0 0 1 {x1:.1f},{yt + r:.1f} V{yb:.1f} Z")
    return (f"M{x0:.1f},{yb:.1f} V{yt - r:.1f} A{r},{r} 0 0 0 {x0 + r:.1f},{yt:.1f} "
            f"H{x1 - r:.1f} A{r},{r} 0 0 0 {x1:.1f},{yt - r:.1f} V{yb:.1f} Z")


# ---------------------------------------------------------------- facts --
n_new = fe["n_new_features"]
best_quick = max(((k, v) for k, v in fe["quick_ic"].items() if v.get("mean_ic") is not None),
                 key=lambda kv: abs(kv[1]["mean_ic"]))
red = fe["redundancy_flags_gt095"]
red_lo, red_hi = min(r["spearman"] for r in red), max(r["spearman"] for r in red)

n_worst_break = sum(1 for v in IC.values()
                    if (v.get("worst_month") or {}).get("month") == BREAK)
crash = eda["market_state"]["month_table"][BREAK]["mean_median_mom20"]
state = eda["market_state"]["ic_by_state"]

deliv, deliv_sma = IC["deliv_pct"], IC["deliv_pct_sma_20"]
noise_clearers = [f for f, v in IC.items() if v["mean_abs_lt_monthly_std"] is False]
assert noise_clearers == ["deliv_pct"], noise_clearers

age = eda["listing_age"]
liq = eda["liquidity_gradient"]
lab = eda["label_eda"]
rankt = eda["rank_transform_test"]
rank_gain = [v["abs_t_stat_gain_from_rank"] for v in rankt.values()
             if isinstance(v, dict) and "abs_t_stat_gain_from_rank" in v]
dist = eda["distribution_audit"]
clip_max = max(v["pct_clipped_at_fold1_train_1_99"] for v in dist.values()
               if isinstance(v, dict) and v.get("pct_clipped_at_fold1_train_1_99") is not None)
mono = eda["monotonicity"]


def interaction(key: str) -> dict:
    g = eda["interactions"][key]["grid_mean_y_excess"]
    hi_eff = g[2][2] - g[0][2]
    lo_eff = g[2][0] - g[0][0]
    d = eda["interactions"][key]
    assert abs((hi_eff - lo_eff) - d["double_difference"]) < 1e-3, key
    return {"grid": g, "hi": hi_eff, "lo": lo_eff, "dd": hi_eff - lo_eff,
            "k": round(d["pct_months_dd_same_sign"] * d["n_months_dd"]),
            "n": d["n_months_dd"], "dev": d["max_abs_deviation_from_additive"],
            "axis": d["grid_axis"]}


ix_vol = interaction("cs_rank_vol_20_x_mom_12_1")
ix_del = interaction("deliv_pct_sma_20_x_mom_12_1")

# ----------------------------------------------------------- A/B rows ----
VARIANTS = [
    ("lgbm_fe_top18", "fe_top18",
     "Champion 10 + the 8 new features with the highest build-time IC"),
    ("lgbm_fe_newaxes", "fe_newaxes",
     "Champion 10 + the 6 new features least correlated with existing ones"),
    ("lgbm_fe_regime", "fe_regime", "Champion 10 + 4 market-state features"),
    ("lgbm_fe_all", "fe_all", "All 51 base features + all 23 new features"),
    ("lr_rank_fe", "lr_rank_fe",
     "L2 logistic regression on 11 cross-sectional rank features"),
]


def ab_row(d: dict, short: str, desc: str, ctrl: bool = False) -> dict:
    folds = [f["auc"] for f in d["folds"]]
    return {"short": short, "desc": desc, "ctrl": ctrl, "nf": d["n_features"],
            "cv": d["cv_auc_mean"], "std": d["cv_auc_std"], "folds": folds,
            "lo": min(folds), "hi": max(folds), "holdout": d["holdout"]["auc"],
            "spread": d["holdout"].get("decile_spread")}


AB = [ab_row(control, "champion (control)",
             "Pilot champion: LightGBM on the 10 selected features, re-run on the cleaned data",
             ctrl=True)]
AB += [ab_row(load(FS / f"{k}__beat_mkt_20d.json"), s, d) for k, s, d in VARIANTS]
PASS = verdict["rebuild_bar_cv"]
BEST = max(AB[1:], key=lambda r: r["cv"])
assert not verdict["rebuild_warranted"]
assert all(r["cv"] < AB[0]["cv"] for r in AB[1:])
regime_ho = next(r for r in AB if r["short"] == "fe_regime")["holdout"]
lr_rank = next(r for r in AB if r["short"] == "lr_rank_fe")


def ab_chart() -> str:
    W, L, R = 760, 190, 640
    top, rh = 50, 46
    H = top + rh * len(AB) + 36
    allx = [a for r in AB for a in r["folds"]] + [0.50, PASS]
    lo = math.floor((min(allx) - 0.004) * 100) / 100
    hi = math.ceil((max(allx) + 0.004) * 100) / 100

    def X(v: float) -> float:
        return L + (v - lo) / (hi - lo) * (R - L)

    p = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="CV AUC by variant: mean and fold range, '
         f'with the control and the pass mark">']
    v = lo
    while v <= hi + 1e-9:
        x = X(v)
        p.append(f'<line x1="{x:.1f}" y1="{top - 8}" x2="{x:.1f}" y2="{H - 30}" class="grid"/>')
        p.append(f'<text x="{x:.1f}" y="{H - 12}" class="ax" text-anchor="middle">{v:.2f}</text>')
        v = round(v + 0.01, 2)
    xc, xp = X(AB[0]["cv"]), X(PASS)
    p.append(f'<line x1="{X(0.50):.1f}" y1="{top - 8}" x2="{X(0.50):.1f}" y2="{H - 30}" class="chance"/>')
    p.append(f'<line x1="{xc:.1f}" y1="{top - 14}" x2="{xc:.1f}" y2="{H - 30}" stroke="var(--ctrl)" stroke-width="1.5"/>')
    p.append(f'<line x1="{xp:.1f}" y1="{top - 14}" x2="{xp:.1f}" y2="{H - 30}" class="passln"/>')
    p.append(f'<text x="{xc - 6:.1f}" y="{top - 20}" class="lbl" text-anchor="end">control {AB[0]["cv"]:.4f}</text>')
    p.append(f'<text x="{xp + 6:.1f}" y="{top - 20}" class="lbl-em">pass mark {PASS:.4f}</text>')
    for i, r in enumerate(AB):
        y = top + rh * i + rh / 2
        col = "var(--ctrl)" if r["ctrl"] else "var(--s1)"
        folds_txt = ", ".join(f"{a:.3f}" for a in r["folds"])
        tip = (f'{r["short"]}: mean CV AUC {r["cv"]:.4f}; folds {folds_txt}; '
               f'holdout {r["holdout"]:.4f}')
        p.append(f'<g data-tip="{E(tip)}"><rect x="0" y="{y - rh / 2:.1f}" width="{W}" '
                 f'height="{rh}" fill="transparent"/>')
        p.append(f'<text x="{L - 16}" y="{y + 4:.1f}" class="{"lbl-em" if r["ctrl"] else "lbl"}" '
                 f'text-anchor="end">{E(r["short"])}</text>')
        p.append(f'<line x1="{X(r["lo"]):.1f}" y1="{y:.1f}" x2="{X(r["hi"]):.1f}" y2="{y:.1f}" '
                 f'stroke="{col}" stroke-width="2" stroke-linecap="round"/>')
        for a in r["folds"]:
            p.append(f'<circle cx="{X(a):.1f}" cy="{y:.1f}" r="4" fill="var(--surface)" '
                     f'stroke="{col}" stroke-width="2"/>')
        p.append(f'<circle cx="{X(r["cv"]):.1f}" cy="{y:.1f}" r="6.5" fill="{col}" '
                 f'stroke="var(--surface)" stroke-width="2"/></g>')
        p.append(f'<text x="{R + 18}" y="{y + 4:.1f}" class="val">{r["cv"]:.4f}</text>')
    p.append("</svg>")
    return "".join(p)


def ab_table() -> str:
    rows = []
    for r in AB:
        mn = "pos" if r["lo"] >= 0.50 else "neg"
        sp = r["spread"] or 0.0
        tr = '<tr class="champ">' if r["ctrl"] else "<tr>"
        rows.append(
            f'{tr}'
            f'<td class="mname">{E(r["short"])}</td><td class="wrapcell">{E(r["desc"])}</td>'
            f'<td>{r["nf"]}</td><td><b>{r["cv"]:.4f}</b> <span class="dim2">± {r["std"]:.3f}</span></td>'
            f'<td class="{mn}">{r["lo"]:.4f}</td><td>{r["holdout"]:.4f}</td>'
            f'<td class="{"pos" if sp > 0 else "neg"}">{pts(sp)}</td></tr>')
    return ('<table><thead><tr><th>Variant</th><th class="wrapcell">Features</th><th>#</th>'
            '<th>CV AUC ± std</th><th>Worst fold</th><th>Holdout</th><th>Holdout decile spread (pts)</th>'
            '</tr></thead><tbody>' + "".join(rows) + "</tbody></table>")


# ------------------------------------------------------ regime break ----
BREAK_ROWS = ["atr_pct", "vol_20", "range_pct", "dist_52w_low", "flag_below_200dma",
              "dist_200dma", "ret_63d", "mom_20", "ret_126d", "dist_52w_high", "deliv_pct",
              "log_turnover", "deliv_pct_sma_20"]
TWINS = {"deliv_pct_z_20": "cs_rank_deliv_z", "ret_126d": "cs_rank_ret_126",
         "vol_20": "cs_rank_vol_20", "log_turnover": "cs_rank_turnover",
         "mom_20": "cs_rank_mom_20", "ret_1d": "log_ret_1d"}
for a, b in TWINS.items():   # Spearman IC is rank-invariant: twins must match exactly
    ma, mb = IC[a]["monthly_ic"], IC[b]["monthly_ic"]
    assert ma.keys() == mb.keys() and all(
        (ma[m] is None and mb[m] is None) or abs(ma[m] - mb[m]) < 1e-9 for m in ma), (a, b)


def members(f: str) -> list[str]:
    return [f] + ([TWINS[f]] if f in TWINS else [])


def label(f: str) -> str:
    return " · ".join(members(f))


def is_champ(f: str) -> bool:
    return any(m in CHAMPION for m in members(f))


BRK = []
for f in BREAK_ROWS:
    pre, post = mean_over(f, PRE), mean_over(f, POST)
    BRK.append({"f": f, "pre": pre, "post": post, "chg": post - pre})
BRK.sort(key=lambda r: -r["chg"])

champ_on_chart = [(m, r) for r in BRK for m in members(r["f"]) if m in CHAMPION]
n_champ_on = len(champ_on_chart)
n_flip = sum(1 for _, r in champ_on_chart if (r["pre"] > 0) != (r["post"] > 0))
n_weak = sum(1 for _, r in champ_on_chart
             if (r["pre"] > 0) == (r["post"] > 0) and abs(r["post"]) < abs(r["pre"]))
missing_champ = [m for m in CHAMPION if m not in {c for c, _ in champ_on_chart}]


def break_chart() -> str:
    W, L, R = 760, 268, 728
    top, rh = 20, 30
    H = top + rh * len(BRK) + 40
    lo, hi = -0.16, 0.16

    def X(v: float) -> float:
        return L + (v - lo) / (hi - lo) * (R - L)

    p = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Mean monthly IC before and after '
         f'the March 2026 break, per feature">']
    for t in (-0.15, -0.10, -0.05, 0.05, 0.10, 0.15):
        x = X(t)
        p.append(f'<line x1="{x:.1f}" y1="{top - 6}" x2="{x:.1f}" y2="{H - 30}" class="grid"/>')
        p.append(f'<text x="{x:.1f}" y="{H - 12}" class="ax" text-anchor="middle">{sgn(t, 2)}</text>')
    p.append(f'<line x1="{X(0):.1f}" y1="{top - 6}" x2="{X(0):.1f}" y2="{H - 30}" class="axisln"/>')
    p.append(f'<text x="{X(0):.1f}" y="{H - 12}" class="ax" text-anchor="middle">0</text>')
    for i, r in enumerate(BRK):
        y = top + rh * i + rh / 2
        tip = (f'{label(r["f"])}: {sgn(r["pre"])} before, {sgn(r["post"])} after '
               f'(change {sgn(r["chg"])})')
        p.append(f'<g data-tip="{E(tip)}"><rect x="0" y="{y - rh / 2:.1f}" width="{W}" '
                 f'height="{rh}" fill="transparent"/>')
        p.append(f'<text x="{L - 14}" y="{y + 4:.1f}" class="{"lbl-em" if is_champ(r["f"]) else "lbl"}" '
                 f'text-anchor="end">{E(label(r["f"]))}</text>')
        p.append(f'<line x1="{X(r["pre"]):.1f}" y1="{y:.1f}" x2="{X(r["post"]):.1f}" y2="{y:.1f}" '
                 f'stroke="var(--axisc)" stroke-width="2"/>')
        p.append(f'<circle cx="{X(r["pre"]):.1f}" cy="{y:.1f}" r="5" fill="var(--surface)" '
                 f'stroke="var(--muted)" stroke-width="2"/>')
        p.append(f'<circle cx="{X(r["post"]):.1f}" cy="{y:.1f}" r="5.5" fill="var(--s1)" '
                 f'stroke="var(--surface)" stroke-width="2"/></g>')
    p.append("</svg>")
    return "".join(p)


def break_table() -> str:
    rows = "".join(
        f'<tr><td class="mname">{E(label(r["f"]))}{" ★" if is_champ(r["f"]) else ""}</td>'
        f'<td>{sgn(r["pre"])}</td><td>{sgn(r["post"])}</td><td>{sgn(r["chg"])}</td></tr>'
        for r in BRK)
    return ('<table><thead><tr><th>Feature</th><th>Jun 2025 – Feb 2026</th>'
            '<th>Mar – Sep 2026</th><th>Change</th></tr></thead><tbody>' + rows + "</tbody></table>")


# ------------------------------------------------------------ heatmap ----
FAMILIES = [
    ("Delivery", ["deliv_pct", "deliv_pct_sma_20", "deliv_pct_z_20"]),
    ("Long momentum and trend", ["ret_126d", "ret_63d", "mom_12_1", "ret_252d", "dist_200dma",
                                 "flag_below_200dma", "macd_norm", "dist_sma_50"]),
    ("52-week range", ["dist_52w_high", "dist_52w_low", "flag_near_52w_low"]),
    ("Volatility and range", ["atr_pct", "vol_20", "vol_10", "vol_5", "range_pct", "vol_ratio_20"]),
    ("Liquidity and data flags", ["log_turnover", "flag_split_20d"]),
    ("Short horizon (20 sessions or less)", ["mom_20", "rsi_14", "mom_10", "mom_5", "dist_sma_20",
                                             "dist_sma_10", "dist_sma_5", "rsi_2", "ret_1d",
                                             "gap_pct", "close_pos_in_range", "vol_z_20"]),
]
covered = {m for _, fs in FAMILIES for f in fs for m in members(f)}
assert covered == set(IC), sorted(set(IC) ^ covered)

SHORT = dict(FAMILIES)["Short horizon (20 sessions or less)"]
dead_short = [f for f in SHORT if abs(IC[f]["t_stat"]) < 1 and not is_champ(f)]


def bucket(v: float | None) -> str:
    if v is None:
        return "na"
    a = abs(v)
    step = 0 if a < 0.02 else 1 if a < 0.06 else 2 if a < 0.10 else 3
    return "hm-0" if step == 0 else f"hm-{'p' if v > 0 else 'n'}{step}"


def mon(m: str) -> str:
    return datetime.strptime(m, "%Y-%m").strftime("%b")


def heatmap() -> str:
    years: dict[str, int] = {}
    for m in MONTHS:
        years[m[:4]] = years.get(m[:4], 0) + 1
    pre_cv = [m for m in MONTHS if m < CV_MONTHS[0]]
    h1 = ('<tr><th rowspan="3" class="fcol">Feature</th>'
          + "".join(f'<th colspan="{n}" class="yr">{y}</th>' for y, n in years.items())
          + '<th rowspan="3" class="sumh">Mean</th><th rowspan="3" class="sumh">t</th>'
            '<th rowspan="3" class="sumh">Same sign</th></tr>')
    h2 = (f'<tr><th colspan="{len(pre_cv)}" class="ph">before CV</th>'
          f'<th colspan="{len(CV_MONTHS)}" class="ph ph-cv">CV folds</th>'
          f'<th colspan="{len(HOLDOUT_MONTHS)}" class="ph ph-ho">holdout</th></tr>')
    h3 = "<tr>" + "".join(f'<th class="mo{" brk" if m == BREAK else ""}">{mon(m)}</th>'
                          for m in MONTHS) + "</tr>"
    body = []
    ncol = 1 + len(MONTHS) + 3
    for fam, feats in FAMILIES:
        body.append(f'<tr class="fam"><th colspan="{ncol}" scope="colgroup">{E(fam)}</th></tr>')
        for f in feats:
            v = IC[f]
            star = '<span class="star" aria-label="champion feature">★</span> ' if is_champ(f) else ""
            cells = []
            for m in MONTHS:
                x = v["monthly_ic"].get(m)
                cls = bucket(x) + (" brk" if m == BREAK else "")
                if x is None:
                    cells.append(f'<td class="{cls}">·</td>')
                else:
                    tip = f"{label(f)} · {m}: IC {sgn(x)}"
                    cells.append(f'<td class="{cls}" data-tip="{E(tip)}">'
                                 f'{str(round(x * 100)).replace("-", MINUS)}</td>')
            t = v["t_stat"]
            tcls = "sum strong" if abs(t) >= 2 else "sum"
            body.append(
                f'<tr><th scope="row">{star}{E(label(f))}</th>{"".join(cells)}'
                f'<td class="sum">{sgn(v["mean_ic"] * 100, 1)}</td>'
                f'<td class="{tcls}">{sgn(t, 2)}</td>'
                f'<td class="sum">{months_same_sign(v)}/{v["n_months"]}</td></tr>')
    return (f'<table class="heat"><thead>{h1}{h2}{h3}</thead><tbody>{"".join(body)}</tbody></table>')


HM_KEY = (
    '<div class="hm-key" aria-hidden="true">IC × 100:&nbsp;'
    '<span class="sw hm-n3"></span>≤ −10 <span class="sw hm-n2"></span>−6 '
    '<span class="sw hm-n1"></span>−2 <span class="sw hm-0"></span>within ±2 '
    '<span class="sw hm-p1"></span>+2 <span class="sw hm-p2"></span>+6 '
    '<span class="sw hm-p3"></span>≥ +10</div>')

# ------------------------------------------------------- monotonicity ----
MONO_ORDER = ["deliv_pct", "deliv_pct_sma_20", "dist_52w_high", "ret_126d", "ret_63d",
              "mom_12_1", "cs_rank_mom_20", "atr_pct", "cs_rank_vol_20"]
assert mono["ret_126d"]["decile_mean_y_excess"] == mono["cs_rank_ret_126"]["decile_mean_y_excess"]
SHAPE = {"monotone_up": "monotone", "u_shape": "U-shape", "hump": "hump", "noisy": "noisy"}
YMAX = math.ceil(max(max(mono[f]["decile_mean_y_excess"]) for f in MONO_ORDER) * 200) / 200
vol_dec = mono["cs_rank_vol_20"]["decile_mean_y_excess"]
atr_dec = mono["atr_pct"]["decile_mean_y_excess"]
atr_peak = max(range(10), key=lambda i: atr_dec[i]) + 1


def mini(f: str) -> str:
    d = mono[f]["decile_mean_y_excess"]
    x0, x1, yb, yt = 30, 196, 112, 14
    slot = (x1 - x0) / 10

    def Y(v: float) -> float:
        return yb - v / YMAX * (yb - yt)

    name = "ret_126d · cs_rank_ret_126" if f == "ret_126d" else f
    p = [f'<svg viewBox="0 0 200 134" role="img" aria-label="{E(name)}: mean 20-day excess '
         f'return by decile">']
    tick = 0.01
    while tick <= YMAX + 1e-9:
        p.append(f'<line x1="{x0}" y1="{Y(tick):.1f}" x2="{x1}" y2="{Y(tick):.1f}" class="grid"/>')
        p.append(f'<text x="{x0 - 5}" y="{Y(tick) + 3.5:.1f}" class="ax ax-s" text-anchor="end">'
                 f'{tick * 100:.0f}%</text>')
        tick = round(tick + 0.01, 2)
    p.append(f'<line x1="{x0}" y1="{yb}" x2="{x1}" y2="{yb}" class="axisln"/>')
    p.append(f'<text x="{x0 - 5}" y="{yb + 3.5}" class="ax ax-s" text-anchor="end">0</text>')
    for i, v in enumerate(d):
        xc = x0 + slot * (i + 0.5)
        path = vbar(xc, 11, Y(0), Y(v))
        tip = f"{name} · D{i + 1}: {pts(v)}%"
        p.append(f'<path d="{path}" fill="var(--s1)" data-tip="{E(tip)}"/>')
    for i in (0, 9):
        xc = x0 + slot * (i + 0.5)
        p.append(f'<text x="{xc:.1f}" y="{Y(d[i]) - 5:.1f}" class="val ax-s" text-anchor="middle">'
                 f'{d[i] * 100:.1f}</text>')
    p.append(f'<text x="{x0 + slot / 2:.1f}" y="{yb + 15}" class="ax ax-s" text-anchor="middle">D1</text>')
    p.append(f'<text x="{x1 - slot / 2:.1f}" y="{yb + 15}" class="ax ax-s" text-anchor="middle">D10</text>')
    p.append("</svg>")
    m = mono[f]
    k = round(m["pct_months_spread_positive"] * m["n_months"])
    star = '<span class="star">★</span> '
    return (f'<figure class="mini"><figcaption><b>{star}{E(name)}</b>'
            f'<span>{SHAPE.get(m["shape"], m["shape"])} · spread {pts(m["pooled_top_bottom_spread"], 1)} pts</span>'
            f'<span>spread positive in {k} of {m["n_months"]} months</span></figcaption>'
            f'{"".join(p)}</figure>')


def mono_table() -> str:
    head = "".join(f"<th>D{i}</th>" for i in range(1, 11))
    rows = "".join(
        f'<tr><td class="mname">{E(f)}</td>'
        + "".join(f"<td>{x * 100:.1f}</td>" for x in mono[f]["decile_mean_y_excess"])
        + f'<td>{SHAPE.get(mono[f]["shape"], mono[f]["shape"])}</td></tr>'
        for f in MONO_ORDER)
    return (f'<table><thead><tr><th>Feature</th>{head}<th>Shape</th></tr></thead>'
            f'<tbody>{rows}</tbody></table>')


# -------------------------------------------------------- interactions ----
INTER = [
    ("cs_rank_vol_20_x_mom_12_1", "mom_12_1", "cs_rank_vol_20", "test", "Retest on 5 years"),
    ("deliv_pct_sma_20_x_mom_12_1", "mom_12_1", "deliv_pct_sma_20", "drop", "Do not build"),
    ("dist_52w_high_x_cs_rank_mom_20", "cs_rank_mom_20", "dist_52w_high", "drop",
     "Skip: inconsistent"),
    ("atr_pct_x_deliv_pct_z_20", "deliv_pct_z_20", "atr_pct", "drop", "Skip: small"),
]


def seq_bucket(v: float) -> str:
    pct = v * 100
    return ("hm-0" if pct < 0.5 else "hm-p1" if pct < 1.5 else "hm-p2" if pct < 2.5
            else "hm-p3" if pct < 3.5 else "hm-p4")


def grid_card(key: str, rowf: str, colf: str, cls: str, verdict_txt: str) -> str:
    ix = interaction(key)
    assert ix["axis"]["rows"].startswith(rowf) and ix["axis"]["cols"].startswith(colf), key
    g = ix["grid"]
    terc = ["low", "mid", "high"]
    head = "".join(f"<th>{t}</th>" for t in terc)

    def cell(i: int, j: int) -> str:
        tip = E(f"{rowf} {terc[i]} × {colf} {terc[j]}: {pts(g[i][j])}%")
        return f'<td class="{seq_bucket(g[i][j])}" data-tip="{tip}">{pts(g[i][j])}</td>'

    body = "".join(f'<tr><th scope="row">{terc[i]}</th>' + "".join(cell(i, j) for j in range(3))
                   + "</tr>" for i in range(3))
    stat = (f'Moving {E(rowf)} from low to high adds {pts(ix["hi"])} points when {E(colf)} is high '
            f'and {pts(ix["lo"])} when it is low. Same direction in {ix["k"]} of {ix["n"]} months. '
            f'Largest cell gap from an additive fit: {ix["dev"] * 100:.2f} points.')
    return (f'<div class="card gcard"><div class="ghead"><h4>{E(rowf)} × {E(colf)}</h4>'
            f'<span class="act {cls}">{E(verdict_txt)}</span></div>'
            f'<p class="axisnote">Rows: {E(rowf)} tercile · Columns: {E(colf)} tercile</p>'
            f'<div class="scroll"><table class="grid3"><thead><tr>'
            f'<th class="corner"></th>{head}</tr></thead>'
            f'<tbody>{body}</tbody></table></div><p class="cap">{stat}</p></div>')


# ----------------------------------------------------------- liquidity ----
LIQ = [("composite_top10", "Champion composite"), ("deliv_pct_sma_20", "deliv_pct_sma_20"),
       ("mom_12_1", "mom_12_1")]
TERC = [("illiquid", "least liquid third"), ("mid", "middle third"), ("liquid", "most liquid third")]
liq_t = liq["ic_by_turnover_tercile"]
comp = liq_t["composite_top10"]
absx = liq["mean_abs_y_excess_by_tercile"]


def liq_chart() -> str:
    W, L, R = 760, 210, 590
    rh, gh, gap = 26, 30, 16
    H = 24 + len(LIQ) * (gh + rh * 3) + (len(LIQ) - 1) * gap + 30
    lo, hi = 0.0, 0.11

    def X(v: float) -> float:
        return L + (v - lo) / (hi - lo) * (R - L)

    p = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Monthly IC by turnover third">']
    for t in (0.02, 0.04, 0.06, 0.08, 0.10):
        p.append(f'<line x1="{X(t):.1f}" y1="14" x2="{X(t):.1f}" y2="{H - 30}" class="grid"/>')
        p.append(f'<text x="{X(t):.1f}" y="{H - 12}" class="ax" text-anchor="middle">{t:.2f}</text>')
    p.append(f'<line x1="{X(0):.1f}" y1="14" x2="{X(0):.1f}" y2="{H - 30}" class="axisln"/>')
    p.append(f'<text x="{X(0):.1f}" y="{H - 12}" class="ax" text-anchor="middle">0</text>')
    y = 24
    for gi, (key, name) in enumerate(LIQ):
        if gi:
            y += gap
        n_m = liq_t[key]["illiquid"]["n_months"]
        p.append(f'<text x="0" y="{y + 14}" class="colh">{E(name)}'
                 f'{"" if n_m == 16 else f" ({n_m} months of data)"}</text>')
        y += gh
        for tk, tname in TERC:
            v = liq_t[key][tk]
            yc = y + rh / 2
            k = round(v["pct_months_same_sign"] * v["n_months"])
            tip = f"{name}, {tname}: mean monthly IC {v['mean_monthly_ic']:.3f}, same sign {k} of {v['n_months']} months"
            p.append(f'<g data-tip="{E(tip)}"><rect x="0" y="{y:.1f}" width="{W}" height="{rh}" fill="transparent"/>')
            p.append(f'<text x="{L - 12}" y="{yc + 4:.1f}" class="lbl" text-anchor="end">{tname}</text>')
            p.append(f'<path d="{hbar(X(0), X(v["mean_monthly_ic"]), yc, 16)}" fill="var(--s1)"/></g>')
            p.append(f'<text x="{X(v["mean_monthly_ic"]) + 8:.1f}" y="{yc + 4:.1f}" class="val">'
                     f'{v["mean_monthly_ic"]:.3f}<tspan class="ax"> · {k} of {v["n_months"]} months</tspan></text>')
            y += rh
    p.append("</svg>")
    return "".join(p)


# ----------------------------------------------------------- decisions ----
cs_mom = IC["cs_rank_mom_20"]
DECISIONS = [
    ("The champion's 10 features",
     f"Best engineered variant {BEST['cv']:.4f} against the champion's {AB[0]['cv']:.4f}. "
     f"The pass mark was {PASS:.4f}.", "keep", "Keep for now"),
    ("Feature selection",
     f"The volatility signs and cs_rank_mom_20's sign (same sign in {months_same_sign(cs_mom)} of "
     f"{cs_mom['n_months']} months) were set by one regime. mom_12_1 and ret_252d had only "
     f"{IC['mom_12_1']['n_months']} months of data.", "proto", "Re-run on 5 years before freezing"),
    ("Delivery features",
     f"Most consistent signal ({months_same_sign(deliv)} of {deliv['n_months']} months), but its IC "
     f"fell from {sgn(mean_over('deliv_pct', PRE))} to {sgn(mean_over('deliv_pct', POST))} after "
     f"March 2026.", "keep", "Keep, with a rolling-IC alert"),
    ("Market-state inputs",
     f"Momentum IC {sgn(state['mom_12_1']['up_dates']['mean_ic'])} on rising days against "
     f"{sgn(state['mom_12_1']['down_dates']['mean_ic'])} otherwise. In the 6-month A/B they cut "
     f"the holdout AUC to {regime_ho:.4f}.", "test", "Test on 5 years"),
    ("mom_12_1 × cs_rank_vol_20",
     f"Momentum adds {pts(ix_vol['hi'])} points at high volatility and {pts(ix_vol['lo'])} at low, "
     f"in the same direction in {ix_vol['k']} of {ix_vol['n']} months.", "test", "Test on 5 years"),
    ("Listing age",
     f"Within-month premium of {pts(age['mean_monthly_gap'])} points a month (t = "
     f"{age['monthly_gap_t_stat']:.2f}). The current proxy is confounded by the database start.",
     "test", "Build from real listing dates"),
    ("Top-decile volatility flag",
     f"The most volatile tenth returns {pts(vol_dec[9], 1)}% against {pts(vol_dec[8], 1)}% for "
     f"the ninth.", "add", "Linear and neural models only"),
    ("log1p on volatility features, ranks on raw returns",
     f"atr_pct skew {dist['atr_pct']['skew']:.0f} and excess kurtosis about "
     f"{round(dist['atr_pct']['excess_kurtosis'], -2):,.0f}. Up to {clip_max * 100:.1f}% of rows "
     f"are clipped by the 1/99 winsorization.", "add", "Linear and neural models only"),
    ("A full rank layer",
     f"Ranking the champion's features changes their monthly |t| by {sgn(min(rank_gain), 2)} to "
     f"{sgn(max(rank_gain), 2)}. A logistic model on ranks alone scored {lr_rank['cv']:.4f}.",
     "drop", "Do not build"),
    ("deliv_pct_sma_20 × mom_12_1",
     f"They act as substitutes. Momentum adds {pts(ix_del['lo'])} points among low-delivery stocks "
     f"and {pts(ix_del['hi'])} among high-delivery stocks.", "drop", "Do not build"),
    ("Short-horizon features",
     f"{len(dead_short)} have |t| below 1 over {deliv['n_months']} months.", "drop",
     "Leave out of new builds"),
    ("Calendar and seasonality features",
     "The 2026 archive served copies of the previous day on 12 holidays (now removed), so its "
     "calendar needs a full audit before seasonality can be trusted.", "drop", "Do not build yet"),
    ("20-day horizon and monthly retraining",
     f"Daily IC autocorrelation is at or above what the 20-day label overlap explains "
     f"(lag 1: {lab['mom_12_1_daily_ic_autocorr']['lag_1']:.2f}), so the signal does not decay "
     f"within a month.", "keep", "Keep"),
]


def decisions_table() -> str:
    rows = "".join(
        f'<tr><td class="mname wrapcell">{E(item)}</td><td class="wrapcell ev">{E(ev)}</td>'
        f'<td><span class="act {cls}">{E(dec)}</span></td></tr>'
        for item, ev, cls, dec in DECISIONS)
    return ('<table class="dec"><thead><tr><th class="wrapcell">Item</th><th class="wrapcell">Evidence</th>'
            '<th>Decision</th></tr></thead><tbody>' + rows + "</tbody></table>")


# ----------------------------------------------------------------- page ----
CSS = """
/* Layout: one reading column of evidence cards on a soft page plane; serif prose,
   sans headings and data. Tokens shared with the pilot report. */
:root{
  --bg:#f9f9f7; --surface:#fcfcfb; --ink:#161513; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axisc:#c3c2b7; --border:rgba(11,11,11,.10);
  --accent:#9a5b00; --accent-soft:rgba(154,91,0,.10);
  --s1:#2a78d6; --ctrl:#9a5b00;
  --good:#006300; --bad:#b32e2e;
  --hm-n3:#f4b6b5; --hm-n2:#f8cfce; --hm-n1:#fbe4e3; --hm-0:#f0efec;
  --hm-p1:#ddecfb; --hm-p2:#bcd6f7; --hm-p3:#9ec5f4; --hm-p4:#6da7ec;
  --serif:Charter,"Iowan Old Style","Source Serif 4",Georgia,"Times New Roman",serif;
  --sans:system-ui,-apple-system,"Segoe UI",sans-serif;
  --mono:ui-monospace,"SF Mono",Menlo,Consolas,monospace;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --bg:#0d0d0d; --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --muted:#898781;
    --grid:#2c2c2a; --axisc:#383835; --border:rgba(255,255,255,.12);
    --accent:#e8a33d; --accent-soft:rgba(232,163,61,.12);
    --s1:#3987e5; --ctrl:#c98500;
    --good:#0ca30c; --bad:#e66767;
    --hm-n3:#7e2a29; --hm-n2:#5d2423; --hm-n1:#402020; --hm-0:#262624;
    --hm-p1:#1a2c45; --hm-p2:#17395f; --hm-p3:#1c4d8c; --hm-p4:#2a6cc0;
    color-scheme:dark;
  }
}
:root[data-theme="dark"]{
  --bg:#0d0d0d; --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axisc:#383835; --border:rgba(255,255,255,.12);
  --accent:#e8a33d; --accent-soft:rgba(232,163,61,.12);
  --s1:#3987e5; --ctrl:#c98500;
  --good:#0ca30c; --bad:#e66767;
  --hm-n3:#7e2a29; --hm-n2:#5d2423; --hm-n1:#402020; --hm-0:#262624;
  --hm-p1:#1a2c45; --hm-p2:#17395f; --hm-p3:#1c4d8c; --hm-p4:#2a6cc0;
  color-scheme:dark;
}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--ink);font:16.5px/1.55 var(--serif);-webkit-text-size-adjust:100%}
.wrap{max-width:1060px;margin-inline:auto;
  padding-left:max(16px,env(safe-area-inset-left,0px));
  padding-right:max(16px,env(safe-area-inset-right,0px));
  padding-block:0 56px}
h1,h2,h3,h4{font-family:var(--sans);line-height:1.15;text-wrap:balance;margin:0}
p{margin:.55em 0;max-width:70ch}
a{color:var(--accent)}
a:focus-visible,summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
td,th{font-variant-numeric:tabular-nums}
.hero{padding-block:44px 6px}
.eyebrow,.sec-eyebrow{font:700 12px/1 var(--sans);letter-spacing:.14em;text-transform:uppercase;color:var(--accent)}
.hero h1{font-size:clamp(28px,5vw,44px);font-weight:800;letter-spacing:-.02em;margin:.3em 0 .25em}
.hero .sub{color:var(--ink2);font-size:17px;max-width:72ch}
.verdict{margin-top:20px;background:var(--accent-soft);border-radius:10px;padding:16px 18px}
.verdict .vhead{font:700 12px/1 var(--sans);letter-spacing:.12em;text-transform:uppercase;color:var(--accent)}
.verdict p{font-family:var(--sans);font-size:17px;font-weight:600;margin:.45em 0 .35em;max-width:none}
.kv{display:flex;flex-wrap:wrap;gap:6px 18px;font:13.5px var(--sans);color:var(--ink2)}
.kv b{color:var(--ink)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin-top:14px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px;min-width:0}
.tile .v{font:700 28px/1.15 var(--sans);letter-spacing:-.01em}
.tile .v small{font-size:16px;font-weight:600;color:var(--muted)}
.tile .k{font:600 12px/1.3 var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--ink2);margin-top:6px}
.tile .d{font:400 13.5px/1.45 var(--sans);color:var(--muted);margin-top:6px}
section{margin-top:46px}
section>h2{font-size:clamp(21px,3vw,27px);font-weight:750;letter-spacing:-.015em;margin:.3em 0 .35em}
h3{font-size:16.5px;margin-top:22px}
.lede{color:var(--ink2)}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;margin-top:14px;min-width:0}
.cap{font:400 13.5px/1.55 var(--sans);color:var(--muted);margin:10px 4px 2px;max-width:none}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.wide{min-width:640px}
svg{display:block;width:100%;height:auto}
svg text{font-family:var(--sans)}
.ax{font-size:12px;fill:var(--muted)}
.ax-s{font-size:10.5px}
.lbl{font-size:12.5px;fill:var(--ink2)}
.lbl-em{font-size:12.5px;font-weight:700;fill:var(--ink)}
.val{font-size:12.5px;font-weight:600;fill:var(--ink2)}
.colh{font-size:13px;font-weight:700;fill:var(--ink)}
.grid{stroke:var(--grid);stroke-width:1}
.axisln{stroke:var(--axisc);stroke-width:1.2}
.chance{stroke:var(--axisc);stroke-width:1.4;stroke-dasharray:5 4}
.passln{stroke:var(--ink2);stroke-width:1.5;stroke-dasharray:6 4}
.legend{list-style:none;display:flex;flex-wrap:wrap;gap:6px 18px;margin:10px 4px 0;padding:0;font:13px var(--sans);color:var(--ink2)}
.legend li{display:flex;align-items:center;gap:7px}
.dot{width:12px;height:12px;border-radius:50%;flex:none}
.dot.hollow{background:var(--surface);border:2px solid var(--muted)}
.dot.hollow.s1{border-color:var(--s1)}
table{border-collapse:collapse;width:100%;font-family:var(--sans);font-size:13.5px}
th,td{padding:7px 9px;text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
thead th{font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);border-bottom:1.5px solid var(--axisc)}
tbody tr{border-bottom:1px solid var(--grid)}
tbody tr:last-child{border-bottom:none}
.mname{font-weight:600}
.dim2{color:var(--muted);font-weight:400}
.wrapcell{white-space:normal;text-align:left;min-width:220px}
tr.champ td{background:var(--accent-soft)}
tr.champ .mname{color:var(--accent)}
td.pos{color:var(--good)} td.neg{color:var(--bad)}
.hm-n3{background:var(--hm-n3)} .hm-n2{background:var(--hm-n2)} .hm-n1{background:var(--hm-n1)}
.hm-0{background:var(--hm-0)} .hm-p1{background:var(--hm-p1)} .hm-p2{background:var(--hm-p2)}
.hm-p3{background:var(--hm-p3)} .hm-p4{background:var(--hm-p4)}
table.heat{border-collapse:separate;border-spacing:2px;font-size:12px;width:auto;min-width:100%}
table.heat thead th{text-align:center;padding:3px 2px;border-bottom:none;font-size:10.5px}
table.heat thead th.fcol{text-align:left;vertical-align:bottom}
table.heat th.yr{color:var(--ink2);font-weight:700}
table.heat th.ph{font-weight:600;letter-spacing:.04em;text-transform:none;font-size:11px;border-top:1.5px solid var(--axisc)}
table.heat th.ph-cv,table.heat th.ph-ho{color:var(--ink);font-weight:700}
table.heat th.mo{text-transform:none;letter-spacing:0;font-size:11px;color:var(--ink2)}
table.heat th.sumh{vertical-align:bottom;min-width:48px}
table.heat td{text-align:center;min-width:34px;padding:5px 2px;font-weight:600;color:var(--ink)}
table.heat td.na{background:transparent;color:var(--muted);font-weight:400}
table.heat td.sum{background:transparent;color:var(--ink2);font-weight:500;padding-inline:6px}
table.heat td.sum.strong{color:var(--ink);font-weight:700}
table.heat .brk{box-shadow:inset 3px 0 0 var(--ink2)}
table.heat tbody th{text-align:left;font-weight:500;font-size:12.5px;color:var(--ink2);padding:4px 10px 4px 2px}
table.heat tbody tr{border:none}
table.heat tr.fam th{font:700 11px/1 var(--sans);letter-spacing:.09em;text-transform:uppercase;color:var(--accent);padding:14px 2px 4px}
.star{color:var(--accent)}
.hm-key{display:flex;flex-wrap:wrap;gap:6px;align-items:center;font:12px var(--sans);color:var(--muted);margin:12px 4px 0}
.hm-key .sw{display:inline-block;width:24px;height:13px;border-radius:3px;margin-left:6px}
.minis{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px 20px}
.mini{margin:0;min-width:0}
.mini figcaption{font:12.5px/1.35 var(--sans);color:var(--ink2);margin-bottom:4px}
.mini figcaption b{display:block;color:var(--ink);font-size:13px}
.mini figcaption span{display:block;color:var(--muted)}
.cols2{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px;margin-top:14px}
.cols2.two{grid-template-columns:repeat(auto-fit,minmax(min(100%,400px),1fr))}
.cols2>.card{margin-top:0}
.axisnote{font:12px/1.4 var(--sans);color:var(--muted);margin:0 2px 6px;max-width:none}
.panel h3{margin:0 0 6px}
.panel p{font-size:15px;max-width:none}
.tag{font:700 11px/1 var(--sans);letter-spacing:.09em;text-transform:uppercase;padding:4px 9px;border-radius:999px;display:inline-block;margin-bottom:8px}
.tag.keep{background:var(--hm-p1);color:var(--s1)}
.tag.warn{background:var(--accent-soft);color:var(--accent)}
.tag.drop{background:var(--hm-n1);color:var(--bad)}
.gcard .ghead{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:center;gap:8px;margin-bottom:8px}
.gcard h4{font-size:14px}
table.grid3{border-collapse:separate;border-spacing:2px;width:auto}
table.grid3 thead th{text-align:center;border-bottom:none;padding:4px 6px}
table.grid3 thead th.corner{text-align:left;text-transform:none;letter-spacing:0;font-size:11px;white-space:normal;max-width:150px}
table.grid3 tbody th{font:600 11.5px var(--sans);color:var(--muted);text-transform:uppercase;letter-spacing:.06em;padding-right:10px}
table.grid3 td{text-align:center;min-width:66px;padding:9px 6px;font-weight:600;color:var(--ink)}
table.grid3 tbody tr{border:none}
.act{font:700 11px/1.3 var(--sans);letter-spacing:.05em;text-transform:uppercase;border-radius:999px;padding:4px 10px;white-space:nowrap;display:inline-block}
.act.keep{background:var(--accent-soft);color:var(--accent)}
.act.test,.act.add{background:var(--hm-p1);color:var(--s1)}
.act.drop{background:var(--hm-n1);color:var(--bad)}
.act.proto{background:var(--bg);border:1px solid var(--border);color:var(--ink2)}
table.dec td{vertical-align:top}
table.dec td.ev{color:var(--ink2);font-size:13px;min-width:280px}
details{margin-top:10px}
summary{cursor:pointer;font:600 13.5px var(--sans);color:var(--accent);padding:4px}
ul.steps{padding-left:20px;margin:10px 0}
ul.steps li{margin:8px 0;max-width:72ch}
footer{margin-top:52px;border-top:1px solid var(--grid);padding-top:14px;font:12.5px/1.6 var(--sans);color:var(--muted)}
footer code{font-family:var(--mono);font-size:12px}
#tip{position:fixed;z-index:50;max-width:320px;background:var(--ink);color:var(--bg);
  font:12.5px/1.45 var(--sans);padding:7px 10px;border-radius:7px;pointer-events:none;
  opacity:0;transform:translateY(3px);transition:opacity .12s;white-space:normal}
#tip.on{opacity:.97}
@media (prefers-reduced-motion:reduce){*{transition:none !important}}
@media (max-width:560px){.minis{grid-template-columns:1fr}}
@media (max-width:480px){.hero{padding-top:30px}.tile .v{font-size:24px}th,td{padding:6px 7px}}
"""

JS = """
(function(){
  var tip=document.getElementById('tip');
  function move(e){var x=e.clientX+14,y=e.clientY+14,r=tip.getBoundingClientRect();
    if(x+r.width>window.innerWidth-8)x=e.clientX-r.width-10;
    if(y+r.height>window.innerHeight-8)y=e.clientY-r.height-10;
    tip.style.left=x+'px';tip.style.top=y+'px';}
  function show(e,t){tip.textContent=t;tip.classList.add('on');move(e);}
  function hide(){tip.classList.remove('on');}
  document.addEventListener('pointerover',function(e){
    var el=e.target.closest('[data-tip]');if(el)show(e,el.getAttribute('data-tip'));});
  document.addEventListener('pointermove',function(e){
    if(tip.classList.contains('on'))move(e);
    if(!e.target.closest('[data-tip]'))hide();});
  document.addEventListener('pointerdown',function(e){
    var el=e.target.closest('[data-tip]');
    if(el){show(e,el.getAttribute('data-tip'));setTimeout(hide,2600);}});
})();
"""


def page() -> str:
    today = datetime.now()
    pre_n, post_n = len(PRE), len(POST)
    terc_lo, terc_mid, terc_hi = (comp[t]["mean_monthly_ic"] for t in ("illiquid", "mid", "liquid"))
    liquid_k = round(comp["liquid"]["pct_months_same_sign"] * comp["liquid"]["n_months"])
    dl = liq_t["deliv_pct_sma_20"]
    sp = state["deliv_pct_sma_20"]
    mom_trend = ["ret_126d", "ret_63d", "mom_12_1", "dist_52w_high"]
    ho_mom = sum(mean_over(f, HOLDOUT_MONTHS) for f in mom_trend) / len(mom_trend)
    cv_mom = sum(mean_over(f, CV_MONTHS) for f in mom_trend) / len(mom_trend)
    vol_k = "vol_20"
    best = BEST
    return f"""<meta charset="utf-8">
<title>SuryaDhana Feature Study</title>
<meta name="claude:viewport-fit-sides" content="cover">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>{CSS}</style>
<div class="wrap">

<header class="hero">
  <div class="eyebrow">SuryaDhana · NSE EOD universe · feature study</div>
  <h1>Do the features need a rebuild before the 5-year run?</h1>
  <p class="sub">Before scaling the pilot to five years of data, we checked whether its features need
  rebuilding or fine-tuning. An exploratory analysis measured how each feature relates to the next
  20-day excess return, month by month, across {META['rows_labeled_clean']:,} labelled rows and
  {META['n_dates']} trading dates. Then {n_new} new features were built without look-ahead and tested
  against the pilot champion in the same walk-forward harness, with the pass mark fixed before any
  result was seen.</p>
  <div class="verdict">
    <div class="vhead">Verdict · {today:%d %b %Y}</div>
    <p>No rebuild now. Keep LightGBM on the 10 selected features. All five engineered variants scored
    below it. The analysis does change how the 5-year run should select and monitor features, and the
    list of changes is at the end of this page.</p>
    <div class="kv"><span>Pass mark <b>CV AUC ≥ {PASS:.4f}</b></span>
    <span>Best variant <b>{best['cv']:.4f}</b></span><span>Rebuild <b>no</b></span></div>
  </div>
  <div class="tiles">
    <div class="tile"><div class="v">{best['cv']:.4f} <small>vs {AB[0]['cv']:.4f}</small></div>
      <div class="k">Best variant vs champion</div>
      <div class="d">Mean CV AUC. All five variants scored below the champion, and the best one dropped
      under 0.50 in one fold ({best['lo']:.4f}).</div></div>
    <div class="tile"><div class="v">{n_worst_break} of {len(IC)}</div>
      <div class="k">Features at their worst in March 2026</div>
      <div class="d">One regime break after a sharp sell-off. The volatility features changed sign.
      Delivery and 52-week-high kept their sign but lost most of their strength.</div></div>
    <div class="tile"><div class="v">{terc_mid:.3f}</div>
      <div class="k">Composite IC, mid-liquidity stocks</div>
      <div class="d">The champion's composite signal by turnover third is {terc_lo:.3f} for the least
      liquid, {terc_mid:.3f} for the middle and {terc_hi:.3f} for the most liquid. The edge does not
      depend on hard-to-trade names.</div></div>
  </div>
</header>

<section id="ab">
  <div class="sec-eyebrow">Engineered features</div>
  <h2>Every engineered variant scored below the 10-feature champion</h2>
  <p class="lede">Each variant uses the champion's LightGBM settings on the cleaned dataset, with the
  primary task beat_mkt_20d and the same purged walk-forward splits. The pass mark was set before the
  runs: beat the control by at least 0.005 in mean CV AUC, with no fold below 0.50.</p>
  <div class="card">
    <div class="scroll"><div class="wide">{ab_chart()}</div></div>
    <ul class="legend">
      <li><span class="dot" style="background:var(--ctrl)"></span>Champion (control), mean of 4 CV folds</li>
      <li><span class="dot" style="background:var(--s1)"></span>Engineered variant, mean of 4 CV folds</li>
      <li><span class="dot hollow s1"></span>Single fold</li>
    </ul>
    <div class="scroll" style="margin-top:12px">{ab_table()}</div>
    <p class="cap">The new features were strong one at a time. The best, {E(best_quick[0])}, had a
    cross-sectional IC of {sgn(best_quick[1]['mean_ic'])} at build time. Added to the model, they made
    it worse. The likely cause is redundancy, since {len(red)} of the new features correlate
    {red_lo:.2f} to {red_hi:.2f} with features the model already uses. The trees then split on
    near-copies and spread a fixed 300-tree budget thinner. The four market-state features did the most damage on the holdout
    ({regime_ho:.4f}). Four CV months hold too few regime changes for a tree model to learn when those
    features matter. A logistic model on the rank features alone reached {lr_rank['cv']:.4f}, below the
    pilot's logistic benchmark of {lr_bench['cv_auc_mean']:.4f}. These results come from a 6-month
    sample, so each idea is queued for a retest on five years of data.</p>
  </div>
</section>

<section id="regime">
  <div class="sec-eyebrow">What the analysis found</div>
  <h2>March 2026 changed which features work</h2>
  <p class="lede">IC here is the rank correlation between a feature and the next 20-day excess return
  across all stocks on a date, averaged over each month. In March 2026, after a sell-off that left the
  median stock down {abs(crash) * 100:.1f}% over 20 sessions, {n_worst_break} of the {len(IC)} base
  features had their worst month at once. The pilot's first CV fold was trained on data up to
  {FOLD1_TRAIN_END} and tested in April, so it learned the old relationships and was scored on the new
  ones. That is why April was the hardest fold for every model.</p>
  <div class="card">
    <h3 style="margin:2px 4px 8px">Average monthly IC before and after the break</h3>
    <ul class="legend" style="margin:0 4px 6px">
      <li><span class="dot hollow"></span>Jun 2025 – Feb 2026 · {pre_n} months</li>
      <li><span class="dot" style="background:var(--s1)"></span>Mar – Sep 2026 · {post_n} months</li>
    </ul>
    <div class="scroll"><div class="wide">{break_chart()}</div></div>
    <p class="cap">Bold rows contain one of the champion's 10 features. Of those 10, this chart covers
    {n_champ_on} ({', '.join(missing_champ)} has no data before March). Of the {n_champ_on},
    {n_weak} kept their sign and weakened, and {n_flip} changed sign.</p>
    <details><summary>Show as a table</summary><div class="scroll">{break_table()}</div></details>
  </div>
  <div class="cols2 two">
    <div class="card panel"><span class="tag keep">Most stable</span>
      <h3>Delivery is the most consistent signal, and it is fading</h3>
      <p>deliv_pct had a positive IC in {months_same_sign(deliv)} of {deliv['n_months']} months
      (t = {deliv['t_stat']:.2f}). It is the only feature whose average IC is larger than its
      month-to-month swing. deliv_pct_sma_20 held up on rising and falling market days alike
      ({sgn(sp['up_dates']['mean_ic'])} and {sgn(sp['down_dates']['mean_ic'])}). After the break both
      shrank: deliv_pct from {sgn(mean_over('deliv_pct', PRE))} to {sgn(mean_over('deliv_pct', POST))}
      a month on average, and deliv_pct_sma_20 from {sgn(mean_over('deliv_pct_sma_20', PRE))} to
      {sgn(mean_over('deliv_pct_sma_20', POST))}. Delivery is the champion's main non-price input, so
      production needs an alert on its rolling IC.</p></div>
    <div class="card panel"><span class="tag warn">Conditional</span>
      <h3>Momentum pays when the market is rising</h3>
      <p>mom_12_1 averaged an IC of {sgn(state['mom_12_1']['up_dates']['mean_ic'])} on days when the
      median stock was up over the past 20 sessions and {sgn(state['mom_12_1']['down_dates']['mean_ic'])}
      on the other days (t = {state['mom_12_1']['t_stat_diff']:.2f} for the gap). Its deciles are flat
      through the seventh, and the effect sits in the top three. Momentum is also stronger among
      volatile stocks. Moving from low to high momentum adds {pts(ix_vol['hi'])} points of 20-day excess
      return when volatility is high and {pts(ix_vol['lo'])} points when it is low, in the same direction
      in {ix_vol['k']} of {ix_vol['n']} months.</p></div>
    <div class="card panel"><span class="tag drop">Unstable</span>
      <h3>The volatility features change sign with the regime</h3>
      <p>atr_pct averaged {sgn(mean_over('atr_pct', PRE))} over the nine months to February 2026 and
      {sgn(mean_over('atr_pct', POST))} from March. {vol_k} moved from {sgn(mean_over(vol_k, PRE))} to
      {sgn(mean_over(vol_k, POST))}. The pilot's CV folds (April to July) saw only the positive phase,
      so the selection study gave these features a positive sign that a full cycle will not support.
      Market-state inputs such as the market's drawdown or the days since a sell-off might let a model
      learn when the sign flips. Testing that needs many regimes, so it waits for the 5-year data.</p></div>
    <div class="card panel"><span class="tag warn">Real, but confounded</span>
      <h3>Recently listed stocks earn a premium</h3>
      <p>Within the same month, stocks with less than a year of history beat seasoned stocks by
      {pts(age['mean_monthly_gap'])} points a month on average (positive in
      {round(age['pct_months_gap_positive'] * age['months_with_both_cohorts'])} of
      {age['months_with_both_cohorts']} months, t = {age['monthly_gap_t_stat']:.2f}). Pooled across all
      months the gap reverses to {pts(age['pooled_gap_young_minus_seasoned'])} points, because the pilot
      database starts in March 2025 and every stock looks new before March 2026. The pilot's proxy, a
      missing 252-day return, mixes the real effect with that artifact. The 5-year build should use real
      listing dates.</p></div>
  </div>
</section>

<section id="heatmap">
  <div class="sec-eyebrow">Monthly evidence</div>
  <h2>Monthly IC for every base feature</h2>
  <p class="lede">Values are IC × 100. Rows are grouped by family. Rank-transformed twins have identical
  rank ICs, so each pair shares a row. <span class="star">★</span> marks the champion's features. The
  vertical rule marks the March 2026 break.</p>
  <div class="card">
    <div class="scroll">{heatmap()}</div>
    {HM_KEY}
    <p class="cap">Delivery stays positive in almost every month. The volatility family changes sign at
    the break. In the two holdout months the long-momentum and 52-week-high features averaged an IC of
    {sgn(ho_mom, 2)}, against {sgn(cv_mom, 2)} in the four CV months. That friendly window is why nearly
    every model in the pilot scored better on the holdout than in CV. These short-horizon features have |t| below 1 across {deliv['n_months']} months and flip
    sign from month to month: {', '.join(dead_short)}. The champion's cs_rank_mom_20 does no better
    (t = {IC['cs_rank_mom_20']['t_stat']:.2f}) and is the first candidate to drop when selection is
    re-run.</p>
  </div>
</section>

<section id="shapes">
  <div class="sec-eyebrow">Shapes</div>
  <h2>How returns change across each feature's deciles</h2>
  <p class="lede">Mean 20-day excess return by decile, pooled over {deliv['n_months']} months, for the
  champion's features. ret_126d and cs_rank_ret_126 have identical deciles and share a chart. Each label
  gives the analysis' shape call, the top-minus-bottom spread and the number of months in which that
  spread was positive.</p>
  <div class="card">
    <div class="minis">{''.join(mini(f) for f in MONO_ORDER)}</div>
    <p class="cap">Delivery and 52-week-high rise steadily. The long-momentum features are convex, with
    most of their effect in the top two or three deciles. atr_pct peaks in decile {atr_peak} and falls
    back. cs_rank_vol_20 climbs to the ninth decile and then drops in the tenth
    ({pts(vol_dec[9], 1)}% against {pts(vol_dec[8], 1)}%), so the most volatile tenth of stocks
    underperforms. Trees pick up these shapes on their own. A linear model needs them spelled out, for
    example as a flag for the top volatility decile.</p>
    <details><summary>Show as a table</summary><div class="scroll">{mono_table()}</div></details>
  </div>

  <h3>Feature pairs</h3>
  <p class="lede">Mean 20-day excess return in % for each pair of terciles. Rows are the first feature,
  low to high, and columns the second.</p>
  <div class="cols2 two">{''.join(grid_card(*g) for g in INTER)}</div>
  <p class="cap">Delivery and momentum work as substitutes. Momentum adds {pts(ix_del['lo'])} points
  among low-delivery stocks and only {pts(ix_del['hi'])} among high-delivery stocks, so a combined
  feature would cut against both. Only the momentum and volatility pair is consistent enough to
  retest.</p>
</section>

<section id="liquidity">
  <div class="sec-eyebrow">Capacity</div>
  <h2>The signal does not depend on illiquid stocks</h2>
  <p class="lede">Monthly IC within each third of the universe by turnover, assigned per date. The
  composite averages the cross-sectional ranks of the champion's 10 features, with signs aligned. Next
  to each bar is the number of months in which that IC was positive.</p>
  <div class="card">
    <div class="scroll"><div class="wide">{liq_chart()}</div></div>
    <p class="cap">The composite is strongest in the middle third and still {terc_hi:.3f} in the most
    liquid third, although it holds its sign there in only {liquid_k} of {comp['liquid']['n_months']}
    months. Delivery weakens as liquidity rises but keeps about two thirds of its IC
    ({dl['illiquid']['mean_monthly_ic']:.3f} to {dl['liquid']['mean_monthly_ic']:.3f}). The spread of
    outcomes is the same in every third, with mean absolute excess return between
    {min(absx.values()) * 100:.1f}% and {max(absx.values()) * 100:.1f}%. Moving toward larger, more
    liquid names should keep most of the edge.</p>
  </div>
</section>

<section id="decisions">
  <div class="sec-eyebrow">Decisions</div>
  <h2>What to keep, build, transform and drop</h2>
  <div class="card"><div class="scroll">{decisions_table()}</div></div>
</section>

<section id="next">
  <div class="sec-eyebrow">For the 5-year run</div>
  <h2>Changes to the scale-up plan</h2>
  <ul class="steps">
    <li><b>Re-run feature selection on the full history</b> before freezing the feature set, starting
    from the pilot's 10.</li>
    <li><b>Report results by regime.</b> Label each month by market state, keep the worst-fold floor as a
    pass condition, and expect one or two months per cycle like March 2026.</li>
    <li><b>Run three separate A/Bs</b> against the re-selected baseline: market-state inputs, the momentum
    and volatility product, and listing age. Fix each pass mark before running it.</li>
    <li><b>Monitor delivery in production.</b> Track the rolling IC of the delivery features and the drift
    of every input.</li>
    <li><b>Keep the date-block significance test.</b> Daily ICs are close to fully dependent (lag-1
    autocorrelation {lab['mom_12_1_daily_ic_autocorr']['lag_1']:.2f}), so they are not independent
    samples.</li>
  </ul>
</section>

<footer>
  <p>Generated {today:%Y-%m-%d %H:%M} by <code>ml/make_feature_study.py</code>. Analysis:
  <code>ml/eda_features.py</code> ({META['rows_labeled_clean']:,} clean labelled rows,
  {META['n_dates']} dates, {META['n_months']} months; per-date Spearman IC against y_excess_20d).
  Engineered features: <code>ml/features_ext.py</code> ({n_new} features, checked for look-ahead by
  recomputing values from truncated history). A/B: <code>ml/feature_ab.py</code> (champion LightGBM
  settings, the pilot's walk-forward splits, seed 108). Companion to the
  <a href="{PILOT_URL}">pilot report</a> and <code>ml/MODEL_SELECTION.md</code>.</p>
</footer>

</div>
<div id="tip" role="status" aria-live="polite"></div>
<script>{JS}</script>
"""


if __name__ == "__main__":
    OUT.write_text(page())
    print(f"wrote {OUT} ({OUT.stat().st_size / 1024:.0f} KiB)")
