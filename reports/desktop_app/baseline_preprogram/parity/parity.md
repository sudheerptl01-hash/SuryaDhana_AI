# Parity — A `http://127.0.0.1:8097` vs B `http://127.0.0.1:8010`

- started 2026-10-25T12:14:33+05:30 · finished 2026-10-25T12:51:27+05:30 · wait 3.0 s · retries 1
- A: pre-program baseline (reconstructed, served on scratch :8097)
- B: live :8010 release 20261025-114737-0ae66db

## chromium (155.0.8059.85): 39/42 PARITY

- DIFF: ostrategy, discovery, mcxgold
- audit failures — A: ostrategy, discovery, mcxgold; B: none
- differences that disappeared on retry: none
- platform-seam traffic differed (set aside): brief, watch, charts, compare, screen, alerts, eco, seag, memb, options, ostrategy, derivatives, insiders, deals, preopen, ipo, movers, wrap, filings, margin, holders, world, desk, markets, events, overview, stocks, backtest, positions, broker, pipeline, scanner, discovery, commodity, mcxgold, glassbox, mlengine, explorer, warehouse, research, risk, system
- audit failures other than platform seams — A: ostrategy, discovery, mcxgold; B: none

| tab | code | verdict | A pass | B pass | ready A ms | ready B ms | API endpoints A/B | reasons |
|---|---|---|---|---|---:|---:|---|---|
| brief | BRF | PARITY | yes | yes | 823 | 512 | 48/49 |  |
| watch | WTCH | PARITY | yes | yes | 439 | 463 | 25/26 |  |
| charts | CHRT | PARITY | yes | yes | 448 | 471 | 21/22 |  |
| compare | COMP | PARITY | yes | yes | 450 | 464 | 23/24 |  |
| screen | FUND | PARITY | yes | yes | 449 | 447 | 21/22 |  |
| alerts | ALRT | PARITY | yes | yes | 452 | 437 | 20/21 |  |
| eco | ECO | PARITY | yes | yes | 493 | 502 | 20/21 |  |
| seag | SEAG | PARITY | yes | yes | 451 | 440 | 20/21 |  |
| memb | MEMB | PARITY | yes | yes | 436 | 455 | 21/22 |  |
| options | OMON | PARITY | yes | yes | 498 | 454 | 22/23 |  |
| ostrategy | OSTR | **DIFF** | **no** | yes | 446 | 500 | 21/22 | status classes differ: POST /api/options/strategy/analyze A['4xx'] B['2xx']; console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []; panels differ: only  |
| derivatives | DERV | PARITY | yes | yes | 450 | 500 | 27/28 |  |
| insiders | INSD | PARITY | yes | yes | 453 | 449 | 22/23 |  |
| deals | DEAL | PARITY | yes | yes | 189 | 506 | 23/24 |  |
| preopen | PRE | PARITY | yes | yes | 449 | 456 | 22/23 |  |
| ipo | IPO | PARITY | yes | yes | 450 | 197 | 21/22 |  |
| movers | MOV | PARITY | yes | yes | 451 | 460 | 25/26 |  |
| wrap | WRAP | PARITY | yes | yes | 444 | 456 | 21/22 |  |
| filings | CF | PARITY | yes | yes | 247 | 459 | 22/23 |  |
| margin | MRGN | PARITY | yes | yes | 437 | 437 | 21/22 |  |
| holders | HDS | PARITY | yes | yes | 432 | 200 | 21/22 |  |
| world | WEI | PARITY | yes | yes | 124 | 511 | 22/23 |  |
| desk | DESK | PARITY | yes | yes | 440 | 449 | 27/28 |  |
| markets | MKT | PARITY | yes | yes | 192 | 454 | 26/27 |  |
| events | EVTS | PARITY | yes | yes | 191 | 450 | 30/31 |  |
| overview | OVRV | PARITY | yes | yes | 494 | 192 | 21/22 |  |
| stocks | EQS | PARITY | yes | yes | 735 | 750 | 21/22 |  |
| backtest | BTST | PARITY | yes | yes | 453 | 461 | 19/20 |  |
| positions | PORT | PARITY | yes | yes | 239 | 502 | 23/24 |  |
| broker | BRKR | PARITY | yes | yes | 451 | 458 | 23/24 |  |
| pipeline | PIPE | PARITY | yes | yes | 435 | 607 | 19/20 |  |
| scanner | LWSC | PARITY | yes | yes | 435 | 593 | 20/21 |  |
| discovery | ALFA | **DIFF** | **no** | yes | 233 | 441 | 21/23 | API request set differs: only A [], only B ['GET /api/market/surveillance?all_flagged,symbols']; status classes differ: POST /api/alpha/scan A['4xx'] B['2xx']; console errors differ: only A ['Failed to load resource: the |
| commodity | CMDT | PARITY | yes | yes | 1530 | 505 | 23/24 |  |
| mcxgold | MCXG | **DIFF** | **no** | yes | 444 | 447 | 24/25 | status classes differ: POST /api/mcx/ticket A['4xx'] B['2xx']; console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []; table_headers differ: only A [], o |
| glassbox | GBOX | PARITY | yes | yes | 444 | 452 | 19/20 |  |
| mlengine | MLEN | PARITY | yes | yes | 143 | 457 | 19/20 |  |
| explorer | DEXP | PARITY | yes | yes | 450 | 455 | 20/21 |  |
| warehouse | WHSE | PARITY | yes | yes | 540 | 181 | 24/25 |  |
| research | RSCH | PARITY | yes | yes | 438 | 454 | 21/22 |  |
| risk | RSK | PARITY | yes | yes | 439 | 528 | 20/21 |  |
| system | SYS | PARITY | yes | yes | 495 | 804 | 22/23 |  |

### chromium: details

- **ostrategy** (DIFF)
  - reason: status classes differ: POST /api/options/strategy/analyze A['4xx'] B['2xx']
  - reason: console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []
  - reason: panels differ: only A [], only B ['Margin & costs — ESTIMATE']
  - reason: error boxes: A ['▲ blocked by desktop-qa scratch server (--block-mutations)'] vs B []
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8097/api/options/strategy/analyze → HTTP 403
  - note: attempt 1 differed: ["status classes differ: POST /api/options/strategy/analyze A['4xx'] B['2xx']", "console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []", "panels differ: only A [], only B ['Margin & costs — ESTIMATE']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/prefs': ['2xx']} []
- **discovery** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/market/surveillance?all_flagged,symbols']
  - reason: status classes differ: POST /api/alpha/scan A['4xx'] B['2xx']
  - reason: console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []
  - reason: table_headers differ: only A [], only B ['| TICKER | SIGNAL DATE | LTP / CLOSE | CHG% | NET #D']
  - reason: tables: A 0 vs B 1
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8097/api/alpha/scan → HTTP 403
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/market/surveillance?all_flagged,symbols']", "status classes differ: POST /api/alpha/scan A['4xx'] B['2xx']", "console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], on
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/prefs': ['2xx']} []
- **mcxgold** (DIFF)
  - reason: status classes differ: POST /api/mcx/ticket A['4xx'] B['2xx']
  - reason: console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []
  - reason: table_headers differ: only A [], only B ['Leg | Brokerage | Exch # | CTT # (sell) | Stamp (buy) | SEBI | GST # | Total']
  - reason: tables: A 2 vs B 3
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8097/api/mcx/ticket → HTTP 403
  - note: attempt 1 differed: ["status classes differ: POST /api/mcx/ticket A['4xx'] B['2xx']", "console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []", "table_headers differ: only A [], only B ['Leg | Brokerage | Exch # | CTT # (sell) | Stam
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/prefs': ['2xx']} []

## webkit (26.4): 39/42 PARITY

- DIFF: ostrategy, discovery, mcxgold
- audit failures — A: ostrategy, discovery, mcxgold; B: none
- differences that disappeared on retry: none
- platform-seam traffic differed (set aside): brief, watch, charts, compare, screen, alerts, eco, seag, memb, options, ostrategy, derivatives, insiders, deals, preopen, ipo, movers, wrap, filings, margin, holders, world, desk, markets, events, overview, stocks, backtest, positions, broker, pipeline, scanner, discovery, commodity, mcxgold, glassbox, mlengine, explorer, warehouse, research, risk, system
- audit failures other than platform seams — A: ostrategy, discovery, mcxgold; B: none

| tab | code | verdict | A pass | B pass | ready A ms | ready B ms | API endpoints A/B | reasons |
|---|---|---|---|---|---:|---:|---|---|
| brief | BRF | PARITY | yes | yes | 798 | 534 | 48/49 |  |
| watch | WTCH | PARITY | yes | yes | 455 | 487 | 25/26 |  |
| charts | CHRT | PARITY | yes | yes | 493 | 513 | 21/22 |  |
| compare | COMP | PARITY | yes | yes | 472 | 492 | 23/24 |  |
| screen | FUND | PARITY | yes | yes | 496 | 479 | 21/22 |  |
| alerts | ALRT | PARITY | yes | yes | 1614 | 487 | 20/21 |  |
| eco | ECO | PARITY | yes | yes | 515 | 488 | 20/21 |  |
| seag | SEAG | PARITY | yes | yes | 495 | 475 | 20/21 |  |
| memb | MEMB | PARITY | yes | yes | 448 | 478 | 21/22 |  |
| options | OMON | PARITY | yes | yes | 468 | 507 | 22/23 |  |
| ostrategy | OSTR | **DIFF** | **no** | yes | 475 | 500 | 21/22 | status classes differ: POST /api/options/strategy/analyze A['4xx'] B['2xx']; console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []; panels differ: only  |
| derivatives | DERV | PARITY | yes | yes | 524 | 510 | 27/28 |  |
| insiders | INSD | PARITY | yes | yes | 475 | 428 | 22/23 |  |
| deals | DEAL | PARITY | yes | yes | 467 | 515 | 23/24 |  |
| preopen | PRE | PARITY | yes | yes | 479 | 585 | 22/23 |  |
| ipo | IPO | PARITY | yes | yes | 499 | 490 | 21/22 |  |
| movers | MOV | PARITY | yes | yes | 495 | 485 | 25/26 |  |
| wrap | WRAP | PARITY | yes | yes | 489 | 506 | 21/22 |  |
| filings | CF | PARITY | yes | yes | 440 | 492 | 22/23 |  |
| margin | MRGN | PARITY | yes | yes | 458 | 501 | 21/22 |  |
| holders | HDS | PARITY | yes | yes | 452 | 531 | 21/22 |  |
| world | WEI | PARITY | yes | yes | 510 | 501 | 22/23 |  |
| desk | DESK | PARITY | yes | yes | 509 | 497 | 27/28 |  |
| markets | MKT | PARITY | yes | yes | 445 | 486 | 26/27 |  |
| events | EVTS | PARITY | yes | yes | 490 | 477 | 30/31 |  |
| overview | OVRV | PARITY | yes | yes | 562 | 489 | 21/22 |  |
| stocks | EQS | PARITY | yes | yes | 1608 | 1152 | 21/22 |  |
| backtest | BTST | PARITY | yes | yes | 471 | 482 | 19/20 |  |
| positions | PORT | PARITY | yes | yes | 446 | 491 | 23/24 |  |
| broker | BRKR | PARITY | yes | yes | 498 | 429 | 23/24 |  |
| pipeline | PIPE | PARITY | yes | yes | 461 | 482 | 19/20 |  |
| scanner | LWSC | PARITY | yes | yes | 873 | 478 | 20/21 |  |
| discovery | ALFA | **DIFF** | **no** | yes | 193 | 476 | 21/23 | API request set differs: only A [], only B ['GET /api/market/surveillance?all_flagged,symbols']; status classes differ: POST /api/alpha/scan A['4xx'] B['2xx']; console errors differ: only A ['Failed to load resource: the |
| commodity | CMDT | PARITY | yes | yes | 469 | 1009 | 23/24 |  |
| mcxgold | MCXG | **DIFF** | **no** | yes | 468 | 532 | 24/25 | status classes differ: POST /api/mcx/ticket A['4xx'] B['2xx']; console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []; table_headers differ: only A [], o |
| glassbox | GBOX | PARITY | yes | yes | 486 | 499 | 19/20 |  |
| mlengine | MLEN | PARITY | yes | yes | 494 | 505 | 19/20 |  |
| explorer | DEXP | PARITY | yes | yes | 442 | 430 | 20/21 |  |
| warehouse | WHSE | PARITY | yes | yes | 605 | 563 | 24/25 |  |
| research | RSCH | PARITY | yes | yes | 441 | 474 | 21/22 |  |
| risk | RSK | PARITY | yes | yes | 491 | 476 | 20/21 |  |
| system | SYS | PARITY | yes | yes | 703 | 804 | 22/23 |  |

### webkit: details

- **ostrategy** (DIFF)
  - reason: status classes differ: POST /api/options/strategy/analyze A['4xx'] B['2xx']
  - reason: console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []
  - reason: panels differ: only A [], only B ['Margin & costs — ESTIMATE']
  - reason: error boxes: A ['▲ blocked by desktop-qa scratch server (--block-mutations)'] vs B []
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8097/api/options/strategy/analyze → HTTP 403
  - note: attempt 1 differed: ["status classes differ: POST /api/options/strategy/analyze A['4xx'] B['2xx']", "console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []", "panels differ: only A [], only B ['Margin & costs — ESTIMATE']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/prefs': ['2xx']} []
- **discovery** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/market/surveillance?all_flagged,symbols']
  - reason: status classes differ: POST /api/alpha/scan A['4xx'] B['2xx']
  - reason: console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []
  - reason: table_headers differ: only A [], only B ['| TICKER | SIGNAL DATE | LTP / CLOSE | CHG% | NET #D']
  - reason: tables: A 0 vs B 1
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8097/api/alpha/scan → HTTP 403
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/market/surveillance?all_flagged,symbols']", "status classes differ: POST /api/alpha/scan A['4xx'] B['2xx']", "console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], on
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/prefs': ['2xx']} []
- **mcxgold** (DIFF)
  - reason: status classes differ: POST /api/mcx/ticket A['4xx'] B['2xx']
  - reason: console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []
  - reason: table_headers differ: only A [], only B ['Leg | Brokerage | Exch # | CTT # (sell) | Stamp (buy) | SEBI | GST # | Total']
  - reason: tables: A 2 vs B 3
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8097/api/mcx/ticket → HTTP 403
  - note: attempt 1 differed: ["status classes differ: POST /api/mcx/ticket A['4xx'] B['2xx']", "console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []", "table_headers differ: only A [], only B ['Leg | Brokerage | Exch # | CTT # (sell) | Stam
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/prefs': ['2xx']} []

**Overall: DIFF**
