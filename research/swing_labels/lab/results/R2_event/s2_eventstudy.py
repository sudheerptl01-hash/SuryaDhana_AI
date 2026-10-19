"""Stage 2: event study (no model) for the R1 capitulation family and 6 other overreaction events.

Per (event definition, h): n, frequency, P(net50>0), mean net, DATE-MATCHED excess x_h (event minus
same-date U mean) event-weighted and date-weighted, month-cluster t (and quarter-cluster t), for
DEV / HOLDOUT / PRE(2021-22).  Every cell is registered -> Bonferroni over all tests.

R1 family: close < min(low[t-L..t-1]) (L in 10/20/40) & volz_20 > v (v in none/0/0.5/1/2)
           & market filter M in {none, mkt_mom20<0, mkt_dist_sma200<0, brd>=5%, brd>=10%, mom20<0&brd>=5%}
           brd = share of U closing below its prior 20-day low (any volume) that day (PIT at close t).
Others (x market none / mkt_mom20<0):
  CR  crash day       r1 <= -k*vol20[t-1], k in {3,4}, volz_20>1
  GR  gap reclaimed   gap_open <= -m*atr[t-1], m in {1,2}, close>open
  SL  5d loser        xs-rank(mom_5) <= q, q in {1%,3%}
  OS  oversold        rsi_14 < r, r in {20,25}
  LV  52w-low volume  lo52_dist < 0.5% & volz_20 > v, v in {1,2}
  BO  upside blow-off r1 >= +k*vol20[t-1], k in {3,4}, volz_20>1   (AVOID side: expect xs < 0)
"""
import numpy as np
import pandas as pd
from scipy.stats import norm, t as tdist

from common import HS, OUT, EventStudy, T, load_base, month_concentration, save

t = T()
B = load_base()
ES = EventStudy(B)
U = B["U"]
didx = ES.didx
ncal = len(ES.cal)
nU = np.bincount(didx[U], minlength=ncal)
bd20_any = U & (B["bdd20"] < 0)
brd_day = np.bincount(didx[bd20_any], minlength=ncal) / np.maximum(nU, 1)
brd = brd_day[didx]
B["brd"] = brd.astype(np.float32)
np.save(f"{OUT}/brd_day.npy", brd_day)

mm20 = B["mkt_mom20"]
MKT = {"none": np.ones(len(U), bool), "mom20dn": mm20 < 0, "sma200dn": B["mkt_dist_sma200"] < 0,
       "brd5": brd >= 0.05, "brd10": brd >= 0.10, "mom20dn_brd5": (mm20 < 0) & (brd >= 0.05)}
VOL = {"vnone": None, "v0": 0.0, "v0.5": 0.5, "v1": 1.0, "v2": 2.0}
defs = {}
with np.errstate(invalid="ignore"):
    for Lb in (10, 20, 40):
        bd = U & (B[f"bdd{Lb}"] < 0)
        for vn, vz in VOL.items():
            bv = bd if vz is None else bd & (B["volz_20"] > vz)
            for mn, mk in MKT.items():
                defs[f"R1|L{Lb}|{vn}|{mn}"] = ("R1", bv & mk)
    vz = B["volz_20"]
    others = {
        "CR|k3": U & (B["r1"] <= -3 * B["vol20_lag"]) & (vz > 1),
        "CR|k4": U & (B["r1"] <= -4 * B["vol20_lag"]) & (vz > 1),
        "GR|m1": U & (B["gap_open"] <= -1 * B["atr_lag"]) & (B["intraday"] > 0),
        "GR|m2": U & (B["gap_open"] <= -2 * B["atr_lag"]) & (B["intraday"] > 0),
        "SL|q1": U & (B["xr_mom5"] <= 0.01),
        "SL|q3": U & (B["xr_mom5"] <= 0.03),
        "OS|r20": U & (B["rsi_14"] < 20),
        "OS|r25": U & (B["rsi_14"] < 25),
        "LV|v1": U & (B["lo52_dist"] < 0.005) & (vz > 1),
        "LV|v2": U & (B["lo52_dist"] < 0.005) & (vz > 2),
        "BO|k3": U & (B["r1"] >= 3 * B["vol20_lag"]) & (vz > 1),
        "BO|k4": U & (B["r1"] >= 4 * B["vol20_lag"]) & (vz > 1),
    }
    for k, m in others.items():
        for mn in ("none", "mom20dn"):
            defs[f"{k.split('|')[0]}|{k.split('|')[1]}|-|{mn}"] = (k.split("|")[0], m & MKT[mn])
