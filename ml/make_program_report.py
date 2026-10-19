#!/usr/bin/env python3
"""Generate ml/report/program_report.html: the SuryaDhana research program's capstone report.

Narrative of record: ml/PROGRAM_REPORT.md (program lead). This page says what that file says, in its
order and with its hedges; ml/results/scale5y/SCALE5Y.md supplies the wording of the 5-year results.
Every number that exists in a JSON/CSV artifact is loaded at build time and formatted here, never
typed. The few figures that exist only in Markdown (the lead's full-history scan of the data store,
literature calibration points, a handful of memo figures) are typed once in MD_ONLY with their source.

Inputs (read-only; nothing is retrained and no prediction parquet is opened):
  ml/data/{manifest,splits}.json
  ml/results/scale5y/{manifest_5y,splits_5y,nested_selection}.json, <model>__beat_mkt_20d.json
  ml/results/label_study/{label_summary,label_variants,model_level}.json
  ml/results/feature_study/{eda_features,feature_ab_verdict,manifest_fe}.json
  ml/results/feature_sufficiency/feature_sufficiency.json
  ml/results/sota/{league_summary,exposures}.json and the per-model JSONs
  ml/results/strategy/{strategy.json,champion_monthly.csv}
  ml/results/audit/audit.json, ml/results/model_selection.json and the pilot per-model JSONs
  ml/results/{holiday_duplicates,data_profile}.json

5-year outputs (ml/scale5y_report.py, ml/scale5y_nested.py), consumed when present:
  scale5y_summary.json, bootstrap_5y.json, regimes_5y.json, portfolio_5y.json,
  nested_ensemble_rank / nested_lambdarank / nested_catboost __beat_mkt_20d.json, SCALE5Y.md.
  A file that is absent, unreadable, partial (fewer than 43 folds) or from a smoke run
  (bootstrap B < 1000) renders a muted "pending" card naming the file; the build never fails on them.

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
from decimal import ROUND_HALF_UP, Decimal
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
MID = "·"
DASH = "—"

CORE5 = ["all51", "nested_lgbm", "champion10", "lr_l2", "nested_lr_l2", "baseline_mom"]
ENS = "nested_ensemble_rank"
MEMBERS = ["nested_catboost", "nested_lambdarank"]
HEUR = "heuristic_mom20"
GATE_MODELS = ["nested_lgbm", "all51", ENS]
PAPER_BASKET = "liq_top_decile"
STRIP = ["all51", "nested_lgbm", "champion10", "lr_l2", "baseline_mom", ENS]
CMP7 = ["all51", "nested_lgbm", ENS, "champion10", "lr_l2", "nested_lr_l2", "baseline_mom"]
LEAGUE_ORDER = ["all51", "nested_lgbm", ENS, "nested_catboost", "nested_lambdarank", "champion10", "lr_l2",
                "nested_lr_l2", "baseline_mom"]
YEAR_COLS = ["nested_lgbm", "all51", "champion10", "lr_l2", "baseline_mom"]
SLOT = {"all51": 1, "nested_lgbm": 2, "champion10": 3, "lr_l2": 4, "baseline_mom": 5, ENS: 7}
NAME5 = {
    "all51": "LightGBM, all features",
    "nested_lgbm": "LightGBM, nested yearly selection",
    "champion10": "LightGBM, pilot 10 features",
    "lr_l2": "L2 logistic, all features",
    "nested_lr_l2": "L2 logistic, nested selection",
    "baseline_mom": "Momentum rule",
    ENS: "Rank ensemble",
    "nested_catboost": "CatBoost, 600 fixed trees",
    "nested_lambdarank": "LambdaRank",
    HEUR: "Momentum rank (no fit)",
}
LEAGUE_LABEL = {
    "all51": "LightGBM, all features (<code>all51</code>)",
    "nested_lgbm": "LightGBM, nested yearly selection (<code>nested_lgbm</code>, exit-date purge)",
    ENS: "Rank ensemble (<code>nested_ensemble_rank</code>: LightGBM + LambdaRank + CatBoost on the nested sets)",
    "nested_catboost": "CatBoost, 600 fixed trees (ensemble member)",
    "nested_lambdarank": "LambdaRank (ensemble member)",
    "champion10": "LightGBM, pilot 10 features (<code>champion10</code>)",
    "lr_l2": "L2 logistic, all features (<code>lr_l2</code>)",
    "nested_lr_l2": "L2 logistic, nested selection (<code>nested_lr_l2</code>)",
    "baseline_mom": "Momentum rule (<code>baseline_mom</code>)",
}

# Figures that exist only in Markdown (no JSON/CSV carries them). Source named per group.
MD_ONLY = {
    "store_rows": 3_078_294, "store_sessions": 1_245, "store_first": "2021-10-01",
    "store_last": "2026-10-16", "store_tickers": 4_219, "store_feature_rows": 2_722_591,
    "sessions_by_year": {"2021": 63, "2022": 248, "2023": 245, "2024": 247, "2025": 247, "2026": 195},
    "echo_max_share": "0.35%", "echo_max_date": "2026-07-23", "ingest_tests": "19 of 19",
    "gkx_corr": "0.06", "qlib_ic": "0.045", "gkx_r2": "0.33 to 0.40% vs 0.11 to 0.27%",
    "univ_excess_range": "+1.4% to +2.0%", "champ_vs_mean_windows": "3 of 5",
    "naive_flip": MINUS + "5.3%", "cost_realistic": "15 to 25", "fno_names": "about 200",
    "train_dates": "140 to 230", "indep_xs": "7 to 11", "lit_refs": 71,
}
MD_ONLY_SOURCES = [
    ("Data store: 3,078,294 rows, 1,245 sessions, 4,219 tickers, 2,722,591 feature rows, sessions per "
     "year, largest echo share 0.35% (2026-07-23), 19 of 19 ingest tests", "ml/PROGRAM_REPORT.md §3"),
    ("Literature: GKX correlation about 0.06, Qlib IC 0.045, GKX monthly R², 71 references",
     "ml/research/SOTA_FORECASTING.md"),
    ("Universe mean minus median +1.4% to +2.0% per 20 days; champion positive against the mean in 3 of 5 windows",
     "ml/results/label_study/LABEL_STUDY.md"),
    ("Naive fully-invested flip to " + MINUS + "5.3%; realistic costs 15 to 25 bps; about 200 F&O names",
     "ml/results/strategy/STRATEGY.md"),
    ("140 to 230 training dates; 7 to 11 independent cross-sections", "ml/results/sota/SOTA_MODELS.md"),
]

D = SimpleNamespace()   # closed artifacts and derived data
P = SimpleNamespace()   # 5-year outputs (may be pending)
FACTS: dict[str, str] = {}      # verdict-board numbers as rendered; read by the QA script
LOADED: dict[str, str] = {}     # input -> read / absent / unreadable / not used


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


PILOT_ROWS = [  # PROGRAM_REPORT.md §6.1 rows: (json, label, family, note)
    ("lgbm_fs_selected_clean", "LightGBM, 10 selected features", "GBM", "t11"),
    ("lr_l2_clean", "L2 logistic (= L1 = elastic net)", "linear", ""),
    ("random_forest", "Random forest", "trees", ""),
    ("rl_reinforce", "REINFORCE contextual bandit", "RL", "rl"),
    ("decision_tree", "Decision tree", "trees", ""),
    ("lightgbm", "LightGBM, all features", "GBM", ""),
    ("mlp", "MLP", "deep", ""),
    ("xgboost", "XGBoost", "GBM", ""),
    ("lstm", "LSTM", "deep", ""),
    ("baseline_mom", "Momentum rule (1 feature)", "baseline", ""),
    ("gru", "GRU", "deep", ""),
]
SOTA_ROWS = [  # PROGRAM_REPORT.md §6.2 rows: (json, table label, chart label)
    ("ensemble_rank", "Rank-average ensemble (LightGBM + LambdaRank + CatBoost)", "Rank-average ensemble"),
    ("catboost_fixed600", "CatBoost, fixed 600 trees", "CatBoost, fixed 600 trees"),
    ("lgbm_lambdarank", "LightGBM LambdaRank", "LightGBM LambdaRank"),
    ("lgbm_huber", "LightGBM Huber regression", "LightGBM Huber regression"),
    ("cs_transformer", "Cross-sectional set-attention transformer", "Set-attention transformer"),
    ("patchtst_lite", "PatchTST-lite (temporal transformer)", "PatchTST-lite"),
    ("dlinear", "DLinear (sequence control)", "DLinear"),
]


def load_closed() -> None:
    D.man_pilot = load_json(ML / "data" / "manifest.json")
    D.splits_pilot = load_json(ML / "data" / "splits.json")
    D.man5 = load_json(S5 / "manifest_5y.json")
    D.splits5 = load_json(S5 / "splits_5y.json")
    D.sel = load_json(S5 / "nested_selection.json")
    D.m5 = {m: load_json(S5 / f"{m}__{TASK}.json") for m in CORE5}
    D.ms = load_json(RES / "model_selection.json")
    D.pilot = {m: load_json(RES / f"{m}__{TASK}.json") for m, *_ in PILOT_ROWS}
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
    D.sota = load_json(RES / "sota" / "league_summary.json")
    D.expo = load_json(RES / "sota" / "exposures.json")
    D.sota_m = {m: load_json(RES / "sota" / f"{m}__{TASK}.json") for m, *_ in SOTA_ROWS}
    D.strat = load_json(RES / "strategy" / "strategy.json")
    D.monthly = read_csv(RES / "strategy" / "champion_monthly.csv")
    D.audit = load_json(RES / "audit" / "audit.json")


def load_pending(pdir: Path) -> None:
    def lab(nm: str) -> str:
        return f"ml/results/scale5y/{nm}"

    nfolds = len(D.splits5["folds"])
    P.boot_file = load_json(pdir / "bootstrap_5y.json", lab("bootstrap_5y.json"), required=False)
    summary = load_json(pdir / "scale5y_summary.json", lab("scale5y_summary.json"), required=False)
    regimes = load_json(pdir / "regimes_5y.json", lab("regimes_5y.json"), required=False)
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
    # run identity: every scale5y_report run writes bootstrap_5y.json first, then regimes and the summary
    bt = P.boot_file
    P.boot_B = (bt or {}).get("design", {}).get("B")
    P.boot_at = (bt or {}).get("generated_at", "")
    P.final = bt is not None and P.boot_B is not None and P.boot_B >= B_FINAL
    if bt is not None and not P.final:
        LOADED[lab("bootstrap_5y.json")] = f"smoke run (B = {P.boot_B}), not used"
    P.boot = bt if P.final else None
    if summary is not None:
        sb = summary.get("bootstrap", {}).get("design", {}).get("B")
        if not (P.final and sb is not None and sb >= B_FINAL and summary.get("generated_at", "") >= P.boot_at):
            LOADED[lab("scale5y_summary.json")] = f"smoke run (B = {sb}), not used"
            summary = None
    P.summary = summary
    if regimes is not None and not (P.final and regimes.get("generated_at", "") >= P.boot_at):
        LOADED[lab("regimes_5y.json")] = "from a smoke run, not used"
        regimes = None
    P.regimes = regimes


# ===================================================================== formatting
def E(s) -> str:
    return html.escape(str(s), quote=True)


def neg(s: str) -> str:
    return s.replace("-", MINUS)


def dq(x: float, d: int, scale: int = 1) -> Decimal:
    """Round half-up on the value as stored (0.0455 -> 0.046, as the Markdown rounds it), not on its
    binary float expansion (which gives 0.045); a rounded negative zero becomes zero."""
    q = (Decimal(repr(float(x))) * scale).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP)
    return q + 0


def f(x: float, d: int = 4) -> str:
    return neg(f"{dq(x, d):.{d}f}")


def sg(x: float, d: int = 3) -> str:
    return neg(f"{dq(x, d):+.{d}f}")


def pc(x: float, d: int = 1) -> str:
    """Signed percent of a fraction."""
    return neg(f"{dq(x, d, 100):+.{d}f}%")


def pu(x: float, d: int = 0) -> str:
    """Unsigned percent of a fraction."""
    return neg(f"{dq(x, d, 100):.{d}f}%")


def n(x) -> str:
    return f"{int(round(x)):,}"


def ci(lo: float, hi: float, d: int = 4, signed: bool = True) -> str:
    g = sg if signed else f
    return f"[{g(lo, d)}, {g(hi, d)}]"


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


def rng(lo: str, hi: str) -> str:
    return lo if lo == hi else f"{lo} to {hi}"


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


GLYPH = {"pass": "✓", "fail": "✕", "pending": "…", "info": "i"}


def chip(status: str, text: str | None = None) -> str:
    s = status.lower()
    return (f'<span class="st {s}"><span aria-hidden="true">{GLYPH.get(s, "")}</span> '
            f'{E(text or status.upper())}</span>')


def pending_card(title: str, files: list[str], running: str) -> str:
    fl = ", ".join(f"<code>{E(x)}</code>" for x in files)
    return (f'<div class="pending"><div class="ph">Pending</div><h4>{E(title)}</h4>'
            f'<p>Waits for {fl}. {E(running)}</p>'
            f'<p class="dim2">Re-run <code>python3 -m ml.make_program_report</code> when it lands; this card '
            f'is then replaced by the numbers.</p></div>')


def srcs(*paths: str) -> str:
    return '<p class="srcs">Source: ' + ", ".join(f"<code>{E(p)}</code>" for p in paths) + "</p>"


def table(head: list[str], rows: list[list[str]], cls: str = "", wrap: tuple[int, ...] = (),
          row_cls: list[str] | None = None) -> str:
    def cell(tag: str, i: int, c: str) -> str:
        return f'<{tag} class="wrapcell">{c}</{tag}>' if i in wrap else f"<{tag}>{c}</{tag}>"

    th = "".join(cell("th", i, h) for i, h in enumerate(head))
    body = []
    for k, r in enumerate(rows):
        rc = (row_cls or [""] * len(rows))[k]
        body.append(f'<tr class="{rc}">' + "".join(cell("td", i, c) for i, c in enumerate(r)) + "</tr>")
    return (f'<div class="scroll"><table class="{cls}"><thead><tr>{th}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


# ===================================================================== derived data
def stats5(js: dict) -> dict:
    folds = js["folds"]
    a = [x["auc"] for x in folds]
    names = [x["fold"] for x in folds]
    assert abs(sum(a) / len(a) - js["cv_auc_mean"]) < 1e-9, js["model"]
    wi = min(range(len(a)), key=lambda i: a[i])
    dsv = [x["decile_spread"] for x in folds if x.get("decile_spread") is not None]
    sets = js.get("nested_feature_sets") or {}
    if js.get("n_features"):
        feats = str(js["n_features"])
    elif sets:
        sz = sorted(len(v) for v in sets.values())
        feats = rng(str(sz[0]), str(sz[-1]))
    else:
        feats = DASH
    per_year = {}
    for y in sorted({x[:4] for x in names}):
        v = [a[i] for i, nm in enumerate(names) if nm.startswith(y)]
        per_year[y] = (sum(v) / len(v), len(v))
    f39 = [a[i] for i, nm in enumerate(names) if nm <= "2026-03"]
    ho = js.get("holdout") or {}
    return {"model": js["model"], "cv": js["cv_auc_mean"], "sd": js["cv_auc_std"], "auc": dict(zip(names, a)),
            "n": len(a), "ge": sum(x >= 0.5 for x in a), "lt": sum(x < 0.5 for x in a),
            "worst": a[wi], "worst_m": names[wi], "ho": ho.get("auc"), "ho_ds": ho.get("decile_spread"),
            "ho_dm": ho.get("decile_means"), "mds": sum(dsv) / len(dsv) if dsv else None,
            "mds_pos": sum(x > 0 for x in dsv), "n_ds": len(dsv), "feats": feats, "per_year": per_year,
            "cv39": sum(f39) / len(f39), "n39": len(f39), "ntrain": {x["fold"]: x.get("n_train") for x in folds}}


def derive() -> None:
    D.folds = [s["name"] for s in D.splits5["folds"]]
    D.M5 = {m: D.m5[m] for m in CORE5}
    for m in [ENS] + MEMBERS:
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
    D.A = {t["id"]: t for t in D.audit["tests"]}
    D.Tab = {r["id"]: r for r in D.audit["table"]}
    D.sota_rows = {r["model"]: r for r in D.sota["rows"]}
    D.BAR = D.fab["rebuild_bar_cv"]
    assert abs(D.BAR - D.sota["pass_mark"]) < 1e-12
    D.CTRL = D.fab["control_clean_cv"]
    D.sm = D.strat["models"]
    D.IC = D.eda["ic_stability"]
    D.eda_months = sorted({mo for v in D.IC.values() for mo in v["monthly_ic"]})
    sel = D.sel
    D.years = sorted(sel["per_year"])
    D.sel_overlap = [sel["stability"][f"{a}->{b}"]["selected_overlap"] for a, b in zip(D.years[:-1], D.years[1:])]
    D.top10_overlap = [sel["stability"][f"{a}->{b}"]["top10_overlap"] for a, b in zip(D.years[:-1], D.years[1:])]
    D.k_sel = [sel["per_year"][y]["k_selected"] for y in D.years]
    D.pilot_ov = [sel["per_year"][y]["n_overlap_selected_with_pilot10"] for y in D.years]
    D.n_cand = 50 + len(D.suff["verdict"]["features_new_information_bh"])
    assert D.m5["all51"]["n_features"] == 50
    D.ex = D.strat["deflated_sharpe"]
    D.gates = compute_gates()


def compute_gates() -> dict:
    """SCALE_UP.md gates 1-5, scored exactly as ml/scale5y_report.py gates(); None where pending."""
    out = {}
    pairs = (P.boot or {}).get("pairs", {})
    nh = str(P.port["dsr"]["N_headline"]) if P.port else None
    for m in GATE_MODELS:
        if m not in D.S5:
            continue
        s = D.S5[m]
        g = {}
        pr = pairs.get(f"{m} - lr_l2")
        delta = s["cv"] - D.S5["lr_l2"]["cv"]
        if pr:
            d = pr["cv_mean"]
            g["1"] = {"num": f"{sg(d['delta'], 4)} {ci(*d['ci95'])}", "pass": d["delta"] > 0 and d["ci95"][0] > 0}
        elif delta <= 0:
            g["1"] = {"num": f"{sg(delta, 4)} (interval pending)", "pass": False}
        g["2"] = {"num": f"{pu(s['ge'] / s['n'])} ({s['ge']}/{s['n']})", "pass": s["ge"] / s["n"] >= 0.90}
        if P.port and f"{m}|top_decile" in P.port["books"]:
            b = P.port["books"][f"{m}|top_decile"]
            g["3"] = {"num": f"{b['months_positive']}/{b['n_months']} = {pu(b['share_months_positive'])}",
                      "pass": b["share_months_positive"] >= 0.75}
        g["4"] = {"num": ", ".join(str(x) for x in D.top10_overlap), "pass": min(D.top10_overlap) >= 7}
        if P.port and f"{m}|{PAPER_BASKET}" in P.port["dsr"]["books"]:
            e = P.port["dsr"]["books"][f"{m}|{PAPER_BASKET}"]["skill"][nh]
            g["5"] = {"num": f"{e['dsr']:.3f}", "pass": e["dsr"] >= 0.95}
        out[m] = g
    if P.summary is not None:   # cross-check against the scale-up agent's own scoring
        for m, g in out.items():
            sg_ = P.summary["gates"].get(m, {})
            for k, v in g.items():
                if k in sg_:
                    assert sg_[k]["pass"] == v["pass"], (m, k)
    return out


def ninth(x: float) -> str:
    return f"{x:.2f}"


def cap5(x: float) -> str:
    return f"{int(round(x / 5.0) * 5):,}"


# ===================================================================== charts
def svg_coverage() -> str:
    W, H = 920, 240
    X0, X1 = 150, 902

    def mi(d: str) -> float:
        y, m = int(d[:4]), int(d[5:7])
        dd = int(d[8:10]) if len(d) >= 10 else 1
        return (y - 2021) * 12 + (m - 10) + (dd - 1) / 31

    span = mi("2026-11-01")

    def X(d: str) -> float:
        return lin(mi(d), 0, span, X0, X1)

    p = [svg_open(W, H, "Data timeline: NSE sessions per calendar year in the store, the 5-year modelling "
                        "dataset and the pilot dataset")]
    for y in range(2022, 2027):
        x = X(f"{y}-01-01")
        p.append(f'<line x1="{x:.1f}" y1="14" x2="{x:.1f}" y2="{H - 24}" class="grid"/>')
    for y in range(2021, 2027):
        a = X("2021-10-01") if y == 2021 else X(f"{y}-01-01")
        b = X(f"{y + 1}-01-01") if y < 2026 else X(MD_ONLY["store_last"])
        p.append(f'<text x="{(a + b) / 2:.1f}" y="{H - 6}" class="ax" text-anchor="middle">{y}</text>')
    yr = 24
    p.append(f'<text x="{X0 - 12}" y="{yr + 15}" class="lbl" text-anchor="end">NSE sessions</text>')
    p.append(f'<text x="{X0 - 12}" y="{yr + 29}" class="ax ax-s" text-anchor="end">in the store</text>')
    sby = MD_ONLY["sessions_by_year"]
    for y in sorted(sby):
        a = X(MD_ONLY["store_first"]) if y == "2021" else X(f"{y}-01-01")
        b = X(MD_ONLY["store_last"]) if y == "2026" else X(f"{int(y) + 1}-01-01")
        tip = f"{y}: {sby[y]} sessions" + (" (Q4 only)" if y == "2021" else "") + (
            f" (to {MD_ONLY['store_last']})" if y == "2026" else "")
        p.append(f'<rect x="{a + 1:.1f}" y="{yr}" width="{b - a - 2:.1f}" height="32" rx="4" class="cell-y" '
                 f'data-tip="{E(tip)}"/>')
        p.append(f'<text x="{(a + b) / 2:.1f}" y="{yr + 21}" class="val" text-anchor="middle">{sby[y]}</text>')
    m5, s5 = D.man5, D.splits5
    y2 = 84

    def row(y0, man, spl, title, folds_label):
        p.append(f'<text x="{X0 - 12}" y="{y0 + 13}" class="lbl" text-anchor="end">{title}</text>')
        p.append(f'<text x="{X0 - 12}" y="{y0 + 27}" class="ax ax-s" text-anchor="end">{n(man["rows"])} rows</text>')
        segs = [(man["date_min"], spl["folds"][0]["test_start"], "seg-warm", "training only"),
                (spl["folds"][0]["test_start"], spl["folds"][-1]["test_end"], "seg-cv",
                 f"{len(spl['folds'])} monthly folds {spl['folds'][0]['name']} to {spl['folds'][-1]['name']}"),
                (spl["holdout"]["test_start"], spl["holdout"]["test_end"], "seg-ho",
                 f"holdout {spl['holdout']['test_start']} to {spl['holdout']['test_end']}"),
                (spl["holdout"]["test_end"], man["date_max"], "seg-tail", "unlabelled tail (20-session label window)")]
        for a, b, cls, tip in segs:
            xa, xb = X(a), X(b)
            p.append(f'<rect x="{xa:.1f}" y="{y0}" width="{max(xb - xa - 1.5, 2):.1f}" height="22" rx="3" '
                     f'class="{cls}" data-tip="{E(tip)}"/>')
        if folds_label:
            p.append(f'<text x="{X(spl["folds"][0]["test_start"]) + 8:.1f}" y="{y0 + 15}" class="inbar">'
                     f'{folds_label}</text>')

    row(y2, m5, s5, "5-year dataset", f"{len(s5['folds'])} monthly CV folds")
    y3 = 134
    row(y3, D.man_pilot, D.splits_pilot, "Pilot dataset", "")
    for d in D.hd["phantom_days"]:
        x = X(d)
        p.append(f'<line x1="{x:.1f}" y1="{y3 + 26}" x2="{x:.1f}" y2="{y3 + 34}" class="tick-echo" '
                 f'data-tip="{E(d + ": holiday echo, removed")}"/>')
    p.append(f'<text x="{X(D.hd["phantom_days"][0]) - 6:.1f}" y="{y3 + 35}" class="ax ax-s" text-anchor="end">'
             f'{len(D.hd["phantom_days"])} holiday-echo days removed</text>')
    xm = X("2026-03-01")
    p.append(f'<line x1="{xm:.1f}" y1="{y2 - 8}" x2="{xm:.1f}" y2="{y3 + 24}" class="mark"/>')
    p.append(f'<text x="{xm - 5:.1f}" y="{y2 - 11}" class="ax ax-s" text-anchor="end">March 2026 inversion</text>')
    ky = H - 38
    keys = [("seg-warm", "training only"), ("seg-cv", "monthly CV folds"), ("seg-ho", "holdout, used once"),
            ("seg-tail", "unlabelled tail")]
    x = X0
    for cls, t in keys:
        p.append(f'<rect x="{x}" y="{ky - 9}" width="12" height="10" rx="2" class="{cls}"/>'
                 f'<text x="{x + 17}" y="{ky}" class="ax ax-s">{t}</text>')
        x += 30 + 6.2 * len(t)
    p.append("</svg>")
    return "".join(p)


H_ORDER = [1, 2, 3, 5, 10, 20, 40]


def svg_horizon_panel(kind: str) -> tuple[str, str]:
    W, H = 330, 230
    X0, X1, Y0, Y1 = 44, 318, 16, 178

    def X(i: int) -> float:
        return lin(i, 0, len(H_ORDER) - 1, X0 + 10, X1 - 10)

    L = D.lsum["labels"]
    runs = D.lmod["runs"]
    econ = D.lmod["econ"]
    if kind == "q":
        title = "Features passing BH q < 0.05, Newey-West adjusted (of 40)"
        d0, d1, ticks = 0, 24, [0, 5, 10, 15, 20]
        ser = [("next-open", "s1", {h: L[f"ex_no_{h}d"]["n_q_nw_lt_0.05"] for h in H_ORDER}),
               ("close-to-close", "s2", {h: L[f"ex_cc_{h}d"]["n_q_nw_lt_0.05"] for h in H_ORDER})]

        def fmt(v):
            return f"{v:d}"
    elif kind == "auc":
        title = "Model CV AUC, excess label vs raw > 0 label"
        d0, d1, ticks = 0.50, 0.57, [0.50, 0.52, 0.54, 0.56]
        ex = {r["h"]: r["cv_auc_mean"] for k, r in runs.items() if "_ex_" in k}
        raw = {r["h"]: r["cv_auc_mean"] for k, r in runs.items() if "_raw_" in k}
        ser = [("excess, next-open", "s1", ex), ("raw > 0, close-to-close", "s2", raw)]

        def fmt(v):
            return f"{v:.3f}"
    else:
        title = "Break-even cost, bps per side at 100% turnover"
        d0, d1, ticks = 0, 30, [0, 10, 20, 30]
        key = "breakeven_cost_per_side_bps_full_turnover"
        ex = {runs[k]["h"]: e["oos_all"]["label_return"][key] for k, e in econ.items() if "_ex_" in k}
        raw = {runs[k]["h"]: e["oos_all"]["label_return"][key] for k, e in econ.items() if "_raw_" in k}
        ser = [("excess, next-open", "s1", ex), ("raw > 0, close-to-close", "s2", raw)]

        def fmt(v):
            return f"{v:.1f}"

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
        p.append(f'<text x="{X0 + 4}" y="{Y(20) - 5:.1f}" class="ax ax-s">20 bps per side assumed</text>')
    for i, h in enumerate(H_ORDER):
        p.append(f'<text x="{X(i):.1f}" y="{Y1 + 16}" class="ax ax-s" text-anchor="middle">{h}</text>')
    p.append(f'<text x="{(X0 + X1) / 2:.0f}" y="{H - 10}" class="ax" text-anchor="middle">horizon, sessions</text>')
    for name, slot, vals in ser:
        pts = [(X(i), Y(vals[h]), h, vals[h]) for i, h in enumerate(H_ORDER) if h in vals]
        if len(pts) > 1:
            pl = " ".join(f"{x:.1f},{y:.1f}" for x, y, _, _ in pts)
            p.append(f'<polyline points="{pl}" fill="none" stroke="var(--{slot})" stroke-width="2" '
                     f'stroke-linejoin="round" stroke-linecap="round"/>')
        for x, y, h, v in pts:
            p.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4.5" fill="var(--{slot})" stroke="var(--surface)" '
                     f'stroke-width="2" data-tip="{E(f"{name}, {h} sessions: {fmt(v)}")}"/>')
    if kind != "q":
        for h in [h for h in H_ORDER if h not in ser[0][2]]:
            i = H_ORDER.index(h)
            p.append(f'<text x="{X(i):.1f}" y="{Y1 - 8}" class="ax ax-s" text-anchor="middle">not run</text>')
    p.append("</svg>")
    leg = "".join(f'<li><span class="dot" style="background:var(--{slot})"></span>{E(name)}</li>'
                  for name, slot, _ in ser)
    return title, "".join(p) + f'<ul class="legend sm">{leg}</ul>'


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
    covered = {x for _, fs in FAMILIES for g in fs for x in [g] + ([TWINS[g]] if g in TWINS else [])}
    assert covered == set(IC), sorted(set(IC) ^ covered)
    worst = {mo: sum(1 for v in IC.values() if (v.get("worst_month") or {}).get("month") == mo) for mo in months}
    mx = max(worst.values())
    years: dict[str, int] = {}
    for mo in months:
        years[mo[:4]] = years.get(mo[:4], 0) + 1
    h1 = ('<tr><th rowspan="2" class="fcol">Feature</th>'
          + "".join(f'<th colspan="{k}" class="yr">{y}</th>' for y, k in years.items())
          + '<th rowspan="2" class="sumh">Mean IC × 100</th><th rowspan="2" class="sumh">Worst month</th></tr>')
    h2 = "<tr>" + "".join(f'<th class="mo{" brk" if mo == D.crash else ""}">{MONTHS[int(mo[5:]) - 1][:3]}</th>'
                          for mo in months) + "</tr>"
    cnt_cells = []
    for mo in months:
        k = worst[mo]
        cls = ("cmax" if k == mx else "") + (" brk" if mo == D.crash else "")
        tip = f"{mname(mo)}: the worst IC month for {k} of {len(IC)} features"
        cnt_cells.append(f'<td class="{cls}" data-tip="{E(tip)}">{k if k else MID}</td>')
    body = [f'<tr class="cnt"><th scope="row">Features at their worst</th>{"".join(cnt_cells)}'
            f'<td class="sum"></td><td class="sum strong">{mx} of {len(IC)}</td></tr>']
    ncol = 1 + len(months) + 2
    for fam, feats in FAMILIES:
        body.append(f'<tr class="fam"><th colspan="{ncol}" scope="colgroup">{E(fam)}</th></tr>')
        for x in feats:
            v = IC[x]
            name = x + (f" {MID} {TWINS[x]}" if x in TWINS else "")
            cells = []
            for mo in months:
                val = v["monthly_ic"].get(mo)
                cls = heat_bucket(val) + (" brk" if mo == D.crash else "")
                if val is None:
                    cells.append(f'<td class="{cls}">{MID}</td>')
                else:
                    tip = f"{name} {MID} {mo}: IC {sg(val)}"
                    cells.append(f'<td class="{cls}" data-tip="{E(tip)}">{neg(str(round(val * 100)))}</td>')
            wm = (v.get("worst_month") or {}).get("month", "")
            body.append(f'<tr><th scope="row">{E(name)}</th>{"".join(cells)}'
                        f'<td class="sum">{sg(v["mean_ic"] * 100, 1)}</td>'
                        f'<td class="sum{" strong" if wm == D.crash else ""}">{E(mshort(wm)) if wm else ""}</td></tr>')
    return f'<table class="heat"><thead>{h1}{h2}</thead><tbody>{"".join(body)}</tbody></table>'


HM_KEY = ('<div class="hm-key" aria-hidden="true">IC × 100:&nbsp;<span class="sw hm-n3"></span>≤ '
          + MINUS + '10 <span class="sw hm-n2"></span>' + MINUS + '6 <span class="sw hm-n1"></span>' + MINUS
          + '2 <span class="sw hm-0"></span>within ±2 <span class="sw hm-p1"></span>+2 '
          '<span class="sw hm-p2"></span>+6 <span class="sw hm-p3"></span>≥ +10</div>')


def svg_resid_ic() -> str:
    fs = D.suff
    surv = set(fs["verdict"]["features_new_information_bh"])
    q_bar = fs["rules"]["bh_q"]
    rows = sorted(((x, fs["ic_summary"][x]["resid_full"]) for x in fs["new_features"]),
                  key=lambda r: (-r[1]["t"], r[0]))
    W, L, R = 760, 196, 556
    top, rh = 24, 22
    H = top + rh * len(rows) + 34
    lo, hi = -0.045, 0.035

    def X(v: float) -> float:
        return lin(v, lo, hi, L, R)

    p = [svg_open(W, H, "Residual IC of the 23 new features against the champion's 10 ranks, sorted by t; "
                        "the two BH survivors highlighted")]
    for t in (-0.04, -0.02, 0.02):
        p.append(f'<line x1="{X(t):.1f}" y1="{top - 6}" x2="{X(t):.1f}" y2="{H - 30}" class="grid"/>')
        p.append(f'<text x="{X(t):.1f}" y="{H - 12}" class="ax" text-anchor="middle">{sg(t, 2)}</text>')
    p.append(f'<line x1="{X(0):.1f}" y1="{top - 6}" x2="{X(0):.1f}" y2="{H - 30}" class="axisln"/>')
    p.append(f'<text x="{X(0):.1f}" y="{H - 12}" class="ax" text-anchor="middle">0</text>')
    p.append(f'<text x="{R + 12}" y="{top - 10}" class="ax ax-s">t {MID} BH q (passes at q ≤ {q_bar:g})</text>')
    for i, (x, r) in enumerate(rows):
        y = top + rh * i + rh / 2
        hot = x in surv
        tip = (f"{x}: residual IC {sg(r['mean_ic'], 4)}, t {sg(r['t'], 2)}, BH q {r['q_bh']:.3f}"
               + (" (passes)" if hot else ""))
        p.append(f'<g data-tip="{E(tip)}"><rect x="0" y="{y - rh / 2:.1f}" width="{W}" height="{rh}" fill="transparent"/>')
        p.append(f'<text x="{L - 10}" y="{y + 4:.1f}" class="{"lbl-em" if hot else "lbl"}" text-anchor="end">{E(x)}</text>')
        p.append(f'<path d="{hbar(X(0), X(r["mean_ic"]), y, 13, 3)}" fill="{"var(--s1)" if hot else "var(--axisc)"}"/></g>')
        p.append(f'<text x="{R + 12}" y="{y + 4:.1f}" class="{"val-em" if hot else "val"}">t {sg(r["t"], 2)} {MID} '
                 f'q {r["q_bh"]:.3f}</text>')
    p.append("</svg>")
    return "".join(p)


def svg_league_panel(rows: list[dict], title: str, d0: float = 0.44, d1: float = 0.58,
                     control: float | None = None) -> str:
    W, L, R = 860, 236, 820
    top, rh = 50, 30
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
    p.append(f'<line x1="{X(D.BAR):.1f}" y1="{top - 24}" x2="{X(D.BAR):.1f}" y2="{H - 26}" class="passln"/>')
    p.append(f'<text x="{X(D.BAR) + 6:.1f}" y="{top - 28}" class="lbl-em">bar {f(D.BAR)}</text>')
    if control is not None:
        p.append(f'<line x1="{X(control):.1f}" y1="{top - 24}" x2="{X(control):.1f}" y2="{H - 26}" class="ctrlln"/>')
        p.append(f'<text x="{X(control) - 6:.1f}" y="{top - 28}" class="lbl" text-anchor="end">control {f(control)}</text>')
    for i, r in enumerate(rows):
        y = top + rh * i + rh / 2
        tip = (f"{r['name']}: CV AUC {f(r['cv'])} ± {r['sd']:.3f}; worst fold {r['worst']:.3f}; "
               f"holdout {r['ho']:.3f}")
        p.append(f'<g data-tip="{E(tip)}"><rect x="0" y="{y - rh / 2:.1f}" width="{W}" height="{rh}" fill="transparent"/>')
        p.append(f'<text x="{L - 12}" y="{y + 4:.1f}" class="lbl" text-anchor="end">{E(r["name"])}</text>')
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


LEAGUE_KEY = ('<ul class="legend"><li><span class="dot" style="background:var(--s1)"></span>CV AUC, mean '
              '± 1 sd across folds</li><li><span class="tri"></span>worst fold</li>'
              '<li><span class="dia"></span>holdout</li><li><span class="lk chance-k"></span>chance 0.50</li>'
              '<li><span class="lk pass-k"></span>pre-registered bar</li></ul>')


def svg_strip() -> str:
    S = D.S5
    models = [m for m in STRIP if m in S]
    folds = D.folds
    W, H = 940, 392
    X0, X1, XH = 58, 846, 900
    Y0, Y1 = 60, 318
    d0, d1 = 0.34, 0.69
    step = (X1 - X0) / (len(folds) - 1)

    def X(i: int) -> float:
        return X0 + i * step

    def Y(v: float) -> float:
        return lin(v, d0, d1, Y1, Y0)

    p = [svg_open(W, H, "Monthly fold AUC over the 43 folds, January 2023 to July 2026, and the holdout, per model",
                  ' id="strip"')]
    k = len(D.short_folds)
    xa, xb = X(0) - step / 2, X(k - 1) + step / 2
    nt = S["all51"]["ntrain"]
    p.append(f'<rect x="{xa:.1f}" y="{Y0}" width="{xb - xa:.1f}" height="{Y1 - Y0}" class="shade"/>')
    p.append(f'<text x="{xa + 6:.1f}" y="{Y0 + 15}" class="ax ax-s">short training window (under '
             f'{FULL_WINDOW_ROWS // 1000}k rows): {folds[0]} to {D.short_folds[-1]}</text>')
    p.append(f'<text x="{xa + 6:.1f}" y="{Y0 + 28}" class="ax ax-s">{n(nt[folds[0]])} to '
             f'{n(nt[D.short_folds[-1]])} training rows</text>')
    for t in (0.40, 0.45, 0.55, 0.60, 0.65):
        p.append(f'<line x1="{X0 - 6}" y1="{Y(t):.1f}" x2="{XH + 14}" y2="{Y(t):.1f}" class="grid"/>')
        p.append(f'<text x="{X0 - 10}" y="{Y(t) + 4:.1f}" class="ax" text-anchor="end">{t:.2f}</text>')
    p.append(f'<line x1="{X0 - 6}" y1="{Y(0.5):.1f}" x2="{XH + 14}" y2="{Y(0.5):.1f}" class="chance"/>')
    p.append(f'<text x="{X0 - 10}" y="{Y(0.5) + 4:.1f}" class="ax" text-anchor="end">0.50</text>')
    ml = [m for m in models if m != "baseline_mom"]
    ir = [folds.index(fo) for fo in D.run]
    rv = [S[m]["auc"][fo] for m in ml for fo in D.run]
    xr0, xr1 = X(ir[0]) - step / 2, X(ir[-1]) + step / 2
    yb = Y0 - 16
    p.append(f'<path d="M{xr0:.1f},{yb + 6:.1f} V{yb:.1f} H{xr1:.1f} V{yb + 6:.1f}" class="bracket"/>')
    p.append(f'<text x="{(xr0 + xr1) / 2:.1f}" y="{yb - 7:.1f}" class="anno-t" text-anchor="middle">'
             f'{mshort(D.run[0])} to {mshort(D.run[-1])}: {min(rv):.2f} to {max(rv):.2f}</text>')
    ic = folds.index(D.crash)
    cv = [S[m]["auc"][D.crash] for m in models]
    p.append(f'<line x1="{X(ic):.1f}" y1="{Y0}" x2="{X(ic):.1f}" y2="{Y1}" class="mark"/>')
    p.append(f'<text x="{X(ic) - 7:.1f}" y="{Y(0.352):.1f}" class="anno-t" text-anchor="end">'
             f'{mshort(D.crash)}: {min(cv):.2f} to {max(cv):.2f}</text>')
    for i, fo in enumerate(folds):
        if fo.endswith("-01"):
            p.append(f'<text x="{X(i):.1f}" y="{Y1 + 32}" class="ax" text-anchor="middle">{fo[:4]}</text>')
        if int(fo[5:]) % 3 == 1:
            p.append(f'<line x1="{X(i):.1f}" y1="{Y1}" x2="{X(i):.1f}" y2="{Y1 + 5}" class="axisln"/>')
            p.append(f'<text x="{X(i):.1f}" y="{Y1 + 17}" class="ax ax-s" text-anchor="middle">'
                     f'{MONTHS[int(fo[5:]) - 1][:3]}</text>')
    p.append(f'<text x="{XH:.1f}" y="{Y1 + 17}" class="ax ax-s" text-anchor="middle">holdout</text>')
    p.append(f'<line x1="{XH - 24:.1f}" y1="{Y0}" x2="{XH - 24:.1f}" y2="{Y1}" class="grid"/>')
    if P.regimes is not None:
        pm = P.regimes["per_month"]
        yd = Y1 + 44
        for i, fo in enumerate(folds):
            r = pm.get(fo, {})
            if r.get("direction") == "down":
                tip = f"{fo}: down month (equal-weight universe 20-day return {pc(r['ew_fwd_20d'])})"
                p.append(f'<rect x="{X(i) - step / 2 + 1:.1f}" y="{yd}" width="{step - 2:.1f}" height="7" rx="1.5" '
                         f'class="down-cell" data-tip="{E(tip)}"/>')
        p.append(f'<text x="{X0 - 10}" y="{yd + 7}" class="ax ax-s" text-anchor="end">down month</text>')
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
        vals = f" {MID} ".join(f"{m} {S[m]['auc'][fo]:.3f}" for m in models)
        p.append(f'<rect x="{X(i) - step / 2:.1f}" y="{Y0}" width="{step:.1f}" height="{Y1 - Y0}" fill="transparent" '
                 f'data-tip="{E(f"{fo} ({n(nt[fo])} training rows): {vals}")}"/>')
    p.append("</svg>")
    return "".join(p)


def strip_legend() -> str:
    items = []
    for m in [x for x in STRIP if x in D.S5]:
        items.append(f'<li class="iso" data-m="{m}" tabindex="0"><span class="chip" '
                     f'style="background:var(--s{SLOT[m]})"></span><span>{E(NAME5[m])}</span>'
                     f'<b>{f(D.S5[m]["cv"])}</b></li>')
    return f'<ul class="legend iso-legend" data-for="strip">{"".join(items)}</ul>'


def svg_decile() -> str:
    S = D.S5
    models = [m for m in CMP7 if m in S]
    W, L, R = 880, 236, 640
    top, gh = 34, 46
    H = top + gh * len(models) + 34
    lo, hi = -0.04, 0.04

    def X(v: float) -> float:
        return lin(v, lo, hi, L, R)

    p = [svg_open(W, H, "Mean fold decile spread and holdout decile spread per model, beside CV AUC")]
    for t in (-0.04, -0.02, 0.02, 0.04):
        p.append(f'<line x1="{X(t):.1f}" y1="{top - 8}" x2="{X(t):.1f}" y2="{H - 30}" class="grid"/>')
        p.append(f'<text x="{X(t):.1f}" y="{H - 12}" class="ax" text-anchor="middle">{pc(t, 0)}</text>')
    p.append(f'<line x1="{X(0):.1f}" y1="{top - 8}" x2="{X(0):.1f}" y2="{H - 30}" class="axisln"/>')
    p.append(f'<text x="{X(0):.1f}" y="{H - 12}" class="ax" text-anchor="middle">0</text>')
    p.append(f'<text x="{R + 18}" y="{top - 14}" class="ax ax-s">CV AUC {MID} folds with spread &gt; 0</text>')
    for i, m in enumerate(models):
        s = S[m]
        y = top + gh * i + gh / 2
        p.append(f'<text x="{L - 12}" y="{y + 4:.1f}" class="lbl" text-anchor="end">{E(NAME5[m])}</text>')
        t1 = f"{NAME5[m]}: mean fold decile spread {pc(s['mds'], 2)} per 20 days ({s['mds_pos']} of {s['n_ds']} folds > 0)"
        t2 = f"{NAME5[m]}: holdout decile spread {pc(s['ho_ds'], 2)}"
        p.append(f'<path d="{hbar(X(0), X(s["mds"]), y - 7, 11, 3)}" fill="var(--s1)" data-tip="{E(t1)}"/>')
        p.append(f'<path d="{hbar(X(0), X(s["ho_ds"]), y + 7, 11, 3)}" fill="var(--s2)" data-tip="{E(t2)}"/>')
        p.append(f'<text x="{R + 18}" y="{y + 4:.1f}" class="val">{f(s["cv"])} {MID} {s["mds_pos"]}/{s["n_ds"]}</text>')
    p.append("</svg>")
    return "".join(p)


def svg_boot_models() -> str:
    bm = P.boot["models"]
    order = [m for m in ["nested_lgbm", "all51", ENS, "champion10", "lr_l2", "nested_lr_l2", "baseline_mom", HEUR]
             if m in bm]
    W, L, R = 860, 236, 700
    top, rh = 36, 36
    H = top + rh * len(order) + 30
    d0, d1 = 0.47, 0.58

    def X(v: float) -> float:
        return lin(v, d0, d1, L, R)

    p = [svg_open(W, H, "Five-year CV mean AUC and holdout AUC with 20-session block-bootstrap 95% intervals")]
    for t in (0.48, 0.50, 0.52, 0.54, 0.56, 0.58):
        cls = "chance" if t == 0.50 else "grid"
        p.append(f'<line x1="{X(t):.1f}" y1="{top - 8}" x2="{X(t):.1f}" y2="{H - 26}" class="{cls}"/>')
        p.append(f'<text x="{X(t):.1f}" y="{H - 8}" class="ax" text-anchor="middle">{t:.2f}</text>')
    p.append(f'<text x="{R + 16}" y="{top - 16}" class="ax ax-s">P(CV mean &gt; 0.50)</text>')
    for i, m in enumerate(order):
        b = bm[m]
        y = top + rh * i + rh / 2
        lo, hi = b["cv_mean_ci95"]
        hl, hh = b["holdout_ci95"]
        p.append(f'<text x="{L - 12}" y="{y + 4:.1f}" class="lbl" text-anchor="end">{E(NAME5.get(m, m))}</text>')
        t1 = f"{NAME5.get(m, m)}: CV mean {f(b['cv_auc_mean'])}, 95% interval [{f(lo)}, {f(hi)}]"
        t2 = f"{NAME5.get(m, m)}: holdout {f(b['holdout_auc'])}, 95% interval [{f(hl)}, {f(hh)}] (indicative)"
        p.append(f'<g data-tip="{E(t1)}"><line x1="{X(lo):.1f}" y1="{y - 6:.1f}" x2="{X(hi):.1f}" y2="{y - 6:.1f}" '
                 f'stroke="var(--s1)" stroke-width="2"/><circle cx="{X(b["cv_auc_mean"]):.1f}" cy="{y - 6:.1f}" r="5" '
                 f'fill="var(--s1)" stroke="var(--surface)" stroke-width="2"/></g>')
        p.append(f'<g data-tip="{E(t2)}"><line x1="{X(hl):.1f}" y1="{y + 7:.1f}" x2="{X(hh):.1f}" y2="{y + 7:.1f}" '
                 f'stroke="var(--s2)" stroke-width="2"/><circle cx="{X(b["holdout_auc"]):.1f}" cy="{y + 7:.1f}" r="4.5" '
                 f'fill="var(--surface)" stroke="var(--s2)" stroke-width="2.4"/></g>')
        p.append(f'<text x="{R + 16}" y="{y + 4:.1f}" class="val">{b["p_cv_mean_gt_050"]:.3f}</text>')
    p.append("</svg>")
    return "".join(p)


def pair_label(k: str) -> str:
    a, b = k.split(" - ")
    return f"{NAME5.get(a, a)} {MINUS} {NAME5.get(b, b)}"


def svg_boot_pairs() -> str:
    pr = P.boot["pairs"]
    keys = list(pr)
    W, L, R = 900, 380, 760
    top, rh = 36, 34
    H = top + rh * len(keys) + 44
    allv = [v for k in keys for c in ("cv_mean", "holdout") for v in pr[k][c]["ci95"]]
    lim = max(0.03, math.ceil(max(abs(x) for x in allv) * 100) / 100)

    def X(v: float) -> float:
        return lin(v, -lim, lim, L, R)

    p = [svg_open(W, H, "Paired five-year AUC differences, A minus B, with 95% block-bootstrap intervals")]
    t = -lim
    while t <= lim + 1e-9:
        zero = abs(t) < 1e-9
        p.append(f'<line x1="{X(t):.1f}" y1="{top - 8}" x2="{X(t):.1f}" y2="{H - 36}" class="{"axisln" if zero else "grid"}"/>')
        p.append(f'<text x="{X(t):.1f}" y="{H - 20}" class="ax" text-anchor="middle">{"0" if zero else sg(t, 2)}</text>')
        t = round(t + 0.02, 2)
    p.append(f'<text x="{X(0) + 6:.1f}" y="{H - 5}" class="ax ax-s">A higher →</text>')
    p.append(f'<text x="{X(0) - 6:.1f}" y="{H - 5}" class="ax ax-s" text-anchor="end">← B higher</text>')
    p.append(f'<text x="{R + 14}" y="{top - 16}" class="ax ax-s">folds A &gt; B</text>')
    for i, k in enumerate(keys):
        r = pr[k]
        y = top + rh * i + rh / 2
        c, h = r["cv_mean"], r["holdout"]
        p.append(f'<text x="{L - 12}" y="{y + 4:.1f}" class="lbl" text-anchor="end">{E(pair_label(k))}</text>')
        t1 = f"{pair_label(k)}: CV-mean difference {sg(c['delta'], 4)}, 95% interval {ci(*c['ci95'])}"
        t2 = f"{pair_label(k)}: holdout difference {sg(h['delta'], 4)}, 95% interval {ci(*h['ci95'])}"
        p.append(f'<g data-tip="{E(t1)}"><line x1="{X(c["ci95"][0]):.1f}" y1="{y - 6:.1f}" x2="{X(c["ci95"][1]):.1f}" '
                 f'y2="{y - 6:.1f}" stroke="var(--s1)" stroke-width="2"/><circle cx="{X(c["delta"]):.1f}" cy="{y - 6:.1f}" '
                 f'r="5" fill="var(--s1)" stroke="var(--surface)" stroke-width="2"/></g>')
        p.append(f'<g data-tip="{E(t2)}"><line x1="{X(h["ci95"][0]):.1f}" y1="{y + 7:.1f}" x2="{X(h["ci95"][1]):.1f}" '
                 f'y2="{y + 7:.1f}" stroke="var(--s2)" stroke-width="2"/><circle cx="{X(h["delta"]):.1f}" cy="{y + 7:.1f}" '
                 f'r="4.5" fill="var(--surface)" stroke="var(--s2)" stroke-width="2.4"/></g>')
        p.append(f'<text x="{R + 14}" y="{y + 4:.1f}" class="val">{E(r["folds_won"])}</text>')
    p.append("</svg>")
    return "".join(p)


def svg_monthly_book(key: str, ymax: float) -> str:
    b = P.port["books"][key]
    mo = sorted(b["monthly_20bps"])
    vals = [b["monthly_20bps"][m] for m in mo]
    W, H = 900, 178
    X0, X1, Y0, Y1 = 52, 888, 14, 138
    step = (X1 - X0) / len(mo)

    def Y(v: float) -> float:
        return lin(v, -ymax, ymax, Y1, Y0)

    sc, bk = key.split("|")
    title = (f"{NAME5.get(sc, sc)}, {bk.replace('_', ' ')}: net (20 bps) 20-day return minus the equal-weight "
             f"benchmark, by signal month")
    p = [svg_open(W, H, title)]
    for t in (-ymax, -ymax / 2, 0.0, ymax / 2, ymax):
        cls = "axisln" if t == 0 else "grid"
        p.append(f'<line x1="{X0}" y1="{Y(t):.1f}" x2="{X1}" y2="{Y(t):.1f}" class="{cls}"/>')
        p.append(f'<text x="{X0 - 6}" y="{Y(t) + 4:.1f}" class="ax ax-s" text-anchor="end">{pc(t, 0) if t else "0"}</text>')
    for i, (m, v) in enumerate(zip(mo, vals)):
        xc = X0 + step * (i + 0.5)
        tip = f"{m}: {pc(v, 2)} per 20 days vs the benchmark" + (" (holdout)" if m >= "2026-08" else "")
        path = vbar(xc, max(min(step - 3, 24), 3), Y(0), Y(max(min(v, ymax), -ymax)), 2)
        if path:
            p.append(f'<path d="{path}" fill="{"var(--pos)" if v >= 0 else "var(--neg)"}" data-tip="{E(tip)}"/>')
        if m.endswith("-01"):
            p.append(f'<text x="{xc:.1f}" y="{Y1 + 16}" class="ax ax-s" text-anchor="middle">{m[:4]}</text>')
    p.append(f'<text x="{X1}" y="{Y1 + 32}" class="ax ax-s" text-anchor="end">{b["months_positive"]} of '
             f'{b["n_months"]} months above 0</text>')
    p.append("</svg>")
    return "".join(p)


def svg_champion_mini(model: str, title: str, ymax: float) -> str:
    rows = [r for r in D.monthly if r["model"] == model]
    W, H = 300, 206
    X0, X1, Y0, Y1 = 42, 292, 22, 134

    def Y(v: float) -> float:
        return lin(v, -ymax, ymax, Y1, Y0)

    step = (X1 - X0) / len(rows)
    p = [svg_open(W, H, f"{title}: net active return vs the equal-weight universe and hit rate, per signal month")]
    for t in (-ymax, -ymax / 2, 0.0, ymax / 2, ymax):
        cls = "axisln" if t == 0 else "grid"
        p.append(f'<line x1="{X0}" y1="{Y(t):.1f}" x2="{X1}" y2="{Y(t):.1f}" class="{cls}"/>')
        p.append(f'<text x="{X0 - 5}" y="{Y(t) + 3.5:.1f}" class="ax ax-s" text-anchor="end">'
                 f'{pc(t, 1) if t else "0"}</text>')
    for i, r in enumerate(rows):
        v = float(r["net_active_vs_ew_20bps"])
        hit = float(r["hit_vs_ew_net20"])
        xc = X0 + step * (i + 0.5)
        adv = r["adversarial_month"] == "True"
        tip = (f"{r['signal_month']} ({r['segment']}{', adversarial' if adv else ''}): net active vs the "
               f"equal-weight universe {pc(v, 2)} per 20 days; beat it in {pu(hit)} of {r['n_tranches']} tranches")
        path = vbar(xc, min(22, step - 10), Y(0), Y(v), 3)
        if path:
            p.append(f'<path d="{path}" fill="{"var(--pos)" if v >= 0 else "var(--neg)"}" data-tip="{E(tip)}"/>')
        p.append(f'<text x="{xc:.1f}" y="{Y1 + 15}" class="ax ax-s" text-anchor="middle">'
                 f'{MONTHS[int(r["signal_month"][5:]) - 1][:3]}</text>')
        p.append(f'<text x="{xc:.1f}" y="{Y1 + 31}" class="val ax-s" text-anchor="middle">{pu(hit)}</text>')
        if adv:
            p.append(f'<text x="{xc:.1f}" y="{Y1 + 46}" class="ax ax-s" text-anchor="middle">adv.</text>')
    ho_i = [i for i, r in enumerate(rows) if r["segment"] == "holdout"]
    if ho_i:
        x = X0 + step * ho_i[0]
        p.append(f'<line x1="{x:.1f}" y1="{Y0 - 8}" x2="{x:.1f}" y2="{Y1 + 4}" class="mark"/>')
        p.append(f'<text x="{x + 4:.1f}" y="{Y0 - 9}" class="ax ax-s">holdout</text>')
    p.append(f'<text x="{X0 - 5}" y="{Y1 + 31}" class="ax ax-s" text-anchor="end">hit</text>')
    p.append("</svg>")
    return "".join(p)


def svg_flow() -> str:
    W, H = 920, 232
    p = [svg_open(W, H, "Daily and monthly jobs of the paper-trading product")]
    p.append('<defs><marker id="arw" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
             'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="arrowhead"/></marker></defs>')

    def box(x, y, w, h, t1, t2="", em=False):
        p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" class="{"fbox em" if em else "fbox"}"/>')
        ty = y + (h / 2 - 3 if t2 else h / 2 + 4)
        p.append(f'<text x="{x + w / 2:.1f}" y="{ty:.1f}" class="ftxt" text-anchor="middle">{E(t1)}</text>')
        if t2:
            p.append(f'<text x="{x + w / 2:.1f}" y="{y + h / 2 + 13:.1f}" class="ax ax-s" text-anchor="middle">{E(t2)}</text>')

    def arrow(x1, y1, x2, y2):
        p.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" class="farrow" marker-end="url(#arw)"/>')

    p.append('<text x="10" y="22" class="colh">Daily, after the end-of-day ingest</text>')
    daily = [("Ingest", "dup-day guard"), ("Feature build", f"{D.n_cand} end-of-day features"),
             ("Score", "ensemble, LightGBM, L2"), ("Rank list", "liquid top decile"),
             ("Paper portfolio", "20 tranches, 20 bps/side"), ("Dashboard", "alerts")]
    bw, gap, y = 134, 20, 34
    for i, (a, b) in enumerate(daily):
        x = 10 + i * (bw + gap)
        box(x, y, bw, 54, a, b, em=(a == "Paper portfolio"))
        if i:
            arrow(x - gap + 2, y + 27, x - 3, y + 27)
    p.append('<text x="10" y="136" class="colh">Monthly</text>')
    monthly = [("Retrain the members", "trailing 504 sessions"), ("Embargo and purge", "22 sessions, exit dates"),
               ("Champion vs challenger", "LightGBM reference"), ("Log the trial count", "paper book stays N = 1")]
    bw2, y2 = 196, 148
    for i, (a, b) in enumerate(monthly):
        x = 10 + i * (bw2 + 30)
        box(x, y2, bw2, 54, a, b)
        if i:
            arrow(x - 28, y2 + 27, x - 3, y2 + 27)
    p.append("</svg>")
    return "".join(p)


def minibar(v: float, lim: float = 0.10, label: str = "") -> str:
    W, H = 132, 16
    x0 = W / 2

    def X(t: float) -> float:
        return lin(max(min(t, lim), -lim), -lim, lim, 4, W - 4)

    lab = label or f"IC {sg(v)}"
    return (f'<svg class="mb" viewBox="0 0 {W} {H}" role="img" aria-label="{E(lab)}"><title>{E(lab)}</title>'
            f'<line x1="{x0}" y1="1" x2="{x0}" y2="{H - 1}" class="axisln"/>'
            f'<path d="{hbar(x0, X(v), H / 2, 10, 3)}" fill="{"var(--pos)" if v >= 0 else "var(--neg)"}"/></svg>')


# ===================================================================== sections
def gate_counts() -> dict:
    return {m: (sum(1 for v in g.values() if v["pass"]), len(g)) for m, g in D.gates.items()}


def pending_items() -> list[str]:
    out = []
    if P.port is None:
        out.append("paper portfolio")
    if P.boot is None:
        out.append("block bootstrap")
    if P.regimes is None:
        out.append("regime table")
    if ENS not in P.m:
        out.append("rank-ensemble challenger")
    return out


def join_words(xs: list[str]) -> str:
    return xs[0] if len(xs) == 1 else ", ".join(xs[:-1]) + " and " + xs[-1]


def sec_header() -> str:
    pend = pending_items()
    if pend:
        ribbon = (f'<div class="ribbon running"><span class="pulse"></span><span><b>Status:</b> 5-year model league '
                  f'complete; {E(join_words(pend))} running. Sections marked pending fill in when '
                  f'<code>ml/results/scale5y/</code> lands.</span></div>')
    else:
        ribbon = ('<div class="ribbon done"><span class="pulse"></span><span><b>Status: complete.</b> The 5-year '
                  'walk-forward, its paired block bootstrap, regime table, rank-ensemble challenger and paper '
                  'portfolio are all in (<code>ml/results/scale5y/SCALE5Y.md</code>).</span></div>')
    gc = gate_counts()
    gb = f" {MID} ".join(f"{NAME5[m]} <b>{k} of 5</b>" for m, (k, _) in gc.items())
    return f"""
