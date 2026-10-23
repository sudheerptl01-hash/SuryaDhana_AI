# Q4: market-neutral long-short on F&O names via stock futures

**Plan:** `ml/IMPROVEMENT_PLAN_2.md` §2 Q4 (2 trials; ledger N = 261) · **Code:** `ml/improve/fo_ls.py` · **Results of record:** `ml/results/improve2/fo_ls/fo_ls.json` (every number in the results section below is quoted from it).

**Pass mark (plan, unchanged):** for each book, net annualised Sharpe ≥ 1.0 with its month-block 95% CI lower bound > 0, **and** beta to the Nifty 50 within ±0.2. Data 2018-01..2026-09 (signal dates).

## 1. Conventions and deviations (fixed 2026-10-23 02:50 UTC, before any result of this stream was computed)

The plan fixes the definitions; the items below settle what it leaves open. Items marked **D** are deviations from the plan's literal wording, with the reason; none changes a pass mark.

### 1.1 Inputs
- Scores: the ten-year control's out-of-sample predictions `ml/results/improve/ab/10y/preds/control__beat_mkt_20d.parquet` (103 folds 2018-01..2026-07 and the holdout 2026-08-03..2026-09-16), joined to the scored rows of `ml/data_10y/model_dataset.parquet` with `ml/books/data.py` (`load_base`, `load_scores`: rows with a label and `y_clean_20d`, exactly the base panel of every phase-1 book).
- Cash prices: `ml/results/improve/cache/features_prices_export_10y.parquet` (adjusted opens for the long leg, through `ml/strategy_backtest.py build_blocks`; the exit mark is pinned to `y_raw_20d` as the engine does). Price calendar from 2017-10-02, as the ten-year books.
- Futures: `ml/data_ext/fo_daily_stock.parquet` (near and next contract settle and expiry per stock and session, `main` and `hist` windows concatenated; the far contract is not stored).
- Index: `ml/data_ext/index_daily.parquet`, `index_name == "Nifty 50"`, close.
- Corporate actions: split/bonus adjustment factors are the integrity stream's, read as `close / close_unadj` from the features export (built from `ml/data_ext/corporate_actions_feed_10y.csv`, 755 validated events); unadjustable events from `ml/data_ext/price_break_flags_10y.csv`.

