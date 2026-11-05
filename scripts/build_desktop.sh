#!/bin/bash
# Build, sign (ad-hoc), install and self-test SuryaDhana.app (the Tauri v2 desktop shell in desktop/).
#
#   scripts/build_desktop.sh                  build desktop/src-tauri/target/release/bundle/macos/SuryaDhana.app
#   scripts/build_desktop.sh --install        … then install it (/Applications if writable, else ~/Applications),
#                                              quitting the installed SuryaDhana first; the copy it replaces is KEPT
#                                              for --rollback; an existing Launch-at-Login entry is rewritten for the
#                                              installed copy (KeepAlive format) and its stale launchd job unloaded
#   scripts/build_desktop.sh --install --relaunch   … and start the installed app again: THROUGH launchd when
#                                              Launch at Login is on (crash relaunch in force at once), else `open`
#   scripts/build_desktop.sh --rollback [--relaunch]   swap the installed app with the kept previous copy (again
#                                              = roll forward); same login-item handling as --install
#   scripts/build_desktop.sh --test           … then run the app with --self-test and print the JSON summary
#                                              (with --install: the BUILT bundle, BEFORE it is installed; a failed
#                                              self-test installs nothing (FEATURE_PARITY R1). With --rollback: the
#                                              rolled-back copy. Otherwise the built bundle, else the installed one)
#   scripts/build_desktop.sh --no-build --test     self-test an existing build without rebuilding
#   scripts/build_desktop.sh --out <file>     where --test writes the self-test JSON
#                                              (default: desktop/src-tauri/target/selftest.json)
#   scripts/build_desktop.sh --install --force     install even a build whose id ends in -devtools / -debug
#                                              (Web Inspector on the IPC-granted origin: never for daily use)
#
# What it does:
#   1. checks the toolchain (node/npm, rustc/cargo, Xcode command-line tools: codesign, xcrun);
#   2. `npm ci` in desktop/ (exact @tauri-apps/cli pin from package-lock.json);
#   3. bakes SURYADHANA_ROOT (this repo), SURYADHANA_GIT_SHA (git sha7) and SURYADHANA_BUILD_TIME into the
#      binary: its build id is <sha7>[-dirty]-<source hash>-<UTC time> (About, menu-bar item, shell_info,
#      `SuryaDhana --version`), and CFBundleVersion is the same UTC time (yyyymmddHHMM, monotonic);
#   4. `npx tauri build --bundles app` (signingIdentity "-" in tauri.conf.json = ad-hoc signature);
#   5. `codesign --verify --deep --strict`, reports the bundle size (target < 25 MB) and the build id.
#
# Crash relaunch: the copy launchd starts (Launch at Login, or --relaunch here) is relaunched by launchd's
# KeepAlive; a copy opened by hand (Dock / Finder after ⌘Q) runs a small crash guard that asks launchd to start
# the app again if it ends without a clean exit (desktop/src-tauri/src/supervise.rs). The menu-bar item says
# which applies ("Relaunch after a crash: …").
#
# Rollback: the replaced app is kept as ~/Library/Application Support/ai.suryadhana.terminal/previous/
# SuryaDhana.app.previous (renamed so macOS does not register it as a second SuryaDhana), with its build id in
# previous/BUILD; the installed build id is in …/installed-build. One previous copy is kept.
#
# Environment:
#   SURYADHANA_UI_URL=http://127.0.0.1:<port>   passed through to --test (point the app at a scratch UI server)
#   SURYADHANA_STARTUP_GRACE_S=<s>              passed through to --test (boot-page start-up grace, 0..900)
#   SELFTEST_ARGS=--autostart                   extra app argument for --test (only --autostart: login-start mode)
#   SELFTEST_TIMEOUT=75                         seconds before a hung self-test is killed
#   SURYADHANA_INSTALL_DIR=<dir>                install into <dir> instead of /Applications (drills, tests)
#
# Safety: the self-test never starts/stops the stack, never sends Telegram, never toggles Launch at Login,
# takes no single-instance lock (safe while the installed app runs), and keeps its window/session state and its
# app log in a temp dir (the log is copied to <out>.app.log). Install / rollback quit only the copy at the
# install path (by pid, Apple Event then SIGTERM; never a kill -9). This script never touches the live stack.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DESKTOP="$ROOT/desktop"
TAURI_DIR="$DESKTOP/src-tauri"
BUNDLE="$TAURI_DIR/target/release/bundle/macos/SuryaDhana.app"
APP_ID="ai.suryadhana.terminal"
SIZE_TARGET_MB=25
STATE_DIR="$HOME/Library/Application Support/$APP_ID"
PREV_DIR="$STATE_DIR/previous"
PREV_APP="$PREV_DIR/SuryaDhana.app.previous"
LOGIN_PLIST="$HOME/Library/LaunchAgents/SuryaDhana.plist"