<header class="hero">
  <div class="eyebrow">SuryaDhana {MID} NSE cash equities {MID} end-of-day bhavcopy {MID} research program</div>
  <h1>SuryaDhana Research Program</h1>
  <p class="sub">Final report {MID} {REPORT_DATE} {MID} Program lead: evaluation lead {MID} Scope: NSE cash equities,
  end-of-day bhavcopy data, 5 years (2021-10 to 2026-10). Every number on this page is read at build time from a
  committed JSON or CSV artifact; the narrative follows <code>ml/PROGRAM_REPORT.md</code>.</p>
  {ribbon}
  <div class="verdict">
    <div class="vhead">Verdict {MID} {REPORT_DATE}</div>
    <p>There is a real but small cross-sectional signal in NSE end-of-day data, and it is not yet a demonstrated
    tradable edge.</p>
    <div class="badges"><span class="badge">Recommendation <b>commit no capital</b></span>
    <span class="badge">Pre-registered gates passed: {gb}</span></div>
  </div>
</header>"""


def fold_span() -> str:
    return f"{mname(D.folds[0])} to {mname(D.folds[-1])}"


def sec_verdict() -> str:
    S = D.S5
    a51, nl, bm, c10 = S["all51"], S["nested_lgbm"], S["baseline_mom"], S["champion10"]
    FACTS.update({"n_folds": str(a51["n"]), "all51_cv": f(a51["cv"]), "all51_pct": pu(a51["ge"] / a51["n"]),
                  "all51_worst": f"{a51['worst']:.3f}", "all51_worst_month": mname(a51["worst_m"]),
                  "nested_cv": f(nl["cv"]), "mom_cv": f(bm["cv"]), "c10_cv": f(c10["cv"])})
    pairs = (P.boot or {}).get("pairs", {})
    ric = (P.summary or {}).get("rank_ic", {}).get("nested_lgbm")
    sig_extra = ""
    if P.boot:
        lo, hi = P.boot["models"]["nested_lgbm"]["cv_mean_ci95"]
        sig_extra = f"20-session block-bootstrap 95% interval [{f(lo)}, {f(hi)}]"
        FACTS["nested_ci"] = f"[{f(lo)}, {f(hi)}]"
    if ric:
        k, nm = ric["cv_months_ic_positive"].split("/")
        sig_extra += (("; " if sig_extra else "") + f"per-date rank IC {sg(ric['cv_mean_ic'])}, Newey-West t "
                      f"{ric['cv_nw_t_lag20']:.1f}, positive in {k} of {nm} months")
        FACTS["rank_ic_5y"] = sg(ric["cv_mean_ic"])
    sig_extra = f" ({sig_extra})" if sig_extra else ""
    p10 = pairs.get("all51 - champion10")
    p10_txt = (f" ({sg(-p10['cv_mean']['delta'], 4)} {ci(-p10['cv_mean']['ci95'][1], -p10['cv_mean']['ci95'][0])} "
               f"against all features)") if p10 else ""
    signal = (f"Over {a51['n']} monthly out-of-sample folds ({fold_span()}), a LightGBM classifier on all end-of-day "
              f"features ranks stocks by 20-session relative performance with mean AUC {f(a51['cv'])}, above 0.50 in "
              f"{pu(a51['ge'] / a51['n'])} of months, worst month {a51['worst']:.3f} ({mname(a51['worst_m'])}). The "
              f"honest nested-selection variant scores {f(nl['cv'])}{sig_extra}. A one-feature momentum rule scores "
              f"{f(bm['cv'])}. The pilot's 10-feature subset, chosen on 2026 data, scores {f(c10['cv'])} at 5 years"
              f"{p10_txt}: its selection did not transfer.")
    ex_ric = [e["oos_all"]["label_return"]["rank_ic_mean"] for k, e in D.lmod["econ"].items() if "_ex_" in k]
    pil = rng(f"{min(ex_ric):.2f}", f"{max(ex_ric):.2f}")
    FACTS["ic_pilot"] = pil
    size = (f"Per-date rank information coefficient (IC) is {pil} on the pilot"
            + (f" and {f(ric['cv_mean_ic'], 3)} over the five years" if ric else "")
            + f". That is the size the literature finds at the frontier: GKX's neural nets imply a forecast-return "
              f"correlation of about {MD_ONLY['gkx_corr']} on US data, Qlib's LightGBM reaches IC {MD_ONLY['qlib_ic']} "
              f"on CSI300.")
    if ric:
        FACTS["ic_5y"] = f(ric["cv_mean_ic"], 3)
    econ = econ_text()
    gates = gates_text()
    t1 = D.A["T1"]["null_cv"]
    FACTS.update({"perm_null": f"{t1['mean']:.3f} ± {t1['sd']:.3f}", "sessions": n(MD_ONLY["store_sessions"]),
                  "pilot_headline": f"{D.audit['claim_audited']['cv_auc_clean']:.3f}"})
    integ = (f"The pipeline is clean: labels and features recompute exactly from raw data, point-in-time universe "
             f"verified, label-permutation null {t1['mean']:.3f} ± {t1['sd']:.3f}, no duplicate sessions in "
             f"{n(MD_ONLY['store_sessions'])} trading days. The pilot's headline (CV AUC "
             f"{D.audit['claim_audited']['cv_auc_clean']:.3f}, “only model above chance”) was inflated by "
             f"feature selection on test months and has been corrected in <code>ml/MODEL_SELECTION.md</code>.")
    cards = [("Signal", signal, ["ml/results/scale5y/*.json"]),
             ("Size", size, ["ml/research/SOTA_FORECASTING.md", "ml/results/label_study/model_level.json"]),
             ("Economics", econ[0], econ[1]),
             ("Pre-registered promotion gates", gates, ["ml/SCALE_UP.md", "ml/results/scale5y/scale5y_summary.json"]),
             ("Integrity", integ, ["ml/results/audit/audit.json"])]
    vc = "".join(f'<div class="vc"><h3>{E(t)}</h3><p>{body}</p>{srcs(*s)}</div>' for t, body, s in cards)
    return f"""
