# ICICI Breeze data catalog — INFY (probed live 2026-09-28, 11:20–11:45 IST)

Produced by `scripts/breeze_data_catalog.py --ticker INFY` (read-only; ~45 API calls).
Raw responses: `samples/`. Machine summary: `summary.json`. Derived numbers: `analysis.json`.
Readable report with charts: https://claude.ai/artifact/MneLaEE2fk9dtn8RCFKatf

## What exists
| Endpoint | Granularity | History (measured) | Status 2026-09-28 |
|---|---|---|---|
| SecurityMaster.zip (no login) | daily file | current instruments only | OK — NSE ~5.9k, NSE F&O ~81k, BSE ~13.6k, BFO ~5.1k, MCX ~25k, MF ~7k |
| get_historical_data_v2 — cash (NSE, BSE, indices) | 1s, 1m, 5m, 30m, 1d | 1d from 2000-03-06; 1m/5m/30m from 2011; 1s from mid-2018 | OK |
| — futures / options (+ open_interest) | 1s … 1d | live **and expired** contracts (checked Sep 2020/2023/2025) | OK |
| get_option_chain_quotes | snapshot | now | OK — 26 fields incl. OI, ΔOI, bid/ask, spot_price |
| get_quotes | snapshot | now | **capped: "Limit exceed: API call per day"** |
| websocket depth (L2, 5 levels + order counts) | event | live | OK |
| websocket candles | 1s/1m/5m/30m | live | OK (after SDK timeout fix) |
| websocket ticks (L1) | tick | live | subscribed, **0 events** (likely same cap) |
| preview_order (GET, charges) / margin_calculator | — | — | OK |

## Findings that affect research
1. Daily series is bonus-adjusted to today's scale but has 10 isolated off-scale days (2011–2017) and an unadjusted 2004 bonus → 24 one-day moves > 30% that never happened. Clean it or use NSE bhavcopy + `shared/nse_panel.py` factors.
2. Intraday history is also bonus-adjusted (2014-09-25 1-min close ₹463.13 vs ~₹3,700 traded) — the SDK README says otherwise.
3. 1,000 bars per call, and the API returns the **latest** 1,000 in the window → page backwards.
4. 1-min volume on 2026-09-25 sums exactly to daily volume (10,164,746); 369/375 bars (no-trade minutes absent), some days add a 15:30 bar.
5. breeze-connect 1.0.69 websocket uses a 3 s handshake timeout; from this network it takes 3.4 s → `patch_socket_timeout()` in the script.
6. ICICI preview charges **0.25%** delivery brokerage (model assumes 0.29%; no saved profile has 0.25%); preview omits the DP charge.
7. 1 lot INFY future (400) → SPAN ₹80,408 (~20% of notional).
8. Expiries shift for holidays (Nov 2026 → Mon 23 Nov): read them from the master.

## Rerun for another stock
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/breeze_data_catalog.py --ticker RELIANCE
