#!/bin/bash
# SuryaDhana stack watchdog — the stack's self-healing and its alerter of last resort.
#
# Run by launchd at login and every 2 minutes (ops/launchd/com.suryadhana.watchdog.plist; install with
# scripts/install_launch_agents.sh). Why it exists (19 Oct 2026 resilience review): on Fri 16 Oct the Mac
# mini slept/rebooted, nothing restarted the stack, and because the only alerter (master-controller) was
# part of the stack, nobody knew for three days.
#
# Rules:
#   * starts a CORE service only if it is down on two checks 30 s apart, never restarts one that answers;
#   * never starts a service that was stopped on purpose (start-local.sh writes .pids/paused/<svc>);
#   * stays out of the way while a start-local.sh run is in progress;
#   * Telegram goes straight to the Bot API (independent of master-controller), throttled;
#   * off-machine dead-man switch: HEALTHCHECK_PING_URL in .env (a free healthchecks.io check, see
#     docs/RUNBOOK_RESTORE.md "Off-machine dead-man ping") is pinged when the stack is healthy and at /fail when
#     it is not — the only signal that survives the Mac itself being off or stopped at the FileVault screen. The
#     last result ("<epoch> ok|fail|error", never the URL) is kept in .pids/watchdog/deadman for status;
#   * a SECOND heartbeat (Terminal v2 PLAN 0.2): HEALTHCHECK_WATCHDOG_URL, pinged on every run before anything is
#     checked, whatever the stack's state — it stops only when the Mac itself is off, asleep, at the FileVault screen
#     or launchd no longer runs this script. Read with the first: first = fail while the second beats → the stack is
#     down on a live Mac; both silent → the Mac is gone. Result in .pids/watchdog/deadman_watchdog ("<epoch> ok|error");
#   * also: Telegram when ui-api is up but there is no UI release to serve (at most every 6 h), and an
#     hourly `start-local.sh rotate-logs` (the .logs/*.log size cap);
#   * a HUNG core service (25 Oct 2026: ui-api listened but stopped answering for 8 min, and the old watchdog
#     only logged "already running" / "FAILED to start") is restarted with `start-local.sh restart <svc>` when
#     EVERY listener on its port is its own uvicorn, /health on 127.0.0.1 (the address the services bind) got no
#     200 at both checks of a run (the 30 s debounce), on WATCHDOG_HANG_RUNS consecutive runs (default 2) against
#     the same listener pid(s), and still none just before the restart. data-service and master-controller above
#     WATCHDOG_BUSY_CPU % CPU (default 50) are busy, not wedged: they wait WATCHDOG_BUSY_RUNS runs (default 8).
#     Diagnostics are saved first to .logs/hangs/<stamp>-<svc>/ (sample, lsof, the last 200 log lines, and every
#     Python thread's stack for a service that registered faulthandler on SIGUSR1, i.e. ui-api; the newest 10
#     captures are kept, plus each service's first capture of the last 24 h). Right before the restart it checks
#     again that nobody stopped or restarted the service by hand meanwhile (paused marker, a start-local.sh run, a
#     changed listener). At most WATCHDOG_HANG_MAX_RESTARTS (3) hang restarts per service per hour, then it only
#     alerts until the hour is up or the service is restarted by hand. Never inside a restart freeze window for
#     data-service / master-controller (07:45-09:20 and 18:30-21:15 IST; ui-api any time); master-controller
#     waits (at most WATCHDOG_LOGIN_DEFER_MAX_MIN, 10 min) while an ICICI login it may be relaying an OTP for runs;
#     a port shared with another program is never stopped: it alerts instead. WATCHDOG_DRY_RUN=1 logs what it
#     would do and changes nothing.
#
# Editing this file: launchd runs it every 2 minutes and bash reads a running script incrementally, so never
# rewrite it in place; write a temp file next to it and rename it over this one (C2-reliability-ops-01).
# The body is one function called from the last line, so a run never reads past that line.
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"   # launchd's PATH is minimal
export UI_MODE=prod                     # only used if frontend is ever started through start-local.sh
STATE="$ROOT/.pids/watchdog"
LOG="$ROOT/.logs/watchdog.log"
mkdir -p "$STATE" "$ROOT/.logs"
# The 3-process core (desktop program, 24 Oct 2026): ui-api serves the terminal UI (ui/dist/current), so
# the Next frontend on :3000 is optional and never auto-started (./start-local.sh start frontend).
CORE="data-service ui-api master-controller"
DEBOUNCE_S="${WATCHDOG_DEBOUNCE_S:-30}"         # second look before acting on a down/hung service
HANG_RUNS="${WATCHDOG_HANG_RUNS:-2}"            # consecutive hung runs (2 min apart) before a restart
HANG_STALE_MIN="${WATCHDOG_HANG_STALE_MIN:-6}"  # a hang count older than this (a missed run, a sleep) starts over
BUSY_CPU="${WATCHDOG_BUSY_CPU:-50}"             # data-service / master-controller above this % CPU: busy, not wedged
BUSY_RUNS="${WATCHDOG_BUSY_RUNS:-8}"            # hung runs required while busy (about 16 min)
HANG_MAX_RESTARTS="${WATCHDOG_HANG_MAX_RESTARTS:-3}"   # hang restarts of one service per window, then alert only
HANG_WINDOW_MIN="${WATCHDOG_HANG_WINDOW_MIN:-60}"
LOGIN_DEFER_MAX_MIN="${WATCHDOG_LOGIN_DEFER_MAX_MIN:-10}"   # master-controller waits at most this for a login
HANG_DIR="$ROOT/.logs/hangs"                    # diagnostics captured before each hang restart
HANG_KEEP="${WATCHDOG_HANG_KEEP:-10}"           # captures kept (oldest removed first)
DRY_RUN="${WATCHDOG_DRY_RUN:-0}"                # 1 = log the hang decisions, never capture or restart
HEALTH_TIMEOUT_S="${WATCHDOG_HEALTH_TIMEOUT_S:-8}"   # seconds a /health probe may take

