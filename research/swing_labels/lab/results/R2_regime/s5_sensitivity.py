"""Stage 5: parameter-sensitivity map for the simple rules + break-even accuracy of a timer.

(a) Threshold grid (sleeve gating, EW and XR20 books, x_off 0 and 0.5, 50 bps, phase-averaged):
      breadth50 > {0.35,0.40,0.45,0.50,0.55,0.60,0.65}
      mkt_mom60 > {-0.04,-0.02,0,+0.02,+0.04}
      mkt_dist_sma200 > {-0.04,-0.02,0,+0.02,+0.04}
      vix_rel < {-0.20,-0.10,0,+0.10,+0.20}
      hysteresis: breadth on >0.55 / off <0.45 ; 200dma on >+1% / off <-1%
    Reported for PRE / DEV / HOLD: risk-on share (the 'event rate' of a timing rule), flips/yr,
    dCAGR, dSharpe_xs (vs always-in = vs static mix, since static de-risking is Sharpe-neutral), dMaxDD.
(b) Noisy-oracle break-even: state = 1{EW f20 > 0} flipped in random 10-day blocks with prob 1-a,
    a in {0.5..1.0}; 50 draws each; EW book DEV; sleeve gating (x_off 0) and daily overlay (50 bps).
"""
import pickle
import time

import numpy as np
import pandas as pd

from common import OUT, save, compose, metrics, CASH

t0 = time.time()
with open(f"{OUT}/paths_cache.pkl", "rb") as fh:
    cache = pickle.load(fh)
D = pd.read_parquet(f"{OUT}/dateset.parquet")
cal = D.index.values.astype("datetime64[D]")
cd = (1 + CASH) ** (1 / 252) - 1


def xmap(state, x_off):
    st = np.asarray(state, float)
    return np.where(np.isfinite(st), x_off + (1 - x_off) * st, 1.0)


def thr(feat, k, above=True):
    v = D[feat].values.astype(float)
    return np.where(np.isfinite(v), ((v > k) if above else (v < k)).astype(float), np.nan)


def hyst(feat, on_k, off_k):
    v = D[feat].values.astype(float)
    st = np.full(len(v), np.nan)
    cur = np.nan
    for i, x in enumerate(v):
        if not np.isfinite(x):
            continue
        if not np.isfinite(cur):
            cur = 1.0 if x > (on_k + off_k) / 2 else 0.0
        elif cur == 1.0 and x < off_k:
            cur = 0.0
        elif cur == 0.0 and x > on_k:
            cur = 1.0
        st[i] = cur
    return st


GRID = {}
for k in (0.35, 0.40, 0.45, 0.50, 0.55, 0.60, 0.65):
    GRID[f"breadth50>{k:.2f}"] = ("breadth", k, thr("breadth50", k))
for k in (-0.04, -0.02, 0.0, 0.02, 0.04):
    GRID[f"mom60>{k:+.2f}"] = ("mom60", k, thr("mkt_mom60", k))
    GRID[f"dma200>{k:+.2f}"] = ("dma200", k, thr("mkt_dist_sma200", k))
for k in (-0.20, -0.10, 0.0, 0.10, 0.20):
    GRID[f"vix_rel<{k:+.2f}"] = ("vix", k, thr("vix_rel", k, above=False))
GRID["breadth_hyst_0.55/0.45"] = ("breadth_hyst", 0.5, hyst("breadth50", 0.55, 0.45))
GRID["dma200_hyst_+1%/-1%"] = ("dma200_hyst", 0.0, hyst("mkt_dist_sma200", 0.01, -0.01))

