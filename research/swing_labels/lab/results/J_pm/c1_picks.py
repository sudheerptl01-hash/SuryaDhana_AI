"""J_pm check 1: who does the selected book buy (liquidity tiers, ADV participation, tiered cost),
and how much do near-identical models disagree (model noise)."""
import sys, json, numpy as np, pandas as pd
LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB); import lablib as L
R = LAB + "/results"
P = L.load_panel(["date", "entity", "turnover"])
F = L.load_features(["elig_base", "elig_liq5", "fno_proxy", "log_turn20", "vol_20"])
mask = F.elig_base.values.astype(bool)
d = P.date.values.astype("datetime64[D]")
cal = np.unique(d); didx = np.searchsorted(cal, d)
# arithmetic 20d mean turnover, PIT (rows t-19..t inside entity)
ent = P.entity.values
to = pd.Series(P.turnover.values.astype("float64"))
adv = to.groupby(ent).transform(lambda s: s.rolling(20, min_periods=15).mean()).values
fno = F.fno_proxy.values.astype(bool); liq5 = F.elig_liq5.values.astype(bool)
vol = F.vol_20.values
order = np.argsort(didx, kind="stable"); b = np.searchsorted(didx[order], np.arange(len(cal) + 1))
def rows_on(g): return order[b[g]:b[g + 1]]
def sig_dates(start, end_exit, h=20, step=5, phase=0):
    g0 = int(np.searchsorted(cal, np.datetime64(start))) + phase
    gl = int(np.searchsorted(cal, np.datetime64(end_exit), side="right")) - 1 - h - 1
    return list(range(g0, gl + 1, step))
def load(path):
    return np.load(path)["score"].astype("float64")
S = {
 "neumom_RANK": load(R + "/R2_rel/wf_h20_neumom_RANK.npz"),
 "neu_RANK": load(R + "/R2_rel/wf_h20_neu_RANK.npz"),
 "neu_T30": load(R + "/R2_rel/wf_h20_neu_T30.npz"),
 "neumom_T30": load(R + "/R2_rel/wf_h20_neumom_T30.npz"),
 "neumom_C20": load(R + "/R2_rel/wf_h20_neumom_C20.npz"),
 "dual_REL": load(R + "/R2_dual/wf_M_REL.npz"),
 "dual_RUP": load(R + "/R2_dual/wf_M_RUP.npz"),
}
out = {}
# tiers: fno_proxy (large/liquid), liq5 & not fno (mid), liq2-only (small)
TIER_COST = {"fno": 30.0, "mid": 50.0, "small": 95.0}  # round-trip bps (TEAM_BRIEF ranges: 25-35 / 35-60 / 60-130)
def comp(rows):
    t_f = fno[rows]; t_m = liq5[rows] & ~fno[rows]; t_s = ~liq5[rows]
    return t_f.mean(), t_m.mean(), t_s.mean()
for win, (st, en) in {"dev": L.DEV, "hold": ("2026-01-01", "2026-10-14")}.items():
    sigs = sig_dates(st, en)
    res = {}
    for name in ["neumom_RANK", "neu_RANK", "neumom_T30"]:
        sc = S[name]; picks = []; uni = []
        for g in sigs:
            c = rows_on(g); c = c[mask[c] & np.isfinite(sc[c])]
            picks.append(c[np.argsort(-sc[c], kind="stable")[:20]]); uni.append(c)
        pk = np.concatenate(picks); un = np.concatenate(uni)
        f, m, s = comp(pk); fu, mu, su = comp(un)
        cost_p = f * TIER_COST["fno"] + m * TIER_COST["mid"] + s * TIER_COST["small"]
        cost_u = fu * TIER_COST["fno"] + mu * TIER_COST["mid"] + su * TIER_COST["small"]
        a = adv[pk]
        part = {}
        for book_cr in [1, 5, 25, 100]:
            pos = book_cr * 1e7 / 80.0          # 4 sleeves x 20 slots
            pr = pos / a
            part[f"Rs{book_cr}cr"] = dict(median_pct_adv=float(np.nanmedian(pr) * 100), p90_pct_adv=float(np.nanpercentile(pr, 90) * 100),
                                          share_gt5pct=float(np.nanmean(pr > 0.05)), share_gt10pct=float(np.nanmean(pr > 0.10)))
        res[name] = dict(n_picks=int(len(pk)), share_fno=float(f), share_mid_liq5=float(m), share_small_liq2only=float(s),
                         universe_share_fno=float(fu), universe_share_mid=float(mu), universe_share_small=float(su),
                         tiered_cost_bps_picks=float(cost_p), tiered_cost_bps_universe=float(cost_u),
                         median_adv_cr=float(np.nanmedian(a) / 1e7), p10_adv_cr=float(np.nanpercentile(a, 10) / 1e7),
                         p25_adv_cr=float(np.nanpercentile(a, 25) / 1e7),
                         capacity=part)
    out[win] = res
# model-noise: per-date spearman + top-20 overlap on dev signal dates
def pair(a, bname, sigs):
    sa, sb = S[a], S[bname]; rhos = []; ov = []
    for g in sigs:
        c = rows_on(g); c = c[mask[c] & np.isfinite(sa[c]) & np.isfinite(sb[c])]
        if len(c) < 50: continue
        ra = pd.Series(sa[c]).rank().values; rb = pd.Series(sb[c]).rank().values
        rhos.append(np.corrcoef(ra, rb)[0, 1])
        ta = set(c[np.argsort(-sa[c], kind="stable")[:20]]); tb = set(c[np.argsort(-sb[c], kind="stable")[:20]])
        ov.append(len(ta & tb) / 20.0)
    return dict(spearman=float(np.mean(rhos)), top20_overlap=float(np.mean(ov)))
sigs = sig_dates(*L.DEV)
out["noise"] = {
 "neu_RANK vs dual_REL (same label, beta clip only)": pair("neu_RANK", "dual_REL", sigs),
 "neu_T30 vs dual_RUP (same label, beta clip only)": pair("neu_T30", "dual_RUP", sigs),
 "neu_RANK vs neumom_RANK (neutraliser +mom)": pair("neu_RANK", "neumom_RANK", sigs),
 "neumom_RANK vs neumom_C20 (loss)": pair("neumom_RANK", "neumom_C20", sigs),
 "neumom_RANK vs neumom_T30 (loss)": pair("neumom_RANK", "neumom_T30", sigs),
}
json.dump(out, open(R + "/J_pm/c1_picks.json", "w"), indent=1)
print(json.dumps(out, indent=1))
