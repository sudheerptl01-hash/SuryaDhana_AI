# SuryaDhana: from analysis tool to money-making process

*Written 2026-09-27 as a senior-PM review. This is the plan before any build.*

## 0. One-paragraph verdict
SuryaDhana has good plumbing: clean data, honest backtests, services, scheduler, UI. What it lacks is the one thing that makes money: **a validated edge, sized and costed for your capital, turned into a daily decision that you actually execute and then measure.** Every study so far searched **5-day, high-turnover** ideas and assumed **0.15% cost**. Retail costs in India are about **0.9–2.4% per round trip**, which is exactly where retail loses. The fix is not more features. It is a different search space (lower turnover, documented premia, India-specific data), a true cost model, and a **decision layer**: what to do today, how much, why, and how we'll know if it stopped working.

## 1. Why nothing converts to money today
| # | Gap | Evidence in this repo | Consequence |
|---|---|---|---|
| 1 | **No validated edge** | XGBoost OOS AUC 0.48; SOTA sweeps: 0/30 cells; nested holdout rejected; value-area and circuit ideas rejected | Signals are noise, so any automation just pays costs |
| 2 | **Wrong cost model** | All backtests use 0.15% total. ICICI Direct delivery: brokerage ~0.27–0.29%/side + STT 0.1%/side + stamp + GST + ₹20 DP per sale | Real round trip ≈ **0.86% + ₹23.6**; see table below |
| 3 | **Horizon × turnover mismatch** | 5-day holds, weekly rebalance | ~50 round trips a year × 0.86% ≈ **43%/yr cost drag**. No known equity edge survives that |
| 4 | **Capital scale ignored** | ₹10k × 15% = ₹1,500 tickets | The fixed ₹23.6 DP charge alone is **1.6%** per sale |
| 5 | **No decision layer** | Screens, charts, scores, but no "action + size + reason + invalidation", no execution journal, no live-vs-backtest tracking, no per-strategy kill switch | You can't act, and you can't learn from what you did |
| 6 | **Data biases and gaps** | Universe = today's listed names (survivorship); fundamentals are one 2026-05 snapshot; no earnings dates, delivery %, bulk/block deals or insider trades | Momentum/value backtests are overstated; India-specific edges are untestable |

**Round-trip cost by position size (approximate; confirm with one of your contract notes):**
| Position | ICICI Neo (0.27% brokerage) | Zero-brokerage broker |
|---|---|---|
| ₹1,500 | **2.43%** | 1.28% |
| ₹10,000 | 1.10% | 0.38% |
| ₹1,00,000 | 0.88% | 0.24% |
| ₹10,00,000 | 0.86% | 0.22% |

## 2. Where money actually comes from (the senior-PM decomposition)
**Net profit = capital × (market return + factor premia + alpha − costs − taxes − behaviour mistakes)**

| Component | How reliable | Cost to harvest | What the tool should do |
|---|---|---|---|
| Market return (beta) | High over years | ~0.05%/yr via an index ETF | Hold it cheaply; don't pay trading costs to own it |
| Factor premia (momentum, low-vol, quality) | Documented in India; NSE runs indices on them | Low, *if rebalanced monthly or semi-annually with buffers* | Harvest systematically, with a regime overlay to cut drawdowns |
| Alpha (true edge) | Rare; must be proven | High (research + turnover) | Test ruthlessly, give it a small risk budget, auto-demote when it decays |
| Costs | Certain | — | Model them exactly; refuse any trade where expected edge < 2 × cost |
| Taxes | Certain | — | STCG 20% vs LTCG 12.5% (first ₹1.25L exempt): make rebalancing tax-aware |
| Behaviour | The biggest retail loss | — | One decision brief per day or week, pre-committed rules, a journal |

SEBI found that **91% of individual F&O traders lost money in FY25** (net losses ₹1.06 lakh crore). A tool that stands out from retail tooling is one that **refuses trades without proven edge**, not one with more indicators.

## 3. Target product: "SuryaDhana Allocator + Decision Desk"
Three sleeves, one decision layer.

**Sleeve A: Core (beta + regime).** Index/factor ETFs, rebalanced monthly. A risk-off overlay (NIFTY vs its 200-day average, market breadth) moves money to a liquid/gilt ETF. Purpose: capture the market while cutting the worst drawdowns. Works at any capital, including ₹10k, because it needs few trades and one DP charge per sale.

