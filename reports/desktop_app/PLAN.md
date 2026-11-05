# SuryaDhana Desktop: program plan and contract (24 Oct 2026)

Status: **ACTIVE**. Owner request (verbatim intent): convert the terminal to a **Tauri desktop app**, logic unchanged;
it **starts when the owner logs in**; the UI is **Bloomberg-terminal grade**, fast and scalable; everything is
**tested thoroughly**; the work is done **in parallel by a team of agents** (migrate, test, improve), and the result is
professional and production grade. Background: `reports/desktop_app/FEASIBILITY.md` (Options 1 and 2, proven in
Chromium and WebKit).

---

## 1. The improved prompt (what we are actually building)

> Build **SuryaDhana.app**, a native macOS desktop terminal (Tauri v2, system WKWebView) for the existing
> SuryaDhana stack, in two layers:
>
> **Layer 1, Node out of production.** The Next.js terminal is built as a **static export** and served by
> **ui-api on 127.0.0.1:8010**, on the same origin as `/api`, SSE and the WebSocket. Builds are **atomic releases**
> with rollback, and old chunks stay servable so an open window never breaks. Caching is correct: hashed assets are
> immutable and `index.html` is no-cache. Precompressed gzip is used when the client accepts it. Dev hot reload
> (`next dev` on :3000) keeps working.
> The production stack goes from 4 processes to 3 (data-service, ui-api, master-controller).
>
> **Layer 2, the desktop shell.**
> - A ~15 MB `.app` that **launches at login** (toggleable).
> - It opens a **Bloomberg-style boot screen** that checks every service, then loads the terminal.
> - Native **multi-window**: ⌘N opens another panel. Window geometry and the set of open windows are restored on relaunch.
> - **Single instance**.
> - A **dark overlay title strip** with page code, IST clock, market session and connection state.
> - A full **native menu bar**. The Go menu holds all 42 function codes; the Edit menu makes copy/paste work.
> - A **menu-bar item**: a live NIFTY ticker plus health of the 3 services, ICICI session state and Desk NAV.
>   Its actions: start the stack, stop the stack (guarded), open logs, launch at login.
> - **Native notifications** (price alerts, service down/up).
> - **Native downloads** to ~/Downloads.
> - **External links** open in the default browser.
> - **Least-privilege IPC.**
>
> The backend stays as the launchd-supervised services, so it runs **whether or not the window is open**. Closing
> the window keeps the app (and its notifications) alive in the menu bar.
>
> **User settings** (watchlist, pins, recents, page preferences) move from per-browser localStorage to **ui-api
> storage**, so the browser, the app and every window share them. There is a one-time migration from the old origin.
>
> **No trading, data or API logic changes.** Every page must behave identically: a 42-page parity audit in Chromium
> **and** WebKit against the old :3000 build, with 0 console errors and 0 failed requests.
>
> **Measure** cold start, boot-to-interactive, tab-switch latency and memory against budgets.
>
> **Verify** the shell from inside WKWebView with a built-in `--self-test` mode.
>
> **Finish** with two adversarial critiques (trader/desktop UX, production/security/reliability) and fix what they find.

## 2. Non-negotiables

1. **Logic unchanged.** No edits to trading rules (`shared/momentum.py`, `shared/decision_desk.py`,
   `shared/trading_costs.py`), jobs, data, or API semantics. UI page logic is unchanged. Only the platform seams
   listed in §5 change. Parity is proven by audit, not asserted.
2. **PAPER ONLY.** No order placement, no MCX orders. Agents never send Telegram messages and never call
   state-changing endpoints of the live stack. Exception: new code may be exercised on **throwaway instances
   and temp storage**.
3. **Don't disturb the live stack.** It stays up throughout: data-service :8001, ui-api :8010, master-controller :8008,
   and the frontend :3000 (`ui/.next-prod`).
   - **Only the PM** restarts live ui-api, at switchover, outside the freeze windows. No agent restarts live services.
   - Never restart data-service or master-controller 07:45–09:20 or 18:30–21:15 IST.
   - Never touch `ui/.next-prod`.
   - Never pkill a running ICICI login.
4. **Test instances.** A second ui-api instance runs startup warmers that log in to Breeze, copy a 4 GB snapshot and
   warm gold. So agents test ui-api code through FastAPI `TestClient`/ASGI, or through a scratch proxy server
   (template: `scratchpad/desktop_poc_server.py`) that mounts the new module and forwards `/api` to live :8010.
   Do not start a second full ui-api.
