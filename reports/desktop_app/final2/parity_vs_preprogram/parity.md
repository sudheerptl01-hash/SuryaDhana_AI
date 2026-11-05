# Parity — A `http://127.0.0.1:8090` vs B `http://127.0.0.1:8091`

- started 2026-10-25T22:44:03+05:30 · finished 2026-10-25T23:51:28+05:30 · wait 3.0 s · retries 1
- A: pre-program UI (24 Oct 10:38, reconstructed)
- B: final release 20261025-223942-0ae66db

## chromium (155.0.8059.85): 2/42 PARITY

- DIFF: watch, charts, compare, screen, alerts, eco, seag, memb, options, ostrategy, derivatives, insiders, deals, preopen, ipo, movers, wrap, filings, margin, holders, world, desk, markets, events, overview, stocks, backtest, positions, pipeline, scanner, discovery, commodity, mcxgold, glassbox, mlengine, explorer, warehouse, research, risk, system
- audit failures — A: ostrategy, discovery, mcxgold; B: ostrategy, discovery, mcxgold
- differences that disappeared on retry: none
- platform-seam traffic differed (set aside): brief, watch, charts, compare, screen, alerts, eco, seag, memb, options, ostrategy, derivatives, insiders, deals, preopen, ipo, movers, wrap, filings, margin, holders, world, desk, markets, events, overview, stocks, backtest, positions, broker, pipeline, scanner, discovery, commodity, mcxgold, glassbox, mlengine, explorer, warehouse, research, risk, system
- expected program deltas on one side only (set aside): brief, watch, charts, compare, screen, alerts, eco, seag, memb, options, ostrategy, derivatives, insiders, deals, preopen, ipo, movers, wrap, filings, margin, holders, world, desk, markets, events, overview, stocks, backtest, positions, broker, pipeline, scanner, discovery, commodity, mcxgold, glassbox, mlengine, explorer, warehouse, research, risk, system
- audit failures other than platform seams — A: ostrategy, discovery, mcxgold; B: ostrategy, discovery, mcxgold

