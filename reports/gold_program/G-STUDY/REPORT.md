# G-STUDY — Is CFTC Commitments-of-Traders positioning (and the usual "gold health" indicators) USEFUL to a gold trader?

Research team, SuryaDhana GOLD program · Mon 26 Oct 2026 · agent G-STUDY
Files: `g_study.py` (the study, reproducible), `data/` (every download, see `DATA_SOURCES.md`), `results/` (CSVs), `figures/`,
`RESULTS_TABLES.md` (every table the script produced), `summary.json`, `FINDINGS.md` (one page).

The owner's gate: *"analyse first: will it be useful to refer to the data being presented? if yes then only publish."*
This report answers that for the COT and its usual companions, for two different jobs:

1. **Forecasting** — does the number tell you where gold goes next (1, 4, 13 weeks)? → tested like a trading signal.
2. **Describing** — does it explain what just happened (was the rally new longs or short covering; who sold the dip)? → tested
   as a same-week relation, which is a legitimate, different use the owner asked for.

---

## 0. Glossary first (for the reader new to gold; professionals skip to §1)

| Term | Plain English | Exact definition / pitfall |
|---|---|---|
| **COMEX** | The New York futures exchange (part of CME Group) where the world's benchmark gold futures trade. | Contract GC: 100 troy oz, $/oz, delivery months Feb/Apr/Jun/Aug/Oct/Dec most active. MCX gold ≈ COMEX × USD/INR ÷ 31.1035 × 10 (per 10 g) plus Indian duty/premium. |
| **CFTC** | The US regulator of futures markets. | Commodity Futures Trading Commission. |
| **COT report** | The CFTC's weekly census of who holds the futures: it groups every large trader's positions by *type of trader*. | Positions as of **Tuesday close**, published **Friday 15:30 ET** (3-day lag; longer around US holidays, and much longer during government shutdowns: 2013, 2018-19, 2025). Weekly only — there is no daily version. |
| **Legacy report** | The old two-way split: *commercial* (hedgers) vs *non-commercial* (large speculators) plus *non-reportable* (small traders). | Since 1986 for gold. |
| **Disaggregated report** | The modern four-way split (since 2006): **Producer/Merchant/Processor/User** (miners, refiners, jewellers — physical hedgers), **Swap Dealers** (banks hedging OTC client exposure — includes the "bullion banks"), **Managed Money** (hedge funds, CTAs — "the funds", "the specs"), **Other Reportables** (large traders that fit none of the above: family offices, some central-bank agents, prop desks). | Classification is by the trader's *self-declared* business, not by the trade's purpose; a bank's prop desk sits in Swap Dealers; "Other reportables" is a growing, opaque bucket (95,659 net long today). |
| **Futures-only vs combined** | The combined report adds options, converted to futures-equivalents by their delta. | Options-only positioning = combined − futures-only. |
| **Open interest (OI)** | The number of contracts outstanding (each has a long and a short). | COT `open_interest_all`. Falls when both sides close (liquidation), rises when both sides open. |
| **Net position** | Longs minus shorts of a trader group. | Managed-money net = `m_money_positions_long_all − m_money_positions_short_all`. Commercial net (disaggregated) = producer/merchant net + swap-dealer net. |
| **52-week COT index** | Where today's net position sits between its 1-year low (0) and high (100). | `(net − min52) / (max52 − min52) × 100`. The desk lore: ≥ 90 = "crowded long, fade it", ≤ 10 = "washed out, buy it". |
| **z-score** | Today's net position in standard deviations from its 1-year average. | `(net − mean52) / sd52`. |
| **Managed money, % of OI** | Net fund position scaled by the size of the market. | `mm_net / open_interest_all × 100`. 25.9 % today. |
| **Short covering / long liquidation / new longs / new shorts** | The four ways a price move can happen: buyers who had sold (short covering) or fresh buyers (new longs); sellers who had bought (long liquidation) or fresh sellers (new shorts). | From the COT: Δ gross long and Δ gross short of a group. From OI: price ↑ & OI ↑ = new longs; price ↑ & OI ↓ = short covering; price ↓ & OI ↑ = new shorts; price ↓ & OI ↓ = long liquidation. |
| **GLD tonnes** | The gold held by the largest gold ETF (SPDR Gold Shares); investors' "paper gold" demand. | Daily from the issuer; 1,045.6 t on 22 Oct 2026. |
| **Real yield (DFII10)** | The yield on 10-year US inflation-protected bonds — the opportunity cost of holding gold, which pays nothing. | FRED series DFII10; 2.64 % on 22 Oct. Gold tends to move inversely with it *in the same week*. |
| **DXY** | The US dollar index (vs EUR, JPY, GBP, CAD, SEK, CHF). | A strong dollar usually means a weaker gold price in dollars, same week. |
| **IC (information coefficient)** | How well a signal ranks future returns, from −1 to +1. 0.05 is weak, 0.10 is good, 0.00 is nothing. | Spearman rank correlation of the signal with the forward return; t-stat Newey-West (the 4- and 13-week windows overlap, which inflates naive t-stats). |
| **Walk-forward / out-of-sample (OOS)** | The rule is fitted only on data before each decision, so the backtest never peeks. | Expanding window; in-sample (IS) = first 40 % of weeks (optimistic by construction), OOS = the rest. |
| **Look-ahead** | Using a number before it was actually published. | The classic COT mistake: dating Tuesday's positions on Tuesday. Here every signal is dated at the CFTC release and traded at the next session's close. |

