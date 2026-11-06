# UI audit — http://127.0.0.1:8010

- started 2026-11-06T16:11:48+05:30 · finished 2026-11-06T16:23:54+05:30 · strict=False · wait=6.0s
- label: after-close deploy 6 Nov: wave 2 + review fixes + gold 1e (0b27dcc) + RSCH scroll-pane fix, release 20261106-161045

## chromium (156.0.8078.81): 43/43 PASS

console errors 0 · page errors 0 · failed requests 0 · allowlisted stream aborts 1 · third-party 0 · ready p50 49 ms / p95 166 ms / max 3040 ms

| tab | code | result | ready ms | idle ms | total ms | FCP ms | console | page err | failed | first failure |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| brief | BRF | PASS | 166 | 2114 | 8117 | 148 | 0 | 0 | 0 |  |
| watch | WTCH | PASS | 75 | 4180 | 10182 | 48 | 0 | 0 | 0 |  |
| charts | CHRT | PASS | 57 | 618 | 6627 | 56 | 0 | 0 | 0 |  |
| compare | COMP | PASS | 82 | 629 | 6634 | 52 | 0 | 0 | 0 |  |
| screen | FUND | PASS | 82 | 1301 | 7305 | 44 | 0 | 0 | 0 |  |
| alerts | ALRT | PASS | 60 | 624 | 6629 | 56 | 0 | 0 | 0 |  |
| eco | ECO | PASS | 93 | 619 | 6624 | 48 | 0 | 0 | 0 |  |
| seag | SEAG | PASS | 49 | 623 | 6627 | 44 | 0 | 0 | 0 |  |
| memb | MEMB | PASS | 48 | 989 | 6994 | 44 | 0 | 0 | 0 |  |
| options | OMON | PASS | 46 | 702 | 6707 | 44 | 0 | 0 | 0 |  |
| ostrategy | OSTR | PASS | 48 | 1538 | 7541 | 48 | 0 | 0 | 0 |  |
| derivatives | DERV | PASS | 49 | 709 | 6714 | 44 | 0 | 0 | 0 |  |
| insiders | INSD | PASS | 42 | 663 | 6667 | 44 | 0 | 0 | 0 |  |
| deals | DEAL | PASS | 46 | 904 | 6908 | 44 | 0 | 0 | 0 |  |
| preopen | PRE | PASS | 45 | 665 | 6670 | 44 | 0 | 0 | 0 |  |
| ipo | IPO | PASS | 49 | 1423 | 7428 | 48 | 0 | 0 | 0 |  |
| movers | MOV | PASS | 46 | 1558 | 7561 | 44 | 0 | 0 | 0 |  |
| wrap | WRAP | PASS | 38 | 621 | 6625 | 44 | 0 | 0 | 0 |  |
| filings | CF | PASS | 38 | 1465 | 7468 | 44 | 0 | 0 | 0 |  |
| margin | MRGN | PASS | 44 | 631 | 6636 | 40 | 0 | 0 | 0 |  |
| holders | HDS | PASS | 59 | 621 | 6624 | 48 | 0 | 0 | 0 |  |
| world | WEI | PASS | 55 | 2040 | 8043 | 52 | 0 | 0 | 0 |  |
| desk | DESK | PASS | 36 | 867 | 6870 | 36 | 0 | 0 | 0 |  |
| markets | MKT | PASS | 41 | 1743 | 7747 | 44 | 0 | 0 | 0 |  |
| events | EVTS | PASS | 45 | 3901 | 9904 | 44 | 0 | 0 | 0 |  |
| overview | OVRV | PASS | 37 | 614 | 6616 | 40 | 0 | 0 | 0 |  |
| stocks | EQS | PASS | 50 | 1638 | 7642 | 48 | 0 | 0 | 0 |  |
| backtest | BTST | PASS | 58 | 847 | 6851 | 60 | 0 | 0 | 0 |  |
| positions | PORT | PASS | 93 | 611 | 6614 | 40 | 0 | 0 | 0 |  |
| broker | BRKR | PASS | 32 | 1480 | 7483 | 32 | 0 | 0 | 0 |  |
| pipeline | PIPE | PASS | 55 | 662 | 6667 | 56 | 0 | 0 | 0 |  |
| scanner | LWSC | PASS | 51 | 612 | 6616 | 48 | 0 | 0 | 0 |  |
| discovery | ALFA | PASS | 48 | 2117 | 8120 | 44 | 0 | 0 | 0 |  |
| commodity | CMDT | PASS | 3040 | 4163 | 10167 | 28 | 0 | 0 | 0 |  |
| mcxgold | MCXG | PASS | 51 | 1471 | 7476 | 48 | 0 | 0 | 0 |  |
| gold | GOLD | PASS | 67 | 2109 | 8113 | 64 | 0 | 0 | 0 |  |
| glassbox | GBOX | PASS | 40 | 852 | 6854 | 36 | 0 | 0 | 0 |  |
| mlengine | MLEN | PASS | 57 | 620 | 6624 | 60 | 0 | 0 | 0 |  |
| explorer | DEXP | PASS | 51 | 636 | 6641 | 48 | 0 | 0 | 0 |  |
| warehouse | WHSE | PASS | 106 | 655 | 6660 | 48 | 0 | 0 | 0 |  |
| research | RSCH | PASS | 47 | 699 | 6704 | 40 | 0 | 0 | 0 |  |
| risk | RSK | PASS | 48 | 612 | 6616 | 44 | 0 | 0 | 0 |  |
| system | SYS | PASS | 313 | — | 27318 | 60 | 0 | 0 | 0 |  |

