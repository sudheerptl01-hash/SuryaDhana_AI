# Claims matrix: the two research documents vs SuryaDhana's measured evidence

Claims analyst, alpha_lab · 14 Oct 2026. Sources: `alpha_lab/inputs/oi_field_guide.md` (FG), `alpha_lab/inputs/feature_research_brief.md` (RB, sections 1–10 complete; its own IDs kept), and this repo's studies:
`reports/evidence_probability/` (EP; weekly frame, liquid universe L ≈ 1,945 stocks 2011–2026, "pre" = pre-2024, "24+" = 2024→, Newey-West t), `reports/held_overnight/` (HO), `reports/results_drift/` (RD, corrected), `reports/results_filter/`, `reports/fii_positioning/` (FII), `reports/ml_labels/` (ML), `reports/idea_lab/` (IL), `reports/value_area/` (VA), `reports/poc_conditional/` (POC), `reports/handbook_swing/` (HS), `docs/NSE_DATA_DICTIONARY.md` (DD).

Data reality for verdicts: `nse_fo_daily` = one row per symbol-day, futures close + OI **aggregated across expiries**, call/put OI totals, futures/options volume and ₹ value, 2019-10→ (312 stocks, 7 indices). `nse_participant_oi` daily. INDIAVIX daily **2009-09-22→**. No per-strike option prices stored (NSE archives have them), no per-expiry futures split (so no stored rollover), no tick/order-flow data. MWPL/FutEq files (`combineoi_DDMMYYYY.zip`) and daily ban lists (`fo_secban_DDMMYYYY.csv`) are dated archives on nsearchives — fetchable history (DD lines 78–104, 350–357).

Verdict scale: **TESTED-ROBUST** (same sign, |t|≥2 both periods here) · **TESTED-WEAK** (signal exists but fails the robust bar, or one period only) · **TESTED-NO-EDGE** · **TESTED-REJECTED** (opposite sign to the claim) · **UNTESTED-testable-now** · **UNTESTED-needs-data** (per-strike / per-expiry / MWPL / tick) · **UNTESTABLE** (intraday-only with our data).

## A. Every distinct claim, mapped

### A.1 Cash market — momentum, trend, reversal
| ID | Claim | Horizon | Verdict | Evidence | Note |
|---|---|---|---|---|---|
| MOM-01 | 12-1 momentum + | 1–12m | **TESTED-ROBUST** (pre-2024), weak since | phase_b_extended: adopted, beats NIFTY over 16y after costs; EP mom_top10 h20 +1.32% (t 5.7) / +0.55 (1.6); mom_bot10 h60 −2.16 (−3.6) / −2.15 (−3.7) Robust | The one adopted edge. 2024+ long side weak; short side (avoid) still robust |
| MOM-02 | 5/21-day reversal −, grade A | 5–21d | **TESTED-WEAK** | EP loser_5d h5 +0.04 (0.6) / +0.17 (1.9); quiet_loser_5d h5 +0.14 (1.5) / +0.30 (3.2) Holds-weaker; loser_20d h20 No effect, h60 pre −1.49 (−3.2) | Only the low-volume variant works, only at 5 sessions, only clearly since 2024. RB's grade A overstates India large-caps |
| MOM-03 | 52-week-high proximity + | 20–120d | **TESTED-WEAK** | EP near_52w_high binary h20 +0.40 (1.9) / +0.19 (0.5) No effect; as continuous signal, label-study IC 0.052 (t 4.1) h20, 0.087 (4.7) h60 | Binary flag adds nothing; the continuous distance is one of our strongest ranking signals |
| MOM-06 | Trend template (Minervini) as entry filter | swing | **TESTED-REJECTED as a system**; one leg robust as avoid | HS: full handbook −17.8% CAGR after costs vs Nifty500 +12.4%; EP below_200dma Robust −0.69 (−5.1) / −0.60 (−3.2) h20 | Keep "below 200-DMA = avoid"; drop the rest as entries |
| MOM-10 | RSI oversold bounce | 2–10d | **TESTED-ROBUST (leaders, 5d only)** | EP rsi2_leader h5 +0.49% (2.9) / +0.58 (2.5), P(beat) 53.1% vs 46.1%; h20 No effect | The only robust *buy* timing flag we have; costs still exceed the edge at delivery rates |
| RB §4.2 MOM-04/05/08/09 | residual/relative/quality/industry momentum | 1–6m | UNTESTED-testable-now | — | Variants of a proven family; test behind MOM-01, expect correlated |

