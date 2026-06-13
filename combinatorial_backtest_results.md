# Combinatorial Alpha Grid — Top Institutional Edges

_Generated 2026-06-11 21:46 · MODE=PAPER (research)_

> ## ⚠️ SURVIVORSHIP HAIRCUT — read before trusting any CAGR below (audit finding D1)
>
> **Every CAGR / Total-Return / Sharpe in this file is upward-biased by an unquantified
> survivorship premium and must be read with an explicit haircut applied.**
>
> The survivorship-control *mechanism* is live (as-of index membership + delisting
> force-close, G1/G2), but the underlying tables are **empty/absent**:
> `index_membership` and `delistings` do not exist; `corporate_events`, `splits`,
> `dividends` have 0 rows. So the engine correctly runs on the **current 1,496 survivors**
> and honestly flags `membership_pit = False` — but the bias is **live until the tables
> are backfilled** (Phase 5, data-eng).
>
> **Direct evidence this dataset is 100% survivorship-pruned** (queried 2026-06-13 from
> `data/market.duckdb`, window 2021-05-17 → 2026-06-11):
> - Names present early (≤ 2021-08): 579 · present late (≥ 2026-03): **1,496**
> - Names present-early-but-not-late (i.e. *observed exits*): **0**
>
> A real Nifty-1500-class universe reconstitutes ~8–12%/yr; over a 5-year window roughly
> **30–50% of constituents churn**. That this dataset shows **zero exits** is the textbook
> signature of a pure backfill of *today's* winners — every delisted / acquired / relegated
> name is silently missing. The 917 names that "appear later" are coverage growth, not
> entrants replacing exits.
>
> **Haircut to apply (Brown–Goetzmann–Ibbotson–Ross 1992):**
>
> | Estimate | CAGR haircut | Apply to |
> |---|---:|---|
> | Conservative (low-churn assumption) | **−1.0%/yr** | every CAGR column below |
> | Central (this universe's implied churn) | **−1.5% to −3.0%/yr** | headline ranking |
> | Severe (high-churn / microcap-skewed factors) | **−4.0%/yr** | VMI/Intention-heavy combos |
>
> Microcap-skewed factors (VMI, Intention) deserve the **upper** end of the band: small/illiquid
> names have the highest delisting hazard, so their survivor cohort is the most positively
> selected. A combo reporting e.g. **+12%/yr CAGR** should be read as **≈ +8% to +11%/yr**
> survivorship-adjusted — *before* the at-scale market-impact haircut (C1/C2/C3) is also applied.
>
> This caveat is removed only when `membership_pit = True` (tables backfilled). Until then,
> **no number in this file is deliverable at face value.**

## Methodology

- **Dataset**: Nifty-1500 DuckDB · 1,496 tickers · window **2021-06-01 → 2026-06-01** (1,247 trading days)
- **Trade model**: signal on day T → enter **next open** → exit **+5 trading days** close · net of **0.15% friction** per trade
- **Equity**: daily-marked equal-weight portfolio (each trade's 5-day return attributed geometrically across its holding bars; portfolio = mean of concurrently-held positions, cash on idle days). This makes CAGR / MaxDD / Sharpe **frequency-fair** — high-firing filters cannot fake leverage via overlapping returns.
- **Anti-curve-fit**: combinations with **< 100 trades discarded**; ranked by **Sharpe** (risk-adjusted), not raw return.
- **Search**: all 2⁶−1 = 63 filter combinations · **43** cleared the trade floor · engine ran in 8.8s.
- **Multiple-testing correction (Bailey & López de Prado)**: the **Deflated Sharpe Ratio (DSR)** column is P(true SR > expected-max-of-43 under the null) — it deflates each combo's Sharpe for the number of trials, sample length, skew and kurtosis. **DSR ≳ 0.95** survives multiple-testing; **< 0.5** is likely a selection artefact even if the raw Sharpe looks high.
- **Probability of Backtest Overfitting (PBO)** via CSCV over 6 calendar-year blocks × 43 combos (20 symmetric splits): **PBO = 0.15** → ~15% chance the in-sample-best combo ranks below the out-of-sample median.

## Filter definitions (all strictly trailing — zero look-ahead)

| Filter | Signal |
|---|---|
| **VMI** | vmi_ratio ≥ 1.0  — dollar-volume at/above its volatility-normalized 20d baseline |
| **VIPT** | vipt_breakout — close clears the 20d range on > 3σ volume thrust |
| **SectorDisp** | positive sector regime AND top-decile sector-relative 14d momentum (cross-sectional) |
| **BetaDecouple** | decoupled_leader — 30d corr < 0.2 in a market pullback while holding positive 5d return |
| **Intention** | intraday_intention ≥ 0.8 — buyers defending the close (3-day aggregated CLV) |
| **Squeeze** | squeeze_on — Bollinger Bands compressed inside Keltner Channels |

## Top 20 — Overall metrics (ranked by Sharpe)

_**PSR** = P(SR>0) in isolation; **DSR** = Deflated Sharpe after correcting for the 43 trials. PSR high + DSR low ⇒ the Sharpe is real but **eaten by the search** (too many combos tried for the signal present)._

| # | Filter Combination | Trades | Win % | Avg Win % | Avg Loss % | Profit Factor | Expectancy % | Sharpe | PSR | DSR | Calmar | Max DD % | CAGR % | Total Ret % |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | VMI + BetaDecouple + Intention | 337 | 42.4 | 7.53 | -3.80 | 1.46 | 1.008 | **1.46** | 1.00 | 0.00 | 0.42 | -55.6 | 23.3 | 182.1 |
| 2 | VMI + VIPT + BetaDecouple + Intention | 132 | 52.3 | 9.67 | -6.80 | 1.56 | 1.809 | **1.04** | 0.99 | 0.00 | 0.46 | -36.0 | 16.6 | 114.1 |
| 3 | VMI + Intention | 2,531 | 41.7 | 6.36 | -3.96 | 1.15 | 0.344 | **0.72** | 0.95 | 0.00 | 0.16 | -54.3 | 8.7 | 51.0 |
| 4 | VMI + SectorDisp + BetaDecouple | 392 | 49.0 | 8.59 | -7.04 | 1.17 | 0.617 | **0.66** | 0.92 | 0.00 | 0.18 | -44.6 | 7.9 | 45.7 |
| 5 | VIPT + BetaDecouple + Intention | 168 | 53.6 | 8.99 | -6.98 | 1.49 | 1.575 | **0.60** | 0.91 | 0.00 | 0.22 | -38.8 | 8.7 | 51.1 |
| 6 | BetaDecouple + Intention | 1,541 | 44.8 | 7.86 | -5.03 | 1.27 | 0.743 | **0.33** | 0.75 | 0.00 | 0.07 | -59.8 | 4.0 | 21.1 |
| 7 | VMI + SectorDisp + Squeeze | 112 | 47.3 | 8.14 | -6.26 | 1.17 | 0.553 | **0.28** | 0.74 | 0.00 | 0.07 | -41.5 | 3.0 | 15.6 |
| 8 | VMI + SectorDisp + Intention | 744 | 44.8 | 9.10 | -6.79 | 1.08 | 0.317 | **0.27** | 0.73 | 0.00 | 0.06 | -59.3 | 3.3 | 17.6 |
| 9 | SectorDisp + BetaDecouple | 2,879 | 44.8 | 7.83 | -5.85 | 1.09 | 0.280 | **0.23** | 0.70 | 0.00 | 0.05 | -35.0 | 1.8 | 9.2 |
| 10 | VMI + VIPT + Intention | 1,188 | 46.2 | 7.53 | -6.01 | 1.08 | 0.243 | **-0.08** | 0.43 | 0.00 | -0.05 | -55.7 | -2.8 | -13.0 |
| 11 | SectorDisp + BetaDecouple + Intention | 333 | 50.5 | 10.64 | -7.22 | 1.50 | 1.790 | **-0.08** | 0.43 | 0.00 | -0.04 | -42.0 | -1.8 | -8.6 |
| 12 | VIPT + SectorDisp + Squeeze | 134 | 50.0 | 7.60 | -6.14 | 1.24 | 0.733 | **-0.21** | 0.32 | 0.00 | -0.08 | -43.6 | -3.7 | -17.0 |
| 13 | VMI + BetaDecouple | 4,330 | 28.5 | 4.76 | -2.18 | 0.87 | -0.199 | **-0.26** | 0.28 | 0.00 | -0.06 | -26.4 | -1.6 | -7.9 |
| 14 | VIPT + BetaDecouple + Squeeze | 196 | 40.8 | 7.25 | -5.57 | 0.90 | -0.335 | **-0.26** | 0.28 | 0.00 | -0.08 | -50.7 | -4.2 | -19.1 |
| 15 | VIPT + SectorDisp + Intention | 816 | 44.9 | 9.17 | -7.00 | 1.07 | 0.252 | **-0.26** | 0.28 | 0.00 | -0.09 | -67.5 | -6.0 | -26.2 |
| 16 | VMI + VIPT + SectorDisp + Intention | 582 | 43.8 | 9.21 | -6.93 | 1.04 | 0.142 | **-0.39** | 0.19 | 0.00 | -0.14 | -63.3 | -8.6 | -35.8 |
| 17 | VMI + VIPT + BetaDecouple + Squeeze | 155 | 38.7 | 7.38 | -5.53 | 0.84 | -0.532 | **-0.55** | 0.12 | 0.00 | -0.15 | -48.1 | -7.0 | -30.2 |
| 18 | VMI + VIPT + BetaDecouple | 884 | 41.3 | 7.76 | -5.74 | 0.95 | -0.164 | **-0.55** | 0.11 | 0.00 | -0.13 | -65.4 | -8.7 | -36.2 |
| 19 | Intention | 20,547 | 47.4 | 6.76 | -4.93 | 1.23 | 0.606 | **-0.57** | 0.10 | 0.00 | -0.09 | -62.3 | -5.3 | -23.7 |
| 20 | VMI + VIPT + SectorDisp + BetaDecouple | 276 | 45.7 | 8.99 | -7.29 | 1.04 | 0.145 | **-0.62** | 0.07 | 0.00 | -0.15 | -71.2 | -10.5 | -42.4 |

## Top 20 — Year-over-Year return matrix (%)

_Each cell is the strategy's compounded return within that calendar year — proves the edge isn't a single-year artefact._

> ⚠️ **Partial / warm-up years**: 2021 covers Jun–Dec only and overlaps factor warm-up (200d MA, 30d corr) so its sample is thin and its % is not comparable to a full year; 2026 covers Jan–Jun only. Judge robustness on the **full years 2022–2025**.

| # | Filter Combination | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|--:|--:|--:|--:|--:|--:|
| 1 | VMI + BetaDecouple + Intention | +122.5 | -26.4 | +11.6 | +74.8 | +12.3 | -21.3 |
| 2 | VMI + VIPT + BetaDecouple + Intention | +103.6 | -18.6 | +3.0 | +43.8 | +15.5 | -24.5 |
| 3 | VMI + Intention | +63.2 | -34.3 | +79.6 | +8.5 | -15.8 | -14.2 |
| 4 | VMI + SectorDisp + BetaDecouple | +36.6 | -17.0 | +46.1 | +44.2 | -11.7 | -30.9 |
| 5 | VIPT + BetaDecouple + Intention | +84.0 | -32.4 | +10.6 | +23.7 | +3.9 | -14.5 |
| 6 | BetaDecouple + Intention | +35.8 | -20.8 | +1.5 | +33.9 | -6.6 | -11.2 |
| 7 | VMI + SectorDisp + Squeeze | +1.1 | -1.1 | +7.4 | +40.3 | -19.1 | -5.2 |
| 8 | VMI + SectorDisp + Intention | +51.8 | +36.7 | +1.9 | +15.0 | -38.9 | -20.9 |
| 9 | SectorDisp + BetaDecouple | +26.3 | -23.0 | +32.9 | +8.0 | -7.4 | -15.4 |
| 10 | VMI + VIPT + Intention | +66.4 | -34.4 | +26.9 | -0.2 | -21.5 | -19.9 |
| 11 | SectorDisp + BetaDecouple + Intention | +35.3 | -22.9 | -6.9 | +34.1 | -15.5 | -16.9 |
| 12 | VIPT + SectorDisp + Squeeze | +0.6 | -8.8 | +9.9 | +26.4 | -26.3 | -11.7 |
| 13 | VMI + BetaDecouple | +10.4 | -21.4 | +23.9 | +3.7 | -10.5 | -7.8 |
| 14 | VIPT + BetaDecouple + Squeeze | +8.3 | -12.5 | -10.5 | +12.1 | +18.5 | -28.2 |
| 15 | VIPT + SectorDisp + Intention | +45.9 | +9.2 | +31.4 | -18.5 | -37.9 | -30.4 |
| 16 | VMI + VIPT + SectorDisp + Intention | +30.5 | +14.9 | -4.6 | +8.3 | -49.4 | -18.1 |
| 17 | VMI + VIPT + BetaDecouple + Squeeze | +4.2 | -12.4 | -1.9 | -13.3 | +5.5 | -14.9 |
| 18 | VMI + VIPT + BetaDecouple | +61.0 | -27.8 | -1.1 | +18.1 | -19.5 | -41.6 |
| 19 | Intention | +71.0 | -36.6 | +19.9 | -4.9 | -37.2 | -1.6 |
| 20 | VMI + VIPT + SectorDisp + BetaDecouple | +37.8 | -20.8 | +15.9 | +13.8 | -30.9 | -42.1 |

## Read-out

- **Best risk-adjusted edge**: `VMI + BetaDecouple + Intention` — Sharpe **1.46**, PSR 1.00, DSR **0.00**, Calmar 0.42, 337 trades, win 42.4%, PF 1.46, MaxDD -55.6%.
- **Multiple-testing verdict**: PSR 1.00 (raw significance) vs DSR 0.00 (post-search) → this edge does **not** survive the 43-combo search — even the winner's Sharpe is within the expected-max-under-null, i.e. largely trial-count luck given the deep drawdowns.
- **Overfitting probability (PBO)**: **0.15** across 20 CSCV splits — low (robust selection).
- **Regime robustness (full years 2022–2025)**: positive in **3/4**.
- Treat single-filter rows as the baseline edge; multi-filter rows that *raise Sharpe without collapsing trade count* are the genuine interaction effects worth trading.
