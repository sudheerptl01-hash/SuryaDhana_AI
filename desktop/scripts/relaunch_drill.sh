#!/bin/bash
# Relaunch drill for SuryaDhana.app (AC-5 / AC-7 evidence) in an ISOLATED HOME.
#
#   desktop/scripts/relaunch_drill.sh --ui http://127.0.0.1:<port> [--app <SuryaDhana.app>]
#
# Normal (non-self-test) launches of the real app, with HOME pointed at a temp dir, so the owner's config,
# session, window geometry, logs and ~/Library/LaunchAgents are never read or written:
#   1. seeds state.json with two windows (main=desk, term-3=risk) -> launch -> both restored and loaded
#   2. first-run Launch at Login: the LaunchAgent plist appears in the TEMP HOME (never the real one), in the
#      app's own format (KeepAlive/SuccessfulExit=false, AssociatedBundleIdentifiers, ProcessType), and the
#      first-run marker file is written
#   3. single instance: a second launch exits on its own, the first keeps running
#   4. graceful quit (an Apple Event "quit" sent to THIS process only) saves state.json and the geometry
#   5. relaunch restores the same windows; the first-run enable does not run again, even after state.json is
#      deleted (the README's "reset window layout" recipe)
#   6. a crash (kill -9) is recorded as an unclean end on the next launch
#   7. a Launch-at-Login entry that points at a missing app is repaired on the next launch
#   W2 (wave 2): every Launch-at-Login change is reconciled with launchd at once (completeness-03) — recorded
#      by a fake `launchctl` INSIDE the temp HOME (SURYADHANA_LAUNCHCTL), so the real per-user launchd domain
#      (where the owner's SuryaDhana job lives) is never touched: first-run enable / repair = bootout +
#      bootstrap; an instance that IS the login job (XPC_SERVICE_NAME=SuryaDhana) defers instead of booting
#      itself out; a login-job second launch exits without stealing focus; an unclean end from before this
#      boot keeps the login start; `--version` and `--login-item-sync [--start]` run without a window
#   R3 (round 3, SECREL-06 / R-RUST-05): a copy opened by hand (not the login job's process) starts a crash guard;
#      after kill -9 the guard asks launchd (the recorder) to start the login job, after a clean quit it starts
#      nothing, and it never holds the single-instance lock
#   R4b (round 4b): the banner-sink heartbeat follows macOS's notification permission: a leftover
#      notify-sink.alive (seeded before the first launch, as after a crash) is removed while SuryaDhana's
#      notifications are off (the scheduler's own banner must stay on) and refreshed while they are allowed;
#      a clean quit removes it
#   8. no secrets in the app log; no drill process (app or crash guard) left
#
# Safe while the installed SuryaDhana is running: the drill's instances use a single-instance lock and a
# WebKit data store keyed on the temp HOME (the app logs both; checked below), it quits only the pids it
# launched (NSRunningApplication -terminate, never "tell application id"), and it refuses only when a
# SuryaDhana from the SAME app path is already running.
#
# DRILL_KEEP_LOG=<file> keeps a copy of the drill's app log (the temp HOME is deleted at the end).
#
# --ui must be a SCRATCH UI server (e.g. scripts/desktop_qa/scratch_server.py --block-mutations on 8090-8099),
# never the live ui-api: the windows load real pages. Preferably back it with desktop/scripts/stub_backend.py
# (scratch_server.py --backend http://127.0.0.1:<stub port>): the drill only needs pages to commit, and a
# stub keeps its ~10 launches (RSK and DESK pages each time) off the live ui-api. WebKit keeps website data under the REAL
# ~/Library/WebKit|Caches/ai.suryadhana.terminal (it ignores $HOME); the drill's private data store there is
# deleted afterwards, and the two folders only if the drill created them. Exit 0 = every step passed.
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
APP="$ROOT/desktop/src-tauri/target/release/bundle/macos/SuryaDhana.app"
UI=""
while [ $# -gt 0 ]; do
  case "$1" in
    --app) shift; APP="${1:?--app needs a path}" ;;
    --ui) shift; UI="${1:?--ui needs a URL}" ;;
    -h|--help) awk 'NR > 1 && /^#/ { sub(/^# ?/, ""); print; next } NR > 1 { exit }' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
