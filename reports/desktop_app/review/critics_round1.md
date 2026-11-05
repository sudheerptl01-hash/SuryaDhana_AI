# C2-security — BLOCK

The Tauri shell is well hardened. The remote capability is exactly the 9 commands plus 2 window permissions. The ACL resolves on the IPC request's frame Origin, so it is frame-aware, and require_ui/require_boot re-check it. The boot page has a strict CSP and renders only via textContent. The navigation guard has a one-shot boot permit, and downloads use O_EXCL with a 50 MB cap checked before decoding. static_ui.py resisted every traversal GET I tried. My scan found no secret values in the .app bundle, the UI release or any log. Three problems block a production-grade label, and they all sit behind the shell:
(1) ui-api checks neither the Host header nor Origin on state-changing routes. That allows DNS rebinding from any website and plain cross-site POSTs. I verified that a spoofed Host gets 200. In a replica with the same middleware and handler shapes, a text/plain cross-site POST ran desk/reenable (which clears the HARD −20% drawdown stop), data/provider/configure and prefs/import.
(2) Right now the whole unauthenticated API is reachable from the LAN through the Next server on *:3000. I verified this with GETs to 192.168.31.62:3000. The pending pm_lan.py would reopen the same exposure on :8010 with only a shell comment as the warning.
(3) GET /api/execution/status reports the legacy engine as mode LIVE, state ACTIVE, while the product says PAPER ONLY. So any of those paths can reach breeze.place_order with the owner's real ICICI session (code path read, never exercised).
Also important: the port-squatting analysis in desktop/README.md understates the risk. A squatter gets full UI spoofing inside a trusted app window, plus a primitive that writes unquarantined files with any safe-charset extension into ~/Downloads. The shell accepts data: downloads from any frame, including the unsandboxed TradingView iframe. ui-api still sends credentialed CORS to http://localhost:3000 and :3001. master-controller allows CORS from '*'.
The fixes are small: TrustedHost and Origin middleware, a LIVE opt-in guard, a LAN token, and download quarantine with an extension allowlist. With those it becomes SHIP-WITH-FIXES.

