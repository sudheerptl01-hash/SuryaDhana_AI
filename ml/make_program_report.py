#!/usr/bin/env python3
"""Generate ml/report/program_report.html: the SuryaDhana research program's capstone report.

Narrative of record: ml/PROGRAM_REPORT.md (program lead). This page says what that file says, in its
order and with its hedges; ml/results/scale5y/SCALE5Y.md supplies the wording of the 5-year results.
Every number that exists in a JSON/CSV artifact is loaded here at build time and formatted, never
typed. The few figures that exist only in Markdown (the full-history data-store scan, literature
calibration points, three strategy/label memo figures) are typed once in MD_ONLY with their source.

Inputs (read-only; nothing is retrained and no prediction parquet is opened):
  ml/data/{manifest,splits}.json
  ml/results/scale5y/{manifest_5y,splits_5y,nested_selection}.json and <model>__beat_mkt_20d.json
  ml/results/label_study/{label_summary,label_variants,model_level}.json
  ml/results/feature_study/{eda_features,feature_ab_verdict,manifest_fe}.json
  ml/results/feature_sufficiency/{feature_sufficiency,ab_results}.json
  ml/results/sota/{league_summary,exposures}.json and the per-model JSONs
  ml/results/strategy/{strategy.json,champion_monthly.csv}
  ml/results/audit/audit.json, ml/results/model_selection.json and the pilot per-model JSONs
  ml/results/{holiday_duplicates,data_profile}.json

5-year outputs consumed when present (written by ml/scale5y_report.py / ml/scale5y_nested.py):
  scale5y_summary.json, bootstrap_5y.json, regimes_5y.json, portfolio_5y.json,
  nested_ensemble_rank__beat_mkt_20d.json (+ members), SCALE5Y.md.
  A file that is absent, unreadable, partial, or from a smoke run (bootstrap B < 1000) renders a
  muted "pending" card naming the file instead of numbers; the build never fails on them.

Run:  cd /home/user/SuryaDhana_AI && python3 -m ml.make_program_report
      [--pending-dir DIR] [--out FILE]   (QA only: read the 5-year outputs from DIR / write FILE)
Deterministic: identical inputs give byte-identical HTML (no clock, fixed orderings).
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import math
from pathlib import Path
from types import SimpleNamespace

ML = Path(__file__).resolve().parent
REPO = ML.parent
RES = ML / "results"
S5 = RES / "scale5y"
OUT = ML / "report" / "program_report.html"

REPORT_DATE = "2026-10-19"
TASK = "beat_mkt_20d"
B_FINAL = 1000                 # ml/scale5y_report.py default --B; a smaller B is a smoke run
FULL_WINDOW_ROWS = 580_000     # "~580k": folds whose 504-session window is full (PROGRAM_REPORT.md §6.3)
MINUS = "−"

CORE5 = ["all51", "nested_lgbm", "champion10", "lr_l2", "nested_lr_l2", "baseline_mom"]
ENS = "nested_ensemble_rank"
MEMBERS = ["nested_lambdarank", "nested_catboost"]
HEUR = "heuristic_mom20"
GATE_MODELS = ["nested_lgbm", "all51", ENS]
PAPER_BASKET = "liq_top_decile"
STRIP = ["all51", "nested_lgbm", "champion10", "lr_l2", "baseline_mom", ENS]
SLOT = {"all51": 1, "nested_lgbm": 2, "champion10": 3, "lr_l2": 4, "baseline_mom": 5, ENS: 7}
NAME5 = {
    "all51": "LightGBM, all features",
    "nested_lgbm": "LightGBM, nested yearly selection",
    "champion10": "LightGBM, pilot 10 features",
    "lr_l2": "L2 logistic, all features",
    "nested_lr_l2": "L2 logistic, nested selection",
    "baseline_mom": "Momentum rule",
    ENS: "Rank-average ensemble (nested)",
    "nested_lambdarank": "LambdaRank (ensemble member)",
    "nested_catboost": "CatBoost, 600 trees (ensemble member)",
    HEUR: "Momentum rank (no fit)",
}

# Figures that exist only in Markdown (no JSON/CSV carries them). Source named per entry.
MD_ONLY = {
    # ml/PROGRAM_REPORT.md §3: the lead's full-history scan of nse_market.duckdb
    "store_rows": 3_078_294, "store_sessions": 1_245, "store_first": "2021-10-01",
    "store_last": "2026-10-16", "store_tickers": 4_219, "store_feature_rows": 2_722_591,
    "sessions_by_year": {"2021": 63, "2022": 248, "2023": 245, "2024": 247, "2025": 247, "2026": 195},
    "echo_max_share": "0.35%", "echo_max_date": "2026-07-23", "ingest_tests": "19 of 19",
    # ml/research/SOTA_FORECASTING.md: literature calibration points
    "gkx_corr": "0.06", "qlib_ic": "0.045", "gkx_r2_gbm": "0.33 to 0.40%", "gkx_r2_lin": "0.11 to 0.27%",
    # ml/results/label_study/LABEL_STUDY.md, verdict 4(a)
    "univ_excess_range": "+1.4% to +2.0%", "champ_vs_mean_windows": "3 of 5",
    # ml/results/strategy/STRATEGY.md (not stored in strategy.json)
    "naive_flip": MINUS + "5.3%", "cost_realistic": "15 to 25", "fno_names": "about 200",
    # ml/results/sota/SOTA_MODELS.md
    "train_dates": "140 to 230", "indep_xs": "7 to 11",
}
MD_ONLY_SOURCES = [
    ("Data-store scan: rows, sessions, tickers, sessions per year, largest echo share", "ml/PROGRAM_REPORT.md §3"),
    ("Literature calibration (GKX, Qlib) ", "ml/research/SOTA_FORECASTING.md"),
    ("Universe mean minus median per 20 days; champion vs universe mean in 3 of 5 windows",
     "ml/results/label_study/LABEL_STUDY.md"),
    ("Naive fully-invested flip to " + MINUS + "5.3%; realistic cost 15 to 25 bps; about 200 F&O names",
     "ml/results/strategy/STRATEGY.md"),
    ("140 to 230 training dates, 7 to 11 independent cross-sections", "ml/results/sota/SOTA_MODELS.md"),
]

D = SimpleNamespace()   # closed artifacts
P = SimpleNamespace()   # 5-year outputs (may be pending)
FACTS: dict[str, str] = {}      # verdict-board numbers as rendered; read by the QA script
LOADED: dict[str, str] = {}     # input -> read / absent / unreadable / not used (smoke run)


# ===================================================================== loading
def rel(p: Path) -> str:
    try:
        return str(p.relative_to(REPO))
    except ValueError:
        return str(p)


def load_json(p: Path, label: str | None = None, required: bool = True):
    name = label or rel(p)
    try:
        obj = json.loads(p.read_text())
    except FileNotFoundError:
        if required:
            raise SystemExit(f"make_program_report: missing required input {name}")
        LOADED[name] = "absent"
        return None
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        if required:
            raise SystemExit(f"make_program_report: unreadable required input {name}")
        LOADED[name] = "unreadable at build time"
        return None
    LOADED[name] = "read"
    return obj


def read_csv(p: Path) -> list[dict]:
    with p.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    LOADED[rel(p)] = "read"
    return rows


PILOT_MODELS = ["lgbm_fs_selected_clean", "lr_l2_clean", "random_forest", "rl_reinforce", "decision_tree",
                "lightgbm", "mlp", "xgboost", "lstm", "baseline_mom", "gru", "baseline_mom_clean"]
SOTA_MODELS = ["ensemble_rank", "catboost_fixed600", "lgbm_lambdarank", "lgbm_huber", "cs_transformer",
               "patchtst_lite", "dlinear"]


def load_closed() -> None:
    D.man_pilot = load_json(ML / "data" / "manifest.json")
    D.splits_pilot = load_json(ML / "data" / "splits.json")
    D.man5 = load_json(S5 / "manifest_5y.json")
    D.splits5 = load_json(S5 / "splits_5y.json")
    D.sel = load_json(S5 / "nested_selection.json")
    D.m5 = {m: load_json(S5 / f"{m}__{TASK}.json") for m in CORE5}
    D.ms = load_json(RES / "model_selection.json")
    D.pilot = {m: load_json(RES / f"{m}__{TASK}.json") for m in PILOT_MODELS}
    D.hd = load_json(RES / "holiday_duplicates.json")
    D.dp = load_json(RES / "data_profile.json")
    ls = RES / "label_study"
    D.lsum = load_json(ls / "label_summary.json")
    D.lvar = load_json(ls / "label_variants.json")
    D.lmod = load_json(ls / "model_level.json")
    D.n_label_json = len(sorted(ls.glob("*.json")))
    fs = RES / "feature_study"
    D.eda = load_json(fs / "eda_features.json")
    D.fab = load_json(fs / "feature_ab_verdict.json")
    D.fe = load_json(fs / "manifest_fe.json")
    D.suff = load_json(RES / "feature_sufficiency" / "feature_sufficiency.json")
    D.suff_ab = load_json(RES / "feature_sufficiency" / "ab_results.json")
    D.sota = load_json(RES / "sota" / "league_summary.json")
    D.expo = load_json(RES / "sota" / "exposures.json")
    D.sota_m = {m: load_json(RES / "sota" / f"{m}__{TASK}.json") for m in SOTA_MODELS}
    D.strat = load_json(RES / "strategy" / "strategy.json")
    D.monthly = read_csv(RES / "strategy" / "champion_monthly.csv")
    D.audit = load_json(RES / "audit" / "audit.json")


def load_pending(pdir: Path) -> None:
    def lab(nm: str) -> str:
        return f"ml/results/scale5y/{nm}"

    nfolds = len(D.splits5["folds"])
    P.boot_file = load_json(pdir / "bootstrap_5y.json", lab("bootstrap_5y.json"), required=False)
    P.summary_raw = load_json(pdir / "scale5y_summary.json", lab("scale5y_summary.json"), required=False)
    P.regimes_raw = load_json(pdir / "regimes_5y.json", lab("regimes_5y.json"), required=False)
    P.port = load_json(pdir / "portfolio_5y.json", lab("portfolio_5y.json"), required=False)
    P.m = {}
    for m in [ENS] + MEMBERS:
        js = load_json(pdir / f"{m}__{TASK}.json", lab(f"{m}__{TASK}.json"), required=False)
        if js is not None and len(js.get("folds", [])) != nfolds:
            LOADED[lab(f"{m}__{TASK}.json")] = f"partial ({len(js.get('folds', []))} folds), not used"
            js = None
        if js is not None:
            P.m[m] = js
    P.scale5y_md = (pdir / "SCALE5Y.md").exists()
    LOADED[lab("SCALE5Y.md")] = "read (narrative)" if P.scale5y_md else "absent"
    # run identity: every scale5y_report run writes bootstrap_5y.json first, then regimes, summary
    bt = P.boot_file
    P.boot_B = (bt or {}).get("design", {}).get("B")
    P.boot_at = (bt or {}).get("generated_at", "")
    P.final = bt is not None and P.boot_B is not None and P.boot_B >= B_FINAL
    if bt is not None and not P.final:
        LOADED[lab("bootstrap_5y.json")] = f"smoke run (B = {P.boot_B}), not used"
    P.boot = bt if P.final else None
    s = P.summary_raw
    if s is not None:
        sb = s.get("bootstrap", {}).get("design", {}).get("B")
        if not (P.final and sb is not None and sb >= B_FINAL and s.get("generated_at", "") >= P.boot_at):
            LOADED[lab("scale5y_summary.json")] = f"smoke run (B = {sb}), not used"
            s = None
    P.summary = s
    r = P.regimes_raw
    if r is not None and not (P.final and r.get("generated_at", "") >= P.boot_at):
        LOADED[lab("regimes_5y.json")] = "from a smoke run, not used"
        r = None
    P.regimes = r


# ===================================================================== formatting
def E(s) -> str:
    return html.escape(str(s), quote=True)


def neg(s: str) -> str:
    return s.replace("-", MINUS)


def f(x: float, d: int = 4) -> str:
    return neg(f"{x:.{d}f}")


def sg(x: float, d: int = 3) -> str:
    return neg(f"{x:+.{d}f}")


def pc(x: float, d: int = 1) -> str:
    """Signed percent of a fraction."""
    return neg(f"{x * 100:+.{d}f}%")


def pu(x: float, d: int = 0) -> str:
    """Unsigned percent of a fraction."""
    return neg(f"{x * 100:.{d}f}%")


def n(x) -> str:
    return f"{int(x):,}"


MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]


def mname(ym: str) -> str:
    y, m = ym[:7].split("-")
    return f"{MONTHS[int(m) - 1]} {y}"


def mshort(ym: str) -> str:
    y, m = ym[:7].split("-")
    return f"{MONTHS[int(m) - 1][:3]} {y}"


WORDS = {0: "zero", 1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven",
         8: "eight", 9: "nine", 10: "ten", 11: "eleven", 12: "twelve", 13: "thirteen"}


def word(k: int, cap: bool = False) -> str:
    w = WORDS.get(k, str(k))
    return w[:1].upper() + w[1:] if cap else w


def rng(lo: float, hi: float, fmt) -> str:
    a, b = fmt(lo), fmt(hi)
    return a if a == b else f"{a} to {b}"


def lin(v: float, d0: float, d1: float, p0: float, p1: float) -> float:
    return p0 + (v - d0) / (d1 - d0) * (p1 - p0)


def hbar(x0: float, x1: float, yc: float, h: float, r: float = 4) -> str:
    """Horizontal bar, square at the baseline x0, rounded at the data end x1."""
    y0, y1 = yc - h / 2, yc + h / 2
    w = abs(x1 - x0)
    r = min(r, w, h / 2)
    if w < 0.5:
        return ""
    if x1 >= x0:
        return (f"M{x0:.1f},{y0:.1f} H{x1 - r:.1f} A{r:.1f},{r:.1f} 0 0 1 {x1:.1f},{y0 + r:.1f} "
                f"V{y1 - r:.1f} A{r:.1f},{r:.1f} 0 0 1 {x1 - r:.1f},{y1:.1f} H{x0:.1f} Z")
    return (f"M{x0:.1f},{y0:.1f} H{x1 + r:.1f} A{r:.1f},{r:.1f} 0 0 0 {x1:.1f},{y0 + r:.1f} "
            f"V{y1 - r:.1f} A{r:.1f},{r:.1f} 0 0 0 {x1 + r:.1f},{y1:.1f} H{x0:.1f} Z")


def vbar(xc: float, w: float, yb: float, yt: float, r: float = 4) -> str:
    """Vertical column, square at the baseline yb, rounded at the data end yt."""
    x0, x1 = xc - w / 2, xc + w / 2
    hgt = abs(yb - yt)
    r = min(r, w / 2, hgt)
    if hgt < 0.5:
        return ""
    if yt <= yb:
        return (f"M{x0:.1f},{yb:.1f} V{yt + r:.1f} A{r:.1f},{r:.1f} 0 0 1 {x0 + r:.1f},{yt:.1f} "
                f"H{x1 - r:.1f} A{r:.1f},{r:.1f} 0 0 1 {x1:.1f},{yt + r:.1f} V{yb:.1f} Z")
    return (f"M{x0:.1f},{yb:.1f} V{yt - r:.1f} A{r:.1f},{r:.1f} 0 0 0 {x0 + r:.1f},{yt:.1f} "
            f"H{x1 - r:.1f} A{r:.1f},{r:.1f} 0 0 0 {x1:.1f},{yt - r:.1f} V{yb:.1f} Z")


def svg_open(w: int, h: int, label: str, extra: str = "") -> str:
    return (f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{E(label)}"{extra}>'
            f'<title>{E(label)}</title>')


def chip(status: str, text: str | None = None) -> str:
    s = status.lower()
    glyph = {"pass": "✓", "fail": "✕", "pending": "…", "info": "i"}.get(s, "")
    return f'<span class="st {s}"><span aria-hidden="true">{glyph}</span> {E(text or status.upper())}</span>'


def pending_card(title: str, files: list[str], running: str, note: str = "") -> str:
    fl = ", ".join(f"<code>{E(x)}</code>" for x in files)
    return (f'<div class="pending"><div class="ph">Pending</div><h4>{E(title)}</h4>'
            f'<p>Waits for {fl}. {E(running)}</p>{f"<p>{note}</p>" if note else ""}'
            f'<p class="dim2">Re-run <code>python3 -m ml.make_program_report</code> when it lands; this card '
            f'is replaced by the numbers.</p></div>')


def src(*paths: str) -> str:
    return '<span class="srcs">' + " · ".join(f"<code>{E(p)}</code>" for p in paths) + "</span>"


# ===================================================================== derived data
def stats5(js: dict) -> dict:
    folds = js["folds"]
    a = [x["auc"] for x in folds]
    names = [x["fold"] for x in folds]
    mean = sum(a) / len(a)
    assert abs(mean - js["cv_auc_mean"]) < 1e-9, js["model"]
    wi = min(range(len(a)), key=lambda i: a[i])
    ds = [x.get("decile_spread") for x in folds]
    dsv = [x for x in ds if x is not None]
    nf = [x.get("n_features") for x in folds if x.get("n_features")]
    sets = js.get("nested_feature_sets") or {}
    if js.get("n_features"):
        feats = str(js["n_features"])
    elif sets:
        sz = sorted(len(v) for v in sets.values())
        feats = f"{sz[0]} to {sz[-1]}" if sz[0] != sz[-1] else str(sz[0])
    elif nf:
        feats = f"{min(nf)} to {max(nf)}"
    else:
        feats = "—"
    per_year = {}
    for y in sorted({x[:4] for x in names}):
        v = [a[i] for i, nm in enumerate(names) if nm.startswith(y)]
        per_year[y] = (sum(v) / len(v), len(v))
    f39 = [a[i] for i, nm in enumerate(names) if nm <= "2026-03"]
    ho = js.get("holdout") or {}
    return {"model": js["model"], "cv": js["cv_auc_mean"], "sd": js["cv_auc_std"], "auc": dict(zip(names, a)),
            "n": len(a), "ge": sum(x >= 0.5 for x in a), "worst": a[wi], "worst_m": names[wi],
            "ho": ho.get("auc"), "ho_ds": ho.get("decile_spread"),
            "mds": sum(dsv) / len(dsv) if dsv else None, "mds_pos": sum(x > 0 for x in dsv), "n_ds": len(dsv),
            "feats": feats, "per_year": per_year, "cv39": sum(f39) / len(f39), "n39": len(f39),
            "ntrain": {x["fold"]: x.get("n_train") for x in folds}}


def derive() -> None:
    D.folds = [s["name"] for s in D.splits5["folds"]]
    D.M5 = {m: D.m5[m] for m in CORE5}
    if ENS in P.m:
        D.M5[ENS] = P.m[ENS]
    for m in MEMBERS:
        if m in P.m:
            D.M5[m] = P.m[m]
    D.S5 = {m: stats5(js) for m, js in D.M5.items()}
    for m, s in D.S5.items():
        assert list(s["auc"]) == D.folds, m
    nt = D.S5["all51"]["ntrain"]
    D.short_folds = [fo for fo in D.folds if nt[fo] < FULL_WINDOW_ROWS]
    assert D.short_folds == D.folds[:len(D.short_folds)]
    D.first_full = D.folds[len(D.short_folds)]
    D.run = [fo for fo in D.folds if "2025-09" <= fo <= "2026-02"]
    D.crash = "2026-03"
    A = {t["id"]: t for t in D.audit["tests"]}
    D.A = A
    D.Tab = {r["id"]: r for r in D.audit["table"]}
    D.sota_rows = {r["model"]: r for r in D.sota["rows"]}
    D.BAR = D.fab["rebuild_bar_cv"]
    assert abs(D.BAR - D.sota["pass_mark"]) < 1e-12
    D.CTRL = D.fab["control_clean_cv"]
    D.sm = D.strat["models"]
    D.IC = D.eda["ic_stability"]
    D.eda_months = sorted({mo for v in D.IC.values() for mo in v["monthly_ic"]})


def gates_from_portfolio() -> dict:
    """Gates 3 and 5 scored exactly as ml/scale5y_report.py gates() from portfolio_5y.json."""
    out = {}
    if P.port is None:
        return out
    nh = str(P.port["dsr"]["N_headline"])
    for m in GATE_MODELS:
        g = {}
        b = P.port["books"].get(f"{m}|top_decile")
        if b:
            g["3"] = {"k": b["months_positive"], "n": b["n_months"], "share": b["share_months_positive"],
                      "pass": b["share_months_positive"] >= 0.75}
        e = P.port["dsr"]["books"].get(f"{m}|{PAPER_BASKET}")
        if e:
            g["5"] = {"dsr": e["skill"][nh]["dsr"], "psr": e["skill"][nh]["psr_vs_0"], "N": int(nh),
                      "pass": e["skill"][nh]["dsr"] >= 0.95}
        if g:
            out[m] = g
    return out


# ===================================================================== charts
def svg_coverage() -> str:
    """Data timeline: sessions per year in the store, the 5-year dataset and the pilot dataset."""
    W, H = 920, 236
    X0, X1 = 150, 902
    t0 = (2021, 10)

    def mi(d: str) -> float:   # fractional month index from 2021-10
        y, m, dd = int(d[:4]), int(d[5:7]), int(d[8:10]) if len(d) >= 10 else 1
        return (y - t0[0]) * 12 + (m - t0[1]) + (dd - 1) / 31

    span = mi("2026-11-01")

    def X(d: str) -> float:
        return lin(mi(d), 0, span, X0, X1)

    lbl = "Data timeline: NSE sessions per calendar year in the store, the 5-year modelling dataset and the pilot"
    p = [svg_open(W, H, lbl)]
    # year grid
    for y in range(2022, 2027):
        x = X(f"{y}-01-01")
        p.append(f'<line x1="{x:.1f}" y1="14" x2="{x:.1f}" y2="{H - 26}" class="grid"/>')
    for y in range(2021, 2027):
        a = X(f"{max(y, 2021)}-{'10' if y == 2021 else '01'}-01")
        b = X(f"{y + 1}-01-01") if y < 2026 else X("2026-10-16")
        p.append(f'<text x="{(a + b) / 2:.1f}" y="{H - 8}" class="ax" text-anchor="middle">{y}</text>')
    # row 1: sessions per year
    yr = 24
    p.append(f'<text x="{X0 - 12}" y="{yr + 17}" class="lbl" text-anchor="end">NSE sessions</text>')
    p.append(f'<text x="{X0 - 12}" y="{yr + 31}" class="ax ax-s" text-anchor="end">in the store</text>')
    sby = MD_ONLY["sessions_by_year"]
    for y in sorted(sby):
        a = X(MD_ONLY["store_first"]) if y == "2021" else X(f"{y}-01-01")
        b = X(MD_ONLY["store_last"]) if y == "2026" else X(f"{int(y) + 1}-01-01")
        tip = f"{y}: {sby[y]} sessions" + (" (Q4 only)" if y == "2021" else "") + (
            f" (to {MD_ONLY['store_last']})" if y == "2026" else "")
        p.append(f'<rect x="{a + 1:.1f}" y="{yr}" width="{b - a - 2:.1f}" height="34" rx="4" '
                 f'class="cell-y" data-tip="{E(tip)}"/>')
        p.append(f'<text x="{(a + b) / 2:.1f}" y="{yr + 22}" class="val" text-anchor="middle">{sby[y]}</text>')
    # row 2: 5-year dataset
    m5, s5 = D.man5, D.splits5
    y2 = 84
    p.append(f'<text x="{X0 - 12}" y="{y2 + 13}" class="lbl" text-anchor="end">5-year dataset</text>')
    p.append(f'<text x="{X0 - 12}" y="{y2 + 27}" class="ax ax-s" text-anchor="end">{n(m5["rows"])} rows</text>')
    segs5 = [(m5["date_min"], s5["folds"][0]["test_start"], "seg-warm", "training only (2022-10 to 2022-12)"),
             (s5["folds"][0]["test_start"], s5["folds"][-1]["test_end"], "seg-cv",
              f"{len(s5['folds'])} monthly folds {s5['folds'][0]['name']} to {s5['folds'][-1]['name']}"),
             (s5["holdout"]["test_start"], s5["holdout"]["test_end"], "seg-ho",
              f"holdout {s5['holdout']['test_start']} to {s5['holdout']['test_end']}"),
             (s5["holdout"]["test_end"], m5["date_max"], "seg-tail", "unlabelled tail (20-session label window)")]
    for a, b, cls, tip in segs5:
        xa, xb = X(a), X(b)
        p.append(f'<rect x="{xa:.1f}" y="{y2}" width="{max(xb - xa - 1.5, 2):.1f}" height="22" rx="3" '
                 f'class="{cls}" data-tip="{E(tip)}"/>')
    p.append(f'<text x="{X(s5["folds"][0]["test_start"]) + 8:.1f}" y="{y2 + 15}" class="inbar">'
             f'{len(s5["folds"])} monthly CV folds</text>')
    # row 3: pilot dataset
    mp, sp = D.man_pilot, D.splits_pilot
    y3 = 134
    p.append(f'<text x="{X0 - 12}" y="{y3 + 13}" class="lbl" text-anchor="end">Pilot dataset</text>')
    p.append(f'<text x="{X0 - 12}" y="{y3 + 27}" class="ax ax-s" text-anchor="end">{n(mp["rows"])} rows</text>')
    segsp = [(mp["date_min"], sp["folds"][0]["test_start"], "seg-warm", "training only"),
             (sp["folds"][0]["test_start"], sp["folds"][-1]["test_end"], "seg-cv",
              f"{len(sp['folds'])} CV folds {sp['folds'][0]['name']} to {sp['folds'][-1]['name']}"),
             (sp["holdout"]["test_start"], sp["holdout"]["test_end"], "seg-ho",
              f"holdout {sp['holdout']['test_start']} to {sp['holdout']['test_end']}"),
             (sp["holdout"]["test_end"], mp["date_max"], "seg-tail", "unlabelled tail")]
    for a, b, cls, tip in segsp:
        xa, xb = X(a), X(b)
        p.append(f'<rect x="{xa:.1f}" y="{y3}" width="{max(xb - xa - 1.5, 2):.1f}" height="22" rx="3" '
                 f'class="{cls}" data-tip="{E(tip)}"/>')
    for d in D.hd["phantom_days"]:
        x = X(d)
        p.append(f'<line x1="{x:.1f}" y1="{y3 + 26}" x2="{x:.1f}" y2="{y3 + 34}" class="tick-echo" '
                 f'data-tip="{E(d + ": holiday echo, removed")}"/>')
    p.append(f'<text x="{X(D.hd["phantom_days"][0]) - 6:.1f}" y="{y3 + 34}" class="ax ax-s" text-anchor="end">'
             f'{len(D.hd["phantom_days"])} echo days removed</text>')
    # March-2026 marker
    xm = X("2026-03-01")
    p.append(f'<line x1="{xm:.1f}" y1="{y2 - 8}" x2="{xm:.1f}" y2="{y3 + 26}" class="mark"/>')
    p.append(f'<text x="{xm - 5:.1f}" y="{y2 - 11}" class="ax ax-s" text-anchor="end">Mar 2026 inversion</text>')
    # key
    ky = H - 40
    p.append(f'<rect x="{X0}" y="{ky - 9}" width="12" height="10" rx="2" class="seg-warm"/>'
             f'<text x="{X0 + 17}" y="{ky}" class="ax ax-s">training only</text>'
             f'<rect x="{X0 + 102}" y="{ky - 9}" width="12" height="10" rx="2" class="seg-cv"/>'
             f'<text x="{X0 + 119}" y="{ky}" class="ax ax-s">monthly CV folds</text>'
             f'<rect x="{X0 + 222}" y="{ky - 9}" width="12" height="10" rx="2" class="seg-ho"/>'
             f'<text x="{X0 + 239}" y="{ky}" class="ax ax-s">holdout (used once)</text>'
             f'<rect x="{X0 + 350}" y="{ky - 9}" width="12" height="10" rx="2" class="seg-tail"/>'
             f'<text x="{X0 + 367}" y="{ky}" class="ax ax-s">unlabelled tail</text>')
    p.append("</svg>")
    return "".join(p)


H_ORDER = [1, 2, 3, 5, 10, 20, 40]


def svg_horizon_panel(kind: str) -> str:
    W, H = 330, 236
    X0, X1, Y0, Y1 = 46, 316, 22, 186

    def X(i: int) -> float:
        return lin(i, 0, len(H_ORDER) - 1, X0 + 8, X1 - 8)

    L = D.lsum["labels"]
    runs = D.lmod["runs"]
    econ = D.lmod["econ"]
    if kind == "q":
        title = "Features passing BH q < 0.05 (Newey-West adjusted), of 40"
        d0, d1, ticks = 0, 24, [0, 5, 10, 15, 20]
        ser = [("next-open", "s1", {h: L[f"ex_no_{h}d"]["n_q_nw_lt_0.05"] for h in H_ORDER}),
               ("close-to-close", "s2", {h: L[f"ex_cc_{h}d"]["n_q_nw_lt_0.05"] for h in H_ORDER})]
        fmt = lambda v: f"{v:d}"   # noqa: E731
    elif kind == "auc":
        title = "Model CV AUC: excess label vs raw > 0 label"
        d0, d1, ticks = 0.50, 0.57, [0.50, 0.52, 0.54, 0.56]
        ex = {r["h"]: r["cv_auc_mean"] for k, r in runs.items() if "_ex_" in k}
        raw = {r["h"]: r["cv_auc_mean"] for k, r in runs.items() if "_raw_" in k}
        ser = [("excess, next-open", "s1", ex), ("raw > 0, close-to-close", "s2", raw)]
        fmt = lambda v: f"{v:.3f}"  # noqa: E731
    else:
        title = "Break-even cost, bps per side (100% turnover)"
        d0, d1, ticks = 0, 30, [0, 10, 20, 30]
        ex = {runs[k]["h"]: e["oos_all"]["label_return"]["breakeven_cost_per_side_bps_full_turnover"]
              for k, e in econ.items() if "_ex_" in k}
        raw = {runs[k]["h"]: e["oos_all"]["label_return"]["breakeven_cost_per_side_bps_full_turnover"]
               for k, e in econ.items() if "_raw_" in k}
        ser = [("excess, next-open", "s1", ex), ("raw > 0, close-to-close", "s2", raw)]
        fmt = lambda v: f"{v:.1f}"  # noqa: E731

    def Y(v: float) -> float:
        return lin(v, d0, d1, Y1, Y0)

    p = [svg_open(W, H, title)]
    for t in ticks:
        cls = "chance" if (kind == "auc" and t == 0.50) else ("axisln" if t == 0 else "grid")
        p.append(f'<line x1="{X0}" y1="{Y(t):.1f}" x2="{X1}" y2="{Y(t):.1f}" class="{cls}"/>')
        tl = f"{t:.2f}" if kind == "auc" else f"{t:d}"
        p.append(f'<text x="{X0 - 6}" y="{Y(t) + 4:.1f}" class="ax ax-s" text-anchor="end">{tl}</text>')
    if kind == "be":
        p.append(f'<line x1="{X0}" y1="{Y(20):.1f}" x2="{X1}" y2="{Y(20):.1f}" class="passln"/>')
        p.append(f'<text x="{X1}" y="{Y(20) - 5:.1f}" class="ax ax-s" text-anchor="end">20 bps per side assumed</text>')
    for i, h in enumerate(H_ORDER):
        p.append(f'<text x="{X(i):.1f}" y="{Y1 + 16}" class="ax ax-s" text-anchor="middle">{h}</text>')
    p.append(f'<text x="{(X0 + X1) / 2:.0f}" y="{H - 14}" class="ax" text-anchor="middle">horizon, sessions</text>')
    for name, slot, vals in ser:
        pts = [(X(i), Y(vals[h]), h, vals[h]) for i, h in enumerate(H_ORDER) if h in vals]
        if len(pts) > 1:
            pl = " ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in pts)
            p.append(f'<polyline points="{pl}" fill="none" stroke="var(--{slot})" stroke-width="2" '
                     f'stroke-linejoin="round" stroke-linecap="round"/>')
        for x, y, h, v in pts:
            tip = f"{name}, {h} sessions: {fmt(v)}"
            p.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="var(--{slot})" stroke="var(--surface)" '
                     f'stroke-width="2" data-tip="{E(tip)}"/>')
    if kind != "q":
        miss = [h for h in H_ORDER if h not in ser[0][2]]
        for h in miss:
            i = H_ORDER.index(h)
            p.append(f'<text x="{X(i):.1f}" y="{Y1 - 8}" class="ax ax-s" text-anchor="middle">not run</text>')
    p.append("</svg>")
    return "".join(p)


def heat_bucket(v: float | None) -> str:
    if v is None:
        return "na"
    a = abs(v)
    step = 0 if a < 0.02 else 1 if a < 0.06 else 2 if a < 0.10 else 3
    return "hm-0" if step == 0 else f"hm-{'p' if v > 0 else 'n'}{step}"


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
TWINS = {"deliv_pct_z_20": "cs_rank_deliv_z", "ret_126d": "cs_rank_ret_126", "vol_20": "cs_rank_vol_20",
         "log_turnover": "cs_rank_turnover", "mom_20": "cs_rank_mom_20", "ret_1d": "log_ret_1d"}


def heatmap_html() -> str:
    IC = D.IC
    months = D.eda_months
    covered = {f_ for _, fs in FAMILIES for g in fs for f_ in [g] + ([TWINS[g]] if g in TWINS else [])}
    assert covered == set(IC), sorted(set(IC) ^ covered)
    worst = {mo: sum(1 for v in IC.values() if (v.get("worst_month") or {}).get("month") == mo) for mo in months}
    mx = max(worst.values())
    years: dict[str, int] = {}
    for mo in months:
        years[mo[:4]] = years.get(mo[:4], 0) + 1
    h1 = ('<tr><th rowspan="2" class="fcol">Feature</th>'
          + "".join(f'<th colspan="{k}" class="yr">{y}</th>' for y, k in years.items())
          + '<th rowspan="2" class="sumh">Mean</th><th rowspan="2" class="sumh">Worst month</th></tr>')
    h2 = "<tr>" + "".join(f'<th class="mo{" brk" if mo == D.crash else ""}">{MONTHS[int(mo[5:]) - 1][:3]}</th>'
                          for mo in months) + "</tr>"
    cnt = ('<tr class="cnt"><th scope="row">Features at their worst month</th>'
           + "".join(f'<td class="{"cmax" if worst[mo] == mx else ""}{" brk" if mo == D.crash else ""}" '
                     f'data-tip="{E(f"{mname(mo)}: worst IC month for {worst[mo]} of {len(IC)} features")}">'
                     f'{worst[mo] if worst[mo] else "·"}</td>' for mo in months)
           + f'<td class="sum"></td><td class="sum">{mx} of {len(IC)}</td></tr>')
    body = [cnt]
    ncol = 1 + len(months) + 2
    for fam, feats in FAMILIES:
        body.append(f'<tr class="fam"><th colspan="{ncol}" scope="colgroup">{E(fam)}</th></tr>')
        for f_ in feats:
            v = IC[f_]
            name = f_ + (f" · {TWINS[f_]}" if f_ in TWINS else "")
            cells = []
            for mo in months:
                x = v["monthly_ic"].get(mo)
                cls = heat_bucket(x) + (" brk" if mo == D.crash else "")
                if x is None:
                    cells.append(f'<td class="{cls}">·</td>')
                else:
                    cells.append(f'<td class="{cls}" data-tip="{E(f"{name} · {mo}: IC {sg(x)}")}">'
                                 f'{neg(str(round(x * 100)))}</td>')
            wm = (v.get("worst_month") or {}).get("month", "")
            body.append(f'<tr><th scope="row">{E(name)}</th>{"".join(cells)}'
                        f'<td class="sum">{sg(v["mean_ic"] * 100, 1)}</td>'
                        f'<td class="sum{" strong" if wm == D.crash else ""}">{E(mshort(wm)) if wm else ""}</td></tr>')
    return f'<table class="heat"><thead>{h1}{h2}</thead><tbody>{"".join(body)}</tbody></table>'


def svg_resid_ic() -> str:
    fs = D.suff
    surv = set(fs["verdict"]["features_new_information_bh"])
    q_bar = fs["rules"]["bh_q"]
    rows = []
    for f_ in fs["new_features"]:
        r = fs["ic_summary"][f_]["resid_full"]
        rows.append((f_, r["mean_ic"], r["t"], r["q_bh"]))
    rows.sort(key=lambda r: (-r[2], r[0]))
    W, L, R = 760, 200, 560
    top, rh = 22, 22
    H = top + rh * len(rows) + 34
    lo, hi = -0.045, 0.035

    def X(v: float) -> float:
        return lin(v, lo, hi, L, R)

    p = [svg_open(W, H, "Residual IC of the 23 new features against the champion's 10 ranks; BH survivors highlighted")]
    for t in (-0.04, -0.02, 0.02):
        p.append(f'<line x1="{X(t):.1f}" y1="{top - 6}" x2="{X(t):.1f}" y2="{H - 30}" class="grid"/>')
        p.append(f'<text x="{X(t):.1f}" y="{H - 12}" class="ax" text-anchor="middle">{sg(t, 2)}</text>')
    p.append(f'<line x1="{X(0):.1f}" y1="{top - 6}" x2="{X(0):.1f}" y2="{H - 30}" class="axisln"/>')
    p.append(f'<text x="{X(0):.1f}" y="{H - 12}" class="ax" text-anchor="middle">0</text>')
    for i, (f_, ic, t, q) in enumerate(rows):
        y = top + rh * i + rh / 2
        hot = f_ in surv
        tip = f"{f_}: residual IC {sg(ic, 4)}, t {sg(t, 2)}, BH q {q:.3f}" + (" (passes q ≤ 0.1)" if hot else "")
        p.append(f'<g data-tip="{E(tip)}"><rect x="0" y="{y - rh / 2:.1f}" width="{W}" height="{rh}" fill="transparent"/>')
        p.append(f'<text x="{L - 10}" y="{y + 4:.1f}" class="{"lbl-em" if hot else "lbl"}" text-anchor="end">{E(f_)}</text>')
        p.append(f'<path d="{hbar(X(0), X(ic), y, 13, 3)}" fill="{"var(--s1)" if hot else "var(--axisc)"}"/></g>')
        p.append(f'<text x="{R + 12}" y="{y + 4:.1f}" class="{"val-em" if hot else "val"}">t {sg(t, 2)} · q {q:.3f}</text>')
    p.append(f'<text x="{R + 12}" y="{top - 9}" class="ax ax-s">BH q ≤ {q_bar:g} passes</text>')
    p.append("</svg>")
    return "".join(p)


def svg_league_panel(rows: list[dict], title: str, d0: float = 0.44, d1: float = 0.58,
                     control: float | None = None) -> str:
    W, L, R = 860, 250, 790
    top, rh = 46, 30
    H = top + rh * len(rows) + 30

    def X(v: float) -> float:
        return lin(v, d0, d1, L, R)

    p = [svg_open(W, H, title)]
    t = d0
    while t <= d1 + 1e-9:
        x = X(t)
        p.append(f'<line x1="{x:.1f}" y1="{top - 8}" x2="{x:.1f}" y2="{H - 26}" class="grid"/>')
        p.append(f'<text x="{x:.1f}" y="{H - 8}" class="ax" text-anchor="middle">{t:.2f}</text>')
        t = round(t + 0.02, 2)
    p.append(f'<line x1="{X(0.5):.1f}" y1="{top - 8}" x2="{X(0.5):.1f}" y2="{H - 26}" class="chance"/>')
    p.append(f'<line x1="{X(D.BAR):.1f}" y1="{top - 22}" x2="{X(D.BAR):.1f}" y2="{H - 26}" class="passln"/>')
    p.append(f'<text x="{X(D.BAR) + 6:.1f}" y="{top - 26}" class="lbl-em">bar {f(D.BAR)}</text>')
    if control is not None:
        p.append(f'<line x1="{X(control):.1f}" y1="{top - 22}" x2="{X(control):.1f}" y2="{H - 26}" class="ctrlln"/>')
        p.append(f'<text x="{X(control) - 6:.1f}" y="{top - 26}" class="lbl" text-anchor="end">control {f(control)}</text>')
    for i, r in enumerate(rows):
        y = top + rh * i + rh / 2
        tip = (f"{r['name']}: CV AUC {f(r['cv'])} ± {r['sd']:.3f}; worst fold {r['worst']:.3f}; "
               f"holdout {r['ho']:.3f}")
        p.append(f'<g data-tip="{E(tip)}"><rect x="0" y="{y - rh / 2:.1f}" width="{W}" height="{rh}" fill="transparent"/>')
        p.append(f'<text x="{L - 12}" y="{y + 4:.1f}" class="{"lbl-em" if r.get("em") else "lbl"}" '
                 f'text-anchor="end">{E(r["name"])}</text>')
        p.append(f'<line x1="{X(r["cv"] - r["sd"]):.1f}" y1="{y:.1f}" x2="{X(r["cv"] + r["sd"]):.1f}" y2="{y:.1f}" '
                 f'stroke="var(--s1)" stroke-width="2" stroke-linecap="round"/>')
        xw = X(r["worst"])
        p.append(f'<path d="M{xw:.1f},{y - 5:.1f} L{xw + 5:.1f},{y + 4:.1f} L{xw - 5:.1f},{y + 4:.1f} Z" '
                 f'fill="var(--surface)" stroke="var(--neg)" stroke-width="1.8"/>')
        xh = X(r["ho"])
        p.append(f'<path d="M{xh:.1f},{y - 6:.1f} L{xh + 6:.1f},{y:.1f} L{xh:.1f},{y + 6:.1f} L{xh - 6:.1f},{y:.1f} Z" '
                 f'fill="var(--s2)" stroke="var(--surface)" stroke-width="1.5"/>')
        p.append(f'<circle cx="{X(r["cv"]):.1f}" cy="{y:.1f}" r="5.5" fill="var(--s1)" stroke="var(--surface)" '
                 f'stroke-width="2"/></g>')
    p.append("</svg>")
    return "".join(p)


LEAGUE_KEY = ('<ul class="legend"><li><span class="dot" style="background:var(--s1)"></span>CV AUC (mean) '
              '± 1 sd across folds</li><li><span class="tri"></span>worst fold</li>'
              '<li><span class="dia"></span>holdout</li><li><span class="ln-k chance-k"></span>chance 0.50</li>'
              '<li><span class="ln-k pass-k"></span>pre-registered bar</li></ul>')


def svg_strip() -> str:
    S = D.S5
    models = [m for m in STRIP if m in S]
    folds = D.folds
    W, H = 940, 386
    X0, X1, XH = 58, 846, 900
    Y0, Y1 = 58, 316
    d0, d1 = 0.34, 0.69
    step = (X1 - X0) / (len(folds) - 1)

    def X(i: int) -> float:
        return X0 + i * step

    def Y(v: float) -> float:
        return lin(v, d0, d1, Y1, Y0)

    lbl = "Monthly fold AUC over the 43 folds, January 2023 to July 2026, plus the holdout, per model"
    p = [svg_open(W, H, lbl, ' id="strip"')]
    k = len(D.short_folds)
    xa, xb = X(0) - step / 2, X(k - 1) + step / 2
    p.append(f'<rect x="{xa:.1f}" y="{Y0}" width="{xb - xa:.1f}" height="{Y1 - Y0}" class="shade"/>')
    p.append(f'<text x="{xa + 6:.1f}" y="{Y0 + 15}" class="ax ax-s">short training window: '
             f'fewer than {FULL_WINDOW_ROWS // 1000}k training rows</text>')
    p.append(f'<text x="{xa + 6:.1f}" y="{Y0 + 28}" class="ax ax-s">{folds[0]} to {D.short_folds[-1]} '
             f'({n(S["all51"]["ntrain"][folds[0]])} to {n(S["all51"]["ntrain"][D.short_folds[-1]])} rows)</text>')
    for t in (0.40, 0.45, 0.55, 0.60, 0.65):
        p.append(f'<line x1="{X0 - 6}" y1="{Y(t):.1f}" x2="{XH + 14}" y2="{Y(t):.1f}" class="grid"/>')
        p.append(f'<text x="{X0 - 10}" y="{Y(t) + 4:.1f}" class="ax" text-anchor="end">{t:.2f}</text>')
    p.append(f'<line x1="{X0 - 6}" y1="{Y(0.5):.1f}" x2="{XH + 14}" y2="{Y(0.5):.1f}" class="chance"/>')
    p.append(f'<text x="{X0 - 10}" y="{Y(0.5) + 4:.1f}" class="ax" text-anchor="end">0.50</text>')
    ml_models = [m for m in models if m != "baseline_mom"]
    ir = [folds.index(fo) for fo in D.run]
    rv = [S[m]["auc"][fo] for m in ml_models for fo in D.run]
    xr0, xr1 = X(ir[0]) - step / 2, X(ir[-1]) + step / 2
    yb = Y0 - 14
    p.append(f'<path d="M{xr0:.1f},{yb + 6:.1f} V{yb:.1f} H{xr1:.1f} V{yb + 6:.1f}" class="bracket"/>')
    p.append(f'<text x="{(xr0 + xr1) / 2:.1f}" y="{yb - 6:.1f}" class="anno-t" text-anchor="middle">'
             f'{mshort(D.run[0])} to {mshort(D.run[-1])}: {min(rv):.2f} to {max(rv):.2f}</text>')
    ic = folds.index(D.crash)
    cv = [S[m]["auc"][D.crash] for m in models]
    p.append(f'<line x1="{X(ic):.1f}" y1="{Y0}" x2="{X(ic):.1f}" y2="{Y1}" class="mark"/>')
    p.append(f'<text x="{X(ic) - 7:.1f}" y="{Y(0.352):.1f}" class="anno-t" text-anchor="end">'
             f'{mshort(D.crash)}: {min(cv):.2f} to {max(cv):.2f}</text>')
    for i, fo in enumerate(folds):
        if fo.endswith("-01") or fo == folds[0]:
            p.append(f'<text x="{X(i):.1f}" y="{Y1 + 34}" class="ax" text-anchor="middle">{fo[:4]}</text>')
        if int(fo[5:]) % 3 == 1:
            p.append(f'<line x1="{X(i):.1f}" y1="{Y1}" x2="{X(i):.1f}" y2="{Y1 + 5}" class="axisln"/>')
            p.append(f'<text x="{X(i):.1f}" y="{Y1 + 17}" class="ax ax-s" text-anchor="middle">'
                     f'{MONTHS[int(fo[5:]) - 1][:3]}</text>')
    p.append(f'<text x="{XH:.1f}" y="{Y1 + 17}" class="ax ax-s" text-anchor="middle">holdout</text>')
    p.append(f'<line x1="{XH - 24:.1f}" y1="{Y0}" x2="{XH - 24:.1f}" y2="{Y1}" class="grid"/>')
    if P.regimes is not None:
        pm = P.regimes["per_month"]
        for i, fo in enumerate(folds):
            if pm.get(fo, {}).get("direction") == "down":
                p.append(f'<rect x="{X(i) - step / 2 + 1:.1f}" y="{Y1 + 40}" width="{step - 2:.1f}" height="6" '
                         f'rx="1.5" class="down-cell" data-tip="{E(f"{fo}: down month (EW 20-day return {pc(pm[fo]["ew_fwd_20d"])})")}"/>')
        p.append(f'<text x="{X0 - 10}" y="{Y1 + 46}" class="ax ax-s" text-anchor="end">down</text>')
    for m in models:
        pts = " ".join(f"{X(i):.1f},{Y(S[m]['auc'][fo]):.1f}" for i, fo in enumerate(folds))
        wd = 2.6 if m == "all51" else 2
        p.append(f'<polyline class="ln" data-m="{m}" points="{pts}" fill="none" stroke="var(--s{SLOT[m]})" '
                 f'stroke-width="{wd}" stroke-linejoin="round" stroke-linecap="round"/>')
    for m in models:
        ho = S[m]["ho"]
        p.append(f'<circle class="ln" data-m="{m}" cx="{XH:.1f}" cy="{Y(ho):.1f}" r="4.5" fill="var(--s{SLOT[m]})" '
                 f'stroke="var(--surface)" stroke-width="2" data-tip="{E(f"{NAME5[m]}: holdout AUC {ho:.4f}")}"/>')
    for i, fo in enumerate(folds):
        vals = " · ".join(f"{m} {S[m]['auc'][fo]:.3f}" for m in models)
        nt = S["all51"]["ntrain"][fo]
        p.append(f'<rect x="{X(i) - step / 2:.1f}" y="{Y0}" width="{step:.1f}" height="{Y1 - Y0}" fill="transparent" '
                 f'data-tip="{E(f"{fo} ({n(nt)} training rows): {vals}")}"/>')
    p.append("</svg>")
    return "".join(p)


def strip_legend() -> str:
    items = []
    for m in [x for x in STRIP if x in D.S5]:
        s = D.S5[m]
        items.append(f'<li class="iso" data-m="{m}" tabindex="0"><span class="chip" style="background:var(--s{SLOT[m]})">'
                     f'</span><span>{E(NAME5[m])} <code>{m}</code></span><b>{f(s["cv"])}</b></li>')
    return f'<ul class="legend iso-legend" data-for="strip">{"".join(items)}</ul>'


def svg_decile() -> str:
    S = D.S5
    models = [m for m in ["all51", "nested_lgbm", ENS, "champion10", "lr_l2", "nested_lr_l2", "baseline_mom"] if m in S]
    W, L, R = 880, 236, 640
    top, gh = 34, 46
    H = top + gh * len(models) + 34
    lo, hi = -0.04, 0.04

    def X(v: float) -> float:
        return lin(v, lo, hi, L, R)

    p = [svg_open(W, H, "Mean fold decile spread and holdout decile spread per model, with CV AUC")]
    for t in (-0.04, -0.02, 0.02, 0.04):
        p.append(f'<line x1="{X(t):.1f}" y1="{top - 8}" x2="{X(t):.1f}" y2="{H - 30}" class="grid"/>')
        p.append(f'<text x="{X(t):.1f}" y="{H - 12}" class="ax" text-anchor="middle">{pc(t, 0)}</text>')
    p.append(f'<line x1="{X(0):.1f}" y1="{top - 8}" x2="{X(0):.1f}" y2="{H - 30}" class="axisln"/>')
    p.append(f'<text x="{X(0):.1f}" y="{H - 12}" class="ax" text-anchor="middle">0</text>')
    p.append(f'<text x="{R + 18}" y="{top - 14}" class="ax ax-s">CV AUC · folds with spread &gt; 0</text>')
    for i, m in enumerate(models):
        s = S[m]
        y = top + gh * i + gh / 2
        p.append(f'<text x="{L - 12}" y="{y + 4:.1f}" class="lbl" text-anchor="end">{E(NAME5[m])}</text>')
        t1 = f"{NAME5[m]}: mean fold decile spread {pc(s['mds'], 2)} per 20 days ({s['mds_pos']} of {s['n_ds']} folds > 0)"
        t2 = f"{NAME5[m]}: holdout decile spread {pc(s['ho_ds'], 2)}"
        p.append(f'<path d="{hbar(X(0), X(s["mds"]), y - 7, 11, 3)}" fill="var(--s1)" data-tip="{E(t1)}"/>')
        p.append(f'<path d="{hbar(X(0), X(s["ho_ds"]), y + 7, 11, 3)}" fill="var(--s2)" data-tip="{E(t2)}"/>')
        p.append(f'<text x="{R + 18}" y="{y + 4:.1f}" class="val">{f(s["cv"])} · {s["mds_pos"]}/{s["n_ds"]}</text>')
    p.append("</svg>")
    return "".join(p)


def svg_boot_models() -> str:
    bm = P.boot["models"]
    order = [m for m in ["nested_lgbm", "all51", ENS, "champion10", "lr_l2", "nested_lr_l2", "baseline_mom", HEUR] if m in bm]
    W, L, R = 860, 250, 700
    top, rh = 34, 34
    H = top + rh * len(order) + 30
    d0, d1 = 0.47, 0.58

    def X(v: float) -> float:
        return lin(v, d0, d1, L, R)

    p = [svg_open(W, H, "Five-year CV mean AUC and holdout AUC with 20-session block-bootstrap 95% intervals")]
    for t in (0.48, 0.50, 0.52, 0.54, 0.56, 0.58):
        cls = "chance" if t == 0.50 else "grid"
        p.append(f'<line x1="{X(t):.1f}" y1="{top - 8}" x2="{X(t):.1f}" y2="{H - 26}" class="{cls}"/>')
        p.append(f'<text x="{X(t):.1f}" y="{H - 8}" class="ax" text-anchor="middle">{t:.2f}</text>')
    p.append(f'<text x="{R + 16}" y="{top - 14}" class="ax ax-s">P(CV mean &gt; 0.50)</text>')
    for i, m in enumerate(order):
        b = bm[m]
        y = top + rh * i + rh / 2
        lo, hi = b["cv_mean_ci95"]
        hl, hh = b["holdout_ci95"]
        p.append(f'<text x="{L - 12}" y="{y + 4:.1f}" class="lbl" text-anchor="end">{E(NAME5.get(m, m))}</text>')
        t1 = f"{m}: CV mean {f(b['cv_auc_mean'])}, 95% CI [{f(lo)}, {f(hi)}]"
        t2 = f"{m}: holdout {f(b['holdout_auc'])}, 95% CI [{f(hl)}, {f(hh)}] (indicative: about 2 blocks)"
        p.append(f'<g data-tip="{E(t1)}"><line x1="{X(lo):.1f}" y1="{y - 6:.1f}" x2="{X(hi):.1f}" y2="{y - 6:.1f}" '
                 f'stroke="var(--s1)" stroke-width="2"/><circle cx="{X(b["cv_auc_mean"]):.1f}" cy="{y - 6:.1f}" r="5" '
                 f'fill="var(--s1)" stroke="var(--surface)" stroke-width="2"/></g>')
        p.append(f'<g data-tip="{E(t2)}"><line x1="{X(hl):.1f}" y1="{y + 7:.1f}" x2="{X(hh):.1f}" y2="{y + 7:.1f}" '
                 f'stroke="var(--s2)" stroke-width="2"/><circle cx="{X(b["holdout_auc"]):.1f}" cy="{y + 7:.1f}" r="4.5" '
                 f'fill="var(--surface)" stroke="var(--s2)" stroke-width="2.4"/></g>')
        p.append(f'<text x="{R + 16}" y="{y + 4:.1f}" class="val">{b["p_cv_mean_gt_050"]:.3f}</text>')
    p.append("</svg>")
    return "".join(p)


def svg_boot_pairs() -> str:
    pr = P.boot["pairs"]
    keys = list(pr)
    W, L, R = 860, 290, 700
    top, rh = 34, 34
    H = top + rh * len(keys) + 40
    allv = [v for k in keys for c in ("cv_mean", "holdout") for v in pr[k][c]["ci95"]]
    lim = max(0.03, math.ceil(max(abs(x) for x in allv) * 100) / 100)

    def X(v: float) -> float:
        return lin(v, -lim, lim, L, R)

    p = [svg_open(W, H, "Paired five-year AUC differences A minus B with 95% block-bootstrap intervals")]
    t = -lim
    while t <= lim + 1e-9:
        cls = "axisln" if abs(t) < 1e-9 else "grid"
        p.append(f'<line x1="{X(t):.1f}" y1="{top - 8}" x2="{X(t):.1f}" y2="{H - 34}" class="{cls}"/>')
        p.append(f'<text x="{X(t):.1f}" y="{H - 18}" class="ax" text-anchor="middle">{sg(t, 2) if abs(t) > 1e-9 else "0"}</text>')
        t = round(t + 0.02, 2)
    p.append(f'<text x="{X(0) + 6:.1f}" y="{H - 4}" class="ax ax-s">A better →</text>')
    p.append(f'<text x="{X(0) - 6:.1f}" y="{H - 4}" class="ax ax-s" text-anchor="end">← B better</text>')
    p.append(f'<text x="{R + 16}" y="{top - 14}" class="ax ax-s">folds won by A</text>')
    for i, k in enumerate(keys):
        r = pr[k]
        y = top + rh * i + rh / 2
        c, h = r["cv_mean"], r["holdout"]
        p.append(f'<text x="{L - 12}" y="{y + 4:.1f}" class="lbl" text-anchor="end">{E(k.replace(" - ", " − "))}</text>')
        t1 = f"{k}: CV-mean Δ {sg(c['delta'], 4)}, 95% CI [{sg(c['ci95'][0], 4)}, {sg(c['ci95'][1], 4)}]"
        t2 = f"{k}: holdout Δ {sg(h['delta'], 4)}, 95% CI [{sg(h['ci95'][0], 4)}, {sg(h['ci95'][1], 4)}]"
        p.append(f'<g data-tip="{E(t1)}"><line x1="{X(c["ci95"][0]):.1f}" y1="{y - 6:.1f}" x2="{X(c["ci95"][1]):.1f}" '
                 f'y2="{y - 6:.1f}" stroke="var(--s1)" stroke-width="2"/><circle cx="{X(c["delta"]):.1f}" cy="{y - 6:.1f}" '
                 f'r="5" fill="var(--s1)" stroke="var(--surface)" stroke-width="2"/></g>')
        p.append(f'<g data-tip="{E(t2)}"><line x1="{X(h["ci95"][0]):.1f}" y1="{y + 7:.1f}" x2="{X(h["ci95"][1]):.1f}" '
                 f'y2="{y + 7:.1f}" stroke="var(--s2)" stroke-width="2"/><circle cx="{X(h["delta"]):.1f}" cy="{y + 7:.1f}" '
                 f'r="4.5" fill="var(--surface)" stroke="var(--s2)" stroke-width="2.4"/></g>')
        p.append(f'<text x="{R + 16}" y="{y + 4:.1f}" class="val">{E(r["folds_won"])}</text>')
    p.append("</svg>")
    return "".join(p)


def svg_monthly_book(key: str, ymax: float) -> str:
    b = P.port["books"][key]
    mo = sorted(b["monthly_20bps"])
    vals = [b["monthly_20bps"][m] for m in mo]
    W, H = 900, 176
    X0, X1, Y0, Y1 = 50, 888, 16, 138
    step = (X1 - X0) / len(mo)

    def Y(v: float) -> float:
        return lin(v, -ymax, ymax, Y1, Y0)

    sc, bk = key.split("|")
    title = f"{NAME5.get(sc, sc)} {bk.replace('_', ' ')}: net (20 bps) 20-day return minus the EW benchmark, by signal month"
    p = [svg_open(W, H, title)]
    t = -ymax
    while t <= ymax + 1e-9:
        cls = "axisln" if abs(t) < 1e-12 else "grid"
        p.append(f'<line x1="{X0}" y1="{Y(t):.1f}" x2="{X1}" y2="{Y(t):.1f}" class="{cls}"/>')
        p.append(f'<text x="{X0 - 6}" y="{Y(t) + 4:.1f}" class="ax ax-s" text-anchor="end">{pc(t, 0)}</text>')
        t = round(t + ymax / 2, 6)
    for i, (m, v) in enumerate(zip(mo, vals)):
        xc = X0 + step * (i + 0.5)
        path = vbar(xc, max(step - 3, 3), Y(0), Y(v), 2)
        tip = f"{m}: {pc(v, 2)} per 20 days vs EW" + (" (holdout)" if m >= "2026-08" else "")
        if path:
            p.append(f'<path d="{path}" fill="{"var(--pos)" if v >= 0 else "var(--neg)"}" data-tip="{E(tip)}"/>')
        if m.endswith("-01"):
            p.append(f'<text x="{xc:.1f}" y="{Y1 + 16}" class="ax ax-s" text-anchor="middle">{m[:4]}</text>')
    p.append(f'<text x="{X1}" y="{Y1 + 30}" class="ax ax-s" text-anchor="end">{b["months_positive"]} of {b["n_months"]} '
             f'months above 0</text>')
    p.append("</svg>")
    return "".join(p)


def svg_champion_mini(model: str, title: str, ymax: float) -> str:
    rows = [r for r in D.monthly if r["model"] == model]
    W, H = 300, 200
    X0, X1, Y0, Y1 = 40, 292, 18, 132

    def Y(v: float) -> float:
        return lin(v, -ymax, ymax, Y1, Y0)

    step = (X1 - X0) / len(rows)
    p = [svg_open(W, H, f"{title}: net active return vs the equal-weight universe per signal month, and hit rate")]
    t = -ymax
    while t <= ymax + 1e-9:
        cls = "axisln" if abs(t) < 1e-12 else "grid"
        p.append(f'<line x1="{X0}" y1="{Y(t):.1f}" x2="{X1}" y2="{Y(t):.1f}" class="{cls}"/>')
        p.append(f'<text x="{X0 - 5}" y="{Y(t) + 3.5:.1f}" class="ax ax-s" text-anchor="end">{pc(t, 0)}</text>')
        t = round(t + ymax / 2, 6)
    for i, r in enumerate(rows):
        v = float(r["net_active_vs_ew_20bps"])
        hit = float(r["hit_vs_ew_net20"])
        xc = X0 + step * (i + 0.5)
        tip = (f"{r['signal_month']} ({r['segment']}{', adversarial' if r['adversarial_month'] == 'True' else ''}): "
               f"net active vs EW {pc(v, 2)} per 20 days; beat EW in {pu(hit)} of {r['n_tranches']} tranches")
        path = vbar(xc, min(24, step - 8), Y(0), Y(v), 3)
        if path:
            p.append(f'<path d="{path}" fill="{"var(--pos)" if v >= 0 else "var(--neg)"}" data-tip="{E(tip)}"/>')
        p.append(f'<text x="{xc:.1f}" y="{Y1 + 15}" class="ax ax-s" text-anchor="middle">'
                 f'{MONTHS[int(r["signal_month"][5:]) - 1][:3]}</text>')
        p.append(f'<text x="{xc:.1f}" y="{Y1 + 30}" class="val ax-s" text-anchor="middle">{pu(hit)}</text>')
        if r["adversarial_month"] == "True":
            p.append(f'<text x="{xc:.1f}" y="{Y1 + 44}" class="ax ax-s" text-anchor="middle">adv.</text>')
    ho_i = [i for i, r in enumerate(rows) if r["segment"] == "holdout"]
    if ho_i:
        x = X0 + step * ho_i[0]
        p.append(f'<line x1="{x:.1f}" y1="{Y0 - 6}" x2="{x:.1f}" y2="{Y1 + 4}" class="mark"/>')
        p.append(f'<text x="{x + 4:.1f}" y="{Y0 - 6}" class="ax ax-s">holdout</text>')
    p.append(f'<text x="{X0 - 5}" y="{Y1 + 30}" class="ax ax-s" text-anchor="end">hit</text>')
    p.append("</svg>")
    return "".join(p)


def svg_flow() -> str:
    W, H = 920, 236
    p = [svg_open(W, H, "Daily and monthly jobs of the paper-trading product")]
    p.append('<defs><marker id="arw" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
             'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="arrowhead"/></marker></defs>')

    def box(x, y, w, h, t1, t2="", em=False):
        p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" class="{"fbox em" if em else "fbox"}"/>')
        p.append(f'<text x="{x + w / 2}" y="{y + (h / 2 - 3 if t2 else h / 2 + 4)}" class="ftxt" text-anchor="middle">{E(t1)}</text>')
        if t2:
            p.append(f'<text x="{x + w / 2}" y="{y + h / 2 + 13}" class="ax ax-s" text-anchor="middle">{E(t2)}</text>')

    def arrow(x1, y1, x2, y2):
        p.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" class="farrow" marker-end="url(#arw)"/>')

    p.append('<text x="10" y="22" class="colh">Daily, after the end-of-day ingest</text>')
    daily = [("Ingest", "bhavcopy, dup-day guard"), ("Feature build", "52 end-of-day features"),
             ("Score", "LightGBM + L2 monitor"), ("Rank lists", "top decile, liquid tercile"),
             ("Paper portfolio", "20 tranches, 20 bps/side"), ("Dashboard", "alerts below")]
    bw, gap, y = 132, 22, 36
    for i, (a, b) in enumerate(daily):
        x = 10 + i * (bw + gap)
        box(x, y, bw, 52, a, b, em=(a == "Paper portfolio"))
        if i:
            arrow(x - gap + 2, y + 26, x - 3, y + 26)
    p.append('<text x="10" y="138" class="colh">Monthly</text>')
    monthly = [("Retrain", "trailing 504 sessions"), ("Purge and embargo", "22 sessions, exit dates"),
               ("Champion vs challenger", "rank-average ensemble"), ("Log the trial count", "feeds DSR")]
    bw2, y2 = 190, 152
    for i, (a, b) in enumerate(monthly):
        x = 10 + i * (bw2 + 30)
        box(x, y2, bw2, 52, a, b)
        if i:
            arrow(x - 28, y2 + 26, x - 3, y2 + 26)
    p.append("</svg>")
    return "".join(p)


# ===================================================================== tables
def table(head: list[str], rows: list[list[str]], cls: str = "", wrap_cols: tuple[int, ...] = ()) -> str:
    th = "".join(f'<th{" class=\"wrapcell\"" if i in wrap_cols else ""}>{h}</th>' for i, h in enumerate(head))
    body = []
    for r in rows:
        tds = "".join(f'<td{" class=\"wrapcell\"" if i in wrap_cols else ""}>{c}</td>' for i, c in enumerate(r))
        body.append(f"<tr>{tds}</tr>")
    return f'<div class="scroll"><table class="{cls}"><thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