ts()  { TZ=Asia/Kolkata date "+%Y-%m-%d %H:%M:%S"; }
log() { echo "[$(ts)] $*" >> "$LOG"; }
LOCK="$STATE/lock"

env_val() { grep -E "^$1=" "$ROOT/.env" 2>/dev/null | tail -1 | cut -d= -f2- | sed -e 's/^["'"'"']//' -e 's/["'"'"']$//'; }
tg() {
  local tok chat; tok=$(env_val TELEGRAM_BOT_TOKEN); chat=$(env_val TELEGRAM_CHAT_ID)
  log "alert: $(printf '%s' "$1" | head -1)"
  [ -n "$tok" ] && [ -n "$chat" ] || return 0
  curl -s -m 15 -X POST "https://api.telegram.org/bot$tok/sendMessage" \
       --data-urlencode "chat_id=$chat" --data-urlencode "text=$1" > /dev/null 2>&1 || true
}
# once per key per N minutes
throttled() { local f="$STATE/throttle-$1"; [ -n "$(find "$f" -mmin -"$2" 2>/dev/null)" ] && return 0; touch "$f"; return 1; }

# The services bind 127.0.0.1 only (start-local.sh), so they are probed there: `localhost` tries ::1 first, where
# another program (a Node dev server binds [::]) could answer for a hung service (R-OPS-05).
health_url() {
  case "$1" in
    frontend) echo "http://127.0.0.1:$(svc_port "$1")" ;;
    *) echo "http://127.0.0.1:$(svc_port "$1")/health" ;;
  esac
}
# health_code <svc> → the HTTP status of its /health, or 000 when nothing answered in HEALTH_TIMEOUT_S
health_code() { curl -s -o /dev/null -m "$HEALTH_TIMEOUT_S" -w '%{http_code}' "$(health_url "$1")" 2>/dev/null; }
is_up() { [ "$(health_code "$1")" = "200" ]; }
start_local_running() { pgrep -f "start-local.sh" > /dev/null 2>&1; }

# ── single instance ─────────────────────────────────────────────────────────────────────────────────────────
# The lock is a directory with an owner file "<pid> <boot epoch>". A lock left by a run that died without its EXIT
# trap (power loss, SIGKILL, launchd's exit timeout) is stale at once when its owner is gone, is not a watchdog,
# or ran before this boot; a lock without an owner file is stale when it predates this boot; and any lock older
# than 20 min is stale. Before 25 Oct (SECREL-05) only the 20 min age counted, so a lock left by a power cut
# silenced every run for up to 20 min after the reboot.
# boot_epoch → the boot time in epoch seconds: the FIRST field of `sysctl -n kern.boottime`
# ("{ sec = 1792906041, usec = 658471 } Sun Oct 25 10:57:21 2026"). The desktop app reads the same owner file and
# compares it with kern.boottime's sec (desktop/src-tauri/src/stack.rs watchdog_lock_held). Until the 25 Oct round 4
# the greedy pattern '.*sec = ' matched "usec = " and returned the microseconds, so the app never saw a watchdog run.
boot_epoch() { sysctl -n kern.boottime 2> /dev/null | sed -nE 's/^[{] *sec = ([0-9]+),.*/\1/p'; }
file_epoch() { date -r "$1" +%s 2> /dev/null; }      # mtime (BSD and GNU date)
lock_is_stale() {
  local owner_pid="" owner_boot="" boot made
  [ -n "$(find "$LOCK" -maxdepth 0 -mmin +20 2> /dev/null)" ] && return 0
  boot=$(boot_epoch)
  if [ -f "$LOCK/owner" ]; then
    read -r owner_pid owner_boot < "$LOCK/owner" 2> /dev/null
    # only an epoch is compared: an owner line written before the boot_epoch fix holds kern.boottime's usec (at most
    # 6 digits), which says nothing about the boot, so the pid checks below decide for it
    case "$owner_boot" in
      [0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]*)
        case "$owner_boot" in *[!0-9]*) ;; *) [ -n "$boot" ] && [ "$owner_boot" != "$boot" ] && return 0 ;; esac ;;
    esac
    case "$owner_pid" in ""|*[!0-9]*) return 0 ;; esac
    kill -0 "$owner_pid" 2> /dev/null || return 0
    case "$(proc_cmd "$owner_pid")" in *stack_watchdog*) return 1 ;; *) return 0 ;; esac
  fi
  made=$(file_epoch "$LOCK")
  [ -n "$boot" ] && [ -n "$made" ] && [ "$made" -lt "$boot" ] && return 0
  return 1                                   # no owner yet: a run that has just taken it
}
take_lock() {
  if ! mkdir "$LOCK" 2> /dev/null; then
    lock_is_stale || return 1
    log "removed a stale watchdog lock (its run is gone, or it is from before this boot)"
    rm -rf "$LOCK"
    mkdir "$LOCK" 2> /dev/null || return 1
  fi
  echo "$$ $(boot_epoch)" > "$LOCK/owner"
}
# only this run's own lock is removed (a run that outlived 20 min must not remove its successor's)
release_lock() { [ "$(cut -d' ' -f1 "$LOCK/owner" 2> /dev/null)" = "$$" ] && rm -rf "$LOCK"; return 0; }