**Sleeve B: Factor satellite.** A concentrated momentum portfolio (6- and 12-month, volatility-adjusted, the same logic as the NSE Momentum 30 index) plus a low-vol blend. Monthly or semi-annual rebalance, with buffer bands so a name is sold only when it leaves the top N+k (this cuts turnover). **Only switched on when capital per name keeps round-trip cost under ~0.5%**, i.e. roughly ≥ ₹1–2L total. Below that, the tool recommends the momentum ETF instead.

**Sleeve C: Research / alpha.** India-specific event signals (§4, R4–R5). Each has a small risk budget and goes through the gates in §5.

**Decision Desk (the missing piece that turns analysis into money):**
1. **Daily/weekly Decision Brief.** Actions only: BUY / SELL / HOLD / NO-TRADE, with size in ₹ and shares, expected edge vs cost, the evidence behind it (walk-forward stats), and an *invalidation* rule ("exit if…").
2. **Pre-trade checks.** Edge/cost ratio, liquidity (≤1% of daily volume), NSE ASM/GSM surveillance list, T2T series, project risk rules (5 positions, 15%/stock, 40%/sector, −2% daily halt, −20% DD stop), tax impact.
3. **One-click order ticket** via Breeze, always with human confirmation; LIVE only when explicitly enabled.
4. **Journal + attribution.** Every fill is logged with its reason. P&L is split into beta / factor / alpha / cost / tax / slippage.
5. **Strategy scorecard + kill switch.** Live vs backtest expectation with a tracking band. A strategy is auto-demoted to paper when it breaches the band (for example, 3 months below the 5th-percentile expectation).
6. **Capital-viability view.** "At ₹X, these strategies are viable, this one isn't (cost drag Y%)."

## 4. Research program (pre-registered, same honest harness)
**R0: Foundations (must come first; every later result depends on them)**
- **Cost model:** broker-configurable (percentage + fixed DP + GST + STT + stamp), calibrated from your real contract notes.
- **Survivorship-free universe:** NSE `sec_bhavdata_full` daily archives (every traded security each day, delisted ones included, **plus delivery quantity / delivery %**). One ingestion fixes survivorship bias and unlocks delivery data. Split adjustment uses the existing splits table plus NSE corporate-action files.
- **Tax model:** STCG/LTCG, holding-period tracking per lot.

**R1: Medium-horizon momentum.** NSE Momentum-30 style score; top 10/20/30; monthly vs semi-annual; with and without buffer bands; net of R0 costs at ₹10k / ₹1L / ₹10L / ₹1Cr; compared against Nifty 50 and against simply holding the momentum ETF. *Pre-registered pass:* beats Nifty after costs and tax in both discovery and holdout, Deflated Sharpe > 0.95, and max drawdown no worse than Nifty's plus 10 percentage points.

**R2: Regime overlay** on the core (200-day average, breadth, VIX): does it cut max drawdown by at least a third without costing more than 1–2%/yr of CAGR?

**R3: Low-volatility and price-based quality proxies**, as a diversifier to momentum (a blend often gives a higher Sharpe than either alone).

**R4: India-specific information signals** (need the R0 data first), tested at 20–60 day horizons, not 5 days:
- Delivery % surges (accumulation vs speculation).
- Bulk/block deals by named institutions (NSE publishes daily).
- Insider/promoter buying (SEBI PIT disclosures) and pledge changes.
- Index inclusion/exclusion events (the documented index effect).
- Results-date drift (PEAD). Evidence in India is mixed: one 2002–17 study finds a 64-day drift, one 2014–18 study finds none. That is exactly why it gets tested, not assumed.

**R5: LLM news scanner scoring.** Log every pick from `new_scnner/` automatically and score its 5/20/60-day excess return. Within about 3 months the feature becomes a measured signal, which is either kept or dropped.

## 5. Promotion gates (how an idea earns money)
`Research → Holdout pass → Paper (≥3 months, inside tracking band) → Small live (≤10% of capital) → Scaled`
Demotion is automatic when live results break the band. Nothing reaches the Decision Brief without passing the gates, and the brief shows which stage each strategy is in.

