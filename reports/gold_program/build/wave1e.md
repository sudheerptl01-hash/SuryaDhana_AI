# Gold wave 1e — results and checks (6 Nov 2026, wf_a1abd08f-881)

# G2-API — ACCEPT-WITH-NOTES

All four majors (M-A to M-D) are fixed on the API side, plus the server-side M-E minors. Every rule has tests with negative controls: 21 in services/ui-api/tests/test_gold_wave1e.py and 7 in tests/gold/test_wave1e_fixes.py.

Results:
- services/ui-api/tests: 1563 passed, 1 failed. The failure is test_terminal_v2_contract (derivatives.py, the V-VOL workflow), not gold.
- tests/gold + tests/gold_replay: 234 passed. scripts/tests: 521 passed.
- core: 1417 passed, 1 failed. tests/integration/test_desktop_qa_harness's regex still expects the old getGoldHealth signature, which G2-UI changed (patch request 3).
- gold.check (367), gold_views.check, pages.check (293), desktop.check (457), tsc, validate_learn, ruff and mypy: all clean.

Live stack: one GET to :8001 /db/gold/series. On the real 6 Nov data it confirms the fixes: the 4 Nov Shanghai pair recomputes to −2.01 from the printed legs (stored +1.50), and the twin rule picks UST_REAL_10Y over FRED_DFII10 (last 3 Nov). No Breeze, Yahoo, POST, restart, data/ write or git.

M-A India basis. /api/gold/health now takes contract and expiry. With a contract during MCX hours it reads the quote once and folds it in with the same function /overview uses (gold.fold_live_quote). So /health?contract=X&expiry=Y equals /overview?contract=X&expiry=Y.health, and the strip, gauge and H4 values are equal. The default /health (no contract) is what WEI and BRF poll; it makes no broker call and folds only a quote already in the cache. Breeze's zone-less times are now read as IST (gold._iso_ist), and a time ahead of the read is dropped, so mcx_live_as_of no longer shows 14:46 for the 09:16 bar.

Field names agreed for G2-UI (it renders overview.health):
- health.live_quote {mcx_live, source, as_of, is_open, applied}.
- india_basis gauge: clock_label, printed verbatim ('LIVE · GOLDTEN NOV-26 · 09:16 IST' or 'SETTLEMENT · VWAP30 PROXY · Thu 05 Nov'), plus mcx_live_as_of and basis_contract.
- H4 clause: clock, clock_label, basis_contract. Text is 'India basis +0.9 % vs duty-paid landed 999 (live) on GOLDTEN NOV-26'.

M-B Real yield. A new gold.pick_twin is MACRO's fresher-twin rule, and MACRO, the HEALTH real_yield tile, the H2 clause and the strip all use it. One value and one date per page.
- Tile: series_id, primary_series_id, label_note, instrument.
- H2 clause: dated ('real yield −3 bp (to Thu 5 Nov)'), with real_yield_series_id, real_yield_value, real_yield_date and real_yield_change_bp.
- Strip: real_10y and real_10y_date come from the tile, plus real_10y_series_id and real_10y_source.
- The 2-y only appears on MACRO, so it has no split to fix.

M-C Shanghai premium. gold.shanghai_pairs recomputes every pair from the printed legs: SGE CNY/g × 31.1035 ÷ USDCNY (latest vintage on or before the SGE date) − LBMA PM of the same date. The stored derive is used only where a leg is missing.
- /premiums.shanghai adds premium_usd_stored, premium_source, reconciles, recompute_note and usdcny_as_of. history[] gains source and stored_usd.
- The HEALTH shanghai tile is built on the same pairs, so it prints the same number.
- data-service: derive.derive_shanghai now re-derives right after the 03:10 yahoo_daily group whenever CNY=X was fetched.

M-D Muhurat. The times (14:20–15:30, pre-open 14:05–14:19, MCX/TRD/590/2026) come from the repo's own sources: the TeamLease republication cited in GOLD_DATA_DICTIONARY F6, ingest_local.py and the 6 Nov brief.
- shared/mcx_specs: SPECIAL_SESSIONS_2026 rows gain opens, closes, pre_open and circular. trading_window returns the Sunday window; is_session_day and special_session_on are new; session_state adds special.
- ui-api: previous_session (Mon 9 → Sun 8), band_session, latest_completed_session (Mon 9 08:45 → Sun 8), session_close_at (15:30, so the VWAP30 window is 15:00–15:30), the sessions_between OI span and the mcx_quote after-open rule all count the session.
- data-service: previous_mcx_session, mcx_close.run (the Mon–Fri 23:58 run also stores a special session from the last 4 days, so Monday night stores Sunday) and reads.sessions_between all count it too.
- mcx_day gains special and a note naming the circular. The 08:45 snapshot refuses a special-session day without force.
- The /fair baseline gains expected_session, older_than_expected and older_note. The log row gains baseline_expected_session, baseline_older_than_expected and baseline_note.
- Tested: Mon 9 08:45 uses Sunday's VWAP; with no Sunday VWAP it falls back to Friday and is flagged 'baseline session older than expected … Sun 08 Nov (Muhurat …)'.

