# Improvement log: the operations journal (newest entry first)

Last updated Fri 13 Nov 2026 15:05 IST (Terminal v2 wave 2 + the 5 Nov review fixes + gold wave 1e DEPLOYED 15:36, entry
below; market-hours acceptance; live NSE program + Terminal v2 wave 1 deployed 5 Nov 13:01; GOLD program deployed on the night
of 4 Nov). The 11–15 Oct sprint entries further down were run and checked against live data at the time; today the terminal
has 43 pages, `scripts/tests` collects 522 tests, ui-api 1,566 and the core suite 1,425.

**13 Nov 2026, 15:05: the cold-boot READ-ONLY trap is closed — the watchdog heals it and can no longer cause it.**
- This morning's incident, end to end: the Mac rebooted 12 Nov 13:11 (FileVault holds everything until login, 14:07
  today); the watchdog started ui-api 14:07 while data-service's first start failed on a transient dependency check;
  data-service finally started 14:13 UNDER ui-api's read lock and opened DuckDB READ-ONLY — /health 200 (so the
  watchdog saw "healthy"), /ready 503, every ingest doomed, and the app greeted the owner with a raw
  "data-service unreachable". Healed by hand in the lock-safe order at 14:15.
- Two watchdog changes (`scripts/stack_watchdog.sh`), both bash-3.2-safe, entry line untouched:
  1. **Every data-service START while ui-api is up is now lock-safe** (`start_data_service_lock_safe`): stop ui-api →
     start data-service → wait `/ready` 200 → start ui-api; ui-api is restarted on every path out, even when
     data-service fails, so the terminal never stays dark because of the dance.
  2. **A READ-ONLY data-service is now detected and healed** (`heal_read_only`, every 2-min run): /health 200 +
     /ready 503 + the body naming read-only → the same lock-safe restart, throttled to one attempt per 50 min,
     never inside a data-service freeze window (one Telegram line instead; it heals after the window).
- 4 new tests in `scripts/tests/test_ops_shell.py` (23 pass): heal order + throttle, freeze-window refusal,
  lock-safe start order, and ui-api coming back even when data-service's start fails. Live no-op run verified on
  the healthy stack (exit 0, no action). launchd picks the new code up on its next 2-minute run — nothing to restart.
- Also today: master-controller had been dead since 11 Nov 17:03 (two days, no jobs); the 14:13 restart's downtime
  catch-up re-ran bhavcopy/positions/events/results/backup and the ICICI login landed unattended.

**8 Nov 2026, 19:10: the auto-store would have stored a figure 28x too high — caught by testing the real document.**
- Fetched the Commerce Ministry's actual September 2026 release (`commerce.gov.in` serves the PDF, HTTP 200) and ran the
  parser over it. It returned **US$51.64 bn** for September, whose real gold figure is **US$1.8 bn**, because the release
  carries no standalone gold number: gold appears only inside "Non-petroleum, non-gems & jewellery (gold, silver &
  precious metals) imports in September 2026 were US$ 51.64 Billion". **The month guard passed it** — that sentence does
  name September 2026 — so the guard that was supposed to make `--store` safe would not have saved the row.
- Fixed: a figure is accepted only when its sentence is ABOUT gold imports (`ABOUT_GOLD_RE`) and does not mention gold
  merely to exclude it (`EXCLUDING_RE`: non-gems, non-petroleum, excluding, gems & jewellery, precious metals, silver &,
  pearls). The real release now returns nothing, which is the correct answer; a true gold sentence still parses.
- 8 new tests, including the ministry's own wording verbatim as a fixture and the case where an aggregate precedes a
  genuine gold sentence in the same document (it must return 1.8, not 51.64).
- **Independent confirmation of the stored history** while doing this: agencies report September 2026 gold imports at
  US$1.8 bn and August at US$2.3 bn — the store holds 1.8 and 2.298. The hand-typed rows are right.
- Honest consequence: the headline release does not contain the figure, so the 15 Nov job will usually send "a release
  is out, read it" rather than store silently. That is the correct behaviour, not a shortfall — and the plausibility band
  (> US$25 bn refused) remains the last line of defence.

**8 Nov 2026, 18:55: `ui_audit --tabs <wrong case or typo>` reported PASS while auditing the BRIEF page.**
- Found by accident: `scripts/ui_audit.py --tabs GOLD` printed "GOLD PASS ready=70ms console=0" and the screenshot was
  the EVENING BRIEF. Two things lined up — the router falls back to the brief for an unknown `?tab=`, and `probe.visit`
  gets no ready code for an id that is not in the page source, so `READY_JS` returns true at once (`if (!code) return
  true`). The run therefore "passed" a page nobody asked for.
- `resolve_tabs` now matches ids case-insensitively (so `GOLD` → `gold`, the real page) and **raises on an id the router
  does not know**, listing the known ids and suggesting near misses, instead of the old documented behaviour
  ("unknown ids are kept: the page ignores them"). 5 tests, incl. the negative control that an unreadable page source
  still falls back to pass-through rather than blocking a run.
- **The 43-page audits are unaffected**: `--tabs all` and the named sets always used real ids. Only a hand-typed id
  could hit this, which is exactly what happened here.
- Verified live after the fix: `--tabs GOLD` now audits `gold` (code GOLD, ready 154 ms, 0 console, 0 page errors) and
  `--tabs gld` stops with "unknown tab id(s): gld".

**8 Nov 2026, 18:40: India's gold-import figure is now stored WITHOUT the owner — a monthly job reads the PIB release.**
- `india_imports_watch` in `scripts/master_controller.py`, `CronTrigger(day="15-22", hour=11, minute=15)` — the release
  lands about the 15th, 11:15 is outside both freeze windows, and the job returns immediately once the month is stored
  (it reads `/db/gold/series` first) or when `GOLD_JOBS_ENABLED=0`.
- It runs `gold_india_imports_find.py --store`, which writes **only when the figure's own sentence names the month it is
  claimed for** (`month_named`). A year-earlier comparison, a quarter or a year-to-date total is reported instead, with
  the link and the command — never stored under the wrong date. The stored source carries the PRID and the sentence, so
  every row is auditable and revisable.
- Telegram: one line when a month is stored, one line when a release is out but ambiguous. Silent when nothing is
  published yet or PIB does not answer — it simply runs again tomorrow, and the data-health row still raises the month on
  the 16th if nothing is ever stored.
- Verified: `--store` run today exits 3 and the store is unchanged (`2026-08-31 2.298`, `2026-09-30 1.8`) — it does not
  invent a figure when none is published. 539 scripts tests, incl. 11 for this path with negative controls.

**8 Nov 2026, 18:05: the last manual number now finds itself — PIB turned out to be open.**
- After the trade portal (form only) and RBI (captcha on the XLSX) were closed, the third route worked: PIB, the
  government's press agency, answers a plain client with HTTP 200 and no captcha on both its RSS listing and its release
  pages, and the Commerce Ministry's monthly release states the gold figure in prose.
- `scripts/gold_india_imports_find.py` fetches the newest trade release, reads the figure, **quotes the sentence it came
  from**, and prints the ready `gold_india_imports.py --month --usd-bn` command. Exit codes say which case happened
  (0 found · 2 release found but no figure, link printed · 3 no release yet · 4 network refused).
- **It never writes to the store.** A number parsed out of prose can be a revision, a quarter, or silver in the same
  sentence; a wrong point-in-time row is worse than a missing one, so the owner reads the quoted sentence and runs the
  command. Read-only, at most 5 requests spaced 1.2 s, no crawl, generic UA.
- 6 parsing tests with negative controls (rupee figures, a gold-less sentence, a number borrowed across a sentence
  boundary, script-tag digits). One of them caught a real bug before release: the first regex used `[^.]` between "gold"
  and the figure, which rejects the commonest phrasing ("grew by 4.8 per cent to US$ 4.2 billion") because the decimal
  point looks like a sentence end; it now tempers on a period FOLLOWED BY whitespace.
- Verified live: 20 releases fetched, 0 trade releases, exit 3 — right answer on 8 Nov, since the release lands ~15th.
  The first real run is this month's; the data-health row still raises it on the 16th if nothing is stored.

**8 Nov 2026, 17:25: India's gold-import figure — a SECOND automation route probed and closed; the ICICI login evidenced.**
- The RBI route looked promising because the Bulletin prints the number in prose and `rbi.org.in` is already allowlisted.
  It is closed too: the Bulletin's statistical annex has no gold-import table (Table 32 Foreign Trade is POL / non-POL
  only; Table 21 is gold PRICES, already covered by IBJA), and `rbidocs.rbi.org.in` answers an automated XLSX download
  with a **captcha page**, not the file (47,938 bytes of HTML, not a zip). Recorded in SOURCES.md F14 beside the
  tradestat finding, so the question is settled with evidence rather than assertion: the hand-typed entry stands, now via
  `scripts/gold_india_imports.py`, with the data-health row raising it on the 16th.
