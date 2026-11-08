# RUNBOOK — restore SuryaDhana on a fresh (or wiped) Mac

Written 14 Oct 2026 (Bloomberg program F1.2); updated 25 Oct 2026 for the desktop program (the terminal UI
is a static release served by ui-api on :8010, the SuryaDhana.app desktop shell, the server-side settings
store). Target: from a blank macOS login to a working terminal + jobs in under an hour, assuming you have
(a) this repo and (b) a backup from `data/backups/duckdb/` (nightly, 02:15 job: the DuckDB plus the settings
store `ui_prefs-YYYYMMDD.sqlite`) or any `data/snapshots/evening/` copy.

The stack today: **3 core processes**, all on 127.0.0.1 only: data-service :8001, ui-api :8010 (the API
and the terminal UI from `ui/dist/current`), master-controller :8008. The Next server on :3000 is optional
(dev UI, and the one-time settings migration in §8); it is not the terminal any more.

**Backup freshness:** the 02:15 backup is built from the 19:20 evening snapshot, so it lags the
20:30 F&O catch-up and 20:45 results ingest of that evening — backups lag **≤1 trading day** of
positions/results data. The next EOD pipeline run (18:30) refills the gap automatically.

## 0. Prerequisites
```bash
# Homebrew python (the env below was built on it). Guard against brew autoremoving deps:
export HOMEBREW_NO_AUTOREMOVE=1
brew install python@3.13 node@20

# The canonical Python env — ALL repo code runs on this exact path:
#   /Users/sudheer/Desktop/jupyter_env
# If it is gone, recreate and reinstall (shared across projects — install ONLY from requirements):
python3.13 -m venv /Users/sudheer/Desktop/jupyter_env
/Users/sudheer/Desktop/jupyter_env/bin/pip install -r requirements.txt

# Headless Chrome for the ICICI login automation:
/Users/sudheer/Desktop/jupyter_env/bin/python -m playwright install chromium
```

## 1. Clone, frontend deps, build the terminal UI
```bash
git clone <repo> ~/MahaKubera_108/SuryaDhana_AI && cd ~/MahaKubera_108/SuryaDhana_AI
cd ui && npm ci && cd ..
# ui/dist/ is git-ignored: without a release ui-api serves a 'UI build not found' page (HTTP 503) and the app
# stays on its start screen. Build one (≈ 15 s to 2 min; needs node, not the services):
./start-local.sh build-ui
./start-local.sh build-ui --list      # 'current  <id>' must be listed
```
The watchdog never builds the UI by itself (publishing a release is deliberate); it Telegrams when ui-api is
up but `ui/dist/current` is missing (at most every 6 h). A bad release: `./start-local.sh build-ui --rollback`.

## 2. Reconstruct `.env`
`cp .env.example .env`, then fill the **[LOGIN-CRITICAL]** groups:

