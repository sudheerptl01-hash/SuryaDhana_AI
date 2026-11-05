"""Opt-in end-to-end check of D1's static UI build (PLAN AC-1): ``scripts/build_ui.sh --out <tmp>``.

Runs a real Next.js static export (~10-60 s), so it is OFF by default; enable with ``DESKTOP_QA_BUILD=1``:

    DESKTOP_QA_BUILD=1 /Users/sudheer/Desktop/jupyter_env/bin/python -m pytest tests/integration/test_desktop_static.py -q

Asserts the output shape the static server relies on: ``index.html``, ``_next/static`` JS chunks, every asset
``index.html`` references exists, no ``api`` route-handler directory anywhere, ``build-info.json`` with
``{id, git_sha, built_at, files, bytes}`` and a release id baked into the bundle (NEXT_PUBLIC_UI_BUILD), a
byte-identical ``.gz`` sibling for every text asset > 1 KiB, and that the build never touched ``ui/.next-prod``,
``ui/tsconfig.json`` or ``ui/next-env.d.ts``.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUILD_UI = ROOT / "scripts" / "build_ui.sh"
UI = ROOT / "ui"
TEXT_SUFFIXES = {".js", ".css", ".html", ".json", ".txt", ".svg", ".map"}
RELEASE_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{7}$")

pytestmark = pytest.mark.skipif(os.environ.get("DESKTOP_QA_BUILD") != "1",
                                reason="opt-in: set DESKTOP_QA_BUILD=1 to run a real static export build")


def _fingerprint(p: Path) -> str | None:
    """Content hash (files) or mtime (dirs) of a path the build must not modify; None if absent."""
    if not p.exists():
        return None
    if p.is_dir():
        marker = p / "BUILD_ID"
        return f"dir:{marker.stat().st_mtime_ns}" if marker.exists() else f"dir:{p.stat().st_mtime_ns}"
    return hashlib.sha256(p.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def build(tmp_path_factory):
    if not BUILD_UI.exists():
        pytest.skip("scripts/build_ui.sh not delivered yet (D1 web-serve)")
    protected = [UI / ".next-prod", UI / "tsconfig.json", UI / "next-env.d.ts"]
    before = {p: _fingerprint(p) for p in protected}
    out = tmp_path_factory.mktemp("build_ui") / "release"
    r = subprocess.run([str(BUILD_UI), "--out", str(out)], capture_output=True, text=True, timeout=900, cwd=ROOT,
                       check=False)
    after = {p: _fingerprint(p) for p in protected}
    return {"out": out, "rc": r.returncode, "log": (r.stdout + r.stderr)[-4000:], "before": before, "after": after}


def _root(build) -> Path:
    assert build["rc"] == 0, f"build_ui.sh --out failed (rc {build['rc']}):\n{build['log']}"
    out = build["out"]
    for cand in (out, out / "current"):
        if (cand / "index.html").is_file():
            return cand
    releases = sorted((out / "releases").glob("*")) if (out / "releases").is_dir() else []
    assert releases, f"no index.html under {out}"
    return releases[-1]


def test_build_succeeds_and_has_index(build):
    root = _root(build)
    assert (root / "index.html").is_file()
    assert "<html" in (root / "index.html").read_text(errors="replace").lower()


def test_next_static_chunks_present(build):
    root = _root(build)
    js = list((root / "_next" / "static").rglob("*.js"))
    assert js, "no JS chunks under _next/static"


def test_index_references_only_existing_assets(build):
    root = _root(build)
    html = (root / "index.html").read_text(errors="replace")
    refs = sorted(set(re.findall(r'(?:src|href)="(/_next/static/[^"?#]+)', html)))
    assert refs, "index.html references no _next/static assets"
    missing = [r for r in refs if not (root / r.lstrip("/")).is_file()]
    assert not missing, f"index.html references missing assets: {missing[:10]}"


def test_no_route_handlers_in_output(build):
    root = _root(build)
    api_dirs = [p for p in root.rglob("api") if p.is_dir()]
    assert not api_dirs, f"route-handler output found in a static release: {api_dirs}"


def test_build_info(build):
    root = _root(build)
    info = json.loads((root / "build-info.json").read_text())
    for key, typ in (("id", str), ("git_sha", str), ("built_at", str), ("files", int), ("bytes", int)):
        assert isinstance(info.get(key), typ), f"build-info.json {key!r} missing or not {typ.__name__}: {info.get(key)!r}"
    assert RELEASE_ID.match(info["id"]), f"release id {info['id']!r} is not YYYYmmdd-HHMMSS-<sha7>"
    assert info["files"] > 0 and info["bytes"] > 0


def test_release_id_baked_into_bundle(build):
    root = _root(build)
    rid = json.loads((root / "build-info.json").read_text())["id"]
    hit = any(rid in p.read_text(errors="ignore") for p in (root / "_next" / "static").rglob("*.js"))
    assert hit, f"NEXT_PUBLIC_UI_BUILD={rid} not found in any JS chunk (build-changed detection needs it)"


def test_gzip_siblings_are_identical(build):
    root = _root(build)
    checked = 0
    for p in root.rglob("*"):
        if p.is_file() and p.suffix in TEXT_SUFFIXES and p.stat().st_size > 1024:
            gz = p.with_name(p.name + ".gz")
            assert gz.is_file(), f"no precompressed sibling for {p.relative_to(root)}"
            assert gzip.decompress(gz.read_bytes()) == p.read_bytes(), f"{gz.relative_to(root)} differs from source"
            checked += 1
    assert checked > 0


def test_build_did_not_touch_protected_paths(build):
    changed = [str(p) for p in build["before"] if build["before"][p] != build["after"][p]]
    assert not changed, f"build_ui.sh --out modified protected paths: {changed}"
