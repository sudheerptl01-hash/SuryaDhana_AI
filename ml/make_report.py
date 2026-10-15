"""Generate ml/report/index.html — the SuryaDhana 6-month pilot report.

Reads the frozen result JSONs and per-row prediction parquets under ml/results/,
computes only chart transforms (holdout ROC curves, champion decile bars), and
writes ONE self-contained HTML file (inline CSS/JS/SVG, no external fetches).

Run:  cd /home/user/SuryaDhana_AI && OMP_NUM_THREADS=2 python3 -m ml.make_report
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, roc_curve

ROOT = Path(__file__).resolve().parent          # ml/
RES = ROOT / "results"
OUT = ROOT / "report" / "index.html"

SEED = 108

# ---------------------------------------------------------------- load inputs

MS = json.loads((RES / "model_selection.json").read_text())
FS = json.loads((RES / "feature_selection.json").read_text())
DP = json.loads((RES / "data_profile.json").read_text())
HD = json.loads((RES / "holiday_duplicates.json").read_text())
LRC = json.loads((RES / "lr_coefficients.json").read_text())
TI = json.loads((RES / "tree_importances.json").read_text())
RL = json.loads((RES / "rl_reinforce__beat_mkt_20d.json").read_text())
MANIFEST = json.loads((ROOT / "data" / "manifest.json").read_text())

LEAGUE = {r["model"]: r for r in MS["league"]["beat_mkt_20d"]}
LEAGUE_UP = {r["model"]: r for r in MS["league"]["up_5d"]}
SIG = MS["significance"]["beat_mkt_20d"]["per_model"]
PAIRS = {p["b"]: p for p in MS["significance"]["beat_mkt_20d"]["pairwise"]
         if p["a"] == "lgbm_fs_selected"}
TENSION = MS["cv_holdout_tension"]
FOLDS = MS["protocol"]["cv_folds"]              # ['2026-04'..'2026-07']
WINDOWS = FOLDS + ["holdout"]

# display names ---------------------------------------------------------------
NICE = {
    "lgbm_fs_selected": "lgbm_fs_selected",
    "lgbm_fs_selected_clean": "lgbm_fs_selected · clean",
    "random_forest": "random_forest",
    "lr_l2": "lr_l2 (≈ l1 ≈ elastic)",
    "lr_l2_clean": "lr_l2 · clean",
    "lr_l1": "lr_l1",
    "lr_elastic": "lr_elastic",
    "rl_reinforce": "rl_reinforce",
    "decision_tree": "decision_tree",
    "lightgbm": "lightgbm (all 51)",
    "mlp": "mlp",
    "xgboost": "xgboost",
    "lstm": "lstm",
    "baseline_mom": "baseline_mom",
    "baseline_mom_clean": "baseline_mom · clean",
    "gru": "gru",
}
FAMILY = {
    "feature_selection": "GBM · selected",
    "linear": "linear", "trees": "trees", "deep": "deep",
    "rl": "RL", "baseline": "baseline",
}

# the memo's 11-row frozen league (lr_l1/elastic folded into lr_l2) + 3 clean
MAIN = ["lgbm_fs_selected", "random_forest", "lr_l2", "rl_reinforce",
        "decision_tree", "lightgbm", "mlp", "xgboost", "lstm",
        "baseline_mom", "gru"]
CLEAN_OF = {"lgbm_fs_selected": "lgbm_fs_selected_clean",
            "lr_l2": "lr_l2_clean", "baseline_mom": "baseline_mom_clean"}
HEAT = ["lgbm_fs_selected", "random_forest", "lr_l2", "lr_l1", "lr_elastic",
        "rl_reinforce", "decision_tree", "lightgbm", "mlp", "xgboost",
        "lstm", "baseline_mom", "gru"]       # the 13 frozen candidates

ROC_MODELS = ["lgbm_fs_selected", "lr_l2", "random_forest", "xgboost",
              "baseline_mom", "mlp", "rl_reinforce"]
ROC_SLOT = {m: i + 1 for i, m in enumerate(ROC_MODELS)}   # palette slots 1..7

# ------------------------------------------------------------- computed parts


def load_preds(model: str) -> pd.DataFrame:
    return pd.read_parquet(RES / "preds" / f"{model}__beat_mkt_20d.parquet")


def roc_points(model: str, max_pts: int = 200):
    """Holdout ROC curve, downsampled to <= max_pts, + AUC (checked vs JSON)."""
    df = load_preds(model)
    h = df[df["fold"] == "holdout"]
    auc = roc_auc_score(h["y"], h["score"])
    ref = LEAGUE[model]["holdout_auc"]
    assert abs(auc - ref) < 5e-4, f"{model}: computed {auc} vs frozen {ref}"
    fpr, tpr, _ = roc_curve(h["y"], h["score"])
    idx = np.unique(np.round(np.linspace(0, len(fpr) - 1, max_pts)).astype(int))
    return fpr[idx], tpr[idx], float(auc)


def champion_deciles():
    """Champion mean 20d excess return per score decile, per window."""
    df = load_preds("lgbm_fs_selected")
    out = {}
    for w in WINDOWS:
        f = df[df["fold"] == w]
        dec = pd.qcut(f["score"].rank(method="first"), 10, labels=False)
        means = f.groupby(dec)["fwd"].mean()
        out[w] = [float(means.loc[i]) for i in range(10)]
    # cross-check against the frozen harness numbers
    ref = LEAGUE["lgbm_fs_selected"]
    assert abs((out["holdout"][9] - out["holdout"][0]) - ref["holdout_decile_spread"]) < 1e-6
    assert abs(out["holdout"][9] - ref["holdout_top_decile_mean_fwd"]) < 1e-6
    return out


print("computing ROC curves + champion deciles ...")
ROC = {m: roc_points(m) for m in ROC_MODELS}
DECILES = champion_deciles()

# ------------------------------------------------------------------ utilities


def esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def a4(v): return f"{v:.4f}"
def a3(v): return f"{v:.3f}"
def pm(v, d=4): return f"{v:+.{d}f}"
def pct(v, d=2): return f"{v * 100:+.{d}f}%"
def pct_u(v, d=2): return f"{v * 100:.{d}f}%"


def lin(v, d0, d1, p0, p1):
    return p0 + (v - d0) / (d1 - d0) * (p1 - p0)


def resolve(ys, gap, lo, hi):
    """Nudge label y-positions apart (min gap), keeping order, within [lo,hi]."""
    order = sorted(range(len(ys)), key=lambda i: ys[i])
    pos = [ys[i] for i in order]
    for k in range(1, len(pos)):
        pos[k] = max(pos[k], pos[k - 1] + gap)
    over = pos[-1] - hi
    if over > 0:
        pos = [p - over for p in pos]
        for k in range(len(pos) - 2, -1, -1):
            pos[k] = min(pos[k], pos[k + 1] - gap)
        pos = [max(p, lo) for p in pos]
    out = [0.0] * len(ys)
    for k, i in enumerate(order):
        out[i] = pos[k]
    return out


def heat_class(auc: float) -> str:
    d = auc - 0.5
    if d <= -0.02: return "hm-n3"
    if d <= -0.01: return "hm-n2"
    if d < -0.002: return "hm-n1"
    if d <= 0.002: return "hm-0"
    if d <= 0.01: return "hm-p1"
    if d <= 0.03: return "hm-p2"
    if d <= 0.05: return "hm-p3"
    return "hm-p4"


# ================================================================ SVG charts =

def svg_ci_dots() -> str:
    """Pooled-CV AUC dot-and-whisker, every frozen model + clean reruns."""
    rows = sorted(HEAT, key=lambda m: -SIG[m]["pooled_cv_auc"])
    W, LPAD, RPAD, TOP, RH = 860, 190, 86, 34, 31
    H = TOP + RH * len(rows) + 14
    X0, X1 = LPAD, W - RPAD
    d0, d1 = 0.46, 0.55
    def X(v): return lin(v, d0, d1, X0, X1)
    p = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Pooled CV AUC with 95% bootstrap CIs per model">']
    for t in (0.46, 0.48, 0.50, 0.52, 0.54):
        x = X(t)
        p.append(f'<line x1="{x:.1f}" y1="{TOP - 6}" x2="{x:.1f}" y2="{H - 12}" class="grid"/>')
        p.append(f'<text x="{x:.1f}" y="{TOP - 12}" class="ax" text-anchor="middle">{t:.2f}</text>')
    xc = X(0.5)
    p.append(f'<line x1="{xc:.1f}" y1="{TOP - 6}" x2="{xc:.1f}" y2="{H - 12}" class="chance"/>')
    p.append(f'<text x="{xc + 5:.1f}" y="{H - 16}" class="ax accent">chance 0.50</text>')
    p.append(f'<text x="{W - RPAD + 10}" y="{TOP - 12}" class="ax">P(&gt;0.5)</text>')
    for i, m in enumerate(rows):
        s = SIG[m]
        y = TOP + RH * i + RH / 2
        lo, hi, v, pp = s["pooled_cv_auc_ci95"][0], s["pooled_cv_auc_ci95"][1], s["pooled_cv_auc"], s["p_pooled_cv_gt_chance"]
        col = "var(--s1)" if lo > 0.5 else ("var(--neg)" if hi < 0.5 else "var(--muted)")
        p.append(f'<text x="{LPAD - 10}" y="{y + 4:.1f}" class="lbl" text-anchor="end">{esc(NICE.get(m, m))}</text>')
        tip = f"{NICE.get(m, m)} — pooled CV AUC {a4(v)}, 95% CI [{a4(lo)}, {a4(hi)}], P(&gt;0.5)={pp:.3f}"
        p.append(f'<g data-tip="{esc(tip)}">'
                 f'<rect x="{X0}" y="{y - RH / 2:.1f}" width="{X1 - X0}" height="{RH}" fill="transparent"/>'
                 f'<line x1="{X(lo):.1f}" y1="{y:.1f}" x2="{X(hi):.1f}" y2="{y:.1f}" stroke="{col}" stroke-width="2"/>'
                 f'<line x1="{X(lo):.1f}" y1="{y - 4:.1f}" x2="{X(lo):.1f}" y2="{y + 4:.1f}" stroke="{col}" stroke-width="2"/>'
                 f'<line x1="{X(hi):.1f}" y1="{y - 4:.1f}" x2="{X(hi):.1f}" y2="{y + 4:.1f}" stroke="{col}" stroke-width="2"/>'
                 f'<circle cx="{X(v):.1f}" cy="{y:.1f}" r="5" fill="{col}" stroke="var(--surface)" stroke-width="2"/></g>')
        p.append(f'<text x="{W - RPAD + 10}" y="{y + 4:.1f}" class="val">{pp:.3f}</text>')
        cm = CLEAN_OF.get(m)
        if cm and cm in SIG:
            cs = SIG[cm]
            clo, chi, cv = cs["pooled_cv_auc_ci95"][0], cs["pooled_cv_auc_ci95"][1], cs["pooled_cv_auc"]
            ccol = "var(--s1)" if clo > 0.5 else ("var(--neg)" if chi < 0.5 else "var(--muted)")
            yy = y + 9
            ctip = f"{NICE[cm]} — pooled CV AUC {a4(cv)}, CI [{a4(clo)}, {a4(chi)}], P={cs['p_pooled_cv_gt_chance']:.3f}"
            p.append(f'<g data-tip="{esc(ctip)}">'
                     f'<line x1="{X(clo):.1f}" y1="{yy:.1f}" x2="{X(chi):.1f}" y2="{yy:.1f}" stroke="{ccol}" stroke-width="1.5" stroke-dasharray="3 3"/>'
                     f'<circle cx="{X(cv):.1f}" cy="{yy:.1f}" r="4" fill="var(--surface)" stroke="{ccol}" stroke-width="2"/></g>')
    p.append("</svg>")
    return "".join(p)


def svg_pair_deltas() -> str:
    """Champion-vs-X paired deltas: CV mean (filled) vs holdout (open)."""
    order = ["lr_l2", "random_forest", "xgboost", "lightgbm", "mlp",
             "rl_reinforce", "baseline_mom"]
    W, LPAD, RPAD, TOP, RH = 860, 190, 24, 34, 40
    H = TOP + RH * len(order) + 16
    X0, X1 = LPAD, W - RPAD
    d0, d1 = -0.062, 0.062
    def X(v): return lin(v, d0, d1, X0, X1)
    p = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Paired champion-minus-rival AUC deltas with 95% CIs, CV vs holdout">']
    for t in (-0.04, -0.02, 0.0, 0.02, 0.04):
        x = X(t)
        cls = "chance" if t == 0 else "grid"
        p.append(f'<line x1="{x:.1f}" y1="{TOP - 6}" x2="{x:.1f}" y2="{H - 14}" class="{cls}"/>')
        p.append(f'<text x="{x:.1f}" y="{TOP - 12}" class="ax" text-anchor="middle">{t:+.2f}</text>')
    p.append(f'<text x="{X(0.002):.1f}" y="{H - 4}" class="ax">champion better →</text>')
    p.append(f'<text x="{X(-0.002):.1f}" y="{H - 4}" class="ax" text-anchor="end">← rival better</text>')
    for i, m in enumerate(order):
        pr = PAIRS[m]
        y = TOP + RH * i + RH / 2
        p.append(f'<text x="{LPAD - 10}" y="{y + 4:.1f}" class="lbl" text-anchor="end">vs {esc(NICE.get(m, m))}</text>')
        cv, (cl, ch) = pr["delta_cv_mean"], pr["delta_cv_mean_ci95"]
        ho, (hl, hh) = pr["delta_holdout"], pr["delta_holdout_ci95"]
        t1 = f"vs {NICE.get(m, m)} — CV-mean Δ {pm(cv)} CI [{pm(cl)}, {pm(ch)}], P={pr['p_a_gt_b_cv_mean']:.3f}"
        t2 = f"vs {NICE.get(m, m)} — holdout Δ {pm(ho)} CI [{pm(hl)}, {pm(hh)}], P={pr['p_a_gt_b_holdout']:.3f}"
        p.append(f'<g data-tip="{esc(t1)}">'
                 f'<line x1="{X(cl):.1f}" y1="{y - 7:.1f}" x2="{X(ch):.1f}" y2="{y - 7:.1f}" stroke="var(--s1)" stroke-width="2"/>'
                 f'<circle cx="{X(cv):.1f}" cy="{y - 7:.1f}" r="5" fill="var(--s1)" stroke="var(--surface)" stroke-width="2"/></g>')
        p.append(f'<g data-tip="{esc(t2)}">'
                 f'<line x1="{X(hl):.1f}" y1="{y + 8:.1f}" x2="{X(hh):.1f}" y2="{y + 8:.1f}" stroke="var(--s2)" stroke-width="2"/>'
                 f'<circle cx="{X(ho):.1f}" cy="{y + 8:.1f}" r="5" fill="var(--surface)" stroke="var(--s2)" stroke-width="2.5"/></g>')
    p.append("</svg>")
    return "".join(p)


def svg_slope() -> str:
    """CV mean -> holdout AUC slopegraph (the rank inversion)."""
    models = MAIN
    W, H = 880, 470
    XL, XR, TOP, BOT = 268, 620, 46, 30
    d0, d1 = 0.468, 0.578
    def Y(v): return lin(v, d0, d1, H - BOT, TOP)
    emph = {"lgbm_fs_selected": ("var(--s1)", 3.2), "xgboost": ("var(--s2)", 2.2),
            "lightgbm": ("var(--s2)", 2.2)}
    lv = [LEAGUE[m]["cv_auc_mean"] for m in models]
    rv = [LEAGUE[m]["holdout_auc"] for m in models]
    ly = resolve([Y(v) for v in lv], 14.5, TOP - 6, H - BOT + 6)
    ry = resolve([Y(v) for v in rv], 14.5, TOP - 6, H - BOT + 6)
    p = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="CV mean AUC versus holdout AUC per model">']
    for t in (0.48, 0.50, 0.52, 0.54, 0.56):
        yy = Y(t)
        cls = "chance" if t == 0.50 else "grid"
        p.append(f'<line x1="{XL}" y1="{yy:.1f}" x2="{XR}" y2="{yy:.1f}" class="{cls}"/>')
        p.append(f'<text x="{(XL + XR) / 2:.0f}" y="{yy - 4:.1f}" class="ax" text-anchor="middle">{t:.2f}</text>')
    p.append(f'<text x="{XL}" y="{TOP - 20}" class="colh" text-anchor="middle">CV mean (4 folds)</text>')
    p.append(f'<text x="{XR}" y="{TOP - 20}" class="colh" text-anchor="middle">Holdout (used once)</text>')
    for i, m in enumerate(models):
        col, wdt = emph.get(m, ("var(--axisc)", 1.4))
        tcls = "slbl-em" if m in emph else "slbl"
        tip = f"{NICE.get(m, m)} — CV {a4(lv[i])} → holdout {a4(rv[i])} (Δ {pm(rv[i] - lv[i])})"
        p.append(f'<g data-tip="{esc(tip)}">'
                 f'<line x1="{XL}" y1="{Y(lv[i]):.1f}" x2="{XR}" y2="{Y(rv[i]):.1f}" stroke="{col}" stroke-width="{wdt}" />'
                 f'<circle cx="{XL}" cy="{Y(lv[i]):.1f}" r="4" fill="{col}"/>'
                 f'<circle cx="{XR}" cy="{Y(rv[i]):.1f}" r="4" fill="{col}"/></g>')
        p.append(f'<text x="{XL - 10}" y="{ly[i] + 4:.1f}" class="{tcls}" text-anchor="end">{esc(NICE.get(m, m))} · {a3(lv[i])}</text>')
        p.append(f'<text x="{XR + 10}" y="{ry[i] + 4:.1f}" class="{tcls}">{a3(rv[i])} · {esc(NICE.get(m, m))}</text>')
    p.append("</svg>")
    return "".join(p)


def heatmap_html() -> str:
    head = "".join(f"<th>{w if w != 'holdout' else 'Holdout'}</th>" for w in
                   [f.replace("2026-", "2026-") for f in FOLDS] + ["holdout"])
    rows = []
    for m in HEAT:
        r = LEAGUE[m]
        cells = []
        for w in FOLDS:
            v = r["fold_aucs"][w]
            cells.append(f'<td class="{heat_class(v)}" data-tip="{esc(NICE.get(m, m))} · {w}: AUC {a4(v)}">{a3(v)}</td>')
        hv = r["holdout_auc"]
        cells.append(f'<td class="{heat_class(hv)} hm-ho" data-tip="{esc(NICE.get(m, m))} · holdout: AUC {a4(hv)}">{a3(hv)}</td>')
        delta = hv - r["cv_auc_mean"]
        dcls = "neg" if delta < 0 else "pos"
        rows.append(f'<tr><th scope="row">{esc(NICE.get(m, m))}</th>{"".join(cells)}'
                    f'<td class="hm-delta {dcls}">{pm(delta, 3)}</td></tr>')
    return (f'<div class="scroll"><table class="heat"><thead><tr><th>Out-of-sample AUC</th>{head}'
            f'<th>Δ hold−CV</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div>')


def svg_roc() -> str:
    W, H = 560, 520
    X0, X1, Y0, Y1 = 62, 536, 18, 470
    def X(v): return lin(v, 0, 1, X0, X1)
    def Y(v): return lin(v, 0, 1, Y1, Y0)
    p = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Holdout ROC curves for seven models">']
    for t in (0, 0.25, 0.5, 0.75, 1.0):
        p.append(f'<line x1="{X(t):.1f}" y1="{Y0}" x2="{X(t):.1f}" y2="{Y1}" class="grid"/>')
        p.append(f'<line x1="{X0}" y1="{Y(t):.1f}" x2="{X1}" y2="{Y(t):.1f}" class="grid"/>')
        p.append(f'<text x="{X(t):.1f}" y="{Y1 + 18}" class="ax" text-anchor="middle">{t:g}</text>')
        p.append(f'<text x="{X0 - 8}" y="{Y(t) + 4:.1f}" class="ax" text-anchor="end">{t:g}</text>')
    p.append(f'<line x1="{X(0):.1f}" y1="{Y(0):.1f}" x2="{X(1):.1f}" y2="{Y(1):.1f}" class="chance"/>')
    p.append(f'<text x="{(X0 + X1) / 2:.0f}" y="{H - 4}" class="ax" text-anchor="middle">False positive rate</text>')
    p.append(f'<text x="14" y="{(Y0 + Y1) / 2:.0f}" class="ax" text-anchor="middle" transform="rotate(-90 14 {(Y0 + Y1) / 2:.0f})">True positive rate</text>')
    for m in ROC_MODELS:
        fpr, tpr, auc = ROC[m]
        pts = " ".join(f"{X(a):.1f},{Y(b):.1f}" for a, b in zip(fpr, tpr))
        wdt = 3 if m == "lgbm_fs_selected" else 1.8
        p.append(f'<polyline class="roc-p" data-m="{m}" points="{pts}" fill="none" '
                 f'stroke="var(--s{ROC_SLOT[m]})" stroke-width="{wdt}" '
                 f'data-tip="{esc(NICE.get(m, m))} — holdout AUC {a4(auc)}"/>')
    p.append("</svg>")
    return "".join(p)


def roc_legend_html() -> str:
    items = []
    for m in ROC_MODELS:
        auc = ROC[m][2]
        star = " ·champion" if m == "lgbm_fs_selected" else ""
        items.append(f'<li class="roc-leg" data-m="{m}"><span class="chip" style="background:var(--s{ROC_SLOT[m]})"></span>'
                     f'<span class="roc-name">{esc(NICE.get(m, m))}{star}</span>'
                     f'<span class="roc-auc">{a4(auc)}</span></li>')
    return f'<ul class="legend roc-legend">{"".join(items)}</ul>'


def svg_decile_panel(w: str, vals: list[float], ymin: float, ymax: float) -> str:
    W, H = 196, 196
    X0, X1, Y0, Y1 = 34, 190, 14, 160
    def Y(v): return lin(v, ymin, ymax, Y1, Y0)
    bw = (X1 - X0) / 10
    title = {"holdout": "Holdout (Aug→mid-Sep)"}.get(w, w)
    p = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Champion decile mean excess, {title}">']
    for t in (-0.02, 0.0, 0.02, 0.04):
        yy = Y(t)
        cls = "axisln" if t == 0 else "grid"
        p.append(f'<line x1="{X0}" y1="{yy:.1f}" x2="{X1}" y2="{yy:.1f}" class="{cls}"/>')
        p.append(f'<text x="{X0 - 4}" y="{yy + 3.5:.1f}" class="ax ax-s" text-anchor="end">{t * 100:+.0f}</text>')
    for i, v in enumerate(vals):
        x = X0 + i * bw + 1
        col = "var(--pos)" if v >= 0 else "var(--neg)"
        y0, y1 = Y(max(v, 0)), Y(min(v, 0))
        hgt = max(y1 - y0, 1.5)
        tip = f"{title} — D{i + 1}{' (top decile)' if i == 9 else ''}: mean 20d excess {pct(v)}"
        p.append(f'<rect x="{x:.1f}" y="{y0:.1f}" width="{bw - 2:.1f}" height="{hgt:.1f}" rx="2.5" '
                 f'fill="{col}" data-tip="{esc(tip)}"/>')
    p.append(f'<text x="{X0}" y="{H - 18}" class="ax ax-s">D1</text>')
    p.append(f'<text x="{X1}" y="{H - 18}" class="ax ax-s" text-anchor="end">D10</text>')
    p.append(f'<text x="{(X0 + X1) / 2:.0f}" y="{H - 2}" class="lbl" text-anchor="middle">{title}</text>')
    return "".join(p) + "</svg>"


def decile_multiples_html() -> str:
    lo = min(min(v) for v in DECILES.values())
    hi = max(max(v) for v in DECILES.values())
    ymin, ymax = min(-0.022, lo - 0.004), max(0.05, hi + 0.004)
    panels = "".join(f'<div class="mini">{svg_decile_panel(w, DECILES[w], ymin, ymax)}</div>'
                     for w in WINDOWS)
    return f'<div class="minis">{panels}</div>'


def svg_elim() -> str:
    curve = FS["elimination_curve"]
    ks = [c["k"] for c in curve]
    W, H = 760, 330
    X0, X1, Y0, Y1 = 64, 724, 26, 272
    d0, d1 = 0.478, 0.562
    def X(k): return lin(k, 4, 31, X0, X1)
    def Y(v): return lin(v, d0, d1, Y1, Y0)
    p = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Feature-count ablation: CV AUC by k">']
    for t in (0.48, 0.50, 0.52, 0.54, 0.56):
        yy = Y(t)
        cls = "chance" if t == 0.50 else "grid"
        p.append(f'<line x1="{X0}" y1="{yy:.1f}" x2="{X1}" y2="{yy:.1f}" class="{cls}"/>')
        p.append(f'<text x="{X0 - 8}" y="{yy + 4:.1f}" class="ax" text-anchor="end">{t:.2f}</text>')
    band_up = [(X(c["k"]), Y(c["cv_auc_mean"] + c["cv_auc_std"])) for c in curve]
    band_dn = [(X(c["k"]), Y(c["cv_auc_mean"] - c["cv_auc_std"])) for c in reversed(curve)]
    band = " ".join(f"{x:.1f},{y:.1f}" for x, y in band_up + band_dn)
    p.append(f'<polygon points="{band}" fill="var(--s1)" opacity="0.12"/>')
    cvl = " ".join(f"{X(c['k']):.1f},{Y(c['cv_auc_mean']):.1f}" for c in curve)
    hol = " ".join(f"{X(c['k']):.1f},{Y(c['holdout_auc']):.1f}" for c in curve)
    p.append(f'<polyline points="{hol}" fill="none" stroke="var(--s2)" stroke-width="2" stroke-dasharray="5 4"/>')
    p.append(f'<polyline points="{cvl}" fill="none" stroke="var(--s1)" stroke-width="2.5"/>')
    for c in curve:
        x, ycv, yho = X(c["k"]), Y(c["cv_auc_mean"]), Y(c["holdout_auc"])
        p.append(f'<circle cx="{x:.1f}" cy="{yho:.1f}" r="4.5" fill="var(--surface)" stroke="var(--s2)" stroke-width="2" '
                 f'data-tip="k={c["k"]} — holdout AUC {a4(c["holdout_auc"])}"/>')
        big = c["k"] == 10
        p.append(f'<circle cx="{x:.1f}" cy="{ycv:.1f}" r="{6 if big else 4.5}" fill="var(--s1)" stroke="var(--surface)" stroke-width="2" '
                 f'data-tip="k={c["k"]} — CV AUC {a4(c["cv_auc_mean"])} ± {a4(c["cv_auc_std"])}"/>')
        p.append(f'<text x="{x:.1f}" y="{Y1 + 22}" class="ax" text-anchor="middle">k={c["k"]}</text>')
    xk, yk = X(10), Y(0.530695)
    p.append(f'<text x="{xk:.1f}" y="{yk - 14:.1f}" class="anno" text-anchor="middle">k=10 · 0.5307 (max)</text>')
    p.append(f'<text x="{X(30) - 4:.1f}" y="{Y(0.5226) - 12:.1f}" class="slbl" text-anchor="end">CV mean ± std</text>')
    p.append(f'<text x="{X(30) - 4:.1f}" y="{Y(0.517) + 20:.1f}" class="slbl s2" text-anchor="end">holdout (record only)</text>')
    p.append("</svg>")
    return "".join(p)


def month_charts_html() -> str:
    pm_rows = DP["per_month"]
    months = [r["month"] for r in pm_rows]
    def wincls(mo):
        if mo in ("2026-04", "2026-05", "2026-06", "2026-07"): return "cv"
        if mo in ("2026-08", "2026-09"): return "ho"
        return "tr"
    WINCOL = {"tr": "var(--axisc)", "cv": "var(--s1)", "ho": "var(--s2)"}

    # --- coverage: tickers per month ---
    W, H = 760, 260
    X0, X1, Y0, Y1 = 56, 744, 18, 206
    n = len(months)
    bw = (X1 - X0) / n
    def Yc(v): return lin(v, 0, 1800, Y1, Y0)
    c = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Universe tickers per month">']
    for t in (0, 600, 1200, 1800):
        yy = Yc(t)
        c.append(f'<line x1="{X0}" y1="{yy:.1f}" x2="{X1}" y2="{yy:.1f}" class="{"axisln" if t == 0 else "grid"}"/>')
        c.append(f'<text x="{X0 - 6}" y="{yy + 4:.1f}" class="ax ax-s" text-anchor="end">{t}</text>')
    for i, r in enumerate(pm_rows):
        x = X0 + i * bw + 1.5
        col = WINCOL[wincls(r["month"])]
        tip = (f"{r['month']} — {r['tickers']} tickers, {r['rows']:,} rows, "
               f"{r['trading_days']} sessions")
        c.append(f'<rect x="{x:.1f}" y="{Yc(r["tickers"]):.1f}" width="{bw - 3:.1f}" '
                 f'height="{Y1 - Yc(r["tickers"]):.1f}" rx="2.5" fill="{col}" data-tip="{esc(tip)}"/>')
        if r["month"] in ("2025-06", "2025-12", "2026-06"):
            c.append(f'<text x="{x + bw / 2:.0f}" y="{Y1 + 16}" class="ax ax-s" text-anchor="middle">{r["month"]}</text>')
    c.append(f'<text x="{(X0 + X1) / 2:.0f}" y="{H - 24}" class="lbl" text-anchor="middle">Universe coverage — tickers/month (1,513 → 1,731)</text>')
    c.append(f'<text x="{(X0 + X1) / 2:.0f}" y="{H - 6}" class="ax" text-anchor="middle">■ train-only&#160;&#160;<tspan fill="var(--s1)">■ CV fold</tspan>&#160;&#160;<tspan fill="var(--s2)">■ holdout</tspan></text>')
    c.append("</svg>")
    cov = "".join(c)

    # --- regime: median 20d forward return by month ---
    g = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Median 20-day forward return by month">']
    def Yr(v): return lin(v, -0.10, 0.08, Y1, Y0 - 6)
    for t in (-0.08, -0.04, 0.0, 0.04, 0.08):
        yy = Yr(t)
        g.append(f'<line x1="{X0}" y1="{yy:.1f}" x2="{X1}" y2="{yy:.1f}" class="{"axisln" if t == 0 else "grid"}"/>')
        g.append(f'<text x="{X0 - 6}" y="{yy + 4:.1f}" class="ax ax-s" text-anchor="end">{t * 100:+.0f}%</text>')
    for i, r in enumerate(pm_rows):
        v = r["median_y_raw_20d"]
        if v is None:
            continue
        x = X0 + i * bw + 1.5
        col = "var(--pos)" if v >= 0 else "var(--neg)"
        y0, y1 = Yr(max(v, 0)), Yr(min(v, 0))
        tip = f"{r['month']} — median 20d fwd return {pct(v)} ({wincls(r['month']) == 'cv' and 'CV fold' or wincls(r['month']) == 'ho' and 'holdout' or 'train-only'})"
        g.append(f'<rect x="{x:.1f}" y="{y0:.1f}" width="{bw - 3:.1f}" height="{max(y1 - y0, 1.5):.1f}" rx="2.5" fill="{col}" data-tip="{esc(tip)}"/>')
        if r["month"] in ("2025-06", "2025-12", "2026-06"):
            g.append(f'<text x="{x + bw / 2:.0f}" y="{Y1 + 16}" class="ax ax-s" text-anchor="middle">{r["month"]}</text>')
    g.append(f'<text x="{(X0 + X1) / 2:.0f}" y="{H - 24}" class="lbl" text-anchor="middle">Regime — median 20d fwd return by month (−8.6% to +5.7%)</text>')
    g.append(f'<text x="{(X0 + X1) / 2:.0f}" y="{H - 6}" class="ax" text-anchor="middle">2026-10 unlabeled (window runs past last data date)</text>')
    g.append("</svg>")
    reg = "".join(g)

    # --- label balance: base rates ---
    lb = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Monthly label base rates">']
    def Yl(v): return lin(v, 0.15, 0.80, Y1, Y0)
    for t in (0.2, 0.35, 0.5, 0.65, 0.8):
        yy = Yl(t)
        lb.append(f'<line x1="{X0}" y1="{yy:.1f}" x2="{X1}" y2="{yy:.1f}" class="{"chance" if t == 0.5 else "grid"}"/>')
        lb.append(f'<text x="{X0 - 6}" y="{yy + 4:.1f}" class="ax ax-s" text-anchor="end">{t:.2f}</text>')
    xs = [X0 + i * bw + bw / 2 for i in range(n)]
    rows_lab = [r for r in pm_rows if r["mean_label_beat_mkt_20d"] is not None]
    beat = " ".join(f"{xs[i]:.1f},{Yl(r['mean_label_beat_mkt_20d']):.1f}"
                    for i, r in enumerate(pm_rows) if r["mean_label_beat_mkt_20d"] is not None)
    up = " ".join(f"{xs[i]:.1f},{Yl(r['mean_label_up_5d']):.1f}"
                  for i, r in enumerate(pm_rows) if r["month"] != "2026-10")
    lb.append(f'<polyline points="{up}" fill="none" stroke="var(--s2)" stroke-width="2"/>')
    lb.append(f'<polyline points="{beat}" fill="none" stroke="var(--s1)" stroke-width="2.5"/>')
    for i, r in enumerate(pm_rows):
        if r["mean_label_beat_mkt_20d"] is not None:
            lb.append(f'<circle cx="{xs[i]:.1f}" cy="{Yl(r["mean_label_beat_mkt_20d"]):.1f}" r="3" fill="var(--s1)" data-tip="{r["month"]} — beat_mkt_20d base rate {r["mean_label_beat_mkt_20d"]:.4f}"/>')
        if r["month"] != "2026-10":
            lb.append(f'<circle cx="{xs[i]:.1f}" cy="{Yl(r["mean_label_up_5d"]):.1f}" r="3" fill="var(--s2)" data-tip="{r["month"]} — up_5d base rate {r["mean_label_up_5d"]:.3f}"/>')
        if r["month"] in ("2025-06", "2025-12", "2026-06"):
            lb.append(f'<text x="{xs[i]:.0f}" y="{Y1 + 16}" class="ax ax-s" text-anchor="middle">{r["month"]}</text>')
    lb.append(f'<text x="{(X0 + X1) / 2:.0f}" y="{H - 24}" class="lbl" text-anchor="middle">Label balance — <tspan fill="var(--s1)">beat_mkt_20d ≈ 0.500 by construction</tspan> vs <tspan fill="var(--s2)">up_5d 0.37–0.72</tspan></text>')
    lb.append(f'<text x="{(X0 + X1) / 2:.0f}" y="{H - 6}" class="ax" text-anchor="middle">partial 2026-10 excluded for up_5d</text>')
    lb.append("</svg>")
    bal = "".join(lb)

    wrap = '<div class="card"><div class="scroll"><div class="wide-svg" style="min-width:620px">{}</div></div></div>'
    return (f'<div class="trio">{wrap.format(cov)}{wrap.format(reg)}{wrap.format(bal)}</div>')


# ================================================================ HTML tables

def league_table_html() -> str:
    def row(m, nested=False):
        r = LEAGUE[m]
        champ = m == "lgbm_fs_selected"
        cls = ("nested " if nested else "") + ("champ" if champ else "")
        spread = r["holdout_decile_spread"]
        scls = "pos" if spread >= 0 else "neg"
        tip = (f"{NICE.get(m, m)} — folds "
               + ", ".join(f"{k[-2:]}:{a3(v)}" for k, v in r["fold_aucs"].items())
               + f"; train {r['train_seconds']:.0f}s")
        return (f'<tr class="{cls}" data-g="{m if not nested else CLEAN_OF_INV[m]}" data-tip="{esc(tip)}">'
                f'<td class="mname">{"└ " if nested else ""}{esc(NICE.get(m, m))}{" ★" if champ else ""}</td>'
                f'<td>{FAMILY.get(r["family"], r["family"])}</td>'
                f'<td data-v="{r["n_features"]}">{r["n_features"]}</td>'
                f'<td data-v="{r["cv_auc_mean"]}"><b>{a4(r["cv_auc_mean"])}</b> <span class="dim2">± {r["cv_auc_std"]:.3f}</span></td>'
                f'<td data-v="{r["min_fold_auc"]}">{a4(r["min_fold_auc"])}</td>'
                f'<td data-v="{r["holdout_auc"]}">{a4(r["holdout_auc"])}</td>'
                f'<td data-v="{spread}" class="{scls}">{pct(spread)}</td></tr>')
    global CLEAN_OF_INV
    CLEAN_OF_INV = {v: k for k, v in CLEAN_OF.items()}
    body = []
    for m in MAIN:
        body.append(row(m))
        if m in CLEAN_OF:
            body.append(row(CLEAN_OF[m], nested=True))
    heads = [("Model", "s"), ("Family", "s"), ("#feat", "n"), ("CV AUC ± std", "n"),
             ("Min fold", "n"), ("Holdout AUC", "n"), ("Holdout decile spread", "n")]
    th = "".join(f'<th data-k="{i}" data-t="{t}" role="button" tabindex="0">{h}<span class="arrow"></span></th>'
                 for i, (h, t) in enumerate(heads))
    return (f'<div class="scroll"><table id="league"><thead><tr>{th}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def up5d_table_html() -> str:
    order = ["lgbm_fs_selected", "lr_l2", "lr_l1", "lr_elastic", "mlp", "lightgbm",
             "xgboost", "random_forest", "decision_tree", "gru", "baseline_mom"]
    exap = MS["secondary_task_caveat"]["cv_mean_excluding_2026_04"]
    nest = {"lgbm_fs_selected": "lgbm_fs_selected_clean", "lr_l2": "lr_l2_clean",
            "baseline_mom": "baseline_mom_clean"}
    rows = []
    def rw(m, nested=False):
        r = LEAGUE_UP[m]
        ex = exap.get(m)
        rows.append(f'<tr class="{"nested" if nested else ""}">'
                    f'<td class="mname">{"└ " if nested else ""}{esc(NICE.get(m, m))}</td>'
                    f'<td><b>{a4(r["cv_auc_mean"])}</b> <span class="dim2">± {r["cv_auc_std"]:.3f}</span></td>'
                    f'<td>{a4(ex) if ex is not None else "—"}</td>'
                    f'<td>{a4(r["min_fold_auc"])}</td><td>{a4(r["holdout_auc"])}</td></tr>')
    for m in order:
        rw(m)
        if m in nest:
            rw(nest[m], nested=True)
    return ('<div class="scroll"><table class="plain"><thead><tr><th>Model</th><th>CV AUC ± std</th>'
            '<th>CV ex-April</th><th>Min fold</th><th>Holdout AUC</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def feature_table_html() -> str:
    sel = [r for r in FS["combined_rank"] if r["selection_order"] is not None][:10]
    sel.sort(key=lambda r: r["selection_order"])
    rows = []
    for r in sel:
        rows.append(f'<tr><td class="mname">{r["selection_order"]}. {esc(r["feature"])}</td>'
                    f'<td>{r["univariate_auc"]:.4f}</td>'
                    f'<td class="{"pos" if r["univariate_sign"] == "+" else "neg"}">{r["univariate_sign"]}</td>'
                    f'<td>{r["lgbm_gain_pct"] * 100:.1f}%</td>'
                    f'<td>#{int(r["rank_permutation"])}</td></tr>')
    return ('<div class="scroll"><table class="plain"><thead><tr><th>Selected feature</th>'
            '<th>Univariate AUC</th><th>Sign</th><th>LGBM gain</th><th>Permutation rank</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def crossval_table_html() -> str:
    cv = HD["cross_validation_vs_production"]
    rel = cv["RELIANCE_2026-10-14"]
    rows = [
        ("Breadth above both 50 &amp; 200-DMA", cv["breadth_above_both_50_200dma"]["pilot"],
         cv["breadth_above_both_50_200dma"]["production"]),
        ("RELIANCE rsi_2 (2026-10-14)", f'{rel["rsi_2"]["pilot"]}', f'{rel["rsi_2"]["production"]}'),
        ("RELIANCE dist_52w_high", f'{rel["dist_52w_high"]["pilot"]}', f'{rel["dist_52w_high"]["production"]}'),
        ("RELIANCE below 200-DMA", "true", "true"),
        ("NH−NL 10d avg", f'{cv["nh_nl_10d_avg"]["pilot_proper_defn"]}', f'{cv["nh_nl_10d_avg"]["production"]}'),
    ]
    body = "".join(f'<tr><td class="mname">{k}</td><td>{a}</td><td>{b}</td></tr>' for k, a, b in rows)
    return ('<div class="scroll"><table class="plain tight"><thead><tr><th>Cross-pipeline check</th>'
            '<th>Pilot</th><th>Production</th></tr></thead>'
            f'<tbody>{body}</tbody></table></div>')


# =================================================================== assembly

CSS = """
/* Layout: single readable column, chart cards on a soft page plane; quant-memo
   typography — serif prose, sans headings & data. */
