#!/usr/bin/env python3
"""Stage 1b: deep-dive on corporate-action defects found in stage 1:
  (1) duplicate Bc records with shifted ex-dates -> factor applied twice
  (2) split/bonus events missing from the Bc archive -> unadjusted jumps
  (3) Bc archive coverage by month
  (4) materiality: feature contamination windows, label windows hit."""
import time

import numpy as np
import pandas as pd

from common import LAB, L, save

t0 = time.time()
cols = ["date", "entity", "symbol", "series", "close", "raw_close", "raw_open", "ca_event", "ca_ratio",
        "label_block", "row_num"]
P = L.load_panel(cols)
F = L.load_features(["elig_base", "fno_proxy"])
n = len(P)
ent = P.entity.values
newent = np.r_[True, ent[1:] != ent[:-1]]
rc, ro, c = P.raw_close.values, P.raw_open.values, P.close.values
ratio = P.ca_ratio.values
lb = P.label_block.values
dates = P.date.values.astype("datetime64[D]")
sym = P.symbol.values
rc_prev = np.r_[np.nan, rc[:-1]]
rc_prev[newent] = np.nan
c_prev = np.r_[np.nan, c[:-1]]
c_prev[newent] = np.nan
ojump = ro / rc_prev          # raw open vs raw prev close
adjj = c / c_prev - 1
eb = F.elig_base.values
fno = F.fno_proxy.values
R = {}

# ---------------- (1) duplicate Bc records ----------------
ev = pd.read_parquet(f"{LAB}/ca_events.parquet")
ev["ex_date"] = pd.to_datetime(ev.ex_date)
ev["ent"] = ent[ev.row.values]
dups = []
for kind in ("shares", "dividend", "rights"):
    e = ev[ev.kind == kind].sort_values(["ent", "desc", "ex_date"])
    same = (e.ent.values[1:] == e.ent.values[:-1]) & (e.desc.values[1:] == e.desc.values[:-1])
    dd = (e.ex_date.values[1:] - e.ex_date.values[:-1]).astype("timedelta64[D]").astype(int)
    hit = same & (dd <= 7) & (dd >= 0)
    a = e.iloc[np.flatnonzero(hit)]
    b = e.iloc[np.flatnonzero(hit) + 1]
    for (ra, rb) in zip(a.itertuples(), b.itertuples()):
        dups.append({"kind": kind, "symbol": ra.symbol, "desc": ra.desc, "ex_date_1": str(ra.ex_date.date()),
                     "ex_date_2": str(rb.ex_date.date()), "row1": int(ra.row), "row2": int(rb.row)})
dups = pd.DataFrame(dups)
R["duplicate_ca_records_within_7d"] = dups.groupby("kind").size().to_dict() if len(dups) else {}
# shares duplicates: is the located row's ratio = factor^2 (double applied)?
sh = ev[ev.kind == "shares"]
dbl = []
if len(dups):
    for r in dups[dups.kind == "shares"].itertuples():
        f = float(sh[(sh.row == r.row1)].factor.iloc[0]) if (sh.row == r.row1).any() else np.nan
        lo, hi = min(r.row1, r.row2) - 3, max(r.row1, r.row2) + 4
        rr = ratio[lo:hi]
        rr = rr[rr != 1.0]
        applied = float(np.prod(rr)) if len(rr) else 1.0
        j = lo + int(np.argmin(np.abs(np.log(ratio[lo:hi]))) if False else 0)
        k = lo + int(np.argmin(ratio[lo:hi]))
        dbl.append({"symbol": r.symbol, "desc": r.desc, "ex1": r.ex_date_1, "ex2": r.ex_date_2, "factor": f,
                    "ratio_applied_in_window": applied, "double_applied": bool(abs(np.log(applied) - 2 * np.log(f)) < 1e-6),
                    "adj_jump_at_row": float(adjj[k]), "label_block_at_row": bool(lb[k]),
                    "fno_proxy": bool(fno[k - 1])})
dbl = pd.DataFrame(dbl)
R["shares_duplicates"] = int(len(dbl))
R["shares_double_applied"] = int(dbl.double_applied.sum()) if len(dbl) else 0
R["shares_double_applied_list"] = dbl[dbl.double_applied].to_dict("records") if len(dbl) else []
# dividends duplicated -> two rows each with ratio<1 (both applied)?
dd_ = dups[dups.kind == "dividend"] if len(dups) else pd.DataFrame()
both = 0
extra_yield = []
for r in dd_.itertuples():
    if r.row1 != r.row2 and ratio[r.row1] < 1 and ratio[r.row2] < 1:
        both += 1
        extra_yield.append(1 - ratio[r.row2])
    elif r.row1 == r.row2 and ratio[r.row1] < 1:
        pass
R["dividend_duplicates"] = int(len(dd_))
R["dividend_duplicates_applied_twice_on_two_rows"] = int(both)
R["dividend_double_extra_yield_median"] = float(np.median(extra_yield)) if extra_yield else None
R["dividend_duplicate_examples"] = dd_.head(8).to_dict("records") if len(dd_) else []

# ---------------- (2) missing split/bonus: big raw open drop, no CA applied within +-3 rows -----
ca_near = np.zeros(n, bool)
cae = P.ca_event.values & (ratio < 0.95)
for k in range(-3, 4):
    sh_ = np.roll(cae, k)
    ca_near |= sh_
