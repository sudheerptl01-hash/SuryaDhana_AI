#!/bin/bash
# SuryaDhana AI — Local Development Startup (No Docker)
# Usage: ./start-local.sh [start|stop|restart|status|logs|help] [service]
#
# Runs the local stack. Core (3 processes): data-service, ui-api (it also serves the terminal UI on :8010
# from the static release ui/dist/current, built by scripts/build_ui.sh), master-controller.
# Optional: frontend (the Next dev server on :3000 with hot reload, or UI_MODE=prod for the old Next prod
# build) and the dormant legacy ml/feature/rl services.
# Requires: Python environment at /Users/sudheer/Desktop/jupyter_env. Node/npm only for the optional frontend
# and for build-ui: starting or restarting the Python services never needs Node.
#
# Editing this file: it is executed by the watchdog every 2 minutes and bash reads a running script
# incrementally, so never rewrite it in place. Write a temp file next to it and rename it over this one
# (os.replace / mv), which gives a running instance its old inode (desktop review C2-reliability-ops-01).

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="/Users/sudheer/Desktop/jupyter_env/bin/python"
VENV_PIP="/Users/sudheer/Desktop/jupyter_env/bin/pip"
# scripts/stack_watchdog.sh sets SURYADHANA_WATCHDOG=1 when it runs this script. Read once and dropped, so it never
# reaches the services' environment. Only a start/restart by HAND clears the watchdog's hourly hang-restart cap.
CALLED_BY_WATCHDOG="${SURYADHANA_WATCHDOG:-0}"
unset SURYADHANA_WATCHDOG

# ── Restart freeze windows (CLAUDE.md), enforced rather than merely documented (F6-07, 14 Nov 2026) ──────────
# data-service and master-controller are never restarted 07:45-09:20 IST (the 08:00 ICICI login and the pre-open
# jobs) or 18:30-21:15 (the EOD pipeline, desk, shadow, wrap). ui-api has no window. Until now this lived only in
# documents and in the watchdog's own in_freeze(); a human (or an agent) running `restart data-service` at 09:00
# was stopped by nothing, and on 14 Nov that is exactly what happened -- benign only because it was a Saturday.
# FREEZE_OVERRIDE=1 is the deliberate escape hatch: it still prints what it is overriding, so the decision is on
# the record instead of invisible.
FREEZE_SERVICES="data-service master-controller"

in_freeze_window() {   # in_freeze_window <service> -> 0 when a restart of it is forbidden right now
  case " $FREEZE_SERVICES " in *" $1 "*) ;; *) return 1 ;; esac
  local hm; hm=$((10#$(TZ=Asia/Kolkata date "+%H%M")))
  { [ "$hm" -ge 745 ] && [ "$hm" -le 920 ]; } || { [ "$hm" -ge 1830 ] && [ "$hm" -le 2115 ]; }
}

refuse_in_freeze_set() {   # refuse_in_freeze_set <action> "<svc> <svc> …" — guards each frozen service in the set
  local action=$1 svc
  for svc in $2; do
    refuse_in_freeze "$action" "$svc"
  done
}

refuse_in_freeze() {   # refuse_in_freeze <action> <service>  -> exits 3 unless overridden or run by the watchdog
  local action=$1 svc=$2 now; now=$(TZ=Asia/Kolkata date "+%H:%M")
  in_freeze_window "$svc" || return 0
  # the watchdog has its own freeze logic (and its own alert-and-wait path), so it is never second-guessed here
  [ "$CALLED_BY_WATCHDOG" = "1" ] && return 0
  if [ "${FREEZE_OVERRIDE:-0}" = "1" ]; then
    echo "⚠️  FREEZE_OVERRIDE=1: ${action}ing $svc at $now IST, inside a freeze window (07:45-09:20 / 18:30-21:15)."
    echo "    Overriding on purpose — if a login or the EOD pipeline is running, this can break it."
    return 0
  fi
  echo "⛔ Refusing to $action $svc at $now IST: that is inside a restart freeze window."
  echo "   07:45-09:20 is the ICICI login + pre-open jobs; 18:30-21:15 is the EOD pipeline, desk, shadow and wrap."
  echo "   Wait for the window to close, or — having checked that nothing is due — re-run with FREEZE_OVERRIDE=1."
  exit 3
}

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color
# Plain text when the output is not a terminal (the watchdog appends it to .logs/watchdog.log) or NO_COLOR is
# set. HW = printf width of a coloured status cell: the HEALTH column's 10 visible characters + 11 escape bytes.
HW=21
if [ ! -t 1 ] || [ -n "${NO_COLOR:-}" ]; then RED=''; GREEN=''; YELLOW=''; BLUE=''; NC=''; HW=10; fi

print_header() {
  echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
  echo -e "${BLUE}$1${NC}"
  echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"
}

print_success() {
  echo -e "${GREEN}✓${NC} $1"
}

print_error() {
  echo -e "${RED}✗${NC} $1"
}

print_info() {
  echo -e "${BLUE}ℹ${NC} $1"
}

# ─────────────────────────────────────────────────────────────────────────────

# needs_node "<services>" — true when the set includes the Next frontend, the only service that runs on Node.
# The watchdog restarts data-service/ui-api/master-controller through `start <svc>`: a missing or half-
# reinstalled Node must never block those (desktop review C2-reliability-ops-10).
needs_node() { case " $1 " in *" frontend "*) return 0 ;; *) return 1 ;; esac; }

# check_prerequisites "<services about to start>"
check_prerequisites() {
  print_header "Checking Prerequisites"

  # Check Python
  if [ ! -x "$PYTHON_BIN" ]; then
    print_error "Python environment not found at $PYTHON_BIN"
    exit 1
  fi
  print_success "Python environment found"

  # Check Node/npm (frontend only; build-ui checks node itself)
  if needs_node "${1:-}"; then
    if ! command -v npm &> /dev/null; then
      print_error "npm is not installed. Please install Node.js (needed for the frontend)."
      exit 1
    fi
    print_success "npm is installed"
  fi

  # Check .env
  if [ ! -f "$PROJECT_ROOT/.env" ]; then
    print_error ".env file not found. Please copy .env.example to .env and configure."
    exit 1
  fi
  print_success ".env file exists"
}

# ─────────────────────────────────────────────────────────────────────────────

# install_deps "<services about to start>"
install_deps() {
  print_header "Checking Dependencies"

  # jupyter_env is SHARED with other projects. Never `pip install -r` a service's
  # pinned requirements into it here — the Docker-oriented pins (uvicorn 0.24,
  # starlette 0.27, pandas 2.2.3, ...) silently downgrade packages other tools need.
  # Only verify imports; install missing packages manually and deliberately.
  print_info "Verifying Python packages (read-only)..."
  if ! $PYTHON_BIN - <<'PYEOF'
import importlib, sys
mods = ["fastapi", "uvicorn", "httpx", "duckdb", "pandas", "numpy", "pyarrow",
        "xgboost", "sklearn", "breeze_connect", "redis", "dotenv", "pytz", "psutil",
        "structlog", "pydantic_settings", "yfinance", "apscheduler"]
missing = []
for m in mods:
    try:
        importlib.import_module(m)
    except Exception as exc:
        missing.append(f"{m} ({type(exc).__name__})")
if missing:
    print("missing/broken: " + ", ".join(missing))
    sys.exit(1)
PYEOF
  then
    print_error "Some Python packages are missing or broken (listed above)."
    print_info "Install them individually with: $VENV_PIP install <package>"
    exit 1
  fi
  print_success "Python packages OK"

  # Frontend dependencies (frontend only)
  if needs_node "${1:-}"; then
    print_info "Installing frontend dependencies..."
    cd "$PROJECT_ROOT/ui"
    if [ ! -d "node_modules" ]; then
      npm install --legacy-peer-deps --silent
    fi
    print_success "Frontend dependencies installed"
  fi

  print_success "All dependencies ready"
}

# ─────────────────────────────────────────────────────────────────────────────

