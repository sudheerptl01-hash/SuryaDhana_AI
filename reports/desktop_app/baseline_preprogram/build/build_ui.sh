#!/bin/bash
# SuryaDhana UI release builder: static export of the Next.js terminal, served by ui-api on :8010.
#
# Usage:
#   scripts/build_ui.sh                    build a release into ui/dist/releases/<id>/ and atomically make it current
#   scripts/build_ui.sh --out <dir>        standalone export into <dir> (no release, no swap; scratch builds)
#   scripts/build_ui.sh --rollback [<id>]  make the newest release older than current (or <id>) current
#   scripts/build_ui.sh --list             releases, current and previous
#   scripts/build_ui.sh --help
# Options:
#   --dist-root <dir>   release root instead of ui/dist (env BUILD_UI_DIST_ROOT); for scratch release flows
#   --keep <n>          releases to keep (default 3, min 2); current and previous are never pruned
#
# What a build does (every failure exits non-zero with a clear message and removes its temp dirs):
#   1. lock      one build at a time (ui/.build-ui/lock; waits up to BUILD_UI_LOCK_TIMEOUT s, default 900;
#                a lock whose pid is gone is taken over)
#   2. id        YYYYmmdd-HHMMSS-<git sha7> in IST (release ids sort chronologically)
#   3. stage     copies the UI sources into ui/.build-ui/staging-<id>/ and builds THERE with
#                NEXT_OUTPUT=export. Why a copy: Next's export mode always writes its intermediate build
#                to <project>/.next (with a custom distDir it even redirects the intermediate there), which
#                would clobber the dev server's ui/.next. Building in a copy means ui/.next, ui/.next-prod,
#                ui/tsconfig.json and ui/next-env.d.ts are never written (Next rewrites the COPY's tsconfig
#                include and next-env.d.ts). Both files are snapshotted before the build; a rewrite that
#                points at the staging dir is restored, any other concurrent edit is left alone.
#   4. verify    index.html, _next/static with JS chunks, every asset index.html references, no api/ path
#   5. gzip      <file>.gz siblings for text assets > 1 KB (node zlib level 9, deterministic)
#   6. carry     _next/static files from the previous 2 releases that the new one lacks are copied in
#                (never overwritten), so an open window can still lazy-load the chunks of its own build
#   7. info      build-info.json {id, git_sha, built_at, files, bytes, next_version, ...}
#   8. swap      releases/.incoming-<id> -> releases/<id> (rename), previous := current, current := <id>,
#                each a rename(2) of a temp symlink over the old one (atomic; never `mv` onto a dir link)
#   9. prune     keep the newest --keep releases plus current and previous
# --rollback also copies the outgoing release's missing _next/static files into the target (add-only), so
# windows still running the newer build keep lazy-loading their per-tab chunks.
#
# ui-api resolves ui/dist/current on every request, so a swap is live without a restart.
# The release id is baked into the bundle as NEXT_PUBLIC_UI_BUILD (ui/next.config.js export mode).
# Exit codes: 0 ok · 1 build/verify/swap failure · 2 usage · 3 lock timeout.
# Test hooks (ui/scripts/build_ui.test.mjs): BUILD_UI_NEXT_BIN (a stand-in `next`), BUILD_UI_RELEASE_ID
# (a fixed id, must match YYYYmmdd-HHMMSS-<7 hex>).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UI_DIR="$ROOT/ui"
WORK_DIR="$UI_DIR/.build-ui"
LOCK_DIR="$WORK_DIR/lock"
RELEASE_JS="$UI_DIR/scripts/release.mjs"
LOG_DIR="$ROOT/.logs"
BUILD_LOG="$LOG_DIR/build-ui.log"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"   # launchd / minimal shells

MODE="release"; OUT_DIR=""; ROLLBACK_ID=""; KEEP=3
DIST_ROOT="${BUILD_UI_DIST_ROOT:-$UI_DIR/dist}"
LOCK_TIMEOUT="${BUILD_UI_LOCK_TIMEOUT:-900}"

STAGING=""; INCOMING=""; OUT_TMP=""; HAVE_LOCK=0; SNAP_DIR=""

