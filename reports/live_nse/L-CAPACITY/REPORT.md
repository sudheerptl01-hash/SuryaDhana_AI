# L-CAPACITY: how much the live sources can carry (measured 5 Nov 2026, 10:15-10:42 IST, market open)

Survey only, read-only, in separate probe processes. The live tick engine was OFF throughout: GET :8001/live/ticks returned state OFF, and GET :8001/provider/status returned connected:true before and after every probe. Conditions: NIFTY +1.7% on the day, a busy morning hour, one trading day only.

## 0. Verdict
- **One Breeze socket carried 1,040 tokens (1,000 stocks + 40 indices) for 90 s with no throttling sign.** 997/1,000 stocks ticked; the 3 silent names are illiquid. 540 tokens (500 stocks + 40 indices) were clean in two separate runs (120 s and 90 s): 500/500 ticked, 0 disconnects, 0 server events, 0 subscribe errors. The NIFTY 50 core's rate (52-60 ticks per symbol per minute) and lag (receive time minus ltt: median 0.70->0.72->0.77 s, p90 1.65->1.54->1.78 s, p99 4.6->4.5->5.5 s at 53 / 540 / 1,040 tokens) did not degrade.
- **Recommended operating cap:** 500 cash stocks + 35 live index tokens + up to 60 F&O contracts on ONE socket (about 600 tokens). Hard ceiling 1,000 (worked for 90 s, never soak-tested). Today's MAX_SYMBOLS=50 can go to 500.
- **F&O ticks.** NIFTY near future gave 85 ticks/60 s (median gap 0.64 s, lag 0.53 s). Weekly ATM±1 CE/PE gave 95-96 ticks/60 s each (lag 0.24-0.82 s). Ticks are keyed '4.1!<FONSE token>' (same '4.' prefix as NSE cash), with 23 fields including live OI (in shares); CHNGOI arrived empty. The parameter path also works: exchange_code=NFO, stock_code=NIFTY, product_type=options|futures, expiry_date='23-Nov-2026' (DD-Mon-YYYY as in the master, not ISO), strike_price, right=call.
- **Indices.** 35 of the 40 index tokens in NSEScripMaster (series '0') stream at fixed rates, whether or not the value changed:
  - NIFTY 50: exactly 10/s.
  - NIFTY BANK, FIN SERVICE, MID SELECT, NEXT 50: 4/s.
  - INDIA VIX and every other NSE broad/sector index: 2/s.
  - Silent: CNX 100, CNX DEFTY, CNX NIFTY JUNIOR, Nifty CPSE, S&P CNX NIFTYY, DJIA, FTSE100, S&P500.
- **Second process:** client A's 5-second buckets stayed at 50-52 stock ticks and exactly 50 index ticks while client B (same key and session token, own process) ran generate_session + ws_connect + subscribe. There was no disconnect, neither received the other's symbols (subscriptions are per socket), and the live stack stayed connected. Run twice.
- **Teardown bug:** BreezeConnect.ws_disconnect() does not close the socket. The server drops the transport, python-socketio reconnects in 1.8-3.2 s, and Breeze's rewatch re-joins every token: 1,122 and 1,036 ticks arrived in the 5 s after ws_disconnect. Only handler.sio.disconnect() ends the stream. live_ticks._teardown_ws() calls only ws_disconnect(), so it leaks a zombie socket.
- **NSE website (fallback):** every endpoint answered 200 except quote-equity (403 from AkamaiGHost, confirmed). A working equity quote path exists: /api/NextApi/apiClient/GetQuoteApi?functionName=getSymbolData&marketType=N&series=EQ&symbol=X (full quote, 5-level book, band, delivery %). None of these sources is live. Matched against Breeze cumulative volume:
  - heatmap-symbols is 49 s old (median of 50 names, p90 51 s; this agrees with its own label).
  - The NextApi quote is 48.6 and 65.2 s old, while its lastUpdateTime claims 8-9 s.
  - allIndices is 2.2 s and 60.2 s old (minute label).
  - option-chain-v3's label is 47-86 s behind.
  - The chip must read 'NSE DELAYED ~1 min' with measured age, never 'NSE LIVE'.

## 1. Ladder, run 1 (120 s steps)
Columns: tokens, ticks/s, stocks ticked, N50 ticks/sym/min, inter-tick gap med/p90, max silence med/p90/max, lag of trade ticks med/p90/p99, probe CPU % of one core.