# ── hung services: listening, but /health does not answer ────────────────────────────────────────────────
svc_port() {
  case "$1" in data-service) echo 8001 ;; ui-api) echo 8010 ;; master-controller) echo 8008 ;; frontend) echo 3000 ;; esac
}
listener_pids() { lsof -nP -tiTCP:"$(svc_port "$1")" -sTCP:LISTEN 2> /dev/null | sort -un; }
listener_pid()  { listener_pids "$1" | head -1; }
proc_cmd()  { ps -o command= -p "$1" 2> /dev/null; }
proc_ppid() { ps -o ppid= -p "$1" 2> /dev/null | tr -d ' '; }
proc_pcpu() { ps -o pcpu= -p "$1" 2> /dev/null | tr -d ' '; }
# listener_is_ours <svc> <pid> — the listener is the uvicorn start-local.sh runs for this service
# (`python -m uvicorn <app> --host 127.0.0.1 --port <port> …`) or its child (the UI_API_RELOAD=1 worker).
# `start-local.sh restart` stops EVERY process listening on the port, so the hang path is taken only when every
# listener is ours (all_listeners_ours); a port shared with anything else (Docker's port forwarder for the legacy
# compose stack, a dev server on [::1], another app) is never restarted: the watchdog alerts instead.
listener_is_ours() {
  local port p cmd
  port=$(svc_port "$1")
  for p in "$2" "$(proc_ppid "$2")"; do
    case "$p" in ""|0|1) continue ;; esac
    cmd=$(proc_cmd "$p")
    case "$cmd" in *uvicorn*" --port $port "*|*uvicorn*" --port $port") return 0 ;; esac
  done
  return 1
}
all_listeners_ours() {   # all_listeners_ours <svc> <pid>...
  local svc=$1 p
  shift
  [ $# -gt 0 ] || return 1
  for p in "$@"; do listener_is_ours "$svc" "$p" || return 1; done
  return 0
}
first_foreign() {        # first_foreign <svc> <pid>... → the first listener that is not ours
  local svc=$1 p
  shift
  for p in "$@"; do listener_is_ours "$svc" "$p" || { echo "$p"; return 0; }; done
  return 1
}
# max_pcpu <pid>... → the highest % CPU among them, as an integer (ps' decaying average over about a minute)
max_pcpu() {
  local p c m=0
  for p in "$@"; do
    c=$(proc_pcpu "$p"); c=${c%%.*}
    case "$c" in ""|*[!0-9]*) continue ;; esac
    [ "$c" -gt "$m" ] && m=$c
  done
  echo "$m"
}
ist_hm() { TZ=Asia/Kolkata date "+%H%M"; }
# Restart freeze windows (CLAUDE.md): data-service and master-controller are never restarted 07:45-09:20 (ICICI
# login + pre-open jobs) or 18:30-21:15 IST (EOD pipeline, desk, shadow, wrap), ends included. ui-api any time.
in_freeze() {
  case "$1" in data-service|master-controller) ;; *) return 1 ;; esac
  local hm; hm=$((10#$(ist_hm)))
  { [ "$hm" -ge 745 ] && [ "$hm" -le 920 ]; } || { [ "$hm" -ge 1830 ] && [ "$hm" -le 2115 ]; }
}
# An ICICI login in progress: a Python process running scripts/daily_session_refresh.py (the 08:00 job and
# Telegram /login, a child of master-controller for up to 8 min; or run by hand, relaying its SMS OTP through the
# controller's Telegram poller). A master-controller restart kills it (start-local.sh stops the whole process
# tree) or takes away the poller that relays its OTP, and a second login would text a new OTP that voids the
# first; so only master-controller's hang restart waits for it, at most LOGIN_DEFER_MAX_MIN. ui-api and
# data-service never wait: the login hands its token to ui-api, or writes .env when ui-api does not answer,
# and a hung one cannot take it anyway. The interactive scripts/icici_session_helper.py (it waits at a prompt
# and writes .env only) defers nothing (R-OPS-01). Editors, tail, pytest on test_*.py and look-alike names do
# not count.
LOGIN_RX='[Pp]ython[0-9.]*( +-[^ ]+)* +([^ ]*/)?daily_session_refresh\.py( |$)'
login_running() { pgrep -f -- "$LOGIN_RX" > /dev/null 2>&1; }

# .pids/watchdog/hung-<svc> = "<listener pids, comma-joined> <count>". The count starts over when the listener
# changed (the service was restarted meanwhile) or the file is older than HANG_STALE_MIN (a missed run, a sleep),
# so a hang is always seen on consecutive runs against the same process (R-OPS-11).
hung_count() {   # hung_count <svc> [<pids key>]
  local f="$STATE/hung-$1" p="" n=""
  [ -f "$f" ] || { echo 0; return 0; }
  [ -n "$(find "$f" -mmin +"$HANG_STALE_MIN" 2> /dev/null)" ] && { echo 0; return 0; }
  read -r p n < "$f" 2> /dev/null
  case "$n" in ""|*[!0-9]*) echo 0; return 0 ;; esac
  if [ -n "${2:-}" ] && [ "$p" != "$2" ]; then echo 0; return 0; fi
  echo "$n"
}
note_hung()  { local n; n=$(( $(hung_count "$1" "$2") + 1 )); echo "$2 $n" > "$STATE/hung-$1"; echo "$n"; }
clear_hung() { rm -f "$STATE/hung-$1" "$STATE/login-defer-$1"; }
# what /health did, for the log and the alert: "timed out" (nothing answered) or "answered HTTP <code>"
health_says() { if [ "${1:-000}" = "000" ]; then echo "timed out"; else echo "answered HTTP $1"; fi; }