---

## 1. Question

For each metric the owner listed — managed-money net (level, 4-week change, 52-week COT index, z-score, extremes), commercial net,
small-spec net, open-interest changes, options-only positioning, GLD holdings change, real-yield change, DXY change, month-of-year,
and the OI-price quadrant — at 1-, 4- and 13-week horizons:

- H-forecast: a signal known at the COT release predicts the next h-week gold return (decile spread and rank IC significant at
  |t| ≥ 2.5, same sign in all three sub-periods, and a walk-forward long/flat rule that beats scaled buy-and-hold after costs with
  t ≥ 2). Pre-registered directions: contrarian for fund extremes, "follow the commercials", falling real yields / dollar bullish,
  ETF inflows bullish; 4-week changes, OI and options exploratory.
- H-describe: the same metric explains the *contemporaneous* weekly move (same-week rank correlation, stability by sub-period).

## 2. Data (all free, all verified live; details in `DATA_SOURCES.md`)

### 2.1 Positioning
CFTC COT for COMEX gold (contract code 088691) from the CFTC's Socrata API — disaggregated futures-only and combined
(1,063 weekly reports, 13 Jun 2006 → 20 Oct 2026), legacy futures-only (1,939 reports, 1986 →) and legacy combined (1,648, 1995 →).
Cross-checked against the 44 raw history zips on cftc.gov: identical row counts and zero value mismatches on every field tested.