| step | tokens | ticks/s | ticked | N50 /sym/min | gap med/p90 (s) | silence med/p90/max (s) | trade-tick lag med/p90/p99 (s) | CPU |
|---|---|---|---|---|---|---|---|---|
| 50 | 53 | 60.0 | 50/50 | 52.8 | 0.67/3.58 | 5.0/6.8/6.9 | 0.89/1.66/4.72 | 4.5% |
| 100 | 103 | 98.4 | 100/100 | 54.9 | 0.74/3.66 | 5.0/6.7/19.4 | 0.92/1.79/4.78 | 6.9% |
| 200 | 240 | 219.4 | 200/200 | 55.7 | 0.80/4.36 | 6.0/6.9/13.0 | 0.96/2.28/6.06 | 11.6% |
| 300 | 340 | 272.4 | 300/300 | 54.4 | 0.89/4.66 | 6.0/6.9/25.6 | 1.00/2.89/6.40 | 13.4% |
| 500 | 540 | 337.8 | 500/500 | 58.5 | 0.99/5.00 | 6.7/13.4/38.7 | 1.08/3.95/6.86 | 10.8% |

**Run 2, verify (90 s steps), lag per group:**

| step | tokens | ticks/s | ticked | N50 lag med/p90/p99 (s) | NN50 lag (s) | rest lag (s) | max silence (s) | CPU |
|---|---|---|---|---|---|---|---|---|
| 50 | 53 | 59.3 | 50/50 | 0.70/1.65/4.56 | - | - | max 7.6 | 4.3% |
| 500 | 540 | 333.7 | 500/500 | 0.72/1.54/4.55 | 0.74/3.35/11.2 | 0.78/6.94/36.2 | p90 13.4 | 12.9% |
| 1000 | 1,040 | 463.7 | 997/1,000 | 0.77/1.78/5.49 | - | 0.94/10.3/56.4 | max 78 | 15.4% |

The overall p90 rises because of composition: illiquid names re-send quotes with an old ltt and can be silent for up to 78 s. The feed itself does not slow.
- About 50% of ticks are quote-only (bid/ask moved, ttq unchanged).
- Subscribing with stock_token=[50 tokens] takes 0-2 ms per emit and returns only a local message. There is no server ack, so the first tick is the only proof of a subscription.
- ltt has whole-second resolution, so up to 1 s of each measured lag is truncation.
- The handler costs about 37 µs/tick. Most CPU is socket.io/engine.io frame handling on the receive thread, which holds the GIL. RSS peaked at 228 MB.

## 2. Tick shape (for LV-DATA)
- **Keys:** cash, index and NFO ticks all use symbol '4.1!<token>'. Indices use names: '4.1!NIFTY 50', '4.1!NIFTY BANK', '4.1!INDIA VIX'.
  - Build token->SYM from NSEScripMaster.txt (EQ/BE row per ExchangeCode).
  - Do not use get_names: it returns isec_token '1333 1462 17320' for HDFCBANK because of its W3 rows.
  - Two token values exist in both the NSE cash and NFO masters (123654, 41435), so key by the token you subscribed, per instrument type.
- **Raw frames:** 21 fields for cash/index, 23 for F&O. The raw ltt epoch seconds sits at index 19/21, prev close at 20/22, ttq at 12/14.
- **Units:** ttv is a string with a 'C' suffix, but the number is in ₹ lakh (TATASTEEL '15823.59C' = 8,712,469 shares × ₹181.62). Use ttq × avgPrice instead. change is % against close (prev close).
- **Index ticks:** bid, ask and ttq arrive as empty strings.
- **Reconnects:** python-socketio auto-reconnects and Breeze's rewatch re-joins the whole tokenlist (a set, so it is idempotent). 540 and 1,040 tokens re-joined in 1.8 and 3.2 s.

## 3. NSE endpoints
28 paced GETs in total, each ≥2.0 s after the previous one, with at most 5 per endpoint. All used the nse_live.py pattern: Chrome UA, Referer and cookie prime on market-data/top-gainers-losers (200, 310 KB, 0.6 s). No 429 occurred; latency was 80-300 ms.
- **allIndices** (114 KB, 139 indices, adv/dec): minute label 1-2 min behind. Values changed within 17 s once but were identical 58 s apart another time. True age 2.2-60 s.
- **heatmap-symbols** (12.7 KB, 50 rows incl. volume, VWAP, lastUpdatedTime): batch refresh about every 60-110 s. 0/50 rows changed in 43 s, then all 50 changed. Label age 14-105 s; true age 49 s.
- **NextApi GetQuoteApi:** 200, 3.5 KB. True age 49-65 s; its label understates this.
- **quote-equity:** 403 Akamai.
- **live-analysis-variations gainers** (7 universes × ≤20 rows): label 11-22 s, cadence about 52 s.
- **most-active value:** label 12-53 s, cadence ≥60 s.
- **marketStatus:** identical over 43 s; tradeDate 2 min behind; GIFT NIFTY TIMESTMP 3 min behind.
- **chart-databyindex-dynamic:** one point per minute from 09:00:59 (pre-open), served from about a 60 s cache. Its epoch-ms values are IST wall-clock encoded as UTC.
- **option-chain-contract-info:** 18 expiries.
- **option-chain-v3 NIFTY:** 286 KB, 135 strikes with IV and buyPrice1/sellPrice1. records.timestamp is 47-86 s behind.
- **Failure modes:** per-path Akamai 403; the 600 s breaker; B1's note that priming on www.nseindia.com/ got a 403 (the gainers page prime worked twice); minute-resolution or wrong labels.

