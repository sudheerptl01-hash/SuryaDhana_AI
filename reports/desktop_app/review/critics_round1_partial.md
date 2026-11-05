# C2-security — BLOCK

The Tauri shell is well hardened. The remote capability is exactly the 9 commands plus 2 window permissions. The ACL resolves on the IPC request's frame Origin, so it is frame-aware, and require_ui/require_boot re-check it. The boot page has a strict CSP and renders only via textContent. The navigation guard has a one-shot boot permit, and downloads use O_EXCL with a 50 MB cap checked before decoding. static_ui.py resisted every traversal GET I tried. My scan found no secret values in the .app bundle, the UI release or any log. Three problems block a production-grade label, and they all sit behind the shell:
(1) ui-api checks neither the Host header nor Origin on state-changing routes. That allows DNS rebinding from any website and plain cross-site POSTs. I verified that a spoofed Host gets 200. In a replica with the same middleware and handler shapes, a text/plain cross-site POST ran desk/reenable (which clears the HARD −20% drawdown stop), data/provider/configure and prefs/import.
(2) Right now the whole unauthenticated API is reachable from the LAN through the Next server on *:3000. I verified this with GETs to 192.168.31.62:3000. The pending pm_lan.py would reopen the same exposure on :8010 with only a shell comment as the warning.
(3) GET /api/execution/status reports the legacy engine as mode LIVE, state ACTIVE, while the product says PAPER ONLY. So any of those paths can reach breeze.place_order with the owner's real ICICI session (code path read, never exercised).
Also important: the port-squatting analysis in desktop/README.md understates the risk. A squatter gets full UI spoofing inside a trusted app window, plus a primitive that writes unquarantined files with any safe-charset extension into ~/Downloads. The shell accepts data: downloads from any frame, including the unsandboxed TradingView iframe. ui-api still sends credentialed CORS to http://localhost:3000 and :3001. master-controller allows CORS from '*'.
The fixes are small: TrustedHost and Origin middleware, a LIVE opt-in guard, a LAN token, and download quarantine with an extension allowlist. With those it becomes SHIP-WITH-FIXES.