<section id="verdict">
  <div class="sec-eyebrow">01 {MID} Verdict board</div>
  <h2>Verdict in one page</h2>
  <div class="vcards">{vc}</div>
  <h3 class="sub3">The three deliverables</h3>
  {deliverables()}
  <h3 class="sub3">Pre-registered promotion gates (<code>ml/SCALE_UP.md</code>)</h3>
  {gates_table()}
  {recommendation()}
</section>"""


def econ_text() -> tuple[str, list[str]]:
    if P.port is None:
        sm = D.sm["lgbm_fs_selected"]["top_decile"]["results"]["20bps"]
        da = sm["combined"]["daily_active"]
        txt = (f"On the six-month pilot, the champion's top decile beat the equal-weight universe by "
               f"{pc(da['ann_mean_daily'])} a year net of 20 bps per side, with an information ratio of "
               f"{da['sharpe']:.2f} and a 95% interval of [{sg(da['sharpe_ci95'][0], 1)}, {sg(da['sharpe_ci95'][1], 1)}]. "
               f"Its Deflated Sharpe Ratio was {D.ex['champion_top_decile_skill']['dsr']:.2f}. On the holdout it "
               f"trailed the universe. <b>Pending:</b> the 5-year paper portfolio (<code>portfolio_5y.json</code>) "
               f"decides whether this changes.")
        return txt, ["ml/results/strategy/strategy.json"]
    pt = P.port
    bk = pt["books"]
    nh = str(pt["dsr"]["N_headline"])
    ew = pt["benchmarks"]["ew_universe"]["combined"]["tranche"]["ann_return_252_h"]
    singles = [m for m in ["nested_lgbm", "all51", "champion10", "lr_l2", "nested_lr_l2"] if f"{m}|top_decile" in bk]
    single_ex = [bk[f"{m}|top_decile"]["segments"]["combined"]["20bps"]["excess_ann_vs_ew_252_20"] for m in singles]
    lg = [bk[f"{m}|top_decile"] for m in ("nested_lgbm", "all51")]
    lgx = sorted(-b["segments"]["combined"]["20bps"]["excess_ann_vs_ew_252_20"] * 100 for b in lg)
    lgm = sorted({b["months_positive"] for b in lg})
    e = bk[f"{ENS}|top_decile"]
    ec = e["segments"]["combined"]["20bps"]
    dsr_top = pt["dsr"]["books"][f"{ENS}|top_decile"]["skill"][nh]["dsr"]
    dsr_liq = pt["dsr"]["books"][f"{ENS}|{PAPER_BASKET}"]["skill"][nh]["dsr"]
    months = sorted(pt["direction_by_month"])
    every_year = all(v > 0 for v in e["by_year_20d"].values())
    FACTS.update({"ew_ann": pc(ew), "lgbm_trail": rng(f"{lgx[0]:.1f}", f"{lgx[-1]:.1f}"),
                  "ens_excess": pc(ec["excess_ann_vs_ew_252_20"]), "ens_ir": f"{ec['ir']:.2f}",
                  "ens_ir_ci": f"[{ec['ir_ci95'][0]:.2f}, {ec['ir_ci95'][1]:.2f}]", "dsr_top": f"{dsr_top:.2f}",
                  "dsr_liq": f"{dsr_liq:.2f}", "N": nh, "n_signal_dates": str(pt["n_signal_dates"])})
    txt = (f"Over {n(pt['n_signal_dates'])} out-of-sample signal dates ({mname(months[0])} to {mname(months[-1])}), net "
           f"of 20 bps per side, <b>no single machine-learned model's top decile beats simply holding the universe "
           f"equally weighted</b> ({pc(ew)} a year)" if all(x < 0 for x in single_ex) else
           f"Over {n(pt['n_signal_dates'])} out-of-sample signal dates, net of 20 bps per side, against the "
           f"equal-weight universe ({pc(ew)} a year)")
    txt += (f": the LightGBM books trail it by {rng(f'{lgx[0]:.1f}', f'{lgx[-1]:.1f}')} points a year and beat it in "
            f"{rng(str(lgm[0]), str(lgm[-1]))} of {lg[0]['n_months']} months. The pre-registered three-model rank "
            f"ensemble is the one exception: {pc(ec['excess_ann_vs_ew_252_20'])} a year over the universe, information "
            f"ratio {ec['ir']:.2f} with a 95% interval of [{ec['ir_ci95'][0]:.2f}, {ec['ir_ci95'][1]:.2f}]"
            + (", positive in every calendar year" if every_year else "")
            + f". Its Deflated Sharpe Ratio at an honestly counted {nh} trials is {dsr_top:.2f} ({dsr_liq:.2f} for the "
              f"liquid book pre-registered as the paper portfolio)"
            + (", so it does not survive multiple-testing adjustment." if max(dsr_top, dsr_liq) < 0.95 else "."))
    return txt, ["ml/results/scale5y/portfolio_5y.json", "ml/results/scale5y/SCALE5Y.md"]


def gates_text() -> str:
    G = D.gates
    gc = gate_counts()
    order = [m for m in GATE_MODELS if m in G]
    lab = {"nested_lgbm": "LightGBM with nested selection", "all51": "LightGBM on all features", ENS: "the rank ensemble"}
    head = ", ".join(f"{lab[m]} passes <b>{gc[m][0]} of 5</b>" if i == 0 else f"{lab[m]} <b>{gc[m][0]} of 5</b>"
                     for i, m in enumerate(order)) + "."
    FACTS["gates_pass"] = " / ".join(f"{gc[m][0]} of 5" for m in order)

    def vals(k):
        return ", ".join(G[m][k]["num"].split(" (")[0] if k == "2" else G[m][k]["num"] for m in order if k in G[m])

    parts = [head]
    if all("1" in G[m] for m in order):
        all_fail = all(not G[m]["1"]["pass"] for m in order)
        parts.append(f"Gate 1 (beats L2 logistic on mean CV AUC with an interval excluding zero) "
                     f"{'fails for all three' if all_fail else 'results: ' + vals('1')}: the logistic model's mean is "
                     f"higher (delta {G['nested_lgbm']['1']['num']} for nested LightGBM).")
    g2 = [pu(D.S5[m]["ge"] / D.S5[m]["n"]) for m in order]
    passers2 = [m for m in order if G[m]["2"]["pass"]]
    note2 = ""
    if passers2 == [ENS] and gc[ENS][0] == 1:
        note2 = " (the ensemble's one pass)"
    parts.append(f"Gate 2 (fold floor ≥ 0.50 in ≥ 90% of months): {', '.join(g2)}{note2}.")
    FACTS["gate2"] = ", ".join(g2)
    if all("3" in G[m] for m in order):
        g3 = [G[m]["3"]["num"].split("= ")[-1] for m in order]
        parts.append(f"Gate 3 (top decile beats the equal-weight universe in ≥ 75% of months net of 20 bps): "
                     f"{', '.join(g3)}.")
        FACTS["gate3"] = ", ".join(g3)
    else:
        parts.append("Gate 3 (top decile beats the equal-weight universe in ≥ 75% of months net of 20 bps) is "
                     "<b>pending</b> (<code>portfolio_5y.json</code>).")
    parts.append(f"Gate 4 (selected-feature overlap ≥ 7 of 10 across yearly re-selections): "
                 f"{', '.join(str(x) for x in D.top10_overlap)}.")
    FACTS["gate4"] = ", ".join(str(x) for x in D.top10_overlap)
    if all("5" in G[m] for m in order):
        g5 = [G[m]["5"]["num"] for m in order]
        parts.append(f"Gate 5 (DSR ≥ 0.95 on the liquid top decile, N = {P.port['dsr']['N_headline']}): "
                     f"{', '.join(g5)}.")
        FACTS["gate5"] = ", ".join(g5)
    else:
        parts.append("Gate 5 (DSR ≥ 0.95 for the paper portfolio) is <b>pending</b> (<code>portfolio_5y.json</code>).")
    decided_fail = all(any(not v["pass"] for v in G[m].values()) for m in order)
    if decided_fail:
        parts.append("<b>The pre-registered criteria for committing capital are not met by any model.</b>")
    return " ".join(parts)


def deliverables() -> str:
    nl = D.S5["nested_lgbm"]
    pr = (P.boot or {}).get("pairs", {}).get("nested_lgbm - all51")
    d_txt = f" ({sg(pr['cv_mean']['delta'], 4)} {ci(*pr['cv_mean']['ci95'])})" if pr else ""
    surv = D.suff["verdict"]["features_new_information_bh"]
    lgb = D.m5["nested_lgbm"]["params"]["lgbm"]
    lrp = D.m5["nested_lr_l2"]["params"]["lr"]
    FACTS.update({"n_cand": str(D.n_cand), "trees": str(lgb["n_estimators"]),
                  "window": str(D.m5["all51"]["params"]["train_sessions"]), "embargo": str(D.splits5["embargo_sessions"]),
                  "lr_C": f"{lrp['C']:g}"})
    ens_note = "" if ENS in P.m else " (<b>pending</b> at 5 years)"
    rows = [
        ("Feature set",
         f"The {D.n_cand} end-of-day candidates: the 50 base features plus <code>{surv[0]}</code> and "
         f"<code>{surv[1]}</code>, the two that honest yearly re-selection keeps picking. The single-model reference "
         f"feeds all {D.n_cand} to LightGBM without hand selection; the ensemble as tested re-selects {nl['feats']} of "
         f"them each year, which buys nothing on AUC{d_txt}. The pilot's 10-feature subset is retired. No further "
         f"feature engineering on bhavcopy-derived inputs; the next gains require external data (corporate actions "
         f"first).", '<a href="#features">Features</a>, <a href="#five-year">Five-year walk-forward</a>'),
        ("Label set",
         "Primary <code>label_beat_mkt_20d</code> (20-session next-open excess vs the cross-sectional median, "
         "clean-masked). Economics judged against the equal-weight universe <b>mean</b>, rank-IC and net spread "
         "reported beside AUC, ETFs excluded, 40-day label carried as a candidate, <code>up_5d</code> demoted to a "
         "negative control.", '<a href="#labels">Labels</a>'),
        ("Model",
         f"For paper trading only: the pre-registered rank-average ensemble (LightGBM champion config + LambdaRank + "
         f"CatBoost with fixed tree budgets, per-date rank average), frozen as one strategy{ens_note}. Single-model "
         f"reference: LightGBM, fixed {lgb['n_estimators']} trees, all features, rolling "
         f"{D.m5['all51']['params']['train_sessions']}-session window, monthly retrain, "
         f"{D.splits5['embargo_sessions']}-session embargo, exit-date purge. L2 logistic (C = {lrp['C']:g}) kept as the "
         f"drift monitor, not a scorer. Deep sequence models, transformers, DLinear, time-series foundation models and "
         f"reinforcement learning are dropped with evidence. <b>Nothing is promoted to capital.</b>",
         '<a href="#models">Models</a>, <a href="#strategy">Strategy</a>'),
    ]
    return '<div class="deliv">' + "".join(
        f'<div class="dcard"><div class="dk">{E(k)}</div><p>{v}</p><p class="dev">Evidence: {ev}</p></div>'
        for k, v, ev in rows) + "</div>"


GATE_NAMES = {
    "1": ("Beats L2 logistic on CV mean, bootstrap interval excluding zero", "Delta vs <code>lr_l2</code> [95% CI]"),
    "2": ("Monthly fold AUC ≥ 0.50 in ≥ 90% of months", "Share of 43 folds"),
    "3": ("Top-decile book beats the equal-weight universe in ≥ 75% of months, net of 20 bps",
          "Months beating the universe"),
    "4": ("Selected-feature overlap ≥ 7 of 10 across yearly re-selections", "Consecutive-year top-10 overlap"),
    "5": ("Deflated Sharpe ≥ 0.95 for the paper book (liquid top decile)", "DSR"),
}


def gates_table() -> str:
    G = D.gates
    order = [m for m in GATE_MODELS if m in G]
    head = ["Gate", "Pre-registered criterion"] + [f"{E(NAME5[m])}" for m in order]
    rows = []
    for k in ("1", "2", "3", "4", "5"):
        name, unit = GATE_NAMES[k]
        if k == "5" and P.port:
            name = name + f", N = {P.port['dsr']['N_headline']}"
        cells = [f"<b>{k}</b>", f'{name}<div class="dim2 small">{unit}</div>']
        for m in order:
            g = G[m].get(k)
            if g is None:
                cells.append(f'{chip("pending")}<div class="small dim2">needs <code>portfolio_5y.json</code></div>')
            else:
                note = ""
                if k == "4" and m == "all51":
                    note = '<div class="small dim2">all51 selects nothing; scored on the same yearly re-selection</div>'
                cells.append(f'<div class="gnum">{g["num"]}</div>{chip("pass" if g["pass"] else "fail")}{note}')
        rows.append(cells)
    gc = gate_counts()
    rows.append(["", "<b>Gates passed</b>"] + [f"<b>{gc[m][0]} of 5</b>" + (
        f' <span class="dim2">({5 - gc[m][1]} pending)</span>' if gc[m][1] < 5 else "") for m in order])
    tbl = table(head, rows, cls="gates", wrap=tuple(range(len(head))))
    note = ("Scored exactly as <code>ml/scale5y_report.py</code> scores them (gate 4 uses the consecutive-year "
            "top-10 overlap; the chosen sets themselves share 2 to 3 features). Gate 5 is scored on the liquid "
            "top decile pre-registered as the paper book.")
    return f'<div class="card">{tbl}<p class="cap">{note}</p></div>'


def recommendation() -> str:
    if P.port is None:
        body = ("Commit no capital. Run the model as a nightly paper portfolio (liquid-tercile top decile, long-only, "
                "equal-weight benchmark, 20 bps per side) with the monitoring below, and put the next unit of effort "
                "into data (corporate actions, sector classification, F&amp;O membership, fundamentals) rather than "
                "into models.")
    else:
        b = P.port["books"][f"{ENS}|{PAPER_BASKET}"]["segments"]["combined"]["20bps"]
        nh = str(P.port["dsr"]["N_headline"])
        trl = P.port["dsr"]["books"][f"{ENS}|{PAPER_BASKET}"]["skill"][nh]["min_track_record_periods_psr95_vs_0"]
        FACTS.update({"paper_ir": f"{b['ir']:.2f}", "paper_years": str(round(trl / 252))})
        body = (f"Commit no capital. Paper-trade the ensemble's liquid-tercile top decile as one frozen, pre-registered "
                f"strategy from November 2026 (a fresh test with N = 1; at its observed information ratio of "
                f"{b['ir']:.2f} it needs about {round(trl / 252)} years of track record to reach a 95% probabilistic "
                f"Sharpe), with the monitoring in <a href=\"#product\">Product and monitoring</a>. Put the next research "
                f"effort into volatility-neutral book construction and into data (corporate actions, sector "
                f"classification, F&amp;O membership, fundamentals) rather than into new model families.")
    return f'<div class="rec"><div class="vhead">Recommendation</div><p>{body}</p></div>'


def sec_status() -> str:
    S = D.S5
    lg3 = [S[m]["cv"] for m in ("all51", "nested_lgbm", "champion10")]
    pct2 = sorted(S[m]["ge"] / S[m]["n"] for m in ("all51", "nested_lgbm"))
    working = [
        f"Data pipeline: 5 years ingested, resilient to archive quirks, no duplicate sessions, resume-safe, "
        f"{MD_ONLY['ingest_tests']} tests.",
        "Evaluation harness: purged walk-forward, nested selection, exit-date purging, block bootstraps, "
        "pre-registered pass marks, one result schema that every team used.",
        f"The signal: delivery and long momentum, AUC {rng(f'{min(lg3):.2f}', f'{max(lg3):.2f}')} over {S['all51']['n']} "
        f"months, above 0.50 in {rng(pu(pct2[0]), pu(pct2[-1]))} of months, consistent with published frontier numbers.",
        "Model choice: LightGBM with fixed trees on all features; it is the most stable thing in the league and nothing "
        "from deep learning, ranking losses or attention beats it.",
        "Honesty: the one inflated claim was found by the program's own red team and corrected before any capital "
        "decision.",
    ]
    notw = []
    unknown = []
    if P.port is not None:
        pt = P.port
        nh = str(pt["dsr"]["N_headline"])
        ec = pt["books"][f"{ENS}|top_decile"]
        ex = ec["segments"]["combined"]["20bps"]
        d_top = pt["dsr"]["books"][f"{ENS}|top_decile"]["skill"][nh]["dsr"]
        d_liq = pt["dsr"]["books"][f"{ENS}|{PAPER_BASKET}"]["skill"][nh]["dsr"]
        every_year = all(v > 0 for v in ec["by_year_20d"].values())
        clear = ex["ir_ci95"][0] > 0
        working.append(f"The ensemble's five-year economics: {pc(ex['excess_ann_vs_ew_252_20'])} a year over the universe"
                       + (" with an interval clear of zero" if clear else "")
                       + (", positive in every year" if every_year else "")
                       + "; the only book in the program with that property.")
        notw.append(f"Tradable edge: not demonstrated. No single model's long-only book beats the equal-weight universe "
                    f"net of costs over five years; the ensemble's does, with DSR {d_top:.2f} ({d_liq:.2f} for the paper "
                    f"book) at {nh} trials.")
        unknown.append(f"Whether the ensemble's {pc(ex['excess_ann_vs_ew_252_20'], 0)} a year is skill or a favourable "
                       f"factor mix over {ec['n_months']} months of one, mostly rising, market.")
    else:
        notw.append("Tradable edge: not demonstrated on the pilot; the 5-year paper portfolio is pending.")
    gc = gate_counts()
    notw.append("Pre-registered gates: " + ", ".join(
        f"{lab} {gc[m][0]} of 5" for m, lab in (("nested_lgbm", "nested LightGBM"), ("all51", "all-features LightGBM"),
                                                (ENS, "ensemble")) if m in gc) + ".")
    lr_pairs = [v for k, v in ((P.boot or {}).get("pairs", {})).items() if k.endswith(" - lr_l2")]
    if lr_pairs:
        all0 = all(not v["cv_mean"]["ci_excludes_0"] for v in lr_pairs)
        notw.append("Machine learning over a linear model: not shown; the logistic model's mean AUC is higher"
                    + (" and every paired interval includes zero." if all0 else "."))
    notw += [
        "Feature selection: unstable year to year; buys nothing on AUC.",
        "Extreme-decile economics: the top decile holds a lottery tail in down markets; book construction must change "
        "(liquidity filter, equal-weight benchmark, possibly top quintile or rank-weighted rather than top decile).",
        "The linear model as a scorer: highest mean, worst tails; demoted to drift monitor.",
        "Deep learning, transformers, foundation models, reinforcement learning: nothing beats trees here; stopped.",
    ]
    pend = pending_items()
    if pend:
        pending = [f"5-year {x} (<code>ml/results/scale5y/</code>)" for x in pend]
    else:
        pending = [f"Nothing. Every run in the program is complete and committed. (The label study closed with a clean "
                   f"end-to-end rerun that reproduced all {D.n_label_json} of its JSON outputs with zero numeric "
                   f"differences.)"]
    unknown += [
        "Whether delivery % is a durable signal or a 2025 artefact: its IC fell by two-thirds after March 2026; it "
        "needs the 5-year by-year test and, ideally, independent literature that does not exist.",
        "Anything that needs several market cycles: market-state conditioning, seasonality, sector rotation.",
        "Realistic costs in the illiquid tail: name-level spread and impact are not modelled.",
    ]

    def col(cls, title, items):
        return (f'<div class="col {cls}"><h3>{title}</h3><ul>' + "".join(f"<li>{x}</li>" for x in items)
                + "</ul></div>")

    return f"""
