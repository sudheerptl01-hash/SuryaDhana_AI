# S3 Leader-dip — results (2026-10-14 21:00, panel snapshot same day)
- Pre-registered expectation (PLAN §S3): delivery likely fails on costs; futures is the live candidate; both failing = a 'stay away' verdict, which is a wanted outcome.
- Verdicts: `{"delivery Gate A": "FAIL", "futures Gate A": "FAIL"}`
- config: `{"mom_pct": 0.7, "slots": 5, "hold": 5, "cooldown": 10, "circuit": 0.095, "lot_proxy": {"before_2024-11-20": 500000.0, "after": 1500000.0}, "windows": {"smoke": ["2025-10-01", "2026-10-13"], "gateA": ["2020-01-01", "2026-10-13"], "gateB": ["2011-01-01", "2019-12-31"]}}`

## Delivery ₹10L — Gate A 2020-01-01 → 2026-10-13
- {"entries": 1498, "win_rate": 47.19626168224299, "avg_net": -0.0055180741491053075, "median_net": -0.36567133092487714, "forced_exits": 0, "entries_per_year": 220.8899878885749}
### Gate A (delivery): **FAIL**
- ❌ 1a CAGR -4.28% > NIFTY 9.63% (price-to-price)
- ❌ 1b CAGR -4.28% > EW universe 26.50%
- ❌ 2  maxDD -58.1% ≥ −30% and ≥ 1.25×NIFTY (-48.0%)
- ❌ 3  IR -0.52 ≥ 0.45
- ✅ 4  decisions 1498 ≥ 30

```
      strategy  nifty    ew
2020     -13.8   14.8  18.6
2021      60.1   24.1  67.6
2022     -25.8    4.3   9.5
2023       6.4   20.0  56.0
2024     -12.3    8.8  39.7
2025     -30.7   10.5  -1.4
2026      12.3  -13.0   5.2
```

## Delivery — Gate B: **not run** (Gate A failed, per protocol)

## Futures ₹1Cr (1 lot/name, dated lot proxy; spot opens proxy fills) — Gate A
- {"entries": 923, "win_rate": 53.19609967497292, "avg_net": 0.2954125477208864, "median_net": 0.44080391221374043, "forced_exits": 1, "entries_per_year": 136.10244247073072}
### Gate A (futures): **FAIL**
- ❌ 1a CAGR 1.94% > NIFTY 9.63% (price-to-price)
- ❌ 1b CAGR 1.94% > EW universe 26.50%
- ✅ 2  maxDD -17.7% ≥ −30% and ≥ 1.25×NIFTY (-48.0%)
- ❌ 3  IR -0.52 ≥ 0.45
- ✅ 4  decisions 923 ≥ 30
- Gate B: **N/A** — fut_close data begins 2019-10 (Amendments v2 §2).

```
      strategy  nifty    ew
2020       3.2   14.8  18.6
2021       8.1   24.1  67.6
2022      -4.3    4.3   9.5
2023       3.2   20.0  56.0
2024      -1.0    8.8  39.7
2025       8.1   10.5  -1.4
2026      -3.3  -13.0   5.2
```

## Verdict (read the gates right)

**Delivery ₹10L: STAY AWAY — confirmed.** 1,498 trades, win 47.2%, average net **−0.006% per trade**: the gross
dip edge is consumed whole by the ~1.05% delivery round trip, compounding to −4.3%/yr with a −58% drawdown.
This is the pre-registered expectation landing exactly; it also replicates the handbook post-mortem. No revision
can rescue a per-trade edge smaller than its own costs — the avoid rule is the product.

**Futures ₹1Cr (as specced): FAILS the gates, but the signal itself survives futures costs.** 923 trades,
win 53.2%, average net **+0.295%/trade** (median +0.44%), positive in 5 of 7 years (2022, 2026 negative).
Spot-check of fills passed (entry/exit opens, t+6 exit, 200-DMA condition). The economics:
- average concurrent exposure only **₹23.4L** on ₹1Cr (1-lot sizing; idle cash earns 0 by PLAN),
- total net P&L ₹13.4L over 6.8y = **+8.5%/yr on deployed exposure**, but **+1.9%/yr on total capital** → fails
  1a/1b/IR by construction, while maxDD −17.7% passes.
- Sensitivity (labelled, not a gate): idle cash at 6% would lift total-capital CAGR to roughly ~8%/yr — still
  below EW-L's 26.5% in this window.

**What this licenses:** per Amendments v2 §8, sizing/cash-yield are execution mechanics — the PM may file ONE
revision (e.g. slot = min(20% of capital, k lots) with liquid-fund idle cash) and re-gate; otherwise S3 is a
stay-away in book form and survives only as (a) the standing avoid rule's mirror and (b) a small futures overlay
candidate for a larger multi-strategy book. The ₹23L-exposure cap also means the edge's total capacity at 5 names
× 1 lot is a few lakh rupees a year — honest ceiling, stated.
