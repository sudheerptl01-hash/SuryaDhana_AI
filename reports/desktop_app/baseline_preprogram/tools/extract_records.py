"""Extract the pre-program evidence for the baseline reconstruction from the program's agent transcripts.

The desktop program (reports/desktop_app/PLAN.md) started on 24 Oct 2026 at 10:38 IST. Most of the UI files it
changed have no pre-program copy on disk: D4 rewrote ``ui/app/layout.tsx`` and ``ui/app/global-error.tsx`` with a
full Write, appended to ``ui/app/globals.css``, D1 rewrote ``ui/next.config.js``, and D3 edited six call sites with
a scripted replace. Their transcripts kept what the agents saw *before* the first write, so this script recovers:

* ``originals/app/layout.tsx`` and ``originals/app/global-error.tsx``: D4's first ``cat`` (05:39:02 UTC), which ran
  before D4's Write of either file;
* ``originals/app/globals.css``: D4's first full ``Read`` of the file (05:39:06 UTC);
* ``originals/next.config.js``: D1's first ``cat`` (05:38:58 UTC), before D1's Write (05:45:15 UTC);
* ``d3_callsites.json``: the exact (old, new) pairs of D3's call-site edit script (06:00:55 UTC), parsed with
  ``ast`` from the command text (never executed);
* ``inventory_0539Z.txt``: the ``ls`` of ui/, app/, components/, lib/ and public/ from D4's first command;
* ``program_writes.tsv``: every Write/Edit tool call on a ui/ source path in the program's transcripts, plus the
  content hash of the final Write, so reconstruct.py can prove the current file is still exactly what was written.

Read-only on the transcripts. Usage::

    python extract_records.py --out reports/desktop_app/baseline_preprogram/records
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

PROJ = Path("/Users/sudheer/.claude/projects/-Users-sudheer-MahaKubera-108-SuryaDhana-AI")
SESSION = "a24906e4-7b64-46ba-b24b-14c536f43922"
WF_BUILD = PROJ / SESSION / "subagents" / "workflows" / "wf_7753e95e-caa"
D1 = WF_BUILD / "agent-a384c9fe0430a67b4.jsonl"
D3 = WF_BUILD / "agent-a4d641463b164d7ab.jsonl"
D4 = WF_BUILD / "agent-a67f6ea07f9ae62d7.jsonl"
REPO_UI = "/Users/sudheer/MahaKubera_108/SuryaDhana_AI/ui/"
PROGRAM_START_UTC = "2026-10-24T05:08:00"  # 10:38 IST, FEASIBILITY.md
UI_SRC_RE = re.compile(r"SuryaDhana_AI/ui/(?!node_modules/|\.next|dist/)")
READ_LINE = re.compile(r"^\s*(\d+)\t(.*)$", re.DOTALL)


def blocks(path: Path) -> Iterator[tuple[str, dict[str, Any]]]:
    """(timestamp, content block) for every tool_use / tool_result block of a transcript, in order."""
    with path.open() as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            content = (rec.get("message") or {}).get("content")
            if isinstance(content, list):
                for b in content:
                    if isinstance(b, dict) and b.get("type") in ("tool_use", "tool_result"):
                        yield rec.get("timestamp", ""), b


def result_text(b: dict[str, Any]) -> str:
    c = b.get("content")
    if isinstance(c, str):
        return c
    return "".join(x.get("text", "") for x in c or [] if isinstance(x, dict))


def tool_result(path: Path, pred: Any) -> tuple[str, str, dict[str, Any], str]:
    """First (timestamp, tool_use_id, input, result text) whose tool_use satisfies ``pred(name, input)``."""
    uses: dict[str, tuple[str, str, dict[str, Any]]] = {}
    for ts, b in blocks(path):
        if b["type"] == "tool_use":
            uses[b["id"]] = (ts, b.get("name", ""), b.get("input") or {})
        elif b.get("tool_use_id") in uses:
            ts0, name, inp = uses[b["tool_use_id"]]
            if pred(name, inp):
                return ts0, b["tool_use_id"], inp, result_text(b)
    raise SystemExit(f"{path.name}: no matching tool call")


def first_write_ts(path: Path, file_path: str) -> str:
    for ts, b in blocks(path):
        if b["type"] != "tool_use" or b.get("name") not in ("Write", "Edit"):
            continue
        if (b.get("input") or {}).get("file_path") == file_path:
            return ts
    return "9999"


def sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def extract_d4_cat(out: Path, prov: dict[str, Any]) -> None:
    ts, tid, inp, txt = tool_result(D4, lambda n, i: n == "Bash" and "cat app/layout.tsx" in i.get("command", ""))
    for f in ("app/layout.tsx", "app/global-error.tsx"):
        assert ts < first_write_ts(D4, REPO_UI + f), f"D4 wrote {f} before its first cat"
    lines = txt.split("\n")
    # ls block (up to the blank line before layout.tsx's first line), then layout.tsx, '----', global-error.tsx,
    # then the `wc -l` lines.
    i_layout = lines.index("import type { Metadata } from 'next'")
    i_sep = lines.index("----", i_layout)
    i_wc = next(k for k in range(i_sep, len(lines)) if re.match(r"^\s+\d+ app/globals\.css$", lines[k]))
    layout = "\n".join(lines[i_layout:i_sep]) + "\n"
    gerr = "\n".join(lines[i_sep + 1:i_wc]) + "\n"
    (out / "originals/app").mkdir(parents=True, exist_ok=True)
    (out / "originals/app/layout.tsx").write_text(layout)
    (out / "originals/app/global-error.tsx").write_text(gerr)
    (out / "inventory_0539Z.txt").write_text("\n".join(lines[:i_layout]).rstrip("\n") + "\n")
    wc = re.match(r"^\s+(\d+) app/globals\.css$", lines[i_wc])
    assert wc
    prov["d4_first_cat"] = {"transcript": D4.name, "tool_use_id": tid, "timestamp": ts, "command": inp["command"],
                            "globals_css_lines": int(wc.group(1))}


def extract_d4_globals(out: Path, prov: dict[str, Any]) -> None:
    fp = REPO_UI + "app/globals.css"
    ts, tid, _inp, txt = tool_result(D4, lambda n, i: n == "Read" and i.get("file_path") == fp
                                     and not i.get("offset") and not i.get("limit"))
    txt = re.sub(r"\n*<system-reminder>.*?</system-reminder>\s*$", "", txt, flags=re.DOTALL)
    body: list[str] = []
    for k, raw in enumerate(txt.split("\n"), start=1):
        m = READ_LINE.match(raw)
        if not m or int(m.group(1)) != k:
            raise SystemExit(f"globals.css Read result: unexpected line {k}: {raw[:60]!r}")
        body.append(m.group(2))
    if body and body[-1] == "":
        body.pop()  # the Read view shows the file's final newline as an empty last line
    assert len(body) == prov["d4_first_cat"]["globals_css_lines"], (len(body), prov["d4_first_cat"])
    (out / "originals/app/globals.css").write_text("\n".join(body) + "\n")
    prov["d4_globals_read"] = {"transcript": D4.name, "tool_use_id": tid, "timestamp": ts, "lines": len(body)}


def extract_d1_config(out: Path, prov: dict[str, Any]) -> None:
    ts, tid, inp, txt = tool_result(D1, lambda n, i: n == "Bash" and "cat ui/next.config.js; echo ----; cat ui/package.json"
                                    in i.get("command", ""))
    assert ts < first_write_ts(D1, REPO_UI + "next.config.js")
    lines = txt.split("\n")
    seps = [k for k, ln in enumerate(lines) if ln == "----"]  # FEASIBILITY head | next.config.js | package.json
    assert len(seps) == 2, seps
    cfg_text = "\n".join(lines[seps[0] + 1:seps[1]]) + "\n"
    assert cfg_text.startswith("/** @type {import('next').NextConfig} */") and "module.exports = nextConfig" in cfg_text
    (out / "originals/next.config.js").write_text(cfg_text)
    prov["d1_first_cat"] = {"transcript": D1.name, "tool_use_id": tid, "timestamp": ts, "command": inp["command"][:200]}


def extract_d3_callsites(out: Path, prov: dict[str, Any]) -> None:
    ts, tid, inp, txt = tool_result(D3, lambda n, i: n == "Bash" and 'edit("lib/alerts.ts"' in i.get("command", ""))
    assert txt.splitlines()[:6] == [f"edited {f}" for f in (
        "lib/alerts.ts", "components/WatchMonitor.tsx", "lib/backtestExport.ts", "components/ResearchLibrary.tsx",
        "components/CommandBar.tsx", "components/terminal/index.tsx")], "D3's call-site script did not report 6 edits"
    cmd = inp["command"]
    src = cmd.split("<<'EOF'\n", 1)[1].split("\nEOF\n", 1)[0]
    pairs = []
    for stmt in ast.parse(src).body:  # top-level edit("<file>", [(old, new), ...]) calls, in execution order
        call = stmt.value if isinstance(stmt, ast.Expr) else None
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "edit":
            file = ast.literal_eval(call.args[0])
            for old, new in ast.literal_eval(call.args[1]):
                pairs.append({"file": "ui/" + file, "old": old, "new": new})
    (out / "d3_callsites.json").write_text(json.dumps({"source": {"transcript": D3.name, "tool_use_id": tid,
                                                                  "timestamp": ts}, "pairs": pairs}, indent=1) + "\n")
    prov["d3_callsites"] = {"transcript": D3.name, "tool_use_id": tid, "timestamp": ts, "pairs": len(pairs)}


def program_writes(out: Path) -> None:
    """Every Write/Edit on a ui/ source path since the program start, across all of this session's agents."""
    files = [PROJ / f"{SESSION}.jsonl", *sorted((PROJ / SESSION / "subagents").rglob("*.jsonl"))]
    rows = []
    for p in files:
        meta = p.with_suffix(".meta.json")
        who = json.loads(meta.read_text()).get("description", p.stem) if meta.exists() else "PM (main session)"
        for ts, b in blocks(p):
            if b["type"] != "tool_use" or ts < PROGRAM_START_UTC or b.get("name") not in ("Write", "Edit", "MultiEdit"):
                continue
            inp = b.get("input") or {}
            fp = inp.get("file_path", "")
            if UI_SRC_RE.search(fp):
                content_sha = sha(inp["content"]) if b["name"] == "Write" else ""
                rows.append((ts, who[:48], b["name"], fp.split("SuryaDhana_AI/")[1], content_sha))
    rows.sort()
    (out / "program_writes.tsv").write_text("timestamp\tagent\ttool\tpath\twrite_content_sha256\n"
                                            + "".join("\t".join(r) + "\n" for r in rows))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args(argv)
    a.out.mkdir(parents=True, exist_ok=True)
    prov: dict[str, Any] = {}
    extract_d4_cat(a.out, prov)
    extract_d4_globals(a.out, prov)
    extract_d1_config(a.out, prov)
    extract_d3_callsites(a.out, prov)
    program_writes(a.out)
    for f in sorted((a.out / "originals").rglob("*")):
        if f.is_file():
            prov.setdefault("sha256", {})[str(f.relative_to(a.out))] = sha(f.read_bytes())
    (a.out / "provenance.json").write_text(json.dumps(prov, indent=1) + "\n")
    print(json.dumps(prov, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
