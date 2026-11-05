# G-LOGIN — ICICI Direct auto-login with TOTP (static review, 26 Oct 2026)

Agent: G-LOGIN · SuryaDhana GOLD program · review window 05:40–06:30 IST, Monday 26 Oct 2026 (a trading day; the
08:00 login job was still 2 h away and was not touched).

**Verdict in one line:** the code already does zero-touch TOTP login end to end and is unit-tested against the RFC
6238 vectors; the only missing piece is the secret. Store it (Keychain preferred, `.env` acceptable once the file is
`chmod 600`), run ONE attended `--force` login outside market hours to prove the real TOTP panel submits the way the
code expects, and the 08:00 job becomes silent. Two code-level risks remain (the Submit handler of the TOTP panel is
inferred, and a stale secret would be retried every morning); both have cheap mitigations below. Nothing proposed
here changes the 08:00 job, the start-up check or the freeze windows.

Read this with: `shared/icici_login.py`, `scripts/daily_session_refresh.py`, `services/ui-api/icici_admin.py`,
`services/ui-api/routers/positions.py`, `services/ui-api/routers/config.py`, `scripts/master_controller.py`
(lines 1809–1904, 1936–2004, 2514–2535, 2685–2693), `tests/unit/test_icici_login.py`,
`tests/integration/test_icici_login_browser.py`, `docs/IMPROVEMENT_LOG.md` (14 Oct entry),
`reports/desktop_app/FEATURE_PARITY.md` (rows 5, "TOTP vs SMS OTP", action 19).

---

## 0. What was verified live (and what was not)

Hard rules kept: read-only on the repo (only this folder was written), no POST/PUT/DELETE to any local service, no
login started, no ICICI credential used, no `.env` value printed, no restart. The only local calls were `GET
:8008/health`, `GET :8008/api/scheduler/status` and `GET :8010/api/config/setup-status` (booleans only).

