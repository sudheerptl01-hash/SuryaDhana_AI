#!/usr/bin/env python3
"""Stage 1: lab validation — entity bridging, corporate actions, discontinuities,
elig_next materiality, index/panel date alignment."""
import time

import numpy as np
import pandas as pd

from common import LAB, L, save

t0 = time.time()
cols = ["date", "entity", "symbol", "isin", "series", "open", "high", "low", "close", "raw_close",
        "raw_open", "prev_close_file", "ca_event", "ca_ratio", "seg_break", "label_block",
        "gap_prev_days", "row_num", "turnover", "adj_factor"]
P = L.load_panel(cols)
n = len(P)
print("loaded", n, time.time() - t0, flush=True)
ent = P.entity.values
newent = np.r_[True, ent[1:] != ent[:-1]]
same_prev = ~newent
rc = P.raw_close.values
ro = P.raw_open.values
c = P.close.values
o = P.open.values
ratio = P.ca_ratio.values
dates = P.date.values.astype("datetime64[D]")
rc_prev = np.r_[np.nan, rc[:-1]]
c_prev = np.r_[np.nan, c[:-1]]
rc_prev[newent] = np.nan
c_prev[newent] = np.nan
raw_jump = rc / rc_prev - 1
adj_jump = c / c_prev - 1
raw_ojump = ro / rc_prev - 1
sym = P.symbol.values
isin = P["isin"].values
gap = P.gap_prev_days.values
rng = np.random.default_rng(42)
OUT = {}

# ----------------------------------------------------------------------------- #
# (a) Entity bridging
# ----------------------------------------------------------------------------- #
sym_change = same_prev & (sym != np.r_[None, sym[:-1]])
isin_change = same_prev & (isin != np.r_[None, isin[:-1]])
ren_rows = np.flatnonzero(sym_change)
isin_rows = np.flatnonzero(isin_change)


def row_info(i):
    return {"entity": ent[i], "date": str(dates[i]), "old_symbol": sym[i - 1], "new_symbol": sym[i],
            "old_isin": isin[i - 1], "new_isin": isin[i], "gap_days": float(gap[i]),
            "raw_close_prev": float(rc[i - 1]), "raw_open": float(ro[i]), "raw_close": float(rc[i]),
            "raw_jump_close": float(raw_jump[i]), "adj_jump_close": float(adj_jump[i]),
            "ca_ratio_row": float(ratio[i]), "label_block_row": bool(P.label_block.values[i])}


# symbol switches that are pure renames (same ISIN) vs ISIN changes
pure_ren = ren_rows[~isin_change[ren_rows]]
ren_tab = pd.DataFrame([row_info(i) for i in pure_ren])
isin_tab = pd.DataFrame([row_info(i) for i in isin_rows])
OUT["rename_switches_total"] = int(len(pure_ren))
OUT["rename_abs_adj_jump_quantiles"] = ren_tab.adj_jump_close.abs().quantile([.5, .9, .99, 1]).to_dict()
OUT["rename_gt20pct_adj_jump"] = int((ren_tab.adj_jump_close.abs() > 0.2).sum())
samp = ren_tab.sample(min(15, len(ren_tab)), random_state=1)
OUT["rename_sample15"] = samp[["date", "old_symbol", "new_symbol", "gap_days", "raw_close_prev", "raw_close",
                               "raw_jump_close", "adj_jump_close"]].to_dict("records")
OUT["isin_change_switches_total"] = int(len(isin_tab))
OUT["isin_change_abs_adj_jump_quantiles"] = isin_tab.adj_jump_close.abs().quantile([.5, .9, .99, 1]).to_dict()
OUT["isin_change_abs_raw_jump_quantiles"] = isin_tab.raw_jump_close.abs().quantile([.5, .9, .99, 1]).to_dict()
OUT["isin_change_gt20pct_adj_jump_n"] = int((isin_tab.adj_jump_close.abs() > 0.2).sum())
OUT["isin_change_gt20pct_adj_jump_list"] = isin_tab[isin_tab.adj_jump_close.abs() > 0.2][
    ["date", "old_symbol", "new_symbol", "old_isin", "new_isin", "gap_days", "raw_jump_close", "adj_jump_close",
     "ca_ratio_row", "label_block_row"]].to_dict("records")
OUT["isin_change_with_raw_jump_gt30pct"] = int((isin_tab.raw_jump_close.abs() > 0.3).sum())
OUT["isin_change_sample10"] = isin_tab.sample(min(10, len(isin_tab)), random_state=2)[
    ["date", "old_symbol", "new_symbol", "old_isin", "new_isin", "gap_days", "raw_jump_close", "adj_jump_close",
     "ca_ratio_row"]].to_dict("records")
