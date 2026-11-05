# Phase B extended: the untouched decade (Feb 2011 → Oct 2020)

Run: `scripts/phase_b_allocator.py --panel-start 2010-01-01 --out reports/phase_b_extended` (~2 min). Same 24 variants, same rules, same costs (ICICI MoneySaver) and tax as `reports/phase_b/`; nothing was tuned. Data: NSE classic + full bhavcopy 2010–2026 (8.16M rows, delisted names included); the 2010–2019 data was spot-checked against Yahoo (0.029% of days differ by > 5 points; see `reports/data_quality/NSE_PANEL_QA_2010_2019.md`).

## Benchmark: NIFTY 50 (price index)
| Period | CAGR | Max drawdown |
|---|---|---|
| Untouched, Feb 2011 → Oct 2020 | 8.2% | −38.4% (COVID) |
| Full, Feb 2011 → Sep 2026 | 9.7% | −38.4% |

## Result 1: momentum beats NIFTY on data never seen before ✅
- **All 12 momentum variants beat NIFTY over 2011–2020** after costs and tax (20 of 24 overall; low-vol didn't).
- Best: NSE momentum, top 20, no filter: **22.7%/yr vs 8.2%** (+14.6 points), max DD −40%.
- NSE momentum, top 20, crash filter + vol target: 16.5%/yr (+8.3 points), max DD −35%.
- The formal significance gate (Deflated Sharpe > 0.95 across 24 variants) is **still not met**: best 0.89, i.e. ~89% confidence after correcting for multiple tries.

## Result 2: the −15% mixes sized on 2020–24 did NOT all hold ❌
| Mix (share fixed in advance) | 2011–2020 CAGR | 2011–2020 max DD | Within −15%? |
|---|---|---|---|
| NSE mom top 20 + filter + vol target @ 66% | 13.1% | −22.1% | ❌ |
| Momentum 12-1 top 20 @ 40% | 10.0% | −21.8% | ❌ |
| NSE momentum top 20 @ 50% | 14.7% | −18.7% | ❌ |
| Momentum 12-1 top 20 + filter + vol target @ 45% | 8.5% | **−14.1%** | ✅ (NIFTY 8.2%, −38%) |

2020–24 alone was too calm to size the risk: the 2011–2020 decade had deeper strategy drawdowns (2016, 2018, 2020).

## Year by year (₹5L, % return)
| Year | NSE mom top 20 | NSE mom + filter + vol target | NIFTY |
|---|---|---|---|
| 2011 | −6.9 | +12.6 | −14.6 |
| 2012 | +59.4 | +28.7 | +27.7 |
| 2013 | +5.0 | −0.8 | +6.8 |
| 2014 | +70.6 | +74.0 | +31.4 |
| 2015 | +6.0 | −7.0 | −4.1 |
| 2016 | −11.6 | +1.0 | +3.0 |
| 2017 | +112.3 | +78.8 | +28.6 |
| 2018 | −10.8 | −13.6 | +3.2 |
| 2019 | +4.6 | −6.2 | +12.0 |
| 2020 | +77.6 | +48.4 | +14.9 |
| 2021 | +56.2 | +65.1 | +24.1 |
| 2022 | −8.7 | −10.1 | +4.3 |
| 2023 | +84.9 | +65.1 | +20.0 |
| 2024 | +9.6 | +19.4 | +8.8 |
| 2025 | −11.7 | +3.2 | +10.5 |
| 2026 (to Sep) | +29.5 | −3.1 | −11.4 |

Momentum lost money or lagged NIFTY in 2013, 2016, 2018, 2019, 2022 and 2025. The gains come in bursts. Sticking with it through those years is the real cost of this premium.

## Verdict
- **The momentum premium is real and persistent in Indian stocks**: it held across 16 years, including a decade this research had never seen, after real ICICI costs and tax.
- **Proven at 95% confidence? Not quite** (~89%).
- **A −15% drawdown with momentum is only reachable at ~40–45% equity share.** That gives roughly NIFTY-like returns with about a third of NIFTY's drawdown. Higher returns need a looser drawdown budget.

Decision needed from the owner: risk budget (−15% / −25% / full) and the trading-rule set for a monthly strategy (see the chat for options).
