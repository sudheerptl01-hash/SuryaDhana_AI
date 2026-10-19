"""Stage 8: execution-realism check — is the t+1 entry bar of gate events locked (high==low)?
A limit-up locked open cannot be bought; a limit-down locked bar can (sellers abundant) but is rare.
Also: share of events whose t+1 open gaps up > 5% (fill-quality risk)."""
import numpy as np
from common import L, OUT, T, load_base, save
t = T()
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
fw = L.Fwd(P)
B = load_base()
U = B["U"]
didx = np.searchsorted(np.unique(B["day"]), B["day"])
brd = np.load(f"{OUT}/brd_day.npy")[didx]
A1 = U & (B["bdd10"] < 0) & (B["volz_20"] > 0) & (B["mkt_mom20"] < 0) & (brd >= 0.05)
A0 = U & (B["bdd20"] < 0) & (B["volz_20"] > 1) & (B["mkt_mom20"] < 0)
h1, l1, o1 = fw.at(P["high"].values, 1), fw.at(P["low"].values, 1), fw.at(P["open"].values, 1)
c0 = P["close"].values
locked = (h1 == l1) & np.isfinite(h1)
out = {}
for nm, m in (("A1", A1), ("A0", A0), ("U", U)):
    v = m & np.isfinite(o1)
    out[nm] = {"n": int(v.sum()), "t1_locked_share": float(locked[v].mean()),
               "t1_locked_up_share": float((locked & (o1 > c0))[v].mean()),
               "t1_gap_up_gt5pct_share": float((o1 / c0 - 1 > 0.05)[v].mean()),
               "t1_gap_dn_gt5pct_share": float((o1 / c0 - 1 < -0.05)[v].mean()),
               "t1_gap_mean_bps": 1e4 * float(np.nanmean(o1[v] / c0[v] - 1))}
save("s8_locks", out)
print(out)
