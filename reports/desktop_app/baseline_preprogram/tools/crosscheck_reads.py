"""Independent cross-check of the reconstructed baseline against what the program's agents SAW before they edited.

Every ``Read`` result (``cat -n`` view) and every direct ``grep -n`` output of a touched ui/ file that an agent of this
session produced *before that file's first program modification* shows original lines with their line numbers. Each
such line must equal the reconstructed file at the same line number.

Heuristics (deliberately conservative, so a reported mismatch is worth reading):
* only greps run directly on repo files count: a ``| grep -n`` (line numbers relative to a slice) and commands that
  touch node_modules, scratch copies or patch documents are skipped;
* a grep line that is a strict prefix of the baseline line counts separately (the agent truncated output with
  ``cut -c``);
* a grep line is attributed to a file by its ``path:`` prefix, or, for a single-file grep, by the one touched file the
  command names; a command naming two touched files and printing bare ``N:`` lines can still misattribute, and the
  report lists each mismatch with its command so it can be judged.

Usage: python crosscheck_reads.py <reconstructed ui/ tree>   (read-only on the transcripts)
"""
from __future__ import annotations

import json
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

PROJ = Path("/Users/sudheer/.claude/projects/-Users-sudheer-MahaKubera-108-SuryaDhana-AI")
SESSION = "a24906e4-7b64-46ba-b24b-14c536f43922"
PROGRAM_START_UTC = "2026-10-24T05:08"
D3_CALLSITES_UTC = "2026-10-24T06:00:55"
PM_INTEGRATION_UTC = "2026-10-25T05:34:40"  # apply_patches.py --apply (11:04:48 IST file mtimes)
FIRST_MOD: dict[str, str] = {
    **{f: D3_CALLSITES_UTC for f in ("lib/alerts.ts", "components/WatchMonitor.tsx", "lib/backtestExport.ts",
                                     "components/ResearchLibrary.tsx", "components/CommandBar.tsx",
                                     "components/terminal/index.tsx")},
    **{f: PM_INTEGRATION_UTC for f in ("app/page.tsx", "components/MarketCommandHeader.tsx",
                                       "components/news/NewsTerminal.tsx", "components/StockDetailModal.tsx",
                                       "context/ToastContext.tsx", "components/ErrorCatcher.tsx", "components/Compare.tsx",
                                       "components/OptionChain.tsx", "components/DealsMonitor.tsx",
                                       "components/AlphaDiscoveryDesk.tsx", "tailwind.config.ts", "context/AppContext.tsx")},
    "app/layout.tsx": "2026-10-24T06:01:01",
    "app/global-error.tsx": "2026-10-24T05:58:41",
    "next.config.js": "2026-10-24T05:45:15",
}
GREP_LINE = re.compile(r"^(?:(?:\S*?/)?((?:app|lib|components|context)/[\w/.\-]+\.tsx?|tailwind\.config\.ts|next\.config\.js):)?"
                       r"(\d+)[:\t](.*)$", re.MULTILINE)
READ_LINE = re.compile(r"^\s*(\d+)\t(.*)$", re.MULTILINE)
SKIP_CMD = ("node_modules", "scratchpad", "/tmp/", "patches/")


def tool_results(path: Path) -> Iterator[tuple[str, str, dict[str, Any], str]]:
    """(timestamp of the call, tool name, input, result text) for every tool call of a transcript."""
    uses: dict[str, tuple[str, str, dict[str, Any]]] = {}
    with path.open() as fh:
        for raw in fh:
            try:
                rec = json.loads(raw)
            except json.JSONDecodeError:
                continue
            for b in (rec.get("message") or {}).get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    uses[b["id"]] = (rec.get("timestamp", ""), b.get("name", ""), b.get("input") or {})
                elif b.get("type") == "tool_result" and b.get("tool_use_id") in uses:
                    c = b.get("content")
                    txt = c if isinstance(c, str) else "".join(x.get("text", "") for x in c or [] if isinstance(x, dict))
                    yield (*uses[b["tool_use_id"]], txt)


def seen_lines(ts: str, name: str, inp: dict[str, Any], txt: str) -> list[tuple[str, int, str]]:
    """(file, line number, text) an agent saw of a touched file before its first modification."""
    if name == "Read":
        fp = inp.get("file_path", "")
        f = next((k for k in FIRST_MOD if fp.endswith("/ui/" + k)), None)
        if f is None or ts >= FIRST_MOD[f]:
            return []
        return [(f, int(n), t) for n, t in READ_LINE.findall(txt)]
    cmd = inp.get("command", "") if name == "Bash" else ""
    if "grep -n" not in cmd and "grep -rn" not in cmd:
        return []
    if re.search(r"\|\s*grep", cmd) or any(x in cmd for x in SKIP_CMD):
        return []
    out = []
    for m in GREP_LINE.finditer(txt):
        f = m.group(1)
        if f is None:
            named = [k for k in FIRST_MOD if k in cmd]
            if len(named) != 1:
                continue
            f = named[0]
        if f in FIRST_MOD and ts < FIRST_MOD[f]:
            out.append((f, int(m.group(2)), m.group(3)))
    return out


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(__doc__.strip().splitlines()[-1], file=sys.stderr)
        return 2
    base = Path(args[0])
    lines = {f: (base / f).read_text().split("\n") for f in FIRST_MOD}
    exact = dict.fromkeys(FIRST_MOD, 0)
    prefix = dict.fromkeys(FIRST_MOD, 0)
    mismatches: list[dict[str, Any]] = []
    for p in [PROJ / f"{SESSION}.jsonl", *sorted((PROJ / SESSION / "subagents").rglob("*.jsonl"))]:
        for ts, name, inp, txt in tool_results(p):
            if ts < PROGRAM_START_UTC:
                continue
            for f, n, t in seen_lines(ts, name, inp, txt):
                cur = lines[f][n - 1] if 0 < n <= len(lines[f]) else None
                if cur == t:
                    exact[f] += 1
                elif cur is not None and t and cur.startswith(t):
                    prefix[f] += 1
                elif t.strip():
                    mismatches.append({"transcript": p.stem, "at": ts, "file": f, "line": n, "seen": t[:100],
                                       "baseline": (cur or "<past end of file>")[:100],
                                       "command": (inp.get("command") or inp.get("file_path", ""))[:200]})
    report = {"exact": exact, "exact_total": sum(exact.values()), "prefix_total": sum(prefix.values()),
              "mismatches": mismatches}
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
