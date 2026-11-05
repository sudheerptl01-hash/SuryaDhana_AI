# Quant Idea Lab: out-of-the-box stock selection on NSE

Run: `scripts/quant_idea_lab.py` (~6 s) · 1,374 NSE equities, 2020-09 → 2026-09 · liquid = ≥ ₹10 Cr median daily turnover.
Discovery < 2024-07-01, holdout after. Each idea's direction was fixed before its result was seen.

## 1. Ideas considered (and cut before testing)
| Idea | Mechanism | Status |
|---|---|---|
| Lower/upper circuit locks | India-specific: price bands trap order flow | tested |
| Overnight momentum / "tug of war" | clientele persistence | tested |
| MAX lottery effect | retail lottery demand | tested |
| Abnormal-volume premium | attention | tested |
| Quiet-loser reversal | liquidity-driven drop reverts | tested |
| Dividend yield (dated dividends) | value, point-in-time | tested |
| Dividend run-up / post-ex drift | dividend clientele | tested |
| Post-split drift | signalling | tested |
| P/E, ROE, analyst targets | — | cut: fundamentals are one 2026-05 snapshot (look-ahead) |
| Earnings drift | — | cut: no earnings dates in DB |
| Momentum / sector variants | — | cut: already rejected in earlier repo research |

## 2. Results
**Weekly factors (long the expected-best decile, net of turnover cost, vs liquid market):**
| Factor | 2020–24 net/wk (t) | 2024–26 net/wk (t) | Verdict |
|---|---|---|---|
| overnight momentum | −0.23% (−2.2) | −0.21% (−2.2) | rejected: wrong sign, consistently |
| tug of war | −0.12% (−1.3) | −0.16% (−1.5) | rejected |
| low MAX | −0.22% (−2.7) | −0.16% (−1.7) | rejected |
| abnormal volume | −0.12% (−1.3) | −0.35% (−4.5) | rejected (high-volume names *lag*) |
| quiet-loser reversal | +0.06% (0.5) | +0.06% (0.5) | rejected. Gross +0.2%/wk with perfectly ordered deciles, but 91% weekly turnover eats it |
| dividend yield | +0.21% (2.6) | +0.02% (0.3) | rejected: disappeared in holdout |

**Events:**
| Event | 2020–24 | 2024–26 | Verdict |
|---|---|---|---|
| Dividend run-up (ex−5 → ex−1) | +0.46% (t 2.5) | +0.52% (t 1.9) | **rejected on inspection**: the same gain shows up 10–6 days before ex-date (announcement effect). The surely-known window (ex−3→ex−1) is ≈0 in liquid names |
| Post-ex-dividend | negative | negative | rejected |
| Post-split drift (20d) | −4.1% | −4.3% | rejected (splits *follow* rallies and then mean-revert) |
| Upper-circuit lock | −0.53% (−4.4) | +0.10% (0.7) | rejected |
| **Lower-circuit lock → next day open→close** | **+1.00% (t 6.6)** | **+0.64% (t 3.0)** | **survives** |

## 3. The survivor: lower-circuit rebound
**Rule:** yesterday the stock closed down by its band (5/10/20%) and pinned at the day's low. Today, if it **re-opens at or near the floor** (open ≤ −4.8% vs yesterday's close, visible at the 09:15 open), buy at the open and sell at today's close. EQ series and liquid names only.

**Why it works:** a stock that re-opens locked is trading at the lowest price it's allowed to that day. Buyers there absorb forced and panic sellers. When the selling exhausts and the lock breaks, price can only go up from the floor.

| | 2020–24 | 2024–26 |
|---|---|---|
| Trades / distinct stocks | 518 / 119 | 224 / 87 |
| Net per trade (0.15% cost) | +1.80% | +1.40% |
| Excess vs market | **+1.77% (t 7.3)** | **+1.76% (t 3.5)** |
| Win rate | 60% | 60% |
| Book: ≤5 names/day at 15%, cash otherwise | CAGR 37.3%, MaxDD −3.3%, Sharpe 3.6 | CAGR 20.5%, MaxDD −2.4%, Sharpe 2.4 |
| Days with capital deployed | 32% | 27% |

**Robustness it passed:**
- Same-size drops that were *not* pinned at the low: 0% / −0.5%. The effect needs the lock.
- Without the Adani group: +1.79% / +1.77%.
- Without the 10 most frequent names: +1.87% / +1.77%.
- Without the Jan–Mar 2023 crash: +1.79% / +1.76%.
- Positive every year from 2020 to 2026. Per-stock average matches the per-trade average.

**What kills it:** holding overnight. Selling at the next open gives ≈0 / −0.6%. It's a **same-day trade only**, so it only works where intraday square-off is allowed. The effect sits in EQ-series stocks; the few BE-series cases are untradeable intraday.

**Caveats before real money:**
1. **Capacity.** Lower-circuit days are one-sided; size each order to a small fraction of the day's volume. The CAGR above assumes 15% of capital per trade fills at the open price, which is only realistic for small accounts.
2. **Fills.** It assumes you are filled at the opening (pre-open auction) price and exit near the official close, which NSE computes as the last-30-minute VWAP.
3. **Series is today's, not historical.** A stock in EQ now may have been in T2T back then.
4. **Survivorship.** Delisted or suspended stocks, which would have kept locking, are missing from the data.
5. The re-open-locked refinement was chosen after seeing the plain lock result (+1.00 / +0.64). Both pass.

~~Next step: paper-trade it live.~~ Superseded: rejected in §5, strategy removed.

## 5. CORRECTION (2026-09-26): the survivor fails with realistic exits
Found by walking through a real case (ATALREAL, Sep 2026). On **~45% of trades** (49% in 2020–24, 42% in 2024–26) the stock stayed **locked at the lower circuit all day** (open = high = low = close). You can *buy* on such a day because sellers are queued, but **you cannot sell**: you'd be at the back of that same queue. The backtest above assumed a sale at the close anyway, and booked those days as ≈ −0.15%.

Carrying those positions until the stock first trades a range, then selling at that close:

| | 2020–24 | 2024–26 |
|---|---|---|
| Backtest, same-day exit (§3) | +1.77% (t 7.3) | +1.76% (t 3.5) |
| **Realistic: stuck positions carried** | **−0.49% (t −0.8)** | **−1.19% (t −1.2)** |
| Stuck trades alone | −5.0% avg, worst −42% | −10.1% avg, worst −64% |
| Trades where the lock broke that day | +3.3% | +2.1% |

**Verdict: REJECTED as specified.** The §3 robustness tests all kept the same-day-exit assumption, so none of them could catch this.

Open lead only (post-hoc, few trades): if the stock opens *just above* the circuit floor instead of exactly at it, the realistic excess was +2.1% (n=44) and +4.2% (n=29), t ≈ 2. That's too little data to trade. It would need intraday data or months of forward paper records.

The paper-trading job and the pre-open watchlist were **removed on 2026-09-26 at the owner's request**. This section stays as the research record.
