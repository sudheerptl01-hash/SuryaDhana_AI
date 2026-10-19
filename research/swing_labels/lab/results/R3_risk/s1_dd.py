"""R3_risk item 1: drawdown anatomy + monthly return distribution of the frozen PROD book,
phase-averaged, contiguous 2023-01-01 -> 2026-10-14 (also DEV / 2026 at 50 and 80 bps).
Saves the daily phase-averaged series to pa_series.npz for the later scripts."""
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab")
import r3common as C  # noqa: E402

OUT = C.set_agent("R3_risk")
P, F, fw, S, E = C.load_sim()
Z = C.load_prod()
prod = Z["prod"]
CONTIG = ("2023-01-01", "2026-10-14")
H = 20

res = {}
ser = {}
for cost in (50, 80):
    kw = dict(C.BASE_KW, cost_bps=cost)
    for name, per in (("dev", "dev"), ("hold", "hold"), ("contig", CONTIG)):
        pa, sm, rm, em = C.phase_avg(S, prod, E, "liq2", H, kw, per, with_ew=True)
        res[f"{name}_c{cost}"] = pa
        C.log(name, cost, C.short({k: v for k, v in pa.items() if not isinstance(v, list)}))
        for tag, x in (("book", sm), ("rand", rm), ("ew", em)):
            ser[f"{name}_c{cost}_{tag}"] = x
C.save("item1_phase_avg", res)

# ---- market series aligned on the contiguous book calendar
n500 = C.market_daily("Nifty 500")
cash = C.market_daily("Nifty 1D Rate Index")
b, r, e = ser["contig_c50_book"], ser["contig_c50_rand"], ser["contig_c50_ew"]
idx = b.index
m = n500.reindex(idx).fillna(0.0)
cs = cash.reindex(idx).fillna(0.0)
np.savez(f"{OUT}/pa_series.npz", **{k: v.values for k, v in ser.items()},
         **{k + "_dates": v.index.values.astype("datetime64[D]").astype(str) for k, v in ser.items()},
         n500=m.values, cash=cs.values, contig_dates=idx.values.astype("datetime64[D]").astype(str))

eqb = (1 + b).cumprod()
eqr, eqe, eqm = (1 + r).cumprod(), (1 + e).cumprod(), (1 + m).cumprod()


def episodes(eq):
    """Non-overlapping peak->trough->recovery drawdown episodes."""
    v = eq.values
    dates = eq.index
    out = []
    peak_i = 0
    i = 1
    n = len(v)
    while i < n:
        if v[i] >= v[peak_i]:
            peak_i = i
            i += 1
            continue
        # in drawdown from peak_i; find recovery
        j = i
        while j < n and v[j] < v[peak_i]:
            j += 1
        seg = v[peak_i:j]
        tr = peak_i + int(np.argmin(seg))
        rec = j if j < n else None
        out.append({"peak": str(dates[peak_i].date()), "trough": str(dates[tr].date()),
                    "recovery": (str(dates[rec].date()) if rec is not None else None),
                    "depth": float(v[tr] / v[peak_i] - 1), "days_peak_to_trough": int(tr - peak_i),
                    "days_peak_to_recovery": (int(rec - peak_i) if rec is not None else None),
                    "days_trough_to_recovery": (int(rec - tr) if rec is not None else None),
                    "_pi": peak_i, "_ti": tr, "_ri": rec})
        peak_i = j if j < n else peak_i
        i = j + 1 if j < n else n
    return out


eps = sorted(episodes(eqb), key=lambda d: d["depth"])[:5]
for ep in eps:
    pi, ti, ri = ep.pop("_pi"), ep.pop("_ti"), ep.pop("_ri")
    for tag, eq in (("nifty500", eqm), ("ew", eqe), ("random", eqr)):
        ep[f"{tag}_peak_to_trough"] = float(eq.iloc[ti] / eq.iloc[pi] - 1)
        # the comparator's own worst drawdown inside the same peak->trough window
        w = eq.iloc[pi:ti + 1]
        ep[f"{tag}_maxdd_in_window"] = float((w / w.cummax() - 1).min())
    ep["excess_vs_random_peak_to_trough"] = ep["depth"] - ep["random_peak_to_trough"]
    ep["excess_vs_ew_peak_to_trough"] = ep["depth"] - ep["ew_peak_to_trough"]
    C.log("DD", C.short(ep))


def dd_stats(eq):
    dd = eq / eq.cummax() - 1
    return {"maxdd": float(dd.min()), "date_of_maxdd": str(dd.idxmin().date()),
            "pct_days_in_dd_gt_10": float((dd < -0.10).mean()), "pct_days_in_dd_gt_20": float((dd < -0.20).mean()),
            "longest_underwater_days": int(max((len(list(g)) for k, g in __import__("itertools").groupby(dd.values < 0) if k),
                                               default=0))}


