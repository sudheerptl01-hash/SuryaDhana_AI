# Parity — A `http://127.0.0.1:8097` vs B `http://127.0.0.1:8098`

- started 2026-10-25T12:51:43+05:30 · finished 2026-10-25T12:55:02+05:30 · wait 3.0 s · retries 1
- A: pre-program baseline (:8097, --block-mutations)
- B: copy of live release 20261025-114737-0ae66db (:8098, --block-mutations)

## chromium (155.0.8059.85): 4/4 PARITY

- DIFF: none
- audit failures — A: ostrategy, discovery, mcxgold; B: ostrategy, discovery, mcxgold
- differences that disappeared on retry: none
- platform-seam traffic differed (set aside): ostrategy, discovery, mcxgold, brief
- audit failures other than platform seams — A: ostrategy, discovery, mcxgold; B: ostrategy, discovery, mcxgold

| tab | code | verdict | A pass | B pass | ready A ms | ready B ms | API endpoints A/B | reasons |
|---|---|---|---|---|---:|---:|---|---|
| ostrategy | OSTR | PARITY | **no** | **no** | 859 | 536 | 21/22 |  |
| discovery | ALFA | PARITY | **no** | **no** | 461 | 467 | 21/22 |  |
| mcxgold | MCXG | PARITY | **no** | **no** | 505 | 453 | 24/25 |  |
| brief | BRF | PARITY | yes | yes | 462 | 214 | 48/49 |  |

### chromium: details

- **ostrategy** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8097/api/options/strategy/analyze → HTTP 403
  - B failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - B failure: failed_request: POST http://127.0.0.1:8098/api/options/strategy/analyze → HTTP 403
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/prefs': ['2xx']} []
- **discovery** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8097/api/alpha/scan → HTTP 403
  - B failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - B failure: failed_request: POST http://127.0.0.1:8098/api/alpha/scan → HTTP 403
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/prefs': ['2xx']} []
- **mcxgold** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8097/api/mcx/ticket → HTTP 403
  - B failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - B failure: failed_request: POST http://127.0.0.1:8098/api/mcx/ticket → HTTP 403
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/prefs': ['2xx']} []

## webkit (26.4): 4/4 PARITY

- DIFF: none
- audit failures — A: ostrategy, discovery, mcxgold; B: ostrategy, discovery, mcxgold
- differences that disappeared on retry: none
- platform-seam traffic differed (set aside): ostrategy, discovery, mcxgold, brief
- audit failures other than platform seams — A: ostrategy, discovery, mcxgold; B: ostrategy, discovery, mcxgold

| tab | code | verdict | A pass | B pass | ready A ms | ready B ms | API endpoints A/B | reasons |
|---|---|---|---|---|---:|---:|---|---|
| ostrategy | OSTR | PARITY | **no** | **no** | 861 | 518 | 21/22 |  |
| discovery | ALFA | PARITY | **no** | **no** | 454 | 537 | 21/22 |  |
| mcxgold | MCXG | PARITY | **no** | **no** | 138 | 501 | 24/25 |  |
| brief | BRF | PARITY | yes | yes | 468 | 454 | 48/49 |  |

### webkit: details

- **ostrategy** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8097/api/options/strategy/analyze → HTTP 403
  - B failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - B failure: failed_request: POST http://127.0.0.1:8098/api/options/strategy/analyze → HTTP 403
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/prefs': ['2xx']} []
- **discovery** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8097/api/alpha/scan → HTTP 403
  - B failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - B failure: failed_request: POST http://127.0.0.1:8098/api/alpha/scan → HTTP 403
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/prefs': ['2xx']} []
- **mcxgold** (PARITY)
  - A failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - A failure: failed_request: POST http://127.0.0.1:8097/api/mcx/ticket → HTTP 403
  - B failure: console_error: Failed to load resource: the server responded with a status of 403 (Forbidden)
  - B failure: failed_request: POST http://127.0.0.1:8098/api/mcx/ticket → HTTP 403
  - note: platform seams differ (set aside): A {} [] · B {'GET /api/prefs': ['2xx']} []

**Overall: PARITY**