[ -n "$UI" ] || { echo "--ui http://127.0.0.1:<scratch port> is required" >&2; exit 2; }
case "$UI" in
  http://127.0.0.1:8010*|http://localhost:8010*) echo "refusing the live ui-api ($UI); use a scratch server" >&2; exit 2 ;;
  http://127.0.0.1:*|http://localhost:*) ;;
  *) echo "--ui must be http://127.0.0.1:<port>" >&2; exit 2 ;;
esac
APP="$(cd "$APP" 2> /dev/null && pwd -P)" || { echo "no app at the given path" >&2; exit 2; }
EXE="$APP/Contents/MacOS/$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$APP/Contents/Info.plist" 2> /dev/null)"
[ -x "$EXE" ] || { echo "no app executable under $APP" >&2; exit 2; }
curl -fsS -m 5 -o /dev/null "$UI/" || { echo "scratch UI not answering at $UI" >&2; exit 2; }
mine_running() { pgrep -f -- "^$EXE" > /dev/null 2>&1; }
if mine_running; then echo "a SuryaDhana from $APP is running; quit it first" >&2; exit 2; fi

REAL_HOME="$HOME"
WK_DIRS=("$REAL_HOME/Library/WebKit/ai.suryadhana.terminal" "$REAL_HOME/Library/Caches/ai.suryadhana.terminal")
WK_PRE=()
for d in "${WK_DIRS[@]}"; do [ -e "$d" ] && WK_PRE+=("$d"); done
H="$(mktemp -d "${TMPDIR:-/tmp}/suryadhana-drill.XXXXXX")"
H="$(cd "$H" && pwd -P)"
CFG="$H/Library/Application Support/ai.suryadhana.terminal"
LOG="$H/Library/Logs/ai.suryadhana.terminal/suryadhana.log"
PL="$H/Library/LaunchAgents/SuryaDhana.plist"
mkdir -p "$CFG"
FAILS=0
PIDS=()
pass() { printf '\033[32mPASS\033[0m %s\n' "$*"; }
fail() { printf '\033[31mFAIL\033[0m %s\n' "$*"; FAILS=$((FAILS + 1)); }
store_uuid() { grep -oE "private WebKit data store [0-9A-F-]{36}" "$LOG" 2> /dev/null | tail -1 | awk '{print $NF}'; }
# the recording launchctl (lives inside the temp HOME: the app refuses any other for a non-account HOME)
mkdir -p "$H/bin"
CALLS="$H/launchctl.calls"
cat > "$H/bin/launchctl" << R
#!/bin/sh
echo "\$*" >> "$CALLS"
case "\$1" in bootout) echo "Boot-out failed: 3: No such process" >&2; exit 3;; esac
exit 0
R
chmod 755 "$H/bin/launchctl"
calls() { cat "$CALLS" 2> /dev/null; }
guards() { pgrep -f -- "suryadhana-crash-guard [0-9]+ $H/" 2> /dev/null; }
cleanup() {
  [ -n "${DRILL_KEEP_LOG:-}" ] && [ -f "$LOG" ] && cp "$LOG" "$DRILL_KEEP_LOG"
  for p in "${PIDS[@]:-}"; do [ -n "$p" ] && kill -0 "$p" 2> /dev/null && { kill "$p"; sleep 1; kill -9 "$p" 2> /dev/null; }; done
  for g in $(guards); do kill "$g" 2> /dev/null; done
  local u; u="$(store_uuid)"
  if [ -n "$u" ]; then
    for base in "$REAL_HOME/Library/WebKit/ai.suryadhana.terminal" "$REAL_HOME/Library/Caches/ai.suryadhana.terminal"; do
      find "$base" -maxdepth 3 -type d -iname "$u" -prune -exec rm -rf {} + 2> /dev/null
    done
  fi
  for d in "${WK_DIRS[@]}"; do
    local pre=0; for x in "${WK_PRE[@]:-}"; do [ "$x" = "$d" ] && pre=1; done
    [ "$pre" = 0 ] && rm -rf "$d"
  done
  rm -rf "$H"
}
trap cleanup EXIT
log_since() { tail -n +"$(( $1 + 1 ))" "$LOG" 2> /dev/null; }
wait_log() { # <from-line> <regex> <timeout s>
  local i; for i in $(seq 1 $(( $3 * 4 ))); do log_since "$1" | grep -qE "$2" && return 0; sleep 0.25; done; return 1
}
launch() { HOME="$H" SURYADHANA_UI_URL="$UI" SURYADHANA_LAUNCHCTL="$H/bin/launchctl" "$EXE" "$@" > /dev/null 2>&1 & PIDS+=($!); LAST=$!; }
# graceful quit of ONE pid: the standard Apple Event "quit" (NSRunningApplication -terminate, i.e. ⌘Q's path);
# then SIGTERM, which the app also handles as Quit (saves the session, exits 0); SIGKILL last.
# Returns 0 = Apple Event, 2 = SIGTERM (graceful), 1 = had to SIGKILL.
quit_app() {
  HOME="$REAL_HOME" timeout 20 osascript -l JavaScript -e "ObjC.import('AppKit'); var a = \$.NSRunningApplication.runningApplicationWithProcessIdentifier($1); (a && !a.isNil()) ? String(typeof a.terminate === 'function' ? a.terminate() : a.terminate) : 'gone'" > /dev/null 2>&1
  local i; for i in $(seq 1 40); do kill -0 "$1" 2> /dev/null || return 0; sleep 0.25; done
  kill -TERM "$1" 2> /dev/null
  for i in $(seq 1 40); do kill -0 "$1" 2> /dev/null || return 2; sleep 0.25; done
  kill -9 "$1" 2> /dev/null; return 1
}
origin="${UI%/}"
cat > "$CFG/state.json" << J
{"version":1,"windows":[{"label":"main","url":"$origin/?tab=desk"},{"label":"term-3","url":"$origin/?tab=risk"}]}
J
# R4b: a heartbeat left by an earlier run that crashed (the scheduler would skip its own banner for 3 min)
SINK="$CFG/notify-sink.alive"
echo '{"pid":1,"at":"left by a crashed run"}' > "$SINK"
touch -t "$(date -v-30S +%Y%m%d%H%M.%S)" "$SINK"
SINK_T0="$(stat -f %m "$SINK")"

