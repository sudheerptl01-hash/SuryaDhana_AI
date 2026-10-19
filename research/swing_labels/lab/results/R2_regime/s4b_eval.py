"""Stage 4b: apply each timing signal as an exposure scaler on the cached books.

Implementation A — sleeve gating (primary): at every signal date g the sleeve that rebalances
invests x_g of its equity (x_g = 1 risk-on, x_off risk-off; VOTE graded) and holds 1-x_g in cash
at 6.5%/yr. Each sleeve fully turns over every 20 days anyway, so gating adds no trades.
Implementation B — daily overlay (whipsaw stress): the always-in book's daily return is scaled
by the state decided at close d-2 (one extra day of lag, conservative), switching cost
|dx| * cost/2 charged on every change.
Implementation C — pure index timing: Nifty 500 open-to-open returns, state at close g applied
to open g+1 -> open g+2, switching cost 10 bps per side (and 0 = information value only).

Benchmarks for every gated run: always-in (x=1); static mix with the same average signal
exposure (x = mean x_g, constant); circular-shift null (200 random cyclic shifts of the state
series inside the window; same exposure and persistence, no timing information);
foresight canaries ORACLE_E = 1{EW f20 > 0}, ORACLE_N = 1{N500 f20 > 0}, ANTI_E.
"""
import pickle
import time

import numpy as np
import pandas as pd

from common import OUT, save, compose, metrics, nw_t, CASH, nw_mean_diff_t

t0 = time.time()
with open(f"{OUT}/paths_cache.pkl", "rb") as fh:
    cache = pickle.load(fh)
S = pd.read_parquet(f"{OUT}/timing_signals.parquet")
D = pd.read_parquet(f"{OUT}/dateset.parquet")
cal = D.index.values.astype("datetime64[D]")
any_pp = next(iter(cache.values()))
assert len(S) == len(cal)

RULES = ["R200", "RBR", "RVIX", "RM60", "VOTE"]
MODELS = [f"{m}_{t}" for m in ("LOG4", "LOG10", "LGB10") for t in ("N0", "N1", "E0")]
SIGS = RULES + MODELS
CANARY = {"ORACLE_E": np.where(np.isfinite(D.ew_f20), (D.ew_f20 > 0).astype(float), np.nan),
          "ORACLE_N": np.where(np.isfinite(D.n500_f20), (D.n500_f20 > 0).astype(float), np.nan)}
CANARY["ANTI_E"] = 1 - CANARY["ORACLE_E"]
STATE = {s: S[s].values.astype(float) for s in SIGS}
STATE.update(CANARY)
XOFF = (0.5, 0.0)
PHASES = range(5)
rng = np.random.default_rng(12345)


def xmap(state, x_off):
    st = np.asarray(state, float)
    return np.where(np.isfinite(st), x_off + (1 - x_off) * st, 1.0)


def run_one(book, wname, cost, ph, x_by_g=None, x_const=None):
    pp = cache[(book, wname, cost, ph)]
    eq, r, inv, xs = compose(pp, x_by_g=x_by_g, x_const=x_const)
    m = metrics(eq, r, pp["dates"], inv, xs)
    return m, r, xs


def rnd_mean(wname, cost, ph, x_by_g=None, x_const=None):
    rr = []
    cg = []
    for sd in (1, 2, 3, 4, 5):
        m, r, _ = run_one(f"RND20_s{sd}", wname, cost, ph, x_by_g, x_const)
        rr.append(r)
        cg.append(m["cagr"])
    return float(np.mean(cg)), np.mean(rr, 0)


