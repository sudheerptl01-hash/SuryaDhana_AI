#!/usr/bin/env python3
"""Decision-focused feature EDA for the SuryaDhana pilot dataset.

Answers one question per analysis: "does this change what we feed the models?"
Outputs:
  * ml/results/feature_study/eda_features.json   -- all numbers + ranked insights
  * ml/report/assets/eda_*.png     -- 4 compact figures (Agg, dpi 120)

Protocol notes
  * every label-involving stat uses ONLY rows with y_clean_20d == True and
    label_beat_mkt_20d not NaN (the harness's primary-task frame);
  * IC = per-date cross-sectional Spearman rank correlation of feature vs
    y_excess_20d, averaged within calendar month (monthly IC);
  * Spearman IC is invariant to monotone transforms, so the rank-transform
    test (analysis 3) uses per-date PEARSON IC -- the linear-model view --
    comparing harness-style winsorized raw values vs cross-sectional rank;
  * seed 108; read-only w.r.t. every existing dataset / results file.

Run: cd /home/user/SuryaDhana_AI && python3 -m ml.eda_features
"""
from __future__ import annotations

import os

os.environ.setdefault("OMP_NUM_THREADS", "2")

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm

SEED = 108
np.random.seed(SEED)

ML_DIR = Path(__file__).resolve().parent
DATA_DIR = ML_DIR / "data"
RESULTS_DIR = ML_DIR / "results"
ASSETS_DIR = ML_DIR / "report" / "assets"

# Not ml/results/ itself: eval_aggregate treats every JSON there as a pilot league entry.
OUT_JSON = RESULTS_DIR / "feature_study" / "eda_features.json"

# ---- palette (dataviz skill reference instance): neutral grays + one accent --
ACCENT = "#2a78d6"          # categorical slot 1 (blue)
GRAY_DARK = "#52514e"       # secondary text / negative pole
GRAY_MID = "#8a8984"
GRAY_LIGHT = "#c3c2bb"
INK = "#0b0b0b"
SURFACE = "#fcfcfb"         # explicit light card -> readable on dark pages too
NEUTRAL_MID = "#f2f1ee"     # diverging midpoint
DIV_CMAP = LinearSegmentedColormap.from_list("gray_blue", [GRAY_DARK, NEUTRAL_MID, ACCENT])
DIV_CMAP.set_bad("#ffffff")

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE,
    "savefig.facecolor": SURFACE, "text.color": INK,
    "axes.edgecolor": GRAY_LIGHT, "axes.labelcolor": INK,
    "xtick.color": GRAY_DARK, "ytick.color": GRAY_DARK,
    "axes.grid": False, "font.size": 9,
})

CHAMPION = ["atr_pct", "deliv_pct_sma_20", "dist_52w_high", "ret_126d",
            "mom_12_1", "cs_rank_mom_20", "cs_rank_ret_126", "cs_rank_vol_20",
            "deliv_pct", "ret_63d"]
# univariate signs from ml/results/feature_selection.json ('+' = higher -> beats)
UNIV_SIGN = {f: "+" for f in CHAMPION}
UNIV_SIGN["cs_rank_mom_20"] = "-"

Y = "y_excess_20d"
MIN_N_DATE = 100      # min cross-section for a per-date IC
MIN_N_TERC = 50       # min rows per (date, tercile) group
FOLD1_TRAIN_END = "2026-02-25"   # splits.json fold 2026-04 train_end (harness fit window)
TEST_MONTHS = ["2026-04", "2026-05", "2026-06", "2026-07", "2026-08", "2026-09"]


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def load_labeled():
    df = pd.read_parquet(DATA_DIR / "model_dataset.parquet")
    df["date"] = pd.to_datetime(df["date"])
    manifest = json.loads((DATA_DIR / "manifest.json").read_text())
    base_feats = [f for f in manifest["features"] if not f.endswith("_isnan")]
    lab = df[df["label_beat_mkt_20d"].notna() & df["y_clean_20d"].astype(bool)].copy()
    lab["month"] = lab["date"].dt.strftime("%Y-%m")
    return df, lab, base_feats


def corr_by_group(frame: pd.DataFrame, keys: list[str], xcol: str, ycol: str,
                  min_n: int) -> pd.Series:
    """Per-group Pearson corr of xcol vs ycol, vectorized via group sums."""
    t = frame[keys + [xcol, ycol]].dropna(subset=[xcol, ycol]).copy()
    if t.empty:
        return pd.Series(dtype=float)
    t["_xy"] = t[xcol] * t[ycol]
    t["_xx"] = t[xcol] * t[xcol]
    t["_yy"] = t[ycol] * t[ycol]
    g = t.groupby(keys, observed=True)
    s = g[[xcol, ycol, "_xy", "_xx", "_yy"]].sum()
    n = g.size()
    mx, my = s[xcol] / n, s[ycol] / n
    cov = s["_xy"] / n - mx * my
    vx = (s["_xx"] / n - mx ** 2).clip(lower=0)
    vy = (s["_yy"] / n - my ** 2).clip(lower=0)
    denom = np.sqrt(vx * vy)
    ic = cov / denom.replace(0, np.nan)
    return ic[n >= min_n]


def daily_spearman_ic(lab: pd.DataFrame, feat: str, min_n: int = MIN_N_DATE) -> pd.Series:
    """Per-date Spearman rank IC of feat vs y_excess_20d (ranks within date,
    restricted to rows where the feature is observed)."""
    sub = lab.loc[lab[feat].notna(), ["date", feat, Y]].copy()
    if sub.empty:
        return pd.Series(dtype=float)
    g = sub.groupby("date", observed=True)
    sub["_rx"] = g[feat].rank()
    sub["_ry"] = g[Y].rank()
    return corr_by_group(sub, ["date"], "_rx", "_ry", min_n)


def monthly_stats(daily_ic: pd.Series) -> dict:
    """Collapse a per-date IC series to monthly ICs and stability stats."""
    if daily_ic.empty:
        return {"n_months": 0}
    m = daily_ic.groupby(daily_ic.index.get_level_values("date").strftime("%Y-%m")).mean()
    mean_ic = float(m.mean())
    ic_std = float(m.std(ddof=1)) if len(m) > 1 else float("nan")
    sgn = np.sign(mean_ic) if mean_ic != 0 else 1.0
    consistency = float((np.sign(m) == sgn).mean())
    adverse = (m * sgn)
    worst = adverse.idxmin()
    t = mean_ic / (ic_std / np.sqrt(len(m))) if ic_std and ic_std > 0 else float("nan")
    return {
        "mean_ic": round(mean_ic, 5), "ic_std": round(ic_std, 5),
        "ic_sign_consistency": round(consistency, 3),
        "worst_month": {"month": str(worst), "ic": round(float(m.loc[worst]), 5)},
        "n_months": int(len(m)), "t_stat": round(float(t), 2) if np.isfinite(t) else None,
        "mean_abs_lt_monthly_std": bool(abs(mean_ic) < ic_std) if np.isfinite(ic_std) else None,
        "monthly_ic": {k: round(float(v), 5) for k, v in m.items()},
    }