5. **Python** is `/Users/sudheer/Desktop/jupyter_env/bin/python` only. No pip installs into it: it is shared, and
   FastAPI/Starlette/httpx/websockets/Playwright are already there. Node deps go into `ui/` or `desktop/` with
   exact pins. Rust crates are pinned in `Cargo.lock`.
6. **Secrets** are never printed or logged. Mask tokens. The ICICI `login_url` contains the API key and must never be
   logged or shown by the shell.
7. **No git commits.** Everyone writes only the files they own (§4). Changes to shared files are delivered as
   **patch blocks**, exact old/new text in `reports/desktop_app/patches/<agent>.md`, and the PM applies them.

## 3. Target architecture

```
macOS login ─► launchd
   ├─ com.suryadhana.watchdog  (RunAtLoad + every 2 min) ─► start-local.sh start <svc>
   │      data-service :8001 (DuckDB owner) · ui-api :8010 · master-controller :8008 (scheduler, Telegram)
   ├─ com.suryadhana.awake     (caffeinate -s -i)
   └─ SuryaDhana.app autostart (LaunchAgent written by the app: RunAtLoad + KeepAlive{SuccessfulExit:false}, relaunched after a crash, never after Quit)
          ├─ Rust core: health poller (5 s), tray/menu-bar, native menu, notifications, downloads,
          │             window manager (multi-window, state, restore), single instance, logs
          ├─ boot window  tauri://localhost/index.html (bundled; full local capability)
          └─ terminal windows ─► http://127.0.0.1:8010/?tab=<id>   (remote capability: minimal commands)
                                   │ same origin
ui-api :8010 ─ /api/* · SSE · WS /api/monitor/ws/monitor · /version · /build-info.json · static UI (ui/dist/current)
```

Why this shape: the 24×7 jobs (18:30 EOD, 19:30 Desk, 19:50 shadow, 02:15 backup, Telegram) must not depend on a
window. The UI stays one codebase for app, browser and the future iPad. Same origin means zero CORS work, no 30 s Next
proxy timeouts, and SSE/WS behave exactly as proven in the feasibility test.

## 4. Workstreams and file ownership (disjoint)

| Agent | Scope | Owns (writes) | Patch blocks for |
|---|---|---|---|
| **D1 web-serve** | Static export build, atomic releases, ui-api static serving, `/version`, build-info | `ui/next.config.js`, `scripts/build_ui.sh`, `ui/scripts/**` (new), `services/ui-api/static_ui.py` (new), `services/ui-api/tests/test_static_ui.py` (new) | `services/ui-api/main.py`, `.gitignore`, `start-local.sh`, `scripts/stack_watchdog.sh` |
| **D2 shell** | Tauri v2 app, Rust core, boot screen, tray, menus, IPC commands, self-test, build/install script | `desktop/**` (new), `scripts/build_desktop.sh` (new) | `.gitignore` |
| **D3 bridge+prefs** | TS platform bridge (desktop ↔ browser fallbacks), prefs server storage + sync + migration, call-site ports | `ui/lib/platform/**` (new), `ui/lib/prefs/**` (new), `services/ui-api/routers/prefs.py` (new), `services/ui-api/tests/test_prefs.py` (new); call sites `ui/lib/alerts.ts`, `ui/components/WatchMonitor.tsx`, `ui/lib/backtestExport.ts`, `ui/components/ResearchLibrary.tsx`, `ui/components/CommandBar.tsx` (only the `window.open` lines), `ui/components/terminal/index.tsx` (only the CSV download helper) | `services/ui-api/main.py` |
| **D4 desktop UX + perf** | `PlatformShell` (wraps the app: bridge init, prefs gate, title strip, connection/build banners, shortcuts), self-hosted fonts, no white flash, ChunkLoadError recovery, perf measurement and evidence-backed fixes | `ui/components/desktop/**` (new), `ui/app/layout.tsx`, `ui/app/globals.css` (append-only), `ui/app/global-error.tsx`, `ui/public/fonts/**`, `scripts/ui_perf.py` (new) | `ui/app/page.tsx`, any component perf fix |
| **T qa** | Test harness: 42-page Chromium + WebKit audit, :3000 ↔ :8010 parity, SSE/WS/stream checks, desktop E2E driver (runs `--self-test`), Rust↔UI page-list parity | `scripts/ui_audit.py`, `scripts/desktop_qa/**` (new), `tests/integration/test_desktop_*.py` (new) | — |
| **PM** (main session) | Integration, patch application, switchover, full gates, docs | `CLAUDE.md`, `docs/RUNBOOK_RESTORE.md`, `docs/IMPROVEMENT_LOG.md`, `reports/desktop_app/*.md` | — |
| **C1, C2** critics | After integration: trader/desktop UX; production/security/reliability | `reports/desktop_app/critique_*.md` | — |