### 1.2 Universe on signal date t
1. F&O member on t: the stock has a row in the futures file on t (every row has `has_future = 1`). The futures file lacks one price session, 2021-03-30; membership on that session is the previous session's, and its settles are imputed (1.4).
2. Scored: the (ticker, t) row is in the base panel above. The universe therefore inherits the dataset's `y_clean_20d` screen (drops windows with a one-day move above 22%, a look-ahead screen every book of the program uses; for a short book it removes both its best and its worst outcomes). Stated, not changed.
3. Entry contract listed on t (point in time): the contract the short would use at entry (1.3) must be listed for the stock on t; a stock whose next-month contract is not issued (being removed from F&O) is out when it would need it.
4. Window exclusions (**D1**, the plan's "adjust or drop those (ticker, window) pairs"): a (ticker, t) pair is dropped from the universe before ranking, for both legs and both books, if inside its window
   - a price-break event of `price_break_flags_10y.csv` (rights, demerger, scheme of arrangement, capital reduction, unvalidated split/bonus) has its ex-date in sessions t+2..t+21 (an ex-date on t+1 is already priced at both entries);
   - the stock has an off-calendar contract on any session t+1..t+21 (its near or next expiry differs from that session's common expiry: the early expiries NSE imposes at demergers and mergers; 21 rows in the file);
   - a futures/cash break occurs on any session t+2..t+21: the same contract's split-adjusted settle return differs from the split-adjusted cash close return by more than 5 percentage points (an unadjusted contract adjustment or a data error; the two are both end-of-day prices and normally agree within a fraction of a point). *[Superseded by amendment A1, §1.8: a diagnostic, not an exclusion.]*
   These use the window's dates. Corporate-action ex-dates are announced in advance; the break screen is a data-quality screen in the same spirit as `y_clean_20d`. Counts are reported.
5. Splits and bonuses inside a window are **adjusted**, not dropped: every settle is multiplied by the stock's adjustment factor of its session, so a contract's return across an ex-date is continuous (NSE adjusts the contract price and lot by the same ratio as the cash price).

### 1.3 Books
- Two books (the 2 trials): **plain** (the control score) and **neutral** (the score neutralised within the F&O universe per date: `ml/books/engine.neutralise(kind="vol+size")` on that date's F&O universe rows, i.e. the rank residual on the ranks of `atr_pct` and `log_turnover`, re-ranked).
- Ranking on t within the universe (score descending, ticker ascending, as `sb.select`): k = max(1, round(0.2 n)); long = top k, short = bottom k. Equal weight within each leg; one rupee long and one rupee short per tranche at entry (dollar-neutral at entry; buy-and-hold inside the tranche, weights drift, as the engine).
- **Long leg:** cash, entry at the adjusted open of t+1, exit at the adjusted open of t+21, marked open to open (the engine's paths). *[Amendment A2, §1.8: in the long-short books the interior daily marks are closes; entry and exit unchanged.]*
- **Short leg:** short stock futures, marked on **settlement prices** (**D2**: futures opens are not in the staging table, so the settle replaces the open; entry at the settle of session t+1, exit at the settle of session t+21). The short leg's marks are therefore end-of-day while the long leg's are opening prices (about three quarters of a session apart).
  - Entry contract: the near-month contract at t+1 (the earliest expiry on or after t+1); if it has fewer than 3 sessions to expiry at t+1 (expiry session index minus entry session index ∈ {0, 1, 2}), the next-month contract.
  - Expiry session of a contract = the last price session on or before its expiry date (the June 2023 expiry dated 2023-06-29, a closure, maps to 2023-06-28).
  - Roll: when the held contract's expiry session e falls before the exit session, the position is closed at e's settle (the final settlement price) and opened in the next contract at e's settle; the return is chain-linked across the roll. A contract expiring on the exit session is simply closed at its final settlement. Physically settled contracts are treated as squared off at that price.
  - If the roll target is not listed for the stock (removal from F&O), the name closes at final settlement and is flat (zero return) for the rest of the window. A missing settle of a listed contract inside a window is carried forward (counted); an entry settle missing at t+1 is back-filled from the contract's next quote (as the engine back-fills a missing entry open; counted).
  - Basis convergence is included by construction (the short earns the futures premium as it converges to the cash price).
- Tranche P&L per rupee of notional = increment of the long leg's value path minus increment of the short leg's futures value path (`sb.ls_net`'s convention). Returns are quoted per rupee of long notional (gross exposure 2x); the futures margin is assumed posted from the long holdings (no extra cash, no interest on margin). No dividends on the long leg (the engine's price-only convention); the futures price already embeds expected dividends.
- Twenty overlapping tranches, one per signal date, aggregated daily with `sb.Calendar` (live-tranche average; every statistic exposure-weighted by live tranches / 20; idle capital at zero), exactly as the engine.

### 1.4 Data repairs
- Session 2021-03-30 (in the cash calendar, absent from the futures file): each contract's settle = the stock's unadjusted cash close on 2021-03-30 × that contract's settle / cash close ratio of the previous session; expiries as on the previous session (not an expiry session).

### 1.5 Costs
- Long: 20 bps per side, netted between consecutive tranches as the engine (`sb.trade_fracs`: the tranche entering at the open of t+1 replaces the one exiting at the same open; only the difference is traded; the 20 tranches without a neighbour pay the median steady-state turnover).
- Short: 40 bps per side, netted the same way **where the exiting and the entering tranche hold the same contract at the same settle** (exact netting, no cost on the overlap). Where they hold different contracts (entry in the last 3 sessions before expiry: the new tranche goes to the next month while the exiting one holds the near month) the overlap is a roll and pays 10 bps (**D3**: a roll, priced as the plan prices rolls, rather than 2 x 40 bps). Every roll inside a window pays 10 bps on the tranche's short notional still in futures. Roll costs cannot be netted across tranches (all tranches roll the same way).
- Sensitivities (reported, not pass marks): gross; and no netting (every tranche fully bought and fully sold: 2 x 20 bps long, 2 x 40 bps short, plus every roll).

### 1.6 Statistics
- Headline segment: all signal dates 2018-01-01..2026-09-16 (`combined`); `cv` and `holdout` reported alongside.
- Annualised net return: exposure-weighted mean daily net return x 252 (`sb.series_stats`); the tranche figure (mean tranche net x 252/20) alongside.
- **Sharpe (D4):** `sb.series_stats` on the daily net series with rf = 5.5% a year (`sb.RF_ANNUAL`, the engine's T-bill proxy), i.e. (mean − rf/252) / sd x √252. Reason: the short futures leg earns the cost of carry (≈ rf minus dividends) while the long leg's capital earns nothing else; with rf = 0 that carry would add about rf/volatility to the Sharpe for no skill. Subtracting rf makes the book comparable with the engine's rf = 0 long-short convention, whose cash short earned no carry. The rf = 0 Sharpe is reported alongside. Month-block bootstrap 95% CI, B = 1000, seed 108 (the Calendar's draws).
- Max drawdown: the fixed-capital NAV (`sb.series_stats`).
- Months positive: signal months whose mean tranche net return exceeds rf over 20 sessions (excess over cash); the count with net > 0 alongside.
- **Beta (D5):** two exposure-weighted daily estimators against the Nifty 50 close-to-close return: (i) plain, `sb.beta_alpha` on the same session; (ii) timing-corrected (Dimson), the sum of the slopes on the same-session and the previous-session index return in one exposure-weighted regression, because the long leg is marked open to open and so spans the previous session's afternoon. The beta part of the pass mark requires **both** within ±0.2. Per-leg betas are reported.
- Contributions: long-leg net (after long costs) and short-leg net (minus the futures return, after short costs and rolls) as annualised exposure-weighted daily means; they add to the book. Of the short leg, the basis component = short-futures gross minus the short of the same names' split-adjusted cash closes over the same sessions.
- Turnover: mean fraction of each leg replaced per rebalance (`sb.trade_fracs`), annualised x 252/20; rolls per tranche; names per leg; universe size.
- By year (calendar year of the P&L session): annualised net, Sharpe (rf 5.5%), long and short contributions, plain beta.
- **Deflated Sharpe:** `sb.dsr_block` on the exposure-weighted daily net series minus rf/252 (the series the Sharpe is computed on), V[SR] = 0.00387 (`ml/results/improve/books/books.json` `dsr_common.var_sr_daily_across_66_books`), N = 261.
- PASS per book: Sharpe (rf 5.5%, net, combined) ≥ 1.0 **and** its CI lower bound > 0 **and** |plain beta| ≤ 0.2 **and** |Dimson beta| ≤ 0.2.

### 1.7 Context (not trials)
- Long-only F&O top quintile (cash, 20 bps netted and the name-level cost model) vs the equal-weight F&O universe, plain and neutral, through `ml/books/engine.BookEngine.run_members` and `ml/books/construct.summarize`; and the bottom quintile vs the same benchmark (cash, the short side's information). Rank IC of each score with `y_raw_20d` inside the F&O universe (`construct.per_date_spearman`).

### 1.8 Amendments (2026-10-23 03:00 UTC, after a three-fold smoke run, before the full run)

*Lead's note: these stream-level amendments are recorded in `ml/IMPROVEMENT_PLAN_2.md` section 4 as Q4-a (A1 below) and Q4-b (A2 below) to avoid a clash with the plan's own A1; A2 was chosen after the smoke run's betas were seen, so the open-mark books are counted as two further trials (N = 270). Both conventions fail the pass mark.*

The smoke run (`--smoke`: signal dates 2019-01-01..2019-03-29 only, outputs in `fo_ls/smoke/`, not a result) and an inspection of the break-screen hits on the whole futures file led to two amendments. The smoke run's other figures (three months) were seen; they are not results and are not quoted. The pass mark is unchanged.

- **A1. The futures/cash break screen becomes a diagnostic, not an exclusion** (replaces the third bullet of 1.2 item 4). At 5 points it flags 333 stock-sessions (431 contract comparisons), and they are not adjustment breaks. The adjustment factor is unchanged on both days in every one of the largest cases. 299 of the 431 are next-month contracts, whose settles on illiquid days are exchange-computed theoretical prices, and the stocks are the distressed names of 2018-2020 (Jet Airways 55, DHFL 37, Yes Bank 30, Indiabulls Housing 18, Reliance Capital 16) on stress dates. Dropping those windows would remove crash windows from the short side with hindsight. Corporate actions stay handled as the brief specifies: split/bonus adjustment from the feed, price-break flags and off-calendar early expiries dropped. A split missing from both feeds would move the cash price too and is already masked by `y_clean_20d`. The counts are still reported.
- **A2. Daily marks of the long leg move to the closing price between entry and exit** (amends 1.3 "Long leg" for the long-short books only). Entry stays at the adjusted open of t+1 and exit at the adjusted open of t+21; the tranche return is unchanged (path[0] = 1 and path[20] = 1 + `y_raw_20d` as the engine pins it). The 19 interior marks are adjusted closes t+2..t+20 instead of adjusted opens. Reason: D2 puts the short leg on the end-of-day clock (settles). With open marks the long leg's daily increment spans the previous afternoon plus the overnight gap, while the short's spans the overnight gap plus the day. The market component then does not cancel day by day, which inflates the daily variance and makes the same-session beta measure the clock rather than the exposure. In the smoke run the plain book's same-session beta was −0.73 against a Dimson beta of +0.10, and the cash equal-weight F&O basket (open marks) read 0.64 against 1.38. These figures come from the first smoke run. `fo_ls/smoke/` now holds the re-run with A1 and A2 applied; its open-marks sensitivity reads −0.71 against +0.12. With interior closes, each tranche is mismatched only at its first and last increment (1/20 of the book per session each). This is also how a fund strikes its NAV (closes and settles). Both beta estimators are still reported and **both** must lie within ±0.2.
- **Sensitivity kept:** the long-short books with the engine's open-to-open long marks (the convention of 1.3 before A2) are reported in full alongside, with the pass mark evaluated the same way, so the effect of A2 is visible. The long-only context books (1.7) keep the engine's open marks (cash against cash, one clock).

<!-- RESULTS (written by ml/improve/fo_ls.py from fo_ls.json; everything above this line was fixed before any result) -->

## 2. Results

Signal dates 2018-01-01 to 2026-09-16 (2158), P&L sessions to 2026-10-16. Universe: 183 F&O names per date on average (355 stocks over the sample). Costs: long 20 bps per side, short 40 bps per side + 10 bps per roll. Sharpe uses rf 5.5% (FO_LS.md §1.6 D4). DSR at N = 261, V[SR] = 0.00387.

### 2.1 Pass mark

| Book | Net Sharpe [95% CI] | Sharpe ≥ 1.0 | CI lower > 0 | Beta plain | Beta Dimson | Both within ±0.2 | Verdict |
|---|---|---|---|---:|---:|---|---|
| plain | -0.65 [-1.43, +0.12] | no | no | -0.15 | -0.11 | yes | **FAIL** |
| neutral | -1.22 [-1.87, -0.53] | no | no | -0.05 | +0.00 | yes | **FAIL** |

### 2.2 The two books (all signal dates, net of costs unless stated)

| | plain | neutral |
|---|---:|---:|
| Annualised net return | -1.8% | -3.4% |
|   of which long leg (net) | +10.3% | +9.4% |
|   of which short leg (net, incl. basis and rolls) | -12.1% | -12.7% |
|   short leg's basis convergence (gross) | +3.3% | +3.3% |
| Annualised gross return | +9.1% | +8.1% |
| Annualised net, no netting | -7.1% | -8.1% |
| Annualised volatility | 11.2% | 7.3% |
| Sharpe, rf 5.5% [95% CI] | -0.65 [-1.43, +0.12] | -1.22 [-1.87, -0.53] |
| Sharpe, rf 0 [95% CI] | -0.16 [-0.92, +0.58] | -0.46 [-1.15, +0.27] |
| Gross Sharpe, rf 5.5% | +0.32 | +0.35 |
| Max drawdown (fixed capital); peak → trough | -42.8%; 2020-10-15 → 2026-01-16 | -34.0%; 2020-10-08 → 2025-06-04 |
| Max drawdown gross; peak → trough | -29.3%; 2020-10-15 → 2021-10-18 | -21.0%; 2020-10-08 → 2021-05-27 |
| Months positive (excess over rf) | 42/105 | 39/105 |
| Months positive (net > 0) | 50/105 | 47/105 |
| Beta to Nifty 50, plain | -0.15 | -0.05 |
| Beta to Nifty 50, Dimson (lag 0 + lag 1) | -0.11 | +0.00 |
|   long leg / short leg Dimson beta | +1.00 / -1.12 | +1.05 / -1.04 |
| Turnover per rebalance, long / short | 64% / 65% | 69% / 68% |
| Rolls per tranche; tranches entering next month | 0.81; 14% | 0.82; 14% |
| Names per leg (long / short); universe | 36.7 / 36.7; 183 | 36.7 / 36.7; 183 |
| Holdout (2026-08..09) net Sharpe | +0.23 | +0.30 |
| DSR (N = 261) | 0.000 | 0.000 |

The expected best null Sharpe at N = 261 and V[SR] = 0.00387 is 2.82 a year.

### 2.3 By year (calendar year of the P&L session; net)

| Year | plain: net / Sharpe / long / short / beta | neutral: net / Sharpe / long / short / beta |
|---|---|---|
| 2018 | -9.8% / -1.11 / -23.5% / +13.7% / -0.23 | -7.9% / -2.03 / -21.8% / +13.8% / -0.09 |
| 2019 | +14.1% / +0.60 / +3.4% / +10.7% / -0.43 | -0.6% / -0.88 / -4.1% / +3.5% / -0.07 |
| 2020 | +2.7% / -0.15 / +32.3% / -29.7% / -0.18 | -11.1% / -1.35 / +25.4% / -36.5% / -0.03 |
| 2021 | -17.1% / -2.31 / +23.3% / -40.4% / -0.17 | -7.9% / -1.93 / +27.4% / -35.3% / -0.00 |
| 2022 | -8.4% / -2.04 / -0.8% / -7.6% / -0.05 | -8.1% / -2.25 / -0.6% / -7.5% / -0.07 |
| 2023 | +0.3% / -0.96 / +29.1% / -28.8% / -0.05 | -2.3% / -1.66 / +27.2% / -29.6% / -0.03 |
| 2024 | +6.6% / +0.14 / +19.1% / -12.5% / +0.05 | +3.8% / -0.28 / +17.2% / -13.4% / -0.10 |
| 2025 | -9.3% / -1.89 / +3.8% / -13.1% / -0.05 | -1.4% / -1.16 / +7.6% / -8.9% / -0.07 |
| 2026 | +6.7% / +0.15 / +1.4% / +5.4% / -0.10 | +7.7% / +0.29 / +2.0% / +5.7% / -0.04 |

### 2.4 Context (not trials): long-only F&O quintiles vs the equal-weight F&O universe (cash)

| Score | Basket | Excess vs EW F&O, 20 bps | IR [95% CI] | Name-level cost excess | Months beating EW | Turnover |
|---|---|---:|---|---:|---:|---:|
| plain | top_quintile | -1.7% | -0.28 [-1.04, +0.45] | -3.0% | 46/105 | 64% |
| plain | bottom_quintile | -8.1% | -1.34 [-2.13, -0.53] | -9.7% | 31/105 | 65% |
| neutral | top_quintile | -2.6% | -0.65 [-1.38, +0.07] | -4.3% | 41/105 | 69% |
| neutral | bottom_quintile | -7.5% | -1.91 [-2.83, -1.05] | -9.1% | 18/105 | 68% |

Equal-weight F&O universe: +11.8% a year, Sharpe (rf 5.5%) +0.30. Rank IC with y_raw_20d inside the F&O universe: plain +0.026, neutral +0.023. Beta check on the cash EW F&O universe: with the engine's open marks plain +0.33, Dimson +1.05; with interior close marks (A2) plain +0.94, Dimson +1.03.

### 2.5 Sensitivity: the long leg on the engine's open-to-open marks (the convention before amendment A2)

Tranche returns are identical to the primary books; only the daily marks, and so the daily statistics, differ.

| Book | Net Sharpe [95% CI] | Ann. vol | Beta plain | Beta Dimson | Max DD | DSR | Verdict under the same rule |
|---|---|---:|---:|---:|---:|---:|---|
| plain | -0.28 [-0.59, +0.04] | 26.2% | -0.76 | -0.12 | -50.4% | 0.000 | FAIL |
| neutral | -0.35 [-0.59, -0.12] | 25.2% | -0.67 | -0.00 | -49.2% | 0.000 | FAIL |

### 2.6 Data accounting

- F&O member rows among the scored rows: 396,572 of 2,137,000; excluded: entry contract not listed 598, price-break flag in window 554, off-calendar contract in window 78 (any window rule 598); universe 395,376 rows, of which 2,919 have a futures/cash gap above 5 points inside the window (kept, amendment A1).
- Futures file: 359 stocks; sessions imputed ['2021-03-30']; off-calendar rows 24 (ABFRL, HINDUNILVR, IDFC, IOC, ITC, SIEMENS, TATAMOTORS, VEDL); break sessions 333 of 812,761 comparisons.
- Short paths: 395,376 name-windows; entry settle back-filled 2, never quoted (flat) 0; settles carried forward 364; names flat after a final settlement with no roll target 2456; exiting tranche not in the next entry's near contract 0.
- Long paths: exit mark matches the label on 100.000% of rows; entry open back-filled 0; interior close marks carried forward 0.
- Nifty 50 sessions missing on the price calendar (forward-filled): [].
- Independent recomputation of the short leg (seeded sample of 400 name-windows, straight from each stock's raw futures rows without the common calendar): 390 checked (318 with a roll, 10 skipped for a gap or a flat tail), largest difference in the exit value 1.6e-15.
- Split/bonus adjustment of the futures: 76 validated ex-dates of F&O stocks with quotes on both sides; the unadjusted settle moves by a median 51% on the ex-date, the adjusted settle stays within 4.0 points of the adjusted cash close (2.6% of events above 2 points).

### 2.7 Sensitivity added after the results of record: dividends (total return)

This sensitivity was added after §2.1-2.6 existed. It changes no convention, book or pass mark. The primary long leg is price-only (the engine's convention) and the futures short owes no dividends, so the book misses the long leg's dividends. Separately, NSE adjusts a stock-futures contract on the ex-date of a large dividend, and the unadjusted settle chain books that adjustment as a gain to the short. The sensitivity corrects both. Cash dividends with ex-date t+2..t+21 are credited to the long leg. On contracts classified as adjusted, the dividend is added back to the ex-date settle. Rule: adjusted if dividend >= 2% of the previous unadjusted close and the ex-date futures-minus-cash return gap < 0.5 x the dividend yield.

- Dividend events of F&O stocks with a parsed amount: 99.4% (3,423 in the price span). Events at or above 2% of price: 444, of which 158 fall outside the stock's F&O membership (no short exposure possible) and 12 are members without a quote on one side or with a split the same day (left unadjusted). Classified as adjusted contracts: 139. By year (member events at or above 2% / classified adjusted): 2017 1/0, 2018 31/3, 2019 32/4, 2020 37/10, 2021 34/9, 2022 46/11, 2023 41/40, 2024 18/17, 2025 23/23, 2026 23/22.
- Cross-check: the dividend credit of the equal-weight F&O universe is +1.48% a year. The Nifty 50's own dividend yield averages +1.27% over the same sessions.

| Book | Net ann. | Long-leg dividends | Short-leg add-back | Net Sharpe [95% CI] | Sharpe rf 0 | Beta plain / Dimson | DSR | Verdict under the same rule |
|---|---:|---:|---:|---|---:|---|---:|---|
| plain | -0.8% | +1.39% | -0.45% | -0.57 [-1.34, +0.19] | -0.08 | -0.15 / -0.11 | 0.000 | FAIL |
| neutral | -2.4% | +1.37% | -0.44% | -1.09 [-1.75, -0.41] | -0.34 | -0.05 / +0.00 | 0.000 | FAIL |

<!-- END OF GENERATED RESULTS -->

## 3. Reading (hand-written; every number is from `fo_ls.json`)

**Verdict: both books FAIL the plan's pass mark.** Plain: net Sharpe −0.65 [−1.43, +0.12]. Neutral: −1.22 [−1.87, −0.53]. Both use rf 5.5%, combined segment, `books.<name>.pass_mark`. Neither reaches 1.0, and neither interval lies above zero. The DSR at N = 261 is 0.000 for both. The market-neutral part of the construction works: the beta to the Nifty 50 is −0.15 plain / −0.11 Dimson for the plain book and −0.05 / +0.00 for the neutral one. Each leg carries a beta near one (long +1.00 / +1.05, short −1.12 / −1.04, Dimson), and the two cancel. The failure is the return, not the hedge.

1. **No cost assumption rescues it.** Gross of all costs the books earn +9.1% (plain) and +8.1% (neutral) a year. Of that, +3.3% is the short futures' basis convergence (`short_leg_basis_ann`), which is roughly the cost of carry. The gross Sharpe at rf 5.5% is +0.32 and +0.35 (`segments.combined.gross.sharpe`). With rf = 0, which credits the carry to the book, the gross figures are +0.81 [+0.04, +1.54] and +1.10 [+0.31, +1.90]. Both readings are without a single rupee of cost. Costs then take 10.9 and 11.4 points a year: about 65% to 69% of each leg is replaced every rebalance, the short pays 40 bps a side, and the book rolls 0.81 to 0.82 times per tranche. That leaves −1.8% and −3.4% net, and −7.1% and −8.1% when nothing is netted.
2. **Within F&O names the score carries little information, and what it has sits on the short side.** The rank IC with `y_raw_20d` inside the F&O universe is +0.026 (plain) and +0.023 (neutral) (`context.*rank_ic*`), against +0.088 on the full ten-year universe (PROGRAM_REPORT §13.6). Long-only, against the equal-weight F&O universe:
   - The top quintile adds +1.5% (plain) and +0.9% (neutral) a year gross, and trails after 20 bps: −1.7% (IR −0.28 [−1.04, +0.45]) and −2.6% (IR −0.65).
   - The bottom quintile trails by −4.8% and −4.0% a year gross, and by −8.1% and −7.5% after 20 bps. The neutral bottom quintile beats the benchmark in only 18 of 105 months.
   So the model does know which F&O names will lag. But the short leg's own costs exceed that gross shortfall: about 6.6 points a year in round trips (40 bps × 2 sides × 65% turnover × 12.6 rebalances) plus about 1.0 point in rolls (0.81 × 10 bps × 12.6).
3. **By year** (§2.3) the plain book is ahead only in 2019 (+14.1%), 2020 (+2.7%), 2023 (+0.3%), 2024 (+6.6%) and 2026 (+6.7%). Its worst year is 2021 (−17.1%), when the short leg lost 40.4% in the small- and mid-cap rally. Gross of costs, the largest drawdown is −29.3% (plain, 2020-10-15 to 2021-10-18, recovered 2024-05-02) and −21.0% (neutral, 2020-10-08 to 2021-05-27, recovered 2024-02-02). Net of costs it is −42.8% (plain, 2020-10-15 to 2026-01-16) and −34.0% (neutral, 2020-10-08 to 2025-06-04), and neither book recovers by the end of the sample (`segments.combined.<gross|net>.max_dd_*`). Months ahead of cash: 42/105 (plain) and 39/105 (neutral).
4. **The amendments do not decide the verdict.** With the engine's open-to-open long marks (§2.5) the net Sharpe is −0.28 and −0.35. The same-session beta is −0.76 and −0.67, the clock artefact A2 removes. The tranche returns are identical under both conventions (`sensitivity_open_marks.*.tranche_returns_identical_to_primary`). A1 keeps 2,919 universe rows (0.7% of 395,376) that have a futures/cash gap above 5 points inside the window. No run with those rows excluded was made, so A1's effect is not quantified here.
5. **Dividends do not decide it either** (§2.7, a sensitivity added after the results; not a pass-mark input). Crediting the long leg's cash dividends adds +1.39% (plain) and +1.37% (neutral) a year. Removing the short leg's spurious gain on contracts NSE adjusted for a large dividend takes away 0.45% and 0.44%. The total-return books earn −0.8% and −2.4% a year, with net Sharpe −0.57 [−1.34, +0.19] and −1.09 [−1.75, −0.41]: FAIL under the same rule (`sensitivity_total_return`). The adjustment rule is read from the futures prices themselves. Contracts classified as adjusted are rare among member events at or above 2% of price in 2018-2022 (37 of 180). From 2023 they are nearly all of them (102 of 105). The parsed dividends are plausible: the equal-weight F&O universe's dividend credit is +1.48% a year, against the Nifty 50's own dividend yield of +1.27%. The primary short leg was therefore flattered by about 0.45 points a year on average, most of it after 2022, and the primary long leg understated by about 1.4 points throughout. Together the corrections add about 0.9 points a year. A net Sharpe of 1.0 at rf 5.5% would need a net return of rf plus one volatility: about 16.7% (plain, volatility 11.2%) and 12.8% (neutral, 7.3%) a year, against −0.8% and −2.4%.
6. **Checks** (§2.6). The short-leg engine was recomputed independently, straight from each stock's raw futures rows: 390 sampled name-windows (318 with a roll) match the exit value to 1.6e-15 (`data.independent_short_check`). On the 76 validated split/bonus ex-dates of F&O stocks, the adjusted futures settle stays within 4.0 points of the adjusted cash close, while the unadjusted settle moves by a median 51% (`data.split_bonus_check`).
7. **Holdout** (2026-08-03..2026-09-16 signals; 51 P&L sessions): net Sharpe +0.23 and +0.30. That is too short to read.
8. **Consistent with phase 1.** The F&O names are the liquid end of the market, where the ten-year liquid-tercile books earned nothing (§13.6: neutral liquid +1.2% a year, IR 0.21). The long leg's capacity is large (about ₹2,000 crore at 5% of ADV for the tenth-percentile name, `capacity_long_leg`), but there is no return to scale. The question the plan asked ("does a market-neutral long-short book on F&O names work net of futures costs?") is answered **no**, for this score and this construction. The short side's gross information (about 4 to 5 points a year) is real, but it is smaller than the cost of harvesting it monthly through stock futures.

Trial ledger: these are the plan's 2 Q4 trials (N = 261 already counts them). The context books, the open-marks sensitivity and the total-return sensitivity are not trials.