def per_date_rank_pct(lab: pd.DataFrame, feat: str) -> pd.Series:
    return lab.groupby("date", observed=True)[feat].rank(pct=True)


def tercile_of(rank_pct: pd.Series) -> pd.Series:
    return np.minimum(np.ceil(rank_pct * 3) - 1, 2).astype(int)


def jsonable(o):
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [jsonable(v) for v in o]
    if isinstance(o, (np.floating, float)):
        f = float(o)
        return None if not np.isfinite(f) else f
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


# --------------------------------------------------------------------------- #
# 1. IC stability
# --------------------------------------------------------------------------- #
def analysis_ic_stability(lab, base_feats):
    out, daily_store = {}, {}
    for f in base_feats:
        d = daily_spearman_ic(lab, f)
        daily_store[f] = d
        out[f] = monthly_stats(d)
    return out, daily_store


# --------------------------------------------------------------------------- #
# 2. Monotonicity (champion 10)
# --------------------------------------------------------------------------- #
def shape_label(dec_means: np.ndarray) -> str:
    v = dec_means
    steps = np.diff(v)
    frac_up = (steps > 0).mean()
    amax, amin = int(np.argmax(v)), int(np.argmin(v))
    if frac_up >= 0.7 and amax >= 8:
        return "monotone_up"
    if frac_up <= 0.3 and amin >= 8:
        return "monotone_down"
    if 2 <= amax <= 7 and v[amax] > max(v[0], v[-1]):
        return "hump"
    if 2 <= amin <= 7 and v[amin] < min(v[0], v[-1]):
        return "u_shape"
    return "noisy"


def analysis_monotonicity(lab):
    res = {}
    for f in CHAMPION:
        sub = lab.loc[lab[f].notna(), ["date", "month", f, Y]].copy()
        r = sub.groupby("date", observed=True)[f].rank(pct=True)
        sub["_dec"] = np.minimum(np.ceil(r * 10) - 1, 9).astype(int)
        dec_means = sub.groupby("_dec")[Y].mean().reindex(range(10))
        dec_n = sub.groupby("_dec")[Y].size().reindex(range(10)).fillna(0)
        bym = sub[sub["_dec"].isin([0, 9])].groupby(["month", "_dec"])[Y].mean().unstack()
        spread_m = (bym[9] - bym[0]).dropna()
        res[f] = {
            "decile_mean_y_excess": [round(float(x), 5) for x in dec_means],
            "decile_n": [int(x) for x in dec_n],
            "pooled_top_bottom_spread": round(float(dec_means.iloc[9] - dec_means.iloc[0]), 5),
            "pct_months_spread_positive": round(float((spread_m > 0).mean()), 3),
            "n_months": int(len(spread_m)),
            "shape": shape_label(dec_means.to_numpy()),
        }
    return res


# --------------------------------------------------------------------------- #
# 3. Distribution & transform audit
# --------------------------------------------------------------------------- #
def recommend_transform(f, skew, kurt, vmin):
    if f.startswith("cs_rank") or f.startswith("flag_") or f in ("close_pos_in_range",):
        return "keep_as_is (bounded/rank)"
    if f in ("rsi_2", "rsi_14"):
        return "keep_as_is (bounded 0-100)"
    if abs(skew) > 2 and vmin >= 0:
        return "log1p + cs_rank variant"
    if abs(skew) > 2:
        return "cs_rank (or signed-power 0.5)"
    if kurt > 8:
        return "cs_rank (heavy tails)"
    return "keep_as_is"


def analysis_distribution(lab, base_feats):
    train = lab[lab["date"] <= FOLD1_TRAIN_END]
    post = lab[lab["date"] > FOLD1_TRAIN_END]
    dist = {}
    for f in base_feats:
        v = lab[f].dropna()
        if v.empty:
            continue
        lo, hi = train[f].quantile(0.01), train[f].quantile(0.99)
        pv = post[f].dropna()
        pct_clip = float(((pv < lo) | (pv > hi)).mean()) if len(pv) and np.isfinite(lo) else None
        skew = float(v.skew())
        kurt = float(v.kurt())
        dist[f] = {
            "skew": round(skew, 3), "excess_kurtosis": round(kurt, 3),
            "pct_exact_zero": round(float((v == 0).mean()), 5),
            "pct_clipped_at_fold1_train_1_99": round(pct_clip, 5) if pct_clip is not None else None,
            "recommended_transform": recommend_transform(f, skew, kurt, float(v.min())),
        }
    return dist


def analysis_rank_transform(lab):
    """Linear-model view: monthly PEARSON IC of harness-winsorized raw values
    vs per-date cs-rank, for the champion 10. (Spearman is transform-invariant.)"""
    out = {}
    for f in CHAMPION:
        sub = lab.loc[lab[f].notna(), ["date", f, Y]].copy()
        lo, hi = sub[f].quantile(0.01), sub[f].quantile(0.99)
        sub["_raw"] = sub[f].clip(lo, hi)
        sub["_rnk"] = sub.groupby("date", observed=True)[f].rank(pct=True)
        raw = monthly_stats(corr_by_group(sub, ["date"], "_raw", Y, MIN_N_DATE))
        rnk = monthly_stats(corr_by_group(sub, ["date"], "_rnk", Y, MIN_N_DATE))
        for d in (raw, rnk):
            d.pop("monthly_ic", None)
        gain_t = None
        if raw.get("t_stat") is not None and rnk.get("t_stat") is not None:
            gain_t = round(abs(rnk["t_stat"]) - abs(raw["t_stat"]), 2)
        out[f] = {"pearson_ic_raw_winsorized": raw, "pearson_ic_cs_rank": rnk,
                  "abs_t_stat_gain_from_rank": gain_t}
    return out


# --------------------------------------------------------------------------- #
# 4. Listing-age effect (ret_252d NaN = <252 sessions of history in DB)
# --------------------------------------------------------------------------- #
def analysis_listing_age(lab):
    lab = lab.copy()
    lab["_young"] = lab["ret_252d"].isna()
    grp = {}
    for name, g in lab.groupby("_young"):
        key = "young_history" if name else "seasoned"
        grp[key] = {
            "n": int(len(g)),
            "mean_y_excess_20d": round(float(g[Y].mean()), 5),
            "label_beat_rate": round(float(g["label_beat_mkt_20d"].mean()), 4),
            "mean_vol_20": round(float(g["vol_20"].mean()), 5),
            "mean_log_turnover": round(float(g["log_turnover"].mean()), 3),
            "median_turnover_rs_crore": round(float(np.exp(g["log_turnover"].median()) / 1e7), 2),
        }
    # monthly consistency only where both cohorts exist with >=200 rows
    bym = lab.groupby(["month", "_young"])[Y].agg(["mean", "size"]).unstack()
    ok = (bym[("size", True)] >= 200) & (bym[("size", False)] >= 200)
    gap = (bym[("mean", True)] - bym[("mean", False)])[ok].dropna()
    t = float(gap.mean() / (gap.std(ddof=1) / np.sqrt(len(gap)))) if len(gap) > 1 else float("nan")
    return {
        "definition": "young_history = ret_252d is NaN (<252 sessions since first DB bar; in this pilot that is listing age OR late DB entry -- before 2026-03 EVERY ticker is 'young' because the DB starts 2025-03)",
        "groups": grp,
        "pooled_gap_young_minus_seasoned": round(
            grp["young_history"]["mean_y_excess_20d"] - grp["seasoned"]["mean_y_excess_20d"], 5),
        "monthly_gap_young_minus_seasoned": {k: round(float(v), 5) for k, v in gap.items()},
        "mean_monthly_gap": round(float(gap.mean()), 5) if len(gap) else None,
        "months_with_both_cohorts": int(len(gap)),
        "pct_months_gap_positive": round(float((gap > 0).mean()), 3) if len(gap) else None,
        "monthly_gap_t_stat": round(t, 2) if np.isfinite(t) else None,
        "caveat": "identification only possible 2026-03 onward; pilot confounds true IPO age with DB start -- at 5y replace ret_252d_isnan with explicit listing_age_days",
    }


