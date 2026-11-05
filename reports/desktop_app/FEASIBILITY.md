# Desktop app instead of the web app — feasibility, effort, pros & cons (24 Oct 2026)

**Question (owner):** can SuryaDhana run as a desktop application instead of a web application, given the
web app's many dependencies? Check feasibility first, then effort, then pros and cons.

## Verdict
**Yes, it is possible, and the evidence says the risk is low.** The terminal UI is already a client-side
application. It needs the Node.js/Next.js server for exactly one thing: 6 small stream proxies. Measured
on 24 Oct, without touching the live app:

| Test | Result |
|---|---|
| Static export of the UI (`output: 'export'`, scratch copy) | First attempt failed **only** on the 6 `app/api/*/stream` proxies. With them removed: **all routes static, 3.4 MB, 60 JS files**, build 8 s |
| Static UI served from one local port, `/api` to the live ui-api (Chrome engine = Electron) | 8 key pages: **0 console errors**. The one aborted request was the SYS log stream closing on navigation, which is normal |
| Same in **WebKit** (Safari engine = Tauri / macOS app window) | 8/8 pages: **0 console errors, 0 failed requests, no crashes** (BRIEF, DESK, MKT, CHRT, WATCH, OSTR, MCXG, SYS incl. live stream + WebSocket) |
| ui-api already serves everything the UI calls | `/api/*`, the monitor WebSocket `/api/monitor/ws/monitor`, the telemetry stream: same paths, so no CORS changes are needed if ui-api serves the UI |
| Toolchain on this Mac | Rust 1.94 + Cargo (Tauri) ✓ · Node 25 (Electron) ✓ · Xcode CLT ✓ · M4 Pro |

## Read this first: what a desktop app removes, and what it doesn't
The dependencies you feel are mostly **not the web part**:

| Removed by going desktop (web layer) | Stays whatever the UI is (the product itself) |
|---|---|
| Node.js **at run time**, `next start`, port 3000 | Python 3.13 + 43 pinned packages (the shared `jupyter_env`, 2.3 GB) |
| `ui/node_modules` (400 MB) and `.next-prod` (1.5 GB) at run time; Node is still needed to *build* the UI | data-service (DuckDB owner), ui-api, master-controller (scheduler, Telegram, EOD jobs) |
| The browser tab/URL; browser permission problems on the Mac | 36 GB of market data (4.4 GB DuckDB), backups |
| One of the 4 processes that can crash | Playwright + Chrome for the ICICI auto-login; Breeze; Redis (optional) |

Two consequences:
1. **The backend must keep running when the app window is closed.** The 18:30 EOD pipeline, the 19:30 Desk,
   the 19:50 shadow, the 02:15 backup and Telegram are 24×7 jobs. The sound design is how professional terminals work (IBKR's
   Trader Workstation has a separate always-on gateway): the services stay as background services (the launchd agents
   installed on 19 Oct), and the desktop app is the window plus a control panel.
2. **A Mac desktop app does nothing for the iPad.** That problem was network separation (the iPad
   was on a different segment). The iPad still needs the web UI over the network (Tailscale) or a native iPad app (much
   larger effort).

## Options, effort, pros & cons
Effort = focused engineering days for one experienced developer, including tests and the 42-page audit.

### Option 0 — install the existing web app as an app (Safari "Add to Dock" / Chrome "Install") · ~1 hour
- ➕ Zero code; Dock icon; its own window without browser chrome; works today
- ➖ Still the full web stack (Node, port 3000); only cosmetic

### Option 1 — ui-api serves the static UI; Node.js leaves production · **1–2 days** · RECOMMENDED FIRST
Build the UI with static export (a build script moves the 6 dev-only stream proxies aside, as in the test), and mount the files in ui-api
(`StaticFiles` with index fallback). The terminal becomes `http://127.0.0.1:8010`. `start-local.sh` and the watchdog drop the
frontend process; `next dev` stays available for UI editing.
- ➕ Removes the whole Node runtime from production: 4 processes → 3, no port 3000, 1.9 GB of runtime files gone
- ➕ One origin for UI + API, so no CORS and no proxy timeouts (the old 30 s Next proxy 500s disappear for good)
- ➕ Works in every browser, in an app window (Option 2), and over Tailscale for the iPad
- ➕ Tiny and reversible; proven above in Chrome **and** WebKit
- ➖ UI changes now need a rebuild (8 s) and a ui-api reload instead of hot reload (dev mode keeps hot reload)
- ➖ The 6 stream proxies stay in the repo for dev mode, so there are two ways streams are served (documented, tested)

