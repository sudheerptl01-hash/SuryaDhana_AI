# Parity — A `http://127.0.0.1:8091` vs B `http://127.0.0.1:8010`

- started 2026-11-04T23:10:19+05:30 · finished 2026-11-04T23:49:56+05:30 · wait 3.0 s · retries 1
- A: 20261025-223942
- B: 20261104-230634

## chromium (156.0.8078.79): 38/42 PARITY + 1 NEW (no A side: gold)

- DIFF: ostrategy, discovery, commodity, mcxgold
- NEW pages failing their B audit: none
- audit failures — A: ostrategy, discovery, mcxgold; B: none
- differences that disappeared on retry: events
- platform-seam traffic differed (set aside): none
- expected program deltas on one side only (set aside): brief, world, broker, commodity, mcxgold
- intended structure deltas (set aside): brief, broker, commodity, mcxgold
- audit failures other than platform seams — A: ostrategy, discovery, mcxgold; B: none

| tab | code | verdict | A pass | B pass | ready A ms | ready B ms | API endpoints A/B | reasons |
|---|---|---|---|---|---:|---:|---|---|
| brief | BRF | PARITY | yes | yes | 169 | 126 | 41/40 |  |
| watch | WTCH | PARITY | yes | yes | 51 | 73 | 20/20 |  |
| charts | CHRT | PARITY | yes | yes | 44 | 57 | 16/16 |  |
| compare | COMP | PARITY | yes | yes | 79 | 51 | 18/18 |  |
| screen | FUND | PARITY | yes | yes | 76 | 47 | 16/16 |  |
| alerts | ALRT | PARITY | yes | yes | 70 | 25 | 15/15 |  |
| eco | ECO | PARITY | yes | yes | 95 | 96 | 14/14 |  |
| seag | SEAG | PARITY | yes | yes | 69 | 43 | 15/15 |  |
| memb | MEMB | PARITY | yes | yes | 45 | 46 | 16/16 |  |
| options | OMON | PARITY | yes | yes | 48 | 46 | 17/17 |  |
| ostrategy | OSTR | **DIFF** | **no** | yes | 47 | 48 | 16/16 | status classes differ: POST /api/options/strategy/analyze A['4xx'] B['2xx']; console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []; panels differ: only  |
| derivatives | DERV | PARITY | yes | yes | 47 | 50 | 22/22 |  |
| insiders | INSD | PARITY | yes | yes | 40 | 51 | 17/17 |  |
| deals | DEAL | PARITY | yes | yes | 42 | 48 | 18/18 |  |
| preopen | PRE | PARITY | yes | yes | 45 | 44 | 17/17 |  |
| ipo | IPO | PARITY | yes | yes | 46 | 36 | 16/16 |  |
| movers | MOV | PARITY | yes | yes | 47 | 48 | 21/21 |  |
| wrap | WRAP | PARITY | yes | yes | 47 | 44 | 16/16 |  |
| filings | CF | PARITY | yes | yes | 45 | 45 | 18/18 |  |
| margin | MRGN | PARITY | yes | yes | 46 | 51 | 16/16 |  |
| holders | HDS | PARITY | yes | yes | 47 | 46 | 16/16 |  |
| world | WEI | PARITY | yes | yes | 50 | 58 | 17/18 |  |
| desk | DESK | PARITY | yes | yes | 52 | 52 | 22/22 |  |
| markets | MKT | PARITY | yes | yes | 51 | 49 | 22/22 |  |
| events | EVTS | PARITY | yes | yes | 40 | 54 | 24/24 |  |
| overview | OVRV | PARITY | yes | yes | 49 | 57 | 17/17 |  |
| stocks | EQS | PARITY | yes | yes | 52 | 55 | 17/17 |  |
| backtest | BTST | PARITY | yes | yes | 57 | 51 | 14/14 |  |
| positions | PORT | PARITY | yes | yes | 97 | 83 | 18/18 |  |
| broker | BRKR | PARITY | yes | yes | 50 | 54 | 18/19 |  |
| pipeline | PIPE | PARITY | yes | yes | 65 | 58 | 20/20 |  |
| scanner | LWSC | PARITY | yes | yes | 48 | 53 | 15/15 |  |
| discovery | ALFA | **DIFF** | **no** | yes | 53 | 57 | 16/17 | API request set differs: only A [], only B ['GET /api/market/surveillance?all_flagged,symbols']; status classes differ: POST /api/alpha/scan A['4xx'] B['2xx']; console errors differ: only A ['Failed to load resource: the |
| commodity | CMDT | **DIFF** | yes | yes | 101 | 102 | 18/16 | table_headers differ: only A ['DRIVER \| AT MCX CLOSE \| NOW \| CHANGE \| IMPACT ON MCX'], only B [] |
| mcxgold | MCXG | **DIFF** | **no** | yes | 52 | 56 | 20/20 | status classes differ: POST /api/mcx/ticket A['4xx'] B['2xx']; console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []; table_headers differ: only A [], o |
| gold | GOLD | NEW | — | yes | — | 59 | —/23 |  |
| glassbox | GBOX | PARITY | yes | yes | 55 | 139 | 14/14 |  |
| mlengine | MLEN | PARITY | yes | yes | 50 | 57 | 14/14 |  |
| explorer | DEXP | PARITY | yes | yes | 57 | 60 | 15/15 |  |
| warehouse | WHSE | PARITY | yes | yes | 155 | 156 | 19/19 |  |
| research | RSCH | PARITY | yes | yes | 53 | 64 | 16/16 |  |
| risk | RSK | PARITY | yes | yes | 43 | 58 | 15/15 |  |
| system | SYS | PARITY | yes | yes | 361 | 317 | 17/17 |  |

### chromium: details

- **ostrategy** (DIFF)
  - reason: status classes differ: POST /api/options/strategy/analyze A['4xx'] B['2xx']
  - reason: console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []
  - reason: panels differ: only A [], only B ['Margin & costs — ESTIMATE']
  - reason: error boxes: A ['▲ blocked by desktop-qa scratch server (--block-mutations)'] vs B []
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8091/api/options/strategy/analyze → HTTP 403
  - note: attempt 1 differed: ["status classes differ: POST /api/options/strategy/analyze A['4xx'] B['2xx']", "console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []", "panels differ: only A [], only B ['Margin & costs — ESTIMATE']"]
- **discovery** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/market/surveillance?all_flagged,symbols']
  - reason: status classes differ: POST /api/alpha/scan A['4xx'] B['2xx']
  - reason: console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []
  - reason: table_headers differ: only A [], only B ['| TICKER | SIGNAL DATE | LTP / CLOSE | CHG% | NET #D']
  - reason: tables: A 0 vs B 1
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8091/api/alpha/scan → HTTP 403
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/market/surveillance?all_flagged,symbols']", "status classes differ: POST /api/alpha/scan A['4xx'] B['2xx']", "console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], on
- **commodity** (DIFF)
  - reason: table_headers differ: only A ['DRIVER | AT MCX CLOSE | NOW | CHANGE | IMPACT ON MCX'], only B []
  - note: attempt 1 differed: ["table_headers differ: only A ['DRIVER | AT MCX CLOSE | NOW | CHANGE | IMPACT ON MCX'], only B []"]
  - note: expected program deltas set aside: only A {'GET /api/commodity/gold-preopen/log?threshold': 'gold-preopen-moved', 'GET /api/commodity/gold-preopen?eurusd_trigger,threshold': 'gold-preopen-moved'} · only B {}
  - note: expected structure deltas set aside (PLAN §b: CMDT drops <GoldPreOpen /> (desk, gap waterfall, inputs, context table, headlines, manual checks, accuracy log) and '· Gold desk' from its label/subtitle; the gold board tile gains a GOLD › chip): page_headers {'a_only': ['CMDT Commodity Desk'], 'b_only'
- **mcxgold** (DIFF)
  - reason: status classes differ: POST /api/mcx/ticket A['4xx'] B['2xx']
  - reason: console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []
  - reason: table_headers differ: only A [], only B ['Leg | Brokerage | Exch # | CTT # (sell) | Stamp (buy) | SEBI | GST # | Total']
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8091/api/mcx/ticket → HTTP 403
  - note: attempt 1 differed: ["status classes differ: POST /api/mcx/ticket A['4xx'] B['2xx']", "console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []", "table_headers differ: only A [], only B ['Leg | Brokerage | Exch # | CTT # (sell) | Stam
  - note: expected program deltas set aside: only A {'GET /api/mcx/specs': 'gold-mcxg-specs-replaced'} · only B {'GET /api/gold/contracts?exchange': 'gold-mcxg-selector'}
  - note: expected structure deltas set aside (PLAN §b: MCXG's overlay shrinks to one line in the Quote panel (/api/mcx/overlay, GOLD › chip) and its specs card is replaced by the shared contract selector (c.selector, adds GOLDTEN); the subtitle follows): panels {'a_only': ['COMEX × rupee overlay', 'Contract 

## webkit (26.4): 38/42 PARITY + 1 NEW (no A side: gold)

- DIFF: ostrategy, discovery, commodity, mcxgold
- NEW pages failing their B audit: none
- audit failures — A: brief, ostrategy, discovery, mcxgold; B: none
- differences that disappeared on retry: events
- platform-seam traffic differed (set aside): brief
- expected program deltas on one side only (set aside): brief, world, broker, commodity, mcxgold
- intended structure deltas (set aside): brief, broker, commodity, mcxgold
- audit failures other than platform seams — A: ostrategy, discovery, mcxgold; B: none

| tab | code | verdict | A pass | B pass | ready A ms | ready B ms | API endpoints A/B | reasons |
|---|---|---|---|---|---:|---:|---|---|
| brief | BRF | PARITY | **no** | yes | 202 | 176 | 41/40 |  |
| watch | WTCH | PARITY | yes | yes | 97 | 97 | 20/20 |  |
| charts | CHRT | PARITY | yes | yes | 102 | 67 | 16/16 |  |
| compare | COMP | PARITY | yes | yes | 98 | 100 | 18/18 |  |
| screen | FUND | PARITY | yes | yes | 99 | 99 | 16/16 |  |
| alerts | ALRT | PARITY | yes | yes | 100 | 99 | 15/15 |  |
| eco | ECO | PARITY | yes | yes | 165 | 257 | 14/14 |  |
| seag | SEAG | PARITY | yes | yes | 103 | 100 | 15/15 |  |
| memb | MEMB | PARITY | yes | yes | 94 | 102 | 16/16 |  |
| options | OMON | PARITY | yes | yes | 100 | 100 | 17/17 |  |
| ostrategy | OSTR | **DIFF** | **no** | yes | 69 | 105 | 16/16 | status classes differ: POST /api/options/strategy/analyze A['4xx'] B['2xx']; console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []; panels differ: only  |
| derivatives | DERV | PARITY | yes | yes | 97 | 103 | 22/22 |  |
| insiders | INSD | PARITY | yes | yes | 99 | 108 | 17/17 |  |
| deals | DEAL | PARITY | yes | yes | 99 | 101 | 18/18 |  |
| preopen | PRE | PARITY | yes | yes | 102 | 104 | 17/17 |  |
| ipo | IPO | PARITY | yes | yes | 107 | 104 | 16/16 |  |
| movers | MOV | PARITY | yes | yes | 117 | 124 | 21/21 |  |
| wrap | WRAP | PARITY | yes | yes | 101 | 115 | 16/16 |  |
| filings | CF | PARITY | yes | yes | 100 | 108 | 18/18 |  |
| margin | MRGN | PARITY | yes | yes | 104 | 109 | 16/16 |  |
| holders | HDS | PARITY | yes | yes | 102 | 108 | 16/16 |  |
| world | WEI | PARITY | yes | yes | 108 | 108 | 17/18 |  |
| desk | DESK | PARITY | yes | yes | 107 | 157 | 22/22 |  |
| markets | MKT | PARITY | yes | yes | 82 | 81 | 22/22 |  |
| events | EVTS | PARITY | yes | yes | 108 | 84 | 24/24 |  |
| overview | OVRV | PARITY | yes | yes | 106 | 87 | 17/17 |  |
| stocks | EQS | PARITY | yes | yes | 84 | 87 | 17/17 |  |
| backtest | BTST | PARITY | yes | yes | 105 | 114 | 14/14 |  |
| positions | PORT | PARITY | yes | yes | 140 | 134 | 18/18 |  |
| broker | BRKR | PARITY | yes | yes | 85 | 114 | 18/19 |  |
| pipeline | PIPE | PARITY | yes | yes | 110 | 128 | 20/20 |  |
| scanner | LWSC | PARITY | yes | yes | 110 | 114 | 15/15 |  |
| discovery | ALFA | **DIFF** | **no** | yes | 96 | 119 | 16/17 | API request set differs: only A [], only B ['GET /api/market/surveillance?all_flagged,symbols']; status classes differ: POST /api/alpha/scan A['4xx'] B['2xx']; console errors differ: only A ['Failed to load resource: the |
| commodity | CMDT | **DIFF** | yes | yes | 115 | 118 | 18/16 | table_headers differ: only A ['DRIVER \| AT MCX CLOSE \| NOW \| CHANGE \| IMPACT ON MCX'], only B [] |
| mcxgold | MCXG | **DIFF** | **no** | yes | 116 | 121 | 20/20 | status classes differ: POST /api/mcx/ticket A['4xx'] B['2xx']; console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []; table_headers differ: only A [], o |
| gold | GOLD | NEW | — | yes | — | 87 | —/23 |  |
| glassbox | GBOX | PARITY | yes | yes | 129 | 134 | 14/14 |  |
| mlengine | MLEN | PARITY | yes | yes | 124 | 145 | 14/14 |  |
| explorer | DEXP | PARITY | yes | yes | 150 | 89 | 15/15 |  |
| warehouse | WHSE | PARITY | yes | yes | 227 | 173 | 19/19 |  |
| research | RSCH | PARITY | yes | yes | 116 | 95 | 16/16 |  |
| risk | RSK | PARITY | yes | yes | 109 | 126 | 15/15 |  |
| system | SYS | PARITY | yes | yes | 429 | 374 | 17/17 |  |

### webkit: details

- **brief** (PARITY)
  - A failure: failed_request: GET http://127.0.0.1:8091/api/health → cancelled (cancelled by the page: client timeout / AbortController)
  - note: platform seams differ (set aside): A {'GET /api/health': ['2xx', 'ERR'], 'GET /api/prefs': ['2xx']} ['GET api/health → cancelled (cancelled by the page: client timeout / AbortController)'] · B {'GET /api/health': ['2xx'], 'GET /api/prefs': ['2xx']} []
  - note: expected program deltas set aside: only A {'GET /api/commodity/gold-preopen': 'gold-preopen-moved', 'GET /api/commodity/gold-preopen/log?threshold': 'gold-preopen-moved'} · only B {'GET /api/gold/health?window': 'gold-health-line'}
  - note: expected structure deltas set aside (PLAN §b: BRF's 'Gold open (MCX)' panel becomes one Line in the Market panel (from /api/gold/health.line)): panels {'a_only': ['Gold open (MCX)'], 'b_only': []}
- **ostrategy** (DIFF)
  - reason: status classes differ: POST /api/options/strategy/analyze A['4xx'] B['2xx']
  - reason: console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []
  - reason: panels differ: only A [], only B ['Margin & costs — ESTIMATE']
  - reason: error boxes: A ['▲ blocked by desktop-qa scratch server (--block-mutations)'] vs B []
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8091/api/options/strategy/analyze → HTTP 403
  - note: attempt 1 differed: ["status classes differ: POST /api/options/strategy/analyze A['4xx'] B['2xx']", "console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []", "panels differ: only A [], only B ['Margin & costs — ESTIMATE']"]
- **discovery** (DIFF)
  - reason: API request set differs: only A [], only B ['GET /api/market/surveillance?all_flagged,symbols']
  - reason: status classes differ: POST /api/alpha/scan A['4xx'] B['2xx']
  - reason: console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []
  - reason: table_headers differ: only A [], only B ['| TICKER | SIGNAL DATE | LTP / CLOSE | CHG% | NET #D']
  - reason: tables: A 0 vs B 1
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8091/api/alpha/scan → HTTP 403
  - note: attempt 1 differed: ["API request set differs: only A [], only B ['GET /api/market/surveillance?all_flagged,symbols']", "status classes differ: POST /api/alpha/scan A['4xx'] B['2xx']", "console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], on
- **commodity** (DIFF)
  - reason: table_headers differ: only A ['DRIVER | AT MCX CLOSE | NOW | CHANGE | IMPACT ON MCX'], only B []
  - note: attempt 1 differed: ["table_headers differ: only A ['DRIVER | AT MCX CLOSE | NOW | CHANGE | IMPACT ON MCX'], only B []"]
  - note: expected program deltas set aside: only A {'GET /api/commodity/gold-preopen/log?threshold': 'gold-preopen-moved', 'GET /api/commodity/gold-preopen?eurusd_trigger,threshold': 'gold-preopen-moved'} · only B {}
  - note: expected structure deltas set aside (PLAN §b: CMDT drops <GoldPreOpen /> (desk, gap waterfall, inputs, context table, headlines, manual checks, accuracy log) and '· Gold desk' from its label/subtitle; the gold board tile gains a GOLD › chip): page_headers {'a_only': ['CMDT Commodity Desk'], 'b_only'
- **mcxgold** (DIFF)
  - reason: status classes differ: POST /api/mcx/ticket A['4xx'] B['2xx']
  - reason: console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []
  - reason: table_headers differ: only A [], only B ['Leg | Brokerage | Exch # | CTT # (sell) | Stamp (buy) | SEBI | GST # | Total']
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8091/api/mcx/ticket → HTTP 403
  - note: attempt 1 differed: ["status classes differ: POST /api/mcx/ticket A['4xx'] B['2xx']", "console errors differ: only A ['Failed to load resource: the server responded with a status of # (Forbidden)'], only B []", "table_headers differ: only A [], only B ['Leg | Brokerage | Exch # | CTT # (sell) | Stam
  - note: expected program deltas set aside: only A {'GET /api/mcx/specs': 'gold-mcxg-specs-replaced'} · only B {'GET /api/gold/contracts?exchange': 'gold-mcxg-selector'}
  - note: expected structure deltas set aside (PLAN §b: MCXG's overlay shrinks to one line in the Quote panel (/api/mcx/overlay, GOLD › chip) and its specs card is replaced by the shared contract selector (c.selector, adds GOLDTEN); the subtitle follows): panels {'a_only': ['COMEX × rupee overlay', 'Contract 

**Overall: DIFF**
