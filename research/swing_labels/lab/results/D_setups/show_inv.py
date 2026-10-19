import sys
import pandas as pd
a = pd.read_csv("s6_invest_agg.csv")
pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
keep = sys.argv[1].split(",") if len(sys.argv) > 1 else None
q = a if keep is None else a[a.config.isin(keep)]
sz = sys.argv[2] if len(sys.argv) > 2 else "slot"
ex = sys.argv[3] if len(sys.argv) > 3 else "time"
q = q[(q.sizing == sz) & (q.exit == ex)]
for w in ("dev", "hold", "full"):
    for c in (50, 80):
        s = q[(q.window == w) & (q.cost == c)]
        print(f"== window={w} cost={c} sizing={sz} exit={ex}")
        print(s[["config", "top_k", "step", "trades", "avg_exposure_slot", "hit_rate", "mean_trade_net_bps", "cagr", "sharpe", "max_dd",
                 "y2023", "y2024", "y2025", "y2026"]].round(3).to_string(index=False))