:root{
  --bg:#f9f9f7; --surface:#fcfcfb; --ink:#161513; --ink2:#52514e; --muted:#898781;
  --grid:#e1e0d9; --axisc:#c3c2b7; --border:rgba(11,11,11,.10);
  --accent:#9a5b00; --accent-soft:rgba(154,91,0,.10);
  --s1:#2a78d6; --s2:#eb6834; --s3:#1baf7a; --s4:#eda100; --s5:#e87ba4; --s6:#008300; --s7:#6250d6;
  --pos:#2a78d6; --neg:#e34948; --good:#006300; --bad:#b32e2e;
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
    --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181; --s6:#008300; --s7:#9085e9;
    --pos:#3987e5; --neg:#e66767; --good:#0ca30c; --bad:#e66767;
    --hm-n3:#7e2a29; --hm-n2:#5d2423; --hm-n1:#402020; --hm-0:#262624;
    --hm-p1:#1a2c45; --hm-p2:#17395f; --hm-p3:#1c4d8c; --hm-p4:#2a6cc0;
    color-scheme:dark;
  }
}
:root[data-theme="dark"]{
  --bg:#0d0d0d; --surface:#1a1a19; --ink:#f0efec; --ink2:#c3c2b7; --muted:#898781;
  --grid:#2c2c2a; --axisc:#383835; --border:rgba(255,255,255,.12);
  --accent:#e8a33d; --accent-soft:rgba(232,163,61,.12);
  --s1:#3987e5; --s2:#d95926; --s3:#199e70; --s4:#c98500; --s5:#d55181; --s6:#008300; --s7:#9085e9;
  --pos:#3987e5; --neg:#e66767; --good:#0ca30c; --bad:#e66767;
  --hm-n3:#7e2a29; --hm-n2:#5d2423; --hm-n1:#402020; --hm-0:#262624;
  --hm-p1:#1a2c45; --hm-p2:#17395f; --hm-p3:#1c4d8c; --hm-p4:#2a6cc0;
  color-scheme:dark;
}
*{box-sizing:border-box}
html{height:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16.5px/1.55 var(--serif);
  -webkit-text-size-adjust:100%}