### A.2 Volatility, volume, liquidity
| ID | Claim | Horizon | Verdict | Evidence | Note |
|---|---|---|---|---|---|
| VOL-01/02 | High realised vol − | 20–60d | **TESTED-WEAK (strong as risk flag)** | EP high_vol h20 −0.79 (−2.6) / −0.49 (−1.4); P(worst fifth) 32% vs 20% | Best bottom-quintile predictor; mean effect not robust |
| VOL-03 | High beta − | 20–60d | TESTED-NO-EDGE (mean); risk flag | EP beta No effect, bottom 27% | |
| VOL-04 | Lottery MAX − | 5–20d | TESTED-NO-EDGE | IL low-MAX long −0.22%/wk (−2.7) wrong sign; EP lottery_max No effect, bottom 27.8% | Risk marker only |
| VOL-06 | Overnight-return clientele + | 20d | **TESTED-REJECTED** | IL overnight factor −0.23%/wk (−2.2) and −0.21 (−2.2) both periods; EP overnight_mom No effect | Sign is negative in India if anything |
| LIQ-01/02 | Delivery % / value surge = accumulation | 5–20d | **TESTED-NO-EDGE** | HO H1 5d excess −0.04 / −0.28 vs control; EP deliv_surge_up h20 No effect, h5/h60 Unstable | RB itself grades C·IN "never rigorously tested" — now it is: nothing |
| LIQ-03 | Abnormal volume × up-day + | 5–20d | **TESTED-REJECTED** | IL abnormal-volume long −0.12 / −0.35%/wk (t −4.5 holdout); EP abnormal_volume h5 24+ −0.14 (−2.3) | High-volume names *lag* here — opposite of Gervais et al. |
| LIQ-05 | Close above day VWAP + | 1–5d | TESTED-WEAK/No effect | ML close_loc feature: never significant; POC: no VA/POC long entry beats random | `avg_price` exists in bhavcopy; as a flag it added nothing |
| LIQ-06 | Amihud illiquidity premium | 60d+ | TESTED-NO-EDGE at our horizons | EP illiquid h20 No effect; bottom 26.7% | Use as capacity filter, not signal |
| LIQ-08 + VOL-05 | Volume dry-up / contraction before breakout | swing | TESTED-WEAK | HS B_vcp: 8 trades, −0.43R net | Too rare to judge; breakout family itself failed |
| FG RVOL | RVOL ≥1.5 confirms breakouts | 1–5d | **TESTED-NO-EDGE** | EP breakout_52w (1.5× vol, strong close) h20 +0.56 (2.2) / +0.15 (0.4) No effect; HS A_breakout net −0.20R | Volume-confirmed 52w breakouts drift *up* slightly, not − as FG warns, but nothing tradable after costs |

### A.3 Price action (FG volume-profile chapters, VA family)
| ID | Claim | Horizon | Verdict | Evidence | Note |
|---|---|---|---|---|---|
| FG profile | POC magnet / value-area trading | 5–10d | **TESTED-NO-EDGE (veto only)** | VA: upside breaks fail to POC +2.3pp over chance (z 11), long entries lag −0.22 (−5.7); POC: every VA strategy ≤ random entry | EP va_up_break h5 Robust −0.15 (−3.2) / −0.20 (−2.4) — a real avoid flag |
| FG 80% rule, profile shapes | intraday rotation rules | intraday | UNTESTABLE (EOD data) | — | |
| FG anchored VWAP holds | pullback support | days | UNTESTABLE as stated; EOD proxy no-edge | POC: MA-between-price-and-POC adds nothing beyond distance | |