echo "== 1-2. launch with a seeded session (temp HOME $H)"
launch; A=$LAST
# "committed" = the terminal page is rendered (with the screen locked WebKit may never fire "finished")
if wait_log 0 "term-3: terminal (committed|loaded)" 20 && wait_log 0 "main: terminal (committed|loaded)" 5; then pass "restored main + term-3 and both opened the terminal"; else fail "restore: $(grep -E 'restored|committed|loaded|opening' "$LOG" | tail -4)"; fi
grep -q "restored 2 window" "$LOG" && pass "log: restored 2 window(s)" || fail "log has no 'restored 2 window(s)'"
if [ -f "$PL" ] && [ "$(plutil -extract ProgramArguments.0 raw -o - "$PL")" = "$EXE" ]; then
  pass "first-run Launch at Login plist written in the temp HOME -> this app"
else fail "no/odd LaunchAgent plist in the temp HOME"; fi
if plutil -lint "$PL" > /dev/null 2>&1 && [ "$(plutil -extract KeepAlive.SuccessfulExit raw -o - "$PL" 2> /dev/null)" = "false" ] \
   && [ "$(plutil -extract AssociatedBundleIdentifiers.0 raw -o - "$PL" 2> /dev/null)" = "ai.suryadhana.terminal" ] \
   && [ "$(plutil -extract ProcessType raw -o - "$PL" 2> /dev/null)" = "Interactive" ]; then
  pass "plist: KeepAlive/SuccessfulExit=false (relaunch after a crash, not after Quit), bundle id, Interactive"