### 2.2 Prices
**GC=F from Yahoo** (COMEX front-month continuous settlement, 6,564 daily bars, 30 Aug 2000 → 25 Oct 2026). Chosen because it is
the longest *clean* free daily series reachable from this machine and it is the instrument the COT describes: FRED's LBMA fix
series (`GOLDPMGBD228NLBM`, the brief's first choice) now returns 404, stooq is behind a JavaScript proof-of-work wall, and Nasdaq
Data Link's LBMA set needs a key. Roll check: GC=F vs GLD (ETF, adjusted close) weekly returns Nov 2004 → Oct 2026 correlate at
**0.983**; CAGR 10.49 % vs 10.03 %, a 0.46 %/yr gap that is GLD's 0.40 % expense ratio, so front-month roll gaps add no material
drift. For the MCX view, GC=F × USD/INR (`INR=X`, 2003 →) is the proxy: **no free MCX gold daily history exists** — mcxindia.com
answers 403 to every non-browser request (bhavcopy, historical data, quotes), CME's OI pages likewise, and Breeze (credentialed)
was off-limits for this study.

### 2.3 Companions
FRED `DFII10` (10-y real yield, via the key-less `fredgraph.csv`; `.env` has no `FRED_API_KEY`), Yahoo `DX-Y.NYB` (DXY, 1971 →),
SPDR's own GLD archive (xlsx, daily tonnes since 18 Nov 2004; **its disclaimer prohibits redistribution**).

### 2.4 The look-ahead guard (the part most COT studies get wrong)
A report dated Tuesday T is released Friday 15:30 ET (after the COMEX settlement). The entry is therefore the **Monday close**
(T + 6 days) — 851 of 1,059 usable reports. When a federal holiday falls Tuesday–Friday the CFTC releases on Monday and the
entry becomes Tuesday (165 reports at T + 7). The verified catch-up calendars were applied for the 2025 shutdown (reports of
30 Sep – 23 Dec 2025 released 19 Nov – 29 Dec 2025, up to 51 days late), the 2023 ION cyber incident (seven reports, up to 24 days
late) and the 2018-19 shutdown (eleven reports, released 1 Feb – 8 Mar 2019 per CFTC release 7864-19). The four October 2013
reports, whose catch-up dates could not be verified on cftc.gov, were **excluded**. GLD tonnes, DFII10 and DXY are taken as of the
Friday release date (published before the Monday close). A robustness run enters two sessions later (Wednesday close).

Forward return at horizon h = close at the last session ≤ entry + 7h days ÷ entry close − 1. Unconditional: 1 wk 0.23 %
(sd 2.5), 4 wk 0.87 % (sd 4.7), 13 wk 2.74 % (sd 8.2). Sub-periods: pre-2011 (2006 → 2010; legacy 2000 → 2010), 2011-19, 2020-26.

## 3. Method

- **Deciles, walk-forward:** each week's signal is ranked against its own *past* (expanding percentile, ≥ 104 weeks of history), so
  no cut-off uses future data; decile 10 = highest tenth of history-to-date. Per decile: mean forward return, hit rate, Newey-West t
  of the excess over the unconditional mean (lags = h − 1). Top-minus-bottom spread with NW t. Rank IC with NW t on the slope.
- **Classic bands:** COT index ≥ 90 / ≤ 10, by sub-period.
- **Long/flat rule after costs, walk-forward:** one tranche a week, each held h weeks (so h overlapping tranches), position = 1
  when the signal's expanding percentile is in the favourable tercile. The favourable *direction* is learned from completed history
  only (sign of the IC on pairs whose forward window had ended before the decision); fixed-direction variants (the lore: contrarian
  on funds, follow the commercials, fade dollar strength, follow ETF inflows) are also run. Cost: 0.15 % per round trip (the
  project floor; `shared/mcx_specs.round_trip_costs("GOLD", ₹122,104/10 g)` gives ₹2,146 per 1-kg lot = 0.018 %, so the floor
  is deliberately harsh). Benchmark: buy-and-hold **scaled to the same average exposure** — a rule that is long 30 % of the time
  must beat 30 % of gold, not 100 % of it.
- **Seasonality:** mean 4-week return by calendar month with t; walk-forward "long in the 6 best months of all prior years".
- **Quadrants:** report-week price change × OI change → four states, forward returns per state.
- **Descriptive:** same-week Spearman/Pearson, R², "percent move per 1,000 contracts", share of weeks with the same sign, and —
  the acid test — the same change against the *following* week; stability by sub-period; a "who did what" decomposition of the
  last 12 reports, of the last rally, and of the decline since its high.
- **Multiple testing:** 45 learned signal × horizon tests + 24 legacy + 69 walk-forward rules + 12 months + 12 quadrant cells
  ≈ 160 tests; ~8 should show |t| ≥ 2 by chance alone. The PASS bar (|t| ≥ 2.5, same sign in every sub-period, OOS t ≥ 2 after
  costs) is set with that in mind.

## 4. Results — forecasting

### 4.1 Rank IC and decile spreads (disaggregated COT, 2006-2026)

| Signal | h | n | top decile % | bottom decile % | spread % (t) | IC (t) | IC pre-2011 / 2011-19 / 2020-26 |
|---|---|---|---|---|---|---|---|
| Managed-money net | 1 | 953 | 0.19 | 0.48 | −0.29 (−1.0) | −0.008 (−0.7) | +0.01 / −0.08 / +0.04 |
| | 4 | 950 | 1.27 | 1.01 | +0.26 (+0.2) | +0.013 (+0.6) | −0.04 / −0.09 / +0.13 |
| | 13 | 941 | 1.61 | 3.30 | −1.69 (−0.7) | +0.075 (+0.9) | −0.09 / −0.10 / **+0.28 (t 2.3)** |
| MM net, % of OI | 1/4/13 | 953 | | | +0.1 / +0.6 / +0.9 (t ≤ 0.6) | −0.02 / 0.00 / +0.07 (t ≤ 0.8) | signs flip 2011-19 (−) vs 2020-26 (+) |
| MM net, 4-week change | 1 | 949 | 0.16 | 0.53 | −0.37 (−1.3) | **−0.055 (−2.3)** | −0.00 / −0.06 / −0.08 (same sign) |
| | 4 | 946 | 0.29 | 0.96 | −0.66 (−0.8) | +0.005 (+0.3) | −0.06 / −0.01 / +0.05 |
| | 13 | 937 | 0.64 | 2.29 | −1.64 (−1.3) | −0.021 (−0.7) | −0.01 / −0.04 / −0.01 |
| MM 52-wk COT index | 1 | 902 | 0.14 | 0.24 | −0.10 (−0.3) | −0.026 (−0.6) | +0.06 / −0.07 / −0.02 |
| | 4 | 899 | 1.38 | 0.61 | +0.77 (+1.0) | +0.008 (+0.7) | −0.04 / −0.09 / +0.05 |
| | 13 | 890 | 3.35 | 1.96 | +1.40 (+0.8) | +0.092 (+1.1) | −0.11 / −0.07 / +0.21 |
| MM 52-wk z-score | 1/4/13 | 902 | | | −0.44 / −0.29 / −1.63 (t −1.4 / −0.4 / −1.0) | −0.05 / −0.04 / +0.01 | mixed |
| Commercial net | 1/4/13 | 953 | | | +0.16 / −0.44 / +0.46 (t ≤ 0.6) | 0.00 / −0.02 / −0.08 (t ≤ 1.0) | + / + / − (2020-26 wrong sign) |
| Commercial COT index | 13 | 890 | 2.40 | 3.38 | −0.98 (−0.5) | −0.077 (−1.1) | +0.18 / +0.12 / **−0.25 (t −2.2)** |
| Small-spec net | 1/4/13 | 953 | | | −0.20 / −0.61 / −0.78 (t ≤ 0.5) | +0.01 / −0.02 / +0.01 | all weakly negative, none significant |
| OI, 1-wk change | 1/4/13 | 952 | | | −0.19 / 0.00 / −0.78 | −0.04 / −0.02 / −0.05 (t −1.4 / −0.4 / −1.6) | |
| OI, 4-wk change | 1/4/13 | 949 | | | | −0.01 / +0.03 / −0.02 | 2020-26 4-wk +0.12 (t 2.0) only |
| Options-only MM net (and its 4-wk change) | 1/4/13 | 953 | | | | −0.01 to −0.04 (t ≤ 1.1) | nothing |
| GLD tonnes, 4-wk change | 1/4/13 | 945 | | | −0.3 / −1.0 / +0.6 (t ≤ 1.0) | −0.03 / −0.01 / 0.00 | |
| Real yield, 4-wk change | 1/4/13 | 945 | | | −0.1 / −1.5 / −0.5 (t ≤ 1.5) | −0.02 / −0.06 / −0.01 | right sign, no power |
| DXY, 4-wk change | 1/4/13 | 945 | | | +0.2 / 0.0 / −1.3 | −0.01 / −0.06 / −0.03 (t ≤ 1.4) | right sign, no power |

One of 45 tests clears |t| = 2 (the 1-week reversal after a big 4-week fund build-up, IC −0.055) — exactly the number chance
predicts. It has the same sign in all three sub-periods, so it was taken forward to the trading test (§4.3), where it earns
+2.0 %/yr OOS at t 0.95: not tradable. The 13-week fund-net result in 2020-26 (IC +0.28) is the *opposite* of 2011-19 (−0.10):
funds were right-way in the great bull market and wrong-way in the range — a regime description, not a signal. Full decile tables
for eight signals × three horizons are in `RESULTS_TABLES.md`; none shows a monotone pattern (fig 2).

### 4.2 The classic desk rule: COT index ≥ 90 "crowded long" / ≤ 10 "washed out"

| h | band | n | mean % | hit % | vs all (t) | pre-2011 | 2011-19 | 2020-26 |
|---|---|---|---|---|---|---|---|---|
| 1 | ≥ 90 | 158 | 0.07 | 50 | −0.16 (−0.8) | +0.47 | −0.14 | −0.02 |
| 1 | ≤ 10 | 181 | 0.26 | 54 | +0.03 (+0.2) | +1.48 (n 10) | +0.23 | +0.14 |
| 4 | ≥ 90 | 158 | **1.08** | 57 | +0.20 (+0.4) | +2.28 | +0.02 | +1.30 |
| 4 | ≤ 10 | 181 | **0.63** | 60 | −0.25 (−0.5) | +5.08 (n 10) | +0.88 | −0.37 |
| 13 | ≥ 90 | 158 | 2.97 | 61 | +0.18 (+0.1) | +5.36 | −0.46 | +4.86 |
| 13 | ≤ 10 | 181 | 2.15 | 56 | −0.64 (−0.5) | +12.22 (n 10) | +1.98 | +0.97 |

"Crowded" weeks returned *more* than "washed-out" weeks at 4 and 13 weeks — the lore is not merely weak, it points the wrong way
in two of three sub-periods. A fund-crowded gold market in a bull trend stays crowded.

### 4.3 Walk-forward long/flat rules after 0.15 % costs (OOS from Aug 2014 / Mar 2015 → Oct 2026)

| Rule (direction learned walk-forward unless stated) | h | OOS exposure | OOS CAGR rule | OOS CAGR gold | excess vs scaled B&H, %/yr (t) |
|---|---|---|---|---|---|
| MM net | 1 / 4 / 13 | 26–30 % | 3.4 / 3.5 / 1.7 | 9.8 | +0.9 (0.5) / +0.4 (0.2) / −0.7 (−0.5) |
| MM 4-wk change | 1 / 4 / 13 | 32–33 % | 5.4 / 0.5 / 3.5 | 10.2 | **+2.0 (0.95)** / **−2.9 (−2.1)** / −0.1 (−0.1) |
| MM 52-wk COT index | 1 / 4 / 13 | 30 % | 1.0 / −0.6 / 2.6 | 11.1 | −2.1 (−0.9) / **−3.8 (−2.1)** / −0.8 (−0.5) |
| MM z-score | 1 / 4 / 13 | 26–35 % | 2.2 / 1.9 / −1.3 | 11.1 | −1.4 / −1.9 / **−4.3 (−3.2)** |
| Commercial net | 1 / 4 / 13 | 16–30 % | 3.4 / 1.9 / 3.4 | 9.8 | +1.9 (1.3) / +0.3 (0.3) / +0.5 (0.3) |
| Small-spec net | 1 / 4 / 13 | 19–22 % | 1.3 / 1.9 / 1.1 | 9.8 | −0.3 / −0.2 / −0.8 |
| OI 1-wk / 4-wk change | best of 6 | 35 % | 4.5 | 9.9 | +0.9 (1.5) |
| Options-only MM net (+ change) | best of 6 | 22 % | 3.6 | 9.8 | +1.5 (0.7) |
| GLD 4-wk change | 1 / 4 / 13 | 28–37 % | 3.5 / 2.3 / 1.9 | 10.3 | −0.3 / −1.5 / −1.0 |
| Real-yield 4-wk change | 1 / 4 / 13 | 27–31 % | 1.6 / 3.2 / 1.7 | 10.3 | −1.0 / +0.5 / −1.6 |
| DXY 4-wk change | 1 / 4 / 13 | 31–35 % | 4.7 / 2.6 / 2.9 | 10.3 | +1.1 (0.5) / −1.0 / −0.4 |
| **Fixed lore:** fade the COT index (long when ≤ bottom tercile) | 1 / 4 / 13 | 35 % | 3.2 / 1.7 / 2.2 | 11.1 | −0.4 / −2.0 (−1.1) / −1.6 (−0.9) |
| **Fixed lore:** follow the commercials | 1 / 4 / 13 | 25 % | 4.3 / 3.2 / 2.6 | 9.8 | +1.8 (1.0) / +0.7 (0.5) / +0.1 (0.0) |
| **Fixed lore:** fade dollar strength | 1 / 4 / 13 | 31 % | 5.6 / 4.6 / 2.9 | 10.3 | +2.5 (1.1) / +1.3 (0.9) / −0.4 |
| **Fixed lore:** follow ETF inflows | 1 / 4 / 13 | 32 % | 5.1 / 4.8 / 3.3 | 10.3 | +2.0 (0.8) / +1.6 (0.9) / −0.1 |
| **In rupees** (GC=F × USD/INR), COT-index rule learned / contrarian | 4 | 35 % | 3.1 / 3.1 | **15.1** | −2.0 (−1.1) / −2.0 (−1.1) |

**Zero of 69 rules beat scaled buy-and-hold at t ≥ 2; three lost at t ≤ −2.** The learned rules average −0.8 %/yr OOS, the
fixed-lore rules +0.2 %/yr — i.e. noise around zero with 0.15 % costs. The in-sample columns (`RESULTS_TABLES.md`) are no better,
which is itself informative: there was nothing to overfit. Fig 3 shows the OOS equity curves against gold, which compounded
at 10–11 %/yr in dollars and 15 %/yr in rupees over the OOS window; a rule that is in the market a third of the time cannot
keep up and does not pick its third well. Robustness: entering on Wednesday instead of Monday changes no IC by more than 0.04.
Legacy report 2000-2026 (large speculators, commercials, small traders, 24 tests): no |t| ≥ 2.

### 4.4 Month of year

| Month | n | mean 4-wk % | hit % | t vs all |
|---|---|---|---|---|
| Jan | 86 | **+2.41** | 72 | **+2.2** |
| Feb | 82 | +0.39 | 50 | −0.7 |
| Mar | 93 | +1.14 | 61 | +0.3 |
| Apr | 86 | −0.08 | 48 | −1.6 |
| May | 85 | +0.04 | 44 | −1.7 |
| Jun | 91 | −0.09 | 47 | −1.5 |
| Jul | 93 | +1.84 | 70 | +1.1 |
| Aug | 93 | +0.86 | 53 | 0.0 |
| Sep | 89 | +0.35 | 53 | −0.7 |
| Oct | 81 | +0.57 | 52 | −0.4 |
| Nov | 81 | +0.32 | 54 | −0.8 |
| Dec | 94 | **+2.46** | 77 | **+2.5** |

December and January are the strong months (the year-end / Chinese-New-Year restocking pattern that physical traders describe);
April–June are flat; the "autumn effect" (Baur 2013 found September/November strength) is *not* in this 2006-2026 sample. As a
rule it fails: long only in the six best months of all prior years (walk-forward from 2011) earns +0.33 %/yr over scaled
buy-and-hold, t 0.2, with a −32 % drawdown. Two of twelve months at |t| ≥ 2 is what chance gives. **CONTEXT-ONLY.**

### 4.5 OI-price quadrant (report week)

| State | n | 1 wk % (t) | 4 wk % (t) | 13 wk % (t) |
|---|---|---|---|---|
| Price ↑, OI ↑ — new longs | 380 | 0.16 (−0.6) | 0.87 (0.0) | 2.98 (+0.3) |
| Price ↑, OI ↓ — short covering | 210 | 0.38 (+0.8) | 1.04 (+0.4) | 2.77 (0.0) |
| Price ↓, OI ↑ — new shorts | 167 | 0.11 (−0.6) | 0.29 (−1.6) | **1.03 (−2.0)** |
| Price ↓, OI ↓ — long liquidation | 300 | 0.30 (+0.4) | 1.06 (+0.6) | 3.38 (+0.6) |

The only cell below the average is "new shorts" at 13 weeks (1.0 % vs 2.7 %) — weak support for *continuation* (fresh shorts
precede weakness), none for the contrarian reading, and one of twelve cells. **CONTEXT-ONLY** as a label of the week.

## 5. Results — description (does it explain what just happened?)

| Change over the report week | Spearman same week | R² | same sign | … vs the NEXT week |
|---|---|---|---|---|
| Managed-money net | **+0.65** | 31 % | 76 % | −0.02 |
| Managed-money gross long | +0.63 | 29 % | 76 % | −0.02 |
| Managed-money gross short | −0.40 | 12 % | 35 % | 0.00 |
| Commercial net (producer/merchant + swap) | **−0.66** | 34 % | 23 % | +0.01 |
| Producer/merchant net · Swap-dealer net | −0.54 · −0.58 | 27 · 22 % | 31 · 26 % | +0.01 · +0.03 |
| Other reportables net | −0.07 | 0.3 % | 45 % | +0.01 |
| Non-reportable (small) net | +0.30 | 11 % | 62 % | −0.03 |
| Open interest | +0.39 | 12 % | 64 % | −0.01 |
| GLD tonnes (%) | +0.32 | 16 % | 56 % | +0.03 |
| 10-y real yield (bp) | −0.40 | 14 % | 34 % | −0.01 |
| DXY (%) | −0.45 | 21 % | 33 % | +0.03 |
| USD/INR (%) | −0.22 | 3 % | 42 % | −0.02 |

Stability of the fund relation by sub-period: Spearman +0.66 (2006-10), +0.70 (2011-19), +0.60 (2020-26). Every 1,000
contracts of fund net buying coincides with +0.08 % on the week (t 21); the following week's correlation is zero in every case.
This is the whole story in one line: **positioning follows price inside the week and says nothing about the next one.** The
academic record agrees — in agricultural and energy futures the CFTC groups' positions track returns rather than forecast them
(Sanders, Boris & Manfredo 2004; Sanders, Irwin & Merrin 2009), and the only robust short-horizon effect in the literature, a
small reversal after speculators' position changes consistent with their being paid for liquidity (Kang, Rouwenhorst & Tang
2020), is the one weak 1-week result found here. *(Citations from memory; check before quoting them in the app.)*