| Key | Where to get it |
|---|---|
| ICICI_API_KEY / ICICI_API_SECRET | api.icicidirect.com → your Breeze app |
| ICICI_CLIENT_ID / ICICI_PASSWORD / ICICI_MOBILE | your ICICI Direct login (mobile no. + PIN works) |
| ICICI_SESSION_TOKEN | leave blank — the 08:00 job / Telegram `/login` fills it |
| ICICI_TOTP_SECRET | optional; the authenticator setup key = fully unattended 08:00 login. **Preferred home is the macOS Keychain, not this file:** `security add-generic-password -U -s suryadhana -a ICICI_TOTP_SECRET -w` (prompts for the value; nothing in argv or shell history), then `chmod 600 .env`. The Keychain item is not in git or the project's 02:15 backups by design (only your login keychain's own Time Machine / iCloud Keychain cover): on a fresh Mac re-add it by hand (the key: icicidirect.com Settings → Login Authenticator → "manually enter the provided key"; steps in `reports/gold_program/OWNER_GUIDE.md` §5). A `.env` copy is a complete login: 0600, and the password-manager copy treated the same way |
| TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID | @BotFather bot + your chat id (bot answers only you) |
| HEALTHCHECK_PING_URL | **strongly recommended**: the off-machine dead-man ping, the only alert that still works when this Mac is off, frozen or waiting at the FileVault screen. A free healthchecks.io check, see [Off-machine dead-man ping](#off-machine-dead-man-ping-healthchecksio). Read by the watchdog every run (no restart) |
| HEALTHCHECK_WATCHDOG_URL | optional second heartbeat (Terminal v2 0.2): a second healthchecks.io check pinged on every watchdog run whatever the stack's state, see the end of [Off-machine dead-man ping](#off-machine-dead-man-ping-healthchecksio) |
| REDIS_PASSWORD | optional (Terminal v2 0.7): prefer the Keychain item `suryadhana-redis`; letters and digits only. Read [Redis password](#redis-password-terminal-v2-07-o-t10) before setting it |
| OFFSITE_BACKUP_DIR | the off-machine target for `scripts/db_backup.py --offsite` (a mounted external disk or rclone mount); see [Version control and off-machine backup](#version-control-and-off-machine-backup) step 5 |
| TERMINAL_JOBS_ENABLED / IV_WATCHLIST / IV_SURFACE_ALL / BREEZE_BUDGET_CAP_DAY / BREEZE_BUDGET_CAP_MINUTE / BREEZE_BUDGET_QUOTAS | Terminal v2 (5 Nov 2026), all optional: `TERMINAL_JOBS_ENABLED=0` stops the controller's v2 jobs; `IV_WATCHLIST` = your F&O names for the IV store and the 15-min pilot (comma list; default indices only); `IV_SURFACE_ALL=1` stores the per-strike surface for all ≈ 224 underlyings (≈ 2–3 GB over 7 years, O-T4); the Breeze ledger defaults to 60/min · 4,000/day, clamped under the documented 100 · 5,000 (O-T6) |
| FRED_API_KEY / EIA_API_KEY | optional: EIA for the CMDT energy leg; FRED only for ALFRED vintages (the gold jobs use the keyless `fredgraph.csv`) |
| GOLD_IMPORT_DUTY_PCT / GOLD_IMPORT_DUTY_EFFECTIVE / CFTC_APP_TOKEN | gold (26 Oct 2026): duty 15 / 2026-05-13 (defaults; the owner confirms at CBIC, PLAN O-3); the CFTC Socrata token is optional (free; raises the rate limit) |

Everything else in `.env.example` has working defaults; set `PYTHON_BIN` to the jupyter_env
python path.

`.env` holds the broker and Telegram credentials: make it readable by you only, and check again after you save
credentials from the terminal's Broker tab (a save rewrites the file):
```bash
chmod 600 .env && ls -l .env            # -rw-------
```
Editing `.env` by hand: `.env` is read by python-dotenv (every service; it expands `${NAME}` and cuts a comment that
starts with ` #`) and by plain parsers that only strip one layer of quotes (the 08:00 login script among them). The
Broker tab writes credentials in the one form all of them read back exactly, and refuses a value no form can hold;
by hand, follow the same rules (SECREL-03):
- write the value unquoted: `ICICI_PASSWORD=pa#ss` reads back as `pa#ss` (a `#` starts a comment only after a
  space, and a quote inside the value is fine);
- single-quote it only when it has a space before a `#`, or a leading or trailing space: `ICICI_PASSWORD='pa #ss'`;
  when such a value also holds a single quote, double-quote it instead: `ICICI_PASSWORD="it's #1"`;
- a value containing `${` cannot be kept in `.env`: python-dotenv expands it in every quoting style, single quotes
  included (`ICICI_PASSWORD='pa#ss${x}'` reads back as `pa#ss`, so the next login sends a wrong password). Change
  such a password. The same holds for a value that starts or ends with a quote, or needs quotes and holds both kinds;
- `ICICI_API_KEY`, `ICICI_API_SECRET` and `ICICI_SESSION_TOKEN` stay unquoted (two scripts read them verbatim); real
  ones never need quotes.

Then check that every reader sees the login and alert keys the same way (prints key names only, never a value):
```bash
/Users/sudheer/Desktop/jupyter_env/bin/python - << 'EOF'
from dotenv import dotenv_values
SHARED = ("ICICI_", "TELEGRAM_", "HEALTHCHECK_")                     # also read by the plain parsers / the watchdog
RAW = {"ICICI_API_KEY", "ICICI_API_SECRET", "ICICI_SESSION_TOKEN"}   # read verbatim, quotes and all
plain = {}
for line in open(".env"):
    key, eq, val = (part.strip() for part in line.partition("="))
    if eq and key.startswith(SHARED):
        plain[key] = val if key in RAW else val.strip('"').strip("'")
bad = sorted(k for k, v in dotenv_values(".env").items() if k.startswith(SHARED) and plain.get(k) != v)
print("OK: every reader sees the same values" if not bad else "FIX (read differently): " + " ".join(bad))
EOF
```

## 3. Restore the database (4.4 GB, git-ignored)
```bash
mkdir -p data
LATEST=$(ls -t data/backups/duckdb/market-*.duckdb* 2>/dev/null | head -1)   # or copy from offsite
# plain copy:
cp "$LATEST" data/market.duckdb
# zstd backup:
#   /Users/sudheer/Desktop/jupyter_env/bin/python -c "import zstandard,sys; zstandard.ZstdDecompressor().copy_stream(open(sys.argv[1],'rb'), open('data/market.duckdb','wb'))" "$LATEST"

# Verify (row count should be ~8.2M and match the backup's .meta.json "rows"):
/Users/sudheer/Desktop/jupyter_env/bin/python -c "import duckdb; print(duckdb.connect('data/market.duckdb', read_only=True).execute('SELECT COUNT(*) FROM nse_bhavcopy').fetchone())"
```
No backup at all? The panel is rebuildable from NSE archives (days, not hours): start services,
then `POST :8001/jobs/ingest-bhavcopy` and the nightly pipelines refill — see
docs/NSE_DATA_DICTIONARY.md.

**Gold tables (26 Oct 2026).** The 21 `gold_*` tables and the `gold_cot_metrics` view (PLAN §c.1's 20 — `gold_cot_raw` and
`gold_cot` are two — plus `gold_ingest_state`: CFTC COT, CME daily OI / EFRP / calendar / specs, settlement
curves, margins, daily and 1-minute bars, Shanghai, ETF holdings, Fed path, events, the pre-open log, briefs, health
snapshots, the series catalog) live in the same `market.duckdb`, so restoring the file restores them and `scripts/db_backup.py`
copies them with the rest; the catalog re-seeds itself from code at every data-service start. With no backup, or to fill a
gap, the data-service jobs rebuild them from the publishers in this order (PLAN §c.4; all free, paced, one-off; each is a
`POST` to data-service, never a restart; run outside 07:45–09:20 and 18:30–21:15 and not next to the 02:15 backup;
every source is listed with its verdict in docs/GOLD_DATA_DICTIONARY.md):

| Order | Table(s) | Job id · groups (`GOLD_JOBS` in `scripts/master_controller.py`) | Source · size · time |
|---|---|---|---|
| 1 | `gold_cot_raw`, `gold_cot` | `gold_cot_weekly` · `cot` | CFTC Socrata, four datasets 1986→ (~35 MB JSON) · ≈ 20 s |
| 2 | `gold_daily_bars`, `gold_curve` (COMEX, LAST TRADE) | `gold_overnight` · `yahoo_daily` | Yahoo, one call per symbol 6 s apart, app UA, `period1/period2` (never `range=max`) · ≈ 3 min; **no other Yahoo caller while it runs** |
| 3 | `gold_series` (Treasury, FRED daily / weekly / monthly) | `gold_overnight` · `treasury`, `fred_daily`; `gold_weekly` · `fred_weekly`; `gold_morning` · `monthly_due` | plain UA · ≈ 2 min |
| 4 | `gold_cme_daily_voi`, `gold_cme_efrp` | `gold_cme_daily` · `cme_voi`; `gold_fred_daily` · `cme_efrp` — with `backfill_from` 2014-01-02 / 2017-01-20 | CME **FTP** (`ftp.cmegroup.com`), 1 file / 2 s, resumable by date · ≈ 2 h each, ~330 MB in passing (owner approval O-6) |
| 5 | `gold_cme_calendar`, `gold_cme_prf` | `gold_cme_calendar` · `cme_calendar`; `gold_cme_daily` · `cme_prf` | CME FTP · seconds |
| 6 | `gold_etf_holdings`; WGC, IMF, LBMA, SGE, AMFI, Swiss, GPR, World Bank, Atlanta Fed rows of `gold_series`; `gold_asia_daily`; `gold_fed_path` | `gold_morning` · `etf`, `fed_path`, `gpr_daily`, `monthly_due`; `gold_weekly` · `wgc_etf`, `rbi_wss`, `lbma_turnover`, `wgc_premiums`; `gold_asia_close` · `sge_daily`, `sge_benchmark`, `shfe`; `gold_fred_daily` · `lbma_wgc` | WGC rows gated on the owner's terms decision O-1 · minutes |
| 7 | `gold_curve` (MCX, PROXY), `gold_margins`, IBJA and RBI reference-rate rows | `gold_mcx_master` · `mcx_master`, `margins`; `gold_india_midday` · `ibja_am`, `inr_ref`; `gold_india_pm` · `ibja_pm`, `derive_india` | **no history exists anywhere: these start the day the job runs** (the page says "since <date>") |
| 8 | `gold_preopen_log` | the migration of `data/gold_preopen/log.json` (dual-written for one release) | 4 rows |
| 9 | derived series (landed, duty-paid, basis, premiums, KGX, GSR, GVZ σ, ATR) | `gold_india_pm` · `derive_india`; `gold_fred_daily` · `derive_global` | computed from 1–7 |

One job by hand — the body is B1's contract (`job` in the query and the body, `groups`, optional `backfill_from`); the
controller does the same on its next start for the key jobs (`gold_overnight`, `gold_mcx_master`, `gold_cot_weekly`) with
`backfill_from` = the last heartbeat's date (`gold_downtime_catchup` on SYS, never inside a freeze window):
```bash
curl -s -X POST "localhost:8001/jobs/ingest-gold?job=gold_cot_weekly" -H 'Content-Type: application/json' \
     -d '{"job":"gold_cot_weekly","groups":["cot"],"backfill_from":"2006-06-13"}'
```
Verify: `/status` on Telegram and the WHSE page list the gold tables' latest dates (COT may be 9 days old, the curve /
bars / COMEX OI 4, ETF 5 — `GOLD_MAX_AGE_DAYS`); `GET :8001/db/gold/catalog` (PLAN §c.5) lists the series the page may
render. A 404 on `/jobs/ingest-gold` means data-service is running without the gold package: deploy it outside the freeze
windows; the controller pauses the gold jobs for an hour and retries by itself.

Settings store (watchlist, pins, saved tickets, page settings): restore it now too, see §8 "Restore".

## 4. Start + verify
```bash
./start-local.sh start            # the 3 core services: data-service, ui-api, master-controller
./start-local.sh status           # every service up, ui-release ok, prefs, desktop-app, dead-man-ping, reboot-recovery (read-only)
curl -s localhost:8001/health && curl -s localhost:8010/health && curl -s localhost:8008/health
curl -s localhost:8010/ready      # "ui":"ok" and the ui_build_id of the release from §1
/Users/sudheer/Desktop/jupyter_env/bin/python scripts/ui_audit.py          # :8010 by default; expect 16/16 ok (the GOLD page is in the default set since 26 Oct 2026)
/Users/sudheer/Desktop/jupyter_env/bin/python scripts/ui_audit.py --tabs all --browser both   # all 43 pages
```
Then on Telegram: `/status` (services + data dates), `/login` when ICICI asks, `/shadow`.

The `ui-release` row shows the release in `ui/dist/current` next to the one ui-api says it serves
(`GET /version`): `ok <id> (ui/dist/current) · served by ui-api` is the normal state. `mismatch` (with a `→`
line) means ui-api serves something else: run status again (a `build-ui` swap may have just happened); if it
stays, ui-api has `UI_DIST_DIR` set in its shell or `.env`: remove it and `./start-local.sh restart ui-api`
(outside the freeze windows).

The other rows of `status`:
- a service row saying **`no answer`**: the service listens on its port but `/health` gave no answer in 5 s, i.e.
  it is hung; the watchdog restarts it on its own (see "After an outage"). `down` = nothing listens.
- **`desktop-app`**: the installed copy (pid, version, Launch at Login) and who relaunches it after a crash (§5):
  `supervised by launchd (relaunched after a crash)` (the Launch at Login job's own process); `opened by hand: its
  crash guard relaunches it through launchd` (a copy reopened from the Dock or Finder); `opened by hand: not
  relaunched after a crash` (no crash guard watches it: an app build older than 25 Oct round 3, or the guard could
  not start; a `→` line gives the fix); `not relaunched after a crash (Launch at Login is off)`. A self-test or
  build copy under `desktop/` is listed as `other copies`, never as the app.
- **`dead-man-ping`**: `not set` until HEALTHCHECK_PING_URL is configured; then the watchdog's last ping (`ok`,
  `fail sent` = it told healthchecks.io the stack is unhealthy, `failing` = the ping itself failed, `stale` = the
  watchdog has not run for 10 min). Only the URL's host is shown.
- **`reboot-recovery`**: `check` while the Mac stays off after a power failure or installs macOS updates (and
  restarts) by itself; see [Unattended reboots](#unattended-reboots-power-cuts-macos-updates-filevault).

## 5. Re-arm the schedule, autostart and the desktop app
Jobs register automatically when master-controller starts (02:15 backup, 08:00 login, 09:09
pre-open, 18:30 EOD, 19:20 snapshot, 19:30 desk, 19:45 news, 19:50 shadow, 21:00 wrap), and so do the gold jobs
(`GOLD_JOBS`, 26 Oct 2026: 03:10 overnight, 1-minute bars every 5 min while COMEX trades, 06:40 morning, 07:35 MCX
master, 08:40 health snapshot, 08:45 pre-open snapshot, 09:05 brief, hourly US calendar, 13:45 / 18:10 India, 15:45
CME, 16:10 Asia, 21:30 FRED, Sat 02:30 COT, Mon 12:00 / Fri 18:00 / Sat 10:30 weekly, Sun 04:00 CME calendar). They
fetch only; a 404 from data-service (gold package not deployed) pauses them for an hour, and SYS shows each one's last run.

Autostart after a reboot is the watchdog LaunchAgent (plus `caffeinate`), not a second login script:
```bash
scripts/install_launch_agents.sh install      # com.suryadhana.watchdog (every 2 min) + com.suryadhana.awake
scripts/install_launch_agents.sh status
```
Do **not** run the old `scripts/install_autostart.sh`: it installs a redundant `com.suryadhana.stack` agent
that races the watchdog at login. If an old Mac still has it: `launchctl bootout gui/$(id -u)/com.suryadhana.stack;
rm ~/Library/LaunchAgents/com.suryadhana.stack.plist`.

The desktop app (optional; the browser at http://127.0.0.1:8010 is the same terminal):
```bash
scripts/build_desktop.sh --install            # build, ad-hoc sign, install /Applications/SuryaDhana.app
scripts/build_desktop.sh --install --test     # … and run the installed copy's --self-test
```
- Always launch the **installed** copy (/Applications, or ~/Applications when /Applications is not writable),
  never the build output under desktop/: Launch at Login records the path it was enabled from.
- First launch enables **Launch at Login** once (`~/Library/LaunchAgents/SuryaDhana.plist`, label `SuryaDhana`);
  turn it off/on from the menu *SuryaDhana ▸ Launch at Login* or the menu-bar icon. `./start-local.sh status`
  shows it on the desktop-app row. The app only opens the terminal and talks to the watchdog; the stack keeps
  running whether or not the app is open.
- **Crash relaunch.** launchd relaunches the copy it started (the Launch at Login job; label `SuryaDhana`). A copy
  you reopen from the Dock or Finder after ⌘Q runs outside that job, so it starts a small crash guard
  (`suryadhana-crash-guard` in `ps`): when the app ends without a clean quit, the guard asks launchd to start it
  again (within about 15–20 s), supervised by launchd from then on. The menu-bar item says which applies
  (*Relaunch after a crash: on (login item)* / *on (crash guard for this copy)* / *off (…)*); with Launch at Login
  off nothing relaunches the app. Four crashes within 10 min stop launchd's relaunch (the crash-loop breaker, in the
  app log); opening the app by hand always works.
- **No crash guard?** An app build older than 25 Oct round 3 has none, and a guard that could not start leaves the
  menu-bar item at *off (…)*: `./start-local.sh status` then says `opened by hand: not relaunched after a crash`.
  Hand the copy to launchd: quit it (⌘Q), then
  ```bash
  launchctl kickstart gui/$(id -u)/SuryaDhana   # "Could not find service": launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/SuryaDhana.plist
  ```
  (or log out and in). The app then runs as the login job's own process (`supervised by launchd`).
- "SuryaDhana is damaged / unidentified developer" (ad-hoc signature): right-click ▸ Open once, or
  `xattr -dr com.apple.quarantine /Applications/SuryaDhana.app`.
- App log: `~/Library/Logs/ai.suryadhana.terminal/suryadhana.log` (Help ▸ Open App Logs Folder); stack actions
  the app takes go to `.logs/desktop-stack.log`. Troubleshooting table: desktop/README.md.

## 6. What is NOT in git or backups (accept or re-create)
- `.env` itself (step 2) and the macOS Keychain item `suryadhana` / `ICICI_TOTP_SECRET` (the TOTP secret's preferred
  home once auto-login is enabled: not in git or the project's backups by design; re-add it with the one-liner in §2).
- `data/` caches beyond the DuckDB and the settings store (reference CSVs regenerate via jobs; `data/reference/`
  ships in git).
- `ui/dist/` (the terminal UI releases): rebuilt by `./start-local.sh build-ui` (§1). `ui/.next-prod` exists
  only for the optional `UI_MODE=prod` frontend and is rebuilt by `start frontend`.
- The app itself: rebuilt by `scripts/build_desktop.sh --install` (§5). Its window state and downloads folder
  are per Mac; its settings live in the server store (§8), not in the app.
- Backup rotation: 7 daily + 4 weekly Sundays in `data/backups/duckdb/`, for both `market-*.duckdb[.zst]`
  and `ui_prefs-*.sqlite` (each with a `.meta.json`). They sit on the SAME internal disk as the live data: a
  disk failure takes both. Copy them, the repo and `.env` off this Mac:
  [Version control and off-machine backup](#version-control-and-off-machine-backup).
- One backup at a time: `scripts/db_backup.py` holds a lock on `data/backups/duckdb/.db_backup.lock` (released by
  the kernel when the run ends or dies; leave the file alone). A second run while one is going (the 02:15 job,
  the start-up catch-up below, or a manual run) prints "skipped: another backup is running" and exits 75 having
  written nothing; the controller logs that as a skip, not a failure.

## 7. Phone / iPad access: Tailscale Serve (never the LAN)
ui-api, like every service, listens on **127.0.0.1 only**, and the terminal has no login: anything that can
reach it can place paper orders, change broker credentials and re-enable the Desk. The old `UI_API_HOST=0.0.0.0`
LAN opt-in was removed (25 Oct 2026); `start-local.sh` ignores the variable and says so. To use the terminal
from a phone or iPad, put Tailscale Serve in front of loopback: it gives an HTTPS URL that only devices signed
in to your own tailnet can open.
```bash
brew install --cask tailscale        # or the Mac App Store app; sign in, and sign in on the phone/iPad too
# Tailscale admin console → DNS: enable MagicDNS and HTTPS Certificates (one time)
tailscale serve --bg 8010            # https://<mac-name>.<tailnet>.ts.net → http://127.0.0.1:8010
tailscale serve status               # shows the URL
#   (CLI inside the app: /Applications/Tailscale.app/Contents/MacOS/Tailscale)
```
ui-api's request guard (`shared/http_guard.py`) answers only to loopback `Host` names by default, and Serve
keeps the browser's `Host` (the ts.net name), so allow exactly that name in `.env`, then restart ui-api:
```bash
GUARD_ALLOWED_HOSTS=<mac-name>.<tailnet>.ts.net        # comma list; without it every tailnet request gets 400
./start-local.sh restart ui-api                       # the guard reads its settings at start (freeze windows!)
```
`GUARD_ALLOWED_ORIGINS` is not needed: the page's `Origin` (`https://<mac-name>.<tailnet>.ts.net`) equals that
allowed `Host`, which the guard already admits.

**Tailnet devices are read-only by default.** Serve puts the device's tailnet address in `X-Forwarded-For`, so
the guard counts every request through it as a REMOTE client (whatever uvicorn's proxy-header setting). Remote
clients may read: every page, quotes, the live monitor WebSocket. Every write gets **403 "clients on other
machines are read-only"**: settings edits are not saved to the server store (they stay on that device only),
and compute requests (OSTR analyze, ALFA scan, MCXG ticket, backtests, ML training), paper orders and Desk
actions are refused. To let tailnet devices write, add one more line and restart ui-api again:
```bash
GUARD_ALLOW_REMOTE_WRITES=1                           # remote clients may use POST/PUT/DELETE
```
Every service binds 127.0.0.1, so the only remote clients there can be are the ones arriving through Serve on
this Mac, i.e. devices signed in to your tailnet (plus anyone you share this Mac's node with). With the flag on,
such a device can do everything the terminal can: place paper orders, change the ICICI credentials, re-enable
the Desk. Turn it on only if every device on the tailnet is yours. (Only ui-api sits behind Serve, so the other
services never see a remote client either way.)
- Use `tailscale serve`, **never** `tailscale funnel` (Funnel publishes the terminal to the whole internet).
- Turn it off: `tailscale serve --https=443 off` (or `tailscale serve reset`), remove the GUARD_* lines and
  restart ui-api.
- The phone's terminal is a separate browser origin: it loads its settings from the server store (§8) on
  first load, like the app. In the default read-only mode its own edits stay on the phone.

## 8. Settings store: migration, backup, restore
ui-api keeps the terminal's user settings (watchlist, pins, GO recents, saved tickets, page settings) in
`data/ui_prefs.sqlite` (`PREFS_DB` overrides; SQLite in WAL mode, so the live file comes with `-wal`/`-shm`).
Every origin (the app, a browser on :8010, a phone through §7) loads them before first render and writes
through; each also keeps a local copy.

**In-app import (from the first ui-api restart after 6 Nov 2026; page review M35).** While the server says nothing was
imported, the terminal offers it once in a toast; later use GO `IMPORT` or MORE ▾ → ⇪ IMPORT SETTINGS. START opens a
one-time page on http://localhost:3000, served by ui-api itself for at most 10 minutes (no Next dev server, single use,
a token in the link). Copy the link into the browser you used for the old terminal and click IMPORT there: it fills only
settings you have not set in the app. If something already listens on :3000, the dialog says so and the steps below apply.

**One-time migration from the old browser terminal (:3000).** Settings from before the switchover exist only
in the localStorage of the browser that used http://localhost:3000. They reach the server the first time that
browser loads the :3000 build that carries the sync code. Do it **before** editing the watchlist or pins in the
app: an edit in the app is a deliberate write that wins over the old copy (which then survives only under that
browser's `suryadhana.prefs.backup` key).
```bash
./start-local.sh status          # prefs row: 'imported' = done; 'not imported' = continue
./start-local.sh start frontend  # if the frontend row says off
# open exactly http://localhost:3000 in the browser profile you always used; wait ~5 s
./start-local.sh status          # prefs: imported … · imported <n> keys from http://localhost:3000 on <date> IST
./start-local.sh stop frontend
```
Stop :3000 **right after** the import and do not browse other sites in that browser while it runs. It is a
second door to ui-api that any web page in your browser can reach: its stream routes (ML training, backtests, the
scheduler log) re-send requests without the browser's `Origin`, so ui-api's cross-site guard cannot refuse them
(desktop review SECREL-01). The `frontend` row of `status` shows whether it is still up.
What the `prefs` row says (read-only; it never prints a value):
- **imported**: ui-api recorded the first import from the browser terminal (the `migration` record of
  `GET /api/prefs`, kept in the store and never cleared by later writes), shown with its date, origin and key
  count. It stays `imported` after you edit the watchlist or pins in the app. With an older ui-api that has no
  such record, `imported` means a record written from :3000 still exists.
- **not imported**: no import yet. The `→` line names what an import can still fill (the watchlist and/or the
  pins, while they hold nothing or only a default); a key you already set in the app is kept by an import.
- **app-owned** (older ui-api only): the watchlist and the pins were both set in the app, so an import from
  :3000 can no longer replace them, and whether one ever happened is unknown.
- **unreadable**: the store could not be read (the reason is shown), or the status helper timed out (10 s,
  `STATUS_PY_TIMEOUT`): typically the jupyter_env Python waiting on a macOS privacy prompt (§ After an outage).
Settings that lived only on a phone/iPad's old LAN :3000 origin cannot be migrated this way (the frontend binds
127.0.0.1 now); re-create them.

**Backup.** The 02:15 job (`scripts/db_backup.py`) also copies the store with SQLite's online backup API
(consistent while ui-api writes; a plain `cp` would miss what is still in the `-wal`), checks it with
`PRAGMA integrity_check`, and writes `data/backups/duckdb/ui_prefs-YYYYMMDD.sqlite` + `.meta.json`
(keys, sha256) into the same 7-daily + 4-Sunday rotation. A failed settings backup fails the job (Telegram)
even when the DuckDB backup succeeded. On demand, e.g. before a migration or an experiment:
```bash
/Users/sudheer/Desktop/jupyter_env/bin/python scripts/db_backup.py --prefs-only
```

**Restore** (stop ui-api first: the store must not be open while its files are swapped):
```bash
./start-local.sh stop ui-api
mkdir -p data/prefs-before-restore && mv data/ui_prefs.sqlite* data/prefs-before-restore/ 2>/dev/null
LATEST=$(ls -t data/backups/duckdb/ui_prefs-*.sqlite | head -1)
cp "$LATEST" data/ui_prefs.sqlite          # a single file: the backup has no -wal/-shm to copy
/Users/sudheer/Desktop/jupyter_env/bin/python -c "import sqlite3; print(sqlite3.connect('data/ui_prefs.sqlite').execute('PRAGMA integrity_check').fetchone())"
./start-local.sh start ui-api              # ('ok',) above; then status → prefs row
```
A device that synced after the backup was taken re-uploads its newer values on its next load (the server copy
only moves forward), so a restore never rolls a device back. No backup at all: start ui-api with no store; it
creates an empty one and every device re-uploads what it has.

## After an outage, a reboot or a crash (resilience review, 19 Oct 2026)

**Restart order when data-service and ui-api both restart (4 Nov 2026 incident).** ui-api opens a persistent *read-only*
connection to `data/market.duckdb` the first time a route touches `db.get_conn()`. If data-service is down at that moment
the read lock succeeds, and when data-service comes back it cannot take the write lock and logs `DuckDB opened READ-ONLY …
all ingestion will fail` (`/ready` 503; every `/jobs/*` answers `503 DuckDB is read-only`). Always: `./start-local.sh stop ui-api`
→ `./start-local.sh restart data-service` (check `/ready` is 200) → `./start-local.sh start ui-api`; or restart data-service
alone and leave ui-api up. `lsof data/market.duckdb` must show data-service with `u` (write) and no ui-api line.

**What now happens on its own** (once `scripts/install_launch_agents.sh install` has run):
- **Login after a reboot** → the `com.suryadhana.watchdog` LaunchAgent starts the core stack (data-service,
  ui-api, master-controller; ui-api serves the terminal UI) and sends a Telegram "the stack was down" note.
  The app (Launch at Login) shows its start screen until ui-api answers, about a minute after login.
- **A crashed service** → started again about 1–3 min after the crash (the next 2-minute watchdog run, checked
  twice 30 s apart, then the start itself), Telegram note.
  Services you stopped yourself (`./start-local.sh stop …`) are left alone until you start them again.
  The crashed instance's output survives the restart: a start appends to `.logs/<service>.log` after a
  `=== … start-local.sh: starting <service>` line, so the traceback is just above the last such line.
- **A hung service** (its uvicorn still listens on the port but `/health` on 127.0.0.1 gets no answer, as ui-api
  did on 25 Oct 14:40–14:48) → restarted with `./start-local.sh restart <service>` once it has been hung on two
  watchdog runs in a row against the same process and once more just before the restart: the restart begins
  about 3–5 min after the hang starts and the service is back about 3.5–5.5 min after it (data-service or
  master-controller busy above 50 % CPU, i.e. probably a long job rather than a hang: about 16 min, with a "busy"
  Telegram first). Telegram: "<service> was hung (listening, /health timed out): restarted"; a restart that fails
  gets its own "🔴 … the restart FAILED" message even right after a "restarted" one. Before the restart the
  watchdog saves `.logs/hangs/<YYYYmmdd-HHMMSS>-<service>/`: `summary.txt` (what it saw, `ps` of the listener,
  the number of open connections), `py-stacks-<pid>.txt` (every Python thread's stack, from faulthandler on
  SIGUSR1; only for a service whose log announces that handler since its last start: ui-api, and data-service /
  master-controller once restarted on the 25 Oct round-3 code; never to one that has not, nor to the
  `UI_API_RELOAD=1` reload supervisor, since SIGUSR1 would kill it), `sample-<pid>.txt` (a 3 s `/usr/bin/sample` of every
  thread), `lsof-<pid>.txt` (its files and sockets) and `log-tail.txt` (the last 200 log lines). The newest 10
  are kept, plus each service's first capture of the last 24 h. Read `summary.txt` first, then `py-stacks`
  (the thread inside `run_forever` is the event loop: the frame below it is where it is stuck), then the sample's
  main-thread call graph, then the log tail (in `.logs/<service>.log` the hung instance's lines are just above
  the restart's `=== … starting` banner).
  It alerts instead of restarting (and restarts later on its own) when: data-service or master-controller is
  inside a freeze window (07:45–09:20, 18:30–21:15 IST; ui-api may restart any time); master-controller only,
  an ICICI login (`daily_session_refresh.py`) is running, at most 10 min (the manual `icici_session_helper.py`
  holds nothing back); the service was already restarted 3 times for a hang in the last hour (it then only
  alerts until the hour is up or you restart it yourself, which clears the count); or any listener on the port is
  a program that is not the service's own uvicorn (nothing is ever stopped: free the port, then
  `./start-local.sh start <service>`). It also skips the restart if, during the capture, you stopped the service
  (Stop Stack), restarted it yourself or a `start-local.sh` run started. `WATCHDOG_DRY_RUN=1
  scripts/stack_watchdog.sh` logs the hang decisions without capturing or restarting (a down service is still
  started).
- **A watchdog lock left by a power cut or a killed run** no longer silences the first runs after boot: a lock
  whose run is gone (or that predates this boot) is taken over at once and logged. Its owner file
  (`.pids/watchdog/lock/owner`: `<pid> <boot time in epoch seconds>`, the first field of `sysctl -n kern.boottime`)
  is also what the desktop app reads to show "the watchdog is starting the stack".
- **Logs** → `.logs/*.log` are rotated by size (20 MB, keeping `.1`–`.3`) at every service start and hourly by
  the watchdog (`./start-local.sh rotate-logs`). A service started before 25 Oct 2026 opened its log without
  append mode; its log is not rotated (the watchdog log says so) until that service is restarted once.
- **No UI release** (`ui/dist/current` missing while ui-api is up) → logged hourly and Telegrammed at most
  every 6 h; fix with `./start-local.sh build-ui` or `./start-local.sh build-ui --rollback`.
- **No idle sleep** → `com.suryadhana.awake` holds `caffeinate -s -i` while you are logged in.
- **Controller downtime** → on its next start the controller reads `data/.controller_heartbeat.json`,
  counts every scheduled run it missed, catches up the NSE files (or re-runs the whole EOD pipeline when
  the market is shut) and sends ONE Telegram report. Outside the evening window the catch-up re-runs the Desk and
  the S1 shadow when their 19:30 / 19:50 runs were missed (both replay every missed session from stored closes, rules
  unchanged). **Inside the 18:20–21:15 evening window** (6 Nov 2026, review M30: a 19:34–19:55 restart on 5 Nov left the
  19:45 news track record and the 19:50 S1 shadow stale for a day) the catch-up replays, once each and in this order,
  every evening job whose slot passed during the downtime: the 18:30 EOD pipeline, the 19:15 index valuation, the
  19:20 evening snapshot, the 19:30 Desk, the 19:50 S1 shadow, the 19:45 news track record (the shadow goes first: it
  never reads the track record, whose run may take 30 min) and Friday's 20:10 journal (`EVENING_REPLAY` in
  `scripts/master_controller.py`); a slot still ahead is left to its own run. These are jobs, not restarts, so the
  freeze window allows them. The report lists what was re-run with the status **that** run recorded (`error`,
  `skipped`, `no new data` or `done`; "no run recorded" when the job returned without running), what waits for today's
  own slot, and every missed job that is **NOT** re-run with its next scheduled run. "The Desk / the S1 shadow replayed
  every missed session" appears only for a run of that catch-up that recorded `done`: never for a failed shadow (a
  non-zero exit, a timeout), a Desk with `DESK_ENABLED=0` (`skipped`) or a run that moved no dataset (`no new data`).
  SYS's `/api/scheduler/status` carries `catchup_at` for a job that the downtime missed, only while a catch-up run of
  it is actually scheduled; it is cleared when that catch-up ends, whether the job ran, failed or was skipped.
  The key gold jobs (`gold_overnight`, `gold_mcx_master`, `gold_cot_weekly`, …) re-run with `backfill_from` = the last
  heartbeat's date (`gold_downtime_catchup`, 26 Oct 2026), never inside a freeze window; `gold_mcx_close` (Breeze bars)
  only while an ICICI session is live (sessions expire at midnight IST, so the old 00:15 retry was removed on 6 Nov);
  the other gold jobs simply run at their next slot (every series is point-in-time, so a late fetch is a gap, not a lie).
  To refill what a long outage left missing (ALRT notes, wraps, FII/DII rows), see
  [Backfill after a long outage](#backfill-after-a-long-outage-m31).
- **A missed 02:15 backup** (Mac off or asleep at 02:15, controller down, even a 2-minute restart across 02:15)
  → at start-up, when today's `market-YYYYMMDD.meta.json` is missing and 02:15 has passed, the controller runs the
  backup once (`db_backup_catchup` on SYS): about 3 min after the start, and after the data catch-up above when
  there is one (it waits while that writes the DuckDB). Never inside the freeze windows, and never less than 20 min
  (the backup's timeout) before one opens: a start at 07:25–09:20 runs at 09:21, one at 18:10–21:15 at 21:16. No
  catch-up when the slot would fall after midnight (the next 02:15 run is close then). The downtime report says
  "today's 02:15 backup is missing: one run at HH:MM"; a failed run still sends "DuckDB backup FAILED".
- **SYS job history** → each job's last run, status and duration are saved in `data/.scheduler_history.json`
  (rewritten atomically after every job; safe to delete, it refills as jobs run). After a restart SYS shows them
  until each job runs again (`/api/scheduler/status` marks such rows `last_run_source: "history"`). Jobs that catch
  their own failure (the backup, the 19:45 news track record, and since 6 Nov the 19:50 S1 shadow, which also sends a
  Telegram WARNING "S1 shadow job failed" for an exception, not only for a non-zero exit) record `error`, not `done`.
  Since 6 Nov 2026 (review M33 / m111) a run's status is one of: `error`; `skipped` (the dormant legacy engine with
  AUTOPILOT off, which used to say `done` in 0 ms); `no new data` (the job ran, but none of the datasets the catalog
  gives it moved: the stored as-of, the ingest_log date / revision / sha256 / Last-Modified are compared before and
  after the run on data-service `/db/data-health`; not judged for the every-few-minutes jobs, nor without a reading;
  `JOB_DATASET_CHECK=0` turns it off); or `done`. `/api/scheduler/status` also gives each job `schedule_ist` (its
  trigger in words), `running_since` (a run in flight) and `catchup_at`. The first polls of a data-service job now
  come after 1, 1, 2, 3, 5 and 8 s (then every 15 s), so a short job no longer reads ≈ 15,000 ms.
- **News-scanner track record (19:45)** → a failed run sends a Telegram WARNING "News track record failed" with
  the error line and shows `error` on SYS; the BRF/NEWS track record keeps its last good run. From 15 to 23 Oct
  2026 it failed silently every evening (the script took the evening snapshot's DuckDB connection for the price
  panel); fixed 25 Oct. To refresh it by hand (reads the snapshot or a private copy, never writes the DuckDB):
  `PYTHONPATH=. /Users/sudheer/Desktop/jupyter_env/bin/python scripts/news_scan_performance.py`.

**What still needs a human**
- **The dead-man ping (one-time, do it first)**: without HEALTHCHECK_PING_URL nobody is told when this Mac is
  off or frozen. On 24–25 Oct it stopped uncleanly at 16:35 and stayed down 18 hours (the EOD pipeline, the Desk,
  the shadow and the 02:15 backup all missed) with no alert. Steps:
  [Off-machine dead-man ping](#off-machine-dead-man-ping-healthchecksio).
- **Unattended reboots (one-time decisions)**: the Mac stays off after a power failure (`autorestart 0`), macOS
  installs updates and restarts by itself, and with FileVault on nothing runs after any reboot until someone logs
  in at the Mac (every SuryaDhana job is a per-user LaunchAgent). Steps:
  [Unattended reboots](#unattended-reboots-power-cuts-macos-updates-filevault).
- **Version control and an off-machine copy (one-time, then routine)**: the system exists only as an
  uncommitted working tree on one disk (no commit since 14 Jun, no remote, no Time Machine). Steps:
  [Version control and off-machine backup](#version-control-and-off-machine-backup).
- **macOS privacy (one-time)**: the stack's Python lives in `~/Desktop`; background (launchd) processes
  must be allowed Desktop-folder access or every watchdog restart blocks. Grant it once: System Settings →
  Privacy & Security → Files and Folders (or click **Allow** on the prompt). The watchdog detects the block
  in 15 s and Telegrams these instructions instead of hanging.
- **ICICI**: send `/login` on Telegram (OTP to your phone) if live broker data is needed.
- **Telegram `/status`** shows each service (`HUNG` when it listens but `/health` times out), the terminal UI
  release (or `MISSING` with the build-ui fix), the desktop app (running, and whether launchd supervises it), the
  dead-man ping, and an "Unattended reboots" warning while the reboot settings above are not done.

### Backfill after a long outage (M31)

The controller's log records it down 31 Oct 11:29 → 4 Nov 21:29 IST and 28 Oct 12:46 → 30 Oct 08:11 (its "Down from …
to … IST." downtime reports; also 24 Oct 16:36 → 25 Oct 10:59, a weekend, and 5 Nov 19:34 → 19:55). The review found no
ALRT notes on 29 Oct or 2–4 Nov (and none for the 28 Oct close), no wraps for 16 / 21 / 28 / 29 Oct and 2 / 3 Nov, no
FII/DII rows for 28 Oct and 2 / 3 Nov. One PM-run command refills what stored data allows and says what it cannot; it is
never scheduled. A **dry run is the default** (it prints the plan and writes nothing); `--execute` refuses to run
inside a freeze window (exit 3). The default range starts 28 Oct, the review's evidence window.
```bash
P=/Users/sudheer/Desktop/jupyter_env/bin/python
$P scripts/master_controller.py backfill-outage --since 2026-10-28 --until 2026-11-04            # the plan, nothing written
$P scripts/daily_wrap.py --backfill-missing --since 2026-10-12 --until 2026-11-04 --dry-run --base http://127.0.0.1:8010   # which wraps it would write
$P scripts/master_controller.py backfill-outage --since 2026-10-28 --until 2026-11-04 --execute  # after 21:15 or on a weekend
$P scripts/master_controller.py backfill-outage --steps wraps --since 2026-10-12 --until 2026-11-04 --execute   # the 16 / 21 Oct wraps
```
- **wraps**: D-DATA's generator, `scripts/daily_wrap.py --backfill-missing --since … --until …` (stored NSE sessions
  only; a wrap whose required sections are not stored is skipped, never half-written; a complete wrap is never touched).
- **fii_dii**: D-DATA's job, data-service `POST /jobs/fii-dii-backfill {"since": …}`. NSE's API serves only the latest
  day, so a missed session stays missing unless you saved NSE's CSV that day: pass it with `--fii-dii-csv <file>`
  (validated: every date an NSE session, one FII and one DII row, buy − sell = net). The result lists what stays missing.
- **notes**: the ALRT inbox (`data/notifications.jsonl`), merged in time order: for each missed **closing** note one
  line built from the stored NSE index closes (`index_ohlc_daily`: NIFTY 50 and NIFTY BANK close and day change),
  titled "(backfilled)", dated and saying "no closing note is recorded for this session; backfilled from stored data on
  <date>"; for each missed **pre-market** note one "No pre-market note is recorded for this session" line (kind `gap`):
  GIFT NIFTY and the overnight cues were never stored point-in-time, so that note is not rebuilt. A line states only
  what the command checked (the inbox has no note of that kind for that session). It names a controller outage, with
  its dates, only when the controller's own log (`.logs/master-controller.log*`, its "Down from … to … IST." lines)
  records one over that slot; otherwise it gives no cause (the current log begins with the 25 Oct 10:59 start, so no
  earlier session gets one; on 6 Nov it named the 28 Oct close, 29 Oct and 2–4 Nov, and nothing else). Re-running adds
  nothing twice.
- Run only the steps you want with `--steps wraps,fii_dii,notes`. The wraps step needs ui-api up; the FII/DII step needs
  D-DATA's route mounted in data-service (a 404 says so and does nothing).

**Manual recovery recipe (no restarts needed, works inside freeze windows)**
```bash
./start-local.sh status                      # what is down
./start-local.sh start                       # core stack (add `legacy` for the dormant ML services)
for j in ingest-bhavcopy ingest-nse-positions ingest-nse-events; do
  curl -s -X POST localhost:8001/jobs/$j -H 'Content-Type: application/json' -d '{}'; done
curl -s localhost:8001/db/market-monitor > /dev/null   # rebuilds the MKT cache for the new session
curl -s -X POST "localhost:8001/jobs/ingest-gold?job=gold_cot_weekly" -H 'Content-Type: application/json' \
     -d '{"job":"gold_cot_weekly","groups":["cot"]}'   # gold: the COT (the controller re-runs the other key gold jobs itself; §3 has the full order)
tail -20 .logs/watchdog.log                  # what the watchdog did ('alert:' lines = what it Telegrammed)
ls -t .logs/hangs | head -3                  # diagnostics saved before a hung service was restarted
scripts/install_launch_agents.sh status      # agents loaded? caffeinate holding?
```
Remove the agents with `scripts/install_launch_agents.sh uninstall`.

**Editing the stack's shell scripts** (`start-local.sh`, `scripts/stack_watchdog.sh`, `scripts/build_ui.sh`):
the watchdog runs them every 2 minutes, and bash reads a running script incrementally, so an in-place rewrite
can make a running instance execute fragments of the new file. Always write a temp file next to the script and
rename it over the original (`cp new start-local.sh.tmp-$$ && chmod 755 start-local.sh.tmp-$$ && mv -f
start-local.sh.tmp-$$ start-local.sh`, or `os.replace` from Python), which leaves a running instance on the old
inode. Each script also ends with a single `…; exit` line, so a run never reads past it.

## Off-machine dead-man ping (healthchecks.io)

Every alert so far is sent FROM this Mac, so none of them can say that the Mac itself is off, frozen or waiting
at the FileVault screen. The watchdog (every 2 minutes while you are logged in) therefore pings a URL when the
stack is healthy and `<url>/fail` when it is not; a free outside service alerts you when the pings stop or say
`fail`. One-time, about 10 minutes:

1. Sign up at https://healthchecks.io (the free plan is enough; you need one check).
2. **Add Check**, name it `SuryaDhana Mac`, then edit its schedule (**Simple**): Period **5 minutes**, Grace Time
   **10 minutes**. With pings every 2 minutes, one or two skipped runs do not alert, and a dead Mac alerts at most
   about 15 minutes after its last ping.
3. **Integrations**: email to your sign-up address is on by default. Also add **Telegram** (Integrations →
   Telegram, then follow the link to healthchecks.io's own bot): it reaches your phone while this Mac is down.
4. Copy the check's ping URL (`https://hc-ping.com/<uuid>`) into `.env` as one line, with an editor or:
   ```bash
   [ -z "$(tail -c 1 .env)" ] || echo >> .env        # end the last line first, if it has no newline
   printf 'HEALTHCHECK_PING_URL=%s\n' 'https://hc-ping.com/<uuid>' >> .env
   ```
   No restart is needed: the watchdog reads `.env` on every run. Treat the URL like a password (anyone who has it
   can send fake "healthy" pings); `status`, Telegram `/status` and the watchdog log never print it.
5. Check it — one command, which pings every configured check once and never prints the URL:
   ```bash
   bash scripts/stack_watchdog.sh --ping-test     # stack OK (HTTP 200) · mac OK (HTTP 200)
   ./start-local.sh status                        # within 2 min: dead-man-ping  ok  hc-ping.com pinged … ago
   ```
   It names anything missing or mistyped ("not set", "NOT A URL", or the HTTP code the service answered).
   On healthchecks.io the check turns green with a last ping under 2 minutes. `failing` in `status` means the
   ping itself fails: no network, or a mistyped URL (healthchecks.io answers 404 for an unknown check).
6. Test the alert path once: on the Integrations page use **Test!** next to Telegram and email.
7. Recommended (8 Nov 2026 RCA): add a SECOND check, `Mac alive`, same schedule, and put its URL in `.env` as
   `HEALTHCHECK_WATCHDOG_URL`. The first check goes `fail` when the STACK is down; this one is pinged on every
   watchdog run whatever the stack is doing, so its only meaning is "this Mac is up and launchd still runs the
   watchdog" — the signal that was missing when the Mac lost power on 6 Nov and stayed off for 38 hours.

What it catches: no ping for 15 minutes (Mac off, frozen, asleep, at the FileVault or login screen after a reboot,
the watchdog not loaded, no network), and `fail` on every watchdog run while a core service you did not stop is
down or hung. Before a planned shutdown, pause the check on healthchecks.io (or expect the alert).

**Second heartbeat (optional, Terminal v2 0.2).** Add a second check (`SuryaDhana watchdog`, same Period 5 min /
Grace 10 min) and put its ping URL in `.env` as `HEALTHCHECK_WATCHDOG_URL=`. The watchdog pings it first thing on
every run, whatever the stack's state, so it goes quiet only when the Mac itself is off, asleep, at the FileVault
screen or launchd no longer runs the watchdog. Read the two together: the first says `fail` while the second keeps
beating → the stack is down on a live Mac; both silent → the Mac is gone. The last result is kept in
`.pids/watchdog/deadman_watchdog` (`<epoch> ok|error`, never the URL) and Telegram `/status` shows it beside the
dead-man line.

## Redis password (Terminal v2 0.7, O-T10)

Redis carries the live quotes from data-service to ui-api's `/ws/monitor` hub (`live.quotes`); without it the terminal
works and live streaming does not. It used to listen on `*:6379` with no password (R-ARCH §3). `start-local.sh` now
starts it bound to 127.0.0.1 and, when a password is configured (`REDIS_PASSWORD` in `.env`, else the Keychain item
`suryadhana-redis`), with `requirepass` passed on stdin (never argv), and exports
`REDIS_URL=redis://:<pw>@127.0.0.1:6379/0` to the services it starts. A Redis that is already listening is reused as it
is, so the change applies only after that Redis is shut down once. One-time, outside both freeze windows:

1. **Before you set a password**, check that a single-service start or restart also exports it:
   ```bash
   grep -c 'start_redis; start_one' start-local.sh      # must print 2
   ```
   With 1, `./start-local.sh restart <svc>` (the path the watchdog uses for hang restarts) starts the service with
   `.env`'s password-less `REDIS_URL`: Redis refuses it and live quotes stop until a full restart. A fix was requested
   on 5 Nov 2026; until it is in, leave the password unset (the 127.0.0.1 bind alone already closes the LAN exposure).
2. Store a URL-safe password (letters and digits: it is embedded unencoded in `REDIS_URL`) without showing it:
   ```bash
   openssl rand -hex 24 | tr -d '\n' | pbcopy                          # to the clipboard, never the screen
   security add-generic-password -U -a "$USER" -s suryadhana-redis -w   # paste at the prompt; then clear the clipboard
   ```
   (`REDIS_PASSWORD=<pw>` in `.env` wins over the Keychain; `REDIS_NO_KEYCHAIN=1` skips the Keychain lookup.)
3. Restart in the documented order, with Redis in between:
   ```bash
   ./start-local.sh stop ui-api
   redis-cli -h 127.0.0.1 shutdown nosave                     # the old, unprotected Redis (stop never stops it)
   ./start-local.sh stop data-service && ./start-local.sh start data-service   # starts Redis bound + protected first
   curl -s -o /dev/null -w '%{http_code}\n' localhost:8001/ready               # 200
   ./start-local.sh start ui-api
   ./start-local.sh stop master-controller && ./start-local.sh start master-controller
   ```
4. Check (prints no password):
   ```bash
   lsof -nP -iTCP:6379 -sTCP:LISTEN                            # 127.0.0.1:6379 only, never *:6379
   redis-cli -h 127.0.0.1 ping                                 # NOAUTH Authentication required.
   REDISCLI_AUTH="$(security find-generic-password -a "$USER" -s suryadhana-redis -w)" redis-cli -h 127.0.0.1 ping   # PONG
   ```
   then open a terminal window: live quotes move again. Every later `redis-cli` command needs the same `REDISCLI_AUTH=`
   prefix (the [first-trading-day](#first-trading-day-after-a-deploy-checklist) Redis rows included). The legacy Docker
   compose is not changed (it is not run).

## Unattended reboots (power cuts, macOS updates, FileVault)

The current state is on the `reboot-recovery` row of `./start-local.sh status`. As checked on 25 Oct: the Mac
does not power back on after a power failure (`pmset -g`: `autorestart 0`), macOS is set to install updates by
itself, restarts included (`AutomaticallyInstallMacOSUpdates 1`), and FileVault is on. (What caused each reboot
of 22–25 Oct is not known.) Every SuryaDhana job (the watchdog, `caffeinate`,
the app) is a per-user LaunchAgent, which runs only once a user is logged in. So after ANY reboot nothing runs
(02:15 backup, 08:00 ICICI login, ingests, 18:30 EOD, 19:30 Desk, 19:50 shadow, the Telegram bot, the app) until
someone logs in at the Mac: 4 boots in about 4 days, 22–25 Oct. The dead-man ping tells you when it happens;
these steps remove the avoidable triggers.

1. **Power back on after a power failure** (Mac mini and other desktop Macs):
   ```bash
   sudo pmset -a autorestart 1
   pmset -g | grep -w autorestart          # autorestart 1
   ```
   (System Settings → Energy → "Start up automatically after a power failure" is the same switch.) With FileVault
   on, the Mac then boots to the FileVault unlock screen and waits there: still better than staying off, because
   you can log in the moment you are told.
2. **No automatic macOS installs** (they restart the Mac whenever macOS chooses): System Settings → General →
   Software Update → ⓘ next to *Automatic updates* → turn **off** "Install macOS updates"; keep "Download new
   updates when available" on. Keep "Install Security Responses and system files" on (security fixes; if one
   ever restarts the Mac, the dead-man ping tells you). Check:
   ```bash
   defaults read /Library/Preferences/com.apple.SoftwareUpdate AutomaticallyInstallMacOSUpdates   # 0
   ```
3. **Install macOS updates yourself** on a Sunday daytime (no trading, no freeze window, after the 02:15 backup;
   Saturday has jobs at 09:00 and 10:00), letting that one restart skip the FileVault screen:
   ```bash
   softwareupdate --list                            # what is pending
   sudo fdesetup authrestart -delayminutes -1       # the NEXT restart unlocks FileVault by itself, once
   sudo softwareupdate --install --all --restart    # or System Settings → Software Update → Update Now
   ```
   After the restart, log in if the Mac waits at the login window; the watchdog then starts the stack and
   Telegrams "the stack was down". Check `./start-local.sh status` and Telegram `/status`.
4. **FileVault: decide explicitly, and write the decision down here (date, choice).**
   - Keep it **on** (recommended): `.env` holds the ICICI password, the API keys and the Telegram bot token, and
     FileVault keeps them unreadable if the Mac is stolen or its disk removed. The cost: after an unplanned
     reboot (power cut, crash) the stack waits until you log in at the Mac; the dead-man ping tells you within
     about 15 minutes.
   - Turn it **off** only if unattended recovery matters more than the disk at rest: System Settings → Privacy &
     Security → FileVault → Turn Off (decrypts in the background), then System Settings → Users & Groups →
     "Automatically log in as" your user. After a power cut the Mac then boots, logs in and the watchdog starts
     the stack by itself; anyone with physical access gets the logged-in session and every credential in `.env`.
   - Decision: ______________________

## Version control and off-machine backup

On 25 Oct the production system existed only as an uncommitted working tree on one disk: no commit since 14 Jun,
hundreds of modified and untracked files (the desktop shell, the HTTP guard, the static UI serving, the monitor
hub), no `git remote`, Time Machine off, and the nightly backups on the same internal disk. A disk failure, a
stray `git checkout -- .` / `git clean -fd`, or a bad patch would lose them, and there is no known-good state to
diff against or roll back to. One-time, about 20 minutes:

1. **What must never be committed is ignored.** Each path below must print the `.gitignore` rule that covers it;
   for any that prints nothing, add that path to `.gitignore` first (`.logs/` and `.pids/` hold service logs, stack
   samples, open-file lists and pid state):
   ```bash
   for p in .env data/market.duckdb data/backups/x data/ui_prefs.sqlite ui/dist/x ui/.build-ui/x ui/.next-prod/x \
            .logs/x .pids/x desktop/src-tauri/target/x; do git check-ignore -q "$p" && echo "ignored  $p" || echo "NOT IGNORED  $p"; done
   ```
   `ui/node_modules/` and `ui/.next/` were committed long ago (about 14,000 files): with them ignored, take them out of
   the index once, so `git add -A` never stages package updates (the files stay on disk):
   ```bash
   git rm -r --cached --quiet ui/node_modules ui/.next
   ```
2. **Stage, then prove that no secret, no data file and no huge file is staged** (the checks print file names only):
   ```bash
   git add -A
   git diff --cached --name-only | grep -E '(^|/)\.env$|\.duckdb|\.sqlite|\.zst$|\.parquet$' && echo "STOP: git restore --staged <file>"
   git diff --cached --name-only -z | xargs -0 stat -f '%z %N' 2> /dev/null | awk '$1 > 52428800 {print "STOP, over 50 MB:", $2}'
   git diff --cached --name-only | grep -iE '\.(png|jpe?g)$'      # review each: a screenshot can show broker details
   /Users/sudheer/Desktop/jupyter_env/bin/python - << 'EOF'
   import subprocess
   from dotenv import dotenv_values
   words = ("KEY", "SECRET", "TOKEN", "PASSWORD", "TOTP", "WEBHOOK", "PING_URL", "MOBILE", "CLIENT_ID")
   secrets = [v for k, v in dotenv_values(".env").items() if v and len(v) >= 8 and any(w in k for w in words)]
   names = subprocess.run(["git", "diff", "--cached", "--name-only", "-z"], capture_output=True, text=True).stdout.split("\0")
   hits = []
   for name in filter(None, names):
       try:
           text = open(name, encoding="utf-8", errors="ignore").read()
       except OSError:
           continue                      # deleted in the working tree
       if any(s in text for s in secrets):
           hits.append(name)
   print("\n".join("STOP, holds a .env secret: " + h for h in hits) or "OK: no .env secret value in the staged files")
   EOF
   ```
3. **Commit and tag the deployed state:**
   ```bash
   git switch -c desktop-program-2026-10            # a branch for it (or commit on the current one)
   git commit -m "Desktop program: SuryaDhana.app, static UI on ui-api, HTTP guard, watchdog hang restarts"
   git tag -a desktop-20261025 -m "UI release $(curl -s localhost:8010/ready | sed -nE 's/.*"ui_build_id":"([^"]*)".*/\1/p') · $(cat ~/Library/Application\ Support/ai.suryadhana.terminal/installed-build 2> /dev/null)"
   git log -1 --oneline && git tag -n1 desktop-20261025
   ```
4. **Push to the remote.** `origin` is github.com/sudheerptl01-hash/SuryaDhana_AI and it is **PUBLIC** (the owner's
   choice, 5 Nov 2026; the earlier advice here was a private repository). Everything committed is world-readable
   for good: run the step-2 checks before **every** push, keep `data/`, logs, screenshots and `.env` out (`.gitignore`
   covers them; never `git add -f`), and never paste PORT / BRKR / RSK / DESK output into a committed file. Setting
   up a new remote:
   ```bash
   git remote add origin git@github.com:<you>/SuryaDhana_AI.git    # or: gh repo create SuryaDhana_AI --private --source . --remote origin
   git push -u origin --all && git push origin --tags
   git ls-remote --tags origin | grep desktop-20261025               # the tag is on the remote
   ```
   A private repository would also keep the strategy code private; with a public one, assume anyone can read it.
   `.env` never goes to git: keep a copy of it in your password manager.
5. **An off-machine copy of the data**, which git does not hold (`data/` is ignored: the 4.4 GB DuckDB, the
   settings store and the nightly backups). Either Time Machine to an external disk at least twice the size of
   `data/`:
   ```bash
   sudo tmutil setdestination -a /Volumes/<disk>
   sudo tmutil enable
   tmutil startbackup --auto
   tmutil destinationinfo && tmutil latestbackup      # the destination, then the newest backup
   ```
   or, weekly, copy the nightly backups to an external disk (an encrypted one if it also gets `.env`):
   ```bash
   rsync -a data/backups/duckdb/ /Volumes/<disk>/suryadhana/backups/duckdb/
   ```
   or let the backup script do it (Terminal v2 0.1): `scripts/db_backup.py --offsite [DIR]` copies tonight's
   `.duckdb(.zst)`, the `ui_prefs` `.sqlite` and both `.meta.json` to `DIR` (default `OFFSITE_BACKUP_DIR` from `.env`),
   each through a temp name + rename, verifies the DuckDB copy by sha256 and keeps the same rotation (7 daily + 4
   Sundays) there. A missing or unmounted target fails the run (exit 1) after the local backup is complete. Since
   6 Nov 2026 the 02:15 `db_backup_daily` job passes `--offsite <OFFSITE_BACKUP_DIR>` **only when `OFFSITE_BACKUP_DIR`
   is set** (in the environment, or in `.env`, read at each run: no restart needed); unset, it runs exactly as before.
   An off-site failure is reported as "Off-site backup copy FAILED" (Telegram warning, SYS `error`), not as a failed
   backup: the local copy is complete. A first run by hand (never inside a freeze window or beside the 02:15 run; one
   run at a time, a busy lock exits 75):
   ```bash
   /Users/sudheer/Desktop/jupyter_env/bin/python scripts/db_backup.py --offsite /Volumes/<disk>/suryadhana/backups/duckdb
   ```
   Steps for the owner: [Owner actions after the 5 Nov review](#owner-actions-after-the-5-nov-review-m32).
6. **Routine:** commit and push after every deploy, and tag it (`git tag -a deploy-YYYYMMDD -m …`). To see what a
   deploy changed in one file: `git diff <tag> -- <file>`; to put one file back: `git checkout <tag> -- <file>`,
   then restart that service outside the freeze windows.

## Owner actions after the 5 Nov review (M32)

The 43-page review found the appliance tells nobody when it is dark (31 Oct–4 Nov went unnoticed) and the 4.4 GB
database has no off-machine copy. Three one-time settings, about an hour in all, none needing a restart of the stack
and none inside a freeze window (07:45–09:20, 18:30–21:15 IST):

1. **O-1 · the dead-man ping (≈ 15 min, do it first).** Create the healthchecks.io check and put its URL in `.env` as
   `HEALTHCHECK_PING_URL=` exactly as in [Off-machine dead-man ping](#off-machine-dead-man-ping-healthchecksio) steps
   1–6 (optionally the second check, `HEALTHCHECK_WATCHDOG_URL=`). Done when `./start-local.sh status` shows
   `dead-man-ping  ok` within 2 minutes and the Telegram test on healthchecks.io reaches your phone.
2. **O-2 · power-on recovery (≈ 15 min).** `sudo pmset -a autorestart 1`, then `pmset -g | grep -w autorestart` prints
   `autorestart 1`; turn off automatic macOS installs and write the FileVault decision down, as in
   [Unattended reboots](#unattended-reboots-power-cuts-macos-updates-filevault) steps 1, 2 and 4. Done when the
   `reboot-recovery` row of `./start-local.sh status` no longer warns about `autorestart`.
3. **O-3 · the off-machine copy (≈ 30 min, plus one restore drill).**
   - Mount the target (an external SSD, or an rclone / cloud-drive mount) and create the folder, e.g.
     `mkdir -p /Volumes/<disk>/suryadhana/backups/duckdb`. An encrypted volume is best: the backups hold the settings
     store (`ui_prefs`).
   - Add one line to `.env` (no restart: the 02:15 job reads it at each run):
     ```bash
     [ -z "$(tail -c 1 .env)" ] || echo >> .env
     printf 'OFFSITE_BACKUP_DIR=%s\n' '/Volumes/<disk>/suryadhana/backups/duckdb' >> .env
     ```
   - Run one copy by hand outside the windows (it makes tonight's local backup too, ≈ 2–20 min). Pass the folder:
     run by hand, `db_backup.py` does not read `.env` (the 02:15 job passes it for you):
     `/Users/sudheer/Desktop/jupyter_env/bin/python scripts/db_backup.py --offsite /Volumes/<disk>/suryadhana/backups/duckdb`
     — the last line is `RESULT {…}` with `"offsite": {"sha256_verified": true, …}`. From the next night the 02:15 job
     does the same.
   - **Restore drill** (read-only on the live database; on a scratch copy):
     ```bash
     D=/Volumes/<disk>/suryadhana/backups/duckdb
     LATEST=$(ls -t "$D"/market-*.meta.json | head -1); echo "$LATEST"
     /Users/sudheer/Desktop/jupyter_env/bin/python - "$LATEST" << 'EOF'
     import hashlib, json, sys, pathlib
     meta = json.loads(pathlib.Path(sys.argv[1]).read_text()); f = pathlib.Path(sys.argv[1]).with_name(meta["file"])
     h = hashlib.sha256()
     with f.open("rb") as fh:                      # 4.7 GB: hashed in 8 MB chunks, never read whole
         for block in iter(lambda: fh.read(8 << 20), b""):
             h.update(block)
     print(meta["file"], "sha256 ok" if h.hexdigest() == meta["sha256"] else "sha256 MISMATCH", "rows", meta.get("rows"))
     EOF
     ```
     then restore that file into a scratch folder as in [§3 Restore the database](#3-restore-the-database-44-gb-git-ignored)
     (never over `data/market.duckdb` while the stack runs) and open it read-only to check the row count matches
     `rows`. Write the date of the drill here: ______________________
   - Every failure later arrives as a Telegram "Off-site backup copy FAILED" warning (target unmounted, disk full);
     the local backup is unaffected.
4. **O-12 · the public repository.** Keep the secret scan of [Version control](#version-control-and-off-machine-backup)
   step 2 before every push.

## Data health: the DATA view and `/api/data/health` (Terminal v2 1.4)

In the tree since 5 Nov 2026, live after the Terminal v2 deploy (ui-api + data-service + master-controller restarts):
until then `/api/data/health` answers from a built-in fallback seed (R-DATA §3) and says so in `catalog_source`.

- **What it is.** One row per dataset in data-service's `dataset_catalog` (`services/data-service/data_health/catalog.py`;
  rendered as `docs/TERMINAL_DATA_DICTIONARY.md`): publisher, publication time (IST), `expected_by` (IST, trading-day
  aware), what is stored (`as_of`), `lag_sessions`, state `live | fresh | amber | red | gap`, the ingest job's last and next
  run, the catch-up slot and the dictionary anchor. The SYS › DATA view (GO `DATA`) and the header chip `DATA n STALE`
  read it. No composite score; the page says "stored 30 Oct · expected by 21:00 · 3 sessions behind · catch-up 19:30
  tomorrow".
- **Read it** (no restart, no fetch from a publisher: it reads stored data, the scheduler and `ingest_log`):
  ```bash
  curl -s localhost:8010/api/data/health | /Users/sudheer/Desktop/jupyter_env/bin/python -c "
  import json, sys
  d = json.load(sys.stdin); print(d.get('catalog_source'), d.get('summary'))
  for r in d.get('rows', []):
      if r.get('state') not in ('fresh', 'live'):
          print(f\"{r['id']:28} {r['state']:6} as_of={r.get('as_of')} lag={r.get('lag_sessions')} job={r.get('job_id')}\")"
  ```
- **What happens by itself.** Hourly at :10 `data_health_check` sends one Telegram line per dataset that changes
  state (state kept in `data/.data_health_state.json`, so a restart does not repeat lines; red is critical). At 08:35
  `morning_sweep` re-runs the jobs behind amber / red rows (at most 6 light NSE fetches, never a gold or a backfill job)
  and sends the DATA digest. Inside the morning window it leaves the results ingest (≈ 14 min) to the 20:45 capture,
  and it stops waiting after `SWEEP_BUDGET_S` (480 s): data-service finishes a running job on its own and the digest
  says which step it did not wait for (6 Nov 2026, review m112). After downtime the start-up catch-up writes explicit **gap** rows for captures that only
  exist during the session (pre-open book, breadth samples, FII/DII, gold open): those cannot be backfilled, and the
  pages say "no intraday data for …" instead of showing the last day.
- **What you do.** amber: usually nothing (the 22:45 pass or the 08:35 sweep catches it). red on an NSE file: check
  the NSE archive by hand (the publisher may be late; NSE's `Last-Modified` header is GMT, add 5:30), then
  `curl -s -X POST localhost:8001/jobs/ingest-nse-files -H 'Content-Type: application/json' -d '{"datasets":["<id>"],"revalidate":true}'`
  outside the freeze windows. red on `iv_*` or `index_*`: `POST :8001/jobs/iv-eod?job=iv_eod` or
  `POST :8001/jobs/index-drivers?job=index_drivers_daily` for the missing date (same shape as `/jobs/ingest-gold`).
  A **backfill** (`iv_backfill`, `index_drivers_backfill`, `vix_backfill`) is never started inside a freeze window or
  beside the 02:15 backup; a Sunday 10:00 start (PLAN 1.8).

## First trading day after a deploy (checklist)

New backend code can go live on a non-trading day (the desktop program went live on Sunday 25 Oct), so the first
session is its first real run: the request guard against real job traffic, the monitor hub under real ticks, the
08:00 login, the 18:30–21:15 chain and the first 02:15 settings backup. Read-only checks (none restarts anything):

| When (IST) | Check | Good |
|---|---|---|
| 08:05 | Telegram: the ICICI login result, then `/status` | "ICICI logged in" (or "session already valid"); every service and the terminal UI green (the dead-man and reboot lines stay ⚠️ until those one-time steps are done) |
| 09:20 | with a terminal window open (the app, or a browser on :8010): `redis-cli -h 127.0.0.1 PUBSUB NUMSUB live.quotes` (with a Redis password, prefix `REDISCLI_AUTH=…`, see [Redis password](#redis-password-terminal-v2-07-o-t10)) | `live.quotes` then 1 or more (ui-api's monitor hub subscribes while a window is open, and lets go 15 s after the last one closes) |
| 09:20 | `timeout 10 redis-cli -h 127.0.0.1 SUBSCRIBE live.quotes` | tick messages arrive (NIFTY at least) |
| 09:20, 15:35 | `grep -c http_guard.rejected .logs/ui-api.log .logs/data-service.log .logs/master-controller.log` | the counts do not grow; if they do, read those lines: a job the guard blocked shows its path |
| 15:35, 21:20 | the scheduler's results (below) | every job that ran today says `done` (or `no new data` / `skipped`, see SYS job history above), none `error` |
| 21:20 | `ls -l alpha_lab/reports/shadow_status.md`; the DESK page | the shadow status and the Desk show today |
| 08:50, 16:00, 21:40 | the GOLD page header strip and the SYS rows `gold_*` (26 Oct 2026) | the MCX settlement labelled by its session (Monday shows "Fri … settlement"), no STALE chip older than `GOLD_MAX_AGE_DAYS`, the 15:45 CME job `done` (log the hour the FTP file arrived in week one); Saturday ≈ 03:30: the "COT <date>: funds net …" Telegram digest line |
| 02:20 next night | `ls -l data/backups/duckdb/*"$(date +%Y%m%d)"*` | a `market-` and a `ui_prefs-` backup dated today |
| 21:30, 22:00 (Terminal v2, first week) | the scheduler's `nse_positions_catchup`, `iv_eod`, `index_drivers_daily`; the [data-health](#data-health-the-data-view-and-apidatahealth-terminal-v2-14) summary | `iv_eod` done by 21:30 five days running; the drivers job found the top-10 file (published ≈ 16:30); at 22:00 at most 2 amber rows (PLAN G13) |

```bash
curl -s localhost:8008/api/scheduler/status | /Users/sudheer/Desktop/jupyter_env/bin/python -c "
import json, sys
for j in json.load(sys.stdin)['jobs']:
    if j['last_status']:
        print(f\"{j['id']:32} {j['last_status']:6} {j['last_run_ts']}\")"
```
(Each job's latest result; `last_run_source` says whether it ran since master-controller last started
(`this_run`) or before (`history`, from `data/.scheduler_history.json`).) If something broke: a bad UI release → `./start-local.sh build-ui
--rollback`; a bad app build → `scripts/build_desktop.sh --rollback --relaunch`; backend code → the deploy tag
([Version control](#version-control-and-off-machine-backup), step 6), restarted outside the freeze windows.