else fail "plist format: $(tr -d '\n' < "$PL" 2> /dev/null | head -c 300)"; fi
[ -f "$CFG/.autostart-initialized" ] && pass "first-run marker file written" || fail "no .autostart-initialized marker"
UIDN="$(id -u)"
if wait_log 0 "first-run Launch at Login: launchd now matches" 5 && calls | grep -qx "bootout gui/$UIDN/SuryaDhana" \
   && calls | grep -qx "bootstrap gui/$UIDN $PL"; then
  pass "W2 first-run enable reconciled launchd at once: bootout + bootstrap of the app's own job (recorded, not the real launchd)"
else fail "W2 launchd reconcile after first-run enable: calls=[$(calls | tr '\n' '|')] log=$(grep -E '\[autostart\]' "$LOG" | tail -3)"; fi
calls | grep -qvE "SuryaDhana($| )|^bootstrap gui/$UIDN $PL$" && fail "W2 a launchctl call named another job: $(calls)" || pass "W2 only the app's own label was ever named"
ls "$REAL_HOME/Library/LaunchAgents/" | grep -qE "^SuryaDhana\.plist$" && echo "note: the REAL ~/Library/LaunchAgents/SuryaDhana.plist exists (not written by this drill)"
lock="$(grep -oE "single-instance lock [^ ]+" "$LOG" | tail -1 | awk '{print $NF}')"
if [ -n "$lock" ] && [ "$lock" != "/tmp/ai_suryadhana_terminal_si.sock" ]; then pass "isolated single-instance lock ($lock), not the owner's"; else fail "single-instance lock: '$lock'"; fi
[ -n "$(store_uuid)" ] && pass "private WebKit data store $(store_uuid) for the temp HOME" || fail "no private WebKit data store logged"

echo "== R4b. banner-sink heartbeat vs macOS notification permission"
# the shell reads the permission 1 s after start and polls the feed every 15 s (the stub serves the feed)
if wait_log 0 "\[notify\] (macOS has notifications OFF|notification permission: )" 10 && wait_log 0 "\[feed\] following" 25; then
  sleep 1
  perm="$(grep -oE "notifications OFF|notification permission: [a-z]+" "$LOG" | tail -1)"
  case "$perm" in
    "notifications OFF"|"notification permission: default")
      [ ! -e "$SINK" ] && pass "R4b notifications not allowed ($perm): the leftover heartbeat was removed (the scheduler keeps its own banner)" \
        || fail "R4b notifications not allowed ($perm) but notify-sink.alive is still there"
      grep -qE "opening System Settings" "$LOG" \
        && fail "R4b System Settings was opened without a click" || pass "R4b System Settings never opened by itself" ;;
    "notification permission: granted")
      for i in $(seq 1 80); do [ -e "$SINK" ] && [ "$(stat -f %m "$SINK")" -gt "$SINK_T0" ] && break; sleep 0.25; done
      [ -e "$SINK" ] && [ "$(stat -f %m "$SINK")" -gt "$SINK_T0" ] && pass "R4b notifications allowed: the heartbeat is refreshed" \
        || fail "R4b notifications allowed but notify-sink.alive was not refreshed" ;;
    *) fail "R4b could not tell the notification permission from the log: '$perm'" ;;
  esac
else fail "R4b no permission / feed lines: $(grep -E '\[notify\]|\[feed\]' "$LOG" | tail -3)"; fi

echo "== 3. single instance"
L=$(wc -l < "$LOG")
launch; B=$LAST
for i in $(seq 1 40); do kill -0 "$B" 2> /dev/null || break; sleep 0.25; done
if kill -0 "$B" 2> /dev/null; then fail "second instance still running"; kill -9 "$B"; else pass "second instance exited after ~$((i * 250)) ms"; fi
kill -0 "$A" 2> /dev/null && pass "first instance still running" || fail "first instance died"
wait_log "$L" "second launch" 3 && pass "first instance logged the second launch (focus)" || fail "no second-launch log line"
# W2: the login job's RunAtLoad start after a reload finds the app running: it exits without stealing focus
L=$(wc -l < "$LOG")
launch --autostart; B2=$LAST
for i in $(seq 1 40); do kill -0 "$B2" 2> /dev/null || break; sleep 0.25; done
kill -0 "$B2" 2> /dev/null && { fail "W2 login-job second copy still running"; kill -9 "$B2"; } || pass "W2 login-job second copy exited after ~$((i * 250)) ms"
if wait_log "$L" "login job started a second copy" 3 && ! log_since "$L" | grep -q "second launch -> focusing"; then
  pass "W2 the running instance kept its focus (logged the login-job copy, no focus change)"
