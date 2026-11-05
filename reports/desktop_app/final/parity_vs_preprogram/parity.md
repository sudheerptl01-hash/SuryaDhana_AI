# Parity — A `http://127.0.0.1:8097` vs B `http://127.0.0.1:8098`

- started 2026-10-25T15:41:43+05:30 · finished 2026-10-25T16:16:09+05:30 · wait 3.0 s · retries 1
- A: pre-program UI (24 Oct 10:38, reconstructed)
- B: release 20261025-153533-0ae66db (after wave 2)

## chromium (155.0.8059.85): 42/42 PARITY

- DIFF: none
- audit failures — A: ostrategy, discovery, mcxgold; B: ostrategy, discovery, mcxgold
- differences that disappeared on retry: none
- platform-seam traffic differed (set aside): brief, watch, charts, compare, screen, alerts, eco, seag, memb, options, ostrategy, derivatives, insiders, deals, preopen, ipo, movers, wrap, filings, margin, holders, world, desk, markets, events, overview, stocks, backtest, positions, broker, pipeline, scanner, discovery, commodity, mcxgold, glassbox, mlengine, explorer, warehouse, research, risk, system
- expected program deltas on one side only (set aside): brief, watch, charts, compare, screen, alerts, eco, seag, memb, options, ostrategy, derivatives, insiders, deals, preopen, ipo, movers, wrap, filings, margin, holders, world, desk, markets, events, overview, stocks, backtest, positions, broker, pipeline, scanner, discovery, commodity, mcxgold, glassbox, mlengine, explorer, warehouse, research, risk, system
- audit failures other than platform seams — A: ostrategy, discovery, mcxgold; B: ostrategy, discovery, mcxgold

| tab | code | verdict | A pass | B pass | ready A ms | ready B ms | API endpoints A/B | reasons |
|---|---|---|---|---|---:|---:|---|---|
| brief | BRF | PARITY | yes | yes | 1104 | 141 | 48/42 |  |
| watch | WTCH | PARITY | yes | yes | 463 | 54 | 25/20 |  |
| charts | CHRT | PARITY | yes | yes | 460 | 55 | 21/16 |  |
| compare | COMP | PARITY | yes | yes | 465 | 35 | 23/18 |  |
| screen | FUND | PARITY | yes | yes | 442 | 34 | 21/16 |  |
| alerts | ALRT | PARITY | yes | yes | 505 | 30 | 20/15 |  |
| eco | ECO | PARITY | yes | yes | 501 | 69 | 20/14 |  |
| seag | SEAG | PARITY | yes | yes | 431 | 36 | 20/15 |  |
| memb | MEMB | PARITY | yes | yes | 449 | 43 | 21/16 |  |
| options | OMON | PARITY | yes | yes | 444 | 45 | 22/17 |  |
| ostrategy | OSTR | PARITY | **no** | **no** | 556 | 26 | 21/16 |  |
| derivatives | DERV | PARITY | yes | yes | 437 | 49 | 27/22 |  |
| insiders | INSD | PARITY | yes | yes | 452 | 44 | 22/17 |  |
| deals | DEAL | PARITY | yes | yes | 450 | 48 | 23/18 |  |
| preopen | PRE | PARITY | yes | yes | 454 | 46 | 22/17 |  |
| ipo | IPO | PARITY | yes | yes | 451 | 40 | 21/16 |  |
| movers | MOV | PARITY | yes | yes | 446 | 39 | 25/20 |  |
| wrap | WRAP | PARITY | yes | yes | 454 | 33 | 21/16 |  |
| filings | CF | PARITY | yes | yes | 430 | 48 | 23/18 |  |
| margin | MRGN | PARITY | yes | yes | 431 | 84 | 21/16 |  |
| holders | HDS | PARITY | yes | yes | 496 | 31 | 21/16 |  |
| world | WEI | PARITY | yes | yes | 432 | 44 | 22/17 |  |
| desk | DESK | PARITY | yes | yes | 443 | 48 | 27/22 |  |
| markets | MKT | PARITY | yes | yes | 431 | 42 | 26/21 |  |
| events | EVTS | PARITY | yes | yes | 447 | 53 | 30/24 |  |
| overview | OVRV | PARITY | yes | yes | 193 | 47 | 21/17 |  |
| stocks | EQS | PARITY | yes | yes | 798 | 51 | 21/17 |  |
| backtest | BTST | PARITY | yes | yes | 455 | 60 | 19/14 |  |
| positions | PORT | PARITY | yes | yes | 502 | 99 | 23/18 |  |
| broker | BRKR | PARITY | yes | yes | 443 | 50 | 23/18 |  |
| pipeline | PIPE | PARITY | yes | yes | 193 | 54 | 19/20 |  |
| scanner | LWSC | PARITY | yes | yes | 455 | 51 | 20/15 |  |
| discovery | ALFA | PARITY | **no** | **no** | 457 | 53 | 21/16 |  |
| commodity | CMDT | PARITY | yes | yes | 920 | 97 | 23/18 |  |
| mcxgold | MCXG | PARITY | **no** | **no** | 450 | 49 | 24/19 |  |
| glassbox | GBOX | PARITY | yes | yes | 503 | 32 | 19/14 |  |
| mlengine | MLEN | PARITY | yes | yes | 456 | 34 | 19/14 |  |
| explorer | DEXP | PARITY | yes | yes | 451 | 28 | 20/15 |  |
| warehouse | WHSE | PARITY | yes | yes | 194 | 97 | 24/19 |  |
| research | RSCH | PARITY | yes | yes | 494 | 134 | 21/16 |  |
| risk | RSK | PARITY | yes | yes | 436 | 38 | 20/15 |  |
| system | SYS | PARITY | yes | yes | 697 | 420 | 22/17 |  |

