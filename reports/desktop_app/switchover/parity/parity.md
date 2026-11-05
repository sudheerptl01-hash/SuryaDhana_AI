# Parity — A `http://localhost:3000` vs B `http://127.0.0.1:8010`

- started 2026-10-25T11:09:08+05:30 · finished 2026-10-25T11:43:35+05:30 · wait 3.0 s · retries 1
- A: old :3000 (Next prod)
- B: ui-api :8010 static release 20261025-110718-0ae66db

## chromium (155.0.8059.85): 42/42 PARITY

- DIFF: none
- audit failures — A: brief, watch, charts, compare, screen, alerts, eco, seag, memb, options, ostrategy, derivatives, insiders, deals, preopen, ipo, movers, wrap, filings, margin, holders, world, desk, markets, events, overview, stocks, backtest, positions, broker, pipeline, scanner, discovery, commodity, mcxgold, glassbox, mlengine, explorer, warehouse, research, risk, system; B: none
- differences that disappeared on retry: none
- platform-seam traffic differed (set aside): brief, watch, charts, compare, screen, alerts, eco, seag, memb, options, ostrategy, derivatives, insiders, deals, preopen, ipo, movers, wrap, filings, margin, holders, world, desk, markets, events, overview, stocks, backtest, positions, broker, pipeline, scanner, discovery, commodity, mcxgold, glassbox, mlengine, explorer, warehouse, research, risk, system
- audit failures other than platform seams — A: none; B: none

| tab | code | verdict | A pass | B pass | ready A ms | ready B ms | API endpoints A/B | reasons |
|---|---|---|---|---|---:|---:|---|---|
| brief | BRF | PARITY | **no** | yes | 2067 | 542 | 50/49 |  |
| watch | WTCH | PARITY | **no** | yes | 505 | 448 | 27/26 |  |
| charts | CHRT | PARITY | **no** | yes | 486 | 191 | 23/22 |  |
| compare | COMP | PARITY | **no** | yes | 487 | 436 | 25/24 |  |
| screen | FUND | PARITY | **no** | yes | 461 | 449 | 23/22 |  |
| alerts | ALRT | PARITY | **no** | yes | 505 | 447 | 22/21 |  |
| eco | ECO | PARITY | **no** | yes | 543 | 494 | 22/21 |  |
| seag | SEAG | PARITY | **no** | yes | 491 | 199 | 22/21 |  |
| memb | MEMB | PARITY | **no** | yes | 502 | 457 | 23/22 |  |
| options | OMON | PARITY | **no** | yes | 500 | 450 | 24/23 |  |
| ostrategy | OSTR | PARITY | **no** | yes | 190 | 448 | 23/22 |  |
| derivatives | DERV | PARITY | **no** | yes | 500 | 451 | 29/28 |  |
| insiders | INSD | PARITY | **no** | yes | 495 | 458 | 24/23 |  |
| deals | DEAL | PARITY | **no** | yes | 490 | 455 | 25/24 |  |
| preopen | PRE | PARITY | **no** | yes | 507 | 454 | 24/23 |  |
| ipo | IPO | PARITY | **no** | yes | 502 | 197 | 23/22 |  |
| movers | MOV | PARITY | **no** | yes | 479 | 454 | 27/26 |  |
| wrap | WRAP | PARITY | **no** | yes | 499 | 453 | 23/22 |  |
| filings | CF | PARITY | **no** | yes | 243 | 466 | 24/23 |  |
| margin | MRGN | PARITY | **no** | yes | 501 | 457 | 23/22 |  |
| holders | HDS | PARITY | **no** | yes | 503 | 263 | 23/22 |  |
| world | WEI | PARITY | **no** | yes | 497 | 503 | 24/23 |  |
| desk | DESK | PARITY | **no** | yes | 489 | 440 | 29/28 |  |
| markets | MKT | PARITY | **no** | yes | 196 | 434 | 28/27 |  |
| events | EVTS | PARITY | **no** | yes | 500 | 450 | 32/31 |  |
| overview | OVRV | PARITY | **no** | yes | 184 | 544 | 23/22 |  |
| stocks | EQS | PARITY | **no** | yes | 773 | 754 | 23/22 |  |
| backtest | BTST | PARITY | **no** | yes | 494 | 455 | 21/20 |  |
| positions | PORT | PARITY | **no** | yes | 192 | 503 | 25/24 |  |
| broker | BRKR | PARITY | **no** | yes | 502 | 496 | 25/24 |  |
| pipeline | PIPE | PARITY | **no** | yes | 495 | 199 | 21/20 |  |
| scanner | LWSC | PARITY | **no** | yes | 501 | 440 | 22/21 |  |
| discovery | ALFA | PARITY | **no** | yes | 502 | 150 | 24/23 |  |
| commodity | CMDT | PARITY | **no** | yes | 655 | 503 | 25/24 |  |
| mcxgold | MCXG | PARITY | **no** | yes | 506 | 462 | 26/25 |  |
| glassbox | GBOX | PARITY | **no** | yes | 508 | 189 | 21/20 |  |
| mlengine | MLEN | PARITY | **no** | yes | 500 | 443 | 21/20 |  |
| explorer | DEXP | PARITY | **no** | yes | 552 | 200 | 22/21 |  |
| warehouse | WHSE | PARITY | **no** | yes | 550 | 557 | 26/25 |  |
| research | RSCH | PARITY | **no** | yes | 502 | 455 | 23/22 |  |
| risk | RSK | PARITY | **no** | yes | 504 | 202 | 22/21 |  |
| system | SYS | PARITY | **no** | yes | 762 | 760 | 24/23 |  |

