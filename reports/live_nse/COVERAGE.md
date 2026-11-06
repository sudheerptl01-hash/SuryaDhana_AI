# Live NSE coverage, 5 Nov 2026

**Market hours (15:04–15:16 IST, UI release 20261105-144911, audit `ui_audit_20261105_live7`): 43/43 pages pass in Chromium and WebKit.** The audit asserts that every page shows a LIVE NSE price no more than 10 s old (the header NIFTY 50 from the Breeze websocket) and that no chip reads LIVE on older data. Counts are chips seen across both engines. EOD / periodic chips are datasets NSE publishes only after the close or on a schedule (bhavcopy, F&O files, participant OI, results, shareholding, deals), labelled with their date. The raw audit JSON is not committed (its request URLs carry the book's symbols).

**Source check** (Chromium crawl of all 43 pages, every Yahoo-capable API call): no NSE symbol is priced from Yahoo. WEI sends ^NSEI / ^NSEBANK / ^CNXIT / ^INDIAVIX to the quotes route, which answers them from the live NSE hub (verified: NIFTY 50, NIFTY BANK, NIFTY IT and RELIANCE `breeze_ws` LIVE; INDIA VIX `nse_api` DELAYED because Breeze does not stream that index). Yahoo serves only USD/INR, Brent, COMEX gold and the US / Asian indices on the tape, labelled.

**Feed**: Breeze websocket, subscription cap 500 (L-CAPACITY's operating cap; `LIVE_TICKS_MAX_SYMBOLS`). At 372 subscribed (about 10,000 ticks/min) data-service used 6–12 % CPU, `/health` answered in about 1 ms and no event-loop stall was logged. A name newly asked for goes LIVE in 2–5 s (p50 2.0 s); the page re-polls it every 2 s meanwhile.

| Page | Live chips (Breeze / NSE) | NSE delayed | EOD / periodic | Other states | Oldest live chip | Audit |
|---|---|---|---|---|---|---|
| ALFA · Alpha Discovery | 1 / 0 | 0 | 0 | LIVE·other 1 | 0.2 s | PASS |
| ALRT · Alerts | 1 / 0 | 0 | 0 | DELAYED 2, INPUT 1 | 2.1 s | PASS |
| BRF · Morning brief | 3 / 0 | 2 | 3 | DELAYED 1, LIVE·other 1 | 6.7 s | PASS |
| BRKR · Broker Account | 1 / 0 | 0 | 0 | DELAYED 3, REFERENCE 1 | 0.9 s | PASS |
| BTST · Backtest | 1 / 0 | 0 | 0 | — | 2.0 s | PASS |
| CF · Company filings | 1 / 0 | 1 | 0 | — | 2.9 s | PASS |
| CHRT · Chart studio | 2 / 0 | 0 | 1 | — | 3.0 s | PASS |
| CMDT · Commodity | 1 / 0 | 0 | 1 | DELAYED 2, OFFLINE 1 | 3.0 s | PASS |
| COMP · Compare stocks | 1 / 0 | 1 | 3 | — | 2.1 s | PASS |
| DEAL · Block & bulk deals | 1 / 0 | 0 | 4 | — | 3.0 s | PASS |
| DERV · Derivatives desk | 2 / 0 | 1 | 3 | — | 2.1 s | PASS |
| DESK · Decision Desk | 1 / 0 | 0 | 6 | DELAYED 1, REFERENCE 1 | 2.9 s | PASS |
| DEXP · Data Explorer | 1 / 0 | 0 | 0 | — | 2.9 s | PASS |
| ECO · Economic calendar | 1 / 0 | 0 | 0 | DELAYED 1 | 2.1 s | PASS |
| EQS · Stocks | 2 / 0 | 1 | 2 | — | 6.9 s | PASS |
| EVTS · Corporate calendar | 1 / 0 | 5 | 2 | DELAYED 1 | 0.8 s | PASS |
| FUND · Fundamentals screener | 1 / 0 | 2 | 0 | — | 2.9 s | PASS |
| GBOX · Glass-Box | 1 / 0 | 0 | 0 | — | 2.0 s | PASS |
| GOLD · Gold terminal | 1 / 0 | 0 | 0 | DELAYED 1, INPUT 1 | 3.8 s | PASS |
| HDS · Ownership shifts | 1 / 0 | 0 | 1 | — | 2.1 s | PASS |
| INSD · Insider monitor | 1 / 0 | 0 | 0 | STALE 1 | 2.1 s | PASS |
| IPO · IPO monitor | 1 / 0 | 1 | 2 | — | 2.9 s | PASS |
| LWSC · LW Scanner | 1 / 0 | 0 | 0 | — | 2.0 s | PASS |
| MCXG · MCX gold desk | 2 / 0 | 0 | 0 | DELAYED 2, INPUT 1, LIVE·other 1 | 3.0 s | PASS |
| MEMB · Index members | 3 / 0 | 0 | 3 | — | 5.7 s | PASS |
| MKT · Market Monitor | 1 / 0 | 3 | 11 | — | 3.0 s | PASS |
| MLEN · ML Engine | 1 / 0 | 0 | 0 | — | 2.0 s | PASS |
| MOV · Live movers | 5 / 0 | 10 | 0 | — | 4.9 s | PASS |
| MRGN · Margin monitor | 1 / 0 | 0 | 4 | — | 2.1 s | PASS |
| OMON · Option monitor | 2 / 0 | 3 | 0 | OFFLINE 2 | 2.9 s | PASS |
| OSTR · Options strategies | 3 / 0 | 2 | 0 | — | 3.0 s | PASS |
| OVRV · Overview | 1 / 0 | 0 | 3 | LIVE·other 1, REFERENCE 1 | 2.1 s | PASS |
| PIPE · Pipeline | 1 / 0 | 0 | 0 | — | 3.0 s | PASS |
| PORT · Portfolio | 1 / 0 | 0 | 0 | DELAYED 1 | 2.1 s | PASS |
| PRE · Pre-open auction | 1 / 0 | 5 | 0 | — | 2.9 s | PASS |
| RSCH · Research library | 1 / 0 | 0 | 1 | REFERENCE 1 | 0.2 s | PASS |
| RSK · Risk dashboard | 1 / 0 | 0 | 0 | DELAYED 6 | 2.2 s | PASS |
| SEAG · Seasonality | 1 / 0 | 1 | 0 | — | 2.1 s | PASS |
| SYS · System | 1 / 0 | 0 | 0 | LIVE·other 2 | 1.0 s | PASS |
| WEI · World markets | 2 / 0 | 0 | 0 | DELAYED 6 | 2.6 s | PASS |
| WHSE · Warehouse | 1 / 0 | 0 | 1 | DELAYED 2 | 2.9 s | PASS |
| WRAP · Daily market wrap | 1 / 0 | 0 | 2 | — | 2.1 s | PASS |
| WTCH · Watch monitor | 1 / 0 | 0 | 0 | INPUT 1 | 2.2 s | PASS |

## What is not live, and why (after the post-close batch, 16:25 IST)

| Page(s) | Before | Fix | Now |
|---|---|---|---|
| OMON, EVTS (IV history, results IV crush) | OFFLINE · only 1 stored session | IV backfill 2019-10-01 → 2026-11-04 (1,759 sessions, 329,725 summary rows, 626 events; 42 min, no errors) | no OFFLINE / STALE chip; NIFTY IV rank 20.6 over 750 sessions |
| OMON, MEMB, EVTS, DESK (IV / drivers) | OFFLINE · 404 | f4c884e contract routes; drivers backfill 2019-10-01 (1,761 sessions) | answering |
| INSD | STALE · 30 Oct | insider ingest at 15:31 (data through 5 Nov); `nse_insider_daily` 21:50 Mon–Fri (4935c9b) | current |
| DESK, OVRV, BRF (Desk ledger) | STALE · 30 Oct | the missed `desk_daily` cycle run once (sessions 2–4 Nov); 19:30 marks 5 Nov | current to the last close |
| OMON intraday IV path for a stock | OFFLINE chip | coverage line: the 15-min Breeze pilot covers NIFTY, BANKNIFTY and the watch list's F&O names (0270a0b) | labelled; the stock's live chain is the NSE panel |
| VIX overlay (index IV views) | 5 sessions of VIX | NSE's vixhistory API answered 403; backfilled from the `ind_close_all` archive files (1,847 days: 1,744 files, 100 holidays, 3 files NSE dated wrongly, e.g. 6 Apr 2023 stamped 4 Jun 2023) | `vix_daily` 2019-10-01 → 2026-11-04 (1,749 sessions); NIFTY IV page overlays 750 |
| CMDT | OFFLINE (EIA) | keyless fallback to EIA's own public file of the same series (cd8778e; checked by its Sourcekey row) | EIA crude stocks through 30 Oct, production through Aug 2026; a free `EIA_API_KEY` switches to the v2 API |
| MCXG, WEI tape | DELAYED / non-NSE | MCX gold, USD/INR, Brent, COMEX gold and the US / Asian indices are not NSE data | labelled with their source |

## After the close (audit `ui_audit_20261105_closed3`, 17:28–17:40 IST)

43/43 pages pass in Chromium and WebKit with the market closed:
- No NSE price reads LIVE. The only LIVE chips are the controller clock, the service probes and MCX (open until 23:30).
- The OSTR margin chip read LIVE · BREEZE after the close in the 17:00 run. Fixed in cd8778e: it now reads CLOSE · <session>.
- A data-service restart after the close keeps today's last prices. On its first quote request the tick engine primes itself from today's
  tick store (33a214d; 423 symbols primed after the 17:27 restart), so stock, members and movers rows read CLOSED · 5 Nov, not STALE · 4 Nov.
- Today's equity bhavcopy was ingested at 17:41 as soon as NSE published it (3,567 rows). NSE's official closes replace the last traded
  prices within 10 min.
- OSTR's seed chain waited on NSE's 5 Nov F&O bhavcopy (404 at 17:40). A watcher polled NSE's archive every 5 min. NSE published at 18:46,
  and the file was ingested within a minute (224 rows), followed by today's `iv_eod` (FOVOLT, contract delta, combined OI, index closes).
  OSTR reads CLOSE · 05 NOV, OMON reads EOD · 05 NOV, and NIFTY's IV history ends 5 Nov (iv30 12.80). No STALE or OFFLINE chip remains.

## Evening (audit `ui_audit_20261105_evening`, 21:41–21:54 IST)

43/43 pages pass in Chromium and WebKit (console errors 0, page errors 0, failed requests 0):
- No NSE price reads LIVE. The 7 LIVE chips per engine are the controller clock, the service probes, the live-service probe, the MCX
  session clock and MCX gold on Breeze (MCX trades until 23:30).
- 232 of 241 dated NSE / stored chips read 5 Nov. The other 9 are dated by design: the MTF report is T+1 (03 Nov; 4 Nov's file comes
  with the 22:45 pass), DESK's monthly brief carries the 30 Oct month-end signal, MEMB's monthly drivers view the November bucket,
  shareholding is quarterly (27 Oct), EVTS results run to 04 Nov until the 22:45 pass, one IV event is dated by its event (07 Aug),
  FRED / EIA are not NSE, and `ml_labels` belongs to the dormant pipeline.
- OMON, EVTS, MEMB, DESK and INSD: no OFFLINE or STALE chip.
- Evening jobs: EOD pipeline (through 5 Nov), 19:25 drivers, 19:30 Desk (last mark 5 Nov), the 20:30 pass with `iv_eod` (685 expiry,
  2,474 surface, 224 summary rows), 21:50 insider filings (13 new).
- The Mac restarted at about 19:52 (controller down 19:34–19:55). The 19:50 S1 shadow and the 19:45 news track record were missed,
  and neither had run since 30 Oct (the 31 Oct–4 Nov outage's catch-up left them to "the next run"). Both were re-run at 21:40 on the
  19:20 snapshot; the shadow's data-health row is fresh again.
- ICICI: the forced login at 20:28 logged in on the authenticator code alone (no SMS), so the 08:00 job can start the Breeze feed
  unattended. The market-hours confirmation is the 6 Nov 09:26 acceptance run.

## Market hours, 6 Nov acceptance (audit `ui_audit_20261106_acceptance`, 09:26–09:38 IST)

43/43 pages pass in Chromium and WebKit with the market open; every page shows a Breeze LIVE chip no more than 10 s old.
- ICICI: the 08:00 job logged in unattended on the authenticator code (08:00:09, no SMS, no OTP prompt).
- Feed: 4,723 ticks/min, 0 unmapped ticks, last tick 0.0 s, every subscribed name had its first tick. NIFTY 50, NIFTY BANK,
  INDIA VIX (now from the websocket, no longer NSE's website) and 7 large caps all read `breeze_ws` live, under 2 s old over a
  20 s sample (ITC up to 5–7 s: its price changes less often). The news hover card reads `breeze_ws`, 0.5 s.
- Still DELAYED · NSE by design during the session: panes that read NSE's website (the option chain v3, about 1 min, on
  OMON / OSTR / BRF; allIndices sector rows and valuation, 1–3 min, on MOV / MKT; the heatmap lists, about 1 min). They are
  live-capable only through Breeze option and sector-index subscriptions, which are not built. Dated EOD / periodic chips
  (bhavcopy, F&O files, MTF T+1, results, deals, calendar, the pre-open snapshot) are not live data. Yahoo appears on WORLD
  only (non-NSE indices).
- EQS read "STALE · NSE · 22m · 27/60 LIVE". Cause (adversarial review wf_2d40b24a-03b, from the tick store and the access
  log): the page had last been asked for at 09:03, the tick engine unsubscribed its names after 10 min without demand and
  kept their 09:08 auction ticks; the audit re-asked at 09:29:5x and captured the page about 7 s later. Breeze sends no
  snapshot on subscribe, so a row waits for its next trade: 50 of the 52 names ticked within 20 s. The old reason text said
  "the feed is not healthy". Fixed in the tree (not yet deployed): a tick older than the current subscription is never
  quiet-LIVE and never "covered" for the NSE poller, which now fetches NSE's copy at once; reasons name the cause
  ("re-subscribed 5 s ago, waiting for the first tick").
- Not shipped, an owner decision: keeping a quiet name LIVE past 120 s when NSE's copy shows the same price and volume.
  Two review rounds (wf_2d40b24a-03b, wf_45861533-2e5) found it needs transport-gap detection, a 66 s NextApi age floor,
  stamped copies only and honest-time storage, and even then a silently dead token could read LIVE for about 3.5 min after a
  missed trade (today's bound is 120 s).