# window around isin change: is the CA located within +-3 rows?
near_ca = []
for i in isin_rows:
    lo, hi = max(i - 3, 0), min(i + 4, n)
    m = (ent[lo:hi] == ent[i]) & (ratio[lo:hi] < 0.8)
    near_ca.append(bool(m.any()))
isin_tab["split_bonus_within3"] = near_ca
OUT["isin_change_with_split_bonus_within3rows"] = int(np.sum(near_ca))

# symbol reuse: a symbol that appears under >1 entity
se = P.groupby("symbol").entity.nunique()
reuse = se[se > 1].index.tolist()
reuse_rows = []
for s in reuse:
    sub = P.loc[P.symbol == s, ["entity", "isin", "date", "raw_close"]]
    g = sub.groupby("entity").agg(first=("date", "min"), last=("date", "max"), isin=("isin", "first"),
                                  px_first=("raw_close", "first"), px_last=("raw_close", "last"), n=("date", "size"))
    g = g.sort_values("first")
    recs = g.reset_index().to_dict("records")
    reuse_rows.append({"symbol": s, "n_entities": int(len(g)),
                       "entities": [{k: (str(v)[:10] if k in ("first", "last") else v) for k, v in r.items()}
                                    for r in recs]})
OUT["symbols_under_multiple_entities"] = int(len(reuse))
OUT["symbol_reuse_cases"] = reuse_rows

# possible FRAGMENTS: same issuer code (isin[2:7]) & equity, one entity ends and another starts within 15 days
ent_tab = P.groupby("entity").agg(first=("date", "min"), last=("date", "max"), isin0=("isin", "first"),
                                  isin1=("isin", "last"), sym0=("symbol", "first"), sym1=("symbol", "last"),
                                  px_last=("raw_close", "last"), px_first=("raw_close", "first"))
ent_tab["issuer"] = ent_tab.isin1.str[2:7]
frag = []
for iss, g in ent_tab[ent_tab.isin1.str.startswith("INE")].groupby("issuer"):
    if len(g) < 2:
        continue
    g = g.sort_values("first")
    for a in range(len(g)):
        for b in range(len(g)):
            if a == b:
                continue
            ga, gb = g.iloc[a], g.iloc[b]
            dd = (gb["first"] - ga["last"]).days
            if 0 < dd <= 15:
                frag.append({"issuer": iss, "ended": ga.sym1, "ended_isin": ga.isin1, "end_date": str(ga["last"].date()),
                             "started": gb.sym0, "started_isin": gb.isin0, "start_date": str(gb["first"].date()),
                             "gap_days": dd, "px_ratio": float(gb.px_first / ga.px_last)})
OUT["possible_unbridged_fragments_same_issuer"] = frag
# entity count by start/end inside sample (survivorship / listing)
last_day = P.date.max()
ent_tab["ended_early"] = ent_tab["last"] < last_day - pd.Timedelta(days=20)
OUT["entities_total"] = int(len(ent_tab))
OUT["entities_ending_before_end"] = int(ent_tab.ended_early.sum())
OUT["entities_ending_by_year"] = ent_tab[ent_tab.ended_early].groupby(ent_tab["last"].dt.year).size().to_dict()
save("s1_entity_bridging", OUT)
print("a done", time.time() - t0, flush=True)

# ----------------------------------------------------------------------------- #
# (b) Corporate actions
# ----------------------------------------------------------------------------- #
CA = {}
sb = np.flatnonzero(P.ca_event.values & (ratio < 0.8) & same_prev)
CA["split_bonus_rows_ratio_lt_0_8"] = int(len(sb))
tab = pd.DataFrame({"row": sb, "symbol": sym[sb], "date": dates[sb].astype(str), "ca_ratio": ratio[sb],
                    "raw_close_prev": rc_prev[sb], "raw_open": ro[sb], "raw_close": rc[sb],
                    "raw_open_jump": raw_ojump[sb], "raw_close_jump": raw_jump[sb], "adj_close_jump": adj_jump[sb]})
