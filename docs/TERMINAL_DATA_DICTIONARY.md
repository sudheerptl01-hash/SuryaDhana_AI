# Terminal data dictionary (`dataset_catalog`)

Every dataset the SuryaDhana terminal shows, as data-service's `dataset_catalog` declares it (Terminal v2 PLAN §0.12 / 1.4: the gold `gold_series_catalog` pattern terminal-wide). One row per dataset: who publishes it, when (IST, measured where R-DATA measured it), the IST time by which the terminal expects it stored (`expected_by`, trading-day aware), the lag budget before a row turns red, the job that ingests it, how freshness is read, the dictionary entry that describes the source, the verdict and the badge. `GET /api/data/health` (ui-api) and the SYS › DATA view evaluate exactly these rows (state live | fresh | amber | red | gap | unknown); `scripts/tests` assert every ingest job and every page's data source has a row. Verified by: R-DATA §3 (4 Nov 2026) + B1-DATA probes (5 Nov 2026).

**Generated** by `scripts/terminal_data_dictionary.py` from `services/data-service/data_health/catalog.py` — do not edit by hand; change the catalog and re-run. `--check` fails when this file is stale. Source entries (URLs, formats, traps) live in `docs/NSE_DATA_DICTIONARY.md` and `docs/GOLD_DATA_DICTIONARY.md`; this file is the per-dataset view the terminal itself uses.

Catalog seed: present (67 rows). Nothing here feeds the Decision Desk, the S1 shadow, a directional alert or a ticket price.

## Verdicts and badges

| Verdict | Meaning in the terminal | Datasets |
|---|---|---|
| **PUBLISH-CORE** | ingested (or computed) and shown on a page's primary panels | 46 |
| **PUBLISH-CONTEXT** | ingested and shown inside its section or a details drawer, always with the `context` badge | 20 |
| **LINK-ONLY** | a labelled link to the publisher; nothing is fetched or stored by the stack | 1 |
| **DO-NOT-PUBLISH** | not fetched, not shown (dead, blocked by terms, or shown to be noise) | 0 |
| **total** | | 67 |

| Badge | Meaning | Datasets |
|---|---|---|
| `context` | a description or a measured relationship that PASSED as a description, never as a forecast; rendered in the neutral token | 39 |
| `arithmetic` | an identity, a model convention or an exchange rule that makes no claim about the future (IV, Greeks, points attribution, SPAN) | 27 |
| `heuristic` | a house rule without evidence, shown with its measured error where one exists (the 12 % margin estimate: 4.8× too high) | 1 |
| `signal` | only by a FINDINGS PASS row from a pre-registered study (PLAN before results, PIT data, \|t\| ≥ 2 full sample and both halves, after the cost floor) | **0 — none exists in F&O, gold or index attribution** |

Context metrics render in the neutral token and are never coloured bullish or bearish; every verdict sentence ends "describes, does not predict"; no composite score; the same number appears once per page.

## Pages → datasets

