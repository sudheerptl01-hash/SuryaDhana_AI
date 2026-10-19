"""Stage 6: investability (setup / setup-AND-score / every-bar model / random baselines).

fastsim() is a line-by-line port of L.portfolio_sim (staggered ceil(h/step) sleeves, picks on every
step-th date, next-open entry, time exit at close[t+h] with forced exit at last close on broken
windows, or barrier exit = L.barrier_labels ret).  It is validated against L.portfolio_sim below.
Extra (not in lablib): 'slot' sizing -- each pick gets 1/top_k of the sleeve, the rest stays in cash
(0%), which is the realistic way to run a sparse event strategy; lablib's default spreads the sleeve
over however many picks exist (1 pick = 100% in one stock).
Windows: full 2023-01-01..2026-09-10; dev = signals <= DEV_END; hold = 2026-01-01..2026-09-10
(dev/hold metrics re-compound the cohorts of the window from 1.0).
"""
import numpy as np
import pandas as pd

from common import L, OUT, H, PT, SL, DEV_END, HOLD_START, HOLD_END, load_base, load_res, save, T

t = T()
B = load_base()
names = list(B["setup_names"])
R = load_res()
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
fw = L.Fwd(P)
dates = P["date"].values.astype("datetime64[D]")
n = len(P)
STEP = 5

# ---------------- trade returns ----------------
e = fw.at(P["open"].values, 1)
x = fw.at(P["close"].values, H)
tr_time = x / e - 1
last = np.full(n, np.nan)
for k in range(1, H + 1):
    xk = fw.at(P["close"].values, k)
    last = np.where(np.isnan(xk), last, xk)
fb = last / e - 1
tr_time = np.where(np.isnan(tr_time) & np.isfinite(e), fb, tr_time)
tr_bar = B["ret_L"].astype("float64")
tr_bar_s = B["ret_S"].astype("float64")
tr_time_s = -tr_time
TR = {("long", "time"): tr_time, ("long", "barrier"): tr_bar, ("short", "time"): tr_time_s,
      ("short", "barrier"): tr_bar_s}
t("trade returns")


def picks_run(score, mask, tr, top_k, side="long", start="2023-01-01", end=HOLD_END, seed=None,
              step=STEP, grid=None):
    """grid=None -> lablib behaviour (signal dates = every step-th date ON WHICH THE MASK HAS ROWS);
    grid=<bool row mask> -> signal dates = every step-th trading date of that universe (sparse setups:
    a grid date without events is a cash cohort)."""
    s = np.asarray(score, dtype="float64")
    m = np.asarray(mask, bool) & (~np.isnan(s) if seed is None else True)
    cal = np.unique(dates[m if grid is None else grid])
    cal = cal[(cal >= np.datetime64(start)) & (cal <= np.datetime64(end))]
    sig = cal[::step]
    rng = np.random.default_rng(seed if seed is not None else 0)
    okt = m & np.isfinite(tr)
    ii = np.flatnonzero(okt)
    by = pd.Series(ii).groupby(dates[okt]).apply(np.array)
    coh = []
    for d in sig:
        cand = by.get(d)
        if cand is None or len(cand) == 0:
            coh.append((d, np.array([], int)))
            continue
        if seed is not None:
            pick = rng.choice(cand, size=min(top_k, len(cand)), replace=False)
        else:
            sc = s[cand]
            order = np.argsort(-sc if side == "long" else sc, kind="stable")
            pick = cand[order][:top_k]
        coh.append((d, pick))
    return coh