tab["raw_jump_over_ratio_err"] = np.log((1 + tab.raw_open_jump) / tab.ca_ratio)
CA["split_bonus_sample20"] = tab.sample(20, random_state=3).drop(columns="row").to_dict("records")
CA["split_bonus_adj_abs_jump_quantiles"] = tab.adj_close_jump.abs().quantile([.5, .75, .9, .95, .99, 1]).to_dict()
CA["split_bonus_raw_abs_jump_median"] = float(tab.raw_close_jump.abs().median())
CA["split_bonus_adj_abs_jump_gt15pct"] = int((tab.adj_close_jump.abs() > 0.15).sum())
CA["split_bonus_adj_abs_jump_gt15pct_list"] = tab[tab.adj_close_jump.abs() > 0.15].drop(columns="row").to_dict("records")
# baseline: normal day abs move distribution for comparison
nm = np.isfinite(adj_jump) & ~P.ca_event.values
CA["normal_day_abs_move_quantiles"] = pd.Series(np.abs(adj_jump[nm])).quantile([.5, .9, .99]).to_dict()

ev = pd.read_parquet(f"{LAB}/ca_events.parquet")
dv = ev[ev.kind == "dividend"].copy()
dv["year"] = pd.to_datetime(dv.ex_date).dt.year
drow = P.index[P.ca_event.values & (ratio >= 0.7) & (ratio < 1)]
dy = 1 - ratio[drow]
CA["dividend_events_by_year"] = dv.groupby("year").size().to_dict()
CA["dividend_rows_applied"] = int(len(drow))
CA["dividend_yield_quantiles"] = pd.Series(dy).quantile([.1, .5, .9, .99, 1]).to_dict()
dyy = pd.DataFrame({"y": dy, "yr": pd.DatetimeIndex(dates[drow]).year, "e": ent[drow]})
CA["dividend_yield_sum_per_entity_year_median"] = float(dyy.groupby(["e", "yr"]).y.sum().median())
CA["dividend_yield_gt5pct_rows"] = int((dy > 0.05).sum())
# dividend parse audit: re-read Bc and find dividend-like purposes that produced no dividend event
import ca as CAM  # noqa: E402
bc = CAM.load_bc()
divlike = bc[bc.PURPOSE.str.contains("DIV", regex=False) & ~bc.PURPOSE.str.contains("SUB-DIV|SUBDIV|SUB DIV", regex=True)]
parsed = divlike.PURPOSE.map(lambda p: any(k == "dividend" for k, _ in CAM.classify(p)))
CA["bc_divlike_records"] = int(len(divlike))
CA["bc_divlike_parsed_as_dividend"] = int(parsed.sum())
unp = divlike[~parsed]
CA["bc_divlike_unparsed_examples"] = unp.PURPOSE.value_counts().head(25).to_dict()
# percent-style dividends (unparsed, missing from adjustment)
CA["bc_div_percent_style_unparsed"] = int(unp.PURPOSE.str.contains("%").sum())
# multi-amount dividends (possible FV contamination)
multi = divlike[divlike.PURPOSE.map(lambda p: len(CAM.RE_DIV_AMT.findall(p)) > 1)]
CA["bc_div_multi_amount_records"] = int(len(multi))
CA["bc_div_multi_amount_examples"] = multi.PURPOSE.value_counts().head(15).to_dict()
# rights
rt = ev[ev.kind == "rights"]
rrow = P.index[P.ca_event.values & (ratio > 0.5)]
CA["rights_events_parsed"] = int(len(rt))
CA["rights_purposes_sample"] = rt.purpose.head(10).tolist()
ca_ev = pd.DataFrame({"row": np.flatnonzero(P.ca_event.values)})
# rights factor magnitudes: reconstruct from event rows
rf = []
for r in rt.itertuples():
    rf.append(float(ratio[r.row]) if P.ca_event.values[r.row] else np.nan)
rf = pd.Series(rf)
CA["rights_rows_with_ratio_applied"] = int(rf.notna().sum())
CA["rights_ratio_quantiles"] = rf.dropna().quantile([.1, .5, .9]).to_dict()
# rights with a split/bonus AFTER the rights date on the same symbol: face value from today's EQUITY_L may be stale
later_split = 0
for r in rt.itertuples():
    e_ = ent[r.row]
    msk = (ent == e_) & (ratio < 0.8) & (np.arange(n) > r.row)
    if msk.any():
        later_split += 1
CA["rights_with_later_split_bonus_fv_stale_risk"] = int(later_split)
# label block causes
lb = P.label_block.values
lb_rows = np.flatnonzero(lb)
cause = []
ev_block_rows = set(ev[ev.kind.isin(["block"])].row.tolist())
pcf = P.prev_close_file.values
for i in lb_rows:
    cz = []
    if i in ev_block_rows:
        cz.append("ca_block:" + ";".join(ev[(ev.row == i) & (ev.kind == "block")].purpose.str[:25].tolist()))
    if same_prev[i]:
        lr = np.log(c[i] / c_prev[i]) if c_prev[i] > 0 else np.nan
        if np.isfinite(lr) and abs(lr) > np.log(1.35):
            cz.append("residual_jump>35%")
        if pcf[i] > 0 and abs(pcf[i] - rc_prev[i]) / rc_prev[i] > 0.05:
            cz.append("prevclose_gap>5%")
    if not cz:
        cz.append("other(unlocated split/bonus, rights_unresolved, shares_unknown)")
    cause.append(cz[0].split(":")[0] if cz else "?")