<section id="status">
  <div class="sec-eyebrow">02 {MID} Status board</div>
  <h2>What works, what does not, what is unknown</h2>
  <div class="board">{col("ok", "Working", working)}{col("not", "Not working", notw)}
  {col("pend", "Pending", pending)}{col("unk", "Unknown (cannot be decided with this data)", unknown)}</div>
</section>"""


def sec_data() -> str:
    mp, m5 = D.man_pilot, D.man5
    sp, s5 = D.splits_pilot, D.splits5
    u = m5["universe"]
    sby = MD_ONLY["sessions_by_year"]
    share = D.hd["share_of_sample"]
    ph = len(D.hd["phantom_days"])
    tot = int(share.split(" of ")[1].split()[0])
    t13 = D.A["T13"]["totals"]
    masked = (t13["masked_extreme_move"] + t13["masked_suspension_only"]) / t13["test_rows_in_window"]
    split20 = D.lvar["variants"]["no_20d"]["mask_breakdown_labelable"]["split_move_gt_22pct"]
    mask_rng = rng(pu(min(masked, split20), 1), pu(max(masked, split20), 1))
    flag = D.dp["integrity"]["pct_rows_flag_split_20d"]
    etf = D.lvar["meta"]["etf_sensitivity"]
    rows = [[f"Pilot (<code>ml/data/</code>)", n(mp["rows"]), n(mp["tickers"]), f"{mp['date_min']} to {mp['date_max']}",
             f"{len(sp['folds'])} monthly ({MONTHS[int(sp['folds'][0]['name'][5:]) - 1][:3]} to "
             f"{MONTHS[int(sp['folds'][-1]['name'][5:]) - 1][:3]} {sp['folds'][-1]['name'][:4]})",
             f"{sp['holdout']['test_start']} to {sp['holdout']['test_end']}"],
            [f"5-year (<code>ml/data_5y/</code>)", n(m5["rows"]), n(m5["tickers"]), f"{m5['date_min']} to {m5['date_max']}",
             f"{len(s5['folds'])} monthly ({s5['folds'][0]['name']} to {s5['folds'][-1]['name']})",
             f"{s5['holdout']['test_start']} to {s5['holdout']['test_end']}"]]
    tiles = [
        (f"{ph}", "phantom days found and fixed",
         f"Holiday-echo files on {ph} NSE holidays in 2026 ({pu(ph / tot, 1)} of pilot sessions)."),
        (f"0 of {n(MD_ONLY['store_sessions'])}", "duplicate sessions",
         f"Full-history scan; largest repeat share {MD_ONLY['echo_max_share']} ({MD_ONLY['echo_max_date']})."),
        ("missing", "corporate-actions feed",
         f"Prices unadjusted; the clean mask drops {mask_rng} of labelled rows, <code>flag_split_20d</code> fires on "
         f"{flag:.2f}% of rows."),
        (f"{etf['etf_tickers']}", "ETFs in the stock universe", f"{pu(etf['etf_row_share'], 1)} of rows; excluded from "
                                                                f"the label specification."),
    ]
    tl = "".join(f'<div class="tile"><div class="v">{v}</div><div class="k">{k}</div><div class="d">{d}</div></div>'
                 for v, k, d in tiles)
    years = ", ".join(str(sby[y]) for y in sorted(sby))
    return f"""
<section id="data">
  <div class="sec-eyebrow">03 {MID} Data</div>
  <h2>Data</h2>
  <p><b>Store.</b> <code>nse_market.duckdb</code> holds {n(MD_ONLY['store_rows'])} raw bhavcopy rows over
  {n(MD_ONLY['store_sessions'])} sessions from {MD_ONLY['store_first']} to {MD_ONLY['store_last']}
  ({n(MD_ONLY['store_tickers'])} ticker codes across all series; {n(MD_ONLY['store_feature_rows'])} feature rows).
  Sessions per calendar year: {sby['2021']} (Q4 2021), {", ".join(str(sby[y]) for y in sorted(sby)[1:-1])},
  {sby['2026']} (to 16 October 2026), consistent with the NSE calendar.</p>
  <div class="card"><div class="scroll"><div class="wide-svg">{svg_coverage()}</div></div>
  <p class="cap">Sessions per year ({years}) come from the lead's full-history scan of the store
  (<code>ml/PROGRAM_REPORT.md</code> §3); dataset spans, folds and holdouts from <code>ml/data/manifest.json</code>,
  <code>ml/data/splits.json</code>, <code>manifest_5y.json</code> and <code>splits_5y.json</code>. Ticks under the
  pilot bar mark the {ph} holiday-echo days that were removed.</p></div>
  <h3 class="sub3">Modelling datasets</h3>
  <div class="card">{table(["Dataset", "Rows", "Tickers", "Dates", "Folds", "Holdout"], rows, cls="plain")}
  <p class="cap">Universe filter is point-in-time: close ≥ ₹{u['min_price']:g} and trailing 20-day median
  turnover ≥ ₹{u['min_median_turnover_20d'] / 1e7:g} crore. The first year of history is feature warm-up.</p></div>
  <div class="tiles">{tl}</div>
  <h3 class="sub3">Quality</h3>
  <ul class="lims">
    <li><b>Holiday echo (found and fixed).</b> The archive mirror re-served the prior session's file on {ph} NSE holidays
    in 2026 ({pu(ph / tot, 1)} of pilot sessions). The ingest now carries a holiday calendar and a duplicate-day
    fingerprint guard; the pilot was rebuilt and re-validated with the model ranking unchanged.</li>
    <li><b>Full-history scan.</b> Across all {n(MD_ONLY['store_sessions'])} sessions, the largest share of tickers
    repeating the previous day's close and volume is {MD_ONLY['echo_max_share']} ({MD_ONLY['echo_max_date']}), the
    normal footprint of illiquid names. No echo exists in the 5-year store.</li>
    <li><b>Ingest resilience.</b> The 5-year backfill exposed an archive day served as an Excel workbook under a
    <code>.csv</code> name; the reader now detects the body type by magic bytes, falls back to Latin-1, rejects HTML
    bodies and skips a bad day instead of aborting. {MD_ONLY['ingest_tests']} ingest tests pass.</li>
    <li><b>Known gap: corporate actions.</b> Prices are unadjusted. The <code>y_clean_20d</code> mask drops {mask_rng}
    of labelled rows around splits and suspensions, and <code>flag_split_20d</code> fires on {flag:.2f}% of rows. Over 5
    years this is the single largest data-integrity risk and the first external feed to add
    (<a href="#recs">Recommendations</a>).</li>
    <li><b>Known gap: ETFs.</b> {etf['etf_tickers']} ETFs ({pu(etf['etf_row_share'], 1)} of rows) sit inside the
    “stock” universe. They carry higher delivery share and higher mean excess return. The label study
    recommends excluding them (<a href="#labels">Labels</a>).</li>
  </ul>
</section>"""


def sec_labels() -> str:
    L = D.lsum["labels"]
    runs, econ = D.lmod["runs"], D.lmod["econ"]
    meta = D.lsum["meta"]
    sf = meta["signflip_null"]
    hz = D.lvar["meta"]["horizons"]
    q1 = [L[f"ex_{e}_1d"]["n_q_lt_0.05"] for e in ("cc", "no")]
    q20 = [L[f"ex_{e}_20d"]["n_q_lt_0.05"] for e in ("cc", "no")]
    q40nw = [L[f"ex_{e}_40d"]["n_q_nw_lt_0.05"] for e in ("cc", "no")]
    comp = {(e, h): L[f"ex_{e}_{h}d"]["composite"]["fdr_q10"] for e in ("cc", "no") for h in hz}
    is_m = comp[("no", 20)]["is_months"]
    ic12 = [comp[(e, h)]["oos_ic"] for e in ("cc", "no") for h in (1, 2)]
    t12 = [comp[(e, h)]["oos_t"] for e in ("cc", "no") for h in (1, 2)]
    ic5 = [comp[(e, 5)]["oos_ic"] for e in ("cc", "no")]
    t5 = [comp[(e, 5)]["oos_t"] for e in ("cc", "no")]
    deliv = {"deliv_pct", "deliv_pct_sma_20", "deliv_pct_z_20", "cs_rank_deliv_z"}
    deliv_every = all(any(t["feature"] in deliv for t in L[f"ex_{e}_{h}d"]["top5"]) for e in ("cc", "no") for h in hz)
    etf20 = max(t["t"] for t in L["ex_no_20d"]["ex_etf"]["top5"] if t["feature"] in deliv)
    top40 = max((t for e in ("cc", "no") for t in L[f"ex_{e}_40d"]["top5"]), key=lambda t: abs(t["mean_ic"]))
    ex_runs = {r["h"]: (k, r) for k, r in runs.items() if "_ex_" in k}
    raw_runs = {r["h"]: (k, r) for k, r in runs.items() if "_raw_" in k}
    ric = {h: econ[k]["oos_all"]["label_return"]["rank_ic_mean"] for h, (k, _) in ex_runs.items()}
    ric_3_20 = [ric[h] for h in ric if 3 <= h <= 20]
    cv_ex = [r["cv_auc_mean"] for _, r in ex_runs.values()]
    cv_raw = max(r["cv_auc_mean"] for _, r in raw_runs.values())
    br = [v for _, r in raw_runs.values() for v in r["fold_base_rates"].values()]
    ho_raw = sorted(r["holdout_auc"] for _, r in raw_runs.values())
    ratio = [econ[k]["oos_all"]["label_return"]["rank_ic_mean"] / ric[h] for h, (k, _) in raw_runs.items()]
    e20 = econ[ex_runs[20][0]]["oos_all"]["label_return"]
    short = [econ[ex_runs[h][0]]["oos_all"]["label_return"] for h in ex_runs if h <= 5]
    loss_lo = min(abs(x["ls_net_annual_measured_turnover"]) for x in short)
    loss_hi = max(abs(x["ls_net_annual_full_turnover"]) for x in short)
    long_neg = all(econ[k]["oos_all"]["label_return"]["long_net_annual_measured_turnover"] < 0 for k, _ in ex_runs.values())
    ew20 = D.strat["benchmarks"]["ew_universe"]["combined"]["tranche"]["excess_vs_median_gross"]
    up5 = D.lvar["variants"]["cc_5d"]["targets"]["raw"]
    raw5 = raw_runs[5][1]
    raw5_ric = econ[raw_runs[5][0]]["oos_all"]["label_return"]["rank_ic_mean"]
    poison = D.lvar["validation_vs_dataset"]["cc_5d_raw_vs_fwd_ret_5d"]["rows_dataset_has_but_masked_here"]
    etf = D.lvar["meta"]["etf_sensitivity"]
    n_months = len(e20["rank_ic_monthly"])
    panels = []
    for kind in ("q", "auc", "be"):
        title, svg = svg_horizon_panel(kind)
        panels.append(f'<figure class="hp"><figcaption>{E(title)}</figcaption>{svg}</figure>')
    # label table
    trs = []
    for h in hz:
        for e in ("cc", "no"):
            v = f"{e}_{h}d"
            var = D.lvar["variants"][v]
            raw, ex = var["targets"]["raw"], var["targets"]["ex"]
            lab, vs = L[f"ex_{v}"], L[f"vs_{v}"]
            c = lab["composite"]["fdr_q10"]
            nw = lab["n_q_nw_lt_0.05"]
            prim = v == "no_20d"
            trs.append([("<b>" + v + "</b> (primary)") if prim else v, pu(var["coverage_labelable_dates"], 2),
                        f"{raw['base_rate_month_min']:.2f} to {raw['base_rate_month_max']:.2f}", pu(ex["xs_std_mean"], 1),
                        f"{raw['per_date_mean_lag1_autocorr']:.2f}",
                        f"{lab['n_q_lt_0.05']} ({'<b>0</b>' if nw == 0 else nw})", str(vs["n_q_lt_0.05"]),
                        f"{c['is_ic']:.3f} → {f(c['oos_ic'], 3)} ({f(c['oos_t'], 1)})"])
    ltab = table(["Label", "Coverage", "Raw > 0 base rate by month", "Cross-sectional sd (excess)",
                  "Lag-1 autocorrelation of the market mean", "Features q &lt; 0.05 (NW-adjusted)",
                  "q &lt; 0.05, vol-scaled", "Composite IC: in-sample (8 months) → OOS (t)"], trs, cls="plain small-t")
    return f"""
<section id="labels">
  <div class="sec-eyebrow">04 {MID} Labels</div>
  <h2>Labels: which target to model</h2>
  <p class="lede">Source: <code>ml/results/label_study/LABEL_STUDY.md</code> ({len(L)} label variants:
  {", ".join(str(h) for h in hz[:-1])} and {hz[-1]} sessions; close-to-close and next-open entry; raw, excess, rank and
  vol-scaled targets; {len(D.lvar['meta']['base_features'])} features; {n(meta['bh_family_size'])} testable
  hypotheses).</p>
  <div class="card"><div class="hpanels">{"".join(panels)}</div>
  <p class="cap">Left: predictability by horizon from <code>label_summary.json</code> (Benjamini-Hochberg q &lt; 0.05
  with Newey-West standard errors; without the overlap correction the 40-session counts are {L['ex_cc_40d']['n_q_lt_0.05']}
  and {L['ex_no_40d']['n_q_lt_0.05']}). Middle and right: the champion LightGBM retrained on each label
  (<code>model_level.json</code>); the excess label was run at 2 to 20 sessions and the raw label at 5 and 20.</p></div>
  <h3 class="sub3">Findings</h3>
  <ol class="lims">
    <li><b>Predictability falls with horizon.</b> {rng(str(min(q1)), str(max(q1)))} of 40 features pass Benjamini-Hochberg
    q &lt; 0.05 at 1 day, {rng(str(min(q20)), str(max(q20)))} at 20 days, {"none" if max(q40nw) == 0 else max(q40nw)} at
    40 days once overlapping windows are corrected for. Selecting features on the first {is_m} months and scoring the
    rest gives an out-of-sample IC of {sg(sum(ic12) / len(ic12), 2)} at 1 to 2 days (t {f(min(t12), 1)} to
    {f(max(t12), 1)}), {sg(sum(ic5) / len(ic5), 2)} at 5 days (t ≈ {round(sum(t5) / len(t5))}), and about zero from
    10 to 20 days, because of the March-2026 regime break. Delivery is the one pillar that ranks in the top five at
    every horizon and for both entry conventions{"" if deliv_every else " (not at every horizon in the JSON)"} (t
    {etf20:.1f} at 20 days even with ETFs excluded); at 40 days the single best feature is
    <code>{top40['feature']}</code> (IC {top40['mean_ic']:.2f}).</li>
    <li><b>The excess label is the most predictable by a model, at any horizon.</b> Model rank-IC is flat at about
    {sum(ric_3_20) / len(ric_3_20):.3f} from 3 to 20 days; CV AUC sits between {min(cv_ex):.3f} and {max(cv_ex):.3f}
    at every horizon. The raw &gt; 0 labels post the highest CV AUC ({cv_raw:.3f}) but that is market timing, not stock
    selection: their fold base rates swing from {min(br):.2f} to {max(br):.2f}, their holdout AUC in a down market is
    {ho_raw[0]:.2f} to {ho_raw[-1]:.2f} and their cross-sectional rank-IC is a quarter to two-fifths of the excess
    label's ({min(ratio):.2f} to {max(ratio):.2f} of it).</li>
    <li><b>Only the 20-day label clears realistic costs.</b> Its long-short decile spread breaks even at
    {e20['breakeven_cost_per_side_bps_full_turnover']:.1f} bps per side at 100% turnover and nets
    {pc(e20['ls_net_annual_full_turnover'])} to {pc(e20['ls_net_annual_measured_turnover'])} a year (at 100% and at
    measured turnover), with a gross spread t of only {e20['decile_spread_t_nw']:.2f} over {n_months} out-of-sample
    months; horizons of 5 days or less lose {loss_lo * 100:.0f}% to {loss_hi * 100:.0f}% a year after costs.
    {"Long-only, every horizon is negative after costs" if long_neg else "Long-only results are mixed after costs"}
    against the equal-weight universe mean, because the top decile holds a lottery tail that does worse than deciles 7
    to 9.</li>
    <li><b>The universe median is a soft benchmark.</b> Right skew puts the equal-weight universe's own “excess
    over the median” at {MD_ONLY['univ_excess_range']} per 20 days (about {ew20 * 252 / 20 * 100:.0f}% a year in
    the strategy study). Measured against the universe mean, the pilot champion's top-decile excess was positive in
    {MD_ONLY['champ_vs_mean_windows']} windows, not 5 of 5.</li>
    <li><b>Multiple testing.</b> {n(meta['bh_family_size'])} hypotheses; {sf['observed']['p_lt_0.05']} nominal
    p &lt; 0.05 and {sf['observed']['q_lt_0.05']} BH discoveries observed. Under a dependence-preserving month-sign-flip
    null the 95th percentile of nominal hits is {sf['null_p95']['p_lt_0.05']:.0f}, so the grid is significant at about
    p = {sf['p_value_obs_q05']:.3f}. But the evidence is effectively {sf['n_months']} monthly draws, and the selection
    test shows it does not carry forward beyond about 5 days.</li>
  </ol>
  <h3 class="sub3">Label table (excess family; coverage over labelable dates)</h3>
  <div class="card">{ltab}<p class="cap">From <code>label_variants.json</code> and <code>label_summary.json</code>. The
  excess &gt; 0 base rate is 0.50 in every month by construction; the in-sample to out-of-sample drop shows the
  selection bias directly.</p></div>
  <div class="panel decision"><h3>Decision</h3>
  <p>Keep <code>label_beat_mkt_20d</code> (20-session next-open excess vs the cross-sectional median, clean-masked) as
  the primary label. Shorter labels are statistically easier but costs dominate them; next-open entry is realistic
  and costs nothing in predictability; raw, excess and rank targets give identical per-date ICs so the cross-sectional
  target choice does not matter; vol-scaling adds nothing. Four changes:</p>
  <ul class="lims">
    <li>(a) judge economics against the equal-weight universe mean, not the median;</li>
    <li>(b) report rank-IC and net spread next to AUC in every league table;</li>
    <li>(c) carry a {hz[-1]}-day label as a candidate horizon for the 5-year run (needs an embargo of at least
    {hz[-1] + 1} sessions; untestable on the pilot);</li>
    <li>(d) drop the {etf['etf_tickers']} ETFs ({pu(etf['etf_row_share'], 1)} of rows) from the stock universe.</li>
  </ul>
  <p>The exact column names, definitions, clean masks, embargo lengths, the ETF exclusion rule and the reporting
  formulas for rank-IC, net spread and the equal-weight benchmark are in <code>LABEL_STUDY.md</code>, section
  “Labels to carry to the 5-year run”; that section is the label specification for the production team.</p></div>
  <div class="panel note"><h3>A negative control, not a label</h3>
  <p><code>up_5d</code> is not a stock-selection label: regime-exposed (monthly base rate {up5['base_rate_month_min']:.2f}
  to {up5['base_rate_month_max']:.2f}), close-to-close entry, {poison} split-poisoned rows because it is unmasked,
  holdout AUC {raw5['holdout_auc']:.3f}, rank-IC {raw5_ric:.3f}. It stays only as a negative control: the gap between
  its pooled and cross-sectional AUC measures how much “skill” is market timing.</p></div>
</section>"""


def mean_over(feat: str, months: list[str]) -> float:
    xs = [D.IC[feat]["monthly_ic"].get(m) for m in months]
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs)


def same_sign(v: dict) -> int:
    return round(v["ic_sign_consistency"] * v["n_months"])


SHORT_H = ["mom_5", "mom_10", "dist_sma_5", "dist_sma_10", "dist_sma_20", "ret_1d", "rsi_2", "gap_pct", "vol_z_20",
           "flag_split_20d"]


def family_cards() -> tuple[str, str]:
    IC = D.IC
    months = D.eda_months
    pre = [m for m in months if m < D.crash]
    post = [m for m in months if m >= D.crash]
    y25 = [m for m in months if m.startswith("2025")]
    cvm = [s["name"] for s in D.splits_pilot["folds"]]
    st = D.eda["market_state"]["ic_by_state"]
    dp, dps = IC["deliv_pct"], IC["deliv_pct_sma_20"]
    sp = st["deliv_pct_sma_20"]
    mm = st["mom_12_1"]
    shape = D.eda["monotonicity"]["mom_12_1"]["shape"]
    shape_txt = {"u_shape": "U-shaped", "monotone_up": "monotone", "hump": "hump-shaped"}.get(shape, shape)
    sel = D.sel["per_year"]
    k52 = sum("dist_52w_high" in sel[y]["selected"] for y in D.years)
    am = D.suff["ic_summary"]["amihud_20"]["resid_full"]
    every = D.sel["features_selected_every_year"]
    tmax = max(abs(IC[x]["t_stat"]) for x in SHORT_H)
    cmax = max(IC[x]["ic_sign_consistency"] for x in SHORT_H)
    FACTS.update({"short_tmax": f"{tmax:.2f}", "short_cmax": f"{cmax:.3f}"})
    dw = dps["worst_month"]
    fams = [
        ("Delivery", "NSE delivery %, the one non-price input", ["deliv_pct", "deliv_pct_sma_20"],
         f"{sg(dp['mean_ic'])} (t {dp['t_stat']:.2f}, same sign in {same_sign(dp)} of {dp['n_months']} months); "
         f"{sg(dps['mean_ic'])} (t {dps['t_stat']:.2f}); works in up and down tapes ({sg(sp['up_dates']['mean_ic'])} / "
         f"{sg(sp['down_dates']['mean_ic'])})",
         f"The regime anchor and the strongest pillar. Its IC fell from about {sg(mean_over('deliv_pct_sma_20', y25), 2)} "
         f"in 2025 to about {sg(mean_over('deliv_pct_sma_20', cvm), 2)} over the 2026 test months (worst {sg(dw['ic'])} "
         f"in {mname(dw['month'])}). No peer-reviewed study of NSE delivery share exists; the signal is internal "
         f"evidence only."),
        ("Long momentum", "", ["ret_126d", "mom_12_1", "ret_63d"],
         f"{sg(IC['ret_126d']['mean_ic'])} (t {IC['ret_126d']['t_stat']:.1f}); mom_12_1 daily IC "
         f"{sg(mm['up_dates']['mean_ic'])} on up dates vs {sg(mm['down_dates']['mean_ic'])} on down dates (t of "
         f"difference {mm['t_stat_diff']:.2f}); {shape_txt} deciles",
         "Real, state-dependent, textbook (Cooper, Gutierrez &amp; Hameed). Linear terms waste it; trees or an explicit "
         "market-state interaction capture it."),
        ("52-week high / low distance", "", ["dist_52w_high", "dist_52w_low"],
         f"selected in {k52} of {len(D.years)} yearly re-selections at 5 years (<code>dist_52w_high</code>)",
         "Stable carrier of trend and drawdown state."),
        ("Volatility", "", ["atr_pct", "vol_20"],
         f"atr_pct averaged {sg(mean_over('atr_pct', pre))} for {len(pre)} months ({pre[0]} to {pre[-1]}), then "
         f"{sg(mean_over('atr_pct', post))} from {mname(post[0])}",
         'A regime variable, not alpha. Every challenger model that drifted off the champion collapsed onto this factor '
         '(<a href="#sota">state-of-the-art challengers</a>).'),
        ("Liquidity / size proxies", "", ["log_turnover", "amihud_20"],
         f"amihud_20 residual IC {sg(am['mean_ic'])} (t {sg(am['t'], 2)}, q {am['q_bh']:.3f})"
         + ("; the only feature selected in all four yearly re-selections" if every == ["amihud_20"] else ""),
         "Carries information the pilot's 10 features lacked."),
        ("Short horizon", ", ".join(SHORT_H), SHORT_H,
         (f"all |t| &lt; 1 (largest {tmax:.2f}), sign consistency ≤ {cmax:.3f}" if tmax < 1 else
          f"largest |t| {tmax:.2f}, sign consistency ≤ {cmax:.3f}"),
         "Dead weight. Adding more of them has negative expected value."),
    ]
    cards, trs = [], []
    for title, sub, reps, evid, verdict in fams:
        rr = []
        for x in reps:
            if x == "amihud_20":
                rr.append(f'<tr><td><code>{x}</code> <span class="dim2">residual</span></td>'
                          f'<td>{minibar(am["mean_ic"], 0.10, f"amihud_20 residual IC {sg(am["mean_ic"])}")}</td>'
                          f'<td>{sg(am["mean_ic"])}</td><td>{sg(am["t"], 2)}</td><td>{DASH}</td></tr>')
                continue
            v = IC[x]
            twin = f" {MID} {TWINS[x]}" if x in TWINS else ""
            rr.append(f'<tr><td><code>{x}</code><span class="dim2">{twin}</span></td>'
                      f'<td>{minibar(v["mean_ic"], 0.10, f"{x} mean monthly IC {sg(v["mean_ic"])}")}</td>'
                      f'<td>{sg(v["mean_ic"])}</td><td>{sg(v["t_stat"], 2)}</td>'
                      f'<td>{same_sign(v)}/{v["n_months"]}</td></tr>')
        cards.append(f'<div class="famc"><h4>{E(title)}</h4>{f"<div class=dim2>{E(sub)}</div>" if sub else ""}'
                     f'<div class="scroll"><table class="ftab"><thead><tr><th>Feature</th><th>Mean monthly IC</th>'
                     f'<th></th><th>t</th><th>Same sign</th></tr></thead><tbody>{"".join(rr)}</tbody></table></div>'
                     f'<p class="ev">{evid}</p><p class="vd">{verdict}</p></div>')
        rep = ", ".join(f"<code>{x}</code>" for x in reps) if title != "Short horizon" else ""
        trs.append([f"<b>{E(title)}</b>" + (f" ({E(sub)})" if sub else ""), rep, evid, verdict])
    tbl = table(["Family", "Representative", "Monthly IC vs 20-day excess", "Verdict"], trs, cls="plain",
                wrap=(0, 1, 2, 3))
    return '<div class="famgrid">' + "".join(cards) + "</div>", tbl


def nested_matrix() -> str:
    sel = D.sel
    years = D.years
    pilot = sel["pilot10"]
    feats = sorted(set(sel["features_selected_any_year"]) | set(pilot))
    cnt = {x: sum(x in sel["per_year"][y]["selected"] for y in years) for x in feats}
    order = sorted(feats, key=lambda x: (-cnt[x], x not in pilot, x))
    head = "<tr><th>Feature</th>" + "".join(f"<th>{y}</th>" for y in years) + "<th>Pilot 10</th><th>Years</th></tr>"
    body = []
    for x in order:
        cells = []
        for y in years:
            on = x in sel["per_year"][y]["selected"]
            tip = f"{x}: {'selected' if on else 'not selected'} for {y}"
            cells.append(f'<td data-tip="{E(tip)}">' + ('<span class="d-on" aria-label="selected"></span>' if on
                                                        else '<span class="d-off" aria-hidden="true"></span>') + "</td>")
        pc_ = '<span class="d-on d-pilot" aria-label="in the pilot 10"></span>' if x in pilot else \
            '<span class="d-off" aria-hidden="true"></span>'
        body.append(f"<tr><th scope=\"row\"><code>{E(x)}</code></th>{''.join(cells)}<td>{pc_}</td>"
                    f"<td class=\"num\">{cnt[x]}</td></tr>")
    k = "".join(f"<td>{sel['per_year'][y]['k_selected']}</td>" for y in years)
    ov = "".join(f"<td>{sel['per_year'][y]['n_overlap_selected_with_pilot10']}</td>" for y in years)
    nxt = "".join(f"<td>{a}</td>" for a in D.sel_overlap) + "<td>—</td>"
    t10 = "".join(f"<td>{a}</td>" for a in D.top10_overlap) + "<td>—</td>"
    foot = (f'<tr class="foot"><th scope="row">Features selected (k)</th>{k}<td>{len(pilot)}</td><td></td></tr>'
            f'<tr class="foot"><th scope="row">Shared with the pilot 10</th>{ov}<td></td><td></td></tr>'
            f'<tr class="foot"><th scope="row">Selected set shared with next year</th>{nxt}<td></td><td></td></tr>'
            f'<tr class="foot"><th scope="row">Top-10 shared with next year</th>{t10}<td></td><td></td></tr>')
    return (f'<div class="scroll"><table class="dots"><thead>{head}</thead><tbody>{"".join(body)}{foot}</tbody>'
            f'</table></div>')


def sec_features() -> str:
    IC = D.IC
    eda = D.eda
    cards, fam_tbl = family_cards()
    liq = eda["liquidity_gradient"]["ic_by_turnover_tercile"]["composite_top10"]
    ix = eda["interactions"]["cs_rank_vol_20_x_mom_12_1"]
    lag1 = eda["label_eda"]["mom_12_1_daily_ic_autocorr"]["lag_1"]
    worst = {mo: sum(1 for v in IC.values() if (v.get("worst_month") or {}).get("month") == mo) for mo in D.eda_months}
    k_crash = worst[D.crash]
    FACTS["worst_count"] = f"{k_crash} of {len(IC)}"
    lm = [m for m in LEAGUE_ORDER if m in D.S5]
    k5 = sum(D.S5[m]["worst_m"] == D.crash for m in lm)
    every5 = k5 == len(lm)
    fab = D.fab
    best = fab["variants"][fab["best_variant"]]
    red = D.fe["redundancy_flags_gt095"]
    rlo, rhi = min(r["spearman"] for r in red), max(r["spearman"] for r in red)
    fs = D.suff
    surv = fs["verdict"]["features_new_information_bh"]
    q = {x: fs["ic_summary"][x]["resid_full"]["q_bh"] for x in fs["new_features"]}
    never = ["avg_trade_size_z", "ats_chg_20", "trades_z_20", "close_vs_vwap", "close_vs_vwap_5", "last_vs_close",
             "gap_fill_10"]
    clus = fs["groups"]["B_cluster_sector_proxy"]
    ab_top5 = fs["ab"]["top5"]
    n_clusters = len(fs["manifest"]["clusters"]["clusters"])
    sel = D.sel
    every = sel["features_selected_every_year"]
    three = sorted([x for x in sel["features_selected_any_year"]
                    if sum(x in sel["per_year"][y]["selected"] for y in D.years) == len(D.years) - 1],
                   key=lambda x: ["deliv_value_share_20", "dist_52w_high", "atr_pct", "vol_20"].index(x)
                   if x in ["deliv_value_share_20", "dist_52w_high", "atr_pct", "vol_20"] else 99)
    t11 = D.A["T11"]
    t12 = D.A["T12"]["cv"]
    nl, a51, c10 = D.S5["nested_lgbm"], D.S5["all51"], D.S5["champion10"]
    w_c10 = sum(a51["auc"][fo] > c10["auc"][fo] for fo in D.folds)
    w_na = sum(nl["auc"][fo] > a51["auc"][fo] for fo in D.folds)
    pr = (P.boot or {}).get("pairs", {}).get("nested_lgbm - all51")
    pr_txt = f", paired delta {sg(pr['cv_mean']['delta'], 4)} {ci(*pr['cv_mean']['ci95'])}" if pr else ""
    ov = {y: sel["per_year"][y]["n_overlap_selected_with_pilot10"] for y in D.years}
    supp = [[f"Feature study A/B (<code>feature_ab_verdict.json</code>)",
             f"{D.fe['n_new_features']} engineered features (regime inputs, interactions, listing age, rank twins, "
             f"accumulation) in {len(fab['variants'])} variants",
             f"CV ≥ {f(fab['rebuild_bar_cv'])} (control {f(fab['control_clean_cv'])} + "
             f"{fab['rebuild_bar_cv'] - fab['control_clean_cv']:.3f}), every fold ≥ 0.50",
             f"<b>All {word(len(fab['variants']))} fail.</b> Best <code>{fab['best_variant']}</code> {f(best['cv'])} "
             f"(worst fold {best['min_fold']:.3f}); all {fab['variants']['lgbm_fe_all']['n_features']} features "
             f"{f(fab['variants']['lgbm_fe_all']['cv'])}; regime variant {f(fab['variants']['lgbm_fe_regime']['cv'])}. "
             f"Cause: redundancy (rank twins correlate {rlo:.2f} to {rhi:.2f} with existing features)."],
            [f"Feature sufficiency (<code>FEATURE_SUFFICIENCY.md</code>)",
             f"{len(fs['new_features'])} features from bhavcopy fields the pilot never read (<code>trades</code>, "
             f"<code>vwap</code>, <code>last</code>, <code>prev_close</code>, delivery value), Amihud illiquidity, "
             f"idiosyncratic vol, a {n_clusters}-cluster sector proxy from return correlations",
             f"residual IC vs the champion's 10 ranks, BH q ≤ {fs['rules']['bh_q']:g}; then the same harness A/B",
             f"<b>{len(surv)} of {len(fs['new_features'])} pass BH</b>: <code>{surv[0]}</code> (q {q[surv[0]]:.3f}) and "
             f"<code>{surv[1]}</code> (q {q[surv[1]]:.3f}), both re-expressions of delivery and liquidity. The A/B with "
             f"the top 5 reached {f(ab_top5['cv'])} ({'pass' if ab_top5['passes'] else 'fail'}), and its selection "
             f"window included the CV months. Fields never read carry no robust signal (lowest q "
             f"{min(q[x] for x in never):.2f}). The sector proxy is real (recovers IT, PSU banks, private banks, "
             f"defence, metals) but adds nothing (q ≥ {min(q[x] for x in clus):.2f})."],
            [f"5-year nested re-selection (<code>nested_selection.json</code>)",
             f"The pilot's selection method re-run inside each training history, once per calendar year, on 50 base "
             f"features + the {len(surv)} BH survivors", "none (descriptive)",
             f"<code>{every[0]}</code> selected every year; " + ", ".join(f"<code>{x}</code>" for x in three)
             + f" in {len(D.years) - 1} of {len(D.years)} years. Selected sets overlap in only "
               f"{rng(str(min(D.sel_overlap)), str(max(D.sel_overlap)))} features year to year; chosen k alternates "
               f"{' / '.join(str(k) for k in D.k_sel)}. The pilot's 10 overlap the yearly picks by "
               f"{' / '.join(str(v) for v in D.pilot_ov)}."]]
    supp_tbl = table(["Study", "What was tried", "Pass mark (fixed in advance)", "Result"], supp, cls="plain",
                     wrap=(0, 1, 2, 3))
    worst_txt = (f"why the 5-year fold for {mname(D.crash)} is the worst month for every model" if every5 else
                 f"why the 5-year fold for {mname(D.crash)} is the worst month for {word(k5)} of the {word(len(lm))} "
                 f"models in the 5-year league")
    return f"""
