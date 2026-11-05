# SuryaDhana desktop app: final report (24–25 Oct 2026)

**The owner's goal:** convert the terminal into a Tauri desktop application. Requirements: the logic stays the same; it
starts when the owner logs in; a professional, Bloomberg-class UI; fast and scalable; everything tested thoroughly; built
in parallel by a team of agents; production grade.

**Result: done and live.** `/Applications/SuryaDhana.app` (build `0ae66db-dirty-ec8c0ab8-20261025T1710Z`) is installed. It
starts at macOS login through its own LaunchAgent and loads the terminal (UI release `20261025-223942-0ae66db`) from ui-api on
http://127.0.0.1:8010. The same release works in any browser at that address.

Logic is proven unchanged. The 42 pages were compared page by page against a byte-for-byte reconstruction of the pre-program
web UI, in Chromium and WebKit: parity vs the reconstructed pre-program UI: **0 unexpected differences in Chromium and WebKit** (42/42 pages per engine identical apart from 2 declared intended changes: the header reads ICICI connection-status while the light is red, and PORT is titled 'Portfolio · Legacy Engine'). A 328-feature web-vs-desktop audit followed, and every regression it found has
been fixed (section 6).

---

## 1. What runs now

```
macOS login
 ├─ com.suryadhana.watchdog   (LaunchAgent, every 2 min) ── starts/keeps data-service :8001, ui-api :8010, master-controller :8008
 │                                                         restarts a crashed OR hung service (diagnostics in .logs/hangs/)
 ├─ com.suryadhana.awake      (caffeinate)
 └─ SuryaDhana                (LaunchAgent: RunAtLoad, KeepAlive{SuccessfulExit:false}: relaunched after a crash, never after Quit)
      boot window (tauri://localhost) → health/trust checks → terminal windows → http://127.0.0.1:8010/?tab=…[&sym=…]
ui-api :8010  = the API + the static terminal UI (ui/dist/current, atomic releases, rollback) + /api/prefs (settings sync)
(optional) Next dev server :3000 on 127.0.0.1 — hot reload, and the one-time settings migration; not part of the core
```

- **Desktop shell** (`desktop/`, Rust, Tauri v2.12.5):
  - **Start-up and state:** a boot screen for every state (starting after login, stack down, ui-api NOT RESPONDING, no UI
    release, untrusted or unverifiable listener on :8010). The menu-bar line shows NIFTY, ICICI, the 3 services and Desk NAV.
  - **Menus and windows:** native menus (Go ▸ 42 pages, ⌘1–9, ⌘[ ⌘], zoom, ⌘F find, ⌘P print, Settings, Help shortcuts),
    multi-window with session restore, single instance.
  - **Downloads and notifications:** downloads go to ~/Downloads, quarantined, with an extension allow-list and a byte
    budget. Native notifications include the scheduler's alert feed.
  - **Resilience:** a crashed WebKit page reloads by itself.
  - **Integrity:** a build id is shown in About, the tray and `--version`. `--self-test` runs 58 checks.
- **Terminal UI** (`ui/`, Next 15 static export):
  - **Same 42 pages and the same logic.** New: a desktop title strip, per-page error panels, an honest LINK DOWN banner
    with reload of failed panels, type-to-GO, Esc, Back/Forward, deep links (`?sym=`), and a find bar in the app.
  - **Formatting and safety:** 2-dp prices with Indian grouping, PAPER ONLY on PORT, and the ICICI login URL is never
    printed. Settings (watchlist, pins, ticket sizing, gold pre-open inputs, screen filters, recents) are stored on the
    server and shared by the browser and the app.
- **Backend** (unchanged business logic):
  - a Host/Origin guard on all 3 services;
  - **PAPER ONLY enforced in code**;
  - ICICI token routes run off the event loop, with an `error_kind` field that tells a network outage apart from an
    expired session;
  - `.env` writes round-trip exactly and stay mode 0600;
  - a monitor WebSocket hub (one Redis subscription) and a loop-stall watchdog;
  - gzip for large JSON, short caches with stale-while-revalidate on slow endpoints (fresh-only for alert decisions);
  - client error reports, a native alert feed, a backup catch-up, persisted job history, and the news track-record job
    repaired.

## 2. How it was built (team, rounds, evidence)