## 4. Recommendations
**Cap (one socket):**
- 500 stocks: holdings, then on-screen symbols with a TTL, then NIFTY 500 by liquidity.
- 35 index tokens.
- ≤60 F&O contracts (near future plus ATM±10 × CE/PE of one weekly expiry = 43).
- Verify each subscription by its first tick.
- Prefer a separate tick-gateway process: it costs 11-15% of a core at 500-1,000 symbols, and a second socket was shown to be safe. If the socket stays in data-service, watch loop_stall.

**Cadences:**
- Receive at full rate and conflate per token.
- Push at ≤1 Hz per symbol (2 Hz for the focused symbol), indices at 1 Hz.
- Use the NIFTY 50 index token (10 Hz) as the heartbeat: STALE when no token ticks for 10 s in session.
- Chips: 'BREEZE LIVE · Ns' if the symbol ticked ≤15 s ago; 'BREEZE LIVE · last trade Ns' for quiet illiquid names on a healthy socket; 'CLOSE · date' after 15:30.
- NSE polling (fallback only):
  - allIndices: ≥15 s
  - heatmap-symbols, live-analysis-*, option-chain-v3, marketStatus: ≥60 s each
  - NextApi quote: ≥60 s per symbol, on demand only

**Fallback order:**

| what | order |
|---|---|
| Stock price | Breeze WS (subscribe on demand) -> Breeze REST get_quotes (focused symbol / trade ticket only, ledger-budgeted) -> NSE heatmap / NextApi ('NSE DELAYED ~1 min', measured age) -> CLOSE · date. Never Yahoo. |
| Indices | Breeze WS -> allIndices (DELAYED) -> CLOSE |
| Movers | computed from the 500-name WS universe -> NSE live-analysis (DELAYED, covers allSec) -> EOD |
| Option chain | WS for ATM±N strikes (live OI) -> NSE option-chain-v3 or Breeze get_option_chain_quotes (budget) -> F&O bhavcopy EOD |

## 5. Patch requests (LV-DATA owns services/data-service/live_ticks.py)
1. **_teardown_ws:** after ws_disconnect(), call .disconnect() on the breeze.sio_rate_refresh_handler.sio kept from _connect_once, and clear its tokenlist.
2. **_sync_subscriptions / _on_tick:**
   - Subscribe with stock_token lists from the master and map ticks by '4.1!<token>' (the root cause of the September 'L1 ticks silent' note).
   - Raise MAX_SYMBOLS to 500.
   - Add the index tokens and an F&O set.
   - Use the raw ltt epoch.

## 6. Evidence and footprint
Scratch files in /Users/sudheer/.suryadhana_pm_scratch/live/L-CAPACITY/:
- breeze_ladder.py -> ladder/{run.log,summary.json}
- breeze_ladder_verify.py -> ladder_verify/summary.json
- session_test.py -> session_test.json and session_test_run1.json
- nse_survey.py -> nse/_log.json and 21 payloads
- render_ladder.py (table helper)

Breeze footprint: 6 generate_session calls (one per probe process), 0 get_quotes, 0 get_names, 0 orders, nothing printed from .env. Breeze's logs/ went to the scratch dir.

Limits: one morning of an up day; 1,040 tokens held for 90 s only; MCX, BSE, market depth (4.2!) and the OHLCV stream were not tested.