CA["label_block_rows"] = int(len(lb_rows))
CA["label_block_cause_counts"] = pd.Series(cause).value_counts().to_dict()
CA["label_block_by_year"] = pd.Series(pd.DatetimeIndex(dates[lb_rows]).year).value_counts().sort_index().to_dict()
save("s1_corporate_actions", CA)
print("b done", time.time() - t0, flush=True)

# ----------------------------------------------------------------------------- #
# Remaining unexplained discontinuities: adjusted |daily move| > 25%
# ----------------------------------------------------------------------------- #
D = {}
F = L.load_features(["elig_base", "fno_proxy", "elig_series"])
big = np.flatnonzero(np.isfinite(adj_jump) & (np.abs(adj_jump) > 0.25))
D["adj_abs_move_gt25pct_rows"] = int(len(big))
D["of_which_label_block"] = int(lb[big].sum())
ub = big[~lb[big]]
D["not_label_blocked"] = int(len(ub))
D["not_label_blocked_on_elig_base_prev_day"] = int(F.elig_base.values[ub - 1].sum())
# classify
ca_ev_mask = P.ca_event.values
cls = []
for i in ub:
    lo, hi = max(i - 3, 0), min(i + 4, n)
    near_ca = bool(((ent[lo:hi] == ent[i]) & ca_ev_mask[lo:hi]).any())
    post_gap = gap[i] > 5
    early = P.row_num.values[i] < 5
    # reversal: next 5 closes revert more than half of the move
    j = min(i + 5, n - 1)
    rev = np.nan
    if ent[j] == ent[i]:
        rev = (c[j] / c[i] - 1)
    reverts = np.isfinite(rev) and (np.sign(rev) != np.sign(adj_jump[i])) and abs(np.log(1 + rev)) > 0.5 * abs(np.log(1 + adj_jump[i]))
    ser = P.series.values[i]
    if post_gap:
        k = "post_suspension_gap>5d"
    elif early:
        k = "first_5_rows_listing/relisting"
    elif near_ca:
        k = "within_3_rows_of_applied_CA"
    elif reverts:
        k = "reverts_within_5d(data_error?)"
    elif F.fno_proxy.values[i - 1]:
        k = "liquid_top200(no/flex band)"
    elif ser != "EQ":
        k = "BE/BZ_series"
    else:
        k = "other_EQ_genuine_move?"
    cls.append(k)
cls = pd.Series(cls)
D["classification_counts"] = cls.value_counts().to_dict()
D["by_year"] = pd.Series(pd.DatetimeIndex(dates[ub]).year).value_counts().sort_index().to_dict()
D["direction_up_share"] = float((adj_jump[ub] > 0).mean())
smp = rng.choice(len(ub), size=min(25, len(ub)), replace=False)
D["sample25"] = [{"symbol": sym[ub[k]], "date": str(dates[ub[k]]), "series": P.series.values[ub[k]],
                  "adj_jump": float(adj_jump[ub[k]]), "raw_jump": float(raw_jump[ub[k]]),
                  "gap_days": float(gap[ub[k]]), "class": cls.iloc[k]} for k in smp]
# how many elig_base h=10/h=20 valid windows contain such a non-blocked jump
fw = L.Fwd(P)
flag = np.zeros(n, bool)
flag[ub] = True
cs = np.cumsum(flag)
for h in (10, 20):
    j = np.clip(np.arange(n) + h, 0, n - 1)
    contains = (cs[j] - cs) > 0
    okh = fw.ok(h) & F.elig_base.values
    D[f"h{h}_valid_elig_windows_containing_gt25pct_jump"] = int((okh & contains).sum())
    D[f"h{h}_share"] = float((okh & contains).sum() / okh.sum())
save("s1_discontinuities", D)
print("disc done", time.time() - t0, flush=True)

# ----------------------------------------------------------------------------- #
# (e) elig_next materiality (uses whether t+1 trades within 5 days = look-ahead)
# ----------------------------------------------------------------------------- #
E = {}
Fe = L.load_features(["elig_series", "elig_price", "elig_liq2", "elig_seasoned", "elig_unlocked", "elig_next",
                      "elig_atr", "elig_date", "elig_base"])
