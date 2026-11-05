# Resilience review — the 16→19 Oct outage and everything like it (19 Oct 2026)

**Trigger:** on Monday 19 Oct at 09:26 IST the whole stack was found down. It had been dark since Friday 16 Oct
~07:51 IST, so Friday's ICICI login, EOD pipeline, Desk mark, S1 shadow, wrap and first weekly journal never
ran, and nobody was told. The owner asked to review flaws like this one completely and resolve them.

## Root cause (evidence: `pmset -g log`, `last`, service logs)
1. The machine is a **Mac mini on AC, set to `sleep 1`** (idle sleep after one minute). The only thing keeping it
   awake was a Claude Code session's caffeinate assertion. At 07:51 Friday the power log shows DarkWake cycling, and the
   service logs stop at that moment: **the stack froze when the Mac slept.**
2. At 15:54 it went through an **unclean reboot** (`last` shows the reboot with no shutdown record).
3. Nothing started the stack after the reboot (`start-local.sh` only runs by hand), and **the only alerter (the
   controller) was part of the stack**, so the outage was silent for three days.
4. On restart, the in-memory scheduler counted every next run from "now", so **missed runs were never caught
   up or reported.**

## Findings → fixes (all verified)
| # | Flaw | Evidence | Fix | Verified |
|---|---|---|---|---|
| R1 | Stack never auto-starts after reboot or login | 3-day outage | LaunchAgent `com.suryadhana.watchdog` (RunAtLoad + every 2 min) starts the core stack | installed; Drill 3 below |
| R2 | Crashed services stay down | — | watchdog restarts down core services: checked twice 30 s apart, never touches running ones, 300 s start timeout | Drill 1: detected in 32 s (restart blocked by R10, now fails fast) |
| R3 | No alert when the stack is down (alerter inside the stack) | 3 silent days | watchdog Telegrams directly via the Bot API (throttled); optional off-machine dead-man `HEALTHCHECK_PING_URL` | code + owner action O3 |
| R4 | Mac idle-sleeps after 1 min → scheduler freezes | `pmset` sleep=1; logs stop at DarkWake | LaunchAgent `com.suryadhana.awake` = `caffeinate -s -i` (KeepAlive) | assertion live: "PreventUserIdleSystemSleep … forever" |
| R5 | Missed scheduled runs silently skipped | APScheduler in-memory store | controller heartbeat (`data/.controller_heartbeat.json`, every 60 s); on start: exact missed-run counts from each trigger, catch-up planned around market hours and freeze windows, one Telegram report | Drill 2: reproduced the real outage exactly (EOD×1, Desk×1, shadow×1, backup×3 …); 4 tests |
| R6 | **NSE served another session's file for a date, and the downloader cached it under that date.** On a publication-delay day this would freeze the table and hide that session **permanently** | `…20261018.csv.gz` contained `16-Oct-2026` rows | `bhavcopy.ingest_range` rejects files whose internal date ≠ requested date, purges the cache, counts the day missing (retried later), reports `date_mismatches` | 2 tests incl. self-heal; **the poisoned 18-Oct file was purged in production** |
| R7 | `start` launched the 3 dormant legacy services (~1 GB RAM) | 09:53 start launched ml, feature and rl | `start` = core 4; `start legacy` opt-in | `help` + live |
| R8 | ui-api ran `--reload` as its canonical mode, so any file save restarts the live backend | critique R1 | opt-in `UI_API_RELOAD=1`; default plain server | `ps` shows no --reload |
| R9 | No way to stop a service on purpose that a supervisor would respect | — | `stop` writes `.pids/paused/<svc>`, `start` clears it; watchdog skips paused | Drill 3: paused ui-api left down, marker cleared on start |
| R10 | **macOS privacy (TCC) blocks the stack's Python under launchd**: the env is in `~/Desktop`; background processes hang on a consent prompt | throwaway agent: `ls ~/Desktop` ok, `python -c 'import sys'` blocked | watchdog 15 s Python preflight → never hangs, Telegrams the exact fix; **one-time grant needed (owner O1)** | `timeout` kills the blocked process: rc=124 at 15 s, no orphans |
| R11 | tick_store: shutdown's final flush could overlap a slow flush, reuse a part index and **overwrite ticks** | critique C2 LOW; reproduced | part writes serialized behind `_write_lock` | test fails without the lock (1 of 2 parts survives), passes with it |
| R12 | RSK broker-staleness: tz-aware timestamp raised an uncaught `TypeError` | critique E8 | normalize tz, catch TypeError | suite green |
| R13 | MCX live quotes never verified (deferred W4) | — | verified with today's ICICI session: GOLD ₹1,48,458 · GOLDM ₹1,46,843 · GOLDPETAL ₹14,791 (1-min-bar path) | live |

Today's recovery: stack started at 09:53. Friday's NSE bhavcopy, positions (F&O, OI, deals, MTF) and events were caught
up, and the monitor is as of 16 Oct. Yahoo bars and the ML rebuild run in tonight's 18:30 pipeline, the first live run of
the 15 Oct step-isolation fix. **Tests: 958 green** (325 · 144 · 462 · 7 · 20) and tsc clean.

## Owner actions (cannot be done from code)
| # | Action | Why | How |
|---|---|---|---|
| **O1** | **Allow Python Desktop-folder access** | Without it the watchdog can detect a crash but not restart (R10) | System Settings → Privacy & Security → Files and Folders → allow Python "Desktop Folder" (or click **Allow** on the waiting prompt). Then test: `kill` a service and wait ~2.5 min |
| O2 | `sudo pmset -a autorestart 1` | The Mac powers back on after a power cut | Terminal, once. FileVault still waits for a login |
| O3 | Off-machine dead-man switch | The only alert that works when the Mac itself is off, hung, or at the FileVault screen | free check at healthchecks.io (period 5 min, grace 15 min) → add `HEALTHCHECK_PING_URL=https://hc-ping.com/<uuid>` to `.env` |
| O4 | **Git remote** (open since 14 Oct) | Code still exists only on this disk; last commit 14 Jun | private GitHub repo → `git push` |
| O5 | Off-machine backup copy | 02:15 backups are same-disk | external disk or cloud folder target |

## What a reboot looks like now
Reboot → FileVault login (human) → watchdog starts the stack (Telegram: "stack was down, restarted …") → controller
start detects the gap → NSE data caught up (or the full EOD pipeline when the market is shut) → Telegram report with
the missed runs → Desk and shadow catch up on their next nightly run. With O3 in place, the dead-man check also fires
while the Mac is still off.