WINS = {"PRE": ("2021-09-01", "2022-12-31"), "DEV": ("2023-01-01", "2025-12-31"), "HOLD": ("2026-01-01", "2026-12-31")}
rows = []
for name, (fam, k, st) in GRID.items():
    for book in ("EW", "XR20"):
        for wname in ("PRE", "DEV", "HOLD"):
            if book == "XR20" and wname == "PRE":
                continue
            a, b = WINS[wname]
            wm = (cal >= np.datetime64(a)) & (cal <= np.datetime64(b)) & np.isfinite(st)
            on_share = float(np.mean(st[wm])) if wm.any() else np.nan
            yrs = (cal[wm][-1] - cal[wm][0]).astype(int) / 365.25 if wm.sum() > 1 else np.nan
            flips = float((np.abs(np.diff(st[wm])) > 0).sum() / yrs) if wm.sum() > 1 else np.nan
            for x_off in (0.0, 0.5):
                acc = []
                for ph in range(5):
                    pp = cache[(book, wname, 50, ph)]
                    eq0, r0, inv0, _ = compose(pp)
                    m0 = metrics(eq0, r0, pp["dates"], inv0)
                    eq, r, inv, xs = compose(pp, x_by_g=xmap(st, x_off))
                    m = metrics(eq, r, pp["dates"], inv, xs)
                    acc.append((m["cagr"] - m0["cagr"], m["sharpe_xs"] - m0["sharpe_xs"], m["max_dd"] - m0["max_dd"],
                                m["cagr"], m["sharpe_xs"], m["max_dd"], m.get("switches_per_yr", np.nan), m["exposure"]))
                A = np.array(acc).mean(0)
                rows.append({"rule": name, "family": fam, "k": k, "book": book, "window": wname, "x_off": x_off,
                             "on_share": on_share, "flips_per_yr": flips, "d_cagr": A[0], "d_sharpe_xs": A[1],
                             "d_maxdd": A[2], "cagr": A[3], "sharpe_xs": A[4], "max_dd": A[5],
                             "gate_switches_per_yr": A[6], "exposure": A[7]})
    print(name, round(time.time() - t0, 1), flush=True)
G = pd.DataFrame(rows)
G.to_pickle(f"{OUT}/sensitivity.pkl")
save("s5_sensitivity", G.to_dict(orient="records"))

# ------------------------------------------------------------------ (b) noisy-oracle break-even
rng = np.random.default_rng(2024)
orc = np.where(np.isfinite(D.ew_f20), (D.ew_f20 > 0).astype(float), np.nan)
nC = len(cal)
blk = np.arange(nC) // 10
nb = blk.max() + 1
be = []
for acc_ in (0.5, 0.55, 0.6, 0.65, 0.7, 0.8, 0.9, 1.0):
    for wname in ("DEV", "HOLD"):
        res_g, res_o = [], []
        for dr in range(50):
            flip = rng.random(nb) > acc_
            st = np.where(flip[blk], 1 - orc, orc)
            pp = cache[("EW", wname, 50, 0)]
            eq0, r0, inv0, _ = compose(pp)
            m0 = metrics(eq0, r0, pp["dates"], inv0)
            eq, r, inv, xs = compose(pp, x_by_g=xmap(st, 0.0))
            m = metrics(eq, r, pp["dates"], inv, xs)
            res_g.append((m["cagr"] - m0["cagr"], m["sharpe_xs"] - m0["sharpe_xs"], m["max_dd"] - m0["max_dd"]))
            gidx = np.arange(pp["D0"], pp["D1"] + 1)
            y = xmap(st, 0.0)[np.clip(gidx - 2, 0, None)]
            y[0] = 1.0
            sw = np.r_[0.0, np.abs(np.diff(y))]
            ro = y * r0 + (1 - y) * cd - sw * 50 / 2e4
            mo = metrics(np.cumprod(1 + ro), ro, pp["dates"])
            res_o.append((mo["cagr"] - m0["cagr"], mo["sharpe_xs"] - m0["sharpe_xs"], mo["max_dd"] - m0["max_dd"]))
        Rg, Ro = np.array(res_g), np.array(res_o)
        wm = (cal >= np.datetime64(WINS[wname][0])) & (cal <= np.datetime64(WINS[wname][1])) & np.isfinite(orc)
        be.append({"accuracy": acc_, "window": wname,
                   "gate_d_cagr_mean": float(Rg[:, 0].mean()), "gate_d_sharpe_xs_mean": float(Rg[:, 1].mean()),
                   "gate_d_maxdd_mean": float(Rg[:, 2].mean()), "gate_p_d_cagr_pos": float((Rg[:, 0] > 0).mean()),
                   "overlay_d_cagr_mean": float(Ro[:, 0].mean()), "overlay_d_sharpe_xs_mean": float(Ro[:, 1].mean()),
                   "overlay_d_maxdd_mean": float(Ro[:, 2].mean()), "overlay_p_d_cagr_pos": float((Ro[:, 0] > 0).mean())})
        print(be[-1], flush=True)
save("s5_noisy_oracle_breakeven", be)
pd.set_option("display.width", 250)
print(G[(G.book == "EW") & (G.x_off == 0.0)].pivot_table(index="rule", columns="window",
      values=["on_share", "d_cagr", "d_sharpe_xs", "d_maxdd"]).round(3).to_string())
print("total", round(time.time() - t0, 1))
