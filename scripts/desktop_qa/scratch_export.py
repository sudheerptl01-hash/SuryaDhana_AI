"""Build a scratch static export of the terminal UI for the parity/streams harness (never inside ui/).

Two methods:

* ``build_ui`` (preferred, used automatically when D1's script exists): ``scripts/build_ui.sh --out <out>``,
  the production recipe (staged copy, export, verify, gzip siblings, build-info.json).
* ``feasibility`` (fallback / ``--method feasibility``): the 24 Oct feasibility recipe. ``ui/`` is copied
  without node_modules/.next/.next-prod/dist into ``<work>/ui_snapshot`` (node_modules symlinked), the 6
  dev-only ``app/api`` stream proxies are moved aside, ``next.config.js`` is replaced by
  ``{output: 'export', distDir: '.next-export'}``, and ``next build`` runs in the copy.

Either way ``<out>/qa_snapshot.json`` records when the UI source snapshot was taken, the git HEAD, the method
and a SHA-256 over the source files, because the UI is being edited in parallel and parity must say exactly
which code it compared.

Usage:
    /Users/sudheer/Desktop/jupyter_env/bin/python scripts/desktop_qa/scratch_export.py --work <scratch dir> \
        [--method auto|build_ui|feasibility]
Prints the export directory (the one containing index.html) on the last line.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "ui"
BUILD_UI = ROOT / "scripts" / "build_ui.sh"
EXCLUDE = {"node_modules", ".next", ".next-prod", "dist", "out", ".build-ui", ".gstack", "tsconfig.tsbuildinfo"}
SOURCE_DIRS = ("app", "components", "lib", "context", "public")
EXPORT_CONFIG = ("/** desktop QA scratch static export (T harness) — NOT the live app, never built inside ui/ */\n"
                 "module.exports = { reactStrictMode: true, output: 'export', distDir: '.next-export', "
                 "images: { unoptimized: true } }\n")


def source_digest(ui_root: Path) -> tuple[str, int]:
    """SHA-256 over (relative path, bytes) of every UI source file; returns (hex, file count)."""
    h, n = hashlib.sha256(), 0
    for d in SOURCE_DIRS:
        base = ui_root / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file():
                h.update(str(p.relative_to(ui_root)).encode() + b"\0" + p.read_bytes())
                n += 1
    return h.hexdigest(), n


def git_head() -> str | None:
    r = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short=7", "HEAD"], capture_output=True, text=True,
                       check=False)
    return r.stdout.strip() or None


def feasibility_build(work: Path) -> Path:
    snap = work / "ui_snapshot"
    if snap.exists():
        shutil.rmtree(snap)
    shutil.copytree(UI, snap, ignore=lambda d, names: [n for n in names if n in EXCLUDE], symlinks=True)
    os.symlink(UI / "node_modules", snap / "node_modules")
    api = snap / "app" / "api"
    if api.exists():
        shutil.move(str(api), str(work / "ui_snapshot_removed_api"))
    (snap / "next.config.js").write_text(EXPORT_CONFIG)
    env = {**os.environ, "NEXT_TELEMETRY_DISABLED": "1"}
    r = subprocess.run(["npx", "next", "build"], cwd=snap, env=env, capture_output=True, text=True, timeout=900,
                       check=False)
    (work / "export_build.log").write_text(r.stdout + r.stderr)
    if r.returncode != 0:
        raise SystemExit(f"next build failed (rc {r.returncode}); see {work / 'export_build.log'}")
    return snap / ".next-export"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="scratch static export for the desktop QA harness")
    ap.add_argument("--work", required=True, help="scratch directory (outside ui/)")
    ap.add_argument("--method", choices=["auto", "build_ui", "feasibility"], default="auto")
    args = ap.parse_args(argv)
    work = Path(args.work).resolve()
    if UI.resolve() in [work, *work.parents]:
        print("--work must be outside ui/", file=sys.stderr)
        return 2
    work.mkdir(parents=True, exist_ok=True)
    taken_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    digest, nfiles = source_digest(UI)
    method = args.method if args.method != "auto" else ("build_ui" if BUILD_UI.exists() else "feasibility")
    if method == "build_ui":
        out = work / "release"
        if out.exists():
            shutil.rmtree(out)
        r = subprocess.run([str(BUILD_UI), "--out", str(out)], cwd=ROOT, capture_output=True, text=True, timeout=900,
                           check=False)
        (work / "build_ui.log").write_text(r.stdout + r.stderr)
        if r.returncode != 0:
            print(f"build_ui.sh --out failed (rc {r.returncode}); see {work / 'build_ui.log'}", file=sys.stderr)
            return 1
    else:
        out = feasibility_build(work)
    meta = {"taken_at": taken_at, "git_head": git_head(), "method": method, "ui_source_sha256": digest,
            "ui_source_files": nfiles, "export_dir": str(out),
            "build_info": json.loads((out / "build-info.json").read_text()) if (out / "build-info.json").is_file() else None}
    (out / "qa_snapshot.json").write_text(json.dumps(meta, indent=2))
    print(json.dumps(meta, indent=2))
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
