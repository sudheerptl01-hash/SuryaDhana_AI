"""R3_risk item 2: pre-declared exposure policies X100 / X80 / X60 / G50 (breadth governor) on the
PROD book (DEV, 2026, contiguous) and the EW-universe book (PRE 2021-09..2022-12, DEV, 2026).
Validation: run_x with x=1 and no cash index must equal L.Sim.run bit-exact."""
import sys

import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
sys.path.insert(0, LAB + "/results/R3_risk")
import r3common as C  # noqa: E402
import lablib as L  # noqa: E402
from expo_sim import run_x, phase_avg_x  # noqa: E402

OUT = C.set_agent("R3_risk")
P, F, fw, S, E = C.load_sim(extra_feat=("breadth50",))
prod = C.load_prod()["prod"]
H = 20
cal = pd.DatetimeIndex(S.cal)
cash_level = L.market_series("Nifty 1D Rate Index")["close"].reindex(cal).ffill().bfill().values
b50 = pd.Series(F["breadth50"].values.astype("float64")).groupby(S.didx).first().reindex(range(len(cal))).values
C.log("breadth50 NaN share on calendar", float(np.isnan(b50).mean()))

# ---------------- validation vs L.Sim
val = {}
for tag, sc, extra in (("PROD", prod, {}), ("EW", np.ones(S.n), dict(select_quantile=(0.0, 1.0), sizing="equal"))):
    kw = dict(step=5, cost_bps=50.0, start="2023-01-02", end_exit="2025-12-31", **extra)
    if "select_quantile" not in extra:
        kw["top_k"] = 20
    a = S.run(sc, E, H, **kw)
    kw2 = dict(kw)
    b = run_x(S, sc, E, H, **kw2)
    val[tag] = {"max_abs_daily_diff": float(np.max(np.abs(a["_daily_ret"] - b["_daily_ret"]))),
                "cagr_lablib": a["cagr"], "exposure_lablib": a["exposure"], "exposure_copy": b["exposure"]}
z = np.load(f"{OUT}/pa_series.npz")
base_dev, _, _ = phase_avg_x(S, prod, E, H, dict(step=5, top_k=20, cost_bps=50.0), C.DEV)
ref = pd.Series(z["dev_c50_book"], index=pd.DatetimeIndex(z["dev_c50_book_dates"]))
val["phase_avg_vs_C_phase_avg_max_abs_diff"] = float(np.max(np.abs(base_dev.reindex(ref.index).values - ref.values)))
C.log("validation", C.short(val, 8))
C.save("item2_validation", val)

# ---------------- policies
def gov(g):
    return 0.5 if (np.isfinite(b50[g]) and b50[g] < 0.5) else 1.0


POL = {"X100": dict(xfun=None, cash_level=None),
       "X100_cash": dict(xfun=None, cash_level=cash_level),      # diagnostic: idle cash at 1D rate
       "X80": dict(xfun=lambda g: 0.8, cash_level=cash_level),
       "X60": dict(xfun=lambda g: 0.6, cash_level=cash_level),
       "G50": dict(xfun=gov, cash_level=cash_level)}
BOOKS = {"PROD": (prod, dict(step=5, top_k=20)),
         "EW": (np.ones(S.n), dict(step=5, select_quantile=(0.0, 1.0), sizing="equal"))}
PERIODS = {"PROD": {"dev": C.DEV, "hold": ("2026-01-01", None), "contig": ("2023-01-01", "2026-10-14")},
           "EW": {"pre": ("2021-09-01", "2022-12-31"), "dev": C.DEV, "hold": ("2026-01-01", None)}}

res, series = {}, {}
for book, (sc, bkw) in BOOKS.items():
    for pname, per in PERIODS[book].items():
        for cost in (50, 80):
            kw = dict(bkw, cost_bps=float(cost))
            base = None
            for pol, kx in POL.items():
                sm, expo, xsig = phase_avg_x(S, sc, E, H, kw, per, **kx)
                st = C.stats_from_daily(sm)
                st["calmar"] = st["cagr"] / abs(st["maxdd"]) if st["maxdd"] < 0 else None
                st["avg_exposure"] = expo
                if pol == "X100":
                    base = sm
                else:
                    pr = C.paired(sm, base, h=H)
                    st["paired_vs_X100"] = pr
                    st["maxdd_change_vs_X100"] = st["maxdd"] - C.stats_from_daily(base)["maxdd"]
                if pol == "G50":
                    x0 = xsig[0]
                    yrs = len(sm) / 252
                    st["share_signals_risk_off"] = float(np.mean(x0 < 1))
                    st["switches_per_year"] = float(np.sum(np.diff(x0) != 0) / yrs)
                key = f"{book}_{pname}_c{cost}_{pol}"
                res[key] = st
                if cost == 50:
                    series[key] = sm
                C.log(key, C.short({k: v for k, v in st.items() if k in ("cagr", "vol", "sharpe", "maxdd", "calmar",
                                                                         "avg_exposure", "paired_vs_X100",
                                                                         "share_signals_risk_off", "switches_per_year")}))
# adoption rule (PREREG) for G50 on the PROD book, DEV, 50 bps
g = res["PROD_dev_c50_G50"]
adopt = {"G50_dev_paired_diff_ann": g["paired_vs_X100"]["diff_ann"], "G50_dev_paired_nw_t": g["paired_vs_X100"]["nw_t"],
         "G50_dev_maxdd_change": g["maxdd_change_vs_X100"],
         "adopted": bool(g["paired_vs_X100"]["nw_t"] >= 2 and g["maxdd_change_vs_X100"] >= -0.03)}
for pol in ("X80", "X60"):
    q = res[f"PROD_dev_c50_{pol}"]
    adopt[f"{pol}_dev_paired_diff_ann"] = q["paired_vs_X100"]["diff_ann"]
    adopt[f"{pol}_dev_paired_nw_t"] = q["paired_vs_X100"]["nw_t"]
    adopt[f"{pol}_dev_maxdd_change"] = q["maxdd_change_vs_X100"]
    adopt[f"{pol}_adopted_as_addon"] = bool(q["paired_vs_X100"]["nw_t"] >= 2 and q["maxdd_change_vs_X100"] >= -0.03)
C.log("adoption", C.short(adopt))
C.save("item2_exposure", {"results": res, "adoption": adopt,
                          "notes": ["Exposure set at each sleeve's rebalance (signal close); idle share earns the Nifty 1D "
                                    "Rate Index from that close. X100 = frozen baseline (idle cash 0%, identical to L.Sim). "
                                    "X100_cash is a diagnostic (idle cash at 1D rate), not a policy.",
                                    "PRE (2021-09..2022-12) exists only for the EW-universe book: no PROD scores before 2023.",
                                    "Sharpe uses rf = 0 (as C.stats_from_daily); Calmar = CAGR / |maxDD| over the period."]})
np.savez(f"{OUT}/expo_series.npz", **{k: v.values for k, v in series.items()},
         **{k + "_dates": v.index.values.astype("datetime64[D]").astype(str) for k, v in series.items()})
C.log("done")