# Stop whatever listens on the given ports: SIGTERM first so uvicorn runs its
# shutdown hooks (data-service CHECKPOINTs DuckDB and releases the file lock),
# SIGKILL only for processes still alive after the grace period.
graceful_stop_ports() {
  local pids
  pids=$(lsof -ti:"$1" 2>/dev/null | sort -u)
  [ -z "$pids" ] && return 0
  kill -TERM $pids 2>/dev/null || true
  for _ in $(seq 1 20); do
    sleep 1
    pids=$(lsof -ti:"$1" 2>/dev/null | sort -u)
    [ -z "$pids" ] && return 0
  done
  print_info "Force-stopping unresponsive processes on $1"
  kill -9 $pids 2>/dev/null || true
}

# ─────────────────────────────────────────────────────────────────────────────

# Local (non-Docker) service URLs. Services otherwise fall back to Docker DNS names
# (http://data-service:8001, ...) which do not resolve outside compose.
export DATA_SERVICE_URL="http://localhost:8001"
# DuckDB memory cap for the NATIVE local stack. The code default (1.5GB, duckdb_store._apply_pragmas)
# was sized for the old 2GB Docker container; on this 26GB Mac it OOM'd the nightly ML-dataset
# upsert on 15 Oct 2026. Override in the shell or .env if needed.
export DUCKDB_MEMORY_LIMIT="${DUCKDB_MEMORY_LIMIT:-4GB}"
export ML_SERVICE_URL="http://localhost:8003"
export FEATURE_SERVICE_URL="http://localhost:8002"
export RL_SERVICE_URL="http://localhost:8004"
export EXECUTION_SERVICE_URL="http://localhost:8006"
export MASTER_CONTROLLER_URL="http://localhost:8008"
export UI_API_URL="http://localhost:8010"
export PYTHON_BIN

# Every service, ui-api included, listens on 127.0.0.1 only. The terminal has no login, so it is never opened
# to the LAN, and a single-interface bind would also break every loopback consumer (the app, the watchdog, the
# jobs). The UI_API_HOST opt-in was removed (desktop review C2-security-02/-12, C2-reliability-ops-07,
# C3-logic-unchanged-04, 25 Oct 2026). Phone/iPad access: Tailscale Serve (tailnet-authenticated HTTPS in
# front of 127.0.0.1:8010), see docs/RUNBOOK_RESTORE.md §7.
env_file_val() { grep -E "^$1=" "$PROJECT_ROOT/.env" 2> /dev/null | tail -1 | cut -d= -f2- | tr -d "\"'" ; }
case "${UI_API_HOST:-$(env_file_val UI_API_HOST)}" in
  ""|127.0.0.1) ;;
  *) echo "start-local.sh: UI_API_HOST is no longer supported and is ignored: ui-api binds 127.0.0.1 only" \
          "(phone/iPad: Tailscale Serve, docs/RUNBOOK_RESTORE.md §7)" >&2 ;;
esac

# master-controller locally: data jobs (08:30 refresh, 18:30 Mon-Fri refresh + ML
# rebuild) run on schedule; TRADING jobs (15-min inference, 15:15 square-off, 23:00
# RL retrain) stay OFF until autopilot is enabled explicitly (UI or POST /api/scheduler/autopilot).
export AUTOPILOT_DEFAULT="off"

ALL_PORTS="8001,8002,8003,8004,8008,8010,3000"

# ── Service logs (.logs/<svc>.log) ────────────────────────────────────────────
# A (re)start APPENDS to the service log after a '=== … starting' banner, so the output of the instance that
# crashed (the traceback the watchdog's alert points at) survives the restart. Logs are rotated by size:
# over LOG_MAX_BYTES (default 20 MB) <log> becomes <log>.1, older generations shift up to <log>.LOG_KEEP
# (default 3) and the oldest is dropped. Rotation runs before every start and hourly from the watchdog
# (`rotate-logs`), so a long-running service is capped too (desktop review C2-reliability-ops-05).
LOG_MAX_BYTES="${LOG_MAX_BYTES:-20971520}"
LOG_KEEP="${LOG_KEEP:-3}"

# log_writers <file> → "ok <writers> <writers without O_APPEND>" over every process that has <file> open for
# writing, or "error <why>" when that cannot be known. Fails CLOSED: lsof exits 1 both for "nobody has it open"
# and for its own errors, so only exit 1 with no output at all counts as "no writers"; a missing lsof, any other
# exit status, an "lsof: …" message or a line that is not a -F p/f/G field is an error, and the caller then
# leaves the file alone (renaming a log a service still writes would send its output into an unlinked file).
log_writers() {
  local out rc=0
  command -v lsof > /dev/null 2>&1 || { echo "error lsof is not on PATH"; return 0; }
  out=$(lsof -F G +fg -- "$1" 2>&1) || rc=$?
  if [ "$rc" -eq 1 ] && [ -z "$out" ]; then echo "ok 0 0"; return 0; fi
  if [ "$rc" -ne 0 ]; then echo "error lsof exited $rc"; return 0; fi
  printf '%s\n' "$out" | awk '
    /^[pf]/ { next }
    /^G/    { n = split(substr($0, 2), f, /[,;]/); w = 0; ap = 0
              for (i = 1; i <= n; i++) { if (f[i] == "W" || f[i] == "RW") w = 1; if (f[i] == "AP") ap = 1 }
              if (w) { writers++; if (!ap) bad++ }
              next }
            { odd++ }
    END     { if (odd) print "error unexpected lsof output"; else printf "ok %d %d\n", writers, bad }'
}

# rotate_log <file> — rotate <file> when it is larger than LOG_MAX_BYTES; prints one line when it acts.
# A file nobody has open is renamed. A file a process still writes is copied, then truncated in place
# (copytruncate): that is only safe when every writer opened it for append (`>>`), because the next write
# then lands at the new end. A writer without O_APPEND (a service started by an older start-local.sh with `>`)
# would write behind a sparse hole, so such a file is left alone and reported (restart that service once).
# When the writers cannot be determined (log_writers says error) the file is left alone too (fail closed).
rotate_log() {
  local f=$1 size res writers bad i
  [ -f "$f" ] || return 0
  size=$(wc -c < "$f" 2> /dev/null | tr -d ' ')
  [ -n "$size" ] && [ "$size" -gt "$LOG_MAX_BYTES" ] || return 0
  res=$(log_writers "$f")
  case "$res" in
    "ok "*) read -r _ writers bad <<< "$res" ;;
    *) print_info "not rotating ${f#$PROJECT_ROOT/} ($size bytes): cannot tell whether a process still writes it (${res#error }); left as is"
       return 0 ;;
  esac
  if [ "${bad:-0}" -gt 0 ]; then
    print_info "not rotating ${f#$PROJECT_ROOT/} ($size bytes): its writer did not open it for append; restart that service once"
    return 0
  fi
  rm -f "$f.$LOG_KEEP"
  i=$LOG_KEEP
  while [ "$i" -gt 1 ]; do
    if [ -f "$f.$((i - 1))" ]; then mv -f "$f.$((i - 1))" "$f.$i"; fi
    i=$((i - 1))
  done
  if [ "${writers:-0}" -gt 0 ]; then
    cp -p "$f" "$f.1" && : > "$f"
  else
    mv -f "$f" "$f.1"
  fi
  print_info "rotated ${f#$PROJECT_ROOT/} ($size bytes) to ${f#$PROJECT_ROOT/}.1 (keeping $LOG_KEEP)"
}