def metrics(coh, tr, cost_bps, top_k, sizing="ew", lo=None, hi=None, step=STEP):
    cs = [(d, p) for d, p in coh if (lo is None or d >= np.datetime64(lo)) and (hi is None or d <= np.datetime64(hi))]
    if not cs:
        return {}
    S = int(np.ceil(H / step))
    cr = []
    for d, p in cs:
        if len(p) == 0:
            cr.append(0.0)
            continue
        net = tr[p] - cost_bps / 1e4
        cr.append(float(net.mean()) if sizing == "ew" else float(net.sum() / top_k))
    cr = np.array(cr)
    sleeves = np.ones(S)
    eq = []
    for c, r in enumerate(cr):
        sleeves[c % S] *= (1 + r)
        eq.append(sleeves.mean())
    eq = np.array(eq)
    stepret = np.r_[eq[0] - 1, eq[1:] / eq[:-1] - 1]
    cd = np.array([d for d, _ in cs])
    years = max((cd[-1] - cd[0]).astype(int) / 365.25, 1e-9) + H / 252
    allp = np.concatenate([p for _, p in cs if len(p)]) if any(len(p) for _, p in cs) else np.array([], int)
    tnet = tr[allp] - cost_bps / 1e4
    dd = eq / np.maximum.accumulate(eq) - 1
    yr = pd.Series(stepret, index=pd.DatetimeIndex(cd))
    by_year = yr.groupby(yr.index.year).apply(lambda s_: float(np.prod(1 + s_) - 1)).to_dict()
    npk = np.array([len(p) for _, p in cs])
    return {"trades": int(len(allp)), "hit_rate": float((tnet > 0).mean()) if len(tnet) else None,
            "mean_trade_net_bps": 1e4 * float(tnet.mean()) if len(tnet) else None,
            "cagr": float(eq[-1] ** (1 / years) - 1), "total_return": float(eq[-1] - 1),
            "sharpe": float(stepret.mean() / stepret.std() * np.sqrt(252 / step)) if stepret.std() > 0 else None,
            "max_dd": float(dd.min()), "by_year": {int(k): v for k, v in by_year.items()},
            "avg_picks": float(npk.mean()), "share_cohorts_empty": float((npk == 0).mean()),
            "avg_exposure_slot": float(np.minimum(npk, top_k).mean() / top_k)}


# ---------------- validation vs L.portfolio_sim ----------------
F = L.load_features(["sector", "atr_pct"])
sc_all = np.load(f"{OUT}/wf_ALL.npz")["score"].astype("float64")
U = B["U"]
val = {}
for ex in ("time", "barrier"):
    ref = L.portfolio_sim(sc_all, U, P, F, fw, H, step=STEP, top_k=20, exit_rule=ex, pt=PT, sl=SL,
                          cost_bps=50, start="2023-01-01", end=HOLD_END)
    mine = metrics(picks_run(sc_all, U, TR[("long", ex)], 20), TR[("long", ex)], 50, 20)
    val[ex] = {"lablib_cagr": ref["cagr"], "fast_cagr": mine["cagr"], "lablib_sharpe": ref["sharpe"],
               "fast_sharpe": mine["sharpe"], "lablib_trades": ref["trades"], "fast_trades": mine["trades"]}
    refr = L.portfolio_sim(None if False else sc_all, U, P, F, fw, H, step=STEP, top_k=20, exit_rule=ex, pt=PT, sl=SL,
                           cost_bps=50, start="2023-01-01", end=HOLD_END, random_seed=1)
    miner = metrics(picks_run(sc_all, U, TR[("long", ex)], 20, seed=1), TR[("long", ex)], 50, 20)
    val[ex].update({"lablib_rand_cagr": refr["cagr"], "fast_rand_cagr": miner["cagr"]})
print("validation", val)
del F
t("validated")

# ---------------- configurations ----------------
yrs_all = pd.DatetimeIndex(dates).year.values


def setup_mask(nm):
    return B["setups"][:, names.index(nm)] & U


R1 = setup_mask("S1_bd20")
mm20 = B["mkt_mom20"]
R1dn = R1 & (mm20 < 0)
S = {"R1": R1, "R1dn": R1dn, "R3": setup_mask("S3_rslag"), "L7": setup_mask("L7_oversold_up"),
     "L3": setup_mask("L3_pullback"), "L1": setup_mask("L1_bo20"), "L6": setup_mask("L6_rslead")}
meta = {k: np.load(f"{OUT}/wf_{k}.npz")["score"].astype("float64") for k in ("R1", "R3", "L7", "L3")}
meta["R1dn"] = meta["R1"]


def pit_adjust(score, tag):
    """score minus the fold's training base rate -> >0 means 'model says better than average'."""
    thr = np.full(n, np.nan)
    for f in R[f"s4_wf_{tag}"]["folds"]:
        thr[yrs_all == f["year"]] = f["train_base_rate"]
    return score - thr


rand_seeds = (1, 2, 3)
configs = []  # (name, score, mask, top_k, seed or None, side[, step])
for sd in (1, 2, 3, 4, 5):
    configs.append(("U_random", None, U, 20, sd, "long"))
configs.append(("U_allbar_top20", sc_all, U, 20, None, "long"))
# daily-entry (step=1, 10 staggered sleeves) variants: use EVERY event, not only every 5th day
for sd in (1, 2, 3):
    configs.append(("D1_U_random_top5", None, U, 5, sd, "long", 1))