ts()   { TZ=Asia/Kolkata date "+%H:%M:%S"; }
say()  { echo "[build_ui $(ts)] $*"; }
die()  { echo "[build_ui $(ts)] ERROR: $*" >&2; exit 1; }
usage() { sed -n '2,/^set -euo pipefail/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; }
now_ms() { node -e 'process.stdout.write(String(Date.now()))'; }
json_get() { node -e 'const o=JSON.parse(process.argv[1]);const v=process.argv[2].split(".").reduce((a,k)=>a==null?a:a[k],o);process.stdout.write(v==null?"":Array.isArray(v)?v.join("\n"):String(v))' "$1" "$2"; }
# release.mjs prints exactly one JSON object; empty output is a failure, never "success".
rel() {
  local o
  o="$(node "$RELEASE_JS" "$@")" || return 1
  case "$o" in "{"*) printf '%s' "$o" ;; *) echo "release.mjs $1: unexpected output: ${o:-<empty>}" >&2; return 1 ;; esac
}

cleanup() {
  local rc=$?
  set +e
  [ -n "$STAGING" ] && [ -d "$STAGING" ] && rm -rf "$STAGING"
  [ -n "$INCOMING" ] && [ -d "$INCOMING" ] && rm -rf "$INCOMING"
  [ -n "$OUT_TMP" ] && [ -d "$OUT_TMP" ] && rm -rf "$OUT_TMP"
  restore_protected
  [ -n "$SNAP_DIR" ] && rm -rf "$SNAP_DIR"
  if [ "$HAVE_LOCK" = 1 ]; then rm -rf "$LOCK_DIR"; fi
  rmdir "$WORK_DIR" 2> /dev/null   # only when empty (another run may hold its lock/staging there)
  if [ "$rc" != 0 ]; then
    case "$MODE" in
      out) echo "[build_ui $(ts)] FAILED (exit $rc); temp dirs cleaned, --out dir left as it was" >&2 ;;
      *)   echo "[build_ui $(ts)] FAILED (exit $rc); temp dirs cleaned, $DIST_ROOT/current unchanged" >&2 ;;
    esac
  fi
  exit "$rc"
}
# ── args ───────────────────────────────────────────────────────────────────────────────────────
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --out) [ $# -ge 2 ] || { echo "--out needs a directory" >&2; exit 2; }; MODE="out"; OUT_DIR="$2"; shift 2 ;;
    --rollback)
      MODE="rollback"
      if [ $# -ge 2 ] && [ "${2#--}" = "$2" ]; then ROLLBACK_ID="$2"; shift 2; else shift; fi ;;
    --list) MODE="list"; shift ;;
    --dist-root) [ $# -ge 2 ] || { echo "--dist-root needs a directory" >&2; exit 2; }; DIST_ROOT="$2"; shift 2 ;;
    --keep) [ $# -ge 2 ] || { echo "--keep needs a number" >&2; exit 2; }; KEEP="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
case "$KEEP" in ''|*[!0-9]*) echo "--keep must be a number >= 2" >&2; exit 2 ;; esac
[ "$KEEP" -ge 2 ] || { echo "--keep must be >= 2" >&2; exit 2; }

command -v node > /dev/null 2>&1 || die "node not found on PATH"
[ -f "$RELEASE_JS" ] || die "missing $RELEASE_JS"

# Absolute, normalised path of a (possibly not yet existing) directory.
abspath() { node -e 'process.stdout.write(require("path").resolve(process.argv[1]))' "$1"; }
DIST_ROOT="$(abspath "$DIST_ROOT")"