<section id="features">
  <div class="sec-eyebrow">05 {MID} Features</div>
  <h2>Features: predictive power, sufficiency, enhancement</h2>
  <h3 class="sub3">What the features predict</h3>
  <p class="lede">Source: <code>ml/results/feature_study/eda_features.json</code>, {D.eda['meta']['n_months']} months,
  {n(D.eda['meta']['rows_labeled_clean'])} clean labelled rows. Mean monthly rank IC against the 20-day excess
  return; bars span ±0.10.</p>
  {cards}
  <details><summary>Show as a table</summary><div class="card">{fam_tbl}</div></details>
  <p>Other facts that shape the design: edge is not confined to the illiquid tail (composite IC by turnover tercile
  {liq['illiquid']['mean_monthly_ic']:.3f} / {liq['mid']['mean_monthly_ic']:.3f} / {liq['liquid']['mean_monthly_ic']:.3f}
  from least to most liquid); the one interaction that earns a slot is momentum × volatility
  ({sg(ix['double_difference'] * 100, 2)} pp double difference, same sign in {pu(ix['pct_months_dd_same_sign'])} of
  months); delivery and momentum are substitutes, not a confirmation pair; daily ICs are nearly fully dependent draws
  (mom_12_1 lag-1 autocorrelation {lag1:.3f}), so only date-block significance is honest; <b>March 2026 is a
  common-mode inversion month</b>, the worst IC month for {k_crash} of {len(IC)} features at once, which is why every
  model's April 2026 fold was adversarial and {worst_txt} (<a href="#five-year">five-year walk-forward</a>).</p>
  <div class="card" id="inversion"><h3 class="cardh">Monthly IC of every base feature, and the March-2026 inversion</h3>
  <div class="scroll">{heatmap_html()}</div>{HM_KEY}
  <p class="cap">IC × 100 per month from <code>eda_features.json</code>; rank twins share a row because their rank
  ICs are identical. The first row counts the features whose worst month it was; the rule marks March 2026.</p></div>
  <h3 class="sub3">Sufficiency: three attempts to improve the features, one modest success</h3>
  <div class="card">{supp_tbl}</div>
  <div class="cols2">
    <div class="card"><h3 class="cardh">Residual IC of the {len(fs['new_features'])} new features</h3>
    <div class="scroll"><div class="wide-svg sm">{svg_resid_ic()}</div></div>
    <p class="cap">Information beyond the champion's 10 ranks (<code>feature_sufficiency.json</code>, residual IC over
    16 months). Highlighted: the {word(len(surv))} that pass Benjamini-Hochberg at q ≤ {fs['rules']['bh_q']:g}.</p></div>
    <div class="card"><h3 class="cardh">Nested yearly selection: which features each year picked</h3>
    {nested_matrix()}
    <p class="cap">From <code>nested_selection.json</code>: each year's selection used only data dated on or before that
    year's first training cut-off. Filled dots are selected features; the last column marks the pilot's 10.</p></div>
  </div>
  <div class="panel decision"><h3>Verdict on sufficiency</h3>
  <p>The end-of-day bhavcopy has been mined to its resolvable limit at this sample size. Two liquidity and delivery
  re-expressions carry information the 10-feature champion lacked and earn a place in the candidate set; nothing else
  does. Feature selection itself is unstable (gate 4 fails) and, at 5 years, buys nothing over giving LightGBM every
  feature ({f(nl['cv'])} nested vs {f(a51['cv'])} all features{pr_txt}, {w_na} of {nl['n']} fold wins: a tie).
  <b>The candidate set is therefore the {D.n_cand} end-of-day features; the single-model reference uses all of them
  without hand selection, and the ensemble as tested re-selects yearly from the same {D.n_cand}</b> (an all-{D.n_cand}
  ensemble A/B is queued). Further engineering on these inputs is stopped. The remaining feature upside is external
  data, ranked in <a href="#recs">Recommendations</a>.</p></div>
  <h3 class="sub3">What the pilot got wrong about features, and how it was found</h3>
  <p>The pilot's 10 features were ranked by univariate AUC on the four CV test months and by permutation importance on
  the June test month. The red team's honest re-run (<code>AUDIT.md</code>, T11) scored {f(t11['cv_auc_k10'])} instead
  of {f(D.audit['claim_audited']['cv_auc_frozen'])}, level with random 10-feature subsets ({t12['mean']:.3f} ±
  {t12['sd']:.3f}). At 5 years the same subset scores {f(c10['cv'])} and loses to all features in {w_c10} of
  {c10['n']} folds. The mechanism is visible in the yearly re-selections: the pilot's set is the 2025/2026 regime's set
  (overlap {ov['2025']} of 10 with the 2025 pick, {ov['2024']} of 10 with 2024's).</p>
</section>"""


def pilot_rows() -> list[dict]:
    out = []
    for m, label, fam, note in PILOT_ROWS:
        js = D.pilot[m]
        a = [x["auc"] for x in js["folds"]]
        out.append({"m": m, "name": label, "fam": fam, "note": note, "cv": js["cv_auc_mean"], "sd": js["cv_auc_std"],
                    "worst": min(a), "ho": js["holdout"]["auc"]})
    return out


def sota_rows() -> list[dict]:
    out = []
    for m, label, short in SOTA_ROWS:
        js = D.sota_m[m]
        a = [x["auc"] for x in js["folds"]]
        r = D.sota_rows[m]
        out.append({"m": m, "label": label, "name": short, "cv": js["cv_auc_mean"], "sd": js["cv_auc_std"],
                    "worst": min(a), "ho": js["holdout"]["auc"], "ric": r["rank_ic_cv_mean"],
                    "nw": r["rank_ic_cv_t_nw19"], "passes": r["passes"]})
    return out


def sec_models() -> str:
    pr = pilot_rows()
    t11 = D.A["T11"]
    rl_tr = D.pilot["rl_reinforce"]["training"]
    cvf = [s["name"] for s in D.splits_pilot["folds"]]
    rl_init = sum(rl_tr[f_]["best_epoch"] == 0 for f_ in cvf if f_ in rl_tr)
    notes = {"t11": f"selection-inflated; honest nested value {f(t11['cv_auc_k10'])}",
             "rl": f"fails to beat its own init on {rl_init} of {len(cvf)} folds"}
    ptab = table(["Model", "Family", "CV AUC", "Worst fold", "Holdout AUC", "Note"],
                 [[r["name"], r["fam"], f(r["cv"]), f"{r['worst']:.3f}", f"{r['ho']:.3f}", notes.get(r["note"], "")]
                  for r in pr], cls="plain", wrap=(5,))
    ten = D.ms["cv_holdout_tension"]
    k, nn = (int(x) for x in ten["models_holdout_above_cv"].split("/"))
    sr = sota_rows()
    nonpass = [r for r in sr if not r["passes"]]
    closest = max(nonpass, key=lambda r: r["cv"])
    stable = min(sr, key=lambda r: r["sd"])

    def passtxt(r):
        if r["passes"]:
            return "yes"
        if r is closest:
            return f"no, by {D.BAR - r['cv']:.4f}"
        if r is stable:
            return "no (most stable)"
        return "no"

    stab = table(["Model", "CV AUC ± sd", "Worst fold", "Holdout AUC", "Rank-IC (Newey-West t)", "Pass"],
                 [[r["label"], f"{f(r['cv'])} ± {r['sd']:.3f}", f"{r['worst']:.3f}", f"{r['ho']:.3f}",
                   f"{sg(r['ric'])} ({r['nw']:.1f})", passtxt(r)] for r in sr], cls="plain", wrap=(0,))
    ex = D.expo["exposures"]
    cvp = cvf

    def mexp(m):
        return sum(ex[m][fo]["vs_atr"] for fo in cvp) / len(cvp)

    lam = mexp("lgbm_lambdarank")
    nets = [mexp(m) for m in ("patchtst_lite", "dlinear", "cs_transformer")]
    lgb = D.m5["nested_lgbm"]["params"]["lgbm"]
    ttxt = (f"Why trees win here: the signal is weak and lives in a few slow features (IC about 0.05); extra capacity "
            f"mainly buys the ability to fit the training window's regime, and every challenger that drifted collapsed "
            f"onto the volatility factor (LambdaRank long high-vol: score correlation with <code>atr_pct</code> "
            f"{sg(lam, 2)}; the networks short it: {sg(max(nets), 2)} to {sg(min(nets), 2)}); "
            f"{MD_ONLY['train_dates']} training dates with overlapping labels are {MD_ONLY['indep_xs']} independent "
            f"cross-sections; and the March-2026 break sits inside every early-stopping validation tail, so each "
            f"early-stopped model paid for it while the champion's fixed {lgb['n_estimators']} trees did not. The "
            f"CatBoost result shows the gap was protocol, not algorithm: with fixed trees it ties LightGBM. The "
            f"literature agrees on all three points (<code>SOTA_FORECASTING.md</code> §1, §3, §4): on "
            f"engineered tabular features GBMs beat deep nets; temporal transformers lose to linear models; zero-shot "
            f"time-series foundation models have negative R² on daily returns.")
    return f"""
<section id="models">
  <div class="sec-eyebrow">06 {MID} Models</div>
  <h2>Models</h2>
  <h3 class="sub3" id="pilot-league">Pilot league (6 months, 4 CV folds + holdout)</h3>
  <p class="lede"><code>ml/MODEL_SELECTION.md</code>, clean reruns where available. Both panels share one scale; the
  dashed vertical is the bar fixed in advance for every later challenger, CV ≥ {f(D.BAR)}.</p>
  <div class="card"><div class="scroll"><div class="wide-svg">{svg_league_panel(pr, "Pilot league: CV AUC with spread, worst fold and holdout")}</div></div>
  {LEAGUE_KEY}
  <details><summary>Show as a table</summary>{ptab}</details></div>
  <p>{word(k, cap=True)} of {word(nn)} candidates scored better on the single holdout than on CV, and the two views rank
  models in near-opposite order (Spearman {sg(ten['spearman_rank_corr_cv_vs_holdout_primary'], 2)}): one regime change
  sitting on the CV/holdout boundary. That is why the program moved to {len(D.folds)} folds.</p>
  <h3 class="sub3" id="sota">State-of-the-art challengers</h3>
  <p class="lede">Same folds; <code>ml/results/sota/SOTA_MODELS.md</code>; bar fixed in advance: CV ≥ {f(D.BAR)}
  with every fold ≥ 0.50.</p>
  <div class="card"><div class="scroll"><div class="wide-svg">{svg_league_panel(sr, "State-of-the-art challengers: CV AUC with spread, worst fold and holdout", control=D.CTRL)}</div></div>
  {LEAGUE_KEY}
  <details open><summary>Show as a table</summary>{stab}</details></div>
  <p>{ttxt}</p>
  {sec_five_year()}
  {bifurcation()}
</section>"""


def league5_table() -> str:
    rows, rc = [], []
    boot = (P.boot or {}).get("models", {})
    for m in LEAGUE_ORDER:
        if m not in D.S5:
            if m == ENS:
                rows.append([LEAGUE_LABEL[m], "", chip("pending"), "", "", "", "", "needs the ensemble JSON"])
                rc.append("pend")
            continue
        s = D.S5[m]
        b = boot.get(m)
        cis = f"[{f(b['cv_mean_ci95'][0])}, {f(b['cv_mean_ci95'][1])}]" if b else ""
        mds = f"{pc(s['mds'], 2)} ({s['mds_pos']} / {s['n_ds']})" if s["mds"] is not None else ""
        rows.append([LEAGUE_LABEL[m], s["feats"], f"{f(s['cv'])} ± {s['sd']:.3f}", cis,
                     f"{s['ge']} / {s['n']} ({pu(s['ge'] / s['n'])})", f"{s['worst']:.3f} ({s['worst_m']})",
                     f"{s['ho']:.3f} ({pc(s['ho_ds'], 2)})", mds])
        rc.append("nested" if m in MEMBERS else "")
    return table(["Model", "Features", "CV AUC ± sd", "95% CI (20-session blocks)", "Folds ≥ 0.50",
                  "Worst fold", "Holdout AUC (decile spread)", "Mean fold decile spread (positive folds)"],
                 rows, cls="plain league5", wrap=(0,), row_cls=rc)


def peryear_table() -> str:
    S = D.S5
    years = sorted(S["all51"]["per_year"])
    rows = []
    for y in years:
        k = S["all51"]["per_year"][y][1]
        lab = {"2023": "2023 (short training windows)", "2026": "2026 (Jan to Jul)"}.get(y, y)
        rows.append([lab, str(k)] + [f"{S[m]['per_year'][y][0]:.3f}" for m in YEAR_COLS])
    return table(["Year", "Folds"] + [f"<code>{m}</code>" for m in YEAR_COLS], rows, cls="plain")


def wins_matrix() -> str:
    S = D.S5
    models = [m for m in CMP7 if m in S]
    nf = len(D.folds)
    head = "<tr><th>A beats B in k of " + str(nf) + " folds</th>" + "".join(
        f"<th>{E(NAME5[m])}</th>" for m in models) + "</tr>"
    body = []
    for a in models:
        cells = []
        for b in models:
            if a == b:
                cells.append(f'<td class="diag">{DASH}</td>')
                continue
            k = sum(S[a]["auc"][fo] > S[b]["auc"][fo] for fo in D.folds)
            dlt = k - nf / 2
            cls = ("hm-p3" if dlt >= 9 else "hm-p2" if dlt >= 5 else "hm-p1" if dlt >= 2 else "hm-0" if dlt > -2
                   else "hm-n1" if dlt > -5 else "hm-n2" if dlt > -9 else "hm-n3")
            cells.append(f'<td class="{cls}" data-tip="{E(f"{NAME5[a]} beats {NAME5[b]} in {k} of {nf} folds")}">{k}</td>')
        body.append(f'<tr><th scope="row">{E(NAME5[a])}</th>{"".join(cells)}</tr>')
    return f'<div class="scroll"><table class="wins"><thead>{head}</thead><tbody>{"".join(body)}</tbody></table></div>'


def regime_table() -> str:
    R = P.regimes
    G = R["groups"]
    skip = {"2023", "2024", "2025", "2026 Jan-Jul"}
    models = [m for m in ["nested_lgbm", "all51", ENS, "champion10", "lr_l2", "baseline_mom"]
              if G["all 43 CV months"].get(m, {}).get("n_months")]
    rows = []
    for lab, g in G.items():
        if lab in skip or lab.startswith("39 folds") or lab.startswith("POST-HOC"):
            continue
        c = g.get("nested_lgbm", {})
        if not c.get("n_months"):
            continue
        rows.append([E(lab), str(c["n_months"]), n(c["mean_n_train"]) if c.get("mean_n_train") else ""]
                    + [f"{g[m]['mean_auc']:.4f}" if g.get(m, {}).get("n_months") else "" for m in models]
                    + [pu(c["share_auc_ge_050"]), pc(c["top_decile_excess_vs_ew_20d"], 2), sg(c["mean_ic"], 4)])
    head = (["Regime or window", "Months", "Mean training rows"] + [E(NAME5[m]) for m in models]
            + ["nested_lgbm months ≥ 0.50", "nested_lgbm top decile − EW (20 days, gross)", "nested_lgbm mean IC"])
    return table(head, rows, cls="plain small-t", wrap=(0,))


def sec_five_year() -> str:
    S = D.S5
    a51, nl, c10, lr, nlr, bm = (S[m] for m in ("all51", "nested_lgbm", "champion10", "lr_l2", "nested_lr_l2",
                                                "baseline_mom"))
    nf = len(D.folds)

    def w(a, b):
        return sum(S[a]["auc"][fo] > S[b]["auc"][fo] for fo in D.folds)

    h2h = (f"Head-to-head by fold: all features beat the pilot's 10 in {w('all51', 'champion10')} of {nf}; nested beat the "
           f"pilot's 10 in {w('nested_lgbm', 'champion10')} of {nf}; nested vs all features {w('nested_lgbm', 'all51')} "
           f"of {nf} (a tie); all features beat the momentum rule in {w('all51', 'baseline_mom')} of {nf}.")
    # bootstrap paragraph + charts
    if P.boot:
        bd = P.boot["design"]
        pr = P.boot["pairs"]

        def pp(key, flip=False):
            c = pr[key]["cv_mean"]
            d, lo, hi = c["delta"], c["ci95"][0], c["ci95"][1]
            if flip:
                d, lo, hi = -d, -hi, -lo
            tag = " (a tie)" if lo <= 0 <= hi else (" (a real loss)" if hi < 0 else " (a real gain)")
            return f"{sg(d, 4)} {ci(lo, hi)}", tag

        s1, t1 = pp("nested_lgbm - all51")
        s2, t2 = pp("all51 - champion10", flip=True)
        s3, _ = pp("nested_lgbm - lr_l2")
        ens_lr = f"; ensemble vs L2 logistic {pp(f'{ENS} - lr_l2')[0]}" if f"{ENS} - lr_l2" in pr else ""
        lr_all0 = all(not v["cv_mean"]["ci_excludes_0"] for k, v in pr.items() if k.endswith(" - lr_l2"))
        FACTS.update({"boot_sel": s1, "boot_p10": s2, "boot_lr": s3})
        boot_p = (f"<p><b>Paired 20-session block bootstrap</b> (B = {bd['B']}, {bd['blocks_per_replicate']} blocks per "
                  f"replicate over the pooled {bd['n_cv_dates']} test dates, identical draws for every model; "
                  f"<code>bootstrap_5y.json</code>): nested selection vs all features {s1}{t1}; pilot 10 features vs "
                  f"all features {s2}{t2}; nested LightGBM vs L2 logistic {s3}{ens_lr}."
                  + (" The program cannot claim that any machine-learning model beats the linear benchmark on AUC."
                     if lr_all0 else "") + "</p>")
        boot_card = (f'<div class="card"><h3 class="cardh">Block-bootstrap intervals</h3>'
                     f'<div class="scroll"><div class="wide-svg">{svg_boot_models()}</div></div>'
                     f'<div class="scroll"><div class="wide-svg">{svg_boot_pairs()}</div></div>'
                     f'<ul class="legend"><li><span class="dot" style="background:var(--s1)"></span>43-fold CV mean, '
                     f'95% interval</li><li><span class="dot hollow s2"></span>holdout, 95% interval (about 2 blocks: '
                     f'indicative)</li></ul><p class="cap">{E(bd["holdout"])}.</p></div>')
    else:
        boot_p = ""
        boot_card = pending_card("Paired 20-session block bootstrap", ["ml/results/scale5y/bootstrap_5y.json"],
                                 "ml/scale5y_report.py is running the B = 1000 bootstrap.")
    # regimes
    if P.regimes:
        R = P.regimes
        G = R["groups"]
        nlg = {k: v["nested_lgbm"] for k, v in G.items()}
        up, dn = nlg["up (EW 20d > 0)"], nlg["down (EW 20d <= 0)"]
        lo_v, hi_v = nlg["low-vol"], nlg["high-vol"]
        run_k = next(k for k in G if k.startswith("2025-09..2026-02"))
        ex_k = next(k for k in G if k.startswith("43 CV months ex"))
        pm = R["per_month"]
        run_dirs = [pm[mo]["direction"] for mo in D.run]
        run_vol = [pm[mo]["vol_state"] for mo in D.run]
        ml_models = [m for m in (ENS, "all51", "nested_lgbm", "champion10", "lr_l2", "nested_lr_l2")
                     if G[run_k].get(m, {}).get("n_months")]
        run_means = [G[run_k][m]["mean_auc"] for m in ml_models]
        mom_run = G[run_k]["baseline_mom"]["mean_auc"]
        cr = pm[D.crash]
        inv = R["majority_inverted_months"]
        FACTS.update({"reg_down": f"{dn['mean_auc']:.3f}", "reg_up": f"{up['mean_auc']:.3f}",
                      "reg_ex": f"{nlg[ex_k]['mean_auc']:.4f}", "n_inverted": str(len(inv))})
        reg_p = (f"<p><b>Regimes</b> (defined from market data before any AUC was split by them; "
                 f"<code>regimes_5y.md</code>): models score higher in down months (nested LightGBM {dn['mean_auc']:.3f} "
                 f"over {dn['n_months']} months) than in up months ({up['mean_auc']:.3f} over {up['n_months']}), and higher "
                 f"in low-volatility months ({lo_v['mean_auc']:.3f}) than in high-volatility ones ({hi_v['mean_auc']:.3f}). "
                 f"One episode lifts the five-year mean: the {mname(D.run[0])} to {mname(D.run[-1])} run "
                 f"({word(run_dirs.count('down'))} of {word(len(D.run))} months down, {word(run_vol.count('low-vol'))} "
                 f"low-volatility) carries every machine-learned model to {min(run_means):.2f} to {max(run_means):.2f} "
                 f"(the momentum rule {mom_run:.2f}); without it and {mname(D.crash)}, nested LightGBM averages "
                 f"{nlg[ex_k]['mean_auc']:.4f} over the other {nlg[ex_k]['n_months']} months. {mname(D.crash)} was a "
                 f"V-shaped rebound after the February sell-off (equal-weight universe {pc(cr['ew_fwd_20d'])} in 20 days, "
                 f"volatility {pu(cr['ew_daily_vol_ann'])}) in which {pu(cr['inverted_feature_share'])} of features had "
                 f"their IC against its usual sign; {word(len(inv))} of {nf} months had a majority of features inverted "
                 f"({', '.join(inv)}).</p>")
        reg_card = (f'<div class="card"><h3 class="cardh">Mean fold AUC by pre-specified market regime</h3>'
                    f'{regime_table()}<p class="cap">From <code>regimes_5y.json</code>: direction is the sign of the '
                    f'equal-weight universe’s forward 20-day return; volatility is high above the 43-month median '
                    f'({pu(R["definition"]["vol_threshold_ann"], 1)} a year). Top-decile excess is gross of costs.</p></div>')
    else:
        reg_p = ""
        reg_card = pending_card("Regime table by pre-specified market state", ["ml/results/scale5y/regimes_5y.json"],
                                "ml/scale5y_report.py writes it after the bootstrap.")
    # moves together (JSON numbers; see hand-back)
    mlm = [m for m in STRIP if m in S and m != "baseline_mom"] + ["nested_lr_l2"]
    rv = [S[m]["auc"][fo] for m in mlm for fo in D.run]
    rmeans = [sum(S[m]["auc"][fo] for fo in D.run) / len(D.run) for m in mlm]
    mv = [S["baseline_mom"]["auc"][fo] for fo in D.run]
    allm = [m for m in LEAGUE_ORDER if m in S and m not in MEMBERS]
    cv_ = [S[m]["auc"][D.crash] for m in allm]
    all_crash = all(x < 0.5 for x in cv_)
    together = (f"Every model moves together month to month: from {mname(D.run[0])} to {mname(D.run[-1])} the "
                f"machine-learned models run {min(rv):.2f} to {max(rv):.2f} (window means {min(rmeans):.2f} to "
                f"{max(rmeans):.2f}; the momentum rule {min(mv):.2f} to {max(mv):.2f}) and "
                + ("all of them crash" if all_crash else "most of them crash")
                + f" in {mname(D.crash)} ({min(cv_):.2f} to {max(cv_):.2f}), the inversion month the EDA identified. "
                  f"The common component is the market regime, not the algorithm.")
    FACTS.update({"run_range": f"{min(rv):.2f} to {max(rv):.2f}", "crash_range": f"{min(cv_):.2f} to {max(cv_):.2f}"})
    nt = a51["ntrain"]
    # four findings
    pr = (P.boot or {}).get("pairs", {})
    p10 = pr.get("all51 - champion10", {}).get("cv_mean")
    p10_txt = f" {ci(p10['ci95'][0], p10['ci95'][1], signed=False)}" if p10 else ""
    py = {y: (S["nested_lgbm"]["per_year"][y][0], S["all51"]["per_year"][y][0]) for y in S["all51"]["per_year"]}
    ahead = [y for y, (a, b) in py.items() if a > b + 5e-4]
    ahead_txt = " and ".join(f"{y} ({py[y][0]:.4f} vs {py[y][1]:.4f})" for y in ahead)
    exp = (P.summary or {}).get("score_exposures_mean_per_date_spearman", {})
    reg = (P.regimes or {}).get("groups", {})
    f2_exp = ""
    if exp:
        def e3(m, k):
            return sg(exp[m][k]["cv_mean"], 2)
        f2_exp = (f" It is the purest defensive-factor ranker in the league: per-date score correlation "
                  f"{e3('lr_l2', 'atr_pct')} with <code>atr_pct</code>, {e3('lr_l2', 'amihud_20')} with Amihud illiquidity "
                  f"and {e3('lr_l2', 'dist_52w_high')} with the 52-week high (LightGBM: {e3('nested_lgbm', 'atr_pct')}, "
                  f"{e3('nested_lgbm', 'amihud_20')}, {e3('nested_lgbm', 'dist_52w_high')}).")
    f2_reg = ""
    if reg:
        f2_reg = (f" AUC rewards that tilt in down months ({reg['down (EW 20d <= 0)']['lr_l2']['mean_auc']:.3f}) and "
                  f"punishes it in rebounds ({lr['auc'][D.crash]:.3f} in {mname(D.crash)});")
    best_bottom = lr["ho_dm"] and max(range(10), key=lambda i: lr["ho_dm"][i]) == 0
    worst_lr = sorted([lr["worst"], nlr["worst"]])
    classifiers = [m for m in ("all51", "nested_lgbm", "champion10", "lr_l2", "nested_lr_l2", "nested_catboost") if m in S]
    hold_n = (P.boot or {}).get("design", {}).get("n_holdout_dates") or "holdout"
    hs = sorted(S[m]["ho_ds"] for m in classifiers)
    all_neg = all(x < 0 for x in hs)
    lgm = sorted([S["all51"]["mds"], S["nested_lgbm"]["mds"]])
    lgk = sorted([S["all51"]["mds_pos"], S["nested_lgbm"]["mds_pos"]])
    ric = (P.summary or {}).get("rank_ic", {}).get("nested_lgbm")
    f3 = ""
    if P.port:
        bk = P.port["books"]
        nup = bk["nested_lgbm|top_decile"]["by_direction_20d"]["up"]
        e_ex = bk[f"{ENS}|top_decile"]["segments"]["combined"]["20bps"]["excess_ann_vs_ew_252_20"]
        n_ex = bk["nested_lgbm|top_decile"]["segments"]["combined"]["20bps"]["excess_ann_vs_ew_252_20"]
        ens_atr = exp.get(ENS, {}).get("atr_pct", {}).get("cv_mean")
        f3 = (f"AUC {nl['cv']:.3f}" + (f" with an IC t of {ric['cv_nw_t_lag20']:.0f}" if ric else "")
              + f" coexists with no long-only edge (<a href=\"#portfolio5\">five-year portfolio</a>). The label "
                f"“beat the universe median” rewards low-volatility names, which cross the median often but do "
                f"not beat the mean of a right-skewed, rising universe, so the classifiers' top deciles are defensive: "
                f"nested LightGBM's trails the equal-weight universe by {abs(nup) * 100:.2f}% per 20 days in up months, "
                f"net of costs. ")
        tail = (f" The ensemble shows the fix: adding the high-volatility LambdaRank makes the blended score "
                f"volatility-neutral" + (f" (correlation with <code>atr_pct</code> {sg(ens_atr, 2)})" if ens_atr is not None
                                         else "")
                + f", costs {nl['cv'] - S[ENS]['cv']:.3f} of AUC and turns {pc(n_ex)} a year into {pc(e_ex)} a year over "
                  f"the universe. AUC is necessary, not sufficient; models are judged on net excess over the equal-weight "
                  f"universe." if ENS in S else "")
    else:
        tail = ""
    f3 += ((f"The negative holdout decile spreads (every classifier {pc(hs[-1], 1)} to {pc(hs[0], 1)}, the momentum rule "
            f"{pc(bm['ho_ds'], 2)}) are the same tilt over one {hold_n}-day window"
            if all_neg else "The holdout decile spreads differ in sign across classifiers")
           + f"; across the {nf} folds the classifiers' mean decile spreads are positive (LightGBM: "
             f"{pc(lgm[0], 2)} to {pc(lgm[1], 2)}, positive in {lgk[0]} to {lgk[1]} months).{tail}")
    lgb = D.m5["nested_lgbm"]["params"]["lgbm"]
    order43 = [m for m in ("lr_l2", "all51", "nested_lgbm", "champion10", "baseline_mom")]
    same_rank = sorted(order43, key=lambda m: -S[m]["cv"]) == sorted(order43, key=lambda m: -S[m]["cv39"])
    findings = [
        ("Feature selection did not transfer, and is not needed.",
         f"The pilot's 10 features lose to all features by {a51['cv'] - c10['cv']:.4f} AUC{p10_txt} and in "
         f"{w('all51', 'champion10')} of {nf} months; they average {c10['per_year']['2023'][0]:.4f} in 2023. Honest "
         f"yearly re-selection recovers the full-feature score exactly ({f(nl['cv'])} vs {f(a51['cv'])}) at the price of "
         f"unstable, alternating sets, and by calendar year it was ahead of all features only in {ahead_txt}"
         f"{' (2023 with small training sets)' if '2023' in ahead else ''}. LightGBM's own regularisation does the job. "
         f"The single-model reference uses all {D.n_cand} features."),
        ("The linear model has the highest mean and the worst risk.",
         f"L2 logistic scores {f(lr['cv'])} ({f(nlr['cv'])} nested), above LightGBM, so pre-registered gate 1 fails as "
         f"written.{f2_exp}{f2_reg} its month-to-month spread is {lr['sd'] / a51['sd']:.1f}× LightGBM's, its worst "
         f"month is {worst_lr[0]:.2f} to {worst_lr[1]:.2f}, and its holdout decile spread is {pc(lr['ho_ds'])}"
         + (", with its bottom decile its best decile" if best_bottom else "")
         + f". Nonlinearity here buys stability and sane tails, not mean accuracy, which matches the literature's "
           f"modest GBM-over-linear gains (GKX: {MD_ONLY['gkx_r2']} monthly R²)."),
        ("AUC and tradability disagree.", f3),
        ("Hyperparameters are a mild contamination of 2026.",
         f"The LightGBM configuration (num_leaves {lgb['num_leaves']}, learning rate {lgb['learning_rate']:g}, "
         f"{lgb['n_estimators']} trees, feature and bagging fraction {lgb['feature_fraction']:g}, min_data_in_leaf "
         f"{lgb['min_data_in_leaf']}) was chosen in the pilot, which saw April to July 2026. Those 4 folds and the holdout "
         f"are therefore not fully out-of-sample for the configuration; the {a51['n39']} folds from {D.folds[0]} to "
         f"2026-03 are. Removing those folds {'leaves the ranking unchanged' if same_rank else 'changes the ranking'} "
         f"({a51['n39']} folds, {D.folds[0]} to 2026-03: all features {f(a51['cv39'])}, nested {f(nl['cv39'])}, pilot 10 "
         f"features {f(c10['cv39'])}, L2 logistic {f(lr['cv39'])}, momentum rule {f(bm['cv39'])}; derived from the "
         f"per-fold JSONs)."),
    ]
    fl = "".join(f"<li><b>{t}</b> {b}</li>" for t, b in findings)
    pend_cards = []
    if ENS not in S:
        pend_cards.append(pending_card("Rank-average ensemble at 5 years", [f"ml/results/scale5y/{ENS}__{TASK}.json"],
                                       "ml/scale5y_nested.py --ensemble is running."))
    if not P.scale5y_md:
        pend_cards.append(pending_card("Scale-up narrative", ["ml/results/scale5y/SCALE5Y.md"],
                                       "The scale-up lead writes it after the report run."))
    return f"""
  <h3 class="sub3" id="five-year">Five-year walk-forward ({nf} monthly folds, rolling
  {D.m5['all51']['params']['train_sessions']}-session training window, {D.splits5['embargo_sessions']}-session embargo)</h3>
  <p class="lede"><code>ml/results/scale5y/</code>. Lines are each model's AUC in each monthly fold; hover a month for
  every value, or a legend entry to isolate one model.</p>
  <div class="card">{strip_legend()}<div class="scroll"><div class="wide-svg">{svg_strip()}</div></div>
  <p class="cap">The shaded folds trained on fewer than {FULL_WINDOW_ROWS // 1000}k rows ({n(nt[D.folds[0]])} for
  {D.folds[0]}, {n(nt['2023-12'])} for 2023-12; the full {D.m5['all51']['params']['train_sessions']}-session window of
  {n(nt[D.first_full])} rows arrives in {D.first_full}). Training rows from <code>all51__beat_mkt_20d.json</code>
  (<code>n_train</code>). The strip under the axis marks down months from <code>regimes_5y.json</code>.</p></div>
  <div class="card">{league5_table()}<p class="cap">Mean fold decile spread is the top-minus-bottom decile 20-day excess
  per fold, averaged over {nf} folds. Ensemble members are shown indented.</p></div>
  <p>{h2h}</p>
  <div class="card"><h3 class="cardh">Fold-win matrix</h3>{wins_matrix()}
  <p class="cap">Cell = number of the {nf} monthly folds in which the row model's AUC beat the column model's. Blue
  shades: row model ahead; red shades: behind; grey: within two of a tie.</p></div>
  {boot_p}
  {boot_card}
  {reg_p}
  {reg_card}
  <p><b>By calendar year</b> (mean fold AUC; <b>the 2023 folds train on short windows</b> because the dataset starts in
  {mname(D.man5['date_min'])}: {n(nt[D.folds[0]])} training rows for {D.folds[0]}, {n(nt['2023-12'])} for 2023-12, the
  full {D.m5['all51']['params']['train_sessions']}-session window of {FULL_WINDOW_ROWS // 1000}k+ rows only from
  {D.first_full}):</p>
  <div class="card">{peryear_table()}</div>
  <p>{together}</p>
  <h3 class="sub3">Four findings from the 5-year run</h3>
  <ol class="lims">{fl}</ol>
  <div class="card"><h3 class="cardh">AUC versus tradability</h3><div class="scroll"><div class="wide-svg">{svg_decile()}</div></div>
  <ul class="legend"><li><span class="chip" style="background:var(--s1)"></span>mean fold decile spread, {nf} folds</li>
  <li><span class="chip" style="background:var(--s2)"></span>holdout decile spread (one {hold_n}-session window)</li></ul>
  <p class="cap">Top-minus-bottom decile 20-day excess return per model, beside its CV AUC. The momentum rule has the
  lowest AUC and the largest positive holdout spread; L2 logistic has the highest AUC and the most negative one.</p></div>
  {"".join(pend_cards)}"""


def bifurcation() -> str:
    rl = D.pilot["rl_reinforce"]
    cvf = [s["name"] for s in D.splits_pilot["folds"]]
    rl_init = sum(rl["training"][x]["best_epoch"] == 0 for x in cvf if x in rl["training"])
    best = D.ex["best_skill"]
    hold_dates = D.strat["benchmarks"]["ew_universe"]["holdout"]["tranche"]["n_tranches"]
    p = {m: D.pilot[m]["cv_auc_mean"] for m in ("gru", "lstm", "mlp")}
    pt, dl, cs = D.sota_m["patchtst_lite"], D.sota_m["dlinear"], D.sota_m["cs_transformer"]
    cs_f = {x["fold"] if "fold" in x else cvf[i]: x["auc"] for i, x in enumerate(cs["folds"])}
    below = [mshort(k).split()[0] for k in cvf if cs_f.get(k, 1) < 0.5]
    below_txt = (" and ".join(MONTHS[[mm[:3] for mm in MONTHS].index(b)] for b in below) + " below 0.50") if below else ""
    cs_ric = D.sota_rows["cs_transformer"]
    sm = D.sm
    cap_ill = sm["lgbm_fs_selected"]["top_decile"]["capacity"]["aum_cap_rs_crore_p10name_5pct_adv"]
    top20 = sm["lgbm_fs_selected"]["top20"]["results"]["20bps"]["combined"]["daily_active"]["ann_mean_daily"]
    up5 = D.strat["up5d_label_check"]["lgbm_fs_selected_up5d|top_decile|hold5"]["results"]["20bps"]["combined"][
        "daily_active"]["ann_mean_daily"]
    rows = [
        ["Reinforcement learning (REINFORCE contextual bandit)",
         f"CV {f(rl['cv_auc_mean'])}; fails to beat its own initialisation on {rl_init} of {len(cvf)} folds; its own "
         f"portfolio simulation loses to a free momentum heuristic out of sample; its best numbers come from "
         f"{hold_dates} holdout dates (DSR {best['dsr']:.2f}). Literature: “no decent profitability” for RL in "
         f"cross-sectional selection; RL works where a simulator exists (execution, hedging)."],
        ["GRU / LSTM / MLP",
         f"At or below chance on CV ({p['gru']:.3f} / {p['lstm']:.3f} / {p['mlp']:.3f}). A 20-session temporal view adds "
         f"nothing the features do not already carry."],
        ["Temporal transformer (PatchTST-lite), DLinear",
         f"{pt['cv_auc_mean']:.3f} / {dl['cv_auc_mean']:.3f} CV, {pt['holdout']['auc']:.3f} / {dl['holdout']['auc']:.3f} "
         f"holdout; nearly identical fold paths, so attention adds about {pt['cv_auc_mean'] - dl['cv_auc_mean']:.3f} over "
         f"a two-layer linear model; both are a low-volatility bet in disguise."],
        ["Cross-sectional set-attention transformer",
         f"{cs['cv_auc_mean']:.3f} ± {cs['cv_auc_std']:.3f}, {below_txt}, holdout {cs['holdout']['auc']:.3f}, rank-IC "
         f"not significant (Newey-West t {cs_ric['rank_ic_cv_t_nw19']:.2f}). The label is already cross-sectional and the "
         f"rank features already normalise across stocks."],
        ["Time-series foundation models (Chronos, TimesFM)",
         "Not run; literature reports negative zero-shot R² on daily stock returns and direction accuracy near 50%."],
        ["51-feature LambdaRank and CatBoost variants, Huber as a scorer",
         "Below the champion; Huber stays only as an IC monitor (most stable fold path)."],
        ["Pilot 10-feature subset", f"{f(D.S5['champion10']['cv'])} at 5 years; selection fitted to the 2026 regime."],
        ["Decision tree, L1 / elastic-net logistic", "Dominated by their ensembles; identical to L2 to three decimals."],
        ["Short leg, illiquid tail, top-20 books, <code>up_5d</code> native book",
         f"Strategy study: shorts need SLB or F&amp;O ({MD_ONLY['fno_names']} names), the bottom decile is small caps "
         f"with unmodelled borrow; the illiquid tail caps capacity at ₹{cap_ill:,.0f} cr; top-20 books lose to the "
         f"universe ({pc(top20)} a year); the 5-day book nets {pc(up5)} a year."],
    ]
    return (f'<h3 class="sub3">Bifurcation: what is dropped and the evidence</h3><div class="card">'
            f'{table(["Dropped", "Evidence"], rows, cls="plain", wrap=(0, 1))}</div>')


def interp_be(sc: str, bk: str) -> float:
    r = D.sm[sc][bk]["results"]
    a20 = r["20bps"]["combined"]["daily_active"]["ann_mean_daily"]
    a40 = r["40bps"]["combined"]["daily_active"]["ann_mean_daily"]
    return 20 + 20 * a20 / (a20 - a40)


SCORER_LABEL = {"rl_reinforce": "RL", "lgbm_fs_selected": "champion"}
BASKET_LABEL = {"liq_ls_decile": "liquid long-short", "ls_decile": "long-short", "top_decile": "top decile",
                "liq_top_decile": "liquid top decile"}


def sec_strategy() -> str:
    sm = D.sm
    td = sm["lgbm_fs_selected"]["top_decile"]
    lq = sm["lgbm_fs_selected"]["liq_top_decile"]
    hm = sm["heuristic_mom20"]["top_decile"]
    ew = D.strat["benchmarks"]["ew_universe"]
    eng = D.strat["engine"]

    def c(b, seg="combined"):
        return b["results"]["20bps"][seg]

    def row_book(label, b, active_extra="", show_risk=True):
        r = c(b)
        da = r["daily_active"]
        return [label, pc(r["tranche"]["ann_return_252_h"]), f"<b>{pc(da['ann_mean_daily'])}</b>{active_extra}",
                f"{da['sharpe']:.2f} [{sg(da['sharpe_ci95'][0], 2)}, {sg(da['sharpe_ci95'][1], 2)}]",
                pc(r["daily"]["max_dd"]) if show_risk else "", pu(b["turnover_per_rebalance"]) if show_risk else ""]

    lq_extra = (f" (CV {pc(c(lq, 'cv')['daily_active']['ann_mean_daily'])}, holdout "
                f"{pc(c(lq, 'holdout')['daily_active']['ann_mean_daily'])})")
    ba_h = c(hm)["beta_alpha_vs_benchmark"]
    ba_c = c(td)["beta_alpha_vs_benchmark"]
    hm_extra = (f" (beta {ba_h['beta_vs_benchmark']:.2f}; beta-adjusted alpha {pc(ba_h['alpha_ann'])} vs champion "
                f"{pc(ba_c['alpha_ann'])})")
    cap_l = lq["capacity"]["aum_cap_rs_crore_p10name_5pct_adv"]
    books = [row_book(f"Champion top decile, long-only (~{td['basket_size_mean']:.0f} names)", td),
             row_book(f"Champion liquid-tercile top decile (~{lq['basket_size_mean']:.0f} names, capacity "
                      f"₹{cap_l:,.0f} cr)", lq, lq_extra, show_risk=False),
             row_book("Momentum heuristic (free)", hm, hm_extra),
             ["Equal-weight universe (passive)", pc(ew["combined"]["tranche"]["ann_return_252_h"]), "", "",
              pc(ew["combined"]["daily"]["max_dd"]), pu(ew["turnover_per_rebalance"])]]
    btab = table(["Book (20 bps per side)", "Annualised net", "Active vs equal-weight universe", "IR [95% CI]",
                  "Max drawdown", "Turnover"], books, cls="plain", wrap=(0, 2))
    ex = D.ex
    ch = ex["champion_top_decile_skill"]
    bs = ex["best_skill"]
    sc, bk = bs["series"].split("|")
    be = sorted([interp_be("lgbm_fs_selected", "top_decile"), interp_be("lgbm_fs_selected", "liq_top_decile")])
    trl = ch["min_track_record_periods_psr95_vs_0"]
    FACTS.update({"pilot_active": pc(c(td)["daily_active"]["ann_mean_daily"]), "pilot_ir": f"{c(td)['daily_active']['sharpe']:.2f}",
                  "pilot_dsr": f"{ch['dsr']:.2f}", "pilot_N": str(ex["n_trials"]["N_used"]),
                  "breakeven": f"{be[0]:.0f} to {be[1]:.0f}", "trl_days": f"{trl:.0f}"})
    dsr_p = (f"Deflated Sharpe with N = {ex['n_trials']['N_used']} trials: champion active book PSR {ch['psr_vs_0']:.2f}, "
             f"<b>DSR {ch['dsr']:.2f}</b>; best cell in the whole grid ({SCORER_LABEL.get(sc, sc)} "
             f"{BASKET_LABEL.get(bk, bk)}) DSR {bs['dsr']:.2f}. "
             + ("No cell survives. " if bs["dsr"] < 0.95 else "")
             + f"At its observed IR the champion needs about {trl:.0f} trading days ({trl / 252:.1f} years) of track "
               f"record to reach PSR 95%. What does look solid is cost headroom (break-even {be[0]:.0f} to {be[1]:.0f} bps "
               f"per side against a realistic {MD_ONLY['cost_realistic']}) and capacity (about "
               f"₹{round(cap_l, -2):,.0f} cr in the liquid book).")
    drows = []
    for key, lab in (("best_skill", f"Best cell: {SCORER_LABEL.get(sc, sc)}, {BASKET_LABEL.get(bk, bk)}"),
                     ("champion_top_decile_skill", "Champion top decile, active vs equal-weight universe"),
                     ("best_absolute_long_only", "Best absolute long-only (champion top decile, net − rf)"),
                     ("ew_universe_absolute_reference", "Passive equal-weight universe (net − rf)")):
        e = ex[key]
        drows.append([lab, f"{e['sr_annualised']:.2f}", sg(e["skew"], 2), f"{e['kurtosis_pearson']:.2f}",
                      f"{e['psr_vs_0']:.3f}", f"<b>{e['dsr']:.3f}</b>", f"{e['min_track_record_periods_psr95_vs_0']:.0f}"])
    dtab = table(["Strategy (combined, 20 bps)", "Sharpe (ann.)", "Skew", "Kurtosis", "PSR (SR* = 0)", "DSR",
                  "Days for PSR 95%"], drows, cls="plain", wrap=(0,))
    ymax = math.ceil(max(abs(float(r["net_active_vs_ew_20bps"])) for r in D.monthly) * 100) / 100
    minis = "".join(f'<figure class="mini"><figcaption>{E(t)}</figcaption>{svg_champion_mini(m, t, ymax)}</figure>'
                    for m, t in (("lgbm_fs_selected", "Champion (frozen run)"),
                                 ("lgbm_fs_selected_clean", "Champion (clean rerun)"),
                                 ("ensemble_rank3", "Pilot rank ensemble")))
    ewm = ew["combined"]["tranche"]["excess_vs_median_gross"]
    cap_ill = td["capacity"]["aum_cap_rs_crore_p10name_5pct_adv"]
    top20 = sm["lgbm_fs_selected"]["top20"]["results"]["20bps"]["combined"]["daily_active"]["ann_mean_daily"]
    up5 = D.strat["up5d_label_check"]["lgbm_fs_selected_up5d|top_decile|hold5"]["results"]["20bps"]["combined"][
        "daily_active"]["ann_mean_daily"]
    return f"""
<section id="strategy">
  <div class="sec-eyebrow">07 {MID} Strategy</div>
  <h2>Strategy: is there a promising return on capital?</h2>
  <h3 class="sub3">Pilot ({ew['combined']['tranche']['n_tranches']} signal dates, April to September 2026)</h3>
  <p class="lede"><code>ml/results/strategy/STRATEGY.md</code>. Engine: 20 overlapping tranches, one rebalanced per session,
  entry at the next open and exit 20 sessions later, exact open-to-open marks (reproduces the label on
  {pu(eng['path_check']['exit_mark_matches_label_frac'], 3)} of rows), costs netted against the tranche replaced, daily
  statistics weighted by exposure.</p>
  <div class="card">{btab}</div>
  <p>{dsr_p}</p>
  <div class="card">{dtab}<p class="cap">Bailey and López de Prado, from <code>strategy.json</code>
  (<code>deflated_sharpe</code>); T = {ch['T_periods']} effective daily observations.</p></div>
  <div class="card"><h3 class="cardh">Champion, month by month (net of 20 bps per side)</h3><div class="minis">{minis}</div>
  <p class="cap">Bars: mean 20-day net active return against the equal-weight universe per signal month, from
  <code>champion_monthly.csv</code>; figures under the bars: share of tranches that beat the universe. All four CV
  months were up months and both holdout months were down months.</p></div>
  <p>Two measurement lessons from this study now bind the whole program: the equal-weight universe beats the universe
  median by {pc(ewm, 2)} per 20 days (skew, not skill), so every “beats the median” hit rate is inflated; and
  the naive fully-invested average would have flipped the champion's active return from
  {pc(c(td)['daily_active']['ann_mean_daily'])} to {MD_ONLY['naive_flip']} a year, so exposure-weighting is mandatory.</p>
  <div class="panel note"><h3>Bifurcated by the strategy study</h3><ul class="lims">
    <li><b>Short leg.</b> Shorts need SLB or F&amp;O ({MD_ONLY['fno_names']} names); the bottom decile is small caps with
    unmodelled borrow.</li>
    <li><b>Illiquid tail.</b> It caps capacity at ₹{cap_ill:,.0f} cr.</li>
    <li><b>Top-20 books.</b> They lose to the universe ({pc(top20)} a year).</li>
    <li><b><code>up_5d</code> native book.</b> The 5-day book nets {pc(up5)} a year.</li></ul></div>
  {portfolio5()}
</section>"""


def portfolio5() -> str:
    if P.port is None:
        return ('<h3 class="sub3" id="portfolio5">Five years</h3>' + pending_card(
            "5-year paper portfolio", ["ml/results/scale5y/portfolio_5y.json"],
            "ml/scale5y_report.py runs the pre-registered paper portfolio over the 43-fold signal dates; gates 3 and 5 "
            "are decided by it. Until it lands, the ROC verdict stands at the pilot's: no capital."))
    pt = P.port
    bk = pt["books"]
    nh = str(pt["dsr"]["N_headline"])
    tr = pt["dsr"]["trials"]
    ew = pt["benchmarks"]["ew_universe"]["combined"]
    s5 = D.splits5

    def brow(key, label, em=False):
        b = bk[key]
        c = b["segments"]["combined"]["20bps"]
        d = pt["dsr"]["books"][key]["skill"][nh]
        ls = key.endswith("|ls_decile")
        exc = "" if ls else pc(c["excess_ann_vs_ew_252_20"])
        ir = "" if ls else f"{c['ir']:.2f} [{c['ir_ci95'][0]:.2f}, {c['ir_ci95'][1]:.2f}]"
        return [f"<b>{label}</b>" if em else label, pc(c["ann_return_252_20"]), exc,
                f"{c['sharpe']:.2f} [{c['sharpe_ci95'][0]:.2f}, {c['sharpe_ci95'][1]:.2f}]", ir, pc(c["max_dd"]),
                pu(b["turnover_per_rebalance"]), f"{b['months_positive']} / {b['n_months']}", f"{d['psr_vs_0']:.2f}",
                f"{d['dsr']:.3f}"]

    rows = [["Equal-weight universe (passive)", pc(ew["tranche"]["ann_return_252_h"]), "",
             f"{ew['daily']['sharpe']:.2f} [{ew['daily']['sharpe_ci95'][0]:.2f}, {ew['daily']['sharpe_ci95'][1]:.2f}]", "",
             pc(ew["daily"]["max_dd"]), pu(pt["benchmarks"]["ew_universe"]["turnover_per_rebalance"]), "", "", ""]]
    spec = [("nested_lgbm|top_decile", "Nested LightGBM, top decile"),
            ("nested_lgbm|liq_top_decile", "Nested LightGBM, liquid top decile"),
            ("all51|top_decile", "LightGBM all features, top decile"),
            (f"{ENS}|top_decile", "Rank ensemble, top decile"),
            (f"{ENS}|liq_top_decile", "Rank ensemble, liquid top decile (the pre-registered paper book)"),
            (f"{ENS}|ls_decile", "Rank ensemble, long-short"),
            ("lr_l2|top_decile", "L2 logistic, top decile"),
            (f"{HEUR}|top_decile", "Momentum rank, top decile")]
    for key, lab in spec:
        if key in bk:
            rows.append(brow(key, lab, em=key == f"{ENS}|top_decile"))
    head = ["Book (20 bps per side)", "Annualised net", "Excess vs equal-weight universe", "Sharpe [95% CI]",
            "IR [95% CI]", "Max drawdown", "Turnover", "Months beating the universe", "PSR", f"DSR (N = {nh})"]
    main_t = table(head, rows, cls="plain", wrap=(0,))
    allrows = [brow(k, k.replace("|", " | ")) for k in bk]
    full_t = table(head, allrows, cls="plain small-t", wrap=(0,))
    e = bk.get(f"{ENS}|top_decile")
    nl = bk["nested_lgbm|top_decile"]
    bullets = []
    if e:
        es = e["segments"]["combined"]
        ns = nl["segments"]["combined"]
        bullets.append(f"<b>Costs.</b> At 10 / 40 bps per side the ensemble's top-decile excess is "
                       f"{pc(es['10bps']['excess_ann_vs_ew_252_20'])} / {pc(es['40bps']['excess_ann_vs_ew_252_20'])} a "
                       f"year; nested LightGBM's is {pc(ns['10bps']['excess_ann_vs_ew_252_20'])} / "
                       f"{pc(ns['40bps']['excess_ann_vs_ew_252_20'])}.")
        cl = bk[f"{ENS}|liq_top_decile"]["capacity"]
        bullets.append(f"<b>Capacity.</b> The full ensemble top decile carries about "
                       f"₹{cap5(e['capacity']['aum_cap_rs_crore_p10name_5pct_adv'])} crore "
                       f"({pu(e['capacity']['share_names_adv20_below_5cr'])} of its names trade under ₹5 crore a day); "
                       f"the liquid book about ₹{cap5(cl['aum_cap_rs_crore_p10name_5pct_adv'])} crore.")
        sr0 = pt["dsr"]["books"][f"{ENS}|top_decile"]["skill"][nh]["sr0_expected_max_annualised"]
        all_miss = all(v["skill"][nh]["sr_annualised"] < v["skill"][nh]["sr0_expected_max_annualised"]
                       for v in pt["dsr"]["books"].values())
        n5 = str(pt["dsr"]["N_sensitivity"]["5y_only"])
        ls34 = pt["dsr"]["books"][f"{ENS}|ls_decile"]["skill"][n5]["dsr"]
        bullets.append(f"<b>Deflation.</b> The expected maximum Sharpe under the null at N = {nh} is {sr0:.2f} a year"
                       + ("; every book misses it" if all_miss else "")
                       + f". Counting only this run's {n5} trials, the ensemble long-short book's DSR would be "
                         f"{ls34:.2f}. That book also needs shorts that NSE cash offers only on {MD_ONLY['fno_names']} "
                         f"F&amp;O names.")
        yrs = sorted(e["by_year_20d"].values())
        beta = es["20bps"]["beta_vs_bench"]
        bullets.append(f"<b>Why the ensemble and not the classifiers.</b> It is close to volatility-neutral while the "
                       f"classifiers lean to low-volatility names (finding 3 above); its excess is "
                       + (f"positive in every calendar year ({pc(yrs[0], 2)} to {pc(yrs[-1], 2)} per 20 days)"
                          if yrs[0] > 0 else f"{pc(yrs[0], 2)} to {pc(yrs[-1], 2)} per 20 days by calendar year")
                       + f" with a beta of {beta:.2f} to the universe. It is also the best of {n5} trials in this run, "
                         f"which is exactly what the DSR charges for.")
    paper = bk.get(f"{ENS}|{PAPER_BASKET}")
    roc = ""
    if paper:
        pc_ = paper["segments"]["combined"]["20bps"]
        trl = pt["dsr"]["books"][f"{ENS}|{PAPER_BASKET}"]["skill"][nh]["min_track_record_periods_psr95_vs_0"]
        clear = e["segments"]["combined"]["20bps"]["ir_ci95"][0] > 0 if e else False
        roc = (f"<p><b>ROC verdict: no capital.</b> The ensemble's economics are the one result in the program "
               + ("with an interval clear of zero, and they fail the multiple-testing test. " if clear else
                  "considered, and they fail the multiple-testing test. ")
               + f"The historical record cannot reach DSR 0.95 at N = {nh}; only a fresh, frozen paper track record can "
                 f"(about {round(trl / 252)} years at IR {pc_['ir']:.2f} for PSR 95%).</p>")
    ymax = 0.06
    charts = "".join(f'<figure class="bookfig"><figcaption>{E(lab)}</figcaption><div class="scroll"><div class="wide-svg">'
                     f'{svg_monthly_book(k, ymax)}</div></div></figure>'
                     for k, lab in (("nested_lgbm|top_decile", "Nested LightGBM, top decile"),
                                    ("all51|top_decile", "LightGBM all features, top decile"),
                                    (f"{ENS}|top_decile", "Rank ensemble, top decile")) if k in bk)
    return f"""
  <h3 class="sub3" id="portfolio5">Five years ({n(pt['n_signal_dates'])} signal dates, {s5['folds'][0]['test_start']} to
  {s5['holdout']['test_end']})</h3>
  <p class="lede"><code>ml/results/scale5y/portfolio_5y.json</code>. Same engine and costs as the pilot. <b>N = {nh}
  trials was fixed in the code before any portfolio number existed</b>: {tr['5y_model_configs']} model configurations
  and {tr['5y_portfolio_books']} books on these folds, plus the pilot's {tr['pilot_configs_audit_T7_77']} configurations
  and {tr['pilot_portfolio_cells_STRATEGY_md']} portfolio cells.</p>
  <div class="card">{main_t}<details><summary>All {len(bk)} books</summary>{full_t}</details></div>
  <ul class="lims">{"".join(f"<li>{b}</li>" for b in bullets)}</ul>
  <div class="card"><h3 class="cardh">Month by month: net return minus the equal-weight universe (gate 3 counts the
  months above zero)</h3>{charts}
  <p class="cap">Per signal month: mean net (20 bps per side) 20-day tranche return minus the equal-weight universe's,
  from <code>portfolio_5y.json</code> (<code>monthly_20bps</code>); bars are clipped at ±{pu(ymax)}. The last two
  months are the holdout.</p></div>
  {roc}"""


SUP = str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹")


def sec_integrity() -> str:
    A = D.A
    ca = D.audit["claim_audited"]
    t0, t1, t2, t3, t4, t5, t6 = (A[k] for k in ("T0", "T1", "T2", "T3", "T4", "T5", "T6"))
    t7, t11, t12, t14 = A["T7"], A["T11"], A["T12"], A["T14"]
    n_tr = sum(x["n_train_rows"] for x in t3["folds"])
    pn = t6["persistent_noise"]
    in_noise = pn["champion_features_within_persistent_noise_range"]
    n_iid = len(t6["iid_noise"]["noise_ranks"])
    tab = {}
    for r in t7["table"]:
        tab.setdefault(r["N"], {})[r["null_sd_source"]] = r["p_at_least_one_reaches_champion"]
    nmax = t7["N"]["plus_univariate_feature_screens"]
    row = tab[nmax]
    perm = row["T1_within_date_permutation"]
    month = [v for k, v in row.items() if k.startswith("fold_to_fold") or k.startswith("10-session")]
    cross = next(v for k, v in row.items() if k.startswith("cross_config"))
    expo = round(math.log10(perm))
    b10 = t14["bootstrap"]["block_10"]
    ch_ho = D.pilot["lgbm_fs_selected_clean"]["holdout"]["auc"]
    mom_ho = D.mom_clean["holdout"]["auc"]
    purge = D.m5["nested_lgbm"]["exit_date_purge"]["rows_removed_total"] if "exit_date_purge" in D.m5["nested_lgbm"] \
        else None
    t9 = A["T9"]
    rows = [
        ["Reproduction", f"champion CV {t0['json_cv']:.6f} and holdout {t0['json_holdout']:.6f} reproduce "
                         f"{'exactly' if t0['delta_cv'] == 0 and t0['delta_holdout'] == 0 else 'within ' + str(max(abs(t0['delta_cv']), abs(t0['delta_holdout'])))}"],
        ["Null distribution", f"label permutation within date, {len(t1['null_cv']['values'])} seeds: CV "
                              f"{t1['null_cv']['mean']:.4f} ± {t1['null_cv']['sd']:.4f} (max {t1['null_cv']['max']:.4f}); "
                              f"champion z = {t1['z_cv']:.0f} against this null"],
        ["Leakage", f"features shifted by +1 session: {sg(t2['runs']['shift_-1']['cv_auc_mean'] - t2['real_cv'], 3)} AUC only; "
                    f"by +21 sessions: {t2['runs']['shift_-21']['cv_auc_mean']:.3f} (the detector works); labels recomputed "
                    f"from raw EOD: {n(t4['full_rows_compared'])} labels, max difference {t4['full_max_abs_diff']:g}; "
                    f"point-in-time universe identical; {t5['d_champion_features_truncated']['mismatches']} of "
                    f"{t5['d_champion_features_truncated']['n_values']} champion feature values change when recomputed "
                    f"from data ≤ t"],
        ["Embargo", f"{t3['violating_rows']} of {n_tr / 1e6:.2f}M training rows exit on or after test start; "
                    f"{t3['label_horizon']['rows_horizon_gt_21_market_sessions']} labels span more than 21 sessions."
                    + (f" Fixed at 5 years by purging on each label's actual exit date ({purge} rows purged across the "
                       f"{len(D.folds)} folds)" if purge is not None else "")],
        ["Noise control", f"{len(in_noise)} of {len(ca['features'])} pilot champion features sit inside the univariate AUC "
                          f"range of persistent pure noise (max {pn['noise_univariate_auc']['max']:.3f}); adding {n_iid} iid "
                          f"noise features raised CV by {sg(t6['harness_delta_cv'], 3)}"],
        ["Selection bias", f"features chosen on CV test months (T9 {t9['status'].lower()}); honest nested re-selection "
                           f"{f(t11['cv_auc_k10'])} vs claimed {f(ca['cv_auc_frozen'])} (T11); {len(t12['runs'])} random "
                           f"10-feature sets {t12['cv']['mean']:.3f} ± {t12['cv']['sd']:.3f}, "
                           f"{t12['n_holdout_ge_champion']} of {len(t12['runs'])} beat the champion on the holdout (T12)"],
        ["Best-of-N", f"{t7['N']['distinct_full_protocol_primary']} full configurations ({nmax} with screens) on the pilot "
                      f"task. Against the permutation σ the champion is distinguishable (P ≈ 10"
                      f"{str(expo).translate(SUP)}); against month-level σ narrowly (P {min(month):.3f} to "
                      f"{max(month):.3f}); against the cross-configuration spread it is not (P {cross:.2f})"],
        ["Dependence", f"10-session block CI for the champion's CV mean [{b10['champion_clean_cv_mean']['ci95'][0]:.3f}, "
                       f"{b10['champion_clean_cv_mean']['ci95'][1]:.3f}]; champion minus momentum on the holdout "
                       f"{sg(ch_ho - mom_ho, 3)} [{sg(b10['champion_minus_baseline_mom_clean_holdout']['ci95'][0], 3)}, "
                       f"{sg(b10['champion_minus_baseline_mom_clean_holdout']['ci95'][1], 3)}]"],
    ]
    area = table(["Area", "Result"], rows, cls="plain", wrap=(1,))

    def key(t):
        i = t["id"]
        if i == "T0":
            return f"CV {t['json_cv']:.6f}, holdout {t['json_holdout']:.6f}; difference {t['delta_cv']:g}"
        if i == "T1":
            return f"null {t['null_cv']['mean']:.4f} ± {t['null_cv']['sd']:.4f}; z = {t['z_cv']:.1f}"
        if i == "T2":
            return f"t+1: {t['runs']['shift_-1']['cv_auc_mean']:.4f}; t+21: {t['runs']['shift_-21']['cv_auc_mean']:.4f}"
        if i == "T3":
            return f"{t['violating_rows']} of {n(n_tr)} rows; {t['label_horizon']['rows_horizon_gt_21_market_sessions']} long labels"
        if i == "T4":
            return f"{n(t['full_rows_compared'])} labels, max |diff| {t['full_max_abs_diff']:g}"
        if i == "T5":
            d = t["d_champion_features_truncated"]
            return f"{d['mismatches']} of {d['n_values']} values differ"
        if i == "T6":
            return f"{len(in_noise)} of 10 in the noise range; +30 noise: {sg(t['harness_delta_cv'], 4)}"
        if i == "T7":
            return f"N = {t['N']['distinct_full_protocol_primary']} / {nmax}"
        if i == "T8":
            return f"duplicate rows {t['dataset_dup']}; phantom days {len(t['phantom_days_in_clean_calendar'])}"
        if i == "T9":
            return "selection used CV test folds"
        if i == "T10":
            return f"max |diff| {t['max_abs_diff']:g}"
        if i == "T11":
            return f"{f(t['cv_auc_k10'])} vs {f(t['claimed_cv'])} (optimism {sg(t['selection_optimism_cv'], 4)})"
        if i == "T12":
            return f"CV {t['cv']['mean']:.4f} ± {t['cv']['sd']:.4f}; holdout ≥ champion {t['n_holdout_ge_champion']} of 5"
        if i == "T13":
            v = t["variant_summary"]
            return (f"mask off: CV {v['all labelled rows (no y_clean mask)']['cv_auc_mean']:.4f} vs "
                    f"{v['clean (harness)']['cv_auc_mean']:.4f}")
        if i == "T14":
            c = t["bootstrap"]["block_10"]["champion_clean_cv_mean"]["ci95"]
            return f"10-session CI [{c[0]:.4f}, {c[1]:.4f}]"
        return ""

    trows = [[f"<b>{t['id']}</b>", E(t["name"]), chip(t["status"]), key(t)] for t in D.audit["tests"]]
    ttab = table(["Test", "What it checks", "Status", "Key number"], trows, cls="plain", wrap=(1, 3))
    stat = {s: sum(1 for t in D.audit["tests"] if t["status"] == s) for s in ("PASS", "FAIL", "INFO")}
    bon = []
    for nn in sorted(tab):
        r = tab[nn]
        bon.append([str(nn)] + [f"{r[k]:.2g}" if r[k] < 1e-3 else f"{r[k]:.3f}" for k in sorted(r)])
    bhead = ["N trials"] + [E(k.split(" (")[0].replace("_", " ")) for k in sorted(tab[nmax])]
    btab = table(bhead, bon, cls="plain small-t")
    return f"""
<section id="integrity">
  <div class="sec-eyebrow">08 {MID} Integrity</div>
  <h2>Integrity: what the red team found</h2>
  <p class="lede"><code>ml/results/audit/AUDIT.md</code>, {len(D.audit['tests'])} tests ({stat['PASS']} pass,
  {stat['FAIL']} fail, {stat['INFO']} informational).</p>
  <div class="card">{area}</div>
  <div class="card"><h3 class="cardh">The {len(D.audit['tests'])} audit tests</h3>{ttab}
  <p class="cap">From <code>audit.json</code>. The four failures are the findings that were then corrected: the
  embargo leak (purged on exit dates at 5 years), the noise-range features, holdout and CV-test use in selection, and
  the selection optimism that T11 measured.</p></div>
  <div class="card"><h3 class="cardh">Best-of-N: probability that the best of N pure-noise trials reaches the champion</h3>
  {btab}<p class="cap">From audit T7. The answer depends on which null standard deviation is honest: the permutation
  null ignores regime and selection, the cross-configuration spread includes them.</p></div>
  <p><b>Corrections made.</b> <code>ml/MODEL_SELECTION.md</code> now opens with the correction; the PR description is
  updated with it; the 5-year protocol nests selection inside each training window, purges on exit dates, and reports
  block bootstraps. The allowed wording for the pilot is the audit's: <i>“slightly better than chance … not a
  data or code artefact … not evidence of a tradable edge.”</i></p>
</section>"""


def sec_product() -> str:
    IC = D.IC
    months = D.eda_months
    y25 = [m for m in months if m.startswith("2025")]
    cvm = [s["name"] for s in D.splits_pilot["folds"]]
    kurt = D.eda["distribution_audit"]["atr_pct"]["excess_kurtosis"]
    inv = (P.regimes or {}).get("majority_inverted_months")
    exp = (P.summary or {}).get("score_exposures_mean_per_date_spearman", {}).get(ENS, {}).get("atr_pct", {})
    lm = [m for m in LEAGUE_ORDER if m in D.S5]
    crash_all = all(D.S5[m]["auc"][D.crash] < 0.5 for m in lm)
    crash_txt = ("every model failed in March 2026" if crash_all else
                 "every candidate failed in March 2026 (the LambdaRank member did not)")
    alerts = [
        ("Delivery monthly IC (<code>deliv_pct_sma_20</code> vs 20-day excess)", "below +0.02 for 2 consecutive months",
         f"the pillar faded from {sg(mean_over('deliv_pct_sma_20', y25), 2)} to {sg(mean_over('deliv_pct_sma_20', cvm), 2)} "
         f"after March 2026"),
        ("Monthly fold AUC of the live model", "below 0.50",
         "2026-03-type inversion months recur; floor is the headline stability metric"),
        ("Rank-IC, Newey-West t over trailing 12 months", "below 2.0", "the honest significance statistic"),
        ("L2 logistic coefficient sign flips, top 5 by magnitude", "any flip", "regime drift, cheap to compute"),
        ("Feature population stability index", "&gt; 0.25 on any champion feature",
         f"distribution drift (atr_pct kurtosis ≈ {round(kurt, -2):,.0f}: tails move)"),
        ("Paper book active return vs equal-weight universe, trailing 6 months",
         "IR confidence interval entirely below zero", "the economics, measured the honest way"),
    ]
    if inv is not None:
        alerts.append(("Feature-inversion monitor", "more than half of the features with IC against their usual sign in "
                       "a month", f"{word(len(inv))} of {len(D.folds)} months were inversion months and {crash_txt}"))
    if exp:
        alerts.append(("Ensemble score correlation with <code>atr_pct</code>, per date",
                       "absolute value above 0.20 for a month",
                       f"the book's edge rests on staying volatility-neutral ({sg(exp['cv_mean'], 2)} as tested)"))
    alerts.append(("Universe ETF count, split flag rate",
                   "ETFs &gt; 0 after the exclusion rule; <code>flag_split_20d</code> &gt; 1%", "data integrity"))
    at = table(["Signal", "Threshold", "Why"], [list(a) for a in alerts], cls="plain", wrap=(0, 1, 2))
    return f"""
<section id="product">
  <div class="sec-eyebrow">09 {MID} Product and monitoring</div>
  <h2>Product and monitoring specification (paper trading, no capital)</h2>
  <div class="card"><div class="scroll"><div class="wide-svg">{svg_flow()}</div></div></div>
  <p><b>Daily job (after EOD ingest).</b> Ingest → feature build → score every universe name with the frozen
  rank ensemble, the LightGBM all-features reference and the L2 logistic monitor → write ranks and the
  liquid-tercile top-decile paper list → paper-portfolio mark-to-market with 20 overlapping tranches at 20 bps
  per side → dashboard.</p>
  <p><b>Monthly job.</b> Retrain the three ensemble members on the trailing
  {D.m5['all51']['params']['train_sessions']} sessions ({D.splits5['embargo_sessions']}-session embargo, exit-date
  purge) on the year's frozen feature set, re-selected once a year; run the LightGBM reference as champion-challenger;
  log the trial count (the paper book is N = 1 and stays N = 1).</p>
  <h3 class="sub3">Alerts (pre-registered thresholds)</h3>
  <div class="card">{at}</div>
  <p><b>Dashboard.</b> The {len(D.folds)}-fold AUC strip with live months appended; IC by family; paper book vs
  equal-weight universe with the DSR trial count; gate table; data-quality tiles (sessions, duplicates, split flags,
  ETFs).</p>
  <p><b>Not a product yet.</b> No order routing, no short book, no capital. The program's own gate table is the release
  criterion.</p>
</section>"""


def sec_recs() -> str:
    pt = P.port
    t13 = D.A["T13"]["totals"]
    masked = (t13["masked_extreme_move"] + t13["masked_suspension_only"]) / t13["test_rows_in_window"]
    split20 = D.lvar["variants"]["no_20d"]["mask_breakdown_labelable"]["split_move_gt_22pct"]
    mask_rng = rng(pu(min(masked, split20), 1), pu(max(masked, split20), 1))
    be = sorted([interp_be("lgbm_fs_selected", "top_decile"), interp_be("lgbm_fs_selected", "liq_top_decile")])
    inv = (P.regimes or {}).get("majority_inverted_months")
    S = D.S5
    recs = []
    if pt:
        nh = str(pt["dsr"]["N_headline"])
        paper = pt["books"][f"{ENS}|{PAPER_BASKET}"]["segments"]["combined"]["20bps"]
        trl = pt["dsr"]["books"][f"{ENS}|{PAPER_BASKET}"]["skill"][nh]["min_track_record_periods_psr95_vs_0"]
        e = pt["books"][f"{ENS}|top_decile"]["segments"]["combined"]["20bps"]
        ls = pt["books"][f"{ENS}|ls_decile"]["segments"]["combined"]["20bps"]
        ls_d = pt["dsr"]["books"][f"{ENS}|ls_decile"]["skill"][nh]["dsr"]
        lam = S.get("nested_lambdarank", {}).get("cv")
        recs += [
            f"<b>Paper-trade the ensemble's liquid book as one frozen, pre-registered strategy from November 2026</b> "
            f"with the specification in <a href=\"#product\">Product and monitoring</a> and no new trials (N = 1). At "
            f"IR {paper['ir']:.2f} it needs about {round(trl / 252)} years ({trl:.0f} sessions) of track record to reach "
            f"PSR 95%; the clock starts only when the book exists.",
            f"<b>Pre-registered test of volatility-neutral construction:</b> each classifier's score residualised on "
            f"volatility and size per date, pass mark fixed in advance. The ensemble's {pc(e['excess_ann_vs_ew_252_20'], 0)} "
            f"a year says this is where the money is; a deliberate construction should capture it without depending on a "
            f"LambdaRank member that scores {lam:.3f} on its own." if lam is not None else
            "<b>Pre-registered test of volatility-neutral construction.</b>",
        ]
    else:
        recs.append("<b>Finish the 5-year verdict (running).</b> Portfolio, DSR with an honest N, bootstrap, regime table. "
                    "Decides gates 3 and 5.")
    recs += [
        f"<b>Corporate-actions feed</b> (NSE corporate actions, splits and bonuses, ex-dates and ratios). A data-integrity "
        f"item, not a feature item: it removes split artefacts from every rolling feature and from the {mask_rng} of labels "
        f"the mask drops.",
        f"<b>Two A/Bs with fixed pass marks:</b> LightGBM on all {D.n_cand} features (50 plus <code>amihud_20</code> and "
        f"<code>deliv_value_share_20</code>) against the 50; and the ensemble on all {D.n_cand} without yearly "
        f"re-selection against the ensemble as tested.",
        "<b>Delivery validation, pre-registered:</b> IC by year, liquidity tier and market state, orthogonalised against "
        "turnover and volatility. The strongest signal in the program has no external literature.",
        f"<b>Name-level costs:</b> high-low spread estimator plus square-root impact by liquidity tier; asymmetric STT and "
        f"stamp duty. This is what turns the {be[0]:.0f} to {be[1]:.0f} bps break-even into a real capacity number.",
    ]
    if pt:
        recs.append(f"<b>The short side only where it exists:</b> long-short restricted to F&amp;O names via stock "
                    f"futures, with borrow costs and 40 bps per side. The ensemble long-short book (Sharpe "
                    f"{ls['sharpe']:.2f}, DSR {ls_d:.2f}) is the only candidate; it is untested under those constraints.")
    recs += [
        "<b>Address the March-2026 failure mode:</b> market-state inputs (trailing universe momentum, drawdown, days since "
        "a sell-off) pre-registered against the full-feature baseline, plus the monthly feature-inversion monitor."
        + (f" {word(len(inv), cap=True)} of {len(D.folds)} months were inversion months; the 5-year window has enough "
           f"sell-offs to test on." if inv is not None else ""),
        "<b>External data in order of mechanism strength:</b> sector / industry classification (industry momentum, "
        "sector-neutral ranking); index and F&amp;O membership (shortability, inclusion pressure); fundamentals (value, "
        "profitability, accruals, earnings surprise); options-implied volatility and India VIX (the regime conditioner); "
        "institutional flows; surveillance lists, SLB and pledges.",
        "<b>Book construction research:</b> top quintile vs top decile, rank-weighting, turnover bands or hysteresis "
        "(Novy-Marx &amp; Velikov: a buy/hold spread is the best cost mitigation). Deterministic, cheap, and it replaces "
        "the only thing RL was adding.",
        "<b>Hygiene still open:</b> probability of backtest overfitting across the candidate set, combinatorial purged CV "
        "for the final choice, uniqueness weights for overlapping labels, history before 2021.",
        "<b>Do not spend the next unit of effort on</b> transformers, foundation models, reinforcement learning, or more "
        "bhavcopy-derived feature engineering. The evidence in <a href=\"#features\">Features</a> and "
        "<a href=\"#models\">Models</a> is against all four.",
    ]
    # what the program does not claim
    gc = gate_counts()
    claims = []
    if pt:
        best = max((v["skill"][nh]["dsr"], k) for k, v in pt["dsr"]["books"].items())
        claims.append(f"It does not claim a tradable edge. No model passes more than {word(max(k for k, _ in gc.values()))} "
                      f"of five pre-registered gates, and the best Deflated Sharpe in the program is {best[0]:.2f}, for a "
                      f"long-short book that cannot be traded as tested.")
    else:
        claims.append("It does not claim a tradable edge.")
    claims.append("It does not claim that machine learning beats a linear model on this problem; the logistic benchmark's "
                  "mean AUC is higher and every paired interval includes zero.")
    if pt:
        e = pt["books"][f"{ENS}|top_decile"]
        claims.append(f"It does not claim that the ensemble's {pc(e['segments']['combined']['20bps']['excess_ann_vs_ew_252_20'], 0)} "
                      f"a year over the universe is skill rather than a favourable volatility-factor mix over "
                      f"{e['n_months']} months of one, mostly rising, market.")
    cand = [m for m in ("nested_lgbm", "all51", "lr_l2", "nested_lr_l2") if m in S]
    lt = sorted(S[m]["lt"] for m in cand)
    every_c = all(S[m]["auc"][D.crash] < 0.5 for m in cand + [x for x in (ENS,) if x in S])
    claims.append(f"It does not claim that any model is reliable month to month: the single-model candidates fall below "
                  f"0.50 in {lt[0]} to {lt[-1]} of {len(D.folds)} months"
                  + (", and every candidate did in March 2026." if every_c else "."))
    claims.append("It does not claim the delivery signal is durable. Its IC fell by two-thirds after one regime break and "
                  "there is no external literature.")
    first = D.man5["date_min"]
    spans = []
    for fo in ("2023-01", "2023-12"):
        te = next(s["train_end"] for s in D.splits5["folds"] if s["name"] == fo)
        spans.append(((int(te[:4]) - int(first[:4])) * 12 + int(te[5:7]) - int(first[5:7])
                      + (int(te[8:10]) - int(first[8:10])) / 30.4))
    FACTS["train_months_2023"] = f"{round(spans[0])} to {round(spans[1])}"
    claims.append(f"It does not claim the 2023 fold results are representative: those models trained on "
                  f"{round(spans[0])} to {round(spans[1])} months of data.")
    claims.append("It does not claim the 2026 folds are fully out-of-sample for the LightGBM configuration, which was "
                  "tuned on them in the pilot.")
    if P.boot:
        hw = [(v["cv_mean"]["ci95"][1] - v["cv_mean"]["ci95"][0]) / 2 for v in P.boot["pairs"].values()]
        FACTS["pair_halfwidth"] = f"{min(hw):.3f} to {max(hw):.3f}"
        claims.append(f"It does not claim that AUC differences of 0.01 between models are decidable on these samples: the "
                      f"paired block-bootstrap intervals are about ±{min(hw):.3f} to ±{max(hw):.3f} wide.")
    else:
        claims.append("It does not claim that AUC differences of 0.01 between models are decidable on these samples; the "
                      "paired block bootstrap (pending) sets the resolution.")
    claims.append("It does not claim realistic costs for the illiquid tail or for any short book.")
    return f"""
<section id="recs">
  <div class="sec-eyebrow">10 {MID} Recommendations</div>
  <h2>Recommendations, ranked by expected value per unit of effort</h2>
  <ol class="lims recs">{"".join(f"<li>{r}</li>" for r in recs)}</ol>
  <div class="panel claims" id="claims"><h3>What this program does not claim</h3>
  <ul class="lims">{"".join(f"<li>{c}</li>" for c in claims)}</ul></div>
</section>"""


TEAMS = [
    ("Data engineering", "5-year ingest with duplicate-day guard, body-type detection, resume; dataset builder",
     ["nse_historical_ingest.py", "ml/data.py", "ml/build_5y.py"], ["ml/results/scale5y/manifest_5y.json"]),
    ("Quant (labels)", "Feature × label predictive-power matrix across 28 label variants", ["ml/label_study.py"],
     ["ml/results/label_study/LABEL_STUDY.md"]),
    ("Quant (features)", "Feature EDA, 23 engineered features, A/B against a pre-registered bar",
     ["ml/eda_features.py", "ml/features_ext.py", "ml/feature_ab.py"],
     ["ml/report/feature_study.html", "ml/results/feature_study/feature_ab_verdict.json"]),
    ("Data science", "Unused bhavcopy information, residual-IC test, external-data gap list",
     ["ml/feature_sufficiency.py"], ["ml/results/feature_sufficiency/FEATURE_SUFFICIENCY.md"]),
    ("Classic ML / DL / RL", "Logistic family, trees, GBMs, MLP, GRU/LSTM, REINFORCE bandit", ["ml/models/"],
     ["ml/MODEL_SELECTION.md"]),
    ("ML (state of the art)", "LambdaRank, Huber, CatBoost, PatchTST-lite, cross-sectional transformer, DLinear, rank "
                              "ensemble", ["ml/models/sota.py"], ["ml/results/sota/SOTA_MODELS.md"]),
    ("Research", "Literature review with 71 references, calibration of our numbers against published ones", [],
     ["ml/research/SOTA_FORECASTING.md"]),
    ("Testing (red team)", "Leakage, permutation null, point-in-time, best-of-N, honest nested selection",
     ["ml/audit.py"], ["ml/results/audit/AUDIT.md"]),
    ("Portfolio quant", "Net-of-cost backtest, capacity, Deflated Sharpe, bifurcation", ["ml/strategy_backtest.py"],
     ["ml/results/strategy/STRATEGY.md"]),
    ("Scale-up", "5-year walk-forward, nested selection, duel, regimes, gates",
     ["ml/scale5y.py", "ml/scale5y_nested.py", "ml/scale5y_report.py"], ["ml/results/scale5y/SCALE5Y.md"]),
    ("Analytics / product", "This report, the HTML report, monitoring spec", ["ml/make_program_report.py"],
     ["ml/PROGRAM_REPORT.md"]),
]

REPRO = """# data
python3 nse_historical_ingest.py --start 2021-10-01 --end 2026-10-16          # 5-year store (resume-safe)
python3 -m ml.data                                                              # pilot dataset (ml/data/)
python3 -m ml.build_5y                                                          # 5-year dataset (ml/data_5y/)
# studies
python3 -m ml.eval_aggregate && python3 -m ml.make_report                       # pilot league + report
python3 -m ml.eda_features && python3 -m ml.feature_ab && python3 -m ml.make_feature_study
python3 -m ml.feature_sufficiency
python3 -m ml.label_study
python3 -m ml.audit
python3 -m ml.models.sota
python3 -m ml.strategy_backtest
# 5-year walk-forward
python3 -m ml.scale5y --data ml/data_5y --out ml/results/scale5y --models champion10 all51 lr_l2 baseline_mom --train-sessions 504 --n-jobs 2 --n-threads 2
python3 -m ml.scale5y_nested --stages prep,select,run --n-jobs 2
python3 -m ml.scale5y_nested --stages run --ensemble
python3 -m ml.scale5y_report
# this report
python3 -m ml.make_program_report"""


def sec_appendix() -> str:
    trows = []
    for team, deliv, code, verdict in TEAMS:
        vs = []
        for v in verdict:
            on = (REPO / v).exists() if not v.startswith("ml/results/scale5y/") else (
                (P_dir() / Path(v).name).exists())
            vs.append(f"<code>{E(v)}</code> {chip('pass', 'on disk') if on else chip('pending')}")
        trows.append([f"<b>{E(team)}</b>", E(deliv), "<br>".join(f"<code>{E(c)}</code>" for c in code),
                      "<br>".join(vs)])
    ttab = table(["Team", "Agent deliverable", "Code", "Verdict file"], trows, cls="plain", wrap=(1, 2, 3))
    t7 = D.A["T7"]["N"]
    nt = D.ex["n_trials"]
    ab5 = len(D.fab["variants"])
    ab6 = len(D.suff["ab"])
    ledger = (f"Pilot primary task: {t7['distinct_full_protocol_primary']} full-protocol configurations, "
              f"{t7['plus_univariate_feature_screens']} including hyper-parameter and univariate screens "
              f"(<code>AUDIT.md</code> T7). Strategy grid: {nt['N_used']} trials ({nt['grid_scorer_x_basket']} scorer "
              f"× basket cells, {nt['diagnostics_up5d_and_hold5']} diagnostics, {nt['program_configs_on_label']} "
              f"program configurations). SOTA study: {len(D.sota['rows'])} configurations. Feature A/Bs: {ab5} + {ab6} "
              f"variants. Label study: {len(D.lmod['runs'])} model-level runs, {n(D.lsum['meta']['bh_family_size'])} "
              f"feature-label hypotheses. ")
    if P.port:
        tr = P.port["dsr"]["trials"]
        ledger += (f"Five-year run: N = {P.port['dsr']['N_headline']}, fixed in the code before any portfolio number "
                   f"existed: {tr['5y_model_configs']} model configurations and {tr['5y_portfolio_books']} books on the "
                   f"{len(D.folds)} folds, plus the pilot's {tr['pilot_configs_audit_T7_77']} configurations and "
                   f"{tr['pilot_portfolio_cells_STRATEGY_md']} portfolio cells (<code>portfolio_5y.json</code>). The paper "
                   f"book from November 2026 is N = 1 and must stay N = 1.")
    else:
        ledger += ("Five-year run: final count pending in <code>portfolio_5y.json</code>.")
    inputs = "".join(f"<li><code>{E(k)}</code>: {E(v)}</li>" for k, v in sorted(LOADED.items()))
    mdo = "".join(f"<li>{E(a)} ({E(b)})</li>" for a, b in MD_ONLY_SOURCES)
    return f"""
<section id="appendix">
  <div class="sec-eyebrow">Appendix</div>
  <h2>How the work was organised, how to reproduce it</h2>
  <p>Management asked for a Renaissance-grade, evidence-based answer to five questions: how well do the features predict
  each label type; which labels should be modelled; are the features sufficient or do they need enhancement; what do
  classic ML, deep learning, reinforcement learning, transformers and state-of-the-art forecasters achieve on this
  problem; and is there a strategy with a promising return on capital. The standing rule was: nothing inflated, every
  number reproducible, bifurcate what does not work.</p>
  <p>The program ran as a team of specialist agents under one shared evaluation harness (<code>ml/evaluation.py</code>,
  <code>ml/data.py</code>): purged walk-forward splits, {D.splits5['embargo_sessions']}-session embargo, seed 108,
  train-only preprocessing, one result schema. Each team wrote its own code and verdict:</p>
  <div class="card">{ttab}</div>
  <h3 class="sub3">Reproduction</h3>
  <pre><code>{E(REPRO)}</code></pre>
  <p class="small dim2">Seed 108 everywhere; OMP_NUM_THREADS=2 on the shared 4-core box.</p>
  <h3 class="sub3">Trial ledger (for Deflated Sharpe and best-of-N accounting)</h3>
  <p>{ledger}</p>
  <details><summary>Inputs read when this page was built</summary><ul class="inputs">{inputs}</ul>
  <p class="small">Figures typed from Markdown because no JSON or CSV carries them:</p><ul class="inputs">{mdo}</ul>
  </details>
</section>"""


_PDIR = [S5]


def P_dir() -> Path:
    return _PDIR[0]


# ===================================================================== page
CSS = """
/* Layout: one reading column of evidence cards on a soft page plane; serif prose,
   sans headings and data. Tokens shared verbatim with ml/report/index.html and feature_study.html. */
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
body{margin:0;background:var(--bg);color:var(--ink);font:16.5px/1.55 var(--serif);-webkit-text-size-adjust:100%}
.wrap{max-width:1072px;margin-inline:auto;
  padding-left:max(16px,env(safe-area-inset-left,0px));
  padding-right:max(16px,env(safe-area-inset-right,0px));
  padding-block:0 56px}
h1,h2,h3,h4{font-family:var(--sans);line-height:1.15;text-wrap:balance;margin:0}
p{margin:.55em 0;max-width:72ch}
a{color:var(--accent)}
a:focus-visible,summary:focus-visible,[tabindex]:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
b,strong{font-weight:700}
code{font-family:var(--mono);font-size:.86em;overflow-wrap:anywhere}
td,th{font-variant-numeric:tabular-nums}
.small{font-size:12.5px}
.dim2{color:var(--muted);font-weight:400}

/* hero */
.hero{padding-block:44px 8px}
.eyebrow{font:600 12px/1.3 var(--sans);letter-spacing:.14em;text-transform:uppercase;color:var(--accent)}
.hero h1{font-size:clamp(30px,5.4vw,46px);font-weight:800;letter-spacing:-.02em;margin:.25em 0 .2em}
.hero .sub{color:var(--ink2);font-size:17px;max-width:76ch}
.ribbon{display:flex;gap:10px;align-items:flex-start;margin-top:16px;padding:10px 14px;border-radius:10px;
  background:var(--surface);border:1px solid var(--border);font:500 14px/1.45 var(--sans);color:var(--ink2);max-width:100%}
.ribbon b{color:var(--ink)}
.ribbon .pulse{width:9px;height:9px;border-radius:50%;flex:none;margin-top:5px;background:var(--muted)}
.ribbon.done .pulse{background:var(--good)}
.ribbon.running .pulse{background:var(--accent)}
.verdict{margin-top:16px;border:1px solid var(--border);border-left:4px solid var(--accent);
  background:var(--surface);border-radius:10px;padding:16px 18px}
.verdict .vhead,.rec .vhead{font:700 13px/1 var(--sans);letter-spacing:.1em;text-transform:uppercase;color:var(--accent)}
.verdict p{font-family:var(--sans);font-size:18px;font-weight:650;margin:.45em 0 .55em;max-width:none}
.badges{display:flex;flex-wrap:wrap;gap:8px;font-family:var(--sans);font-size:13px}
.badge{border:1px solid var(--border);border-radius:12px;padding:5px 11px;color:var(--ink2);background:var(--bg)}
.badge b{color:var(--ink)}

/* sections */
section{margin-top:52px}
.sec-eyebrow{font:700 12px/1 var(--sans);letter-spacing:.14em;color:var(--accent);text-transform:uppercase}
section>h2{font-size:clamp(21px,3.2vw,28px);font-weight:750;letter-spacing:-.015em;margin:.3em 0 .4em}
h3.sub3{font-size:17.5px;margin:30px 0 6px}
h3.cardh{font-size:14.5px;margin:2px 4px 10px;color:var(--ink)}
.lede{color:var(--ink2)}
.card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px;margin-top:14px;min-width:0}
.cap{font:400 13px/1.5 var(--sans);color:var(--muted);margin:10px 4px 2px;max-width:none}
.srcs{font:400 12px/1.4 var(--sans);color:var(--muted);margin:8px 0 0;max-width:none}
figure{margin:0}
svg{display:block;width:100%;height:auto}
.scroll{overflow-x:auto;-webkit-overflow-scrolling:touch}
.wide-svg{min-width:700px}
.wide-svg.sm{min-width:560px}
.cols2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr));gap:12px;margin-top:14px}
.cols2>.card{margin-top:0}

