from common import *
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["atr_pct"])
fw = L.Fwd(P); S0 = L.Sim(P, F, fw); S1 = SimX(P, F, fw)
B = load_base(); U = B['U']
sc = np.load(f"{L.LAB}/results/R2_rel/wf_h20_neumom_RANK.npz")["score"].astype("float64")
for kw in (dict(h=20, step=5, top_k=20), dict(h=10, step=1, top_k=20)):
    a = S0.run(sc, U & np.isfinite(sc), kw['h'], step=kw['step'], top_k=kw['top_k'])
    b = S1.run(sc, U & np.isfinite(sc), kw['h'], step=kw['step'], top_k=kw['top_k'])
    print(kw, 'max|diff| daily', np.abs(a['_daily_ret'] - b['_daily_ret']).max(), 'cagr', round(a['cagr'],4), round(b['cagr'],4),
          'exposure', round(a['exposure'],4), 'mean inv_daily', round(b['_invested'].mean(),4))