## C2-security-01 [blocker] ui-api has no Host-header validation and no Origin/CSRF check; any website can drive state-changing endpoints
- file: services/ui-api/main.py:121
- area: ui-api HTTP surface (DNS rebinding + CSRF) · reproduced: True
- evidence: main.py:121-127 installs only CORSMiddleware(allow_origins=[localhost:3000, localhost:3001]). There is no TrustedHostMiddleware and no Origin check anywhere. Live GETs: `curl -H 'Host: rebind.attacker.example' http://127.0.0.1:8010/health` returned 200, and the same Host on / returned 200 text/html. :8001 and :8008 also answered 200 to a spoofed Host. Replica in scratch (crit/C2-security/csrf_sim.py, same CORS config and handler shapes): text/plain POSTs with Origin https://evil.example and no preflight EXECUTED /api/desk/reenable (no body, desk.py:105), /api/data/provider/configure (`await request.json()` ignores Content-Type, data_proxy.py:68-70) and /api/prefs/import (`_read_json` ignores Content-Type, prefs.py:453-470, 543). Pydantic-body routes returned 422. After DNS rebinding the page is same-origin, so JSON routes open up too: /api/execution/order (execution.py:172), /api/execution/mode (89), and /api/positions/credentials (positions.py:595, which writes ICICI_API_KEY/SECRET/CLIENT_ID/PASSWORD into .env via persist_env_updates). GET /api/positions/connection-status (login_url carries the API key) also becomes readable. data-service has the same class of no-body POSTs, e.g. POST /jobs/build-ml-dataset (data-service/main.py:541), the heavy build involved in the 15 Oct EOD OOM incident.
- failure: The owner opens any web page in Safari, which has no Private/Local Network Access protection. The page auto-submits a hidden <form method=POST action=http://127.0.0.1:8010/api/desk/reenable>. That clears the HARD max-drawdown emergency stop and resets the peak, defeating 'manual re-enable'. Alternatively the page rebinds its hostname to 127.0.0.1 (no Host check), reads connection-status, then POSTs JSON to /api/positions/credentials to swap the ICICI API key/secret in .env, or POSTs to /api/execution/order. Because of finding 03 that order goes to breeze.place_order. A POST to :8001/jobs/build-ml-dataset during the 18:30–21:15 EOD window can repeat the OOM incident.
- fix: Add two outermost middlewares to ui-api, and the same to data-service and master-controller. (a) starlette TrustedHostMiddleware(allowed_hosts=['127.0.0.1','localhost','testserver'] plus the explicit LAN host/IP only when LAN mode is on). (b) An unsafe-method guard: for POST/PUT/PATCH/DELETE, reject with 403 when an Origin header is present and not in {http://127.0.0.1:8010, http://localhost:8010, plus http://localhost:3000 only while the dev frontend runs}, or when Sec-Fetch-Site is 'cross-site'. Allow requests with no Origin header (httpx from master-controller, curl, scripts). Also make /api/data/provider/configure and /api/prefs/import require Content-Type: application/json. Add a test that posts text/plain with a foreign Origin to /api/desk/reenable and expects 403.

## C2-security-02 [blocker] The full unauthenticated API is reachable from the LAN today via Next on *:3000, and the pending UI_API_HOST=0.0.0.0 opt-in reopens it on :8010 with no token
- file: start-local.sh:250
- area: LAN exposure (current :3000 + pending pm_lan.py) · reproduced: True
- evidence: lsof: `node 2970 ... TCP *:3000 (LISTEN)`. ui/next.config rewrites /api/:path* to ui-api (lines 14-18), and start-local.sh:250/252 starts `next start -p 3000` / `next dev -p 3000` without -H. From the Mac's LAN address: `curl http://192.168.31.62:3000/api/desk/status` returned 200 and /api/prefs returned 200. /api/execution/status returned {mode: LIVE, state: ACTIVE, available: true}. /api/positions/connection-status returned HTTP 200; I discarded the body unread because it carries the login_url with the API key. Next rewrites proxy every method, so POSTs go through too. pm_lan.py:19-29 makes 0.0.0.0 an opt-in whose only safeguard is a shell comment ('The terminal has no login: only on a trusted network') and a yellow echo line in print_urls (pm_lan.py:52-54) that the launchd watchdog never shows. When on, /docs (Swagger 'Try it out'), every POST route and the ICICI credential and session-token entry forms all travel in cleartext over Wi-Fi.
- failure: Any device on the same Wi-Fi (guest, a compromised IoT device, a café or hotel network once the owner enables UI_API_HOST=0.0.0.0 for the iPad) sends `POST http://192.168.31.62:3000/api/execution/order {symbol, side, quantity, price}`. Or it POSTs /api/positions/credentials to replace the broker key and secret, or /api/desk/reenable. No authentication is required. Today this works through :3000 until the switchover stops that process.
- fix: At switchover (D1 P12), stop the running :3000 process. Make the optional frontend bind loopback: `next start -H 127.0.0.1 -p 3000` and `next dev -H 127.0.0.1 -p 3000` in start-local.sh:250/252 and ui/package.json. Do not apply pm_lan.py as written. LAN mode should require a pairing token: middleware that rejects any non-loopback peer (request.client.host) without a valid `sd_lan` cookie or bearer token, set once from a QR/one-time URL that the desktop app shows. Non-loopback peers should also be read-only by default (403 on unsafe methods unless UI_API_LAN_WRITE=1). TrustedHost should list the LAN IP. Show a persistent 'LAN EXPOSED' chip in TitleStrip and the tray when /version reports a non-loopback bind. Prefer documenting Tailscale over 0.0.0.0.

## C2-security-03 [blocker] The legacy execution engine served by ui-api is persisted in LIVE/ACTIVE mode while the product says PAPER ONLY, so every unauthenticated path to /api/execution/order is a real-money path
- file: services/ui-api/routers/execution.py:172
- area: Trading posture vs. exposed execution engine · reproduced: True
- evidence: `curl http://127.0.0.1:8010/api/execution/status` returned "mode":"LIVE","state":"ACTIVE" (same from the LAN via :3000). The mode is restored from the engine's SQLite state (services/execution-service/live_execution.py:256-258); no EXECUTION_MODE key exists in .env (key-presence check only). place_manual_order (execution.py:172-190) → engine.place_order → _submit_order_internal → LIVE branch → _breeze_place_order (live_execution.py:365-395) calls breeze.place_order(exchange_code='NSE', product='cash', order_type='market') with ICICI_API_KEY/SECRET/SESSION_TOKEN from the ui-api environment. The only gates are the price guard and state==ACTIVE. The boot page and CLAUDE.md both say 'PAPER ONLY'. I did NOT POST, so a real fill is inferred from code, not exercised.
- failure: On a trading day after the 08:00 ICICI auto-login, any request that reaches POST /api/execution/order places a real NSE market order on the owner's account. That request can come from a DNS-rebinding page (finding 01), a LAN client via :3000 today or via UI_API_HOST later (finding 02), a localhost:3000/3001 dev page (finding 06), or a mistaken UI click in LivePortfolio. This contradicts the owner-approved paper-only posture.
- fix: This is not a trading-rule change: enforce the documented posture. Have the owner confirm the intended mode, reset the engine to PAPER, and make ui-api refuse ExecutionMode.LIVE (and refuse to restore LIVE from SQLite at startup) unless an explicit opt-in env flag is set, e.g. EXECUTION_LIVE_ALLOWED=1, which is absent today. Surface the engine mode in ShellStatus/TitleStrip so the 'PAPER ONLY' chip can never contradict the backend. Combine with the Origin/Host guard from finding 01.

## C2-security-04 [major] The shell trusts whatever answers 127.0.0.1:8010, and the README's squatting analysis understates what a squatter gets
- file: desktop/src-tauri/src/health.rs:439
- area: Port squatting / ui-api identity · reproduced: False
- evidence: ui_ready is just `GET /health` 200 plus `GET /` returning 200 text/html (health.rs:439-447). No server identity or listener-owner check exists anywhere in desktop/src-tauri/src (grep). The navigator auto-navigates every waiting window to the terminal as soon as ui_ready is true (windows.rs navigator_tick). desktop/README.md:140 and PLAN.md §8 claim a squatter gets 'No process control, no arbitrary file access ... no secrets'. In fact the squatter supplies the entire UI inside a trusted SuryaDhana window. It can show a pixel-perfect ICICI credential or session-token form, since the real terminal has one. It can call shell_save_download to write attacker bytes under any [A-Za-z0-9._ -] name and extension into ~/Downloads, unquarantined (finding 05), raise native notifications attributed to SuryaDhana, and open browser URLs. It also keeps :8010 so the watchdog cannot restart ui-api (EADDRINUSE). Tray Desk NAV and NIFTY values come from the squatter. A realistic squatter is any same-uid sandboxed app with the network.server entitlement: it cannot read the repo, but through the shell it escapes its sandbox's quarantine-on-write.
- failure: ui-api crashes or restarts (the watchdog takes up to ~2 min). A sandboxed helper app binds 127.0.0.1:8010 first. The SuryaDhana window on the boot page auto-enters the fake terminal. It shows 'ICICI session expired: re-enter API secret / password' and posts the native notification 'ICICI session expired'. The owner types credentials into a window that looks exactly like their terminal. Or the fake terminal saves 'Q3_results.zip' (an ad-hoc-signed .app inside) to ~/Downloads with a 'Download complete' notification. Gatekeeper never assesses it because there is no quarantine xattr.
- fix: Verify the server before granting it a window. Simplest: before navigating, resolve the PID listening on the ui port (libproc proc_pidfdinfo, or `lsof -nP -iTCP:<port> -sTCP:LISTEN -Fpu`) and require uid == getuid() and an executable under the configured Python/venv. Stronger: a handshake secret. The shell creates ~/Library/Application Support/ai.suryadhana.terminal/shell.key (0600), ui-api reads it, and the shell calls GET /version?nonce=N and requires an HMAC(key, N) header before ui_ready. A sandboxed squatter cannot read the key. Correct the README/PLAN squatting text, and apply finding 05.

## C2-security-05 [major] Saved files get no quarantine xattr and no extension allowlist, and data: downloads are accepted from any frame, including the unsandboxed TradingView iframe
- file: desktop/src-tauri/src/windows.rs:491
- area: Downloads (shell_save_download + on_download) · reproduced: True
- evidence: commands.rs:146-187 writes with std::fs and sets no xattr. A grep for quarantine/xattr/LSFileQuarantine in src/ and tauri.conf.json finds nothing. The bundle Info.plist (plutil -p) has no LSFileQuarantineEnabled. A scratch file written by a normal process gets only com.apple.provenance, not com.apple.quarantine. policy::sanitize_filename (policy.rs:346) keeps any extension: '.terminal', '.zip', '.pkg', '.webloc', '.fileloc' and '.command' all survive. on_download allows `url.scheme() == "data"` with no origin condition (windows.rs:489-495). wry routes `<a download>` (shouldPerformDownload) straight to the download handler, bypassing on_navigation (wry-0.57.1/src/wkwebview/navigation.rs:82-88). The TradingView iframe has no sandbox attribute (ui/components/news/NewsChart.tsx:129-136). The UI itself never uses data: downloads (grep). A 'Download complete' native notification follows each save (windows.rs Finished branch).
- failure: A compromised TradingView widget script, an XSS in the terminal origin, or a squatter (finding 04) triggers `<a download='NIFTY_levels.zip' href='data:application/zip;base64,...'>.click()`. SuryaDhana writes ~/Downloads/NIFTY_levels.zip with no quarantine and shows 'Download complete'. The owner double-clicks it, Archive Utility extracts an ad-hoc-signed .app without quarantine, and the app runs with no Gatekeeper prompt on this arm64 Mac.
- fix: (1) Remove `data:` from the on_download allowlist. Only same-origin and ui-origin blob: are needed. (2) Allowlist extensions in both paths (csv, json, txt, md, pdf, png, svg, xlsx), otherwise append '.txt'. (3) Tag every file the shell writes with com.apple.quarantine (setxattr, value '0083;<hex epoch>;SuryaDhana;'), or set LSFileQuarantineEnabled=true in Info.plist via tauri.conf bundle.macOS.infoPlist. (4) Add sandbox='allow-scripts allow-same-origin allow-popups allow-popups-to-escape-sandbox' to the TradingView iframe: no allow-downloads, no allow-top-navigation. (5) Use symlink_metadata instead of exists() in unique_name so dangling symlinks count as taken.

## C2-security-06 [major] ui-api still gives credentialed CORS to http://localhost:3000 and :3001, which the same-origin UI no longer needs
- file: services/ui-api/main.py:123
- area: ui-api CORS · reproduced: True
- evidence: A live GET with `Origin: http://localhost:3000` returned `access-control-allow-origin: http://localhost:3000` and `access-control-allow-credentials: true`. :3001 behaves the same on /api/desk/status. allow_methods and allow_headers are '*', so JSON POSTs pass preflight. The terminal is now same-origin on :8010, and the optional dev UI on :3000 calls relative /api via Next rewrites and server route handlers (ui/lib/api.ts baseURL '', app/api/*/route.ts). No browser code needs cross-origin access to :8010 (grep).
- failure: The owner runs another project's dev server on localhost:3000. ~/CLAUDE.md lists job_hunter's `npm run dev` on :3000; Grafana and CRA also default to :3000/:3001. Any script on that page, e.g. a compromised npm dependency or an XSS there, can fetch http://127.0.0.1:8010/api/positions/connection-status with credentials and read the ICICI login_url/API key. It can also POST JSON to /api/positions/credentials or /api/execution/order.
- fix: Remove CORSMiddleware from ui-api, since same-origin needs none and the dev UI proxies server-side. If something truly needs it, enable it only when UI_DEV_CORS=1, never by default, and without allow_credentials.

## C2-security-07 [major] master-controller allows CORS from any origin ('*', all methods, all headers): any website can toggle autopilot, trigger the ICICI login flow and read scheduler logs
- file: scripts/master_controller.py:2165
- area: master-controller CORS · reproduced: True
- evidence: master_controller.py:2165-2170 sets `allow_origins=['*'], allow_methods=['*'], allow_headers=['*']`. I sent one OPTIONS preflight to :8008/health with Origin https://evil.example; the CORS middleware answered it without running any route. The response returned `access-control-allow-origin: *` and allow-methods 'DELETE, GET, HEAD, OPTIONS, PATCH, POST, PUT'. Write routes: POST /api/scheduler/autopilot (JSON, line 2237; AUTOPILOT gates the legacy inference, EOD square-off and the 1 h overnight RL retrain subprocess, lines 448/505/534) and POST /api/scheduler/icici-refresh (no body, line 2250; runs the unattended ICICI login, which sends 'ICICI login needs you' Telegram alerts on failure). GET /api/scheduler/logs is readable cross-origin; the current tail holds no secret-like strings (pattern count 0).
- failure: A web page runs `fetch('http://127.0.0.1:8008/api/scheduler/autopilot',{method:'POST',headers:{'content-type':'application/json'},body:'{"enabled":true}'})`. The preflight passes and autopilot turns ON, which the owner retired because it 'loses ~45–50%/yr'. It also triggers nightly RL retraining and alert noise. A loop of POST /api/scheduler/icici-refresh on a weekend, when the session is expired, repeatedly runs the headless broker login with the owner's credentials, risking an ICICI lockout and Telegram alert floods.
- fix: Remove CORSMiddleware from master-controller; its only browser client is ui-api's server-side proxy. Add the same TrustedHost and Origin guard as finding 01.

## C2-security-08 [minor] POST /api/prefs/import works as a cross-site simple request and accepts any key matching the regex, so a web page can fill the 500-key / 5 MB quota
- file: services/ui-api/routers/prefs.py:543
- area: Prefs store abuse · reproduced: True
- evidence: _read_json (prefs.py:453-470) parses the body whatever its Content-Type, so a text/plain no-cors POST runs; in the replica it executed. import_items accepts any key matching ^[A-Za-z0-9._:-]{1,128}$ (prefs.py:344-347), not only the 12 SYNC_KEYS (ui/lib/prefs/keys.ts). The quota is global (MAX_KEYS=500, MAX_TOTAL_BYTES=5 MB, prefs.py:73-74), and GET /api/prefs returns every row on each hydration.
- failure: A visited page sends about 20 POSTs, each importing 25 random keys of 200 KB, which fills 500 keys and 5 MB. After that, every new legitimate key the owner's UI writes gets 413 'too many preference keys'. Each app launch also downloads 5 MB of junk before first render and may hit the hydration timeout, so settings silently stop syncing.
- fix: Enforce a server-side key allowlist that mirrors SYNC_KEYS, or a prefix allowlist; require Content-Type application/json on PUT and import; and rely on the Origin guard from finding 01.

## C2-security-09 [minor] Terminal HTML is served with no Content-Security-Policy, although this origin holds the remote IPC capability
- file: services/ui-api/static_ui.py:531
- area: Terminal origin hardening (CSP) · reproduced: True
- evidence: Live `curl -D - http://127.0.0.1:8010/` shows cache-control, etag, nosniff, vary and x-frame-options SAMEORIGIN, but no Content-Security-Policy, Referrer-Policy or frame-ancestors. index.html has no CSP meta. static_ui.py:526-531 adds only nosniff and XFO. The release has no third-party scripts (grep), so a strict policy is feasible.
- failure: Any future injection in the terminal origin, e.g. an unescaped news or NSE string in a non-React sink or a malicious dependency, runs with __TAURI_INTERNALS__ and can call shell_save_download, shell_open_external and shell_notify without restriction. A CSP would contain it.
- fix: Have static_ui send a CSP on .html: default-src 'self'; script-src 'self' plus sha256 hashes of Next's inline bootstrap scripts (computed by build_ui.sh into build-info.json); style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' ws://127.0.0.1:8010 ws://localhost:8010; frame-src https://s.tradingview.com; object-src 'none'; base-uri 'none'; frame-ancestors 'self'. Add Referrer-Policy: no-referrer.

## C2-security-10 [minor] frame_hosts allow plain http:// and main-frame commits; the TradingView frame can take over the top window until the post-commit bounce
- file: desktop/src-tauri/src/policy.rs:206
- area: Navigation policy for embedded frames · reproduced: False
- evidence: navigation_decision allows any http or https URL whose host matches a frame_hosts suffix, for every frame including the main frame (policy.rs:197-211). Main-frame loads are only bounced after commit in on_page_load Started (windows.rs:536-551). The iframe is unsandboxed (NewsChart.tsx:129-136), so a framed page with user activation can set top.location to a *.tradingview.com page.
- failure: A compromised or MITM-injected TradingView frame navigates top to http://…tradingview.com/… (cleartext allowed). For a moment that page is the main document of a SuryaDhana window before the bounce. It has no IPC rights (the ACL is origin-scoped), but it can flash a convincing phishing page and repeatedly loop open_external tabs.
- fix: Allow https only for frame_hosts. Sandbox the iframe as in finding 05, without allow-top-navigation, so top navigation is impossible and the bounce becomes a backstop.

## C2-security-11 [minor] shell_save_download and shell_open_external have no rate limit (only shell_notify does)
- file: desktop/src-tauri/src/commands.rs:147
- area: IPC rate limits · reproduced: False
- evidence: commands.rs:146-197: the only limiter is ui_notify_limiter (20/min) inside shell_notify. shell_save_download accepts up to 50 MB per call with unlimited calls and unique ' (n)' suffixes up to 9,999 names per stem. shell_open_external opens a browser tab on every call.
- failure: A compromised terminal origin or squatter loops shell_save_download with 50 MB payloads and fills the disk in minutes. DuckDB and SQLite writes then fail and the EOD pipeline breaks. Or it loops shell_open_external and floods the default browser with phishing tabs.
- fix: Add per-window limiters: save_download at 10/min and 200 MB/hour, and stop when free disk is under 5 GB; open_external at 10/min. Log refusals.

## C2-security-12 [minor] pm_lan.py accepts a specific IPv4 bind that breaks every loopback consumer, validates no octets, and prints the wrong interface
- file: /private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/a24906e4-7b64-46ba-b24b-14c536f43922/scratchpad/pm/pm_lan.py:25
- area: Pending block pm_lan.py (robustness) · reproduced: True
- evidence: Its case statement (lines 25-29) lets any [0-9.] string through, e.g. 192.168.31.62 (the error hint even suggests 'an IPv4 address') or 999.1.1.1. A specific-IP bind leaves 127.0.0.1:8010 closed. But the watchdog probes http://localhost:8010/health (scripts/stack_watchdog.sh:51,56), master-controller uses UI_API_URL=http://localhost:8010, and the desktop app uses http://127.0.0.1:8010. The LAN echo (line 53) uses `ipconfig getifaddr en0`, but this Mac's active interface is en1 (192.168.31.62), so it would print '<this-mac-ip>'.
- failure: The owner sets UI_API_HOST=192.168.31.62 to limit exposure to Wi-Fi. ui-api binds only that IP. The watchdog sees it as down and kill/restarts it every cycle (with Telegram and dead-man noise), the desktop app sits on 'reconnecting', and scheduled jobs that call ui-api fail. Typo values never bind, so ui-api never starts.
- fix: Accept only 127.0.0.1 or 0.0.0.0, or bind loopback plus the LAN IP as two uvicorn binds. Validate octets 0-255. Derive the interface from `route -n get default`. Put the token requirement from finding 02 in the same block.

## C2-security-13 [minor] /api/monitor/ws/monitor accepts any Origin, and each connection spawns a reader thread plus a Redis connection
- file: services/ui-api/routers/monitor.py:108
- area: WebSocket · reproduced: False
- evidence: ws_monitor (monitor.py:108-160) accepts every socket without an Origin check. Each connection opens redis.from_url(...).pubsub() and starts a reader thread. WebSockets are not covered by CORS.
- failure: A malicious page opens a few hundred ws://127.0.0.1:8010/api/monitor/ws/monitor sockets. That creates hundreds of threads and Redis connections, so ui-api's worker threads and Redis maxclients are exhausted and the terminal's live ticks and SSE stall. The page can also read live quotes cross-site (low sensitivity).
- fix: Reject handshakes whose Origin is not the ui origin (or absent). Cap concurrent sockets (e.g. 32) and share one Redis pubsub fan-out instead of one per client.

## C2-security-14 [nit] .env (ICICI and Telegram secrets) is 0644 inside a home folder that group staff can traverse
- file: .env:1
- area: Local file permissions (other-user threat) · reproduced: True
- evidence: `ls -ld /Users/sudheer` shows drwxr-x---+ sudheer staff. Ancestors are 755, and .env, .logs/*.log, .logs/icici_login_failure.png and data/ui_prefs.sqlite are 0644. Only one human account exists today (dscl). For contrast, the desktop app's own config.json is 0600 (good).
- failure: If a second standard account is ever added (all are in group staff), it can read ICICI_API_KEY/SECRET, ICICI_PASSWORD and TELEGRAM_BOT_TOKEN from .env, plus the login-failure screenshot.
- fix: chmod 600 .env and .logs/*.png; have persist_env_updates write 0600; optionally chmod 700 the repo root.

## C2-security-15 [nit] The devtools feature is compiled into release, and small information leaks remain
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
- file: /private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/a24906e4-7b64-46ba-b24b-14c536f43922/scratchpad/pm/apply_patches.py:155
- area: ops/patch-application · reproduced: True
- evidence: apply_patches.py:155 `p.write_text(content)` and pm_lan.py:71 `(ROOT / f).write_text(s)` truncate and rewrite the same inode. bash reads scripts incrementally from a saved byte offset. Reproduced in scratch (crit/C2-reliability-ops/inplace): the live start-local.sh plus a 3 s pause after `status` was run, then rewritten mid-run with the D1 P4–P11 + pm_lan version (18,597 → 22,154 bytes). After main returned, bash resumed at byte 18597 of the NEW file (the middle of the P8 `else` branch), printed `run/start-local.sh: line 457: syntax error near unexpected token `else'` and exited 2 instead of 0. start-local.sh:456 is a bare `main "$@"` with no exit. stack_watchdog.sh is all top-level code (lines 69–134), so a run sleeping at line 71 resumes inside shifted text (P12 adds about 190 bytes before it).
- failure: The PM applies P4–P14 while a watchdog run is in progress (every 120 s; it spends 30 s in `sleep 30` whenever a CORE service is down) or while a watchdog-launched `start-local.sh start <svc>` is running. That run then executes fragments of the new file: at best a syntax error (exit 2, so the watchdog logs 'FAILED to start' and Telegrams a false failure); at worst a line that happens to sit at the old offset (the new file contains `stop_services`, `kill -9 $alive`, `exec scripts/build_ui.sh`). Every future in-place edit by an agent or tool carries the same latent hazard.
- fix: Write atomically, giving the file a new inode so a running bash keeps the old one: `tmp = p.with_name(p.name + f'.tmp-{os.getpid()}'); tmp.write_text(content); shutil.copymode(p, tmp); os.replace(tmp, p)`. Apply P4–P14 only when `pgrep -f 'stack_watchdog.sh|start-local.sh'` is empty. Harden both scripts: end start-local.sh with `main "$@"; exit $?` on one line, and wrap the watchdog body in `main() { … }` ending with `main "$@"; exit $?`, so bash never reads past the last line.

## C2-reliability-ops-02 [major] Server prefs store is still empty while the only origin holding the owner's watchlist/pins (:3000) is about to be stopped
- file: reports/desktop_app/prefs_inventory.md:84
- area: migration/prefs · reproduced: True
- evidence: `curl -s 127.0.0.1:8010/api/prefs` returned 0 keys at 11:2x and again at 11:31 IST. data/ui_prefs.sqlite was created 11:07 at 4096 bytes. The live :3000 build (ui/.next-prod BUILD_ID 24 Oct 15:32) does contain the sync code (chunk 1170-87bf5039cd9a56f0.js references api/prefs), but nobody has opened it in the owner's browser since ui-api got the prefs router at 11:07. All QA contexts run with suryadhana.prefs.mode=readonly and fresh profiles, so they never migrate. PLAN §7 step 6 stops :3000 right after parity. prefs_inventory.md:92-94 documents that if the owner edits a key in the app first, LWW makes the app copy win and the old value survives only in that browser's suryadhana.prefs.backup.
- failure: The PM applies D1 P4–P14 and runs `stop frontend`. The owner launches SuryaDhana.app: the watchlist is empty and the pins are gone. The owner re-adds a few symbols (a deliberate PUT clears the provisional mark). Later, opening :3000 through `start frontend` gets the legacy import back as 'skipped', so the original watchlist never reaches the app. To the owner, the product lost their data on day 1.
- fix: Gate step 6 on `GET /api/prefs` listing suryadhana.watchlist and newsTerminal.pins.v1 with origin http://localhost:3000. Before stopping :3000, ask the owner to open http://localhost:3000 once in their usual browser (exact host spelling, profile not in readonly mode). Document the after-the-fact path in the RUNBOOK: `./start-local.sh start frontend`, open the same origin, verify /api/prefs, then `./start-local.sh stop frontend`, and do this before editing the watchlist or pins in the app. Optionally the app could show a one-time banner when /api/prefs has no suryadhana.watchlist.

## C2-reliability-ops-03 [major] Every login: boot screen declares DOWN after 15 s and offers 'Start stack', which `kickstart -k`s (kills) the watchdog run that is already starting the stack
- file: desktop/src-tauri/src/stack.rs:84
- area: boot/login-ordering · reproduced: False
- evidence: boot.js:17 `DOWN_ACTIONS_AFTER_S = 15`. boot.js:99-110 then shows 'Terminal unreachable for N s. The watchdog restarts core services every 2 min; start the stack now…' plus Start, and also 'Stop stack…' as soon as any service is up. The watchdog's login path needs much longer by design. Today's reboot in .logs/watchdog.log: agents loaded about 10:57:58 → `sleep 30` debounce → 10:58:30 data-service starting → 10:58:48 ui-api starting → 10:58:58 ui-api healthy, about 60 s. So the red state with actions is shown for about 45 s on every normal boot (the exact text is in selftest-down-20261024.json boot_down_state). Start runs stack.rs:84-87 `launchctl kickstart -k gui/<uid>/com.suryadhana.watchdog`, and `-k` kills a running instance. Scratch test (trap_test.sh): SIGTERM runs the watchdog's EXIT trap and removes `.pids/watchdog/lock`; SIGKILL leaves the lock behind, and stack_watchdog.sh:32-35 then makes every run exit silently until the lock is 20 min old.
- failure: The owner logs in after a reboot. At T+15 s the boot screen is red with 'Start stack', which the owner clicks. The in-flight watchdog run dies mid-loop: the in-progress `timeout 300 start-local.sh start data-service` survives in timeout's own process group, but the ui-api and master-controller starts are abandoned. The restarted run sleeps 30 s, and if the orphaned start is still running its `pgrep start-local.sh` makes it defer until the next 120 s tick. The terminal arrives 30–150 s later than it would have without the click. If launchd escalates to SIGKILL, the orphaned mkdir lock disables the watchdog for 20 min, with no Telegram.
- fix: In stack.rs start_plan, drop `-k`. Plain `kickstart` starts the job only when it is not running, or check `launchctl print … state = running` first. Have boot_status expose app uptime and a watchdog_running flag (from `launchctl print`). In boot.js, show 'Stack starting (watchdog)…' without actions while the watchdog is running or the app uptime is under about 150 s. Show Stop stack only on explicit request, never during a start.

## C2-reliability-ops-04 [major] Missing/broken UI release: the app tells the owner to start the stack (and offers Stop), never says 'build-ui/rollback', and nothing alerts
- file: desktop/boot/boot.js:99
- area: observability/ui-release · reproduced: False
- evidence: With ui-api up and ui/dist/current missing, health.rs:446 sets ui_detail 'GET / returned HTTP 503 (UI build not served yet?)'. boot.js:99 then switches to the generic down state after 15 s: 'The watchdog restarts core services every 2 min; start the stack now', plus Start stack and, because all services are up (boot.js:110), 'Stop stack…'. Neither can fix a missing release. The real remedy (`scripts/build_ui.sh`, `--rollback`) appears only in static_ui.py's 503 HTML (lines 421-443), which the app never displays: the window stays on the boot page because ui_ready needs 200 text/html. desktop/README.md:180 troubleshooting says 'GET / returned HTTP 404', but the actual status is 503. Pending P14 only writes an hourly line to watchdog.log ('Never auto-build', no Telegram). Telegram /status (scripts/master_controller.py:1775) probes only data-service and ui-api /health, which stay 200 while the UI is missing. /ready already reports `"ui":"missing"` (observed shape: {"status":"ready",…,"ui":"ok","ui_build_id":…}).
- failure: After a restore (ui/dist is git-ignored; see C2-reliability-ops-06), a stray `rm -rf ui/dist`, or a prune or disk problem, the owner opens the app. All three services show UP, the terminal row says HTTP 503, and the advice is to start the stack. The owner clicks Start (a no-op that kicks the watchdog) or Stop, and Stop halts the EOD, Desk and backup jobs. Away from the Mac, Telegram /status shows everything green.
- fix: health.rs: on 503 (or always), also GET /ready, and when ui == 'missing' set a distinct ui_detail plus a `ui_missing` flag in BootStatus. boot.js: add a 'no UI release' state that shows the commands `./start-local.sh build-ui` and `./start-local.sh build-ui --rollback`, and hides Start/Stop. README troubleshooting: list 503 with those commands. Watchdog P14: also Telegram, throttled to once per 6 h. Telegram /status: add a 'terminal UI: release <id> / MISSING' line from /ready.

## C2-reliability-ops-05 [major] Every (re)start truncates the service log, so the watchdog's auto-restart erases the crash traceback; no rotation anywhere
- file: start-local.sh:168
- area: observability/logs · reproduced: True
- evidence: start-local.sh:168 `> "$PROJECT_ROOT/.logs/$name.log" 2>&1` (frontend: lines 250/252). Observed: .logs/ui-api.log now begins with the 11:07 start (pytz warning, then static_ui.mounted at 05:37:41Z), and the output of the 10:58–11:07 instance is gone. frontend.log is 296 bytes. Nothing is rotated: ui-api.log reached 331 KB in about 15 min under audit load (4,301 lines; ui-api now also logs every static-asset request), and watchdog.log grows forever with ANSI escape codes. The watchdog's alert text says 'see .logs/<service>.log', which by then is the new instance's log.
- failure: ui-api crashes at 14:05 (the terminal goes black or frozen, since ui-api now serves the UI shell itself). The watchdog restarts it at about 14:07 and truncates ui-api.log. When the owner investigates the Telegram 'stack was down' note, the traceback no longer exists, so root cause cannot be established. Repeated crashes look like isolated incidents.
- fix: In start_py_service and start_frontend, rotate before starting (`for i in 4 3 2 1; do [ -f "$log.$i" ] && mv "$log.$i" "$log.$((i+1))"; done; [ -f "$log" ] && mv "$log" "$log.1"`), then write with `>>` and a '=== start <ts> pid <n>' banner. Add size-based rotation: a nightly controller job or a newsyslog.d entry with a 50 MB cap, gzip, keep 5. In the watchdog, before starting a down service, `tail -n 400 .logs/$svc.log > .logs/crash/$svc-$(date +%Y%m%d-%H%M%S).log`, and name that file in the Telegram message.

## C2-reliability-ops-06 [major] RUNBOOK restore path produces a UI-less terminal; ui_prefs.sqlite has no backup or restore procedure; stale :3000/autostart instructions
- file: docs/RUNBOOK_RESTORE.md:66
- area: runbook/backup-restore · reproduced: True
- evidence: RUNBOOK §1 (lines 27-31) runs `npm ci` only and has no `build-ui` step. ui/dist/ is git-ignored (.gitignore:54), so a restored Mac serves the 503 page, and the watchdog deliberately never builds (P14). §4 line 66 lists frontend as core. Line 69 runs `scripts/ui_audit.py` 'expect 15/15', but ui_audit.py:187 defaults to `--base http://localhost:3000`, which is refused after the switchover; CLAUDE.md:124 uses the same command. §5 line 76 still recommends scripts/install_autostart.sh, an obsolete second login agent (com.suryadhana.stack, `UI_MODE=prod ./start-local.sh start`) superseded by the watchdog. §6 line 81 says 'ui/.next-prod … rebuilt by start-local'. Lines 88-89 say the watchdog starts the 'prod terminal'. There are no steps for SuryaDhana.app install, Launch at Login or the app log location. scripts/db_backup.py backs up only market-*.duckdb (lines 82, 100), so data/ui_prefs.sqlite (WAL mode; the live -wal is 8,272 bytes) is in no backup, and a naive `cp` without the -wal file misses committed writes. The LAN change (pm_lan: ui-api is loopback by default, so the phone/iPad path that :3000 provided disappears) exists only as a code comment. CLAUDE.md:7/23/30/93/104 still describe the 4-process :3000 stack.
- failure: On a disk replacement the owner follows the RUNBOOK: services come up, the app shows HTTP 503 with 'start the stack' (see C2-reliability-ops-04), ui_audit reports connection refused, and the watchlist and pins are gone unless the old Mac's app profile survived. Following §5 installs a redundant login agent. The phone/iPad terminal silently stops working at switchover.
- fix: RUNBOOK: §1 add `./start-local.sh build-ui`, then check that `/ready` shows ui ok. §4: core = 3 services, and `scripts/ui_audit.py --base http://127.0.0.1:8010` (or change the default). §5: replace install_autostart.sh with `scripts/install_launch_agents.sh install`, add the SuryaDhana.app install (installed copy first) and Launch at Login. §6: say ui/dist is rebuilt by build-ui. Add a prefs section: nightly backup with `sqlite3.connect('data/ui_prefs.sqlite').backup(dst)` inside db_backup.py (rotated like the DuckDB backups); restore = stop ui-api, copy the file, delete -wal/-shm, start (clients re-upload any key they synced, merge.ts:136-141). Add the UI_API_HOST=0.0.0.0 phone/iPad note. Update CLAUDE.md lines 7/23/30/93/104/124.

## C2-reliability-ops-07 [major] UI_API_HOST accepts any dotted string (e.g. the Mac's LAN IP, even 999.1.1.1); binding ui-api to it breaks every loopback consumer
- file: /private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/a24906e4-7b64-46ba-b24b-14c536f43922/scratchpad/pm/pm_lan.py:25
- area: ops/start-local (pending pm_lan.py) · reproduced: True
- evidence: I sourced the applied block and fed it test values. 192.168.1.20 and 999.1.1.1 both come out unchanged; localhost, :: and a value with a trailing space are coerced to 127.0.0.1 with a warning. The block's own message invites this: 'use 127.0.0.1, 0.0.0.0 or an IPv4 address'. A listener bound to this Mac's LAN IP (192.168.31.62:18977) accepted a connection to the LAN IP, but `connect 127.0.0.1` got ConnectionRefusedError. The consumers that need loopback: start_py_service's health loop (`curl http://localhost:$port/health`, start-local.sh:172), watchdog is_up (stack_watchdog.sh:51), the app (ui_url http://127.0.0.1:8010 only; config.rs rejects non-loopback) and master-controller (UI_API_URL=http://localhost:8010, start-local.sh:142).
- failure: The owner wants iPad access and sets UI_API_HOST=192.168.31.62 in .env. ui-api listens only there. start-local reports 'did not become healthy' after 60 s. The watchdog sees ui-api down on every run, finds the port already LISTENing ('already running'), and is_up still fails, so it sends a 'FAILED to start' Telegram every 30 min. The app stays on the boot page forever, and Telegram /status shows ui-api red. When DHCP changes the IP, uvicorn cannot bind at all after a reboot.
- fix: Accept only 127.0.0.1 or 0.0.0.0. For any other value, warn ('binding a single interface breaks local health checks; using 0.0.0.0') and use 0.0.0.0, or refuse. Change the message to say exactly that. Show the effective bind address in `status`.

## C2-reliability-ops-08 [minor] 'X is back up' notification is suppressed for any outage shorter than 2 min (down and up share one throttle key)
- file: desktop/src-tauri/src/lib.rs:378
- area: desktop/notifications · reproduced: False
- evidence: lib.rs:378 `shell.notify_throttled(app, &format!("svc:{name}"), Duration::from_secs(120), …)` is used for both WentDown and CameUp. WentDown fires after 2 failed 5-s polls with a 2-s /health timeout (health.rs:427). A manual `restart ui-api` takes about 13 s (watchdog log 10:58:48→10:58:58), and watchdog recoveries take about 40–160 s, so CameUp lands inside the 120 s window and is dropped. Also, the app's 2-s /health timeout is far stricter than the watchdog's 8 s (stack_watchdog.sh:56), so a ui-api event-loop stall of about 10 s (a known historical failure mode) produces a 'down' banner the watchdog would not act on.
- failure: During market hours the PM restarts ui-api, or it crashes and recovers within 2 min. The owner, away from the desk, sees a lock-screen notification 'ui-api is down — the watchdog restarts…' and never gets the recovery notice, so they assume the terminal is still down.
- fix: Throttle per (service, transition), or always deliver CameUp when the last delivered notification for that service was WentDown. Coalesce flaps by delaying WentDown 15–20 s. Use a 5–8 s /health timeout to match the watchdog.

## C2-reliability-ops-09 [minor] Chunk carry-forward is transitive and unbounded: every release keeps every chunk ever built (×3 full copies)
- file: ui/scripts/release.mjs:261
- area: release/carry-forward · reproduced: True
- evidence: carry() copies every file under the source release's _next/static that the destination lacks, including files that release had itself carried and their .gz siblings. pickCarry uses current and previous. A scratch simulation with the real release.mjs (crit/C2-reliability-ops/carrysim/sim.mjs: 10 builds, one new chunk each, swap and prune keep=3) gave 'chunks in new release' = 1,2,3,…,10. Each release is a full copy (no hardlinks); the live release is 4.5 MB, 4.3 MB of it _next/static. build-info files/bytes inflate the same way.
- failure: After months of UI releases (each changing about 1–3 MB of hashed chunks), every release directory carries hundreds of MB of dead chunks, 3 copies are kept, and each build's carry step copies them all again. Builds slow down and disk use grows without bound on the same disk that holds the 4.4 GB DuckDB and its nightly backups (the watchdog alerts below 20 GB free).
- fix: Record each release's native _next/static file list in build-info (or a static-manifest.json) and carry only the native files of current and previous. That preserves the 'open window survives 2 swaps' guarantee and caps growth. Optionally hardlink (fs.linkSync) instead of copying.

## C2-reliability-ops-10 [minor] Python service restarts still depend on Node/npm ('Node out of production' is not true for the restart path)
- file: start-local.sh:52
- area: ops/start-local · reproduced: True
- evidence: check_prerequisites exits 1 when npm is missing (start-local.sh:52-55), and it runs for every `start <svc>`, including watchdog restarts of data-service, ui-api and master-controller. install_deps runs `npm install --legacy-peer-deps` whenever ui/node_modules is absent (lines 100-103). Reproduced on the patched scratch copy: `env -i PATH=/usr/bin:/bin bash patched/start-local.sh start ui-api` stops at '✗ npm is not installed' before starting anything.
- failure: A `brew upgrade`/uninstall leaves npm off /opt/homebrew/bin, or the owner is mid `rm -rf ui/node_modules && npm ci`. ui-api crashes, and the watchdog's restart either exits at the npm check or starts a concurrent npm install under the 300 s timeout. ui-api stays down and a FAILED Telegram goes out every 30 min, all for a Node dependency the 3 Python services do not need.
- fix: Require npm, and run the node_modules install, only when the start set includes frontend or the command is build-ui.

## C2-reliability-ops-11 [minor] --self-test writes its synthetic attacks and scratch-origin traffic into the owner's real app log
- file: desktop/src-tauri/src/lib.rs:503
- area: observability/app-log · reproduced: True
- evidence: resolve_paths isolates state, window state and downloads in self-test but keeps the real log_dir (lib.rs:499-509). ~/Library/Logs/ai.suryadhana.terminal/suryadhana.log (819 lines) contains entries such as `[nav] main: blocked tauri://localhost/index.html (boot page navigation not initiated by the shell)`, `[nav] main: blocked http://127.0.0.1:8001/health`, `[ipc] shell_notify rejected: title longer than 120 characters` and terminal loads of scratch origins :8092/:8098, all from self-test and drill runs and not marked as such.
- failure: After `scripts/build_desktop.sh --install --test`, the owner diagnosing a real problem (a 'black window') opens Help ▸ App Logs and finds WARN lines about blocked navigations and rejected IPC. These look like an attack or a bug and hide the real entries.
- fix: In self-test mode log to `<temp_dir>/logs` (and copy the file next to the JSON report), or prefix every line with `[selftest]`.

## C2-reliability-ops-12 [minor] Nothing restarts the app if it crashes; tray, notifications and ICICI-expiry alerts stop until next login
- file: desktop/src-tauri/src/lib.rs:573
- area: desktop/supervision · reproduced: False
- evidence: tauri-plugin-autostart 2.7.0 → auto-launch 0.6.0 writes a LaunchAgent with RunAtLoad only (macos.rs:288-306; agent_extra_config not set by the plugin). There is no KeepAlive. The watchdog supervises only the 3 Python services. The Rust shell has panic paths (`.expect("error while building the SuryaDhana app")` lib.rs:700, `expect("http client")` health.rs:371).
- failure: On an unattended Mac mini, the shell crashes (a WebKit or plugin panic) on Monday at 10:00. The menu-bar NIFTY/health item and native 'service down' and 'ICICI session expired' notifications are silently gone for the rest of the week. Only Telegram remains.
- fix: Have the watchdog relaunch the app (throttled, logged): if ~/Library/LaunchAgents/SuryaDhana.plist exists (Launch at Login on) and `pgrep -x SuryaDhana` is empty on 2 checks, run `open -gj -b ai.suryadhana.terminal`. Alternatively, write the autostart plist yourself with KeepAlive {SuccessfulExit: false}, so ⌘Q stays honoured.

## C2-reliability-ops-13 [minor] Fallback 'Start stack' (watchdog not loaded) launches the stack's Python as a child of SuryaDhana.app, contrary to the TCC design note
- file: desktop/src-tauri/src/stack.rs:89
- area: desktop/stack-control · reproduced: False
- evidence: stack.rs:1-9 says 'The app NEVER runs the stack's Python itself (TCC: the interpreter lives under ~/Desktop…)'. But start_plan with watchdog_loaded=false spawns `/bin/bash <repo>/start-local.sh start` from the app (stack.rs:88-95), which runs ~/Desktop/jupyter_env/bin/python. macOS attributes TCC to the responsible process (the app), and process_group(0) does not change that. There is no TCC preflight on this path, unlike stack_watchdog.sh:79-86. An ad-hoc-signed app's TCC grant is tied to its code signature and is invalidated by every rebuild.
- failure: After an `install_launch_agents.sh uninstall`, or on a fresh restore where the agents are not installed yet, the owner clicks Start stack. Python blocks on a 'SuryaDhana would like to access files in your Desktop folder' prompt, or is denied. start-local reports 'did not become healthy' after 60 s per service, the boot page stays down, and the failure is visible only in .logs/desktop-stack.log.
- fix: When the watchdog agent is not loaded, do not spawn start-local.sh. Bootstrap the agent instead (`launchctl bootstrap gui/<uid> ~/Library/LaunchAgents/com.suryadhana.watchdog.plist` if the plist exists), or show 'run scripts/install_launch_agents.sh install', so Python is always started by launchd.

## C2-reliability-ops-14 [minor] A SIGKILLed or crashed build leaves ui/.build-ui/staging-* behind forever
- file: scripts/build_ui.sh:203
- area: release/interrupted-build · reproduced: False
- evidence: The staging dir is `$WORK_DIR/staging-$RELEASE_ID-$$` (build_ui.sh:203), removed only by the run's own cleanup trap (line 74). acquire_lock takes over a stale lock (lines 132-139) but never removes stale staging dirs. prune() cleans only releases/.incoming-* with dead pids (release.mjs:390-397). A staging copy holds the UI sources plus Next's intermediate .next build output (ui/.next-prod is 1.5 GB for comparison).
- failure: A build is killed by OOM, `kill -9`, a reboot or a closed laptop lid, possibly several times over the months. Each leaves a staging tree inside ui/, consuming disk on the data volume. A leftover staging dir also shows up in `check_ui_entries` and in tools that scan ui/.
- fix: After acquiring the lock, delete `ui/.build-ui/staging-*-<pid>` dirs whose pid is not alive (the same rule prune applies to .incoming-*).

## C2-reliability-ops-15 [nit] Three 'X is back up' notifications at every login although nothing went down from the app's point of view
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
- file: reports/desktop_app/PLAN.md:184
- area: prefs migration / switchover sequencing · reproduced: True
- evidence: Live `curl http://127.0.0.1:8010/api/prefs` returned {"prefs": {}, "server_time": ...} at about 11:25 IST. data/ui_prefs.sqlite is 4096 B plus an 8 KB WAL, created 11:07 when ui-api restarted with the prefs router. The :3000 server (pid 2955, `next start -p 3000`) serves ui/.next-prod, built 24 Oct 15:32; its chunk 1170-87bf5039cd9a56f0.js contains the '/api/prefs' sync code. prefs_inventory.md:84-92 says the one-time migration runs only when the owner's usual browser loads that :3000 build. The pending D1 P5/P12 remove frontend from CORE, and PLAN §7 step 6 then stops :3000. Steps 6 and 7 have no check that the migration happened. Before 11:07, /api/prefs was a 404 on live, so no earlier visit could have migrated anything.
- failure: The PM applies P4–P14, stops :3000 and installs the app with autostart. The owner logs in and the app opens on the new origin http://127.0.0.1:8010 with empty localStorage. The watchlist ([]), pins, ticket sizing, goldPreOpen baseline and checks, fund filters, research selection and GO recents all show defaults. The app uploads '[]' as a provisional value. If the owner adds even one symbol before reopening :3000, last-write-wins makes that the server value, and the later legacy import from :3000 is 'skipped'. The original list then survives only in :3000's localStorage (suryadhana.prefs.backup). To the owner the conversion looks like it lost their data on day one.
- fix: Make the migration a hard gate before step 6. Keep :3000 running and ask the owner to open http://localhost:3000 once (and the iPad/phone LAN :3000 if used). Proceed only when GET /api/prefs shows non-provisional records whose origin is the old :3000 origin for at least suryadhana.watchlist and newsTerminal.pins.v1. Add this check to the switchover script or to `start-local.sh status` ('prefs: N keys, legacy import: done/missing'). Optionally, have the app show a one-time notice when the store has no non-provisional records: 'Settings not yet imported from the browser terminal: open localhost:3000 once'.

## C3-logic-unchanged-02 [major] Same-origin multi-window watchlist edits overwrite each other; D3 1d does not fix ⌘N
- file: ui/context/AppContext.tsx:276
- area: prefs sync / multi-window · reproduced: True
- evidence: AppContext reads the watchlist from localStorage once, on mount (lines 260-271). The 1d listener (lines 276-287) reacts only to 'suryadhana:prefs-changed'. The sync engine emits that event only when it applies a server value that differs from the current localStorage value. App windows share one localStorage: windows.rs:409 makes the webview incognito only in self-test, so all windows use the default data store. So the second window never gets the event, and D3's own check E9 asserts exactly this (ui/lib/__tests__/prefs.check.ts:392-403, 'window 2 applied nothing'). I ran `node ui/lib/__tests__/prefs.check.ts` and all 107 checks pass. A grep shows only lib/pins.ts listens to the native 'storage' event. I simulated it with the real PrefsSyncEngine and one shared storage (/private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/a24906e4-7b64-46ba-b24b-14c536f43922/scratchpad/crit/C3/multiwin.mts): window A adds HDFCBANK, window B refetches and gets no event, then B removes INFY. Result: server and localStorage hold ["RELIANCE","TCS"], and HDFCBANK is lost. D3.md:95 claims 'The patch makes multi-window (⌘N) correct'.
- failure: After a relaunch the app restores two windows (AC-7 session restore), or the owner presses ⌘N. The owner adds a stock to the watchlist in window 1. Later they remove a different stock in window 2, which still holds its mount-time list. Window 2 writes its stale list, which is uploaded to the server, and window 1's addition is silently gone everywhere, including other devices after sync. The same pattern affects TradeTicket, GoldPreOpen and FundamentalsScreen state.
- fix: In AppContext, also adopt changes from other same-origin windows, as lib/pins.ts already does: `window.addEventListener('storage', e => { if (e.key === WATCHLIST_KEY) adopt(e.newValue) })`, with the same parse and filter. Apply the same pattern to the other SYNC-key consumers that cache state on mount. Add an E2E with two pages in ONE browser context: edit in page 1, edit in page 2, and assert both edits survive. Correct the D3.md claim.

## C3-logic-unchanged-03 [major] The :3000 parity baseline already contains the program's UI changes, so parity cannot prove the logic is unchanged
- file: reports/desktop_app/switchover/parity.log:1
- area: evidence / AC-3 parity · reproduced: True
- evidence: ui/.next-prod/BUILD_ID was modified 2026-10-24 15:32, after D3's call-site edits (11:30) and D4's layout and globals.css (11:31 and 11:50). static/chunks/1170-87bf5039cd9a56f0.js contains `__SURYADHANA_SHELL__`, '/api/prefs' and 'prefs-changed'. static/css/b7bd282d6a372266.css contains `--shell-top`. The page chunk lacks only the PM's 25 Oct P7/P8 code (no requestIdleCallback). The only measurement of the pre-program build is reports/desktop_app/perf_baseline_3000.csv (11:28, perf counts only, no structural parity). parity.log reports PARITY between this rebuilt :3000 and :8010.
- failure: Any browser-mode behaviour change that D3/D4 introduced is present on both sides and is reported PARITY. Examples: the PlatformShell boot gate, prefs hydration overriding localStorage, the /health monitor and banner, the CSV helper change, the font swap, and C3-02/C3-05. AC-3 and the owner's 'logic remains same' requirement would be signed off against a baseline that already includes the change under test.
- fix: Build a true pre-program baseline. In a staging copy of ui/, reverse the recorded blocks: D3.md §2 call sites, D3 1d, D4 P1–P11. Restore the original layout.tsx and global-error.tsx, which are recorded in D4's first transcript (agent-a67f6ea07f9ae62d7, 05:39 UTC). Drop components/desktop, lib/platform, lib/prefs and the PlatformShell wrapper. Build with `scripts/build_ui.sh --out <scratch>`, serve it with scripts/desktop_qa/scratch_server.py, and run parity.py with A=baseline and B=:8010 in both engines. Publish the expected-delta list (gate, prefs GET/PUT, /health, build-info). At minimum, label the current report 'vs the 24 Oct 15:32 build (already contains D3/D4)'.

## C3-logic-unchanged-04 [major] UI_API_HOST accepts a specific IPv4 address, which takes ui-api off loopback for every local consumer
- file: /private/tmp/claude-501/-Users-sudheer-MahaKubera-108-SuryaDhana-AI/a24906e4-7b64-46ba-b24b-14c536f43922/scratchpad/pm/pm_lan.py:25
- area: pending PM block (LAN host) · reproduced: True
- evidence: The case statement (lines 25-29) normalises only non-numeric values, and its warning text tells the user to 'use 127.0.0.1, 0.0.0.0 or an IPv4 address'. These consumers all reach ui-api over loopback: scripts/stack_watchdog.sh:51/56 (is_up → http://localhost:8010/health), start-local.sh:172 (start_py_service waits on http://localhost:$port/health), start-local.sh:271 (start_one treats any listener on the port as 'already running'), desktop/src-tauri/src/config.rs:23 (DEFAULT_UI_URL http://127.0.0.1:8010, loopback-only), and scripts/daily_session_refresh.py:59/108 (POSTs the ICICI session token to localhost:8010). Demonstration: a scratch python http.server bound to this Mac's en0 address on port 18765 answered 200 on that IP and 000 (refused) on both localhost and 127.0.0.1. I stopped it immediately.
- failure: The owner sets UI_API_HOST to the Mac's LAN IP, as the warning invites, to use the iPad. ui-api then listens only on that IP. start-local reports 'did not become healthy'. Every 2 minutes the watchdog sees ui-api down, but start_one says 'already running', so ui-api is reported down indefinitely. The desktop boot screen never reaches the terminal. The 08:00 ICICI session refresh cannot post the token, so there is no live data that day. A DHCP address change makes the bind fail outright.
- fix: Accept only 127.0.0.1 and 0.0.0.0. Reject anything else and fall back to 127.0.0.1, and change the warning to 'use 127.0.0.1 or 0.0.0.0'. 0.0.0.0 keeps loopback working for the watchdog, the app and the jobs. If interface-specific binding is ever needed, also keep a loopback listener (for example a second uvicorn socket) and test the watchdog against it.

## C3-logic-unchanged-05 [minor] Moving to the new origin resets the per-device 'seen' markers, so the first app visit replays alert history and badges
- file: ui/lib/alerts.ts:21
- area: prefs hydration / new-origin initial state · reproduced: False
- evidence: readSeen() returns '' when suryadhana.alerts.seen.v2 is absent. WatchMonitor.tsx:124-129 then treats every history hit as fresh: a 20 s toast plus a native notification for each. AlertsBell.tsx:20 shows the whole 30-item feed as unread, and the NewsDock badge resets too. All three keys are LOCAL by design (ui/lib/prefs/keys.ts:31-35) and are never migrated. P11 makes those toasts visible for the first time. Live /api/alerts currently has history=0, so there is no impact today.
- failure: The owner sets a few alerts this week, they fire, and only afterwards does the owner first open WTCH in the app. Every past hit pops again as a toast and a macOS notification, as if new. The inbox badge shows up to 30 unread items that were already read in the browser.
- fix: On an origin's first sync run (meta null, empty legacy snapshot), set the three seen markers to 'now' or to the newest server timestamp before first render. Alternatively, add a 'migrate once' class so the legacy import carries them without syncing them afterwards.

## C3-logic-unchanged-06 [minor] The desktop window shows two contradicting NSE session states on trading holidays
- file: ui/components/desktop/TitleStrip.tsx:85
- area: duplicated session logic (desktop chrome) · reproduced: True
- evidence: The page header uses a weekday-only rule (MarketCommandHeader.tsx:35-42: 'NSE OPEN' from 09:15 to 15:30 on any weekday). The new TitleStrip uses session.ts nseSession() with holidays from /api/market/eco-calendar. Live GET /api/market/eco-calendar?back=0&ahead=45 lists HOLIDAY on 2026-11-10 and 2026-11-24, both Tuesdays.
- failure: On 10 Nov 2026 at 10:00 IST the app shows 'NSE OPEN' in green in the header and 'NSE CLOSED · holiday' in the title strip at the same time. The browser shows only the header. The conversion has introduced a second market-session rule that disagrees with the first.
- fix: Use one session function for both: either the header adopts session.ts with the holiday list (a small, deliberate UI fix, to be called out), or the strip shows the header's state. Add a unit test pinning both to the same answer for 2026-11-10 10:00 IST.

## C3-logic-unchanged-07 [minor] In the app, price-alert notifications beyond 20 per minute are rejected; the browser path has no limit
- file: desktop/src-tauri/src/commands.rs:97
- area: notifications behaviour (desktop vs browser) · reproduced: False
- evidence: shell_notify rejects with 'rate limited (20 notifications per minute)' (commands.rs:97-104; limiter created at lib.rs:631, shared by every window). WatchMonitor.tsx:124-129 calls notify() once per fresh hit. The browser branch, platform/index.ts notify(), fires a Notification for every hit. The in-page toast still shows, and the master-controller's Mac and Telegram announcement is independent.
- failure: On a gap-down open, 25 alert levels cross in the first minute. The browser shows 25 notifications; the app shows 20 and drops 5, with only a console warning.
- fix: Coalesce instead of rejecting: after the limit, show one '+N more price alerts' summary per window of time, or queue and deliver later. Alternatively, have WatchMonitor batch hits into one notification per check.

## C3-logic-unchanged-08 [minor] ui_perf.py does not put prefs sync into readonly mode, so a run against live :8010 writes the owner's prefs store
- file: scripts/ui_perf.py:381
- area: QA tooling vs live prefs · reproduced: True
- evidence: measure_cold() creates `browser.new_context(...)` and adds INIT_SCRIPT, which never sets localStorage 'suryadhana.prefs.mode'. ui_audit.py, parity.py and probe.new_qa_context all default to readonly (probe.py:90-105). prefs_inventory.md §3 says QA tools that drive live :8010 must set readonly.
- failure: The PM measures AC-13 with `scripts/ui_perf.py --base http://127.0.0.1:8010`. Each fresh context mounts 42 pages, and the defaults that pages persist on mount (watchlist '[]', rsch.sel, omon, comp, goldPreOpen day blank, fund filters) are uploaded as provisional imports to data/ui_prefs.sqlite. The design prevents them from overwriting real values, but they become what the owner's first app launch adopts before migration, which makes C3-01 worse.
- fix: Create the contexts with scripts/desktop_qa/probe.new_qa_context (readonly by default), or prepend `localStorage.setItem('suryadhana.prefs.mode','readonly')` to INIT_SCRIPT and add a --prefs-mode flag.

## C3-logic-unchanged-09 [nit] On :3000 (next dev) the health monitor triggers a 404 every 10 s, and ui_audit.py still defaults to :3000
- file: ui/components/desktop/health.ts:80
- area: dev mode / ops docs · reproduced: False
- evidence: probeUiApi falls back from /health (a Next 404 page) to /api/health, which ui-api does not have, so every probe is a 404 that the monitor counts as 'alive'. That is one console 'Failed to load resource' error and one ui-api 404 access-log line every 10 s per dev tab. Separately, scripts/ui_audit.py:187 defaults to --base http://localhost:3000, and CLAUDE.md's documented audit command will target a server that the switchover stops.
- failure: After switchover, `$P scripts/ui_audit.py` as documented fails because nothing listens on :3000. In dev (`start frontend`), the console fills with 404s, which hides real errors.
- fix: Add a GET /api/health alias in ui-api that returns the same body as /health (a pure addition), and probe it first. Change ui_audit.py's default --base to http://127.0.0.1:8010 when P4–P14 are applied, and update CLAUDE.md.

## C3-logic-unchanged-10 [nit] P11 and the font self-hosting change what the browser shows (toasts now visible, Greek σ from a system font)
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
- file: desktop/src-tauri/src/windows.rs:592
- area: window lifecycle (fullscreen) · reproduced: False
- evidence: - windows.rs:592-595: CloseRequested on main calls prevent_close and hide().
- tao's set_visible(false) is a plain orderOut with no fullscreen handling (tao platform_impl/macos/window.rs:643-647).
- The window-state plugin saves FULLSCREEN (lib.rs:581), so main often restarts in fullscreen.
- Electron had to special-case exactly this AppKit behaviour.
- failure: Main is in native fullscreen on display 2. The owner presses ⌘W or the red button. The window is hidden while its fullscreen Space stays, leaving an empty black Space he has to swipe away; reopening from the Dock or tray can then look confusing.
- fix: If is_fullscreen(), call set_fullscreen(false) and hide only after the exit transition finishes, or minimize instead. Cover it in the PM drill.

## C1-desktop-native-15 [minor] ⌘N places new windows relative to main, not the focused window; window minimum size, focus targeting and drag regions need polish
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
- file: desktop/src-tauri/src/windows.rs:396
- area: window lifecycle (tabbing) · reproduced: False
- evidence: - tao 0.37.2 turns automatic tabbing on by default (platform_impl/macos/window.rs:118) and disables it only when asked (306-307).
- Tauri 2.12.5 exposes only tabbing_identifier (webview/webview_window.rs:839).
- The window builder (windows.rs:396-409) sets neither.
- The 32 px TitleStrip and the traffic-light inset (14, 18) assume there is no tab bar.
- failure: With the macOS default 'Prefer tabs when opening documents: In Full Screen', ⌘N in a fullscreen terminal opens the new window as a native tab. AppKit then draws a tab bar in the title area over or under the custom strip, and the Window and View menus gain Merge All Windows and Show Tab Bar. Session restore later brings the tabs back as separate windows.
- fix: Call NSWindow.setAllowsAutomaticWindowTabbing(false) once at startup (objc2, on the main thread), or give each window a unique tabbingIdentifier and set tabbingMode to disallowed.

## C1-desktop-native-17 [minor] Boot page: progress not announced to VoiceOver, error text can't be copied, raw command text shown, and a missing UI build is shown as a stack outage
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