/* verdict board */
.vcards{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:12px;margin-top:10px}
.vc{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px;min-width:0}
.vc h3{font-size:12px;letter-spacing:.1em;text-transform:uppercase;color:var(--accent);margin-bottom:6px}
.vc p{font-size:15.5px;margin:0;max-width:none}
.deliv{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:12px}
.dcard{background:var(--surface);border:1px solid var(--border);border-top:3px solid var(--accent);border-radius:10px;padding:14px 16px}
.dcard .dk{font:800 15px/1.2 var(--sans);color:var(--ink)}
.dcard p{font-size:15px;margin:.5em 0 0;max-width:none}
.dcard .dev{font:400 12.5px/1.4 var(--sans);color:var(--muted)}
.rec{margin-top:14px;background:var(--accent-soft);border-radius:10px;padding:16px 18px}
.rec p{font-family:var(--sans);font-size:16px;font-weight:550;margin:.45em 0 0;max-width:none}
table.gates{min-width:760px}
table.gates td,table.gates th{vertical-align:top;text-align:left}
table.gates td:nth-child(n+3){min-width:150px}
.gnum{font:600 13px/1.35 var(--sans);color:var(--ink);margin-bottom:5px}
table.gates tr:last-child td{border-top:1.5px solid var(--axisc)}

