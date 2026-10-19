"""Stage 10: paired book comparisons. For two scores evaluated with identical Sim settings and phases,
the difference of their phase-averaged daily return series isolates the score difference (the random
baseline cancels). Reports annualised mean difference and Newey-West t (lag 20), DEV and HOLD,
for the long top-20 book (K20 s5 50 bps) and the avoid30 overlay (s5 50 bps).
Pairs: every XR ablation vs XR_all; each ensemble / component vs XR_all; FN / FC vs raw; and the
no-market BAR/TSX models vs their full-feature versions (if present).
"""
import os

import numpy as np
import pandas as pd

from common import OUT, L, H, save


def series(tag, key):
    fn = f"{OUT}/daily_main_{tag}.npz"
    if not os.path.exists(fn):
        return None
    z = np.load(fn, allow_pickle=True)
    return pd.Series(z[f"{key}__strat"], index=pd.DatetimeIndex(z[f"{key}__strat__dates"]))


PAIRS = [(f"XR_no_{g}", "XR_all") for g in ("momentum", "volrisk", "volume", "delivery", "market", "xsrank",
                                               "technical")]
PAIRS += [(t, "XR_all") for t in ("BAR_all", "TSX_all", "ENS3", "ENS_XB", "ENS_XT", "ENS_BT")]
PAIRS += [("XR_all_FN", "XR_all"), ("ENS3_FN", "ENS3"), ("TSX_all_FN", "TSX_all"), ("ENS3_FN", "XR_all"),
          ("TSX_all_FN", "XR_all"), ("XR_all_FC", "XR_all"), ("ENS3_FC", "ENS3"), ("TSX_all_FC", "TSX_all"),
          ("BAR_no_market", "BAR_all"), ("TSX_no_market", "TSX_all"), ("TSX_no_market", "XR_all"),
          ("ENS3_nomkt", "ENS3"), ("ENS3_nomkt", "XR_all"), ("XR_no_market", "XR_all")]
out = {}
for a, b in PAIRS:
    rec = {}
    for book in ("K20_s5_c50", "avoid30_s5_c50"):
        for per in ("dev", "hold"):
            k = f"{book}_{per}"
            sa, sb = series(a, k), series(b, k)
            if sa is None or sb is None:
                continue
            j = pd.concat([sa, sb], axis=1, join="inner").dropna()
            d = j.iloc[:, 0] - j.iloc[:, 1]
            rec[k] = {"diff_ann": float(d.mean() * 252), "nw_t": L.nw_t(d.values, lag=H),
                      "corr_daily": float(j.iloc[:, 0].corr(j.iloc[:, 1])),
                      "diff_by_year": {int(y): float(g.mean() * 252) for y, g in d.groupby(d.index.year)}}
    if rec:
        out[f"{a}__minus__{b}"] = rec
        print(f"{a:16s} - {b:10s}", " | ".join(f"{k}: {v['diff_ann']:+.3f} (t {v['nw_t']:+.2f})" for k, v in rec.items()))
save("s10_paired", out)

# ---------------------------------------------------------------- per-date dIC with NW t on ALL dates
IC_PAIRS = [(f"XR_no_{g}", "XR_all") for g in ("momentum", "volrisk", "volume", "delivery", "market", "xsrank",
                                                  "technical")]
IC_PAIRS += [(t, "XR_all") for t in ("BAR_all", "TSX_all", "ENS3", "ENS_XT", "XR_all_FN", "ENS3_nomkt")]
IC_PAIRS += [("BAR_no_market", "BAR_all"), ("TSX_no_market", "TSX_all"), ("ENS3_nomkt", "ENS3")]
ic_out = {}
for a, b in IC_PAIRS:
    fa, fb = f"{OUT}/xs_daily_{a}.parquet", f"{OUT}/xs_daily_{b}.parquet"
    if not (os.path.exists(fa) and os.path.exists(fb)):
        continue
    j = pd.read_parquet(fb).join(pd.read_parquet(fa), lsuffix="_b", rsuffix="_a", how="inner")
    rec = {}
    for name, (lo, hi) in (("dev", L.DEV), ("hold", ("2026-01-01", "2100-01-01"))):
        sub = j[(j.index >= np.datetime64(lo)) & (j.index <= np.datetime64(hi))]
        for col in ("ic_xr", "ic_raw", "auc_top", "auc_bot"):
            d = (sub[f"{col}_a"] - sub[f"{col}_b"]).dropna()
            dn = d.iloc[::H]
            rec[f"{name}_d_{col}"] = float(d.mean())
            rec[f"{name}_d_{col}_nw_t"] = L.nw_t(d.values, lag=H)
            rec[f"{name}_d_{col}_nonoverlap_t"] = float(dn.mean() / (dn.std(ddof=1) / np.sqrt(len(dn)))) if len(dn) > 3 else None
    yrs = pd.DatetimeIndex(j.index).year
    rec["d_ic_xr_by_year"] = {int(y): float((g["ic_xr_a"] - g["ic_xr_b"]).mean()) for y, g in j.groupby(yrs)}
    ic_out[f"{a}__minus__{b}"] = rec
    print(f"dIC {a:16s}-{b:8s}", " ".join(f"{k}={v:+.4f}" for k, v in rec.items() if isinstance(v, float) and ("ic_xr" in k)),
          {y: round(v, 4) for y, v in rec["d_ic_xr_by_year"].items()})
save("s10_dIC_nw", ic_out)