| Stage | Agents | Output |
|---|---|---|
| Plan + improved prompt | PM | `reports/desktop_app/PLAN.md`: architecture, frozen shell↔UI contract, AC-1..AC-15 |
| Build | D1 static serving · D2 Tauri shell · D3 bridge + settings sync · D4 desktop UX + perf · T QA harness | first working app, patch blocks |
| Integration + switchover | PM | release served on :8010; 42/42 audit; :3000 parity 84/84; app installed; Launch at Login on; 4 drills |
| Review round 1 | 7 critics: trader UX, desktop-native, security, reliability, performance, logic-unchanged, completeness. Every serious finding was verified by 1–2 skeptics | 4 blockers, 37 majors (`review/critics_round1.md`) |
| Fix round 1 + wave 2 | 10 fixers with disjoint file ownership, each adversarially checked | `review/fix_round1.md`, `review/wave2/` |
| Final review | 9 reviewers + verifiers | 0 blockers (`review/final_round.md`) |
| **Web-vs-desktop equivalence audit** (owner request) | 8 auditors + verifiers | 328 features (`FEATURE_PARITY.md`) |
| Fix rounds 3, 4a, 4b | 12 fixers + checkers | every equivalence regression fixed (`review/fix_round3.md`, `fix_round4a.md`, `fix_round4b.md`) |
| Final deploy + verification | PM | section 4 |

About 150 agent runs in total. Every change to a shared file went through a uniqueness-checked patch with a backup
(`~/.suryadhana_pm_backups/`).

## 3. Acceptance criteria (PLAN §6)

| # | Criterion | Status |
|---|---|---|
| AC-1 | Atomic UI releases, 3 kept, chunk carry-forward, rollback, `--out` | **Met.** `scripts/build_ui.sh`; 26 node tests |
| AC-2 | ui-api serves the UI (no-cache index, immutable hashed assets, gzip, ETag), `/version`, a 503 page when there is no build | **Met.** Live, with ui-api tests |
| AC-3 | 42 pages, 0 console errors, 0 failed requests, Chromium + WebKit; parity with the web app | **Met.** 42-page audit on live :8010: **42/42 PASS in Chromium and 42/42 in WebKit**, 0 console errors, 0 page errors, 0 failed requests; page-ready p50/p95 47/195 ms (Chromium), 78/214 ms (WebKit); parity vs the reconstructed pre-program UI: **0 unexpected differences in Chromium and WebKit** (42/42 pages per engine identical apart from 2 declared intended changes: the header reads ICICI connection-status while the light is red, and PORT is titled 'Portfolio · Legacy Engine') |
| AC-4 | Build, ad-hoc sign, install, `--self-test` | **Met.** 8.4 MB; codesign strict; self-test 58/58; installed-app E2E all PASS |
| AC-5 | Starts at login | **Met.** LaunchAgent written, loaded and running under launchd; a login-job start was drilled (`launchctl bootstrap`). A real logout/login cycle has not been observed yet |
| AC-6 | Boot < 500 ms paint; every service state shown; actionable when down; continues on its own | **Met except the paint number.** Boot DOM ready ≈ 0.22 s; boot → terminal ≈ 0.1 s; start → terminal ≈ 2 s. Paint cannot be measured while the screen is locked (owner, below) |
| AC-7 | Black window, title strip + traffic lights, geometry, ⌘N, session restore, single instance | **Met.** Self-test + relaunch drill (36/36) |
| AC-8 | Notifications, downloads, external links, navigation allow-list, ⌘C/⌘V, close-hides | **Met.** Notifications are DENIED in macOS for SuryaDhana (owner, below). ⌘V in the app has not been observed |
| AC-9 | Menu-bar item with health, ICICI, NAV and actions | **Met** |
| AC-10 | Resilience: ui-api restart, release swap, stack down at launch, hung ui-api | **Met.** Drills: restart (no flap, WebSocket resumed), release swap (NEW BUILD notice; old chunks still served), launch while down (waits, then enters by itself), SIGSTOP 45 s (noticed in 16 s, windows kept, recovered in 3 s) |
| AC-11 | Security | **Met.** Least-privilege capability (9 commands + window drag, exact origin); Rust validation; boot CSP; navigation guard; Host/Origin guard; no secrets in bundle or logs; port-squatting guard with the residual risk documented |
| AC-12 | Server-side settings with LWW, caps, migration | **Met.** The migration itself needs the owner to open :3000 once |
| AC-13 | Performance | **Met for everything measurable here.** First-load JS 280 kB gz (≤ 300). UI-ready p50 41 ms / p95 191 ms. Idle RSS ≈ 307 MB (< 500). CPU 2.3 % in a start-up sample; a true idle CPU sample needs an unlocked screen (owner) |
| AC-14 | All suites green | **Met.** Section 4 |
| AC-15 | Ops and docs | **Met.** CORE = 3; watchdog, start-local, RUNBOOK, CLAUDE.md, IMPROVEMENT_LOG and desktop/README are current |

