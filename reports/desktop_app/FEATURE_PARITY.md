# SuryaDhana: web app vs desktop app, feature by feature

Audit date: Sunday 25 Oct 2026 (IST). Eight auditors compared three setups on the same live backend data:

- **Web before**: the web app as it was before today (reconstructed pre-program UI, proven byte-for-byte), on a read-only copy at :8090.
- **Browser now**: today's UI release `20261025-153533-0ae66db` in an ordinary browser (what you get at http://127.0.0.1:8010).
- **Desktop app**: the same release inside the app's engine (WebKit) with a simulated app shell, plus evidence from the real `/Applications/SuryaDhana.app`: its self-test, its log, its settings files, and a copy of the newer build run only in self-test mode.

Every regression and serious pre-existing bug was re-checked by a separate verifier. Where a verifier corrected a status, this report uses the corrected one. Nothing on the live stack was changed: writes were refused on both sides, and anything that needed a write ran on scratch servers or in-process with temporary stores.

Evidence lives under `$S` = `/private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/a24906e4-7b64-46ba-b24b-14c536f43922/scratchpad/` (folders `eq-login`, `eq-data`, `eq-pages-1`, `eq-pages2`, `eq-pages3`, `eq-cross`, `eq-native`, `eq-backend`, and the `eq-v*` / `eq-verify*` verifier folders). It is in /tmp, so it may be cleared by a reboot.

---

## 1. Verdict

1. **Yes, the desktop app does everything the web app did.** All 42 pages show the same data, the same dates and the same numbers, send the same API requests, and offer the same actions. The only differences in the browser view are the documented intended ones (2-decimal prices, PAPER ONLY on PORT, honest closed-market labels, and so on).
2. **The backend is shared and unchanged in behaviour.** Login, the Telegram OTP relay, the 08:00 job, data jobs and the scheduler work as before. Every internal caller still gets through the new Host/Origin guard (32 request shapes replayed).
3. **Better in the app:** it starts at login with a clear boot screen for every failure; it has a menu-bar NIFTY/ICICI/Desk line, a native Go menu with ⌘1–⌘9, multiple windows, session restore, and working Back/Forward. A failed panel no longer blanks the whole terminal, pages reload after an outage, and exports are byte-identical. The ICICI login URL (which contains the API key) is no longer printed on screen.
4. **Worse, major (3 confirmed):**
   - (a) If one window's WebKit page process dies, the **whole app crashes**. A browser loses only that tab.
   - (b) In the app, DESK **"Re-enable after review" clears the −20% emergency stop without asking.**
   - (c) OMON's OI chart labels the **wrong strike as CALL/PUT WALL** (in the app and in the browser).
5. **Worse, minor (7):** OVRV shows invented zeros before it loads; COMP brings back a removed symbol; the settings reminder bar covers buttons; a stock window during LINK DOWN slides under the header; exports give no visible confirmation in the app; there is no ⌘F/⌘P in the app; the Muhurat session (8 Nov) will be shown as CLOSED. **Nits (3):** DERV axis labels, a red "0.0%" on the market map, and the Back/Forward hint in a Mac browser.
6. **Already broken before today (not caused by the conversion):** the biggest is GO "RELIANCE OMON" showing the NIFTY chain (67–85% of tries, in every setup). Others: ui-api freezes for 10–40 s while it checks a new ICICI token; MOV's movers table freezes if it was opened before 09:15; the news-scanner track record has been frozen since 14 Oct; and the 25 Oct backup was missed.
7. **9 of the 13 confirmed regressions already have a fix (full or partial) in the working tree, but none is released yet.** They need `./start-local.sh build-ui`. No fix exists yet for: the app crash, the DESK confirm, export feedback, and Find/Print.
8. **Needs you:** the Monday 08:00 ICICI login with an SMS OTP (no TOTP secret is stored); allowing macOS notifications for SuryaDhana (currently DENIED, so no app banners appear at all); moving your settings across from :3000 (not done yet); and one ⌘V test in the app.
9. **Data is up to date:** the latest stored session is Fri 23 Oct everywhere it should be. ICICI is expired, which is normal on a Sunday. LIVE_TICKS is OFF.
10. **Do not install the newer build** sitting in `desktop/src-tauri/target`: its own self-test crashes. Keep the installed app.

**Status counts** for the section 5 matrix (328 features, with duplicates across auditors merged and verified statuses used):

| Status | Count | Meaning |
|---|---|---|
| SAME | 146 | Works exactly as before |
| IMPROVED | 75 | Better, and intended |
| DIFFERENT-INTENDED | 36 | Changed on purpose |
| REGRESSION | 13 | Worse than before: 3 major, 7 minor, 3 nit |
| BROKEN-IN-BOTH | 41 | Bug that was already in the web app: 1 major, 28 minor, 12 nit |
| NEEDS-OWNER | 13 | Only you can confirm or decide |
| NOT-APPLICABLE | 4 | Nothing to compare |

---

## 2. Opening the app, step by step