# rotate_all_logs — `rotate-logs`: every .logs/*.log over the cap (the watchdog runs it hourly).
rotate_all_logs() {
  local f
  for f in "$PROJECT_ROOT"/.logs/*.log; do
    [ -f "$f" ] && rotate_log "$f"
  done
  return 0
}

# open_service_log <name> <port> — rotate if needed, append the start banner, print the log path.
open_service_log() {
  local log="$PROJECT_ROOT/.logs/$1.log"
  rotate_log "$log" >&2
  echo "=== $(date '+%Y-%m-%d %H:%M:%S %z') start-local.sh: starting $1 on 127.0.0.1:$2 ===" >> "$log"
  echo "$log"
}

# start_py_service <name> <dir, relative to project> <module:app> <port> [extra uvicorn args...]
start_py_service() {
  local name=$1 dir=$2 app=$3 port=$4; shift 4
  local log
  print_info "Starting $name (port $port)..."
  log=$(open_service_log "$name" "$port")
  # cd first, then background ONLY the server (with stdin detached), so $! is the
  # server's own PID and no wrapper shell lingers holding the caller's terminal/pipe.
  (
    cd "$PROJECT_ROOT/$dir" || exit 1
    # --timeout-graceful-shutdown: the UI holds long-lived SSE/WebSocket streams; without
    # a cap, uvicorn waits for them forever on stop/--reload and the service wedges.
    # --timeout-keep-alive 75: must outlive the CLIENT's idle-socket timeout (Next's proxy
    # and httpx both drop idle sockets at ~5s). With uvicorn's default of 5s the two race:
    # a pooled socket gets reused just as uvicorn closes it → "socket hang up" → the
    # browser sees an intermittent 500 on POSTs (seen on /api/analytics/rrg).
    nohup $PYTHON_BIN -m uvicorn "$app" --host 127.0.0.1 --port "$port" \
      --timeout-graceful-shutdown 5 --timeout-keep-alive 75 "$@" \
      >> "$log" 2>&1 < /dev/null &
    echo $! > "$PROJECT_ROOT/.pids/$name.pid"
  )
  for _ in $(seq 1 60); do
    # 127.0.0.1, the address it binds (localhost tries ::1 first, where another program could answer)
    if curl -sf -m 5 "http://127.0.0.1:$port/health" > /dev/null 2>&1; then
      print_success "$name healthy (PID: $(cat "$PROJECT_ROOT/.pids/$name.pid"))"
      return 0
    fi
    sleep 1
  done
  print_error "$name did not become healthy — see .logs/$name.log"
  return 1
}

# ── Service registry ──────────────────────────────────────────────────────────
# Start order = listed order. data-service first: it is the ONLY writer of
# market.duckdb. Stop order is the reverse, so data-service stops last and
# checkpoints DuckDB after everything that talks to it has gone.
ALL_SERVICES="data-service ml-service feature-service rl-service ui-api master-controller frontend"
# The real 3-process stack (CLAUDE.md; desktop program 24 Oct 2026): ui-api serves the terminal UI itself
# (static release ui/dist/current), so Node is out of production. `frontend` (Next on :3000) is optional:
# `start frontend` still runs the dev server (hot reload) or, with UI_MODE=prod, the old Next prod build.
# The 5-day ML era services are dormant: `start`/`restart` with no service name never launch them (they
# cost ~1 GB RAM for nothing); `start legacy` still does.
CORE_SERVICES="data-service ui-api master-controller"
UI_RELEASE_DIR="$PROJECT_ROOT/ui/dist/current"
LEGACY_SERVICES="ml-service feature-service rl-service"
# ui-api hot reload is opt-in (UI_API_RELOAD=1): under --reload any file save silently restarts the
# live backend, and the watchdog/boot path must run the plain server (critique_engineering R1).
if [ "${UI_API_RELOAD:-0}" = "1" ]; then UI_API_RELOAD_FLAG="--reload"; else UI_API_RELOAD_FLAG=""; fi
# "Stopped on purpose" markers: scripts/stack_watchdog.sh never starts a service that has one.
# Any explicit stop writes it; any explicit start clears it.
PAUSE_DIR="$PROJECT_ROOT/.pids/paused"
mark_paused()   { mkdir -p "$PAUSE_DIR"; date "+%Y-%m-%d %H:%M:%S" > "$PAUSE_DIR/$1"; }
clear_paused()  { rm -f "$PAUSE_DIR/$1"; }
# The watchdog restarts a hung service at most 3 times an hour, then only alerts (.pids/watchdog/hang-restarts-<svc>).
# A start or restart by hand is the owner taking over, so it clears that record; the watchdog's own calls do not.
clear_hang_history() { [ "$CALLED_BY_WATCHDOG" = "1" ] || rm -f "$PROJECT_ROOT/.pids/watchdog/hang-restarts-$1"; }

# svc_spec <name> → "dir|module:app|port|extra-args"   (bash 3.2: no assoc arrays)
svc_spec() {
  case "$1" in
    data-service)      echo "services/data-service|main:app|8001|" ;;
    ml-service)        echo "services/ml-service|main:app|8003|" ;;
    feature-service)   echo "services/feature-service|main:app|8002|" ;;
    rl-service)        echo "services/rl-service|main:app|8004|" ;;
    ui-api)            echo "services/ui-api|main:app|8010|$UI_API_RELOAD_FLAG" ;;
    master-controller) echo "scripts|master_controller:app|8008|" ;;
    frontend)          echo "ui|next|3000|" ;;
    *) return 1 ;;
  esac
}

svc_port() { svc_spec "$1" | cut -d'|' -f3; }

require_service() {
  if ! svc_spec "$1" > /dev/null; then
    print_error "Unknown service: $1"
    echo "  Services: $ALL_SERVICES"
    exit 1
  fi
}

reverse_list() { local out=""; for x in $1; do out="$x $out"; done; echo "$out"; }

# Redis password (Terminal v2 Wave 0.7, O-T10): REDIS_PASSWORD in .env, else the Keychain item
# 'suryadhana-redis' (security add-generic-password -a "$USER" -s suryadhana-redis -w '<pw>'). Printed never.
redis_password() {
  local pw; pw=$(env_file_val REDIS_PASSWORD)
  if [ -z "$pw" ] && [ -z "${REDIS_NO_KEYCHAIN:-}" ] && command -v security > /dev/null 2>&1; then
    pw=$(security find-generic-password -a "$USER" -s suryadhana-redis -w 2> /dev/null || true)
  fi
  printf '%s' "$pw"
}

# Does the Redis on 6379 answer PING with this password (empty = no AUTH)? REDISCLI_AUTH keeps it off argv.
redis_answers() {
  local pw=$1
  if [ -n "$pw" ]; then REDISCLI_AUTH="$pw" redis-cli -h 127.0.0.1 -p 6379 ping 2> /dev/null | grep -q PONG
  else redis-cli -h 127.0.0.1 -p 6379 ping 2> /dev/null | grep -q PONG; fi
}

start_redis() {
  # Optional: live-quote pub/sub + monitored-symbol set. Left running on stop
  # (lightweight, and other local tools may share it). Stop: redis-cli shutdown
  # Bound to 127.0.0.1 only (R-ARCH §3: it listened on *:6379 with no password); --requirepass when a
  # password is configured. The services read REDIS_URL from the environment first (.env never overrides an
  # exported variable), so the URL with the password is exported here for the children this script starts.
  local pw; pw=$(redis_password)
  if lsof -iTCP:6379 -sTCP:LISTEN > /dev/null 2>&1; then
    if [ -n "$pw" ] && command -v redis-cli > /dev/null 2>&1; then
      if redis_answers "$pw"; then
        export REDIS_URL="redis://:${pw}@127.0.0.1:6379/0"
        print_success "Redis already listening on 6379 (password set)"
      elif redis_answers ""; then
        print_info "Redis already listening on 6379 WITHOUT the configured password — restart it to apply:" \
          "redis-cli shutdown; ./start-local.sh restart"
        export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"
      else
        print_info "Redis already listening on 6379 but not answering with the configured password"
      fi
    else
      print_success "Redis already listening on 6379"
    fi
  elif command -v redis-server > /dev/null 2>&1; then
    if [ -n "$pw" ]; then
      # The password goes through a config on stdin, never argv (ps would show it).
      printf 'requirepass %s\n' "$pw" | redis-server - --port 6379 --bind 127.0.0.1 --daemonize yes --save "" \
        --appendonly no --logfile "$PROJECT_ROOT/.logs/redis.log" \
        && { export REDIS_URL="redis://:${pw}@127.0.0.1:6379/0"; print_success "Redis started (127.0.0.1:6379, password set)"; }
    else
      redis-server --port 6379 --bind 127.0.0.1 --daemonize yes --save "" --appendonly no \
        --logfile "$PROJECT_ROOT/.logs/redis.log" \
        && print_success "Redis started (127.0.0.1:6379, no password: set REDIS_PASSWORD in .env or the Keychain item suryadhana-redis)"
    fi
  else
    print_info "Redis not installed — live quote streaming disabled (enable: brew install redis)"
  fi
}

start_frontend() {
  local log
  print_info "Starting frontend (port 3000)..."
  log=$(open_service_log frontend 3000)
  (
    cd "$PROJECT_ROOT/ui" || exit 1
    # Loopback only (-H 127.0.0.1): Next binds every interface by default, which exposed the whole unauthenticated
    # API to the LAN through its /api rewrite (desktop review C2-security-02, 25 Oct 2026).
    if [ "${UI_MODE:-dev}" = "prod" ]; then
      # Optimised build in .next-prod (dev keeps .next). Rebuild only when a source file is newer than the build.
      if [ ! -f .next-prod/BUILD_ID ] || [ -n "$(find app components lib context next.config.js -newer .next-prod/BUILD_ID -type f 2>/dev/null | head -1)" ]; then
        print_info "Building production UI (≈ 1–2 min)..."
        NEXT_DIST_DIR=.next-prod npx next build > "$PROJECT_ROOT/.logs/frontend-build.log" 2>&1 \
          || { print_error "UI build failed — see .logs/frontend-build.log"; exit 1; }
      fi
      NEXT_DIST_DIR=.next-prod nohup npx next start -H 127.0.0.1 -p 3000 >> "$log" 2>&1 < /dev/null &
    else
      nohup npm run dev -- -H 127.0.0.1 >> "$log" 2>&1 < /dev/null &
    fi
    echo $! > "$PROJECT_ROOT/.pids/frontend.pid"
  )
  for _ in $(seq 1 90); do
    if curl -sf -m 3 http://127.0.0.1:3000 > /dev/null 2>&1; then
      print_success "frontend ready"
      return 0
    fi
    sleep 1
  done
  print_error "frontend did not become ready — see .logs/frontend.log"
  return 1
}

# start_one <name> — start a single service if it is not already up
# The UI release ui-api serves (scripts/build_ui.sh swaps ui/dist/current atomically). Prints its id.
ui_release_id() {
  [ -f "$UI_RELEASE_DIR/index.html" ] || return 1
  basename "$(cd "$UI_RELEASE_DIR" 2> /dev/null && pwd -P)"
}

warn_if_no_ui_release() {
  if ! ui_release_id > /dev/null; then
    echo -e "${YELLOW}!${NC} No UI release at ui/dist/current: the terminal at http://127.0.0.1:8010 shows a"
    echo -e "  'UI build not found' page until one exists (the API works). Build one: ./start-local.sh build-ui"
  fi
}

start_one() {
  local name=$1 spec dir app port extra
  spec=$(svc_spec "$name"); IFS='|' read -r dir app port extra <<< "$spec"
  if [ "$name" = "ui-api" ]; then warn_if_no_ui_release; fi
  if lsof -iTCP:"$port" -sTCP:LISTEN > /dev/null 2>&1; then
    print_success "$name already running on $port"
    return 0
  fi
  if [ "$name" = "frontend" ]; then
    start_frontend
  else
    # shellcheck disable=SC2086
    start_py_service "$name" "$dir" "$app" "$port" $extra
  fi
}

# tree_pids <pid> — the pid plus all descendants (npm → next dev → next-server,
# uvicorn --reload supervisor → worker, …)
tree_pids() {
  local p=$1 c
  echo "$p"
  for c in $(pgrep -P "$p" 2>/dev/null); do tree_pids "$c"; done
}

# stop_one <name> — SIGTERM the WHOLE process tree (pidfile + port listener +
# children), wait for every pid to exit, then SIGKILL survivors. Signalling only
# the top process used to orphan children (e.g. a stale next-server kept running).
stop_one() {
  local name=$1 port grace pids="" root p alive
  port=$(svc_port "$name")
  [ "$name" = "frontend" ] && grace=6 || grace=20   # next-server ignores SIGTERM; no state

  for root in $(cat "$PROJECT_ROOT/.pids/$name.pid" 2>/dev/null) \
              $(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null); do
    kill -0 "$root" 2>/dev/null && pids="$pids $(tree_pids "$root")"
  done
  pids=$(echo $pids | tr ' ' '\n' | sort -u | tr '\n' ' ')
  if [ -z "${pids// /}" ]; then
    print_info "$name not running"
    rm -f "$PROJECT_ROOT/.pids/$name.pid"
    return 0
  fi

  kill -TERM $pids 2>/dev/null || true
  for _ in $(seq 1 "$grace"); do
    alive=""
    for p in $pids; do kill -0 "$p" 2>/dev/null && alive="$alive $p"; done
    [ -z "$alive" ] && break
    sleep 1
  done
  if [ -n "$alive" ]; then
    kill -9 $alive 2>/dev/null || true
    print_info "$name: force-stopped$alive after ${grace}s"
  fi
  rm -f "$PROJECT_ROOT/.pids/$name.pid"
  print_success "$name stopped"
}

print_urls() {
  print_header "✓ Services Running Locally"
  local rid; rid=$(ui_release_id || echo "none, run ./start-local.sh build-ui")
  echo -e "${GREEN}Terminal:      http://127.0.0.1:8010   (static UI served by ui-api · release: $rid)${NC}"
  echo -e "${GREEN}UI API:        http://localhost:8010${NC}"
  echo -e "${GREEN}Dev UI:        http://localhost:3000   (optional: ./start-local.sh start frontend)${NC}"
  echo -e "${GREEN}Data Service:  http://localhost:8001   (freshness: /db/freshness, jobs: /jobs)${NC}"
  echo -e "${GREEN}ML Service:    http://localhost:8003${NC}"
  echo -e "${GREEN}Feature Svc:   http://localhost:8002   RL Service: http://localhost:8004${NC}"
  echo -e "${GREEN}Scheduler:     http://localhost:8008   (status: /api/scheduler/status — autopilot OFF, data jobs ON)${NC}"
  echo ""
  echo -e "${BLUE}Manage:${NC} ./start-local.sh status | restart | stop | restart <service> | logs <service>"
}

start_services() {
  print_header "Starting Services Locally"
  start_redis
  local failed=""
  for name in ${START_SET:-$CORE_SERVICES}; do
    clear_paused "$name"
    clear_hang_history "$name"
    start_one "$name" || failed="$failed $name"
  done
  if [ -n "$failed" ]; then
    print_error "Failed to start:$failed — check .logs/<service>.log"
    return 1
  fi
  print_urls
}

stop_services() {
  # F9-06: this used to loop $ALL_SERVICES unconditionally while start_services honoured $START_SET, so
  # `START_SET='ui-api' ./start-local.sh stop` stopped AND paused all seven services without saying so — and
  # `restart` inherited it, stopping everything and bringing back only the set, leaving the rest paused. The
  # asymmetry was the footgun behind F8-01: the guard was asked about one set and a different set went down.
  # Both halves now read the same variable, so what the window is asked about is what actually stops.
  # F10-07: an explicit list wins, then $START_SET, then everything. `restart` passes the set it is going to
  # bring back UP, because stopping and PAUSING services it will not restart leaves them down with the watchdog
  # told to ignore them — bare `restart` used to stop and pause all seven and start only the three core ones.
  local targets="${1:-${START_SET:-$ALL_SERVICES}}"
  print_header "Stopping Local Services"
  [ -n "${START_SET:-}" ] && print_info "START_SET is set: stopping only $targets"
  for name in $(reverse_list "$targets"); do
    mark_paused "$name"
    stop_one "$name"
  done
  if [ -n "${START_SET:-}" ]; then
    print_success "Stopped: $targets (others left running; Redis untouched)"
  else
    print_success "All local services stopped (Redis left running: redis-cli shutdown)"
  fi
}

# ── status rows beyond the services ──────────────────────────────────────────
# STATUS_UI_API: the ui-api `status` asks for the UI release it serves and the settings migration record (GET
# only). STATUS_PY_TIMEOUT: seconds a status helper (the jupyter_env Python) may run; a Python blocked on a
# macOS Desktop-folder (TCC) consent prompt would otherwise hang `status` forever in a non-interactive context.
STATUS_UI_API="${STATUS_UI_API:-http://127.0.0.1:8010}"
STATUS_PY_TIMEOUT="${STATUS_PY_TIMEOUT:-10}"

# run_with_timeout <seconds> <cmd...> — the command's exit status, or 124 when it ran out of time (it is then
# killed: TERM, and KILL 2 s later; GNU timeout signals its whole process group, the bash fallback the command and
# its direct children). GNU timeout (Homebrew coreutils) when present, else a bash wait loop. The command gets no
# stdin (pass a program with -c and data as arguments).
run_with_timeout() {
  local secs=$1 pid n=0 rc=0
  shift
  if command -v timeout > /dev/null 2>&1; then
    timeout -k 2 "$secs" "$@" < /dev/null || rc=$?
    case "$rc" in 124|137) return 124 ;; *) return "$rc" ;; esac
  fi
  "$@" < /dev/null &
  pid=$!
  while kill -0 "$pid" 2> /dev/null; do
    if [ "$n" -ge $((secs * 10)) ]; then
      pkill -TERM -P "$pid" 2> /dev/null || true
      kill -TERM "$pid" 2> /dev/null || true
      sleep 2
      pkill -KILL -P "$pid" 2> /dev/null || true
      kill -KILL "$pid" 2> /dev/null || true
      wait "$pid" 2> /dev/null || true
      return 124
    fi
    sleep 0.1
    n=$((n + 1))
  done
  wait "$pid" || rc=$?
  return "$rc"
}

# ui_api_answers — ui-api's /health is 200 (cached in UI_API_UP; status_services sets it from its own probe).
ui_api_answers() {
  if [ -z "${UI_API_UP:-}" ]; then
    UI_API_UP=0
    [ "$(curl -s -o /dev/null -m 3 -w '%{http_code}' "$STATUS_UI_API/health" 2> /dev/null)" = "200" ] && UI_API_UP=1
  fi
  [ "$UI_API_UP" = "1" ]
}

# prefs: the server-side settings store (desktop program D3). The owner's watchlist, pins and page settings
# live in the old browser terminal's localStorage (:3000) until that origin is opened once with the sync code;
# this row says whether that one-time import has happened (desktop review C2-reliability-ops-02, C3-01).
prefs_db_path() {
  local p="${PREFS_DB:-$(env_file_val PREFS_DB)}"
  [ -n "$p" ] || p="$PROJECT_ROOT/data/ui_prefs.sqlite"
  case "$p" in "~/"*) p="$HOME/${p#\~/}" ;; esac
  echo "$p"
}

# The status helper (run with -c; argv: <db> <ui-api base, or '' to never ask ui-api>). One line:
#   ok|<live keys>|<defaults>|<from :3000>|<watchlist>|<pins>|<import>|<import at>|<import keys>|<import origin>|<inferred>
#   error|<message>
# <import> comes from the durable migration record (contract K2: GET /api/prefs → migration {legacy_import_at,
# legacy_origin, legacy_keys, inferred}, which ui-api keeps as the JSON row 'migration' of the store's meta table
# (k, v), set by the FIRST legacy import and never cleared by later writes; 'inferred' = backfilled once from
# per-record provenance for a store migrated before the record existed): yes / no, or unknown when neither the
# store nor ui-api has one (an older ui-api). Read-only and value-free: with ui-api running (a -wal exists) the store is opened mode=ro; with the
# store closed (no -wal: everything is in the main file) immutable, so no -wal/-shm is ever left behind.
prefs_summary_py() {
  cat << 'PYEOF'
import json
import sqlite3
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

KEYS = ("suryadhana.watchlist", "newsTerminal.pins.v1")
IST = timezone(timedelta(hours=5, minutes=30))
db = Path(sys.argv[1]).resolve()
api = sys.argv[2] if len(sys.argv) > 2 else ""


def clean(v, n=60):
    s = "".join(ch for ch in str(v) if ch.isalnum() or ch in ":/._-")[:n]
    return s or "-"


def from_browser(origin):  # the old browser terminal: http://localhost:3000, a LAN :3000, ...
    return origin.rstrip("/").endswith(":3000")


def meta_migration(con):
    """K2 record from the store's meta table (ui-api: columns k, v); None when the store has no such table."""
    names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "meta" not in names:
        return None
    cols = {r[1] for r in con.execute("PRAGMA table_info(meta)")}
    k, v = ("k", "v") if {"k", "v"} <= cols else ("key", "value") if {"key", "value"} <= cols else (None, None)
    if k is None:
        return None
    kv = dict(con.execute(f"SELECT {k}, {v} FROM meta WHERE {k} IN "
                          "('migration', 'legacy_import_at', 'legacy_origin', 'legacy_keys')").fetchall())
    if "migration" in kv:
        try:
            m = json.loads(kv["migration"])
        except (TypeError, ValueError):
            return None
        return m if isinstance(m, dict) else None
    return {k: kv.get(k) for k in ("legacy_import_at", "legacy_origin", "legacy_keys")}


def api_migration():
    """K2 record from ui-api's GET /api/prefs (only the 'migration' field is read; values are never printed)."""
    if not api:
        return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(api + "/api/prefs", timeout=3) as r:
            body = json.load(r)
    except Exception:  # unreachable, or an older ui-api: fall back to per-record provenance
        return None
    m = body.get("migration") if isinstance(body, dict) else None
    return m if isinstance(m, dict) else None


try:
    flags = "?mode=ro" if Path(str(db) + "-wal").exists() else "?mode=ro&immutable=1"
    con = sqlite3.connect(db.as_uri() + flags, uri=True, timeout=2)
    try:
        rows = con.execute("SELECT key, provisional, COALESCE(origin, '') FROM prefs WHERE deleted = 0").fetchall()
        mig = meta_migration(con)
    finally:
        con.close()
except sqlite3.Error as e:
    print("error|" + clean(type(e).__name__, 40) + ": " + " ".join(str(e).split())[:100].replace("|", "/"))
    sys.exit(0)
if mig is None:
    mig = api_migration()

state = dict.fromkeys(KEYS, "absent")
for key, provisional, origin in rows:
    if key in state:
        state[key] = "default" if provisional else ("browser" if from_browser(origin) else "app")
browser = sum(1 for _k, provisional, origin in rows if not provisional and from_browser(origin))
imp, at, nkeys, src, inferred = "unknown", "-", "-", "-", "-"
if mig is not None:
    raw = mig.get("legacy_import_at")
    try:
        t = float(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        t = None
    imp = "no" if t is None else "yes"
    if t is not None:
        t = t / 1000 if t > 1e11 else t  # epoch ms (the store's unit) or seconds
        try:
            at = datetime.fromtimestamp(t, IST).strftime("%Y-%m-%d %H:%M IST")
        except (OverflowError, OSError, ValueError):
            at = "-"
        try:
            nkeys = str(int(mig.get("legacy_keys") or 0))
        except (TypeError, ValueError):
            nkeys = "-"
        src = clean(mig.get("legacy_origin") or "-")
        inferred = "yes" if mig.get("inferred") is True else "no"
print("|".join(["ok", str(len(rows)), str(sum(1 for r in rows if r[1])), str(browser), state[KEYS[0]], state[KEYS[1]],
                imp, at, nkeys, src, inferred]))
PYEOF
}

# prefs_summary <db> → one line of prefs_summary_py. ui-api's own record is consulted only for the store ui-api
# itself uses: never when PREFS_DB is set in the caller's environment (a test or scratch store).
prefs_summary() {
  local api="" out rc=0
  if [ -z "${PREFS_DB:-}" ] && ui_api_answers; then api="$STATUS_UI_API"; fi
  out=$(run_with_timeout "$STATUS_PY_TIMEOUT" "$PYTHON_BIN" -c "$(prefs_summary_py)" "$1" "$api" 2> /dev/null) || rc=$?
  if [ "$rc" -eq 124 ]; then
    echo "error|$PYTHON_BIN timed out after ${STATUS_PY_TIMEOUT}s (blocked on a macOS privacy prompt?)"
  elif [ "$rc" -ne 0 ] || [ -z "$out" ]; then
    echo "error|cannot run $PYTHON_BIN"
  else
    printf '%s\n' "$out" | tail -1
  fi
}

prefs_status_row() {
  local db s n defaults browser wl pins imp at nkeys src inferred detail open="" step
  db=$(prefs_db_path)
  if [ ! -f "$db" ]; then
    printf "%-18s %-6s %-8s %-${HW}b %s\n" "prefs" "-" "-" "${YELLOW}none${NC}" \
      "no settings store yet (ui-api creates ${db#$PROJECT_ROOT/} on first use)"
    return 0
  fi
  s=$(prefs_summary "$db")
  case "$s" in
    "ok|"*) IFS='|' read -r _ n defaults browser wl pins imp at nkeys src inferred <<< "$s" ;;
    *) printf "%-18s %-6s %-8s %-${HW}b %s\n" "prefs" "-" "-" "${RED}unreadable${NC}" "${db#$PROJECT_ROOT/}: ${s#error|}"
       return 0 ;;
  esac
  detail="$n keys ($defaults defaults) · watchlist: $wl · pins: $pins"
  # Imported: ui-api's durable record says so (it never flips back after later edits in the app), or, without
  # one (an older ui-api), some live non-provisional record was still written from the :3000 origin.
  if [ "$imp" = "yes" ]; then
    local how="imported $nkeys keys from $src on $at"
    [ "$inferred" = "yes" ] && how="imported from $src (recorded from its $nkeys records; earliest $at)"
    printf "%-18s %-6s %-8s %-${HW}b %s\n" "prefs" "-" "-" "${GREEN}imported${NC}" "$detail · $how"
    return 0
  fi
  if [ "${browser:-0}" -gt 0 ]; then
    printf "%-18s %-6s %-8s %-${HW}b %s\n" "prefs" "-" "-" "${GREEN}imported${NC}" \
      "$detail · $browser from the browser terminal (:3000)"
    return 0
  fi
  # Keys an import can still fill: absent, or holding only a provisional default. A key set in the app is a
  # deliberate write that a later import never replaces, so its migration window is closed.
  case "$wl" in default|absent) open="watchlist" ;; esac
  case "$pins" in default|absent) open="${open:+$open or }pins" ;; esac
  step="./start-local.sh start frontend, then open"
  lsof -iTCP:3000 -sTCP:LISTEN > /dev/null 2>&1 && step="open"
  if [ -n "$open" ]; then
    printf "%-18s %-6s %-8s %-${HW}b %s\n" "prefs" "-" "-" "${YELLOW}not imported${NC}" "$detail"
    echo -e "  ${YELLOW}→${NC} before editing the $open in the app: $step http://localhost:3000 once in your" \
      "usual browser, check this row again, then ./start-local.sh stop frontend (RUNBOOK §8)"
  elif [ "$imp" = "no" ]; then
    printf "%-18s %-6s %-8s %-${HW}b %s\n" "prefs" "-" "-" "${YELLOW}not imported${NC}" \
      "$detail · the watchlist and pins were set in the app (an import keeps them)"
    echo -e "  ${YELLOW}→${NC} to bring over the browser terminal's other settings: $step http://localhost:3000 once" \
      "in your usual browser, then ./start-local.sh stop frontend (RUNBOOK §8)"
  else
    printf "%-18s %-6s %-8s %-${HW}b %s\n" "prefs" "-" "-" "app-owned" \
      "$detail · set in the app; an import from the browser terminal can no longer replace them"
  fi
}

# ui_api_served_release → "<release id or -> <ui_status>" from ui-api's GET /version; status 1 when it does not
# answer. Parsed with sed (no Python): the release id sits in the flat build-info object under "ui_build".
ui_api_served_release() {
  local body id st
  body=$(curl -s -m 3 "$STATUS_UI_API/version" 2> /dev/null) || return 1
  id=$(printf '%s' "$body" | tr -d '\n' |
    sed -nE 's/.*"ui_build"[[:space:]]*:[[:space:]]*[{][^}]*"id"[[:space:]]*:[[:space:]]*"([A-Za-z0-9._-]{1,80})".*/\1/p')
  st=$(printf '%s' "$body" | tr -d '\n' | sed -nE 's/.*"ui_status"[[:space:]]*:[[:space:]]*"([a-z_]{1,20})".*/\1/p')
  [ -n "$st" ] || return 1
  echo "${id:--} $st"
}

