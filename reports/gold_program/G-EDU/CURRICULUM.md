# Gold, zero to professional — the SuryaDhana LEARN reference (G-EDU)

Written 26 Oct 2026, 05:50 IST, for the GOLD program. Terminal-grade reference text: short, exact, no fluff. Every
section has three voices:

- **[B]** the beginner line: what it is in plain words, defined the first time it appears.
- **[P]** the pro line: the exact definition, the formula, the pitfall.
- **[APP]** where it lives on the GOLD page (the panel id of PLAN §a, e.g. `ph.ladder`) or which page keeps it (MCXG, WEI,
  BRF, CMDT). Updated 5 Nov 2026 after the page shipped; "LEARN only" means there is deliberately no panel.

Numbers in worked examples are the live values the app, the CFTC, FRED and the LBMA served at the time of writing
(each one is dated). They are illustrations of how to read, not quotes. Where a claim is backed by a study it is cited;
where it is desk lore it says **context only**. Our own rule from `reports/fii_positioning/FINDINGS.md` applies to every
positioning number in this document: *who is positioned where* is context, not a timing tool, until a G-STUDY proves it.

---

## 0. The health check: five numbers before anything else

The owner asked for a "health check for gold". A gold desk reads these five, in this order, before any trade. Each is
explained in full later; this is the one-screen version, and the **GOLD header strip** at the top of every view repeats
them in this order.

| # | Number | Why first | Where it comes from | 26 Oct 2026 05:50 IST |
|---|---|---|---|---|
| 1 | **COMEX gold, $/oz** (front or matched month) | The world price. Everything else is a ratio to it. | CME via Yahoo `GC=F` / `GCZ26.CMX` (app overlay) | $4,004.2 (GCZ26, 05:39 IST) |
| 2 | **USD/INR** | MCX gold = gold × rupee. A 1% rupee move is a 1% MCX move with gold flat. | Yahoo `INR=X` (offshore before 09:00) | 94.93 |
| 3 | **10-year US real yield** (TIPS, %) | The opportunity cost of holding a zero-coupon asset. The classic driver. | FRED `DFII10` (T+1) / US Treasury (same day, slow) | 2.64% (22 Oct) · Treasury 2.66% (23 Oct) |
| 4 | **MCX basis vs duty-paid landed, %** | How much of the rupee price is local premium, carry and expectation once the dated 15% duty is taken out. | GOLD › PHYSICAL `ph.ladder` (`basis_pct`; the old `implied_premium_pct` 18.0% = 0.995 × 1.15 × 1.031) | **+3.1%** at the 26 Oct 05:49 fair value (§2.6) |
| 5 | **Managed-money net position, contracts** (COT, weekly) | Is the speculative crowd long, how long, and is it adding or leaving — as a description of the week, never a forecast (G-STUDY). | CFTC disaggregated, Tuesday data, Friday release (`p.hero`) | +104,206 (20 Oct), 3rd week of long liquidation; 52-week COT index 26 (context) |

**[B]** If 1 is up, 2 is up and 3 is down, the rupee price has every reason to rise. If 4 is unusually high, part of the
rupee price is not gold and can vanish on a policy change (and the 15% duty itself can change on a Budget line). If 5
is at a multi-year extreme, the crowd is already in — which, our study found, says nothing about next week.

**[P]** None of these five predicts tomorrow on its own (evidence in Part 5). Their job is to tell you *what you are
actually long* when you buy an MCX lot: gold, the rupee, a duty regime and the crowd's position, all at once.

---

# PART 1 — Units, purity, products

## 1.1 Troy ounce, gram, tola, kilo

**[B]** Gold is priced in the world market per *troy ounce*, an old apothecaries' unit, not the kitchen ounce. In India
it is priced per 10 grams; jewellers also use the tola.

**[P]** Exact constants (use these, never 31.1):

| Unit | Grams | Troy oz | Notes |
|---|---|---|---|
| 1 troy ounce (ozt) | **31.1034768** | 1 | the only ounce in bullion; avoirdupois oz = 28.3495 g (never used) |
| 10 g (MCX GOLD, GOLDM quote) | 10 | 0.3215075 | ₹/10 g ↔ $/oz: `₹/10g = $/oz × USDINR × 10 / 31.1034768` |
| 1 kg (MCX GOLD lot, SGE/SHFE kilobar) | 1,000 | 32.1507 | |
| 1 tola | 11.6638 | 0.375 | = 3/8 ozt; Indian/Gulf jewellery trade; 10-tola bar = 116.638 g |
| 1 LBMA Good Delivery bar | ≈ 12,441 (400 ozt nominal) | 350–430 allowed | §1.3 |
| 1 COMEX GC contract | 3,110.35 | 100 | |
| 1 MGC micro contract | 311.03 | 10 | |

**[P]** Pitfall: the fineness-adjusted price. A COMEX contract delivers 100 oz of *gold content* at ≥ 995; MCX GOLD delivers
1 kg at 995. $/oz quotes are for pure gold; when converting a 995 bar's price to a 999 quote, multiply by 999/995.

**[APP]** `shared/mcx_specs.GRAMS_PER_TROY_OZ` and the overlay's `landed`. The LEARN view should show this table once;
the tooltip on any ₹/10 g number is: "₹ per 10 g = $/oz × USD/INR × 10 ÷ 31.1035".

## 1.2 Purity: karat, fineness, 999 vs 995, 916

**[B]** Purity is how much of the metal is gold. Jewellers say *karat* (24K = pure); bullion says *fineness* in parts
per thousand (999 = 99.9% gold). 22K jewellery is 916; most coins and small bars are 999; the big London bars are at
least 995.

**[P]**
- fineness = parts gold per 1,000 by mass. karat K → fineness = K/24 × 1000. 24K ≡ ≥ 999 in practice, 22K = 916.7
  (hallmarked "916"), 18K = 750, 14K = 585, 20K = 833, 23K = 958 (BIS hallmark grades).
- **995 vs 999:** price ratio = 999/995 = 1.00402 → a 999 quote is 0.40% above the same gold at 995. The IBJA board on
  26 Oct 2026 showed 999 at ₹14,163/g and 995 at ₹14,106/g: ratio 1.00404. MCX GOLD and GOLDM are **995**; GOLDPETAL and
  GOLDGUINEA are **999**. Comparing an MCX GOLD price with a jeweller's 999 board without the 0.4% is a classic error.
- **999.9** ("four nines") is the kilobar/SGE standard (Au99.99); **999.5** (Au99.95) is the LBMA minimum for Good Delivery
  rounded up from 995 in some markets — LBMA's rule is ≥ 995.0.
- BIS hallmarking in India: 6-digit alphanumeric HUID is mandatory on hallmarked jewellery (since 2023); the hallmark carries
  the fineness grade, not a price.

**[APP]** `purity` column on MCXG specs. Tooltip: "995/999: multiply a 995 price by 1.00402 to compare with 999".

## 1.3 Bars and coins: who holds what

**[B]** Gold trades in standard shapes so a buyer does not have to assay every piece. The world's wholesale unit is the
~12.4 kg London bar; Asia trades 1 kg bars; retail trades 100 g, 10 g and coins.

**[P]**

| Form | Mass / fineness | Market | Who uses it |
|---|---|---|---|
| LBMA Good Delivery (GD) bar | 350–430 ozt (nominal 400), ≥ 995, refiner on the GD List, serial, year, assay stamp | London OTC, central banks, ETFs (GLD holds GD bars) | bullion banks, central banks, ETF custodians |
| Kilobar | 1,000 g, 999.9 (999.5 accepted at some venues) | SGE, SHFE, Dubai, Istanbul, India imports, COMEX (3 kilobars = one GC delivery) | refiners, Asian banks, Indian nominated agencies, jewellers |
| 100 g bar | 999 / 999.9 | retail-wholesale, MCX GOLDM delivery unit (995) | HNIs, jewellers' stock |
| 10-tola bar | 116.638 g, 999 | legacy Gulf–India trade | historical; still quoted in Dubai |
| 8 g (MCX GOLDGUINEA / PETAL delivery), 1 oz coins (Eagle, Maple, Krugerrand, Britannia, Sovereign 7.98 g 916) | 999 / 916 | retail | retail, mints |

**[P]** Why it matters to a trader: **deliverability drives spreads.** In March–April 2020 flights stopped and Swiss refiners
closed; London had 400 oz bars, New York needed 100 oz bars or kilobars, and the COMEX–London spread (the EFP, §3.6)
blew out to tens of dollars. CME answered with the 400 oz-deliverable "Gold (Enhanced Delivery)" contract (code 4GC) in
April 2020. The lesson: "gold is gold" only until a bar has to move.

**[APP]** `delivery_unit` on MCXG specs. LEARN: this table.

## 1.4 Ways to hold gold in India, and what each one really costs

**[B]** You can own gold as jewellery, coins/bars, a gold ETF or fund, a sovereign gold bond (SGB), "digital gold", or a
futures contract. They are not the same thing: some pay you (SGB coupon), some charge you (ETF expense, making charges),
and one (futures) is a leveraged bet with a date on it.

**[P]**

| Instrument | What you own | Costs you pay | Taxes (headline, verify current year) | Trading hours / liquidity |
|---|---|---|---|---|
| Jewellery (916) | metal + making | making 8–25%, GST 3% on gold + 5% on making, buy-back deductions | capital gains on sale | illiquid; buy-back at a discount |
| Coins/bars (999) | metal | dealer premium 1–4%, GST 3% | capital gains | dealer-dependent |
| Gold ETF (e.g. GOLDBEES on NSE) | units backed by 999 bars in a vault | expense ratio ~0.5–0.8%/yr, brokerage, tracking error | capital gains; no GST on units | NSE hours; tight spreads on the large ones |
| Gold fund of funds | ETF units via a mutual fund | FoF + ETF expense | capital gains | daily NAV |
| Sovereign Gold Bond | government bond indexed to IBJA 999 | nil; **2.5%/yr coupon** | gains tax-free at maturity (8 yrs) for individuals | no new tranches since early 2024; secondary market on NSE/BSE, thin |
| Digital gold (fintech) | a claim on vaulted metal (unregulated) | spread 3–6% round trip, GST 3% | capital gains | app hours |
| **MCX futures** (this program) | a contract, not metal, unless you take delivery | brokerage, exchange/CTT/stamp/SEBI/GST (≈ ₹2,600 round trip on one GOLD lot, §3.1), **financing is implicit in contango** | business/speculative income, not capital gains | 09:00–23:30/23:55 IST, Mon–Fri |
| IIBX (GIFT City) | $-denominated bullion for qualified jewellers | — | — | institutional; link only |

**[B]** The one sentence to take away: a futures long is *not* the same as owning gold — it has leverage, a date, a roll
cost and no coupon, and it carries the rupee.

**[APP]** LEARN only (no live data); there is deliberately no "compare holdings" panel — every broker site has one.

---

# PART 2 — Venues and how each price is made

## 2.1 London: the OTC market, the LBMA, the "fix" (now the LBMA Gold Price auction)

**[B]** Most of the world's gold changes hands in London between banks, over the counter (OTC: privately, not on an
exchange), in "loco London" accounts. Twice a day an electronic auction sets the LBMA Gold Price, the benchmark that
central banks, refiners, jewellers and Indian SGBs reference. People still call it "the fix" from the 1919–2015 phone
fix at N M Rothschild.

**[P]**
- **Loco London** = gold deliverable in an LBMA-approved London vault, in GD bars. **Unallocated** = a claim on a bank's
  pool (you are an unsecured creditor; most OTC trading is unallocated); **allocated** = specific numbered bars in your
  name (storage fee, no credit risk). Spot settles T+2 (loco London), priced in $/ozt.
- **LBMA Gold Price**: run by ICE Benchmark Administration (IBA) since 20 Mar 2015; electronic auction in rounds until
  buy and sell volume balance within tolerance; 10:30 and 15:00 London time. In IST: **AM 16:00 / PM 20:30 while the UK is
  on GMT (from 25 Oct 2026); 15:00 / 19:30 on BST**. Published in USD, GBP, EUR. Access: the price itself is viewable with
  a delay on licensees' sites; the **data tables moved to the MyLBMA portal and need an IBA licence** (verified 26 Oct
  2026: "you will need to have the relevant licence from IBA"). For the app: **link only**; do not scrape.
- **LBMA-i trade reporting** (since Nov 2018): members report OTC trades; the public page shows the **weekly turnover**
  (12-week moving average of daily value; the page on 26 Oct 2026 read "period ending 16 October 2026, Gold: $964 bn…" —
  that is the weekly average value traded). Daily T+1 and full weekly tables are licensed via Nasdaq/Bloomberg/LSEG. This
  is the only public window on the OTC market the owner asked about ("over the counter deals"). It is turnover, not
  positions: there is no COT for London.
- **London vault holdings** (monthly, ~3–4 weeks after month-end): end-September 2026: **9,821 t of gold (+1.96% m/m),
  $1.3 trn, ≈ 785,690 bars; 28,985 t silver** (LBMA page, 26 Oct 2026). Includes the Bank of England's vault (which holds
  for central banks). A rising London stock with a falling COMEX stock = metal moving West→East or East→West; read with
  §6.3.
- Clearing: LPMCL (five clearing banks) nets loco London transfers daily. The clearing statistics (ounces transferred per
  day, monthly) are a second public OTC activity gauge.

**[APP]** GOLD › PHYSICAL `ph.otc` (weekly LBMA-i turnover in $ bn, monthly vault tonnes, CME EFP prints); micro-copy
§8.2.6.

## 2.2 COMEX (CME Group, New York): the futures price the world watches

**[B]** COMEX is the exchange where the big gold futures trade almost 23 hours a day. Its front contract is what news
sites call "gold futures" and what MCX follows tick for tick during the overnight.

**[P]** GC contract (verify on the CME specs page; cmegroup.com answered 403 to this machine's non-browser fetch, so the
figures below are from the project's existing code and CME's published rules as known to June 2026):
- **Size** 100 ozt; **tick** $0.10/oz = **$10**; quoted $/ozt; **fineness** ≥ 995; **delivery** one 100 oz bar or three
  kilobars from an approved refiner into a licensed COMEX depository; delivery months Feb, Apr, Jun, Aug, Oct, Dec (the
  liquid ones) plus nearby months. The *active* month is the one with the most open interest, usually the next even
  month until roughly two weeks before its first notice day.
- **First Notice Day (FND)**: last business day of the month *before* the delivery month (Dec-26: 30 Nov 2026). A long held
  past FND can be assigned delivery; brokers force retail out before it. **Last trading day**: third-last business day
  of the delivery month. The whole futures roll (Dec→Feb) happens in the two weeks before FND; OI migrates and the
  front-month OI collapses: never read a falling front-month OI in roll week as "liquidation" (§6.2).
- **Hours**: CME Globex Sunday 18:00 → Friday 17:00 ET with a 60-minute break 17:00–18:00 ET daily. In IST (US DST until
  1 Nov 2026): 03:30 → 02:30 next day, break 02:30–03:30; from 2 Nov: 04:30 → 03:30. **MCX is closed for about 8.5 hours
  of COMEX trading every night and from Friday 23:30 IST to Monday 09:00 IST while COMEX trades Sunday night.** That is
  the whole reason the Pre-Open desk exists.
- **Daily settlement**: VWAP of trades in the 13:29–13:30 ET window for the active month (23:00 IST on DST, 00:00 IST
  otherwise); other months settle off spreads. Margin: CME SPAN; brokers add house margin. Micro gold **MGC** (10 oz,
  cash-equivalent to GC/10), **1 oz** gold futures (launched 2025), **4GC** (400 oz enhanced delivery). Options: OG
  (American, exercisable into GC) plus weekly expiries.
- **Warehouse stocks**: the daily "Gold Stocks" report (registered / eligible / pledged, by depository). The XLS link
  (`cmegroup.com/delivery_reports/Gold_Stocks.xls`) answered **403** to a non-browser client on 26 Oct 2026; it opens in a
  browser. Definitions in §6.3.

**[APP]** the GOLD header strip names the four instruments (spot proxy · COMEX front GC1 · matched month GCZ26 · MCX
contract) so the continuous `GC=F` and the dated `GCZ26.CMX` are never confused; `d.24h` charts the matched month; WEI
keeps one row (`GC=F`) and CMDT one tile.

## 2.3 Shanghai: SGE spot, SHFE futures, the China premium

**[B]** China is the largest gold consumer and producer. Its spot exchange (SGE) prices gold in yuan per gram; its
futures exchange (SHFE) trades kilobar futures. The difference between the Shanghai price and London, converted to $/oz,
is "the SGE premium": positive when China is pulling metal in.