DO_BUILD=1; DO_INSTALL=0; DO_TEST=0; RELAUNCH=0; DO_ROLLBACK=0; FORCE=0
INSTALL_TMP=""
OUT="$TAURI_DIR/target/selftest.json"

usage() { sed -n '2,/^set -euo pipefail/p' "$0" | sed '$d' | sed 's/^# \{0,1\}//'; }
while [ $# -gt 0 ]; do
  case "$1" in
    --install) DO_INSTALL=1 ;;
    --rollback) DO_ROLLBACK=1; DO_BUILD=0 ;;
    --relaunch) RELAUNCH=1 ;;
    --test) DO_TEST=1 ;;
    --no-build) DO_BUILD=0 ;;
    --force) FORCE=1 ;;
    --out) shift; OUT="${1:?--out needs a path}" ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
[ "$DO_ROLLBACK" = 1 ] && [ "$DO_INSTALL" = 1 ] && { echo "--rollback and --install exclude each other" >&2; exit 2; }

say()  { printf '\033[1;33m==>\033[0m %s\n' "$*"; }
ok()   { printf '\033[1;32m ok\033[0m %s\n' "$*"; }
warn() { printf '\033[1;31m!!\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mERR\033[0m %s\n' "$*" >&2; exit 1; }

exe_of() { echo "$1/Contents/MacOS/$(/usr/libexec/PlistBuddy -c 'Print :CFBundleExecutable' "$1/Contents/Info.plist")"; }
# run_timeout <seconds> <command…>: a bash-native time limit (R-RUST-09: GNU `timeout` is Homebrew coreutils,
# not part of macOS; without it the graceful Apple-Event quit silently never ran)
run_timeout() {
  local limit="$1" pid killer rc=0
  shift
  "$@" &
  pid=$!
  ( sleep "$limit"; kill -TERM "$pid" 2> /dev/null ) &
  killer=$!
  wait "$pid" || rc=$?
  kill "$killer" 2> /dev/null || true
  wait "$killer" 2> /dev/null || true
  return "$rc"
}
# a temp bundle being installed is removed on any exit (R-RUST-09: a failed quit left a hidden 8 MB bundle in
# /Applications that LaunchServices may register)
trap 'if [ -n "$INSTALL_TMP" ]; then rm -rf "$INSTALL_TMP"; fi' EXIT
# The build id of a bundle made by this script (it answers --version without opening a window). An older
# bundle (before wave 2) would start the full app on an unknown flag, so it is never asked: its id comes from
# the install record, else its Info.plist and executable hash.
build_id_of() {
  local app="$1" exe
  exe="$(exe_of "$app")"
  if grep -q -a -F -- '--login-item-sync' "$exe" 2> /dev/null; then
    "$exe" --version 2> /dev/null | head -1
  else
    echo "SuryaDhana $(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$app/Contents/Info.plist" 2> /dev/null) (pre-wave-2 build, sha256 $(shasum -a 256 "$exe" | cut -c1-12))"
  fi
}
write_record() { # <file> <text>: temp + rename
  mkdir -p "$(dirname "$1")"
  printf '%s\n' "$2" > "$1.tmp.$$" && mv "$1.tmp.$$" "$1"
}

check_toolchain() {
  say "Toolchain"
  [ "$(uname -s)" = "Darwin" ] || die "macOS only"
  for t in node npm cargo rustc xcrun codesign git; do
    command -v "$t" > /dev/null 2>&1 || die "missing $t (install Node ≥ 20, Rust via rustup, and: xcode-select --install)"
  done
  xcode-select -p > /dev/null 2>&1 || die "Xcode command-line tools not installed (xcode-select --install)"
  ok "node $(node --version) · npm $(npm --version) · $(rustc --version | cut -d' ' -f1-2) · $(cargo --version | cut -d' ' -f1-2)"
}