# ui-release: the release in ui/dist/current next to the one ui-api says it serves (GET /version). They differ
# when ui-api serves another directory (UI_DIST_DIR in its environment) or a build-ui swap ran in between.
ui_release_row() {
  local rid="" served="" sid="" sst=""
  rid=$(ui_release_id) || rid=""
  if ui_api_answers; then
    served=$(ui_api_served_release) || served="? ?"
    read -r sid sst <<< "$served"
  fi
  if [ -z "$rid" ]; then
    if [ "$sst" = "ok" ]; then
      printf "%-18s %-6s %-8s %-${HW}b %s\n" "ui-release" "-" "-" "${RED}missing${NC}" \
        "./start-local.sh build-ui · ui-api serves $sid from another directory (UI_DIST_DIR?)"
    else
      printf "%-18s %-6s %-8s %-${HW}b %s\n" "ui-release" "-" "-" "${RED}missing${NC}" "./start-local.sh build-ui"
    fi
    return 0
  fi
  if [ -z "$served" ]; then
    printf "%-18s %-6s %-8s %-${HW}b %s\n" "ui-release" "-" "-" "${GREEN}ok${NC}" "$rid (ui/dist/current) · ui-api not answering (/health)"
  elif [ "$sid" = "?" ]; then
    printf "%-18s %-6s %-8s %-${HW}b %s\n" "ui-release" "-" "-" "${GREEN}ok${NC}" \
      "$rid (ui/dist/current) · ui-api's GET /version did not answer"
  elif [ "$sst" = "ok" ] && [ "$sid" = "$rid" ]; then
    printf "%-18s %-6s %-8s %-${HW}b %s\n" "ui-release" "-" "-" "${GREEN}ok${NC}" "$rid (ui/dist/current) · served by ui-api"
  else
    [ "$sst" = "ok" ] || sid="no release"
    printf "%-18s %-6s %-8s %-${HW}b %s\n" "ui-release" "-" "-" "${YELLOW}mismatch${NC}" \
      "$rid (ui/dist/current) · ui-api serves: $sid"
    echo -e "  ${YELLOW}→${NC} ui-api is not serving ui/dist/current: run status again (a build-ui swap may have just" \
      "run); if it persists, ui-api has UI_DIST_DIR set (shell or .env): fix it, then ./start-local.sh restart ui-api"
  fi
}
# The desktop app (informational): running or not, and whether macOS starts it at login. SURYADHANA_APP
# names the bundle to report on (tests); otherwise the installed copy (/Applications, else ~/Applications).
app_bundle() {
  local a
  if [ -n "${SURYADHANA_APP:-}" ]; then [ -d "$SURYADHANA_APP" ] && echo "$SURYADHANA_APP"; return; fi
  for a in /Applications/SuryaDhana.app "$HOME/Applications/SuryaDhana.app"; do
    [ -d "$a" ] && { echo "$a"; return 0; }
  done
  return 1
}

