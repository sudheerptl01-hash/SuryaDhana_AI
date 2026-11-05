# Hedge overlay study — modeled puts (S1P) and liquid-yield sensitivity

Derivatives & risk analyst · 14 Oct 2026 · code `alpha_lab/strategies/overlays.py`.

> **MODELED, never gated.** Our store holds no market option prices. Puts here are Black-Scholes at
> sigma = India VIX × 1.1, r = 6%, European, no dividends. That understates crash-skew payoffs and misprices
> short-dated wings — and it especially flatters the *regime* stance below, because real 5%-OTM put IV in
> below-200-DMA regimes is far richer than VIX × 1.1 (panic skew). Shapes, not prices. The gateable hedge
> instrument in this lab remains the NIFTY **futures** short (S1H/S2H), which needs no volatility model.

## 1. Rolling a 1-month 5%-OTM NIFTY put on the index path, 2011-01 → 2026-10-13 (monthly grid)

| Stance | CAGR | maxDD | Months hedged | Avg premium, %/yr |
|---|---|---|---|---|
| Never (bare NIFTY price path) | 9.44% | −29.3% | 0 / 188 | 0 |
| Always hedged | 6.68% | −21.9% | 188 / 188 | ≈ 5.0 |
| Hedged only when NIFTY < 200-DMA | **9.47%** | **−21.5%** | 54 / 188 | ≈ 2.5 in hedged years, 0 in 4 of 16 |

- **Always-hedged** pays −2.76 CAGR points for ~7.4 points less drawdown. The insurance is real and the drag is
  real: 2017 cost 1.8%, 2020 cost 16.8% of notional in premiums (partly refunded by the Feb/Mar-2020 payoffs).
- **Regime-hedged looks free in the model (+0.03 pts vs never, with the same DD cut as always-hedged).** That is
  the model's skew-blindness talking: the stance buys puts exactly when real IV skew is most expensive. Treat the
  honest expectation as "crash-tail cut for a low-single-digit annual cost in hedged regimes", not free.
- Where the payoffs came from (always-hedged, top months): Feb-2020 +18.3% of notional (index −23%), Feb-2026
  +6.3% (−11%), Oct-2011 +4.3%, Jul-2011 +3.8%, Jan-2016 +2.6%.

Annual premium, % of notional:

| Year | Always | Regime | | Year | Always | Regime |
|---|---|---|---|---|---|---|
| 2011 | 11.3 | 9.9 | | 2019 | 4.2 | 1.4 |
| 2012 | 7.0 | 1.9 | | 2020 | 16.8 | 11.5 |
| 2013 | 6.6 | 3.2 | | 2021 | 7.2 | 0.0 |
| 2014 | 4.9 | 0.0 | | 2022 | 7.3 | 3.5 |
| 2015 | 5.6 | 3.1 | | 2023 | 1.8 | 0.4 |
| 2016 | 4.3 | 2.2 | | 2024 | 3.4 | 0.2 |
| 2017 | 1.8 | 0.0 | | 2025 | 2.2 | 0.7 |
| 2018 | 3.5 | 1.0 | | 2026* | 3.0 | 2.8 |

*2026 to 13 Oct. VIX from 2009-09, so every year is priced from the actual VIX print.

**Use in this lab:** S1/S2's crash filter (sell to the liquid fund) and S1H/S2H (futures short) are the gated
paths. The put overlay becomes decidable only with live NSE option quotes; if the owner wants it, start capturing
the NIFTY chain forward (free on nseindia.com) and revisit after ~6 months of real premiums.

## 2. Liquid-yield sensitivity (plan amendment 12; review finding 13)

S1 plain, Gate A window 2020-01-01 → 2026-10-13 (23 of 83 months risk-off in cash):

| Cash yield | CAGR | maxDD |
|---|---|---|
| 4% | 27.34% | −16.6% |
| 6% (baseline) | 28.02% | −16.5% |
| 8% | 28.70% | −16.5% |

±2 pts of cash yield moves S1's Gate-A CAGR by ∓/± ~0.7 pts — the flat-6% convention is not driving the result.
(The formal Gate-A verdict for S1 lives in the PM's run, not here.)