/* status chips */
.st{font:700 10.5px/1 var(--sans);letter-spacing:.06em;text-transform:uppercase;border-radius:999px;padding:4px 9px;
  display:inline-flex;gap:5px;align-items:center;white-space:nowrap;border:1px solid transparent}
.st.pass{color:var(--good);border-color:currentColor;background:var(--surface)}
.st.fail{color:var(--bad);background:var(--hm-n1)}
.st.pending{color:var(--ink2);border:1px dashed var(--muted)}
.st.info{color:var(--ink2);background:var(--hm-0)}

/* status board */
.board{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,440px),1fr));gap:12px;margin-top:12px}
.board .col{background:var(--surface);border:1px solid var(--border);border-top:3px solid var(--axisc);border-radius:10px;padding:14px 16px}
.board .col.ok{border-top-color:var(--good)}
.board .col.not{border-top-color:var(--bad)}
.board .col.pend{border-top-color:var(--muted)}
.board .col.unk{border-top-color:var(--accent)}
.board h3{font-size:15px;margin-bottom:6px}
.board ul{margin:0;padding-left:18px}
.board li{font-size:14.5px;margin:6px 0}

/* tiles */
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr));gap:12px;margin-top:14px}
.tile{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px;min-width:0}
.tile .v{font:700 27px/1.15 var(--sans);letter-spacing:-.01em}
.tile .k{font:600 12px/1.3 var(--sans);letter-spacing:.08em;text-transform:uppercase;color:var(--ink2);margin-top:6px}
.tile .d{font:400 13px/1.45 var(--sans);color:var(--muted);margin-top:6px}

