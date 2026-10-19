"""Stage 1: build all relative / cross-sectional labels for h in {5,10,20}.

Executable window: entry open[t+1] -> exit close[t+h] (L.fwd_return; NaN unless fw.ok(h)).
Market return is measured over the SAME executable window as each stock (Nifty 500 open on the
stock's t+1 date -> close on the stock's t+h date); L.market_fwd (calendar-position version) is
kept for a diagnostic comparison.
Universe U = elig_base & ISIN 'INE*' (equities only; ETFs removed per auditor issue #2).
Labels are NaN wherever the forward window is undefined; filters never change values.
"""
import time

import numpy as np
import pandas as pd

from common import HS, OUT, L, save, universe, xs_rank, tercile_label, dz_label

t0 = time.time()
P = L.load_panel(["date", "entity", "isin", "open", "close", "seg_break", "label_block"])
F = L.load_features(["elig_base", "fno_proxy", "sector", "beta_60", "vol_20"])
fw = L.Fwd(P)
U = universe(P, F)
fno = F["fno_proxy"].values.astype(bool)
dates = P["date"].values.astype("datetime64[D]")
cal = np.unique(dates)
mk = L.market_series("Nifty 500").reindex(pd.DatetimeIndex(cal)).ffill()
mo, mc = mk["open"].values, mk["close"].values
pos = np.searchsorted(cal, dates).astype(float)
beta_c = np.clip(F["beta_60"].values.astype("float64"), 0.0, 3.0)
vol = F["vol_20"].values.astype("float64")
sector = F["sector"].values
known = sector != "NA"
np.savez_compressed(f"{OUT}/meta.npz", U=U, fno=fno, known=known)
print("loaded", round(time.time() - t0, 1), flush=True)

diag = {"U_rows": int(U.sum()), "U_fno_rows": int((U & fno).sum()), "beta_clip": [0.0, 3.0],
        "beta_share_clipped_on_U": float(((F["beta_60"].values[U] < 0) | (F["beta_60"].values[U] > 3)).mean())}
for h in HS:
    r = L.fwd_return(P, fw, h)
    p1, ph = fw.at(pos, 1), fw.at(pos, h)
    okm = np.isfinite(p1) & np.isfinite(ph)
    m = np.full(len(P), np.nan)
    m[okm] = mc[ph[okm].astype(int)] / mo[p1[okm].astype(int)] - 1
    m[np.isnan(r)] = np.nan
    m_cal = L.market_fwd(P, h)
    v = U & np.isfinite(r)
    dd = np.abs(m - m_cal)[v]
    diag[f"h{h}"] = {"valid_U_rows": int(v.sum()), "valid_share_of_U": float(v.sum() / U.sum()),
                     "mkt_window_mismatch_share(>1bp)": float(np.nanmean(dd > 1e-4)),
                     "mkt_window_mismatch_mean_abs_bps": float(np.nanmean(dd) * 1e4)}
    ex = r - m
    br = r - beta_c * m
    # sector-relative: same-date same-sector median of r among U rows (>=5 names), NA -> market-excess
    df = pd.DataFrame({"d": dates, "s": sector, "r": np.where(v & known, r, np.nan)})
    g = df.groupby(["d", "s"]).r
    med = g.transform("median").values
    cnt = g.transform("count").values
    use_sec = v & known & (cnt >= 5)
    sr = np.where(use_sec, r - med, ex)
    sr[np.isnan(r)] = np.nan
    vn = r / (vol * np.sqrt(h))
    vnx = ex / (vol * np.sqrt(h))
    pct = {"raw": xs_rank(r, dates, v), "ex": xs_rank(ex, dates, v), "br": xs_rank(br, dates, v),
           "vn": xs_rank(vn, dates, v), "vnx": xs_rank(vnx, dates, v)}
    diag[f"h{h}"]["spearman_pct_raw_vs_pct_ex"] = float(pd.Series(pct["raw"][v]).corr(pd.Series(pct["ex"][v])))
    diag[f"h{h}"]["share_rows_sector_median_used"] = float(use_sec[v].mean())
    out = {"r": r, "m": m, "ex": ex, "br": br, "sr": sr, "use_sec": use_sec.astype(np.float32)}
    for k_, p_ in pct.items():
        out[f"pct_{k_}"] = p_
    out["ABS_dz"] = dz_label(r)
    out["MX_dz"] = dz_label(ex)
    out["BR_dz"] = dz_label(br)
    out["SR_dz"] = dz_label(sr)
    for k_ in ("raw", "br", "vn", "vnx"):
        for q in (0.3, 0.2, 0.1):
            out[f"XR_{k_}_{int(q * 100)}"] = tercile_label(pct[k_], q)
    np.savez_compressed(f"{OUT}/labels_h{h}.npz", **{k_: np.asarray(a, dtype=np.float32) for k_, a in out.items()})
    print(h, "done", round(time.time() - t0, 1), diag[f"h{h}"], flush=True)
save("s1_label_build", diag)
