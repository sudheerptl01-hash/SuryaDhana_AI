"""J_stat check 5: does the DEV statistic used for selection predict the 2026 holdout across candidates?
Numbers are the phase-averaged values printed in the refiners' reports (R2_rel s7_phase, R2_alpha section 4a)."""
from scipy.stats import spearmanr
rel = {  # name: (DEV PA NW t, DEV PA excess %, 2026 PA excess %)
 "neu_RANK": (3.81, 15.2, 3.3), "neumom_RANK": (4.11, 15.8, 3.9), "neu_T30": (4.26, 19.4, 14.9), "none_RANK": (3.27, 13.8, -7.7),
 "size_RANK": (2.90, 12.7, -1.8), "neu_B30": (0.09, 0.7, -15.2), "neu_C30": (3.61, 14.7, 1.0), "neu_C20": (4.87, 18.1, 10.2),
 "neu_C33": (3.30, 13.6, -0.4), "neu_T20": (3.39, 17.1, 15.9), "neu_T10": (3.01, 17.8, 17.8), "neu_T50": (1.23, 5.9, -7.1),
 "neumom_T30": (4.57, 19.6, 11.6), "neumom_C20": (5.07, 18.5, 8.9)}
alpha = {"BAR": (2.38, 9.1, -7.3), "TSX": (3.18, 11.4, -7.0), "ENS3": (4.37, 15.4, -7.0), "ENS_XB": (3.59, 13.5, -5.5),
         "ENS_XT": (4.21, 15.5, -6.8), "ENS_BT": (3.88, 13.3, -10.3), "XR_no_market": (3.16, 13.3, 9.1), "XR_FN": (3.22, 12.9, 4.7)}
for nm, dset in (("R2_rel h20 forms (14)", rel), ("R2_rel + R2_alpha (22)", {**rel, **alpha})):
    t = [v[0] for v in dset.values()]; e = [v[1] for v in dset.values()]; h = [v[2] for v in dset.values()]
    print(f"{nm}: Spearman(DEV t, 2026 excess) = {spearmanr(t, h)[0]:.2f};  Spearman(DEV excess, 2026 excess) = {spearmanr(e, h)[0]:.2f}")
top = {k: v for k, v in {**rel, **alpha}.items() if v[0] >= 3.5}
t = [v[0] for v in top.values()]; h = [v[2] for v in top.values()]
print(f"only candidates with DEV PA t >= 3.5 ({len(top)}): Spearman(DEV t, 2026) = {spearmanr(t, h)[0]:.2f};  2026 range {min(h)}..{max(h)}")
print(sorted(top.items(), key=lambda kv: -kv[1][0]))
