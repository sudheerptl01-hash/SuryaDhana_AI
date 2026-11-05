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