## C2-security-01 [blocker] ui-api has no Host-header validation and no Origin/CSRF check; any website can drive state-changing endpoints
- verify: ['REAL->blocker', 'REAL->blocker']
- file: services/ui-api/main.py:121
- area: ui-api HTTP surface (DNS rebinding + CSRF) · reproduced: True
- evidence: main.py:121-127 installs only CORSMiddleware(allow_origins=[localhost:3000, localhost:3001]). There is no TrustedHostMiddleware and no Origin check anywhere. Live GETs: `curl -H 'Host: rebind.attacker.example' http://127.0.0.1:8010/health` returned 200, and the same Host on / returned 200 text/html. :8001 and :8008 also answered 200 to a spoofed Host. Replica in scratch (crit/C2-security/csrf_sim.py, same CORS config and handler shapes): text/plain POSTs with Origin https://evil.example and no preflight EXECUTED /api/desk/reenable (no body, desk.py:105), /api/data/provider/configure (`await request.json()` ignores Content-Type, data_proxy.py:68-70) and /api/prefs/import (`_read_json` ignores Content-Type, prefs.py:453-470, 543). Pydantic-body routes returned 422. After DNS rebinding the page is same-origin, so JSON routes open up too: /api/execution/order (execution.py:172), /api/execution/mode (89), and /api/positions/credentials (positions.py:595, which writes ICICI_API_KEY/SECRET/CLIENT_ID/PASSWORD into .env via persist_env_updates). GET /api/positions/connection-status (login_url carries the API key) also becomes readable. data-service has the same class of no-body POSTs, e.g. POST /jobs/build-ml-dataset (data-service/main.py:541), the heavy build involved in the 15 Oct EOD OOM incident.
- failure: The owner opens any web page in Safari, which has no Private/Local Network Access protection. The page auto-submits a hidden <form method=POST action=http://127.0.0.1:8010/api/desk/reenable>. That clears the HARD max-drawdown emergency stop and resets the peak, defeating 'manual re-enable'. Alternatively the page rebinds its hostname to 127.0.0.1 (no Host check), reads connection-status, then POSTs JSON to /api/positions/credentials to swap the ICICI API key/secret in .env, or POSTs to /api/execution/order. Because of finding 03 that order goes to breeze.place_order. A POST to :8001/jobs/build-ml-dataset during the 18:30–21:15 EOD window can repeat the OOM incident.
- fix: Add two outermost middlewares to ui-api, and the same to data-service and master-controller. (a) starlette TrustedHostMiddleware(allowed_hosts=['127.0.0.1','localhost','testserver'] plus the explicit LAN host/IP only when LAN mode is on). (b) An unsafe-method guard: for POST/PUT/PATCH/DELETE, reject with 403 when an Origin header is present and not in {http://127.0.0.1:8010, http://localhost:8010, plus http://localhost:3000 only while the dev frontend runs}, or when Sec-Fetch-Site is 'cross-site'. Allow requests with no Origin header (httpx from master-controller, curl, scripts). Also make /api/data/provider/configure and /api/prefs/import require Content-Type: application/json. Add a test that posts text/plain with a foreign Origin to /api/desk/reenable and expects 403.

## C2-security-02 [blocker] The full unauthenticated API is reachable from the LAN today via Next on *:3000, and the pending UI_API_HOST=0.0.0.0 opt-in reopens it on :8010 with no token
- verify: ['REAL->major', 'REAL->blocker']
- file: start-local.sh:250
- area: LAN exposure (current :3000 + pending pm_lan.py) · reproduced: True
- evidence: lsof: `node 2970 ... TCP *:3000 (LISTEN)`. ui/next.config rewrites /api/:path* to ui-api (lines 14-18), and start-local.sh:250/252 starts `next start -p 3000` / `next dev -p 3000` without -H. From the Mac's LAN address: `curl http://192.168.31.62:3000/api/desk/status` returned 200 and /api/prefs returned 200. /api/execution/status returned {mode: LIVE, state: ACTIVE, available: true}. /api/positions/connection-status returned HTTP 200; I discarded the body unread because it carries the login_url with the API key. Next rewrites proxy every method, so POSTs go through too. pm_lan.py:19-29 makes 0.0.0.0 an opt-in whose only safeguard is a shell comment ('The terminal has no login: only on a trusted network') and a yellow echo line in print_urls (pm_lan.py:52-54) that the launchd watchdog never shows. When on, /docs (Swagger 'Try it out'), every POST route and the ICICI credential and session-token entry forms all travel in cleartext over Wi-Fi.
- failure: Any device on the same Wi-Fi (guest, a compromised IoT device, a café or hotel network once the owner enables UI_API_HOST=0.0.0.0 for the iPad) sends `POST http://192.168.31.62:3000/api/execution/order {symbol, side, quantity, price}`. Or it POSTs /api/positions/credentials to replace the broker key and secret, or /api/desk/reenable. No authentication is required. Today this works through :3000 until the switchover stops that process.
- fix: At switchover (D1 P12), stop the running :3000 process. Make the optional frontend bind loopback: `next start -H 127.0.0.1 -p 3000` and `next dev -H 127.0.0.1 -p 3000` in start-local.sh:250/252 and ui/package.json. Do not apply pm_lan.py as written. LAN mode should require a pairing token: middleware that rejects any non-loopback peer (request.client.host) without a valid `sd_lan` cookie or bearer token, set once from a QR/one-time URL that the desktop app shows. Non-loopback peers should also be read-only by default (403 on unsafe methods unless UI_API_LAN_WRITE=1). TrustedHost should list the LAN IP. Show a persistent 'LAN EXPOSED' chip in TitleStrip and the tray when /version reports a non-loopback bind. Prefer documenting Tailscale over 0.0.0.0.

## C2-security-03 [blocker] The legacy execution engine served by ui-api is persisted in LIVE/ACTIVE mode while the product says PAPER ONLY, so every unauthenticated path to /api/execution/order is a real-money path
- verify: ['REAL->blocker', 'REAL->blocker']
- file: services/ui-api/routers/execution.py:172
- area: Trading posture vs. exposed execution engine · reproduced: True
- evidence: `curl http://127.0.0.1:8010/api/execution/status` returned "mode":"LIVE","state":"ACTIVE" (same from the LAN via :3000). The mode is restored from the engine's SQLite state (services/execution-service/live_execution.py:256-258); no EXECUTION_MODE key exists in .env (key-presence check only). place_manual_order (execution.py:172-190) → engine.place_order → _submit_order_internal → LIVE branch → _breeze_place_order (live_execution.py:365-395) calls breeze.place_order(exchange_code='NSE', product='cash', order_type='market') with ICICI_API_KEY/SECRET/SESSION_TOKEN from the ui-api environment. The only gates are the price guard and state==ACTIVE. The boot page and CLAUDE.md both say 'PAPER ONLY'. I did NOT POST, so a real fill is inferred from code, not exercised.
- failure: On a trading day after the 08:00 ICICI auto-login, any request that reaches POST /api/execution/order places a real NSE market order on the owner's account. That request can come from a DNS-rebinding page (finding 01), a LAN client via :3000 today or via UI_API_HOST later (finding 02), a localhost:3000/3001 dev page (finding 06), or a mistaken UI click in LivePortfolio. This contradicts the owner-approved paper-only posture.
- fix: This is not a trading-rule change: enforce the documented posture. Have the owner confirm the intended mode, reset the engine to PAPER, and make ui-api refuse ExecutionMode.LIVE (and refuse to restore LIVE from SQLite at startup) unless an explicit opt-in env flag is set, e.g. EXECUTION_LIVE_ALLOWED=1, which is absent today. Surface the engine mode in ShellStatus/TitleStrip so the 'PAPER ONLY' chip can never contradict the backend. Combine with the Origin/Host guard from finding 01.

## C2-security-04 [major] The shell trusts whatever answers 127.0.0.1:8010, and the README's squatting analysis understates what a squatter gets
- verify: ['REAL->minor']
- file: desktop/src-tauri/src/health.rs:439
- area: Port squatting / ui-api identity · reproduced: False
- evidence: ui_ready is just `GET /health` 200 plus `GET /` returning 200 text/html (health.rs:439-447). No server identity or listener-owner check exists anywhere in desktop/src-tauri/src (grep). The navigator auto-navigates every waiting window to the terminal as soon as ui_ready is true (windows.rs navigator_tick). desktop/README.md:140 and PLAN.md §8 claim a squatter gets 'No process control, no arbitrary file access ... no secrets'. In fact the squatter supplies the entire UI inside a trusted SuryaDhana window. It can show a pixel-perfect ICICI credential or session-token form, since the real terminal has one. It can call shell_save_download to write attacker bytes under any [A-Za-z0-9._ -] name and extension into ~/Downloads, unquarantined (finding 05), raise native notifications attributed to SuryaDhana, and open browser URLs. It also keeps :8010 so the watchdog cannot restart ui-api (EADDRINUSE). Tray Desk NAV and NIFTY values come from the squatter. A realistic squatter is any same-uid sandboxed app with the network.server entitlement: it cannot read the repo, but through the shell it escapes its sandbox's quarantine-on-write.
- failure: ui-api crashes or restarts (the watchdog takes up to ~2 min). A sandboxed helper app binds 127.0.0.1:8010 first. The SuryaDhana window on the boot page auto-enters the fake terminal. It shows 'ICICI session expired: re-enter API secret / password' and posts the native notification 'ICICI session expired'. The owner types credentials into a window that looks exactly like their terminal. Or the fake terminal saves 'Q3_results.zip' (an ad-hoc-signed .app inside) to ~/Downloads with a 'Download complete' notification. Gatekeeper never assesses it because there is no quarantine xattr.
- fix: Verify the server before granting it a window. Simplest: before navigating, resolve the PID listening on the ui port (libproc proc_pidfdinfo, or `lsof -nP -iTCP:<port> -sTCP:LISTEN -Fpu`) and require uid == getuid() and an executable under the configured Python/venv. Stronger: a handshake secret. The shell creates ~/Library/Application Support/ai.suryadhana.terminal/shell.key (0600), ui-api reads it, and the shell calls GET /version?nonce=N and requires an HMAC(key, N) header before ui_ready. A sandboxed squatter cannot read the key. Correct the README/PLAN squatting text, and apply finding 05.

## C2-security-05 [major] Saved files get no quarantine xattr and no extension allowlist, and data: downloads are accepted from any frame, including the unsandboxed TradingView iframe
- verify: ['REAL->minor']
- file: desktop/src-tauri/src/windows.rs:491
- area: Downloads (shell_save_download + on_download) · reproduced: True
- evidence: commands.rs:146-187 writes with std::fs and sets no xattr. A grep for quarantine/xattr/LSFileQuarantine in src/ and tauri.conf.json finds nothing. The bundle Info.plist (plutil -p) has no LSFileQuarantineEnabled. A scratch file written by a normal process gets only com.apple.provenance, not com.apple.quarantine. policy::sanitize_filename (policy.rs:346) keeps any extension: '.terminal', '.zip', '.pkg', '.webloc', '.fileloc' and '.command' all survive. on_download allows `url.scheme() == "data"` with no origin condition (windows.rs:489-495). wry routes `<a download>` (shouldPerformDownload) straight to the download handler, bypassing on_navigation (wry-0.57.1/src/wkwebview/navigation.rs:82-88). The TradingView iframe has no sandbox attribute (ui/components/news/NewsChart.tsx:129-136). The UI itself never uses data: downloads (grep). A 'Download complete' native notification follows each save (windows.rs Finished branch).
- failure: A compromised TradingView widget script, an XSS in the terminal origin, or a squatter (finding 04) triggers `<a download='NIFTY_levels.zip' href='data:application/zip;base64,...'>.click()`. SuryaDhana writes ~/Downloads/NIFTY_levels.zip with no quarantine and shows 'Download complete'. The owner double-clicks it, Archive Utility extracts an ad-hoc-signed .app without quarantine, and the app runs with no Gatekeeper prompt on this arm64 Mac.
- fix: (1) Remove `data:` from the on_download allowlist. Only same-origin and ui-origin blob: are needed. (2) Allowlist extensions in both paths (csv, json, txt, md, pdf, png, svg, xlsx), otherwise append '.txt'. (3) Tag every file the shell writes with com.apple.quarantine (setxattr, value '0083;<hex epoch>;SuryaDhana;'), or set LSFileQuarantineEnabled=true in Info.plist via tauri.conf bundle.macOS.infoPlist. (4) Add sandbox='allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox' to the TradingView iframe: no allow-downloads, no allow-top-navigation. (5) Use symlink_metadata instead of exists() in unique_name so dangling symlinks count as taken.

## C2-security-06 [major] ui-api still gives credentialed CORS to http://localhost:3000 and :3001, which the same-origin UI no longer needs
- verify: ['REAL->major']
- file: services/ui-api/main.py:123
- area: ui-api CORS · reproduced: True
- evidence: A live GET with `Origin: http://localhost:3000` returned `access-control-allow-origin: http://localhost:3000` and `access-control-allow-credentials: true`. :3001 behaves the same on /api/desk/status. allow_methods and allow_headers are '*', so JSON POSTs pass preflight. The terminal is now same-origin on :8010, and the optional dev UI on :3000 calls relative /api via Next rewrites and server route handlers (ui/lib/api.ts baseURL '', app/api/*/route.ts). No browser code needs cross-origin access to :8010 (grep).
- failure: The owner runs another project's dev server on localhost:3000. ~/CLAUDE.md lists job_hunter's `npm run dev` on :3000; Grafana and CRA also default to :3000/:3001. Any script on that page, e.g. a compromised npm dependency or an XSS there, can fetch http://127.0.0.1:8010/api/positions/connection-status with credentials and read the ICICI login_url/API key. It can also POST JSON to /api/positions/credentials or /api/execution/order.
- fix: Remove CORSMiddleware from ui-api, since same-origin needs none and the dev UI proxies server-side. If something truly needs it, enable it only when UI_DEV_CORS=1, never by default, and without allow_credentials.

## C2-security-07 [major] master-controller allows CORS from any origin ('*', all methods, all headers): any website can toggle autopilot, trigger the ICICI login flow and read scheduler logs
- verify: ['REAL->major']
- file: scripts/master_controller.py:2165
- area: master-controller CORS · reproduced: True
- evidence: master_controller.py:2165-2170 sets `allow_origins=['*'], allow_methods=['*'], allow_headers=['*']`. I sent one OPTIONS preflight to :8008/health with Origin https://evil.example; the CORS middleware answered it without running any route. The response returned `access-control-allow-origin: *` and allow-methods 'DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT'. Write routes: POST /api/scheduler/autopilot (JSON, line 2237; AUTOPILOT gates the legacy inference, EOD square-off and the 1 h overnight RL retrain subprocess, lines 448/505/534) and POST /api/scheduler/icici-refresh (no body, line 2250; runs the unattended ICICI login, which sends 'ICICI login needs you' Telegram alerts on failure). GET /api/scheduler/logs is readable cross-origin; the current tail holds no secret-like strings (pattern count 0).
- failure: A web page runs `fetch('http://127.0.0.1:8008/api/scheduler/autopilot',{method:'POST',headers:{'content-type':'application/json'},body:'{"enabled":true}'})`. The preflight passes and autopilot turns ON, which the owner retired because it 'loses ~45–50%/yr'. It also triggers nightly RL retraining and alert noise. A loop of POST /api/scheduler/icici-refresh on a weekend, when the session is expired, repeatedly runs the headless broker login with the owner's credentials, risking an ICICI lockout and Telegram alert floods.
- fix: Remove CORSMiddleware from master-controller; its only browser client is ui-api's server-side proxy. Add the same TrustedHost and Origin guard as finding 01.

## C2-security-08 [minor] POST /api/prefs/import works as a cross-site simple request and accepts any key matching the regex, so a web page can fill the 500-key / 5 MB quota
- verify: not verified (minor/nit)
- file: services/ui-api/routers/prefs.py:543
- area: Prefs store abuse · reproduced: True
- evidence: _read_json (prefs.py:453-470) parses the body whatever its Content-Type, so a text/plain no-cors POST runs; in the replica it executed. import_items accepts any key matching ^[A-Za-z0-9._:-]{1,128}$ (prefs.py:344-347), not only the 12 SYNC_KEYS (ui/lib/prefs/keys.ts). The quota is global (MAX_KEYS=500, MAX_TOTAL_BYTES=5 MB, prefs.py:73-74), and GET /api/prefs returns every row on each hydration.
- failure: A visited page sends about 20 POSTs, each importing 25 random keys of 200 KB, which fills 500 keys and 5 MB. After that, every new legitimate key the owner's UI writes gets 413 'too many preference keys'. Each app launch also downloads 5 MB of junk before first render and may hit the hydration timeout, so settings silently stop syncing.
- fix: Enforce a server-side key allowlist that mirrors SYNC_KEYS, or a prefix allowlist; require Content-Type application/json on PUT and import; and rely on the Origin guard from finding 01.

## C2-security-09 [minor] Terminal HTML is served with no Content-Security-Policy, although this origin holds the remote IPC capability
- verify: not verified (minor/nit)
- file: services/ui-api/static_ui.py:531
- area: Terminal origin hardening (CSP) · reproduced: True
- evidence: Live `curl -D - http://127.0.0.1:8010/` shows cache-control, etag, nosniff, vary and x-frame-options SAMEORIGIN, but no Content-Security-Policy, Referrer-Policy or frame-ancestors. index.html has no CSP meta. static_ui.py:526-531 adds only nosniff and XFO. The release has no third-party scripts (grep), so a strict policy is feasible.
- failure: Any future injection in the terminal origin, e.g. an unescaped news or NSE string in a non-React sink or a malicious dependency, runs with __TAURI_INTERNALS__ and can call shell_save_download, shell_open_external and shell_notify without restriction. A CSP would contain it.
- fix: Have static_ui send a CSP on .html: default-src 'self'; script-src 'self' plus sha256 hashes of Next's inline bootstrap scripts (computed by build_ui.sh into build-info.json); style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' ws://127.0.0.1:8010 ws://localhost:8010; frame-src https://s.tradingview.com; object-src 'none'; base-uri 'none'; frame-ancestors 'self'. Add Referrer-Policy: no-referrer.

## C2-security-10 [minor] frame_hosts allow plain http:// and main-frame commits; the TradingView frame can take over the top window until the post-commit bounce
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/policy.rs:206
- area: Navigation policy for embedded frames · reproduced: False
- evidence: navigation_decision allows any http or https URL whose host matches a frame_hosts suffix, for every frame including the main frame (policy.rs:197-211). Main-frame loads are only bounced after commit in on_page_load Started (windows.rs:536-551). The iframe is unsandboxed (NewsChart.tsx:129-136), so a framed page with user activation can set top.location to a *.tradingview.com page.
- failure: A compromised or MITM-injected TradingView frame navigates top to http://…tradingview.com/… (cleartext allowed). For a moment that page is the main document of a SuryaDhana window before the bounce. It has no IPC rights (the ACL is origin-scoped), but it can flash a convincing phishing page and repeatedly loop open_external tabs.
- fix: Allow https only for frame_hosts. Sandbox the iframe as in finding 05, without allow-top-navigation, so top navigation is impossible and the bounce becomes a backstop.

## C2-security-11 [minor] shell_save_download and shell_open_external have no rate limit (only shell_notify does)
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/commands.rs:147
- area: IPC rate limits · reproduced: False
- evidence: commands.rs:146-197: the only limiter is ui_notify_limiter (20/min) inside shell_notify. shell_save_download accepts up to 50 MB per call with unlimited calls and unique ' (n)' suffixes up to 9,999 names per stem. shell_open_external opens a browser tab on every call.
- failure: A compromised terminal origin or squatter loops shell_save_download with 50 MB payloads and fills the disk in minutes. DuckDB and SQLite writes then fail and the EOD pipeline breaks. Or it loops shell_open_external and floods the default browser with phishing tabs.
- fix: Add per-window limiters: save_download at 10/min and 200 MB/hour, and stop when free disk is under 5 GB; open_external at 10/min. Log refusals.

## C2-security-12 [minor] pm_lan.py accepts a specific IPv4 bind that breaks every loopback consumer, validates no octets, and prints the wrong interface
- verify: not verified (minor/nit)
- file: /private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/a24906e4-7b64-46ba-b24b-14c536f43922/scratchpad/pm/pm_lan.py:25
- area: Pending block pm_lan.py (robustness) · reproduced: True
- evidence: Its case statement (lines 25-29) lets any [0-9.] string through, e.g. 192.168.31.62 (the error hint even suggests 'an IPv4 address') or 999.1.1.1. A specific-IP bind leaves 127.0.0.1:8010 closed. But the watchdog probes http://localhost:8010/health (scripts/stack_watchdog.sh:51,56), master-controller uses UI_API_URL=http://localhost:8010, and the desktop app uses http://127.0.0.1:8010. The LAN echo (line 53) uses `ipconfig getifaddr en0`, but this Mac's active interface is en1 (192.168.31.62), so it would print '<this-mac-ip>'.
- failure: The owner sets UI_API_HOST=192.168.31.62 to limit exposure to Wi-Fi. ui-api binds only that IP. The watchdog sees it as down and kill/restarts it every cycle (with Telegram and dead-man noise), the desktop app sits on 'reconnecting', and scheduled jobs that call ui-api fail. Typo values never bind, so ui-api never starts.
- fix: Accept only 127.0.0.1 or 0.0.0.0, or bind loopback plus the LAN IP as two uvicorn binds. Validate octets 0-255. Derive the interface from `route -n get default`. Put the token requirement from finding 02 in the same block.

## C2-security-13 [minor] /api/monitor/ws/monitor accepts any Origin, and each connection spawns a reader thread plus a Redis connection
- verify: not verified (minor/nit)
- file: services/ui-api/routers/monitor.py:108
- area: WebSocket · reproduced: False
- evidence: ws_monitor (monitor.py:108-160) accepts every socket without an Origin check. Each connection opens redis.from_url(...).pubsub() and starts a reader thread. WebSockets are not covered by CORS.
- failure: A malicious page opens a few hundred ws://127.0.0.1:8010/api/monitor/ws/monitor sockets. That creates hundreds of threads and Redis connections, so ui-api's worker threads and Redis maxclients are exhausted and the terminal's live ticks and SSE stall. The page can also read live quotes cross-site (low sensitivity).
- fix: Reject handshakes whose Origin is not the ui origin (or absent). Cap concurrent sockets (e.g. 32) and share one Redis pubsub fan-out instead of one per client.

## C2-security-14 [nit] .env (ICICI and Telegram secrets) is 0644 inside a home folder that group staff can traverse
- verify: not verified (minor/nit)
- file: .env:1
- area: Local file permissions (other-user threat) · reproduced: True
- evidence: `ls -ld /Users/sudheer` shows drwxr-x---+ sudheer staff. Ancestors are 755, and .env, .logs/*.log, .logs/icici_login_failure.png and data/ui_prefs.sqlite are 0644. Only one human account exists today (dscl). For contrast, the desktop app's own config.json is 0600 (good).
- failure: If a second standard account is ever added (all are in group staff), it can read ICICI_API_KEY/SECRET, ICICI_PASSWORD and TELEGRAM_BOT_TOKEN from .env, plus the login-failure screenshot.
- fix: chmod 600 .env and .logs/*.png; have persist_env_updates write 0600; optionally chmod 700 the repo root.

## C2-security-15 [nit] The devtools feature is compiled into release, and small information leaks remain
- verify: not verified (minor/nit)
- file: desktop/src-tauri/Cargo.toml:24
- area: Release build hygiene · reproduced: True
- evidence: Cargo.toml:24 has `features = ["tray-icon","image-png","devtools"]`, and config.json `devtools: true` enables Web Inspector on the IPC-privileged origin (menu.rs:283-285). shell_save_download returns the absolute path (with the macOS username) to the page (commands.rs:178-180). The 503 page prints the dist path (static_ui.py _MISSING_PAGE).
- failure: Devtools are one config flag away from being enabled on the IPC-privileged origin in a shipped build, and the page learns the local username and path layout. Both are low impact.
- fix: Gate the devtools feature behind a cargo feature used only by dev builds. Return only the basename from shell_save_download (the UI shows 'Saved to Downloads/<name>').

### strengths
- Least-privilege ACL: the remote capability (capabilities-runtime/terminal-remote.json) is exactly the 9 contract commands plus window drag/zoom, granted only to the exact configured origin. The autogenerated permissions each map to a single command. The self-test JSON proves that boot_status, stack_*, open_*, plugin:autostart and plugin:event are rejected from the remote page.
- Frame-aware IPC: Tauri 2.12.5 resolves the ACL from the IPC request's Origin header, and wry's postMessage path uses WKScriptMessage.frameInfo. require_ui/require_boot then re-check webview.url(), so a TradingView iframe cannot ride the terminal's grant.
- Boot page: strict CSP (default-src 'none'; script-src 'self'; connect-src ipc:), proven by the self-test boot_csp check. boot.js renders every value via textContent. The privileged boot origin is reachable only through a shell-issued one-shot permit.
- Navigation guard: file:, javascript: and data: are denied, as are custom schemes and other loopback ports. The localhost↔127.0.0.1 alias is canonicalized. External links open in the default browser. window.open is routed (same-origin opens a new terminal window, capped at 8). Logged URLs never include query strings; the app log shows '?…' redaction.
- Downloads: basename-only sanitizer to [A-Za-z0-9._ -] with leading dots/dashes stripped, base64 length checked before decoding, a 50 MB decoded cap, and O_EXCL create_new, which closes the uniqueness race and refuses to follow a final-component symlink.
- static_ui.py is traversal-proof in practice: --path-as-is GETs for /..%2f..%2f.env, /%2e%2e/%2e%2e/.env, /_next/../../../.env, /.env, /index.html.gz, /%00 and backslash forms all returned JSON 404. Containment uses realpath with the release root resolved per request. It also sends nosniff, XFO SAMEORIGIN on HTML, correct immutable/no-cache/no-store headers, and gzip negotiation with Vary and a distinct ETag.
- prefs.py: fully parameterized SQL, body caps enforced before parsing, a key regex, per-value and total quotas, a future-timestamp clamp, no value logging (keys, sizes and outcomes only), and corruption quarantine instead of deletion.
- Secrets: I scanned the .app bundle, ui/dist/releases, ~/Library/Logs/ai.suryadhana.terminal, the app config dir, .logs/, logs/, services/ui-api/logs, reports/desktop_app and target/ for the literal values of 6 secret .env keys and for login_url/session patterns: 0 hits. The shell deserializes connection-status into two booleans only.
- Stack control never executes the stack's Python. Stop sits behind a native confirm plus an IST freeze guard computed in Asia/Kolkata. config.json is written 0600, and service URLs are validated to loopback http only.
### not checked
- End-to-end DNS rebinding against Safari or Chrome. It needs an attacker-controlled DNS server and a browser, which the brief does not cover. I verified only the missing Host check (spoofed Host returns 200). Chrome 142+ Local Network Access prompts may mitigate it in Chrome; Safari has no equivalent.
- Real cross-site POSTs against the live stack, which are forbidden. CSRF execution was reproduced in a scratch replica with the same CORS config and handler shapes (crit/C2-security/csrf_sim.py), not against :8010. I sent one OPTIONS preflight to :8008/health to read its CORS policy; the CORS middleware answered it and no route ran.
- Whether a LIVE order would actually be accepted by ICICI (session validity, price guard on a trading day). This is inferred from GET /api/execution/status (LIVE/ACTIVE) and the code path; I never POSTed.
- WKDownload quarantine behaviour and .zip/.app or .terminal execution end to end. I did not launch SuryaDhana.app (forbidden). The conclusion rests on the code (no xattr), the Info.plist (no LSFileQuarantineEnabled) and a scratch write showing only com.apple.provenance.
- A port-squatter simulation against the real app (would require launching the app or binding :8010, both forbidden).
- Browser-based checks (Playwright). My brief did not ask for them, so I did not wait for AUDIT_DONE.
- TradingView-compromise behaviour (top navigation without user activation, programmatic data: download from a cross-origin frame in WKWebView). This is reasoned from wry's navigation.rs and the on_download code, not exercised.
- The full contents of /api/positions/connection-status from the LAN. I confirmed HTTP 200 only; I discarded the body unread per the no-secrets rule.

# C2-reliability-ops — SHIP-WITH-FIXES

The core design holds up. Today's real reboot (boot 10:57:20, agents loaded about 10:57:58, ui-api healthy 10:58:58) shows the watchdog bringing the stack back in about 60 s. The release builder is atomic, locked and well tested. static_ui falls back cleanly to a 503 page while /ready stays green. The prefs store is robust: corruption is quarantined, LWW is idempotent, and legacy/provisional imports keep an empty origin from wiping the server. All 11 pending D1 blocks plus pm_lan.py apply cleanly to scratch copies (each OLD unique). They pass `bash -n` under /bin/bash 3.2.57, and `status`/`help` render correctly.

No monitor, Telegram command or controller check still expects :3000. Only the watchdog (fixed by P12), start-local status (fixed by P8), the docs and scripts/ui_audit.py's default --base do. Telegram /status never checked :3000, and it does not check the UI release either.

What stops this from being production-grade is operations, not features:
1. The PM's patch appliers overwrite running bash scripts in place. Reproduced: a running start-local.sh died with "syntax error near unexpected token `else'" (exit 2) after an in-place rewrite.
2. The server prefs store still holds 0 keys (11:31 IST), and :3000, the only origin that holds the owner's watchlist and pins, is about to be stopped.
3. At every login the boot screen turns red after 15 s and offers "Start stack". That runs `launchctl kickstart -k`, which kills the watchdog run that is already starting the stack.
4. When the UI release is missing, the app gives the wrong advice ("start the stack") and nothing alerts.
5. Every restart truncates `.logs/<svc>.log`, so the watchdog's own crash recovery erases the crash traceback (observed: ui-api.log now starts at the 11:07 restart). No log is rotated.
6. The RUNBOOK restore path yields a UI-less terminal, and data/ui_prefs.sqlite has no backup.
7. pm_lan.py accepts a specific LAN IP, which makes ui-api unreachable on loopback for the app, the watchdog and the controller.

Migration answer: the one-time migration is still possible after :3000 stops. The owner must (a) do it before editing the watchlist or pins in the app, (b) run `./start-local.sh start frontend` (the dev server carries the sync code and next.config rewrites /api to :8010), (c) open exactly http://localhost:3000 in the same browser profile they always used, wait a few seconds, (d) check that `curl -s 127.0.0.1:8010/api/prefs` lists suryadhana.watchlist and newsTerminal.pins.v1, then (e) run `./start-local.sh stop frontend`. It is far simpler to do it now, before P4–P14.

## C2-reliability-ops-01 [major] PM patch appliers rewrite start-local.sh / stack_watchdog.sh in place while bash may be executing them
- verify: ['REAL->minor']
- file: /private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/a24906e4-7b64-46ba-b24b-14c536f43922/scratchpad/pm/apply_patches.py:155
- area: ops/patch-application · reproduced: True
- evidence: apply_patches.py:155 `p.write_text(content)` and pm_lan.py:71 `(ROOT / f).write_text(s)` truncate and rewrite the same inode. bash reads scripts incrementally from a saved byte offset. Reproduced in scratch (crit/C2-reliability-ops/inplace): the live start-local.sh plus a 3 s pause after `status` was run, then rewritten mid-run with the D1 P4–P11 + pm_lan version (18,597 → 22,154 bytes). After main returned, bash resumed at byte 18597 of the NEW file (the middle of the P8 `else` branch), printed `run/start-local.sh: line 457: syntax error near unexpected token `else'` and exited 2 instead of 0. start-local.sh:456 is a bare `main "$@"` with no exit. stack_watchdog.sh is all top-level code (lines 69–134), so a run sleeping at line 71 resumes inside shifted text (P12 adds about 190 bytes before it).
- failure: The PM applies P4–P14 while a watchdog run is in progress (every 120 s; it spends 30 s in `sleep 30` whenever a CORE service is down) or while a watchdog-launched `start-local.sh start <svc>` is running. That run then executes fragments of the new file: at best a syntax error (exit 2, so the watchdog logs 'FAILED to start' and Telegrams a false failure); at worst a line that happens to sit at the old offset (the new file contains `stop_services`, `kill -9 $alive`, `exec scripts/build_ui.sh`). Every future in-place edit by an agent or tool carries the same latent hazard.
- fix: Write atomically, giving the file a new inode so a running bash keeps the old one: `tmp = p.with_name(p.name + f'.tmp-{os.getpid()}'); tmp.write_text(content); shutil.copymode(p, tmp); os.replace(tmp, p)`. Apply P4–P14 only when `pgrep -f 'stack_watchdog.sh|start-local.sh'` is empty. Harden both scripts: end start-local.sh with `main "$@"; exit $?` on one line, and wrap the watchdog body in `main() { … }` ending with `main "$@"; exit $?`, so bash never reads past the last line.

## C2-reliability-ops-02 [major] Server prefs store is still empty while the only origin holding the owner's watchlist/pins (:3000) is about to be stopped
- verify: ['REAL->major']
- file: reports/desktop_app/prefs_inventory.md:84
- area: migration/prefs · reproduced: True
- evidence: `curl -s 127.0.0.1:8010/api/prefs` returned 0 keys at 11:2x and again at 11:31 IST. data/ui_prefs.sqlite was created 11:07 at 4096 bytes. The live :3000 build (ui/.next-prod BUILD_ID 24 Oct 15:32) does contain the sync code (chunk 1170-87bf5039cd9a56f0.js references api/prefs), but nobody has opened it in the owner's browser since ui-api got the prefs router at 11:07. All QA contexts run with suryadhana.prefs.mode=readonly and fresh profiles, so they never migrate. PLAN §7 step 6 stops :3000 right after parity. prefs_inventory.md:92-94 documents that if the owner edits a key in the app first, LWW makes the app copy win and the old value survives only in that browser's suryadhana.prefs.backup.
- failure: The PM applies D1 P4–P14 and runs `stop frontend`. The owner launches SuryaDhana.app: the watchlist is empty and the pins are gone. The owner re-adds a few symbols (a deliberate PUT clears the provisional mark). Later, opening :3000 through `start frontend` gets the legacy import back as 'skipped', so the original watchlist never reaches the app. To the owner, the product lost their data on day 1.
- fix: Gate step 6 on `GET /api/prefs` listing suryadhana.watchlist and newsTerminal.pins.v1 with origin http://localhost:3000. Before stopping :3000, ask the owner to open http://localhost:3000 once in their usual browser (exact host spelling, profile not in readonly mode). Document the after-the-fact path in the RUNBOOK: `./start-local.sh start frontend`, open the same origin, verify /api/prefs, then `./start-local.sh stop frontend`, and do this before editing the watchlist or pins in the app. Optionally the app could show a one-time banner when /api/prefs has no suryadhana.watchlist.

## C2-reliability-ops-03 [major] Every login: boot screen declares DOWN after 15 s and offers 'Start stack', which `kickstart -k`s (kills) the watchdog run that is already starting the stack
- verify: ['REAL->major']
- file: desktop/src-tauri/src/stack.rs:84
- area: boot/login-ordering · reproduced: False
- evidence: boot.js:17 `DOWN_ACTIONS_AFTER_S = 15`. boot.js:99-110 then shows 'Terminal unreachable for N s. The watchdog restarts core services every 2 min; start the stack now…' plus Start, and also 'Stop stack…' as soon as any service is up. The watchdog's login path needs much longer by design. Today's reboot in .logs/watchdog.log: agents loaded about 10:57:58 → `sleep 30` debounce → 10:58:30 data-service starting → 10:58:48 ui-api starting → 10:58:58 ui-api healthy, about 60 s. So the red state with actions is shown for about 45 s on every normal boot (the exact text is in selftest-down-20261024.json boot_down_state). Start runs stack.rs:84-87 `launchctl kickstart -k gui/<uid>/com.suryadhana.watchdog`, and `-k` kills a running instance. Scratch test (trap_test.sh): SIGTERM runs the watchdog's EXIT trap and removes `.pids/watchdog/lock`; SIGKILL leaves the lock behind, and stack_watchdog.sh:32-35 then makes every run exit silently until the lock is 20 min old.
- failure: The owner logs in after a reboot. At T+15 s the boot screen is red with 'Start stack', which the owner clicks. The in-flight watchdog run dies mid-loop: the in-progress `timeout 300 start-local.sh start data-service` survives in timeout's own process group, but the ui-api and master-controller starts are abandoned. The restarted run sleeps 30 s, and if the orphaned start is still running its `pgrep start-local.sh` makes it defer until the next 120 s tick. The terminal arrives 30–150 s later than it would have without the click. If launchd escalates to SIGKILL, the orphaned mkdir lock disables the watchdog for 20 min, with no Telegram.
- fix: In stack.rs start_plan, drop `-k`. Plain `kickstart` starts the job only when it is not running, or check `launchctl print … state = running` first. Have boot_status expose app uptime and a watchdog_running flag (from `launchctl print`). In boot.js, show 'Stack starting (watchdog)…' without actions while the watchdog is running or the app uptime is under about 150 s. Show Stop stack only on explicit request, never during a start.

## C2-reliability-ops-04 [major] Missing/broken UI release: the app tells the owner to start the stack (and offers Stop), never says 'build-ui/rollback', and nothing alerts
- verify: ['REAL->minor']
- file: desktop/boot/boot.js:99
- area: observability/ui-release · reproduced: False
- evidence: With ui-api up and ui/dist/current missing, health.rs:446 sets ui_detail 'GET / returned HTTP 503 (UI build not served yet?)'. boot.js:99 then switches to the generic down state after 15 s: 'The watchdog restarts core services every 2 min; start the stack now', plus Start stack and, because all services are up (boot.js:110), 'Stop stack…'. Neither can fix a missing release. The real remedy (`scripts/build_ui.sh`, `--rollback`) appears only in static_ui.py's 503 HTML (lines 421-443), which the app never displays: the window stays on the boot page because ui_ready needs 200 text/html. desktop/README.md:180 troubleshooting says 'GET / returned HTTP 404', but the actual status is 503. Pending P14 only writes an hourly line to watchdog.log ('Never auto-build', no Telegram). Telegram /status (scripts/master_controller.py:1775) probes only data-service and ui-api /health, which stay 200 while the UI is missing. /ready already reports `"ui":"missing"` (observed shape: {"status":"ready",…,"ui":"ok","ui_build_id":…}).
- failure: After a restore (ui/dist is git-ignored; see C2-reliability-ops-06), a stray `rm -rf ui/dist`, or a prune or disk problem, the owner opens the app. All three services show UP, the terminal row says HTTP 503, and the advice is to start the stack. The owner clicks Start (a no-op that kicks the watchdog) or Stop, and Stop halts the EOD, Desk and backup jobs. Away from the Mac, Telegram /status shows everything green.
- fix: health.rs: on 503 (or always), also GET /ready, and when ui == 'missing' set a distinct ui_detail plus a `ui_missing` flag in BootStatus. boot.js: add a 'no UI release' state that shows the commands `./start-local.sh build-ui` and `./start-local.sh build-ui --rollback`, and hides Start/Stop. README troubleshooting: list 503 with those commands. Watchdog P14: also Telegram, throttled to once per 6 h. Telegram /status: add a 'terminal UI: release <id> / MISSING' line from /ready.

## C2-reliability-ops-05 [major] Every (re)start truncates the service log, so the watchdog's auto-restart erases the crash traceback; no rotation anywhere
- verify: ['REAL->major']
- file: start-local.sh:168
- area: observability/logs · reproduced: True
- evidence: start-local.sh:168 `> "$PROJECT_ROOT/.logs/$name.log" 2>&1` (frontend: lines 250/252). Observed: .logs/ui-api.log now begins with the 11:07 start (pytz warning, then static_ui.mounted at 05:37:41Z), and the output of the 10:58–11:07 instance is gone. frontend.log is 296 bytes. Nothing is rotated: ui-api.log reached 331 KB in about 15 min under audit load (4,301 lines; ui-api now also logs every static-asset request), and watchdog.log grows forever with ANSI escape codes. The watchdog's alert text says 'see .logs/<service>.log', which by then is the new instance's log.
- failure: ui-api crashes at 14:05 (the terminal goes black or frozen, since ui-api now serves the UI shell itself). The watchdog restarts it at about 14:07 and truncates ui-api.log. When the owner investigates the Telegram 'stack was down' note, the traceback no longer exists, so root cause cannot be established. Repeated crashes look like isolated incidents.
- fix: In start_py_service and start_frontend, rotate before starting (`for i in 4 3 2 1; do [ -f "$log.$i" ] && mv "$log.$i" "$log.$((i+1))"; done; [ -f "$log" ] && mv "$log" "$log.1"`), then write with `>>` and a '=== start <ts> pid <n>' banner. Add size-based rotation: a nightly controller job or a newsyslog.d entry with a 50 MB cap, gzip, keep 5. In the watchdog, before starting a down service, `tail -n 400 .logs/$svc.log > .logs/crash/$svc-$(date +%Y%m%d-%H%M%S).log`, and name that file in the Telegram message.

## C2-reliability-ops-06 [major] RUNBOOK restore path produces a UI-less terminal; ui_prefs.sqlite has no backup or restore procedure; stale :3000/autostart instructions
- verify: ['REAL->minor']
- file: docs/RUNBOOK_RESTORE.md:66
- area: runbook/backup-restore · reproduced: True
- evidence: RUNBOOK §1 (lines 27-31) runs `npm ci` only and has no `build-ui` step. ui/dist/ is git-ignored (.gitignore:54), so a restored Mac serves the 503 page, and the watchdog deliberately never builds (P14). §4 line 66 lists frontend as core. Line 69 runs `scripts/ui_audit.py` 'expect 15/15', but ui_audit.py:187 defaults to `--base http://localhost:3000`, which is refused after the switchover; CLAUDE.md:124 uses the same command. §5 line 76 still recommends scripts/install_autostart.sh, an obsolete second login agent (com.suryadhana.stack, `UI_MODE=prod ./start-local.sh start`) superseded by the watchdog. §6 line 81 says 'ui/.next-prod … rebuilt by start-local'. Lines 88-89 say the watchdog starts the 'prod terminal'. There are no steps for SuryaDhana.app install, Launch at Login or the app log location. scripts/db_backup.py backs up only market-*.duckdb (lines 82, 100), so data/ui_prefs.sqlite (WAL mode; the live -wal is 8,272 bytes) is in no backup, and a naive `cp` without the -wal file misses committed writes. The LAN change (pm_lan: ui-api is loopback by default, so the phone/iPad path that :3000 provided disappears) exists only as a code comment. CLAUDE.md:7/23/30/93/104 still describe the 4-process :3000 stack.
- failure: On a disk replacement the owner follows the RUNBOOK: services come up, the app shows HTTP 503 with 'start the stack' (see C2-reliability-ops-04), ui_audit reports connection refused, and the watchlist and pins are gone unless the old Mac's app profile survived. Following §5 installs a redundant login agent. The phone/iPad terminal silently stops working at switchover.
- fix: RUNBOOK: §1 add `./start-local.sh build-ui`, then check that `/ready` shows ui ok. §4: core = 3 services, and `scripts/ui_audit.py --base http://127.0.0.1:8010` (or change the default). §5: replace install_autostart.sh with `scripts/install_launch_agents.sh install`, add the SuryaDhana.app install (installed copy first) and Launch at Login. §6: say ui/dist is rebuilt by build-ui. Add a prefs section: nightly backup with `sqlite3.connect('data/ui_prefs.sqlite').backup(dst)` inside db_backup.py (rotated like the DuckDB backups); restore = stop ui-api, copy the file, delete -wal/-shm, start (clients re-upload any key they synced, merge.ts:136-141). Add the UI_API_HOST=0.0.0.0 phone/iPad note. Update CLAUDE.md lines 7/23/30/93/104/124.

## C2-reliability-ops-07 [major] UI_API_HOST accepts any dotted string (e.g. the Mac's LAN IP, even 999.1.1.1); binding ui-api to it breaks every loopback consumer
- verify: ['REAL->minor']
- file: /private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/a24906e4-7b64-46ba-b24b-14c536f43922/scratchpad/pm/pm_lan.py:25
- area: ops/start-local (pending pm_lan.py) · reproduced: True
- evidence: I sourced the applied block and fed it test values. 192.168.1.20 and 999.1.1.1 both come out unchanged; localhost, :: and a value with a trailing space are coerced to 127.0.0.1 with a warning. The block's own message invites this: 'use 127.0.0.1, 0.0.0.0 or an IPv4 address'. A listener bound to this Mac's LAN IP (192.168.31.62:18977) accepted a connection to the LAN IP, but `connect 127.0.0.1` got ConnectionRefusedError. The consumers that need loopback: start_py_service's health loop (`curl http://localhost:$port/health`, start-local.sh:172), watchdog is_up (stack_watchdog.sh:51), the app (ui_url http://127.0.0.1:8010 only; config.rs rejects non-loopback) and master-controller (UI_API_URL=http://localhost:8010, start-local.sh:142).
- failure: The owner wants iPad access and sets UI_API_HOST=192.168.31.62 in .env. ui-api listens only there. start-local reports 'did not become healthy' after 60 s. The watchdog sees ui-api down on every run, finds the port already LISTENing ('already running'), and is_up still fails, so it sends a 'FAILED to start' Telegram every 30 min. The app stays on the boot page forever, and Telegram /status shows ui-api red. When DHCP changes the IP, uvicorn cannot bind at all after a reboot.
- fix: Accept only 127.0.0.1 or 0.0.0.0. For any other value, warn ('binding a single interface breaks local health checks; using 0.0.0.0') and use 0.0.0.0, or refuse. Change the message to say exactly that. Show the effective bind address in `status`.

## C2-reliability-ops-08 [minor] 'X is back up' notification is suppressed for any outage shorter than 2 min (down and up share one throttle key)
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/lib.rs:378
- area: desktop/notifications · reproduced: False
- evidence: lib.rs:378 `shell.notify_throttled(app, &format!("svc:{name}"), Duration::from_secs(120), …)` is used for both WentDown and CameUp. WentDown fires after 2 failed 5-s polls with a 2-s /health timeout (health.rs:427). A manual `restart ui-api` takes about 13 s (watchdog log 10:58:48→10:58:58), and watchdog recoveries take about 40–160 s, so CameUp lands inside the 120 s window and is dropped. Also, the app's 2-s /health timeout is far stricter than the watchdog's 8 s (stack_watchdog.sh:56), so a ui-api event-loop stall of about 10 s (a known historical failure mode) produces a 'down' banner the watchdog would not act on.
- failure: During market hours the PM restarts ui-api, or it crashes and recovers within 2 min. The owner, away from the desk, sees a lock-screen notification 'ui-api is down — the watchdog restarts…' and never gets the recovery notice, so they assume the terminal is still down.
- fix: Throttle per (service, transition), or always deliver CameUp when the last delivered notification for that service was WentDown. Coalesce flaps by delaying WentDown 15–20 s. Use a 5–8 s /health timeout to match the watchdog.

## C2-reliability-ops-09 [minor] Chunk carry-forward is transitive and unbounded: every release keeps every chunk ever built (×3 full copies)
- verify: not verified (minor/nit)
- file: ui/scripts/release.mjs:261
- area: release/carry-forward · reproduced: True
- evidence: carry() copies every file under the source release's _next/static that the destination lacks, including files that release had itself carried and their .gz siblings. pickCarry uses current and previous. A scratch simulation with the real release.mjs (crit/C2-reliability-ops/carrysim/sim.mjs: 10 builds, one new chunk each, swap and prune keep=3) gave 'chunks in new release' = 1,2,3,…,10. Each release is a full copy (no hardlinks); the live release is 4.5 MB, 4.3 MB of it _next/static. build-info files/bytes inflate the same way.
- failure: After months of UI releases (each changing about 1–3 MB of hashed chunks), every release directory carries hundreds of MB of dead chunks, 3 copies are kept, and each build's carry step copies them all again. Builds slow down and disk use grows without bound on the same disk that holds the 4.4 GB DuckDB and its nightly backups (the watchdog alerts below 20 GB free).
- fix: Record each release's native _next/static file list in build-info (or a static-manifest.json) and carry only the native files of current and previous. That preserves the 'open window survives 2 swaps' guarantee and caps growth. Optionally hardlink (fs.linkSync) instead of copying.

## C2-reliability-ops-10 [minor] Python service restarts still depend on Node/npm ('Node out of production' is not true for the restart path)
- verify: not verified (minor/nit)
- file: start-local.sh:52
- area: ops/start-local · reproduced: True
- evidence: check_prerequisites exits 1 when npm is missing (start-local.sh:52-55), and it runs for every `start <svc>`, including watchdog restarts of data-service, ui-api and master-controller. install_deps runs `npm install --legacy-peer-deps` whenever ui/node_modules is absent (lines 100-103). Reproduced on the patched scratch copy: `env -i PATH=/usr/bin:/bin bash patched/start-local.sh start ui-api` stops at '✗ npm is not installed' before starting anything.
- failure: A `brew upgrade`/uninstall leaves npm off /opt/homebrew/bin, or the owner is mid `rm -rf ui/node_modules && npm ci`. ui-api crashes, and the watchdog's restart either exits at the npm check or starts a concurrent npm install under the 300 s timeout. ui-api stays down and a FAILED Telegram goes out every 30 min, all for a Node dependency the 3 Python services do not need.
- fix: Require npm, and run the node_modules install, only when the start set includes frontend or the command is build-ui.

## C2-reliability-ops-11 [minor] --self-test writes its synthetic attacks and scratch-origin traffic into the owner's real app log
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/lib.rs:503
- area: observability/app-log · reproduced: True
- evidence: resolve_paths isolates state, window state and downloads in self-test but keeps the real log_dir (lib.rs:499-509). ~/Library/Logs/ai.suryadhana.terminal/suryadhana.log (819 lines) contains entries such as `[nav] main: blocked tauri://localhost/index.html (boot page navigation not initiated by the shell)`, `[nav] main: blocked http://127.0.0.1:8001/health`, `[ipc] shell_notify rejected: title longer than 120 characters` and terminal loads of scratch origins :8092/:8098, all from self-test and drill runs and not marked as such.
- failure: After `scripts/build_desktop.sh --install --test`, the owner diagnosing a real problem (a 'black window') opens Help ▸ App Logs and finds WARN lines about blocked navigations and rejected IPC. These look like an attack or a bug and hide the real entries.
- fix: In self-test mode log to `<temp_dir>/logs` (and copy the file next to the JSON report), or prefix every line with `[selftest]`.

## C2-reliability-ops-12 [minor] Nothing restarts the app if it crashes; tray, notifications and ICICI-expiry alerts stop until next login
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/lib.rs:573
- area: desktop/supervision · reproduced: False
- evidence: tauri-plugin-autostart 2.7.0 → auto-launch 0.6.0 writes a LaunchAgent with RunAtLoad only (macos.rs:288-306; agent_extra_config not set by the plugin). There is no KeepAlive. The watchdog supervises only the 3 Python services. The Rust shell has panic paths (`.expect("error while building the SuryaDhana app")` lib.rs:700, `expect("http client")` health.rs:371).
- failure: On an unattended Mac mini, the shell crashes (a WebKit or plugin panic) on Monday at 10:00. The menu-bar NIFTY/health item and native 'service down' and 'ICICI session expired' notifications are silently gone for the rest of the week. Only Telegram remains.
- fix: Have the watchdog relaunch the app (throttled, logged): if ~/Library/LaunchAgents/SuryaDhana.plist exists (Launch at Login on) and `pgrep -x SuryaDhana` is empty on 2 checks, run `open -gj -b ai.suryadhana.terminal`. Alternatively, write the autostart plist yourself with KeepAlive {SuccessfulExit: false}, so ⌘Q stays honoured.

## C2-reliability-ops-13 [minor] Fallback 'Start stack' (watchdog not loaded) launches the stack's Python as a child of SuryaDhana.app, contrary to the TCC design note
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/stack.rs:89
- area: desktop/stack-control · reproduced: False
- evidence: stack.rs:1-9 says 'The app NEVER runs the stack's Python itself (TCC: the interpreter lives under ~/Desktop…)'. But start_plan with watchdog_loaded=false spawns `/bin/bash <repo>/start-local.sh start` from the app (stack.rs:88-95), which runs ~/Desktop/jupyter_env/bin/python. macOS attributes TCC to the responsible process (the app), and process_group(0) does not change that. There is no TCC preflight on this path, unlike stack_watchdog.sh:79-86. An ad-hoc-signed app's TCC grant is tied to its code signature and is invalidated by every rebuild.
- failure: After an `install_launch_agents.sh uninstall`, or on a fresh restore where the agents are not installed yet, the owner clicks Start stack. Python blocks on a 'SuryaDhana would like to access files in your Desktop folder' prompt, or is denied. start-local reports 'did not become healthy' after 60 s per service, the boot page stays down, and the failure is visible only in .logs/desktop-stack.log.
- fix: When the watchdog agent is not loaded, do not spawn start-local.sh. Bootstrap the agent instead (`launchctl bootstrap gui/<uid> ~/Library/LaunchAgents/com.suryadhana.watchdog.plist` if the plist exists), or show 'run scripts/install_launch_agents.sh install', so Python is always started by launchd.

## C2-reliability-ops-14 [minor] A SIGKILLed or crashed build leaves ui/.build-ui/staging-* behind forever
- verify: not verified (minor/nit)
- file: scripts/build_ui.sh:203
- area: release/interrupted-build · reproduced: False
- evidence: The staging dir is `$WORK_DIR/staging-$RELEASE_ID-$$` (build_ui.sh:203), removed only by the run's own cleanup trap (line 74). acquire_lock takes over a stale lock (lines 132-139) but never removes stale staging dirs. prune() cleans only releases/.incoming-* with dead pids (release.mjs:390-397). A staging copy holds the UI sources plus Next's intermediate .next build output (ui/.next-prod is 1.5 GB for comparison).
- failure: A build is killed by OOM, `kill -9`, a reboot or a closed laptop lid, possibly several times over the months. Each leaves a staging tree inside ui/, consuming disk on the data volume. A leftover staging dir also shows up in `check_ui_entries` and in tools that scan ui/.
- fix: After acquiring the lock, delete `ui/.build-ui/staging-*-<pid>` dirs whose pid is not alive (the same rule prune applies to .incoming-*).

## C2-reliability-ops-15 [nit] Three 'X is back up' notifications at every login although nothing went down from the app's point of view
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/health.rs:785
- area: desktop/notifications · reproduced: False
- evidence: SvcTracker treats a launch-time baseline of 'down' as a stable state, and the next success emits CameUp. The unit test asserts this (health.rs:785-788: observe(false), observe(false) → None; observe(true) → Some(CameUp)). At login the stack is down for about 60 s, so the app posts 'ui-api is back up', 'data-service is back up' and 'master-controller is back up'.
- failure: Every reboot or login produces 3 'back up' banners alongside the watchdog's Telegram note. The notifications become noise and the owner learns to ignore them, including the real ones.
- fix: Suppress CameUp transitions from a launch baseline (or during the first about 3 min of app uptime), or replace them with a single 'Stack ready' notification.

### strengths
- static_ui.py serves the UI as the router's not-found fallback, so /api, /health and later routes are never shadowed. It resolves ui/dist/current on every request, so a swap or rollback is live with no restart. A missing build gives a self-refreshing 503 page while /health and /ready stay up (/ready reports ui ok|missing). Asset I/O runs on a dedicated 16-token limiter, separate from the DuckDB thread pool. Verified live: /ready → {"ui":"ok","ui_build_id":"20261025-110718-0ae66db"}, index.html is 7,422 B (2,463 B gzip) in about 1 ms.
- build_ui.sh/release.mjs: the build is staged in a copy (ui/.next and ui/.next-prod are never touched), verified before the swap, and swapped by rename(2) of a temp symlink. A pid lock is taken over when stale and serializes concurrent runs; cleanup traps restore protected files only when the build itself rewrote them. Rollback carries the outgoing chunks; prune protects current and previous and removes dead .incoming-* entries. Lock, failure and verify paths are covered by node tests.
- Prefs store: SQLite kept separate from the 4 GB DuckDB, WAL with busy_timeout and BEGIN IMMEDIATE, one serialized connection (so WAL checkpoints are never starved). Corruption is quarantined (renamed, never deleted), a newer schema is refused with 503, and idempotent replays return 200. The legacy-versus-provisional import design means an empty new origin, such as the app on first launch, cannot wipe the server. The client persists its dirty queue across reloads and outages and flushes with keepalive on pagehide, so a ui-api restart loses no settings.
- Watchdog: two-check debounce, paused markers, TCC preflight, Telegram sent straight to the Bot API, a disk check and a dead-man ping. Observed: services started through GNU `timeout` land in their own process groups (pgid 2447/2854/13062 ≠ watchdog), so launchd's job-group cleanup never kills them. Today's real reboot recovered the full stack about 60 s after login with no human.
- All 11 pending D1 blocks (P4–P14) and both pm_lan.py stages apply to scratch copies with each OLD unique, pass `bash -n` under /bin/bash 3.2.57, and `status` (adds the 'ui-release ok <id>' row) and `help` render correctly against the live ports (read-only).
- No runtime monitor still expects :3000 after P12: master-controller and Telegram /status never probed it; ui-api has no :3000 health dependency (only a dev CORS entry).
- Desktop shell: the health poller deserializes only two booleans from connection-status and never logs the login_url (the app log has 0 secret-like strings). Terminal windows are not taken away from the user on a blip; a window whose load never commits within 12 s returns to a 'reconnecting' boot page; Tauri's default reloads the webview after a WebContent process crash. Session restore uses atomic writes. The app log rotates at 5 MB × 5. The UI side has a connection banner with a 4 s grace, WS reconnect with backoff, EventSource auto-retry and a guarded ChunkLoadError reload that waits while the origin is unreachable.
### not checked
- I did not launch SuryaDhana.app or run the AC-10 drills (ui-api restart mid-session, release swap with an open window, sleep/wake), as the brief forbids. Window, banner and boot-page behaviour was traced in code, plus the self-test JSON and relaunch-drill evidence.
- Whether `launchctl kickstart -k` sends SIGTERM or SIGKILL to a running watchdog. I would have had to create a launchd job to test it, which is outside read-only scope. Bash's EXIT-trap behaviour under SIGTERM vs SIGKILL was verified in scratch.
- The boot page's actual WebKit rendering for the 'ui-api up, UI release missing' (503) case. No browser was allowed in my brief, so the result comes from tracing health.rs, commands.rs and boot.js.
- The patched stack_watchdog.sh was not executed: it curls the live stack and could start services or Telegram. Only `bash -n` and code review were done; the in-place-rewrite hazard was reproduced with start-local.sh instead.
- TCC attribution for the app's fallback start path (C2-reliability-ops-13) was not tested, because it would start live services.
- Prefs corruption, lock-contention and disk-full paths were not exercised live: no POST/PUT is allowed against :8010, and I did not run test_prefs.py. The judgement comes from code review and the PM's reported green ui-api suite (601).
- ui-api log growth under normal (non-audit) desktop usage was not measured; the only measurement (about 331 KB per 15 min) was taken under the PM's audit load.
- The after-switchover migration path (`./start-local.sh start frontend` → owner's browser → legacy import) was not exercised end to end. It needs the owner's real browser profile, and starting frontend is not allowed.
- Idle CPU and RSS of the app and the cost of the 1-s/5-s health poll over days were not measured.

# C3-logic-unchanged — SHIP-WITH-FIXES

The trading and business logic is untouched. No file under shared/, alpha_lab/, services/data-service/ or services/execution-service/ is newer than FEASIBILITY.md (24 Oct 10:38). The same holds for scripts/master_controller.py, scripts/live_execution.py, services/ui-api/backtest_engine.py and every ui-api router except the new prefs.py. ui-api's API behaviour is also unchanged. I loaded the pre-integration backup of main.py and the current one, with no lifespan, and sent both the same 31 request shapes through TestClient. Every existing route returns the same status, content type and envelope: unknown /api paths still give the JSON 404 envelope, 405 and the trailing-slash 307 still work, HEAD and OPTIONS behave as before, and CORS preflight results are the same. What differs is limited to the 6 new paths (/api/prefs x3, /version, /ready, /live), the UI files, and an HTML 404 page when a browser navigates to an unknown non-API path. The only Next rewrite is /api/:path* to ui-api :8010 (confirmed in ui/.env.local without printing values). The 6 app/api/**/route.ts stream proxies that the static export drops all exist natively in the live ui-api OpenAPI with the same methods, and nothing points at :8001 or :8008 directly. The PM applied every patch block exactly as documented (diffed against ~/.suryadhana_pm_backups). D3's browser branches are verbatim copies of the code they replaced, and the link interceptor installs only in the desktop app. The D4 lazyTab change is safe because no tab uses a construct that suspends. The idle warm-up fires no API calls: an AST scan of components/, lib/ and context/ found no import-time side effects. Four things must be fixed before calling it "logic unchanged": (1) The owner's settings have NOT been migrated. Live GET /api/prefs returns {"prefs": {}}, and the pending switchover stops :3000, the only place they can migrate from. (2) Two app windows can lose each other's watchlist edits. I reproduced this with the real sync engine, and it contradicts D3.md's claim that ⌘N is fixed. (3) The :3000 parity baseline was rebuilt on 24 Oct 15:32 and already contains D3/D4's UI code, so AC-3 parity cannot prove the UI is unchanged from before the program. (4) The pending pm_lan.py accepts a specific IPv4 address, which breaks every loopback consumer of ui-api.

## C3-logic-unchanged-01 [major] Owner's settings not yet migrated, and the pending switchover removes the only origin that can migrate them
- verify: ['REAL->major']
- file: reports/desktop_app/PLAN.md:184
- area: prefs migration / switchover sequencing · reproduced: True
- evidence: Live `curl http://127.0.0.1:8010/api/prefs` returned {"prefs": {}, "server_time": ...} at about 11:25 IST. data/ui_prefs.sqlite is 4096 B plus an 8 KB WAL, created 11:07 when ui-api restarted with the prefs router. The :3000 server (pid 2955, `next start -p 3000`) serves ui/.next-prod, built 24 Oct 15:32; its chunk 1170-87bf5039cd9a56f0.js contains the '/api/prefs' sync code. prefs_inventory.md:84-92 says the one-time migration runs only when the owner's usual browser loads that :3000 build. The pending D1 P5/P12 remove frontend from CORE, and PLAN §7 step 6 then stops :3000. Steps 6 and 7 have no check that the migration happened. Before 11:07, /api/prefs was a 404 on live, so no earlier visit could have migrated anything.
- failure: The PM applies P4–P14, stops :3000 and installs the app with autostart. The owner logs in and the app opens on the new origin http://127.0.0.1:8010 with empty localStorage. The watchlist ([]), pins, ticket sizing, goldPreOpen baseline and checks, fund filters, research selection and GO recents all show defaults. The app uploads '[]' as a provisional value. If the owner adds even one symbol before reopening :3000, last-write-wins makes that the server value, and the later legacy import from :3000 is 'skipped'. The original list then survives only in :3000's localStorage (suryadhana.prefs.backup). To the owner the conversion looks like it lost their data on day one.
- fix: Make the migration a hard gate before step 6. Keep :3000 running and ask the owner to open http://localhost:3000 once (and the iPad/phone LAN :3000 if used). Proceed only when GET /api/prefs shows non-provisional records whose origin is the old :3000 origin for at least suryadhana.watchlist and newsTerminal.pins.v1. Add this check to the switchover script or to `start-local.sh status` ('prefs: N keys, legacy import: done/missing'). Optionally, have the app show a one-time notice when the store has no non-provisional records: 'Settings not yet imported from the browser terminal: open localhost:3000 once'.

## C3-logic-unchanged-02 [major] Same-origin multi-window watchlist edits overwrite each other; D3 1d does not fix ⌘N
- verify: ['REAL->major']
- file: ui/context/AppContext.tsx:276
- area: prefs sync / multi-window · reproduced: True
- evidence: AppContext reads the watchlist from localStorage once, on mount (lines 260-271). The 1d listener (lines 276-287) reacts only to 'suryadhana:prefs-changed'. The sync engine emits that event only when it applies a server value that differs from the current localStorage value. App windows share one localStorage: windows.rs:409 makes the webview incognito only in self-test, so all windows use the default data store. So the second window never gets the event, and D3's own check E9 asserts exactly this (ui/lib/__tests__/prefs.check.ts:392-403, 'window 2 applied nothing'). I ran `node ui/lib/__tests__/prefs.check.ts` and all 107 checks pass. A grep shows only lib/pins.ts listens to the native 'storage' event. I simulated it with the real PrefsSyncEngine and one shared storage (/private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/a24906e4-7b64-46ba-b24b-14c536f43922/scratchpad/crit/C3/multiwin.mts): window A adds HDFCBANK, window B refetches and gets no event, then B removes INFY. Result: server and localStorage hold ["RELIANCE","TCS"], and HDFCBANK is lost. D3.md:95 claims 'The patch makes multi-window (⌘N) correct'.
- failure: After a relaunch the app restores two windows (AC-7 session restore), or the owner presses ⌘N. The owner adds a stock to the watchlist in window 1. Later they remove a different stock in window 2, which still holds its mount-time list. Window 2 writes its stale list, which is uploaded to the server, and window 1's addition is silently gone everywhere, including other devices after sync. The same pattern affects TradeTicket, GoldPreOpen and FundamentalsScreen state.
- fix: In AppContext, also adopt changes from other same-origin windows, as lib/pins.ts already does: `window.addEventListener('storage', e => { if (e.key === WATCHLIST_KEY) adopt(e.newValue) })`, with the same parse and filter. Apply the same pattern to the other SYNC-key consumers that cache state on mount. Add an E2E with two pages in ONE browser context: edit in page 1, edit in page 2, and assert both edits survive. Correct the D3.md claim.

## C3-logic-unchanged-03 [major] The :3000 parity baseline already contains the program's UI changes, so parity cannot prove the logic is unchanged
- verify: ['REAL->minor']
- file: reports/desktop_app/switchover/parity.log:1
- area: evidence / AC-3 parity · reproduced: True
- evidence: ui/.next-prod/BUILD_ID was modified 2026-10-24 15:32, after D3's call-site edits (11:30) and D4's layout and globals.css (11:31 and 11:50). static/chunks/1170-87bf5039cd9a56f0.js contains `__SURYADHANA_SHELL__`, '/api/prefs' and 'prefs-changed'. static/css/b7bd282d6a372266.css contains `--shell-top`. The page chunk lacks only the PM's 25 Oct P7/P8 code (no requestIdleCallback). The only measurement of the pre-program build is reports/desktop_app/perf_baseline_3000.csv (11:28, perf counts only, no structural parity). parity.log reports PARITY between this rebuilt :3000 and :8010.
- failure: Any browser-mode behaviour change that D3/D4 introduced is present on both sides and is reported PARITY. Examples: the PlatformShell boot gate, prefs hydration overriding localStorage, the /health monitor and banner, the CSV helper change, the font swap, and C3-02/C3-05. AC-3 and the owner's 'logic remains same' requirement would be signed off against a baseline that already includes the change under test.
- fix: Build a true pre-program baseline. In a staging copy of ui/, reverse the recorded blocks: D3.md §2 call sites, D3 1d, D4 P1–P11. Restore the original layout.tsx and global-error.tsx, which are recorded in D4's first transcript (agent-a67f6ea07f9ae62d7, 05:39 UTC). Drop components/desktop, lib/platform, lib/prefs and the PlatformShell wrapper. Build with `scripts/build_ui.sh --out <scratch>`, serve it with scripts/desktop_qa/scratch_server.py, and run parity.py with A=baseline and B=:8010 in both engines. Publish the expected-delta list (gate, prefs GET/PUT, /health, build-info). At minimum, label the current report 'vs the 24 Oct 15:32 build (already contains D3/D4)'.

## C3-logic-unchanged-04 [major] UI_API_HOST accepts a specific IPv4 address, which takes ui-api off loopback for every local consumer
- verify: ['REAL->major']
- file: /private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/a24906e4-7b64-46ba-b24b-14c536f43922/scratchpad/pm/pm_lan.py:25
- area: pending PM block (LAN host) · reproduced: True
- evidence: The case statement (lines 25-29) normalises only non-numeric values, and its warning text tells the user to 'use 127.0.0.1, 0.0.0.0 or an IPv4 address'. These consumers all reach ui-api over loopback: scripts/stack_watchdog.sh:51/56 (is_up → http://localhost:8010/health), start-local.sh:172 (start_py_service waits on http://localhost:$port/health), start-local.sh:271 (start_one treats any listener on the port as 'already running'), desktop/src-tauri/src/config.rs:23 (DEFAULT_UI_URL http://127.0.0.1:8010, loopback-only), and scripts/daily_session_refresh.py:59/108 (POSTs the ICICI session token to localhost:8010). Demonstration: a scratch python http.server bound to this Mac's en0 address on port 18765 answered 200 on that IP and 000 (refused) on both localhost and 127.0.0.1. I stopped it immediately.
- failure: The owner sets UI_API_HOST to the Mac's LAN IP, as the warning invites, to use the iPad. ui-api then listens only on that IP. start-local reports 'did not become healthy'. Every 2 minutes the watchdog sees ui-api down, but start_one says 'already running', so ui-api is reported down indefinitely. The desktop boot screen never reaches the terminal. The 08:00 ICICI session refresh cannot post the token, so there is no live data that day. A DHCP address change makes the bind fail outright.
- fix: Accept only 127.0.0.1 and 0.0.0.0. Reject anything else and fall back to 127.0.0.1, and change the warning to 'use 127.0.0.1 or 0.0.0.0'. 0.0.0.0 keeps loopback working for the watchdog, the app and the jobs. If interface-specific binding is ever needed, also keep a loopback listener (for example a second uvicorn socket) and test the watchdog against it.

## C3-logic-unchanged-05 [minor] Moving to the new origin resets the per-device 'seen' markers, so the first app visit replays alert history and badges
- verify: not verified (minor/nit)
- file: ui/lib/alerts.ts:21
- area: prefs hydration / new-origin initial state · reproduced: False
- evidence: readSeen() returns '' when suryadhana.alerts.seen.v2 is absent. WatchMonitor.tsx:124-129 then treats every history hit as fresh: a 20 s toast plus a native notification for each. AlertsBell.tsx:20 shows the whole 30-item feed as unread, and the NewsDock badge resets too. All three keys are LOCAL by design (ui/lib/prefs/keys.ts:31-35) and are never migrated. P11 makes those toasts visible for the first time. Live /api/alerts currently has history=0, so there is no impact today.
- failure: The owner sets a few alerts this week, they fire, and only afterwards does the owner first open WTCH in the app. Every past hit pops again as a toast and a macOS notification, as if new. The inbox badge shows up to 30 unread items that were already read in the browser.
- fix: On an origin's first sync run (meta null, empty legacy snapshot), set the three seen markers to 'now' or to the newest server timestamp before first render. Alternatively, add a 'migrate once' class so the legacy import carries them without syncing them afterwards.

## C3-logic-unchanged-06 [minor] The desktop window shows two contradicting NSE session states on trading holidays
- verify: not verified (minor/nit)
- file: ui/components/desktop/TitleStrip.tsx:85
- area: duplicated session logic (desktop chrome) · reproduced: True
- evidence: The page header uses a weekday-only rule (MarketCommandHeader.tsx:35-42: 'NSE OPEN' from 09:15 to 15:30 on any weekday). The new TitleStrip uses session.ts nseSession() with holidays from /api/market/eco-calendar. Live GET /api/market/eco-calendar?back=0&ahead=45 lists HOLIDAY on 2026-11-10 and 2026-11-24, both Tuesdays.
- failure: On 10 Nov 2026 at 10:00 IST the app shows 'NSE OPEN' in green in the header and 'NSE CLOSED · holiday' in the title strip at the same time. The browser shows only the header. The conversion has introduced a second market-session rule that disagrees with the first.
- fix: Use one session function for both: either the header adopts session.ts with the holiday list (a small, deliberate UI fix, to be called out), or the strip shows the header's state. Add a unit test pinning both to the same answer for 2026-11-10 10:00 IST.

## C3-logic-unchanged-07 [minor] In the app, price-alert notifications beyond 20 per minute are rejected; the browser path has no limit
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/commands.rs:97
- area: notifications behaviour (desktop vs browser) · reproduced: False
- evidence: shell_notify rejects with 'rate limited (20 notifications per minute)' (commands.rs:97-104; limiter created at lib.rs:631, shared by every window). WatchMonitor.tsx:124-129 calls notify() once per fresh hit. The browser branch, platform/index.ts notify(), fires a Notification for every hit. The in-page toast still shows, and the master-controller's Mac and Telegram announcement is independent.
- failure: On a gap-down open, 25 alert levels cross in the first minute. The browser shows 25 notifications; the app shows 20 and drops 5, with only a console warning.
- fix: Coalesce instead of rejecting: after the limit, show one '+N more price alerts' summary per window of time, or queue and deliver later. Alternatively, have WatchMonitor batch hits into one notification per check.

## C3-logic-unchanged-08 [minor] ui_perf.py does not put prefs sync into readonly mode, so a run against live :8010 writes the owner's prefs store
- verify: not verified (minor/nit)
- file: scripts/ui_perf.py:381
- area: QA tooling vs live prefs · reproduced: True
- evidence: measure_cold() creates `browser.new_context(...)` and adds INIT_SCRIPT, which never sets localStorage 'suryadhana.prefs.mode'. ui_audit.py, parity.py and probe.new_qa_context all default to readonly (probe.py:90-105). prefs_inventory.md §3 says QA tools that drive live :8010 must set readonly.
- failure: The PM measures AC-13 with `scripts/ui_perf.py --base http://127.0.0.1:8010`. Each fresh context mounts 42 pages, and the defaults that pages persist on mount (watchlist '[]', rsch.sel, omon, comp, goldPreOpen day blank, fund filters) are uploaded as provisional imports to data/ui_prefs.sqlite. The design prevents them from overwriting real values, but they become what the owner's first app launch adopts before migration, which makes C3-01 worse.
- fix: Create the contexts with scripts/desktop_qa/probe.new_qa_context (readonly by default), or prepend `localStorage.setItem('suryadhana.prefs.mode','readonly')` to INIT_SCRIPT and add a --prefs-mode flag.

## C3-logic-unchanged-09 [nit] On :3000 (next dev) the health monitor triggers a 404 every 10 s, and ui_audit.py still defaults to :3000
- verify: not verified (minor/nit)
- file: ui/components/desktop/health.ts:80
- area: dev mode / ops docs · reproduced: False
- evidence: probeUiApi falls back from /health (a Next 404 page) to /api/health, which ui-api does not have, so every probe is a 404 that the monitor counts as 'alive'. That is one console 'Failed to load resource' error and one ui-api 404 access-log line every 10 s per dev tab. Separately, scripts/ui_audit.py:187 defaults to --base http://localhost:3000, and CLAUDE.md's documented audit command will target a server that the switchover stops.
- failure: After switchover, `$P scripts/ui_audit.py` as documented fails because nothing listens on :3000. In dev (`start frontend`), the console fills with 404s, which hides real errors.
- fix: Add a GET /api/health alias in ui-api that returns the same body as /health (a pure addition), and probe it first. Change ui_audit.py's default --base to http://127.0.0.1:8010 when P4–P14 are applied, and update CLAUDE.md.

## C3-logic-unchanged-10 [nit] P11 and the font self-hosting change what the browser shows (toasts now visible, Greek σ from a system font)
- verify: not verified (minor/nit)
- file: ui/tailwind.config.ts:7
- area: browser-visible presentation changes not covered by parity · reproduced: True
- evidence: P11 adds './context/**' to Tailwind content. ToastContext's 17 missing utilities now exist, so toasts that were transparent at the left edge under the header now render top-right at z-9999. This includes WatchMonitor's 20 s price-alert toasts (WatchMonitor.tsx:127). The :3000 build lacks P11, so parity does not see it. Self-hosted JetBrains Mono ships only the latin and latin-ext subsets (ui/public/fonts/README.md:22-23), while the UI uses 'σ' 24 times across 9 files (RiskDashboard, OptionPricer, BacktestPanel, …), which previously came from Google's greek subset.
- failure: The owner sees new toasts covering the right end of the header for 20 s per alert, and slightly different σ glyphs in volatility labels. These are presentation changes, but undeclared to the owner as behaviour changes.
- fix: List both in the release notes and IMPROVEMENT_LOG as intentional browser-visible changes. Add JetBrains Mono's greek subset woff2 (about 10 kB) with its unicode-range, so σ keeps the same face.

### strengths
- Trading and business logic is provably untouched. Nothing in shared/, alpha_lab/, services/data-service/ or services/execution-service/ has an mtime after 24 Oct 10:38, and neither do scripts/master_controller.py, scripts/live_execution.py or services/ui-api/backtest_engine.py. Under services/ui-api/routers only the new prefs.py is newer. The only newer files under scripts/ are new QA and build tooling, and no job references them.
- ui-api API semantics are preserved by construction and by test. Old (backup) vs new main.py went through a 31-case TestClient matrix with no lifespan. Results were identical for /api 404 envelopes, POST to an unknown path, 405, HEAD, OPTIONS and CORS preflight from :3000 and from :8010, the trailing-slash 307, /docs and /metrics. The OpenAPI diff is exactly the 6 new paths. The UI fallback is installed as router.default rather than a Mount, so it cannot shadow routes.
- All 6 Next route handlers that the static export drops (/api/analytics/backtest/stream, /api/analytics/wfo-backtest/stream, /api/ml/train/stream, /api/pipeline/{ml,rl}-stream/{job_id}, /api/telemetry/logs/stream) are thin passthroughs to the same ui-api paths, which exist in the live OpenAPI with the same methods. The single rewrite targets ui-api only, and UI code uses relative /api (axios baseURL '') and a same-origin WebSocket URL.
- D3's call-site ports were applied by a uniqueness-asserted script whose old and new text matches D3.md §2. Each browser branch in ui/lib/platform is the removed code verbatim (Notification-if-granted, anchor download with 1 s revoke, window.open noopener), still synchronous inside the user gesture. The link interceptor and the window.open override install only when isDesktop() is true.
- D4 P7/P8 are safe for page logic. No tab component uses a construct that suspends (no lazy(), use(), useSearchParams or Suspense), so removing the dynamic() Suspense boundary for resolved modules changes only timing. An AST scan of components/, lib/ and context/ found no import-time side effects, so the warm-up loads code but fires no API calls.
- The PM's 25 Oct integration matches the patch documents exactly. A diff against ~/.suryadhana_pm_backups shows only D4 P1–P11, D3 1a–1d and D1 P1–P3. No dependencies were added (ui/package.json and requirements.txt are unmodified).
- The prefs design keeps an empty origin from overwriting the server: legacy values go through a fill-only import and other never-synced values through a provisional import. QA contexts run in readonly mode, which is why the live store is still empty after today's audit and parity runs. D3's 107 client checks pass when re-run.
### not checked
- No browser was run (per the brief). Behaviour inside WKWebView, and whether native 'storage' events cross Tauri windows (pins.ts relies on this), were not observed. C3-02 was reproduced with the real sync engine in node, not in a browser.
- The pre-program versions of D3/D4's directly edited files are not in the PM backups. I reconstructed them from the builders' transcripts: D3's edit script, and D4's cat of the original layout.tsx and global-error.tsx. The first 203 lines of globals.css were confirmed only by line count and the 'append-only' marker, not byte-for-byte.
- I did not run the 42-page audit or parity myself. AUDIT_DONE was not present during my review, and parity.log was still in progress (Chromium rows only).
- Rust code (desktop/src-tauri) was read only where it affects UI behaviour (notification limiter, data store, ⌘1–9 page map, which matches ALT+1–9). I did not do a security or ACL review.
- I did not test whether the :3000 browser's legacy snapshot exists in the owner's real browser profile, so I cannot say whether the first :3000 visit after 11:07 will import everything. I inferred it from code, and the D3 E2E covers it.
- Per-tab API request counts in perf_baseline_3000.csv against perf_export_after.csv differ on 8 of 84 tab/engine pairs (mcxgold, watch, ipo, …). This looks like poll-timing noise, but I did not confirm it with a controlled run.
- I did not review the PM's scratch build_ui.fixed.sh or the gates/ directory.

# C1-desktop-native — SHIP-WITH-FIXES

The shell itself is well engineered. The remote capability is least-privilege and checks the exact origin. The macOS menus are real (the Edit menu uses the predefined items, the Go menu has all 42 pages plus ⌘1–9, and the Window and Help menus are registered with the app). Single instance, session restore, per-window geometry and quit-via-Apple-Event are proven by the relaunch drill. The app log contains no secrets.

The basic login flow works: the boot page polls every second and enters the terminal by itself. Six problems would still stop it feeling like a professional Mac product, and I rate each one major:
1. **Login.** Around every login the boot page turns red after 15 s and pushes START STACK. In the logs I read, the watchdog took about 98 s to 3 min 43 s to bring ui-api up. Start Stack runs `launchctl kickstart -k`, which kills the watchdog's start in progress, so clicking it can delay the terminal by up to about 2 minutes. The 22 Oct macOS privacy (Desktop-folder) block on Python never shows on the boot page.
2. **Crashed pages.** If a window's web-content process dies, the window just goes black. Nothing recovers it, because no termination handler is registered.
3. **Status dots.** The shell sends status every 30 s when nothing changes, but the UI marks status stale after 20 s. The title-strip service dots go grey and the UI's fallback health monitor switches on and off on every cycle.
4. **NIFTY in the menu bar.** It keeps the last quote forever while ui-api is up, even when data-service is down. It has no closed or stale marker.
5. **Downloads.** Saves through `shell_save_download` (CSV, Excel and in-page download links) give no feedback at all on success or failure. Nobody listens to the download event. The real ~/Downloads folder and its macOS privacy prompt were never exercised.
6. **Alerts.** Price, filing, results, move and morning/close notes still come from `osascript`, so they show as Script Editor and clicking opens Script Editor. When the watch page is open in a window, each price-alert crossing also fires a second, SuryaDhana banner.

The minor findings are notification noise and wrong text, the 12 s page-load timeout, the Launch-at-Login marker and plist, the notification permission that always reports granted, the pending UI_API_HOST block, the Start Stack fallback running Python under the app's privacy permissions, crash visibility, fullscreen ⌘W, window placement and tabbing, and boot-page accessibility.

Nothing is a blocker. Still unverified on the real account: Launch at Login, boot paint time, real notification banners and real ~/Downloads writes.

## C1-desktop-native-01 [major] At every login the boot page tells the owner to Start Stack while the watchdog is still booting it, and Start (`kickstart -k`) kills that in-flight run
- verify: ['REAL->major']
- file: desktop/boot/boot.js:17
- area: launch-at-login / boot page / stack control · reproduced: False
- evidence: boot.js:17 sets DOWN_ACTIONS_AFTER_S = 15. At boot.js:99-101 the page then switches to the red 'down' state: 'Terminal unreachable for N s. The watchdog restarts core services every 2 min; start the stack now', with START STACK as the primary button.

stack.rs:84-87: Start Stack runs `/bin/launchctl kickstart -k gui/<uid>/com.suryadhana.watchdog`. `man launchctl` says: '-k If the service is already running, kill the running instance before restarting'.

scripts/stack_watchdog.sh, at login:
- sleeps 30 s;
- runs the macOS privacy preflight;
- starts data-service, then ui-api, then master-controller, each with `timeout 300 start-local.sh start <svc>`;
- a run that finds start-local.sh already running logs 'deferring' and exits.

I checked that GNU timeout puts itself in its own process group (pid 65980, pgid 65980). A killed watchdog therefore leaves its start running as an orphan, and the restarted run defers to it.

Observed start times (.logs/watchdog.log):
- Mac booted 10:57:20 today; ui-api started 10:58:58.
- 24 Oct run began 15:37:09; data-service took 108 s; ui-api up at 15:40:52.

lib.rs:575 passes `--autostart`, but nothing reads it.

.logs/watchdog.log 2026-10-22 09:25:17: 'preflight FAILED: python cannot start from launchd (macOS Desktop-folder permission)'. boot_status (commands.rs:254-277) has no field for watchdog state, paused markers or preflight result.
- failure: The owner logs in. The app and the watchdog start together.
- At t=15 s the boot page goes red with START STACK as the primary action.
- He clicks it at t≈40 s, while data-service is still starting. The watchdog run is killed. data-service finishes as an orphan, the restarted run sees start-local.sh and exits, and ui-api and master-controller wait for the next 120 s interval. The terminal appears about 2 minutes later than if he had done nothing.
- A click during the 30 s debounce restarts the debounce.
- On a day like 22 Oct, the real cause is the Desktop-folder privacy block. The page still only says 'start the stack now', which hits the same block, and never says what to allow.
- fix: 1. Start Stack: use `launchctl kickstart` without `-k`, and treat 'already running' as success.
2. Add watchdog state to boot_status:
   - whether `.pids/watchdog/lock` exists, or `launchctl print` shows state = running;
   - whether start-local.sh is running;
   - the paused markers;
   - the last line of .logs/watchdog.log, with 'preflight FAILED' mapped to step-by-step steps for System Settings › Privacy & Security › Files and Folders.
3. Use `--autostart` or system uptime: for about 5 minutes after login, show 'Starting the stack after login · data-service ✓ → ui-api … → master-controller' and hide Start while the watchdog is active.
4. Replace the '~30–60 s' text with the observed 1–4 min.

## C1-desktop-native-02 [major] A crashed web-content process leaves a terminal window permanently black; no termination handler is registered
- verify: ['REFUTED->not-a-defect']
- file: desktop/src-tauri/src/lib.rs:570
- area: crash/hang behaviour · reproduced: False
- evidence: - grep of desktop/src-tauri/src finds no on_web_content_process_terminate.
- Tauri 2.12.5 offers Builder::on_web_content_process_terminate (app.rs:1910) and installs a handler only if the app provides one (manager/webview.rs:338-357). By default wry does nothing (wkwebview/navigation.rs:121-130).
- navigator_tick only acts on Boot and Loading windows (windows.rs:719-733), so a Terminal window whose web-content process died stays Terminal.
- ui-api stays healthy, so no banner or health signal appears.
- Self-test: 5 WebKit helper processes used 292 MB right after the checks. The stack also holds a 4 GB DuckDB.
- failure: Under memory pressure (several windows with live ticks next to DuckDB) or after a WebKit crash, a window's web-content process is killed. The window turns plain black (its background colour) with no title strip, banner or error. Status, goto and build-changed events can no longer reach it. The owner sees a 'frozen' terminal. Only View ▸ Reload (⌘R) recovers it, and nothing suggests that. A hidden main window can be dead when reopened from the tray.
- fix: Register `.on_web_content_process_terminate(|wv| …)`:
- log the crash;
- set the window back to Loading and call navigate_to_terminal or reload, with backoff;
- after 3 crashes in 5 minutes, show the boot page in a 'page crashed — Reload' state and send a notification.

Add a drill that `kill -9`s a test instance's com.apple.WebKit.WebContent process and checks that the window recovers.

## C1-desktop-native-03 [major] Title-strip service dots go grey ('status is stale') for 5–15 s of every ~30 s because the shell's 30 s status interval is longer than the UI's 20 s stale threshold
- verify: ['REAL->major']
- file: ui/components/desktop/PlatformShell.tsx:46
- area: window chrome / status contract · reproduced: False
- evidence: Shell side, lib.rs:333-346: a status event is sent when something changes (latency excluded) or after 30 s without one. on_health_update runs every 5 s in steady state, so with nothing changing a status event arrives every 30–35 s. README:109 documents this 30 s interval.

UI side:
- PlatformShell.tsx:46 sets STATUS_STALE_MS = 20_000.
- :215 computes `statusStale = Date.now() - statusAt > 20 s`.
- TitleStrip.tsx:101-108 draws stale status as grey dots with the tooltip 'status is stale (shell poller silent)'.
- PlatformShell.tsx:124-133 sets `fallback` after 20 s of silence, which starts the browser HealthMonitor; the next status event stops it.
- The bridge calls shell_status only once, at mount (lib/platform/index.ts:70). The comment at PlatformShell.tsx:45 assumes the shell 'pushes on change and at most every 5 s'.
- failure: On a weekend or a quiet market, with all 3 services up, every window's UI/DATA/CTRL dots are green for about 20–25 s, then grey ('stale') for 5–15 s, about every 30–35 s, indefinitely. The fallback health monitor starts and stops on the same cycle, sending extra /health probes. A trader sees the health strip show 'unknown' about a third of the time and stops trusting it.
- fix: Make the two sides agree. Either:
- send the status event every 10 s from Rust (it is a cheap eval), or
- set STATUS_STALE_MS to at least 2.5× the interval (e.g. 75 s), and have the UI call shell_status when 10 s pass with no event.

Add a contract test that the interval is shorter than the stale threshold.

## C1-desktop-native-04 [major] Menu-bar NIFTY freezes at the last quote indefinitely when data-service fails, and never shows closed or stale
- verify: ['REAL->major']
- file: desktop/src-tauri/src/health.rs:532
- area: tray / menu-bar ticker · reproduced: False
- evidence: - health.rs:532-538: `if nifty.is_some() || !s.status.ui_api.up { s.status.nifty = nifty }`. The comment says 'keep the last good quote through a single failed fetch', but the old value is kept through every failure while ui-api is up.
- services/ui-api/routers/markets.py:722-732: /api/market/nifty-live returns 503 when data-service is unreachable.
- parse_nifty (health.rs:149-153) ignores the payload's `time` field. A live GET today (Sunday) returned time '23-Oct-2026 15:30'.
- The tray title is 'NIFTY 22,600.0 ▼0.39%' (self-test tray_present), with no closed marker.
- The same value is sent to every window as ShellStatus.nifty and shown on the boot page.
- failure: On a trading day, data-service dies or wedges at 11:00 while ui-api stays up (the 15 Oct DuckDB out-of-memory incident is the precedent). The menu bar keeps showing e.g. 'NIFTY 24,180.5 ▲0.42%' for hours and looks live, so the owner reads a frozen number as the market. On weekends and holidays, Friday's close looks like a live quote.
- fix: - Track consecutive failures and the last successful fetch. After 2 failures (30 s), or when the quote's `time` is more than ~3 min old during market hours, show 'NIFTY —' or add a stale mark.
- Outside NSE hours, add 'CLOSED' or use a neutral glyph.
- Set ShellStatus.nifty to null while the quote is stale; this stays within contract v1.

## C1-desktop-native-05 [major] Downloads saved through the bridge give no feedback, no Show-in-Finder and no error; the real ~/Downloads privacy path was never tested
- verify: ['REAL->major']
- file: desktop/src-tauri/src/commands.rs:147
- area: downloads · reproduced: False
- evidence: - shell_save_download (commands.rs:146-187) writes the file and returns {path} but never calls shell.notify. Only the WebKit on_download path notifies (windows.rs:530-536).
- The bridge sends in-page `<a download>` clicks through shell_save_download (lib/platform/index.ts:341-342, `void downloadUrl(...)`; self-test 'bridge_download').
- CSV and Excel exports call `void saveDownload(...)` (components/terminal/index.tsx:348, lib/backtestExport.ts:77).
- The 'suryadhana:download' event (index.ts:136-146) has no listener anywhere in ui/app, ui/components or ui/lib. Failures only reach console.warn.
- Nothing offers Show in Finder.
- Both self-test download checks wrote to a temp folder (meta.isolated_state_dir). ~/Downloads is protected by macOS privacy controls for non-sandboxed apps, and an ad-hoc-signed app's grant is tied to each build's signature.
- failure: The owner clicks EXPORT CSV in the app. Nothing visible happens: no toast, no notification, no Dock bounce. He clicks again and gets 'stocks-2026-10-25 (1).csv', then '(2)'. If macOS denies Downloads access or the disk is full, the export fails with no message at all.
- fix: - On success, post a native notification 'Saved <name> to Downloads' and/or show a UI toast from DOWNLOAD_EVENT with a Show in Finder button. This needs a new contract command, e.g. shell_reveal_download(path), limited to ~/Downloads (opener reveal_item_in_dir).
- On failure, show the reason. Map EPERM to 'Allow SuryaDhana to access Downloads in System Settings › Privacy & Security › Files and Folders'.
- Test the real ~/Downloads path in the post-install drill.

## C1-desktop-native-06 [major] Scheduler notifications (price alerts, filings, moves, morning/close notes) still go through osascript as 'Script Editor'; the app duplicates price alerts only while the watch page is open
- verify: ['REAL->major']
- file: scripts/master_controller.py:736
- area: notifications · reproduced: False
- evidence: - _notify_mac (master_controller.py:736-746) runs `/usr/bin/osascript -e 'display notification …'`.
- It is called for price alerts (773), filings (868), results (915), market moves (1011), the closing note (1158) and the pre-market note (1200).
- The shell never reads GET /api/alerts/feed (services/ui-api/routers/alerts.py:143); grep of desktop/src-tauri/src finds nothing.
- The app's own price-alert banner fires only while WTCH is mounted: WatchMonitor.tsx:126-128 → alerts.ts:80-90, whose check() returns hits 'fired here or by the scheduler' → notify(h).
- PLAN §1 promises native notifications for price alerts.
- failure: TCS crosses a level at 11:02 with WTCH not open. The banner comes from 'Script Editor' with a generic icon, and clicking it opens Script Editor instead of the WTCH page. If WTCH is open in some window, the same crossing shows two banners (Script Editor and SuryaDhana). The SuryaDhana notification settings do not control the most important alerts.
- fix: - The shell polls GET /api/alerts/feed every 30 s, de-duplicates by `at` (kept in state.json), and posts native notifications by kind. A click opens WTCH, EVTS or BRIEF via goto.
- master-controller skips osascript while the app reports it is alive (for example, the app touches data/.desktop_alive every minute and the controller checks the modification time is under 3 minutes).
- WTCH check() stops re-notifying hits that the shell has already posted.

## C1-desktop-native-07 [minor] Service notifications are noisy and sometimes wrong: 3 'is back up' banners at every login, and 'the watchdog restarts…' after a deliberate Stop
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/health.rs:283
- area: notifications · reproduced: False
- evidence: - SvcTracker treats a service that is down at app start as its baseline and then emits CameUp when it comes up (health.rs:283-312). The unit test at health.rs:785-788 asserts exactly this.
- lib.rs:365-380 posts one notification per service, throttled per service.
- The 'went down' text always says 'The watchdog restarts core services within ~2 min' (lib.rs:374), even for services with a .pids/paused marker. stack_watchdog.sh candidates() skips paused services, so the watchdog never restarts them.
- failure: - Every login, because the app starts before the stack: three banners, 'data-service is back up', 'ui-api is back up' and 'master-controller is back up'.
- After the owner confirms Stop Stack…: three 'X is down — The watchdog restarts core services within ~2 min' banners, which is false because the services are paused.
- fix: - Treat 'down at app start' as 'starting': no notification, or one 'Stack is up' summary when all three are up.
- Check .pids/paused/<svc>: either suppress the banner or say 'stopped on purpose (paused) — Start Stack to resume'.
- Combine transitions that happen together into one notification.

## C1-desktop-native-08 [minor] The 12 s load timeout waits for the page's full load, not the first commit, and can bounce a working terminal window back to the boot page in a loop
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/windows.rs:725
- area: window lifecycle / boot navigator · reproduced: False
- evidence: - windows.rs:9 documents 'nothing committed within 12 s ──► Boot'.
- But a window becomes Terminal only on PageLoadEvent::Finished (windows.rs:564-577), and the timeout check (725-731) ignores Started.
- wry maps Started to didCommitNavigation and Finished to didFinishNavigation (wkwebview/navigation.rs:17-25 and 53-59). didFinishNavigation is the window load event, which also waits for iframes and images.
- The TradingView iframe (components/news/NewsChart.tsx:129-132, used by Compare and the news terminal) can hold back that event.
- So can ui-api's startup threads (main.py:81-87: Breeze login, 4 GB snapshot copy, gold warm-up).
- failure: A window is restored on COMP while the external network is slow and the TradingView iframe hangs, or it loads at login while ui-api is copying its 4 GB snapshot. The page commits and renders, but at 12 s the shell sends it back to the boot page ('RECONNECTING'), reloads it 3 s later, and repeats about every 15 s. The terminal itself is fine.
- fix: Record a 'committed' flag on Started for the ui origin and time out only loads that never committed, as documented; or switch the window to Terminal on commit. Never navigate away from a committed terminal page.

## C1-desktop-native-09 [minor] Launch-at-Login can turn itself back on, and the toggle does not reflect System Settings
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/lib.rs:405
- area: launch at login · reproduced: False
- evidence: - first_run_autostart (lib.rs:395-418) uses Session.autostart_initialized in state.json to decide whether it has already run.
- Session::load returns defaults when state.json is missing or corrupt (windows.rs:181-186).
- README:185 says 'Reset window layout | quit, delete .window-state.json and state.json'.
- auto-launch 0.6.0 in LaunchAgent mode writes Label 'SuryaDhana', an empty AssociatedBundleIdentifiers array, and no ProcessType or KeepAlive. is_enabled() only checks that the plist file exists (auto-launch macos.rs).
- repair_autostart rewrites the plist only when its target no longer exists (lib.rs:442-447). README:59 says 'Run the installed copy first'.
- failure: - The owner turns Launch at Login off. Later he follows the README's reset-layout step, and the next launch silently turns it back on.
- If he disables SuryaDhana under System Settings › General › Login Items › Allow in the Background, the menu and tray still show ✓ Launch at Login while nothing starts at login.
- If a build-directory copy is ever launched before the installed one, login keeps starting that copy until it is deleted.
- fix: - Store the first-run marker somewhere the reset recipe doesn't touch (a config.json key or a separate file).
- Prefer SMAppService.mainApp: auto-launch already supports it, so call it directly since the plugin doesn't expose it. The toggle then mirrors System Settings, and the item shows the app's name and icon.
- If staying with the LaunchAgent: write AssociatedBundleIdentifiers=[ai.suryadhana.terminal] and ProcessType=Interactive, and have build_desktop.sh --install point the plist at the installed copy.

## C1-desktop-native-10 [minor] Notification permission always reports 'granted', so WTCH says 'desktop notifications on' even when macOS has them off
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/commands.rs:118
- area: notifications permission flow · reproduced: False
- evidence: - tauri-plugin-notification 2.7.0 (desktop.rs:193-207) returns PermissionState::Granted unconditionally from both permission_state and request_permission. The self-test notes 'always Granted'.
- WatchMonitor.tsx:67-68 and 256-258 show 'desktop notifications on' when the permission is 'granted', so the ENABLE button never appears.
- The backend is mac-notification-sys 0.6.15, which uses the deprecated NSUserNotificationCenter (objc/notify.m:79).
- The self-test only records notifications; no real banner was ever observed.
- No click handler is registered: clicking a banner activates the app but shows no window when main is hidden.
- failure: The owner has notifications off for SuryaDhana (or never allowed them for the ad-hoc-signed app). WTCH still says 'desktop notifications on', and service-down, ICICI and alert banners are dropped silently.
- fix: - Read the real authorization state through UNUserNotificationCenter getNotificationSettings (objc2-user-notifications), and call requestAuthorization on first use.
- At minimum, return 'default' and show 'Managed in System Settings ▸ Notifications ▸ SuryaDhana' with a button that opens x-apple.systempreferences:com.apple.Notifications-Settings.extension.
- Add a tap handler that shows the main window or the relevant page.
- Add a manual drill that checks a real banner appears.

## C1-desktop-native-11 [minor] The pending UI_API_HOST block accepts a specific LAN IPv4, which removes the loopback listener the app and the watchdog depend on
- verify: not verified (minor/nit)
- file: /private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/a24906e4-7b64-46ba-b24b-14c536f43922/scratchpad/pm/pm_lan.py:25
- area: pending PM block (LAN access) · reproduced: True
- evidence: I ran the block's case statement on its own:
- 192.168.1.5 → `uvicorn --host 192.168.1.5`
- 0.0.0.0 → 0.0.0.0
- '' → 127.0.0.1
- 'lan' and '::' → ignored

The docstring invites 'an IPv4 address'. Binding one LAN IP drops 127.0.0.1, but these all use loopback:
- SuryaDhana.app: ui_url is http://127.0.0.1:8010, and config.rs rejects any non-loopback URL;
- stack_watchdog.sh `is_up`: curl http://localhost:8010/health;
- start_py_service's 60 s health wait: curl localhost:$port.
- failure: The owner sets UI_API_HOST=192.168.1.5 in .env to reach the terminal from the iPad.
- start-local.sh reports 'did not become healthy'.
- Every 2 min the watchdog finds :8010 listening ('already running') but is_up fails, and sends a throttled 'FAILED to start: ui-api' Telegram.
- SuryaDhana.app stays on the boot page showing 'ui-api DOWN'.
- fix: Accept only 127.0.0.1 or 0.0.0.0 (0.0.0.0 covers both loopback and the LAN) and reject everything else with the message. Document the macOS firewall prompt for Python when binding 0.0.0.0.

## C1-desktop-native-12 [minor] When the watchdog agent is not loaded, Start Stack launches the stack's Python under the app's macOS privacy permissions and reports success at once
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/stack.rs:88
- area: stack control · reproduced: False
- evidence: - stack.rs:3-4 says 'The app NEVER runs the stack's Python itself (TCC…)'.
- But when the watchdog agent is not loaded, start_plan (stack.rs:88-95) spawns `/bin/bash <repo>/start-local.sh start` as the app's child process.
- start-local.sh:166 then runs /Users/sudheer/Desktop/jupyter_env/bin/python. macOS attributes that Desktop-folder access to SuryaDhana.app, an ad-hoc build whose grant is tied to each build's signature.
- execute() returns Ok for a Spawn step right after fork (stack.rs:173-214), and the boot page then says 'Start requested … Services come up within ~30–60 s'.
- The watchdog hit this same block on 22 Oct 09:25.
- failure: The watchdog agent is unloaded (for example after `install_launch_agents.sh uninstall` or a failed reinstall). The owner clicks Start Stack. Python blocks on a Desktop-folder consent prompt attributed to SuryaDhana, or is denied. Each service waits 60 s and fails, logged only in .logs/desktop-stack.log, while the UI keeps saying the start was requested.
- fix: Launch through launchd instead (`launchctl bootstrap` or `submit` of the watchdog plist), or disclaim responsibility when spawning (responsibility_spawnattrs_setdisclaim). Alternatively drop the fallback and show 'run scripts/install_launch_agents.sh install'. Either way, poll for the outcome and report failure.

## C1-desktop-native-13 [minor] Rust panics are never logged and a crashed app is not relaunched
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/lib.rs:553
- area: crash/hang behaviour and logs · reproduced: False
- evidence: - There is no std::panic::set_hook anywhere (grep).
- The stderr log target is added only in self-test and debug builds (lib.rs:565-567).
- The Launch-at-Login plist has no StandardErrorPath, so panic messages from a login-launched app are lost; only a .ips crash report remains.
- The plist has no KeepAlive (auto-launch build_launch_agent_plist), and the app has no relaunch mechanism.
- failure: A panic in a menu or tray handler or a poller aborts the app mid-session. The menu-bar ticker and notifications disappear without notice, the app log says nothing about why, and the app stays down until the next login or a manual launch.
- fix: - Install a panic hook that logs the location and message with log::error! and flushes.
- Relaunch on crash but not on ⌘Q: KeepAlive {SuccessfulExit=false} in the plist, or the SMAppService route.
- Optionally show a tray line 'Last crash: <time>'.

## C1-desktop-native-14 [minor] ⌘W on a fullscreen main window hides it without leaving fullscreen, which can leave an empty black Space
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/windows.rs:592
- area: window lifecycle (fullscreen) · reproduced: False
- evidence: - windows.rs:592-595: CloseRequested on main calls prevent_close and hide().
- tao's set_visible(false) is a plain orderOut with no fullscreen handling (tao platform_impl/macos/window.rs:643-647).
- The window-state plugin saves FULLSCREEN (lib.rs:581), so main often restarts in fullscreen.
- Electron had to special-case exactly this AppKit behaviour.
- failure: Main is in native fullscreen on display 2. The owner presses ⌘W or the red button. The window is hidden while its fullscreen Space stays, leaving an empty black Space he has to swipe away; reopening from the Dock or tray can then look confusing.
- fix: If is_fullscreen(), call set_fullscreen(false) and hide only after the exit transition finishes, or minimize instead. Cover it in the PM drill.

## C1-desktop-native-15 [minor] ⌘N places new windows relative to main, not the focused window; window minimum size, focus targeting and drag regions need polish
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/windows.rs:411
- area: window lifecycle / multiple displays · reproduced: False
- evidence: - New term windows cascade from MAIN's position (windows.rs:411-420), not the focused window's. The window-state plugin then applies whatever geometry an earlier window with the same term-N label had.
- min_inner_size(1100, 700) and the default 1600×1000 (398-399) are not clamped to the screen.
- focused_label falls back to MAIN when the app is not active (325-331), so tray and menu actions un-hide main instead of targeting the last-used window.
- On Dock reopen, main is shown even when the only other windows are minimized (lib.rs:703-709).
- The window can only be dragged from elements with data-tauri-drag-region. BootGate (ShellNotices.tsx:88), app/global-error.tsx and ui-api's 503 page have none.
- Zoom level is not saved.
- failure: - Working in term-3 on display 2, ⌘N opens the new window on display 1 next to main, or at a stale saved position.
- On a 1920×1080 monitor, two terminal windows can't be tiled side by side (2 × 1100 > 1920), and Move & Resize ▸ Left/Right fails. That limits the 'open another panel with ⌘N' workflow.
- If a page fails to start and shows global-error, the window can't be moved.
- fix: - Cascade from the focused window and clamp to that monitor's work area.
- Don't apply saved geometry to brand-new ⌘N windows; only to session restore.
- Track the last-focused window via WindowEvent::Focused.
- Lower the minimum size if the UI can reflow (e.g. 900×600).
- Add a drag region to BootGate, global-error and the 503 page.
- Save zoom per window.

## C1-desktop-native-16 [minor] macOS automatic window tabbing is left on, which conflicts with the custom title strip
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/windows.rs:396
- area: window lifecycle (tabbing) · reproduced: False
- evidence: - tao 0.37.2 turns automatic tabbing on by default (platform_impl/macos/window.rs:118) and disables it only when asked (306-307).
- Tauri 2.12.5 exposes only tabbing_identifier (webview/webview_window.rs:839).
- The window builder (windows.rs:396-409) sets neither.
- The 32 px TitleStrip and the traffic-light inset (14, 18) assume there is no tab bar.
- failure: With the macOS default 'Prefer tabs when opening documents: In Full Screen', ⌘N in a fullscreen terminal opens the new window as a native tab. AppKit then draws a tab bar in the title area over or under the custom strip, and the Window and View menus gain Merge All Windows and Show Tab Bar. Session restore later brings the tabs back as separate windows.
- fix: Call NSWindow.setAllowsAutomaticWindowTabbing(false) once at startup (objc2, on the main thread), or give each window a unique tabbingIdentifier and set tabbingMode to disallowed.

## C1-desktop-native-17 [minor] Boot page: progress not announced to VoiceOver, error text can't be copied, raw command text shown, and a missing UI build is shown as a stack outage
- verify: not verified (minor/nit)
- file: desktop/boot/index.html:46
- area: boot page accessibility and wording · reproduced: False
- evidence: - #progress (index.html:46) has no aria-live, and focus doesn't move to the action buttons when they appear.
- boot.css sets user-select:none on html and body, so error text can't be copied.
- boot.js:137 shows the raw step log ('cleared paused marker …; ran launchctl kickstart -k gui/501/com.suryadhana.watchdog') and promises '~30–60 s'; the observed time was 98–223 s.
- When ui-api answers 503 because there is no UI release, the page still says 'start the stack now' and offers Start, which can't help.
- The footer (index.html:60) says closing keeps SuryaDhana in the menu bar, also in term-N windows, where closing destroys the window.
- The blinking cursor ignores prefers-reduced-motion.
- The boot strip is 38 px tall while the traffic lights are positioned for 32 px, so they sit about 3 px off centre.
- failure: - A VoiceOver user hears nothing while the stack starts.
- The owner can't paste the exact error into a note.
- A missing UI release looks like the whole stack is down, with no hint to run build-ui.
- fix: - Add role=status and aria-live=polite to the progress line, and focus the primary action when it appears.
- Allow selecting text in .message and #ui.
- Use plain wording, e.g. 'Asked the watchdog to start any stopped service'.
- When ui_detail reports HTTP 503, show './start-local.sh build-ui' or rollback instead of Start.
- Use per-window footer text, add a reduced-motion rule, and make the strip 32 px.

## C1-desktop-native-18 [nit] Menus miss standard Mac items (Settings… ⌘,, Find ⌘F, ⌘+), and several shortcuts and tray lines are rough
- verify: not verified (minor/nit)
- file: desktop/src-tauri/src/menu.rs:90
- area: native menus and tray polish · reproduced: False
- evidence: - No Settings… ⌘,: config.json can only be edited by hand, and changes need a relaunch.
- No Find ⌘F for long tables.
- Zoom In is bound only to 'CmdOrCtrl+=', so ⌘+ (⇧⌘=) does nothing.
- The GO Bar item puts '(⌘K in the terminal)' in its title (menu.rs:162) instead of a real shortcut.
- Hitting the window limit sends a notification (menu.rs:272-275) instead of a beep or alert.
- Double-clicking the title strip always zooms, ignoring System Settings' 'Double-click a window's title bar to'.
- Tray status lines are aligned with spaces in a proportional font, and the NIFTY title changes width as its digits change.
- Start Stack stays enabled, and still says 'starting any service that is down', when all three services are up.
- failure: A Mac power user reaches for ⌘, or ⌘F and gets nothing. ⌘+ doesn't zoom. Other menu-bar items shift every 15 s as the NIFTY title changes width.
- fix: - Add Settings… (open config.json, or a small settings window, with hot reload).
- Add Find via window.find or a UI find bar.
- Add a CmdOrCtrl+Shift+= alias for Zoom In.
- Give the GO Bar item a real ⌘K shortcut that dispatches the command-bar event.
- Beep (NSBeep) when the window limit is hit.
- Honour the System Settings double-click action (AppleActionOnDoubleClick).
- Disable Start Stack when all three services are up.

### strengths
- Least-privilege inter-process calls (IPC): the remote capability is added at runtime for exactly the configured origin, every command re-checks its caller's origin, and the localhost↔127.0.0.1 alias is converted to the one canonical origin. The boot page has a strict content-security policy (CSP), checked by the self-test.
- The boot → terminal navigator is careful. It waits for the boot page to paint, polls every 1 s while a window waits, has a 'reconnecting' mode, and never yanks a loaded terminal window away when ui-api blips; the UI's own banner handles that.
- Real macOS menus: App menu (About, Services, Hide, Hide Others, Show All, ⌘Q); Edit with the predefined clipboard items, so ⌘C/⌘V reach inputs in the web view; View with zoom and Enter Full Screen; a Go menu with all 42 pages and ⌘1–⌘9 (matching the UI's ALT+1–9); Window and Help menus registered with the app. ⌘K is deliberately left to the page.
- The relaunch drill (desktop/src-tauri/target/relaunch-drill-20261024.log, 14/14 PASS) proves single instance (the second launch exits in about 500 ms), session restore of main + term-3, per-window geometry, quit via Apple Event saving state, the first-run marker, and repair of a stale Launch-at-Login path, all in an isolated HOME.
- Native window titles '<CODE> · <label> — SuryaDhana' come from the UI, which helps Mission Control, the Window menu and VoiceOver. The 'new build' detection compares against the page's own build, so it never prompts spuriously.
- Stack control is careful. Stop needs a native confirm and is refused inside the IST restart-freeze windows (computed in Asia/Kolkata whatever the Mac's timezone). Start clears only the 3 paused markers, inside .pids/paused. The normal path runs no Python.
- Secrets hygiene holds: the ICICI connection-status body is reduced to two booleans, and grep of the real app log (~/Library/Logs/ai.suryadhana.terminal/suryadhana.log) found 0 secret-like strings.
- Download filenames are cleaned (letters, digits and . _ - only), get Finder-style ' (n)' suffixes and are created exclusively (O_EXCL); downloads from foreign origins are refused. Window-state restores positions only onto connected monitors. Mutex poisoning is tolerated throughout.
### not checked
- I did not launch SuryaDhana.app (forbidden by the brief). So I did not see the native chrome: traffic-light position, dragging, tray rendering, real notification banners, ⌘C/⌘V in inputs, fullscreen/tabbing behaviour, or the WebKit context menu. Findings 02, 10, 14 and 16 are based on code and AppKit/WebKit knowledge, not observed.
- Real Launch at Login on the owner's account is not verified (AC-5): ~/Library/LaunchAgents/SuryaDhana.plist does not exist yet and `launchctl print gui/501/SuryaDhana` reports no such service. Login timing, the macOS 'Background Items Added' prompt, and the Allow-in-the-Background toggle are untested.
- Boot paint under 500 ms (AC-6/AC-13) was never measured: both self-test reports have screen_locked=true and skipped boot_page_painted.
- Writes to the real ~/Downloads and the macOS privacy prompt for it, and real notification delivery on macOS 26 through the deprecated NSUserNotificationCenter: the self-test used a temp folder and only recorded notifications.
- AC-10 drills (ui-api restart mid-session, UI release swap with open windows, sleep/wake): pending with the PM. I reviewed only the code paths; the shell has no wake observer and relies on polling.
- I did not run cargo test or compile the crate, to avoid CPU load during the PM's live 42-page audit. Unit-test behaviour is cited from source (e.g. health.rs:785-788). The only command I reproduced is the UI_API_HOST validation logic, in isolation.
- No browser runs (static brief), and the PM's AUDIT_DONE marker was absent throughout. The title-strip staleness flicker (finding 03) is derived from the two timing constants, not observed in a window.
- Idle CPU and memory with a hidden main window (its page keeps its live data streams and polling running) and App Nap effects on the poller.
- The Start Stack and Stop Stack end-to-end paths against the live stack (forbidden). Finding 01's kill/defer sequence is inferred from the launchctl man page, the watchdog script, my GNU timeout process-group check and watchdog.log timings.

# C1-trader-ux — BLOCK

From a Bloomberg user's chair, the terminal already looks the part. It is amber on black with function codes on every page. The GO bar handles ticker plus function (RELIANCE DES/FA/ERN/HP/OMON/DEAL), there are 42 pages, the BRF/OMON/MCXG/MOV/PRE pages say plainly when the market is closed, and the parity audits are clean. What stops me calling it production-grade:

(1) There is no error isolation. One unexpected field in one API response replaces the whole window with a minified stack trace. The title strip, header, GO bar and navigation all go. I reproduced this in WebKit.

(2) The resilience UX promises more than it does. After LINK UP the banner says "the terminal resumes on its own", but every panel that failed stays "Unavailable: Network Error". I saw this both in my drill and during the PM's real ui-api restart. Separately, one non-essential bootstrap call (enrichment-status) failing blocks all 42 pages with a wrong "ui-api may be starting up" diagnosis while every light is green.

(3) Status is contradictory or misleading:
- The chrome shows two clocks (1 s apart in one frame), two session clocks with different rules (the header will say green "NSE OPEN" on the 10 Nov and 24 Nov holidays), two brands and two sets of service lights.
- The footer "● READY" stays green during LINK DOWN.
- The title-strip dots go grey 27% of the time in steady state, because the shell's 30 s heartbeat is longer than the UI's 20 s staleness limit.
- On a "PAPER ONLY" product the PORT page (Alt+0) shows the legacy engine as LIVE with the LIVE⚡ toggle selected.
- PORT and BRKR print the ICICI login URL with its API key in plain text. That URL is now also in the audit screenshots under reports/, which git does not ignore.

(4) Prices are misreported or formatted inconsistently. Desk "Last" rounds to 1 decimal: CUPID 311.65 shows as ₹311.70→₹311.7 (MOREPENLAB 125.99 shows as ₹126.0). Several price columns have ragged decimals. NIFTY appears with 0, 1 or 2 decimals on the same screen.

(5) Keyboard-first operation has gaps:
- Esc does not close the stock window, although the footer and the help both promise it.
- Typing a ticker does nothing until you press / first.
- There is no page history or BACK. Browser Back leaves the terminal.
- The desktop help still teaches Alt 1…0 and never mentions ⌘1–9, ⌘N or ⌘W.

(6) At the app's own default 1600×1000 window, header row 1 overflows on every page I sampled: REFRESH is cut off and a horizontal scrollbar appears.

Finding 01 is a blocker. Most of the rest are small, UI-only fixes. None of them touches trading logic.

## C1-trader-ux-01 [blocker] No per-page error boundary: one malformed API field crashes the whole terminal window to a raw minified stack trace
- verify: ['REAL->major', 'REAL->blocker']
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/app/global-error.tsx:1
- area: resilience / error states · reproduced: True
- evidence: grep finds no componentDidCatch/getDerivedStateFromError/ErrorBoundary/error.tsx anywhere in ui/. The only boundary is app/global-error.tsx, which replaces the root layout. Repro (crash.py, WebKit, simulated shell): I client-side-mocked ONE GET (/api/market/eco-calendar?back=0&ahead=7, used by Brief.tsx:179 `new Map((eco.data?.events ?? []).filter(...))`) to return events as an object, then navigated DESK→BRF. At +3 s the result was {exc:true, strip:false, header:false}, with body text "⚠ Client-side Exception (null!=(q=null==(a=tl.data)?void 0:a.events)?q:[]).filter is not a function…" followed by 9 lines of chunk URLs. Screenshot: /private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/a24906e4-7b64-46ba-b24b-14c536f43922/scratchpad/crit/C1-trader-ux/shots/crash-6s.png. The project log already records an earlier render crash of this kind ("RSK tz TypeError" in the RSCH what's-new entry).
- failure: A backend change, a partial or empty payload, or a null in any of about 200 render paths (42 pages, the stock window, hover cards) during market hours. The trader's window becomes a stack-trace page: no title strip (in the app that also removes the drag region), no GO bar, no menu-driven navigation (no goto listener), and all page state is lost. Every page is one bad payload away from this.
- fix: In ui/app/page.tsx, wrap each `{view === '<tab>' && …}` render (and StockDetailModal, NewsTerminal and CommandBar) in a small TabErrorBoundary keyed by tab. Its fallback is a terminal Panel: "<CODE> failed to render · RETRY · details", with the stack hidden behind a disclosure and the error posted to ui-api's log. The chrome (PlatformShell, MarketCommandHeader, footer) stays mounted. Reset the boundary on tab change and on reconnect. Reduce global-error.tsx to the last-resort case and stop showing stack traces by default. Remove ErrorCatcher.tsx, which is itself marked "DIAGNOSTIC TOOL. Remove once the root cause is identified", or gate it behind a dev flag.

## C1-trader-ux-02 [major] After LINK UP, panels that failed during the outage stay 'Unavailable: Network Error'; the banner's 'the terminal resumes on its own' is false
- verify: ['REAL->major']
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/desktop/ShellNotices.tsx:30
- area: resilience / connection banner · reproduced: True
- evidence: Drill (scenarios.py step 7, client-side abort of /api/** plus shell status ui_api.up=false). The LINK DOWN banner appeared correctly. At 32 s BRF panels showed "Loading…" indefinitely while the header still showed NIFTY 22,600.00 with the "● NSE" chip. After unrouting and status up=true, 21 s later: strip dots green and banner gone, but every BRF panel still read "Unavailable: Network Error" and Scheduler read "offline" (recovered_body_has_error=true; shots/s-recovered-21s.png). Real-world confirmation: during the PM's actual ui-api restart (new pid 42312, 11:49:02) my 1100×700 run captured DERV showing only "▲ Load failed  [RETRY]" (shots/d1100-derivatives.png). Banner copy ShellNotices.tsx:30: "the terminal resumes on its own · your pages keep their state". PlatformShell.tsx:159-163 flips to 'recovered' but tells no page.
- failure: The 18:30 EOD or ui-api watchdog restarts ui-api, or the Mac wakes from sleep. The trader returns to a green-lit terminal whose panels all say Network Error or Load failed. They must find each Retry button or switch tabs, and they may trust stale or missing panels because the chrome says everything is healthy.
- fix: On the down→recovered transition, dispatch `suryadhana:reconnected` from PlatformShell. In page.tsx, remount the active tab (bump a `key`) or have the shared useLoad/Pending helpers re-run any load that ended in error. While down, render panel state as "LINK DOWN · last data HH:MM" instead of an endless "Loading…". Change the copy to what is actually guaranteed.

## C1-trader-ux-03 [major] Every page is gated on 3 bootstrap calls (incl. a 0.9 MB 1,500-stock list); one failing non-essential call blocks all 42 pages with a wrong diagnosis
- verify: ['REAL->major']
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/app/page.tsx:598
- area: loading / bootstrap gating · reproduced: True
- evidence: page.tsx:221-244 awaits getDashboardSummary, getEnrichmentStatus and listStocks(0,1500) together. page.tsx:598-604 renders only "Backend unreachable" for every view if any of them fails. curl shows /api/stocks/list?limit=1500 = 934,658 B per window open. gate.py: a client-side 503 on /api/dashboard/enrichment-status alone, opening MCXG (which never uses it). At 8 s the page shows "BACKEND UNREACHABLE ▲ Request failed with status code 503: ui-api may be starting up (auto-retry every 10 s)" while the strip shows UI/DATA/CTRL green and the header DATA/DB green. It then alternates between "Connecting…" and "Unreachable" every 10 s (shots/gate-8s.png, gate-15s.png).
- failure: A slow or failing dashboard or enrichment endpoint (DuckDB busy during the 18:30–21:15 EOD window, a data-service sub-route error) keeps the trader out of DESK, MCXG, OMON and RSK, none of which need those calls. The message blames ui-api, which is healthy.
- fix: Mount the active tab immediately. Fetch dashboard and enrichment lazily, only for OVRV, EQS and the footer, and the stock universe only for EQS. Show a non-blocking footer chip on failure ("universe stats unavailable"). Keep the blocking screen only for a real ui-api outage, as reported by the shell or the health monitor.

## C1-trader-ux-04 [major] On a PAPER-ONLY terminal, PORT (Alt+0) shows the engine as LIVE with the LIVE⚡ toggle selected and a big LIQUIDATE & HALT button
- verify: ['REAL->major']
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/LivePortfolio.tsx:829
- area: paper-only posture / page semantics · reproduced: True
- evidence: GET /api/execution/status → mode "LIVE", state "ACTIVE" (secret fields excluded). The PORT header chip (LivePortfolio.tsx:829) renders a green "LIVE". The mode toggle (243-281) shows "LIVE ⚡" selected in emerald, while the banner on the same page says "running in PAPER mode only" and the subtitle says autopilot OFF. Seen in PM audit chromium/positions.png and my d1680-positions.png and d1100-positions.png. PORT is strip slot 10, so Alt+0 opens it. Its labels also disagree: strip and menu say "Portfolio", the page says "Execution Engine".
- failure: The owner, or anyone glancing at a shared screen, sees LIVE in green on a terminal that everywhere else says PAPER. That undermines trust in the PAPER posture, and the selected LIVE toggle plus "Yes, Go LIVE" flow sits one hotkey away.
- fix: UI only: render PORT's mode chip as "LEGACY · DORMANT" (grey). Show the engine's reported mode as a warning line ("engine reports LIVE · autopilot OFF · no broker session · nothing can be sent") and disable the toggle in the UI. Take PORT out of the Alt+0 slot (tabList) in favour of RSK or CHRT. Owner decision: set the dormant legacy engine's mode to PAPER (a state change, not a trading-rule change).

## C1-trader-ux-05 [major] PORT and BRKR print the full ICICI login URL (with the API key) as on-screen text; the audit screenshots now hold it under reports/, and git does not ignore them
- verify: ['REAL->minor']
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/LivePortfolio.tsx:659
- area: broker banner / secret hygiene in UI · reproduced: True
- evidence: LivePortfolio.tsx:659-661 renders `{status.login_url}` as plain monospace text. PortfolioSummary.tsx:229-233 renders it as the link's visible text. The PM's audit captures reports/desktop_app/switchover/audit_8010/{chromium,webkit}/positions.png (and broker.png) show the URL with its api_key parameter in full; I am not reproducing it. `git check-ignore` on those PNGs returns nothing (exit 1), so a `git add reports/` would commit them. PLAN §2.6 says the login_url must never be shown or logged.
- failure: Screen share, screenshot, the audit artifacts or a future commit expose the broker API key. On PORT the URL is not even clickable, so the user has to select and copy it.
- fix: Replace the raw URL in both components with a "LOG IN TO ICICI ↗" button that calls openExternal(login_url) and never renders the URL text (mask it as api_key=•••• if it must be shown). Add reports/desktop_app/switchover/**/*.png (or all audit screenshot dirs) to .gitignore. Make scripts/ui_audit.py mask or blank PORT and BRKR captures. Delete or redact the existing captures.

## C1-trader-ux-06 [major] Duplicated and contradictory status chrome: 2 brands, 2 clocks (1 s apart), 2 session clocks with different holiday rules, 2 sets of service lights, page identity ×3, footer READY stays green during LINK DOWN
- verify: ['REAL->major']
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/MarketCommandHeader.tsx:35
- area: desktop chrome / status consistency · reproduced: True
- evidence: Retina crop (shots/s-retina-chrome.png): the strip shows "11:52:24 IST" and the header shows "11:52:23" in the same frame. Strip: "◆ SURYADHANA │ DESK DECISION DESK … NSE CLOSED WEEKEND … ● UI ● DATA ● CTRL". Header right below: "◉ SURYADHANA ▸ DESK … ● DATA ● DB ● ICICI … WEEKEND". The page header then repeats "DESK DECISION DESK". The header's sessionState (MarketCommandHeader.tsx:35-43) has no holiday input. Running both functions in node for 2026-11-10 10:30 and 2026-11-24 14:00 IST (holidays from /api/market/eco-calendar) gives strip="CLOSED HOLIDAY" and header="NSE OPEN" (green). The header also has a CLOSING state the strip lacks (15:45: strip "AFTER CLOSE", header "CLOSING"). page.tsx:708 footer `loadError ? 'OFFLINE' : 'READY'` reflects only the first load: during my outage drill it read "● READY" (green) under a red LINK DOWN banner (shots/s-outage-7s.png). D4 noted the double clock but left it in place.
- failure: On Diwali-Balipratipada (10 Nov) the most prominent session chip says green NSE OPEN while the title strip says CLOSED · HOLIDAY. During an outage the footer says READY. A professional cannot tell which indicator to trust. About 75 px of the most valuable screen area repeats the same facts.
- fix: In desktop mode (html[data-sd-shell=desktop]), drop the header's brand, clock, session chip and DATA/DB lights; keep NIFTY, ICICI, alerts and refresh. In browser mode, have the header reuse session.ts nseSession() with the ECO holidays and the shared useSecondTick(). Derive the footer status from PlatformShell's banner phase (export it through context) rather than from loadError.

## C1-trader-ux-07 [major] Title-strip service dots go grey ('status is stale (shell poller silent)') ~27% of the time in steady state: UI stale threshold 20 s < shell heartbeat 30 s
- verify: ['REAL->major']
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/desktop/PlatformShell.tsx:46
- area: title strip / shell status cadence · reproduced: True
- evidence: desktop/src-tauri/src/lib.rs:333-338 re-broadcasts an unchanged status only when `since >= 30 s`; change_key ignores latency and time. PlatformShell.tsx:46 sets STATUS_STALE_MS = 20_000 and :123-134 flips `fallback` (starting the browser /health monitor) after 20 s of silence. heartbeat.py emulates the lib.rs cadence exactly (a push every 30 s). Over 75 s, all three dots were grey for 20 samples (t=21-27 s and 52-58 s), with tooltip "ui-api :8010: status is stale (shell poller silent)", and the fallback /health probe fired every cycle (counter 0→1→2). Steady state covers most of the time: after 15:30, overnight, weekends and holidays, whenever NIFTY does not change.
- failure: Every evening and weekend the strip's health lights flicker grey for about 8 of every 30 seconds, and the tooltip claims the shell poller is silent. The professional learns to ignore the health lights, which defeats them on the day of a real outage.
- fix: Set STATUS_STALE_MS to at least 1.5× the heartbeat (≥ 45 s), or lower the Rust heartbeat to 10 s, or have the UI call the non-blocking cached `shell_status` every 10 s when no event arrived. Add a test that pins the two constants together.

## C1-trader-ux-08 [major] Displayed prices don't match the exchange: Desk 'Last' rounds to 1 dp; price columns elsewhere have ragged decimals; NIFTY shown with 0/1/2 dp on one screen
- verify: ['REAL->minor']
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/DecisionDesk.tsx:152
- area: number formatting · reproduced: True
- evidence: DecisionDesk.tsx:152 `render: w => fmtInr(w.close, 1)`. The API (/api/desk/status plans[0].summary.watchlist) gives CUPID 311.65, MOREPENLAB 125.99, FCL 57.45, PAISALO 76.41. The screen shows ₹311.7, ₹126.0, ₹57.5, ₹76.4 (PM chromium/desk.png, webkit/desk.png, my d1680-desk.png). StockTable.tsx:98-101 and 10 other sites (PreOpen, IndexMembers, DealsMonitor, AlertsCenter, LiveMovers, PriceHistory, kit) use `toLocaleString('en-IN', {maximumFractionDigits: 2})` only, so a right-aligned CMP column reads ₹189.41 / ₹1,125.3 / ₹33,100 / ₹363.05 (EQS) and PRE IEP reads 1,187 / 46.65 / 194.5. NIFTY appears as 22,600.00 (header), 22,600.0 (BRF/MOV intraday, IndexIntraday.tsx:91), 22,600 (MOV tile) and tray "NIFTY 22,600.0". CMDT shows "within ₹300 of ₹144,376" (Western grouping from the server text) next to "₹1,44,376". ALFA shows ₹3910.30 with no grouping. OSTR payoff axis mixes ₹1.3L and ₹88.9k (StrategyBuilder.tsx:112).
- failure: A trader reads ₹311.7 for a stock that closed at ₹311.65, an impossible value on the 0.05 tick grid, and ₹126.0 for ₹125.99. Ragged decimals break the decimal alignment a pro scans by, and mixed L/k units on one axis invite misreads by orders of magnitude.
- fix: Add one kit formatter, fmtPx(v) = toLocaleString('en-IN', {minimumFractionDigits: 2, maximumFractionDigits: 2}), and use it for every equity, index and commodity price column (Desk Last, EQS CMP, PRE IEP/prev, MEMB, DEAL, ALRT, MOV, HP, ALFA). Index levels always 2 dp, including the tray. Use one unit per axis or column (all ₹ L or all ₹ cr), and format server-built verdict strings client-side in Indian grouping.

## C1-trader-ux-09 [major] Keyboard gaps vs Bloomberg: Esc doesn't close the stock window, no type-to-GO, no page history/BACK (Back exits the app), desktop help still teaches Alt 1…0
- verify: ['REAL->major']
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/StockDetailModal.tsx:202
- area: keyboard-first navigation · reproduced: True
- evidence: scenarios.py (WebKit). stock_window_closes_on_esc=false: StockDetailModal has no Escape handler (the only 'Escape' handlers are CommandBar, NewsTerminal, ChartStudio, DataTable and MoreMenu), yet the footer (page.tsx:717 "ESC CLOSE") and help (CommandBar.tsx:304 "Esc · Close any window") promise it. type_to_go_opens_bar=false: typing TCS with no focus does nothing. page.tsx:161-166 setView uses history.replaceState, so after BRF→DESK→MKT history.length=2 and browser Back went to about:blank, leaving the terminal. menu.rs defines no Back/Forward (⌘[ / ⌘]) and no Find. Help card (shots/s-help.png, CommandBar.tsx:301) lists "Alt 1 … 0" and no ⌘1–9/⌘N/⌘W; the footer says "ALT+1…0 PAGES" while the boot page says "⌘1–⌘9 pages". Bloomberg mnemonics land wrong: GP→GPIL/GPPL tickers, TOP→SHOPERSTOP, MOST→ticker 'MOST', BACK→BTST.
- failure: The core loop is ticker ⟶ stock window ⟶ Esc ⟶ next ticker. Here Esc does nothing and the user must mouse to the ✕. After hopping TCS → OMON → DEAL there is no way back except retyping. Muscle memory from Bloomberg (GP, TOP, MOST, N, <MENU>) misfires.
- fix: Add a keydown Escape handler in StockDetailModal (when no input is focused) calling onClose. Make any printable keystroke outside inputs open the GO bar seeded with that character. Use pushState in setView with a popstate handler, and add Go ▸ Back ⌘[ / Forward ⌘] to menu.rs. In desktop mode, show ⌘1–9 / ⌘N / ⌘W / ⌘K in the footer and help. Add aliases GP→CHRT (or TICKER GP → chart), TOP/N→NEWS, MOST→MOV, BRIEF→BRF, and give exact code matches priority over substring matches.

## C1-trader-ux-10 [major] Header row 1 overflows at the app's default 1600×1000 window (REFRESH clipped, labels wrap, page-level horizontal scrollbar); also at 1680 on long page names and at 1100
- verify: ['REAL->major']
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/MarketCommandHeader.tsx:341
- area: layout at the app's window sizes · reproduced: True
- evidence: Measured in WebKit with the simulated shell. At 1600×1000 (windows.rs:398 inner_size), header row-1 scrollWidth vs clientWidth was 1606/1600 (BRF), 1646 (RSCH), 1643 (OVRV), 1644 (DEXP), 1653 (GBOX), 1660 (WHSE), 1657 (CMDT), and the document scrollWidth exceeded clientWidth on all 7 (metrics-mid.json). Screenshot d1600-warehouse.png shows "↻ RE" cut at the right edge, "NIFTY / 50" and the alerts bell on two lines, and the tape cut off. At 1680, the PM's screenshots show the same wrap on RESEARCH, PORTFOLIO, OVERVIEW, BACKTEST, GLASS-BOX, EXPLORER and COMMODITY. At 1100×700 row 1 overflows on MKT (1101), RSCH (1112) and PORT (1117). Separately, DESK's momentum table is clipped at 1680 in both engines (header "NEXT E", chips "FUND R"/"RESULT" cut).
- failure: On first launch, at the app's own default size, the top bar shows a horizontal scrollbar, a half-visible REFRESH button and wrapped labels. That is the first impression of 'Bloomberg-grade'. The Desk's next-event column is unreadable without discovering a hidden horizontal scroll.
- fix: Give row-1 children `whiteSpace: nowrap` and `minWidth: 0`, and let only the NIFTY block shrink. Raise the .t-hide-lg breakpoint (O/H/L, stock count, date) to about 1760 px, or drop the brand and page name in desktop mode (see -06). Check widths of 1100, 1280, 1440, 1600 and 1680 in ui_audit. On DESK, give the watchlist DataTable fixed column widths or truncate Industry so NEXT EVENT fits, and show a scroll affordance.

## C1-trader-ux-11 [minor] 160 px of stacked chrome; at the 1100×700 minimum only 541 px (77%) is content; EQS rows ~51 px tall
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/app/page.tsx:466
- area: density / vertical real estate · reproduced: True
- evidence: metrics: strip 32 + header 106 (row1 44 + tape 26 + page strip ~36) + footer 22 = 160 px. Content height is 891 px at 1050 and 541 px at 700, plus 24 px more when the watchlist bar is non-empty. At 1100×700, DESK shows only the KPI tiles and an empty "NO TRADES THIS MONTH" panel above the fold; the momentum watchlist sits below it (d1100-desk.png). EQS (StockTable) rows are about 51 px, so about 12 rows fit on a 1050 px screen (PM stocks.png), while FUND on the same data is a dense ~26 px grid.
- failure: On a laptop or a quarter-screen tiled window, the trader scrolls for every table. EQS shows a fraction of what a Bloomberg EQS screen shows.
- fix: In desktop mode, merge the strip and header row 1 into one 32 px bar (with -06). Make the macro tape optional. Add a dense mode (row padding 3-4 px, the kit's `dense`) and apply it to StockTable. On DESK, put the watchlist above the empty-trades panel when there are 0 trades.

## C1-trader-ux-12 [minor] Header '↻ REFRESH' on every page starts a 5-year yfinance download of 1,500 stocks with no confirm, next to page-level '↻ REFRESH' buttons that only reload the page
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/MarketCommandHeader.tsx:371
- area: dangerous affordance · reproduced: False
- evidence: MarketCommandHeader.tsx:371-375 → page.tsx:359-370 handleRefresh → lib/api.ts:15-16 `client.post('/api/dashboard/refresh', {universe:'nse_1500', years:5})`. DESK (PM desk.png) shows both buttons on screen, with the same label and glyph and different blast radius. I did not click it (POST).
- failure: A Bloomberg user presses the prominent amber REFRESH to update the screen and instead queues a heavy universe-wide download. It opens an indigo panel reading "Downloading 5yr OHLCV…" and loads data-service, possibly during the EOD window.
- fix: Rename it "DATA ⟳" (or move it to OVRV/PIPE), add a confirm that states scope and duration, and disable it inside the 18:30–21:15 freeze. Keep "REFRESH" for reloading the current page's data.

## C1-trader-ux-13 [minor] Closed-market and offline state not marked consistently: tray NIFTY, '● NSE', 'WS LIVE', 'STREAMING', SYS 'NOW', no Muhurat session
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/src-tauri/src/health.rs:217
- area: stale-data / market-closed semantics · reproduced: True
- evidence: Sunday 25 Oct. Tray title (health.rs:217-236, self-test "NIFTY 22,600.0 ▼0.39%") ignores the payload's `time` ("23-Oct-2026 15:30"), so the menu bar shows Friday's move all weekend with no CLOSED marker. The header shows the NIFTY change with a cyan "● NSE" live-style chip and keeps showing it unchanged during an outage (s-outage-brief-32s.png). ALFA shows "● WS LIVE" (AlphaDiscoveryDesk.tsx:352) and LiveMonitorBar shows "● STREAMING" (LiveMonitorBar.tsx:57-59): both mean the socket is connected, not that data is flowing. SYS shows 'NEXT JOB XGBoost + RL Inference Cycle NOW' with a 09:15–15:30 schedule on a Sunday. The MOV panel title reads "today vs previous close" for the last session. The hover card always says "≈1 min delayed". session.ts:54 treats every Sunday as CLOSED, although the app's own MCXG page lists "2026-11-08: Muhurat trading (Sunday evening special session)".
- failure: On weekends and holidays (most of the clock), the menu bar and several chips present Friday's numbers as live. During Muhurat trading on Sun 8 Nov every NSE session indicator will say CLOSED · WEEKEND while the market is open.
- fix: Add one shared marketState (from nseSession + holidays + a special-sessions list), and when closed suffix every last-price display with "CLOSE 23-OCT". Tray: "NIFTY 22,600.00 ▼0.39% · CL". Rename socket chips to "SOCKET OK" or show "NO TICKS (CLOSED)". Make SYS next-run weekday-aware and mark dormant jobs. Support special sessions in session.ts via the ECO feed.

## C1-trader-ux-14 [minor] ⌘−/⌘= zoom scales the CSS title strip but not the native traffic lights; zoom-out collides them with the wordmark; zoom isn't persisted
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/src-tauri/src/windows.rs:781
- area: desktop window / zoom · reproduced: False
- evidence: windows.rs:781-797 calls set_zoom (WKWebView pageZoom) on the focused window. The strip's 84 px left inset (globals.css:282) and its 32 px height are CSS px and scale with zoom; the traffic lights (windows.rs:399-402, x=14, zoom button ends at 74 px per D4) do not. Arithmetic: at 0.9 the inset is 75.6 px (touching), at 0.8 it is 67.2 px (the ◆ mark and 'S' sit under the green button), and at 0.5 (the clamp) it is 42 px with a 16 px strip, so the lower half of each light sits over the header row. WinInfo.zoom starts at 1.0 and is not part of the saved Session, so it resets on every relaunch. Not observed natively (the app may not be launched).
- failure: A user on a non-Retina external monitor zooms out to fit more columns and the wordmark disappears under the traffic lights. A user who zooms in for legibility (see -15) must redo it after every restart.
- fix: Send the zoom factor to the page (a shell event, or `window.devicePixelRatio` changes) and set the strip's padding-left to calc(84px / zoom) and its height to calc(32px / zoom). Alternatively clamp zoom-out at 1.0 and offer a UI density setting instead. Persist zoom per window label in state.json.

## C1-trader-ux-15 [minor] Dim text token #475063 is 2.4–2.55:1 on the terminal backgrounds and is used for 9–9.5 px labels throughout
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/news/format.ts:13
- area: typography / contrast · reproduced: True
- evidence: WCAG contrast computed for --t-dim/T.dim #475063: 2.55 on the strip (#020304), 2.49 on bg, 2.40 on panel. (--t-muted is 4.5–4.8:1 and is fine.) `color: T.dim` appears 334 times in ui/components and app; font-size 9/9.5 appears 115 times, plus the strip CSS (.sd-strip-k, .sd-strip-detail 9 px). Measured share of visible text elements under 10 px: 12–39% per page at 1680 and up to 41% at 1100 (metrics-big/small.json). Examples: strip 'NSE'/'IST'/build id, the footer brand, PRE's 'market closed today · showing the last session', panel hints.
- failure: Exactly the qualifying text (closed-market notes, as-of times, units) is the least legible on a non-Retina or bright-room display, so traders miss the very caveats meant to stop misreads.
- fix: Raise T.dim for text to at least #6a7487 (≥4.5:1) and keep the current value only for rules and borders. Set a 10 px floor for informational text. Promote as-of and closed notes to T.muted or T.amber.

## C1-trader-ux-16 [minor] Multi-window is clone-only: no 'open ticker/page in new window', no security deep link, each window repeats full chrome and polling
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/src-tauri/src/menu.rs:264
- area: multi-window workflow · reproduced: False
- evidence: menu.rs:264-276: ⌘N opens the focused window's tab. The only URL param is ?tab (page.tsx:158; pages.ts tabFromSearch), so a window cannot open on a security. Page tabs are <button>s (MarketCommandHeader.tsx:283), so ⌘-click or middle-click does nothing. ui/lib/platform newWindow() is reachable only through the anchor/window.open interceptor. The stock window is a single in-window modal. Session restore saves only ?tab (selftest: "/?tab=desk"). Per window the chrome polls every 5 s (NIFTY), 15 s, 30 s (3 calls), and 60 s (tape, news, alerts), regardless of market hours.
- failure: The classic layout (chart of TCS here, OMON for NIFTY there, DESK on monitor 2) requires ⌘N and then manual navigation in each window, and is lost on restart apart from the page. Eight windows multiply the background polling eightfold on a closed market.
- fix: Add deep links ?tab=charts&sym=TCS (and stock-window ?sym=), honoured on load and saved in the session. Make ⌘-click or middle-click on page tabs and TickerLinks call newWindow(tab, sym). Add 'Open in new window' to the stock window. Back off chrome polling when the market is closed or the window is hidden. Later: window-group security linking.

## C1-trader-ux-17 [minor] SVG charts scale their text with viewBox (axis labels ~17 px vs 9–11 px UI); OI-by-strike has no strike axis; overlapping labels; stock window off-style rounded
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/OptionChain.tsx:50
- area: charts / visual polish · reproduced: True
- evidence: DerivativesDesk.tsx:85 and OptionChain.tsx:33/58/101 use `viewBox` with width 100% and height auto, so fontSize 9-10 renders at about 16-17 px at 1680 (PM derivatives.png and options.png: 'Oct 21 … Oct 26', '70 / 16 / −38' oversized, non-round ticks). OiBars (OptionChain.tsx:50-75) labels only the first and last strike; other strikes appear only in a <title> on the call bar. OSTR payoff: 'BE 22324.9' and 'BE 22875.1' overlap, and x ticks are 19865/20948/… (non-round). Stock window: the SMA 200 legend is drawn over the red SMA 200 line, and the '14.91M' volume label covers a y-axis tick (s-stock-window.png). The stock window has about 16 px rounded corners because `md:rounded-2xl` (StockDetailModal.tsx:208) is not matched by the legacy skin's `.terminal .rounded-2xl`.
- failure: A derivatives user cannot read which strike holds the OI wall from the chart. Typography jumps between pages and window widths, and the stock window looks like a different app.
- fix: Render SVG axis text in a non-scaling overlay, or compute W from the container width (ResizeObserver) so 1 SVG unit = 1 px. Label OI strikes every N strikes plus the walls and ATM. Use 'nice' tick steps. Offset or collision-avoid the BE labels. Move the chart legend outside the plot. Add `.terminal .md\:rounded-2xl { border-radius: 2px }` (or use square classes).

## C1-trader-ux-18 [nit] Polish: duplicate step numbers, stale hard-coded date defaults, dev paths and emoji in UI copy, mixed minus glyphs, menu label, LAN access change
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/PipelineStudio.tsx:692
- area: copy / consistency · reproduced: True
- evidence: PipelineStudio.tsx:692-693: two tabs numbered '③' (Feature Inspector, Model Studio). GlassBoxStudio.tsx:39-40 defaults the range to 2025-09-01 → 2026-05-31, and MLEngineWorkspace.tsx:54-55 ends at 2025-12-31 (five months stale today). RiskDashboard.tsx:308 shows "Rules are read from CLAUDE.md…", and DESK shows "charges from shared/trading_costs.py". 🔍 (EQS Column Filters) and 🔌 (PORT banner) appear in a glyph-based terminal. fmtPct prints ASCII '-1.23%' while fmtSignedPct and the header print U+2212 '−'; units are written both 'cr' and 'Cr'. menu.rs:162 embeds "(⌘K in the terminal)" in the item title instead of an accelerator. The strip uses 'UI' for both the ui-api dot and the build chip. MCXG copy has a doubled "auto-login).)". Pending pm_lan.py makes ui-api loopback-only by default, so after switchover the iPad/phone URL (:3000) and localhost:3000 bookmarks stop working silently.
- failure: Small inconsistencies that a professional user reads as unfinished. A default GBOX render shows data ending five months ago. The owner's iPad loses the terminal after switchover without being told why.
- fix: Renumber the PIPE steps. Default date ranges to [today − N, today]. Replace dev paths with user-facing wording ("rules: Desk policy (owner-approved 2026-09-27)"). Swap the emoji for kit glyphs. Use U+2212 in fmtPct. Use one 'cr' casing. Set the ⌘K accelerator (or drop the parenthetical) and label the build chip 'BUILD'. Fix the typo. Add a line to the switchover notes and the start-local print_urls about UI_API_HOST=0.0.0.0 for iPad access (on a trusted LAN).

### strengths
- Consistent Bloomberg-style visual language across about 40 of the 42 pages: void black, amber accents, a JetBrains Mono data face with a Chakra Petch display face, 1 px square rules, uppercase micro-labels. Every page carries an amber function-code chip (BRF, DESK, OMON, MCXG, RSK…).
- The GO bar is genuinely terminal-grade. It takes the ticker-then-function grammar (RELIANCE → DES/FA/ERN/HP/SEAG/OMON/DEAL/TV/W), searches company names, keeps command recall with ↑, and opens with / or ⌘K. The ? help card lists every code. Shots: s-gobar-reliance.png, s-help.png.
- Honest closed-market messaging on the pages that matter most. BRF: 'NSE closed (weekend) · next session Mon, 26 Oct'. MKT: 'EOD 23 Oct 2026'. OMON: an EOD chip with 'NSE F&O bhavcopy 2026-10-23 · end of day'. MOV: 'market closed: last session'. PRE: 'book as of 23-Oct-2026 09:09:05'. MCXG: a CLOSED state with an 'opens in 21h 46m' countdown and its own MCX holiday calendar (including the 8 Nov Muhurat session). WEI: a last-print-age column.
- Indian number conventions are handled in most places: lakh/crore grouping (₹5,02,085, 1,03,32,756), ₹ L/cr units, and a ₹ glyph patched into the mono font so it renders the same in WebKit and Chromium. +/− colouring and tabular figures are in place.
- Tables are keyboard-navigable (click, then ↑↓ or j/k, Enter, Esc) and every DataTable has '⤓ CSV' export that goes to ~/Downloads in the app.
- The desktop shell basics are solid: no white flash, a black boot gate, the 32 px overlay strip with page code, IST clock, NSE session from the holiday feed, service dots and a NEW BUILD · RELOAD chip. The native menu has all 42 pages in 6 groups plus ⌘1–9, the tray shows NIFTY, health, ICICI and Desk NAV, and the connection banner is clear and shows outage duration.
- The 42-page parity is clean in Chromium and WebKit (parity.log: 42/42, no diff, no audit failures), and tab switches are fast once warm (0.01–0.06 s UI-ready for most pages in my WebKit run).
### not checked
- Native chrome inside the real SuryaDhana.app: traffic-light alignment, the drag region, how the native menu and tray look, notification banners, ⌘C/⌘V in inputs, and Window-menu titles. The brief forbids launching the app. I relied on the self-test JSON and a simulated __SURYADHANA_SHELL__/__TAURI_INTERNALS__ in Playwright WebKit (the same engine, not the same host). The zoom/traffic-light collision (-14) is inferred from code and arithmetic.
- Market-hours behaviour: live ticks, flash colouring, the OMON LIVE chain, the PRE auction at 09:00–09:15, Desk execution-day views, and the ICICI-connected states. Today is a Sunday and Breeze is expired.
- Clicking any state-changing control (header REFRESH, Desk PREVIEW NOW, PORT toggle/LIQUIDATE, alert creation, watchlist add, ENRICH). Their behaviour (-12, -04) is from code and the GET endpoints only.
- Sleep/wake reconnect, a real multi-monitor or multi-window layout, and session restore with 8 windows. These come from code and the PM's relaunch drill log only.
- A real WKWebView outage. My outage drill aborted requests client-side and faked the shell's down status. Separately, during the PM's actual ui-api restart and release swap (11:46–11:49), I observed DERV 'Load failed' (d1100-derivatives.png), and one tab switch in an ad-hoc probe did not become ready within 30 s. I did not capture what it showed, could not reproduce it in 5 later attempts, and do not report it as a finding.
- Screen-reader or VoiceOver accessibility, the light theme (if any), and iPad/phone layouts.
- A new UI release (20261025-114737) was published and ui-api restarted (pid 42312, 11:49:02) in the middle of my runs. The 1680 and 1100 captures were made on the 110718 build and the scenario, crash and gate runs on 114737. The findings do not depend on the build difference.

# C2-performance — SHIP-WITH-FIXES

The serving layer is fast and holds up under load. I measured static_ui.py live. index.html (gzip, no-cache) and a 73 kB hashed chunk (immutable) each answer in about 1 ms, and a 304 in 1.2 ms. First-load JS is 263,277 B gz against the 300 kB budget. While DEXP read a 352 MB parquet, the worst ui-api /live latency was 106 ms, so the event loop is not blocked. Tab-switch UI-ready p95 on the integrated :8010 is 40.8 ms in Chromium and 81 ms in WebKit. Cycling all 42 pages twice leaked no timers, listeners, sockets or DOM nodes. A burst of 8 windows restored at once was handled fine (/api/prefs p99 115 ms).

The problems are on specific pages and in idle cost:
(1) EQS takes 1.34 s to appear in WebKit, the app's engine. It then re-renders all 1,500 rows on every context change, every NIFTY tick (3 times each) and every row the mouse crosses.
(2) Every new window, restored window or reload still pays React's 300 ms Suspense throttle, about 510–570 ms in total. P7/P8 removed it for tab switches only.
(3) An endless "NEW" pulse in the news dock alone pushes an idle window past the 3 % CPU budget.
(4) Several server endpoints keep the data-settled p95 at 1.4–1.5 s, and DEXP adds about 830 MB of transient ui-api RSS per page click.
(5) The AC-13 RSS/CPU claim has no idle evidence, and my WebKit stand-in sits at 480–522 MB for one window.

The status-heartbeat mismatch, which turns the strip lights grey for about 16 % of the time, is confirmed on the served build. It is already fixed in the working tree (C1-desktop-native-03) and still has to be rebuilt.

Measurements: Chromium and WebKit through Playwright against live :8010 (GET only, prefs readonly, my own page's WS mocked for the tick tests), ps CPU-time deltas, CDP Performance metrics, and a 20-minute idle run. Scratch files: /private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/a24906e4-7b64-46ba-b24b-14c536f43922/scratchpad/crit/C2-performance/ (c2_harness.py, anim_probe.py, stall_test.py, perf_out/, *.json).

## C2-performance-01 [major] EQS re-renders all 1,500 rows on every hover, every NIFTY tick (3x) and every 30 s status poll; 1.34 s to show in WebKit
- verify: ['REAL->major']
- file: ui/components/StockTable.tsx:394
- area: UI rendering / EQS (StockTable) · reproduced: True
- evidence: ui_perf sweep on :8010 (scratch copy, readonly prefs): EQS is the only page over 400 ms even for UI-ready, at 1,340 ms in WebKit and 411 ms in Chromium. Causes in code: onMouseEnter={() => setHovered(stock.ticker)} (:394) is state on the whole table. useLiveQuotes() (:123) plus the flash effect (:128-153) gives 3 full renders per tick: the context change, setFlashMap (:144) and the clear 700 ms later. AppContext.tsx:326 passes an inline value object, and the 30 s refreshDataStatus (:249) always sets lastChecked: Date.now(), so every consumer re-renders, HomeContent and the table included. Measured with a mocked monitor WS (my page only), Chromium: idle EQS has 2 long tasks/min (max 114 ms); NIFTY ticks at 0.2 Hz (the data-service poller rate) give 36 long tasks/min, 3,675 ms/min, main thread 8.86 % busy; at 1 Hz, 36.8 % busy. WebKit at 0.2 Hz: 36 freezes/min, 3,941 ms/min blocked, max 165 ms. Each row the mouse crosses costs +78.6 ms (Chromium) / +123 ms (WebKit) p50, up to 163/210 ms. BRF under the same ticks stays at 1.3 % CPU, so the cost is specific to EQS.
- failure: In market hours the owner opens EQS in SuryaDhana.app (WKWebView). The page takes about 1.3 s to appear. Then the table freezes for about 110 ms three times every ~5 s (each NIFTY tick), and moving the mouse down the list repaints at about 5–8 fps.
- fix: No change to data or logic: (1) drop the hovered state and use CSS hover (e.g. tr:hover / hover:bg-[#131926]); (2) extract a React.memo row that takes only its own live/flash/watched props, and pass stable callbacks (useCallback for onRowClick and onWatchToggle in page.tsx StocksTab); (3) split AppContext into LiveQuotes / Watchlist / DataServiceStatus contexts with useMemo'd values, so ticks and the 30 s poll re-render only their consumers; (4) window the rows (react-window), or as a first step add content-visibility:auto with contain-intrinsic-size on <tr>.

## C2-performance-02 [major] Every new window, restored window or reload still pays React's 300 ms Suspense throttle (content at ~510–570 ms)
- verify: ['REAL->minor']
- file: ui/app/page.tsx:258
- area: Window open / restore latency (P7/P8 gap) · reproduced: True
- evidence: P8's warm-up starts 3 s after mount (page.tsx:258), but windows open deep-linked (/?tab=<id>, windows.rs terminal_url). The tab's module is therefore never resolved at first render: lazyTab (:41-51) falls back to the dynamic() Suspense path and React holds the skeleton for its 300 ms throttle. A rAF-sampled title/skeleton timeline on :8010 with a faked shell shows the skeleton phase lasting exactly ~300 ms. Chromium: RSCH skeleton 266→567 ms, DESK 211→503, RSK 230→526. WebKit: RSCH 228→526, DESK 221→530, RSK 227→521, MKT 211→513. The PM's own audit agrees: readyB is 435–651 ms on most deep-linked pages and 190–200 ms on the few that do not suspend (switchover/audit_8010.log, parity.log). Tab switches inside a window are at 21–30 ms p50. Before the skeleton, every page also waits ~200–260 ms on loadDashboard (dashboard summary, enrichment status, and the 934,658 B /api/stocks/list?limit=1500) via pageLoading (:204, :598), even pages that never use stock data.
- failure: The owner presses ⌘N for DESK, or launches at login and the app restores 3 windows, or clicks NEW BUILD · RELOAD, or a chunk error triggers recovery. Each window shows a skeleton for about 300 ms longer than needed, so opening a window costs 2–3× a tab switch.
- fix: Key the warmers by tab id and start the URL tab's import when the module first evaluates on the client: `if (typeof window !== 'undefined') { const t = new URLSearchParams(location.search).get('tab'); WARM[t]?.() }`. The boot gate plus the dashboard gate give it about 200 ms of head start, so lazyTab's `resolved` is already set when the tab first mounts and no fallback is shown. Optional: initialise `view` from the URL in the useState initializer (safe, because PlatformShell renders only BootGate in the prerender), and stop gating non-EQS/OVRV pages on pageLoading.

## C2-performance-03 [major] An endless 'NEW' pulse in the news dock (and the NEW BUILD glow) keeps every idle window repainting at 60 fps, over the 3 % CPU budget
- verify: ['REAL->major']
- file: ui/components/news/NewsDock.tsx:89
- area: Idle CPU (AC-13 < 3 %) · reproduced: True
- evidence: document.getAnimations() on idle BRF shows one running animation: nd-pulse, iterations Infinity, on the 6 px NewsDock dot (:89). Idle CPU over 60 s (ps CPU-time deltas): Chromium renderer + GPU + browser = 5.38 % with it running and 1.25 % after pausing it. WebKit (Playwright build; UI + WebContent + GPU + Networking) = 3.54 % vs 2.29 %, WebContent 2.27 % → 1.33 %. The NEW state stays on until the dock is opened, and newsTerminal.seenVersion is a LOCAL per-origin key, so the app starts out unseen and every new scan turns it on again. globals.css:328 .sd-newbuild also runs sd-attn (an infinite box-shadow animation that repaints every frame) in every open window after each release swap until reload. The reduced-motion block covers sd-newbuild but not nd-pulse.
- failure: The app sits on BRF all day with an unread scan, as is typical after each daily scan. Every window burns about 3.5 % CPU (WebKit stand-in) instead of about 2.3 %, which breaks AC-13's < 3 % per window and multiplies with every open window.
- fix: Make attention animations finite (e.g. `nd-pulse 1.2s ease-in-out 3`, then a static amber dot; the same for sd-attn). Animate only opacity or transform (move the sd-attn glow to an ::after with opacity). Pause when document.hidden. Add nd-pulse to the prefers-reduced-motion rule.

## C2-performance-04 [major] Data-settled p95 is still 1.4–1.5 s; gold-preopen re-fetches 6 Yahoo series on every call; DEXP reads 352 MB per page click (+830 MB ui-api RSS)
- verify: ['REAL->major']
- file: services/ui-api/routers/gold_preopen.py:460
- area: Server endpoints (data-settled tab switch, ui-api memory) · reproduced: True
- evidence: Integrated :8010 sweep: settled p95 1,461 ms (Chromium) / 1,379 ms (WebKit); 12 / 11 of 42 tabs over 400 ms. WEI 2,170–2,201 ms: /api/news-scanner/quotes takes 1.96 s cold and 1 ms warm by curl; the 60 s TTL (news_scanner.py:572) makes any visit more than 60 s after the last one cold. CMDT 1,426–1,710 ms and BRF 771 ms: /api/commodity/gold-preopen takes 0.50–0.89 s on every call (0.54 s then 0.50 s back to back), because :460 starts 6 uncached Yahoo chart requests per call, and CMDT re-polls it every 60 s per window. EVTS 1,243–1,461 ms: results-implied-moves takes 0.66 s on both consecutive calls; fundamentals-screen 0.45 s and 541 kB. DEXP 926–1,339 ms: features-explorer takes 0.86–0.95 s per pagination click, because pipeline.py:765 reads the whole 352 MB parquet on each call; ui-api RSS went from 1,885 to 2,712 MB after one call. BRF in WebKit never settled: results-reacting took 3,087 ms. Event loop during DEXP: /live max 106 ms, so it is offloaded correctly; the cost is latency and memory.
- failure: The trader switches to WEI, CMDT, EVTS or DEXP and waits 1–2+ s for numbers on every visit. Two windows paging DEXP at the same time allocate about 1.7 GB inside the process that now also serves the UI, so an OOM kill takes down the whole terminal, not just the API.
- fix: Add stale-while-revalidate caches with single-flight: gold-preopen 30–60 s keyed by its query params (or cache the 6 Yahoo bar series); quotes served stale while refreshing in the background; results-implied-moves and results-recent 5 min. For DEXP, query with DuckDB `SELECT … FROM read_parquet(?) [WHERE ticker=?] ORDER BY <col> LIMIT ? OFFSET ?` and cache the health block per (path, mtime, v, ticker). Warm the BRF endpoint set when ui-api starts.

## C2-performance-05 [major] AC-13 '< 500 MB / < 3 % for one idle window' has no idle measurement, and a WebKit stand-in sits at the budget
- verify: ['REAL->minor']
- file: desktop/src-tauri/target/selftest-up-20261024.json:1
- area: AC-13 evidence (idle RSS/CPU, multi-window) · reproduced: True
- evidence: The self-test app_total_rss of 396.7 MB is labelled 'measured right after the checks, not idle'; meta.screen_locked is true and the self-test reports no CPU. perf_baseline.md §1 says the idle window is 'not measurable here'. scripts/desktop_qa/run_selftest.py defaults to --warmup 12 and --idle 30 (:575-576), too short to cover the 30 s / 60 s pollers or any growth. My Playwright-WebKit stand-in for one idle BRF window: 480–491 MB at 25 s and 513–522 MB at 75–135 s (UI process 108 MB, WebContent 245–287, GPU 82, Networking 45; the Tauri shell itself was 99.9–104.7 MB in the self-test); CPU 3.54 % (see -03). The P8 warm-up does not move RSS (245 vs 251 MB with saveData). Each extra window adds another WebContent process (~250–290 MB) while the app restores up to MAX_WINDOWS = 8 (windows.rs:43), and there is no multi-window budget.
- failure: AC-13 is marked PASS from a 30 s sample taken about 5 s after load with the screen locked. In daily use one window idles at about 500 MB and 3.5 % CPU, and three restored windows approach 1 GB, with no number anyone signed off.
- fix: Run run_selftest.py --live --warmup 30 --idle 600 with the screen unlocked, for 1 and 3 windows, on BRF and EQS. Budget on phys_footprint (already collected as footprint_mb_peak) rather than RSS, which double-counts shared WebKit pages. Add a per-extra-window budget (e.g. < 250 MB). Record the results in perf_baseline.md.

## C2-performance-06 [minor] The hidden PipelineStudio is mounted on every page in every window and polls the dormant RL pipeline (27 % of idle requests)
- verify: not verified (minor/nit)
- file: ui/app/page.tsx:696
- area: Polling waste per window · reproduced: True
- evidence: The comment says 'stays mounted once first visited', but the code mounts it unconditionally (display:none, :696-699), so it is mounted in every window from boot. 20-minute idle BRF (Chromium): 39.1 req/min in total, of which /api/pipeline/rl-status is 6.29/min (PipelineStudio.tsx:511, 10 s) and rl-training-metrics 4.24/min (15 s); the RL pipeline is dormant (autopilot OFF). Every window open also fires data-quality, feature-importance, model-metrics, rl-training-metrics and service-health (seen in every deep-link run), loads the PipelineStudio chunk at boot, and keeps 165 hidden nodes that re-render with HomeContent. The ui_perf EQS row even names rl-status as its 'dominant call'.
- failure: With 4 windows open on unrelated pages, ui-api serves about 42 RL-status requests per minute and 20 pipeline calls per round of window opens, for a page nobody opened.
- fix: Mount it on first visit, as the comment intends (`const [pipeSeen, setPipeSeen] = useState(view === 'pipeline')`, set it when view becomes 'pipeline'), and/or pause its intervals while view !== 'pipeline'.

## C2-performance-07 [minor] A 1 s clock at the top of MarketCommandHeader re-renders the whole header every second, unsynced with the strip clock
- verify: not verified (minor/nit)
- file: ui/components/MarketCommandHeader.tsx:340
- area: Idle re-render (header clock) · reproduced: True
- evidence: `const now = useIST()` (:340; setInterval(1000) from mount, :26-35) re-renders NiftyLive, MacroTape (Intl formatting per item), PageStrip and AlertsBell every second, in every window. The desktop strip has its own second-aligned clock (TitleStrip.tsx:37-46). Idle BRF: 121.8 layouts/min and 343 style recalcs/min (Chromium CDP). The two clocks showed different seconds in 35 of 259 samples (13.5 %); D4 noted this as a known issue. Main-thread cost is small (0.84 % in total), so this is polish.
- failure: In the app the strip reads 11:45:52 while the header reads 11:45:51, about one sample in seven, in a 'Bloomberg-grade' window bar. Every window also does two layouts per second while idle.
- fix: Move the clock into a memo'd <HeaderClock/> leaf that reuses useSecondTick (second-aligned). In desktop mode drive both clocks from one shared tick, or hide one of them.

## C2-performance-08 [minor] API JSON is uncompressed on :8010 (the old :3000 gzipped it), a regression for the pending UI_API_HOST=0.0.0.0 iPad path
- verify: not verified (minor/nit)
- file: services/ui-api/main.py:136
- area: Transfer size (pending LAN mode) · reproduced: True
- evidence: GET /api/stocks/list?limit=1500, which every window fetches at boot: :3000 sends Content-Encoding gzip, 110,043 B on the wire; :8010 sends content-length 934,658 with no encoding (curl with Accept-Encoding: gzip). ui-api has no compression middleware; the only middleware is the http_guard (main.py:134-136). On loopback the cost is negligible. pm_lan.py turns on LAN access for phone/iPad.
- failure: After pm_lan.py, an iPad on Wi-Fi downloads about 8.5× more bytes per window open and per poll than it did through :3000.
- fix: Add Starlette GZipMiddleware(minimum_size=1024, compresslevel=5) above install_http_guard. Starlette 0.52.1 already skips text/event-stream; check that it leaves the static UI's precompressed responses (Content-Encoding already set) alone. Alternatively enable it only when UI_API_HOST != 127.0.0.1.

## C2-performance-09 [minor] Each window duplicates every global poll, and each WS gets its own Redis connection and OS thread on ui-api
- verify: not verified (minor/nit)
- file: services/ui-api/routers/monitor.py:209
- area: Multi-window scalability · reproduced: False
- evidence: Per window, the shell polls cost about 29 req/min before any page polls: nifty 12.6/min, nifty-live 4.2, data health/ready/provider 2.1 each, gift, quotes, indices, alerts feed and news scans about 1/min each. Restoring 8 windows fired 233 API requests in 8 s (ui-api coped: /api/prefs p99 115 ms, max 235 ms; all 8 interactive within 0.65 s). Server side, every ws_monitor call opens _redis.from_url + pubsub (:151) and starts a dedicated 'redis-reader' thread (:209) that schedules one coroutine per message per socket. Also, lib/wsManager.ts:243 doubles the reconnect delay up to 32 s with no reset when health recovers, so live ticks can resume up to 32 s after a watchdog restart (code reading; not measured).
- failure: With 8 windows plus a browser tab there are about 260 identical chrome polls per minute, 9 Redis connections and 9 blocked threads in ui-api, all for the same NIFTY, macro and status data. After a 2-minute outage, ICICI ticks come back up to 32 s after the banner says reconnected.
- fix: Server: run one Redis subscriber task per process and fan messages out to the connected sockets with asyncio. UI: elect one leader window with BroadcastChannel to poll the global chrome data and broadcast it, or let the shell push NIFTY and status it already polls. In wsManager, reset the backoff and reconnect immediately on online or health recovery, and add jitter.

## C2-performance-10 [minor] Confirmed on the served release: strip lights go grey about 16 % of the time and a fallback /health probe fires every cycle; the fix needs a rebuild and a check
- verify: not verified (minor/nit)
- file: ui/components/desktop/status.ts:16
- area: Shell status cadence (already fixed in the working tree) · reproduced: True
- evidence: Served release 20261025-114737 with a simulated 30 s Rust heartbeat (the old lib.rs `since >= 30s`): dots grey in 42 of 259 samples (16.2 %), in runs at 25.1–30.2, 55.3–60.3, 85.0–90.5 and 115.2–120.7 s, with the tooltip 'status is stale (shell poller silent)'; fallback /health probes at 25.09, 55.09, 85.09 and 115.09 s. The working tree now has status.ts (STATUS_STALE_MS 35 s, pull after 10 s) and health.rs STATUS_HEARTBEAT 8 s (C1-desktop-native-03). Neither is in the served UI release or a built app yet.
- failure: If only one side ships (a new app with the old UI build, or the reverse), the flicker or extra pulls continue. With the old build live, every terminal window flickers its service lights.
- fix: Rebuild the UI (build_ui.sh) and the app together, then re-run this cadence check (scratchpad crit/C2-performance/c2_harness.py cadence --heartbeat 10) and expect 0 grey samples and 0 /health probes. Also update the health.rs:548 comment, which still says the UI's threshold is 20 s.

### strengths
- static_ui.py is production-quality. Measured live: index.html 0.9 ms (gzip 2,463 B, no-cache, strong ETag); 73 kB hashed chunk 1.0 ms (immutable, gzip); 304 revalidation 1.2 ms. Lookups and reads run on a dedicated 16-token limiter with a bounded LRU, so static serving never queues behind ui-api's sync DuckDB routes.
- ui-api's event loop stays responsive: /live p50 1–3 ms through the PM's 42-page audit, and max 106 ms while DEXP read a 352 MB parquet (the work runs in a worker thread).
- First-load JS measured live is 263,277 B gz (≤ 300 kB). No off-origin font requests (self-hosted fonts).
- P7/P8 are correct: one component type per mount, so no remount. Cycling all 42 pages twice in Chromium returned intervals to baseline (14 → 14 → 14), DOM nodes 1,875 → 1,882 → 1,882, JS listeners 460 → 464 → 464, heap after GC 8.86 → 12.74 → 13.03 MB. One WS stayed open throughout, and the SYS EventSource closed on unmount. The warm-up adds no measurable WebKit RSS (245 vs 251 MB with saveData).
- Integrated tab-switch UI-ready p95: 40.8 ms (Chromium) and 81 ms (WebKit), well inside the 400 ms budget on every page except EQS.
- A 20-minute idle Chromium run on BRF (desktop shell faked) showed main thread 0.84 % busy, heap 8.88 → 10.02 MB after GC, a flat DOM (1,873 nodes) and no long tasks. Live ticks on BRF cost only 1.3 % (0.2 Hz) to 3.3 % (1 Hz) of the main thread.
- Multi-window burst: 8 windows restored at once were all interactive within 0.65 s. /api/prefs, the boot gate's dependency, had p99 115 ms and max 235 ms, far below the 1.5 s gate ceiling.
- The Rust poller is cheap and correct: localhost GETs on a 5 s / 15 s / 60 s / 300 s cadence, and NSE upstream calls are TTL-cached in data-service, so more windows do not multiply NSE traffic.
### not checked
- The real SuryaDhana.app / WKWebView, which the rules say not to launch. All idle CPU/RSS numbers come from Playwright WebKit (UI process plus XPC helpers) and headless Chromium; Tauri's shell, hardware GPU compositing and phys_footprint may differ. Boot paint < 0.5 s: the self-test skipped it (screen locked) and I could not run it.
- How hidden or minimized windows behave over hours: windows.rs create_window sets no background_throttling policy, so WebKit's default inactive scheduling (throttle or suspend after ~5 min) applies. Its effect on polls, the WS and alert notifications in a hidden main window is unverified.
- Market-hours behaviour with real ICICI ticks through Redis. Ticks were simulated with a mocked monitor WS in my own page only (rates 0.2 and 1 Hz), never written to live Redis.
- The ui-api restart, sleep/wake and release-swap drills (PM-owned). I only observed one PM restart of ui-api at 11:47–11:49 (connection refused for about 20 s).
- The LAN/iPad path (pm_lan.py not applied) and any Wi-Fi measurements.
- CPU and memory of the Rust shell process and its poller over hours.
- RSS for 3–8 real app windows; I measured one-window stand-ins only.
- Working-tree changes made from 12:12 onwards by the fix rounds of other critics (http_guard, status.ts, holidays.ts, AppContext watchlist sync, MarketCommandHeader session label, lib.rs/health.rs) are not in the served release 20261025-114737. My browser numbers are from that release, and from 20261025-110718 for the first Chromium deep-link run. The C1 cadence fix was checked by reading the code only.

# completeness — SHIP-WITH-FIXES

I looked for risks the six critics did not examine, or examined only from code: the gate state after the fix rounds, client-side observability, the real Launch-at-Login mechanics under launchd, the shell's build identity and rollback, CI coverage of the desktop program, and what else now shares the terminal origin. I worked read-only and sent only GET requests. I did not launch the app or a browser.

**Six findings:**
- **completeness-01 (major, reproduced): the core test suite is red right now.** A fix round changed the default URL in `scripts/ui_audit.py` without updating its test. Result: 1 failed, 516 passed, 8 skipped. The PM's reported "core 414 passed" predates the fix rounds.
- **completeness-02 (major): no client-side error reporting at all.** UI exceptions are shown only by a debug overlay whose own header says it should be removed (`ErrorCatcher`), or by `global-error`. Nothing reaches ui-api or the app log, and no ingestion route exists among the 225 OpenAPI paths.
- **completeness-03 (minor): crash-relaunch and the Launch-at-Login toggle only change a file on disk.** The app never asks launchd to reload the job. The job launchd has loaded today has no KeepAlive (`properties = runatload | inferred program`), so the "relaunch after a crash" fix has no effect until the next login, and turning the toggle off does not stop the loaded job.
- **completeness-04 (minor): two different shell binaries report the same identity, and there is no way back.** The installed app (11:10) and the new build (13:14) have different SHA-256 hashes but both say "1.0.0 (0ae66db)". Install deletes the previous app, and `desktop/` is untracked in git, so a bad build cannot be rolled back.
- **completeness-05 (minor): CI covers none of the desktop program's own gates.** It does not run `cargo test`, the 262 node checks, the `ui/scripts` tests or a static export build. The contract tests turn missing files and shape mismatches into skips, so drift passes silently.
- **completeness-06 (minor): FastAPI's `/docs` and `/redoc` now share the terminal's origin.** They load floating-version jsdelivr scripts (`swagger-ui-dist@5`, `redoc@2`) with no integrity check, on the same origin that holds the terminal's localStorage and the app's shell commands.

**What held up:** the 42-page audit and parity are green in both Chromium and WebKit. Static serving is robust against edge paths. ui-api stayed flat over 4 minutes: memory 1.717→1.718 GB, `/live` at most 6.8 ms, `/` at most 1.5 ms. tsc is clean and the static UI and prefs tests pass (150). First-load JS is 302 KB gzipped, about 263 KB without the polyfills chunk that modern WebKit skips.

## completeness-01 [major] Core suite is red now: a fix round changed ui_audit.py's default base URL without updating its test, so the reported 'core 414 passed' gate is stale
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/tests/integration/test_desktop_qa_harness.py:415
- area: test gates / release process · reproduced: True
- evidence: `PYTHONDONTWRITEBYTECODE=1 pytest -p no:cacheprovider -q tests -W ignore` gives `FAILED tests/integration/test_desktop_qa_harness.py::test_ui_audit_cli_is_backward_compatible` and `1 failed, 516 passed, 8 skipped`. The assertion compares `args.base == "http://localhost:3000"` against `'http://127.0.0.1:8010'`. scripts/ui_audit.py was modified at 12:22 (the C3-logic-unchanged-09 fix); the test file is from 11:08. The PM's gate log (scratchpad/pm/gates/core.log, 11:07) shows `414 passed, 8 skipped`. The suite has since grown by about 100 fix-round tests (now 525), so that number no longer describes the tree. The same drift shows in the desktop contract and harness files: 90 passed, 1 failed, against the claimed 89 green.
- failure: The PM reports 'all gates green' from the 11:07 logs and closes the program. The next run of the canonical five suites (CLAUDE.md: 'run all before claiming green') is red. More importantly, several fix rounds are editing shared files (ui_audit.py, http_guard, autostart.rs, health.rs, status.ts) without re-running the suites, so other regressions can land unseen. The owner is told the product is tested when the tree on disk fails its own core gate.
- fix: Update the assertion to the new default (`args.base == 'http://127.0.0.1:8010'`) and add an explicit `--base http://localhost:3000` case for backward compatibility. Make the fix-round protocol re-run all gates after the last edit and regenerate gates/*.log with timestamps later than every source mtime: the 5 pytest suites, `tsc --noEmit`, `cargo test`, the 3 node check files and ui/scripts. Have the report quote those new numbers.

## completeness-02 [major] No client-side error reporting: UI exceptions in the app go only to a debug overlay or global-error, never to ui-api or the app log
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/components/ErrorCatcher.tsx:7
- area: observability / supportability · reproduced: True
- evidence: ErrorCatcher.tsx:7 reads 'This is a DIAGNOSTIC TOOL. Remove once the root cause is identified.' It is mounted for every window at ui/app/page.tsx:963. It catches window 'error' and 'unhandledrejection', keeps the last 5 errors in React state, and renders a red 'UNCAUGHT CLIENT EXCEPTION' box with full stacks. It sends nothing anywhere. global-error.tsx shows the stack and a Retry button, with no reporting. PlatformShell.tsx:248-253 only reacts to ChunkLoadError. GET /openapi.json on :8010 lists 225 paths and none ingests client errors (only /api/telemetry/* for scheduler logs). The shell registers on_page_load only (windows.rs:657) and captures no console output or JS errors. ~/Library/Logs/ai.suryadhana.terminal/suryadhana.log holds shell events only.
- failure: During market hours a WebKit-only TypeError or an unhandled rejection fires on, say, OMON or DESK after the window has been open for hours. That is a state the 42-page audit (fresh 6 s loads in Playwright) never reaches. The owner sees a red stack-trace box over the trading screen, or a full-window 'Client-side Exception', clicks Dismiss or Retry, and the evidence is gone. There is no record of the build id, tab, window, time or stack in any log. The app gives the owner no Web Inspector, so the defect can be neither reproduced nor triaged.
- fix: Add a same-origin endpoint, e.g. `POST /api/ui/client-errors`: body capped at about 8 KB, rate-limited (30/min), refused cross-site by the http_guard Origin rule. It writes one structured JSON log line: {ui build id, isDesktop, window label, tab, message, truncated stack, ts}. Send to it from ErrorCatcher, global-error and any per-page boundary (C1-trader-ux-01) via navigator.sendBeacon. Show a count on the SYS page and in /api/telemetry/status. Replace the debug overlay with a compact 'N UI errors · copy details' chip in the title strip.

## completeness-03 [minor] KeepAlive crash-relaunch and the Launch-at-Login toggle only rewrite the plist; launchd keeps the old job until the next login, so the fix has no effect this session and toggling off does not stop the loaded job
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/desktop/src-tauri/src/lib.rs:373
- area: launch at login / crash relaunch · reproduced: False
- evidence: autostart.rs:5 promises 'launchd relaunches the app when it crashes'. LoginAgent::write/remove only write or delete ~/Library/LaunchAgents/SuryaDhana.plist. toggle_autostart (lib.rs:373-399), first_run_autostart and maintain_autostart (lib.rs:436-470) never call launchctl for the SuryaDhana label; launchctl appears only in stack.rs, for the watchdog. Live state: `launchctl print gui/501/SuryaDhana` shows the app running under the job with `properties = runatload | inferred program`, i.e. no keepalive. That job was loaded from the plugin-era plist (written 11:46, empty AssociatedBundleIdentifiers). The new binary (target bundle, 13:14, contains the KeepAlive template) has not been installed.
- failure: (a) After the fix-round build is installed, the app upgrades the plist to KeepAlive on its first launch, but launchd still runs the loaded runatload-only job. If the app crashes at 10:30 on a trading day it is not relaunched, and the tray, notifications and ICICI-expiry alerts are gone until the next login, although C2-reliability-ops-12 reads as fixed. A PM drill that kills the app right after install would either fail or pass only because the job was re-bootstrapped by hand. (b) Once a KeepAlive job is loaded, turning Launch at Login off deletes the file but the job stays loaded, so a crash still relaunches the app against the owner's setting. (c) Turning it on writes a file that does nothing until the next login.
- fix: After writing or removing the plist, reconcile launchd. The app can tell whether it was started by the job: launchd sets XPC_SERVICE_NAME=SuryaDhana, as seen in `launchctl print`. If it was not, `launchctl bootout gui/<uid>/SuryaDhana` (ignoring not-found) and then `launchctl bootstrap gui/<uid> <plist>` when on. A second instance started by RunAtLoad exits through single-instance. If it was, defer the reload and show 'applies at next login' in the menu item. For off, mark the change pending rather than booting out the job the app is running under, which would kill it. Add a check to the self-test and the boot report that compares the loaded job's properties with the plist.

## completeness-04 [minor] Two different shell binaries both identify as '1.0.0 (0ae66db)', and install deletes the previous app with no rollback; the shell's sources are untracked in git
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/scripts/build_desktop.sh:121
- area: release provenance / rollback (shell) · reproduced: True
- evidence: The /Applications binary (11:10, sha256 1f48af96…) and the target bundle binary (13:14, sha256 7cea7a8f…) both embed '0ae66db', and both Info.plists have CFBundleShortVersionString 1.0.0 and CFBundleVersion 1.0.0. build.rs:37 git_sha7 uses `git rev-parse --short=7 HEAD` with no dirty flag. HEAD is 0ae66db while `git status --porcelain desktop` gives `?? desktop/`, so none of the shell is in that commit. The UI build-info, by contrast, has git_dirty and source_sha256. build_desktop.sh:121 does `rm -rf "$dest"` and then moves the new copy in, keeping no previous bundle. The UI has `build_ui.sh --rollback`; the shell has nothing equivalent.
- failure: A fix-round shell build that crash-loops or mis-renders at login is installed on Sunday night. On Monday morning the previous working .app has been deleted. The source state that built it exists in no commit, so it cannot be rebuilt. The About box, shell_info, the logs and the self-test all say '1.0.0 (0ae66db)' for both binaries, so the PM cannot even tell which shell the owner is running. Two registered copies with the same bundle id and version (build dir and /Applications) also let a notification click or Spotlight open the build-dir copy. Mitigation: the browser at http://127.0.0.1:8010 still works.
- fix: Bake `<sha7>[-dirty]-<UTC yyyymmddHHMM>` plus a hash of desktop/ into SURYADHANA_BUILD, and use a monotonic CFBundleVersion. Show both in About and the tray, and record them in the self-test JSON. In install_app, move the existing bundle to e.g. ~/Applications/.SuryaDhana-previous.app instead of deleting it, and add `build_desktop.sh --rollback`. Once the gates are green, the owner or PM should make a local commit of the program (no remote needed) so a known-good shell can be rebuilt.

## completeness-05 [minor] CI runs none of the desktop program's own gates, and the contract tests turn missing or reshaped sources into skips, so drift passes silently
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/.github/workflows/ci.yml:50
- area: CI / regression gates · reproduced: True
- evidence: ci.yml has two jobs. `python` runs the 5 pytest suites. `ui` runs `npm ci` and `npx tsc --noEmit` (line 50) and nothing else. Never run in CI: `cargo test` (53 tests), ui/lib/__tests__/prefs.check.ts and platform.check.ts (107+104), ui/components/desktop/__tests__/desktop.check.ts (51), ui/scripts/*.test.mjs (23), and a static export build (test_desktop_static.py is opt-in through DESKTOP_QA_BUILD=1; 8 skipped here). In tests/integration/test_desktop_contract.py, `need()` (lines 60-62) calls pytest.skip('… not delivered yet') when pages.rs, the capabilities or ui/lib/platform are missing. Lines 102 and 119 also skip when pages.rs or PAGE_META are not in the expected regex shape. .github/ itself is untracked.
- failure: A later change adds a page to COMMAND_PAGES and reformats ui/components/desktop/pages.ts. test_ui_desktop_page_meta_equals_command_pages skips ('PAGE_META entries not in the expected shape') instead of failing, so the title-strip copy drifts with nothing to flag it. The same applies to the frozen contract's Go-menu/⌘1–9 parity check (§5) after a pages.rs refactor. Likewise, a Rust change that weakens a download or open_external validation rule is caught only if someone remembers to run cargo test by hand.
- fix: Add a macos-latest job, or a scripts/gates.sh that the PM must run, covering `cargo test --manifest-path desktop/src-tauri/Cargo.toml`, the three node check files, the ui/scripts node tests, and `DESKTOP_QA_BUILD=1 pytest tests/integration/test_desktop_static.py`. Now that the program is delivered, turn the 'not delivered yet' and 'shape' skips into hard failures, or allow them only behind an explicit DESKTOP_CONTRACT_ALLOW_SKIP=1.

## completeness-06 [minor] /docs and /redoc now share the terminal's origin and load floating-version third-party scripts from jsdelivr with no SRI
- verify: not verified (minor/nit)
- file: /Users/sudheer/MahaKubera_108/SuryaDhana_AI/services/ui-api/main.py:103
- area: security / origin hygiene · reproduced: True
- evidence: FastAPI(...) at main.py:103 keeps the default docs_url and redoc_url. GET http://127.0.0.1:8010/docs returns 200 HTML that loads `https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js`, and /redoc loads `https://cdn.jsdelivr.net/npm/redoc@2/bundles/redoc.standalone.js`. Both are floating major tags with no integrity attribute. The security headers in static_ui.py:148 apply to static responses only, not to these API-served pages. The shell grants the remote capability to the whole origin (lib.rs:739 substitutes __UI_ORIGIN__ with the origin), and main_frame_allowed accepts any path on it. Before the program, /docs lived on :8010 and the terminal on :3000, which are different origins.
- failure: A compromised swagger-ui-dist@5 or redoc@2 release, or a jsdelivr compromise, runs as same-origin code with the terminal whenever /docs is opened in the owner's browser. It can read and rewrite the terminal's localStorage, including the suryadhana.prefs.* cache that prefs sync pushes to the server and every window. In an app window that reaches /docs (for example through the TradingView frame's top-level navigation, C2-security-10), the script gets __TAURI_INTERNALS__ and the 9 shell commands: open_external to any https URL, native notifications, and writes into ~/Downloads.
- fix: Construct the app with `FastAPI(..., docs_url=None, redoc_url=None)` unless an opt-in such as UI_API_DOCS=1 is set. If the docs stay, serve pinned, self-hosted swagger and redoc assets with SRI, or serve them on a separate port. In desktop policy.rs main_frame_allowed, refuse /docs, /redoc and /openapi.json so app windows never host them.

### strengths
- The switchover gates I could read are genuinely green: the 42-page audit on :8010 passed 42/42 in both Chromium and WebKit (0 console errors, 0 failed requests; the one allowlisted item is the SYS SSE stream torn down by navigation), and :3000 vs :8010 parity is 42/42 with no differences in both engines.
- Static serving is robust. Over GET, unknown /api/* paths, unknown non-API paths and path-traversal variants (`/_next/static/../../../../.env`, `/%2e%2e/%2e%2e/.env`, `/..%2f..%2f.env`) all return the JSON 404 envelope. `/` and index.html are no-cache, `/build-info.json` is no-store, and file I/O runs on a dedicated anyio CapacityLimiter, so slow API handlers cannot starve chunk serving.
- ui-api is stable at idle while serving the UI. 48 samples over 4 minutes: memory 1,717,232 to 1,717,968 KB, `/live` at most 6.8 ms and `/` at most 1.5 ms. The heavy parquet reads I checked (pipeline data-quality) already run in worker threads.
- The shell's 24x7 polling adds no upstream load: `/api/positions/connection-status` is served from a single-flight cached Breeze probe (600 s TTL when OK, 900 s when expired), and the NIFTY and Desk polls hit cached data-service endpoints.
- The UI release is traceable: build-info.json records git_dirty, source_sha256 and gz stats, and /version and /ready expose the live release id (20261025-114737-0ae66db).
- Current state checks pass: tsc is clean (run with --incremental false, so no files were written); the static UI and prefs ui-api tests pass (150); first-load JS is 302 KB gzipped, about 263 KB excluding the polyfills chunk that modern WebKit does not load. The desk NAV return the tray computes matches the Desk page today (first NAV point equals start_capital 500,000).
### not checked
- No browser and no app launch, per my brief, so I did not measure long sessions in WKWebView (memory or WebContent growth over a trading day), multi-window session restore at login (8 windows loading through WebKit's shared 6-connections-per-host pool), or hidden-window timer throttling.
- I did not run scripts/tests (to avoid any Telegram path), the full ui-api suite (601), cargo test, or the node check files. I ran only the core suite (1 failure, reported), the desktop contract and harness tests, test_static_ui plus test_prefs, and tsc.
- Whether macOS Background Task Management auto-loads a newly written ~/Library/LaunchAgents plist on macOS 26. completeness-03 relies on standard launchd behaviour plus the observed loaded-job properties, not a reload experiment, which would require bootstrapping or booting out a live job.
- Market-hours paths: live ticks through the same-origin WebSocket, the 08:00 ICICI login interplay, and the first trading day (Mon 26 Oct) on the 3-process core.
- Whether CFNetwork in WKWebView reuses idle keep-alive sockets past uvicorn's --timeout-keep-alive 75 (the old Next-proxy race on POSTs). It needs a WKWebView or browser run.
- The fix-round source changes (http_guard, autostart.rs, health.rs, status.ts) are not live: the installed app is from 11:10 and ui-api has been up since 11:49. I reviewed them as code only, apart from the core-suite failure they caused.