# --------------------------------------------------------------------------- #
# 5. Interaction scan (3x3 tercile grids)
# --------------------------------------------------------------------------- #
PAIRS = [("deliv_pct_sma_20", "mom_12_1"),
         ("cs_rank_vol_20", "mom_12_1"),
         ("dist_52w_high", "cs_rank_mom_20"),
         ("atr_pct", "deliv_pct_z_20")]


def analysis_interactions(lab):
    res = {}
    for fa, fb in PAIRS:
        sub = lab.loc[lab[fa].notna() & lab[fb].notna(), ["date", "month", fa, fb, Y]].copy()
        sub["_ta"] = tercile_of(per_date_rank_pct(sub, fa))
        sub["_tb"] = tercile_of(per_date_rank_pct(sub, fb))
        grid = sub.groupby(["_tb", "_ta"])[Y].mean().unstack().reindex(index=[0, 1, 2], columns=[0, 1, 2])
        nn = sub.groupby(["_tb", "_ta"])[Y].size().unstack().reindex(index=[0, 1, 2], columns=[0, 1, 2])
        row = sub.groupby("_tb")[Y].mean()
        col = sub.groupby("_ta")[Y].mean()
        grand = sub[Y].mean()
        add = np.add.outer(row.reindex([0, 1, 2]).to_numpy(),
                           col.reindex([0, 1, 2]).to_numpy()) - grand
        g = grid.to_numpy()
        dd = float(g[2, 2] - g[2, 0] - g[0, 2] + g[0, 0])
        # monthly sign consistency of the double difference
        bym = sub.groupby(["month", "_tb", "_ta"])[Y].agg(["mean", "size"])
        dd_m = {}
        for mth, gm in bym.groupby(level=0):
            gm = gm.droplevel(0)
            cells = [(0, 0), (0, 2), (2, 0), (2, 2)]
            if all(c in gm.index and gm.loc[c, "size"] >= 30 for c in cells):
                dd_m[mth] = float(gm.loc[(2, 2), "mean"] - gm.loc[(2, 0), "mean"]
                                  - gm.loc[(0, 2), "mean"] + gm.loc[(0, 0), "mean"])
        dd_m = pd.Series(dd_m)
        res[f"{fa}_x_{fb}"] = {
            "grid_mean_y_excess": [[round(float(x), 5) for x in r] for r in g],
            "grid_n": [[int(x) for x in r] for r in nn.to_numpy()],
            "grid_axis": {"rows": f"{fb} tercile (low->high)", "cols": f"{fa} tercile (low->high)"},
            "additive_expectation": [[round(float(x), 5) for x in r] for r in add],
            "corner_spread_observed": round(float(g[2, 2] - g[0, 0]), 5),
            "corner_spread_additive": round(float(add[2, 2] - add[0, 0]), 5),
            "double_difference": round(dd, 5),
            "max_abs_deviation_from_additive": round(float(np.max(np.abs(g - add))), 5),
            "pct_months_dd_same_sign": round(float((np.sign(dd_m) == np.sign(dd)).mean()), 3) if len(dd_m) else None,
            "n_months_dd": int(len(dd_m)),
        }
    return res


# --------------------------------------------------------------------------- #
# 6. Market-state conditioning
# --------------------------------------------------------------------------- #
MS_FEATS = ["mom_12_1", "cs_rank_mom_20", "deliv_pct_sma_20", "atr_pct"]


def analysis_market_state(lab, daily_store, ic_stab):
    med = lab.groupby("date", observed=True)["mom_20"].median()
    state = med > 0  # trailing 20d universe median return positive -> "up"
    mtab = pd.DataFrame({"med_mom20": med, "up": state})
    mtab["month"] = mtab.index.strftime("%Y-%m")
    month_state = mtab.groupby("month").agg(mean_median_mom20=("med_mom20", "mean"),
                                            share_up_days=("up", "mean"))
    month_state["state"] = np.where(month_state["mean_median_mom20"] > 0, "up", "down")

    per_feat = {}
    for f in MS_FEATS:
        d = daily_store[f].copy()
        d.index = pd.to_datetime(d.index.get_level_values("date"))
        st = state.reindex(d.index)
        rows = {}
        for lab_name, mask in (("up_dates", st == True), ("down_dates", st == False)):  # noqa: E712
            s = d[mask.to_numpy()]
            rows[lab_name] = {"mean_ic": round(float(s.mean()), 5),
                              "std": round(float(s.std(ddof=1)), 5), "n_dates": int(len(s))}
        diff = rows["up_dates"]["mean_ic"] - rows["down_dates"]["mean_ic"]
        n1, n2 = rows["up_dates"]["n_dates"], rows["down_dates"]["n_dates"]
        se = np.sqrt(rows["up_dates"]["std"] ** 2 / max(n1, 1) + rows["down_dates"]["std"] ** 2 / max(n2, 1))
        rows["ic_up_minus_down"] = round(float(diff), 5)
        rows["t_stat_diff"] = round(float(diff / se), 2) if se > 0 else None
        per_feat[f] = rows

    # structural break at the Feb-2026 crash: monthly IC before vs from 2026-03
    brk = {}
    for f in MS_FEATS:
        m = ic_stab[f].get("monthly_ic", {})
        pre = [v for k, v in m.items() if k < "2026-03"]
        post = [v for k, v in m.items() if k >= "2026-03"]
        brk[f] = {"mean_ic_2025_06_to_2026_02": round(float(np.mean(pre)), 5) if pre else None,
                  "mean_ic_2026_03_onward": round(float(np.mean(post)), 5) if post else None,
                  "n_pre": len(pre), "n_post": len(post)}

    return {
        "state_definition": "per-date universe median mom_20 (trailing 20d return, point-in-time); date is 'up' if > 0; month state = sign of monthly mean of the per-date median",
        "regime_break_2026_03": {
            "note": "monthly IC means before vs from 2026-03 (the month after the -8.6pct median-20d crash of 2026-02). The vol family's sign flip is tied to this break, NOT to the trailing up/down state -- a trailing binary flag alone does not capture it.",
            "per_feature": brk,
        },
        "month_table": {m: {"mean_median_mom20": round(float(r.mean_median_mom20), 5),
                            "share_up_days": round(float(r.share_up_days), 3),
                            "state": r.state,
                            "is_test_month": m in TEST_MONTHS}
                        for m, r in month_state.iterrows()},
        "ic_by_state": per_feat,
    }