.wrap{max-width:1072px;margin-inline:auto;
  padding-left:max(16px,env(safe-area-inset-left,0px));
  padding-right:max(16px,env(safe-area-inset-right,0px));
  padding-block:0 56px}
h1,h2,h3,h4{font-family:var(--sans);line-height:1.15;text-wrap:balance;margin:0}
p{margin:.55em 0;max-width:72ch}
a{color:var(--accent)}
b,strong{font-weight:700}
.num,td,th{font-variant-numeric:tabular-nums}

/* hero */
.hero{padding-block:44px 8px}
.eyebrow{font:600 12px/1 var(--sans);letter-spacing:.14em;text-transform:uppercase;color:var(--accent)}
.hero h1{font-size:clamp(30px,5.4vw,46px);font-weight:800;letter-spacing:-.02em;margin:.25em 0 .2em}
.hero .sub{color:var(--ink2);font-size:17px;max-width:76ch}
.verdict{margin-top:20px;border:1px solid var(--border);border-left:4px solid var(--accent);
  background:var(--surface);border-radius:10px;padding:16px 18px}
.verdict .vhead{font:700 13px/1 var(--sans);letter-spacing:.1em;text-transform:uppercase;color:var(--accent)}
.verdict p{font-family:var(--sans);font-size:17.5px;font-weight:600;margin:.4em 0 .5em;max-width:none}
.badges{display:flex;flex-wrap:wrap;gap:8px;font-family:var(--sans);font-size:13px}
.badge{border:1px solid var(--border);border-radius:999px;padding:4px 11px;color:var(--ink2);background:var(--bg)}
.badge b{color:var(--ink)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin-top:14px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px}
.tile .v{font:700 30px/1.1 var(--sans);letter-spacing:-.01em}
.tile .k{font:600 12px/1.3 var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--ink2);margin-top:6px}
.tile .d{font:400 13px/1.45 var(--sans);color:var(--muted);margin-top:6px}