## Facts
- One Breeze websocket (ws_connect once, separate process, 10:30-10:38 IST) carried 540 tokens (500 NSE cash stocks + 40 index tokens) clean in two runs (120 s and 90 s): 500/500 stocks ticked, 334-338 ticks/s, 0 disconnects, 0 server events, 0 subscribe errors.
- 1,040 tokens (1,000 stocks + 40 indices) on one socket for 90 s: 463.7 ticks/s, 997/1,000 stocks ticked (silent: LIQUIDBETF, SANGAMIND, SUNCLAY, all illiquid), no disconnect or server event. NIFTY 50 lag median 0.77 s, p90 1.78 s, p99 5.49 s vs 0.70/1.65/4.56 s at 53 tokens: no throttling sign found.
- NIFTY 50 per-symbol rate was 52-60 ticks/min at every step from 53 to 1,040 tokens (no aggregate server cap). Overall p90 lag growth comes from illiquid names re-sending quotes with an old ltt; their max silence reached 78 s.
- Ticks are keyed symbol='4.1!<token>', where the token is the NSEScripMaster.txt Token column: HDFCBANK '4.1!1333', RELIANCE '4.1!2885'. Indices use the name as token: '4.1!NIFTY 50', '4.1!NIFTY BANK', '4.1!INDIA VIX'. NFO ticks use the same '4.' prefix: '4.1!61471' = NIFTY FUT 23-Nov-2026.
- Two token values (123654, 41435) appear in both the NSE cash and NFO masters. get_names returns multi-token strings (HDFCBANK '1333 1462 17320') because of extra series rows. Map from the master's EQ/BE row instead.
- subscribe_feeds(stock_token=[list]) sends one socket.io 'join' per call (0-2 ms for 50 tokens) and returns only a locally built message. There is no server ack, so only the first tick proves a subscription.
- Index streams tick at fixed rates regardless of value change: NIFTY 50 exactly 10/s; NIFTY BANK, FIN SERVICE, MID SELECT, NEXT 50 at 4/s; INDIA VIX and 29 other NSE indices at 2/s. 35 of the 40 index tokens stream; silent: CNX 100, CNX DEFTY, CNX NIFTY JUNIOR, Nifty CPSE, S&P CNX NIFTYY, DJIA, FTSE100, S&P500.
- F&O streams tick. NIFTY near future: 85 ticks/60 s, median gap 0.64 s, lag 0.53 s. Weekly 09-Nov ATM±1 CE/PE: 95-96 ticks/60 s each, lag 0.24-0.82 s. F&O frames have 23 fields including OI (shares); CHNGOI arrived empty.
- The F&O parameter path works with expiry_date in DD-Mon-YYYY (exchange_code='NFO', stock_code='NIFTY', product_type='options', expiry_date='23-Nov-2026', strike_price='24350', right='call' -> '4.1!64411'), not the ISO form the REST API uses.
- Raw tick frames are lists of 21 fields (cash, indices) or 23 (F&O). ltt is a raw epoch-seconds int at index 19/21 (whole seconds, so measured lag includes up to 1 s of truncation); prev close is at index 20/22.
- Tick ttv is a string with a 'C' suffix, but the number is in ₹ lakh: TATASTEEL '15823.59C' = 8,712,469 shares × ₹181.62 avg. Derive value from ttq × avgPrice.
- About 50% of stock ticks are quote-only (ttq unchanged). Liquid NIFTY 50 names go at most 5.0 s (median) and 7.6 s (worst) without a tick.
- BreezeConnect.ws_disconnect() does not close the socket. It emits a 'disconnect' event, the server drops the transport, python-socketio reconnects in 1.8-3.2 s, and Breeze's rewatch re-joins every token: 1,122 and 1,036 ticks arrived in the 5 s after ws_disconnect. Only handler.sio.disconnect() stopped the stream. live_ticks._teardown_ws calls only ws_disconnect.
- A second process with the same API key and session token ran generate_session (0.5 s) and ws_connect (1.9-2.4 s) while process A streamed. A's 5-s buckets stayed at 50-52 stock ticks and exactly 50 index ticks, with no disconnect; neither process received the other's symbols. Run twice. Live stack /provider/status stayed connected:true.
- Probe CPU was 4% of one core at about 60 ticks/s, 11-13% at about 335 ticks/s and 15% at 464 ticks/s. Breeze's handler is about 37 µs per tick; the rest is socket.io/engine.io frame handling on the GIL-holding receive thread. RSS peaked at 228 MB.
- NSE /api/quote-equity?symbol=RELIANCE returned 403 from AkamaiGHost (blocked, confirmed). /api/NextApi/apiClient/GetQuoteApi?functionName=getSymbolData&marketType=N&series=EQ&symbol=X returned 200 with the same cookie prime: full quote, 5-level book, band, delivery %, index list.
- Measured against Breeze cumulative volume, NSE heatmap-symbols NIFTY 50 is 49 s old (median of 50 names, p90 51 s; matches its lastUpdatedTime). The NextApi quote was 48.6 s and 65.2 s old while its lastUpdateTime claimed 8-9 s.
- NSE allIndices (139 indices) has a minute-resolution label 1-2 min behind. Its values were 2.2 s old at one read and 60.2 s old at another (NIFTY 50 value match); in another pair the values changed within 17 s.
- NSE heatmap-symbols refreshes in batches about every 60-110 s (10:14:05 -> 10:15:53; 0/50 rows changed in 43 s, then 50/50). live-analysis-variations has a cadence of about 52 s (label 11-22 s at read); most-active by value ≥60 s; marketStatus content was identical over 43 s with GIFT NIFTY TIMESTMP 3 min behind.
- NSE option-chain-v3 NIFTY 09-Nov (286 KB, 135 strikes, IV, buyPrice1/sellPrice1) had records.timestamp 47-86 s behind the fetch. option-chain-contract-info lists 18 expiries.
- NSE chart-databyindex-dynamic (RELIANCEEQN) returns one point per minute since 09:00:59 (pre-open), identical 41 s later (about a 60 s cache); its epoch-ms values are IST wall-clock encoded as UTC.
- Priming on www.nseindia.com/market-data/top-gainers-losers returned 200 (310 KB, 0.6 s) twice. 28 NSE GETs total, each ≥2 s after the previous one, at most 5 per endpoint, 80-300 ms each; no 429, and the only 403 was quote-equity.
- Probe footprint: 6 generate_session calls (one per probe process, each a single customer-details REST call), 0 get_quotes, 0 get_names, 0 orders. The security master came from a scratch copy via shared.breeze_cache (BREEZE_CACHE_DIR), so nothing under data/ was written.