t(f"{len(defs)} definitions")

rows = []
for name, (fam, m) in defs.items():
    for h in HS:
        st = ES.stats(m, h)
        r = {"def": name, "family": fam, "h": h}
        for wn in ("dev", "hold", "pre"):
            o = st.get(wn, {})
            for k in ("n", "event_days", "share_days_with_event", "events_per_event_day", "share_of_U_rows",
                      "p_net_pos", "net_bps", "xs_bps", "xs_t_month", "xs_t_quarter", "months", "p_xs_pos",
                      "xs_dw_bps", "xs_dw_t_month"):
                r[f"{wn}_{k}"] = o.get(k, np.nan)
        rows.append(r)
    if len(rows) % 60 == 0:
        t(f"{len(rows)} cells")
df = pd.DataFrame(rows)
N = len(df)
# Bonferroni (two-sided, 5% family-wise) over every (definition, h) cell tested here
z_b = float(norm.ppf(1 - 0.025 / N))
df["dev_p_t"] = 2 * tdist.sf(np.abs(df["dev_xs_t_month"]), df["dev_months"].clip(lower=2) - 1)
df["bonf_pass_z"] = np.abs(df["dev_xs_t_month"]) > z_b
df["bonf_pass_tdist"] = df["dev_p_t"] < 0.05 / N
df.to_csv(f"{OUT}/s2_grid.csv", index=False)
t("grid done")

# --- detail for anchor (round-1 R1dn) and per-family best cells ---------------------------------
anchor = "R1|L20|v1|mom20dn"
detail = {}


def regime_liq(m, h):
    r = B[f"r{h}"]
    x = B[f"x{h}"]
    W = ES.windows(h)
    out = {}
    for wn in ("dev", "hold"):
        v = m & np.isfinite(r) & W[wn]
        o = {"by_regime": {}, "by_liq": {}, "fno": {}, "liq5": {}}
        for rc, rn in ((0, "bull_up20"), (1, "bull_dn20"), (2, "bear_up20"), (3, "bear_dn20")):
            k = v & (B["reg"] == rc)
            base = U & np.isfinite(r) & W[wn] & (B["reg"] == rc)
            o["by_regime"][rn] = {"n": int(k.sum()), "share_events": float(k.sum() / max(v.sum(), 1)),
                                  "share_U_rows": float(base.sum() / max((U & np.isfinite(r) & W[wn]).sum(), 1)),
                                  "p_net_pos": float((r[k] > 0.005).mean()) if k.any() else None,
                                  "net_bps": 1e4 * float(r[k].mean() - 0.005) if k.any() else None,
                                  "xs_bps": 1e4 * float(x[k].mean()) if k.any() else None}
        for lt in (0, 1, 2):
            k = v & (B["liq"] == lt)
            o["by_liq"][lt] = {"n": int(k.sum()), "share_events": float(k.sum() / max(v.sum(), 1)),
                               "p_net_pos": float((r[k] > 0.005).mean()) if k.any() else None,
                               "net_bps": 1e4 * float(r[k].mean() - 0.005) if k.any() else None,
                               "xs_bps": 1e4 * float(x[k].mean()) if k.any() else None}
        for nm, msk in (("fno", B["fno"]), ("liq5", B["liq5"])):
            for flag in (True, False):
                k = v & (msk == flag)
                o[nm][str(flag)] = {"n": int(k.sum()), "net_bps": 1e4 * float(r[k].mean() - 0.005) if k.any() else None,
                                    "xs_bps": 1e4 * float(x[k].mean()) if k.any() else None}
        out[wn] = o
    return out