/* sections */
section{margin-top:44px}
.sec-eyebrow{font:700 12px/1 var(--sans);letter-spacing:.14em;color:var(--accent);text-transform:uppercase}
section>h2{font-size:clamp(21px,3.2vw,27px);font-weight:750;letter-spacing:-.015em;margin:.3em 0 .35em}
.lede{color:var(--ink2)}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;margin-top:14px}
.card .cap{font:400 13px/1.5 var(--sans);color:var(--muted);margin:10px 4px 2px;max-width:none}
figure{margin:0}
svg{display:block;width:100%;height:auto}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.scroll .wide-svg{min-width:720px}
#rocsvg-w{min-width:440px;max-width:600px;margin-inline:auto}

/* svg type */
svg text{font-family:var(--sans)}
.ax{font-size:12px;fill:var(--muted)}
.ax-s{font-size:10.5px}
.lbl{font-size:12.5px;fill:var(--ink2)}
.val{font-size:12.5px;font-weight:600;fill:var(--ink2)}
.colh{font-size:13px;font-weight:700;fill:var(--ink)}
.slbl{font-size:10.8px;fill:var(--ink2)}
.slbl-em{font-size:11.5px;font-weight:700;fill:var(--ink)}
.s2{fill:var(--s2)}
.anno{font-size:12.5px;font-weight:700;fill:var(--s1)}
.accent{fill:var(--accent)}
.grid{stroke:var(--grid);stroke-width:1}
.axisln{stroke:var(--axisc);stroke-width:1.2}
.chance{stroke:var(--axisc);stroke-width:1.4;stroke-dasharray:5 4}

