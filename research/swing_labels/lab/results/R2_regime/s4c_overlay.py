"""Stage 4c: whipsaw stress — daily overlay on the books and pure Nifty-500 index timing.

B. Daily overlay on a book (always-in daily returns r_d from the cached paths, all 5 phases):
   position for day d = x(state at close of d-2)  (decision at close, trade next open, and one
   extra day of lag because the book's open prices are not tracked — conservative);
   r_ov = y_d * r_d + (1-y_d) * cash_d - |y_d - y_{d-1}| * cost/2.
   The book's own entry/exit costs are still charged at full size (double counting = conservative).
C. Pure index timing: Nifty 500 open-to-open returns; state at close g is executed at open g+1 and
   earns open[g+1] -> open[g+2]; switching cost per side 10 bps (ETF-like) and 0 (information only);
   buy-and-hold N500 is the benchmark (price index, no dividends — this flatters timing slightly).
Null for C: 200 circular shifts of the state inside the window.
"""
import pickle
import time

import numpy as np
import pandas as pd

from common import OUT, save, compose, metrics, CASH, nw_t

t0 = time.time()
with open(f"{OUT}/paths_cache.pkl", "rb") as fh:
    cache = pickle.load(fh)
S = pd.read_parquet(f"{OUT}/timing_signals.parquet")
D = pd.read_parquet(f"{OUT}/dateset.parquet")
cal = D.index.values.astype("datetime64[D]")
RULES = ["R200", "RBR", "RVIX", "RM60", "VOTE"]
MODELS = [f"{m}_{t}" for m in ("LOG4", "LOG10", "LGB10") for t in ("N0", "N1", "E0")]
SIGS = RULES + MODELS
ORA = np.where(np.isfinite(D.ew_f20), (D.ew_f20 > 0).astype(float), np.nan)
ORN = np.where(np.isfinite(D.n500_f20), (D.n500_f20 > 0).astype(float), np.nan)
STATE = {s: S[s].values.astype(float) for s in SIGS}
STATE["ORACLE_E"] = ORA
STATE["ORACLE_N"] = ORN
cd = (1 + CASH) ** (1 / 252) - 1


def xmap(state, x_off):
    st = np.asarray(state, float)
    return np.where(np.isfinite(st), x_off + (1 - x_off) * st, 1.0)


def mstats(r, dates, y=None):
    eq = np.cumprod(1 + r)
    m = metrics(eq, r, dates)
    if y is not None:
        yrs = max((dates[-1] - dates[0]).astype(int) / 365.25, 1e-9)
        m["switches_per_yr"] = float((np.abs(np.diff(y)) > 1e-9).sum() / yrs)
        m["exposure"] = float(np.mean(y))
    return m


rows = []
# ------------------------------------------------------------------ B. daily overlay on books
for book in ("EW", "XR20"):
    for wname in ("DEV", "HOLD", "PRE"):
        if book == "XR20" and wname == "PRE":
            continue
        for cost in (50, 80):
            for sn in SIGS + ["ORACLE_E"]:
                if wname == "PRE" and sn not in RULES + ["ORACLE_E"]:
                    continue
                for x_off in (0.5, 0.0):
                    acc = []
                    for ph in range(5):
                        pp = cache[(book, wname, cost, ph)]
                        eq0, r0, inv0, _ = compose(pp)
                        dates = pp["dates"]
                        gidx = np.arange(pp["D0"], pp["D1"] + 1)
                        x = xmap(STATE[sn], x_off)
                        y = x[np.clip(gidx - 2, 0, None)]
                        y[0] = 1.0  # first day of the window: book just starting
                        sw = np.r_[0.0, np.abs(np.diff(y))]
                        r = y * r0 + (1 - y) * cd - sw * cost / 2e4
                        m = mstats(r, dates, y)
                        m0 = mstats(r0, dates)
                        acc.append({"cagr": m["cagr"], "sharpe_xs": m["sharpe_xs"], "max_dd": m["max_dd"],
                                    "switches_per_yr": m["switches_per_yr"], "exposure": m["exposure"],
                                    "base_cagr": m0["cagr"], "base_sharpe_xs": m0["sharpe_xs"], "base_max_dd": m0["max_dd"],
                                    "switch_cost_per_yr": float(sw.sum() * cost / 2e4 / ((dates[-1] - dates[0]).astype(int) / 365.25)),
                                    "nw_t_vs_base": nw_t(r - r0, 20)})
                    rec = {"impl": "daily_overlay", "book": book, "window": wname, "cost": cost, "signal": sn, "x_off": x_off}
                    for k in acc[0]:
                        rec[k] = float(np.mean([a[k] for a in acc]))
                    rec["d_cagr"] = rec["cagr"] - rec["base_cagr"]
                    rec["d_sharpe_xs"] = rec["sharpe_xs"] - rec["base_sharpe_xs"]
                    rec["d_maxdd"] = rec["max_dd"] - rec["base_max_dd"]
                    rows.append(rec)
    print("overlay", book, round(time.time() - t0, 1), flush=True)