# Hang restarts per service, one epoch per line in .pids/watchdog/hang-restarts-<svc> (start-local.sh removes the
# file when the owner starts or restarts that service by hand). recent_hang_restarts drops lines older than
# HANG_WINDOW_MIN and prints how many are left (R-OPS-02: before, a service that stayed wedged was restarted
# every ~4 min forever).
recent_hang_restarts() {
  local f="$STATE/hang-restarts-$1" cut n
  [ -f "$f" ] || { echo 0; return 0; }
  cut=$(( $(date +%s) - HANG_WINDOW_MIN * 60 ))
  if [ "$DRY_RUN" = "1" ]; then                       # a dry run changes nothing: count without pruning the file
    n=$(awk -v c="$cut" '$1 ~ /^[0-9]+$/ && $1 > c' "$f" 2> /dev/null | grep -c .)
  else
    awk -v c="$cut" '$1 ~ /^[0-9]+$/ && $1 > c' "$f" > "$f.tmp" 2> /dev/null && mv -f "$f.tmp" "$f"
    n=$(grep -c . "$f" 2> /dev/null)
  fi
  echo "${n:-0}"
}
note_hang_restart() { date +%s >> "$STATE/hang-restarts-$1"; }

# diagnostics (functions, so tests can stand them in): a 3 s stack sample, the open files
diag_sample() { timeout 30 /usr/bin/sample "$1" 3 -file "$2" > /dev/null 2>&1; }
diag_lsof()   { timeout 20 lsof -nP -p "$1" > "$2" 2>&1; }
# py_stacks_registered <svc> <pid> — the listener registered faulthandler on SIGUSR1 and said so: it is the process
# start-local.sh last started (.pids/<svc>.pid), so its output is .logs/<svc>.log after the last start banner (or
# .log.1 after a rotation), and that section has the start-up line '"stack_dump_signal": "SIGUSR1"' (ui-api's loop
# watchdog, services/ui-api/routers/_loop_watchdog.py). Only then is USR1 sent: SIGUSR1's default action is to
# terminate a process that has no handler for it (R-OPS-07). Under UI_API_RELOAD=1 the pidfile names uvicorn's
# --reload supervisor, which has no handler (its worker child registered it and wrote the line): it is never
# signalled, or USR1 would kill it and orphan the hung worker on the port (round 3 review).
py_stacks_registered() {
  local svc=$1 pid=$2 f ln
  [ "$(tr -d ' \n' < "$ROOT/.pids/$svc.pid" 2> /dev/null)" = "$pid" ] || return 1
  case "$(proc_cmd "$pid")" in *" --reload"*) return 1 ;; esac
  for f in "$ROOT/.logs/$svc.log" "$ROOT/.logs/$svc.log.1"; do
    ln=$(grep -n "start-local\.sh: starting $svc on " "$f" 2> /dev/null | tail -1 | cut -d: -f1)
    [ -n "$ln" ] || continue
    tail -n +"$ln" "$f" | grep -q '"stack_dump_signal": "SIGUSR1"'
    return $?
  done
  return 1
}
# diag_pystacks <svc> <pid> <out> — every Python thread's stack: faulthandler writes it into the service log on
# SIGUSR1 (a C-level handler, so it works while the event loop is stuck); the new bytes are copied to <out>.
# Status 2 = not sent (no handler announced), 1 = sent but nothing arrived.
diag_pystacks() {
  local log="$ROOT/.logs/$1.log" size
  py_stacks_registered "$1" "$2" || return 2
  size=$(wc -c < "$log" 2> /dev/null | tr -d ' ')
  kill -USR1 "$2" 2> /dev/null || return 1
  sleep 1
  tail -c +"$((${size:-0} + 1))" "$log" > "$3" 2> /dev/null
  [ -s "$3" ] || { rm -f "$3"; return 1; }
}