## webkit (26.4): 43/43 PASS

console errors 0 · page errors 0 · failed requests 0 · allowlisted stream aborts 1 · third-party 0 · ready p50 93 ms / p95 277 ms / max 2526 ms

| tab | code | result | ready ms | idle ms | total ms | FCP ms | console | page err | failed | first failure |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| brief | BRF | PASS | 223 | 1880 | 7884 | 191 | 0 | 0 | 0 |  |
| watch | WTCH | PASS | 92 | 645 | 6648 | 73 | 0 | 0 | 0 |  |
| charts | CHRT | PASS | 93 | 634 | 6639 | 80 | 0 | 0 | 0 |  |
| compare | COMP | PASS | 101 | 638 | 6642 | 79 | 0 | 0 | 0 |  |
| screen | FUND | PASS | 277 | 767 | 6770 | 52 | 0 | 0 | 0 |  |
| alerts | ALRT | PASS | 96 | 631 | 6636 | 73 | 0 | 0 | 0 |  |
| eco | ECO | PASS | 163 | 662 | 6664 | 39 | 0 | 0 | 0 |  |
| seag | SEAG | PASS | 100 | 622 | 6627 | 70 | 0 | 0 | 0 |  |
| memb | MEMB | PASS | 101 | 972 | 6976 | 68 | 0 | 0 | 0 |  |
| options | OMON | PASS | 83 | 759 | 6761 | 53 | 0 | 0 | 0 |  |
| ostrategy | OSTR | PASS | 102 | 1554 | 7555 | 77 | 0 | 0 | 0 |  |
| derivatives | DERV | PASS | 101 | 752 | 6756 | 68 | 0 | 0 | 0 |  |
| insiders | INSD | PASS | 93 | 745 | 6749 | 56 | 0 | 0 | 0 |  |
| deals | DEAL | PASS | 102 | 1029 | 7035 | 70 | 0 | 0 | 0 |  |
| preopen | PRE | PASS | 105 | 808 | 6811 | 68 | 0 | 0 | 0 |  |
| ipo | IPO | PASS | 102 | 1376 | 7378 | 71 | 0 | 0 | 0 |  |
| movers | MOV | PASS | 122 | 820 | 6824 | 73 | 0 | 0 | 0 |  |
| wrap | WRAP | PASS | 73 | 615 | 6619 | 68 | 0 | 0 | 0 |  |
| filings | CF | PASS | 85 | 663 | 6666 | 39 | 0 | 0 | 0 |  |
| margin | MRGN | PASS | 69 | 689 | 6692 | 58 | 0 | 0 | 0 |  |
| holders | HDS | PASS | 70 | 695 | 6698 | 59 | 0 | 0 | 0 |  |
| world | WEI | PASS | 87 | 8802 | 14806 | 76 | 0 | 0 | 0 |  |
| desk | DESK | PASS | 84 | 963 | 6967 | 74 | 0 | 0 | 0 |  |
| markets | MKT | PASS | 56 | 1843 | 7844 | 48 | 0 | 0 | 0 |  |
| events | EVTS | PASS | 83 | 3427 | 9430 | 71 | 0 | 0 | 0 |  |
| overview | OVRV | PASS | 121 | 665 | 6668 | 97 | 0 | 0 | 0 |  |
| stocks | EQS | PASS | 90 | 1627 | 7630 | 74 | 0 | 0 | 0 |  |
| backtest | BTST | PASS | 71 | 867 | 6870 | 69 | 0 | 0 | 0 |  |
| positions | PORT | PASS | 93 | 587 | 6590 | 37 | 0 | 0 | 0 |  |
| broker | BRKR | PASS | 54 | 2799 | 8804 | 46 | 0 | 0 | 0 |  |
| pipeline | PIPE | PASS | 123 | 696 | 6701 | 84 | 0 | 0 | 0 |  |
| scanner | LWSC | PASS | 86 | 648 | 6652 | 75 | 0 | 0 | 0 |  |
| discovery | ALFA | PASS | 52 | 2217 | 8221 | 46 | 0 | 0 | 0 |  |
| commodity | CMDT | PASS | 2526 | 8816 | 14820 | 74 | 0 | 0 | 0 |  |
| mcxgold | MCXG | PASS | 76 | 1562 | 7565 | 66 | 0 | 0 | 0 |  |
| gold | GOLD | PASS | 76 | 1893 | 7897 | 65 | 0 | 0 | 0 |  |
| glassbox | GBOX | PASS | 128 | 905 | 6908 | 91 | 0 | 0 | 0 |  |
| mlengine | MLEN | PASS | 134 | 631 | 6635 | 94 | 0 | 0 | 0 |  |
| explorer | DEXP | PASS | 85 | 665 | 6669 | 74 | 0 | 0 | 0 |  |
| warehouse | WHSE | PASS | 122 | 658 | 6661 | 44 | 0 | 0 | 0 |  |
| research | RSCH | PASS | 86 | 749 | 6751 | 77 | 0 | 0 | 0 |  |
| risk | RSK | PASS | 60 | 608 | 6613 | 52 | 0 | 0 | 0 |  |
| system | SYS | PASS | 362 | — | 27372 | 82 | 0 | 0 | 0 |  |

## Live freshness (reports/live_nse)

- market closed (live service) · feed LIVE · max age 10.0 s · run-level failures: none

**Overall: PASS**