base_wo_next = (Fe.elig_series & Fe.elig_price & Fe.elig_liq2 & Fe.elig_seasoned & Fe.elig_unlocked
                & Fe.elig_atr & Fe.elig_date).values
excl = base_wo_next & ~Fe.elig_next.values
lastd = dates == dates.max()
E["base_without_next_rows"] = int(base_wo_next.sum())
E["excluded_by_elig_next"] = int(excl.sum())
E["excluded_share"] = float(excl.sum() / base_wo_next.sum())
E["excluded_on_last_panel_date"] = int((excl & lastd).sum())
E["excluded_not_last_date"] = int((excl & ~lastd).sum())
# what happened next for the non-last-date excluded rows
ex2 = np.flatnonzero(excl & ~lastd)
nxt_same = np.r_[ent[1:] == ent[:-1], False]
has_next = nxt_same[ex2]
E["excluded_with_any_later_bar"] = int(has_next.sum())
E["excluded_entity_ends_after_row (delisting/suspension end)"] = int((~has_next).sum())
gaps_next = (dates[ex2[has_next] + 1] - dates[ex2[has_next]]).astype(int)
E["excluded_next_gap_days_quantiles"] = pd.Series(gaps_next).quantile([.1, .5, .9]).to_dict()
r_next = c[ex2[has_next] + 1] / c[ex2[has_next]] - 1
E["excluded_next_bar_return_mean"] = float(np.nanmean(r_next))
E["excluded_next_bar_return_median"] = float(np.nanmedian(r_next))
E["normal_elig_1bar_return_mean"] = float(np.nanmean((np.r_[c[1:], np.nan] / c - 1)[Fe.elig_base.values & nxt_same]))
E["excluded_per_year"] = pd.Series(pd.DatetimeIndex(dates[ex2]).year).value_counts().sort_index().to_dict()
save("s1_elig_next", E)
print("e done", time.time() - t0, flush=True)

# ----------------------------------------------------------------------------- #
# (f) Index / panel date alignment
# ----------------------------------------------------------------------------- #
A = {}
mk = L.market_series("Nifty 500")
vx = L.market_series("India VIX")
pd_dates = pd.DatetimeIndex(np.unique(P.date.values))
A["panel_dates"] = int(len(pd_dates))
A["nifty500_dates"] = int(len(mk))
A["panel_dates_missing_in_nifty500"] = [str(d.date()) for d in pd_dates.difference(mk.index)]
A["nifty500_dates_missing_in_panel"] = [str(d.date()) for d in mk.index.difference(pd_dates)]
A["vix_dates_missing_vs_panel"] = len(pd_dates.difference(vx.index))
A["nifty500_zero_change_days"] = int((mk.close.diff() == 0).sum())
A["nifty500_open_eq_prevclose_days"] = int((mk.open == mk.close.shift()).sum())
A["nifty500_open_missing_or_zero"] = int(((mk.open <= 0) | mk.open.isna()).sum())
# cross-check: median stock daily return vs index return at lags -1,0,+1
r = pd.Series(adj_jump, index=P.date.values)
r = r[np.isfinite(r.values) & F.elig_base.values]
med = r.groupby(level=0).median()
ir = mk.close.pct_change()
j = pd.concat([med.rename("stk"), ir.rename("idx")], axis=1).dropna()
A["corr_median_stock_ret_vs_index_lag0"] = float(j.stk.corr(j.idx))
A["corr_lag_plus1"] = float(j.stk.corr(j.idx.shift(1)))
A["corr_lag_minus1"] = float(j.stk.corr(j.idx.shift(-1)))
# per-day worst mismatch
j["diff"] = (j.stk - j.idx).abs()
A["worst10_days_median_stock_vs_index_absdiff"] = {str(k.date()): float(v) for k, v in j["diff"].nlargest(10).items()}
# index open sanity: index open vs previous close gap distribution
g = (mk.open / mk.close.shift() - 1).dropna()
A["nifty500_open_gap_abs_quantiles"] = g.abs().quantile([.5, .9, .99, 1]).to_dict()
A["nifty500_open_gap_gt3pct_days"] = {str(k.date()): float(v) for k, v in g[g.abs() > 0.03].items()}
# market_fwd on panel dates that are absent from index: ffilled open -> stale values
A["note"] = "market_fwd reindexes the index to panel dates with ffill; dates missing in index get stale OHLC"
# weekend sessions present
wd = pd_dates.dayofweek
A["weekend_sessions"] = [str(d.date()) for d in pd_dates[wd >= 5]]
save("s1_date_alignment", A)
print("all done", time.time() - t0, flush=True)