### A.4 Events & corporate
| ID | Claim | Horizon | Verdict | Evidence | Note |
|---|---|---|---|---|---|
| FUN-01/02 | Earnings surprise / announcement-return drift + | 20–60d | **TESTED-WEAK (good news), ROBUST (bad news, as avoid)** | RD: strong-down 60d −3.69 (−2.8) / −2.04 (−3.0) PASS; strong-up +2.72 (1.4) / +3.40 (3.4) FAIL-pre; EP fresh bad results h5 −0.53 (−2.0) / −0.88 (−4.4), P(beat) 39% | Matches RB's "mixed" Indian PEAD; the tradable half is the avoid side |
| FUN-07 | Reported growth → drift | 60d | **TESTED-NO-EDGE** | earnings_growth_drift broad run: +1.0% (weekly t −2.3) H1 FAIL | First run's + was selection bias |
| EVT-06 | Splits/bonuses drift up after announcement | 20d | **TESTED-REJECTED (India)** | IL post-split 20d −4.1% / −4.3%; EP post_split h5 Robust −0.80 (−4.2) / −0.95 (−2.4), P(beat) 40.2% | Strong avoid flag — opposite of the US evidence RB cites |
| EVT-01 | Index add/delete flows | 10–240d | UNTESTED-needs-data | No historical membership-change feed ingested | Fetchable (index-provider notices) |
| EVT-03 | F&O inclusion +/exclusion − | 20–60d | **UNTESTED-testable-now** | First/last appearance per symbol in nse_fo_daily 2019-10→ gives the event dates | ISB: −4.07% around exclusion. Cheap test |
| EVT-04/05/07/08 | lock-ins, QIP/OFS, ratings, governance | event | UNTESTED-needs-data | Not ingested | Ratings/pledge feeds exist (DD §pledges) |
| OWN-03 | Insider open-market buys + | 20–60d | TESTED-WEAK (promising, unproven) | HO H4b first-buy-in-90d: +2.15 (3.0) disc / +3.06 (2.3) hold 20d but coverage-biased; EP insider_fresh_buy h20 +1.12 (1.7) / +0.77 (0.9) | Forward test running since Oct-2026 |
| OWN-05 | Bulk deals: smart vs dumb money | 20d | TESTED-WEAK, faded | HO H3 non-inst buy 20d −2.22/−1.23 (t_nw −2.5/−2.0); EP 24+ +0.21 (0.6) No effect; inst buy +, never significant | The one Desk candidate filter; effect gone since 2024 in liquid names |
| OWN-01 | FPI quarterly holding change + | 20–60d | TESTED-NO-EDGE | HO H6: accumulation ≈ other filers, same weeks | Filing-season timing explains it |
| OWN-06/07 | Short-sale disclosures / SLB − | 5–20d | UNTESTED-testable-now (short history) | Weekly short-selling ingested (deals_monitor.short_selling) from 2024ish | Series too short for a verdict; log and wait |
| OWN-08 | MTF crowding − | 20d | **TESTED-NO-EDGE** | HO H5 near-high MTF surge ≈ control; EP mtf_surge_near_high No effect | |

### A.5 Futures-derived (FG quadrant chapters; RB §6)
| ID | Claim | Horizon | Verdict | Evidence | Note |
|---|---|---|---|---|---|
| FUT-01 / FG quadrants | Long build-up = "most reliable bullish state"; continuation 5–20d | 5–20d | **TESTED-NO-EDGE / Unstable** | HO H2: long build-up 5d −0.74 (t_nw −3.0) disc, +0.03 hold; EP fo_long_buildup h20 −0.94 (−2.2) / +0.30 (0.7) Unstable, h5 −0.57 (−3.3) pre; fo_short_buildup No effect everywhere | The most-used Indian heuristic; measured, it leans *against* the folklore pre-2024 and is noise since. RB's own literature row agrees ("Weak… never tested formally") |
| FUT-02 | OI intensity/crowding − | 20d | UNTESTED-testable-now (partially tested) | ML oi_days univariate IC n.s. | Float-scaled version untested |
| FUT-03 | MWPL utilisation / ban effects | days | UNTESTED-needs-data (MWPL history fetchable) | RB cites Panda et al. 2025: 1,246 bans 2018–22, insignificant before/during/after | Build the combineoi archive only as a *tradability* filter |
| FUT-04/05 | Basis / excess carry; discount = bearish info | 5–20d | **UNTESTED-testable-now** ← top candidate | fut_close + spot + T-bill proxy, 2019-10→; NIFTY basis sample checks out (+26 pts on 14 Oct) | Short-sale-constraint channel is the best-motivated untested F&O claim |
| FUT-06 | Rollover % and cost | monthly | UNTESTED-needs-data (per-expiry split not stored) | — | Needs raw per-expiry F&O bhavcopy backfill |
| FUT-07/08 | Churn; derivatives share of activity | 5–20d | UNTESTED-testable-now | fut_value_lakh, opt_value_lakh vs cash turnover all stored | Johnson–So analogue |
| FG basis table | Premium↑ = leveraged longs; discount = hedging/shorts | — | folds into FUT-04 | | |
| FG rollover table | High roll + rising price = bullish continuation | monthly | UNTESTED-needs-data | | Grade C in RB too |

