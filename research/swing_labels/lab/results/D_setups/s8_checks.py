"""Stage 8: leak / artefact checks on the winning setup R1 (S1_bd20 bought) and R1dn (R1 & mkt_mom20<0).

1. Data-artefact exposure: R1 events whose signal row is a label_block row, a CA row, or has an
   adjusted 1-day move < -20% (possible bad print that reverts) -> edge with/without them.
2. Concentration: edge excluding the heaviest capitulation days (>=100 R1 events) and excluding
   2026-03; number of distinct capitulation episodes.
3. Liquidity / shortability split: F&O-proxy names vs the rest; liquidity tercile.
4. Sector-snapshot composition: share of R1 events with known sector vs universe (leak exposure).
"""
import numpy as np
import pandas as pd

from common import L, OUT, DEV_END, load_base, save, T

t = T()
B = load_base()
names = list(B["setup_names"])
U = B["U"]
P = L.load_panel(["date", "entity", "close", "seg_break", "label_block", "ca_event"])
fw = L.Fwd(P)
dates = P["date"].values.astype("datetime64[D]")
lab = B["lab_L"].astype("float64")
ret = B["ret_L"].astype("float64")
okL = U & ~np.isnan(lab)
dser = pd.Series(dates)
x_ret = ret - pd.Series(np.where(okL, ret, np.nan)).groupby(dser).transform("mean").values
r1d = P["close"].values / fw.at(P["close"].values, -1) - 1
dev = (dates >= np.datetime64("2023-01-01")) & (dates <= np.datetime64(DEV_END))
hold = dates >= np.datetime64("2026-01-01")
R1 = B["setups"][:, names.index("S1_bd20")] & U
R1dn = R1 & (B["mkt_mom20"] < 0)
cnt = pd.Series(R1.astype(int)).groupby(dser).transform("sum").values
sec_known = L.load_features(["sector"])["sector"].values != "NA"
res = {}


def st(m):
    m = m & okL
    if m.sum() == 0:
        return {"n": 0}
    return {"n": int(m.sum()), "P+1": float((lab[m] == 1).mean()), "net50_bps": 1e4 * (ret[m].mean() - 0.005),
            "xs_bps": 1e4 * x_ret[m].mean()}


art = P["label_block"].values | P["ca_event"].values | (r1d < -0.20)
for nm, m0 in (("R1", R1), ("R1dn", R1dn)):
    o = {}
    for per, pm in (("dev", dev), ("hold", hold)):
        o[per] = {"all": st(m0 & pm), "artefact_rows": st(m0 & pm & art), "excl_artefacts": st(m0 & pm & ~art),
                  "excl_days_ge100_events": st(m0 & pm & (cnt < 100)),
                  "only_days_ge30_events": st(m0 & pm & (cnt >= 30)),
                  "only_days_lt30_events": st(m0 & pm & (cnt < 30)),
                  "fno_proxy": st(m0 & pm & B["fno"]), "non_fno": st(m0 & pm & ~B["fno"]),
                  "sector_known": st(m0 & pm & sec_known), "sector_NA": st(m0 & pm & ~sec_known),
                  "universe_sector_known": st(pm & U & sec_known), "universe_sector_NA": st(pm & U & ~sec_known),
                  "share_events_sector_known": float((m0 & pm & okL & sec_known).sum() / max((m0 & pm & okL).sum(), 1)),
                  "share_universe_sector_known": float((pm & okL & sec_known).sum() / max((pm & okL).sum(), 1))}
        for lt in (0, 1, 2):
            o[per][f"liq_tercile_{lt}"] = st(m0 & pm & (B["liq"] == lt))
    o["hold"]["excl_2026_03"] = st(m0 & hold & ~((dates >= np.datetime64("2026-03-01")) & (dates < np.datetime64("2026-04-01"))))
    res[nm] = o
    print(nm)
    for per in ("dev", "hold"):
        print(" ", per, pd.DataFrame({k: v for k, v in o[per].items() if isinstance(v, dict)}).T.round(3).to_string())

# capitulation episodes: runs of trading days with >= 30 R1 events (gap <= 5 trading days merges)
cal = np.unique(dates[U])
dc = pd.Series(R1.astype(int)).groupby(dser).sum().reindex(cal).fillna(0).values
heavy = np.flatnonzero(dc >= 30)
eps = []
if len(heavy):
    s0 = heavy[0]
    prev = heavy[0]
    for i in heavy[1:]:
        if i - prev > 5:
            eps.append((s0, prev))
            s0 = i
        prev = i
    eps.append((s0, prev))
res["capitulation_episodes"] = [{"start": str(cal[a]), "end": str(cal[b]), "days_ge30": int(((dc[a:b + 1]) >= 30).sum()),
                                 "max_events_day": int(dc[a:b + 1].max())} for a, b in eps]
res["n_episodes"] = len(eps)
res["n_episodes_by_year"] = pd.Series([str(cal[a])[:4] for a, _ in eps]).value_counts().sort_index().to_dict()
print("episodes", len(eps), res["n_episodes_by_year"])
for e in res["capitulation_episodes"]:
    print(e)
save("s8_checks", res)
t("done")