# app_procs → "<pid><TAB><executable>" for every running SuryaDhana app executable (…/SuryaDhana.app/Contents/MacOS/
# SuryaDhana): the installed copy, and any self-test or build copy (desktop/src-tauri/target/…), told apart by path.
# The executable must be the command itself: an absolute path with no space before the bundle suffix (so a grep, or
# this awk, whose arguments name the path never counts).
app_procs() {
  ps -axo pid=,command= 2> /dev/null | awk -v tail=".app/Contents/MacOS/SuryaDhana" '{
    pid = $1; line = $0; sub(/^ *[0-9]+ +/, "", line); n = index(line, tail)
    if (!n || substr(line, 1, 1) != "/" || index(substr(line, 1, n), " ")) next
    exe = substr(line, 1, n + length(tail) - 1); rest = substr(line, length(exe) + 1)
    if (rest == "" || rest ~ /^ /) printf "%s\t%s\n", pid, exe }'
}

# the pid of the app instance launchd runs as the Launch at Login job (label SuryaDhana), if any
launchd_app_pid() {
  launchctl print "gui/$(id -u)/SuryaDhana" 2> /dev/null | awk '$1 == "pid" && $2 == "=" { print $3; exit }'
  return 0
}

# The desktop app (informational): running or not, whether macOS starts it at login, and whether launchd supervises
# the running copy. SECREL-11: the row used to take the first process NAMED SuryaDhana, which reported a self-test
# copy from desktop/ as the installed app; now only the installed bundle's own executable counts, other copies are
# listed apart. SECREL-06: launchd's KeepAlive relaunches after a crash only the copy it started (the Launch at Login
# job); a copy reopened from the Dock or Finder after Quit starts a crash guard instead (desktop/src-tauri/src/
# supervise.rs: `/bin/sh -c <script> suryadhana-crash-guard <app pid> …`, which has launchd start the app again after
# an unclean end; app builds from 25 Oct round 3), so the row says which applies, and gives the RUNBOOK §5 remedy
# when neither does. SURYADHANA_APP names the bundle to report on (tests); otherwise the installed copy
# (/Applications, else ~/Applications).
app_status_row() {
  local app pid="" login=off ver state exe procs others job sup=""
  [ -f "$HOME/Library/LaunchAgents/SuryaDhana.plist" ] && login=on
  procs=$(app_procs)
  if ! app=$(app_bundle); then
    others=$(printf '%s\n' "$procs" | awk -F'\t' 'NF == 2 { printf "%s%s", sep, $1; sep = " " }')
    printf "%-18s %-6s %-8s %-${HW}b %s\n" "desktop-app" "-" "-" "${YELLOW}absent${NC}" \
      "SuryaDhana.app not installed (scripts/build_desktop.sh --install) · Launch at Login: $login${others:+ · other copies running: pid $others}"
    return 0
  fi
  exe="$app/Contents/MacOS/SuryaDhana"
  pid=$(printf '%s\n' "$procs" | awk -F'\t' -v e="$exe" '$2 == e { print $1; exit }')
  others=$(printf '%s\n' "$procs" | awk -F'\t' -v e="$exe" -v root="$PROJECT_ROOT" -v home="$HOME" '
    NF == 2 && $2 != e { p = $2; sub(/\/Contents\/MacOS\/SuryaDhana$/, "", p)
                         if (index(p, root "/") == 1) p = "." substr(p, length(root) + 1)
                         else if (index(p, home "/") == 1) p = "~" substr(p, length(home) + 1)
                         printf "%s%s (%s)", sep, $1, p; sep = ", " }')
  ver=$(/usr/libexec/PlistBuddy -c "Print :CFBundleShortVersionString" "$app/Contents/Info.plist" 2> /dev/null || echo "?")
  if [ -n "$pid" ]; then
    state="${GREEN}running${NC}"
    job=$(launchd_app_pid)
    if [ "$job" = "$pid" ]; then
      sup=" · supervised by launchd (relaunched after a crash)"
    elif [ "$login" = "on" ] && pgrep -f -- "suryadhana-crash-guard $pid " > /dev/null 2>&1; then
      sup=" · opened by hand: its crash guard relaunches it through launchd"
    elif [ "$login" = "on" ]; then
      sup=" · opened by hand: not relaunched after a crash"
    else
      sup=" · not relaunched after a crash (Launch at Login is off)"
    fi
  else
    state="${YELLOW}not running${NC}"
  fi
  printf "%-18s %-6s %-8s %-${HW}b %s\n" "desktop-app" "-" "${pid:--}" "$state" \
    "${app/#$HOME/~} $ver · Launch at Login: $login$sup${others:+ · other copies: $others}"
  if [ -n "$pid" ] && [ "$login" = "on" ] && [ "$job" != "$pid" ] && ! pgrep -f -- "suryadhana-crash-guard $pid " > /dev/null 2>&1; then
    echo -e "  ${YELLOW}→${NC} to have launchd supervise it: quit the app (⌘Q), then launchctl kickstart gui/$(id -u)/SuryaDhana" \
      "(RUNBOOK §5)"
  fi
  return 0
}

# ago <seconds> → "45 s" / "12 min" / "3 h"
ago() { if [ "$1" -lt 120 ]; then echo "$1 s"; elif [ "$1" -lt 7200 ]; then echo "$(($1 / 60)) min"; else echo "$(($1 / 3600)) h"; fi; }

# Off-machine dead-man ping (SECREL-02): is HEALTHCHECK_PING_URL set, and what did the watchdog's last ping do
# (.pids/watchdog/deadman = "<epoch> ok|fail|error", written every run)? Only the URL's host is ever printed.
deadman_status_row() {
  local url host f="$PROJECT_ROOT/.pids/watchdog/deadman" at="" res="" age=""
  url=$(env_file_val HEALTHCHECK_PING_URL)
  if [ -z "$url" ]; then
    printf "%-18s %-6s %-8s %-${HW}b %s\n" "dead-man-ping" "-" "-" "${YELLOW}not set${NC}" \
      "nobody is told when this Mac is off, frozen or waiting at the FileVault screen"
    echo -e "  ${YELLOW}→${NC} set HEALTHCHECK_PING_URL in .env (a free healthchecks.io check):" \
      "docs/RUNBOOK_RESTORE.md 'Off-machine dead-man ping'"
    return 0
  fi
  host=$(printf '%s' "$url" | sed -nE 's#^[A-Za-z]+://([^/:?]+).*#\1#p')
  host=${host:-the ping URL}
  if [ -f "$f" ]; then read -r at res < "$f" || true; fi
  case "$at" in ""|*[!0-9]*) age="" ;; *) age=$(( $(date +%s) - at )) ;; esac
  if [ -z "$age" ]; then
    printf "%-18s %-6s %-8s %-${HW}b %s\n" "dead-man-ping" "-" "-" "${YELLOW}no ping${NC}" \
      "configured ($host), no ping recorded yet: the watchdog pings every 2 min (scripts/install_launch_agents.sh status)"
  elif [ "$age" -gt 600 ]; then
    printf "%-18s %-6s %-8s %-${HW}b %s\n" "dead-man-ping" "-" "-" "${YELLOW}stale${NC}" \
      "last ping to $host $(ago "$age") ago: the watchdog has not run since (scripts/install_launch_agents.sh status)"
  else
    case "$res" in
      ok)   printf "%-18s %-6s %-8s %-${HW}b %s\n" "dead-man-ping" "-" "-" "${GREEN}ok${NC}" \
              "$host pinged $(ago "$age") ago (stack healthy)" ;;
      fail) printf "%-18s %-6s %-8s %-${HW}b %s\n" "dead-man-ping" "-" "-" "${YELLOW}fail sent${NC}" \
              "$host was told $(ago "$age") ago that the stack is unhealthy" ;;
      *)    printf "%-18s %-6s %-8s %-${HW}b %s\n" "dead-man-ping" "-" "-" "${RED}failing${NC}" \
              "the last ping to $host failed $(ago "$age") ago (no network, or a wrong URL: RUNBOOK step 5)" ;;
    esac
  fi
  return 0
}