| tab | code | verdict | A pass | B pass | ready A ms | ready B ms | API endpoints A/B | reasons |
|---|---|---|---|---|---:|---:|---|---|
| brief | BRF | PARITY | yes | yes | 1040 | 147 | 48/42 |  |
| watch | WTCH | **DIFF** | yes | yes | 493 | 51 | 25/21 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| charts | CHRT | **DIFF** | yes | yes | 452 | 68 | 21/17 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| compare | COMP | **DIFF** | yes | yes | 454 | 84 | 23/19 | API request set differs: only A [], only B ['GET /api/positions/connection-status']; table_headers differ: only A ['\| TCS \| INFY \| HCLTECH'], only B ['\| TCS \| INFY'] |
| screen | FUND | **DIFF** | yes | yes | 446 | 48 | 21/17 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| alerts | ALRT | **DIFF** | yes | yes | 437 | 47 | 20/16 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| eco | ECO | **DIFF** | yes | yes | 505 | 85 | 20/15 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| seag | SEAG | **DIFF** | yes | yes | 452 | 44 | 20/16 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| memb | MEMB | **DIFF** | yes | yes | 449 | 43 | 21/17 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| options | OMON | **DIFF** | yes | yes | 453 | 44 | 22/18 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| ostrategy | OSTR | **DIFF** | **no** | **no** | 446 | 48 | 21/17 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| derivatives | DERV | **DIFF** | yes | yes | 457 | 50 | 27/23 | API request set differs: only A [], only B ['GET /api/positions/connection-status']; table_headers differ: only A ['Series \| Expiry \| DTE \| Close \| Basis \| Ann % \| OI (shares) \| OI chg \| Contracts'], only B ['Series \| Ex |
| insiders | INSD | **DIFF** | yes | yes | 452 | 46 | 22/18 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| deals | DEAL | **DIFF** | yes | yes | 500 | 50 | 23/19 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| preopen | PRE | **DIFF** | yes | yes | 459 | 50 | 22/18 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| ipo | IPO | **DIFF** | yes | yes | 453 | 50 | 21/17 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| movers | MOV | **DIFF** | yes | yes | 441 | 51 | 25/21 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| wrap | WRAP | **DIFF** | yes | yes | 458 | 50 | 21/17 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| filings | CF | **DIFF** | yes | yes | 459 | 52 | 23/19 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| margin | MRGN | **DIFF** | yes | yes | 456 | 56 | 21/17 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| holders | HDS | **DIFF** | yes | yes | 463 | 36 | 21/17 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| world | WEI | **DIFF** | yes | yes | 463 | 55 | 22/18 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| desk | DESK | **DIFF** | yes | yes | 459 | 54 | 27/23 | API request set differs: only A [], only B ['GET /api/positions/connection-status']; table_headers differ: only A ['# ↕ \| Stock ↕ \| Industry ↕ \| # ↕ \| # ↕ \| Last ↕ \| P/E ↕ \| Profit y/y ↕ \| Next event'], only B ['# ↕ \| St |
| markets | MKT | **DIFF** | yes | yes | 463 | 53 | 26/22 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| events | EVTS | **DIFF** | yes | yes | 459 | 59 | 30/25 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| overview | OVRV | **DIFF** | yes | yes | 520 | 60 | 21/18 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| stocks | EQS | **DIFF** | yes | yes | 778 | 67 | 21/18 | API request set differs: only A [], only B ['GET /api/positions/connection-status']; table_headers differ: only A ['Ticker ↑ \| Company \| Nifty \| Midcap \| Cap Type \| Event \| CMP ₹ ↕ \| P/E ↕ \| Mkt Cap Cr ↕ \| Div Yld% ↕ \| N |
| backtest | BTST | **DIFF** | yes | yes | 470 | 63 | 19/15 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| positions | PORT | **DIFF** | yes | yes | 469 | 112 | 23/18 | page_headers differ: only A ['PORT Execution Engine'], only B ['PORT Portfolio · Legacy Engine'] |
| broker | BRKR | PARITY | yes | yes | 512 | 65 | 23/18 |  |
| pipeline | PIPE | **DIFF** | yes | yes | 468 | 65 | 19/21 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| scanner | LWSC | **DIFF** | yes | yes | 502 | 66 | 20/16 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| discovery | ALFA | **DIFF** | **no** | **no** | 457 | 159 | 21/17 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| commodity | CMDT | **DIFF** | yes | yes | 481 | 112 | 23/19 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| mcxgold | MCXG | **DIFF** | **no** | **no** | 473 | 69 | 24/20 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| glassbox | GBOX | **DIFF** | yes | yes | 471 | 69 | 19/15 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| mlengine | MLEN | **DIFF** | yes | yes | 460 | 53 | 19/15 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| explorer | DEXP | **DIFF** | yes | yes | 475 | 78 | 20/16 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| warehouse | WHSE | **DIFF** | yes | yes | 529 | 126 | 24/20 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| research | RSCH | **DIFF** | yes | yes | 526 | 76 | 21/17 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| risk | RSK | **DIFF** | yes | yes | 484 | 56 | 20/16 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| system | SYS | **DIFF** | yes | yes | 734 | 333 | 22/18 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |

### chromium: details

- **watch** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **charts** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **compare** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - reason: table_headers differ: only A ['| TCS | INFY | HCLTECH'], only B ['| TCS | INFY']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']", "table_headers differ: only A ['| TCS | INFY | HCLTECH'], only B ['| TCS | INFY']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **screen** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **alerts** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **eco** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **seag** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **memb** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **options** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **ostrategy** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8090/api/options/strategy/analyze → HTTP 403
  - B failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - B failure: failed_request: POST http://127.0.0.1:8091/api/options/strategy/analyze → HTTP 403
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **derivatives** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - reason: table_headers differ: only A ['Series | Expiry | DTE | Close | Basis | Ann % | OI (shares) | OI chg | Contracts'], only B ['Series | Expiry | DTE | Close | Basis | Ann % | OI (shares · L) | OI chg · L | Contracts']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']", "table_headers differ: only A ['Series | Expiry | DTE | Close | Basis | Ann % | OI (shares) | OI chg | Contracts'], only B ['Series | Expiry | DTE | Close | Basis | Ann % | OI (shares · L) | O
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **insiders** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **deals** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **preopen** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **ipo** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **movers** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **wrap** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **filings** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **margin** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **holders** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **world** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **desk** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - reason: table_headers differ: only A ['# ↕ | Stock ↕ | Industry ↕ | # ↕ | # ↕ | Last ↕ | P/E ↕ | Profit y/y ↕ | Next event'], only B ['# ↕ | Stock ↕ | Industry ↕ | Last ↕ | # ↕ | # ↕ | Next event | P/E ↕ | Profit y/y ↕']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']", "table_headers differ: only A ['# ↕ | Stock ↕ | Industry ↕ | # ↕ | # ↕ | Last ↕ | P/E ↕ | Profit y/y ↕ | Next event'], only B ['# ↕ | Stock ↕ | Industry ↕ | Last ↕ | # ↕ | # ↕ | Next event | P
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **markets** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **events** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **overview** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /api/pipeline/rl-status': 'w2-pipeline-pipe-only', 'GET /api/pipelin
- **stocks** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - reason: table_headers differ: only A ['Ticker ↑ | Company | Nifty | Midcap | Cap Type | Event | CMP ₹ ↕ | P/E ↕ | Mkt Cap Cr ↕ | Div Yld% ↕ | NP Qtr Cr ↕ | Sales Qtr Cr ↕ | ROCE% ↕ | Data% ↕ | Health | Watch'], only B ['★ | Ticker ↑ | Company · Sector | Nifty | Midcap | Cap Type | Event | CMP ₹ ↕ | P/E ↕ | Mkt Cap Cr ↕ | Div Yld% ↕ | NP Qtr Cr ↕ | Sales Qtr Cr ↕ | ROCE% ↕ | Data% ↕']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']", "table_headers differ: only A ['Ticker ↑ | Company | Nifty | Midcap | Cap Type | Event | CMP ₹ ↕ | P/E ↕ | Mkt Cap Cr ↕ | Div Yld% ↕ | NP Qtr Cr ↕ | Sales Qtr Cr ↕ | ROCE% ↕ | Data% ↕ | Health
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **backtest** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **positions** (DIFF)
  - reason: page_headers differ: only A ['PORT Execution Engine'], only B ['PORT Portfolio · Legacy Engine']
  - note: attempt 1 differed: ["page_headers differ: only A ['PORT Execution Engine'], only B ['PORT Portfolio · Legacy Engine']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **pipeline** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/stocks/list?limit,search,skip': 'w2-stock-list-eqs-only'} · only B {'GET /api/market/eco-calendar?ahead,back': 'header-holidays'}
- **scanner** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **discovery** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8090/api/alpha/scan → HTTP 403
  - B failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - B failure: failed_request: POST http://127.0.0.1:8091/api/alpha/scan → HTTP 403
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **commodity** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **mcxgold** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8090/api/mcx/ticket → HTTP 403
  - B failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - B failure: failed_request: POST http://127.0.0.1:8091/api/mcx/ticket → HTTP 403
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **glassbox** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **mlengine** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **explorer** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **warehouse** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **research** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **risk** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **system** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /

## webkit (26.4): 2/42 PARITY

- DIFF: watch, charts, compare, screen, alerts, eco, seag, memb, options, ostrategy, derivatives, insiders, deals, preopen, ipo, movers, wrap, filings, margin, holders, world, desk, markets, events, overview, stocks, backtest, positions, pipeline, scanner, discovery, commodity, mcxgold, glassbox, mlengine, explorer, warehouse, research, risk, system
- audit failures — A: ostrategy, discovery, mcxgold; B: ostrategy, discovery, mcxgold
- differences that disappeared on retry: none
- platform-seam traffic differed (set aside): brief, watch, charts, compare, screen, alerts, eco, seag, memb, options, ostrategy, derivatives, insiders, deals, preopen, ipo, movers, wrap, filings, margin, holders, world, desk, markets, events, overview, stocks, backtest, positions, broker, pipeline, scanner, discovery, commodity, mcxgold, glassbox, mlengine, explorer, warehouse, research, risk, system
- expected program deltas on one side only (set aside): brief, watch, charts, compare, screen, alerts, eco, seag, memb, options, ostrategy, derivatives, insiders, deals, preopen, ipo, movers, wrap, filings, margin, holders, world, desk, markets, events, overview, stocks, backtest, positions, broker, pipeline, scanner, discovery, commodity, mcxgold, glassbox, mlengine, explorer, warehouse, research, risk, system
- audit failures other than platform seams — A: ostrategy, discovery, mcxgold; B: ostrategy, discovery, mcxgold

| tab | code | verdict | A pass | B pass | ready A ms | ready B ms | API endpoints A/B | reasons |
|---|---|---|---|---|---:|---:|---|---|
| brief | BRF | PARITY | yes | yes | 875 | 191 | 48/42 |  |
| watch | WTCH | **DIFF** | yes | yes | 519 | 101 | 25/21 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| charts | CHRT | **DIFF** | yes | yes | 545 | 101 | 21/17 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| compare | COMP | **DIFF** | yes | yes | 487 | 101 | 23/19 | API request set differs: only A [], only B ['GET /api/positions/connection-status']; table_headers differ: only A ['\| TCS \| INFY \| HCLTECH'], only B ['\| TCS \| INFY'] |
| screen | FUND | **DIFF** | yes | yes | 663 | 102 | 21/17 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| alerts | ALRT | **DIFF** | yes | yes | 523 | 102 | 20/16 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| eco | ECO | **DIFF** | yes | yes | 528 | 172 | 20/15 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| seag | SEAG | **DIFF** | yes | yes | 520 | 69 | 20/16 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| memb | MEMB | **DIFF** | yes | yes | 516 | 107 | 21/17 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| options | OMON | **DIFF** | yes | yes | 483 | 103 | 22/18 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| ostrategy | OSTR | **DIFF** | **no** | **no** | 516 | 108 | 21/17 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| derivatives | DERV | **DIFF** | yes | yes | 519 | 82 | 27/23 | API request set differs: only A [], only B ['GET /api/positions/connection-status']; table_headers differ: only A ['Series \| Expiry \| DTE \| Close \| Basis \| Ann % \| OI (shares) \| OI chg \| Contracts'], only B ['Series \| Ex |
| insiders | INSD | **DIFF** | yes | yes | 481 | 108 | 22/18 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| deals | DEAL | **DIFF** | yes | yes | 520 | 84 | 23/19 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| preopen | PRE | **DIFF** | yes | yes | 519 | 79 | 22/18 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| ipo | IPO | **DIFF** | yes | yes | 521 | 84 | 21/17 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| movers | MOV | **DIFF** | yes | yes | 526 | 130 | 25/21 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| wrap | WRAP | **DIFF** | yes | yes | 486 | 115 | 21/17 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| filings | CF | **DIFF** | yes | yes | 485 | 121 | 23/19 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| margin | MRGN | **DIFF** | yes | yes | 520 | 123 | 21/17 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| holders | HDS | **DIFF** | yes | yes | 522 | 117 | 21/17 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| world | WEI | **DIFF** | yes | yes | 507 | 83 | 22/18 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| desk | DESK | **DIFF** | yes | yes | 490 | 97 | 27/23 | API request set differs: only A [], only B ['GET /api/positions/connection-status']; table_headers differ: only A ['# ↕ \| Stock ↕ \| Industry ↕ \| # ↕ \| # ↕ \| Last ↕ \| P/E ↕ \| Profit y/y ↕ \| Next event'], only B ['# ↕ \| St |
| markets | MKT | **DIFF** | yes | yes | 544 | 96 | 26/22 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| events | EVTS | **DIFF** | yes | yes | 542 | 98 | 30/25 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| overview | OVRV | **DIFF** | yes | yes | 600 | 125 | 21/18 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| stocks | EQS | **DIFF** | yes | yes | 1249 | 122 | 21/18 | API request set differs: only A [], only B ['GET /api/positions/connection-status']; table_headers differ: only A ['Ticker ↑ \| Company \| Nifty \| Midcap \| Cap Type \| Event \| CMP ₹ ↕ \| P/E ↕ \| Mkt Cap Cr ↕ \| Div Yld% ↕ \| N |
| backtest | BTST | **DIFF** | yes | yes | 546 | 142 | 19/15 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| positions | PORT | **DIFF** | yes | yes | 596 | 132 | 23/18 | page_headers differ: only A ['PORT Execution Engine'], only B ['PORT Portfolio · Legacy Engine'] |
| broker | BRKR | PARITY | yes | yes | 541 | 126 | 23/18 |  |
| pipeline | PIPE | **DIFF** | yes | yes | 523 | 101 | 19/21 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| scanner | LWSC | **DIFF** | yes | yes | 538 | 148 | 20/16 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| discovery | ALFA | **DIFF** | **no** | **no** | 537 | 131 | 21/17 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| commodity | CMDT | **DIFF** | yes | yes | 607 | 116 | 23/19 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| mcxgold | MCXG | **DIFF** | **no** | **no** | 496 | 136 | 24/20 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| glassbox | GBOX | **DIFF** | yes | yes | 544 | 143 | 19/15 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| mlengine | MLEN | **DIFF** | yes | yes | 538 | 149 | 19/15 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| explorer | DEXP | **DIFF** | yes | yes | 504 | 161 | 20/16 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| warehouse | WHSE | **DIFF** | yes | yes | 627 | 284 | 24/20 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| research | RSCH | **DIFF** | yes | yes | 499 | 107 | 21/17 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| risk | RSK | **DIFF** | yes | yes | 570 | 109 | 20/16 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |
| system | SYS | **DIFF** | yes | yes | 809 | 371 | 22/18 | API request set differs: only A [], only B ['GET /api/positions/connection-status'] |

### webkit: details

- **watch** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **charts** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **compare** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - reason: table_headers differ: only A ['| TCS | INFY | HCLTECH'], only B ['| TCS | INFY']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']", "table_headers differ: only A ['| TCS | INFY | HCLTECH'], only B ['| TCS | INFY']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **screen** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **alerts** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **eco** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **seag** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **memb** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **options** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **ostrategy** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8090/api/options/strategy/analyze → HTTP 403
  - B failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - B failure: failed_request: POST http://127.0.0.1:8091/api/options/strategy/analyze → HTTP 403
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **derivatives** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - reason: table_headers differ: only A ['Series | Expiry | DTE | Close | Basis | Ann % | OI (shares) | OI chg | Contracts'], only B ['Series | Expiry | DTE | Close | Basis | Ann % | OI (shares · L) | OI chg · L | Contracts']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']", "table_headers differ: only A ['Series | Expiry | DTE | Close | Basis | Ann % | OI (shares) | OI chg | Contracts'], only B ['Series | Expiry | DTE | Close | Basis | Ann % | OI (shares · L) | O
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **insiders** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **deals** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **preopen** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **ipo** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **movers** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **wrap** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **filings** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **margin** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **holders** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **world** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **desk** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - reason: table_headers differ: only A ['# ↕ | Stock ↕ | Industry ↕ | # ↕ | # ↕ | Last ↕ | P/E ↕ | Profit y/y ↕ | Next event'], only B ['# ↕ | Stock ↕ | Industry ↕ | Last ↕ | # ↕ | # ↕ | Next event | P/E ↕ | Profit y/y ↕']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']", "table_headers differ: only A ['# ↕ | Stock ↕ | Industry ↕ | # ↕ | # ↕ | Last ↕ | P/E ↕ | Profit y/y ↕ | Next event'], only B ['# ↕ | Stock ↕ | Industry ↕ | Last ↕ | # ↕ | # ↕ | Next event | P
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **markets** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **events** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **overview** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /api/pipeline/rl-status': 'w2-pipeline-pipe-only', 'GET /api/pipelin
- **stocks** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - reason: table_headers differ: only A ['Ticker ↑ | Company | Nifty | Midcap | Cap Type | Event | CMP ₹ ↕ | P/E ↕ | Mkt Cap Cr ↕ | Div Yld% ↕ | NP Qtr Cr ↕ | Sales Qtr Cr ↕ | ROCE% ↕ | Data% ↕ | Health | Watch'], only B ['★ | Ticker ↑ | Company · Sector | Nifty | Midcap | Cap Type | Event | CMP ₹ ↕ | P/E ↕ | Mkt Cap Cr ↕ | Div Yld% ↕ | NP Qtr Cr ↕ | Sales Qtr Cr ↕ | ROCE% ↕ | Data% ↕']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']", "table_headers differ: only A ['Ticker ↑ | Company | Nifty | Midcap | Cap Type | Event | CMP ₹ ↕ | P/E ↕ | Mkt Cap Cr ↕ | Div Yld% ↕ | NP Qtr Cr ↕ | Sales Qtr Cr ↕ | ROCE% ↕ | Data% ↕ | Health
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **backtest** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **positions** (DIFF)
  - reason: page_headers differ: only A ['PORT Execution Engine'], only B ['PORT Portfolio · Legacy Engine']
  - note: attempt 1 differed: ["page_headers differ: only A ['PORT Execution Engine'], only B ['PORT Portfolio · Legacy Engine']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **pipeline** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/stocks/list?limit,search,skip': 'w2-stock-list-eqs-only'} · only B {'GET /api/market/eco-calendar?ahead,back': 'header-holidays'}
- **scanner** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **discovery** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8090/api/alpha/scan → HTTP 403
  - B failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - B failure: failed_request: POST http://127.0.0.1:8091/api/alpha/scan → HTTP 403
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **commodity** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']", "status classes differ: GET /api/commodity/gold-preopen/log?threshold A['ERR'] B['2xx']", "panels differ: only A [], only B ['Accuracy log', 'Context', 'Gap build-up']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **mcxgold** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8090/api/mcx/ticket → HTTP 403
  - B failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - B failure: failed_request: POST http://127.0.0.1:8091/api/mcx/ticket → HTTP 403
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **glassbox** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **mlengine** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **explorer** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **warehouse** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **research** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **risk** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /
- **system** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/positions/connection-status']
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/positions/connection-status']"]
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/dashboard/enrichment-status': 'w2-enrichment-ovrv-only', 'GET /api/pipeline/data-quality': 'w2-pipeline-pipe-only', 'GET /api/pipeline/feature-importance': 'w2-pipeline-pipe-only', 'GET /api/pipeline/model-metrics': 'w2-pipeline-pipe-only', 'GET /

**Overall: DIFF**