# capture_hang <svc> <health code> <pid>... → prints the capture directory .logs/hangs/<IST stamp>-<svc>:
# summary.txt (what was seen, ps of each listener), py-stacks-<pid>.txt (when the service supports it),
# sample-<pid>.txt, lsof-<pid>.txt, log-tail.txt (200 lines)
capture_hang() {
  local svc=$1 code=$2 d p port conns rc; shift 2
  port=$(svc_port "$svc")
  d="$HANG_DIR/$(TZ=Asia/Kolkata date "+%Y%m%d-%H%M%S")-$svc"
  mkdir -p "$d"
  conns=$(lsof -nP -iTCP:"$port" -sTCP:ESTABLISHED 2> /dev/null | grep -c ESTABLISHED)
  { echo "service: $svc  port: $port  listener pid(s): $*  pidfile: $(cat "$ROOT/.pids/$svc.pid" 2> /dev/null)"
    echo "captured: $(ts) IST by scripts/stack_watchdog.sh: listening, /health $(health_says "$code") (${HEALTH_TIMEOUT_S} s limit)"
    echo "hung runs: $(hung_count "$svc")  established TCP connections on :$port (both ends counted): $conns"
    for p in "$@"; do ps -o pid,ppid,pcpu,pmem,rss,etime,state,command -p "$p" 2>&1; done
  } > "$d/summary.txt"
  for p in "$@"; do               # Python stacks first: the dump is instant, the sample takes 3 s
    rc=0; diag_pystacks "$svc" "$p" "$d/py-stacks-$p.txt" || rc=$?
    case "$rc" in
      0) ;;
      2) echo "py-stacks $p: not requested (the process announced no SIGUSR1 stack dump in .logs/$svc.log)" >> "$d/summary.txt" ;;
      *) echo "py-stacks $p: SIGUSR1 sent, nothing written" >> "$d/summary.txt" ;;
    esac
  done
  for p in "$@"; do
    diag_sample "$p" "$d/sample-$p.txt" || echo "sample $p: failed or unavailable" >> "$d/summary.txt"
    diag_lsof "$p" "$d/lsof-$p.txt" || echo "lsof $p: failed" >> "$d/summary.txt"
  done
  tail -n 200 "$ROOT/.logs/$svc.log" > "$d/log-tail.txt" 2> /dev/null || echo "no .logs/$svc.log" >> "$d/summary.txt"
  prune_hangs
  echo "$d"
}

# prune_hangs — keep the newest HANG_KEEP captures, plus each service's FIRST capture of the last 24 h (the start
# of a hang storm, usually the most telling one); only <YYYYmmdd-HHMMSS>-<svc> directories are touched
prune_hangs() {
  local all n i=0 d svc keep=""
  all=$(ls -1 "$HANG_DIR" 2> /dev/null | grep -E '^[0-9]{8}-[0-9]{6}-[a-z-]+$' | sort)
  for svc in $CORE; do
    for d in $all; do
      case "$d" in *-"$svc") ;; *) continue ;; esac
      [ -n "$(find "$HANG_DIR/$d" -maxdepth 0 -mmin -1440 2> /dev/null)" ] || continue
      keep="$keep $d"
      break
    done
  done
  n=$(printf '%s\n' "$all" | grep -c .)
  for d in $all; do
    [ $((n - i)) -le "$HANG_KEEP" ] && break
    case " $keep " in *" $d "*) ;; *) rm -rf "${HANG_DIR:?}/$d" ;; esac
    i=$((i + 1))
  done
}