Builds: until D1's `scripts/build_ui.sh` exists, D3 and D4 validate with `cd ui && npx tsc --noEmit` only, and nobody
runs `next build` into `.next` or `.next-prod`. All static builds use `scripts/build_ui.sh --out <dir>` (a scratch dir
for agents) or D1's own scratch dist dir.

## 5. Shell ↔ UI contract v1 (frozen; changes go through the PM)

**Detection.** The shell injects this at document start into every window, via an initialization script:
`window.__SURYADHANA_SHELL__ = Object.freeze({ api: 1, version: '<app semver>', build: '<git sha7>', platform: 'macos' })`.
`isDesktop()` is true iff `window.__SURYADHANA_SHELL__?.api === 1` and `window.__TAURI_INTERNALS__` exists.
In a browser, every bridge call falls back to today's browser behavior, so the browser UI stays fully functional.

**Commands** (UI → Rust, `invoke`). Each one is allowed to the remote origin `http://127.0.0.1:8010` and nothing else
(app-manifest permissions + a capability with `remote.urls`):

| Command | Args | Returns | Rules (enforced in Rust) |
|---|---|---|---|
| `shell_info` | — | `{version, build, build_id, autostart, windows, ui_api_url}` | `build_id` (additive, completeness-04): `<sha7>[-dirty]-<source hash>-<UTC time>`, also in About, the menu-bar item and `SuryaDhana --version` |
| `shell_status` | — | `ShellStatus` (below) | cached poller value, never blocks |
| `shell_notify` | `{title, body}` | `null` | title ≤ 120, body ≤ 1000 chars; throttle 20/min |
| `shell_notification_permission` | — | `'granted'\|'denied'\|'default'` | — |
| `shell_request_notification_permission` | — | same | opens System Settings › Notifications only when macOS says `denied`, at most once a minute |
| `shell_save_download` | `{filename, base64}` | `{path}` | basename only, sanitized `[A-Za-z0-9._ -]`, ≤ 120 chars, unique suffix, writes only into `~/Downloads`, ≤ 50 MB decoded |
| `shell_open_external` | `{url}` | `null` | `http`/`https` only, ≤ 2048 chars, never 127.0.0.1/localhost/file/javascript |
| `shell_new_window` | `{tab?, sym?}` | `{label}` | tab must be one of the 42 ids; `sym` (K4) an NSE symbol `^[A-Z0-9&_.-]{1,20}$`, validated in Rust; the window opens `http://127.0.0.1:8010/?tab=<tab>&sym=<SYM>` (URL-encoded); ≤ 8 windows |
| `shell_set_title` | `{title}` | `null` | ≤ 120 chars, plain text |

`ShellStatus = { at: ISO, ui_api: Svc, data_service: Svc, master_controller: Svc, icici: 'connected'|'expired'|'unknown',
ui_build: string|null, nifty: {last: number, change_pct: number}|null }`, where `Svc = {up: boolean, latency_ms: number|null}`.

**Boot-only commands** (local `tauri://localhost` boot page only; never granted to the remote origin):
`boot_status`, `stack_start`, `stack_stop` (refused inside the IST freeze windows 07:45–09:20 / 18:30–21:15),
`open_logs`, `open_terminal {tab?}`. `boot_status` service rows carry `state` (`up`|`down`|`not_responding`) and `stalled_secs`. `ui_state:'not_responding'` = ui-api holds its port but `/health` timed out on two polls in a row (hung). The boot page then shows UI-API NOT RESPONDING with how long, never 'starting' or 'down', and offers no Start. It says the watchdog restarts a hung core service after two failed runs (scripts/stack_watchdog.sh) and names `./start-local.sh restart ui-api`. Open windows are never moved, and `ShellStatus` keeps `up:false`.

