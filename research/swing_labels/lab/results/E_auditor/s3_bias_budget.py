#!/usr/bin/env python3
"""Stage 3: bias budget at h=10 and h=20 on elig_base.
Each line quantifies one known labeling defect against the lab's bias-free convention."""
import time

import numpy as np
import pandas as pd

from common import L, save

t0 = time.time()
P = L.load_panel(["date", "entity", "symbol", "series", "open", "close", "raw_close", "raw_open", "ca_event",
                  "ca_ratio", "seg_break", "label_block"])
F = L.load_features(["elig_base", "elig_seasoned", "elig_series", "elig_price", "elig_liq2", "elig_unlocked",
                     "elig_next", "elig_atr", "elig_date", "mkt_dist_sma200", "mkt_mom20", "log_turn20", "fno_proxy"])
fw = L.Fwd(P)
n = len(P)
eb = F.elig_base.values
dates = P.date.values.astype("datetime64[D]")
years = pd.DatetimeIndex(dates).year.values
cal = np.unique(dates)
o, c = P.open.values, P.close.values
ro, rc = P.raw_open.values, P.raw_close.values
ent = P.entity.values
print("loaded", time.time() - t0, flush=True)
OUT = {}


def q(x):
    x = x[np.isfinite(x)]
    return {"n": int(len(x)), "mean_bps": float(x.mean() * 1e4), "median_bps": float(np.median(x) * 1e4),
            "p_gt0": float((x > 0).mean()), "p_gt50bps": float((x > 0.005).mean())}