# Unattended reboots (completeness-final-04): whether the 24x7 stack comes back on its own after a power cut or an
# overnight macOS update. Read-only: pmset -g, defaults read, fdesetup status (no sudo).
reboot_recovery_row() {
  local ar ai fv a i v warn=0
  ar=$(pmset -g 2> /dev/null | awk '$1 == "autorestart" { print $2; exit }')
  ai=$(defaults read /Library/Preferences/com.apple.SoftwareUpdate AutomaticallyInstallMacOSUpdates 2> /dev/null || true)
  fv=$(fdesetup status 2> /dev/null | head -1 || true)
  case "$ar" in 1) a=on ;; 0) a=off; warn=1 ;; *) a="n/a" ;; esac
  case "$ai" in 0) i=off ;; 1) i=on; warn=1 ;; *) i=unknown ;; esac
  case "$fv" in *"is On"*) v="on: after any reboot nothing runs until you log in" ;; *"is Off"*) v=off ;; *) v=unknown ;; esac
  if [ "$warn" = 1 ]; then
    printf "%-18s %-6s %-8s %-${HW}b %s\n" "reboot-recovery" "-" "-" "${YELLOW}check${NC}" \
      "power-on after a power failure: $a · automatic macOS installs: $i · FileVault: $v"
    echo -e "  ${YELLOW}→${NC} docs/RUNBOOK_RESTORE.md 'Unattended reboots' (sudo pmset -a autorestart 1; install macOS" \
      "updates by hand on a weekend)"
  else
    printf "%-18s %-6s %-8s %-${HW}b %s\n" "reboot-recovery" "-" "-" "${GREEN}ok${NC}" \
      "power-on after a power failure: $a · automatic macOS installs: $i · FileVault: $v"
  fi
  return 0
}