**Events** (Rust → UI). Delivered with `window.dispatchEvent(new CustomEvent('suryadhana:shell', {detail}))`; Rust
evaluates a JSON-serialized literal, so the remote origin needs no event-plugin permission. The `detail` variants:
- `{type:'status', status: ShellStatus}`: on change (at most every 5 s) and a heartbeat at least every 10 s (the shell sends every 8 s, checked by a 1 s ticker; UI side ui/components/desktop/status.ts SHELL_STATUS_MAX_INTERVAL_MS). `nifty` is null while the quote is stale
- `{type:'goto', tab}`: from the Go menu, the tray or ⌘1–⌘9. The UI handles it through the existing `goToPage` / `GOTO_EVENT`
- `{type:'command-bar'}`: menu Go → GO Bar. Opens the existing command bar
- `{type:'build-changed', build}`: the served UI build differs from the page's own build
- `{type:'zoom', factor}` (K3, additive): the window's page zoom after ⌘= / ⌘− / ⌘0 (0.5–2.0, steps of 0.1, saved per window with the session); the init script also sets `window.__SURYADHANA_ZOOM__` before page scripts. Traffic lights stay at (14, 18) screen pt, so the title strip keeps its inset at 84 px / factor

**Build identity.** `scripts/build_ui.sh` sets `NEXT_PUBLIC_UI_BUILD=<release id>` at build time and writes
`build-info.json` (`{id, git_sha, built_at, files, bytes}`) into the release root. ui-api serves it at
`/build-info.json` (no-cache) and in `/version`.

**Page list.** The 42 tab ids and codes in `ui/app/page.tsx` `COMMAND_PAGES` are the source of truth. The Rust Go-menu
copy is checked against it by a T test. ⌘1–⌘9 map to the same pages as the UI's existing ALT+1…9.

## 6. Acceptance criteria (Definition of Done)

| # | Criterion | Evidence |
|---|---|---|
| AC-1 | `scripts/build_ui.sh` builds a static release into `ui/dist/releases/<id>/` and swaps `ui/dist/current` atomically. It keeps 3 releases, carries forward old `_next/static` chunks, and supports `--rollback` and `--out <dir>`. The output contains no route handlers. `next dev` and the `.next-prod` path are unaffected | D1 tests + a run log |
| AC-2 | ui-api serves `/` (no-cache), hashed assets (immutable, gzip when accepted), `/build-info.json` and `/version`. Unknown `/api/*` paths stay JSON 404s with the error envelope. A missing build gives a clear 503 page while the API keeps working. SSE is unbuffered (first byte < 2 s) and the WS works same-origin. A release swap is live without restart | `test_static_ui.py` + harness |
| AC-3 | All 42 pages at :8010 show **0 console errors and 0 failed API requests in Chromium and WebKit**, and match the :3000 build (same API calls, same visible structure; live values excepted) | T parity report |
| AC-4 | `scripts/build_desktop.sh` builds and ad-hoc signs `SuryaDhana.app` (< 25 MB), installs it, and passes `--self-test` | build log + self-test JSON |
| AC-5 | **Starts at login**: autostart is enabled on first run, the LaunchAgent plist exists and loads, and there is a menu toggle | plist + `launchctl print` + self-test |
| AC-6 | Boot screen paints in < 500 ms and shows each service's state. It enters the terminal automatically when ui-api and the build are up; when the stack is down it is actionable (Start stack, Logs, Retry) and continues on its own | self-test + drill |
| AC-7 | Window: black, no white flash, overlay title strip with traffic-light inset and drag region. Geometry is remembered, ⌘N multi-window works, open windows are restored on relaunch, and the app is single instance | self-test + C1 |
| AC-8 | Native notifications, downloads to ~/Downloads, and external links in the default browser all work. Navigation off the allowlist is blocked. ⌘C/⌘V/⌘A work in inputs. Closing the window hides to the menu bar; ⌘Q quits | self-test + C1 |
| AC-9 | Menu-bar item: NIFTY title, 3-service health, ICICI state and Desk NAV. Actions: Open, New window, Go, Start stack, Stop stack (guarded), Logs, Launch at login, Quit | self-test + C1 |
| AC-10 | Resilience: when ui-api restarts mid-session, a banner appears and the session recovers without a reload. A release swap shows a "new build" prompt and never breaks an open window. The app reconnects after sleep/wake. A stack that is down at launch is handled | drills (PM) |
| AC-11 | Security: least-privilege capabilities (remote = the 9 commands only), Rust-side validation with tests, strict CSP on the boot page, a navigation allowlist, no secrets in the bundle or logs, and a port-squatting threat analysis | C2 + Rust tests |
| AC-12 | Prefs: server-side storage with LWW per key, size caps and key validation. Hydration runs before first render with a timeout fallback, writes go through, and there is a one-time migration from the browser origin. The watchlist and pins survive browser ↔ app | `test_prefs.py` + E2E |
| AC-13 | Performance (measured, reported): app start to boot paint < 0.5 s; boot to interactive terminal < 2.5 s (warm stack); tab switch p95 < 400 ms; one idle window < 500 MB total RSS and < 3 % CPU; first-load JS ≤ 300 kB gz | `ui_perf.py` + self-test |
| AC-14 | All 5 suites, tsc, `cargo test` and the new suites are green. The 42-page Chromium + WebKit audits and the desktop E2E are green | PM gate |
| AC-15 | Ops: CORE = 3 services; the watchdog and start-local.sh are updated; dev mode still works; the docs (RUNBOOK, CLAUDE.md, IMPROVEMENT_LOG, desktop/README) are current | PM |

