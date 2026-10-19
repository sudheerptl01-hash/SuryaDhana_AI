"""J_stat check 1: how often do top-20 picks (vs random) get a forced exit because a label_block row
or a segment break appears inside the 20-day window, and what move does the simulator 'dodge'?
Sim.run truncates a position at the last valid close BEFORE a label_block row / segment end, which is
look-ahead if those events are real price moves. We measure frequency and the dodged return
(close at the first bar after the block/break vs the forced-exit close) for strategy vs random."""
import sys
import numpy as np
import pandas as pd

LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
import lablib as L  # noqa: E402

P = L.load_panel(["date", "entity", "open", "high", "low", "close", "raw_close", "seg_break", "label_block"])
F = L.load_features(["atr_pct"])
fw = L.Fwd(P)
S = L.Sim(P, F, fw)
E = np.load(f"{LAB}/results/R2_rel/meta.npz")["E"]
sc = np.load(f"{LAB}/results/R2_rel/wf_h20_neumom_RANK.npz")["score"].astype("float64")
lb = P["label_block"].values.astype(bool)
c = P["close"].values.astype("float64")
ent = P["entity"].values
n = len(P)
h = 20


def classify(trades):
    rows = np.array([t[1] for t in trades])
    Kx = np.array([t[3] for t in trades])
    forced = np.array([t[4] for t in trades])
    net = np.array([t[2] for t in trades])
    out = {"trades": len(rows), "forced": int(forced.sum())}
    # cause of truncation at bar Kx (< h): the row i+Kx+1 is (a) label_block, (b) beyond segment end, (c) calendar cut
    nxt = rows + Kx + 1
    nxt_c = np.clip(nxt, 0, n - 1)
    beyond_seg = nxt > fw.end[rows]
    is_lb = (~beyond_seg) & lb[nxt_c]
    trunc = Kx < h
    cause_lb = trunc & is_lb
    cause_seg = trunc & beyond_seg
    cause_cal = trunc & ~is_lb & ~beyond_seg
    out.update(n_trunc=int(trunc.sum()), n_lb=int(cause_lb.sum()), n_seg=int(cause_seg.sum()), n_cal=int(cause_cal.sum()))
    # dodged move: close of the first row after the exit bar (same entity) vs exit close
    exit_row = rows + Kx
    after = np.clip(exit_row + 1, 0, n - 1)
    same_ent = ent[after] == ent[exit_row]
    dodged = np.where(same_ent, c[after] / c[exit_row] - 1, np.nan)
    for nm, m in (("lb", cause_lb), ("seg", cause_seg)):
        d = dodged[m]
        out[f"dodged_{nm}_n_resumed"] = int(np.isfinite(d).sum())
        out[f"dodged_{nm}_mean"] = float(np.nanmean(d)) if np.isfinite(d).any() else None
        out[f"dodged_{nm}_median"] = float(np.nanmedian(d)) if np.isfinite(d).any() else None
        out[f"dodged_{nm}_p10"] = float(np.nanpercentile(d, 10)) if np.isfinite(d).sum() > 2 else None
        # contribution to book mean trade if the dodged move had been taken (per trade, bps)
        out[f"dodged_{nm}_bps_per_trade"] = float(np.nansum(d) / len(rows) * 1e4)
    out["mean_trade_net_bps"] = float(net.mean() * 1e4)
    return out


res = {}
for per, (a, b) in {"dev": L.DEV, "hold": ("2026-01-01", None)}.items():
    st = S.run(sc, E, h, step=5, top_k=20, cost_bps=50, start=a, end_exit=b, keep_trades=True)
    res[f"strategy_{per}"] = classify(st["_trades"])
    rr = [classify(S.run(None, E, h, step=5, top_k=20, cost_bps=50, start=a, end_exit=b, keep_trades=True,
                         random_seed=s)["_trades"]) for s in (1, 2, 3, 4, 5)]
    res[f"random_{per}"] = {k: float(np.nanmean([x[k] if x[k] is not None else np.nan for x in rr])) for k in rr[0]}
for k, v in res.items():
    print(k, {a: (round(b, 4) if isinstance(b, float) else b) for a, b in v.items()})

# universe-level: how often does a 20d window starting on an elig row contain a label_block / seg end,
# and what is the label_block day's adjusted close-to-close move (the 'unexplained' moves)
lbr = np.flatnonzero(lb)
prev_same = (lbr > 0) & (ent[np.clip(lbr - 1, 0, n - 1)] == ent[lbr])
mv = np.where(prev_same, c[lbr] / c[np.clip(lbr - 1, 0, n - 1)] - 1, np.nan)
print("label_block rows:", len(lbr), "adj move on lb day: median", np.nanmedian(mv), "mean", np.nanmean(mv),
      "share < -30%", np.nanmean(mv < -0.3), "share > +30%", np.nanmean(mv > 0.3), "share |mv|<5%", np.nanmean(np.abs(mv) < 0.05))
