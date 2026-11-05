# UI audit — http://127.0.0.1:8010

- started 2026-11-04T22:13:17+05:30 · finished 2026-11-04T22:27:44+05:30 · strict=False · wait=6.0s
- label: R-UI terminal_v2 review

## chromium (156.0.8078.79): 42/43 PASS

console errors 0 · page errors 0 · failed requests 0 · allowlisted stream aborts 1 · third-party 0 · ready p50 46 ms / p95 212 ms / max 2254 ms

| tab | code | result | ready ms | idle ms | total ms | FCP ms | console | page err | failed | first failure |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| brief | BRF | PASS | 205 | 19540 | 25544 | 568 | 0 | 0 | 0 |  |
| watch | WTCH | PASS | 45 | 2281 | 8284 | 48 | 0 | 0 | 0 |  |
| charts | CHRT | PASS | 63 | 666 | 6669 | 60 | 0 | 0 | 0 |  |
| compare | COMP | PASS | 69 | 961 | 6964 | 40 | 0 | 0 | 0 |  |
| screen | FUND | PASS | 28 | 1386 | 7390 | 32 | 0 | 0 | 0 |  |
| alerts | ALRT | PASS | 68 | 624 | 6627 | 40 | 0 | 0 | 0 |  |
| eco | ECO | PASS | 147 | 852 | 6855 | 44 | 0 | 0 | 0 |  |
| seag | SEAG | PASS | 32 | 659 | 6662 | 32 | 0 | 0 | 0 |  |
| memb | MEMB | PASS | 28 | 685 | 6688 | 28 | 0 | 0 | 0 |  |
| options | OMON | PASS | 42 | 668 | 6671 | 48 | 0 | 0 | 0 |  |
| ostrategy | OSTR | PASS | 47 | 1011 | 7016 | 48 | 0 | 0 | 0 |  |
| derivatives | DERV | PASS | 29 | 724 | 6726 | 36 | 0 | 0 | 0 |  |
| insiders | INSD | PASS | 44 | 688 | 6690 | 44 | 0 | 0 | 0 |  |
| deals | DEAL | PASS | 28 | 906 | 6910 | 40 | 0 | 0 | 0 |  |
| preopen | PRE | PASS | 31 | 687 | 6690 | 32 | 0 | 0 | 0 |  |
| ipo | IPO | PASS | 41 | 1416 | 7419 | 48 | 0 | 0 | 0 |  |
| movers | MOV | PASS | 27 | 749 | 6754 | 36 | 0 | 0 | 0 |  |
| wrap | WRAP | PASS | 28 | 639 | 6642 | 28 | 0 | 0 | 0 |  |
| filings | CF | PASS | 42 | 1455 | 7458 | 52 | 0 | 0 | 0 |  |
| margin | MRGN | PASS | 27 | 622 | 6624 | 36 | 0 | 0 | 0 |  |
| holders | HDS | PASS | 33 | 654 | 6658 | 32 | 0 | 0 | 0 |  |
| world | WEI | PASS | 52 | 2734 | 8737 | 52 | 0 | 0 | 0 |  |
| desk | DESK | PASS | 44 | 2240 | 8243 | 52 | 0 | 0 | 0 |  |
| markets | MKT | PASS | 46 | 5293 | 11297 | 36 | 0 | 0 | 0 |  |
| events | EVTS | PASS | 55 | — | 27061 | 52 | 0 | 0 | 0 |  |
| overview | OVRV | PASS | 38 | 665 | 6666 | 44 | 0 | 0 | 0 |  |
| stocks | EQS | PASS | 54 | 688 | 6690 | 52 | 0 | 0 | 0 |  |
| backtest | BTST | PASS | 62 | 648 | 6650 | 64 | 0 | 0 | 0 |  |
| positions | PORT | PASS | 83 | 789 | 6794 | 32 | 0 | 0 | 0 |  |
| broker | BRKR | PASS | 47 | 1473 | 7475 | 44 | 0 | 0 | 0 |  |
| pipeline | PIPE | PASS | 38 | 651 | 6656 | 40 | 0 | 0 | 0 |  |
| scanner | LWSC | PASS | 32 | 621 | 6625 | 36 | 0 | 0 | 0 |  |
| discovery | ALFA | PASS | 38 | 2143 | 8147 | 48 | 0 | 0 | 0 |  |
| commodity | CMDT | PASS | 2254 | 3685 | 9691 | 72 | 0 | 0 | 0 |  |
| mcxgold | MCXG | PASS | 114 | 1726 | 7728 | 116 | 0 | 0 | 0 |  |
| gold | GOLD | **FAIL** | None | 30069 | 36073 | 88 | 0 | 0 | 0 | not_ready: the page's own header (code chip) did not render within the ready timeout |
| glassbox | GBOX | PASS | 73 | 697 | 6701 | 68 | 0 | 0 | 0 |  |
| mlengine | MLEN | PASS | 121 | 722 | 6725 | 88 | 0 | 0 | 0 |  |
| explorer | DEXP | PASS | 79 | 734 | 6738 | 80 | 0 | 0 | 0 |  |
| warehouse | WHSE | PASS | 212 | 741 | 6744 | 56 | 0 | 0 | 0 |  |
| research | RSCH | PASS | 106 | 770 | 6774 | 80 | 0 | 0 | 0 |  |
| risk | RSK | PASS | 84 | 978 | 6982 | 84 | 0 | 0 | 0 |  |
| system | SYS | PASS | 606 | — | 27615 | 420 | 0 | 0 | 0 |  |

