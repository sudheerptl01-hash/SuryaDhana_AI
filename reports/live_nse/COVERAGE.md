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