else fail "W2 login-job second copy: $(log_since "$L" | grep -E 'second|login job' | tail -2)"; fi

echo "== 4. graceful quit saves the session"
quit_app "$A"; q=$?
case $q in
  0) pass "quit via Apple Event (this pid only)" ;;
  2) pass "graceful quit via SIGTERM (handled as Quit; the Apple Event was not delivered to this pid)" ;;
  *) fail "neither the Apple Event nor SIGTERM quit it (SIGKILL used)" ;;
esac
grep -q '"term-3"' "$CFG/state.json" && grep -q 'tab=risk' "$CFG/state.json" \
  && pass "state.json: main + term-3 (tab=risk)" || fail "state.json after quit: $(tr -d '\n' < "$CFG/state.json")"
grep -q '"term-3"' "$CFG/.window-state.json" 2> /dev/null && pass ".window-state.json has per-label geometry" || fail "no geometry for term-3"
[ -f "$CFG/run.json" ] && fail "run.json left behind after a clean quit" || pass "clean exit removed the run marker"

[ ! -e "$SINK" ] && pass "R4b after a clean quit there is no banner-sink heartbeat" || fail "R4b notify-sink.alive left after a clean quit"

echo "== 5. relaunch restores; the first-run enable never runs again"
L=$(wc -l < "$LOG")
launch; C=$LAST
if wait_log "$L" "term-3: terminal (committed|loaded)" 20; then pass "relaunch restored term-3"; else fail "relaunch: term-3 not restored"; fi
log_since "$L" | grep -q "enabled on first run" && fail "first-run enable ran again" || pass "first-run enable did not run again"
quit_app "$C" > /dev/null
rm -f "$PL" "$CFG/state.json"   # the owner switched Launch at Login off, then reset the window layout
L=$(wc -l < "$LOG")
launch; C2=$LAST
wait_log "$L" "main: terminal (committed|loaded)" 20 > /dev/null
[ -f "$PL" ] && fail "Launch at Login turned itself back on after state.json was deleted" || pass "Launch at Login stays off after the layout reset"

echo "== 6. a crash is recorded"
kill -9 "$C2"; sleep 0.5
L=$(wc -l < "$LOG")
launch; D=$LAST
if wait_log "$L" "previous run ended without a clean exit" 10; then pass "unclean end recorded on the next launch"; else fail "no unclean-exit line after kill -9"; fi
quit_app "$D" > /dev/null

echo "== 6b. W2: an unclean end from BEFORE this boot (power cut) keeps the login start"
cat > "$CFG/run.json" << M
{"pid":0,"started":1000}
M
L=$(wc -l < "$LOG")
launch --autostart; P0=$LAST
if wait_log "$L" "ended with the previous boot" 10 && wait_log "$L" "login start" 5 \
   && ! log_since "$L" | grep -q "previous run ended without a clean exit"; then
  pass "W2 power-cut marker: not a crash, the login start keeps its grace"
else fail "W2 previous-boot marker: $(log_since "$L" | grep -E '\[app\]' | head -4)"; fi
quit_app "$P0" > /dev/null

# an entry left by an older install that pointed at an app which no longer exists (plugin-era format)
cat > "$PL" << P
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict><key>Label</key><string>SuryaDhana</string><key>ProgramArguments</key><array><string>/nonexistent/Old.app/Contents/MacOS/SuryaDhana</string><string>--autostart</string></array><key>RunAtLoad</key><true/></dict></plist>
P

# W2: the same stale entry, but this instance IS the login job (launchd sets XPC_SERVICE_NAME): the entry is
# repaired, launchd is NOT reloaded (that would quit the app), the change waits for the next login
: > "$CALLS"
L=$(wc -l < "$LOG")
HOME="$H" SURYADHANA_UI_URL="$UI" SURYADHANA_LAUNCHCTL="$H/bin/launchctl" XPC_SERVICE_NAME=SuryaDhana "$EXE" --autostart > /dev/null 2>&1 &
PIDS+=($!); E0=$!
if wait_log "$L" "pointed at a missing app" 15 && wait_log "$L" "runs under the login job" 5 && [ -z "$(calls)" ]; then
  pass "W2 under the login job: entry repaired, no bootout of its own job (deferred to the next login)"