### 5.1 What the funds did in up- and down-weeks (1,056 weeks)
Up-weeks (590): funds added gross longs in 57 % and covered shorts in 52 %; OI rose in 57 %. Down-weeks (466): funds cut longs
in 62 %, added shorts in 60 %; OI fell in 52 %. So a weekly label of the *dominant* fund action is right about three weeks in
four — useful as narration ("Tuesday-to-Tuesday the funds sold 10,100 longs"), not as a forecast.

### 5.2 The last 12 reports — who did what (full table in `RESULTS_TABLES.md`)

| Report (released) | Gold $ | Week % | Δ fund long | Δ fund short | Fund net | Δ commercial net | Δ other rep. | Δ OI | Label |
|---|---|---|---|---|---|---|---|---|---|
| 04 Aug (07 Aug) | 4,153 | +2.8 | +4,716 | −6,255 | 130,766 | −14,182 | +4,593 | −13,052 | short covering |
| 11 Aug (14 Aug) | 4,441 | +7.0 | +8,825 | +1,929 | 137,662 | −26,149 | +13,410 | +28,758 | new longs |
| 25 Aug (28 Aug) | 4,694 | +6.2 | +5,224 | +2,125 | 144,747 | −21,167 | +18,046 | +21,697 | new longs |
| 01 Sep (04 Sep) | 4,396 | −6.4 | −10,098 | −2,122 | 136,771 | +14,867 | −7,234 | −12,761 | long liquidation |
| 29 Sep (02 Oct) | 4,180 | −4.5 | −3,988 | +3,083 | 120,318 | +11,936 | −150 | −6,344 | long liquidation |
| 06 Oct (09 Oct) | 4,187 | +0.2 | −4,610 | +4,721 | 110,987 | +6,440 | +1,034 | −10,347 | funds sold into it |
| 13 Oct (16 Oct) | 4,177 | −0.2 | −2,354 | +1,544 | 107,089 | +1,996 | +1,442 | +236 | long liquidation |
| 20 Oct (23 Oct) | 4,143 | −0.8 | −3,777 | −894 | 104,206 | +6,949 | −5,131 | +5,934 | long liquidation |