KEYS = ("cagr", "sharpe", "sharpe_xs", "max_dd", "calmar", "exposure", "switches_per_yr", "signal_exposure_mean", "ann_vol")
rows = []
daily_keep = {}
for book in ("EW", "XR20"):
    for wname in ("DEV", "HOLD", "PRE"):
        if book == "XR20" and wname == "PRE":
            continue
        for cost in (50, 80):
            base = {}
            for ph in PHASES:
                m, r, _ = run_one(book, wname, cost, ph)
                base[ph] = (m, r)
                if book == "XR20":
                    rc, rr = rnd_mean(wname, cost, ph)
                    base[ph] = (m, r, rc, rr)
            sig_list = SIGS + list(CANARY)
            for sn in sig_list:
                if wname == "PRE" and sn not in RULES and sn not in CANARY:
                    continue
                for x_off in XOFF:
                    xg = xmap(STATE[sn], x_off)
                    acc = []
                    for ph in PHASES:
                        m, r, xs = run_one(book, wname, cost, ph, x_by_g=xg)
                        m0, r0 = base[ph][0], base[ph][1]
                        ms, rs_, _ = run_one(book, wname, cost, ph, x_const=float(np.mean(xs)))
                        rec = {k: m.get(k) for k in KEYS}
                        rec.update({f"base_{k}": m0[k] for k in ("cagr", "sharpe", "sharpe_xs", "max_dd", "calmar", "exposure")})
                        rec.update({f"static_{k}": ms[k] for k in ("cagr", "sharpe", "sharpe_xs", "max_dd")})
                        rec["d_cagr"] = m["cagr"] - m0["cagr"]
                        rec["d_sharpe"] = m["sharpe"] - m0["sharpe"]
                        rec["d_sharpe_xs"] = m["sharpe_xs"] - m0["sharpe_xs"]
                        rec["d_sharpe_xs_vs_static"] = m["sharpe_xs"] - ms["sharpe_xs"]
                        rec["d_maxdd"] = m["max_dd"] - m0["max_dd"]
                        rec["d_cagr_vs_static"] = m["cagr"] - ms["cagr"]
                        rec["d_sharpe_vs_static"] = m["sharpe"] - ms["sharpe"]
                        rec["d_maxdd_vs_static"] = m["max_dd"] - ms["max_dd"]
                        rec["nw_t_vs_base"] = nw_t(r - r0, 20)
                        rec["nw_t_vs_static"] = nw_t(r - rs_, 20)
                        if book == "XR20":
                            rcg, rrg = rnd_mean(wname, cost, ph, x_by_g=xg)
                            rec["rnd_cagr_gated"] = rcg
                            rec["excess_vs_rnd_gated"] = m["cagr"] - rcg
                            rec["excess_nw_t_vs_rnd_gated"] = nw_t(r - rrg, 20)
                            rec["base_excess_vs_rnd"] = m0["cagr"] - base[ph][2]
                            rec["base_excess_nw_t"] = nw_t(r0 - base[ph][3], 20)
                        rec["by_year"] = m["by_year"]
                        rec["base_by_year"] = m0["by_year"]
                        acc.append(rec)
                        if ph == 0 and cost == 50:
                            daily_keep[(book, wname, sn, x_off)] = r
                    out = {"book": book, "window": wname, "cost": cost, "signal": sn, "x_off": x_off}
                    p0 = acc[0]
                    for k, v in p0.items():
                        if k in ("by_year", "base_by_year"):
                            out[f"p0_{k}"] = v
                        else:
                            out[f"p0_{k}"] = v
                    for k in p0:
                        if k in ("by_year", "base_by_year"):
                            continue
                        vals = [a[k] for a in acc if a[k] is not None and np.isfinite(a[k])]
                        out[f"pavg_{k}"] = float(np.mean(vals)) if vals else None
                    yrs = sorted(acc[0]["by_year"])
                    out["pavg_by_year"] = {y: float(np.mean([a["by_year"][y] for a in acc if y in a["by_year"]])) for y in yrs}
                    out["pavg_base_by_year"] = {y: float(np.mean([a["base_by_year"][y] for a in acc if y in a["base_by_year"]])) for y in yrs}
                    rows.append(out)
            for ph in (0,):
                daily_keep[(book, wname, "ALWAYS", 1.0)] = base[0][1]
        print(book, "done", round(time.time() - t0, 1), flush=True)

R = pd.DataFrame(rows)
R.to_pickle(f"{OUT}/gating_results.pkl")
np.savez_compressed(f"{OUT}/gating_daily.npz",
                    **{"|".join(map(str, k)): v for k, v in daily_keep.items()})
print("gating rows", len(R), round(time.time() - t0, 1), flush=True)

# ------------------------------------------------------------------ circular-shift null (phase 0, 50 bps)
null_rows = []
NSH = 200
for book in ("EW", "XR20"):
    for wname in ("DEV", "HOLD", "PRE"):
        if book == "XR20" and wname == "PRE":
            continue
        pp = cache[(book, wname, 50, 0)]
        D0, D1 = pp["D0"], pp["D1"]
        L_ = D1 - D0 + 1
        m0, r0, _ = run_one(book, wname, 50, 0)
        shifts = rng.integers(40, L_ - 40, size=NSH)
        for sn in SIGS:
            if wname == "PRE" and sn not in RULES:
                continue
            st = np.asarray(STATE[sn], float)
            for x_off in XOFF:
                xg_obs = xmap(st, x_off)
                mo, ro, xso = run_one(book, wname, 50, 0, x_by_g=xg_obs)
                ds, dc, dd = [], [], []
                for k in shifts:
                    st2 = st.copy()
                    seg = st[D0:D1 + 1]
                    st2[D0:D1 + 1] = np.roll(seg, int(k))
                    m, r, xs = run_one(book, wname, 50, 0, x_by_g=xmap(st2, x_off))
                    ds.append(m["sharpe"] - m0["sharpe"])
                    dc.append(m["cagr"] - m0["cagr"])
                    dd.append(m["max_dd"] - m0["max_dd"])
                ds, dc, dd = map(np.array, (ds, dc, dd))
                obs_s, obs_c, obs_d = mo["sharpe"] - m0["sharpe"], mo["cagr"] - m0["cagr"], mo["max_dd"] - m0["max_dd"]
                null_rows.append({"book": book, "window": wname, "signal": sn, "x_off": x_off,
                                  "obs_d_sharpe": obs_s, "obs_d_cagr": obs_c, "obs_d_maxdd": obs_d,
                                  "null_d_sharpe_mean": float(ds.mean()), "null_d_sharpe_p95": float(np.percentile(ds, 95)),
                                  "null_d_cagr_mean": float(dc.mean()), "null_d_cagr_p95": float(np.percentile(dc, 95)),
                                  "null_d_maxdd_mean": float(dd.mean()), "null_d_maxdd_p95": float(np.percentile(dd, 95)),
                                  "p_sharpe": float((ds >= obs_s).mean()), "p_cagr": float((dc >= obs_c).mean()),
                                  "p_maxdd": float((dd >= obs_d).mean())})
        print("null", book, wname, round(time.time() - t0, 1), flush=True)
N = pd.DataFrame(null_rows)
N.to_pickle(f"{OUT}/gating_null.pkl")
save("s4b_null", N.to_dict(orient="records"))

# compact summary to results.json
keep_cols = ["book", "window", "cost", "signal", "x_off"] + [c for c in R.columns if c.startswith("pavg_") or c.startswith("p0_")]
save("s4b_gating", R[keep_cols].to_dict(orient="records"))
print("total", round(time.time() - t0, 1), flush=True)
