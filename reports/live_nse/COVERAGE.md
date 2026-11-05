# Live NSE coverage, 5 Nov 2026 (market open, 14:20–14:35 IST, UI release 20261105-141624)

Source: the 43-page audit with the live-freshness assertion (`scripts/ui_audit.py --tabs all --browser both`, run `ui_audit_20261105_live4`). 43/43 pages pass in Chromium and WebKit. Every page shows at least one LIVE NSE price no more than 10 s old (the header NIFTY 50, from the Breeze websocket), and no chip reads LIVE on older data. Counts are chips seen across both engines. EOD / periodic chips are datasets NSE publishes only after the close or on a schedule (bhavcopy, F&O files, participant OI, results, shareholding, deals), labelled with their date. The raw audit JSON is not committed (its request URLs carry the book's symbols).

| Page | Live chips (Breeze / NSE) | NSE delayed | EOD / periodic | Other states | Oldest live chip | Audit |
|---|---|---|---|---|---|---|
| ALFA · Alpha Discovery | 1 / 0 | 0 | 0 | LIVE·other 1 | 0.1 s | PASS |
| ALRT · Alerts | 1 / 0 | 0 | 0 | DELAYED 2, INPUT 1 | 2.0 s | PASS |
| BRF · Morning brief | 3 / 0 | 2 | 2 | DELAYED 1, LIVE·other 1, STALE 1 | 7.8 s | PASS |
| BRKR · Broker Account | 1 / 0 | 0 | 0 | DELAYED 3, REFERENCE 1 | 3.0 s | PASS |
| BTST · Backtest | 1 / 0 | 0 | 0 | — | 2.1 s | PASS |
| CF · Company filings | 1 / 0 | 1 | 0 | — | 2.9 s | PASS |
| CHRT · Chart studio | 2 / 0 | 0 | 1 | — | 2.3 s | PASS |
| CMDT · Commodity | 1 / 0 | 0 | 1 | DELAYED 2, OFFLINE 1 | 3.0 s | PASS |
| COMP · Compare stocks | 1 / 0 | 1 | 3 | — | 2.1 s | PASS |
| DEAL · Block & bulk deals | 1 / 0 | 0 | 4 | — | 4.0 s | PASS |
| DERV · Derivatives desk | 2 / 0 | 1 | 3 | — | 2.1 s | PASS |
| DESK · Decision Desk | 1 / 0 | 0 | 4 | DELAYED 1, OFFLINE 1, REFERENCE 1, STALE 1 | 2.1 s | PASS |
| DEXP · Data Explorer | 1 / 0 | 0 | 0 | — | 3.0 s | PASS |
| ECO · Economic calendar | 1 / 0 | 0 | 0 | DELAYED 1 | 2.0 s | PASS |
| EQS · Stocks | 1 / 0 | 0 | 2 | STALE 1 | 3.6 s | PASS |
| EVTS · Corporate calendar | 1 / 0 | 5 | 2 | OFFLINE 1 | 0.9 s | PASS |
| FUND · Fundamentals screener | 1 / 0 | 2 | 0 | — | 2.9 s | PASS |
| GBOX · Glass-Box | 1 / 0 | 0 | 0 | — | 2.0 s | PASS |
| GOLD · Gold terminal | 1 / 0 | 0 | 0 | DELAYED 1, INPUT 1 | 4.0 s | PASS |
| HDS · Ownership shifts | 1 / 0 | 0 | 1 | — | 2.1 s | PASS |
| INSD · Insider monitor | 1 / 0 | 0 | 0 | STALE 1 | 2.0 s | PASS |
| IPO · IPO monitor | 1 / 0 | 1 | 2 | — | 3.1 s | PASS |
| LWSC · LW Scanner | 1 / 0 | 0 | 0 | — | 2.1 s | PASS |
| MCXG · MCX gold desk | 2 / 0 | 0 | 0 | DELAYED 2, INPUT 1, LIVE·other 1 | 2.9 s | PASS |
| MEMB · Index members | 3 / 0 | 0 | 0 | OFFLINE 3 | 5.3 s | PASS |
| MKT · Market Monitor | 1 / 0 | 3 | 11 | — | 2.8 s | PASS |
| MLEN · ML Engine | 1 / 0 | 0 | 0 | — | 3.0 s | PASS |
| MOV · Live movers | 5 / 0 | 10 | 0 | — | 3.4 s | PASS |
| MRGN · Margin monitor | 1 / 0 | 0 | 4 | — | 2.1 s | PASS |
| OMON · Option monitor | 2 / 0 | 3 | 0 | OFFLINE 2 | 1.1 s | PASS |
| OSTR · Options strategies | 3 / 0 | 2 | 0 | — | 3.9 s | PASS |
| OVRV · Overview | 1 / 0 | 0 | 2 | LIVE·other 1, REFERENCE 1, STALE 1 | 3.0 s | PASS |
| PIPE · Pipeline | 1 / 0 | 0 | 0 | — | 2.0 s | PASS |
| PORT · Portfolio | 1 / 0 | 0 | 0 | DELAYED 1 | 2.1 s | PASS |
| PRE · Pre-open auction | 1 / 0 | 5 | 0 | — | 2.1 s | PASS |
| RSCH · Research library | 1 / 0 | 0 | 1 | REFERENCE 1 | 0.1 s | PASS |
| RSK · Risk dashboard | 1 / 0 | 0 | 0 | DELAYED 6 | 2.1 s | PASS |
| SEAG · Seasonality | 1 / 0 | 1 | 0 | — | 2.0 s | PASS |
| SYS · System | 1 / 0 | 0 | 0 | LIVE·other 2 | 1.1 s | PASS |
| WEI · World markets | 1 / 0 | 1 | 0 | DELAYED 6 | 0.1 s | PASS |
| WHSE · Warehouse | 1 / 0 | 0 | 1 | DELAYED 2 | 2.0 s | PASS |
| WRAP · Daily market wrap | 1 / 0 | 0 | 2 | — | 2.0 s | PASS |
| WTCH · Watch monitor | 1 / 0 | 0 | 0 | INPUT 1 | 2.1 s | PASS |

## What is not live yet, and why

| Page(s) | Chip | Cause | When it clears |
|---|---|---|---|
| OMON, EVTS, MEMB, DESK | OFFLINE (IV / drivers) | ui-api read contract routes data-service did not serve (fixed in f4c884e) | data-service restart, 5 Nov 21:37 |
| INSD | STALE · 30 Oct | insider filings were ingested weekly (Saturday) | `nse_insider_daily` 21:50 Mon–Fri (4935c9b), first run 5 Nov |
| DESK, OVRV, BRF | STALE · 30 Oct (Desk ledger) | the controller was down 31 Oct–4 Nov, so the Desk mark did not run | `desk_daily` 5 Nov 19:30 marks the missed sessions |
| EQS | some rows STALE for 2–5 s | names evicted at the 300-symbol Breeze cap when more than 300 are asked for within 10 min re-subscribe in 2–5 s (p50 2.0 s) | warm-up polling (406c084); `LIVE_TICKS_MAX_SYMBOLS` up to 500 is the owner's call (0ea8367) |
| CMDT | OFFLINE (EIA) | `EIA_API_KEY` not set | owner adds a free EIA key |
| MCXG, WEI tape | DELAYED / non-NSE | MCX gold, USD/INR, Brent, COMEX gold, S&P 500 are not NSE data (Yahoo or MCX, labelled) | not NSE: stays labelled |
