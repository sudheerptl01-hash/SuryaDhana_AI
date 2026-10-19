"""Stage 3: the pre-declared down-side strategies (BASE, D0, D1a/b/c, D2 x4, D3, D4, extra X1) + baselines,
phase-averaged, DEV / 2026 / contiguous 2023-01..2026-10, at 50 bps (central) and 80 bps (stress)."""
import sys
import numpy as np
import pandas as pd
LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
sys.path.insert(0, LAB + "/results/R3_twoway")
import r3common as C
from twsim import TwoWay, hedge_overlay
L = C.L
C.set_agent("R3_twoway")
P, F, fw, S, E = C.load_sim(extra_feat=("fno_proxy", "beta_60"))
fnoE = F["fno_proxy"].values.astype(bool) & E
beta60 = F["beta_60"].values.astype("float64")
prod = C.load_prod()["prod"].astype("float64")
cal = pd.DatetimeIndex(S.cal)


def lvl(name):
    return L.market_series(name)["close"].reindex(cal).ffill()


cl1d = lvl("Nifty 1D Rate Index").values
T = TwoWay(S, fw, cl1d)
n500 = lvl("Nifty 500")
fut50 = lvl("Nifty 50 Futures Index")
ms = lvl("Nifty Midcap Select")
r1d = pd.Series(cl1d, index=cal).pct_change()
Q_DIV = 0.0107
r_ms_fut = ms.pct_change() - (r1d - Q_DIV / 252)            # synthetic MIDCPNIFTY futures (C4)
ms_fut = (1 + r_ms_fut.fillna(0)).cumprod()
HEDGE_LEVEL = {"n50fut": fut50, "msfut": ms_fut}
month_end = pd.Series(cal.to_period("M"), index=cal)
month_end = (month_end != month_end.shift(-1)).values         # last trading day of each month
PERIODS = {"dev": C.DEV, "hold": ("2026-01-01", None), "contig": ("2023-01-01", None)}
S_CASH = 1.0 / (1.0 + 0.5 * 0.25 * 1.0)                         # D2 cash-long scale (C6)
S_D3 = 1.0 / (1.0 + 0.5 * 0.25 * 0.5)                           # D3 long scale
SEEDS = (1, 2, 3, 4, 5)


def pa(series_list):
    common = series_list[0].index
    for x in series_list[1:]:
        common = common.intersection(x.index)
    return pd.Series(np.mean([x.reindex(common).values for x in series_list], 0), index=common)


def ser(run):
    return pd.Series(run["_daily"], index=pd.DatetimeIndex(run["_dates"]))


def strategies(cc, cf):
    """name -> kwargs for T.run (score given) ; random baselines handled separately."""
    return {
        "BASE": dict(maskL=E, maskS=None, aL=1.0, aS=0.0, cL=cc),
        "D2_K10_cash": dict(maskL=fnoE, maskS=fnoE, kL=10, kS=10, aL=S_CASH, aS=S_CASH, cL=cc, cS=cf, cash="1d"),
        "D2_K10_fut": dict(maskL=fnoE, maskS=fnoE, kL=10, kS=10, aL=1.0, aS=1.0, long_mode="futures", cL=cf, cS=cf, cash="1d"),
        "D2_K20_cash": dict(maskL=fnoE, maskS=fnoE, kL=20, kS=20, aL=S_CASH, aS=S_CASH, cL=cc, cS=cf, cash="1d"),
        "D2_K20_fut": dict(maskL=fnoE, maskS=fnoE, kL=20, kS=20, aL=1.0, aS=1.0, long_mode="futures", cL=cf, cS=cf, cash="1d"),
        "X1_D2_K20_cash_beta": dict(maskL=fnoE, maskS=fnoE, kL=20, kS=20, aL=S_CASH, aS=S_CASH, cL=cc, cS=cf, cash="1d",
                                    beta_row=beta60),
        "D3": dict(maskL=E, maskS=fnoE, kL=20, kS=20, aL=S_D3, aS=0.5 * S_D3, cL=cc, cS=cf, cash="1d"),
        "D4": dict(maskL=None, maskS=fnoE, kS=20, aL=0.0, aS=1.0, long_mode="none", cS=cf, cash="1d"),
    }