/* tables */
table{border-collapse:collapse;width:100%;font-family:var(--sans);font-size:13.8px}
th,td{padding:7.5px 10px;text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
thead th{font-size:11.5px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);
  border-bottom:1.5px solid var(--axisc);cursor:default}
tbody tr{border-bottom:1px solid var(--grid)}
tbody tr:last-child{border-bottom:none}
.mname{font-weight:600}
.dim2{color:var(--muted);font-weight:400}
tr.champ td{background:var(--accent-soft)}
tr.champ .mname{color:var(--accent)}
tr.nested td{color:var(--ink2);font-size:12.8px}
tr.nested .mname{font-weight:400;padding-left:22px}
td.pos{color:var(--good)} td.neg{color:var(--bad)}
#league thead th{cursor:pointer;user-select:none}
#league thead th .arrow{display:inline-block;width:1em;color:var(--accent)}
table.plain thead th{cursor:default}
table.tight td,table.tight th{padding:6px 10px}

/* heatmap */
table.heat{font-size:13px}
table.heat td{text-align:center;min-width:64px;font-weight:600;border-left:2px solid var(--surface)}
table.heat tbody th{font-weight:600;text-align:left;font-size:12.8px;color:var(--ink2)}
table.heat thead th{text-align:center}
table.heat thead th:first-child{text-align:left}
.hm-n3{background:var(--hm-n3)} .hm-n2{background:var(--hm-n2)} .hm-n1{background:var(--hm-n1)}
.hm-0{background:var(--hm-0)} .hm-p1{background:var(--hm-p1)} .hm-p2{background:var(--hm-p2)}
.hm-p3{background:var(--hm-p3)} .hm-p4{background:var(--hm-p4)}
.hm-ho{border-left:3px double var(--axisc) !important}
.hm-delta{font-weight:700}
.hm-delta.pos{color:var(--good)} .hm-delta.neg{color:var(--bad)}
.hm-key{display:flex;flex-wrap:wrap;gap:4px;align-items:center;font:12px var(--sans);color:var(--muted);margin-top:10px}
.hm-key span{display:inline-block;width:26px;height:13px;border-radius:3px}

/* legends & chips */
.legend{list-style:none;display:flex;flex-wrap:wrap;gap:6px 16px;margin:10px 0 0;padding:0;font:13px var(--sans)}
.legend li{display:flex;align-items:center;gap:7px;color:var(--ink2)}
.chip{width:14px;height:14px;border-radius:4px;flex:none}
.roc-legend li{cursor:pointer;padding:3px 8px;border-radius:7px;border:1px solid transparent}
.roc-legend li:hover{border-color:var(--border);background:var(--bg)}
.roc-auc{font-weight:700;color:var(--ink)}
svg .roc-p{transition:opacity .15s}
svg.dimmed .roc-p{opacity:.14}
svg.dimmed .roc-p.hot{opacity:1;stroke-width:3.5}

