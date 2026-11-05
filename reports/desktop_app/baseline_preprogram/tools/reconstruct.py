"""Reconstruct the terminal UI source tree as it was before the desktop program (24 Oct 2026, 10:38 IST).

Input is a snapshot of ``ui/`` taken after the program (node_modules/.next*/dist excluded, mtimes preserved). The
script undoes exactly the program's *recorded* changes, newest first, and refuses to guess. What it can prove from
the snapshot, and refuses otherwise:

* every reversal removes text that is present exactly once (an edit inside a recorded block fails);
* every file no record touches predates the program (its mtime);
* every file a record touches was last modified at the time of the last record that touched it (its mtime), so an
  unrecorded edit made after that record, anywhere in the file, fails;
* with ``--pm-backup``, the PM's pre-integration copies equal the intermediate state and are themselves dated
  before the program or at a recorded change;
* the recorded inputs (the D3.md/D4.md blocks as parsed, records/d3_callsites.json, the Write hashes and the
  originals) are exactly the ones this baseline was built from (``RECORDS_SHA256``; the D3.md BOM may be written
  either as the literal character or as the escape), so a later edit of the patch docs cannot silently change it.

What it cannot prove: an edit outside a recorded block made between the program start and the file's last
recorded change (the later write leaves no trace in the mtime). That window is covered by evidence outside this
script: the transcript scans (records/program_writes.tsv, records/bash_write_scan.tsv) and the PM backup.

1. PM integration, 25 Oct 11:04:48 IST: D4 P1-P11 and D3 1d (reports/desktop_app/patches/D4.md, D3.md section 1),
   parsed the same way the PM's applier parsed them. P9a (new file lib/pageKeys.ts) is deleted after its content
   is checked. With ``--pm-backup`` the intermediate state of every file must equal the PM's pre-patch backup.
2. D3 call sites, 24 Oct 11:30:55 IST: the (old, new) pairs of D3's own edit script (records/d3_callsites.json),
   each cross-checked against the D3.md section 2 block it documents.
3. D4 full rewrites: app/layout.tsx and app/global-error.tsx are replaced by the originals D4 printed before
   writing (records/originals); the current files must still be byte-identical to D4's Write payloads.
4. D4 append-only section of app/globals.css: the current file must start with the original byte-for-byte, and
   the rest must be the marked "Desktop program (D4) — APPEND-ONLY SECTION".
5. D1 next.config.js: replaced by the original D1 printed before writing (it is NOT git HEAD: the pre-program
   file already had ``distDir: process.env.NEXT_DIST_DIR || '.next'``); the current file must equal D1's Write.
6. Files and directories the program created are left out (PROGRAM_NEW), plus tsc's incremental cache.

Then it proves the result: a forward replay of the same records on the reconstructed tree reproduces the snapshot
byte-for-byte, the reconstructed listings equal the ``ls`` D4 ran at 05:39 UTC, and every snapshot file outside the
recorded set is older than the program. Outputs (in ``--report-dir``): MANIFEST.sha256 of the reconstructed tree,
diff_vs_snapshot.patch, reconstruct_report.json.

Usage::

    python reconstruct.py --src <ui snapshot> --dest <new dir> --report-dir <dir> \
        [--pm-backup ~/.suryadhana_pm_backups/desktop_integration_20261025-110448]
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
BASELINE_DIR = HERE.parent
RECORDS = BASELINE_DIR / "records"
PATCHES = BASELINE_DIR.parent / "patches"
IST = ZoneInfo("Asia/Kolkata")
PROGRAM_START = datetime(2026, 10, 24, 10, 38, tzinfo=IST)
# The PM's apply_patches.py run (D4 P1-P11 + D3 1d; its backup is desktop_integration_20261025-110448).
PM_INTEGRATION_AT = datetime(2026, 10, 25, 11, 4, 48, tzinfo=IST)
# A recorded time is the tool call's start; its write lands just after. Snapshot mtimes are whole seconds.
MTIME_SLACK_BEFORE_S = 1.5
MTIME_SLACK_AFTER_S = 20.0
# sha256 of every recorded input (record_inputs()); see the module docstring. Re-pin only after re-verifying.
RECORDS_SHA256 = "fe76707bc328d5a03b3b472b5f8a585ecd2a7f891b348c393cc55ea8c9cc39f4"

# Created by the program (absent from D4's 05:39 UTC listing / ui/ top level). Directories end with '/'.
PROGRAM_NEW = (
    "components/desktop/",              # D4 PlatformShell, TitleStrip, ShellNotices, health/build/session helpers
    "lib/platform/",                    # D3 platform bridge
    "lib/prefs/",                       # D3 prefs sync + migration
    "lib/__tests__/platform.check.ts",  # D3 node checks
    "lib/__tests__/prefs.check.ts",
    "lib/pageKeys.ts",                  # D4 P9a (applied by the PM, 25 Oct)
    "public/fonts/",                    # D4 self-hosted fonts (public/ itself existed, empty)
    "scripts/",                         # D1 release builder (release.mjs, tests, print-next-config.mjs)
)
# Not source (the release builder's stage step excludes both): tsc's incremental cache, rewritten by a tsc run on
# 24 Oct 16:26, and gstack's local browse-audit state (git-ignored, from May).
NOT_SOURCE = ("tsconfig.tsbuildinfo", ".gstack/")
FENCE = re.compile(r"```[a-z]*\n(.*?)\n```", re.DOTALL)
D4_APPEND_MARK = "Desktop program (D4) — APPEND-ONLY SECTION. Everything above this line is unchanged."


class ReconstructError(RuntimeError):
    """A recorded change does not match the snapshot: the tree is not what the records describe."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _utc(ts: str) -> float:
    """'2026-10-24T06:00:55.416Z' → epoch seconds."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def _fenced_pair(section: str) -> tuple[str, str]:
    i_old, i_new = section.index("OLD:"), section.index("NEW:")
    old, new = FENCE.search(section, i_old), FENCE.search(section, i_new)
    assert old and new
    return old.group(1), new.group(1)


def parse_d4(text: str) -> list[dict[str, Any]]:
    """D4 P1..P11 as [{id, file, old (None = new file), new}] (the PM applier's parser, kept identical)."""
    out = []
    for chunk in re.split(r"\n(?=## P)", text):
        m = re.match(r"## (P\d+[a-e]?) · `([^`]+)`", chunk.splitlines()[0])
        if not m:
            continue
        pid, f = m.group(1), m.group(2)
        if "NEW FILE" in chunk.splitlines()[0]:
            content = FENCE.search(chunk, chunk.index("CONTENT:"))
            assert content
            out.append({"id": f"D4.{pid}", "file": f, "old": None, "new": content.group(1) + "\n"})
        else:
            old, new = _fenced_pair(chunk)
            out.append({"id": f"D4.{pid}", "file": f, "old": old, "new": new})
    return out


def parse_d3_1d(text: str) -> dict[str, Any]:
    sec1 = text.split("## 2. D3-owned call sites")[0]
    blocks = re.findall(r"```text\n--- old\n(.*?)\n\+\+\+ new\n(.*?)\n```", sec1, re.DOTALL)
    assert len(blocks) == 5, len(blocks)
    old, new = blocks[4]  # 1a import, 1a include, 1b, 1c, 1d
    return {"id": "D3.1d", "file": "ui/context/AppContext.tsx", "old": old, "new": new}


def parse_d3_section2(text: str) -> list[tuple[str, str, str]]:
    """D3.md section 2 blocks as (file, old, new); a literal U+FEFF in the doc stands for the source's \\ufeff."""
    sec2 = text.split("## 2. D3-owned call sites")[1]
    out = []
    for chunk in re.split(r"\n(?=### 2[a-f]\. )", sec2):
        m = re.match(r"### 2[a-f]\. `([^`]+)`", chunk)
        if not m:
            continue
        for old, new in re.findall(r"```text\n--- old\n(.*?)\n\+\+\+ new\n(.*?)\n```", chunk, re.DOTALL):
            out.append((m.group(1), old.replace("\ufeff", "\\ufeff"), new.replace("\ufeff", "\\ufeff")))
    return out


def replace_once(text: str, old: str, new: str, where: str) -> str:
    n = text.count(old)
    if n != 1:
        raise ReconstructError(f"{where}: expected exactly 1 occurrence, found {n}: {old[:90]!r}")
    return text.replace(old, new)


def rel_files(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file() or p.is_symlink())


def _matches(rel: str, patterns: tuple[str, ...]) -> bool:
    return any(rel == p or (p.endswith("/") and rel.startswith(p)) for p in patterns)


def is_program_new(rel: str) -> bool:
    return _matches(rel, PROGRAM_NEW)


def is_not_source(rel: str) -> bool:
    return _matches(rel, NOT_SOURCE)


class Reconstruction:
    def __init__(self, src: Path, pm_backup: Path | None) -> None:
        self.src = src
        self.pm_backup = pm_backup
        self.text: dict[str, str] = {}  # rel path (inside ui/) -> current reconstructed text
        self.steps: list[dict[str, Any]] = []
        self.checks: dict[str, Any] = {}
        self.pm_backup_files: list[str] = []  # PM backup files compared in step 1 (rel paths inside ui/)
        d4_text = (PATCHES / "D4.md").read_text()
        d3_text = (PATCHES / "D3.md").read_text()
        self.d4 = parse_d4(d4_text)
        self.d3_1d = parse_d3_1d(d3_text)
        self.d3_doc = parse_d3_section2(d3_text)
        rec = json.loads((RECORDS / "d3_callsites.json").read_text())
        self.d3_pairs: list[dict[str, str]] = rec["pairs"]
        self.writes = self._program_writes()
        self.provenance = json.loads((RECORDS / "provenance.json").read_text())
        self.d3_at = _utc(self.provenance["d3_callsites"]["timestamp"])
        self.write_at = self._program_write_times()
        self.globals_at = self._d4_globals_time()

    # ── recorded inputs and their times ──────────────────────────────────────────────────────────
    def record_inputs(self) -> dict[str, Any]:
        """Everything the reversal reads, in a canonical form (the D3.md BOM is already normalised to the escape)."""
        originals = {rel: sha256((RECORDS / rel).read_bytes()) for rel in sorted(self.provenance["sha256"])}
        return {"d4": self.d4, "d3_1d": self.d3_1d, "d3_doc": [list(x) for x in self.d3_doc], "d3_pairs": self.d3_pairs,
                "writes": dict(sorted(self.writes.items())), "originals": originals}

    def records_digest(self) -> str:
        return sha256(json.dumps(self.record_inputs(), sort_keys=True, ensure_ascii=False).encode())

    def check_records(self) -> None:
        """The recorded inputs must be the pinned ones, and the originals must match provenance.json."""
        bad = [rel for rel, want in self.provenance["sha256"].items() if sha256((RECORDS / rel).read_bytes()) != want]
        if bad:
            raise ReconstructError(f"records/{bad} differ from the sha256 in records/provenance.json")
        got = self.records_digest()
        if got != RECORDS_SHA256:
            raise ReconstructError(f"the recorded inputs changed (patches/D3.md, D4.md or records/): sha256 {got} != pinned "
                                   f"{RECORDS_SHA256}; re-verify the reconstruction before re-pinning RECORDS_SHA256")
        self.checks["records_pinned"] = got

    @staticmethod
    def _program_write_times() -> dict[str, float]:
        """Time of the last Write per ui/ path (records/program_writes.tsv)."""
        out: dict[str, float] = {}
        for line in (RECORDS / "program_writes.tsv").read_text().splitlines()[1:]:
            ts, _who, tool, path, _digest = line.split("\t")
            if tool == "Write":
                out[path] = max(out.get(path, 0.0), _utc(ts))
        return out

    @staticmethod
    def _d4_globals_time() -> float:
        """Time of D4's last write to app/globals.css (its append-only section; records/bash_write_scan.tsv)."""
        times = []
        for line in (RECORDS / "bash_write_scan.tsv").read_text().splitlines()[1:]:
            ts, who, _tool_use, matched, _head = line.split("\t", 4)
            if who.startswith("D4") and "globals.css" in matched.split(","):
                times.append(_utc(ts))
        if not times:
            raise ReconstructError("records/bash_write_scan.tsv has no D4 write of globals.css")
        return max(times)

    def record_time(self, record_id: str, rel: str) -> float:
        """When the record ``record_id`` last changed ``rel`` (epoch seconds)."""
        if record_id.startswith("D4.P") or record_id == "D3.1d":
            return PM_INTEGRATION_AT.timestamp()
        if record_id.startswith("D3.2#"):
            return self.d3_at
        if record_id in ("D4.write", "D1.write"):
            return self.write_at[f"ui/{rel}"]
        if record_id == "D4.globals-append":
            return self.globals_at
        raise ReconstructError(f"no recorded time for {record_id} ({rel})")

    def last_record_time(self, rel: str, *, before: float | None = None) -> float | None:
        """Latest time a record changed ``rel`` (only records before ``before`` when given); None if none did."""
        times = [self.record_time(s["id"], rel) for s in self.steps if s["file"] == rel]
        if before is not None:
            times = [t for t in times if t < before]
        return max(times) if times else None

    @staticmethod
    def _program_writes() -> dict[str, str]:
        """Last Write payload hash per ui/ path from records/program_writes.tsv."""
        out: dict[str, str] = {}
        for line in (RECORDS / "program_writes.tsv").read_text().splitlines()[1:]:
            _ts, _who, tool, path, digest = line.split("\t")
            if tool == "Write":
                out[path] = digest
        return out

    def get(self, rel: str) -> str:
        if rel not in self.text:
            self.text[rel] = (self.src / rel).read_text()
        return self.text[rel]

    # ── 1. PM integration (D4 P1-P11 + D3 1d), reversed newest-first ────────────────────────────
    def undo_pm_integration(self) -> None:
        blocks = [self.d3_1d, *self.d4]  # the PM applied group d3appctx, then d4 (apply_patches.py --groups order)
        for b in reversed(blocks):
            rel = b["file"].removeprefix("ui/")
            if b["old"] is None:
                cur = (self.src / rel).read_text()
                if cur != b["new"]:
                    raise ReconstructError(f"{b['id']}: new file {rel} differs from the recorded content")
                self.text[rel] = ""  # marker: removed below via PROGRAM_NEW
                self.steps.append({"step": 1, "id": b["id"], "file": rel, "action": "delete new file (content verified)"})
                continue
            self.text[rel] = replace_once(self.get(rel), b["new"], b["old"], f"undo {b['id']} in {rel}")
            self.steps.append({"step": 1, "id": b["id"], "file": rel, "action": "reverse replace"})
        if self.pm_backup:
            matched, problems = [], []
            for f in sorted((self.pm_backup / "ui").rglob("*")):
                if not f.is_file():
                    continue
                rel = str(f.relative_to(self.pm_backup / "ui"))
                if self.get(rel) == f.read_text():
                    matched.append(rel)
                else:
                    problems.append(rel)
            if problems:
                raise ReconstructError(f"after undoing the PM integration these files differ from the PM backup: {problems}")
            self.checks["pm_backup_equal_after_step1"] = matched
            self.pm_backup_files = matched

    def check_pm_backup_mtimes(self) -> None:
        """Each PM backup file (the pre-integration state) is dated before the program or at a recorded change."""
        if not self.pm_backup:
            return
        problems = []
        for rel in self.pm_backup_files:
            m = (self.pm_backup / "ui" / rel).stat().st_mtime
            if m < PROGRAM_START.timestamp():
                continue
            t = self.last_record_time(rel, before=PM_INTEGRATION_AT.timestamp())
            if t is None or not t - MTIME_SLACK_BEFORE_S <= m <= t + MTIME_SLACK_AFTER_S:
                problems.append(f"{rel} ({datetime.fromtimestamp(m, IST).isoformat(timespec='seconds')})")
        if problems:
            raise ReconstructError(f"PM backup files changed during the program with no record explaining it: {problems}")
        self.checks["pm_backup_mtimes_predate_program_or_match_records"] = True

    # ── 2. D3 call sites, reversed ─────────────────────────────────────────────────────────────
    def undo_d3_callsites(self) -> None:
        # A markdown block cannot show a trailing newline, so compare with the final newline stripped.
        doc = [(f, o.rstrip("\n"), n.rstrip("\n")) for f, o, n in self.d3_doc]
        for p in self.d3_pairs:
            key = (p["file"], p["old"].rstrip("\n"), p["new"].rstrip("\n"))
            if key not in doc:
                raise ReconstructError(f"D3 executed pair not documented in D3.md section 2: {p['file']} {p['old'][:60]!r}")
            doc.remove(key)
        if doc:
            raise ReconstructError(f"D3.md section 2 documents blocks D3 never executed: {[(f, o[:40]) for f, o, _ in doc]}")
        self.checks["d3_section2_pairs_match_doc"] = len(self.d3_pairs)
        for k, p in reversed(list(enumerate(self.d3_pairs))):
            rel = p["file"].removeprefix("ui/")
            self.text[rel] = replace_once(self.get(rel), p["new"], p["old"], f"undo D3.2 pair {k} in {rel}")
            self.steps.append({"step": 2, "id": f"D3.2#{k}", "file": rel, "action": "reverse replace"})

    # ── 3-5. full-file originals ──────────────────────────────────────────────────────────────
    def restore_originals(self) -> None:
        for rel, owner in (("app/layout.tsx", "D4"), ("app/global-error.tsx", "D4"), ("next.config.js", "D1")):
            got = sha256((self.src / rel).read_bytes())
            want = self.writes.get(f"ui/{rel}")
            if got != want:
                raise ReconstructError(f"{rel}: the snapshot is not {owner}'s Write payload ({got} != {want})")
            self.text[rel] = (RECORDS / "originals" / rel).read_text()
            self.steps.append({"step": 3 if owner == "D4" else 5, "id": f"{owner}.write", "file": rel,
                               "action": f"restore the original {owner} printed before its Write"})
        cur = self.get("app/globals.css")
        orig = (RECORDS / "originals/app/globals.css").read_text()
        tail = cur[len(orig):]
        if not cur.startswith(orig) or D4_APPEND_MARK not in tail.split("*/", 1)[0] or not tail.startswith("\n/* ═"):
            raise ReconstructError("app/globals.css: the snapshot is not <original> + D4's append-only section")
        self.text["app/globals.css"] = orig
        self.steps.append({"step": 4, "id": "D4.globals-append", "file": "app/globals.css",
                           "action": f"drop D4's appended section ({len(tail.splitlines())} lines)"})

    # ── write + prove ─────────────────────────────────────────────────────────────────────────
    def write(self, dest: Path) -> list[str]:
        if dest.exists():
            raise ReconstructError(f"{dest} exists; refusing to overwrite")
        kept = []
        for rel in rel_files(self.src):
            if is_program_new(rel) or is_not_source(rel):
                continue
            out = dest / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            if rel in self.text:
                out.write_text(self.text[rel])
            else:
                shutil.copy2(self.src / rel, out)
            kept.append(rel)
        (dest / "public").mkdir(exist_ok=True)  # existed (empty) before the program
        return kept

    def replay_forward(self, dest: Path) -> None:
        """Apply the same records forward to the reconstructed tree; the result must be the snapshot, byte for byte."""
        t: dict[str, str] = {}

        def get(rel: str) -> str:
            if rel not in t:
                t[rel] = (dest / rel).read_text()
            return t[rel]

        for k, p in enumerate(self.d3_pairs):
            rel = p["file"].removeprefix("ui/")
            t[rel] = replace_once(get(rel), p["old"], p["new"], f"replay D3.2 pair {k}")
        for b in [self.d3_1d, *self.d4]:
            rel = b["file"].removeprefix("ui/")
            t[rel] = b["new"] if b["old"] is None else replace_once(get(rel), b["old"], b["new"], f"replay {b['id']}")
        mismatched = [rel for rel, s in t.items() if (self.src / rel).read_text() != s]
        if mismatched:
            raise ReconstructError(f"forward replay does not reproduce the snapshot: {mismatched}")
        self.checks["forward_replay_reproduces_snapshot"] = sorted(t)

    def check_inventory(self, dest: Path) -> None:
        """Compare with the `ls` D4 ran at 05:39 UTC (ui/ top level without dotfiles; app/ components/ lib/ public/)."""
        lines = (RECORDS / "inventory_0539Z.txt").read_text().split("\n")
        i = lines.index("---")
        top = {x for x in lines[:i] if x}
        groups: dict[str, set[str]] = {}
        cur = None
        for x in lines[i + 1:]:
            if x.endswith(":") and x[:-1] in ("app", "components", "lib", "public"):
                cur = x[:-1]
                groups[cur] = set()
            elif x and cur:
                groups[cur].add(x)
        problems = []
        have_top = {p.name for p in dest.iterdir() if not p.name.startswith(".")}
        want_top = top - {"node_modules", "tsconfig.tsbuildinfo"}
        if have_top != want_top:
            problems.append(f"ui/ top level: extra {sorted(have_top - want_top)} missing {sorted(want_top - have_top)}")
        for d, want in groups.items():
            have = {p.name for p in (dest / d).iterdir()}
            if have != want:
                problems.append(f"{d}/: extra {sorted(have - want)} missing {sorted(want - have)}")
        if problems:
            raise ReconstructError("inventory differs from D4's 05:39 UTC listing: " + "; ".join(problems))
        self.checks["inventory_matches_0539Z_listing"] = {d: len(v) for d, v in groups.items()} | {"top": len(want_top)}

    def check_mtimes(self) -> None:
        """Every snapshot file the records do not touch must predate the program (mtimes preserved by the copy)."""
        touched = set(self.text)
        newer = []
        for rel in rel_files(self.src):
            if is_program_new(rel) or is_not_source(rel) or rel in touched:
                continue
            if (self.src / rel).stat().st_mtime >= PROGRAM_START.timestamp():
                newer.append(rel)
        if newer:
            raise ReconstructError(f"files changed after the program start that no record explains: {newer}")
        self.checks["untouched_files_predate_program"] = True

    def check_touched_mtimes(self) -> None:
        """Every file a record touched was last modified when the last record touching it ran (±slack): an
        unrecorded edit made after that record, inside or outside the recorded blocks, moves the mtime."""
        problems = []
        for rel in sorted(self.text):
            p = self.src / rel
            if is_program_new(rel) or not p.exists():
                continue
            t = self.last_record_time(rel)
            m = p.stat().st_mtime
            if t is None or not t - MTIME_SLACK_BEFORE_S <= m <= t + MTIME_SLACK_AFTER_S:
                when = datetime.fromtimestamp(m, IST).isoformat(timespec="seconds")
                rec = datetime.fromtimestamp(t, IST).isoformat(timespec="seconds") if t else "none"
                problems.append(f"{rel} (modified {when}, last record {rec})")
        if problems:
            raise ReconstructError(f"files modified after their last recorded change (an unrecorded edit): {problems}")
        self.checks["touched_files_dated_at_their_last_record"] = True

    def report(self, dest: Path, kept: list[str], report_dir: Path) -> dict[str, Any]:
        report_dir.mkdir(parents=True, exist_ok=True)
        manifest = "".join(f"{sha256((dest / r).read_bytes())}  {r}\n" for r in kept)
        (report_dir / "MANIFEST.sha256").write_text(manifest)
        removed = [r for r in rel_files(self.src) if is_program_new(r)]
        not_source = [r for r in rel_files(self.src) if is_not_source(r)]
        modified = sorted(r for r in self.text if r in kept and (self.src / r).read_text() != self.text[r])
        patch = []
        per_file = {}
        for r in modified:
            a, b = self.text[r].splitlines(keepends=True), (self.src / r).read_text().splitlines(keepends=True)
            d = list(difflib.unified_diff(a, b, f"baseline/ui/{r}", f"snapshot/ui/{r}", n=2))
            patch += d
            per_file[r] = {"added": sum(1 for x in d if x.startswith("+") and not x.startswith("+++")),
                           "removed": sum(1 for x in d if x.startswith("-") and not x.startswith("---")),
                           "records": sorted({s["id"] for s in self.steps if s["file"] == r})}
        (report_dir / "diff_vs_snapshot.patch").write_text("".join(patch))
        rep = {
            "src": str(self.src), "dest": str(dest), "files": len(kept),
            "tree_sha256": sha256(manifest.encode()),
            "modified_vs_snapshot": per_file,
            "program_new_removed": removed,
            "not_source_left_out": not_source,
            "steps": self.steps, "checks": self.checks,
        }
        (report_dir / "reconstruct_report.json").write_text(json.dumps(rep, indent=1) + "\n")
        return rep


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", required=True, type=Path, help="snapshot of ui/ (mtimes preserved)")
    ap.add_argument("--dest", required=True, type=Path, help="new directory for the reconstructed ui/ tree")
    ap.add_argument("--report-dir", required=True, type=Path)
    ap.add_argument("--pm-backup", type=Path, help="PM pre-patch backup dir (contains ui/...)")
    ap.add_argument("--skip-mtime-check", action="store_true", help="for a snapshot whose mtimes were not preserved")
    a = ap.parse_args(argv)
    try:
        r = Reconstruction(a.src.resolve(), a.pm_backup)
        r.check_records()
        r.undo_pm_integration()
        r.undo_d3_callsites()
        r.restore_originals()
        kept = r.write(a.dest)
        r.replay_forward(a.dest)
        r.check_inventory(a.dest)
        if not a.skip_mtime_check:
            r.check_mtimes()
            r.check_touched_mtimes()
            r.check_pm_backup_mtimes()
    except ReconstructError as e:
        print(f"RECONSTRUCTION FAILED: {e}", file=sys.stderr)
        return 1
    rep = r.report(a.dest, kept, a.report_dir)
    print(json.dumps({k: rep[k] for k in ("files", "tree_sha256", "modified_vs_snapshot", "checks")}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
