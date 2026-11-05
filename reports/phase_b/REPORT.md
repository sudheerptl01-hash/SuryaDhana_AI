# Phase B: monthly allocator after real costs and tax

Run: `scripts/phase_b_allocator.py` (~50 s) · NSE full bhavcopy, survivorship-free (delisted names included), split/bonus-adjusted · Nov 2020 → Sep 2026 · ICICI MoneySaver costs (0.29% brokerage + STT + stamp + GST + ₹20 DP) · whole shares only · STCG/LTCG tax settled each financial year · cash earns 6%/yr.
Discovery = Nov 2020 → Jun 2024, holdout = Jul 2024 → Sep 2026. The rules were fixed before the run (see the script docstring).

## Benchmark: NIFTY 50 (price index)
| | CAGR | Max drawdown |
|---|---|---|
| Full period | 12.3% | −17.2% |
| Discovery (2020–24) | 21.8% | −17.2% |
| Holdout (2024–26) | −1.9% | −15.8% |

## Headline results (₹5L; ₹1L and ₹10L are within ~1–2 points)
| Variant | CAGR after costs+tax | Max DD | 2020–24 vs NIFTY | 2024–26 vs NIFTY | Costs paid | Tax paid |
|---|---|---|---|---|---|---|
| Momentum 12-1, top 20, no filter | **32.0%** | −37.5% | +19.9 pts | **+19.4 pts** | ₹1.69L | ₹2.48L |
| NSE momentum, top 20, no filter | 29.0% | −32.7% | +22.4 pts | +9.1 pts | ₹2.29L | ₹2.39L |
| NSE momentum, top 20, NIFTY-200DMA + vol target | 25.1% | **−22.7%** | +19.8 pts | +3.9 pts | ₹1.88L | ₹2.52L |
| Momentum + low-vol blend, top 10 | 21.4% | −37.9% | +8.0 pts | +10.4 pts | ₹1.51L | ₹1.64L |

- **All 12 momentum variants beat NIFTY after costs and tax in *both* periods** (14 of 24 variants overall). Low-volatility on its own didn't.
- **Against the pre-registered gate, nothing passes.** Deflated Sharpe is ~0.82 (the gate is 0.95), and every stock-only variant fell more than −15%. Six years is too short to prove significance after testing 24 variants.
- Costs and tax are large (together ₹3.5–4.5L on ₹5L over 6 years), and returns are shown *after* both.

## Meeting the −15% drawdown budget: strategy + liquid fund
The equity share is chosen from the **2020–24 drawdown only** (share = 15% ÷ discovery max DD), then checked on 2024–26:

| Mix | Equity share | Full CAGR | Full max DD | 2024–26 CAGR | 2024–26 max DD |
|---|---|---|---|---|---|
| NSE momentum top 20 + filter + vol target | 66% | **18.8%** | **−13.0%** | 3.5% (NIFTY −1.9%) | −8.0% |
| Momentum 12-1 top 20 | 40% | 16.7% | −14.4% | 11.4% | −13.1% |

Both stay inside −15% on data they weren't sized on, and both beat NIFTY (12.3%, −17.2%) with a smaller drawdown.

## Honest caveats
1. **One market regime.** Nov 2020–2024 was a historic mid-cap boom that flatters momentum. The data doesn't yet cover a full momentum crash (2018 mid-cap crash, 2020 COVID crash).
2. Returns are price-only on both sides (dividends excluded), which roughly cancels versus NIFTY.
3. Liquid-fund interest in the mix is taxed at your slab rate (not deducted here).
4. Fills at the next day's open; no impact cost modelled beyond brokerage, fine at ₹1–10L in liquid top-300 names.

## Verdict
**Promising, not proven.** Momentum beats NIFTY after your real costs and tax in both periods, and a strategy + liquid-fund mix meets −15%. But the evidence covers only 6 years of one regime, and the multiple-testing gate fails.

**Next step:** extend history back to ~2010 using NSE's older bhavcopy archive, then re-run this exact grid unchanged on 2010–2020. Those 10 years (including the 2011, 2015–16, 2018 and 2020 crashes) have never been looked at, so they make a clean out-of-sample test.