## 7. Integration and switchover (PM)

1. Collect the builders' outputs and apply the patch blocks with uniqueness-asserted scripted edits.
2. Run the gates: the 5 suites, tsc, `cargo test`, and the new tests.
3. Build the first UI release with `scripts/build_ui.sh`.
4. Restart live ui-api, outside the freeze windows, so that it serves the UI at :8010.
5. Run T's 42-page Chromium + WebKit audit and the :3000 parity check.
6. Only if parity is green, apply the ops patch (frontend leaves CORE) and stop :3000. `./start-local.sh start frontend`
   brings it back at any time.
7. Build and install SuryaDhana.app, run the self-test, and enable autostart.
8. Run the drills: ui-api restart mid-session, release swap, a stack-down launch.
9. Run critics C1 and C2, then a fix round, then re-run the gates, then report.

## 8. Known risks and decisions

| Risk | Decision |
|---|---|
| WKWebView has no Web Notification API / `<a download>` blob handling | Route both through the bridge and shell commands. The browser path is unchanged |
| `target=_blank` / `window.open` in 11 places | A capture-phase global link interceptor in the bridge, plus Rust `on_navigation` / new-window handlers. No per-file edits except CommandBar |
| localStorage is per origin, so the app would start empty | Server prefs + one-time migration (the old :3000 build carries the sync code until switchover) |
| Port squatting: any local process (even a same-user sandboxed app) could bind :8010 while ui-api is down; a window on that origin would show its pages (fake credential forms, fake notifications) with the 9 remote commands | Guard (desktop/src-tauri/src/trust.rs, wave 2): before any window gets the terminal origin, the shell lists the port's LISTEN sockets in-process from kernel facts (libproc). Nothing on disk is read or canonicalized and nothing under ~/Desktop is touched; there is a hard 5 s timeout. Every listener must be this user's process whose executable is a CPython in a Homebrew keg (any python@3.N patch version, so `brew upgrade` never makes the running ui-api look foreign) or a python.org framework. A definitive Foreign verdict keeps new windows on the boot page (it names the pid and executable) and pulls open terminal windows back. An Unknown verdict (probe failed or timed out) never evicts or holds a window back and is retried. Residual risk: a same-user process running Homebrew or python.org CPython passes, including a sandboxed app that execs Homebrew python as a child; closing that needs a shared secret between ui-api and the shell. Downloads are extension-limited and quarantined either way (C2-security-04/05) |
| TCC: the stack's Python lives in ~/Desktop | The app never runs Python itself. Start stack clears the paused markers and kickstarts the watchdog LaunchAgent without -k (a run in progress is left alone); an unloaded agent is loaded with launchctl bootstrap; without the agent, Start refuses and names scripts/install_launch_agents.sh install |
| Screen recording is not granted to this shell (`screencapture` fails) | Visual checks use Playwright WebKit (the same engine); native chrome is verified by `--self-test` introspection |
| Unsigned build | Ad-hoc signing for this Mac; Developer ID signing and notarization is an owner action (paid account) |