build() {
  say "npm ci (desktop/)"
  (cd "$DESKTOP" && npm ci --no-audit --no-fund --loglevel=error)
  ok "$(cd "$DESKTOP" && npx tauri --version)"

  local sha epoch bundle_version
  sha="$(git -C "$ROOT" rev-parse --short=7 HEAD 2> /dev/null || echo unknown)"
  epoch="$(date -u +%s)"
  bundle_version="$(date -u -r "$epoch" +%Y%m%d%H%M)"
  say "Building SuryaDhana.app (repo $ROOT, git $sha, CFBundleVersion $bundle_version)"
  (cd "$DESKTOP" && SURYADHANA_ROOT="$ROOT" SURYADHANA_GIT_SHA="$sha" SURYADHANA_BUILD_TIME="$epoch" \
    npx tauri build --bundles app --config "{\"bundle\":{\"macOS\":{\"bundleVersion\":\"$bundle_version\"}}}")
  [ -d "$BUNDLE" ] || die "bundle not produced: $BUNDLE"
  ok "built $BUNDLE"
}

verify() {
  local app="$1"
  say "Signature"
  codesign --verify --deep --strict "$app" || die "codesign --verify failed for $app"
  local sig
  sig="$(codesign -dv "$app" 2>&1 | grep -E '^(Identifier|Signature|TeamIdentifier)=' | tr '\n' ' ')"
  ok "codesign --verify --deep --strict passed · $sig"
  local kb mb
  kb="$(du -sk "$app" | cut -f1)"
  mb="$(awk -v k="$kb" 'BEGIN { printf "%.1f", k / 1024 }')"
  if [ "$kb" -lt $((SIZE_TARGET_MB * 1024)) ]; then ok "bundle size ${mb} MB (target < ${SIZE_TARGET_MB} MB)"
  else warn "bundle size $mb MB exceeds the $SIZE_TARGET_MB MB target"; fi
  ok "build id: $(build_id_of "$app") · CFBundleVersion $(/usr/libexec/PlistBuddy -c 'Print :CFBundleVersion' "$app/Contents/Info.plist")"
}

# Quit the SuryaDhana running FROM <app> only (never another copy, never by bundle id): the standard quit Apple
# Event to that pid (NSRunningApplication -terminate, ⌘Q's path), then SIGTERM, which the app treats as Quit.
quit_copy() {
  local exe pids p i
  exe="$(exe_of "$1")"
  pids="$(pgrep -f -- "^$exe" 2> /dev/null || true)"
  [ -n "$pids" ] || return 0
  say "Quitting the SuryaDhana running from $1 (pid $(echo $pids))"
  for p in $pids; do
    run_timeout 20 osascript -l JavaScript -e "ObjC.import('AppKit'); var a = \$.NSRunningApplication.runningApplicationWithProcessIdentifier($p); (a && !a.isNil()) ? String(typeof a.terminate === 'function' ? a.terminate() : a.terminate) : 'gone'" > /dev/null 2>&1 || true
  done
  for i in $(seq 1 40); do pgrep -f -- "^$exe" > /dev/null 2>&1 || break; sleep 0.25; done
  if pgrep -f -- "^$exe" > /dev/null 2>&1; then
    pkill -TERM -f -- "^$exe" 2> /dev/null || true
    for i in $(seq 1 40); do pgrep -f -- "^$exe" > /dev/null 2>&1 || break; sleep 0.25; done
  fi
  pgrep -f -- "^$exe" > /dev/null 2>&1 && die "SuryaDhana ($1) is still running; quit it (⌘Q) and retry"
  ok "quit"
}

install_dir() {
  local d="${SURYADHANA_INSTALL_DIR:-/Applications}"
  if [ -z "${SURYADHANA_INSTALL_DIR:-}" ] && [ ! -w "$d" ]; then d="$HOME/Applications"; fi
  mkdir -p "$d"
  echo "$d"
}

