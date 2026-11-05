#!/bin/bash
# Rebuild the PRE-PROGRAM terminal UI (the ui/ source as of 24 Oct 2026 10:38 IST, reconstructed in
# reports/desktop_app/baseline_preprogram/README.md) as a static export, with the same release builder that built
# the live :8010 release 20261025-114737-0ae66db. Use it as the A side of scripts/desktop_qa/parity.py.
#
# Usage:
#   reports/desktop_app/baseline_preprogram/build_baseline.sh --out <dir> [options]
# Options:
#   --tree <dir>           a baseline ui/ tree (default: extract baseline_src.tar.gz next to this script)
#   --node-modules <dir>   node_modules to build with (default: <repo>/ui/node_modules, symlinked, never written)
#   --work <dir>           work dir for the mirror repo (default: a new mktemp dir; removed afterwards)
#   --keep-work            keep the work dir
#   -h, --help
#
# How: it lays out a minimal mirror repo (the layout ui/scripts/build_ui.test.mjs makeRepo() uses):
#   <work>/repo/scripts/build_ui.sh       frozen copy: build/build_ui.sh
#   <work>/repo/ui/                       the baseline tree, checked against MANIFEST.sha256 first
#   <work>/repo/ui/next.config.js         := build/next.config.export.js (the program's config: the pre-program file has
#                                            no static-export branch; for dev/build/start the two resolve identically)
#   <work>/repo/ui/scripts/release.mjs    frozen copy: build/release.mjs
#   <work>/repo/ui/node_modules           symlink to --node-modules
# and runs `build_ui.sh --out <dir>` there, so staging, the export, gzip siblings and build-info.json are produced by
# the same code as a live release. The release id is <IST timestamp>-0000000 (the mirror is not a git checkout).
# Nothing in the real repo is written: ui/, ui/.next*, ui/dist, tsconfig.json and next-env.d.ts are untouched.
# Exit codes: 0 ok · 1 failure · 2 usage.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
OUT=""; TREE=""; NODE_MODULES="$REPO/ui/node_modules"; WORK=""; KEEP_WORK=0; MADE_WORK=0

usage() { sed -n '2,/^set -euo pipefail/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; }
say() { echo "[build_baseline $(TZ=Asia/Kolkata date +%H:%M:%S)] $*"; }
die() { echo "[build_baseline] ERROR: $*" >&2; exit 1; }
abspath() { node -e 'process.stdout.write(require("path").resolve(process.argv[1]))' "$1"; }

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --out) [ $# -ge 2 ] || { echo "--out needs a directory" >&2; exit 2; }; OUT="$2"; shift 2 ;;
    --tree) [ $# -ge 2 ] || { echo "--tree needs a directory" >&2; exit 2; }; TREE="$2"; shift 2 ;;
    --node-modules) [ $# -ge 2 ] || { echo "--node-modules needs a directory" >&2; exit 2; }; NODE_MODULES="$2"; shift 2 ;;
    --work) [ $# -ge 2 ] || { echo "--work needs a directory" >&2; exit 2; }; WORK="$2"; shift 2 ;;
    --keep-work) KEEP_WORK=1; shift ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done
[ -n "$OUT" ] || { echo "--out is required" >&2; usage >&2; exit 2; }
command -v node > /dev/null 2>&1 || die "node not found on PATH"
[ -x "$NODE_MODULES/.bin/next" ] || die "no next binary in $NODE_MODULES (cd ui && npm ci)"
OUT="$(abspath "$OUT")"
case "$OUT/" in
  "$REPO/ui/"*) die "--out must not be inside $REPO/ui (ui/dist, ui/.next* belong to the live stack)" ;;
esac

cleanup() {
  local rc=$?
  if [ "$MADE_WORK" = 1 ] && [ "$KEEP_WORK" = 0 ] && [ -n "$WORK" ]; then rm -rf "$WORK"; fi
  [ "$rc" = 0 ] || echo "[build_baseline] FAILED (exit $rc)" >&2
  exit "$rc"
}
trap cleanup EXIT

if [ -z "$WORK" ]; then WORK="$(mktemp -d "${TMPDIR:-/tmp}/baseline_build.XXXXXX")"; MADE_WORK=1; fi
WORK="$(abspath "$WORK")"
MIRROR="$WORK/repo"
[ ! -e "$MIRROR" ] || die "$MIRROR already exists"
mkdir -p "$MIRROR/scripts" "$MIRROR/ui"

# 1. the baseline tree, verified file by file against the manifest (no extra and no missing file)
if [ -n "$TREE" ]; then
  [ -d "$TREE" ] || die "--tree $TREE is not a directory"
  (cd "$TREE" && tar -cf - .) | (cd "$MIRROR/ui" && tar -xf -)
else
  tar -xzf "$HERE/baseline_src.tar.gz" -C "$MIRROR/ui"
fi
have="$(cd "$MIRROR/ui" && find . -type f | sed 's#^\./##' | LC_ALL=C sort | while IFS= read -r f; do shasum -a 256 "$f"; done)"
want="$(LC_ALL=C sort -k2 "$HERE/MANIFEST.sha256")"
if [ "$have" != "$want" ]; then
  diff <(echo "$want") <(echo "$have") | head -20 >&2
  die "the baseline tree does not match MANIFEST.sha256"
fi
say "baseline tree verified: $(echo "$want" | wc -l | tr -d ' ') files, tree sha256 $(shasum -a 256 < "$HERE/MANIFEST.sha256" | cut -c1-16)…"

# 2. the builder (frozen copies) and the export-capable config
for f in build_ui.sh release.mjs next.config.export.js; do
  got="$(shasum -a 256 "$HERE/build/$f" | cut -d' ' -f1)"
  exp="$(grep " build/$f\$" "$HERE/build/SHA256SUMS" | cut -d' ' -f1)"
  [ "$got" = "$exp" ] || die "build/$f does not match build/SHA256SUMS"
done
cp "$HERE/build/build_ui.sh" "$MIRROR/scripts/build_ui.sh"; chmod 755 "$MIRROR/scripts/build_ui.sh"
mkdir -p "$MIRROR/ui/scripts"; cp "$HERE/build/release.mjs" "$MIRROR/ui/scripts/release.mjs"
cp "$HERE/build/next.config.export.js" "$MIRROR/ui/next.config.js"
ln -s "$(abspath "$NODE_MODULES")" "$MIRROR/ui/node_modules"

# 3. build with the release builder (--out mode: no release root, no swap)
RID="$(TZ=Asia/Kolkata date +%Y%m%d-%H%M%S)-0000000"
say "building $RID into $OUT"
if ! env -u NEXT_DIST_DIR -u NEXT_OUTPUT BUILD_UI_RELEASE_ID="$RID" bash "$MIRROR/scripts/build_ui.sh" --out "$OUT"; then
  [ -f "$MIRROR/.logs/build-ui.log" ] && tail -n 40 "$MIRROR/.logs/build-ui.log" >&2
  die "build_ui.sh failed"
fi
cp "$MIRROR/.logs/build-ui.log" "${OUT%/}.build-ui.log"
say "OK  $OUT  (next build log: ${OUT%/}.build-ui.log)"
node -e 'const o=JSON.parse(require("fs").readFileSync(process.argv[1],"utf8"));console.log(JSON.stringify(o))' "$OUT/build-info.json"