### A.6 Options-derived (RB §7; FG chain/PCR/max-pain/gamma chapters)
| ID | Claim | Horizon | Verdict | Evidence | Note |
|---|---|---|---|---|---|
| OPT-02/03/04/06 | IV changes, call–put IV spread, put skew, RV−IV | 5–21d | **UNTESTED-needs-per-strike-data** | US: ~1%/mo (An et al.), 50bp/wk (Cremers-Weinbaum), 10.9%/yr (Xing et al.) | RB's headline opportunity; needs NSE per-strike archives + Black-76 IV build (RB §12 recipe) |
| OPT-08 | Option-to-stock volume − | 5d | **UNTESTED-testable-now (proxy)** | opt_value_lakh / cash turnover stored 2019-10→ | ₹-value proxy of Johnson–So O/S; delta-weighting impossible without strikes |
| OPT-09 | Stock PCR | 5–20d | TESTED-WEAK | EP pcr_high h20 +0.10 (0.6) / +0.34 (2.3) No effect; h60 24+ +0.72 (1.9); ML univariate +0.024 (2.4) | Promising lead, one period only; keep on watch |
| OPT-10 | OI walls = support/resistance | intraweek | UNTESTED-needs-per-strike-data | FG: crowded walls break *because* crowded | Expiry-week only per both docs |
| OPT-11 / FG max pain | Price gravitates to max pain | expiry | **TESTED-NO-EDGE (literature), don't build** | RB: "max pain shows no effect" (Singh & Sen 2010); FG: "no rigorous public test… never trade toward it early" | Both docs already reject it |
| OPT-12 | Implied earnings move = barrier width | event | UNTESTED-needs-per-strike-data (history) | Live endpoint exists; no stored history | Useful as *width*, not direction |
| OPT-13 | Unusual OTM activity = event detector | event | UNTESTED-needs-per-strike-data | | |
| FG Greeks/gamma | Short-gamma hedging amplifies; pinning vs acceleration | intraday/expiry | UNTESTED-needs-data + assumption-heavy | FG itself: India publishes no dealer positioning; "treat its output as a model, not data" | POS-09 same verdict |
| FG vanna/charm | expiry drift mechanics | expiry | UNTESTABLE (assumptions) | FG: "speculative" | |

### A.7 Positioning & regime (RB §8; FG participant chapter)
| ID | Claim | Horizon | Verdict | Evidence | Note |
|---|---|---|---|---|---|
| POS-01 / FG FII long ratio | Extremes are contrarian (<20–30% squeeze-prone, >75–80% crowded) | 5–20d | **TESTED-NO-EDGE** | FII study: flow terciles −0.53% 20d (t −1.34); extreme-short decile +0.05% (t 0.07). FG itself: "rough guides, not tested thresholds" | Panel is context, not timing |
| POS-02/03 | FII derivative/cash flows predict | 5–20d | TESTED-NO-EDGE (derivatives); cash untested as conditioning | FII study FAIL both hypotheses | |
| POS-04 | India VIX level/percentile → regime, risk scaling | market | UNTESTED-testable-now (direction); fine as scaler | VIX 2009→ in store; HS used VIX percentile inside regime score (system failed for other reasons) | Direction evidence weak everywhere; use for sizing/barriers |
| POS-05 | Variance risk premium + | 20–60d | **UNTESTED-testable-now** ← candidate | (VIX/100)² − realised var, 2009→ | Strong global prior (Bollerslev et al.) |
| POS-06 | Nifty OI-PCR Granger-causes returns 6–12d | 6–12d | UNTESTED-testable-now | Index call/put OI stored 2019-10→; Jena et al. direction unreported | Cheap replication |
| POS-07 | Build-up breadth | 5–20d | UNTESTED-testable-now | Derivable from stored quadrants | Prior weak (quadrant family dead at stock level) |
| POS-08/12 | Leverage/froth extremes − | 20d+ | UNTESTED-testable-now | fut/opt value vs cash turnover stored | |
| POS-10 | Expiry-cycle effects (pre-expiry dip, expiry vol) | 1–2d | UNTESTED-testable-now (index, daily) | Vipul 2005; Agarwalla-Pandey 2012 | Calendar control, not alpha |
| POS-11 | Index basis | 20d | UNTESTED-testable-now | NIFTY fut_close vs NIFTY50 stored | |
| SEC-01/02 | Sector aggregation & peer lead-lag spillovers | 5–20d | UNTESTED-testable-now | Industry map + fo features stored | Only route to 1,600 non-F&O names; test after a stock-level F&O signal survives |