configs.append(("D1_U_allbar_top5", sc_all, U, 5, None, "long", 1))
for sn, sm in S.items():
    for sd in rand_seeds:
        configs.append((f"{sn}_events_random", None, sm, 20, sd, "long"))
    configs.append((f"{sn}_gate_allbar_top20", sc_all, sm, 20, None, "long"))
    configs.append((f"{sn}_gate_allbar_top5", sc_all, sm, 5, None, "long"))
    if sn in meta:
        configs.append((f"{sn}_meta_top20", meta[sn], sm, 20, None, "long"))
        configs.append((f"{sn}_meta_top5", meta[sn], sm, 5, None, "long"))
        tag = "R1" if sn == "R1dn" else sn
        adj = pit_adjust(meta[sn], tag)
        configs.append((f"{sn}_meta_PIT_top20", adj, sm & (adj > 0), 20, None, "long"))
for sn in ("R1", "R1dn", "R3", "L7"):
    for sd in rand_seeds:
        configs.append((f"D1_{sn}_events_random_top5", None, S[sn], 5, sd, "long", 1))
    configs.append((f"D1_{sn}_gate_allbar_top5", sc_all, S[sn], 5, None, "long", 1))
    configs.append((f"D1_{sn}_meta_top5", meta[sn], S[sn], 5, None, "long", 1))
    tag = "R1" if sn == "R1dn" else sn
    adj = pit_adjust(meta[sn], tag)
    configs.append((f"D1_{sn}_meta_PIT_top5", adj, S[sn] & (adj > 0), 5, None, "long", 1))
# short side (F&O proxy only): classic breakdown short and gap-down-fail short, all events
fno = B["fno"] & U
for sn in ("S1_bd20", "S5_gapfail", "S3_rslag"):
    for sd in rand_seeds:
        configs.append((f"SHORT_{sn}_fno_events_random", None, setup_mask(sn) & fno, 20, sd, "short"))
for sd in rand_seeds:
    configs.append(("SHORT_fno_random", None, fno, 20, sd, "short"))

windows = {"full": (None, None), "dev": (None, DEV_END), "hold": (HOLD_START, None)}
rows = []
store = {}
GRID = U  # signal grid = every step-th trading date of the eligible universe
for cfg in configs:
    name, sc, msk, k, sd, side = cfg[:6]
    stp = cfg[6] if len(cfg) > 6 else STEP
    for ex in ("time", "barrier"):
        tr = TR[(side, ex)]
        coh = picks_run(sc if sc is not None else np.zeros(n), msk, tr, k, side=side, seed=sd, step=stp, grid=GRID)
        for cost in (50, 80):
            for sizing in ("ew", "slot"):
                for wn, (lo, hi) in windows.items():
                    mtr = metrics(coh, tr, cost, k, sizing, lo, hi, step=stp)
                    r = {"config": name, "seed": sd, "exit": ex, "cost": cost, "sizing": sizing, "window": wn,
                         "top_k": k, "side": side, "step": stp}
                    r.update({kk: v for kk, v in mtr.items() if kk != "by_year"})
                    for yy, v in mtr.get("by_year", {}).items():
                        r[f"y{yy}"] = v
                    rows.append(r)
    t(name + ("" if sd is None else f" s{sd}"))
df = pd.DataFrame(rows)
df.to_csv(f"{OUT}/s6_invest_all.csv", index=False)
# average random seeds
num = [c for c in df.columns if c not in ("config", "seed", "exit", "sizing", "window", "side")]
agg = df.groupby(["config", "exit", "cost", "sizing", "window", "side", "top_k", "step"], dropna=False)[
    [c for c in num if c not in ("cost", "top_k", "step")]].mean().reset_index()
agg.to_csv(f"{OUT}/s6_invest_agg.csv", index=False)
bm = {w: L.benchmark(P, start=lo or "2023-01-01", end=hi or HOLD_END) for w, (lo, hi) in windows.items()}
save("s6_invest", {"validation_vs_lablib": val, "benchmark_nifty500": bm,
                   "agg": agg.to_dict(orient="records")})
pd.set_option("display.width", 250)
pd.set_option("display.max_columns", 30)
show = agg[(agg.cost == 50) & (agg.exit == "time") & (agg["window"] == "full")]
print(show[["config", "sizing", "top_k", "step", "trades", "avg_picks", "share_cohorts_empty", "hit_rate", "mean_trade_net_bps",
            "cagr", "sharpe", "max_dd", "y2023", "y2024", "y2025", "y2026"]].round(3).to_string())
t("done")