## 6. Roadmap (each phase ends with something you can decide on)
| Phase | Build | You get |
|---|---|---|
| A (1–2 wk) | R0: cost model + contract-note calibration, capital-viability calculator, bhavcopy ingestion (survivorship-free + delivery %) | The true cost of every trade you'd take, and which strategy types are viable at your capital |
| B (1–2 wk) | R1 + R2 + R3 studies on the corrected data | A go/no-go on a momentum satellite and on the regime overlay, with numbers |
| C (2 wk) | Decision Desk v1 for whatever passes B (brief, pre-trade checks, order ticket with confirmation, journal, scorecard); paper mode | A weekly/monthly action list you can follow in 15 minutes |
| D (2–3 wk) | R4 data feeds (bulk/block deals, PIT, pledges, index events, results calendar) + R5 scoring | Evidence on India-specific edges; the LLM scanner becomes measurable |
| E | Small live on sleeves that passed paper; tax-lot optimization | Real P&L, attributed |

## 6b. Status (2026-09-27)
| Phase | Status |
|---|---|
| A: costs, NSE bhavcopy 2010→ (survivorship-free), tax, capital viability | ✅ done (`shared/trading_costs.py`, `shared/nse_panel.py`, `reports/costs/`, `reports/data_quality/`) |
| B: monthly momentum / low-vol / crash filter, 24 variants, 2011–2026 incl. an untouched decade | ✅ done: momentum beats NIFTY after costs+tax in every period; ~89% confidence; −15% only at ~45% equity (`reports/phase_b*/`) |
| C: Decision Desk (paper) | ✅ v1 live: `shared/decision_desk.py`, `/api/desk/*`, UI tab "Decision Desk", master-controller `desk_daily` 19:30 IST. Owner chose Option B (66% equity) |
| D: India-specific signals, LLM scanner scoring | ⏳ next |
| E: small live | after ≥ 3 months of paper inside the tracking band |

## 7. Decisions needed from you before Phase A
1. **Broker/plan for execution.** Confirm your ICICI plan from one contract note. Would you execute on a lower-cost broker if the tool shows it saves ~0.6% per round trip?
2. **Capital path.** Stay at ₹10k, or scale to ₹1L–₹10L+? This determines whether Sleeve B is stocks or an ETF.
3. **Holding horizon.** Are monthly or semi-annual rebalances acceptable, instead of 5-day trades?
4. **Risk tolerance.** Maximum drawdown you'd sit through (e.g. −15% / −25%).
5. **F&O.** Out of scope (recommended, given SEBI's data), or a later hedging-only use?

## Sources
- [SEBI press release: 93% of individual F&O traders lost money, FY22–FY24](https://www.sebi.gov.in/media-and-notifications/press-releases/sep-2024/updated-sebi-study-reveals-93-of-individual-traders-incurred-losses-in-equity-fando-between-fy22-and-fy24-aggregate-losses-exceed-1-8-lakh-crores-over-three-years_86906.html)
- [Business Standard: net losses of individual F&O traders widened in FY25](https://www.business-standard.com/markets/news/net-losses-of-traders-in-fo-widens-in-fy25-sebi-study-125070701221_1.html)
- [ICICI Direct brokerage calculator](https://www.icicidirect.com/calculators/brokerage-calculator) · [ICICI Direct charges summary (knowyourbrokerage)](https://knowyourbrokerage.in/icici-direct/charges) · [Chittorgarh: ICICIdirect brokerage](https://www.chittorgarh.com/brokerage_charges/icicidirect/1/)
- [NSE Indices: Nifty200 Momentum 30 whitepaper](https://www.niftyindices.com/docs/default-source/indices/nifty200-momentum-30-index/nifty200_momentum_30_index_whitepaper_sep_20.pdf?sfvrsn=3eb99734_4) · [Freefincal: caveats on momentum index returns](https://freefincal.com/uti-nifty200-momentum-30-index-fund/)
- [NSE bhavcopy explained (delivery data)](https://volumelens.com/learn/nse-bhavcopy-explained/) · [NSE security-wise archives](https://www.nseindia.com/report-detail/eq_security)
- [PEAD in India, 2002–2017 (SCIRP)](https://www.scirp.org/journal/paperinformation?paperid=88060) · [PEAD and value-glamour in NSE firms](https://journals.vut.cz/index.php/trends/article/view/541)