/* small-multiple rows */
.minis{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:10px}
.trio{display:grid;grid-template-columns:1fr;gap:12px}
.trio .card{margin-top:0;max-width:880px}
.mini{min-width:0}

/* strips & panels */
.strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin-top:12px}
.schip{background:var(--surface);border:1px solid var(--border);border-radius:9px;padding:10px 12px;font-family:var(--sans)}
.schip .w{font-size:11px;letter-spacing:.07em;text-transform:uppercase;color:var(--muted)}
.schip .n{font-size:21px;font-weight:700;margin-top:3px}
.schip .n.pos{color:var(--good)}
.cols2{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px;margin-top:14px}
.panel{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px}
.panel h3{font-size:15.5px;margin-bottom:6px}
.panel p,.panel li{font-size:14.5px}
.panel .tag{font:700 11px/1 var(--sans);letter-spacing:.09em;text-transform:uppercase;
  padding:3px 8px;border-radius:999px;display:inline-block;margin-bottom:8px}
.tag.drop{background:var(--hm-n1);color:var(--bad)}
.tag.keep{background:var(--hm-p1);color:var(--pos)}
.kv{display:flex;flex-wrap:wrap;gap:6px 14px;font:13px var(--sans);color:var(--ink2);margin-top:8px}
.kv b{color:var(--ink)}

/* incident */
.incident{border-left:4px solid var(--neg)}
.incident .steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;margin-top:10px}
.incident .step h4{font-size:13px;letter-spacing:.07em;text-transform:uppercase;color:var(--accent);margin-bottom:4px}
.incident .step p{font-size:14px;margin:0}
.days{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}
.day{font:11.5px var(--mono);border:1px solid var(--border);border-radius:5px;padding:2px 6px;color:var(--ink2);background:var(--bg)}

/* funnel */
.funnel{display:grid;gap:8px;margin-top:12px;font-family:var(--sans)}
.fstage .fbarwrap{background:var(--bg);border:1px solid var(--border);border-radius:6px;overflow:hidden}
.fstage .fbar{height:30px;background:var(--s1);opacity:.85;border-radius:5px 0 0 5px;min-width:2%}
.fstage .fmeta{display:flex;justify-content:space-between;gap:10px;font-size:13px;color:var(--ink2);margin:3px 2px}
.fstage .fmeta b{color:var(--ink);font-size:13.5px}

/* methodology */
.meth{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:12px;margin-top:12px}
.meth .m h4{font-size:12px;letter-spacing:.09em;text-transform:uppercase;color:var(--accent);margin-bottom:4px}
.meth .m p{font-size:14px;margin:0;font-family:var(--sans);color:var(--ink2)}
ol.lims,ul.lims{padding-left:20px;margin:8px 0}
.lims li{margin:6px 0;font-size:15px}
details{margin-top:12px}
summary{cursor:pointer;font:600 14px var(--sans);color:var(--accent);padding:4px 0}
footer{margin-top:52px;border-top:1px solid var(--grid);padding-top:14px;
  font:12.5px/1.6 var(--sans);color:var(--muted)}
footer code{font-family:var(--mono)}

/* tooltip */
#tip{position:fixed;z-index:50;max-width:320px;background:var(--ink);color:var(--bg);
  font:12.5px/1.45 var(--sans);padding:7px 10px;border-radius:7px;pointer-events:none;
  opacity:0;transform:translateY(3px);transition:opacity .12s;white-space:normal}
