# What changes the POC magnet? Conditional study + strategy gauntlet

Run: `scripts/poc_conditional_study.py` (~30 s) · 87,930 value-area events, 1,278 NSE equities, 2020-09 → 2026-09.
Discovery = before 2024-07-01, holdout = 2024-07-01 → 2026-09-25. Bucket cut-offs come from discovery only.

## Method: guards against fooling ourselves
| Guard | Why |
|---|---|
| **Condition-matched chance.** For each condition, chance comes from all stock-days in the same bucket | A stock under its 50DMA drifts down anyway; that drift is not a POC magnet |
| **Week-clustered t-stats** | 500 stocks breaking down in one crash week are one observation, not 500 |
| **Discovery → holdout** | Only effects with the same sign and \|t\| ≥ 2 in *both* periods count |
| **Random-entry control (S0)** | Same stocks, same filters, same stop and cost, random day. A strategy must beat this, not just the market |
| **Span-matched liquid benchmark** | Equal-weight ≥₹10 Cr names, same open→close span as each trade |
| **2·ATR stop, 5-day time stop, 0.15% cost, long only** | Project trading rules |

Two biases I found and removed along the way:
1. Buying S2 at an intraday POC touch while the benchmark starts at the open manufactured +0.5% of fake alpha.
2. Benchmarking liquid-only trades against the whole universe, including small caps that ran +35%/yr, made everything look worse than it was.

## 1. Does trend or an MA change the 33% POC-return rate? (UP breakouts)
| Condition | Returned to POC, disc / hold | Matched chance | Magnet excess (week-weighted) |
|---|---|---|---|
| Stock **below** 50DMA | 34.5% / 40.4% | 33.7% / 38.8% | +6.0 / +8.6 pp |
| Stock above 50DMA | 30.3% / 36.5% | 28.8% / 33.4% | +4.4 / +5.9 pp |
| Stock below 200DMA | 32.8% / 38.2% | 31.6% / 35.4% | +7.8 / +7.6 pp |
| Stock above 200DMA | 31.5% / 36.8% | 29.1% / 33.6% | +5.2 / +5.9 pp |
| 50DMA < 200DMA | 31.4% / 36.7% | | +8.9 / +8.1 pp |
| 50DMA > 200DMA | 31.9% / 37.8% | | +5.2 / +6.3 pp |
| 50DMA sits between price and POC | 24.0% / 31.2% | 25.7% / 25.6% | +3.3 / +8.5 pp |
| No MA in between | 32.6% / 39.1% | 31.4% / 33.1% | +4.3 / +9.0 pp |

**Reading it:** below the 50DMA, raw returns are about 4 points higher, but most of that is the downtrend itself: the matched chance is higher by the same amount. The *extra* pull from the POC is only about 2 points stronger in weak stocks, and that difference is not significant (spread t −1.3 / −1.8). An MA sitting between price and the POC cuts the raw rate a lot (24% vs 33%), but only because the POC is then further away. The MA doesn't act as a floor beyond what distance explains.

Across all conditions, the UP magnet is **+4 to +9 points per typical week**. That's larger than the +2.3 pooled figure, because crowded crash weeks dilute the pooled average.

## 2. Modifiers that replicated in both periods
| Modifier | Effect | Discovery t / Holdout t |
|---|---|---|
| High-volume breakdown (relvol top quintile) | Returns to POC 5–7 pp *less* than chance: the market accepted the lower price | −3.4 / −2.5 |
| Breakdown when market breadth is strong | Returns to POC 7–13 pp less | −2.1 / −3.1 |
| High-volume *upside* breakout | Next-5-day return 0.7–1.4% worse than a low-volume breakout (exhaustion, not confirmation) | −5.9 / −2.4 |
| Breakdown in a stock whose 50DMA is rising | +0.6–0.7% better forward return than falling-50DMA breakdowns | +2.5 / +2.6 |
| Breakdown in a high-ATR% (volatile) stock | +0.6–0.75% better than calm-stock breakdowns | +3.5 / +2.4 |

Rejected: VIX, NIFTY>200DMA, momentum, 52-week-high proximity, gap breakouts, breakout size, VA width. Each either didn't replicate or is explained by distance to the POC. The close-location result on breakdowns replicated statistically but rests on only 77–185 events, so I set it aside.

## 3. Strategies (liquid names, net of cost)
| Strategy | vs random entry, disc / hold | t vs random | Verdict |
|---|---|---|---|
| S1 buy the upside breakout (next open) | −0.09 / −0.33% | −1.0 / −2.5 | ✗ |
| S1 in an uptrend stock (>200DMA, 50>200) | −0.11 / −0.38% | −2.0 / −5.3 | **✗ reliably worse: avoid** |
| S2 buy the POC retest after a breakout | +0.03 / −0.34% | −0.4 / −2.4 | ✗ (the "edge" was the intraday-fill bias) |
| S3 failed breakdown, VAL reclaimed → buy | −0.13 / −0.30% | −2.6 / −2.4 | **✗ avoid** |
| S4 failed breakout → buy | −0.12 / −0.28% | −2.1 / −2.1 | **✗ avoid** |
| S5 buy the breakdown | −0.17 / −0.21% | −3.2 / −1.7 | ✗ |
| S5 in a market uptrend | −0.20 / −0.31% | −3.3 / −4.0 | **✗ avoid** |
| S5 high-volume breakdown | −1.30 / −0.58% | −3.8 / −1.3 | ✗ worst cell |
| S5 in a high-ATR or rising-50DMA stock | ≈ 0 | n.s. | ✗ no edge (only stops being negative) |

**No strategy survived.** None beat both the market and random entry in both periods. The 2·ATR stop cost 0.05–0.10% per trade versus no stop in most cells, which is typical for 5-day mean-reverting moves. Noted only; the project stop rule is unchanged.

## Conclusions
1. The POC magnet is real for upside breakouts (+4–9 pp over chance in a typical week), but it **doesn't turn into a profitable long entry**. Every long timed on a value-area event (breakout, retest, reclaim, failed break, breakdown) did worse than a random entry into the same stocks: −0.1% to −0.4% per 5-day trade, reliably so in uptrends.
2. Moving averages change the *raw* return rate mainly through trend drift, not through the POC.
3. **Usable output = an avoid filter.** Don't open new longs in the 5 sessions after a stock leaves a balanced value area, especially after a high-volume breakdown or an upside break in an already-uptrending stock. Next step: add it as a veto on the project's real entry signals and walk-forward test it. It hasn't been tested as an overlay yet.

## Caveats
- Profiles come from daily bars (volume spread across each bar's range); true intraday volume-at-price isn't in the DB.
- Survivorship: the universe is today's listed names.
- Round-2 filters were chosen after seeing both periods' spreads, so their holdout is not fully clean. They are reported as exploratory, and none became a tradable edge anyway.