else fail "W2 under-job defer: calls=[$(calls | tr '\n' '|')] $(log_since "$L" | grep -E '\[autostart\]' | tail -2)"; fi
quit_app "$E0" > /dev/null
cat > "$PL" << P
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0"><dict><key>Label</key><string>SuryaDhana</string><key>ProgramArguments</key><array><string>/nonexistent/Old.app/Contents/MacOS/SuryaDhana</string><string>--autostart</string></array><key>RunAtLoad</key><true/></dict></plist>
P

echo "== 7. stale Launch-at-Login path is repaired (and upgraded)"
: > "$CALLS"
L=$(wc -l < "$LOG")
launch; E=$LAST
if wait_log "$L" "pointed at a missing app" 15; then pass "repaired: $(plutil -extract ProgramArguments.0 raw -o - "$PL")"; else fail "stale plist not repaired"; fi
[ "$(plutil -extract KeepAlive.SuccessfulExit raw -o - "$PL" 2> /dev/null)" = "false" ] && pass "repaired entry has KeepAlive" || fail "repaired entry lacks KeepAlive"
if wait_log "$L" "repointed: launchd now matches" 5 && [ "$(calls | wc -l | tr -d ' ')" = 2 ]; then
  pass "W2 repair reloaded the job in launchd now (bootout + bootstrap)"
else fail "W2 repair reconcile: calls=[$(calls | tr '\n' '|')]"; fi
quit_app "$E" > /dev/null

echo "== 7c. R3: a copy opened by hand is relaunched after a crash (crash guard)"
guard_of() { log_since "$1" | grep -oE "crash guard pid [0-9]+" | tail -1 | awk '{print $NF}'; }
: > "$CALLS"
L=$(wc -l < "$LOG")
launch; G=$LAST
if wait_log "$L" "crash guard pid [0-9]+" 15; then pass "R3 a copy opened by hand (Launch at Login on, not the job's process) starts a crash guard (pid $(guard_of "$L"))"
else fail "R3 no crash guard: $(log_since "$L" | grep -E 'crash relaunch' | tail -2)"; fi
GP="$(guard_of "$L")"
wait_log "$L" "main: terminal (committed|loaded)" 20 > /dev/null
kill -9 "$G"; sleep 0.3
for i in $(seq 1 100); do calls | grep -qx "kickstart gui/$UIDN/SuryaDhana" && break; sleep 0.25; done
if calls | grep -qx "kickstart gui/$UIDN/SuryaDhana"; then
  pass "R3 after kill -9 the guard asked launchd to start the login job within ~$((i / 4)) s (kickstart gui/$UIDN/SuryaDhana, recorded)"
else fail "R3 no relaunch request after kill -9: calls=[$(calls | tr '\n' '|')]"; fi
for i in $(seq 1 20); do [ -n "$GP" ] && kill -0 "$GP" 2> /dev/null || break; sleep 0.25; done
[ -n "$GP" ] && kill -0 "$GP" 2> /dev/null && fail "R3 the crash guard is still running after it acted" || pass "R3 the crash guard ended after it acted"
L=$(wc -l < "$LOG")
launch; G3=$LAST
if wait_log "$L" "main: terminal (committed|loaded)" 20 && kill -0 "$G3" 2> /dev/null; then
  pass "R3 the next launch runs as the primary (the guard never held the single-instance lock)"
else fail "R3 the launch after the crash did not come up: $(log_since "$L" | tail -3)"; fi
GP3="$(guard_of "$L")"
: > "$CALLS"
quit_app "$G3" > /dev/null
for i in $(seq 1 90); do [ -n "$GP3" ] && kill -0 "$GP3" 2> /dev/null || break; sleep 0.25; done
if [ -n "$GP3" ] && ! kill -0 "$GP3" 2> /dev/null && ! calls | grep -q kickstart; then
  pass "R3 after a clean quit the guard ended within ~$((i / 4)) s and started nothing"