| # | Item | How | Result |
|---|---|---|---|
| V1 | Secret storage state | `grep -c '^ICICI_TOTP_SECRET=' .env`; `security find-generic-password -s suryadhana -a ICICI_TOTP_SECRET` (attributes only, no `-w`) | **Not in `.env` (0 lines), not in the Keychain** ("could not be found"); no `suryadhana` items at all |
| V2 | Other login keys present (names only) | `grep -c '^KEY='` | ICICI_CLIENT_ID, ICICI_PASSWORD, ICICI_MOBILE, ICICI_API_KEY, ICICI_API_SECRET, ICICI_SESSION_TOKEN, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID = 1 each; ICICI_AUTO_LOGIN absent (default **enabled**) |
| V3 | `.env` permissions | `ls -l .env` | **`-rw-r--r--` (0644)** — RUNBOOK §2 says `chmod 600`; never applied. The guarded writer preserves whatever mode the file has (icici_admin.py:309, 332), so one `chmod 600` sticks |
| V4 | 08:00 job scheduled and untouched | `GET :8008/api/scheduler/status` | `icici_session_refresh`, "ICICI Session Refresh (TOTP login)", `next_run_ist 2026-10-26T08:00:00+05:30`, `last_status null` (controller restarted Sat 25 Oct 21:18; history row absent) |
| V5 | Setup checklist | `GET :8010/api/config/setup-status` | `totp: ok=false` ("no TOTP secret: the 08:00 login cannot finish by itself"); `icici_credentials: ok=true` ("last check 2026-10-23T08:08: refreshed (logged in, token applied via ui-api)"); `autostart: ok=false` (the checklist looks for `com.suryadhana.stack.plist`; the 19 Oct LaunchAgents use other names — a stale check, not a login problem) |
| V6 | Last login outcome | `.session_cache.json` (token masked by the script) | `2026-10-23T08:08:17 refreshed "logged in, token applied via ui-api"` |
| V7 | Last failure screenshot | `.logs/icici_login_failure.png`, 23 Oct 08:05 | ICICI's **"Verify OTP"** panel: "Enter 6 digit OTP sent on 88XXXXXX86 & s****3@gmail.com", account holder's name, six underlined single-character boxes, orange **Submit**, **Resend OTP** link, back arrow. Right column: SEBI static-IP notice (see Q4). So on 23 Oct a first attempt timed out on the SMS panel at 08:05 and the retry logged in at 08:08 — consistent with the code's one-attempt rule |
| V8 | OTP quiet-window file | `data/icici_otp_last_ask.json` | `at = 0` (reset on Sat 25 Oct 20:47): no quiet window will suppress today's ask |
| V9 | Block file | `.icici_login_block.json` | absent (credentials not blocked) |
| V10 | TOTP implementation | `pytest tests/unit/test_icici_login.py -q` | **16 passed** (RFC 6238 Appendix B vectors for 59, 1111111109, 1111111111, 1234567890, 2000000000 s; otpauth:// parsing; env-before-Keychain precedence; panel classification) |
| V11 | Mac clock vs internet | HTTP `Date` of apple.com vs `time.time()` | local − server = **+0.3 s** (1 s resolution). TOTP tolerates ±30 s; no drift risk today |
| V12 | Headless browser | `/Applications/Google Chrome.app`, `pip show playwright` | Chrome present; Playwright **1.60.0** in jupyter_env (the job launches `channel="chrome"`) |
| V13 | ICICI public login page | `GET https://api.icicidirect.com/apiuser/login?api_key=<dummy>` with a browser UA | 200 in 0.28 s, body = `Public Key does not exist.` (26 bytes). **The form markup cannot be fetched without the owner's real API key**, and using it is forbidden for this review → selectors remain verified only by the 14/23 Oct real runs (§5) |
| V14 | ICICI official FAQ "Login Authenticator" | WebFetch | 200; quotes in §2 |
| V15 | ICICI official FAQ "Is TOTP option available in ICICI Direct API?" | WebFetch | 200: "The TOTP option is live in ICICIdirect API login page. Users can enable it by visiting the settings option at homepage" |
| V16 | ICICI article "About Two Factor Authentication (2FA) login" (27 Sep 2022) | WebFetch | 200; OTP valid 5 min; **"If user generates OTP consecutively 10 times without using it, then trading account will get locked"** |
| V17 | ICICI FAQ "different ways to log in" | WebFetch | 200: lists OTP (SMS/e-mail) and "Time-based One-Time Password (TOTP) generated through Google Authenticator app" |
| V18 | community.icicidirect.com/totp-login and /introducing-google-authenticator | WebFetch then curl (UA, 25 s) ×2 each | **UNVERIFIED**: ECONNRESET / timeout both times from this machine |
| V19 | ICICI FAQ "What is a Static IP?" | WebFetch | 200 but only the definition is in the page body; the date/enforcement answers are not served statically → UNVERIFIED (Q4) |
| V20 | Controller log for 23 Oct | `.logs/master-controller.log` | rotated at the 25 Oct 21:18 restart: no login lines survive (the `.session_cache.json` and the screenshot are the evidence) |

---

## 1. How the login works today (so the two readers share one picture)

**Terms.** *Session token*: the daily key ICICI's Breeze API needs; ICICI issues it only after a browser login on
`api.icicidirect.com/apiuser/login?api_key=…` and redirects to the app's registered URL with `?apisession=<token>`.
*OTP*: a one-time code ICICI texts/e-mails. *TOTP* (RFC 6238): a 6-digit code an authenticator app computes every
30 s from a shared secret ("setup key", base32 text) and the clock — no SMS involved. *Setup key*: the secret in
human-readable base32, shown by ICICI next to the QR code when the authenticator is registered.

**Pipeline (unchanged by this review).**

1. `master_controller.icici_session_refresh()` fires **08:00 IST Mon–Fri** (CronTrigger, `misfire_grace_time` 4 h,
   `max_instances=1`) and once 45 s after a controller start on a trading morning (`startup=True` → `--quiet-minutes
   30`). Opt-out `ICICI_AUTO_LOGIN=0` (absent today → enabled). It runs
   `python scripts/daily_session_refresh.py --headless` as a subprocess with a **480 s** kill timer.
2. The script merges `{**os.environ, **read_env_file()}` (`.env` wins), **checks the current token with Breeze
   first** (`check_token`, up to 3 network retries); `valid` → exit 0 "valid", no login. `network` → "unreachable",
   no login (an outage never triggers an OTP). Otherwise it reads `ICICI_CLIENT_ID`, `ICICI_PASSWORD`,
   `ICICI_TOTP_SECRET` through `read_secret()` = env/.env first, then macOS Keychain (`security
   find-generic-password -s suryadhana -a <NAME> -w`, darwin only, 10 s timeout, "" on any failure).
3. `browser_login()` (Playwright, installed Chrome, headless): fills `#txtuid`, `#txtPass`, ticks `#chkssTnc`, clicks
   `#btnSubmit`, waits for `#pnlOTP input[tg-nm=otp]`, reads the panel text and classifies it (`totp` / `sms` /
   `unknown`).
   - **No secret** (today): on a `totp` panel it clicks "Having issues? Verify with OTP" (`#pnlOTP
     a[onclick*=goforotp]`), waits for the SMS panel, then `telegram_otp_provider` writes
     `data/icici_otp_request.json`, messages you, and polls `data/icici_otp.json` for **300 s** for the digits the
     bot stores when you reply.
   - **With a secret**: `fresh_totp()` (waits for the next 30 s window if < 5 s remain) → one digit per box →
     `submitotp()` (or a visible Submit button) → **one attempt, never retried**.
   - The redirect to the non-ICICI app URL is intercepted (`context.route`), the token extracted from the query,
     fragment or POST body, and a local success page served so the browser never dials the redirect host.
4. The token is POSTed to ui-api `/api/positions/session-token` with `fresh_login: true` (retried ≈ 2 min; ui-api
   saves it to `.env` through the guarded writer, checks it, pushes it to data-service); if ui-api never answers,
   the script writes `.env` itself and pushes to data-service directly ("outcome": "warning").
5. The controller alerts on Telegram ("ICICI session refreshed" / "ICICI login needs you" / "FAILED"), reconnects
   data-service's live quotes (`_ensure_live_prices`, 3 tries), records the job in `data/.scheduler_history.json`.

**Safety rules already in place and relevant to TOTP:** one code attempt per run; a rejected password writes
`.icici_login_block.json` (fingerprint of user+password) and blocks unattended retries; one login at a time
(`_login_running()` lock shared by the 08:00 job, `/login` and the HTTP trigger); a transient failure gets one retry
after 300 s; the watchdog never restarts master-controller while `daily_session_refresh.py` runs (max 10 min defer).

**Freeze windows:** `FREEZE_WINDOWS = ((07:45, 09:20), (18:30, 21:15))` in the controller is used only to place the
backup catch-up; the watchdog's `in_freeze()` governs restarts. Neither reads anything TOTP-related.

---

## 2. (1) Owner procedure: getting the authenticator setup key from ICICI Direct

### What ICICI publishes (verified pages, quoted verbatim)

FAQ "What is Login Authenticator? How to enable/disable…" (icicidirect.com/faqs/my-account/…, V14):

- Enable: "Log in to your ICICI Direct account" → "Navigate to the 'Settings'" → "Select the option to enable 'Login
  Authenticator' and choose to proceed with Google Authenticator" → "Download the Google Authenticator app on your
  smartphone if you haven't already" → **"Open the app and scan the QR code displayed on the ICICI Direct screen.
  Alternatively, manually enter the provided key"** → "The authenticator setup is now complete".
- Login: "after entering your user ID and password/ PIN, you will be prompted to enter the six-digit code from your
  Google Authenticator app. Enter the current code to complete the login."
- Disable: "Log in" → "Navigate to the 'Settings'" → "Select the option to 'Disable Login Authenticator'" → "Enter
  your Password/ PIN to disable Login Authenticator".

FAQ "Is TOTP option available in ICICI Direct API?" (V15): "The TOTP option is live in ICICIdirect API login page.
Users can enable it by visiting the settings option at homepage: https://www.icicidirect.com". This is the page the
08:00 job drives; the 14 Oct run saw its "Verify TOTP" panel, so the owner's account already has it on.

The FAQ gives no last-updated date, says nothing about what happens to an existing registration, lost phones or the
SMS fallback. The two community posts that would (V18) could not be fetched.

### Option A (official): re-register the Login Authenticator and copy the key

The key is shown **only during registration**. Google Authenticator does not display a stored secret, so an account
that is already enabled must be re-registered.

1. Pick a quiet moment **outside 07:30–09:30 and outside market hours** (a re-registration changes the secret; if the
   08:00 job were to run in between with a half-done setup it would simply fall back to SMS, but keep it simple).
2. On a desktop browser: log in at icicidirect.com (user ID or mobile + PIN, then today's TOTP or OTP).
3. **Settings → "Disable Login Authenticator" → enter Password/PIN.** From this moment the existing Google
   Authenticator entry for ICICI is dead (the server no longer holds that secret). Logins fall back to SMS/e-mail OTP
   until step 4 completes. *(Inference: the FAQ does not state it, but a disable/enable cycle necessarily issues a
   new secret; treat the old entry as invalid.)*
4. **Settings → "Login Authenticator" → proceed with Google Authenticator.** ICICI shows a QR code and, beside or
   under it, the **manual "key"** (the FAQ's "manually enter the provided key"). This key is the TOTP secret.
   - Scan the QR with Google Authenticator on the phone (delete the dead ICICI entry first to avoid two look-alikes).
   - Copy the key text exactly (letters A–Z and digits 2–7, spaces or groups of four are fine; the parser strips
     spaces/dashes and ignores case). Do not photograph the screen to iCloud Photos; type or paste it straight into the
     storage step (§3) or a password manager.
   - If ICICI asks for a confirmation code to finish, type the phone's current code.
5. Store the key (§3), run the attended test (§5.4).
6. Both the phone and SuryaDhana now derive identical codes from the same secret; either can be used; neither
   invalidates the other. Re-registering again later (new phone, "reset TOTP") invalidates **both** at once — update
   SuryaDhana the same day or the 08:00 job will see "Invalid TOTP" and fall to "needs you" (§5.3, R4).

### Option B (no ICICI change): export the secret from Google Authenticator

Google Authenticator → ⋮ → "Transfer accounts" → "Export accounts" → tick only the ICICI entry → it shows a QR whose
payload is `otpauth-migration://offline?data=<base64 protobuf>`. Decoding it on this Mac (offline, e.g. a small
Python script with the public `otpauth-migration` protobuf schema, or the open-source `otpauth` CLI) yields the
bare secret. **Pros:** no re-registration, the phone keeps working, ICICI unaware. **Cons:** the payload carries every
selected account's secret; decode only on this Mac, never in a web decoder, delete the image afterwards; the result's
`digits/period/algorithm` fields should be checked (ICICI is expected to be SHA-1 / 6 digits / 30 s, the Google
Authenticator defaults; anything else is a red flag to prefer Option A). UNVERIFIED from here (needs the phone).

### Which to choose

Option A if the owner wants an official, documented path and does not mind a 5-minute re-registration (and the
10-OTP lockout rule of V16 is irrelevant to it). Option B if minimal disruption matters and the owner is comfortable
decoding a QR offline. Both end with the same 16–32-character base32 string.

---

## 3. (2) Storage options and what the code actually reads

### Precedence (verified in code and by test `test_read_secret_prefers_env_then_keychain`)

`read_secret("ICICI_TOTP_SECRET", env)`: **(1)** the merged environment — process env overlaid by `.env`, so a
`.env` line wins over an exported variable; a non-empty value is returned without touching the Keychain; **(2)** on
macOS only, `security find-generic-password -s suryadhana -a ICICI_TOTP_SECRET -w` (10 s timeout; `""` on non-zero
exit, timeout or OSError); **(3)** `""` → the login proceeds as today (SMS via Telegram). `parse_totp_secret` then
accepts base32 (any case, spaces/dashes, missing `=` padding) or a full `otpauth://totp/...?secret=...&digits=&period=
&algorithm=` URI; a malformed value ends the run **before any ICICI contact** with exit 2 "ICICI_TOTP_SECRET is
unusable: …" (no login attempt, no OTP, a Telegram "needs you").

The BRIEF/Telegram setup checklist (`routers/config.py: setup_checks`) applies the same order: `.env` value, else a
Keychain probe (`find-generic-password` without `-w`, 5 s).

### Side-by-side

| | `.env` `ICICI_TOTP_SECRET=…` | Keychain `security add-generic-password -U -s suryadhana -a ICICI_TOTP_SECRET -w` |
|---|---|---|
| Written by | the guarded writer (`persist_env_updates`: validated, atomic tmp+rename, mode preserved, re-read check) — **but `ICICI_TOTP_SECRET` is not in `ICICI_ENV_KEYS`** (icici_admin.py:90), so today the terminal's routes would refuse it ("cannot be changed from the terminal"); the controller's `write_env_value` path (no allowlist, protected-prefix check only) would accept it | the owner in Terminal; `-w` as the **last** option prompts for the value (nothing in argv, nothing in shell history); `-U` replaces an existing item |
| Read by | every service via python-dotenv (so the secret sits in the environment of data-service, ui-api and the controller too) and the script's plain parser; base32 never needs quoting; an otpauth URI holds `&`, `%`, `:` which the writer can store, but store the **bare base32** anyway (an issuer label with the user ID has no business in `.env`) | only the login script and the checklist probe, via `/usr/bin/security`; "By default, the application which creates an item is trusted to access its data without warning" (`security add-generic-password -h`), so the `security` tool that reads it later gets no GUI prompt while the login keychain is unlocked |
| At rest | plain text, **world-readable today (0644, V3)**; also copied into the owner's password manager per RUNBOOK §2 | encrypted with the login password; ACL-bound to `/usr/bin/security` |
| Survives `git` re-clone + RUNBOOK restore on the same Mac | yes, if the password-manager copy of `.env` was taken after the secret was added | yes (the login keychain lives in `~/Library/Keychains`, untouched by the repo) |
| Survives a **new Mac** built from the RUNBOOK | yes (from the `.env` copy) | **no** — RUNBOOK §6 lists "the macOS Keychain (unused by default)" among things not in git or backups; iCloud Keychain does not sync CLI-created generic passwords. Time Machine / Migration Assistant restores do carry it. **Add the one-liner to RUNBOOK §2's LOGIN-CRITICAL table** if Keychain is chosen |
| Failure mode when missing/locked | the next layer (Keychain) is tried | silent fallback to SMS: `read_secret` returns `""` for "not found" (rc 44) **and** for "keychain locked / access denied"; the run prints only "TOTP not configured". If the owner enables Keychain Access ▸ "Lock after N minutes of inactivity", the 08:00 job will text an OTP instead of using TOTP, with no clue why. (Mitigation M3 below: log the `security` return code.) |
| Blast radius of a leaked copy | `.env` already holds user ID + PIN; adding the seed makes the file a **complete login** (module docstring, icici_login.py:14–16) | a leaked `.env` is still not a full login |

**Recommendation:** Keychain for the secret (one Terminal line, no code change), `chmod 600 .env` regardless, and the
RUNBOOK line. If the owner prefers the BRKR form (§4), it should write `.env` through the guarded writer with the
allowlist extended by one key, and the page should offer the Keychain one-liner as the "safer" alternative it can
*detect* but not write (writing from ui-api would put the secret in `ps` argv for a moment and `security`'s `-w`
prompt needs a TTY).

---

## 4. (3) Design: BRKR "Enable auto-login" flow

Placement: a new panel **"Auto-login (TOTP)"** on BRKR (`ui/components/PortfolioSummary.tsx`), rendered in both the
connected and not-connected layouts (today the not-connected layout only has "Connect ICICI Breeze" + Notice + rules),
using the existing kit (`Panel`, `Label`, `Input`, `Btn`, `Chip`, `KV`, `Notice`, tokens `T.*`). No new page, no GO
code.

### 4.1 Backend (ui-api, loopback-only like everything else; the HTTP guard already refuses cross-site POSTs)

New router `services/ui-api/routers/icici_totp.py`, mounted at `/api/positions/totp` (or inside `positions.py`):

| Route | Body / query | Does | Returns |
|---|---|---|---|
| `GET /status` | `?reveal=1` optional | `read_secret` order; `.env` file mode; `.session_cache.json`; `ICICI_AUTO_LOGIN`; `login_running` (cheap `pgrep -f` of the watchdog's `LOGIN_RX`, or `data/icici_otp_request.json` age < 360 s) | `{configured, source: "env"\|"keychain"\|null, env_mode: "0644", auto_login_enabled, login_running, otp_pending, last_login: {at, status, detail}, next_run_ist}` and with `reveal=1` **`code`, `seconds_left`** computed server-side from the stored secret (never the secret itself) |
| `POST /preview` | `{secret}` | `parse_totp_secret` → `totp(spec, now)`; **stores nothing, logs nothing**; 400 with the parser's message on failure (the message never echoes the value: "TOTP secret is not valid base32", "unsupported TOTP algorithm") | `{valid: true, digits, period, algorithm, length, code, seconds_left}` |
| `POST /` (save) | `{secret, confirm_code}` | parse; **refuse unless `confirm_code` equals the current or previous-window code** (proves the owner compared with the phone); normalise to bare base32; `persist_env_updates({"ICICI_TOTP_SECRET": b32}, allowed_keys=ICICI_ENV_KEYS)` with the allowlist extended; `os.environ` updated; warn in the reply if `.env` is not 0600 | `{saved, persisted, persisted_reason, source: "env", env_mode}` |
| `DELETE /` | — | writes `ICICI_TOTP_SECRET=` (empty) through the same writer; tells the owner the Keychain command if a Keychain copy exists (ui-api must not run `security delete-…` unasked) | `{cleared, keychain_still_present}` |
| `POST /api/telemetry/icici-refresh` | `{force?: bool}` | server-side proxy (httpx, no `Origin`, loopback Host → the controller's guard admits it, exactly like `/api/telemetry/autopilot`) to `POST {MASTER_CONTROLLER_URL}/api/scheduler/icici-refresh` | the controller's `{started, detail}` |

Why the proxy: the desktop webview is pinned to the `http://127.0.0.1:8010` origin (desktop/src-tauri/src/policy.rs),
the controller has **no CORS by design** (test `test_guard_is_the_only_middleware_and_cors_is_gone`), so the page
cannot call :8008 directly. `MASTER_CONTROLLER_URL` is exported by `start-local.sh` (line 168), not by `.env`.

Validation (server is the authority; the client only pre-checks): strip whitespace and `-`; upper-case; charset
`[A-Z2-7]`, optional trailing `=`; length ≥ 16 after stripping (Google Authenticator keys are 16 or 32 characters;
some issuers 26/52); pad to a multiple of 8; `base64.b32decode(casefold=True)` must succeed; an `otpauth://` URI is
accepted and reduced to its `secret`. Reject lengths > 128.

### 4.2 Page flow (what the owner sees)

1. **Status strip** (always): chip `TOTP CONFIGURED · Keychain` / `TOTP CONFIGURED · .env` / `TOTP NOT SET` (amber);
   "08:00 job: enabled · next Mon 08:00 · last: 23 Oct 08:08 refreshed via ui-api"; a small `.env is 0644 — run
   chmod 600 .env` warning when applicable.
2. **Step 1 · Get the key**: three lines of §2 Option A with an `OPEN ICICI SETTINGS ↗` button (`openExternal`,
   like `LOG IN TO ICICI ↗`) and a link to the FAQ.
3. **Step 2 · Paste the key**: one monospace `Input` ("setup key or otpauth:// link"), `type=password` with a SHOW
   toggle; on change (debounced 400 ms) → `POST /preview`; below it a large **"Current code 482 913 · 17 s"** with a
   30 s bar that re-polls on rollover, and the instruction "Open Google Authenticator: the ICICI entry must show the
   same six digits. Wait for one rollover and check again." Parser errors show inline (never the value).
4. **Step 3 · Confirm and save**: a 6-digit `confirm` box ("type the code your phone shows now") and `SAVE` →
   `POST /` → chip turns green; the key input is cleared from React state. A second line offers the Keychain route:
   the exact one-liner in a copy box plus `DETECT` (re-fetches `/status`; shows `source: keychain`).
5. **Step 4 · Test**: `CHECK SESSION / LOG IN IF EXPIRED` → `POST /api/telemetry/icici-refresh` → inline "Started —
   watching…" then a poll (every 5 s, up to 8 min) of `GET /status` until `last_login.at` is newer than the click,
   plus `GET /api/positions/connection-status`; show `last_login.status` + `detail`, and `● LIVE` when the probe
   connects. Links: "open SYS log stream" (`/api/telemetry/logs/stream` already proxied). A secondary, confirm-gated
   `FORCE A NEW LOGIN (ends today's session)` appears only when `force` is supported (§4.3) and is disabled 09:00–15:30
   with a hover reason.
6. **Remove**: `DISABLE AUTO-LOGIN` → `DELETE /` (confirm dialog).

### 4.3 What the "test" button really runs — guards and the valid-token short-circuit

`POST /api/scheduler/icici-refresh` (master_controller.py:2685): returns `{"started": false, "detail": "already
running"}` if the job lock is held; else `asyncio.create_task(icici_session_refresh())` and returns at once with
`"running — watch the System page log"`. The task then: skips if `_login_running()` (also covers a Telegram `/login`
in flight); skips if `ICICI_AUTO_LOGIN=0`; runs `daily_session_refresh.py --headless` (no `--force`, no
`--quiet-minutes`); on rc 0 logs/alerts ("refreshed" → Telegram "ICICI session refreshed" + `_ensure_live_prices`;
"valid" → just the reconnect check; "skipped" → return); rc 2 → `_alerts.critical("ICICI login needs you", …)`;
rc 3 → one retry after 300 s then `critical("ICICI session refresh FAILED")`.

Consequences for the design:

- **If today's token still works, the button proves nothing about TOTP**: the script exits 0 "valid: current token
  still works" in ~1–10 s without opening a browser. That is a fine *session check* and should be labelled as such.
- To exercise the TOTP path on demand the script needs `--force` (it then logs in even with a valid token **and
  ICICI ends the previous session**, so live quotes drop for 1–2 min until the new token propagates). The controller
  endpoint has no such option today: add `?force=1` → `_run_session_refresh(("--force",))`. That is a one-line
  controller change and needs a controller restart **outside the freeze windows** (not 07:45–09:20, not
  18:30–21:15). Until then the first real TOTP exercise is the attended test (§5.4) or simply tomorrow's 08:00 run.
- With `--force` the credentials block (`.icici_login_block.json`) is bypassed (`not args.force` in the condition at
  daily_session_refresh.py:381) — acceptable for an owner-pressed button, but the UI must say "ICICI rejected the
  user ID/PIN on <date>; forcing will try them once more" when the block file exists (available from
  `/api/config/setup-status`).
- **Result visibility defect:** on rc 2 ("needs you") the job returns normally, so `_track` records
  `last_status: "done"` and SYS shows a green "done" for a failed login. Fix: call `_mark_failed(JOB)` on rc 2 and
  after the rc 3 retry (3 lines). The page should not rely on SYS; `.session_cache.json` (`status`, `detail`, `at`) is
  the truth and is already exposed by `/api/config/setup-status` (`icici_credentials` check).
- Timing to show: valid check ≈ 1–10 s; fresh TOTP login ≈ 20–40 s page + 10–40 s Breeze check in ui-api + ≤ 2 min
  hand-off window; worst case 8 min (controller kill).

### 4.4 Tests to add (mirroring the existing style)

- `services/ui-api/tests/test_icici_totp_routes.py`: preview with the RFC vector secret at a frozen clock returns
  `287082` for t=59; bad base32 → 400 whose body does not contain the input; save refused without the matching
  confirm code; save writes exactly one `ICICI_TOTP_SECRET=` line to a tmp `.env`, keeps the 0600 mode, and is
  **refused** through the allowlist until the key is added (regression for the allowlist change); `status` never
  returns the secret (assert the base32 string is absent from the JSON for every route except `preview.code`).
- `scripts/tests/test_http_guard_controller.py`: `?force=1` passes `--force` to `_run_session_refresh` (fake), and
  the cross-site refusal still holds.
- `ui/components/__tests__/pages.check.ts`: the panel's chip text per `source` and the 09:00–15:30 disabling rule.
- `tests/unit/test_icici_login.py` already covers the parser; add a case for a 16-char key with spaces in groups of 4
  (Google's display format) and for an `otpauth://` URI with `%20` in the label.

### 4.5 Deployment order (so the 08:00 job is never in the way)

1. Owner stores the secret (Keychain one-liner, or the BRKR form once shipped) — no restart needed: the script re-reads
   `.env` and the Keychain on every run.
2. ui-api change + `./start-local.sh build-ui` + ui-api restart: allowed any time, but avoid 07:55–08:10 because a
   ui-api restart during the token hand-off turns a clean "refreshed via ui-api" into the `.env`-only warning path.
3. Controller `force` + `_mark_failed` change: restart outside both freeze windows (e.g. 16:00–18:15).
4. Attended test (§5.4), then leave the 08:00 job to itself.

---

## 5. (4) Review of the TOTP branch against the real ICICI panel

### 5.1 What is proven by real runs (not by the fake page)

- 14 Oct (IMPROVEMENT_LOG, memory): after user ID/PIN the real page showed **"Verify TOTP: use your Google
  authenticator app…"** with **"Having issues? Verify with OTP"**; `browser_login` found `#pnlOTP a[onclick*=goforotp]`
  and clicked it, the SMS panel appeared, the Telegram round trip produced the token at 14:43.
- Because `page.wait_for_selector(CODE_BOXES)` (`#pnlOTP input[tg-nm=otp]`) runs **before** the panel is classified
  (icici_login.py:275–287) and the 14 Oct run got past it on the TOTP panel, the **TOTP panel does contain the six
  `tg-nm=otp` boxes inside `#pnlOTP`**. The fill loop (one digit per box) therefore targets the right inputs.
- 23 Oct screenshot (V7): the SMS panel is six single-character boxes + orange Submit, which the same selectors and
  `submitotp()` drove successfully on 14 and 23 Oct.
- `classify_code_panel("Verify TOTP Use your Google authenticator app …")` → `totp` (regex `\bTOTP\b|authenticat|
  time[\s-]*based`, checked before the `sms` regex, so the "Verify with OTP" link text cannot flip it to `sms`).
  Unit-tested with the real wording in `test_authenticator_panel_with_secret_uses_the_secret` (fake page mode
  `realtotp`, which copies the 14 Oct wording).

### 5.2 What is still inferred

- **The Submit handler of the TOTP panel.** `_submit_code` calls the page's global `submitotp()` if it exists, else
  clicks a visible button in `#pnlOTP`. On the SMS panel `submitotp()` is right. If ICICI's TOTP panel wires its
  button to a *different* function (say `submittotp()`), the code would still find the global `submitotp` (defined
  for the SMS flow) and call it — possibly posting the authenticator code to the SMS-OTP verifier → "Invalid OTP" →
  `LoginNeedsHuman` → exit 2 → Telegram "needs you", no retry (safe, but not zero-touch). **Only the attended test
  can settle this** (§5.4). Hardening that costs nothing: when `mode == "totp"`, prefer clicking the panel's visible
  Submit button and fall back to `submitotp()` only if no button is visible; or read the button's `onclick` and
  `page.evaluate` that expression.
- Whether ICICI's TOTP verification tolerates the previous 30 s window. `fresh_totp(min_remaining=5)` plus ~1 s of
  typing means the code is always submitted with ≥ 4 s of validity; with the +0.3 s clock (V11) this is comfortable
  even if ICICI accepts only the current window.
- Whether a wrong TOTP counts toward a lockout. The published rule (V16) is about generating OTPs (10 unused → lock);
  nothing is published for wrong authenticator codes. The code's one-attempt rule keeps exposure at ≤ 1 wrong code
  per run, ≤ 2 runs per morning (08:00 + a possible start-up check).

### 5.3 Risk register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | TOTP panel's Submit is not `submitotp()` (§5.2) | low–medium | login ends "needs you" every morning; SMS path still available via `/login` | attended test; hardening above (prefer the visible button when `mode == "totp"`) |
| R2 | Panel text changes so `classify_code_panel` says `unknown` | low | with a secret, `unknown` still submits the TOTP (`mode != "sms"`), so harmless; without a secret the switch-to-SMS still runs (`mode != "sms"`) | none needed; keep the regex broad |
| R3 | ICICI shows the SMS panel directly although TOTP is on (policy change, API page differs) | low | the secret is ignored, the Telegram SMS path runs — today's behaviour | none; the log line "code panel: sms" tells |
| R4 | **Stale secret** (owner re-registered TOTP at ICICI, e.g. new phone, forgot SuryaDhana) | medium over months | one wrong code per morning, forever, with a misleading hint ("Send /login when you can reply with the SMS code" because the detail contains "TOTP"); `is_credentials_rejection` ignores it so no block file | **M1:** on "ICICI rejected the authenticator code", write `.icici_totp_block.json` (fingerprint of the secret); unattended runs then set `totp_spec=None` and use the SMS path until the stored secret changes; Telegram hint: "the TOTP secret no longer matches ICICI: re-register and update it on BRKR" |
| R5 | Keychain locked/denied at 08:00 (keychain auto-lock enabled, ACL prompt) | low | silent fallback to SMS | **M3:** print `security` rc in the script ("TOTP: keychain rc=36 (locked?)"), never the value |
| R6 | Mac clock drift > 30 s (NTP off after a long sleep) | very low | wrong code once per run | `fresh_totp` cannot fix clock error; add a one-line skew check against an HTTP `Date` to the run (optional) |
| R7 | A wrong code in the screenshot | certain on failure | the screenshot shows the 6 typed digits (already expired) + name + masked phone; stays in git-ignored `.logs/` | acceptable; mention in §7 |
| R8 | Two logins in the same minute (attended test while the 08:00 job runs, or `/login` from the phone) | low | the later login ends the earlier token | the controller lock covers its own two paths; the manual script is not locked against them — run the attended test outside 07:30–09:30 |
| R9 | Static-IP rule for API trading (notice on the login page, V7) | unknown | not a login risk today (23 Oct login from the home IP worked); could matter for LIVE later | Q4 for the owner |
| R10 | `.env` 0644 with the seed in it | certain if `.env` is chosen | any local process or user can read a full login | `chmod 600 .env` first; prefer Keychain |

### 5.4 The one attended test the owner should run

When: **after 15:40 today or any evening (not 07:30–09:30; the 18:30–21:15 window only restricts restarts, a login
there is fine but keep clear of 19:30 Desk / 19:50 shadow which read holdings)**. `--force` ends today's session: after
the close that is harmless.

```bash
cd /Users/sudheer/MahaKubera_108/SuryaDhana_AI
# store the secret first (Keychain; -w last → interactive prompt, nothing in argv/history)
security add-generic-password -U -s suryadhana -a ICICI_TOTP_SECRET -w
chmod 600 .env
# attended = visible Chrome window, forced login even if the token works; watch the console
/Users/sudheer/Desktop/jupyter_env/bin/python scripts/daily_session_refresh.py --force
```

Expected console (values masked by the script): `User 88•••••••• · TOTP configured · visible browser` → `submitted
user ID + password` → `code panel: totp` → `submitted authenticator code (single attempt)` → the window shows
"SuryaDhana: ICICI session captured" → `RESULT {"status": "refreshed", "detail": "logged in, token applied via
ui-api", "outcome": "ok", "via": "ui-api", "token": "xxx•••••"}`. The manual script sends no Telegram line (only the
controller alerts); BRKR turns `● LIVE` within 15 s.

What to watch and what each outcome means:

- `code panel: sms` with the secret present → ICICI is not asking for TOTP on the API page; check Settings ▸ Login
  Authenticator at icicidirect.com (R3).
- `ICICI rejected the authenticator code: Invalid …` → either the secret is wrong (compare the phone's code with
  `python -c` using `shared.icici_login` at the same second) or R1 (wrong submit handler). In the R1 case the
  screenshot `.logs/icici_login_failure.png` shows the TOTP panel with the digits typed and an error text; send the
  *wording* (not the image) to the next session.
- `ICICI_TOTP_SECRET is unusable` → the pasted key has a character outside A–Z/2–7 (typo, `0`/`O`, `1`/`I`).
- `blocked` or `needs_human` **before** the browser opens → the credentials block from an older rejection; not TOTP.
- Then confirm zero-touch for real: tomorrow 08:00 should produce the Telegram line "ICICI session refreshed" with no
  OTP prompt; `/status` should no longer list "ICICI unattended login (TOTP)" under "Setup to do".

---

## 6. (5) What the terminal and the app show during and after

**The contract today** (`iciciState.ts`, `iciciStatus.ts`, `icici_admin.PUBLIC_ERROR_KINDS`): `error_kind` is
`null` when connected, else `expired` ("ICICI refused the token: log in again"), `network` ("not a login problem: do
not log in again"), `credentials` (API key/secret missing or rejected), `unknown`. `needs_session_refresh` stays true
during a network outage, so every surface reads `error_kind` first. The header light, BRKR chip/notice, PORT banner,
BRIEF System line, the boot screen row and the menu-bar line all derive from it.

**During a login (08:00 or the button):** nothing in the contract says "a login is running". BRKR shows `NOT
CONNECTED` with `expired` wording and the `/login` advice; BRIEF says "expired: log in (Broker tab) or enable TOTP
auto-login"; only the SYS log stream (`[icici_session_refresh] …`), Telegram `/status` ("⏳ An ICICI login is
running" / "🔐 … waiting for your OTP") and `data/icici_otp_request.json` know. Proposed additive fields (no change to
`error_kind`): the new `GET /api/positions/totp/status` carries `login_running` and `otp_pending`; BRKR swaps the
amber chip for a cyan `AUTO-LOGIN RUNNING · since 08:00:03` and hides the "send /login" sentence while it is true
(a second login would void the first). The header tooltip can reuse the same field.

**After success:** ui-api's `/session-token` save invalidates the client and probe caches; the next 15 s poll flips
BRKR to `● LIVE · ICICI BREEZE`, the header light goes green once data-service's `/provider/status` says connected
(`_ensure_live_prices` pushes the token within ~10–60 s), BRIEF reads "connected", the bell inbox gets the
controller's "ICICI session refreshed" line (`data/notifications.jsonl`), Telegram gets the same.

**After a failure:** `error_kind` stays `expired`; the specific reason lives in `.session_cache.json` and surfaces
only through `/api/config/setup-status` → the BRIEF checklist ("ICICI daily session · last check 08:00: needs_human
(ICICI rejected the authenticator code …)") and Telegram's critical alert. BRKR should show that same `detail` line
under its notice (one extra fetch) and, with M1 in place, a chip `TOTP MISMATCH — re-register` so the owner is not told
to "send /login" for a problem `/login` cannot fix. With TOTP configured the generic `ICICI_KIND_TEXT.expired` ("send
/login (Telegram) or log in on the Broker tab") is still correct as a fallback action.

**During a network outage at 08:00:** unchanged and correct: the script exits "unreachable", no login, no OTP, the
job retries once after 300 s, and the pages say "ICICI unreachable (network)".

---

## 7. (6) Security notes

- **Secret at rest.** Keychain: encrypted, ACL to `/usr/bin/security`, not exported by backups of the repo. `.env`:
  plain text, currently **0644** (V3) → `chmod 600` before adding the seed; the writer keeps the mode. With the seed,
  `.env` = user ID + PIN + seed = a complete login (captcha aside); treat its password-manager copy accordingly. The
  seed is as sensitive as the phone's authenticator: never in Telegram, chat, screenshots, git (`.env` is ignored;
  the RUNBOOK's pre-commit grep already looks for `TOTP` in key names).
- **In memory / environment.** A `.env` secret is loaded by python-dotenv into data-service, ui-api and the controller
  (`os.environ`), i.e. three long-lived processes instead of one short-lived script. No route dumps the environment
  (`setup-status` returns booleans; `test_env_injection.py` guards the writer). Keychain keeps it out of all three.
- **Logs.** The script prints only `TOTP configured/not configured` and `submitted authenticator code`; the code
  value is never printed; the user ID is masked (`mask()`); the controller logs the `RESULT` line (status/detail,
  masked token). The Telegram bot echoes an SMS OTP as `48…13` only. ui-api's client-error masking already redacts
  `totp`/`otp`/`pin` keys (`reports/desktop_app/review/fix_round4b.md`). The new `/preview` and save routes must
  log nothing but key names; never accept the secret in a query string (uvicorn access logs would keep it).
- **Screenshots.** `.logs/icici_login_failure.png` (git-ignored) shows the account holder's name, masked phone/e-mail
  and, on a TOTP failure, the six typed digits of an already-dead code. Acceptable; do not attach it to reports or
  chats — quote the wording instead.
- **State files.** `data/icici_otp.json` / `icici_otp_request.json` are **not covered by `.gitignore`** (they exist
  only for ≤ 5 min during an SMS login and are unlinked in `finally`, but a crash could leave a 6-digit OTP on disk
  until the next run). Add `data/icici_otp*.json` to `.gitignore`; with TOTP they are never created.
- **Processes.** Writing the Keychain from ui-api would expose the value in `ps` argv for milliseconds; keep the
  Keychain write a Terminal one-liner with `-w` last (interactive prompt). The BRKR form writes `.env` only.
- **Browser.** The input is `type=password` with a show toggle; the preview POST stays on loopback; the value lives
  in React state only until save and is never put in `localStorage`/prefs. The desktop shell's policy already blocks
  the webview from reaching anything but `127.0.0.1:8010`.
- **ICICI side.** One code attempt per run; no retry of a rejected code; the 10-unused-OTP lockout (V16) disappears
  entirely once TOTP is used, because no OTP is generated.

---

## 8. Confirmation: the 08:00 job and the freeze windows are untouched

- Scheduler: `icici_session_refresh` CronTrigger `mon-fri 08:00 IST`, `misfire_grace_time=4h`, `coalesce=True`,
  `max_instances=1` (master_controller.py:2516–2524) and the start-up check (2526–2535) are not modified by any
  proposal here; `GET /api/scheduler/status` at 05:43 IST confirms `next_run 2026-10-26T08:00:00+05:30`.
- The script's behaviour at 08:00 changes only by data: with a secret, step 3 takes the `else` branch
  (`_submit_code(page, fresh_totp(totp_spec), "authenticator code")`) instead of `_switch_to_sms`; everything before
  (token check, network guard, block file) and after (hand-off, `.env` fallback, Telegram alerts, live-quote
  reconnect) is identical.
- Freeze windows: `FREEZE_WINDOWS` (controller, backup placement) and `in_freeze()` (watchdog) are unreferenced by
  the proposals. The only operational asks are *scheduling* asks: ui-api redeploy outside 07:55–08:10, controller
  restart (for `force`/`_mark_failed`) outside 07:45–09:20 and 18:30–21:15, attended test outside 07:30–09:30.
- Nothing proposed calls `scripts/daily_session_refresh.py` with new flags from the scheduled path.

---

## 9. Defects and nits found while reading (file:line)

1. `services/ui-api/icici_admin.py:90` — `ICICI_ENV_KEYS` lacks `ICICI_TOTP_SECRET`; the terminal routes cannot save
   it (by design today; must change for §4). The controller's `/password`-style writer would accept it.
2. `scripts/master_controller.py:1893–1899` — rc 2 ("needs you") leaves the job `done` in SYS/history; use
   `_mark_failed(JOB)`.
3. `scripts/master_controller.py:1896` — hint selection by `"OTP" in detail` misfires on "TOTP" (R4 wording).
4. `scripts/daily_session_refresh.py:271–273` — `is_credentials_rejection` does not recognise a rejected
   authenticator code; no block → a stale secret is retried daily (M1).
5. `shared/icici_login.py:122` — `read_secret` folds "not found" and "locked/denied" into `""` (M3).
6. `shared/icici_login.py:234–236` — `submitotp()` preferred over the visible button on every panel (R1 hardening).
7. `.gitignore` — `data/icici_otp.json`, `data/icici_otp_request.json` not ignored (§7).
8. `.env` mode 0644 vs RUNBOOK §2 (`chmod 600`).
9. `services/ui-api/routers/config.py:100` — autostart check looks for `com.suryadhana.stack.plist`; the 19 Oct
   LaunchAgents (`scripts/install_launch_agents.sh`) use other names, so BRIEF/Telegram report "Start after a restart:
   not ok" although the watchdog agents are installed. Cosmetic, but it sits next to the TOTP line the owner will read.
10. `scripts/icici_session_helper.py:37–45` — the legacy helper rewrites `.env` with a bare regex (no validation, no
    atomic rename); the brief forbade running it and nothing schedules it; consider retiring it so the guarded writer
    is the only `.env` writer.

---

## 10. Open questions for the owner

- Q1 Which storage: Keychain (recommended; one Terminal line; add to RUNBOOK §2) or `.env` via the BRKR form (needs
  the allowlist change and `chmod 600`)? Or both (Keychain now, form later)?
- Q2 Option A (re-register at ICICI, dead phone entry for a few minutes) or Option B (export from Google
  Authenticator, decode offline)?
- Q3 Is the attended `--force` test acceptable this evening (it ends today's session after the close)? If not, the
  first zero-touch attempt is tomorrow 08:00 with the SMS path as automatic fallback only if the TOTP step fails before
  typing a code (a *rejected* code ends the run "needs you" → `/login` from the phone).
- Q4 ICICI's login page carries a notice that "the use of a static IP for API-based trading is to be made mandatory
  from 1st April 2026" (FAQ: icicidirect.com/faqs/fno/what-is-a-static-ip; the answer body could not be fetched).
  Logins from the home IP still worked on 23 Oct. Does the owner know whether this applies to order placement only,
  and whether ICICI has registered an IP for this app? It does not affect PAPER mode; it will affect LIVE.
- Q5 Should the controller get the `?force=1` option (requires one restart outside the freeze windows) so BRKR can
  exercise TOTP on demand, or is "check session / log in if expired" enough?
- Q6 Should a TOTP mismatch (M1) fall back to SMS automatically on later mornings, or stop and wait for the owner?

---

## Appendix A — ICICI pages consulted

| Page | Status | Used for |
|---|---|---|
| https://www.icicidirect.com/faqs/my-account/what-is-login-authenticator-how-to-enable-disable-the-login-authenticator-how-to-login-using-login-authenticator | 200 | enable/disable/login steps, "manually enter the provided key" |
| https://www.icicidirect.com/faqs/fno/is-totp-option-available-in-icici-direct-api | 200 | TOTP live on the API login page; enabled from homepage Settings |
| https://www.icicidirect.com/faqs/my-account/what-are-the-different-ways-to-log-in-to-the-icici-direct-platform | 200 | login methods; TOTP via Google Authenticator |
| https://icicidirect.com/futures-and-options/articles/two-factor-authentication-2fa-login | 200 (27 Sep 2022) | OTP validity 5 min; 10 unused OTPs lock the account; QR web login |
| https://www.icicidirect.com/faqs/fno/what-is-a-static-ip | 200 (answers not in body) | static-IP notice (Q4) |
| https://community.icicidirect.com/totp-login | timeout ×2 | UNVERIFIED |
| https://community.icicidirect.com/introducing-google-authenticator | timeout ×2 | UNVERIFIED |
| https://api.icicidirect.com/apiuser/login?api_key=<dummy> | 200, "Public Key does not exist." | markup not fetchable without the real key |

## Appendix B — files in this folder

- `REPORT.md` (this file)
- `icici_login_page_public.html` — the 26-byte public reply of V13 (kept as evidence)