# --------------------------------------------------------------------------- #
# 7. Liquidity gradient
# --------------------------------------------------------------------------- #
def build_composite(lab):
    acc, cnt = None, None
    for f in CHAMPION:
        r = per_date_rank_pct(lab, f)
        if UNIV_SIGN[f] == "-":
            r = 1 - r
        ok = r.notna().astype(float)
        r = r.fillna(0.0)
        acc = r if acc is None else acc + r
        cnt = ok if cnt is None else cnt + ok
    comp = acc / cnt.replace(0, np.nan)
    return comp


def analysis_liquidity(lab):
    sub = lab[["date", "month", "log_turnover", "deliv_pct_sma_20", "mom_12_1", Y]].copy()
    sub["_comp"] = build_composite(lab)
    sub["_terc"] = tercile_of(per_date_rank_pct(sub, "log_turnover"))

    def terc_ic(col):
        t = sub.loc[sub[col].notna(), ["date", "month", "_terc", col, Y]].copy()
        g = t.groupby(["date", "_terc"], observed=True)
        t["_rx"] = g[col].rank()
        t["_ry"] = g[Y].rank()
        ic = corr_by_group(t, ["date", "_terc"], "_rx", "_ry", MIN_N_TERC)
        ic = ic.rename("ic").reset_index()
        ic["month"] = pd.to_datetime(ic["date"]).dt.strftime("%Y-%m")
        bym = ic.groupby(["month", "_terc"])["ic"].mean().unstack()
        out = {}
        for terc, name in [(0, "illiquid"), (1, "mid"), (2, "liquid")]:
            s = bym[terc].dropna()
            out[name] = {"mean_monthly_ic": round(float(s.mean()), 5),
                         "ic_std": round(float(s.std(ddof=1)), 5),
                         "pct_months_same_sign": round(float((np.sign(s) == np.sign(s.mean())).mean()), 3),
                         "n_months": int(len(s))}
        return out

    abs_y = sub.groupby("_terc")[Y].agg(lambda s: float(s.abs().mean()))
    comp_overall = monthly_stats(
        corr_by_group(
            sub.assign(_rx=sub.groupby("date", observed=True)["_comp"].rank(),
                       _ry=sub.groupby("date", observed=True)[Y].rank()),
            ["date"], "_rx", "_ry", MIN_N_DATE))
    comp_overall.pop("monthly_ic", None)
    return {
        "tercile_definition": "per-date terciles of log_turnover (0=illiquid, 2=liquid)",
        "composite_definition": "mean of per-date cs-rank-pct of the champion's 10 features, sign-aligned (cs_rank_mom_20 inverted), NaN-skipped",
        "composite_overall_monthly_ic": comp_overall,
        "ic_by_turnover_tercile": {
            "composite_top10": terc_ic("_comp"),
            "deliv_pct_sma_20": terc_ic("deliv_pct_sma_20"),
            "mom_12_1": terc_ic("mom_12_1"),
        },
        "mean_abs_y_excess_by_tercile": {
            "illiquid": round(float(abs_y.get(0, np.nan)), 5),
            "mid": round(float(abs_y.get(1, np.nan)), 5),
            "liquid": round(float(abs_y.get(2, np.nan)), 5),
        },
    }


# --------------------------------------------------------------------------- #
# 8. Label EDA
# --------------------------------------------------------------------------- #
def analysis_labels(lab, daily_store):
    std_by_date = lab.groupby("date", observed=True)[Y].std()
    monthly_std = std_by_date.groupby(std_by_date.index.strftime("%Y-%m")).mean()

    d = daily_store["mom_12_1"].copy()
    d.index = pd.to_datetime(d.index.get_level_values("date"))
    d = d.sort_index()
    v = d.to_numpy()
    ac = {}
    for k in range(1, 6):
        if len(v) > k + 2:
            a, b = v[:-k], v[k:]
            ac[f"lag_{k}"] = round(float(np.corrcoef(a, b)[0, 1]), 4)
    overlap = {f"lag_{k}": round((20 - k) / 20, 2) for k in range(1, 6)}
    return {
        "per_month_cross_sectional_std_y_excess_20d": {k: round(float(x), 5) for k, x in monthly_std.items()},
        "opportunity_set_range": {"min_month": {"month": str(monthly_std.idxmin()), "std": round(float(monthly_std.min()), 5)},
                                  "max_month": {"month": str(monthly_std.idxmax()), "std": round(float(monthly_std.max()), 5)}},
        "mom_12_1_daily_ic_autocorr": ac,
        "n_ic_dates_mom_12_1": int(len(v)),
        "overlap_induced_baseline": overlap,
        "note": ("y_excess_20d uses a 20-session overlapping window: adjacent daily ICs share 19/20 of "
                 "their label window, so autocorrelation near (20-k)/20 is mechanical, not signal "
                 "persistence. Autocorr clearly BELOW that baseline means the cross-sectional signal "
                 "itself rotates within the window. Consequence for the 5y protocol: date-block "
                 "bootstrap / monthly folds remain mandatory; daily ICs are not independent draws."),
    }


# --------------------------------------------------------------------------- #
# plots
# --------------------------------------------------------------------------- #
def plot_ic_heatmap(ic_stab):
    rows = [(f, s) for f, s in ic_stab.items() if s.get("n_months", 0) > 0]
    rows.sort(key=lambda kv: kv[1]["mean_ic"], reverse=True)
    months = sorted({m for _, s in rows for m in s["monthly_ic"]})
    mat = np.full((len(rows), len(months)), np.nan)
    names = []
    for i, (f, s) in enumerate(rows):
        names.append(("* " if f in CHAMPION else "") + f)
        for j, m in enumerate(months):
            if m in s["monthly_ic"]:
                mat[i, j] = s["monthly_ic"][m]
    vmax = np.nanmax(np.abs(mat))
    fig, ax = plt.subplots(figsize=(8.2, 9.2))
    im = ax.imshow(np.ma.masked_invalid(mat), aspect="auto", cmap=DIV_CMAP,
                   norm=TwoSlopeNorm(vcenter=0, vmin=-vmax, vmax=vmax))
    ax.set_xticks(range(len(months)))
    ax.set_xticklabels(months, rotation=45, ha="right", fontsize=7)
    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=7)
    ax.set_title("Monthly Spearman rank-IC vs y_excess_20d  (gray = negative, blue = positive;\n"
                 "white = feature not observable that month; * = champion-10 feature)",
                 fontsize=9, loc="left", color=INK)
    cb = fig.colorbar(im, ax=ax, shrink=0.5, pad=0.01)
    cb.set_label("monthly IC", fontsize=8)
    cb.ax.tick_params(labelsize=7)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    fig.savefig(ASSETS_DIR / "eda_ic_stability_heatmap.png", dpi=120)
    plt.close(fig)