- The ICICI auto-login is evidenced, not asserted: today's controller log shows `[special_session_login] Muhurat trading
  (Diwali Laxmi Pujan) ... logging in` followed by `[icici_session_refresh] refreshed: logged in, token applied via
  ui-api` — unattended, on the authenticator code alone, on a Sunday. The earlier `ICICI login needs you` lines are from
  before the TOTP key was stored in the Keychain.

**8 Nov 2026, 17:05: the off-Mac dead-man alert is LIVE — the 6 Nov silence cannot repeat.**
- The owner created the healthchecks.io check and pasted its ping URL; `HEALTHCHECK_PING_URL` is set in `.env` (never
  committed, never echoed — the URL is a credential: anyone holding it can keep the check green). `./start-local.sh status`
  reads `dead-man-ping  ok  hc-ping.com pinged 1 s ago (stack healthy)`.
- Verified end to end, not just configured: `--ping-test` → HTTP 200; a deliberate `/fail` → 200; back to success → 200;
  the status row returned to ok. One down + one up notification were sent to the owner's check by that test.
- **This single check already covers the power-loss case.** `ping_deadman` pings success only when all three services
  answer, hits `<url>/fail` the moment one does not, and sends NOTHING when the Mac is off or frozen — so the check goes
  red by itself after the grace period. On 6 Nov the Mac was off for 38 hours with nobody told; that is now impossible
  provided the check's period / grace are set (5 min / 15 min recommended; the watchdog pings every 120 s).
- Still optional and still unset: `HEALTHCHECK_WATCHDOG_URL`, the second check. It adds only the ability to TELL APART
  "the stack is down but the Mac is up" from "the Mac is down" — useful, not load-bearing.

**8 Nov 2026, 16:50: the 24-hour power clue narrowed from the logs — a daily timer does not fit.**
- Of the four multi-hour outages in the service logs (gaps > 12 h, which the 02:15 backup and 03:10 gold job rule out as
  idle), the stops are Wed 28 Oct 12:46 (43.4 h), Sat 31 Oct 11:00 (106.5 h), Thu 5 Nov 19:35 (20 min) and Fri 6 Nov 19:52
  (38.0 h). The 5–6 Nov pair really is ~24 h apart, but the October pair is eight hours earlier in the day, so NO single
  daily clock time fits them all: a timer or smart plug is not the general explanation, and the owner need not hunt for one
  first. The PMU's under-voltage record stands — irregular supply failures — so a UPS remains the fix that covers every
  candidate (house feed, inverter changeover, strip or socket). Written up in the incident report §8.

**8 Nov 2026, 16:10: the owner closed the gold goal; the power decision is "keep FileVault + an off-Mac alert".**
- Gold goal CONFIRMED COMPLETE by the owner after the final verification on the deployed build: 22/22 goal checks, every
  GOLD page 22/22 in Chromium and WebKit, each family priced in its own unit (GOLDPETAL ₹14,342 per 1 g beside GOLD's
  ₹1,42,540 per 10 g, which used to be printed as the pick's own), positions opened / closed by day / week / month for all
  five families, today's Muhurat settlement stored, 160 glossary terms and 270 tooltips with no dangling links.
- Power / boot (the RCA's O1): the owner keeps FileVault ON and adds the off-Mac dead-man ping, NOT auto-login — auto-login
  cannot coexist with FileVault, so it would have meant decrypting a disk that holds the broker credentials. `autorestart`
  is already 1. Remaining owner step: create two free healthchecks.io checks (period 5 min, grace 15 min — the watchdog
  runs every 120 s) and paste them into `.env` as `HEALTHCHECK_PING_URL` (stack healthy / `/fail`) and
  `HEALTHCHECK_WATCHDOG_URL` (the Mac is up at all). Both are already wired in `scripts/stack_watchdog.sh`; the controller's
  `_deadman_line` warns while they are unset. A UPS remains the only fix for the brownouts themselves.

**8 Nov 2026, 10:05–15:52: the gold program independently reviewed, 18 confirmed defects fixed, and the settlement store filled.**
- Review (`wf_962189ca-105`): three critics on the LIVE page against the owner's goal — a data auditor recomputing every
  number, a Bloomberg-style gold trader, and a newcomer — all PUBLISH-WITH-FIXES (6.4 / 6.8 / 6.8). An adversarial verifier
  reproduced each serious finding on the live stack: **18 of 18 real, 0 refuted**. Evidence
  `~/.suryadhana_pm_scratch/wf_rca_gold_20261108/` (confirmed_findings.json, goldReport.md).
- Fixes (`wf_ffb21be0-507`, two rounds, four disjoint lanes, each adversarially checked; commit `38e9148`): the Kitco-style
  chart drew Shanghai in ¥/g on the $/oz axis (now $4,036.75 from ¥868.0/g, server-converted at the vintage ON OR BEFORE
  that Shanghai session, with a UI guard); one dollar effect and one window per page (the window column refuses a row dated
  after today on EVERY driver and says why; the verdict prints a leg's own span when it is not gold's; MACRO hides the
  window column when it would reprint ANY trailing column); point-in-time dating (the FX day rolls 17:00 New York; a dated
  special session is a session of its own for Indian symbols, while COMEX / ICE / FX keep the weekend rule); the feeds say
  what they cover (calendar coverage, an overdue COT flag, the MCX tape reading the Breeze store, a contract-aware open).
  The round-2 checkers rejected one lane twice; the PM closed the last five majors by hand, each with a negative control.
- **The settlement store went from ZERO rows to a filled history.** The critics were right that no VWAP30 had ever been
  stored: the job's first scheduled run was the night the Mac died. The sweep + the special-session jobs fixed it live —
  `MCX_GOLD_202612_VWAP30` now holds 16 sessions incl. Fri 6 Nov (₹1,42,164.92, the session lost to the outage) and today's
  Muhurat (₹1,42,540.53 from 235 lots). `/api/gold/fair` baseline: session 2026-11-08, `breeze_vwap30`,
  `older_than_expected` false — Monday's 08:45 fair open is measured against today's session, as designed.
- Unattended ICICI login on a Sunday: `special_session_login` fired at 13:00:06 and logged in by TOTP for the Muhurat
  session (pre-open 14:05, trading 14:20–15:30); `special_session_close` stored the settlement at 15:45 (50 s).
- Open: GOLDTEN / PETAL / GUINEA have no stored window yet (their front is in tender; `contracts_for` picked the GOLD and
  GOLDM fronts). The nightly 23:58 run should fill them from Monday — verify.

**8 Nov 2026, 09:50–10:45: back from a 38-hour outage; the drivers history backfilled; two honest-label fixes.**
- The Mac stopped Fri 6 Nov at 19:52 (controller's last heartbeat 19:52:08) and stayed off until Sun 8 Nov 09:50 — the same
  minute as Thu 5 Nov, which restarted itself. `pmset autorestart 0`, so nothing powered it back on; no panic file. A
  four-lens RCA (system log, the 19:45/19:50 jobs, power/updates, the stack's own watchdog), each hypothesis adversarially
  refuted, runs in `wf_962189ca-105`. Owner action, still open: `sudo pmset -a autorestart 1`.
- The start-up catch-up re-ran Friday's evening work by itself (bhavcopy, positions, events, results 769 symbols, NSE files,
  index drivers, `iv_eod`, data-health) and the missed Saturday COT caught up: the latest report is 3 Nov, 1.4 days old.
- Index drivers backfilled from 2019-10-01 (PLAN 1.8 Sunday window, nothing else running): 1,763 sessions in 30 s.
  NIFTY 50 — 354 weight days, 1,044 driver states, tab `ok`, MAE 6 pts/day over 60 sessions (r² 0.9987). NIFTY BANK — 28 days,
  tab `insufficient` with 3 sessions, correct: nothing before its first archived constituent list (4 Nov) is computed.
- **Honesty fix (drivers):** that `insufficient` sentence blamed "the backfill has not run" — false the moment the backfill
  finished. A point-in-time index now names the real limit (its first archived list) and carries `limit: archive|backfill`;
  the UI fallback no longer invents a cause. Tests with negative controls (`tab_state`, `drivers_tab.check`).
- **Flaky-test fix (vol screen):** `/api/derivatives/vol-screen?results_within=N` counted from `date.today()`, so the
  generated `API_CONTRACT.md` §8 drifted with the calendar and failed two days after it was written. The route now reads an
  IST clock seam `_today()`, pinned in the contract test; the committed contract needed no change (proof the test, not the
  contract, was wrong). The old either/or row assertion is exact again.
- Deployed 10:38 (ui-api + UI release `20261108-103820`). Still to do today: Friday's MCX settlement VWAP30 (needs Monday's
  08:00 ICICI login), the Muhurat session at 14:05–15:30, and Monday's fair-open check.

**6 Nov 2026, 15:36: Terminal v2 wave 2, every non-gold defect of the 5 Nov 43-page review, and gold wave 1e DEPLOYED (`0b27dcc`).**
- Built 09:00–10:35 by two workflow rounds (nine builders with disjoint files, each re-checked by an adversarial checker; round 2
  closed every remaining major) plus gold wave 1e (two builders, two checkers). The PM applied 120 cross-builder patch requests
  (exact-match, backed up). Records: `reports/terminal_v2/build/wave2_and_fixes.md`, `reports/gold_program/build/wave1e.md`.
- Gates before commit: ui-api 1,566 · scripts 521 · core 1,416 (the order-dependent live-ticks test is fixed: state isolated,
  green in the full run) · execution 7 · alpha_lab 20 · cargo 154 + clippy + fmt · boot 74 · release builder 26 · tsc · every
  node check · ruff · both LEARN validators · both data dictionaries · both API contracts regenerated.
- Deploy 15:36 (after the close, lock-safe order): stop ui-api → restart data-service (`/ready` 200) → start ui-api → restart
  master-controller; UI release `20261106-153639-0b27dcc`; SuryaDhana.app rebuilt (`pages.rs` changed) and relaunched through
  its login item. `/metrics` answers on all three services.
- After-close jobs: `iv_repair` (329,949 rows; RV filled 329,459, YZ 329,441, IV30 flat-filled 135,342 flagged `cm30_flat`,
  4,702 range-outlier rows out of Parkinson / YZ; INFY YZ RV20 53.7 % → 36.5 %); the 5 Nov combined-OI (MWPL, 218 rows) and
  SPAN files; the FII/DII backfill (28 Oct, 2 Nov, 3 Nov stay missing: NSE keeps no archive); daily wraps 16 / 21 / 29 Oct
  written and the 4 Nov legacy wrap rebuilt (28 Oct, 2 / 3 Nov skipped: no FII/DII cash rows); the expiry-day replay
  (NIFTY 27, BANKNIFTY 6, FINNIFTY 6 expiries since May, 14,660 rows, 80 Breeze calls through the ledger); results filing
  times for the last fortnight's reporters into the new `nse_results.filed_at` (`released_at`, which the S1 shadow reads, is
  unchanged).
- What changed for the reader: one time convention (calendar time to 15:30 IST on expiry ÷ 365) in the store, chain, OVME,
  OSTR and the book, so one expiry shows one ATM IV; IV − RV20 named close-to-close with Parkinson and YZ beside it; skew with
  its own percentile; OI in contracts; IV paid vs delivered on monthlies over each option's own life (NIFTY +2.35 pts mean over
  11 months, 7 of 11 paid above); % MWPL and BAN from NSE's own files; NSE Contract_Delta beside the model delta. The paper
  F&O book (OSTR → BOOK, net Δ Γ Θ ν, daily marks, expired legs settle at the stored expiry-day mark, roll; PAPER ONLY), RSK
  › F&O, typed alerts on any stored series (no direction word in any kind), the 2-minute OI / IV tape, DERV › XPRY, CHRT on
  indices / the near future / IV30 / OI. Honesty sweep: real costs on ALFA and BTST, alpha_lab verdicts in RSCH, FII/DII
  "n of m sessions", EQS real close, crash-filter wording, LWSC liquidity universe, DEXP without Yahoo. GO arguments reach the
  target page; `GO IMPORT` brings the old :3000 settings across (owner click). Gold: contract-aware live HEALTH basis with a
  clock label, one real yield per page, the Shanghai premium recomputed from its printed legs, the Sun 8 Nov Muhurat session
  in the MCX calendar (Monday's fair open uses Sunday's VWAP), the COMEX curve in the 03:10 overnight job.
- Results filing times: 1,476 symbols re-read (62,804 rows; the 14 empty are InvITs / REITs); MOTHERSON's 5 Nov results now
  time to 14:58, inside the session, so ERN / EVTS measure the reaction from that session.
- Audit `reports/terminal_v2/qa/ui_audit_20261106_wave2`: the first run failed one page, RSCH in Chromium (full-page screenshot
  timeout). Cause: the page opened the 2,103-line improvement log in full, making the document 41,600 px tall. Fix: the report
  scrolls in its own pane like the study list, and a first visit opens the newest study with a verdict
  (`ResearchLibrary.tsx`, honesty.check R1/R2 with negative controls); release `20261106-161045`. Re-run: 43/43 in Chromium
  and WebKit.
- Gold verified end to end, 16:30–17:00 (`reports/gold_program/VERIFY_20261106.md`): every item of the gold goal 22/22 by GET on
  the live stack, every GOLD sub-view + MCXG + WEI 22/22 in Chromium and WebKit; the critics' open items closed or re-tested
  (paper-ticket margin == contract card on all 5 contracts; PETAL / GUINEA scaled to ₹/10 g). Three defects found and fixed:
  the accuracy-log dual-write had been refused with 422 on every call (ui-api sent `{"row": …}`, data-service reads the row
  itself; new test runs the real handler; DuckDB copy re-synced through 6 Nov); the COT freshness budget read amber every
  Friday by design (9 → 11 days); the Swiss customs parser matched 0 rows on the real 692 MB file (ISO-code and unit-count
  columns; fixed, 177 months Jan 2012 → Sep 2026 stored). data-service + ui-api restarted twice in the lock-safe order
  (16:37, 16:47), controller once. DATA health: 66 green, 1 amber (news track record, cleared by 19:45), 0 red.
- Gold, 17:00–17:55 — the last open items: owner decisions O-1 (keep as built), O-2 (CME files link-only), O-8 (Breeze daily
  MCX history only) answered; the Breeze collector built (`gold/mcx_daily.py`, table `gold_mcx_daily`, 09:35 Mon–Fri) and
  live-verified (15 contracts, 1,456 bars, OI = the master's roll ratio); Muhurat circular MCX/TRD/590/2026 confirmed by two
  republications; India imports Aug/Sep 2025–26 entered (cross-checked); SGE quotes scheduled every 5 min in SGE hours and
  the SGE parser's trading-day dating fixed (Friday-night quotes had been stamped on Monday, padded into the future; 782
  future rows purged). Deployed 17:44 in the lock-safe order. `reports/gold_program/VERIFY_20261106.md` §5.
- Gold, 18:09: the Breeze history is on the page — GOLD › POSITIONING 'MCX · positions opened / closed — by contract'
  (daily / weekly / monthly per the page window, the picked contract, OI split by expiry; arithmetic badge, describes only).
  Catalog BREEZE_DAILY → PUBLISH-CONTEXT; ui-api restarted, UI release `20261106-180837`; GOLD pages 22/22 both engines.
- Still to run: the outage backfill's inbox notes after 21:15 tonight; the NIFTY / NIFTY BANK drivers history on Sun 8 Nov
  10:00 (PLAN 1.8). Owner items: the IMPORT click; adopting `filed_at` for the S1 shadow (review); O-T13 (BANK pre-list days).

**6 Nov 2026, 09:26–10:45: market-hours acceptance PASSED; the EQS warm-up rows explained and labelled honestly.**
- The 08:00 ICICI job logged in unattended on the authenticator code (no SMS). Breeze: 4,723 ticks/min, 0 unmapped, every
  subscribed name ticked; NIFTY 50 / NIFTY BANK / INDIA VIX and the large caps read `breeze_ws` under 2 s; the hover card too.
- Audit `ui_audit_20261106_acceptance`: 43/43 in Chromium and WebKit, every page with a LIVE chip ≤ 10 s
  (`reports/live_nse/COVERAGE.md`, acceptance section, lists what stays DELAYED · NSE by design).
- EQS showed 24 rows STALE · BREEZE · 22m. An adversarial review traced it to lapsed subscriptions (no demand for 10 min,
  cached 09:08 auction ticks kept, page captured before the first new tick; Breeze sends no snapshot), not to quiet names or
  a sick feed as the reason text claimed. Fix (data-service `live_quotes.py` + `LiveTicks.subscribed_since`): a tick older
  than the current subscription is never quiet-LIVE and never covered for the NSE poller, and reasons name the cause. Not
  deployed: another session's uncommitted data-service work is in the tree, so the restart waits for it.
- Built, reviewed twice and NOT shipped: keeping quiet names LIVE past 120 s through NSE's copy (owner decision; the
  residual risk is a dead token reading LIVE for about 3.5 min after a missed trade).

**5 Nov 2026, evening (20:28–22:00): unattended ICICI login proven; evening checks.**
- ICICI auto-login: the Keychain item `ICICI_TOTP_SECRET` held a password-like value (not base32), so the 15:47 check stopped
  before ICICI. The owner supplied a Google Authenticator export; the key was decoded offline and stored in the Keychain without
  being printed. A forced login at 20:28 logged in on the authenticator code alone in about 14 s (no SMS); Breeze connected.
- Closed-market audit `ui_audit_20261105_evening`: 43/43 in Chromium and WebKit; no NSE chip reads LIVE; 232 of 241 dated chips
  read 5 Nov and the other 9 are dated by design (`reports/live_nse/COVERAGE.md`, evening section).
- The Mac restarted at about 19:52. The S1 shadow and the news track record had not run since 30 Oct: after the 31 Oct–4 Nov
  outage the catch-up deferred them to "the next run", and tonight's 19:45 / 19:50 runs fell in the downtime. Both were re-run at
  21:40 on the 19:20 snapshot. Open: a controller that starts inside the EOD window skips catch-up, so a job whose time has already
  passed waits a full day.
- CME: the VOI history is complete (2016-01-12 → 2026-11-03). The EFRP backfill (2017 →), cut by the 15:32 data-service restart,
  was restarted at 21:42 (2,198 files, finishing before the 02:15 backup).
- Open (gold, not NSE): `gold_india_ibja` reads amber at 18:30 because the parser reads IBJA's "previous 30 days" tables, which
  carry today's rate only the next day.

**5 Nov 2026, 13:01–14:05: live NSE program and Terminal v2 wave 1 DEPLOYED (the morning entry below is history).**
`LIVE_TICKS=1`; data-service, ui-api and master-controller run the v2 code; UI release `20261105-140130-f4c884e`. Breeze
websocket ticks price indices and stocks at 0.1–0.9 s; the 43-page audit with the live-freshness assertion passes in
Chromium and WebKit (`reports/live_nse/COVERAGE.md`). Fixes after the deploy:
- `66ffd28`: ui-api's live hub re-stated a cache-hit row "delayed — data-service did not answer" when it crossed 2 s while
  the request waited for another symbol's batch. Every upstream call had succeeded; this is what made the header NIFTY
  chip flip at random. The `data_health` catalog paths and the archive scanner are fixed too (they load at the next
  data-service restart).
- `f4c884e`: data-service serves API_CONTRACT §6's `/db/iv/*` and `/db/index-drivers/{contribution,fit,state,weights}`.
  ui-api read these and data-service served only `/db/fo-iv/*`, so OMON / EVTS / MEMB / DESK read OFFLINE with the tables
  populated. Gate: `tests/integration/test_ui_api_data_service_routes.py`. They load at the 21:37 data-service restart.
- `e8b8ecc`: honest chips on CF (NSE's DD-MM-YYYY day), ALRT (empty fire log), WTCH (empty list) and RSK (the book is
  dated by `checked_at`, its last confirmed read).
- Open: DESK's ledger stops at 30 Oct because the controller was down 31 Oct–4 Nov; the 19:30 `desk_daily` marks the
  missed sessions. CMDT's EIA panel needs a free `EIA_API_KEY`. The Breeze cap of 300 symbols can churn when more than 300
  names are asked for within 10 min.

**5 Nov 2026, morning: Terminal v2 wave 1 is in the tree, NOT deployed.** The live stack still runs the pre-v2 code:
UI release `20261105-041017` (GOLD), and data-service, ui-api and master-controller have not been restarted on the v2 code.
So no v2 route answers yet, the new tables do not exist in `market.duckdb`, no IV / drivers / VIX backfill has run, the v2
jobs below are not scheduled on the running controller, and `/metrics` is still 404 live. Plan: `reports/terminal_v2/PLAN.md`
(the 5 Nov amendment to §0.3: derived tables keep the latest computation per key, vintages are recomputed from the archived
source files). The repository is now on a PUBLIC GitHub remote; the PM commits and pushes after a secret scan. What the tree
holds, by builder (the first half's results and adversarial checks: `reports/terminal_v2/build/`):
- **Architecture (B7; check ACCEPT-WITH-NOTES).** `DuckDBStore` readers-writer lock (`read()` / `reader()` on per-call cursors,
  shared; `write()` / `writer()` exclusive). The routes' `store._conn` bypasses are retired through the applied patches. The
  R-ARCH §2.3 harness, now a test, measured 10 concurrent history reads at 15 ms wall against 42 ms through the old exclusive
  lock. `shared/metrics.py` (`GET /metrics`, `X-Request-ID`, JSON access log, anyio thread limit 64) is installed on all three
  services. `shared/http_client.py` (allowlisted, paced client; one `AsyncClient` per process with a breaker and stale-serve)
  serves ui-api's nifty-live / gift-nifty / indices-live proxies. Yahoo is gone from `/db/market-monitor`. The secret
  settings are `SecretStr`. Redis is bound to 127.0.0.1 with an optional password. `db_backup.py` has `--offsite`. The
  snapshot policy is one evening snapshot plus an orphan prune.
- **Data (B1; ACCEPT-WITH-NOTES).** `fo_iv/`: `iv_eod` reproduces R-IV's prototype on the 23 cached Oct-2026 NIFTY files within
  0.008 vol-pt and takes 1.5 s for all 224 underlyings of a day's file. `index_drivers/`: the replay on a clone gives a NIFTY 50
  60-session MAE of 5.7 pts and R² 0.998, with calibration equal to the top-10 file to 0.01 pp; NIFTY BANK's MAE of 102 pts shows
  as `fit.degraded`. `data_health/`: `dataset_catalog`, `ingest_log`, `data_gaps`. `nse_positions.py` gains the evening-file
  ingests and the bhavcopy `If-Modified-Since` revision pass. Tables and routes are listed in CLAUDE.md.
- **API (B3; check REJECT, fixes in progress).** `/api/derivatives/iv/*` and `/vol-screen`, `/api/market/index-drivers*`,
  `/api/desk/attribution`, and `POST /api/options/margin` (Breeze → NSE SPAN file → the 12 % heuristic with its measured 4.8×
  error). Also `/api/data/health`, the `shared/breeze_budget.py` ledger, `API_CONTRACT.md` with a sync test, and RSCH rows (IV
  history DESCRIPTIVE, Index drivers DESCRIPTIVE, SPAN margin ARITHMETIC).
- **Controller (B2; check REJECT, fixes in progress).** 18:30 equity-only; 19:25 drivers; the 20:30 evening pass with `iv_eod`
  last; 22:45 `nse_evening_pass`; 08:35 `morning_sweep`; the 15-minute `iv_intraday` pilot; Sat 03:00 `iv_weekly`; the hourly
  `data_health_check`; the start-up catch-up extended with gap rows; the watchdog's optional second heartbeat.
- **UI (B4), gates (B6), studies (B8): in progress as this is written.** IV and drivers components exist under
  `ui/components/vol/` and `ui/components/drivers/` and are being wired into OMON, DERV, EVTS, the stock Profile and MEMB.
  They were in no release when this entry was written; they shipped in the 5 Nov 13:01 release (entry above).
- **Docs and LEARN (B5).** `docs/NSE_DATA_DICTIONARY.md` has verified rows for the top-10 weights file, the constituent lists,
  FOVOLT, Contract_Delta, the combined / delta-equivalent OI, the SPAN file, `historicalOR/vixhistory`, the legacy F&O format,
  the dead `equity-stockIndices` and the ban list. **Finding: NSE's `Last-Modified` header is GMT.** Two probe notes had
  quoted the raw minute as IST; seven range GETs on 5 Nov settled the corrected times:
  - Contract_Delta and the delta-equivalent OI are evening files at 19:18 IST (not midday).
  - FOVOLT lands ≈ 17:00; participant volumes and FII stats at 20:10.
  - The NIFTY top-10 weights file lands at 16:30, so the 19:25 drivers job finds it.
  - `ind_close_all` is re-written at 23:20 IST, after the 22:45 re-check.

  Also from B5: `docs/TERMINAL_DATA_DICTIONARY.md` is generated from `dataset_catalog` (with a `--check` test in
  `scripts/tests`), and the LEARN layer (`reports/terminal_v2/LEARN/`, 44 terms incl. the 15 PLAN 1.6 asks, 123 tooltips, a
  validator for length, direction words, real column / payload keys, code facts and a bundled copy). CLAUDE.md now fixes the
  `/metrics` claim, lists the v2 inventory, extends the freeze-window note and adds the public-repo rule. The RUNBOOK gains the
  Redis password, `db_backup.py --offsite`, the data-health view and first-week checks.
- **Open before the deploy:**
  - Owner decisions O-T1…O-T14. The plan's defaults are taken meanwhile: indices + watchlist surface, a dated 6.5 % rate, no
    NSE v3 beside Breeze, no Desk input touched.
  - The Redis password waits for `./start-local.sh restart <svc>` to export it (the watchdog's hang restarts use that path).
  - The catalog's publication minutes still carry the GMT misreading until the requested patch lands.
  - `vix_backfill`'s cookie prime answered 403 to the shared client.
  - The SPAN file's 4 Nov scanning risk (₹8,124 for the condor) is far below Breeze's ₹81,497.07, so the file leg is exchange
    arithmetic, not the broker's block.
  - The 02:15 backup does not pass `--offsite`.
  - Nothing re-checks `ind_close_all` after its 23:20 re-write.

  The deploy follows PLAN 1.8: data-service, ui-api and master-controller restarted outside both freeze windows in the restart
  order; the backfills on a Sunday at 10:00; one `build-ui` release.

**4 Nov 23:10 → 5 Nov 00:10: GOLD deployed.** Wave 1b (the fix round) ran as 8 builders + 8 adversarial re-checks
(`reports/gold_program/build/wave1b.md`; 7 ACCEPT-WITH-NOTES, B4A REJECT on three new majors). The PM fixed the four remaining
majors by hand (WEEKLY no longer throws on an empty COT store — `latest` is nullable in `ui/lib/gold/types.ts` and every
reader guards it; DAILY charts GC=F's stored 1-minute bars and keeps the matched month for the label and the live dot, the
SGE overlay asks for the `1m` interval the job writes; PHYSICAL's GLD panel reads the one-row-per-fund `/flows` shape with
`cumulative_30d`; HEALTH renders object thresholds as text), applied 25 of 28 cross-builder patch requests (3 already
satisfied), rebuilt the LEARN assets (G-EDU is the superset; `ui/lib/gold/tooltips.json` is a byte copy), regenerated
`docs/GOLD_DATA_DICTIONARY.md`. Two feed fixes that came out of the Terminal v2 research the same night: **CME FTP** had
stored 0 rows ever because `ftplib` raises on the server's `229 Extended Passive Mode` reply to PASV — `gold/hosts.py` now
parses either reply form (`_PassiveMixin`; the client is built at call time so test stubs still intercept); **FRED** stalls
20 s on any User-Agent that names this app, so `fred.stlouisfed.org` gets the HTTP library's default UA, an 8 s timeout and
a breaker after three consecutive failures (a run used to burn 378 s). Gates before deploy: core 926 · scripts 361 · ui-api
1,151 · exec 7 · alpha 20 · cargo 154 + clippy/fmt · tsc · ten node checks · `validate_learn` · dictionary `--check`.
**Deploy:** UI release `20261104-230634` (`build-ui`), data-service / ui-api / master-controller restarted 23:08–23:10,
SuryaDhana.app rebuilt, self-tested, installed and relaunched (43 pages). *Incident:* ui-api restarted first took a
read-only DuckDB lock while data-service was down for a moment, so data-service came back READ-ONLY and every ingest
answered 503 — fixed by stop ui-api → restart data-service → start ui-api, written into RUNBOOK "After an outage" and
CLAUDE.md "Restart order". **Backfill** (steps 1–5, 8–10 of `/db/gold/backfill-plan`, 13 min): catalog 211 rows, COT
6,417 (1986→), Treasury 48,822, FRED daily 123,465 / weekly 21,542 / monthly 6,538, Atlanta Fed 10,942, ETF 5,524 (2004→),
SGE 5,110, CME calendar 266 + product reference 125 + today's VOI/EFRP, Yahoo daily 125,779 + 1-minute bars, IBJA 36,
RBI 12, margins 15, derived 487. WGC / LBMA showed 0 *inserted* because they were already stored (re-checked 5 Nov 10:10:
flows 2,760, holdings 5,914, S&D 660, premiums 516, LBMA turnover and vaults all present and served with attribution). The two
long CME histories (VOI 2014→, EFRP 2017→, ≈ 2 h each) started 5 Nov 10:04. **Acceptance:** parity old vs new release (both engines) 38 PARITY + 4 DIFF (three are the harness
blocking POSTs on the baseline side, one is the pre-open desk leaving CMDT by design) + GOLD NEW
(`reports/gold_program/qa/parity_20261104/SUMMARY.md`); 43-page audit Chromium 43/43, WebKit 42/43 with FUND's only miss
a pending `/api/health` probe that passed on re-run (`qa/ui_audit_20261104*`). The live HEALTH line at 23:35 read "FIRM
WEEK, GOLD-SPECIFIC · gold +0.7 % over the week · real yield −4 bp · funds net 105,562 (+1.3 % w/w, new shorts) · India
basis +1.5 % vs duty-paid · … describes, does not predict". Critics round (trader / beginner / data) launched 23:55:
`reports/gold_program/critics/`.

**5 Nov, wave 1c — LEARN after the critics (B5-LEARN; the other builders' fixes are logged by the PM when the round
closes).** C-BEGINNER rated LEARN PUBLISH-WITH-FIXES: the glossary was unsearchable for the words the page uses most
(C-BEGINNER-11), "basis" defined a different quantity from the strip's (C-BEGINNER-12), the "only [B] copy" toggle left
177 unmarked pro paragraphs and 15 sections with no beginner line (C-BEGINNER-9), 50 entries printed `long` = `short`
(C-BEGINNER-17), and builder-speak ("proposed panel") was on screen (C-BEGINNER-23). In the tree now
(`reports/gold_program/G-EDU/`, source of truth; `ui/lib/gold/{glossary,tooltips}.json` are byte copies that
`gold_views.check.ts` holds to parity): `glossary.json` 160 terms with an `aliases` field (272 — MM, OI, FND, LTD, GC1,
w/w, bp, pp, XAU, Shanghai premium, India basis, funds bought the dip …; unique, never a term's own name) and a top-level
`start_here` dozen (troy ounce · spot · futures · COMEX · MCX · open interest · COT · managed money · net position · basis
· roll · real yield) for the panel to pin above the alphabet; `long` is empty when it would repeat `short` and real long
lines were written for the beginner-critical terms; new entries w/w · d/d · m/m, bp vs pp, percentile, z-score, Moz,
fund-driver label, India price ladder, T+1 and the lag chip; "basis" now reads "the gap between a futures price and the
reference it is compared with — on this page MCX basis = MCX front settle ÷ duty-paid landed − 1" with `MCX basis` in
see_also. Tooltips re-read against the code: the fund-driver label states the rule exactly as
`services/data-service/gold/driver_rule.py` implements it (the larger of the two legs; the 27 Oct 2026 week reads "funds
bought the dip"); `d1w` / `d1m` / `etf_chg_1m` / `pct_1y` say what `change_over()` does (7 / 30 / 365 calendar days back
to the nearest earlier session, not "5 / 21 / 252 sessions"); the crowd percentile names its window; the dollar tile is
labelled by the series it uses; the India premium and the MCX basis each name one clock; `sge_vwap` (rendered by no view)
retired. CURRICULUM: every `## n.m` section of Parts 0–8 carries a `**[B]**` paragraph (§2.5, 4.2, 5.9, 6.4, 6.5, 6.8,
6.9, 6.10, 7.5, 7.7, 8.0–8.4 added), the stray unmarked pro paragraphs are `**[P]**`, §6.1 and §8.3 describe the
driver rule and the glossary fields, "proposed" is gone. `validate_learn.py` gained checks 10 (aliases / start_here /
long ≠ short) and 11 (a [B] in every section) with `--selftest` negative controls; `build_glossary.py` asserts the same at
build time; mypy / ruff clean. `docs/GOLD_DATA_DICTIONARY.md` regenerated (214 catalog rows: data-service's
`SGE_AUTD_OI`, `SGE_AUTD_DIRECTION`, `SHFE_AU_FRONT_OI` now have verdict rows, C-BEGINNER-16); `OWNER_GUIDE.md` §2 / §4
updated (the label is the larger leg; start-here and aliases). Still B4B's: the dotted terms on HEALTH / DAILY / WEEKLY /
MONTHLY / CONTRACTS (C-BEGINNER-7) and the panel-title routines (C-BEGINNER-8, in `learn.ts`).

**6 Nov 00:45: GOLD wave 1d deployed — the MCX settlement was one session stale, now fixed at the source.** Tonight's review
(analyst A6) showed every logged fair-open miss equalled the previous session's gold move (corr 0.98). The PM verified it with
Breeze 1-minute bars (GOLD DEC-26, last-30-min VWAP): Tue 03 Nov ₹1,39,448, Wed 04 Nov ₹1,43,237 — the page's "Wed 04 Nov
settlement" ₹1,39,452 was Tuesday's. Root cause (G-DATA, six files matched): the ICICI master published on day D carries the OI of
the previous session S1 but the price band in force DURING S1, centred on the settlement of the session before S1. Fixes
(build/wave1d.md, two rounds, all three builders ACCEPT-WITH-NOTES after their checkers' majors were closed): the band is labelled
with its real session; a new `mcx_close_vwap30` group (`gold/mcx_close.py`, 23:58 Mon–Fri `gold_mcx_close`, read-only Breeze
1-minute bars through the budget ledger) stores each contract's last-30-min VWAP as the settlement proxy (MCX's own DSP method);
ui-api computes the same VWAP when the store has none; the fair block carries `settlement_source / _session / _quality`,
`band_midpoint / band_session` and `settlement_check` (flagged > 0.6 %); the accuracy log re-checks every morning's baseline;
MCX basis pairs each session's settlement with that session's duty-paid landed price; purity is one rule everywhere (landed is
per fine gold; basis divides by landed × purity/1000 with GOLD/GOLDM 995 and GOLDTEN/PETAL/GUINEA 999 — Guinea's price level
proves 999, not 916); PETAL/GUINEA values are scaled to ₹/10 g; the TREND tile prints vs 20-d / vs 200-d / drawdown and the words;
MCXG matches GOLDTEN NOV to COMEX DEC-26 (not the thin GCX26) and its paper ticket takes the contract card's margin; Brent comes
from the fresher stored BZ=F twin; LBMA weekly turnover keeps every period; the EFP 20-session average reads the 2021→ history
(28,053 rows, backfill finished 00:44); and DAILY gained a **Kitco-style chart** from stored data (24 h · 3 d · 30 d · 60 d · 6 m ·
1 y · 5 y · 10 y · all; USD/oz · ₹/10 g ex/with duty · ₹/g · USD/g · USD/kg; Kitco itself stays a link). Deploy 00:45 (lock-safe
order, controller restarted, UI release 20261106-004501); gold pages 6/6 in both engines. ICICI sessions expire at midnight, so
tonight's VWAP could not be computed after the restart (the page says so and labels the band "Tue 03 Nov"); the first fair open on
the corrected baseline is Friday's 08:45 snapshot, after the 08:00 login. Gates: ui-api 1,369, scripts 447, gold 226, core 1,332
(+1 order-dependent live-ticks test that passes alone, pre-existing), tsc, every node check, validate_learn, both dictionaries.

**5 Nov 21:00–22:00: the 43-page expert review and two fixes it found.** Every page (43 + the GOLD, DERV › VOL and SYS ›
DATA sub-views, OMON/OSTR/DERV/CHRT also on NIFTY and BANKNIFTY) was captured at 1600 px and read by seven analysts as a daily
options trader / PM would, rated by two independent raters, and synthesised (desk note, daily routine, decision frameworks,
issues, glossary) into a private illustrated review for the owner. Re-rating (`reports/terminal_v2/RATING_20261105.md`):
overall **6.0 → 6.5**; UI 7.0 → 7.5 · architecture 5.5 → 6.5 · data freshness 5.0 → 6.0 · platform 5.5 → 5.5 · options & vol
5.0 → 6.5 · index intelligence 6.0 → 7.0 · commodities 5.5 → 6.0 · research & AI 6.0 → 6.0. Fixed the same night:
`/api/market/events` kept the first 500 of 1,737 merged rows, i.e. only the past week, so EVTS read "0 upcoming" and every NEXT
EVENT column (DEAL, INSD, EQS, BRF) was blank — it now keeps upcoming events first (`keep_nearest_events`, default 2,000; 892
upcoming tonight; d10cc2c, ui-api restarted 21:35); SYS › DATA crashed on a never-run job's null `last_run.ts` — guarded, typed,
and the audit's `APP_ERROR_TEXT` now matches the terminal's own "FAILED TO RENDER" box (b2b12a4, UI release 20261105-212905).
Open from the review (ranked in the private issues list): the MCX settlement proxy one session stale (gold fair-open), four
volatility labels (YZ vs close-to-close RV, near-expiry skew vs the 30-day percentile, two ATM IVs per expiry, volume in
contracts vs OI in shares), FII/DII multi-day sums skipping missing sessions, EQS prices from an old snapshot, the S1 shadow red
after the 19:34–19:55 controller outage, OSTR single-expiry, alerts price-only, phone overflow.

**5 Nov 03:50: critics' fix round (wave 1c) deployed.** The three critics (reports/gold_program/critics/: trader HOLD 4.5,
beginner PUBLISH-WITH-FIXES 6, data HOLD 4; 75 findings, 19 blockers) drove a five-builder round (`build/wave1c.md`). Fixed
and verified on the live stack: 1-minute bars and every `*_at` now carry a UTC offset (the 5h30 chart shift is gone); the
fund-driver word is one magnitude-aware helper (`gold/driver_rule.py`; the 27 Oct week reads "bought the dip", not "new
shorts"); IMF holdings are troy ounces scaled per (country, month) from that month's own USD value (BRA 5.54 Moz, USA 261.5
Moz / 8,133.5 t) and duplicate IRFCL period rows collapse; `/api/gold/series` serves the Yahoo-bar, ETF and Asia-backed ids
(DXY, USD/INR, FX, GOLDBEES, GLD/IAU) so the dollar gauge, KGX split and currency table fill; the health verdict names its
window ("week to date since the Fri 30 Oct close"), omits the driver word when a leg is missing and shows the dollar share;
one India premium (at the IBJA fix minute) and one Shanghai premium (same-date pair); the live MCX basis exists only while
MCX trades (`mcx_is_open`), otherwise the settlement-clock figure with its session named — the strip, gauge, ladder and BRF
line agree; next FOMC is the 16 Dec statement, speeches are their own kind; the COMEX spec/roll card follows the matched
month with FND 30 Nov from the CME calendar (the Sunday job was re-run); per-month daily bars (GCZ26 …) feed the header;
MCX OI deltas say "over N sessions"; LEARN gained 9 glossary terms, 272 aliases and a start-here dozen. Deploy: UI release
`20261105-034204`, data-service and ui-api restarted in the lock-safe order (twice), controller untouched; jobs
`imf_official`, `cme_calendar`+`cme_prf`, `yahoo_curve`, derive re-run. Re-review (data 7.5, trader 7, both PUBLISH-WITH-FIXES)
confirmed every blocker closed on the live page; the three leftovers (FOMC calendar, SGE same-date legs, headline cut) shipped
04:10 as UI `20261105-041017`. 43-page audit on the redeployed stack: 43/43 in both engines. Final report:
`reports/gold_program/FINAL_REPORT.md`.

**26 Oct: GOLD program, phase 2 wave 1 — one GOLD page (the 43rd), stored gold histories, COT / COMEX / physical /
macro / contracts, a LEARN layer, ICICI TOTP auto-login; the logic of every existing page unchanged except the
consolidation listed below.** Built from ten research reports synthesised in `reports/gold_program/SOURCES.md` (140 sources,
one verdict each: PUBLISH-CORE 28 · PUBLISH-CONTEXT 41 · LINK-ONLY 53 · DO-NOT-PUBLISH 18) and the plan
`reports/gold_program/PLAN.md` (binding principles, ownership, panel by panel, schema, schedule, API contract, labelling
rules). **Page:** GO `GOLD` (aliases `XAU`, `GC`; `COT` / `GPHY` / `GMAC` / `LRN` jump to a sub-view), nine sub-views
HEALTH / DAILY / WEEKLY / MONTHLY / POSITIONING / PHYSICAL / MACRO / CONTRACTS / LEARN; a header strip that names the four
instruments (spot proxy · COMEX front · matched month · MCX contract) and labels the MCX settlement by its *session*; a
rule-based health verdict that ends "describes, does not predict" (no score, no "N of 8"); the pre-open desk moved here
with its accuracy log (`heuristic` chip + measured miss on the ₹300 limit); the weekly COT "who did what" (five trader
groups, Δ in words, fund-driver label, crowdedness gauge worded "not a signal", options overlay line) and the daily
COMEX / MCX open-interest "what got closed"; the India price stack with the dated 15 % duty (Notification 16/2026-Customs,
13 May 2026 — the old "18 % implied premium" was 0.995 × 1.15 × 1.031); ETF, central-bank, OTC (LBMA turnover, London
vaults, EFP prints) panels; the KGX "gold or the dollar" split with a rupee leg; the contract selector with GOLDTEN,
per-contract economics and the roll calendar; our own Kitco-style 24-h chart from stored 1-minute bars (Kitco stays a
link). **Data:** `services/data-service/gold/` — 21 `gold_*` tables in market.duckdb (PLAN §c.1's 20 plus `gold_ingest_state`) and the `gold_cot_metrics` view, point-in-time (`report_date` /
`release_at` / `first_seen_at`), a catalog table that gates rendering (no verdict row → not rendered), ingest for the CFTC
(Socrata), the CME FTP (daily OI by product since 2014, EFRP, calendar, product reference), Yahoo (one fetcher, paced,
`period1/period2`), FRED / Treasury, GLD / IAU, WGC, IMF, SGE / SHFE, IBJA, RBI, AMFI; a host allowlist enforced by test
(`tests/gold/test_hosts_allowlist.py`, `tests/integration/test_gold_gates.py` T8; never www.cmegroup.com, mcxindia.com, kitco.com, the LBMA price pages, stooq, goldprice.org, investing.com); jobs stream
and batch (≤ 50k rows per insert). **Jobs:** `GOLD_JOBS` in `scripts/master_controller.py` (03:10 overnight, 1-min bars
every 5 min while COMEX trades, 06:40 morning, 07:35 MCX master, 08:40 health snapshot, 09:05 brief, hourly US-calendar refresh, 13:45 / 18:10 India, 15:45 CME,
16:10 Asia, 21:30 FRED, Sat 02:30 COT with hourly retries and a Saturday Telegram digest line, Mon / Fri / Sat weekly,
Sun 04:00 CME calendar); fetch-only, none inside a freeze window, catch-up with `backfill_from` after downtime; dormant with
the reason shown: MCX bhavcopy, MCX category-wise OI, Breeze daily (owner decision O-8). **API:** `/api/gold/*`
(overview, health, fair, series `freq=D|W|M`, bars, cot, positioning/daily, curve, contracts, premiums, flows, macro,
calendar, log, catalog, brief, learn) and `/api/positions/totp/*` (the TOTP section at the end of `routers/positions.py`:
status / preview / store / delete; Keychain first, the secret never echoed); `/api/commodity/gold-preopen*` kept as
aliases for one release. **LEARN + docs:** `reports/gold_program/G-EDU/` (CURRICULUM Parts 0–9 from `parts/`, Part 8 keyed to the panel
ids, §8.4 the verdict rule table copied from `HEALTH_RULES` in `routers/gold.py` — `validate_learn.py` reads that list with
`ast` and fails when the two differ —, Appendix E "what is not free", Appendix F the Bloomberg function map; 151-term
glossary; 260 tooltips (204 payload fields a view renders + one per PLAN panel; 20 unrendered keys retired, listed in
`build_glossary.py`; `ui/lib/gold/{tooltips,glossary}.json` are byte-for-byte copies, checked by `gold_views.check.ts`);
`validate_learn.py`, whose check 9 refuses a field tooltip no `ui/` source names), `docs/GOLD_DATA_DICTIONARY.md` generated from
SOURCES.md + the catalog seed (`scripts/gold_data_dictionary.py --check` runs in the tests), `reports/gold_program/OWNER_GUIDE.md`.
**Studies, one line (`reports/gold_program/FINDINGS.md`, long form `G-STUDY/FINDINGS.md`):** every positioning, flow, macro
and seasonal series FAILS as a forecast at 1 / 4 / 13 weeks (0 of 69 walk-forward rules beat buy-and-hold; GLD daily tonnes
0 of 6; rupee seasonality: no month passes both halves) and PASSES as a description of the week (Δ fund net vs price
Spearman +0.65) — so every gold number carries `context`, `arithmetic` or `heuristic`, never `signal`, and nothing gold
feeds the Decision Desk, the S1 shadow, directional alerts or the paper ticket's price. **Intentional browser-visible
changes:** CMDT drops the Gold Pre-Open desk (a `GOLD ›` chip on its gold tile; keyless FRED leg); BRF's gold panel becomes
one line (and stops rotating on the 09:15 clock); WEI's GC=F row keeps its row and gains one line + a hover; MCXG's overlay
becomes one line and its specs card becomes the shared contract selector (+ GOLDTEN; the ticket adds max lots at 1 % risk,
USD/INR hedge lots, ATR ₹, margin from the dated NRML mirror); the macro tape's "GOLD" is "GOLD GC1"; BRKR gains the
"Auto-login (TOTP)" panel; RSCH gains the gold rows; the 08:45 Telegram adds the measured miss and skips MCX holidays.
*Planned, not in this release (PLAN §b):* ECO / EVTS do not read `gold_events` yet — the gold calendar (COT release,
COMEX FND / LTD, MCX expiries, Dhanteras, Muhurat, Budget, US CPI / NFP / PCE / GDP in IST) is on GOLD › HEALTH
(`h.events`), MACRO (`mc.calendar`) and CONTRACTS (`c.roll`) only. **Gates:** `ui_audit` default 16/16 and `--tabs all` 43/43; desktop `PAGE_COUNT` 43; parity 42 + 1 expected
delta; the five suites plus `services/ui-api/tests/test_gold.py` and `test_icici_totp_routes.py`, `tests/gold/` (schema
PIT, COT, derived series, jobs API, `test_hosts_allowlist.py`), `tests/gold_replay/` (fixture replays),
`tests/integration/test_gold_gates.py` (gates T1–T9), `scripts/tests/test_gold_controller.py`,
`scripts/tests/test_gold_data_dictionary.py`, `tests/test_gold_study_reproduce.py` and the node checks
`ui/components/__tests__/gold.check.ts` / `gold_views.check.ts`. **Owner (ordered, plain
English in OWNER_GUIDE.md):** O-1 terms posture (WGC / SPDR / IBJA / SGE: display-only with attribution, or links), O-3
confirm the duty at CBIC, O-4 store the ICICI TOTP key in the Keychain (`security add-generic-password -U -s suryadhana
-a ICICI_TOTP_SECRET -w`, then `chmod 600 .env`) and run one attended `daily_session_refresh.py --force` after 15:40, O-5 /
O-6 approve the page, the tables, the schedule and the one-off backfills (CME FTP ≈ 2 h, 330 MB transient), O-2 the CME
block, O-8 MCX / Breeze collectors, O-9 ICICI's tender cut-off, O-13 the pre-registered studies, O-14 the Telegram wording.
**Deploy:** data-service and the controller only outside 07:45–09:20 / 18:30–21:15; ui-api not 07:55–08:10; the gold jobs
pause themselves for an hour on a 404 until data-service carries the gold package; every history starts the day its job
starts and the page says so.

**24–25 Oct: SuryaDhana desktop app (Tauri v2), logic unchanged — the terminal is now an app that starts at login.**
The terminal UI is a static release served by ui-api on http://127.0.0.1:8010 (`./start-local.sh build-ui`, atomic
`ui/dist/current`, rollback) and wrapped by `/Applications/SuryaDhana.app` (`desktop/`, `scripts/build_desktop.sh --install`,
`--rollback`). Core stack = 3 processes; the Next server on :3000 is optional (dev + one-time settings migration) and bound to
127.0.0.1. **App:** login job (relaunch after a crash, never after Quit), boot screen for every state (starting / down /
ui-api NOT RESPONDING / no UI release / untrusted port), menu-bar NIFTY/ICICI/Desk line, native menus (Go ▸ 42 pages, ⌘1–9,
⌘[ ⌘], zoom, ⌘F find, ⌘P print), multi-window + session restore, native downloads (quarantined, extension allow-list) and
notifications (incl. the scheduler's alert feed), crash recovery of a dead WebKit page. **Terminal:** per-page error panels
(one bad payload no longer blanks the window), honest LINK DOWN + reload of failed panels, type-to-GO, Esc, Back/Forward,
2-dp prices, PAPER ONLY on PORT (LIVE impossible), login URL never printed, EQS no longer stutters, page-ready p50 41 ms /
p95 191 ms (was 453/760). **Security/ops:** Host/Origin guard on all 3 services (DNS rebinding + cross-site writes refused;
CORS removed; :3000 LAN exposure closed), **PAPER ONLY enforced in code** (the legacy engine was found persisted in
LIVE/ACTIVE and reset to PAPER; ui-api refuses LIVE unless `EXECUTION_LIVE_ALLOWED=1`), .env injection + quoting fixed,
settings sync `/api/prefs` (SQLite, backed up nightly), watchdog restarts a *hung* service with diagnostics, log rotation,
ICICI token routes off the event loop, `error_kind` distinguishes an ICICI outage from an expired session (no OTP is texted
during an outage). **Incident 25 Oct 14:40–14:48:** ui-api's event loop blocked in a sync Redis recv (round-1 monitor
socket code); root-caused, fixed, regression-tested (60-socket churn), plus a loop-stall watchdog that dumps stacks.
**Verified:** 42-page audit 42/42 in Chromium and WebKit; parity vs the reconstructed pre-program UI 84/84 (logic
unchanged); web-vs-desktop equivalence audit of 328 features (reports/desktop_app/FEATURE_PARITY.md); installed-app E2E
58/58; gates core 701 · scripts 287 · ui-api 1078 · execution 7 · alpha_lab 20 · cargo 153 · node checks ~1,250 · boot
74/74. Reviews: 7 critics + 5 fix rounds + a 9-reviewer final round, every serious finding adversarially verified
(reports/desktop_app/review/). **Intentional browser-visible changes:** header HOLIDAY/MUHURAT labels, batched price-alert
notifications, first visit does not replay old alerts, visible toasts, self-hosted fonts, UPDATE DATA confirmation, 2-dp
prices, stock list only on EQS. **Owner:** open http://localhost:3000 once to migrate watchlist/pins; allow macOS
notifications for SuryaDhana; Monday 08:00 SMS-OTP login as usual. Report: reports/desktop_app/FINAL_REPORT.md.

**19 Oct ~10:30: resilience review — the 16→19 Oct outage and every flaw like it.** The stack had been dark since
Friday 07:51 (Mac mini on `sleep 1` froze when the last caffeinate ended; unclean reboot at 15:54; nothing restarted
the stack; the controller, which is the only alerter, was down with it, so the outage was silent for 3 days). Recovered at 09:53, and
Friday's NSE data was caught up. **Fixed (13 findings, `reports/resilience_review/REVIEW.md`):** LaunchAgents
(`scripts/install_launch_agents.sh`): a watchdog that starts the stack at login, restarts crashed services and Telegrams
directly, plus a caffeinate keep-awake. Controller heartbeat + missed-run counts + data catch-up after downtime. The NSE
downloader now rejects files carrying another session's date (it had cached Friday's rows as Sunday, a latent permanent-hole
bug; the poisoned file was purged live). `start` = core 4 only. ui-api `--reload` is opt-in. Paused-service markers.
tick_store overlapping-flush overwrite race. RSK tz TypeError. **MCX gold live quotes verified** (ICICI 1-min bars). 3 live
drills; 958 tests. **Owner: allow Python Desktop-folder access (macOS privacy) or the watchdog can't restart anything**, plus
autorestart, healthchecks.io ping, git remote and an off-machine backup.

**15 Oct ~20:00: INCIDENT — EOD pipeline OOM, tonight's NSE data skipped (recovered + fixed).** At 18:35 the daily
pipeline's ML-dataset rebuild (1.65 M-row `INSERT OR REPLACE` in one transaction, `duckdb_store.replace_ml_dataset`) hit
DuckDB's 1.5 GB cap. Because that step sat **second and unguarded**, the exception skipped every step after it: the NSE
bhavcopy, NSE positions, the market-monitor rebuild and the corporate calendar, so the Desk mark, the 19:20 snapshot, the
shadow and the MKT tab read 14 Oct. **Recovered at 19:45 without a restart** (inside the freeze) by running the
skipped jobs: bhavcopy 15 Oct (3,511 rows), positions, events (424), monitor rebuilt (as_of 15 Oct). **Fixed:**
`services/data-service/eod_steps.py` runs every step in order and isolated (market data first, ML build last and
non-fatal, fatal = only the Yahoo refresh); the controller gains a 🟡 WARNING alert for finished-with-failed-steps
runs; the native stack's DuckDB cap is 4 GB (`start-local.sh`; the 1.5 GB code default was sized for the old 2 GB
container). 6 new tests incl. a structural guard that the build stays last. Activation (restart + ML rebuild) runs
after the 21:15 freeze. The Desk and shadow catch up 15 Oct on tomorrow evening's runs automatically.

**15 Oct ~06:45: label review checked; v2 labels amended.** The owner-shared "Label Logic Review" audits a
file (`nse_historical_ingest.py`) that does not exist here. Its five grounds were applied to this repo's
real labels instead (`reports/ml_labels/LABEL_REVIEW_CHECK.md`). Production label (ML Engine default),
measured on this repo's data: close entry credits **+30.3 bps/trade** of unexecutable overnight gap,
**20.9%** of its UP labels fail the real ICICI cost, and P(UP) swings 24→73% by month (regime, not
selection), so it should not be used for new research. The same check exposed two deviations in the first v2 build: unclean windows
were not masked before the excess benchmark, and there was no liquidity or fillable-entry gate. Both are fixed as a dated
**Amendment 1**, made before any training: a `y_elig` + `y_elig_reason` training mask (83% trainable), 232
data-break windows removed, and the study's exact Desk-universe labels added (`y_rank_20d_desk`). Measured label
autocorrelation is 0.935, so purge ≥ 20 sessions. 10 builder tests; core 318 · ui-api 462.

**15 Oct ~05:45: feature matrix v2 (owner-approved).** `scripts/build_features_v2.py` (pre-registered spec in
the docstring) merges onto the production 73-column matrix: **excess carry** (the TESTED-ROBUST F&O signal —
cross-checked against DERV's independent implementation to 3 bp), the Desk momentum family (mom_nse, ret 6/12m, σ),
52w-high distance, RSI(2), and the four robust avoid flags (200-DMA, 52w-low, split-20d, bad-results-60d) — plus the
**v3 labels** (20-session next-open excess + rank; `y_*` = train targets, never features; leak-tested). Output:
`data/computed_features_v2.parquet` (1.65 M rows × 88 cols + manifest; built from the verified nightly backup in
17 s; ex-dividend carry strip ON). Browse: ML Engine → features-explorer `?v=2` (default v1 untouched). 7 new
definition/leak tests + explorer test; suites now core 315 · ui-api 462.

**15 Oct ~05:00: the world-class program (two agent teams).** Eight expert builders in parallel, then two
adversarial critics. **Five new pages** (42 total): CHRT chart studio (candles/EMA/BB/RSI, D/W/M + intraday-ready),
DERV derivatives desk (term structure, basis history, rollover from a derived per-expiry UDiFF panel, PCR/VIX),
OSTR options strategy builder (exact breakevens, B-76 Greeks, 8 templates, paper-only), MCXG MCX gold desk (session
clock + MCX holidays, contract specs/expiry engine, Breeze quote path with honest degrade, COMEX×INR overlay, paper
ticket), RSK risk dashboard (hist-sim VaR/ES, β, COVID/election/2022 stress replays, drawdown ladder). Plus: tick
persistence → parquet + VWAP/bars endpoints; the two slow bulk routes fixed (1.45 s → 55 ms measured); QuantLab
adoptions A1 (MC drawdown lens — **S1-gateB/S1H flag DD-FRAGILE**, read `alpha_lab/reports/mc_drawdown.md`) and A2
(Friday 20:10 decision journal). **Critics:** trader — TRADE-READY for EOD NSE cash/F&O + MCX paper, NOT yet
intraday (tick store has never seen a live session); engineering — SHIP-WITH-FIXES, bar scores up across the board
(NEVER-LIES 8/10), every defect (GO-bar search, unbounded days/2 GB ratchet, panel race, NaN ticket, Unknown-sector
chip) **fixed the same night**. Gate: 937 tests, 42/42 pages clean. Full trail: `reports/worldclass_program/`
(REPORT.md). Owner actions: **git remote** (still none!) and `LIVE_TICKS=1` for the first live session.

**15 Oct ~01:00: the Bloomberg program (analyze→design→build→test→critique).** Five parallel builders +
red-team gates, then an adversarial critic with license to break things. Shipped & verified: Breeze-websocket
**live tick engine** (lazy, kill-switched `LIVE_TICKS`, zero REST quota; CONNECTING→LIVE 3/3 subscribed in a
valid session, honest `DISCONNECTED — broker session not connected` after midnight) · bounded caches + error
contract + purity scanner (`/health` p95 0.8 ms while 4 screener scans ran) · shared 19:20 evening snapshot +
verified 02:15 DuckDB backups + restore runbook + CI · page chunk −70 % · CLAUDE.md rewritten to the real
4-process stack. Phase 4: 37/37 pages, 148/152 routes within latency bounds, 178 rps load 0 errors.
**Critic's verdict: NO (FAST 6 · LIVE 3 · NEVER-LIES 6.5 · SURVIVES 3 · SCALES 7 · DISCIPLINED 7.5)** — and it
was right twice: (1) the tick wire key (`quotes` vs the UI's `ticks`) meant the terminal could never render a
tick and the LIVE chip lit from `connected` alone — **fixed same night** (key renamed + contract-pinned test;
chips now earn LIVE from row truth; request ledger bounded; 781 tests green after); (2) **no git remote, last
commit 14 Jun, 481 files untracked — OWNER ACTION: commit + private remote + copy `.env` out-of-band.**
Full trail: `reports/bloomberg_program/` (REPORT.md is the summary; bloomberg_verdict.md is the critique);
RSCH → "Bloomberg program". To go live on prices: `LIVE_TICKS=1` in `.env`.

**14 Oct ~21:45: production review (six parallel audits).** Health 37/37 pages · 738 tests · tsc clean. Design
B+ (AI-slop A — no template smell; 72/100 token discipline; 4 HIGH findings incl. the news-pill chart overlay and
missing tabular-nums). Contract tight (0 broken frontend calls; the one real bug — /api/stocks/{t}/ohlcv opening
DuckDB inside ui-api with f-string SQL — FIXED as a data-service proxy). Duplicates: −233 LOC, two latent bugs
(ordinal 110–113, even-count median) died with their copies; dead indicators package deleted. Scale: warm routes
7–50 ms; real debts = unbounded news cache, orphaned 352 MB parquet routes, 20–28 GB/day snapshot copies (a
3.16 GB orphan removed); the "dev build in prod" alarm disproven (.next-prod dist dir, 102 kB shared JS). Operator
DevEx 5/10 — .env.example missing the 3 ICICI keys, no DB backup/restore, no CI. Full report + ranked priorities:
RSCH → "Production review" (`reports/production_review/REPORT.md`).

**14 Oct ~21:15: S1 paper shadow STARTED (owner's decision).** S1 + hedged S1H run forward from 15 Oct, in
parallel with the Desk's paper book: nightly 19:50 job replays the gated engine, Telegram messages fills and a
Friday NAV line, `/shadow` on the bot any time. Flat until the October month-end signal. Paper only.

**14 Oct night: the Alpha Lab.** A self-contained strategy lab (`alpha_lab/`) built by six parallel specialist
agents: three deterministic strategies gate-tested under a pre-registered protocol (2020–26, then 2011–19).
**S1 — momentum top-20 minus five robust avoid-flags with the crash filter — passed both gates**: 28.0%/yr
after costs 2020–26 (NIFTY 9.6%, equal-weight universe 24.2%, maxDD −16.5%) and 15.8%/yr 2011–19; full
2011–26 = 21.0%/yr. Hedged variants pass the modern window only; the 5-day leader-dip FAILS on delivery costs
(the pre-registered "stay away" verdict). New: **excess carry** — stocks whose futures trade at a discount lag
robustly — the first F&O-derived signal to pass a pre-registered bar here. Your two research documents are
reconciled claim-by-claim in `alpha_lab/reports/claims_matrix.md`. Monthly flow: `alpha_lab/run_today.py`.
Research only; nothing trades. Start at `alpha_lab/reports/FINDINGS.md`.

**14 Oct evening: every study as a probability.** One frame for all 38 conditions the studies tested, merged into
P(beat the market) and P(worst fifth), checked out of sample, plus how to label a model for short / swing / long
holds. RSCH → "Evidence → probability", or `reports/evidence_probability/FINDINGS.md`. See "Evidence → probability"
below.

**14 Oct afternoon: ICICI login from your phone works.** The account uses Google Authenticator; the login now asks
ICICI for an SMS instead and you reply on Telegram (first success 14:43). Live ICICI quotes reconnect after every
login.

**14 Oct morning: the Telegram bot.** 20 commands from your phone (`/brief`, `/book`, `/quote TCS`, `/alert …`,
`/login` …) and an ICICI login whose SMS OTP you answer in the chat. See "Telegram bot: 20 commands" below.

**Overnight (13 → 14 Oct): what you should know first**
- **Your book:** CUPID and PCJEWELLER are under NSE surveillance (ASM stage 1), now shown as ⚑ on every page.
  The book's 1-day 95% VaR is about ₹4,600. AEROFLEX's board meeting today is about expansion plans, not results.
- **Fixed, important:** results release times for 2025–26 were often a governance filing taken for the results
  (about 41% of quarters checked). The data is repaired and the results-drift study re-run (verdicts hold;
  the avoid-filter is stronger). The ⚠ BAD RESULTS flag now covers 42 stocks.
- **Fixed:** an expiring ICICI session wiped the saved holdings at 00:11. They are restored and guarded.
- **Fixed:** MKT's Nifty 500 (21,823, "0.00% today") and India VIX (14.12) were stale Yahoo values for 13 Oct; they
  now come from NSE (22,090, +1.22%; VIX 14.04).
- **Market valuation:** NIFTY's P/E is at its 1st percentile since 2021 (P/B 2nd since 2012), while the small-cap
  premium is at its 99th percentile (1.77× NIFTY's P/E).
- **New functions:**
  - MEMB (index members), SEAG (seasonality), ECO (economic calendar with NSE holidays; NSE is closed Tue 20 Oct).
  - EVTS → options into results, OMON pricer, HP (history, dividends, drawdowns), DEAL → short selling.
  - ALRT ± % move alerts, and MKT equity vs bonds.
  - The scheduler now skips session jobs on NSE holidays.
  - A Bloomberg function map of what's here and what's missing.

**New on 13 Oct evening:** market valuation against 14 years of NSE history (NIFTY's P/E is at its 1st
percentile since 2021), an economic calendar (ECO), historical prices for any stock (HP), and a fix for world
moves measured from the wrong session (KOSPI showed −8.9%, the truth was −5.5%).

**Earlier on 13 Oct (read "New (13 Oct, during the session)"):** quarterly financials from NSE's own filings
(FA, P/E, P/B, peers RV, the FUND screener, numbers on every results filing), intraday charts without ICICI,
market internals through the day, your last-known holdings priced live, hover quotes, keyboard tables, CSV on
every table, a 15:40 closing note. Fixed: two-day moves shown as "today" (Yahoo skipped a session), a stale NIFTY
on the tape, earnings-call notices counted as results, a test wiping the saved holdings.

Goal: make SuryaDhana feel like a Bloomberg terminal for NSE, fill the most important gaps, polish
everything. Each entry says what changed, where, and how it was checked.

Open the app at http://localhost:3000. Press **/** (or Ctrl/⌘+K, or **⌕ GO** at the right of the tab
strip) and type a function code or a ticker. Press **?** for every code and shortcut.