### chromium: details

- **ostrategy** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8097/api/options/strategy/analyze → HTTP 403
  - B failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - B failure: failed_request: POST http://127.0.0.1:8098/api/options/strategy/analyze → HTTP 403
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **discovery** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8097/api/alpha/scan → HTTP 403
  - B failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - B failure: failed_request: POST http://127.0.0.1:8098/api/alpha/scan → HTTP 403
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **mcxgold** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8097/api/mcx/ticket → HTTP 403
  - B failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - B failure: failed_request: POST http://127.0.0.1:8098/api/mcx/ticket → HTTP 403
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /

## webkit (26.4): 42/42 PARITY

- DIFF: none
- audit failures — A: ostrategy, discovery, mcxgold; B: ostrategy, discovery, mcxgold
- differences that disappeared on retry: none
- platform-seam traffic differed (set aside): brief, watch, charts, compare, screen, alerts, eco, seag, memb, options, ostrategy, derivatives, insiders, deals, preopen, ipo, movers, wrap, filings, margin, holders, world, desk, markets, events, overview, stocks, backtest, positions, broker, pipeline, scanner, discovery, commodity, mcxgold, glassbox, mlengine, explorer, warehouse, research, risk, system
- expected program deltas on one side only (set aside): brief, watch, charts, compare, screen, alerts, eco, seag, memb, options, ostrategy, derivatives, insiders, deals, preopen, ipo, movers, wrap, filings, margin, holders, world, desk, markets, events, overview, stocks, backtest, positions, broker, pipeline, scanner, discovery, commodity, mcxgold, glassbox, mlengine, explorer, warehouse, research, risk, system
- audit failures other than platform seams — A: ostrategy, discovery, mcxgold; B: ostrategy, discovery, mcxgold