#tip.on{opacity:.97}
[data-tip]{cursor:default}
@media (prefers-reduced-motion:reduce){*{transition:none !important}}
@media (max-width:480px){
  .hero{padding-top:30px}
  th,td{padding:6px 7px}
  .tile .v{font-size:25px}
}
"""

JS = """
(function(){
  // shared tooltip -----------------------------------------------------------
  var tip=document.getElementById('tip');
  function show(e,t){tip.textContent=t;tip.classList.add('on');move(e);}
  function move(e){
    var x=e.clientX+14,y=e.clientY+14,r=tip.getBoundingClientRect();
    if(x+r.width>window.innerWidth-8)x=e.clientX-r.width-10;
    if(y+r.height>window.innerHeight-8)y=e.clientY-r.height-10;
    tip.style.left=x+'px';tip.style.top=y+'px';}
  function hide(){tip.classList.remove('on');}
  document.addEventListener('pointerover',function(e){
    var el=e.target.closest('[data-tip]');if(el)show(e,el.getAttribute('data-tip'));});
  document.addEventListener('pointermove',function(e){
    if(tip.classList.contains('on'))move(e);
    if(!e.target.closest('[data-tip]'))hide();});
  document.addEventListener('pointerdown',function(e){
    var el=e.target.closest('[data-tip]');
    if(el){show(e,el.getAttribute('data-tip'));setTimeout(hide,2600);}});

  // sortable league table (clean rows travel with their parent group) --------
  var table=document.getElementById('league');
  if(table){
    var tbody=table.tBodies[0],dir={};
    function groups(){
      var gs=[],cur=null;
      Array.prototype.forEach.call(tbody.rows,function(r){
        if(!r.classList.contains('nested')){cur={head:r,rows:[r]};gs.push(cur);}
        else if(cur){cur.rows.push(r);}});
      return gs;}
    table.tHead.addEventListener('click',function(e){
      var th=e.target.closest('th');if(!th)return;
      var k=+th.dataset.k,num=th.dataset.t==='n';
      var d=dir[k]=-(dir[k]||(num?1:-1));
      var gs=groups();
      gs.sort(function(a,b){
        var ca=a.head.cells[k],cb=b.head.cells[k];
        var va=num?parseFloat(ca.dataset.v!==undefined?ca.dataset.v:ca.textContent):ca.textContent.trim().toLowerCase();
        var vb=num?parseFloat(cb.dataset.v!==undefined?cb.dataset.v:cb.textContent):cb.textContent.trim().toLowerCase();
        return va<vb?d:va>vb?-d:0;});
      gs.forEach(function(g){g.rows.forEach(function(r){tbody.appendChild(r);});});
      Array.prototype.forEach.call(table.tHead.rows[0].cells,function(c){
        c.querySelector('.arrow').textContent='';});
      th.querySelector('.arrow').textContent=d===1?' ↓':' ↑';});
  }

  // ROC legend highlight ------------------------------------------------------
  var rocSvg=document.getElementById('rocsvg');
  if(rocSvg){
    document.querySelectorAll('.roc-leg').forEach(function(li){
      function on(){rocSvg.classList.add('dimmed');
        rocSvg.querySelectorAll('.roc-p').forEach(function(p){
          p.classList.toggle('hot',p.dataset.m===li.dataset.m);});}
      function off(){rocSvg.classList.remove('dimmed');
        rocSvg.querySelectorAll('.roc-p').forEach(function(p){p.classList.remove('hot');});}
      li.addEventListener('pointerenter',on);
      li.addEventListener('pointerleave',off);
      li.addEventListener('focus',on);li.addEventListener('blur',off);
      li.tabIndex=0;});
  }
})();
"""


def build_html() -> str:
    champ = LEAGUE["lgbm_fs_selected"]
    champ_clean = LEAGUE["lgbm_fs_selected_clean"]
    sig_ch = SIG["lgbm_fs_selected"]
    pr_lr = PAIRS["lr_l2"]
    dq = MS["data_quality_event"]
    top_excess = [DECILES[w][9] for w in WINDOWS]
    wl = {"2026-04": "Apr 26 · fold", "2026-05": "May 26 · fold", "2026-06": "Jun 26 · fold",
          "2026-07": "Jul 26 · fold", "holdout": "Holdout"}
    strip = "".join(
        f'<div class="schip"><div class="w">{wl[w]}</div>'
        f'<div class="n pos">{pct(v)}</div></div>'
        for w, v in zip(WINDOWS, top_excess))
    days = "".join(f'<span class="day">{d}</span>' for d in HD["phantom_days"])
    fn = DP["funnel"]
    funnel_rows = [
        ("equity_eod (raw ingest)", fn["equity_eod"]["rows"], f'{fn["equity_eod"]["tickers"]:,} tickers · Mar-2025 → Oct-2026'),
        ("equity_features", fn["equity_features"]["rows"], f'{fn["equity_features"]["tickers"]:,} tickers · non-feature series &amp; short histories dropped'),
        ("universe parquet (frozen)", fn["universe_parquet"]["rows"], "2,108 tickers · close ≥ ₹10, 20d median turnover ≥ ₹1 cr, warm-up excluded"),
        ("clean rebuild (post-fix)", MANIFEST["rows"], f'{MANIFEST["tickers"]:,} tickers · 12 phantom days purged'),
        ("primary-task rows", fn["primary_task_rows"], "label present &amp; y_clean_20d — what the harness scores"),
    ]
    fmax = funnel_rows[0][1]
    funnel = "".join(
        f'<div class="fstage"><div class="fmeta"><span>{name}</span><b>{v:,}</b></div>'
        f'<div class="fbarwrap"><div class="fbar" style="width:{v / fmax * 100:.1f}%"></div></div>'
        f'<div class="fmeta"><span class="dim2">{note}</span></div></div>'
        for name, v, note in funnel_rows)

    lgbm_top5 = list(TI["importances"].items())[:5]
    lrc_top = sorted(LRC["coefficients"].items(), key=lambda kv: -abs(kv[1]))[:5]
    lgbm_li = ", ".join(f"{k}" for k, _ in lgbm_top5)
    lrc_li = ", ".join(f"{k} ({v:+.2f})" for k, v in lrc_top)

    retest = "".join(f"<li>{esc(t)}</li>" for t in MS["retest_at_5y"])

    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>SuryaDhana ML Pilot</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">

<header class="hero">
  <div class="eyebrow">SuryaDhana · quant ML · NSE EOD universe · 6-month pilot</div>
  <h1>Which algorithm earns the 5-year run?</h1>
  <p class="sub">Thirteen candidates, one fixed protocol: purged walk-forward on ~2,100 NSE tickers,
  four monthly CV folds (Apr–Jul 2026) plus one untouched holdout. Primary task
  <b>beat_mkt_20d</b> — will a stock beat the universe median over the next 20 sessions.
  The question was <i>which algorithm</i>, not whether the edge is already tradable.</p>

  <div class="verdict">
    <div class="vhead">Verdict · 2026-10-15</div>
    <p>Carry <b>LightGBM on the 10-feature selected subset</b> to the 5-year run, with
    <b>L2 logistic regression</b> retained as the interpretable benchmark. Drop RL and the RNNs.</p>
    <div class="badges">
      <span class="badge">★ Champion <b>lgbm_fs_selected</b> · 10 features · ~32 s/run</span>
      <span class="badge">Benchmark <b>lr_l2</b> (C=0.01) · drift monitor</span>
      <span class="badge">Dropped <b>rl_reinforce</b>, <b>gru/lstm</b>, decision_tree, lr_l1/elastic</span>
    </div>
  </div>

  <div class="tiles">
    <div class="tile"><div class="v">0.5307 <span class="dim2" style="font-size:18px">± 0.018</span></div>
      <div class="k">CV AUC — clear of chance at 95%</div>
      <div class="d">Pooled-CV CI [{a4(sig_ch["pooled_cv_auc_ci95"][0])}, {a4(sig_ch["pooled_cv_auc_ci95"][1])}], P(&gt;0.5)=1.000 —
      the only candidate at P=1.000; re-validated clean at 0.5314 ± 0.014.</div></div>
    <div class="tile"><div class="v">5 / 5</div>
      <div class="k">windows at AUC ≥ 0.50 — alone in the league</div>
      <div class="d">Worst fold {a4(champ["min_fold_auc"])} (clean {a4(champ_clean["min_fold_auc"])});
      every rival dips below chance in at least one window.</div></div>
    <div class="tile"><div class="v">5 / 5 <span class="dim2" style="font-size:18px">positive</span></div>
      <div class="k">top-decile 20d excess, every window</div>
      <div class="d">+0.96, +4.58, +1.02, +2.82, +2.12% across the four folds and the holdout.</div></div>
  </div>
</header>

<section id="league-sec">
  <div class="sec-eyebrow">01 · League table</div>
  <h2>Primary task — beat_mkt_20d</h2>
  <p class="lede">Frozen pre-fix runs; <i>· clean</i> rows are the post-incident re-validation
  (separate bootstrap cohort — their test calendars differ). Click a column to sort.
  lr_l1 and lr_elastic match lr_l2 to ~3 decimals and are folded into one anchor row.</p>
  <div class="card">{league_table_html()}
  <p class="cap">★ champion. Holdout decile spread = top-minus-bottom decile mean 20-day excess return.
  Base rate 0.500 by construction. Feature-count ablation (section 7): top-10 beats top-5/15/20/30.</p></div>
  <details><summary>Secondary task up_5d — sanity check only, never for selection</summary>
    <div class="card">{up5d_table_html()}
    <p class="cap">up_5d is regime-exposed (monthly base rate 0.37–0.72) and its CV means are inflated by the
    one-sided 2026-04 fold (base rate 0.72) in every family — linear 0.553 → 0.514 ex-April; the champion
    still leads it ex-April (0.533). label_up_5d also hard-codes 0 where the 5-day forward close is missing
    (~1.6% of rows; fixed in the cleaned rebuild).</p></div>
  </details>
</section>

<section id="regime">
  <div class="sec-eyebrow">02 · The regime problem</div>
  <h2>CV and the holdout rank models in near-opposite order</h2>
  <p class="lede">12 of 13 candidates scored <b>better</b> on the single Aug→mid-Sep holdout than on CV
  (mean +3.2 AUC pts), and the two views invert the ranking (Spearman −0.60). The paired bootstrap says both
  directions are “significant” under date-resampling — so the disagreement is <b>regime-window dependence, not
  sampling noise</b>. April was adversarial for everyone; the holdout was friendly to everyone.</p>
  <div class="card">
    {heatmap_html()}
    <div class="hm-key">AUC vs chance:&nbsp;
      <span class="hm-n3"></span><span class="hm-n2"></span><span class="hm-n1"></span>
      &lt; 0.50 &nbsp;<span class="hm-0"></span> ≈ 0.50 &nbsp;
      <span class="hm-p1"></span><span class="hm-p2"></span><span class="hm-p3"></span><span class="hm-p4"></span> &gt; 0.50</div>
    <p class="cap">The 2026-04 column is the stress test: only the champion and RL stay at or above 0.50.
    The holdout column is uniformly blue — one friendly 6-week window used once.</p>
  </div>
  <div class="card"><div class="scroll"><div class="wide-svg">{svg_slope()}</div></div>
    <p class="cap">Adjudication: four monthly folds (including adversarial April) outvote one friendly window —
    algorithm choice rests on CV mean + worst-fold floor; the holdout is a no-catastrophe check.
    The champion is the only model whose holdout ≈ CV (−0.009 vs +0.01…+0.06 for the rest): the least
    window-sensitive model in the league. Full-feature XGB/LGBM (orange) top the holdout at ~0.56 from
    bottom-tier CV — exactly the profile the 5-year run must adjudicate.</p></div>
</section>

<section id="signif">
  <div class="sec-eyebrow">03 · Significance</div>
  <h2>Who is actually above chance?</h2>
  <p class="lede">Date-block bootstrap on the saved predictions: test dates resampled within folds,
  B=1000, seed 108, all models paired on identical draws.</p>
  <div class="card"><div class="scroll"><div class="wide-svg">{svg_ci_dots()}</div></div>
    <p class="cap">Pooled-CV AUC with 95% CI; open dashed markers are the clean re-validations.
    Blue = CI clear of 0.50; red = significantly below (the 1-feature momentum rank was mildly contrarian
    in this sample); gray = not distinguishable from coin-flipping — which includes full-feature XGB/LGBM
    (P=0.61/0.65), MLP, LSTM, RL and the frozen lr_l2 (P=0.90). On the holdout, every model clears 0.5 at
    P=1.000 — the friendly-window effect in one line.</p></div>
  <div class="card"><div class="scroll"><div class="wide-svg">{svg_pair_deltas()}</div></div>
    <p class="cap">Paired champion-minus-rival deltas: <span style="color:var(--s1);font-weight:700">● CV mean</span> vs
    <span style="color:var(--s2);font-weight:700">○ holdout</span>. Champion vs lr_l2: +{a4(pr_lr["delta_cv_mean"])} on CV
    (CI [{a4(pr_lr["delta_cv_mean_ci95"][0])}, {a4(pr_lr["delta_cv_mean_ci95"][1])}]) but a dead heat on the holdout
    (−0.0008, P=0.46) — with only 4 regime-months the bootstrap cannot capture fold-level regime risk, so the CV gap is
    suggestive, not settled. Against XGB the sign flips outright (+0.0284 CV, −0.0426 holdout). Individual CIs are
    ±0.009–0.012 wide: the mid-table ordering is noise — do not read order into ~0.01–0.02 differences.</p></div>
</section>

<section id="roc">
  <div class="sec-eyebrow">04 · ROC curves</div>
  <h2>Holdout ROC — seven models</h2>
  <p class="lede">Computed from the saved per-row scores on the frozen holdout (50,733 rows, 32 dates).
  Curves hug the diagonal: this is a thin, portfolio-grade edge, not a classifier.</p>
  <div class="card">
    <figure id="rocfig"><div class="scroll" style="max-width:600px;margin-inline:auto"><div id="rocsvg-w">{svg_roc().replace('<svg ', '<svg id="rocsvg" ', 1)}</div></div></figure>
    {roc_legend_html()}
    <p class="cap">Hover or tap a legend entry to isolate a curve. On this one window the full-feature models
    (xgboost 0.5646, rl 0.5680) lead — the same models that are indistinguishable from chance on CV (section 03).</p>
  </div>
</section>

<section id="econ">
  <div class="sec-eyebrow">05 · Economics</div>
  <h2>Champion decile economics — 20-day excess return</h2>
  <p class="lede">Mean y_excess_20d by score decile (D1 lowest → D10 highest), per out-of-sample window.
  Top-decile excess is positive in all five; the full spread is positive in 3 of 4 folds plus the holdout.</p>
  <div class="card">{decile_multiples_html()}
    <p class="cap">Shared scale, % per 20 sessions. The monotonic staircase shows up in trend months
    (May, Jul); April compresses to noise — consistent with its fold AUC of 0.5014.</p></div>
  <h3 style="margin-top:18px;font-size:16px">Top-decile mean excess, window by window</h3>
  <div class="strip">{strip}</div>
  <p class="cap" style="font-family:var(--sans);color:var(--muted);font-size:13px;margin-top:8px">
  Counterpoint: the lr_l2 anchor's holdout decile spread is <b style="color:var(--bad)">−2.33%</b> — its score
  extremes invert economically — and it sat below AUC 0.50 in 2 of 4 folds. A benchmark, not a scorer.
  The champion's clean-rerun holdout spread is mildly negative (−0.40pt): flagged for the 5-year re-test.</p>
</section>

<section id="features">
  <div class="sec-eyebrow">06 · Feature intelligence</div>
  <h2>Ten features carry the signal</h2>
  <p class="lede">Combined rank = average of univariate AUC, LightGBM gain and permutation importance;
  one representative per redundancy cluster (9 clusters at |ρ|&gt;0.9). k chosen on CV mean only, never holdout.</p>
  <div class="card"><div class="scroll"><div class="wide-svg">{svg_elim()}</div></div>
    <p class="cap">Feature-count ablation: CV AUC peaks at k=10 (0.5307); k=5 loses the ranks (0.5125),
    k=15–30 add variance, not signal (0.5217–0.5231). The extra 41 features buy nothing.</p></div>
  <div class="cols2">
    <div class="card" style="margin-top:0">{feature_table_html()}
      <p class="cap">Mix: 4 long momentum, 2 volatility, 2 delivery, 1 trend/location, 1 short momentum.
      cs_rank_mom_20 enters with a <i>negative</i> univariate sign — short-term rank inverts while long
      momentum carries. mom_12_1 is the strongest single feature (univariate AUC 0.5293) despite being
      58% NaN in the pilot.</p></div>
    <div class="panel" style="margin-top:0">
      <h3>The NSE delivery block</h3>
      <p>NSE publishes, per stock and session, the share of traded volume actually taken to delivery rather
      than squared off intraday — a conviction signal most price-only pipelines never see. Two delivery
      features (deliv_pct_sma_20, deliv_pct) made the subset on merit: the dataset's main non-price information.</p>
      <h3 style="margin-top:14px">Redundancy</h3>
      <p>18 pairs at |ρ|&gt;0.85, 9 clusters at |ρ|&gt;0.9 (cs_rank twins, SMA-distance/RSI family,
      mom_12_1↔ret_252d ρ=0.93) — fine for trees, destabilizing for linear coefficients; one representative
      each enters the subset.</p>
      <p class="cap" style="margin-top:10px">Full-model views agree: LGBM gain top-5 — {esc(lgbm_li)};
      lr_l2 per-1σ top coefficients — {esc(lrc_li)}.</p>
    </div>
  </div>
</section>

<section id="data">
  <div class="sec-eyebrow">07 · Data &amp; quality</div>
  <h2>1.22M raw rows → 488k scored rows</h2>
  <div class="card"><div class="funnel">{funnel}</div></div>
  <div style="margin-top:14px">{month_charts_html()}</div>
  <p class="cap" style="font-family:var(--sans);color:var(--muted);font-size:13px;margin-top:8px">
  Splits audit: first fold trains on 269,271 rows / 189 days vs 404,812 / 277 for the holdout; all test
  base rates 0.500–0.502. The regime chart is why beat_mkt_20d (cross-sectionally demeaned) is the primary
  task and up_5d (market-beta-exposed) is not.</p>

  <div class="card incident">
    <div class="sec-eyebrow" style="color:var(--neg)">Data-quality incident · found mid-bake-off · resolved</div>
    <h3 style="margin-top:6px">12 phantom “holiday-echo” days (2.9% of sessions)</h3>
    <p style="font-family:var(--sans);font-size:14.5px">The archive mirror re-served the previous session's
    bhavcopy on 2026 NSE holidays instead of 404ing — every ticker duplicated the prior session's OHLC+volume.
    Caught by a cross-sectional exact-duplicate scan. Zero-return phantom bars dampen short-horizon features and
    dilute label horizons near holidays; the contamination is common-mode across models, so the ranking stands.</p>
    <div class="days">{days}</div>
    <div class="steps">
      <div class="step"><h4>1 · Fix</h4><p>nse_historical_ingest.py patched: 2026 holiday calendar + duplicate-day
      guard (frame vs stored-day fingerprint); phantom days purged, dataset rebuilt (526,180 → 507,163 rows);
      label_up_5d NaN-encoding fixed in the same rebuild.</p></div>
      <div class="step"><h4>2 · Re-validate</h4><p>Champion and anchors re-run on cleaned data:
      lgbm_fs_selected CV <b>0.5307 → 0.5314</b> (std 0.018 → 0.014), lr_l2 0.513 → 0.517,
      baseline_mom 0.493 → 0.491 — <b>ranking unchanged</b>. League keeps the frozen pre-fix runs;
      the <i>· clean</i> rows are the robustness check.</p></div>
      <div class="step"><h4>3 · Cross-pipeline check</h4>{crossval_table_html()}
      <p style="font-size:12.5px;color:var(--muted);margin-top:4px">NH−NL differs by definition
      (universe &amp; history window) — same sign and order.</p></div>
    </div>
  </div>
</section>

<section id="failed">
  <div class="sec-eyebrow">08 · What didn't work</div>
  <h2>Negative results, kept on the record</h2>
  <div class="cols2">
    <div class="panel"><span class="tag drop">Dropped · RL</span>
      <h3>rl_reinforce — a bandit that loses to a free heuristic</h3>
      <p>CV AUC 0.5085 ± 0.022; on 2 of 4 folds REINFORCE never beat its own untrained initialization on
      inner-validation reward. Its own portfolio sim loses to the free one-feature mom-20 heuristic
      out-of-sample: net +1.76% vs +2.71%/20d CV-agg, +4.67% vs +5.15% holdout. The holdout AUC of 0.568 is
      one momentum-friendly 32-date window, not stability. ~160–235 one-shot episodes per fold with a single
      noisy scalar reward is not an RL-sized problem.</p>
      <div class="kv"><span>CV <b>0.5085</b></span><span>beat own init <b>2/4 folds failed</b></span>
      <span>vs mom20 sim <b>lost OOS</b></span></div></div>
    <div class="panel"><span class="tag drop">Dropped · deep</span>
      <h3>gru / lstm (and the MLP ceiling)</h3>
      <p>GRU at or below chance on CV (0.4889 ± 0.011, significantly <i>below</i> 0.5 pooled); LSTM 0.5018.
      A 20-session temporal view adds nothing at this scale. The tabular MLP (0.5025, ~3 AUC pts under the
      champion) shows the deep stack itself isn't paying on six months of EOD data either.</p>
      <div class="kv"><span>GRU CV <b>0.4889</b></span><span>LSTM CV <b>0.5018</b></span>
      <span>MLP CV <b>0.5025</b></span><span>champion <b>0.5307</b></span></div></div>
  </div>
  <p class="cap" style="font-family:var(--sans);color:var(--muted);font-size:13px">Also dropped:
  decision_tree (strictly dominated by its ensembles) and lr_l1/lr_elastic (identical to lr_l2 to ~3 decimals —
  keep one linear anchor).</p>
</section>

<section id="method">
  <div class="sec-eyebrow">09 · Methodology</div>
  <h2>Protocol — fixed, shared, no per-model deviation</h2>
  <div class="meth">
    <div class="m"><h4>Splits</h4><p>Purged walk-forward, <b>22-session embargo</b> (covers the 20-session label
    overlap). Folds = test months 2026-04…07 (88 test dates); holdout 2026-08-03 → 09-11/15 (32 dates),
    <b>used once</b>, never for tuning.</p></div>
    <div class="m"><h4>Tuning</h4><p>Hyper-parameters tuned on the first two CV folds (2026-04/05) or inner
    time-ordered splits of train only; identical preprocessing harness; <b>seed 108 everywhere</b>.</p></div>
    <div class="m"><h4>Universe &amp; label</h4><p>Point-in-time filter: close ≥ ₹10, trailing-20d median turnover
    ≥ ₹1 crore (no survivorship bias). beat_mkt_20d entered at next open; y_clean_20d masks split/suspension-poisoned
    windows (7.2% of rows).</p></div>
    <div class="m"><h4>Inference</h4><p>Date-block bootstrap on saved predictions: test dates resampled within
    folds, B=1000, models paired on identical draws. Headline metric ROC AUC; economics on score deciles of
    y_excess_20d.</p></div>
  </div>
  <h3 style="margin-top:20px;font-size:17px">Limitations</h3>
  <ul class="lims">
    <li><b>Six months ≈ 4 regime-months.</b> The bootstrap conditions on those months and cannot capture
    fold-level regime risk — the dominant risk this sample exposed. The champion-vs-linear CV gap is
    suggestive, not settled.</li>
    <li><b>Prices are unadjusted</b> (no corporate-action feed): the y_clean_20d mask is the only defense;
    never evaluate on masked rows.</li>
    <li><b>No carry or announcement features</b> — they need F&amp;O/announcement feeds this repo doesn't ingest.</li>
    <li><b>2026 archive provenance.</b> The 2026 portion trades every weekday (no holiday closures — a simulated
    continuous calendar), and the holiday-echo incident came from the same archive mirror: build no
    calendar/seasonality features on 2026 data.</li>
    <li><b>up_5d label defect</b> (NaN forward returns hard-labeled 0, ~1.6% of rows) is fixed in the cleaned
    rebuild; the fix applies to future builds — treat every frozen up_5d number as a sanity check only.</li>
    <li><b>Long-lookback features are mostly imputed early on:</b> ret_252d / mom_12_1 / dist_200dma are
    58 / 58 / 21% NaN in the pilot and "switch on" through 2026.</li>
  </ul>
</section>

<section id="retest">
  <div class="sec-eyebrow">10 · Next</div>
  <h2>Must be re-tested at 5-year scale</h2>
  <ol class="lims">{retest}</ol>
</section>

<footer>
  <p>SuryaDhana pilot report · generated {esc(MS["generated_at"])} by <code>ml/eval_aggregate.py</code> → this page by
  <code>ml/make_report.py</code> (inline SVG, no external resources). Seed {SEED}; bootstrap B=1000;
  aggregate runtime {MS["runtime_seconds"]:.0f}s. Sources: <code>ml/results/*.json</code>,
  <code>ml/results/preds/*.parquet</code>; narrative spine <code>ml/MODEL_SELECTION.md</code>.
  ROC curves and decile bars recomputed from the saved per-row scores and verified against the frozen
  harness numbers at build time. League numbers are the frozen pre-fix runs; <i>· clean</i> rows re-validate
  on the rebuilt dataset.</p>
</footer>

</div>
<div id="tip" role="status" aria-live="polite"></div>
<script>{JS}</script>
</body>
</html>
"""
    return html


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    html = build_html()
    OUT.write_text(html)
    print(f"wrote {OUT} ({len(html):,} bytes, {len(html) / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