def monthly_corr(m, h):
    """corr of monthly event count / monthly P(net>0) / monthly mean xs with Nifty-500 monthly return."""
    import lablib as L
    r = B[f"r{h}"]
    x = B[f"x{h}"]
    v = m & np.isfinite(r)
    mk = L.market_series("Nifty 500")["close"]
    mret = mk.resample("ME").last().pct_change()
    mret.index = mret.index.to_period("M").astype(str)
    mon = pd.Series(ES.day[v].astype("datetime64[M]").astype(str))
    d = pd.DataFrame({"mo": mon.values, "pos": (r[v] > 0.005).astype(float), "x": x[v]})
    g = d.groupby("mo").agg(n=("pos", "size"), pos=("pos", "mean"), x=("x", "mean"))
    allmo = pd.Series(ES.day[U].astype("datetime64[M]").astype(str)).unique()
    cnt = g.n.reindex(allmo).fillna(0)
    j = pd.concat([cnt.rename("n"), g.pos.rename("pos"), g.x.rename("x"), mret.rename("m")], axis=1).dropna(subset=["m"])
    jj = j.dropna()
    jj20 = jj[jj.n >= 20]
    return {"corr_monthly_count_vs_mkt": float(j.n.corr(j.m)),
            "corr_monthly_pnet_vs_mkt": float(jj.pos.corr(jj.m)) if len(jj) > 5 else None,
            "corr_monthly_pnet_vs_mkt_n20": float(jj20.pos.corr(jj20.m)) if len(jj20) > 5 else None,
            "corr_monthly_xs_vs_mkt": float(jj.x.corr(jj.m)) if len(jj) > 5 else None,
            "monthly_pnet_mean": float(jj.pos.mean()), "monthly_pnet_std": float(jj.pos.std()),
            "monthly_pnet_min": float(jj.pos.min()), "monthly_pnet_max": float(jj.pos.max()),
            "months_with_events": int((cnt > 0).sum()), "months_total": int(len(cnt))}


def count_buckets(m, h, wn="dev"):
    """xs by number of same-day events (mass-day dependence)."""
    r, x = B[f"r{h}"], B[f"x{h}"]
    v = m & np.isfinite(r) & ES.windows(h)[wn]
    c = np.bincount(didx[v], minlength=ncal)[didx]
    out = {}
    for lo, hi in ((1, 2), (3, 9), (10, 29), (30, 99), (100, 10 ** 6)):
        k = v & (c >= lo) & (c <= hi)
        out[f"{lo}-{hi if hi < 10 ** 6 else 'inf'}"] = {
            "n": int(k.sum()), "days": int(len(np.unique(didx[k]))),
            "net_bps": 1e4 * float(r[k].mean() - 0.005) if k.any() else None,
            "xs_bps": 1e4 * float(x[k].mean()) if k.any() else None,
            "p_net_pos": float((r[k] > 0.005).mean()) if k.any() else None}
    return out


def brd_buckets(m, h, wn="dev"):
    r, x = B[f"r{h}"], B[f"x{h}"]
    v = m & np.isfinite(r) & ES.windows(h)[wn]
    out = {}
    for lo, hi in ((0, 0.02), (0.02, 0.05), (0.05, 0.10), (0.10, 0.20), (0.20, 1.01)):
        k = v & (brd >= lo) & (brd < hi)
        out[f"{lo:.2f}-{hi:.2f}"] = {"n": int(k.sum()), "days": int(len(np.unique(didx[k]))),
                                     "net_bps": 1e4 * float(r[k].mean() - 0.005) if k.any() else None,
                                     "xs_bps": 1e4 * float(x[k].mean()) if k.any() else None,
                                     "p_net_pos": float((r[k] > 0.005).mean()) if k.any() else None}
    return out


