# Terminal FINAL — seed backlog (13 Nov 2026, PM-seeded; wave-0 miner enriches, dedupes, re-ranks)

Rank = money-impact for an index-options day trader. Status: OPEN unless noted. Sources: RATING.md §"what a 9 looks
like" (4 Nov), RATING_20261105.md, page_review synth/05_issues.md, IMPROVEMENT_LOG, owner verbatims 13 Nov.

## P0 — before Monday's open
- F-01 (W1) Watchdog cold-boot order: ui-api started before data-service after reboot → READ-ONLY DuckDB (hit 13 Nov).
- F-02 (W1) Raw "data-service unreachable" on app open → calm boot/catch-up screen with auto-retry + status.
- F-03 (W3) Options charts static SVG: no zoom/pan/crosshair (owner verbatim). IV history/cone, OI tape, IV live path,
  payoff, CHRT overlays, gold charts.
- F-04 (W5) Risk cockpit v1: daily loss cap vs paper book, trade counter, stand-down banner, scenario strip.
- F-05 (W2) OMON: chain above the fold, Greeks columns, strike→OSTR leg handoff, IV percentile labelled correctly.
- F-06 (W6) SourceChip (LIVE/age/STALE/OFFLINE) on every F&O panel; header DATA chip already exists — verify coverage.

## P1 — this weekend
- F-07 (W2) OSTR: real margin via Breeze/SPAN displayed with source badge; multi-expiry strategies; cost-aware breakevens.
- F-08 (W2) XPRY polish: max-pain drift, straddle tracker, intraday PCR (context badges).
- F-09 (W4) Refined-dark token pass + component consistency sweep + strip reorder to the trader's day.
- F-10 (W4) Phone compact: BRF/WTCH/ALRT/MOV/OMON-summary at 390px (no horizontal scroll).
- F-11 (W7) Morning Game Plan page + 08:50 Telegram digest (context-badged, no directions).
- F-12 (W7) Trade journal v1 on paper book: context capture at entry/exit, weekly debrief page.
- F-13 (W2) Keyboard-first: ? help overlay, GO args everywhere, j/k strike navigation.
- F-14 (W1) Catch-up gaps: FII/DII missing days (28 Oct, 2–3 Nov), COT Sat-retry budget fix, IBJA parser fix.
- F-15 (W6) Wrong-LIVE windows: verify b67fb56 behaviour live (deployed 13 Nov restart); heatmap stamps.

## P2 — next week, keep iterating
- F-16 (W7) Options flow radar (30-min OI delta, vol/OI, IV pump; `context`).
- F-17 (W7) Expiry replay simulator (practice mode on stored tapes).
- F-18 (W2) Per-stock IV depth: term, skew, crush ledger surfaced pre-event.
- F-19 (W4) Saved layouts / Launchpad; What-changed diff on BRF.
- F-20 (W1) Keychain `_prev` cleanup; restore-drill run + note; UPS reminder to owner.
- F-21 (RSCH) alpha_lab verdicts into RSCH catalog; BTST cost floor 93 bps.
- F-22 (ARCH) read concurrency burst target ≈ max-single; cold ML tables out of hot file.

## Known-good to PRESERVE (regression gates)
Honesty engineering (badges, dated numbers, FAIL banners), 43/43 page audits both engines, p95 < 250 ms, PAPER-only
enforcement, gold program behaviours, GO bar, atomic UI releases + rollback, watchdog hang detection, dead-man ping.

## R2 follow-ups (13 Nov night)
- F-23 (W1) data/job_queue.sqlite + data/ask_audit.sqlite into db_backup FAMILIES (builder-flagged).
- F-24 (W1) R2-QUEUE test_error_is_persisted timing flake under parallel load (1-in-10; de-flake).
- F-25 (RSCH) ASK: wire a local Ollama model + the nightly eval run; MINOR-1 detector is pattern-based — the describe-only prompt stays the real fence.

## F2 polish queue (13 Nov 23:50 — next round)
- F-26 (W4) ellipsis-truncated cells get hover/tap tooltips (news headlines, sector names; shared kit).
- F-27 (W6) wire catalogVerdictOf into Panel chips for catalogued-dataset panels (risk critic F1+F2 named fix).
- F-28 (W2) OMON 8.25px SVG axis tick; volume/OI unit chips; expiry scorecard bogus 329-day row.
- F-29 (W7) ASK: example questions + recent-audit list in the empty state; louder snapshot-age when stale; F-25 eval run on qwen3.5:9b.
- F-30 (W4) GOLD gauge-delta sub clipping; WTCH one-time settings-import prompt; LAYOUT SAVE toast.
- F-31 (W1) /jobs/recent retention bump; NIFTY BANK drivers recalibration; off-machine DB copy (owner disk).

## Commodities 9-bar: the MCX-options question, answered (14 Nov 08:10)

The rating's last Commodities item — "MCX gold/silver/crude option chains with IV (after the Breeze MCX probe)"
— carried "pending a live session" for three reports. Half of it is answerable offline, from the installed SDK:

- **There is NO one-call MCX option chain.** `breeze_connect`'s `get_option_chain_quotes` refuses every exchange
  but NFO and BFO (its own guard: `exchange_code.lower() not in ["nfo", "bfo"]` -> validation error). That is a
  vendor restriction, not a session or permission problem, so the NSE-style chain call can never serve MCX.
- **The per-contract paths DO allow MCX with options**: `EXCHANGE_CODES_HIST_V2` and `FNO_EXCHANGE_TYPES` both
  list `mcx`, and `PRODUCT_TYPES*` list `options`. A chain is therefore assemblable STRIKE BY STRIKE — one call
  per (strike, right).
- **The cost is what decides whether to build it**: a +/-N-strike window is 2N+2 calls per contract per snapshot
  against the shared 4,000/day Breeze ledger. +/-10 strikes = 42 calls: fine once or twice a day per contract,
  impossible as a live tape. IV would be computed locally (Black-76 on the futures price, as the NSE path does).
- `scripts/probe_mcx_options.py` answers the rest in ONE command on the next trading day: read-only, every call
  through the ledger, 10 calls by default, refuses to run without a live session, and writes the payload shape
  plus a verdict on whether price and open interest are present to compute IV from.

**F-31b**: run the probe Monday, then the owner decides scope — build the per-strike chain at that budget cost,
or accept Commodities without MCX options (which caps that area below 9 on free data, by scope, not by defect).