def randoms(cc, cf):
    """baseline name -> (kwargs, seed mode). 'S' = random short only, 'LS' = both legs random."""
    return {
        "R_D4_randshort": (dict(maskL=None, maskS=fnoE, kS=20, aL=0.0, aS=1.0, long_mode="none", cS=cf, cash="1d"), "S"),
        "R_D2_K20_cash_rand": (dict(maskL=fnoE, maskS=fnoE, kL=20, kS=20, aL=S_CASH, aS=S_CASH, cL=cc, cS=cf, cash="1d"), "LS"),
        "R_D3_randshort": (dict(maskL=E, maskS=fnoE, kL=20, kS=20, aL=S_D3, aS=0.5 * S_D3, cL=cc, cS=cf, cash="1d"), "S"),
        "R_BASE_fnolong_rand": (dict(maskL=fnoE, maskS=None, kL=20, aL=1.0, aS=0.0, cL=cc), "L"),
    }


def ex_ante_beta(book, inst_ret, win=60, minobs=40, skip=20):
    """beta[t] from days t-win..t-1 (data <= t-1); first `skip` ramp-up days of the book excluded."""
    b = book.copy()
    b.iloc[:skip] = np.nan
    x = inst_ret.reindex(b.index)
    df = pd.DataFrame({"y": b.shift(1), "x": x.shift(1)})
    cov = df["y"].rolling(win, min_periods=minobs).cov(df["x"])
    var = df["x"].rolling(win, min_periods=minobs).var()
    beta = (cov / var).clip(0, 2)
    return beta.fillna(1.0)


out = {"conventions": {"S_CASH_D2": S_CASH, "S_D3": S_D3, "q_div_midcap_synthetic": Q_DIV,
                       "stock_futures_margin": 0.25, "index_futures_margin": 0.15}}