### 5.3 The last rally and the decline since — decomposed

| | Price | Δ fund long | Δ fund short | Δ fund net | Δ commercial net (swap · prod/merch) | Δ other reportables | Δ small specs | Δ OI | Δ GLD |
|---|---|---|---|---|---|---|---|---|---|
| 12 Nov 2024 → 10 Mar 2026 | $2,606 → $5,242 (**+101 %**) | **−78,584** | −11,687 | **−66,897** | **+62,606** (+14,846 · +47,760) | −6,422 | +10,713 | **−122,025** | **+201.6 t** |
| 10 Mar 2026 → 20 Oct 2026 | −21 % | −4,107 | −9,914 | +5,807 | −32,606 | +30,926 | −11,677 | — |

Gold doubled while the funds *shrank* their net long by a quarter and COMEX open interest fell by a sixth; the commercials were
covering, GLD took in 200 t, and the rest of the buying (central banks, Asian physical, OTC, Chinese retail) is invisible to the
COT by construction. The −21 % correction since March was not fund selling either (fund net +5,800): commercials re-shorted and
"other reportables" bought. This is the clearest demonstration of why a fund-positioning *level* cannot time gold — the marginal
buyer of 2024-26 was not in the report — and, equally, why the report is the right place to look when the question is "was this
week's move the funds, the hedgers or someone else?" (it answers that for roughly three weeks in four).

