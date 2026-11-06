# UI audit — http://127.0.0.1:8010

- started 2026-11-06T00:46:19+05:30 · finished 2026-11-06T00:48:40+05:30 · strict=False · wait=6.0s
- label: —

## chromium (156.0.8078.80): 6/6 PASS

console errors 0 · page errors 0 · failed requests 0 · allowlisted stream aborts 1 · third-party 0 · ready p50 101 ms / p95 2643 ms / max 2643 ms

| tab | code | result | ready ms | idle ms | total ms | FCP ms | console | page err | failed | first failure |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| gold | GOLD | PASS | 133 | 1143 | 7148 | 140 | 0 | 0 | 0 |  |
| mcxgold | MCXG | PASS | 35 | 974 | 6975 | 48 | 0 | 0 | 0 |  |
| commodity | CMDT | PASS | 2643 | 3761 | 9765 | 48 | 0 | 0 | 0 |  |
| brief | BRF | PASS | 101 | 2596 | 8600 | 68 | 0 | 0 | 0 |  |
| world | WEI | PASS | 52 | 2317 | 8322 | 56 | 0 | 0 | 0 |  |
| system | SYS | PASS | 357 | — | 27362 | 64 | 0 | 0 | 0 |  |

## webkit (26.4): 6/6 PASS

console errors 0 · page errors 0 · failed requests 0 · allowlisted stream aborts 1 · third-party 0 · ready p50 112 ms / p95 1912 ms / max 1912 ms

| tab | code | result | ready ms | idle ms | total ms | FCP ms | console | page err | failed | first failure |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| gold | GOLD | PASS | 286 | 1215 | 7218 | 207 | 0 | 0 | 0 |  |
| mcxgold | MCXG | PASS | 91 | 1029 | 7041 | 60 | 0 | 0 | 0 |  |
| commodity | CMDT | PASS | 1912 | 2401 | 8405 | 77 | 0 | 0 | 0 |  |
| brief | BRF | PASS | 112 | 1388 | 7391 | 97 | 0 | 0 | 0 |  |
| world | WEI | PASS | 79 | 2618 | 8624 | 61 | 0 | 0 | 0 |  |
| system | SYS | PASS | 376 | — | 27386 | 70 | 0 | 0 | 0 |  |

## Live freshness (reports/live_nse)

- market closed (live service) · feed DISCONNECTED · max age 10.0 s · run-level failures: none

**Overall: PASS**
