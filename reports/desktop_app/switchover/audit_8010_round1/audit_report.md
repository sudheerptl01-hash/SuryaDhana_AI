# UI audit — http://127.0.0.1:8010

- started 2026-10-25T13:55:45+05:30 · finished 2026-10-25T14:07:23+05:30 · strict=False · wait=6.0s
- label: live :8010 release 20261025-135500-0ae66db after fix round 1 (prefs readonly)

## chromium (155.0.8059.85): 42/42 PASS

console errors 0 · page errors 0 · failed requests 0 · allowlisted stream aborts 1 · third-party 0 · ready p50 452 ms / p95 632 ms / max 729 ms

| tab | code | result | ready ms | idle ms | total ms | FCP ms | console | page err | failed | first failure |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| brief | BRF | PASS | 632 | 4026 | 10030 | 112 | 0 | 0 | 0 |  |
| watch | WTCH | PASS | 460 | 1964 | 7968 | 52 | 0 | 0 | 0 |  |
| charts | CHRT | PASS | 453 | 1003 | 7007 | 40 | 0 | 0 | 0 |  |
| compare | COMP | PASS | 457 | 1581 | 7586 | 40 | 0 | 0 | 0 |  |
| screen | FUND | PASS | 452 | 1601 | 7606 | 44 | 0 | 0 | 0 |  |
| alerts | ALRT | PASS | 456 | 1015 | 7018 | 40 | 0 | 0 | 0 |  |
| eco | ECO | PASS | 453 | 997 | 7001 | 40 | 0 | 0 | 0 |  |
| seag | SEAG | PASS | 451 | 1016 | 7019 | 44 | 0 | 0 | 0 |  |
| memb | MEMB | PASS | 196 | 935 | 6937 | 40 | 0 | 0 | 0 |  |
| options | OMON | PASS | 452 | 1030 | 7035 | 40 | 0 | 0 | 0 |  |
| ostrategy | OSTR | PASS | 451 | 1369 | 7373 | 44 | 0 | 0 | 0 |  |
| derivatives | DERV | PASS | 453 | 1234 | 7239 | 40 | 0 | 0 | 0 |  |
| insiders | INSD | PASS | 454 | 1054 | 7057 | 44 | 0 | 0 | 0 |  |
| deals | DEAL | PASS | 450 | 1264 | 7269 | 44 | 0 | 0 | 0 |  |
| preopen | PRE | PASS | 463 | 1090 | 7093 | 44 | 0 | 0 | 0 |  |
| ipo | IPO | PASS | 449 | 2217 | 8221 | 44 | 0 | 0 | 0 |  |
| movers | MOV | PASS | 194 | 1802 | 7806 | 44 | 0 | 0 | 0 |  |
| wrap | WRAP | PASS | 444 | 1017 | 7020 | 44 | 0 | 0 | 0 |  |
| filings | CF | PASS | 435 | 1233 | 7237 | 32 | 0 | 0 | 0 |  |
| margin | MRGN | PASS | 453 | 1035 | 7039 | 40 | 0 | 0 | 0 |  |
| holders | HDS | PASS | 449 | 1029 | 7034 | 36 | 0 | 0 | 0 |  |
| world | WEI | PASS | 451 | 4129 | 10131 | 44 | 0 | 0 | 0 |  |
| desk | DESK | PASS | 452 | 2104 | 8107 | 40 | 0 | 0 | 0 |  |
| markets | MKT | PASS | 433 | 1194 | 7197 | 36 | 0 | 0 | 0 |  |
| events | EVTS | PASS | 145 | 1855 | 7856 | 40 | 0 | 0 | 0 |  |
| overview | OVRV | PASS | 492 | 1018 | 7023 | 32 | 0 | 0 | 0 |  |
| stocks | EQS | PASS | 723 | 2097 | 8101 | 44 | 0 | 0 | 0 |  |
| backtest | BTST | PASS | 453 | 1014 | 7017 | 40 | 0 | 0 | 0 |  |
| positions | PORT | PASS | 451 | 987 | 6989 | 40 | 0 | 0 | 0 |  |
| broker | BRKR | PASS | 439 | 1153 | 7156 | 24 | 0 | 0 | 0 |  |
| pipeline | PIPE | PASS | 454 | 1002 | 7006 | 40 | 0 | 0 | 0 |  |
| scanner | LWSC | PASS | 448 | 994 | 6999 | 28 | 0 | 0 | 0 |  |
| discovery | ALFA | PASS | 439 | 2411 | 8414 | 36 | 0 | 0 | 0 |  |
| commodity | CMDT | PASS | 614 | 1986 | 7988 | 44 | 0 | 0 | 0 |  |
| mcxgold | MCXG | PASS | 447 | 1883 | 7886 | 40 | 0 | 0 | 0 |  |
| glassbox | GBOX | PASS | 450 | 1012 | 7017 | 40 | 0 | 0 | 0 |  |
| mlengine | MLEN | PASS | 502 | 1023 | 7026 | 40 | 0 | 0 | 0 |  |
| explorer | DEXP | PASS | 451 | 1980 | 7983 | 40 | 0 | 0 | 0 |  |
| warehouse | WHSE | PASS | 509 | 1044 | 7046 | 44 | 0 | 0 | 0 |  |
| research | RSCH | PASS | 500 | 1090 | 7092 | 44 | 0 | 0 | 0 |  |
| risk | RSK | PASS | 143 | 947 | 6951 | 40 | 0 | 0 | 0 |  |
| system | SYS | PASS | 729 | — | 27734 | 48 | 0 | 0 | 0 |  |