### 5.4 Where the market stands (report of 20 Oct 2026, released 23 Oct)
Funds: 120,970 long / 16,764 short / **104,206 net** = 25.9 % of OI; COT index 26, z −0.5, 4-week change −23,183, 49th percentile
of all history (the record is 273,076 on 5 Jul 2016). Commercials −235,582 (swap dealers −220,799, producers −14,783); other
reportables +95,659; small traders +35,717; options-only fund net +4,479. OI 402,279 — 22nd percentile (record 796,883 on
14 Jan 2020), −2.5 % in four weeks. GLD 1,045.6 t (−0.8 % 4-wk), real yield 2.64 % (−19 bp 4-wk), DXY 101.8 (+0.8 %), USD/INR 94.7.
Reading: three weeks of fund long liquidation into a modest OI rise ("new shorts" quadrant) with the funds at the middle of their
history — nothing extreme, nothing the study would call a signal either way.

## 6. Caveats
- 2006-2026 is one secular bull market with one 2011-15 bear inside it; 20 years ≈ 80 independent 13-week windows.
- GC=F is the front month; GLD confirms no roll distortion at weekly frequency, but intraday entries are not modelled.
- MCX-specific effects (rupee, Indian duty, MCX session hours, the 09:00 open vs the Friday 15:30 ET release) are approximated by
  GC=F × USD/INR; an MCX trader can act at Monday 09:00 IST, earlier than the Monday COMEX close used here — the study's entry is
  conservative, not optimistic.
