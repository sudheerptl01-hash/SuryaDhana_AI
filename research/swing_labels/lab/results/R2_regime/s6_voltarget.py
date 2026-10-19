"""Stage 6: one risk-based (not direction-forecasting) exposure rule, for contrast.

VOLT: x_g = min(1, trailing-250d median of mkt_vol20 / mkt_vol20_g)   (PIT; min 120 obs)
Applied by sleeve gating to EW and XR20, 50/80 bps, PRE/DEV/HOLD, phase-averaged, with
static-mix and circular-shift-null comparisons (same machinery as s4b). One variant only.
Also: signal accuracy vs the 20d targets (share of dates where state == target) for every
primary signal, used by the report next to the noisy-oracle break-even.
"""
import pickle
import time

import numpy as np
import pandas as pd

from common import OUT, save, compose, metrics

t0 = time.time()
with open(f"{OUT}/paths_cache.pkl", "rb") as fh:
    cache = pickle.load(fh)
D = pd.read_parquet(f"{OUT}/dateset.parquet")
S = pd.read_parquet(f"{OUT}/timing_signals.parquet")
cal = D.index.values.astype("datetime64[D]")
mv = D.mkt_vol20
med = mv.rolling(250, min_periods=120).median()
x_volt = np.minimum(1.0, (med / mv).values)
x_volt = np.where(np.isfinite(x_volt), x_volt, 1.0)
rng = np.random.default_rng(99)
rows = []
for book in ("EW", "XR20"):
    for wname in ("PRE", "DEV", "HOLD"):
        if book == "XR20" and wname == "PRE":
            continue
        for cost in (50, 80):
            acc = []
            for ph in range(5):
                pp = cache[(book, wname, cost, ph)]
                eq0, r0, inv0, _ = compose(pp)
                m0 = metrics(eq0, r0, pp["dates"], inv0)
                eq, r, inv, xs = compose(pp, x_by_g=x_volt)
                m = metrics(eq, r, pp["dates"], inv, xs)
                eqs, rs, invs, _ = compose(pp, x_const=float(np.mean(xs)))
                ms = metrics(eqs, rs, pp["dates"], invs)
                acc.append([m["cagr"], m["sharpe_xs"], m["max_dd"], m["exposure"], m["switches_per_yr"],
                            m0["cagr"], m0["sharpe_xs"], m0["max_dd"], ms["cagr"], ms["sharpe_xs"], ms["max_dd"]])
            A = np.array(acc).mean(0)
            rec = dict(zip(["cagr", "sharpe_xs", "max_dd", "exposure", "switches_per_yr", "base_cagr", "base_sharpe_xs",
                            "base_max_dd", "static_cagr", "static_sharpe_xs", "static_max_dd"], A.tolist()))
            rec.update({"book": book, "window": wname, "cost": cost})
            if cost == 50:
                pp = cache[(book, wname, 50, 0)]
                D0, D1 = pp["D0"], pp["D1"]
                eq0, r0, inv0, _ = compose(pp)
                m0 = metrics(eq0, r0, pp["dates"], inv0)
                eq, r, inv, xs = compose(pp, x_by_g=x_volt)
                obs = metrics(eq, r, pp["dates"], inv, xs)["sharpe_xs"] - m0["sharpe_xs"]
                nul = []
                for k in rng.integers(40, D1 - D0 - 40, size=200):
                    x2 = x_volt.copy()
                    x2[D0:D1 + 1] = np.roll(x_volt[D0:D1 + 1], int(k))
                    e2, r2, i2, xs2 = compose(pp, x_by_g=x2)
                    nul.append(metrics(e2, r2, pp["dates"], i2, xs2)["sharpe_xs"] - m0["sharpe_xs"])
                rec["p0_obs_d_sharpe_xs"] = float(obs)
                rec["null_p_sharpe_xs"] = float((np.array(nul) >= obs).mean())
            rows.append(rec)
V = pd.DataFrame(rows)
save("s6_voltarget", V.to_dict(orient="records"))
pd.set_option("display.width", 250)
print(V.round(3).to_string(index=False))

# ------------------------------------------------------------------ signal accuracy vs targets
tg = {"E0": np.where(np.isfinite(D.ew_f20), (D.ew_f20 > 0).astype(float), np.nan),
      "N0": np.where(np.isfinite(D.n500_f20), (D.n500_f20 > 0).astype(float), np.nan)}
sigs = ["R200", "RBR", "RVIX", "RM60"] + [f"{m}_{t}" for m in ("LOG4", "LOG10", "LGB10") for t in ("N0", "N1", "E0")]
accr = {}
for sn in sigs:
    st = S[sn].values
    accr[sn] = {}
    for wname, (a, b) in (("PRE", ("2021-09-01", "2022-12-31")), ("DEV", ("2023-01-01", "2025-12-31")),
                          ("HOLD", ("2026-01-01", "2026-12-31"))):
        m = (cal >= np.datetime64(a)) & (cal <= np.datetime64(b)) & np.isfinite(st)
        for tn, y in tg.items():
            mm = m & np.isfinite(y)
            if mm.sum() < 40:
                continue
            accr[sn][f"{wname}_{tn}"] = float((st[mm] == y[mm]).mean())
            accr[sn][f"{wname}_{tn}_always_on"] = float((y[mm] == 1).mean())
save("s6_signal_accuracy", accr)
for sn, v in accr.items():
    print(sn, {k: round(x, 3) for k, x in v.items()})
print("total", round(time.time() - t0, 1))