# handle_hung <svc> — one run's decision for a service whose own uvicorn holds every listener on its port but gave
# /health no 200 at both checks of this run: count it (against the same listener pids); once it has been hung
# HANG_RUNS runs in a row (BUSY_RUNS while data-service / master-controller is busy at high CPU), alert-and-wait in a
# freeze window or (master-controller) while an ICICI login runs; otherwise probe once more and, still hung and
# under the hourly cap, capture diagnostics, check that nobody restarted or stopped it by hand meanwhile, and
# restart it. The count restarts after every attempt, so a service that stays hung is retried every HANG_RUNS runs,
# at most HANG_MAX_RESTARTS times per HANG_WINDOW_MIN.
handle_hung() {
  local svc=$1 n pids key pid code dir rel says cpu now restarts
  pids=$(listener_pids "$svc" | tr '\n' ' '); pids=${pids% }
  key=$(printf '%s' "${pids:--}" | tr ' ' ',')
  pid=${pids%% *}
  n=$(note_hung "$svc" "$key")
  if [ "$n" -lt "$HANG_RUNS" ]; then
    log "$svc is listening (pid ${pid:-?}) but /health did not answer: hung check $n/$HANG_RUNS"
    return 0
  fi
  case "$svc" in
    data-service|master-controller)   # a long job holding the GIL looks hung too; a wedged loop sits near 0 % (R-OPS-06)
      # shellcheck disable=SC2086
      cpu=$(max_pcpu $pids)
      if [ "$cpu" -gt "$BUSY_CPU" ] && [ "$n" -lt "$BUSY_RUNS" ]; then
        log "$svc is listening (pid ${pid:-?}) but /health did not answer, at ${cpu}% CPU: busy, not treated as hung yet (check $n/$BUSY_RUNS)"
        throttled "hang-busy-$svc" 60 || tg "⚠️ SuryaDhana: $svc is not answering /health but is busy (${cpu}% CPU), likely a long job rather than a hang. The watchdog waits about $((BUSY_RUNS * 2)) min before it restarts it."
        return 0
      fi ;;
  esac
  if in_freeze "$svc"; then
    log "$svc hung ($n checks, pid ${pid:-?}) inside its restart freeze window: NOT restarted"
    throttled "hang-freeze-$svc" 30 || tg "⚠️ SuryaDhana: $svc is hung (listening, /health not answering) but it is inside its restart freeze window (07:45–09:20 / 18:30–21:15 IST), so the watchdog did not restart it.
If it is still hung when the window ends, the watchdog restarts it then. To restart it now: ./start-local.sh restart $svc"
    return 0
  fi
  if [ "$svc" = "master-controller" ] && login_running; then
    [ -f "$STATE/login-defer-$svc" ] || : > "$STATE/login-defer-$svc"
    if [ -z "$(find "$STATE/login-defer-$svc" -mmin +"$LOGIN_DEFER_MAX_MIN" 2> /dev/null)" ]; then
      log "$svc hung ($n checks, pid ${pid:-?}) while an ICICI login runs: restart deferred (at most $LOGIN_DEFER_MAX_MIN min)"
      throttled "hang-login-$svc" 15 || tg "⚠️ SuryaDhana: $svc is hung (listening, /health not answering). An ICICI login is in progress (it may be waiting for your OTP), so the restart waits until it ends, at most $LOGIN_DEFER_MAX_MIN min."
      return 0
    fi
    log "$svc hung ($n checks, pid ${pid:-?}): an ICICI login has been running for over $LOGIN_DEFER_MAX_MIN min, restarting anyway"
  fi
  rm -f "$STATE/login-defer-$svc"
  code=$(health_code "$svc")                           # last look: dead services were started first
  if [ "$code" = "200" ]; then
    log "$svc answered /health again before its restart: not restarted"
    clear_hung "$svc"
    return 0
  fi
  says=$(health_says "$code")
  restarts=$(recent_hang_restarts "$svc")
  if [ "$restarts" -ge "$HANG_MAX_RESTARTS" ]; then
    throttled "hang-storm-log-$svc" 10 || log "$svc hung again ($n checks, pid ${pid:-?}, /health $says) after $restarts hang restarts in the last $HANG_WINDOW_MIN min: NOT restarted (alert only until that window frees up or it is restarted by hand)"
    throttled "hang-storm-$svc" 60 || tg "🔴 SuryaDhana: $svc keeps hanging: restarted $restarts times in the last $HANG_WINDOW_MIN min and hung again (/health $says). The watchdog stops restarting it for now and only alerts.
Check .logs/hangs/ and .logs/$svc.log, then: ./start-local.sh restart $svc"
    return 0
  fi
  if [ "$DRY_RUN" = "1" ]; then
    log "dry run: $svc hung ($n checks, pid ${pid:-?}, /health $says): would capture diagnostics and run start-local.sh restart $svc"
    return 0
  fi
  # shellcheck disable=SC2086
  dir=$(capture_hang "$svc" "${code:-000}" ${pids:-0})
  rel=${dir#$ROOT/}
  clear_hung "$svc"
  # the capture took seconds: the owner may have stopped or restarted it by hand meanwhile (Stop Stack in the app,
  # the boot page's "restart it now" line), and `restart` would clear a pause or race a manual restart (R-OPS-04)
  if [ -f "$ROOT/.pids/paused/$svc" ]; then
    log "$svc hang restart skipped: it was stopped by hand meanwhile (paused); diagnostics in $rel"
    return 0
  fi
  if start_local_running; then
    log "$svc hang restart skipped: a start-local.sh run is in progress (restarted or stopped by hand?); diagnostics in $rel"
    return 0
  fi
  now=$(listener_pids "$svc" | tr '\n' ' '); now=${now% }
  if [ "$now" != "$pids" ]; then
    log "$svc hang restart skipped: its listener changed (pid ${pids:-none} -> ${now:-none}), restarted or stopped by hand; diagnostics in $rel"
    return 0
  fi
  log "$svc hung ($n checks, pid ${pid:-?}, /health $says): diagnostics in $rel; restarting"
  note_hang_restart "$svc"
  # separate throttle keys: an earlier 'restarted' alert never silences a following 'restart FAILED' (R-OPS-03)
  if SURYADHANA_WATCHDOG=1 timeout 300 "$ROOT/start-local.sh" restart "$svc" >> "$LOG" 2>&1 && is_up "$svc"; then
    log "$svc restarted after a hang"
    throttled "hang-ok-$svc" 30 || tg "⚠️ SuryaDhana: $svc was hung (listening, /health $says): restarted.
Diagnostics: $rel"
  else
    log "$svc restart after a hang FAILED (see .logs/$svc.log)"
    throttled "hang-fail-$svc" 30 || tg "🔴 SuryaDhana: $svc was hung (listening, /health $says) and the restart FAILED.
Check .logs/$svc.log and $rel, then: ./start-local.sh restart $svc"
  fi
}