### A.8 Order flow & microstructure (FG II)
| ID | Claim | Verdict | Note |
|---|---|---|---|
| FG CVD, divergence, absorption, exhaustion, footprint imbalances | UNTESTED-needs-tick-data | Chordia-Subrahmanyam is daily-imbalance US evidence; nothing here is testable on bhavcopy. Breeze L1 websocket could *record* forward data (memory: intraday-data-sources) |
| FG depth/OFI/spoofing/VPIN | UNTESTED-needs-tick-data; FG itself: VPIN "disputed… a concept" | Not a backtest candidate |
| FG intraday OI phases | UNTESTABLE historically (no intraday OI archive) | Live-only reading |

## B. Top 5 untested claims worth testing first
Ranked by prior evidence × data-in-hand × capacity at our size. All pre-registrable this week; none requires new data purchases.

1. **FUT-04 excess carry (stock-futures basis vs T-bill)** — RB grade B, best-motivated channel (shorting constraints push bearish views into futures).
   Spec: per F&O stock, basis% = fut_close/spot−1 annualised by days-to-near_expiry (near_expiry stored), minus 91-day T-bill (constant 6.5% fallback); strip ex-dividend windows via `dividends`; weekly cross-sectional quintiles within F&O names; outcomes = 5/20-session next-open excess (EP frame); NW t, split 2019-10→2023 / 2024+ and at the Oct-2025 regime break. Both signs pre-registered (leverage-demand continuation vs crowding reversal).
2. **OPT-08 option-to-stock ₹-volume (O/S proxy)** — Johnson–So 0.34%/wk US, short-sale channel says stronger here.
   Spec: opt_value_lakh (5-day sum) / cash turnover (5-day sum), weekly quintiles within F&O universe; same outcomes/stats as #1; expect low-O/S > high-O/S.
