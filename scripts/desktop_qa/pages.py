"""The terminal's page list: parsed from its single source of truth, ``ui/app/page.tsx``.

``TAB_IDS`` (every page id the router accepts), ``COMMAND_PAGES`` (id, code, label, hint for the GO bar and
the Rust Go menu) and the page strip ``tabList`` (whose first nine entries are ALT+1…9, mirrored by ⌘1…⌘9
in the desktop shell) are read with small, strict parsers. If ``page.tsx`` changes shape the parsers
raise ``PageSourceError`` instead of silently returning a partial list.

Also parses the Rust Go-menu copy (``desktop/src-tauri/src/pages.rs``), which D2 writes as a const array of
string tuples ``("brief", "BRF", "Morning brief", ...)`` or of struct literals
``Page { id: "brief", code: "BRF", label: "Morning brief", .. }``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE_TSX = ROOT / "ui" / "app" / "page.tsx"
PAGES_RS = ROOT / "desktop" / "src-tauri" / "src" / "pages.rs"

# A single-quoted TS string literal (page.tsx uses single quotes; escapes like \' are allowed).
_TS_STR = r"'((?:[^'\\\n]|\\.)*)'"
# A double-quoted Rust string literal.
_RS_STR = r'"((?:[^"\\\n]|\\.)*)"'


class PageSourceError(ValueError):
    """``page.tsx`` / ``pages.rs`` no longer has the shape these parsers expect."""


@dataclass(frozen=True)
class CommandPage:
    """One GO-bar page: ``id`` is the ``?tab=`` value, ``code`` the Bloomberg-style function code."""

    id: str
    code: str
    label: str
    hint: str = ""


def _unescape(s: str) -> str:
    """Undo the backslash escapes allowed inside a TS/Rust literal (\\' \\" \\\\ \\n \\t)."""
    return re.sub(r"\\(.)", lambda m: {"n": "\n", "t": "\t"}.get(m.group(1), m.group(1)), s)


def _block(src: str, opener: str, *, what: str) -> str:
    """Return the text between ``opener`` (which must end with ``[``) and its matching ``]``."""
    i = src.find(opener)
    if i < 0:
        raise PageSourceError(f"{what}: '{opener}' not found")
    start = i + len(opener)
    depth, j, quote = 1, start, None
    while j < len(src):
        c = src[j]
        if quote:
            if c == "\\":
                j += 2
                continue
            if c == quote:
                quote = None
        elif c in ("'", '"', "`"):
            quote = c
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return src[start:j]
        j += 1
    raise PageSourceError(f"{what}: unterminated array after '{opener}'")


def _strip_line_comments(text: str) -> str:
    """Drop ``// …`` comments that are outside string literals (enough for these flat arrays)."""
    out = []
    for line in text.splitlines():
        quote, k = None, 0
        while k < len(line):
            c = line[k]
            if quote:
                if c == "\\":
                    k += 2
                    continue
                if c == quote:
                    quote = None
            elif c in ("'", '"', "`"):
                quote = c
            elif line.startswith("//", k):
                line = line[:k]
                break
            k += 1
        out.append(line)
    return "\n".join(out)


def parse_tab_ids(src: str) -> list[str]:
    """``const TAB_IDS: Tab[] = [...]`` → ordered list of page ids."""
    body = _strip_line_comments(_block(src, "const TAB_IDS: Tab[] = [", what="TAB_IDS"))
    ids = [_unescape(m.group(1)) for m in re.finditer(_TS_STR, body)]
    if not ids:
        raise PageSourceError("TAB_IDS: no ids parsed")
    if len(set(ids)) != len(ids):
        raise PageSourceError(f"TAB_IDS: duplicate ids {sorted({i for i in ids if ids.count(i) > 1})}")
    return ids


def _ts_objects(body: str) -> list[dict[str, str]]:
    """Flat ``{ key: 'value', ... }`` object literals → dicts of their string-valued keys."""
    objs = []
    for m in re.finditer(r"\{([^{}]*)\}", _strip_line_comments(body)):
        fields = {k: _unescape(v) for k, v in re.findall(r"(\w+)\s*:\s*" + _TS_STR, m.group(1))}
        if fields:
            objs.append(fields)
    return objs


def parse_command_pages(src: str) -> list[CommandPage]:
    """``const COMMAND_PAGES: CommandPage[] = [...]`` → ordered ``CommandPage`` list."""
    body = _block(src, "const COMMAND_PAGES: CommandPage[] = [", what="COMMAND_PAGES")
    pages = []
    for o in _ts_objects(body):
        missing = {"id", "code", "label"} - o.keys()
        if missing:
            raise PageSourceError(f"COMMAND_PAGES: entry {o} lacks {sorted(missing)}")
        pages.append(CommandPage(o["id"], o["code"], o["label"], o.get("hint", "")))
    if not pages:
        raise PageSourceError("COMMAND_PAGES: no entries parsed")
    for attr in ("id", "code"):
        vals = [getattr(p, attr) for p in pages]
        if len(set(vals)) != len(vals):
            raise PageSourceError(f"COMMAND_PAGES: duplicate {attr}s")
    return pages


def parse_tab_strip(src: str) -> list[str]:
    """``const tabList = [...]`` (the page strip; index 0..8 = ALT+1..9, 9 = ALT+0) → ordered ids."""
    body = _block(src, "const tabList = [", what="tabList")
    ids = [o["id"] for o in _ts_objects(body) if "id" in o]
    if not ids:
        raise PageSourceError("tabList: no ids parsed")
    return ids


@dataclass(frozen=True)
class PageSource:
    """Everything page-list related, parsed once from ``page.tsx``."""

    tab_ids: list[str]
    command_pages: list[CommandPage]
    tab_strip: list[str]

    @property
    def by_id(self) -> dict[str, CommandPage]:
        return {p.id: p for p in self.command_pages}

    def code(self, tab: str) -> str | None:
        p = self.by_id.get(tab)
        return p.code if p else None


def load_page_source(path: Path = PAGE_TSX) -> PageSource:
    """Parse ``ui/app/page.tsx`` (raises ``PageSourceError`` / ``FileNotFoundError``)."""
    src = path.read_text(encoding="utf-8")
    return PageSource(parse_tab_ids(src), parse_command_pages(src), parse_tab_strip(src))


# ── Rust Go-menu copy (desktop/src-tauri/src/pages.rs, D2) ─────────────────────────────────────────

def parse_rust_pages(src: str) -> list[CommandPage]:
    """Parse the Rust page table.

    Accepted shapes (first match wins; both are "a simple const array"):

    * tuples of string literals, at least ``(id, code, label)``: ``("brief", "BRF", "Morning brief")``
    * struct literals with named fields: ``Page { id: "brief", code: "BRF", label: "Morning brief", .. }``
    """
    text = _strip_line_comments(re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL))
    structs = []
    for m in re.finditer(r"\b[A-Z]\w*\s*\{([^{}]*)\}", text):
        fields = {k: _unescape(v) for k, v in re.findall(r"(\w+)\s*:\s*" + _RS_STR, m.group(1))}
        if {"id", "code", "label"} <= fields.keys():
            structs.append(CommandPage(fields["id"], fields["code"], fields["label"], fields.get("hint", "")))
    if structs:
        return structs
    tuples = []
    for m in re.finditer(r"\(\s*" + _RS_STR + r"\s*,\s*" + _RS_STR + r"\s*,\s*" + _RS_STR, text):
        tuples.append(CommandPage(_unescape(m.group(1)), _unescape(m.group(2)), _unescape(m.group(3))))
    if not tuples:
        raise PageSourceError("pages.rs: no (id, code, label) entries parsed")
    return tuples


def parse_rust_shortcuts(src: str) -> list[str] | None:
    """Optional ⌘1–⌘9 table in pages.rs: a const whose name contains SHORTCUT/HOTKEY/DIGIT holding page ids.

    Returns ``None`` when no such const exists (the shell may derive shortcuts from the page table).
    """
    text = _strip_line_comments(src)
    m = re.search(r"const\s+\w*(?:SHORTCUT|HOTKEY|DIGIT|CMD_NUM)\w*\s*:[^=]*=\s*&?\[", text)
    if not m:
        return None
    end = text.find("]", m.end())
    if end < 0:
        raise PageSourceError("pages.rs: unterminated shortcut array")
    return [_unescape(s) for s in re.findall(_RS_STR, text[m.end():end])]