# pre-declared DEV selection rule (written before results were inspected):
#   among R1-family definitions with >= 500 DEV events at h=10, maximise the DEV DATE-WEIGHTED xs
#   month-cluster t (closest to a slot-sized sleeve); report the plateau around it.
r1 = df[(df.family == "R1") & (df.h == 10) & (df.dev_n >= 500)].copy()
r1 = r1.sort_values("dev_xs_dw_t_month", ascending=False)
best_r1 = r1.iloc[0]["def"]
sel = {"rule": "R1 family, h=10, dev_n>=500, max dev date-weighted xs month-cluster t",
       "selected": best_r1, "top10": r1.head(10)[["def", "dev_n", "dev_xs_bps", "dev_xs_t_month", "dev_xs_dw_bps",
                                                   "dev_xs_dw_t_month", "hold_xs_bps", "hold_xs_dw_bps"]].to_dict("records")}
fam_best = {}
for fam in df.family.unique():
    sub = df[(df.family == fam) & (df.dev_n >= 300)]
    if len(sub):
        k = sub.iloc[np.argmax(np.abs(sub.dev_xs_t_month.values))]
        fam_best[fam] = {"def": k["def"], "h": int(k["h"])}
for name in sorted({anchor, best_r1} | {v["def"] for v in fam_best.values()}):
    m = defs[name][1]
    dd = {}
    for h in HS:
        dd[h] = {"stats": ES.stats(m, h, detail=True), "conc_dev": month_concentration(m, h, ES, "dev"),
                 "conc_hold": month_concentration(m, h, ES, "hold"), "regime_liq": regime_liq(m, h),
                 "monthly_corr": monthly_corr(m, h), "count_buckets_dev": count_buckets(m, h, "dev"),
                 "count_buckets_hold": count_buckets(m, h, "hold"), "brd_buckets_dev": brd_buckets(m, h, "dev"),
                 "brd_buckets_hold": brd_buckets(m, h, "hold")}
    detail[name] = dd
    t(f"detail {name}")

# capitulation episodes for the anchor: runs of days with brd>=10% (gap<=5 trading days merges)
heavy = np.flatnonzero(brd_day >= 0.10)
eps = []
if len(heavy):
    s0 = prev = heavy[0]
    for i in heavy[1:]:
        if i - prev > 5:
            eps.append((s0, prev))
            s0 = i
        prev = i
    eps.append((s0, prev))
episodes = [{"start": str(ES.cal[a]), "end": str(ES.cal[b]), "days_brd10": int((brd_day[a:b + 1] >= 0.10).sum()),
             "max_brd": float(brd_day[a:b + 1].max())} for a, b in eps]
ep_years = pd.Series([e["start"][:4] for e in episodes]).value_counts().sort_index().to_dict()

save("s2_eventstudy", {"n_tests": N, "bonferroni_z_two_sided_5pct": z_b,
                       "n_pass_z": int(df.bonf_pass_z.sum()), "n_pass_tdist": int(df.bonf_pass_tdist.sum()),
                       "selection": sel, "family_best": fam_best, "anchor": anchor,
                       "brd_quantiles": {q: float(np.quantile(brd_day[nU > 0], q)) for q in (0.5, 0.75, 0.9, 0.95, 0.99)},
                       "share_days_brd5": float((brd_day[nU > 0] >= 0.05).mean()),
                       "share_days_brd10": float((brd_day[nU > 0] >= 0.10).mean()),
                       "episodes_brd10": episodes, "episodes_by_start_year": ep_years})
save("s2_detail", detail)
print("Bonferroni z", z_b, "tests", N)
cols = ["def", "h", "dev_n", "dev_share_days_with_event", "dev_p_net_pos", "dev_net_bps", "dev_xs_bps", "dev_xs_t_month",
        "dev_xs_dw_bps", "dev_xs_dw_t_month", "hold_n", "hold_net_bps", "hold_xs_bps", "hold_xs_t_month", "bonf_pass_z"]
pd.set_option("display.width", 250)
print(df[df["def"] == anchor][cols].round(3).to_string())
print(r1.head(12)[cols].round(3).to_string())
print(df[df.family != "R1"][cols].round(3).to_string())
t("done")