# Refuse destinations that would destroy something real.
guard_dest() {
  local d="$1" what="$2" bad
  for bad in / "$HOME" "$ROOT" "$UI_DIR" "$UI_DIR/.next" "$UI_DIR/.next-prod" "$UI_DIR/node_modules" \
             "$UI_DIR/app" "$UI_DIR/components" "$UI_DIR/lib" "$UI_DIR/public" "$WORK_DIR"; do
    [ "$d" = "$bad" ] && die "$what must not be $bad"
  done
  case "$d" in
    "$UI_DIR/.next"/*|"$UI_DIR/.next-prod"/*|"$UI_DIR/node_modules"/*|"$WORK_DIR"/*) die "$what must not be inside $UI_DIR/.next*, node_modules or .build-ui" ;;
  esac
}

# ── lock ───────────────────────────────────────────────────────────────────────────────────────
acquire_lock() {
  local waited=0 holder
  # mkdir -p the parent on EVERY attempt: the previous holder's cleanup rmdirs an empty $WORK_DIR, and a
  # waiter that created it only once would then fail `mkdir $LOCK_DIR` forever (holder '?') until timeout.
  while ! { mkdir -p "$WORK_DIR" && mkdir "$LOCK_DIR"; } 2> /dev/null; do
    holder="$(cat "$LOCK_DIR/pid" 2> /dev/null || true)"
    if [ -n "$holder" ] && ! kill -0 "$holder" 2> /dev/null; then
      say "taking over a stale lock (pid $holder is gone)"
      rm -rf "$LOCK_DIR"; continue
    fi
    if [ -z "$holder" ] && [ -n "$(find "$LOCK_DIR" -maxdepth 0 -mmin +2 2> /dev/null)" ]; then
      say "taking over a lock with no pid file (older than 2 min)"
      rm -rf "$LOCK_DIR"; continue
    fi
    if [ "$waited" -ge "$LOCK_TIMEOUT" ]; then
      echo "[build_ui $(ts)] ERROR: another build_ui.sh run (pid ${holder:-?}, $(cat "$LOCK_DIR/what" 2> /dev/null || echo '?')) still holds the lock after ${LOCK_TIMEOUT}s" >&2
      exit 3
    fi
    [ $((waited % 30)) = 0 ] && say "waiting for the build lock (held by pid ${holder:-?}: $(cat "$LOCK_DIR/what" 2> /dev/null || echo '?'))"
    sleep 2; waited=$((waited + 2))
  done
  HAVE_LOCK=1
  echo $$ > "$LOCK_DIR/pid"
  echo "$MODE ${OUT_DIR:-$DIST_ROOT} since $(ts) IST" > "$LOCK_DIR/what"
}

# ── protected files: ui/tsconfig.json + ui/next-env.d.ts must come out byte-identical ────────────
PROTECTED="tsconfig.json next-env.d.ts"
snapshot_protected() {
  SNAP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/build_ui_snap.XXXXXX")"
  local f
  for f in $PROTECTED; do
    if [ -f "$UI_DIR/$f" ]; then cp -p "$UI_DIR/$f" "$SNAP_DIR/$f"; fi
  done
  ls -A "$UI_DIR" | sort > "$SNAP_DIR/.ui-entries"
}
# Restore ONLY a rewrite that points at this build's staging dir (Next's signature: it adds
# <distDir>/types/** to include and re-points next-env.d.ts). Any other change during the build is
# someone's deliberate edit (another agent, the owner): leave it alone, just say so.
restore_protected() {
  [ -n "$SNAP_DIR" ] && [ -d "$SNAP_DIR" ] || return 0
  local f
  for f in $PROTECTED; do
    [ -f "$SNAP_DIR/$f" ] && [ ! -f "$SNAP_DIR/$f.checked" ] || continue
    if ! cmp -s "$SNAP_DIR/$f" "$UI_DIR/$f"; then
      if grep -qE '\.build-ui|staging-[0-9]{8}' "$UI_DIR/$f" 2> /dev/null; then
        cp -p "$SNAP_DIR/$f" "$UI_DIR/$f"
        echo "[build_ui $(ts)] WARNING: the build rewrote ui/$f (staging paths); restored the pre-build copy" >&2
      else
        echo "[build_ui $(ts)] NOTE: ui/$f changed during the build, not by it (no staging paths); left as is" >&2
      fi
    fi
    : > "$SNAP_DIR/$f.checked"
  done
}
check_ui_entries() {
  local now new
  now="$(ls -A "$UI_DIR" | sort)"
  new="$(comm -13 "$SNAP_DIR/.ui-entries" <(echo "$now") | grep -v '^\.build-ui$' | grep -v '^dist$' || true)"
  [ -z "$new" ] || echo "[build_ui $(ts)] WARNING: new entries appeared in ui/ during the build: $(echo $new)" >&2
}

# ── one export build into $STAGING/out ─────────────────────────────────────────────────────────
GIT_SHA=""; GIT_DIRTY=0; RELEASE_ID=""; NEXT_VERSION=""; SOURCE_SHA=""; BUILD_MS=0
make_id() {
  GIT_SHA="$(git -C "$ROOT" rev-parse --short=7 HEAD 2> /dev/null || echo 0000000)"
  [ ${#GIT_SHA} = 7 ] || GIT_SHA="$(printf '%s' "$GIT_SHA" | cut -c1-7)"
  if [ -n "$(git -C "$ROOT" status --porcelain -- ui/app ui/components ui/lib ui/context ui/public 2> /dev/null | head -1)" ]; then GIT_DIRTY=1; fi
  RELEASE_ID="${BUILD_UI_RELEASE_ID:-$(TZ=Asia/Kolkata date +%Y%m%d-%H%M%S)-$GIT_SHA}"
  echo "$RELEASE_ID" | grep -Eq '^[0-9]{8}-[0-9]{6}-[0-9a-f]{7}$' || die "bad release id: $RELEASE_ID"
  NEXT_VERSION="$(node -e 'process.stdout.write(require(process.argv[1]).version)' "$UI_DIR/node_modules/next/package.json" 2> /dev/null || echo unknown)"
}

export_build() {
  local next_bin="${BUILD_UI_NEXT_BIN:-$UI_DIR/node_modules/.bin/next}"
  [ -x "$next_bin" ] || die "next not found at $next_bin (cd ui && npm ci)"
  snapshot_protected
  STAGING="$WORK_DIR/staging-$RELEASE_ID-$$"
  local staged t0 t1
  staged="$(rel stage --src "$UI_DIR" --dest "$STAGING")" || die "staging copy failed"
  SOURCE_SHA="$(json_get "$staged" source_sha256)"
  say "staged $(json_get "$staged" files) source files ($(json_get "$staged" bytes) bytes) into ${STAGING#$ROOT/}"
  mkdir -p "$LOG_DIR"
  say "next build (static export, NEXT_PUBLIC_UI_BUILD=$RELEASE_ID) — log: ${BUILD_LOG#$ROOT/}"
  t0="$(now_ms)"
  if ! (cd "$STAGING" && env -u NEXT_DIST_DIR NEXT_OUTPUT=export NEXT_PUBLIC_UI_BUILD="$RELEASE_ID" \
          NEXT_TELEMETRY_DISABLED=1 "$next_bin" build) > "$BUILD_LOG" 2>&1; then
    echo "----- last 40 lines of ${BUILD_LOG#$ROOT/} -----" >&2
    tail -n 40 "$BUILD_LOG" >&2
    die "next build failed (full log: $BUILD_LOG)"
  fi
  t1="$(now_ms)"; BUILD_MS=$((t1 - t0))
  restore_protected
  check_ui_entries
  [ -d "$STAGING/out" ] || die "next build produced no out/ directory"
  local v; v="$(rel verify --dir "$STAGING/out")" || die "export verification failed"
  say "built in $((BUILD_MS / 1000)).$(( (BUILD_MS % 1000) / 100 ))s · verified $(json_get "$v" files) files ($(json_get "$v" static_files) under _next/static)"
}

human_bytes() { node -e 'const b=+process.argv[1];process.stdout.write(b>1048576?(b/1048576).toFixed(2)+" MB":(b/1024).toFixed(1)+" kB")' "$1"; }

# ── modes ──────────────────────────────────────────────────────────────────────────────────────
mode_list() { rel list --dist "$DIST_ROOT" | node -e '
  const o=JSON.parse(require("fs").readFileSync(0,"utf8"));
  console.log(`dist root: ${o.dist}`); if(!o.releases.length){console.log("  (no releases)");process.exit(0)}
  for(const r of o.releases.slice().reverse()) console.log(`  ${r.current?"current ":r.previous?"previous":"        "}  ${r.id}  ${r.bytes==null?"?":(r.bytes/1048576).toFixed(2)+" MB"}  ${r.built_at||""}`)'; }

mode_rollback() {
  acquire_lock
  local r
  if [ -n "$ROLLBACK_ID" ]; then r="$(rel rollback --dist "$DIST_ROOT" --id "$ROLLBACK_ID")" || die "rollback failed"
  else r="$(rel rollback --dist "$DIST_ROOT")" || die "rollback failed"; fi
  say "rolled back: current = $(json_get "$r" current) (was $(json_get "$r" previous); carried $(json_get "$r" carried_files) newer _next/static files in for open windows); live on the next request, no restart"
}

mode_out() {
  guard_dest "$OUT_DIR" "--out"
  if [ -e "$OUT_DIR" ] && [ -n "$(ls -A "$OUT_DIR" 2> /dev/null)" ] && [ ! -f "$OUT_DIR/build-info.json" ]; then
    die "--out $OUT_DIR exists, is not empty and is not a previous build_ui output (no build-info.json); refusing to replace it"
  fi
  acquire_lock
  make_id
  local t_start; t_start="$(now_ms)"
  export_build
  OUT_TMP="$OUT_DIR.tmp-$$"
  rm -rf "$OUT_TMP"; mkdir -p "$(dirname "$OUT_DIR")"
  # same filesystem → rename; otherwise copy
  mv "$STAGING/out" "$OUT_TMP" 2> /dev/null || cp -R "$STAGING/out" "$OUT_TMP"
  local gz info old=""
  gz="$(rel precompress --dir "$OUT_TMP")" || die "precompress failed"
  info="$(rel build-info --dir "$OUT_TMP" --id "$RELEASE_ID" --git-sha "$GIT_SHA" --next-version "$NEXT_VERSION" \
           --git-dirty "$GIT_DIRTY" --source-sha256 "$SOURCE_SHA" --build-ms "$BUILD_MS")" || die "build-info failed"
  rel verify --dir "$OUT_TMP" > /dev/null || die "final verification failed"
  if [ -e "$OUT_DIR" ]; then old="$OUT_DIR.old-$$"; mv "$OUT_DIR" "$old"; fi
  mv "$OUT_TMP" "$OUT_DIR"; OUT_TMP=""
  [ -n "$old" ] && rm -rf "$old"
  say "OK  --out $OUT_DIR  id=$RELEASE_ID  $(json_get "$info" files) files $(human_bytes "$(json_get "$info" bytes)")" \
      "· gzip $(json_get "$gz" gz_files) files $(human_bytes "$(json_get "$gz" source_bytes)") → $(human_bytes "$(json_get "$gz" gz_bytes)")" \
      "· total $(( ($(now_ms) - t_start) / 1000 ))s"
}

mode_release() {
  guard_dest "$DIST_ROOT" "--dist-root"
  acquire_lock
  make_id
  local t_start; t_start="$(now_ms)"
  mkdir -p "$DIST_ROOT/releases"
  [ ! -e "$DIST_ROOT/releases/$RELEASE_ID" ] || die "release $RELEASE_ID already exists"
  export_build
  INCOMING="$DIST_ROOT/releases/.incoming-$RELEASE_ID-$$"
  mv "$STAGING/out" "$INCOMING" 2> /dev/null || cp -R "$STAGING/out" "$INCOMING"
  local gz cf carried info sw pr
  gz="$(rel precompress --dir "$INCOMING")" || die "precompress failed"
  cf="$(rel carry-forward --dest "$INCOMING" --dist "$DIST_ROOT" --exclude "$RELEASE_ID" --count 2)" || die "carry-forward failed"
  carried="$(json_get "$cf" carried_files)"
  [ -n "$(json_get "$cf" from)" ] && say "carried forward $carried old _next/static files from: $(json_get "$cf" from | tr '\n' ' ')"
  info="$(rel build-info --dir "$INCOMING" --id "$RELEASE_ID" --git-sha "$GIT_SHA" --next-version "$NEXT_VERSION" \
           --git-dirty "$GIT_DIRTY" --source-sha256 "$SOURCE_SHA" --carried "$carried" --build-ms "$BUILD_MS")" || die "build-info failed"
  rel verify --dir "$INCOMING" > /dev/null || die "final verification failed"
  mv "$INCOMING" "$DIST_ROOT/releases/$RELEASE_ID"; INCOMING=""
  sw="$(rel swap --dist "$DIST_ROOT" --id "$RELEASE_ID")" || die "swap failed (release kept at releases/$RELEASE_ID; current unchanged)"
  if pr="$(rel prune --dist "$DIST_ROOT" --keep "$KEEP")"; then
    [ -n "$(json_get "$pr" removed)" ] && say "pruned: $(json_get "$pr" removed | tr '\n' ' ')"
  else
    say "WARNING: prune failed (old releases kept; the new release is live)"
  fi
  local prev_id; prev_id="$(json_get "$sw" previous)"
  say "OK  current = $RELEASE_ID (previous: ${prev_id:-none})  $(json_get "$info" files) files $(human_bytes "$(json_get "$info" bytes)")" \
      "· gzip $(json_get "$gz" gz_files) files $(human_bytes "$(json_get "$gz" source_bytes)") → $(human_bytes "$(json_get "$gz" gz_bytes)")" \
      "· build $((BUILD_MS / 1000))s · total $(( ($(now_ms) - t_start) / 1000 ))s"
  say "dist root: $DIST_ROOT — ui-api serves it on the next request (no restart)"
}

trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

case "$MODE" in
  list) mode_list ;;
  rollback) mode_rollback ;;
  out) OUT_DIR="$(abspath "$OUT_DIR")"; mode_out ;;
  release) mode_release ;;
esac