underwater = {k: dd_stats(eq) for k, eq in (("book", eqb), ("random", eqr), ("ew", eqe), ("nifty500", eqm))}
C.log("underwater", C.short(underwater))

# ---- monthly distribution
def monthly(x):
    return (1 + x).groupby(x.index.to_period("M")).prod() - 1


M = pd.DataFrame({"book": monthly(b), "random": monthly(r), "ew": monthly(e), "nifty500": monthly(m)})
ndays_m = b.groupby(b.index.to_period("M")).size()
first_full = M.index[1] if (idx[0].day > 7) else M.index[0]   # first month is partial (sleeve ramp-up)
Mf = M[(M.index >= first_full) & (ndays_m.reindex(M.index).values >= 8)]   # drop stub months (< 8 trading days)


def dist(s):
    q = s.quantile([0.05, 0.25, 0.5, 0.75, 0.95])
    return {"n_months": int(len(s)), "mean": float(s.mean()), "median": float(q[0.5]), "sd": float(s.std()),
            "min": float(s.min()), "p5": float(q[0.05]), "p25": float(q[0.25]), "p75": float(q[0.75]),
            "p95": float(q[0.95]), "max": float(s.max()), "pct_positive": float((s > 0).mean()),
            "skew": float(s.skew())}


mdist = {k: dist(Mf[k]) for k in Mf.columns}
beat = {}
for per, sub in (("all", Mf), ("dev", Mf[Mf.index.year <= 2025]), ("hold_2026", Mf[Mf.index.year == 2026])):
    beat[per] = {"n_months": int(len(sub)),
                 "pct_months_beat_random": float((sub.book > sub.random).mean()),
                 "pct_months_beat_ew": float((sub.book > sub.ew).mean()),
                 "pct_months_beat_nifty500": float((sub.book > sub.nifty500).mean()),
                 "mean_monthly_excess_vs_random": float((sub.book - sub.random).mean()),
                 "worst_monthly_excess_vs_random": float((sub.book - sub.random).min()),
                 "best_monthly_excess_vs_random": float((sub.book - sub.random).max()),
                 "worst_month_book": float(sub.book.min()), "worst_month_book_date": str(sub.book.idxmin()),
                 "longest_run_months_below_random": int(max((len(list(g)) for k, g in
                                                             __import__("itertools").groupby((sub.book < sub.random).values) if k),
                                                            default=0))}
C.log("monthly", C.short(mdist), C.short(beat))
# conditional: months when Nifty 500 fell > 3% / rose > 3%
cond = {}
for lab, msk in (("n500_down_gt3", Mf.nifty500 < -0.03), ("n500_flat", Mf.nifty500.abs() <= 0.03),
                 ("n500_up_gt3", Mf.nifty500 > 0.03)):
    sub = Mf[msk]
    cond[lab] = {"n_months": int(len(sub)), "book_mean": float(sub.book.mean()), "random_mean": float(sub.random.mean()),
                 "ew_mean": float(sub.ew.mean()), "nifty500_mean": float(sub.nifty500.mean()),
                 "pct_beat_random": float((sub.book > sub.random).mean())}
C.log("conditional", C.short(cond))

# monthly histogram bins for the chart
bins = np.arange(-0.20, 0.2501, 0.025)
hb = np.histogram(np.clip(Mf.book.values, -0.1999, 0.2499), bins=bins)[0]
he = np.histogram(np.clip(Mf.ew.values, -0.1999, 0.2499), bins=bins)[0]
hm = np.histogram(np.clip(Mf.nifty500.values, -0.1999, 0.2499), bins=bins)[0]
C.save("item1_drawdowns", {
    "window": [str(idx[0].date()), str(idx[-1].date())], "n_days": int(len(idx)),
    "top5": eps, "underwater": underwater,
    "monthly_dist": mdist, "monthly_beat": beat, "monthly_conditional_on_market": cond,
    "monthly_first_month_used": str(first_full), "monthly_last_month_used": str(Mf.index[-1]),
    "monthly_hist": {"bin_left": bins[:-1].tolist(), "book": hb.tolist(), "ew": he.tolist(), "nifty500": hm.tolist()},
    "monthly_table": {str(k): {c: float(Mf.loc[k, c]) for c in Mf.columns} for k in Mf.index},
    "notes": ["Nifty 500 is a price index (no dividends, ~1.2%/yr); book/EW/random use CA-adjusted prices incl. dividends.",
              "First calendar month is partial and the 4 sleeves ramp up over the first 15 trading days; it is excluded "
              "from the monthly statistics when the series starts after the 7th."]})
C.log("done")