### Option 2 — Tauri desktop app (native macOS window + menu-bar control panel) · **3–5 days** on top of Option 1
A ~10–15 MB `.app` using macOS's own WebKit view, pointed at the local ui-api. A menu-bar icon shows service
health, ICICI session state and the Desk NAV, with Start/Stop stack, Open terminal and "Send /login" actions. It also adds
launch at login, native notifications for price alerts and EOD failures, a native Save dialog for CSV exports, and
external links (TradingView, NSE filings) opening in Safari.
- ➕ A real desktop app: Dock icon, ⌘-Tab, its own window, native notifications, starts at login
- ➕ Very small and light (the system WebKit, no bundled browser); the engine is verified 8/8 above
- ➕ Rust toolchain already installed; the backend is unchanged
- ➖ Porting chores found in the code: notifications (2 files), file downloads (3), `window.open`/`target=_blank`
  links (11), all small, plus **localStorage migration**: your watchlist, pins and layout live in the browser's
  localStorage (19 files use it). A new app origin starts empty, so it needs a one-time export/import or,
  better, moving those settings to ui-api storage
- ➖ Rust/Tauri knowledge for future changes to the shell (the shell is small; the UI stays React)
- ➖ Unsigned personal build: macOS asks once ("open anyway"); proper signing needs an Apple Developer account ($99/yr)

### Option 3 — fully self-contained app (Python + all services inside the `.app`) · **2–4 weeks**
Embed a relocatable Python with the 43 pinned packages, bundle Playwright Chromium, run the 3 services as app-managed
background helpers, move the data to `~/Library/Application Support/SuryaDhana`, and add code signing,
notarization and an updater.
- ➕ One-file install on another Mac, so you can give it to someone or move machines
- ➕ No dependence on `~/Desktop/jupyter_env`, which also ends the macOS Desktop-folder permission problem (watchdog R10)
- ➖ Big: 0.8–1.2 GB app; every package upgrade needs an app rebuild; repo-relative paths across
  scripts must be refactored; 24×7 helpers still need launchd registration
- ➖ The 36 GB data folder can't live in the app, so it is still a separate install/restore step
- ➖ Only worth it if the system must run on more than one Mac or for other people

### Option 4 — Electron instead of Tauri · 2–4 days (shell), 2–4 weeks (self-contained)
- ➕ JavaScript only (no Rust); the most mature ecosystem for apps that manage background helpers; verified 8/8 in Chromium
- ➖ Bundles its own Chromium: a 150–250 MB app and 300–500 MB more RAM than Tauri. That is the dependency weight you
  are trying to shed

### Option 5 — native rewrite (SwiftUI or PySide6) · 3–6 months
- ➕ The most "native" feel
- ➖ Re-implements 42 pages, charting and the terminal kit, throwing away working, tested React. Not recommended

## Recommendation
1. **Do Option 1 now (1–2 days).** It removes the biggest piece of web-only weight (the Node runtime) from production and
   makes everything simpler and more robust. It also helps the iPad story via Tailscale.
2. **Then Option 2, Tauri (3–5 days)** if you want a proper app window, menu-bar control and native notifications.
   Keep the backend as the launchd services you already have. Move watchlist/settings off localStorage at the same time.
3. **Option 3 only if** SuryaDhana must run on another Mac or for other users.
4. For the **iPad**, do Tailscale (separate, ~1 hour) whichever option you pick.

## Evidence trail
Scratch copies only (live app untouched, stayed 200 throughout): static export test `scratchpad/ui_export_test/`,
proof server `scratchpad/desktop_poc_server.py` (static UI + `/api`/SSE/WebSocket forwarding),
Chromium audit `scratchpad/poc_audit/audit.json`, WebKit sweep (8/8 clean). Code facts:
`ui/next.config.js` (rewrites only), `ui/app/page.tsx` ('use client'), 6 × `ui/app/api/*/stream/route.ts`,
`ui/lib/api.ts` (relative base), `ui/lib/wsManager.ts` (origin-relative WS), `services/ui-api/routers/monitor.py:108`
(WS), `services/ui-api/routers/telemetry.py:99` (stream), CORS `services/ui-api/main.py:120`.