# ------------------------------------------------------------------ C. pure index timing
mo = D.n500_open.values.astype(float)
roo = np.r_[mo[1:] / mo[:-1] - 1, np.nan]           # open g -> open g+1
WIN = {"PRE": ("2021-09-01", "2022-12-31"), "DEV": ("2023-01-01", "2025-12-31"), "HOLD": ("2026-01-01", "2026-12-31")}
rng = np.random.default_rng(7)
null_rows = []
for wname, (a, b) in WIN.items():
    gsel = np.flatnonzero((cal >= np.datetime64(a)) & (cal <= np.datetime64(b)))
    gsel = gsel[(gsel - 1 >= 0) & np.isfinite(roo[gsel])]     # return day g uses decision at g-1
    dates = cal[gsel]
    r_bh = roo[gsel]
    for sn in SIGS + ["ORACLE_N"]:
        if wname == "PRE" and sn not in RULES + ["ORACLE_N"]:
            continue
        for x_off in (0.5, 0.0):
            for cside in (10.0, 0.0):
                x = xmap(STATE[sn], x_off)
                y = x[gsel - 1]
                sw = np.r_[abs(y[0] - 1.0), np.abs(np.diff(y))]
                r = y * r_bh + (1 - y) * cd - sw * cside / 1e4
                m = mstats(r, dates, y)
                m0 = mstats(r_bh, dates)
                rec = {"impl": "index_n500", "book": "N500", "window": wname, "cost": cside, "signal": sn, "x_off": x_off,
                       "cagr": m["cagr"], "sharpe_xs": m["sharpe_xs"], "max_dd": m["max_dd"],
                       "switches_per_yr": m["switches_per_yr"], "exposure": m["exposure"],
                       "base_cagr": m0["cagr"], "base_sharpe_xs": m0["sharpe_xs"], "base_max_dd": m0["max_dd"],
                       "nw_t_vs_base": nw_t(r - r_bh, 20)}
                rec["d_cagr"] = rec["cagr"] - rec["base_cagr"]
                rec["d_sharpe_xs"] = rec["sharpe_xs"] - rec["base_sharpe_xs"]
                rec["d_maxdd"] = rec["max_dd"] - rec["base_max_dd"]
                # static mix with same mean exposure
                ys = np.full(len(y), y.mean())
                rs = ys * r_bh + (1 - ys) * cd
                ms_ = mstats(rs, dates)
                rec["d_cagr_vs_static"] = rec["cagr"] - ms_["cagr"]
                rec["d_sharpe_xs_vs_static"] = rec["sharpe_xs"] - ms_["sharpe_xs"]
                rows.append(rec)
                if cside == 10.0 and sn != "ORACLE_N":
                    st = np.asarray(STATE[sn], float)
                    ds, dc = [], []
                    L_ = len(gsel)
                    for k in rng.integers(40, L_ - 40, size=200):
                        st2 = st.copy()
                        st2[gsel - 1] = np.roll(st[gsel - 1], int(k))
                        y2 = xmap(st2, x_off)[gsel - 1]
                        sw2 = np.r_[abs(y2[0] - 1.0), np.abs(np.diff(y2))]
                        r2 = y2 * r_bh + (1 - y2) * cd - sw2 * cside / 1e4
                        m2 = mstats(r2, dates)
                        ds.append(m2["sharpe_xs"] - m0["sharpe_xs"])
                        dc.append(m2["cagr"] - m0["cagr"])
                    ds, dc = np.array(ds), np.array(dc)
                    null_rows.append({"window": wname, "signal": sn, "x_off": x_off,
                                      "obs_d_sharpe_xs": rec["d_sharpe_xs"], "obs_d_cagr": rec["d_cagr"],
                                      "null_d_sharpe_xs_mean": float(ds.mean()), "null_d_cagr_mean": float(dc.mean()),
                                      "p_sharpe_xs": float((ds >= rec["d_sharpe_xs"]).mean()),
                                      "p_cagr": float((dc >= rec["d_cagr"]).mean())})
print("index", round(time.time() - t0, 1), flush=True)
O = pd.DataFrame(rows)
O.to_pickle(f"{OUT}/overlay_results.pkl")
NI = pd.DataFrame(null_rows)
NI.to_pickle(f"{OUT}/index_null.pkl")
save("s4c_overlay", O.to_dict(orient="records"))
save("s4c_index_null", NI.to_dict(orient="records"))
pd.set_option("display.width", 250)
cols = ["impl", "book", "window", "cost", "signal", "x_off", "cagr", "base_cagr", "d_cagr", "sharpe_xs", "d_sharpe_xs",
        "max_dd", "d_maxdd", "switches_per_yr", "exposure"]
print(O[(O.signal.isin(RULES + ["ORACLE_E", "ORACLE_N", "LGB10_E0"])) & (O.x_off == 0.0) & (O.cost.isin([50, 10]))][cols].round(3).to_string(index=False))
print(NI.round(3).to_string(index=False))
print("total", round(time.time() - t0, 1))