- Trader-group classification drifts (swap-dealer prop desks, "other reportables" growing from 0 to 95,000 net); the 2025
  shutdown catch-up reports were stale by up to 51 days and are kept (realistically, a trader could only act on them then).
- The release-date rule for ordinary holiday weeks is inferred from the CFTC's published 2026 schedule and applied to all years;
  the two-session-late robustness run guards against a one-day error.
- ~160 tests were run; a 2.5-t bar and sub-period sign agreement protect against false positives, and no signal came close.

## 7. What to publish and how to label it (one page)

| Item | Verdict | How to present | Where (avoid repeats) | Why |
|---|---|---|---|---|
| Weekly "who did what" strip: gross long/short and net by group (funds, swap dealers, producers, other reportables, small traders), Δ week, OI and Δ OI, the quadrant label, the fund-driver label (new longs / short covering / long liquidation / new shorts / "funds sold into it") | **PUBLISH-CORE** (descriptive) | Table + one sentence auto-written from the numbers ("Tue→Tue: funds cut 3,777 longs and 894 shorts; commercials covered 6,949; OI +5,934 — long liquidation"). Timestamp = CFTC release date, with "as of Tuesday" shown. Flag catch-up/stale releases. | MCXG gold desk (owner) and a reduced two-line version in World Markets; one component, one fetch | Same-week R² 31 %, stable across 20 years; the owner's exact question ("which position got closed, who are short/long") |
| 52-week COT index, z-score, % of OI, all-history percentile of fund net | **PUBLISH-CONTEXT** | Small gauge with the words "crowdedness, not a signal — no forecasting power 2006-2026 (G-STUDY)". Never colour it buy/sell. | Inside the same strip | Traders ask for it; honest label prevents misuse |
| Fund net vs price history chart (fig 1 style, stacked panels, never dual-axis) | **PUBLISH-CONTEXT** | 5-year window, weekly | Gold desk "positioning" tab | Lets the reader see the 2024-26 decoupling themselves |
| Rally decomposition ("since the last 2-year low / since the high: who bought, who sold, OI, GLD") | **PUBLISH-CONTEXT** | Two rows, recomputed weekly | Gold desk | The most instructive descriptive output of the study |
| GLD tonnes (daily, 1-wk and 4-wk change) | **PUBLISH-CONTEXT** | Number + sparkline + link; attribute "Source: SPDR Gold Shares"; **do not redistribute** (issuer's disclaimer) — personal-terminal display only | Gold desk; remove the MANUAL_CHECKS link duplicate once shown | Same-week R² 16 %; no forecasting power |
| Real yield (DFII10) and DXY, 4-week changes | **DO-NOT-DUPLICATE** | Already on the Gold Pre-Open page (DXY live, DFII10 a day late). Add nothing. | — | Same-week R² 14 % / 21 %; 4-week changes forecast nothing |
| OI-price quadrant (weekly, from COT OI) | **PUBLISH-CONTEXT** | The label only, inside the strip | strip | One weak cell; narration value |
| Month-of-year table | **PUBLISH-CONTEXT** (optional) | A 12-cell strip with mean and t, captioned "Dec/Jan strong historically; not a rule (walk-forward +0.3 %/yr)" | Gold desk footer | Honest answer to a question every gold trader asks |
| COT-based buy/sell signal, alert, "COT index ≥ 90 → sell" rule, long/flat timing | **DO-NOT-PUBLISH** | — | — | 0 of 69 rules beat scaled buy-and-hold; the lore points the wrong way |
| Options-only positioning (combined − futures) | **DO-NOT-PUBLISH** | — | — | No descriptive or predictive information; clutter |
| Legacy report (non-commercial/commercial) | **LINK-ONLY** | Link to the CFTC viewable report for the 1986 → history | — | Superseded by the disaggregated report |
| MCX gold daily history / MCX OI quadrant | **UNVERIFIED** | Needs Breeze historical (credentialed) or a browser-based MCX fetch; not studied | — | No free source answered |
| Kitco chart, CME OI pages, LBMA/WGC downloads | **LINK-ONLY** | Links in MANUAL_CHECKS as today | — | Bot-walled or registration/licence-gated; terms restrict embedding |

Ingest note for the engineer: one weekly job (Saturday 06:00 IST, after Friday 15:30 ET; Tuesday 06:00 IST in holiday weeks;
poll the Socrata API until `report_date` advances rather than trusting the calendar during shutdowns), four Socrata calls with
`cftc_contract_market_code=088691`, store in DuckDB `cot_gold` keyed by (report_date, dataset) with a `released_at` column taken
from the fetch time — that column is what makes any future backtest honest.