## If you have 10 minutes
1. **BRIEF**: the top strip says what needs you. In the morning it lists results filed overnight with what the
   numbers said; in session the NIFTY intraday chart and breadth take the gold slot.
2. **WTCH**: your four holdings priced live even with ICICI logged out (P&L, today's ₹ move, P/E, profit growth),
   their NSE surveillance flags (CUPID and PCJEWELLER are under ASM), and the book's risk in rupees (VaR).
3. **/ → `CUPID FA`**: twelve quarters of your holding's revenue and profit from its NSE filings, with P/E, P/B and
   peers. (It is at ~355× trailing earnings: checked, real.)
4. **EVTS**: Reacting today (move vs normal + what the numbers said), the Q2 FY27 season scorecard, and every
   upcoming company's last quarter.
5. **FUND**: screen the market on P/E, growth and margin; industry medians on top. Hover any ticker for a quote;
   click a table and use ↑ ↓ Enter.
6. **MOV** (in session): intraday index charts, who moved NIFTY (points per stock), and market internals (is the
   rally broad or narrow?).
7. **RSCH → Earnings-growth drift**: a pre-registered study whose first "pass" was a selection bias; the broad
   re-run on 1,142 companies says NO EDGE.
8. **🔔** (top right): the 08:50 morning note, the 15:40 closing note, move / filing / results-numbers alerts.
9. **MKT → Valuation · NSE**: click NIFTY, BANK, IT… to see 14 years of P/E, P/B and yield, and where today sits;
   below it, equity vs bonds. (NIFTY's P/E is at its 1st percentile since 2021.)
10. **MEMB**: NIFTY 50 member by member: weight, points today, YTD contribution, distance from the high, P/E against
    its own history. Then **ECO** for this month's data dates and holidays (NSE is shut Tue 20 Oct), and **SEAG** for
    seasonality.

## Start here: the 32 things to try

1. **BRIEF** (the landing page): everything you need before 09:15 on one screen.
2. **PRE** (from 09:00): the pre-open auction: gaps and which side of the order book is left over.
3. **MOV** (09:15–15:30): live movers, the sector board, volume surges, 52-week highs/lows and OI spurts.
4. **/ → `TCS` → Profile**: Bloomberg-style DES. Price, ownership, insiders, deals, F&O, results history, peers,
   and a trade ticket with real ICICI costs.
5. **MKT**: market regime, breadth, a heatmap of 250 stocks (live during the session), industry rotation, FII/DII positioning, movers.
   Click an industry to drill in.
6. **EVTS**: the results season calendar, a scoreboard of how the market took each result, and each stock's
   typical results-day move.
7. **OMON**: the NIFTY option chain (live in market hours) with OI walls, the IV smile, a year of IV/PCR history, and the move priced in
   by expiry.
8. **INSD**: promoter and director open-market buying (after this morning's data repair).
9. **WTCH**: your watchlist, live, with price alerts (🔔) that fire as Mac notifications even with the terminal closed.
10. **RSCH**: all 23 studies with honest verdicts, including tonight's two new ones.
11. **News (Shift+N) → TRACK RECORD**: how the news scanner's picks actually did.
12. **DEAL**: today's block and bulk deals; click a client to see everything they traded.
13. **CF**: today's company filings, live, by category (results, orders, ratings…), with your stocks highlighted.
14. **MRGN**: where retail leverage (margin-funded positions) is building, and which stocks are most crowded.
15. **HDS**: who bought and sold last quarter (mutual funds vs foreign investors vs promoters vs retail).
16. **IPO**: open issues with live subscription, and how the last 2 years of listings did.
17. **WRAP**: the end-of-day market wrap (Friday's is there; tonight's is written at 21:00).
18. **WEI**: world markets (US, Asia, Europe, FX, crude, gold, yields) before the open.
19. **Commodity → Gold desk**: the fair open is recorded at 08:45 every weekday, with an accuracy log.
20. **EVTS → Reacting today · live** (also on BRIEF): results filed since yesterday's close, today's move, and
    how big that is against the stock's usual results-day move.
21. **Any stock → Chart → ⚡ Today**: a real 5-minute intraday chart (works without ICICI), and **NIFTY intraday** on
    BRIEF (from 09:15) and MOV.
22. **Hover any amber ticker** for a quote card (price, day move, ranges, sparkline).
23. **/ → `TCS FA`**: 12 quarters of revenue and profit from NSE's own filings, P/E, P/B, and peers side by side (RV).
24. **FUND**: screen companies on P/E, growth and margin (`COMP TCS INFY` adds the same fundamentals to Compare).
25. **ALRT**: every price alert in one place (distance to each level, add / remove), what fired, and the full inbox.
26. **MOV → Who moved the index**: each stock's contribution to NIFTY / BANK / IT in points.
27. **/ → `TCS FA` → P/E history**: today's P/E against the stock's own range (point-in-time), plus dividends (DVD).
28. **ECO**: India's CPI, WPI, IIP and GDP release dates with the RBI and Fed decisions (WPI is due tomorrow at 12:00).
29. **/ → `TCS HP`**: every session as traded (OHLC, VWAP, volume, delivery %), with CSV export.
30. **MKT → Valuation · NSE**: index P/E, P/B and yield against their history since 2012; click a row to chart it.
31. **MEMB**: every NIFTY 50 member's weight, points today, returns, distance from its high, P/E and growth.
32. **SEAG** (or `TCS SEAG`): average return by calendar month and every year behind it.

**Needs you (2 minutes each):**
1. ~~ICICI login~~ **done 14 Oct 14:43** from your phone (SMS OTP via Telegram). Each weekday at 08:00 the bot
   asks for that day's SMS code. Optional: `ICICI_TOTP_SECRET` (the Google Authenticator setup key) removes even
   that step.
2. ~~**Telegram**~~ **done 14 Oct 07:32**: @SURYADHANA_bot is connected (token and chat ID in `.env`).
3. **Start after a restart:** run `scripts/install_autostart.sh` once. It adds a per-user launch agent so the stack
   starts ~20 s after you log in; `--remove` undoes it. On 13 Oct the Mac restarted overnight and nothing came
   back up until it was started by hand, so the 08:45–09:10 jobs were missed.
4. **Desk industry cap:** decide how to treat the 5 "Unknown"-industry names in the Desk's top 20. Capital Goods
   is already at 7 of the 8 allowed (DESK → Watchlist risk).

**Honest notes on the data (13 Oct):**
- **Results release times for 2025–26 were wrong for about three quarters of companies until 14 Oct, 02:45** (a
  governance filing was taken for the results). Fixed and repaired. Anything computed before then that used
  results *timing* (typical reactions, the ⚠ BAD RESULTS flag, the results-drift study's holdout) has been redone;
  the study's verdicts held. Details: "Fixed (14 Oct, 02:30)" below.
- Day changes before 16:50 on 13 Oct were wrong for most NSE stocks: Yahoo skipped 12 Oct, so they were two-day
  moves. Fixed (official NSE previous close). The 15:40 closing note and the morning's move alerts were affected; a
  correction is in the inbox.
- Quarterly financials (FA, FUND) are as filed with NSE. Q4 FY25 is missing for about 1 company in 8 (an NSE feed
  gap), EPS is not adjusted for bonuses or splits, and a few filers make typos (the share count is cross-checked).
- FUND now covers 1,832 companies (tonight's sweep finished at 22:10), 1,405 of them with a P/E-vs-own-history
  percentile. It is a screen; the related study found NO EDGE.
- ICICI is logged out, so holdings are the last known book (12 Oct 18:30) priced at live prices.

BRIEF shows these items too, as an amber **NEEDS YOU** strip at the top with the exact fix for each. It goes away
by itself as each is done (`GET /api/config/setup-status` returns yes/no and reasons, never a secret).

**Most important findings:**
- **Your book is two stocks.** CUPID (52%) and AEROFLEX (41%) are 93% of the ICICI holdings by value: it behaves like
  2.3 equal positions, with 42% volatility (3× NIFTY) and a value-weighted P/E of 116×. WTCH → Your book · X-ray.
- **Earnings-growth drift (13 Oct): NO EDGE.** Strong reported growth does not beat the market over the next 60
  sessions once every company is included (1,142 companies, delisted ones too): about +1% before costs, about zero
  after. The afternoon's "pass" (+6.4%) was selection bias, as the plan warned. RSCH has the detail.
- **CUPID** (your holding) is priced at ~355× trailing earnings and 108× book after a +635% year. That is a fact
  about the price, not a recommendation.
- **Your ICICI holdings run 3× NIFTY's volatility** (42% vs 14%, beta 1.22). See Broker → Holdings risk.
- **IPOs:** heavy institutional demand (QIB ≥ 100×) is priced in on day 1 (+36% average listing gain), and those
  stocks then lost 12% over 60 sessions from the day-1 close. Under 10× QIB they listed flat and gained 8%.
  Descriptive, in-sample. See IPO.
- **Retail leverage is rising into a falling market:** the NSE margin (MTF) book grew from about ₹1.0 to ₹1.5
  lakh crore over a year in which NIFTY fell 11% (MRGN).
- After a strong bad results reaction, stocks keep lagging (PASS). That's shown as a ⚠ BAD RESULTS flag; it is
  not a Desk rule.
- FII positioning does not predict NIFTY.
- NSE's insider feed had silently died in May. It is now repaired and alarmed.
- Our bhavcopy's prev_close is not split-adjusted. Every "move since" figure now uses adjusted closes (some
  showed fake −80% crashes before).

## New research: post-results drift (pre-registered, tonight)
Earlier research had skipped earnings drift ("no earnings dates in DB"). Exact NSE release times are now stored,
so I ran the classic test on **16,247 quarterly results of 651 stocks (2015 → Oct 2026)**. The stock list was
the top-300 traded of each year, delisted names included. The plan was fixed in `reports/results_drift/PLAN.md`
before any number existed.

| Hypothesis | Verdict | 60-session excess vs market (2015–21 / 2022–26) |
|---|---|---|
| Strong bad results (≤ −5% reaction) keep hurting | **PASS** | −3.7% (t −2.8) / −1.8% (t −2.5); corrected data 14 Oct: −2.0% (t −3.0) |
| Strong good results (≥ +5%) keep drifting up | **FAIL** (2015–21 t 1.4 < 2.0) | +2.7% / +3.6% (2022–26 t 4.0) |
| Spread good − bad | **PASS** | +7.4% / +5.4% |

**Use:** don't buy a stock within ~3 months of a strong negative results reaction (an avoid-filter, like the
bulk-deal one). The terminal now shows this as a red **⚠ BAD RESULTS** flag wherever you pick stocks: the Desk
watchlist, Watch, the stock Profile (with the details) and the EVTS scoreboard. It covers stocks whose last results
reaction was ≤ −5% vs NIFTY within 60 sessions (42 stocks after the 14 Oct release-time fix, e.g. BANDHANBNK −16%). None of the Desk's current
top 20 is flagged. It is a flag, not a rule.

**Follow-up test (also pre-registered, tonight): as a Desk rule it does nothing.** Running the Desk's own
simulator with "skip names after bad results", 2015–2026:
- the holdout CAGR was 4.30% vs 3.98%, but the drawdown was 0.01 pp deeper, so it fails the bar;
- the full-period result is essentially identical;
- only 23 names were ever blocked.

Momentum leaders rarely have bad results reactions. So: keep the flag for discretionary buys, and don't add it to
the Desk (`reports/results_filter/`). The proposed next step is to test it as a Decision Desk filter. It needs your review; no rule
was changed. Read: RSCH → "Post-results drift on NSE: findings" (`reports/results_drift/FINDINGS.md`).

## New research (13 Oct): does "what the numbers said" predict the next 60 sessions?
**Final verdict (22:11): NO EDGE.** The pre-registered broad re-run read every liquid NSE company's filings (5,785
filings, 1,142 companies, 16 since delisted). The whole sample then averages about zero against the market, so the
bias is gone. Strong growth: +1.3% (t 0.9) / +1.0% over 60 sessions, about zero after costs. H1 fails, and H3 holds
only in discovery. The addendum said the broad run decides, so the afternoon's PROMISING (below) is withdrawn
and the January forward test is dropped. `reports/earnings_growth_drift/FINDINGS.md`, `broad/REPORT.md`.

The afternoon run, kept for the record: pre-registered at 15:00 (`reports/earnings_growth_drift/PLAN.md`) before the data was assembled, run at 15:59 on
1,691 results filings from 241 companies (the FA cache after today's first sweep). **Verdict: PROMISING, not a
pass. Nothing changes.**
- Strong growth (profit ≥ +30%, revenue ≥ +10% y/y) beat the universe by +3.7% / +6.4% over 60 sessions, so H1
  passes as written. But **every** bucket beat the universe, even profit collapses (+4.7%). The companies read
  are today's liquid winners, so the comparison is biased.
- Within the sample (vs the same week's other filings): +1.3% (t 0.5) in discovery, +2.2% (t 2.8) in holdout.
  That is a possible small edge, only recent. No avoid signal for collapses.
- Forward test: Q2 FY27 filings are out-of-sample; re-run mid-January 2027. A fair test would need every listed
  company's filings (~3.5 h to read); proposed, not run. RSCH has the verdict; FINDINGS.md has the detail.

## Bloomberg function map (gap review, 14 Oct 01:45)
Where the terminal stands against the Bloomberg functions a cash-equity trader uses most. Codes work from GO (`/`).

| Bloomberg | Here | Status |
|---|---|---|
| BRIEF, TOP, N | BRF, Headlines, News (Shift+N), Profile → news | have |
| DES / FA / ERN / RV / DVD / CN / OWN | `TCS DES`, `TCS FA`, `TCS ERN`, Profile → RV, DVD, filings, ownership | have |
| GP / GIP / HP | stock window → Chart (⚡ Today = intraday, RS vs NIFTY), `TCS HP` | HP 13 Oct, RS 14 Oct |
| DDIS-style drawdowns | HP → max drawdown (dates) and current drawdown | added 14 Oct |
| TRA (total return) | HP → "with dividends" | added 13 Oct |
| SEAG (seasonality) | `SEAG`, `TCS SEAG` | **added 14 Oct** |
| MEMB (index members) | `MEMB` (NIFTY 50 / NEXT 50 / BANK / IT) | **added 14 Oct** |
| WEI / IMAP / MOV / MOST | WEI, MKT map, MOV | have |
| ECO / ECOS | ECO (dates from MoSPI, DPIIT, RBI, Fed) | added 13 Oct; no consensus or actual figures (no free source) |
| Index valuation (EQRV-style) | MKT → Valuation · NSE (14 years, vs own history, vs NIFTY, vs bonds) | added 13–14 Oct |
| EQS / screening | FUND, EQS | have |
| OMON / OVME | OMON (chain, IV smile, OI walls) + pricer (click a price) | pricer added 14 Oct |
| PORT / risk | WTCH book X-ray, basket risk (vol, beta, drawdown, VaR/ES in ₹), PORT (paper) | VaR added 14 Oct |
| ALRT | ALRT, 🔔 (price levels and ± % day moves) | move alerts added 14 Oct |
| EVTS / CACT / IPO | EVTS, DVD, IPO | have |
| Flows (FII/DII, deals, insiders, margin) | BRF, DEAL, INSD, MRGN, HDS | have (India-specific, beyond Bloomberg's defaults) |
| Exchange risk flags (India: ASM/GSM/ESM, bands, F&O ban) | ⚑ chips on WTCH, BRIEF, DESK, stock window; OMON ban list | added 14 Oct |
| SI (short interest) | DEAL → Institutional short selling | added 14 Oct (short-sale flow; NSE doesn't publish outstanding shorts) |
| EE / ANR (estimates, ratings) | none (EVTS → Options into results gives the market's priced reaction instead) | **missing: no free source** |
| GC / WB (yield curves, bonds) | MKT → Equity vs bonds (10Y monthly, ~3 months late); WEI G-sec price index | partial: no free daily India yield curve |
| MA / SPLC (M&A, supply chain) | none | missing: no free source |
| Launchpad (custom layouts) | WTCH + pins | partial |

## New (14 Oct, overnight)

### SEAG: seasonality for any index or stock (GO: `SEAG`, `TCS SEAG`, or the SEAG tab in the stock window)
Average return by calendar month, how often each month was up, and the year × month heatmap behind it (with each
calendar year's return). The current month is shown "so far" and kept out of the averages.
- Indices use NSE's own closes since 2012 (the valuation backfill); stocks use split- and bonus-adjusted closes
  (TCS since 2010).
- NIFTY 50 over 15 years: February is the weakest month (−1.5%, up 36% of years) and July the most reliable
  (+2.3%, up 73%); October so far is +0.5%. That describes the past, not a forecast: each month is only 14–15
  observations.
- `/db/seasonality` (`services/data-service/seasonality.py`), tested in `tests/unit/test_index_valuation_history.py`.
  An index that isn't in the history (e.g. NIFTY 100) answers with the list of indices that are.

### Book risk in rupees: 1-day VaR and expected shortfall (WTCH → Your book · risk, DESK watchlist risk)
The risk row adds a historical **1-day 95% value-at-risk**, the average loss on the worst 5% of days (expected
shortfall) and the worst day, all against NIFTY. On WTCH it is in rupees, using the book's live value.
- Your book (last 12 months, value-weighted): VaR −3.4% ≈ ₹4,600 a day, the worst 5% of days average −5.4%
  (≈ ₹7,300), worst day −9.1%. NIFTY: −1.6% / −2.0% / −3.3%. The same story as the 42% volatility, in rupees.
- Historical VaR uses an observed day (`interpolation="lower"`): the default blended the 5th-worst day with a gain
  and can come out *negative* on short or lumpy data (caught by the test). `basket_risk.tail_risk`, tested.

### BRIEF: "New since your last visit" strip
A cyan strip at the top of BRIEF has one chip per new function: MEMB, SEAG, ECO, the MKT valuation history,
`TCS HP`, the OMON pricer, and this log. **✕ GOT IT** hides it until the next release (remembered in this browser).

### OMON → option pricer (Bloomberg OVME): click any call or put price in the chain
A panel prices that contract with Black-76 on the chain's forward, the same model and conventions OMON's
implied vols use (r 6.5%, calendar days + ½ for the expiry session).
- It shows model vs market price and the Greeks (Δ, Γ, θ per day, vega per vol point), plus breakeven, the chance of
  finishing in the money (risk-neutral), the cost and delta exposure of one lot, and the payoff of one long lot at
  expiry and today.
- IV and days are editable for what-ifs. In-the-money strikes take the IV of the other side at the same strike
  (put–call parity), because OMON computes IV only out of the money.
- Check: NIFTY 22,700 CE (19 Oct) prices at ₹207.76 against ₹207.20 in the market; the 22,700 PE at ₹105.61
  against ₹105.05. The gap is IV rounding. The maths (`ui/lib/black76.ts`) matches scipy to 6 significant figures.
- **Fixed:** after the close on an expiry day, OMON opened on the series that had just settled (0 days left). It now
  moves to the next expiry and says so; the settled series stays one click away.

### EVTS → Options into results (Bloomberg-style implied earnings move)
For every F&O stock reporting in the next 10 days, the panel shows the move its options price by the first expiry
after the results, the part attributable to the **results day**, and the stock's **usual results-day move** (last 8
quarters).
- **The results-day part** uses the options' term structure: the variance between the first two expiries gives the
  normal-day volatility; what is left in the front expiry is the event. That event σ × 0.8 gives an expected
  absolute move, comparable with the usual reaction. Where the second expiry isn't usable it falls back to 60-session
  realised volatility, and says so.
- **Calibrated:** across 51 names this week the median ratio (priced ÷ usual) is **1.00**. So stand-outs are the
  useful bit: today HDFCLIFE (2.4×), JIOFIN, CANBK (2.1×) and LTF price much bigger reactions than usual. Before the
  release-time fix the median looked like 1.3×, because "usual" moves were understated (measured on governance-filing
  days); this panel is what exposed that bug.
- `/db/results-implied-moves` (`option_chain.implied_event_move_term`, tested); maths checked against a constructed
  example. It describes what options charge, not the direction.

### DEAL → Institutional short selling (Bloomberg SI-style)
NSE publishes institutional short sales every evening (stock and quantity, no client names). They were stored but
only summarised inside each stock's Profile. DEAL now ranks the whole market over 5, 20 or 60 sessions: shares
shorted, **as a share of all shares traded** in the window, the number of days with a disclosure, the last one, and
the price move over the window. ⤓ CSV exports it.
- Last 20 sessions: 588 stocks had short sales. HEROMOTOCO stands out: about 10% of all shares traded were sold
  short, on 11 separate days (price −3.3%).
- Context, not a signal: this is the flow of short sales, not the outstanding short position (NSE doesn't publish
  that). `/db/short-selling` (`deals_monitor.short_selling`, tested).
- The 21:00 wrap's *Money flows* adds persistent short selling of the last 5 sessions: at least 1% of volume on
  at least 2 days (tonight that would be "IREDA 1.1% of volume (4 days)").

### MEMB: index members (GO: `MEMB`)
For NIFTY 50, NEXT 50, BANK or IT, one row per member:
- the rebuilt free-float weight (with a bar) and today's move and index points;
- returns over 1M, 3M, YTD and 1Y, and the distance from the 52-week high;
- P/E plus profit and revenue growth from the member's latest NSE filing.

On top: breadth, top-5 concentration (36% of NIFTY in five stocks), members near their highs, and a
**weight-implied P/E** (18.5×, from 99% of the weight). That cross-checks NSE's published 19.4×. ⤓ CSV exports
the table.
- **YTD attribution:** a "YTD pts" column gives each member's contribution to the index's year-to-date move
  (weight × YTD return). The "Year to date" box sets NSE's actual YTD against what the members explain. NIFTY 50:
  −13.0% actual, members explain −10.0, led by HDFCBANK −2.8, RELIANCE −1.9 and INFY −1.1. NIFTY IT: −21.3%
  actual, −19.8 explained, of which INFY −11.4 and TCS −5.9. It uses today's weights, so stocks that fell count
  for less than they did in January, and it understates the move.
- A **P/E vs own** column shows each member's P/E percentile within its own point-in-time history (the same
  number FUND uses), so "cheap against its own past" is visible member by member.
- `/db/index-memb` (named so it does not clash with MOV's live `/db/index-members` drill-down).
- Fixed while building it: the "last quarter" was read from the wrong end of the filings cache (newest first).
- MOV → Who moved the index links to it ("all members · MEMB ›").

## New (13 Oct, evening)

### Market valuation against its own history, since 2012 (MKT → Valuation · NSE, BRIEF, WRAP)
NSE's daily index files have P/E, P/B and dividend yield for every index. I backfilled 3,617 sessions (Feb 2012 →
today, 13 indices; the CNX-era names before 2016 are mapped to today's). The MKT valuation panel now has:
- a **P/E vs history** column: today's percentile and the median;
- a weekly history chart of whichever index you click, with **P/E · P/B · Div yield** toggles, the median, the
  middle half (shaded), and a hover readout.

**The basis break, found in the data and handled:** on 31 Mar 2021 NSE moved index P/E and yield to consolidated
figures. NIFTY's P/E fell from 40.4 to 33.2 overnight with the index flat. P/B did not change. So P/E and yield
percentiles compare today only with days since 31 Mar 2021; P/B uses all 14 years. The chart shows the break as a
dotted line.

**What it says tonight (13 Oct close):**
| | Now | Percentile | Median |
|---|---|---|---|
| NIFTY 50 P/E | 19.4× | **1st** (since Mar 2021) | 22.1× |
| NIFTY 50 P/B | 2.79× | **2nd** (since 2012) | 3.49× |
| NIFTY 50 dividend yield | 1.51% | highest since Mar 2021 | 1.28% |
| NIFTY IT / BANK / FMCG P/E | 18.5× / 13.2× / 31.0× | 2nd / 4th / 0th | 27.4× / 16.1× / 42.0× |
| PHARMA / SMALLCAP 250 P/E | 40.3× / 34.4× | **96th / 90th** | 33.6× / 28.9× |

Large caps are the cheapest they have been since June 2022 on NSE's own numbers, while small caps and pharma are
near their highs. This describes valuation only: cheap markets can get cheaper, and nothing here is a signal or
changes the Desk.
- BRIEF's valuation line adds "(1st percentile since 2021)". The 21:00 wrap prints the percentile and the median.
- Loss years send some sector P/Es into the thousands (REALTY reached 23,308×). The tooltips therefore show the
  band covering 90% of days instead of min–max, and those charts clip their axis (and say so).
- `scripts/backfill_index_valuation.py` (incremental) → `data/nse_archive/derived/index_valuation_history.csv`;
  `/db/index-valuation` (vs_history) and `/db/index-valuation-history?index=&metric=`. NSE serves these files only
  from mid-2012. Test: `tests/unit/test_index_valuation_history.py`.
- **Relative valuation (added 14 Oct):** a "vs NIFTY P/E" column gives each index's P/E ÷ NIFTY 50's and that
  ratio's percentile since Mar 2021 (the chart has the same as a fourth toggle, **P/E vs NIFTY**). Tonight:
  **Smallcap 250 at 1.77× NIFTY, the 99th percentile** (median 1.26×), and **Pharma at 2.08×, also 99th**, while
  IT (8th), FMCG (10th) and Next 50 (12th) sit at the cheap end. So large caps look cheap while the small-cap
  premium is near its record. BRIEF and the wrap mention a premium or discount only when it is stretched (≥ 80th
  or ≤ 20th percentile). `relative_vs_history` (tested).
- **Equity vs bonds (added 14 Oct):** a second MKT panel charts NIFTY's earnings yield minus India's 10-year
  bond yield, monthly since 2012 (the "Fed model"). The bond yield is the OECD monthly series on FRED, about three
  months late: no free daily India 10-year yield exists. July 2026: earnings yield 4.83% − 10Y 6.78% = −1.95
  points, the **88th percentile** of months since the basis change. So equities are relatively cheap against
  bonds, consistent with the P/E reading. Context, not a timing signal. `/db/yield-gap` (`yield_gap.py`, tested).
- It stays current on its own. A new scheduler job, **index_valuation_daily** (19:15 Mon–Fri, on SYS), adds each
  day's row (`backfill_index_valuation.py --recent 10`: no database copy, and a holiday is just a miss).

### Fixed (14 Oct, 02:30): results release times for 2025–26 were often a governance filing, not the results
Found while checking a suspicious "usual results move" (ETERNAL ±0.7%, a stock that moves 5–10% on results).
- **Cause:** since April 2025 NSE's results feed is SEBI's *integrated filing*, which lists each quarter's
  **Governance** filing (due ~2 weeks after quarter-end) besides the **Financials** one. The parser kept the
  earliest broadcast of any type, so the governance filing, one to two weeks before the results, became the
  "release". For ETERNAL Q1 FY27: recorded 14 Jul, actual 22 Jul.
- **Scale:** against the results filings' own timestamps (FA cache), 2,740 of 6,739 quarters (41%; 556 companies)
  were early by more than a day, all in 2025–26. Before 2025: none.
- **What it touched:** EVTS's results scoreboard and "usual reaction" figures, the ⚠ BAD RESULTS flag, the
  post-results-drift study's 2022–26 holdout (its 2015–21 discovery is unaffected), and tonight's options-into-
  results panel. Not affected: FA, FUND, the earnings-growth study (they use the filing times), and the
  live filings feeds (CF, reacting today).
- **Fix:** the parser keeps only "… Financials" rows (test with the real ETERNAL rows). The stored rows were
  re-read for the 619 affected companies in a new *replace* mode, needed because the normal update keeps the
  earliest time and would have preserved the wrong dates. A backup of the old table is in the session scratchpad.
- **Result:** mismatches fell from 41% to 1.7%. The rest are the FA cache holding a later, revised filing; the
  results time is the right one there (e.g. SUNPHARMA Q1 FY25 on 1 Aug 2024).
- **The study, re-run on corrected data** (`reports/results_drift/corrected_2026-10-14/`): all verdicts stand and
  the avoid-filter got stronger. After strong bad news the holdout 60-session excess is −2.04% (t −3.03), was
  −1.82% (t −2.50). Good-news drift still fails discovery, and the spread holds (+5.39%, t 3.50).
- **The ⚠ BAD RESULTS flag** now covers 42 stocks (was 10). Most July–August bad reactions had been measured on
  the governance-filing day and missed; POWERINDIA dropped off (its "reaction" was an ordinary day).
- **EVTS results scoreboard:** before the fix it showed 30 "results" in the last 10 days, of which 22 (IRFC,
  UNIMECH, FSL…) were governance filings. It now shows the 8 real ones; RBLBANK carries ⚠ BAD RESULTS.

### Chart: relative strength vs NIFTY (stock window → Chart → RS vs NIFTY)
A toggle in the chart toolbar overlays the stock's close ÷ NIFTY 50's close, rebased to 100 at the start of the
visible window (rising = beating NIFTY, the Bloomberg GP relative chart). TCS over one year ends at 83.8,
consistent with −23% for the stock against −10% for NIFTY. Daily periods (5D–5Y); it has its own scale so the
candles are untouched. NIFTY daily closes come from `/db/index-daily`.

### NSE surveillance flags everywhere you look at a stock (⚑ chips)
**Two of your four holdings are under NSE surveillance, and the terminal didn't say so:** CUPID is under
*long-term ASM, stage 1*, and PCJEWELLER under *short-term ASM, stage 1*. ASM means higher margins and closer
exchange scrutiny, and a later stage can mean trade-to-trade settlement or a tighter price band.
- Source: NSE's three free daily files. The surveillance indicators give GSM, long- and short-term ASM, ESM,
  insolvency (IRP), pledge, loss-making and trade-to-trade. The price-band list catches 2% and 5% circuits. The
  F&O ban list is for the next session (14 Oct: AMBUJACEM, KAYNES). Market-wide today: 229 stocks under ESM, 134
  under long-term ASM, 78 short-term ASM, 74 GSM, 56 IRP.
- Shown as ⚑ chips (red = serious: GSM, ESM, IRP, stage ≥ 2, a 2% band, trade-to-trade or F&O ban; amber = ASM
  stage 1 or a 5% band), with the reason on hover. They appear in WTCH, BRIEF's holdings lines, the DESK
  watchlist and the stock window header. OMON lists the day's F&O ban and warns when the chosen underlying is
  banned.
- **Every ticker in the app** (the amber links on DEAL, MOV, INSD, EVTS, CF, IPO, hover cards…) carries a small ⚑
  when the stock is flagged: red for serious, amber otherwise, with the flags on hover. One shared fetch of all
  flagged stocks, refreshed every 30 minutes.
- **FUND** marks every flagged company with ⚑ and has a **⚑ HIDE SURVEILLANCE** toggle (remembered), so screens can
  exclude them; 861 NSE stocks carry at least one flag (`/db/surveillance?all_flagged=true`).
- The 08:50 note reports **changes** on your holdings: a new flag, a later stage, one dropped. Today's first run
  will list the two ASM flags.
- `services/data-service/surveillance.py` (files kept under `data/nse_archive/surveillance/`), `/db/surveillance`;
  tests `tests/unit/test_surveillance.py` (real file layouts) and `scripts/tests/test_move_alerts.py`. Context,
  not a signal: no Desk rule changes.

### ALRT: "move ± %" alerts on any stock
Besides price levels (above / below), an alert can now fire when a stock **moves ± X% on the day**, measured against
NSE's official previous close, up or down, once (one-shot like the others). It is checked every minute in market
hours by the scheduler, with the terminal closed too, and arrives like a price alert: "TCS +6.8% today (alert at
±3%, now ₹2,269.30)". Set it on ALRT ("Move ±%"); setting price levels from WTCH's 🔔 keeps an existing move level.
Tests: `services/ui-api/tests/test_price_alerts.py`.

### Board meetings say what they are about (BRIEF, every event badge, the 08:50 note)
Your holding AEROFLEX has a board meeting today. The terminal showed only "BOARD MTG", because when an event was in
both NSE feeds the merge kept the board feed's boilerplate ("…has informed the Exchange about Board Meeting…").
It now keeps the specific line from NSE's calendar: **"To consider and approve the Company's expansion plans,
including further capacity enhancements."** That text is under the stock in BRIEF's *Your stocks*, on hover over
every event badge, and in the morning note ("AEROFLEX (board meeting: Company's expansion plans…)"). It is not a
results meeting. Tests: `test_markets_research.py`, `test_move_alerts.py`; the note test also caught a missing
import that would have stopped the 08:50 note.

### Fixed (14 Oct, 06:55): MKT and BRIEF used stale Yahoo index closes for 13 Oct
- **Nifty 500:** the market monitor (regime trend check, MKT's index box, BRIEF's market panel) showed
  **21,823, "0.00% today"** for 13 Oct. Yahoo's ^CRSLDX had no 13 Oct bar when the evening snapshot was built, so
  the previous close was carried. NSE closed it at **22,090 (+1.22%)**. The monitor now takes Nifty 500 from NSE
  (the daily index-file history plus NSE's live index feed after the close) and falls back to Yahoo only if NSE
  can't supply the session.
- **India VIX:** stored as 14.12 (a Yahoo intraday snapshot) against NSE's official close of **14.04**, which is
  why BRIEF and WEI disagreed. After each Yahoo refresh the EOD pipeline now writes NSE's official NIFTY 50 and
  VIX closes for the session (`_nse_official_index_closes`; also `POST /jobs/nse-index-closes`). 13 Oct is
  corrected.
- The regime score is unchanged (0/4; Nifty 500 is still below its 200-day average).

### Telegram connected (14 Oct, 07:32)
Alerts now also go to Telegram (@SURYADHANA_bot): the 08:50 pre-market note, the 15:40 closing note, price and ±%
move alerts, filings and results numbers for your stocks, the 21:00 wrap, and job failures. The token and chat ID
are in `.env` (git-ignored).
- **Fixed while connecting:** the sender used Telegram's Markdown and never checked the reply. Telegram rejects
  Markdown with a stray `_` or `*` ("can't parse entities"), as in job names like `results_capture_daily`, so
  those alerts would have been dropped silently (confirmed against the API). It now resends as plain text and
  logs any other rejection. Test: `scripts/tests/test_move_alerts.py`.

### Evidence → probability (14 Oct, evening)
You asked for every study's pass / fail as a probability, merged into buy / sell, plus how to label a model.
`scripts/evidence_probability_study.py` (pre-registered plan, ~90 s), findings in `reports/evidence_probability/`.

**The probability map:**
- A liquid stock beats the market over 20 sessions ~45% of the time.
- Flags move that by a few points:
  - momentum top decile 49%; strong good results 49%;
  - high volatility 41%, with a 32% chance of the worst fifth (vs 20%);
  - below the 200-day and near the 52-week low are robust negatives.
- Short-term (5-session) flags:
  - split / bonus ex-dates and upside value-area breaks are robust negatives;
  - fresh bad results: only 39% of these stocks beat the market;
  - RSI(2) dips in momentum leaders are a robust positive.
- Most flow data (bulk deals, insider, F&O build-ups, MTF, delivery, shareholding) has no reliable effect in liquid
  stocks. The retail bulk-buy effect has faded since 2024.

**The merge:**
- The logistic merge ranks about twice as well as momentum alone and is calibrated out of sample: it said 33%,
  and 32% happened.
- **Desk veto:** it beat the Desk in both periods (+0.9 and +1.4 points a year) with the same turnover; shadow it
  before any change.
- **By holding period:** the BUY vs AVOID gap pays its costs at 60 sessions (3.3–3.5% vs 0.96%), is about
  break-even at 20 and loses at 5.

**Labels:**
- Next-open excess vs the universe, ranked per date, with horizon = holding period.
- Prefer 20 sessions for the Desk veto and 60 sessions for buy / sell probabilities.
- Short term: meta-labels on a defined setup only, and not on delivery costs.

**Fixed during the study:**
- The first run's merged model used three coverage flags chosen with hindsight (stocks fetched because they are
  liquid today) and rewarded membership.
- They are now neutralised at prediction. The first run is kept in `first_run_coverage_leak/`.
- Test: `scripts/tests/test_evidence_probability.py` (7 tests).

**Data note:** after your ICICI login, ICICI reported no holdings. A second empty read at 15:13 replaced the saved
book, as designed. The 12 Oct book (CUPID, AEROFLEX, PCJEWELLER, SYNCOMF) is kept in
`data/backups/last_holdings_before_icici_empty_2026-10-14.json`. Tell me if you still hold them.

### Telegram bot: 20 commands, and ICICI login with the OTP from your phone (14 Oct, 08:30)
The bot now answers you, not only alerts. It runs inside master-controller (long poll, no open port) and answers
only your chat. Type `/` in the chat for the menu; `/help` sends the full list. Code: `scripts/telegram_bot.py`
(commands + formatting), `scripts/master_controller.py` (poller, login/password/status actions).

| Command | What it does |
|---|---|
| `/brief` | market + your book + today's events in one message |
| `/market` | NIFTY / BANK / VIX, Nifty 500 breadth, regime, NIFTY P/E percentile |
| `/book` | each holding: price, today, P&L, ⚑ surveillance; totals (last-known book if ICICI is offline) |
| `/quote TCS` | price, day range, 52-week range, P/E, profit growth, next event |
| `/movers` · `/results` · `/events` | top F&O movers · results filed since the close (revenue/profit y/y, usual move) · this week's events, holidays, data |
| `/flags` · `/valuation` · `/desk` · `/wrap` | ASM/GSM flags on your book · index P/E vs history · Decision Desk · latest wrap |
| `/alerts` · `/alert TCS above 2400` · `/unalert TCS` | list / set (above, below, move %) / remove alerts |
| `/status` | services, ICICI session, data dates, next scheduled jobs |
| `/login` · `/otp 123456` | ICICI login now; reply with the SMS digits (or `/otp`) |
| `/userid …` · `/password …` | change the ICICI user ID / password in `.env`; your message is deleted at once |

**ICICI login, fully from the phone:**
1. The script fills the user ID and password from `.env`.
2. ICICI texts the OTP. The bot messages "🔐 an OTP was sent to your phone ending 86…".
3. You reply with the 6 digits, or paste the whole SMS. The script submits them and saves the session (it
   waits up to 5 minutes).

The 08:00 job does the same, so each morning is: the SMS arrives, you reply. Tests:
`scripts/tests/test_telegram_bot.py`, `test_bot_login_guard.py`, and `tests/integration/test_icici_login_browser.py`
(SMS path against a copy of ICICI's page in headless Chrome).

**Credentials:**
- Until 08:19 `.env` held user ID AD…94 with a 6-digit PIN. ICICI rejected that pair on 12 Oct and again today at
  08:16 ("Invalid Credentials").
- At 08:19 you changed the user ID by `/userid` (88…86) with the same PIN. ICICI accepted it and sent the OTP.
- The login page reads "Password / PIN", so a PIN is valid. The 13 dots in the old failure screenshot are ICICI's
  own `************` placeholder written after submit, not a typing error.

**Why no OTP ever came (fixed 14:40, first successful phone login 14:43):**
- Your ICICI account uses **Google Authenticator**. After the user ID and PIN, ICICI shows "Verify TOTP: use your
  Google authenticator app…", and texts an OTP only after "Having issues? **Verify with OTP**" is clicked.
- The login never clicked it, yet the bot said "an OTP was sent", so you waited for an SMS that never came.
- Now, without `ICICI_TOTP_SECRET`, the login clicks "Verify with OTP" (`goforotp()`), waits for ICICI's SMS panel,
  and only then asks you on Telegram.
- Verified live: SMS at 14:42, your reply, logged in at 14:43. The test copy of ICICI's page now has the real
  TOTP panel and link (2 new tests).
- **Zero-touch option:** put the authenticator's setup key in `.env` as `ICICI_TOTP_SECRET` and the login
  generates the code itself, with no SMS and no reply. The key is shown once when TOTP is set up in ICICI Direct; to
  get it again, reset TOTP in ICICI and add the new key to both Google Authenticator and `.env`.

**Guards:**
- `/login` refuses a user ID + password that ICICI already rejected, because repeated failures can lock the
  account. `/login anyway` overrides.
- `/password` with the value that was already rejected says so instead of "updated".
- One ICICI login at a time: the scheduled one and `/login` share a lock. A second login would text another
  OTP and invalidate the first.
- A controller restart on a trading morning checks the session, but does not ask for another OTP within 30
  minutes of the last ask (`--quiet-minutes 30`, `data/icici_otp_last_ask.json`).
- `/status` shows when a login is waiting for your code. The alert after an OTP timeout says "send /login",
  not "change the password".

**Fixed, important: every Breeze call could hang for minutes.** `breeze_connect` downloads ICICI's 3 MB
SecurityMaster.zip when it is imported and again inside `generate_session`, the first time with no timeout. This
morning ICICI's file server crawled, so the 08:00 login, `/login` and the holdings call behind WTCH, BRIEF and
`/book` all hung (open positions took over 2 minutes).
- `shared/breeze_cache.py` now serves the archive from `data/cache/breeze/`: refreshed at most every 20 h,
  downloads capped at 2 minutes, a stale copy used rather than waiting.
- It is installed before every `BreezeConnect` import (9 places).
- Open positions now answer in 0.02 s and the token check in 0.7 s. Test: `tests/unit/test_breeze_cache.py`.
- The bot's `/book` falls back to `data/last_holdings.json` if ui-api doesn't answer.

### WRAP: right headlines, surveillance on your stocks (14 Oct, 07:05)
- The wrap looked up stock news by ticker alone, so AEROFLEX matched a story about the "Andover-Aeroflex Airport".
  Without a company name, the news lookup now uses the full name from the symbol directory ("Aeroflex Industries"),
  so tonight's wrap reads "Aeroflex Industries Stock Rallies 13% Ahead of Expansion Decision".
- *Your stocks* lines list NSE surveillance flags ("CUPID … NSE surveillance: ASM LT 1").
- The 13 Oct wrap was revised at 07:07 with the corrected results times (RBLBANK's ⚠ flag, four after-close filers)
  and VIX 14.04. Note: regenerating a *past* day's wrap loses the parts that need live data (index moves,
  valuation, GIFT, holdings' day moves), so those lines were restored from the 21:01 / 21:53 versions by hand.
  Regenerate a wrap only on its own evening.

### Errors read like sentences (all proxied pages)
42 ui-api proxy routes passed data-service errors through as raw text, so an error box showed
`{"detail":"TCS1 is not in the NSE bhavcopy"}`. They now unwrap the upstream message
(`routers/_upstream.upstream_detail`, tested). `ErrorBox` also renders FastAPI validation errors (a list of
objects, which React cannot render and would crash on) as plain text. Probed: unknown stocks, bad symbols and
out-of-range windows all give a clean 404 or 422 with a readable reason.

### Fixed (14 Oct, 01:50): the saved holdings were wiped by an expiring ICICI session
At 00:11 a session about to expire answered "success" with **no holdings**, and the saved last-known book (CUPID,
AEROFLEX, PCJEWELLER, SYNCOMF, read 12 Oct 18:30) was replaced by an empty one. BRIEF, WTCH, alerts and the wrap
would have shown no stocks.
- Restored the book exactly as last read (12 Oct 18:30); the empty file is kept in the session scratchpad.
- Guard (`positions._remember_holdings`): an empty read no longer replaces a non-empty book. Overnight it is
  ignored; in the day (09:00–23:00) it takes a second empty read ≥ 30 minutes later, so a real sell-out still
  registers. Tests: `services/ui-api/tests/test_remember_holdings.py`.
- If you did sell everything on 13 Oct, the next ICICI login corrects this by itself.

### Small fixes (13 Oct evening)
- Percentiles read "1th", "2th" and "22th" on BRIEF, FUND, COMP, the Profile and MKT, and in the wrap. They now
  read 1st, 2nd and 22nd (`ordinal()` in the terminal kit and in `daily_wrap.py`, tested).
- Tonight's wrap was regenerated at 21:53 with the valuation percentile and tomorrow's WPI release.
- Stock window header: with an event badge (e.g. TCS's dividend tomorrow), the MCAP · P/E chip ran under the ☆ PIN
  button. The title row now wraps.

### ECO: economic calendar (from GO: `ECO`, BRIEF → MORNING PAGES, or WEI → FULL CALENDAR)
India's official data releases with the RBI and Fed decisions, in IST: CPI, WPI, IIP, the core-industries index
and GDP. Each has a line on why it matters, the last 30 days are greyed out, and the next four sit in cards on top.
- Dates come from the published calendars, not guesses. CPI, IIP and GDP are taken date by date from MoSPI's
  Advance Release Calendar 2026-27 (updated 25 May 2026). WPI (14th, 12:00) and core industries (20th, 17:00)
  follow DPIIT's fixed-day rule. A release planned on a weekend moves to the next working day, which matches what
  happened: August CPI came out on Mon 14 Sep. Stored in `data/reference/india_data_calendar.json` with source
  links; it runs to 31 Mar 2027, and MoSPI publishes the next year's calendar around February.
- The Fed time is converted to IST: 23:30 in US summer time, 00:30 the next day in winter.
- BRIEF shows a **Data this week** line (e.g. `WPI Sep tmrw 12:00 · CORE Sep in 7d · IIP Sep in 15d`). The 08:50
  morning note adds "data today: …", and the 21:00 wrap's *Tomorrow* section lists the next day's releases.
- Limits: there are only dates, with no consensus forecasts (there is no free source for those). Gazetted holidays
  aren't known, so a release planned on one shows a day early.
- **NSE market holidays** (NSE's holiday master, weekdays only) appear as CLOSED: Dussehra Tue 20 Oct,
  Diwali-Balipratipada Tue 10 Nov, Guru Nanak Jayanti Tue 24 Nov. They show in ECO, the EVTS calendar and BRIEF's
  week line, and on a holiday the 08:50 note opens with "NSE CLOSED TODAY (…)". Government releases are *not*
  moved by NSE holidays, because the calendars differ: MoSPI published CPI on 14 Sep, an NSE holiday. `/db/market-holidays`.
- **The scheduler now knows about exchange holidays.** On an NSE holiday it skips the pre-open capture, price
  alerts, move alerts, market internals, the 15:40 closing note and the 21:00 wrap (each logs one "skipped: NSE
  closed today (…)" line). Otherwise, on Tue 20 Oct (Dussehra), the closing note and the wrap would have presented
  Monday's session as Tuesday's. If the holiday list can't be read, the jobs run as usual (fail open).
- BRIEF's header knows too. On a holiday it reads "NSE closed today (Dussehra) · next session Wed 21 Oct"; after the
  close before a holiday it adds "tomorrow is a holiday (…): next session …"; at weekends it names the next session.
- EVTS's five-week calendar marks the same releases in each day (◆ WPI 12:00, ◆ IIP 16:00, ◆ FED 23:30…), so
  results and macro data are planned on one screen (added 14 Oct).
- Tests: `services/ui-api/tests/test_eco_calendar.py` (weekend move, validity end, Fed IST times, reference file),
  `scripts/tests/test_move_alerts.py` (morning note).

### HP: historical prices for any stock (GO: `TCS HP`, or the **HP** tab in the stock window)
Every session in a window you choose (1M, 3M, 6M, 1Y, 3Y or 5Y), straight from the NSE bhavcopy: open, high, low
and close as traded, VWAP, volume, ₹ value, number of trades and delivery %. ⤓ CSV exports it.
- The day's change, the period return and the high and low use split- and bonus-adjusted closes, so an ex-date
  (marked ◆, with the ratio) is not a fake crash.
- Amber volume means over 2× the window average; green delivery means well above the window's average delivery.
- Ex-dividend days are marked **D ₹x** (NSE corporate actions). The summary adds the **total return with
  dividends reinvested** on each ex-date, before tax. TCS over one year: price −24.5%, with dividends −21.5%
  (₹111 a share paid).
- The summary also shows the **maximum drawdown** inside the window, with its peak and trough dates on hover, and
  how far the stock is below that peak now. TCS over one year: −40.4% (22 Dec → 1 Jul), now −31.8%.
- `GET /api/stocks/{ticker}/history?days=` → data-service `/db/security/{symbol}/history` (`security.history_rows`).
  Test: `tests/unit/test_security_profile.py` (a 1:1 bonus reads +0.99%, not −50%).

### Fixed: world-market moves measured from the wrong session (WEI, BRIEF cues, morning note)
WEI showed KOSPI **−8.91%** on 13 Oct; the real move was **−5.46%** (6,384 → 6,035). Yahoo leaves today's
daily bar without a close, and the code then took the bar *before* yesterday as "previous". The previous close is
now the last session before the live price's own session (`news_scanner._quote_from`). Every quote also carries
`prev_date`. When a change spans more than one weekday, WEI says so under the number (USD/INR shows "since Fri":
Yahoo has no 12 Oct bar for the rupee, so its −1.6% is Friday to Tuesday). Tests:
`services/ui-api/tests/test_quote_prev_close.py`.

## New (13 Oct, during the session)

### Results · reacting today (EVTS and BRIEF)
HCLTECH reported after Monday's close and was up ~5% on Tuesday morning, but the results scoreboard only scores a
reaction after the nightly capture. Now results filed since the previous close (after 15:30, or today) are priced
live: today's move, the move vs NIFTY, and the size against the stock's own average results-day move over its last
8 quarters. On 13 Oct at 10:15: RBLBANK −5.7% (2.2× its normal ±2.5%), HCLTECH +4.9% (1.4×), INDIANB +2.6% (1.3×).
- It knows the time of day. Before 09:00 it reads "results since the last close · react at 09:15" and lists what
  the numbers said (yesterday's price change is not a reaction). 09:00–09:15 uses the pre-open auction price.
  In session it shows the live move. A filing after today's 15:30 close says "reacts next session".
- ui-api `GET /api/market/results-reacting` (cached 60 s): NSE announcements (results category) + NSE heatmap quotes,
  Yahoo for the rest; data-service `GET /db/typical-results-moves?symbols=` (from `nse_results` reactions).
- Tests: `services/ui-api/tests/test_results_reacting.py`.

### Intraday charts that work without ICICI
- **Stock window → Chart → ⚡ Today** was broken even with ICICI: the chart cut every timestamp down to the date,
  so a day of 5-minute bars collapsed into one day. Bars now carry real times (hh:mm on the axis). When ICICI is
  not connected, the bars come from NSE's chart feed (1-minute last-traded prices turned into 5-minute candles; no volume).
  Before, it silently showed 10 daily bars. The badge says which source is shown (ICICI LIVE / NSE / no intraday),
  and the header shows the move vs the previous close. Only 09:15–15:30 is plotted (the 15:40 closing-session
  prints made a false spike).
- **NIFTY intraday** (Bloomberg GIP style): green above / red below the previous close, with H/L/range and a crosshair
  readout; switch NIFTY / BANK / MID150 / IT / VIX. On BRIEF it takes the gold panel's slot from 09:15 (gold
  pre-open leads before the open and moves to the bottom after it); on MOV there are two side by side.
- data-service: `nse_live.parse_symbol_chart`, `NseLive.symbol_chart` / `index_chart`; `/live/intraday/{t}` falls
  back to NSE; `GET /db/index-intraday?index=`; ui-api `GET /api/market/index-intraday`. Tests in `tests/unit/test_nse_live.py`.

### FA: quarterly financials in every stock's Profile
Bloomberg's FA for NSE: open any stock → **Profile → Financials (FA)**. Revenue and net-profit bars for the last
12 quarters and a table with YoY / QoQ growth, margin and EPS, read straight from the XBRL file attached to each
NSE results filing (consolidated where filed). Banks show interest earned and net interest income. Checked against
TCS Q2 FY27: revenue ₹73,188 cr (+11.2% y/y), net profit ₹13,934 cr (+14.9%), EPS 38.37. Cross-checked against the
publicly reported Q2 FY26 figures: TCS revenue ₹65,799 cr, HCLTech ₹31,942 cr / profit ₹4,236 cr, Infosys
₹44,490 cr, Reliance ₹2,58,898 cr / ₹22,092 cr. All match.
**Validated against NSE's own P/E file** (`PE_131026.csv`, 13 Oct): across 918 companies our filings-based P/E has a
median ratio of 1.008 to NSE's, 85% are within ±15% and 93% within ±30%, with rank correlation 0.978. The biggest
gaps are basis, not errors: NSE appears to use standalone earnings and FA uses consolidated, so holding companies
(CHOLAHLDNG) and parents of large listed subsidiaries (EIDPARRY → Coromandel) differ most.
- EPS is as reported: it is not adjusted for bonuses or splits (HDFCBANK's 1:1 bonus halves it), so EPS growth is
  deliberately not shown.
- First view of a company reads ~12 filings (~6 s), then it is cached (`data/nse_archive/financials/`).
- **CF** shows the numbers next to every results filing once its XBRL is read: "Q2 FY27 · rev +71% · profit +46% y/y ·
  P/E 31×" (Eimco Elecon, 13 Oct). CF becomes an earnings feed.
- **EVTS → season so far** also lists the five best and five worst reporters by profit growth (turns to loss count
  as worst).
- **Reacting today** (EVTS, BRIEF) now also says what the numbers were: revenue and profit vs a year ago for each
  company that reported since the last close. The filings are read in the background (… until ready).
- **P/E history (GE)**: today's P/E against the stock's own daily P/E since the cache begins (~2–3 years), with the
  middle-half band and the median, plus "Nth percentile of its own range". Point-in-time: each day divides by the
  last four quarters' profit as filed by that day; price is split/bonus-adjusted × today's share count.
- **FUND → "P/E vs own past"** column and a **CHEAP VS OWN PAST** preset (bottom fifth of its own P/E history with
  profit growing). Percentiles are rebuilt for every company after each sweep (`nse_archive/derived/pe_percentiles.json`).
  The same "vs own past" percentile appears in COMP's Fundamentals and the Profile's Peers (RV) table.
  Built for 887 companies on 13 Oct. Examples: HDFCBANK 13.9× is the 4th percentile of its own history, TCS 15.9×
  the 8th (it was 34× in late 2024), CUPID 346× the 99th (its median is 111×).
- **TTM line**: trailing-twelve-month revenue and net profit vs the four quarters before (TCS: ₹2,83,248 cr, +9.9%;
  ₹51,858 cr, +4.4%). Shown only when the quarters are consecutive.
- **Valuation strip**: market cap (shares = paid-up capital ÷ face value from the latest filing × last NSE close),
  **P/E on trailing-4-quarter profit to owners**, **P/B** on owners' equity from the last balance sheet, and
  earnings yield. Checked: TCS P/E 14.9× / P/B 6.47×, HDFCBANK P/E 13.7×, AEROFLEX P/E 112× (TTM EPS 5.16 at ₹568).
  Hover each figure for how it was computed. No P/E when the last four quarters aren't consecutive (the Mar-2025 gap).
  The share count is cross-checked against profit ÷ EPS because filers make typos (SHILPAMED's Jun-2026 filing
  has a face value of ₹1,956 instead of ₹1, which made its P/E read 0×; now 66.7×). A P/E below 1× shows "—".
  Your holding **CUPID** really is ~355× trailing earnings (₹48,650 cr market cap on ₹137 cr of profit over four
  quarters): checked, not a data error.
- **Peers → relative value (RV)**: the Profile's peer list is now a sortable table: market cap, P/E, P/B,
  revenue and profit growth, margin, 1D / 1W / 1M. P/Es below the peer median are green. Peers not read yet are
  fetched in the background and fill in within a minute or two. Example: TCS 14.9× vs an IT median of 23.5×
  (INFY 13.6×, HCLTECH 18.1×, PERSISTENT 47.5×).
- **Profile → Price** box shows market cap · P/E · P/B at a glance (from FA), and the stock window's header carries a
  "MCAP · P/E" chip on every tab.
- **Profile → Dividends & corporate actions (DVD)**: dividends per share by financial year (specials flagged), the
  trailing-12-month dividend and yield, and every bonus, split and buyback (5 years, NSE corporate actions). TCS:
  ₹111 per share over the last 12 months (including a ₹46 special), a 5.2% yield at ₹2,125.
- **Profile → Company filings (CN)**: the stock's own NSE announcements for 30 days / 90 days / 1 year, categorised
  (results, orders, capital, M&A, analyst, press…), with filter chips and a PDF link each; routine paperwork is
  hidden unless asked for.
- **DESK momentum watchlist** and **WTCH** show P/E and latest-quarter profit growth beside each name. These are
  context only: the Desk still ranks on momentum alone.
- **COMP → Fundamentals**: the compare page adds market cap, P/E, P/B, revenue / profit growth, margin, dividend
  yield and the latest quarter for the stocks you compare (`COMP TCS INFY HCLTECH`).
- Weekly **financials sweep** (Saturday 10:00) pre-reads the market-map names, your holdings, Desk and watchlist
  so FA / RV open instantly.
- A profit that turns into a loss (or back) says "to loss" / "to profit" instead of a meaningless percentage.
- Every new results filing (the 5-minute filing watcher) queues a background read of its numbers, so tonight's
  **WRAP** lists "Results announced today" with revenue / profit vs a year ago.
- **Results-numbers alert**: when one of your stocks (holdings, Desk, watchlist, alerts) files results, the Mac
  notification / 🔔 inbox now follows up with what they said once the filing is read, e.g. "HCLTECH Q2 FY27:
  revenue +12%, profit +21% y/y, net margin 14.4% · P/E 18.1×". Once per quarter per stock.
- The **08:50 morning note** now opens with what reported overnight: "4 reported since yesterday's close:
  HCLTECH (rev +11.5% / profit +21.2%), …" (your stocks first).
- **GO**: `TCS DES` opens the Profile, `TCS FA` jumps to the financials, `TCS ERN` to the results history. Typing
  a bare ticker lists all its functions (DES, FA, ERN, OMON, DEAL, TV, W), Bloomberg-style.
- Known gap: Q4 FY25 (Mar 2025) is missing for about 1 company in 8 (54 of 421 checked). NSE's two feeds don't
  cover it for them (the switch to integrated filing), so those rows show no YoY for Q4 FY26.
- `services/data-service/financials.py`; `/db/security/{s}/financials`, `/db/financials-latest`,
  `POST /db/financials/prefetch`; ui-api `/api/stocks/{t}/financials`. Tests: `tests/unit/test_financials.py`.

### 15:40 closing note
The counterpart to the 08:50 morning note, as a Mac notification + 🔔 inbox (+ Telegram once set up): NIFTY's
close, breadth through the day ("NIFTY 500 335 up / 164 down, net ranged −105 to +171", flagged when narrow),
small caps vs NIFTY when they diverge, and what your holdings did today in ₹ with the biggest movers. It uses the
last known holdings while ICICI is logged out. `compose_close_note` / `close_note` in `scripts/master_controller.py`.

### ALRT: alerts centre (from GO: `ALRT`, MORE ▾, or "ALL · ALRT ›" in the 🔔 dropdown)
Every server-side price alert in one table: last price, the above / below levels with their distance, nearest
level first (amber within 2%), a form to add or change one, and ✕ to remove. Alongside: the alerts that fired, and
the whole notification inbox (morning and closing notes, moves, filings, results numbers, wraps) with kind filters.
`ui/components/AlertsCenter.tsx` on the existing `/api/alerts` endpoints.

### FUND: fundamentals screener (from GO: `FUND`, or MORE ▾)
Screens every company whose results filings have been read: market cap, P/E (TTM), P/B, revenue and profit growth
(latest quarter vs a year ago), net margin and which quarter it is. There are presets (GROWTH SANE PRICE, FAST
PROFIT GROWTH, LOW P/E, HIGH MARGIN, LARGE CAPS), filters for P/E, growth, margin, size and industry, sortable
columns, hover quotes and ⤓ CSV. Rows still on an older quarter (results not out yet) show the quarter in amber.
- Coverage: 271 companies after the first sweep (13 Oct, 15:32–15:59: the market-map names, your holdings, Desk and
  watchlist). It grows with every results filing, every FA opened, and the Saturday sweep.
- STOCKS (code EQS) keeps its snapshot fundamentals (P/E, market cap, quarterly sales/profit from the older
  enrichment source). FUND / FA are from NSE's own filings, quarter by quarter.
- FUND remembers your last screen (filters only) in this browser.
- **Tick 2–8 rows → COMPARE** opens them in COMP (price performance, risk, correlation and fundamentals side by side).
- **Industries** panel on top (Bloomberg BI style): company count, market cap, and median P/E, P/B, revenue and
  profit growth and margin per NSE industry; click one to filter the list. After today's sweep: Financial Services
  56 companies at a 22.5× median P/E, Capital Goods 49.7×, Oil & Gas 8×.
- **Filer unit errors repaired, only when proven**: a scan for quarter-to-quarter revenue jumps of more than 50×
  found filings entered 100× off (COROMANDEL's Mar-2026 XBRL reports quarterly revenue of ₹60 cr and a full year of
  ₹315 cr instead of ~₹6,004 cr / ₹31,480 cr). A quarter is rescaled only if its paid-up capital (or profit ÷ EPS)
  is off by the same 100×. Four quarters were repaired (PFC, MTNL, METROBRAND, COROMANDEL) and are marked † in FA.
  Genuine odd quarters such as SWANDEF's dormant-shipyard ₹0.42 cr are left as filed.
- **Insurers** (LICI, SBILIFE, HDFCLIFE, ICICIGI, NIACL and others) now parse too: their filings use the insurance
  taxonomies (net premium income / premium earned, profit after tax, EPS); the share count comes from profit ÷ EPS.
  A data-quality scan found them showing no revenue. The rest of the outliers it flagged are genuine (holding
  companies' margins above 100%, P/E below 2 from one-off gains such as TMPV's demerger).
- Banks now get a P/B too (their filings report book value as Capital + Reserves, not "equity"); only the banks'
  filings were re-read.
- Labelled as a screen, not a signal. The idea behind the growth presets was tested the same day (RSCH, PROMISING).
- `/db/financials-universe` → `/api/market/fundamentals-screen`; `ui/components/FundamentalsScreen.tsx`.

### Market valuation from NSE (MKT, BRIEF)
NSE publishes P/E, P/B and dividend yield for every index. **MKT → Valuation · NSE** lists them for NIFTY 50, NEXT 50,
500, MIDCAP 150, SMALLCAP 250 and the main sectors, with earnings yield and 1D / 1M / 1Y moves. P/Es well above or
below NIFTY's are coloured. BRIEF's MARKET panel has one line ("NIFTY P/E 19.4× · P/B 2.8 · yield 1.5% · mid 28× ·
small 34×" on 13 Oct). After each close the day's figures are archived (`nse_archive/derived/index_valuation.jsonl`),
so a valuation history builds from 13 Oct. `/db/index-valuation`.

### MOV → Who moved the index
Each constituent's contribution to today's index move in points, the biggest adders and subtractors as bars, for
NIFTY 50, BANK, IT and NEXT 50. NSE doesn't publish live weights, so they are rebuilt from the filings: shares
(latest results XBRL) × previous close × (1 − promoter holding, latest shareholding filing). The panel shows the
explained total next to the actual move, so the error is visible. On 13 Oct NIFTY moved +358.6 points and the
rebuilt weights explain +357.3 (TCS +30.7, INFY +30.6, ICICIBANK +30.2, HDFCBANK +29.1; KOTAKBANK −6.7). Sector
indices cap single weights, so BANK NIFTY is explained less exactly (+631 vs +563). `/db/index-contribution`.
BRIEF's Market today panel carries the one-line version ("NIFTY points · TCS +31 · INFY +31 · ICICIBANK +30 · drag
KOTAKBANK −7"), and the 15:40 closing note names the top contributors.

### Market internals through the day (MOV, and tonight's WRAP)
Is a rally broad, or a few heavyweights? On 13 Oct at 11:34 NIFTY 50 was +0.6% while only 208 of the NIFTY 500
were up (290 down) and small caps were −0.7%. NSE only shows a breadth snapshot, so the terminal now samples it
every 2 minutes in session and keeps the path:
- **MOV → Market internals**: NIFTY 500 advances − declines as bars, with the % move of NIFTY 50, Midcap 150 and
  Smallcap 250 as lines, plus a ⚠ flag when the index and the average stock go different ways.
- **WRAP**: a "through the day" line (net breadth range and close, small caps vs NIFTY), and the narrow-rally flag.
- master-controller job `internals_sample` (every 2 min, 09:15–15:31) → data-service `POST /db/internals/sample` →
  `data/nse_archive/internals/<date>.jsonl`; read with `GET /db/internals` / `/api/market/internals`.
  `services/data-service/market_internals.py`; tests `tests/unit/test_market_internals.py`, `scripts/tests/test_daily_wrap.py`.
- Today's line starts at 11:34 (when it was switched on); from tomorrow it covers the full session.
- What it showed on 13 Oct: until ~13:45 the rally was narrow (NIFTY up, net NIFTY 500 breadth as low as −105, small
  caps red). Then it broadened: by 14:50 net breadth was +171 (335 up / 164 down) and NIFTY closed the move at
  +1.5%. That is the kind of read the snapshot numbers alone can't give.

### Your holdings priced live while ICICI is logged out (BRIEF and WTCH)
ICICI is logged out most mornings, which used to mean no P&L anywhere. Now the last known quantities and buy
prices are priced with live quotes (Yahoo, ≈1 min delayed; refreshed every 2 min on BRIEF):
- **BRIEF → Your book**: "Last-known book · live prices": value, total P&L, today's ₹ move, and each stock's day
  move and P&L. (The "today" figures shown before 16:50 on 13 Oct were wrong: see the Yahoo fix below.)
- **WTCH → Your book · X-ray**: weights by value at live prices, the largest holding, effective number of holdings
  (1 ÷ Σw²), the book's P/E and profit growth (value-weighted), and value-weighted risk. On 13 Oct: CUPID 52% +
  AEROFLEX 41% = 93% in two stocks; the book behaves like 2.3 equal positions; P/E 116×; volatility 42%, beta 1.21.
  The 21:00 WRAP opens its Your stocks section with the same line. BRIEF's Your book shows it too ("CUPID 52% of the book · behaves like 2.3 equal positions").
- **WTCH → COMPARE HELD** opens your holdings side by side in COMP (performance, risk, correlation, P/E, growth,
  dividend yield).
- **WTCH → Holdings today** stat: today's ₹ move and total P&L of your holdings at live prices.
- **WTCH → Position** column: `qty @ buy` and P&L in ₹ and %, sortable; hover for value and today's ₹ move.
  The live ICICI book is used when connected.

### Hover any ticker for a quote card (everywhere)
Hold the mouse on any amber ticker for half a second: last price, day move, 1-month sparkline, day range,
52-week range and where the price sits in it. Click still opens the stock window. Quotes are cached for 60 s, so
hovering down a table is cheap. When the company's filings have been read, the card adds P/E and the latest
quarter's revenue / profit growth. (`TickerLink` in `ui/components/terminal/index.tsx`.)

### Keyboard tables, ⤓ CSV on every table, and the ICICI light opens the login
- **Keyboard through any table**: click a table, then ↑ / ↓ (or j / k), Home / End to move a highlighted row
  cursor; Enter opens that row's stock; Esc clears. Listed in the `?` help card.
- Hover any table (EVTS, DEAL, INSD, MOV, WTCH, DESK…) and a **⤓ CSV** button appears top-right: it downloads
  exactly what is shown, in the current sort (e.g. `evts-2026-10-13.csv`), with clean headers and a UTF-8 marker so
  Excel shows ₹ and × properly.
- The red **● ICICI** light in the header now says "not connected: click to log in" and takes you to the Broker
  tab's login box.

### Small polish (13 Oct afternoon)
- **Warehouse → NSE research datasets** now also lists the file archives kept outside DuckDB (pre-open books,
  market internals, financials cache, IPO bid books, option history) with counts, date range and a freshness flag.
- BRIEF's title follows the clock: **Morning Brief** before the open, **Session Brief** in market hours,
  **Evening Brief** after the close. The "Market today" panel adds a breadth line (up / down, net range, ⚠ narrow).
- BRIEF's industries line was "Leading industries" even when they were falling. It now shows the best three
  **and** worst three over a month, coloured.
- FUND has a **REPORTED THIS QUARTER** preset (results season view).
- SYSTEM's job table shows schedules for the new jobs (internals every 2 min, 15:40 closing note, Saturday
  financials sweep); OVERVIEW's fundamentals panel now says how many companies have NSE-filing financials (→ FUND).
- Broker (ICICI logged out) no longer shows a red "execution service: all connection attempts failed": that
  service isn't part of the local paper stack (the Desk runs in data-service). It now reads "not running · not
  needed in PAPER mode", and the page links to WTCH where your last-known holdings are priced live.
- BRIEF's "Largest names reporting" shows each one's last-quarter profit growth too.
- EVTS tables (Your stocks, All events) have a **Last quarter** column: what each company reported last time
  (profit vs a year ago · P/E), so an upcoming result has its baseline beside it. It reads the cache only.

### WRAP (13 Oct evening)
Tonight's wrap was checked line by line and regenerated at 21:01 with two fixes:
- **Options line rolls on expiry day**: at 21:00 on 13 Oct (an expiry day) it described the contract that had just
  settled ("±0.18% priced in"). It now moves to the next series (19 Oct: ±1.67%, PCR 1.39, walls 23,000 / 22,500).
- **New lines**: valuation from NSE (NIFTY P/E 19.4×, P/B 2.79, yield 1.51%; midcaps 28×, smallcaps 34×), who moved
  NIFTY in points, breadth through the day, results announced today with their numbers, and the book's
  concentration. Day moves for your stocks use official NSE previous closes.

### Fixed: "today" moves were two-day moves (Yahoo skipped Monday)
Yahoo's daily series for NSE stocks is missing Monday 12 Oct, so every "today" change computed from it compared
against Friday's close. On 13 Oct that turned AEROFLEX's −1.8% day into "+7.1%" and CUPID's −2.4% into −3.6%, and
the 15:40 closing note said your holdings made **+₹622**. With official NSE prices they **lost ₹3,326** (all four
down). The morning's ±5% move alerts were computed the same way: the 10:10 "AEROFLEX is up 6.7% today" was
false (AEROFLEX was down on the day), and the PCJEWELLER / SYNCOMF ones were two-day figures.
- Every NSE stock quote now takes its previous close from our NSE bhavcopy (the last official close before the
  quote's session; `/db/prev-close`, applied in `news_scanner._official_prev_close`, marked `prev_source: NSE`).
  WTCH, BRIEF, hover cards, Reacting today, the closing note and move alerts all use it.
- A corrected closing note was added to the 🔔 inbox at 16:48, labelled as a correction.
- Tests: `services/ui-api/tests/test_official_prev_close.py`.

### Fixed: the market tape showed yesterday's NIFTY after the close
At 16:40 the header tape read "NIFTY 50 22,363.30 −0.70%": Yahoo was still serving the 12 Oct close (its timestamp
said 12 Oct 15:30) while NIFTY had closed at 22,721.95, +1.60%. BANK NIFTY and VIX were stale too, and WEI's India
block mixed Yahoo's stale point change with fresh percentages. The tape, WEI's India rows and the move-alert job's
NIFTY now come from NSE (`/db/indices-live`, one allIndices read); Yahoo keeps FX, commodities, global indices
and the sparklines.

### Fixed: earnings-call notices were counted as results
NSE filings were classified by keywords, so any notice that mentioned "financial results" counted as results:
earnings-call invitations (ICICIBANK, JIOFIN, INDIANB, SWSOLAR, IXIGO…), "Integrated Filing- Governance", even
"Reasons for Delayed/Non-submission of Financial Results". On 12 Oct, 14 of 36 "results" were wrong, so they
appeared in Reacting today, CF and the results filing alerts. The classifier now trusts NSE's standardised
subject first: earnings-call notices → analyst, governance → routine, "Outcome of Board Meeting" → results only
when the text says results were filed or approved. Nothing real was lost (`nse_live.filing_category`, 9 new test cases).
The reacting table also says why a figure is missing: … = still reading, "not on feed yet" = NSE hasn't published
the XBRL (it often lands hours after the PDF), — = no year-ago quarter.

### Fixed: a test run wiped the saved holdings
At 10:11 a broker test wrote an empty book over `data/last_holdings.json`, so BRIEF showed "last known 0
holdings". The 4 holdings are restored, and every ui-api test now writes state files to a temp folder
(`services/ui-api/tests/conftest.py`).

## New

### BRIEF (BRF): the morning one-pager, now the landing page
Everything to know before 09:15 on one screen. Each block links to its full page:
- **Market:** regime score, breadth, VIX, leading industries, and a NIFTY options line (move priced to expiry,
  PCR, call/put walls) linking to OMON.
- **Your book:** Desk value and return vs NIFTY, plan status; ICICI holdings and P&L when connected.
- **Gold open:** fair value and verdict before 09:00.
- **This week:** events for your stocks, the **biggest results reactions of the last 5 days** (ranked by size vs
  normal, with the bad-results flag), **insider buying ≥ ₹1 cr in the last 7 days**, and the largest names
  reporting with their typical move.
- **News scanner:** top picks by conviction, plus the honest track-record line.
- **Headlines:** the last 24 h of Indian market news (markets, RBI, FII flows, results, IPOs, global cues) from
  Google News, de-duplicated and cached for 5 minutes (`GET /api/market/headlines`).
- **System:** data date, ICICI session, scheduler, next jobs.

Each block loads on its own, so a slow source never blanks the page. To make the Desk the landing page again:
`useState<Tab>('desk')` in `ui/app/page.tsx`. File: `ui/components/Brief.tsx`.

**Crash filter, live:** BRIEF and the Desk show today's NIFTY 50 vs its 200-DMA. That is the series the Desk
uses (`GET /db/crash-filter`). It also shows how far NIFTY must rise to turn risk-on and the next monthly signal
date, so you know whether the next rebalance will invest or stay in the liquid fund.

### Watch tab (WTCH): live monitor of everything you follow
- **Contents:** one grid with your watchlist, pinned stocks, ICICI holdings and Desk positions, each tagged.
- **Columns:** last price, day change, a 1-month sparkline, day-range and 52-week-range markers (with "HIGH"
  at a new high), the next corporate event, and a remove button.
- **Summary:** names, up/down count, average move, best/worst.
- **Add a stock:** type it and press Enter. Quotes refresh every 60 s (Yahoo; ICICI live quotes stay on the Broker tab).
- **Price alerts:** click 🔔 on any row to set "above" / "below" levels. They're checked on every quote refresh;
  a crossed level fires once, as an in-app toast and a desktop notification (enable it with one click), and is
  removed. The most recent alerts that fired are listed. **Update: alerts now live on the server and fire with
  the terminal closed** (see "Price alerts now work with the terminal closed"). They are not broker orders.
  Implementation: `ui/lib/alerts.ts`, `services/ui-api/routers/alerts.py`.

File: `ui/components/WatchMonitor.tsx`.

### Command bar ⟨GO⟩: `/` or Ctrl+K
Bloomberg's command line. Type:

| You type | It does |
|---|---|
| `MKT`, `EVTS`, `DESK`, `BTST`, `PORT`, `RSCH` … | jumps to that page: the code shown in each page's header (prefixes and names work too) |
| `TCS` or `tata` | opens the stock: chart, levels, ☆ PIN, + WATCHLIST (searches 1,500 tickers and company names) |
| `TCS TV` / `TCS YF` | opens the stock on TradingView / Yahoo Finance |
| `TCS W` | adds the stock to the watchlist, or removes it |
| `NEWS` | opens the News Catalyst Terminal |

Remembers your recent stocks. Press **?** (or type `HELP`) for a card listing every function code and keyboard shortcut; click a code to jump there.
Files: `ui/components/CommandBar.tsx`, `GET /api/stocks/symbols`.

### COMP: compare stocks (from GO: `COMP TCS INFY HCLTECH`)
- **The chart:** up to 8 stocks rebased to 100 against NIFTY 50 (dashed), over 1M–2Y, with hover values.
- **Risk table:** return, annualised volatility, max drawdown, beta and correlation to NIFTY, best/worst day.
- **Correlation matrix** of daily returns, to see whether names actually diversify.
- **Reaching it:** from GO and HELP. It is deliberately not in the tab strip, so the strip still fits.

File: `ui/components/Compare.tsx`.

### OMON: option monitor (from GO: `OMON`, `OMON RELIANCE`, or OPTION CHAIN › in a stock's Profile)
The end-of-day option chain for NIFTY, BANKNIFTY, FINNIFTY and all 219 F&O stocks, from NSE's F&O bhavcopy
(already cached nightly). No new data feed was needed.
- **Chain:** per strike, call/put open interest (bars), OI change, volume, price and **implied volatility**. It
  opens centred on the at-the-money strike, with the in-the-money side shaded.
- **History (NIFTY, BANKNIFTY):** one year of near-expiry ATM implied volatility and PCR, with today's **IV rank**
  (share of the past year below today). It's built once from the 561 cached F&O files (~40 s) and then updated
  incrementally; NIFTY IV peaked near 33% in spring 2026 and is 10.4% now (rank 46).
- **Charts:** the **volatility smile** (out-of-the-money IV by strike: the put skew shows how much traders pay for
  downside protection) and **open interest by strike** (calls red, puts green, forward marked).
- **Summary:** spot and forward, ATM IV, the **move the options price in by expiry** and its range, put/call OI
  ratio, **max pain**, and the **OI walls** (largest call OI = resistance, largest put OI = support). Any expiry.
- **Method:** IV is Black–Scholes on the put–call-parity forward. Using spot skewed call and put IVs apart;
  the forward makes them agree at the money. IVs for deep in-the-money options (stale prints) are hidden.
  Example on Friday: NIFTY ATM IV 10.4%, a priced move of ±1.15% by Tuesday's expiry, PCR 1.28, max pain
  22,500, walls 23,000 / 22,500.

Files: `services/data-service/option_chain.py`, `GET /db/option-chain/{symbol}`, `GET /api/market/option-chain/{symbol}`,
`ui/components/OptionChain.tsx`. Tests: `tests/unit/test_option_chain.py` (IV inversion, max pain, chain).

### INSD: insider monitor (from GO: `INSD`)
- **What it shows:** open-market purchases by promoters, directors and key managers (≥ ₹10 lakh, or ≥ ₹1 cr), per
  stock, over 30/60/180 days. Columns: amount bought, trades, number of buyers, who, the move since the latest
  filing, and the next corporate event.
- **Definition:** exactly the H4 definition from the held-overnight study. It opens with that verdict (PROMISING:
  +1.0% / +2.6% over 20 days, holdout not yet significant) and warns if the insider feed goes stale.
- **Data:** this was only possible after the feed repair below.

Files: `GET /db/insider-buys`, `GET /api/market/insider-buys`, `ui/components/InsiderMonitor.tsx`.

### HDS: ownership shifts (from GO: `HDS`, or MORE ▾)
- **What it shows:** for the ~320 liquid stocks with shareholding filings, the latest quarter vs the previous one:
  change in mutual-fund, foreign-investor (FPI), promoter and retail share (percentage points, with the new level),
  and the change in the number of shareholders.
- **Views:** MF buying / selling, FPI buying / selling, promoter changes, and shareholder surge (a retail rush).
  Pick the quarter (the September 2026 filings are arriving now: 45 so far).
- **Today's read:** in the September quarter so far, **mutual funds bought what foreign investors sold**, e.g.
  HDFCBANK (MF +1.26 pp, FPI −2.43 pp) and AXISBANK (MF +1.39, FPI −1.86).
- **Data:** the weekly (Saturday) shareholding job keeps it current. Context, not a signal.

Files: `DuckDBStore.holding_changes`, `GET /db/holding-changes`, `GET /api/market/holding-changes`,
`ui/components/OwnershipShifts.tsx`, `tests/unit/test_holding_changes.py`.

### MRGN: margin monitor (from GO: `MRGN`, or MORE ▾)
- **What it shows:** how much stock is held on broker-funded margin (NSE's MTF report, already in our database:
  2.08 M rows since 2022). It was only visible per stock on the Profile.
  - **Market MTF book:** total, its change over 5/20/60 sessions, fresh funding vs liquidations on the last day,
    and a 1-year chart.
  - **Three lists (≥ ₹5 cr funded):**
    - fastest leveraged build-up (growth in funded quantity);
    - most crowded: **days to unwind** = funded amount ÷ 20-day average traded value, i.e. how many sessions of
      normal volume a forced sale would take;
    - largest funded positions.
- **Today's read:**
  - The MTF book is **₹1,50,144 cr, up from about ₹1.0 lakh cr a year ago while NIFTY fell 11%**: retail leverage
    has been building into a falling market.
  - RELIANCE's funded position grew 49% in 20 sessions.
- Context, not a signal.

Files: `DuckDBStore.mtf_monitor`, `GET /db/mtf-monitor`, `GET /api/market/mtf-monitor`, `ui/components/MarginMonitor.tsx`,
`tests/unit/test_mtf_monitor.py`.

### OMON goes LIVE during the session
- **The change:** OMON has a ● LIVE / EOD switch, on LIVE by default 09:15–15:35. The live chain comes from NSE's
  own option chain, refreshed every 30 s, for NIFTY, BANKNIFTY, FINNIFTY and any F&O stock.
- **Same engine:** NSE's payload is converted to the end-of-day format and run through the same engine.
  - Implied vols are our own Black-76 on the put–call-parity forward, not NSE's numbers; plus max pain, OI walls,
    the smile and the OI bars.
  - Live OI comes in contracts and is converted with the lot size, so it is comparable to end of day.
- **Today, 12:37:** NIFTY ATM IV 15.9% (10.4% at Friday's close), ±1.02% priced in to Tuesday's expiry, PCR 0.72
  (1.28 Friday: heavy call writing as NIFTY falls), call wall 22,500, put wall 22,400.
- **Behaviour:** if NSE's live feed fails or throttles, OMON falls back to end of day and says so. The view stays
  put while it refreshes (it only re-centres on the at-the-money strike when you change symbol or expiry).

Files: `services/data-service/option_chain.py` (`live_frame`), `GET /db/option-chain-live/{symbol}`,
`GET /api/market/option-chain-live/{symbol}`, `ui/components/OptionChain.tsx`, `tests/unit/test_option_chain.py` (+1).

### CF: company filings, live (from GO: `CF`, or MORE ▾)
- **What it shows:** every NSE equity announcement of the day, newest first, refreshed every 60 s in market
  hours. Each filing is tagged RESULTS, ORDERS, RATINGS, M&A, INSIDER/SAST, CAPITAL (dividends, splits,
  allotments, fund raises), PEOPLE, BOARD, ANALYST MEETS, PRESS or OTHER, each with a filter chip and a count.
- **Noise:** routine compliance filings (depository certificates, trading-window notices, newspaper copies; 48 of
  today's first 72 filings) are hidden unless you ask for them.
- **Your stocks** (holdings, watchlist, pins) are highlighted, with a YOUR STOCKS filter. ↗ opens the filing PDF on
  NSE; click a ticker for its profile.
- **Filing alerts:** every 5 minutes from 08:00 to 22:55, Mon–Sat, a new material filing by one of your stocks
  (results, orders, ratings, M&A, insider/SAST, capital actions, board outcomes) pops up as a Mac notification,
  and on Telegram once that's set. Seen filings are remembered, so nothing repeats, and the first run doesn't
  replay the day's backlog.

- **EVTS:** today's RESULTS rows get a **✓ FILED hh:mm** badge as soon as the company files with NSE (today:
  HCLTECH 16:58, RBLBANK 16:48, ICICIAMC 17:42).
- **BRIEF "This week" panel:** a **RESULTS FILED TODAY** line, live from the same feed (today: ICICIBANK, HCLTECH,
  RBLBANK, PIRAMALFIN…). The nightly 20:45 capture still adds the exact release times and the next-day reaction.

Files: `services/data-service/nse_live.py` (`filing_category`, `NseLive.announcements`, `GET /db/announcements`),
`GET /api/market/announcements`, `ui/components/CompanyFilings.tsx`, `scripts/master_controller.py` (`filing_alerts`),
`tests/unit/test_nse_live.py` (+12 tests).

### Price alerts now work with the terminal closed
- **Before:** WTCH alerts lived in the browser and were checked only while the page was open.
- **Now:** they're kept on the server (`data/price_alerts.json`).
  - The master controller checks them every minute, 09:15–15:30 Mon–Fri.
  - A crossing pops up as a **macOS notification** (works today, no setup), and goes to Telegram once that's
    configured.
  - While WTCH is open it also checks on every refresh (so US-stock pins fire outside Indian hours) and shows a
    toast.
  - Each level still fires exactly once, whichever side catches it first. Levels saved by the old browser-only
    version move to the server automatically on the first visit.
- **Tested end to end:** a TCS level crossed and fired once at ₹2,155.20; the other side was kept.

- **Automatic move alerts (no setup):** every 5 minutes in market hours:
  - If one of your ICICI holdings is up or down 5%, or 10%, on the day, you get a Mac notification (once per
    level per day).
  - If NIFTY crosses its 200-day average intraday, you get a heads-up. That's the Desk's crash-filter line; the
    filter itself is decided only at the month-end close.
  - Tests: `scripts/tests/test_move_alerts.py`.

- **Pre-market note at 08:50 (Mon–Fri):** one line, sent to the Mac, the inbox and Telegram, covering:
  - GIFT NIFTY's implied gap;
  - the overnight S&P, Nasdaq, Brent and USD/INR;
  - the last FII/DII cash figures;
  - **your stocks' events today first**, then how many results are due and the biggest names.

  Tonight's preview: "GIFT NIFTY implies +0.0% at the open · overnight S&P +0.6%, Nasdaq +0.6%, Brent +2.0%,
  USD/INR −1.1% · FII −3,569 cr / DII +4,743 cr · 14 results today: HEROMOTORS, SSRETAIL, TATAELXSI…"
- **Notification inbox:** a 🔔 bell in the header lists everything the scheduler sent (price alerts, moves in your
  holdings, filings by your stocks, the nightly wrap), with an unread count. A dismissed Mac notification isn't
  lost. Stored in `data/notifications.jsonl` (git-ignored); endpoint `GET /api/alerts/feed`.

Files: `services/ui-api/routers/alerts.py` (`GET/PUT /api/alerts`, `POST /api/alerts/run`), `ui/lib/alerts.ts`,
`scripts/master_controller.py` (`price_alerts_check`), `services/ui-api/tests/test_price_alerts.py` (3 tests).

### Risk profile of a basket: DESK watchlist and WTCH
- **On DESK, under the momentum watchlist: "Watchlist risk · what the Desk would hold".**
  - The equal-weight basket's volatility (vs NIFTY), beta, max drawdown over the last year, average pairwise
    correlation (with the tightest pair) and diversification ratio.
  - Industry concentration against the Desk's 40% cap, plus per-stock volatility, beta, 1-year return and max
    drawdown.
- **Today's reading** (useful for the pending industry-cap decision):
  - The basket runs 24% volatility (NIFTY 14%) at beta 1.18, and fell at most 12% over the year (NIFTY −16%).
  - **Capital Goods already fills 7 of the 20 slots (cap = 8), and 5 names are "Unknown"**, which the cap cannot
    see. If AEROFLEX (industrial pipes) is Capital Goods, the real concentration is already at or above the cap.
- **On WTCH:** the same panel for your own list (holdings, Desk positions, watchlist, pins).
- **On Broker (your real ICICI holdings):** a **Today** column (each holding's % move on the day) and **today's P&L
  in rupees**, next to the unrealised total. ICICI's holdings call has no previous close, so the day move comes
  from Yahoo (about 1 minute delayed).
- **On Broker, also:** "Holdings risk", **weighted by holding value**.
  - Today: CUPID, AEROFLEX, PCJEWELLER and SYNCOMF together run **42% volatility (3× NIFTY's 14%), beta 1.22**,
    with a −20% max drawdown over the year.
  - The legacy-settings line there now says the approved "stop 2×ATR" instead of the stale "stop −2%".
- **On every stock's Profile, a new News box:** the last 7 days of headlines about that company (Google News,
  filtered so a title must name the company or its ticker). Example, today: AEROFLEX's +13% was explained by
  "Aeroflex Industries shares rally 13% ahead of key board meeting on expansion plans" (board meeting Wed 14 Oct).
  Endpoint: `GET /api/market/stock-news/{symbol}`.
- **On every stock's Profile, a new Risk box:**
  - 1-year volatility vs NIFTY (and the multiple), beta, and max drawdown vs NIFTY's.
  - A sizing guide: the position at which a 2-standard-deviation day costs about 1% of the portfolio (TCS: 29%
    volatility, 2.1× NIFTY, beta 0.77, −40% max drawdown → about 28% of capital).
- **Data correctness:** returns use corporate-action-adjusted closes, the same `shared/nse_panel.adjust` the Desk
  ranks on. Our bhavcopy's prev_close is *not* adjusted: CUPID's 1:5 split on 9 Mar showed as −77%, and 129
  stock-days in the year moved more than ±35% for that kind of reason.
- **IPO scorecard made split-safe:** "+20 / +60 sessions" and "now vs issue" chain adjusted closes after
  listing. The < 10× QIB bucket's 60-session mean was +5.5% before the fix and is +8.0% after.

Files: `services/data-service/basket_risk.py` (`GET /db/basket-risk`), `GET /api/market/basket-risk`,
`ui/components/BasketRisk.tsx`, `tests/unit/test_basket_risk.py` (3 tests), `test_ipo_monitor.py` (+1 split test).

### Market map goes LIVE during the session (MKT and MOV)
- **The change:** the 250-stock heatmap has a ● LIVE mode, the default between 09:15 and 15:35. Tiles are
  coloured by today's move and refreshed every 60 s; 1D/1W/1M still show the end-of-day picture.
- **Prices:**
  - About 185 of the 250 come from NSE's own heatmap lists (every sectoral index plus NIFTY 50 / NEXT 50 /
    MIDCAP 50, cached 30 s server-side). The rest come from Yahoo, about 1 min delayed.
  - The subtitle shows how many were priced from each source. Grey means no live price.
- **Also on MOV**, under the sector board.
- **After the close** (until midnight), the map opens on **TODAY** (the session close) instead of Friday's 1D
  colours.
- **Speed:** the map paints at once from NSE. The ~65 names priced by Yahoo (about 25 s cold) fill in behind it,
  refreshed every 5 minutes in session and once after the close. MOV went from ~56 s to ~13 s to settle.
- **Robustness:** NSE live calls now time out after 8 s instead of 20 s, so a slow NSE answer can't push a page
  past the 30 s proxy limit. That limit caused one failed MOV load after the close.
- Industry headers on the map no longer run into the next block.

Files: `GET /db/live-quotes` (`nse_live.NseLive.heatmap_quotes`), `GET /api/market/live-quotes`, `ui/components/MarketMap.tsx`.

### WRAP: daily market wrap (from GO: `WRAP`, or MORE ▾)
- **What it is:** one page per session, written at 21:00 IST once the evening NSE files, FII/DII cash and results
  times are in. It's built only from the terminal's own data, with no forecasts:
  - the session (indices, breadth, regime, crash-filter distance);
  - best and worst industries;
  - money flows (FII/DII cash, FII futures, the biggest net block/bulk deal flows, MF/insurer deals, insider
    buys disclosed that day);
  - movers and volume shockers, and results reactions with the bad-results drift flag;
  - results announced today (largest first, with each stock's typical results-day move), since they react next
    session. The wrap waits for the 20:45 results capture to finish;
  - **your stocks** (ICICI holdings, Desk positions, watchlist, alerted symbols): the day's move, the next event
    within a week, the day's top headline, and any deal, insider filing, results reaction or price alert that
    day;
  - tomorrow (corporate events by size, GIFT NIFTY's implied gap at 21:00, the NIFTY options' priced-in move,
    PCR, max pain and walls);
  - the Decision Desk's NAV.
- **Safeguards:** if the end-of-day files weren't processed yet, the wrap says so and dates the affected sections.
  A source that doesn't answer is listed at the bottom, and the rest is still written.
- **Archive and alerts:** the WRAP page lists every wrap, with older/newer navigation. The one-line summary goes
  out as an alert (Telegram once configured). Friday 9 Oct's wrap is already there as the first entry.
- **Manual run:** `PYTHONPATH=. python scripts/daily_wrap.py [--date YYYY-MM-DD]`.

Files: `scripts/daily_wrap.py`, `reports/daily_wrap/`, `GET /api/market/wraps(/{date})`, `ui/components/DailyWrap.tsx`,
`scripts/tests/test_daily_wrap.py`, master-controller job `daily_wrap` (21:00 Mon–Fri).

### MOV: live movers during the session (from GO: `MOV`, or BRIEF → MORNING PAGES)
- **What it shows:** the intraday picture. MKT is end-of-day.
  - Header: NIFTY 50 with its advance/decline count, NIFTY 500 breadth, midcap vs smallcap, and the count of
    new 52-week highs vs lows.
  - Sector board: every NSE sectoral, thematic or broad index, coloured by its move, with a bar showing the share
    of members up. Hover for 30-day and 1-year moves.
  - Seven lists: gainers and losers (NIFTY 50, BANK NIFTY, NEXT 50, F&O, > ₹20 or all), most active by value,
    volume surges vs the 1-week average (≥ ₹1 cr traded), new 52-week highs and lows (with the old level and its
    date), and F&O open-interest spurts.
- **Data:** NSE's own live market analysis, about 1 min delayed. Refreshed every 30 s while the market is open
  (cached 30 s server-side, so any number of open tabs cost NSE one request). Nothing is stored.

- **Sector board drill-down:** click any tile (sectoral, thematic or broad) to see its member stocks live, best to
  worst, refreshed every minute. Click a member for its profile.

Files: `services/data-service/nse_live.py` (`GET /db/live-movers`, `GET /db/index-members`), `GET /api/market/live-movers`,
`ui/components/LiveMovers.tsx`, `tests/unit/test_nse_live.py` (3 tests).

### IPO: IPO monitor (from GO: `IPO`)
- **Open & forthcoming issues (NSE):** board (mainboard or SME), bidding dates, price band, size in ₹ cr, and
  lot size with the rupee cost of one lot. While an issue is open, live subscription by category: QIB
  (institutions), NII (HNIs), retail and total.
- **Recent listings scorecard** (mainboard or SME, 12/24/60 months), from our NSE bhavcopy:
  - subscription by category;
  - listing-day open and day-1 close vs the issue price;
  - +20 and +60 sessions measured from the day-1 close (what a buyer after listing actually got);
  - today vs the issue price.
- **"Does institutional demand show up in the listing?"** Mainboard IPOs bucketed by QIB subscription, 24 months
  of data:

  | QIB subscription | IPOs | Average listing gain | Average next 60 sessions |
  |---|---|---|---|
  | ≥ 100× | 48 | +36% | −12.3% (n = 23) |
  | < 10× | 91 | −1.7% | +8.0% (n = 69) |

  Heavy institutional demand is priced in on day 1, and the stocks then gave back. Descriptive and in-sample,
  with small samples: context, not a rule.
- **Data:**
  - NSE's bid book of every listed issue is cached on disk for good (`data/nse_archive/ipo/`); the first visit
    fetches them in the background, about 3 minutes.
  - NSE publishes no bid book for SME issues, so the SME view has no subscription columns.

Files: `services/data-service/ipo_monitor.py` (`GET /db/ipo`), `GET /api/market/ipo`, `ui/components/IpoMonitor.tsx`,
`tests/unit/test_ipo_monitor.py` (5 tests).

### FII / DII cash flows: now collected every day
- **Data:** NSE only serves the latest day of FII and DII cash-market buying and selling (NSE + BSE, provisional),
  so nothing was being kept. A new table, `nse_fii_dii_cash`, stores it from today:
  - filled by the 20:30 catch-up job, and by the page itself at most every 30 min;
  - covered by the freshness alarm.
- **Where it shows:**
  - BRIEF's Market panel: a line with the latest day.
  - MKT, under "Who holds index futures": the latest day, the last 5 sessions and month to date. These fill in
    as history accumulates.
- **History:** starts 9 Oct 2026. NSDL's FPI archive (the usual source for older history) was unreachable from
  here.

Files: `services/data-service/fii_dii.py`, `GET/POST /db/fii-dii-cash`, `GET /api/market/fii-dii-cash`,
`tests/unit/test_fii_dii.py`.

### PRE: pre-open auction (from GO: `PRE`)
- **What it shows:** NSE's 09:00–09:08 call auction for F&O stocks, NIFTY 50, BANK NIFTY or all NSE.
  - For each stock: the indicative equilibrium price (IEP), the gap vs yesterday's close, the matched quantity
    and value, and the buy and sell orders left over.
  - An imbalance bar: +100 means only buyers are left, −100 only sellers.
  - Also distance from the 52-week high and the next corporate event.
- **Header and panels:**
  - Advances/declines, the median gap, the count of gaps beyond ±2%, the value matched, and a gap-distribution
    histogram.
  - Your watchlist and pinned stocks, plus four leader boards (gap up, gap down, buyers left, sellers left).
    The leader boards only count stocks with ≥ ₹10 L matched, so illiquid names don't top them on a handful of
    shares.
- **Refresh:** every 20 s from 09:00 to 09:16. Outside that window, NSE keeps the last session's final book and
  the page says so.
- **BRIEF:** the Market panel has a "Pre-open F&O" line (advances/declines plus the biggest gaps) linking to PRE.
- **Archive:** each session's final book is archived daily by a 09:09 scheduled job. The order imbalance exists
  in no EOD file, so this builds a dataset that can be researched later. It's not a signal yet.

Files: `services/data-service/preopen.py` (`GET /db/preopen`), `GET /api/market/preopen`, `ui/components/PreOpen.tsx`,
`tests/unit/test_preopen.py` (3 tests), `scripts/master_controller.py` (`preopen_capture`).

### DEAL: block & bulk deals (from GO: `DEAL`)
- **What it shows:** every named-client bulk and block deal on NSE over 1/5/10/30 days (≥ ₹10 L / ₹1 cr / ₹10 cr).
  Each client is netted per stock per day, so intraday round trips drop out.
- **Columns:** client, side, quantity, average price, value, the deal's share of that day's volume (amber at
  ≥ 25%), the move since the deal day's close, and the stock's next corporate event.
- **Tags and clicks:** mutual funds, insurers and pension funds are tagged MF/INS. Clicking a client name filters
  to every deal that client made.
- **Header:** money bought and sold, the MF/insurer share, and the biggest net flows per stock. Same-group
  cross-trades (a fund buying from its sister fund) net to zero there.
- **Research:** the page opens with the H3 note. Non-institutional bulk buying was followed by lagging returns;
  MF/insurer buying was promising. The Desk filter built on it stays OFF.
- **Definitions:** the netting and the institution rule are the research code (`shared/deal_filters.py`), so the
  page and the studies agree.

- **Most active clients:** a leaderboard of who traded the most in the window (gross value, net buy or sell,
  MF/insurer tag); click one to filter.
- **Fix (12 Oct evening):**
  - NSE lists a large block deal again in the bulk-deal file, so the same trade was counted twice in the totals.
    Example: Quant MF selling ₹101 cr of JUBLPHARMA to Abakkus.
  - Duplicates are now dropped (the block row is kept). The 10-day totals fell from ₹1,898 cr to ₹1,542 cr bought.
  - The H3 research used bulk deals only and is unaffected. The stock Profile's deals box had the same double
    count and is fixed too (tested).

Files: `GET /db/deals`, `GET /api/market/deals`, `services/data-service/deals_monitor.py`,
`ui/components/DealsMonitor.tsx`, `tests/unit/test_deals_monitor.py` (3 tests).

### WEI: world markets (from GO: `WEI`)
- **What it shows:** the global cues before 09:15, in 37 instruments across seven groups:
  - India;
  - Americas, Asia-Pacific and Europe indices;
  - currencies (USD/INR, the dollar index, EUR, JPY, CNY);
  - commodities (Brent, WTI, gold, silver, copper, natural gas);
  - US yields and crypto.
- **Columns:** price, change, change %, a one-month sparkline, where the price sits in today's range, and the
  time since the last print. Closed markets show their last close.
- **Header:** the biggest moves among markets that printed in the last 18 hours. A closed market's stale change
  is not news.
- **BRIEF:** the Market panel has a one-line "Global cues" summary (S&P, Nikkei, HSI, Brent, USD/INR) that links
  to WEI.
- **Data:** Yahoo Finance, delayed, refreshed every 60 s, through the news-scanner quotes endpoint. There is no
  new backend.

- **GIFT NIFTY:** the overnight cue for the NIFTY open. It's the top row of the India panel, with the gap it
  implies vs NIFTY's last close. It leads BRIEF's "Global cues" line ("GIFT +0.06%") and the MARKETS tape at the
  top of every page.
  - Source: NSE's own market-status feed. GIFT trades 06:30–15:40 and 16:35–02:45 IST, and the feed kept
    updating at 18:13 after NSE's close, which confirms it is GIFT and not NSE's own future.
  - Refreshed every minute, including evenings. Endpoint: `GET /api/market/gift-nifty`.
- **US Fed (FOMC) dates:** a strip at the top with the next four decision dates, read from federalreserve.gov
  and cached a day. ★ marks meetings with economic projections (the dot plot), and the first entry counts the days
  down. Decisions land around 23:30 IST, or 00:30 IST the next day in US winter. BRIEF's "Global cues" line adds
  "Fed in Nd" when it is within two weeks. Endpoint: `GET /api/market/fomc` (parser tested, incl. "Apr/May" meetings).
- **RBI policy (MPC) dates** sit next to the Fed's: next decision 4 Dec, about 10:00 IST.
  - Taken from RBI's own schedule (press release of 23 Mar 2026, verified on rbi.org.in), stored with its source
    in `data/reference/rbi_mpc.json`. Add next year's dates when RBI publishes them in March.
  - BRIEF shows "RBI in Nd" within two weeks.
- **India 10-year G-sec:** in the Rates panel, from NSE's 10-year benchmark G-sec clean-price index, labelled
  PRICE with a "yields up / down" note. There is no free live yield feed, so it shows the price; a falling price
  means rising yields.

Files: `ui/components/WorldMarkets.tsx`.

### Markets tab (MKT): Market Monitor
"How is the Indian market today", built from NSE's own end-of-day files (1,409 liquid stocks, ETFs
excluded, survivorship-free):
- **Regime score 0–4** (Scanner Handbook stage 2), with each of the 4 checks shown as pass or fail, an
  exposure guide and how long the score has held. It is a health gauge, not a buy signal: in the handbook
  backtest, breakouts bought on score-4 days did worst.
- **Breadth tiles:**
  - index vs its 200-DMA;
  - advances/declines;
  - % of stocks above their 20/50/200-DMA;
  - new 52-week highs vs lows;
  - Stockbee ±4% Market Monitor ratios;
  - distribution days;
  - India VIX and its 1-year percentile.
- **One-year breadth chart:** index, % above 50-DMA, % above 200-DMA, and a coloured regime strip.
- **Industry heatmap:** 1D/1W/1M/3M equal-weight returns and the share of stocks above their 50-DMA. Sortable.
- **Industry drilldown:** click any industry in the table to list its most traded stocks with 1D/1W/1M
  returns; click a stock for its profile.
- **Six mover lists:** gainers, losers, most active, volume shockers (≥ 3× average), new highs, new lows.
  Click a row to open the stock. A violet **RESULTS** tag marks movers whose move was their results-reaction
  session.

Files: `services/data-service/market_monitor.py`, `GET /db/market-monitor` (cached per bhavcopy date),
`GET /api/market/monitor`, `ui/components/MarketMonitor.tsx`. Tests: `tests/unit/test_market_monitor.py`.

### Market map (MKT tab): Bloomberg-style heatmap
- **What it is:** the 250 most traded NSE stocks as a treemap grouped by industry. Tile size is turnover;
  colour is the 1D / 1W / 1M return.
- **Use:** industry averages in each header, hover for details, click a tile to open the stock.

**Industry rotation (RRG)**, also on MKT: each NSE industry's relative strength vs the equal-weight universe
(→) against the momentum of that strength (↑), with 8-week tails. Quadrants: Leading / Weakening / Lagging /
Improving, plus a side list. Hover an industry to highlight its path. It shows sector leadership for the
momentum book; it is not a trading signal.

**Who holds index futures**, also on MKT, from NSE participant-wise OI:
- FII / DII / Pro / Client long, short, net and long %, net changes over 1 and 5 sessions, and index-options
  bullishness;
- a one-year chart of the FII long ratio.

Friday: FIIs only **9.6% long** (net −2.94 L contracts) against clients 82% long. The four nets sum to zero,
as futures must; that is checked.

I also tested whether this predicts NIFTY (pre-registered, 2019–2026). **It doesn't**, over 5–20 sessions:
neither the flow nor extreme FII shorting (`reports/fii_positioning/`). The panel says so.

**Fix found while building it:** the breadth universe included **107 ETFs** (NIFTYBEES, GOLDBEES, LIQUIDBEES…).
They are now excluded with the Desk's own ETF rule, so the universe is 1,409 real stocks, and every breadth
number and the regime score now measure stocks only.

### Events tab (EVTS): Corporate Calendar
Bloomberg's EVTS for NSE: what's coming up for every listed company, from three free NSE feeds (event
calendar, board-meeting intimations with the filing PDF, corporate actions).
- **Your stocks:** events for your ICICI holdings, Desk positions, watchlist and pins. Each row is tagged
  HELD / DESK / WATCH / PIN.
- **Results scoreboard:** everyone who reported in the last 10 days and how the market took it, with a season
  summary (how many beat or lagged NIFTY, and the average reaction). It shows the
  reaction (on the correct session for the release time), the move vs NIFTY, the stock's typical results move,
  and **size vs normal** (e.g. 3.1× flags an unusual reaction). Unreacted releases show as "pending".
- **Typical move column:** for every upcoming result, the stock's average results-day move over its last 8 quarters.
  It's also in the BRIEF "This week" list and in the event-badge tooltips.
- **Next five weeks:** a weekday calendar with the busiest names per day. Click a day to filter.
- **All events:** results, dividends, bonuses, splits, rights, buybacks, fund raises and M&A. Filter by type,
  "liquid only" (≥ ₹5 cr/day) or text. Shows turnover, last close, the record date for ex-dates, and a
  FILING ↗ link. Click a row to open the stock.
- **Freshness:** a new `nse_events` table, pulled by the EOD pipeline. It also refreshes itself in the
  background if older than 12 h, and the page never waits for NSE.
- **History:** past events are kept with `first_seen`, so the table builds a point-in-time history. That
  enables research on how stocks move after results.
- **First pull:** 313 events, including Q2 results season (HCLTECH 12 Oct, TCS 14 Oct, INFY 23 Oct…).

Files: `services/data-service/nse_events.py`, `POST /jobs/ingest-nse-events`, `GET /db/events`,
`GET /api/market/events` (merges duplicates across feeds), `ui/components/EventCalendar.tsx`.
Tests: `tests/unit/test_nse_events.py`, `services/ui-api/tests/test_markets_research.py`.

### Research tab (RSCH): Research Library
All 23 studies in one place. Each has a verdict chip (ADOPTED / PASS / PROMISING / FAIL / NO EDGE /
REFERENCE), a one-line bottom line, the full report rendered in the terminal style, and its CSV/JSON
data files to download. Filter by verdict or search. Verdicts are curated in
`services/ui-api/routers/research.py` (CATALOG). New reports appear automatically with verdict "—".
Files are served read-only, and only from inside `reports/` and `docs/` (path traversal is rejected; tested).

### News Terminal: TRACK RECORD (Shift+N → ▦ TRACK RECORD)
- **Honest record:** how every past scanner pick did after it was flagged. Entry is the next session's open;
  each pick is measured against NSE stocks of similar liquidity, after the real ICICI round-trip cost.
- **The view:** a verdict banner, a table by holding period, best and worst picks, and splits by conviction,
  news age, the move before the scan, theme and scan date.
- **Previously flagged:** a strip on any pick the scanner chose on an earlier date, showing how it did since then.
- **Current state (259 picks, 15 scans, 25 Sep → 11 Oct):**
  - Too early for a verdict (9 scan days at 5 sessions; a first read needs ≥ 10).
  - So far the picks behave like similar stocks: 43% beat them, and the average is −2.6% after costs over 5 sessions.
  - Only conviction 6–8 picks beat similar stocks more often than not (56%, +0.74%), and they still lose
    after costs.
- **Files:** `scripts/news_scan_performance.py` now also writes `reports/news_scanner/track_record.json`;
  served at `GET /api/news-scanner/track-record`; UI in `ui/components/news/TrackRecord.tsx`.

### Gold desk: accuracy log (Commodity tab)
- **Purpose:** checks whether the gold model works and sizes the ₹300 chase limit with evidence instead of a guess.
- **Daily record (Mon–Fri):** master-controller saves the fair open at **08:45 IST**. At 09:10 it fills in the
  actual MCX open from ICICI. Without an ICICI session, type the open in the panel.
- **The panel shows:** typical model miss, % of days within the chase limit, bias, and model vs naive
  ("open = yesterday's settlement").
- **Alert:** the 08:45 snapshot also sends "fair open ₹X (+Y vs settlement)" as an info alert.
- **First real row:** Monday 12 Oct.
- **Honesty fix:** on weekends, and before ICICI's ~07:30 file, the baseline is the session before last. The
  desk now says so: the fair open is still valid, but the gap includes the last session's move.

Files: `services/ui-api/routers/gold_preopen.py` (`/gold-preopen/snapshot`, `/capture-open`, `/actual`, `/log`;
`data/gold_preopen/log.json`), `scripts/master_controller.py` (`gold_preopen_snapshot`, `gold_open_capture`),
`ui/components/GoldAccuracyLog.tsx`. Tests in `services/ui-api/tests/test_gold_preopen.py`.

### Stock window → Profile tab (Bloomberg DES)
Open any stock (click a ticker, or `/` → `TCS`) → **Profile**. One page from NSE's own files:
- **Price:**
  - split/bonus-adjusted returns 1W–1Y, the 52-week range bar, above/below the 20/50/200-day averages;
  - ATR, turnover, volume vs average;
  - **delivery % today vs its 20-day average**;
  - which corporate actions were adjusted.
- **Ownership:** promoter / FPI / MF / retail share with an 8-quarter trend, the change in percentage points,
  and the number of shareholders.
- **Positioning:** futures open interest and its 20-day change, basis, put/call OI, and **MTF** (shares bought
  on margin) with its 20-day change.
- **Insider trades:** last 12 months, with net *on-market* buying. Off-market transfers and pledges are
  excluded, and this is tested.
- **Bulk & block deals:** last 6 months, net buying; short-sale disclosures as a one-line summary.
- **Coming up:** results and ex-dates with the filing link.
- **Trade ticket:** enter an amount, a stop multiple and your capital. You see:
  - the shares;
  - ICICI's real round-trip charges, itemised (brokerage, STT, GST, DP, stamp…);
  - the breakeven move;
  - an ATR stop with the ₹ loss and % of capital if it is hit;
  - the tax on a +10% gain, short vs long term.

  It uses exactly the cost model the backtests use (`shared/trading_costs.py`, `GET /api/costs/ticket`). It
  shows why small positions are expensive: below ₹25,506 a round trip costs more than 1%.
- **Results history (ERN):** how the stock moved on each of its last 12 quarterly results.
  - Release timestamps come from NSE's two results feeds: the classic one up to early 2025, then SEBI's
    integrated filing.
  - The reaction session follows the release time: pre-open or market hours → that session; after 15:30 →
    the next session.
  - Each row shows the move, the opening gap and the move vs NIFTY; the summary shows the typical move, %
    up, best and worst.
  - The "Coming up" banner adds e.g. "typically ±2.1% on results".
  - Release times are stored in a new `nse_results` table (refreshed weekly per stock), ready for a
    post-results drift study.

- **Peers:** the stock's industry with its most traded names over 1D / 1W / 1M; click one to jump to it.

Also: the stock window is wider; the old "Details" tab is now "Data" (coverage diagnostics).
Files: `services/data-service/security.py`, `GET /db/security/{symbol}`, `GET /api/stocks/{ticker}/profile`,
`ui/components/StockProfile.tsx`. Tests: `tests/unit/test_security_profile.py`.

### Research verdicts where decisions are made
ML Engine, Backtest, Alpha, LW Scanner and Portfolio now open with a one-line verdict from the relevant study:
- **ML Engine:** ML trails Desk momentum after costs.
- **Backtest:** costs decide short holds.
- **Alpha:** no out-of-sample edge in the India-specific ideas.
- **LW Scanner:** the rules-only swing system lost after costs.
- **Portfolio:** this is the legacy 5-day engine; it loses ~45–50%/yr to costs, so its autopilot is OFF. The
  banner sits right next to its LIVE switch.

Each banner has **READ THE STUDY ›**, which opens it in RSCH. The aim is that nobody trades a research tool by
accident. Implementation: `<ResearchNote>` in the kit, and `goToPage()` in `ui/lib/navigate.ts`.

### Upcoming events next to every stock
The Stocks screener (EQS) and the Desk watchlist have a **Next event** column (e.g. `RESULTS 26 OCT · 15d`, amber within a week), and the stock
window header shows the stock's next results or ex-date. Know about a result before you buy. One shared, cached
fetch: `ui/lib/useCorpEvents.ts`, `<EventBadge>` in the kit.

### Click any ticker to open it
Desk orders, watchlist and positions, Broker holdings, Portfolio, Alpha and Backtest trades now open the stock
window. One global helper, `openTicker('TCS')` (`ui/lib/openTicker.ts`); `<TickerLink>` in the terminal kit.

### New scheduled jobs (master-controller, IST, Mon–Fri)
| Time | Job | What it does |
|---|---|---|
| 08:45 | Gold pre-open snapshot | records the MCX GOLD fair open (accuracy log) and sends it as an alert |
| 08:50 | Pre-market note | GIFT gap, overnight cues, FII/DII, today's events (yours first) → Mac + inbox + Telegram |
| 09:09 | NSE pre-open book capture (ran today: 2,350 stocks at 09:08:09) | archives the final pre-open book (F&O + all stocks) to `data/nse_archive/preopen/`: order imbalance is in no EOD file |
| 09:10 | Gold open capture | stores the actual MCX open from ICICI (if connected) |
| every 5 min 08:00–22:55 (Mon–Sat) | Filing alerts | new material NSE filings by your stocks → Mac notification (+ Telegram) |
| every 5 min 09:20–15:30 | Move alerts | your holdings at ±5% / ±10% on the day; NIFTY crossing its 200-DMA |
| every minute 09:15–15:30 | Price alerts | checks your WTCH alert levels; Mac notification (+ Telegram when set) |
| 19:45 | News scanner track record | re-measures every past pick (News Terminal → TRACK RECORD) |
| 20:45 | Results release capture | stores release times of results announced in the last 3 days (ERN, research) |
| 21:00 | Daily market wrap | writes `reports/daily_wrap/<date>.md` (WRAP page) and sends the one-line summary as an alert |
| EOD pipeline | NSE corporate calendar + Market Monitor rebuild | events for EVTS; the monitor cache is warm before you open BRIEF |

## Data repair: insider trades had silently stopped (found and fixed this morning)
- **What broke:** NSE's insider-trading API (`corporates-pit`) returns almost nothing after **5 May 2026**. The weekly
  job kept "succeeding" while storing nothing, so the database had no insider trades for May–October. That
  also starved the **H4b forward test** (insider buys from Oct 2026), the only PROMISING flow signal.
- **Why:** NSE circular NSE/CML/2026/11 moved insider disclosures to the single-filing XBRL system.
- **Fix:** I found the new endpoint by recording what NSE's own page calls (`corporates-pit-gg`) and wrote a parser
  for the per-filing XBRL (`nse_filings.ingest_pit_gg`, tested on a real RELIANCE filing). The weekly job now uses
  it, and May → today was backfilled.
- **Also fixed:** 4 insider rows had impossible future dates (an NSE typo, e.g. DMART "2028"). They are now capped
  at the broadcast date, at startup and in the parser.
- **Result:** 5,426 insider trades restored (May → 9 Oct 2026), continuous by month.
- **H4b forward test unblocked:** it now receives insider buys again (checked: it runs and reports "0 of 100
  events so far"). The first 20-session windows complete around 29 Oct 2026; run
  `PYTHONPATH=. python scripts/held_overnight_study.py --tests H4B` then. (I also fixed a crash in its report
  rendering when no window had completed yet.)
- **Caveat for research:** before May 2026 the table covers the ~320 liquid names fetched per stock; from May it
  covers every NSE company. Studies must use a fixed universe across that seam.
- **Documented** in `docs/NSE_DATA_DICTIONARY.md`.
- **So it can't happen silently again:** after the EOD pipeline and the weekly filings job, master-controller
  checks every NSE dataset's newest date against its expected cadence and raises a critical alert if one is
  stale. The Warehouse "NSE research datasets" panel shows the same check (OK / ⚠ STALE). Run against
  yesterday's data, it flags the insider table at 136 days stale, so it would have caught this in May.

## Fixed / polished
- **Gold desk: the 09:10 open capture now works with ICICI.**
  - The problem: Breeze answers MCX futures quotes with a server error ("Object reference not set…") whatever
    the expiry format.
  - The fix: the desk now reads the first 1-minute bar from Breeze's historical API for the open, and the last
    bar for the live MCX price.
  - Today: fair open ₹1,49,971 vs actual ₹1,51,061, an error of ₹1,090 vs ₹1,451 for the naive "previous
    settlement" guess.
- **BRIEF gold panel after 09:00:** once MCX has opened, the pre-open "chase / wait" verdict is settled, so the
  panel switches to **THIS MORNING'S CALL**: the 08:45 fair open vs the actual open, the model's miss vs the naive
  miss, MCX now vs the open, and the running track record. Before 09:00 it still shows the live verdict.
- **Your holdings are remembered when ICICI is not logged in:**
  - Every successful holdings read is saved (`data/last_holdings.json`, git-ignored). While the ICICI session has
    lapsed (each morning until a login), these keep working from the last known holdings:
    - move alerts and filing alerts;
    - the wrap's "your stocks";
    - the "your stocks" lists on BRIEF, WTCH, EVTS and CF.
  - BRIEF says "not connected · last known 4 holdings (12 Oct 18:30) · log in on Broker" instead of "holdings
    hidden". Money figures (P&L, cash) still appear only from a live ICICI session.
- **Header NIFTY was stale when ICICI is disconnected:**
  - On 13 Oct morning the header showed yesterday's close (22,363 −0.70%) under a "LIVE" badge, because it fell
    back to the last stored ICICI quote.
  - Now it uses, in order: the ICICI stream, then NSE's live index (`GET /api/market/nifty-live`, ≈1 min delayed,
    with open/high/low), then the stored ICICI quote labelled STALE. The badge names the source (● LIVE /
    ● NSE / ◌ STALE).
  - In the tape, GIFT NIFTY's difference reads "vs spot" while NSE is open, and "gap" outside market hours.
- **Missed jobs are caught up at start-up:** when the scheduler starts, it runs today's jobs that were missed
  while it was down and are still useful: the pre-open book (NSE keeps it until the next session), the morning
  note (only before 09:15), and the evening wrap (after 21:00). Tested in `scripts/tests/test_move_alerts.py`.
- **ICICI daily API limit:**
  - The problem: on 12 Oct evening ICICI answered "Limit exceed: API call per day", so every ICICI feature
    stopped for the rest of the day. The cause was the data-service's NIFTY poller calling Breeze every 5 s around
    the clock, with up to 5 symbol aliases and retries each time it failed. Every page that showed holdings also
    made 3 fresh Breeze calls.
  - The fix: the pollers now run only in market hours, every 15 s, using the alias that worked. On a daily-limit
    error they stop calling Breeze until midnight, and the quote endpoint then says why instead of returning 500.
  - Holdings/funds reads are cached for 30 s and shared by every page and scheduler job.
- **Broker cash figure:**
  - The problem: ICICI's funds API disagreed with itself between refreshes seconds apart. The same account read
    ₹13.40 L all "unallocated" on one call, and ₹6.70 L unallocated plus about ₹6.70 L allocated-and-blocked on
    the next. "Cash available" flipped between the two.
  - The fix: the page now shows ⚠ "ICICI reported ₹X / ₹Y in the last 10 min" instead of silently changing.
    Check ICICI Direct before acting on that number.
  - Also, when ICICI's funds call returns garbage (it sometimes sends a non-JSON page), the Broker page no
    longer fails with a 502. It keeps the holdings and shows the last good funds reading, marked stale.
- **NSE politeness:**
  - The live pages (MOV, live map, CF) share one NSE session and server-side caches, so any number of open tabs
    costs NSE the same few requests.
  - If NSE starts refusing us (403/429 even with a fresh cookie), the client backs off for 10 minutes and serves
    the last good copy instead of hammering it. The machine's IP can't get blocked, which would also break the
    evening ingestion.
- **Company names everywhere:**
  - The problem: the universe file had real names for only 504 of the 1,500 stocks; the rest showed the ticker,
    with industry "Unknown".
  - The fix: names now come from NSE's own reference files (EQUITY_L and the Nifty Total Market industry list).
  - Result: **1,380 names** (the remaining 120 are mostly delisted or renamed symbols) and 748 industries, in
    EQS, the GO bar, the Profile's news search and the wrap.
  - Industries for the other small caps still need a source (see the Desk industry recommendation).
- **"Move since" figures are split-safe:**
  - INSD's "since filing" and DEAL's "since deal" now use corporate-action-adjusted closes, through one shared
    store helper (`adjusted_closes` / `move_since`), so a split between the filing and today no longer shows
    as a −80% loss.
  - Same for the IPO scorecard and the risk panels (above).
- **News Scanner button:** once you've opened the latest scan, it shrinks to a small "● NEWS 11-10" pill instead
  of a large glowing button over the bottom-right of every page. It grows back, pulsing NEW, when a new scan
  arrives.
- **Gold desk speed:** after MCX opens, the live MCX price comes from Breeze 1-minute bars, and a day of bars
  takes Breeze 10–15 s. That fetch is now cached for 60 s, and Breeze's broken MCX quote call is skipped for
  10 minutes after a failure. The desk answers in about 1 s again (it was 15–18 s, which also slowed BRIEF).

  - One shared formatter (`fmtPct` in the terminal kit) replaces six copies.
  - A value that rounds to zero prints 0.0%.
- **MKT FII long-ratio chart:** it no longer forces the 50% line into the range. That line squashed the 5–20%
  series flat and overlapped its labels.
- **BRIEF:** a MORNING PAGES launcher (WEI, PRE, MOV, OMON, DEAL, INSD, IPO) in the header.
- **GO understands TICKER FUNCTION, Bloomberg order:**
  - `RELIANCE OMON` opens its option chain; `RELIANCE DEAL` (or `DEAL RELIANCE`) opens DEAL filtered to that stock
    over 30 days.
  - Typing a bare ticker now lists what you can do with it: open, OMON, DEAL, TradingView, watchlist.
- **MORE ▾ menu in the tab strip, next to ⌕ GO:** lists the nine pages outside the strip, in trading-day order
  (WEI, PRE, MOV, OMON, DEAL, INSD, IPO, WRAP, COMP), each with its code and a one-line description. When one of them
  is open, the button shows its code and is highlighted. Tabs were tightened slightly so the whole strip fits at
  1680 px.
- **Stock chart, long averages:**
  - Before: SMA 150/200 drew nothing on 3M (and only part of the line on 1Y), because only the visible
    window was loaded.
  - Now: 200 warm-up bars load before the window, so every average draws from the first visible bar,
    and you can scroll left for more context.
  - Files: `IndicatorPriceChart.tsx` (`visibleBars`), `StockDetailModal.tsx`.
- **Tab strip:**
  - Tightened so all 20 pages fit at 1680 px.
  - Added a **⌕ GO** button that is always visible.
  - The active tab scrolls into view when you jump there from the command bar.
- **Laptop screens (≤ 1480 px):** the top bar no longer wraps into 3 lines. Secondary items (stock count, data
  date, NIFTY O/H/L, weekday) hide on smaller screens; they are on the footer, Overview and the macro tape.
  The tab strip scrolls, and ⌕ GO reaches every page.
- **Desk "Book vs NIFTY" chart:** now has % gridlines, dates and end labels (BOOK +0.2% vs NIFTY −2.7%).
  Before, it was two unlabeled lines.
- **Browser tab titles** follow the page code (`BRF · SuryaDhana`, `OMON · SuryaDhana`…), which helps with several tabs open.
- **Breadth warm-up:** the "% above 200-DMA" history no longer shows a fake 0% while the averages warm up.
  The denominator counts only stocks that have the average.
- **Production UI mode:** `UI_MODE=prod ./start-local.sh restart frontend` serves an optimised build
  (pages load instantly instead of compiling on first visit). It builds into `ui/.next-prod`, so the dev
  server's `.next` is untouched, and it rebuilds only when sources changed. The default stays the dev
  server with hot reload.

## Recommendations (not done: your call)
- `ui/.next/` (98 build files) is tracked in git. It should be untracked (`git rm -r --cached ui/.next`)
  and ignored: it churns on every build and bloats diffs.
- **Desk industry cap has a blind spot.** 5 of the Desk's current top-20 (MOREPENLAB, FCL, PAISALO, AEROFLEX,
  TFCILTD) are not in `data/reference/nse_industry.csv` (the Nifty Total Market list, 756 names), so they show
  "Unknown" and the 40%-per-industry cap cannot count them. NSE's quote API (which has `industryInfo`) now
  refuses scripted requests (Access Denied, checked 11 Oct). The Microcap 250 list adds only 43 names. The
  practical fix is a small hand-kept map for names that enter the Desk's top 20. Not done, because it changes
  how the approved cap behaves and needs your review.
  - **Proposed map (12 Oct, please check before approving):** MOREPENLAB → Healthcare (Morepen Laboratories),
    FCL → Chemicals (Fineotex Chemical), PAISALO → Financial Services (Paisalo Digital, NBFC), AEROFLEX →
    Capital Goods (industrial flexible hoses), TFCILTD → Financial Services (Tourism Finance Corp., NBFC).
  - **Effect on today's top 20:** Capital Goods goes from 7 to **8 of 20 = exactly the 40% cap** (a 9th
    industrial would then be skipped). Healthcare goes to 4, Financial Services to 2, Chemicals to 1. No other
    industry comes near the cap.
  - The DESK page's "Watchlist risk" panel shows the live counts.
- **Telegram alerts are not configured.** `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are empty in `.env`, so no
  alert reaches your phone: not the scheduler failures, the Desk fills, or the new 08:45 gold fair-open message.
  Create a bot with @BotFather, put both values in `.env`, then `./start-local.sh restart master-controller`.
- **ICICI auto-login: the user ID / password in `.env` are being rejected.**
  - What happened: this morning's 08:00 login got "Invalid Credentials" from ICICI right after the user ID +
    password step, before the 6-digit code. Your manual login works, so `ICICI_CLIENT_ID` or `ICICI_PASSWORD`
    in `.env` is out of date (or the login ID differs from the customer ID).
  - Guard added: brokers lock accounts after a few wrong passwords, and every master-controller restart used to
    try again. Unattended runs now stop after a credentials rejection (`.icici_login_block.json`, git-ignored).
    The block lifts by itself when the credentials in `.env` change, or run
    `python scripts/daily_session_refresh.py --force` once.
  - Still needed: `ICICI_TOTP_SECRET` for fully unattended logins. Until both are fixed, the Broker tab, the
    ICICI holdings in BRIEF/WATCH/EVTS, and the 09:10 gold capture need your manual daily login.