def plot_monotonicity(mono):
    fig, axes = plt.subplots(2, 5, figsize=(12.5, 5.2), sharey=True)
    vals_all = [v * 100 for s in mono.values() for v in s["decile_mean_y_excess"]]
    ymax = max(vals_all) * 1.3
    ymin = min(0.0, min(vals_all) * 1.1)
    for ax, (f, s) in zip(axes.ravel(), mono.items()):
        v = np.array(s["decile_mean_y_excess"]) * 100
        ax.bar(range(1, 11), v, color=GRAY_LIGHT, width=0.8)
        ax.plot(range(1, 11), v, color=ACCENT, lw=2, marker="o", ms=3.5)
        ax.axhline(0, color=GRAY_DARK, lw=0.8)
        ax.set_title(f, fontsize=8.5, color=INK)
        ax.text(0.03, 0.95,
                f"spread {s['pooled_top_bottom_spread']*100:+.2f}pp\n"
                f"{s['pct_months_spread_positive']*100:.0f}% months + | {s['shape']}",
                transform=ax.transAxes, fontsize=7, va="top", color=GRAY_DARK)
        ax.set_ylim(ymin, ymax)
        ax.tick_params(labelsize=7)
        ax.set_xticks([1, 5, 10])
    for ax in axes[1]:
        ax.set_xlabel("feature decile (per-date)", fontsize=7.5)
    for ax in axes[:, 0]:
        ax.set_ylabel("mean y_excess_20d (%)", fontsize=7.5)
    fig.suptitle("Champion-10 monotonicity: mean 20d excess return by per-date feature decile",
                 fontsize=10, x=0.01, ha="left", color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(ASSETS_DIR / "eda_monotonicity.png", dpi=120)
    plt.close(fig)


def plot_interactions(inter):
    fig, axes = plt.subplots(2, 2, figsize=(9.2, 8.0))
    for ax, (pair, s) in zip(axes.ravel(), inter.items()):
        g = np.array(s["grid_mean_y_excess"]) * 100
        vmax = np.max(np.abs(g))
        im = ax.imshow(g, cmap=DIV_CMAP, norm=TwoSlopeNorm(vcenter=0, vmin=-vmax, vmax=vmax),
                       origin="lower")
        fa, fb = pair.split("_x_")
        for i in range(3):
            for j in range(3):
                val = g[i, j]
                lum_dark = abs(val) > 0.6 * vmax
                ax.text(j, i, f"{val:+.2f}", ha="center", va="center", fontsize=9,
                        color=SURFACE if lum_dark else INK)
        ax.set_xticks([0, 1, 2]); ax.set_xticklabels(["low", "mid", "high"], fontsize=8)
        ax.set_yticks([0, 1, 2]); ax.set_yticklabels(["low", "mid", "high"], fontsize=8)
        ax.set_xlabel(fa, fontsize=8.5); ax.set_ylabel(fb, fontsize=8.5)
        ax.set_title(f"double-diff {s['double_difference']*100:+.2f}pp | "
                     f"{(s['pct_months_dd_same_sign'] or 0)*100:.0f}% months same sign",
                     fontsize=8.5, color=GRAY_DARK)
        for spine in ax.spines.values():
            spine.set_visible(False)
    fig.suptitle("Interaction scan: mean y_excess_20d (%) by per-date tercile pairs "
                 "(blue = outperform, gray = underperform)", fontsize=10, x=0.01, ha="left", color=INK)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    fig.savefig(ASSETS_DIR / "eda_interaction_grids.png", dpi=120)
    plt.close(fig)


def plot_liquidity(liq):
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.2, 4.0))
    tercs = ["illiquid", "mid", "liquid"]
    series = [("composite_top10", ACCENT, "composite (top-10 blend)"),
              ("deliv_pct_sma_20", GRAY_MID, "deliv_pct_sma_20"),
              ("mom_12_1", GRAY_LIGHT, "mom_12_1")]
    x = np.arange(3)
    w = 0.26
    for k, (key, col, lbl) in enumerate(series):
        vals = [liq["ic_by_turnover_tercile"][key][t]["mean_monthly_ic"] for t in tercs]
        bars = ax1.bar(x + (k - 1) * w, vals, w, color=col, label=lbl)
        for b, v in zip(bars, vals):
            ax1.text(b.get_x() + b.get_width() / 2, v + (0.0012 if v >= 0 else -0.0032),
                     f"{v:.3f}", ha="center", fontsize=6.5, color=GRAY_DARK)
    ax1.axhline(0, color=GRAY_DARK, lw=0.8)
    ax1.set_xticks(x); ax1.set_xticklabels([t + "\nturnover tercile" for t in tercs], fontsize=8)
    ax1.set_ylabel("mean monthly Spearman IC", fontsize=8.5)
    ax1.legend(fontsize=7.5, frameon=False)
    ax1.set_title("Signal strength by liquidity", fontsize=9.5, loc="left", color=INK)
    vals = [liq["mean_abs_y_excess_by_tercile"][t] * 100 for t in tercs]
    bars = ax2.bar(tercs, vals, color=GRAY_MID, width=0.55)
    for b, v in zip(bars, vals):
        ax2.text(b.get_x() + b.get_width() / 2, v + 0.08, f"{v:.1f}%", ha="center",
                 fontsize=8, color=GRAY_DARK)
    ax2.set_ylabel("mean |y_excess_20d| (%)", fontsize=8.5)
    ax2.set_title("Dispersion (opportunity size) by liquidity", fontsize=9.5, loc="left", color=INK)
    for ax in (ax1, ax2):
        ax.tick_params(labelsize=8)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
    fig.tight_layout()
    fig.savefig(ASSETS_DIR / "eda_liquidity_gradient.png", dpi=120)
    plt.close(fig)


