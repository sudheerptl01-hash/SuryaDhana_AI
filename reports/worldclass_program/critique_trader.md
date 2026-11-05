# C1 — Trader-completeness critique (15 Oct 2026, 03:36–03:55 IST)

Auditor: C1, desk-trader persona (15y NSE cash/F&O + MCX). Method: walked a full trading day on the
live terminal (http://localhost:3000, 42 GO pages) with Playwright screenshots
(`reports/worldclass_program/c1_shots/`), hand-verified every number I'd bet on, GET-only (one
sanctioned POST to the options calculator). Audit ran at 03:36 IST — NSE closed, MCX closed,
ICICI session invalid — deliberately the harshest hour for honesty judging.

---

## VERDICT

**TRADE-READY FOR: NSE cash equities (EOD-driven swing/positional workflow) · NSE F&O analytics &
strategy pricing (EOD chain) · MCX gold pre-open + paper workflow.**
**NOT YET FOR: intraday execution-grade trading in any segment (tick persistence has never run a
session; quotes off-session are delayed Yahoo; no depth), live MCX gold session work (no live quote
until Breeze entitlement verifies, and no gold price chart exists anywhere), and anything needing
consensus estimates or a news wire.**

One sentence: this is the best self-built Indian-markets terminal I have audited — the honesty
engineering is genuinely Bloomberg-grade and most numbers foot to the rupee — but it is still an
*EOD analyst's* terminal with a paper ticket, not yet an *intraday trader's* terminal.

---

## Workflow scores