### chromium: details

- **brief** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **watch** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **charts** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **compare** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **screen** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **alerts** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **eco** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **seag** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **memb** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **options** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **ostrategy** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **derivatives** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **insiders** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **deals** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **preopen** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **ipo** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **movers** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **wrap** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **filings** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **margin** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **holders** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **world** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **desk** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **markets** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **events** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **overview** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **stocks** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **backtest** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **positions** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **broker** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **pipeline** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **scanner** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **discovery** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **commodity** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **mcxgold** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **glassbox** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **mlengine** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **explorer** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **warehouse** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **research** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **risk** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **system** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []

## webkit (26.4): 42/42 PARITY

- DIFF: none
- audit failures — A: brief, watch, charts, compare, screen, alerts, eco, seag, memb, options, ostrategy, derivatives, insiders, deals, preopen, ipo, movers, wrap, filings, margin, holders, world, desk, markets, events, overview, stocks, backtest, positions, broker, pipeline, scanner, discovery, commodity, mcxgold, glassbox, mlengine, explorer, warehouse, research, risk, system; B: none
- differences that disappeared on retry: none
- platform-seam traffic differed (set aside): brief, watch, charts, compare, screen, alerts, eco, seag, memb, options, ostrategy, derivatives, insiders, deals, preopen, ipo, movers, wrap, filings, margin, holders, world, desk, markets, events, overview, stocks, backtest, positions, broker, pipeline, scanner, discovery, commodity, mcxgold, glassbox, mlengine, explorer, warehouse, research, risk, system
- audit failures other than platform seams — A: none; B: none

