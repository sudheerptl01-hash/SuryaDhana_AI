"""List every Bash command of the program period that names a pre-existing ui/ file AND contains a write construct.

A Write/Edit tool call is recorded exactly (extract_records.py → records/program_writes.tsv), but an agent can also
change a file from Bash (sed -i, a python heredoc, cp, a redirect). This scan is deliberately broad: a command
qualifies when it mentions ui/ and the basename of a file that existed before the program (the baseline manifest),
and contains any write-like construct anywhere (even one that only writes to a scratch dir). Each row is then judged
by reading the command; the verdicts are summarised in README.md §2.3.

Window: program start (24 Oct 10:38 IST) up to the starting copy (25 Oct 11:58:02 IST). Output is TSV on stdout:
timestamp, agent, tool_use id, matched basenames, the first 160 characters of the command. Read-only.

Usage: python scan_bash_writes.py > ../records/bash_write_scan.tsv
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJ = Path("/Users/sudheer/.claude/projects/-Users-sudheer-MahaKubera-108-SuryaDhana-AI")
SESSION = "a24906e4-7b64-46ba-b24b-14c536f43922"
MANIFEST = Path(__file__).resolve().parent.parent / "MANIFEST.sha256"
WINDOW = ("2026-10-24T05:08:00", "2026-10-25T06:28:02")
COMMON = {"README.md", "package.json", "index.tsx", "index.ts", ".env.local", ".dockerignore", "Dockerfile"}
WRITE = re.compile(r"sed -i|perl -pi|write_text|os\.replace|open\([^)]*['\"][wa]['\"]|writeFileSync|appendFileSync|>>|"
                   r"(?<![0-9&])>(?![&=])\s*[\w./$\"']|\bcp\b|\bmv\b|\brm\b|\btee\b|\btouch\b|shutil|rsync|\.replace\(")
MENTIONS_UI = re.compile(r"SuryaDhana_AI/ui|(^|[\s;&(])(cd )?ui(/|\b)")


def main() -> int:
    names = {line.split("  ", 1)[1].rsplit("/", 1)[-1] for line in MANIFEST.read_text().splitlines()} - COMMON
    pats = {n: re.compile(r"(?<![\w.-])" + re.escape(n) + r"(?![\w-])") for n in names}
    print("timestamp\tagent\ttool_use_id\tmatched\tcommand_head")
    for p in [PROJ / f"{SESSION}.jsonl", *sorted((PROJ / SESSION / "subagents").rglob("*.jsonl"))]:
        meta = p.with_suffix(".meta.json")
        who = json.loads(meta.read_text()).get("description", p.stem)[:40] if meta.exists() else "PM (main session)"
        with p.open() as fh:
            for raw in fh:
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                ts = rec.get("timestamp", "")
                if not WINDOW[0] <= ts <= WINDOW[1]:
                    continue
                for b in (rec.get("message") or {}).get("content") or []:
                    if not (isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "Bash"):
                        continue
                    cmd = (b.get("input") or {}).get("command", "")
                    if not MENTIONS_UI.search(cmd) or not WRITE.search(cmd):
                        continue
                    hit = sorted(n for n, rx in pats.items() if rx.search(cmd))
                    if hit:
                        head = " ".join(cmd.split())[:160].replace("\t", " ")
                        print(f"{ts}\t{who}\t{b['id']}\t{','.join(hit)}\t{head}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
