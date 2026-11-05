"""Regression tests for the pre-program baseline reconstruction (reconstruct.py) and its committed artefacts.

They rebuild a synthetic post-program snapshot from the committed baseline (baseline_src.tar.gz) plus the recorded
program changes, run the reconstruction on it, and require the exact baseline back (MANIFEST.sha256). The negative
tests change the snapshot in ways no record explains and require the reconstruction to refuse.

Run: /Users/sudheer/Desktop/jupyter_env/bin/python -m pytest reports/desktop_app/baseline_preprogram/tools -q
"""
from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import tarfile
from pathlib import Path

import pytest

# pytest's default (prepend) import mode puts this directory on sys.path; importlib keeps isort cwd-independent
rc = importlib.import_module("reconstruct")

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
TARBALL = BASE / "baseline_src.tar.gz"
MANIFEST = BASE / "MANIFEST.sha256"
FINAL = BASE / "records" / "program_final"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def extract(dest: Path) -> Path:
    with tarfile.open(TARBALL) as t:
        t.extractall(dest, filter="data")  # keeps the archived mtimes
    return dest


def make_snapshot(tmp: Path) -> Path:
    """Baseline + every recorded program change = the ui/ tree the live release 20261025-114737 was built from
    (minus the program's brand-new files, which the reconstruction drops anyway). Each changed file is dated at
    the time of the last record that changed it, as in the real snapshot."""
    snap = extract(tmp / "snap")
    r = rc.Reconstruction(snap, None)
    when: dict[str, float] = {}

    def stamp(rel: str, record_id: str) -> None:
        when[rel] = max(when.get(rel, 0.0), r.record_time(record_id, rel))

    for k, p in enumerate(r.d3_pairs):
        rel = p["file"].removeprefix("ui/")
        f = snap / rel
        f.write_text(rc.replace_once(f.read_text(), p["old"], p["new"], "test"))
        stamp(rel, f"D3.2#{k}")
    for b in [r.d3_1d, *r.d4]:
        rel = b["file"].removeprefix("ui/")
        f = snap / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(b["new"] if b["old"] is None else rc.replace_once(f.read_text(), b["old"], b["new"], "test"))
        stamp(rel, b["id"])
    for rel, owner in (("app/layout.tsx", "D4"), ("app/global-error.tsx", "D4"), ("next.config.js", "D1")):
        shutil.copyfile(FINAL / rel, snap / rel)
        stamp(rel, f"{owner}.write")
    css = snap / "app/globals.css"
    css.write_text(css.read_text() + (FINAL / "app/globals.css.d4_append").read_text())
    stamp("app/globals.css", "D4.globals-append")
    for rel, t in when.items():
        os.utime(snap / rel, (t, t))
    return snap