FACT = np.array([1 / 2, 1 / 3, 2 / 3, 1 / 4, 3 / 4, 1 / 5, 4 / 5, 5 / 6, 1 / 10, 2 / 5, 3 / 5, 1 / 6, 2 / 7, 5 / 7, 1 / 20])
lj = np.log(ojump)
near_fact = np.zeros(n, bool)
best_f = np.full(n, np.nan)
for f in FACT:
    m = np.abs(lj - np.log(f)) < 0.015
    best_f = np.where(m & np.isnan(best_f), f, best_f)
    near_fact |= m
cand = np.isfinite(lj) & (ojump < 0.86) & near_fact & ~ca_near
# exclude cases that are an exact-looking factor but price did not stay (should persist: close/open stays)
idx = np.flatnonzero(cand)
R["missing_splitlike_open_jumps"] = int(len(idx))
R["missing_splitlike_label_blocked"] = int(lb[idx].sum())
R["missing_splitlike_not_blocked"] = int((~lb[idx]).sum())
R["missing_splitlike_prev_row_elig_base"] = int(eb[np.maximum(idx - 1, 0)].sum())
R["missing_splitlike_prev_row_fno_proxy"] = int(fno[np.maximum(idx - 1, 0)].sum())
tab = pd.DataFrame({"symbol": sym[idx], "date": dates[idx].astype(str), "series": P.series.values[idx],
                    "raw_open_jump": ojump[idx] - 1, "matched_factor": best_f[idx], "adj_close_jump": adjj[idx],
                    "label_block": lb[idx], "prev_elig_base": eb[np.maximum(idx - 1, 0)],
                    "prev_fno": fno[np.maximum(idx - 1, 0)]})
R["missing_splitlike_by_factor"] = tab.matched_factor.round(4).value_counts().to_dict()
R["missing_splitlike_by_year"] = pd.Series(pd.DatetimeIndex(dates[idx]).year).value_counts().sort_index().to_dict()
R["missing_splitlike_list_elig_or_fno"] = tab[tab.prev_elig_base | tab.prev_fno].to_dict("records")
R["missing_splitlike_not_blocked_list"] = tab[~tab.label_block].head(40).to_dict("records")
# feature contamination: elig_base rows within 250 / 60 bars AFTER a missed split or an over-adjusted (double) row
bad = np.zeros(n, bool)
bad[idx] = True
for r in R["shares_double_applied_list"]:
    pass
dbl_rows = []
if len(dbl):
    for r in dbl[dbl.double_applied].itertuples():
        m = (sym == r.symbol) & (dates >= np.datetime64(r.ex1) - np.timedelta64(3, "D")) & \
            (dates <= np.datetime64(r.ex2) + np.timedelta64(3, "D")) & (ratio < 0.95)
        dbl_rows += np.flatnonzero(m).tolist()
bad[dbl_rows] = True
segid = np.cumsum(newent)
for W in (20, 60, 250):
    # rows t such that a bad row lies in (t-W, t] of the same entity
    cs = np.cumsum(bad)
    lo = np.maximum(np.arange(n) - W, 0)
    cnt = cs - cs[lo]
    same = segid[lo] == segid
    # conservative: when the window starts in another entity, count from entity start
    st = np.maximum.accumulate(np.where(newent, np.arange(n), 0))
    cnt2 = cs - np.where(st > 0, cs[np.maximum(st - 1, 0)], 0)
    contaminated = np.where(same, cnt, cnt2) > 0
    R[f"elig_rows_with_bad_jump_in_last_{W}_bars"] = int((contaminated & eb).sum())
    R[f"elig_share_with_bad_jump_in_last_{W}_bars"] = float((contaminated & eb).sum() / eb.sum())
    R[f"fno_rows_with_bad_jump_in_last_{W}_bars"] = int((contaminated & eb & fno).sum())

# ---------------- (3) Bc archive coverage by month ----------------
import ca as CAM  # noqa: E402
bc = CAM.load_bc()
bc["m"] = bc.ex_date.dt.to_period("M").astype(str)
divm = bc[bc.PURPOSE.str.contains("DIV")].groupby("m").size()
allm = bc.groupby("m").size()
R["bc_records_by_month"] = allm.to_dict()
R["bc_div_records_by_month"] = divm.to_dict()
# compare with same month other years: flag months with < 40% of the median of that calendar month
mm = divm.copy()
mm.index = pd.PeriodIndex(mm.index, freq="M")
cal_med = mm.groupby(mm.index.month).median()
low = {str(p): int(v) for p, v in mm.items() if v < 0.4 * cal_med[p.month]}
R["bc_div_months_below_40pct_of_calendar_median"] = low
# Bc files list -> dates with files
import glob, os  # noqa: E401,E402
fl = sorted(os.path.basename(p)[:8] for p in glob.glob(f"{LAB}/raw/bc/*.csv"))
sizes = {os.path.basename(p)[:8]: os.path.getsize(p) for p in glob.glob(f"{LAB}/raw/bc/*.csv")}
R["bc_files"] = len(fl)
R["bc_files_tiny_lt_200B"] = sum(1 for v in sizes.values() if v < 200)
save("s1b_ca_deep", R)
print("done", time.time() - t0, flush=True)
