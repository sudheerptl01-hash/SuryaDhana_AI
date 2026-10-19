import sys
import numpy as np, pandas as pd
LAB = "/tmp/claude-0/-home-user-SuryaDhana-AI/09834923-517b-5951-ac02-867e5810ca36/scratchpad/lab"
sys.path.insert(0, LAB)
import lablib as L
P = L.load_panel(["date", "entity", "symbol", "open", "high", "low", "close", "raw_close", "seg_break", "label_block", "ca_event"])
F = L.load_features(["atr_pct"])
fw = L.Fwd(P); S = L.Sim(P, F, fw)
E = np.load(f"{LAB}/results/R2_rel/meta.npz")["E"]
sc = np.load(f"{LAB}/results/R2_rel/wf_h20_neumom_RANK.npz")["score"].astype("float64")
st = S.run(sc, E, 20, step=5, top_k=20, cost_bps=50, start=L.DEV[0], end_exit=L.DEV[1], keep_trades=True)
lb = P["label_block"].values.astype(bool); n = len(P)
rows=[]
for (d, i, net, Kx, forced) in st["_trades"]:
    if Kx < 20:
        j = i + Kx + 1
        rows.append(dict(signal=d, symbol=P.symbol.iat[i], Kx=Kx, net=round(net,4), lb_date=str(P.date.iat[j])[:10] if j<n else None,
                         lb=bool(lb[j]) if j<n else None, ca_event=P.ca_event.iat[j] if j<n else None,
                         adj_move=round(P.close.iat[j]/P.close.iat[j-1]-1,3) if j<n else None,
                         raw_move=round(P.raw_close.iat[j]/P.raw_close.iat[j-1]-1,3) if j<n else None))
print(pd.DataFrame(rows).to_string())
