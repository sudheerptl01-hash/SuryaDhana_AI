import time
from common import *
t=T()
P = L.load_panel(["date", "entity", "open", "high", "low", "close", "seg_break", "label_block"])
F = L.load_features(["atr_pct"])
fw = L.Fwd(P); S = L.Sim(P, F, fw)
B = load_base(); U=B['U']
t('init')
m = U & (B['bdd20']<0) & (B['volz_20']>1) & (B['mkt_mom20']<0)
for K in (5,20):
  for h in (10,20):
    t0=time.time(); r=S.run(None, m, h, step=1, top_k=K, random_seed=1)
    print(K,h,'%.2fs'%(time.time()-t0), {k:round(v,4) for k,v in r.items() if k in ('cagr','sharpe','max_dd','exposure','trades','mean_trade_net','hit_rate')})
t0=time.time(); r=S.run(None, U, 10, step=1, top_k=5, random_seed=1); print('U rand', '%.2fs'%(time.time()-t0), {k:round(v,4) for k,v in r.items() if k in ('cagr','sharpe','max_dd','exposure','trades','mean_trade_net')})
