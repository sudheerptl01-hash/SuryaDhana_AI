"""R3_book item 4: operations + tax illustration on the contiguous window 2023-01-01 -> 2026-10-14.
Books: frozen PROD book E0 and the executable-carry book X3 (phase-averaged, 50 bps). Turnover by calendar year
from BookSim accounting (STT = 0.1% of buys + 0.1% of sells, delivery).
Tax model (Indian resident individual, calendar-year realisation, tax paid at year end from the book):
 * STCG: 15% on gains realised before 23-Jul-2024, 20% from 23-Jul-2024; STCL carried forward and set off
   against later gains. STT is NOT deductible from capital gains (s.48) -> taxable = net P&L + STT paid.
 * Alternative: business income at 31.2% (30% + 4% cess, no surcharge), STT deductible, losses carried forward.
 * Buy-and-hold Nifty 500 (PRICE index; ~1.2%/yr dividends missing): one sale at the end, LTCG 12.5% above
   Rs 1.25 lakh (sale after 23-Jul-2024), illustrated for Rs 50 lakh and Rs 5 crore of capital.
Open positions at the window end are treated as realised (<= 20 trading days of P&L)."""
import numpy as np
import pandas as pd

from bk_setup import setup, C, L, phase_runs, avg_series, pa_stats, turnover_summary

T = setup()
S, E, BS, prod = T["S"], T["E"], T["BS"], T["prod"]
PER = ("2023-01-01", None)
CUT = pd.Timestamp("2024-07-23")

books = {}
for nm, kw in (("E0", {}), ("X3", dict(carry="exec"))):
    runs, _ = phase_runs(BS, prod, E, PER, dict(kw, cost_bps=50))
    sm = avg_series(runs)
    # yearly traded multiple of average equity (buys + sells), averaged over phases
    yrs = sorted(set(sm.index.year))
    trad = {}
    for y in yrs:
        vals = []
        for r in runs:
            if y in r["avg_eq"]:
                vals.append((r["acc"]["buy"].get(y, 0.0) + r["acc"]["sell"].get(y, 0.0)) / r["avg_eq"][y])
        trad[int(y)] = float(np.mean(vals))
    books[nm] = {"daily": sm, "traded_multiple_by_year": trad, "turnover": turnover_summary(runs),
                 "avg_names_held": float(np.mean([r["avg_names_held"] for r in runs])), "stats": pa_stats(sm)}
    C.log(nm, C.short(books[nm]["stats"]), C.short(trad, 3))


def tax_book(sm, trad, mode):
    V = 1.0
    cf = 0.0
    rows = {}
    for y in sorted(set(sm.index.year)):
        r = sm[sm.index.year == y]
        gf = np.cumprod(1 + r.values)
        pre = r.index < CUT
        g_tot = gf[-1] - 1
        g_a = (gf[pre][-1] - 1) if pre.any() else 0.0           # growth up to 22-Jul-2024 (only matters in 2024)
        V_avg = V * gf.mean()
        stt = 0.001 * trad[int(y)] * V_avg          # trad = in-year (buys + sells) / average equity of that year
        gain = V * g_tot
        if mode == "stcg":
            frac_a = (pre.sum() / len(r))
            Ga = V * g_a + stt * frac_a
            Gb = V * (g_tot - g_a) + stt * (1 - frac_a)
            if y < 2024:
                Ga, Gb = Ga + Gb, 0.0
            elif y > 2024:
                Ga, Gb = 0.0, Ga + Gb
            if Ga < 0:
                Gb, Ga = Gb + Ga, 0.0
            if Gb < 0:
                Ga, Gb = Ga + Gb, 0.0
            if Ga + Gb <= 0:
                cf += -(Ga + Gb)
                tax = 0.0
            else:
                use = min(cf, Gb)
                Gb -= use
                cf -= use
                use = min(cf, Ga)
                Ga -= use
                cf -= use
                tax = 0.15 * max(Ga, 0) + 0.20 * max(Gb, 0)
        else:  # business income, STT deductible
            taxable = gain
            if taxable <= 0:
                cf += -taxable
                tax = 0.0
            else:
                use = min(cf, taxable)
                taxable -= use
                cf -= use
                tax = 0.312 * taxable
        V_end = V * (1 + g_tot) - tax
        rows[int(y)] = {"pre_tax_return": float(g_tot), "stt_paid_frac_of_start_equity": float(stt / V),
                        "tax_paid_frac_of_start_equity": float(tax / V), "post_tax_return": float(V_end / V - 1),
                        "loss_carried_forward_after": float(cf)}
        V = V_end
    yrs = len(sm) / 252
    pre_cagr = float(np.prod(1 + sm.values) ** (1 / yrs) - 1)
    return {"by_year": rows, "pre_tax_cagr": pre_cagr, "post_tax_cagr": float(V ** (1 / yrs) - 1),
            "tax_drag_cagr": pre_cagr - float(V ** (1 / yrs) - 1), "final_wealth_pre": float(np.prod(1 + sm.values)),
            "final_wealth_post": float(V)}


out = {"window": [str(books["E0"]["daily"].index[0])[:10], str(books["E0"]["daily"].index[-1])[:10]]}
for nm in books:
    out[nm] = {"stats": books[nm]["stats"], "turnover": books[nm]["turnover"],
               "avg_names_held": books[nm]["avg_names_held"], "traded_multiple_by_year": books[nm]["traded_multiple_by_year"],
               "tax_stcg": tax_book(books[nm]["daily"], books[nm]["traded_multiple_by_year"], "stcg"),
               "tax_business_income": tax_book(books[nm]["daily"], books[nm]["traded_multiple_by_year"], "business")}
    C.log(nm, "tax", C.short({k: v for k, v in out[nm]["tax_stcg"].items() if k != "by_year"}),
          C.short({k: v for k, v in out[nm]["tax_business_income"].items() if k != "by_year"}))

# buy-and-hold Nifty 500 (price index) on the same dates
idx = books["E0"]["daily"].index
n5 = L.market_series("Nifty 500")["close"].astype("float64")
n5.index = pd.DatetimeIndex(n5.index)
lv = n5.reindex(n5.index.union(idx)).ffill().reindex(idx)
g = float(lv.iloc[-1] / lv.iloc[0] - 1)
yrs = len(idx) / 252
bh = {"pre_tax_cagr": float((1 + g) ** (1 / yrs) - 1), "total_return": g}
for cap_nm, cap in (("Rs50L", 5e6), ("Rs5cr", 5e7)):
    gain = cap * g
    tax = 0.125 * max(0.0, gain - 1.25e5)   # STT (not deductible) and brokerage ignored for buy-and-hold
    post = (cap * (1 + g) - tax) / cap
    bh[cap_nm] = {"ltcg_tax_frac_of_capital": float(tax / cap), "post_tax_cagr": float(post ** (1 / yrs) - 1),
                  "tax_drag_cagr": float((1 + g) ** (1 / yrs) - post ** (1 / yrs))}
out["nifty500_buy_hold"] = bh
C.log("B&H", C.short(bh))
C.save("item4_ops_tax", out)
np.savez_compressed(f"{C.OUT}/pa_series_contig_books.npz",
                    **{f"{k}__s": v["daily"].values for k, v in books.items()},
                    **{f"{k}__dates": v["daily"].index.values.astype("datetime64[D]").astype(str) for k, v in books.items()})
C.log("done")