def make_pm_backup(tmp: Path) -> Path:
    """The PM's pre-integration backup: every file the PM integration changed, in the intermediate state (baseline
    + D3's call sites), dated as in the real backup (pre-program, or D3's script time where D3 changed it)."""
    base = extract(tmp / "pmbase")
    r = rc.Reconstruction(base, None)
    old = rc.PROGRAM_START.timestamp() - 86400   # the baseline tarball dates the files it rewrote at its build time
    for f in base.rglob("*"):
        if f.is_file():
            os.utime(f, (old, old))
    for p in r.d3_pairs:
        f = base / p["file"].removeprefix("ui/")
        f.write_text(rc.replace_once(f.read_text(), p["old"], p["new"], "test"))
        os.utime(f, (r.d3_at, r.d3_at))
    backup = tmp / "pm_backup"
    for b in [r.d3_1d, *r.d4]:
        rel = b["file"].removeprefix("ui/")
        if b["old"] is None or (backup / "ui" / rel).exists():
            continue
        (backup / "ui" / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(base / rel, backup / "ui" / rel)
    return backup


def run(snap: Path, tmp: Path, *extra: str) -> tuple[int, Path]:
    rep = tmp / "report"
    code = rc.main(["--src", str(snap), "--dest", str(tmp / "out"), "--report-dir", str(rep), *extra])
    return code, rep


def test_tarball_matches_manifest(tmp_path: Path) -> None:
    root = extract(tmp_path / "t")
    have = {str(p.relative_to(root)): sha(p) for p in root.rglob("*") if p.is_file()}
    want = {path: digest for digest, path in (line.split("  ", 1) for line in MANIFEST.read_text().splitlines())}
    assert have == want
    assert len(have) == 134


def test_records_are_what_the_live_release_was_built_from() -> None:
    writes = rc.Reconstruction._program_writes()
    for rel in ("app/layout.tsx", "app/global-error.tsx", "next.config.js"):
        assert sha(FINAL / rel) == writes[f"ui/{rel}"]
    assert sha(BASE / "build/next.config.export.js") == writes["ui/next.config.js"]


def test_d3_doc_bom_in_either_form_parses_to_the_executed_pairs(tmp_path: Path, monkeypatch) -> None:
    """D3.md 2f's CSV byte-order mark: the source and D3's script have the 6-character escape. The doc showed the
    literal U+FEFF until the PM corrected it (25 Oct); either form must parse to exactly the executed pairs and to
    the same pinned record digest."""
    text = (rc.PATCHES / "D3.md").read_text()
    pairs = json.loads((rc.RECORDS / "d3_callsites.json").read_text())["pairs"]
    raw = [o for o in text.split("## 2. D3-owned call sites")[1].split("```") if "new Blob(['" in o]
    assert raw and all(("\ufeff" in o) != ("\\ufeff" in o) for o in raw), "each block uses exactly one form"
    assert all("\ufeff" not in p["old"] for p in pairs) and any("'\\ufeff'" in p["old"] for p in pairs)
    doc = {(f, o.rstrip("\n"), n.rstrip("\n")) for f, o, n in rc.Reconstruction(Path("/nonexistent"), None).d3_doc}
    assert doc == {(p["file"], p["old"].rstrip("\n"), p["new"].rstrip("\n")) for p in pairs}
    # the other form (literal <-> escape inside the Blob lines only) gives the same records digest
    sec1, sec2 = text.split("## 2. D3-owned call sites")
    other = sec2.replace("\\ufeff", "\ufeff") if "\\ufeff" in sec2 else sec2.replace("\ufeff", "\\ufeff")
    patches = tmp_path / "patches"
    patches.mkdir()
    (patches / "D3.md").write_text(sec1 + "## 2. D3-owned call sites" + other)
    shutil.copyfile(rc.PATCHES / "D4.md", patches / "D4.md")
    monkeypatch.setattr(rc, "PATCHES", patches)
    assert rc.Reconstruction(Path("/nonexistent"), None).records_digest() == rc.RECORDS_SHA256


def test_records_are_pinned_and_a_changed_patch_block_is_refused(tmp_path: Path, monkeypatch) -> None:
    r = rc.Reconstruction(Path("/nonexistent"), None)
    r.check_records()
    assert r.checks["records_pinned"] == rc.RECORDS_SHA256
    patches = tmp_path / "patches"
    shutil.copytree(rc.PATCHES, patches)
    d4 = patches / "D4.md"
    d4.write_text(d4.read_text().replace("calc(100vh - var(--shell-top, 0px))", "calc(100vh - 31px)", 1))
    monkeypatch.setattr(rc, "PATCHES", patches)
    with pytest.raises(rc.ReconstructError, match="recorded inputs changed"):
        rc.Reconstruction(Path("/nonexistent"), None).check_records()
    # prose outside the parsed blocks may change freely
    shutil.copyfile(rc.HERE.parent.parent / "patches" / "D4.md", d4)
    d4.write_text(d4.read_text() + "\nA note added after the program.\n")
    rc.Reconstruction(Path("/nonexistent"), None).check_records()


def test_parsers_match_the_pm_applier_counts() -> None:
    r = rc.Reconstruction(Path("/nonexistent"), None)
    assert [b["id"] for b in r.d4] == ["D4.P1", "D4.P2", "D4.P3", "D4.P4", "D4.P5", "D4.P6", "D4.P7", "D4.P8",
                                       "D4.P9a", "D4.P9b", "D4.P9c", "D4.P9d", "D4.P9e", "D4.P10", "D4.P11"]
    assert r.d3_1d["file"] == "ui/context/AppContext.tsx"
    assert len(r.d3_pairs) == 14 and len(r.d3_doc) == 14


def test_replace_once_refuses_missing_and_ambiguous() -> None:
    assert rc.replace_once("a b", "a", "c", "t") == "c b"
    with pytest.raises(rc.ReconstructError):
        rc.replace_once("a b", "x", "c", "t")
    with pytest.raises(rc.ReconstructError):
        rc.replace_once("a a", "a", "c", "t")


def test_reconstruction_returns_the_exact_baseline(tmp_path: Path) -> None:
    snap = make_snapshot(tmp_path)
    code, rep = run(snap, tmp_path)
    assert code == 0
    report = json.loads((rep / "reconstruct_report.json").read_text())
    assert (rep / "MANIFEST.sha256").read_text() == MANIFEST.read_text()
    assert report["tree_sha256"] == hashlib.sha256(MANIFEST.read_bytes()).hexdigest()
    assert set(report["checks"]) == {"records_pinned", "d3_section2_pairs_match_doc", "forward_replay_reproduces_snapshot",
                                     "inventory_matches_0539Z_listing", "untouched_files_predate_program",
                                     "touched_files_dated_at_their_last_record"}


def test_unrecorded_edit_outside_the_recorded_blocks_of_a_touched_file_is_refused(tmp_path: Path) -> None:
    """The adversarial reviewer's case: an edit OUTSIDE every recorded block of a file the records touch (and
    so not refused by any reversal) moves that file's mtime past its last record."""
    snap = make_snapshot(tmp_path)
    watch = snap / "components/WatchMonitor.tsx"
    page = snap / "app/page.tsx"
    watch.write_text(watch.read_text() + "\nexport const UNRECORDED = 1\n")
    page.write_text("// unrecorded comment\n" + page.read_text())
    code, _ = run(snap, tmp_path)
    assert code == 1
    # with the files dated at their last record again the same tree passes: an edit made BEFORE a file's last
    # recorded change is outside what the snapshot can prove (module docstring; the transcript scans cover it)
    r = rc.Reconstruction(snap, None)
    for f, rid in ((watch, "D3.2#2"), (page, "D4.P1")):
        t = r.record_time(rid, str(f.relative_to(snap)))
        os.utime(f, (t, t))
    shutil.rmtree(tmp_path / "out", ignore_errors=True)
    code, _ = run(snap, tmp_path)
    assert code == 0


def test_pm_backup_must_match_and_be_dated_before_the_program_or_at_a_record(tmp_path: Path) -> None:
    snap = make_snapshot(tmp_path)
    backup = make_pm_backup(tmp_path)
    code, rep = run(snap, tmp_path, "--pm-backup", str(backup))
    assert code == 0
    checks = json.loads((rep / "reconstruct_report.json").read_text())["checks"]
    assert len(checks["pm_backup_equal_after_step1"]) == 13 and checks["pm_backup_mtimes_predate_program_or_match_records"]
    # a backup file touched during the program with no record explaining it is refused
    os.utime(backup / "ui" / "components/Compare.tsx", (rc.PROGRAM_START.timestamp() + 3600,) * 2)
    shutil.rmtree(tmp_path / "out", ignore_errors=True)
    code, _ = run(snap, tmp_path, "--pm-backup", str(backup))
    assert code == 1


def test_unrecorded_edit_inside_a_recorded_block_is_refused(tmp_path: Path) -> None:
    snap = make_snapshot(tmp_path)
    page = snap / "app/page.tsx"
    page.write_text(page.read_text().replace("calc(100vh - var(--shell-top, 0px))", "calc(100vh - 32px)", 1))
    code, _ = run(snap, tmp_path, "--skip-mtime-check")
    assert code == 1


def test_unrecorded_edit_of_an_untouched_file_is_refused(tmp_path: Path) -> None:
    snap = make_snapshot(tmp_path)
    kpi = snap / "components/KPICard.tsx"
    kpi.write_text(kpi.read_text() + "\n// edited after the program started\n")
    code, _ = run(snap, tmp_path)
    assert code == 1
    # the same tree passes once the edit is dated before the program (proves it is the mtime check that refused it)
    os.utime(kpi, (rc.PROGRAM_START.timestamp() - 60, rc.PROGRAM_START.timestamp() - 60))
    shutil.rmtree(tmp_path / "out", ignore_errors=True)
    code, _ = run(snap, tmp_path)
    assert code == 0


def test_rewritten_file_that_is_not_the_recorded_write_is_refused(tmp_path: Path) -> None:
    snap = make_snapshot(tmp_path)
    lay = snap / "app/layout.tsx"
    lay.write_text(lay.read_text().replace("TERMINAL_BG = '#05070a'", "TERMINAL_BG = '#000000'"))
    code, _ = run(snap, tmp_path, "--skip-mtime-check")
    assert code == 1


def test_globals_css_must_be_original_plus_marked_append(tmp_path: Path) -> None:
    snap = make_snapshot(tmp_path)
    css = snap / "app/globals.css"
    css.write_text(css.read_text().replace(":root", ":root ", 1))
    code, _ = run(snap, tmp_path, "--skip-mtime-check")
    assert code == 1