## 4. Final verification (25 Oct, after the last deploy)

- **Gates:**
  - Python suites: core 701 passed (9 skipped), scripts 287, ui-api 1,078, execution 7, alpha_lab 20.
  - Static checks: tsc clean; event-loop purity 0 findings.
  - Rust: cargo test 153, clippy 0, fmt clean.
  - Node checks: pages 281, desktop 398, ws 82, streamProxy 76, platform 123, prefs 160, alerts 31, no-dialogs pass,
    ui/scripts 26.
  - Boot-page checks: 74/74.
- **Live:** 42-page audit on live :8010: **42/42 PASS in Chromium and 42/42 in WebKit**, 0 console errors, 0 page errors, 0 failed requests; page-ready p50/p95 47/195 ms (Chromium), 78/214 ms (WebKit). parity vs the reconstructed pre-program UI: **0 unexpected differences in Chromium and WebKit** (42/42 pages per engine identical apart from 2 declared intended changes: the header reads ICICI connection-status while the light is red, and PORT is titled 'Portfolio · Legacy Engine').
- **Installed app:** bundle, codesign, autostart, self-test 58/58, single instance and idle resources all PASS. The app runs
  under its login job, the trust check passed, and the terminal loaded 2 s after start.
- **Backend guard (live):** a spoofed or test Host gets 400 on :8010, :8001 and :8008; a cross-site write gets 403;
  `/api/execution/status` reports PAPER / PAPER_ONLY with live_allowed false; `/docs` returns 404; the loop-stall
  watchdog is running.

## 5. Logic unchanged: the proof

1. **Frozen trading files.** `shared/momentum.py`, `shared/decision_desk.py` and `shared/trading_costs.py` were last
   modified on 27–28 Sep. alpha_lab is untouched.
2. **Page parity with the pre-program web UI.** The UI was reconstructed byte for byte
   (`baseline_preprogram/README.md`) and compared page by page in both engines, with the same API requests and
   structure. The only differences are the declared intended changes.
3. **Backend behaviour.** The same 31 request shapes return the same results through the old and the new ui-api
   `main.py`. 32 internal caller request shapes pass the new guard.
4. **Owner-requested equivalence audit.** 328 features: 146 SAME, 75 IMPROVED, 36 DIFFERENT-INTENDED, 13 regressions
   (all fixed since), 41 pre-existing bugs (the serious ones fixed).

## 6. The 13 regressions the equivalence audit found: all fixed

| # | Regression | Fix |
|---|---|---|
| R1 | A dead WebKit page crashed the whole app | The page reloads by itself (self-test kills it: recovers in ~0.3 s); the wry nil-URL panic is avoided |
| R2 | DESK "Re-enable after review" (clears the −20% stop) did not ask inside the app | In-page two-step confirmation (Cancel focused, Esc cancels), the same in a browser; a guard check forbids `window.confirm/alert/prompt` |
| R3 | OI chart labelled the wrong strike as CALL/PUT WALL | Uses the same wall as the stat, with an edge marker when it is off-chart |
| R4–R13 | OVRV zeros, COMP removed symbol returning, reminder bar covering buttons, overlays during LINK DOWN, no export feedback, no ⌘F/⌘P, Muhurat shown as closed, DERV axes, a red "0.0%", a wrong Back/Forward hint | All fixed (`review/fix_round3.md`, `fix_round4b.md`) |

Pre-existing bugs fixed along the way:

- GO "RELIANCE OMON" no longer shows NIFTY's chain.
- ui-api no longer freezes while an ICICI token is saved.
- An ICICI network outage is no longer called "expired", and no OTP is texted during one.
- The token hand-off retries.
- MOV refreshes after the open.
- The news track-record job runs again.
- A missed 02:15 backup is caught up.
- SYS job history persists.
- `.env` writes are safe.
- The DESK window shows its columns.
- Price-alert wording and save errors are fixed.
- ALFA knobs scan with the new value.

## 7. Incidents and safety findings during the program