# service_row <name> <port> <url> — one service's row. A listener whose /health gives no HTTP answer within 5 s is
# shown as 'no answer' (hung), with no latency: R-OPS-10, the row used to print 'HTTP 000' and '<time>000 -s'.
service_row() {
  local name=$1 port=$2 url=$3 pid out code t
  pid=$(lsof -tiTCP:"$port" -sTCP:LISTEN 2> /dev/null | head -1)
  if [ -n "$pid" ]; then
    out=$(curl -s -o /dev/null -m 5 -w '%{http_code} %{time_total}' "$url" 2> /dev/null; true)
    read -r code t <<< "$out" || true
    code=${code:-000}
    if [ "$code" = "200" ]; then
      if [ "$name" = "ui-api" ]; then UI_API_UP=1; fi
      printf "%-18s %-6s %-8s %-${HW}b %ss\n" "$name" "$port" "$pid" "${GREEN}up${NC}" "$t"
    elif [ "$code" = "000" ]; then
      printf "%-18s %-6s %-8s %-${HW}b %s\n" "$name" "$port" "$pid" "${RED}no answer${NC}" \
        "listening, but no answer in 5 s: hung? (the watchdog restarts a hung core service after about 3.5–5.5 min)"
    else
      printf "%-18s %-6s %-8s %-${HW}b %ss\n" "$name" "$port" "$pid" "${RED}HTTP $code${NC}" "$t"
    fi
  elif [ "$name" = "frontend" ]; then
    printf "%-18s %-6s %-8s %-${HW}b %s\n" "$name" "$port" "-" "${YELLOW}off${NC}" "(optional dev UI)"
  else
    printf "%-18s %-6s %-8s %-${HW}b %s\n" "$name" "$port" "-" "${RED}down${NC}" "-"
  fi
  return 0
}