install_app() {
  local dest_dir dest tmp new_id old_id
  dest_dir="$(install_dir)"
  dest="$dest_dir/SuryaDhana.app"
  tmp="$dest_dir/.SuryaDhana.app.installing.$$"
  new_id="$(build_id_of "$BUNDLE")"
  # R-RUST-08: a devtools / debug build (Web Inspector on the IPC-granted origin) is never installed by accident
  case "$new_id" in
    *-devtools*|*-debug*) [ "$FORCE" = 1 ] || die "refusing to install $new_id: a devtools / debug build (use --force for a local debugging copy)" ;;
  esac
  rm -rf "$tmp"
  INSTALL_TMP="$tmp"
  ditto "$BUNDLE" "$tmp"
  codesign --verify --deep --strict "$tmp" || { rm -rf "$tmp"; die "the copy to install fails codesign --verify"; }
  [ -d "$dest" ] && quit_copy "$dest"
  say "Installing to $dest"
  if [ -d "$dest" ]; then
    old_id="$(cat "$STATE_DIR/installed-build" 2> /dev/null || build_id_of "$dest")"
    mkdir -p "$PREV_DIR"
    rm -rf "$PREV_APP.old"
    [ -d "$PREV_APP" ] && mv "$PREV_APP" "$PREV_APP.old"
    if ! mv "$dest" "$PREV_APP"; then
      [ -d "$PREV_APP.old" ] && mv "$PREV_APP.old" "$PREV_APP"
      rm -rf "$tmp"; die "could not move the installed app aside; nothing changed"
    fi
    if ! mv "$tmp" "$dest"; then
      mv "$PREV_APP" "$dest"; [ -d "$PREV_APP.old" ] && mv "$PREV_APP.old" "$PREV_APP"
      die "could not install; the previous app is back in place"
    fi
    rm -rf "$PREV_APP.old"
    write_record "$PREV_DIR/BUILD" "$old_id"
    ok "kept the previous app for --rollback: $old_id"
  else
    mv "$tmp" "$dest"
  fi
  INSTALL_TMP=""
  codesign --verify --deep --strict "$dest" || die "installed copy fails codesign --verify"
  write_record "$STATE_DIR/installed-build" "$new_id"
  ok "installed $dest · $new_id"
  INSTALLED="$dest"
  login_item_sync "$dest" 0
}

rollback_app() {
  local dest_dir dest tmp cur_id prev_id
  dest_dir="$(install_dir)"
  dest="$dest_dir/SuryaDhana.app"
  [ -d "$PREV_APP" ] || die "no previous app kept in $PREV_DIR (nothing to roll back to)"
  [ -d "$dest" ] || die "no installed app at $dest"
  codesign --verify --deep --strict "$PREV_APP" || die "the kept previous app fails codesign --verify; not rolling back"
  cur_id="$(cat "$STATE_DIR/installed-build" 2> /dev/null || build_id_of "$dest")"
  prev_id="$(cat "$PREV_DIR/BUILD" 2> /dev/null || build_id_of "$PREV_APP")"
  quit_copy "$dest"
  say "Rolling back $dest: $cur_id -> $prev_id"
  tmp="$dest_dir/.SuryaDhana.app.rollback.$$"
  mv "$dest" "$tmp"
  if ! mv "$PREV_APP" "$dest"; then mv "$tmp" "$dest"; die "could not move the previous app in; nothing changed"; fi
  mv "$tmp" "$PREV_APP"
  write_record "$STATE_DIR/installed-build" "$prev_id"
  write_record "$PREV_DIR/BUILD" "$cur_id"
  codesign --verify --deep --strict "$dest" || die "the rolled-back copy fails codesign --verify"
  ok "rolled back; --rollback again rolls forward to $cur_id"
  INSTALLED="$dest"
  login_item_sync "$dest" 0
}

# An existing Launch-at-Login entry is rewritten by the INSTALLED copy itself (`--login-item-sync`: one source
# of truth for the plist format, KeepAlive etc.) and its stale launchd job is unloaded; `start`=1 also loads
# it, which starts the app under launchd now (crash relaunch in force at once). A pre-wave-2 copy (rollback
# target) does not know the flag: its entry is repointed with plutil (temp file + rename) instead. No entry =
# Launch at Login is off: left off.
login_item_sync() {
  local app="$1" start="$2" exe cur tmp
  [ -f "$LOGIN_PLIST" ] || { ok "Launch at Login is off: no login item to update"; return 0; }
  exe="$(exe_of "$app")"
  if grep -q -a -F -- '--login-item-sync' "$exe" 2> /dev/null; then
    if [ "$start" = 1 ]; then "$exe" --login-item-sync --start; else "$exe" --login-item-sync; fi \
      && ok "Launch at Login entry synced to $exe" || warn "login item sync failed (see above)"
    return 0
  fi
  cur="$(plutil -extract ProgramArguments.0 raw -o - "$LOGIN_PLIST" 2> /dev/null || true)"
  if [ "$cur" != "$exe" ]; then
    tmp="$LOGIN_PLIST.tmp.$$"
    cp "$LOGIN_PLIST" "$tmp" && plutil -replace ProgramArguments.0 -string "$exe" "$tmp" && plutil -lint "$tmp" > /dev/null \
      && mv "$tmp" "$LOGIN_PLIST" && ok "Launch at Login now starts $exe (was ${cur:-unreadable})" \
      || { rm -f "$tmp"; warn "could not repoint $LOGIN_PLIST"; }
  fi
  if [ "$start" = 1 ] && [ "$app" = "/Applications/SuryaDhana.app" -o "$app" = "$HOME/Applications/SuryaDhana.app" ]; then
    launchctl bootout "gui/$(id -u)/SuryaDhana" 2> /dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$LOGIN_PLIST" && ok "started under launchd"
  fi
}