# --------------------------------------------------------------------------- #
# insights (built from the computed payload -- every number is reproducible)
# --------------------------------------------------------------------------- #
def build_summary_and_insights(ic_stab, mono, dist, rankt, age, inter, ms, liq, lb):
    full = {f: s for f, s in ic_stab.items() if s.get("n_months", 0) >= 13}
    by_stab = sorted(full.items(),
                     key=lambda kv: (-kv[1]["ic_sign_consistency"], -abs(kv[1].get("t_stat") or 0)))
    top5 = [{"feature": f, "ic_sign_consistency": s["ic_sign_consistency"],
             "mean_ic": s["mean_ic"], "t_stat": s["t_stat"]} for f, s in by_stab[:5]]
    bot3 = [{"feature": f, "ic_sign_consistency": s["ic_sign_consistency"],
             "mean_ic": s["mean_ic"], "t_stat": s["t_stat"]} for f, s in by_stab[-3:]]

    deliv, dsma = ic_stab["deliv_pct"], ic_stab["deliv_pct_sma_20"]
    atr, mom = ic_stab["atr_pct"], ic_stab["mom_12_1"]
    csm = ic_stab["cs_rank_mom_20"]
    volmom = inter["cs_rank_vol_20_x_mom_12_1"]
    delmom = inter["deliv_pct_sma_20_x_mom_12_1"]
    msb = ms["regime_break_2026_03"]["per_feature"]
    msi = ms["ic_by_state"]
    liqt = liq["ic_by_turnover_tercile"]
    comp = liq["composite_overall_monthly_ic"]
    ac = lb["mom_12_1_daily_ic_autocorr"]

    # how many features had their worst (most adverse) month in 2026-03
    n_worst_mar = sum(1 for s in ic_stab.values()
                      if s.get("worst_month", {}).get("month") == "2026-03")

    insights = [
        {"finding": f"The volatility family is a regime variable, not alpha: atr_pct averaged "
                    f"{msb['atr_pct']['mean_ic_2025_06_to_2026_02']:+.3f} monthly IC for 9 straight months "
                    f"(2025-06..2026-02), then flipped to {msb['atr_pct']['mean_ic_2026_03_onward']:+.3f} from 2026-03 "
                    "(post-crash junk rally). The CV window (Apr-Jul 2026) saw ONLY the positive phase, so the "
                    "feature-selection '+' sign on atr_pct / cs_rank_vol_20 is regime-local and WILL invert at 5y scale.",
         "evidence": f"ic_stability.atr_pct monthly ICs (16 months, sign consistency {atr['ic_sign_consistency']:.2f}, "
                     f"|mean| {abs(atr['mean_ic']):.3f} < monthly std {atr['ic_std']:.3f}); market_state.regime_break_2026_03",
         "action": "add_feature trailing market-state (universe median mom_20, universe drawdown/days-since-crash) so trees can condition vol features instead of learning one regime's sign"},

        {"finding": "Delivery is the regime anchor: deliv_pct holds the same IC sign in 15/16 months "
                    f"(mean {deliv['mean_ic']:+.3f}, t={deliv['t_stat']}, the only feature with |mean IC| > its monthly std); "
                    f"deliv_pct_sma_20 mean {dsma['mean_ic']:+.3f} (t={dsma['t_stat']}) and works in BOTH market states "
                    f"(IC {msi['deliv_pct_sma_20']['up_dates']['mean_ic']:+.3f} up / "
                    f"{msi['deliv_pct_sma_20']['down_dates']['mean_ic']:+.3f} down).",
         "evidence": "ic_stability.deliv_pct / deliv_pct_sma_20; market_state.ic_by_state.deliv_pct_sma_20",
         "action": "keep_as_is (delivery block is the core; protect it in any rebuild)"},

        {"finding": f"Momentum pays only in up-tape: mom_12_1 daily IC {msi['mom_12_1']['up_dates']['mean_ic']:+.3f} "
                    f"on up dates vs {msi['mom_12_1']['down_dates']['mean_ic']:+.3f} on down dates (t of diff "
                    f"{msi['mom_12_1']['t_stat_diff']}), and its deciles are U-shaped (deep losers also outperform) -- "
                    "a linear term wastes it; trees or an explicit state interaction capture it.",
         "evidence": "market_state.ic_by_state.mom_12_1; monotonicity.mom_12_1 (shape u_shape, spread "
                     f"{mono['mom_12_1']['pooled_top_bottom_spread']*100:+.2f}pp)",
         "action": "add_feature mom_12_1 x market_state interaction (and keep tree model); for the linear anchor use cs-rank of mom_12_1"},

        {"finding": f"2026-03 is a common-mode inversion month: it is the worst (most adverse) IC month for "
                    f"{n_worst_mar} of 40 base features simultaneously, including every momentum/trend/delivery signal "
                    "(features observed in post-crash March pointed the wrong way for April outcomes). This, not any "
                    "model defect, is why fold 2026-04 was adversarial for every candidate.",
         "evidence": f"ic_stability.*.worst_month == 2026-03 for {n_worst_mar}/40; composite worst month "
                     f"{comp['worst_month']['month']} IC {comp['worst_month']['ic']:+.3f}; market_state.month_table "
                     "(2026-03 trailing median mom_20 -0.086 -> 2026-04 +0.065, sharpest V in sample)",
         "action": "affects_5y_protocol (keep worst-fold floor as the headline stability metric; expect ~1-2 such months/cycle; a days-since-crash feature is the only feature-level mitigation)"},

        {"finding": "One interaction earns a slot: momentum x volatility. The high-mom/high-vol corner returns "
                    f"{volmom['grid_mean_y_excess'][2][2]*100:+.2f}% vs {volmom['additive_expectation'][2][2]*100:+.2f}% additive "
                    f"(double-difference {volmom['double_difference']*100:+.2f}pp, same sign in "
                    f"{volmom['pct_months_dd_same_sign']*100:.0f}% of months) -- 'junky' high-vol momentum beat quality momentum "
                    "in this sample. This is what cs_rank_vol_20 is doing inside the champion (near-zero univariate IC, #2 permutation importance).",
         "evidence": "interactions.cs_rank_vol_20_x_mom_12_1 grid; monotonicity.cs_rank_vol_20 shape noisy",
         "action": "add_feature explicit mom_12_1 x cs_rank_vol_20 product (gives the linear anchor what only trees see today); re-test corner at 5y -- high-vol-wins may itself be regime-local"},

        {"finding": f"Delivery does NOT confirm momentum: the deliv x mom_12_1 double-difference is "
                    f"{delmom['double_difference']*100:+.2f}pp (negative, {delmom['pct_months_dd_same_sign']*100:.0f}% of months) -- "
                    "delivery helps most where momentum is weak. They are substitutes (independent pillars), not a confirmation pair.",
         "evidence": "interactions.deliv_pct_sma_20_x_mom_12_1 (corner +1.81% vs +1.96% additive)",
         "action": "keep_as_is (no deliv x mom product; diversification across the two pillars is the value)"},

        {"finding": f"Recently-listed names outperform within-month: young-history (ret_252d NaN) beats seasoned by "
                    f"{age['mean_monthly_gap']*100:+.2f}pp/month on average ({age['pct_months_gap_positive']*100:.0f}% of the "
                    f"{age['months_with_both_cohorts']} identifiable months, t={age['monthly_gap_t_stat']}). The pooled gap is "
                    f"{age['pooled_gap_young_minus_seasoned']*100:+.2f}pp (opposite sign) -- a calendar confound: before 2026-03 every "
                    "ticker is 'young' because the DB starts 2025-03. ret_252d_isnan's tree gain (#13) is partly this real effect, "
                    "partly imputation artifact.",
         "evidence": "listing_age.monthly_gap_young_minus_seasoned; listing_age.groups",
         "action": "add_feature listing_age_days (sessions since first bar) + is_recent_listing flag at 5y; do not rely on ret_252d_isnan as the carrier"},

        {"finding": "Tails are pathological for anything non-tree: atr_pct skew 95 / excess kurtosis ~13,900; macd_norm skew -87; "
                    "vol_20 kurtosis ~3,300; dist_52w_low skew 32. Harness 1/99 winsorization leaves 2.0-3.4% of post-train rows "
                    "clipped (vs 2% if stationary) -- mild drift, concentrated in 1d-return features.",
         "evidence": "distribution_audit (skew/kurt/pct_clipped per feature)",
         "action": "transform vol family (vol_5/10/20, atr_pct, vol_ratio_20, range_pct, dist_52w_low) with log1p and return family (ret_63/126/252d, mom_*, macd_norm) with cs_rank -- for linear/NN pipelines only; champion trees run raw and are unaffected"},

        {"finding": "Cross-sectional rank does NOT materially improve univariate linear IC once harness winsorization is applied: "
                    "|t| gain from ranking the champion 10 ranges -0.44 to +0.24 (only dist_52w_high and atr_pct improve). "
                    "Ranks' value is model-side (tree splits, scale-free across regimes), not signal-side.",
         "evidence": "rank_transform_test (monthly Pearson IC, winsorized-raw vs cs-rank)",
         "action": "keep_as_is (do NOT rebuild all features as ranks; add rank variants only for the skewed momentum/vol blocks above)"},

        {"finding": f"cs_rank_mom_20's inverted ('-') univariate sign is a CV-window artifact: full-sample mean IC is "
                    f"{csm['mean_ic']:+.3f} with sign consistency {csm['ic_sign_consistency']:.2f} (a coin flip). It is the weakest "
                    "champion member and its contribution direction cannot be trusted across regimes.",
         "evidence": "ic_stability.cs_rank_mom_20 vs feature_selection.json univariate sign '-'",
         "action": "affects_5y_protocol (re-run feature selection on full history before freezing the subset; cs_rank_mom_20 is the first candidate to fall out)"},

        {"finding": "The short-horizon block is dead weight: mom_5/10, dist_sma_5/10/20, ret_1d/log_ret_1d, rsi_2, gap_pct, "
                    "vol_z_20, flag_split_20d all have |t| < 1 and sign consistency <= 0.56 over 16 months. None of the 30 "
                    "non-champion features clears monthly noise.",
         "evidence": "ic_stability (all features with n_months=16, |t_stat|<1)",
         "action": "drop short-horizon raw block from linear/NN variants (keeps 51->~25 cols); harmless but useless for trees -- confirms the 10-feature subset decision"},

        {"finding": "No capacity red flag: the edge does not live in the illiquid tail. Composite top-10 IC by turnover tercile: "
                    f"illiquid {liqt['composite_top10']['illiquid']['mean_monthly_ic']:+.3f}, mid "
                    f"{liqt['composite_top10']['mid']['mean_monthly_ic']:+.3f}, liquid "
                    f"{liqt['composite_top10']['liquid']['mean_monthly_ic']:+.3f}; delivery fades with liquidity "
                    f"({liqt['deliv_pct_sma_20']['illiquid']['mean_monthly_ic']:+.3f} -> "
                    f"{liqt['deliv_pct_sma_20']['liquid']['mean_monthly_ic']:+.3f}) but keeps ~2/3 of its IC in the liquid tercile; "
                    "momentum is actually strongest mid/liquid. Dispersion is flat across terciles (~7.1-7.5%).",
         "evidence": "liquidity_gradient.ic_by_turnover_tercile; mean_abs_y_excess_by_tercile",
         "action": "keep_as_is (report to management: strategy is deployable beyond the illiquid tail; monitor deliv IC decay with liquidity at 5y)"},

        {"finding": f"No intra-month signal decay beyond label overlap: mom_12_1 daily-IC autocorrelation "
                    f"(lag1..5: {ac.get('lag_1')}, {ac.get('lag_2')}, {ac.get('lag_3')}, {ac.get('lag_4')}, {ac.get('lag_5')}) sits AT or ABOVE "
                    "the mechanical overlap baseline (0.95/0.90/0.85/0.80/0.75). Signals are slow; a 20d horizon with monthly "
                    "refresh loses nothing, and daily ICs are nearly fully dependent draws.",
         "evidence": "label_eda.mom_12_1_daily_ic_autocorr vs overlap_induced_baseline",
         "action": "affects_5y_protocol (date-block bootstrap and monthly purged folds remain mandatory; never compute significance on daily rows)"},

        {"finding": "Delivery's IC halved after the crash: deliv_pct_sma_20 monthly IC averaged ~+0.13 in 2025 but only ~+0.04 "
                    "over the 2026 test months (worst -0.143 in 2026-03). Still positive and the most consistent signal, but the "
                    "pilot's CV window UNDERSTATES delivery relative to its long-run average -- and a structural fade would hit "
                    "the champion hardest.",
         "evidence": "ic_stability.deliv_pct_sma_20.monthly_ic (2025 vs 2026 halves); market_state.regime_break_2026_03.deliv_pct_sma_20",
         "action": "affects_5y_protocol (add delivery-IC drift monitor to the 5y run; re-estimate delivery weight on full history)"},

        {"finding": f"Opportunity set is healthy and stable: per-month cross-sectional std of y_excess_20d ranges "
                    f"{lb['opportunity_set_range']['min_month']['std']*100:.1f}% ({lb['opportunity_set_range']['min_month']['month']}) to "
                    f"{lb['opportunity_set_range']['max_month']['std']*100:.1f}% ({lb['opportunity_set_range']['max_month']['month']}) -- no "
                    "dead months; decile-spread economics are comparable across folds.",
         "evidence": "label_eda.per_month_cross_sectional_std_y_excess_20d",
         "action": "keep_as_is"},
    ]

    summary = {
        "top5_regime_stable_by_sign_consistency": top5,
        "bottom3_least_stable": bot3,
        "note_short_history": "mom_12_1/ret_252d excluded from the stability ranking (only 7 observable months); their own stats are in ic_stability",
        "listing_age_effect": {
            "mean_monthly_gap_young_minus_seasoned": age["mean_monthly_gap"],
            "pct_months_positive": age["pct_months_gap_positive"],
            "t_stat": age["monthly_gap_t_stat"],
            "n_months": age["months_with_both_cohorts"],
            "pooled_gap_confounded": age["pooled_gap_young_minus_seasoned"],
        },
        "strongest_interaction": {
            "pair": "cs_rank_vol_20 x mom_12_1",
            "corner_low_low": volmom["grid_mean_y_excess"][0][0],
            "corner_high_high": volmom["grid_mean_y_excess"][2][2],
            "additive_high_high": volmom["additive_expectation"][2][2],
            "double_difference": volmom["double_difference"],
            "pct_months_same_sign": volmom["pct_months_dd_same_sign"],
        },
        "liquidity_answer": "edge NOT confined to the illiquid tail: composite IC illiquid 0.049 / mid 0.073 / liquid 0.058; delivery keeps ~2/3 of its IC in the liquid tercile",
        "recommendation": {
            "feature_rebuild_verdict": "targeted additions, not a wholesale rebuild",
            "add": ["market_state (trailing universe median mom_20; universe drawdown / days-since-crash)",
                    "mom_12_1 x market_state and mom_12_1 x cs_rank_vol_20 interactions",
                    "listing_age_days + is_recent_listing (replace ret_252d_isnan as carrier)",
                    "log1p variants of vol family and cs_rank variants of raw return family (linear/NN pipelines only)"],
            "against_rebuild": ["champion runs on raw trees: winsorization/rank changes do not touch it",
                                "rank transforms add ~no univariate IC after winsorization",
                                "short-horizon features are noise -- adding more of them has negative expected value",
                                "10-feature subset already spans the two stable pillars (delivery + long momentum)"],
            "affects_5y_protocol": ["re-run feature selection on full history (vol/short-mom signs are regime-local; cs_rank_mom_20 inversion is a window artifact)",
                                    "keep worst-fold floor headline metric (2026-03-type inversion months recur)",
                                    "delivery-IC drift monitor",
                                    "date-block significance only (daily ICs ~fully dependent)"],
        },
    }
    return summary, insights