for h in (10, 20):
    R = {}
    ok = fw.ok(h)
    e1 = fw.at(o, 1)
    xh = fw.at(c, h)
    r_o = xh / e1 - 1
    r_c = xh / c - 1
    valid = ok & eb & np.isfinite(r_o) & np.isfinite(r_c)
    # ---- 1. entry convention
    gap = e1 / c - 1
    R["entry"] = {"close_t_entry": q(r_c[valid]), "open_t1_entry": q(r_o[valid]),
                  "overnight_gap_mean_bps": float(np.nanmean(gap[valid]) * 1e4),
                  "label_disagree_sign": float(((r_c[valid] > 0) != (r_o[valid] > 0)).mean()),
                  "label_disagree_50bps": float(((r_c[valid] > 0.005) != (r_o[valid] > 0.005)).mean()),
                  "gap_by_year_bps": pd.Series(gap[valid] * 1e4).groupby(years[valid]).mean().to_dict(),
                  "close_minus_open_entry_mean_by_year_bps":
                      pd.Series((r_c[valid] - r_o[valid]) * 1e4).groupby(years[valid]).mean().to_dict()}
    # ---- 2. unadjusted vs adjusted
    rr = fw.at(rc, h) / fw.at(ro, 1) - 1
    caf = (P.ca_ratio.values != 1.0).astype(int)
    cs = np.cumsum(caf)
    j = np.clip(np.arange(n) + h, 0, n - 1)
    j1 = np.clip(np.arange(n) + 1, 0, n - 1)
    n_ca = cs[j] - cs[j1]        # CA rows in t+2..t+h (after entry open)
    spl = (P.ca_ratio.values < 0.8).astype(int)
    css = np.cumsum(spl)
    n_split = css[j] - css[j1]
    v2 = valid & np.isfinite(rr)
    w_ca = v2 & (n_ca > 0)
    w_sp = v2 & (n_split > 0)
    w_dv = w_ca & (n_split == 0)
    R["unadjusted"] = {
        "valid_windows": int(v2.sum()),
        "windows_with_any_CA": int(w_ca.sum()), "share_with_any_CA": float(w_ca.sum() / v2.sum()),
        "windows_with_split_bonus": int(w_sp.sum()), "share_with_split_bonus": float(w_sp.sum() / v2.sum()),
        "sign_flips_all": int(((rr > 0) != (r_o > 0))[v2].sum()),
        "sign_flips_share_all": float(((rr > 0) != (r_o > 0))[v2].mean()),
        "sign_flips_in_split_windows_share": float(((rr > 0) != (r_o > 0))[w_sp].mean()) if w_sp.any() else None,
        "flip_50bps_label_in_dividend_windows_share": float(((rr > 0.005) != (r_o > 0.005))[w_dv].mean()) if w_dv.any() else None,
        "dividend_window_mean_diff_bps": float(np.mean((r_o - rr)[w_dv]) * 1e4) if w_dv.any() else None,
        "raw_mean_ret_bps": float(np.mean(rr[v2]) * 1e4), "adj_mean_ret_bps": float(np.mean(r_o[v2]) * 1e4),
        "share_ret_lt_-30pct_raw": float((rr[v2] < -0.3).mean()), "share_ret_lt_-30pct_adj": float((r_o[v2] < -0.3).mean()),
        "bottom1pct_raw_share_that_are_split_windows": float(n_split[v2][rr[v2] <= np.quantile(rr[v2], 0.01)].astype(bool).mean()),
        "raw_split_window_mean_ret": float(np.mean(rr[w_sp])) if w_sp.any() else None,
        "adj_split_window_mean_ret": float(np.mean(r_o[w_sp])) if w_sp.any() else None,
    }
    # ---- 3. NaN -> 0
    base = eb.copy()
    e_ok = np.isfinite(e1)
    undefined = base & ~(ok & e_ok)
    last_dates = cal[-h:]
    in_tail = np.isin(dates, last_dates)
    ex_h = fw.exists(h)
    span = fw.span_days(h)
    cap = int(np.ceil(h * 7 / 5)) + 8
    lbclean = (fw.lb_cs[np.clip(np.arange(n) + h, 0, n - 1)] - fw.lb_cs) == 0
    reason = np.where(in_tail, "end_of_data(last h dates)",
              np.where(~ex_h, "entity/segment ends inside window (delist/suspend)",
               np.where(span > cap, "suspension: calendar span > cap",
                np.where(~lbclean, "label_block (demerger/unadjustable CA) in window", "other"))))
    ru = pd.Series(reason[undefined]).value_counts().to_dict()
    # economic outcome of the undefined (non-tail) rows: forced exit at last available close within h
    last = np.full(n, np.nan)
    for k in range(1, h + 1):
        xk = fw.at(c, k)
        last = np.where(np.isnan(xk), last, xk)
    fb = last / e1 - 1
    und_nt = undefined & ~in_tail
    R["nan_to_zero"] = {"elig_rows": int(base.sum()), "undefined_rows": int(undefined.sum()),
                        "undefined_share": float(undefined.sum() / base.sum()),
                        "undefined_excl_end_of_data": int(und_nt.sum()),
                        "undefined_excl_end_share": float(und_nt.sum() / base.sum()),
                        "reasons": ru,
                        "forced_exit_ret_mean_of_undefined_nontail": float(np.nanmean(fb[und_nt])),
                        "forced_exit_ret_median_of_undefined_nontail": float(np.nanmedian(fb[und_nt])),
                        "naive_label0_would_add_false_down_labels_share_of_negatives":
                            float(und_nt.sum() / (valid & (r_o <= 0.005)).sum())}
    # ---- 4. ticker-keyed vs entity-keyed (naive: group by symbol, shift by rows, no segment/span check)
    df = pd.DataFrame({"sym": P.symbol.values, "date": dates, "o": o, "c": c, "row": np.arange(n)})
    df = df.sort_values(["sym", "date"], kind="mergesort")
    g = df.groupby("sym", sort=False)
    no1 = g.o.shift(-1).values
    nch = g.c.shift(-h).values
    naive = np.full(n, np.nan)
    naive[df.row.values] = nch / no1 - 1
    # symbol-keyed seasoning
    sym_age = np.empty(n)
    sym_age[df.row.values] = g.cumcount().values
    ent_def = eb & ok & np.isfinite(r_o)
    nai_def = eb & np.isfinite(naive)
    both = ent_def & nai_def
    diff = both & (np.abs(naive - r_o) > 1e-9)
    R["ticker_vs_entity"] = {
        "entity_defined": int(ent_def.sum()), "ticker_defined": int(nai_def.sum()),
        "ticker_defined_entity_undefined": int((nai_def & ~ent_def).sum()),
        "entity_defined_ticker_undefined(fragments)": int((ent_def & ~nai_def).sum()),
        "both_defined_but_different(splices)": int(diff.sum()),
        "splice_mean_abs_diff": float(np.mean(np.abs(naive - r_o)[diff])) if diff.any() else None,
        "ticker_defined_entity_undefined_mean_ret": float(np.nanmean(naive[nai_def & ~ent_def])),
        "ticker_defined_entity_undefined_share_abs_ret_gt50pct": float((np.abs(naive[nai_def & ~ent_def]) > 0.5).mean()),
        "elig_rows_lost_to_symbol_seasoning_reset": int((eb & (sym_age < 120)).sum()),
    }
    # ---- 5. threshold 0 vs 50 bps
    x = r_o[valid]
    R["threshold"] = {"share_0_to_50bps": float(((x > 0) & (x <= 0.005)).mean()),
                      "share_-50_to_0bps": float(((x <= 0) & (x >= -0.005)).mean()),
                      "flat_share_pm50": float((np.abs(x) <= 0.005).mean()),
                      "flat_share_pm80": float((np.abs(x) <= 0.008).mean()),
                      "p_up_0": float((x > 0).mean()), "p_up_50": float((x > 0.005).mean()),
                      "p_up_80": float((x > 0.008).mean()),
                      "share_up0_that_lose_after_50bps": float(((x > 0) & (x <= 0.005)).sum() / (x > 0).sum())}
    # ---- 6. overlap: autocorrelation of label and N_eff
    y = np.where(valid, (r_o > 0.005).astype(float), np.nan)
    ac = {}
    for k in sorted({1, 2, 3, 5, h // 2, h - 1, h, h + 1, h + 5}):
        yl = fw.at(y, -k)
        m = np.isfinite(y) & np.isfinite(yl)
        ac[k] = float(np.corrcoef(y[m], yl[m])[0, 1])
    acr = {}
    rv = np.where(valid, r_o, np.nan)
    for k in (1, h // 2, h):
        rl = fw.at(rv, -k)
        m = np.isfinite(rv) & np.isfinite(rl)
        acr[k] = float(np.corrcoef(rv[m], rl[m])[0, 1])
    # full sum over lags 1..h-1 (Bartlett / overlapping-window design effect)
    rho = []
    for k in range(1, h + 1):
        yl = fw.at(y, -k)
        m = np.isfinite(y) & np.isfinite(yl)
        rho.append(float(np.corrcoef(y[m], yl[m])[0, 1]))
    de_time = 1 + 2 * np.sum(rho)
    # cross-sectional intra-date correlation (ICC) of the binary label
    dd = pd.DataFrame({"d": dates[valid], "y": y[valid]})
    pm = dd.groupby("d").y.agg(["mean", "size"])
    pbar = dd.y.mean()
    var_between = np.average((pm["mean"] - pbar) ** 2, weights=pm["size"])
    icc = var_between / (pbar * (1 - pbar))
    mbar = pm["size"].mean()
    de_cs = 1 + (mbar - 1) * icc
    N = int(valid.sum())
    R["overlap"] = {"label_autocorr_by_lag": ac, "ret_autocorr_by_lag": acr, "sum_rho_1_to_h": float(np.sum(rho)),
                    "design_effect_time": float(de_time), "N": N, "N_eff_time_only": float(N / de_time),
                    "icc_within_date": float(icc), "mean_names_per_date": float(mbar),
                    "design_effect_cross_section": float(de_cs),
                    "N_eff_time_and_cross_section": float(N / de_time / de_cs),
                    "non_overlapping_market_periods": int(len(np.unique(dates[valid])) / h)}
    # ---- 7. regime: absolute label event report (and market-excess contrast)
    lab = np.where(valid, (r_o > 0.005).astype(float), np.nan)
    rep = L.event_report(lab, valid, P, F, positive=1)
    mf = L.market_fwd(P, h)
    exl = np.where(valid & np.isfinite(mf), ((r_o - mf) > 0.005).astype(float), np.nan)
    rep2 = L.event_report(exl, valid & np.isfinite(mf), P, F, positive=1)
    R["regime_abs_label_gt50bps"] = {k: v for k, v in rep.items() if k != "monthly_pos"}
    R["regime_abs_label_gt50bps"]["monthly_pos"] = {k: v for k, v in rep["monthly_pos"].items() if k != "series"}
    R["regime_excess_label_gt50bps_contrast"] = {"monthly_pos": {k: v for k, v in rep2["monthly_pos"].items() if k != "series"},
                                                 "corr_monthly_pos_vs_mkt_ret": rep2.get("corr_monthly_pos_vs_mkt_ret"),
                                                 "by_year": rep2["by_year"]}
    # ---- 8. survivorship
    last_row = np.r_[ent[1:] != ent[:-1], True]
    ent_last_date = pd.Series(dates).groupby(ent).transform("max").values
    ends_early = ent_last_date < (cal[-1] - np.timedelta64(30, "D"))
    rows_to_end = pd.Series(np.arange(n)).groupby(ent).transform("max").values - np.arange(n)
    final_win = eb & ends_early & (rows_to_end < h) & (rows_to_end >= 1)
    surv_only = eb & ~ends_early
    early = years <= 2023
    R["survivorship"] = {
        "entities_ending_early": int(len(np.unique(ent[ends_early]))),
        "elig_rows_of_entities_ending_early": int((eb & ends_early).sum()),
        "elig_rows_in_final_h_bars_before_exit": int(final_win.sum()),
        "final_window_forced_exit_ret_mean": float(np.nanmean(fb[final_win])) if final_win.any() else None,
        "final_window_forced_exit_ret_median": float(np.nanmedian(fb[final_win])) if final_win.any() else None,
        "final_window_label_defined_share": float((ok & final_win).sum() / max(final_win.sum(), 1)),
        "all_valid_mean_ret_bps_2021_2023": float(np.nanmean(r_o[valid & early]) * 1e4),
        "survivors_only_valid_mean_ret_bps_2021_2023": float(np.nanmean(r_o[valid & early & ~ends_early]) * 1e4),
        "nonsurvivors_valid_mean_ret_bps_2021_2023": float(np.nanmean(r_o[valid & early & ends_early]) * 1e4),
        "p_up50_all_2021_2023": float((r_o[valid & early] > 0.005).mean()),
        "p_up50_survivors_2021_2023": float((r_o[valid & early & ~ends_early] > 0.005).mean()),
    }
    OUT[f"h{h}"] = R
    save(f"s3_bias_budget_h{h}", R)
    print("h", h, "done", time.time() - t0, flush=True)
