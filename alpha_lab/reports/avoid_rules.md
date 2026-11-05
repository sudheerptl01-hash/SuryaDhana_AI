# The avoid library — "stay away today" rules with their measured probabilities

Derivatives & risk analyst · 14 Oct 2026. Numbers: `reports/evidence_probability/conditions.csv` (liquid NSE
universe L ≈ 1,945 stocks, weekly signals 2011 → Oct 2026, entry next open, excess vs the universe's equal-weight
mean, Newey-West t). Base rate to beat: a liquid stock beats the universe average ~**45%** of the time; lands in
the worst fifth **20%** by construction. "pre / 24+" = pre-2024 and 2024→ mean weekly excess in % (t).

## 1. Active avoid rules (robust first — these are the "we win by not playing" set)

| Rule (do not newly buy when…) | Horizon | P(beat) vs base | P(worst 20%) | pre | 24+ | Verdict | Events pre/24+ |
|---|---|---|---|---|---|---|---|
| Close below its 200-day average | 60d | 42.1 vs 45.0 | 20.2 | −1.99 (−5.4) | −1.26 (−3.0) | **Robust** | 80K/45K |
| — same flag | 20d | 44.0 vs 45.9 | 19.6 | −0.69 (−5.1) | −0.60 (−3.2) | **Robust** | 80K/48K |
| — same flag | 5d | 44.9 vs 46.3 | 18.9 | −0.17 (−4.1) | −0.16 (−2.8) | **Robust** | 80K/49K |
| Momentum score in the bottom decile | 60d | 38.5 vs 44.3 | 22.7 | −2.16 (−3.6) | −2.15 (−3.7) | **Robust** | 22K/11K |
| Within 10% of the 52-week low | 60d | 42.5 vs 45.4 | 19.3 | −2.54 (−6.1) | −2.01 (−2.8) | **Robust** | 28K/16K |
| — same flag | 20d | 45.0 vs 46.4 | 18.0 | −0.65 (−3.0) | −0.71 (−2.4) | **Robust** | 28K/17K |
| Split/bonus ex-date in the last 20 sessions | 5d | 40.2 vs 45.4 | 28.6 | −0.80 (−4.2) | −0.95 (−2.4) | **Robust** | 1.2K/0.7K |
| Upside value-area break in the last 5 sessions | 5d | 44.1 vs 44.9 | 22.4 | −0.15 (−3.2) | −0.20 (−2.4) | **Robust** | 36K/16K |
| Strong bad results (≤ −5% vs mkt) in the last 5 sessions | 5d | **39.2** vs 45.4 | 22.7 | −0.53 (−2.0) | −0.88 (−4.4) | Holds | 0.7K/0.5K |
| Momentum bottom decile | 20d | 41.5 vs 45.1 | 21.0 | −0.51 (−2.0) | −0.92 (−3.1) | Holds | 22K/11K |
| 60-day volatility in the top decile | 20d | 40.8 vs 45.1 | **32.0** | −0.79 (−2.6) | −0.49 (−1.4) | Holds (the best *worst-fifth* predictor) | 23K/12K |
| Burst day (≥ +4% on higher volume) in the last 5 sessions | 5d | 43.4 vs 45.1 | 26.0 | −0.09 (−2.1) | −0.10 (−1.7) | Holds (small) | 49K/25K |

The one robust **buy-timing** exception, for contrast (it lives in S3, not in this library):
RSI(2) < 5 in a momentum leader, 5d: P(beat) 53.1 vs 46.1, +0.49 (2.8) / +0.58 (2.5), Robust — and still smaller
than a delivery round trip.

## 2. How to use
- **Veto on new buys only.** Nothing here is a short signal (the book cannot short, and none of these effects
  covers futures shorting costs + margin). A held name hitting a flag is reviewed, not force-sold — forced sales
  on these flags were tested (results-filter study) and did nothing.
- The **S1 strategy uses five of these** as its pre-registered veto: below-200-DMA, near-52w-low, top-decile
  volatility, split-ex-20d, strong-bad-results-60d (the 60-session version of the results flag is weaker than the
  5-session one — S1 holds monthly so it uses the long window; the 5-session flag is the screen/scanner rule).
- Compounding flags: the merged-probability study showed naive stacking over-counts correlated risk (vol + beta +
  lottery + burst ≈ one factor). Treat 1 robust flag = stay away; 3+ risk flags = the worst-fifth odds roughly
  double (20% → ~40% per evidence_probability's AVOID bucket).
- **Coverage asymmetry (stated, per plan):** the results flags exist only where NSE release times cover the
  symbol; an uncovered name is never vetoed by results. Coverage itself must never become a model input
  (the leak test in `scripts/tests/test_evidence_probability.py` guards this).

## 3. Retired avoid ideas — tested, no effect; do not re-litigate without new data
Non-institutional bulk-deal buying (faded to +0.21 (0.6) since 2024) · lottery-MAX spike (risk marker only) ·
binary "near 52-week high" (if anything +) · delivery surge (nothing, any horizon) · MTF crowding ·
F&O long/short build-up quadrants (Unstable) · FII positioning extremes (null) · shareholding accumulation
(filing-season timing) · overnight-momentum and abnormal-volume (sign-flipped vs US priors — see
`claims_matrix.md` §D) · max pain (the research brief itself expects none).

## 4. Forward capture that would upgrade this library
NSE publishes dated archives of MWPL/FutEq (`combineoi_DDMMYYYY.zip`) and the daily F&O ban list
(`fo_secban_DDMMYYYY.csv`). Backfilling them makes the ban filter a *tradability* rule (bans gate S3 entries),
not an alpha claim. Also worth capturing forward: the NIFTY option chain (for the put overlay) and index
add/delete notices (EVT-01, untested for lack of history).