**[P]**
- **SGE** (Shanghai Gold Exchange): physical spot contracts Au99.99 (kilobar 999.9), Au99.95, Au100g; deferred
  **Au(T+D)** (a rolling, margined spot-deferred contract with a daily deferral fee that flips between longs and shorts —
  China's own "lease rate" signal); international board (iAu99.99) in the Shanghai FTZ. **Shanghai Gold Benchmark Price**
  (since Apr 2016): auctions at **10:15 and 14:15 Beijing (07:45 and 11:45 IST)**, CNY/g.
- **SGE premium** = `SGE Au99.99 (CNY/g) × 31.1035 ÷ USDCNY − LBMA/COMEX spot ($/oz)`. Typical range −$5 to +$30; spikes to
  $50–120 (2023 Q3–Q4) when import quotas were tight; negative in weak-demand or quota-free periods. Chinese import
  demand is quota-managed by the PBoC: a high premium with few new quotas is a *shortage*, not necessarily *demand*.
- **SGE withdrawals** (monthly, tonnes): the standard proxy for Chinese wholesale demand. **PBoC reserves**: reported
  monthly (~7th) via SAFE; WGC compiles.
- Data access: the EN daily table (close, VWAP, volume, OI, Au(T+D) direction) and the benchmark JSON are fetchable once
  a day and stored by the 16:10 job (view-only, attributed; owner decision O-1 may downgrade them to links). The
  `data_DelayedQuotes` page itself is JavaScript-filled and is not read.
- **SHFE AU**: 1 kg, CNY/g, night session 21:00–02:30 Beijing (18:30–00:00 IST): it is the Asian price while MCX is in its
  evening session. English site verified (200, 7 s).

**[APP]** GOLD › PHYSICAL `ph.shanghai` (SGE PM vs the same date's London PM or COMEX at 14:15 Beijing, both timestamps
shown), DAILY `d.sge` (delayed intraday line on the Shanghai band), POSITIONING `p.asia` (SHFE front OI, Au(T+D)
direction). PUBLISH-CONTEXT, attributed.

## 2.4 MCX: the rupee contract you actually trade

**[B]** MCX (Multi Commodity Exchange, Mumbai) lists gold futures in rupees per 10 grams. The big one (GOLD) is one
kilogram; the Mini is 100 g; the Guinea is 8 g; the Petal is 1 g. Prices follow COMEX × the rupee minute by minute,
plus the import duty and India's local premium or discount. Trading runs 09:00 to 23:30 IST (23:55 in US winter).

**[P]** Specs as the app serves them (`/api/mcx/specs`, ICICI master of 23 Oct 2026; margins = exchange NRML from the Zerodha
mirror of 25 Oct 2026, 9.25% of notional on every gold contract, dated — the old 6% constant is gone):

| Code | Lot | Quote | Tick | ₹ per ₹1 move per lot | Purity | Expiry | Front (26 Oct) | Settlement 22 Oct | OI (lots) | NRML margin (25 Oct 2026) |
|---|---|---|---|---|---|---|---|---|---|---|
| GOLD | 1 kg | ₹/10 g | ₹1 | **₹100** | 995 | 5th of Feb/Apr/Jun/Aug/Oct/Dec (prev. business day if closed) | 4 Dec 2026 | ₹1,46,079 | 16,650 | ≈ ₹13.26 lakh (9.25%) |
| GOLDM | 100 g | ₹/10 g | ₹1 | **₹10** | 995 | 5th, monthly | 5 Nov 2026 | ₹1,44,584 | 48,437 | ≈ ₹1,31,165 |
| GOLDTEN | 10 g | ₹/10 g | ₹1 | **₹1** | 999 | month-end | 30 Oct 2026 | (Breeze `GOLDTE`) | 25,655 | ≈ ₹13,291 |
| GOLDGUINEA | 8 g | ₹/8 g | ₹1 | **₹1** | 999 | month-end | 30 Oct 2026 | ₹1,16,648 | 12,009 | ≈ ₹10,686 |
| GOLDPETAL | 1 g | ₹/1 g | ₹1 | **₹1** | 999 | month-end | 30 Oct 2026 | ₹14,581 | 155,778 | ≈ ₹1,335 |

**[P]** Note the OI pattern: GOLDM (48k lots × 100 g = 4.8 t) and GOLDPETAL (156k lots × 1 g = 0.16 t) have more *lots*, GOLD
(16,650 × 1 kg = 16.7 t) has by far the most *metal*. Liquidity for a ₹-sized order lives in GOLD and GOLDM.

**[P]** Mechanics (`shared/mcx_specs.py` is the code source; the exchange circular is the legal source):
- **Session**: 09:00 → 23:30 IST while New York is on daylight time, 23:55 otherwise (US-linked; switches 2 Nov 2026).
  Morning/evening split at 17:00 matters only on partial holidays (MCX's calendar ≠ NSE's: 10 Nov Diwali-Balipratipada
  is morning-closed, 24 Nov Guru Nanak morning-closed; Muhurat session Sunday 8 Nov evening).
- **Daily settlement price** = VWAP of the last 30 minutes of trading (the project's `reference_price` window mirrors
  it). **Daily price band** ±3% around the previous settlement, widened in steps (to 6%, then 9%) after a cooling
  period when hit: on a shock day the first ±3% can lock the market for 15 minutes while COMEX keeps moving.
- **Margin**: SPAN-style initial margin + exposure margin (ELM), revised daily; bullion has run ≈ 6–12%; **additional /
  special margins** by circular on volatile days; **delivery margins ramp up in the tender period**. Leverage §3.2.
- **Expiry & delivery**: GOLD and GOLDM expire on the 5th; compulsory delivery for open positions at expiry (995, 1 kg /
  100 g bars with assay certificate, at Ahmedabad basis centre and additional centres). The **tender/delivery window
  runs through the last sessions before expiry**; brokers without a delivery facility square off clients before it.
  ICICI's cut-off date for GOLD is **not in this repo** — owner action: confirm the commodity rulebook and put the date on
  the MCXG specs table. PETAL/GUINEA deliver 999 in 8 g coin multiples, month-end.
- **Due Date Rate (final settlement)**: a polled spot price (995, ex-Ahmedabad, duty-paid, ex-GST) on the expiry day.
- **MCX price basis**: ex-Ahmedabad, **inclusive of customs duty and AIDC, exclusive of GST**. So the MCX price is a
  duty-paid landed price; GST (3%) is added only when physical gold is sold.
- **Options**: MCX lists European options on GOLD (1 kg) and GOLDM futures; in-the-money options **devolve into futures
  positions on the option expiry** (a few sessions before the futures expiry): the pitfall is waking up with a 1 kg
  futures position and its margin. Options are out of scope for the paper ticket; LEARN must carry the warning.
- Public data: `mcxindia.com` answered **403** to non-browser clients (both the product page and the bhavcopy page, 26 Oct
  2026). The ICICI public security master (`SecurityMaster.zip`, verified 200, 3.0 MB, 23 Oct 01:58 UTC) is the app's
  source for the price band (settlement = band midpoint) and OI. MCX bhavcopy history (daily OHLC/OI per contract) is
  the missing piece for any daily/weekly/monthly MCX view: **it must be fetched in a browser session or through the broker
  (Breeze historical, verified working for 1-minute bars)**.

**[APP]** MCXG: session clock, quote, ticket; GOLD › CONTRACTS `c.selector` (specs, shared with MCXG), `c.mcx` (chain),
`c.roll` (expiries and tender); the pre-open desk is GOLD › HEALTH `h.open`. Tooltips per column in §8.1.12.

## 2.5 Other venues (link only)

**[B]** Other exchanges list gold too — Tokyo, Dubai, Istanbul, Moscow, GIFT City — but none sets the price the way
London, COMEX, Shanghai and MCX do, so the page links to them and shows no number from them.

**[P]** TOCOM/OSE (Japan, yen/g, 1 kg), DGCX (Dubai, $/oz, 32 oz lots; the Gulf–India corridor's futures), Borsa Istanbul,
Moscow Exchange, **IIBX** (India International Bullion Exchange, GIFT City: $-denominated spot for qualified jewellers;
the government's intended import channel), Nasdaq Data Link (ex-Quandl LBMA series: paid). None belongs in the app as a
number; all belong in LEARN as "exists, because…".

## 2.6 How the rupee price is built (the ladder, and what the old "18% premium" was made of)

**[B]** The Indian gold price is the world price, converted to rupees per 10 grams, plus the import duty at the border
(**15% since 13 May 2026**), plus whatever the local market adds or subtracts that week. When the rupee weakens, Indian
gold rises even if world gold is flat; when the Budget changes the duty, MCX jumps against COMEX in a minute. On the page
every bar of the ladder carries its own timestamp; a premium or basis is honest only when both of its legs share a clock —
never divide a live bar by yesterday's settlement.

**[P]** The ladder, with the live values of 26 Oct 2026 05:49 IST (COMEX GCZ26 $4,004.2, USD/INR 94.93, MCX fair ₹1,44,228):

```
landed_999 (₹/10 g)  = COMEX ($/oz) × USDINR × 10 / 31.1034768
                     = 4,004.2 × 94.93 × 10 / 31.1034768 = ₹1,22,211
landed_995           = landed_999 × 0.995                = ₹1,21,600    (MCX GOLD/GOLDM deliver 995)
duty-paid landed     = landed_995 × (1 + 0.15)           = ₹1,39,840    (BCD 10% + AIDC 5% = 15%, Notification 16/2026-Customs, effective 13 May 2026)
MCX fair (model)     = ₹1,44,228                                         (settlement 1,46,079 scaled by COMEX and INR moves since the 22 Oct close)
MCX basis            = 1,44,228 / 1,39,840 − 1 = +3.1%                   (carry to the Dec expiry ≈ 1%; local premium + expectation ≈ 2%)
old "implied premium"= 1,44,228 / 1,22,211 − 1 = +18.0% = 0.995 × 1.15 × 1.031 − 1   (purity × duty × basis: the mystery number was mostly duty)
```

**[P]** What the terminal does with it (PLAN §a.7 `ph.ladder`, SOURCES.md §10 M5–M8): the duty is a **dated constant**
(`GOLD_IMPORT_DUTY_PCT` with its effective date; `DUTY_HISTORY`: 6% from 24 Jul 2024, 15% from 13 May 2026), printed with
its notification on every render; the basis is shown against the duty-paid landed price and again carry-adjusted; the old
`implied_premium_pct` survives one release as a deprecated alias. **Owner caveat (PLAN O-3):** the 15% rests on secondary
sources that all agree (taxguru, a2ztaxcorp, LiveLaw, ICRA, the 16 Oct 2026 headlines; MCX June gold rose 6–7% on 13 May
2026); CBIC's own site refuses scripted clients (incomplete TLS chain), so **confirm the notification and the fortnightly
tariff-value practice at CBIC in a browser** and set `GOLD_IMPORT_DUTY_PCT=15` with its effective date in `.env`. If CBIC
says otherwise, the ladder is wrong by exactly the difference; nothing else in this document depends on the number.

**[P]** Three things make up the basis, and the panel shows which, dated and sourced:
1. **Carry.** MCX Dec vs spot carries ~6 weeks of rupee interest (≈ 0.8–1.0%, §3.3). Mechanical; shown as the
   carry-adjusted basis.
2. **Local premium/discount.** Dealers quote India at a premium or discount to the official duty-paid price (Reuters'
   weekly "Asia Gold" survey: a discount of up to $14/oz in early Oct 2026, a premium of up to $3 late Oct; WGC's weekly
   India premium +$11.4/oz on 16 Oct). Festive demand (Dhanteras Fri 6 Nov 2026, Diwali Sun 8 Nov) and a rupee at 95 push
   it up; post-duty-hike inventory and weak demand push it into discount (Aug 2026, the duty-change month: −$113.6/oz).
3. **Expectation.** A Budget line (1 Feb, 11:00 IST) can cut the duty in a minute; the back months price that in (MCX Feb
   vs Dec, §3.3, §7.3). That is policy expectation, not physical tightness.

**[P]** Whatever the split, the trading lesson is the same: **the duty and the basis are positions.** A long in MCX GOLD is long
gold, long USD/INR, long a 15% duty regime and long "the premium". The duty can be cut by a Budget line in one minute and
the premium by a rupee rally over weeks. `MCX_BASIS_PCT` and `INDIA_PREMIUM_PCT` are stored daily from the day the jobs
start (point-in-time, PLAN §c.1), so this time the history exists.

**[P]** **Sensitivities** (the desk's rule-of-thumb numbers, 26 Oct 2026): `rs_per_comex_dollar = settlement / COMEX_ref ≈
1,46,079 / 4,004 ≈ ₹36.5 per $1` (per 10 g; × 100 = **₹3,650 per $1 per GOLD lot**); `rs_per_inr_rupee = settlement /
USDINR_ref ≈ 1,46,079 / 94.93 ≈ ₹1,539 per ₹1 of USD/INR` (per 10 g; × 100 = **₹1,53,900 per ₹1 move in USD/INR per lot**).
A 1% rupee move (≈ ₹0.95) is worth ≈ ₹1,46,000 on one GOLD lot. That is why the ladder shows the rupee next to COMEX.

**[P]** **Tariff value mechanics (pro pitfall):** customs duty is charged on the CBIC *tariff value* (notified roughly every
fortnight in $/10 g), not on the invoice. Between notifications the embedded duty in landed cost lags the market, so the
"fair" duty-paid price drifts around the MCX price by up to ±0.5% through the fortnight. Do not read that drift as a
premium signal.

**[APP]** GOLD › PHYSICAL `ph.ladder` (the stack: the first bars live and stamped "now", the IBJA premium at the fix
minute, the MCX basis at the settlement session — each derived number names its clock) and `ph.india` (premium and basis
history with the duty steps annotated); MCXG's overlay is one line that links to it; the desk's `rs_per_comex_dollar` /
`rs_per_inr_rupee` live on GOLD › HEALTH `h.moved`. Each number appears once per page.

---

# PART 3 — Futures mechanics

## 3.1 Lot, multiplier, tick value, notional, P&L, cost

**[B]** A futures lot is a fixed quantity of gold. The price is quoted per 10 g, but you own 1 kg (GOLD) or 100 g
(GOLDM), so every ₹1 move in the quote is ₹100 or ₹10 of profit or loss. The *tick* is the smallest price step.

**[P]**
- `multiplier = lot_grams / quote_grams` (GOLD 1000/10 = 100; GOLDM 100/10 = 10; GUINEA 8/8 = 1; PETAL 1/1 = 1).
- `tick value = tick × multiplier` (GOLD ₹1 × 100 = ₹100).
- `notional = price × multiplier × lots` (GOLD at ₹1,46,079: **₹1.46 crore per lot**; GOLDM ₹14.6 lakh; PETAL ₹14,581).
- `P&L = (exit − entry) × multiplier × lots − costs`.
- Round-trip cost, squared off, one GOLD lot at ₹1,46,079 (app ticket model, `shared/mcx_specs.round_trip_costs`):
  exchange 0.0021% × 2 sides ≈ ₹614; CTT 0.01% sell side ≈ ₹1,461; stamp 0.002% buy ≈ ₹292; SEBI ₹10/crore × 2 ≈ ₹29;
  brokerage ₹20 × 2; GST 18% on brokerage + exchange + SEBI ≈ ₹123 → **≈ ₹2,560 ≈ 0.018% of notional ≈ 26 ticks** (26 Oct 2026 prices; ≈ ₹2,445 / 24.5 ticks on 5 Nov — the CONTRACTS card prints today's). The
  breakeven move is ₹26 per 10 g. Costs are not the problem in gold futures; **leverage and gaps are.** (Compare the
  project's equity delivery round trip of ≈ 0.93%.)

**[APP]** MCXG paper ticket (`notional`, `tick_value_position`, `round_trip`). Tooltip on "Tick": "₹1 on the quote =
₹100 on one GOLD lot (1 kg ÷ 10 g)".

## 3.2 Margin and leverage

**[B]** You do not pay the full ₹1.46 crore for a GOLD lot; you post a deposit (margin) — 9.25% of notional on every MCX gold contract on 25 Oct 2026 (exchange NRML,
Zerodha mirror; it changes daily and jumps after circulars) — and the exchange marks your position to the settlement price every evening, debiting losses in cash. If your cash runs out the
broker closes you. The deposit is small, so the leverage is large: a 1% move is about a 10–15% move on your margin.

**[P]**
- `leverage = notional / margin`. At 9.25%: 10.8×. A 1% adverse day on one GOLD lot = ₹1,46,000 against ≈ ₹13.3 lakh of
  margin = **−11% of margin in one day**. Gold's realised daily volatility has run 1–1.5% in 2024–26,
  with 3–6% days on event shocks (Apr 2025, Oct 2025).
- Daily MTM in **cash**; the margin itself can be pledged collateral but MTM losses cannot. Keep MTM headroom of at
  least 3 daily-vol moves (≈ 4–5% of notional) in cash beyond the initial margin, or the first bad week ends the trade
  for you.
- Margins **change**: SPAN parameters are reset daily; special/additional margins are imposed by circular on volatile
  days; delivery margins rise in the tender period; a margin increase on an open position is a cash call the next
  morning. The MCXG `margin_pct_indicative` is a planning number, never the broker's number.
- Calendar-spread margin benefit: a long Dec / short Feb pair carries a fraction of outright margin (exchange-defined);
  this is what makes term-structure trades (§7.3) financeable.

**[APP]** MCXG ticket (`indicative_margin`, `margin_pct_indicative`). The "Manual checks" list already links MCX
circulars for margin changes.

## 3.3 Contango, backwardation, cost of carry, implied lease rate

**[B]** Futures for later months usually cost more than for nearer months, because whoever holds gold for you until then
has to finance and store it. That upward slope is *contango*. When later months are *cheaper* (backwardation), someone
wants gold now badly enough to pay up: a shortage signal.

**[P]**
- Cost of carry: `F = S × exp((r − l + s) × T)`, with r the funding rate of the quote currency, l the gold lease rate
  (what a borrower of metal pays), s storage/insurance. Gold is almost always in contango because r ≫ l.
- **Implied carry** from two futures months: `c = ln(F2/F1) × 365/days(F1→F2)`. On COMEX, compare c with SOFR/T-bills:
  `implied lease ≈ r − c` (ignoring storage). On MCX, the carry embeds the **rupee** rate: `c_MCX ≈ c_COMEX + (r_INR −
  r_USD)` by covered interest parity; the INR forward premium (historically 1–4%/yr) makes MCX contango steeper in %
  than COMEX's. **A steeper MCX curve is not a bullish Indian signal; it is interest-rate differential.**
- **Backwardation** in gold is rare and meaningful: Nov 2008, 2013 (post-crash physical demand), Jan–Feb 2025 (tariff
  scare: front COMEX bid above London spot, EFP $40–60). On MCX, apparent backwardation across a Budget date usually
  means the market is pricing a **duty cut** into the later month, not physical tightness. Read the calendar first.
- Roll yield for a long holder = −c: holding gold futures through contango costs the carry every roll (≈ 4–5%/yr in USD
  at 2024–26 rates, more in INR). This is the "no coupon" of §1.4 made explicit.

**[APP]** GOLD › CONTRACTS `c.comex` (six COMEX months with last week's ghost curve, calendar spreads, implied carry
p.a.) and `c.mcx` (the MCX chain with implied carry); one carry convention per page (against the front month). Micro-copy
§8.2.10.

## 3.4 Roll: when, cost, what it does to the data

**[B]** Before a contract expires, traders move their position to the next month: sell Dec, buy Feb. Everyone does it in
the same two weeks, so prices and open interest shift between months in a predictable pattern.

**[P]**
- COMEX: roll in the ~10 sessions before FND (Dec-26 FND = 30 Nov 2026); volume leaves the front around 2 weeks out;
  CME's "pace of roll" is the public tracker. MCX GOLD: roll in the last week before the 5th; the app's contract picker
  uses "highest OI among expiries more than 5 days away" (`pick_contract(roll_days=5)`) and the ICICI master's OI.
- Roll cost = calendar spread paid = carry (§3.3) ± liquidity. On MCX the Dec/Feb spread trades its own book; a retail
  roll is two market orders and ~2× the round-trip costs.
- Data effects: front-month **OI falls and next-month OI rises** — total-market OI is the only honest OI series across a
  roll; the **continuous price series jumps** by the spread at the roll date (back-adjust before computing returns);
  **COT is total-market** so it is roll-proof, but its *spreading* column swells in roll weeks (20 Oct 2026: non-commercial
  spreads +8,304 while longs −8,158: a roll/relative-value footprint, not a liquidation).

**[APP]** `pick_contract` (Pre-Open), `_resolve_expiry` (MCXG). Tooltip on "front (by OI)": "the month with the most
open interest at least 5 sessions from expiry; traders roll before expiry week".

## 3.5 Settlement, expiry, delivery, and choosing the contract

**[B]** Every futures contract ends. On MCX the big contracts end with physical delivery, so a trader who does not want
to receive or deliver a kilo of gold must close or roll before the delivery window. Choose the contract by what you want:
the liquid month for trading, the small contract for sizing, never a far month for a short trade.

**[P]** The contract chooser the owner asked for, as a decision table:

| Purpose | Choose | Why | Avoid |
|---|---|---|---|
| Intraday / swing, ₹ sizing > ₹10 lakh risk capacity | **GOLD front** (Dec-26 now) | most metal, tightest spread, OI 16.6k lots | far months (Apr-27: thin, wide) |
| Swing with 1% account risk on a ₹5–20 lakh account | **GOLDM front** (Nov-26, then Dec-26) | ×10 multiplier makes ATR-stops affordable (§7.6) | GOLD (₹100 tick, ₹8.8 lakh margin) |
| Learning with real ticks, pocket money | GOLDPETAL / GOLDGUINEA | ₹1 per ₹1, margin ≈ ₹900–7,000 | treating them as a liquidity benchmark (they are thin per lot) |
| Holding through a COMEX roll (mid/late Nov) | the MCX month that **matches the next COMEX active month** (Feb-27 ↔ GCG27) | the overlay compares like with like; MCX Dec vs COMEX Feb mixes carry into "premium" | mismatched months in the premium calc |
| Expressing "gold up, rupee flat" | GOLD/GOLDM **plus short USD/INR futures** (§7.4) | strips the rupee leg | believing MCX gold is a pure gold bet |
| Delivery / physical arbitrage | GOLD or GOLDM with a delivery-enabled broker, before tender | 995 bars at Ahmedabad; assay rules | retail accounts (brokers auto-square-off) |

**[P]** Dates on the roll calendar (`c.roll`; computed by `active_expiries`, verified against the ICICI master):
GOLD 4 Dec 2026 / 5 Feb 2027 / 5 Apr 2027; GOLDM 5 Nov / 4 Dec / 5 Jan; PETAL & GUINEA 30 Oct / 30 Nov / 31 Dec. COMEX
GCZ26 FND 30 Nov 2026, LTD ≈ 29 Dec 2026.

**[APP]** GOLD › CONTRACTS `c.selector` (shared with MCXG) and `c.roll`; this table is the LEARN companion of the
selector; per-column tooltips in §8.1.12.

## 3.6 Basis and EFP

**[B]** *Basis* is the gap between the futures price and the cash price. *EFP* (exchange for physical) is the trade
dealers use to swap a futures position for real metal in London; its price is the COMEX–London spread. When bars cannot
move, the EFP explodes and the futures price detaches from spot.

**[P]**
- `basis = F − S` (quote: $/oz for COMEX front vs loco London spot; ₹/10 g for MCX vs IBJA/dealer spot). Fair basis =
  carry (§3.3); the **residual basis** (actual − fair) is the stress gauge.
- EFP = futures-vs-spot swap, quoted by bullion banks as a spread; positive and wide = NY bid for metal (Mar 2020: $70+;
  Jan–Feb 2025: $40–60 on tariff fears, COMEX stocks rose above 40 Moz as metal flew in); collapsing to zero or negative =
  NY long on metal, London short.
- MCX–IBJA basis (₹/10 g): the Indian version. IBJA publishes 999/995 rates daily (AM/PM), free on `ibjarates.com`
  (verified 200: 999 ₹14,163/g, 995 ₹14,106/g on the morning of 26 Oct 2026, i.e. 995 = ₹1,41,060/10 g vs MCX Dec fair
  ₹1,44,228: +2.2%, of which Dec carry ≈ 1% and the rest local premium/expectation). Caveat: IBJA's timestamp ("Rates will
  be uploaded soon" for today's AM) means the board can be yesterday's PM; always store the date with the rate.

**[APP]** GOLD › PHYSICAL `ph.ladder` (IBJA 999 PM and the MCX front against duty-paid landed, each derived number at
its own clock) and `ph.india` (premium and basis history); IBJA is stored by the 13:45 / 18:10 jobs. PUBLISH-CONTEXT,
attributed (owner decision O-1).

---

# PART 4 — The players, and who is long or short structurally

## 4.1 The cast

**[B]** Gold has a small number of recurring characters. Miners dig it and sell it forward; refiners turn it into bars;
bullion banks stand between everyone, lending, storing and hedging; central banks hold it as a reserve; ETFs hold it
for investors; jewellers and fabricators buy it to make things; funds trade it; and retail buys coins, jewellery and
futures. Each one has a structural side.

**[P]**

| Player | What they do | Structural futures position | COT category (§6.1) | Read them via |
|---|---|---|---|---|
| **Bullion banks** (JPM, HSBC, UBS, ICBC Standard, StoneX…) | market-make OTC, vault, lend, hedge client flow, run ETF custody/APs | **net short futures** (hedging OTC longs sold to clients and physical inventory) | Swap Dealer (mostly) + Producer/Merchant | COT swap-dealer short (−238,536 on 20 Oct 2026), CFTC Bank Participation Report (monthly) |
| Refiners (Valcambi, PAMP, Argor, Rand, Indian: MMTC-PAMP) | melt scrap and doré into bars; the physical bottleneck | short futures vs metal in process | Producer/Merchant | LBMA GD List, EFP stress |
| Miners | produce ~3,600 t/yr; hedge a slice of future output | short (hedge book; small since the 2000s de-hedging) | Producer/Merchant | WGC/Metals Focus hedge-book data (paid), quarterly reports |
| Central banks | hold ~36,000 t; net buyers every year since 2010; >1,000 t/yr in 2022, 2023, 2024 (WGC) | none on COMEX; buy OTC/locally | — | WGC/IMF monthly, PBoC (~7th), RBI WSS (weekly $ value), RBI half-yearly tonnes |
| ETFs (GLD, IAU, GOLDBEES…) | hold allocated bars; create/redeem via APs | none; their flow is physical | — | SPDR daily tonnes (now a PDF), WGC weekly/monthly flows |
| Jewellers / fabricators (India, China, Turkey, Gulf) | ~2,000 t/yr jewellery; buy spot, hedge inventory | short futures (inventory hedge) or long (pre-season) | Producer/Merchant (MCX: "hedgers") | India premium/discount, SGE premium, trade data |
| CTAs / managed futures / macro funds | trend and macro trading in size | **the swing long**; occasionally net short (Oct 2023: −7,561) | Managed Money | COT MM net, COT index, number of traders |
| Family offices, prop desks, unregistered funds | discretionary | mixed; in 2025–26 a large **net long** (other reportables +95,659 on 20 Oct 2026) | Other Reportables | COT |
| Retail (futures) | small lots | net long, sentiment-driven | Non-reportable | COT non-reportable; MCX participant-wise OI (if MCX publishes it: UNVERIFIED) |
| Indian importers: nominated agencies, banks, IIBX | import under RBI/DGFT rules | hedge on MCX/COMEX | — | DGCI&S monthly imports, RBI, customs tariff value |
| Governments | duty, quotas, sanctions, reserve freezes | — | — | Budget, CBIC, PBoC quotas |

**[P]** The structural picture in one line, with the 20 Oct 2026 numbers: **commercials are net short 235,582 contracts (73% of
OI on the short side) and almost all of it is swap dealers (−220,799), not miners (−14,783); non-commercials are net long
(managed money +104,206, other reportables +95,659); retail is net long +35,717.** This is the normal shape of the gold
market since 2016: hedgers short, investors long. The *change* in these numbers, not the level, is the information (§6.1).

## 4.2 Physical flow in round numbers (WGC Gold Demand Trends, annual; approximate, for scale)

**[B]** Gold is a stock, not a flow: about 216,000 tonnes exist above ground and a year of mining adds under 2 % of it,
so the price is set by who wants to hold what already exists — investors and central banks — not by this year's mine
output.

**[P]** Supply ≈ 4,800 t/yr: mine ≈ 3,600 t + recycling ≈ 1,200 t. Demand ≈ jewellery 2,000 t + bars & coins 1,200 t + central
banks 1,000 t + technology 300 t ± ETF flows (−250 to +900 t in a given year) ± OTC/other (the balancing item, which
the WGC itself labels as including unreported OTC investment). Above-ground stock ≈ 216,000 t (a 21 m cube), of which
jewellery ≈ 45%, private investment ≈ 22%, central banks ≈ 17%. Annual mine supply is ≈ 1.7% of the stock: **gold is a
stock market, not a flow market — price is set by who wants to hold the existing stock, not by this year's mine output.**
That is why "supply/demand" for gold means investor + central-bank demand, and why the COT and ETF data matter more than
mine news.

**[APP]** GOLD › MONTHLY `m.balance` (the WGC quarterly balance sheet, attributed, display-only); the round numbers above
are the LEARN version.

---

# PART 5 — What moves gold, and the regimes

## 5.1 Real yields

**[B]** Gold pays nothing. When safe bonds pay a lot *after inflation*, holding gold costs you that income, so gold falls;
when real yields drop or go negative, gold rises. From 2007 to 2021 this was the single best explanation of the gold
price. Since 2022 it has worked much less well, because central banks started buying gold regardless of yields.

**[P]**
- Measure: 10-year TIPS yield (FRED `DFII10`, daily, published T+1; US Treasury real yield curve CSV same day but ~20 s
  to fetch — the app already uses both). Also 5y and 2y real; the 10y is the convention.
- Mechanism: gold ≈ a zero-coupon real perpetuity; its "duration" to real yields was empirically ≈ −15 to −25 (a 100 bp
  fall in the 10y real yield went with +15–25% in gold) during 2007–2021. **2022–2026 broke the level relationship**: the
  real yield rose from −1.1% (Aug 2020, gold $2,075) to +2.64% (22 Oct 2026) while gold went from $2,075 to ~$4,000. The
  direction still matters day to day (a 10 bp real-yield jump on a CPI print still knocks gold), the level no longer
  anchors it. Reason in §5.3.
- Evidence: Erb & Harvey, "The Golden Dilemma" (Financial Analysts Journal 2013; SSRN 2078535 — SSRN answered 403 to
  this machine, standard reference): the real gold price mean-reverts over decades and gold is an unreliable short-run
  inflation hedge; the real-yield correlation is strong in-sample but regime-dependent. The app's own data
  (`context` row "10-year real yield") is signed "supportive/headwind" by the *change since the MCX close*: that is the
  right use (direction), and the LEARN tooltip must say so.

**[APP]** the header strip (10-y real yield, T+1) and GOLD › MACRO `mc.drivers` (history, percentile, 60-day
correlation), `mc.health` (the rolling correlation and the betas by regime). PUBLISH-CORE; one driver panel, no second
plot.

## 5.2 The dollar

**[B]** Gold is priced in dollars, so when the dollar weakens against other currencies, gold tends to rise in dollar
terms (and vice versa). For an Indian trader there are two dollars: the world dollar (DXY) that moves COMEX, and USD/INR
that moves MCX on top.

**[P]** DXY (ICE, 57.6% euro) and the Fed's broad index (FRED `DTWEXBGS`, 121.40 on 16 Oct 2026; T+~7 days) are the
measures. Correlation of daily changes with gold ≈ −0.3 to −0.5 historically; it weakens in crises when both rise
(Mar 2020, 2022 H1, Apr 2025). The MCX exposure is `∂MCX/∂USDINR ≈ settlement/USDINR ≈ ₹1,539 per ₹1` (26 Oct 2026). The
EUR/USD "trigger" on the desk (1.1161 default) is the owner's own level: context, no study behind it.

**[APP]** USD/INR on the header strip and `mc.drivers`; the dollar tile on `h.gauges` and `mc.drivers` names the series it
uses (DXY from stored bars, or FRED's broad index DTWEXBGS with its ≈ 1-week lag when that is all the store has — never
the one under the other's name); `mc.kgx` splits a move into gold and the dollar. PUBLISH-CORE for USD/INR; CONTEXT for
the dollar.

## 5.3 Central-bank buying

**[B]** Since 2010 central banks have been net buyers of gold every year, and since 2022 — after Russia's dollar reserves
were frozen — they have bought more than 1,000 tonnes a year (about a quarter of annual supply). They buy for reserve
diversification, not for price, so they keep buying when funds sell. That is the main reason the real-yield rule broke.

**[P]** WGC (IMF IFS + central-bank reports): 2022 ≈ 1,082 t, 2023 ≈ 1,037 t, 2024 ≈ 1,045 t (WGC annual Gold Demand
Trends; approximate). Leaders: PBoC (reports monthly via SAFE around the 7th; pauses and restarts are market events),
Poland, Turkey, India (RBI ≈ 880 t by 2025 after buying 70+ t in 2024; weekly WSS shows the $ value, tonnes in the
half-yearly reserve-management report), Czech, Singapore, Kazakhstan, Uzbekistan. Reporting lag 1–2 months; some buying
is unreported (the WGC's "OTC and other" balancing item). Evidence of predictive value: **context only** — the flow is
steady and lagged; it explains the level regime, not next week.

**[APP]** GOLD › PHYSICAL `ph.official` (IMF holdings as Moz and tonnes, each with its data month; the PBoC streak; RBI
weekly value and share) and MONTHLY `m.official` (net purchases over 12 months). PUBLISH-CONTEXT.

## 5.4 ETF flows

**[B]** Gold ETFs buy and vault physical bars when investors put money in and sell them when money leaves. Their tonnage
is public daily, so it is the cleanest daily read on Western investor demand.

**[P]** GLD (largest; ~900–1,000 t range in 2024–26) publishes "Total Net Asset Value Tonnes in the Trust" daily; the
historical CSV the project once used **now returns a PDF** (verified 26 Oct 2026: `GLD_US_archive_EN.csv` → `%PDF-1.5`,
697 KB) — the page itself is 200 and the number is readable in a browser. iShares IAU page verified 200 (1.6 MB,
JS-heavy). WGC aggregates all funds weekly and monthly (page verified: "Flows and holdings data are updated on the
website weekly and monthly… xlsx monthly", latest "Gold ETF Flows: September 2026"). Indian gold ETFs: AMFI monthly AUM
(₹), tonnes via WGC.
Evidence: flows are **contemporaneous** with price (they are the price's footprint in Western demand), forward
predictive power is weak and regime-dependent (2013: −880 t with −28%; 2020: +877 t with +25%; 2022–23 outflows while
price held because of §5.3). Use as "who is buying", not "what is next". **Context only.**

**[APP]** GOLD › PHYSICAL `ph.etf` (GLD tonnes daily since 2004 with changes, IAU, WGC weekly flows by region;
display-only, attributed, O-1) and the ETF tile on `h.gauges`. PUBLISH-CONTEXT.

## 5.5 Risk-off and the safe-haven claim

**[B]** In a crisis people buy gold — usually. But in the first days of a liquidity crash (Mar 2020, Oct 2008) gold falls
with everything else because it is the asset people *can* sell. The safe-haven effect comes after the margin calls.

**[P]** Baur & Lucey (2010, Financial Review) and Baur & McDermott (2010, JBF): gold is a hedge for equities on average
and a *safe haven in extreme stock-market days*, but the effect fades within ~15 trading days. Practical reading: gold's
first move on a shock is noise (liquidation), its second move is the signal. The desk's "event risk" headline count
(risk words in the last 24 h) is a tally with **no study behind it**: it wears a `heuristic` chip and gives no sizing
advice.

**[APP]** GOLD › HEALTH `h.headlines` (the risk-word count with its `heuristic` chip).

## 5.6 Inflation expectations

**[B]** Gold is sold as an inflation hedge. Over decades it roughly keeps its purchasing power; over months it does not
track inflation at all. The market watches *expected* inflation (breakevens) because that, with nominal yields, sets the
real yield.

**[P]** `real yield ≈ nominal (DGS10 4.96%) − breakeven (T10YIE 2.34%)` ≈ 2.62% (22–23 Oct 2026; FRED DFII10 2.64%:
consistent). Erb–Harvey: gold/CPI ratio has swung 2× to 8× — a "hedge" with a 4× range is not a hedge at a 1-year horizon.
A CPI print moves gold through the real-yield channel in the first minute (§7.5).

**[APP]** `mc.drivers` shows the breakeven (T10YIE) beside the real yield. PUBLISH-CONTEXT.

## 5.7 Positioning extremes

**[B]** When nearly everyone who might buy has already bought, there is no one left to push the price up; the same in
reverse. The COT shows how crowded the speculative side is.

**[P]** COT index (§6.1) at > 90 or < 10 on the 52-report or 3-year window is what desks call "crowded". **Our own study
says it does not forecast** (G-STUDY, 26 Oct 2026: 1,063 reports 2006→2026, every signal dated at its Friday release,
Newey-West t, 0.15% costs): rank IC at 1/4/13 weeks ≈ 0 for every positioning metric; the classic rule points the wrong way
(crowded weeks +1.08% vs washed-out +0.63% over the next 4 weeks); 0 of 69 walk-forward long/flat rules beat scaled
buy-and-hold. The academic record agrees (Sanders, Irwin & Merrin 2009; Wang 2003 — standard references, not live-verified),
and our NSE analogue (`reports/fii_positioning/FINDINGS.md`) failed the same way. What the COT does do, strongly and stably,
is **describe the week that just ended** (Δ fund net vs the week's move: Spearman +0.65, stable by sub-period, next week
−0.02). So: PUBLISH-CONTEXT; the `p.crowd` gauge is worded "crowdedness, not a signal" and never coloured; nothing on the
page sizes or times a trade on it.

## 5.8 The rupee, duty and policy (the Indian layer)

**[B]** Indian gold = world gold × rupee + duty. The rupee is set by RBI policy, oil, flows and the dollar; duty is set
by the Finance Ministry in the Budget (1 Feb) and occasionally between budgets. Both can move MCX gold with COMEX flat.

**[P]** Rupee drivers to watch: USD/INR spot and the FBIL reference rate (13:30 IST; fbil.org.in verified 200), RBI
intervention (WSS weekly: reserves, forward book), oil (India's import bill), FPI flows (already in MKT). Duty history:
10% (2013) → 12.5% (2019) → 15% incl. AIDC (Jul 2022) → 6% (23 Jul 2024) → **15% (BCD 10% + AIDC 5%) from 13 May 2026,
Notification 16/2026-Customs** (MCX June gold rose 6–7% that day; Budget Feb 2026 had left it unchanged). The primary CBIC
page is unreadable to scripts, so the owner confirms the rate and the fortnightly tariff-value practice in a browser (PLAN
O-3); Budget 1 Feb 2027 can change it again. A duty change is the one scheduled event where MCX gaps *against* COMEX. §7.5 has the playbook. Seasonality:
Dhanteras/Diwali (Oct–Nov), weddings (Nov–Jan, Apr–May), Akshaya Tritiya (Apr/May); the premium/discount responds, the
world price barely does (**context only**; no study).

**[APP]** USD/INR on the GOLD header strip and `mc.drivers`; the FBIL rate stored daily (`USDINR_FBIL`); the duty as a dated
constant (`GOLD_IMPORT_DUTY_PCT`, `DUTY_HISTORY`) printed on `ph.ladder`; duty steps annotated on `ph.india`.

## 5.9 Regimes 2001–2025: what drove each

**[B]** Gold has had five different "reasons" in 25 years — the dollar and real yields, then rising yields, then a range,
then QE, then central banks. Each regime's rule stops working in the next one; the table shows what drove each.

**[P]** The regimes, with what the data looked like:
| Period | Price path ($/oz, LBMA PM approx.) | Dominant drivers | What the data looked like |
|---|---|---|---|
| 2001–2011 | $256 (Apr 2001) → $1,895 (Sep 2011; $1,921 intraday) | dollar bear 2002–08, real yields falling, GFC + QE1/QE2, ETF era (GLD Nov 2004), China/India demand, central banks turn net buyers (2010), miners de-hedge | MM net long builds to records 2011; ETFs +2,000 t; backwardation scare Nov 2008 |
| 2011–2015 | → $1,046 (Dec 2015) | real yields rise (2013 taper tantrum: gold −28% in 2013, the worst year since 1981), dollar bull 2014–15, ETF outflows (−880 t in 2013), Fed lift-off Dec 2015 | MM net short episodes (2013, 2015); Chinese/Indian physical buying on dips (SGE premium spikes); India duty to 10% and 80:20 rule |
| 2016–2019 | $1,050–$1,550 range; breakout Jun 2019 | Fed hikes 2016–18 cap it; 2019 Fed pivot, $17 trn negative-yielding debt, trade war | MM swings ±200k; central banks 650 t/yr |
| 2020–2021 | $1,450 (Mar 2020 liquidity crash) → $2,075 (Aug 2020) → ~$1,800 chop (2021) | real yields to −1.1%, QE4, ETF record +877 t, EFP blow-out (bar logistics); 2021 real yields rise, ETF outflows | April 2020: 4GC contract; COMEX stocks 8 → 38 Moz |
| 2022–2025 | 2022 flat (~$1,800); 2023 +13% ($2,063); 2024 +27% ($2,620); 2025 $3,000 (Mar), $3,500 (Apr), $4,000 (Oct), record ≈ $4,380 then a ~6% one-day washout (late Oct 2025) | fastest Fed hikes ever **but** central banks > 1,000 t/yr after the Russian reserve freeze; PBoC streak; geopolitics; US tariff shock Apr 2025; India duty cut Jul 2024 (MCX −5–6% that day); ETF inflows resume 2024–25 | the real-yield level link breaks; MM net long peaks ≈ 219k (3-yr max in our CFTC pull); other reportables grow into a second structural long; EFP/warehouse episode Jan–Feb 2025 |
| 2026 | read from CHRT / WEI; this document's knowledge ends June 2026 | — | our pull: MM net fell from 144,747 (52-wk max) to 104,206 by 20 Oct 2026 while gold ≈ $4,000; USD/INR ≈ 95; MCX premium 18% |

**[P]** Reading rule: the driver of the **next** regime is the one the current regime's rule ignores. In 2026 the real-yield
rule says gold is too high; the central-bank rule says yields do not matter; the positioning rule says the crowd is
leaving. A panel that shows all three with history is worth more than any one of them.

---

# PART 6 — Reading the data

## 6.1 The Commitments of Traders (COT) report

**[B]** Every Friday evening (US time) the CFTC, the US futures regulator, publishes who held COMEX gold futures as of the
previous Tuesday: commercial hedgers, big speculative funds, and small traders, long and short. It is the only public
window on *who* is positioned in gold. It is a week old when you read it and it covers COMEX only, not London, Shanghai
or MCX. The page sums the week up in one label: the larger of the two fund moves names it — and when price fell while
funds still added more longs than shorts, the label is "funds bought the dip".

**[P]** Anatomy, using the actual 20 Oct 2026 legacy block (CFTC short format, `cftc.gov/dea/futures/deacmxsf.htm`,
verified 200):
```
GOLD - COMMODITY EXCHANGE INC.                                       Code-088691
FUTURES ONLY POSITIONS AS OF 10/20/26
      NON-COMMERCIAL      |   COMMERCIAL    |      TOTAL      | NONREPORTABLE
  LONG  | SHORT  |SPREADS |  LONG  | SHORT  |  LONG  | SHORT  |  LONG  | SHORT
(CONTRACTS OF 100 TROY OUNCES)                       OPEN INTEREST:      402,279
COMMITMENTS
 237,142   37,277   54,199   59,531  295,113  350,872  386,589   51,407   15,690
CHANGES FROM 10/13/26 (CHANGE IN OPEN INTEREST:      5,934)
  -8,158     -144    8,304    5,112   -1,837    5,258    6,323      676     -389
PERCENT OF OPEN INTEREST FOR EACH CATEGORY OF TRADERS
    58.9      9.3     13.5     14.8     73.4     87.2     96.1     12.8      3.9
NUMBER OF TRADERS IN EACH CATEGORY (TOTAL TRADERS:      288)
     158       59       69       53       42      241      143
```

**[P]** Line by line:
- **Code 088691** = COMEX gold (100 oz). **Micro gold is a separate line (088695)**; do not add them (10 oz each) without
  scaling by 0.1.
- **Open interest 402,279** contracts × 100 oz = 40.2 Moz ≈ 1,251 t (≈ 1/3 of annual supply, ≈ 4 months of mine output).
  "Futures only": there is a second table "futures and options combined" (options delta-adjusted; 20 Oct 2026 OI
  532,443). Use futures-only for positioning, combined for crowding.
- **Legacy categories**: *Non-commercial* = speculators above the reporting level (gold: 200 contracts); *commercial* =
  hedgers; *non-reportable* = everyone below the level (retail + small pros). Spreads = positions held long in one month
  and short in another (relative value, roll).
- **Identity**: long sum = short sum = OI: 237,142 + 54,199 + 59,531 + 51,407 = 402,279 ✓. Any net you compute must
  sum to zero across categories (§4.1 does).
- **Changes** are week over week (Tuesday to Tuesday). Here non-commercial longs −8,158 while spreads +8,304 and OI
  +5,934: positions moved *from outright to spread* (roll footprint, GCZ26 FND 30 Nov), not a liquidation. Reading
  changes without the spread column is the commonest COT error.
- **% of OI** tells you crowding; **number of traders** tells you breadth (158 reportable longs vs 59 shorts; a rally on
  a rising count is broad, on a falling count is concentrated).
- **Disaggregated** report (same page family, `other_lf.htm`, verified 200): splits commercial into **Producer/Merchant/
  Processor/User** (miners, refiners, jewellers, physical dealers) and **Swap Dealers** (banks hedging OTC swaps); splits
  non-commercial into **Managed Money** (CTAs, CPOs, hedge funds) and **Other Reportables**. 20 Oct 2026, futures only:
  PM 19,715 L / 34,498 S; SD 17,737 L / 238,536 S / 22,079 spread; MM 120,970 L / 16,764 S / 38,634 spread (78 long
  traders, 25 short); OR 116,172 L / 20,513 S / 15,565 spread; NR 51,407 L / 15,690 S. Changes: MM long −3,777, MM short
  −894 (longs leaving and shorts covering at once: a quiet de-grossing, not a directional bet); PM short −2,325 (hedgers
  lifting hedges into a dip: supportive); SD long +3,761.
- **Concentration**: top-4 traders' gross share: long 20.4%, short 37.8%. The short side of gold is always concentrated
  (a few banks); a rising short concentration with falling price is "the banks are pressing", with rising price it is
  "the banks are being squeezed" — context only.

**[P]** **Derived metrics**
1. **Net position** per category: `net = long − short` (spreads excluded). MM net +104,206 (20 Oct 2026).
2. **Net as % of OI**: 104,206 / 402,279 = 25.9%.
3. **COT index** (the "stochastic" of positioning): `100 × (net − min_N) / (max_N − min_N)` over N weeks (26, 52, 156).
   Worked, from our 160-week pull (`cot_gold_mm_history.csv`): 52-week min 89,752, max 144,747 → **(104,206 − 89,752) /
   (144,747 − 89,752) = 26.3**; 3-year (156-week) range 34,176 → 219,029 gives **37.9**. Reading: managed money is in the
   lower third of its 1-year range after five straight weekly declines (133,116 on 15 Sep → 104,206), with gold still near
   $4,000: speculators have been *leaving a rising/flat market*, which is the opposite of a crowded top.
4. **Weekly change in net** and its z-score over 52 weeks (a ±2σ week is a positioning event).
5. **Long/short ratio** (MM): 120,970 / 16,764 = 7.2 (very long-skewed; above 10 is rare).
6. **"Who closed what"** (the owner's words): per category, `Δlong` and `Δshort` with signs: closed longs = negative
   Δlong; closed shorts (short covering) = negative Δshort; new longs = +Δlong; new shorts = +Δshort. The 20 Oct 2026
   row: MM closed 3,777 longs and covered 894 shorts; producers covered 2,325 shorts and added 1,329 longs; swap
   dealers added 3,761 longs and 466 shorts; other reportables closed 4,381 longs (120,553 → 116,172) and added 750 shorts.
7. **Fund-driver label** (`p.hero`; the HEALTH verdict's H3 clause; WEEKLY `w.whodid`): the larger of the two managed-money
   legs names the week — one rule, `services/data-service/gold/driver_rule.py`, mirrored by ui-api. ΔL / ΔS are the w/w
   changes in managed-money long / short contracts, the week's direction is the Tue→Tue price change. Down-week: `long
   liquidation` if ΔL < 0 and |ΔL| ≥ |ΔS|; `new shorts` if ΔS > 0 and ΔS ≥ |ΔL|; else `funds bought the dip` (the bigger leg
   moved against the price: net length added). Up-week, mirrored: `short covering` if ΔS < 0 and |ΔS| ≥ |ΔL|; `new longs`
   if ΔL > 0 and ΔL ≥ |ΔS|; else `funds sold into it` (net length cut). Ties go to the leg that moves with the price.
   Narration of the week that ended (G-STUDY §5.2: right ≈ 3 weeks in 4 as narration), never a forecast. The 27 Oct 2026
   week — price −1.64 %, +1,538 longs, +182 shorts, net +1,356 — reads "funds bought the dip" (ΔS 182 < ΔL 1,538); the
   earlier rule, which tested the sign of ΔS before its size, called it "new shorts" (C-TRADER-3 / C-BEGINNER-1, fixed
   5 Nov 2026).

**[P]** **Patterns, in the data** — the table:
| Pattern | Price | MM long | MM short | OI | Usual meaning |
|---|---|---|---|---|---|
| Fresh long build | ↑ | ↑ | flat | ↑ | trend being bought; healthy while traders-count rises |
| **Short-covering rally** | ↑ | flat/↓ | **↓ sharply** | ↓ | shorts forced out; rally has no new buyers → fades unless longs follow next week (Mar 2024 start: MM short fell from ~90k while longs rose: that one *did* get followed) |
| Long liquidation | ↓ | ↓ sharply | flat | ↓ | crowded longs leaving (late Oct 2025 washout) |
| Short build | ↓ | flat | ↑ | ↑ | new bets against; sets up the next covering rally if price turns |
| De-grossing | flat | ↓ | ↓ | ↓ | risk-off in funds (Oct 2026 weeks) |
| Roll footprint | any | ↓ | ↓ | spreads ↑ | ignore; look again after FND |

**[P]** **Timing in IST**: data as of Tuesday close; released **Friday 15:30 ET = Saturday 01:00 IST (US DST) / 02:00 IST (from
7 Nov 2026 onward, US standard time)**; so the first MCX session that can trade it is Monday 09:00 — six days after the
data. Federal holidays shift releases to Monday (the CFTC release-schedule page, verified 200, lists them; the page's
date text is rendered in JavaScript, so parse the table in a browser or hard-code the holiday shifts).

**[P]** **Access**: free, no key. Socrata API `publicreporting.cftc.gov/resource/72hh-3qpy.json` (disaggregated futures-only),
`kh3c-gbw2` (disaggregated combined), `6dca-aqww` (legacy futures-only); filter
`market_and_exchange_names='GOLD - COMMODITY EXCHANGE INC.'`; JSON, ~1.3 s, 186 fields, verified 26 Oct 2026 with latest
`report_date_as_yyyy_mm_dd = 2026-10-20`. History zips by year (`fut_disagg_txt_2026.zip`, 2.0 MB, verified). An app
token is optional (higher rate limits). Terms: US government data, public domain.

**[P]** **Pitfalls** (the tooltip list): (1) Tuesday data read on Monday; (2) spreads ≠ direction; (3) micro gold separate;
(4) futures-only vs combined; (5) reporting-level changes shift history; (6) the categories are self-declared on CFTC
Form 40 — a bank's prop desk can sit in "swap dealer"; (7) COMEX ≠ the world: LBMA OTC is 5–10× larger and has no COT;
(8) a record net long is only a record until the next one (2020, 2024, 2025 all set records before rising further).

**[P]** **Evidence**: §5.7 — context only. **G-STUDY ran (26 Oct 2026, `reports/gold_program/G-STUDY/FINDINGS.md`)**: 1,063 reports 2006→2026, signals dated at
the Friday release, entry the next session, Newey-West, 0.15% costs. **FAIL as a forecast** at 1/4/13 weeks for every
metric (net, % OI, COT index, z, 4-week change, commercials, small specs, OI, options-only, GLD Δ, real-yield Δ, DXY Δ);
0 of 69 walk-forward rules beat scaled buy-and-hold. **PASS as description**: the same-week Δ fund net vs price Spearman is
+0.65. Hence the panel's label — *explains the week, does not forecast* — and no COT alert, rule or colour anywhere.

**[APP]** GOLD › POSITIONING `p.hero` (net, the change in words, the fund-driver label), `p.whois` (who is long / short,
closed / covered chips), `p.history`, `p.crowd` (COT index, z-scores, a percentile over the window it names — never
coloured), `p.drawer` (trader counts, concentration, micro gold, the options line, the raw block); the weekly "who did
what" line is echoed on WEEKLY `w.whodid` and in the HEALTH verdict's H3 clause. Micro-copy §8.2.2.

## 6.2 Daily open interest with price: the four quadrants

**[B]** Open interest (OI) is the number of contracts alive. Price and OI together say whether a move is being made by
new money entering or old money leaving. Rising price with rising OI = new buyers; rising price with falling OI = shorts
escaping; falling price with rising OI = new sellers; falling price with falling OI = longs giving up.

**[P]** The quadrant map (the NSE vocabulary the terminal already uses on DERV):

| ΔPrice | ΔOI | Name | Who | Confidence rule |
|---|---|---|---|---|
| + | + | **Long build-up** | new longs vs new shorts; longs winning | strongest with rising volume and rising number of traders (COT) |
| + | − | **Short covering** | shorts closing; no new conviction | fades unless OI turns up within days |
| − | + | **Short build-up** | new shorts vs new longs; shorts winning | strongest into a known event (FOMC, Budget) |
| − | − | **Long unwinding** | longs closing | typical of post-record washouts |

**[P]** Rules: (1) use **total OI across all months** (sum of contracts) — single-month OI is destroyed by the roll; (2) compare
to the 20-day average ΔOI, not raw; (3) expiry days (MCX 5th, COMEX LTD) drop OI mechanically; (4) for MCX, OI per
contract comes from the exchange bhavcopy (blocked for bots; browser/broker) or ICICI's master (yesterday's OI only, no
history); for COMEX, CME's daily bulletin / volume-OI page (browser only; the CFTC COT carries weekly total OI as a
free fallback); (5) the quadrant is a **description**, not a forecast — the DERV page's own evidence standard applies.

**[APP]** GOLD › DAILY `d.quadrant` and POSITIONING `p.daily.comex` (CME FTP, T+1; history since 2014 once the backfill
lands) / `p.daily.mcx` (ICICI master at 07:35; history since the job started). A day whose OI file has not landed has no
label yet (the API sends none; T+1); roll and expiry days are greyed `mechanical`. PUBLISH-CONTEXT.

## 6.3 COMEX warehouse stocks

**[B]** COMEX publishes every day how much gold sits in its approved New York vaults and how much of it is "registered"
(has a warehouse receipt and can be delivered against a futures contract). Metal flowing in means someone wants
deliverable gold in New York; registered metal rising means more inventory is ready for delivery.

**[P]** Categories: **Registered** (warrant issued; deliverable), **Eligible** (meets spec, stored, no warrant — can be
registered in a day), **Pledged** (registered metal posted as clearing collateral; reported separately since 2020 — check
the report footnote for whether it is netted). `Total = registered + eligible`. Metrics: registered/OI coverage (`registered
oz / (OI × 100)`: 20 Oct 2026 OI = 40.2 Moz; a typical registered stock of 15–25 Moz gives 40–60% "coverage" — social
media calls the inverse "owners per ounce"; **deliveries are ≈ 1–3% of OI per month, so coverage is context only**),
daily net inflow (tonnes), and the **delivery notices** report (first-notice-day tallies) which is the real physical
demand on COMEX. Episodes: Mar–Jul 2020 (8 → 38 Moz as banks shipped metal to cover EFP shorts), Jan–Feb 2025 (to > 40 Moz
on tariff fears), outflows thereafter as the EFP normalised.
Access: `cmegroup.com/delivery_reports/Gold_Stocks.xls` — **403 for non-browser clients** (26 Oct 2026); readable in a
browser; CME's data terms restrict redistribution of real-time data but the warehouse report is public. UNVERIFIED as a
feed from this machine.

**[APP]** GOLD › PHYSICAL `ph.comex.stocks`: link-only tiles until the owner resolves CME's block (O-2); the daily
per-product OI and the EFP prints come from the CME FTP instead.

## 6.4 ETF holdings and flows

**[B]** Gold ETFs own real bars in a vault: when money comes in they buy bars, when it leaves they sell. Their tonnage is
published daily, so it is the simplest daily read of Western investors — and it moves *with* the price, not ahead of it.

**[P]** See §5.4 for the evidence. Read: **tonnes, Δtonnes (1d/5d/20d), flows in $ (WGC)**, and the *divergence* between price and
tonnes (price up / tonnes down in 2022–23 = non-Western buying; price flat / tonnes up = Western accumulation into
weakness). Pitfall: GLD's daily number is at the US close; Indian ETF AUM (AMFI) is monthly and in ₹ (includes price
effect — convert to tonnes via WGC).

**[APP]** GOLD › PHYSICAL `ph.etf`, the ETF tile on `h.gauges`, the GLD Δ t column on `w.table`; micro-copy §8.2.5.

## 6.5 LBMA trade data and London vault holdings (the OTC window)

**[B]** London is where most gold changes hands, between banks, in private. There is no report of who is long or short
there — only how much traded each week and how much metal sits in London vaults each month. Activity and stock, never
positions.

**[P]** Read: weekly turnover ($ bn and Moz) — rising turnover with rising price = active two-way institutional
market; vault tonnes monthly (9,821 t end-Sep 2026, +1.96% m/m) — a rising London stock while COMEX stocks fall = metal
returning East→West or being re-allocated; the Bank of England share (central banks' custody) in the same release. Lag: 1
month+ for vaults, 1 week for turnover. Evidence: context only; no public study links LBMA turnover to returns.

**[APP]** GOLD › PHYSICAL `ph.otc` (LBMA-i weekly turnover in $ bn, 12-week average; London vault tonnes, monthly; CME EFP
round turns). PUBLISH-CONTEXT (the WGC / LBMA rows are gated on O-1).

## 6.6 SGE premium and the Indian premium/discount

**[B]** Compare the local price (Shanghai, or India) with the world price after converting units and currency. A premium
means local buyers are paying up (demand or import friction); a discount means they are not.

**[P]** SGE: §2.3 formula, in $/oz. India: `premium_$ = (IBJA_999 ₹/10 g × 31.1035/10 ÷ USDINR) / (1 + duty) − COMEX spot`
… but the dealer premium Reuters quotes is *over the duty-paid official price* in $/oz (−$50 to +$20 typical; −$14 → +$3
through Oct 2026); the old overlay's **implied premium** (18.0% on 26 Oct 2026) was a duty-inclusive quantity and is now
split into the dated 15% duty and the **MCX basis vs duty-paid landed** (+3.1% that morning, ≈ 1% of it carry). Three
definitions, three panels (`ph.ladder`, `ph.india`, `ph.shanghai`); never mix them, and sample both legs at the same minute
(NY close vs the IBJA afternoon fix gave a spurious +0.9%, G-INDIA §5.3; SGE PM vs LBMA PM are 7 hours apart). Reading: a widening Indian discount into Dhanteras is a demand failure; a premium with a weak
rupee is import-channel stress; a jump on a Budget day is duty. Evidence: context only.

**[APP]** `ph.ladder` (the stack, live for the first three bars), `ph.india` (IBJA premium and MCX basis history with the
duty steps), `ph.shanghai` (SGE PM vs London PM / COMEX at 14:15 Beijing, both timestamps shown); IBJA AM/PM and the SGE
daily table are stored by the 13:45 / 16:10 / 18:10 jobs, so the history starts the day they start.

## 6.7 Gold/silver ratio

**[B]** How many ounces of silver buy one ounce of gold. Around 60–80 for most of the last 20 years; above 90 silver is
cheap relative to gold (deflation/risk-off fear); below 60 silver is expensive (reflation, industrial boom).

**[P]** `GSR = gold $/oz ÷ silver $/oz`. Range since 2000: ≈ 32 (Apr 2011) to ≈ 125 (Mar 2020). Silver's beta to gold ≈
1.5–2 with an industrial component (solar, electronics); the ratio trends for years, so "extreme" means vs a 2–3 year
window. Trade expression: ratio spread (long one, short the other, dollar-neutral) — on MCX via GOLD/SILVER contracts
(SILVER 30 kg lot). Evidence: mean reversion at multi-year horizons (context only; no citation we could verify live).

**[APP]** GOLD › MACRO `mc.context` (gold/silver and gold/platinum with percentiles over the window they name).

## 6.8 Real yield, breakeven, dollar: reading the driver table

**[B]** The driver tiles say whether each input helped or hurt gold *over the window shown* — a description of what just
happened, not a forecast of tonight. Falling real yields and a falling dollar are "supportive"; rising ones are
"headwind".

**[P]** `mc.drivers` signs each row by its change over the window (supportive / headwind, the rule printed beside the
tag) and shows the 60-day correlation with gold's daily change. Correct reading: these rows explain the move that
happened; they do not forecast the next one. The level (percentile over 1 year) is there for *regime*, not timing. The
T+1 lag on DFII10 is printed as the data's date; the dollar tile names the series it uses (DXY bars, or FRED's broad
index DTWEXBGS with its lag).

**[APP]** GOLD › MACRO `mc.drivers`, `mc.health`; the real-yield and dollar tiles on `h.gauges`.

## 6.9 Central-bank data

**[B]** Central banks report their gold holdings monthly, one to two months late. China's monthly number (around the
7th) — and whether it is still buying — is the one the market reacts to; India's shows up as a rupee value every Friday.

**[P]** Monthly tonnes by country (WGC/IMF, 1–2 month lag), PBoC monthly (~7th), RBI weekly $ value (WSS, verified 200; tonnes
only half-yearly). Reading: streaks (PBoC buying 18 straight months 2022–24, pause May 2024, resume Nov 2024) are
headline events; the annual total vs the 1,000 t line is the regime gauge.

**[APP]** GOLD › PHYSICAL `ph.official` (IMF ounces shown as Moz and tonnes, each with its data month; the PBoC streak;
RBI weekly value and share), MONTHLY `m.official` (net purchases over 12 months).

## 6.10 Term structure and implied carry

**[B]** The curve is the list of prices for each future month. Normally later months cost more (contango); the page turns
each step into a yearly % so MCX and COMEX can be read on one scale, and warns when the shape is unusual.

**[P]** Read §3.3. Panel reading: plot the MCX curve (Dec/Feb/Apr) and the COMEX curve as **annualised % carry** between adjacent
months, next to SOFR and the INR–USD rate gap; a COMEX carry above SOFR + storage = stress (negative implied lease);
MCX carry far below COMEX carry + rate gap into a Budget = duty-cut expectation.

**[APP]** GOLD › CONTRACTS `c.comex`, `c.mcx` (one carry convention per page: against the front month); the curve/roll
tile on `h.gauges` and the verdict's H5 clause.

## 6.11 Volatility: GVZ, realised, ATR in rupees

**[B]** Volatility is the size of typical daily moves. In gold it is quoted three ways: implied (what options expect:
GVZ), realised (what happened: the standard deviation of daily returns), and ATR (the average daily range in price
units, which is what a stop-loss needs).

**[P]** GVZ (Cboe Gold ETF Volatility Index on GLD options; Yahoo `^GVZ`, free, delayed; 429 for this machine at the time
of writing): normal 14–20, stress > 30. Realised: `σ_daily = stdev(ln returns, 20d)`; annualise × √252. ATR(14) in
₹/10 g: at 1.2% daily range and ₹1,46,000 that is ≈ ₹1,750 (26 Oct 2026; ATR14 was ₹2,820 on 5 Nov — MACRO prints today's) — the unit of every stop in §7.6. Implied minus realised
(the variance premium) is usually positive; a negative gap after a shock = options are cheap vs what is happening.

**[APP]** GOLD › MACRO `mc.move` (GVZ → a 1σ day in %, $/oz, ₹/10 g and ₹ per lot per family; realised 20-day vol; ATR14
in rupees).

---

# PART 7 — Advanced

## 7.1 Carry, GOFO and lease rates: what died and what replaced it

**[B]** Gold can be lent, like money. The interest a borrower pays in gold is the *lease rate*. Until 2015 the London
banks published a benchmark (GOFO) that let anyone compute it; they stopped, and today you have to infer it from futures
prices.

**[P]** GOFO (Gold Forward Offered Rate) = the rate at which contributing banks would lend gold on swap against US
dollars; `lease ≈ LIBOR − GOFO`. LBMA **discontinued GOFO on 30 January 2015** (benchmark-regulation burden after the
LIBOR scandal, shrinking contributor panel). Replacements: (a) **implied lease from the futures curve**:
`lease_implied ≈ r_USD − [ln(F2/F1) × 365/days]` (storage ignored); (b) bullion-bank OTC swap quotes (not public);
(c) Bloomberg/LSEG derived curves (paid); (d) the SGE Au(T+D) deferral fee (§2.3) as China's lease signal. A **negative
GOFO / high lease rate** (2013, Jan–Feb 2025) = physical tightness (longs willing to pay to hold metal now). Pitfall:
the implied number is noisy on the front spread in roll weeks; use the 2nd/3rd month pair.

**[APP]** GOLD › CONTRACTS `c.comex` (implied lease ≈ SOFR − COMEX carry, one number).

## 7.2 Options: skew, risk reversals, what gold's smile says

**[B]** Options prices reveal what the market fears. If calls cost more than equally-distant puts, the market pays for
upside protection or upside bets — common in gold, unlike stocks where puts cost more.

**[P]** `RR25 = IV(25Δ call) − IV(25Δ put)`; gold's RR25 is usually **positive** (call skew) in bull/crisis phases
(2020, 2024–25) and flips negative in liquidation phases (2013, late 2025 washout). Butterfly `BF25 = (IV25c + IV25p)/2 −
ATM` measures tail demand. GVZ is the ATM proxy. COMEX OG options: American, exercise into GC; weekly expiries. MCX
GOLD/GOLDM options: European, cash-settled into a *futures position* at expiry (§2.4 pitfall). Vol surface data is paid
(CME, Bloomberg); GVZ is the free scalar. Use: when GVZ spikes and RR flips negative on a down day, longs are buying
puts = capitulation footprint (context only).

**[APP]** OSTR (options strategy builder) exists for NSE; gold options are out of scope for the paper ticket. LEARN only.

## 7.3 Term-structure trades

**[B]** Instead of betting on the price, bet on the gap between two months. Buying the far month and selling the near
one profits if the curve steepens (carry rises); the reverse profits if the front tightens (shortage) or a duty cut is
priced into the far month.

**[P]** MCX calendar spread Dec/Feb: fair = carry (INR rate − lease + storage) × 2/12; margin benefit makes it
capital-light; P&L per ₹1 of spread = ₹100 per lot pair. Drivers: RBI/Fed rate gap, Budget duty expectations (short the
spread — short Feb vs long Dec — ahead of an expected duty cut; the Feb-27 contract spans 1 Feb 2027), physical tightness
(long front). COMEX: the Dec/Feb spread vs SOFR is the cleanest "implied lease" trade; retail rarely has the fee
structure for it. Evidence: context only; the carry itself is arithmetic, the *change* in carry is the bet.

## 7.4 Cross-exchange: MCX vs COMEX, duty, rupee, timing

**[B]** You cannot arbitrage MCX against COMEX by buying one and selling the other: the gap is made of duty, GST, the
rupee and shipping rules, not mispricing. What you *can* do is understand that an MCX gold position is three bets at
once, and hedge the ones you do not want.

**[P]** Decomposition (26 Oct 2026): `MCX_fair = COMEX × USDINR × 10/31.1035 × 0.995 × (1 + duty) × (1 + local premium) ×
(1 + carry_adj)`. Hedging the rupee: one GOLD lot ≈ 32.15 oz × $4,004 ≈ **$128,700 ≈ 129 USD/INR futures ($1,000 each,
NSE/BSE currency segment, 09:00–17:00 IST)**; a GOLDM lot ≈ 13 lots. Long GOLD + short 129 USDINR futures ≈ long gold in
dollars, financed in rupees (you keep the INR–USD rate gap as cost: that is the covered-interest cost, ≈ the MCX
contango excess). Timing: MCX trades 14.5 h, COMEX 23 h; every MCX open is a gap trade against 8.5 hours of COMEX
(the Pre-Open desk); the currency segment closes at 17:00 while MCX runs to 23:30 — **the rupee hedge is off for the
evening session** (offshore NDF moves it; the app shows `INR=X` as the proxy). Duty: §5.8, §7.5.

**[APP]** `ph.ladder` and `mc.kgx` (with the rupee leg) compute the pieces; the MCXG paper ticket carries
`hedge_usdinr_lots`, `max_lots_at_risk_pct`, `atr14_rupees` and the dated NRML margin.

## 7.5 Event playbooks (IST; US winter times apply from 2 Nov 2026)

**[B]** The scheduled moments that move gold, in Indian time: US data lands in the MCX evening and can be traded; the Fed
decides after MCX closes in winter, so it arrives as a gap at 09:00; the Budget can change the duty in a minute. Know
which is which before holding a position through it.

**[P]** The playbooks, event by event:
| Event | When (IST) | What moves first | Playbook | Data to check after |
|---|---|---|---|---|
| **FOMC** statement + SEP | 23:30 (DST) / 00:30; presser +30 min | real yields and DXY → COMEX within seconds; MCX live until 23:30/23:55 so the move hits during or just after MCX close | half size into it; never hold through it with less than 3-ATR cash headroom; the *second* move (presser) often reverses the first | DFII10 next day, COT the following Friday |
| **US CPI** | 18:00 (DST) / 19:00, 2nd week | breakeven → real yield → gold within a minute | MCX evening session is open: expect a ₹1,000–3,000 (0.7–2%) swing in GOLD; bands can lock at ±3% | T10YIE, DFII10 |
| **NFP** | first Friday 18:00 / 19:00 | nominal yields, DXY | as CPI; Friday evening liquidity on MCX thins after 21:00 | — |
| **COT release** | Sat 01:00 / 02:00 | nothing (markets closed) | read Saturday; plan Monday | §6.1 |
| **Union Budget** | 1 Feb, 11:00 | **duty**: MCX gaps vs COMEX (23 Jul 2024: −5–6% in minutes) | no new MCX positions through the speech unless the rupee leg is hedged and the duty call is explicit; the Feb/Apr spread is the cleaner expression | CBIC notification, overlay premium |
| **RBI MPC** | ~10:00, bi-monthly | USD/INR | rupee move × ₹1,539/₹1 per 10 g | FBIL 13:30 |
| **India CPI / trade data** | ~17:30 (12th) / ~16:00 (15th) | rupee, gold-import headlines | import tonnage drives the premium/discount narrative | DGCI&S (tradestat, verified 200, browser) |
| **PBoC reserves** | ~7th, during Asian hours | COMEX in Asia; SGE premium | a resumed streak is bought; a pause is sold for a day | WGC central-bank table |
| **COMEX FND / LTD** | 30 Nov 2026 / ≈ 29 Dec 2026 (Dec-26) | OI migration, EFP | hold the MCX month that matches the *new* COMEX active month | CME pace-of-roll |
| **MCX expiry / tender** | 5th (GOLD/GOLDM), month-end (PETAL/GUINEA) | front liquidity dies; delivery margins rise | be out before the broker's cut-off (owner action: confirm ICICI's) | specs `observed_expiries` |
| **Dhanteras / Diwali / Akshaya Tritiya** | 6–8 Nov 2026; Apr/May | Indian premium, volumes; MCX Muhurat session Sun 8 Nov evening | demand folklore; no world-price effect; the premium is the trade | IBJA basis |
| **Chinese Golden Week** (1–7 Oct) / **Lunar New Year** | SGE closed | thin Asian hours; London–NY dominate | reduce size in the 03:30–09:00 IST window | SGE premium on reopen |
| **UK / US holidays** | LBMA closed → no auction; CME may be open (Globex) | thin liquidity, no fix | avoid resting orders at round numbers | — |
| **Geopolitical shock** | any | gold ↑ then often ↓ (liquidation), DXY ↑ | §5.5: first move is noise; wait for the real-yield read | event-risk flag |

## 7.6 Position sizing for a rupee account on MCX

**[B]** Decide how much money you are willing to lose on one trade (say 1% of the account). Divide that by how much one
lot loses if your stop is hit. That is your lot count — often zero for the big contract, which is the honest answer.

**[P]**

```
risk_budget      = account × risk_pct                       (₹10,00,000 × 1% = ₹10,000)
stop_distance    = k × ATR14 (price units, ₹ per quote unit) (1.5 × ₹1,750 ≈ ₹2,600 per 10 g on GOLD/GOLDM)
risk_per_lot     = stop_distance × multiplier               (GOLD ₹2.6 lakh; GOLDM ₹26,000; GUINEA ≈ ₹2,100; PETAL ≈ ₹262)
lots             = floor(risk_budget / risk_per_lot)        (GOLD 0; GOLDM 0; GUINEA 4; PETAL 38)
margin_check     = lots × margin_per_lot ≤ 35% × account    (PETAL 38 × ₹875 = ₹33,250 ✓)
headroom_check   = 3 × ATR × multiplier × lots ≤ free cash   (PETAL 38 × ₹525 = ₹20,000 ✓)
```

**[P]** Conclusions: (1) at 1% risk and a volatility stop, **one GOLDM lot needs a ≈ ₹26 lakh
account and one GOLD lot ≈ ₹2.6 crore**; (2) tightening the stop below ~1 ATR does not fix that — it converts a sizing
problem into a stop-out problem; (3) PETAL/GUINEA exist exactly for this, at the cost of thinner books; (4) the owner's
paper ticket should print `max_lots_at_risk_pct` next to `indicative_margin` — the two numbers disagree by an order of
magnitude and that disagreement *is* the lesson. Vol-targeting variant: `notional = (target_vol / realised_vol) ×
account` (e.g. 10% target / 18% realised × ₹10 lakh = ₹5.6 lakh notional ≈ 38 g ≈ 38 PETAL lots — the same answer by a
different road, which is reassuring).

**[P]** Scenario table at 26 Oct 2026 settlements (₹ P&L per lot):
| Move | GOLD (×100 @ 1,46,079) | GOLDM (×10 @ 1,44,584) | GUINEA (×1 @ 1,16,648) | PETAL (×1 @ 14,581) |
|---|---|---|---|---|
| 1% | 1,46,079 | 14,458 | 1,166 | 146 |
| 2% | 2,92,158 | 28,917 | 2,333 | 292 |
| 3% (one ±3% band) | 4,38,237 | 43,375 | 3,499 | 437 |
| 5% (Budget-day scale) | 7,30,395 (= 55% of the 9.25% margin) | 72,292 | 5,832 | 729 |

**[APP]** MCXG paper ticket: add `max_lots_at_risk_pct`, `atr14_rupees` (needs daily history), `hedge_usdinr_lots`.

## 7.7 Risk management: the rules list

**[B]** Eleven rules in plain words: size for the overnight gap, not the session; remember MCX can lock while COMEX keeps
moving; the rupee is half the trade; the duty is a policy variable; be out before tender; stay in the liquid months; keep
cash for margin calls; costs are small, leverage is not; the COT never sizes a trade; the first move on a shock is noise;
paper first.

1. **Gap risk is the main risk.** MCX misses ~8.5 h of COMEX nightly and ~58 h over a weekend. Size for the gap, not the
   session: 3 × ATR of cash headroom per lot, always.
2. **Bands lock, COMEX does not.** On a shock the ±3% band halts MCX for a cooling period while COMEX keeps printing; the
   reopen gaps. Do not rest stops inside the band on event days.
3. **Rupee is half the trade.** Know `₹ per ₹1 of USD/INR` for your position; hedge or accept it explicitly.
4. **Duty is a policy variable.** No open MCX position into 1 Feb 11:00 IST without a decision about it.
5. **Expiry and tender.** Be out before the broker's cut-off; ITM options become futures.
6. **Liquidity by contract.** GOLD and GOLDM front only for size; far months and PETAL in size are illiquid.
7. **Margins change overnight.** A special-margin circular is a cash call; keep 35% of the account free.
8. **Costs are small, leverage is not.** ≈ ₹2,445 round trip on a ₹1.44 crore lot is ≈ 24.5 ticks (5 Nov 2026; CONTRACTS prints today's); one 1% day is ≈ 1,440 ticks.
9. **Positioning extremes are context, not a rule.** G-STUDY (26 Oct 2026) found no forecasting power in the COT index at any
   horizon; size on ATR and the event calendar (§7.6, §7.5), never on the COT index.
10. **The first move on a shock is liquidation.** Wait for the real-yield read (§5.5).
11. **Paper first.** The program's posture is PAPER; the ticket records nothing and should stay that way until the
    accuracy log (Part 8, §8.8) shows the open-model is better than naive over ≥ 20 days — today it is not (3 days: model
    mean miss ₹2,496 vs naive ₹2,147, 0% within ₹300).
# PART 8 — "How to read this panel": micro-copy, panel by panel

**[P]** Format per panel: **Reads** (2–3 lines for the panel header tooltip) · **Is not** (the misreading to prevent) ·
**Updates** (cadence and lag) · **Evidence** chip — one of the four badges of PLAN §f: `signal` (a pre-registered study
PASSED as a forecast; **none today**), `context` (PASS as a description, or context-only), `arithmetic` (an identity,
cost or spec), `heuristic` (a house rule without evidence). Phase-2 pass (26 Oct 2026, B5-LEARN-DOCS): every heading now
names the GOLD panel id(s) of `PLAN.md` §a that the copy belongs to, or the page that keeps the panel (MCXG, WEI, BRF,
CMDT, ECO). The ids are what the UI keys its `?` popovers and `tooltips.json` on; `validate_learn.py` checks that every
id named here exists in the plan and that every panel in the plan has a tooltip.

## 8.0 Where each panel went (PLAN Appendix B)

**[B]** The names used when this guide was written and the panel ids the page uses now, side by side — only needed when
an older note refers to a panel by its old name.

**[P]** The map:
| G-EDU name (26 Oct 05:50) | GOLD panel id(s) / home |
|---|---|
| 8.1.1 verdict · 8.1.2 key numbers · 8.1.4 inputs | `h.open` |
| 8.1.3 gap build-up | `h.open` waterfall · `h.moved` |
| 8.1.5 context table | `mc.drivers` |
| 8.1.6 headlines | `h.headlines` |
| 8.1.7 manual checks | `ph.links` · `c.links` (four links became data) |
| 8.1.8 accuracy log | `h.accuracy` |
| 8.1.9 session clock · 8.1.10 quote · 8.1.13 ticket | MCXG (unchanged; ticket gains sizing arithmetic) |
| 8.1.11 overlay | MCXG one line · `ph.ladder` |
| 8.1.12 specs | `c.selector` (shared with MCXG) |
| 8.1.14 WEI row · 8.1.15 BRF panel · 8.1.16 CMDT board | WEI card (one extra line) · BRF one line · CMDT tile with a `GOLD ›` chip |
| 8.2.1 health strip | header strip · `h.gauges` |
| 8.2.2 COT | `p.hero` · `p.whois` · `p.crowd` · `p.drawer` |
| 8.2.3 daily OI × price | `d.quadrant` · `p.daily.comex` · `p.daily.mcx` |
| 8.2.4 warehouse | `ph.comex.stocks` |
| 8.2.5 ETF | `ph.etf` |
| 8.2.6 OTC window | `ph.otc` |
| 8.2.7 premium monitor | `ph.ladder` · `ph.india` · `ph.shanghai` |
| 8.2.8 drivers | `mc.drivers` · `mc.move` · `mc.health` |
| 8.2.9 central banks | `ph.official` · `m.official` |
| 8.2.10 term structure | `c.comex` · `c.mcx` |
| 8.2.11 chooser + calendar | `c.selector` · `c.roll` · `h.events` |
| 8.2.12 events calendar | `h.events` · `mc.calendar` (+ ECO) |
| 8.2.13 Kitco-style chart | `d.24h` · `d.3day` |
| 8.2.14 periodicity switch | the `window` param · WEEKLY / MONTHLY views |

## 8.1 Existing panels (today's surfaces, and where each one now lives)

**[B]** The panels that existed before the GOLD page — the pre-open desk, the MCXG quote and ticket, the WEI and BRF lines
— and where each one lives now. On the page every panel carries this copy as its own [B] line and its `?` popover; this
section is the reference version.

**[P]** **8.1.1 Pre-Open desk — verdict → `h.open` (verdict strip, GOLD › HEALTH; BRF keeps one line before 09:00)**
Reads: "Where MCX GOLD 'should' open given what COMEX and the rupee did since the close — arithmetic to read, not advice.
The OK / WAIT strip is a house rule (the ₹300 chase limit) that has missed by thousands of rupees on a typical scored
morning and has been worse than 'open = yesterday's settlement' so far (8.1.8)."
Is not: a direction call, and not an instruction to trade or to wait. Fair can be ₹2,000 above yesterday and the day can
still close lower.
Updates: every 60 s; the baseline (settlement) is computed once the MCX session closes and is labelled by its
**session** ("Thu 22 Oct settlement") and its source, never by the file date.
Evidence: `heuristic` — the ₹300 chase limit has **no support yet**: 7 scored days to 5 Nov 2026, 0% within ₹300, model
worse than naive (8.1.8) — and those mornings were priced off the band midpoint, which ran one MCX session stale (each
miss ≈ the previous session's gold move). The chip carries the measured miss until ≥ 20 VWAP-baseline rows say otherwise.

**[P]** **8.1.2 Key numbers (baseline, fair, expected gap, MCX now vs fair, chase limit) → `h.open`**
Reads: "Baseline = the last completed session's MCX settlement — the VWAP of its last 30 minutes of Breeze 1-minute bars
(VWAP30 PROXY), else the midpoint of the ±3% band (BAND PROXY, set around an earlier session; an amber note when the two
differ by > 0.6 %). Fair = baseline × COMEX ratio × rupee ratio. Gap = fair − baseline, also per lot (×100) and per Mini (×10)."
Is not: a prediction of the *close*; a mismatch of the COMEX month and the MCX month (both Dec today; GCZ26 → GCG27
around 25 Nov while MCX Dec runs to 4 Dec) would add carry to the gap — the symbol is printed so you can check.
Updates: 60 s. Evidence: `arithmetic`; the *usefulness* is what the accuracy log measures.

**[P]** **8.1.3 Gap build-up (COMEX part, rupee part, waterfall) → `h.open` waterfall · `h.moved`**
Reads: "How much of the expected gap is world gold and how much is the rupee. ₹36.5 per $1 on COMEX, ₹1,539 per ₹1 on
USD/INR (today's values)."
Is not: additive beyond small moves (the model is multiplicative; the split is a first-order approximation).
Updates: 60 s. Evidence: `arithmetic`.

**[P]** **8.1.4 Your inputs → `h.open` (inputs panel; triggers live in prefs `gold.triggers.v1`)** — Reads: "Override the baseline with
your broker's close; type the MCX price at the open if ICICI is not connected; chase limit and EUR/USD trigger are your
settings." Evidence: n/a.

**[P]** **8.1.5 Context table (DXY, EUR/USD, US 10y, silver, 10y real yield) → `mc.drivers` (GOLD › MACRO; the desk's rows go)**
Reads: "Each driver's move since the MCX close, signed for gold (falling real yields and dollar = supportive), with its
60-day correlation to gold's daily change. Explains the overnight COMEX move; does not forecast the next one."
Is not: a level signal — the real yield is 2.64% with gold at $4,000; the level relationship broke in 2022 (§5.1).
Updates: Yahoo 30–120 s; DFII10 T+1 (printed). Evidence: `context` (G-MACRO H1/H2: contemporaneous betas, no lead).

**[P]** **8.1.6 Headlines + event-risk chip → `h.headlines`** — Reads: "Last 24 h of gold / Fed / Hormuz / China / rupee headlines;
the chip counts risk words (war, strike, sanction, margin, halt…)." Is not: sentiment analysis, and not sizing advice (the
old "half size at ≥ 3" line is gone, disagreement 14). Evidence: `heuristic` (say so on the chip). The "France / OAT"
topic is dropped; the topic list is a pref.

**[P]** **8.1.7 Manual checks → `ph.links` · `c.links`** — four of the ten links became data (SGE, ETF flows, GLD, real yields), Fed
odds became `mc.fed` (Atlanta Fed), FedWatch / MCX circulars / FBIL / TradingView / Kitco moved to the two "linked"
lists, the investing.com USD/INR link was removed (403 to scripts; INR=X is in the app). Add from this document: CFTC COT
(Saturday, now a job), IBJA rate (now a job), CBIC duty/tariff value (fortnightly, owner), CME warehouse stocks (browser,
O-2). Evidence: n/a.

**[P]** **8.1.8 Accuracy log → `h.accuracy` (strip + the full table)**
Reads: "The 08:45 fair open vs the actual 09:00 open, day by day. 'Naive' = open at yesterday's settlement. Need ~20 days
before the chase limit means anything."
Is not: a judgement yet. **As of 26 Oct 2026: 4 rows, 3 with an actual open; misses +₹1,090, −₹3,518, −₹2,880; mean
₹2,496 vs naive ₹2,147; 0% within ₹300.** The 15 Oct row (baseline 1,48,450 → actual 1,47,482, fair 1,51,000) looks like
a stale baseline (the "settlement before last" case the desk warns about) — the table flags such rows (`stale_baseline`)
and keeps every input (`inputs_json`) for the audit.
Updates: daily (08:45 snapshot, 09:10 capture; holiday-aware since phase 2). Evidence: this *is* the evidence; keep it on
the page.

**[P]** **8.1.9 MCXG session clock + holidays → MCXG (unchanged)** — Reads: "OPEN/CLOSED with time to close; evening close 23:30 IST
while New York is on daylight time, 23:55 otherwise (switches 2 Nov 2026). Holidays are MCX's own: morning-only or
evening-only days exist. Muhurat Sun 8 Nov 2026: special session 14:05–14:19, trading 14:20–15:30 (MCX/TRD/590/2026)."
Is not: NSE's calendar. Evidence: n/a.

**[P]** **8.1.10 Quote (Breeze / price band / fair value) → MCXG (unchanged, honest degrade)** — Reads: "Live LTP from ICICI when the
account can serve MCX; otherwise the previous settlement (band midpoint, PROXY) and the COMEX × rupee fair value, each
labelled. 'Desk price in use' is what the ticket prices with." Is not: a fair-vs-fair premium (the overlay only computes
a premium against a *live* broker price). Evidence: n/a.

**[P]** **8.1.11 COMEX × rupee overlay → MCXG one line · `ph.ladder` (GOLD › PHYSICAL)** — Reads (MCXG line): "COMEX GCZ26 ·
₹/$ · duty-paid landed · fair · live vs fair · GOLD ›". Reads (`ph.ladder`): "COMEX → × USD/INR → landed → + duty 15%
(dated, Notification 16/2026-Customs) → duty-paid landed → IBJA premium → MCX basis and carry, each bar with its
timestamp." Is not: an arbitrage; the basis is a demand and policy variable. The old "18% implied premium" was
0.995 × 1.15 × 1.031 (§2.6) — mostly duty. Evidence: `arithmetic` (ladder); `context` (premium, basis).

**[P]** **8.1.12 Contract specs → `c.selector` (GOLD › CONTRACTS, the same component on MCXG)** — per-column tooltips: Lot "metal
per contract"; Quote "price unit — ₹ per 10 g, 8 g or 1 g"; Tick "₹1 on the quote = ₹100 / ₹10 / ₹1 per lot"; Delivery
"what you receive if you hold to expiry; 995 vs 999"; Margin "exchange NRML (Zerodha mirror, dated: 9.25% of notional on
25 Oct 2026); special and delivery margins come on top"; Cycle "bimonthly / monthly"; Next expiries "observed = ICICI
master; computed = rule (5th / month-end, previous business day if closed)". Adds GOLDTEN, the FND/LTD of the matched
COMEX month, the broker tender cut-off (owner action O-9) and a diff strip on switch.

**[P]** **8.1.13 Paper ticket → MCXG ticket (+ sizing arithmetic)** — Reads: "Notional, NRML margin (dated), tick value and round-trip
costs for N lots at the desk price. PAPER: prices the trade, sends nothing." Adds `max_lots_at_risk_pct`,
`hedge_usdinr_lots`, `atr14_rupees` (§7.6, §7.4). Is not: a broker margin statement. Nothing gold feeds the ticket's
price. Evidence: cost model from `shared/mcx_specs.py` (rates cited there).

**[P]** **8.1.14 WEI commodities row (GOLD, SILVER) → WEI card (the row + one second line + hover)** — Reads: "Yahoo continuous front
month (GC=F), delayed; day change and 1-month spark." Second line: "GOLD · verdict words · basis % · COT MM net (Δ) · next
roll · GOLD ›"; the hover is the five-number header strip. Is not: the Dec contract the desk uses — the tooltip names the
symbol difference. Nothing else moves into WEI.

**[P]** **8.1.15 BRF gold panel → BRF one line** — before 09:00 "Gold open: fair ₹… (gap …) · WAIT · verdict words · GOLD ›"; after
the captured open "Gold opened ₹… vs fair ₹… (miss ₹…) · … · GOLD ›"; on MCX holidays "Gold: MCX closed (…) · GOLD ›". The
full panel and its rotation on the NSE 09:15 clock go (G-APP finding 14).

**[P]** **8.1.16 CMDT futures board → CMDT tile with a `GOLD ›` chip** — gold/silver/copper/oil/gas continuous; the gold tile's detail
chart opens GOLD › WEEKLY; the Pre-Open desk leaves CMDT. The tape's "GOLD" quote is relabelled "GOLD GC1" (a tape
repeats quotes by design).

## 8.2 The GOLD page panels (the owner's list, under the ids the build uses)

**[B]** One entry per GOLD panel: what it reads, what it is not, how often it updates and which evidence badge it wears. A
beginner needs none of this to use the page — each panel's own [B] line says the same in one sentence; this is the audit
copy.

**[P]** **8.2.1 GOLD health strip → header strip (page-global) · `h.gauges` (GOLD › HEALTH)** — Reads: "COMEX matched-month settle
and live · USD/INR · 10-y real yield (T+1) · MCX settle (by session) · basis vs duty-paid landed · managed-money net (COT,
weekly) · MCX opens in …: the five numbers of §0 — what you are long when you buy an MCX lot. Below them, eight tiles:
TREND, REAL YIELD, DOLLAR, POSITIONING, INDIA BASIS, SHANGHAI PREMIUM, ETF HOLDINGS, CURVE/ROLL." Is not: a score; there
is no composite index because none of the inputs is a validated predictor (0 of 69 rules, G-STUDY). Updates: 60 s / T+1 /
weekly. Evidence: `context` on every tile (`arithmetic` on curve/roll).

**[P]** **8.2.2 COT positioning (weekly) → `p.hero` · `p.whois` · `p.crowd` · `p.drawer` (GOLD › POSITIONING)** — Reads: "Who held
COMEX gold futures last Tuesday: producers/merchants, swap dealers (banks), managed money (funds), other reportables,
small traders — long, short, net, change on the week in words ('closed 3,777 longs, covered 894 shorts'), the fund-driver
label (the larger of the two fund legs: 'funds bought the dip' when price fell and the net still rose), OI. Spreads are
excluded from net." Is not: this week — it is 4–6 days old, COMEX only, no London/MCX; and not a
forecast: G-STUDY (26 Oct 2026) FAILED every positioning metric at 1/4/13 weeks and PASSED it as a description of the
week (Spearman +0.65). Updates: Saturday 01:00/02:00 IST; catch-up Monday/Tuesday after holidays; STALE at 10 days.
Evidence: `context` ("explains the week — does not forecast").
Sub-copy: *Who closed what* (`p.whois`): "negative Δlong = longs closed; negative Δshort = shorts covered". *Crowdedness*
(`p.crowd`): "0 = most short in the window, 100 = most long. Crowdedness, not a signal — no forecasting power 2006–2026
(G-STUDY); never coloured." *Options overlay* (`p.drawer`, one line): "options add +4,479 to funds' net; combined OI
532,443 — no information in it (G-STUDY)".

**[P]** **8.2.3 Daily OI × price → `d.quadrant` (GOLD › DAILY) · `p.daily.comex` · `p.daily.mcx` (GOLD › POSITIONING)** — Reads:
"Price change vs open-interest change, all months summed: new longs (both up), short covering (price up, OI down), new
shorts (price down, OI up), long unwinding (both down). COMEX product OI from the CME FTP daily file (T+1, ≈15:30 IST,
history since 2014); MCX OI per contract from the ICICI master (07:35; history since the job started)." Is not: a
forecast; roll weeks and expiry days distort OI (greyed, `mechanical`); OI never says *who* — the COT does, weekly.
Evidence: `context` ("folklore until G-STUDY-2", the pre-registered daily study).

**[P]** **8.2.4 COMEX warehouse stocks → `ph.comex.stocks` (GOLD › PHYSICAL, LINK-ONLY tiles)** — Reads: "Registered (deliverable)
and eligible gold in COMEX vaults, pledged warrants; the coverage ratio with its front-month version beside it. Rising
inflow = metal wanted in New York (EFP stress)." Is not: "owners per ounce" — deliveries are 1–3% of OI a month; the
internet's "100:1" counts all months and ignores eligible. Updates: not fetched — www.cmegroup.com blocks this IP and
its terms forbid scripts; tiles link out until the owner resolves it (O-2). Evidence: `context` (no study shows stock
changes predict gold).

**[P]** **8.2.5 ETF holdings and flows → `ph.etf` (GOLD › PHYSICAL; HEALTH tile)** — Reads: "GLD tonnes daily since 2004 (display-only,
attributed) with daily changes; IAU; WGC weekly flows by region and the India tonnes; AMFI gold-ETF AUM monthly.
Divergence from price (price up, tonnes down) = non-Western buying." Is not: a leading indicator (contemporaneous; G-STUDY
4-week change t ≤ 1; G-MACRO weekly corr 0.33–0.37, ≈ 0 predictive; AMFI flows chase last month's return, G-INDIA-1).
Updates: daily ≈06:00 IST T+1 (GLD) / Monday ≈11:30 (WGC) / monthly. Evidence: `context`.

**[P]** **8.2.6 OTC window (LBMA trade turnover + London vault holdings + EFP prints) → `ph.otc`** — Reads: "The London
over-the-counter market, where most gold trades: weekly turnover (12-week average, $bn — $964 bn for the week ended 16 Oct
2026 ≈ 7,500 t gross), tonnes in London vaults (monthly, ~1 month lag; 9,821 t at end-Sep 2026) and the EFP prints
registered on COMEX (round turns, 20-day average, % of volume). There is no COT for London — this is activity and stock,
not positions." Is not: 'deals' with names; OTC counterparties are never public; CME publishes EFP volume, never the EFP
price. Updates: weekly / monthly / daily. Evidence: `context`.

**[P]** **8.2.7 Premium monitor → `ph.ladder` · `ph.india` · `ph.shanghai`** — Reads: "`ph.ladder`: the India price stack with the
duty printed and dated (15%, Notification 16/2026-Customs, 13 May 2026). `ph.india`: IBJA 999 PM vs duty-paid landed (the
dealer premium) and MCX front vs duty-paid landed (the basis, carry-adjusted beside it), history with duty steps, WGC's
weekly India premium and the Reuters survey as sanity lines. `ph.shanghai`: SGE PM (CNY/g → $/oz) vs London PM or COMEX
at 14:15 Beijing, both timestamps shown, WGC weekly China premium beside it." Is not: one number — three definitions,
three uses; a premium computed from prices seven hours apart is clock error (G-INDIA §5.3: +0.9% spurious), so each
derived number on the ladder names the clock it used (the IBJA premium at the fix minute, the MCX basis at the settlement
session) and the live bars, stamped "now", are never divided by a settlement. Updates: daily
at the IBJA fix minutes (13:45 / 18:10 jobs) and the SGE close (16:10); the first three ladder bars live. Evidence:
`arithmetic` (ladder) · `context` (premiums; no study yet — GS-P3 and GS-PREMIUM wait for history).

**[P]** **8.2.8 Drivers → `mc.drivers` · `mc.move` · `mc.health` (GOLD › MACRO)** — Reads: "The macro inputs with history and today's
percentile: 10-y real yield, 2-y, breakeven, DXY / broad dollar, USD/INR, GVZ, Brent, GLD; each tagged supportive or
headwind by its rule and its 60-day correlation. `mc.move`: GVZ → a 1σ day in %, $/oz, ₹/10 g and ₹ per lot per family;
realised vol; ATR14 ₹. `mc.health`: the rolling 1-year correlations and the betas by regime." Is not: a model. The
*level* link to gold broke in 2022 (G-MACRO H1: beta −9.9%/100 bp 2010–21, −5.0 since 2022); the dollar never stopped
working (H2: beta ≈ −1 in every regime); neither forecasts (G-STUDY). Updates: daily T+1 (FRED/Treasury), 60 s (Yahoo).
Evidence: `context` (drivers) · `arithmetic` (`mc.move`).

**[P]** **8.2.9 Central banks → `ph.official` (GOLD › PHYSICAL) · `m.official` (GOLD › MONTHLY)** — Reads: "Monthly net purchases by
country from the IMF (ounces shown as Moz and tonnes, each with its data month; 1–2 month lag; China 76.73 Moz ≈ 2,409 t
in Aug-26, +20 t/month), the PBoC
streak, RBI tonnes (half-yearly) and the weekly $ value and share (14.7% of reserves on 16 Oct 2026); the 1,000 t/yr
line." Is not: timely — it explains the regime (the 2024-26 doubling with funds *cutting* net length: the marginal buyer is
outside the COT). Updates: monthly (~25th) / weekly (Friday). Evidence: `context` (GS-P5 proposed, not yet pre-registered; honest prior FAIL as
timing).

**[P]** **8.2.10 Term structure / carry → `c.comex` · `c.mcx` (GOLD › CONTRACTS)** — Reads: "COMEX six months with last week's ghost
curve, calendar spreads, implied carry p.a. (Dec-26 → Feb-27 +$41.1 = 1.03% ≈ 3.2%/yr on settlements); MCX chain with
settle (proxy/official), band, OI, implied carry; implied lease ≈ SOFR − COMEX carry. Backwardation = shortage (COMEX) or
duty-cut expectation (MCX, into Feb)." The MCX chain is ONE session: its settles are the ICICI band midpoints of the session
the band belongs to (5 Nov 2026: the Tue 03 Nov band, with the OI at the Wed 04 Nov close), printed with that session — never
the file or request date; vs-front and carry are taken inside it. The basis under it names its own session (the latest
close's last-30-min VWAP), so the note says when the two differ. PETAL (₹/1 g) and GUINEA (₹/8 g) also print a ₹/10 g
equivalent. Is not: a yield you earn — a long pays the carry at every roll; and Yahoo's per-month price is the last trade,
not the settlement (labelled LAST TRADE until the bulletin is allowed, O-2). Updates: daily. Evidence: `arithmetic`.

**[P]** **8.2.11 Contract chooser + calendar strip → `c.selector` · `c.roll` · `h.events`** — Reads: "Which contract for which purpose
(§3.5 table, now with GOLDTEN: PETAL round trip 0.34% of notional vs GOLD 0.018%); next MCX expiries, COMEX first intent /
FND / LTD in IST, broker tender cut-off (owner, O-9), Budget, FOMC, COT release." Is not: advice on direction. Updates:
daily. Evidence: `arithmetic`.

**[P]** **8.2.12 Gold events calendar (the 'weeks, days, months' view) → `h.events` · `mc.calendar` (+ ECO)** — Reads: "Scheduled
events that move gold, in IST, with the in-session / after-close flag (US data 18:00/19:00 IST inside the MCX evening;
FOMC 23:30 / 00:30 after the close in US winter → gap risk at 09:00)." Written once into `gold_events`, read by GOLD
(`h.events`, `mc.calendar`, `c.roll`). ECO / EVTS reading the same rows (US CPI/NFP/PCE/GDP in IST and the gold-specific
rows: COT release, COMEX FND/LTD, MCX expiries, Dhanteras, Diwali/Muhurat, Akshaya Tritiya, Budget, PIB/AMFI/WSS days)
is PLAN §b's intent and **not in this release**: today ECO and EVTS do not read `gold_events`. Evidence: `arithmetic`
(dates), with the caveat that no seasonal passes both halves (G-MACRO H3, G-STUDY §4.4).

**[P]** **8.2.13 Chart (Kitco-style 24-hour with session shading) → `d.24h` · `d.3day` (GOLD › DAILY)** — Reads: "COMEX matched
month, 24 h, 1-minute line from our own stored bars, with the previous day dotted, the settlement dashed, a two-row time
axis (IST over NY), session bands Sydney/Tokyo · Shanghai · London · New York and the **MCX 09:00–23:30/23:55 bar**; the
3-day overlay beside it; the SGE Au99.99 line on the Shanghai band." Is not: Kitco's chart — Kitco's terms (verified
26 Oct 2026) allow personal, non-commercial use only and prohibit redistribution; **link, never embed or scrape.** The
bars come from one Yahoo fetcher through data-service (`gold_bars_intraday`), never from a publisher on the request path.
Evidence: `arithmetic` (it is the price).

**[P]** **8.2.14 Periodicity switch (day / week / month) → the `window` param · `w.table` · `w.grid` (GOLD › WEEKLY) · `m.physical` · `m.balance` (GOLD › MONTHLY)** — Reads: "Same series,
aggregated: daily changes, weekly (Tuesday COT weeks, `w.table`, `w.grid`), monthly (vaults, central banks, ETF monthly,
India imports, `m.physical`, `m.balance`)." Every history starts the day its job starts and the page says so ("since
27 Oct 2026"); the resampling rule (last / sum / mean) comes from the catalog. Evidence: n/a (plumbing).

## 8.3 Glossary and tooltips

**[B]** Every dotted word on the page opens the glossary; the search box also understands the page's own abbreviations
(MM, OI, FND, w/w, bp, GC1) and a dozen "start here" terms sit above the alphabet until you type.

**[P]** `glossary.json` (this folder, rebuilt 5 Nov 2026): 160 terms with `term`, `short` (≤ 200 chars, the tooltip),
`long` (the LEARN entry; empty when the short line is the whole story — the panel prints it only when it exists),
`see_also` (every reference resolves), `aliases` (272 abbreviations and page labels — MM, OI, FND, LTD, GC1, w/w, bp, pp,
Shanghai premium, India basis, funds bought the dip … — each unique and never a term's own name; the search ranks an alias
hit like the term itself) and a top-level `start_here` list of twelve terms the glossary panel pins above the alphabet
while the search box is empty. `build_glossary.py` asserts all of it; `validate_learn.py` re-checks the written file
(check 10) and has a `--selftest` with negative controls. `tooltips.json`: 259 one-liners — 203 keyed by the app's payload
field names (`basis_pct`, `duty_pct`, `rs_per_comex_dollar`, `tick_value`, `mm_net`, `cot_index_52w`, `driver_label`, …)
and 56 keyed by the panel ids of PLAN §a (`h.verdict` … `c.links`, listed under `panels`) so the UI can attach them
without parsing prose. `validate_learn.py` checks all of it against `PLAN.md` and, in the other direction, that every
field key is referenced by name in a `ui/` source file (check 9): the keys no view renders are retired from the file and
listed in `build_glossary.py` (`RETIRED_FIELD_KEYS`) for the day a view renders the field. Tooltips that state a server
rule (the fund-driver label — `driver_rule.py`, the larger leg; the 1w / 1m / 1y windows, which step back 7 / 30 / 365
calendar days to the nearest earlier session; the percentile windows; the dollar series named on its tile; the premium and
basis clocks) were re-read against the code on 5 Nov 2026.

## 8.4 The health verdict, clause by clause (the rule table the owner can audit)

**[B]** The verdict is one sentence made of short facts — how gold moved, whether the dollar or yields explain it, what
funds did, where India's price sits against imported gold, what the roll costs, what the big ETF did — each from a stored
number with a threshold. No score, no count of "supportive" items, and it ends "describes, does not predict" on purpose.

**[P]** `h.verdict` is one sentence built from thresholded clauses on stored series. Each clause the API returns carries
`rule_id`, `series_id`, `value` and `threshold`, so every word can be traced to a number. There is **no score** and no
count of "supportive" clauses: 0 of 69 walk-forward rules beat buy-and-hold (G-STUDY), so a count would read as the
forecast it cannot be. A gauge whose `state` is `stale` or `unavailable` contributes no clause (the `freshness.stale[]`
and `freshness.unavailable[]` lists name it and the tile says STALE); nothing is guessed. The table below **is**
`HEALTH_RULES` in `services/ui-api/routers/gold.py` (ui-api `/api/gold/health`), rule for rule: the code is the source,
this table follows it, and `validate_learn.py` (check 8) reads that list with `ast` and fails when the two differ.
Changing a threshold is a one-line change in that list; GOLD › LEARN renders the live clauses with their `rule_id`
directly above this text, so the two can be compared on the page.

| rule_id | Clause it produces | Series | Rule (as implemented) | `threshold` dict (verbatim) | Window |
|---|---|---|---|---|---|
| H1 | "WEAK WEEK" / "STRONG WEEK" / "FLAT WEEK" / "FIRM WEEK" / "SOFT WEEK" (DAY / MONTH when `window=D` / `M`) | `COMEX_GC_FRONT` | gold's change over the window: ≤ −2 % WEAK · ≥ +2 % STRONG · \|Δ\| < 0.5 % FLAT · else FIRM (up) / SOFT (down); then the trend sentence from the TREND gauge: the price vs its 20-d and 200-d averages ('below both averages' / 'between' / 'above both', both % printed) and the drawdown from the 52-week high — a description, no threshold of its own | `{"weak_pct": -2.0, "strong_pct": 2.0, "flat_pct": 0.5}` | D: latest close vs the previous session · W: the calendar week to date (Monday's close → latest) once the week has started, else the last 5 sessions — the clause names the span it used · M: 30 calendar days (the nearest earlier session) |
| H2 | "DOLLAR-DRIVEN" / "YIELD-DRIVEN" / "GOLD-SPECIFIC" after the H1 words; then the decomposition "gold −2.8 % over the week · of which the dollar −1.9 % · real yield +12 bp" | `DXY_CLOSE` (the KGX dollar effect) · `FRED_DFII10` | DOLLAR-DRIVEN when the dollar effect (KGX split) is ≥ 40 % of gold's move with the same sign and \|move\| ≥ 0.5 %; YIELD-DRIVEN when the 10-y real yield moved ≥ 5 bp against gold; else GOLD-SPECIFIC; no driver word at all when \|move\| < 0.5 %, and none when the dollar or the real-yield leg is unavailable (the clause then says the driver is untested and names the offline series) | `{"usd_share": 0.4, "min_move_pct": 0.5, "real_yield_bp": 5.0}` | the H1 window |
| H3 | "funds net 104,206 (−2.7 % w/w, long liquidation)" | `COT_DISAGG_F` (`gold_cot_metrics`, managed money) | managed-money net and its w/w change in % with the fund-driver label — the larger of the two fund legs (G-STUDY §5.2; "funds bought the dip" when price fell and the net still rose); printed whenever the positioning gauge is fresh | no threshold | latest report (Tuesday positions, Friday release) |
| H4 | "India basis +3.1 % vs duty-paid landed" (the 26 Oct 05:49 figure of §2.6) | `MCX_BASIS_PCT` | the contract's settlement (last-30-min VWAP, else the band of its real session), in ₹/10 g, vs the duty-paid landed price × purity/1000 (GOLD / GOLDM 995, GOLDTEN / PETAL / GUINEA 999; landed is fine gold — PM decision D1) at that session's close, or the live price vs now while a quote exists; one value per clock (duty dated); stated, not judged — no "wide" or "discount" word | no threshold | latest |
| H5 | "roll DEC-26→FEB-27 costs +1.03 % (+3.2 %/yr), FND in 35 d" | `COMEX_CARRY_ANN_PCT` (days to FND from `gold_cme_calendar`) | front → next calendar spread as % and annualised; days to first notice; printed whenever the curve gauge is fresh | no threshold | latest |
| H6 | "GLD −12.0 t on the day (notable)" | `GLD_TONNES` | GLD tonnes change on the latest day, printed whenever the ETF gauge is fresh; ≥ 5 t is called "notable" | `{"notable_t": 5.0}` | latest day |
| H0 | "no fresh gauge: every input is stale or unavailable" (only when no other clause exists) · the closing words on every sentence | — | every verdict ends "describes, does not predict"; stale or unavailable gauges contribute no clause | no threshold | — |

**[P]** How the API labels the clauses: the first clause (the H1 words plus the H2 driver word) comes back with
`rule_id: "H1/H2"`, the decomposition line as `H2`, then `H3` … `H6` in that order; `H0` appears alone when nothing is
fresh. The sentence is the clauses joined with " · " plus " · describes, does not predict" (tests T1 / T7 assert the
ending; `line` also feeds the WEI second line and the BRF line, PLAN §b).

**[P]** Planned, not in this release (PLAN §a.2 names them; no `rule_id` exists for them and nothing on the page prints them):
the week's largest day ("gold −2.8 % Thu …"), a Shanghai-premium clause (sign flip or \|value\| ≥ $20), an event clause
for a high-impact release in the next 24 h, a "(COT 10 days old)" note inside the sentence (today a stale gauge is simply
left out and its tile says STALE), and the "wide basis" / "India at a discount" words on H4.

**[B]** Reading it: what moved and who was behind it, in one breath.

**[P]** Every clause is a threshold on a stored series; nothing in the sentence is a forecast, and the thresholds are
deliberately coarse so the sentence changes only when the data does. The sentence ends "describes, does not predict".

---

# PART 9 — Reading routines (the "days, weeks, months" the owner asked for)

Each step names the panel in words, with its id in backticks and its view in capitals; LEARN renders these three lists
as collapsible checklists whose deep link is the first panel id on the line.

**Daily (08:30–08:55 IST, 10 minutes)**
1. The header strip (top of every view): COMEX settle and live, USD/INR, the real yield (yesterday's), the MCX settlement
   (by session), the basis, funds' net (last Tuesday) — then the verdict sentence (`h.verdict`, HEALTH) and the eight
   tiles (`h.gauges`).
2. Today's open (`h.open`, HEALTH): fair value vs yesterday's settlement; how much of the gap is COMEX and how much the
   rupee (`h.moved`); the event-risk chip. Decide OK / WAIT before 09:00 — the ₹300 limit is unproven, so read the strip
   as arithmetic, not advice.
3. The drivers (`mc.drivers`, MACRO): what changed overnight and why; the headlines (`h.headlines`, HEALTH); any scheduled
   event today (`h.events`, HEALTH; the after-close flag).
4. Yesterday's OI × price (`d.quadrant`, DAILY): COMEX (T+1) and MCX (07:35); roll and expiry days are greyed.
5. The expected move (`mc.move`, MACRO): ATR in rupees and the 1σ day per lot; max lots at 1 % risk sits on the MCXG paper ticket, cash headroom is yours to keep (≥ 3 ATR per lot); the roll
   calendar (`c.roll`, CONTRACTS) if a tender cut-off is within 7 days.
Evening (the last 30 min before the MCX close: 23:25–23:55 in US winter, 23:00–23:30 in US summer): the 24-hour chart (`d.24h`, DAILY) for COMEX vs the MCX close; tomorrow's events; MCX settles on the volume-weighted average of those 30 min.

**Weekly (Saturday morning, 20 minutes)**
1. Who did what (`p.hero` / `p.whois`, POSITIONING): the nets, the change by group in words, who closed what, the
   fund-driver label; crowdedness (`p.crowd`) as context only; the drawer (`p.drawer`) for the options line and trader
   counts; days to first notice (`c.roll`, CONTRACTS) for the roll footprint.
2. ETF holdings (`ph.etf`, PHYSICAL): GLD week on week; WGC weekly flows (Monday); the week's table and its CSV
   (`w.table`, WEEKLY).
3. The OTC window (`ph.otc`, PHYSICAL): LBMA turnover (weekly), EFP prints; the warehouse link (`ph.comex.stocks`) in a
   browser.
4. Term structure (`c.comex` / `c.mcx`, CONTRACTS): carry vs SOFR, the implied lease; the MCX–COMEX carry gap.
5. Premium and basis history (`ph.india` / `ph.shanghai`, PHYSICAL); any CBIC tariff-value or duty notification (owner,
   dated).
6. Next week's calendar (`h.events`, HEALTH / `mc.calendar`, MACRO): FOMC / CPI / NFP / RBI / Budget / MCX expiry /
   COMEX first notice day.

**Monthly (first weekend)**
1. Central banks (`m.official`, MONTHLY / `ph.official`, PHYSICAL): IMF ~25th, PBoC ~7th, RBI weekly.
2. Physical flow (`m.physical`, MONTHLY): London vaults; SGE withdrawals; India imports (PIB ~15th); Swiss exports; AMFI
   AUM in tonnes.
3. The regime check (`mc.health`, MACRO + `m.ladder`, `m.season`, MONTHLY): the real-yield link, central-bank pace, the
   ETF trend, the 3-year COT index as context, the seasonality caveat (§5.9).
4. The accuracy log (`h.accuracy`, HEALTH): model vs naive over the month; the chase-limit decision at 20 rows.
5. The contract selector (`c.selector`, CONTRACTS): any margin change (dated NRML mirror); broker rate changes.

---

# Appendix A — Formulas and constants (cheat-sheet)

```
1 ozt = 31.1034768 g        1 kg = 32.1507 ozt       1 tola = 11.6638 g = 3/8 ozt
₹/10 g (999)   = $/oz × USDINR × 10 / 31.1034768
995 → 999      × 1.00402 ;   999 → 995  × 0.99600
MCX fair (desk)= settlement × (COMEX_now / COMEX_ref) × (USDINR_now / USDINR_ref)   [refs = last-30-min average before MCX close]
duty-paid      = landed_995 × (1 + BCD + AIDC)      [15% (10% + 5%) since 13 May 2026, Notification 16/2026-Customs — dated input; tariff value fortnightly]
MCX basis      = MCX_front / duty-paid − 1 ; carry-adjusted basis = basis − carry_to_expiry
old implied premium = MCX / landed_999 − 1 = 0.995 × (1 + duty) × (1 + basis) − 1      [deprecated alias]
multiplier     = lot_g / quote_g  (GOLD 100, GOLDM 10, GOLDTEN 1, GUINEA 1, PETAL 1)
tick value     = ₹1 × multiplier ; notional = price × multiplier × lots ; P&L = Δprice × multiplier × lots
leverage       = notional / margin   [NRML 9.25% on 25 Oct 2026 → 10.8×]
carry (ann.)   = ln(F2/F1) × 365 / days ; implied lease ≈ r_USD − carry_COMEX ; carry_MCX ≈ carry_COMEX + (r_INR − r_USD)
basis          = F − S ; residual basis = basis − fair carry
net (COT)      = long − short (spreads excluded) ; COT index = 100 × (net − min_N)/(max_N − min_N)   [context only]
KGX            = usd_move = −Σ wᵢ Δln fᵢ (DXY weights) ; pure_gold = gold_usd + usd_move ; rupee leg = Δln USDINR
GSR            = gold $/oz ÷ silver $/oz
1σ day         = GVZ / √252  (× price × multiplier = ₹ per lot)
RR25           = IV(25Δ call) − IV(25Δ put)
lots           = floor(account × risk% / (k × ATR14 × multiplier)) ; margin ≤ 35% account ; cash headroom ≥ 3 × ATR × multiplier × lots
USDINR hedge   = lots × lot_g/31.1035 × $/oz / 1,000   (USD/INR futures of $1,000)
```

# Appendix B — The gold day in IST (US DST until 1 Nov 2026; UK on GMT from 25 Oct 2026)

| IST | What |
|---|---|
| 03:30 (04:30 winter) | CME Globex reopens after the 60-min break (Sun night: the week opens) |
| 07:45 / 11:45 | Shanghai Gold Benchmark auctions (10:15 / 14:15 Beijing); SGE day session ~06:30–13:00 IST |
| ~07:30 | ICICI publishes the MCX security master (yesterday's settlement, OI); the 07:35 job stores it |
| 08:45 / 09:10 | app: fair-open snapshot / actual-open capture (holiday-aware) |
| 09:00 | **MCX opens**; onshore USD/INR opens; NSE currency futures 09:00–17:00 |
| 13:30 | FBIL USD/INR reference rate; IBJA AM fix ≈12:00–13:00 (13:45 job) |
| 14:00–15:30 (T+1) | CME FTP daily volume & OI file (15:45 job) |
| 16:00 (15:00 BST) | **LBMA Gold Price AM** |
| 17:00 | MCX morning/evening split (partial holidays only); currency segment closes — rupee hedge is off |
| 18:00 (19:00 winter) | US data: CPI, NFP, retail sales (08:30 ET) — inside the MCX evening session |
| 18:30–00:00 | SHFE night session |
| 20:30 (19:30 BST) | **LBMA Gold Price PM**; IBJA PM fix ≈17:00–18:30 (18:10 job) |
| 23:00 (00:00 winter) | **COMEX settlement window** (13:29–13:30 ET) |
| 23:30 (23:55 winter) | **MCX closes**; settlement = VWAP of the last 30 min |
| 23:30 (00:30 winter) | FOMC statement (14:00 ET), presser +30 min — after the MCX close in winter |
| 02:30 (03:30 winter) | Globex daily close; break until 03:30 (04:30) |
| Sat 01:00 (02:00 winter) | **COT release** (Fri 15:30 ET); the job retries hourly to 06:30 |

# Appendix C — Evidence ledger

The single ledger is **`SOURCES.md` §11** (the G-STUDY results every badge rests on) with the full rows in
`G-STUDY/FINDINGS.md`, `G-MACRO/study.json`, `G-INDIA/scratch/amfi_study_results.json` and the program-level
`reports/gold_program/FINDINGS.md`. The claims this document makes, in one table:

| Claim | Status | Source |
|---|---|---|
| ₹/10 g conversion, multipliers, tick values, cost ladder, margin % | `arithmetic` | `shared/mcx_specs.py`, ICICI master, Zerodha NRML mirror (25 Oct 2026) |
| Duty 15% (BCD 10% + AIDC 5%) since 13 May 2026, Notification 16/2026-Customs | fact from secondary sources that agree; **owner confirms at CBIC (O-3)** | SOURCES.md F9 |
| COT positioning forecasts gold | **FAIL** at 1/4/13 weeks, every metric; COT-index lore reversed; 0 of 69 rules | G-STUDY (26 Oct 2026); G-COT COT-1 |
| COT describes the week | **PASS** (Δ fund net vs price Spearman +0.65, stable; next week −0.02) | G-STUDY |
| Real yields / dollar drive gold | contemporaneous explainers (H1 beta weaker since 2022; H2 ≈ −1 every regime); **no lead** | G-MACRO H1/H2; G-STUDY |
| ETF flows lead price | **no**; contemporaneous (R² 16% same week); AMFI flows chase returns | G-STUDY; G-MACRO; G-INDIA-1 |
| Seasonality (Dec/Jan, Diwali, weddings) | **context only**: no month passes both halves; walk-forward +0.3%/yr | G-MACRO H3; G-STUDY §4.4 |
| GPR, net liquidity, fair-value regressions | no prediction (H4); fair value DO-NOT-PUBLISH (H5) | G-MACRO |
| Chase limit ₹300 | **unsupported** (3 scored days, 0% within; model worse than naive) | accuracy log (SOURCES.md H2) |
| Event-risk headline chip | `heuristic`, no study; count only | `gold_preopen.py` |
| Safe-haven effect short-lived; GOFO discontinued 2015; academic COT literature | standard references, **not live-verified** | Baur & Lucey 2010; LBMA; Sanders–Irwin–Merrin 2009 (PLAN j.2 #15) |
| Source status (LBMA licence, Kitco terms, CME/MCX 403, Yahoo 429, GLD XLSX, SGE table) | **verified live 26 Oct 2026** | `verify_results.json`, `verify_pass2.json`, SOURCES.md |

# Appendix D — Source verification table

See REPORT.md §2 (the same table with status, latency, sample and verdict for all 52 probes) and `SOURCES.md` for the
program-wide 140 entries with verdicts.

# Appendix E — What is not free, and where to click instead

| Wanted | Why there is no feed | Where it is (link-only) | What the page shows instead |
|---|---|---|---|
| LBMA Gold Price AM/PM history | IBA licence; JSON 403; FRED series removed 2022 (A8, A10) | lbma.org.uk/prices-and-data | fix times as marks on `d.24h`; the WGC chart API's AM/PM as provisional reference marks (A9, gated on O-1) |
| CME daily bulletin, warehouse stocks, delivery notices, options OI, FedWatch, contract pages | www.cmegroup.com blocks this IP; its Data Terms forbid scripts (C7–C13, O-2) | the CME pages in a browser; `ph.comex.stocks`, `c.links` | per-product OI/volume, EFP prints, calendar and specs from the CME **FTP** (C1–C4); Yahoo per-month last trade labelled LAST TRADE; Atlanta Fed for the Fed path |
| MCX bhavcopy (official settlement, volume), category-wise OI, spot polling, circulars, option chain | Akamai bot wall to every scripted client (F3–F7, O-8) | mcxindia.com in a browser; `c.links` | ICICI master band midpoint as PROXY settlement and OI per contract (F1); hand-maintained circular constants; `p.mcx.category` dormant with the reason |
| Kitco charts and the KGX numbers | terms forbid robots and redistribution (A21–A24) | kitco.com/charts/gold | our own chart from stored bars (`d.24h`, `d.3day`); KGX replicated as `mc.kgx` with a rupee leg |
| Bloomberg / LSEG (`CFTC <GO>`, `GC1 Comdty`, `XAU=`) | paid, no redistribution (B16) | — | Appendix F maps each function to a free panel |
| Reuters "Asia Gold" dealer premiums | commentary, not a feed (E22) | mining.com republication | our IBJA-based premium with the Reuters number as a sanity line on `ph.india` |
| stooq, goldprice.org, investing.com | proof-of-work challenge / spoofed-referer only / 403 (A14–A16) | not even linked | Yahoo covers them |
| Sprott PHYS, US Mint, DGCX, Borsa Istanbul, SGE lease rates, HK trade, SAFE page | Cloudflare / no API / JS-only (E4, E18, D6, D8, D9, E13, E20) | `ph.links` | — |
| Nasdaq Data Link CHRIS/LBMA | discontinued / keyed (A19, A20) | — | CME FTP for OI, Yahoo for prices |
| A Yahoo "spot" gold symbol | `XAUUSD=X` is 404 (A7) | — | the spot proxy is the COMEX front, and the page says so |

# Appendix F — What a Bloomberg gold trader looks at → where it is here

Public-guide function names (G-KITCO Appendix C; UNVERIFIED on a terminal), mapped to the free build:

| Bloomberg | What it answers | Here |
|---|---|---|
| `GC1 Comdty DES` | the contract: size, tick, settlement, margin | `c.spec` (CME product reference, daily InitMargin %), `c.selector` for MCX |
| `GP` / `GIP` / `GPO` | the chart, intraday and history | `d.24h`, `d.3day` (1-min, our bars), `w.candles`, `m.candles` |
| `HP` | history table | `w.table` (+ CSV), `/api/gold/series?freq=D\|W\|M` |
| `CT` / `CTM` | the contract chain with volume and OI; exchange search | `c.mcx` (MCX chain, OI, carry), `c.comex`, `c.selector` (exchange × family × expiry) |
| `CCRV` / `FWCV` | the forward curve today vs a week ago | `c.comex` ghost curve, `c.mcx` |
| `GCA Comdty OIS`, the Volume & OI column | daily OI by product, the roll | `p.daily.comex` (CME FTP, T+1), `p.daily.mcx` |
| `CFTC <GO>`, `ALLX`, tickers `…MML/MMS/…N` | who is long and short, weekly | `p.hero`, `p.whois`, `p.history`, `p.crowd`, `p.drawer` |
| `XAU Curncy` | spot | no free spot feed: the spot proxy (COMEX front) with the note; gold-api cross-check chip |
| `GLCO` | gold in every currency | `mc.ccy` |
| `ECO` | releases with consensus | `mc.calendar`, `h.events` (ForexFactory JSON in IST, BEA/BLS links) |
| `WIRP` / FedWatch | the Fed path | `mc.fed` (Atlanta Fed MPT distribution; FedWatch stays a link) |
| `CPFC` | price forecasts | deliberately **not built** (a forecast panel contradicts §f; fair-value regressions are DO-NOT-PUBLISH) |
| WGC Goldhub, `ETF <GO>` | ETF holdings and flows, balance sheet | `ph.etf`, `m.balance`, `m.physical` (attributed, display-only) |
| `MARS` / risk | expected move, sizing | `mc.move` (GVZ → ₹ per lot), the MCXG ticket's sizing arithmetic |