| Page | Datasets |
|---|---|
| ALFA | [`alpha_shadow`](#alpha_shadow) |
| BRF | [`data_gaps`](#data_gaps), [`index_driver_state`](#index_driver_state), [`index_valuation_history`](#index_valuation_history), [`market_monitor`](#market_monitor), [`nse_fii_dii_cash`](#nse_fii_dii_cash), [`nse_live`](#nse_live) |
| BRKR | [`breeze_session`](#breeze_session) |
| BTST | [`ohlcv`](#ohlcv) |
| CF | [`nse_live`](#nse_live) |
| CHRT | [`ohlcv`](#ohlcv), [`tick_store`](#tick_store) |
| DEAL | [`nse_bhavcopy`](#nse_bhavcopy), [`nse_deals`](#nse_deals) |
| DERV | [`archive:chain`](#archive:chain), [`index_ohlc_daily`](#index_ohlc_daily), [`iv_expiry_daily`](#iv_expiry_daily), [`iv_expiry_replay`](#iv_expiry_replay), [`iv_intraday`](#iv_intraday), [`iv_summary_daily`](#iv_summary_daily), [`iv_surface_daily`](#iv_surface_daily), [`market_index_daily`](#market_index_daily), [`nse_combined_oi`](#nse_combined_oi), [`nse_contract_delta`](#nse_contract_delta), [`nse_fo_daily`](#nse_fo_daily), [`nse_fo_volt`](#nse_fo_volt), [`nse_mwpl_clients`](#nse_mwpl_clients), [`option_history_json`](#option_history_json), [`vix_daily`](#vix_daily) |
| DES | [`iv_event_log`](#iv_event_log), [`iv_summary_daily`](#iv_summary_daily), [`nse_bhavcopy`](#nse_bhavcopy) |
| DESK | [`desk_mark`](#desk_mark), [`index_contribution_daily`](#index_contribution_daily), [`nse_bhavcopy`](#nse_bhavcopy), [`nse_deals`](#nse_deals), [`ohlcv`](#ohlcv), [`surveillance`](#surveillance) |
| EQS | [`nse_bhavcopy`](#nse_bhavcopy), [`ohlcv`](#ohlcv), [`surveillance`](#surveillance) |
| ERN | [`nse_events`](#nse_events), [`nse_results`](#nse_results) |
| EVTS | [`iv_event_log`](#iv_event_log), [`iv_expiry_daily`](#iv_expiry_daily), [`iv_summary_daily`](#iv_summary_daily), [`nse_events`](#nse_events), [`nse_results`](#nse_results) |
| GBOX | [`ml_features`](#ml_features) |
| GOLD | [`breeze_security_master`](#breeze_security_master), [`breeze_session`](#breeze_session), [`gold_asia_daily`](#gold_asia_daily), [`gold_brief_docs`](#gold_brief_docs), [`gold_cme_daily_voi`](#gold_cme_daily_voi), [`gold_cot`](#gold_cot), [`gold_curve_mcx`](#gold_curve_mcx), [`gold_daily_bars`](#gold_daily_bars), [`gold_etf_holdings`](#gold_etf_holdings), [`gold_events`](#gold_events), [`gold_fed_path`](#gold_fed_path), [`gold_fred_daily`](#gold_fred_daily), [`gold_health_daily`](#gold_health_daily), [`gold_india_ibja`](#gold_india_ibja), [`gold_preopen_log`](#gold_preopen_log), [`gold_treasury`](#gold_treasury) |
| HDS | [`nse_shareholding`](#nse_shareholding) |
| INSD | [`nse_insider_trades`](#nse_insider_trades) |
| MCXG | [`breeze_security_master`](#breeze_security_master), [`breeze_session`](#breeze_session), [`gold_curve_mcx`](#gold_curve_mcx), [`gold_daily_bars`](#gold_daily_bars) |
| MEMB | [`index_constituents_daily`](#index_constituents_daily), [`index_contribution_daily`](#index_contribution_daily), [`index_contribution_fit`](#index_contribution_fit), [`index_driver_state`](#index_driver_state), [`index_ohlc_daily`](#index_ohlc_daily), [`index_weights_daily`](#index_weights_daily) |
| MKT | [`index_ohlc_daily`](#index_ohlc_daily), [`index_valuation_history`](#index_valuation_history), [`market_index_daily`](#market_index_daily), [`market_monitor`](#market_monitor), [`nse_bhavcopy`](#nse_bhavcopy), [`nse_fii_dii_cash`](#nse_fii_dii_cash), [`nse_fii_stats`](#nse_fii_stats), [`nse_fo_daily`](#nse_fo_daily), [`nse_participant_oi`](#nse_participant_oi), [`nse_participant_vol`](#nse_participant_vol) |
| MLEN | [`ml_features`](#ml_features) |
| MOV | [`archive:internals`](#archive:internals), [`data_gaps`](#data_gaps), [`index_constituents_daily`](#index_constituents_daily), [`nse_live`](#nse_live) |
| MRGN | [`nse_mtf`](#nse_mtf) |
| NEWS | [`news_scanner`](#news_scanner), [`news_track_record`](#news_track_record) |
| OMON | [`archive:chain`](#archive:chain), [`iv_expiry_daily`](#iv_expiry_daily), [`iv_intraday`](#iv_intraday), [`iv_summary_daily`](#iv_summary_daily), [`iv_surface_daily`](#iv_surface_daily), [`nse_combined_oi`](#nse_combined_oi), [`nse_contract_delta`](#nse_contract_delta), [`nse_fo_daily`](#nse_fo_daily), [`nse_fo_volt`](#nse_fo_volt), [`nse_mwpl_clients`](#nse_mwpl_clients), [`option_chain_eod`](#option_chain_eod), [`option_chain_live`](#option_chain_live), [`rate_curve`](#rate_curve), [`vix_daily`](#vix_daily) |
| OSTR | [`nse_fo_daily`](#nse_fo_daily), [`option_chain_eod`](#option_chain_eod), [`rate_curve`](#rate_curve) |
| PORT | [`breeze_session`](#breeze_session) |
| PRE | [`archive:preopen`](#archive:preopen) |
| RSCH | [`alpha_shadow`](#alpha_shadow), [`nse_results`](#nse_results) |
| RSK | [`market_index_daily`](#market_index_daily) |
| SYS | [`data_gaps`](#data_gaps), [`db_backup`](#db_backup), [`ingest_log`](#ingest_log) |
| WEI | [`gold_daily_bars`](#gold_daily_bars) |
| WHSE | [`ohlcv`](#ohlcv) |
| WRAP | [`archive:internals`](#archive:internals), [`data_gaps`](#data_gaps), [`market_monitor`](#market_monitor), [`nse_fii_dii_cash`](#nse_fii_dii_cash) |
| WTCH | [`nse_live`](#nse_live) |

## Ingest jobs → datasets

| Job | Datasets |
|---|---|
| `alpha_shadow_daily` | [`alpha_shadow`](#alpha_shadow) |
| `data_health_refresh` | [`data_gaps`](#data_gaps), [`ingest_log`](#ingest_log) |
| `db_backup_daily` | [`db_backup`](#db_backup) |
| `desk_daily` | [`desk_mark`](#desk_mark) |
| `eod_data_pipeline` | [`market_index_daily`](#market_index_daily), [`market_monitor`](#market_monitor), [`ml_features`](#ml_features), [`nse_bhavcopy`](#nse_bhavcopy), [`nse_events`](#nse_events), [`ohlcv`](#ohlcv) |
| `gold_asia_close` | [`gold_asia_daily`](#gold_asia_daily) |
| `gold_brief_ingest` | [`gold_brief_docs`](#gold_brief_docs) |
| `gold_calendar_refresh` | [`gold_events`](#gold_events) |
| `gold_cme_daily` | [`gold_cme_daily_voi`](#gold_cme_daily_voi) |
| `gold_cot_weekly` | [`gold_cot`](#gold_cot) |
| `gold_fred_daily` | [`gold_fred_daily`](#gold_fred_daily) |
| `gold_health_snapshot` | [`gold_health_daily`](#gold_health_daily) |
| `gold_india_pm` | [`gold_india_ibja`](#gold_india_ibja) |
| `gold_mcx_master` | [`breeze_security_master`](#breeze_security_master), [`gold_curve_mcx`](#gold_curve_mcx) |
| `gold_morning` | [`gold_etf_holdings`](#gold_etf_holdings), [`gold_fed_path`](#gold_fed_path) |
| `gold_overnight` | [`gold_daily_bars`](#gold_daily_bars), [`gold_treasury`](#gold_treasury) |
| `gold_preopen_snapshot` | [`gold_preopen_log`](#gold_preopen_log) |
| `icici_session_refresh` | [`breeze_session`](#breeze_session) |
| `index_drivers_daily` | [`index_constituents_daily`](#index_constituents_daily), [`index_contribution_daily`](#index_contribution_daily), [`index_contribution_fit`](#index_contribution_fit), [`index_driver_state`](#index_driver_state), [`index_weights_daily`](#index_weights_daily) |
| `index_valuation_daily` | [`index_valuation_history`](#index_valuation_history) |
| `internals_sample` | [`archive:internals`](#archive:internals) |
| `iv_eod` | [`index_ohlc_daily`](#index_ohlc_daily), [`iv_event_log`](#iv_event_log), [`iv_expiry_daily`](#iv_expiry_daily), [`iv_summary_daily`](#iv_summary_daily), [`iv_surface_daily`](#iv_surface_daily), [`nse_contract_delta`](#nse_contract_delta), [`nse_fo_volt`](#nse_fo_volt), [`rate_curve`](#rate_curve), [`vix_daily`](#vix_daily) |
| `iv_intraday` | [`archive:chain`](#archive:chain), [`iv_intraday`](#iv_intraday) |
| `news_track_record_daily` | [`news_track_record`](#news_track_record) |
| `nse_filings_weekly` | [`nse_shareholding`](#nse_shareholding) |
| `nse_insider_daily` | [`nse_insider_trades`](#nse_insider_trades) |
| `nse_positions_catchup` | [`nse_combined_oi`](#nse_combined_oi), [`nse_deals`](#nse_deals), [`nse_fii_dii_cash`](#nse_fii_dii_cash), [`nse_fii_stats`](#nse_fii_stats), [`nse_fo_daily`](#nse_fo_daily), [`nse_mtf`](#nse_mtf), [`nse_mwpl_clients`](#nse_mwpl_clients), [`nse_participant_oi`](#nse_participant_oi), [`nse_participant_vol`](#nse_participant_vol), [`option_chain_eod`](#option_chain_eod) |
| `preopen_capture` | [`archive:preopen`](#archive:preopen) |
| `results_capture_daily` | [`nse_results`](#nse_results) |

## Publishers the stack may contact (`shared/http_client.py` allowlist)

- **BREEZE_HOSTS:** `api.icicidirect.com`, `breezeapi.icicidirect.com`
- **GOLD_HOSTS:** `api.gold-api.com`, `api.imf.org`, `api.spdrgoldshares.com`, `api.stlouisfed.org`, `cdn.lbma.org.uk`, `directlink.icicidirect.com`, `en.sge.com.cn`, `fred.stlouisfed.org`, `fsapi.gold.org`, `ftp.cmegroup.com`, `home.treasury.gov`, `ibjarates.com`, `news.google.com`, `nfs.faireconomy.media`, `ocean.nivel.bazg.admin.ch`, `pib.gov.in`, `portal.amfiindia.com`, `publicreporting.cftc.gov`, `thedocs.worldbank.org`, `www.atlantafed.org`, `www.bea.gov`, `www.cftc.gov`, `www.ishares.com`, `www.lbma.org.uk`, `www.matteoiacoviello.com`, `www.rbi.org.in`, `www.sge.com.cn`, `www.shfe.com.cn`, `zerodha.com`
- **LIBRARY_UA_HOSTS:** `fred.stlouisfed.org`
- **NSE_HOSTS:** `niftyindices.com`, `nsearchives.nseindia.com`, `www.niftyindices.com`, `www.nseindia.com`
- **YAHOO_HOSTS:** `query1.finance.yahoo.com`, `query2.finance.yahoo.com`
- **_PLAIN_UA_HOSTS:** `api.gold-api.com`, `api.imf.org`, `api.stlouisfed.org`, `home.treasury.gov`, `nfs.faireconomy.media`

Never fetched: `mcxindia.com`, `www.cmegroup.com`, `kitco.com`, `investing.com`, `stooq`, `goldprice.org`, `prices.lbma.org.uk` (PLAN §0.6). Every fetcher is paced ≥ 1.2 s per host, 20 s timeout, browser UA for NSE, a 600 s breaker after a 403/429 from an NSE host; no new Yahoo caller anywhere (PLAN §0.7).

## The datasets (catalog order)

<a id="ohlcv"></a>
### `ohlcv` · Yahoo daily bars (1,496 tickers)

- **Pages:** EQS, CHRT, WHSE, DESK, BTST · **Publisher:** Yahoo Finance (chart API)
- **Published (IST):** ~18:00 · **Expected stored by:** 19:00 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `eod_data_pipeline` · **Freshness read from:** `MAX(date)` of `ohlcv`
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [NSE_DATA_DICTIONARY.md#yahoo](../docs/NSE_DATA_DICTIONARY.md#yahoo)
- **Note:** PLAN §0.7: no new Yahoo caller; the existing refresh stays

<a id="nse_bhavcopy"></a>
### `nse_bhavcopy` · NSE equity full bhavcopy

- **Pages:** DES, EQS, DEAL, MKT, DESK · **Publisher:** NSE (nsearchives.nseindia.com)
- **Published (IST):** ~18:30; re-published 22:05 (measured) · **Expected stored by:** 19:00 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `eod_data_pipeline` · **Freshness read from:** `MAX(date)` of `nse_bhavcopy`
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [NSE_DATA_DICTIONARY.md#bhavcopy](../docs/NSE_DATA_DICTIONARY.md#bhavcopy)
- **Note:** revisions: the 22:45 pass re-fetches with If-Modified-Since; the table holds the LATEST publication (release_at = the publisher's Last-Modified of that copy, first_seen_at = our first sighting of the day); both copies stay on disk (data/nse_bhavcopy/YYYY/sec_bhavdata_full_YYYYMMDD.csv.gz = the first, ….rN.csv.gz = revision N) and each fetch is an ingest_log row (sha256, Last-Modified, revision)

<a id="nse_fo_daily"></a>
### `nse_fo_daily` · F&O bhavcopy per-underlying aggregate

- **Pages:** DERV, OMON, OSTR, MKT · **Publisher:** NSE (nsearchives.nseindia.com)
- **Published (IST):** 20:10 (measured) · **Expected stored by:** 21:00 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `nse_positions_catchup` · **Freshness read from:** `MAX(date)` of `nse_fo_daily`
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [NSE_DATA_DICTIONARY.md#fo-bhavcopy](../docs/NSE_DATA_DICTIONARY.md#fo-bhavcopy)

<a id="nse_participant_oi"></a>
### `nse_participant_oi` · Participant-wise open interest

- **Pages:** MKT · **Publisher:** NSE (nsearchives.nseindia.com)
- **Published (IST):** 20:10 (measured) · **Expected stored by:** 21:00 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `nse_positions_catchup` · **Freshness read from:** `MAX(date)` of `nse_participant_oi`
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [NSE_DATA_DICTIONARY.md#participant-oi](../docs/NSE_DATA_DICTIONARY.md#participant-oi)

<a id="nse_deals"></a>
### `nse_deals` · Bulk / block / short-selling deals

- **Pages:** DEAL, DESK · **Publisher:** NSE (www.nseindia.com/api)
- **Published (IST):** evening · **Expected stored by:** 21:00 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `nse_positions_catchup` · **Freshness read from:** `MAX(date)` of `nse_deals`
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [NSE_DATA_DICTIONARY.md#deals](../docs/NSE_DATA_DICTIONARY.md#deals)
- **Note:** late additions appear on later days: ingest_log keeps the revisions

<a id="nse_mtf"></a>
### `nse_mtf` · Margin-trading funded positions (T−1 file)

- **Pages:** MRGN · **Publisher:** NSE (nsearchives.nseindia.com)
- **Published (IST):** 22:12 for T−1 (measured) · **Expected stored by:** 23:00 IST on the trading day 1 after the session it describes · **Cadence:** daily · **Amber after:** 2 sessions, red beyond that
- **Ingest job:** `nse_positions_catchup` · **Freshness read from:** `MAX(date)` of `nse_mtf`
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [NSE_DATA_DICTIONARY.md#mtf](../docs/NSE_DATA_DICTIONARY.md#mtf)
- **Note:** structural T+1: the file for session T lands at 22:12 on T+1 (22:45 pass)

<a id="nse_fii_dii_cash"></a>
### `nse_fii_dii_cash` · FII / DII cash (NSE serves the latest day only)

- **Pages:** BRF, WRAP, MKT · **Publisher:** NSE (www.nseindia.com/api)
- **Published (IST):** same evening (provisional) · **Expected stored by:** 21:00 IST · **Cadence:** session · **Amber after:** 1 sessions, red beyond that · **unrecoverable** (a missed capture is a gap row, never backfilled)
- **Ingest job:** `nse_positions_catchup` · **Freshness read from:** `MAX(date)` of `nse_fii_dii_cash`
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [NSE_DATA_DICTIONARY.md#fii-dii](../docs/NSE_DATA_DICTIONARY.md#fii-dii)
- **Note:** a day not fetched the same evening is lost: gap row

<a id="nse_insider_trades"></a>
### `nse_insider_trades` · Insider trades (PIT)

- **Pages:** INSD · **Publisher:** NSE (www.nseindia.com/api)
- **Published (IST):** intimation ≈ T+2 · **Expected stored by:** 22:30 IST · **Cadence:** session · **Amber after:** 4 sessions, red beyond that
- **Ingest job:** `nse_insider_daily` · **Freshness read from:** `MAX(intimation_date)` of `nse_insider_trades`
- **Verdict · badge:** PUBLISH-CONTEXT · `context` · **Dictionary:** [NSE_DATA_DICTIONARY.md#insider](../docs/NSE_DATA_DICTIONARY.md#insider)
- **Note:** the single-filing feed, last 7 days every weekday evening (21:50); Saturday's weekly run also covers it

<a id="nse_shareholding"></a>
### `nse_shareholding` · Shareholding pattern (XBRL)

- **Pages:** HDS · **Publisher:** NSE (www.nseindia.com/api)
- **Published (IST):** quarterly, ≤ 21 days after quarter end · **Expected stored by:** no deadline · **Cadence:** quarterly · **Amber after:** 100 days, red beyond that
- **Ingest job:** `nse_filings_weekly` · **Freshness read from:** `MAX(period_end)` of `nse_shareholding`
- **Verdict · badge:** PUBLISH-CORE · `context` · **Dictionary:** [NSE_DATA_DICTIONARY.md#shareholding](../docs/NSE_DATA_DICTIONARY.md#shareholding)

<a id="nse_results"></a>
### `nse_results` · Results release times

- **Pages:** ERN, EVTS, RSCH · **Publisher:** NSE (www.nseindia.com/api)
- **Published (IST):** filing timestamp (real time) · **Expected stored by:** 21:30 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `results_capture_daily` · **Freshness read from:** `MAX(released_at)` of `nse_results`
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [NSE_DATA_DICTIONARY.md#results](../docs/NSE_DATA_DICTIONARY.md#results)
- **Note:** catch-up window = days down + 3 (Wave 0 0.9)

<a id="nse_events"></a>
### `nse_events` · Corporate calendar (results dates, board meetings, actions)

- **Pages:** EVTS, ERN · **Publisher:** NSE (www.nseindia.com/api)
- **Published (IST):** forward-looking · **Expected stored by:** 19:00 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `eod_data_pipeline` · **Freshness read from:** `MAX(first_seen)` of `nse_events`
- **Verdict · badge:** PUBLISH-CORE · `context` · **Dictionary:** [NSE_DATA_DICTIONARY.md#events](../docs/NSE_DATA_DICTIONARY.md#events)

<a id="market_index_daily"></a>
### `market_index_daily` · NIFTY 50 + India VIX closes (Desk series)

- **Pages:** DERV, MKT, RSK · **Publisher:** Yahoo + NSE allIndices
- **Published (IST):** 15:30 close · **Expected stored by:** 19:00 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `eod_data_pipeline` · **Freshness read from:** `MAX(date)` of `market_index_daily` where `symbol = 'NIFTY50'`
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#market_index_daily](../docs/TERMINAL_DATA_DICTIONARY.md#market_index_daily)
- **Note:** the crash filter's series; O-T9 decides whether the NSE daily file replaces it (DO NOT CHANGE without review); every other index in this table is NSE-only (source nse_daily_file) from the first run: the PK (symbol, date) holds one source per day, so the Yahoo rows are not kept beside them

<a id="market_monitor"></a>
### `market_monitor` · Market monitor (breadth, regime, market map)

- **Pages:** MKT, BRF, WRAP · **Publisher:** SuryaDhana (derived)
- **Published (IST):** derived · **Expected stored by:** 19:00 IST · **Cadence:** derived · **Amber after:** 1 days, red beyond that
- **Ingest job:** `eod_data_pipeline` · **Freshness read from:** composed by ui-api from telemetry / its own stores (data-service reports `unknown`)
- **Verdict · badge:** PUBLISH-CORE · `context` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#market_monitor](../docs/TERMINAL_DATA_DICTIONARY.md#market_monitor)
- **Note:** as_of from /db/market-monitor (ui-api composes)

<a id="index_valuation_history"></a>
### `index_valuation_history` · Index valuation history (P/E, P/B, DY)

- **Pages:** MKT, BRF · **Publisher:** NSE (nsearchives.nseindia.com)
- **Published (IST):** ind_close_all (read 19:15; re-written 23:20) · **Expected stored by:** 20:00 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `index_valuation_daily` · **Freshness read from:** `derived/index_valuation_history.csv` (csv:date)
- **Verdict · badge:** PUBLISH-CORE · `context` · **Dictionary:** [NSE_DATA_DICTIONARY.md#ind-close-all](../docs/NSE_DATA_DICTIONARY.md#ind-close-all)

<a id="option_chain_eod"></a>
### `option_chain_eod` · EOD option chain + IV (from the F&O file)

- **Pages:** OMON, OSTR · **Publisher:** SuryaDhana (derived)
- **Published (IST):** from nse_fo_daily · **Expected stored by:** 21:00 IST · **Cadence:** derived · **Amber after:** 1 days, red beyond that
- **Ingest job:** `nse_positions_catchup` · **Freshness read from:** composed by ui-api from telemetry / its own stores (data-service reports `unknown`)
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#option_chain_eod](../docs/TERMINAL_DATA_DICTIONARY.md#option_chain_eod)
- **Note:** computed on request from the cached F&O file; as_of = the file's date

<a id="option_history_json"></a>
### `option_history_json` · Legacy near-expiry ATM IV history (NIFTY, BANKNIFTY)

- **Pages:** DERV · **Publisher:** SuryaDhana (derived)
- **Published (IST):** lazy on request · **Expected stored by:** 21:00 IST · **Cadence:** derived · **Amber after:** 1 days, red beyond that
- **Ingest job:** none (read on request) · **Freshness read from:** `derived/option_history.json` (json:date)
- **Verdict · badge:** PUBLISH-CONTEXT · `context` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#option_history_json](../docs/TERMINAL_DATA_DICTIONARY.md#option_history_json)
- **Note:** superseded by iv_summary_daily; kept one release as an alias (PLAN 1.1)

<a id="option_chain_live"></a>
### `option_chain_live` · Live option chain (NSE option-chain-v3, 30 s TTL)

- **Pages:** OMON · **Publisher:** NSE (www.nseindia.com/api)
- **Published (IST):** live · **Expected stored by:** no deadline · **Cadence:** live · **Amber after:** 1 days, red beyond that
- **Ingest job:** none (read on request) · **Freshness read from:** composed by ui-api from telemetry / its own stores (data-service reports `unknown`)
- **Verdict · badge:** PUBLISH-CONTEXT · `context` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#option_chain_live](../docs/TERMINAL_DATA_DICTIONARY.md#option_chain_live)
- **Note:** never stored; the 15-min Breeze pilot stores iv_intraday instead

<a id="archive:preopen"></a>
### `archive:preopen` · Pre-open book (order imbalance)

- **Pages:** PRE · **Publisher:** NSE (www.nseindia.com/api)
- **Published (IST):** 09:00–09:08 · **Expected stored by:** 09:12 IST · **Cadence:** session · **Amber after:** 1 sessions, red beyond that · **unrecoverable** (a missed capture is a gap row, never backfilled)
- **Ingest job:** `preopen_capture` · **Freshness read from:** dated files under `data/nse_archive/preopen/`
- **Verdict · badge:** PUBLISH-CORE · `context` · **Dictionary:** [NSE_DATA_DICTIONARY.md#preopen](../docs/NSE_DATA_DICTIONARY.md#preopen)

<a id="archive:internals"></a>
### `archive:internals` · Intraday breadth samples (2-min)

- **Pages:** MOV, WRAP · **Publisher:** NSE (www.nseindia.com/api)
- **Published (IST):** live 09:15–15:31 · **Expected stored by:** 15:35 IST · **Cadence:** session · **Amber after:** 1 sessions, red beyond that · **unrecoverable** (a missed capture is a gap row, never backfilled)
- **Ingest job:** `internals_sample` · **Freshness read from:** dated files under `data/nse_archive/internals/`
- **Verdict · badge:** PUBLISH-CORE · `context` · **Dictionary:** [NSE_DATA_DICTIONARY.md#internals](../docs/NSE_DATA_DICTIONARY.md#internals)

<a id="nse_live"></a>
### `nse_live` · NSE live quotes / movers / indices / GIFT / announcements

- **Pages:** MOV, WTCH, CF, BRF · **Publisher:** NSE (www.nseindia.com/api)
- **Published (IST):** live · **Expected stored by:** no deadline · **Cadence:** live · **Amber after:** 1 days, red beyond that
- **Ingest job:** none (read on request) · **Freshness read from:** composed by ui-api from telemetry / its own stores (data-service reports `unknown`)
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#nse_live](../docs/TERMINAL_DATA_DICTIONARY.md#nse_live)
- **Note:** ≤ 60 s in session; the header chip shows LINK DOWN / DELAYED

<a id="surveillance"></a>
### `surveillance` · Surveillance / price bands / F&O ban list

- **Pages:** EQS, DESK · **Publisher:** NSE (nsearchives.nseindia.com)
- **Published (IST):** evening (ban list 19:24 for the next session) · **Expected stored by:** 19:30 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** none (read on request) · **Freshness read from:** dated files under `data/nse_archive/surveillance/`
- **Verdict · badge:** PUBLISH-CORE · `context` · **Dictionary:** [NSE_DATA_DICTIONARY.md#surveillance](../docs/NSE_DATA_DICTIONARY.md#surveillance)

<a id="breeze_session"></a>
### `breeze_session` · ICICI Breeze session (quotes, MCX, holdings)

- **Pages:** BRKR, PORT, MCXG, GOLD · **Publisher:** ICICI Direct
- **Published (IST):** 08:00 login · **Expected stored by:** 08:30 IST · **Cadence:** session · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `icici_session_refresh` · **Freshness read from:** composed by ui-api from telemetry / its own stores (data-service reports `unknown`)
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#breeze_session](../docs/TERMINAL_DATA_DICTIONARY.md#breeze_session)
- **Note:** ui-api telemetry: logged in by 08:30 without a human (Wave 0 0.3)

<a id="tick_store"></a>
### `tick_store` · Breeze live ticks (tick store)

- **Pages:** CHRT · **Publisher:** ICICI Direct
- **Published (IST):** live · **Expected stored by:** no deadline · **Cadence:** live · **Amber after:** 1 days, red beyond that
- **Ingest job:** none (read on request) · **Freshness read from:** dated files under `data/nse_archive/../ticks/`
- **Verdict · badge:** LINK-ONLY · `context` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#tick_store](../docs/TERMINAL_DATA_DICTIONARY.md#tick_store)
- **Note:** never armed (LIVE_TICKS=0) by decision O-T29

<a id="breeze_security_master"></a>
### `breeze_security_master` · ICICI security master

- **Pages:** MCXG, GOLD · **Publisher:** ICICI Direct
- **Published (IST):** daily · **Expected stored by:** 08:00 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `gold_mcx_master` · **Freshness read from:** `../cache/breeze/SecurityMaster.zip` (mtime)
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#breeze_security_master](../docs/TERMINAL_DATA_DICTIONARY.md#breeze_security_master)

<a id="news_scanner"></a>
### `news_scanner` · News scanner JSON (owner-run)

- **Pages:** NEWS · **Publisher:** owner
- **Published (IST):** manual · **Expected stored by:** no deadline · **Cadence:** manual · **Amber after:** 5 days, red beyond that
- **Ingest job:** none (read on request) · **Freshness read from:** dated files under `data/nse_archive/../../new_scnner/`
- **Verdict · badge:** PUBLISH-CONTEXT · `context` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#news_scanner](../docs/TERMINAL_DATA_DICTIONARY.md#news_scanner)
- **Note:** news picks performed like random same-size stocks (news_scan_track_record)

<a id="news_track_record"></a>
### `news_track_record` · News scanner track record

- **Pages:** NEWS · **Publisher:** SuryaDhana (derived)
- **Published (IST):** derived · **Expected stored by:** 20:00 IST · **Cadence:** derived · **Amber after:** 1 days, red beyond that
- **Ingest job:** `news_track_record_daily` · **Freshness read from:** composed by ui-api from telemetry / its own stores (data-service reports `unknown`)
- **Verdict · badge:** PUBLISH-CONTEXT · `context` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#news_track_record](../docs/TERMINAL_DATA_DICTIONARY.md#news_track_record)

<a id="desk_mark"></a>
### `desk_mark` · Decision Desk mark / plans (paper)

- **Pages:** DESK · **Publisher:** SuryaDhana (derived)
- **Published (IST):** derived · **Expected stored by:** 20:00 IST · **Cadence:** derived · **Amber after:** 1 days, red beyond that
- **Ingest job:** `desk_daily` · **Freshness read from:** composed by ui-api from telemetry / its own stores (data-service reports `unknown`)
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#desk_mark](../docs/TERMINAL_DATA_DICTIONARY.md#desk_mark)
- **Note:** ui-api composes from data/desk*.sqlite; PAPER ONLY

<a id="alpha_shadow"></a>
### `alpha_shadow` · S1 paper shadow NAV

- **Pages:** ALFA, RSCH · **Publisher:** SuryaDhana (derived)
- **Published (IST):** derived · **Expected stored by:** 20:15 IST · **Cadence:** derived · **Amber after:** 1 days, red beyond that
- **Ingest job:** `alpha_shadow_daily` · **Freshness read from:** `../../alpha_lab/paper/state.json` (mtime)
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#alpha_shadow](../docs/TERMINAL_DATA_DICTIONARY.md#alpha_shadow)

<a id="ml_features"></a>
### `ml_features` · ML features (dormant pipeline)

- **Pages:** MLEN, GBOX · **Publisher:** SuryaDhana (derived)
- **Published (IST):** derived · **Expected stored by:** 19:30 IST · **Cadence:** derived · **Amber after:** 1 days, red beyond that
- **Ingest job:** `eod_data_pipeline` · **Freshness read from:** `MAX(date)` of `ml_features`
- **Verdict · badge:** PUBLISH-CONTEXT · `context` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#ml_features](../docs/TERMINAL_DATA_DICTIONARY.md#ml_features)
- **Note:** labels lag 5 sessions by design

<a id="db_backup"></a>
### `db_backup` · Verified DuckDB backup

- **Pages:** SYS · **Publisher:** SuryaDhana (derived)
- **Published (IST):** 02:15 · **Expected stored by:** 03:00 IST on the trading day 1 after the session it describes · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `db_backup_daily` · **Freshness read from:** dated files under `data/nse_archive/../backups/duckdb/`
- **Verdict · badge:** PUBLISH-CONTEXT · `context` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#db_backup](../docs/TERMINAL_DATA_DICTIONARY.md#db_backup)

<a id="gold_daily_bars"></a>
### `gold_daily_bars` · Gold: Yahoo daily series / GC curve / 1-min bars

- **Pages:** GOLD, MCXG, WEI · **Publisher:** Yahoo (one cached fetcher)
- **Published (IST):** continuous · **Expected stored by:** 04:00 IST on the trading day 1 after the session it describes · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `gold_overnight` · **Freshness read from:** `MAX(trade_date)` of `gold_daily_bars`
- **Verdict · badge:** PUBLISH-CORE · `context` · **Dictionary:** [GOLD_DATA_DICTIONARY.md#A1](../docs/GOLD_DATA_DICTIONARY.md#A1)

<a id="gold_cot"></a>
### `gold_cot` · Gold: CFTC COT

- **Pages:** GOLD · **Publisher:** CFTC (Socrata)
- **Published (IST):** Fri 15:30 ET for Tue · **Expected stored by:** no deadline · **Cadence:** weekly · **Amber after:** 11 days, red beyond that
- **Ingest job:** `gold_cot_weekly` · **Freshness read from:** `MAX(report_date)` of `gold_cot`
- **Verdict · badge:** PUBLISH-CONTEXT · `context` · **Dictionary:** [GOLD_DATA_DICTIONARY.md#B10](../docs/GOLD_DATA_DICTIONARY.md#B10)

<a id="gold_cme_daily_voi"></a>
### `gold_cme_daily_voi` · Gold: CME daily OI / volume (FTP)

- **Pages:** GOLD · **Publisher:** CME Group (ftp.cmegroup.com)
- **Published (IST):** T+1 ≈ 14:30 · **Expected stored by:** 17:30 IST on the trading day 1 after the session it describes · **Cadence:** daily · **Amber after:** 2 sessions, red beyond that
- **Ingest job:** `gold_cme_daily` · **Freshness read from:** `MAX(trade_date)` of `gold_cme_daily_voi`
- **Verdict · badge:** PUBLISH-CORE · `context` · **Dictionary:** [GOLD_DATA_DICTIONARY.md#C1](../docs/GOLD_DATA_DICTIONARY.md#C1)
- **Note:** 0 rows until the 229-EPSV fix (Wave 0 0.4)

<a id="gold_fred_daily"></a>
### `gold_fred_daily` · Gold: FRED daily series (18)

- **Pages:** GOLD · **Publisher:** FRED
- **Published (IST):** ~07:00 next day · **Expected stored by:** 08:00 IST on the trading day 1 after the session it describes · **Cadence:** daily · **Amber after:** 2 sessions, red beyond that
- **Ingest job:** `gold_fred_daily` · **Freshness read from:** `MAX(report_date)` of `gold_series` where `source = 'fred_csv' AND freq = 'D'`
- **Verdict · badge:** PUBLISH-CORE · `context` · **Dictionary:** [GOLD_DATA_DICTIONARY.md#G3](../docs/GOLD_DATA_DICTIONARY.md#G3)
- **Note:** keyed REST + breaker (Wave 0 0.4, O-T3)

<a id="gold_treasury"></a>
### `gold_treasury` · Gold: US Treasury real / nominal curves

- **Pages:** GOLD · **Publisher:** US Treasury
- **Published (IST):** ~04:00 · **Expected stored by:** 08:00 IST on the trading day 1 after the session it describes · **Cadence:** daily · **Amber after:** 2 sessions, red beyond that
- **Ingest job:** `gold_overnight` · **Freshness read from:** `MAX(report_date)` of `gold_series` where `source = 'treasury_csv'`
- **Verdict · badge:** PUBLISH-CORE · `context` · **Dictionary:** [GOLD_DATA_DICTIONARY.md#G2](../docs/GOLD_DATA_DICTIONARY.md#G2)

<a id="gold_etf_holdings"></a>
### `gold_etf_holdings` · Gold: GLD / IAU holdings

- **Pages:** GOLD · **Publisher:** SPDR / iShares
- **Published (IST):** ~06:00 · **Expected stored by:** 07:00 IST on the trading day 1 after the session it describes · **Cadence:** daily · **Amber after:** 2 sessions, red beyond that
- **Ingest job:** `gold_morning` · **Freshness read from:** `MAX(report_date)` of `gold_etf_holdings`
- **Verdict · badge:** PUBLISH-CORE · `context` · **Dictionary:** [GOLD_DATA_DICTIONARY.md#A4](../docs/GOLD_DATA_DICTIONARY.md#A4)

<a id="gold_asia_daily"></a>
### `gold_asia_daily` · Gold: SGE / SHFE

- **Pages:** GOLD · **Publisher:** SGE / SHFE
- **Published (IST):** 16:00 · **Expected stored by:** 17:00 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `gold_asia_close` · **Freshness read from:** `MAX(trade_date)` of `gold_asia_daily`
- **Verdict · badge:** PUBLISH-CORE · `context` · **Dictionary:** [GOLD_DATA_DICTIONARY.md#D1](../docs/GOLD_DATA_DICTIONARY.md#D1)

<a id="gold_fed_path"></a>
### `gold_fed_path` · Gold: Atlanta Fed market-implied path

- **Pages:** GOLD · **Publisher:** Atlanta Fed
- **Published (IST):** weekly · **Expected stored by:** no deadline · **Cadence:** weekly · **Amber after:** 7 days, red beyond that
- **Ingest job:** `gold_morning` · **Freshness read from:** `MAX(as_of)` of `gold_fed_path`
- **Verdict · badge:** PUBLISH-CORE · `context` · **Dictionary:** [GOLD_DATA_DICTIONARY.md#G17](../docs/GOLD_DATA_DICTIONARY.md#G17)

<a id="gold_curve_mcx"></a>
### `gold_curve_mcx` · Gold: MCX master / margins / price band

- **Pages:** GOLD, MCXG · **Publisher:** ICICI Breeze (security master)
- **Published (IST):** 07:30 · **Expected stored by:** 08:00 IST on the trading day 1 after the session it describes · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `gold_mcx_master` · **Freshness read from:** `MAX(trade_date)` of `gold_curve` where `exchange = 'MCX'`
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [GOLD_DATA_DICTIONARY.md#F1](../docs/GOLD_DATA_DICTIONARY.md#F1)

<a id="gold_india_ibja"></a>
### `gold_india_ibja` · Gold: IBJA AM / PM, RBI reference rate

- **Pages:** GOLD · **Publisher:** IBJA / RBI
- **Published (IST):** 13:30 / 18:00 · **Expected stored by:** 18:30 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `gold_india_pm` · **Freshness read from:** `MAX(report_date)` of `gold_series` where `series_id LIKE 'IBJA%'`
- **Verdict · badge:** PUBLISH-CORE · `context` · **Dictionary:** [GOLD_DATA_DICTIONARY.md#E1](../docs/GOLD_DATA_DICTIONARY.md#E1)

<a id="gold_health_daily"></a>
### `gold_health_daily` · Gold: health snapshot

- **Pages:** GOLD · **Publisher:** SuryaDhana (derived)
- **Published (IST):** 08:40 · **Expected stored by:** 09:00 IST · **Cadence:** session · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `gold_health_snapshot` · **Freshness read from:** `MAX(day)` of `gold_health_daily`
- **Verdict · badge:** PUBLISH-CORE · `context` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#gold_health_daily](../docs/TERMINAL_DATA_DICTIONARY.md#gold_health_daily)
- **Note:** describes, does not predict

<a id="gold_brief_docs"></a>
### `gold_brief_docs` · Gold: morning brief

- **Pages:** GOLD · **Publisher:** SuryaDhana (derived)
- **Published (IST):** 09:05 · **Expected stored by:** 09:30 IST · **Cadence:** session · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `gold_brief_ingest` · **Freshness read from:** `MAX(report_date)` of `gold_brief_docs`
- **Verdict · badge:** PUBLISH-CORE · `context` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#gold_brief_docs](../docs/TERMINAL_DATA_DICTIONARY.md#gold_brief_docs)

<a id="gold_preopen_log"></a>
### `gold_preopen_log` · Gold: pre-open fair value + captured open (accuracy log)

- **Pages:** GOLD · **Publisher:** SuryaDhana (derived)
- **Published (IST):** 08:45 / 09:10 · **Expected stored by:** 09:15 IST · **Cadence:** session · **Amber after:** 1 sessions, red beyond that · **unrecoverable** (a missed capture is a gap row, never backfilled)
- **Ingest job:** `gold_preopen_snapshot` · **Freshness read from:** `MAX(day)` of `gold_preopen_log`
- **Verdict · badge:** PUBLISH-CORE · `heuristic` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#gold_preopen_log](../docs/TERMINAL_DATA_DICTIONARY.md#gold_preopen_log)

<a id="gold_events"></a>
### `gold_events` · Gold: US calendar + compiled gold events

- **Pages:** GOLD · **Publisher:** ForexFactory / CME / compiled
- **Published (IST):** hourly 09:00–23:00 · **Expected stored by:** 23:30 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `gold_calendar_refresh` · **Freshness read from:** `MAX(first_seen_at)` of `gold_events`
- **Verdict · badge:** PUBLISH-CORE · `context` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#gold_events](../docs/TERMINAL_DATA_DICTIONARY.md#gold_events)

<a id="nse_fo_volt"></a>
### `nse_fo_volt` · NSE F&O daily volatility (FOVOLT, EWMA λ=0.995)

- **Pages:** DERV, OMON · **Publisher:** NSE (nsearchives.nseindia.com)
- **Published (IST):** ≈ 17:00 (measured 16:58 on 3 Nov, 17:01 on 4 Nov) · **Expected stored by:** 21:00 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `iv_eod` · **Freshness read from:** `MAX(date)` of `nse_fo_volt`
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [NSE_DATA_DICTIONARY.md#fovolt](../docs/NSE_DATA_DICTIONARY.md#fovolt)
- **Note:** the exchange's margin vol; a third RV line

<a id="nse_contract_delta"></a>
### `nse_contract_delta` · NSE contract delta factors

- **Pages:** OMON, DERV · **Publisher:** NSE (nsearchives.nseindia.com)
- **Published (IST):** ≈ 18:30–19:20 (measured 18:28 on 3 Nov, 19:18 on 4 Nov) · **Expected stored by:** 21:00 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `iv_eod` · **Freshness read from:** `MAX(date)` of `nse_contract_delta`
- **Verdict · badge:** PUBLISH-CONTEXT · `context` · **Dictionary:** [NSE_DATA_DICTIONARY.md#contract-delta](../docs/NSE_DATA_DICTIONARY.md#contract-delta)
- **Note:** NSE's own delta beside ours; |Δ_ours − Δ_nse| > 0.05 is logged

<a id="nse_combined_oi"></a>
### `nse_combined_oi` · NSE combined OI / delta-equivalent OI vs MWPL

- **Pages:** OMON, DERV · **Publisher:** NSE (nsearchives.nseindia.com)
- **Published (IST):** 19:23 (measured; deleq 19:18) · **Expected stored by:** 21:00 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `nse_positions_catchup` · **Freshness read from:** `MAX(date)` of `nse_combined_oi`
- **Verdict · badge:** PUBLISH-CONTEXT · `context` · **Dictionary:** [NSE_DATA_DICTIONARY.md#combined-oi](../docs/NSE_DATA_DICTIONARY.md#combined-oi)

<a id="nse_participant_vol"></a>
### `nse_participant_vol` · Participant-wise trading volume (contracts)

- **Pages:** MKT · **Publisher:** NSE (nsearchives.nseindia.com)
- **Published (IST):** 20:10 (measured) · **Expected stored by:** 21:00 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `nse_positions_catchup` · **Freshness read from:** `MAX(date)` of `nse_participant_vol`
- **Verdict · badge:** PUBLISH-CONTEXT · `context` · **Dictionary:** [NSE_DATA_DICTIONARY.md#participant-vol](../docs/NSE_DATA_DICTIONARY.md#participant-vol)

<a id="nse_fii_stats"></a>
### `nse_fii_stats` · FII derivative statistics

- **Pages:** MKT · **Publisher:** NSE (nsearchives.nseindia.com)
- **Published (IST):** 20:10 (measured) · **Expected stored by:** 21:00 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `nse_positions_catchup` · **Freshness read from:** `MAX(date)` of `nse_fii_stats`
- **Verdict · badge:** PUBLISH-CONTEXT · `context` · **Dictionary:** [NSE_DATA_DICTIONARY.md#fii-stats](../docs/NSE_DATA_DICTIONARY.md#fii-stats)

<a id="nse_mwpl_clients"></a>
### `nse_mwpl_clients` · Clients ≥ 3 % of MWPL (T−1)

- **Pages:** OMON, DERV · **Publisher:** NSE (nsearchives.nseindia.com)
- **Published (IST):** 18:20 for T−1 (measured) · **Expected stored by:** 21:00 IST on the trading day 1 after the session it describes · **Cadence:** daily · **Amber after:** 2 sessions, red beyond that
- **Ingest job:** `nse_positions_catchup` · **Freshness read from:** `MAX(date)` of `nse_mwpl_clients`
- **Verdict · badge:** PUBLISH-CONTEXT · `context` · **Dictionary:** [NSE_DATA_DICTIONARY.md#mwpl-cli](../docs/NSE_DATA_DICTIONARY.md#mwpl-cli)

<a id="index_ohlc_daily"></a>
### `index_ohlc_daily` · Every NSE index OHLC (ind_close_all)

- **Pages:** DERV, MKT, MEMB · **Publisher:** NSE (nsearchives.nseindia.com)
- **Published (IST):** read 19:15; re-written 23:20 (measured) · **Expected stored by:** 21:30 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `iv_eod` · **Freshness read from:** `MAX(date)` of `index_ohlc_daily`
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [NSE_DATA_DICTIONARY.md#ind-close-all](../docs/NSE_DATA_DICTIONARY.md#ind-close-all)
- **Note:** Parkinson / Yang-Zhang inputs; the index level L for the drivers

<a id="vix_daily"></a>
### `vix_daily` · India VIX OHLC

- **Pages:** DERV, OMON · **Publisher:** NSE (nsearchives.nseindia.com)
- **Published (IST):** daily file (re-written 23:20); vixhistory API for the backfill · **Expected stored by:** 21:30 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `iv_eod` · **Freshness read from:** `MAX(date)` of `vix_daily`
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [NSE_DATA_DICTIONARY.md#vix](../docs/NSE_DATA_DICTIONARY.md#vix)
- **Note:** one source for the VIX everywhere (PLAN 1.1 rules)

<a id="iv_surface_daily"></a>
### `iv_surface_daily` · IV surface per strike (Black-76 on the parity forward)

- **Pages:** OMON, DERV · **Publisher:** SuryaDhana (derived)
- **Published (IST):** from the F&O file (20:10) · **Expected stored by:** 21:30 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `iv_eod` · **Freshness read from:** `MAX(date)` of `iv_surface_daily`
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#iv_surface_daily](../docs/TERMINAL_DATA_DICTIONARY.md#iv_surface_daily)
- **Note:** scope: indices + watchlist (O-T4 default); model_version + r on every row; derived: the latest computation per key (re-runs replace the row with their computed_at / first_seen_at / model_version); a past vintage is recomputed from the archived source files versioned in ingest_log

<a id="iv_expiry_daily"></a>
### `iv_expiry_daily` · IV per expiry (ATM, 25Δ / 10Δ, skew, PCR, expected move)

- **Pages:** OMON, DERV, EVTS · **Publisher:** SuryaDhana (derived)
- **Published (IST):** from the F&O file (20:10) · **Expected stored by:** 21:30 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `iv_eod` · **Freshness read from:** `MAX(date)` of `iv_expiry_daily`
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#iv_expiry_daily](../docs/TERMINAL_DATA_DICTIONARY.md#iv_expiry_daily)
- **Note:** derived: the latest computation per key (re-runs replace the row with their computed_at / first_seen_at / model_version); a past vintage is recomputed from the archived source files versioned in ingest_log

<a id="iv_summary_daily"></a>
### `iv_summary_daily` · IV summary per underlying (iv30/60/90 cm, rank AND percentile, RV cc / Parkinson / YZ, FOVOLT)

- **Pages:** OMON, DERV, DES, EVTS · **Publisher:** SuryaDhana (derived)
- **Published (IST):** from the F&O file (20:10) · **Expected stored by:** 21:30 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `iv_eod` · **Freshness read from:** `MAX(date)` of `iv_summary_daily`
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#iv_summary_daily](../docs/TERMINAL_DATA_DICTIONARY.md#iv_summary_daily)
- **Note:** IV − RV is context, never coloured; rank and percentile both labelled by definition; derived: the latest computation per key (re-runs replace the row with their computed_at / first_seen_at / model_version); a past vintage is recomputed from the archived source files versioned in ingest_log

<a id="iv_event_log"></a>
### `iv_event_log` · Results IV-crush ledger

- **Pages:** EVTS, DES · **Publisher:** SuryaDhana (derived)
- **Published (IST):** from nse_results + iv_expiry_daily · **Expected stored by:** 21:30 IST · **Cadence:** daily · **Amber after:** 3 sessions, red beyond that
- **Ingest job:** `iv_eod` · **Freshness read from:** `MAX(first_seen_at)` of `iv_event_log`
- **Verdict · badge:** PUBLISH-CONTEXT · `context` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#iv_event_log](../docs/TERMINAL_DATA_DICTIONARY.md#iv_event_log)
- **Note:** describes past events, does not forecast the next; derived: the latest computation per key (re-runs replace the row with their computed_at / first_seen_at / model_version); a past vintage is recomputed from the archived source files versioned in ingest_log

<a id="iv_intraday"></a>
### `iv_intraday` · Intraday OI / IV tape (Breeze chain: NIFTY, BANKNIFTY, FINNIFTY + watch names)

- **Pages:** OMON, DERV · **Publisher:** ICICI Breeze (chain quotes)
- **Published (IST):** 09:15–15:30, near expiry every 2 min when the budget allows (tiers planned to the ledger) · **Expected stored by:** 15:45 IST · **Cadence:** session · **Amber after:** 1 sessions, red beyond that · **unrecoverable** (a missed capture is a gap row, never backfilled)
- **Ingest job:** `iv_intraday` · **Freshness read from:** `MAX(ts)` of `iv_intraday`
- **Verdict · badge:** PUBLISH-CONTEXT · `context` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#iv_intraday](../docs/TERMINAL_DATA_DICTIONARY.md#iv_intraday)
- **Note:** through the Breeze budget ledger only; skipped without a live session; ICICI codes (BANKNIFTY = CNXBAN)

<a id="archive:chain"></a>
### `archive:chain` · Raw chain snapshots (parquet parts)

- **Pages:** OMON, DERV · **Publisher:** ICICI Breeze
- **Published (IST):** 09:15–15:30, every tape tick · **Expected stored by:** 15:45 IST · **Cadence:** session · **Amber after:** 1 sessions, red beyond that · **unrecoverable** (a missed capture is a gap row, never backfilled)
- **Ingest job:** `iv_intraday` · **Freshness read from:** dated files under `data/nse_archive/../ticks/chain/`
- **Verdict · badge:** PUBLISH-CONTEXT · `context` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#archive:chain](../docs/TERMINAL_DATA_DICTIONARY.md#archive:chain)

<a id="iv_expiry_replay"></a>
### `iv_expiry_replay` · Expiry-day straddle replays (Breeze 1-minute bars of past expiries)

- **Pages:** DERV · **Publisher:** ICICI Breeze (historical v2)
- **Published (IST):** after the close, on demand (O-T16) · **Expected stored by:** no deadline · **Cadence:** manual · **Amber after:** 400 days, red beyond that
- **Ingest job:** none (read on request) · **Freshness read from:** `MAX(ts)` of `iv_expiry_replay`
- **Verdict · badge:** PUBLISH-CONTEXT · `context` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#iv_expiry_replay](../docs/TERMINAL_DATA_DICTIONARY.md#iv_expiry_replay)
- **Note:** POST /jobs/expiry-replay (the PM, after the close); 2 metered calls per expiry; XPRY's historical curve

<a id="rate_curve"></a>
### `rate_curve` · Risk-free rate (dated constant; O-T5)

- **Pages:** OMON, OSTR · **Publisher:** SuryaDhana (derived)
- **Published (IST):** dated constant 6.5 % · **Expected stored by:** no deadline · **Cadence:** static · **Amber after:** 400 days, red beyond that
- **Ingest job:** `iv_eod` · **Freshness read from:** `MAX(date)` of `rate_curve`
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#rate_curve](../docs/TERMINAL_DATA_DICTIONARY.md#rate_curve)
- **Note:** recorded as r on every IV row; a change never rewrites history

<a id="index_constituents_daily"></a>
### `index_constituents_daily` · Index constituents (NIFTY 50, NIFTY BANK), archived daily

- **Pages:** MEMB, MOV · **Publisher:** niftyindices.com
- **Published (IST):** on reconstitution · **Expected stored by:** 20:00 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `index_drivers_daily` · **Freshness read from:** `MAX(date)` of `index_constituents_daily`
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [NSE_DATA_DICTIONARY.md#constituents](../docs/NSE_DATA_DICTIONARY.md#constituents)
- **Note:** display-only posture (O-T11); members as of today applied before the first archived list

<a id="index_weights_daily"></a>
### `index_weights_daily` · Index weights: official top-10 (NSE file) + rebuilt + calibrated

- **Pages:** MEMB · **Publisher:** NSE (nsearchives.nseindia.com) + SuryaDhana (derived)
- **Published (IST):** top-10 file 16:30 (measured 4 Nov) · **Expected stored by:** 20:45 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `index_drivers_daily` · **Freshness read from:** `MAX(date)` of `index_weights_daily`
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [NSE_DATA_DICTIONARY.md#top10](../docs/NSE_DATA_DICTIONARY.md#top10)
- **Note:** calibration equals the official top-10 to 0.01 pp on the day the file exists; derived: the latest computation per key (re-runs replace the row with their computed_at / first_seen_at / model_version); a past vintage is recomputed from the archived source files versioned in ingest_log

<a id="index_contribution_daily"></a>
### `index_contribution_daily` · Index points per member per day (additive attribution)

- **Pages:** MEMB, DESK · **Publisher:** SuryaDhana (derived)
- **Published (IST):** 19:25 job · **Expected stored by:** 20:45 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `index_drivers_daily` · **Freshness read from:** `MAX(date)` of `index_contribution_daily`
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#index_contribution_daily](../docs/TERMINAL_DATA_DICTIONARY.md#index_contribution_daily)
- **Note:** an identity with its residual shown; derived: the latest computation per key (re-runs replace the row with their computed_at / first_seen_at / model_version); a past vintage is recomputed from the archived source files versioned in ingest_log

<a id="index_contribution_fit"></a>
### `index_contribution_fit` · Attribution fit (actual vs explained points, residual)

- **Pages:** MEMB · **Publisher:** SuryaDhana (derived)
- **Published (IST):** 19:25 job · **Expected stored by:** 20:45 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `index_drivers_daily` · **Freshness read from:** `MAX(date)` of `index_contribution_fit`
- **Verdict · badge:** PUBLISH-CORE · `arithmetic` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#index_contribution_fit](../docs/TERMINAL_DATA_DICTIONARY.md#index_contribution_fit)
- **Note:** derived: the latest computation per key (re-runs replace the row with their computed_at / first_seen_at / model_version); a past vintage is recomputed from the archived source files versioned in ingest_log

<a id="index_driver_state"></a>
### `index_driver_state` · Driver regime (leader with hysteresis, concentration, breadth)

- **Pages:** MEMB, BRF · **Publisher:** SuryaDhana (derived)
- **Published (IST):** 19:25 job · **Expected stored by:** 20:45 IST · **Cadence:** daily · **Amber after:** 1 sessions, red beyond that
- **Ingest job:** `index_drivers_daily` · **Freshness read from:** `MAX(date)` of `index_driver_state`
- **Verdict · badge:** PUBLISH-CONTEXT · `context` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#index_driver_state](../docs/TERMINAL_DATA_DICTIONARY.md#index_driver_state)
- **Note:** describes, does not predict; no colour on the leader; derived: the latest computation per key (re-runs replace the row with their computed_at / first_seen_at / model_version); a past vintage is recomputed from the archived source files versioned in ingest_log

<a id="ingest_log"></a>
### `ingest_log` · Ingest log (url, Last-Modified, sha256, revisions)

- **Pages:** SYS · **Publisher:** SuryaDhana (derived)
- **Published (IST):** every fetch · **Expected stored by:** no deadline · **Cadence:** derived · **Amber after:** 1 days, red beyond that
- **Ingest job:** `data_health_refresh` · **Freshness read from:** `MAX(fetched_at)` of `ingest_log`
- **Verdict · badge:** PUBLISH-CONTEXT · `context` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#ingest_log](../docs/TERMINAL_DATA_DICTIONARY.md#ingest_log)

<a id="data_gaps"></a>
### `data_gaps` · Explicit gap rows for lost session captures

- **Pages:** SYS, MOV, WRAP, BRF · **Publisher:** SuryaDhana (derived)
- **Published (IST):** 08:35 sweep / start-up catch-up · **Expected stored by:** no deadline · **Cadence:** derived · **Amber after:** 1 days, red beyond that
- **Ingest job:** `data_health_refresh` · **Freshness read from:** `MAX(first_seen_at)` of `data_gaps`
- **Verdict · badge:** PUBLISH-CONTEXT · `context` · **Dictionary:** [TERMINAL_DATA_DICTIONARY.md#data_gaps](../docs/TERMINAL_DATA_DICTIONARY.md#data_gaps)

## Metric registries (per-series catalogs that gate rendering)

### IV series (`fo_iv/catalog_seed.py`, served as `/db/fo-iv/catalog`)

Registry present (29 rows). A panel renders a metric only if it has a row here with a PUBLISH verdict (no row, no panel).
`context` 13 · `arithmetic` 16 · `heuristic` 0 · `signal` 0.

| series | name | table.column | badge | definition | precedent | unit |
|---|---|---|---|---|---|---|
| `EVENT_CRUSH` | Results IV crush | `iv_event_log.crush_pct` | `context` | near-expiry ATM IV after the release ÷ before − 1 | ORATS / Market Chameleon earnings | % |
| `EVENT_IMPLIED_VS_REALISED` | Implied vs realised event move | `iv_event_log.implied_move_pct` | `context` | term-split implied event σ (else ATM IV / √252) beside the realised pre→post move | ORATS earnings | % |
| `EXPECTED_MOVE_1D` | 1-day expected move | `iv_summary_daily.expected_move_1d_pct` | `arithmetic` | IV30_CM / √252 | Bloomberg OSA expected move; thinkorswim MMM | % |
| `EXPIRY_ATM_IV` | ATM IV per expiry | `iv_expiry_daily.atm_iv` | `arithmetic` | IV interpolated at the parity forward, per expiry | Bloomberg OVDV | vol pt |
| `EXPIRY_EXPECTED_MOVE` | Expected move to expiry | `iv_expiry_daily.expected_move_pct` | `arithmetic` | ATM IV × √T (1σ) | Bloomberg OSA | % |
| `EXPIRY_PCR` | Put/call OI ratio per expiry | `iv_expiry_daily.pcr` | `context` | put OI ÷ call OI (contracts) on the expiry | Sensibull PCR | vol pt |
| `EXPIRY_SKEW_25D` | 25Δ skew per expiry | `iv_expiry_daily.skew_25d` | `context` | 25Δ put IV − 25Δ call IV, each by inverting that strike's own delta | ORATS skew | vol pt |
| `FOVOLT_ANN` | NSE FOVOLT annualised vol | `iv_summary_daily.fovolt_ann` | `context` | NSE's EWMA (λ 0.995) daily vol × √365: the exchange's margin vol | NSE F&O daily volatility file | vol pt |
| `INTRADAY_ATM_IV` | Intraday ATM IV (15-min pilot) | `iv_intraday.iv` | `context` | Black-76 IV from the bid/ask mid on the Breeze chain, every 15 min | Quantsapp IV live; Bloomberg OMON intraday | vol pt |
| `IV30_CM` | 30-day constant-maturity ATM IV | `iv_summary_daily.iv30_cm` | `arithmetic` | ATM variance interpolated between the two expiries bracketing 30 calendar days (VIX-style), annualised; with no bracket, the ATM IV of the one expiry nearest 30 d inside 10–60 d (flat term, flag cm30_flat) | Bloomberg HIVG / IVOL; Cboe VIX method | vol pt |
| `IV60_CM` | 60-day constant-maturity ATM IV | `iv_summary_daily.iv60_cm` | `arithmetic` | as IV30_CM at 60 days | Bloomberg OVDV term tab | vol pt |
| `IV90_CM` | 90-day constant-maturity ATM IV | `iv_summary_daily.iv90_cm` | `arithmetic` | as IV30_CM at 90 days | Bloomberg OVDV term tab | vol pt |
| `IV_MINUS_RV20` | IV30 − RV20 close-to-close (volatility risk premium) | `iv_summary_daily.iv_minus_rv20` | `context` | IV30_CM minus RV20_CC | Market Chameleon IV30 vs HV; Bloomberg VCA | vol pt |
| `IV_PCTILE_252` | IV percentile (252 sessions) | `iv_summary_daily.iv_pctile_252` | `arithmetic` | share of the past 252 sessions whose IV30_CM was below today's | Bloomberg IVOL %ile; thinkorswim IV percentile | % |
| `IV_RANK_252` | IV rank (252 sessions) | `iv_summary_daily.iv_rank_252` | `arithmetic` | where today's IV30_CM sits between the 252-session minimum and maximum, 0–100 | Bloomberg IVOL rank; tastytrade IVR | % |
| `MONTHLY_ATM_IV` | ~1-month ATM IV (first expiry 20–60 d) | `iv_summary_daily.monthly_atm_iv` | `arithmetic` | ATM IV of the first expiry 20–60 days out (a weekly when one falls in the window; not NSE's monthly series) | Bloomberg OVDV; India VIX (variance strip) sits ≈ 1 pt above it | vol pt |
| `MWPL_FUT_EQUIV_OI` | Futures-equivalent OI (delta-equivalent) | `nse_combined_oi.fut_equiv_oi` | `context` | NSE's portfolio-wise futures-equivalent OI | NSE combineoi_deleq file | shares |
| `NEAR_ATM_IV` | Near-expiry ATM IV (dte > 2) | `iv_summary_daily.near_atm_iv` | `arithmetic` | ATM IV of the first expiry more than 2 days out; a saw-tooth by construction (R-IV §3) | Sensibull / Opstra IV chart | vol pt |
| `NSE_DELTA_FACTOR` | NSE delta factor | `nse_contract_delta.delta_factor` | `context` | NSE Clearing's delta per contract (margins) | NSE Contract_Delta file | vol pt |
| `PAID_VS_DELIVERED` | IV paid vs vol delivered (monthly expiries) | `iv_expiry_daily.atm_iv` | `context` | ATM IV of each NSE monthly expiry at ≈ 30 DTE minus the close-to-close realised vol (zero-mean) over that option's own life, entry close → expiry close | ORATS implied vs realised; Bloomberg VCA | vol pt |
| `RATE_R` | Risk-free rate used | `rate_curve.rate` | `arithmetic` | dated constant 6.5 % (O-T5) recorded as r on every row | — | % |
| `RV20_CC` | Realised vol 20 d (close-to-close) | `iv_summary_daily.rv20_cc` | `arithmetic` | σ of 20 daily log returns × √252 | Bloomberg HVG | vol pt |
| `RV20_PARKINSON` | Realised vol 20 d (Parkinson) | `iv_summary_daily.rv20_parkinson` | `arithmetic` | √(mean ln(H/L)² / 4 ln 2) × √252 | Bloomberg HVG (Parkinson) | vol pt |
| `RV20_YZ` | Realised vol 20 d (Yang-Zhang) | `iv_summary_daily.rv20_yz` | `arithmetic` | overnight + k·open-close + (1−k)·Rogers-Satchell variance × 252 | Bloomberg HVG (Yang-Zhang); IBKR Volatility Lab | vol pt |
| `SKEW_25D_30` | 25Δ skew at 30 days | `iv_summary_daily.skew_25d_30` | `context` | 25Δ put IV minus 25Δ call IV, interpolated to 30 days | Bloomberg SKEW; Cboe SKEW; ORATS skew | vol pt |
| `SURFACE_DELTA` | Delta per strike | `iv_surface_daily.delta` | `arithmetic` | Black-76 delta (discounted) at the strike's own IV | Bloomberg OMON | vol pt |
| `SURFACE_IV` | IV per strike | `iv_surface_daily.iv` | `arithmetic` | Black-76 IV on the parity forward; traded strikes only | Bloomberg OMON / OVDV smile | vol pt |
| `TERM_SLOPE_30_90` | Term slope 30 → 90 | `iv_summary_daily.term_slope_30_90` | `context` | IV90_CM minus IV30_CM | Bloomberg OVDV term; Opstra term structure | vol pt |
| `VIX_CLOSE` | India VIX | `vix_daily.close` | `context` | NSE's India VIX close (OHLC stored) | NSE India VIX | vol pt |

### Index-driver series (`index_drivers/catalog_seed.py`, served as `/db/index-drivers/catalog`)

Registry present (9 rows). A panel renders a metric only if it has a row here with a PUBLISH verdict (no row, no panel).
`context` 3 · `arithmetic` 6 · `heuristic` 0 · `signal` 0.

| series | name | table.column | badge | definition | precedent | unit |
|---|---|---|---|---|---|---|
| `BREADTH_EW_MINUS_CW` | Breadth: equal-weight minus cap-weight | `index_driver_state.ew_minus_cw_pp` | `context` | EW member return − index return over the window; narrow < −1 pp, broad > +1 pp (thresholded words, no colour) | — | pp |
| `DRIVER_LEADER` | Driver leader (hysteresis) | `index_driver_state.leader` | `context` | largest \|rolling points\| name; a challenger replaces it only after 5 consecutive sessions ≥ 1.3× (20 s) / 1.2× (60 s) | — | symbol |
| `EFFECTIVE_N` | Effective number of names | `index_driver_state.effective_n` | `arithmetic` | 1 ÷ Σ weight² | — | names |
| `FIT_RESIDUAL` | Attribution residual | `index_contribution_fit.residual_points` | `arithmetic` | actual index move − Σ member points | — | index points |
| `MEMBER_POINTS` | Points per member | `index_contribution_daily.points` | `arithmetic` | L_{d−1} × w_i,d × r_i,d, additive across days (any horizon is a slice) | Bloomberg MEMB / IMAP | index points |
| `MEMBER_WEIGHT` | Weight (rebuilt, calibrated) | `index_weights_daily.weight_pct` | `arithmetic` | shares (XBRL, filed_at ≤ d) × prev close × (1 − promoter %), calibrated to NSE's top-10 file | NSE top-10 weights file | % |
| `MONTHLY_LEADER` | Monthly leader | `index_contribution_daily.points` | `context` | largest \|Σ points\| in the calendar month | — | symbol |
| `SECTOR_POINTS` | Sector contribution | `index_contribution_daily.points` | `arithmetic` | Σ member points by NSE industry | Bloomberg IMAP | index points |
| `TOP5_SHARE` | Top-5 share of \|points\| | `index_driver_state.top5_share` | `arithmetic` | Σ of the five largest \|points\| ÷ Σ\|points\| over the window | — | share |

## Index by id

[`alpha_shadow`](#alpha_shadow) · [`archive:chain`](#archive:chain) · [`archive:internals`](#archive:internals) · [`archive:preopen`](#archive:preopen) · [`breeze_security_master`](#breeze_security_master) · [`breeze_session`](#breeze_session) · [`data_gaps`](#data_gaps) · [`db_backup`](#db_backup) · [`desk_mark`](#desk_mark) · [`gold_asia_daily`](#gold_asia_daily) · [`gold_brief_docs`](#gold_brief_docs) · [`gold_cme_daily_voi`](#gold_cme_daily_voi) · [`gold_cot`](#gold_cot) · [`gold_curve_mcx`](#gold_curve_mcx) · [`gold_daily_bars`](#gold_daily_bars) · [`gold_etf_holdings`](#gold_etf_holdings) · [`gold_events`](#gold_events) · [`gold_fed_path`](#gold_fed_path) · [`gold_fred_daily`](#gold_fred_daily) · [`gold_health_daily`](#gold_health_daily) · [`gold_india_ibja`](#gold_india_ibja) · [`gold_preopen_log`](#gold_preopen_log) · [`gold_treasury`](#gold_treasury) · [`index_constituents_daily`](#index_constituents_daily) · [`index_contribution_daily`](#index_contribution_daily) · [`index_contribution_fit`](#index_contribution_fit) · [`index_driver_state`](#index_driver_state) · [`index_ohlc_daily`](#index_ohlc_daily) · [`index_valuation_history`](#index_valuation_history) · [`index_weights_daily`](#index_weights_daily) · [`ingest_log`](#ingest_log) · [`iv_event_log`](#iv_event_log) · [`iv_expiry_daily`](#iv_expiry_daily) · [`iv_expiry_replay`](#iv_expiry_replay) · [`iv_intraday`](#iv_intraday) · [`iv_summary_daily`](#iv_summary_daily) · [`iv_surface_daily`](#iv_surface_daily) · [`market_index_daily`](#market_index_daily) · [`market_monitor`](#market_monitor) · [`ml_features`](#ml_features) · [`news_scanner`](#news_scanner) · [`news_track_record`](#news_track_record) · [`nse_bhavcopy`](#nse_bhavcopy) · [`nse_combined_oi`](#nse_combined_oi) · [`nse_contract_delta`](#nse_contract_delta) · [`nse_deals`](#nse_deals) · [`nse_events`](#nse_events) · [`nse_fii_dii_cash`](#nse_fii_dii_cash) · [`nse_fii_stats`](#nse_fii_stats) · [`nse_fo_daily`](#nse_fo_daily) · [`nse_fo_volt`](#nse_fo_volt) · [`nse_insider_trades`](#nse_insider_trades) · [`nse_live`](#nse_live) · [`nse_mtf`](#nse_mtf) · [`nse_mwpl_clients`](#nse_mwpl_clients) · [`nse_participant_oi`](#nse_participant_oi) · [`nse_participant_vol`](#nse_participant_vol) · [`nse_results`](#nse_results) · [`nse_shareholding`](#nse_shareholding) · [`ohlcv`](#ohlcv) · [`option_chain_eod`](#option_chain_eod) · [`option_chain_live`](#option_chain_live) · [`option_history_json`](#option_history_json) · [`rate_curve`](#rate_curve) · [`surveillance`](#surveillance) · [`tick_store`](#tick_store) · [`vix_daily`](#vix_daily)