# foreign_listener <svc> — its port is held (alone or next to its uvicorn) by a program that is not its uvicorn:
# log, alert hourly, never stop anything (start-local.sh restart would kill every listener on the port)
foreign_listener() {
  local svc=$1 pids pid cmd
  pids=$(listener_pids "$svc" | tr '\n' ' ')
  # shellcheck disable=SC2086
  pid=$(first_foreign "$svc" $pids) || pid=${pids%% *}
  cmd=$(proc_cmd "$pid" | cut -c1-120)
  log "$svc does not answer /health and port $(svc_port "$svc") is held by another program (pid $pid: $cmd): left alone"
  throttled "foreign-$svc" 60 || tg "⚠️ SuryaDhana: $svc is not answering, and its port $(svc_port "$svc") is held by another program (pid $pid: $cmd), so the watchdog leaves it alone.
Free the port, then: ./start-local.sh start $svc"
}

candidates() {
  local out=""
  for svc in $CORE; do
    is_up "$svc" && continue
    [ -f "$ROOT/.pids/paused/$svc" ] && continue
    out="$out $svc"
  done
  echo "$out"
}

# ui-api up but no UI release to serve: the terminal shows 'UI build not found' and the app stays on its boot
# page while every health check is green, so this is the only alert for it (C2-reliability-ops-04). Log
# hourly, Telegram at most every 6 h. Never auto-build: publishing a UI release is a deliberate act.
check_ui_release() {
  [ -f "$ROOT/ui/dist/current/index.html" ] && return 0
  is_up ui-api || return 0
  throttled "uibuild" 60 || log "ui/dist/current has no UI release: the terminal at :8010 shows 'UI build not found' (./start-local.sh build-ui)"
  throttled "uibuild-tg" 360 || tg "⚠️ SuryaDhana: the terminal UI is missing (ui/dist/current has no release).
ui-api and its API are up, but the terminal cannot load: the browser shows 'UI build not found' and the app stays on its start screen.
Fix at the Mac: ./start-local.sh build-ui   (or go back to the previous build: ./start-local.sh build-ui --rollback)"
}

# Hourly size-based rotation of .logs/*.log (start-local.sh rotate_log; 20 MB, keeps .1-.3). Skipped while a
# start-local.sh run is in progress, so it never races a start that rotates the same service log.
rotate_logs() {
  start_local_running && return 0
  throttled "logrotate" 60 && return 0
  SURYADHANA_WATCHDOG=1 timeout 120 "$ROOT/start-local.sh" rotate-logs >> "$LOG" 2>&1 || log "log rotation failed"
}

# Off-machine dead-man switch (optional, RUNBOOK "Off-machine dead-man ping"): GET <url> when the stack is healthy,
# <url>/fail when not. The result (never the URL, which is a credential of sorts) goes to $STATE/deadman as
# "<epoch> ok|fail|error" for ./start-local.sh status and Telegram /status; error = curl or HTTP failure.
ping_deadman() {
  local url res target
  url=$(env_val HEALTHCHECK_PING_URL); url=${url%/}
  if [ -z "$url" ]; then rm -f "$STATE/deadman"; return 0; fi
  if [ "$1" = 1 ]; then target=$url; res=ok; else target="$url/fail"; res=fail; fi
  curl -fsS -m 10 --retry 1 -o /dev/null "$target" > /dev/null 2>&1 || res=error
  echo "$(date +%s) $res" > "$STATE/deadman"
}

# The second heartbeat (Terminal v2 PLAN 0.2 / R-DATA §9 #1): GET HEALTHCHECK_WATCHDOG_URL on every run, before the
# stack is looked at and before the TCC preflight can exit, so its only meaning is "this Mac is up and launchd still
# runs the watchdog". Optional like the first; unset → no request and no state file. Never the URL in any output.
ping_watchdog_alive() {
  local url res
  url=$(env_val HEALTHCHECK_WATCHDOG_URL); url=${url%/}
  if [ -z "$url" ]; then rm -f "$STATE/deadman_watchdog"; return 0; fi
  res=ok
  curl -fsS -m 10 --retry 1 -o /dev/null "$url" > /dev/null 2>&1 || res=error
  echo "$(date +%s) $res" > "$STATE/deadman_watchdog"
}