## webkit (26.4): 42/42 PASS

console errors 0 · page errors 0 · failed requests 0 · allowlisted stream aborts 1 · third-party 0 · ready p50 505 ms / p95 740 ms / max 1142 ms

| tab | code | result | ready ms | idle ms | total ms | FCP ms | console | page err | failed | first failure |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| brief | BRF | PASS | 519 | 2153 | 8159 | 136 | 0 | 0 | 0 |  |
| watch | WTCH | PASS | 507 | 1993 | 7995 | 64 | 0 | 0 | 0 |  |
| charts | CHRT | PASS | 520 | 1078 | 7083 | 64 | 0 | 0 | 0 |  |
| compare | COMP | PASS | 202 | 1407 | 7412 | 63 | 0 | 0 | 0 |  |
| screen | FUND | PASS | 198 | 1194 | 7197 | 63 | 0 | 0 | 0 |  |
| alerts | ALRT | PASS | 505 | 1065 | 7069 | 62 | 0 | 0 | 0 |  |
| eco | ECO | PASS | 541 | 1082 | 7086 | 64 | 0 | 0 | 0 |  |
| seag | SEAG | PASS | 501 | 1049 | 7051 | 63 | 0 | 0 | 0 |  |
| memb | MEMB | PASS | 502 | 1172 | 7175 | 64 | 0 | 0 | 0 |  |
| options | OMON | PASS | 505 | 1114 | 7119 | 64 | 0 | 0 | 0 |  |
| ostrategy | OSTR | PASS | 424 | 1394 | 7397 | 34 | 0 | 0 | 0 |  |
| derivatives | DERV | PASS | 471 | 1145 | 7150 | 35 | 0 | 0 | 0 |  |
| insiders | INSD | PASS | 511 | 1173 | 7175 | 66 | 0 | 0 | 0 |  |
| deals | DEAL | PASS | 506 | 1413 | 7418 | 64 | 0 | 0 | 0 |  |
| preopen | PRE | PASS | 532 | 1326 | 7330 | 67 | 0 | 0 | 0 |  |
| ipo | IPO | PASS | 479 | 1770 | 7773 | 62 | 0 | 0 | 0 |  |
| movers | MOV | PASS | 425 | 1267 | 7272 | 33 | 0 | 0 | 0 |  |
| wrap | WRAP | PASS | 511 | 1051 | 7055 | 67 | 0 | 0 | 0 |  |
| filings | CF | PASS | 511 | 1341 | 7346 | 65 | 0 | 0 | 0 |  |
| margin | MRGN | PASS | 504 | 1082 | 7086 | 64 | 0 | 0 | 0 |  |
| holders | HDS | PASS | 425 | 1058 | 7062 | 34 | 0 | 0 | 0 |  |
| world | WEI | PASS | 206 | 3042 | 9046 | 67 | 0 | 0 | 0 |  |
| desk | DESK | PASS | 593 | 2059 | 8063 | 68 | 0 | 0 | 0 |  |
| markets | MKT | PASS | 467 | 1404 | 7409 | 62 | 0 | 0 | 0 |  |
| events | EVTS | PASS | 507 | 2222 | 8225 | 65 | 0 | 0 | 0 |  |
| overview | OVRV | PASS | 511 | 1086 | 7088 | 62 | 0 | 0 | 0 |  |
| stocks | EQS | PASS | 1117 | 1117 | 7119 | 33 | 0 | 0 | 0 |  |
| backtest | BTST | PASS | 182 | 805 | 6810 | 49 | 0 | 0 | 0 |  |
| positions | PORT | PASS | 488 | 1026 | 7031 | 34 | 0 | 0 | 0 |  |
| broker | BRKR | PASS | 173 | 1075 | 7080 | 35 | 0 | 0 | 0 |  |
| pipeline | PIPE | PASS | 507 | 1030 | 7032 | 64 | 0 | 0 | 0 |  |
| scanner | LWSC | PASS | 513 | 1186 | 7190 | 63 | 0 | 0 | 0 |  |
| discovery | ALFA | PASS | 505 | 2552 | 8556 | 64 | 0 | 0 | 0 |  |
| commodity | CMDT | PASS | 1142 | 8633 | 14638 | 48 | 0 | 0 | 0 |  |
| mcxgold | MCXG | PASS | 517 | 1458 | 7463 | 67 | 0 | 0 | 0 |  |
| glassbox | GBOX | PASS | 463 | 1051 | 7056 | 64 | 0 | 0 | 0 |  |
| mlengine | MLEN | PASS | 554 | 1427 | 7430 | 68 | 0 | 0 | 0 |  |
| explorer | DEXP | PASS | 502 | 1862 | 7867 | 66 | 0 | 0 | 0 |  |
| warehouse | WHSE | PASS | 597 | 1130 | 7135 | 67 | 0 | 0 | 0 |  |
| research | RSCH | PASS | 463 | 1256 | 7260 | 66 | 0 | 0 | 0 |  |
| risk | RSK | PASS | 509 | 1082 | 7088 | 66 | 0 | 0 | 0 |  |
| system | SYS | PASS | 740 | — | 27750 | 44 | 0 | 0 | 0 |  |

**Overall: PASS**