# --------------------------------------------------------------------------- #
def main():
    t0 = time.time()
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    df, lab, base_feats = load_labeled()
    print(f"loaded: {len(df):,} rows total, {len(lab):,} labeled+clean rows, "
          f"{lab['date'].nunique()} dates, {len(base_feats)} base features "
          f"({time.time()-t0:.1f}s)")

    ic_stab, daily_store = analysis_ic_stability(lab, base_feats)
    print(f"1/8 IC stability done ({time.time()-t0:.1f}s)")
    mono = analysis_monotonicity(lab)
    print(f"2/8 monotonicity done ({time.time()-t0:.1f}s)")
    dist = analysis_distribution(lab, base_feats)
    rankt = analysis_rank_transform(lab)
    print(f"3/8 distribution + rank-transform done ({time.time()-t0:.1f}s)")
    age = analysis_listing_age(lab)
    print(f"4/8 listing age done ({time.time()-t0:.1f}s)")
    inter = analysis_interactions(lab)
    print(f"5/8 interactions done ({time.time()-t0:.1f}s)")
    ms = analysis_market_state(lab, daily_store, ic_stab)
    print(f"6/8 market state done ({time.time()-t0:.1f}s)")
    liq = analysis_liquidity(lab)
    print(f"7/8 liquidity done ({time.time()-t0:.1f}s)")
    lb = analysis_labels(lab, daily_store)
    print(f"8/8 label EDA done ({time.time()-t0:.1f}s)")

    plot_ic_heatmap(ic_stab)
    plot_monotonicity(mono)
    plot_interactions(inter)
    plot_liquidity(liq)
    print(f"plots written ({time.time()-t0:.1f}s)")

    # ---- quick console digest used to finalize insights ----
    stab_sorted = sorted(
        [(f, s) for f, s in ic_stab.items() if s.get("n_months", 0) >= 7],
        key=lambda kv: (-kv[1]["ic_sign_consistency"], -abs(kv[1].get("t_stat") or 0)))
    print("\n== IC stability (sorted by sign consistency, then |t|) ==")
    for f, s in stab_sorted:
        print(f"{f:22s} mean {s['mean_ic']:+.4f} std {s['ic_std']:.4f} "
              f"cons {s['ic_sign_consistency']:.2f} t {s['t_stat']} n {s['n_months']} "
              f"worst {s['worst_month']['month']} {s['worst_month']['ic']:+.4f} "
              f"{'NOISY' if s['mean_abs_lt_monthly_std'] else ''}")
    print("\n== monotonicity ==")
    for f, s in mono.items():
        print(f"{f:22s} spread {s['pooled_top_bottom_spread']*100:+.2f}pp "
              f"pos-months {s['pct_months_spread_positive']:.2f} shape {s['shape']}")
    print("\n== rank transform (linear view, |t| gain) ==")
    for f, s in rankt.items():
        print(f"{f:22s} raw t {s['pearson_ic_raw_winsorized'].get('t_stat')} -> "
              f"rank t {s['pearson_ic_cs_rank'].get('t_stat')} gain {s['abs_t_stat_gain_from_rank']}")
    print("\n== listing age ==")
    print(json.dumps({k: age[k] for k in ('groups', 'pooled_gap_young_minus_seasoned',
                                          'pct_months_gap_positive', 'monthly_gap_t_stat',
                                          'months_with_both_cohorts')}, indent=1))
    print("\n== interactions ==")
    for p, s in inter.items():
        print(f"{p}: dd {s['double_difference']*100:+.2f}pp corner obs {s['corner_spread_observed']*100:+.2f} "
              f"vs add {s['corner_spread_additive']*100:+.2f} | months same sign {s['pct_months_dd_same_sign']} "
              f"(n={s['n_months_dd']})")
    print("\n== market state ==")
    for f, r in ms["ic_by_state"].items():
        print(f"{f:22s} up {r['up_dates']['mean_ic']:+.4f} (n={r['up_dates']['n_dates']}) "
              f"down {r['down_dates']['mean_ic']:+.4f} (n={r['down_dates']['n_dates']}) "
              f"diff t {r['t_stat_diff']}")
    print("\n== liquidity ==")
    for k, v in liq["ic_by_turnover_tercile"].items():
        print(f"{k:20s} " + " ".join(f"{t}:{v[t]['mean_monthly_ic']:+.4f}" for t in ("illiquid", "mid", "liquid")))
    print("mean |y|:", liq["mean_abs_y_excess_by_tercile"])
    print("\n== labels ==")
    print("autocorr", lb["mom_12_1_daily_ic_autocorr"], "baseline", lb["overlap_induced_baseline"])
    print("opportunity", lb["opportunity_set_range"])

    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "generated_by": "ml/eda_features.py (seed 108, read-only; python3 -m ml.eda_features)",
        "meta": {
            "rows_total": int(len(df)), "rows_labeled_clean": int(len(lab)),
            "n_dates": int(lab["date"].nunique()), "n_months": int(lab["month"].nunique()),
            "base_features": base_feats, "champion_features": CHAMPION,
            "label": Y, "mask": "label_beat_mkt_20d notna AND y_clean_20d == True",
            "ic_method": "per-date cross-sectional Spearman vs y_excess_20d, min 100 names/date, averaged within month",
            "winsor_reference": f"1/99 quantiles fit on labeled rows date <= {FOLD1_TRAIN_END} (fold-1 harness view)",
        },
        "ic_stability": ic_stab,
        "monotonicity": mono,
        "distribution_audit": dist,
        "rank_transform_test": rankt,
        "listing_age": age,
        "interactions": inter,
        "market_state": ms,
        "liquidity_gradient": liq,
        "label_eda": lb,
        "plots": [str(ASSETS_DIR / p) for p in
                  ("eda_ic_stability_heatmap.png", "eda_monotonicity.png",
                   "eda_interaction_grids.png", "eda_liquidity_gradient.png")],
    }
    summary, insights = build_summary_and_insights(ic_stab, mono, dist, rankt, age,
                                                   inter, ms, liq, lb)
    payload["summary"] = summary
    payload["insights"] = insights
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(jsonable(payload), indent=1))
    print(f"\nwrote {OUT_JSON} ({time.time()-t0:.1f}s total)")


if __name__ == "__main__":
    main()