| tab | code | verdict | A pass | B pass | ready A ms | ready B ms | API endpoints A/B | reasons |
|---|---|---|---|---|---:|---:|---|---|
| brief | BRF | PARITY | **no** | yes | 543 | 584 | 50/49 |  |
| watch | WTCH | PARITY | **no** | yes | 494 | 517 | 27/26 |  |
| charts | CHRT | PARITY | **no** | yes | 513 | 528 | 23/22 |  |
| compare | COMP | PARITY | **no** | yes | 509 | 252 | 25/24 |  |
| screen | FUND | PARITY | **no** | yes | 489 | 503 | 23/22 |  |
| alerts | ALRT | PARITY | **no** | yes | 495 | 519 | 22/21 |  |
| eco | ECO | PARITY | **no** | yes | 281 | 528 | 22/21 |  |
| seag | SEAG | PARITY | **no** | yes | 513 | 651 | 22/21 |  |
| memb | MEMB | PARITY | **no** | yes | 508 | 199 | 23/22 |  |
| options | OMON | PARITY | **no** | yes | 478 | 487 | 24/23 |  |
| ostrategy | OSTR | PARITY | **no** | yes | 520 | 507 | 23/22 |  |
| derivatives | DERV | PARITY | **no** | yes | 564 | 504 | 29/28 |  |
| insiders | INSD | PARITY | **no** | yes | 490 | 504 | 24/23 |  |
| deals | DEAL | PARITY | **no** | yes | 520 | 172 | 25/24 |  |
| preopen | PRE | PARITY | **no** | yes | 520 | 435 | 24/23 |  |
| ipo | IPO | PARITY | **no** | yes | 605 | 505 | 23/22 |  |
| movers | MOV | PARITY | **no** | yes | 484 | 492 | 27/26 |  |
| wrap | WRAP | PARITY | **no** | yes | 497 | 439 | 23/22 |  |
| filings | CF | PARITY | **no** | yes | 523 | 253 | 24/23 |  |
| margin | MRGN | PARITY | **no** | yes | 756 | 566 | 23/22 |  |
| holders | HDS | PARITY | **no** | yes | 512 | 208 | 23/22 |  |
| world | WEI | PARITY | **no** | yes | 572 | 525 | 24/23 |  |
| desk | DESK | PARITY | **no** | yes | 516 | 514 | 29/28 |  |
| markets | MKT | PARITY | **no** | yes | 514 | 206 | 28/27 |  |
| events | EVTS | PARITY | **no** | yes | 480 | 526 | 32/31 |  |
| overview | OVRV | PARITY | **no** | yes | 571 | 562 | 23/22 |  |
| stocks | EQS | PARITY | **no** | yes | 1327 | 1318 | 23/22 |  |
| backtest | BTST | PARITY | **no** | yes | 535 | 515 | 21/20 |  |
| positions | PORT | PARITY | **no** | yes | 573 | 203 | 25/24 |  |
| broker | BRKR | PARITY | **no** | yes | 514 | 513 | 25/24 |  |
| pipeline | PIPE | PARITY | **no** | yes | 522 | 510 | 21/20 |  |
| scanner | LWSC | PARITY | **no** | yes | 488 | 489 | 22/21 |  |
| discovery | ALFA | PARITY | **no** | yes | 554 | 512 | 24/23 |  |
| commodity | CMDT | PARITY | **no** | yes | 1150 | 207 | 25/24 |  |
| mcxgold | MCXG | PARITY | **no** | yes | 538 | 525 | 26/25 |  |
| glassbox | GBOX | PARITY | **no** | yes | 512 | 511 | 21/20 |  |
| mlengine | MLEN | PARITY | **no** | yes | 519 | 497 | 21/20 |  |
| explorer | DEXP | PARITY | **no** | yes | 487 | 467 | 22/21 |  |
| warehouse | WHSE | PARITY | **no** | yes | 620 | 285 | 26/25 |  |
| research | RSCH | PARITY | **no** | yes | 524 | 539 | 23/22 |  |
| risk | RSK | PARITY | **no** | yes | 482 | 510 | 22/21 |  |
| system | SYS | PARITY | **no** | yes | 914 | 907 | 24/23 |  |

### webkit: details

- **brief** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **watch** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **charts** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **compare** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **screen** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **alerts** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **eco** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **seag** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **memb** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **options** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **ostrategy** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **derivatives** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **insiders** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **deals** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **preopen** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **ipo** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **movers** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **wrap** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **filings** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **margin** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **holders** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **world** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **desk** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **markets** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **events** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **overview** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **stocks** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **backtest** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **positions** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **broker** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **pipeline** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **scanner** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **discovery** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **commodity** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **mcxgold** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **glassbox** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **mlengine** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **explorer** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **warehouse** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **research** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **risk** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []
- **system** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 404 (Not Found)
  - A failure: failed_request: GET http://localhost:3000/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - A failure: failed_request: GET http://localhost:3000/api/health → HTTP 404
  - note: platform seams differ (set aside): A {'GET /api/health': ['4xx'], 'GET /api/prefs': ['2xx']} ['GET api/health → HTTP 404', 'GET health → HTTP 404'] · B {'GET /api/prefs': ['2xx']} []

**Overall: PARITY**
