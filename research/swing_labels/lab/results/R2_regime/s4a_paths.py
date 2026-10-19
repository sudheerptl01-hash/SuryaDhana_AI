"""Stage 4a: build and cache cohort paths for the books (all phases), verify vs L.Sim.run.

Books (h=20, step=5, cash_yield 6.5%, next-open entry, time exit, half cost each side):
  EW    universe equal-weight: every elig_base row, sizing='equal', select_quantile=(0,1)
  XR20  XR_neu walk-forward score, long top-20, slot sizing
  RND20 random top-20 on elig_base, seeds 1..5 (horizon-matched baseline for XR20)
Windows: DEV (2023-01-01 .. exits by 2025-12-31), HOLD (2026-01-01 .. 2026-10-14),
         PRE (2021-09-01 .. 2022-12-31; EW only — XR scores start 2023).
Costs: 50 and 80 bps round trip. Phases 0..4 (signal-calendar offset).
"""
import pickle
import sys
import time

import numpy as np

from common import OUT, L, save, PathSim, compose, CASH

t0 = time.time()
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["atr_pct"])
fw = L.Fwd(P)
Z = np.load(f"{OUT}/xrneu.npz")
U = Z["U"]
score = Z["score"].astype("float64")
zero = np.zeros(len(P))
S = PathSim(P, F, fw)
del F
print("loaded", round(time.time() - t0, 1), flush=True)

WIN = {"DEV": ("2023-01-01", "2025-12-31"), "HOLD": ("2026-01-01", None), "PRE": ("2021-09-01", "2022-12-31")}
H, STEP = 20, 5
jobs = sys.argv[1:] or ["verify", "build"]

if "verify" in jobs:
    ver = {}
    for book, kw in (("EW", dict(score=zero, sizing="equal", select_quantile=(0, 1))),
                     ("XR20", dict(score=score, sizing="slot", top_k=20)),
                     ("RND20_s1", dict(score=None, random_seed=1, sizing="slot", top_k=20))):
        a, b = WIN["DEV"]
        sc = kw.pop("score")
        ref = S.run(sc, U, H, step=STEP, cost_bps=50, start=a, end_exit=b, cash_yield=CASH, **kw)
        pp = S.paths(sc, U, H, step=STEP, cost_bps=50, start=a, end_exit=b, cash_yield=CASH, **kw)
        eq, r, inv, xs = compose(pp)
        ver[book] = {"ref_cagr": ref["cagr"], "mine_cagr": float(eq[-1] ** (1 / ((pp['dates'][-1] - pp['dates'][0]).astype(int) / 365.25)) - 1),
                     "max_abs_eq_diff": float(np.max(np.abs(eq - ref["_equity"]))),
                     "max_abs_exposure_diff": float(abs(inv.mean() - ref["exposure"])),
                     "ref_sharpe": ref["sharpe"], "ref_maxdd": ref["max_dd"], "ref_exposure": ref["exposure"],
                     "ref_trades": ref["trades"], "ref_mean_trade_net": ref["mean_trade_net"]}
        print(book, ver[book], flush=True)
    save("s4a_verify_pathsim_vs_Sim_run", ver)

if "build" in jobs:
    cache = {}
    for wname, (a, b) in WIN.items():
        for cost in (50, 80):
            for ph in range(5):
                books = [("EW", zero, dict(sizing="equal", select_quantile=(0, 1)))]
                if wname != "PRE":
                    books.append(("XR20", score, dict(sizing="slot", top_k=20)))
                    for sd in (1, 2, 3, 4, 5):
                        books.append((f"RND20_s{sd}", None, dict(random_seed=sd, sizing="slot", top_k=20)))
                for nm, sc, kw in books:
                    pp = S.paths(sc, U, H, step=STEP, cost_bps=cost, start=a, end_exit=b, cash_yield=CASH,
                                 phase=ph, **kw)
                    cache[(nm, wname, cost, ph)] = pp
            print(wname, cost, "done", round(time.time() - t0, 1), flush=True)
    with open(f"{OUT}/paths_cache.pkl", "wb") as fh:
        pickle.dump(cache, fh, protocol=pickle.HIGHEST_PROTOCOL)
    print("cached", len(cache), round(time.time() - t0, 1), flush=True)
