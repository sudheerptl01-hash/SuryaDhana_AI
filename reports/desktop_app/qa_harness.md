# Desktop QA harness (workstream T): how to run it, what PASS means, baselines

Owner: T (QA harness). Program spec: `reports/desktop_app/PLAN.md` (AC-3, AC-4, AC-5, AC-7, AC-11, AC-13, AC-14).
Everything here is **read-only against the live stack**. The harness loads pages as a user would (GET page
loads; the pages' own compute-only POSTs on load are listed below), opens GET streams, and sends one WebSocket
ping. It never POSTs to a stream or job endpoint, never restarts a service, and never writes to `ui/.next*`.

```
P=/Users/sudheer/Desktop/jupyter_env/bin/python        # the only Python (shared env: no pip installs)
```

## 0. Layout

| Path | Kind | Purpose |
|---|---|---|
| `scripts/ui_audit.py` | CLI (extended, old CLI unchanged) | 42-page audit, Chromium and/or WebKit: timing, console/page errors, failed requests |
| `scripts/desktop_qa/netpolicy.py` | module | THE failure policy: what counts, the stream-abort allowlist, platform seams, URL keys, number masking |
| `scripts/desktop_qa/probe.py` | module | one-tab browser probe shared by the audit and parity (epoch attribution, drain, fingerprint) |
| `scripts/desktop_qa/pages.py` | module | strict parsers for `ui/app/page.tsx` (TAB_IDS, COMMAND_PAGES, page strip) and `desktop/src-tauri/src/pages.rs` |
| `scripts/desktop_qa/parity.py` | CLI | per-tab A-vs-B parity (same engine), Markdown + JSON, verdict PARITY/DIFF with reasons |
| `scripts/desktop_qa/streams.py` | CLI | SSE flow, WS ping, unknown-job pipeline streams, POST-stream routability |
| `scripts/desktop_qa/run_selftest.py` | CLI | SuryaDhana.app E2E driver: `--self-test`, codesign, size, plist id, autostart, single instance, RSS/CPU |
| `scripts/desktop_qa/scratch_server.py` | CLI | scratch same-origin server: a static export + /api, SSE, WS, /health, /version forwarded to live :8010 |
| `scripts/desktop_qa/scratch_export.py` | CLI | builds a scratch export (`scripts/build_ui.sh --out`, or the feasibility recipe) + `qa_snapshot.json` |
| `scripts/desktop_qa/tauri_acl.py` | module | static Tauri v2 ACL resolver (capabilities, permissions, commands) for the contract test |
| `tests/integration/test_desktop_qa_harness.py` | pytest (core suite) | unit tests of the harness itself: pure, no browser, no network |
| `tests/integration/test_desktop_contract.py` | pytest (core suite) | static shell-UI contract v1 checks; each test skips until its file is delivered |
| `tests/integration/test_desktop_static.py` | pytest (opt-in) | `DESKTOP_QA_BUILD=1`: a real `scripts/build_ui.sh --out` build and its output shape |

Concurrency rule used for every baseline: **at most two browsers at a time** against the live ui-api (one audit
and one parity, or one parity and nothing else), one page per browser, and streams one at a time.

## 1. The 42-page audit: `scripts/ui_audit.py`

```bash
$P scripts/ui_audit.py                                    # unchanged default: the original 15 tabs, Chromium, :3000
$P scripts/ui_audit.py --tabs all --browser both --base http://127.0.0.1:8010 --out reports/ui_audit/after
$P scripts/ui_audit.py --tabs desk,stocks --browser webkit --strict --screenshots none
```

New flags: `--browser chromium|webkit|both` (default chromium), `--tabs all` (parsed from `ui/app/page.tsx`
TAB_IDS; comma lists and the old 15-tab `TABS` map still work), `--strict`, `--screenshots full|viewport|none`
(default `full` = the old viewport + full-page PNGs), `--idle-timeout`, `--ready-timeout`, `--drain-timeout`,
`--label`, `--json/--md`. Chromium uses the system Chrome channel like the original script (`--chromium-channel ''`
= bundled Chromium).

Per tab: navigate to `<base>/?tab=<id>`, wait until **content-ready** (the tab's code-split chunk replaced the
loading skeleton AND the page's own PageHeader code chip shows its function code), then network-idle (capped),
then `--wait` seconds of dwell, then **drain** (wait up to `--drain-timeout` for the tab's own in-flight API
calls so leaving does not abort them), then leave via `about:blank` so the tab's polls and streams end before
the next tab loads.

**Failure classes** (any one fails the tab; policy in `netpolicy.py`):
`navigation` · `not_ready` (skeleton never replaced / page header never rendered) · `app_error` (error overlay
text) · `crash` · `page_error` (uncaught) · `console_error` · `failed_request` (first-party HTTP >= 400 or
network failure) · `websocket_error`. `--strict` adds console warnings, third-party failures and visible
ErrorBoxes.

**The only allowlist** (narrow, all three must hold): the path is one of the 6 stream endpoints
(`/api/telemetry/logs/stream`, `/api/pipeline/{ml,rl}-stream/<id>`, `/api/ml/train/stream`,
`/api/analytics/{,wfo-}backtest/stream`), the failure text is an abort (Chromium `net::ERR_ABORTED`, WebKit
`cancelled` / `Load request cancelled`), and it happened **after the harness navigated away** from the tab that
opened it. A stream aborted while its tab is still showing is a failure (`stream_abort_in_tab`); an ordinary
request still pending after the drain window and aborted on leave is a failure (`aborted_by_navigation`).

**PASS** = exit code 0 = every tab passes in every requested engine. Exit 1 = a tab failed; 2 = bad arguments.

Outputs: `<out>/audit.json` (old per-tab shape plus new fields; with `--browser both`
`<out>/<engine>/audit.json`), `<out>/audit_report.json` and `<out>/audit_report.md` (per-engine summary, timing
table with ready/idle/total/FCP, and **failed requests by endpoint** with a `platform seam` column, so a run that
fails only on platform probes is told apart from a page failure at a glance; pass/fail is not changed by it).

## 2. Parity: `scripts/desktop_qa/parity.py`

```bash
$P scripts/desktop_qa/parity.py --a http://localhost:3000 --b http://127.0.0.1:8010 --browser both \
   --out reports/desktop_app/parity_switchover --label-a "old :3000" --label-b "ui-api static release <id>"
```

For each of the 42 tabs, in the same engine, A then B (interleaved, so both see the same market state), each
observed for the same window (`--observe 12` s from navigation: the UI's interval pollers are 1/5/10/15/20/30/60 s,
so a 10 s poller fires on both sides or neither), it compares:

1. the **API request set**: method + templated path (tickers, numbers, dates, job ids become `{sym}`, `{n}`,
   `{date}`, `{id}`) + query **keys** only
2. **status classes** per endpoint (2xx/4xx/5xx/ERR/ABORT/PENDING)
3. **console and page errors**, normalised (numbers, local origins and hashed asset names masked)
4. a **structural fingerprint**: PageHeader code + title, panel titles, headings, number of tables and their
   column headers, canvas / recharts presence, iframe hosts, visible ErrorBoxes, loading skeleton, error
   overlay, content-ready. Live numbers are masked; counts of rows are not compared.

**Platform seams** (`netpolicy.PLATFORM_SEAM_PATHS`: `/health`, `/api/health`, `/version`, `/build-info.json`,
`/api/prefs[/<key>]`) are set aside from 1-3 and reported per tab (`diff.platform_seams`, a note on the verdict),
because the same UI code takes a different probe path per front server by design (PLAN §5): on the Next server
`/health` is a 404 page, so D4's health monitor falls back to `/api/health`; on ui-api `/health` answers.
`--no-seam-exclusion` compares them like any other endpoint. The per-side audit scoring (`a_pass`, `b_pass`)
still counts seam failures, and the summary lists `a_failures_non_seam` / `b_failures_non_seam`.

A DIFF is re-probed `--retries` times (default 1); only a difference that persists is reported.
**PASS** = exit 0 = every tab PARITY in every engine. For AC-3 the PM additionally needs `b_pass` (B clean by
the audit policy) on every tab: use the audit on B, or read `b_failed` in the report.

Outputs: `<out>/parity.json` (checkpointed after each engine) and `<out>/parity.md`.

## 3. Streams: `scripts/desktop_qa/streams.py`

```bash
$P scripts/desktop_qa/streams.py --base http://localhost:3000 --base http://127.0.0.1:8010 --out <dir>
```

Sequential, one stream at a time. Every stream GET sends a browser-like `Accept-Encoding: gzip, deflate` and the
harness decodes the body itself, so a front server that compresses an event stream (which holds SSE frames in
the compressor's buffer) is caught and named.

| Check | What | PASS |
|---|---|---|
| `sse_telemetry` | GET `/api/telemetry/logs/stream` | 200, `text/event-stream`, not content-encoded, first decoded byte < 2 s, >= 2 frames and >= 1 frame after the initial burst within `--sse-window` (30 s; master-controller replays 50 lines, then heartbeats every 25 s) |
| `ws_monitor` | WS `/api/monitor/ws/monitor`, send `{"action":"ping"}` | connect and `{"pong": true}` within 5 s (the handler only reads Redis pub/sub) |
| `ml_stream_unknown`, `rl_stream_unknown` | GET `/api/pipeline/{ml,rl}-stream/desktop-qa-nonexistent-job` (a FIXED id) | a clean 404, OR the well-formed pending stream today's handler sends (`event: status` `{"status":"pending"}` < 2 s, then `: heartbeat` every 2 s, first < 6 s), not content-encoded. Not a hang |
| `post_streams_routable` | GET (never POST) `/api/ml/train/stream`, `/api/analytics/backtest/stream`, `/api/analytics/wfo-backtest/stream` + a non-existent sibling | 405 on the three (route exists, method rejected before any handler code runs: Starlette matches the path, finds the method missing and answers 405 without resolving dependencies or reading the body; Next's route handlers export only POST and Next answers 405 itself), 404 on the sibling (negative control). A 404 JSON envelope on the real paths is WARN (not provable by GET) |

Why the unknown-job stream is not a 404 today: `services/ui-api/routers/pipeline.py` `ml_training_stream` /
`rl_training_stream` call `_get_or_create_queue(job_id)` for any id, then yield `event: status` and a heartbeat
per 2 s queue timeout until the client disconnects (checked every loop) or 120 idle beats (about 4 min). The
fixed id means repeated runs reuse one queue entry. Informational field `upstream_release`: whether a front
proxy releases its socket to :8010 after the client closes (lsof on the proxy pid).

Exit 0 = every check PASS/WARN on every base.

## 4. App E2E driver: `scripts/desktop_qa/run_selftest.py`

```bash
$P scripts/desktop_qa/run_selftest.py --out <dir>                    # static checks + --self-test
$P scripts/desktop_qa/run_selftest.py --live --out <dir>             # + single instance + 30 s idle RSS/CPU
$P scripts/desktop_qa/run_selftest.py --app /Applications/SuryaDhana.app --require-app --expect-autostart on
```

App discovery: `--app`, else `desktop/src-tauri/target/{release,debug}/bundle/macos/SuryaDhana.app`, else
`/Applications`, `~/Applications`. No app = SKIP (FAIL with `--require-app`).

| Check | PASS |
|---|---|
| `bundle` | Info.plist `CFBundleIdentifier == ai.suryadhana.terminal`, executable present, bundle < 25 MiB (`--max-mb`) |
| `codesign` | `codesign --verify --deep --strict` rc 0 (ad-hoc accepted; signature kind reported) |
| `autostart` | read only: the LaunchAgent(s) that start a SuryaDhana .app (the stack's watchdog/awake agents excluded), whether it points at THIS app, RunAtLoad, `launchctl print gui/<uid>/<label>`. `--expect-autostart on|off|any` (default any = report) |
| `self_test` | `<app>/Contents/MacOS/<exe> --self-test <json>` exits 0 within `--timeout` (90 s) and the JSON has every check ok. D2's shape `{passed, checks:[{name, ok, detail, ms}], meta}` is accepted (also `{ok, checks}` and dict forms); stdout's last JSON object is the fallback |
| `single_instance` (`--live`) | a second normal launch exits on its own while the first stays the only instance |
| `idle_resources` (`--live`) | app + its WebKit XPC processes (WebContent / Networking / GPU, attributed with macOS `responsibility_get_pid_responsible_for_pid`, the Activity Monitor rule): peak RSS < 500 MB and mean CPU < 3 % over `--idle` 30 s after `--warmup` 12 s (AC-13); phys_footprint reported too |

Safety: it never launches while any SuryaDhana process is running (never alongside the owner's app); every process
it starts runs in its own session and is terminated in `finally` (SIGTERM, then SIGKILL), plus a sweep for any new
process of this bundle's executable; `--live` launches with `SURYADHANA_NO_AUTOSTART=1` so D2's first-run "enable
Launch at Login" never runs from the harness (`--allow-autostart-change` to drop it), and FAILS if the login
agent changed anyway. A normal launch still saves the app's own window/session state under
`~/Library/Application Support/ai.suryadhana.terminal`. D2's `--self-test` mode is isolated by D2 (temp state,
no single-instance lock, autostart read only, notifications and external opens recorded, stack start/stop
refused).

Exit 0 = no FAIL (SKIPs allowed unless `--require-app`).

## 5. Contract and static-build tests

```bash
$P -m pytest tests/integration/test_desktop_qa_harness.py tests/integration/test_desktop_contract.py -q   # part of `pytest tests`
DESKTOP_QA_BUILD=1 $P -m pytest tests/integration/test_desktop_static.py -q                              # opt-in, ~15 s
```

`test_desktop_contract.py` (static, no build, skips per test until the checked file exists):
- Rust Go-menu table `desktop/src-tauri/src/pages.rs` == `page.tsx` COMMAND_PAGES (ids, codes, labels, order),
  covers every TAB_ID; its ⌘1-⌘9 map == the UI's ALT+1...9 page strip; D4's `ui/components/desktop/pages.ts`
  PAGE_META == COMMAND_PAGES
- the remote capability (incl. D2's runtime one `capabilities-runtime/terminal-remote.json`) has origin exactly
  `http://127.0.0.1:8010`, resolves (via `gen/schemas/acl-manifests.json`) to exactly the nine `shell_*`
  commands, grants no fs/shell/process/http permission and no plugin/core permission unless listed in
  `REMOTE_EXTRA_ALLOWED` (a PM-approved amendment; empty = contract v1), and no boot command; boot commands go
  to local content only; build.rs AppManifest == the 14 contract commands == `generate_handler!`
- `tauri.conf.json`: identifier `ai.suryadhana.terminal`, productName, a CSP (not null)
- `ui/lib/platform` references exactly the nine command names, the `__SURYADHANA_SHELL__` marker and the
  `suryadhana:shell` event, and no boot command
- `scripts/build_ui.sh` exists and is executable; `services/ui-api/static_ui.py` exports `mount_static_ui`;
  once the PM applies D1's patch, `main.py` calls it exactly once, after every router/route registration
  (skips until applied)

`test_desktop_static.py` (`DESKTOP_QA_BUILD=1`): `scripts/build_ui.sh --out <tmp>` succeeds; `index.html`,
`_next/static` JS chunks, every asset `index.html` references exists, no `api/` route-handler output,
`build-info.json` fields, the release id baked into the bundle, `.gz` siblings byte-identical when
decompressed, and `ui/.next-prod`, `ui/tsconfig.json`, `ui/next-env.d.ts` untouched (content fingerprints
before/after).

## 6. Scratch topology for baselines before switchover

```bash
S=<scratch dir>
scripts/build_ui.sh --out $S/export                       # ~15 s, never builds inside ui/
$P scripts/desktop_qa/scratch_server.py --ui $S/export --port 8092 &      # ports 8090-8099 only, loopback only
# negative control: the same export with one injected failure
$P scripts/desktop_qa/scratch_server.py --ui $S/export --port 8096 --inject '^/api/desk/status$=500' &
```

The scratch server serves the export like D1's ui-api mount (index no-cache, `_next/static` immutable, `.gz`
when accepted, `404.html`), and forwards `/api/*` (any method, streamed chunk by chunk), the `/api/*` WebSocket
and `/health /ready /live /metrics /version` to `--backend` (live :8010). Against the live :8010 backend (the
default) it forwards no writes: every non-GET/HEAD/OPTIONS `/api` call is answered 403 here (a same-origin write
relayed with X-Forwarded-Host would pass the live guard), unless `--allow-mutations`; and it accepts then closes
(1008) a page's WebSocket instead of relaying it, unless `--allow-live-ws` (R-OPS-08/-09; `/__qa/health` shows
both). `--block-mutations` forces the write block against any backend. Every browser context from
`probe.new_qa_context` (ui_audit, parity, ui_perf, e2e_multiwin, e2e_compare, delta_probe) mocks every WebSocket,
so a run opens 0 live monitor sockets (`parity.py --live-websockets` opts out, scratch backends only). Checked in
real browsers on 25 Oct (round 4, local http and ws servers on ephemeral ports only): in Chromium and in WebKit a
page's socket opens against the mock with 0 connections reaching the server and its URL recorded, while
`live_websockets=True` (the control) reaches it once. `ui_perf.py` has no opt-out, so its post-load idle window
never includes live-tick rendering. Because of the write block, the compute-only POSTs below get 403 behind a
default scratch server against live. Stop every scratch server you start.

Pages that POST on load (compute-only, their own UI behaviour, nothing recorded): `POST /api/alpha/scan` (scan
over cached OHLCV), `POST /api/mcx/ticket` ("PAPER pricing only ... Records nothing"),
`POST /api/options/strategy/analyze` (payoff/Greeks math).

## 7. Baselines (24 Oct 2026)

BASELINE_PLACEHOLDER