main() {   # (body kept at column 0: it is the former top-level code)
# single instance (see take_lock: a lock whose run is gone is taken over at once)
take_lock || exit 0
trap release_lock EXIT
ping_watchdog_alive                                    # the second heartbeat: "the Mac is up", whatever follows

down=$(candidates)
if [ -n "$down" ]; then
  sleep "$DEBOUNCE_S"                                  # a manual restart in flight finishes first
  start_local_running && { log "start-local.sh is running — deferring"; exit 0; }
  down=$(candidates)
fi
# A down service whose port still has listeners is HUNG when every listener is its own uvicorn (start-local.sh
# start would only say "already running"): handle_hung restarts it. A port held, alone or alongside, by another
# program is reported, never stopped. The rest are started as before. Healthy or paused: no hang count.
hung=""; dead=""; foreign=""
for svc in $down; do
  pids=$(listener_pids "$svc" | tr '\n' ' ')
  if [ -z "${pids// /}" ]; then dead="$dead $svc"
  # shellcheck disable=SC2086
  elif all_listeners_ours "$svc" $pids; then hung="$hung $svc"
  else foreign="$foreign $svc"; fi
done
for svc in $CORE; do
  case " $hung " in *" $svc "*) ;; *) clear_hung "$svc" ;; esac
done

# Preflight: can a launchd-spawned process even start the stack's Python? The env lives under ~/Desktop,
# which macOS privacy protection (TCC) guards: until "Python" is allowed Desktop-folder access, Python
# blocks on a consent prompt forever (found in the 19 Oct drill). Never hang — tell the owner what to click.
PY="${WATCHDOG_PYTHON:-/Users/sudheer/Desktop/jupyter_env/bin/python}"
if [ -n "$down" ] && ! timeout 15 "$PY" -c "pass" > /dev/null 2>&1; then
  log "preflight FAILED: python cannot start from launchd (macOS Desktop-folder permission) — down:$down"
  throttled "tcc" 180 || tg "🔒 SuryaDhana watchdog can't restart:$down
macOS is blocking the stack's Python (it lives in ~/Desktop) for background processes.
Fix once at the Mac: System Settings → Privacy & Security → Files and Folders → allow Python access to the Desktop folder (or click Allow on the waiting prompt). Until then, restart with: ./start-local.sh start"
  ping_deadman 0                                       # the stack is down and cannot be restarted: say so off-Mac too
  exit 0
fi

started=""; failed=""
for svc in $dead; do
  log "$svc is down — starting"
  if SURYADHANA_WATCHDOG=1 timeout 300 "$ROOT/start-local.sh" start "$svc" >> "$LOG" 2>&1 && is_up "$svc"; then
    started="$started $svc"; log "$svc started"
  else
    failed="$failed $svc"; log "$svc FAILED to start (see .logs/$svc.log)"
  fi
done

for svc in $hung; do
  handle_hung "$svc"
done
for svc in $foreign; do
  foreign_listener "$svc"
done

now_all_up=1
for svc in $CORE; do
  [ -f "$ROOT/.pids/paused/$svc" ] && continue
  is_up "$svc" || now_all_up=0
done

if [ -n "$started" ] || [ -n "$failed" ]; then
  last_ok="unknown"; [ -f "$STATE/last_all_up" ] && last_ok=$(cat "$STATE/last_all_up")
  boot=$(sysctl -n kern.boottime | sed 's/.*} //')
  msg="🔧 SuryaDhana watchdog: the stack was down."
  [ -n "$started" ] && msg="$msg
Restarted:$started"
  [ -n "$failed" ] && msg="$msg
FAILED to start:$failed (see .logs/<service>.log)"
  msg="$msg
Last seen healthy: $last_ok IST · Mac booted: $boot"
  if [ -n "$failed" ] && throttled "fail" 30; then log "failure alert throttled"; else tg "$msg"; fi
fi

if [ "$now_all_up" = 1 ]; then
  ts > "$STATE/last_all_up"
fi

check_ui_release
rotate_logs

# disk headroom: DuckDB writes and the nightly 4.4 GB backups fail on a full disk
free_gb=$(df -g "$ROOT" | awk 'NR==2 {print $4}')
if [ -n "$free_gb" ] && [ "$free_gb" -lt 20 ] && ! throttled "disk" 720; then
  tg "⚠️ SuryaDhana: only ${free_gb} GB free on the data disk. Nightly DuckDB backups (4.4 GB each) and ingests will start failing — prune data/backups or free space."
  log "low disk: ${free_gb} GB"
fi

ping_deadman "$now_all_up"
exit 0
}

# Run main only when executed (tests source this file for its functions); one line (see the header).
if [ "${BASH_SOURCE[0]}" = "$0" ]; then main; exit $?; fi
