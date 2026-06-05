# Combinatorial Alpha Grid — Top Institutional Edges

_Generated 2026-06-05 20:17 · MODE=PAPER (research)_

## Methodology

- **Dataset**: Nifty-1500 DuckDB · 1,496 tickers · window **2021-06-01 → 2026-06-01** (1,241 trading days)
- **Trade model**: signal on day T → enter **next open** → exit **+5 trading days** close · net of **0.15% friction** per trade
- **Equity**: daily-marked equal-weight portfolio (each trade's 5-day return attributed geometrically across its holding bars; portfolio = mean of concurrently-held positions, cash on idle days). This makes CAGR / MaxDD / Sharpe **frequency-fair** — high-firing filters cannot fake leverage via overlapping returns.
- **Anti-curve-fit**: combinations with **< 100 trades discarded**; ranked by **Sharpe** (risk-adjusted), not raw return.
- **Search**: all 2⁶−1 = 63 filter combinations · **43** cleared the trade floor · engine ran in 8.9s.

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

| # | Filter Combination | Trades | Win % | Avg Win % | Avg Loss % | Profit Factor | Expectancy % | Sharpe | Calmar | Max DD % | CAGR % | Total Ret % |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| 1 | VMI + BetaDecouple + Intention | 336 | 42.6 | 7.53 | -3.76 | 1.48 | 1.042 | **1.63** | 0.47 | -55.6 | 26.3 | 215.5 |
| 2 | VMI + VIPT + BetaDecouple + Intention | 131 | 52.7 | 9.67 | -6.74 | 1.60 | 1.903 | **1.20** | 0.54 | -36.0 | 19.4 | 139.4 |
| 3 | VIPT + BetaDecouple + Intention | 167 | 53.9 | 8.99 | -6.93 | 1.52 | 1.648 | **0.75** | 0.29 | -38.8 | 11.2 | 69.0 |
| 4 | VMI + SectorDisp + BetaDecouple | 384 | 49.5 | 8.60 | -7.01 | 1.20 | 0.715 | **0.73** | 0.21 | -42.5 | 8.9 | 52.3 |
| 5 | VMI + Intention | 2,526 | 41.6 | 6.36 | -3.96 | 1.15 | 0.340 | **0.72** | 0.16 | -54.3 | 8.7 | 50.8 |
| 6 | BetaDecouple + Intention | 1,534 | 44.9 | 7.86 | -5.03 | 1.27 | 0.761 | **0.37** | 0.08 | -59.8 | 4.7 | 25.6 |
| 7 | VMI + SectorDisp + Intention | 742 | 44.7 | 9.11 | -6.79 | 1.09 | 0.328 | **0.30** | 0.07 | -59.3 | 3.9 | 20.6 |
| 8 | SectorDisp + BetaDecouple | 2,845 | 45.0 | 7.83 | -5.85 | 1.10 | 0.314 | **0.29** | 0.07 | -35.0 | 2.4 | 12.4 |
| 9 | VMI + SectorDisp + Squeeze | 112 | 47.3 | 8.14 | -6.26 | 1.17 | 0.553 | **0.28** | 0.07 | -41.5 | 3.0 | 15.6 |
| 10 | SectorDisp + BetaDecouple + Intention | 328 | 50.9 | 10.63 | -7.21 | 1.53 | 1.876 | **-0.01** | -0.02 | -40.7 | -1.0 | -4.7 |
| 11 | VMI + VIPT + Intention | 1,185 | 46.2 | 7.50 | -6.02 | 1.07 | 0.237 | **-0.07** | -0.05 | -55.7 | -2.6 | -12.0 |
| 12 | VIPT + SectorDisp + Intention | 815 | 44.9 | 9.17 | -7.00 | 1.07 | 0.265 | **-0.18** | -0.07 | -65.1 | -4.5 | -20.5 |
| 13 | VMI + BetaDecouple | 4,306 | 28.6 | 4.76 | -2.17 | 0.88 | -0.190 | **-0.20** | -0.05 | -26.4 | -1.3 | -6.2 |
| 14 | VIPT + SectorDisp + Squeeze | 134 | 50.0 | 7.60 | -6.14 | 1.24 | 0.733 | **-0.21** | -0.09 | -43.6 | -3.7 | -17.0 |
| 15 | VIPT + BetaDecouple + Squeeze | 196 | 40.8 | 7.25 | -5.57 | 0.90 | -0.335 | **-0.26** | -0.08 | -50.7 | -4.2 | -19.1 |
| 16 | VMI + VIPT + SectorDisp + Intention | 581 | 43.9 | 9.21 | -6.92 | 1.04 | 0.160 | **-0.31** | -0.12 | -60.7 | -7.2 | -30.8 |
| 17 | VMI + VIPT + BetaDecouple | 876 | 41.4 | 7.76 | -5.74 | 0.96 | -0.145 | **-0.52** | -0.13 | -65.0 | -8.3 | -34.6 |
| 18 | VMI + VIPT + BetaDecouple + Squeeze | 155 | 38.7 | 7.38 | -5.53 | 0.84 | -0.532 | **-0.55** | -0.15 | -48.1 | -7.1 | -30.2 |
| 19 | Intention | 20,429 | 47.4 | 6.75 | -4.93 | 1.23 | 0.607 | **-0.59** | -0.09 | -62.3 | -5.5 | -24.2 |
| 20 | VMI + VIPT + SectorDisp + BetaDecouple | 269 | 46.1 | 9.02 | -7.33 | 1.05 | 0.208 | **-0.59** | -0.14 | -70.7 | -10.1 | -40.9 |

## Top 20 — Year-over-Year return matrix (%)

_Each cell is the strategy's compounded return within that calendar year — proves the edge isn't a single-year artefact._

> ⚠️ **Partial / warm-up years**: 2021 covers Jun–Dec only and overlaps factor warm-up (200d MA, 30d corr) so its sample is thin and its % is not comparable to a full year; 2026 covers Jan–Jun only. Judge robustness on the **full years 2022–2025**.

| # | Filter Combination | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|--:|--:|--:|--:|--:|--:|
| 1 | VMI + BetaDecouple + Intention | +122.5 | -26.4 | +11.6 | +74.8 | +12.3 | -12.0 |
| 2 | VMI + VIPT + BetaDecouple + Intention | +103.6 | -18.6 | +3.0 | +43.8 | +15.5 | -15.5 |
| 3 | VIPT + BetaDecouple + Intention | +84.0 | -32.4 | +10.6 | +23.7 | +3.9 | -4.4 |
| 4 | VMI + SectorDisp + BetaDecouple | +36.6 | -17.0 | +46.1 | +44.2 | -11.7 | -27.8 |
| 5 | VMI + Intention | +63.2 | -34.3 | +79.6 | +8.5 | -15.8 | -14.4 |
| 6 | BetaDecouple + Intention | +35.8 | -20.8 | +1.5 | +33.9 | -6.6 | -8.0 |
| 7 | VMI + SectorDisp + Intention | +51.8 | +36.7 | +1.9 | +15.0 | -38.9 | -18.9 |
| 8 | SectorDisp + BetaDecouple | +26.3 | -23.0 | +32.9 | +8.0 | -7.4 | -13.0 |
| 9 | VMI + SectorDisp + Squeeze | +1.1 | -1.1 | +7.4 | +40.3 | -19.1 | -5.2 |
| 10 | SectorDisp + BetaDecouple + Intention | +35.3 | -22.9 | -6.9 | +34.1 | -15.5 | -13.3 |
| 11 | VMI + VIPT + Intention | +66.4 | -34.4 | +26.9 | -0.2 | -21.5 | -19.0 |
| 12 | VIPT + SectorDisp + Intention | +45.9 | +9.2 | +31.4 | -18.5 | -37.9 | -25.0 |
| 13 | VMI + BetaDecouple | +10.4 | -21.4 | +23.9 | +3.7 | -10.5 | -6.1 |
| 14 | VIPT + SectorDisp + Squeeze | +0.6 | -8.8 | +9.9 | +26.4 | -26.3 | -11.7 |
| 15 | VIPT + BetaDecouple + Squeeze | +8.3 | -12.5 | -10.5 | +12.1 | +18.5 | -28.2 |
| 16 | VMI + VIPT + SectorDisp + Intention | +30.5 | +14.9 | -4.6 | +8.3 | -49.4 | -11.8 |
| 17 | VMI + VIPT + BetaDecouple | +61.0 | -27.8 | -1.1 | +18.1 | -19.5 | -40.1 |
| 18 | VMI + VIPT + BetaDecouple + Squeeze | +4.2 | -12.4 | -1.9 | -13.3 | +5.5 | -14.9 |
| 19 | Intention | +71.0 | -36.6 | +19.9 | -4.9 | -37.2 | -2.3 |
| 20 | VMI + VIPT + SectorDisp + BetaDecouple | +37.8 | -20.8 | +15.9 | +13.8 | -30.9 | -40.7 |

## Read-out

- **Best risk-adjusted edge**: `VMI + BetaDecouple + Intention` — Sharpe **1.63**, Calmar 0.47, 336 trades, win 42.6%, PF 1.48, MaxDD -55.6%.
- **Regime robustness (full years 2022–2025)**: positive in **3/4**.
- Treat single-filter rows as the baseline edge; multi-filter rows that *raise Sharpe without collapsing trade count* are the genuine interaction effects worth trading.