run_selftest() {
  local app="$1"
  local exe
  exe="$(exe_of "$app")"
  [ -x "$exe" ] || die "no executable in $app"
  mkdir -p "$(dirname "$OUT")"
  rm -f "$OUT"
  say "Self-test: $app ${SURYADHANA_UI_URL:+(ui $SURYADHANA_UI_URL)}"
  local t0 rc=0 pid timeout_s="${SELFTEST_TIMEOUT:-75}" extra=()
  case "${SELFTEST_ARGS:-}" in
    "") ;;
    --autostart) extra=(--autostart) ;;
    *) die "SELFTEST_ARGS may only be --autostart" ;;
  esac
  t0=$(date +%s)
  SURYADHANA_NO_AUTOSTART=1 "$exe" --self-test "$OUT" ${extra[@]+"${extra[@]}"} > "$OUT.log" 2>&1 &
  pid=$!
  ( sleep "$timeout_s"; kill -9 "$pid" 2> /dev/null ) &
  local killer=$!
  wait "$pid" || rc=$?
  kill "$killer" 2> /dev/null || true
  wait "$killer" 2> /dev/null || true
  echo "    exit code $rc after $(( $(date +%s) - t0 )) s · log $OUT.log · app log $OUT.app.log"
  [ -f "$OUT" ] || die "no self-test report written ($OUT)"
  node -e '
    const r = require(process.argv[1]);
    for (const c of r.checks) {
      const ms = c.ms == null ? "" : ` (${Math.round(c.ms)} ms)`;
      const tag = c.skipped ? "\x1b[33mSKIP\x1b[0m" : c.ok ? "\x1b[32mPASS\x1b[0m" : "\x1b[31mFAIL\x1b[0m";
      console.log(`    ${tag} ${c.name}${ms}: ${c.detail}`);
    }
    const n = r.checks.filter(c => c.ok && !c.skipped).length;
    const sk = r.checks.filter(c => c.skipped).length;
    console.log(`    ${r.passed ? "\x1b[1;32mPASSED\x1b[0m" : "\x1b[1;31mFAILED\x1b[0m"} ${n}/${r.checks.length} checks passed${sk ? `, ${sk} skipped (not measurable here)` : ""} · build ${r.meta && r.meta.build_id} · report ${process.argv[1]}`);
  ' "$OUT"
  return "$rc"
}

check_toolchain
INSTALLED=""
if [ "$DO_BUILD" = 1 ]; then build; else [ -d "$BUNDLE" ] || [ "$DO_INSTALL" = 0 ] || die "no build at $BUNDLE (drop --no-build)"; fi
if [ -d "$BUNDLE" ] && [ "$DO_ROLLBACK" = 0 ]; then verify "$BUNDLE"; fi

RC=0
if [ "$DO_TEST" = 1 ] && [ "$DO_INSTALL" = 1 ]; then
  # R1 (round 4b): self-test the build BEFORE it replaces the installed app (the installed copy keeps running:
  # the self-test takes no single-instance lock); a failing build is never installed
  run_selftest "$BUNDLE" || die "self-test FAILED: $BUNDLE was NOT installed; the installed app is unchanged (report $OUT)"
  ok "self-test passed: installing the tested build"
fi
if [ "$DO_INSTALL" = 1 ]; then install_app; fi
if [ "$DO_ROLLBACK" = 1 ]; then rollback_app; fi

if [ "$DO_TEST" = 1 ] && [ "$DO_INSTALL" = 0 ]; then
  TARGET="${INSTALLED:-$BUNDLE}"
  if [ "$DO_INSTALL" = 0 ] && [ ! -d "$TARGET" ]; then
    for c in /Applications/SuryaDhana.app "$HOME/Applications/SuryaDhana.app"; do [ -d "$c" ] && TARGET="$c" && break; done
  fi
  [ -d "$TARGET" ] || die "nothing to test"
  run_selftest "$TARGET" || RC=$?
fi

if [ "$RELAUNCH" = 1 ] && [ -n "$INSTALLED" ]; then
  if [ -f "$LOGIN_PLIST" ]; then
    say "Starting $INSTALLED through launchd (Launch at Login is on: crash relaunch in force now)"
    login_item_sync "$INSTALLED" 1
  else
    say "Relaunching $INSTALLED"
    open -a "$INSTALLED"
  fi
fi
exit "$RC"