## Risks
- Zombie socket: live_ticks._teardown_ws() calls only breeze.ws_disconnect(), which leaves the socket.io connection up and auto-reconnecting with every token re-joined. After any teardown or strike cool-off the next ws_connect opens a second socket: double ticks, leaked connections, possibly hitting an unknown per-user connection limit. Fix before arming LIVE_TICKS (patch request for LV-DATA: call handler.sio.disconnect() and clear tokenlist).
- live_ticks.py maps ticks by isec/stock_code, but every tick arrives as '4.1!<token>', so no consumer finds them (the September 'L1 ticks silent' note). MAX_SYMBOLS=50 is also below index + 50 members. The token map must come from NSEScripMaster, scoped per instrument type, because 2 token values collide between the NSE cash and NFO masters.
- No server-side subscribe ack: an ICICI subscription limit above 1,040 tokens, if one exists, would fail silently. The engine must verify each token by its first tick and report unsubscribed or never-ticked tokens on SYS.
- 1,040 tokens were held for 90 s only, on one busy morning; there is no soak, afternoon or expiry-day measurement. Treat 500 stocks + indices + ≤60 F&O as the operating cap and 1,000 as an untested ceiling.
- CPU/GIL: 11-15% of a core on a GIL-holding socket.io receive thread at 500-1,000 symbols. Inside data-service this competes with sync routes and the event loop, the same class of issue as the 25 Oct hang. Prefer a separate tick-gateway process (shown safe by the two-client test) or watch loop_stall after arming.
- Honesty: NSE website data are about 1 minute delayed for stocks (49-65 s), and NextApi's lastUpdateTime claims 8-9 s. Labelling any NSE website source 'NSE LIVE', or deriving age from its labels, would misstate freshness. Use 'NSE DELAYED ~1 min' with measured age.
- Index tokens broadcast at a fixed 10/4/2 Hz whether or not the value changed. Forwarding them unconflated to ui-api or the browser wastes CPU and bandwidth; conflate to ≤1 Hz.
- Illiquid names can be silent for up to 78 s on a healthy socket. A per-symbol 'STALE' rule based on symbol silence would falsely flag them; feed health must come from the 10 Hz NIFTY 50 heartbeat, and per-symbol age shown as 'last trade Ns'.
- Akamai: quote-equity is 403 per path, and B1 saw a 403 when priming on www.nseindia.com/ with PacedClient. NSE fallback polling across many symbols (NextApi per symbol) could trip the 600 s breaker and blank the fallback for everyone, so keep NextApi on demand only at ≥60 s per symbol.
- The session token rotates with the daily ICICI login. A separate tick-gateway process must reload the token after the 08:00 login (and must never start a login itself), or its socket dies at the next reconnect.
- Unit traps for builders: tick ttv is in ₹ lakh despite the 'C' suffix; index ticks carry empty strings for bid/ask/ttq; F&O CHNGOI arrived empty; NSE chart-databyindex epoch-ms values are IST wall-clock encoded as UTC.

Evidence (raw payloads, probe scripts, per-step JSON): the PM's scratch directory, not in the repo.