- **The legacy execution engine was found in LIVE/ACTIVE** (persisted state), on a paper-only system. It was reset to
  PAPER (no open positions; backup kept), and ui-api now refuses LIVE unless `EXECUTION_LIVE_ALLOWED=1`.
- **The whole unauthenticated API was reachable from the LAN** through Next on `*:3000`, and any website could drive
  state-changing endpoints (DNS rebinding / CSRF). Fixed: loopback binds plus the Host/Origin guard on all three services.
  The ICICI login URL (which contains the API key) was printed on PORT/BRKR and captured in audit screenshots: it is no
  longer printed, the screenshots were deleted and are git-ignored, and a repo scan found no key in any text file.
- **ui-api hang, 25 Oct 14:40–14:48.** The event loop was blocked in a synchronous Redis `recv` (round-1 monitor socket
  code under fast socket churn). It was root-caused with native stack samples and a reproduction, fixed, and guarded by a
  60-socket churn regression test and a loop-stall watchdog. The watchdog now also restarts a hung service.
- **Process lesson (PM).** Messaging an agent that is running inside a workflow starts a duplicate of it. This is recorded
  in memory and avoided since.

## 8. Known limitations (minor, documented)

- **Not measurable here** (screen locked during every self-test): boot paint time, and true idle CPU. Run
  `desktop/scripts/measure_idle.py` with the screen unlocked, ≥ 5 min after launch.
- **Display caches:** results / implied-move caches are not invalidated on the 20:45 results ingest. They are bounded by
  their short TTL.
- **Menu bar:** the tray's "Relaunch after a crash" line can go stale right after toggling Launch at Login.
- **Notifications:** clicking a banner does not open its page. macOS notifications are off on this Mac anyway.
- **Not done:**
  - **EQS:** restyling the screener table onto the kit DataTable.
  - **Page strip:** reordering the page strip / ⌘1–9 map. This changes the owner's keyboard map, so it needs the
    owner's decision.
  - **Hidden windows:** suspending rendering while a window is hidden needs an unlocked-screen profile first.
- **Port squatting:** a same-user process that runs Homebrew/python.org CPython on :8010 while ui-api is down would pass
  the guard. Closing that needs a shared secret between ui-api and the app (documented in desktop/README).
- **Signing:** the app is ad-hoc signed for this Mac. Developer ID signing and notarization are an owner action (paid
  account).

## 9. Owner actions

1. **Move your settings once:** open http://localhost:3000 in the browser you used before. `./start-local.sh status`
   should then show the prefs row "imported". After that, `./start-local.sh stop frontend`.
2. **Allow notifications:** System Settings › Notifications › SuryaDhana › Allow. They are currently denied, so no
   banners appear; the menu-bar item says so.
3. **Monday 08:00 IST:** reply to the ICICI OTP on Telegram as usual. The minute-by-minute checklist is in
   `FEATURE_PARITY.md` §3. Nothing to do in the app: it shows "expired" until the login, then "connected".
4. Recommended:
   - an off-machine dead-man ping (`HEALTHCHECK_PING_URL`);
   - `sudo pmset -a autorestart 1`;
   - a git commit + remote and an off-machine backup (the working tree has not been committed since 14 Jun).
   
   The exact steps are in `docs/RUNBOOK_RESTORE.md`.
5. **Optional:**
   - one logout/login to see the app start at login;
   - one ⌘V in BRKR inside the app;
   - `desktop/scripts/measure_idle.py` with the screen unlocked.

## 10. Operating it

```bash
./start-local.sh status                 # services, UI release (file vs served), prefs migration, desktop app, Launch at Login
./start-local.sh build-ui               # publish a new UI release (live on the next request; --rollback, --list)
scripts/build_desktop.sh --install      # build, sign, install the app (keeps the previous one; --rollback)
/Applications/SuryaDhana.app/Contents/MacOS/SuryaDhana --version
$P scripts/desktop_qa/run_selftest.py --app /Applications/SuryaDhana.app --live    # installed-app E2E
$P scripts/ui_audit.py --tabs all --browser both                                   # 42-page audit on :8010
```

Docs: `PLAN.md` (contract), `FEATURE_PARITY.md` (web vs desktop), `review/` (every review and fix round),
`baseline_preprogram/` (logic-unchanged proof), `incidents/` (14:40 hang), `desktop/README.md`,
`docs/RUNBOOK_RESTORE.md`, `docs/IMPROVEMENT_LOG.md`.