SER = {}
for cost_tag, cc, cf, hc in (("c50", 0.005, 0.0025, 1.0), ("c80", 0.008, 0.004, 1.6)):
    strat = strategies(cc, cf)
    rnd = randoms(cc, cf)
    for per in ("contig", "dev", "hold"):
        a, b = PERIODS[per]
        g0 = int(np.searchsorted(S.cal, np.datetime64(a)))
        phase_runs = {k: [] for k in strat}
        phase_rand = {k: [] for k in rnd}
        base_runs = []
        for k in range(5):
            st = str(S.cal[g0 + k])
            for nm, kw in strat.items():
                rr = T.run(prod, start=st, end_exit=b, **kw)
                phase_runs[nm].append(ser(rr))
                if nm == "BASE":
                    base_runs.append(rr)
                if k == 0 and per == "dev":
                    out.setdefault("trade_stats_phase0_dev_" + cost_tag, {})[nm] = {
                        x: rr[x] for x in ("long_trades", "long_mean_net", "long_hit", "short_trades",
                                           "short_mean_net_price_only", "short_hit_price_only", "beta_ratio_mean")}
            for nm, (kw, mode) in rnd.items():
                seeds_daily = []
                for sd in SEEDS:
                    kws = dict(kw)
                    if mode in ("S", "LS"):
                        kws["seedS"] = 100 + sd
                    if mode in ("L", "LS"):
                        kws["seedL"] = sd
                    rr = T.run(prod if mode == "S" else None, start=st, end_exit=b, **kws)
                    seeds_daily.append(ser(rr))
                phase_rand[nm].append(pa(seeds_daily))
        for nm in strat:
            SER[f"{nm}|{per}|{cost_tag}"] = pa(phase_runs[nm])
        for nm in rnd:
            SER[f"{nm}|{per}|{cost_tag}"] = pa(phase_rand[nm])
        # ---------------- index hedges (D1) on the BASE phase books
        if per == "contig" and cost_tag == "c50":
            base_contig = SER["BASE|contig|c50"]
            BETA = {"n50fut": ex_ante_beta(base_contig, fut50.pct_change()),
                    "msfut": ex_ante_beta(base_contig, ms_fut.pct_change())}
            out["beta_ex_ante"] = {h: {"mean_dev": float(v.loc["2023-03-01":"2025-12-31"].mean()),
                                       "mean_2026": float(v.loc["2026-01-01":].mean()),
                                       "min": float(v.loc["2023-03-01":].min()), "max": float(v.loc["2023-03-01":].max())}
                                   for h, v in BETA.items()}
            SER["beta_n50fut"] = BETA["n50fut"]
            SER["beta_msfut"] = BETA["msfut"]
        hed = {"D1a": ("n50fut", "one"), "D1b": ("n50fut", "beta"), "D1c": ("msfut", "beta")}
        for hn, (inst, bmode) in hed.items():
            runs_h, hn_list = [], []
            for k, rr in enumerate(base_runs):
                dts = pd.DatetimeIndex(rr["_dates"])
                gi = np.searchsorted(S.cal, rr["_dates"])
                expl = rr["_expL"]
                expl_next = np.r_[expl[1:], expl[-1]]
                fl = HEDGE_LEVEL[inst].reindex(dts).values
                bt = np.ones(len(dts)) if bmode == "one" else BETA[inst].reindex(dts).fillna(1.0).values
                reset = np.zeros(len(dts), bool)
                reset[::5] = True
                hr, hnot, cst = hedge_overlay(rr["_daily"], dts, expl_next, fl, cl1d[gi], bt, reset, month_end[gi],
                                              c_adj=1e-4 * hc, c_roll=2e-4 * hc)
                runs_h.append(pd.Series(hr, index=dts))
                hn_list.append(pd.Series(hnot, index=dts))
            SER[f"{hn}|{per}|{cost_tag}"] = pa(runs_h)
            if cost_tag == "c50":
                out.setdefault("hedge_notional_over_nav", {})[f"{hn}|{per}"] = float(pa(hn_list).mean())
        C.log(cost_tag, per, "done", {nm: round(float(np.prod(1 + SER[f'{nm}|{per}|{cost_tag}']) ** (252 / len(SER[f'{nm}|{per}|{cost_tag}'])) - 1), 4)
                                      for nm in list(strat) + list(hed) + list(rnd)})
    # ---------------- D0 avoid veto (C.phase_avg, cached random/EW)
    for per in ("dev", "hold", "contig"):
        kw0 = dict(step=5, cost_bps=int(round(cc * 1e4)), select_quantile=(0.3, 1.0), sizing="equal")
        r0, sm, rm, em = C.phase_avg(S, prod, E, "liq2", 20, kw0, PERIODS[per] if per == "contig" else per, with_ew=True)
        SER[f"D0|{per}|{cost_tag}"] = sm
        SER[f"EW|{per}|{cost_tag}"] = em
        SER[f"R_D0_rand70|{per}|{cost_tag}"] = rm
        out[f"D0_phase_avg_{per}_{cost_tag}"] = r0
        rb, sb, rbm, ebm = C.phase_avg(S, prod, E, "liq2", 20, dict(C.BASE_KW, cost_bps=int(round(cc * 1e4))),
                                       PERIODS[per] if per == "contig" else per, with_ew=True)
        SER[f"RAND|{per}|{cost_tag}"] = rbm
        out[f"BASE_phase_avg_{per}_{cost_tag}"] = rb
        chk = float(np.abs(sb.values - SER[f"BASE|{per}|{cost_tag}"].reindex(sb.index).values).max())
        out[f"BASE_check_vs_C_phase_avg_{per}_{cost_tag}"] = chk
        C.log("D0/BASE", cost_tag, per, "D0", round(r0["pa_cagr"], 4), "EW", round(r0["pa_ew_cagr"], 4),
              "BASE", round(rb["pa_cagr"], 4), "rand", round(rb["pa_random_cagr"], 4), "check", chk)
    C.save("s3_runs_meta", out)
# market / cash series aligned to cal
SER["N500"] = n500.pct_change()
SER["CASH1D"] = r1d
SER["N50FUT"] = fut50.pct_change()
SER["MSFUT"] = r_ms_fut
keys = list(SER)
np.savez(f"{LAB}/results/R3_twoway/series_s3.npz", keys=np.array(keys),
         **{f"v{i}": SER[k].values.astype("float64") for i, k in enumerate(keys)},
         **{f"d{i}": SER[k].index.values.astype("datetime64[D]").astype(str) for i, k in enumerate(keys)})
C.save("s3_runs_meta", out)
C.log("saved series", len(keys))