status_services() {
  print_header "Service Status"
  printf "%-18s %-6s %-8s %-10s %s\n" "SERVICE" "PORT" "PID" "HEALTH" "LATENCY"
  local name port url
  UI_API_UP=0   # the rows below ask ui-api only when this probe saw it healthy
  for name in $ALL_SERVICES; do
    port=$(svc_port "$name")
    # 127.0.0.1, the address every service binds (localhost tries ::1 first, where another program could answer)
    if [ "$name" = "frontend" ]; then url="http://127.0.0.1:$port"; else url="http://127.0.0.1:$port/health"; fi
    service_row "$name" "$port" "$url"
  done
  ui_release_row
  if lsof -iTCP:6379 -sTCP:LISTEN > /dev/null 2>&1; then
    printf "%-18s %-6s %-8s %-${HW}b\n" "redis" "6379" "$(lsof -tiTCP:6379 -sTCP:LISTEN | head -1)" "${GREEN}up${NC}"
  else
    printf "%-18s %-6s %-8s %-${HW}b\n" "redis" "6379" "-" "${YELLOW}off${NC}"
  fi
  prefs_status_row
  app_status_row
  deadman_status_row
  reboot_recovery_row
}

show_help() {
  cat <<EOF
SuryaDhana AI — local stack (no Docker)

Usage: ./start-local.sh [command] [service]

  (none) | start            Start the core stack: data-service, ui-api, master-controller
                            (the terminal is http://127.0.0.1:8010, served by ui-api)
  start frontend            Optional: the Next dev UI on :3000 (hot reload; UI_MODE=prod: old Next build)
  start legacy              Start the dormant 5-day-era services (ml, feature, rl)
  build-ui [args]           Build + atomically publish the terminal UI (scripts/build_ui.sh: --help,
                            --rollback [<id>], --list, --out <dir>). Live on the next request, no restart
  stop                      Stop every service (graceful; data-service last). Stopped services are
                            marked paused: the watchdog leaves them alone until you start them again
  restart                   Stop everything, then start everything
  status                    Port, PID, health and latency of each service ('no answer' = listening but hung),
                            the UI release (ui/dist/current and the one ui-api serves, warns when they differ),
                            the settings store (prefs: imported from the browser terminal yet?), the desktop app
                            (and whether launchd supervises it), the off-machine dead-man ping and whether the
                            Mac recovers from reboots unattended. Read-only
  start   <service>         Start one service
  stop    <service>         Stop one service
  restart <service>         Restart one service (e.g. after a code change)
  logs    <service>         Follow one service's log (Ctrl+C to exit)
  rotate-logs               Rotate every .logs/*.log over LOG_MAX_BYTES (20 MB; keeps .1-.3). The watchdog
                            runs it hourly; every start also rotates that service's log, then appends to it
  help                      This help

Services: $ALL_SERVICES

UI build: ./start-local.sh build-ui                         publish a new terminal UI release (~15 s)
UI mode:  UI_MODE=prod ./start-local.sh restart frontend   optional old Next prod build on :3000 (no hot reload)
Reload:   UI_API_RELOAD=1 ./start-local.sh restart ui-api   hot reload while editing ui-api (off by default)
          ./start-local.sh restart frontend                 dev server with hot reload (default)
EOF
}

# ─────────────────────────────────────────────────────────────────────────────

main() {
  mkdir -p "$PROJECT_ROOT/.logs" "$PROJECT_ROOT/.pids"
  local cmd="${1:-start}" svc="${2:-}"

  case "$cmd" in
    start)
      # the same default start_services uses (${START_SET:-$CORE_SERVICES}), so the Node checks see the real set
      local start_set="${START_SET:-$CORE_SERVICES}"
      if [ "$svc" = "legacy" ]; then start_set="$LEGACY_SERVICES"
      elif [ -n "$svc" ]; then require_service "$svc"; start_set="$svc"; fi
      check_prerequisites "$start_set"
      install_deps "$start_set"
      if [ "$svc" = "legacy" ]; then START_SET="$LEGACY_SERVICES" start_services
      elif [ -n "$svc" ]; then clear_paused "$svc"; clear_hang_history "$svc"; start_redis; start_one "$svc"
      else start_services; fi
      ;;
    stop)
      if [ -n "$svc" ]; then require_service "$svc"; refuse_in_freeze stop "$svc"; mark_paused "$svc"; stop_one "$svc"
      else
        # F7-03 / F8-01 / F9-06: the bare form stops BOTH frozen services and was once refused by nothing —
        # it would have left data-service and master-controller down AND paused through the 08:00 ICICI login.
        # The guard asks about exactly the set stop_services will stop: $ALL_SERVICES normally, or $START_SET
        # when it is set, which stop_services now honours too. Those two reading the same variable is the
        # point — F8-01 happened because the guard was asked about one set while a different set went down.
        refuse_in_freeze_set stop "${START_SET:-$ALL_SERVICES}"
        stop_services
      fi
      ;;
    restart)
      if [ -n "$svc" ]; then
        require_service "$svc"; refuse_in_freeze restart "$svc"
        stop_one "$svc"; clear_paused "$svc"; clear_hang_history "$svc"; start_redis; start_one "$svc"
      else
        # F7-03 / F8-01 / F9-06: `restart` calls stop_services() first, so the window is asked about what
        # goes DOWN ($START_SET when set, else $ALL_SERVICES) — not the narrower set that comes back up
        # (bare `restart` deliberately restarts only the 3 core services).
        # the window is asked about exactly what goes down, which for `restart` is what comes back up
        refuse_in_freeze_set restart "${START_SET:-$CORE_SERVICES}"
        stop_services "${START_SET:-$CORE_SERVICES}"
        check_prerequisites "${START_SET:-$CORE_SERVICES}"
        install_deps "${START_SET:-$CORE_SERVICES}"
        start_services
      fi
      ;;
    status)
      status_services
      ;;
    rotate-logs)
      rotate_all_logs
      ;;
    build-ui)
      shift
      exec "$PROJECT_ROOT/scripts/build_ui.sh" "$@"
      ;;
    logs)
      require_service "${svc:-}"
      exec tail -n 50 -F "$PROJECT_ROOT/.logs/$svc.log"   # -F: keeps following across a rotation
      ;;
    help|-h|--help)
      show_help
      ;;
    *)
      print_error "Unknown command: $cmd"
      show_help
      exit 1
      ;;
  esac
}

# Run main only when executed (tests source this file for its functions). One line, so bash never reads past it
# while main runs, even if the file were replaced (C2-reliability-ops-01).
if [ "${BASH_SOURCE[0]}" = "$0" ]; then main "$@"; exit $?; fi