| # | Step | What happens | Works today? | Only confirmable Monday |
|---|---|---|---|---|
| 1 | You log in to the Mac | Two login jobs run. The stack watchdog starts data-service, ui-api and master-controller and keeps the Mac awake. `SuryaDhana.plist` starts the app with `--autostart`; it relaunches the app 20 s after a crash, never after ⌘Q. With FileVault on, nothing runs until you are past the login screen. | Both jobs are loaded and running (app pid 83455, never exited). | The first **real** login since "Launch at Login" was enabled: the Mac has not rebooted since 10:57, and the app job was enabled at 11:46. Check it at your next login. |
| 2 | App opens: boot screen | Shows "Starting the stack" for up to 180 s after login, then the terminal as soon as ui-api is ready. If something is wrong it shows a specific screen (down, ui-api NOT RESPONDING, no UI release, not served, untrusted or unverifiable listener) with the right action. | Every boot screen tested on scratch servers; boot-page checks 62/62. Process start → terminal ≈ 2 s on the real app (log 15:39:19 → 15:39:21). | — |
| 3 | Terminal loads | The same UI release as the browser (`20261025-153533-0ae66db`) loads from ui-api :8010. Your last windows, pages, open stock window and zoom are restored. | Yes ("restored 1 window(s)" at every start). | — |
| 4 | ICICI session state | Shown on the boot screen row, the menu-bar line, the red/green header ICICI light, the BRKR panel and the BRIEF line. | All say **"expired: send /login in Telegram"**, which is correct (Friday's token expired; last good login Fri 23 Oct 08:08:17). | Caveat: a network blip to ICICI also shows as "expired" (section 6, P4). |
| 5 | Unattended login + OTP | At 08:00 the controller logs in headless with your user ID and PIN. No TOTP secret is stored, so it switches to SMS OTP and asks on Telegram. You reply with the 6 digits. The token is posted to ui-api (the guard admits it), ui-api saves it, checks it with Breeze (ui-api pauses 10–40 s; a LINK DOWN banner may flash) and pushes it to data-service. | Every HTTP step was replayed through the real guard and passes. The 08:00 job is scheduled for Mon 26 Oct 08:00 and runs even with autopilot OFF. The real login was not run (agents may not). | **Yes:** the real OTP round trip, the "ICICI session refreshed" message, and every surface turning green. |
| 5b | Manual login fallback | BRKR → LOG IN TO ICICI ↗ opens your default browser. Log in, copy the redirect address (…?apisession=…), paste it into BRKR, press Connect. | Opening the login page works in the real app (log 16:51:03 today). | Whether ⌘V pastes into the BRKR box inside the app has never been observed. |
| 6 | Live data | From 09:00 to 15:35, and only while ICICI is connected, data-service polls NIFTY and your watchlist every 15 s into Redis. ui-api pushes the quotes to every window: header "● LIVE", WTCH "● STREAMING", menu-bar NIFTY. LIVE_TICKS is OFF, so the Breeze L1 tick store stays idle. | The WebSocket plumbing works: handshake 17 ms, subscribe acknowledged, ping answered, one shared Redis subscription. No quotes today (Sunday, ICICI expired). | **Yes**, at 09:15. The watchlist poller has nothing to poll until your settings are migrated (the server watchlist is empty). |
| 7 | Evening | 18:30 EOD pipeline, 19:30 Desk, 19:50 S1 shadow. | Friday's runs all landed (files dated 23 Oct). | Windows left open keep showing "DATA 2026-10-23" until reloaded (pre-existing). Reload after about 18:45. |

---

## 3. Monday 26 Oct, 08:00–09:30 IST checklist

**Tonight (Sunday), recommended:**
- Move your old settings across: open http://localhost:3000 once **in the browser you used before**, then run `./start-local.sh status` and check that the prefs row says "imported". Then run `./start-local.sh stop frontend`. The app's reminder is already dismissed, so it will not prompt you.
- Allow notifications: System Settings › Notifications › SuryaDhana › Allow, or WTCH → ENABLE DESKTOP NOTIFICATIONS.

**Monday:**

| Time (IST) | What happens | What you do / check |
|---|---|---|
| 02:15 | Nightly backup. This one also writes the **first** settings-store backup. | Any time Monday: `ls data/backups/duckdb/` should show `ui_prefs-20261026.sqlite` and `market-20261026.duckdb`. |
| Before 08:00 | Mac on, logged in, awake; phone with SMS signal and Telegram. Until the login, "expired" in the tray and on the boot screen, a red header ICICI light and BRKR "NOT CONNECTED" are all normal. | **Do not restart data-service or master-controller between 07:45 and 09:20**, and never kill a running `daily_session_refresh` or headless Chrome. Optional: send /login any time after 07:00. The 08:00 job then finds a valid token and does nothing. |
| 08:00 | `icici_session_refresh` starts: it tests Friday's token, then logs in headless and switches to SMS OTP. Filing alerts also start (every 5 min). | — |
| ~08:01 | Telegram: "🔐 ICICI login: an OTP was sent to your phone ending NN. Reply with the 6 digits within 5 minutes (or /otp 123456)." | Reply with just the 6 digits (pasting the whole SMS also works). The bot answers "Got the OTP. Submitting it to ICICI…". |
| ~08:02 | ui-api saves the token and checks it with Breeze. ui-api is frozen for 10–40 s; open windows may show "LINK DOWN … ui-api unreachable", then "LINK UP … reloading". | Nothing. This is expected (pre-existing issue P2). |
| ~08:02 | Telegram: "🟢 [INFO] ICICI session refreshed — logged in, token applied via ui-api". | Check the app: tray "ICICI — connected" within 60 s; header light green within ~30 s; BRKR "● LIVE · ICICI BREEZE" with holdings and funds within 15 s; BRIEF "ICICI session connected". |
| ~08:03 | — | Optional terminal checks: Telegram /status says "🟢 ICICI session connected"; `grep icici_session_refresh .logs/master-controller.log \| tail -3` shows "refreshed: logged in, token applied via ui-api"; `curl -s localhost:8001/provider/status` shows connected true. **Do not curl `/api/positions/connection-status`**: its body contains the login URL with your API key. |
| If no OTP within 5 min | You get "⌛ No OTP received in time…", a "🔴 [CRITICAL] ICICI login needs you" alert and a macOS notice. | Send /login and reply with the new code. If ICICI rejects the user ID or password: /password YOUR_PIN (your message is deleted at once) or /userid, then /login. |
| If Telegram says "refreshed" but the app still says expired | ui-api did not take the token; it went to .env only (pre-existing issue P3). | Restart ui-api (allowed any time): `./start-local.sh restart ui-api`. If live quotes stay off, restart data-service **after 09:20**. |
| Manual fallback | — | BRKR → LOG IN TO ICICI ↗ → paste the redirect URL → Connect. If ⌘V does not paste inside the app, use http://127.0.0.1:8010/?tab=broker in a browser. Use either Telegram or the manual login, not both: each login ends the previous token. |
| 08:30 | Pre-market sync. | — |
| 08:45 | Gold pre-open snapshot. Friday's MCX settlement becomes known from Monday's ICICI price band. | CMDT/MCXG show a fresh baseline. |
| 08:50 | Morning note (Telegram). | — |
| 09:00 | Pre-open. data-service pollers start (only if ICICI is connected): NIFTY every 15 s. | — |
| 09:09:30 / 09:10 | Pre-open book capture; gold open capture. | — |
| 09:15 | Market opens. | In the app: strip "NSE OPEN · CLOSES 15:30"; header chip "● LIVE" (or "● NSE": hover it and check the time is today); tray no longer says "· closed"; WTCH "● STREAMING". Optional: `redis-cli PUBSUB NUMSUB live.quotes` ≥ 1 and "NIFTY tick published" in `.logs/data-service.log`. **If MOV was open before 09:15, switch to another page and back** (pre-existing bug P5). |
| 09:20 | Freeze window ends. Move alerts start. | Restarting data-service is allowed again if needed. |

**Later on Monday:**
- 18:30–21:15 is a freeze window: no data-service or master-controller restarts.
- After about 18:45, reload open windows (⌘R) or switch pages, so the footer shows DATA 2026-10-26.
- The 19:45 news track-record job will fail again (P6).
- Do not click DESK "Re-enable after review" inside the app (R2).

---

## 4. Data freshness (as of Sun 25 Oct, about 17:30 IST)

All 42 pages show the same as-of dates in the web before, the browser now and the desktop app. Each value below was checked against the backend directly.

| Dataset | Latest stored | Expected? | Where you see it | Note |
|---|---|---|---|---|
| NSE EOD bars | Fri 23 Oct | Yes (weekend) | footer DATA, CHRT, WHSE | 1,374 of 1,374 eligible tickers current; 0 sessions missed |
| NSE bhavcopy panel | 2010-01-04 → 23 Oct (8,226,913 rows) | Yes | WHSE, research | |
| F&O, participant OI, bulk/block deals, insider trades | 23 Oct | Yes | OMON, DERV, DEAL, INSD | |
| Results / FII-DII cash | 23 Oct (results to 20:39) | Yes | EVTS, BRF | |
| MTF (margin) | 22 Oct | Yes (NSE publishes a day late) | MRGN | |
| Shareholding | 19 Oct | Yes (quarterly) | HDS | |
| Events calendar | to 16 Nov | Yes | EVTS, ECO | refreshed 25 Oct 15:37 |
| Market monitor (breadth, regime) | 23 Oct | Yes | MKT, BRF | |
| ML features / labels | 23 Oct / 15 Oct | Yes (label horizon) | WHSE, DEXP | |
| Decision Desk NAV | 23 Oct, ₹5,02,085 (+0.42%) | Yes | DESK, BRF, menu bar | |
| S1 paper shadow | 23 Oct, NAV 100.00, armed and flat | Yes | alpha_lab status | |
| MCX gold | settlement 22 Oct (band midpoint); COMEX 24 Oct 02:29; INR 25 Oct 09:00 | Yes | CMDT, MCXG | Friday's settlement arrives with Monday's 08:45 band |
| Pre-open book / live movers | 23 Oct 09:09:05 / 23 Oct 16:00 | Yes | PRE, MOV | |
| Alerts feed | 23 Oct 21:00:07 | Yes | ALRT, bell | |
| NIFTY last print | 22,600.00 (−0.39%), 23 Oct 15:30 | Yes | header, menu bar ("· closed") | |
| News-scanner scans | to 25 Oct | Yes | BRF | |
| News-scanner **track record** | **14 Oct** | **No** | BRF ("270 picks", no date shown) | The job has crashed every evening since 15 Oct (P6) |
| ICICI holdings snapshot | 14 Oct 15:13 | Old, but labelled stale | RSK | refreshes after a login |
| ICICI session | expired; last good 23 Oct 08:08:17 | Yes (Sunday) | header, BRKR, tray, boot screen | Monday 08:00 login |
| Live ticks | none; LIVE_TICKS OFF; Redis watchlist set empty | Yes | header, WTCH | watchlist fills after migration |
| DuckDB backup | market-20261024 | **No 25 Oct backup** | — | Mac was off at 02:15; not caught up (P7) |
| Settings-store backup | none yet | Yes (new) | — | first one Mon 02:15 |
| Scheduler job history | blank after today's restarts | Pre-existing gap | SYS shows "—" | (P-list) |

---

## 5. Feature matrix

How to read it:
- "Web app before" is the old web app.
- "Desktop app now" is the app; the browser on :8010 today behaves the same unless the note says otherwise.
- Statuses: SAME · IMPROVED (intended, documented) · DIFFERENT-INTENDED · REGRESSION (worse, not intended) · BROKEN-IN-BOTH (pre-existing bug) · NEEDS-OWNER · NOT-APPLICABLE, with severity after "·" where relevant.
- Verified statuses are used throughout.

### 5.1 Start-up and boot (desktop only)

| Feature | Web app before | Desktop app now | Status | Note |
|---|---|---|---|---|
| Launch at macOS login | Nothing opened; you opened a bookmark | Login job starts the app; relaunches it after a crash | IMPROVED | Not yet seen at a real login (no reboot since it was enabled) |
| Processes at login and terminal address | Watchdog also started the :3000 web server; terminal at localhost:3000 | 3 core services only; app and browser use 127.0.0.1:8010 | DIFFERENT-INTENDED | :3000 is up today only from a manual start and goes at reboot; update bookmarks |
| Time to a usable terminal | No boot screen; first paint about 80 ms | Boot paint about 420 ms; boot → terminal 99–123 ms; process start → terminal about 2 s | IMPROVED | self-test + real app log |
| Right after login ("Starting the stack") | Browser "can't connect" for 1–4 min | Calm starting screen with per-service progress, up to 180 s | IMPROVED | |
| Stack down | Browser error page | Down screen with Start stack, Open logs, Retry | IMPROVED | |
| ui-api hung | Spinner until timeout | NOT RESPONDING screen naming the fix | IMPROVED | the real 14:41–14:48 hang was reported |
| No UI release published | Not possible | Screen names the build-ui / --rollback command | IMPROVED | |
| Server answers but / returns 503 | Not possible | TERMINAL NOT SERVED shown correctly | IMPROVED · nit | the self-test wrongly reports FAIL (selftest.rs:1572) |
| Another program listening on the port | Browser rendered whatever answered | App refuses and names the process | IMPROVED | |
| Listener whose program file was deleted | n/a | "unverifiable" screen | IMPROVED | newer build only; not in the installed app |
| Other boot screens (privacy block, stopped on purpose, no watchdog, page stopped, reconnecting, stale NIFTY) | n/a | 62/62 boot-page checks pass | IMPROVED | the installed app ships an older boot.js |
| ICICI, NIFTY and Desk rows on the boot screen | Only visible on PORT/BRKR | Rows match the live APIs | IMPROVED | |

### 5.2 Menu bar, menus, windows and keyboard

| Feature | Web app before | Desktop app now | Status | Note |
|---|---|---|---|---|
| Menu-bar NIFTY title and status lines | None | "NIFTY 22,600.0 ▼0.39% · closed", services, ICICI, Desk NAV, build | IMPROVED | 1 decimal (pages use 2); brief "stale" flaps under heavy load |
| Menu-bar actions (Open, New Window, Go, Show Latest Download, Start/Stop Stack, Logs, Launch at Login, Quit) | Shell commands only | Present; Stop Stack asks first and is refused in freeze windows | IMPROVED | not clicked on the real app |
| Go menu with all 42 page codes | GO bar and tab strip | 42/42 land on the right page | IMPROVED | same ids, codes and order as the UI |
| Page shortcuts | Alt+1…9, Alt+0 | ⌘1…⌘9 (same pages); Alt keys still work | IMPROVED | ⌘0 is Actual Size; PORT stays on Alt+0 |
| Open the GO bar ("/", Ctrl/⌘K, header button, Esc) | Works | Works; also Go ▸ GO Bar… | SAME | |
| Back / Forward | Browser Back left the terminal | Every page and stock window is a history step; ⌘[ ⌘] in the app | IMPROVED | also in the browser now |
| Back/Forward hint in a Mac browser | No hint | Browser help and footer teach Alt+←/→, which does nothing on a Mac | REGRESSION · nit | app shows ⌘[ ⌘] correctly; fixed in working tree |
| Zoom | Browser zoom | ⌘= ⌘− ⌘0 per window, 50–200 %, remembered | SAME · nit | ⌘+ (with Shift) is not an alias |
| Settings ⌘, Help menu, About with build id | None | Present; shortcut list matches the menus | IMPROVED | |
| Edit menu (cut, copy, paste, select all) | Browser | Present | SAME | |
| ⌘V into an input inside the app (BRKR token box) | Works | Menu item present; never observed in the real app | NEEDS-OWNER · minor | try it once |
| Find ⌘F and Print ⌘P | Browser Find and Print (a print stylesheet exists) | Neither exists; the keys do nothing | REGRESSION · minor | EQS, DEAL, FUND and CF have search boxes; the browser on :8010 still has both |
| Window title | "SuryaDhana Terminal" until a page switch | Native "<CODE> · <page> — SuryaDhana" | IMPROVED | |
| BRF title says "Morning brief" on an EVENING BRIEF page | GO bar label already said "Morning brief" | Native title (Window menu, Mission Control) says the same | BROKEN-IN-BOTH · nit | verifier: pre-existing fixed label |
| Title strip (code, IST clock, session, UI/DATA/CTRL dots, build) | None | Present | IMPROVED | |
| More windows (⌘N, ⌥⌘N, GO Shift+Enter, ⧉ NEW WINDOW, ⌘-click a tab) | Browser tabs; Shift+Enter navigated in place | App windows, up to 8 | IMPROVED · nit | the 8-window cap is silent; Shift+Enter on "TCS DES/FA/ERN/HP/SEAG" stays in place |
| ⌘-click or middle-click on a ticker link | Same window | Same window | SAME · minor | round-1 fix R-UI-SHELL-06 marked done but not implemented |
| Session restore | Browser tabs; ?tab= worked, the stock window was lost | Windows, pages, stock window and zoom come back | IMPROVED | logout or Dock-quit skips the final save (a save runs every 60 s) |
| Single instance | n/a | A second launch focuses the running app | IMPROVED | |
| Close window / quit | Closing the tab | ⌘W hides to the menu bar; ⌘Q quits cleanly; the stack keeps running | DIFFERENT-INTENDED | |
| Relaunch after the app crashes | n/a | The login-job copy is relaunched after 20 s | IMPROVED | a copy opened from Dock or Finder is not (installed build) |
| One window's WebKit page process dies | Browser loses only that tab | **The whole app panics and quits; every window is gone** | REGRESSION · major | section 6, R1 |
| New UI build available | No notice; stale code could fail later | Strip shows NEW BUILD · RELOAD at once | IMPROVED | the browser gets an amber pill |
| What the page may ask the app to do | n/a | Only the 9 shell commands; bad arguments refused | IMPROVED | |
| Rollback | Rebuild the web server | build-ui --rollback; build_desktop.sh --rollback | IMPROVED | the kept app copy is the pre-wave-2 build |
| Idle CPU | WebContent 1.0–1.4 % plus the :3000 Node server | WebContent 0.7–0.9 %; real app 1.9 % total | SAME | |
| Memory after a long session | Not measured | WebContent 750–780 MB after 3 h, not growing | NEEDS-OWNER · minor | over the program's own 500 MB budget |
| Installed app vs the newest build | n/a | Installed fc2248df lacks the round-3 features in desktop/README; the newer build fails its own self-test | NEEDS-OWNER · minor | do not install the newer build yet |

### 5.3 ICICI session and login

| Feature | Web app before | Desktop app now | Status | Note |
|---|---|---|---|---|
| Session state from the backend | Expired | Identical | SAME | last good login Fri 23 Oct 08:08:17 |
| Header ICICI light and click → BRKR | Red; click opens BRKR | Same | SAME | |
| BRKR "not connected" panel | Login URL as link text | LOG IN TO ICICI ↗ button; other texts the same | IMPROVED | |
| Login URL (contains the API key) printed on BRKR and PORT | Printed | Never printed | IMPROVED | |
| LOG IN TO ICICI action | New browser tab | Opens your default browser | IMPROVED | real app did this at 16:51:03 today |
| PORT ICICI banner | URL as plain text, copy by hand | Button plus PAPER ONLY chip | IMPROVED | |
| BRIEF ICICI lines | Present | Same | SAME | |
| MCXG "broker quote unavailable" message | Present | Same | SAME | |
| Paste a rejected token or URL in BRKR | Error shown | Same | SAME | |
| Paste a good redirect URL | Saved, checked, sent to data-service; BRKR turns LIVE | Same | SAME | scratch backend, Breeze stubbed |
| .env injection guard on token and credential saves | Written raw | 400 on control characters; nothing written | IMPROVED | |
| Saving a token freezes ui-api during the Breeze check | Page froze silently | Same freeze; now a LINK DOWN banner for about 17–35 s | BROKEN-IN-BOTH · minor | every 08:00 login; positions.py:630, :664 (P2) |
| A rejected paste overwrites the saved token | Yes | Same | BROKEN-IN-BOTH · nit | positions.py:657 |
| Credentials form | Works | Same | SAME | |
| Values with #, $ or quotes saved raw (SECREL-03) | Yes | Same | BROKEN-IN-BOTH · minor | icici_admin.py:128 |
| Each save resets .env to 0644 (SECREL-13) | Yes | Same | BROKEN-IN-BOTH · nit | icici_admin.py:135 |
| ⚙ ICICI quick form (OVRV/ALFA/SYS, data-service only) | Works; result toasts hidden | Same request; toasts visible | IMPROVED | |
| Token paste from a phone or another machine | LAN :3000 accepted writes with no login | Remote clients are read-only | DIFFERENT-INTENDED | |
| BRKR helper text for other ways to get a token | Showed a developer Python path | Generic command, or /login on Telegram | DIFFERENT-INTENDED · nit | the bare "python" may not be the stack's Python |
| 08:00 Mon–Fri login job | Scheduled | Unchanged; next run Mon 26 Oct 08:00 | SAME | runs even with autopilot OFF |
| Start-up login check (no repeat ask within 30 min) | Present | Unchanged | SAME | |
| TOTP vs SMS OTP | SMS OTP when no TOTP secret | No TOTP secret in .env or Keychain, so SMS OTP every trading morning | NEEDS-OWNER | optional: store a TOTP secret |
| Telegram /login, /password, /userid, /status and the OTP reply | Works | Unchanged; tests pass | SAME | |
| Token hand-off to ui-api through the new guard | No guard | Allowed (the real code was replayed) | SAME | |
| New token reaches data-service | Works | Same requests pass the guard | SAME | |
| ui-api does not answer the hand-off | Token goes to .env only; Telegram still says "refreshed" | Same | BROKEN-IN-BOTH · minor | daily_session_refresh.py:114 (P3) |
| A test writes the live OTP-ask file | Yes | Same | BROKEN-IN-BOTH · nit | test_telegram_bot.py:14 |
| Watchdog during a login (R-OPS-01) | No hang restarts existed | New rule: only master-controller waits (≤ 10 min) | DIFFERENT-INTENDED | edited 17:22, not exercised |
| Real login with SMS OTP | Last success 23 Oct 08:08 | Not run (forbidden) | NEEDS-OWNER | Monday checklist |
| Login history in the logs | — | Logs before 25 Oct are gone | NOT-APPLICABLE | |
| ICICI row on the boot screen | None | CONNECTED / EXPIRED — send /login / unknown | DIFFERENT-INTENDED | |
| ICICI line in the menu bar (checked every 60 s) | None | Present; never logs the login URL | DIFFERENT-INTENDED | |
| "ICICI session expired" notification | None | Fires on connected → expired | NEEDS-OWNER · minor | macOS notifications are denied for the app |
| An ICICI network outage reported as "expired" | BRKR correct; BRIEF already said "expired: log in" | Tray, boot screen and a notification also say expired | BROKEN-IN-BOTH · minor | verifier corrected from regression; the app repeats it in more places (P4) |
| Extra Breeze checks caused by the app's poll | Only while BRKR/PORT/BRIEF were open | About 96–144 extra checks a day | DIFFERENT-INTENDED · nit | within Breeze limits |
| Telegram /status ICICI line | Present | Unchanged | SAME | |

### 5.4 Data freshness and data flow

| Feature | Web app before | Desktop app now | Status | Note |
|---|---|---|---|---|
| EOD bars and bhavcopy | Through 23 Oct | Same | SAME | |
| Fri 23 Oct EOD pipeline (6 steps) | Ran | Same | SAME | proven from output files |
| F&O, participant OI, deals, insider, results, FII/DII | Through 23 Oct | Same | SAME | MTF 22 Oct is normal |
| ML features and labels | Features 23 Oct, labels 15 Oct | Same | SAME | label lag is by design |
| Desk NAV and S1 shadow | 23 Oct | Same, plus the menu-bar NAV line | SAME | |
| MCX gold data | Settlement 22 Oct, COMEX 24 Oct | Same | SAME | |
| News-scanner track record | Frozen since 14 Oct | Same | BROKEN-IN-BOTH · minor | the job crashes every evening; news_scan_performance.py:95 (P6) |
| 02:15 backup | DuckDB only | DuckDB plus the settings store | IMPROVED | first settings backup Mon 02:15 |
| Re-running a 02:15 backup missed during an outage | Not re-run | Same; no 25 Oct backup | BROKEN-IN-BOTH · minor | master_controller.py:1280 (P7) |
| SYS job history after a controller restart | All "—" | Same | BROKEN-IN-BOTH · minor | master_controller.py:2205 |
| Broker feed on SYS | DISCONNECTED, Yahoo fallback | Same | NEEDS-OWNER | turns on after Monday's login |
| As-of dates: BRF and the brief | 23 Oct data, 25 Oct date line | Identical | SAME | |
| As-of dates: CHRT, DERV, OMON, OSTR | EOD 23 Oct | Identical | SAME | |
| As-of dates: PRE, MOV, WEI, ECO, MEMB, SEAG | 23 Oct | Identical | SAME | WEI adds a last-update time |
| As-of dates: DEAL, INSD, IPO, MRGN, HDS, CF | 23 Oct (MRGN 22 Oct) | Identical | SAME | |
| As-of dates: WRAP, MKT, EVTS, ALRT, RSCH | 23 Oct | Identical | SAME | |
| As-of dates: DESK, RSK, COMP | 23 Oct; RSK book 14 Oct, labelled stale | Identical | SAME | |
| As-of dates: OVRV, WHSE, DEXP, PIPE, LWSC, SYS | 23 Oct; labels 15 Oct | Identical once loaded | SAME | |
| Pages with no date claims (WTCH, FUND, EQS, BTST, GBOX, MLEN) | — | — | SAME | |
| Gold desk "updated" time with the new 30 s cache | Compute time | Leg times stay true | DIFFERENT-INTENDED | |
| Header NIFTY chip when the market is closed | "● NSE" on a Sunday | "CLOSE 23-OCT" | IMPROVED | |
| Header NIFTY chip in market hours with an old quote | "● NSE" whatever its age | Same; the menu bar says stale | BROKEN-IN-BOTH · minor | feedState.ts:37 |
| Data date in the header | "DATA 2026-10-23" in the header | Footer and title strip; the browser hides it at ≤ 1760 px | DIFFERENT-INTENDED | |
| Footer DATA date and OVRV in a window left open | Never refreshed | Same; app windows stay open for days | BROKEN-IN-BOTH · minor | page.tsx:298 |
| Macro tape while Yahoo is slow | All dashes, even NSE items | Same | BROKEN-IN-BOTH · minor | MarketCommandHeader.tsx:181 |
| HTTP caching of /api | None | None | SAME | |
| Compressed API responses | Plain JSON | gzip; byte-identical once decoded | IMPROVED | |
| DEXP features cache | Whole file read per click | Cached; refreshes when the file changes | IMPROVED | |
| Economic-calendar requests | BRF only | One shared request per IST day | IMPROVED | |
| 1,500-stock list and enrichment status | Loaded on every page | Only on EQS / OVRV | IMPROVED | |
| PIPE background polling | On every page | Only after PIPE is opened | IMPROVED | |
| Requests per page overall | 971 for 42 page loads | 768 (app) / 809 (browser); page requests identical | DIFFERENT-INTENDED | |
| Polling while a window is hidden | Continues | Same | SAME | |
| Sleep and wake | Dates roll forward | Same | SAME | |
| IST midnight roll | Labels roll | Same | SAME | |
| Panels that load once (EQS list, BRF) | Until reload | Same | BROKEN-IN-BOTH · nit | page.tsx:325 |
| Watchlist re-registered for live quotes after a Redis restart | Not re-sent | Same | BROKEN-IN-BOTH · minor | AppContext.tsx:243 |
| Muhurat session, Sun 8 Nov | Header said "● NSE" / "WS LIVE" (right only by accident) | "CLOSE 08-NOV", "SOCKET OK · NO TICKS"; strip and tray say closed while prices move | REGRESSION · minor | the header WEEKEND label itself is pre-existing (R10) |
| LIVE_TICKS switch and Breeze tick store | OFF | OFF | NEEDS-OWNER | your decision |
| Live-quote WebSocket plumbing | One Redis subscription per socket | One shared subscription; handshake 17 ms | IMPROVED | |
| Monday 09:15 live flow | Same backend path | Same | NEEDS-OWNER | confirm Monday |

### 5.5 Settings

| Feature | Web app before | Desktop app now | Status | Note |
|---|---|---|---|---|
| Settings store and migration state | Settings lived in each browser | Server store; nothing imported from :3000 yet | NEEDS-OWNER · minor | the app's reminder is already dismissed |
| Migration from the old web app (tested on scratch) | n/a | Watchlist and pins arrive; open windows pick them up on focus | IMPROVED | |
| Migration reminder | n/a | Shown until imported or dismissed | DIFFERENT-INTENDED | |
| Reminder bar covers page controls (CT-15) | n/a | Fixed bar over e.g. ALFA Run Scan, DEXP pager, BTST Run, sortable headers on 15 pages | REGRESSION · minor | gone in the app (dismissed); still shows in browsers (R6) |
| Watchlist edited in two windows | The second window's edit wiped the first | Both edits kept | IMPROVED | |
| Pins seen by other windows | Live | Same | SAME | |
| Watchlist reorder | No such control | None | NOT-APPLICABLE | |

### 5.6 GO bar and stock window

| Feature | Web app before | Desktop app now | Status | Note |
|---|---|---|---|---|
| Type a letter to open GO | Absent | Opens GO with that letter | IMPROVED | |
| All 42 page codes + Enter | 42/42 | 42/42 | SAME | |
| Search by name ("markets", "gold") | "markets" → WEI, "gold" → BRF | Same | BROKEN-IN-BOTH · minor | alias table fixed in working tree |
| Mnemonics GP, TOP, MOST, BACK (CT-09) | Wrong targets | Same | BROKEN-IN-BOTH · minor | |
| TICKER (M&M, BAJAJ-AUTO, unknown, company name) | Opens the stock window | Same; the URL gains &sym= | SAME | |
| TICKER DES / FA / ERN / HP / SEAG / GP | Right tab | Same | SAME | |
| TICKER TV / YF / Y | New tab | Default browser | DIFFERENT-INTENDED | |
| TICKER W / WL | Toggles the watchlist | Same | SAME | |
| TICKER DEAL / DEAL TICKER | DEAL filtered | Same | SAME | |
| COMP A B C, NEWS, HELP | Works | Same | SAME | |
| Command recall (↑ ↓, chips) | Works | Same | SAME | |
| A stock with no company name in the symbol list | Whole terminal crashed on the first GO query | Terminal survives; GO stays dead in that window until reload | BROKEN-IN-BOTH · minor | CommandBar.tsx:182; none in live data today |
| Open the stock window (GO, ticker links) | Works | Same | SAME | |
| Stock window tabs (Profile, Data, Chart, HP, SEAG) | Works | Same | SAME | |
| Chart periods (Today, 5D, 1M, 1Y, 5Y) | Works | Same | SAME | |
| ☆ PIN and + WATCHLIST | Works | Same | SAME | |
| 🔔 ALERT form re-opened shows empty boxes | Yes | Same | BROKEN-IN-BOTH · nit | ChartActions.tsx:46-48 |
| ↗ TRADINGVIEW / ↗ YAHOO | New tab | Default browser | DIFFERENT-INTENDED | |
| ⧉ NEW WINDOW button | Absent | Present | IMPROVED | |
| Esc closes the stock window | Did nothing | Closes, on every page | IMPROVED | |
| ✕ close | Works | Same; also clears &sym= | SAME | |
| Deep link ?sym= and reload | Ignored; reload lost the window | Opens it and survives reload | IMPROVED | |

### 5.7 Alerts, notifications, downloads and links

| Feature | Web app before | Desktop app now | Status | Note |
|---|---|---|---|---|
| Alert-hit toasts | Hidden under the header | Visible | IMPROVED | |
| Several hits at once | One notification each | One combined notification | IMPROVED | |
| Notifications actually shown on the Mac | Browser notifications, if allowed | macOS reports DENIED for the app: no banners at all | NEEDS-OWNER · major | Telegram and Script Editor alerts still work |
| ENABLE DESKTOP NOTIFICATIONS chip | Asks the browser | Opens System Settings › Notifications | DIFFERENT-INTENDED | |
| Old hits not replayed on a first visit | 0 replays | 0 | SAME | |
| ±% MOVE alert wording | "fell below ₹5" | Same | BROKEN-IN-BOTH · minor | alertText.ts:26 |
| Alert chip ✕ and the ALRT FIRED list | Works | Same | SAME | |
| Server alerts router | — | Unchanged | SAME | |
| Header 🔔 inbox on a new address | Old items counted as unread | Old items read; new ones counted | IMPROVED | |
| Stack alerts as banners with no window open (K5) | None | Not in the installed app | NEEDS-OWNER · minor | latent risk in feed.rs:455 |
| Table ⤓ CSV content | Browser download | Same file; 2-dp prices, ASCII minus; app bytes identical to the browser now | IMPROVED | |
| Default CSV file name | suryadhana-terminal-DATE.csv | <page code>-DATE.csv | DIFFERENT-INTENDED · nit | not in the list of intended changes |
| Research data files (RSCH) | Browser download | Same bytes | SAME | |
| Downloads in the app | Browser download | Saved to ~/Downloads, quarantined, extension allowlist, rate caps | IMPROVED | |
| Feedback after an export in the app | Browser download bubble | Nothing visible (notifications denied) | REGRESSION · minor | ⌥⌘L Show Latest Download works (R8) |
| External links (filings, ECO PDFs, headlines, News Terminal) | New tab | Default browser, once | DIFFERENT-INTENDED | |
| TradingView embed (News Terminal) | Loads | Loads, sandboxed | SAME | |

### 5.8 Connection and errors

| Feature | Web app before | Desktop app now | Status | Note |
|---|---|---|---|---|
| ui-api outage banner | None; the page went stale | LINK DOWN banner (app after 4 s, browser after about 10 s) | IMPROVED | |
| After the link returns | Manual reload | Failed panels reload by themselves | IMPROVED | |
| One failed summary or stock-list call | Whole terminal "BACKEND UNREACHABLE" | Only that panel (OVRV, EQS) shows an error | IMPROVED | WRAP and others keep working |
| Bad data from an API | Whole terminal "Client-side Exception" | Per-page error panel with RETRY | IMPROVED | |
| Stock window or dialog open during LINK DOWN | Stays in place | Pushed under the header, dimmed, ✕ off-screen | REGRESSION · minor | also in the browser; also ALFA/PIPE dialogs (R7) |

### 5.9 Pages: briefing and markets

| Feature | Web app before | Desktop app now | Status | Note |
|---|---|---|---|---|
| BRF page load (all panels) | Index levels 0–1 dp | Same data, 2 dp | IMPROVED | |
| BRF ↻ REFRESH ALL | 24 sources | Same | SAME | |
| BRF What's new strip and setup items | Works | Same | SAME | |
| BRF page chips and links | Navigate | Same | SAME | |
| BRF Your book and Gold panels | Works | Same | SAME | broker data stubbed equally |
| Intraday chart price tag 1 dp vs 2-dp readout (CT-05, BRF and MOV) | Both 1 dp | Tag 1 dp, readout 2 dp | BROKEN-IN-BOTH · minor | IndexIntraday.tsx:75; fix in working tree |
| WTCH monitor table, filters, sort, X-ray | Works | Same | SAME | |
| WTCH add/remove ticker | Works | Same | SAME | |
| WTCH alert SAVE fails silently | Yes | Same | BROKEN-IN-BOTH · minor | alerts.ts:86 |
| WTCH ↻ refresh and COMPARE HELD | Works | Same | SAME | |
| WTCH CSV | Generic file name | wtch-DATE.csv | DIFFERENT-INTENDED | |
| MKT regime, breadth and tiles | NIFTY 500 tile 0 dp | Same | BROKEN-IN-BOTH · nit | MarketMonitor.tsx:188 |
| MKT breadth-history chart | Odd axis labels | Round ticks | DIFFERENT-INTENDED | |
| MKT industry table, members, rotation, valuation, CSV | Works | Same; CSV identical | SAME | |
| Market map (MKT, MOV) | Scaled; truncated labels | Sharper; fuller labels | DIFFERENT-INTENDED | |
| Market-map industry header near zero | "-0.0%" in red | "0.0%" in red | REGRESSION · nit | MarketMap.tsx:182 (R12) |
| MOV chips, sectors, who-moved, intraday, tables | Works | Same, 2 dp | IMPROVED | |
| MOV says "today" on a closed day (CT-13) | Yes | Same | BROKEN-IN-BOTH · nit | fix in working tree |
| MOV movers table never refreshes after a "closed" answer | Stuck all session | Same | BROKEN-IN-BOTH · minor | LiveMovers.tsx:88; verifier: minor (P5) |
| PRE auction book, chips, find, sort, keys | Works | Same, 2 dp | SAME | |
| WEI world markets | Works | Same | SAME | |
| ECO cards, calendar, chips, sort | Works | Same | SAME | |
| ECO CSV and source PDFs | New tab | CSV identical; PDFs open in the default browser | DIFFERENT-INTENDED | |
| WRAP archive and navigation | Works | Same | SAME | |
| EVTS calendar, chips, tables, CSV | Works | Same; CSV identical | SAME | |
| CF filings, chips, search | Works | Same | SAME | |
| IPO issues, scorecard, chips | Works | Same | SAME | |
| MRGN MTF chart | Scaled | Drawn in screen pixels | DIFFERENT-INTENDED | |
| MRGN lookback, tables, CSV | Works | Same | SAME | |
| HDS shareholding views | Works | Same | SAME | |
| INSD chips, sorts, CSV | Works | Same | SAME | |
| INSD "Who" categories change order between refreshes | Yes | Same | BROKEN-IN-BOTH · nit | duckdb_store.py:871 |
| DEAL chips, search, shorts, sorts | Works | Same | SAME | |
| DEAL CSV | Generic name | deal-DATE.csv, 2 dp | DIFFERENT-INTENDED | |
| MEMB chips, sorts, row Enter | Works | Same, plus a ?sym= link | IMPROVED | |
| MEMB CSV | 0–1 dp | 2 dp | DIFFERENT-INTENDED | |
| SEAG index chips, ticker, tooltips | Works | Same | SAME | |
| Columns cut off at the 1100 px minimum window (WTCH, ECO, MEMB, DEAL) | Yes | Same | BROKEN-IN-BOTH · nit | |

### 5.10 Pages: equities and research

| Feature | Web app before | Desktop app now | Status | Note |
|---|---|---|---|---|
| EQS stock list | Preloaded on every page | Loads on the first EQS visit | DIFFERENT-INTENDED | |
| EQS sorts, filters, Minervini toggles | Works | Same | SAME | |
| EQS watch star and Refresh N | Works | Same | SAME | |
| EQS live price flash stays on (RUP-04) | Yes | Same | BROKEN-IN-BOTH · minor | StockTable.tsx:176; fix in working tree |
| EQS columns hidden at 1600 px (CT-08) | WATCH hidden | HEALTH and WATCH hidden | BROKEN-IN-BOTH · minor | StockTable.tsx:474 |
| FUND presets, filters, sorts | Works | Same counts | SAME | |
| FUND pick rows → COMPARE; saved filters | Works | Same | SAME | |
| FUND CSV | Works | Byte-identical | SAME | |
| COMP starting set | Local default | Your synced set (TCS, INFY) | DIFFERENT-INTENDED | |
| COMP periods, add, remove, tables, max 8 | Works | Same | SAME | |
| COMP chart hover | Scaled chart | Wider plot; correct values | DIFFERENT-INTENDED | |
| COMP: remove every symbol, then add one | Shows only the new one | The last removed symbol comes back and syncs | REGRESSION · minor | Compare.tsx:92/98 (R5) |
| COMP CSV and GO "COMP A B C" | Works | Same content, new file name | DIFFERENT-INTENDED | |
| CHRT timeframes, indicators, lookback | Works | Same | SAME | |
| CHRT symbol search and crosshair | Works | Same | SAME | |
| RSCH list, verdict chips, search, report | Works | Same | SAME | |
| RSCH "What's new" has no entry for the app (CT-12) | Same document | Same | BROKEN-IN-BOTH · minor | docs/IMPROVEMENT_LOG.md |
| OVRV before its data arrives | Hidden until loaded | Invented zeros and an active ENRICH NOW | REGRESSION · minor | page.tsx:903-976 (R4) |
| OVRV data-source widget and Desk card | Works | Same | SAME | |
| OVRV Quick refresh and Re-enrich | Results hidden | Same requests; toasts visible | IMPROVED | |
| WHSE KPIs, coverage, tables, Sync | Works | Same | SAME | |
| DEXP pipeline controls | Works | Same | SAME | |
| DEXP grid, paging, filter | Works | Same | SAME | paging can be covered by the reminder bar (R6) |
| PIPE step tabs | Duplicate ③ | ①–⑤ | IMPROVED | |
| PIPE panels and health sidebar | Works | Same | SAME | |
| PIPE Run / Train / PPO dialogs | Works | Same | SAME | |
| PIPE Feature Inspector and Model Studio | Works | Same | SAME | |
| LWSC cycle-scan table and chart | Works | Same | SAME | |
| LWSC Run scan and vol screener | Works | Same | SAME | |
| ALFA registry, scan, results | Works | Same | SAME | |
| ALFA socket chip on a closed market | "● WS LIVE" | "SOCKET OK · NO TICKS" | IMPROVED | |
| ALFA scan-mode buttons and knobs use the previous value | Yes | Same | BROKEN-IN-BOTH · minor | AlphaDiscoveryDesk.tsx:459, :265-268 |
| ALFA Run Scan, Refresh Matched, Monitor All, row click | Works | Same | SAME | |
| ALFA system widget glyph and font | Emoji; Google font | Glyph; bundled font | IMPROVED | |
| GBOX default date range | Fixed Sep 2025 → May 2026 | Trailing 9 months | DIFFERENT-INTENDED · nit | |
| GBOX RRG, correlation, volume profile | Works | Same | SAME | |
| MLEN default date range | Fixed | Ends today | DIFFERENT-INTENDED · nit | |
| MLEN run and stream | Works | Same | SAME | |
| BTST run and results | Works | Same | SAME | |
| BTST CSV and Excel export | Works | Byte-identical | SAME · nit | UTC time in the file name (pre-existing) |
| BTST blotter sort, row → stock window, hover | Works | Same | SAME | |
| BTST walk-forward and factor studio | Works | Same | SAME | |

### 5.11 Pages: derivatives and gold

| Feature | Web app before | Desktop app now | Status | Note |
|---|---|---|---|---|
| OMON chain, stats, expiry and index chips | Works | Same | SAME | |
| OMON option pricer | Works | Same | SAME | |
| OMON smile and IV/PCR charts | Odd ticks | Round ticks, strike labels | IMPROVED | |
| OMON CALL WALL / PUT WALL labels on the OI chart | No labels | **Labels the wrong strike** (NIFTY 23,500 vs stat 24,000; also FINNIFTY, MIDCPNIFTY, NIFTYNXT50, TCS) | REGRESSION · major | app and browser now (R3) |
| OMON "F&O stock…" box + Enter | WebKit: needs two Enters | Same (WebKit is the app's engine) | BROKEN-IN-BOTH · minor | verifier corrected from regression |
| OMON Enter in that box flips to LIVE (Chromium browsers) | Yes | Same | BROKEN-IN-BOTH · minor | terminal/index.tsx:102-104 |
| GO "RELIANCE OMON" shows the NIFTY chain (CT-01) | 7–8 of 10 tries | Same (67–85 %); retyping does not fix it | BROKEN-IN-BOTH · major | P1; fix in working tree |
| OMON LIVE/EOD toggle; GO with OMON already open | Works | Same | SAME | |
| OSTR templates, legs, analyze requests | Works | Byte-identical requests | SAME | |
| OSTR results and payoff chart | Mixed ₹ units | Round axis in one ₹ unit | IMPROVED | |
| OSTR failure state | Error box | Same | SAME | |
| DERV term structure, chips, rollover, PCR, max pain, VIX | Works | Same | SAME | |
| DERV time-series axes | 3 labels incl. negatives | Often 2 labels; no negative label on today's negative basis | REGRESSION · nit | DerivativesDesk.tsx:87 (R11) |
| DERV OI column mixes "cr" and "L" (CT-11) | Yes | Same | BROKEN-IN-BOTH · minor | DerivativesDesk.tsx:48 |
| DERV CSV | Generic name | derv-DATE.csv, identical bytes | DIFFERENT-INTENDED | |
| CMDT gold pre-open desk | Works | Same values, Indian grouping | SAME | |
| CMDT your inputs → recompute | Works | Same | SAME | |
| CMDT refresh every 60 s vs 30 s Yahoo cache (C-PERF-02) | Mostly cold refreshes | Same | BROKEN-IN-BOTH · minor | gold_preopen.py YAHOO_TTL_S |
| CMDT manual-check boxes and links | Works | Same; links open the default browser | SAME | |
| CMDT accuracy log save | Works | Same | SAME | scratch copy of the log |
| CMDT futures board and history chart | Works | Same | SAME | |
| MCXG session clock and holidays | Works | Same | SAME | |
| MCXG quote panel and fallbacks | Works | Same | SAME | |
| MCXG paper gold ticket | Works | Same | SAME | |

### 5.12 Pages: portfolio and risk

| Feature | Web app before | Desktop app now | Status | Note |
|---|---|---|---|---|
| DESK "Re-enable after review" (clears the −20% emergency stop) | Browser asks "Clear the emergency stop?" | **No question asked; the stop is cleared at once** | REGRESSION · major | app only; the browser still asks (R2) |
| DESK brief, crash filter and notes | Raw numbers | 2 dp, plain-language cost note | IMPROVED | |
| DESK plan, positions and watchlist tables | LAST 1 dp | 2 dp, same rows | IMPROVED | |
| DESK ↻ Refresh and ▶ Preview | Works | Same | SAME | |
| DESK book vs NIFTY chart | Scaled | Screen pixels | DIFFERENT-INTENDED | |
| DESK watchlist NEXT EVENT hidden at 1600 px (CT-03) | 9 px visible | 1 px visible | BROKEN-IN-BOTH · minor | verifier: minor; fix in working tree |
| PORT header chips | "PAPER" | "PAPER ONLY", "LEGACY · DORMANT" | IMPROVED | |
| PORT engine polling | Every 8 s | Same | SAME | |
| PORT token input + Connect | Present | Same | SAME | |
| PORT active-model select | Works | Same | SAME | |
| PORT PAPER/LIVE toggle | LIVE ⚡ selectable with a real-orders confirm | LIVE disabled | IMPROVED | |
| PORT when the first status call fails (RUP-02) | LIVE selectable | Same | BROKEN-IN-BOTH · minor | ui-api still refuses LIVE (403); policy.ts:50 |
| PORT LIQUIDATE & HALT label | Generic | "· PAPER" with a paper-specific confirm | IMPROVED | not pressed |
| PORT KPIs, loss meter, positions, orders | Works | Same | SAME | |
| PORT "₹10.0K" units and "ACTIVE" next to LEGACY (CT-06/11) | Yes | Same | BROKEN-IN-BOTH · nit | LivePortfolio.tsx:87 |
| BRKR header, refresh, Recheck, 15 s polling | Works | Same | SAME | |
| BRKR credential chips, token field, credentials form state | Works | Same | SAME | |
| BRKR backend sync and rules panels | Works | Same | SAME | |
| BRKR connected view (holdings, allocation, risk) | Works | Same | SAME | synthetic book |
| BRKR holdings sort and keyboard | Works | Same | SAME | |
| BRKR CSV | U+2212 minus (text in spreadsheets) | ASCII minus; brkr-DATE.csv | IMPROVED | |
| RSK header, KPIs, VaR, drawdown ladder | Works | Same | SAME | |
| RSK what-if basket, Desk watchlist, Refresh | Works | Same | SAME | |
| RSK holdings table, keyboard, CSV | Works | Byte-identical | SAME | |
| RSK VaR histogram | Scaled; labels could overlap | Screen pixels, staggered labels | DIFFERENT-INTENDED | |
| SYS status, scheduler, logs stream | Works | Same | SAME | autopilot toggle not pressed |

### 5.13 Backend, scheduler, Telegram and operations

| Feature | Web app before | Desktop app now | Status | Note |
|---|---|---|---|---|
| Controller → data-service data jobs (08:30, 18:30, 20:30, 20:45, Sat, catch-up) | No guard | Allowed by the guard | SAME | exact client calls replayed |
| Controller → data-service writes (FII/DII, prefetch, internals, provider) | No guard | Allowed | SAME | 367 live 200s from the same request shape |
| Controller → ui-api writes (Desk 19:30, gold 08:45/09:10, alerts every minute) | No guard | Allowed | SAME | first live guarded runs Monday |
| Controller → ui-api reads (notes, alerts) | Works | Allowed | SAME | |
| ui-api → data-service | Works | Allowed | SAME | |
| ui-api → controller telemetry | Works | Allowed | SAME | |
| Watchdog and start-local health probes | Works | Allowed | SAME | |
| App health poller | n/a | GET only; allowed | IMPROVED | |
| Writes from the terminal page (app window or browser) | No guard | Allowed for 127.0.0.1:8010 and localhost:8010 | SAME | |
| Old :3000 web app path (for the settings migration) | Works | Allowed; foreign pages refused | SAME | |
| Old Next streaming routes | Works | Allowed | SAME | |
| Ad-hoc scripts (urllib, curl, Playwright) | Works | Allowed | SAME | |
| daily_wrap and the weekly journal | Works | Allowed | SAME | |
| Cross-site access (CORS) | Any site could read the controller | Removed; cross-site writes 403 | IMPROVED | no legitimate user of it found |
| Guard rejections in today's logs | — | All 37 were test probes; none from a real caller | SAME | |
| Telegram commands (/help … /alert, /otp) | Works | All pass the guard | SAME | real dispatcher replayed |
| Telegram controller actions (/status, /login, /password, /userid) | Works | Allowed | SAME | |
| Telegram long-polling | Running | Running after today's restarts | SAME | no message sent |
| Scheduler jobs after today's restarts | — | Ran; skipped as designed (autopilot OFF) | SAME | |
| Scheduler header lists 13 of 28 jobs | Yes | Same | BROKEN-IN-BOTH · nit | master_controller.py:5 |
| Legacy autopilot jobs | OFF | OFF | NOT-APPLICABLE | |
| PAPER-ONLY on the execution engine | Saved mode was LIVE (halted) | PAPER enforced; LIVE refused | IMPROVED | legacy :8006 /square-off is outside this guard (dormant) |
| Terminal from a phone or iPad on home Wi-Fi | :3000 open on every interface, no login | Not possible (local only); Tailscale is the documented route | DIFFERENT-INTENDED · minor | Tailscale not installed |
| Watchdog restarts a hung service | Never | Restarts after 2 failed checks; ui-api has no freeze-window exemption | DIFFERENT-INTENDED · minor | decide on the 19:30 Desk window |
| Service logs | Wiped at each restart | Appended and rotated | IMPROVED | |
| ui-api event-loop stall watchdog | None | Running; logged a 49 s stall | IMPROVED | |
| ui-api froze 49 s at 15:39:40 | Unknown | Cause not found in the logs | NEEDS-OWNER · minor | right after the app relaunched |
| gzip for internal clients | Plain | Decoded transparently | SAME | |
| ui-api /docs | On | Off (UI_API_DOCS=1 turns it on) | DIFFERENT-INTENDED | |
| Docker legacy stack | Dormant | Dormant | NOT-APPLICABLE | |

---

## 6. Confirmed regressions and pre-existing bugs

### 6.1 Regressions (worse than the web app and not intended), by severity

| # | What | Severity | Where | Fix | Fix status |
|---|---|---|---|---|---|
| R1 | One window's WebKit page process dying (memory pressure, WebKit crash) **crashes the whole app** (exit 101). The shell asks for the dead page's URL, and wry 0.57.1 unwraps a nil URL. Reproduced 3/3 in the newer build's self-test. The installed build reaches the same call within 60 s (session save), shown by reading its code. A browser loses only the tab. | major | `desktop/src-tauri/src/windows.rs:1329` (record_crash), `:1115` (save_session; installed source `:1020`); root `wry-0.57.1/src/wkwebview/mod.rs:1442` | Make a nil URL an error, not a panic: patch wry through `[patch.crates-io]` (`let Some(url) = webview.URL() else { return Err(..) }`), or add a `webview_url()` helper returning `Option` and ban `Webview::url` with clippy. Every caller already handles errors. Also make `scripts/build_desktop.sh` self-test **before** installing (today it installs first, lines 325-338), and extend the crash self-test. | Not fixed |
| R2 | DESK **"Re-enable after review" has no confirmation in the app.** The dialog plugin replaces `window.confirm` with an async function; the page reads the Promise as "yes" and POSTs `/api/desk/reenable` at once. That clears the HARD −20% stop and resets the drawdown peak. The browser still asks. | major | `ui/components/DecisionDesk.tsx:158`; `desktop/src-tauri/src/lib.rs:1274` | Replace `window.confirm` with an in-page two-step confirm (Cancel focused, Esc cancels). Add a check that fails on any `window.confirm/alert/prompt` in `ui/`. Add a self-test that `typeof window.confirm('x') === 'boolean'`, or a shell init script that makes confirm fail closed. Do **not** grant the dialog permission to the remote page. | Not fixed |
| R3 | OMON's OI chart labels the in-window maximum as CALL/PUT WALL. When the real wall is outside the plotted window (NIFTY, FINNIFTY, MIDCPNIFTY, NIFTYNXT50, TCS today), the chart contradicts the OI WALLS stat on the same screen. | major | `ui/components/OptionChain.tsx:69-70` (release) | Use `data.resistance[0]` / `data.support[0]`; draw an edge marker ("CALL WALL 24,000 →") when it is off-chart. Add a browser check that every labelled wall equals the stat. | In working tree (`omonModel.wallMarks`), unreleased |
| R4 | OVRV renders "Universe 0 / 0% CURRENT / 0 of 0 enriched" and an enabled ▶ ENRICH NOW until the summary loads, and keeps them under the error box if it fails. Bad during the slow 18:30–21:15 window. | minor | `ui/app/page.tsx:903-976` (release) | Show "—" and LOADING with the enrich button disabled. Also treat ui-api's empty-summary payload as "unavailable", and show "— STOCKS" in the footer. | In working tree (except the empty-summary case), unreleased |
| R5 | COMP: remove every symbol, then add one; the last removed symbol comes back and syncs to the server and other windows. | minor | `ui/components/Compare.tsx:92`, `:98` | `compareBase(shown, raw, known)`: use storage only when another window changed it. Do not save an empty set (it would reset other windows to defaults). | In working tree, unreleased |
| R6 | The settings reminder bar is fixed over page content (z above dialogs) and blocks clicks: ALFA Run Scan, the DEXP pager (100 % covered at 1280×800), BTST ▶ Run, and sortable headers on 15 pages. | minor | `ui/app/globals.css:363` (`.sd-note` fixed), `ui/components/desktop/ShellNotices.tsx:97-105` | Render it in the page flow (`position: relative`, no z-index). | In working tree, unreleased. Already dismissed in your app; still shows in browsers |
| R7 | A stock window or dialog open during LINK DOWN jumps to top −527 px, dimmed to 55 %, with ✕ off-screen (the dimming filter re-anchors fixed elements). Also in the browser, and in ALFA/PIPE dialogs. | minor | `ui/app/globals.css:405` | Dim with a `.sd-page::after` overlay instead of filter/opacity on the page. Run ui_audit before release. | In working tree, unreleased |
| R8 | An export in the app gives no visible confirmation or error: the only feedback is a native notification, and notifications are denied. A refused save (rate cap, privacy setting) is silent. | minor | `ui/lib/platform/index.ts:135` (event has no listener) | Add a small `DownloadToasts` component **inside** `ToastProvider` (next to `<ErrorCatcher/>` in `app/page.tsx`), not in PlatformShell (which is outside the provider and would crash). Success: "Saved to … · ⌥⌘L"; failure: the error text. | Not fixed |
| R9 | No Find (⌘F) and no Print (⌘P) in the app. | minor | `desktop/src-tauri/src/menu.rs:188` | Find: a desktop-only find bar using `window.find()`, handled in the page (no Rust or contract change). Print: File ▸ Print… calling `WebviewWindow::print()` from Rust; guard against a hidden window. | Not fixed |
| R10 | Muhurat session (Sun 8 Nov): header chip "CLOSE 08-NOV", socket chips "NO TICKS", strip "CLOSED WEEKEND" and tray "· closed" while prices move. | minor | `ui/lib/feedState.ts`, `ui/components/desktop/session.ts:88`, `desktop/src-tauri/src/health.rs:305-320` | Let fresh data beat the calendar everywhere: ship the working-tree UI override; fix `classify_quote` in health.rs; fill in the Muhurat times when NSE publishes them. | UI part in working tree; tray not fixed. Needed before 8 Nov |
| R11 | DERV time-series axes often show only 2 labels; no negative label on today's negative basis. | nit | `ui/components/DerivativesDesk.tsx:87` | Compute ticks over the padded range, with the count based on chart height (at least 3). Put "%" on the basis axis only. | Partial fix (6/5 ticks) in working tree |
| R12 | Market-map industry header shows "0.0%" in red for −0.03 %. | nit | `ui/components/MarketMap.tsx:182` | Colour by the rounded value. | In working tree, unreleased |
| R13 | Browser help and footer on a Mac teach Alt+←/→ for Back/Forward (does nothing there). | nit | `ui/lib/shortcuts.ts:64,76` (release) | Show ⌘[ ⌘] on a Mac. | In working tree, unreleased |

### 6.2 Pre-existing bugs (also in the old web app), most serious first

| # | What | Severity | Where | Fix |
|---|---|---|---|---|
| P1 | GO "RELIANCE OMON" (and the profile's OPTION CHAIN ›, and Back to OMON) shows **NIFTY's** chain under a RELIANCE selection 67–85 % of the time, with no loading state. Retyping does not fix it. | major | `ui/components/OptionChain.tsx:161, 175, 182` | Ship the working-tree request-sequence guard (`requestSeq.ts`, start on the hand-off symbol). Keep the sequence in `useRef`, not `useMemo`. Gate it with a delayed-reply browser test. |
| P2 | Saving an ICICI token (08:00 job, Telegram, BRKR paste, Save credentials) runs the 10–40 s Breeze check on ui-api's event loop, so every window shows LINK DOWN. | minor | `services/ui-api/routers/positions.py:630`, `:664` | `status = await asyncio.to_thread(_runtime_status)`, as connection-status already does. Add both routes to `test_event_loop_purity.py`. |
| P3 | If ui-api does not answer the token hand-off, the token goes to .env only, Telegram still says "refreshed", and the session stays expired until restarts. | minor | `scripts/daily_session_refresh.py:114`; `master_controller.py:1615` | Retry the ui-api POST for about 2 min; report "via .env" as a warning; send the .env token in the reconnect body instead of `{}`. |
| P4 | An ICICI network outage is reported as "session expired". ui-api drops the error kind; the app's tray, boot screen and notification say "expired: send /login". | minor | `positions.py:573-587`; `desktop/src-tauri/src/health.rs:353` | Add `error_kind` to the response (additive), map "network" to unknown in health.rs, and fix the BRIEF line too. Separately: `token_works()` treats network errors as expired. |
| P5 | MOV's movers table never refreshes once the server has said "closed" (opened before 09:15, or left open). | minor | `ui/components/LiveMovers.tsx:88` | Also poll when the client session clock says OPEN (`nseSession(Date.now()).state === 'OPEN'`). |
| P6 | News-scanner track record frozen since 14 Oct; the 19:45 job crashes every evening and only logs it. | minor | `scripts/news_scan_performance.py:95` | Never return the DuckDB connection; load the panel from it. Alert on a non-zero exit; show "prices through <date>" on BRF. |
| P7 | A 02:15 backup missed during an outage is not re-run; there is no 25 Oct backup. | minor | `scripts/master_controller.py:1280` | Add a one-off backup to the start-up catch-up when it was missed and the time is outside the freeze windows. |
| P8 | PORT offers LIVE and the real-orders confirm if the first status call fails (RUP-02). ui-api still refuses. | minor | `ui/components/portfolio/policy.ts:50` | Fail closed on unknown status; use `allSettled` (in working tree). |
| P9 | Footer DATA date and OVRV never refresh in a long-open window; the header NIFTY chip says "● NSE" for a stale quote in market hours; the macro tape blanks while Yahoo is slow. | minor | `ui/app/page.tsx:298`; `ui/lib/feedState.ts:37`; `MarketCommandHeader.tsx:181` | Refresh the summary every 10 min and on focus/reconnect; mark old quotes STALE; use `Promise.allSettled`. |
| P10 | Watchlist not re-registered for live quotes after a Redis restart. | minor | `ui/context/AppContext.tsx:243` | Re-send subscribe on reconnect and every 10 min. |
| P11 | WTCH alert SAVE fails silently; a ±% MOVE alert says "fell below ₹5"; the re-opened alert form shows empty boxes. | minor | `ui/lib/alerts.ts:86`; `ui/lib/alertText.ts:26`; `ChartActions.tsx:46-48` | Show save errors; word move alerts as "moved −6 % (≥ 5 %)"; prefill the form. |
| P12 | ALFA scan-mode buttons and knobs scan with the previous value. | minor | `AlphaDiscoveryDesk.tsx:459`, `:265-268` | Pass the new value to `doScan`. |
| P13 | .env saved raw (#, $, quotes) and reset to 0644 (SECREL-03/13). | minor | `services/ui-api/icici_admin.py:128`, `:135` | Quote/escape values and re-parse before rename; keep mode 600. |
| P14 | SYS job history lost on every controller restart. | minor | `scripts/master_controller.py:2205` | Persist last run, status and duration to a file. |
| P15 | GO stays dead in a window after a stock with no company name appears. | minor | `ui/components/CommandBar.tsx:182` | `(s.n ?? '').toUpperCase()`. |
| P16 | Smaller: DESK NEXT EVENT hidden at 1600 px (CT-03), EQS columns hidden (CT-08), EQS flash stuck (RUP-04), intraday tag precision (CT-05), DERV OI units (CT-11), OMON Enter quirks, GO "markets"/mnemonics (CT-09), CMDT cache TTL, IMPROVEMENT_LOG has no app entry (CT-12), MKT/MOV wording, INSD order, BTST UTC file names, scheduler header, rejected paste overwrites the token, test writes the live OTP file. | minor / nit | see the matrix | Several are already fixed in the working tree (CT-03, CT-05, CT-13, RUP-04, RUP-02, CT-11 PORT units, CT-09 aliases). |

### 6.3 Final-review findings: pre-existing or new?

| ID | Finding | Verdict |
|---|---|---|
| CT-01 | RELIANCE OMON shows the NIFTY chain | Pre-existing (BROKEN-IN-BOTH, major) |
| CT-02 / RUP-01 | OI wall label vs stat mismatch | **Regression** (major) |
| CT-03 | DESK watchlist columns hidden at 1600 px | Pre-existing (minor) |
| R-UI-SHELL-02 | OVRV zeros before data | **Regression** (minor) |
| RUP-02 | PORT paper-only fails open on null status | Pre-existing; the wave-2 fix does not cover this case (minor) |
| RUP-03 | COMP removed symbol returns | **Regression** (minor) |
| RUP-04 / CT-05 / CT-08 / CT-09 / CT-11 / CT-12 | various | Pre-existing |
| CT-10 / R-UI-SHELL-03 | Muhurat shown as closed | **Regression** for the chips (minor); the header WEEKEND label is pre-existing |
| CT-13 | BRF "Morning brief" title; MOV "today" | Pre-existing (nit) |
| CT-15 | Reminder bar covers controls | **Regression** (minor) |
| RUP-10 | GBOX/MLEN default dates | Intended change |
| RUP-11 | DERV axes; red "0.0%" on the map | **Regression** (both nits) |
| R-UI-SHELL-01 | Stock window during LINK DOWN | **Regression** (minor) |
| R-UI-SHELL-04 | GO crash on a null company name | Pre-existing (better now: no longer crashes the whole terminal) |
| R-UI-SHELL-06 | ⌘-click ticker → new window | Not implemented (same as before) |
| R-UI-SHELL-08 | Alt+←/→ hint on Mac | **Regression** (nit) |
| SECREL-03 / SECREL-13 | .env writes | Pre-existing |
| R-OPS-01 | Watchdog during a login | New watchdog code; reworked at 17:22, not exercised |
| C-PERF-02 | Gold desk cache TTL | Pre-existing |

---

## 7. What could not be tested, and why

- **The real ICICI login, the SMS OTP and any Breeze call.** Forbidden for agents. Every HTTP step was replayed through the real guard on scratch servers; the real round trip is Monday's checklist. Breeze check durations (10–40 s) come from code comments and earlier notes.
- **A real Telegram round trip.** Agents may not send. Polling was confirmed from the live socket's byte counters only.
- **Driving the installed app.** Launching, quitting or clicking it was not allowed. That covers tray clicks, real notification banners, ⌘V, ⌘F/⌘P keystrokes, the native title and a real page-process crash. Evidence came from its self-test (15:37), its log, its settings files (read-only copies), the binary's strings, the newer build run only in self-test mode against scratch servers, and the same UI in WebKit with a simulated shell.
- **A real Mac login or reboot.** None has happened since "Launch at Login" was enabled.
- **Market hours.** Today is Sunday, ICICI is expired and LIVE_TICKS is OFF. Not seen: live ticks, OMON live mode, MOV/PRE polling during the session, CHRT intraday bars, alerts firing live. Sockets were mocked; the clock was faked where useful.
- **Writes to live state.** Refused on both sides by design. Write paths were tested on scratch backends or in-process with temporary stores (ICICI token and credentials, alerts, gold log, OSTR, prefs migration, backup).
- **Real slowdowns, outages and sleep.** The EOD-window slowness, a real Muhurat session, a real network loss and a real Mac sleep were simulated (injected delays, route aborts, fake clocks).
- **Your real browser migration from :3000.** Simulated with an intercepted :3000 origin whose import code is byte-identical.
- **The live 02:15 backup.** Only its code path, on a scratch copy of the settings store.
- **`cargo test` / clippy.** Not run, to avoid writing into the repo's build folder while another agent was building.
- **Late edits.** `stack_watchdog.sh` (17:22), `start-local.sh` (17:28), `master_controller.py` (17:31) and `desktop/` sources (after 18:14) changed during the audit. They were read and checked for request shape, not fully exercised. The working-tree UI fixes were verified in scratch builds or unit checks only; none is released.
- **History.** Logs before 25 Oct are gone, so the 12–23 Oct 08:00 login outcomes and Friday's EOD step results were proven from output files only.
- **The cause of the 49 s ui-api freeze at 15:39:40.** Not found in the logs.
- **Which browser you used for the old web app.** Chrome history shows no :3000 visits, so probably Safari, but Safari's history is blocked by macOS privacy settings.

---

## 8. Your actions

**Before Monday 08:00**
1. Allow notifications for SuryaDhana (System Settings › Notifications, or WTCH → ENABLE DESKTOP NOTIFICATIONS). They are DENIED now, so price alerts, "ui-api down/up", "ICICI session expired" and "Saved to Downloads" banners never appear.
2. Move your settings across: open http://localhost:3000 once in your old browser, check `./start-local.sh status` says the prefs are imported, then `./start-local.sh stop frontend`. This also gives the live-quote poller your watchlist.
3. Update bookmarks from http://localhost:3000 to http://127.0.0.1:8010 (:3000 is gone after a reboot).

**Monday**
4. Follow the section 3 checklist: OTP reply at about 08:01, the checks after login, the 09:15 checks, reload windows after 18:45.
5. Try ⌘V once in the BRKR token box inside the app (paste any text, then clear it).
6. Send /status to the bot once to confirm the Telegram round trip after today's restarts.
7. At your next Mac login, check that SuryaDhana comes up by itself ("Starting the stack", then the terminal).

**Until fixed**
8. Do **not** click DESK "Re-enable after review" inside the app. If you ever need it, use a browser at http://127.0.0.1:8010, where the confirmation works.
9. Trust OMON's OI WALLS stat, not the CALL/PUT WALL label on the chart. After GO "TICKER OMON", check that the header names your ticker; if it shows NIFTY, pick another symbol and then yours again.
10. Do **not** install the build in `desktop/src-tauri/target` (its self-test crashes). Keep the installed app.
11. If MOV was open before 09:15, switch away and back.
12. Exports in the app are saved silently: use File ▸ Show Latest Download (⌥⌘L) or look in ~/Downloads.

**Decisions**
13. Approve publishing the working-tree UI fixes (`./start-local.sh build-ui`, after the five test suites and the UI gates; rollback with `--rollback`). This covers R3–R7, R10 (UI part), R11–R13, P1 and several smaller items. Do it before 8 Nov for Muhurat.
14. Approve fixes with no code yet: R1 (app crash), R2 (DESK confirm), R8 (export toast), R9 (Find/Print), the R10 tray part, and the pre-existing P2–P7 (ui-api freeze during login, token fallback, network-vs-expired, MOV, news track record, backup catch-up).
15. LIVE_TICKS: leave it OFF or enable it after the Phase-4 spike. Your call.
16. Decide whether a ui-api hang restart should wait during 18:30–21:15; the 19:30 Desk cycle runs inside ui-api.
17. Restart master-controller (outside 07:45–09:20 and 18:30–21:15) when the 17:31 /status rework should go live.

**Optional**
18. Run `scripts/db_backup.py` once outside the freeze windows to cover the missing 25 Oct backup (about 4.4 GB).
19. For logins with no OTP: store the authenticator key with `security add-generic-password -U -s suryadhana -a ICICI_TOTP_SECRET -w`, then run one attended `scripts/daily_session_refresh.py --force`.
20. Phone/iPad access: install Tailscale, run `tailscale serve --bg 8010` and add the ts.net name to GUARD_ALLOWED_HOSTS (RUNBOOK §7).
21. Add a 25 Oct entry for the desktop app to `docs/IMPROVEMENT_LOG.md` so RSCH "What's new" mentions it.

**For your information**
22. One auditor's scratch server briefly forwarded a GET of `/api/positions/connection-status` to live :8010. Its body, including the login URL with your ICICI API key, appeared once in that agent's own tool output. It was not written to any file or screenshot. The key alone cannot log in (that also needs the secret, user ID/PIN and an OTP), but you may choose to rotate it.
23. The ui-api access log shows one real `POST /api/dashboard/refresh` (the 5-year UPDATE DATA) at about 16:50 IST, before the audit began and not from an auditor. If you did not start it, check which session did.
24. Keep autopilot OFF and execution-service :8006 paused. The PAPER-ONLY guard covers ui-api's engine, not the legacy `:8006 /square-off` route used by the dormant 15:15 job.

---

## 9. Gold program (26 Oct) — intended changes (addendum)

Written Mon 26 Oct 2026 by B6-GATES (gold program phase 2, wave 1; plan: `reports/gold_program/PLAN.md` §b, §g, §h, Appendix A); revised Wed 4 Nov 2026 (wave 1b: every delta page-scoped and exact against the routes and fetchers in the tree, the gates comment-proof, the counts current). As of 4 Nov the live stack still serves the pre-gold release `20261025-223942-0ae66db` and nothing gold is deployed. Sections 1–8 describe the 25 Oct release (42 pages). The gold program adds a 43rd page, **GOLD**, and moves gold information out of four existing pages, so a parity run of the new release against the 25 Oct release will differ on purpose. Every intended difference is declared in the QA code below **before** deploy; the gates then tell "intended" from "drift". The runtime numbers (audit 43/43, parity 42 PARITY + 1 NEW, perf budgets) are filled in by the PM's post-deploy run (§9.4). Nothing here changes the paper-only posture: no gold series feeds the Decision Desk, the S1 shadow, a directional alert or the paper ticket's price (PLAN 0.1 #7).

### 9.1 What changes, page by page

Every "Declared in" entry is **page-scoped** since wave 1b (`netpolicy.ExpectedDelta.tabs`): the same request on any other page is a DIFF. The exact request shapes were read back from the fetchers (`ui/lib/gold/api.ts`, `Brief.tsx`, `WorldMarkets.tsx`, `McxGoldDesk.tsx`, `gold/IciciTotpPanel.tsx`) and the mounted routes (`services/ui-api/main.py`, `routers/gold.py`, `positions.py`, `mcx.py`, `gold_preopen.py`) and are pinned by `tests/integration/test_desktop_qa_harness.py::test_gold_deltas_are_what_the_ui_sends_and_the_server_mounts` (which also greps the 25 Oct bundle in `ui/dist/previous` for the A-side shapes).

| Surface | 25 Oct release (parity side A) | Gold program (parity side B) | Status | Declared in |
|---|---|---|---|---|
| **GOLD** (`?tab=gold`, code `GOLD`, "Gold terminal", GO aliases `XAU`, `GC`) | Does not exist: `?tab=gold` falls back to the brief and no GOLD code chip ever renders | The 43rd page, after MCXG in the Derivatives & Gold group, no ⌘ digit; sub-views HEALTH, DAILY, WEEKLY, MONTHLY, POSITIONING, PHYSICAL, MACRO, CONTRACTS, LEARN; the pre-open desk and accuracy log live here (`h.open`, `h.accuracy`); reads the whole `/api/gold/*` family | NEW | `netpolicy.EXPECTED_NEW_PAGES` (parity visits B only → verdict NEW, never compared); `gold-page-api` (any `/api/gold/*`, any query, tabs `{gold}` — tags the audit report only); `desktop/src-tauri/src/pages.rs` PAGE_COUNT 43; `ui_audit.TABS` + `gold` |
| **CMDT** | Gold Pre-Open desk at the top (desk, gap build-up, your inputs, context table, headlines, manual checks, accuracy log) reading `GET /api/commodity/gold-preopen[?inputs]` and `/gold-preopen/log?threshold=300`; label "Commodities · Gold desk"; subtitle "MCX gold pre-open desk · …" | No desk and **no gold request at all** (the board tile carries a `GOLD ›` chip; its detail chart opens GOLD › WEEKLY); label "Commodities"; subtitle "… · gold lives on GOLD" | DIFFERENT-INTENDED | `netpolicy.EXPECTED_STRUCTURE_DELTAS["commodity"]` (panels, table headers, page header, table count); `gold-preopen-moved` (A-only, tabs `{commodity, brief}`, any query: the retired desk sent its saved inputs) |
| **BRF** › Market panel | A full "Gold open (MCX)" panel (verdict, fair, baseline, gap, chase limit; after 09:15 "this morning's call"), rotated on the NSE 09:15 clock; reads the desk and its log | One `Line` from `GET /api/gold/health?window=W` (`getGoldHealth('W')`, the only gold read): `Gold open: fair ₹… (gap …) · WAIT · … · GOLD ›`; after the captured open the miss; on MCX holidays the closure note. The 09:15 rotation goes | DIFFERENT-INTENDED | `EXPECTED_STRUCTURE_DELTAS["brief"]`; `gold-health-line` (B-only, exactly `?window=W`, tabs `{brief, world}`); `gold-preopen-moved` (A-only) |
| **WEI** › Commodities › GC=F row | last, Δ, Δ %, 1-month spark, day-range position, age; nothing gold requested | Same row plus one second line (verdict words, basis, COT MM, roll date, `GOLD ›`) and a hover card from `GET /api/gold/health?window=W`; tooltip names the instrument ("Yahoo continuous front GC=F") | DIFFERENT-INTENDED (no structural change) | `EXPECTED_STRUCTURE_DELTAS["world"]` (note only); `gold-health-line` |
| **MCXG** | "COMEX × rupee overlay" panel (4 stats + prose); "Contract specs — MCX gold family" table (`Contract | Lot | Quote | Tick …`) from `GET /api/mcx/specs`; subtitle "… contract specs · COMEX overlay" | The overlay is one **line** inside the Quote panel (from `/api/mcx/overlay`, on both sides) with a `GOLD ›` chip — no overlay panel; the specs card is replaced by the shared selector panel **"Contracts — MCX gold family"** (`ContractSelector`, dense: family cards + the "`<FAMILY>` EXPIRIES · OI LADDER" table `Expiry | Source | settle ₹/10 g | band ₹ | OI lots | ΔOI lots | carry % p.a. | COMEX month | Tender`) reading `GET /api/gold/contracts?exchange=MCX` (the selector offers MCX only; NSE/BSE are disabled); subtitle "session clock · live quotes … · contract selector · paper ticket"; `/api/mcx/session`, `/quote`, `/overlay`, `POST /ticket` on both sides and compared | DIFFERENT-INTENDED | `EXPECTED_STRUCTURE_DELTAS["mcxgold"]` — A-only `^COMEX × rupee overlay$`, `^Contract specs`, header `^Contract \| Lot \| Quote \| Tick`; B-only pinned to `^Contracts — MCX gold family$` and header `^Expiry \| Source \| settle` (a retained overlay panel or a second specs-like panel on B is a DIFF); `^MCXG\b` page header both sides; table count. `gold-mcxg-selector` (B-only, exactly `?exchange=MCX`, tabs `{mcxgold}`); `gold-mcxg-specs-replaced` (A-only `/api/mcx/specs`, no query, tabs `{mcxgold}`) |
| **BRKR** | No auto-login panel | "Auto-login (TOTP)" panel (`gold/IciciTotpPanel.tsx`) in both connected and not-connected layouts (status chip, the three steps, test, disable); on load reads `GET /api/positions/totp/status` with no query (`?reveal=1`, the POST/DELETE calls and `POST /api/telemetry/icici-refresh` are clicks, never on load) | DIFFERENT-INTENDED | `EXPECTED_STRUCTURE_DELTAS["broker"]` (B-only `^Auto-login \(TOTP\)$`); `gold-brkr-totp-status` (B-only, no query, tabs `{broker}`) |
| Macro tape (every page) | "GOLD" = GC=F | Label "GOLD GC1"; unchanged otherwise | DIFFERENT-INTENDED | not fingerprinted (text only) |
| **ECO / EVTS** | No US CPI/NFP/PCE; no gold events | Gain the US releases in IST and the gold rows (COT release, COMEX FND/LTD, MCX expiries, Dhanteras, Muhurat, Budget) from `gold_events` | DIFFERENT-INTENDED (rows only) | same endpoints; row text is not fingerprinted |
| **RSCH** | 84 studies, none gold | CATALOG rows for the gold reports and studies | DIFFERENT-INTENDED (rows only) | — |
| Go menu, GO bar, title strip | 42 codes | 43 codes; GO exact-code match `GOLD`; aliases `XAU`, `GC` | NEW | `pages.rs`, `ui/components/desktop/pages.ts`, `ui/lib/goAliases.ts` (B4A) |
| 08:45 Telegram gold alert | fair open + chase limit | same + the measured miss; skips MCX holidays; Saturday COT digest line | DIFFERENT-INTENDED (owner O-14) | outside the UI gates |
| Decision Desk, S1 shadow, alerts, paper ticket price, every other page (DESK, ALRT, PORT, …) | — | Unchanged — and a gold request appearing on any of them is reported as `API request set differs`, never set aside | SAME | PLAN 0.1 #7; `netpolicy.expected_delta_applies` |

### 9.2 The gates (what changed in the QA code, and their state on 4 Nov 2026)

Everything below is green against the tree on 4 Nov (wave 1 landed; wave 1b reworked the checks). Nothing was run against the live stack.

| Gate | Change | State on 4 Nov |
|---|---|---|
| `desktop/src-tauri/src/pages.rs` | PAGE_COUNT 43; `gold` / `GOLD` / "Gold terminal" after `mcxgold`, group DerivativesGold, shortcut 0 (the nine ⌘ digits unchanged); CMDT label "Commodities"; the count asserts say 43; a test pins GOLD's place | `cargo fmt --check` clean, `cargo clippy --locked --all-targets -D warnings` clean, `cargo test --locked`: **154 passed** (one transient failure was seen only while the core pytest suite ran concurrently; serial re-runs 154/154 — run the Rust gates on their own) |
| `tests/integration/test_desktop_contract.py` | page count 43 (`PAGE_COUNT`, pages.rs PAGE_COUNT cross-checked) | **23 passed** |
| `tests/integration/test_gold_gates.py` | registries agree on 43 + the GOLD entry (page.tsx, tabModules.ts, desktop/pages.ts, pages.rs, goAliases.ts; CMDT label); T9 repetition — **comment-proof since wave 1b**: TSX read with `//`, `/* */` and JSX `{/* */}` comments blanked (`strip_ts_comments`), Python through the AST — one `<GoldPreOpen />` render, Brief one gold-line read and neither `getGoldPreOpen` nor `getGoldLog` and no gold panel, CMDT no desk and no "gold desk" wording, `routers/gold.py` composes `gold_preopen` (imports `_yahoo_bars_cached`, or calls `gp._yahoo_bars_cached` / `gp._gold_preopen` / `gp.fair_open`; a docstring naming the fetcher no longer counts — it did in wave 1) and carries no Yahoo URL / `yfinance` / `_yahoo_bars(` in code, ui-api's Yahoo literals (string constants only) stay the existing four; T8 host allowlist over `services/data-service/gold/**` + `routers/gold.py` — the link exemption is the AST name (`link`/`links`/`href` key, `LINKS`/`*_LINK`) or a **tokenised comment** on the line or the line above (`# link-only`, `# link: …`; the string's own text such as `/links.html` never counts), all of `catalog_seed.py`, or a container named as a denylist; `api.stlouisfed.org` only in a **file** that reads `FRED_API_KEY` (per file since wave 1b, not scan-wide); a bare literal is a host only with a public suffix. PLAN §d's `*_url` keys are not link markers: B3's `REUTERS_LINK` and `fedwatch_link` carry `# link-only` and pass. Fails, never skips | **29 passed** (6 registries, 5 T9, 4 T8 against the tree; 14 fixture tests of the checks themselves with negative controls: commented-out renders/calls/imports, a `# link` comment vs a `/links.html` path, a two-file FRED key, a docstring that names the fetcher) |
| `scripts/ui_audit.py` | default `TABS` + `gold` → **16**; `--tabs all` reads TAB_IDS from page.tsx at run time (43); per-tab `repetition_hits` and a T9 failure when "fair open" titles more than one panel/heading on a page | unit-tested; runtime run after deploy |
| `scripts/desktop_qa/netpolicy.py` | `ExpectedDelta.tabs` (page scope; `None` = page-free as the header's holiday lookup) and `expected_delta_applies(id, tab)`; the gold deltas are page-exact: `gold-health-line` (`GET /api/gold/health?window=W`, BRF/WEI), `gold-mcxg-selector` (`GET /api/gold/contracts?exchange=MCX`, MCXG), `gold-preopen-moved` (A-only, CMDT/BRF), `gold-mcxg-specs-replaced` (A-only `/api/mcx/specs`, no query, MCXG), `gold-brkr-totp-status` (no query, BRKR), `gold-page-api` (the family, GOLD only); `EXPECTED_NEW_PAGES` (gold); `EXPECTED_STRUCTURE_DELTAS` with MCXG's B side pinned to the selector panel/table and BRKR's to `^Auto-login \(TOTP\)$` | unit-tested (`test_gold_expected_deltas_are_page_exact_and_tab_scoped`, `test_expected_delta_applies_is_the_tab_gate`, the drift guard against the fetchers/routes/25 Oct bundle) |
| `scripts/desktop_qa/parity.py` | a declared NEW page is visited on B only (verdict NEW); a one-sided tagged request is set aside **only when its delta is declared for that tab** (`expected_delta_applies`; an unattributed visit is compared, not excused); declared structure deltas set aside under `expected_structure`; exit 0 needs every compared tab PARITY **and** every NEW page clean on B; `--no-expected-deltas` turns all of it off | unit-tested (`test_compare_keeps_a_gold_read_on_an_undeclared_page_as_a_diff`: the same B-only `/api/gold/health?window=W` is set aside on WEI and a DIFF on DESK) |
| `tests/integration/test_desktop_qa_harness.py` | 43 pages; 16 default tabs; the gold delta, tab-gate, negative-control, drift-guard, NEW-page, structure-partition (pinned MCXG/BRKR titles), summary/markdown and repetition-rule tests | **108 passed** |
| `scripts/desktop_qa/pages.py`, `scripts/ui_perf.py` | parsers are count-free (they read page.tsx); ui_perf's docstrings say 43 | — |
| lint | `ruff check --line-length 130` and `compileall` clean on the eight owned Python files; `cargo fmt --check` / clippy (default and `devtools`) clean | green |
| core suite (`pytest tests -q -W ignore --ignore=tests/integration/test_desktop_ops.py`) | none of the three gate files fails | two full runs on 4 Nov: 6 failed / 791 passed, then 2 failed / 814 passed — **all outside B6's files** and order-dependent (the failing set changed between runs; in isolation 2 of 7 fail; the second run added `tests/gold_replay/test_replay_physical_india_local.py::test_briefs_validate_dedupe_and_index`): `tests/gold/test_schema_pit.py::test_release_events_carry_the_monday_dated_report_and_the_ist_instant` (the COT release label "Tue 11 Nov" is missing from the computed set — date-dependent, B1), `tests/gold_replay/test_replay_macro_yahoo.py::test_in_progress_sunday_globex_bar_is_dated_to_mondays_session_and_replaced_by_the_completed_bar` (B1), plus `tests/gold/test_jobs_api.py` ×2, `tests/gold_replay/…::test_yahoo_daily_csv_seeds_cover_every_catalogued_symbol`, `tests/test_gold_study_reproduce.py` ×2 when run in the full suite (B1 / B7; a shared temp-DuckDB or module-state leak between gold test modules is the likely cause) |

Not B6's: `scripts/desktop_qa/probe.py` (it tags every request page-free; the tab check lives in `parity.compare` by design), `docs/RUNBOOK_RESTORE.md` / `CLAUDE.md` page counts (B5), `ui/components/desktop/__tests__/desktop.check.ts` (B4A).

### 9.3 How to read the post-deploy parity report

Expected per engine: `42/42 PARITY + 1 NEW (no A side: gold)`, `DIFF: none`, `NEW pages failing their B audit: none`, `intended structure deltas (set aside): brief, commodity, mcxgold, broker`, `expected program deltas on one side only (set aside)` including brief, world, commodity, mcxgold, broker (plus `header-holidays` wherever the 25 Oct release still sends `?back=0&ahead=7` on one side only). Any other tab under DIFF, and any `panels differ` / `tables:` reason on commodity, brief, mcxgold or broker, is drift to review, not a declared change. The `gold` row shows "—" in the A columns by design; its B audit (console, page errors, failed requests, repetition) must pass.

**Page scope (wave 1b).** A set-aside is granted per page: `GET /api/gold/health?window=W` is excused on BRF and WEI only, `/api/gold/contracts?exchange=MCX` on MCXG only, the TOTP status on BRKR only, the retired desk reads (A side) on CMDT and BRF only. The same request on any other tab — DESK, ALRT, PORT, WATCH, the macro tape host pages — appears as `API request set differs: only B ['GET /api/gold/…']` and that tab is a DIFF: this is the evidence for "existing pages unchanged except PLAN §b" and PLAN 0.1 #7 ("nothing gold feeds the Desk"). Another `/api/gold` path or query on BRF/WEI/MCXG (say `?window=D`) is also a DIFF (it is tagged `gold-page-api`, which applies to GOLD alone). If a DIFF of this kind is intended, the fix is a new page-scoped entry in `netpolicy.EXPECTED_DELTAS`, never a wider one.

Run `--no-expected-deltas` on the five gold pages to *see* the set-aside differences as DIFFs (review only; it exits 1 by construction).

### 9.4 Commands (PM, after deploy; read-only against the live stack: prefs readonly, WebSockets mocked, no writes)

Side A is the release that is live **today** (4 Nov): `ui/dist/releases/20261025-223942-0ae66db` (= `ui/dist/current` until `./start-local.sh build-ui` publishes the gold release, after which `ui/dist/previous` points at it). Pin the release directory rather than the symlink so the comparison does not depend on how many builds were published in between. The old UI keeps working on the new backend only while `/api/commodity/gold-preopen*` stay mounted as aliases (PLAN §d, one release; `test_gold_deltas_are_what_the_ui_sends_and_the_server_mounts` checks `main.py` for the mount) and `/api/mcx/specs` still exists (it does).

```bash
P=/Users/sudheer/Desktop/jupyter_env/bin/python
S=/private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/<session>/scratchpad/gold-gates   # any scratch dir outside the repo
A=ui/dist/releases/20261025-223942-0ae66db        # the release live before the gold deploy (ui/dist/previous after build-ui)
mkdir -p "$S"

# 0. the static gates first (fail, never skip) — all green on 4 Nov
$P -m pytest tests/integration/test_desktop_contract.py tests/integration/test_desktop_qa_harness.py tests/integration/test_gold_gates.py -q

# 1. T10 — the page audit: default 16 tabs (incl. gold), then all 43 in both engines (TAB_IDS read from page.tsx)
$P scripts/ui_audit.py --out "$S/audit16"                                   # expect: [chromium] 16/16 PASS
$P scripts/ui_audit.py --tabs all --browser both --out "$S/audit43"          # expect: 43/43 PASS per engine; failed requests only platform seams;
                                                                              #         repetition_hits ≤ 1 on every tab (audit_report.md)

# 2. T12 — parity: A = the pre-gold release on a scratch server over the SAME live backend, mutations blocked; B = the live terminal
$P scripts/desktop_qa/scratch_server.py --ui "$A" --port 8091 --backend http://127.0.0.1:8010 --block-mutations &
$P scripts/desktop_qa/parity.py --a http://127.0.0.1:8091 --b http://127.0.0.1:8010 --browser both --out "$S/parity" \
    --label-a "pre-gold release 20261025-223942" --label-b "gold program release"
# expect per engine: 42/42 PARITY + 1 NEW (gold) · DIFF: none · structure deltas set aside: brief, commodity, mcxgold, broker
#                    · expected deltas set aside on brief, world, commodity, mcxgold, broker — and on NO other tab
$P scripts/desktop_qa/parity.py --a http://127.0.0.1:8091 --b http://127.0.0.1:8010 --browser chromium --no-expected-deltas \
    --tabs brief,world,commodity,mcxgold,broker,gold --out "$S/parity_strict"    # review only: shows the declared deltas as DIFFs, exits 1
kill %1

# 3. T11 — perf budgets: tab-switch p95 ≤ 400 ms for gold; first-load JS ≤ 300 KB gz (no new chart library)
$P scripts/ui_perf.py --base http://127.0.0.1:8010 --browser both --runs 3 --tabs gold,commodity,brief,world,mcxgold --label gold_release
$P scripts/ui_perf.py --bundle-dir ui/dist/current --label gold_release_bundle

# 4. T12 — desktop: the Rust gates (CI's macOS job; run them on their own, not beside the core pytest suite) and the installed
#    app's self-test (no other instance running; outside the freeze windows 07:45–09:20 and 18:30–21:15 IST)
(cd desktop/src-tauri && cargo fmt -- --check && cargo clippy --locked --all-targets -- -D warnings && cargo test --locked)
node desktop/scripts/boot_check.mjs                                           # 74/74 on 4 Nov
$P scripts/desktop_qa/run_selftest.py --app /Applications/SuryaDhana.app --live
```
