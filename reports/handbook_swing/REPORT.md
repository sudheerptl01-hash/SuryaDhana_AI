# SuryaDhana Scanner Handbook — rules-only backtest, 2020-01-01 → 2026-10-09

Script: `scripts/handbook_swing_backtest.py` (settings fixed in its docstring before the first run).
Survivorship-free NSE bhavcopy panel (split/bonus adjusted, delisted stocks included), ₹5 lakh, Tier A rules,
risk 0.5% per trade, ICICI MoneySaver costs + 0.15% slippage per side unless stated. 8 variants run in total.

## Result

| Variant | CAGR | Max DD | Trades | Win % | Expectancy (R) |
|---|---|---|---|---|---|
| Gross: no costs, no slippage (GTT entry) | −2.5% | −25% | 1,101 | 38% | −0.03 |
| Gross, close-confirmed breakouts | 0.0% | −27% | 1,100 | 43% | +0.01 |
| Zero-brokerage broker + 0.10% slippage (handbook's cost assumption) | −7.4% | −45% | 1,101 | 34% | −0.09 |
| same, close-confirmed breakouts | −5.4% | −42% | 1,096 | 41% | −0.06 |
| **ICICI MoneySaver + 0.15% slippage (your broker)** | **−17.8%** | **−74%** | 1,103 | 30% | −0.25 |
| same, close-confirmed breakouts | −15.8% | −70% | 1,116 | 38% | −0.21 |
| ICICI, 1% risk per trade | −24.9% | −86% | 1,094 | 30% | −0.30 |
| ICICI, 1% risk, close-confirmed | −25.7% | −87% | 1,096 | 35% | −0.32 |
| Nifty 500 buy-and-hold (price) | +12.4% | −38% | | | |
| Decision Desk (approved, Nov-2019 → Sep-2026) | +18.5% | −14% | | | |

Verdict against the pre-registered bar (beat Nifty 500, DD ≤ 25%, expectancy > +0.2R, ≥ 100 trades): **fails on
every measure in every variant.** Per the plan, the 2011 → today run was not done.

## Where it fails (gross, no costs)

| Setup | Trades | Win % | Expectancy (R) | Note |
|---|---|---|---|---|
| A base breakout (GTT) | 392 | 29% | +0.08 | 272 of 392 exits are "failed breakout": price crossed the pivot intraday and closed back below |
| A base breakout (close-confirmed) | 126 | 29% | −0.05 | confirmation does not rescue it |
| B VCP | 10–16 | | ±0.3 | too few signals to judge |
| C pocket pivot | 70–169 | 24–29% | −0.12 to −0.38 | |
| D buyable gap-up | 35 | 34–36% | −0.39 to −0.46 | |
| E momentum burst | 441–577 | 39–43% | −0.09 to +0.04 | the most frequent setup; zero edge |
| F RSI(2) pullback in leaders | 148–173 | 68% | +0.12 to +0.15 | the only positive setup; ~0.2R of costs on ICICI wipes it out |
| G Holy Grail | 4 | | | too rare |

Costs on ICICI MoneySaver are ≈ 0.2R per trade (≈ 1.25% of a ₹20–30k position against stops of 5–8%).

## Not tested (no point-in-time data)
ASM/GSM/ESM surveillance lists, market cap, promoter pledge, fundamentals (Stage 6 "Fund"), catalysts and the
episodic-pivot setup, results dates. And — the handbook's own key component — the LightGBM meta-model: the handbook
says "rules make candidates; the model decides". This backtest is the rules alone.

## Bugs found and fixed during the run
NaN fill on a day without an opening print; renamed/delisted symbols held forever (now closed at the last traded
price after 5 sessions without prints). Both fixed before the final numbers above.