| tab | code | verdict | A pass | B pass | ready A ms | ready B ms | API endpoints A/B | reasons |
|---|---|---|---|---|---:|---:|---|---|
| brief | BRF | PARITY | yes | yes | 829 | 196 | 48/42 |  |
| watch | WTCH | PARITY | yes | yes | 467 | 74 | 25/20 |  |
| charts | CHRT | PARITY | yes | yes | 524 | 85 | 21/16 |  |
| compare | COMP | PARITY | yes | yes | 191 | 70 | 23/18 |  |
| screen | FUND | PARITY | yes | yes | 440 | 133 | 21/16 |  |
| alerts | ALRT | PARITY | yes | yes | 1192 | 76 | 20/15 |  |
| eco | ECO | PARITY | yes | yes | 513 | 93 | 20/14 |  |
| seag | SEAG | PARITY | yes | yes | 521 | 72 | 20/15 |  |
| memb | MEMB | PARITY | yes | yes | 480 | 73 | 21/16 |  |
| options | OMON | PARITY | yes | yes | 485 | 103 | 22/17 |  |
| ostrategy | OSTR | PARITY | **no** | **no** | 527 | 71 | 21/16 |  |
| derivatives | DERV | PARITY | yes | yes | 461 | 80 | 27/22 |  |
| insiders | INSD | PARITY | yes | yes | 485 | 78 | 22/17 |  |
| deals | DEAL | PARITY | yes | yes | 484 | 71 | 23/18 |  |
| preopen | PRE | PARITY | yes | yes | 452 | 91 | 22/17 |  |
| ipo | IPO | PARITY | yes | yes | 586 | 85 | 21/16 |  |
| movers | MOV | PARITY | yes | yes | 506 | 93 | 25/20 |  |
| wrap | WRAP | PARITY | yes | yes | 548 | 74 | 21/16 |  |
| filings | CF | PARITY | yes | yes | 524 | 101 | 23/18 |  |
| margin | MRGN | PARITY | yes | yes | 435 | 72 | 21/16 |  |
| holders | HDS | PARITY | yes | yes | 522 | 75 | 21/16 |  |
| world | WEI | PARITY | yes | yes | 537 | 103 | 22/17 |  |
| desk | DESK | PARITY | yes | yes | 439 | 72 | 27/22 |  |
| markets | MKT | PARITY | yes | yes | 524 | 71 | 26/21 |  |
| events | EVTS | PARITY | yes | yes | 444 | 108 | 30/24 |  |
| overview | OVRV | PARITY | yes | yes | 491 | 101 | 21/17 |  |
| stocks | EQS | PARITY | yes | yes | 1545 | 102 | 21/17 |  |
| backtest | BTST | PARITY | yes | yes | 509 | 105 | 19/14 |  |
| positions | PORT | PARITY | yes | yes | 530 | 156 | 23/18 |  |
| broker | BRKR | PARITY | yes | yes | 494 | 102 | 23/18 |  |
| pipeline | PIPE | PARITY | yes | yes | 490 | 74 | 19/20 |  |
| scanner | LWSC | PARITY | yes | yes | 519 | 93 | 20/15 |  |
| discovery | ALFA | PARITY | **no** | **no** | 466 | 102 | 21/16 |  |
| commodity | CMDT | PARITY | yes | yes | 1111 | 112 | 23/18 |  |
| mcxgold | MCXG | PARITY | **no** | **no** | 509 | 81 | 24/19 |  |
| glassbox | GBOX | PARITY | yes | yes | 483 | 72 | 19/14 |  |
| mlengine | MLEN | PARITY | yes | yes | 517 | 87 | 19/14 |  |
| explorer | DEXP | PARITY | yes | yes | 444 | 107 | 20/15 |  |
| warehouse | WHSE | PARITY | yes | yes | 593 | 206 | 24/19 |  |
| research | RSCH | PARITY | yes | yes | 501 | 74 | 21/16 |  |
| risk | RSK | PARITY | yes | yes | 505 | 91 | 20/15 |  |
| system | SYS | PARITY | yes | yes | 767 | 346 | 22/17 |  |

### webkit: details

- **ostrategy** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8097/api/options/strategy/analyze → HTTP 403
  - B failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - B failure: failed_request: POST http://127.0.0.1:8098/api/options/strategy/analyze → HTTP 403
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **discovery** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8097/api/alpha/scan → HTTP 403
  - B failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - B failure: failed_request: POST http://127.0.0.1:8098/api/alpha/scan → HTTP 403
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **mcxgold** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8097/api/mcx/ticket → HTTP 403
  - B failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - B failure: failed_request: POST http://127.0.0.1:8098/api/mcx/ticket → HTTP 403
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /

**Overall: PARITY**