/* pending */
.pending{border:1.5px dashed var(--axisc);border-radius:10px;padding:14px 16px;margin-top:14px;font-family:var(--sans);color:var(--ink2)}
.pending .ph{font:700 11px/1 var(--sans);letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}
.pending h4{font-size:15px;margin:6px 0 4px}
.pending p{font-size:13.5px;margin:4px 0;max-width:none}

/* svg type & marks */
svg text{font-family:var(--sans)}
.ax{font-size:12px;fill:var(--muted)}
.ax-s{font-size:10.5px}
.lbl{font-size:12.5px;fill:var(--ink2)}
.lbl-em{font-size:12.5px;font-weight:700;fill:var(--ink)}
.val{font-size:12.5px;font-weight:600;fill:var(--ink2)}
.val-em{font-size:12.5px;font-weight:700;fill:var(--ink)}
.colh{font-size:13px;font-weight:700;fill:var(--ink)}
.anno-t{font-size:11.5px;font-weight:600;fill:var(--ink2)}
.inbar{font-size:11px;font-weight:600;fill:var(--surface)}
.grid{stroke:var(--grid);stroke-width:1}
.axisln{stroke:var(--axisc);stroke-width:1.2}
.chance{stroke:var(--axisc);stroke-width:1.4;stroke-dasharray:5 4}
.passln{stroke:var(--ink2);stroke-width:1.5;stroke-dasharray:6 4}
.ctrlln{stroke:var(--accent);stroke-width:1.5}
.mark{stroke:var(--ink2);stroke-width:1;stroke-dasharray:3 3}
.bracket{fill:none;stroke:var(--ink2);stroke-width:1.2}
.shade{fill:var(--hm-0)}
.down-cell{fill:var(--axisc)}
.cell-y{fill:var(--hm-0)}
.seg-warm{fill:var(--axisc)}
.seg-cv{fill:var(--s1)}
.seg-ho{fill:var(--s2)}
.seg-tail{fill:none;stroke:var(--axisc);stroke-width:1.2;stroke-dasharray:3 3}
.tick-echo{stroke:var(--s2);stroke-width:1.6}
.fbox{fill:var(--surface);stroke:var(--axisc);stroke-width:1.2}
.fbox.em{stroke:var(--accent);stroke-width:2}
.ftxt{font-size:13px;font-weight:700;fill:var(--ink)}
.farrow{stroke:var(--muted);stroke-width:1.5}
.arrowhead{fill:var(--muted)}
svg .ln{transition:opacity .15s}
svg.dimmed .ln{opacity:.13}
svg.dimmed .ln.hot{opacity:1}
svg.mb{display:inline-block;width:132px;height:16px;vertical-align:middle}

/* legends */
.legend{list-style:none;display:flex;flex-wrap:wrap;gap:6px 16px;margin:10px 4px 0;padding:0;font:13px var(--sans);color:var(--ink2)}
.legend.sm{font-size:12px;gap:4px 12px;margin:4px 4px 0}
.legend li{display:flex;align-items:center;gap:7px}
.legend .chip{width:14px;height:14px;border-radius:4px;flex:none}
.legend b{color:var(--ink)}
.iso-legend{margin:0 4px 8px}
.iso-legend li{cursor:pointer;padding:3px 8px;border-radius:7px;border:1px solid transparent}
.iso-legend li:hover,.iso-legend li:focus{border-color:var(--border);background:var(--bg)}
.dot{width:11px;height:11px;border-radius:50%;flex:none;display:inline-block}
.dot.hollow{background:var(--surface);border:2px solid var(--muted)}
.dot.hollow.s2{border-color:var(--s2)}
.tri{width:0;height:0;border-left:6px solid transparent;border-right:6px solid transparent;border-bottom:10px solid var(--neg);display:inline-block}
.dia{width:10px;height:10px;background:var(--s2);transform:rotate(45deg);display:inline-block}
.lk{width:20px;height:0;display:inline-block;border-top:2px dashed var(--axisc)}
.lk.pass-k{border-top-color:var(--ink2)}

/* tables */
table{border-collapse:collapse;width:100%;font-family:var(--sans);font-size:13.6px}
th,td{padding:7px 10px;text-align:right;white-space:nowrap}
th:first-child,td:first-child{text-align:left}
thead th{font-size:11.2px;letter-spacing:.05em;text-transform:uppercase;color:var(--muted);border-bottom:1.5px solid var(--axisc);vertical-align:bottom}
tbody tr{border-bottom:1px solid var(--grid)}
tbody tr:last-child{border-bottom:none}
.wrapcell{white-space:normal;text-align:left;min-width:150px}
td.wrapcell{line-height:1.45}
table.plain td.wrapcell:first-child,table.plain th.wrapcell:first-child{min-width:190px}
table.small-t{font-size:12.6px}
table.league5 td.wrapcell:first-child{min-width:240px}
tr.nested td{color:var(--ink2);font-size:12.6px}
tr.nested td:first-child{padding-left:26px}
tr.pend td{color:var(--muted)}
.hm-n3{background:var(--hm-n3)} .hm-n2{background:var(--hm-n2)} .hm-n1{background:var(--hm-n1)}
.hm-0{background:var(--hm-0)} .hm-p1{background:var(--hm-p1)} .hm-p2{background:var(--hm-p2)}
.hm-p3{background:var(--hm-p3)} .hm-p4{background:var(--hm-p4)}
table.wins td{text-align:center;font-weight:600;min-width:62px;border:2px solid var(--surface)}
table.wins thead th{text-align:center;white-space:normal;min-width:70px;text-transform:none;letter-spacing:0;font-size:11.5px}
table.wins td.diag{color:var(--muted);font-weight:400}
table.dots td{text-align:center;padding:4px 8px}
table.dots th[scope=row]{font-weight:400}
table.dots thead th{text-align:center}
table.dots thead th:first-child{text-align:left}
table.dots tr.foot th,table.dots tr.foot td{font-size:12px;color:var(--ink2);border-top:1px solid var(--grid)}
.d-on{display:inline-block;width:12px;height:12px;border-radius:50%;background:var(--s1);vertical-align:middle}
.d-on.d-pilot{background:var(--accent)}
.d-off{display:inline-block;width:5px;height:5px;border-radius:50%;background:var(--axisc);vertical-align:middle}

/* heatmap (feature study pattern) */
table.heat{border-collapse:separate;border-spacing:2px;font-size:12px;width:auto;min-width:100%}
table.heat thead th{text-align:center;padding:3px 2px;border-bottom:none;font-size:10.5px}
table.heat thead th.fcol{text-align:left;vertical-align:bottom}
table.heat th.yr{color:var(--ink2);font-weight:700}
table.heat th.mo{text-transform:none;letter-spacing:0;font-size:11px;color:var(--ink2)}
table.heat th.sumh{vertical-align:bottom;min-width:56px;white-space:normal}
table.heat td{text-align:center;min-width:34px;padding:5px 2px;font-weight:600;color:var(--ink)}
table.heat td.na{background:transparent;color:var(--muted);font-weight:400}
table.heat td.sum{background:transparent;color:var(--ink2);font-weight:500;padding-inline:6px}
table.heat td.sum.strong{color:var(--ink);font-weight:700}
table.heat .brk{box-shadow:inset 3px 0 0 var(--ink2)}
table.heat tbody th{text-align:left;font-weight:500;font-size:12.3px;color:var(--ink2);padding:4px 10px 4px 2px}
table.heat tbody tr{border:none}
table.heat tr.fam th{font:700 11px/1 var(--sans);letter-spacing:.09em;text-transform:uppercase;color:var(--accent);padding:14px 2px 4px}
table.heat tr.cnt td{background:transparent;color:var(--ink2);font-weight:600}
table.heat tr.cnt td.cmax{color:var(--ink);font-weight:800;background:var(--hm-n1)}
table.heat tr.cnt th{font-weight:700;color:var(--ink)}
.hm-key{display:flex;flex-wrap:wrap;gap:6px;align-items:center;font:12px var(--sans);color:var(--muted);margin:12px 4px 0}
.hm-key .sw{display:inline-block;width:24px;height:13px;border-radius:3px;margin-left:6px}

/* feature families */
.famgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr));gap:12px;margin-top:12px}
.famc{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px;min-width:0}
.famc h4{font-size:15px;margin-bottom:2px}
.famc .dim2{font:12.5px var(--sans)}
table.ftab{font-size:12.6px;margin-top:6px}
table.ftab th,table.ftab td{padding:4px 6px}
table.ftab thead th{font-size:10.5px}
.famc .ev{font:13.5px/1.45 var(--sans);color:var(--ink2);margin:.6em 0 .2em;max-width:none}
.famc .vd{font-size:14.5px;margin:.3em 0 0;max-width:none}

/* small multiples */
.hpanels{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,290px),1fr));gap:14px}
.hp figcaption,.mini figcaption,.bookfig figcaption{font:600 12.8px/1.35 var(--sans);color:var(--ink);margin:0 4px 6px}
.minis{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,270px),1fr));gap:14px}
.bookfig{margin-top:10px}
.bookfig .wide-svg{min-width:640px}

/* panels */
.panel{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 16px;margin-top:14px}
.panel h3{font-size:15.5px;margin-bottom:6px}
.panel p,.panel li{font-size:15px;max-width:none}
.panel.decision{border-left:4px solid var(--accent)}
.panel.claims{border-left:4px solid var(--bad)}
ol.lims,ul.lims{padding-left:22px;margin:8px 0}
.lims li{margin:8px 0;max-width:78ch}
ol.recs li::marker{font-family:var(--sans);font-weight:700;color:var(--accent)}
details{margin-top:12px}
summary{cursor:pointer;font:600 13.5px var(--sans);color:var(--accent);padding:4px}
pre{font:12.3px/1.55 var(--mono);background:var(--surface);border:1px solid var(--border);border-radius:10px;
  padding:12px 14px;overflow-x:auto;max-width:100%}
pre code{font-size:inherit;overflow-wrap:normal}
ul.inputs{font:12.5px/1.5 var(--sans);color:var(--ink2);columns:2 320px;padding-left:18px}
footer{margin-top:56px;border-top:1px solid var(--grid);padding-top:14px;font:12.5px/1.6 var(--sans);color:var(--muted)}
footer p{max-width:none}

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
  .tile .v{font-size:23px}
  .verdict p{font-size:16.5px}
  section{margin-top:44px}
}
"""

JS = """
(function(){
  var tip=document.getElementById('tip');
  function move(e){var x=e.clientX+14,y=e.clientY+14,r=tip.getBoundingClientRect();
    if(x+r.width>window.innerWidth-8)x=e.clientX-r.width-10;
    if(y+r.height>window.innerHeight-8)y=e.clientY-r.height-10;
    tip.style.left=Math.max(4,x)+'px';tip.style.top=Math.max(4,y)+'px';}
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
  document.querySelectorAll('.iso-legend').forEach(function(ul){
    var svg=document.getElementById(ul.getAttribute('data-for'));if(!svg)return;
    ul.querySelectorAll('li[data-m]').forEach(function(li){
      function on(){svg.classList.add('dimmed');
        svg.querySelectorAll('.ln').forEach(function(p){p.classList.toggle('hot',p.getAttribute('data-m')===li.getAttribute('data-m'));});}
      function off(){svg.classList.remove('dimmed');
        svg.querySelectorAll('.ln').forEach(function(p){p.classList.remove('hot');});}
      li.addEventListener('pointerenter',on);li.addEventListener('pointerleave',off);
      li.addEventListener('focus',on);li.addEventListener('blur',off);});});
})();
"""


def page() -> str:
    body = "".join([sec_header(), sec_verdict(), sec_status(), sec_data(), sec_labels(), sec_features(), sec_models(),
                    sec_strategy(), sec_integrity(), sec_product(), sec_recs(), sec_appendix()])
    gen = []
    if P.boot:
        gen.append(f"bootstrap {P.boot_at}")
    if P.port:
        gen.append(f"portfolio {P.port.get('generated_at', '')}")
    if P.regimes:
        gen.append(f"regimes {P.regimes.get('generated_at', '')}")
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="description" content="SuryaDhana research program capstone report: NSE end-of-day signal, labels, features, models, strategy and integrity, with every number read from the committed artifacts.">
<title>SuryaDhana Research Program</title>
<style>{CSS}</style>
</head>
<body>
<div class="wrap">
{body}
<footer>
  <p>SuryaDhana research program {MID} {REPORT_DATE} {MID} built by <code>ml/make_program_report.py</code> from the
  committed artifacts listed in the appendix (5-year outputs: {E("; ".join(gen) or "pending")}). Narrative of record:
  <code>ml/PROGRAM_REPORT.md</code>. Inline SVG, no external resources; deterministic for identical inputs. Companion
  reports: <code>ml/report/index.html</code> (pilot) and <code>ml/report/feature_study.html</code>.</p>
</footer>
</div>
<div id="tip" role="status" aria-live="polite"></div>
<script>{JS}</script>
</body>
</html>
"""


def build(pending_dir: Path = S5) -> tuple[str, dict]:
    FACTS.clear()
    LOADED.clear()
    _PDIR[0] = pending_dir
    load_closed()
    D.mom_clean = load_json(RES / f"baseline_mom_clean__{TASK}.json")
    load_pending(pending_dir)
    derive()
    return page(), dict(FACTS)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--pending-dir", type=Path, default=S5, help="QA only: where to read the 5-year outputs")
    ap.add_argument("--out", type=Path, default=OUT, help="QA only: output file")
    a = ap.parse_args()
    html_s, _ = build(a.pending_dir)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(html_s)
    pend = pending_items()
    print(f"wrote {a.out} ({len(html_s.encode()):,} bytes)")
    print("5-year outputs: " + ("all present" if not pend else "pending: " + ", ".join(pend)))
    for k, v in sorted(LOADED.items()):
        if v != "read":
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
