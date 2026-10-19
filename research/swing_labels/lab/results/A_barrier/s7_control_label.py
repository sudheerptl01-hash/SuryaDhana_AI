"""Control label for the path-aware vs path-blind comparison: executable 20d time-only sign label
open[t+1] -> close[t+20], +1 if > +50 bps, -1 if < -50 bps, else 0; NaN where fw.ok(20) is false."""
import numpy as np
from abar import L, OUT, update_results
P = L.load_panel(["date", "entity", "open", "close", "seg_break", "label_block"])
F = L.load_features(["elig_base"])
fw = L.Fwd(P)
r = L.fwd_return(P, fw, 20)
lab = np.where(np.isnan(r), np.nan, np.where(r > 0.005, 1.0, np.where(r < -0.005, -1.0, 0.0)))
m = F["elig_base"].values & ~np.isnan(lab)
rep = L.event_report(lab, m, P, None)
rep["monthly_pos"].pop("series")
print(rep["overall"], rep["monthly_pos"], rep.get("corr_monthly_pos_vs_mkt_ret"))
np.savez_compressed(f"{OUT}/labels_control.npz", T20_time_pm50_long_lab=lab.astype(np.float32),
                    T20_time_pm50_long_ret=r.astype(np.float32))
update_results("control_T20_time_pm50_event", {"overall": rep["overall"], "by_year": rep["by_year"], "monthly_pos": rep["monthly_pos"]})