3. **POS-05 variance risk premium (index regime)** — (VIX/100)² − 21-day realised NIFTY variance, 2009→.
   Spec: monthly terciles of VRP → next 20/60-session NIFTY and equal-weight-universe returns; NW t; then as an exposure gate on the momentum book (does high-VRP improve the Desk's risk-on months?). Market-timing claim — gate it harder.
4. **POS-06 index OI-PCR** — stored index call/put OI 2019-10→.
   Spec: NIFTY put_oi/call_oi percentile vs own 252 sessions; test both signs at 5/10/20 sessions on NIFTY fwd returns; also its weekly change. Replicates Jena et al. at swing horizon.
5. **EVT-03 F&O exclusion (and entry)** — first/last date per symbol in nse_fo_daily.
   Spec: event study ±60 sessions vs liquid-universe benchmark, exits ~ a few dozen events 2019→ (small n — report CIs, no gate); prior −4.07% around exclusion (ISB).
Watchlist behind these: FUT-08 derivatives-share, POS-12 froth, stock-PCR h60 (already a weak lead), SEC-01 spillover once any stock-level F&O signal survives.

## C. Claims the documents themselves flag as weak — never build on these
- FG, opening rule: "**No single stream predicts direction on its own.**"
- FG PCR: "treat the PCR as context… **neither is a trade trigger on its own**"; "Indian evidence is thin… no robust recent Indian study either way."
- FG max pain: "no rigorous public test of max pain as a predictor for the Nifty"; "**Never trade toward it early in the week.**" RB: "max pain shows no effect… belongs on the test list rather than in the core" → and its catalogue row says "none expected".
- FG FII long-ratio thresholds: "**rough guides, not tested thresholds**."
- FG IV×price×OI combinations: "practitioner heuristics, **not tested rules**."
- FG Indian GEX: "rests on an assumption about who is short. **Treat its output as a model, not data**"; vanna/charm "speculative".
- FG VPIN: "later research has disputed how well it forecasts… **a concept rather than a ready-made signal**"; depth: "orders are cancelled constantly… **trust trades over quotes**" (spoofing).
- RB on raw OI: "**rising OI alone says only that leveraged positions are growing, not which side holds them**… Raw OI and the build-up quadrants have no rigorous Indian test."
- RB on bans: "1,246 bans in 2018–22 showed insignificant returns before, during and after" (Panda et al. 2025).
- RB on futures lead-lag: "Intraday only; **no value for end-of-day swing features**."
- Both docs on who loses: SEBI FY26 — 87.7% of individual F&O traders lost money (₹72,243 cr); FY25 ≈ 91%. Context for any retail-positioning contrarian idea, and for humility.

## D. Contradictions between the documents and our measurements
Four places where the imported priors and our own data disagree, all in the direction of *the claim being weaker or inverted in India*. (1) **Splits/bonuses**: RB expects "+" after announcement (Ikenberry et al., US); measured here the post-ex-date window is robustly negative (IL 20d −4.1%/−4.3%; EP post_split h5 −0.80 (−4.2) / −0.95 (−2.4)) — in India this is an avoid flag, not a buy. (2) **Abnormal volume**: RB "+" (Gervais et al.); measured, high-volume names lag (IL −0.35%/wk, t −4.5 holdout) — sign flipped. (3) **The build-up quadrants**: FG calls long build-up "the most reliable bullish state"; measured, 5-day continuation after long build-up was *negative* pre-2024 (HO −0.74%, t_nw −3.0; EP h5 −0.57, t −3.3) and noise after — the folklore fails exactly where it is most quoted. (4) **FII-ratio extremes**: FG's squeeze narrative vs our null (extreme shorts +0.05%, t 0.07). Softer tension: RB grades 5-day reversal "A" globally, while here only the low-volume variant clears any bar and only at 5 sessions; and 52-week-high proximity earns its keep only as a continuous signal, not as the binary flag practitioners quote. None of these contradictions is a data error on our side — each repo number is survivorship-free, point-in-time and cost-aware, which is precisely where folklore usually dies.

## Executive summary (10 lines)
1. Of ~70 distinct claims across both documents, 24 are already tested in this repo; only momentum (pre-2024), below-200-DMA, near-52w-low, bad-results drift, post-split weakness, VA-upside-break (5d) and RSI(2)-in-leaders (5d) survive as robust — mostly **avoid** flags.
2. The field guide is sound pedagogy and candid about evidence; nothing in its OI/PCR/max-pain folklore survives our frame where testable, and the guide itself warns of exactly that.
3. The research brief's cash-market P1 list is ~70% already tested here; its genuinely new, testable-now items are futures **excess carry**, **O/S ₹-proxy**, **VRP**, **index OI-PCR**, **F&O entry/exit events** (section B specs).
4. The brief's flagship opportunity (IV-based features OPT-02/03/04/06) needs per-strike NSE archives we don't hold; it stays on the shelf until that backfill is approved.
5. Two imported priors are sign-flipped in India (splits +→−, abnormal volume +→−); build nothing on US signs without a local test.
6. Quadrants, delivery surges, MTF crowding, FII positioning, max pain: measured no-edge — keep them as display/context only.
7. Order-flow chapters (CVD, footprint, depth, VPIN) are untestable without tick data; optionally start *recording* Breeze L1 now for future research.
8. MWPL/ban history is fetchable (combineoi archives) but justified only as a tradability filter, per the null directional literature.
9. Everything testable-now in section B fits the existing EP weekly frame and costs; each is a ≤1-day pre-registered study.
10. Net: the documents refine the avoid library and hand us five cheap tests; they do not overturn the core finding that durable edges here are momentum + refusal, not derivatives folklore.