## webkit (26.4): 42/43 PASS

console errors 0 · page errors 0 · failed requests 0 · allowlisted stream aborts 1 · third-party 0 · ready p50 74 ms / p95 657 ms / max 950 ms

| tab | code | result | ready ms | idle ms | total ms | FCP ms | console | page err | failed | first failure |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| brief | BRF | PASS | 682 | — | 27686 | 620 | 0 | 0 | 0 |  |
| watch | WTCH | PASS | 68 | 2252 | 8255 | 45 | 0 | 0 | 0 |  |
| charts | CHRT | PASS | 83 | 652 | 6654 | 68 | 0 | 0 | 0 |  |
| compare | COMP | PASS | 101 | 1392 | 7394 | 75 | 0 | 0 | 0 |  |
| screen | FUND | PASS | 99 | 876 | 6879 | 94 | 0 | 0 | 0 |  |
| alerts | ALRT | PASS | 69 | 616 | 6619 | 44 | 0 | 0 | 0 |  |
| eco | ECO | PASS | 137 | 639 | 6642 | 38 | 0 | 0 | 0 |  |
| seag | SEAG | PASS | 68 | 618 | 6620 | 36 | 0 | 0 | 0 |  |
| memb | MEMB | PASS | 72 | 794 | 6796 | 39 | 0 | 0 | 0 |  |
| options | OMON | PASS | 70 | 867 | 6870 | 42 | 0 | 0 | 0 |  |
| ostrategy | OSTR | PASS | 72 | 1010 | 7010 | 39 | 0 | 0 | 0 |  |
| derivatives | DERV | PASS | 74 | 1050 | 7053 | 38 | 0 | 0 | 0 |  |
| insiders | INSD | PASS | 152 | 1009 | 7011 | 102 | 0 | 0 | 0 |  |
| deals | DEAL | PASS | 83 | 1137 | 7138 | 49 | 0 | 0 | 0 |  |
| preopen | PRE | PASS | 71 | 802 | 6805 | 37 | 0 | 0 | 0 |  |
| ipo | IPO | PASS | 74 | 1309 | 7310 | 39 | 0 | 0 | 0 |  |
| movers | MOV | PASS | 74 | 8537 | 14540 | 39 | 0 | 0 | 0 |  |
| wrap | WRAP | PASS | 74 | 819 | 6821 | 40 | 0 | 0 | 0 |  |
| filings | CF | PASS | 44 | 1474 | 7477 | 40 | 0 | 0 | 0 |  |
| margin | MRGN | PASS | 76 | 657 | 6659 | 40 | 0 | 0 | 0 |  |
| holders | HDS | PASS | 48 | 685 | 6687 | 43 | 0 | 0 | 0 |  |
| world | WEI | PASS | 53 | 2502 | 8505 | 49 | 0 | 0 | 0 |  |
| desk | DESK | PASS | 44 | 2349 | 8350 | 40 | 0 | 0 | 0 |  |
| markets | MKT | PASS | 49 | 8561 | 14562 | 44 | 0 | 0 | 0 |  |
| events | EVTS | PASS | 60 | 19176 | 25179 | 55 | 0 | 0 | 0 |  |
| overview | OVRV | PASS | 80 | 726 | 6728 | 52 | 0 | 0 | 0 |  |
| stocks | EQS | PASS | 48 | 756 | 6758 | 43 | 0 | 0 | 0 |  |
| backtest | BTST | PASS | 92 | 634 | 6635 | 79 | 0 | 0 | 0 |  |
| positions | PORT | PASS | 97 | 631 | 6634 | 42 | 0 | 0 | 0 |  |
| broker | BRKR | PASS | 47 | 617 | 6619 | 42 | 0 | 0 | 0 |  |
| pipeline | PIPE | PASS | 87 | 871 | 6874 | 56 | 0 | 0 | 0 |  |
| scanner | LWSC | PASS | 80 | 629 | 6631 | 49 | 0 | 0 | 0 |  |
| discovery | ALFA | PASS | 82 | 2257 | 8260 | 62 | 0 | 0 | 0 |  |
| commodity | CMDT | PASS | 950 | 8681 | 14685 | 61 | 0 | 0 | 0 |  |
| mcxgold | MCXG | PASS | 121 | 1605 | 7606 | 86 | 0 | 0 | 0 |  |
| gold | GOLD | **FAIL** | None | 30027 | 36030 | 64 | 0 | 0 | 0 | not_ready: the page's own header (code chip) did not render within the ready timeout |
| glassbox | GBOX | PASS | 137 | 696 | 6699 | 102 | 0 | 0 | 0 |  |
| mlengine | MLEN | PASS | 103 | 637 | 6640 | 80 | 0 | 0 | 0 |  |
| explorer | DEXP | PASS | 90 | 680 | 6682 | 79 | 0 | 0 | 0 |  |
| warehouse | WHSE | PASS | 141 | 694 | 6697 | 49 | 0 | 0 | 0 |  |
| research | RSCH | PASS | 55 | 860 | 6862 | 50 | 0 | 0 | 0 |  |
| risk | RSK | PASS | 59 | 659 | 6662 | 55 | 0 | 0 | 0 |  |
| system | SYS | PASS | 657 | — | 27667 | 92 | 0 | 0 | 0 |  |

**Overall: FAIL**