else fail "R3 clean quit: guard ${GP3:-none} alive=$(kill -0 "${GP3:-0}" 2> /dev/null && echo yes || echo no) calls=[$(calls | tr '\n' '|')]"; fi

echo "== 7b. W2: command-line modes (no window)"
t0=$(date +%s)
v="$(HOME="$H" "$EXE" --version 2>&1)"
if echo "$v" | grep -qE '^SuryaDhana [0-9.]+ \([0-9a-f]{7}(-dirty)?-[0-9a-f]{8}-[0-9]{8}T[0-9]{4}Z\)$' && [ $(( $(date +%s) - t0 )) -le 3 ]; then
  pass "W2 --version: $v"
else fail "W2 --version: '$v'"; fi
: > "$CALLS"
out="$(HOME="$H" SURYADHANA_LAUNCHCTL="$H/bin/launchctl" "$EXE" --login-item-sync 2>&1)"; rc=$?
if [ $rc = 0 ] && [ "$(plutil -extract ProgramArguments.0 raw -o - "$PL")" = "$EXE" ] && [ "$(calls)" = "bootout gui/$UIDN/SuryaDhana" ]; then
  pass "W2 --login-item-sync: entry rewritten for this copy, stale job unloaded"
else fail "W2 --login-item-sync (rc $rc): $out | calls=[$(calls | tr '\n' '|')]"; fi
: > "$CALLS"
HOME="$H" SURYADHANA_LAUNCHCTL="$H/bin/launchctl" "$EXE" --login-item-sync --start > /dev/null 2>&1
[ "$(calls | tr '\n' '|')" = "bootout gui/$UIDN/SuryaDhana|bootstrap gui/$UIDN $PL|" ] && pass "W2 --login-item-sync --start: bootout + bootstrap" || fail "W2 --start calls=[$(calls | tr '\n' '|')]"
out="$(HOME="$H" "$EXE" --login-item-sync 2>&1)"
echo "$out" | grep -q "launchd not touched" && pass "W2 without its recorder a temp HOME never reaches launchd" || fail "W2 no-recorder sync: $out"
L=$(wc -l < "$LOG")
launch; F=$LAST
wait_log "$L" "main: terminal (committed|loaded)" 20 > /dev/null
: > "$CALLS"
HOME="$H" SURYADHANA_LAUNCHCTL="$H/bin/launchctl" "$EXE" --login-item-sync --start > /dev/null 2>&1; rc=$?
[ $rc = 2 ] && [ -z "$(calls)" ] && kill -0 "$F" 2> /dev/null \
  && pass "W2 --login-item-sync refuses while the app runs from this HOME (it would be booted out)" \
  || fail "W2 sync under a running app: rc $rc calls=[$(calls | tr '\n' '|')]"
quit_app "$F" > /dev/null
mine_running && fail "a CLI mode left an app process behind" || pass "W2 CLI modes opened no app"

echo "== 8. hygiene"
n=$(grep -ciE "login_url|api_key|apikey|session_token|secret" "$LOG")
[ "$n" = 0 ] && pass "no secret-like strings in the app log" || fail "$n secret-like lines in the log"
grep -q "\[panic\]" "$LOG" && fail "a panic was logged: $(grep '\[panic\]' "$LOG" | head -2)" || pass "no panic logged"
sleep 0.5
mine_running && fail "a drill SuryaDhana process is still running" || pass "no drill SuryaDhana process left"
# a guard notices a clean quit within one 15 s check
for i in $(seq 1 80); do [ -z "$(guards)" ] && break; sleep 0.25; done
[ -n "$(guards)" ] && fail "R3 a crash guard of the drill is still running 20 s after the last quit: $(guards | tr '\n' ' ')" || pass "R3 no crash guard left (every guard ended by itself)"
echo "== $([ "$FAILS" = 0 ] && echo PASSED || echo "FAILED ($FAILS)")"
exit $([ "$FAILS" = 0 ] && echo 0 || echo 1)