M-E minors:
- /bars: an open or close outside the high–low range is withheld (o null, o_raw, ohlc_note), and each bar carries the store's partial flag. daily_closes use the store flag first.
- roll.days_in_tender added.
- premiums.india adds the contract's settlement_source, quality and session.
- MACRO: Brent shown as 'Brent front future (BZ=F)' with instrument, source_label and same_level=false.
- ZQ is labelled 'likely DEC-26 (ZQ=F rolled)' when it does not fit EFFR, with rolled_suspect and a note. Fed meetings add mean_rate_pct.
- Calendar: the Muhurat row is timed at 14:20; untimed rows get a timing_label.
- /fair.freshness turns 'delayed' past 5 minutes, with delay_min and chip.
- settlement_check now tests the band against its own session's VWAP (band_check, same_session). The cross-session gap is served as session_move_pct / session_move_label instead.

API_CONTRACT §7d is written and §8 regenerated.

## resolved
- [fixed] M-A India basis: HEALTH ignored the picked contract and the live MCX clock (gauge/verdict GOLD settlement vs strip picked contract live): gold.py: /health takes contract/expiry (memo per contract, expiry, window); build_contract_health + fold_live_quote shared with /overview (live fold only when mcx_is_open; a quote read only for an explicit contract pick, the polled default echo folds only a cached quote); india_basis gauge adds clock_label ('LIVE · GOLDTEN NOV-26 · 09:16 IST' / 'SETTLEMENT · VWAP30 PROXY · Thu 05 Nov' / BAND PROXY / STORED) and mcx_live_as_of; apply_live_mcx updates clock_label; H4 clause adds clock_label + basis_contract and names the contract ('… (live) on GOLDTEN NOV-26'); health.live_quote {mcx_live, source, as_of, is_open, applied}; _iso_ist reads Breeze wall time as IST (fair block, strip, gauge) and a stamp ahead of the read is dropped
- [fixed] M-B Real yield: HEALTH tile, H2 clause and strip used FRED_DFII10 (2 sessions stale) while MACRO used UST_REAL_10Y with the opposite weekly sign: gold.py: pick_twin (MACRO's fresher-twin rule, the only one) used by build_macro, the HEALTH real_yield tile (twin=True; series_id = series shown, primary_series_id, label_note, instrument), the H2 clause (series_id/real_yield_series_id, real_yield_value, real_yield_date, real_yield_change_bp; text dated '(to Thu 5 Nov)') and the strip (real_10y/real_10y_date from the tile + real_10y_series_id, real_10y_source). The 2-y appears only on MACRO (no split).
- [fixed] M-C Shanghai premium did not reproduce from its printed legs (SGE $4,035.8 − LBMA $4,037.8 = −$2.0 vs printed +$1.50): gold.py: shanghai_pairs recomputes every same-date pair from the printed legs (latest USDCNY vintage on/before the SGE date), stored derive only where a leg is missing; /premiums.shanghai adds premium_usd_stored, premium_source, reconciles, recompute_note, usdcny_as_of; history[] adds source/stored_usd; the HEALTH shanghai tile uses the same pairs (+premium_source, sge_usd_oz, london_pm_usd, usdcny, usdcny_date, premium_usd_stored). data-service: derive._shanghai_frames + derive_shanghai; jobs.g_yahoo_daily re-derives the pair when CNY=X was fetched (shanghai_rederive in the result).
- [fixed] M-D Muhurat Sun 8 Nov 2026 (14:20–15:30, MCX/TRD/590/2026) missing from the MCX session calendar; Mon 9 Nov 08:45 baseline would skip it: shared/mcx_specs: SPECIAL_SESSIONS_2026 rows add opens/closes/pre_open/circular (literal "date" keys kept for desktop.check), SPECIAL_SESSION_WINDOWS, special_session_on, is_session_day, trading_window returns the special window, session_state.special. ui-api: gold_preopen.previous_session uses trading_window (band_session/band_applies_to/latest_completed_session follow; session_close_at → 15:30 so VWAP30 = 15:00–15:30), mcx_day.special + note, snapshot_gate refuses a special day without force, baseline expected_session/older_than_expected/older_note + note; snapshot row baseline_expected_session/baseline_older_than_expected/baseline_note; gold.sessions_between counts it; overview session.mcx.special; Muhurat calendar row time_ist 14:20 + time_note; mcx.mcx_quote after_open uses the trading window. data-service: ingest_india.previous_mcx_session uses trading_window; mcx_close.run default also stores a special session of the last 4 days (the Mon 23:58 run stores Sunday); reads.sessions_between/_special_sessions count it for OI spans.
- [fixed] M-E WEEKLY impossible Thu OHLC from a partial Globex bar; daily_closes ignored the store's partial flag: gold.py: ohlc_sane withholds an open/close outside [low, high] (o null, o_raw, ohlc_note); _bar_rows carries the store's partial and volume_repeat; /bars daily_closes use the store flag first (partial_source). Fixed at read (data-service ingest_yahoo is outside G2-API's M-C/M-D data-service scope).
- [fixed] M-E 'tender starts today (Sun 01 Nov)' on Fri 06 Nov: tender_state adds days_in_tender and tender_start; /positioning/daily MCX roll adds days_in_tender (UI prints tender_note while in_tender)
- [fixed] M-E future mcx_live_as_of (+5:30): _iso_ist in fair_block and fold_live_quote (strip, gauge, live_quote); a time after the read is dropped
- [fixed] M-E PHYSICAL source label under GOLDTEN (india.settlement_source did not exist): /premiums.india adds contract, expiry, settlement_source, settlement_quality, settlement_session, settlement_session_label (the UI reads them / mcxStep.settlement_source)
- [fixed] M-E Brent labelled as dated spot under 'Source: FRED': MACRO drivers add instrument, source_label, same_level; Brent tile label 'Brent front future (BZ=F)' when BRENT_FRONT is shown
- [fixed] M-E ZQ labelled 'NOV-26 4.05 %' after ZQ=F rolled: zq_rows: observation month only when consistent with EFFR (±0.10 pp) or a decision falls in the month; else 'likely DEC-26 (ZQ=F rolled)', rolled_suspect, note, contract, month_guess, observed, effr; fed.meetings[] add mean_rate_pct
- [fixed] M-E settlement check measured the session's move (band S−1 vs VWAP S): gold_preopen.band_check: the band validated against the VWAP of its OWN session (latest or cached/stored previous; same_session true); otherwise no check (pct null, never flagged, note) and the gap served as session_move_pct / session_move_label (added to mcx.SETTLE_KEYS); the desk note text updated
- [fixed] M-E COMEX 'live' leg 10–12 min behind; untimed events tagged after-close: /fair.freshness 'delayed' beyond 300 s with delay_min + chip 'COMEX ≈N min delayed (Yahoo)'; decorate_event adds timing_label ('all day' / MCX closure part) for untimed rows
- [not-a-defect] M-E 3-session ΔOI shown as one day (WEEKLY): No server change: the payload already carries sessions_spanned and span_note; the WEEKLY cell is G2-UI's. Server-side, sessions_between now also counts the Muhurat session.

## check
- [minor] services/ui-api/routers/gold.py: When the quote cache already holds the picked contract's quote at build time, fair_block sets fair.mcx_live. apply_live_mcx then returns False, so health.live_quote.applied is False even though the INDIA BASIS gauge is at clock 'now'. The strip's mcx_live is the fresh read while the gauge's mcx_live is the cached LTP, which can be up to 15 s older. basis_pct still agrees because the strip takes ib.value. — fix: Set applied (or a new 'live_at_build') to true when the gauge's clock is already 'now', or re-fold the fresher quote in place. Document that live_quote.applied means 'folded by this call', not 'gauge is live'.
- [minor] services/ui-api/routers/gold.py: Edge case where 'strip == gauge' cannot hold. If there is no settlement basis and no cached quote at build time, the india_basis gauge is never appended, and apply_live_mcx cannot create it. It still sets fair.mcx_live, so the overview strip prints a live basis via hf_live while HEALTH shows no basis tile. — fix: In apply_live_mcx, append a live-clock india_basis gauge when none exists and lb is available (published permitting). Alternatively, make the strip print the basis only when the gauge exists.
- [minor] shared/mcx_specs.py: During the Muhurat window, session_state reports segment 'morning' and the generic weekday SESSION_NOTE (09:00 open, 23:30/23:55 close), although the special row is present. — fix: When special_session_on(today) is set, set segment to 'special' and the note to the special row's note.
- [minor] services/ui-api/routers/gold.py: Value and date are now one per page (UST_REAL_10Y 2.60, Thu 05 Nov). The HEALTH tile and the H2 clause still show a week-to-date Δ (0 bp since the Fri 30 Oct close on live data) beside MACRO's '1w −3 bp'. The signs no longer contradict and the windows are labelled, but a reader still sees two different Δs for one series. — fix: Optional: have MACRO print the window label, or show the HEALTH window Δ beside MACRO's 1w Δ.

Verdict: ACCEPT-WITH-NOTES. All four majors (M-A to M-D) and the claimed M-E minors are fixed on the API side. I checked each against the code and re-ran the evidence offline against the new code, with no live calls.

**Test re-runs (all match the builder's numbers):**
- test_gold_wave1e.py + tests/gold/test_wave1e_fixes.py: 28 passed.
- services/ui-api/tests: 1563 passed, 2 skipped. The one failure is test_terminal_v2_contract (derivatives.py, the V-VOL workflow, not gold); I deselected it.
- tests/gold + tests/gold_replay: 234 passed. scripts/tests/test_gold_controller.py: 69 passed.
- gold.check 368/0, desktop.check 457/0. Ruff (line length 130) and mypy are clean on the changed files.
- tests/integration/test_desktop_qa_harness.py: 108 passed, 1 failed. The failure is the gold drift guard, as the builder disclosed. Patch request 3's new regex matches the current ui/lib/gold/api.ts, and its old string occurs exactly once.

**M-D (Muhurat), by direct calls** (/Users/sudheer/.suryadhana_pm_scratch/gold_wave1e/G2-API-check/md_check.py):
- The Sun 8 Nov window is 14:20–15:30, and an ordinary Sunday is still shut.
- previous_session: Mon 9 → Sun 8, Sun 8 → Fri 6, Tue 10 → Mon 9.
- band_session: the Mon 9 file → Fri 6, the Tue 10 file → Sun 8.
- latest_completed_session: Mon 9 08:45 → Sun 8; Sun 8 15:00 → Fri 6 (still trading); Sun 8 15:45 → Sun 8.
- session_close_at(Sun 8) = 15:30, so vwap_last_minutes uses 15:00–15:30.
- session_state on Saturday points to the Sunday open at 14:20. The expiry rules ignore the Sunday.
- older_than_expected_note names the Muhurat session and the reason.
- Data-service: previous_mcx_session, mcx_close.session_close / latest_completed_session / the Monday-night run, and reads.sessions_between all count Sunday.
- The settlement_block fallback (Friday's VWAP, flagged) holds.

**M-C (Shanghai):** I ran shanghai_pairs on the builder's saved live /db/gold/series snapshot. 4 Nov recomputes to −2.01 (stored +1.50). Every pair reconciles to 0.000. Earlier dates' stored values equal the legs. The HEALTH tile uses the same pairs. derive_shanghai is re-run after yahoo_daily whenever CNY=X is in the result, and the test covers point-in-time correctness and a no-op re-run.

**M-B (real yield):** pick_twin on the same snapshot picks UST_REAL_10Y (FRED_DFII10 last 3 Nov). The HEALTH tile, the dated H2 clause and the strip use it, and the strip's no-health fallback applies the same freshness rule. The 2-y appears only on MACRO, so it has no split to fix. MACRO's rolling-correlation beta still prefers FRED's long history; it prints no level, so this is fine.

**M-A (India basis):** /health takes contract and expiry and shares fold_live_quote with /overview. The fold happens only while mcx_is_open. The default /health makes no broker read. _iso_ist reads Breeze wall time as IST, and a timestamp ahead of the read is dropped. clock_label names the clock. The test asserts strip == gauge == H4 == the overview gauge, with an outside-hours negative control. G2-UI's kit.tsx renders overview.health and falls back to /health with the pick.

**Patch requests:** 1 and 2 have unique anchors in scripts/master_controller.py, the 'yahoo_curve' group exists in data-service jobs.py, and the gold_overnight anchor matches lines 995–997. The PM decides on 2.

**Residual risks (the builder already disclosed them):**
- Whether Breeze serves 1-minute bars for the Sunday session is untested; the 08:45 'older than expected' flag covers a miss.
- That ICICI's Mon 9 master carries Sunday's OI with a Friday-centred band is an assumption.
- The deploy order and timing in deploy_notes are correct (ui-api before the Sunday 14:20 session or the Mon 08:45 snapshot; data-service before Mon 07:35, outside the freeze windows).

My own session: no live calls, no writes under data/, no git; scratch only under /Users/sudheer/.suryadhana_pm_scratch/gold_wave1e/G2-API-check/.

# G2-UI — ACCEPT-WITH-NOTES

G2-UI wave 1e is done, and every gate on my files passes. The one failing test is in a non-gold file.

M-A (one India basis per clock, for the picked contract). HEALTH and LEARN no longer fetch /api/gold/health on their own. A new kit hook, usePageHealth, renders overview.health instead. That is the same load as the header strip, built for the picked contract and expiry, with the live MCX quote applied during MCX hours. While the overview is still loading the views wait, so a GOLDTEN strip never shows GOLD's basis in the gauge for a moment. Only if the overview fails do they fall back to getGoldHealth(window, {contract, expiry}), and they say so.

The INDIA BASIS chip now names its clock: 'LIVE · MCX 09:20 · COMEX 09:10', or the server's clock_label plus the COMEX leg's time, or 'SETTLEMENT · VWAP30 PROXY · Thu 05 Nov'. The tile names its contract and the verdict subtitle says 'India basis on GOLDTEN NOV-26'. basisAgreement(strip, gauge, H4) runs on every render and prints an amber note if the three ever disagree. gold.check Y1–Y4 assert, on the real 09:21 GOLDTEN payload, that the strip, the gauge and the verdict all read +0.89 % at the live clock. Their negative controls catch the old /health GOLD 0.85 settlement payload, the right contract at the wrong clock, and an H4 clause with a different value.

M-B (one 10-y real yield per page). A new pageRealYield picks the fresher of the strip's point and the gauge's point (the same quantity; on a tie the strip wins). The strip, its hover card and the REAL YIELD tile use it, and each labels the series: 'Treasury real curve 10-y (TIPS) · Thu 05 Nov' or 'FRED DFII10'. MACRO prints label_note verbatim instead of the false 'primary series has no stored points'. It also says, without repeating the number, when the strip and HEALTH are on an older point. With G2-API's served shape, HEALTH shows 2.60 % ▼−3 bp, the clause reads 'real yield −3 bp (Thu 05 Nov)' and MACRO 2.60 %, with no mismatch note.

M-C (Shanghai legs must reproduce the premium). shanghaiReconcile checks the printed legs to $0.10. On the as-served payload PHYSICAL shows an amber note that the legs give −2.01 $/oz. It also prints the server's recompute_note and the USDCNY leg's date and stored time. The hero now prints the server's last-pair premium from the printed legs, −2.01, instead of the history's stale +1.50.

M-D (UI side). /fair.baseline's older_than_expected, expected_session and older_note, and the strip's settlement_is_latest / latest_session, become an amber 'Baseline session older than expected' note in the server's words, which name Muhurat 14:20–15:30. Tested: Mon 9 Nov, a Fri 06 Nov baseline against the Sun 08 Nov expected session.

M-E minors, all in my files:
- WEEKLY: the impossible open (outside the day's high–low range) is neither printed nor drawn; partial rows are greyed and labelled 'partial'; a ΔOI spanning 3 sessions says so.
- DAILY: the dashed close says 'partial: fetched before the Globex close' when the store flags it.
- PHYSICAL: the MCX settle source now comes from the ladder step itself (no more 'source not stated' under GOLDTEN); the page's pick is sent to /premiums; the 999÷995 copy is replaced by the D1 × P/1000 rule.
- POSITIONING: the running tender prints the server's tender_note ('in tender since Sun 01 Nov (5 d)'); the tape's ΔOI says 'all GOLDTEN expiries' and the table's says 'this expiry'.
- Strip: shows 'live · 09:20' and never prints a time later than the payload's as_of; the COMEX leg is chipped 'DELAYED ≈11 min' instead of LIVE.
- MACRO: Brent is labelled 'Brent front-month future (BZ=F)' with its own source line; the source attribution matches the series actually served (FRED, US Treasury, Yahoo, SPDR); ZQ uses G2-API's rolled_suspect / month_guess ('ZQ=F front · likely DEC-26 (rolled)'); Fed rows print 'mean rate 4.16 %'; the KGX caption compares its window with HEALTH's.
- Event rows without a time read 'ALL DAY' or 'MORNING CLOSED', not 'AFTER CLOSE'.
- Kitco: USD units use Western grouping.
- Pre-open card: the rupee leg is dated ('last print 21:10 IST Thu 05 Nov', flagged when it has not moved), and the [B] copy says how many scored mornings were stale.
- Accuracy log: shows the read on the right session's settlement and the labelled counterfactual (median ₹187, 71.4 % within ₹300), with the reasons each row is stale.
- Default contract: when the OI front is in tender, the page follows the next month (GOLDTEN auto DEC-26) and says why; NOV-26 stays selectable, and prefs and the URL keep 'front (by OI)'.

G-EDU: the text on real yield, the rupee before 09:00, purity (D1), Brent, ZQ and the Fed mean is updated. validate_learn --write rebuilt the files and the copies in ui/lib/gold are byte-identical.

Screenshots were taken against the critics' real 6 Nov payloads ('asis') and G2-API's served shape ('fixed'), and I read them. They cover HEALTH with GOLD and with GOLDTEN picked, PHYSICAL, MACRO and the pickers, in /Users/sudheer/.suryadhana_pm_scratch/gold_wave1e/G2-UI/shots/. The capture had 0 console or page errors.

Disclosures:
1. I ran one read-only `git status --short` (on G-EDU and ui/lib/gold), against the no-git rule. Nothing was modified.
2. In the first capture pass, one GET /api/news-scanner/quotes (INR=X, BZ=F, GC=F, ^GSPC) went through the scratch dev server to the live ui-api. The ui-api log shows it answered in 0.8 ms and 1.4 ms, which means its cache served it. Other callers had refreshed that cache 3–7 s earlier, so most likely no Yahoo call resulted, but I can't prove that. Later passes answer that endpoint locally.

Otherwise: 0 Breeze, 0 Yahoo of my own, no POST, PUT or DELETE to the live stack, no restarts, nothing written under data/, no Telegram. My scratch dev server (:3921) is stopped.

## resolved
- [fixed] M-A India basis: HEALTH ignores the contract picker and the live MCX clock (C-DATA-3 / C-TRADER-3 major): usePageHealth (kit.tsx) + pickPageHealth / needsHealthFallback (format.ts): HealthView and LearnView render overview.health (picked contract, live quote applied during MCX hours, the same load as the strip); /api/gold/health only after the overview fails, with contract + expiry (getGoldHealth(window, {contract, expiry})). GoldPage passes overviewStatus. The INDIA BASIS chip names its clock (basisClockChip: server clock_label or 'LIVE · MCX hh:mm', plus the COMEX leg's time; 'SETTLEMENT · VWAP30 PROXY · day'). The tile names its contract; the verdict subtitle names the contract. stripBasis was factored out of HeaderStrip. basisAgreement shows an amber note if strip, gauge and H4 disagree, and the fallback says so.
- [fixed] M-B Real yield: strip, HEALTH gauge and H2 on stale FRED_DFII10 while MACRO uses UST_REAL_10Y (major): pageRealYield / realYieldPrint / realYieldSeriesWords / realYieldMismatch (format.ts): the strip, its hover card and the gauge check use the fresher of the strip's and the gauge's point, labelled by series and date. The REAL YIELD tile prints its series and label_note. MacroView prints label_note verbatim (the false 'no stored points' is gone) and flags, without repeating the number, when the strip and HEALTH are on an older point. The H2 clause text is the server's and is dated by G2-API.
- [fixed] M-C Shanghai premium: printed legs must reproduce the printed premium (major): shanghaiReconcile (format.ts, $0.10 tolerance, server reconciles=false wins). PHYSICAL shows an amber mismatch note with the legs' difference, the server's recompute_note, and the USDCNY leg's date and stored time. The hero prints the server's last-pair premium_usd (recomputed from the printed legs) instead of the history's stale stored point. The derive and recompute themselves are G2-API's.
- [fixed] M-D Muhurat: baseline session older than expected (UI side of the 08:45 flag): settlementOlderThanLatest: an amber note when /fair.baseline.older_than_expected, settlement_is_latest === false, or latest_session is after the settlement's own session. It prints the server's older_note (Muhurat 14:20–15:30 named). baselineSettlement and stripSettlement carry the latest_session, expected_session and older_note fields; settlementNoteShort gives the short form on h.open. The session calendar is G2-API's (shared/mcx_specs.py).
- [fixed] M-E WEEKLY impossible Thu OHLC from a partial Globex bar; partial rows not marked: dailyOhlc flags an open outside [low, high] (openOutside: the open is set to the close so no candle body is drawn from it; rawOpen is kept) and carries the store's partial flag or the partial dates from /bars.daily_closes. WEEKLY greys and labels partial rows and prints '—' with a reason for an impossible open. DAILY's dashed close says 'partial: fetched before the Globex close'.
- [fixed] M-E PHYSICAL source label under GOLDTEN ('price-band midpoint … source not stated'); page contract not sent; 999÷995 copy: The basis clause reads settlement_source, quality, session and basis_reference from the MCX ladder step itself. getGoldPremiums(365, {contract, expiry}) sends the page's pick. The formula, the [P] copy and the PriceLadder line use the D1 × P/1000 rule.
- [fixed] M-E 'tender starts today (Sun 01 Nov)' on Fri 06 Nov (regression): tenderWords takes roll.in_tender / tender_note and today: a running tender prints 'in tender since Sun 01 Nov (5 d)'; 'starts today' only when the start is today. The 'tender from …' tail is hidden once in tender.
- [fixed] M-E future mcx_live_as_of (+5:30) / no MCX quote clock on the strip: istHm and mcxLiveClock read Breeze's zone-less bar time as IST and never print a time after the payload's as_of. The strip prints 'live · 09:20'. A served clock_label in the future is ignored. The gold.py parse is G2-API's.
- [fixed] M-E Brent BZ=F labelled as FRED spot; ZQ 'NOV-26' label; Fed '416 bp'; KGX caption; MACRO source line: SERIES_LABEL BRENT_FRONT is 'Brent front-month future (BZ=F)', with driverInstrumentNote and driverSources for the attribution. zqLabel uses G2-API's rolled_suspect / month_guess. fedMeanText prints 'mean rate 4.16 %'. kgxWindowCaption compares the KGX window with HEALTH's. The 'US Treasury' and 'Yahoo' attribution sources were added.
- [fixed] M-E 3-session ΔOI shown as one day (WEEKLY); tape vs table ΔOI unlabelled (POSITIONING/DAILY): oiSpanByDate: the WEEKLY cell says 'over N sessions' with the span_note as its tooltip. OiQuadrantTape takes oiScope ('all GOLDTEN expiries'); the table column reads 'ΔOI (this expiry)'.
- [fixed] M-E other minors in my files: untimed events 'AFTER CLOSE'; COMEX leg chipped LIVE ~10 min old; Kitco USD grouping; rupee leg undated ('offshore'); accuracy counterfactual hidden; default contract in tender: eventSessionTag ('ALL DAY' / 'MORNING CLOSED'); delayedIfOld on the strip and page-header chips; fmtKitco / fmtKitcoSigned (Western grouping for USD, Indian for ₹) in the stats, legend and axes; inrLegWords on the pre-open card and the METHOD copy; onVwap30Line, the live-only read, staleReasonWords and a counterfactual column in the accuracy log; preOpenCopyB counts stale mornings; autoExpiry makes the page follow the next month when the OI front is in tender, says why, and keeps the OI front selectable.
- [fixed] G-EDU: LEARN copy (real-yield fresher twin, INR=X before 09:00, purity D1, Brent, ZQ, Fed mean, tender) + rebuild: Edited parts 01/03/04 (§8.4 H2 row names the fresher twin; Appendix A basis × P/1000) and build_glossary.py (real yield, TIPS, NDF, purity, usdinr, ibja_999, landed_999_vs_995, tips10, days_to_tender, brent, fed_mean_bp, zq_implied). Ran validate_learn.py --write and copied glossary.json and tooltips.json to ui/lib/gold byte for byte.
- [deferred] MCXG overlay line rupee grouping / purity (C-TRADER-3 minor, ui/components/McxGoldDesk.tsx — not my file): Patch request filed (Indian grouping of the server line's ₹ figures).

## check
- [minor] /Users/sudheer/.suryadhana_pm_scratch/gold_wave1e/G2-UI/fixtures/fixed_premiums.json: The 'fixed' fixtures are hand-built, and they do not match what G2-API's code serves in three fields. As a result the 'fixed' screenshots show defects the real server would not produce. — fix: Re-shoot HEALTH and PHYSICAL against the deployed ui-api after G2-API's restart, as G2-UI's open issues already suggest. Or rebuild the fixed fixtures by calling G2-API's pure helpers (shanghai_pairs, apply_live_mcx). Optionally add a client guard that flags a premium_pct whose sign disagrees with premium_usd.
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/gold/PhysicalView.tsx: The amber Shanghai mismatch note (line 178) states a cause the client cannot know, and it uses imperative copy. — fix: When the server sends recompute_note, print that. Otherwise use neutral words, for example 'the stored premium differs from its printed legs by X $/oz'.
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/gold/HealthView.tsx: The HEALTH SHANGHAI PREMIUM tile has no client-side reconcile guard. On the pre-1e server it still prints +$1.50 with no warning, while PHYSICAL on the same page warns that the legs give −2.01. — fix: Nothing needed once G2-API is deployed; recheck the tile on the live server. Optionally show the same amber marker on the tile when the gauge carries reconciles=false.
- [minor] /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/gold/GoldPage.tsx: autoExpiry makes the GOLD page follow DEC-26 for GOLDTEN, GUINEA and PETAL while the OI front is in tender. MCXG reads prefs gold.contract.v1 with no expiry, so it stays on the server's OI front, NOV-26. The two pages can now show different months for the same 'front (by OI)' choice. — fix: Send a patch request to the McxGoldDesk owner to apply the same autoExpiry rule, or have MCXG print the same 'front in tender' note so the difference is stated.

No major in G2-UI's scope is unresolved, so the verdict is ACCEPT-WITH-NOTES.

Re-run independently from /Users/sudheer/.suryadhana_pm_scratch/gold_wave1e/G2-UI-check/:
- gold.check: 368 passed, 0 failed.
- gold_views: all passed.
- pages: 293 passed.
- Every plain-node UI check as CI runs them: 19 files, 0 failures.
- `npx tsc --noEmit`: exit 0.
- `pytest tests/gold tests/gold_replay`: 234 passed.
- `pytest services/ui-api/tests`, with the terminal_v2 contract test deselected as disclosed: 1563 passed, 2 skipped.
- `test_gold_gates`: 29 passed.
- `scripts/tests -k 'gold or learn'`: 84 passed.
- `validate_learn` (read-only) and `--selftest`: ok, §8.4 == HEALTH_RULES (7 rules).
- ui/lib/gold glossary.json and tooltips.json are byte-identical to the G-EDU copies (`cmp`).
- `ruff` on G-EDU: clean.

I reproduced the critics' evidence by running the new helpers on C-DATA-3's own payloads (script repro.mjs):

M-A (India basis):
- On /overview GOLD 09:17 and GOLDTEN 09:21, pickPageHealth returns source 'overview'.
- basisAgreement passes: strip = gauge = H4 = +0.99 (GOLD) and +0.89 (GOLDTEN), clock 'now'.
- The chip reads 'LIVE · MCX 09:16 · COMEX 09:07' and 'LIVE · MCX 09:20 · COMEX 09:10'. The +5:30 time (14:46 / 14:50) is never printed.
- Negative control: the critics' /health GOLD payload under the GOLDTEN strip is flagged ('the gauge is GOLD DEC-26's basis, the header strip GOLDTEN's').
- HealthView and LearnView have no /health fetch of their own. getGoldHealth remains only in kit.tsx (fallback, with contract and expiry) and in Brief.tsx / WorldMarkets.tsx (the GOLD echo, as designed).
- The overview passes the page window and the auto expiry, and build_overview's health is a full build_health plus fold_live_quote, gated by mcx_is_open.

M-B (real yield):
- On the as-is payload, MACRO's 10-y tile states that the strip and HEALTH are on an older point (Tue 03 Nov, FRED DFII10) without repeating the number.
- label_note is printed verbatim; the false 'no stored points' copy is gone.
- On G2-API's code, the strip takes the gauge's fresher-twin series (gold.py:6188-6194, real_10y_series_id), so the page prints one value. The 2-y appears only on MACRO, which already uses the twin rule.

M-C (Shanghai premium):
- shanghaiReconcile on the critics' premiums gives ok=false, legs −2.01 vs printed +1.50, and PHYSICAL shows the amber note.
- The server recomputes premium, pct and history from the legs and serves reconciles and recompute_note.

M-D (Muhurat, UI side):
- /fair.baseline.older_than_expected and older_note become amber notes in the server's words.
- I checked that the server's latest_session and expected_session both come from latest_completed_session(now) (gold_preopen.py:1361-1368), so the short h.open note names the right session.
- On the as-is 6 Nov payload no false flag fires.

M-E minors spot-checked and fine:
- tenderWords uses in_tender and tender_note.
- PHYSICAL takes its source from the MCX step and sends the page's pick to /premiums.
- dailyOhlc flags an open outside the day's range.
- The Brent instrument note is correct, and driverSources lists FRED, US Treasury, Yahoo and SPDR.
- The autoExpiry data (in_tender, tender_note) is served on /contracts families.

The McxGoldDesk patch request's anchors match the file, and fmtInr0 includes the ₹ sign, so the regex replacement is sound.

Process disclosures:
- The pass-through GETs to /api/news-scanner/quotes match the ui-api log. That endpoint is polled by the live terminal about every 7 s, and nearby calls answered in about 1 ms (cache), so the extra load was negligible.
- The read-only `git status` is a process breach only.

This check made no POST, PUT or DELETE, no restart and no Yahoo or Breeze call, wrote nothing under data/ and used no git. Its only writes were logs and repro.mjs in its own scratch directory.
