#!/usr/bin/env python
"""Event-loop purity scanner (Bloomberg program S2/F2.2, design §8).

Flags blocking calls written DIRECTLY inside `async def` bodies — the bug class that
froze ui-api (see memory: ui_api_event_loop). Nested `def`/`lambda` bodies are skipped
on purpose: that is exactly where `asyncio.to_thread(worker)` workers live.

Allowlist: scripts/event_loop_allowlist.txt, one `path::call::async_func` per line
(`#` comments allowed). Keyed on the (file, dotted call, enclosing async function)
triple instead of the design's path:line form so entries survive line drift without
rotting. New findings → exit 1.

Usage:
    check_event_loop.py                      # scan the default service trees
    check_event_loop.py --paths a.py dir/    # scan something else (used by its test)
    check_event_loop.py --write-allowlist    # accept current findings as the baseline
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_PATHS = ["services/ui-api", "services/data-service"]
ALLOWLIST = REPO / "scripts" / "event_loop_allowlist.txt"

# Canonical module-level blocking calls (module aliases are normalised before matching).
BLOCKED_CALLS = {
    "pandas.read_parquet", "pandas.read_csv", "pandas.read_sql",
    "duckdb.connect",
    "time.sleep",
    "shutil.copy", "shutil.copy2", "shutil.copyfile", "shutil.copytree", "shutil.move",
    "subprocess.run", "subprocess.call", "subprocess.check_output",
    "subprocess.check_call", "subprocess.Popen",
    "requests.get", "requests.post", "requests.put", "requests.delete",
    "requests.head", "requests.request",
    # sync httpx module verbs (httpx.AsyncClient is fine; httpx.get(...) is not)
    "httpx.get", "httpx.post", "httpx.put", "httpx.delete", "httpx.head", "httpx.request",
    "os.system",
}
# Bare-name calls that mean "DuckDB on this thread" in this repo.
BLOCKED_NAMES = {"get_conn"}


def _dotted(node: ast.expr) -> str | None:
    """`pd.read_parquet` → "pd.read_parquet"; bails on anything fancier."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


class _ModuleInfo(ast.NodeVisitor):
    """Alias map (import pandas as pd → {"pd": "pandas"}) + duckdb/get_conn usage."""

    def __init__(self) -> None:
        self.aliases: dict[str, str] = {}
        self.flags_execute = False  # flag bare `X.execute(...)` in this module

    def visit_Import(self, node: ast.Import) -> None:
        for a in node.names:
            self.aliases[a.asname or a.name.split(".")[0]] = a.name.split(".")[0]
            if a.name.split(".")[0] == "duckdb":
                self.flags_execute = True

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module and node.module.split(".")[0] == "duckdb":
            self.flags_execute = True
        for a in node.names:
            if a.name == "get_conn":  # the repo's DuckDB accessor
                self.flags_execute = True


class _AsyncBodyScan(ast.NodeVisitor):
    """Walks ONE async def body; never descends into nested function/lambda scopes."""

    def __init__(self, info: _ModuleInfo, func_name: str, findings: list) -> None:
        self.info, self.func, self.findings = info, func_name, findings

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        pass  # nested sync def = a to_thread worker; its blocking calls are the point

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        pass  # nested async defs get their own top-level scan

    def visit_Lambda(self, node: ast.Lambda) -> None:
        pass

    def visit_Call(self, node: ast.Call) -> None:
        dotted = _dotted(node.func)
        if dotted:
            head, _, rest = dotted.partition(".")
            canonical = f"{self.info.aliases.get(head, head)}.{rest}" if rest else self.info.aliases.get(head, head)
            if canonical in BLOCKED_CALLS or dotted in BLOCKED_CALLS:
                self.findings.append((node.lineno, canonical, self.func))
            elif dotted in BLOCKED_NAMES:
                self.findings.append((node.lineno, dotted, self.func))
            elif self.info.flags_execute and rest.endswith("execute") and "." in dotted:
                self.findings.append((node.lineno, f"{dotted.rsplit('.', 1)[0]}.execute", self.func))
        self.generic_visit(node)


def scan_file(path: Path) -> list[tuple[int, str, str]]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    info = _ModuleInfo()
    info.visit(tree)
    findings: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            scanner = _AsyncBodyScan(info, node.name, findings)
            for stmt in node.body:
                scanner.visit(stmt)
    return findings


def iter_py(paths: list[str]) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        root = (REPO / p) if not Path(p).is_absolute() else Path(p)
        if root.is_file():
            out.append(root)
            continue
        for f in sorted(root.rglob("*.py")):
            s = str(f)
            if "__pycache__" in s or "/tests/" in s or "/node_modules/" in s or "/.venv/" in s:
                continue
            out.append(f)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--paths", nargs="*", default=DEFAULT_PATHS)
    ap.add_argument("--write-allowlist", action="store_true")
    ap.add_argument("--allowlist", default=str(ALLOWLIST))
    args = ap.parse_args()

    allow: set[tuple[str, str, str]] = set()
    allow_path = Path(args.allowlist)
    if allow_path.exists():
        for line in allow_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                parts = line.split("::")
                if len(parts) == 3:
                    allow.add(tuple(parts))  # type: ignore[arg-type]

    rows: list[tuple[str, int, str, str]] = []
    for f in iter_py(args.paths):
        rel = str(f.relative_to(REPO)) if f.is_relative_to(REPO) else str(f)
        for lineno, call, func in scan_file(f):
            rows.append((rel, lineno, call, func))

    new = [r for r in rows if (r[0], r[2], r[3]) not in allow]

    if args.write_allowlist:
        lines = ["# event-loop purity allowlist — path::blocking_call::async_func",
                 "# (regenerate: scripts/check_event_loop.py --write-allowlist)"]
        lines += sorted({f"{r[0]}::{r[2]}::{r[3]}" for r in rows})
        allow_path.write_text("\n".join(lines) + "\n")
        print(f"wrote {len(rows)} finding(s) to {allow_path}")
        return 0

    for rel, lineno, call, func in rows:
        tag = "ALLOWED" if (rel, call, func) in allow else "NEW"
        print(f"[{tag}] {rel}:{lineno}  {call}  in async def {func}")
    print(f"\nevent-loop purity: {len(rows)} finding(s), {len(new)} new, "
          f"{len(rows) - len(new)} allowlisted")
    if new:
        print("FAIL: blocking call(s) directly inside async handlers — wrap in "
              "asyncio.to_thread or allowlist with justification.")
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