### 1. 06:30 pre-market prep — **9/10**
Evidence: `c1_shots/brief.png`, `world.png`, `eco.txt`.
- One command (BRF) delivers the full morning run: 0/4 RISK-OFF regime score with exposure guide,
  breadth 825/577, distribution days, NIFTY P/E percentile, crash-filter state ("needs +7.1% to turn
  risk-on · 154 sessions below"), book NAV, **gold fair open ₹1,47,612 with a ₹300 chase limit and
  the baseline mechanics spelled out**, results-to-react ("MRPL +203% profit, awaiting the open,
  react at 09:15"), FII/DII cash, eco week incl. the Dussehra closure, 9 morning-page links, and a
  "NEEDS YOU · 3" ops strip. That IS a Bloomberg morning run.
- WEI: per-row freshness ages (54m NASDAQ, 1m EUR/USD), GIFT implied gap vs NIFTY close, FOMC
  28 Oct / RBI MPC 4 Dec dates with IST times (23:30 DST vs 00:30 winter — correct), footer honesty
  "Delayed data, for context only."
- ECO: every release sourced (MoSPI/DPIIT/RBI/Fed), moved-from-weekend annotations, and the honest
  footer "Dates only: no forecasts or consensus figures (no free source for those)."
- Docked: **CF (filings) defaults to "today" — at 06:30 that shows "0 filings"** (`filings.txt`).
  The filings-since-yesterday's-close question is answered only indirectly (BRF results strip, 08:50
  alert). A "since last close" default window is the missing piece. India 10Y shown as price 840.68,
  not yield — traders think in yield.

### 2. 09:00 pre-open — **8.5/10**
Evidence: `preopen.png`.
- IEP, gap %, prev close, matched qty/value, buy/sell leftover with imbalance bars, median gap, gap
  histogram, F&O/NIFTY50/BANKNIFTY/ALL filters, full 213-stock book with find-box, **NEXT EVENT
  column tagging results dates on gap names** (OBEROIRLTY "RESULTS 16 OCT · TMRW") — that's the
  exact context a pre-open trader wants. Honest header: "book as of 14-Oct-2026 09:09:33 · showing
  the last session."
- Withheld 1.5: I could not observe the live 09:00–09:08 window (audit hour), and there's no path
  from a gap row to a queued paper order — you re-type in the profile ticket.

### 3. NSE session 09:15–15:30 — **8/10** (composite)
- **Watchlist (WTCH) 8/10** (`watch.png`, `watch_reliance.png`): empty state honest; added RELIANCE
  → row with LAST/DAY/P-E/profit-YY/1M sparkline/day-range/52w/next-event/alert-bell. Source chip
  "● DELAYED · YAHOO" + footer "ICICI live quotes, when connected, are on the Broker tab" — the page
  says what it is. Nit: at 03:46 the "UP/DOWN **TODAY** 1/0" and "● STREAMING" wording refer to the
  prior session; during market hours they're right.
- **CHRT 7.5/10** (`charts.png`, `chrt_tcs.png`, `chrt_weekly.png`, `chrt_5m.png`): real candle
  studio — crosshair OHLCV+% readout, symbol switch works, D/W/M verified (**W bars labeled by the
  bucket's last trading day — Thu 1 Oct proves holiday-awareness**, checked via
  `/api/charts/ohlcv?tf=W`), EMA/BB/RSI toggles, source line "DUCKDB EOD · YAHOO HISTORY · AS OF
  2026-10-14". Intraday 5m shows a loud, honest amber: "INTRADAY UNAVAILABLE — no tick data for TCS
  on 2026-10-15. The chart shows nothing rather than fake bars." Missing vs a GP screen: drawing
  tools, comparison overlay, log scale, saved layouts — and the GO bar has **no ticker→CHRT suffix**
  (see cross-cutting).
- **OMON 8.5/10** (`options.png`): EOD chain with forward (put-call parity), expected move ±1.53%,
  PCR with ₹Cr, max pain, OI walls, IV-rank 66 with 1y history, volatility smile, **the F&O
  securities-in-ban list (AMBUJACEM KAYNES SAIL)** — a real desk need most home terminals forget.
- **OSTR 8.5/10** (`ostrategy.png`, `ostr_condor.png`): numbers foot *exactly*. Straddle (22600
  CE 144.20 + PE 131.75, lot 65): debit ₹17,936.75, BEs 22,324.05/22,875.95 = strike ∓ premium,
  theta −₹1,630/day ≈ half the average decay rate (B-76-correct at T), Δ +2.3 ≈ ₹51k — all verified
  against my own POST to `/api/options/strategy/analyze`. Iron condor: credit ₹4,144 = max profit,
  max loss ₹2,356 = width−credit, BEs = short strikes ∓ 63.75 — exact; theta +, vega − (signs
  right). Guardrails: 5 legs → 422 unified envelope; CE-no-strike → 400 with hint. "PRICES ONLY ·
  NO ORDERS" chip. Docked: **margin heuristic is ~10× conservative for defined-risk books**
  (condor estimate ₹3,73,135 vs real SPAN ~₹30–50k) — loudly labeled, but it would mis-size every
  spread; no probability-of-profit on screen; one expiry per book in the UI.
- **DERV 8/10** (`derivatives.png`, `derv_reliance.png`, `derv_banknifty.png`): NIFTY near basis
  +3.20% ann (0.114% × 365/13 — foots), next +5.38%, far +5.95%, labeled contango; rollover 14.2%
  at T−13 vs 14.8% prior-cycle at same DTE (14.2% = 3.06M/21.5M shares — foots); 5y basis history;
  VIX 71st pctile vs rv20 spread −0.15; works per-stock (RELIANCE +18.14% ann near, "inverted carry
  curve" flagged, profile cross-link). BANKNIFTY basis-history hole stated with the exact reason
  ("market_index_daily holds NIFTY50 only"). Docked: term-structure column header "CONTRACTS" is
  actually day *volume* in contracts (53,505 = the API's `volume`), not OI — a desk reader will
  misread it; summary card compares rollover-so-far 14.2% against *final* avg 74.5% (apples/oranges
  — the tracker below does it right at same-DTE); the annualized-basis history spikes ±40–70% near
  expiry (honest but noisy — cap or grey the <5 DTE region).
- **Alerts 8/10** (`alerts.txt`): inbox with MORNING/CLOSE/FILING/MOVE/WRAP kinds, per-holding move
  alerts, and even a **self-correcting entry** ("Correction to the 15:40 note: Yahoo's daily series
  skipped 12 Oct, so day changes were two-day moves"). Setting a price alert exists via the profile
  ALERT button (POST — untested under my constraints).
- **Costs ticket 8.5/10**: `/api/costs/ticket` — value-based sizing, ₹49,333 notional → round trip
  ₹471.28 = 0.955% with DP ₹20, itemized to the leg; matches the MoneySaver reality in CLAUDE.md,
  not the 0.15% fantasy.
- **RSK 8.5/10** (`risk.png`, `risk_whatif_btn.png`): empty-book handling is exemplary — "The book
  is ALL CASH today… nothing at market risk," VaR panels honestly dashed, drawdown ladder still live
  from EOD NAV marks (stop NAV ₹4,01,111, room before −2% halt 2.02%, "intraday halt distance needs
  live marks"), Desk rules quoted "displayed, never modified here." What-if basket
  (RELIANCE/TCS/HDFCBANK/INFY): VaR95 1.66%/₹8,319, VaR99 2.89%, ES95 2.28%, σ 1.02%, β 0.92
  (HDFCBANK 1.22 / INFY 0.70 — right ordering), COVID replay −33.4% vs NIFTY −37 (≈β — foots),
  election-day −3.4%, **SECTOR CRIT chip fired on the 50% IT count vs the 40% Desk cap** — correct
  rule, correctly applied. Methodology notes label the √5 scaling as an approximation. Docked:
  pressing Enter in the what-if input does nothing — only the WHAT-IF button submits.
- Composite docked to 8: the session story depends on live ticks, and the tick store has **never
  persisted a session yet** (`/ticks/store-status`: started:false; no `data/ticks/` day yet). The
  intraday promise is untested in production until today 09:15.

### 4. MCX gold evening — **8/10**
Evidence: `mcxgold.png`, `mcxg_ticket.png`; specs cross-checked against public contract pages.
- Session clock **correct at 03:40**: CLOSED, opens 15 Oct 09:00 (countdown 5h19m), evening close
  23:30 with the US-DST note (23:55 in winter). Holiday table is MCX's own calendar, not NSE's:
  **Dussehra Tue 20 Oct = EVE ONLY (17:00→)** ✓, Diwali-Balipratipada 10 Nov, Guru Nanak 24 Nov,
  Christmas full day, plus the 8 Nov Muhurat note.
- **Contract specs verified**: GOLD 1kg, ₹/10g, tick ₹1 = ₹100 ✓; GOLDM 100g = ₹10 ✓; GOLDPETAL 1g,
  ₹/1g, ₹1 = ₹1 ✓; GOLDGUINEA 8g, ₹/8g, ₹1 = ₹1 ✓ (Zerodha Varsity / ICICIdirect / broker spec
  sheets); expiry rule "5th, previous business day if closed" ✓; expiries cross-checked against the
  ICICI master on screen (GOLD 2026-12-04 observed ✓). Margins honestly labeled indicative 6%,
  "revised daily by MCX (typically ≈6–12%)."
- Quote degrade is the best I've seen pre-login: "Broker quote unavailable — Breeze gave no MCX GOLD
  quote (Object reference not set…) — commodity segment not verified for this account… LIVE-VERIFY
  PENDING · after the 08:00 login," with the price-band settlement (₹1,49,543, band, OI 17,548 lots)
  AND the COMEX×INR fair value (₹1,47,480; landed ₹1,26,134 "no import duty or local premium";
  premium 16.9% over landed) as labeled fallbacks, and "Premium vs fair appears when a live broker
  quote exists — never computed against the model itself."
- **Paper ticket foots to the rupee**: GOLD 1 lot @147,480 → notional ₹1,47,48,000; margin 6%
  ₹8,84,880; round trip ₹2,582.68 = buy ₹701.42 + sell ₹1,881.26 — I recomputed every leg
  (exch 0.0021% = ₹309.71/leg, CTT 0.01% sell-only = ₹1,474.80, stamp 0.002% buy-only = ₹294.96,
  SEBI ₹14.75, GST 18% of brokerage+txn+SEBI = ₹62.00): exact. Breakeven 25.8 ticks stated.
- Docked 2: **you cannot chart MCX gold anywhere in this terminal** (CHRT is NSE-only; the desk has
  no gold price history), gold options absent, and the live-quote path remains unproven until the
  entitlement check. Minor: BRF's gold card (cached) showed ₹1,47,612 while MCXG (fresh) showed
  ₹1,47,480 — both timestamped, but a shared cache would remove the cross-page mismatch.

### 5. EOD — **8/10**
Evidence: `wrap.txt`, `positions.txt`, `backtest.txt`, `research.txt`, SYS job table.
- WRAP: per-session archive, "written 21:00 IST… facts only, not signals." Alerts carry the 21:00
  wrap + 15:40 closing note. Backtest lab: 250-day warm-up note ("no cold-start bias"), next-open
  entry timing, friction floored at 0.15%, walk-forward in the engine. RSCH: verdict-tagged library
  that includes **its own failures** (news-scanner "no edge," the Bloomberg critic's NO verdict) —
  unheard-of honesty in a vendor terminal.
- Journal (W8): wired — SYS shows "Weekly Decision Journal (Friday)" due in 40h; `reports/journal/`
  does not exist yet (first run Fri 20:10). Graded as plumbing-present, output unproven. The MC
  drawdown lens output exists and is honest (DD-FRAGILE on S1-gateB/S1H — report-only).
- Docked: **the PORT tab is the dormant legacy engine's ₹10k book** ("engine populates positions
  when signals fire (autopilot is OFF)") while the real paper money (₹5.01L Desk) lives in DESK —
  a trader pressing PORTFOLIO sees a dead book. Naming/wiring needs one decision.

### 6. Cross-cutting — **7/10**
- **Ticker-first UX is world-class**: GO → "RELIANCE" → suffix commands DES/FA/ERN/HP/SEAG/OMON/
  DEAL/TV/W (`go_reliance.png`); Enter → full profile modal with price, DELAYED·YAHOO chip, mcap,
  P/E, chart, PIN/WATCHLIST/ALERT buttons (`go_reliance_enter.png`). Any symbol → profile/chain in
  ≤2 actions ✓.
- **Page discovery is the weak half**: `CommandBar.tsx:137` matches pages only on
  `code.startsWith(q) || label.startsWith(q)` — hints are never searched. Typing **"gold" returns
  only tickers (GOLDBEES, GOLDIAM…) and never surfaces MCXG or CMDT** (`go_gold.png`);
  "rollover"/"straddle"/"vwap" return a raw echo row and no page (`go_rollover.png`,
  `go_straddle.png`). Exact codes work (`go_chrt.png`). The 5 new pages are findable only if you
  already know their codes. Also: no CHRT suffix on tickers, and the profile modal's chart (SMA
  stack) is a different component from CHRT (EMA stack) with no cross-link — two chart truths.
- **Latency feel: excellent.** Warm: mcx/session 1ms, derv/term 7ms, charts D 2–9ms, risk 1–13ms,
  option-chain 18ms, preopen 12ms, eco 5ms, alpha/universe 54ms (cold 1.40s — the W7 cache verified
  working), events 24ms. Slowest: lw/screener 1.44s warm (its own indicator compute),
  live-quotes 1.13s (Yahoo fan-out at night). Pages settle in 5–8s incl. pollers; SYS took 24s to
  network-idle (long-poll noise, not blocking paint).
- **Data honesty: pervasive.** 23/23 pages loaded with **zero console errors and zero failed API
  calls at 03:40 with the broker session invalid** — the degrade paths all return 200-with-reason.
  As-of stamps and source labels on every panel I opened (12+ distinct honesty markers captured in
  `walk.json`). Phone control (Telegram) remains relevant: alerts inbox mirrors it; not exercised
  (constraint).

---

## THE MISSING LIST

### (a) Buildable next, ranked by trading value
1. **Prove intraday end-to-end + index intraday in CHRT.** The tick store has never written a
   parquet (store-status: started:false). Today 09:15 is the first real test of W6→W1. Also wire
   the existing NSE 1-min index feed (MOV uses it) into CHRT so NIFTY/BANKNIFTY intraday exists
   even without broker ticks.
2. **MCX gold price history + chart.** MCX daily bhavcopy is free (GAPS §3 says so itself). Ingest
   it and give MCXG/CHRT a GOLD continuous series with the COMEX overlay. A gold desk without a
   gold chart is half a desk.
3. **GO bar search upgrade.** Substring + hint-keyword matching ("gold"→MCXG, "rollover"→DERV,
   "straddle"→OSTR, "vwap"→CHRT), a `<TICKER> CHRT` suffix, and "open in CHRT" from the profile
   modal. One file, removes the single biggest daily friction.
4. **Real SPAN margin.** NSE publishes SPAN risk-parameter files free, intraday. Parse them and
   replace the 10×-conservative heuristic; until then every spread's margin is fiction (labeled
   fiction, but fiction).
5. **CF pre-market window.** Default "since yesterday's close" (and a YOUR STOCKS default filter)
   between 06:00–09:15.
6. **One book story.** Rename/rewire PORT (legacy engine) vs DESK (real paper NAV) vs BRKR — a
   single "where is my money" page with the ladder; RSK already reads the right books.
7. **Paper F&O book + position Greeks.** OSTR's math is done (W3 lib); let a priced strategy be
   saved as a paper position and aggregate net Greeks on RSK.
8. **Derivatives alerts.** Alert on basis/rollover pace/PCR/max-pain drift/IV-rank levels, not just
   price.
9. **Expiry-day (T-0) view.** OI unwind vs max pain through the session once intraday OI sampling
   exists (Breeze quote OI as the free approximation).
10. **Pre-open → ticket shortcut.** From a PRE gap row to a pre-filled paper ticket at the IEP.

### (b) External / paid — GAPS §6 verified, with my notes
GAPS §6's claims are **accurate**; I checked each against what's on screen tonight:
- **L2/L3 depth, tick-by-tick**: correct — NSE TBT is paid/colo-grade. Best-5 via Breeze WS is the
  realistic ceiling; note W6 currently stores L1+best bid/ask only, so even best-5 display is a
  later build on an entitled feed.
- **News wire** (Reuters/BBG embargoed): paid. Free proxy honestly labeled on BRF (scanner's own
  track record shown as no-edge). Correct.
- **Consensus estimates / sell-side models**: paid (Refinitiv/Visible Alpha class); ECO already
  says "no free source for forecasts." Correct — and it's the biggest *analyst* gap vs Bloomberg
  (EPS estimates, target prices, surprise history).
- **Real-time F&O OI**: correct — exchange snapshots ~3 min; true RT is member territory. Breeze
  quote-OI sampling is the free approximation (goes with (a)9).
- **Earnings-call audio/transcripts**: mostly paid; NSE submissions free. Correct.
- **Global futures live** (CME GC, ES/NQ): correct — free is delayed; the terminal shows delayed
  Yahoo with as-of chips, which is the honest ceiling without a CME agreement (~$100s/mo + redist
  terms for display-only).
- **MCX tick history**: paid — but the *daily* grain is free bhavcopy, which is why (a)2 is
  buildable tonight-class work, not external.
- **Live order routing** (SEBI retail algo framework, Apr 2026): owner process — broker approval,
  static IP, audit trail. Paper mode sidesteps it deliberately. Correct.
- **My additions**: RBI reference-rate FX fix is *free* (not external — small build);
  corporate-actions hardening beyond Yahoo adj-factors would want a paid CA feed eventually;
  multi-user entitlements/IB chat remain out of scope by design.

### (c) Polish that matters (frictions I actually hit)
- RSK what-if input: Enter must submit (button-only today).
- DERV: "CONTRACTS" column → "VOL (contracts)"; summary card should compare rollover at same-DTE
  (the tracker already does); cap/grey the <5-DTE spikes on the basis-history chart.
- CHRT intraday-empty state: keep the last EOD chart ghosted behind the amber notice instead of a
  blank canvas with a 1500–4750 axis.
- WTCH at night: "UP/DOWN TODAY" → "LAST SESSION"; the STREAMING dot should grey off-session.
- WEI: show the 10Y *yield* (and change in bp), not the G-SEC price index alone.
- Unify BRF gold card and MCXG fair value through one cache (₹43 divergence tonight, both
  timestamped so honest, still looks like a bug to a user).
- OSTR: show probability-of-profit (the math already computes prob-ITM); display days-to-expiry
  recomputed from *today* beside the chain-date figure.
- `/api/derivatives/vix` as_of carries a midnight timestamp for a date — trim to date.

---

## Flaws found (severity-ranked)

1. **MED-HIGH — GO bar page search is startsWith-only on code/label; hints unindexed.**
   `ui/components/CommandBar.tsx:137`. "gold" → tickers only; "rollover"/"straddle" → nothing. The
   five new pages are effectively invisible unless you memorized the codes. (Discoverability of
   tonight's work is the one place the "world-class" claim visibly fails.)
2. **MED — No MCX gold chart.** The gold desk has specs, clock, fair value and a ticket, but no
   price history anywhere; CHRT only resolves NSE symbols.
3. **MED — Margin estimates mis-size defined-risk books ~10×** (condor ₹3.73L est vs SPAN-reality
   ~₹30–50k). Labeled ESTIMATE with the floor stated — honest — but unusable for spread sizing,
   and the fix (NSE SPAN files) is free.
4. **MED — Tick persistence unproven in production.** started:false, zero parquet days; W1's
   intraday and VWAP remain claims until a session runs. (The degrade story meanwhile is perfect.)
5. **LOW-MED — PORT is the dormant legacy book.** "Portfolio" shows the dead ₹10k engine ledger
   with a LIQUIDATE & HALT button; the real ₹5.01L paper NAV lives in DESK. Confusing and slightly
   dangerous-looking (the big red button controls a book with nothing in it).
6. **LOW — assorted:** RSK Enter no-op; CF "today · 0 filings" at dawn; DERV label nits; WTCH
   night-wording ("TODAY", STREAMING); 10Y price-not-yield; BRF↔MCXG ₹43 fair-value cache skew;
   VIX as_of format. None of these lies to the user; they just rub.

No fabricated data found anywhere. Every number I hand-checked — basis annualization, rollover %,
straddle/condor BEs and Greeks signs, VaR order statistics, beta ordering, stress replays vs β,
MCX ticket cost legs, W-bar holiday labels, cost-ticket round trip — **footed**. That is rare.

---

## What genuinely impressed a 15-year desk rat

- **The honesty system.** Every panel carries as-of + source; every degrade carries the *reason*
  ("Breeze gave no MCX GOLD quote (Object reference not set…) — commodity segment not verified…
  LIVE-VERIFY PENDING · after the 08:00 login"); an alert that corrected its own earlier number;
  a research library that displays its own critic's NO verdict and its scanner's no-edge record.
  Bloomberg does not tell you when it's guessing. This terminal does.
- **Math exactness.** OSTR breakevens solved on payoff segments (exact to the paise), condor
  credit=max-profit identities, CTT/STT on the correct legs only, GST on exactly
  brokerage+txn+SEBI, MCX ticket to the rupee, holiday-aware weekly bars.
- **23/23 pages, zero console errors, zero failed API calls at 03:40 with the broker logged out.**
  Most retail platforms can't survive that screenshot run at market close, let alone at night.
- **BRF + the gold open card** — fair value, baseline provenance, expected gap, chase limit —
  is a better pre-open gold brief than most commodity desks write by hand.
- **W7's cache is real**: alpha/universe 1.40s cold → 54ms warm, measured live.
- **RSK's empty-book page** — the hardest state to design — is the best page in the risk stack:
  it refuses to invent numbers and still gives you the ladder, the rules, and a one-click what-if.

Spec sources used for MCX verification:
[Zerodha Varsity — Gold](https://zerodha.com/varsity/chapter/gold-part-1/) ·
[ICICIdirect — gold contracts](https://www.icicidirect.com/ilearn/commodity/articles/how-to-trade-gold-in-commodity-derivatives-market-in-india-1) ·
[Rupeezy — commodity contract specs](https://support.rupeezy.in/support/solutions/articles/21000005285-what-are-commodity-lot-sizes-and-contract-specs)

*Screens: `reports/worldclass_program/c1_shots/*.png` · raw page text + honesty markers:
`walk.json`, `*.txt` · interaction evidence: `interact.json` · scripts: `c1_walk.py`,
`c1_interact.py` (GET-only).*
